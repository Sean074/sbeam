"""MONSECT section-cut running loads (Monitor Points Phase 2).

A section cut is free-body equilibrium: the load carried across a plane is the
resultant of everything on one side of it.  That is exactly the MONPNT1/MONPNT3
integrand of :mod:`sbeam.results.monitor_points` with (a) the collection filtered
by a plane test and (b) the moment reference moved onto the cut plane — so this
module is a station sweep around the Phase 1 sum, not new physics.  It consumes
the arrays ``run_sol144`` has already built (``box_forces``, ``grid_loads``,
``inertial_loads`` and the recovered reactions); nothing is re-solved.

Two conventions carry the weight and are deliberate (see
``docs/30_future/designs/monsect_section_cuts.md`` §4.6):

* **On-plane members count as inboard** — the test is strictly ``s > station``.
  A grid load is a point load, so a cut *at* a node must exclude it for the
  outboard free body's resultant to equal the beam internal force at that node.
* **No symmetry parity, ever.**  ``monitor_points._apply_symmetry`` doubles the
  symmetric components of a half model to report the whole airplane; a wing
  section cut is already the physical per-side load, its reference is
  deliberately off-centreline, and the antisymmetric cancellation is meaningless
  there.  Half-model runs are annotated, never scaled.
"""
import warnings
from typing import Optional

import numpy as np

from sbeam.assembly.coord_transform import get_transform
from sbeam.aero.aero_model import AeroModel
from sbeam.model.aero import Monsect
from sbeam.model.bulk_data import BulkData
from sbeam.results.results import SectionCutResult, SectionCutStation
from sbeam.types import FloatArray

# Floor on the auto on-plane tolerance, for a single-station cut (no span to
# scale from) or a degenerate station list.
_MIN_TOL = 1e-9


def component_map(axis: int) -> tuple[int, ...]:
    """Indices into a cid-frame ``[Fx,Fy,Fz,Mx,My,Mz]`` for the labelled components.

    Only two of the six components need a *role* name: the force along the
    station axis is the axial load ``N``, and the moment about it is the torque
    ``Mt``.  The other four keep the name of the CID axis they act along or
    about, so nothing is silently renamed — with the default ``AXIS=2`` (a
    spanwise wing cut) the table is ``N(Fy), Vx, Vz, Mt(My), Mx, Mz``, where
    ``Vz`` is the vertical shear and ``Mx`` the bending moment a stress group
    expects, not a relabelled neighbour.
    """
    i0 = axis - 1
    others = [i for i in (0, 1, 2) if i != i0]
    return (i0, others[0], others[1], 3 + i0, 3 + others[0], 3 + others[1])


def component_names(axis: int) -> tuple[str, ...]:
    """Labels matching :func:`component_map`, e.g. ``('N','Vx','Vz','Mt','Mx','Mz')``."""
    others = [i for i in (0, 1, 2) if i != axis - 1]
    xyz = "xyz"
    return ("N", f"V{xyz[others[0]]}", f"V{xyz[others[1]]}",
            "Mt", f"M{xyz[others[0]]}", f"M{xyz[others[1]]}")


def labelled(v6: FloatArray, comp_map: tuple[int, ...]) -> FloatArray:
    """Reorder a raw cid-frame 6-vector into the labelled component order."""
    return np.array([v6[i] for i in comp_map])


def component_legend(axis: int) -> str:
    """Human-readable mapping, e.g. ``N=Fy  Vx=Fx  Vz=Fz  Mt=My  Mx=Mx  Mz=Mz``."""
    raw = ["Fx", "Fy", "Fz", "Mx", "My", "Mz"]
    return "  ".join(f"{n}={raw[i]}"
                     for n, i in zip(component_names(axis), component_map(axis)))


def _cut_geometry(cut: Monsect, bulk: BulkData) -> tuple[FloatArray, FloatArray,
                                                          FloatArray, FloatArray, float]:
    """Return ``(P, R, a_hat, n_hat, denom)`` for a cut, all in basic CID 0.

    ``P``/``R`` are the CID origin and rotation (``v_basic = R @ v_cid``), ``a_hat``
    the station axis, ``n_hat`` the cut-plane normal (``a_hat`` unless overridden),
    and ``denom = a_hat · n_hat`` the factor placing the reference point on the
    plane.  The parser has already rejected ``|denom| < 0.1``.
    """
    P, R = get_transform(cut.cid, bulk.cord2rs)
    a_hat = R[:, cut.axis - 1]
    if cut.normal is None:
        n_hat = a_hat
    else:
        n_cid = np.array(cut.normal, dtype=float)
        n_hat = R @ (n_cid / np.linalg.norm(n_cid))
    return P, R, a_hat, n_hat, float(a_hat @ n_hat)


def _auto_tol(cut: Monsect) -> float:
    if cut.tol is not None:
        return float(cut.tol)
    span = cut.stations[-1] - cut.stations[0]
    return max(_MIN_TOL, 1e-6 * abs(span))


def _member_geometry(
    cut: Monsect, bulk: BulkData, aero: Optional[AeroModel],
    grid_index: dict[int, int],
) -> tuple[str, list[int], FloatArray]:
    """Resolve the AECOMP collection once: ``(listtype, member_ids, positions)``.

    For a ``SET1`` component the members are grid IDs and the positions their
    basic coordinates; for an ``AELIST`` component they are global box indices
    ``k`` and the positions the box force points — the same points the MON1
    integration applies the box force at.  Duplicates across several lists are
    collapsed, so a grid named twice is not counted twice.
    """
    aecomp = bulk.aecomps[cut.comp]
    if aecomp.listtype == "SET1":
        gids: list[int] = []
        seen: set[int] = set()
        for sid in aecomp.list_ids:
            for gid in bulk.set1s[sid].grids:
                if gid in seen:
                    continue
                if gid not in grid_index:
                    raise ValueError(
                        f"MONSECT {cut.name}: SET1 grid {gid} (AECOMP {cut.comp}) "
                        "is not a grid in the model"
                    )
                seen.add(gid)
                gids.append(gid)
        pos = np.array([[bulk.grids[g].x, bulk.grids[g].y, bulk.grids[g].z]
                        for g in gids], dtype=float).reshape(-1, 3)
        return "SET1", gids, pos

    if aero is None:
        raise ValueError(
            f"MONSECT {cut.name}: an AELIST-type AECOMP needs an aero model"
        )
    id_to_k = aero.require_box_id_to_k()
    ks: list[int] = []
    seen_k: set[int] = set()
    for sid in aecomp.list_ids:
        for bid in bulk.aelists[sid].elements:
            if bid not in id_to_k:
                raise ValueError(
                    f"MONSECT {cut.name}: AELIST box ID {bid} is not a meshed aero "
                    "box.  Check the AELIST box range against the CAERO1 it belongs "
                    "to (box IDs run EID .. EID + NSPAN*NCHORD - 1)."
                )
            k = id_to_k[bid]
            if k not in seen_k:
                seen_k.add(k)
                ks.append(k)
    pos = np.array([aero.boxes[k].force_point for k in ks], dtype=float).reshape(-1, 3)
    return "AELIST", ks, pos


def _gather_grid_load(load_g: Optional[FloatArray], gids: list[int],
                      grid_index: dict[int, int]) -> tuple[FloatArray, FloatArray]:
    """Split a g-set load vector into per-member ``(forces (n,3), moments (n,3))``."""
    n = len(gids)
    if load_g is None:
        return np.zeros((n, 3)), np.zeros((n, 3))
    rows = np.array([6 * grid_index[g] for g in gids], dtype=int)
    f = np.stack([load_g[rows + 0], load_g[rows + 1], load_g[rows + 2]], axis=1)
    m = np.stack([load_g[rows + 3], load_g[rows + 4], load_g[rows + 5]], axis=1)
    return f, m


def _resultant(f: FloatArray, m: FloatArray, pos: FloatArray,
               ref: FloatArray, mask: FloatArray) -> FloatArray:
    """(6,) ``[F, M]`` resultant about ``ref`` (basic) over the masked members."""
    if not mask.any():
        return np.zeros(6)
    fm = f[mask]
    F = fm.sum(axis=0)
    M = np.cross(pos[mask] - ref, fm).sum(axis=0) + m[mask].sum(axis=0)
    return np.concatenate([F, M])


def _warn_on_plane(cut: Monsect, station: float, member_ids: list[int],
                   s_member: FloatArray, tol: float, kind: str) -> None:
    """Warn when a member sits within ``tol`` of a cut — where the table steps.

    A station coinciding with a grid changes the answer by that grid's entire
    load, and the inboard convention (§4.6) is not what every user assumes, so
    the ambiguity is reported rather than resolved silently.
    """
    on_plane = np.nonzero(np.abs(s_member - station) <= tol)[0]
    if on_plane.size == 0:
        return
    ids = [member_ids[i] for i in on_plane]
    warnings.warn(
        f"MONSECT {cut.name}: station {station:g} lies within TOL={tol:g} of "
        f"{len(ids)} {kind}(s) {ids[:10]}{' ...' if len(ids) > 10 else ''} — "
        f"they are counted on the INBOARD side (excluded from the cut load).  "
        f"Move the station clear of them if a different split was intended.",
        UserWarning,
        stacklevel=3,
    )


def compute_section_cut(
    cut: Monsect, bulk: BulkData, aero: Optional[AeroModel],
    box_forces: Optional[FloatArray], grid_loads: Optional[FloatArray],
    inertial_loads: Optional[FloatArray], grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
) -> SectionCutResult:
    """Build the per-station running-load table for one MONSECT card."""
    P, R, a_hat, n_hat, denom = _cut_geometry(cut, bulk)
    listtype, member_ids, pos = _member_geometry(cut, bulk, aero, grid_index)
    tol = _auto_tol(cut)
    cmap = component_map(cut.axis)

    # Station coordinate of every member, measured once for the whole sweep.
    s_member = (pos - P) @ n_hat if len(member_ids) else np.zeros(0)

    if listtype == "SET1":
        gids = member_ids
        f_aero, m_aero = _gather_grid_load(grid_loads, gids, grid_index)
        f_in, m_in = _gather_grid_load(inertial_loads, gids, grid_index)
        react_g: Optional[FloatArray] = None
        if reactions:
            n_dofs = 6 * (max(grid_index.values()) + 1) if grid_index else 0
            react_g = np.zeros(n_dofs)
            for gid, r6 in reactions.items():
                if gid in grid_index:
                    react_g[6 * grid_index[gid]: 6 * grid_index[gid] + 6] = r6
        f_re, m_re = _gather_grid_load(react_g, gids, grid_index)
    else:
        forces = (np.asarray(box_forces)[member_ids] if len(member_ids)
                  else np.zeros((0, 3)))
        f_aero, m_aero = forces, np.zeros_like(forces)
        f_in = m_in = f_re = m_re = np.zeros_like(forces)

    stations: list[SectionCutStation] = []
    prev_lab: Optional[FloatArray] = None
    prev_s: Optional[float] = None
    for s in cut.stations:
        _warn_on_plane(cut, s, member_ids, s_member, tol,
                       "grid" if listtype == "SET1" else "box")
        if cut.side == "POS":
            mask = s_member > s + tol
        else:
            mask = s_member < s - tol

        # Reference point: the cut plane's intercept with the reference line
        # origin + t·â — the elastic axis when CID is the surface's spline CID.
        ref = P + (s / denom) * a_hat

        aero6_b = _resultant(f_aero, m_aero, pos, ref, mask)
        inert6_b = _resultant(f_in, m_in, pos, ref, mask)
        react6_b = _resultant(f_re, m_re, pos, ref, mask)
        # Rotate basic -> cid.  No parity factor is applied (see module docstring).
        aero6 = np.concatenate([R.T @ aero6_b[:3], R.T @ aero6_b[3:]])
        inert6 = np.concatenate([R.T @ inert6_b[:3], R.T @ inert6_b[3:]])
        react6 = np.concatenate([R.T @ react6_b[:3], R.T @ react6_b[3:]])
        totals = aero6 + inert6 + react6

        lab = labelled(totals, cmap)
        d_ds = None
        if prev_lab is not None and prev_s is not None and s != prev_s:
            d_ds = (lab - prev_lab) / (s - prev_s)
        prev_lab, prev_s = lab, s

        stations.append(SectionCutStation(
            station=float(s), ref=ref, totals=totals, aero=aero6,
            inertia=inert6, reaction=react6, n_members=int(mask.sum()),
            d_ds=d_ds,
        ))

    half = bool(bulk.aeros is not None and bulk.aeros.symxz != 0)
    return SectionCutResult(
        name=cut.name, label=cut.label, comp=cut.comp, listtype=listtype,
        cid=cut.cid, axis=cut.axis, side=cut.side, stations=stations,
        comp_map=cmap, half_model=half,
        normal=(n_hat.copy() if cut.normal is not None else None),
    )


def compute_section_cuts(
    bulk: BulkData, aero: Optional[AeroModel], box_forces: Optional[FloatArray],
    grid_loads: Optional[FloatArray], inertial_loads: Optional[FloatArray],
    grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
) -> dict[str, SectionCutResult]:
    """Build ``{name: SectionCutResult}`` for every MONSECT card in the model."""
    return {
        name: compute_section_cut(cut, bulk, aero, box_forces, grid_loads,
                                  inertial_loads, grid_index, reactions)
        for name, cut in bulk.monsects.items()
    }
