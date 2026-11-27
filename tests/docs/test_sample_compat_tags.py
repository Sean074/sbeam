"""Every sample deck says in its header whether MSC NASTRAN could read it (#95 D4).

``$ COMPAT: MSC-runnable``    every bulk card and case-control command in the deck, and in
                              the files it INCLUDEs, is one MSC defines.
``$ COMPAT: sbeam-extension`` the deck uses at least one sbeam-only card or command, or a
                              ZAERO card: MSC will not run it.

The tag is a statement about names and layouts.  No deck here has been run in MSC, and
"MSC-runnable" does not say MSC gives sbeam's numbers (the deviation register lists the
known differences).  This module holds the tag to sbeam's own list of sbeam-only names;
``tests/compat/test_pynastran_crossparse.py`` holds it to what pyNastran rejects (#83).
"""
from __future__ import annotations

import pytest

from tests.docs.test_field_dispositions import SBEAM_ONLY
from tests.samples import (
    MSC_RUNNABLE,
    SBEAM_EXTENSION,
    SBEAM_ONLY_COMMANDS,
    compat_tags,
    deck_names,
    sample_decks,
)

DECKS = [*sample_decks("*.bdf"), *sample_decks("*.dat")]

#: Cards MSC does not define: sbeam's own, and the one ZAERO card sbeam reads.
NOT_MSC_CARDS = SBEAM_ONLY | {"TRIMVAR"}


def expected_tag(deck) -> tuple[str, set[str]]:
    commands, cards = deck_names(deck)
    own = (commands & SBEAM_ONLY_COMMANDS) | (cards & NOT_MSC_CARDS)
    return (SBEAM_EXTENSION if own else MSC_RUNNABLE), own


@pytest.mark.parametrize("deck", DECKS, ids=lambda p: p.name)
def test_deck_header_carries_one_compat_tag(deck):
    tags = compat_tags(deck)
    assert len(tags) == 1, f"{deck.name}: expected one '$ COMPAT:' header line, found {tags}"
    assert tags[0] in (MSC_RUNNABLE, SBEAM_EXTENSION), tags[0]


@pytest.mark.parametrize("deck", DECKS, ids=lambda p: p.name)
def test_tag_agrees_with_the_names_the_deck_uses(deck):
    expected, own = expected_tag(deck)
    assert compat_tags(deck) == [expected], (
        f"{deck.name} uses {sorted(own) or 'no sbeam-only name'}, so its tag is {expected}")


def test_both_tags_are_in_use():
    """Guards the scan: if it found no names, every deck would read MSC-runnable."""
    tags = {t for d in DECKS for t in compat_tags(d)}
    assert tags == {MSC_RUNNABLE, SBEAM_EXTENSION}
