"""Read an airplane's own properties out of its deck.

Case generators need reference geometry, weight per mass case and a lift-curve
slope.  Every one of those already exists in the model, so a tool reads them
back rather than asking the user to retype numbers that could then disagree
with the deck actually being solved.

The lift-curve slope is taken **rigid**: ``compute_rigid_derivs`` needs no
structure, no mass and no dynamic pressure, so reading a deck stays single-pass
and no trim is solved.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx
from sbeam.assembly.coord_transform import get_transform
from sbeam.gpwg import compute_gpwg
from sbeam.model.aero import require_aeros
from sbeam.model.mass_overlay import resolve_mass_case
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol144 import compute_rigid_derivs


@dataclass(frozen=True)
class MassCase:
    sid: Optional[int]
    label: str
    mass: float


@dataclass(frozen=True)
class Airplane:
    """Everything a case generator needs, read from the deck rather than retyped."""

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

    ``trim_template`` names the TRIM whose prescribed labels the generated cases
    inherit — every label except ``URDD3``, which a gust or maneuver card
    supplies.
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
        ref_pt = np.zeros(3)
    derivs = compute_rigid_derivs(
        aero, djx, ["ANGLEA"], bulk, float(ref_pt[0]), ref_pt
    )
    cz_alpha = derivs["ANGLEA"]["CZ"]
    if cz_alpha <= 0.0:
        raise ValueError(
            f"rigid CZ_alpha = {cz_alpha:.6g} is not positive — a load-factor "
            f"formula needs a positive airplane normal-force slope"
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
