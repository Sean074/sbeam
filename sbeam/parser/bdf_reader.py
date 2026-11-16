"""BDF reader entry points and bulk-card dispatch.

``parse_bdf`` / ``parse_bulk_file`` / ``parse_bulk_data`` are the public API
(``docs/10_standard/11_python_api.md``).  Card handlers live in family modules
(``bulk_structural``, ``bulk_aero``, ``bulk_trim``); cross-card checks run once every card
is read (``bulk_xref``); field utilities are in ``bulk_fields`` (#48).
"""
import difflib
import os
import warnings
from collections import Counter

from sbeam.model.bulk_data import BulkData
from sbeam.parser import bulk_aero, bulk_structural, bulk_trim
from sbeam.parser.bulk_fields import ContHandler, FieldHandler, MultiHandler, iter_cards
from sbeam.parser.bulk_xref import check_frame_orientations, cross_reference
from sbeam.types import StrPath
from sbeam.parser.case_control import CaseControl, parse_case_control

_IGNORED_KEYWORDS = frozenset({"BEGIN", "BEGINBULK", "ENDDATA"})

#: NASTRAN bulk cards sbeam recognises but does not implement (issue #45).  A deck
#: carrying any of them is **refused** at parse: solving with the card silently dropped
#: would change the answer (missing loads, elements, constraints or frames).  The value
#: is what the deck would lose.  Since #55 any keyword that is neither handled nor in
#: ``_HARMLESS_CARDS`` is refused too, as an unknown card (a typo such as FROCE is a
#: dropped load).  Field reference: ``docs/10_standard/02_card_reference.md``
#: "Unsupported cards".
_UNSUPPORTED_CARDS: dict[str, str] = {
    # distributed / element loads
    "PLOAD": "pressure load", "PLOAD1": "distributed CBAR load",
    "PLOAD2": "pressure load", "PLOAD4": "pressure load",
    # other static loads
    "RFORCE": "rotational inertia load", "SLOAD": "scalar load",
    "ACCEL": "acceleration load", "ACCEL1": "acceleration load",
    "TEMP": "thermal load", "TEMPD": "thermal load", "DEFORM": "enforced deformation",
    "SPCD": "enforced displacement",
    # dynamic loads
    "DLOAD": "dynamic load", "DAREA": "dynamic load scale",
    "TLOAD1": "transient load", "TLOAD2": "transient load",
    "RLOAD1": "frequency-response load", "RLOAD2": "frequency-response load",
    # elements / properties / materials
    "CBEAM": "beam element", "PBEAM": "beam property", "PBEAML": "beam property",
    "PBARL": "bar property by shape", "CTUBE": "tube element", "PTUBE": "tube property",
    "CELAS1": "spring element", "CELAS2": "spring element", "PELAS": "spring property",
    "CONM1": "mass element", "CQUAD4": "shell element", "CTRIA3": "shell element",
    "PSHELL": "shell property", "MAT2": "anisotropic material", "MAT8": "orthotropic material",
    # coordinate systems
    "CORD1R": "coordinate system", "CORD1C": "coordinate system", "CORD1S": "coordinate system",
    "CORD2C": "coordinate system", "CORD2S": "coordinate system",
    # constraints
    "MPC": "multipoint constraint", "MPCADD": "constraint set", "SPCADD": "constraint set",
    "RBE1": "rigid element",
    # direct matrix input (#55): MSC decks carry aero corrections this way
    "DMI": "direct matrix input (for W2GJ/WKK aero corrections use the native W2GJ/WKK cards)",
    "DMIG": "direct matrix input at grid points", "DMIAX": "direct matrix input",
    "DMIJ": "aero direct matrix input (use the native W2GJ/WKK cards)",
    "DMIJI": "aero direct matrix input (use the native W2GJ/WKK cards)",
    "DMIK": "aero direct matrix input (use the native W2GJ/WKK cards)",
    # damping
    "TABDMP1": "modal damping table (the MLOADS transient takes its damping from ZETA)",
}

#: Bulk keywords that only control listing or output and never change an answer: these
#: are ignored with a ``UserWarning``.  Anything else unknown is refused (#55).  Add a
#: keyword here only with that justification.
_HARMLESS_CARDS: dict[str, str] = {
    "ECHOON": "bulk-data echo control", "ECHOOFF": "bulk-data echo control",
}

_FAMILIES = (bulk_structural, bulk_aero, bulk_trim)
_FIELD_HANDLERS: dict[str, FieldHandler] = {}
_CONT_HANDLERS: dict[str, ContHandler] = {}
_MULTI_HANDLERS: dict[str, MultiHandler] = {}
for _family in _FAMILIES:
    _FIELD_HANDLERS.update(_family.FIELD_HANDLERS)
    _CONT_HANDLERS.update(_family.CONT_HANDLERS)
    _MULTI_HANDLERS.update(_family.MULTI_HANDLERS)

#: Every bulk keyword sbeam implements.  A keyword in two tables would be dispatched by
#: whichever is checked first, so registration must be unique across all three.
HANDLED_CARDS: frozenset[str] = frozenset(_FIELD_HANDLERS) | frozenset(_CONT_HANDLERS) | frozenset(_MULTI_HANDLERS)
assert len(HANDLED_CARDS) == len(_FIELD_HANDLERS) + len(_CONT_HANDLERS) + len(_MULTI_HANDLERS), \
    "a bulk keyword is registered by more than one handler table"


def _read_cards(lines: list[str]) -> BulkData:
    """Read every card into a BulkData, checking each card on its own (phase 1 of 2).

    No reference between cards is checked here: that is ``cross_reference``, once every
    card is read, which is what makes the deck order-independent (#51).  Called on its
    own only by tests that read a card fragment with no model around it.
    """
    bulk = BulkData()
    unsupported: Counter[str] = Counter()
    unknown: Counter[str] = Counter()

    # Handlers are called directly from this frame, which parse_bulk_data calls: their
    # warnings' stacklevel counts both frames, so it points at parse_bulk_data's caller.
    for keyword, fields, conts in iter_cards(lines):
        if keyword in _IGNORED_KEYWORDS:
            continue
        if keyword in _UNSUPPORTED_CARDS:
            # Counted, not raised: the deck is refused once with the full list below.
            unsupported[keyword] += 1
        elif keyword in _FIELD_HANDLERS:
            _FIELD_HANDLERS[keyword](fields, bulk)
        elif keyword in _CONT_HANDLERS:
            _CONT_HANDLERS[keyword](fields, conts[0] if conts else None, bulk)
        elif keyword in _MULTI_HANDLERS:
            _MULTI_HANDLERS[keyword](fields, conts, bulk)
        elif keyword in _HARMLESS_CARDS:
            warnings.warn(f"BDF card '{keyword}' ignored ({_HARMLESS_CARDS[keyword]})",
                          UserWarning, stacklevel=3)
        else:
            # Unknown: a typo or a card sbeam has never heard of.  Skipping it used to be a
            # warning, which a dropped load or matrix hid behind (#55).
            unknown[keyword] += 1

    parts = []
    if unsupported:
        parts.append("Unsupported bulk data card(s): " + ", ".join(
            f"{kw} x{n} ({_UNSUPPORTED_CARDS[kw]})" for kw, n in sorted(unsupported.items())))
    if unknown:
        parts.append("Unknown bulk data card(s): " + ", ".join(
            f"{kw} x{n}{_did_you_mean(kw)}" for kw, n in sorted(unknown.items())))
    if parts:
        raise ValueError(
            ". ".join(parts) + ". sbeam would solve with these cards dropped; remove them, "
            "correct a misspelt keyword, or model the content with supported cards "
            "(02_card_reference.md, 'Unsupported cards').")
    return bulk


def _did_you_mean(keyword: str) -> str:
    close = difflib.get_close_matches(keyword, sorted(HANDLED_CARDS | set(_HARMLESS_CARDS)),
                                      n=1, cutoff=0.7)
    return f" (did you mean {close[0]}?)" if close else ""


def parse_bulk_data(lines: list[str]) -> BulkData:
    """Parse BDF bulk data lines into a BulkData object.

    Supports free-field (comma-separated) and fixed-field (8-character column) formats,
    with cards in any order.
    Issues UserWarning for the listing-only cards in ``_HARMLESS_CARDS`` and for PARAMs
    sbeam does not read.
    Raises ValueError for cards in ``_UNSUPPORTED_CARDS`` (known NASTRAN cards sbeam does
    not implement, #45), any other unknown keyword (#55), duplicate IDs, invalid DOF
    strings, and any reference to a card the deck does not define (#51).
    """
    bulk = _read_cards(lines)
    cross_reference(bulk)

    # Resolve all grid positions from their CP system into global CID 0; frame checks
    # that need a resolved CORD2R chain run here too (the parser's one assembly import)
    from sbeam.assembly.coord_transform import get_transform, resolve_grid_positions
    resolve_grid_positions(bulk)
    check_frame_orientations(bulk, get_transform)

    return bulk


def parse_bulk_file(filepath: StrPath) -> BulkData:
    """Parse a bulk-data-only file and return a BulkData object.

    Handles files with or without a BEGIN BULK header line.  Does not
    require or parse any case control section — useful for loading model
    geometry into the viewer before case control has been defined.

    Raises FileNotFoundError if the file does not exist.
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    # If a BEGIN BULK line is present, discard everything before it
    bulk_start = 0
    for i, line in enumerate(lines):
        idx = line.find("$")
        clean = (line[:idx] if idx >= 0 else line).strip()
        if clean.upper().startswith("BEGIN"):
            bulk_start = i + 1
            break

    return parse_bulk_data([line.rstrip("\n") for line in lines[bulk_start:]])


def parse_bdf(filepath: StrPath) -> tuple[CaseControl, BulkData]:
    """Read a BDF file and return (CaseControl, BulkData).

    Handles single-file models (bulk data after BEGIN BULK in the same file)
    and multi-file models (one or more INCLUDEs in the case control section, each
    naming a bulk data file).  The bulk is the **concatenation** of every included
    file, in the order the INCLUDEs appear, followed by any inline bulk data after
    BEGIN BULK.  That lets a driver deck compose a shared bulk with a small overlay
    without duplicating the shared part (e.g. the Cessna 210 flagship bulk plus its
    body-panel overlay).

    Raises FileNotFoundError if the main file or an INCLUDE file does not exist.
    Raises ValueError if the SOL value is not supported (101 or 103).
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    # Split on the first BEGIN BULK line
    begin_bulk_idx = None
    for i, line in enumerate(lines):
        idx = line.find("$")
        clean = (line[:idx] if idx >= 0 else line).strip()
        if clean.upper().startswith("BEGIN"):
            begin_bulk_idx = i
            break

    if begin_bulk_idx is None:
        cc_lines = lines
        bulk_lines = []
    else:
        cc_lines = lines[:begin_bulk_idx]
        bulk_lines = lines[begin_bulk_idx + 1:]

    cc = parse_case_control([line.rstrip("\n") for line in cc_lines])

    if cc.includes:
        base_dir = os.path.dirname(os.path.abspath(filepath))
        included_lines: list[str] = []
        for inc in cc.includes:
            include_path = inc if os.path.isabs(inc) else os.path.join(base_dir, inc)
            if not os.path.exists(include_path):
                raise FileNotFoundError(f"INCLUDE file not found: {inc!r}")
            with open(include_path, "r") as fh:
                included_lines.extend(fh.readlines())
        # Included files first, then any inline bulk after BEGIN BULK.  Inline bulk
        # used to be discarded whenever an INCLUDE was present — a silent-input
        # hazard: cards typed into the driver deck vanished without a word.
        bulk_lines = included_lines + bulk_lines

    bulk = parse_bulk_data([line.rstrip("\n") for line in bulk_lines])
    return cc, bulk
