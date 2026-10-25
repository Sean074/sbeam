"""Grid Point Weight Generator (GPWG) — mass and CG computation."""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.coord_transform import build_transform
from sbeam.assembly.elements import iter_line_elements, line_element_mass_per_length


@dataclass
class GpwgResult:
    total_mass: float
    cg_x: float
    cg_y: float
    cg_z: float
    massset_sid: Optional[int] = None   # MASSSET SID for this case (None = baseline)
    massset_label: str = "BASELINE"


def compute_gpwg(bulk: BulkData, massset_sid: Optional[int] = None) -> GpwgResult:
    """Compute total mass and centre of gravity from line elements and CONM2 masses.

    CBAR / CROD / CONROD mass = (rho * A + nsm) * L, placed at the element midpoint.
    CONM2 mass = Conm2.m at grid location + offset (x1, x2, x3).

    ``massset_sid`` (Step 60) selects a MASSSET payload / mass case; ``None``
    gives the baseline configuration.
    """
    from sbeam.model.mass_overlay import resolve_mass_case
    case = resolve_mass_case(bulk, massset_sid)

    mass_contributions = []  # list of (mass, x, y, z)

    # Line elements: CBAR, CROD, CONROD (assembly/elements.py registry, #38).
    # Elements whose property, material or grids are missing are skipped, as
    # before: the viewer calls this on partially valid decks.
    for elem in iter_line_elements(bulk):
        try:
            m_lin = line_element_mass_per_length(elem, bulk)
        except KeyError:
            continue

        ga = bulk.grids.get(elem.ga)
        gb = bulk.grids.get(elem.gb)
        if ga is None or gb is None:
            continue

        ga_pos = np.array([ga.x, ga.y, ga.z])
        gb_pos = np.array([gb.x, gb.y, gb.z])
        L = np.linalg.norm(gb_pos - ga_pos)

        elem_mass = case.scale * m_lin * L

        midpoint = 0.5 * (ga_pos + gb_pos)
        mass_contributions.append((elem_mass, midpoint[0], midpoint[1], midpoint[2]))

    # CONM2 point masses
    for conm2 in case.conm2s.values():
        grid = bulk.grids.get(conm2.gid)
        if grid is None:
            continue
        r_cid = np.array([conm2.x1, conm2.x2, conm2.x3])
        if conm2.cid != 0:
            R = build_transform(conm2.cid, bulk.cord2rs)
            r = R @ r_cid
        else:
            r = r_cid
        mass_contributions.append((conm2.m, grid.x + r[0], grid.y + r[1], grid.z + r[2]))

    total_mass = sum(m for m, _, _, _ in mass_contributions)

    if total_mass == 0.0:
        return GpwgResult(
            total_mass=0.0, cg_x=0.0, cg_y=0.0, cg_z=0.0,
            massset_sid=case.sid, massset_label=case.label,
        )

    cg_x = sum(m * x for m, x, _, _ in mass_contributions) / total_mass
    cg_y = sum(m * y for m, _, y, _ in mass_contributions) / total_mass
    cg_z = sum(m * z for m, _, _, z in mass_contributions) / total_mass

    return GpwgResult(
        total_mass=total_mass,
        cg_x=cg_x,
        cg_y=cg_y,
        cg_z=cg_z,
        massset_sid=case.sid,
        massset_label=case.label,
    )
