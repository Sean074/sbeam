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

Two-phase evaluation (Step 68)
------------------------------
A transient maneuver evaluates the same cuts once per output sample, so the
state-independent half of the work — resolving the AECOMP collection, the CID
transform, the member station coordinates, the per-station masks and the on-plane
warnings — is hoisted into :func:`prepare_section_cuts`, which returns a frozen
:class:`SectionCutPlan`.  :func:`evaluate_section_cut` is then masked sums only.
That is what keeps the per-sample cost proportional to stations rather than to a
full geometry rebuild, and what makes the on-plane ``UserWarning`` fire once per
run instead of once per sample.  :func:`compute_section_cuts` (the static SOL 144
entry point) is prepare + evaluate and is unchanged for its callers.
"""
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sbeam.assembly.coord_transform import get_transform
from sbeam.aero.aero_model import AeroModel
from sbeam.model.aero import Monsect
from sbeam.model.bulk_data import BulkData
from sbeam.results.results import SectionCutResult, SectionCutStation
from sbeam.types import BoolArray, FloatArray, IntArray

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


def _gather_grid_load(load_g: Optional[FloatArray],
                      rows: IntArray) -> tuple[FloatArray, FloatArray]:
    """Split a g-set load vector into per-member ``(forces (n,3), moments (n,3))``.

    ``rows`` is the precomputed ``6·grid_index[gid]`` base row of every member
    (see :class:`SectionCutPlan`), so this is pure gather with no dict lookups.
    """
    n = rows.size
    if load_g is None:
        return np.zeros((n, 3)), np.zeros((n, 3))
    f = np.stack([load_g[rows + 0], load_g[rows + 1], load_g[rows + 2]], axis=1)
    m = np.stack([load_g[rows + 3], load_g[rows + 4], load_g[rows + 5]], axis=1)
    return f, m


def _resultant(f: FloatArray, m: FloatArray, pos: FloatArray,
               ref: FloatArray, mask: BoolArray) -> FloatArray:
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


@dataclass(frozen=True)
class SectionCutPlan:
    """Everything about one MONSECT cut that does not depend on the load state.

    Built once per run by :func:`prepare_section_cuts` and consumed by
    :func:`evaluate_section_cut` at every sample of a transient maneuver.  The
    on-plane warnings are emitted while building this, so they are a property of
    the model rather than of the number of output samples.
    """
    cut: Monsect
    listtype: str                    # 'SET1' | 'AELIST'
    member_ids: list[int]            # grid IDs (SET1) or global box indices k (AELIST)
    rows: IntArray                   # (n,) 6·grid_index[gid] base rows; empty for AELIST
    pos: FloatArray                  # (n, 3) member positions, basic
    R: FloatArray                    # (3, 3) cid rotation, v_basic = R @ v_cid
    masks: list[BoolArray]           # per station, (n,) bool — members on the cut side
    refs: FloatArray                 # (n_station, 3) reference points, basic
    comp_map: tuple[int, ...]
    half_model: bool
    normal: Optional[FloatArray]     # (3,) cut normal in basic, when overridden
    n_dofs: int                      # g-set size, for scattering the reaction dict


def prepare_section_cut(
    cut: Monsect, bulk: BulkData, aero: Optional[AeroModel],
    grid_index: dict[int, int],
) -> SectionCutPlan:
    """Resolve one cut's geometry, masks and warnings — everything state-free."""
    P, R, a_hat, n_hat, denom = _cut_geometry(cut, bulk)
    listtype, member_ids, pos = _member_geometry(cut, bulk, aero, grid_index)
    tol = _auto_tol(cut)

    # Station coordinate of every member, measured once for the whole sweep.
    s_member = (pos - P) @ n_hat if len(member_ids) else np.zeros(0)

    masks: list[BoolArray] = []
    refs: list[FloatArray] = []
    for s in cut.stations:
        _warn_on_plane(cut, s, member_ids, s_member, tol,
                       "grid" if listtype == "SET1" else "box")
        if cut.side == "POS":
            masks.append(s_member > s + tol)
        else:
            masks.append(s_member < s - tol)
        # Reference point: the cut plane's intercept with the reference line
        # origin + t·â — the elastic axis when CID is the surface's spline CID.
        refs.append(P + (s / denom) * a_hat)

    rows = (np.array([6 * grid_index[g] for g in member_ids], dtype=int)
            if listtype == "SET1" else np.zeros(0, dtype=int))
    return SectionCutPlan(
        cut=cut, listtype=listtype, member_ids=member_ids, rows=rows, pos=pos,
        R=R, masks=masks,
        refs=np.array(refs, dtype=float).reshape(-1, 3),
        comp_map=component_map(cut.axis),
        half_model=bool(bulk.aeros is not None and bulk.aeros.symxz != 0),
        normal=(n_hat.copy() if cut.normal is not None else None),
        n_dofs=(6 * (max(grid_index.values()) + 1) if grid_index else 0),
    )


def prepare_section_cuts(
    bulk: BulkData, aero: Optional[AeroModel], grid_index: dict[int, int],
) -> dict[str, SectionCutPlan]:
    """Build ``{name: SectionCutPlan}`` for every MONSECT card in the model."""
    return {name: prepare_section_cut(cut, bulk, aero, grid_index)
            for name, cut in bulk.monsects.items()}


def _scatter_reactions(reactions: Optional[dict[int, FloatArray]],
                       grid_index: dict[int, int],
                       n_dofs: int) -> Optional[FloatArray]:
    """Expand a ``{gid: (6,)}`` reaction dict into a g-set vector."""
    if not reactions:
        return None
    react_g = np.zeros(n_dofs)
    for gid, r6 in reactions.items():
        if gid in grid_index:
            react_g[6 * grid_index[gid]: 6 * grid_index[gid] + 6] = r6
    return react_g


def evaluate_section_cut(
    plan: SectionCutPlan,
    box_forces: Optional[FloatArray], grid_loads: Optional[FloatArray],
    inertial_loads: Optional[FloatArray], grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
    elastic_inertial_loads: Optional[FloatArray] = None,
    damping_loads: Optional[FloatArray] = None,
) -> SectionCutResult:
    """Sum one prepared cut against a load state — masked sums, no geometry.

    ``elastic_inertial_loads``/``damping_loads`` are the Step 68 transient
    contributions (``M·ü_e`` and the modal-damping force).  They are zero on a
    static trim and are reported as their own columns rather than folded into
    ``inertia``, so a reader can see how much of a transient cut is elastic
    response — and so the static tables keep the exact three-column split the
    Monitor Phase 2 outputs were verified against.
    """
    cut = plan.cut
    pos, R, cmap = plan.pos, plan.R, plan.comp_map

    if plan.listtype == "SET1":
        f_aero, m_aero = _gather_grid_load(grid_loads, plan.rows)
        f_in, m_in = _gather_grid_load(inertial_loads, plan.rows)
        f_el, m_el = _gather_grid_load(elastic_inertial_loads, plan.rows)
        f_da, m_da = _gather_grid_load(damping_loads, plan.rows)
        react_g = _scatter_reactions(reactions, grid_index, plan.n_dofs)
        f_re, m_re = _gather_grid_load(react_g, plan.rows)
    else:
        forces = (np.asarray(box_forces)[plan.member_ids] if plan.member_ids
                  else np.zeros((0, 3)))
        f_aero, m_aero = forces, np.zeros_like(forces)
        z = np.zeros_like(forces)
        f_in = m_in = f_re = m_re = f_el = m_el = f_da = m_da = z

    has_extra = elastic_inertial_loads is not None or damping_loads is not None

    def to_cid(v6: FloatArray) -> FloatArray:
        """Rotate basic -> cid.  No parity factor (see the module docstring)."""
        return np.concatenate([R.T @ v6[:3], R.T @ v6[3:]])

    stations: list[SectionCutStation] = []
    prev_lab: Optional[FloatArray] = None
    prev_s: Optional[float] = None
    for i, s in enumerate(cut.stations):
        mask, ref = plan.masks[i], plan.refs[i]

        aero6 = to_cid(_resultant(f_aero, m_aero, pos, ref, mask))
        inert6 = to_cid(_resultant(f_in, m_in, pos, ref, mask))
        react6 = to_cid(_resultant(f_re, m_re, pos, ref, mask))
        totals = aero6 + inert6 + react6
        elastic6 = damp6 = None
        if has_extra:
            elastic6 = to_cid(_resultant(f_el, m_el, pos, ref, mask))
            damp6 = to_cid(_resultant(f_da, m_da, pos, ref, mask))
            totals = totals + elastic6 + damp6

        lab = labelled(totals, cmap)
        d_ds = None
        if prev_lab is not None and prev_s is not None and s != prev_s:
            d_ds = (lab - prev_lab) / (s - prev_s)
        prev_lab, prev_s = lab, s

        stations.append(SectionCutStation(
            station=float(s), ref=ref, totals=totals, aero=aero6,
            inertia=inert6, reaction=react6, n_members=int(mask.sum()),
            d_ds=d_ds, elastic_inertia=elastic6, damping=damp6,
        ))

    return SectionCutResult(
        name=cut.name, label=cut.label, comp=cut.comp, listtype=plan.listtype,
        cid=cut.cid, axis=cut.axis, side=cut.side, stations=stations,
        comp_map=cmap, half_model=plan.half_model,
        normal=(plan.normal.copy() if plan.normal is not None else None),
    )


def compute_section_cut(
    cut: Monsect, bulk: BulkData, aero: Optional[AeroModel],
    box_forces: Optional[FloatArray], grid_loads: Optional[FloatArray],
    inertial_loads: Optional[FloatArray], grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
) -> SectionCutResult:
    """Build the per-station running-load table for one MONSECT card."""
    plan = prepare_section_cut(cut, bulk, aero, grid_index)
    return evaluate_section_cut(plan, box_forces, grid_loads, inertial_loads,
                                grid_index, reactions)


def compute_section_cuts(
    bulk: BulkData, aero: Optional[AeroModel], box_forces: Optional[FloatArray],
    grid_loads: Optional[FloatArray], inertial_loads: Optional[FloatArray],
    grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
) -> dict[str, SectionCutResult]:
    """Build ``{name: SectionCutResult}`` for every MONSECT card in the model."""
    return {
        name: evaluate_section_cut(plan, box_forces, grid_loads, inertial_loads,
                                   grid_index, reactions)
        for name, plan in prepare_section_cuts(bulk, aero, grid_index).items()
    }
