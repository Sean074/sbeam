"""Grid Point Weight Generator (GPWG) — mass and CG computation."""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.types import FloatArray
from sbeam.assembly.coord_transform import build_transform
from sbeam.assembly.elements import iter_line_elements, line_element_mass_per_length


@dataclass
class GpwgResult:
    total_mass: float
    cg_x: float
    cg_y: float
    cg_z: float
    massset_sid: Optional[int] = None   # MASSCASE SID for this case (None = baseline)
    massset_label: str = "BASELINE"


def compute_gpwg(bulk: BulkData, massset_sid: Optional[int] = None) -> GpwgResult:
    """Compute total mass and centre of gravity from line elements and CONM2 masses.

    CBAR / CROD / CONROD mass = (rho * A + nsm) * L, placed at the element midpoint.
    CONM2 mass = Conm2.m at grid location + offset (x1, x2, x3).

    ``massset_sid`` (Step 60) selects a MASSCASE payload / mass case; ``None``
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


# ---------------------------------------------------------------------------
# MSC's grid point weight generator printout (PARAM,GRDPNT; QRG p.885; #90)
# ---------------------------------------------------------------------------

@dataclass
class GpwgTable:
    """The quantities MSC prints from the grid point weight generator (AAUG 2023.1 PDF p.269).

    ``mo`` is the rigid-body mass matrix about the reference point in basic axes.
    ``mass[i]`` and ``cg[i]`` are the mass and the C.G. (relative to the reference point,
    S axes) seen by a translation along S axis i; the component along the direction itself
    is undefined and printed as 0.0, as MSC does.  ``i_s`` is the inertia tensor about the
    C.G. in S axes, ``i_q`` its principal values and ``q`` the principal directions
    (columns).
    """
    reference_point: int
    mo: FloatArray
    s: FloatArray
    mass: FloatArray
    cg: FloatArray
    i_s: FloatArray
    i_q: FloatArray
    q: FloatArray


def rigid_body_mass_matrix(bulk: BulkData, reference_point: int) -> FloatArray:
    """MO = Dᵀ M D: the 6×6 rigid-body mass matrix about the reference point, basic axes.

    D maps the reference point's six rigid motions to every grid's six DOFs (sbeam carries
    every DOF in basic axes).  M is the assembled consistent mass matrix, so MO's mass and
    first moments equal any lumping's; the inertias include each CBAR's distributed rotary
    inertia, where MSC's default lumped mass (COUPMASS -1) would not (QRG p.885).
    """
    from sbeam.assembly.load_vector import build_grid_index
    from sbeam.assembly.mass_matrix import assemble_global_mass

    grid = bulk.grids.get(reference_point)
    r0 = np.array([grid.x, grid.y, grid.z]) if grid is not None else np.zeros(3)
    grid_index = build_grid_index(bulk)
    d = np.zeros((6 * len(grid_index), 6))
    for gid, i in grid_index.items():
        g = bulk.grids[gid]
        x, y, z = np.array([g.x, g.y, g.z]) - r0
        d[6 * i:6 * i + 3, 0:3] = np.eye(3)
        # translation of the grid = θ × (r − r0)
        d[6 * i:6 * i + 3, 3:6] = [[0.0, z, -y], [-z, 0.0, x], [y, -x, 0.0]]
        d[6 * i + 3:6 * i + 6, 3:6] = np.eye(3)
    m = assemble_global_mass(bulk)
    return np.asarray(d.T @ (m @ d))


def reduce_rigid_body_mass(mo: FloatArray, reference_point: int) -> GpwgTable:
    """MSC's reduction of MO to directional masses, C.G.s and inertias (AAUG p.269 numbers).

    S is the identity: every sbeam mass (CBAR, CROD, CONROD, CONM2) is the same in each
    translation, so the translational block of MO is m·I and is already principal.
    """
    mo = np.asarray(mo, dtype=float)
    mass = np.array([mo[0, 0], mo[1, 1], mo[2, 2]])
    with np.errstate(divide="ignore", invalid="ignore"):
        def ratio(a: float, b: float) -> float:
            return float(a / b) + 0.0 if b != 0.0 else 0.0      # + 0.0: no "-0.0" printed
        cg = np.array([
            [0.0, ratio(-mo[0, 5], mass[0]), ratio(mo[0, 4], mass[0])],
            [ratio(mo[1, 5], mass[1]), 0.0, ratio(-mo[1, 3], mass[1])],
            [ratio(-mo[2, 4], mass[2]), ratio(mo[2, 3], mass[2]), 0.0],
        ])
    mx, my, mz = mass
    (_, yx, zx), (xy, _, zy), (xz, yz, _) = cg
    i_s = np.empty((3, 3))
    i_s[0, 0] = mo[3, 3] - my * zy ** 2 - mz * yz ** 2
    i_s[1, 1] = mo[4, 4] - mz * xz ** 2 - mx * zx ** 2
    i_s[2, 2] = mo[5, 5] - mx * yx ** 2 - my * xy ** 2
    i_s[0, 1] = i_s[1, 0] = -mo[3, 4] - mz * xz * yz
    i_s[0, 2] = i_s[2, 0] = -mo[3, 5] - my * xy * zy
    i_s[1, 2] = i_s[2, 1] = -mo[4, 5] - mx * yx * zx
    # Principal inertias of the tensor with the products sign-flipped back (I_ij = -∫xy dm)
    tensor = np.array([[i_s[0, 0], -i_s[0, 1], -i_s[0, 2]],
                       [-i_s[1, 0], i_s[1, 1], -i_s[1, 2]],
                       [-i_s[2, 0], -i_s[2, 1], i_s[2, 2]]])
    vals, vecs = np.linalg.eigh(tensor)
    order = np.argsort(vals)[::-1]
    q = vecs[:, order]
    if np.linalg.det(q) < 0.0:          # right-handed principal axes, as MSC's printed Q
        q[:, 2] = -q[:, 2]
    return GpwgTable(reference_point=reference_point, mo=mo, s=np.eye(3), mass=mass, cg=cg,
                     i_s=i_s, i_q=vals[order], q=q + 0.0)


def compute_gpwg_table(bulk: BulkData) -> Optional[GpwgTable]:
    """The GPWG printout PARAM,GRDPNT asks for, or ``None`` when GRDPNT is -1 (default)."""
    if bulk.grdpnt < 0:
        return None
    return reduce_rigid_body_mass(rigid_body_mass_matrix(bulk, bulk.grdpnt), bulk.grdpnt)
