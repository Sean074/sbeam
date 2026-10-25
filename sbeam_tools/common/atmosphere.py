"""ISA standard atmosphere, in SI.

Kept free of any dependency on :mod:`sbeam_tools.common.units` so the
dependency runs one way (``units`` → ``atmosphere``).  Unit-system conversion
lives with the unit systems; the physics lives here.

Troposphere + lower stratosphere covers the whole FAR/CS 23.333(c) range
(sea level to 50,000 ft).
"""

from __future__ import annotations

import math

RHO0_SI = 1.225
"""Sea-level ISA density, kg/m^3."""

_T0 = 288.15
_LAPSE = 0.0065
_G = 9.80665
_R = 287.05287
_H_TROP = 11000.0
_T_TROP = _T0 - _LAPSE * _H_TROP


def isa_density_si(h_m: float) -> float:
    """ISA density (kg/m^3) at geopotential altitude ``h_m`` metres."""
    if h_m < 0.0:
        raise ValueError(f"altitude {h_m} m is below sea level")
    if h_m <= _H_TROP:
        theta = 1.0 - _LAPSE * h_m / _T0
        return RHO0_SI * theta ** (_G / (_LAPSE * _R) - 1.0)
    rho_trop = RHO0_SI * (_T_TROP / _T0) ** (_G / (_LAPSE * _R) - 1.0)
    return rho_trop * math.exp(-_G * (h_m - _H_TROP) / (_R * _T_TROP))
