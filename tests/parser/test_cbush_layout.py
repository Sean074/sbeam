"""CBUSH is read in MSC's layout (#62).

MSC Nastran 2024.1 Quick Reference Guide, PDF p.1378-1380:
``CBUSH EID PID GA GB GO/X1 X2 X3 CID`` / ``S OCID S1 S2 S3``.  sbeam read field 7 as
CID and the orientation vector from the continuation, so a NASTRAN card's GO and CID
were dropped and the default orientation was used without a message.  pyNastran reads
the card as MSC does (cross-parse gate in tests/compat).
"""
import numpy as np
import pytest

from sbeam.assembly.stiffness import cbush_stiffness_global
from sbeam.parser.bdf_reader import parse_bulk_data

_K = (1.0e6, 2.0e6, 3.0e6)
_BASE = ["GRID, 1, , 0., 0., 0.", "GRID, 2, , 2., 0., 0.", "GRID, 3, , 0., 1., 0.",
         "GRID, 100, , 0., 0., 0.", "GRID, 75, , 0., 5., 0.",
         "PBUSH, 40, K, 1.e6, 2.e6, 3.e6", "PBUSH, 6, K, 1.e6, 2.e6, 3.e6",
         # CID 7: 90 deg about basic z (x' = basic y, y' = -basic x)
         "CORD2R, 7, 0, 0., 0., 0., 0., 0., 1.", "+, 0., 1., 0."]


def _parse(*cards):
    return parse_bulk_data(_BASE + list(cards))


def _translational_k(bulk, eid):
    bush = bulk.cbushs[eid]
    return cbush_stiffness_global(bush, bulk.grids, bulk.pbushs, bulk.cord2rs)[:3, :3]


class TestIssueProbes:
    """The three probe rows of #62."""

    def test_go_form_is_refused_naming_go(self):
        """`CBUSH 4 40 1 2 3` was accepted with GO read as S and ignored."""
        with pytest.raises(ValueError, match="CBUSH 4: field 6 is the integer 3, which NASTRAN "
                                             "reads as the grid GO"):
            _parse("CBUSH, 4, 40, 1, 2, 3")

    def test_cid_in_field_nine_is_read(self):
        """CID 7 in field 9 was ignored."""
        assert _parse("CBUSH, 4, 40, 1, 2, , , , 7").cbushs[4].cid == 7

    def test_vector_in_fields_six_to_eight_is_read(self):
        """It was refused as `CID=1. not supported`, naming the wrong field."""
        bush = _parse("CBUSH, 4, 40, 1, 2, 0., 1., 0.").cbushs[4]
        assert (bush.x1, bush.x2, bush.x3, bush.cid) == (0.0, 1.0, 0.0, None)


class TestQrgExamples:
    """The four examples of QRG p.1378."""

    def test_example_1_go(self):
        with pytest.raises(ValueError, match="CBUSH 39: field 6 is the integer 75"):
            _parse("CBUSH   39      6       1       100     75")

    def test_example_2_grounded_with_cid_0(self):
        bush = _parse("CBUSH   39      6       1                                       0").cbushs[39]
        assert (bush.gb, bush.cid) == (None, 0)

    def test_example_3_cid_6(self):
        bulk = _parse("CBUSH   39      6       1                                       6",
                      "CORD2R, 6, 0, 0., 0., 0., 0., 0., 1.", "+, 1., 0., 0.")
        assert bulk.cbushs[39].cid == 6

    def test_example_4_spring_offset_is_refused(self):
        with pytest.raises(ValueError, match="CBUSH 39: S=0.25 is not supported"):
            _parse("CBUSH   39      6       1       100",
                   "        0.25    10      0.      10.     10.")


class TestFieldRules:
    def test_pid_defaults_to_eid(self):
        """p.1378: "Default = EID"."""
        assert _parse("CBUSH, 40, , 1, 2, 0., 1., 0.").cbushs[40].pid == 40

    def test_gb_zero_is_grounded(self):
        """p.1378: "GB >= 0 or blank"."""
        assert _parse("CBUSH, 4, 40, 1, 0, , , , 0").cbushs[4].gb is None

    def test_default_s_and_ocid_are_accepted(self):
        bush = _parse("CBUSH, 4, 40, 1, 2, 0., 1., 0.", "+, 0.5, -1").cbushs[4]
        assert bush.x2 == 1.0

    def test_ocid_is_refused(self):
        with pytest.raises(ValueError, match="CBUSH 4: OCID=10 is not supported"):
            _parse("CBUSH, 4, 40, 1, 2, 0., 1., 0.", "+, , 10, 0., 1., 1.")

    def test_the_old_sbeam_layout_is_refused_with_the_way_out(self):
        """Vector on the continuation: its first value now sits in the S field."""
        with pytest.raises(ValueError, match="CBUSH 4: S=0. is not supported.*orientation vector "
                                             "X1 X2 X3 on this line; it now goes in fields 6-8"):
            _parse("CBUSH, 4, 40, 1, 2", "+, 0., 1., 0.")

    def test_grounded_needs_a_cid(self):
        """p.1379 remark 6."""
        with pytest.raises(ValueError, match="CBUSH 4: GB is blank .* so CID must be specified"):
            _parse("CBUSH, 4, 40, 1")

    def test_coincident_grids_need_a_cid(self):
        with pytest.raises(ValueError, match="CBUSH 4: GA and GB are 0 apart"):
            _parse("CBUSH, 4, 40, 1, 100, 0., 1., 0.")

    def test_no_orientation_with_lateral_stiffness_is_refused(self):
        """p.1379 remark 5: valid only with K1 and K4; sbeam picked basic y."""
        with pytest.raises(ValueError, match="CBUSH 4: no orientation vector and no CID.*PBUSH 40 "
                                             "has K2, K3"):
            _parse("CBUSH, 4, 40, 1, 2")

    def test_no_orientation_with_axial_stiffness_only_is_accepted(self):
        bulk = _parse("PBUSH, 41, K, 1.e6, , , 5.e3", "CBUSH, 4, 41, 1, 2")
        assert _translational_k(bulk, 4) == pytest.approx(np.diag([1.0e6, 0.0, 0.0]))


class TestSpringAxes:
    """With unequal K1, K2, K3 the axes decide the answer."""

    def test_vector_puts_v_in_the_element_xy_plane(self):
        """Remark 4: x = GA-GB = basic x; v = basic z, so y = basic z and z = -basic y."""
        bulk = _parse("CBUSH, 4, 40, 1, 2, 0., 0., 1.")
        assert _translational_k(bulk, 4) == pytest.approx(np.diag([_K[0], _K[2], _K[1]]))

    def test_cid_0_is_basic_whatever_the_line_ga_gb(self):
        """Remark 3: CID >= 0 overrides the line GA-GB; grid 3 is along basic y."""
        bulk = _parse("CBUSH, 4, 40, 1, 3, , , , 0")
        assert _translational_k(bulk, 4) == pytest.approx(np.diag(_K))

    def test_rotated_cid_gives_the_rotated_stiffness(self):
        """Remark 3 with CID 7: K1 along basic y, K2 along basic x."""
        bulk = _parse("CBUSH, 4, 40, 1, , , , , 7")
        assert _translational_k(bulk, 4) == pytest.approx(np.diag([_K[1], _K[0], _K[2]]))

    def test_cid_overrides_the_vector(self):
        bulk = _parse("CBUSH, 4, 40, 1, 2, 0., 0., 1., 7")
        assert _translational_k(bulk, 4) == pytest.approx(np.diag([_K[1], _K[0], _K[2]]))
