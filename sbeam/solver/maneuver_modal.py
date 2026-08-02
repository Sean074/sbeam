"""Phase G0 Step 62 — modal transient maneuver-loads solver (prescribed rigid).

This solver integrates the same physics as the increment-1 direct solver
(`maneuver_qs.run_maneuver_qs`: Level-1 quasi-steady aero, open-loop commands,
rigid motion prescribed through the δ(t) trim labels, restrained l-set frame)
but in the coordinates of the Step 61 free-free maneuver basis, with
mode-acceleration recovery.  It exists to de-risk basis quality, truncation
behaviour and the recovery machinery before Step 63 frees the rigid partition,
and to land the fixed-Φ mass-case transient capability on top of Step 60.

Restrained-frame representation of the free-free basis
------------------------------------------------------
The Step 61 elastic modes Φ_e are mean-axis shapes: mass-orthogonal to the
rigid vectors Φ_r, with nonzero values at the SUPORT (r-set) DOFs.  A Galerkin
projection onto Φ_e directly would NOT reproduce the direct solver: whenever
the commanded history unbalances the aircraft, the direct solver's implicit
SUPORT reaction λ leaks into the mean-axis test space (Φ_eᵀ e_r λ = Φ_e,rᵀ λ
≠ 0), and the rigid content of the restrained solution carries aerodynamic
load (q·Φ_eᵀ Q Φ_r) that an elastic-only mean-axis system never sees.

Both terms vanish identically when each mode's rigid content is re-based so it
is zero at the SUPORT DOFs (the D2 output convention applied to the *basis*):

    ψ_e = φ_e − Φ_r · (Φ_r[r-rows])⁻¹ · φ_e[r-rows]        (ψ_e[r-rows] = 0)

ψ_e differs from φ_e by a rigid (strain-free) vector, so frequencies, strain
content and truncation behaviour are those of the free-free basis; but every
ψ_e lies in the restrained subspace (u_r = 0), so projecting the direct
solver's l-set system onto V = ψ_e[l-rows] is an exact change of coordinates
of the increment-1 ODE system whenever V spans it.  That is the full-basis
identity gate: with all elastic modes retained (and no massless DOFs condensed
out of the basis eigensolve) the modal solution matches ``run_maneuver_qs`` to
round-off; with massless DOFs condensed (CONM2-only decks) the mass-carrying
dynamics still match and mode-acceleration recovers the massless static
content through K_eff⁻¹, leaving only the (second-order) aerodynamic coupling
to that static content as a documented near-identity.

Reduced equation of motion (n_e × n_e, dense)::

    M_ψψ ξ̈ + C_ψψ ξ̇ + K_ψψ ξ = Vᵀ F_l(t)

    M_ψψ = Vᵀ M_ll V          (= I + Φ_e,rᵀ M_rr Φ_e,r at baseline)
    K_ψψ = Vᵀ (K_ll − q·Q_ll) V
    C_ψψ = M_ψψ · diag(2 ζ ω_i)   (uniform modal damping; the consistent
                                   physical damping force is M_ll V·2ζω_i ξ̇_i,
                                   so Vᵀ f_damp ≡ C_ψψ ξ̇ exactly)
    F_l(t) = f_aero_l + q·Q_ax_l·δ(t) + M_ax_l·δ_basic(t)   (shared with the
                                                             direct solver)

``B_hh`` (the Step 61 rigid-rate GAF) is deliberately NOT engaged here: the
rigid rates are prescribed via the δ(t) PITCH/ROLL/YAW labels, so their
aerodynamics already arrive through q·Q_ax·δ — adding B_hh would double-count.
It activates at Step 63 when the rates become states.

Mode-acceleration recovery (per output step, theory Eq. 23)::

    u_l = K_eff_ll⁻¹ (F_l − M_ll V ξ̈ − f_damp,l)

reusing the direct solver's K_eff_ll (which already contains the static aero
coupling, including to any condensed massless DOFs).  The recovered u_l has
u_r = 0 by construction — the D2 output convention — and feeds the shared
``maneuver_qs.recover_step`` so both solvers' per-step recovery is identical.

Fixed-Φ mass cases (Step 60 MASSSET)
------------------------------------
The basis Φ is built once from the BASELINE mass case; a MASSSET subcase swaps
only the mass side (M_ll,i / M_ax,i, via the shared subcase-threaded assembly)
and the IC trim.  ``ManeuverBasisCache`` holds the untruncated basis per
(spc_sid, EIGRL sid) so a multi-subcase mass sweep builds Φ exactly once.  A
warning is issued when an overlay moves the CG by more than 5 % of c_ref —
beyond that the frozen mean axis is materially wrong and the basis should be
re-solved (decision D4).

Public API:
    run_maneuver_modal(bulk, subcase, aero, aero_cache=None, basis_cache=None,
                       recovery="acceleration")
    ManeuverBasisCache(bulk, aero)
"""

import warnings
from dataclasses import replace
from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import require_aeros
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.load_vector import build_grid_index
from sbeam.aero.aero_model import AeroModel
from sbeam.gpwg import compute_gpwg
from sbeam.results.results import ManeuverStep, ManeuverResult, peak_grid_force
from sbeam.solver.maneuver_qs import (
    Operators,
    assemble_operators,
    delta_of_t,
    force_l,
    recover_step,
)
from sbeam.solver.modal_basis import (
    ManeuverBasis,
    assemble_aset_operators,
    build_maneuver_basis,
    truncate_basis,
)
from sbeam.solver.sol144 import AeroCache, run_sol144_trim
from sbeam.types import FloatArray

# CG shift (fraction of c_ref) beyond which the frozen mean axis of the
# baseline basis is considered materially wrong for a MASSSET case (D4).
_CG_SHIFT_WARN_FRAC = 0.05

# Tolerance on the re-based modes' residual at the SUPORT DOFs (they are zero
# there by construction; violation means Phi_rr was near-singular).
_REBASE_TOL = 1e-8


class ManeuverBasisCache:
    """Job-level cache of the untruncated free-free basis (decision D3).

    One basis per (spc_sid, EIGRL sid), always built from the BASELINE mass
    case (the fixed-Φ rule: MASSSET subcases swap M, never Φ).  ``n_builds``
    counts eigensolves — the build-once gate asserts it stays at 1 across a
    multi-subcase mass sweep.
    """

    def __init__(self, bulk: BulkData, aero: AeroModel):
        self._bulk = bulk
        self._aero = aero
        self._cache: dict[tuple, ManeuverBasis] = {}
        self.n_builds = 0

    def get(self, subcase: SubcaseControl, eigrl_sid: int) -> ManeuverBasis:
        key = (subcase.spc_sid, eigrl_sid)
        if key not in self._cache:
            self._cache[key] = _build_basis(
                self._bulk, subcase, self._aero, eigrl_sid)
            self.n_builds += 1
        return self._cache[key]


def _build_basis(
    bulk: BulkData, subcase: SubcaseControl, aero: AeroModel, eigrl_sid: int
) -> ManeuverBasis:
    """One untruncated baseline-mass basis (massset stripped; NMODES applied later)."""
    base_subcase = replace(subcase, massset_sid=None)
    ops_base = assemble_aset_operators(bulk, base_subcase, aero)
    eigrl = bulk.eigrls[eigrl_sid] if eigrl_sid > 0 else None
    return build_maneuver_basis(bulk, ops_base, eigrl, nmodes=0)


def _restrained_modes(ops: Operators, basis: ManeuverBasis) -> FloatArray:
    """Re-base the mean-axis elastic modes into the restrained (u_r = 0) frame.

    Returns V = ψ_e[l-rows]: each column is φ_e minus the unique rigid vector
    that zeroes it at the SUPORT DOFs (strain-identical to φ_e).
    """
    n_r = basis.n_r
    phi_r = basis.phi[:, :n_r]
    phi_e = basis.phi[:, n_r:]
    r_rows = ops.suport_local

    phi_rr = phi_r[r_rows, :]
    try:
        coeff = np.linalg.solve(phi_rr, phi_e[r_rows, :])
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "run_maneuver_modal: the rigid basis restricted to the SUPORT DOFs "
            "is singular — the SUPORT DOF set does not span the rigid modes "
            f"about the reference point.  ({exc})"
        ) from exc
    psi = phi_e - phi_r @ coeff

    resid = float(np.abs(psi[r_rows, :]).max()) if psi.size else 0.0
    scale = max(1.0, float(np.abs(psi).max()))
    if resid / scale > _REBASE_TOL:
        raise ValueError(
            "run_maneuver_modal: re-based elastic modes are not zero at the "
            f"SUPORT DOFs (residual {resid:.3e}) — Phi_rr is ill-conditioned."
        )
    return psi[ops.l_idx, :]


def _warn_cg_shift(bulk: BulkData, massset_sid: int) -> None:
    """D4: warn when a MASSSET overlay moves the CG > 5 % of c_ref."""
    base = compute_gpwg(bulk, None)
    case = compute_gpwg(bulk, massset_sid)
    shift = float(np.linalg.norm([
        case.cg_x - base.cg_x, case.cg_y - base.cg_y, case.cg_z - base.cg_z]))
    cref = require_aeros(bulk).cref
    if cref > 0.0 and shift > _CG_SHIFT_WARN_FRAC * cref:
        warnings.warn(
            f"run_maneuver_modal: MASSSET {massset_sid} moves the CG by "
            f"{shift:.4g} ({shift / cref:.1%} of c_ref) from the baseline; the "
            f"fixed-Phi mean axis is only trustworthy below "
            f"{_CG_SHIFT_WARN_FRAC:.0%} — re-solve the basis for this mass "
            "case (or accept the documented approximation).",
            UserWarning,
        )


def run_maneuver_modal(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional[AeroCache] = None,
    basis_cache: Optional[ManeuverBasisCache] = None,
    recovery: str = "acceleration",
) -> ManeuverResult:
    """Step 62 modal transient maneuver-loads solve (prescribed rigid states).

    Selected by ``main.py`` when the MLOADS card requests it
    (``Mloads.selects_modal``: any of NMODES/METHOD/ZETA nonzero, METHOD=-1
    for the all-defaults-modal sentinel).

    Args:
        bulk:        Parsed BulkData — same requirements as ``run_maneuver_qs``.
        subcase:     SubcaseControl — uses ``mloads_sid``, ``spc_sid`` and
                     ``massset_sid`` (Step 60 mass case).
        aero:        AeroModel (seeds the AeroCache; rebuilt at the TRIM Mach).
        aero_cache:  Optional shared AeroCache.
        basis_cache: Optional job-level ManeuverBasisCache (D3); ``None``
                     builds a fresh basis for this subcase.
        recovery:    "acceleration" (default; mode-acceleration with inertia
                     relief) or "displacement" (u = V·ξ; test/reference only —
                     the convergence gate quantifies how much worse it is).

    Returns:
        ManeuverResult with ``modal_coords`` per step and ``n_modes_used`` /
        ``basis_info`` set.
    """
    if recovery not in ("acceleration", "displacement"):
        raise ValueError(
            f"run_maneuver_modal: unknown recovery '{recovery}' "
            "(expected 'acceleration' or 'displacement')")
    if subcase.mloads_sid is None or subcase.mloads_sid not in bulk.mloads:
        raise ValueError(
            f"run_maneuver_modal: MLOADS SID {subcase.mloads_sid} not found")
    mload = bulk.mloads[subcase.mloads_sid]
    mldtrim = bulk.mldtrims[mload.mldtrim]
    mldtime = bulk.mldtimes[mload.mldtime]
    mldcomd = bulk.mldcomds.get(mload.mldcomd) if mload.mldcomd else None
    mldprnt = bulk.mldprnts.get(mload.mldprnt) if mload.mldprnt else None

    if subcase.massset_sid is not None:
        _warn_cg_shift(bulk, subcase.massset_sid)

    # Initial condition: the Step 53 static balanced trim (same pattern as the
    # direct solver, mass overlay included via the subcase thread).
    ic_subcase = SubcaseControl(
        subcase_id=subcase.subcase_id,
        spc_sid=subcase.spc_sid,
        trim_sid=mldtrim.trim_sid,
        trimobj_sid=subcase.trimobj_sid,
        massset_sid=subcase.massset_sid,
    )
    grid_index = build_grid_index(bulk)
    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)
    ic = run_sol144_trim(bulk, ic_subcase, aero, aero_cache=aero_cache)
    q = ic.q
    aero = aero_cache.get(ic.mach)

    # Subcase l-set operators (mass case included) + the baseline-mass basis.
    ops = assemble_operators(bulk, subcase, aero, q)

    eigrl_sid = mload.method if mload.method > 0 else 0
    if basis_cache is not None:
        basis_full = basis_cache.get(subcase, eigrl_sid)
    else:
        basis_full = _build_basis(bulk, subcase, aero, eigrl_sid)
    basis = truncate_basis(basis_full, mload.nmodes)
    n_e = basis.n_e

    V = _restrained_modes(ops, basis)                       # (n_l, n_e)

    # Reduced operators (dense n_e × n_e).
    M_red = V.T @ ops.M_ll @ V
    K_red = V.T @ ops.K_eff_ll @ V
    omega = 2.0 * np.pi * basis.elastic_freqs_hz            # (n_e,)
    c_rate = 2.0 * mload.zeta * omega                       # per-mode damping rate
    C_red = M_red * c_rate[np.newaxis, :] if mload.zeta else np.zeros((n_e, n_e))

    # Recovery operator: K_eff_ll LU shared with the mode-acceleration formula
    # (the direct solver's effective stiffness, aero included).
    K_eff_lu = scipy.linalg.lu_factor(ops.K_eff_ll)

    base_delta = {l: float(ic.trim_vars.get(l, 0.0)) for l in ops.all_labels}
    commands = mldcomd.commands if mldcomd is not None else []

    # ---- Newmark-β (average acceleration: β=1/4, γ=1/2), n_e coordinates ----
    t0, tend, dt = mldtime.t0, mldtime.tend, mldtime.dt
    n_steps = int(round((tend - t0) / dt))
    tout = mldtime.tout if mldtime.tout > 0 else dt
    out_every = max(1, int(round(tout / dt)))

    beta, gamma = 0.25, 0.5
    a0 = 1.0 / (beta * dt * dt)
    a1 = gamma / (beta * dt)
    a2 = 1.0 / (beta * dt)
    a3 = 1.0 / (2.0 * beta) - 1.0
    a4 = gamma / beta - 1.0
    a5 = dt * 0.5 * (gamma / beta - 2.0)

    K_hat = K_red + a1 * C_red + a0 * M_red
    K_hat_lu = scipy.linalg.lu_factor(K_hat)

    # Equilibrium start: K_red ξ0 = Vᵀ F(t0) makes ξ̈0 = 0 exactly, and the
    # mode-acceleration recovery of the t0 sample is then K_eff⁻¹ F(t0) — the
    # direct solver's static start, truncation-independent.
    delta = delta_of_t(t0, base_delta, commands, bulk.tabled1s, ops.all_labels)
    F = force_l(ops, delta)
    xi = scipy.linalg.solve(K_red, V.T @ F)
    vxi = np.zeros_like(xi)
    axi = np.zeros_like(xi)

    def _vals_at(delta_arr: FloatArray) -> dict[str, float]:
        return {l: float(delta_arr[i]) for i, l in enumerate(ops.all_labels)}

    def _recover_u_l(F_l: FloatArray) -> FloatArray:
        if recovery == "displacement":
            return V @ xi
        f_inert = ops.M_ll @ (V @ axi)
        f_damp = ops.M_ll @ (V @ (c_rate * vxi)) if mload.zeta else 0.0
        return scipy.linalg.lu_solve(K_eff_lu, F_l - f_inert - f_damp)

    steps: list[ManeuverStep] = []
    times: list[float] = []

    def _emit(t: float, F_l: FloatArray, delta_arr: FloatArray) -> None:
        u_l = _recover_u_l(F_l)
        step = recover_step(
            ops, bulk, grid_index, t, u_l, delta_arr, _vals_at(delta_arr),
            modal_coords=xi.copy())
        steps.append(step)
        times.append(t)

    _emit(t0, F, delta)
    for n in range(1, n_steps + 1):
        t = t0 + n * dt
        delta = delta_of_t(t, base_delta, commands, bulk.tabled1s, ops.all_labels)
        F = force_l(ops, delta)
        rhs = (V.T @ F
               + M_red @ (a0 * xi + a2 * vxi + a3 * axi)
               + C_red @ (a1 * xi + a4 * vxi + a5 * axi))
        xi_new = scipy.linalg.lu_solve(K_hat_lu, rhs)
        axi_new = a0 * (xi_new - xi) - a2 * vxi - a3 * axi
        vxi_new = vxi + dt * ((1.0 - gamma) * axi + gamma * axi_new)
        xi, vxi, axi = xi_new, vxi_new, axi_new
        if n % out_every == 0 or n == n_steps:
            _emit(t, F, delta)

    crit_index = int(np.argmax([peak_grid_force(s) for s in steps])) if steps else 0

    return ManeuverResult(
        subcase_id=subcase.subcase_id,
        mloads_sid=subcase.mloads_sid,
        trim_sid=mldtrim.trim_sid,
        q=q,
        mach=ic.mach,
        labels=ops.all_labels,
        times=np.array(times),
        steps=steps,
        crit_index=crit_index,
        mldprnt_items=(mldprnt.items if mldprnt is not None else []),
        massset_sid=subcase.massset_sid,
        n_modes_used=n_e,
        basis_info={
            "n_r": basis.n_r,
            "n_e": n_e,
            "n_available": basis.n_available_elastic,
            "freqs_hz": basis.elastic_freqs_hz.tolist(),
            "orthogonality_residual": basis.orthogonality_residual,
            "n_massless": basis.n_massless,
            "zeta": mload.zeta,
        },
    )
