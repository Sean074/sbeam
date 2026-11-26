"""The case control is checked against the model before any subcase is solved (#124).

Each entry of ``NOT_RUNNABLE`` is a deck that **parses** and cannot be run as asked.
Before #124 most of them failed inside the solver when the subcase was reached, and
two ran to completion while ignoring part of the request (``SILENT_BEFORE``).
"""
from __future__ import annotations

import sys

import pytest

from sbeam import main as cli
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.precheck import check_case_control, require_runnable
from tests.samples import sample_decks, sample_path

MLOADS = sample_path("ha144a_fullspan_mloads.bdf")
SOURCE = MLOADS.read_text()
_MODAL = ("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 1, 1, 1, 6, -1")


def _mutated(*pairs: tuple[str, str], add: str = "") -> str:
    text = SOURCE
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new, 1)
    if add:
        text = text.replace("ENDDATA", add + "\nENDDATA")
    return text


NOT_RUNNABLE = {
    "subcase with no driver": (_mutated(("  TRIM   = 1\n", "")), "needs a driver"),
    "TRIM selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 77")), "TRIM 77 not found"),
    "MANVR selector names no card": (
        _mutated(("  MANVR = 1", "  MANVR = 77")), "MANVR 77 not found"),
    "MANVR with TRIM in one subcase": (
        _mutated(("  MANVR = 1", "  MANVR = 1\n  TRIM = 1")), "cannot combine"),
    "LOAD selector names no set": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  LOAD = 777")), "LOAD 777 not found"),
    "LOAD on a MANVR subcase": (
        _mutated(("  MANVR = 1", "  MANVR = 1\n  LOAD = 777")),
        "LOAD combines only with a TRIM subcase"),
    "MASSCASE selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  MASSCASE = 777")), "MASSCASE 777 not found"),
    "GUSTLF selector names no card": (
        _mutated(("  TRIM   = 1", "  GUSTLF = 777")), "GUSTLF 777 not found"),
    "DIVERG selector names no card": (
        _mutated(("  TRIM   = 1", "  DIVERG = 777")), "DIVERG 777 not found"),
    "TRIMWGT selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  TRIMWGT = 777")), "TRIMWGT 777 not found"),
    "MANVR subcase with no SUPORT": (
        _mutated(("SUPORT, 90, 35", "$SUPORT, 90, 35")), "needs a SUPORT card"),
    "modal MANVR, MANTRIM without RHO": (
        _mutated(_MODAL, ("MANTRIM, 1, 1, 2.3769-3", "MANTRIM, 1, 1")), "needs RHO"),
    "LOAD on a divergence-only subcase": (
        _mutated(("  TRIM   = 1", "  DIVERG = 5\n  LOAD = 701"),
                 add="DIVERG, 5, 1, 0.9\nFORCE, 701, 90, 0, 100.0, 1.0, 0.0, 0.0"),
        "LOAD combines only with a TRIM subcase"),
    "GRAV in a trim LOAD set": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  LOAD = 702"),
                 add="GRAV, 702, 0, 32.174, 0.0, 0.0, -1.0"),
        "references GRAV [702]"),
}

# Ran to completion before #124, with part of the request ignored (rule 7).
SILENT_BEFORE = {"MANVR with TRIM in one subcase", "TRIMWGT selector names no card"}


@pytest.mark.parametrize("rule", sorted(NOT_RUNNABLE))
def test_each_fault_parses_and_is_reported(rule):
    text, fragment = NOT_RUNNABLE[rule]
    cc, bulk = parse_bdf(MLOADS, text=text)              # the parser does not check this
    errors, _ = check_case_control(cc, bulk)
    assert any(fragment in e for e in errors), errors
    with pytest.raises(ValueError, match="cannot be run on this model"):
        require_runnable(cc, bulk)


def test_the_silent_faults_are_in_the_table():
    assert SILENT_BEFORE <= set(NOT_RUNNABLE)


def test_the_unmodified_deck_is_runnable():
    cc, bulk = parse_bdf(MLOADS)
    assert check_case_control(cc, bulk)[0] == []
    require_runnable(cc, bulk)


@pytest.mark.parametrize("deck", [p for p in sample_decks()], ids=lambda p: p.name)
def test_every_sample_deck_that_parses_is_runnable(deck):
    """No sample deck is refused by the new check."""
    text = deck.read_text()
    if not any(line.upper().startswith("SOL") for line in text.splitlines()):
        pytest.skip("bulk data only")
    try:
        cc, bulk = parse_bdf(deck)
    except Exception:
        pytest.skip("not a deck that parses on its own")
    assert check_case_control(cc, bulk)[0] == []


def test_gust_subcases():
    """A GUSTLF subcase is a trim subcase whose TRIM the card names (#122)."""
    cc, bulk = parse_bdf(sample_path("cessna210_flagship_gust.bdf"))
    assert check_case_control(cc, bulk)[0] == []
    sc = cc.subcases[0]
    card_trim = bulk.gustlfs[sc.gustlf_sid].trimid
    sc.trim_sid = next(t for t in bulk.trims if t != card_trim)
    assert any(f"names TRIM {card_trim}" in e for e in check_case_control(cc, bulk)[0])
    sc.trim_sid = card_trim                              # agreeing with the card is allowed
    assert check_case_control(cc, bulk)[0] == []
    sc.trim_sid, sc.gustlf_sid = None, 987654
    assert any("GUSTLF 987654 not found" in e for e in check_case_control(cc, bulk)[0])


def test_other_solutions_are_not_checked():
    cc, bulk = parse_bdf(sample_path("val_cantilever_static.bdf"))
    cc.subcases[0].load_sid = 987654
    assert check_case_control(cc, bulk) == ([], [])       # SOL 101: the solver reports it


def test_warnings_inform_and_do_not_block():
    cc, bulk = parse_bdf(sample_path("ha144a_mloads_massset.bdf"))
    errors, warns = check_case_control(cc, bulk)
    assert errors == [] and any("fixed-Φ" in w for w in warns)
    require_runnable(cc, bulk)


# --- the command line -------------------------------------------------------------------

def _run_cli(tmp_path, monkeypatch, text: str):
    deck = tmp_path / "deck.bdf"
    deck.write_text(text)
    monkeypatch.setattr(sys, "argv", ["sbeam", str(deck)])
    with pytest.raises(SystemExit) as stop:
        cli.main()
    return deck, stop.value.code


def test_the_command_line_lists_every_fault_before_solving_anything(tmp_path, monkeypatch):
    """Two faults in two subcases: both are named, and no subcase is solved.  Before
    #124 the run stopped at the first one it reached, from inside the solver."""
    text = _mutated(("  TRIM   = 1", "  TRIM   = 77"), ("  MANVR = 1", "  MANVR = 88"))
    solved: list[int] = []
    import sbeam.solver.sol144 as sol144
    real = sol144.run_sol144_trim
    monkeypatch.setattr(sol144, "run_sol144_trim",
                        lambda *a, **k: solved.append(1) or real(*a, **k))
    deck, message = _run_cli(tmp_path, monkeypatch, text)
    assert "cannot be run on this model" in message
    assert "Subcase 1: TRIM 77 not found" in message
    assert "Subcase 2: MANVR 88 not found" in message
    assert solved == [] and not deck.with_suffix(".f06").exists()


@pytest.mark.parametrize("rule", sorted(SILENT_BEFORE))
def test_the_command_line_refuses_what_it_used_to_run_silently(rule, tmp_path, monkeypatch):
    text, fragment = NOT_RUNNABLE[rule]
    deck, message = _run_cli(tmp_path, monkeypatch, text)
    assert fragment in message and not deck.with_suffix(".f06").exists()
