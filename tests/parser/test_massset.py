"""MASSCASE card parsing and mass-case resolution (Step 60).

Gates the card round-trip (all three ops), the overlay-marking rule that keeps
overlay CONM2s out of the baseline mass, SCALE, and every negative case the
card contract promises to reject.
"""

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.model.mass_overlay import resolve_mass_case, effective_conm2s


BASE_CONM2S = """
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
CONM2, 11, 1, 0, 10.0
CONM2, 12, 2, 0, 20.0
CONM2, 91, 1, 0, 5.0
CONM2, 92, 2, 0, 7.0
"""


def _parse(extra: str):
    return parse_bulk_data((BASE_CONM2S + extra).splitlines())


# ---- parsing round-trip -----------------------------------------------------

class TestParse:
    def test_all_three_ops(self):
        bulk = _parse("""
MASSCASE, 10, FULLFUEL, 1.25
+, ADD, 91
+, REPLACE, 11, 92
+, DELETE, 12
""")
        ms = bulk.masssets[10]
        assert (ms.sid, ms.label, ms.scale) == (10, "FULLFUEL", 1.25)
        assert ms.add == [91]
        assert ms.replace == [(11, 92)]
        assert ms.delete == [12]

    def test_defaults(self):
        bulk = _parse("MASSCASE, 10\n+, DELETE, 12\n")
        ms = bulk.masssets[10]
        assert ms.label == "MASSCASE 10"
        assert ms.scale == 1.0

    def test_fixed_field(self):
        bulk = _parse(
            "MASSCASE10      EMPTY   2.0\n"
            "+       ADD     91      92\n"
        )
        ms = bulk.masssets[10]
        assert (ms.label, ms.scale, ms.add) == ("EMPTY", 2.0, [91, 92])

    def test_multiple_rows_of_one_op(self):
        bulk = _parse("MASSCASE, 10\n+, ADD, 91\n+, ADD, 92\n")
        assert bulk.masssets[10].add == [91, 92]

    def test_overlay_eids_marked(self):
        bulk = _parse("MASSCASE, 10\n+, ADD, 91\n+, REPLACE, 11, 92\n")
        # ADD target and the REPLACE *overlay* slot are overlay-only; the
        # REPLACE baseline slot (11) stays a baseline card.
        assert bulk.overlay_conm2_eids == {91, 92}

    def test_no_massset_leaves_no_overlays(self):
        bulk = _parse("")
        assert bulk.masssets == {}
        assert bulk.overlay_conm2_eids == set()


# ---- negative cases ---------------------------------------------------------

class TestErrors:
    @pytest.mark.parametrize("deck, msg", [
        ("MASSCASE, 10\n+, DELETE, 777\n", "not defined by any CONM2"),
        ("MASSCASE, 10\n+, REPLACE, 777, 91\n", "not defined by any CONM2"),
        ("MASSCASE, 10\n+, ADD, 777\n", "not defined by any CONM2"),
        ("MASSCASE, 10\n+, SCALEUP, 91\n", "unknown op"),
        ("MASSCASE, 10\n+, REPLACE, 11, 91, 12\n", "odd count"),
        ("MASSCASE, 10\n+, ADD, 91\n+, DELETE, 91\n", "referenced more than once"),
        ("MASSCASE, 10\n+, ADD\n", "lists no CONM2 EIDs"),
        ("MASSCASE, 10, X, -1.0\n+, ADD, 91\n", "SCALE must be >= 0"),
        ("MASSCASE, 10\n+, ADD, 91\nMASSCASE, 10\n+, ADD, 92\n", "Duplicate MASSCASE"),
    ])
    def test_rejected(self, deck, msg):
        with pytest.raises(ValueError, match=msg):
            _parse(deck)

    def test_eid_cannot_be_both_overlay_and_baseline(self):
        # 91 is an ADD overlay in case 10 and a DELETE (baseline) target in 20.
        deck = "MASSCASE, 10\n+, ADD, 91\nMASSCASE, 20\n+, DELETE, 91\n"
        with pytest.raises(ValueError, match="one or the other"):
            _parse(deck)


# ---- mass-case resolution ---------------------------------------------------

def _masses(case_conm2s):
    return {eid: c.m for eid, c in case_conm2s.items()}


class TestResolve:
    def test_baseline_excludes_overlays(self):
        bulk = _parse("MASSCASE, 10\n+, ADD, 91\n+, REPLACE, 11, 92\n")
        case = resolve_mass_case(bulk, None)
        assert case.sid is None and case.label == "BASELINE" and case.scale == 1.0
        assert _masses(case.conm2s) == {11: 10.0, 12: 20.0}

    def test_baseline_without_masssets_is_the_whole_deck(self):
        bulk = _parse("")
        assert resolve_mass_case(bulk, None).conm2s == bulk.conm2s

    def test_add(self):
        bulk = _parse("MASSCASE, 10\n+, ADD, 91, 92\n")
        assert _masses(effective_conm2s(bulk, 10)) == {11: 10.0, 12: 20.0, 91: 5.0, 92: 7.0}

    def test_delete(self):
        # 91/92 are unreferenced here, so they are ordinary baseline masses.
        bulk = _parse("MASSCASE, 10\n+, DELETE, 12\n")
        assert _masses(effective_conm2s(bulk, 10)) == {11: 10.0, 91: 5.0, 92: 7.0}

    def test_replace_swaps_baseline_for_overlay(self):
        bulk = _parse("MASSCASE, 10\n+, REPLACE, 11, 91\n")
        # 11 dropped, overlay 91 in its place; 12/92 are untouched baseline.
        assert _masses(effective_conm2s(bulk, 10)) == {12: 20.0, 91: 5.0, 92: 7.0}

    def test_scale_applies_to_baseline_not_overlay(self):
        bulk = _parse("MASSCASE, 10, HEAVY, 2.0\n+, ADD, 91\n")
        m = _masses(effective_conm2s(bulk, 10))
        # Baseline members doubled; the ADD overlay enters at its card value.
        assert m == {11: 20.0, 12: 40.0, 92: 14.0, 91: 5.0}

    def test_scale_applies_to_inertia_tensor(self):
        bulk = parse_bulk_data((
            "GRID, 1, , 0.0, 0.0, 0.0\n"
            "CONM2, 11, 1, 0, 10.0, 0.0, 0.0, 0.0, , 3.0, 0.0, 4.0, 0.0, 0.0, 5.0\n"
            "CONM2, 12, 1, 0, 1.0\n"
            "MASSCASE, 10, HEAVY, 2.0\n+, DELETE, 12\n"
        ).splitlines())
        c = effective_conm2s(bulk, 10)[11]
        assert (c.m, c.i11, c.i22, c.i33) == (20.0, 6.0, 8.0, 10.0)
        assert (c.x1, c.x2, c.x3) == (0.0, 0.0, 0.0)   # offsets untouched

    def test_case_keeps_deck_order(self):
        bulk = _parse("MASSCASE, 10\n+, ADD, 92\n+, REPLACE, 11, 91\n")
        assert list(effective_conm2s(bulk, 10)) == [12, 91, 92]

    def test_scale_zero_gives_massless_baseline(self):
        bulk = _parse("MASSCASE, 10, MASSLESS, 0.0\n+, ADD, 91\n")
        m = _masses(effective_conm2s(bulk, 10))
        assert m == {11: 0.0, 12: 0.0, 92: 0.0, 91: 5.0}

    def test_unknown_sid_raises(self):
        bulk = _parse("")
        with pytest.raises(ValueError, match="MASSCASE 99 selected"):
            resolve_mass_case(bulk, 99)


class TestOldNameIsRefused:
    """#78: MASSSET is MSC's Mass Combination entry (MSC Nastran 2024.1 QRG PDF p.2018:
    ``MASSSET ID S0 S1 ID1 S2 ID2 ...``; case control p.482).  sbeam's card had the name
    with another layout until it was renamed MASSCASE."""

    def test_msc_bulk_card_is_refused(self):
        """Audit A8: read as label '1.0', scale 1.0, with ID1/S2/ID2 dropped."""
        from sbeam.parser.bdf_reader import parse_bulk_data
        with pytest.raises(ValueError, match=r"MASSSET x1 \(MSC mass combination, not "
                                             r"implemented; sbeam's payload / mass-case card "
                                             r"is MASSCASE"):
            parse_bulk_data(["GRID, 1, , 0., 0., 0.", "MASSSET,11,1.0,1.0,0,1.0,101"])

    def test_old_sbeam_card_is_refused_the_same_way(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        with pytest.raises(ValueError, match="rename the card"):
            parse_bulk_data(["GRID, 1, , 0., 0., 0.", "MASSSET, 10, EMPTY, 1.0"])

    def test_case_control_command_is_refused(self):
        from sbeam.parser.case_control import parse_case_control
        with pytest.raises(ValueError, match="Case control MASSSET selects an MSC mass "
                                             "combination.*MASSCASE = n"):
            parse_case_control(["SOL 144", "SUBCASE 1", "  MASSSET = 11"])

    def test_new_command_selects_the_mass_case(self):
        from sbeam.parser.case_control import parse_case_control
        cc = parse_case_control(["SOL 144", "SUBCASE 1", "  MASSCASE = 11"])
        assert cc.subcases[0].massset_sid == 11
