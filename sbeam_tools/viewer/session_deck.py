"""The deck the viewer session holds, as text, and the one way to change its cards (#113).

**What runs is what exports.**  The session's model is always the parser's reading of
one text: the loaded deck's bulk section, then the cards authored in the viewer, then
any block another panel contributes (the aero-correction cards).  A card edit is not
applied to the model in memory.  It is written into that text, the text is parsed, and
the parser's result replaces the session model.  If the parser refuses the text, the
edit is refused with the parser's message and nothing changes.

So a rule the parser makes for a card holds for a card typed into a form, with no copy
of the rule in the viewer, and the deck the Run button solves is the deck the export
writes.
"""
from __future__ import annotations

import warnings
from typing import Any, Optional, Sequence

import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file
from sbeam.parser.case_control import CaseControl
from sbeam_tools.viewer import sol144_authoring as logic
from sbeam_tools.viewer.case_control_ui import deck_bulk_section, export_bdf_text

# Results and caches that describe the model as it was before a card changed.
_STALE_ON_CHANGE = (
    "sol101_result", "sol103_result", "sol144_result", "sol144_diverg_result",
    "maneuver_result", "aero_model_144", "aero_model", "aero_result", "aero_result_unc",
)
FLASH = "_deck_flash"


def _bulk_only_body(source_text: str) -> str:
    """A bulk-data-only file's cards: its lines up to ENDDATA."""
    lines: list[str] = []
    for line in source_text.splitlines():
        if line.split("$", 1)[0].strip().upper().startswith("ENDDATA"):
            break
        lines.append(line)
    return "\n".join(lines)


def deck_text(cc: Optional[CaseControl], source_text: str, cards: str) -> str:
    """The session's deck: ``cc``, the loaded deck's bulk data, then ``cards``.

    With no case control (a bulk-data-only file, none defined yet) the text is bulk data
    alone.  The bulk data is always written inline here, also for a bulk-data-only file
    whose export INCLUDEs it by name, because this text is the one that is parsed.
    """
    section = deck_bulk_section(source_text)
    if section is None:
        section = _bulk_only_body(source_text)
    if cc is not None:
        return export_bdf_text(cc, bulk_section=section, authored_block=cards)
    body = [section] + ([cards.rstrip("\n")] if cards.strip() else [])
    return "\n".join(["BEGIN BULK", *body, "ENDDATA"]) + "\n"


def parse_deck_text(text: str, has_case_control: bool, deck_path: Optional[str],
                    name: str) -> tuple[BulkData, list[str]]:
    """Parse the session deck; return the model and the parser's warnings.

    ``deck_path`` is where the loaded deck stands, so its relative INCLUDEs resolve; an
    uploaded deck has none (and no INCLUDE, or it would not have loaded).
    """
    where = deck_path or name or "deck.bdf"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if has_case_control:
            _, bulk = parse_bdf(where, text=text)
        else:
            bulk = parse_bulk_file(where, text=text)
    return bulk, [str(w.message) for w in caught]


def session_cards_text(bulk: BulkData) -> str:
    """The cards the session adds to the loaded deck, as the export writes them."""
    return logic.cards_text(
        bulk, st.session_state.get("authored_cards") or {},
        st.session_state.get("deck_blocks") or {})


def commit(
    bulk: BulkData,
    *,
    changes: Sequence[tuple[str, Any]] = (),
    deletes: Sequence[tuple[str, int]] = (),
    blocks: Optional[dict[str, Optional[str]]] = None,
    done: str = "",
    panel: str = "authoring",
) -> bool:
    """Try an edit on the deck text; on success replace the session model and rerun.

    ``changes`` are ``(family, card)`` pairs to add or replace, ``deletes`` are
    ``(family, key)`` pairs, ``blocks`` sets (or with ``None`` removes) a named block of
    card text.  Returns False, with the reason shown, when the edit touches a loaded
    card or the parser refuses the resulting deck; the session is then unchanged.  On
    success it does not return: the run restarts on the new model, and ``panel`` shows
    ``done`` (``show_flash``).
    """
    ss = st.session_state
    source = ss.get("_uploaded_source_text")
    if source is None:
        st.error("This session has no deck text to edit: open the deck from disk or "
                 "upload it, then author cards.")
        return False
    problems = logic.loaded_card_edits(ss.get("file_card_sids"), changes, deletes)
    for message in problems:
        st.error(message)
    if problems:
        return False

    trial, record = logic.candidate(bulk, ss.get("authored_cards") or {}, changes, deletes)
    new_blocks = dict(ss.get("deck_blocks") or {})
    for name, text in (blocks or {}).items():
        if text:
            new_blocks[name] = text
        else:
            new_blocks.pop(name, None)
    cc = ss.get("case_control")
    text = deck_text(cc, source, logic.cards_text(trial, record, new_blocks))
    try:
        parsed, parse_warnings = parse_deck_text(
            text, cc is not None, ss.get("_deck_path"), ss.get("_uploaded_filename") or "")
    except Exception as exc:                     # the parser's refusal is the message
        st.error(f"Not applied. The deck would not parse: {exc}")
        return False

    ss.bulk_data = parsed
    ss.authored_cards = record
    ss.deck_blocks = new_blocks
    ss._parse_warnings = parse_warnings
    for key in _STALE_ON_CHANGE:
        ss[key] = None
    ss[FLASH] = (panel, done)
    st.rerun()
    return True                                  # not reached: st.rerun() raises


def show_flash(panel: str = "authoring") -> None:
    """Show, once, the message of the edit ``panel`` made before this run restarted."""
    owner, message = st.session_state.get(FLASH) or ("", "")
    if owner == panel:
        del st.session_state[FLASH]
        if message:
            st.success(message)
