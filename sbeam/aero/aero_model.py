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
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Caero1, Chordcp, Paero1, Aeros, require_aeros
from sbeam.aero.panel import AeroBox, mesh_caero1
from sbeam.aero.vlm import build_ajj, prandtl_glauert_boxes
from sbeam.aero.integration import build_skj, build_djk, build_wg
from sbeam.aero.corrections import (
    apply_wkk, apply_wt2, apply_wt1, apply_chordcp, check_conditioning,
)
from sbeam.aero.spline import build_g_spline
from sbeam.aero.strip import strip_box_mask, strip_box_slopes, is_strip_caero
from sbeam.types import FloatArray


@dataclass
class AeroModel:
    boxes: list[AeroBox]                # list[AeroBox] — all panels across all CAERO1 elements
    ajj:          FloatArray          # raw VLM AIC,  shape (n, n)
    ajj_inv_corr: FloatArray          # corrected A*⁻¹, shape (n, n)
    skj:          FloatArray          # force integration matrix, shape (3n, n)
    djk:          FloatArray          # deflection-to-downwash matrix, shape (n, n)
    wg:           FloatArray          # baseline normalwash vector, shape (n,)
    aeros:        Optional[Aeros] = None       # AEROS reference geometry card
    mach:         float = 0.0                  # Mach number for Prandtl–Glauert
    g_slope:      Optional[FloatArray] = None  # slope spline, shape (n, 6*n_g)
    g_disp:       Optional[FloatArray] = None  # displacement spline, shape (3n, 6*n_g)
    chordcp_alpha_ref: Optional[float] = None  # CHORDCP reference AOA [rad]; None = no injection

    def require_g_disp(self) -> FloatArray:
        """``g_disp``, raising if the model was built without splines.

        ``g_disp``/``g_slope`` are ``None`` until ``build_aero_model`` runs with a
        ``grid_index`` (a spline needs the structural grid).  Aeroelastic code
        that cannot proceed without them funnels through these accessors rather
        than dereferencing ``None``.
        """
        if self.g_disp is None:
            raise ValueError(
                "AeroModel.g_disp is None — build_aero_model must be called with a "
                "grid_index so the structure/aero displacement spline is built."
            )
        return self.g_disp

    def require_g_slope(self) -> FloatArray:
        """``g_slope``, raising if the model was built without splines."""
        if self.g_slope is None:
            raise ValueError(
                "AeroModel.g_slope is None — build_aero_model must be called with a "
                "grid_index so the structure/aero slope spline is built."
            )
        return self.g_slope


def _assemble_vlm_operator(
    bulk: BulkData, op_boxes: list[AeroBox], mach: float
) -> tuple[FloatArray, FloatArray]:
    """Build the raw AIC and the corrected ΔCp operator over a box subset.

    Returns ``(ajj, ajj_inv_corr)`` for ``op_boxes`` — the ordinary horseshoe-vortex
    VLM path (PG compression, WKK/WT2/WT1 correction precedence, Göthert 1/β, and the
    Γ→ΔCp chord conversion).  Strip body panels are *excluded* by the caller, so the
    wing/tail inverse is the inverse of the lifting-surface-only AIC (the strip boxes
    contribute a separate diagonal block — see ``build_aero_model``).
    """
    n = len(op_boxes)
    beta_pg = math.sqrt(1.0 - mach ** 2) if mach > 0.0 else 1.0

    # Build raw AIC on PG-compressed geometry
    ajj = build_ajj(prandtl_glauert_boxes(op_boxes, mach))

    # Correction precedence over the boxes present here — WKK, then WT2, then WT1.
    op_eids = sorted({b.caero_eid for b in op_boxes})
    primary_eid = op_eids[0]
    wkk_card  = next((c for c in bulk.wkks.values() if c.caero_eid == primary_eid), None)
    wt2_cards = [c for c in bulk.aecorrs.values()
                 if c.method == "WT2" and c.caero_eid in op_eids]
    wt1_card  = next((c for c in bulk.aecorrs.values()
                      if c.caero_eid == primary_eid and c.method == "WT1"), None)

    if wkk_card is not None:
        ajj_star = apply_wkk(ajj, wkk_card.data)
        check_conditioning(ajj_star)
        ajj_inv_corr = np.linalg.solve(ajj_star, np.eye(n))
    elif wt2_cards:
        ajj_inv_raw = np.linalg.solve(ajj, np.eye(n))
        cp_target = ajj_inv_raw @ (-np.ones(n))
        for card in wt2_cards:
            surf_idx = [k for k, b in enumerate(op_boxes) if b.caero_eid == card.caero_eid]
            tgt = np.asarray(card.target, dtype=float)
            if tgt.shape[0] != len(surf_idx):
                raise ValueError(
                    f"AECORR {card.sid} (WT2, CAERO {card.caero_eid}): target length "
                    f"{tgt.shape[0]} != {len(surf_idx)} boxes on that surface"
                )
            cp_target[surf_idx] = tgt
        ajj_inv_corr = apply_wt2(ajj, cp_target)
    elif wt1_card is not None:
        # DEPRECATED (DEF-H2/H3) — kept working, not fixed.  The PG-compressed boxes
        # passed here (combined with the 1/β and physical-chord steps below) deliver
        # f_target/β²; and apply_wt1's i_span grouping bleeds across CAERO1s.
        f_target = np.asarray(wt1_card.target, dtype=float)
        ajj_inv_corr = apply_wt1(ajj, prandtl_glauert_boxes(op_boxes, mach), f_target)
    else:
        check_conditioning(ajj)
        ajj_inv_corr = np.linalg.solve(ajj, np.eye(n))

    # Göthert 1/β scaling (boundary-condition factor from §2.8 Eq. 14)
    if beta_pg != 1.0:
        ajj_inv_corr /= beta_pg

    # Convert ajj_inv_corr from Γ-units to ΔCp-units (K-J: Cp = 2Γ/chord).
    _chord_degen = 1e-14
    chord_box_arr = np.array([
        b.area / max(math.sqrt((b.bound_b[1] - b.bound_a[1])**2
                              + (b.bound_b[2] - b.bound_a[2])**2), _chord_degen)
        for b in op_boxes          # physical boxes, not pg_boxes
    ])
    ajj_inv_corr *= (2.0 / chord_box_arr)[:, np.newaxis]
    return ajj, ajj_inv_corr


def _apply_chordcp_injection(
    bulk: BulkData,
    boxes: list[AeroBox],
    strip_mask: FloatArray,
    ajj_inv_corr: FloatArray,
    wg: FloatArray,
) -> Optional[float]:
    """CHORDCP steady-pressure injection (Step 54) — mutates ``wg`` in place.

    Replaces the program-computed baseline normalwash of every VLM lifting-surface
    box with the equivalent wash of the injected Cp distribution (see
    ``corrections.apply_chordcp``).  PSTRIP strip boxes keep their W2GJ/Δα wash —
    the strip block of ``ajj_inv_corr`` is diagonal with zero coupling, so the
    VLM sub-block solve is exact.

    v1 rules: every VLM CAERO1 must be covered by exactly one CHORDCP card, all
    cards must share the same ALPHREF, and strip CAERO1s may not be targeted.

    Returns the common reference AOA (radians), or None when no CHORDCP cards
    are present.
    """
    if not bulk.chordcps:
        return None

    vlm_eids = sorted(eid for eid in bulk.caero1s if not is_strip_caero(bulk, eid))

    cards_by_eid: dict[int, Chordcp] = {}
    for card in bulk.chordcps.values():
        if card.caero_eid not in bulk.caero1s:
            raise ValueError(
                f"CHORDCP {card.sid}: CAERO1 {card.caero_eid} not found in bulk data"
            )
        if is_strip_caero(bulk, card.caero_eid):
            raise ValueError(
                f"CHORDCP {card.sid}: CAERO1 {card.caero_eid} is a PSTRIP body panel; "
                "steady-pressure injection applies to VLM lifting surfaces only"
            )
        if card.caero_eid in cards_by_eid:
            raise ValueError(
                f"CHORDCP {card.sid}: CAERO1 {card.caero_eid} already covered by "
                f"CHORDCP {cards_by_eid[card.caero_eid].sid}"
            )
        cards_by_eid[card.caero_eid] = card

    missing = [eid for eid in vlm_eids if eid not in cards_by_eid]
    if missing:
        raise ValueError(
            "CHORDCP injection requires full coverage of all VLM lifting surfaces; "
            f"missing CHORDCP card(s) for CAERO1 {missing}"
        )

    alpha_refs = {eid: c.alpha_ref for eid, c in cards_by_eid.items()}
    alpha_ref = next(iter(alpha_refs.values()))
    if any(abs(a - alpha_ref) > 1e-12 for a in alpha_refs.values()):
        raise ValueError(
            "CHORDCP cards disagree on ALPHREF (all injected surfaces must share "
            f"one reference AOA): {{eid: rad}} = {alpha_refs}"
        )

    # The injected Cp already contains camber/incidence — any W2GJ baseline on a
    # covered surface is discarded (including body-correction-derived W2GJ cards).
    discarded = sorted({
        w.caero_eid for w in bulk.w2gjs.values()
        if w.caero_eid in cards_by_eid and any(v != 0.0 for v in w.data)
    })
    if discarded:
        warnings.warn(
            f"CHORDCP injection replaces the W2GJ baseline on CAERO1 {discarded}; "
            "the W2GJ camber/incidence (and any body-correction offsets) on those "
            "surfaces is discarded — the injected Cp must already contain it.",
            UserWarning,
        )

    # Assemble the injected Cp over the VLM boxes in global box order (per-CAERO
    # local ordering is row-major, span slowest — same as build_wg / W2GJ).
    vlm_idx = np.where(~np.asarray(strip_mask, dtype=bool))[0]
    vlm_boxes = [boxes[i] for i in vlm_idx]
    cp_inj = np.zeros(len(vlm_boxes))
    for eid, card in cards_by_eid.items():
        local = [k for k, b in enumerate(vlm_boxes) if b.caero_eid == eid]
        if len(card.data) != len(local):
            raise ValueError(
                f"CHORDCP {card.sid}: data length {len(card.data)} != "
                f"{len(local)} boxes on CAERO1 {eid} (NSPAN×NCHORD)"
            )
        cp_inj[local] = card.data

    block = ajj_inv_corr[np.ix_(vlm_idx, vlm_idx)]
    wg[vlm_idx] = apply_chordcp(block, vlm_boxes, cp_inj, alpha_ref)
    return alpha_ref


# VLM mesh-quality guidance (A7/A8): NASA SP-405; Rodden/MSC practice.
_MIN_NCHORD = 4            # boxes/chord below which chordwise loading/moment are unconverged
_AR_BAND = (0.5, 2.0)      # acceptable box aspect-ratio band (spanwise/streamwise edge)


def _warn_mesh_quality(caero: Caero1, new_boxes: list[AeroBox]) -> None:
    """Pre-solve mesh-quality warnings for one VLM CAERO1 (A7 box density, A8 box AR).

    A7: steady-VLM chordwise loading needs ≥ 4 boxes/chord (NASA SP-405); lift
    alone converges at NCHORD=1, chordwise loading/pressure do not.  Cosine
    LE-concentrated spacing (``panel.cosine_chord_fractions`` → AEFACT/LCHORD)
    reaches the same accuracy with fewer boxes.

    A8: high-aspect-ratio boxes degrade the VLM induced-downwash kernel; keep
    each box AR = spanwise edge / streamwise edge within [0.5, 2.0].  Coupled
    with A7: raising NCHORD shortens the streamwise edge, which forces NSPAN up
    to hold AR ≈ 1 — size the two together.  One warning per CAERO1.
    """
    # A7 — effective chordwise box count (NCHORD or LCHORD/AEFACT intervals)
    nchord_boxes = 1 + max(b.j_chord for b in new_boxes)
    if nchord_boxes < _MIN_NCHORD:
        warnings.warn(
            f"CAERO1 {caero.eid}: only {nchord_boxes} chordwise boxes — steady "
            f"VLM chordwise loading/moment need ≥ {_MIN_NCHORD} boxes/chord "
            "(recommended 8, or cosine LE-concentrated spacing via "
            "panel.cosine_chord_fractions + AEFACT/LCHORD)",
            UserWarning,
            stacklevel=3,
        )

    # A8 — box aspect ratio: spanwise LE edge / mean box streamwise edge.
    # NB: AeroBox.chord is the STRIP chord at the box span station, not the
    # box streamwise length — use the corner edges.
    ar_lo, ar_hi = _AR_BAND
    worst = 1.0
    n_out = 0
    for b in new_boxes:
        span_edge = float(np.linalg.norm(b.corners[1] - b.corners[0]))
        chord_edge = 0.5 * (float(np.linalg.norm(b.corners[3] - b.corners[0]))
                            + float(np.linalg.norm(b.corners[2] - b.corners[1])))
        ar = span_edge / max(chord_edge, 1e-14)
        if ar < ar_lo or ar > ar_hi:
            n_out += 1
            if abs(math.log(ar)) > abs(math.log(worst)):
                worst = ar
    if n_out:
        warnings.warn(
            f"CAERO1 {caero.eid}: {n_out} of {len(new_boxes)} boxes have aspect "
            f"ratio (spanwise/streamwise edge) outside [{ar_lo}, {ar_hi}] "
            f"(worst {worst:.3g}) — high-AR boxes degrade the VLM kernel; "
            "resize NSPAN/NCHORD together toward AR ≈ 1",
            UserWarning,
            stacklevel=3,
        )


def build_aero_model(
    bulk: BulkData,
    grid_index: Optional[dict[int, int]] = None,
    mach: Optional[float] = None,
) -> AeroModel:
    """Assemble the full AeroModel from parsed bulk data.

    sbeam is full-span only.  A half-span / symmetry model (AEROS SYMXZ or
    SYMXY non-zero) is rejected here — mirror it to a full-span deck first
    (see sbeam.aero.mirror.mirror_halfspan).

    Mach (AE9): the effective Mach is ``mach`` if given, otherwise ``AEROS.mach``
    (field 9, an sbeam extension).  Callers running SOL 144 at a per-TRIM Mach
    pass it explicitly so a single deck can be built at several flight Machs (see
    ``sbeam.solver.sol144.AeroCache``).  The steady subsonic VLM cannot solve the
    transonic/supersonic regime, so an effective Mach ≥ 1 is rejected here rather
    than silently clamped.

    Correction precedence (first match wins):
      1. WKK card present  → diagonal multiplicative: AJJ* = diag(wkk) @ AJJ,
                              AJJ*⁻¹ computed via lstsq (primary CAERO1 only).
      2. AECORR WT2 present → pressure-matching correction (apply_wt2). **Multi-surface:**
                              all WT2 cards are combined into one global Γ-unit target —
                              each card fills its own CAERO1's boxes (row-major), boxes on
                              uncorrected surfaces default to ratio 1.
      3. AECORR WT1 present → force-matching correction (apply_wt1).  **DEPRECATED
                              (DEF-H2/H3)** — the card is *selected* by the primary
                              CAERO1, but it is *applied* to every box sharing an
                              ``i_span`` key (which restarts per CAERO1), and the
                              achieved strip force is ``f_target/β²`` at M > 0.  Use
                              WT2 or the section-correction path.
      4. No correction       → AJJ*⁻¹ = solve(AJJ).

    When multiple CAERO1 elements are present, all boxes are concatenated into a single
    list and a single AIC is built for the combined surface.  W2GJ (baseline normalwash)
    is already accumulated per CAERO1, and WT2 corrections are now combined per surface;
    WKK and WT1 still act on the primary CAERO1 only.

    Decoupled strip body panels (CAERO1 PID → PSTRIP) bypass all of the above: they are
    excluded from the VLM AIC inversion and contribute a diagonal block to ``ajj_inv_corr``
    (ΔCp = -slope/β · normalwash), with zero off-diagonal coupling to or from the lifting
    surfaces (see ``sbeam.aero.strip``).  Per-box slopes come from a STRIPK card if
    present, else the PSTRIP ``slope0``; their Δα offset rides in the ordinary W2GJ ``wg``.
    """
    if not bulk.caero1s:
        raise ValueError("build_aero_model: no CAERO1 elements found in bulk data")

    if bulk.aeros is not None and (require_aeros(bulk).symxz != 0 or require_aeros(bulk).symxy != 0):
        raise ValueError(
            "build_aero_model: half-span / symmetry models are not supported "
            f"(AEROS SYMXZ={require_aeros(bulk).symxz}, SYMXY={require_aeros(bulk).symxy}). "
            "sbeam runs full-span only. Convert the deck with "
            "sbeam.aero.mirror.mirror_halfspan(), or rebuild it full-span, "
            "so that SYMXZ=SYMXY=0."
        )

    # Mesh all CAERO1 elements in ascending EID order
    boxes: list[AeroBox] = []
    start_k = 0
    for eid in sorted(bulk.caero1s):
        caero = bulk.caero1s[eid]
        # A strip-body CAERO1 points at a PSTRIP, not a PAERO1; mesh_caero1 does
        # not use the property card, so a placeholder keeps the geometry path
        # identical for both panel kinds.
        paero = bulk.paero1s.get(caero.pid) or Paero1(pid=caero.pid)
        new_boxes = mesh_caero1(caero, paero, bulk.aefacts, bulk.cord2rs, start_k=start_k)

        # Pre-solve mesh-quality warnings (A7/A8) — VLM lifting surfaces only;
        # decoupled strip body panels carry no horseshoe vortex, so the VLM
        # box-density and box-AR guidance does not apply to them.
        if not is_strip_caero(bulk, eid):
            _warn_mesh_quality(caero, new_boxes)

        boxes.extend(new_boxes)
        start_k += len(new_boxes)

    n = len(boxes)

    # Prandtl–Glauert / Göthert compressibility correction (§2.8 Eq. 14):
    # compress box y,z by β = √(1-M²) before building AIC; scale AIC⁻¹ by 1/β.
    # AE9: effective Mach = explicit override (per-TRIM) or AEROS.mach fallback.
    mach = mach if mach is not None else (require_aeros(bulk).mach if bulk.aeros else 0.0)
    if mach >= 1.0:
        raise ValueError(
            f"build_aero_model: effective Mach {mach} ≥ 1.0; the steady subsonic "
            "VLM cannot solve the transonic/supersonic regime (needs ZONA51/"
            "piston theory). Use a subsonic Mach."
        )

    # Decoupled strip body panels (PID → PSTRIP) carry NO horseshoe vortex and NO AIC
    # coupling: they are excluded from the VLM AIC inversion and placed as a diagonal
    # block in the ΔCp operator (sbeam.aero.strip).  The lifting-surface inverse is then
    # the inverse of the lifting-surface-only AIC — so strip boxes change the wing/tail
    # loads by exactly zero (no contamination by construction).
    strip_mask = strip_box_mask(bulk, boxes)
    for b, is_s in zip(boxes, strip_mask):
        b.is_strip = bool(is_s)
    if not strip_mask.any():
        ajj, ajj_inv_corr = _assemble_vlm_operator(bulk, boxes, mach)
    else:
        vlm_idx   = np.where(~strip_mask)[0]
        strip_idx = np.where(strip_mask)[0]
        ajj          = np.zeros((n, n))
        ajj_inv_corr = np.zeros((n, n))
        if vlm_idx.size:
            vlm_boxes = [boxes[i] for i in vlm_idx]
            ajj_vlm, inv_vlm = _assemble_vlm_operator(bulk, vlm_boxes, mach)
            ajj[np.ix_(vlm_idx, vlm_idx)]          = ajj_vlm
            ajj_inv_corr[np.ix_(vlm_idx, vlm_idx)] = inv_vlm
        # Raw `ajj` keeps an identity on the strip diagonal (not zero) so the full
        # block-diagonal AIC stays invertible — downstream consumers that invert the
        # whole AIC (e.g. the flying-surface section synthesiser) get the correct
        # lifting-surface block; the strip rows are decoupled and unused there.
        ajj[strip_idx, strip_idx] = 1.0
        # Diagonal strip block in ΔCp-units: ΔCp = -slope/β · rhs (Göthert 1/β for
        # consistency with the compressible VLM surfaces).  No off-diagonal terms.
        beta_pg = math.sqrt(1.0 - mach ** 2) if mach > 0.0 else 1.0
        slopes = strip_box_slopes(bulk, boxes)
        ajj_inv_corr[strip_idx, strip_idx] = -slopes[strip_idx] / beta_pg

    # Integration matrices use physical (unscaled) boxes — structural coupling
    # geometry must match the physical planform, not the PG-compressed one.
    skj = build_skj(boxes)
    djk = build_djk(boxes)

    # Accumulate baseline normalwash across all CAERO1 elements
    wg = np.zeros(n)
    for eid in sorted(bulk.caero1s):
        wg += build_wg(boxes, bulk.w2gjs, eid)

    # CHORDCP steady-pressure injection (Step 54): replace the VLM boxes'
    # baseline wash with the equivalent wash of the injected Cp distribution.
    chordcp_alpha_ref = _apply_chordcp_injection(bulk, boxes, strip_mask, ajj_inv_corr, wg)

    # Build spline operators if spline cards are present and grid_index is provided
    g_slope: Optional[FloatArray] = None
    g_disp:  Optional[FloatArray] = None
    if grid_index is not None and (bulk.spline2s or bulk.attaches or bulk.spline0s):
        g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)

    return AeroModel(
        boxes=boxes,
        ajj=ajj,
        ajj_inv_corr=ajj_inv_corr,
        skj=skj,
        djk=djk,
        wg=wg,
        aeros=bulk.aeros,
        mach=mach,
        g_slope=g_slope,
        g_disp=g_disp,
        chordcp_alpha_ref=chordcp_alpha_ref,
    )


def compute_structural_loads(
    aero_model: AeroModel,
    q: float,
    alpha: float,
) -> FloatArray:
    """Compute structural g-set loads from rigid VLM at angle of attack alpha.

    Combines AoA-driven normalwash with W2GJ baseline (wg), then transfers
    aerodynamic box forces to structural DOFs via the virtual-work path:

        w_total[j] = -(alpha * normal_z[j]) + wg[j]
        gamma       = ajj_inv_corr @ w_total
        f_box       = skj @ gamma
        f_g         = q * g_disp.T @ f_box

    Sign convention matches solve_rigid_cl: for a horizontal flat plate
    (normal=[0,0,1]), AoA alpha gives normalwash = -alpha at each box.

    Args:
        aero_model: AeroModel with g_disp populated (build_aero_model called
                    with a grid_index argument).
        q:          Dynamic pressure (Pa or consistent units).
        alpha:      Angle of attack (rad).

    Returns:
        f_g: FloatArray, shape (6 * n_structural_grids,).

    Raises:
        ValueError: if aero_model.g_disp is None.
    """
    if aero_model.g_disp is None:
        raise ValueError(
            "compute_structural_loads: aero_model.g_disp is None; "
            "pass grid_index to build_aero_model to populate the spline operators"
        )
    w_aoa   = np.array([-(alpha * b.normal[2]) for b in aero_model.boxes])
    w_total = w_aoa + aero_model.wg
    gamma   = aero_model.ajj_inv_corr @ w_total
    f_box   = aero_model.skj @ gamma
    return q * (aero_model.require_g_disp().T @ f_box)
