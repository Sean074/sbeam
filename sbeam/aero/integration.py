"""
Aeroelastic integration matrices for steady VLM (Phase A, k=0).

Convention: all downwash / normalwash quantities are dimensionless slope (Δz/Δx).
"""

import numpy as np

from sbeam.aero.panel import AeroBox


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
