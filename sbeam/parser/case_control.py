import re
import warnings
from dataclasses import dataclass, field, replace
from typing import Optional

from sbeam.parser.bulk_structural import check_param


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
    massset_sid: Optional[int] = None # MASSCASE set ID (Step 60 payload / mass case)
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
    # The files the main deck INCLUDEs below BEGIN BULK, in file order.  Set by
    # `parse_bdf`, which expands every INCLUDE (#81); a driver deck composes a shared
    # bulk file with a small overlay this way, e.g. the Cessna 210 flagship + its body
    # panels.  `include` stays the first entry so single-INCLUDE callers are unaffected.
    includes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Command tables
# ---------------------------------------------------------------------------
# Every line above BEGIN BULK must name a command in one of these tables; any other
# line is refused (#80).  Names are MSC's full names, so the four-character
# abbreviation rule (`_cc_resolve`) works from the right spelling.  Field
# reference: docs/10_standard/02_card_reference.md "Case Control Keywords".

_SUPPORTED_SOLS = frozenset({101, 103, 144})

# MSC QRG 2024.1 PDF p.186-187, Table 2 (solution sequence names).
_SOL_NAMES = {"SESTATIC": 101, "SEMODES": 103, "AESTAT": 144}

# Set selectors (command -> SubcaseControl attribute); the value is a set ID.
_SELECTORS = {
    "LOAD": "load_sid",
    "SPC": "spc_sid",
    "METHOD": "method_sid",
    "TRIM": "trim_sid",
    "TRIMOBJ": "trimobj_sid",
    "DIVERG": "diverg_sid",
    "MLOADS": "mloads_sid",
    "GUSTLF": "gustlf_sid",
    "MASSCASE": "massset_sid",
}

# Output requests (command -> SubcaseControl attribute); `= NONE` cancels one.
# ELFORCE and ELSTRESS are MSC's equivalents of FORCE and STRESS (QRG PDF p.413,
# p.646); SPCFORCES and APRESSURE are MSC's full names (p.634, p.263).
_OUTPUT_REQUESTS = {
    "DISPLACEMENT": "displacement",
    "SPCFORCES": "spcforce",
    "OLOAD": "oload",
    "FORCE": "force",
    "ELFORCE": "force",
    "STRESS": "stress",
    "ELSTRESS": "stress",
    "AEROF": "aerof",
    "APRESSURE": "apres",
}

# Read by the parser's own branches.
_STRUCTURE = frozenset({"SOL", "TITLE", "SUBCASE", "INCLUDE", "BEGIN", "PARAM"})

# Accepted and ignored without a message: none of these changes a result.
_IGNORED = {
    "ID": "executive job identification",
    "TIME": "executive time limit",
    "DIAG": "executive diagnostic output",
    "CEND": "end of the executive control section",
    "NASTRAN": "system-cell settings",
    "ASSIGN": "file assignment; sbeam names its own output files",
    "ECHO": "bulk-data listing control",
    "ECHOON": "case-control listing control",
    "ECHOOFF": "case-control listing control",
    "SUBTITLE": "page heading",
    "LABEL": "page heading",
    "LINE": "lines per printed page",
    "MAXLINES": "output line limit",
    # MSC itself ignores MONITOR in SOL 144 (QRG PDF p.524, remark 2); sbeam prints
    # monitor results in every run that defines monitor points.
    "MONITOR": "monitor results are always printed",
}

# Output requests for results sbeam does not write: accepted with a warning, since
# the missing block is visible and no printed number changes.
_UNWRITTEN_OUTPUT = {
    "GPFORCE": "grid point force balance",
    "TRIMF": "trim load output",
}

# Known MSC commands that would change the run: refused with the reason.
_DELIMITER = ("starts a kind of subcase sbeam does not run; only SUBCASE is "
              "supported (MSC QRG PDF p.210)")
_REFUSED = {
    # QRG PDF p.252 remark 1: case control decides the symmetry when present.
    "AESYMXZ": "is not supported: set the symmetry in the AEROS SYMXZ field",
    "AESYMXY": "is not supported: set the symmetry in the AEROS SYMXY field",
    "SUBCOM": _DELIMITER,
    "SYMCOM": _DELIMITER,
    "SYM": _DELIMITER,
    "REPCASE": _DELIMITER,
    "SUBSEQ": "combines subcases; sbeam does not combine subcases",
    "SYMSEQ": "combines subcases; sbeam does not combine subcases",
    "COMPILE": "is DMAP; sbeam has no DMAP",
    "ALTER": "is DMAP; sbeam has no DMAP",
    "MALTER": "is DMAP; sbeam has no DMAP",
    "ENDALTER": "is DMAP; sbeam has no DMAP",
    # MSC's GUST selects a SOL 146 gust field (QRG PDF p.452).  Listed so that it
    # is not taken as an abbreviation of sbeam's GUSTLF.
    "GUST": "is the SOL 146 gust selector, which sbeam does not support "
            "(sbeam's static gust case is GUSTLF)",
    # MSC's MASSSET selects a MASSSET bulk entry, a mass combination (QRG PDF p.482).
    # sbeam's mass-case selector had this name until #78.
    "MASSSET": "selects an MSC mass combination, which sbeam does not support; sbeam's "
               "mass case is selected with MASSCASE = n (named MASSSET before #78: "
               "rename the command)",
}

_COMMANDS = (frozenset(_SELECTORS) | frozenset(_OUTPUT_REQUESTS) | _STRUCTURE
             | frozenset(_IGNORED) | frozenset(_UNWRITTEN_OUTPUT)
             | frozenset(_REFUSED))

# Heading text may end in a comma, so these lines are never continued.
_TEXT_COMMANDS = frozenset({"TITLE", "SUBTITLE", "LABEL"})


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_CC_LINE = re.compile(r"([A-Za-z][A-Za-z0-9]*)\s*(\(.*?\))?\s*[=,]?\s*(.*)$")


def _cc_strip_comment(line: str) -> str:
    idx = line.find("$")
    return (line[:idx] if idx >= 0 else line).strip()


def _cc_split(line: str) -> tuple[str, str, str]:
    """Split a command line into (KEYWORD, describers, value).

    The keyword ends at the first blank, '=', ',' or '('.  `describers` is the
    parenthesised text after the keyword, with its parentheses, or ''.
    A line that does not start with a letter returns an empty keyword.
    """
    match = _CC_LINE.match(line)
    if match is None:
        return "", "", line
    return match.group(1).upper(), match.group(2) or "", match.group(3).strip()


def _cc_resolve(keyword: str) -> Optional[str]:
    """Return the command a keyword names, or None if it names none.

    A command "may be abbreviated down to the first four characters if the
    abbreviation is unique" (MSC QRG 2024.1 PDF p.209).  Uniqueness is checked
    against the commands sbeam knows, not MSC's full list.
    """
    if keyword in _COMMANDS:
        return keyword
    if len(keyword) < 4:
        return None
    matches = sorted(name for name in _COMMANDS if name.startswith(keyword))
    if len(matches) > 1:
        raise ValueError(
            f"Case control command {keyword!r} is ambiguous: it abbreviates "
            f"{', '.join(matches)}")
    return matches[0] if matches else None


def case_control_command(keyword: str) -> Optional[str]:
    """The case-control command ``keyword`` names (or abbreviates), else None."""
    try:
        return _cc_resolve(keyword.upper())
    except ValueError:  # an ambiguous abbreviation still names a command
        return keyword


def _cc_sol(value: str) -> int:
    """Read the SOL number, or MSC's name for it (QRG PDF p.186-187)."""
    token = value.replace(",", " ").split()[0].upper() if value.strip() else ""
    if token in _SOL_NAMES:
        return _SOL_NAMES[token]
    try:
        sol = int(token)
    except ValueError:
        sol = None
    if sol not in _SUPPORTED_SOLS:
        raise ValueError(
            f"SOL {token} not supported (only SOL 101, 103, and 144 supported)")
    return sol


def _cc_set_id(command: str, value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(
            f"Case control {command} = {value!r}: the set ID must be an integer"
        ) from None


def _cc_param(value: str) -> None:
    """Apply the bulk PARAM rules to a case-control PARAM (QRG PDF p.570)."""
    fields = ["PARAM"] + [f.strip() for f in value.split(",")]
    fields += [""] * (4 - len(fields))
    check_param(fields)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

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
    """Parse the lines above BEGIN BULK into a CaseControl object.

    Selectors and output requests above the first SUBCASE are defaults: every
    subcase starts from them and its own lines override (MSC AAUG 2023.1 PDF
    p.752).  A deck with no SUBCASE runs those commands as one subcase, which
    sbeam numbers 1.  A section with neither returns no subcases: that is a
    deck read for its bulk data, and `sbeam.main` refuses to run it.

    Every line must name a command sbeam reads, ignores for a stated reason or
    refuses by name; anything else is refused as unknown (#80).

    Raises ValueError if no SOL statement is found, the SOL is not one of the
    supported solutions (101, 103, 144), a line is not a known command, a
    command is one sbeam refuses, a SUBCASE ID is not greater than every
    earlier one, or a line is an INCLUDE (``parse_bdf`` expands those first).
    """
    commands = [c for c in (_cc_strip_comment(raw) for raw in lines) if c]

    # Checked first, so a bulk-data file read as a deck is reported as a file
    # with no SOL rather than by its first card.
    if not any(_cc_split(c)[0] == "SOL" for c in commands):
        raise ValueError("Case control section contains no SOL statement")

    sol = None
    title = ""
    subcases = []
    defaults = SubcaseControl(subcase_id=1)
    has_defaults = False
    current_sc = None

    i = 0
    while i < len(commands):
        line = commands[i]
        i += 1
        keyword, describers, value = _cc_split(line)
        command = _cc_resolve(keyword) if keyword else None
        if command is None:
            raise ValueError(
                f"Unknown case control command: {line!r} (sbeam refuses a "
                f"command it does not act on)")

        # A line ending in a comma continues on the next one (QRG PDF p.209).
        if command not in _TEXT_COMMANDS:
            while value.endswith(",") and i < len(commands):
                value = f"{value} {commands[i]}"
                i += 1

        if command == "SOL":
            sol = _cc_sol(value)

        elif command == "TITLE":
            if current_sc is not None:
                current_sc.title = value
            else:
                title = value

        elif command == "SUBCASE":
            previous = current_sc.subcase_id if current_sc is not None else None
            if current_sc is not None:
                subcases.append(current_sc)
            current_sc = replace(defaults,
                                 subcase_id=_cc_subcase_id(value, previous))

        elif command == "INCLUDE":
            raise ValueError(
                f"Case control {line!r}: INCLUDE inserts a file, which parse_bdf does "
                "before the case control is read (#81); parse_case_control reads text "
                "with every INCLUDE already expanded")

        elif command == "BEGIN":
            break

        elif command == "PARAM":
            _cc_param(value)

        elif command in _SELECTORS or command in _OUTPUT_REQUESTS:
            if describers:
                raise ValueError(
                    f"Case control {command}{describers}: describers in "
                    f"parentheses are not supported; write {command} = {value}")
            target = current_sc if current_sc is not None else defaults
            if command in _SELECTORS:
                setattr(target, _SELECTORS[command], _cc_set_id(command, value))
            else:
                setattr(target, _OUTPUT_REQUESTS[command],
                        value.upper() != "NONE")
            if current_sc is None:
                has_defaults = True

        elif command in _UNWRITTEN_OUTPUT:
            warnings.warn(
                f"Case control {command} ignored: sbeam does not write "
                f"{_UNWRITTEN_OUTPUT[command]}", UserWarning, stacklevel=2)

        elif command in _REFUSED:
            raise ValueError(f"Case control {command} {_REFUSED[command]}")

        # else: a command in _IGNORED

    if current_sc is not None:
        subcases.append(current_sc)
    elif has_defaults:
        subcases.append(defaults)

    if sol is None:
        raise ValueError("Case control section contains no SOL statement")

    return CaseControl(sol=sol, title=title, subcases=subcases)
