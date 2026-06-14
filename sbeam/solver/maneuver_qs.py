"""Phase G0 — DLM-free quasi-steady transient maneuver-loads solver.

This is increment 1 of Phase G0 (the realistic, DLM-free path to a ZAERO
``MLOADS``-style transient maneuver capability).  It time-integrates the elastic
response of the airframe to a prescribed (open-loop) pilot-command history,
starting from a Step 53 static balanced-trim initial condition, and recovers the
net (aero + inertial) maneuver loads at each output time.

Level-1 quasi-steady aerodynamics
---------------------------------
The aerodynamic generalised force at each instant is the **steady** VLM evaluated
at the instantaneous structural deformation and the instantaneous trim-variable
state ``δ(t)`` (control deflections, attitude, and rigid-body rates via the
``build_djx`` rate columns).  There is no DLM, no aerodynamic lag, and no
apparent-mass state — those are the graded Level 2–4 follow-ons.  The method is
valid for slow maneuvers (reduced frequency ``k = ω·c_ref / (2V) ≲ 0.05–0.1``).

Restrained l-set formulation
----------------------------
Exactly like the Step 53 trim, the SUPORT (r-set) rigid-body DOFs are held at the
mean axis (``u_r = 0``) and the elastic l-set responds.  The rigid-body motion is
prescribed through the URDD trim labels in ``δ(t)`` and enters the structure as an
inertia-relief forcing ``M_ax · a(t)``.  The governing l-set equation integrated
in time is::

    M_ll ü_l + C_ll u̇_l + (K_ll − q·Q_ll) u_l
        =  f_aero_l(baseline)  +  q·Q_ax_l·δ(t)  +  M_ax_l·a_basic(t)

The right-hand side is identical to the Step 53 trim RHS when ``δ(t) = δ_trim``;
holding the commanded state at the trim value therefore makes the steady-state
solution reproduce the Step 53 balanced load to machine precision (the
quasi-static identity gate).  Time integration uses the unconditionally stable
Newmark-β average-acceleration scheme (β=1/4, γ=1/2).

Modal reduction (reuse of the SOL 103 eigenbasis with mode-acceleration recovery)
is the documented Level-1b follow-on; increment 1 integrates the l-set directly so
the static identity is exact rather than truncation-limited.

Public API:
    run_maneuver_qs(bulk, subcase, aero, aero_cache=None, damping_alpha=0.0)
"""

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa, build_fg
from sbeam.aero.integration import build_djx, build_djk
from sbeam.results.results import BarForce, ManeuverStep, ManeuverResult
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses
from sbeam.solver.sol144 import (
    AeroCache,
    _compute_aset_data,
    _build_inertial_cols,
    _urdd_rcsid_to_basic,
    _get_suport_local,
    _expand_to_g,
    _load_resultant,
    _pitch_moment,
    run_sol144_trim,
)


@dataclass
class _Operators:
    """Re-assembled a-set / l-set operators mirroring run_sol144_trim's assembly.

    Kept local to the maneuver solver; the matrices are exactly those the trim
    builds, so the steady state of the time integration coincides with the
    Step 53 static solution.
    """
    all_labels: list
    label_to_col: dict
    T: np.ndarray
    free_local: list
    red_dofs: list
    free_dofs: list
    l_idx: list                  # l-set indices into the a-set (non-SUPORT)
    K_eff_ll: np.ndarray         # K_ll − q·Q_ll
    M_ll: np.ndarray
    Q_ax_l: np.ndarray
    M_ax_l: np.ndarray
    f_aero_l: np.ndarray
    M_ax_g: np.ndarray
    aero: AeroModel
    D_jx: np.ndarray
    djk: np.ndarray
    q: float
    x_ref: float
    suport_pos: np.ndarray
    R_rcsid: np.ndarray
    has_rcsid: bool


def _assemble_operators(
    bulk: BulkData, subcase: SubcaseControl, aero: AeroModel, q: float
) -> _Operators:
    """Build the a-set / l-set matrices the transient integration needs.

    Mirrors the matrix assembly inside ``run_sol144_trim`` (Q_ax, K_aa, Q_aa,
    M_ax, baseline aero, RCSID transform), plus the structural mass matrix reduced
    to the l-set.  Re-assembled here rather than threaded through the trim result
    so the working trim path is untouched.
    """
    from sbeam.assembly.coord_transform import _get_transform

    grid_index = build_grid_index(bulk)
    spc_sid = subcase.spc_sid

    all_labels = sorted(
        [a.label for a in bulk.aestats.values()]
        + [s.label for s in bulk.aesurfs.values()]
    )
    label_to_col = {l: i for i, l in enumerate(all_labels)}

    aeros = bulk.aeros
    if aeros.rcsid:
        x_ref_pt, R_rcsid = _get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(x_ref_pt[0])
        suport_pos = x_ref_pt
        has_rcsid = True
    else:
        x_ref = 0.0
        R_rcsid = np.eye(3)
        suport_pos = np.zeros(3)
        has_rcsid = False

    # Trim-variable normalwash columns and the g-set aero sensitivity Q_ax.
    D_jx = build_djx(aero.boxes, all_labels, bulk)                  # (n_box, n_labels)
    Q_ax_g = aero.g_disp.T @ aero.skj @ aero.ajj_inv_corr @ D_jx    # (n_g, n_labels)

    T, dep_dofs, red_dofs, free_local, free_dofs = _compute_aset_data(
        bulk, grid_index, spc_sid
    )
    ncols = list(range(len(all_labels)))

    # Reduce Q_ax, K, Q, structural mass to the a-set (same RBE3+SPC path as trim).
    Q_ax_red = (T.T @ Q_ax_g) if dep_dofs else Q_ax_g
    Q_ax_a = Q_ax_red[np.ix_(free_local, ncols)]

    K_gg = assemble_global_stiffness(bulk)
    K_red = (T.T @ K_gg @ T) if dep_dofs else K_gg.toarray()
    if hasattr(K_red, "toarray"):
        K_red = K_red.toarray()
    K_aa = K_red[np.ix_(free_local, free_local)]

    Q_gg = build_qaa(aero, aero.g_disp, aero.g_slope)
    Q_red = (T.T @ Q_gg @ T) if dep_dofs else Q_gg
    Q_aa = Q_red[np.ix_(free_local, free_local)]

    M_gg = assemble_global_mass(bulk)
    M_red = (T.T @ M_gg @ T) if dep_dofs else M_gg.toarray()
    if hasattr(M_red, "toarray"):
        M_red = M_red.toarray()
    M_aa = M_red[np.ix_(free_local, free_local)]

    # Baseline aero load and inertial sensitivity (basic frame) on the g-set.
    f_aero_g = q * build_fg(aero, aero.g_disp)                      # (n_g,)
    M_ax_g = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)

    f_aero_red = (T.T @ f_aero_g) if dep_dofs else f_aero_g
    f_aero_a = f_aero_red[free_local]
    M_ax_red = (T.T @ M_ax_g) if dep_dofs else M_ax_g
    M_ax_a = M_ax_red[np.ix_(free_local, ncols)]

    # l-set partition (drop the SUPORT DOFs — the mean-axis restraint).
    suport_local = _get_suport_local(bulk, free_dofs, grid_index)
    if not suport_local:
        raise ValueError(
            "run_maneuver_qs: no SUPORT DOFs found — Phase G0 requires a free "
            "aircraft (SUPORT card) so the rigid-body mean axis is defined."
        )
    n_a = K_aa.shape[0]
    r_set = set(suport_local)
    l_idx = [i for i in range(n_a) if i not in r_set]

    K_eff_ll = (K_aa - q * Q_aa)[np.ix_(l_idx, l_idx)]
    M_ll = M_aa[np.ix_(l_idx, l_idx)]
    Q_ax_l = Q_ax_a[np.ix_(l_idx, ncols)]
    M_ax_l = M_ax_a[np.ix_(l_idx, ncols)]
    f_aero_l = f_aero_a[l_idx]

    djk = build_djk(aero.boxes)

    return _Operators(
        all_labels=all_labels, label_to_col=label_to_col,
        T=T, free_local=free_local, red_dofs=red_dofs, free_dofs=free_dofs,
        l_idx=l_idx, K_eff_ll=K_eff_ll, M_ll=M_ll, Q_ax_l=Q_ax_l, M_ax_l=M_ax_l,
        f_aero_l=f_aero_l, M_ax_g=M_ax_g, aero=aero, D_jx=D_jx, djk=djk,
        q=q, x_ref=x_ref, suport_pos=suport_pos, R_rcsid=R_rcsid, has_rcsid=has_rcsid,
    )


def _delta_of_t(
    t: float, base_delta: dict, commands: list, tabled1s: dict, all_labels: list
) -> np.ndarray:
    """Full label-ordered δ(t): commanded labels from their TABLED1, others held."""
    vals = dict(base_delta)
    for label, tabid in commands:
        vals[label] = tabled1s[tabid].evaluate(t)
    return np.array([vals.get(l, 0.0) for l in all_labels])


def _force_l(ops: _Operators, delta_arr: np.ndarray) -> np.ndarray:
    """l-set forcing F(t) = f_aero_l + q·Q_ax_l·δ + M_ax_l·δ_basic (mirror of trim RHS)."""
    delta_basic = _urdd_rcsid_to_basic(
        delta_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid
    )
    return ops.f_aero_l + ops.q * (ops.Q_ax_l @ delta_arr) + ops.M_ax_l @ delta_basic


def _recover_step(
    ops: _Operators, bulk: BulkData, grid_index: dict,
    t: float, u_l: np.ndarray, delta_arr: np.ndarray, vals: dict,
) -> ManeuverStep:
    """Recover per-step displacements, CBAR loads, and net (aero+inertial) loads."""
    aero = ops.aero
    # Scatter l-set displacement into the a-set (r-set = 0), expand to g-set so
    # RBAR/RBE3 slaves follow their masters (same as the trim recovery).
    n_a = len(ops.free_local)
    u_a = np.zeros(n_a)
    for li_idx, li in enumerate(ops.l_idx):
        u_a[li] = u_l[li_idx]
    displacements = _expand_to_g(u_a, ops.T, ops.free_local, len(ops.red_dofs))

    # CBAR force recovery (reuses sol101 unchanged).
    bar_forces = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid] = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)

    # Instantaneous aero box forces at this state (steady VLM, Level 1).
    w_struct = ops.djk @ (aero.g_slope @ displacements)
    w_total = w_struct + ops.D_jx @ delta_arr + aero.wg
    gamma = aero.ajj_inv_corr @ w_total
    f_box_vec = aero.skj @ gamma                                   # force/q units
    grid_loads = aero.g_disp.T @ (ops.q * f_box_vec)
    Fz_aero = float(ops.q * f_box_vec[2::3].sum())
    My_aero = float(ops.q * _pitch_moment(f_box_vec, aero.boxes, ops.x_ref))

    # Inertial load from the instantaneous rigid-body acceleration (basic frame).
    delta_basic = _urdd_rcsid_to_basic(
        delta_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid)
    inertial_loads = ops.M_ax_g @ delta_basic
    net_loads = grid_loads + inertial_loads
    closure = _load_resultant(net_loads, bulk, grid_index, ops.suport_pos)

    return ManeuverStep(
        t=t, trim_vars=dict(vals), displacements=displacements,
        bar_forces=bar_forces, grid_loads=grid_loads,
        inertial_loads=inertial_loads, net_loads=net_loads, closure=closure,
        Fz_aero=Fz_aero, My_aero=My_aero,
    )


def run_maneuver_qs(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional[AeroCache] = None,
    damping_alpha: float = 0.0,
) -> ManeuverResult:
    """Phase G0 quasi-steady transient maneuver-loads solve.

    Args:
        bulk:          Parsed BulkData — must include SUPORT, the MLOADS card set
                       referenced by ``subcase.mloads_sid``, and the TRIM the
                       MLDTRIM points to.
        subcase:       SubcaseControl — uses ``mloads_sid`` and ``spc_sid``.
        aero:          AeroModel (seeds the AeroCache; rebuilt at the TRIM Mach).
        aero_cache:    Optional shared AeroCache.
        damping_alpha: Mass-proportional (Rayleigh) structural damping coefficient
                       ``C_ll = α·M_ll`` (default 0 — undamped).  Aerodynamic and
                       modal structural damping are Level-1b/2 follow-ons.

    Returns:
        ManeuverResult with one ManeuverStep per output sample.
    """
    if subcase.mloads_sid is None or subcase.mloads_sid not in bulk.mloads:
        raise ValueError(
            f"run_maneuver_qs: MLOADS SID {subcase.mloads_sid} not found")
    mload = bulk.mloads[subcase.mloads_sid]
    mldtrim = bulk.mldtrims[mload.mldtrim]
    mldtime = bulk.mldtimes[mload.mldtime]
    mldcomd = bulk.mldcomds.get(mload.mldcomd) if mload.mldcomd else None
    mldprnt = bulk.mldprnts.get(mload.mldprnt) if mload.mldprnt else None

    if mload.nmodes:
        warnings.warn(
            "run_maneuver_qs: MLOADS NMODES is reserved for the Level-1b modal "
            "reduction (a Phase G0 follow-on); increment 1 integrates the l-set "
            "directly and ignores NMODES.",
            UserWarning,
        )

    # Initial condition: the Step 53 static balanced trim for the referenced TRIM.
    ic_subcase = SubcaseControl(
        subcase_id=subcase.subcase_id,
        spc_sid=subcase.spc_sid,
        trim_sid=mldtrim.trim_sid,
        trimobj_sid=subcase.trimobj_sid,
    )
    ic = run_sol144_trim(bulk, ic_subcase, aero, aero_cache=aero_cache)

    # Resolve the flight Mach / dynamic pressure from the IC trim, and the
    # Mach-correct AeroModel (the AeroCache built/seeded inside the trim solve).
    q = ic.q
    if aero_cache is None:
        aero_cache = AeroCache(bulk, build_grid_index(bulk), seed=aero)
    aero = aero_cache.get(ic.mach)

    ops = _assemble_operators(bulk, subcase, aero, q)
    grid_index = build_grid_index(bulk)

    # Base δ held for any label the command set does not drive = the trim value.
    base_delta = {l: float(ic.trim_vars.get(l, 0.0)) for l in ops.all_labels}
    commands = mldcomd.commands if mldcomd is not None else []

    # ---- Newmark-β (average acceleration: β=1/4, γ=1/2) ----
    t0, tend, dt = mldtime.t0, mldtime.tend, mldtime.dt
    n_steps = int(round((tend - t0) / dt))
    tout = mldtime.tout if mldtime.tout > 0 else dt
    out_every = max(1, int(round(tout / dt)))

    M = ops.M_ll
    C = damping_alpha * M
    K = ops.K_eff_ll
    beta, gamma = 0.25, 0.5
    a0 = 1.0 / (beta * dt * dt)
    a1 = gamma / (beta * dt)
    a2 = 1.0 / (beta * dt)
    a3 = 1.0 / (2.0 * beta) - 1.0
    a4 = gamma / beta - 1.0
    a5 = dt * 0.5 * (gamma / beta - 2.0)

    # K_eff_ll is full rank, so K_hat is invertible even when M_ll is singular
    # (lumped / CONM2-only models leave massless rotational DOFs).  The Newmark
    # update computes acceleration kinematically, never via M⁻¹, so singular mass
    # is tolerated throughout.
    K_hat = K + a1 * C + a0 * M
    K_hat_lu = scipy.linalg.lu_factor(K_hat)

    # Initial state: start from the static l-set solution for δ(t0) so the run
    # begins at equilibrium (MLDTRIM = steady-state initial condition).  At
    # equilibrium K·u = F and v = 0, so the initial acceleration is exactly zero
    # (M·a = F − K·u = 0) — no M⁻¹ needed.
    delta0 = _delta_of_t(t0, base_delta, commands, bulk.tabled1s, ops.all_labels)
    F0 = _force_l(ops, delta0)
    u = scipy.linalg.solve(K, F0)                    # static l-set displacement
    v = np.zeros_like(u)
    a = np.zeros_like(u)

    def _vals_at(delta_arr):
        return {l: float(delta_arr[i]) for i, l in enumerate(ops.all_labels)}

    steps: list = []
    times: list = []

    def _emit(t, u_l, delta_arr):
        step = _recover_step(
            ops, bulk, grid_index, t, u_l, delta_arr, _vals_at(delta_arr))
        steps.append(step)
        times.append(t)

    _emit(t0, u, delta0)
    for n in range(1, n_steps + 1):
        t = t0 + n * dt
        delta = _delta_of_t(t, base_delta, commands, bulk.tabled1s, ops.all_labels)
        F = _force_l(ops, delta)
        rhs = F + M @ (a0 * u + a2 * v + a3 * a) + C @ (a1 * u + a4 * v + a5 * a)
        u_new = scipy.linalg.lu_solve(K_hat_lu, rhs)
        a_new = a0 * (u_new - u) - a2 * v - a3 * a
        v_new = v + dt * ((1.0 - gamma) * a + gamma * a_new)
        u, v, a = u_new, v_new, a_new
        if n % out_every == 0 or n == n_steps:
            _emit(t, u, delta)

    # Critical sample = peak net resultant-force magnitude (loads-team deliverable).
    crit_index = int(np.argmax([np.linalg.norm(s.closure[:3]) for s in steps])) \
        if steps else 0

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
    )
