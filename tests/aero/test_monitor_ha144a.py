"""V-MON1 — HA144A monitor-point cross-check (closing gate for MON1–MON4).

The full-span HA144A deck carries four monitor cards (see the MONITOR POINTS
block in ``sample/ha144a_fullspan_sbeam.bdf``):

  * MWINGRT — MONPNT3 wing-root cut, SET1 = {100}
  * MWINGEA — MONPNT3 right-wing EA, SET1 = {100, 110, 120}
  * MALLEA  — MONPNT3 whole-aircraft EA, SET1 = all spline target grids
  * MALLAR  — MONPNT1 whole-aircraft aero, AELIST = all CAERO1 boxes

Gates:
  * spline conservation — MONPNT1 (all boxes) aero == MONPNT3 (all grids) aero;
  * total trimmed lift — whole-aircraft MONPNT3 Fz == 1g weight (16000 lb);
  * aero/inertia/reaction breakdown is consistent (totals == Σ contributions);
  * section cuts return finite, sign-correct loads (regression lock).
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"
G = 32.174  # ft/s², deck gravity


@pytest.fixture(scope="module")
def trim():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero
        )
    return result, bulk


def test_monitors_present(trim):
    result, _ = trim
    assert set(result.monitor_loads) == {"MWINGRT", "MWINGEA", "MALLEA", "MALLAR"}


def test_spline_conservation_monpnt1_vs_monpnt3(trim):
    """MONPNT1 (all boxes) aero == MONPNT3 (all grids) aero — spline conserves
    net force/moment.  Force is exact to machine precision; the moment carries
    the spline rotational-row numerics (~1e-6 relative)."""
    result, _ = trim
    a1 = result.monitor_loads["MALLAR"].aero
    a3 = result.monitor_loads["MALLEA"].aero
    # Force components: machine precision relative to total lift.
    assert a1[:3] == pytest.approx(a3[:3], abs=1e-6)
    # Moment components: spline numerics.
    assert a1[3:] == pytest.approx(a3[3:], rel=1e-5, abs=1e-3)


def test_whole_aircraft_lift_equals_weight(trim):
    """Whole-aircraft MONPNT3 aero Fz == 1g trimmed weight (~16000 lb) within 1%."""
    result, bulk = trim
    weight = sum(c.m for c in bulk.conm2s.values()) * G
    # The aero column carries the total lift; at 1g trim lift balances weight.
    fz_aero = result.monitor_loads["MALLEA"].aero[2]
    assert fz_aero == pytest.approx(weight, rel=0.01)
    assert weight == pytest.approx(16000.0, rel=1e-3)


def test_breakdown_sums_to_total(trim):
    result, _ = trim
    for name, ml in result.monitor_loads.items():
        total_check = ml.aero + ml.inertia + ml.reaction
        assert ml.totals == pytest.approx(total_check, abs=1e-9), name


def test_section_cuts_finite_and_lift_positive(trim):
    """Wing-root and right-wing cuts return finite loads; right wing lifts up."""
    result, _ = trim
    for name in ("MWINGRT", "MWINGEA"):
        ml = result.monitor_loads[name]
        assert np.all(np.isfinite(ml.totals))
    # Right-wing aero carries positive lift.
    assert result.monitor_loads["MWINGEA"].aero[2] > 0.0


def test_inertia_column_live(trim):
    """The deck is a 1g gravity trim (URDD3 = -32.174 prescribed), so the MONPNT3
    inertia column is non-zero — the plumbing that consumes
    ``Sol144TrimResult.inertial_loads`` is exercised, not just zero-by-default."""
    result, _ = trim
    inertia = result.monitor_loads["MALLEA"].inertia
    assert np.linalg.norm(inertia) > 1.0


# ---------------------------------------------------------------------------
# DEF-M10 — whole-aircraft mass coverage
# ---------------------------------------------------------------------------

def _run(bulk):
    """Trim ``bulk``, returning (result, coverage warnings raised)."""
    gi = build_grid_index(bulk)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    coverage = [str(w.message) for w in caught
                if "CONM2-bearing" in str(w.message)]
    return result, coverage


def test_whole_aircraft_set1_covers_every_conm2_grid():
    """SET1 1310 must include every mass-bearing grid.

    Grid 97 carries a 93.236-slug CONM2 but no spline load, so it was omitted —
    18.75 % of the model inertia missing from the 'whole aircraft' monitor.
    """
    _cc, bulk = parse_bdf(str(BDF_PATH))
    conm2_grids = {c.gid for c in bulk.conm2s.values()}
    set1_grids = set(bulk.set1s[1310].grids)
    assert conm2_grids - set1_grids == set(), (
        f"SET1 1310 omits CONM2-bearing grids {sorted(conm2_grids - set1_grids)}")


def test_whole_aircraft_monitor_closes_on_a_balanced_trim(trim):
    """Aero and inertia cancel: a balanced 1g trim has no net section load.

    This is the observable the omission corrupted — MALLEA reported ~+3000 lb
    of phantom lift (exactly the missing 93.236 slug × 32.174).
    """
    result, _ = trim
    ml = result.monitor_loads["MALLEA"]
    assert ml.totals[2] == pytest.approx(0.0, abs=1e-6 * abs(ml.aero[2]))


def test_missing_mass_grid_raises_a_coverage_warning():
    """A whole-aircraft monitor that omits a CONM2 grid is called out."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    bulk.set1s[1310].grids = [g for g in bulk.set1s[1310].grids if g != 97]
    result, coverage = _run(bulk)
    assert len(coverage) == 1, coverage
    msg = coverage[0]
    assert "MALLEA" in msg and "97" in msg and "18.75%" in msg
    # And the warning is warranted: the monitor really is out of balance.
    assert abs(result.monitor_loads["MALLEA"].totals[2]) > 1000.0


def test_section_cuts_do_not_warn():
    """The check must not cry wolf on deliberate partial cuts.

    MWINGRT (one grid) and MWINGEA (one wing) legitimately exclude most of the
    model's mass; only a monitor integrating the *whole* aero load is checked.
    """
    _cc, bulk = parse_bdf(str(BDF_PATH))
    _result, coverage = _run(bulk)
    assert coverage == []
