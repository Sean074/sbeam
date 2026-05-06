"""Tests for Step 23: CBAR pin releases (PA/PB)."""

import numpy as np
import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import (
    local_stiffness,
    apply_pin_releases,
    element_stiffness_global,
)
from sbeam.solver.sol101 import run_sol101
from sbeam.parser.case_control import CaseControl, SubcaseControl


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

E = 2.0e11
G = 7.692e10
A = 0.05
I = 8.333e-4
J = 1.406e-3
L = 1.0

_pbar_full = Pbar(pid=10, mid=100, A=A, I1=I, I2=I, J=J)
_mat1 = Mat1(mid=100, E=E, G=G, nu=0.3, rho=7850.0)


# ---------------------------------------------------------------------------
# apply_pin_releases — unit tests
# ---------------------------------------------------------------------------

class TestApplyPinReleasesZeroing:
    def test_no_release_returns_identical(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "", "")
        assert np.allclose(K_rel, K)

    def test_pa_dof1_zeros_row0_col0(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "1", "")
        assert np.all(K_rel[0, :] == 0.0)
        assert np.all(K_rel[:, 0] == 0.0)
        # Other rows unchanged
        assert K_rel[6, 6] == pytest.approx(K[6, 6])

    def test_pb_dof1_zeros_row6_col6(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "", "1")
        assert np.all(K_rel[6, :] == 0.0)
        assert np.all(K_rel[:, 6] == 0.0)
        assert K_rel[0, 0] == pytest.approx(K[0, 0])

    def test_pa_56_zeros_ry_rz_at_a(self):
        """PA='56' zeroes local DOF indices 4 (Ry) and 5 (Rz) at end A."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "56", "")
        # indices 4, 5 (Ry, Rz at end A)
        assert np.all(K_rel[4, :] == 0.0)
        assert np.all(K_rel[:, 4] == 0.0)
        assert np.all(K_rel[5, :] == 0.0)
        assert np.all(K_rel[:, 5] == 0.0)

    def test_pa_pb_56_zeros_all_bending_moment_dofs(self):
        """PA=PB='56' zeroes indices 4,5 at A and 10,11 at B."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "56", "56")
        for idx in (4, 5, 10, 11):
            assert np.all(K_rel[idx, :] == 0.0), f"row {idx} not zero"
            assert np.all(K_rel[:, idx] == 0.0), f"col {idx} not zero"

    def test_pa_pb_456_zeros_all_rotational_dofs(self):
        """PA=PB='456' zeroes indices 3,4,5 at A and 9,10,11 at B."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "456", "456")
        for idx in (3, 4, 5, 9, 10, 11):
            assert np.all(K_rel[idx, :] == 0.0), f"row {idx} not zero"
            assert np.all(K_rel[:, idx] == 0.0), f"col {idx} not zero"

    def test_does_not_modify_original(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        K_copy = K.copy()
        apply_pin_releases(K, "456", "456")
        assert np.allclose(K, K_copy)


class TestPinReleasesPreserveStiffness:
    def test_pa_pb_56_preserves_axial(self):
        """PA=PB='56': axial term K[0,6] unchanged."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "56", "56")
        assert K_rel[0, 0] == pytest.approx(K[0, 0])
        assert K_rel[6, 6] == pytest.approx(K[6, 6])
        assert K_rel[0, 6] == pytest.approx(K[0, 6])

    def test_pa_pb_56_preserves_torsion(self):
        """PA=PB='56': torsion terms K[3,3], K[9,9] unchanged (DOF 4 not in '56')."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "56", "56")
        assert K_rel[3, 3] == pytest.approx(K[3, 3])
        assert K_rel[9, 9] == pytest.approx(K[9, 9])
        assert K_rel[3, 9] == pytest.approx(K[3, 9])

    def test_pa_pb_56_bending_moment_terms_zero(self):
        """PA=PB='56': all Ry/Rz coupling terms are zero."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "56", "56")
        for bending_idx in (4, 5, 10, 11):
            assert K_rel[1, bending_idx] == pytest.approx(0.0, abs=0.0)
            assert K_rel[bending_idx, 1] == pytest.approx(0.0, abs=0.0)

    def test_pa_pb_456_preserves_axial(self):
        """PA=PB='456': axial term K[0,6] unaffected (DOFs 1,2,3 not released)."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "456", "456")
        assert K_rel[0, 0] == pytest.approx(K[0, 0])
        assert K_rel[0, 6] == pytest.approx(K[0, 6])

    def test_pa_pb_456_torsion_zeroed(self):
        """PA=PB='456': torsion term K[3,9] zeroed because DOF 4 (Rx) is released."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "456", "456")
        assert K_rel[3, 3] == pytest.approx(0.0, abs=0.0)
        assert K_rel[9, 9] == pytest.approx(0.0, abs=0.0)
        assert K_rel[3, 9] == pytest.approx(0.0, abs=0.0)

    def test_pa_pb_456_transverse_shear_survives(self):
        """PA=PB='456': Ty-Ty and Tz-Tz stiffness terms survive (DOFs 2,3 not in '456')."""
        K = local_stiffness(_pbar_full, _mat1, L)
        K_rel = apply_pin_releases(K, "456", "456")
        # local Ty DOFs: indices 1, 7
        assert K_rel[1, 1] == pytest.approx(K[1, 1])
        assert K_rel[7, 7] == pytest.approx(K[7, 7])
        assert K_rel[1, 7] == pytest.approx(K[1, 7])


# ---------------------------------------------------------------------------
# element_stiffness_global — pin releases wired into the pipeline
# ---------------------------------------------------------------------------

class TestElementStiffnessGlobalPins:
    def _grids_horizontal(self, L=1.0):
        return {
            1: Grid(gid=1, x=0.0, y=0.0, z=0.0),
            2: Grid(gid=2, x=L,   y=0.0, z=0.0),
        }

    def test_no_pins_symmetric(self):
        grids = self._grids_horizontal()
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="", pb="")
        K = element_stiffness_global(cbar, grids, {10: _pbar_full}, {100: _mat1})
        assert np.allclose(K, K.T, atol=1e-10)

    def test_pa_pb_56_bending_coupling_zero(self):
        """With PA=PB='56', no rotational coupling in global K for aligned element."""
        grids = self._grids_horizontal()
        cbar_no_pin = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="", pb="")
        cbar_pinned = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="56", pb="56")
        K_full = element_stiffness_global(cbar_no_pin, grids, {10: _pbar_full}, {100: _mat1})
        K_pin  = element_stiffness_global(cbar_pinned, grids, {10: _pbar_full}, {100: _mat1})
        # Bending moment coupling (Ty-Rz = global indices 1,5 for node A)
        assert K_full[1, 5] != pytest.approx(0.0, abs=1e-8)
        assert K_pin[1, 5]  == pytest.approx(0.0, abs=1e-10)

    def test_pa_pb_456_symmetry_preserved(self):
        grids = self._grids_horizontal()
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="456", pb="456")
        K = element_stiffness_global(cbar, grids, {10: _pbar_full}, {100: _mat1})
        assert np.allclose(K, K.T, atol=1e-10)


# ---------------------------------------------------------------------------
# Truss analytical verification
# ---------------------------------------------------------------------------

class TestTrussAnalytical:
    """
    2-bar A-frame truss (2D, XY plane):
      Node 1 at (-1, 0, 0) — fully fixed support
      Node 2 at ( 1, 0, 0) — fully fixed support
      Node 3 at ( 0, 1, 0) — loaded joint, Fy = -P

    Both bars have I1=I2=J=0 (pure axial members) and PA=PB='456'.
    Length of each bar: L = sqrt(2), angle θ = 45°.

    Analytical (truss):
      Each bar force: F = P / (2 * sin(θ)) = P * sqrt(2) / 2
      Bar extension: δ_bar = F * L / EA = P * sqrt(2)/2 * sqrt(2) / EA = P / EA
      Vertical displacement: δy = δ_bar / sin(θ) = P * sqrt(2) / EA
    """

    def _make_bulk(self):
        bulk = BulkData()
        # Supports
        bulk.grids[1] = Grid(gid=1, x=-1.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x= 1.0, y=0.0, z=0.0)
        # Free joint (loaded)
        bulk.grids[3] = Grid(gid=3, x=0.0, y=1.0, z=0.0)

        # Property: pure axial member (I=0, J=0)
        bulk.pbars[10] = Pbar(pid=10, mid=100, A=A, I1=0.0, I2=0.0, J=0.0)
        bulk.mat1s[100] = Mat1(mid=100, E=E, G=G, nu=0.3, rho=0.0)

        # Elements: orientation vector out-of-plane = (0,0,1)
        bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=3,
                             x1=0.0, x2=0.0, x3=1.0, pa="456", pb="456")
        bulk.cbars[2] = Cbar(eid=2, pid=10, ga=2, gb=3,
                             x1=0.0, x2=0.0, x3=1.0, pa="456", pb="456")

        # Constraints:
        # Supports: fully fixed (123456)
        # Node 3: constrain out-of-plane (Tz=3) and all rotations (456) so K is non-singular
        bulk.spc1s[10] = [
            Spc1(sid=10, c="123456", grids=[1, 2]),
            Spc1(sid=10, c="3456",   grids=[3]),
        ]

        # Load: Fy = -1 at node 3
        bulk.forces[20] = [Force(sid=20, gid=3, cid=0, f=1.0, n1=0.0, n2=-1.0, n3=0.0)]
        return bulk

    def test_tip_deflection_matches_truss_analytical(self):
        """Vertical displacement of apex = -P*sqrt(2)/EA ≈ -sqrt(2)*L_bar/EA."""
        bulk = self._make_bulk()
        cc = CaseControl(
            sol=101,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, load_sid=20)],
        )
        result = run_sol101(bulk, cc.subcases[0])

        # Node 3 is the third grid in sorted order (GIDs 1,2,3 → index 2)
        # Ty at node 3 = global DOF 6*2+1 = 13
        ty_node3 = result.displacements[6 * 2 + 1]

        analytical = -(1.0 * np.sqrt(2)) / (E * A)   # -P*sqrt(2)/EA
        assert ty_node3 == pytest.approx(analytical, rel=1e-6)

    def test_horizontal_displacement_zero_by_symmetry(self):
        """By symmetry, Tx at node 3 must be zero."""
        bulk = self._make_bulk()
        cc = CaseControl(
            sol=101,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, load_sid=20)],
        )
        result = run_sol101(bulk, cc.subcases[0])
        tx_node3 = result.displacements[6 * 2 + 0]
        assert tx_node3 == pytest.approx(0.0, abs=1e-12)

    def test_pin_release_changes_result_vs_rigid(self):
        """With full bending (no pin release), result differs from truss solution."""
        bulk = self._make_bulk()

        # Replace pin-released elements with rigid-connection elements
        # but keep I=0 — so the only difference is torsion (J is also 0 here,
        # so the bending-only test uses non-zero I)
        bulk.pbars[10] = Pbar(pid=10, mid=100, A=A, I1=I, I2=I, J=J)
        bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=3,
                             x1=0.0, x2=0.0, x3=1.0, pa="", pb="")
        bulk.cbars[2] = Cbar(eid=2, pid=10, ga=2, gb=3,
                             x1=0.0, x2=0.0, x3=1.0, pa="", pb="")
        cc = CaseControl(
            sol=101,
            subcases=[SubcaseControl(subcase_id=1, spc_sid=10, load_sid=20)],
        )
        result_rigid = run_sol101(bulk, cc.subcases[0])
        ty_rigid = result_rigid.displacements[6 * 2 + 1]

        analytical_truss = -(1.0 * np.sqrt(2)) / (E * A)

        # Rigid frame carries bending; displacement differs from pure truss
        assert ty_rigid != pytest.approx(analytical_truss, rel=0.01)
