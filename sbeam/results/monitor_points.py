"""Monitor-point integrated section loads (MON2 / MON3).

Replicates NASTRAN ``MONPNT1`` (aero-only) and ``MONPNT3`` (aero + inertia +
reaction, splined to structural grids) integrated loads from a SOL 144 trim
solution.  Forces/moments already exist on ``Sol144TrimResult`` at the box level
(``box_forces``) and the g-set grid level (``grid_loads``, ``inertial_loads``);
the monitor integration is a summation of those over the monitor's AECOMP
collection, transformed to the monitor reference point and ``cp`` frame and
scaled by the AEROS symmetry parity.

Split into a state-free :class:`MonitorPlan` (geometry, index rows, frame,
parity — built once per run by :func:`prepare_monitor_points`) and a per-load
:func:`evaluate_monitor_point`, so a transient (MLOADS) maneuver can take the
same monitors at every output sample without re-resolving the collection
(#2, the pattern Step 68 set for ``MONSECT``).  On a transient sample the
evaluation additionally carries the elastic d'Alembert and damping loads as
their own columns, exactly as the section cuts do.
"""
import warnings
from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np

from sbeam.assembly.coord_transform import get_transform
from sbeam.results.results import MonitorLoad
from sbeam.types import FloatArray, IntArray
from sbeam.model.aero import Monpnt1, Monpnt3, require_aeros
from sbeam.model.bulk_data import BulkData
from sbeam.model.mass_overlay import effective_conm2s
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


def monitor_frame(
    mon: Union[Monpnt1, Monpnt3], bulk: BulkData
) -> tuple[FloatArray, FloatArray]:
    """Return (ref_basic (3,), R (3x3)) for a monitor point.

    ``ref_basic`` is the reference point in basic CID 0; ``R`` rotates a basic
    vector into the cp frame via ``R.T @ v_basic`` (R: v_basic = R @ v_cp).
    """
    origin, R = get_transform(mon.cp, bulk.cord2rs)
    ref_basic = origin + R @ np.array([mon.x, mon.y, mon.z], dtype=float)
    return ref_basic, R


def to_cp(load6_basic: FloatArray, R: FloatArray) -> FloatArray:
    """Rotate a (6,) [F, M] resultant from basic CID 0 into the cp frame."""
    out = np.empty(6)
    out[:3] = R.T @ load6_basic[:3]
    out[3:] = R.T @ load6_basic[3:]
    return out


@dataclass
class MonitorPlan:
    """Everything about one monitor that does not depend on the load state.

    Built once per run by :func:`prepare_monitor_points` and consumed by
    :func:`evaluate_monitor_point` at every sample of a transient maneuver (or
    once, on a static trim).  Resolving the AELIST/SET1 collection here rather
    than per evaluation keeps a 2000-sample run from re-walking the same box
    and grid lists 2000 times.
    """
    name: str
    mtype: str                       # 'MONPNT1' | 'MONPNT3'
    label: str
    axes: int
    cid: int
    ref_basic: FloatArray            # (3,) reference point, basic
    R: FloatArray                    # (3, 3) cp rotation, v_basic = R @ v_cp
    par: float                       # AEROS symmetry parity (1.0 or 2.0)
    source_ids: list[int]            # AELIST or SET1 SIDs
    pos: FloatArray                  # (n, 3) member positions, basic
    rows: IntArray                   # (n,) 6·grid_index[gid] base rows (SET1); empty for AELIST
    box_ks: IntArray                 # (n,) global box indices (AELIST); empty for SET1
    gids: list[int] = field(default_factory=list)   # SET1 grid IDs (MONPNT3)
    n_dofs: int = 0                  # g-set size, for scattering the reaction dict


def prepare_monitor_point(
    mon: Union[Monpnt1, Monpnt3], bulk: BulkData, aero: Optional[AeroModel],
    grid_index: dict[int, int],
) -> MonitorPlan:
    """Resolve one monitor's collection, reference point, frame and parity."""
    aecomp = bulk.aecomps[mon.comp]
    ref_basic, R = monitor_frame(mon, bulk)
    par = _parity(bulk)
    if isinstance(mon, Monpnt1):
        if aero is None:
            raise ValueError(f"MONPNT1 {mon.name}: an AeroModel is required")
        # AELIST box IDs -> global box indices k (shared collision-checked map, F1)
        id_to_k = aero.require_box_id_to_k()
        box_ids: list[int] = []
        for sid in aecomp.list_ids:
            box_ids.extend(bulk.aelists[sid].elements)
        ks: list[int] = []
        for bid in box_ids:
            if bid not in id_to_k:
                raise ValueError(
                    f"MONPNT1 {mon.name}: AELIST box ID {bid} is not a meshed aero "
                    "box.  Check the AELIST box range against the CAERO1 it belongs "
                    "to (box IDs run EID .. EID + NSPAN*NCHORD - 1)."
                )
            ks.append(id_to_k[bid])
        pos = (np.array([aero.boxes[k].force_point for k in ks], dtype=float)
               .reshape(-1, 3))
        return MonitorPlan(
            name=mon.name, mtype="MONPNT1", label=mon.label, axes=mon.axes,
            cid=mon.cp, ref_basic=ref_basic, R=R, par=par,
            source_ids=list(aecomp.list_ids), pos=pos,
            rows=np.zeros(0, dtype=int), box_ks=np.array(ks, dtype=int),
        )

    gids: list[int] = []
    for sid in aecomp.list_ids:
        gids.extend(bulk.set1s[sid].grids)
    pos = np.array([[bulk.grids[g].x, bulk.grids[g].y, bulk.grids[g].z]
                    for g in gids], dtype=float).reshape(-1, 3)
    return MonitorPlan(
        name=mon.name, mtype="MONPNT3", label=mon.label, axes=mon.axes,
        cid=mon.cp, ref_basic=ref_basic, R=R, par=par,
        source_ids=list(aecomp.list_ids), pos=pos,
        rows=np.array([6 * grid_index[g] for g in gids], dtype=int),
        box_ks=np.zeros(0, dtype=int), gids=gids,
        n_dofs=(6 * (max(grid_index.values()) + 1) if grid_index else 0),
    )


def prepare_monitor_points(
    bulk: BulkData, aero: Optional[AeroModel], grid_index: dict[int, int],
) -> dict[str, MonitorPlan]:
    """Build ``{name: MonitorPlan}`` for every MONPNT1/MONPNT3 card in the model."""
    out: dict[str, MonitorPlan] = {}
    for name, mon1 in bulk.monpnt1s.items():
        out[name] = prepare_monitor_point(mon1, bulk, aero, grid_index)
    for name, mon3 in bulk.monpnt3s.items():
        out[name] = prepare_monitor_point(mon3, bulk, aero, grid_index)
    return out


def _gather(load_g: Optional[FloatArray], rows: IntArray) -> tuple[FloatArray, FloatArray]:
    """(n, 3) forces and moments of a g-set load at the plan's rows (zeros if None)."""
    if load_g is None or rows.size == 0:
        return np.zeros((rows.size, 3)), np.zeros((rows.size, 3))
    idx = rows[:, None] + np.arange(6)[None, :]
    blk = np.asarray(load_g)[idx]
    return blk[:, :3], blk[:, 3:]


def _resultant_about(f: FloatArray, m: FloatArray, pos: FloatArray,
                     ref: FloatArray) -> FloatArray:
    """(6,) [ΣF, Σ(m + r×f)] about ``ref`` — the same sum ``grid_resultant`` takes."""
    if f.shape[0] == 0:
        return np.zeros(6)
    F = f.sum(axis=0)
    M = m.sum(axis=0) + np.cross(pos - ref, f).sum(axis=0)
    return np.concatenate([F, M])


def evaluate_monitor_point(
    plan: MonitorPlan,
    box_forces: Optional[FloatArray], grid_loads: Optional[FloatArray],
    inertial_loads: Optional[FloatArray],
    reactions: Optional[dict[int, FloatArray]] = None,
    grid_index: Optional[dict[int, int]] = None,
    elastic_inertial_loads: Optional[FloatArray] = None,
    damping_loads: Optional[FloatArray] = None,
) -> MonitorLoad:
    """Sum one prepared monitor against a load state — no geometry, no lookups.

    ``elastic_inertial_loads``/``damping_loads`` are the transient contributions
    (``−M·ü_e`` and ``−M·w``, #2).  They are absent (None) on a static trim and
    reported as their own columns rather than folded into ``inertia`` — so the
    static outputs keep the exact three-way split they were verified against,
    and a reader of a transient monitor can see how much of it is elastic
    response.  A MONPNT1 is aero-only by definition and never carries them.
    """
    ref, R, par = plan.ref_basic, plan.R, plan.par

    def cp(v6: FloatArray) -> FloatArray:
        return to_cp(_apply_symmetry(v6, par, ref, plan.name), R)

    if plan.mtype == "MONPNT1":
        forces = (np.asarray(box_forces)[plan.box_ks] if plan.box_ks.size
                  else np.zeros((0, 3)))
        aero6 = cp(_resultant_about(forces, np.zeros_like(forces), plan.pos, ref))
        return MonitorLoad(
            name=plan.name, label=plan.label, mtype="MONPNT1", axes=plan.axes,
            cid=plan.cid, ref=ref, totals=aero6, aero=aero6,
            inertia=np.zeros(6), reaction=np.zeros(6),
            parity=par, whole_airplane=(par != 1.0),
            source_ids=list(plan.source_ids),
        )

    f_a, m_a = _gather(grid_loads, plan.rows)
    f_i, m_i = _gather(inertial_loads, plan.rows)
    # Reaction: only grids in the collection that carry a recovered reaction.
    react_g = None
    if reactions and grid_index is not None:
        react_g = np.zeros(plan.n_dofs)
        for gid, r6 in reactions.items():
            if gid in grid_index:
                gi = grid_index[gid]
                react_g[6 * gi: 6 * gi + 6] = r6
    f_r, m_r = _gather(react_g, plan.rows)

    aero6 = cp(_resultant_about(f_a, m_a, plan.pos, ref))
    inert6 = cp(_resultant_about(f_i, m_i, plan.pos, ref))
    react6 = cp(_resultant_about(f_r, m_r, plan.pos, ref))
    totals = aero6 + inert6 + react6

    elastic6 = damp6 = None
    if elastic_inertial_loads is not None or damping_loads is not None:
        f_e, m_e = _gather(elastic_inertial_loads, plan.rows)
        f_d, m_d = _gather(damping_loads, plan.rows)
        elastic6 = cp(_resultant_about(f_e, m_e, plan.pos, ref))
        damp6 = cp(_resultant_about(f_d, m_d, plan.pos, ref))
        totals = totals + elastic6 + damp6

    return MonitorLoad(
        name=plan.name, label=plan.label, mtype="MONPNT3", axes=plan.axes,
        cid=plan.cid, ref=ref, totals=totals,
        aero=aero6, inertia=inert6, reaction=react6,
        parity=par, whole_airplane=(par != 1.0),
        source_ids=list(plan.source_ids),
        elastic_inertia=elastic6, damping=damp6,
    )


def integrate_monpnt1(
    mon: Monpnt1, bulk: BulkData, aero: AeroModel, box_forces: FloatArray
) -> MonitorLoad:
    """Aero-only integrated load over the monitor's AELIST collection."""
    plan = prepare_monitor_point(mon, bulk, aero, {})
    return evaluate_monitor_point(plan, box_forces, None, None)


def grid_resultant(
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
    plan = prepare_monitor_point(mon, bulk, None, grid_index)
    return evaluate_monitor_point(plan, None, grid_loads, inertial_loads,
                                  reactions, grid_index)


def _warn_if_mass_coverage_incomplete(
    name: str, mon: Monpnt3, bulk: BulkData, grid_loads: FloatArray,
    grid_index: dict[int, int], massset_sid: Optional[int],
) -> None:
    """Warn when a whole-aircraft MONPNT3 omits CONM2-bearing grids (DEF-M10).

    A section-cut monitor legitimately covers only part of the model, so a plain
    "does this set include every mass?" test would fire on every wing-root or
    per-wing cut.  The signature of the real defect is narrower: a monitor that
    integrates *all* of the aero but only *some* of the mass.  Such a monitor
    reports a spurious force imbalance on a balanced trim — the shipped HA144A
    deck omitted one 93.24-slug grid and showed ~+3000 lb of phantom lift.

    So the aero coverage is what qualifies a monitor as whole-aircraft in scope;
    only then is its mass coverage checked.

    Masses are taken from the *active* mass case, not from every CONM2 card:
    a MASSSET deck carries mutually exclusive overlays (half fuel / full fuel),
    and counting them all would report a fraction the run never had.
    """
    conm2s = effective_conm2s(bulk, massset_sid)
    conm2_grids = {c.gid for c in conm2s.values()}
    if not conm2_grids:
        return

    aecomp = bulk.aecomps[mon.comp]
    gids = set()
    for sid in aecomp.list_ids:
        gids.update(bulk.set1s[sid].grids)

    # Aero coverage: this monitor's z-force against the model total.
    total_fz = float(np.sum(grid_loads[2::6]))
    if abs(total_fz) < 1e-12:
        return
    mon_fz = sum(float(grid_loads[6 * grid_index[gid] + 2])
                 for gid in gids if gid in grid_index)
    if abs(mon_fz - total_fz) > 0.01 * abs(total_fz):
        return                      # a genuine section cut — not our business

    missing = sorted(conm2_grids - gids)
    if not missing:
        return

    m_missing = sum(c.m for c in conm2s.values() if c.gid in missing)
    m_total = sum(c.m for c in conm2s.values())
    frac = 100.0 * m_missing / m_total if m_total else 0.0
    warnings.warn(
        f"MONPNT3 {name} (AECOMP {mon.comp}) integrates the whole-aircraft aero "
        f"load but its grid set omits {len(missing)} CONM2-bearing grid(s) "
        f"{missing} carrying {m_missing:g} of {m_total:g} mass units "
        f"({frac:.2f}%).  The monitor will report a spurious force imbalance on "
        f"a balanced trim; add the grid(s) to its SET1.",
        UserWarning,
        stacklevel=3,
    )


def compute_monitor_loads(
    bulk: BulkData, aero: AeroModel, box_forces: FloatArray,
    grid_loads: FloatArray, inertial_loads: Optional[FloatArray],
    grid_index: dict[int, int],
    reactions: Optional[dict[int, FloatArray]] = None,
    massset_sid: Optional[int] = None,
) -> dict[str, MonitorLoad]:
    """Build {name: MonitorLoad} for all MONPNT1/MONPNT3 cards in the model."""
    out: dict[str, MonitorLoad] = {}
    for name, plan in prepare_monitor_points(bulk, aero, grid_index).items():
        out[name] = evaluate_monitor_point(
            plan, box_forces, grid_loads, inertial_loads, reactions or {},
            grid_index)
        if plan.mtype == "MONPNT3":
            _warn_if_mass_coverage_incomplete(
                name, bulk.monpnt3s[name], bulk, grid_loads, grid_index,
                massset_sid)
    return out
