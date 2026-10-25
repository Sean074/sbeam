"""AIC correction methods — steady (k=0) rescaling of the VLM aerodynamic influence matrix.

Two tiers, in increasing data requirement:

  Wkk   — diagonal multiplicative weighting: AJJ* = diag(w) @ AJJ.
  WT2   — pressure matching: per-box cp scaling to reproduce a target cp distribution.

A third tier, force/moment matching by per-strip lift scaling (``AECORR
METHOD=WT1``), was removed at the first SOL 144 loads release (DEF-R7): it was
deprecated by DEF-H2/H3 (2026-07-31) for delivering ``f_target/β²`` at Mach and
for aliasing strips across CAERO1s, and ``WT2`` plus the section-correction path
(``sbeam.aero.section_correction``) are correct and strictly more capable.

Reference normalwash convention (WT2) — per incidence axis (#52):
  every CAERO1 is calibrated at unit incidence on ITS OWN axis, with the other axis's
  surfaces at zero.  A surface whose boxes' dominant normal is y (a fin, a vertical body
  panel) is a β surface; every other surface is an α surface.  Box k's reference is
      cp_ref_k = (AJJ⁻¹ @ w_α)_k   for an α surface,   w_α = −1 on α boxes, 0 elsewhere
      cp_ref_k = (AJJ⁻¹ @ w_β)_k   for a β surface,    w_β = −1 on β boxes, 0 elsewhere
  (``wt2_reference_cp``).  A uniform −1 on every box, the pre-#52 rule, is a SIDESLIP on
  a vertical surface: on a deck with a fin it loaded the fin sideways in the reference,
  whose vortex system made the tailplane reference — and so every WT2 ratio there —
  port/starboard asymmetric at β = 0.  On a deck with no y-dominant surface the two rules
  coincide exactly (w_α = −ones), so such decks are unchanged.
  All corrections are relative to the VLM solution at that reference.

Return types:
  apply_wkk  →  corrected AJJ*  (caller inverts via np.linalg.solve)
  apply_wt2  →  corrected AJJ*⁻¹
"""

import warnings
from typing import Optional, Sequence, Union

import numpy as np
from scipy.linalg import lu_solve

from sbeam.aero.panel import AeroBox
from sbeam.linalg_utils import estimate_cond_1norm
from sbeam.types import FloatArray, LuFactor

_COND_WARN_THRESHOLD = 1e10
_RATIO_TOL = 1e-12   # guard for near-zero reference quantities


def check_conditioning(
    ajj: FloatArray, lu_piv: Optional[LuFactor] = None
) -> LuFactor:
    """Warn if the AIC's 1-norm condition estimate exceeds the threshold.

    LU + LAPACK ``gecon`` estimate (DEF-R6), replacing the former full-SVD
    ``np.linalg.cond``.  Returns the LU factorization of ``ajj`` so callers
    solve with it (``scipy.linalg.lu_solve``) instead of refactorizing.
    """
    cond, lu_piv = estimate_cond_1norm(ajj, lu_piv)
    if cond > _COND_WARN_THRESHOLD:
        warnings.warn(
            f"AIC matrix is poorly conditioned (1-norm condition estimate "
            f"{cond:.2e}); correction accuracy may be degraded",
            UserWarning,
            stacklevel=3,
        )
    return lu_piv


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
    any WKK/WT2 correction), find the baseline normalwash ``wg_eff`` such
    that the rigid model at the injected operating point (ANGLEA = alpha_ref,
    all other trim variables zero, no structural deformation) reproduces the
    injected physical pressures ``cp_inj``:

        ajj_inv_corr @ (D_alpha·alpha_ref + wg_eff) = cp_inj,   D_alpha = -n_z

        ⟹  wg_eff = lstsq(ajj_inv_corr, cp_inj) + n_z·alpha_ref

    The ``+ n_z·alpha_ref`` term re-references the injection to alpha = 0, so
    a downstream trim solves for the ABSOLUTE angle of attack.

    A min-norm least-squares solve is used instead of a direct solve: a WT2
    correction can zero entire rows of the operator (target ratio r_k = 0),
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


def wt2_reference_cp(boxes: Sequence[AeroBox], ajj_inv: FloatArray) -> FloatArray:
    """Per-axis WT2 reference loading (Γ-units), the single source for builder and solver.

    Each CAERO1 is assigned an axis from the mean absolute normal of its boxes: a
    y-dominant surface is a β surface, every other surface an α surface.  α surfaces
    take their reference from ``AJJ⁻¹ @ w_α`` (−1 on α boxes, 0 on β boxes), β surfaces
    from ``AJJ⁻¹ @ w_β`` — so a fin is never sideslipped by the α calibration of the
    tailplane beside it (#52).  With no β surface this is exactly ``AJJ⁻¹ @ −ones``.
    """
    n = len(boxes)
    by_surface: dict[int, list[int]] = {}
    for k, box in enumerate(boxes):
        by_surface.setdefault(box.caero_eid, []).append(k)
    is_beta = np.zeros(n, dtype=bool)
    for idxs in by_surface.values():
        mean_abs = np.mean([np.abs(boxes[k].normal) for k in idxs], axis=0)
        if mean_abs[1] > mean_abs[2]:
            is_beta[idxs] = True
    w_alpha = np.where(is_beta, 0.0, -1.0)
    cp_ref = ajj_inv @ w_alpha
    if is_beta.any():
        cp_beta = ajj_inv @ np.where(is_beta, -1.0, 0.0)
        cp_ref = np.where(is_beta, cp_beta, cp_ref)
    return np.asarray(cp_ref)


def apply_wt2(
    ajj: FloatArray, cp_target: FloatArray, ajj_inv: Optional[FloatArray] = None,
    cp_ref: Optional[FloatArray] = None,
) -> FloatArray:
    """Pressure-matching correction.  Returns corrected AJJ*⁻¹.

    Finds a diagonal scaling r such that the corrected A*⁻¹ = diag(r) @ AJJ⁻¹
    reproduces cp_target on the reference loading cp_ref:

        r_k         = cp_target_k / cp_ref_k
        A*⁻¹        = diag(r) @ AJJ⁻¹

    ``cp_ref`` is the per-axis reference from ``wt2_reference_cp`` (#52); callers with
    the box geometry must pass it.  When omitted it falls back to the uniform
    ``AJJ⁻¹ @ −ones`` — identical to the per-axis rule only when no surface is
    y-dominant (no fin), which is all a geometry-free caller can assume.

    Boxes where |cp_ref_k| < _RATIO_TOL keep r_k = 1 (no correction applied).
    ``ajj_inv`` may be supplied by a caller that already inverted AJJ (DEF-R6:
    ``_assemble_vlm_operator`` computes it for the WT2 target baseline, and its
    ``check_conditioning`` already covered the matrix); when omitted, this
    function factors and inverts AJJ itself and warns if cond(AJJ) > 1e10.
    """
    n = ajj.shape[0]
    if ajj_inv is None:
        lu_piv = check_conditioning(ajj)
        inv = np.asarray(lu_solve(lu_piv, np.eye(n)))
    else:
        inv = ajj_inv
    cp_vlm_ref = inv @ -np.ones(n) if cp_ref is None else np.asarray(cp_ref)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(cp_vlm_ref != 0.0, cp_target / cp_vlm_ref, 1.0)
    r = np.where(np.abs(cp_vlm_ref) > _RATIO_TOL, ratio, 1.0)
    return np.diag(r) @ inv
