"""Tests for Step 15: SOL 103 eigenvalue solver."""

import numpy as np
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Eigrl
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs, apply_spcs
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol103 import solve_modes, run_sol103


# ---- Model parameters -------------------------------------------------------

E = 2.0e11
G = 7.692e10
rho = 7850.0
A = 0.05
I = 8.333e-4   # I1 = I2 = I
J = 1.406e-3
N_ELEM = 10
L_TOTAL = 1.0
le = L_TOTAL / N_ELEM   # element length

# Analytical frequencies
_sqrt_EI_rhoA = np.sqrt(E * I / (rho * A))
F1_CANTILEVER = (1.87510 ** 2) / (2 * np.pi) * _sqrt_EI_rhoA / L_TOTAL ** 2
F1_SS = (np.pi ** 2) / (2 * np.pi * L_TOTAL ** 2) * _sqrt_EI_rhoA


# ---- Helpers ----------------------------------------------------------------

def _make_bulk(n_elem=N_ELEM, le=le):
    """Create a straight beam BulkData with n_elem CBAR elements along x-axis."""
    bulk = BulkData()
    for i in range(n_elem + 1):
        gid = i + 1
        bulk.grids[gid] = Grid(gid=gid, x=i * le, y=0.0, z=0.0)
    bulk.pbars[10] = Pbar(pid=10, mid=100, A=A, I1=I, I2=I, J=J)
    bulk.mat1s[100] = Mat1(mid=100, E=E, G=G, nu=0.3, rho=rho)
    for eid in range(1, n_elem + 1):
        bulk.cbars[eid] = Cbar(eid=eid, pid=10, ga=eid, gb=eid + 1,
                               x1=0.0, x2=1.0, x3=0.0)
    return bulk


def _cantilever_cc(eigrl_sid=20, spc_sid=10):
    bulk = _make_bulk()
    bulk.eigrls[eigrl_sid] = Eigrl(sid=eigrl_sid, nd=4, norm="MASS")
    bulk.spc1s[spc_sid] = [
        _make_spc1(spc_sid, "123456", [1])
    ]
    cc = CaseControl(
        sol=103,
        subcases=[SubcaseControl(subcase_id=1, spc_sid=spc_sid, method_sid=eigrl_sid)],
    )
    return bulk, cc


def _make_spc1(sid, dofs, grids):
    from sbeam.model.constraint import Spc1
    return Spc1(sid=sid, c=dofs, grids=grids)


# ---- Step 15 acceptance tests -----------------------------------------------

class TestCantileverFrequency:
    def test_first_mode_within_1pct(self):
        bulk, cc = _cantilever_cc()
        result = run_sol103(bulk, cc.subcases[0])
        assert result.frequencies_hz[0] == pytest.approx(F1_CANTILEVER, rel=0.01)

    def test_mode_shapes_shape(self):
        bulk, cc = _cantilever_cc()
        result = run_sol103(bulk, cc.subcases[0])
        n_dofs = 6 * (N_ELEM + 1)
        n_modes = len(result.frequencies_hz)
        assert result.mode_shapes.shape == (n_dofs, n_modes)

    def test_eigenvalues_positive(self):
        bulk, cc = _cantilever_cc()
        result = run_sol103(bulk, cc.subcases[0])
        assert np.all(result.eigenvalues >= -1e-6)

    def test_mass_normalisation(self):
        """phi^T M_free phi == I within tolerance (MASS norm from eigh)."""
        bulk, cc = _cantilever_cc()
        grid_index = build_grid_index(bulk)
        n_dofs = 6 * len(grid_index)
        K = assemble_global_stiffness(bulk)
        M = assemble_global_mass(bulk)
        spc_dofs = get_spc_dofs(bulk, 10, grid_index)
        K_free, _, free_dofs = apply_spcs(K, np.zeros(n_dofs), spc_dofs)
        M_free = M[np.ix_(free_dofs, free_dofs)]

        eigrl = bulk.eigrls[20]
        _, phi_free = solve_modes(K_free, M_free, eigrl)

        # phi^T M phi should be identity
        MPhi = M_free @ phi_free
        identity_check = phi_free.T @ MPhi
        assert np.allclose(identity_check, np.eye(phi_free.shape[1]), atol=1e-8)


class TestFreeFreeBeam:
    def test_first_six_rigid_body_modes(self):
        """Free-free beam: first 6 modes << first elastic mode (numerical rigid body)."""
        bulk = _make_bulk()
        bulk.eigrls[20] = Eigrl(sid=20, nd=10, norm="MASS")
        cc = CaseControl(
            sol=103,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=None, method_sid=20)],
        )
        result = run_sol103(bulk, cc.subcases[0])
        # Rigid body modes should be < 0.1 Hz; elastic first mode is >1000 Hz for free-free
        assert np.all(result.frequencies_hz[:6] < 0.1)

    def test_seventh_mode_is_elastic(self):
        """First elastic mode (7th) must be > 1 Hz."""
        bulk = _make_bulk()
        bulk.eigrls[20] = Eigrl(sid=20, nd=10, norm="MASS")
        cc = CaseControl(
            sol=103,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=None, method_sid=20)],
        )
        result = run_sol103(bulk, cc.subcases[0])
        assert result.frequencies_hz[6] > 1.0


class TestSimplySupportedFrequency:
    def test_first_mode_within_1pct(self):
        """Simply supported beam f1 = pi/(2L²) * sqrt(EI/rhoA) ± 1%."""
        bulk = _make_bulk()
        bulk.eigrls[20] = Eigrl(sid=20, nd=4, norm="MASS")
        # Left: fix Tx, Ty, Tz, Rx (DOFs 1234)
        # Right: fix Ty, Tz, Rx (DOFs 234)
        bulk.spc1s[10] = [
            _make_spc1(10, "1234", [1]),
            _make_spc1(10, "234", [N_ELEM + 1]),
        ]
        cc = CaseControl(
            sol=103,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, method_sid=20)],
        )
        result = run_sol103(bulk, cc.subcases[0])
        assert result.frequencies_hz[0] == pytest.approx(F1_SS, rel=0.01)


class TestMaxNormalisation:
    def test_max_component_equals_one(self):
        """MAX normalisation: each mode's maximum absolute component = 1.0."""
        bulk = _make_bulk()
        bulk.eigrls[20] = Eigrl(sid=20, nd=4, norm="MAX")
        bulk.spc1s[10] = [_make_spc1(10, "123456", [1])]
        cc = CaseControl(
            sol=103,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, method_sid=20)],
        )
        result = run_sol103(bulk, cc.subcases[0])
        for mode in range(result.mode_shapes.shape[1]):
            phi = result.mode_shapes[:, mode]
            # max over free DOFs
            max_abs = np.max(np.abs(phi))
            assert max_abs == pytest.approx(1.0, abs=1e-10)
