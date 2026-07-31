"""Monitor-point integrated section loads (MON2 / MON3).

Replicates NASTRAN ``MONPNT1`` (aero-only) and ``MONPNT3`` (aero + inertia +
reaction, splined to structural grids) integrated loads from a SOL 144 trim
solution.  Forces/moments already exist on ``Sol144TrimResult`` at the box level
(``box_forces``) and the g-set grid level (``grid_loads``, ``inertial_loads``);
the monitor integration is a summation of those over the monitor's AECOMP
collection, transformed to the monitor reference point and ``cp`` frame and
scaled by the AEROS symmetry parity.
"""
from typing import Optional, Union

import numpy as np

from sbeam.assembly.coord_transform import get_transform
from sbeam.aero.spline import nchord_per_caero, build_id_to_k
from sbeam.results.results import MonitorLoad
from sbeam.types import FloatArray
from sbeam.model.aero import Monpnt1, Monpnt3, require_aeros
from sbeam.model.bulk_data import BulkData
from sbeam.aero.aero_model import AeroModel

# A monitor must sit on the xz symmetry plane (y≈0) for the SYMXZ parity
# reconstruction to integrate the mirror half about the correct reference point.
_SYM_PLANE_TOL = 1e-6


def _parity(bulk: BulkData) -> float:
    """Symmetry doubling factor from AEROS.SYMXZ.

    Single-sourced from the post-mirror ``require_aeros(bulk).symxz``: full-span builds
    (mirror.py zeros SYMXZ) give 1.0; a half-model fed directly (SYMXZ≠0) gives
    2.0 so the monitor reports the whole-airplane load.
    """
    if bulk.aeros is not None and require_aeros(bulk).symxz != 0:
        return 2.0
    return 1.0


def _apply_symmetry(load6_basic: FloatArray, par: float,
                    ref_basic: FloatArray, mon_name: str) -> FloatArray:
    """Reconstruct the whole-airplane [F, M] resultant for a half-span (SYMXZ) build.

    For an xz-plane-symmetric model under symmetric loading the mirror half doubles
    the symmetric components (Fx, Fz, My) and cancels the antisymmetric ones
    (Fy, Mx, Mz) — so simply scaling all six by ``par`` would wrongly double the
    antisymmetric load.  Valid only for a monitor reference on the symmetry plane
    (y≈0): an off-plane reference would integrate the mirror load about the wrong
    point, so that case is rejected (use a full-span model instead).
    """
    if par == 1.0:
        return load6_basic
    if abs(ref_basic[1]) > _SYM_PLANE_TOL:
        raise ValueError(
            f"Monitor {mon_name!r}: SYMXZ half-model parity reconstruction requires "
            f"the monitor reference on the symmetry plane (y≈0), got y={ref_basic[1]:g}. "
            f"Use a full-span model for off-centerline monitors."
        )
    out = np.zeros(6)
    out[0] = par * load6_basic[0]   # Fx — symmetric
    out[2] = par * load6_basic[2]   # Fz — symmetric
    out[4] = par * load6_basic[4]   # My — symmetric
    # Fy (1), Mx (3), Mz (5) are antisymmetric and cancel across the mirror.
    return out


def _monitor_frame(
    mon: Union[Monpnt1, Monpnt3], bulk: BulkData
) -> tuple[FloatArray, FloatArray]:
    """Return (ref_basic (3,), R (3x3)) for a monitor point.

    ``ref_basic`` is the reference point in basic CID 0; ``R`` rotates a basic
    vector into the cp frame via ``R.T @ v_basic`` (R: v_basic = R @ v_cp).
    """
    origin, R = get_transform(mon.cp, bulk.cord2rs)
    ref_basic = origin + R @ np.array([mon.x, mon.y, mon.z], dtype=float)
    return ref_basic, R


def _to_cp(load6_basic: FloatArray, R: FloatArray) -> FloatArray:
    """Rotate a (6,) [F, M] resultant from basic CID 0 into the cp frame."""
    out = np.empty(6)
    out[:3] = R.T @ load6_basic[:3]
    out[3:] = R.T @ load6_basic[3:]
    return out


def integrate_monpnt1(
    mon: Monpnt1, bulk: BulkData, aero: AeroModel, box_forces: FloatArray
) -> MonitorLoad:
    """Aero-only integrated load over the monitor's AELIST collection."""
    aecomp = bulk.aecomps[mon.comp]
    ref_basic, R = _monitor_frame(mon, bulk)

    # AELIST box IDs -> global box indices k
    nchord = nchord_per_caero(aero.boxes)
    id_to_k = build_id_to_k(aero.boxes, nchord)
    box_ids: list[int] = []
    for sid in aecomp.list_ids:
        box_ids.extend(bulk.aelists[sid].elements)

    F = np.zeros(3)
    M = np.zeros(3)
    for bid in box_ids:
        k = id_to_k[bid]
        f = box_forces[k]
        r = aero.boxes[k].force_point - ref_basic
        F += f
        M += np.cross(r, f)

    par = _parity(bulk)
    aero6 = _to_cp(_apply_symmetry(np.concatenate([F, M]), par, ref_basic, mon.name), R)
    return MonitorLoad(
        name=mon.name, label=mon.label, mtype="MONPNT1", axes=mon.axes,
        cid=mon.cp, ref=ref_basic, totals=aero6, aero=aero6,
        inertia=np.zeros(6), reaction=np.zeros(6),
        parity=par, whole_airplane=(par != 1.0), source_ids=list(aecomp.list_ids),
    )


def _grid_resultant(
    load_g: FloatArray, gids: list[int], bulk: BulkData,
    grid_index: dict[int, int], ref_basic: FloatArray,
) -> FloatArray:
    """Sum a g-set load over ``gids`` into a (6,) [F, M] resultant about ref (basic)."""
    F = np.zeros(3)
    M = np.zeros(3)
    for gid in gids:
        gi = grid_index[gid]
        f = load_g[6 * gi: 6 * gi + 3]
        m = load_g[6 * gi + 3: 6 * gi + 6]
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z]) - ref_basic
        F += f
        M += m + np.cross(r, f)
    return np.concatenate([F, M])


def integrate_monpnt3(
    mon: Monpnt3, bulk: BulkData, grid_loads: FloatArray,
    inertial_loads: Optional[FloatArray], grid_index: dict[int, int],
    reactions: dict[int, FloatArray],
) -> MonitorLoad:
    """Aero + inertia + reaction integrated load over the monitor's SET1 grids.

    Aero comes from ``grid_loads`` (splined, RBE3/RBAR pass-through), inertia
    from ``inertial_loads`` (zero for plain trim), reaction from the recovered
    SPC/SUPORT reaction dict (restricted to constrained grids in the collection
    — zero elsewhere).
    """
    aecomp = bulk.aecomps[mon.comp]
    ref_basic, R = _monitor_frame(mon, bulk)

    gids = []
    for sid in aecomp.list_ids:
        gids.extend(bulk.set1s[sid].grids)

    aero_b = _grid_resultant(grid_loads, gids, bulk, grid_index, ref_basic)
    inert_b = (_grid_resultant(inertial_loads, gids, bulk, grid_index, ref_basic)
               if inertial_loads is not None else np.zeros(6))

    # Reaction: only grids in the collection that carry a recovered reaction.
    react_g = np.zeros_like(grid_loads)
    if reactions:
        for gid, r6 in reactions.items():
            if gid in grid_index:
                gi = grid_index[gid]
                react_g[6 * gi: 6 * gi + 6] = r6
    react_b = _grid_resultant(react_g, gids, bulk, grid_index, ref_basic)

    par = _parity(bulk)
    aero6 = _to_cp(_apply_symmetry(aero_b, par, ref_basic, mon.name), R)
    inert6 = _to_cp(_apply_symmetry(inert_b, par, ref_basic, mon.name), R)
    react6 = _to_cp(_apply_symmetry(react_b, par, ref_basic, mon.name), R)
    totals = aero6 + inert6 + react6
    return MonitorLoad(
        name=mon.name, label=mon.label, mtype="MONPNT3", axes=mon.axes,
        cid=mon.cp, ref=ref_basic, totals=totals,
        aero=aero6, inertia=inert6, reaction=react6,
        parity=par, whole_airplane=(par != 1.0), source_ids=list(aecomp.list_ids),
    )


def compute_monitor_loads(
    bulk: BulkData, aero: AeroModel, box_forces: FloatArray,
    grid_loads: FloatArray, inertial_loads: Optional[FloatArray],
    grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
) -> dict[str, MonitorLoad]:
    """Build {name: MonitorLoad} for all MONPNT1/MONPNT3 cards in the model."""
    out: dict[str, MonitorLoad] = {}
    for name, mon in bulk.monpnt1s.items():
        out[name] = integrate_monpnt1(mon, bulk, aero, box_forces)
    for name, mon in bulk.monpnt3s.items():
        out[name] = integrate_monpnt3(mon, bulk, grid_loads, inertial_loads,
                                      grid_index, reactions or {})
    return out
