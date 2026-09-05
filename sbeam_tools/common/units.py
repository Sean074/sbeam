"""Unit systems for the loads toolchain.

The solver is unit-neutral by charter §7 and never converts.  Tools are where
the regulation's dimensional content is allowed to live, so a tool that reads a
deck must be *told* which system that deck is in — there is no way to infer it.
Every dimensional constant a case generator needs hangs off a ``UnitSystem``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .atmosphere import isa_density_si

_KGM3_PER_SLUGFT3 = 515.378818
_M_PER_FT = 0.3048


@dataclass(frozen=True)
class UnitSystem:
    """Everything dimensional the regulation needs, in one model's units."""

    name: str
    length_per_ft: float
    """Model length units in one foot (1.0 imperial, 0.3048 SI)."""
    density_per_kgm3: float
    """Model density units in one kg/m^3."""
    g: float
    """Standard gravity, model units."""
    length_unit: str
    speed_unit: str

    @property
    def rho0(self) -> float:
        """Sea-level ISA density in model units — one source, the ISA at h = 0."""
        return isa_density(0.0, self)


UNIT_SYSTEMS: dict[str, UnitSystem] = {
    "SI": UnitSystem(
        name="SI",
        length_per_ft=_M_PER_FT,
        density_per_kgm3=1.0,
        g=9.80665,
        length_unit="m",
        speed_unit="m/s",
    ),
    "IMPERIAL": UnitSystem(
        name="IMPERIAL",
        length_per_ft=1.0,
        density_per_kgm3=1.0 / _KGM3_PER_SLUGFT3,
        g=32.174049,
        length_unit="ft",
        speed_unit="ft/s",
    ),
}


def isa_density(altitude: float, units: UnitSystem) -> float:
    """ISA density at ``altitude`` (model length units), in model density units."""
    h_m = altitude / units.length_per_ft * _M_PER_FT
    return isa_density_si(h_m) * units.density_per_kgm3
