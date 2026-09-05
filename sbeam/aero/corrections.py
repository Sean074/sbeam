"""AIC correction methods — steady (k=0) rescaling of the VLM aerodynamic influence matrix.

Two tiers, in increasing data requirement:

  Wkk   — diagonal multiplicative weighting: AJJ* = diag(w) @ AJJ.
  WT2   — pressure matching: per-box cp scaling to reproduce a target cp distribution.

A third tier, force/moment matching by per-strip lift scaling (``AECORR
METHOD=WT1``), was removed at the first SOL 144 loads release (DEF-R7): it was
deprecated by DEF-H2/H3 (2026-07-31) for delivering ``f_target/β²`` at Mach and
for aliasing strips across CAERO1s, and ``WT2`` plus the section-correction path
(``sbeam.aero.section_correction``) are correct and strictly more capable.

Reference normalwash convention (WT2):
  w_ref = -np.ones(n)  (uniform unit incidence, alpha = 1, same rhs as solve_rigid_cl).
  All corrections are relative to the VLM solution at that reference incidence.

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


def apply_wt2(
    ajj: FloatArray, cp_target: FloatArray, ajj_inv: Optional[FloatArray] = None
) -> FloatArray:
    """Pressure-matching correction.  Returns corrected AJJ*⁻¹.

    Finds a diagonal scaling r such that the corrected A*⁻¹ = diag(r) @ AJJ⁻¹
    reproduces cp_target when applied to the unit-incidence reference normalwash
    w_ref = -ones(n):

        cp_vlm_ref  = AJJ⁻¹ @ w_ref          (VLM at unit incidence)
        r_k         = cp_target_k / cp_vlm_ref_k
        A*⁻¹        = diag(r) @ AJJ⁻¹

    Boxes where |cp_vlm_ref_k| < _RATIO_TOL keep r_k = 1 (no correction applied).
    ``ajj_inv`` may be supplied by a caller that already inverted AJJ (DEF-R6:
    ``_assemble_vlm_operator`` computes it for the WT2 target baseline, and its
    ``check_conditioning`` already covered the matrix); when omitted, this
    function factors and inverts AJJ itself and warns if cond(AJJ) > 1e10.
    """
    n = ajj.shape[0]
    if ajj_inv is None:
        lu_piv = check_conditioning(ajj)
        ajj_inv = np.asarray(lu_solve(lu_piv, np.eye(n)))
    w_ref = -np.ones(n)
    cp_vlm_ref = ajj_inv @ w_ref
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(cp_vlm_ref != 0.0, cp_target / cp_vlm_ref, 1.0)
    r = np.where(np.abs(cp_vlm_ref) > _RATIO_TOL, ratio, 1.0)
    return np.diag(r) @ ajj_inv
