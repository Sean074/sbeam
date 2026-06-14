"""Section force + moment correction synthesis (Option A).

Generate a **W2GJ** baseline-normalwash card *and* a **WT2** (AECORR) AIC-correction
card per lifting surface that together reproduce a target *section* aerodynamic line —
both the slope **and** the zero-incidence offset of force and pitching moment — while
perturbing the uncorrected VLM chordwise load distribution as little as possible.

Why two cards
-------------
A linear section is fully defined by four numbers per span strip:

    F(α) = (dF/dα)·α + F₀        M(α) = (dM/dα)·α + M₀

These split into two pairs, each handled by the mechanism that can do it without
disturbing the other:

  * **slope pair** (dF/dα, dM/dα → force-curve slope *and* aerodynamic-centre):
    needs to reshape the α-driven chordwise load, so it is a per-box **WT2** ratio.
  * **offset pair** (F₀, M₀ → zero-α lift offset *and* camber pitching moment):
    is a load that exists at α=0, so it is a baseline **W2GJ** normalwash (camber line).

The two compose exactly in the existing solve: cp = (corrected A⁻¹)·(w_α + w_g), with the
WT2 ratio in the operator and W2GJ added to the normalwash.

Multi-surface
-------------
The AIC ``A_jj`` is global — every box, on every CAERO1, is aerodynamically coupled — so
the correction is built once over the whole model and emitted as a **per-surface** card
pair. The WT2 ratio ``r`` is per-box (a global diagonal whose entries are 1 on uncorrected
boxes), and the W2GJ offset is solved **globally** across all corrected strips because a
camber line on one surface induces load on the others. ``build_section_correction_multi``
is the engine; ``build_section_correction`` is the single-surface convenience wrapper.

Decoupling
----------
The WT2 ratio is calibrated on the unit-incidence reference w_ref = -1 and is therefore
independent of w_g. So the build is one pass: size WT2 from the slope pair first (per strip,
on the global reference circulation), then size W2GJ for the offset pair *through the
WT2-corrected operator* (which also scales the camber load).

Minimal change
--------------
  * WT2: per strip a uniform scale r̄ = (dF/dα)_target / (dF/dα)_VLM hits the force with
    **no shape change**; a minimum-norm per-box perturbation δ orthogonal to the force
    (Σ δ_k·g0_k = 0) supplies only the moment/a.c. mismatch. When the target a.c. equals the
    VLM a.c. (pure slope scaling) δ = 0 and the result degenerates to the uniform WT1 scaling.
  * W2GJ: a two-mode camber line per strip (uniform incidence + chordwise-linear camber).

Conventions
-----------
Per-strip target arrays are ordered by ascending ``i_span`` within each surface. Force is
the surface-normal force/q (``Σ area·Cp``; §2.9) per unit reference normalwash — exactly
``apply_wt1``'s convention. Pitching moment is **nose-up positive** about the per-strip
moment reference (default = strip ¼-chord), matching ``sol144._pitch_moment``.

The supplied ``ajj`` and ``boxes`` must be the **whole model** (full AIC); pass the AIC
calibrated at the correction Mach (the PG-consistent ``β·ajj_pg``, or M=0).
"""

import math
import warnings
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from sbeam.aero.panel import AeroBox
from sbeam.model.aero import W2gj, Aecorr

_RATIO_TOL = 1e-12   # near-zero reference circulation guard (mirrors apply_wt2)
_COND_WARN = 1e10    # ill-conditioning warning threshold


@dataclass
class SurfaceTargets:
    """Per-strip section targets for one CAERO1 (arrays length = that surface's strips)."""
    caero_eid:  int
    f_slope:    np.ndarray            # dF/dα  (force/q per rad)
    alpha_0:    np.ndarray            # zero-force angle α₀ (rad); F₀ = −f_slope·α₀
    m_slope:    np.ndarray            # dM/dα  (moment/q per rad, nose-up +)
    m_0:        np.ndarray            # M at α=0 (moment/q, nose-up +)
    moment_ref: Optional[np.ndarray] = None   # per-strip moment ref x; default ¼-chord


@dataclass
class SurfaceDiagnostics:
    """Achieved-vs-target per-strip diagnostics for one surface."""
    caero_eid:        int
    moment_ref:       np.ndarray
    achieved_f_slope: np.ndarray
    achieved_m_slope: np.ndarray
    achieved_f0:      np.ndarray
    achieved_m0:      np.ndarray


@dataclass
class MultiSectionCorrectionResult:
    """Per-surface cards + global operators + per-surface diagnostics."""
    cards:       dict                 # {caero_eid: (W2gj, Aecorr)}
    r:           np.ndarray           # global per-box WT2 multiplier (length n_box)
    wg:          np.ndarray           # global per-box W2GJ normalwash (length n_box)
    per_surface: dict = field(default_factory=dict)   # {caero_eid: SurfaceDiagnostics}


@dataclass
class SectionCorrectionResult:
    """Single-surface result (the wrapper return type); global r/wg restricted to it."""
    w2gj:             W2gj
    aecorr:           Aecorr
    r:                np.ndarray
    wg:               np.ndarray
    moment_ref:       np.ndarray
    achieved_f_slope: np.ndarray
    achieved_m_slope: np.ndarray
    achieved_f0:      np.ndarray
    achieved_m0:      np.ndarray


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


def _surface_strips(boxes: list, caero_eid: int) -> list:
    """Ordered [(i_span, [global box index,...]), ...] for one CAERO1."""
    groups: dict = {}
    for k, box in enumerate(boxes):
        if box.caero_eid == caero_eid:
            groups.setdefault(box.i_span, []).append(k)
    return [(s, groups[s]) for s in sorted(groups)]


def build_section_correction_multi(
    boxes: list,
    ajj: np.ndarray,
    targets,
    *,
    sid_w2gj_base: int,
    sid_aecorr_base: int,
    beta: float = 1.0,
) -> MultiSectionCorrectionResult:
    """Synthesise a per-surface W2GJ + WT2 card pair for one or more surfaces at once.

    Args:
        boxes:   AeroBox list for the **whole model** (mesh order; full AIC).
        ajj:     **raw PG AIC** ``ajj_pg = build_ajj(pg_boxes)`` (Γ-form), exactly as
                 ``build_aero_model`` builds it at the correction Mach. Do *not* pre-scale
                 by β — pass β separately.
        targets: iterable of SurfaceTargets, one per CAERO1 to correct.
        sid_w2gj_base / sid_aecorr_base: SIDs are assigned ``base + i`` in the order the
                 surfaces appear in ``targets``.
        beta:    Prandtl–Glauert factor √(1−M²) at the correction Mach. The physical
                 force carries the solver's 1/β scaling, while the emitted WT2 target
                 stays in pure Γ-units (what ``apply_wt2`` reconstructs from). β=1 at M=0.

    Returns:
        MultiSectionCorrectionResult with ``cards[eid] = (W2gj, Aecorr)``, the global
        per-box ``r``/``wg``, and per-surface diagnostics.

    Raises:
        ValueError: unknown surface EID, per-surface length mismatch, a strip with < 2
                    chordwise boxes, or a singular fit.
    """
    targets = list(targets)
    n = len(boxes)
    if ajj.shape != (n, n):
        raise ValueError(
            f"build_section_correction_multi: ajj is {ajj.shape}, expected ({n}, {n}) "
            "— pass the whole-model AIC and box list"
        )

    cond = float(np.linalg.cond(ajj))
    if cond > _COND_WARN:
        warnings.warn(
            f"AIC matrix is poorly conditioned (cond={cond:.2e}); "
            "section-correction accuracy may be degraded",
            UserWarning, stacklevel=2,
        )

    ajj_inv   = np.linalg.solve(ajj, np.eye(n))
    gamma_ref = ajj_inv @ (-np.ones(n))          # PG circulation (Γ-units; no 1/β)
    chord_box = np.array([_box_chord(b) for b in boxes])
    area_box  = np.array([b.area for b in boxes])
    x_box     = np.array([b.force_point[0] for b in boxes])
    # Physical per-box reference force/q carries the solver's 1/β scaling.
    g0        = area_box * 2.0 * gamma_ref / chord_box / beta

    # ------------------------------------------------------------------ WT2 slope (per box)
    r = np.ones(n)
    surface_meta = []          # (target, strips, moment_ref_array)
    for T in targets:
        strips = _surface_strips(boxes, T.caero_eid)
        if not strips:
            raise ValueError(
                f"build_section_correction: CAERO1 {T.caero_eid} has no boxes in the model"
            )
        n_strip = len(strips)
        for name, arr in (("f_slope", T.f_slope), ("alpha_0", T.alpha_0),
                          ("m_slope", T.m_slope), ("m_0", T.m_0)):
            if np.asarray(arr).shape != (n_strip,):
                raise ValueError(
                    f"build_section_correction: CAERO1 {T.caero_eid} {name} has length "
                    f"{np.asarray(arr).shape[0]}, expected one value per span strip "
                    f"({n_strip})"
                )
        if T.moment_ref is None:
            x_mref = np.array([_strip_quarter_chord_x(boxes, idxs) for _, idxs in strips])
        else:
            x_mref = np.asarray(T.moment_ref, dtype=float)
            if x_mref.shape != (n_strip,):
                raise ValueError(
                    f"build_section_correction: CAERO1 {T.caero_eid} moment_ref has length "
                    f"{x_mref.shape[0]}, expected one value per span strip ({n_strip})"
                )
        surface_meta.append((T, strips, x_mref))

        for s, (i_span, idxs) in enumerate(strips):
            if len(idxs) < 2:
                raise ValueError(
                    f"build_section_correction: CAERO1 {T.caero_eid} span strip "
                    f"i_span={i_span} has {len(idxs)} chordwise box(es); matching a "
                    "section moment needs NCHORD ≥ 2"
                )
            idx = np.array(idxs)
            arm = x_box[idx] - x_mref[s]
            a_k = g0[idx]
            b_k = -g0[idx] * arm
            F_vlm = float(a_k.sum())
            M_vlm = float(b_k.sum())
            if abs(F_vlm) > _RATIO_TOL:
                rbar = float(T.f_slope[s]) / F_vlm
            else:
                warnings.warn(
                    f"build_section_correction: CAERO1 {T.caero_eid} strip i_span={i_span} "
                    "produces ≈0 reference force; cannot scale force slope, leaving r̄=1",
                    UserWarning, stacklevel=2,
                )
                rbar = 1.0
            A = np.column_stack((a_k, b_k))
            gram = A.T @ A
            rhs = np.array([0.0, float(T.m_slope[s]) - rbar * M_vlm])
            try:
                mu = np.linalg.solve(gram, rhs)
            except np.linalg.LinAlgError:
                raise ValueError(
                    f"build_section_correction: singular force/moment fit on CAERO1 "
                    f"{T.caero_eid} strip i_span={i_span} (chordwise boxes share an x?)"
                )
            r[idx] = rbar + A @ mu

    tiny = np.abs(gamma_ref) <= _RATIO_TOL
    r[tiny] = 1.0
    cp_target = r * gamma_ref                     # Γ-units WT2 target (no 1/β)
    # Physical ΔCp operator the solver uses: diag(2r/chord)·(1/β)·AJJ⁻¹.
    b_op = (2.0 * r / chord_box / beta)[:, np.newaxis] * ajj_inv

    # ----------------------------------------------------------------- W2GJ offset (global)
    corrected = []   # (idx_array, arm, F0, M0)
    for T, strips, x_mref in surface_meta:
        for s, (_, idxs) in enumerate(strips):
            idx = np.array(idxs)
            arm = x_box[idx] - x_mref[s]
            corrected.append((idx, arm,
                              -float(T.f_slope[s]) * float(T.alpha_0[s]),
                              float(T.m_0[s])))
    n_cs = len(corrected)
    P = np.zeros((n, 2 * n_cs))
    sec = np.zeros((2 * n_cs, n))
    t = np.zeros(2 * n_cs)
    for j, (idx, arm, F0, M0) in enumerate(corrected):
        c_s = float(np.mean(chord_box[idx]))
        P[idx, 2 * j] = 1.0
        P[idx, 2 * j + 1] = arm / max(c_s, 1e-14)
        sec[2 * j,     idx] = area_box[idx]
        sec[2 * j + 1, idx] = -area_box[idx] * arm
        t[2 * j], t[2 * j + 1] = F0, M0

    g_map = sec @ b_op @ P
    if n_cs and (float(np.linalg.cond(g_map)) > 1e14):
        p_vec, *_ = np.linalg.lstsq(g_map, t, rcond=None)
    else:
        p_vec = np.linalg.solve(g_map, t) if n_cs else np.zeros(0)
    wg = P @ p_vec if n_cs else np.zeros(n)

    # ----------------------------------------------------------- emit cards + diagnostics
    cp_off = b_op @ wg
    fbox_off = area_box * cp_off
    cards: dict = {}
    per_surface: dict = {}
    for i, (T, strips, x_mref) in enumerate(surface_meta):
        n_strip = len(strips)
        af = np.zeros(n_strip); am = np.zeros(n_strip)
        af0 = np.zeros(n_strip); am0 = np.zeros(n_strip)
        for s, (_, idxs) in enumerate(strips):
            idx = np.array(idxs)
            arm = x_box[idx] - x_mref[s]
            af[s]  = float((r[idx] * g0[idx]).sum())
            am[s]  = float((-(r[idx] * g0[idx]) * arm).sum())
            af0[s] = float(fbox_off[idx].sum())
            am0[s] = float((-fbox_off[idx] * arm).sum())
        surf_idx = [k for k, b in enumerate(boxes) if b.caero_eid == T.caero_eid]
        w2 = W2gj(sid=sid_w2gj_base + i, caero_eid=T.caero_eid,
                  data=wg[surf_idx].tolist())
        ac = Aecorr(sid=sid_aecorr_base + i, method="WT2", caero_eid=T.caero_eid,
                    target=cp_target[surf_idx].tolist())
        cards[T.caero_eid] = (w2, ac)
        per_surface[T.caero_eid] = SurfaceDiagnostics(
            caero_eid=T.caero_eid, moment_ref=x_mref,
            achieved_f_slope=af, achieved_m_slope=am,
            achieved_f0=af0, achieved_m0=am0,
        )

    return MultiSectionCorrectionResult(cards=cards, r=r, wg=wg, per_surface=per_surface)


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
    beta: float = 1.0,
) -> SectionCorrectionResult:
    """Single-surface convenience wrapper around ``build_section_correction_multi``.

    Requires ``boxes`` to contain exactly one CAERO1 (the whole AIC). For multi-surface
    models call ``build_section_correction_multi`` with one ``SurfaceTargets`` per surface.
    ``beta`` is the Prandtl–Glauert factor at the correction Mach (see the multi engine).
    """
    eids = {b.caero_eid for b in boxes}
    if len(eids) != 1:
        raise ValueError(
            "build_section_correction targets a single surface "
            f"(boxes span CAERO1 {sorted(eids)}); use build_section_correction_multi "
            "for multiple surfaces."
        )
    if caero_eid not in eids:
        raise ValueError(
            f"build_section_correction: caero_eid {caero_eid} not in boxes {sorted(eids)}"
        )
    tgt = SurfaceTargets(
        caero_eid=caero_eid,
        f_slope=np.asarray(f_slope, dtype=float),
        alpha_0=np.asarray(alpha_0, dtype=float),
        m_slope=np.asarray(m_slope, dtype=float),
        m_0=np.asarray(m_0, dtype=float),
        moment_ref=None if moment_ref is None else np.asarray(moment_ref, dtype=float),
    )
    multi = build_section_correction_multi(
        boxes, ajj, [tgt], sid_w2gj_base=sid_w2gj, sid_aecorr_base=sid_aecorr, beta=beta,
    )
    w2, ac = multi.cards[caero_eid]
    d = multi.per_surface[caero_eid]
    return SectionCorrectionResult(
        w2gj=w2, aecorr=ac, r=multi.r, wg=multi.wg, moment_ref=d.moment_ref,
        achieved_f_slope=d.achieved_f_slope, achieved_m_slope=d.achieved_m_slope,
        achieved_f0=d.achieved_f0, achieved_m0=d.achieved_m0,
    )


def _card_lines(name: str, head: list, values: list) -> str:
    """Free-field BDF card text: head fields then 8 values/line, '+'-continued."""
    fields = [name] + [str(h) for h in head]
    line = fields[:]
    first_cap = max(0, 8 - len(head))
    line += [f"{v:.6E}" for v in values[:first_cap]]
    out = [", ".join(line)]
    rest = values[first_cap:]
    for i in range(0, len(rest), 8):
        out.append(", ".join(["+"] + [f"{v:.6E}" for v in rest[i:i + 8]]))
    return "\n".join(out)


def _pair_to_bdf(w2: W2gj, ac: Aecorr) -> str:
    return (f"{_card_lines('W2GJ', [w2.sid, w2.caero_eid], w2.data)}\n"
            f"{_card_lines('AECORR', [ac.sid, ac.method, ac.caero_eid], ac.target)}\n")


def cards_to_bdf(result) -> str:
    """Format the generated W2GJ + AECORR(WT2) cards as bulk-data text.

    Accepts a single-surface ``SectionCorrectionResult`` or a multi-surface
    ``MultiSectionCorrectionResult`` (all surfaces concatenated).
    """
    header = "$ Section force+moment correction (W2GJ camber offset + WT2 slope/a.c.)\n"
    if isinstance(result, MultiSectionCorrectionResult):
        body = "".join(_pair_to_bdf(w2, ac)
                       for _, (w2, ac) in sorted(result.cards.items()))
    else:
        body = _pair_to_bdf(result.w2gj, result.aecorr)
    return header + body
