"""Unit tests for coord_transform.py."""

import math
import numpy as np
import pytest

from sbeam.model.coordinate_system import Cord2r
from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.assembly.coord_transform import (
    build_transform,
    to_global,
    to_local,
    resolve_grid_positions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cord2rs(**kwargs):
    """Build a cord2rs dict from keyword arguments {cid: Cord2r(...)}."""
    return kwargs


def _cord2r(cid, rid=0, a=(0,0,0), b=(0,0,1), c=(1,0,0)):
    return Cord2r(cid=cid, rid=rid, a=a, b=b, c=c)


# ---------------------------------------------------------------------------
# CID 0 identity
# ---------------------------------------------------------------------------

class TestCid0:
    def test_build_transform_returns_identity(self):
        R = build_transform(0, {})
        np.testing.assert_allclose(R, np.eye(3), atol=1e-14)

    def test_to_global_noop(self):
        v = np.array([1.0, 2.0, 3.0])
        np.testing.assert_allclose(to_global(v, 0, {}), v)

    def test_to_local_noop(self):
        v = np.array([1.0, 2.0, 3.0])
        np.testing.assert_allclose(to_local(v, 0, {}), v)


# ---------------------------------------------------------------------------
# Standard orientation (identity CORD2R)
# ---------------------------------------------------------------------------

class TestIdentityCord2r:
    """CORD2R aligned with global axes should give identity rotation."""

    @pytest.fixture
    def crs(self):
        # Z-axis = global Z, XZ-plane defined by global X
        return {1: _cord2r(1, 0, a=(0,0,0), b=(0,0,1), c=(1,0,0))}

    def test_rotation_is_identity(self, crs):
        R = build_transform(1, crs)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-14)

    def test_to_global_unchanged(self, crs):
        v = np.array([3.0, 0.0, 0.0])
        np.testing.assert_allclose(to_global(v, 1, crs), v, atol=1e-14)


# ---------------------------------------------------------------------------
# 90° rotation about Z
# ---------------------------------------------------------------------------

class TestRotation90DegZ:
    """CORD2R where local X = global Y (90° CCW about Z)."""

    @pytest.fixture
    def crs(self):
        # Z = global Z, C in direction of global Y → local X = global Y
        return {1: _cord2r(1, 0, a=(0,0,0), b=(0,0,1), c=(0,1,0))}

    def test_rotation_matrix(self, crs):
        R = build_transform(1, crs)
        # local X (1,0,0) → global (0,1,0)
        np.testing.assert_allclose(R @ [1,0,0], [0,1,0], atol=1e-14)
        # local Y (0,1,0) → global (-1,0,0)
        np.testing.assert_allclose(R @ [0,1,0], [-1,0,0], atol=1e-14)
        # local Z (0,0,1) → global (0,0,1)
        np.testing.assert_allclose(R @ [0,0,1], [0,0,1], atol=1e-14)

    def test_orthonormal(self, crs):
        R = build_transform(1, crs)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-14)
        assert abs(np.linalg.det(R) - 1.0) < 1e-14

    def test_to_global_then_local_roundtrip(self, crs):
        v = np.array([2.0, 3.0, 4.0])
        np.testing.assert_allclose(to_local(to_global(v, 1, crs), 1, crs), v, atol=1e-14)


# ---------------------------------------------------------------------------
# Translated origin
# ---------------------------------------------------------------------------

class TestTranslatedOrigin:
    """CORD2R with A != origin — affects point transform but not vector rotation."""

    @pytest.fixture
    def crs(self):
        # origin at (5, 0, 0), Z = global Z, X = global X
        return {1: _cord2r(1, 0, a=(5,0,0), b=(5,0,1), c=(6,0,0))}

    def test_rotation_still_identity(self, crs):
        R = build_transform(1, crs)
        np.testing.assert_allclose(R, np.eye(3), atol=1e-14)


# ---------------------------------------------------------------------------
# Chained coordinate systems
# ---------------------------------------------------------------------------

class TestChainedCord2r:
    """CID 2 defined relative to CID 1 (which is 90° about Z)."""

    @pytest.fixture
    def crs(self):
        # CID 1: local X = global Y (90° about Z)
        c1 = _cord2r(1, 0, a=(0,0,0), b=(0,0,1), c=(0,1,0))
        # CID 2 in CID 1 frame, identity relative to CID 1
        # → should combine to a further 90° rotation (total 180° about Z)
        # In CID 1 frame: Z = (0,0,1), C points in local Y = (-1,0,0) in global
        c2 = _cord2r(2, 1, a=(0,0,0), b=(0,0,1), c=(0,1,0))
        return {1: c1, 2: c2}

    def test_chained_rotation(self, crs):
        R = build_transform(2, crs)
        # Two 90° CCW rotations = 180° about Z
        # local X2 (1,0,0) → global (-1, 0, 0)
        np.testing.assert_allclose(R @ [1,0,0], [-1,0,0], atol=1e-12)
        np.testing.assert_allclose(R @ [0,0,1], [0,0,1], atol=1e-12)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestErrors:
    def test_undefined_cid_raises(self):
        with pytest.raises(ValueError, match="CID 99 not defined"):
            build_transform(99, {})

    def test_circular_reference_raises(self):
        crs = {
            1: _cord2r(1, rid=2, a=(0,0,0), b=(0,0,1), c=(1,0,0)),
            2: _cord2r(2, rid=1, a=(0,0,0), b=(0,0,1), c=(1,0,0)),
        }
        with pytest.raises(ValueError, match="Circular reference"):
            build_transform(1, crs)

    def test_collinear_points_raises(self):
        crs = {1: _cord2r(1, 0, a=(0,0,0), b=(1,0,0), c=(2,0,0))}
        with pytest.raises(ValueError, match="collinear"):
            build_transform(1, crs)

    def test_coincident_ab_raises(self):
        crs = {1: _cord2r(1, 0, a=(1,0,0), b=(1,0,0), c=(2,0,0))}
        with pytest.raises(ValueError, match="coincident"):
            build_transform(1, crs)


# ---------------------------------------------------------------------------
# resolve_grid_positions
# ---------------------------------------------------------------------------

class TestResolveGridPositions:
    def test_cp0_grids_unchanged(self):
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=3.0, y=4.0, z=5.0, cp=0)
        resolve_grid_positions(bulk)
        assert bulk.grids[1].x == pytest.approx(3.0)
        assert bulk.grids[1].y == pytest.approx(4.0)
        assert bulk.grids[1].z == pytest.approx(5.0)

    def test_cp_nonzero_transforms(self):
        """Grid at local (1,0,0) in 90°-rotated frame → global (0,1,0)."""
        bulk = BulkData()
        bulk.cord2rs[1] = _cord2r(1, 0, a=(0,0,0), b=(0,0,1), c=(0,1,0))
        bulk.grids[1] = Grid(gid=1, x=1.0, y=0.0, z=0.0, cp=1)
        resolve_grid_positions(bulk)
        assert bulk.grids[1].x == pytest.approx(0.0, abs=1e-14)
        assert bulk.grids[1].y == pytest.approx(1.0, abs=1e-14)
        assert bulk.grids[1].z == pytest.approx(0.0, abs=1e-14)
        assert bulk.grids[1].cp == 0

    def test_cp_with_offset_origin(self):
        """CORD2R origin at (2,0,0) — grid at local (0,0,0) maps to global (2,0,0)."""
        bulk = BulkData()
        bulk.cord2rs[1] = _cord2r(1, 0, a=(2,0,0), b=(2,0,1), c=(3,0,0))
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0, cp=1)
        resolve_grid_positions(bulk)
        assert bulk.grids[1].x == pytest.approx(2.0, abs=1e-14)
        assert bulk.grids[1].y == pytest.approx(0.0, abs=1e-14)

    def test_undefined_cp_raises(self):
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=1.0, y=0.0, z=0.0, cp=5)
        with pytest.raises(ValueError, match="CP=5"):
            resolve_grid_positions(bulk)
