"""SOL 144 divergence solvers (P13/DEF-R1 split from sol144.py).

The restrained-l-set divergence eigenproblem: the single critical dynamic
pressure used by the trim result, the lowest-N-roots QZ sweep, and the
DIVERG-card multi-Mach entry point ``run_sol144_diverg`` (Step 55).
All names remain importable from ``sbeam.solver.sol144`` (facade).
"""

from typing import Optional, Tuple, cast

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.reduction import reduce_to_aset, expand_to_g
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa
from sbeam.model.aero import require_aeros
from sbeam.results.results import Sol144DivergResult, DivergMachResult, DivergRoot
from sbeam.solver.sol144_util import AeroCache, get_suport_local
from sbeam.types import ComplexArray, FloatArray


def divergence_dynamic_pressure(K_ll: FloatArray, Q_ll: FloatArray) -> Optional[float]:
    """Critical static-aeroelastic divergence dynamic pressure (restrained l-set).

    Divergence occurs when the effective stiffness ``K_ll - q*Q_ll`` first becomes
    singular, i.e. ``K_ll x = q*Q_ll x``.  Rewriting as the standard eigenproblem
    ``(K_ll^{-1} Q_ll) x = (1/q) x``, the eigenvalues are ``1/q``; the lowest
    positive divergence pressure is the reciprocal of the largest positive real
    eigenvalue.  The restrained l-set (SUPORT DOFs removed) is used because the
    full a-set ``K_aa`` is singular for the free-flight SUPORT model.

    This is the single critical divergence pressure derived from the trim
    matrices.  A user-driven DIVERG-card q-sweep is a separate item (Step 55).

    Returns:
        Lowest positive divergence dynamic pressure, or None if the model does
        not diverge (no positive real eigenvalue — e.g. a stiffening surface).
    """
    if K_ll.size == 0:
        return None
    try:
        M = scipy.linalg.solve(K_ll, Q_ll)        # K_ll^{-1} Q_ll
        eigvals = scipy.linalg.eigvals(M)
    except Exception:
        return None
    # Keep eigenvalues that are real and positive (1/q must be a positive real).
    real_pos = [ev.real for ev in eigvals
                if abs(ev.imag) < 1e-8 * max(1.0, abs(ev.real)) and ev.real > 1e-12]
    if not real_pos:
        return None
    return float(1.0 / max(real_pos))


def divergence_roots(
    K_ll: FloatArray, Q_ll: FloatArray, nroots: int
) -> list[tuple[float, FloatArray]]:
    """Lowest ``nroots`` positive divergence roots and their eigenvectors.

    Generalises ``divergence_dynamic_pressure`` from the single critical q to a
    full sorted sweep: solves ``K_ll x = q*Q_ll x`` as the standard eigenproblem
    ``(K_ll^{-1} Q_ll) x = (1/q) x`` via a dense ``scipy.linalg.eig`` on the
    restrained l-set, keeps the real-positive ``1/q`` eigenvalues, and returns
    them ordered by ascending divergence pressure.

    Selection rule (Risk KC3): the unsymmetric ``Q_ll`` can produce spurious
    negative or complex eigenvalues; only real, strictly positive ``1/q`` are
    physical divergence roots, so those are filtered and the rest discarded.

    Returns:
        list of (q_div, eigvec_l) tuples, length <= nroots, sorted by q_div.
        eigvec_l is the (n_l,) l-set divergence mode shape (real part).
    """
    if K_ll.size == 0:
        return []
    try:
        M = scipy.linalg.solve(K_ll, Q_ll)        # K_ll^{-1} Q_ll
        # scipy.linalg.eig is overloaded on left=/right=; with the defaults it
        # returns exactly the (eigenvalues, right eigenvectors) pair.
        eigvals, eigvecs = cast(
            Tuple[ComplexArray, ComplexArray], scipy.linalg.eig(M))
    except Exception:
        return []
    roots: list[tuple[float, FloatArray]] = []
    for ev, vec in zip(eigvals, eigvecs.T):
        if abs(ev.imag) < 1e-8 * max(1.0, abs(ev.real)) and ev.real > 1e-12:
            roots.append((float(1.0 / ev.real), vec.real.copy()))
    roots.sort(key=lambda t: t[0])
    return roots[:nroots]


def run_sol144_diverg(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional["AeroCache"] = None,
) -> Sol144DivergResult:
    """SOL 144 DIVERG-card aeroelastic divergence sweep (Step 55).

    Solves the restrained-l-set divergence eigenproblem ``K_ll φ = q·Q_ll φ`` for
    the lowest ``NROOTS`` positive divergence dynamic pressures and their mode
    shapes, at each Mach listed on the ``DIVERG`` card.  Divergence depends only
    on ``K_aa`` and ``Q_aa`` (no trim RHS), so no TRIM card is required.

    With the sbeam-extension ``RHOREF`` density on the DIVERG card, each root is
    mapped to a divergence speed ``V_div = sqrt(2·q_div/ρ)``.

    Args:
        bulk:       Parsed BulkData — must include a SUPORT card and the DIVERG
                    card referenced by ``subcase.diverg_sid``.
        subcase:    SubcaseControl with ``diverg_sid`` set.
        aero:       Prebuilt AeroModel (seeds the AeroCache for the sweep Machs).
        aero_cache: Optional shared AeroCache so multi-Mach sweeps build each AIC
                    once.  When None a local cache seeded with ``aero`` is used.

    Returns:
        Sol144DivergResult with the per-Mach root/mode-shape sweep.

    Raises:
        ValueError if no SUPORT card or the DIVERG SID is not found.
    """
    if not bulk.supports:
        raise ValueError("run_sol144_diverg: no SUPORT card found in model")

    diverg_sid = subcase.diverg_sid
    if diverg_sid is None or diverg_sid not in bulk.divergs:
        raise ValueError(f"run_sol144_diverg: DIVERG SID {diverg_sid} not found")
    diverg = bulk.divergs[diverg_sid]

    grid_index = build_grid_index(bulk)
    spc_sid = subcase.spc_sid

    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)

    # Mach list: the DIVERG card's, else the seed/AEROS Mach (single point).
    aeros_mach = require_aeros(bulk).mach if bulk.aeros else 0.0
    machs = diverg.machs if diverg.machs else [aeros_mach]

    # ------------------------------------------------------------------ #
    # Mach-independent structural reduction: a-set partition + K_aa + l-set.
    # ------------------------------------------------------------------ #
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    T, free_local, free_dofs = red.T, red.free_local, red.free_dofs
    n_red = red.n_red

    K_gg = assemble_global_stiffness(bulk)
    K_aa = red.reduce_matrix(K_gg, dense=True)

    # Restrained l-set: drop SUPORT DOFs (full a-set K_aa is singular for the
    # free-flight SUPORT model — same restraint the single-q path uses).
    suport_local = get_suport_local(bulk, free_dofs, grid_index)
    r_idx = list(suport_local)
    l_idx = [i for i in range(K_aa.shape[0]) if i not in set(r_idx)]
    K_ll = K_aa[np.ix_(l_idx, l_idx)]

    rho = diverg.rhoref

    mach_results = []
    for mach in machs:
        aero_m = aero_cache.get(mach)
        Q_gg = build_qaa(aero_m, aero_m.require_g_load(), aero_m.require_g_slope())
        Q_aa = red.reduce_matrix(Q_gg)
        Q_ll = Q_aa[np.ix_(l_idx, l_idx)]

        roots = []
        for q_div, vec_l in divergence_roots(K_ll, Q_ll, diverg.nroots):
            # Scatter l-set eigenvector to a-set, expand to g-set (RBAR/RBE3),
            # then max-abs normalise for a readable mode-shape report.
            u_a = np.zeros(K_aa.shape[0])
            for li_idx, li in enumerate(l_idx):
                u_a[li] = vec_l[li_idx]
            mode_g = expand_to_g(u_a, T, free_local, n_red)
            peak = np.max(np.abs(mode_g))
            if peak > 0.0:
                mode_g = mode_g / peak
            v_div = float(np.sqrt(2.0 * q_div / rho)) if rho > 0.0 else None
            roots.append(DivergRoot(q_div=q_div, v_div=v_div, mode_shape=mode_g))

        mach_results.append(DivergMachResult(mach=float(mach), roots=roots))

    return Sol144DivergResult(
        subcase_id=subcase.subcase_id,
        diverg_sid=diverg_sid,
        nroots=diverg.nroots,
        rhoref=rho,
        mach_results=mach_results,
    )


