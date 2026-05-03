"""Tests for Step 13: GPWG (Grid Point Weight Generator)."""

import pytest

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2
from sbeam.model.bulk_data import BulkData
from sbeam.gpwg import compute_gpwg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_one_element_bulk(L=2.0, rho=7850.0, A=0.01, nsm=0.0):
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
    bulk.grids[2] = Grid(gid=2, x=L,   y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=2e11, G=7.7e10, nu=0.3, rho=rho)
    bulk.pbars[10] = Pbar(pid=10, mid=1, A=A, I1=1e-5, I2=1e-5, J=2e-5, nsm=nsm)
    bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
    return bulk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGpwgOneElement:
    def test_total_mass(self):
        rho = 7850.0
        A = 0.01
        L = 2.0
        bulk = make_one_element_bulk(L=L, rho=rho, A=A)
        result = compute_gpwg(bulk)
        expected_mass = rho * A * L
        assert result.total_mass == pytest.approx(expected_mass, rel=1e-4)

    def test_cg_at_midpoint(self):
        """CG of uniform element should be at midpoint."""
        L = 2.0
        bulk = make_one_element_bulk(L=L)
        result = compute_gpwg(bulk)
        assert result.cg_x == pytest.approx(L / 2, rel=1e-6)
        assert result.cg_y == pytest.approx(0.0, abs=1e-12)
        assert result.cg_z == pytest.approx(0.0, abs=1e-12)

    def test_with_nsm(self):
        """NSM adds extra mass per unit length."""
        rho = 7850.0
        A = 0.01
        nsm = 5.0  # kg/m
        L = 2.0
        bulk = make_one_element_bulk(L=L, rho=rho, A=A, nsm=nsm)
        result = compute_gpwg(bulk)
        expected_mass = (rho * A + nsm) * L
        assert result.total_mass == pytest.approx(expected_mass, rel=1e-4)


class TestGpwgWithConm2:
    def test_total_mass_includes_conm2(self):
        rho = 7850.0
        A = 0.01
        L = 2.0
        point_mass = 50.0

        bulk = make_one_element_bulk(L=L, rho=rho, A=A)
        bulk.conm2s[100] = Conm2(eid=100, gid=2, cid=0, m=point_mass)

        result = compute_gpwg(bulk)
        elem_mass = rho * A * L
        expected = elem_mass + point_mass
        assert result.total_mass == pytest.approx(expected, rel=1e-4)

    def test_cg_shifts_toward_tip(self):
        """Adding mass at tip (x=L) moves CG toward tip."""
        L = 2.0
        rho = 7850.0
        A = 0.01

        bulk_no_tip = make_one_element_bulk(L=L, rho=rho, A=A)
        result_no_tip = compute_gpwg(bulk_no_tip)

        bulk_tip = make_one_element_bulk(L=L, rho=rho, A=A)
        bulk_tip.conm2s[100] = Conm2(eid=100, gid=2, cid=0, m=1000.0)
        result_tip = compute_gpwg(bulk_tip)

        assert result_tip.cg_x > result_no_tip.cg_x

    def test_conm2_only(self):
        """CONM2 with zero density CBAR: mass and CG from point mass only."""
        bulk = make_one_element_bulk(rho=0.0, A=0.0)
        bulk.conm2s[1] = Conm2(eid=1, gid=2, cid=0, m=10.0)
        result = compute_gpwg(bulk)
        assert result.total_mass == pytest.approx(10.0, rel=1e-10)
        # CG at grid 2: x=2.0
        assert result.cg_x == pytest.approx(2.0, rel=1e-10)


class TestGpwgZeroDensity:
    def test_zero_density_zero_mass(self):
        bulk = make_one_element_bulk(rho=0.0)
        result = compute_gpwg(bulk)
        assert result.total_mass == pytest.approx(0.0, abs=1e-30)

    def test_zero_density_cg_at_origin(self):
        bulk = make_one_element_bulk(rho=0.0)
        result = compute_gpwg(bulk)
        assert result.cg_x == pytest.approx(0.0, abs=1e-12)
        assert result.cg_y == pytest.approx(0.0, abs=1e-12)
        assert result.cg_z == pytest.approx(0.0, abs=1e-12)
