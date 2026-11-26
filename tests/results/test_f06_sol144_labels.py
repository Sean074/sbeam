"""SOL 144 f06 labels that misled a comparison with MSC (#82).

Audit findings O1-O4 (2026-11-16).  The reference is MSC's own HA144A output, Listing
7-2 of the MSC Nastran 2023.1 Aeroelastic Analysis User's Guide (PDF p.233-235).  MSC
runs the half model and prints coefficients in the AEROS reference frame (z down); sbeam
runs ``ha144a_fullspan_sbeam.bdf`` (both sides, so hinge moments are doubled) and prints
basic axes.  ``G`` converts MSC's per-g URDD values to per unit acceleration.
"""
import warnings

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam.results.f06_writer import write_f06_sol144
from sbeam.solver.sol144 import run_sol144_trim
from sbeam.solver.sol144_util import urdd_derivs_to_label_frame
from tests.samples import sample_path

G = 32.174


@pytest.fixture(scope="module")
def ha144a():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(str(sample_path("ha144a_fullspan_sbeam.bdf")))
        gi = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=gi)
        result = run_sol144_trim(bulk, cc.subcases[0], aero)
    return cc, bulk, result


@pytest.fixture(scope="module")
def f06(ha144a, tmp_path_factory):
    cc, bulk, result = ha144a
    path = tmp_path_factory.mktemp("f06") / "ha144a.f06"
    sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1, aerof=True, apres=True)
    write_f06_sol144(str(path), CaseControl(sol=144, subcases=[sc]), bulk, result, subcase_id=1)
    return path.read_text()


class TestCoefficientFrame:
    """O1: sbeam CZ(ANGLEA) = +5.070976 in basic; MSC prints -5.070975 in the reference
    frame after "TRANSFORMATION FROM BASIC TO REFERENCE COORDINATES" (AAUG p.233)."""

    def test_the_frame_is_stated(self, f06):
        assert "COEFFICIENTS IN THIS BLOCK ARE IN BASIC AXES" in f06
        assert "MSC NASTRAN PRINTS THEM IN THE AEROS REFERENCE FRAME (RCSID = 100)" in f06

    def test_msc_transformation_is_printed(self, f06):
        """AAUG p.233: [-1 0 0; 0 1 0; 0 0 -1], offset (15, 0, 0)."""
        block = f06[f06.index("TRANSFORMATION FROM BASIC TO REFERENCE COORDINATES"):]
        rows = [line for line in block.splitlines()[1:4]]
        values = [[float(t) for t in row.replace("{", " ").replace("}", " ").replace("[", " ")
                   .replace("]", " ").split() if t.replace(".", "").replace("-", "")
                   .replace("E", "").replace("+", "").isdigit()] for row in rows]
        assert values == [[-1.0, 0.0, 0.0, 15.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, -1.0, 0.0]]

    def test_rigid_cz_alpha_converts_to_msc(self, ha144a):
        """sbeam basic +5.070976 -> reference -5.070976; MSC -5.070975E+00."""
        cz = ha144a[2].rigid_derivs["ANGLEA"]["CZ"]
        assert -cz == pytest.approx(-5.070975, rel=1e-6)


class TestUrddRowsArePerUnitLabel:
    """O2: the URDD rows were per unit basic acceleration, while the trim variable of
    that name (printed as -32.174) is a reference-frame component."""

    def test_restrained_urdd3_matches_msc(self, ha144a):
        """AAUG p.234: restrained URDD3 CZ = 3.154313E-03, CMY = 2.368632E-03 per g in the
        reference frame.  In basic axes per unit acceleration: -9.804e-5 and +7.362e-5.
        sbeam printed +1.0097e-4 and -7.69e-5.  The elastic increments of the two models
        differ by a few per cent (sbeam's restrained CZ-alpha increment is 12 % below
        MSC's), hence the tolerance."""
        row = ha144a[2].restrained_derivs["URDD3"]
        assert row["CZ"] == pytest.approx(-3.154313e-3 / G, rel=0.05)
        assert row["CMY"] == pytest.approx(2.368632e-3 / G, rel=0.06)

    def test_restrained_urdd5_still_matches_msc(self, ha144a):
        """AAUG p.234: CZ = 5.904780E-02, CMY = 3.950050E-02 per g.  A rotation about y
        is the same in both frames, so this row did not change."""
        row = ha144a[2].restrained_derivs["URDD5"]
        assert row["CZ"] == pytest.approx(-5.904780e-2 / G, rel=0.01)
        assert row["CMY"] == pytest.approx(3.950050e-2 / G, rel=0.01)

    def test_helper_is_the_chain_rule(self):
        """d/d(URDD_j, RCSID) = sum_i d/d(URDD_i, basic) R[i, j]."""
        c, s = np.cos(0.3), np.sin(0.3)
        rot = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
        basic = {"URDD1": {"CZ": 2.0}, "URDD3": {"CZ": 5.0}, "ANGLEA": {"CZ": 7.0}}
        out = urdd_derivs_to_label_frame(basic, rot, True)
        assert out["URDD1"]["CZ"] == pytest.approx(2.0 * c + 5.0 * -s)
        assert out["URDD3"]["CZ"] == pytest.approx(2.0 * s + 5.0 * c)
        assert out["ANGLEA"]["CZ"] == 7.0 and basic["URDD3"]["CZ"] == 5.0

    def test_no_rcsid_leaves_the_rows_alone(self):
        basic = {"URDD3": {"CZ": 5.0}}
        assert urdd_derivs_to_label_frame(basic, -np.eye(3), False) == basic


class TestHingeMoments:
    """O3: the per-variable rows were rigid, the TOTAL row elastic, in one column."""

    @pytest.mark.parametrize("label, msc_rigid, msc_restrained", [
        ("ANGLEA", 3.103143e1, 3.020692e1), ("PITCH", -6.124346e2, -6.132635e2),
        ("ELEV", 1.193384e2, 1.192125e2),
    ])
    def test_rigid_and_restrained_columns_match_msc(self, ha144a, label, msc_rigid,
                                                    msc_restrained):
        """AAUG p.234, "HINGE MOMENT DERIVATIVE COEFFICIENTS", CREFC = CREFS = 1: the
        coefficient is HM/q.  Half model, so sbeam's full span is twice it."""
        result = ha144a[2]
        assert result.hinge_moments["ELEV"][label] == pytest.approx(2 * msc_rigid, rel=1e-5)
        restrained = result.hinge_moments_restrained["ELEV"][label]
        assert restrained / result.hinge_moments["ELEV"][label] == pytest.approx(
            msc_restrained / msc_rigid, abs=1e-3)

    @pytest.mark.parametrize("label, msc_per_g", [("URDD3", 4.527646e-2), ("URDD5", 5.787790e-1)])
    def test_restrained_urdd_rows_match_msc(self, ha144a, label, msc_per_g):
        """AAUG p.234; zero in the rigid column, as in MSC."""
        result = ha144a[2]
        assert result.hinge_moments["ELEV"][label] == 0.0
        assert result.hinge_moments_restrained["ELEV"][label] == pytest.approx(
            2 * msc_per_g / G, rel=0.03)

    def test_trimmed_hinge_moment_matches_msc(self, ha144a):
        """AAUG p.235, "CONTROL SURFACE POSITION AND HINGE MOMENT RESULTS": ELEV position
        4.924567E-01, hinge moment 2.544685E+03 (half model)."""
        result = ha144a[2]
        assert result.trim_vars["ELEV"] == pytest.approx(4.924567e-1, rel=2e-3)
        assert result.q * result.hinge_moments["ELEV"]["total"] == pytest.approx(
            2 * 2.544685e3, rel=5e-3)

    def test_f06_separates_derivatives_from_the_trimmed_moment(self, f06):
        assert "TOTAL (TRIM)" not in f06
        derivs = f06[f06.index("H I N G E   M O M E N T   D E R I V A T I V E S"):
                     f06.index("C O N T R O L   S U R F A C E   P O S I T I O N")]
        assert "RIGID   RESTRAINED" in derivs
        row = next(l for l in derivs.splitlines() if l.strip().startswith("ANGLEA"))
        assert [float(row[22:35]), float(row[35:48])] == pytest.approx([2.482515e3, 2.417875e3])
        trimmed = f06[f06.index("C O N T R O L   S U R F A C E   P O S I T I O N"):]
        row = next(l for l in trimmed.splitlines() if l.strip().startswith("ELEV"))
        assert [float(row[22:35]), float(row[35:48])] == pytest.approx([4.917114e-1, 5.083026e3])


class TestBoxIds:
    """O4: the AEROF/APRES "BOX ID" was a running index, so row 9 was MSC's box 1100.
    MSC lists the box forces by box ID ("GRID ID" 1000, 1001 ... 1100; AAUG p.237) and
    the pressures by a running index (p.236)."""

    def test_result_carries_nastran_box_ids(self, ha144a):
        result = ha144a[2]
        assert len(result.box_ids) == len(result.box_forces)
        assert result.box_ids[:2] == [1000, 1001] and 1100 in result.box_ids

    def test_aerof_block_prints_them(self, f06):
        block = f06[f06.index("A E R O D Y N A M I C   B O X   P R E S S U R E S"):]
        ids = [int(l.split()[0]) for l in block.splitlines()[3:] if l.strip()
               and l.split()[0].isdigit()]
        assert ids[0] == 1000 and 1100 in ids and 1 not in ids

    @pytest.mark.parametrize("box_id, msc_cp, msc_fz", [
        (1000, 4.784523, 1.196131e3), (1001, 8.703240e-1, 2.175810e2),
        (1100, -1.200071, -3.000177e2),
    ])
    def test_box_values_match_msc_by_box_id(self, ha144a, box_id, msc_cp, msc_fz):
        """AAUG p.236 (pressure coefficients, rows 1, 2 and 9) and p.237 (forces of
        boxes 1000, 1001 and 1100).  The remaining difference is VLM against DLM."""
        result = ha144a[2]
        k = result.box_ids.index(box_id)
        assert result.box_cp[k] == pytest.approx(msc_cp, rel=1e-2)
        assert result.box_forces[k][2] == pytest.approx(msc_fz, rel=1e-2)


class TestDeltaCpFrame:
    """#84: the printed ΔCp is along MSC's element normal (QRG 2024.1 PDF p.1344, CAERO1
    Figure 9-5).  The full-span HA144A port wing (CAERO1 2000) is drawn root to tip,
    so its MSC normal is −z: box 2000 mirrors box 1000 (MSC 4.784523, AAUG p.236) and
    prints the same magnitude with the opposite sign.  ``result.box_cp`` stays along
    sbeam's normal (+z on both wings)."""

    def _printed(self, f06, box_id):
        block = f06[f06.index("A E R O D Y N A M I C   B O X   P R E S S U R E S"):]
        for line in block.splitlines():
            parts = line.split()
            if parts and parts[0] == str(box_id):
                return float(line[14:27])
        raise AssertionError(box_id)

    def test_result_is_along_the_box_normal_on_both_wings(self, ha144a):
        result = ha144a[2]
        k1, k2 = result.box_ids.index(1000), result.box_ids.index(2000)
        assert result.box_msc_sign[k1] == 1.0 and result.box_msc_sign[k2] == -1.0
        assert result.box_cp[k2] == pytest.approx(result.box_cp[k1], rel=1e-9)

    def test_f06_prints_the_port_box_along_msc_normal(self, ha144a, f06):
        result = ha144a[2]
        k1 = result.box_ids.index(1000)
        assert self._printed(f06, 1000) == pytest.approx(result.box_cp[k1], rel=1e-6)
        assert self._printed(f06, 2000) == pytest.approx(-result.box_cp[k1], rel=1e-6)
