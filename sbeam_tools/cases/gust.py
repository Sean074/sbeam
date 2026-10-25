"""Quasi-static gust load cases — the Pratt formula (FAR/CS 23.341).

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` (issue #1).

The formula, in consistent units::

    n   = 1 +/- dn,   dn = K_g * rho_0 * U_de * V * a * S / (2 * W)
    K_g = 0.88 * mu / (5.3 + mu)
    mu  = 2 * (W/S) / (rho * cbar * a * g)

``rho_0`` is the sea-level density, pairing with ``V`` and ``U_de`` as
**equivalent** airspeeds; ``rho`` is the density **at altitude** and appears only
in ``mu``.  Transposing the two is the classic error in this formula, so they
arrive from different places by construction: ``rho_0`` from the unit system,
``rho(h)`` from the ISA model.

``a`` is the airplane **normal-force** curve slope per radian — the regulation's
``C_NA`` — which is sbeam's body-axis ``CZ_alpha`` (charter §2), *not* wind-axis
``CL_alpha``.  It is taken **rigid**: Pratt is a rigid-airplane derivation in
plunge, so an elastic slope would mix a flexible quantity into a rigid-body
formula whose empirical constants were calibrated on the rigid basis.  ``K_g``
alleviates rigid-body plunge during gust penetration together with unsteady lift
growth; it is *not* a structural-flexibility correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sbeam.model.aero import Trim
from sbeam.model.card_writers import write_gustlf, write_trim
from sbeam.model.gust import Gustlf

from ..common.deck import Airplane, MassCase
from ..common.units import UnitSystem, isa_density

# --------------------------------------------------------------------------- #
# FAR/CS 23.333(c) derived gust velocities
# --------------------------------------------------------------------------- #

_UDE_FPS: dict[str, tuple[float, float]] = {
    # design speed: (U_de at or below 20,000 ft, U_de at 50,000 ft), ft/s EAS
    "VC": (50.0, 25.0),
    "VD": (25.0, 12.5),
    "VB": (66.0, 38.0),
}
_ALT_LOW_FT = 20000.0
_ALT_HIGH_FT = 50000.0


def derived_gust_velocity(speed: str, altitude: float, units: UnitSystem) -> float:
    """``U_de`` per 23.333(c) at ``altitude``, in model speed units.

    Constant below 20,000 ft, then reduced linearly to the 50,000 ft value.
    Above 50,000 ft the regulation gives no value, so this raises rather than
    extrapolate a certification quantity.
    """
    kind = speed.upper()
    if kind not in _UDE_FPS:
        raise ValueError(f"unknown design speed {speed!r} — expected one of {sorted(_UDE_FPS)}")
    alt_ft = altitude / units.length_per_ft
    if alt_ft < 0.0:
        raise ValueError(f"altitude {altitude} {units.length_unit} is below sea level")
    if alt_ft > _ALT_HIGH_FT:
        raise ValueError(
            f"altitude {altitude} {units.length_unit} ({alt_ft:.0f} ft) is above the "
            f"50,000 ft limit of the 23.333(c) gust schedule"
        )
    low, high = _UDE_FPS[kind]
    if alt_ft <= _ALT_LOW_FT:
        ude_fps = low
    else:
        frac = (alt_ft - _ALT_LOW_FT) / (_ALT_HIGH_FT - _ALT_LOW_FT)
        ude_fps = low + frac * (high - low)
    return ude_fps * units.length_per_ft


# --------------------------------------------------------------------------- #
# The Pratt formula
# --------------------------------------------------------------------------- #


def mass_ratio(wing_loading: float, rho: float, cbar: float, a: float, g: float) -> float:
    """``mu = 2 (W/S) / (rho * cbar * a * g)`` — density at **altitude**."""
    denom = rho * cbar * a * g
    if denom <= 0.0:
        raise ValueError("mass_ratio: rho, cbar, a and g must all be positive")
    return 2.0 * wing_loading / denom


def alleviation_factor(mu: float) -> float:
    """``K_g = 0.88 mu / (5.3 + mu)`` — strictly within ``(0, 0.88)``."""
    if mu <= 0.0:
        raise ValueError("alleviation_factor: mu must be positive")
    return 0.88 * mu / (5.3 + mu)


def gust_increment(
    kg: float, rho0: float, ude: float, v_eas: float, a: float,
    sref: float, weight: float,
) -> float:
    """``dn = K_g rho_0 U_de V a S / (2 W)`` — density at **sea level**."""
    if weight <= 0.0:
        raise ValueError("gust_increment: weight must be positive")
    return kg * rho0 * ude * v_eas * a * sref / (2.0 * weight)


# --------------------------------------------------------------------------- #
# Case generation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GustCase:
    """One generated gust case: the inputs, the derivation and the result."""

    sid: int
    speed: str
    sense: str
    altitude: float
    v_eas: float
    ude: float
    rho: float
    rho0: float
    mass_case: MassCase
    weight: float
    a: float
    mu: float
    kg: float
    dn: float
    n: float
    q: float
    g: float
    units: UnitSystem

    @property
    def urdd3(self) -> float:
        """``URDD3 = -n g`` — the only quantity the solver derives from ``n``."""
        return -self.n * self.g

    @property
    def title(self) -> str:
        sign = "+" if self.sense == "UP" else "-"
        return (
            f"{sign}{self.ude:.4g} {self.units.speed_unit} gust at {self.speed}, "
            f"alt {self.altitude:g} {self.units.length_unit}, "
            f"{self.mass_case.label}, n = {self.n:.4g}"
        )


def generate_cases(
    airplane: Airplane, units: UnitSystem, speeds: dict[str, float],
    altitudes: Sequence[float], g: float, sid_base: int,
) -> list[GustCase]:
    """The full ``(design speed x altitude x mass case x sense)`` set."""
    cases: list[GustCase] = []
    sid = sid_base
    rho0 = units.rho0
    a = airplane.cz_alpha
    for speed in sorted(speeds):
        v_eas = speeds[speed]
        if v_eas <= 0.0:
            raise ValueError(f"{speed}: speed must be positive, got {v_eas}")
        for altitude in altitudes:
            ude = derived_gust_velocity(speed, altitude, units)
            rho = isa_density(altitude, units)
            q = 0.5 * rho0 * v_eas * v_eas
            for mass_case in airplane.mass_cases:
                weight = mass_case.mass * g
                mu = mass_ratio(weight / airplane.sref, rho, airplane.cref, a, g)
                kg = alleviation_factor(mu)
                dn = gust_increment(kg, rho0, ude, v_eas, a, airplane.sref, weight)
                for sense, n in (("UP", 1.0 + dn), ("DOWN", 1.0 - dn)):
                    cases.append(
                        GustCase(
                            sid=sid, speed=speed, sense=sense, altitude=altitude,
                            v_eas=v_eas, ude=ude, rho=rho, rho0=rho0,
                            mass_case=mass_case, weight=weight, a=a, mu=mu,
                            kg=kg, dn=dn, n=n, q=q, g=g, units=units,
                        )
                    )
                    sid += 1
    return cases


# --------------------------------------------------------------------------- #
# Deck emission
# --------------------------------------------------------------------------- #


def write_gustlf_card(case: GustCase) -> list[str]:
    """Emit one ``GUSTLF`` through the solver's own card writer.

    Going through ``card_writers.write_gustlf`` rather than formatting fields
    here is what makes the generator and the parser agree by construction — the
    S-GUST6b half of the design note's round-trip gate.
    """
    return write_gustlf(Gustlf(
        sid=case.sid, trimid=case.sid, n=case.n, g=case.g,
        ude=case.ude, veas=case.v_eas, kg=case.kg, mu=case.mu,
        a=case.a, asrc="RIGID", alt=case.altitude,
    ))


def emit_deck(
    cases: Sequence[GustCase], airplane: Airplane, units: UnitSystem,
    command: str, title: str,
) -> list[str]:
    """A complete SOL 144 driver: case control, then the TRIM/GUSTLF bulk cards."""
    lines: list[str] = [
        f"$ {title}",
        "$",
        "$ GENERATED by sbeam-cases -- do not hand-edit; regenerate.",
        f"$   {command}",
        "$",
        "$ FAR/CS 23.341 quasi-static gust load cases.  Each GUSTLF carries the load",
        "$ factor N (which the solver uses, as URDD3 = -N*G) plus the derivation that",
        "$ produced it (which the solver only echoes to the f06).",
        "$",
        f"$ Units: {units.name} (lengths {units.length_unit}, speeds {units.speed_unit}); "
        + (
            f"g = {cases[0].g:g} (unit-system standard)"
            if cases[0].g == units.g
            else f"g = {cases[0].g:g} (overriding the {units.g:g} standard)"
        ),
        f"$ Rigid CZ_alpha = {airplane.cz_alpha:.6g} /rad, "
        f"S = {airplane.sref:g}, cbar = {airplane.cref:g}",
        "$",
        "SOL 144",
        f"TITLE = {title}",
    ]
    lines += [f"INCLUDE '{inc}'" for inc in airplane.includes]
    lines.append("$")

    for case in cases:
        lines.append(f"SUBCASE {case.sid}")
        lines.append(f"  TITLE   = {case.title}")
        lines.append(f"  GUSTLF  = {case.sid}")
        if case.mass_case.sid is not None:
            lines.append(f"  MASSSET = {case.mass_case.sid}")
        if airplane.template_spc is not None:
            lines.append(f"  SPC     = {airplane.template_spc}")
        lines.append("  DISPLACEMENT = ALL")
        lines.append("  FORCE        = ALL")
        lines.append("$")

    lines.append("BEGIN BULK")
    lines.append("$")
    for case in cases:
        lines.append(f"$ {case.title}")
        lines.append(
            f"$   mu = {case.mu:.6g}   K_g = {case.kg:.6g}   "
            f"dn = {case.dn:.6g}   W = {case.weight:.6g}"
        )
        trim = Trim(
            sid=case.sid, mach=airplane.mach, q=case.q,
            vars=dict(airplane.template_vars), rhoref=case.rho,
        )
        lines += write_trim(trim)
        lines += write_gustlf_card(case)
        lines.append("$")
    lines.append("ENDDATA")
    return lines


def format_summary(cases: Sequence[GustCase], units: UnitSystem) -> str:
    """The human-readable table printed alongside the deck."""
    head = (
        f"{'SID':>6}  {'SPEED':<5} {'SENSE':<5} {'ALT':>9} {'U_DE':>9} "
        f"{'RHO':>10} {'MASS CASE':<10} {'MU':>9} {'K_G':>8} {'DN':>9} {'N':>9}"
    )
    rows = [head, "-" * len(head)]
    for c in cases:
        rows.append(
            f"{c.sid:>6}  {c.speed:<5} {c.sense:<5} {c.altitude:>9.4g} "
            f"{c.ude:>9.4g} {c.rho:>10.5g} {c.mass_case.label:<10} "
            f"{c.mu:>9.4f} {c.kg:>8.4f} {c.dn:>9.4f} {c.n:>9.4f}"
        )
    rows.append("")
    rows.append(
        f"Units: {units.name}.  Speeds are EQUIVALENT airspeeds in "
        f"{units.speed_unit}; altitudes in {units.length_unit}."
    )
    return "\n".join(rows)
