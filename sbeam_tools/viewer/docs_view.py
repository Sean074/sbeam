"""The viewer's Documentation page (#129): the pages shipped with the package, drawn.

This module only draws.  Which pages exist, where they are read from, where each link
goes and where a page is cut into headings are decided in
``sbeam_tools/common/user_docs.py``, which has no Streamlit in it.

What a browser showed on 2026-11-27 (Streamlit 1.50), and why the page is drawn this way:

- Math renders (KaTeX), if a display equation's ``$$`` fences stand on lines of their
  own.  ``tests/tools/test_user_docs.py`` holds the shipped pages to that.
- An image with a relative path does not load; a data address does.
- A link in Markdown opens in a new browser tab, and a new tab is a new session.  So a
  link to another page opens a second viewer showing that page, and the first keeps its
  deck.  Inside one session the page is chosen from the list.
- Streamlit's own heading anchors are not predictable where a heading holds math or
  non-ASCII letters, so each level 1 to 3 heading is drawn with the anchor GitHub gives
  it; the links in the pages were written against those.
"""
from __future__ import annotations

from importlib import metadata
from pathlib import Path

import streamlit as st

from sbeam_tools.common import user_docs

#: Session key of the page shown.  It is not a model widget: it survives a new deck.
PAGE_KEY = "docs_page"
#: Session key of the search box, and of the heading to scroll to on the next run.
SEARCH_KEY = "docs_search"
SCROLL_KEY = "_docs_scroll_to"
#: Search results drawn; the rest are counted.
MAX_RESULTS = 20


def installed_version() -> str:
    """The installed sbeam version; links to files that are not shipped go to its tag."""
    try:
        return metadata.version("sbeam")
    except metadata.PackageNotFoundError:      # run from a tree that was never installed
        return "main"


@st.cache_data(show_spinner=False)
def _blocks(page: str, root: str, version: str) -> list[user_docs.Block]:
    return user_docs.page_blocks(page, Path(root), version)


@st.cache_data(show_spinner=False)
def _labels(root: str) -> dict[str, str]:
    """page -> "Section — page title", for the page list."""
    out = {}
    for section, group in user_docs.sections(Path(root)):
        for page in group:
            title = user_docs.page_title(user_docs.read_page(page, Path(root)), page)
            out[page] = f"{section} — {title}"
    return out


@st.cache_data(show_spinner=False)
def _reference_anchor(heading_start: str, root: str) -> str:
    return user_docs.reference_anchor(heading_start, Path(root))


def reference_link(heading_start: str, label: str | None = None) -> None:
    """A one-line link to a section of the card reference, for a form (#131).

    ``heading_start`` is how the section's heading starts: a card name, or a section
    title.  The link opens the Documentation page in a second browser tab, so the form
    and everything typed into it stay as they are.  The form states no field rule of
    its own; the card reference is the one place they are written.
    """
    try:
        root = user_docs.docs_root()
    except FileNotFoundError:
        return                                   # no documentation in this installation
    anchor = _reference_anchor(heading_start, str(root))
    url = user_docs.page_url(user_docs.CARD_REFERENCE, anchor)
    st.caption(f"Fields, defaults and rules: [{label or heading_start} in the card reference]({url})")


def _open_result(page: str, anchor: str) -> None:
    """Button callback: show ``page`` and scroll to ``anchor`` on the run that follows."""
    st.session_state[PAGE_KEY] = page
    st.session_state[SCROLL_KEY] = anchor


def _render_search(root: Path, labels: dict[str, str]) -> None:
    query = st.text_input(
        "Search the documentation", key=SEARCH_KEY,
        placeholder="A card name, a keyword or a phrase",
        help="Not case-sensitive. A single word is matched as a whole word: "
             "TRIM does not find TRIMVAR.")
    if not query.strip():
        return
    hits = user_docs.search(query, root)
    if not hits:
        st.info(f"Nothing in the documentation matches “{query.strip()}”.")
        return
    with st.expander(f"{len(hits)} section(s) match “{query.strip()}”", expanded=True):
        for i, hit in enumerate(hits[:MAX_RESULTS]):
            title = labels[hit.page].split(" — ", 1)[1]
            heading = user_docs.plain_title(hit.heading) or "(top of the page)"
            st.button(f"{title} › {heading}", key=f"docs_hit_{i}", on_click=_open_result,
                      args=(hit.page, hit.anchor),
                      help=f"{hit.count} matching line(s). First: {hit.context}")
        if len(hits) > MAX_RESULTS:
            st.caption(f"{len(hits) - MAX_RESULTS} more section(s) are not listed; "
                       "narrow the search.")


def _scroll_to(anchor: str) -> None:
    """Scroll the browser to a heading of the page just drawn.  Streamlit has no call
    for this; a zero-height component runs one line of script in the page."""
    import json
    from streamlit.components.v1 import html
    html("<script>const e = window.parent.document.getElementById("
         f"{json.dumps(anchor)}); if (e) e.scrollIntoView();</script>", height=0)


def render_documentation() -> None:
    """Draw the page list, the chosen page's contents list and the page."""
    try:
        root = user_docs.docs_root()
    except FileNotFoundError as exc:
        st.info(str(exc))
        return
    labels = _labels(str(root))
    pages = list(labels)

    if PAGE_KEY not in st.session_state:
        # A link from another page of the documentation names the page to open.
        asked = st.query_params.get(user_docs.PAGE_PARAMETER)
        st.session_state[PAGE_KEY] = asked if asked in labels else pages[0]
    elif st.session_state[PAGE_KEY] not in labels:
        st.session_state[PAGE_KEY] = pages[0]

    _render_search(root, labels)
    page = st.selectbox("Page", pages, format_func=labels.__getitem__, key=PAGE_KEY)
    version = installed_version()
    blocks = _blocks(page, str(root), version)

    contents = [b for b in blocks if b.level in (2, 3)]
    if contents:
        with st.expander("On this page"):
            st.markdown("\n".join(
                f"{'  ' * (b.level - 2)}- [{user_docs.plain_title(b.text)}](#{b.anchor})" for b in contents))
    st.caption(f"sbeam {version} · `{page}` · a link to another page opens it in a new tab")

    for block in blocks:
        if block.level == 0:
            st.markdown(block.text)
        elif block.level == 1:
            st.title(block.text, anchor=block.anchor)
        elif block.level == 2:
            st.header(block.text, anchor=block.anchor)
        else:
            st.subheader(block.text, anchor=block.anchor)

    pending = st.session_state.pop(SCROLL_KEY, None)
    if pending:
        _scroll_to(pending)
