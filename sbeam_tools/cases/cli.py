"""``sbeam-cases`` — generate design load cases for an sbeam deck.

Today this generates FAR/CS 23.341 quasi-static gust cases (issue #1); the
maneuver corner points of 23.337 and the case index join it under issue #4.

Speeds and altitudes are given in the **model's own units** (m/s and m under
``--units SI``; ft/s and ft under ``--units IMPERIAL`` — note ft/s, *not*
knots).  Declaring the unit system is mandatory: there is no way to infer it
from a deck, since sbeam's card fields are unit-neutral by charter §7.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..common.deck import read_airplane
from ..common.units import UNIT_SYSTEMS
from .gust import emit_deck, format_summary, generate_cases


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
        prog="sbeam-cases",
        description=(
            "Generate design load cases for an sbeam deck. "
            "Speeds and altitudes are in the model's own units."
        ),
    )
    p.add_argument("deck", type=Path, help="SOL 144 driver deck (its INCLUDEs are reused)")
    p.add_argument("--units", required=True, choices=sorted(UNIT_SYSTEMS),
                   help="unit system of the deck — supplies rho_0, g and the ISA atmosphere")
    p.add_argument("--trim-template", required=True, type=int, metavar="SID",
                   help="TRIM whose prescribed labels (except URDD3) the cases inherit")
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
    command = "sbeam-cases " + " ".join(argv if argv is not None else sys.argv[1:])
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
