"""Tests for _get_pre_solve_warnings in viewer/app.py."""
import math

import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.element import Cbar
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.model.constraint import Spc1
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.viewer.app import _get_pre_solve_warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _two_node_bulk(*, ga_xyz=(0, 0, 0), gb_xyz=(1, 0, 0), rho=7800.0, E=200e9) -> BulkData:
    """Minimal BulkData with one CBAR between GID 1 and GID 2."""
    from sbeam.model.property import Pbar
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=ga_xyz[0], y=ga_xyz[1], z=ga_xyz[2])
    bulk.grids[2] = Grid(gid=2, x=gb_xyz[0], y=gb_xyz[1], z=gb_xyz[2])
    bulk.pbars[10] = Pbar(pid=10, mid=20, A=1e-4, I1=1e-8, I2=1e-8, J=1e-8)
    bulk.mat1s[20] = Mat1(mid=20, E=E, G=80e9, nu=0.3, rho=rho)
    bulk.cbars[100] = Cbar(eid=100, pid=10, ga=1, gb=2, x1=0, x2=1, x3=0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    return bulk


def _sol101_cc(spc_sid=1) -> CaseControl:
    sc = SubcaseControl(subcase_id=1, load_sid=10, spc_sid=spc_sid)
    return CaseControl(sol=101, subcases=[sc])


def _sol103_cc(spc_sid=None) -> CaseControl:
    sc = SubcaseControl(subcase_id=1, spc_sid=spc_sid)
    return CaseControl(sol=103, subcases=[sc])


# ---------------------------------------------------------------------------
# 1. Zero-length CBAR
# ---------------------------------------------------------------------------

def test_zero_length_cbar_flagged():
    bulk = _two_node_bulk(ga_xyz=(1, 2, 3), gb_xyz=(1, 2, 3))
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert any("Zero-length CBAR" in m for m in msgs)
    assert any("100" in m for m in msgs)  # EID appears in message


def test_nonzero_length_cbar_ok():
    bulk = _two_node_bulk(ga_xyz=(0, 0, 0), gb_xyz=(1, 0, 0))
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert not any("Zero-length" in m for m in msgs)


# ---------------------------------------------------------------------------
# 2. SPC coverage
# ---------------------------------------------------------------------------

def test_no_spc_sol101_warns():
    bulk = _two_node_bulk()
    bulk.spcs.clear()
    bulk.spc1s.clear()
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert any("singular stiffness matrix" in m for m in msgs)
    assert any("SOL 101" in m for m in msgs)


def test_no_spc_sol103_warns_free_free():
    bulk = _two_node_bulk()
    bulk.spcs.clear()
    bulk.spc1s.clear()
    msgs = _get_pre_solve_warnings(bulk, _sol103_cc(), [])
    assert any("free-free" in m for m in msgs)
    assert not any("SOL 101 will fail" in m for m in msgs)


def test_no_spc_no_cc_warns_sol101_path():
    bulk = _two_node_bulk()
    bulk.spcs.clear()
    bulk.spc1s.clear()
    msgs = _get_pre_solve_warnings(bulk, None, [])
    assert any("singular stiffness matrix" in m for m in msgs)


def test_spc_sid_missing_from_bulk():
    bulk = _two_node_bulk()
    # spc1s has SID 1, but case control references SID 99
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(spc_sid=99), [])
    assert any("SPC SID 99" in m for m in msgs)
    assert any("Subcase 1" in m for m in msgs)


def test_spc_sid_present_no_warning():
    bulk = _two_node_bulk()  # spc1s[1] exists
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(spc_sid=1), [])
    assert not any("SPC SID" in m for m in msgs)


# ---------------------------------------------------------------------------
# 3. Unsupported load cards
# ---------------------------------------------------------------------------

def test_pload1_in_parse_warnings():
    bulk = _two_node_bulk()
    parse_warnings = ["Unknown BDF card 'PLOAD1' — skipped"]
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), parse_warnings)
    assert any("PLOAD1" in m for m in msgs)
    assert any("ignored during parsing" in m for m in msgs)


def test_multiple_unsupported_load_cards():
    bulk = _two_node_bulk()
    parse_warnings = [
        "Unknown BDF card 'PLOAD1' — skipped",
        "Unknown BDF card 'RFORCE' — skipped",
    ]
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), parse_warnings)
    assert any("PLOAD1" in m and "RFORCE" in m for m in msgs)


def test_unknown_non_load_card_not_flagged():
    bulk = _two_node_bulk()
    parse_warnings = ["Unknown BDF card 'SOMECARD' — skipped"]
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), parse_warnings)
    assert not any("SOMECARD" in m for m in msgs)


# ---------------------------------------------------------------------------
# 4. Zero density for SOL 103
# ---------------------------------------------------------------------------

def test_zero_rho_sol103_warns():
    bulk = _two_node_bulk(rho=0.0)
    msgs = _get_pre_solve_warnings(bulk, _sol103_cc(), [])
    assert any("rho=0" in m for m in msgs)
    assert any("SOL 103" in m for m in msgs)


def test_zero_rho_sol101_no_warning():
    # rho=0 is not a problem for SOL 101 (no mass matrix needed)
    bulk = _two_node_bulk(rho=0.0)
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert not any("rho=0" in m for m in msgs)


# ---------------------------------------------------------------------------
# 5. Units consistency heuristic
# ---------------------------------------------------------------------------

def test_e_ratio_large_warns():
    from sbeam.model.property import Pbar
    bulk = _two_node_bulk(E=200e9)
    bulk.grids[3] = Grid(gid=3, x=2, y=0, z=0)
    bulk.pbars[11] = Pbar(pid=11, mid=21, A=1e-4, I1=1e-8, I2=1e-8, J=1e-8)
    bulk.mat1s[21] = Mat1(mid=21, E=70e3, G=27e3, nu=0.3, rho=2700.0)
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert any("unit inconsistency" in m.lower() for m in msgs)


def test_e_ratio_small_no_warning():
    from sbeam.model.property import Pbar
    bulk = _two_node_bulk(E=200e9)
    bulk.grids[3] = Grid(gid=3, x=2, y=0, z=0)
    bulk.pbars[11] = Pbar(pid=11, mid=21, A=1e-4, I1=1e-8, I2=1e-8, J=1e-8)
    bulk.mat1s[21] = Mat1(mid=21, E=70e9, G=27e9, nu=0.3, rho=2700.0)
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert not any("unit inconsistency" in m.lower() for m in msgs)


def test_single_material_no_ratio_warning():
    bulk = _two_node_bulk(E=200e9)
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert not any("unit inconsistency" in m.lower() for m in msgs)


# ---------------------------------------------------------------------------
# 6. Clean model produces no warnings
# ---------------------------------------------------------------------------

def test_clean_model_no_warnings():
    bulk = _two_node_bulk()
    msgs = _get_pre_solve_warnings(bulk, _sol101_cc(), [])
    assert msgs == []
