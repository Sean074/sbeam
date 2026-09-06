"""V-TMON — MONPNT1/MONPNT3 on transient (MLOADS) maneuvers (#2).

The per-sample monitor integrand (box forces, splined aero, rigid inertia,
elastic d'Alembert load, damping, reactions) existed since Step 68; this is
the output surface on top of it.  The gates tie it to things computed by other
routes:

  * V-TMON1 — commands held at trim ⇒ every sample's monitor equals the static
    trim monitor (the issue's stated acceptance), on both solvers.
  * V-TMON2 — on a DYNAMIC sample a whole-model MONPNT3 is a closed free body:
    aero + rigid inertia + elastic inertia + damping equals the sample's
    closure (same reference point, all six components), and adding the
    reaction lands on zero.
  * V-TMON3 — a MONPNT3 over exactly the members outboard of a MONSECT
    station, referenced at that station, equals the section-cut table there,
    column by column.  The cut is itself tied to the beam internal force by
    V-TSEC3, so the monitor inherits that gate transitively.
  * The companion to V-TMON3 shows the elastic column is load-bearing.
  * The DEF-M10 mass-coverage warning fires once per run, not once per sample.
  * The envelope bounds every sample and names the sample that drove it.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.model.aero import Aecomp, Monpnt3, Set1
from sbeam.model.maneuver import Mldcomd, Mldtime, Mldtrim, Mloads
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.results.section_cuts import prepare_section_cut
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol144 import run_sol144_trim
from tests.aero.test_section_cuts_transient import (
    CUT, _deck, _dynamic_sample, _elevator_step, _maneuver, _modal_run,
)

MONITORS = {"MWINGRT", "MWINGEA", "MALLEA", "MALLAR"}
SUPORT_POS = np.array([15.0, 0.0, 0.0])     # GRID 90 — also every monitor's ref


def _transient_terms(ml):
    el = ml.elastic_inertia if ml.elastic_inertia is not None else np.zeros(6)
    da = ml.damping if ml.damping is not None else np.zeros(6)
    return el, da


# --------------------------------------------------------------------------- #
# Presence
# --------------------------------------------------------------------------- #

def test_monitors_present_at_every_sample_direct():
    res, ic, _b, _gi = _maneuver(commands_builder=_elevator_step())
    assert set(ic.monitor_loads) == MONITORS
    for step in res.steps:
        assert set(step.monitor_loads) == MONITORS
        for ml in step.monitor_loads.values():
            assert ml.totals.shape == (6,)
            assert np.all(np.isfinite(ml.totals))


def test_monitors_present_at_every_sample_modal():
    """The feature must not land on the direct solver only (cf. V-TSEC11)."""
    res, _ic, _b, _gi = _modal_run()
    for step in res.steps:
        assert set(step.monitor_loads) == MONITORS


def test_monpnt1_is_aero_only_and_has_no_transient_columns():
    res, _ic, _b, _gi = _maneuver(commands_builder=_elevator_step())
    for step in res.steps:
        ml = step.monitor_loads["MALLAR"]
        assert ml.mtype == "MONPNT1"
        assert ml.elastic_inertia is None and ml.damping is None
        assert np.array_equal(ml.totals, ml.aero)


# --------------------------------------------------------------------------- #
# V-TMON1 — quasi-static identity (the issue's acceptance)
# --------------------------------------------------------------------------- #

def _assert_matches_static(res, ic):
    for name in MONITORS:
        static = ic.monitor_loads[name]
        scale = max(np.max(np.abs(static.totals)), 1.0)
        for step in res.steps:
            ml = step.monitor_loads[name]
            assert np.max(np.abs(ml.totals - static.totals)) < 1e-6 * scale, (
                f"t={step.t} {name}: transient monitor drifted from static")
            assert np.allclose(ml.aero, static.aero, atol=1e-6 * scale)
            assert np.allclose(ml.inertia, static.inertia, atol=1e-6 * scale)
            assert ml.cid == static.cid and ml.axes == static.axes
            assert np.array_equal(ml.ref, static.ref)
            if ml.mtype == "MONPNT3":
                # Held at trim: the transient columns are computed-and-zero,
                # as opposed to absent on the static monitor.
                assert static.elastic_inertia is None
                assert ml.elastic_inertia is not None
                assert np.max(np.abs(ml.elastic_inertia)) < 1e-6 * scale


def test_vtmon1_held_at_trim_reproduces_the_static_monitor_direct():
    res, ic, _b, _gi = _maneuver()
    _assert_matches_static(res, ic)


def test_vtmon1_held_at_trim_reproduces_the_static_monitor_modal():
    res, ic, _b, _gi = _modal_run(commanded=False)
    _assert_matches_static(res, ic)


# --------------------------------------------------------------------------- #
# V-TMON2 — whole-model free body on a DYNAMIC sample
# --------------------------------------------------------------------------- #

def _everygrid_monitor(bulk):
    """A MONPNT3 over EVERY grid, including the SUPORT grid 90 the deck's own
    ALLGRID omits (the V-TSEC5 lesson), referenced at the SUPORT point so its
    moments and the closure's are about the same point."""
    bulk.set1s[9991] = Set1(sid=9991, grids=sorted(bulk.grids))
    bulk.aecomps["EVERYGRD"] = Aecomp(
        name="EVERYGRD", listtype="SET1", list_ids=[9991])
    bulk.monpnt3s["MEVERY"] = Monpnt3(
        name="MEVERY", label="EVERY GRID", axes=123456, comp="EVERYGRD",
        cp=0, x=SUPORT_POS[0], y=SUPORT_POS[1], z=SUPORT_POS[2])


def _direct_run_with(bulk_mod, damping_alpha=0.0, tend=0.3):
    bulk, gi, aero = _deck()
    bulk_mod(bulk, gi, aero)
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
        res = run_maneuver_qs(bulk, sc, aero, damping_alpha=damping_alpha)
    return res, ic, bulk, gi


@pytest.mark.parametrize("damping_alpha", [0.0, 2.0])
def test_vtmon2_whole_model_monitor_equals_the_closure_and_closes(damping_alpha):
    """aero + rigid inertia + elastic inertia + damping == closure (6 comps);
    + reaction == 0.  Under the direct solver the closure is genuinely non-zero
    on a dynamic sample and is reacted at GRID 90 — a monitor that omits the
    grid, or the elastic column, cannot close."""
    res, _ic, _b, _gi = _direct_run_with(lambda b, gi, a: _everygrid_monitor(b),
                                         damping_alpha=damping_alpha)
    lift = max(abs(s.Fz_aero) for s in res.steps)
    dynamic = [s for s in res.steps if abs(s.closure[2]) > 1.0]
    assert dynamic, "no sample is out of rigid balance; pick a stronger command"
    for step in dynamic:
        ml = step.monitor_loads["MEVERY"]
        assert np.array_equal(ml.ref, SUPORT_POS)
        el, da = _transient_terms(ml)
        applied = ml.aero + ml.inertia + el + da
        assert np.allclose(applied, step.closure, rtol=1e-8, atol=1e-8 * lift), (
            f"t={step.t}: monitor applied load {applied} != closure {step.closure}")
        assert np.linalg.norm(ml.totals[:3]) < 1e-8 * lift
        assert np.linalg.norm(ml.totals[3:]) < 1e-6 * lift
        assert abs(ml.reaction[2]) > 0.0
        if damping_alpha:
            assert np.max(np.abs(da)) > 0.0


def _modal_run_with(bulk_mod, zeta=0.0, tend=0.3, dt=0.01, tout=0.05):
    """``_modal_run`` with a hook to add cards before the IC trim."""
    from tests.solver.test_maneuver_modal import (
        RHO, _aero_and_trim_elev, _build, _command_elev)
    from sbeam.solver.maneuver_modal import run_maneuver_modal

    bulk, gi = _build(rho=RHO, tend=tend, dt=dt, tout=tout, zeta=zeta)
    bulk_mod(bulk)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        _command_elev(bulk, elev0, [0.0, 0.05, 60.0], [0.0, 0.05, 0.05])
        res = run_maneuver_modal(bulk, sc, aero)
    return res, ic, bulk, gi


def test_vtmon2_modal_free_flight_every_grid_monitor_closes():
    """Free flight: the integrator satisfies the rigid equations at every
    step, so a MONPNT3 over every grid (aero + rigid inertia + elastic inertia
    + damping, nothing reacted) is ≈ 0 at every sample and equals the closure
    about the same point — while its aero column swings with the command."""
    res, _ic, _b, _gi = _modal_run_with(_everygrid_monitor, zeta=0.02)
    lift = max(abs(s.Fz_aero) for s in res.steps)
    swing = 0.0
    for step in res.steps:
        ml = step.monitor_loads["MEVERY"]
        el, da = _transient_terms(ml)
        applied = ml.aero + ml.inertia + el + da
        assert np.allclose(applied, step.closure, rtol=1e-8, atol=1e-8 * lift)
        assert np.linalg.norm(ml.totals[:3]) < 1e-6 * lift, f"t={step.t}: {ml.totals}"
        assert np.linalg.norm(ml.totals[3:]) < 1e-6 * lift
        swing = max(swing, abs(ml.aero[2] - res.steps[0].monitor_loads["MEVERY"].aero[2]))
    assert swing > 1e-3 * lift, "the command did not move the aero; vacuous"
    assert any(np.max(np.abs(_transient_terms(s.monitor_loads["MEVERY"])[1])) > 0
               for s in res.steps), "zeta produced no damping column"


# --------------------------------------------------------------------------- #
# V-TMON3 — monitor == section-cut station on a DYNAMIC sample
# --------------------------------------------------------------------------- #

STATION = 8.0


def _station_monitor(bulk, gi, aero):
    """A MONPNT3 over exactly the members outboard of SECRW station 8.0,
    referenced at that station's cut-plane/EA intercept, reported in the cut
    CID — so its six components are the section-cut row itself."""
    plan = prepare_section_cut(bulk.monsects[CUT], bulk, aero, gi)
    i = list(bulk.monsects[CUT].stations).index(STATION)
    outboard = [g for g, on in zip(plan.member_ids, plan.masks[i]) if on]
    assert outboard, "no member outboard of the station"
    origin, R = get_transform(bulk.monsects[CUT].cid, bulk.cord2rs)
    xyz = R.T @ (plan.refs[i] - origin)
    bulk.set1s[9992] = Set1(sid=9992, grids=outboard)
    bulk.aecomps["OUTBD8"] = Aecomp(name="OUTBD8", listtype="SET1", list_ids=[9992])
    bulk.monpnt3s["MOUTBD8"] = Monpnt3(
        name="MOUTBD8", label="OUTBOARD OF S=8", axes=123456, comp="OUTBD8",
        cp=bulk.monsects[CUT].cid, x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]))


def test_vtmon3_monitor_equals_the_section_cut_station_column_by_column():
    res, _ic, _b, _gi = _direct_run_with(_station_monitor, damping_alpha=2.0)
    _k, step = _dynamic_sample(res)
    assert np.max(np.abs(step.elastic_inertial_loads)) > 0.0
    ml = step.monitor_loads["MOUTBD8"]
    st = next(s for s in step.section_loads[CUT].stations if s.station == STATION)
    assert np.allclose(ml.ref, st.ref, atol=1e-12)
    scale = max(np.max(np.abs(st.totals)), 1.0)
    for a, b, what in ((ml.aero, st.aero, "aero"),
                       (ml.inertia, st.inertia, "inertia"),
                       (ml.reaction, st.reaction, "reaction"),
                       (ml.elastic_inertia, st.elastic_inertia, "elastic"),
                       (ml.damping, st.damping, "damping"),
                       (ml.totals, st.totals, "totals")):
        assert np.allclose(a, b, rtol=1e-10, atol=1e-10 * scale), what
    assert np.max(np.abs(ml.elastic_inertia)) > 1e-3 * scale, (
        "elastic column negligible on this sample — V-TMON3 would not test it")
    assert np.max(np.abs(ml.damping)) > 0.0


def test_vtmon3_companion_fails_without_the_elastic_column():
    """Re-summed without the elastic column the monitor misses the cut by far
    more than the gate tolerance — the gate is load-bearing, not vacuous."""
    res, _ic, _b, _gi = _direct_run_with(_station_monitor)
    _k, step = _dynamic_sample(res)
    ml = step.monitor_loads["MOUTBD8"]
    st = next(s for s in step.section_loads[CUT].stations if s.station == STATION)
    without = ml.aero + ml.inertia + ml.reaction
    scale = max(np.max(np.abs(st.totals)), 1.0)
    assert np.max(np.abs(without - st.totals)) > 1e-4 * scale


# --------------------------------------------------------------------------- #
# Hygiene: DEF-M10 warning once per run; envelope
# --------------------------------------------------------------------------- #

def test_mass_coverage_warning_fires_once_per_run_not_per_sample():
    """A whole-aircraft MONPNT3 missing a CONM2 grid warns on the IC trim
    (DEF-M10) and is NOT re-warned at every output sample."""
    def add_incomplete(bulk, gi, aero):
        # Drop GRID 97: it carries a CONM2 but no splined aero, so the monitor
        # still integrates all of the aero and DEF-M10 qualifies it.
        grids = [g for g in bulk.set1s[1310].grids if g != 97]
        bulk.set1s[9993] = Set1(sid=9993, grids=grids)
        bulk.aecomps["MOSTGRID"] = Aecomp(
            name="MOSTGRID", listtype="SET1", list_ids=[9993])
        bulk.monpnt3s["MMOST"] = Monpnt3(
            name="MMOST", label="MISSING A MASS", axes=123456, comp="MOSTGRID",
            cp=0, x=15.0, y=0.0, z=0.0)

    bulk, gi, aero = _deck()
    add_incomplete(bulk, gi, aero)
    labels = sorted([a.label for a in bulk.aestats.values()]
                    + [s.label for s in bulk.aesurfs.values()])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ic = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
        n_static = sum("MONPNT3 MMOST" in str(w.message) for w in caught)
    assert n_static == 1
    assert "MMOST" in ic.monitor_loads

    commands = _elevator_step()(bulk, labels, ic.trim_vars)
    bulk.mldtrims[1] = Mldtrim(sid=1, trim_sid=1)
    bulk.mldtimes[1] = Mldtime(sid=1, t0=0.0, tend=0.3, dt=0.005, tout=0.02)
    bulk.mldcomds[1] = Mldcomd(sid=1, commands=commands)
    bulk.mloads[1] = Mloads(sid=1, mldtrim=1, mldtime=1, mldcomd=1)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = run_maneuver_qs(bulk, sc, aero)
    n_transient = sum("MONPNT3 MMOST" in str(w.message) for w in caught)
    assert len(res.steps) > 5
    assert n_transient == 1, (
        f"DEF-M10 warning issued {n_transient} times over {len(res.steps)} samples")


@pytest.mark.parametrize("runner", ["direct", "modal"])
def test_envelope_is_produced_and_bounds_every_sample(runner):
    res = (_maneuver(commands_builder=_elevator_step())[0] if runner == "direct"
           else _modal_run()[0])
    env = res.monitor_envelope
    assert env is not None and set(env) == MONITORS
    for name, e in env.items():
        assert e.n_samples == len(res.steps)
        assert len(e.entries) == 6
        for entry in e.entries:
            vals = [s.monitor_loads[name].totals[entry.comp] for s in res.steps]
            assert entry.max_value == pytest.approx(max(vals))
            assert entry.min_value == pytest.approx(min(vals))
            assert vals[entry.max_sample - 1] == entry.max_value
            assert vals[entry.min_sample - 1] == entry.min_value
            assert entry.max_time == pytest.approx(res.steps[entry.max_sample - 1].t)


# --------------------------------------------------------------------------- #
# Shipped flagship deck — the whole-aircraft monitor closes on every sample
# --------------------------------------------------------------------------- #

FLAGSHIP = Path(__file__).parent.parent.parent / "sample" / "cessna210_flagship_mloads.bdf"


def test_flagship_whole_aircraft_monitor_closes_at_every_sample():
    """On the shipped C210 MLOADS deck the whole-aircraft MONPNT3 (whose SET1
    includes the SUPORT grid) is a closed free body at every sample: the f06
    TOTAL row of MALLEA is ~1e-10 against a 1e4 lift."""
    cc, bulk = parse_bdf(str(FLAGSHIP))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        sc = next(s for s in cc.subcases if s.mloads_sid is not None)
        res = run_maneuver_qs(bulk, sc, aero)
    lift = max(abs(s.Fz_aero) for s in res.steps)
    assert set(res.steps[0].monitor_loads) == {"MWROOT", "MALLEA", "MALLAR", "MRWAER"}
    for step in res.steps:
        ml = step.monitor_loads["MALLEA"]
        assert np.linalg.norm(ml.totals[:3]) < 1e-9 * lift
        assert np.linalg.norm(ml.totals[3:]) < 1e-9 * lift
    # The envelope of a closed free body is ~0 everywhere — and the wing-root
    # monitor's driving sample is reported per component.
    assert res.monitor_envelope["MALLEA"].entries[2].absmax < 1e-9 * lift
    assert res.monitor_envelope["MWROOT"].entries[2].absmax > 1e3
