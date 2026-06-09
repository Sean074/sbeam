"""AIC correction methods — steady (k=0) rescaling of the VLM aerodynamic influence matrix.

Three tiers, in increasing data requirement:

  Wkk   — diagonal multiplicative weighting: AJJ* = diag(w) @ AJJ.
  WT2   — pressure matching: per-box cp scaling to reproduce a target cp distribution.
  WT1   — force/moment matching: per-strip lift scaling to reproduce target section loads.

Reference normalwash convention (WT1 and WT2):
  w_ref = -np.ones(n)  (uniform unit incidence, alpha = 1, same rhs as solve_rigid_cl).
  All corrections are relative to the VLM solution at that reference incidence.

Return types:
  apply_wkk  →  corrected AJJ*  (caller inverts via lstsq)
  apply_wt2  →  corrected AJJ*⁻¹
  apply_wt1  →  corrected AJJ*⁻¹
"""

import warnings

import numpy as np

from sbeam.aero.panel import AeroBox

_COND_WARN_THRESHOLD = 1e10
_RATIO_TOL = 1e-12   # guard for near-zero reference quantities


def _check_conditioning(ajj: np.ndarray) -> None:
    cond = float(np.linalg.cond(ajj))
    if cond > _COND_WARN_THRESHOLD:
        warnings.warn(
            f"AIC matrix is poorly conditioned (cond={cond:.2e}); "
            "correction accuracy may be degraded",
            UserWarning,
            stacklevel=3,
        )


def _solve_ajj(ajj: np.ndarray) -> np.ndarray:
    """Compute AJJ⁻¹ stably via lstsq."""
    n = ajj.shape[0]
    inv, *_ = np.linalg.lstsq(ajj, np.eye(n), rcond=None)
    return inv


def apply_wkk(ajj: np.ndarray, wkk_data: list) -> np.ndarray:
    """Diagonal multiplicative AIC correction.

    Returns AJJ* = diag(wkk_data) @ AJJ.
    Caller is responsible for inverting AJJ* (e.g. via lstsq).
    """
    w = np.asarray(wkk_data, dtype=float)
    return np.diag(w) @ ajj


def apply_wt2(ajj: np.ndarray, cp_target: np.ndarray) -> np.ndarray:
    """Pressure-matching correction.  Returns corrected AJJ*⁻¹.

    Finds a diagonal scaling r such that the corrected A*⁻¹ = diag(r) @ AJJ⁻¹
    reproduces cp_target when applied to the unit-incidence reference normalwash
    w_ref = -ones(n):

        cp_vlm_ref  = AJJ⁻¹ @ w_ref          (VLM at unit incidence)
        r_k         = cp_target_k / cp_vlm_ref_k
        A*⁻¹        = diag(r) @ AJJ⁻¹

    Boxes where |cp_vlm_ref_k| < _RATIO_TOL keep r_k = 1 (no correction applied).
    Warns if cond(AJJ) > 1e10.
    """
    _check_conditioning(ajj)
    n = ajj.shape[0]
    ajj_inv = _solve_ajj(ajj)
    w_ref = -np.ones(n)
    cp_vlm_ref = ajj_inv @ w_ref
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(cp_vlm_ref != 0.0, cp_target / cp_vlm_ref, 1.0)
    r = np.where(np.abs(cp_vlm_ref) > _RATIO_TOL, ratio, 1.0)
    return np.diag(r) @ ajj_inv


def apply_wt1(ajj: np.ndarray, boxes: list[AeroBox], f_target: np.ndarray) -> np.ndarray:
    """Force/moment-matching correction.  Returns corrected AJJ*⁻¹.

    Finds a diagonal scaling r — constant within each span strip — such that the
    corrected A*⁻¹ = diag(r) @ AJJ⁻¹ reproduces the per-strip lift f_target when
    applied to the unit-incidence reference normalwash w_ref = -ones(n):

        cp_vlm_ref  = AJJ⁻¹ @ w_ref
        f_vlm_s     = sum(area_k * cp_vlm_ref_k)  for box k in strip s
        ratio_s     = f_target_s / f_vlm_s
        r_k         = ratio_s  for all boxes k in strip s

    Strips where |f_vlm_s| < _RATIO_TOL keep ratio_s = 1 (no correction applied).
    f_target must have length equal to the number of distinct i_span values in boxes,
    ordered by ascending i_span.

    Warns if cond(AJJ) > 1e10.
    """
    _check_conditioning(ajj)
    n = ajj.shape[0]
    ajj_inv = _solve_ajj(ajj)
    w_ref = -np.ones(n)
    cp_vlm_ref = ajj_inv @ w_ref

    # Group boxes by span strip
    strip_indices: dict[int, list[int]] = {}
    for k, box in enumerate(boxes):
        strip_indices.setdefault(box.i_span, []).append(k)

    sorted_strips = sorted(strip_indices.keys())
    if len(sorted_strips) != len(f_target):
        raise ValueError(
            f"apply_wt1: f_target length {len(f_target)} does not match "
            f"number of span strips {len(sorted_strips)}"
        )

    r = np.ones(n)
    for s_idx, i_span in enumerate(sorted_strips):
        idxs = strip_indices[i_span]
        f_vlm_s = sum(boxes[k].area * cp_vlm_ref[k] for k in idxs)
        if abs(f_vlm_s) > _RATIO_TOL:
            ratio_s = float(f_target[s_idx]) / f_vlm_s
            for k in idxs:
                r[k] = ratio_s

    return np.diag(r) @ ajj_inv
