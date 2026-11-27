"""The viewer's Documentation page (#129).

AppTest drives widgets, not a browser: that figures, math and anchors look right was
checked in a browser on 2026-11-27 and is checked again at each release hand walk (#133).
"""
from __future__ import annotations

import copy
from pathlib import Path

from streamlit.testing.v1 import AppTest

from sbeam_tools.common import user_docs
from sbeam_tools.viewer.docs_view import PAGE_KEY
from tests.viewer.journey_helpers import _assert_clean, _open, _sbeam_app, differences

REPO = Path(__file__).resolve().parents[2]
PAGES = user_docs.pages(REPO)


def _fresh() -> AppTest:
    return AppTest.from_function(_sbeam_app, default_timeout=600)


def _headings(at: AppTest) -> list[str]:
    """The text of the documentation headings drawn in the main area (the app's own
    title is first; the sidebar has headings of its own)."""
    main = at.main
    return [h.value for h in list(main.title)[1:] + list(main.header) + list(main.subheader)]


def test_every_page_opens_with_no_deck_loaded() -> None:
    at = _fresh()
    at.run()
    _assert_clean(at, "start")
    assert at.session_state["bulk_data"] is None
    assert at.selectbox(key=PAGE_KEY).options and at.session_state[PAGE_KEY] == PAGES[0]
    for page in PAGES:
        at.selectbox(key=PAGE_KEY).set_value(page)
        at.run()
        _assert_clean(at, page)
        blocks = user_docs.page_blocks(page, REPO, "0")
        drawn = _headings(at)
        assert len(drawn) == sum(1 for b in blocks if b.level), page
        assert sum(1 for b in blocks if b.level == 0) <= len(at.markdown), page


def test_a_link_from_another_page_opens_the_page_it_names() -> None:
    at = _fresh()
    at.query_params[user_docs.PAGE_PARAMETER] = "docs/10_standard/02_card_reference.md"
    at.run()
    _assert_clean(at, "linked page")
    assert at.session_state[PAGE_KEY] == "docs/10_standard/02_card_reference.md"

    at = _fresh()
    at.query_params[user_docs.PAGE_PARAMETER] = "docs/30_future/00_backlog.md"   # not shipped
    at.run()
    _assert_clean(at, "unknown page")
    assert at.session_state[PAGE_KEY] == PAGES[0]


def test_reading_the_documentation_leaves_the_project_unchanged() -> None:
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    kept = ("bulk_data", "case_control", "_deck_path", "authored_cards")
    before = {k: copy.deepcopy(at.session_state[k]) for k in kept if k in at.session_state}
    assert "bulk_data" in before and "case_control" in before
    for page in ("docs/10_standard/02_card_reference.md", "docs/20_theory/01_aeroelastics_theory.md"):
        at.selectbox(key=PAGE_KEY).set_value(page)
        at.run()
        _assert_clean(at, page)
    at.selectbox(key=PAGE_KEY).set_value(PAGES[0])
    at.run()
    for key, value in before.items():
        assert differences(value, at.session_state[key]) == [], key


def test_the_page_shown_survives_a_new_deck() -> None:
    at = _open("validation/val_cantilever_static.bdf")
    at.selectbox(key=PAGE_KEY).set_value("docs/10_standard/09_conventions.md")
    at.run()
    at.selectbox(key="sample_pick").set_value("validation/val_cantilever_modes.bdf")
    at.button(key="open_deck").click()
    at.run()
    _assert_clean(at, "second deck")
    assert at.session_state[PAGE_KEY] == "docs/10_standard/09_conventions.md"
