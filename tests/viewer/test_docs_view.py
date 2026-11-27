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


# --- Search (#130) -------------------------------------------------------------------

def test_a_search_result_opens_its_page_at_its_heading() -> None:
    from sbeam_tools.viewer.docs_view import SCROLL_KEY, SEARCH_KEY
    at = _fresh()
    at.run()
    at.text_input(key=SEARCH_KEY).set_value("MASSCASE")
    at.run()
    _assert_clean(at, "search")
    first = at.button(key="docs_hit_0")
    assert first.label.endswith("MASSCASE — Payload / Mass Case (sbeam extension; Step 60)")
    first.click()
    at.run()
    _assert_clean(at, "result")
    assert at.session_state[PAGE_KEY] == user_docs.CARD_REFERENCE
    assert SCROLL_KEY not in at.session_state          # consumed: the page scrolled once


def test_a_search_with_no_match_says_so() -> None:
    from sbeam_tools.viewer.docs_view import SEARCH_KEY
    at = _fresh()
    at.run()
    at.text_input(key=SEARCH_KEY).set_value("zzzz-no-such-term")
    at.run()
    _assert_clean(at, "search")
    assert any("Nothing in the documentation matches" in i.value for i in at.info)
    assert not [b for b in at.button if (b.key or "").startswith("docs_hit_")]


# --- Links from the forms to the card reference (#131) -------------------------------

def test_every_form_links_to_its_section_of_the_card_reference() -> None:
    from sbeam_tools.viewer.sol144_authoring import CARD_NAMES
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    captions = "\n".join(c.value for c in at.caption)
    wanted = set(CARD_NAMES.values()) | {"Case Control Keywords", "W2GJ", "AECORR"}
    for start in sorted(wanted):
        url = user_docs.page_url(user_docs.CARD_REFERENCE, user_docs.reference_anchor(start, REPO))
        assert f"]({url})" in captions, start
    # 21 families (MONPNT1 has two forms), the case-control editor, two on Aero Correction
    assert captions.count("in the card reference](") == len(CARD_NAMES) + 3


def test_a_form_link_opens_the_card_reference() -> None:
    """The link is an address: a second browser tab, so the first session is untouched."""
    at = _fresh()
    at.query_params[user_docs.PAGE_PARAMETER] = user_docs.CARD_REFERENCE
    at.run()
    _assert_clean(at, "card reference")
    assert at.session_state[PAGE_KEY] == user_docs.CARD_REFERENCE
    assert "TRIM — Static trim condition" in _headings(at)
