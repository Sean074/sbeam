"""NASTRAN bulk-data real-field format — both directions.

A NASTRAN small/free-field data field is **8 characters wide**.  Free-field
(comma-separated) input is not exempt: a strict reader still truncates each
comma-delimited field to its first 8 characters, so a token such as
``4.715932E+03`` is read as ``4.715932`` — a silent factor-of-1000 corruption.
Exported load cards are the advertised handoff to an external stress code, so
every real this program writes into a card field must fit in 8 characters.

``fmt_real8`` spends that budget on significant digits.  It builds both a
fixed-point candidate (``4715.932``) and a NASTRAN implicit-exponent candidate
(``4.716+3``) and keeps whichever reproduces the value more closely — decimal
usually wins in the normal load range, implicit exponent wins for very large or
very small magnitudes.

``parse_real`` is the matching read side, and ``bdf_reader._to_float``
delegates to it, so the format sbeam writes and the format it accepts are one
definition and cannot drift apart.
"""

import math
import re

# NASTRAN small-field / free-field data field width.
FIELD_WIDTH = 8

# Implicit-exponent reals: a digit (not an exponent marker or sign) immediately
# followed by a signed integer at end of field — '1.44+9', '-2.31-4', '1.5+03'.
NASTRAN_SCI = re.compile(r'([^eEdD+\-])([+-]\d+)$')


def parse_real(s: str) -> float:
    """Convert a BDF real field to float — the read side of ``fmt_real8``.

    Handles NASTRAN implicit-exponent notation ('1.44+9' -> 1.44e9) in addition
    to standard Python float literals.  An empty field reads as 0.0.
    """
    s = s.strip()
    if not s:
        return 0.0
    m = NASTRAN_SCI.search(s)
    if m:
        s = s[:m.start(2)] + 'e' + s[m.start(2):]
    return float(s)


def _decimal(val: float) -> str:
    """Widest fixed-point spelling of ``val`` fitting FIELD_WIDTH, or ''.

    Returns '' when no fixed-point form both fits and keeps a significant digit
    (i.e. the magnitude is too large or too small for plain decimal).
    """
    for digits in range(FIELD_WIDTH, -1, -1):
        s = f"{val:.{digits}f}"
        if len(s) > FIELD_WIDTH:
            continue
        # A spelling that has rounded away every significant digit ('0.000',
        # '-0.00') is not a usable representation of a non-zero value.
        if float(s) == 0.0:
            return ""
        if "." not in s:            # NASTRAN reals require a decimal point
            s += "."
            if len(s) > FIELD_WIDTH:
                return ""
        return s
    return ""


def _implicit_exponent(val: float) -> str:
    """Widest NASTRAN implicit-exponent spelling ('4.716+3') fitting FIELD_WIDTH.

    Built from Python's ``%e``, which normalises the mantissa for us (so a value
    rounding up across a decade, 9.99e2 -> 1.0e3, is handled correctly).
    """
    for sig in range(FIELD_WIDTH, 0, -1):
        mant, _, exp = f"{val:.{sig}e}".partition("e")
        s = f"{mant}{int(exp):+d}"
        if len(s) <= FIELD_WIDTH:
            return s
    raise ValueError(f"cannot format {val!r} into {FIELD_WIDTH} characters")


def fmt_real8(val: float) -> str:
    """Format a real into a NASTRAN-legal field of at most 8 characters.

    Args:
        val: Finite real value.

    Returns:
        The 8-character-or-shorter field — fixed-point or implicit-exponent,
        whichever reproduces ``val`` more closely.

    Raises:
        ValueError: if ``val`` is NaN or infinite.  A non-finite number in an
            exported load card is a silently corrupt deliverable, so this is
            surfaced rather than written out.
    """
    val = float(val)
    if not math.isfinite(val):
        raise ValueError(f"cannot write non-finite value {val!r} to a BDF field")
    if val == 0.0:
        return "0.0"

    # Rounding up at the top of the double range can produce a field that reads
    # back as inf; such a card would be worse than no card at all.
    candidates = [c for c in (_decimal(val), _implicit_exponent(val))
                  if c and math.isfinite(parse_real(c))]
    if not candidates:
        raise ValueError(f"cannot format {val!r} into {FIELD_WIDTH} characters")
    best = min(candidates, key=lambda s: abs(parse_real(s) - val))
    assert len(best) <= FIELD_WIDTH, f"{best!r} exceeds {FIELD_WIDTH} characters"
    return best
