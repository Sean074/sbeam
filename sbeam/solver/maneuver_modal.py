"""Phase G0 Step 63 — free-flight modal transient maneuver solver (G0-b).

The self-balancing maneuver: the rigid modal coordinates ξ_r are states of the
coupled h-set Newmark system, so the net (aero + inertial) load closes to ≈ 0
for an arbitrary commanded *control* history — no per-step trim solve.  The
prescribed-rigid physics of increment 1 remains available through the direct
solver (`maneuver_qs.run_maneuver_qs`, selected by an all-zeros MLOADS card).

Coupled free-flight equation of motion (perturbation about the IC trim)
-----------------------------------------------------------------------
With Δξ = ξ − ξ_trim on the Step 61 free-free basis Φ = [Φ_r | Φ_e]::

    M_hh Δξ̈ + (C_s − q·B_hh) Δξ̇ + (K_hh − q·Q_hh) Δξ = q·Q_hc·Δδ_c(t)

    M_hh = Φᵀ M_aa Φ     (subcase mass case — fixed-Φ MASSSET rule, Step 60/62)
    K_hh = Φᵀ K_aa Φ     (rigid rows/cols ≡ 0: free flight = the rigid
                          partition is simply not constrained — no Schur
                          complement and no per-step re-trim; K̂ stays
                          nonsingular through a0·M_rr with M_rr ≻ 0)
    Q_hh, Q_hc, B_hh     from ``build_hset_gafs`` (their first production
                          consumer): modal GAF, AESURF control columns, and
                          the Level-1 quasi-steady rigid-rate GAF
    C_s[:, e-cols] = M_hh[:, e-cols]·diag(2 ζ ω_i)
                         (uniform elastic modal damping; built from the
                          case M_hh, NOT ``HsetGafs.C_hh``, so the damping
                          force is exactly M Φ_e (2ζω ξ̇_e) under a MASSSET)

The Δ-form keeps gravity and the trim forcing implicit: at Δδ_c = 0 the trim
IS the equilibrium, so the run starts exactly at rest (Δξ = Δξ̇ = 0) and a
zero-command free response stays there to round-off.  Rigid trim labels
(ANGLEA/PITCH/URDD…) are **outputs** computed from Δξ_r/Δξ̇_r/Δξ̈_r; commanding
one in MLDCOMD under this solver is a hard error.

Scope (documented limits): linear inertial-frame rigid coordinates at fixed V
(the steady pull-up is reachable since α = θ − ḣ/V settles); no phugoid/speed
DOF, no large attitude; determined command sets only (over-determined transient
allocation is G0-e); symmetric-maneuver lateral-attitude mapping deliberately
unencoded (`_RIGID_LABELS`).

Recovery — the label-fill consistency identity
----------------------------------------------
Per output step the TOTAL trim-label vector δ(t) is reconstructed:

  * commanded AESURF labels: their TABLED1 values (tables are totals);
  * attitude (displacement) labels, e.g. ANGLEA from pitch: trim value plus
    the SUPORT-frame attitude ``η_r = Δξ_r + (Φ_rr⁻¹ Φ_e,r) Δξ_e`` — the
    restrained re-split of the whole field Φ_r Δξ_r + Φ_e Δξ_e =
    Φ_r η_r + Ψ_e Δξ_e (Step 62's Eq. 41 applied per step), so the label path
    plus the Ψ_e deformation reproduces q·Q_aa·u exactly;
  * rate labels (PITCH/SIDES/ROLL/YAW and ANGLEA's −ḣ/V term): trim value
    plus the MEAN-AXIS rates Δξ̇_r through ``rigid_state_label_increments`` —
    the SAME ``rigid_rate_scales`` factors that built B_hh, whose columns are
    by construction the rescaled ``build_djx`` label columns, so the ``D_jx``
    path reproduces q·B_hh·Δξ̇ exactly;
  * URDD labels: trim value plus the MEAN-AXIS Δξ̈_r, added in the basic frame
    and rotated back to RCSID (``urdd_basic_to_rcsid``) — since
    M_ax = −M_gg Φ_r is definitional (Q4/DEF-M3), ``recover_step``'s
    M_ax_g·δ_basic then equals −M Φ_r ξ̈_r exactly, and the elastic inertia
    M Φ_e Δξ̈_e needs no load-side term at all: its rigid-row resultant is
    zero by mean-axis orthogonality.  (Feeding η̈_r instead would inject the
    elastic ringing straight into the closure.)

The shared ``maneuver_qs.recover_step`` therefore needs NO free-flight changes;
its closure output measures the true self-balancing residual (the discrete
Newmark residual, ~round-off), the G0-b headline metric.

Mode-acceleration recovery (D2 output convention: displacements elastic-only,
u_r = 0; rigid motion is reported through the label histories and the per-step
``xi_r``/``xi_r_dot``/``xi_r_ddot`` states)::

    u_l = K_eff_ll⁻¹ (F_l(δ_total) − M_aa Φ_e Δξ̈_e|_l − M_aa Φ_e (2ζω Δξ̇_e)|_l)

Only the ELASTIC inertia/damping is subtracted — the rigid inertia already
arrived in F_l through the M_ax·δ_basic path (subtracting M_aa Φ Δξ̈ with the
full Φ would double-count it).  At t0 (Δξ = 0) this is the Step 53 static
solution, truncation-independent; at a settled state it is the static trim
solve at the settled δ.

Fixed-Φ mass cases (Step 60 MASSSET)
------------------------------------
The basis Φ is built once from the BASELINE mass case; a MASSSET subcase swaps
only the mass side (M_hh = Φᵀ M_aa,case Φ, M_ax,case) and the IC trim.  K_hh
and the aero operators (Q_hh/Q_hc/B_hh) depend only on geometry and Mach and
are reused.  ``ManeuverBasisCache`` holds the untruncated basis per
(spc_sid, EIGRL sid); the D4 CG-shift warning is unchanged.

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
from sbeam.results.section_envelope import (
    build_monitor_envelope, build_section_envelope,
)
from sbeam.solver.maneuver_qs import (
    assemble_operators,
    delta_of_t,
    force_l,
    recover_step,
)
from sbeam.solver.modal_basis import (
    ManeuverBasis,
    assemble_aset_operators,
    build_hset_gafs,
    build_maneuver_basis,
    rigid_state_label_increments,
    truncate_basis,
    yaw_reference_loading,
)
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.solver.sol144_util import (
    AeroCache,
    urdd_basic_to_rcsid,
    urdd_rcsid_to_basic,
)
from sbeam.types import FloatArray

# CG shift (fraction of c_ref) beyond which the frozen mean axis of the
# baseline basis is considered materially wrong for a MASSSET case (D4).
_CG_SHIFT_WARN_FRAC = 0.05


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
        self._cache: dict[tuple[Optional[int], int], ManeuverBasis] = {}
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


def _check_commanded_labels(
    bulk: BulkData, mldcomd_sid: int, commands: list[tuple[str, int]]
) -> None:
    """D5: under the free-flight solver only AESURF controls may be commanded."""
    aesurf_labels = {s.label for s in bulk.aesurfs.values()}
    for label, _tabid in commands:
        if label not in aesurf_labels:
            raise ValueError(
                f"run_maneuver_modal: MLDCOMD {mldcomd_sid} commands "
                f"rigid-state label '{label}' — under the free-flight modal "
                "solver ANGLEA/PITCH/URDD/... are outputs computed from the "
                "rigid states, not inputs.  Command AESURF controls only, or "
                "use the direct solver (all-zeros MLOADS NMODES/METHOD/ZETA) "
                "for prescribed-rigid studies."
            )


def _warn_unrepresented_labels(
    basis: ManeuverBasis, label_to_col: dict[str, int]
) -> None:
    """Warn once when a rigid state has no trim label to carry it in recovery.

    The EOM still integrates that state's aerodynamics/inertia (Q_hh/B_hh/M_hh
    never involve the label list), but the recovery reconstructs its effect
    through the trim-label columns — a missing label makes the recovered loads
    (and closure) blind to that state.
    """
    missing: list[str] = []
    for _col, entry in basis.rigid_label_map.items():
        for key in ("accel", "rate", "disp"):
            lbl = entry[key]
            if lbl is not None and lbl not in label_to_col:
                missing.append(lbl)
    if missing:
        warnings.warn(
            "run_maneuver_modal: rigid-state trim label(s) "
            f"{sorted(set(missing))} are not defined as AESTAT cards — the "
            "recovered loads and closure cannot represent those states.  Add "
            "the AESTAT card(s) for a consistent free-flight recovery.",
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
    """Step 63 free-flight modal transient maneuver-loads solve.

    Selected by ``main.py`` when the MLOADS card requests it
    (``Mloads.selects_modal``: any of NMODES/METHOD/ZETA nonzero, METHOD=-1
    for the all-defaults-modal sentinel).  Requires RHOREF on the IC TRIM card
    (the rigid-rate aerodynamics B_hh need the true airspeed V = sqrt(2q/ρ)).

    Args:
        bulk:        Parsed BulkData — same requirements as ``run_maneuver_qs``,
                     plus RHOREF on the MLDTRIM-referenced TRIM.
        subcase:     SubcaseControl — uses ``mloads_sid``, ``spc_sid`` and
                     ``massset_sid`` (Step 60 mass case).
        aero:        AeroModel (seeds the AeroCache; rebuilt at the TRIM Mach).
        aero_cache:  Optional shared AeroCache.
        basis_cache: Optional job-level ManeuverBasisCache (D3); ``None``
                     builds a fresh basis for this subcase.
        recovery:    "acceleration" (default; mode-acceleration with inertia
                     relief) or "displacement" (u_l = u_l,trim + Φ_e Δξ_e|_l;
                     test/reference only — the convergence gate quantifies how
                     much worse it is).

    Returns:
        ManeuverResult with per-step ``modal_coords`` (full Δξ), the rigid
        states ``xi_r``/``xi_r_dot``/``xi_r_ddot``, ``nz_rel``, and
        ``n_modes_used`` / ``basis_info`` set.
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

    commands = mldcomd.commands if mldcomd is not None else []
    if mldcomd is not None:
        _check_commanded_labels(bulk, mldcomd.sid, commands)

    # True airspeed for the rigid-rate aerodynamics (B_hh): RHOREF mandatory.
    trim_card = bulk.trims[mldtrim.trim_sid]
    try:
        v_inf = trim_card.velocity()
    except ValueError as exc:
        raise ValueError(
            "run_maneuver_modal: the free-flight maneuver needs the true "
            "airspeed V = sqrt(2q/rho) for the rigid-rate aerodynamics "
            f"(B_hh) — add the RHOREF pseudo-label to TRIM {mldtrim.trim_sid}."
            f"  ({exc})"
        ) from exc

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

    # Shared a-set operators (mass case included) once; the l-set recovery
    # operators reuse them instead of re-assembling.
    # Step 67a — the yaw-rate wing term is scaled by the IC-trim loading, frozen
    # for the whole time history (fixed-Φ discipline); None-safe on decks with
    # no YAW label, where it changes nothing.
    f_box_ref = yaw_reference_loading(aero, ic)
    ops_a = assemble_aset_operators(bulk, subcase, aero, f_box_ref=f_box_ref)
    ops = assemble_operators(bulk, subcase, aero, q, ops_a=ops_a)

    eigrl_sid = mload.method if mload.method > 0 else 0
    if basis_cache is not None:
        basis_full = basis_cache.get(subcase, eigrl_sid)
    else:
        basis_full = _build_basis(bulk, subcase, aero, eigrl_sid)
    basis = truncate_basis(basis_full, mload.nmodes)
    n_r, n_e, n_h = basis.n_r, basis.n_e, basis.n_h

    _warn_unrepresented_labels(basis, ops.label_to_col)

    # Case-mean-axis correction (MASSSET): the baseline Φ_e is mass-orthogonal
    # to Φ_r under the BASELINE mass only; under a mass case Φ_rᵀ M_case Φ_e ≠ 0
    # and the elastic inertia would acquire a rigid-row resultant the recovery
    # (whose only inertia channel is M_ax·URDD = −M Φ_r·δ̈) cannot represent —
    # a closure error proportional to the overlay.  Re-orthogonalize the
    # elastic columns against Φ_r under the CASE mass (a cheap projection —
    # same eigensolve, same span, still fixed-Φ):
    #     Φ_e ← Φ_e − Φ_r · M_rr,case⁻¹ (Φ_rᵀ M_case Φ_e)
    # After this every Step 63 identity (mean-axis elastic inertia, closure)
    # holds exactly in the case coordinates.
    if subcase.massset_sid is not None:
        phi0 = basis.phi
        M_case = phi0.T @ ops_a.M_aa @ phi0
        X = scipy.linalg.solve(
            M_case[:n_r, :n_r], M_case[:n_r, n_r:], assume_a="sym")
        phi_corr = phi0.copy()
        phi_corr[:, n_r:] -= phi0[:, :n_r] @ X
        basis = replace(basis, phi=phi_corr)

    gafs = build_hset_gafs(bulk, ops_a, basis, aero, v_inf, zeta=mload.zeta,
                           f_box_ref=f_box_ref)

    phi = basis.phi
    phi_r = phi[:, :n_r]
    phi_e = phi[:, n_r:]

    # Restrained decomposition for RECOVERY (the EOM stays in mean-axis
    # coordinates): the mean-axis elastic modes carry rigid content at the
    # SUPORT DOFs (mass-orthogonality ≠ zero r-rows), so the total motion is
    # re-split per step (Step 62's Eq. 41 applied pointwise) as
    #
    #     Φ_r ξ_r + Φ_e ξ_e  =  Φ_r η_r + Ψ_e ξ_e,
    #     η_r = ξ_r + (Φ_rr⁻¹ Φ_e,r) ξ_e,     Ψ_e = Φ_e − Φ_r (Φ_rr⁻¹ Φ_e,r)
    #
    # with Ψ_e ≡ 0 at the SUPORT DOFs.  η_r is the rigid attitude/motion AT the
    # SUPORT point — the quantity the trim labels describe — and Ψ_e ξ_e is the
    # deformation the D2 (u_r = 0) displacement output reports.  Using raw
    # ξ_r/Φ_e here would drop the elastic modes' rigid content (and the
    # K_eff_lr coupling of the l-row equilibrium), a dt-independent closure
    # error.
    r_rows = ops.suport_local
    phi_rr = phi_r[r_rows, :]
    try:
        coeff = np.linalg.solve(phi_rr, phi_e[r_rows, :])   # (n_r, n_e)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "run_maneuver_modal: the rigid basis restricted to the SUPORT "
            "DOFs is singular — the SUPORT DOF set does not span the rigid "
            f"modes about the reference point.  ({exc})"
        ) from exc
    psi_e = phi_e - phi_r @ coeff                           # (n_a, n_e)

    # ---- Coupled h-set operators (dense n_h × n_h) ----
    # Mass from the SUBCASE M_aa (fixed-Φ MASSSET rule: baseline Φ, case mass).
    M = phi.T @ ops_a.M_aa @ phi
    omega = 2.0 * np.pi * basis.elastic_freqs_hz            # (n_e,)
    c_rate = 2.0 * mload.zeta * omega                       # per-mode damping rate
    C_struct = np.zeros((n_h, n_h))
    if mload.zeta:
        # Physical damping force M Φ_e (2ζω Δξ̇_e), projected — exact under a
        # MASSSET where the elastic mass block is no longer identity.
        C_struct[:, n_r:] = M[:, n_r:] * c_rate[np.newaxis, :]
    C = C_struct - q * gafs.B_hh                            # unsymmetric
    K = basis.K_hh - q * gafs.Q_hh

    # Recovery operator: K_eff_ll LU shared with the mode-acceleration formula
    # (the direct solver's effective stiffness, aero included).
    K_eff_lu = scipy.linalg.lu_factor(ops.K_eff_ll)

    base_delta = {l: float(ic.trim_vars.get(l, 0.0)) for l in ops.all_labels}
    ctrl_cols = [ops.label_to_col[l] for l in gafs.ctrl_labels]
    base_ctrl = np.array([base_delta[l] for l in gafs.ctrl_labels])
    urdd_cols = {col: ops.label_to_col.get(f"URDD{dof}")
                 for col, dof in enumerate(basis.rigid_dofs)}

    # ---- Newmark-β (average acceleration: β=1/4, γ=1/2), n_h coordinates ----
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

    # K̂_rr = a0·M_rr − q·(Q_rr + a1·B_rr): nonsingular because M_rr ≻ 0 —
    # free flight is simply the unconstrained rigid partition.  LU handles the
    # B_hh asymmetry.
    K_hat = K + a1 * C + a0 * M
    K_hat_lu = scipy.linalg.lu_factor(K_hat)

    def _rhs_ext(t: float) -> tuple[FloatArray, FloatArray]:
        """(forcing q·Q_hc·Δδ_c(t), total δ(t) with rigid labels still held)."""
        delta_tot = delta_of_t(t, base_delta, commands, bulk.tabled1s, ops.all_labels)
        d_dc = delta_tot[ctrl_cols] - base_ctrl if ctrl_cols else np.zeros(0)
        return q * (gafs.Q_hc @ d_dc), delta_tot

    # Equilibrium start: the IC trim IS the equilibrium of the Δ-form, so
    # Δξ = Δξ̇ = 0 exactly.  Δξ̈₀ = M⁻¹·RHS(t0) is zero whenever the command
    # tables start at their trim values (M is invertible: M_rr ≻ 0 and the
    # elastic block is positive definite by construction).
    F_ext0, delta_tot0 = _rhs_ext(t0)
    xi = np.zeros(n_h)
    vxi = np.zeros(n_h)
    axi = scipy.linalg.solve(M, F_ext0)

    # Baseline basic-frame URDD3 for the NZ_REL ratio (D3).
    base_arr = np.array([base_delta[l] for l in ops.all_labels])
    base_basic = urdd_rcsid_to_basic(
        base_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid)
    urdd3_col = ops.label_to_col.get("URDD3")
    urdd3_basic0 = float(base_basic[urdd3_col]) if urdd3_col is not None else 0.0

    # Constant trim static l-set solution for the "displacement" reference mode
    # (None in mode-acceleration recovery, and never read there).
    u_l_trim = (scipy.linalg.lu_solve(K_eff_lu, force_l(ops, base_arr))
                if recovery == "displacement" else None)

    def _vals_at(delta_arr: FloatArray) -> dict[str, float]:
        return {l: float(delta_arr[i]) for i, l in enumerate(ops.all_labels)}

    steps: list[ManeuverStep] = []
    times: list[float] = []

    def _emit(t: float, delta_tot: FloatArray) -> None:
        dxi_r, dxi_e = xi[:n_r], xi[n_r:]
        dvxi_r, dvxi_e = vxi[:n_r], vxi[n_r:]
        daxi_r, daxi_e = axi[:n_r], axi[n_r:]
        # Rigid ATTITUDE at the SUPORT point (restrained decomposition): the
        # displacement labels must carry the rigid content of the whole field
        # Φ_r ξ_r + Φ_e ξ_e = Φ_r η_r + Ψ_e ξ_e, so the label path reproduces
        # q·Q_aa·u exactly.  Rates and accelerations stay MEAN-AXIS (ξ̇_r/ξ̈_r):
        # they mirror the EOM's B_hh ξ̇_r and M_ax ξ̈_r terms one-for-one, and
        # the elastic inertia M Φ_e ξ̈_e has zero rigid-row resultant by the
        # mean-axis orthogonality — injecting η̈_r here would add the elastic
        # ringing to the closure instead of cancelling it.
        eta_r = dxi_r + coeff @ dxi_e

        # Total δ for recovery: attitude labels gain η_r, rate labels ξ̇_r;
        # URDD labels gain Δξ̈_r in the basic frame.
        delta_arr = delta_tot.copy()
        incs = rigid_state_label_increments(basis, bulk, v_inf, eta_r, dvxi_r)
        for lbl, dv in incs.items():
            col = ops.label_to_col.get(lbl)
            if col is not None:
                delta_arr[col] += dv
        delta_basic = urdd_rcsid_to_basic(
            delta_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid)
        for col_r, lab_col in urdd_cols.items():
            if lab_col is not None:
                delta_basic[lab_col] += daxi_r[col_r]
        nz_rel = (float(delta_basic[urdd3_col]) / urdd3_basic0
                  if urdd3_col is not None and urdd3_basic0 != 0.0 else None)
        delta_arr = urdd_basic_to_rcsid(
            delta_basic, ops.label_to_col, ops.R_rcsid, ops.has_rcsid)

        F_l = force_l(ops, delta_arr)
        # Elastic acceleration and damping-rate fields, built ONCE outside the
        # recovery-mode branch (Step 68).  They were previously formed only on
        # the mode-acceleration path; leaving them there would make the
        # "displacement" recovery silently report section cuts with no elastic
        # inertia — the same physical sample answering differently depending on
        # a recovery switch.
        accel_a = phi_e @ daxi_e                        # ü_e, a-set
        damp_rate_a = (phi_e @ (c_rate * dvxi_e)) if mload.zeta else None
        if u_l_trim is not None:  # "displacement" recovery
            u_l = u_l_trim + (psi_e @ dxi_e)[ops.l_idx]
        else:
            f_inert = ops_a.M_aa @ accel_a
            f_damp = (ops_a.M_aa @ damp_rate_a if damp_rate_a is not None
                      else np.zeros_like(f_inert))
            u_l = scipy.linalg.lu_solve(
                K_eff_lu, F_l - f_inert[ops.l_idx] - f_damp[ops.l_idx])

        step = recover_step(
            ops, bulk, grid_index, t, u_l, delta_arr, _vals_at(delta_arr),
            modal_coords=xi.copy(),
            xi_r=dxi_r.copy(), xi_r_dot=dvxi_r.copy(), xi_r_ddot=daxi_r.copy(),
            nz_rel=nz_rel,
            elastic_accel_a=accel_a, damping_rate_a=damp_rate_a)
        steps.append(step)
        times.append(t)

    _emit(t0, delta_tot0)
    for n in range(1, n_steps + 1):
        t = t0 + n * dt
        F_ext, delta_tot = _rhs_ext(t)
        rhs = (F_ext
               + M @ (a0 * xi + a2 * vxi + a3 * axi)
               + C @ (a1 * xi + a4 * vxi + a5 * axi))
        xi_new = scipy.linalg.lu_solve(K_hat_lu, rhs)
        axi_new = a0 * (xi_new - xi) - a2 * vxi - a3 * axi
        vxi_new = vxi + dt * ((1.0 - gamma) * axi + gamma * axi_new)
        xi, vxi, axi = xi_new, vxi_new, axi_new
        if n % out_every == 0 or n == n_steps:
            _emit(t, delta_tot)

    crit_index = int(np.argmax([peak_grid_force(s) for s in steps])) if steps else 0

    result = ManeuverResult(
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
            "n_r": n_r,
            "n_e": n_e,
            "n_available": basis.n_available_elastic,
            "freqs_hz": basis.elastic_freqs_hz.tolist(),
            "orthogonality_residual": basis.orthogonality_residual,
            "n_massless": basis.n_massless,
            "zeta": mload.zeta,
            "free_flight": True,
            "v_inf": v_inf,
            "rigid_dofs": list(basis.rigid_dofs),
        },
    )
    result.section_envelope = build_section_envelope(result)
    result.monitor_envelope = build_monitor_envelope(result)
    return result
