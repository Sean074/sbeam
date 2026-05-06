"""Assembly and solver tests for CBUSH spring elements (Step 37)."""

import numpy as np
import pytest

from sbeam.model.element import Cbush
from sbeam.model.property import Pbush
from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.assembly.stiffness import (
    cbush_local_stiffness,
    cbush_transform_matrix,
    cbush_stiffness_global,
)
from sbeam.parser.bdf_reader import parse_bulk_data


def _make_simple_bulk(k1=0.0, k2=0.0, k3=0.0, k4=0.0, k5=0.0, k6=0.0, grounded=False):
    """Two-grid model with a single CBUSH along global X."""
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
    bulk.pbushs[10] = Pbush(pid=10, k1=k1, k2=k2, k3=k3, k4=k4, k5=k5, k6=k6)
    gb = None if grounded else 2
    bulk.cbushs[1] = Cbush(eid=1, pid=10, ga=1, gb=gb, x1=0.0, x2=1.0, x3=0.0)
    return bulk


class TestCbushLocalStiffness:
    def test_diagonal_values(self):
        pbush = Pbush(pid=1, k1=1.0, k2=2.0, k3=3.0, k4=4.0, k5=5.0, k6=6.0)
        K = cbush_local_stiffness(pbush)
        assert K.shape == (6, 6)
        np.testing.assert_allclose(np.diag(K), [1, 2, 3, 4, 5, 6])
        # Off-diagonal must be zero
        np.testing.assert_allclose(K - np.diag(np.diag(K)), 0.0)

    def test_zeros_for_unset_dofs(self):
        pbush = Pbush(pid=1, k1=500.0)
        K = cbush_local_stiffness(pbush)
        assert K[0, 0] == pytest.approx(500.0)
        assert K[1, 1] == pytest.approx(0.0)
        assert K[5, 5] == pytest.approx(0.0)


class TestCbushTransformMatrix:
    def test_aligned_with_global_x(self):
        cbush = Cbush(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
        grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=1.0, y=0.0, z=0.0),
        }
        R = cbush_transform_matrix(cbush, grids)
        # Local x should be global X
        np.testing.assert_allclose(R[0], [1.0, 0.0, 0.0], atol=1e-12)
        # R must be orthonormal
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)

    def test_coincident_nodes_raises(self):
        cbush = Cbush(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
        grids = {
            1: Grid(gid=1, x=0.5, y=0.5, z=0.5),
            2: Grid(gid=2, x=0.5, y=0.5, z=0.5),
        }
        with pytest.raises(ValueError, match="coincident"):
            cbush_transform_matrix(cbush, grids)

    def test_default_orientation_when_vector_zero(self):
        # No orientation vector provided; should default without error
        cbush = Cbush(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=0.0)
        grids = {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=1.0, y=0.0, z=0.0),
        }
        R = cbush_transform_matrix(cbush, grids)
        assert R.shape == (3, 3)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)


class TestCbushStiffnessGlobal:
    def test_two_node_symmetric(self):
        bulk = _make_simple_bulk(k1=1000.0, k2=500.0)
        cbush = bulk.cbushs[1]
        K = cbush_stiffness_global(cbush, bulk.grids, bulk.pbushs)
        assert K.shape == (12, 12)
        np.testing.assert_allclose(K, K.T, atol=1e-10)

    def test_grounded_returns_6x6(self):
        bulk = _make_simple_bulk(k1=1000.0, grounded=True)
        cbush = bulk.cbushs[1]
        K = cbush_stiffness_global(cbush, bulk.grids, bulk.pbushs)
        assert K.shape == (6, 6)
        np.testing.assert_allclose(K, K.T, atol=1e-10)

    def test_45deg_symmetric(self):
        """CBUSH at 45° in XY plane: global K must be symmetric."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=1.0, z=0.0)
        bulk.pbushs[10] = Pbush(pid=10, k1=1000.0)
        bulk.cbushs[1] = Cbush(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        K = cbush_stiffness_global(bulk.cbushs[1], bulk.grids, bulk.pbushs)
        np.testing.assert_allclose(K, K.T, atol=1e-10)

    def test_45deg_hand_computed(self):
        """For K1-only spring at 45° in XY: K_global[0,0] = K_global[1,1] = K1/2."""
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=1.0, z=0.0)
        bulk.pbushs[10] = Pbush(pid=10, k1=1000.0)
        bulk.cbushs[1] = Cbush(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=0.0, x3=1.0)
        K = cbush_stiffness_global(bulk.cbushs[1], bulk.grids, bulk.pbushs)
        assert K[0, 0] == pytest.approx(500.0, rel=1e-10)
        assert K[1, 1] == pytest.approx(500.0, rel=1e-10)
        assert K[0, 1] == pytest.approx(500.0, rel=1e-10)


class TestCbushAxialSolver:
    """Test case 1: K1-only CBUSH, SPC at GA, unit force at GB → u = F/K1.

    Zero-stiffness DOFs at GB are constrained so the model is non-singular.
    """

    def _run(self, K1, F):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, {K1}".format(K1=K1),
            "CBUSH, 1, 10, 1, 2",
            "SPC1, 1, 123456, 1",   # full fix at GA
            "SPC1, 1, 23456, 2",    # fix all non-Tx DOFs at GB (zero stiffness DOFs)
            "FORCE, 2, 2, 0, {F}, 1.0, 0.0, 0.0".format(F=F),
        ]
        bulk = parse_bulk_data(lines)

        from sbeam.parser.case_control import CaseControl, SubcaseControl
        sc = SubcaseControl(subcase_id=1, load_sid=2, spc_sid=1)
        cc = CaseControl(sol=101, subcases=[sc])

        from sbeam.solver.sol101 import run_sol101
        result = run_sol101(bulk, cc.subcases[0])
        return result

    def test_axial_displacement(self):
        K1, F = 5000.0, 100.0
        bulk = parse_bulk_data([
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, {K1}".format(K1=K1),
            "CBUSH, 1, 10, 1, 2",
            "SPC1, 1, 123456, 1",
            "SPC1, 1, 23456, 2",
            "FORCE, 2, 2, 0, {F}, 1.0, 0.0, 0.0".format(F=F),
        ])
        from sbeam.parser.case_control import CaseControl, SubcaseControl
        from sbeam.solver.sol101 import run_sol101
        from sbeam.assembly.load_vector import build_grid_index
        sc = SubcaseControl(subcase_id=1, load_sid=2, spc_sid=1)
        cc = CaseControl(sol=101, subcases=[sc])
        result = run_sol101(bulk, cc.subcases[0])
        gi = build_grid_index(bulk)
        tx2 = result.displacements[6 * gi[2]]
        assert tx2 == pytest.approx(F / K1, rel=1e-4)

    def test_cbush_force_recovered(self):
        K1, F = 5000.0, 100.0
        result = self._run(K1, F)
        assert 1 in result.cbush_forces
        f = result.cbush_forces[1]
        assert abs(f[0]) == pytest.approx(F, rel=1e-4)


class TestCbushTorsionalSolver:
    """Test case 2: K4-only CBUSH, torque at GB → rotation = M/K4.

    Zero-stiffness DOFs at GB are constrained so the model is non-singular.
    """

    def test_torsional_rotation(self):
        K4, M = 2000.0, 50.0
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "PBUSH, 10, K, 0.0, 0.0, 0.0, {K4}".format(K4=K4),
            "CBUSH, 1, 10, 1, 2",
            "SPC1, 1, 123456, 1",   # full fix at GA
            "SPC1, 1, 12356, 2",    # fix all non-Rx (DOF4) DOFs at GB (zero stiffness DOFs)
            "MOMENT, 2, 2, 0, {M}, 1.0, 0.0, 0.0".format(M=M),
        ]
        bulk = parse_bulk_data(lines)

        from sbeam.parser.case_control import CaseControl, SubcaseControl
        sc = SubcaseControl(subcase_id=1, load_sid=2, spc_sid=1)
        cc = CaseControl(sol=101, subcases=[sc])

        from sbeam.solver.sol101 import run_sol101
        from sbeam.assembly.load_vector import build_grid_index
        result = run_sol101(bulk, cc.subcases[0])
        gi = build_grid_index(bulk)
        i2 = gi[2]
        rx2 = result.displacements[6 * i2 + 3]
        expected = M / K4
        assert rx2 == pytest.approx(expected, rel=1e-4)


class TestCbushGroundedSolver:
    """Test case 3: Grounded CBUSH at GA."""

    def test_grounded_axial_stiffness(self):
        K1, F = 3000.0, 90.0
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "PBUSH, 10, K, {K1}".format(K1=K1),
            "CBUSH, 1, 10, 1,  ,  ,  ,  ,  ,  ",
            "SPC1, 1, 23456, 1",
            "FORCE, 2, 1, 0, {F}, 1.0, 0.0, 0.0".format(F=F),
        ]
        bulk = parse_bulk_data(lines)

        from sbeam.parser.case_control import CaseControl, SubcaseControl
        sc = SubcaseControl(subcase_id=1, load_sid=2, spc_sid=1)
        cc = CaseControl(sol=101, subcases=[sc])

        from sbeam.solver.sol101 import run_sol101
        from sbeam.assembly.load_vector import build_grid_index
        result = run_sol101(bulk, cc.subcases[0])
        gi = build_grid_index(bulk)
        i1 = gi[1]
        tx1 = result.displacements[6 * i1]
        assert tx1 == pytest.approx(F / K1, rel=1e-4)


class TestCbushMixed:
    """Test case 5: CBAR cantilever + mid-span CBUSH support."""

    def test_cbar_plus_cbush_tip_deflection(self):
        """
        Model: 2-element cantilever (nodes 1-2-3 along X, L=1 each) with
        a CBUSH (K2=K_spring) supporting node 2 in Y.
        Tip force P in Y at node 3.
        Analytical: for a simply-supported-by-spring structure, checked numerically.
        The main check is that the CBUSH stiffness reduces the tip deflection compared
        to a free cantilever.
        """
        E, I = 2e5, 1.0
        A, G, J = 1.0, 1e5, 1.0
        L = 1.0
        P = 100.0
        K_spring = 1e6  # stiff spring at mid-span

        lines = [
            # Grids
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "GRID, 3, 0, 2.0, 0.0, 0.0",
            # Material and property
            "MAT1, 1, {E}, {G}, 0.3, 0.0".format(E=E, G=G),
            "PBAR, 1, 1, {A}, {I}, {I}, {J}".format(A=A, I=I, J=J),
            # Two CBAR elements
            "CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0",
            "CBAR, 2, 1, 2, 3, 0.0, 1.0, 0.0",
            # CBUSH spring at mid-node (node 2) in Y direction
            "PBUSH, 10, K, 0.0, {Ks}".format(Ks=K_spring),
            "CBUSH, 10, 10, 2,  ,  ,  ,  ,  ,  ",
            # Fixed support at node 1
            "SPC1, 1, 123456, 1",
            # Constrain the CBUSH grounded node (Ty only constrained by spring, other DOFs free)
            # Tip load
            "FORCE, 2, 3, 0, {P}, 0.0, 1.0, 0.0".format(P=P),
        ]
        bulk = parse_bulk_data(lines)

        from sbeam.parser.case_control import CaseControl, SubcaseControl
        sc = SubcaseControl(subcase_id=1, load_sid=2, spc_sid=1)
        cc = CaseControl(sol=101, subcases=[sc])

        from sbeam.solver.sol101 import run_sol101
        from sbeam.assembly.load_vector import build_grid_index
        result = run_sol101(bulk, cc.subcases[0])
        gi = build_grid_index(bulk)

        # Free cantilever tip deflection: PL^3/3EI with L=2
        delta_free = P * (2 * L) ** 3 / (3 * E * I)
        tip_ty = result.displacements[6 * gi[3] + 1]

        # The spring reduces deflection; tip_ty should be less than free cantilever
        assert abs(tip_ty) < abs(delta_free)
        # And positive (in load direction)
        assert tip_ty > 0.0
        # CBUSH force should be nonzero
        assert 10 in result.cbush_forces
        assert abs(result.cbush_forces[10][1]) > 0.0


class TestCbushValidation:
    def test_unknown_pid_raises_at_parse(self):
        lines = [
            "GRID, 1, 0, 0.0, 0.0, 0.0",
            "GRID, 2, 0, 1.0, 0.0, 0.0",
            "CBUSH, 1, 99, 1, 2",
        ]
        with pytest.raises(ValueError, match="PID=99"):
            parse_bulk_data(lines)
