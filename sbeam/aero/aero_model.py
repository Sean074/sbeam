"""AeroModel — assembled aeroelastic data container for steady VLM (Phase A, k=0).

Build order:
  1. Mesh all CAERO1 elements into AeroBox lists.
  2. Build the raw VLM AIC matrix AJJ.
  3. Apply whichever correction is present (Wkk → WT2 → WT1 → none).
  4. Build Skj, Djk, and the baseline normalwash wg.
  5. Package everything into AeroModel.

The corrected inverse AJJ*⁻¹ is stored directly so that the downstream SOL 144
solve (A*⁻¹ @ w) never has to refactor the matrix.
"""

from dataclasses import dataclass

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import AeroBox, mesh_caero1
from sbeam.aero.vlm import build_ajj
from sbeam.aero.integration import build_skj, build_djk, build_wg
from sbeam.aero.corrections import apply_wkk, apply_wt2, apply_wt1


@dataclass
class AeroModel:
    boxes:        list          # list[AeroBox] — all panels across all CAERO1 elements
    ajj:          np.ndarray    # raw VLM AIC,  shape (n, n)
    ajj_inv_corr: np.ndarray    # corrected A*⁻¹, shape (n, n)
    skj:          np.ndarray    # force integration matrix, shape (3n, n)
    djk:          np.ndarray    # deflection-to-downwash matrix, shape (n, n)
    wg:           np.ndarray    # baseline normalwash vector, shape (n,)
    parity:       int           # +1 symmetric / -1 antisymmetric / 0 full-span


def build_aero_model(bulk: BulkData, parity: int = 1) -> AeroModel:
    """Assemble the full AeroModel from parsed bulk data.

    Correction precedence (first match wins, per CAERO1 element):
      1. WKK card present  → diagonal multiplicative: AJJ* = diag(wkk) @ AJJ,
                              AJJ*⁻¹ computed via lstsq.
      2. AECORR WT2 present → pressure-matching correction (apply_wt2).
      3. AECORR WT1 present → force-matching correction (apply_wt1).
      4. No correction       → AJJ*⁻¹ = lstsq(AJJ).

    When multiple CAERO1 elements are present, all boxes are concatenated into a
    single list and a single AIC is built for the combined surface.  Corrections
    are applied to the *global* AIC using the data from the correction card whose
    caero_eid matches the first (or only) CAERO1 element found.  Multi-element
    per-surface corrections are a Phase B concern.
    """
    if not bulk.caero1s:
        raise ValueError("build_aero_model: no CAERO1 elements found in bulk data")

    # Mesh all CAERO1 elements in ascending EID order
    boxes: list[AeroBox] = []
    start_k = 0
    for eid in sorted(bulk.caero1s):
        caero = bulk.caero1s[eid]
        paero = bulk.paero1s.get(caero.pid)
        new_boxes = mesh_caero1(caero, paero, bulk.aefacts, bulk.cord2rs, start_k=start_k)
        boxes.extend(new_boxes)
        start_k += len(new_boxes)

    n = len(boxes)

    # Build raw AIC
    ajj = build_ajj(boxes, parity)

    # Determine which correction applies — use the first CAERO1 EID as the key
    primary_eid = sorted(bulk.caero1s)[0]

    wkk_card  = next((c for c in bulk.wkks.values()   if c.caero_eid == primary_eid), None)
    wt2_card  = next((c for c in bulk.aecorrs.values() if c.caero_eid == primary_eid and c.method == "WT2"), None)
    wt1_card  = next((c for c in bulk.aecorrs.values() if c.caero_eid == primary_eid and c.method == "WT1"), None)

    if wkk_card is not None:
        ajj_star = apply_wkk(ajj, wkk_card.data)
        ajj_inv_corr, *_ = np.linalg.lstsq(ajj_star, np.eye(n), rcond=None)
    elif wt2_card is not None:
        cp_target = np.asarray(wt2_card.target, dtype=float)
        ajj_inv_corr = apply_wt2(ajj, cp_target)
    elif wt1_card is not None:
        f_target = np.asarray(wt1_card.target, dtype=float)
        ajj_inv_corr = apply_wt1(ajj, boxes, f_target)
    else:
        ajj_inv_corr, *_ = np.linalg.lstsq(ajj, np.eye(n), rcond=None)

    skj = build_skj(boxes)
    djk = build_djk(boxes)

    # Accumulate baseline normalwash across all CAERO1 elements
    wg = np.zeros(n)
    for eid in sorted(bulk.caero1s):
        wg += build_wg(boxes, bulk.w2gjs, eid)

    return AeroModel(
        boxes=boxes,
        ajj=ajj,
        ajj_inv_corr=ajj_inv_corr,
        skj=skj,
        djk=djk,
        wg=wg,
        parity=parity,
    )
