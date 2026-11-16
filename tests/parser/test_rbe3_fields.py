"""#59 gate: RBE3 fields are read strictly by field type, and nothing is skipped.

Before #59 the RBE3 handler guessed where groups started (a field with ``.``/``e`` is a
weight) and skipped any field that was not an integer. A typo grid vanished, a UM
section became independent grids, ALPHA was dropped, and REFC/Ci were never checked as
DOF strings (a REFC digit 7 constrained DOF 1 of the next grid in the index).

NASTRAN reads the groups the same way: a real starts a group, the next field is C, and
integers after it are grids. So an *integer* weight after a group's grids reads as
another grid in NASTRAN too; only an integer in the first WT position is a type error.
That case is pinned below and documented in the card reference.
"""

import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

_GRIDS = [f"GRID, {g}, , {g}.0, 0.0, 0.0" for g in (*range(1, 13), 123)]


def _fixed(*fields) -> str:
    return "".join(str(f).ljust(8) for f in fields)


def _rbe3(*card: str):
    return parse_bulk_data(_GRIDS + list(card)).rbe3s[30]


@pytest.mark.parametrize("card, match", [
    (["RBE3, 30, , 10, 123, 1.0, 123, 1, X, 3"], r"RBE3 30: cannot read 'X' in group 1"),
    (["RBE3, 30, , 10, 123, 1, 123, 1, 2"], r"RBE3 30: expected weight WT1, got '1' \(an integer"),
    (["RBE3, 30, , 10, 123, 1.0, 123, 1, 2", "+, UM, 4, 123"], r"RBE3 30: the UM section is not supported"),
    (["RBE3, 30, , 10, 1237, 1.0, 123, 1, 2"], r"RBE3 30 REFC: invalid DOF string '1237'"),
    (["RBE3, 30, , 10, 123, 1.0, 7, 1, 2"], r"RBE3 30 C1: invalid DOF string '7'"),
    (["RBE3, 30, , 10, 123, 1.0, 123, 2.0, 123, 1"], r"RBE3 30: group 1 \(WT=1.0, C=123\) has no grids"),
    (["RBE3, 30, , 10, 123, 1.0, 123, 1, 2, 3.0"], r"RBE3 30: weight WT2 has no DOF string C2"),
    (["RBE3, 30, 5, 10, 123, 1.0, 123, 1, 2"], r"RBE3 30: field 2 must be blank"),
    (["RBE3, 30, , 10, 123"], r"RBE3 30: no independent grids"),
    (["RBE3, 30, , 10, 123, 1.0, 123, 1, 2", "+, ALPHA, 1.-5, 20., 3"],
     r"RBE3 30: cannot read the ALPHA section"),
], ids=["typo-grid", "integer-first-WT", "UM", "bad-REFC", "bad-C", "empty-group",
        "WT-without-C", "field-2", "no-groups", "ALPHA-not-last"])
def test_malformed_rbe3_is_refused(card, match):
    with pytest.raises(ValueError, match=match):
        _rbe3(*card)


def test_card_reference_examples_parse_as_before():
    assert parse_bulk_data(_GRIDS + ["RBE3, 20, , 7, 123456, 1.0, 123456, 6"]).rbe3s[20].wt_gc \
        == [(1.0, "123456", [6])]
    assert _rbe3("RBE3, 30, , 10, 123, 2.0, 123, 1, 2, 1.0, 123, 3").wt_gc \
        == [(2.0, "123", [1, 2]), (1.0, "123", [3])]


@pytest.mark.parametrize("card", [
    [_fixed("RBE3", 30, "", 10, 123, "2.0", 123, 1, 2) + "+R1", _fixed("+R1", 4, "1.0", 123, 3)],
    ["RBE3, 30, , 10, 123, 2.0, 123, 1, 2, +R1", "+R1, 4, 1.0, 123, 3"],
    ["RBE3, 30, , 10, 123, 2.0, 123, 1, 2", "+, 4, 10.-1, 123, 3"],
], ids=["fixed-field", "free-field-marker", "nastran-real"])
def test_continuations_and_nastran_reals(card):
    assert _rbe3(*card).wt_gc == [(2.0, "123", [1, 2, 4]), (1.0, "123", [3])]


@pytest.mark.parametrize("tail", [["+, ALPHA, 1.-5"], ["+, ALPHA, 1.-5, 20."],
                                  ["+, ALPHA, 1.-5, TREF, 20."]])
def test_alpha_tref_are_ignored_with_a_warning(tail):
    with pytest.warns(UserWarning, match=r"RBE3 30: ALPHA/TREF ignored"):
        rbe3 = _rbe3("RBE3, 30, , 10, 123, 1.0, 123, 1, 2", *tail)
    assert rbe3.wt_gc == [(1.0, "123", [1, 2])]


def test_well_formed_rbe3_reads_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _rbe3("RBE3, 30, , 10, 123, 1.0, 123, 1, 2")


@pytest.mark.parametrize("cid", ["A", "1.5", "2"])
def test_cbush_cid_must_be_zero(cid):
    """Rule-3 sweep: a non-integer CBUSH CID was swallowed and read as 0."""
    with pytest.raises(ValueError, match=rf"CBUSH 4: CID={cid} not supported"):
        parse_bulk_data(_GRIDS + [f"CBUSH, 4, 40, 1, 2, , {cid}", "+, 0., 1., 0."])


def test_integer_weight_after_grids_reads_as_grids_as_in_nastran():
    """Known pitfall, not a defect: in a grid position an integer is a grid ID, in
    NASTRAN too. The card reference tells authors to write every WT as a real."""
    assert _rbe3("RBE3, 30, , 10, 123, 2.0, 123, 1, 2, 1, 123, 3").wt_gc \
        == [(2.0, "123", [1, 2, 1, 123, 3])]
