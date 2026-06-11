"""AeroModel — assembled aeroelastic data container for steady VLM (Phase A, k=0).

Build order:
  1. Mesh all CAERO1 elements into AeroBox lists.
  2. Build the raw VLM AIC matrix AJJ.
  3. Apply whichever correction is present (Wkk → WT2 → WT1 → none).
  4. Build Skj, Djk, and the baseline normalwash wg.
  5. Package everything into AeroModel.

The corrected inverse AJJ*⁻¹ is stored directly (computed via LU factorization) so
that the downstream SOL 144 solve (A*⁻¹ @ w) never has to refactor the matrix.
"""

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros
from sbeam.aero.panel import AeroBox, mesh_caero1
from sbeam.aero.vlm import build_ajj, prandtl_glauert_boxes
from sbeam.aero.integration import build_skj, build_djk, build_wg
from sbeam.aero.corrections import apply_wkk, apply_wt2, apply_wt1, _check_conditioning
from sbeam.aero.spline import build_g_spline


@dataclass
class AeroModel:
    boxes:        list                # list[AeroBox] — all panels across all CAERO1 elements
    ajj:          np.ndarray          # raw VLM AIC,  shape (n, n)
    ajj_inv_corr: np.ndarray          # corrected A*⁻¹, shape (n, n)
    skj:          np.ndarray          # force integration matrix, shape (3n, n)
    djk:          np.ndarray          # deflection-to-downwash matrix, shape (n, n)
    wg:           np.ndarray          # baseline normalwash vector, shape (n,)
    parity:       int                 # +1 symmetric / -1 antisymmetric / 0 full-span
    aeros:        Optional[Aeros] = None       # AEROS reference geometry card
    mach:         float = 0.0                  # Mach number for Prandtl–Glauert
    g_slope:      Optional[np.ndarray] = None  # slope spline, shape (n, 6*n_g)
    g_disp:       Optional[np.ndarray] = None  # displacement spline, shape (3n, 6*n_g)


def build_aero_model(bulk: BulkData, parity: int = 1, grid_index: Optional[dict] = None) -> AeroModel:
    """Assemble the full AeroModel from parsed bulk data.

    Correction precedence (first match wins, per CAERO1 element):
      1. WKK card present  → diagonal multiplicative: AJJ* = diag(wkk) @ AJJ,
                              AJJ*⁻¹ computed via lstsq.
      2. AECORR WT2 present → pressure-matching correction (apply_wt2).
      3. AECORR WT1 present → force-matching correction (apply_wt1).
      4. No correction       → AJJ*⁻¹ = solve(AJJ).

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

    # Prandtl–Glauert / Göthert compressibility correction (§2.8 Eq. 14):
    # compress box y,z by β = √(1-M²) before building AIC; scale AIC⁻¹ by 1/β.
    mach = bulk.aeros.mach if bulk.aeros else 0.0
    beta_pg = math.sqrt(1.0 - min(mach, 0.99) ** 2) if mach > 0.0 else 1.0
    pg_boxes = prandtl_glauert_boxes(boxes, mach)

    # Build raw AIC on PG-compressed geometry
    ajj = build_ajj(pg_boxes, parity)

    # Determine which correction applies — use the first CAERO1 EID as the key
    primary_eid = sorted(bulk.caero1s)[0]

    wkk_card  = next((c for c in bulk.wkks.values()   if c.caero_eid == primary_eid), None)
    wt2_card  = next((c for c in bulk.aecorrs.values() if c.caero_eid == primary_eid and c.method == "WT2"), None)
    wt1_card  = next((c for c in bulk.aecorrs.values() if c.caero_eid == primary_eid and c.method == "WT1"), None)

    if wkk_card is not None:
        ajj_star = apply_wkk(ajj, wkk_card.data)
        _check_conditioning(ajj_star)
        ajj_inv_corr = np.linalg.solve(ajj_star, np.eye(n))
    elif wt2_card is not None:
        cp_target = np.asarray(wt2_card.target, dtype=float)
        ajj_inv_corr = apply_wt2(ajj, cp_target)
    elif wt1_card is not None:
        f_target = np.asarray(wt1_card.target, dtype=float)
        ajj_inv_corr = apply_wt1(ajj, pg_boxes, f_target)
    else:
        _check_conditioning(ajj)
        ajj_inv_corr = np.linalg.solve(ajj, np.eye(n))

    # Apply Göthert 1/β scaling (boundary-condition factor from §2.8 Eq. 14)
    if beta_pg != 1.0:
        ajj_inv_corr /= beta_pg

    # Integration matrices use physical (unscaled) boxes — structural coupling
    # geometry must match the physical planform, not the PG-compressed one.
    skj = build_skj(boxes)
    djk = build_djk(boxes)

    # Accumulate baseline normalwash across all CAERO1 elements
    wg = np.zeros(n)
    for eid in sorted(bulk.caero1s):
        wg += build_wg(boxes, bulk.w2gjs, eid)

    # Build spline operators if spline cards are present and grid_index is provided
    g_slope: Optional[np.ndarray] = None
    g_disp:  Optional[np.ndarray] = None
    if grid_index is not None and (bulk.spline2s or bulk.attaches or bulk.spline0s):
        g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)

    return AeroModel(
        boxes=boxes,
        ajj=ajj,
        ajj_inv_corr=ajj_inv_corr,
        skj=skj,
        djk=djk,
        wg=wg,
        parity=parity,
        aeros=bulk.aeros,
        mach=mach,
        g_slope=g_slope,
        g_disp=g_disp,
    )
