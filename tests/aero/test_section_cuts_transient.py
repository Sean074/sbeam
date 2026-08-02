"""V-TSEC — MONSECT section cuts on transient (MLOADS) maneuvers (Step 68).

Fixture: the full-span HA144A deck, which already carries the Monitor Phase 2
``MONSECT SECRW`` right-wing cut (CID 2 = the wing SPLINE2 axis, stations
8/10/12/20).  The static behaviour of that cut is gated by
``tests/aero/test_section_cuts_sol144.py``; everything here is about what
changes when the same cut is taken at an instant of a maneuver.

The load-bearing gate is **V-TSEC3**.  A transient section cut needs a load
column no static trim has: the elastic d'Alembert load ``−M·ü_e``.  Every
*global* diagnostic sbeam already has is blind to it — mean-axis orthogonality
makes the rigid-row resultant of ``M·Φ_e ξ̈_e`` exactly zero, so the closure is
≈ 0 whether or not the term is present.  A section cut is a *local* resultant
and carries it in full, so the only way to catch a missing or mis-signed
elastic-inertia term is to compare a cut against the beam internal force it must
equal.  That is V-TSEC3.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.stiffness import transform_matrix
from sbeam.model.aero import Monsect
from sbeam.model.maneuver import Tabled1, Mldtime, Mldcomd, Mldtrim, Mloads
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.results.section_cuts import labelled
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol101 import _element_local_forces
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
G = 32.174  # ft/s²
CUT = "SECRW"


def _deck(n_z=2.0):
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.trims[1].vars["URDD3"] = load_factor_to_urdd3(n_z, G)
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
    return bulk, gi, aero


def _static(n_z=2.0):
    bulk, gi, aero = _deck(n_z)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return res, bulk, gi


def _maneuver(n_z=2.0, commands_builder=None, tend=0.4, dt=0.005, tout=0.02,
              damping_alpha=0.0):
    """Run an MLOADS transient on the n_z trim IC (direct l-set solver)."""
    bulk, gi, aero = _deck(n_z)
    labels = sorted([a.label for a in bulk.aestats.values()]
                    + [s.label for s in bulk.aesurfs.values()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        commands = (commands_builder(bulk, labels, ic.trim_vars)
                    if commands_builder is not None else [])
        bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
        bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=tend, dt=dt, tout=tout)
        if commands:
            bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
        bulk.mloads[1] = Mloads(sid=1, mldtrim=1, mldtime=1,
                                mldcomd=1 if commands else 0)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        res = run_maneuver_qs(bulk, sc, aero, damping_alpha=damping_alpha)
    return res, ic, bulk, gi


def _elevator_step(delta_rad=0.05, t_ramp=0.02):
    """A fast elevator input — deliberately abrupt, to excite elastic modes.

    V-TSEC3 is only a meaningful gate on a sample where ``ü_e`` is large enough
    to matter, so the command ramps in over 20 ms rather than the 0.3 s of the
    quasi-static settling tests.
    """
    def builder(bulk, labels, ic_vars):
        lbl = "ELEV" if "ELEV" in labels else labels[0]
        bulk.tabled1s[900] = Tabled1(
            tid=900, xs=[0.0, t_ramp, 100.0],
            ys=[float(ic_vars.get(lbl, 0.0)),
                float(ic_vars.get(lbl, 0.0)) + delta_rad,
                float(ic_vars.get(lbl, 0.0)) + delta_rad])
        return [(lbl, 900)]
    return builder


# --------------------------------------------------------------------------- #
# V-TSEC1 — quasi-static identity (the anchor gate)
# --------------------------------------------------------------------------- #

def test_vtsec1_held_at_trim_reproduces_the_static_table():
    """Commands held at trim ⇒ every sample's cut equals the static MONSECT table.

    This ties the whole transient path to the already-verified static one: the
    integrator's fixed point IS the Step 53 trim, so the section cut taken there
    must be the Step 53 section cut, station by station and component by
    component.
    """
    res, ic, _bulk, _gi = _maneuver()
    static = ic.section_loads[CUT]
    scale = max(np.max(np.abs(st.totals)) for st in static.stations)

    for step in res.steps:
        sc = step.section_loads[CUT]
        assert [s.station for s in sc.stations] == [s.station for s in static.stations]
        for a, b in zip(sc.stations, static.stations):
            assert np.max(np.abs(a.totals - b.totals)) < 1e-6 * scale, (
                f"t={step.t} station {a.station}: transient cut drifted from static")
            assert a.n_members == b.n_members
        # Held at trim there is no elastic acceleration, so the new columns are
        # computed-and-zero (not absent) — the distinction the static path draws.
        for a in sc.stations:
            assert a.elastic_inertia is not None
            assert np.max(np.abs(a.elastic_inertia)) < 1e-6 * scale


# --------------------------------------------------------------------------- #
# V-TSEC3 — free-body / CBAR equilibrium on a DYNAMIC sample
# --------------------------------------------------------------------------- #

def _to_basic(cid, v6, bulk):
    """Cut-frame 6-vector back to basic (mirrors the static V-SEC2 helper)."""
    _P, R = get_transform(cid, bulk.cord2rs)
    return R @ v6[:3], R @ v6[3:]


def _dynamic_sample(res):
    """The sample with the largest elastic d'Alembert load."""
    k = int(np.argmax([np.max(np.abs(s.elastic_inertial_loads)) for s in res.steps]))
    return k, res.steps[k]


@pytest.mark.parametrize("station", [8.0, 10.0])
def test_vtsec3_dynamic_cut_equals_the_beam_internal_force(station):
    """V-TSEC3 — the load-bearing gate, on a DYNAMIC sample.

    The transient analogue of the static V-SEC2: at a station crossing only
    CBAR 120, the resultant of everything outboard must equal that element's
    end-B internal force from ``K·u``.  The two routes are independent — one
    sums applied loads, the other is element stiffness × displacement — and they
    agree only if every load column the free body carries is present.

    This is what fails when the elastic d'Alembert load is missing: ``K·u``
    already contains it (the integrator solved for ``u`` with it on the RHS),
    while the load sum would not.
    """
    res, _ic, bulk, gi = _maneuver(commands_builder=_elevator_step())
    _k, step = _dynamic_sample(res)
    assert np.max(np.abs(step.elastic_inertial_loads)) > 0.0, (
        "no elastic inertia anywhere in the run — the command is not exciting "
        "the modes, so this gate would pass vacuously")

    sc = step.section_loads[CUT]
    st = next(s for s in sc.stations if s.station == station)
    cut_F, cut_M = _to_basic(sc.cid, st.totals, bulk)

    cbar = bulk.cbars[120]
    f_local = _element_local_forces(cbar, bulk.grids, bulk.pbars, bulk.mat1s,
                                    step.displacements, gi)
    R3 = transform_matrix(cbar, bulk.grids)[:3, :3]     # rows = local axes in basic
    fb = R3.T @ f_local[6:9]
    mb = R3.T @ f_local[9:12]
    gb = bulk.grids[cbar.gb]
    rb = np.array([gb.x, gb.y, gb.z])
    bar_M = mb + np.cross(rb - st.ref, fb)

    scale = max(np.linalg.norm(fb), 1.0)
    assert cut_F == pytest.approx(fb, abs=1e-8 * scale)
    m_scale = max(np.linalg.norm(bar_M), 1.0)
    assert cut_M == pytest.approx(bar_M, abs=1e-8 * m_scale)


def test_vtsec3_gate_would_fail_without_the_elastic_column():
    """The elastic column is not a rounding term — dropping it breaks V-TSEC3.

    Guards the gate above against becoming vacuous: if the elastic-inertia
    contribution were ever small enough to sit inside V-TSEC3's tolerance, that
    test would pass with the physics removed.  Here the cut is deliberately
    re-summed *without* the elastic column and must miss the beam force by far
    more than the tolerance.
    """
    res, _ic, bulk, gi = _maneuver(commands_builder=_elevator_step())
    _k, step = _dynamic_sample(res)
    sc = step.section_loads[CUT]
    st = next(s for s in sc.stations if s.station == 8.0)

    without = st.aero + st.inertia + st.reaction + st.damping
    cut_F, _cut_M = _to_basic(sc.cid, without, bulk)

    cbar = bulk.cbars[120]
    f_local = _element_local_forces(cbar, bulk.grids, bulk.pbars, bulk.mat1s,
                                    step.displacements, gi)
    R3 = transform_matrix(cbar, bulk.grids)[:3, :3]
    fb = R3.T @ f_local[6:9]

    err = np.linalg.norm(cut_F - fb)
    assert err > 1e-6 * max(np.linalg.norm(fb), 1.0), (
        "the elastic-inertia column is negligible on this sample — V-TSEC3 is "
        "not actually testing it; strengthen the command history")


def test_vtsec3b_elastic_column_moves_the_cut_by_its_own_resultant():
    """The elastic column is the free-body sum of −M·ü_e outboard of the plane.

    Recomputed here straight from ``step.elastic_inertial_loads`` and the grid
    positions — an independent check that the column is the outboard resultant
    of the g-set vector, with the moment taken about the cut reference point.
    """
    res, _ic, bulk, gi = _maneuver(commands_builder=_elevator_step())
    k = int(np.argmax([np.max(np.abs(s.elastic_inertial_loads))
                       for s in res.steps]))
    step = res.steps[k]
    sc = step.section_loads[CUT]
    f_el = step.elastic_inertial_loads

    # The cut's collection and frame, re-derived from the deck.
    from sbeam.assembly.coord_transform import get_transform
    P, R = get_transform(sc.cid, bulk.cord2rs)
    a_hat = R[:, sc.axis - 1]
    gids = [111, 112, 121, 122]
    pos = {g: np.array([bulk.grids[g].x, bulk.grids[g].y, bulk.grids[g].z])
           for g in gids}
    s_of = {g: float((pos[g] - P) @ a_hat) for g in gids}

    for st in sc.stations:
        ref = st.ref
        F = np.zeros(3)
        M = np.zeros(3)
        for g in gids:
            if s_of[g] <= st.station:          # strictly-outboard convention
                continue
            row = 6 * gi[g]
            f = f_el[row:row + 3]
            F += f
            M += f_el[row + 3:row + 6] + np.cross(pos[g] - ref, f)
        expected = np.concatenate([R.T @ F, R.T @ M])
        assert np.allclose(st.elastic_inertia, expected, rtol=1e-10, atol=1e-9)


# --------------------------------------------------------------------------- #
# V-TSEC4 / V-TSEC5 — trivial cuts and closure consistency
# --------------------------------------------------------------------------- #

def test_vtsec4_station_outboard_of_everything_is_zero():
    res, _ic, _b, _gi = _maneuver(commands_builder=_elevator_step())
    for step in res.steps:
        for st in step.section_loads[CUT].stations:
            if st.n_members == 0:
                assert np.allclose(st.totals, 0.0)
                assert np.allclose(st.elastic_inertia, 0.0)


def test_cut_columns_sum_to_the_totals_every_sample():
    """totals ≡ aero + inertia + reaction + elastic + damping, at every sample.

    Pins the contribution split: a column that silently failed to enter the sum
    (or entered twice) is otherwise invisible, because each column looks
    individually plausible.
    """
    res, _ic, _b, _gi = _maneuver(commands_builder=_elevator_step())
    for step in res.steps:
        sc = step.section_loads[CUT]
        for st in sc.stations:
            parts = (st.aero + st.inertia + st.reaction
                     + st.elastic_inertia + st.damping)
            assert np.allclose(st.totals, parts, rtol=1e-12, atol=1e-12)


def _whole_model_cut_deck(bulk):
    """Replace the deck's cuts with one plane inboard of EVERY grid.

    Note the collection is built here rather than reusing the deck's ``ALLGRID``
    AECOMP: that one omits GRID 90, the SUPORT/SPC reference grid.  On a static
    balanced trim the omission is invisible (the reaction is ~0), but a
    prescribed-rigid transient sample reacts its imbalance exactly there, so a
    whole-model free body that leaves GRID 90 out cannot close — which is the
    behaviour ``test_partial_collection_does_not_close`` pins.

    The CID origin is parked far inboard (y = −1000) so a single POS cut at
    station 0 captures everything, including the centreline grids a cut at
    y = 0 would split.
    """
    from sbeam.parser.bdf_reader import parse_bulk_data
    from sbeam.model.aero import Aecomp, Set1
    extra = parse_bulk_data([
        "CORD2R, 901, 0, 15.0, -1000.0, 0.0, 15.0, -1000.0, 1.0",
        "+, 16.0, -1000.0, 0.0",
    ])
    bulk.cord2rs.update(extra.cord2rs)
    bulk.set1s[9990] = Set1(sid=9990, grids=sorted(bulk.grids))
    bulk.aecomps["EVERYGRID"] = Aecomp(
        name="EVERYGRID", listtype="SET1", list_ids=[9990])
    bulk.monsects.clear()
    bulk.monsects["SECALL"] = Monsect(
        name="SECALL", label="WHOLE MODEL", comp="EVERYGRID", cid=901,
        axis=2, side="POS", stations=[0.0],
    )


def _whole_model_run(collection_all=True, tend=0.3):
    bulk, gi, aero = _deck()
    _whole_model_cut_deck(bulk)
    if not collection_all:
        # The deck's own AECOMP, which omits the SUPORT grid.
        bulk.monsects["SECALL"].comp = "ALLGRID"
    labels = sorted([a.label for a in bulk.aestats.values()]
                    + [s.label for s in bulk.aesurfs.values()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        commands = _elevator_step()(bulk, labels, ic.trim_vars)
        bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
        bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=tend, dt=0.005, tout=0.02)
        bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
        bulk.mloads[1] = Mloads(sid=1, mldtrim=1, mldtime=1, mldcomd=1)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        res = run_maneuver_qs(bulk, sc, aero)
    return res, bulk


def test_vtsec5_whole_model_cut_balances_at_every_sample():
    """V-TSEC5 — a cut containing the entire model is a closed free body: ≈ 0.

    ``aero + rigid inertia + elastic inertia + damping + reaction ≡ 0`` at every
    instant, because summing all rows of ``K·u = f`` gives zero.  This pins the
    **signs** of the two new columns and the reaction against a route that never
    touches the section-cut code — and it is the gate that catches recovering
    the reaction against ``net_loads`` instead of the full applied load, since
    the omitted term reappears here as an unbalanced residual.

    Note this is NOT ``step.closure ≈ 0``.  Under the direct (prescribed-rigid)
    solver the closure is genuinely non-zero during a maneuver: the rigid state
    is held at the trim URDD while the elevator adds lift, and the imbalance is
    reacted at the SUPORT.  The free body closes only once that reaction is
    counted.
    """
    res, _bulk = _whole_model_run()
    lift = max(abs(s.Fz_aero) for s in res.steps)
    assert lift > 1e3, "the trim is not carrying load; the gate would be vacuous"
    for step in res.steps:
        st = step.section_loads["SECALL"].stations[0]
        assert np.linalg.norm(st.totals[:3]) < 1e-8 * lift, (
            f"t={step.t}: whole-model free body does not close "
            f"(F={st.totals[:3]}, reaction={st.reaction[:3]})")
        assert np.linalg.norm(st.totals[3:]) < 1e-6 * lift


def test_prescribed_rigid_closure_is_carried_by_the_reaction():
    """The direct solver's non-zero closure IS the SUPORT reaction.

    Documents the distinction the gate above rests on, so a future reader does
    not "fix" a closure that is supposed to be non-zero.
    """
    res, _bulk = _whole_model_run()
    dynamic = [s for s in res.steps if abs(s.closure[2]) > 1.0]
    assert dynamic, "no sample is out of rigid balance; pick a stronger command"
    for step in dynamic:
        st = step.section_loads["SECALL"].stations[0]
        # closure = aero + rigid inertia only; the free body adds elastic +
        # damping + reaction and lands on zero.  Forces only: the cut takes
        # moments about its own plane/reference-line intercept while the closure
        # takes them about the SUPORT point, so the two moment sets differ by a
        # transfer term and are not comparable term-by-term.
        assert np.allclose(st.aero[:3] + st.inertia[:3], step.closure[:3],
                           rtol=1e-8, atol=1e-6 * abs(step.closure[2]))
        assert abs(st.reaction[2]) > 0.0


def test_partial_collection_does_not_close():
    """A collection missing the reaction grid cannot balance — and should not.

    Guards the gate above against being satisfied by a cut that simply reports
    zeros: with GRID 90 omitted the same run leaves a visible residual.
    """
    res, bulk = _whole_model_run(collection_all=False)
    lift = max(abs(s.Fz_aero) for s in res.steps)
    worst = max(abs(s.section_loads["SECALL"].stations[0].totals[2])
                for s in res.steps)
    assert worst > 1e-4 * lift


def test_undamped_run_reports_no_damping_column():
    """ζ = α = 0 ⇒ the damping load is absent, and the cut column is exactly 0."""
    res, _ic, _b, _gi = _maneuver()
    assert res.steps[0].damping_loads is None
    for st in res.steps[0].section_loads[CUT].stations:
        assert np.array_equal(st.damping, np.zeros(6))


def test_mass_proportional_damping_populates_the_column():
    """With α ≠ 0 the damping force is recovered and enters the cut."""
    res, _ic, _b, _gi = _maneuver(commands_builder=_elevator_step(),
                                  damping_alpha=2.0)
    assert res.steps[-1].damping_loads is not None
    moved = any(np.max(np.abs(st.damping)) > 0.0
                for s in res.steps for st in s.section_loads[CUT].stations)
    assert moved, "alpha damping produced no damping load anywhere in the run"


# --------------------------------------------------------------------------- #
# Cost / hygiene
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# V-TSEC11 — the modal free-flight solver (Step 63) takes cuts too
# --------------------------------------------------------------------------- #

def _modal_run(commanded=True, tend=0.3, dt=0.01, tout=0.05, zeta=0.0):
    """Free-flight modal transient on the same deck (Step 62/63 solver)."""
    from tests.solver.test_maneuver_modal import (
        RHO, _aero_and_trim_elev, _build, _command_elev)
    from sbeam.solver.maneuver_modal import run_maneuver_modal

    bulk, gi = _build(rho=RHO, tend=tend, dt=dt, tout=tout, zeta=zeta)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        if commanded:
            _command_elev(bulk, elev0, [0.0, 0.05, 60.0], [0.0, 0.05, 0.05])
        res = run_maneuver_modal(bulk, sc, aero)
    return res, ic, bulk, gi


def test_vtsec11_modal_solver_produces_section_cuts():
    """The feature must not land on the direct solver only.

    The free-flight modal solver is the one a production maneuver deck actually
    runs (METHOD = −1); a cut capability present on the legacy direct solver
    alone would be invisible in practice.
    """
    res, _ic, _b, _gi = _modal_run()
    assert all(s.section_loads for s in res.steps)
    assert CUT in res.steps[0].section_loads


def test_vtsec11_modal_zero_command_reproduces_the_static_table():
    """V-TSEC1 on the modal path: no command ⇒ the cut is the static trim cut."""
    res, ic, _b, _gi = _modal_run(commanded=False)
    static = ic.section_loads[CUT]
    scale = max(np.max(np.abs(st.totals)) for st in static.stations)
    for step in res.steps:
        for a, b in zip(step.section_loads[CUT].stations, static.stations):
            assert np.max(np.abs(a.totals - b.totals)) < 1e-6 * scale


def test_vtsec11_modal_columns_sum_to_the_totals():
    res, _ic, _b, _gi = _modal_run()
    for step in res.steps:
        for st in step.section_loads[CUT].stations:
            parts = (st.aero + st.inertia + st.reaction
                     + st.elastic_inertia + st.damping)
            assert np.allclose(st.totals, parts, rtol=1e-12, atol=1e-12)


def test_vtsec11_modal_recovery_modes_agree_on_the_elastic_column():
    """Both recovery modes must build the elastic inertia — it is not a
    property of the mode-acceleration branch.

    The term used to be formed only where the mode-acceleration recovery needed
    it; leaving it there would make the same physical sample report different
    section cuts depending on a recovery switch.
    """
    from tests.solver.test_maneuver_modal import (
        RHO, _aero_and_trim_elev, _build, _command_elev)
    from sbeam.solver.maneuver_modal import run_maneuver_modal

    out = {}
    for mode in ("acceleration", "displacement"):
        bulk, gi = _build(rho=RHO, tend=0.2, dt=0.01, tout=0.05)
        sc = SubcaseControl(subcase_id=1, spc_sid=1)
        sc.mloads_sid = 1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero, elev0 = _aero_and_trim_elev(bulk, gi)
            _command_elev(bulk, elev0, [0.0, 0.05, 60.0], [0.0, 0.05, 0.05])
            out[mode] = run_maneuver_modal(bulk, sc, aero, recovery=mode)

    for sa, sd in zip(out["acceleration"].steps, out["displacement"].steps):
        ea = np.array([st.elastic_inertia
                       for st in sa.section_loads[CUT].stations])
        ed = np.array([st.elastic_inertia
                       for st in sd.section_loads[CUT].stations])
        # Same ξ̈_e drives both — the recovery mode changes u_l, not the
        # elastic acceleration field, so this column must be identical.
        assert np.allclose(ea, ed, rtol=1e-12, atol=1e-12)


# --------------------------------------------------------------------------- #
# Cost / hygiene
# --------------------------------------------------------------------------- #

def test_vtsec6_envelope_is_produced_and_bounds_every_sample():
    """The run's envelope must actually bound the per-sample tables it came from.

    The unit reduction is gated in ``tests/results/test_section_envelope.py``;
    this is the end-to-end version — that the solver attaches an envelope and
    that no sample escapes it.
    """
    res, _ic, _b, _gi = _maneuver(commands_builder=_elevator_step())
    assert res.section_envelope is not None
    env = res.section_envelope[CUT]
    assert env.n_samples == len(res.steps)

    for step in res.steps:
        sc = step.section_loads[CUT]
        for j, stn in enumerate(sc.stations):
            lab = labelled(stn.totals, sc.comp_map)
            for c in range(6):
                e = next(x for x in env.entries
                         if x.station == stn.station and x.comp == c)
                assert e.min_value - 1e-9 <= lab[c] <= e.max_value + 1e-9


def test_vtsec6_modal_run_also_gets_an_envelope():
    res, _ic, _b, _gi = _modal_run()
    assert res.section_envelope is not None
    assert CUT in res.section_envelope


def test_vtsec10_section_cuts_do_not_dominate_the_runtime():
    """V-TSEC10 — the per-sample cost must stay proportional to stations.

    A geometry rebuild inside the time loop would not fail any correctness gate;
    it would only make long runs slow.  Compared against the same run with the
    MONSECT cards removed.
    """
    import time

    def _timed(with_cuts):
        bulk, gi, aero = _deck()
        if not with_cuts:
            bulk.monsects.clear()
        labels = sorted([a.label for a in bulk.aestats.values()]
                        + [s.label for s in bulk.aesurfs.values()])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic = run_sol144_trim(
                bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
            commands = _elevator_step()(bulk, labels, ic.trim_vars)
            bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
            bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=0.5, dt=0.002,
                                       tout=0.002)
            bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
            bulk.mloads[1] = Mloads(sid=1, mldtrim=1, mldtime=1, mldcomd=1)
            sc = SubcaseControl(subcase_id=1, spc_sid=1)
            sc.mloads_sid = 1
            t0 = time.perf_counter()
            res = run_maneuver_qs(bulk, sc, aero)
            return time.perf_counter() - t0, len(res.steps)

    with_cuts, n = _timed(True)
    without, _ = _timed(False)
    assert n >= 100, "not enough samples for the timing to mean anything"
    # Generous bound: this catches an O(model) rebuild per sample, not a few
    # percent of noise on a shared CI box.
    assert with_cuts < 2.0 * without + 0.5, (
        f"{n} samples: {with_cuts:.3f}s with cuts vs {without:.3f}s without — "
        "the per-sample cut cost looks like a geometry rebuild")


def test_on_plane_warning_is_not_emitted_once_per_sample():
    """The geometry (and its warnings) is resolved once per run, not per sample."""
    with warnings.catch_warnings(record=True) as rec:
        warnings.simplefilter("always")
        res, _ic, _b, _gi = _maneuver(tend=0.2)
    on_plane = [w for w in rec if "INBOARD side" in str(w.message)]
    assert len(on_plane) <= len(res.steps) // 4 + 1, (
        f"{len(on_plane)} on-plane warnings for {len(res.steps)} samples — the "
        "cut geometry is being rebuilt inside the time loop")
