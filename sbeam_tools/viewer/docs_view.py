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
