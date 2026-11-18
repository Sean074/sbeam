"""CBAR and CROD field rules (#67).

MSC Nastran 2024.1 Quick Reference Guide, PDF pages: CBAR p.1360-1363, CROD p.1522.
Audit findings S2, S17, P2, P7, N1 (2026-11-16).
"""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

_BASE = ["GRID, 1, , 0., 0., 0.", "GRID, 2, , 1., 0., 0.", "GRID, 13, , 0., 1., 0.",
         "MAT1, 1, 2.e11, , .3", "PBAR, 1, 1, .01, 1.e-6, 1.e-6, 1.e-6",
         "PBAR, 7, 1, .01, 1.e-6, 1.e-6, 1.e-6", "PROD, 8, 1, 1.e-4"]


def _parse(*cards):
    return parse_bulk_data(_BASE + list(cards))


class TestOffsets:
    """p.1360-1361: continuation fields 4-9 are W1A W2A W3A W1B W2B W3B."""

    def test_audit_probe_is_refused(self):
        """W3A = W3B = 5. used to parse with the offsets gone."""
        with pytest.raises(ValueError, match="CBAR 1: offset W3A=5. is not supported"):
            _parse("CBAR, 1, 1, 1, 2, 0., 1., 0.", "+, , , , , 5., , , 5.")

    @pytest.mark.parametrize("k, name", enumerate(["W1A", "W2A", "W3A", "W1B", "W2B", "W3B"]))
    def test_each_offset_field_is_refused(self, k, name):
        cont = ["+", "", ""] + [""] * 6
        cont[3 + k] = "0.25"
        with pytest.raises(ValueError, match=f"CBAR 1: offset {name}=0.25 is not supported"):
            _parse("CBAR, 1, 1, 1, 2, 0., 1., 0.", ",".join(cont))

    def test_zero_offsets_and_pin_flags_are_accepted(self):
        bar = _parse("CBAR, 1, 1, 1, 2, 0., 1., 0.", "+, 56, 5, 0., 0., 0., 0., 0., 0.").cbars[1]
        assert (bar.pa, bar.pb) == ("56", "5")


class TestOfft:
    """p.1363 remark 7: GGG BGG GGO BGO GOG BOG GOO BOO."""

    @pytest.mark.parametrize("code", ["GGG", "BGG", "GGO", "BGO", "GOG", "BOG", "GOO", "BOO", "bgg"])
    def test_the_eight_codes_are_accepted(self, code):
        assert _parse(f"CBAR, 1, 1, 1, 2, 0., 1., 0., {code}").cbars[1].offt == code.upper()

    def test_blank_is_ggg(self):
        assert _parse("CBAR, 1, 1, 1, 2, 0., 1., 0.").cbars[1].offt == "GGG"

    @pytest.mark.parametrize("code", ["XYZ", "GG", "OGG", "2", "EEE"])
    def test_anything_else_is_refused(self, code):
        """`2` is the COSMIC NASTRAN-95 F flag that sits in this field in old decks."""
        with pytest.raises(ValueError, match=f"CBAR 1: OFFT='{code}' is not one of"):
            _parse(f"CBAR, 1, 1, 1, 2, 0., 1., 0., {code}")

    def test_basic_orientation_is_allowed_on_a_grid_with_a_cd(self):
        """#65 refuses a vector given in GA's displacement system; B.. gives it in basic."""
        cards = ["CORD2R, 5, 0, 0., 0., 0., 0., 0., 1.", "+, 0., 1., 0.",
                 "GRID, 3, , 2., 0., 0., 5"]
        assert _parse(*cards, "CBAR, 1, 1, 3, 2, 0., 1., 0., BGG").cbars[1].offt == "BGG"
        with pytest.raises(ValueError, match=r"CBAR 1 takes its orientation vector at this grid "
                                             r"\(GA, OFFT=GGG\)"):
            _parse(*cards, "CBAR, 1, 1, 3, 2, 0., 1., 0.")


class TestG0IsDecidedByFieldSix:
    """p.1362: "If an integer is specified in field 6, then G0 is used; if field 6 is
    blank or real, then X1, X2, X3 is used."  pyNastran reads it the same way."""

    @pytest.mark.parametrize("orientation", ["13", "13, 0, 0", "13, 0., 0.", "0, 1, 0"])
    def test_integer_field_six_is_g0(self, orientation):
        """`13 0 0` used to become the vector (13, 0, 0)."""
        first = orientation.split(",")[0]
        with pytest.raises(ValueError, match=f"CBAR 1: field 6 is the integer {first}, which "
                                             "NASTRAN reads as the grid G0"):
            _parse(f"CBAR, 1, 1, 1, 2, {orientation}")

    @pytest.mark.parametrize("orientation, vector", [
        ("0., 1., 0.", (0.0, 1.0, 0.0)), ("1.0, 0, 0", (1.0, 0.0, 0.0)), (", 1., ", (0.0, 1.0, 0.0)),
    ])
    def test_real_or_blank_field_six_is_a_vector(self, orientation, vector):
        bar = _parse(f"CBAR, 1, 1, 1, 2, {orientation}").cbars[1]
        assert (bar.x1, bar.x2, bar.x3) == vector


class TestPidDefaultsToEid:
    def test_cbar(self):
        """p.1360: "Default = EID unless BAROR entry has nonzero entry in field 3"."""
        assert _parse("CBAR, 7, , 1, 2, 0., 1., 0.").cbars[7].pid == 7

    def test_crod(self):
        """p.1522: "Default = EID"."""
        assert _parse("CROD, 8, , 1, 2").crods[8].pid == 8

    def test_default_pid_must_still_exist(self):
        with pytest.raises(ValueError, match="CBAR 9: property PID=9 not found"):
            _parse("CBAR, 9, , 1, 2, 0., 1., 0.")
