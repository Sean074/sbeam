"""The viewer journey: every sample deck, every tab, one no-op per editable block (#112).

A boot test proves the app starts.  The defects this test is for sit two or three steps
after an interaction that should change nothing: an Apply that drops a selector, an
export that leaves out a card, a form that shows another card's values.  So for each
deck under ``sample/`` the journey

1. opens the deck from the sample picker and draws every tab;
2. submits the case-control editor unchanged;
3. opens one loaded card in every card-family editor and submits it unchanged;
4. takes the export the viewer offers, parses it, and compares it with the deck on disk,
   case control and bulk data, field by field;
5. runs the analysis and draws every tab again.

"Project unchanged" is scored on step 4, on the re-parsed export and not on session
state, so it covers the writers as well as the editors.
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest

from sbeam.model.card_writers import FAMILIES
from sbeam.parser.bdf_reader import parse_bdf
from sbeam_tools.viewer import sol144_authoring as logic
from sbeam_tools.viewer.app import list_sample_decks
from sbeam_tools.viewer.sol144_authoring_ui import _family_ids
from tests.viewer.journey_helpers import _assert_clean, _open, _submit, differences
from tests.viewer.test_open_deck import NOT_STANDALONE

SAMPLES = list_sample_decks()
DECKS = sorted(set(SAMPLES) - set(NOT_STANDALONE))

# Card families with no editor yet.  Each entry names the issue that adds one; the test
# fails if a family is listed here and an editor exists, so the list cannot go stale.
NO_EDITOR: dict[str, str] = {}


def _card(bulk: Any, family: str, key: int) -> Any:
    store = logic.family_store(bulk, family)
    if family == "suport":
        return next(s for s in store if s.gid == key)
    return store[key]


def _family_keys(bulk: Any, family: str) -> list[int]:
    """The cards the family's editor offers (it leaves out MSC MASSSET mass cases)."""
    return _family_ids(bulk, family)


def _exported_text(at: Any) -> str:
    """The deck text behind the "Download BDF" button: the last code block of the editor."""
    blocks = [c.value for c in at.code if "BEGIN BULK" in c.value]
    assert blocks, "no export preview on the Case Control tab"
    return blocks[-1]


@pytest.mark.parametrize("name", DECKS)
def test_journey(name: str, tmp_path: Path) -> None:
    source = SAMPLES[name]
    at = _open(name)
    bulk = at.session_state["bulk_data"]
    cc = at.session_state["case_control"]

    # 1. every tab the deck enables is drawn
    labels = {t.label for t in at.tabs}
    expected = {"Model", "Case Control", "Results"}
    if bulk.caero1s:
        expected |= {"Aeroelastic Authoring", "Aero", "Aero Correction"}
    assert expected <= labels, (expected - labels)

    if cc is None:
        # A bulk-data-only file has no case control to leave unchanged: defining one is
        # an edit, not a no-op.  The tabs drew; nothing more applies.
        assert at.session_state["case_control"] is None
        return

    cc_before = copy.deepcopy(cc)
    bulk_before = copy.deepcopy(bulk)

    # 2. the case-control editor, submitted unchanged
    at.checkbox(key="cc_show_editor").check()
    at.run()
    _submit(at, "cc_form")
    _assert_clean(at, "case control Apply")
    assert differences(cc_before, at.session_state["case_control"], "cc") == []

    # 3. one loaded card per family, submitted unchanged
    if bulk.caero1s:
        for family in FAMILIES:
            has_editor = any(s.key == f"auth_sel_{family}" for s in at.selectbox)
            if family in NO_EDITOR:
                assert not has_editor, f"{family} has an editor now: drop it from NO_EDITOR"
                continue
            assert has_editor, f"no editor for card family {family}"
            keys = _family_keys(bulk, family)
            if not keys:
                continue
            at.selectbox(key=f"auth_sel_{family}").set_value(keys[0])
            at.run()
            _submit(at, f"auth_form_{family}")
            _assert_clean(at, f"{family} {keys[0]} Apply")
            assert any(i.value == "No change." for i in at.info), (
                f"{family} {keys[0]}: the form did not rebuild the loaded card")
            at.selectbox(key=f"auth_sel_{family}").set_value("— new —")
            at.run()
        assert not any(at.session_state["authored_cards"].values())
    assert differences(bulk_before, at.session_state["bulk_data"], "bulk") == []

    # 4. the export, re-parsed beside copies of the deck's own folder
    work = tmp_path / "deck"
    shutil.copytree(source.parent, work)
    exported = work / f"journey_export{source.suffix}"
    exported.write_text(_exported_text(at))
    cc_disk, bulk_disk = parse_bdf(str(source))
    cc_again, bulk_again = parse_bdf(str(exported))
    assert differences(cc_disk, cc_again, "cc") == []
    assert differences(bulk_disk, bulk_again, "bulk") == []

    # 5. run, and every tab draws with results
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    _assert_clean(at, "run")
    results = [at.session_state[k] for k in (
        "sol101_result", "sol103_result", "sol144_result",
        "sol144_diverg_result", "maneuver_result")]
    assert any(r is not None for r in results), "the run produced no result"
    assert differences(cc_before, at.session_state["case_control"], "cc after run") == []
