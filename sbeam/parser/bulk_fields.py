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
    if fields[0].startswith(("+", "*")):
        return True
    # Unnamed continuation: blank first field with subsequent non-blank content
    if not fields[0].strip() and any(f.strip() for f in fields[1:]):
        return True
    return False


def validate_dof(c: str, context: str) -> None:
    """Component numbers: "any unique combination of the Integers 1 through 6 ... with no
    embedded blanks" (MSC Nastran 2024.1 QRG PDF p.2870, SUPORT; the same wording on
    GRID PS, SPC and the rigid elements)."""
    if not c or any(ch not in "123456" for ch in c) or len(set(c)) != len(c):
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


def list_fields(first: list[str], conts: list[list[str]], card: str, rule: str) -> list[str]:
    """The values of a list card (``first`` then each continuation's data fields).

    Trailing blanks are dropped; a blank followed by more values is refused with the
    card's own ``rule`` (its QRG remark), never skipped (#73).
    """
    raw = list(first) + [f for cont in conts for f in cont[1:]]
    while raw and not raw[-1].strip():
        raw.pop()
    for k, f in enumerate(raw):
        if not f.strip():
            after = [g.strip() for g in raw[k + 1:]]
            raise ValueError(f"{card}: {rule}; remove the blank field before {after}")
    return [f.strip() for f in raw]


#: Data fields per physical line: fields 2–9 of a small-field line, or fields 2–5 (6–9 on
#: the next line) of a 16-column large-field line.  Field 10 never holds data (QRG p.1048).
_SMALL, _LARGE = 8, 4


def _is_marker(token: str) -> bool:
    """A field-10 token is a continuation marker if it starts with + or * and is not a number."""
    if not token.startswith(("+", "*")):
        return False
    try:
        parse_real(token)
    except ValueError:
        return True
    return False


def _physical_line(line: str) -> tuple[str, list[str], int]:
    """Split one physical line into ``(field 1, data fields, capacity)``.

    Capacity is 8 for small field and 4 for large field (field 1 ends ``*`` on a parent,
    starts ``*`` on a continuation).  A free-field line may carry more data than one line
    holds: the data runs on in capacity-sized rows, and a token in a row's field-10 slot
    is dropped when it is a continuation marker (QRG p.1049–1051: ``SPC1,100,12456,1,...,10``
    continues automatically; ``MATT9,...,8 ,+P101`` ends with a marker).  The data is
    padded to whole rows, so the next physical line starts a new row.
    """
    if "," in line:
        tokens = _split_free_field(line)
        name, rest = tokens[0], tokens[1:]
        capacity = _LARGE if name.endswith("*") or name.startswith("*") else _SMALL
        data: list[str] = []
        k = 0
        while k < len(rest):
            if data and len(data) % capacity == 0 and _is_marker(rest[k]):
                k += 1
                continue
            data.append(rest[k])
            k += 1
        while data and not data[-1]:
            data.pop()
    else:
        padded = line.ljust(72)
        name = padded[:8].strip()
        capacity = _LARGE if name.endswith("*") or name.startswith("*") else _SMALL
        width = 64 // capacity
        data = [padded[8 + i * width: 8 + (i + 1) * width].strip() for i in range(capacity)]
    rows = max(1, -(-len(data) // capacity))
    return name, data + [""] * (rows * capacity - len(data)), capacity


def iter_cards(lines: list[str]) -> Iterator[tuple[str, list[str], list[list[str]]]]:
    """Yield ``(KEYWORD, fields, continuations)`` for every card in bulk-data lines.

    Every card is normalised to NASTRAN's 10-field layout whatever its input format
    (free, small or large field; #64): ``fields`` is ``[KEYWORD, field 2 … field 9]`` and
    each continuation is ``["+", field 2 … field 9]`` — always 9 entries, field 10 dropped.
    A free-field line longer than 10 fields runs on into automatic continuations, and a
    large-field keyword loses its ``*``.  A ``$`` anywhere on a line starts a comment;
    blank lines between a card and its continuations are skipped.

    Raises ``ValueError`` for a continuation line with no card before it, and for a card
    that switches between large and small field in the middle of a row (the QRG's own
    examples do not settle where its fields land).
    """
    processed = []
    for raw in lines:
        idx = raw.find("$")
        processed.append(raw[:idx].rstrip() if idx >= 0 else raw.rstrip())

    card: Optional[tuple[str, list[str]]] = None
    for line in processed:
        if not line.strip():
            continue
        name, data, capacity = _physical_line(line)
        if not is_continuation([name, *data]):
            if card is not None:
                yield _card(*card)
            if not name:
                continue
            card = (name.rstrip("*").upper(), data)
            continue
        if card is None:
            raise ValueError(f"Continuation line with no card before it: '{line.strip()}'")
        if capacity == _SMALL and len(card[1]) % _SMALL:
            raise ValueError(f"{card[0]}: a small-field continuation follows half a "
                             "large-field row; write the card in one field format")
        card[1].extend(data)
    if card is not None:
        yield _card(*card)


def _card(keyword: str, data: list[str]) -> tuple[str, list[str], list[list[str]]]:
    data = data + [""] * (-len(data) % _SMALL)
    rows = [data[i:i + _SMALL] for i in range(0, len(data), _SMALL)]
    return keyword, [keyword, *rows[0]], [["+", *row] for row in rows[1:]]
