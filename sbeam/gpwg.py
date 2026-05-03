"""Grid Point Weight Generator (GPWG) — mass and CG computation."""

from dataclasses import dataclass
import numpy as np

from sbeam.model.bulk_data import BulkData


@dataclass
class GpwgResult:
    total_mass: float
    cg_x: float
    cg_y: float
    cg_z: float


def compute_gpwg(bulk: BulkData) -> GpwgResult:
    """Compute total mass and centre of gravity from CBAR elements and CONM2 masses.

    CBAR mass = (rho * A + nsm) * L, distributed at element midpoint.
    CONM2 mass = Conm2.m at grid location.
    """
    mass_contributions = []  # list of (mass, x, y, z)

    # CBAR elements
    for cbar in bulk.cbars.values():
        pbar = bulk.pbars.get(cbar.pid)
        if pbar is None:
            continue
        mat1 = bulk.mat1s.get(pbar.mid)
        if mat1 is None:
            continue

        ga = bulk.grids.get(cbar.ga)
        gb = bulk.grids.get(cbar.gb)
        if ga is None or gb is None:
            continue

        ga_pos = np.array([ga.x, ga.y, ga.z])
        gb_pos = np.array([gb.x, gb.y, gb.z])
        L = np.linalg.norm(gb_pos - ga_pos)

        elem_mass = (mat1.rho * pbar.A + pbar.nsm) * L

        midpoint = 0.5 * (ga_pos + gb_pos)
        mass_contributions.append((elem_mass, midpoint[0], midpoint[1], midpoint[2]))

    # CONM2 point masses
    for conm2 in bulk.conm2s.values():
        grid = bulk.grids.get(conm2.gid)
        if grid is None:
            continue
        mass_contributions.append((conm2.m, grid.x, grid.y, grid.z))

    total_mass = sum(m for m, _, _, _ in mass_contributions)

    if total_mass == 0.0:
        return GpwgResult(total_mass=0.0, cg_x=0.0, cg_y=0.0, cg_z=0.0)

    cg_x = sum(m * x for m, x, _, _ in mass_contributions) / total_mass
    cg_y = sum(m * y for m, _, y, _ in mass_contributions) / total_mass
    cg_z = sum(m * z for m, _, _, z in mass_contributions) / total_mass

    return GpwgResult(
        total_mass=total_mass,
        cg_x=cg_x,
        cg_y=cg_y,
        cg_z=cg_z,
    )
