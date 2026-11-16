from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass
class SubcaseControl:
    subcase_id: int
    title: str = ""
    load_sid: Optional[int] = None    # LOAD set ID
    spc_sid: Optional[int] = None     # SPC set ID
    method_sid: Optional[int] = None  # METHOD (EIGRL) SID for SOL 103
    trim_sid: Optional[int] = None    # TRIM set ID for SOL 144
    trimobj_sid: Optional[int] = None # TRIMOBJ set ID (over-determined trim objective)
    diverg_sid: Optional[int] = None  # DIVERG set ID for SOL 144
    mloads_sid: Optional[int] = None  # MLOADS set ID (Phase G0 transient maneuver loads)
    gustlf_sid: Optional[int] = None  # GUSTLF set ID (FAR/CS 23.341 gust load case)
    massset_sid: Optional[int] = None # MASSSET set ID (Step 60 payload / mass case)
    displacement: bool = False        # Request DISPLACEMENT output
    spcforce: bool = False            # Request SPCFORCE output
    oload: bool = False               # Request OLOAD output
    force: bool = False               # Request FORCE output
    stress: bool = False              # Request STRESS output
    aerof: bool = False               # Request AEROF output (SOL 144 aero box forces)
    apres: bool = False               # Request APRES output (SOL 144 aero box pressures)


@dataclass
class CaseControl:
    sol: int
    title: str = ""
    subcases: list["SubcaseControl"] = field(default_factory=list)
    include: Optional[str] = None  # First INCLUDE path (back-compat; see `includes`)
    # All INCLUDE paths, in file order.  A deck may name several — the bulk is the
    # concatenation of every included file followed by any inline bulk data (the
    # NASTRAN behaviour).  This is what lets a driver deck compose a shared bulk
    # file with a small overlay, e.g. the Cessna 210 flagship + its body panels.
    # `include` stays the first entry so existing single-INCLUDE callers are
    # unaffected.
    includes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _cc_strip_comment(line: str) -> str:
    idx = line.find("$")
    return (line[:idx] if idx >= 0 else line).strip()


def _cc_value(line: str):
    """Split 'KEYWORD = VALUE' or 'KEYWORD VALUE' into (keyword_upper, value_str)."""
    if "=" in line:
        keyword, _, rest = line.partition("=")
        return keyword.strip().upper(), rest.strip()
    parts = line.split(None, 1)
    keyword = parts[0].upper()
    value = parts[1].strip() if len(parts) > 1 else ""
    return keyword, value


def _cc_include_path(line: str) -> str:
    """Extract the file path from an INCLUDE line, stripping surrounding quotes."""
    _, value = _cc_value(line)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

_SUPPORTED_SOLS = frozenset({101, 103, 144})

# Set selectors (keyword -> SubcaseControl attribute); the value is a set ID.
_SELECTORS = {
    "LOAD": "load_sid",
    "SPC": "spc_sid",
    "METHOD": "method_sid",
    "TRIM": "trim_sid",
    "TRIMOBJ": "trimobj_sid",
    "DIVERG": "diverg_sid",
    "MLOADS": "mloads_sid",
    "GUSTLF": "gustlf_sid",
    "MASSSET": "massset_sid",
}

# Output requests (keyword -> SubcaseControl attribute); `= NONE` cancels one.
_OUTPUT_REQUESTS = {
    "DISPLACEMENT": "displacement",
    "SPCFORCE": "spcforce",
    "OLOAD": "oload",
    "FORCE": "force",
    "STRESS": "stress",
    "AEROF": "aerof",
    "APRES": "apres",
}


def _cc_subcase_id(value: str, previous: Optional[int]) -> int:
    """Read a SUBCASE ID: a positive integer greater than every earlier one.

    MSC QRG 2024.1 PDF p.651, SUBCASE remark 1.  Results are keyed by this ID,
    so a repeated ID would overwrite the earlier subcase's results.
    """
    try:
        subcase_id = int(value)
    except ValueError:
        raise ValueError(f"SUBCASE {value!r}: the ID must be an integer") from None
    if subcase_id <= 0:
        raise ValueError(f"SUBCASE {subcase_id}: the ID must be greater than 0")
    if previous is not None and subcase_id <= previous:
        raise ValueError(
            f"SUBCASE {subcase_id} follows SUBCASE {previous}: each subcase ID "
            f"must be greater than all previous subcase IDs")
    return subcase_id


def parse_case_control(lines: list[str]) -> CaseControl:
    """Parse case control lines (above BEGIN BULK) into a CaseControl object.

    Selectors and output requests above the first SUBCASE are defaults: every
    subcase starts from them and its own lines override (MSC AAUG 2023.1 PDF
    p.752).  A deck with no SUBCASE runs those commands as one subcase, which
    sbeam numbers 1.  A section with neither returns no subcases: that is a
    deck read for its bulk data, and `sbeam.main` refuses to run it.

    Raises ValueError if no SOL card is found, the SOL value is not one of the
    supported solutions (101, 103, 144), or a SUBCASE ID is not greater than
    every earlier one.
    """
    sol = None
    title = ""
    subcases = []
    includes: list[str] = []
    defaults = SubcaseControl(subcase_id=1)
    has_defaults = False
    current_sc = None

    for raw in lines:
        stripped = _cc_strip_comment(raw)
        if not stripped:
            continue

        keyword, value = _cc_value(stripped)

        if keyword == "SOL":
            sol = int(value)
            if sol not in _SUPPORTED_SOLS:
                raise ValueError(f"SOL {sol} not supported (only SOL 101, 103, and 144 supported)")

        elif keyword == "TITLE":
            if current_sc is not None:
                current_sc.title = value
            else:
                title = value

        elif keyword == "SUBCASE":
            previous = current_sc.subcase_id if current_sc is not None else None
            if current_sc is not None:
                subcases.append(current_sc)
            current_sc = replace(defaults,
                                 subcase_id=_cc_subcase_id(value, previous))

        elif keyword == "INCLUDE":
            includes.append(_cc_include_path(stripped))

        elif keyword == "BEGIN":
            break

        elif keyword in _SELECTORS or keyword in _OUTPUT_REQUESTS:
            target = current_sc if current_sc is not None else defaults
            if keyword in _SELECTORS:
                setattr(target, _SELECTORS[keyword], int(value))
            else:
                setattr(target, _OUTPUT_REQUESTS[keyword],
                        value.upper() != "NONE")
            if current_sc is None:
                has_defaults = True

    if current_sc is not None:
        subcases.append(current_sc)
    elif has_defaults:
        subcases.append(defaults)

    if sol is None:
        raise ValueError("Case control section contains no SOL statement")

    return CaseControl(sol=sol, title=title, subcases=subcases,
                       include=includes[0] if includes else None,
                       includes=includes)
