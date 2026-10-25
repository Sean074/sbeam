"""#38 rod element — recovery gates G6 (NASTRAN-95 ``srod1.f``/``srod2.f`` mapping)
and G7 (every solver path fills the rod dicts), design note
``docs/30_future/designs/rod_element_crod.md``.
"""

from typing import Union

import numpy as np
import pytest

from sbeam.assembly.elements import line_element
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.element import Conrod, Crod
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.model.bulk_data import BulkData
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.results import RodForce
from sbeam.solver.element_recovery import (
    local_end_forces, recover_line_elements, rod_force_from_local, rod_stress_from_force,
)
from sbeam.solver.sol101 import run_sol101
from tests.assembly.test_rod_element import A, C, E, G, J, MIXED_DECK


def _rod_bulk(ga_xyz, gb_xyz, kind="CONROD") -> tuple[BulkData, Union[Crod, Conrod]]:
    bulk = BulkData()
    bulk.grids[1] = Grid(gid=1, x=ga_xyz[0], y=ga_xyz[1], z=ga_xyz[2])
    bulk.grids[2] = Grid(gid=2, x=gb_xyz[0], y=gb_xyz[1], z=gb_xyz[2])
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.25, rho=7850.0)
    elem = Conrod(eid=5, ga=1, gb=2, mid=1, A=A, J=J, c=C)
    bulk.conrods[5] = elem
    return bulk, elem


class TestG6NastranMapping:
    """``σ = (E/L)·n·(u_B − u_A)``, ``P = A·σ``, ``T = (GJ/L)·n·(θ_B − θ_A)``, ``τ = T·C/J``."""

    @pytest.mark.parametrize("gb_xyz", [(2.0, 0.0, 0.0), (1.0, 2.0, 3.0), (-0.5, 0.2, 1.1)])
    def test_force_and_torque_from_a_synthetic_displacement(self, gb_xyz):
        bulk, elem = _rod_bulk((0.3, -0.2, 0.1), gb_xyz)
        le = line_element(elem, bulk)
        gi = build_grid_index(bulk)
        rng = np.random.default_rng(38)
        u = rng.normal(size=12) * 1e-3
        rf = rod_force_from_local(elem.eid, local_end_forces(le, u, gi))
        n = (np.array(gb_xyz) - np.array((0.3, -0.2, 0.1)))
        L = np.linalg.norm(n); n = n / L
        p_expected = A * (E / L) * n @ (u[6:9] - u[0:3])
        t_expected = (G * J / L) * n @ (u[9:12] - u[3:6])
        assert rf.axial == pytest.approx(p_expected, rel=1e-13)
        assert rf.torque == pytest.approx(t_expected, rel=1e-13)

    def test_tension_positive_whichever_way_the_rod_is_numbered(self):
        for ga, gb in (((0, 0, 0), (2, 0, 0)), ((2, 0, 0), (0, 0, 0))):
            bulk, elem = _rod_bulk(ga, gb)
            le = line_element(elem, bulk)
            gi = build_grid_index(bulk)
            u = np.zeros(12)
            # Stretch: move the grid at x = 2 further out by 1e-3 whichever node it is.
            far = 0 if ga[0] == 2 else 6
            u[far] = 1e-3
            rf = rod_force_from_local(elem.eid, local_end_forces(le, u, gi))
            assert rf.axial == pytest.approx(E * A / 2.0 * 1e-3, rel=1e-13)
            assert rf.axial > 0.0

    def test_stress_mapping_and_zero_J(self):
        rf = RodForce(eid=1, axial=1000.0, torque=10.0)
        rs = rod_stress_from_force(1, rf, A=A, J=J, c=C)
        assert rs.axial == pytest.approx(1000.0 / A, rel=1e-14)
        assert rs.torsional == pytest.approx(10.0 * C / J, rel=1e-14)
        # srod1.f: FJOVRC = 0 when J = 0; a zero C also leaves τ = 0.
        assert rod_stress_from_force(1, rf, A=A, J=0.0, c=C).torsional == 0.0
        assert rod_stress_from_force(1, rf, A=A, J=J, c=0.0).torsional == 0.0


class TestG7RecoveryCoverage:
    @pytest.fixture(scope="class")
    def solved(self, tmp_path_factory):
        f = tmp_path_factory.mktemp("mixed") / "mixed.bdf"
        f.write_text(MIXED_DECK)
        cc, bulk = parse_bdf(str(f))
        return bulk, run_sol101(bulk, cc.subcases[0]), build_grid_index(bulk)

    def test_sol101_fills_every_dict(self, solved):
        bulk, result, _ = solved
        assert set(result.bar_forces) == {1} and set(result.bar_stresses) == {1}
        assert set(result.rod_forces) == {2, 3} and set(result.rod_stresses) == {2, 3}

    def test_recover_line_elements_matches_sol101_and_can_skip_stresses(self, solved):
        bulk, result, gi = solved
        elems = recover_line_elements(bulk, result.displacements, gi)
        assert elems.rod_forces == result.rod_forces
        assert elems.bar_forces == result.bar_forces
        forces_only = recover_line_elements(bulk, result.displacements, gi, stresses=False)
        assert forces_only.rod_forces == result.rod_forces
        assert forces_only.rod_stresses == {} and forces_only.bar_stresses == {}

    def test_rod_only_grid_carries_the_axial_load(self, solved):
        bulk, result, _ = solved
        # Grid 4 is loaded by Fx = 100 and held only by CONROD 3 from grid 2.
        rod = bulk.conrods[3]
        ga, gb = bulk.grids[rod.ga], bulk.grids[rod.gb]
        n = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z]); n /= np.linalg.norm(n)
        # The rod pulls its end-B node toward end A with -N·n; that must balance the
        # applied +100 x-load (the grid's other DOFs are SPC'd).
        assert result.rod_forces[3].axial * n[0] == pytest.approx(100.0, rel=1e-9)
        assert result.rod_forces[3].axial == pytest.approx(100.0, rel=1e-9)
