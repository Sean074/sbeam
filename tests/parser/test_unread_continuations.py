"""No card line is dropped silently: a handler reads every line it is given, or the card is refused (#63).

Invariant gate for the defect class: every keyword registered as single-line (FIELD) or
one-continuation (CONT) refuses a card carrying data on a line it does not read.  The
cards the 2026-11-16 audit found dropping lines are then read in full or refused field by
field.  QRG pages are PDF pages of the MSC Nastran 2024.1 Quick Reference Guide.
"""
import pytest

from sbeam.parser import bdf_reader
from sbeam.parser.bdf_reader import _read_cards


@pytest.mark.parametrize("keyword", sorted(bdf_reader._FIELD_HANDLERS))
def test_single_line_cards_refuse_a_continuation(keyword):
    with pytest.raises(ValueError, match=f"{keyword} 1: continuation line 1 .* is not read"):
        _read_cards([f"{keyword},1", "+,1.0"])


@pytest.mark.parametrize("keyword", sorted(bdf_reader._CONT_HANDLERS))
def test_one_continuation_cards_refuse_a_second(keyword):
    with pytest.raises(ValueError, match=f"{keyword} 1: continuation line 2 .* is not read"):
        _read_cards([f"{keyword},1", "+,1.0", "+,2.0"])


def test_blank_continuation_rows_are_harmless():
    bulk = _read_cards(["GRID,1,,0.,0.,0.", "+"])
    assert list(bulk.grids) == [1]


def test_free_field_overflow_on_a_single_line_card_is_refused():
    """Audit S7: FORCE,...,1.,,7. lost the 7. silently (field 9 blank, 7. runs on)."""
    with pytest.raises(ValueError, match=r"FORCE 1: continuation line 1 \(7\.\)"):
        _read_cards(["FORCE,1,2,0,1.,0.,0.,1.,,7."])


class TestLoad:
    def test_every_continuation_is_read(self):
        """Audit S4: a 3-line LOAD with 9 components kept 6 (QRG p.2008 '-etc.-')."""
        load = _read_cards(["LOAD,10,1.,1.,1,1.,2,1.,3",
                            "+,1.,4,1.,5,1.,6,1.,7",
                            "+,1.,8,1.,9"]).loads[10]
        assert load.components == [(1.0, i) for i in range(1, 10)]


class TestPbar:
    BASE = ["PBAR,1,1,2.,1.,1.,1.", "+,0.,0.,0.,0.,0.,0.,0.,0."]

    def test_blank_third_line_is_accepted(self):
        assert 1 in _read_cards(self.BASE + ["+,,,0."]).pbars

    @pytest.mark.parametrize("line, match", [
        ("+,.5,.5", "K1/K2 shear factors are not supported"),
        ("+,,,1.5", r"I12 = 1.5 \(coupled bending\)"),
        ("+,,,,9.", "fields after I12"),
    ], ids=["K1K2", "I12", "extra"])
    def test_third_line_values_sbeam_cannot_honour(self, line, match):
        """Audit S5: K1/K2 and I12 vanished with the line (QRG p.2431)."""
        with pytest.raises(ValueError, match=f"PBAR 1: {match}"):
            _read_cards(self.BASE + [line])

    def test_fourth_line_is_refused(self):
        with pytest.raises(ValueError, match="more than three lines"):
            _read_cards(self.BASE + ["+", "+,1."])


class TestPbush:
    def test_k_on_the_first_line(self):
        p = _read_cards(["PBUSH,1,K,1.,2.,3.,4.,5.,6."]).pbushs[1]
        assert (p.k1, p.k2, p.k3, p.k4, p.k5, p.k6) == (1., 2., 3., 4., 5., 6.)

    def test_flags_in_any_order_k_on_a_continuation(self):
        """QRG p.2494 remark 6; RCV is output only, zero damping is harmless."""
        p = _read_cards(["PBUSH,1,RCV,7.3,3.3", "+,,B,0.", "+,,K,4.35,2.4"]).pbushs[1]
        assert (p.k1, p.k2, p.k3) == (4.35, 2.4, 0.0)

    @pytest.mark.parametrize("lines, match", [
        (["PBUSH,1,M,5."], r"M \(lumped mass"),
        (["PBUSH,1,K,1.", "+,,GE,.06"], r"GE \(structural damping\)"),
        (["PBUSH,1,K,1.", "+,,B,2.3"], r"B \(viscous damping\)"),
        (["PBUSH,1,T,1.e-5"], r"T \(thermal"),
        (["PBUSH,1,X,1."], "unknown flag 'X'"),
        (["PBUSH,1,K,1.", "+,,K,2."], "flag K given twice"),
        (["PBUSH,1,K,1.", "+,,,2."], "a line with values has no K/B/GE/RCV/M/T flag"),
    ], ids=["M", "GE", "B", "T", "unknown", "twice", "no-flag"])
    def test_flags_sbeam_cannot_honour(self, lines, match):
        """Audit S6: PBUSH 1 M 5. gave K1 = 5 (mass read as stiffness); GE lines were K."""
        with pytest.raises(ValueError, match=f"PBUSH 1: {match}"):
            _read_cards(lines)


class TestCardsTheAuditFound:
    def test_aesurf_noldw_is_refused(self):
        """Audit A4: field 9 (LDW) was never read (QRG p.1155–1156)."""
        with pytest.raises(ValueError, match="AESURF 77: LDW = 'NOLDW' is not supported"):
            _read_cards(["AESURF,77,AIL,77,77,,,0.5,NOLDW"])

    def test_aesurf_limits_line_is_refused(self):
        """Audit A4: CREFC/CREFS/PLLIM/PULIM were dropped with the continuation."""
        with pytest.raises(ValueError, match="AESURF 77: continuation line 1"):
            _read_cards(["AESURF,77,AIL,77,77", "+,10.,180.,-0.1,0.1"])

    def test_eigrl_option_line_is_refused(self):
        """Audit S13: NORM=MAX on a continuation was ignored and MASS used."""
        with pytest.raises(ValueError, match="EIGRL 1: continuation line 1 .*NORM=MAX"):
            _read_cards(["EIGRL,1,,,6", "+,NORM=MAX"])

    def test_msc_two_line_monpnt1_is_read(self):
        """Audit A9/P10: MSC's MONPNT1 data line was dropped; refused by #63, read by #86."""
        bulk = _read_cards(["MONPNT1,WRBM,Wing root bending", "+,123456,WING,0,0.,10.,0."])
        assert (bulk.monpnt1s["WRBM"].comp, bulk.monpnt1s["WRBM"].y) == ("WING", 10.0)

    def test_a_third_monpnt1_line_is_refused(self):
        with pytest.raises(ValueError, match="MONPNT1 WRBM: continuation line 2"):
            _read_cards(["MONPNT1,WRBM,Wing root bending", "+,123456,WING,0,0.,10.,0.",
                         "+,1"])
