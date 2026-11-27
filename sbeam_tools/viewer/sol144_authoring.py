"""Streamlit-free logic for the viewer's SOL 144 / MANVR authoring tab (P12).

Everything here is plain-Python and unit-testable: SID allocation, CAERO1
box-range bounds for AELIST authoring, THRU-aware integer list parsing, and the
candidate model a card edit is tried on before the deck is re-parsed (#113).
The Streamlit layer lives in ``sol144_authoring_ui.py`` and ``session_deck.py``.
"""

import copy
from typing import Any, Optional, Sequence

from sbeam.model.bulk_data import BulkData
from sbeam.model.card_writers import FAMILIES, write_authored_block
from sbeam.parser.bulk_fields import expand_int_list_with_thru
from sbeam.parser.case_control import CaseControl
from sbeam.solver import precheck
from sbeam_tools.cases.maneuver import IncrementSpec

# Canonical AESTAT rigid-body trim-variable labels.
AESTAT_LABELS = [
    "ANGLEA", "SIDES", "ROLL", "PITCH", "YAW",
    "URDD2", "URDD3", "URDD4", "URDD5", "URDD6",
]

# family key -> BulkData attribute (shared with the card writers so the two
# can never disagree about where a family lives).
FAMILY_ATTRS: dict[str, str] = {fam: attr for fam, (attr, _) in FAMILIES.items()}


# family key -> the card's name in a deck and in every message to the user.
CARD_NAMES: dict[str, str] = {
    "aestat": "AESTAT", "aesurf": "AESURF", "aelist": "AELIST", "suport": "SUPORT",
    "trim": "TRIM", "trimvar": "TRIMVAR", "trimobj": "TRIMWGT", "trimcon": "TRIMINEQ",
    "diverg": "DIVERG", "gustlf": "GUSTLF", "masscase": "MASSCASE", "tabled1": "TABLED1",
    "mldtrim": "MANTRIM", "mldtime": "MANTIME", "mldcomd": "MANCMD",
    "mldprnt": "MANPRNT", "mloads": "MANVR",
    "aecomp": "AECOMP", "monpnt1": "MONPNT1", "monpnt3": "MONPNT1", "monsect": "MONSECT",
}

# Families whose cards are identified by a NAME (a string of up to 8 characters), not
# a number, with the prefix a new card's default name takes.
NAMED_FAMILIES: dict[str, str] = {
    "aecomp": "COMP", "monpnt1": "MON", "monpnt3": "MON", "monsect": "SEC",
}
assert set(CARD_NAMES) == set(FAMILIES)

AUTHORED_HEADER = "Authored in the sbeam viewer (SOL 144 / MANVR authoring tab)"


def family_store(bulk: BulkData, family: str) -> Any:
    return getattr(bulk, FAMILY_ATTRS[family])


def key_attr(family: str, card: Any) -> str:
    """The name of the field that identifies a card: GID for SUPORT, else SID/ID/TID."""
    if family == "suport":
        return "gid"
    if family in NAMED_FAMILIES:
        return "name"
    for name in ("sid", "id", "tid"):
        if hasattr(card, name):
            return name
    raise AttributeError(f"{type(card).__name__} has no SID, ID or TID field")


def card_key(family: str, card: Any) -> Any:
    """The tracking key for a card: its SID/ID/TID, GID for SUPORT, NAME for a monitor."""
    return getattr(card, key_attr(family, card))


def next_free_sid(bulk: BulkData, family: str) -> Any:
    """Default ID for a new card: max(existing) + 1, or 1 on an empty family.

    A monitor family is keyed by name: the default is its prefix and the first number
    that no monitor uses (monitor names are unique across MONPNT1 and MONSECT).
    """
    store = family_store(bulk, family)
    if family in NAMED_FAMILIES:
        taken = (set(bulk.aecomps) if family == "aecomp"
                 else set(bulk.monpnt1s) | set(bulk.monpnt3s) | set(bulk.monsects))
        prefix = NAMED_FAMILIES[family]
        return next(f"{prefix}{n}" for n in range(1, len(taken) + 2)
                    if f"{prefix}{n}" not in taken)
    if family == "suport":
        ids = [s.gid for s in store]
    else:
        ids = [k for k in store.keys() if k > 0]
    return (max(ids) + 1) if ids else 1


def apply_card(bulk: BulkData, family: str, card: Any,
               authored: dict[str, set[int]]) -> int:
    """Insert/replace ``card`` in the session model and track it as authored.

    For 'trimcon' pass the full list of constraints sharing one SID.
    Returns the tracking key.
    """
    if family == "trimcon":
        cons = card if isinstance(card, list) else [card]
        key = cons[0].sid
        family_store(bulk, family)[key] = list(cons)
    elif family == "suport":
        key = card.gid
        store = family_store(bulk, family)
        store[:] = [s for s in store if s.gid != key]
        store.append(card)
    else:
        key = card_key(family, card)
        family_store(bulk, family)[key] = card
    authored.setdefault(family, set()).add(key)
    return key


def candidate(
    bulk: BulkData,
    authored: dict[str, set[int]],
    changes: Sequence[tuple[str, Any]] = (),
    deletes: Sequence[tuple[str, int]] = (),
) -> tuple[BulkData, dict[str, set[int]]]:
    """The model and the authored-card record as they would be after an edit.

    The session model is not touched: the result is a shallow copy whose card-family
    stores are new containers.  It exists only to write the authored cards as text;
    the model the session keeps is the one the parser returns for that text (#113).
    """
    trial = copy.copy(bulk)
    for attr in FAMILY_ATTRS.values():
        setattr(trial, attr, copy.copy(getattr(bulk, attr)))
    record = {family: set(keys) for family, keys in authored.items()}
    for family, key in deletes:
        delete_card(trial, family, key, record)
    for family, card in changes:
        apply_card(trial, family, card, record)
    return trial, record


def loaded_card_edits(
    file_sids: Optional[dict[str, set[int]]],
    changes: Sequence[tuple[str, Any]] = (),
    deletes: Sequence[tuple[str, int]] = (),
) -> list[str]:
    """A message for each edit that would change or remove a card of the loaded deck.

    A loaded card is not changed in place.  The deck text the viewer runs and exports
    is the loaded deck plus the authored cards; an edited copy of a loaded card would
    be a second card with the same ID beside the original.  The edit is saved under a
    new ID instead ("Save as new SID").  The parser refuses most such duplicates, but
    not a second SUPORT on one grid, so the rule is checked here for every family.
    """
    file_sids = file_sids or {}
    touched = [(family, card_key(family, card[0] if isinstance(card, list) else card))
               for family, card in changes]
    touched += list(deletes)
    return [
        f"{CARD_NAMES[family]} {key} comes from the loaded deck and is not changed "
        "here: the deck would then hold two cards with that ID. Use 'Save as new "
        "SID', then select the new card where the old one was used."
        for family, key in dict.fromkeys(touched)
        if key in file_sids.get(family, set())
    ]


def cards_text(bulk: BulkData, authored: dict[str, set[int]],
               blocks: Optional[dict[str, str]] = None) -> str:
    """The bulk text the viewer adds to the loaded deck: authored cards, then each
    named block another panel contributes (the aero-correction cards)."""
    parts = [write_authored_block(bulk, authored, AUTHORED_HEADER)]
    parts += [text for _, text in sorted((blocks or {}).items()) if text]
    return "".join(part if part.endswith("\n") else part + "\n" for part in parts if part)


def delete_card(bulk: BulkData, family: str, key: int,
                authored: dict[str, set[int]]) -> None:
    """Remove a card from the session model and from the authored set."""
    store = family_store(bulk, family)
    if family == "suport":
        store[:] = [s for s in store if s.gid != key]
    else:
        store.pop(key, None)
    authored.get(family, set()).discard(key)


def caero_box_ranges(bulk: BulkData) -> list[tuple[int, int]]:
    """Valid AELIST box-ID ranges: [EID, EID + NSPAN*NCHORD - 1] per CAERO1."""
    ranges = []
    for c in bulk.caero1s.values():
        n = c.nspan * c.nchord
        if n > 0:
            ranges.append((c.eid, c.eid + n - 1))
    return sorted(ranges)


def boxes_outside_ranges(elements: list[int],
                         ranges: list[tuple[int, int]]) -> list[int]:
    """Box IDs not covered by any CAERO1 range (empty ranges = no check)."""
    if not ranges:
        return []
    return [e for e in elements
            if not any(lo <= e <= hi for lo, hi in ranges)]


def expand_int_tokens(text: str) -> list[int]:
    """Parse '1101 THRU 1112, 1120' style text into a flat integer list.

    Uses the parser's own THRU expansion so UI entry and BDF cards agree.
    Raises ValueError on non-integer tokens.
    """
    tokens = [t for t in text.replace(",", " ").split() if t]
    return expand_int_list_with_thru(tokens)


def parse_float_list(text: str) -> list[float]:
    """Parse a whitespace/comma-separated float list."""
    return [float(t) for t in text.replace(",", " ").split() if t]


def label_options(bulk: BulkData, modal_only: bool = False) -> list[str]:
    """Trim-variable labels an MANCMD/TRIM row may use.

    ``modal_only`` restricts to AESURF labels — under the modal (free-flight)
    solver, rigid-state AESTAT labels are outputs and commanding one is a
    hard parse error.
    """
    surf = [s.label for s in bulk.aesurfs.values()]
    if modal_only:
        return sorted(surf)
    stat = [a.label for a in bulk.aestats.values()]
    return sorted(set(stat + surf))


# ---------------------------------------------------------------------------
# Pre-launch check.  Card rules are the parser's (every authored card is re-parsed,
# #113) and case-control rules are the solver package's (#124); the viewer states
# neither.
# ---------------------------------------------------------------------------

def snapshot_family_ids(bulk: BulkData) -> dict[str, set[int]]:
    """IDs per family as loaded from the deck: the cards that are not changed in place."""
    out: dict[str, set[int]] = {}
    for family in FAMILY_ATTRS:
        store = family_store(bulk, family)
        if family == "suport":
            out[family] = {s.gid for s in store}
        else:
            out[family] = set(store.keys())
    return out


def check_case_control(
    bulk: BulkData,
    cc: Optional[CaseControl],
    unresolved_increments: Optional[list[IncrementSpec]] = None,
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a SOL 144 case control against its model.

    Errors block Launch and export; warnings inform.  The rules are the solver
    package's (``sbeam.solver.precheck``, #124), the same ones the command line applies
    before a run.  The one check added here is viewer state: a command still written
    as an increment from trim, which the two-pass builder has not yet resolved.
    """
    if cc is None:
        return [], []
    errors, warns = precheck.check_case_control(cc, bulk)
    for key in (unresolved_increments or []):
        errors.append(
            f"MANVR {key.mloads_sid} {key.label}: unresolved increment command — resolve "
            "to absolute TABLED1s (after a solve) before exporting.")
    return errors, warns


def suggest_run_name(stem: str, cc: Optional[CaseControl]) -> str:
    """Filesystem-safe driver filename for an exported SOL 144 run deck."""
    base = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                   for ch in (stem or "model"))
    kinds = set()
    for sc in (cc.subcases if cc is not None else []):
        if sc.mloads_sid is not None:
            kinds.add("mloads")
        elif sc.gustlf_sid is not None:
            kinds.add("gust")
        elif sc.diverg_sid is not None and sc.trim_sid is None:
            kinds.add("diverg")
        elif sc.trim_sid is not None:
            kinds.add("trim")
    suffix = "_".join(sorted(kinds)) or "run"
    return f"{base}_{suffix}.bdf"
