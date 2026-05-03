"""Tests for Steps 7 & 8: element and global stiffness matrices."""

import math
import numpy as np
import pytest

from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.grid import Grid
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import (
    local_stiffness,
    element_stiffness_global,
    assemble_global_stiffness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mat1(E=2e11, G=7.7e10, rho=7850.0):
    return Mat1(mid=1, E=E, G=G, nu=0.3, rho=rho)


def make_pbar(A=0.05, I1=8.333e-4, I2=8.333e-4, J=1.406e-3):
    return Pbar(pid=10, mid=1, A=A, I1=I1, I2=I2, J=J)


# ---------------------------------------------------------------------------
# Step 7 tests — local_stiffness
# ---------------------------------------------------------------------------

class TestLocalStiffnessAxial:
    """Test axial-only stiffness terms."""

    def test_axial_diagonal(self):
        pbar = Pbar(pid=10, mid=1, A=0.01, I1=0.0, I2=0.0, J=0.0)
        mat1 = make_mat1()
        L = 1.0
        K = local_stiffness(pbar, mat1, L)
        ea_l = mat1.E * pbar.A / L  # 2e9
        assert K[0, 0] == pytest.approx(ea_l, rel=1e-10)
        assert K[6, 6] == pytest.approx(ea_l, rel=1e-10)

    def test_axial_off_diagonal(self):
        pbar = Pbar(pid=10, mid=1, A=0.01, I1=0.0, I2=0.0, J=0.0)
        mat1 = make_mat1()
        L = 1.0
        K = local_stiffness(pbar, mat1, L)
        ea_l = mat1.E * pbar.A / L
        assert K[0, 6] == pytest.approx(-ea_l, rel=1e-10)
        assert K[6, 0] == pytest.approx(-ea_l, rel=1e-10)

    def test_non_axial_dofs_zero(self):
        """When I1=I2=J=0, all non-axial terms should be zero."""
        pbar = Pbar(pid=10, mid=1, A=0.01, I1=0.0, I2=0.0, J=0.0)
        mat1 = make_mat1()
        L = 1.0
        K = local_stiffness(pbar, mat1, L)
        axial_dofs = {0, 6}
        for r in range(12):
            for c in range(12):
                if r not in axial_dofs or c not in axial_dofs:
                    if not (r in axial_dofs and c in axial_dofs):
                        assert K[r, c] == pytest.approx(0.0, abs=1e-30), f"K[{r},{c}] should be zero but is {K[r,c]}"


class TestLocalStiffnessBending:
    """Test bending sub-matrix (xy-plane, I1)."""

    def test_bending_xy_submatrix(self):
        E = 2e11
        I1 = 1e-4
        L = 1.0
        pbar = Pbar(pid=10, mid=1, A=0.0, I1=I1, I2=0.0, J=0.0)
        mat1 = make_mat1(E=E)
        K = local_stiffness(pbar, mat1, L)
        ei = E * I1
        # Expected 4x4 sub-matrix at [1,5,7,11]
        K_expect = ei * np.array([
            [12,    6,   -12,    6],
            [6,     4,    -6,    2],
            [-12,  -6,    12,   -6],
            [6,     2,    -6,    4],
        ])  # L=1 so L^n = 1
        idx = [1, 5, 7, 11]
        for ii, ri in enumerate(idx):
            for jj, ci in enumerate(idx):
                assert K[ri, ci] == pytest.approx(K_expect[ii, jj], rel=1e-8), \
                    f"K[{ri},{ci}] mismatch: got {K[ri,ci]}, expected {K_expect[ii,jj]}"


class TestLocalStiffnessSymmetry:
    """Full PBAR: stiffness matrix must be symmetric."""

    def test_symmetry(self):
        pbar = make_pbar()
        mat1 = make_mat1()
        L = 1.5
        K = local_stiffness(pbar, mat1, L)
        assert K == pytest.approx(K.T, abs=1e-10)

    def test_symmetry_various_L(self):
        pbar = make_pbar()
        mat1 = make_mat1()
        for L in [0.1, 1.0, 5.0]:
            K = local_stiffness(pbar, mat1, L)
            assert K == pytest.approx(K.T, abs=1e-8), f"Not symmetric at L={L}"


# ---------------------------------------------------------------------------
# Step 7 tests — transform_matrix and element_stiffness_global
# ---------------------------------------------------------------------------

class TestTransformMatrixIdentity:
    """Element along X-axis with Y orientation → T should be identity-like."""

    def test_k_global_equals_k_local_for_x_axis_element(self):
        """Element from (0,0,0) to (1,0,0) with orientation (0,1,0) in global y."""
        grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=1.0, y=0.0, z=0.0),
        }
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
        pbar = make_pbar()
        mat1 = make_mat1()

        K_local = local_stiffness(pbar, mat1, L=1.0)
        K_global = element_stiffness_global(cbar, grids, {10: pbar}, {1: mat1})

        assert K_global == pytest.approx(K_local, abs=1e-10)


class TestTransformMatrix45Degrees:
    """Element at 45° in xy-plane."""

    def test_k_global_symmetric(self):
        s = 1.0 / math.sqrt(2)
        grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=s,   y=s,   z=0.0),
        }
        # Orientation vector in global z (perpendicular to element in the xz plane rotated to y)
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        pbar = make_pbar()
        mat1 = make_mat1()

        K_global = element_stiffness_global(cbar, grids, {10: pbar}, {1: mat1})

        # Must be symmetric
        assert K_global == pytest.approx(K_global.T, abs=1e-8)

    def test_k_global_psd(self):
        s = 1.0 / math.sqrt(2)
        grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=s,   y=s,   z=0.0),
        }
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        pbar = make_pbar()
        mat1 = make_mat1()

        K_global = element_stiffness_global(cbar, grids, {10: pbar}, {1: mat1})
        eigenvalues = np.linalg.eigvalsh(K_global)
        # Unconstrained element has 6 rigid body modes (near-zero eigenvalues);
        # allow small numerical noise from floating point (relative to structural eigenvalues ~1e8)
        assert np.all(eigenvalues >= -1e-4), \
            f"Negative eigenvalue found: {eigenvalues.min()}"


# ---------------------------------------------------------------------------
# Step 8 tests — assemble_global_stiffness
# ---------------------------------------------------------------------------

def _make_one_element_bulk(L=1.0):
    """One element along X, grids at 0 and L."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = make_mat1()
    bulk.pbars[10] = make_pbar()
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    return bulk


def _make_two_element_bulk(L=1.0):
    """Two elements along X: grids at 0, L, 2L."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0,  y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,    y=0.0, z=0.0)
    bulk.grids[3] = Grid(gid=3, x=2*L,  y=0.0, z=0.0)
    bulk.mat1s[1] = make_mat1()
    bulk.pbars[10] = make_pbar()
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.cbars[2] = Cbar(eid=2, pid=10, ga=2, gb=3, x1=0.0, x2=1.0, x3=0.0)
    return bulk


class TestGlobalStiffnessShape:
    def test_one_element_12x12(self):
        bulk = _make_one_element_bulk()
        K = assemble_global_stiffness(bulk)
        assert K.shape == (12, 12)

    def test_two_elements_18x18(self):
        bulk = _make_two_element_bulk()
        K = assemble_global_stiffness(bulk)
        assert K.shape == (18, 18)


class TestGlobalStiffnessProperties:
    def test_symmetric(self):
        bulk = _make_one_element_bulk()
        K = assemble_global_stiffness(bulk)
        assert K == pytest.approx(K.T, abs=1e-8)

    def test_psd(self):
        bulk = _make_one_element_bulk()
        K = assemble_global_stiffness(bulk)
        eigenvalues = np.linalg.eigvalsh(K)
        # Unconstrained element: 6 rigid body modes near zero; allow small floating-point noise
        assert np.all(eigenvalues >= -1e-6), \
            f"Negative eigenvalue: {eigenvalues.min()}"


class TestGlobalStiffnessDOFPlacement:
    def test_axial_coupling_between_grids(self):
        """For element along X, K[0,6] = K[6,0] = -EA/L."""
        E = 2e11
        A = 0.05
        L = 1.0
        bulk = _make_one_element_bulk(L=L)
        bulk.mat1s[1] = Mat1(mid=1, E=E, G=7.7e10, nu=0.3, rho=7850)
        bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=8.333e-4, I2=8.333e-4, J=1.406e-3)

        K = assemble_global_stiffness(bulk)
        ea_l = -E * A / L
        assert K[0, 6] == pytest.approx(ea_l, rel=1e-8)
        assert K[6, 0] == pytest.approx(ea_l, rel=1e-8)
