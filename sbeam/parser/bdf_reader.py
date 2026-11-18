"""BDF reader entry points and bulk-card dispatch.

``parse_bdf`` / ``parse_bulk_file`` / ``parse_bulk_data`` are the public API
(``docs/10_standard/11_python_api.md``).  Card handlers live in family modules
(``bulk_structural``, ``bulk_aero``, ``bulk_trim``); cross-card checks run once every card
is read (``bulk_xref``); field utilities are in ``bulk_fields`` (#48).
"""
import difflib
import os
import re
import warnings
from collections import Counter
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.parser import bulk_aero, bulk_structural, bulk_trim
from sbeam.parser.bulk_fields import ContHandler, FieldHandler, MultiHandler, iter_cards, split_line
from sbeam.parser.bulk_xref import check_frame_orientations, cross_reference
from sbeam.types import StrPath
from sbeam.parser.case_control import CaseControl, case_control_command, parse_case_control


#: INCLUDE nesting limit: "the nested depth level must not be greater than 10" (QRG p.1984).
_MAX_INCLUDE_DEPTH = 10
_INCLUDE = re.compile(r"\s*INCLUDE\b", re.IGNORECASE)

#: NASTRAN bulk cards sbeam recognises but does not implement (issue #45).  A deck
#: carrying any of them is **refused** at parse: solving with the card silently dropped
#: would change the answer (missing loads, elements, constraints or frames).  The value
#: is what the deck would lose.  Since #55 any keyword that is neither handled nor in
#: ``_HARMLESS_CARDS`` is refused too, as an unknown card (a typo such as FROCE is a
#: dropped load).  Field reference: ``docs/10_standard/02_card_reference.md``
#: "Unsupported cards".
_UNSUPPORTED_CARDS: dict[str, str] = {
    # MSC's Mass Combination card (QRG 2024.1 PDF p.2018): ID S0 S1 ID1 S2 ID2 ...  sbeam's
    # payload card had this name with another layout until #78 and read an MSC card as
    # label and scale; it is now MASSCASE
    "MASSSET": "MSC mass combination, not implemented; sbeam's payload / mass-case card "
               "is MASSCASE, which was named MASSSET before #78: rename the card",
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
        if keyword in _UNSUPPORTED_CARDS:
            # Counted, not raised: the deck is refused once with the full list below.
            unsupported[keyword] += 1
        elif keyword in _FIELD_HANDLERS:
            _refuse_unread(keyword, fields, conts, 0)
            _FIELD_HANDLERS[keyword](fields, bulk)
        elif keyword in _CONT_HANDLERS:
            _refuse_unread(keyword, fields, conts, 1)
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


def _refuse_unread(keyword: str, fields: list[str], conts: list[list[str]], reads: int) -> None:
    """Refuse a card with data on a continuation line its handler does not read (#63).

    A FIELD handler reads the first line only and a CONT handler one continuation; before
    #63 any further line was dropped without a message (LOAD components past the second
    line, AESURF limits, EIGRL options, MSC's second MONPNT1 line).  Blank rows are fine.
    """
    for n, cont in enumerate(conts[reads:], start=reads + 1):
        if any(f.strip() for f in cont[1:]):
            ident = fields[1].strip() if len(fields) > 1 else ""
            raise ValueError(
                f"{keyword} {ident}: continuation line {n} "
                f"({', '.join(f.strip() for f in cont[1:]).rstrip(', ')}) is not read by sbeam "
                f"and would be dropped; {keyword} takes "
                f"{'no continuation' if reads == 0 else 'one continuation line'} here "
                "(02_card_reference.md)")


def _did_you_mean(keyword: str) -> str:
    close = difflib.get_close_matches(keyword, sorted(HANDLED_CARDS | set(_HARMLESS_CARDS)),
                                      n=1, cutoff=0.7)
    return f" (did you mean {close[0]}?)" if close else ""


def parse_bulk_data(lines: list[str]) -> BulkData:
    """Parse BDF bulk data lines into a BulkData object.

    Supports free-field (comma-separated) and fixed-field (8-character column) formats,
    with cards in any order.  A BEGIN BULK line is skipped and reading stops at ENDDATA
    (#81).
    Issues UserWarning for the listing-only cards in ``_HARMLESS_CARDS`` and for PARAMs
    sbeam does not read.
    Raises ValueError for cards in ``_UNSUPPORTED_CARDS`` (known NASTRAN cards sbeam does
    not implement, #45), any other unknown keyword (#55), duplicate IDs, invalid DOF
    strings, any reference to a card the deck does not define (#51), a card after
    ENDDATA and a BEGIN line that opens any section but the main bulk data (#81).
    """
    bulk = _read_cards(_bulk_section(lines))
    cross_reference(bulk)

    # Resolve all grid positions from their CP system into global CID 0; frame checks
    # that need a resolved CORD2R chain run here too (the parser's one assembly import)
    from sbeam.assembly.coord_transform import get_transform, resolve_grid_positions
    resolve_grid_positions(bulk)
    check_frame_orientations(bulk, get_transform)

    return bulk


def parse_bulk_file(filepath: StrPath) -> BulkData:
    """Parse a bulk-data-only file and return a BulkData object.

    Handles files with or without a BEGIN BULK header line; INCLUDEs are expanded as in
    ``parse_bdf``.  Does not require or parse any case control section — useful for
    loading model geometry into the viewer before case control has been defined.

    Raises FileNotFoundError if the file or an INCLUDE file does not exist.
    """
    lines, origins, _ = _read_input(filepath)
    begin = _begin_bulk_index(lines)
    start = 0 if begin is None else begin + 1
    return parse_bulk_data(_bulk_section(lines[start:], origins[start:]))


def parse_bdf(filepath: StrPath) -> tuple[CaseControl, BulkData]:
    """Read a BDF file and return (CaseControl, BulkData).

    The file is read as NASTRAN reads it (#81): every INCLUDE is replaced by the text of
    its file wherever it stands, nested up to 10 deep (QRG p.1984); the case control is
    everything above BEGIN BULK and the bulk data everything below it, up to ENDDATA.  A
    driver deck composes a shared bulk with an overlay by INCLUDEing both after BEGIN
    BULK (e.g. the Cessna 210 flagship bulk plus its body-panel overlay); the files
    those INCLUDEs name are ``CaseControl.includes``.

    Raises FileNotFoundError if the main file or an INCLUDE file does not exist.
    Raises ValueError for bulk data INCLUDEd above BEGIN BULK, a BEGIN line other than
    BEGIN BULK, data after ENDDATA, and everything ``parse_case_control`` and
    ``parse_bulk_data`` refuse.
    """
    lines, origins, includes = _read_input(filepath)
    begin = _begin_bulk_index(lines)
    if begin is None:
        begin = len(lines)
    _refuse_included_bulk_in_case_control(lines[:begin], origins[:begin], filepath)
    cc = parse_case_control(lines[:begin])
    cc.includes = [name for at, name in includes if at > begin]
    cc.include = cc.includes[0] if cc.includes else None
    bulk = parse_bulk_data(_bulk_section(lines[begin + 1:], origins[begin + 1:]))
    return cc, bulk


# ---------------------------------------------------------------------------
# File structure: INCLUDE, BEGIN BULK, ENDDATA (#81)
# ---------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    idx = line.find("$")
    return (line[:idx] if idx >= 0 else line).strip()


def _begin_bulk_index(lines: list[str]) -> Optional[int]:
    """Index of the BEGIN BULK line, or None; a BEGIN that opens another section is refused."""
    for i, line in enumerate(lines):
        if _strip_comment(line).upper().startswith("BEGIN"):
            _refuse_partitioned_bulk(line)
            return i
    return None


def _refuse_partitioned_bulk(line: str) -> None:
    """Refuse a BEGIN line that opens any section but the main bulk data.

    ``BEGIN SUPER=seid``, ``BEGIN BULK TRMC=id``, ``BEGIN AUXMODEL=id`` and the other
    describers open a separate Bulk Data Section (QRG p.286–287).  sbeam reads one bulk
    data section and used to merge such a section into it.
    """
    if " ".join(_strip_comment(line).upper().split()) != "BEGIN BULK":
        raise ValueError(
            f"{line.strip()!r}: sbeam reads one bulk data section, opened by a plain "
            "BEGIN BULK; partitioned Bulk Data Sections (SUPER, TRMC, AUXMODEL, MASSID, "
            "MODULE, ...; QRG p.286–287) are not supported")


def _read_input(filepath: StrPath) -> tuple[list[str], list[str], list[tuple[int, str]]]:
    """Return a file's lines with every INCLUDE expanded, as NASTRAN reads it.

    Returns ``(lines, origins, includes)``: the expanded lines, the file each came from,
    and ``(position, filename)`` for each INCLUDE in the main file, where ``position`` is
    the index its file's text starts at.  An INCLUDE may appear anywhere and may nest up
    to 10 deep (QRG p.465, p.1984).  A relative filename is resolved against the directory
    of the file holding the INCLUDE — sbeam's rule: the QRG leaves filenames to the
    installation (p.1984).
    """
    lines: list[str] = []
    origins: list[str] = []
    includes: list[tuple[int, str]] = []
    _expand(os.fspath(filepath), (), lines, origins, includes)
    return lines, origins, includes


def _expand(path: str, chain: tuple[str, ...], lines: list[str], origins: list[str],
            includes: Optional[list[tuple[int, str]]]) -> None:
    with open(path, "r") as fh:
        raw = [line.rstrip("\n") for line in fh]
    chain = (*chain, os.path.abspath(path))
    i = 0
    while i < len(raw):
        if not _INCLUDE.match(_strip_comment(raw[i])):
            lines.append(raw[i])
            origins.append(path)
            i += 1
            continue
        name, i = _include_filename(raw, i, path)
        target = name if os.path.isabs(name) else os.path.join(os.path.dirname(chain[-1]), name)
        if not os.path.exists(target):
            raise FileNotFoundError(f"INCLUDE file not found: {name!r} (INCLUDEd by {path})")
        if os.path.abspath(target) in chain:
            raise ValueError(f"INCLUDE {name!r} in {path} includes itself (via "
                             + " -> ".join(os.path.basename(c) for c in chain) + ")")
        if len(chain) > _MAX_INCLUDE_DEPTH:
            raise ValueError(f"INCLUDE {name!r} in {path}: INCLUDEs nest more than "
                             f"{_MAX_INCLUDE_DEPTH} deep (QRG p.1984)")
        if includes is not None:
            includes.append((len(lines), name))
        _expand(target, chain, lines, origins, None)


def _include_filename(raw: list[str], i: int, path: str) -> tuple[str, int]:
    """Read the filename of the INCLUDE on line ``i``; return it and the next line index.

    A quoted name may run over several lines, which join with no separator (QRG p.1984
    remark 2: ``INCLUDE '/dir123`` / ``/dir456`` / ``/dir789/filename.dat'``).
    """
    rest = _strip_comment(raw[i])[len("INCLUDE"):].strip()
    i += 1
    if rest[:1] not in ("'", '"'):
        if len(rest.split()) != 1:
            raise ValueError(f"{path}: INCLUDE needs one filename, got {rest!r}")
        return rest, i
    quote, name = rest[0], rest[1:]
    while quote not in name:
        if i == len(raw):
            raise ValueError(f"{path}: INCLUDE {rest!r} has no closing quote")
        name += _strip_comment(raw[i])
        i += 1
    name, after = name.split(quote, 1)
    if after.strip():
        raise ValueError(f"{path}: text after the INCLUDE filename: {after.strip()!r}")
    return name, i


def _refuse_included_bulk_in_case_control(lines: list[str], origins: list[str],
                                         main: StrPath) -> None:
    """Refuse bulk cards that an INCLUDE above BEGIN BULK put into the case control.

    INCLUDE inserts its file where it stands (QRG p.465), so a bulk file INCLUDEd above
    BEGIN BULK is case control to NASTRAN.  sbeam once read it as bulk data, and its
    sample decks relied on that (#81).  The case-control parser would refuse the first
    card as an unknown command; this names the INCLUDE instead.
    """
    known = HANDLED_CARDS | set(_UNSUPPORTED_CARDS) | set(_HARMLESS_CARDS)
    for line, origin in zip(lines, origins):
        clean = _strip_comment(line)
        if origin == os.fspath(main) or not clean:
            continue
        keyword = split_line(clean)[0].rstrip("*").upper()
        if keyword in known and case_control_command(keyword) is None:
            raise ValueError(
                f"{origin} holds bulk data ({keyword}) but is INCLUDEd above BEGIN BULK, "
                "where its text is case control (INCLUDE inserts the file where it stands, "
                "QRG p.465); move the INCLUDE below BEGIN BULK")


def _bulk_section(lines: list[str], origins: Optional[list[str]] = None) -> list[str]:
    """Return the bulk data lines up to ENDDATA, without BEGIN BULK; refuse any card after.

    ENDDATA "designates the end of the Bulk Data Section" (QRG p.1808), so NASTRAN reads
    nothing after it.  sbeam read on, and applied a FORCE placed there (#81); a card
    after ENDDATA is now refused rather than read or dropped.  ENDDATA is optional.  A
    repeated plain BEGIN BULK is skipped; any other BEGIN is refused.
    """
    lines = list(lines)
    for i, line in enumerate(lines):
        clean = _strip_comment(line)
        if clean.upper().startswith("BEGIN"):
            _refuse_partitioned_bulk(line)
            lines[i] = ""
            continue
        if not clean or split_line(clean)[0].upper() != "ENDDATA":
            continue
        for j in range(i + 1, len(lines)):
            if _strip_comment(lines[j]):
                where = (f" (ENDDATA in {origins[i]}, this line in {origins[j]})"
                         if origins else "")
                raise ValueError(
                    f"Bulk data after ENDDATA: {lines[j].strip()!r}{where}.  NASTRAN reads "
                    "nothing after ENDDATA (QRG p.1808); remove ENDDATA from a file that "
                    "is INCLUDEd ahead of more bulk data")
        return lines[:i]
    return lines
