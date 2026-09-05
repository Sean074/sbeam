"""Load vector assembly for FEA."""

from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.load import Grav
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.load import Force, Moment
from sbeam.assembly.coord_transform import to_global
from sbeam.types import FloatArray, SparseMatrix


def build_grid_index(bulk: BulkData) -> dict[int, int]:
    """Return {gid: i} where i is the 0-based index in sorted GID order."""
    return {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}


def _apply_forces_to_vector(
    f_vec: FloatArray, forces: list[Force], grid_index: dict[int, int],
    cord2rs: dict[int, Cord2r], scale: float = 1.0
) -> None:
    """Add scaled force contributions to f_vec in-place, rotating CID → global."""
    for force in forces:
        if force.gid not in grid_index:
            continue
        i = grid_index[force.gid]
        n = to_global(np.array([force.n1, force.n2, force.n3]), force.cid, cord2rs)
        f_vec[6 * i + 0] += scale * force.f * n[0]
        f_vec[6 * i + 1] += scale * force.f * n[1]
        f_vec[6 * i + 2] += scale * force.f * n[2]


def _apply_moments_to_vector(
    f_vec: FloatArray, moments: list[Moment], grid_index: dict[int, int],
    cord2rs: dict[int, Cord2r], scale: float = 1.0
) -> None:
    """Add scaled moment contributions to f_vec in-place, rotating CID → global."""
    for moment in moments:
        if moment.gid not in grid_index:
            continue
        i = grid_index[moment.gid]
        n = to_global(np.array([moment.n1, moment.n2, moment.n3]), moment.cid, cord2rs)
        f_vec[6 * i + 3] += scale * moment.m * n[0]
        f_vec[6 * i + 4] += scale * moment.m * n[1]
        f_vec[6 * i + 5] += scale * moment.m * n[2]


def _apply_grav_to_vector(
    grav: Grav,
    bulk: BulkData,
    f_vec: FloatArray,
    grid_index: dict[int, int],
    scale: float = 1.0,
    M: Optional[SparseMatrix] = None,
) -> None:
    """Add gravity body-force contribution to f_vec in-place.

    f_grav = scale * M_global @ a_field, where a_field has G*[N1,N2,N3] at every
    translational DOF triplet and zero at rotational DOFs.

    M is the pre-assembled global mass matrix; if None it is assembled here (single-GRAV
    fast-path, avoids the import in the common case where the caller pre-assembles it).
    """
    if M is None:
        from sbeam.assembly.mass_matrix import assemble_global_mass
        M = assemble_global_mass(bulk)

    a_global = to_global(
        np.array([grav.n1, grav.n2, grav.n3]), grav.cid, bulk.cord2rs
    ) * grav.g

    n = len(f_vec)
    a_field = np.zeros(n)
    for i in range(len(grid_index)):
        a_field[6 * i + 0] = a_global[0]
        a_field[6 * i + 1] = a_global[1]
        a_field[6 * i + 2] = a_global[2]

    f_vec += scale * (M @ a_field)


def assemble_load_vector(bulk: BulkData, load_sid: int) -> FloatArray:
    """Assemble global load vector for the given load SID.

    Handles:
      - Direct FORCE / MOMENT SIDs
      - LOAD card (linear combination of other FORCE/MOMENT SIDs)

    Raises ValueError if load_sid is not found in any load dictionary.
    """
    if (
        load_sid not in bulk.loads
        and load_sid not in bulk.forces
        and load_sid not in bulk.moments
        and load_sid not in bulk.gravs
    ):
        raise ValueError(
            f"Load SID {load_sid} not found in LOAD, FORCE, MOMENT, or GRAV bulk data. "
            "Check the LOAD case control entry."
        )

    grid_index = build_grid_index(bulk)
    n = 6 * len(grid_index)
    f_vec = np.zeros(n)
    cord2rs = bulk.cord2rs

    # Pre-assemble mass matrix once if any GRAV loads are present.
    grav_sids_needed = set()
    if load_sid in bulk.loads:
        for (_, sid_i) in bulk.loads[load_sid].components:
            if sid_i in bulk.gravs:
                grav_sids_needed.add(sid_i)
    elif load_sid in bulk.gravs:
        grav_sids_needed.add(load_sid)

    M = None
    if grav_sids_needed:
        from sbeam.assembly.mass_matrix import assemble_global_mass
        M = assemble_global_mass(bulk)

    if load_sid in bulk.loads:
        # LOAD card: f = s * sum(scale_i * load_sid_i)
        load = bulk.loads[load_sid]
        s = load.s
        for (scale_i, sid_i) in load.components:
            combined_scale = s * scale_i
            if sid_i in bulk.forces:
                _apply_forces_to_vector(f_vec, bulk.forces[sid_i], grid_index, cord2rs, scale=combined_scale)
            if sid_i in bulk.moments:
                _apply_moments_to_vector(f_vec, bulk.moments[sid_i], grid_index, cord2rs, scale=combined_scale)
            if sid_i in bulk.gravs:
                _apply_grav_to_vector(bulk.gravs[sid_i], bulk, f_vec, grid_index, scale=combined_scale, M=M)
    else:
        # Direct FORCE, MOMENT, or GRAV SID
        if load_sid in bulk.forces:
            _apply_forces_to_vector(f_vec, bulk.forces[load_sid], grid_index, cord2rs)
        if load_sid in bulk.moments:
            _apply_moments_to_vector(f_vec, bulk.moments[load_sid], grid_index, cord2rs)
        if load_sid in bulk.gravs:
            _apply_grav_to_vector(bulk.gravs[load_sid], bulk, f_vec, grid_index, M=M)

    return f_vec
