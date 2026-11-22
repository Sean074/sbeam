"""#57 gate: a second card with an ID already in use refuses the deck.

Before #57, PLOTEL, RBE2, RBE3, CONM2 and EIGRL stored ``bulk.<family>[id] = ...`` with no
duplicate check, so a second card silently replaced the first. A duplicate CONM2 dropped
a mass.

Three parts:

1. Each of the five cards refuses a same-type duplicate.
2. ID spaces stay separate where they are separate: only CBAR, CROD, CONROD and CBUSH
   share element IDs (#38 D7). CONM2 may reuse a CBAR's EID, as MSC's own HA144A does
   (CBAR 100 and CONM2 100). Rigid elements and PLOTEL keep their own spaces until
   NASTRAN's rule for them is confirmed.
3. Invariant: every ID-keyed card type the reader handles refuses a second copy of
   itself. Card instances come from the repository's decks, with a few hand-written
   cards for types no deck uses. A new card type fails this test until it is either
   found in a deck, given a card here, or listed as accumulating.
"""

import re
import warnings
from pathlib import Path

import pytest

from sbeam.parser import bdf_reader
from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.parser.bulk_fields import split_line
from tests.parser.test_card_order import _cards

REPO = Path(__file__).resolve().parents[2]

_GRIDS = ["GRID, 1, , 0.0, 0.0, 0.0", "GRID, 2, , 1.0, 0.0, 0.0", "GRID, 3, , 2.0, 0.0, 0.0"]


@pytest.mark.parametrize("first, second, match", [
    (["PLOTEL, 5, 1, 2"], ["PLOTEL, 5, 2, 3"], r"Duplicate PLOTEL EID 5"),
    (["RBE2, 6, 1, 123456, 2"], ["RBE2, 6, 1, 123456, 3"], r"Duplicate RBE2 EID 6"),
    (["RBE3, 8, , 1, 123456, 1.0, 123456, 2"], ["RBE3, 8, , 1, 123456, 1.0, 123456, 3"],
     r"Duplicate RBE3 EID 8"),
    (["CONM2, 9, 1, 0, 10.0"], ["CONM2, 9, 2, 0, 20.0"], r"Duplicate CONM2 EID 9"),
    (["EIGRL, 1, , , 5"], ["EIGRL, 1, , , 9"], r"Duplicate EIGRL SID 1"),
], ids=["PLOTEL", "RBE2", "RBE3", "CONM2", "EIGRL"])
def test_same_type_duplicate_is_refused(first, second, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_GRIDS + first + second)


_ELEMENTS = {
    "CBAR": ["MAT1, 30, 2.0e11, 8.0e10, 0.25, 7850.0",
             "PBAR, 10, 30, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8",
             "CBAR, {eid}, 10, 1, 2, 0., 1., 0."],
    "RBAR": ["RBAR, {eid}, 2, 3, 123456"],
    "RBE2": ["RBE2, {eid}, 1, 123456, 3"],
    "RBE3": ["RBE3, {eid}, , 3, 123456, 1.0, 123456, 1"],
    "CONM2": ["CONM2, {eid}, 1, 0, 10.0"],
    "PLOTEL": ["PLOTEL, {eid}, 1, 3"],
}


def test_separate_id_spaces_may_reuse_an_eid():
    """Every card in _ELEMENTS with EID 7 at once: each type keeps its own card."""
    deck = _GRIDS + [c.format(eid=7) for cards in _ELEMENTS.values() for c in cards]
    bulk = parse_bulk_data(deck)
    for family in ("cbars", "rbars", "rbe2s", "rbe3s", "conm2s", "plotels"):
        assert set(getattr(bulk, family)) == {7}, family


# Several cards share one SID by design (the set is their union); PARAM stores nothing,
# and SPLINE1 and MONPNT3 (#86) are refused outright as not implemented.
_ACCUMULATING = {"FORCE", "MOMENT", "SPC", "SPC1", "SUPORT", "TRIMINEQ"}
_NOT_STORED = {"PARAM", "SPLINE1", "MONPNT3"}

# ID-keyed cards no repository deck uses (examples from 02_card_reference.md)
_HAND_WRITTEN = {
    "AEFACT": ["AEFACT, 10, 0.0, 0.333, 0.667, 1.0"],
    "CPINJ": ["CPINJ, 40, 100, 2.0, 0.9, 0.52, 0.31, 0.21, 0.14",
                "+,       0.52, 0.31, 0.21, 0.14"],
    "DIVERG": ["DIVERG, 20, 2, 0.4, 0.6, 0.8"],
    "MASSSET": ["MASSSET, 11, 1.0, 1.0, 0"],          # MSC mass combination (#102)
    # No sample deck has an RBE3 since #60 moved beam_vib1/simple_beam to RBAR
    "RBE3": ["RBE3, 30, , 10, 123, 2.0, 123, 1, 2, 1.0, 123, 3"],
    "TRIMWGT": ["TRIMWGT, 20, ANGLEA, 1.0, CL, 0.5", "+,       CM, 0.1"],
    "TRIMVAR": ["TRIMVAR, 10, ANGLEA, -0.3, 0.3, , , , 0.05"],
    "WKK": ["WKK, 10, 100, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1", "+,   1.1, 1.1"],
}


def _harvest() -> dict[str, list[str]]:
    """The first instance of each handled card type in any sample or test deck file
    (include files too), with its continuation lines."""
    found: dict[str, list[str]] = {}
    files = sorted(p for d in ("sample", "tests") for p in (REPO / d).rglob("*")
                   if p.suffix.lower() in (".bdf", ".dat"))
    for path in files:
        lines = path.read_text(errors="ignore").splitlines()
        upper = [line.strip().upper() for line in lines]
        begin = [i for i, u in enumerate(upper) if u.startswith("BEGIN BULK")]
        if begin:
            lines = lines[begin[0] + 1:]
        for card in _cards(lines)[1:]:
            name = split_line(card[0].split("$", 1)[0])[0].strip().upper().rstrip("*")
            if name in bdf_reader.HANDLED_CARDS:
                found.setdefault(name, card)
    return found


_CARDS = {**_harvest(), **_HAND_WRITTEN}
_ID_KEYED = sorted(bdf_reader.HANDLED_CARDS - _ACCUMULATING - _NOT_STORED)


def test_every_handled_card_is_classified():
    unclassified = set(_ID_KEYED) - set(_CARDS)
    assert not unclassified, (
        f"no card instance for {sorted(unclassified)}: add one to _HAND_WRITTEN, "
        f"or list the type in _ACCUMULATING if several cards may share its ID")


@pytest.mark.parametrize("card", _ID_KEYED)
def test_every_id_keyed_card_refuses_a_second_copy(card):
    lines = _CARDS[card]
    # One copy reads (cross-references are checked only after the read, so they may
    # still fail); the second copy must be refused while reading, as a duplicate.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            parse_bulk_data(list(lines))
        except ValueError as exc:
            assert not re.search(r"duplicate|collides", str(exc), re.I), exc
        with pytest.raises(ValueError, match=r"(?i)duplicate|collides"):
            parse_bulk_data(list(lines) + list(lines))
