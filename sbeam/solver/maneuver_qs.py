"""Phase G0 — DLM-free quasi-steady transient maneuver-loads solver.

This is increment 1 of Phase G0 (the realistic, DLM-free path to a ZAERO
``MLOADS``-style transient maneuver capability).  It time-integrates the elastic
response of the airframe to a prescribed (open-loop) pilot-command history,
starting from a Step 53 static balanced-trim initial condition, and recovers the
net applied maneuver loads (aero + rigid inertia + elastic inertia + damping, #3)
at each output time.

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

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.model.maneuver import Tabled1
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.stiffness import get_spc_dofs
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.integration import build_djk
from sbeam.solver.modal_basis import (
    AsetOperators, assemble_aset_operators, yaw_reference_loading,
)
from sbeam.results.results import ManeuverStep, ManeuverResult, peak_grid_force
from sbeam.results.section_cuts import (
    SectionCutPlan, evaluate_section_cut, prepare_section_cuts,
)
from sbeam.results.monitor_points import (
    MonitorPlan, evaluate_monitor_point, prepare_monitor_points,
)
from sbeam.results.section_envelope import (
    build_monitor_envelope, build_section_envelope,
)
from sbeam.solver.sol101 import recover_bar_forces, recover_reactions
from sbeam.assembly.reduction import AsetReduction, expand_to_g
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.solver.sol144_util import (
    AeroCache,
    urdd_rcsid_to_basic,
    load_resultant,
    pitch_moment,
)
from sbeam.types import FloatArray, SparseMatrix


@dataclass
class Operators:
    """Re-assembled a-set / l-set operators mirroring run_sol144_trim's assembly.

    Kept local to the maneuver solver; the matrices are exactly those the trim
    builds, so the steady state of the time integration coincides with the
    Step 53 static solution.
    """
    all_labels: list[str]
    label_to_col: dict[str, int]
    T: FloatArray
    free_local: list[int]
    red_dofs: list[int]
    free_dofs: list[int]
    l_idx: list[int]                  # l-set indices into the a-set (non-SUPORT)
    suport_local: list[int]           # SUPORT (r-set) a-set indices, Phi_r column order
    K_eff_ll: FloatArray         # K_ll − q·Q_ll
    M_ll: FloatArray
    Q_ax_l: FloatArray
    M_ax_l: FloatArray
    f_aero_l: FloatArray
    M_ax_g: FloatArray
    aero: AeroModel
    D_jx: FloatArray
    djk: FloatArray
    q: float
    x_ref: float
    suport_pos: FloatArray
    R_rcsid: FloatArray
    has_rcsid: bool
    # ---- Step 68: per-sample section-cut recovery ----
    red: AsetReduction                # for the a-set -> g-set expansion
    M_gg: SparseMatrix                # elastic-inertia load is formed in the g-set
    K_gg: SparseMatrix                # reaction recovery (R = K·u − f)
    # MONSECT plans, resolved once per subcase (geometry + on-plane warnings);
    # empty when the deck has no MONSECT cards, which is the whole opt-in.
    cut_plans: dict[str, SectionCutPlan] = field(default_factory=dict)
    constrained_dofs: list[int] = field(default_factory=list)  # SPC + SUPORT g-set DOFs
    # #2: MONPNT1/MONPNT3 plans, resolved once like the cut plans.
    monitor_plans: dict[str, MonitorPlan] = field(default_factory=dict)


def assemble_operators(
    bulk: BulkData, subcase: SubcaseControl, aero: AeroModel, q: float,
    ops_a: Optional["AsetOperators"] = None,
    f_box_ref: Optional[FloatArray] = None,
) -> Operators:
    """Build the a-set / l-set matrices the transient integration needs.

    The a-set assembly is the shared ``modal_basis.assemble_aset_operators``
    (Step 61) — the same matrices ``run_sol144_trim`` builds (Q_ax, K_aa, Q_aa,
    M_ax, baseline aero, RCSID transform).  This function adds only the l-set
    partition (SUPORT DOFs dropped) and the dynamic-pressure scaling.  A caller
    that already holds the a-set operators for this subcase (the Step 63
    free-flight solver) passes them via ``ops_a`` to skip the second assembly.
    """
    ops = (ops_a if ops_a is not None
           else assemble_aset_operators(bulk, subcase, aero, f_box_ref=f_box_ref))

    all_labels, label_to_col = ops.all_labels, ops.label_to_col
    x_ref, suport_pos = ops.x_ref, ops.suport_pos
    R_rcsid, has_rcsid = ops.R_rcsid, ops.has_rcsid
    D_jx = ops.D_jx

    red = ops.red
    T, free_local, free_dofs = red.T, red.free_local, red.free_dofs
    ncols = list(range(len(all_labels)))

    Q_ax_a, K_aa, Q_aa, M_aa = ops.Q_ax_a, ops.K_aa, ops.Q_aa, ops.M_aa
    M_ax_g, M_ax_a = ops.M_ax_g, ops.M_ax_a

    f_aero_a = red.reduce_vector(q * ops.f_aero_g_unit)

    # l-set partition (drop the SUPORT DOFs — the mean-axis restraint).
    suport_local = ops.suport_local
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

    # ---- Step 68: MONSECT plans + the reaction DOF set, resolved once ---- #
    # The geometry, the masks and the on-plane warnings are state-free, so they
    # are built here rather than inside the time loop; a 2000-sample run would
    # otherwise rebuild them (and re-warn) 2000 times.
    grid_index = ops.grid_index
    cut_plans: dict[str, SectionCutPlan] = {}
    monitor_plans: dict[str, MonitorPlan] = {}
    constrained_dofs: list[int] = []
    if bulk.monsects:
        cut_plans = prepare_section_cuts(bulk, aero, grid_index)
    if bulk.monpnt1s or bulk.monpnt3s:
        # #2: the DEF-M10 mass-coverage warning is NOT re-issued here — the IC
        # trim this run starts from has already computed (and warned on) the
        # same monitors, so a 2000-sample run warns exactly once.
        monitor_plans = prepare_monitor_points(bulk, aero, grid_index)
    # A SET1-backed cut spanning a constrained grid carries its reaction across
    # the plane, and a MONPNT3 over a constrained grid carries it in the sum —
    # the same reason run_sol144_trim recovers reactions for both.  Aero-only
    # (AELIST) cuts and MONPNT1s never need them.
    if (any(p.listtype == "SET1" for p in cut_plans.values())
            or bool(bulk.monpnt3s)):
        if subcase.spc_sid:
            constrained_dofs += list(
                get_spc_dofs(bulk, subcase.spc_sid, grid_index))
        for sup in bulk.supports:
            if sup.gid in grid_index:
                base = grid_index[sup.gid] * 6
                constrained_dofs += [base + (int(ch) - 1) for ch in sup.dofs]

    return Operators(
        all_labels=all_labels, label_to_col=label_to_col,
        T=T, free_local=free_local, red_dofs=red.red_dofs, free_dofs=free_dofs,
        l_idx=l_idx, suport_local=list(suport_local),
        K_eff_ll=K_eff_ll, M_ll=M_ll, Q_ax_l=Q_ax_l, M_ax_l=M_ax_l,
        f_aero_l=f_aero_l, M_ax_g=M_ax_g, aero=aero, D_jx=D_jx, djk=djk,
        q=q, x_ref=x_ref, suport_pos=suport_pos, R_rcsid=R_rcsid, has_rcsid=has_rcsid,
        red=red, M_gg=ops.M_gg, K_gg=ops.K_gg,
        cut_plans=cut_plans, constrained_dofs=constrained_dofs,
        monitor_plans=monitor_plans,
    )


def delta_of_t(
    t: float, base_delta: dict[str, float], commands: list[tuple[str, int]],
    tabled1s: dict[int, Tabled1], all_labels: list[str],
) -> FloatArray:
    """Full label-ordered δ(t): commanded labels from their TABLED1, others held."""
    vals = dict(base_delta)
    for label, tabid in commands:
        vals[label] = tabled1s[tabid].evaluate(t)
    return np.array([vals.get(l, 0.0) for l in all_labels])


def force_l(ops: Operators, delta_arr: FloatArray) -> FloatArray:
    """l-set forcing F(t) = f_aero_l + q·Q_ax_l·δ + M_ax_l·δ_basic (mirror of trim RHS)."""
    delta_basic = urdd_rcsid_to_basic(
        delta_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid
    )
    return ops.f_aero_l + ops.q * (ops.Q_ax_l @ delta_arr) + ops.M_ax_l @ delta_basic


def recover_step(
    ops: Operators, bulk: BulkData, grid_index: dict[int, int],
    t: float, u_l: FloatArray, delta_arr: FloatArray, vals: dict[str, float],
    modal_coords: Optional[FloatArray] = None,
    xi_r: Optional[FloatArray] = None,
    xi_r_dot: Optional[FloatArray] = None,
    xi_r_ddot: Optional[FloatArray] = None,
    nz_rel: Optional[float] = None,
    elastic_accel_a: Optional[FloatArray] = None,
    damping_rate_a: Optional[FloatArray] = None,
) -> ManeuverStep:
    """Recover per-step displacements, CBAR loads, and the net applied load.

    The optional ``xi_r*``/``nz_rel`` fields are the Step 63 free-flight rigid
    states, passed through untouched — the recovery itself sees rigid motion
    only through the ``delta_arr`` labels the free-flight solver fills.

    ``elastic_accel_a`` / ``damping_rate_a`` (Step 68) are the a-set elastic
    acceleration ``ü_e`` and the damping rate vector ``w`` for which the damping
    force is ``M·w`` — mass-proportional ``α·u̇`` for the direct solver, modal
    ``Φ_e(2ζω)ξ̇_e`` for the modal one.  Both are turned into g-set loads here,
    in one place, so the two solvers cannot grow two definitions of the same
    force.  They are what a **section cut** needs and the global closure does
    not: mean-axis orthogonality makes the rigid-row resultant of ``M·Φ_e ξ̈_e``
    exactly zero, so a whole-airplane resultant is blind to a term that a local
    free body carries in full.  Both are also folded into ``net_loads`` (#3),
    which is the full applied load at the sample.
    """
    aero = ops.aero
    # Scatter l-set displacement into the a-set (r-set = 0), expand to g-set so
    # RBAR/RBE3 slaves follow their masters (same as the trim recovery).
    n_a = len(ops.free_local)
    u_a = np.zeros(n_a)
    for li_idx, li in enumerate(ops.l_idx):
        u_a[li] = u_l[li_idx]
    displacements = expand_to_g(u_a, ops.T, ops.free_local, len(ops.red_dofs))

    # CBAR force recovery (reuses sol101 unchanged).
    bar_forces = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid] = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)

    # Instantaneous aero box forces at this state (steady VLM, Level 1).
    w_struct = ops.djk @ (aero.require_g_slope() @ displacements)
    w_total = w_struct + ops.D_jx @ delta_arr + aero.wg
    gamma = aero.ajj_inv_corr @ w_total
    f_box_vec = aero.skj @ gamma                                   # force/q units
    grid_loads = aero.require_g_load().T @ (ops.q * f_box_vec)
    Fz_aero = float(ops.q * f_box_vec[2::3].sum())
    My_aero = float(ops.q * pitch_moment(f_box_vec, aero.boxes, ops.x_ref))

    # Inertial load from the instantaneous rigid-body acceleration (basic frame).
    delta_basic = urdd_rcsid_to_basic(
        delta_arr, ops.label_to_col, ops.R_rcsid, ops.has_rcsid)
    inertial_loads = ops.M_ax_g @ delta_basic

    # ---- Step 68: elastic-inertia and damping loads (g-set) ---- #
    # Same d'Alembert sign as the rigid column: M_ax_g IS −M_gg·Φ_r, so the
    # rigid load is −M·ü_rigid and the elastic one must be −M·ü_elastic.  Formed
    # in the g-set (M_gg·expand(ü_a)), never as a reduced force pushed back
    # through Tᵀ — that mapping is not well defined across an RBE3.
    elastic_inertial_loads = None
    damping_loads = None
    if elastic_accel_a is not None:
        elastic_inertial_loads = -(ops.M_gg @ ops.red.expand_to_g(elastic_accel_a))
    if damping_rate_a is not None:
        damping_loads = -(ops.M_gg @ ops.red.expand_to_g(damping_rate_a))

    # ---- The net load: the FULL applied load at this sample (#3) ---- #
    # K·u = F_aero − M·ü_rigid − M·ü_elastic − C·u̇, and ``net_loads`` is the
    # right-hand side entire: the exported FORCE/MOMENT cards, the closure and
    # the DEF-M5 critical-sample metric all read this one vector, so a stress
    # model that applies the cards statically recovers this sample's internal
    # loads (gate G1, tests/aero/test_maneuver_reapply.py).  The elastic and
    # damping terms are kept as separate fields as well because the section
    # cuts report them as their own columns.
    net_loads = grid_loads + inertial_loads
    if elastic_inertial_loads is not None:
        net_loads = net_loads + elastic_inertial_loads
    if damping_loads is not None:
        net_loads = net_loads + damping_loads
    closure = load_resultant(net_loads, bulk, grid_index, ops.suport_pos)

    # ---- Step 68 / #2: MONSECT section cuts and monitor points at this sample ---- #
    section_loads = None
    monitor_loads = None
    if ops.cut_plans or ops.monitor_plans:
        reactions = {}
        if ops.constrained_dofs:
            # R = K·u − f_applied, with ``net_loads`` the full applied load
            # (aero + rigid + elastic inertia + damping): the elastic d'Alembert
            # and damping forces act on the constrained DOFs too, and omitting
            # them would leave that difference sitting in the reaction.
            #
            # NOTE: no current sample deck exercises this.  It only bites when a
            # constrained grid carries mass; on HA144A the SPC/SUPORT grid 90 is
            # massless, so it is 0.0 there.  Written in the correct form
            # deliberately rather than to match a passing test.
            reactions = recover_reactions(
                bulk, displacements, ops.constrained_dofs, ops.K_gg,
                grid_index, net_loads)
        box_forces = (ops.q * f_box_vec).reshape(-1, 3)
        zero_g = np.zeros_like(net_loads)
        # On a transient sample the two extra columns are always *present*
        # (computed-and-zero when the solver has no elastic acceleration, e.g.
        # held at trim), as opposed to absent on a static trim — the
        # distinction the static outputs draw.
        elastic_g = (elastic_inertial_loads if elastic_inertial_loads is not None
                     else zero_g)
        damping_g = damping_loads if damping_loads is not None else zero_g
        if ops.cut_plans:
            section_loads = {
                name: evaluate_section_cut(
                    plan, box_forces, grid_loads, inertial_loads, grid_index,
                    reactions,
                    elastic_inertial_loads=elastic_g, damping_loads=damping_g,
                )
                for name, plan in ops.cut_plans.items()
            }
        if ops.monitor_plans:
            monitor_loads = {
                name: evaluate_monitor_point(
                    plan, box_forces, grid_loads, inertial_loads, reactions,
                    grid_index,
                    elastic_inertial_loads=elastic_g, damping_loads=damping_g,
                )
                for name, plan in ops.monitor_plans.items()
            }

    return ManeuverStep(
        t=t, trim_vars=dict(vals), displacements=displacements,
        bar_forces=bar_forces, grid_loads=grid_loads,
        inertial_loads=inertial_loads, net_loads=net_loads, closure=closure,
        Fz_aero=Fz_aero, My_aero=My_aero, modal_coords=modal_coords,
        xi_r=xi_r, xi_r_dot=xi_r_dot, xi_r_ddot=xi_r_ddot, nz_rel=nz_rel,
        elastic_inertial_loads=elastic_inertial_loads,
        damping_loads=damping_loads, section_loads=section_loads,
        monitor_loads=monitor_loads,
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

    # NMODES/METHOD/ZETA select the Step 62 modal solver (Mloads.selects_modal);
    # the main.py dispatch routes those cards to run_maneuver_modal, so this
    # solver only ever sees all-zeros cards and the increment-1 ignored-warning
    # is retired.

    # Initial condition: the Step 53 static balanced trim for the referenced TRIM.
    ic_subcase = SubcaseControl(
        subcase_id=subcase.subcase_id,
        spc_sid=subcase.spc_sid,
        trim_sid=mldtrim.trim_sid,
        trimobj_sid=subcase.trimobj_sid,
        massset_sid=subcase.massset_sid,   # Step 60: IC trim uses the same mass case
    )
    # Seed the AeroCache BEFORE the IC trim (DEF-R6): the trim then populates
    # it at the flight Mach, so the .get(ic.mach) below is a cache hit instead
    # of a second full AIC build.
    grid_index = build_grid_index(bulk)
    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)
    ic = run_sol144_trim(bulk, ic_subcase, aero, aero_cache=aero_cache)

    # Resolve the flight Mach / dynamic pressure from the IC trim, and the
    # Mach-correct AeroModel from the shared cache.
    q = ic.q
    aero = aero_cache.get(ic.mach)

    # Step 67a — yaw-rate wing term, scaled by the IC-trim loading frozen for the
    # whole time history.
    ops = assemble_operators(bulk, subcase, aero, q,
                             f_box_ref=yaw_reference_loading(aero, ic))

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
    delta0 = delta_of_t(t0, base_delta, commands, bulk.tabled1s, ops.all_labels)
    F0 = force_l(ops, delta0)
    u = scipy.linalg.solve(K, F0)                    # static l-set displacement
    v = np.zeros_like(u)
    a = np.zeros_like(u)

    def _vals_at(delta_arr: FloatArray) -> dict[str, float]:
        return {l: float(delta_arr[i]) for i, l in enumerate(ops.all_labels)}

    steps: list[ManeuverStep] = []
    times: list[float] = []

    def _scatter_l(x_l: FloatArray) -> FloatArray:
        """l-set vector -> a-set with the restrained r-set rows at zero."""
        x_a = np.zeros(len(ops.free_local))
        for li_idx, li in enumerate(ops.l_idx):
            x_a[li] = x_l[li_idx]
        return x_a

    def _emit(t: float, u_l: FloatArray, delta_arr: FloatArray,
              a_l: FloatArray, v_l: FloatArray) -> None:
        # Step 68: the l-set acceleration the integrator already carries IS the
        # elastic acceleration here (the rigid motion is prescribed through the
        # URDD labels, so u_l is purely elastic in the mean-axis frame).
        step = recover_step(
            ops, bulk, grid_index, t, u_l, delta_arr, _vals_at(delta_arr),
            elastic_accel_a=_scatter_l(a_l),
            damping_rate_a=(_scatter_l(damping_alpha * v_l)
                            if damping_alpha else None))
        steps.append(step)
        times.append(t)

    _emit(t0, u, delta0, a, v)
    for n in range(1, n_steps + 1):
        t = t0 + n * dt
        delta = delta_of_t(t, base_delta, commands, bulk.tabled1s, ops.all_labels)
        F = force_l(ops, delta)
        rhs = F + M @ (a0 * u + a2 * v + a3 * a) + C @ (a1 * u + a4 * v + a5 * a)
        u_new = scipy.linalg.lu_solve(K_hat_lu, rhs)
        a_new = a0 * (u_new - u) - a2 * v - a3 * a
        v_new = v + dt * ((1.0 - gamma) * a + gamma * a_new)
        u, v, a = u_new, v_new, a_new
        if n % out_every == 0 or n == n_steps:
            _emit(t, u, delta, a, v)

    # Critical sample = peak per-grid net force (DEF-M5).  One metric, shared with
    # the f06 table, the MLDPRNT column and the critical-sample export.
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
    )
    result.section_envelope = build_section_envelope(result)
    result.monitor_envelope = build_monitor_envelope(result)
    return result
