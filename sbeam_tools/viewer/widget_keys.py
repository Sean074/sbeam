"""Widget keys that belong to the deck that is open (#123).

Streamlit identifies a keyed widget by its key alone, and keeps the widget's value for
as long as that key is drawn.  A viewer widget keyed ``sc_trim_sid_1`` therefore kept the
previous deck's choice after another deck was opened: the subcase editor showed the old
selections, and Apply wrote them into the new deck.

Every widget whose value depends on the model takes its key through :func:`wk`, which
adds the number of the deck opened in this session.  A new deck means new keys, so new
widgets, each starting from the new deck's values.  The first deck of a session keeps
the plain key.
"""
from __future__ import annotations

import streamlit as st

DECK_GENERATION = "_deck_generation"


def wk(key: str) -> str:
    """``key`` for the first deck opened in the session, ``key#n`` for the n-th."""
    generation = st.session_state.get(DECK_GENERATION, 0)
    return key if generation <= 1 else f"{key}#{generation}"
