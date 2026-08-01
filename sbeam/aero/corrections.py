"""AIC correction methods — steady (k=0) rescaling of the VLM aerodynamic influence matrix.

Three tiers, in increasing data requirement:

  Wkk   — diagonal multiplicative weighting: AJJ* = diag(w) @ AJJ.
  WT2   — pressure matching: per-box cp scaling to reproduce a target cp distribution.
  WT1   — force/moment matching: per-strip lift scaling.  **DEPRECATED (DEF-H2/H3)** —
          see ``apply_wt1``; use WT2 or ``sbeam.aero.section_correction`` instead.

Reference normalwash convention (WT1 and WT2):
  w_ref = -np.ones(n)  (uniform unit incidence, alpha = 1, same rhs as solve_rigid_cl).
  All corrections are relative to the VLM solution at that reference incidence.

Return types:
  apply_wkk  →  corrected AJJ*  (caller inverts via np.linalg.solve)
  apply_wt2  →  corrected AJJ*⁻¹
  apply_wt1  →  corrected AJJ*⁻¹
"""

import warnings
from typing import Sequence, Union

import numpy as np

from sbeam.aero.panel import AeroBox
from sbeam.types import FloatArray

_COND_WARN_THRESHOLD = 1e10
_RATIO_TOL = 1e-12   # guard for near-zero reference quantities


def check_conditioning(ajj: FloatArray) -> None:
    cond = float(np.linalg.cond(ajj))
    if cond > _COND_WARN_THRESHOLD:
        warnings.warn(
            f"AIC matrix is poorly conditioned (cond={cond:.2e}); "
            "correction accuracy may be degraded",
            UserWarning,
            stacklevel=3,
        )


def _solve_ajj(ajj: FloatArray) -> FloatArray:
    """Compute AJJ⁻¹ via LU factorization (np.linalg.solve)."""
    return np.linalg.solve(ajj, np.eye(ajj.shape[0]))


def apply_chordcp(
    ajj_inv_corr_block: FloatArray,
    boxes: list[AeroBox],
    cp_inj: FloatArray,
    alpha_ref: float,
) -> FloatArray:
    """Equivalent-normalwash substitution for injected steady pressures (Step 54).

    Given the corrected normalwash→ΔCp operator of the VLM lifting-surface
    boxes (``ajj_inv_corr`` restricted to the VLM sub-block — the operator
    already carries the 2/chord Γ→Cp conversion, the Göthert 1/β factor and
    any WKK/WT2/WT1 correction), find the baseline normalwash ``wg_eff`` such
    that the rigid model at the injected operating point (ANGLEA = alpha_ref,
    all other trim variables zero, no structural deformation) reproduces the
    injected physical pressures ``cp_inj``:

        ajj_inv_corr @ (D_alpha·alpha_ref + wg_eff) = cp_inj,   D_alpha = -n_z

        ⟹  wg_eff = lstsq(ajj_inv_corr, cp_inj) + n_z·alpha_ref

    The ``+ n_z·alpha_ref`` term re-references the injection to alpha = 0, so
    a downstream trim solves for the ABSOLUTE angle of attack.

    A min-norm least-squares solve is used instead of a direct solve: WT2/WT1
    corrections can zero entire rows of the operator (target ratio r_k = 0),
    making it singular.  A dead row can reproduce only Cp = 0 there, so a
    nonzero injected Cp on such a row is unrepresentable — detected by the
    residual check below and raised as an error rather than silently dropped.

    Args:
        ajj_inv_corr_block: (n, n) corrected wash→ΔCp operator, VLM boxes only.
        boxes:              the n VLM AeroBox objects (same ordering).
        cp_inj:             (n,) injected physical Cp at alpha_ref.
        alpha_ref:          reference angle of attack, radians.

    Returns:
        wg_eff: (n,) equivalent baseline normalwash for these boxes.
    """
    n = ajj_inv_corr_block.shape[0]
    if len(boxes) != n or cp_inj.shape[0] != n:
        raise ValueError(
            f"apply_chordcp: size mismatch (operator {n}, boxes {len(boxes)}, "
            f"cp {cp_inj.shape[0]})"
        )
    check_conditioning(ajj_inv_corr_block)
    w_solve, *_ = np.linalg.lstsq(ajj_inv_corr_block, cp_inj, rcond=None)
    residual = ajj_inv_corr_block @ w_solve - cp_inj
    res_norm = float(np.linalg.norm(residual))
    cp_norm  = float(np.linalg.norm(cp_inj))
    if res_norm > 1e-8 * max(cp_norm, 1.0):
        bad = np.argsort(-np.abs(residual))[:5]
        raise ValueError(
            "apply_chordcp: injected Cp distribution is not reproducible by the "
            f"corrected AIC operator (residual ‖A·w − cp‖ = {res_norm:.3e}); "
            "nonzero Cp was likely injected on boxes whose correction ratio is "
            f"zero (dead rows). Worst box indices (local): {bad.tolist()}"
        )
    n_z = np.array([b.normal[2] for b in boxes])
    return w_solve + n_z * alpha_ref


def apply_wkk(
    ajj: FloatArray, wkk_data: Union[Sequence[float], FloatArray]
) -> FloatArray:
    """Diagonal multiplicative AIC correction.

    Returns AJJ* = diag(wkk_data) @ AJJ.
    Caller is responsible for inverting AJJ* — ``_assemble_vlm_operator`` uses
    ``np.linalg.solve``, which requires AJJ* to be non-singular.  A zero entry
    in ``wkk_data`` zeroes a whole row and makes it singular, so the caller
    rejects zero weights rather than letting LAPACK raise.
    """
    w = np.asarray(wkk_data, dtype=float)
    return np.diag(w) @ ajj


def apply_wt2(ajj: FloatArray, cp_target: FloatArray) -> FloatArray:
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
    check_conditioning(ajj)
    n = ajj.shape[0]
    ajj_inv = _solve_ajj(ajj)
    w_ref = -np.ones(n)
    cp_vlm_ref = ajj_inv @ w_ref
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(cp_vlm_ref != 0.0, cp_target / cp_vlm_ref, 1.0)
    r = np.where(np.abs(cp_vlm_ref) > _RATIO_TOL, ratio, 1.0)
    return np.diag(r) @ ajj_inv


def apply_wt1(ajj: FloatArray, boxes: list[AeroBox], f_target: FloatArray) -> FloatArray:
    """**DEPRECATED (DEF-H2/H3, 2026-07-31).**  Force/moment-matching correction.

    Returns corrected AJJ*⁻¹ (Γ-unit output).  Two defects make this path
    untrustworthy, and the decision taken was to **deprecate rather than fix** —
    ``WT2`` and the section-correction path (``sbeam.aero.section_correction``,
    which divides by β and is genuinely multi-surface) are correct and strictly
    more capable:

      DEF-H2  ``build_aero_model`` passes PG-compressed boxes here, so the
              reference strip force is integrated over compressed areas/chords
              while the Göthert 1/β factor and the Γ→ΔCp conversion (physical
              chords) are applied afterwards.  The delivered strip force is
              ``f_target/β²`` — a 56 % overshoot at M = 0.6.  Exact at M = 0 only.
      DEF-H3  Strips are grouped by ``box.i_span``, which restarts per parent
              CAERO1.  On a multi-surface deck a card selected for one CAERO1
              rescales strips on every surface sharing an ``i_span`` index.

    The numerics below are left unchanged on purpose; both defects are pinned by
    characterization tests in ``tests/aero/test_corrections.py``.  Removal of the
    whole path is tracked as backlog DEF-R7.

    Finds a diagonal scaling r — constant within each span strip — such that the
    corrected A*⁻¹ = diag(r) @ AJJ⁻¹ reproduces the per-strip physical lift/q
    f_target when the caller subsequently applies the 2/chord Cp-conversion step
    (build_aero_model does this).  f_target must be physical strip lift/q:

        f_target_s  = Σ_k area_k · Cp_k  for all k in strip s  (force per q)

    Internally:
        gamma_ref   = AJJ⁻¹ @ w_ref          (VLM circulation at unit incidence)
        f_vlm_s     = Σ_k area_k · 2·gamma_ref_k / chord_k   (physical reference)
        ratio_s     = f_target_s / f_vlm_s
        r_k         = ratio_s  for all boxes k in strip s

    Strips where |f_vlm_s| < _RATIO_TOL keep ratio_s = 1 (no correction applied).
    f_target must have length equal to the number of distinct i_span values in boxes,
    ordered by ascending i_span.

    Warns if cond(AJJ) > 1e10.
    """
    import math as _math
    check_conditioning(ajj)
    n = ajj.shape[0]
    ajj_inv = _solve_ajj(ajj)
    w_ref = -np.ones(n)
    gamma_ref = ajj_inv @ w_ref

    # Physical chord per box (same formula as solve_rigid_cl / build_aero_model)
    chord_box = [
        b.area / max(_math.sqrt((b.bound_b[1] - b.bound_a[1])**2
                                + (b.bound_b[2] - b.bound_a[2])**2), 1e-14)
        for b in boxes
    ]

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
        # Physical strip lift/q reference: Σ area * Cp = Σ area * 2*Γ/chord
        f_vlm_s = sum(boxes[k].area * 2.0 * gamma_ref[k] / chord_box[k] for k in idxs)
        if abs(f_vlm_s) > _RATIO_TOL:
            ratio_s = float(f_target[s_idx]) / f_vlm_s
            for k in idxs:
                r[k] = ratio_s

    return np.diag(r) @ ajj_inv
