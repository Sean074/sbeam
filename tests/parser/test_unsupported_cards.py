"""#45 — decks carrying known-but-unsupported NASTRAN cards are refused at parse.

Before this gate a ``PLOAD1`` deck parsed, solved and reported with the load absent and
only a generic ``UserWarning`` nobody collected.  Now every keyword in
``_UNSUPPORTED_CARDS`` is counted and the deck is refused once with the full list;
unlisted keywords keep the warning (typos, output requests, vendor cards).
"""

import re
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

from sbeam.parser import bdf_reader
from sbeam.parser.bdf_reader import _UNSUPPORTED_CARDS, parse_bdf

REPO = Path(__file__).resolve().parents[2]

HEAD = """\
SOL 101
SUBCASE 1
  SPC = 1
  LOAD = 10
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
MAT1, 1, 2.0e11, 8.0e10, 0.25, 7850.0
PBAR, 1, 1, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 100.0, 0.0, 0.0, 1.0
"""


def _deck(tmp_path: Path, body: str) -> str:
    f = tmp_path / "deck.bdf"
    f.write_text(HEAD + body + "ENDDATA\n")
    return str(f)


class TestRefusal:
    def test_pload1_is_refused_with_a_count(self, tmp_path):
        body = ("PLOAD1, 10, 1, FY, FR, 0.0, -100.0, 1.0, -100.0\n"
                "PLOAD1, 10, 1, FZ, FR, 0.0, -100.0, 1.0, -100.0\n")
        with pytest.raises(ValueError, match=r"Unsupported bulk data card\(s\): "
                                             r"PLOAD1 x2 \(distributed CBAR load\)"):
            parse_bdf(_deck(tmp_path, body))

    def test_all_offenders_listed_once_in_one_message(self, tmp_path):
        body = ("CBEAM, 9, 1, 1, 2, 0.0, 1.0, 0.0\n"
                "PLOAD1, 10, 1, FY, FR, 0.0, -100.0, 1.0, -100.0\n"
                "CORD2C, 5, , 0., 0., 0., 0., 0., 1., 1., 0., 0.\n")
        with pytest.raises(ValueError) as ei:
            parse_bdf(_deck(tmp_path, body))
        msg = str(ei.value)
        assert "CBEAM x1 (beam element), CORD2C x1 (coordinate system), PLOAD1 x1" in msg
        assert "02_card_reference.md" in msg

    def test_continuation_lines_of_a_refused_card_do_not_leak(self, tmp_path):
        # Fixed-field PLOAD4 with a continuation: the "+" line must not be parsed as a card.
        body = ("PLOAD4  10      1       1.0     1.0     1.0     1.0             +P1\n"
                "+P1     0       0.0     0.0     1.0\n")
        with pytest.raises(ValueError, match=r"PLOAD4 x1"):
            parse_bdf(_deck(tmp_path, body))

    def test_supported_deck_still_parses_and_solves(self, tmp_path):
        cc, bulk = parse_bdf(_deck(tmp_path, ""))
        assert set(bulk.cbars) == {1}

    def test_unknown_keyword_still_warns_and_parses(self, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cc, bulk = parse_bdf(_deck(tmp_path, "FOOBAR, 1, 2, 3\n"))
        assert set(bulk.cbars) == {1}
        assert any("Unknown BDF card 'FOOBAR'" in str(w.message) for w in caught)


class TestSetHygiene:
    """The set cannot drift: nothing in it has a handler, nothing supported is in it."""

    def test_no_unsupported_keyword_has_a_handler(self):
        src = (REPO / "sbeam/parser/bdf_reader.py").read_text()
        handled = set(re.findall(r'keyword == "([A-Z0-9]+)"', src))
        assert handled, "dispatch scan found nothing — the gate would pass vacuously"
        assert not handled & set(_UNSUPPORTED_CARDS), (
            "a card is both handled and refused; remove it from _UNSUPPORTED_CARDS")

    def test_claude_md_supported_cards_are_not_refused(self):
        text = (REPO / "CLAUDE.md").read_text()
        block = text[text.index("## Supported Cards"):text.index("## Key Constraints")]
        supported = set(re.findall(r"\b[A-Z][A-Z0-9]{2,}\b", block))
        assert not supported & set(_UNSUPPORTED_CARDS)

    def test_every_refused_card_is_documented(self):
        doc = (REPO / "docs/10_standard/02_card_reference.md").read_text()
        section = doc[doc.index("## Unsupported cards"):doc.index("## Constraints and Limitations")]
        missing = [kw for kw in _UNSUPPORTED_CARDS if f"`{kw}`" not in section]
        assert not missing, f"02_card_reference.md 'Unsupported cards' lacks: {missing}"

    def test_pload1_stays_unsupported_until_its_parked_item_lands(self):
        assert "PLOAD1" in _UNSUPPORTED_CARDS
        assert not hasattr(bdf_reader, "_handle_pload1")


class TestCli:
    def test_cli_exits_with_the_refusal(self, tmp_path):
        deck = _deck(tmp_path, "PLOAD1, 10, 1, FY, FR, 0.0, -100.0, 1.0, -100.0\n")
        r = subprocess.run([sys.executable, "-m", "sbeam", deck],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode != 0
        assert "Parse error: Unsupported bulk data card(s): PLOAD1 x1" in r.stderr
        assert not Path(deck).with_suffix(".f06").exists()

    def test_cli_prints_unknown_card_warnings(self, tmp_path):
        deck = _deck(tmp_path, "FOOBAR, 1\n")
        r = subprocess.run([sys.executable, "-m", "sbeam", deck],
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stderr
        assert "Parser warning: Unknown BDF card 'FOOBAR' — skipped" in r.stderr
