"""Tests for Step 9: load vector and SPC assembly."""

import numpy as np
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force, Moment, Load
from sbeam.model.constraint import Spc, Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.load_vector import build_grid_index, assemble_load_vector
from sbeam.assembly.stiffness import (
    get_spc_dofs,
    apply_spcs,
    assemble_global_stiffness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_cantilever_bulk(L=1.0):
    """One element cantilever along X. GA fully fixed, GB free."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=2e11, G=7.7e10, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=0.05, I1=8.333e-4, I2=8.333e-4, J=1.406e-3)
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    # SPC: fix all DOFs at grid 1
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    # Load: force in Y at grid 2
    bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=1000.0, n1=0.0, n2=1.0, n3=0.0)]
    return bulk


# ---------------------------------------------------------------------------
# Step 9 tests — build_grid_index
# ---------------------------------------------------------------------------

class TestBuildGridIndex:
    def test_sorted_order(self):
        bulk = BulkData()
        bulk.grids[3] = Grid(gid=3, x=0.0, y=0.0, z=0.0)
        bulk.grids[1] = Grid(gid=1, x=1.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=2.0, y=0.0, z=0.0)
        gi = build_grid_index(bulk)
        assert gi[1] == 0
        assert gi[2] == 1
        assert gi[3] == 2


# ---------------------------------------------------------------------------
# Step 9 tests — assemble_load_vector
# ---------------------------------------------------------------------------

class TestAssembleLoadVector:
    def test_point_force_y(self):
        """Force in Y at tip grid (GID=2)."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=1000.0, n1=0.0, n2=1.0, n3=0.0)]

        f_vec = assemble_load_vector(bulk, load_sid=10)
        assert f_vec.shape == (12,)
        # grid_index: 1->0, 2->1; Ty of grid 2 is dof 6*1+1 = 7
        assert f_vec[7] == pytest.approx(1000.0)
        # All others should be zero
        for i in range(12):
            if i != 7:
                assert f_vec[i] == pytest.approx(0.0, abs=1e-30), f"f_vec[{i}] = {f_vec[i]}"

    def test_load_combination(self):
        """LOAD card with s=1, component (2.0, sid=10), Force SID 10 f=500, n1=1."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=500.0, n1=1.0, n2=0.0, n3=0.0)]
        bulk.loads[20] = Load(sid=20, s=1.0, components=[(2.0, 10)])

        f_vec = assemble_load_vector(bulk, load_sid=20)
        # Tx at grid 2 (dof index 6): 1*2*500*1 = 1000
        assert f_vec[6] == pytest.approx(1000.0)

    def test_moment_load(self):
        """Moment about Z at grid 2."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bulk.moments[5] = [Moment(sid=5, gid=2, cid=0, m=200.0, n1=0.0, n2=0.0, n3=1.0)]

        f_vec = assemble_load_vector(bulk, load_sid=5)
        # Rz at grid 2: dof 6*1+5 = 11
        assert f_vec[11] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Step 9 tests — get_spc_dofs
# ---------------------------------------------------------------------------

class TestGetSpcDofs:
    def test_spc1_all_dofs(self):
        """SPC1 DOFs 123456 at grid 1 (index 0)."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]

        grid_index = {1: 0, 2: 1}
        spc_dofs = get_spc_dofs(bulk, spc_sid=1, grid_index=grid_index)
        assert set(spc_dofs) == {0, 1, 2, 3, 4, 5}

    def test_spc_single_dof(self):
        """SPC with DOF string '2' at grid 1 → only DOF 1."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.spcs[1] = [Spc(sid=1, g1=1, c1="2")]

        grid_index = {1: 0}
        spc_dofs = get_spc_dofs(bulk, spc_sid=1, grid_index=grid_index)
        assert 1 in spc_dofs  # DOF 2 → index 1

    def test_permanent_spc_in_grid(self):
        """Grid.ps='123456' always contributes regardless of SID."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0, ps="123456")
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)

        grid_index = {1: 0, 2: 1}
        # Even with spc_sid=99 (no SPC cards), ps still contributes
        spc_dofs = get_spc_dofs(bulk, spc_sid=99, grid_index=grid_index)
        assert set(spc_dofs) == {0, 1, 2, 3, 4, 5}


# ---------------------------------------------------------------------------
# Step 9 tests — apply_spcs
# ---------------------------------------------------------------------------

class TestApplySpcs:
    def test_partitioning(self):
        """12x12 K, spc_dofs=[0..5] → K_free 6x6, f_free len 6."""
        K = np.eye(12)
        f = np.arange(12, dtype=float)
        spc_dofs = [0, 1, 2, 3, 4, 5]
        K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
        assert K_free.shape == (6, 6)
        assert len(f_free) == 6
        assert free_dofs == [6, 7, 8, 9, 10, 11]

    def test_cantilever_kfree_positive_definite(self):
        """Cantilever (fully fixed at GA) → K_free should be positive definite."""
        bulk = make_cantilever_bulk()
        K = assemble_global_stiffness(bulk)
        grid_index = build_grid_index(bulk)
        spc_dofs = get_spc_dofs(bulk, spc_sid=1, grid_index=grid_index)
        K_free, f_free, free_dofs = apply_spcs(K, np.zeros(12), spc_dofs)

        eigenvalues = np.linalg.eigvalsh(K_free)
        assert np.all(eigenvalues > 0), \
            f"K_free not positive definite. Min eigenvalue: {eigenvalues.min()}"
