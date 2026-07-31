"""Shared number formatting for the viewer — 5 significant figures, no needless sci.

Engineering-table convention:

* ``fmt`` renders to ``sig`` significant figures (default 5) using ``%G`` rules:
  decimal notation while the exponent is ≥ −4, switching to scientific only below
  that (so ``0.012`` stays ``"0.012"`` but ``0.0000012`` becomes ``"1.2E-6"``).
  Trailing zeros are trimmed and the exponent is normalised to drop leading zeros
  (``E-06`` → ``E-6``, ``E+05`` → ``E+5``).
* ``fmt_mass`` keeps masses at the conventional 0.1-unit precision (``"%.1f"``).
* ``style_numeric`` wraps a DataFrame in a pandas Styler that applies ``fmt`` to
  every float column (and ``fmt_mass`` to named mass columns) for ``st.dataframe``.

Integer columns (GID/EID/Mode/…) are left untouched so they keep their dtype and
sort order; only float columns are reformatted.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, cast

import pandas as pd


def fmt(x: Any, sig: int = 5) -> str:
    """Format *x* to *sig* significant figures, decimal where reasonable.

    Non-numeric values pass through as ``str``; NaN renders as ``""`` and
    ±inf as ``"∞"`` / ``"-∞"``.
    """
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return "" if x is None else str(x)
    if math.isnan(xf):
        return ""
    if math.isinf(xf):
        return "∞" if xf > 0 else "-∞"
    s = format(xf, f".{sig}G")
    if "E" in s:
        mant, _, exp = s.partition("E")
        sign = "-" if exp.startswith("-") else "+"
        digits = exp.lstrip("+-").lstrip("0") or "0"
        s = f"{mant}E{sign}{digits}"
    return s


def fmt_mass(x: Any) -> str:
    """Format a mass at 0.1-unit precision (e.g. kg reported to ±0.1)."""
    try:
        return f"{float(x):.1f}"
    except (TypeError, ValueError):
        return "" if x is None else str(x)


def style_numeric(df: pd.DataFrame, sig: int = 5, mass_cols: Iterable[str] = ()):
    """Return a pandas Styler formatting float columns to *sig* sig figs.

    Columns named in *mass_cols* use ``fmt_mass`` instead; integer and text
    columns are left as-is.  Pass the result straight to ``st.dataframe``.
    """
    mass = set(mass_cols)
    fmt_map: dict[str, Callable[[Any], str]] = {}
    for col in df.columns:
        if col in mass:
            fmt_map[col] = fmt_mass
        elif pd.api.types.is_float_dtype(df[col]):
            fmt_map[col] = (lambda v, s=sig: fmt(v, s))
    # cast: pandas types the formatter map as str-only, but a per-column
    # callable is supported and is what the numeric formatting needs.
    return df.style.format(cast(Any, fmt_map))
