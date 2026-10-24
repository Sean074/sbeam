"""DEF-M21 (#37): CBAR fibre stress from +x-face internal resultants.

Gates G1–G5 of ``docs/30_future/designs/cbar_stress_recovery_sign.md``.
Geometry is the ``sample/val_cantilever_static.bdf`` beam (10 × 1 m, solid
square section) built in code so the loads can be varied per gate.
"""

import numpy as np
import pytest

from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.bulk_data import BulkData
from sbeam.model.constraint import Spc1
from sbeam.model.element import Cbar
from sbeam.model.grid import Grid
from sbeam.model.load import Force
from sbeam.model.material import Mat1
from sbeam.model.property import Pbar
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol101 import (
    _element_local_forces,
    bar_internal_resultants,
    run_sol101,
)

E = 2.0e11
G = 7.692e10
A = 0.1
I1 = 8.333e-4
I2 = 8.333e-4
J = 1.406e-3
C_PT = 0.15811
L_TOTAL = 10.0
N_EL = 10
TIP = N_EL + 1

# Recovery points (y, z) as on the sample PBAR.
POINTS = {
    "C": (+C_PT, +C_PT),
    "D": (-C_PT, +C_PT),
    "E": (-C_PT, -C_PT),
    "F": (+C_PT, -C_PT),
}
SA = {"C": "sa", "D": "sa_d", "E": "sa_e", "F": "sa_f"}
SB = {"C": "sb", "D": "sb_d", "E": "sb_e", "F": "sb_f"}


def _bulk(px: float = 0.0, py: float = 0.0, pz: float = 0.0) -> BulkData:
    bulk = BulkData()
    for i in range(TIP):
        bulk.grids[i + 1] = Grid(gid=i + 1, x=float(i), y=0.0, z=0.0)
    bulk.mat1s[1] = Mat1(mid=1, E=E, G=G, nu=0.3, rho=7850.0)
    bulk.pbars[1] = Pbar(
        pid=1, mid=1, A=A, I1=I1, I2=I2, J=J,
        c1=POINTS["C"][0], c2=POINTS["C"][1],
        d1=POINTS["D"][0], d2=POINTS["D"][1],
        e1=POINTS["E"][0], e2=POINTS["E"][1],
        f1=POINTS["F"][0], f2=POINTS["F"][1],
    )
    for e in range(1, N_EL + 1):
        bulk.cbars[e] = Cbar(eid=e, pid=1, ga=e, gb=e + 1, x1=0.0, x2=1.0, x3=0.0)
    bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1])]
    loads = []
    if px:
        loads.append(Force(sid=10, gid=TIP, cid=0, f=px, n1=1.0, n2=0.0, n3=0.0))
    if py:
        loads.append(Force(sid=10, gid=TIP, cid=0, f=py, n1=0.0, n2=1.0, n3=0.0))
    if pz:
        loads.append(Force(sid=10, gid=TIP, cid=0, f=pz, n1=0.0, n2=0.0, n3=1.0))
    bulk.forces[10] = loads
    return bulk


def _run(px: float = 0.0, py: float = 0.0, pz: float = 0.0):
    bulk = _bulk(px, py, pz)
    res = run_sol101(bulk, SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1))
    return res, bulk


def _closed_form(x: float, y: float, z: float, px: float, py: float, pz: float) -> float:
    """σ(x, y, z) for a cantilever with tip loads Px (tension), Py, Pz."""
    return px / A - py * (L_TOTAL - x) * y / I1 - pz * (L_TOTAL - x) * z / I2


PX, PY, PZ = 5000.0, 1000.0, 2000.0


class TestG1TwoPlaneClosedForm:
    """Both ends of elements 1, 5, 6, 9 at points C and E, both planes + axial."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run(PX, PY, PZ)[0]

    @pytest.mark.parametrize("eid", [1, 5, 6, 9])
    @pytest.mark.parametrize("pt", ["C", "E"])
    def test_end_a(self, result, eid, pt):
        y, z = POINTS[pt]
        x_a = float(eid - 1)
        got = getattr(result.bar_stresses[eid], SA[pt])
        assert got == pytest.approx(_closed_form(x_a, y, z, PX, PY, PZ), rel=1e-9)

    @pytest.mark.parametrize("eid", [1, 5, 6, 9])
    @pytest.mark.parametrize("pt", ["C", "E"])
    def test_end_b(self, result, eid, pt):
        y, z = POINTS[pt]
        x_b = float(eid)
        got = getattr(result.bar_stresses[eid], SB[pt])
        assert got == pytest.approx(_closed_form(x_b, y, z, PX, PY, PZ), rel=1e-9)

    def test_design_note_table_values(self, result):
        """The §1 'closed form' column of the design note (C = 0.15811)."""
        bs5 = result.bar_stresses[5]
        assert bs5.sb == pytest.approx(_closed_form(5.0, C_PT, C_PT, PX, PY, PZ), rel=1e-12)
        assert bs5.sb < 0.0 and bs5.sb_e > 0.0
        bs6 = result.bar_stresses[6]
        assert bs6.sa == pytest.approx(bs5.sb, rel=1e-12)


class TestG2SignAnchors:
    """+Py compresses +y fibres; +Pz compresses +z fibres; signed, at both ends."""

    def test_py_only(self):
        res, _ = _run(py=PY)
        for eid in (1, 5, 9):
            bs = res.bar_stresses[eid]
            # C and F have y > 0 → compression; D and E have y < 0 → tension.
            assert bs.sa < 0 and bs.sb < 0
            assert bs.sa_f < 0 and bs.sb_f < 0
            assert bs.sa_d > 0 and bs.sb_d > 0
            assert bs.sa_e > 0 and bs.sb_e > 0

    def test_pz_only(self):
        res, _ = _run(pz=PZ)
        for eid in (1, 5, 9):
            bs = res.bar_stresses[eid]
            # C and D have z > 0 → compression; E and F have z < 0 → tension.
            assert bs.sa < 0 and bs.sb < 0
            assert bs.sa_d < 0 and bs.sb_d < 0
            assert bs.sa_e > 0 and bs.sb_e > 0
            assert bs.sa_f > 0 and bs.sb_f > 0

    def test_px_only_uniform_tension(self):
        res, _ = _run(px=PX)
        for bs in res.bar_stresses.values():
            for pt in POINTS:
                assert getattr(bs, SA[pt]) == pytest.approx(PX / A, rel=1e-12)
                assert getattr(bs, SB[pt]) == pytest.approx(PX / A, rel=1e-12)


class TestG3Continuity:
    """σ(end B of e) == σ(end A of e+1) at every shared node and point."""

    @pytest.mark.parametrize("loads", [
        (PX, PY, PZ), (0.0, PY, 0.0), (0.0, 0.0, PZ), (PX, 0.0, -PY),
    ])
    def test_all_shared_nodes(self, loads):
        res, _ = _run(*loads)
        for e in range(1, N_EL):
            left = res.bar_stresses[e]
            right = res.bar_stresses[e + 1]
            for pt in POINTS:
                sb = getattr(left, SB[pt])
                sa = getattr(right, SA[pt])
                assert sa == pytest.approx(sb, rel=1e-9, abs=1e-6), (e, pt)


class TestG4EquilibriumIdentity:
    """Helper end-B moments equal the end-A moments carried by the shears."""

    def test_identity_every_element(self):
        res, bulk = _run(PX, PY, PZ)
        gi = build_grid_index(bulk)
        for cbar in bulk.cbars.values():
            f = _element_local_forces(
                cbar, bulk.grids, bulk.pbars, bulk.mat1s, res.displacements, gi)
            r = bar_internal_resultants(f)
            L = 1.0
            assert r.mz_b == pytest.approx(r.mz_a - r.vy * L, rel=1e-12, abs=1e-9)
            assert r.my_b == pytest.approx(r.my_a + r.vz * L, rel=1e-12, abs=1e-9)
            # Constant resultants: both nodal values agree in magnitude.
            assert r.p == pytest.approx(-f[0], rel=1e-12, abs=1e-9)
            assert r.vy == pytest.approx(-f[1], rel=1e-12, abs=1e-9)
            assert r.vz == pytest.approx(-f[2], rel=1e-12, abs=1e-9)
            assert r.t == pytest.approx(-f[3], rel=1e-12, abs=1e-9)

    def test_face_mapping(self):
        """End A negated, end B as-is, on a synthetic vector."""
        f = np.arange(1.0, 13.0)
        r = bar_internal_resultants(f)
        assert (r.p, r.vy, r.vz, r.t) == (7.0, 8.0, 9.0, 10.0)
        assert (r.my_a, r.mz_a) == (-5.0, -6.0)
        assert (r.my_b, r.mz_b) == (11.0, 12.0)


class TestG5EndANonRegression:
    """End-A stresses are bit-identical to the pre-#37 formula on raw nodal values."""

    def test_end_a_exact(self):
        res, bulk = _run(PX, PY, PZ)
        gi = build_grid_index(bulk)
        for cbar in bulk.cbars.values():
            f = _element_local_forces(
                cbar, bulk.grids, bulk.pbars, bulk.mat1s, res.displacements, gi)
            bs = res.bar_stresses[cbar.eid]
            for pt, (y, z) in POINTS.items():
                old = 0.0
                old += f[6] / A
                old += f[5] * y / I1
                old -= f[4] * z / I2
                assert getattr(bs, SA[pt]) == old

    def test_end_b_is_the_face_value_not_the_raw_nodal_value(self):
        res, bulk = _run(PX, PY, PZ)
        gi = build_grid_index(bulk)
        cbar = bulk.cbars[5]
        f = _element_local_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, res.displacements, gi)
        y, z = POINTS["C"]
        raw = f[6] / A + f[11] * y / I1 - f[10] * z / I2
        face = f[6] / A - f[11] * y / I1 + f[10] * z / I2
        assert res.bar_stresses[5].sb == pytest.approx(face, rel=1e-12)
        assert res.bar_stresses[5].sb != pytest.approx(raw, rel=1e-3)
