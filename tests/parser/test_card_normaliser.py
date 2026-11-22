"""Every card is normalised to NASTRAN's 10-field layout before a handler sees it (#64).

Free-field lines longer than 10 fields run on into automatic continuations, a field-10
token is a continuation marker only when it starts with + or * and is not a number, and
large-field (``GRID*``) cards are read in 16-column fields.  Each case is the QRG's own
example or a card the 2026-11-16 audit found misread; QRG pages are PDF pages of the MSC
Nastran 2024.1 Quick Reference Guide.
"""
import pytest

from sbeam.parser.bdf_reader import _read_cards
from sbeam.parser.bulk_fields import iter_cards


def _cards(*lines: str):
    return list(iter_cards(list(lines)))


class TestShape:
    def test_every_line_has_nine_fields(self):
        [(kw, fields, conts)] = _cards("GRID,2,,1.0", "+,9")
        assert kw == "GRID"
        assert fields == ["GRID", "2", "", "1.0", "", "", "", "", ""]
        assert conts == [["+", "9", "", "", "", "", "", "", ""]]

    def test_fixed_field_drops_field_10(self):
        line = "PBAR    39      6       2.9     1.86    2.92    .48             +PB1"
        [(_, fields, conts)] = _cards(line, "+PB1    0.      0.")
        assert fields[1:5] == ["39", "6", "2.9", "1.86"] and len(fields) == 9
        assert conts[0][1:3] == ["0.", "0."]


class TestFreeFieldOverflow:
    def test_qrg_spc1_automatic_continuation(self):
        """QRG p.1049: SPC1,100,12456,1,2,...,10 continues onto a second line."""
        [(_, fields, conts)] = _cards("SPC1,100,12456,1,2,3,4,5,6,7,8,9,10")
        assert fields[1:] == ["100", "12456", "1", "2", "3", "4", "5", "6"]
        assert conts == [["+", "7", "8", "9", "10", "", "", "", ""]]
        bulk = _read_cards(["SPC1,100,12456,1,2,3,4,5,6,7,8,9,10"])
        assert bulk.spc1s[100][0].grids == list(range(1, 11))

    def test_conm2_inertia_lands_where_nastran_puts_it(self):
        """Audit S7: this line used to give I21 = 1, I31 = 2; NASTRAN reads I11, I22, I33."""
        c = _read_cards(["CONM2,1,2,,10.,0.,0.,0.,,1.,0.,2.,0.,0.,3."]).conm2s[1]
        assert (c.i11, c.i21, c.i22, c.i31, c.i32, c.i33) == (1.0, 0.0, 2.0, 0.0, 0.0, 3.0)

    def test_conm2_field_9_must_be_blank(self):
        """sbeam once read I11 from field 9; NASTRAN leaves it blank (QRG p.1449)."""
        with pytest.raises(ValueError, match="CONM2 1: field 9 must be blank"):
            _read_cards(["CONM2,1,2,,10.,0.,0.,0.,5."])

    def test_cbar_pin_flags_after_blank_field_9(self):
        """Audit S7: CBAR,...,,56,56 dropped PA/PB."""
        cbar = _read_cards(["CBAR,1,1,1,2,0.,1.,0.,,56,56"]).cbars[1]
        assert (cbar.pa, cbar.pb) == ("56", "56")

    def test_overflow_rows_then_physical_continuation(self):
        """A physical continuation starts a new row after the overflow row."""
        bulk = _read_cards(["SET1,7,1,2,3,4,5,6,7,8,9", "+,10,11"])
        assert bulk.set1s[7].grids == list(range(1, 12))


class TestFieldTenMarker:
    @pytest.mark.parametrize("parent, cont", [
        ("LOAD,10,1.,1.,1,1.,2,1.,3,+L1", "+L1,1.,4"),
        ("LOAD,10,1.,1.,1,1.,2,1.,3,+", "+,1.,4"),
        ("LOAD,10,1.,1.,1,1.,2,1.,3", ",1.,4"),
    ], ids=["named", "plus", "leading-comma"])
    def test_marker_forms(self, parent, cont):
        """QRG p.1049–1050 (MATT9): a marker in field 10, or none, all give one card."""
        load = _read_cards([parent, cont]).loads[10]
        assert load.components == [(1.0, 1), (1.0, 2), (1.0, 3), (1.0, 4)]

    def test_signed_number_in_field_10_is_data(self):
        """+8 is a number, so it runs on as data rather than being taken for a marker."""
        assert _read_cards(["SET1,7,1,2,3,4,5,6,7,+8"]).set1s[7].grids == list(range(1, 9))


class TestLargeField:
    # QRG p.1048/1052: GRID 2, CP blank, 1.0 -2.0 3.0, CD blank, PS 136
    SMALL = "GRID,2,,1.0,-2.0,3.0,,136"
    FIXED = ("GRID*   " + "2".rjust(16) + "".rjust(16) + "1.0".rjust(16) + "-2.0".rjust(16)
             + "*GRID10",
             "*GRID10 " + "3.0".rjust(16) + "".rjust(16) + "136".rjust(16))
    FREE = ("GRID*,2,,1.0,-2.0,*GRID10", "*GRID10,3.0,,136")

    @pytest.mark.parametrize("lines", [FIXED, FREE], ids=["fixed", "free"])
    def test_large_field_grid_equals_small_field(self, lines):
        assert _read_cards(list(lines)).grids == _read_cards([self.SMALL]).grids

    def test_large_then_small_mid_row_is_refused(self):
        with pytest.raises(ValueError, match="half a large-field row"):
            _cards("GRID*,2,,1.0,-2.0", "+,3.0,,136")


def test_orphan_continuation_is_refused():
    with pytest.raises(ValueError, match="Continuation line with no card before it"):
        _cards("+,1.,4", "GRID,1,,0.,0.,0.")


@pytest.mark.parametrize("fmt, lines", [
    ("fixed", ["TRIMVAR 1       ANGLEA                                          0.0"]),
    ("free", ["TRIMVAR,1,ANGLEA,,,,,,0.0"]),
])
def test_trimvar_blank_bounds_are_open_in_every_format(fmt, lines):
    """Audit P6: fixed field gave lb = ub = 0.0, pinning the variable (#77 part 1)."""
    tv = _read_cards(lines).trimvars[1]
    assert (tv.lb, tv.ub) == (-1.0e30, 1.0e30)


def test_diverg_blank_nroot_defaults_to_one():
    """QRG p.1603: NROOT Default = 1, in fixed and free field alike."""
    assert _read_cards(["DIVERG  70              0.      .8"]).divergs[70].nroots == 1
