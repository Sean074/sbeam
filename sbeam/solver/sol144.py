"""SOL 144 static aeroelastic solver — Steps 50 and 52.

Assembles the flexible aerodynamic stiffness Q_aa on the structural a-set and
solves (K_aa - q*Q_aa)*u_a = q*f_g for a given dynamic pressure, without trim
variables (Step 52 adds those).

Matrix chain (theory docs/20_theory/01_aeroelastics_theory.md Eq. 2, 22a):
    Q_aa  = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope       (n_g, n_g)
    f_g   = G_disp^T  S_kj  (A_jj*)^-1  w_g                  (n_g,)
    Q_hh  = Phi^T  Q_aa  Phi                                  (n_m, n_m)

Governing equation (a-set, Step 50 — no trim variables):
    (K_aa - q * Q_aa) * u_a  =  q * f_g  +  f_struct

Public API:
    run_aeroelastic_static(bulk, subcase, aero, q, use_rom, sol103_result)
"""

import warnings
from typing import Any, Optional, Tuple, cast

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.reduction import reduce_to_aset, expand_to_g
from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.aero.integration import build_djx
from sbeam.results.results import (
    Sol144Result, Sol144TrimResult,
    Sol144DivergResult, DivergMachResult, DivergRoot,
)
from sbeam.linalg_utils import estimate_cond_1norm
from sbeam.results.monitor_points import compute_monitor_loads
from sbeam.results.section_cuts import compute_section_cuts
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses, recover_reactions
from sbeam.solver.sol103 import run_sol103
from sbeam.results.results import Sol103Result
from sbeam.types import ComplexArray, FloatArray, LuFactor
from sbeam.aero.panel import AeroBox
from sbeam.model.aero import Trimcon, Trimobj, Trimvar, require_aeros


class AeroCache:
    """Mach-keyed cache of AeroModels for multi-Mach SOL 144 (AE9).

    The VLM AIC depends on Mach (Prandtl–Glauert / Göthert β scaling), so each
    TRIM subcase at a distinct Mach needs its own AeroModel.  Building the AIC is
    the expensive step, so models are memoized by Mach (rounded to 6 dp) and the
    build-once fixture pattern still holds across subcases at the same Mach.

    The cache is seeded with a prebuilt AeroModel so existing callers that pass a
    model built at ``AEROS.mach`` incur no rebuild when ``TRIM.mach`` matches.
    """

    _MACH_DP = 6

    def __init__(self, bulk: BulkData, grid_index: dict[int, int], seed: Optional[AeroModel] = None):
        self.bulk = bulk
        self.grid_index = grid_index
        self._cache: dict[float, AeroModel] = {}
        if seed is not None:
            self._cache[round(float(seed.mach), self._MACH_DP)] = seed

    def get(self, mach: float) -> AeroModel:
        """Return the AeroModel for ``mach``, building and memoizing on a miss."""
        key = round(float(mach), self._MACH_DP)
        model = self._cache.get(key)
        if model is None:
            model = build_aero_model(self.bulk, grid_index=self.grid_index, mach=mach)
            self._cache[key] = model
        return model


def _build_qaa_aset(
    bulk: BulkData,
    aero: AeroModel,
    grid_index: dict[int, int],
    spc_sid: Optional[int],
    f_g_full: Optional[FloatArray] = None,
) -> tuple[FloatArray, FloatArray, Optional[FloatArray], list[int]]:
    """Reduce the g-set Q_aa and K_aa to the SPC-free a-set.

    Applies the same RBE3-then-SPC reduction as sol101.py so that the a-set
    indices are identical to those used in the static and modal solvers.

    Args:
        bulk:       Parsed BulkData.
        aero:       AeroModel with g_slope and g_disp populated.
        grid_index: {gid: i} mapping from build_grid_index.
        spc_sid:    SPC set ID (may be None — no SPCs applied when None).
        f_g_full:   Optional full g-set load vector (n_g,) to reduce alongside
                    K and Q.  When supplied the returned f_aa is on the a-set;
                    otherwise None is returned.

    Returns:
        (Q_aa, K_aa, f_aa, free_dofs) where:
          Q_aa      — dense (n_a, n_a) aero stiffness on the free a-set
          K_aa      — dense (n_a, n_a) structural stiffness on the free a-set
          f_aa      — (n_a,) load vector on the a-set, or None if not supplied
          free_dofs — list[int] of g-set DOF indices for the a-set rows/cols

    Raises:
        ValueError if aero.g_slope or aero.g_disp is None.
    """
    if aero.g_slope is None or aero.g_disp is None:
        raise ValueError(
            "_build_qaa_aset: aero.g_slope and aero.g_disp must be populated. "
            "Call build_aero_model with a grid_index argument."
        )

    # --- g-set matrices ---
    Q_gg = build_qaa(aero, aero.require_g_load(), aero.require_g_slope())     # (n_g, n_g) dense
    K_gg = assemble_global_stiffness(bulk)                  # (n_g, n_g) sparse CSR

    # --- RBE3/RBAR-then-SPC reduction (shared path, Step 59) ---
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    K_aa = red.reduce_matrix(K_gg, dense=True)      # (n_a, n_a) dense system
    Q_aa = red.reduce_matrix(Q_gg)                  # (n_a, n_a)
    f_aa = red.reduce_vector(f_g_full) if f_g_full is not None else None

    return Q_aa, K_aa, f_aa, red.free_dofs


def _solve_direct(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    free_dofs: list[int],
    n_dofs: int,
) -> tuple[FloatArray, FloatArray, LuFactor]:
    """Dense direct solve of (K_aa - q*Q_aa)*u_a = f_aa.

    Returns:
        (displacements, K_eff, k_aa_lu) where:
          displacements — full g-set vector (n_dofs,); SPC DOFs zero
          K_eff         — (n_a, n_a) effective stiffness K_aa - q*Q_aa
          k_aa_lu       — (lu, piv) from lu_factor(K_aa); reused by mode-
                          acceleration recovery and Step 52
    """
    K_eff = K_aa - q * Q_aa
    k_aa_lu = scipy.linalg.lu_factor(K_aa)

    # Factor K_eff once (DEF-R6): gecon 1-norm condition estimate replaces the
    # former full-SVD np.linalg.cond, and the same LU serves the solve below.
    try:
        cond, keff_lu = estimate_cond_1norm(K_eff)
    except Exception:
        cond, keff_lu = np.inf, None
    if keff_lu is None or cond > 1e15:
        raise ValueError(
            "Singular effective aeroelastic stiffness (K_aa - q*Q_aa): "
            "model may be at or beyond divergence dynamic pressure."
        )

    u_free = scipy.linalg.lu_solve(keff_lu, f_aa)

    displacements = np.zeros(n_dofs)
    for local_idx, g_dof in enumerate(free_dofs):
        displacements[g_dof] = u_free[local_idx]

    return displacements, K_eff, k_aa_lu


def _solve_rom(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    phi_free: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Modal-truncation ROM solve of the reduced system.

    Forms the (n_m, n_m) reduced system:
        (K_hh - q * Q_hh) * xi = Phi^T * f_aa
    where K_hh = Phi^T K_aa Phi  and  Q_hh = Phi^T Q_aa Phi (via build_gaf).

    Args:
        phi_free: (n_a, n_modes) mode matrix on the a-set.

    Returns:
        (xi, k_hh, q_hh):
          xi    — (n_modes,) modal amplitudes
          k_hh  — (n_modes, n_modes) modal structural stiffness
          q_hh  — (n_modes, n_modes) modal GAF
    """
    k_hh = phi_free.T @ K_aa @ phi_free         # (n_m, n_m)
    q_hh = build_gaf(Q_aa, phi_free)            # (n_m, n_m) — reuses coupling.py
    K_eff_hh = k_hh - q * q_hh
    f_hh = phi_free.T @ f_aa                    # (n_m,) modal RHS
    xi = scipy.linalg.solve(K_eff_hh, f_hh)
    return xi, k_hh, q_hh


def _mode_acceleration_recovery(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    phi_free: FloatArray,
    xi: FloatArray,
    k_aa_lu: LuFactor,
) -> FloatArray:
    """Mode-acceleration corrected a-set displacement.

    Corrects the mode-displacement estimate u_md = Phi*xi by the static
    flexibility of the residual force:

        u_a = Phi*xi + K_aa^{-1} * (f_aa - (K_aa - q*Q_aa)*Phi*xi)

    The K_aa factorization is already available from _solve_direct so no
    additional factorization is required.  When all modes are retained the
    residual is zero and u_corrected == u_md exactly.

    Returns:
        u_free_corrected — (n_a,) corrected a-set displacement
    """
    u_md = phi_free @ xi                            # mode-displacement (n_a,)
    K_eff = K_aa - q * Q_aa
    residual = f_aa - K_eff @ u_md                 # static residual from truncation
    delta_u = scipy.linalg.lu_solve(k_aa_lu, residual)  # K_aa^{-1} * residual
    return u_md + delta_u


def run_aeroelastic_static(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    q: float,
    use_rom: bool = False,
    sol103_result: Optional[Sol103Result] = None,
) -> Sol144Result:
    """Solve the flexible static aeroelastic problem (Step 50 — no trim variables).

    Governing equation (a-set):
        (K_aa - q * Q_aa) * u_a  =  q * f_g  +  f_struct

    where:
      K_aa     — structural stiffness reduced to the SPC-free a-set
      Q_aa     — flexible aero stiffness assembled from coupling.build_qaa
      f_g      — baseline aero load from build_fg (camber/twist/incidence w_g)
      f_struct — structural load from the subcase LOAD set (may be zero)

    Args:
        bulk:           Parsed BulkData.
        subcase:        SubcaseControl — uses spc_sid, load_sid, method_sid.
        aero:           AeroModel with g_slope and g_disp populated (built with
                        grid_index argument to build_aero_model).
        q:              Dynamic pressure in consistent units.
        use_rom:        If True, also solve via modal-truncation ROM with
                        mode-acceleration recovery.  Requires either a
                        sol103_result or a method_sid in the subcase.
        sol103_result:  Pre-computed Sol103Result (optional).  When None and
                        use_rom=True the SOL 103 solve is run internally.

    Returns:
        Sol144Result with direct-solve displacements (and ROM outputs when
        use_rom=True).

    Raises:
        ValueError if aero.g_slope/g_disp are None, or use_rom=True but no
        EIGRL method is available.
    """
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)
    spc_sid = subcase.spc_sid
    load_sid = subcase.load_sid

    # Combine structural load and baseline aero load on the g-set
    f_struct = assemble_load_vector(bulk, load_sid) if load_sid is not None else np.zeros(n_dofs)
    f_aero_g = q * build_fg(aero, aero.require_g_load())    # (n_g,) from coupling.py
    f_g_full = f_struct + f_aero_g

    # Reduce Q_aa, K_aa, and the combined load to the a-set
    Q_aa, K_aa, f_aa, free_dofs = _build_qaa_aset(bulk, aero, grid_index, spc_sid, f_g_full)
    if f_aa is None:   # f_g_full was supplied, so _build_qaa_aset always reduces it
        raise ValueError("run_aeroelastic_static: a-set load vector was not built")

    # Direct solve
    displacements, _K_eff, k_aa_lu = _solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_dofs)

    # --- Modal ROM path (optional) ---
    modal_coords = phi_free = k_hh = q_hh = None
    if use_rom:
        if sol103_result is None:
            if subcase.method_sid is None:
                raise ValueError(
                    "run_aeroelastic_static: use_rom=True requires either a "
                    "pre-computed sol103_result or a METHOD (EIGRL) set ID in the subcase."
                )
            sol103_result = run_sol103(bulk, subcase)

        # Extract a-set mode shapes (free_dofs rows of full-DOF mode matrix)
        phi_full = sol103_result.mode_shapes       # (n_dofs, n_modes)
        phi_free = phi_full[free_dofs, :]          # (n_a, n_modes)

        xi, k_hh, q_hh = _solve_rom(K_aa, Q_aa, f_aa, q, phi_free)
        u_free_corrected = _mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)

        modal_coords = xi
        # Scatter mode-acceleration corrected a-set back to full DOF vector
        displacements = np.zeros(n_dofs)
        for local_idx, g_dof in enumerate(free_dofs):
            displacements[g_dof] = u_free_corrected[local_idx]

    # CBAR force and stress recovery (reuses sol101 functions unchanged)
    bar_forces = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid] = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )

    return Sol144Result(
        displacements=displacements,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        q_aa=Q_aa,
        q=q,
        free_dofs=free_dofs,
        k_aa_lu=k_aa_lu,
        modal_coords=modal_coords,
        phi_free=phi_free,
        k_hh=k_hh,
        q_hh=q_hh,
    )


# ---------------------------------------------------------------------------
# Step 52 — SOL 144 Trim Solver
# ---------------------------------------------------------------------------

def urdd_rcsid_to_basic(
    vec: FloatArray, label_to_col: dict[str, int], R_rcsid: FloatArray, has_rcsid: bool
) -> FloatArray:
    """Rotate the URDD translational/rotational triples of a label-ordered trim
    vector from the RCSID frame into the basic CID 0 frame (AE5).

    ``vec`` is ordered by ``all_labels``; ``label_to_col`` maps each label to its
    index.  Non-URDD entries (aero labels) pass through unchanged.  Absent URDD
    components are treated as zero in the rotation, then only the present ones are
    written back.  Returns a copy; the input is not mutated.
    """
    out = vec.copy()
    if not has_rcsid:
        return out
    for triple_lbls in (['URDD1', 'URDD2', 'URDD3'], ['URDD4', 'URDD5', 'URDD6']):
        present = {l: label_to_col[l] for l in triple_lbls if l in label_to_col}
        if not present:
            continue
        triple = np.array([
            out[label_to_col[l]] if l in label_to_col else 0.0 for l in triple_lbls
        ])
        triple_basic = R_rcsid @ triple
        for i, lbl in enumerate(triple_lbls):
            if lbl in present:
                out[present[lbl]] = triple_basic[i]
    return out


def urdd_basic_to_rcsid(
    vec: FloatArray, label_to_col: dict[str, int], R_rcsid: FloatArray, has_rcsid: bool
) -> FloatArray:
    """Inverse of ``urdd_rcsid_to_basic``: rotate the URDD triples of a
    label-ordered vector from the basic CID 0 frame into the RCSID frame.

    Same conventions: non-URDD entries pass through, absent URDD components are
    treated as zero in the rotation, only present ones are written back, and a
    copy is returned.  Used by the Step 63 free-flight recovery to express the
    basic-frame ``ξ̈_r`` accelerations as URDD label values.

    If the rotation puts non-negligible content onto an absent URDD component
    (no AESTAT label to carry it), a ``UserWarning`` names the component — the
    dropped content would silently vanish from the label bookkeeping.
    """
    out = vec.copy()
    if not has_rcsid:
        return out
    R_inv = R_rcsid.T
    for triple_lbls in (['URDD1', 'URDD2', 'URDD3'], ['URDD4', 'URDD5', 'URDD6']):
        present = {l: label_to_col[l] for l in triple_lbls if l in label_to_col}
        if not present:
            continue
        triple = np.array([
            out[label_to_col[l]] if l in label_to_col else 0.0 for l in triple_lbls
        ])
        triple_rcsid = R_inv @ triple
        scale = max(1.0, float(np.abs(triple_rcsid).max()))
        for i, lbl in enumerate(triple_lbls):
            if lbl in present:
                out[present[lbl]] = triple_rcsid[i]
            elif abs(triple_rcsid[i]) > 1e-10 * scale:
                warnings.warn(
                    f"urdd_basic_to_rcsid: the RCSID rotation places "
                    f"{triple_rcsid[i]:.4g} on {lbl}, which has no AESTAT "
                    "label — that acceleration component is dropped from the "
                    "URDD bookkeeping.",
                    UserWarning,
                )
    return out


def load_resultant(
    loads_g: FloatArray, bulk: BulkData, grid_index: dict[int, int], ref_pos: FloatArray
) -> FloatArray:
    """Body-frame 6-component resultant (Fx,Fy,Fz, Mx,My,Mz) of a g-set load
    vector about ``ref_pos``, summed over all grids.

    Moments are taken about the (undeformed) grid positions in the basic CID 0
    frame — the small-deflection convention used throughout the trim path.
    """
    F = np.zeros(3)
    M = np.zeros(3)
    for gid, gi in grid_index.items():
        f = loads_g[gi * 6: gi * 6 + 3]
        m = loads_g[gi * 6 + 3: gi * 6 + 6]
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z]) - ref_pos
        F += f
        M += m + np.cross(r, f)
    return np.concatenate([F, M])


#: URDD label -> rigid DOF component (1-6).  URDD1-3 are translational
#: accelerations along basic x/y/z; URDD4-6 are angular accelerations about
#: basic x/y/z, referred to ``suport_pos``.
_URDD_DOF = {f"URDD{d}": d for d in range(1, 7)}


def build_inertial_cols(
    bulk: BulkData,
    all_labels: list[str],
    grid_index: dict[int, int],
    suport_pos: FloatArray,
    massset_sid: Optional[int] = None,
    M_gg: Optional[Any] = None,
) -> FloatArray:
    """Inertial sensitivity matrix M_ax on the full g-set — basic frame.

    Returns (n_g, n_labels) where column k is dF/dURDD_k (force per unit
    acceleration for URDD labels; zero for aerodynamic labels).  All values
    are expressed in the basic CID 0 frame; RCSID-frame URDD values must be
    transformed to basic before multiplying.

    Definition — one mass model (Q4 / DEF-M3)
    -----------------------------------------
    A unit URDD_k is, by definition, a unit rigid-body acceleration of the whole
    airframe about ``suport_pos``.  The d'Alembert load it induces is therefore

        M_ax[:, k] = -M_gg @ phi_r_g[:, dof(k)]

    with ``phi_r_g`` the geometric rigid-body vectors from
    ``assembly.rigid_body.build_rigid_vectors_g`` and ``M_gg`` the *same*
    consistent mass matrix the elastic equations use.  This is not an
    approximation of the inertia model — it *is* the inertia model, so
    ``M_ax = -M_aa Phi_r`` holds column for column on the a-set as an identity
    (``red.reduce_rect`` is ``T^T .`` and ``T Phi_r_a = Phi_r_g``).

    Before this was unified, M_ax was a hand-rolled *lumped* model that read
    ``conm2.m`` and the diagonal ``i11/i22/i33`` in the basic frame only.  It
    silently dropped CONM2 offset transport, products of inertia, CONM2 CID
    rotation and PBAR ``nsm``, and mixed lumped CBAR half-masses with the
    consistent ``M_aa`` — all of which ``assemble_global_mass`` handles and all
    of which now come along for free.

    Args:
        bulk:        parsed model.
        all_labels:  trim labels, in column order.
        grid_index:  {gid: i} — must be the g-set ordering ``M_gg`` was built on.
        suport_pos:  rigid-acceleration reference point, basic coordinates.
        massset_sid: MASSSET mass case (Step 60); ignored when ``M_gg`` is given.
        M_gg:        pre-assembled global mass matrix for this mass case.  Pass
                     it when the caller already has one — it is the single most
                     expensive object here.  When ``None`` it is assembled from
                     ``bulk``/``massset_sid``.

    Raises:
        ValueError: if a supplied ``M_gg`` does not match the g-set size.
    """
    from sbeam.assembly.mass_matrix import assemble_global_mass
    from sbeam.assembly.rigid_body import build_rigid_vectors_g

    n_g = 6 * len(grid_index)
    M = np.zeros((n_g, len(all_labels)))

    # {rigid DOF -> column} for the URDD labels actually present.
    urdd_cols: dict[int, int] = {}
    for col, label in enumerate(all_labels):
        dof = _URDD_DOF.get(label.upper())
        if dof is not None:
            urdd_cols[dof] = col
    if not urdd_cols:
        return M            # aerodynamic labels only — M_ax is identically zero

    if M_gg is None:
        M_gg = assemble_global_mass(bulk, massset_sid)
    elif M_gg.shape != (n_g, n_g):
        raise ValueError(
            f"build_inertial_cols: supplied M_gg is {M_gg.shape[0]}x"
            f"{M_gg.shape[1]} but the g-set has {n_g} DOFs — the mass matrix "
            "and grid_index must come from the same model."
        )

    dofs = sorted(urdd_cols)
    phi_r_g = build_rigid_vectors_g(bulk, grid_index, dofs, suport_pos)
    cols = -np.asarray(M_gg @ phi_r_g)          # (n_g, n_dofs)

    for k, dof in enumerate(dofs):
        M[:, urdd_cols[dof]] = cols[:, k]
    return M


# Moved to assembly.reduction (Step 59); alias retained for existing importers.
_expand_to_g = expand_to_g


def get_suport_local(
    bulk: BulkData, free_dofs: list[int], grid_index: dict[int, int]
) -> list[int]:
    """Return local a-set indices corresponding to SUPORT DOFs.

    Uses bulk.supports (list[Suport]).  DOF string "35" means Tz (3) and Ry (5).
    """
    g_to_local = {g_dof: loc for loc, g_dof in enumerate(free_dofs)}
    suport_local = []
    for sup in bulk.supports:
        if sup.gid not in grid_index:
            continue
        base = grid_index[sup.gid] * 6
        for ch in sup.dofs:
            g_dof = base + (int(ch) - 1)
            if g_dof in g_to_local:
                suport_local.append(g_to_local[g_dof])
    return suport_local


def _build_trim_schur(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_label_cols: list[int],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int], FloatArray, FloatArray]:
    """Build the trim-equilibrium operator shared by the determined and
    over-determined solves.

    Partitions K_eff = K_aa - q*Q_aa into l-set (non-SUPORT) and r-set (SUPORT).
    With u_r = 0, the r-set equilibrium is the trim equation in the free trim
    variables δ_free:

        schur_A @ delta_free = schur_b
        schur_A = K_rl @ K_ll^{-1} @ C_ax_l - C_ax_r          (n_r, n_free)
        schur_b = f_rhs_r - K_rl @ K_ll^{-1} @ f_rhs_l        (n_r,)

    where C_ax = q*Q_ax_a + M_ax_a is the combined aero + inertial sensitivity.

    Returns:
        (schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l)
    """
    n_a = K_aa.shape[0]
    r_idx = list(suport_local)
    l_idx = [i for i in range(n_a) if i not in set(r_idx)]

    K_eff = K_aa - q * Q_aa
    K_ll = K_eff[np.ix_(l_idx, l_idx)]
    K_rl = K_eff[np.ix_(r_idx, l_idx)]

    # Combined aero + inertial sensitivity for free columns only
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, free_label_cols)]
              + M_ax_a[np.ix_(l_idx, free_label_cols)])  # (n_l, n_free)
    C_ax_r = (q * Q_ax_a[np.ix_(r_idx, free_label_cols)]
              + M_ax_a[np.ix_(r_idx, free_label_cols)])  # (n_r, n_free)

    f_rhs_l = f_rhs_a[l_idx]
    f_rhs_r = f_rhs_a[r_idx]

    K_ll_lu = scipy.linalg.lu_factor(K_ll)

    Kinv_f = scipy.linalg.lu_solve(K_ll_lu, f_rhs_l)            # (n_l,)
    Kinv_C = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)             # (n_l, n_free)

    schur_A = K_rl @ Kinv_C - C_ax_r                            # (n_r, n_free)
    schur_b = f_rhs_r - K_rl @ Kinv_f                           # (n_r,)

    return schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l


def _recover_u_a(
    K_ll_lu: LuFactor,
    C_ax_l: FloatArray,
    f_rhs_l: FloatArray,
    delta_free_arr: FloatArray,
    l_idx: list[int],
    n_a: int,
) -> FloatArray:
    """Recover the a-set displacement from the trimmed free variables (u_r = 0)."""
    u_l = scipy.linalg.lu_solve(K_ll_lu, C_ax_l @ delta_free_arr + f_rhs_l)
    u_a = np.zeros(n_a)
    for li, val in zip(l_idx, u_l):
        u_a[li] = val
    return u_a


def _solve_trim_determined(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_label_cols: list[int],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int]]:
    """Schur-complement trim solve for the determined case (n_free == n_suport).

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    n_a = K_aa.shape[0]
    schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l = _build_trim_schur(
        K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q, suport_local, free_label_cols)

    delta_free_arr = scipy.linalg.solve(schur_A, schur_b)        # (n_free,)

    u_a = _recover_u_a(K_ll_lu, C_ax_l, f_rhs_l, delta_free_arr, l_idx, n_a)
    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


def _solve_trim_overdetermined(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_labels: list[str],
    free_label_cols: list[int],
    trimobj: Optional[Trimobj],
    trimcons: list[Trimcon],
    trimvars: dict[int, Trimvar],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int]]:
    """Over-determined trim solve (n_free > n_suport): redundant controls.

    The trim equilibrium ``schur_A @ δ = schur_b`` is ``n_suport`` equations in
    ``n_free`` unknowns (under-determined as an equality system).  The solution is
    made unique by minimising the weighted-L2 ``TRIMOBJ`` objective

        min_δ  Σ_k  w_k · δ_k²        (k over TRIMOBJ labels; w_k its weight)

    subject to
        * equality:   schur_A @ δ = schur_b          (trim equilibrium),
        * inequality: TRIMCON  (δ_label ≤ rhs  or  δ_label ≥ rhs),
        * bounds:     TRIMVAR  lb ≤ δ_label ≤ ub.

    The equilibrium equality is eliminated by a **null-space reduction** rather
    than handed to the optimiser as a stiff constraint: ``schur_A`` carries
    structural-force magnitudes O(10³) that swamp the O(0.1) trim variables and
    defeat SLSQP's line search.  Writing

        δ = δ_p + N · z          (δ_p = least-norm equilibrium solution,
                                  N = null(schur_A), so schur_A·δ ≡ schur_b)

    turns the problem into a small, well-scaled convex QP in the redundancy
    coordinate ``z`` with only the TRIMCON/TRIMVAR bounds (now linear in ``z``).
    The convex objective makes the optimum initial-guess insensitive (KC6); the
    TRIMVAR ``init`` only seeds the warm start.

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    import scipy.optimize

    n_a = K_aa.shape[0]
    n_free = len(free_labels)
    schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l = _build_trim_schur(
        K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q, suport_local, free_label_cols)

    label_to_idx = {lbl: i for i, lbl in enumerate(free_labels)}

    # Weighted-L2 objective from TRIMOBJ (default weight 1.0 on every free var
    # when no TRIMOBJ label matches, so the solve is always well-posed).
    weights = np.ones(n_free)
    if trimobj is not None and trimobj.labels:
        w_obj = np.zeros(n_free)
        matched = False
        for lbl, w in zip(trimobj.labels, trimobj.weights):
            if lbl in label_to_idx:
                w_obj[label_to_idx[lbl]] = w
                matched = True
        if matched:
            weights = w_obj

    # Particular (least-norm) equilibrium solution and the null-space basis.
    delta_p, *_ = np.linalg.lstsq(schur_A, schur_b, rcond=None)
    _u, sv, vt = np.linalg.svd(schur_A)
    tol = max(schur_A.shape) * np.finfo(float).eps * (sv[0] if sv.size else 0.0)
    rank = int((sv > tol).sum())
    N = vt[rank:].T.conj()                      # (n_free, n_free - rank)
    nz = N.shape[1]

    # TRIMVAR bounds and per-variable initial guess (defaults: unbounded, 0).
    lb = np.full(n_free, -np.inf)
    ub = np.full(n_free, np.inf)
    delta_init = np.zeros(n_free)
    for tv in (trimvars or {}).values():
        if tv.label in label_to_idx:
            i = label_to_idx[tv.label]
            lb[i] = tv.lb
            ub[i] = tv.ub
            delta_init[i] = tv.init

    if nz == 0:
        # No redundancy left after the equilibrium constraint — δ is determined.
        delta_free_arr = delta_p
    else:
        def objective(z: FloatArray) -> float:
            d = delta_p + N @ z
            return float(np.sum(weights * d * d))

        def objective_grad(z: FloatArray) -> FloatArray:
            d = delta_p + N @ z
            return 2.0 * (N.T @ (weights * d))

        constraints = []
        # TRIMCON inequalities (linear in z).
        for tc in (trimcons or []):
            if tc.label not in label_to_idx:
                continue
            i = label_to_idx[tc.label]
            if tc.sense == "LE":      # δ_i ≤ rhs  →  rhs − δ_i ≥ 0
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i, r=tc.rhs: r - (delta_p[i] + N[i] @ z)),
                    'jac': (lambda z, i=i: -N[i]),
                })
            else:                     # GE: δ_i ≥ rhs  →  δ_i − rhs ≥ 0
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i, r=tc.rhs: (delta_p[i] + N[i] @ z) - r),
                    'jac': (lambda z, i=i: N[i]),
                })
        # TRIMVAR bounds → linear inequalities in z.
        for i in range(n_free):
            if np.isfinite(ub[i]):
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i: ub[i] - (delta_p[i] + N[i] @ z)),
                    'jac': (lambda z, i=i: -N[i]),
                })
            if np.isfinite(lb[i]):
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i: (delta_p[i] + N[i] @ z) - lb[i]),
                    'jac': (lambda z, i=i: N[i]),
                })

        # Warm start: project the TRIMVAR init guess onto the redundancy space.
        z0, *_ = np.linalg.lstsq(N, delta_init - delta_p, rcond=None)
        res = scipy.optimize.minimize(
            objective, z0, jac=objective_grad, method='SLSQP',
            constraints=constraints, options={'ftol': 1e-14, 'maxiter': 500},
        )
        if not res.success:
            raise ValueError(
                "Over-determined trim could not satisfy the TRIMCON/TRIMVAR "
                f"bounds: {res.message}")
        delta_free_arr = delta_p + N @ res.x

    u_a = _recover_u_a(K_ll_lu, C_ax_l, f_rhs_l, delta_free_arr, l_idx, n_a)
    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


def pitch_moment(f_box_vec: FloatArray, boxes: list[AeroBox], x_ref: float) -> float:
    """Nose-up-positive aerodynamic pitching moment about ``x_ref`` (AE1 Step E).

    Single source for the moment-arm convention `My = −ΣFz·(x_force − x_ref)`
    used throughout the trim chain.  The sign is nose-up positive, matching
    `solve_rigid_cl.CM` (`vlm.py`) and NASTRAN's Cm convention.  Each box load
    acts at its ¼-chord bound-vortex midpoint `box.force_point` (AE6), not the
    ¾-chord collocation point.

    Args:
        f_box_vec: (3·n_box,) per-box force vector [Fx0, Fy0, Fz0, Fx1, …] in
                   force/q units (skj @ Cp).
        boxes:     AeroBox list (provides force_point[0] moment arms).
        x_ref:     moment reference x-coordinate in basic CID 0 (RCSID origin).

    Returns:
        Pitching moment about x_ref (force/q · length units).  Full-span model,
        so this is already the whole-airplane moment (no symmetry factor).
    """
    return -sum(
        f_box_vec[3 * j + 2] * (boxes[j].force_point[0] - x_ref)
        for j in range(len(boxes))
    )


def aero_moment_resultant(
    box_forces: FloatArray, boxes: list[AeroBox], ref_point: FloatArray
) -> FloatArray:
    """Full 3-component aerodynamic moment about ``ref_point`` (Step 58).

    ``M = Σ_j (r_j − ref) × F_j`` with ``r_j = box.force_point`` (¼-chord
    bound-vortex midpoint) and ``F_j`` the per-box force.  Returns ``[Mx, My, Mz]``
    — roll, pitch, yaw — in the same frame as ``box_forces``.

    Unlike ``pitch_moment`` (the single-source nose-up-positive *pitch* arm used
    inside the trim), this is the complete resultant needed once lifting surfaces
    leave the xy-plane: a canted panel carries a side force ``Fy`` that contributes
    roll/yaw, and the moment arm has a non-zero ``z`` component.  Used by the
    V-C-DIH dihedral gate to assert residual ``Fy``/roll/yaw ≈ 0 over a symmetric
    build, and reusable by future monitor-point load integration.

    Args:
        box_forces: per-box force, shape ``(n_box, 3)`` ``[Fx, Fy, Fz]`` (any
                    consistent force units).
        boxes:      AeroBox list (provides ``force_point``).
        ref_point:  (3,) moment reference in the same CID frame as the forces.

    Returns:
        (3,) ndarray ``[Mx, My, Mz]``.
    """
    ref = np.asarray(ref_point, dtype=float)
    m = np.zeros(3)
    for j, box in enumerate(boxes):
        m += np.cross(box.force_point - ref, box_forces[j])
    return m


def _build_injection_echo(
    aero: AeroModel,
    box_forces: FloatArray,
    ref_point: FloatArray,
    bulk: BulkData,
    grid_index: dict[int, int],
    free_dofs: list[int],
) -> list[dict[str, Any]]:
    """Summarise the Step 64 load injections for the f06 (and warn on dead ends).

    For each group of structurally-uncoupled boxes (SPLINE0 body panels,
    un-splined boxes) report the master grid, the box count and the physical
    6-component resultant about ``ref_point`` that the injection puts into the
    trim balance and the load export.

    Warns when the master grid's translations are all constrained: the injected
    load is then removed by the a-set reduction and reappears as an SPC
    reaction rather than trimming the aircraft.

    Returns [] when no injection is active, so decks without body panels get a
    byte-identical f06.
    """
    echo: list[dict[str, Any]] = []
    free = set(free_dofs)
    for inj in aero.load_injections:
        idx = inj.boxes
        forces = box_forces[idx]
        sub_boxes = [aero.boxes[k] for k in idx]
        f_tot = forces.sum(axis=0)
        m_tot = aero_moment_resultant(forces, sub_boxes, ref_point)
        col = 6 * grid_index[inj.master_grid]
        if not any((col + d) in free for d in range(3)):
            warnings.warn(
                f"{inj.source}: master GRID {inj.master_grid} has all three "
                "translations constrained — the injected aerodynamic load "
                f"(F={f_tot}) is carried by the constraint, not by the trim.",
                UserWarning,
            )
        echo.append({
            'source':      inj.source,
            'master_grid': inj.master_grid,
            'n_boxes':     len(idx),
            'force':       f_tot,
            'moment':      m_tot,
        })
    return echo


def compute_rigid_derivs(
    aero: AeroModel,
    D_jx: FloatArray,
    all_labels: list[str],
    bulk: BulkData,
    x_ref: float,
    ref_pt: FloatArray,
) -> dict[str, dict[str, float]]:
    """Rigid aerodynamic stability and control derivatives.

    For each label, computes the change in total force/moment per unit label
    value without any structural deformation (u_a = 0).

    Longitudinal (single-source nose-up-positive pitch arm, AE1 Step E):
        CZ = Fz / S_ref,    CMY = My / (S_ref * c_ref)
    Lateral/directional (full 3-component resultant about ``ref_pt``, Step 52):
        CMX = Mx / (S_ref * b_ref)   — roll  (gives C_lp from ROLL, C_lβ from SIDES)
        CMZ = Mz / (S_ref * b_ref)   — yaw   (gives C_nr from YAW)

    ``CMX``/``CMZ`` use ``aero_moment_resultant`` so the roll/yaw moments carry
    the side force ``Fy`` of any canted (±Γ dihedral) panel; on a planar wing
    the roll column decouples cleanly from Fz/My (V-LAT gate).
    """
    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref

    n_box = len(aero.boxes)
    boxes = aero.boxes
    rigid_derivs: dict[str, dict[str, float]] = {}

    for col, label in enumerate(all_labels):
        # Normalwash from unit perturbation of this label alone
        w_pert = D_jx[:, col]
        gamma = aero.ajj_inv_corr @ w_pert          # (n_box,)
        f_box_vec = aero.skj @ gamma                 # (3*n_box,)

        Fz_sens = f_box_vec[2::3].sum()
        My_sens = pitch_moment(f_box_vec, boxes, x_ref)   # nose-up-positive
        Fz_x = f_box_vec[0::3].sum()
        Fz_y = f_box_vec[1::3].sum()
        Mx, _My_xp, Mz = aero_moment_resultant(
            f_box_vec.reshape(n_box, 3), boxes, ref_pt)

        rigid_derivs[label] = {
            'CZ':  Fz_sens / sref,
            'CMY': My_sens / (sref * cref),
            'CMX': Mx / (sref * bref) if bref > 0 else 0.0,
            'CMZ': Mz / (sref * bref) if bref > 0 else 0.0,
            'CX':  Fz_x / sref,
            'CY':  Fz_y / sref,
        }

    return rigid_derivs


def _compute_hinge_moments(
    aero: AeroModel,
    D_jx: FloatArray,
    all_labels: list[str],
    bulk: BulkData,
    f_box_trim: FloatArray,
) -> dict[str, dict[str, float]]:
    """Hinge-moment derivatives and trimmed hinge moment per AESURF control.

    The hinge moment is the moment of the aero box forces on a surface's AELIST
    boxes about its hinge axis ĥ (the cid1 y-axis) through the hinge origin o:

        HM = Σ_{j∈AELIST} [(r_j − o) × F_j] · ĥ          (r_j = box force point)

    Returns ``{label: {'total': HM_trim, <trim_label>: dHM/dδ, ...}}`` where each
    ``dHM/dδ`` uses the rigid box forces from that label's normalwash column
    alone (u_a = 0, force/q units), mirroring ``compute_rigid_derivs``.  The
    ``'total'`` entry uses the full trimmed box-force field ``f_box_trim``
    (force/q units; multiply by q for the physical hinge moment).
    """
    from sbeam.assembly.coord_transform import get_transform

    # NASTRAN-box-ID → global-k index — the one shared, collision-checked map (F1)
    id_to_k = aero.require_box_id_to_k()

    hinge_moments: dict[str, dict[str, float]] = {}
    for aesurf in bulk.aesurfs.values():
        aelist = bulk.aelists.get(aesurf.alid1)
        if aelist is None:
            continue
        o, R = get_transform(aesurf.cid1, bulk.cord2rs)
        h_hat = R[:, 1]                                   # hinge axis = cid1 y-axis
        ks = [id_to_k[bid] for bid in aelist.elements if bid in id_to_k]

        def _hm(f_box: FloatArray, _ks: list[int] = ks,
                _o: FloatArray = o, _h: FloatArray = h_hat) -> float:
            total = 0.0
            for k in _ks:
                F = f_box[3 * k:3 * k + 3]
                r = aero.boxes[k].force_point - _o
                total += float(np.dot(np.cross(r, F), _h))
            return total

        entry = {'total': _hm(f_box_trim)}
        for col, lbl in enumerate(all_labels):
            f_box_col = aero.skj @ (aero.ajj_inv_corr @ D_jx[:, col])
            entry[lbl] = _hm(f_box_col)
        hinge_moments[aesurf.label.upper()] = entry

    return hinge_moments


def _compute_restrained_derivs(
    K_ll_lu: LuFactor,
    l_idx: list[int],
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    all_labels: list[str],
    u_a_trim: FloatArray,
    delta_all_trim: FloatArray,
    aero: AeroModel,
    D_jx: FloatArray,
    T: FloatArray,
    free_local: list[int],
    n_red: int,
    bulk: BulkData,
    x_ref: float,
    q: float,
    ref_pt: FloatArray,
) -> dict[str, dict[str, float]]:
    """Elastic restrained stability derivatives — exact analytic form (AE1 Step G).

    Restrained means the SUPORT (r-set) DOFs are held at zero; the l-set responds
    elastically.  The trim problem is linear in each label δ, so the derivative is
    obtained directly from the Schur factorisation instead of by finite difference
    (which the prior one-pass hybrid approximated and which converged to neither
    NASTRAN's restrained nor unrestrained column — see AE8).

    For label column ``col`` with combined aero + inertial sensitivity
    ``C_ax_l = q·Q_ax_a + M_ax_a`` on the l-set:

        ∂u_l/∂δ = K_ll⁻¹ · C_ax_l[:, col]        (K_ll already carries q·Q_aa,
                                                   so this is the restrained,
                                                   aero-coupled sensitivity)
        ∂w/∂δ   = D_jx[:, col] + D_jk·G_slope·∂u/∂δ
        ∂γ/∂δ   = A_jj*⁻¹ · ∂w/∂δ
        ∂f_box/∂δ = S_kj · ∂γ/∂δ
        CZ = Σ∂Fz/∂δ / S_ref,   CMY = ∂My/∂δ / (S_ref·c_ref)

    My uses the nose-up-positive ``pitch_moment`` convention (AE1 Step E).  Each
    g-set displacement derivative is expanded through the RBE3/RBAR T matrix so
    slave DOFs move with their masters (AE1 Step B1).  The result is exact (no FD
    truncation) and the URDD/inertial columns are carried by M_ax_a.
    """
    from sbeam.aero.integration import build_djk

    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref
    djk  = build_djk(aero.boxes)
    n_a  = Q_ax_a.shape[0]
    n_box = len(aero.boxes)
    boxes = aero.boxes

    # Combined aero + inertial sensitivity on the l-set (one column per label).
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, list(range(len(all_labels))))]
              + M_ax_a[np.ix_(l_idx, list(range(len(all_labels))))])

    # ∂u_l/∂δ for every label at once: K_ll⁻¹ · C_ax_l  (n_l, n_labels)
    du_l_all = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)

    rest_derivs: dict[str, dict[str, float]] = {}
    for col, label in enumerate(all_labels):
        # Scatter the l-set sensitivity into a full a-set vector, then expand to
        # the g-set so RBAR/RBE3 slaves follow their masters.
        u_a_d = np.zeros(n_a)
        for li_idx, li in enumerate(l_idx):
            u_a_d[li] = du_l_all[li_idx, col]
        u_full_d = _expand_to_g(u_a_d, T, free_local, n_red)

        # Linear normalwash sensitivity: direct trim term + elastic feedback.
        dw = D_jx[:, col] + djk @ (aero.require_g_slope() @ u_full_d)
        dgamma = aero.ajj_inv_corr @ dw
        df_box = aero.skj @ dgamma                              # (3·n_box,) force/q

        Mx, _My_xp, Mz = aero_moment_resultant(
            df_box.reshape(n_box, 3), boxes, ref_pt)
        rest_derivs[label] = {
            'CZ':  df_box[2::3].sum() / sref,
            'CMY': pitch_moment(df_box, boxes, x_ref) / (sref * cref),
            'CMX': Mx / (sref * bref) if bref > 0 else 0.0,
            'CMZ': Mz / (sref * bref) if bref > 0 else 0.0,
        }

    return rest_derivs


def _compute_unrestrained_derivs(
    K_aa: FloatArray,
    M_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    f_aero_a: FloatArray,
    all_labels: list[str],
    l_idx: list[int],
    r_idx: list[int],
    free_dofs: list[int],
    grid_index: dict[int, int],
    bulk: BulkData,
    q: float,
    ref_pt: FloatArray,
) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Unrestrained (mean-axis / inertia-relief) stability derivatives — AE8b.

    Implements the MSC Nastran SOL 144 unrestrained-derivative algorithm
    verbatim (MSC Aeroelastic Analysis User's Guide, Static Aeroelasticity,
    Eqs. 2-111 … 2-134; DMAP matrix names kept in the comments for audit).
    Cross-checked against the ZAERO Theoretical Manual Ch. 12 modal mean-axis
    form (Eqs. 12.14–12.16).

    The unrestrained derivative is NOT the aero force integrated over a
    converged free-free aeroelastic response (both reverted AE8b attempts —
    see docs/40_history).  It is the rigid-body inertial reaction m_r·ü_r per
    unit trim variable, from a three-block system in (u_l, u_r, ü_r):

        1. l-set equilibrium:      K^a_ll·u_l + K^a_lr·u_r + (M_ll·D+M_lr)·ü_r
                                       = −K^a_lx·u_x + P_l
        2. mean-axis constraint:   (DᵀM_ll+M_rl)·u_l + (DᵀM_lr+M_rr)·u_r = 0
        3. rigid equilibrium:      Dᵀ·(row l) + (row r)

    where D = −K_ll⁻¹·K_lr (STRUCTURAL K only, Eq. 2-111) and
    K^a = K_aa − q̄·Q_aa.  u_l is eliminated through the aeroelastic K^a_ll,
    u_r through the mass-weighted mean-axis row (2-129/2-130), leaving
    MIRR·ü_r + KR1ZX·u_x = IPZF, whence Z1ZX = −m_r·MIRR⁻¹·KR1ZX (2-133).

    Note: the manual's KARZX line prints "KAZL − KAXL·ALX", which is
    dimensionally impossible (KAXL is n_r×n_x, ALX is n_l×n_x); the correct
    reading is KARZX = KAXL − KAZL·ALX.

    Only aero labels are computed (URDD acceleration columns are the ü_r
    unknowns of this formulation, handled by NASTRAN via TRX; not needed for
    the Phase C derivative deliverable).  Returns ``(derivs, intercepts)``:
    ``derivs`` shaped like ``restrained_derivs`` and ``intercepts`` holding the
    unrestrained {CZ0, CMY0} from the IPZF chain (w_g baseline).
    """
    n_r = len(r_idx)
    if n_r == 0:
        return {}, {}

    aero_cols = [c for c, lbl in enumerate(all_labels)
                 if not lbl.upper().startswith("URDD")]
    if not aero_cols:
        return {}, {}

    ll = np.ix_(l_idx, l_idx)
    lr = np.ix_(l_idx, r_idx)
    rl = np.ix_(r_idx, l_idx)
    rr = np.ix_(r_idx, r_idx)
    lx = np.ix_(l_idx, aero_cols)
    rx = np.ix_(r_idx, aero_cols)

    # Structural rigid-body modes (2-111) — STRUCTURAL K only, no aero in D.
    K_ll_s = K_aa[ll]
    K_lr_s = K_aa[lr]
    D = -scipy.linalg.lu_solve(scipy.linalg.lu_factor(K_ll_s), K_lr_s)  # (n_l, n_r)

    # The mean-axis formulation requires genuine free-flight rigid modes in the
    # SUPORT directions: K_rl·D + K_rr must vanish for a floating structure.
    res = np.linalg.norm(K_aa[rl] @ D + K_aa[rr]) / max(np.linalg.norm(K_aa), 1e-30)
    if res > 1e-8:
        warnings.warn(
            f"unrestrained derivatives skipped: SUPORT directions are not "
            f"free rigid-body modes (‖K_rl·D + K_rr‖/‖K‖ = {res:.2e}); "
            "check SPC/SUPORT consistency.", UserWarning)
        return {}, {}

    M_ll = M_aa[ll]; M_lr = M_aa[lr]; M_rl = M_aa[rl]; M_rr = M_aa[rr]
    m_r = M_rr + M_rl @ D + D.T @ M_lr + D.T @ M_ll @ D   # total rigid mass (2-114)
    MR = D.T @ M_ll + M_rl                                 # mean-axis row operator

    # Aeroelastic partitions (K^a = K − q̄·Q; K^a_ax = −q̄·Q_ax, Eq. 2-110).
    K_eff = K_aa - q * Q_aa
    Ka_ll = K_eff[ll]; Ka_lr = K_eff[lr]; Ka_rl = K_eff[rl]; Ka_rr = K_eff[rr]
    Ka_lx = -q * Q_ax_a[lx]
    Ka_rx = -q * Q_ax_a[rx]
    intl = f_aero_a[l_idx]                                 # INTL: aero part of P_l
    intz = D.T @ intl + f_aero_a[r_idx]                    # INTZ: aero part of DᵀP_l+P_r

    try:
        lu_a = scipy.linalg.lu_factor(Ka_ll)
        ARLR  = scipy.linalg.lu_solve(lu_a, Ka_lr)                 # (2-128)
        AMLR  = scipy.linalg.lu_solve(lu_a, M_ll @ D + M_lr)
        ALX   = scipy.linalg.lu_solve(lu_a, Ka_lx)
        UINTL = scipy.linalg.lu_solve(lu_a, intl)

        # Mean-axis row eliminates u_r through the MASS matrix (2-129/2-130).
        M2RR = (D.T @ M_lr + M_rr) - MR @ ARLR
        M3RR = -MR @ AMLR
        K3LX = -MR @ ALX
        TMP1 = MR @ UINTL
        M4RR = np.linalg.solve(M2RR, M3RR)
        K4LX = np.linalg.solve(M2RR, K3LX)
        TMP2 = np.linalg.solve(M2RR, TMP1)

        # Rigid-equilibrium row (2-131).
        KAZL  = D.T @ Ka_ll + Ka_rl
        KAXL  = D.T @ Ka_lx + Ka_rx
        K2RR  = -KAZL @ ARLR + (D.T @ Ka_lr + Ka_rr)
        KARZX = KAXL - KAZL @ ALX
        IPZ   = intz - KAZL @ UINTL

        # (2-132): MIRR·ü_r + KR1ZX·u_x = IPZF.
        M5RR  = -K2RR @ M4RR + m_r
        MIRR  = -KAZL @ AMLR + M5RR
        KR1ZX = -K2RR @ K4LX + KARZX
        IPZF  = K2RR @ TMP2 + IPZ

        # (2-133): dimensional derivatives Z1ZX = m_r·ü_r per unit u_x.
        Z1ZX  = -m_r @ np.linalg.solve(MIRR, KR1ZX)        # (n_r, n_x)
        IPZF2 = m_r @ np.linalg.solve(MIRR, IPZF)          # (n_r,)  intercepts
    except (np.linalg.LinAlgError, ValueError) as exc:
        warnings.warn(
            f"unrestrained derivatives skipped: singular mean-axis system "
            f"({exc}); q may be at/near divergence.", UserWarning)
        return {}, {}

    # TR (2-122): transfer the r-set force rows to a 6-component resultant
    # (Fx,Fy,Fz,Mx,My,Mz) about the aero reference point.  Right-hand My about
    # +y equals the nose-up-positive pitch_moment convention.
    idx_to_gid = {i: gid for gid, i in grid_index.items()}
    TR = np.zeros((6, n_r))
    for row, a_loc in enumerate(r_idx):
        g_dof = free_dofs[a_loc]
        gid = idx_to_gid[g_dof // 6]
        comp = g_dof % 6
        g = bulk.grids[gid]
        r_vec = np.array([g.x, g.y, g.z]) - ref_pt
        if comp < 3:
            TR[comp, row] = 1.0
            e = np.zeros(3); e[comp] = 1.0
            TR[3:, row] += np.cross(r_vec, e)
        else:
            TR[comp, row] = 1.0
    R6  = TR @ Z1ZX          # (6, n_x) physical force/moment per unit label
    R60 = TR @ IPZF2         # (6,)     physical intercept resultant

    # Non-dimensionalisation (NDIM, 2-123) — sbeam sign sense (CZ up-positive,
    # CMY nose-up-positive), matching the rigid/restrained columns.
    sref = require_aeros(bulk).sref
    cref = require_aeros(bulk).cref
    bref = require_aeros(bulk).bref
    qS = q * sref
    unrest_derivs: dict[str, dict[str, float]] = {}
    for j, c in enumerate(aero_cols):
        unrest_derivs[all_labels[c]] = {
            'CZ':  R6[2, j] / qS,
            'CMY': R6[4, j] / (qS * cref),
            'CMX': R6[3, j] / (qS * bref) if bref > 0 else 0.0,
            'CMZ': R6[5, j] / (qS * bref) if bref > 0 else 0.0,
        }
    unrest_intercepts = {
        'CZ0':  R60[2] / qS,
        'CMY0': R60[4] / (qS * cref),
    }
    return unrest_derivs, unrest_intercepts


def _divergence_dynamic_pressure(K_ll: FloatArray, Q_ll: FloatArray) -> Optional[float]:
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


def _divergence_roots(
    K_ll: FloatArray, Q_ll: FloatArray, nroots: int
) -> list[tuple[float, FloatArray]]:
    """Lowest ``nroots`` positive divergence roots and their eigenvectors.

    Generalises ``_divergence_dynamic_pressure`` from the single critical q to a
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
        for q_div, vec_l in _divergence_roots(K_ll, Q_ll, diverg.nroots):
            # Scatter l-set eigenvector to a-set, expand to g-set (RBAR/RBE3),
            # then max-abs normalise for a readable mode-shape report.
            u_a = np.zeros(K_aa.shape[0])
            for li_idx, li in enumerate(l_idx):
                u_a[li] = vec_l[li_idx]
            mode_g = _expand_to_g(u_a, T, free_local, n_red)
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


def run_sol144_trim(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional["AeroCache"] = None,
) -> Sol144TrimResult:
    """SOL 144 static aeroelastic trim solve (Step 52).

    Solves the coupled structural/aerodynamic trim problem using the Schur
    complement method.  Handles both the determined case
    (n_free == n_suport) and the over-determined (redundant-control) case —
    the latter via null-space reduction with a weighted-L2 objective from
    the TRIMOBJ/TRIMCON/TRIMVAR cards.

    Args:
        bulk:       Parsed BulkData — must include SUPORT and TRIM cards.
        subcase:    SubcaseControl — uses spc_sid and trim_sid.
        aero:       AeroModel with g_slope, g_disp, ajj_inv_corr, skj, wg
                    populated.  Used directly when its Mach matches the TRIM
                    Mach; otherwise it seeds the AeroCache and the AIC is rebuilt
                    at the TRIM Mach (AE9).
        aero_cache: Optional AeroCache shared across subcases so multi-Mach runs
                    build each AIC once.  When None, a local cache seeded with
                    ``aero`` is created.

    Returns:
        Sol144TrimResult with trim variables, displacements, stability derivatives.

    Raises:
        ValueError  if no SUPORT card, TRIM card, a LOAD request the trim
                    cannot honour, or the trim is over-determined without a
                    TRIMOBJ objective.
    """
    if not bulk.supports:
        raise ValueError("run_sol144_trim: no SUPORT card found in model")

    trim_sid = subcase.trim_sid
    if trim_sid is None or trim_sid not in bulk.trims:
        raise ValueError(f"run_sol144_trim: TRIM SID {trim_sid} not found")

    # DEF-M4 — the trim RHS is aero + inertia only; it has no f_struct term, so a
    # LOAD request here would be read, discarded and never mentioned.  Refuse it
    # rather than silently solving a different problem than the deck asked for.
    if subcase.load_sid is not None:
        raise ValueError(
            f"run_sol144_trim: subcase {subcase.subcase_id} requests both "
            f"TRIM={trim_sid} and LOAD={subcase.load_sid}, but SOL 144 trim "
            "applies aerodynamic and inertial loads only — the LOAD would be "
            "silently ignored.  Remove the LOAD request, or use the restrained "
            "static path (run_aeroelastic_static), which does combine a LOAD "
            "set with the aero load."
        )

    trim_card = bulk.trims[trim_sid]
    q_dyn  = trim_card.q

    # ------------------------------------------------------------------ #
    # Mass case (Step 60) — MASSSET payload configuration for this subcase
    # ------------------------------------------------------------------ #
    # Every mass-derived operator below (M_ax, M_aa, GPWG) is built for this
    # case; nothing else changes.  The AIC, splines and the whole AeroCache are
    # geometry/Mach-only and are reused across mass cases untouched — a MASSSET
    # sweep must never invalidate the aero cache.
    from sbeam.gpwg import compute_gpwg
    from sbeam.model.mass_overlay import resolve_mass_case
    massset_sid = subcase.massset_sid
    mass_case_label = resolve_mass_case(bulk, massset_sid).label
    mass_case_gpwg = compute_gpwg(bulk, massset_sid)

    grid_index = build_grid_index(bulk)
    spc_sid = subcase.spc_sid

    # ------------------------------------------------------------------ #
    # Resolve the flight Mach for this subcase (AE9)
    # ------------------------------------------------------------------ #
    # The AIC is Mach-dependent (Prandtl–Glauert β scaling), so the flight Mach
    # comes from the TRIM card.  AEROS.mach is the fallback when the TRIM field is
    # unset (0.0); a genuine disagreement is warned about.  A supersonic Mach is
    # rejected by build_aero_model / AeroCache (steady subsonic VLM only).
    aeros_mach = require_aeros(bulk).mach if bulk.aeros else 0.0
    mach = trim_card.mach if trim_card.mach else aeros_mach
    if trim_card.mach and aeros_mach and abs(trim_card.mach - aeros_mach) > 1e-9:
        warnings.warn(
            f"run_sol144_trim: TRIM Mach {trim_card.mach} disagrees with AEROS "
            f"Mach {aeros_mach}; using the TRIM Mach {trim_card.mach} for the AIC.",
            UserWarning,
        )

    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)
    aero = aero_cache.get(mach)

    # ------------------------------------------------------------------ #
    # All labels (AESTAT + AESURF), sorted consistently
    # ------------------------------------------------------------------ #
    all_labels = sorted(
        [a.label for a in bulk.aestats.values()]
        + [s.label for s in bulk.aesurfs.values()]
    )

    # ------------------------------------------------------------------ #
    # CHORDCP injection validation (Step 54, KC7)
    # ------------------------------------------------------------------ #
    chordcp_alpha_ref = aero.chordcp_alpha_ref
    if chordcp_alpha_ref is not None:
        if abs(chordcp_alpha_ref) > 0.0 and "ANGLEA" not in all_labels:
            raise ValueError(
                "CHORDCP injection with a nonzero ALPHREF requires an ANGLEA "
                "AESTAT label (the injected operating point is re-referenced "
                "through the angle-of-attack normalwash column)."
            )
        card_machs = sorted({c.mach for c in bulk.chordcps.values() if c.mach})
        if card_machs and any(abs(m - mach) > 1e-9 for m in card_machs):
            warnings.warn(
                f"run_sol144_trim: CHORDCP data Mach {card_machs} disagrees with "
                f"the flight Mach {mach}; the injected pressures were measured at "
                "a different operating point (KC7).",
                UserWarning,
            )

    # Separate free (to solve for) vs prescribed (given in TRIM card)
    prescribed_dict = {k.upper(): v for k, v in trim_card.vars.items()}
    free_labels   = [l for l in all_labels if l not in prescribed_dict]

    # ------------------------------------------------------------------ #
    # Reference geometry + RCSID rotation matrix for URDD transform
    # ------------------------------------------------------------------ #
    aeros = require_aeros(bulk)
    from sbeam.assembly.coord_transform import get_transform
    if aeros.rcsid:
        x_ref_pt, R_rcsid = get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref    = float(x_ref_pt[0])
        suport_pos = x_ref_pt          # RCSID origin = moment reference
    else:
        x_ref    = 0.0
        R_rcsid  = np.eye(3)
        suport_pos = np.zeros(3)

    # ------------------------------------------------------------------ #
    # CHORDCP injected-operating-point echo (Step 54) — per-surface integrals
    # of the supplied Cp, plus the VLM flat-plate lift at the same ALPHREF as
    # a plausibility reference for the f06 block (KC7 visibility).
    # ------------------------------------------------------------------ #
    chordcp_echo = None
    if chordcp_alpha_ref is not None:
        n_z_all = np.array([b.normal[2] for b in aero.boxes])
        cp_flat = aero.ajj_inv_corr @ (-n_z_all * chordcp_alpha_ref)
        surfaces: dict[int, dict[str, float]] = {}
        for card in sorted(bulk.chordcps.values(), key=lambda c: c.caero_eid):
            idxs = np.array([j for j, b in enumerate(aero.boxes)
                             if b.caero_eid == card.caero_eid])
            cp   = np.asarray(card.data, dtype=float)
            area = np.array([aero.boxes[j].area for j in idxs])
            nz   = n_z_all[idxs]
            xfp  = np.array([aero.boxes[j].force_point[0] for j in idxs])
            surfaces[card.caero_eid] = {
                'FZ_Q':     float((cp * area * nz).sum()),
                'MY_Q':     float(-(cp * area * nz * (xfp - x_ref)).sum()),
                'FZ_Q_VLM': float((cp_flat[idxs] * area * nz).sum()),
            }
        chordcp_echo = {
            'alpha_ref':  chordcp_alpha_ref,
            'data_machs': sorted({c.mach for c in bulk.chordcps.values() if c.mach}),
            'surfaces':   surfaces,
        }

    # ------------------------------------------------------------------ #
    # Build D_jx and Q_ax on the g-set
    # ------------------------------------------------------------------ #
    # Full-span model: aero and inertia are both whole-airplane, so there is no
    # symmetry force-doubling factor (the AE1 Step D `sym=2` double-count that
    # halved the trim solution is gone with half-span support).
    D_jx = build_djx(aero.boxes, all_labels, bulk,
                     id_to_k=aero.require_box_id_to_k())   # (n_box, n_labels)
    Q_ax_g = aero.require_g_load().T @ aero.skj @ aero.ajj_inv_corr @ D_jx  # (n_g, n_labels)

    # ------------------------------------------------------------------ #
    # A-set partition (SPC + RBE3 reduction)
    # ------------------------------------------------------------------ #
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    T, free_local, free_dofs = red.T, red.free_local, red.free_dofs
    red_dofs = red.red_dofs

    # Reduce Q_ax and structural stiffness to a-set
    Q_ax_a = red.reduce_rect(Q_ax_g)               # (n_a, n_labels)

    K_gg = assemble_global_stiffness(bulk)
    K_aa = red.reduce_matrix(K_gg, dense=True)     # (n_a, n_a)

    # Also compute Q_aa for storage in result (reuse existing helper)
    from sbeam.aero.coupling import build_qaa
    Q_gg = build_qaa(aero, aero.require_g_load(), aero.require_g_slope())
    Q_aa = red.reduce_matrix(Q_gg)

    # ------------------------------------------------------------------ #
    # Build combined RHS: q*f_g (baseline aero) + inertial load
    # ------------------------------------------------------------------ #
    from sbeam.aero.coupling import build_fg
    f_aero_g = q_dyn * build_fg(aero, aero.require_g_load())   # (n_g,) baseline aero (whole-airplane)

    # Aerodynamic contribution of prescribed trim variables (URDD cols = 0)
    label_to_col = {l: i for i, l in enumerate(all_labels)}
    pres_values = np.array([prescribed_dict.get(l, 0.0) for l in all_labels])
    pres_aero_g = q_dyn * Q_ax_g @ pres_values       # (n_g,)

    # Transform prescribed URDD values from RCSID frame to basic frame (AE5).
    # pres_values_basic is used only for the inertial path; prescribed_dict
    # is preserved in RCSID-frame form so trim_vars output matches the input card.
    pres_values_basic = urdd_rcsid_to_basic(
        pres_values, label_to_col, R_rcsid, bool(aeros.rcsid)
    )

    # Mass matrix for this mass case.  Assembled once here and reused by both
    # M_ax (below) and the unrestrained-derivative block further down — one mass
    # model for the whole subcase, by construction (Q4 / DEF-M3).
    from sbeam.assembly.mass_matrix import assemble_global_mass
    M_gg = assemble_global_mass(bulk, massset_sid)

    # Inertial sensitivity matrix (basic frame); prescribed inertial RHS (AE7).
    # M_ax_g[:, col] = dF/dURDD_col = -M_gg @ phi_r; zero for non-URDD labels.
    M_ax_g = build_inertial_cols(
        bulk, all_labels, grid_index, suport_pos, massset_sid, M_gg=M_gg)
    pres_inertial_g = M_ax_g @ pres_values_basic     # (n_g,) — free URDD entry = 0

    f_rhs_g = f_aero_g + pres_aero_g + pres_inertial_g  # (n_g,)

    # Reduce f_rhs to a-set
    f_rhs_a = red.reduce_vector(f_rhs_g)   # (n_a,)

    # Reduce M_ax to a-set (same RBE3+SPC path as Q_ax)
    M_ax_a = red.reduce_rect(M_ax_g)       # (n_a, n_labels)

    # ------------------------------------------------------------------ #
    # SUPORT DOF indices in a-set
    # ------------------------------------------------------------------ #
    suport_local = get_suport_local(bulk, free_dofs, grid_index)
    n_suport = len(suport_local)
    n_free   = len(free_labels)

    over_determined = n_free > n_suport
    if n_free < n_suport:
        raise ValueError(
            f"Under-determined trim (n_free={n_free} < n_suport={n_suport}): "
            "more SUPORT DOFs than free variables."
        )
    if n_free == 0:
        raise ValueError("run_sol144_trim: no free trim variables — all labels prescribed.")

    # ------------------------------------------------------------------ #
    # Map free labels to column indices in Q_ax_a
    # ------------------------------------------------------------------ #
    free_label_cols = [label_to_col[l] for l in free_labels]

    # ------------------------------------------------------------------ #
    # Schur-complement trim solve (determined or over-determined)
    # ------------------------------------------------------------------ #
    if over_determined:
        # Resolve the TRIMOBJ/TRIMCON/TRIMVAR sets referenced by this subcase.
        trimobj = bulk.trimobjs.get(subcase.trimobj_sid) if subcase.trimobj_sid else None
        if trimobj is None and bulk.trimobjs:
            # Fall back to a single defined TRIMOBJ when the subcase did not name one.
            trimobj = next(iter(bulk.trimobjs.values())) if len(bulk.trimobjs) == 1 else None
        if trimobj is None:
            raise ValueError(
                f"Over-determined trim (n_free={n_free} > n_suport={n_suport}) "
                "requires a TRIMOBJ card to specify the weighted objective."
            )
        trimcons = []
        for cons in bulk.trimcons.values():
            trimcons.extend(cons)
        u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = _solve_trim_overdetermined(
            K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q_dyn, suport_local,
            free_labels, free_label_cols, trimobj, trimcons, bulk.trimvars,
        )
    else:
        u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = _solve_trim_determined(
            K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q_dyn, suport_local, free_label_cols
        )
    trim_mode = "over-determined" if over_determined else "determined"

    # ------------------------------------------------------------------ #
    # Assemble full trim variable dict
    # ------------------------------------------------------------------ #
    trim_vars: dict[str, float] = dict(prescribed_dict)
    for i, lbl in enumerate(free_labels):
        trim_vars[lbl] = float(delta_free_arr[i])

    # FREE URDD variables are solved in the BASIC frame — their sensitivity
    # column in the Schur system is the basic-frame M_ax — while URDD *labels*
    # are RCSID-frame values.  Rebuild the label values from the full basic
    # triple (prescribed entries from pres_values_basic, free entries from the
    # solve) so trim_vars is uniformly RCSID; without this a free URDD on an
    # RCSID deck is reported in the wrong frame and the downstream
    # rcsid-to-basic rotation corrupts the inertial loads and closure
    # (latent since Step 52 — every earlier deck prescribed its URDDs;
    # exposed by the Step 63 settled-state gate).
    free_urdd = [l for l in free_labels if l in _URDD_DOF]
    if free_urdd and bool(aeros.rcsid):
        urdd_full_basic = pres_values_basic.copy()
        for i, lbl in enumerate(free_labels):
            if lbl in _URDD_DOF:
                urdd_full_basic[label_to_col[lbl]] = float(delta_free_arr[i])
        urdd_full_rcsid = urdd_basic_to_rcsid(
            urdd_full_basic, label_to_col, R_rcsid, True)
        for lbl in free_urdd:
            trim_vars[lbl] = float(urdd_full_rcsid[label_to_col[lbl]])

    # Full delta_all vector (ordered by all_labels)
    delta_all = np.array([trim_vars.get(l, 0.0) for l in all_labels])

    # KC7: the injected mean flow is only valid as a perturbation base near its
    # reference AOA — warn when the trimmed AOA strays outside ~2 degrees of it.
    _CHORDCP_ALPHA_TOL = 0.035  # rad
    if chordcp_alpha_ref is not None and "ANGLEA" in trim_vars:
        alpha_err = abs(trim_vars["ANGLEA"] - chordcp_alpha_ref)
        if alpha_err > _CHORDCP_ALPHA_TOL:
            warnings.warn(
                f"run_sol144_trim: trimmed ANGLEA {trim_vars['ANGLEA']:.4f} rad is "
                f"{alpha_err:.4f} rad from the CHORDCP reference AOA "
                f"{chordcp_alpha_ref:.4f} rad (> {_CHORDCP_ALPHA_TOL} rad ≈ 2°); "
                "the trim perturbs about the injected operating point and its "
                "validity degrades with distance (KC7).",
                UserWarning,
            )

    # ------------------------------------------------------------------ #
    # Expand a-set displacement to full g-set via RBAR/RBE3 T matrix.
    # AE1 Step B1: RBAR slave DOFs must move with their masters before any
    # downstream `g_slope @ u` or `_compute_aero_forces` call; a bare index
    # scatter leaves them at zero and corrupts the structural normalwash.
    # ------------------------------------------------------------------ #
    displacements = _expand_to_g(u_a, T, free_local, len(red_dofs))

    # ------------------------------------------------------------------ #
    # CBAR force / stress recovery
    # ------------------------------------------------------------------ #
    bar_forces   = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid]   = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)

    # ------------------------------------------------------------------ #
    # Rigid derivatives (no structural deformation)
    # ------------------------------------------------------------------ #
    rigid_derivs = compute_rigid_derivs(aero, D_jx, all_labels, bulk, x_ref, suport_pos)

    # ------------------------------------------------------------------ #
    # Elastic restrained derivatives (finite difference, u_r = 0)
    # ------------------------------------------------------------------ #
    rest_derivs = _compute_restrained_derivs(
        K_ll_lu, l_idx, Q_ax_a, M_ax_a, all_labels,
        u_a, delta_all, aero, D_jx,
        T, free_local, len(red_dofs),
        bulk, x_ref, q_dyn, suport_pos,
    )

    # ------------------------------------------------------------------ #
    # Unrestrained (mean-axis / inertia-relief) derivatives — AE8b
    # (MSC Aeroelastic Analysis UG Eqs. 2-111 … 2-134)
    # ------------------------------------------------------------------ #
    M_aa = red.reduce_matrix(M_gg, dense=True)   # M_gg assembled with M_ax above
    f_aero_a = red.reduce_vector(f_aero_g)
    unrest_derivs, unrest_intercepts = _compute_unrestrained_derivs(
        K_aa, M_aa, Q_aa, Q_ax_a, f_aero_a, all_labels,
        l_idx, r_idx, free_dofs, grid_index, bulk, q_dyn, suport_pos,
    )

    # ------------------------------------------------------------------ #
    # Total CL and CM at trim
    # ------------------------------------------------------------------ #
    from sbeam.aero.integration import build_djk
    djk = build_djk(aero.boxes)
    w_struct = djk @ (aero.require_g_slope() @ displacements)
    w_total  = w_struct + D_jx @ delta_all + aero.wg
    gamma    = aero.ajj_inv_corr @ w_total
    f_box_vec = aero.skj @ gamma
    Fz_total = float(f_box_vec[2::3].sum())
    Fx_total = float(f_box_vec[0::3].sum())
    # nose-up-positive (single-source helper, AE1 Step E); whole-airplane (full-span)
    My_total = float(pitch_moment(f_box_vec, aero.boxes, x_ref))
    sref = aeros.sref
    cref = aeros.cref
    # Fz_total and My_total are force/q (skj @ Cp); divide by area only, not q.
    # total_cl/total_cx are BODY-axis (CZ along global-z, CX along streamwise-x);
    # total_cl balances weight at trim and matches NASTRAN's body-axis convention.
    total_cl = Fz_total / sref if sref > 0 else 0.0
    total_cx = Fx_total / sref if sref > 0 else 0.0
    total_cm = My_total / (sref * cref) if sref * cref > 0 else 0.0
    # Wind-axis lift (genuine CL, ⊥ to U∞): rotate the body resultant through
    # the trimmed angle of attack.  CL_wind = CZ·cosα − CX·sinα; equals CZ only
    # at α ≈ 0 (see docs/20_theory/01_aeroelastics_theory.md §5.4).
    alpha_trim = (
        float(delta_all[all_labels.index("ANGLEA")])
        if "ANGLEA" in all_labels else 0.0
    )
    total_cl_wind = float(
        total_cl * np.cos(alpha_trim) - total_cx * np.sin(alpha_trim)
    )
    # Lateral/directional totals — side force plus the full 3-component moment
    # resultant about the RCSID origin, matching the CMX/CMZ derivative-column
    # convention (Step 52).  ≈0 for a symmetric model at a symmetric trim.
    bref = aeros.bref
    Fy_total = float(f_box_vec[1::3].sum())
    Mx_total, _My_xp, Mz_total = aero_moment_resultant(
        f_box_vec.reshape(-1, 3), aero.boxes, suport_pos
    )
    total_cy = Fy_total / sref if sref > 0 else 0.0
    total_cmx = float(Mx_total) / (sref * bref) if sref * bref > 0 else 0.0
    total_cmz = float(Mz_total) / (sref * bref) if sref * bref > 0 else 0.0

    # ------------------------------------------------------------------ #
    # Hinge-moment derivatives + trimmed hinge moment per AESURF control
    # ------------------------------------------------------------------ #
    hinge_moments = _compute_hinge_moments(aero, D_jx, all_labels, bulk, f_box_vec)

    # ------------------------------------------------------------------ #
    # Step 56 — per-box pressures/forces, g-set flight loads, divergence q
    # ------------------------------------------------------------------ #
    # f_box_vec is in force/q units; the physical box force is q * f_box_vec.
    # ΔCp is the normal-projected force per unit area in force/q units (so the
    # box's z-normal flat-plate limit reduces to f_box_vec[3j+2] / area).
    n_box = len(aero.boxes)
    box_forces = np.empty((n_box, 3))
    box_cp = np.empty(n_box)
    for j, b in enumerate(aero.boxes):
        f_j = f_box_vec[3 * j:3 * j + 3]
        box_forces[j] = q_dyn * f_j
        box_cp[j] = float(np.dot(f_j, b.normal) / b.area) if b.area > 0 else 0.0

    # g-set aero flight-load vector for FORCE/MOMENT export (plain trim:
    # G_load^T · q · P_k).  Preserves net force/moment through the spline.
    grid_loads = aero.require_g_load().T @ (q_dyn * f_box_vec)

    # Step 64 / DEF-M1 — echo what the load injection contributed.  Boxes with
    # no structural coupling (SPLINE0 body panels, un-splined boxes) enter the
    # trim balance and the load export as a rigid load at their master grid;
    # report each group's 6-component resultant about the moment reference so a
    # mis-placed master grid is visible.  Empty on decks with none, so their f06
    # is byte-identical.
    load_injection_echo = _build_injection_echo(
        aero, box_forces, suport_pos, bulk, grid_index, red.free_dofs
    )

    # ------------------------------------------------------------------ #
    # Step 53 — balanced maneuver loads & inertia relief.
    # The inertial g-set load is M_ax · a using the FINAL trim accelerations
    # (prescribed AND solved-free URDD), not just the prescribed ones — the
    # free URDD already entered the displacement solve via the M_ax_a column.
    # Net (aero + inertial) grid loads are the deliverable for stress and the
    # non-zero inertia column consumed by MONPNT3 (MON3).  For a 1g determined
    # trim with URDD≈0 these reduce to the aero-only / zero case.
    # ------------------------------------------------------------------ #
    delta_all_basic = urdd_rcsid_to_basic(
        delta_all, label_to_col, R_rcsid, bool(aeros.rcsid)
    )
    inertial_loads = M_ax_g @ delta_all_basic     # (n_g,)
    net_loads = grid_loads + inertial_loads       # (n_g,)

    # Force/moment closure (V-C5 / KC9): body-frame resultant of the net
    # (aero + inertial) load about the moment reference.  For a true free
    # aircraft (SUPORT, no SPC) this must balance to ≈ 0 — a non-zero residual
    # flags a gravity double-count or a lumped-vs-consistent mass mismatch.  For
    # an SPC'd (e.g. half-span) model the residual legitimately equals the
    # constraint reaction, so the hard warning fires only in the free case; the
    # residual is always stored for the per-case acceptance test.
    maneuver_closure = load_resultant(net_loads, bulk, grid_index, suport_pos)
    spc_dofs_closure = get_spc_dofs(bulk, spc_sid, grid_index) if spc_sid else []
    if len(spc_dofs_closure) == 0:
        aero_res = load_resultant(grid_loads, bulk, grid_index, suport_pos)
        f_scale = max(np.linalg.norm(aero_res[:3]), 1.0)
        m_scale = max(np.linalg.norm(aero_res[3:]), 1.0)
        if (np.linalg.norm(maneuver_closure[:3]) > 1e-6 * f_scale or
                np.linalg.norm(maneuver_closure[3:]) > 1e-6 * m_scale):
            warnings.warn(
                f"SOL 144 maneuver closure: free-aircraft net (aero+inertial) "
                f"resultant is non-zero (F={maneuver_closure[:3]}, "
                f"M={maneuver_closure[3:]}) — check inertia relief / load factor "
                f"(KC9).",
                UserWarning,
            )

    # Critical divergence dynamic pressure on the restrained l-set.
    K_ll_div = K_aa[np.ix_(l_idx, l_idx)]
    Q_ll_div = Q_aa[np.ix_(l_idx, l_idx)]
    q_div = _divergence_dynamic_pressure(K_ll_div, Q_ll_div)

    k_aa_lu_trim = scipy.linalg.lu_factor(K_aa)

    # ------------------------------------------------------------------ #
    # MON2/MON3 — monitor-point integrated section loads.
    # The reaction column needs the SPC/SUPORT reaction that balances the net
    # (aero + inertial) load; recovered the same way as SOL 101 (R = K·u − f).
    # ------------------------------------------------------------------ #
    monitor_loads = None
    section_loads = None
    # A SET1-backed MONSECT needs the reaction column for exactly the same
    # reason MONPNT3 does — a cut that spans a constrained grid carries its
    # reaction across the plane.
    needs_reactions = bool(bulk.monpnt3s) or any(
        bulk.aecomps[c.comp].listtype == "SET1" for c in bulk.monsects.values()
    )
    if bulk.monpnt1s or bulk.monpnt3s or bulk.monsects:
        reactions = {}
        if needs_reactions:
            constrained = list(get_spc_dofs(bulk, spc_sid, grid_index)) if spc_sid else []
            for sup in bulk.supports:
                if sup.gid in grid_index:
                    base = grid_index[sup.gid] * 6
                    constrained += [base + (int(ch) - 1) for ch in sup.dofs]
            if constrained:
                reactions = recover_reactions(
                    bulk, displacements, constrained, K_gg, grid_index, net_loads
                )
        if bulk.monpnt1s or bulk.monpnt3s:
            monitor_loads = compute_monitor_loads(
                bulk, aero, box_forces, grid_loads, inertial_loads, grid_index,
                reactions, massset_sid
            )
        # MONSECT — the same integrand swept over cut planes (Monitor Phase 2).
        if bulk.monsects:
            section_loads = compute_section_cuts(
                bulk, aero, box_forces, grid_loads, inertial_loads, grid_index,
                reactions
            )

    return Sol144TrimResult(
        subcase_id=subcase.subcase_id,
        trim_sid=trim_sid,
        q=q_dyn,
        mach=mach,
        trim_vars=trim_vars,
        displacements=displacements,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        q_aa=Q_aa,
        free_dofs=free_dofs,
        k_aa_lu=k_aa_lu_trim,
        rigid_derivs=rigid_derivs,
        restrained_derivs=rest_derivs,
        unrestrained_derivs=unrest_derivs,
        unrestrained_intercepts=unrest_intercepts,
        box_gamma=gamma,
        total_cl=total_cl,
        total_cm=total_cm,
        total_cx=total_cx,
        total_cl_wind=total_cl_wind,
        total_cy=total_cy,
        total_cmx=total_cmx,
        total_cmz=total_cmz,
        box_cp=box_cp,
        box_forces=box_forces,
        grid_loads=grid_loads,
        inertial_loads=inertial_loads,
        net_loads=net_loads,
        maneuver_closure=maneuver_closure,
        q_div=q_div,
        hinge_moments=hinge_moments,
        trim_mode=trim_mode,
        monitor_loads=monitor_loads,
        section_loads=section_loads,
        chordcp_echo=chordcp_echo,
        load_injection_echo=load_injection_echo,
        massset_sid=massset_sid,
        massset_label=mass_case_label,
        massset_mass=mass_case_gpwg.total_mass,
        massset_cg=(mass_case_gpwg.cg_x, mass_case_gpwg.cg_y, mass_case_gpwg.cg_z),
    )
