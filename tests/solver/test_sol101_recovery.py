"""Tests for Step 11: SOL 101 post-processing (forces, stresses, reactions)."""

import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.solver.sol101 import (
    run_sol101,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

E = 2e11
I1 = 8.333e-4
A = 0.05
L = 1.0
P = 1000.0
G = E / (2.0 * 1.3)
J = 2 * I1
c1_val = 0.15   # y-coordinate of recovery point C
c2_val = 0.0    # z-coordinate of recovery point C


def make_cantilever_bulk():
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[10] = Pbar(
        pid=10, mid=1, A=A, I1=I1, I2=I1, J=J,
        c1=c1_val, c2=c2_val,
    )
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    bulk.forces[10] = [Force(sid=10, gid=2, cid=0, f=P, n1=0.0, n2=1.0, n3=0.0)]
    return bulk


def _run_cantilever():
    bulk = make_cantilever_bulk()
    cc = CaseControl(
        sol=101,
        subcases=[SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1)],
    )
    return run_sol101(bulk, cc), bulk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBarForceRecovery:
    def setup_method(self):
        self.result, self.bulk = _run_cantilever()

    def test_bending_moment_at_fixed_end(self):
        """Fixed-end Mz (bending moment about z) = P*L."""
        bf = self.result.bar_forces[1]
        expected_mz = P * L
        # bm2_a = Mz at end A (fixed end)
        assert abs(bf.bm2_a) == pytest.approx(expected_mz, rel=1e-3)

    def test_shear_along_beam(self):
        """Shear force (Fy) = P along beam."""
        bf = self.result.bar_forces[1]
        # shear1 is Fy at end B; for a cantilever with tip load P, shear = P
        assert abs(bf.shear1) == pytest.approx(P, rel=1e-3)

    def test_axial_near_zero(self):
        """No axial load applied → axial force near zero."""
        bf = self.result.bar_forces[1]
        assert abs(bf.axial) < 1.0  # < 1 N relative to kN-level loads


class TestReactionRecovery:
    def setup_method(self):
        self.result, self.bulk = _run_cantilever()

    def test_reaction_sum_y(self):
        """Sum of Y-reactions = applied load P."""
        total_ry = 0.0
        for gid, r in self.result.reactions.items():
            total_ry += r[1]
        assert abs(total_ry) == pytest.approx(P, rel=1e-3)

    def test_reaction_moment_z(self):
        """Moment reaction at fixed end = P*L (about z-axis)."""
        r = self.result.reactions.get(1)
        assert r is not None
        assert abs(r[5]) == pytest.approx(P * L, rel=1e-3)

    def test_sum_of_reactions_equals_negative_applied(self):
        """Sum of SPC reactions = -P (reactions oppose applied load)."""
        fy_total = 0.0
        for gid, r in self.result.reactions.items():
            fy_total += r[1]
        # Applied load is +P in Y; SPC reactions must sum to -P
        assert fy_total == pytest.approx(-P, rel=1e-3)


class TestBarStressRecovery:
    def setup_method(self):
        self.result, self.bulk = _run_cantilever()

    def test_bending_stress_at_fixed_end(self):
        """Bending stress at recovery point C at end A: σ = Mz*c1/I1."""
        bs = self.result.bar_stresses[1]
        bf = self.result.bar_forces[1]
        mz_a = abs(bf.bm2_a)
        expected_stress = mz_a * c1_val / I1
        assert abs(bs.sa) == pytest.approx(expected_stress, rel=1e-3)

    def test_stress_end_b_smaller(self):
        """Tip stress should be smaller than fixed-end stress for cantilever."""
        bs = self.result.bar_stresses[1]
        # At end B (tip), moment is zero → stress near zero
        assert abs(bs.sb) < abs(bs.sa)


class TestRunSol101:
    def test_returns_sol101result(self):
        from sbeam.results.results import Sol101Result
        result, bulk = _run_cantilever()
        assert isinstance(result, Sol101Result)

    def test_displacement_shape(self):
        result, bulk = _run_cantilever()
        assert result.displacements.shape == (12,)

    def test_bar_forces_keys(self):
        result, bulk = _run_cantilever()
        assert 1 in result.bar_forces

    def test_bar_stresses_keys(self):
        result, bulk = _run_cantilever()
        assert 1 in result.bar_stresses
