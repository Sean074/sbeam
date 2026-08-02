"""
Aeroelastic integration matrices for steady VLM (Phase A, k=0).

Sign convention (see docs/20_theory/01_aeroelastics_theory.md §2.4):
the assembled normalwash ``w`` (and the baseline ``w_g``) is a dimensionless
downwash slope Δz/Δx (z up, x streamwise).  POSITIVE ``w``/``w_g`` is a local
nose-down (washout) slope that REDUCES lift; a leading-edge-up incidence that
increases lift is NEGATIVE.  The spline/AoA boundary condition is supplied as a
nose-up-positive *incidence* and mapped to this normalwash by the negative sign
in ``build_djk`` (-I) and the ANGLEA column (-n_z).  W2GJ card data follows the
NASTRAN convention (positive = nose-up incidence, like ANGLEA), so ``build_wg``
applies the same negation when assembling the internal ``w_g``.
"""

from typing import Optional

import numpy as np

from sbeam.aero.panel import AeroBox, build_box_id_map
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.coord_transform import get_transform
from sbeam.types import FloatArray
from sbeam.model.aero import W2gj, require_aeros


def build_skj(boxes: list[AeroBox]) -> FloatArray:
    """Area-weighted force integration matrix.  Shape: (3*n_box, n_box).

    Column j maps pressure coefficient cp_j to the resultant force vector
    [Fx, Fy, Fz] at box j:  F_j = area_j * normal_j * cp_j.

    Usage: F_vec = build_skj(boxes) @ cp_vec  →  [Fx0, Fy0, Fz0, Fx1, …].
    """
    n = len(boxes)
    skj = np.zeros((3 * n, n))
    if n:
        areas = np.array([box.area for box in boxes])
        normals = np.array([box.normal for box in boxes])
        idx = np.arange(n)
        skj.reshape(n, 3, n)[idx, :, idx] = areas[:, None] * normals
    return skj


def build_djk(boxes: list[AeroBox]) -> FloatArray:
    """Deflection-to-downwash matrix for rigid wing at k=0.  Shape: (n_box, n_box).

    The input is the per-box *incidence* (nose-up positive) that the spline
    delivers from structural motion; the output is the normalwash at each
    collocation point.

    Returns negative identity: w_j = −incidence_j, so a nose-up incidence
    (lift-increasing) becomes a negative normalwash.  This is the OPPOSITE sign
    sense to a baseline ``w_g`` slope, which is supplied directly as a normalwash
    (positive = washout = less lift; see ``build_wg``).  Phase D DLM will replace
    this with the full unsteady kernel without changing callers.
    """
    return -np.eye(len(boxes))


def build_wg(boxes: list[AeroBox], w2gjs: dict[int, W2gj], caero_eid: int) -> FloatArray:
    """Baseline normalwash vector from W2GJ card.  Shape: (n_box,).

    W2GJ card data follows the NASTRAN convention (MSC Aeroelastic UG Eq 2-104,
    HA144A example): POSITIVE = leading-edge-up incidence/camber → MORE lift —
    the same nose-up-positive sense as ANGLEA.  Like the ANGLEA column (-n_z)
    and ``build_djk`` (-I), the card values are NEGATED here to form the
    internal normalwash slope (positive = washout).

    Returns a zero vector when no W2GJ card is present for *caero_eid*.
    W2GJ data is ordered row-major (span index varies slowest, chord fastest),
    matching the ordering produced by mesh_caero1.

    Raises:
        ValueError: if two W2GJ cards target the same CAERO1 (the second used to
            be silently shadowed), or if the card's data length does not match
            the surface's box count.  A short card used to be zero-padded and a
            long one truncated — both silent, and both almost always a mesh the
            builder and the deck disagree about (DEF-M8a / DEF-L1).
    """
    n = len(boxes)
    wg = np.zeros(n)

    cards = [w for w in w2gjs.values() if w.caero_eid == caero_eid]
    if not cards:
        return wg
    if len(cards) > 1:
        sids = ", ".join(str(w.sid) for w in sorted(cards, key=lambda w: w.sid))
        raise ValueError(
            f"W2GJ: CAERO1 {caero_eid} is targeted by {len(cards)} cards "
            f"(SIDs {sids}); only one W2GJ per CAERO1 is supported.  Merge them "
            "into a single card or remove the duplicates."
        )

    w2gj = cards[0]
    surf_idx = [j for j, box in enumerate(boxes) if box.caero_eid == caero_eid]
    if len(w2gj.data) != len(surf_idx):
        raise ValueError(
            f"W2GJ {w2gj.sid}: {len(w2gj.data)} data values for CAERO1 "
            f"{caero_eid}, which meshes to {len(surf_idx)} boxes.  W2GJ data is "
            "one value per box, row-major (span slowest, chord fastest)."
        )
    for local_k, global_j in enumerate(surf_idx):
        wg[global_j] = -w2gj.data[local_k]
    return wg


def build_wg_all(boxes: list[AeroBox], w2gjs: dict[int, W2gj]) -> FloatArray:
    """Assemble the baseline normalwash over every meshed CAERO1.  Shape: (n_box,).

    Replaces the caller-side ``for eid in sorted(bulk.caero1s)`` loop so that the
    orphan case is caught: a W2GJ naming a ``caero_eid`` that no meshed CAERO1
    provides was never visited by that loop at all, making it dead data that the
    program accepted and ignored (DEF-M8a).

    Raises:
        ValueError: if a W2GJ card references a CAERO1 with no meshed boxes.
    """
    meshed = {box.caero_eid for box in boxes}
    orphans = sorted({w.sid for w in w2gjs.values() if w.caero_eid not in meshed})
    if orphans:
        detail = ", ".join(
            f"W2GJ {sid} → CAERO1 {w2gjs[sid].caero_eid}" for sid in orphans)
        raise ValueError(
            f"{detail}: no such CAERO1 in the meshed model, so the card would "
            "never be applied.  Check the CAERO1 EID on the W2GJ card."
        )

    wg = np.zeros(len(boxes))
    for eid in sorted(meshed):
        wg += build_wg(boxes, w2gjs, eid)
    return wg


#: Rigid-body DOF (1-6) → the ``build_djx`` trim label whose normalwash column
#: has the same geometry, and the factor that converts that nondimensional
#: column to a physical rate column (see ``build_dj_rigidrate``).
#: ``None`` marks a DOF with no quasi-steady rate normalwash at Level 1.
_RIGID_RATE_LABEL = {1: None, 2: "SIDES", 3: "ANGLEA",
                     4: "ROLL", 5: "PITCH", 6: "YAW"}


def rigid_rate_scales(bulk: BulkData, v_inf: float) -> dict[int, float]:
    """Physical rigid rate (DOF 1-6) -> equivalent steady-trim-label value.

    The single owner of the quasi-steady rate nondimensionalization: the same
    factors convert a ``build_djx`` label column into a physical rate column
    (``build_dj_rigidrate``) and a rigid modal rate into the trim-label
    increment the free-flight recovery feeds through ``D_jx`` (Step 63) — by
    construction the two paths then agree exactly.

    See the sign discussion in ``build_dj_rigidrate``; DOF 3 carries the
    ``α = θ − ḣ/V`` plunge-rate sign.
    """
    if v_inf <= 0.0:
        raise ValueError(
            f"rigid_rate_scales: v_inf must be positive; got {v_inf}")
    c_ref = require_aeros(bulk).cref
    b_ref = require_aeros(bulk).bref
    return {1: 0.0, 2: 1.0 / v_inf, 3: -1.0 / v_inf,
            4: b_ref / (2.0 * v_inf), 5: c_ref / (2.0 * v_inf),
            6: b_ref / (2.0 * v_inf)}


def build_dj_rigidrate(
    boxes: list[AeroBox], rigid_dofs: list[int], bulk: BulkData, v_inf: float
) -> FloatArray:
    """Normalwash per unit *physical* rigid-body rate.  Shape: (n_box, n_rigid).

    Level-1 quasi-steady rate aerodynamics for the free-free maneuver basis
    (Step 61).  Column k corresponds to ``rigid_dofs[k]`` (a rigid-body DOF
    component 1-6 about the basis reference point) and gives the normalwash per
    unit rate of that DOF: per unit velocity (length/time) for the translational
    DOFs 1-3, per unit angular rate (rad/s) for the rotational DOFs 4-6.

    The geometry is not re-derived here — every column is the corresponding
    ``build_djx`` column rescaled, so the ``Ω×r`` collocation algebra lives in
    exactly one place:

    ===== ==================== ==========================================
    DOF   build_djx label      physical column
    ===== ==================== ==========================================
    1 Tx  —                    0 (streamwise rate has no k=0 normalwash)
    2 Ty  SIDES  (−n_y)        SIDES / V      (sideslip β = v/V)
    3 Tz  ANGLEA (−n_z)        −ANGLEA / V    (α = −ḣ/V, plunge-rate −1/V)
    4 Rx  ROLL   (−2y/b_ref)   ROLL · b_ref/(2V)
    5 Ry  PITCH  (−2(x−x_r)/c) PITCH · c_ref/(2V)
    6 Rz  YAW    (−2(x−x_r)n_y/b) YAW · b_ref/(2V)
    ===== ==================== ==========================================

    The sign on DOF 3 is the one physical subtlety: a positive plunge *rate*
    (``ḣ`` up) reduces the angle of attack (``α = θ − ḣ/V``), so its column is
    the negative of the ANGLEA column scaled by 1/V.  Positive ``v`` (DOF 2) is
    a positive sideslip velocity and keeps the SIDES sign.

    Elastic-rate normalwash (the ``ḣ`` of the deformation itself) is zero at
    Level 1 — the G0-d unsteady-correction hook.

    Args:
        boxes:      aero boxes.
        rigid_dofs: list[int] of rigid-body DOF components (1-6), one per column.
        bulk:       BulkData (AEROS reference geometry, as for build_djx).
        v_inf:      true airspeed, from ``Trim.velocity()``.

    Returns:
        (n_box, n_rigid) physical-rate normalwash matrix.
    """
    if v_inf <= 0.0:
        raise ValueError(
            f"build_dj_rigidrate: v_inf must be positive; got {v_inf}")
    scale = rigid_rate_scales(bulk, v_inf)

    labels = [_RIGID_RATE_LABEL[d] for d in rigid_dofs]
    known = [l for l in labels if l is not None]
    djx = build_djx(boxes, known, bulk) if known else np.zeros((len(boxes), 0))

    out = np.zeros((len(boxes), len(rigid_dofs)))
    col_of = {l: i for i, l in enumerate(known)}
    for k, (dof, label) in enumerate(zip(rigid_dofs, labels)):
        if label is None:
            continue                       # DOF 1 (streamwise) — no k=0 effect
        out[:, k] = scale[dof] * djx[:, col_of[label]]
    return out


def build_djx(
    boxes: list[AeroBox], trim_labels: list[str], bulk: BulkData,
    id_to_k: Optional[dict[int, int]] = None,
) -> FloatArray:
    """Downwash-to-trim-variable matrix D_jx.  Shape: (n_box, n_labels).

    Each column k gives the normalwash contribution at each box collocation
    point per unit of the corresponding trim label.  Signs follow the
    aerodynamic normalwash convention (positive = upward flow, i.e. nose-down).

    Supported labels
    ----------------
    ANGLEA  -nz[j]
    SIDES   -ny[j]  (for vertical surfaces)
    PITCH   -(2/cref)*(x_ctrl[j] - x_ref)
    ROLL    -(2/bref)*y_ctrl[j]
    YAW     -(2/bref)*(x_ctrl[j] - x_ref)*ny[j]  (yaw-rate sidewash on vertical
            panels; vanishes on horizontal/z-normal panels)
    URDD1–6  0  (inertial — structural only, no direct aerodynamic effect)
    AESURF  -(h_hat × n[j])·x_hat * eff for boxes in the AELIST, 0 elsewhere,
            where h_hat is the hinge axis (cid1 y-axis); reduces to -nz[j]*eff
            for a spanwise (global-y) hinge.
    """
    n_box    = len(boxes)
    n_labels = len(trim_labels)
    djx      = np.zeros((n_box, n_labels))

    aeros   = require_aeros(bulk)
    c_ref   = aeros.cref
    b_ref   = aeros.bref

    # Reference point for pitch rate: origin of RCSID in basic CID 0
    if aeros.rcsid:
        x_ref_pt, _ = get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(x_ref_pt[0])
    else:
        x_ref = 0.0

    # NASTRAN-box-ID → global-k reverse map (for AESURF/AELIST columns).  One
    # shared, collision-checked derivation (F1); callers holding an AeroModel
    # pass ``aero.require_box_id_to_k()`` so it is not rebuilt per call.
    nastran_id_to_k = build_box_id_map(boxes) if id_to_k is None else id_to_k

    for col, label in enumerate(trim_labels):
        ul = label.upper()

        if ul == "ANGLEA":
            for box in boxes:
                djx[box.k, col] = -box.normal[2]

        elif ul == "SIDES":
            for box in boxes:
                djx[box.k, col] = -box.normal[1]

        elif ul == "PITCH":
            for box in boxes:
                x_ctrl = box.colloc[0]
                djx[box.k, col] = -(2.0 / c_ref) * (x_ctrl - x_ref)

        elif ul == "ROLL":
            for box in boxes:
                y_ctrl = box.colloc[1]
                djx[box.k, col] = -(2.0 / b_ref) * y_ctrl

        elif ul == "YAW":
            # Yaw rate r about z induces lateral sidewash v_y = r*(x − x_ref),
            # an effective local sideslip sensed only through the box y-normal
            # (matching SIDES = −n_y).  Horizontal (z-normal) panels have n_y = 0
            # and see no yaw-rate normalwash, so the column vanishes there;
            # nondimensionalised by 2/bref like the other rate columns.
            for box in boxes:
                x_ctrl = box.colloc[0]
                djx[box.k, col] = -(2.0 / b_ref) * (x_ctrl - x_ref) * box.normal[1]

        elif ul.startswith("URDD"):
            pass  # zero — no direct aerodynamic effect

        else:
            # AESURF label: control deflection rotates the box about the hinge
            # axis (cid1 y-axis).  The induced streamwise normalwash is
            # −(h_hat × n)·x_hat; for a spanwise hinge (h_hat = global y) this is
            # exactly −n_z, recovering the flat-plate flap result.
            for aesurf in bulk.aesurfs.values():
                if aesurf.label.upper() != ul:
                    continue
                eff    = aesurf.eff
                _o, R  = get_transform(aesurf.cid1, bulk.cord2rs)
                h_hat  = R[:, 1]                       # hinge axis = cid1 y-axis
                aelist = bulk.aelists.get(aesurf.alid1)
                if aelist is None:
                    continue
                for bid in aelist.elements:
                    k = nastran_id_to_k.get(bid)
                    if k is not None:
                        djx[k, col] = -np.cross(h_hat, boxes[k].normal)[0] * eff
    return djx
