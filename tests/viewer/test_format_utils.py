"""Shared viewer number formatting — 5 sig figs, no needless scientific notation."""
from __future__ import annotations

import math

import pandas as pd

from sbeam.viewer.format_utils import fmt, fmt_mass, style_numeric


def test_fmt_decimal_vs_scientific():
    # Decimal while the exponent is ≥ −4; scientific (uppercase, normalised) below.
    assert fmt(0.012) == "0.012"
    assert fmt(0.0000012) == "1.2E-6"
    assert fmt(0.00012345) == "0.00012345"
    assert fmt(1e-8) == "1E-8"


def test_fmt_five_sig_figs():
    assert fmt(1.23456789) == "1.2346"
    assert fmt(12345.678) == "12346"        # 5 sig figs, still decimal
    assert fmt(123456.78) == "1.2346E+5"    # 6th digit → scientific


def test_fmt_specials():
    assert fmt(0.0) == "0"
    assert fmt(-2.0) == "-2"
    assert fmt(float("nan")) == ""
    assert fmt(math.inf) == "∞"
    assert fmt(-math.inf) == "-∞"
    assert fmt(None) == ""
    assert fmt("text") == "text"


def test_fmt_mass_tenth():
    assert fmt_mass(1234.567) == "1234.6"
    assert fmt_mass(0.04) == "0.0"
    assert fmt_mass(None) == ""


def test_style_numeric_floats_and_mass():
    df = pd.DataFrame({
        "GID": [1, 2],                       # int → untouched
        "X": [0.0000012, 12345.678],         # float → fmt
        "Mass": [1234.567, 0.5],             # mass col → fmt_mass
        "PS": ["123", ""],                   # text → untouched
    })
    rendered = style_numeric(df, mass_cols=["Mass"]).to_html()
    assert "1.2E-6" in rendered
    assert "12346" in rendered
    assert "1234.6" in rendered
    # Integer ids keep their plain rendering (no sci-format applied).
    assert ">1<" in rendered
