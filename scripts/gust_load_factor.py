#!/usr/bin/env python3
"""Generate FAR/CS 23.341 quasi-static gust load cases for an sbeam deck.

This tool lives **outside** the ``sbeam/`` solver package on purpose.  The gust
regulation is dimensional — ``U_de`` is 50 ft/s, the gust schedule is keyed to
altitude in feet, ``rho_0`` is a sea-level density — while conventions charter
§7 forbids unit-converting fields anywhere in the solver, and sbeam has no
atmosphere model.  Rather than breach the charter, the whole dimensional
calculation happens here and the solver receives only a **dimensionless load
factor** on a ``GUSTLF`` provenance card.  Charter §7 governs the solver; a tool
that writes decks *for* the solver is free to know what a foot is.

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` (issue #1).

The formula (FAR/CS 23.341), in consistent units::

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
plunge, so feeding it an elastic slope would mix a flexible quantity into a
rigid-body formula whose empirical constants were calibrated on the rigid basis.
``K_g`` alleviates rigid-body plunge during gust penetration together with
unsteady lift growth; it is *not* a structural-flexibility correction.

Usage::

    .venv/bin/python scripts/gust_load_factor.py sample/cessna210_flagship_trim.bdf \\
        --units SI --trim-template 1 --vc 85.0 --vd 106.0 \\
        --altitude 0 --massset 10,20,30 -o sample/cessna210_flagship_gust.bdf

Speeds and altitudes are given in the **model's own units** (m/s and m under
``--units SI``; ft/s and ft under ``--units IMPERIAL`` — note ft/s, *not* knots).
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.assembly.coord_transform import get_transform
from sbeam.gpwg import compute_gpwg
from sbeam.model.aero import Trim, require_aeros
from sbeam.model.card_writers import Field, write_card, write_trim
from sbeam.model.mass_overlay import resolve_mass_case
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol144 import compute_rigid_derivs

# --------------------------------------------------------------------------- #
# Unit systems
# --------------------------------------------------------------------------- #

_KGM3_PER_SLUGFT3 = 515.378818


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
        length_per_ft=0.3048,
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

# --------------------------------------------------------------------------- #
# ISA standard atmosphere
# --------------------------------------------------------------------------- #

_ISA_RHO0_SI = 1.225
_ISA_T0 = 288.15
_ISA_LAPSE = 0.0065
_ISA_G = 9.80665
_ISA_R = 287.05287
_ISA_H_TROP = 11000.0
_ISA_T_TROP = _ISA_T0 - _ISA_LAPSE * _ISA_H_TROP


def _isa_density_si(h_m: float) -> float:
    """ISA density (kg/m^3) at geopotential altitude ``h_m`` metres."""
    if h_m < 0.0:
        raise ValueError(f"altitude {h_m} m is below sea level")
    if h_m <= _ISA_H_TROP:
        theta = 1.0 - _ISA_LAPSE * h_m / _ISA_T0
        return _ISA_RHO0_SI * theta ** (_ISA_G / (_ISA_LAPSE * _ISA_R) - 1.0)
    rho_trop = _ISA_RHO0_SI * (_ISA_T_TROP / _ISA_T0) ** (
        _ISA_G / (_ISA_LAPSE * _ISA_R) - 1.0
    )
    return rho_trop * math.exp(
        -_ISA_G * (h_m - _ISA_H_TROP) / (_ISA_R * _ISA_T_TROP)
    )


def isa_density(altitude: float, units: UnitSystem) -> float:
    """ISA density at ``altitude`` (model length units), in model density units."""
    h_m = altitude / units.length_per_ft * 0.3048
    return _isa_density_si(h_m) * units.density_per_kgm3


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
# Reading the airplane out of its own deck
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MassCase:
    sid: Optional[int]
    label: str
    mass: float


@dataclass(frozen=True)
class Airplane:
    """Everything the formula needs, read from the deck rather than retyped."""

    sref: float
    cref: float
    cz_alpha: float
    mach: float
    includes: list[str]
    template_vars: dict[str, float]
    template_spc: Optional[int]
    mass_cases: list[MassCase]


def read_airplane(
    deck: Path, trim_template: int, massets: Sequence[Optional[int]],
) -> Airplane:
    """Parse ``deck`` and extract reference geometry, mass cases and rigid ``CZ_alpha``.

    The rigid derivative needs no structure, no mass and no dynamic pressure
    (``compute_rigid_derivs``), so this is single-pass: no trim is solved.
    """
    cc, bulk = parse_bdf(str(deck))
    aeros = require_aeros(bulk)

    template = bulk.trims.get(trim_template)
    if template is None:
        raise ValueError(
            f"--trim-template {trim_template} names no TRIM card in {deck} "
            f"(found: {sorted(bulk.trims)})"
        )
    template_vars = {k: v for k, v in template.vars.items() if k.upper() != "URDD3"}

    spc = next(
        (sc.spc_sid for sc in cc.subcases if sc.trim_sid == trim_template),
        None,
    )

    aero = build_aero_model(bulk)
    djx = build_djx(aero.boxes, ["ANGLEA"], bulk, id_to_k=aero.require_box_id_to_k())
    if aeros.rcsid:
        ref_pt, _r = get_transform(aeros.rcsid, bulk.cord2rs)
    else:
        import numpy as np

        ref_pt = np.zeros(3)
    derivs = compute_rigid_derivs(
        aero, djx, ["ANGLEA"], bulk, float(ref_pt[0]), ref_pt
    )
    cz_alpha = derivs["ANGLEA"]["CZ"]
    if cz_alpha <= 0.0:
        raise ValueError(
            f"rigid CZ_alpha = {cz_alpha:.6g} is not positive — the Pratt formula "
            f"needs a positive airplane normal-force slope"
        )

    cases: list[MassCase] = []
    for sid in massets:
        label = "BASELINE" if sid is None else resolve_mass_case(bulk, sid).label
        mass = compute_gpwg(bulk, sid).total_mass
        if mass <= 0.0:
            raise ValueError(f"MASSSET {sid}: total mass is {mass} — cannot form a weight")
        cases.append(MassCase(sid=sid, label=label, mass=mass))

    return Airplane(
        sref=aeros.sref,
        cref=aeros.cref,
        cz_alpha=cz_alpha,
        mach=template.mach,
        includes=list(cc.includes),
        template_vars=template_vars,
        template_spc=spc,
        mass_cases=cases,
    )


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


def emit_deck(
    cases: Sequence[GustCase], airplane: Airplane, units: UnitSystem,
    command: str, title: str,
) -> list[str]:
    """A complete SOL 144 driver: case control, then the TRIM/GUSTLF bulk cards."""
    lines: list[str] = [
        f"$ {title}",
        "$",
        "$ GENERATED by scripts/gust_load_factor.py -- do not hand-edit; regenerate.",
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


def write_gustlf_card(case: GustCase) -> list[str]:
    """Emit one ``GUSTLF``.

    Written through ``write_card`` (so field formatting already follows
    ``fmt_real8``, DEF-M12).  When the ``GUSTLF`` card lands in ``sbeam/model``
    this becomes a call to ``card_writers.write_gustlf`` and the two agree by
    construction.
    """
    fields: list[Field] = [
        case.sid, case.sid, case.n, case.g,
        case.ude, case.v_eas, case.kg, case.mu,
        case.a, "RIGID", case.altitude,
    ]
    return write_card("GUSTLF", fields)


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


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_massets(raw: Optional[str]) -> list[Optional[int]]:
    if raw is None or raw.strip() == "":
        return [None]
    out: list[Optional[int]] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(int(tok))
    return out or [None]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gust_load_factor.py",
        description=(
            "Generate FAR/CS 23.341 quasi-static gust load cases for an sbeam deck. "
            "Speeds and altitudes are in the model's own units."
        ),
    )
    p.add_argument("deck", type=Path, help="SOL 144 driver deck (its INCLUDEs are reused)")
    p.add_argument("--units", required=True, choices=sorted(UNIT_SYSTEMS),
                   help="unit system of the deck — supplies rho_0, g and the ISA atmosphere")
    p.add_argument("--trim-template", required=True, type=int, metavar="SID",
                   help="TRIM whose prescribed labels (except URDD3) the gust cases inherit")
    p.add_argument("--vc", type=float, help="design cruising speed V_C (EAS, model units)")
    p.add_argument("--vd", type=float, help="design dive speed V_D (EAS, model units)")
    p.add_argument("--vb", type=float,
                   help="design rough-air speed V_B (EAS, model units; commuter category)")
    p.add_argument("--altitude", type=float, action="append", metavar="ALT",
                   help="altitude in model units; repeatable (default: 0)")
    p.add_argument("--massset", type=str, metavar="SIDS",
                   help="comma-separated MASSSET SIDs (default: the baseline mass)")
    p.add_argument("--g", type=float, dest="gravity",
                   help="gravitational acceleration (default: the unit system's standard)")
    p.add_argument("--sid-base", type=int, default=9000,
                   help="first SID for generated TRIM/GUSTLF cards (default: 9000)")
    p.add_argument("--title", type=str, help="TITLE for the generated driver")
    p.add_argument("-o", "--output", type=Path, help="write the deck here (default: stdout)")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    units = UNIT_SYSTEMS[str(args.units)]
    gravity = float(args.gravity) if args.gravity is not None else units.g
    if gravity <= 0.0:
        raise SystemExit("--g must be positive")

    speeds: dict[str, float] = {}
    for key, value in (("VC", args.vc), ("VD", args.vd), ("VB", args.vb)):
        if value is not None:
            speeds[key] = float(value)
    if not speeds:
        raise SystemExit("at least one of --vc / --vd / --vb is required")

    altitudes: list[float] = [float(a) for a in (args.altitude or [0.0])]
    massets = _parse_massets(args.massset)
    deck = Path(args.deck)
    template = int(args.trim_template)

    airplane = read_airplane(deck, template, massets)
    cases = generate_cases(
        airplane, units, speeds, altitudes, gravity, int(args.sid_base)
    )

    title = str(args.title) if args.title else f"{deck.stem} — FAR/CS 23.341 gust cases"
    command = "gust_load_factor.py " + " ".join(
        argv if argv is not None else sys.argv[1:]
    )
    lines = emit_deck(cases, airplane, units, command, title)

    output = Path(args.output) if args.output else None
    if output is not None:
        output.write_text("\n".join(lines) + "\n")
        print(f"Wrote {len(cases)} gust cases to {output}\n")
    else:
        print("\n".join(lines))
        print()
    print(format_summary(cases, units))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
