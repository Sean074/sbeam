"""DEF-M6 — NASTRAN 8-character field formatting (sbeam/parser/bdf_field.py).

Precision is bounded by the field width, and the bound differs between the two
spellings ``fmt_real8`` chooses from (measured, not assumed):

* **Fixed point** (``4715.932``) — used wherever a decimal fits, roughly
  1e-3 to 1e7.  6-7 significant figures, worst observed rel 2e-6.  This is the
  range every physical load export lives in.
* **Implicit exponent** (``1.2346-6``) — used outside it.  The mantissa shares
  the eight characters with the exponent and the sign, leaving 3-5 significant
  figures: worst observed rel 2.6e-5 positive, 3.5e-4 negative, degrading to
  3.7e-3 once the exponent needs two digits.

Absolute error stays negligible throughout, because the coarse cases are the
ones whose magnitude is tiny or huge.
"""

import math

import pytest

from sbeam.parser.bdf_field import FIELD_WIDTH, fmt_real8, parse_real

# Loads a real export can contain — all in the fixed-point regime.
_ENGINEERING = [
    1.0, -1.0, 0.5, -0.5, 2.0 / 3.0, -2.0 / 3.0,
    4715.932, -4715.932, 471593.25, -471593.25,
    2999.775064, -2999.775064, 16000.0, -16000.0,
    999.9999, -999.9999, 1000.005, -1000.005,
    0.001234, -0.001234, 32.174, -32.174,
]

# Magnitudes that force the implicit-exponent spelling.
_EXTREME = [
    1e-5, -1e-5, 1.23456e-5, -1.23456e-5,
    1e8, -1e8, 123456789.0, -123456789.0,
    4.715932e9, -4.715932e9, 4.715932e-9, -4.715932e-9,
    3e-16, -3e-16, 1e30, -1e30,
]

_ALL = _ENGINEERING + _EXTREME


@pytest.mark.parametrize("val", _ALL)
def test_field_never_exceeds_eight_characters(val):
    """The whole point of DEF-M6: a strict free-field reader truncates at 8."""
    assert len(fmt_real8(val)) <= FIELD_WIDTH


@pytest.mark.parametrize("val", _ALL)
def test_field_is_a_legal_nastran_real(val):
    """Reals must carry a decimal point, else the field reads as an integer."""
    assert "." in fmt_real8(val)


@pytest.mark.parametrize("val", _ENGINEERING)
def test_engineering_range_keeps_six_significant_figures(val):
    """Physical loads round-trip to the fixed-point floor."""
    assert parse_real(fmt_real8(val)) == pytest.approx(val, rel=1e-5)


@pytest.mark.parametrize("val", _EXTREME)
def test_extreme_range_round_trips_within_the_field_budget(val):
    """Outside fixed point the mantissa shares the field with the exponent."""
    assert parse_real(fmt_real8(val)) == pytest.approx(val, rel=1e-3)


def test_zero():
    assert fmt_real8(0.0) == "0.0"
    assert parse_real(fmt_real8(0.0)) == 0.0


@pytest.mark.parametrize("val", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_raises(val):
    """A NaN/inf in an exported load card is a silently corrupt deliverable."""
    with pytest.raises(ValueError, match="non-finite"):
        fmt_real8(val)


def test_never_writes_a_field_that_reads_back_non_finite():
    """Rounding up at the top of the double range must not produce 'inf'."""
    with pytest.raises(ValueError):
        fmt_real8(1.7976931348623157e308)


def test_prefers_the_more_accurate_spelling():
    """Fixed point wins mid-range; implicit exponent wins for small magnitudes."""
    assert fmt_real8(4715.932) == "4715.932"            # exact, 7 sig figs
    # As fixed point 1.23456e-5 would collapse to 0.000012 — 2 sig figs.
    assert fmt_real8(1.23456e-5) == "1.2346-5"          # 5 sig figs
    # The sign costs a character, so negatives carry one digit less.
    assert fmt_real8(-2999.775064) == "-2999.78"


@pytest.mark.parametrize("text,expected", [
    ("1.44+9", 1.44e9),
    ("-2.31-4", -2.31e-4),
    ("1.5+03", 1.5e3),
    ("4.715932E+03", 4715.932),
    ("", 0.0),
    ("  2.5  ", 2.5),
])
def test_parse_real_accepts_nastran_notations(text, expected):
    assert parse_real(text) == pytest.approx(expected)


def test_reader_uses_the_same_parser():
    """bdf_reader._to_float must stay one source of truth with the formatter."""
    from sbeam.parser.bdf_reader import _to_float
    for val in _ALL:
        s = fmt_real8(val)
        assert _to_float(s) == parse_real(s)


def test_width_holds_over_the_full_representable_range():
    """No magnitude escapes the width budget or reads back non-finite."""
    for exp in range(-30, 31):
        for mant in (1.0, 1.0001, 1.2345678, 3.3333333, 5.5, 9.876543, 9.999999):
            for sign in (1.0, -1.0):
                val = sign * mant * (10.0 ** exp)
                s = fmt_real8(val)
                assert len(s) <= FIELD_WIDTH, f"{val!r} -> {s!r}"
                assert math.isfinite(parse_real(s))
                # 3.7e-3 is the measured worst case (negative, 2-digit exponent).
                assert parse_real(s) == pytest.approx(val, rel=4e-3)
