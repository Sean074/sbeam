"""Total-aircraft moment correction via cruciform body panels.

sbeam's VLM has no body/slender-body element, so a flat-panel airplane built only
from wing + tails gets the **overall pitching moment Cm and yawing moment Cn** wrong
(it misses fuselage lift carry-through, cross-flow, and the body's contribution to
static margin / directional stability).  The fix is the classic **cruciform**: two
crossing flat VLM surfaces standing in for the fuselage —

  * a **horizontal body panel** (XY plane, normal ≈ +Z) carrying the body's
    lift / pitch;
  * a **vertical body panel** (XZ plane, normal ≈ +Y) carrying side-force / yaw.

The correction is **two-stage**:

  1. The flying surfaces (wing/HTP/VTP) are matched to spanwise section data
     (``sbeam.aero.section_data`` → ``sbeam.aero.section_correction``).
  2. The body panels then absorb the **residual** so the **total airplane**
     Cm_α, Cm0 (pitch, horizontal panel) and Cn_β, Cn0, Cl_β, Cl0 (the sideslip yaw +
     roll set, vertical panel) match CFD/wind tunnel.  This module is stage 2.

Method (moment-primary, direct linear solve)
--------------------------------------------
The body panels are tuned to match the total **moments**; their lift / side-force is
left at the bare VLM value (a minimum-norm by-product).  The body correction is two
mechanisms, solved in an order that decouples them exactly:

  * **slope — WT2 per-box ratio ``r``.**  The corrected operator is ``diag(r)·A⁻¹``,
    so a body-box ratio scales *only that box's* Cp: the body's slope contribution is
    **linear and decoupled** from the flying surfaces.  The horizontal panel matches
    Cm_α (one scalar min-norm); the vertical panel matches Cn_β **and** Cl_β together (a
    2-constraint min-norm — it has the chordwise x-spread for the yaw arm and the
    spanwise z-spread for the roll arm).  Force is held at the bare VLM value.

  * **offset — W2GJ baseline normalwash ``wg``.**  ``wg`` enters *before* the inverse
    (``cp = A⁻¹·wg``), so body camber induces load on the wing/tail too — and for a
    long body panel under the wing that induced load dominates the body's own.  We
    therefore solve the offset against the **actual corrected operator** (with the
    slope ``r`` already baked in): Cm0, Cn0 and Cl0 are linear functionals of ``wg``
    over the body boxes, so one joint minimum-norm least-squares hits all offset targets
    exactly — the wing induction is accounted for, not fought.

Because the slope is fixed before the offset is solved and the offset does not feed
back into the slope (the slope metric is ``wg``-free), the build is **non-iterative
and exact**.  The vertical panel relies on ``n_z = 0`` (planar in XZ) for clean
pitch/roll separation; matching Cl_β needs enough spanwise (z) resolution on it.

The body cards are ordinary ``W2gj`` / ``Aecorr`` (WT2) cards on the body CAERO1 EIDs;
``build_aero_model`` composes them with the flying-surface cards unchanged.

Geometry, the WT2 ratio, and the cruciform's limits
---------------------------------------------------
The body panels should be held **clear of the lifting surfaces** — a body box that
overlaps (or trails its +X wake through) the wing/HTP/VTP dumps a spurious load onto
those surfaces, which is the very interaction the cruciform is meant to substitute for.
Keeping the panels clear has a consequence worth understanding:

  * **A large WT2 ratio is expected and benign for clear-of-tail panels.**  Held away
    from the lifting surfaces the panels are weakly coupled to the flow, so their bare
    response per box is small and the slope solve scales it up (``ratio_max`` of tens to
    a few hundred is normal).  This does **not** contaminate the real surfaces: WT2 is a
    post-inverse diagonal on the *body rows only* (``diag(r)·A⁻¹``), so it never changes
    the lifting-surface operator rows — verified by the decoupling test.  The resulting
    body-box ΔCp stays of the same order as the real surfaces (the bare value it scales
    is tiny).  Do **not** chase a low ratio by enlarging the panels: bigger/closer panels
    lower the ratio but *raise* the spurious field they shed on the wing/tail.

  * **The flat-plate cruciform can only legitimately supply a SMALL body increment.**  A
    flat plate aft of the moment reference makes a *stabilising* (nose-down) bare pitch —
    the wrong sign for a fuselage — so a large destabilising target is only reachable by
    immersing the panels in the tail (spurious) or with an extreme correction.  Use it
    for a mild dCm/dα, dCn/dβ and ~0 roll increment; large body effects (a several-MAC
    neutral-point shift, strong wing-body interference) need a true slender-body element
    (backlog: "Body aerodynamic panels (slender body / CAERO2)").  ``ratio_max`` past
    ``RATIO_WARN`` is the flag that the targets have crossed that line.

  * **A plane may be one panel or several.**  ``horiz_eid`` / ``vert_eid`` each accept a
    list of CAERO1 EIDs, so a body side can be split into pieces (e.g. one short panel
    by the wing, one running to the fin TE, one for the lower body) and the horizontal
    plane likewise.  All listed panels are tuned by **one** joint min-norm solve over
    every body box — the per-box weights route each box to pitch (n_z≠0) or yaw/roll
    (n_y≠0), so no per-panel bookkeeping is needed.  Splitting a plane across more boxes
    gives the solve more freedom: it generally **lowers** ``ratio_max`` and spreads the
    correction load, and lets the body follow the fuselage shape.  (Placement caveat from
    the first bullet still applies to every piece — keep them clear of the lifting
    surfaces; a piece that overlaps the wing/fin contaminates it, it does not model
    interference.)
"""

import warnings
from dataclasses import dataclass
from typing import Iterable, Optional, Union, cast

import numpy as np
import pandas as pd

from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.model.bulk_data import BulkData
from sbeam.types import FloatArray
from sbeam.aero.integration import build_djx
from sbeam.aero.strip import is_strip_caero, strip_box_slopes
from sbeam.assembly.coord_transform import get_transform
from sbeam.model.aero import Aecorr, Stripk, W2gj, require_aeros
from sbeam.solver.sol144_derivs import compute_rigid_derivs
from sbeam.solver.sol144_util import pitch_moment, aero_moment_resultant

# Warn only on a genuinely extreme WT2 ratio.  For body panels held clear of the
# lifting surfaces a ratio of tens to ~100 is normal and benign (the panels are weakly
# coupled; WT2 scales body-box pressure only and does not touch the real surfaces — see
# the module docstring).  Past this bound the flat-plate cruciform is being pushed beyond
# what it can represent and a slender-body element is the proper tool.
RATIO_WARN = 200.0


@dataclass
class BodyTargets:
    """Total-aircraft moment targets (about the AEROS RCSID reference).

    Pitch (Cm) is matched by the horizontal panel; yaw (Cn) and roll (Cl), both
    sideslip-driven, by the vertical panel.
    """
    cm_alpha: float = 0.0   # dCm/dα   (nose-up +, per rad)
    cm0:      float = 0.0   # Cm at α=0
    cn_beta:  float = 0.0   # dCn/dβ   (per rad)
    cn0:      float = 0.0   # Cn at β=0
    cl_beta:  float = 0.0   # dCl/dβ   (per rad — dihedral effect)
    cl0:      float = 0.0   # Cl at β=0


@dataclass
class BodyCorrectionResult:
    """Body-panel cards + achieved-vs-target diagnostics."""
    # Cruciform builds pair the W2GJ with an AECORR (WT2 ratios); the strip-body
    # builder pairs it with a STRIPK (per-box slopes) instead.
    cards:      dict[int, tuple[W2gj, Union[Aecorr, Stripk]]]
    target:     BodyTargets
    achieved:   BodyTargets   # total airplane after the body correction
    baseline:   BodyTargets   # total airplane before the body correction (flying only)
    residual:   dict[str, float]   # keyed by the BodyTargets field names
    converged:  bool
    ratio_max:  float         # max |WT2 ratio| over the body boxes


def body_cards_to_bdf(result: "BodyCorrectionResult") -> str:
    """Format the body-panel W2GJ + AECORR(WT2) cards as bulk-data text."""
    from sbeam.aero.section_correction import pair_to_bdf
    header = "$ Cruciform body-panel total-aircraft moment correction (W2GJ + WT2)\n"
    body = "".join(pair_to_bdf(w2, ac)
                   for _eid, (w2, ac) in sorted(result.cards.items())
                   if isinstance(ac, Aecorr))
    return header + body


def split_total_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a section-data table into (flying_rows, total_rows).

    A ``TOTAL`` block carries the total-aircraft CFD/WT targets for the body
    correction; the flying rows feed the ordinary section-correction pipeline (which
    only accepts ``var`` in {ALPHA, BETA}).  Returns two DataFrames; the total block
    may be empty.
    """
    var = df["var"].astype(str).str.upper()
    is_total = var == "TOTAL"
    # cast: boolean-mask selection on a DataFrame is always a DataFrame.
    return (cast(pd.DataFrame, df[~is_total]).copy(),
            cast(pd.DataFrame, df[is_total]).copy())


def parse_body_targets(
    df: pd.DataFrame, mach: float, mach_tol: float = 1e-6
) -> Optional[BodyTargets]:
    """Read the ``TOTAL`` block of a section-data table into :class:`BodyTargets`.

    Column mapping (reusing the section-data schema): ``cm_a``→Cm_α, ``cm0``→Cm0,
    ``cn_a``→Cn_β, ``a0``→Cn0; optional roll columns ``cl_a``→Cl_β, ``cl0``→Cl0 (default
    0 when absent).  Selects the row at ``mach`` (exact within ``mach_tol``).  Returns
    ``None`` if no TOTAL row matches.

    Raises:
        ValueError: if a *required* TOTAL column is blank/NaN.  The optional roll
            columns degrade to 0.0 by design; the required four used to go
            through a bare ``float()``, so a blank cell became a silent ``nan``
            that propagated into the min-norm solve (DEF-L1).
    """
    _flying, totals = split_total_rows(df)
    if totals.empty:
        return None
    hit = totals[np.isclose(totals["mach"].astype(float), mach, atol=mach_tol)]
    if hit.empty:
        return None
    r = hit.iloc[0]

    def _opt(col: str) -> float:
        v = r.get(col)
        return 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)

    def _req(col: str) -> float:
        v = r.get(col)
        if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
            raise ValueError(
                f"body targets: TOTAL row at mach={mach:g} has a blank/non-numeric "
                f"{col!r}.  cm_a, cm0, cn_a and a0 are required (only the roll "
                "columns cl_a/cl0 default to 0)."
            )
        return float(v)

    return BodyTargets(
        cm_alpha=_req("cm_a"), cm0=_req("cm0"),
        cn_beta=_req("cn_a"), cn0=_req("a0"),
        cl_beta=_opt("cl_a"), cl0=_opt("cl0"),
    )


def _ref_geometry(bulk: BulkData) -> tuple[float, FloatArray]:
    """Moment reference (x_ref, ref_pt) from the AEROS RCSID (basic if 0)."""
    aeros = require_aeros(bulk)
    if aeros.rcsid:
        ref_pt, _R = get_transform(aeros.rcsid, bulk.cord2rs)
        return float(ref_pt[0]), np.asarray(ref_pt, dtype=float)
    return 0.0, np.zeros(3)


def _total_metrics(
    aero: AeroModel, bulk: BulkData, d_jx: FloatArray, labels: list[str],
    x_ref: float, ref_pt: FloatArray,
) -> BodyTargets:
    """Total-aircraft Cm_α, Cm0, Cn_β, Cn0 for the current corrected model.

    Slopes reuse the SOL 144 rigid-derivative integration; offsets integrate the
    baseline normalwash ``aero.wg`` (which already accumulates every W2GJ, body
    panels included once their cards are applied).
    """
    sref, cref, bref = require_aeros(bulk).sref, require_aeros(bulk).cref, require_aeros(bulk).bref
    derivs = compute_rigid_derivs(aero, d_jx, labels, bulk, x_ref, ref_pt)
    n = len(aero.boxes)
    f_box0 = aero.skj @ (aero.ajj_inv_corr @ aero.wg)
    cm0 = pitch_moment(f_box0, aero.boxes, x_ref) / (sref * cref)
    mx0, _my0, mz0 = aero_moment_resultant(f_box0.reshape(n, 3), aero.boxes, ref_pt)
    cn0 = mz0 / (sref * bref) if bref > 0 else 0.0
    cl0 = mx0 / (sref * bref) if bref > 0 else 0.0
    return BodyTargets(
        cm_alpha=derivs["ANGLEA"]["CMY"], cm0=cm0,
        cn_beta=derivs["SIDES"]["CMZ"], cn0=cn0,
        cl_beta=derivs["SIDES"]["CMX"], cl0=cl0,
    )


def _as_eid_list(x: Optional[Union[int, Iterable[int]]]) -> list[int]:
    """Normalise an EID argument (``None`` | ``int`` | iterable of ``int``) to a list.

    Lets a body plane be defined by **one or many** CAERO1s — e.g. a fuselage whose
    side is split into several vertical panels (one short, one to the fin TE, one for
    the lower body).  The joint min-norm solve treats all body boxes as one set, so any
    number of panels per plane is matched together (see the module docstring).
    """
    if x is None:
        return []
    if isinstance(x, int):
        return [int(x)]
    return [int(e) for e in x]


def _body_panel_geometry(
    bulk: BulkData, aero0: AeroModel,
) -> tuple[list, int, FloatArray, BodyTargets, FloatArray, FloatArray, FloatArray,
           FloatArray, FloatArray, FloatArray]:
    """Shared body-builder prelude (DEF-R4): baseline metrics, per-box geometry,
    moment weight rows and the corrected unit α/β responses.

    Returns:
        (boxes, n, d_jx, baseline, w_pitch, w_yaw, w_roll, a_base, cp_a, cp_b)
    """
    boxes = aero0.boxes
    n = len(boxes)
    sref, cref, bref = require_aeros(bulk).sref, require_aeros(bulk).cref, require_aeros(bulk).bref

    labels = ["ANGLEA", "SIDES"]
    d_jx = build_djx(boxes, labels, bulk)
    x_ref, ref_pt = _ref_geometry(bulk)
    baseline = _total_metrics(aero0, bulk, d_jx, labels, x_ref, ref_pt)

    # Per-box geometry (force point = ¼-chord bound-vortex midpoint, AE6).
    xfp = np.array([b.force_point[0] for b in boxes])
    yfp = np.array([b.force_point[1] for b in boxes])
    zfp = np.array([b.force_point[2] for b in boxes])
    area = np.array([b.area for b in boxes])
    nrm = np.array([b.normal for b in boxes])
    nx, ny, nz = nrm[:, 0], nrm[:, 1], nrm[:, 2]

    # Moment "weight" rows so that C = w·cp (cp = per-box ΔCp): pitch My, yaw Mz, roll Mx
    # (the resultant M = Σ(r−ref)×F, with F = area·n̂·cp).
    arm_x = xfp - x_ref
    arm_y = yfp - ref_pt[1]
    arm_z = zfp - ref_pt[2]
    w_pitch = -(arm_x * area * nz) / (sref * cref)            # cm = w_pitch·cp
    if bref > 0:
        w_yaw = (area * (arm_x * ny - arm_y * nx)) / (sref * bref)   # cn = w_yaw·cp
        w_roll = (area * (arm_y * nz - arm_z * ny)) / (sref * bref)  # cl = w_roll·cp
    else:
        w_yaw = np.zeros(n)
        w_roll = np.zeros(n)

    # Corrected per-box Cp at unit α / β.  Cruciform: flying corrections baked in,
    # body r=1 (coupled inverse).  Strip: the body block is diagonal, so the body
    # boxes' responses are purely local (slope0·n_z/β, slope0·n_y/β).
    a_base = aero0.ajj_inv_corr
    cp_a = a_base @ d_jx[:, 0]      # ANGLEA
    cp_b = a_base @ d_jx[:, 1]      # SIDES

    return boxes, n, d_jx, baseline, w_pitch, w_yaw, w_roll, a_base, cp_a, cp_b


def _body_panel_indices(
    boxes: list, panel_eids: list[int], what: str,
) -> tuple[dict[int, FloatArray], FloatArray]:
    """Per-panel box indices and the joined body set (caller-validated EIDs).

    Horizontal panels first, then vertical, preserving the caller's order.
    """
    panel_idx = {}
    for eid in panel_eids:
        idx = np.array([k for k, b in enumerate(boxes) if b.caero_eid == eid])
        if idx.size == 0:
            raise ValueError(f"{what}: CAERO1 {eid} has no boxes")
        panel_idx[eid] = idx
    body_idx = np.concatenate([panel_idx[e] for e in panel_eids])
    return panel_idx, body_idx


def _solve_body_min_norm(
    targets: BodyTargets,
    baseline: BodyTargets,
    horiz_eids: list[int],
    vert_eids: list[int],
    w_pitch: FloatArray, w_yaw: FloatArray, w_roll: FloatArray,
    cp_a: FloatArray, cp_b: FloatArray,
    a_base: FloatArray,
    wg0: FloatArray,
    body_idx: FloatArray,
    n: int,
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Joint minimum-norm slope-ratio and offset solves over the body boxes (DEF-R4).

    Each metric is linear in the body ratios: C = C_base + Σ (w·cp_unit)·δr.  Pitch
    uses the α response (cp_a), yaw/roll the β response (cp_b).  The metrics are NOT
    all panel-private — Cl_β picks up the horizontal panel too (its β-load carries a
    rolling moment through the w_roll `y·n_z` term) — so all slope constraints are
    solved jointly over **every** body box.  This is what lets a plane be split
    across multiple panels: the per-box weights route each box to pitch (horizontal,
    n_z≠0) or yaw/roll (vertical, n_y≠0) automatically, so any number of panels per
    plane is matched together with no special-casing.  The slope is fixed before the
    offset and the offset never feeds back, so the build is non-iterative.

    Returns:
        (r, v_pitch, v_yaw, v_roll, wg_body)
    """
    # ---- slope: joint minimum-norm ratio over the body boxes ------------------
    slope_cons = []   # (weight, cp_unit, d_target)
    if horiz_eids:
        slope_cons.append((w_pitch, cp_a, targets.cm_alpha - baseline.cm_alpha))
    if vert_eids:
        slope_cons.append((w_yaw, cp_b, targets.cn_beta - baseline.cn_beta))
        slope_cons.append((w_roll, cp_b, targets.cl_beta - baseline.cl_beta))
    a_slope = np.vstack([(w * cp)[body_idx] for w, cp, _d in slope_cons])
    d_slope = np.array([d for _w, _cp, d in slope_cons])
    r = np.ones(n)
    r[body_idx] = 1.0 + np.linalg.pinv(a_slope) @ d_slope

    # Corrected operator with the body slope ratios baked in (rows scaled).
    a_r = r[:, np.newaxis] * a_base

    # ---- offset: joint minimum-norm W2GJ against the actual operator ----------
    # Cm0/Cn0/Cl0 are linear functionals of wg; solve all offset constraints
    # together over the body boxes (minimum-norm: smallest camber hitting the
    # targets).  Cruciform: body camber on one panel induces load on the other
    # surfaces through the full inverse.  Strip: purely local (diagonal block).
    v_pitch = w_pitch @ a_r        # (n,) row: d cm0 / d wg
    v_yaw = w_yaw @ a_r            # (n,) row: d cn0 / d wg
    v_roll = w_roll @ a_r          # (n,) row: d cl0 / d wg
    cm0_base = float(v_pitch @ wg0)
    cn0_base = float(v_yaw @ wg0)
    cl0_base = float(v_roll @ wg0)
    rows, dvec = [], []
    if horiz_eids:
        rows.append(v_pitch[body_idx]); dvec.append(targets.cm0 - cm0_base)
    if vert_eids:
        rows.append(v_yaw[body_idx]); dvec.append(targets.cn0 - cn0_base)
        rows.append(v_roll[body_idx]); dvec.append(targets.cl0 - cl0_base)
    a_off = np.vstack(rows)                       # (m, n_body)
    wg_solve = np.linalg.pinv(a_off) @ np.array(dvec)   # min-norm
    wg_body = np.zeros(n)
    wg_body[body_idx] = wg_solve

    return r, v_pitch, v_yaw, v_roll, wg_body


def _summarize_body_result(
    targets: BodyTargets,
    horiz_eids: list[int],
    vert_eids: list[int],
    w_pitch: FloatArray, w_yaw: FloatArray, w_roll: FloatArray,
    r: FloatArray,
    cp_a: FloatArray, cp_b: FloatArray,
    v_pitch: FloatArray, v_yaw: FloatArray, v_roll: FloatArray,
    wg_total: FloatArray,
    body_idx: FloatArray,
    tol: float,
) -> tuple[BodyTargets, dict[str, float], bool, float]:
    """Achieved totals, residuals, convergence flag and max slope ratio (DEF-R4).

    Analytic — no second AIC build is needed: ``a_r = diag(r)·A_base`` matches what
    ``build_aero_model`` assembles from the emitted cards, and ``wg`` simply
    accumulates the body W2GJ.

    Returns:
        (achieved, residual, converged, ratio_max)
    """
    achieved = BodyTargets(
        cm_alpha=float(w_pitch @ (r * cp_a)),
        cm0=float(v_pitch @ wg_total),
        cn_beta=float(w_yaw @ (r * cp_b)),
        cn0=float(v_yaw @ wg_total),
        cl_beta=float(w_roll @ (r * cp_b)),
        cl0=float(v_roll @ wg_total),
    )
    residual = {
        "cm_alpha": (targets.cm_alpha - achieved.cm_alpha) if horiz_eids else 0.0,
        "cm0": (targets.cm0 - achieved.cm0) if horiz_eids else 0.0,
        "cn_beta": (targets.cn_beta - achieved.cn_beta) if vert_eids else 0.0,
        "cn0": (targets.cn0 - achieved.cn0) if vert_eids else 0.0,
        "cl_beta": (targets.cl_beta - achieved.cl_beta) if vert_eids else 0.0,
        "cl0": (targets.cl0 - achieved.cl0) if vert_eids else 0.0,
    }
    converged = max(abs(v) for v in residual.values()) < tol
    ratio_max = float(np.max(np.abs(r[body_idx]))) if body_idx.size else 0.0
    return achieved, residual, converged, ratio_max


def build_body_correction(
    bulk: BulkData,
    *,
    horiz_eid: Optional[Union[int, Iterable[int]]] = None,
    vert_eid: Optional[Union[int, Iterable[int]]] = None,
    targets: BodyTargets,
    mach: Optional[float] = None,
    aero: Optional[AeroModel] = None,
    sid_w2gj_base: int = 9301,
    sid_aecorr_base: int = 9401,
    grid_index: Optional[dict[int, int]] = None,
    tol: float = 1e-4,
) -> BodyCorrectionResult:
    """Tune the cruciform body panels so the total airplane Cm/Cn match ``targets``.

    Args:
        bulk:        BulkData with the flying-surface corrections already applied
                     (their W2GJ/WT2 cards in ``bulk.w2gjs`` / ``bulk.aecorrs``).
        horiz_eid:   CAERO1 EID(s) of the horizontal body panel(s) that match Cm_α, Cm0
                     — an ``int`` or a list of ``int`` (define the horizontal body plane
                     with several panels). ``None``/empty skips the pitch match.
        vert_eid:    CAERO1 EID(s) of the vertical body panel(s) that match the sideslip
                     set Cn_β, Cn0, Cl_β, Cl0 — an ``int`` or a list of ``int`` (e.g. a
                     fuselage side split into several panels). ``None``/empty skips the
                     yaw/roll match. All listed panels (both planes) are tuned **jointly**
                     by one min-norm solve over all their boxes.
        targets:     total-aircraft :class:`BodyTargets` (about the AEROS RCSID ref).
        mach:        Mach override (default: AEROS field-8 Mach), for PG consistency.
        aero:        optional pre-built flying-corrected AeroModel for ``bulk`` (avoids
                     an AIC rebuild); must be consistent with ``bulk``/``mach``.
        sid_w2gj_base / sid_aecorr_base: SID bases for the emitted body cards; each panel
                     gets ``base + i`` (horizontal panels first, then vertical, in the
                     order given).
        grid_index:  optional g-set index, passed through to ``build_aero_model``.
        tol:         convergence tolerance reported on each coefficient residual.

    Returns:
        :class:`BodyCorrectionResult` with the body card pair(s) and diagnostics.
    """
    horiz_eids = _as_eid_list(horiz_eid)
    vert_eids = _as_eid_list(vert_eid)
    if not horiz_eids and not vert_eids:
        raise ValueError("build_body_correction: give horiz_eid and/or vert_eid")
    # The cruciform builder tunes VLM body panels through the shared AIC.  A
    # PSTRIP panel carries no AIC coupling at all, so it would be accepted
    # here and then never actually corrected — use build_strip_body_correction
    # for those (DEF-L1; mirrors the CHORDCP guard in aero_model).
    # Horizontal panels first, then vertical, preserving the caller's order.
    panel_eids = horiz_eids + vert_eids
    for eid in panel_eids:
        if is_strip_caero(bulk, eid):
            raise ValueError(
                f"build_body_correction: CAERO1 {eid} is a PSTRIP body panel; "
                "the cruciform builder corrects VLM body panels only — use "
                "build_strip_body_correction for decoupled strip panels."
            )

    aero0 = aero if aero is not None else build_aero_model(bulk, grid_index, mach)

    # Shared prelude: geometry, moment weight rows, unit responses (flying
    # corrections baked in, body r=1) and the per-panel box index sets.
    (boxes, n, _d_jx, baseline, w_pitch, w_yaw, w_roll,
     a_base, cp_a, cp_b) = _body_panel_geometry(bulk, aero0)
    panel_idx, body_idx = _body_panel_indices(boxes, panel_eids, "build_body_correction")

    # Bare-VLM reference circulation (Γ-units) for the WT2 card target.
    gamma_ref = np.linalg.solve(aero0.ajj, -np.ones(n))

    # Joint minimum-norm WT2-ratio + W2GJ-offset solves over the body boxes (the
    # flying surfaces stay untouched: r is a post-inverse diagonal, so only
    # body-box Cp changes).
    r, v_pitch, v_yaw, v_roll, wg_body = _solve_body_min_norm(
        targets, baseline, horiz_eids, vert_eids,
        w_pitch, w_yaw, w_roll, cp_a, cp_b, a_base, aero0.wg, body_idx, n,
    )

    # ---- emit body cards (ordinary W2GJ + WT2 on the body CAERO1s) -------------
    cards = {}
    for i, eid in enumerate(panel_eids):
        idx = panel_idx[eid]
        # Card data is NASTRAN-convention (positive = incidence); the internal
        # normalwash ``wg_body`` is the negated sense — see ``build_wg``.
        w2 = W2gj(sid=sid_w2gj_base + i, caero_eid=eid, data=(-wg_body[idx]).tolist())
        ac = Aecorr(sid=sid_aecorr_base + i, method="WT2", caero_eid=eid,
                    target=(r[idx] * gamma_ref[idx]).tolist())
        cards[eid] = (w2, ac)

    # Achieved totals are analytic to ~1e-13 (the body WT2 ratio is a
    # post-inverse diagonal scaling).
    wg_total = aero0.wg + wg_body
    achieved, residual, converged, ratio_max = _summarize_body_result(
        targets, horiz_eids, vert_eids, w_pitch, w_yaw, w_roll,
        r, cp_a, cp_b, v_pitch, v_yaw, v_roll, wg_total, body_idx, tol,
    )
    if ratio_max > RATIO_WARN:
        warnings.warn(
            f"build_body_correction: body WT2 ratio reached {ratio_max:.1f} — beyond what a "
            "flat-plate cruciform can represent.  (A ratio of tens-to-~100 is normal and "
            "benign for panels held clear of the tail; WT2 scales body-box pressure only "
            "and does not perturb the lifting surfaces.)  A value this large means the "
            "TOTAL targets demand more than a fuselage stand-in should supply — reduce the "
            "body increment, or use a slender-body element for large body effects",
            UserWarning, stacklevel=2,
        )
    if not converged:
        warnings.warn(
            f"build_body_correction: residual {residual} exceeds tol={tol:g}; the body "
            "panels may lack the authority to reach these targets",
            UserWarning, stacklevel=2,
        )

    return BodyCorrectionResult(
        cards=cards, target=targets, achieved=achieved, baseline=baseline,
        residual=residual, converged=converged, ratio_max=ratio_max,
    )


def strip_body_cards_to_bdf(result: "BodyCorrectionResult") -> str:
    """Format the strip body-panel W2GJ + STRIPK cards as bulk-data text."""
    from sbeam.aero.section_correction import card_lines
    header = "$ Decoupled strip body-panel total-aircraft moment match (W2GJ Δα + STRIPK slope)\n"
    body = ""
    for _eid, (w2, sk) in sorted(result.cards.items()):
        if not isinstance(sk, Stripk):
            continue
        body += card_lines("W2GJ", [w2.sid, w2.caero_eid], w2.data) + "\n"
        body += card_lines("STRIPK", [sk.sid, sk.caero_eid], sk.data) + "\n"
    return header + body


def build_strip_body_correction(
    bulk: BulkData,
    *,
    horiz_eid: Optional[Union[int, Iterable[int]]] = None,
    vert_eid: Optional[Union[int, Iterable[int]]] = None,
    targets: BodyTargets,
    mach: Optional[float] = None,
    aero: Optional[AeroModel] = None,
    sid_w2gj_base: int = 9301,
    sid_stripk_base: int = 9501,
    grid_index: Optional[dict[int, int]] = None,
    tol: float = 1e-4,
) -> BodyCorrectionResult:
    """Tune **decoupled strip** body panels so the total airplane Cm/Cn/Cl match ``targets``.

    The strip-panel analogue of :func:`build_body_correction`.  The named panels must be
    decoupled strip bodies (CAERO1 PID → PSTRIP); each box's load is purely local
    (``sbeam.aero.strip``), so the correction is **contamination-free by construction** —
    the lifting-surface loads are untouched no matter what the body does, and there is no
    WT2 ratio / conditioning gauge to watch.

    Two per-box knobs, solved in the same decoupled order as the cruciform:

      * **slope — STRIPK per-box lift-curve slope.**  The strip block of the operator is the
        diagonal ``diag(-slope/β)``, so scaling a body box's slope scales *only that box's*
        ΔCp.  The horizontal panel(s) match Cm_α; the vertical panel(s) match Cn_β and Cl_β
        (jointly, since a horizontal box's β-load also carries roll).  Solved as a slope
        ratio ``r`` about the nominal PSTRIP slope, then emitted as ``slope = r·slope0``.
      * **offset — W2GJ baseline normalwash Δα.**  Because the block is diagonal, a strip
        box's Δα induces load on *no other box*, so Cm0/Cn0/Cl0 are purely local linear
        functionals of ``wg`` — one joint minimum-norm solve hits the offset targets exactly.

    The slope is fixed before the offset, and the offset never feeds back into the slope, so
    the build is non-iterative and exact.  Returns a :class:`BodyCorrectionResult` whose
    ``cards`` map ``{caero_eid: (W2gj, Stripk)}``; ``ratio_max`` reports the largest slope
    scaling (informational — a large value is benign here, the panel cannot contaminate).
    """
    horiz_eids = _as_eid_list(horiz_eid)
    vert_eids = _as_eid_list(vert_eid)
    if not horiz_eids and not vert_eids:
        raise ValueError("build_strip_body_correction: give horiz_eid and/or vert_eid")
    panel_eids = horiz_eids + vert_eids
    for eid in panel_eids:
        if not is_strip_caero(bulk, eid):
            raise ValueError(
                f"build_strip_body_correction: CAERO1 {eid} is not a strip panel "
                "(its PID must reference a PSTRIP). Use build_body_correction for a "
                "cruciform VLM body panel."
            )

    aero0 = aero if aero is not None else build_aero_model(bulk, grid_index, mach)

    # Shared prelude (identical to the cruciform): geometry, moment weight rows,
    # unit responses (the strip block of ajj_inv_corr is diagonal, so the body
    # boxes' cp_a/cp_b are purely local and carry the nominal slope) and the
    # per-panel box index sets.
    (boxes, n, _d_jx, baseline, w_pitch, w_yaw, w_roll,
     a_base, cp_a, cp_b) = _body_panel_geometry(bulk, aero0)
    panel_idx, body_idx = _body_panel_indices(
        boxes, panel_eids, "build_strip_body_correction")

    slope0 = strip_box_slopes(bulk, boxes)   # nominal per-box slope (length n)

    # Joint minimum-norm slope-ratio (about the nominal PSTRIP slope) + W2GJ Δα
    # offset solves; purely local for the diagonal strip block.
    r, v_pitch, v_yaw, v_roll, wg_body = _solve_body_min_norm(
        targets, baseline, horiz_eids, vert_eids,
        w_pitch, w_yaw, w_roll, cp_a, cp_b, a_base, aero0.wg, body_idx, n,
    )

    # ---- emit body cards: W2GJ (Δα offset) + STRIPK (per-box slope = r·slope0) ---------
    cards = {}
    for i, eid in enumerate(panel_eids):
        idx = panel_idx[eid]
        # Card data is NASTRAN-convention (positive = incidence) — see ``build_wg``.
        w2 = W2gj(sid=sid_w2gj_base + i, caero_eid=eid, data=(-wg_body[idx]).tolist())
        sk = Stripk(sid=sid_stripk_base + i, caero_eid=eid,
                    data=(r[idx] * slope0[idx]).tolist())
        cards[eid] = (w2, sk)

    # Achieved totals are analytic (a_r is the exact production operator).
    wg_total = aero0.wg + wg_body
    achieved, residual, converged, ratio_max = _summarize_body_result(
        targets, horiz_eids, vert_eids, w_pitch, w_yaw, w_roll,
        r, cp_a, cp_b, v_pitch, v_yaw, v_roll, wg_total, body_idx, tol,
    )
    if not converged:
        warnings.warn(
            f"build_strip_body_correction: residual {residual} exceeds tol={tol:g}; the "
            "strip panels may lack the spatial spread (x-arm for pitch/yaw, z-arm for "
            "roll) to reach these targets — add boxes or extend the panel",
            UserWarning, stacklevel=2,
        )

    return BodyCorrectionResult(
        cards=cards, target=targets, achieved=achieved, baseline=baseline,
        residual=residual, converged=converged, ratio_max=ratio_max,
    )
