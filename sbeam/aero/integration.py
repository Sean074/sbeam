"""
Aeroelastic integration matrices for steady VLM (Phase A, k=0).

Convention: all downwash / normalwash quantities are dimensionless slope (Δz/Δx).
"""

import numpy as np

from sbeam.aero.panel import AeroBox
from sbeam.assembly.coord_transform import _get_transform


def build_skj(boxes: list[AeroBox]) -> np.ndarray:
    """Area-weighted force integration matrix.  Shape: (3*n_box, n_box).

    Column j maps pressure coefficient cp_j to the resultant force vector
    [Fx, Fy, Fz] at box j:  F_j = area_j * normal_j * cp_j.

    Usage: F_vec = build_skj(boxes) @ cp_vec  →  [Fx0, Fy0, Fz0, Fx1, …].
    """
    n = len(boxes)
    skj = np.zeros((3 * n, n))
    for j, box in enumerate(boxes):
        skj[3 * j : 3 * j + 3, j] = box.area * box.normal
    return skj


def build_djk(boxes: list[AeroBox]) -> np.ndarray:
    """Deflection-to-downwash matrix for rigid wing at k=0.  Shape: (n_box, n_box).

    The input is a vector of dimensionless slopes (Δz/Δx) at each box collocation
    point; the output is the normalwash at each collocation point.

    Returns negative identity: w_j = −slope_j (nose-up slope → downward wash).
    Phase D DLM will replace this with the full unsteady kernel without changing
    callers.
    """
    return -np.eye(len(boxes))


def build_wg(boxes: list[AeroBox], w2gjs: dict, caero_eid: int) -> np.ndarray:
    """Baseline normalwash vector from W2GJ card.  Shape: (n_box,).

    Returns a zero vector when no W2GJ card is present for *caero_eid*.
    W2GJ data is ordered row-major (span index varies slowest, chord fastest),
    matching the ordering produced by mesh_caero1.
    """
    n = len(boxes)
    wg = np.zeros(n)
    for w2gj in w2gjs.values():
        if w2gj.caero_eid != caero_eid:
            continue
        caero_boxes = [
            (global_j, box)
            for global_j, box in enumerate(boxes)
            if box.caero_eid == caero_eid
        ]
        for local_k, (global_j, _) in enumerate(caero_boxes):
            if local_k < len(w2gj.data):
                wg[global_j] = w2gj.data[local_k]
        break   # only one W2GJ per CAERO1
    return wg


def build_djx(boxes: list, trim_labels: list, bulk) -> np.ndarray:
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
    YAW     -(2/bref)*y_ctrl[j]  (side slip rate, for vertical panels)
    URDD1–6  0  (inertial — structural only, no direct aerodynamic effect)
    AESURF  -nz[j]*eff for boxes in the AELIST, 0 elsewhere
    """
    n_box    = len(boxes)
    n_labels = len(trim_labels)
    djx      = np.zeros((n_box, n_labels))

    aeros   = bulk.aeros
    c_ref   = aeros.cref
    b_ref   = aeros.bref

    # Reference point for pitch rate: origin of RCSID in basic CID 0
    if aeros.rcsid:
        x_ref_pt, _ = _get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(x_ref_pt[0])
    else:
        x_ref = 0.0

    # Build NASTRAN-box-ID → global-k-index reverse map (for AESURF columns)
    nastran_id_to_k: dict = {}
    for box in boxes:
        caero = bulk.caero1s[box.caero_eid]
        nchord_b = (caero.nchord if caero.nchord > 0
                    else len(bulk.aefacts[caero.lchord].data) - 1)
        bid = box.caero_eid + box.i_span * nchord_b + box.j_chord
        nastran_id_to_k[bid] = box.k

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

        elif ul in ("ROLL", "YAW"):
            for box in boxes:
                y_ctrl = box.colloc[1]
                djx[box.k, col] = -(2.0 / b_ref) * y_ctrl

        elif ul.startswith("URDD"):
            pass  # zero — no direct aerodynamic effect

        else:
            # AESURF label: find the matching surface
            for aesurf in bulk.aesurfs.values():
                if aesurf.label.upper() != ul:
                    continue
                eff    = aesurf.eff if aesurf.eff != 0.0 else 1.0
                aelist = bulk.aelists.get(aesurf.alid1)
                if aelist is None:
                    continue
                for bid in aelist.elements:
                    k = nastran_id_to_k.get(bid)
                    if k is not None:
                        djx[k, col] = -boxes[k].normal[2] * eff
    return djx
