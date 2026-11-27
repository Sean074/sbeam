"""PARAM,GRDPNT prints MSC's grid point weight generator block (#90).

MSC: GRDPNT > -1 runs the GPWG about grid GRDPNT; 0 or an undefined grid is the basic
origin; -1 (default) prints nothing (QRG 2024.1 PDF p.885).  The reduction of MO to
directional masses, C.G.s and inertias is gated on MSC's own printout for HA144B
(AAUG 2023.1 PDF p.269), fed the MO matrix MSC printed.
"""
import warnings

import numpy as np
import pytest

from sbeam.gpwg import reduce_rigid_body_mass, rigid_body_mass_matrix
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.results.f06_writer import build_f06_gpwg_text

# HA144B, reference point 11 (AAUG 2023.1 PDF p.269)
_MO_HA144B = np.array([
    [0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0],
    [0, 0, 4.191900E+04, 5.128960E+06, -1.642074E+05, 0],
    [0, 0, 5.128960E+06, 1.350243E+09, -2.381847E+07, 0],
    [0, 0, -1.642074E+05, -2.381847E+07, 4.458796E+09, 0],
    [0, 0, 0, 0, 0, 0]])


class TestMscReduction:
    def test_ha144b_mass_and_cg(self):
        t = reduce_rigid_body_mass(_MO_HA144B, 11)
        assert t.mass == pytest.approx([0.0, 0.0, 4.191900E+04])
        assert t.cg[2] == pytest.approx([3.917256E+00, 1.223541E+02, 0.0], rel=1e-6)
        assert np.all(t.cg[:2] == 0.0)          # massless directions print zeros

    def test_ha144b_inertia_about_cg(self):
        t = reduce_rigid_body_mass(_MO_HA144B, 11)
        assert t.i_s == pytest.approx(np.array([
            [7.226942E+08, 3.727022E+06, 0.0],
            [3.727022E+06, 4.458153E+09, 0.0],
            [0.0, 0.0, 0.0]]), rel=2e-6, abs=1.0)

    def test_ha144b_principal_inertia(self):
        t = reduce_rigid_body_mass(_MO_HA144B, 11)
        assert t.i_q == pytest.approx([4.458157E+09, 7.226906E+08, 0.0], rel=2e-6, abs=1.0)
        # MSC's Q, column by column, up to each column's sign
        q_msc = np.array([[9.977400E-04, 9.999995E-01, 0.0],
                          [-9.999995E-01, 9.977400E-04, 0.0],
                          [0.0, 0.0, 1.0]])
        for j in range(3):
            assert abs(float(t.q[:, j] @ q_msc[:, j])) == pytest.approx(1.0, abs=1e-6)
        assert np.linalg.det(t.q) == pytest.approx(1.0)


def _masses(grdpnt_line=""):
    lines = ["GRID, 1, , 0., 0., 0.", "GRID, 2, , 4., 1., 0.", "GRID, 3, , 0., 0., 2.",
             "CONM2, 10, 2, , 3.0", "CONM2, 11, 3, , 1.0"]
    if grdpnt_line:
        lines.append(grdpnt_line)
    return parse_bulk_data(lines)


class TestRigidBodyMassMatrix:
    def test_point_masses_by_hand(self):
        """3.0 at (4, 1, 0) and 1.0 at (0, 0, 2) about grid 1 (the origin)."""
        mo = rigid_body_mass_matrix(_masses(), 1)
        m = 4.0
        sx, sy, sz = 3.0 * 4.0, 3.0 * 1.0, 1.0 * 2.0          # first moments Σm·r
        assert mo[:3, :3] == pytest.approx(m * np.eye(3))
        # translation x coupled to rotation y and z: Fx·z → My, −Fx·y → Mz
        assert mo[0, 4] == pytest.approx(sz) and mo[0, 5] == pytest.approx(-sy)
        assert mo[1, 3] == pytest.approx(-sz) and mo[1, 5] == pytest.approx(sx)
        assert mo[2, 3] == pytest.approx(sy) and mo[2, 4] == pytest.approx(-sx)
        ixx = 3.0 * 1.0 + 1.0 * 4.0      # Σm(y² + z²)
        assert mo[3, 3] == pytest.approx(ixx)
        t = reduce_rigid_body_mass(mo, 1)
        assert t.cg[2] == pytest.approx([sx / m, sy / m, 0.0])
        # about the C.G.: Ixx = Σm(y²+z²) − m(ycg² + zcg²)
        assert t.i_s[0, 0] == pytest.approx(ixx - m * ((sy / m) ** 2 + (sz / m) ** 2))

    def test_reference_point_shifts_the_cg(self):
        t = reduce_rigid_body_mass(rigid_body_mass_matrix(_masses(), 2), 2)
        assert t.cg[2] == pytest.approx([3.0 - 4.0, 0.75 - 1.0, 0.0])


class TestGrdpnt:
    def test_default_prints_nothing(self):
        assert build_f06_gpwg_text(_masses()) == ""

    @pytest.mark.parametrize("value, ref", [(0, 0), (2, 2), (99, 99)])
    def test_block_and_reference_point(self, value, ref):
        bulk = _masses(f"PARAM, GRDPNT, {value}")
        text = build_f06_gpwg_text(bulk)
        assert "W E I G H T   G E N E R A T O R" in text
        assert f"REFERENCE POINT ={ref:>10}" in text

    def test_undefined_grid_is_the_basic_origin(self):
        """QRG p.885: 'not a defined grid point' -> the basic origin."""
        assert np.allclose(rigid_body_mass_matrix(_masses(), 99),
                           rigid_body_mass_matrix(_masses(), 0))

    def _deck(self, tmp_path, cc_param, bulk_param):
        deck = tmp_path / "d.bdf"
        deck.write_text("SOL 103\n" + cc_param + "SUBCASE 1\n  METHOD = 1\nBEGIN BULK\n"
                        "EIGRL, 1, , , 2\nGRID, 1, , 0., 0., 0.\nCONM2, 10, 1, , 3.0\n"
                        + bulk_param + "ENDDATA\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return parse_bdf(deck)

    def test_case_control_param_is_read(self, tmp_path):
        _cc, bulk = self._deck(tmp_path, "PARAM, GRDPNT, 0\n", "")
        assert bulk.grdpnt == 0

    def test_conflicting_values_are_refused(self, tmp_path):
        with pytest.raises(ValueError, match="GRDPNT is 0 in case control and 1"):
            self._deck(tmp_path, "PARAM, GRDPNT, 0\n", "PARAM, GRDPNT, 1\n")
