"""Tests for RBAR DOF transformation matrix (Step 37)."""

import numpy as np
import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.model.element import Rbar, Rbe2
from sbeam.assembly.rbe3 import build_rbe3_transformation


def _two_grid_bulk(dx=1.0, dy=0.0, dz=0.0):
    """2 grids: GID 1 at origin, GID 2 offset by (dx, dy, dz). n_dof=12."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=dx, y=dy, z=dz)
    return bulk


def _grid_index(bulk: BulkData) -> dict:
    return {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}


class TestRbarNoElement:
    def test_no_rbar_returns_identity(self):
        bulk = _two_grid_bulk()
        gi = _grid_index(bulk)
        T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, gi)
        assert dep_dofs == []
        assert len(red_dofs) == 12
        assert np.allclose(T, np.eye(12))


class TestRbarBasicOffset:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _two_grid_bulk(dx=1.0)
        self.bulk.rbars[1] = Rbar(eid=1, ga=1, gb=2)
        self.gi = _grid_index(self.bulk)
        self.T, self.dep_dofs, self.red_dofs = build_rbe3_transformation(self.bulk, self.gi)

    def test_dep_dofs_are_all_gb_dofs(self):
        # GID 2 is index 1 → global DOFs 6..11 are all dependent
        assert self.dep_dofs == [6, 7, 8, 9, 10, 11]

    def test_red_dofs_are_only_ga(self):
        assert self.red_dofs == [0, 1, 2, 3, 4, 5]

    def test_T_shape(self):
        assert self.T.shape == (12, 6)


class TestRbarKinematicsMatrix:
    """Verify every entry of the embedded R block in T against the formula."""

    def test_all_R_entries(self):
        dx, dy, dz = 1.0, 0.5, 0.25
        bulk = _two_grid_bulk(dx=dx, dy=dy, dz=dz)
        bulk.rbars[1] = Rbar(eid=1, ga=1, gb=2)
        gi = _grid_index(bulk)
        T, _, _ = build_rbe3_transformation(bulk, gi)

        # Expected R (6×6):
        R_expected = np.array([
            [1, 0, 0,   0,  dz, -dy],
            [0, 1, 0, -dz,   0,  dx],
            [0, 0, 1,  dy, -dx,   0],
            [0, 0, 0,   1,   0,   0],
            [0, 0, 0,   0,   1,   0],
            [0, 0, 0,   0,   0,   1],
        ])

        # T[6:12, 0:6] should equal R
        np.testing.assert_allclose(T[6:12, 0:6], R_expected, atol=1e-15)


class TestRbarZeroOffset:
    """With d=(0,0,0) the R matrix must be identity — equivalent to RBE2."""

    def test_zero_offset_is_identity(self):
        bulk = _two_grid_bulk(dx=0.0, dy=0.0, dz=0.0)
        bulk.rbars[1] = Rbar(eid=1, ga=1, gb=2)
        gi = _grid_index(bulk)
        T, _, _ = build_rbe3_transformation(bulk, gi)

        np.testing.assert_allclose(T[6:12, 0:6], np.eye(6), atol=1e-15)


class TestRbarLeverbArmEffect:
    """Key RBAR vs RBE2 distinction: rotation at GA produces translation at GB."""

    def test_rotation_produces_offset_translation(self):
        L = 2.0
        bulk = _two_grid_bulk(dx=L, dy=0.0, dz=0.0)
        bulk.rbars[1] = Rbar(eid=1, ga=1, gb=2)
        gi = _grid_index(bulk)
        T, _, red_dofs = build_rbe3_transformation(bulk, gi)

        # u_red: only θ_Ay (DOF index 4 of GA, i.e. red_dofs[4]) = 1.0
        u_red = np.zeros(6)
        u_red[4] = 1.0  # θ_Ay at GA
        u_full = T @ u_red

        # From R: u_Bz = dy*θ_Ax - dx*θ_Ay + 0 = 0 - L*1.0 = -L
        # (row 2, col 4 of R is -dx = -L)
        assert u_full[8] == pytest.approx(-L, abs=1e-14)   # u_Bz

        # θ_By (DOF 10) must equal θ_Ay = 1.0
        assert u_full[10] == pytest.approx(1.0, abs=1e-14)

        # u_Bx and u_By must be zero (no coupling with θ_Ay for dx-only offset)
        assert u_full[6] == pytest.approx(0.0, abs=1e-14)  # u_Bx
        assert u_full[7] == pytest.approx(0.0, abs=1e-14)  # u_By


class TestRbarDisplacementRecovery:
    """u_full[6:12] must equal R @ u_full[0:6] for any arbitrary u_red."""

    def test_gb_dofs_equal_R_times_ga_dofs(self):
        dx, dy, dz = 1.5, 0.3, 0.7
        bulk = _two_grid_bulk(dx=dx, dy=dy, dz=dz)
        bulk.rbars[1] = Rbar(eid=1, ga=1, gb=2)
        gi = _grid_index(bulk)
        T, _, _ = build_rbe3_transformation(bulk, gi)

        u_red = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        u_full = T @ u_red

        R = np.array([
            [1, 0, 0,   0,  dz, -dy],
            [0, 1, 0, -dz,   0,  dx],
            [0, 0, 1,  dy, -dx,   0],
            [0, 0, 0,   1,   0,   0],
            [0, 0, 0,   0,   1,   0],
            [0, 0, 0,   0,   0,   1],
        ])
        u_gb_expected = R @ u_full[0:6]
        np.testing.assert_allclose(u_full[6:12], u_gb_expected, atol=1e-15)


class TestRbarGaInDepSetRaises:
    def test_ga_as_dep_raises(self):
        """RBAR GA that is a dependent DOF of another constraint must raise ValueError."""
        bulk = BulkData()
        for i in range(1, 4):
            bulk.grids[i] = Grid(gid=i, x=float(i - 1), y=0.0, z=0.0)

        # RBE2 makes GID 2 dependent on GID 1
        bulk.rbe2s[1] = Rbe2(eid=1, gn=1, cm="1", gm=[2])
        # RBAR tries to use GID 2 as GA (independent) — but DOF 1 of GID 2 is in dep_set
        bulk.rbars[2] = Rbar(eid=2, ga=2, gb=3)

        gi = _grid_index(bulk)
        with pytest.raises(ValueError, match="GA=2"):
            build_rbe3_transformation(bulk, gi)


class TestRbarWithRbe2Coexistence:
    def test_dep_dof_count_is_sum(self):
        """RBAR and RBE2 both present: dep_dofs = 6 (RBAR GB) + 1 (RBE2 GM partial)."""
        bulk = BulkData()
        for i in range(1, 5):
            bulk.grids[i] = Grid(gid=i, x=float(i - 1), y=0.0, z=0.0)

        # RBAR: GID 3 (GB) depends on GID 1 (GA) — 6 dep DOFs
        bulk.rbars[10] = Rbar(eid=10, ga=1, gb=3)
        # RBE2: GID 4 depends on GID 2, Ty only — 1 dep DOF
        bulk.rbe2s[20] = Rbe2(eid=20, gn=2, cm="2", gm=[4])

        gi = _grid_index(bulk)
        T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, gi)

        assert len(dep_dofs) == 7   # 6 from RBAR + 1 from RBE2
        assert T.shape == (24, 17)  # 24 total - 7 dep = 17 independent
