"""Load vector assembly for FEA."""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.coord_transform import to_global


def build_grid_index(bulk: BulkData) -> dict:
    """Return {gid: i} where i is the 0-based index in sorted GID order."""
    return {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}


def _apply_forces_to_vector(
    f_vec: np.ndarray, forces: list, grid_index: dict, cord2rs: dict, scale: float = 1.0
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
    f_vec: np.ndarray, moments: list, grid_index: dict, cord2rs: dict, scale: float = 1.0
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


def assemble_load_vector(bulk: BulkData, load_sid: int) -> np.ndarray:
    """Assemble global load vector for the given load SID.

    Handles:
      - Direct FORCE / MOMENT SIDs
      - LOAD card (linear combination of other FORCE/MOMENT SIDs)
    """
    grid_index = build_grid_index(bulk)
    n = 6 * len(grid_index)
    f_vec = np.zeros(n)
    cord2rs = bulk.cord2rs

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
    else:
        # Direct FORCE or MOMENT SID
        if load_sid in bulk.forces:
            _apply_forces_to_vector(f_vec, bulk.forces[load_sid], grid_index, cord2rs)
        if load_sid in bulk.moments:
            _apply_moments_to_vector(f_vec, bulk.moments[load_sid], grid_index, cord2rs)

    return f_vec
