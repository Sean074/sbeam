from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SubcaseControl:
    subcase_id: int
    title: str = ""
    load_sid: Optional[int] = None    # LOAD set ID
    spc_sid: Optional[int] = None     # SPC set ID
    method_sid: Optional[int] = None  # METHOD (EIGRL) SID for SOL 103
    displacement: bool = False        # Request DISPLACEMENT output
    spcforce: bool = False            # Request SPCFORCE output
    oload: bool = False               # Request OLOAD output
    force: bool = False               # Request FORCE output
    stress: bool = False              # Request STRESS output


@dataclass
class CaseControl:
    sol: int
    title: str = ""
    subcases: list = field(default_factory=list)  # list[SubcaseControl]
    include: Optional[str] = None  # Path to bulk data INCLUDE file


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

_SUPPORTED_SOLS = frozenset({101, 103})


def parse_case_control(lines: list) -> CaseControl:
    """Parse case control lines (above BEGIN BULK) into a CaseControl object.

    Raises ValueError if no SOL card is found or SOL value is not 101 or 103.
    """
    sol = None
    title = ""
    subcases = []
    include = None
    current_sc = None

    for raw in lines:
        stripped = _cc_strip_comment(raw)
        if not stripped:
            continue

        keyword, value = _cc_value(stripped)

        if keyword == "SOL":
            sol = int(value)
            if sol not in _SUPPORTED_SOLS:
                raise ValueError(f"SOL {sol} not supported in phase 1 (only 101 and 103)")

        elif keyword == "TITLE":
            if current_sc is not None:
                current_sc.title = value
            else:
                title = value

        elif keyword == "SUBCASE":
            if current_sc is not None:
                subcases.append(current_sc)
            current_sc = SubcaseControl(subcase_id=int(value))

        elif keyword == "INCLUDE":
            include = _cc_include_path(stripped)

        elif keyword == "BEGIN":
            break

        elif current_sc is not None:
            if keyword == "LOAD":
                current_sc.load_sid = int(value)
            elif keyword == "SPC":
                current_sc.spc_sid = int(value)
            elif keyword == "METHOD":
                current_sc.method_sid = int(value)
            elif keyword == "DISPLACEMENT":
                current_sc.displacement = True
            elif keyword == "SPCFORCE":
                current_sc.spcforce = True
            elif keyword == "OLOAD":
                current_sc.oload = True
            elif keyword == "FORCE":
                current_sc.force = True
            elif keyword == "STRESS":
                current_sc.stress = True

    if current_sc is not None:
        subcases.append(current_sc)

    if sol is None:
        raise ValueError("Case control section contains no SOL statement")

    return CaseControl(sol=sol, title=title, subcases=subcases, include=include)
