"""Tests for Step 14: consistent mass matrix."""

import numpy as np
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.mass_matrix import local_mass, element_mass_global, assemble_global_mass


# ---- shared fixtures --------------------------------------------------------

E = 2.0e11
G = 7.692e10
rho = 7850.0
A = 0.05
I1 = 8.333e-4
I2 = 8.333e-4
J = 1.406e-3
L = 1.0

_pbar = Pbar(pid=10, mid=100, A=A, I1=I1, I2=I2, J=J)
_mat1 = Mat1(mid=100, E=E, G=G, nu=0.3, rho=rho)
_grids = {
    1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
    2: Grid(gid=2, x=L, y=0.0, z=0.0),
}
_cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)


def _one_element_bulk():
    bulk = BulkData()
    bulk.grids = dict(_grids)
    bulk.cbars = {1: _cbar}
    bulk.pbars = {10: _pbar}
    bulk.mat1s = {100: _mat1}
    return bulk


# ---- local_mass tests -------------------------------------------------------

class TestLocalMassAxialTotal:
    def test_axial_rigid_body_total_mass(self):
        """For rigid body x-translation (u1=u2=1): sum = rho*A*L."""
        M = local_mass(_pbar, _mat1, L)
        total = M[0, 0] + 2 * M[0, 6] + M[6, 6]
        expected = rho * A * L
        assert total == pytest.approx(expected, rel=1e-10)

    def test_bending_y_rigid_body_total_mass(self):
        """For rigid body y-translation (v1=v2=1): sum = rho*A*L."""
        M = local_mass(_pbar, _mat1, L)
        # M[1,1]*1 + M[1,7]*1 + M[7,1]*1 + M[7,7]*1
        total = M[1, 1] + M[1, 7] + M[7, 1] + M[7, 7]
        assert total == pytest.approx(rho * A * L, rel=1e-10)

    def test_symmetry(self):
        M = local_mass(_pbar, _mat1, L)
        assert np.allclose(M, M.T, atol=1e-12)

    def test_psd(self):
        M = local_mass(_pbar, _mat1, L)
        eigvals = np.linalg.eigvalsh(M)
        assert np.all(eigvals >= -1e-10)

    def test_zero_torsion_if_no_polar_inertia(self):
        pbar_no_inertia = Pbar(pid=10, mid=100, A=A, I1=0.0, I2=0.0, J=J)
        M = local_mass(pbar_no_inertia, _mat1, L)
        # Torsion DOFs should have zero mass
        assert M[3, 3] == 0.0
        assert M[9, 9] == 0.0
        assert M[3, 9] == 0.0


# ---- element_mass_global tests ----------------------------------------------

class TestElementMassGlobal:
    def test_symmetry(self):
        M_g = element_mass_global(_cbar, _grids, {10: _pbar}, {100: _mat1})
        assert np.allclose(M_g, M_g.T, atol=1e-12)

    def test_transform_preserves_trace(self):
        """Orthogonal transformation preserves trace (total kinetic energy)."""
        M_local = local_mass(_pbar, _mat1, L)
        M_global = element_mass_global(_cbar, _grids, {10: _pbar}, {100: _mat1})
        assert np.trace(M_global) == pytest.approx(np.trace(M_local), rel=1e-10)

    def test_transform_preserves_eigenvalues(self):
        """Orthogonal transformation preserves eigenvalue spectrum."""
        M_local = local_mass(_pbar, _mat1, L)
        M_global = element_mass_global(_cbar, _grids, {10: _pbar}, {100: _mat1})
        eig_local = np.sort(np.linalg.eigvalsh(M_local))
        eig_global = np.sort(np.linalg.eigvalsh(M_global))
        assert np.allclose(eig_local, eig_global, rtol=1e-8)


# ---- assemble_global_mass tests ---------------------------------------------

class TestAssembleGlobalMass:
    def test_shape(self):
        bulk = _one_element_bulk()
        M = assemble_global_mass(bulk)
        assert M.shape == (12, 12)

    def test_symmetry(self):
        bulk = _one_element_bulk()
        M = assemble_global_mass(bulk)
        assert np.allclose(M, M.T, atol=1e-12)

    def test_psd(self):
        bulk = _one_element_bulk()
        M = assemble_global_mass(bulk)
        eigvals = np.linalg.eigvalsh(M)
        assert np.all(eigvals >= -1e-10)

    def test_positive_definite_two_elements(self):
        """2-element model with non-zero density: M is PD (all eigvals > 0)."""
        bulk = BulkData()
        bulk.grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=0.5, y=0.0, z=0.0),
            3: Grid(gid=3, x=1.0, y=0.0, z=0.0),
        }
        bulk.cbars = {
            1: Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0),
            2: Cbar(eid=2, pid=10, ga=2, gb=3, x1=0.0, x2=1.0, x3=0.0),
        }
        bulk.pbars = {10: _pbar}
        bulk.mat1s = {100: _mat1}
        M = assemble_global_mass(bulk)
        eigvals = np.linalg.eigvalsh(M)
        assert np.all(eigvals > -1e-10)

    def test_conm2_added_to_correct_dofs(self):
        """Zero-offset CONM2 adds mass to translational DOF diagonals only."""
        bulk_no = _one_element_bulk()
        M_no = assemble_global_mass(bulk_no)

        bulk_with = _one_element_bulk()
        bulk_with.conm2s = {1: Conm2(eid=99, gid=2, cid=0, m=10.0)}
        M_with = assemble_global_mass(bulk_with)

        # Grid 2 is index 1 (sorted: GID 1→index0, GID 2→index1)
        tip_idx = 1
        for d in range(3):  # Tx, Ty, Tz
            diff = M_with[6 * tip_idx + d, 6 * tip_idx + d] - M_no[6 * tip_idx + d, 6 * tip_idx + d]
            assert diff == pytest.approx(10.0, rel=1e-10)

        # Rotational DOFs unchanged when offset is zero
        for d in range(3, 6):
            diff = M_with[6 * tip_idx + d, 6 * tip_idx + d] - M_no[6 * tip_idx + d, 6 * tip_idx + d]
            assert diff == pytest.approx(0.0, abs=1e-12)

    def test_conm2_offset_z_coupling_terms(self):
        """CONM2 with z-offset produces translation-rotation coupling in mass matrix."""
        bulk = BulkData()
        bulk.grids = {1: Grid(gid=1, x=0.0, y=0.0, z=0.0)}
        m, d = 5.0, 2.0  # mass = 5, offset z = 2
        bulk.conm2s = {1: Conm2(eid=1, gid=1, cid=0, m=m, x3=d)}
        M = assemble_global_mass(bulk)

        # Translational diagonal: m on Tx, Ty, Tz
        for k in range(3):
            assert M[k, k] == pytest.approx(m)

        # Coupling: Tx-Ry = -m*tilde(r)[0,1] → tilde([0,0,d])[0,1] = -d → M[0,4] = m*d
        # More precisely: M_tr = -m*tilde(r), tilde([0,0,d]) = [[0,-d,0],[d,0,0],[0,0,0]]
        # M_tr = -m*[[0,-d,0],[d,0,0],[0,0,0]] = [[0,m*d,0],[-m*d,0,0],[0,0,0]]
        assert M[0, 4] == pytest.approx(m * d)   # Tx-Ry
        assert M[1, 3] == pytest.approx(-m * d)  # Ty-Rx
        assert M[4, 0] == pytest.approx(m * d)   # Ry-Tx  (symmetric)
        assert M[3, 1] == pytest.approx(-m * d)  # Rx-Ty  (symmetric)

        # Parallel-axis rotational: Rx = m*d^2, Ry = m*d^2, Rz = 0
        assert M[3, 3] == pytest.approx(m * d**2)  # Rx
        assert M[4, 4] == pytest.approx(m * d**2)  # Ry
        assert M[5, 5] == pytest.approx(0.0, abs=1e-12)  # Rz (no z² term)

        # Matrix is symmetric
        assert np.allclose(M, M.T, atol=1e-14)

    def test_conm2_inertia_tensor(self):
        """CONM2 with zero offset but non-zero I33 adds only to Rz DOF diagonal."""
        bulk = BulkData()
        bulk.grids = {1: Grid(gid=1, x=0.0, y=0.0, z=0.0)}
        I33_val = 7.5
        bulk.conm2s = {1: Conm2(eid=1, gid=1, cid=0, m=1.0, i33=I33_val)}
        M = assemble_global_mass(bulk)

        assert M[5, 5] == pytest.approx(I33_val)   # Rz gets I33
        assert M[3, 3] == pytest.approx(0.0, abs=1e-14)  # Rx unchanged
        assert M[4, 4] == pytest.approx(0.0, abs=1e-14)  # Ry unchanged
        assert np.allclose(M, M.T, atol=1e-14)
