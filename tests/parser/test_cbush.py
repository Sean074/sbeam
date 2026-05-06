"""Parser tests for CBUSH and PBUSH cards (Step 37)."""

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data


def _parse(lines):
    return parse_bulk_data(lines)


class TestPbushParser:
    def test_pbush_all_stiffness_values(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0",
            "CBUSH, 1, 10, 1, 2",
        ]
        bulk = _parse(lines)
        p = bulk.pbushs[10]
        assert p.k1 == pytest.approx(1.0)
        assert p.k2 == pytest.approx(2.0)
        assert p.k3 == pytest.approx(3.0)
        assert p.k4 == pytest.approx(4.0)
        assert p.k5 == pytest.approx(5.0)
        assert p.k6 == pytest.approx(6.0)

    def test_pbush_partial_stiffness_defaults_zero(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 1000.0",
            "CBUSH, 1, 10, 1, 2",
        ]
        bulk = _parse(lines)
        p = bulk.pbushs[10]
        assert p.k1 == pytest.approx(1000.0)
        assert p.k2 == pytest.approx(0.0)
        assert p.k3 == pytest.approx(0.0)
        assert p.k4 == pytest.approx(0.0)
        assert p.k5 == pytest.approx(0.0)
        assert p.k6 == pytest.approx(0.0)

    def test_pbush_duplicate_pid_raises(self):
        lines = [
            "PBUSH, 10, K, 1000.0",
            "PBUSH, 10, K, 2000.0",
        ]
        with pytest.raises(ValueError, match="Duplicate PBUSH PID 10"):
            _parse(lines)

    def test_pbush_b_keyword_raises(self):
        lines = ["PBUSH, 10, B, 5.0"]
        with pytest.raises(ValueError, match="B.*not supported"):
            _parse(lines)


class TestCbushParser:
    def test_cbush_two_node_basic(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 5000.0",
            "CBUSH, 1, 10, 1, 2",
        ]
        bulk = _parse(lines)
        c = bulk.cbushs[1]
        assert c.eid == 1
        assert c.pid == 10
        assert c.ga == 1
        assert c.gb == 2

    def test_cbush_grounded_gb_blank(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "PBUSH, 10, K, 5000.0",
            "CBUSH, 1, 10, 1,  ,  ,  ,  ,  ,  ",
        ]
        bulk = _parse(lines)
        assert bulk.cbushs[1].gb is None

    def test_cbush_orientation_from_continuation(self):
        lines = [
            "GRID,1,,0.0,0.0,0.0",
            "GRID,2,,1.0,0.0,0.0",
            "PBUSH,10,K,1000.0",
            "CBUSH,1,10,1,2",
            "+,0.0,1.0,0.0",
        ]
        bulk = _parse(lines)
        c = bulk.cbushs[1]
        assert c.x1 == pytest.approx(0.0)
        assert c.x2 == pytest.approx(1.0)
        assert c.x3 == pytest.approx(0.0)

    def test_cbush_missing_pid_raises(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "CBUSH, 1, 99, 1, 2",
        ]
        with pytest.raises(ValueError, match="PID=99"):
            _parse(lines)

    def test_cbush_missing_ga_raises(self):
        lines = [
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 1000.0",
            "CBUSH, 1, 10, 1, 2",
        ]
        with pytest.raises(ValueError, match="GA=1"):
            _parse(lines)

    def test_cbush_missing_gb_raises(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "PBUSH, 10, K, 1000.0",
            "CBUSH, 1, 10, 1, 99",
        ]
        with pytest.raises(ValueError, match="GB=99"):
            _parse(lines)

    def test_cbush_nonzero_cid_raises(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 1000.0",
            "CBUSH, 1, 10, 1, 2, , 5",
        ]
        with pytest.raises(ValueError, match="CID=5"):
            _parse(lines)

    def test_cbush_ga_equals_gb_raises(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "PBUSH, 10, K, 1000.0",
            "CBUSH, 1, 10, 1, 1",
        ]
        with pytest.raises(ValueError, match="GA and GB must be different"):
            _parse(lines)
