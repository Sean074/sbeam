"""Bulk-data field and line utilities shared by every card family (#48).

Line splitting (free/fixed field), field conversion, continuation detection and the
card iterator that groups each card with its continuation lines.
"""
from typing import Callable, Iterator, Optional

from sbeam.model.bulk_data import BulkData
from sbeam.parser.bdf_field import parse_real

#: Card handler signatures, by how much of the card the handler reads.  A family module
#: registers each keyword in exactly one of its three tables (see ``bdf_reader``).
FieldHandler = Callable[[list[str], BulkData], None]                         # first line only
ContHandler = Callable[[list[str], Optional[list[str]], BulkData], None]     # + first continuation
MultiHandler = Callable[[list[str], list[list[str]], BulkData], None]        # + every continuation


def _split_free_field(line: str) -> list[str]:
    return [f.strip() for f in line.split(",")]


def _split_fixed_field(line: str) -> list[str]:
    line = line.ljust(72)
    return [line[i : i + 8].strip() for i in range(0, 72, 8)]


def split_line(line: str) -> list[str]:
    return _split_free_field(line) if "," in line else _split_fixed_field(line)


def to_float(s: str) -> float:
    """Convert a BDF field string to float.

    Handles NASTRAN short scientific notation (e.g. '1.44+9' → 1.44e9)
    in addition to standard Python float literals.  Defined in ``bdf_field``
    alongside the write-side formatter so read and write cannot drift.
    """
    return parse_real(s)


def to_int(s: str) -> int:
    return int(s.strip())


def to_int_opt(s: str, default: int = 0) -> int:
    s = s.strip()
    return int(s) if s else default


def to_float_or_none(s: str) -> Optional[float]:
    s = s.strip()
    return float(s) if s else None


def to_int_or_none(s: str) -> Optional[int]:
    s = s.strip()
    return int(s) if s else None


def is_continuation(fields: list[str]) -> bool:
    if not fields:
        return False
    if fields[0].startswith("+"):
        return True
    # Unnamed continuation: blank first field with subsequent non-blank content
    if not fields[0].strip() and any(f.strip() for f in fields[1:]):
        return True
    return False


def validate_dof(c: str, context: str) -> None:
    if not c or any(ch not in "123456" for ch in c):
        raise ValueError(f"{context}: invalid DOF string '{c}'")

def expand_int_list_with_thru(tokens: list[str]) -> list[int]:
    """Expand a token list that may contain THRU keywords into a flat integer list."""
    result = []
    k = 0
    while k < len(tokens):
        t = tokens[k].strip()
        if not t:
            k += 1
            continue
        if t.upper() == "THRU":
            start = result[-1]
            end = to_int(tokens[k + 1])
            result.extend(range(start + 1, end + 1))
            k += 2
        else:
            result.append(to_int(t))
            k += 1
    return result


def iter_cards(lines: list[str]) -> Iterator[tuple[str, list[str], list[list[str]]]]:
    """Yield ``(KEYWORD, fields, continuations)`` for every card in bulk-data lines.

    A ``$`` anywhere on a line starts a comment.  ``continuations`` holds the split
    continuation lines that directly follow the card, blank lines between them skipped.
    Continuation lines are never yielded on their own, so an orphan continuation is
    dropped silently.
    """
    processed = []
    for raw in lines:
        idx = raw.find("$")
        processed.append(raw[:idx].rstrip() if idx >= 0 else raw.rstrip())

    for i, line in enumerate(processed):
        if not line.strip():
            continue
        fields = split_line(line)
        if not fields or not fields[0] or is_continuation(fields):
            continue
        conts: list[list[str]] = []
        k = i + 1
        while k < len(processed):
            if not processed[k].strip():
                k += 1
                continue
            nf = split_line(processed[k])
            if not is_continuation(nf):
                break
            conts.append(nf)
            k += 1
        yield fields[0].upper(), fields, conts
