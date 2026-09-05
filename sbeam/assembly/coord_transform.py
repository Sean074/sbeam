"""Coordinate system transformation utilities for CORD2R systems."""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.types import FloatArray


def get_transform(
    cid: int,
    cord2rs: dict[int, Cord2r],
    _visited: frozenset[int] = frozenset(),
) -> tuple[FloatArray, FloatArray]:
    """Return (origin, R) for CID expressed in global CID 0.

    R (3x3): v_global = R @ v_local
    origin (3-vector): p_global = origin + R @ p_local
    """
    if cid == 0:
        return np.zeros(3), np.eye(3)

    if cid in _visited:
        raise ValueError(f"Circular reference in coordinate system chain at CID {cid}")
    if cid not in cord2rs:
        raise ValueError(f"Coordinate system CID {cid} not defined")

    cs = cord2rs[cid]
    origin_rid, R_rid = get_transform(cs.rid, cord2rs, _visited | {cid})

    a = np.array(cs.a, dtype=float)
    b = np.array(cs.b, dtype=float)
    c = np.array(cs.c, dtype=float)

    # Transform defining points from RID frame to global
    a_g = origin_rid + R_rid @ a
    b_g = origin_rid + R_rid @ b
    c_g = origin_rid + R_rid @ c

    # Local Z-axis
    k = b_g - a_g
    k_norm = np.linalg.norm(k)
    if k_norm < 1e-12:
        raise ValueError(f"CORD2R {cid}: points A and B are coincident")
    k_hat: FloatArray = k / k_norm

    # Local X-axis (Gram-Schmidt: project C−A onto plane normal to k)
    v = c_g - a_g
    v = v - np.dot(v, k_hat) * k_hat
    v_norm = np.linalg.norm(v)
    if v_norm < 1e-12:
        raise ValueError(f"CORD2R {cid}: points A, B, C are collinear")
    i_hat: FloatArray = v / v_norm

    # Local Y-axis (right-handed)
    j_hat: FloatArray = np.cross(k_hat, i_hat)

    # R columns are local basis vectors expressed in global frame
    R = np.column_stack([i_hat, j_hat, k_hat])
    return a_g, R


def build_transform(cid: int, cord2rs: dict[int, Cord2r]) -> FloatArray:
    """Return 3×3 rotation matrix R for CID. v_global = R @ v_local."""
    _, R = get_transform(cid, cord2rs)
    return R


def to_global(v: FloatArray, cid: int, cord2rs: dict[int, Cord2r]) -> FloatArray:
    """Rotate 3-vector from coordinate system `cid` into global CID 0."""
    if cid == 0:
        return v
    return build_transform(cid, cord2rs) @ v


def to_local(v: FloatArray, cid: int, cord2rs: dict[int, Cord2r]) -> FloatArray:
    """Rotate 3-vector from global CID 0 into coordinate system `cid`."""
    if cid == 0:
        return v
    return build_transform(cid, cord2rs).T @ v


def resolve_grid_positions(bulk: BulkData) -> None:
    """Transform all Grid positions from their CP system to global CID 0 in-place.

    Called once after parsing is complete. After this call every Grid.x/y/z
    is in CID 0. Grid.cp is zeroed; Grid.cd is preserved for output use.
    """
    for gid, grid in bulk.grids.items():
        if grid.cp == 0:
            continue
        if grid.cp not in bulk.cord2rs:
            raise ValueError(
                f"GRID {gid}: CP={grid.cp} references undefined coordinate system"
            )
        origin, R = get_transform(grid.cp, bulk.cord2rs)
        p_local = np.array([grid.x, grid.y, grid.z])
        p_global = origin + R @ p_local
        grid.x = float(p_global[0])
        grid.y = float(p_global[1])
        grid.z = float(p_global[2])
        grid.cp = 0
