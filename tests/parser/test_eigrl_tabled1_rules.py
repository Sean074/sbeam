"""EIGRL root selection and TABLED1 evaluation follow NASTRAN, or are refused (#70).

Audit findings S12, S13, A14, P13 (2026-11-16).  Page numbers are PDF pages of the MSC
Nastran 2024.1 Quick Reference Guide: EIGRL p.1801-1803, TABLED1 p.2896-2897.
"""
import warnings

import pytest

from sbeam.model.maneuver import Tabled1
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.solver.maneuver_qs import warn_extrapolated_commands
from sbeam_tools.viewer import sol144_authoring as logic
from tests.samples import sample_decks



class TestEigrl:
    def test_nd_only_is_the_supported_row(self):
        """Table 9-13 (p.1802): V1 blank, V2 blank, ND -> lowest ND roots."""
        e = parse_bulk_data(["EIGRL, 20, , , 10, , , , MAX"]).eigrls[20]
        assert (e.v1, e.v2, e.nd, e.norm) == (None, None, 10, "MAX")

    @pytest.mark.parametrize("card, name", [
        ("EIGRL, 1, 0.1, , 10", "V1=0.1"), ("EIGRL, 1, , 3.2, 10", "V2=3.2"),
        ("EIGRL, 1, 0.1, 3.2, 10", "V1=0.1"),       # the QRG's own example, p.1801
        ("EIGRL, 1, 1.-1, , 10", "V1=0.1"),         # NASTRAN short real: float() failed on it
    ])
    def test_frequency_range_is_refused(self, card, name):
        """V1/V2 were warned and not applied: V1 = 0.1 still returned rigid-body modes."""
        with pytest.raises(ValueError, match=f"EIGRL 1: {name} is not supported"):
            parse_bulk_data([card])

    def test_blank_nd_is_refused(self):
        """MSC returns the lowest root; sbeam returned every mode."""
        with pytest.raises(ValueError, match="EIGRL 1: ND is blank"):
            parse_bulk_data(["EIGRL, 1"])

    def test_nd_must_be_positive(self):
        with pytest.raises(ValueError, match="EIGRL 1: ND=0 must be > 0"):
            parse_bulk_data(["EIGRL, 1, , , 0"])

    def test_norm_must_be_mass_or_max(self):
        """`POINT` was accepted and treated as MASS."""
        with pytest.raises(ValueError, match="EIGRL 1: NORM='POINT' must be MASS or MAX"):
            parse_bulk_data(["EIGRL, 1, , , 4, , , , POINT"])

    def test_norm_case_and_default(self):
        assert parse_bulk_data(["EIGRL, 1, , , 4, , , , max"]).eigrls[1].norm == "MAX"
        assert parse_bulk_data(["EIGRL, 1, , , 4"]).eigrls[1].norm == "MASS"


def _table(*cards):
    return parse_bulk_data(list(cards)).tabled1s[32]


class TestTabled1:
    def test_qrg_example_extrapolates_from_the_end_points(self):
        """p.2896 example: (-3, 6.9) (2, 5.6) (3, 5.6).  Remark 6: "extrapolation outside
        the table using the two starting or end points"."""
        t = _table("TABLED1, 32", "+, -3.0, 6.9, 2.0, 5.6, 3.0, 5.6, ENDT")
        assert t.evaluate(-0.5) == pytest.approx(6.25)            # inside
        assert t.evaluate(-5.0) == pytest.approx(6.9 + 0.26 * 2)  # slope -0.26 carried back
        assert t.evaluate(10.0) == pytest.approx(5.6)             # flat end: held

    def test_a_ramp_keeps_ramping(self):
        """sbeam used to hold 5.0 beyond x = 2."""
        t = _table("TABLED1, 32", "+, 0., 0., 2., 5., ENDT")
        assert t.evaluate(4.0) == pytest.approx(10.0)
        assert t.evaluate(-1.0) == pytest.approx(-2.5)

    @pytest.mark.parametrize("card, name", [("TABLED1, 32, LOG", "XAXIS=LOG"),
                                            ("TABLED1, 32, , LOG", "YAXIS=LOG"),
                                            ("TABLED1, 32, LINEAR, XYZ", "YAXIS=XYZ")])
    def test_log_axes_are_refused(self, card, name):
        """LOG was accepted and evaluated linearly (p.2897 gives the LOG formulas)."""
        with pytest.raises(ValueError, match=f"TABLED1 32: {name} is not supported"):
            _table(card, "+, 1., 1., 2., 5., ENDT")

    def test_linear_is_accepted(self):
        assert _table("TABLED1, 32, LINEAR, LINEAR", "+, 1., 1., 2., 5., ENDT").xs == [1.0, 2.0]


class TestExtrapolationIsAnnounced:
    """MSC gives no message; sbeam held the end value until #70, so it warns."""

    def test_ramp_ending_inside_the_run_warns(self):
        tables = {7: Tabled1(tid=7, xs=[0.0, 0.5], ys=[0.0, 0.1])}
        with pytest.warns(UserWarning, match=r"TABLED1 7 \(ELEV\) covers x = 0 to 0.5 but the "
                                             r"run is t = 0 to 2: beyond x = 0.5 it is "
                                             r"extrapolated at its end slope 0.2"):
            warn_extrapolated_commands([("ELEV", 7)], tables, 0.0, 2.0)

    @pytest.mark.parametrize("xs, ys", [([0.0, 0.5, 2.0], [0.0, 0.1, 0.1]),   # covers the run
                                        ([0.0, 0.5, 0.6], [0.0, 0.1, 0.1])])  # ends flat
    def test_covered_or_flat_ended_tables_are_silent(self, xs, ys):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            warn_extrapolated_commands([("ELEV", 7)], {7: Tabled1(tid=7, xs=xs, ys=ys)}, 0.0, 2.0)

    @pytest.mark.parametrize("deck", sample_decks("*mloads*.bdf"), ids=lambda p: p.name)
    def test_no_repo_command_table_is_extrapolated_on_a_slope(self, deck):
        """So no shipped transient result moved with #70."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _cc, bulk = parse_bdf(str(deck))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for mloads in bulk.mloads.values():
                window = bulk.mldtimes[mloads.mldtime]
                commands = bulk.mldcomds[mloads.mldcomd].commands if mloads.mldcomd else []
                warn_extrapolated_commands(commands, bulk.tabled1s, window.t0, window.tend)


@pytest.mark.parametrize("points", [
    logic.gen_step(0.1, 0.0, 0.5), logic.gen_ramp(0.1, 0.3, 0.0, 0.5),
    logic.gen_cosine_ramp(0.0, 1.0, 0.0, 1.0), logic.gen_doublet(0.1, 0.5, 0.2, 1.0),
], ids=["step", "ramp", "cosine", "doublet"])
def test_generated_shapes_hold_their_last_value(points):
    """Each viewer generator ends with two points of equal y, so the table is flat
    beyond its end under linear extrapolation."""
    table = Tabled1(tid=1, xs=[p[0] for p in points], ys=[p[1] for p in points])
    assert table.end_slopes()[1] == 0.0
    assert table.evaluate(table.xs[-1] + 100.0) == table.ys[-1]
