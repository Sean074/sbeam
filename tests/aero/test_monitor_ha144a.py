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
