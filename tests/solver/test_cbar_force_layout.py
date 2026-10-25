"""DEF-M18 (#21): CBAR force and stress output in the NASTRAN/MSC layout.

Gates G1–G5 and G7 of ``docs/30_future/designs/cbar_force_stress_output_layout.md``
(G6, the f06 header text and column positions, is in
``tests/results/test_f06_sol101.py`` and ``tests/results/test_f06_column_alignment.py``).
The beam is the ``sample/val_cantilever_static.bdf`` geometry built in
``test_cbar_stress_sign.py`` (10 × 1 m, A = 0.1, I1 = I2 = 8.333e-4,
C = (+c, +c), D = (−c, +c), E = (−c, −c), F = (+c, −c)), tip loads
Px = 5000 (tension), Py = 1000, Pz = 2000.

NASTRAN reference: NASTRAN-95 ``mis/sbar2.f`` forms, from the end-A nodal
forces ``FA``, ``M1A = −FA(6)``, ``M2A = +FA(5)``, ``V1 = −FA(2)``,
``V2 = −FA(3)``, ``FX = −FA(1)``, ``T = −FA(4)``, ``M1B = M1A − V1·L``,
``M2B = M2A − V2·L`` and the bending stress ``σ = −M1·y/I1 − M2·z/I2``, with
``SA-MAX/MIN = AXIAL + max/min(SA1..4)``.
"""

import ast
import pathlib
import re

import numpy as np
import pytest

from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.case_control import SubcaseControl
from sbeam.results.results import BarForce, BarStress
from sbeam.solver.sol101 import (
    _bar_force_from_internal,
    _element_local_forces,
    bar_internal_resultants,
    run_sol101,
)

from tests.solver.test_cbar_stress_sign import (
    A, I1, I2, L_TOTAL, N_EL, POINTS, PX, PY, PZ, _bulk, _run,
)

REL = 1e-9


@pytest.fixture(scope="module")
def solved():
    return _run(PX, PY, PZ)


class TestG1ForceClosedForm:
    """Element 5 (x = 4 → 5): M1 = Py(L−x), M2 = Pz(L−x), the design-note table."""

    def test_element_5_table(self, solved):
        bf = solved[0].bar_forces[5]
        assert bf.m1_a == pytest.approx(6000.0, rel=REL)
        assert bf.m2_a == pytest.approx(12000.0, rel=REL)
        assert bf.m1_b == pytest.approx(5000.0, rel=REL)
        assert bf.m2_b == pytest.approx(10000.0, rel=REL)
        assert bf.v1 == pytest.approx(1000.0, rel=REL)
        assert bf.v2 == pytest.approx(2000.0, rel=REL)
        assert bf.axial == pytest.approx(5000.0, rel=REL)
        assert bf.torque == pytest.approx(0.0, abs=1e-9)

    @pytest.mark.parametrize("eid", range(1, N_EL + 1))
    def test_every_element_both_ends(self, solved, eid):
        bf = solved[0].bar_forces[eid]
        xa, xb = float(eid - 1), float(eid)
        assert bf.m1_a == pytest.approx(PY * (L_TOTAL - xa), rel=REL)
        assert bf.m2_a == pytest.approx(PZ * (L_TOTAL - xa), rel=REL)
        assert bf.m1_b == pytest.approx(PY * (L_TOTAL - xb), rel=REL, abs=1e-9)
        assert bf.m2_b == pytest.approx(PZ * (L_TOTAL - xb), rel=REL, abs=1e-9)


class TestG2SignAnchors:
    """Py only → M1 > 0, M2 = 0; Pz only → M2 > 0, M1 = 0; root plane moment = +PL."""

    def test_py_only(self):
        res, _ = _run(py=PY)
        for bf in res.bar_forces.values():
            assert bf.m1_a > 0 and bf.m2_a == pytest.approx(0.0, abs=1e-9)
            assert bf.v1 == pytest.approx(PY, rel=REL) and bf.v2 == pytest.approx(0.0, abs=1e-9)
        assert res.bar_forces[1].m1_a == pytest.approx(PY * L_TOTAL, rel=REL)

    def test_pz_only(self):
        res, _ = _run(pz=PZ)
        for bf in res.bar_forces.values():
            assert bf.m2_a > 0 and bf.m1_a == pytest.approx(0.0, abs=1e-9)
            assert bf.v2 == pytest.approx(PZ, rel=REL) and bf.v1 == pytest.approx(0.0, abs=1e-9)
        assert res.bar_forces[1].m2_a == pytest.approx(PZ * L_TOTAL, rel=REL)

    def test_negative_py_flips_m1_only(self):
        res, _ = _run(py=-PY, pz=PZ)
        bf = res.bar_forces[1]
        assert bf.m1_a == pytest.approx(-PY * L_TOTAL, rel=REL)
        assert bf.m2_a == pytest.approx(PZ * L_TOTAL, rel=REL)


class TestG3Continuity:
    """Printed end-B values of e equal end-A values of e+1 at every shared node."""

    @pytest.mark.parametrize("loads", [
        (PX, PY, PZ), (0.0, PY, 0.0), (0.0, 0.0, PZ), (PX, 0.0, -PY),
    ])
    def test_all_shared_nodes(self, loads):
        res, _ = _run(*loads)
        for e in range(1, N_EL):
            left, right = res.bar_forces[e], res.bar_forces[e + 1]
            assert right.m1_a == pytest.approx(left.m1_b, rel=REL, abs=1e-9)
            assert right.m2_a == pytest.approx(left.m2_b, rel=REL, abs=1e-9)
            for fld in ("v1", "v2", "axial", "torque"):
                assert getattr(right, fld) == pytest.approx(getattr(left, fld), rel=REL, abs=1e-9)


class TestG4StressClosedForm:
    """Element 6 end A (x = 5): the design-note table, bending-only + AXIAL + MAX/MIN."""

    def test_element_6_end_a(self, solved):
        bs = solved[0].bar_stresses[6]
        assert bs.sa1 == pytest.approx(-2.846094e6, rel=1e-6)
        assert bs.sa2 == pytest.approx(-9.48698e5, rel=1e-6)
        assert bs.sa3 == pytest.approx(+2.846094e6, rel=1e-6)
        assert bs.sa4 == pytest.approx(+9.48698e5, rel=1e-6)
        assert bs.axial == pytest.approx(5.0e4, rel=1e-6)
        assert bs.sa_max == pytest.approx(2.896094e6, rel=1e-6)
        assert bs.sa_min == pytest.approx(-2.796094e6, rel=1e-6)

    def test_max_min_are_axial_plus_extreme_bending(self, solved):
        for bs in solved[0].bar_stresses.values():
            sa = (bs.sa1, bs.sa2, bs.sa3, bs.sa4)
            sb = (bs.sb1, bs.sb2, bs.sb3, bs.sb4)
            assert bs.sa_max == bs.axial + max(sa) and bs.sa_min == bs.axial + min(sa)
            assert bs.sb_max == bs.axial + max(sb) and bs.sb_min == bs.axial + min(sb)

    def test_undefined_point_prints_zero_bending(self):
        """A recovery point left at (0, 0) contributes 0.0, and so bounds MAX/MIN, as in NASTRAN."""
        bulk = _bulk(py=PY)
        pb = bulk.pbars[1]
        pb.d1 = pb.d2 = pb.e1 = pb.e2 = pb.f1 = pb.f2 = 0.0
        res = run_sol101(bulk, SubcaseControl(subcase_id=1, load_sid=10, spc_sid=1))
        bs = res.bar_stresses[1]
        assert (bs.sa2, bs.sa3, bs.sa4) == (0.0, 0.0, 0.0)
        assert bs.sa1 < 0 and bs.sa_max == 0.0 and bs.sa_min == bs.sa1


class TestG5StressForceConsistency:
    """SAi = −M1·yᵢ/I1 − M2·zᵢ/I2 from the *printed* force-table values, every element and end."""

    def test_every_element_and_end(self, solved):
        res = solved[0]
        pts = [POINTS[k] for k in ("C", "D", "E", "F")]
        for eid, bf in res.bar_forces.items():
            bs = res.bar_stresses[eid]
            for i, (y, z) in enumerate(pts, start=1):
                sa = -bf.m1_a * y / I1 - bf.m2_a * z / I2
                sb = -bf.m1_b * y / I1 - bf.m2_b * z / I2
                assert getattr(bs, f"sa{i}") == pytest.approx(sa, rel=1e-12, abs=1e-6)
                assert getattr(bs, f"sb{i}") == pytest.approx(sb, rel=1e-12, abs=1e-6)
            assert bs.axial == pytest.approx(bf.axial / A, rel=1e-12)


class TestNastranMapping:
    """The field mapping against NASTRAN-95 ``sbar2.f`` on the nodal 12-vector."""

    def test_sbar2_formulas_on_synthetic_vector(self):
        f = np.arange(1.0, 13.0)        # FA = f[0:6], FB = f[6:12]
        bf = _bar_force_from_internal(1, bar_internal_resultants(f))
        FA = f[:6]
        assert bf.m1_a == -FA[5]        # M1A = −FA(6)
        assert bf.m2_a == +FA[4]        # M2A = +FA(5)
        assert bf.m1_b == f[11] and bf.m2_b == -f[10]
        assert (bf.v1, bf.v2, bf.axial, bf.torque) == (f[7], f[8], f[6], f[9])

    def test_sbar2_end_b_carry(self, solved):
        """M1B = M1A − V1·L, M2B = M2A − V2·L (sbar2.f line 10) on the solved beam."""
        res, bulk = solved
        gi = build_grid_index(bulk)
        for cbar in bulk.cbars.values():
            f = _element_local_forces(cbar, bulk.grids, bulk.pbars, bulk.mat1s, res.displacements, gi)
            bf = _bar_force_from_internal(cbar.eid, bar_internal_resultants(f))
            L = 1.0
            assert bf.m1_b == pytest.approx(bf.m1_a - bf.v1 * L, rel=1e-12, abs=1e-9)
            assert bf.m2_b == pytest.approx(bf.m2_a - bf.v2 * L, rel=1e-12, abs=1e-9)
            # and the sbar2 end-A definitions hold on the real vector too
            assert bf.v1 == pytest.approx(-f[1], rel=1e-12, abs=1e-9)
            assert bf.v2 == pytest.approx(-f[2], rel=1e-12, abs=1e-9)
            assert bf.axial == pytest.approx(-f[0], rel=1e-12, abs=1e-9)
            assert bf.torque == pytest.approx(-f[3], rel=1e-12, abs=1e-9)


_LEGACY = {"bm1_a", "bm2_a", "bm1_b", "bm2_b", "shear1", "shear2",
           "sa", "sb", "sa_d", "sb_d", "sa_e", "sb_e", "sa_f", "sb_f"}
_ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestG7NoLegacyNames:
    """The old field names are gone from the dataclasses and from all shipped code."""

    def test_dataclass_fields(self):
        assert set(BarForce.__dataclass_fields__) == {
            "eid", "m1_a", "m2_a", "m1_b", "m2_b", "v1", "v2", "axial", "torque"}
        assert set(BarStress.__dataclass_fields__) == {
            "eid", "sa1", "sa2", "sa3", "sa4", "sb1", "sb2", "sb3", "sb4",
            "axial", "sa_max", "sa_min", "sb_max", "sb_min"}
        assert not (_LEGACY & set(BarForce.__dataclass_fields__))
        assert not (_LEGACY & set(BarStress.__dataclass_fields__))

    def test_no_legacy_attribute_access_in_packages(self):
        """No ``.bm1_a`` / ``.shear1`` / ``.sa_d`` … attribute access in sbeam or sbeam_tools."""
        hits = []
        for pkg in ("sbeam", "sbeam_tools"):
            for path in (_ROOT / pkg).rglob("*.py"):
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and node.attr in _LEGACY:
                        hits.append(f"{path.relative_to(_ROOT)}:{node.lineno} .{node.attr}")
        assert not hits, "\n".join(hits)

    def test_no_legacy_f06_labels(self):
        src = (_ROOT / "sbeam/results/f06_writer.py").read_text()
        for label in ("SHEAR-1", "BENDING-1", "BENDING-2", "SA(END-A)", "SB(END-B)"):
            assert label not in src, label
        assert re.search(r"BEND-MOMENT END-A.*BEND-MOMENT END-B", src, re.S)
