"""Section force + moment correction synthesis (Option A).

Generate a **W2GJ** baseline-normalwash card *and* a **WT2** (AECORR) AIC-correction
card that together reproduce a target *section* aerodynamic line — both the slope
**and** the zero-incidence offset of force and pitching moment — while perturbing the
uncorrected VLM chordwise load distribution as little as possible.

Why two cards
-------------
A linear section is fully defined by four numbers per span strip:

    F(α) = (dF/dα)·α + F₀        M(α) = (dM/dα)·α + M₀

These split into two pairs, each handled by the mechanism that can do it without
disturbing the rest (see corrections.py and the turn-by-turn analysis in
docs/20_theory/01_aeroelastics_theory.md §3):

  * **slope pair** (dF/dα, dM/dα → force-curve slope *and* aerodynamic-centre):
    needs to reshape the α-driven chordwise load, so it is a per-box **WT2** ratio.
  * **offset pair** (F₀, M₀ → zero-α lift offset *and* camber pitching moment):
    is a load that exists at α=0, so it is a baseline **W2GJ** normalwash (camber
    line). A pure WT2/WT1 correction is multiplicative about the unit-incidence
    reference and produces nothing at α=0, so the offset *must* come from W2GJ.

The two compose exactly in the existing solve: cp = (corrected A⁻¹)·(w_α + w_g),
with the WT2 ratio in the operator and W2GJ added to the normalwash
(aero_model.build_aero_model / compute_structural_loads).

Decoupling
----------
The WT2 ratio is calibrated on the unit-incidence reference w_ref = -1 (the same
reference apply_wt2/apply_wt1 use) and is therefore independent of w_g. So the build
is one pass: size WT2 from the slope pair first, then size W2GJ for the offset pair
*through the WT2-corrected operator* (which also scales the camber load).

Minimal change
--------------
  * WT2: per strip a uniform scale r̄ = (dF/dα)_target / (dF/dα)_VLM hits the force
    with **no shape change**; a minimum-norm per-box perturbation δ (orthogonal to the
    force, i.e. Σ δ_k·g0_k = 0) supplies only the moment/a.c. mismatch. When the target
    a.c. equals the VLM a.c. (pure slope scaling) δ = 0 and the result degenerates to
    the uniform WT1 scaling — i.e. the chordwise distribution is untouched.
  * W2GJ: a two-mode camber line per strip (uniform incidence + chordwise-linear
    camber) — the lowest-order shape that can set F₀ and M₀.

Conventions
-----------
All per-strip target arrays are ordered by ascending ``i_span`` (the same order as
``apply_wt1``'s ``f_target``).  Force is the surface-normal force/q (``Σ area·Cp``;
§2.9), i.e. *per unit reference normalwash* — exactly ``apply_wt1``'s convention:
per rad of α for a horizontal surface, per rad of β for a vertical surface, per
(α·cosΓ) for a surface canted at dihedral Γ.  Pitching moment is **nose-up positive**
about the per-strip moment reference (default = strip ¼-chord), matching
``sol144._pitch_moment``: M = −Σ Fₙ·(x − x_ref).

Single-surface only: like the existing WT2/WT1 path (apply_wt2 takes a full-length
cp_target), this targets one CAERO1 whose boxes are the whole AIC.  The supplied
``ajj`` must be calibrated at the correction Mach (pass the same compressed AIC the
solver will use, or build at M=0).
"""

import math
import warnings
from dataclasses import dataclass

import numpy as np

from sbeam.aero.panel import AeroBox
from sbeam.model.aero import W2gj, Aecorr

_RATIO_TOL = 1e-12   # near-zero reference circulation guard (mirrors apply_wt2)
_COND_WARN = 1e10    # ill-conditioning warning threshold


@dataclass
class SectionCorrectionResult:
    """Generated cards plus per-strip diagnostics (achieved vs. target)."""
    w2gj:             W2gj
    aecorr:           Aecorr
    r:                np.ndarray   # per-box WT2 multiplier (length n_box)
    wg:               np.ndarray   # per-box W2GJ normalwash  (length n_box)
    moment_ref:       np.ndarray   # per-strip moment reference x used (length n_strip)
    achieved_f_slope: np.ndarray   # per-strip dF/dα reproduced by the cards
    achieved_m_slope: np.ndarray   # per-strip dM/dα reproduced (nose-up +)
    achieved_f0:      np.ndarray   # per-strip F at α=0 reproduced
    achieved_m0:      np.ndarray   # per-strip M at α=0 reproduced (nose-up +)


def _box_chord(box: AeroBox) -> float:
    """Physical VLM box chord = area / projected spanwise width (apply_wt1 formula)."""
    dy = math.sqrt((box.bound_b[1] - box.bound_a[1]) ** 2
                   + (box.bound_b[2] - box.bound_a[2]) ** 2)
    return box.area / max(dy, 1e-14)


def _strip_quarter_chord_x(boxes: list, idxs: list) -> float:
    """Default per-strip moment reference: strip leading-edge x + ¼ strip chord."""
    le = min(min(boxes[k].corners[0][0], boxes[k].corners[1][0]) for k in idxs)
    te = max(max(boxes[k].corners[2][0], boxes[k].corners[3][0]) for k in idxs)
    return le + 0.25 * (te - le)


def _strip_groups(boxes: list) -> list:
    """Ordered [(i_span, [box-index,...]), ...] for a single-CAERO1 box list."""
    eids = {b.caero_eid for b in boxes}
    if len(eids) != 1:
        raise ValueError(
            "build_section_correction: multiple CAERO1 surfaces present "
            f"(eids={sorted(eids)}); this builder targets a single surface, "
            "matching the existing WT2 path. Build per surface."
        )
    groups: dict = {}
    for k, box in enumerate(boxes):
        groups.setdefault(box.i_span, []).append(k)
    return [(s, groups[s]) for s in sorted(groups)]


def build_section_correction(
    boxes: list,
    ajj: np.ndarray,
    *,
    f_slope,
    alpha_0,
    m_slope,
    m_0,
    caero_eid: int,
    sid_w2gj: int,
    sid_aecorr: int,
    moment_ref=None,
) -> SectionCorrectionResult:
    """Synthesise W2GJ + WT2 cards reproducing per-strip section force AND moment.

    Args:
        boxes:      AeroBox list for one CAERO1, in mesh (row-major) order.
        ajj:        raw VLM AIC for those boxes (Γ-form: Γ = AJJ⁻¹·w).
        f_slope:    per-strip section normal-force slope dF/dα (force/q per rad).
        alpha_0:    per-strip zero-normal-force angle α₀ (rad). F at α=0 is
                    F₀ = −f_slope·α₀ (cambered section: α₀ ≠ 0).
        m_slope:    per-strip pitch-moment slope dM/dα (moment/q per rad, nose-up +).
        m_0:        per-strip pitch moment at α=0 (moment/q, nose-up +) — Cm0-like.
        caero_eid:  CAERO1 EID the generated cards apply to.
        sid_w2gj:   SID for the emitted W2GJ card.
        sid_aecorr: SID for the emitted AECORR (WT2) card.
        moment_ref: optional per-strip moment reference x (CID 0). Default =
                    each strip's ¼-chord.

    Returns:
        SectionCorrectionResult with the two cards and achieved-vs-target diagnostics.

    Raises:
        ValueError: on multi-surface input, length mismatch, a strip with < 2
                    chordwise boxes (a moment needs ≥ 2), or a singular fit.
    """
    n = len(boxes)
    strips = _strip_groups(boxes)
    n_strip = len(strips)

    f_slope = np.asarray(f_slope, dtype=float)
    alpha_0 = np.asarray(alpha_0, dtype=float)
    m_slope = np.asarray(m_slope, dtype=float)
    m_0     = np.asarray(m_0,     dtype=float)
    for name, arr in (("f_slope", f_slope), ("alpha_0", alpha_0),
                      ("m_slope", m_slope), ("m_0", m_0)):
        if arr.shape != (n_strip,):
            raise ValueError(
                f"build_section_correction: {name} has length {arr.shape[0]}, "
                f"expected one value per span strip ({n_strip})"
            )

    if moment_ref is None:
        x_mref = np.array([_strip_quarter_chord_x(boxes, idxs) for _, idxs in strips])
    else:
        x_mref = np.asarray(moment_ref, dtype=float)
        if x_mref.shape != (n_strip,):
            raise ValueError(
                f"build_section_correction: moment_ref has length {x_mref.shape[0]}, "
                f"expected one value per span strip ({n_strip})"
            )

    cond = float(np.linalg.cond(ajj))
    if cond > _COND_WARN:
        warnings.warn(
            f"AIC matrix is poorly conditioned (cond={cond:.2e}); "
            "section-correction accuracy may be degraded",
            UserWarning, stacklevel=2,
        )

    ajj_inv   = np.linalg.solve(ajj, np.eye(n))
    gamma_ref = ajj_inv @ (-np.ones(n))            # unit-incidence reference circulation
    chord_box = np.array([_box_chord(b) for b in boxes])
    area_box  = np.array([b.area for b in boxes])
    x_box     = np.array([b.force_point[0] for b in boxes])   # box ¼-chord x (force pt)

    # Per-box reference surface-normal force/q (= per-rad slope contribution).
    g0 = area_box * 2.0 * gamma_ref / chord_box

    # ------------------------------------------------------------------ WT2 slope
    # Per strip: uniform scale for the force (no shape change) + minimum-norm
    # perturbation orthogonal to the force for the a.c./moment mismatch.
    r = np.ones(n)
    f0_slope_vlm = np.zeros(n_strip)
    m0_slope_vlm = np.zeros(n_strip)
    for s, (_, idxs) in enumerate(strips):
        if len(idxs) < 2:
            raise ValueError(
                f"build_section_correction: span strip i_span={strips[s][0]} has "
                f"{len(idxs)} chordwise box(es); matching a section moment needs "
                "NCHORD ≥ 2"
            )
        idx = np.array(idxs)
        arm = x_box[idx] - x_mref[s]
        a_k = g0[idx]                  # force coefficients
        b_k = -g0[idx] * arm           # nose-up moment coefficients
        F_vlm = float(a_k.sum())
        M_vlm = float(b_k.sum())
        f0_slope_vlm[s] = F_vlm
        m0_slope_vlm[s] = M_vlm

        if abs(F_vlm) > _RATIO_TOL:
            rbar = float(f_slope[s]) / F_vlm
        else:
            warnings.warn(
                f"build_section_correction: strip i_span={strips[s][0]} produces "
                "≈0 reference force; cannot scale force slope, leaving r̄=1",
                UserWarning, stacklevel=2,
            )
            rbar = 1.0

        # δ minimises ‖δ‖ s.t. Σδ·a = 0 (force unchanged) and
        #                       Σδ·b = m_slope − r̄·M_vlm (moment residual).
        A = np.column_stack((a_k, b_k))             # (len(idx), 2)
        gram = A.T @ A
        rhs = np.array([0.0, float(m_slope[s]) - rbar * M_vlm])
        try:
            mu = np.linalg.solve(gram, rhs)
        except np.linalg.LinAlgError:
            raise ValueError(
                f"build_section_correction: singular force/moment fit on strip "
                f"i_span={strips[s][0]} (chordwise boxes share an x-station?)"
            )
        r[idx] = rbar + A @ mu

    # Mirror apply_wt2's near-zero-reference guard so the emitted card and the
    # operator used below are identical (apply_wt2 keeps r=1 where |Γ_ref|<tol).
    tiny = np.abs(gamma_ref) <= _RATIO_TOL
    r[tiny] = 1.0
    cp_target = r * gamma_ref            # WT2 target is in Γ-units (apply_wt2 convention)

    # ΔCp operator the solver will use: diag(2r/chord) · AJJ⁻¹  (== ajj_inv_corr).
    b_op = (2.0 * r / chord_box)[:, np.newaxis] * ajj_inv

    # ----------------------------------------------------------------- W2GJ offset
    # Two-mode camber per strip: wg = a_s·1 + b_s·ξ  (ξ = (x − x_ref)/chord).
    # Solve the (2·n_strip) linear system so the WT2-corrected operator reproduces
    # (F₀, M₀) per strip exactly (global, accounts for inter-strip induction).
    P = np.zeros((n, 2 * n_strip))
    sec = np.zeros((2 * n_strip, n))     # rows: [F_s, M_s] interleaved per strip
    f0_target = -f_slope * alpha_0
    t = np.zeros(2 * n_strip)
    for s, (_, idxs) in enumerate(strips):
        idx = np.array(idxs)
        arm = x_box[idx] - x_mref[s]
        c_s = float(np.mean([chord_box[k] for k in idxs]))
        P[idx, 2 * s] = 1.0
        P[idx, 2 * s + 1] = arm / max(c_s, 1e-14)
        sec[2 * s,     idx] = area_box[idx]          # section force row
        sec[2 * s + 1, idx] = -area_box[idx] * arm   # section nose-up moment row
        t[2 * s]     = f0_target[s]
        t[2 * s + 1] = m_0[s]

    g_map = sec @ b_op @ P               # (2 n_strip, 2 n_strip)
    if abs(float(np.linalg.det(g_map))) < 1e-300 or float(np.linalg.cond(g_map)) > 1e14:
        # Fall back to least squares rather than fail outright.
        p_vec, *_ = np.linalg.lstsq(g_map, t, rcond=None)
    else:
        p_vec = np.linalg.solve(g_map, t)
    wg = P @ p_vec

    # ------------------------------------------------------------- diagnostics
    cp_off = b_op @ wg                   # ΔCp at α=0 from the camber line
    fbox_off = area_box * cp_off
    ach_f_slope = np.zeros(n_strip)
    ach_m_slope = np.zeros(n_strip)
    ach_f0      = np.zeros(n_strip)
    ach_m0      = np.zeros(n_strip)
    for s, (_, idxs) in enumerate(strips):
        idx = np.array(idxs)
        arm = x_box[idx] - x_mref[s]
        ach_f_slope[s] = float((r[idx] * g0[idx]).sum())
        ach_m_slope[s] = float((-(r[idx] * g0[idx]) * arm).sum())
        ach_f0[s]      = float(fbox_off[idx].sum())
        ach_m0[s]      = float((-fbox_off[idx] * arm).sum())

    w2gj_card   = W2gj(sid=sid_w2gj, caero_eid=caero_eid, data=wg.tolist())
    aecorr_card = Aecorr(sid=sid_aecorr, method="WT2", caero_eid=caero_eid,
                         target=cp_target.tolist())

    return SectionCorrectionResult(
        w2gj=w2gj_card,
        aecorr=aecorr_card,
        r=r,
        wg=wg,
        moment_ref=x_mref,
        achieved_f_slope=ach_f_slope,
        achieved_m_slope=ach_m_slope,
        achieved_f0=ach_f0,
        achieved_m0=ach_m0,
    )


def _card_lines(name: str, head: list, values: list) -> str:
    """Free-field BDF card text: head fields then 8 values/line, '+'-continued."""
    fields = [name] + [str(h) for h in head]
    out, line = [], fields[:]
    # first line carries head + up to (8 - len(head)) values
    first_cap = max(0, 8 - len(head))
    line += [f"{v:.6E}" for v in values[:first_cap]]
    out.append(", ".join(line))
    rest = values[first_cap:]
    for i in range(0, len(rest), 8):
        out.append(", ".join(["+"] + [f"{v:.6E}" for v in rest[i:i + 8]]))
    return "\n".join(out)


def cards_to_bdf(result: SectionCorrectionResult) -> str:
    """Format the generated W2GJ + AECORR(WT2) cards as bulk-data text."""
    w2 = result.w2gj
    ac = result.aecorr
    w2gj_txt = _card_lines("W2GJ", [w2.sid, w2.caero_eid], w2.data)
    aecorr_txt = _card_lines("AECORR", [ac.sid, ac.method, ac.caero_eid], ac.target)
    return (
        "$ Section force+moment correction (W2GJ camber offset + WT2 slope/a.c.)\n"
        f"{w2gj_txt}\n"
        f"{aecorr_txt}\n"
    )
