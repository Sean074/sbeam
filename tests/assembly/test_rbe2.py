"""Tests for RBE2 DOF transformation matrix (Step 36)."""

import numpy as np
import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.model.element import Rbe2, Rbe3
from sbeam.assembly.rbe3 import build_rbe3_transformation


def _two_grid_bulk():
    """2 grids: GID 1 (indep index 0), GID 2 (dep index 1). n_dof=12."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    return bulk


def _three_grid_bulk():
    """3 grids: GID 1 (indep index 0), GID 2 (dep index 1), GID 3 (dep index 2). n_dof=18."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.grids[3] = Grid(gid=3, x=2.0, y=0.0, z=0.0)
    return bulk


def _grid_index(bulk: BulkData) -> dict:
    return {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}


class TestRbe2NoElement:
    def test_no_rbe2_returns_identity(self):
        bulk = _two_grid_bulk()
        gi = _grid_index(bulk)
        T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, gi)
        assert dep_dofs == []
        assert len(red_dofs) == 12
        assert np.allclose(T, np.eye(12))


class TestRbe2SingleDof:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _two_grid_bulk()
        self.bulk.rbe2s[1] = Rbe2(eid=1, gn=1, cm="2", gm=[2])
        self.gi = _grid_index(self.bulk)
        self.T, self.dep_dofs, self.red_dofs = build_rbe3_transformation(self.bulk, self.gi)

    def test_dep_dofs_length(self):
        # GID 2 (index 1) DOF Ty (d=1) → global 6*1+1 = 7
        assert len(self.dep_dofs) == 1

    def test_dep_dof_global_index(self):
        assert self.dep_dofs == [7]

    def test_red_dofs_excludes_dep(self):
        assert 7 not in self.red_dofs
        assert len(self.red_dofs) == 11

    def test_T_shape(self):
        assert self.T.shape == (12, 11)

    def test_T_dep_row_maps_to_indep(self):
        # T[7, col] should be 1.0 where col corresponds to GID1 DOF Ty=1 (global index 1)
        col = self.red_dofs.index(1)
        assert self.T[7, col] == pytest.approx(1.0)
        other_cols = [c for c in range(11) if c != col]
        for c in other_cols:
            assert self.T[7, c] == pytest.approx(0.0)

    def test_non_dep_rows_are_identity_columns(self):
        for p in self.red_dofs:
            col = self.red_dofs.index(p)
            assert self.T[p, col] == pytest.approx(1.0)


class TestRbe2AllDofs:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _two_grid_bulk()
        self.bulk.rbe2s[1] = Rbe2(eid=1, gn=1, cm="123456", gm=[2])
        self.gi = _grid_index(self.bulk)
        self.T, self.dep_dofs, self.red_dofs = build_rbe3_transformation(self.bulk, self.gi)

    def test_dep_dofs_all_six(self):
        # GID 2 has index 1 → DOFs 6..11 are all dependent
        assert self.dep_dofs == [6, 7, 8, 9, 10, 11]

    def test_red_dofs_only_indep(self):
        assert self.red_dofs == [0, 1, 2, 3, 4, 5]

    def test_T_shape(self):
        assert self.T.shape == (12, 6)

    def test_T_rigid_coupling(self):
        # T[6+d, d] == 1.0 for d in 0..5
        for d in range(6):
            assert self.T[6 + d, d] == pytest.approx(1.0)


class TestRbe2TwoDepGrids:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.bulk = _three_grid_bulk()
        self.bulk.rbe2s[1] = Rbe2(eid=1, gn=1, cm="123", gm=[2, 3])
        self.gi = _grid_index(self.bulk)
        self.T, self.dep_dofs, self.red_dofs = build_rbe3_transformation(self.bulk, self.gi)

    def test_dep_dofs_count(self):
        # 3 DOFs per dep grid × 2 grids = 6
        assert len(self.dep_dofs) == 6

    def test_red_dofs_count(self):
        # 18 total - 6 dep = 12
        assert len(self.red_dofs) == 12

    def test_T_shape(self):
        assert self.T.shape == (18, 12)


class TestRbe2DisplacementRecovery:
    def test_gm_equals_gn_after_recovery(self):
        """u[GM DOFs] must equal u[GN DOFs] after T @ u_red."""
        bulk = _two_grid_bulk()
        bulk.rbe2s[1] = Rbe2(eid=1, gn=1, cm="123456", gm=[2])
        gi = _grid_index(bulk)
        T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, gi)

        # u_red has 6 components (only GN's DOFs remain)
        u_red = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.06])
        u_full = T @ u_red

        # GN (index 0) → DOFs 0..5
        np.testing.assert_allclose(u_full[0:6], u_red, atol=1e-15)
        # GM (index 1) → DOFs 6..11 must equal GN
        np.testing.assert_allclose(u_full[6:12], u_red, atol=1e-15)


class TestRbe2WithRbe3Coexistence:
    def test_both_present(self):
        """RBE2 and RBE3 in same model: dep_dofs from both are collected."""
        bulk = BulkData()
        for i in range(1, 5):
            bulk.grids[i] = Grid(gid=i, x=float(i - 1), y=0.0, z=0.0)

        # RBE3: GID 1 is dependent, GID 2 is independent (Ty only)
        bulk.rbe3s[10] = Rbe3(eid=10, refgrid=1, refc="2", wt_gc=[(1.0, "2", [2])])
        # RBE2: GID 4 is dependent on GID 3 (all DOFs)
        bulk.rbe2s[20] = Rbe2(eid=20, gn=3, cm="123456", gm=[4])

        gi = _grid_index(bulk)
        T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, gi)

        # RBE3 eliminates 1 DOF (GID1/Ty); RBE2 eliminates 6 DOFs (GID4 all)
        assert len(dep_dofs) == 7
        assert T.shape == (24, 17)


class TestRbe2GnInDepSetRaises:
    def test_gn_as_dep_raises(self):
        """RBE2 GN that is itself a dependent DOF must raise ValueError."""
        bulk = _three_grid_bulk()
        # RBE2 #1: GID 3 depends on GID 2
        bulk.rbe2s[1] = Rbe2(eid=1, gn=2, cm="1", gm=[3])
        # RBE2 #2: GID 2 depends on GID 1 — but GID2/DOF1 is now in dep_set from #1
        # Wait: #1 makes GID3 dependent on GID2; GID2 is GN for #1.
        # Then #2 makes GID2 dependent on GID1.
        # After processing #2 in the RBE2 pass, GID2/DOF1 enters dep_set.
        # Post-validation of #1 detects GID2/DOF1 is in dep_set and raises.
        bulk.rbe2s[2] = Rbe2(eid=2, gn=1, cm="1", gm=[2])
        gi = _grid_index(bulk)
        with pytest.raises(ValueError, match="GN=2"):
            build_rbe3_transformation(bulk, gi)
