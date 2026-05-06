"""Parser tests for CORD2R coordinate system card."""

import math
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.model.coordinate_system import Cord2r


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cord2r_lines(cid, rid, a, b, c):
    """Free-field CORD2R + continuation lines."""
    return [
        f"CORD2R, {cid}, {rid}, {a[0]}, {a[1]}, {a[2]}, {b[0]}, {b[1]}, {b[2]}",
        f"+, {c[0]}, {c[1]}, {c[2]}",
    ]


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

class TestCord2rParser:
    def test_free_field_roundtrip(self):
        lines = _cord2r_lines(1, 0, (0, 0, 0), (0, 0, 1), (1, 0, 0))
        bulk = parse_bulk_data(lines)
        assert 1 in bulk.cord2rs
        cs = bulk.cord2rs[1]
        assert cs.cid == 1
        assert cs.rid == 0
        assert cs.a == pytest.approx((0.0, 0.0, 0.0))
        assert cs.b == pytest.approx((0.0, 0.0, 1.0))
        assert cs.c == pytest.approx((1.0, 0.0, 0.0))

    def test_fixed_field_roundtrip(self):
        lines = [
            "CORD2R         1       0     0.0     0.0     0.0     0.0     0.0     1.0",
            "+            1.0     0.0     0.0",
        ]
        bulk = parse_bulk_data(lines)
        assert 1 in bulk.cord2rs
        cs = bulk.cord2rs[1]
        assert cs.b == pytest.approx((0.0, 0.0, 1.0))
        assert cs.c == pytest.approx((1.0, 0.0, 0.0))

    def test_non_zero_rid_stored(self):
        lines = (
            _cord2r_lines(1, 0, (0, 0, 0), (0, 0, 1), (1, 0, 0))
            + _cord2r_lines(2, 1, (1, 0, 0), (1, 0, 1), (2, 0, 0))
        )
        bulk = parse_bulk_data(lines)
        assert bulk.cord2rs[2].rid == 1

    def test_unnamed_continuation(self):
        """Continuation without + marker (blank first field in fixed format)."""
        # Proper 8-char NASTRAN fixed field: blank(8)|C1(8)|C2(8)|C3(8)
        lines = [
            "CORD2R         1       0     0.0     0.0     0.0     0.0     0.0     1.0",
            "             1.0     0.0     0.0",
        ]
        bulk = parse_bulk_data(lines)
        assert 1 in bulk.cord2rs
        assert bulk.cord2rs[1].c == pytest.approx((1.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

class TestCord2rErrors:
    def test_duplicate_cid_raises(self):
        lines = (
            _cord2r_lines(1, 0, (0, 0, 0), (0, 0, 1), (1, 0, 0))
            + _cord2r_lines(1, 0, (0, 0, 0), (0, 1, 0), (1, 0, 0))
        )
        with pytest.raises(ValueError, match="Duplicate coordinate system CID 1"):
            parse_bulk_data(lines)

    def test_missing_continuation_raises(self):
        lines = ["CORD2R, 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0"]
        with pytest.raises(ValueError, match="continuation"):
            parse_bulk_data(lines)

    def test_cid_zero_raises(self):
        lines = _cord2r_lines(0, 0, (0, 0, 0), (0, 0, 1), (1, 0, 0))
        with pytest.raises(ValueError, match="CID must be > 0"):
            parse_bulk_data(lines)


# ---------------------------------------------------------------------------
# GRID CP/CD integration
# ---------------------------------------------------------------------------

class TestGridCoordSystem:
    def test_grid_cp_transforms_position(self):
        """GRID defined in a rotated CP system ends up in global CID 0."""
        # CORD2R 1: origin at (0,0,0), Z=global-Z, X=global-Y
        # → local X = global Y, local Y = -global X, local Z = global Z
        # A grid at local (1, 0, 0) should map to global (0, 1, 0)
        lines = (
            _cord2r_lines(1, 0, (0, 0, 0), (0, 0, 1), (0, 1, 0))
            + ["GRID, 1, 1, 1.0, 0.0, 0.0"]   # local (1,0,0) in CID 1
        )
        bulk = parse_bulk_data(lines)
        g = bulk.grids[1]
        assert g.x == pytest.approx(0.0, abs=1e-12)
        assert g.y == pytest.approx(1.0, abs=1e-12)
        assert g.z == pytest.approx(0.0, abs=1e-12)
        assert g.cp == 0  # zeroed after resolution

    def test_grid_cd_preserved(self):
        """Grid CD field is stored and not zeroed."""
        lines = (
            _cord2r_lines(1, 0, (0, 0, 0), (0, 0, 1), (1, 0, 0))
            + ["GRID, 1, 0, 0.0, 0.0, 0.0, 1"]
        )
        bulk = parse_bulk_data(lines)
        assert bulk.grids[1].cd == 1

    def test_grid_cp0_unchanged(self):
        """Grid with CP=0 (global) has position unchanged."""
        lines = ["GRID, 1, 0, 3.0, 4.0, 5.0"]
        bulk = parse_bulk_data(lines)
        g = bulk.grids[1]
        assert g.x == pytest.approx(3.0)
        assert g.y == pytest.approx(4.0)
        assert g.z == pytest.approx(5.0)

    def test_undefined_cp_raises(self):
        """GRID referencing undefined CP system raises ValueError."""
        lines = ["GRID, 1, 99, 1.0, 0.0, 0.0"]
        with pytest.raises(ValueError, match="CP=99"):
            parse_bulk_data(lines)
