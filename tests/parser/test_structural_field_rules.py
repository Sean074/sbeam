"""Structural field rules that were not enforced (#68).

Audit findings S8, S9, S10, S11, S20, P3, P14 (2026-11-16).  Page numbers are PDF pages
of the MSC Nastran 2024.1 Quick Reference Guide (QRG).
"""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

_GRIDS = ["GRID, 1, , 0., 0., 0.", "GRID, 2, , 1., 0., 0.", "GRID, 3, , 2., 0., 0."]


def _parse(*cards):
    return parse_bulk_data(_GRIDS + list(cards))


class TestMat1Blanks:
    """QRG p.2020-2021 remark 2."""

    def _mat(self, card):
        m = _parse(card).mat1s[1]
        return m.E, m.G, m.nu

    def test_blank_e_is_computed(self):
        """Audit S8: `MAT1,1,,4.e6,0.3` gave E = 0.0; E = 2(1+NU)G = 1.04e7."""
        assert self._mat("MAT1, 1, , 4.e6, 0.3") == pytest.approx((1.04e7, 4.0e6, 0.3))

    def test_blank_g_is_computed(self):
        assert self._mat("MAT1, 1, 1.04e7, , 0.3") == pytest.approx((1.04e7, 4.0e6, 0.3))

    def test_blank_nu_is_computed(self):
        assert self._mat("MAT1, 1, 1.04e7, 4.e6") == pytest.approx((1.04e7, 4.0e6, 0.3))

    def test_qrg_example(self):
        """p.2020: MAT1 17 3.+7 (blank) 0.33 4.28 6.5-6 5.37+2 0.23."""
        e, g, nu = self._mat("MAT1, 1, 3.+7, , 0.33, 4.28, 6.5-6, 5.37+2, 0.23")
        assert (e, nu) == (3.0e7, 0.33) and g == pytest.approx(3.0e7 / 2.66)

    @pytest.mark.parametrize("card, expected", [
        ("MAT1, 1, 1.e7", (1.0e7, 0.0, 0.0)), ("MAT1, 1, , 4.e6", (0.0, 4.0e6, 0.0)),
    ])
    def test_nu_and_one_modulus_blank_are_both_zero(self, card, expected):
        """ "If NU and E, or NU and G, are both blank, then both are set to 0.0." """
        assert self._mat(card) == expected

    @pytest.mark.parametrize("card", ["MAT1, 1, , , 0.3", "MAT1, 1"])
    def test_e_and_g_both_blank_is_refused(self, card):
        with pytest.raises(ValueError, match="MAT1 1: E and G may not both be blank"):
            _parse(card)

    @pytest.mark.parametrize("card, name", [
        ("MAT1, 1, -1., 4.e6, 0.3", "E=-1"), ("MAT1, 1, 0., 4.e6, 0.3", "E=0"),
        ("MAT1, 1, 1.e7, 0., 0.3", "G=0"), ("MAT1, 1, 1.e7, 4.e6, 0.6", "NU=0.6"),
        ("MAT1, 1, 1.e7, 4.e6, -1.", "NU=-1"),
    ])
    def test_values_outside_the_qrg_ranges_are_refused(self, card, name):
        """E, G: "Real > 0.0 or blank"; NU: "-1.0 < Real < 0.5 or blank" (p.2020)."""
        with pytest.raises(ValueError, match=f"MAT1 1: {name} must be"):
            _parse(card)


class TestRbarDependentComponents:
    """QRG p.2691-2692 remark 4: every DOF outside CNA/CNB is dependent only "if both CMA
    and CMB are zero or blank"."""

    @pytest.mark.parametrize("card", [
        "RBAR, 1, 1, 2, 123456", "RBAR, 1, 1, 2, 123456, , 0, 0", "RBAR, 1, 1, 2, , , , 123456",
        "RBAR, 1, 1, 2",
    ])
    def test_all_six_dependent_is_accepted(self, card):
        assert _parse(card).rbars[1].cna == "123456"

    @pytest.mark.parametrize("card", ["RBAR, 1, 1, 2, 123456, , , 123",
                                      "RBAR, 1, 1, 2, 123456, , 123"])
    def test_partial_dependent_set_is_refused(self, card):
        """Audit S9: CMB = 123 still made all six GB DOFs dependent."""
        with pytest.raises(ValueError, match="RBAR 1: CMA=.* selects a partial set"):
            _parse(card)


class TestComponentFields:
    @pytest.mark.parametrize("ps", ["7", "0", "12a", "11"])
    def test_grid_ps_must_be_digits_one_to_six(self, ps):
        """QRG p.1944.  Audit S10: PS = 7 constrained T1 of the next grid."""
        with pytest.raises(ValueError, match=f"GRID 5 PS: invalid DOF string '{ps}'"):
            _parse(f"GRID, 5, , 0., 0., 0., , {ps}")

    def test_grid_ps_is_kept(self):
        assert _parse("GRID, 5, , 0., 0., 0., , 136").grids[5].ps == "136"

    @pytest.mark.parametrize("c", ["0", "7", "33"])
    def test_suport_c_must_be_unique_digits_one_to_six(self, c):
        """QRG p.2870.  C = 0 indexed R3 of the previous grid."""
        with pytest.raises(ValueError, match=f"SUPORT grid 1: invalid DOF string '{c}'"):
            _parse(f"SUPORT, 1, {c}")

    def test_suport_reads_four_pairs(self):
        """QRG p.2870: ID1 C1 ... ID4 C4."""
        sup = _parse("SUPORT, 1, 123, 2, 456, 3, 1, 1, 5").supports
        assert [(s.gid, s.dofs) for s in sup] == [(1, "123"), (2, "456"), (3, "1"), (1, "5")]

    def test_suport_pair_after_a_blank_pair_is_refused(self):
        """`SUPORT 1 123 _ _ 2 456` dropped grid 2."""
        with pytest.raises(ValueError, match=r"SUPORT: blank ID in pair 2 with data after it \(2\)"):
            _parse("SUPORT, 1, 123, , , 2, 456")


class TestEnforcedDisplacement:
    @pytest.mark.parametrize("card, grid", [("SPC, 1, 1, 3, 0.5", 1),
                                            ("SPC, 1, 1, 3, 0., 2, 3, 0.1", 2)])
    def test_spc_d_is_refused_at_parse(self, card, grid):
        """Audit S11: SOL 144 and MLOADS took D = 0 without a message."""
        with pytest.raises(ValueError, match=f"SPC 1: enforced displacement D=.* on grid {grid}"):
            _parse(card)

    def test_zero_d_is_accepted(self):
        assert _parse("SPC, 1, 1, 3, 0., 2, 3, 0.").spcs[1][0].g2 == 2


class TestLoadSets:
    _F = ["FORCE, 10, 2, , 1., 0., 0., 1.", "FORCE, 11, 2, , 1., 0., 0., 1."]

    def test_repeated_li_is_refused(self):
        """QRG p.2008 remark 2: "Load set IDs (Li) must be unique"; it was summed twice."""
        with pytest.raises(ValueError, match="LOAD 20: load set 10 is listed twice"):
            _parse(*self._F, "LOAD, 20, 1., 1., 10, 2., 10")

    def test_distinct_li_are_accepted(self):
        assert _parse(*self._F, "LOAD, 20, 1., 1., 10, 2., 11").loads[20].components == [
            (1.0, 10), (2.0, 11)]

    @pytest.mark.parametrize("pair", [", 10", "1.,"])
    def test_half_a_pair_is_refused(self, pair):
        """A scale with no set, or a set with no scale, was skipped."""
        with pytest.raises(ValueError, match="LOAD 20: pair 2 has S="):
            _parse(*self._F, f"LOAD, 20, 1., 1., 11, {pair}")

    @pytest.mark.parametrize("simple", ["FORCE, 10, 2, , 1., 0., 0., 1.",
                                        "MOMENT, 10, 2, , 1., 0., 0., 1."])
    def test_grav_sharing_a_simple_load_sid_is_refused(self, simple):
        """QRG p.1941 GRAV remark 3; the two were summed."""
        with pytest.raises(ValueError, match="GRAV 10: a (FORCE|MOMENT) card has the same SID"):
            _parse(simple, "GRAV, 10, , 9.81, 0., 0., -1.")

    def test_grav_combined_through_a_load_card_is_accepted(self):
        bulk = _parse(self._F[0], "GRAV, 12, , 9.81, 0., 0., -1.", "LOAD, 20, 1., 1., 10, 1., 12")
        assert bulk.loads[20].components == [(1.0, 10), (1.0, 12)]
