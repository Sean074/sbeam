"""#51 gate: bulk data is order-independent, and every reference between cards is checked.

Three parts:

1. Every parseable sample and integration deck gives the same ``BulkData`` with its bulk
   cards reversed and shuffled (continuations kept with their card). Before #51 every
   reversed deck failed at its first element, because the element came before its GRIDs.
2. Each structural element parses when it comes before everything it references, and
   each cross-type uniqueness rule fires in both card orders (before #51 CBUSH,
   PAERO1 and MONPNT1/3 did not check against cards already read).
3. Every reference that was never checked (group C) now refuses the deck. Before #51 a
   FORCE or CONM2 on a missing grid was dropped from the solve without a word.

The physics gate (part 4) solves the flagship trim deck and a SOL 101 deck in shuffled
order and compares them with the original to round-off.
"""

import random
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser import bdf_reader
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.bulk_fields import is_continuation, split_line

REPO = Path(__file__).resolve().parents[2]
DECKS = sorted([*(REPO / "sample").glob("*.bdf"), *(REPO / "tests/integration/bdf").glob("*.bdf")])
SEEDS = (0, 1, 2)


def _bulk_lines(path: Path) -> list[str]:
    """The exact bulk lines ``parse_bdf`` hands to ``parse_bulk_data`` (INCLUDEs resolved)."""
    captured: list[list[str]] = []
    real = bdf_reader.parse_bulk_data

    def capture(lines: list[str]):
        captured.append(list(lines))
        return real(lines)

    bdf_reader.parse_bulk_data = capture
    try:
        parse_bdf(path)
    finally:
        bdf_reader.parse_bulk_data = real
    return captured[0]


def _cards(lines: list[str]) -> list[list[str]]:
    """Group lines into cards: each card line with the continuation, blank and comment
    lines that follow it.  Lines before the first card stay as the leading group."""
    groups: list[list[str]] = [[]]
    for line in lines:
        body = line.split("$", 1)[0]
        if body.strip() and not is_continuation(split_line(body)):
            groups.append([])
        groups[-1].append(line)
    return groups


def _reordered(lines: list[str], order: str) -> list[str]:
    head, *cards = _cards(lines)
    if order == "reversed":
        cards.reverse()
    else:
        random.Random(int(order)).shuffle(cards)
    return head + [line for card in cards for line in card]


def _canonical(bulk) -> dict:
    """BulkData with card order removed: dicts compare unordered already; the lists of
    whole cards (SUPORT, and the per-SID FORCE/MOMENT/SPC/SPC1/TRIMCON lists) are sorted."""
    out = {}
    for f in fields(bulk):
        value = getattr(bulk, f.name)
        if isinstance(value, list):
            value = sorted(value, key=repr)
        elif isinstance(value, dict) and value and all(isinstance(v, list) for v in value.values()):
            value = {k: sorted(v, key=repr) for k, v in value.items()}
        out[f.name] = value
    return out


def _parseable(path: Path) -> bool:
    try:
        parse_bdf(path)
    except Exception:
        return False
    return True


PARSEABLE = [d for d in DECKS if _parseable(d)]


def test_gate_covers_the_deck_set():
    """Not vacuous: nearly every repo deck parses (HA144A and a few by-design failures do not)."""
    assert len(PARSEABLE) >= 50, [d.name for d in DECKS if d not in PARSEABLE]


@pytest.mark.parametrize("order", ["reversed", *map(str, SEEDS)])
@pytest.mark.parametrize("deck", PARSEABLE, ids=lambda d: d.name)
def test_deck_is_order_independent(deck, order):
    lines = _bulk_lines(deck)
    reordered = _reordered(lines, order)
    assert sorted(reordered) == sorted(lines)   # same lines, nothing lost
    if order == "reversed":
        assert reordered != lines
    assert _canonical(parse_bulk_data(reordered)) == _canonical(parse_bulk_data(lines))


# --------------------------------------------------------------------------------------
# Part 2: references after the card, and cross-type uniqueness in both orders
# --------------------------------------------------------------------------------------

# Every element and reference-carrying card first, then what it references.
_FORWARD_REFERENCES = """\
CBAR, 1, 10, 1, 2, 0., 1., 0.
CROD, 2, 20, 1, 2
CONROD, 3, 1, 2, 30, 1.0e-4
CBUSH, 4, 40, 1, 2, 0., 1., 0.
PLOTEL, 5, 1, 2
RBE2, 6, 2, 123456, 3
RBAR, 7, 1, 3
RBE3, 8, , 3, 123456, 1.0, 123, 1, 2
CONM2, 9, 2, 50, 10.0
FORCE, 100, 2, 50, 1.0, 0., 0., 1.
MOMENT, 100, 2, 50, 1.0, 0., 0., 1.
SPC1, 1, 123456, 1
SPC, 2, 2, 3
PBAR, 10, 30, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8
PROD, 20, 30, 1.0e-4
PBUSH, 40, K, 1.0e6, 1.0e6, 1.0e6, 1.0e3, 1.0e3, 1.0e3
MAT1, 30, 2.0e11, 8.0e10, 0.25, 7850.0
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 2.0, 0.0, 0.0
GRID, 4, , 3.0, 0.0, 0.0, 50
CORD2R, 50, 51, 0., 0., 0., 0., 0., 1.
+, 1., 0., 0.
CORD2R, 51, 0, 0., 0., 0., 0., 0., 1.
+, 1., 0., 0.
"""


def test_every_element_may_precede_its_references():
    bulk = parse_bulk_data(_FORWARD_REFERENCES.splitlines())
    assert set(bulk.cbars) == {1} and set(bulk.crods) == {2} and set(bulk.conrods) == {3}
    assert set(bulk.cbushs) == {4} and set(bulk.plotels) == {5} and set(bulk.rbe2s) == {6}
    assert set(bulk.rbars) == {7} and set(bulk.rbe3s) == {8} and set(bulk.conm2s) == {9}


_PBUSH = "PBUSH, 40, K, 1.0e6, 1.0e6, 1.0e6, 1.0e3, 1.0e3, 1.0e3"
_BASE = ["GRID, 1, , 0.0, 0.0, 0.0", "GRID, 2, , 1.0, 0.0, 0.0",
         "MAT1, 30, 2.0e11, 8.0e10, 0.25, 7850.0",
         "PBAR, 10, 30, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8", _PBUSH]


@pytest.mark.parametrize("first, second, match", [
    (["CBAR, 4, 10, 1, 2, 0., 1., 0."], ["CBUSH, 4, 40, 1, 2, 0., 1., 0."],
     r"CBUSH 4: duplicate element ID \(already defined by CBAR 4\)"),
    (["CBUSH, 4, 40, 1, 2, 0., 1., 0."], ["CBAR, 4, 10, 1, 2, 0., 1., 0."],
     r"CBAR 4: duplicate element ID \(already defined by CBUSH 4\)"),
    (["CBUSH, 4, 40, 1, 2, 0., 1., 0."], ["CBUSH, 4, 40, 1, 2, 0., 1., 0."],
     r"CBUSH 4: duplicate element ID"),
    (["PAERO1, 7"], ["PSTRIP, 7"], "PSTRIP PID 7 collides with a PAERO1"),
    (["PSTRIP, 7"], ["PAERO1, 7"], "PSTRIP PID 7 collides with a PAERO1"),
    (["MONPNT1, M1, L, 123456, C1"], ["MONPNT3, M1, L, 123456, C3"],
     "MONPNT3 M1: NAME collides with an existing MONPNT1"),
    (["MONPNT3, M1, L, 123456, C3"], ["MONPNT1, M1, L, 123456, C1"],
     "MONPNT3 M1: NAME collides with an existing MONPNT1"),
    (["MONPNT1, S1, L, 123456, C1"], ["MONSECT, S1, L, C1, 0, 2, POS", "+, 0.5"],
     "MONSECT S1: NAME collides with an existing MONPNT1/MONPNT3"),
    (["MONSECT, S1, L, C1, 0, 2, POS", "+, 0.5"], ["MONPNT3, S1, L, 123456, C3"],
     "MONSECT S1: NAME collides with an existing MONPNT1/MONPNT3"),
], ids=["CBUSH-after-CBAR", "CBAR-after-CBUSH", "CBUSH-twice", "PSTRIP-after-PAERO1",
        "PAERO1-after-PSTRIP", "MONPNT3-after-MONPNT1", "MONPNT1-after-MONPNT3",
        "MONSECT-after-MONPNT1", "MONPNT3-after-MONSECT"])
def test_cross_type_uniqueness_in_either_order(first, second, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_BASE + first + second)


# --------------------------------------------------------------------------------------
# Part 3: references that were never checked now refuse the deck
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("cards, match", [
    (["FORCE, 1, 99, 0, 1.0, 0., 0., 1."], "FORCE 1: grid GID=99 not found"),
    (["MOMENT, 1, 99, 0, 1.0, 0., 0., 1."], "MOMENT 1: grid GID=99 not found"),
    (["FORCE, 1, 2, 7, 1.0, 0., 0., 1."], "FORCE 1: CID=7 not found in CORD2R"),
    (["MOMENT, 1, 2, 7, 1.0, 0., 0., 1."], "MOMENT 1: CID=7 not found in CORD2R"),
    (["CONM2, 5, 99, 0, 10.0"], "CONM2 5: grid GID=99 not found"),
    (["CONM2, 5, 2, 7, 10.0"], "CONM2 5: CID=7 not found in CORD2R"),
    (["SPC, 1, 99, 3"], "SPC 1: grid G1=99 not found"),
    (["SPC, 1, 1, 3, 0.0, 99, 3"], "SPC 1: grid G2=99 not found"),
    (["SPC1, 1, 123456, 1, 99"], "SPC1 1: grid Gi=99 not found"),
    (["SUPORT, 99, 3"], "SUPORT: grid GID=99 not found"),
    (["RBE3, 8, , 99, 123456, 1.0, 123, 1, 2"], "RBE3 8: grid REFGRID=99 not found"),
    (["RBE3, 8, , 2, 123456, 1.0, 123, 1, 99"], "RBE3 8: grid Gi=99 not found"),
    (["PBAR, 11, 99, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8"], "PBAR 11: material MID=99 not found"),
    (["PROD, 21, 99, 1.0e-4"], "PROD 21: material MID=99 not found"),
    (["GRID, 3, , 2.0, 0.0, 0.0, 7"], "GRID 3: CD=7 not found in CORD2R"),
    (["CORD2R, 5, 7, 0., 0., 0., 0., 0., 1.", "+, 1., 0., 0."], "CORD2R 5: RID=7 not found in CORD2R"),
], ids=lambda v: v if isinstance(v, str) else None)
def test_dangling_structural_reference_is_refused(cards, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_BASE + cards)


def _aero_deck(old: str, new: str) -> list[str]:
    """The dihedral trim deck's bulk with card ``old`` (and its continuations) replaced."""
    lines = _bulk_lines(REPO / "sample/val_dihedral_trim.bdf")
    head, *cards = _cards(lines)
    hits = [k for k, card in enumerate(cards) if card[0].strip() == old]
    assert len(hits) == 1, old
    cards[hits[0]] = new.split("\n")
    return head + [line for card in cards for line in card]


_SPLINE = "SPLINE2, 1601, 1100, 1100, 1131, 1100, 0.0, 1.0, 2"


@pytest.mark.parametrize("old, new, match", [
    ("AEROS,  0,  0,  1.0,  8.0,  8.0,  0,  0", "AEROS,  7,  0,  1.0,  8.0,  8.0,  0,  0",
     "AEROS card: ACSID=7 not found in CORD2R"),
    ("AEROS,  0,  0,  1.0,  8.0,  8.0,  0,  0", "AEROS,  0,  7,  1.0,  8.0,  8.0,  0,  0",
     "AEROS card: RCSID=7 not found in CORD2R"),
    ("CAERO1, 1100, 1, 0, 8, 4, 0, 0, 1",
     "CAERO1, 1100, 1, 7, 8, 4, 0, 0, 1\n+, 0.0, 0.0, 0.0, 1.0, 0.0, 3.93923099, 0.69459271, 1.0",
     "CAERO1 1100: CP=7 not found in CORD2R"),
    (_SPLINE, "SPLINE2, 1601, 1100, 1100, 1131, 1100, 0.0, 1.0, 7",
     "SPLINE2 1601: CID=7 not found in CORD2R"),
    (_SPLINE, "SPLINE0, 1601, 1199, 1100, 1131, 90",
     "SPLINE0 1601: CAERO=1199 not found in CAERO1"),
    (_SPLINE, "SPLINE0, 1601, 1100, 1100, 1131, 99", "SPLINE0 1601: grid GRID=99 not found"),
    (_SPLINE, "ATTACH, 1601, 1199, 1100, 1131, 90", "ATTACH 1601: CAERO=1199 not found in CAERO1"),
    (_SPLINE, "ATTACH, 1601, 1100, 1100, 1131, 99", "ATTACH 1601: grid GRID=99 not found"),
    (_SPLINE, "ATTACH, 1601, 1100, 1100, 1131, 90, 7", "ATTACH 1601: CID=7 not found in CORD2R"),
    ("SET1, 1100, 90, 110, 120", "SET1, 1100, 90, 110, 120\nW2GJ, 1, 1199, 0.0",
     "W2GJ 1: CAERO1 1199 not found"),
    ("SET1, 1100, 90, 110, 120", "SET1, 1100, 90, 110, 120\nWKK, 1, 1199, 1.0",
     "WKK 1: CAERO1 1199 not found"),
    ("SET1, 1100, 90, 110, 120", "SET1, 1100, 90, 110, 120\nAECORR, 1, WT2, 1199, 6.0",
     "AECORR 1: CAERO1 1199 not found"),
    ("SET1, 1100, 90, 110, 120", "SET1, 1100, 90, 110, 120\nCHORDCP, 1, 1199, 2.0, 0.0, 0.1",
     "CHORDCP 1: CAERO1 1199 not found"),
], ids=["AEROS-ACSID", "AEROS-RCSID", "CAERO1-CP", "SPLINE2-CID", "SPLINE0-CAERO",
        "SPLINE0-GRID", "ATTACH-CAERO", "ATTACH-GRID", "ATTACH-CID", "W2GJ-CAERO",
        "WKK-CAERO", "AECORR-CAERO", "CHORDCP-CAERO"])
def test_dangling_aero_reference_is_refused(old, new, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_aero_deck(old, new))


def test_ha144a_is_past_the_card_order_error():
    """The issue's reproduction: HA144A puts its CBARs before their PBAR.  It now gets
    past that and stops at its next real limitation, the weight-unit PARAM,WTMASS (#39)."""
    with pytest.raises(ValueError, match=r"PARAM,WTMASS,0.031081 is not supported"):
        parse_bdf(REPO / "sample/HA144A.bdf")


# --------------------------------------------------------------------------------------
# Part 4: physics gate — a shuffled deck solves to the same answer
# --------------------------------------------------------------------------------------

def _parse_reordered(path: Path, order: str):
    cc, _ = parse_bdf(path)
    return cc, parse_bulk_data(_reordered(_bulk_lines(path), order))


def test_shuffled_sol101_deck_solves_identically():
    from sbeam.solver.sol101 import run_sol101
    path = REPO / "tests/integration/bdf/v25_strut_pylon_statics.bdf"
    cc, bulk = parse_bdf(path)
    _, shuffled = _parse_reordered(path, "1")
    for sc in cc.subcases:
        ref, got = run_sol101(bulk, sc), run_sol101(shuffled, sc)
        np.testing.assert_allclose(got.displacements, ref.displacements,
                                   rtol=1e-10, atol=1e-12 * np.abs(ref.displacements).max())


def test_shuffled_flagship_trim_solves_identically():
    """The real operating condition: the Cessna 210 flagship trim deck, every subcase."""
    from sbeam.aero.aero_model import build_aero_model
    from sbeam.assembly.load_vector import build_grid_index
    from sbeam.solver.sol144 import AeroCache, run_sol144_trim

    def trims(bulk, cc):
        grid_index = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=grid_index)
        cache = AeroCache(bulk, grid_index, seed=aero)
        return {sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache)
                for sc in cc.subcases}

    path = REPO / "sample/cessna210_flagship_trim.bdf"
    cc, bulk = parse_bdf(path)
    _, shuffled = _parse_reordered(path, "2")
    ref, got = trims(bulk, cc), trims(shuffled, cc)
    assert len(ref) == len(cc.subcases) >= 2
    for sid in ref:
        for label, value in ref[sid].trim_vars.items():
            assert got[sid].trim_vars[label] == pytest.approx(value, rel=1e-9, abs=1e-12), (sid, label)
        np.testing.assert_allclose(got[sid].displacements, ref[sid].displacements,
                                   rtol=1e-9, atol=1e-12 * np.abs(ref[sid].displacements).max())
