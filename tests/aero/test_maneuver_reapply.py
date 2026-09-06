"""G1 — the transient net load re-applied statically reproduces the sample (#3).

``ManeuverStep.net_loads`` is the FULL applied load at a transient sample:
``F_aero − M·ü_rigid − M·ü_elastic − C·u̇``.  Its one contract is that a stress
model applying it statically to the same structure recovers the same internal
loads the transient run reported.  That is what every gate here checks: take a
sample, apply its net load as a SOL 101 case with the SPC plus the SUPORT DOFs
fixed (the same system the transient solvers integrate on), and compare the
recovered CBAR forces against ``step.bar_forces``.

* **G1a** — the g-set vector applied directly: 1e-8 on the direct solver and on
  the modal solver under mode-acceleration recovery (whose displacement IS the
  static l-set solve of the full load, so truncation does not enter).
* **G1a companion** — the same check FAILS with the elastic-inertia and damping
  terms removed, so the gate is demonstrably load-bearing (V-TSEC3 pattern).
* **G1b** — the same through the exported ``FORCE``/``MOMENT`` cards: 1e-5, the
  NASTRAN 8-character field floor (DEF-M6).  Also run on the Cessna 210 flagship
  MLOADS sample deck, which is the file a stress office actually receives.
* **G1c** — the modal solver under ``displacement`` recovery: exact with every
  elastic mode retained, and a MEASURED truncation error otherwise (the
  residual ``F − Mü − Cu̇ − Ku`` is orthogonal to the retained modes, not zero).
* **G2** — the closure: under free flight the elastic + damping resultant is
  zero by mean-axis orthogonality, so folding it in changes nothing; under the
  direct solver the closure shifts by exactly that resultant.
* **G3** — commands held at trim: every sample's ``net_loads`` equals the static
  Step 53 ``net_loads`` (the transient terms are zero).

Design note: ``docs/30_future/designs/transient_net_loads_elastic_inertia.md``.
"""

import copy
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.constraint import Spc1
from sbeam.model.load import Force, Moment
from sbeam.results.maneuver_output import build_maneuver_critical_load_cards_text
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol101 import run_sol101
from sbeam.solver.sol144_util import load_resultant

from tests.aero.test_section_cuts_transient import (
    _elevator_step, _maneuver, _modal_run)

_SAMPLE = Path(__file__).parent.parent.parent / "sample"
FLAGSHIP_MLOADS = _SAMPLE / "cessna210_flagship_mloads.bdf"

LOAD_SID = 9301          # any sid the sample decks do not use
_BAR_FIELDS = ("axial", "shear1", "shear2", "torque",
               "bm1_a", "bm2_a", "bm1_b", "bm2_b")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _static_model(bulk, spc_sid):
    """A copy of the deck with the SUPORT DOFs added to SPC set ``spc_sid``.

    The transient solvers hold the r-set at zero (mean axis); the equivalent
    static system is the same SPC set plus the SUPORT DOFs fixed.
    """
    b = copy.deepcopy(bulk)
    for sup in b.supports:
        b.spc1s.setdefault(spc_sid, []).append(
            Spc1(sid=spc_sid, c=sup.dofs, grids=[sup.gid]))
    return b


def _apply_vector(bulk, gi, load_g, spc_sid=1):
    """SOL 101 on the deck with the g-set vector applied at full precision."""
    b = _static_model(bulk, spc_sid)
    b.forces[LOAD_SID] = []
    b.moments[LOAD_SID] = []
    for gid, row in gi.items():
        f = load_g[6 * row: 6 * row + 3]
        m = load_g[6 * row + 3: 6 * row + 6]
        b.forces[LOAD_SID].append(Force(LOAD_SID, gid, 0, 1.0, *map(float, f)))
        b.moments[LOAD_SID].append(Moment(LOAD_SID, gid, 0, 1.0, *map(float, m)))
    return run_sol101(b, SubcaseControl(subcase_id=1, load_sid=LOAD_SID, spc_sid=spc_sid))


def _apply_cards(bulk, cards_text, sid, spc_sid=1):
    """SOL 101 on the deck with the exported cards parsed back in."""
    b = _static_model(bulk, spc_sid)
    parsed = parse_bulk_data(cards_text.splitlines())
    b.forces[sid] = parsed.forces.get(sid, [])
    b.moments[sid] = parsed.moments.get(sid, [])
    return run_sol101(b, SubcaseControl(subcase_id=1, load_sid=sid, spc_sid=spc_sid))


def _bar_mismatch(ref, got):
    """max |got − ref| / max |ref| over every CBAR end-force component."""
    eids = sorted(ref)
    a = np.array([[getattr(ref[e], f) for f in _BAR_FIELDS] for e in eids])
    b = np.array([[getattr(got[e], f) for f in _BAR_FIELDS] for e in eids])
    return float(np.max(np.abs(b - a)) / np.max(np.abs(a)))


def _transient_terms(step):
    """elastic inertia + damping (the damping term is None on an undamped run)."""
    extra = step.elastic_inertial_loads
    return extra if step.damping_loads is None else extra + step.damping_loads


def _dynamic_sample(res):
    """The sample with the largest elastic d'Alembert load — where G1 bites."""
    return int(np.argmax([np.max(np.abs(s.elastic_inertial_loads))
                          for s in res.steps]))


@pytest.fixture(scope="module")
def direct_run():
    """HA144A, abrupt elevator step on the direct solver, with damping so the
    damping term is exercised too."""
    return _maneuver(commands_builder=_elevator_step(), damping_alpha=0.5)


@pytest.fixture(scope="module")
def modal_run():
    return _modal_run(commanded=True, zeta=0.02)


@pytest.fixture(scope="module")
def flagship_run():
    """The shipped Cessna 210 MLOADS deck, exactly as the CLI runs it."""
    cc, bulk = parse_bdf(str(FLAGSHIP_MLOADS))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        sc = [s for s in cc.subcases if s.mloads_sid is not None][0]
        res = run_maneuver_qs(bulk, sc, aero)
    return res, bulk, gi, sc.spc_sid


# --------------------------------------------------------------------------- #
# G1a — the vector, exact
# --------------------------------------------------------------------------- #

def test_g1a_direct_solver_reapply_is_exact(direct_run):
    res, _ic, bulk, gi = direct_run
    step = res.steps[_dynamic_sample(res)]
    assert np.max(np.abs(step.elastic_inertial_loads)) > 0.0
    static = _apply_vector(bulk, gi, step.net_loads)
    assert _bar_mismatch(step.bar_forces, static.bar_forces) < 1e-8


def test_g1a_critical_sample_reapply_is_exact(direct_run):
    """The exported sample specifically — the one the stress office gets."""
    res, _ic, bulk, gi = direct_run
    step = res.steps[res.crit_index]
    static = _apply_vector(bulk, gi, step.net_loads)
    assert _bar_mismatch(step.bar_forces, static.bar_forces) < 1e-8


def test_g1a_companion_fails_without_the_transient_terms(direct_run):
    """Aero + rigid inertia alone — the pre-#3 export — does NOT reproduce the
    sample.  Without this the gate could pass vacuously."""
    res, _ic, bulk, gi = direct_run
    step = res.steps[_dynamic_sample(res)]
    partial = step.net_loads - _transient_terms(step)
    static = _apply_vector(bulk, gi, partial)
    assert _bar_mismatch(step.bar_forces, static.bar_forces) > 1e-3


def test_g1a_modal_solver_reapply_is_exact(modal_run):
    """Mode-acceleration recovery: the displacement is the static l-set solve
    of the full load, so the re-apply is exact regardless of NMODES."""
    res, _ic, bulk, gi = modal_run
    for k in (_dynamic_sample(res), res.crit_index):
        step = res.steps[k]
        static = _apply_vector(bulk, gi, step.net_loads)
        assert _bar_mismatch(step.bar_forces, static.bar_forces) < 1e-8


# --------------------------------------------------------------------------- #
# G1b — through the exported cards (DEF-M6 field floor)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("which", ["direct", "modal"])
def test_g1b_exported_cards_reapply_to_field_precision(which, direct_run, modal_run):
    res, _ic, bulk, gi = direct_run if which == "direct" else modal_run
    text = build_maneuver_critical_load_cards_text(bulk, res, sid=LOAD_SID)
    step = res.steps[res.crit_index]
    static = _apply_cards(bulk, text, LOAD_SID)
    assert _bar_mismatch(step.bar_forces, static.bar_forces) < 1e-5


def test_g1b_flagship_sample_deck(flagship_run):
    """The shipped deck: the file written by the CLI applies back to 1e-5."""
    res, bulk, _gi, spc_sid = flagship_run
    text = build_maneuver_critical_load_cards_text(bulk, res, sid=LOAD_SID)
    step = res.steps[res.crit_index]
    static = _apply_cards(bulk, text, LOAD_SID, spc_sid=spc_sid)
    assert _bar_mismatch(step.bar_forces, static.bar_forces) < 1e-5


# --------------------------------------------------------------------------- #
# G1c — modal displacement recovery: exact at all modes, measured when truncated
# --------------------------------------------------------------------------- #

def _modal_displacement_run(nmodes):
    from tests.solver.test_maneuver_modal import (
        RHO, _aero_and_trim_elev, _build, _command_elev)
    from sbeam.solver.maneuver_modal import run_maneuver_modal
    bulk, gi = _build(rho=RHO, tend=0.3, dt=0.01, tout=0.05, nmodes=nmodes)
    sc = SubcaseControl(subcase_id=1, spc_sid=1)
    sc.mloads_sid = 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero, elev0 = _aero_and_trim_elev(bulk, gi)
        _command_elev(bulk, elev0, [0.0, 0.05, 60.0], [0.0, 0.05, 0.05])
        res = run_maneuver_modal(bulk, sc, aero, recovery="displacement")
    return res, bulk, gi


def _g1c_error(nmodes):
    res, bulk, gi = _modal_displacement_run(nmodes)
    step = res.steps[_dynamic_sample(res)]
    static = _apply_vector(bulk, gi, step.net_loads)
    return _bar_mismatch(step.bar_forces, static.bar_forces)


def test_g1c_displacement_recovery_exact_with_all_modes():
    assert _g1c_error(0) < 1e-8


def test_g1c_truncation_error_is_measured_and_shrinks():
    """NMODES = 2 vs all: the truncated figure is the modal-truncation error of
    the shipped recovery mode, recorded in the #3 history entry.  It must be a
    real number (the gate sees it) and must vanish as modes are added."""
    e_trunc, e_all = _g1c_error(2), _g1c_error(0)
    assert e_trunc > 1e-6
    assert e_trunc < 0.05
    assert e_all < 1e-8


# --------------------------------------------------------------------------- #
# G2 — closure
# --------------------------------------------------------------------------- #

def test_g2_free_flight_closure_unchanged_by_the_transient_terms(modal_run):
    res, _ic, bulk, gi = modal_run
    ref = np.array([bulk.grids[bulk.supports[0].gid].x, bulk.grids[bulk.supports[0].gid].y, bulk.grids[bulk.supports[0].gid].z])
    lift = max(abs(s.Fz_aero) for s in res.steps)
    for s in res.steps:
        r = load_resultant(_transient_terms(s), bulk, gi, ref)
        assert np.linalg.norm(r[:3]) < 1e-12 * lift
        partial = load_resultant(s.grid_loads + s.inertial_loads, bulk, gi, ref)
        assert np.allclose(s.closure[:3], partial[:3], atol=1e-12 * lift)


def test_g2_direct_closure_shifts_by_exactly_the_transient_resultant(direct_run):
    res, _ic, bulk, gi = direct_run
    ref = np.array([bulk.grids[bulk.supports[0].gid].x, bulk.grids[bulk.supports[0].gid].y, bulk.grids[bulk.supports[0].gid].z])
    step = res.steps[_dynamic_sample(res)]
    partial = load_resultant(step.grid_loads + step.inertial_loads, bulk, gi, ref)
    extra = load_resultant(_transient_terms(step), bulk, gi, ref)
    assert np.allclose(step.closure, partial + extra, rtol=1e-12, atol=1e-9)
    assert np.linalg.norm(extra[:3]) > 0.0     # the direct solver does react it


# --------------------------------------------------------------------------- #
# G3 — static anchor
# --------------------------------------------------------------------------- #

def test_g3_held_commands_reproduce_the_static_net_load_direct():
    res, ic, _bulk, _gi = _maneuver(commands_builder=None, tend=0.2)
    scale = np.max(np.abs(ic.net_loads))
    for s in res.steps:
        assert np.max(np.abs(s.net_loads - ic.net_loads)) < 1e-8 * scale


def test_g3_held_commands_reproduce_the_static_net_load_modal():
    res, ic, _bulk, _gi = _modal_run(commanded=False)
    scale = np.max(np.abs(ic.net_loads))
    for s in res.steps:
        assert np.max(np.abs(s.net_loads - ic.net_loads)) < 1e-8 * scale
