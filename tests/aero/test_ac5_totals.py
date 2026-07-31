"""AC5 — all-six aerodynamic trim totals on Sol144TrimResult.

The lateral/directional totals (CY, CMx roll, CMz yaw) join the longitudinal
set (CZ, CX, CMy). On the symmetric HA144A full-span deck at a symmetric trim
they must vanish, and CY must equal the per-box side-force sum independently
recomputed from ``box_forces``.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


@pytest.fixture(scope="module")
def trim_result():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero)
    return result, bulk


def test_lateral_totals_vanish_on_symmetric_trim(trim_result):
    result, _bulk = trim_result
    assert abs(result.total_cy) < 1e-10
    assert abs(result.total_cmx) < 1e-10
    assert abs(result.total_cmz) < 1e-10


def test_total_cy_matches_box_force_sum(trim_result):
    result, bulk = trim_result
    # box_forces are physical (q-scaled); CY = ΣFy / (q · sref).
    cy_boxes = float(result.box_forces[:, 1].sum()) / (result.q * bulk.aeros.sref)
    assert result.total_cy == pytest.approx(cy_boxes, abs=1e-12)


def test_longitudinal_totals_unchanged(trim_result):
    """Regression guard: CZ balances the 16000 lb weight at q=40 (sref=400)."""
    result, _bulk = trim_result
    assert result.total_cl == pytest.approx(16000.0 / (40.0 * 400.0), rel=1e-4)
