"""Steady vortex-lattice aerodynamics — AIC matrix and rigid-wing solver.

Horseshoe-vortex convention (NASA SP-405):
  - Bound vortex at 1/4-chord of each box (from AeroBox.bound_a to bound_b)
  - Collocation (flow-tangency) point at 3/4-chord midspan (AeroBox.colloc)
  - Trailing legs extend downstream in +X to a finite far-field cutoff

Models are full-span: every lifting surface is meshed in full (both sides of
the XZ plane).  sbeam does not support half-span / symmetry-image models — see
the AEROS SYMXZ guard in aero_model.build_aero_model.

All coordinates in global CID 0. Freestream V∞ = 1 in +X direction.
"""

import math
from collections import defaultdict
from typing import Any, Optional

import numpy as np

from sbeam.aero.panel import AeroBox
from sbeam.model.aero import Aeros
from sbeam.types import FloatArray, IntArray

_FAR_FIELD_FACTOR = 1000.0   # trailing leg length = factor × box chord
_DEGEN_TOL = 1e-14           # near-zero threshold for Biot-Savart guards


# ---------------------------------------------------------------------------
# Core Biot-Savart kernel
# ---------------------------------------------------------------------------

def biot_savart_seg(p: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Velocity at p induced by a unit-strength finite vortex segment a→b.

    Returns the zero vector when p lies on or very near the segment.
    """
    r1 = p - a
    r2 = p - b
    r0 = b - a

    n1 = math.sqrt(r1[0]*r1[0] + r1[1]*r1[1] + r1[2]*r1[2])
    n2 = math.sqrt(r2[0]*r2[0] + r2[1]*r2[1] + r2[2]*r2[2])
    if n1 < _DEGEN_TOL or n2 < _DEGEN_TOL:
        return np.zeros(3)

    cross = np.cross(r1, r2)
    denom = cross[0]*cross[0] + cross[1]*cross[1] + cross[2]*cross[2]
    if denom < _DEGEN_TOL:
        return np.zeros(3)

    factor = (np.dot(r0, r1) / n1 - np.dot(r0, r2) / n2) / (4.0 * math.pi * denom)
    return factor * cross


# ---------------------------------------------------------------------------
# Horseshoe influence — single AIC entry
# ---------------------------------------------------------------------------

def horseshoe_influence(colloc: FloatArray, colloc_normal: FloatArray,
                        box: AeroBox) -> float:
    """Normalwash at colloc from a unit-strength horseshoe vortex at box.

    The horseshoe consists of:
      • bound segment  bound_a → bound_b
      • right trailing bound_b → far-field (+x)
      • left trailing  far-field (+x) → bound_a

    Returns the induced velocity projected onto colloc_normal (ZAERO Eq. 3.49a:
    NIC = n_x·UIC + n_y·VIC + n_z·WIC — general non-planar formulation).
    """
    a = box.bound_a
    b = box.bound_b
    far_x = max(a[0], b[0]) + _FAR_FIELD_FACTOR * box.chord
    far_a = np.array([far_x, a[1], a[2]])
    far_b = np.array([far_x, b[1], b[2]])

    v = (biot_savart_seg(colloc, a, b)
         + biot_savart_seg(colloc, b, far_b)
         + biot_savart_seg(colloc, far_a, a))
    return float(np.dot(v, colloc_normal))


# ---------------------------------------------------------------------------
# AIC matrix assembly — broadcast Biot-Savart
# ---------------------------------------------------------------------------

_AJJ_CHUNK = 512   # receiver rows per broadcast block (bounds peak temp memory)


def _dot3(u: FloatArray, v: FloatArray) -> FloatArray:
    """3-component dot over the last axis, summed left-to-right like the
    scalar kernel's explicit x*x + y*y + z*z (bit-for-bit with biot_savart_seg)."""
    return u[..., 0] * v[..., 0] + u[..., 1] * v[..., 1] + u[..., 2] * v[..., 2]


def _boxes_to_arrays(
    boxes: list[AeroBox],
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray]:
    """Gather box geometry into arrays in POSITIONAL order (not box.k — callers
    pass filtered sublists, e.g. the VLM subset with strip boxes removed)."""
    colloc = np.array([box.colloc for box in boxes], dtype=float)
    normal = np.array([box.normal for box in boxes], dtype=float)
    a = np.array([box.bound_a for box in boxes], dtype=float)
    b = np.array([box.bound_b for box in boxes], dtype=float)
    chord = np.array([box.chord for box in boxes], dtype=float)
    return colloc, normal, a, b, chord


def _biot_savart_batch(p: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Broadcast biot_savart_seg: receivers p (m,1,3) × segments a,b (n,3) → (m,n,3).

    Same formula and float64 op order as the scalar kernel; the scalar's
    early-return-zero guards become masks (any NaN/Inf produced in a masked
    lane is discarded by the final where).
    """
    r1 = p - a
    r2 = p - b
    r0 = b - a
    n1 = np.sqrt(_dot3(r1, r1))
    n2 = np.sqrt(_dot3(r2, r2))
    cross = np.cross(r1, r2)
    denom = _dot3(cross, cross)
    bad = (n1 < _DEGEN_TOL) | (n2 < _DEGEN_TOL) | (denom < _DEGEN_TOL)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = (_dot3(r0, r1) / n1 - _dot3(r0, r2) / n2) / (4.0 * math.pi * denom)
        v = factor[..., None] * cross
    return np.where(bad[..., None], 0.0, v)


def build_ajj(boxes: list[AeroBox]) -> FloatArray:
    """Build the n_box × n_box aerodynamic influence coefficient matrix.

    A[i, j] = normalwash at colloc_i per unit circulation at horseshoe_j.
    Uses the receiving panel's outward normal (ZAERO Eq. 3.49a), supporting
    arbitrary surface orientations (horizontal wings, vertical fins, etc.).

    Vectorized broadcast Biot-Savart (P9), bit-for-bit identical to the scalar
    horseshoe_influence loop; receivers are processed in chunks of _AJJ_CHUNK
    rows so peak temporary memory stays bounded (~25 MB per (chunk, n, 3)
    float64 temp at n = 2000).
    """
    n = len(boxes)
    if n == 0:
        return np.zeros((0, 0))
    colloc, normal, a, b, chord = _boxes_to_arrays(boxes)

    # Per-sender far-field points (horseshoe_influence convention): trailing
    # legs run downstream to max(a_x, b_x) + factor × CAERO1 macroelement chord.
    far_x = np.maximum(a[:, 0], b[:, 0]) + _FAR_FIELD_FACTOR * chord
    far_a = np.column_stack([far_x, a[:, 1], a[:, 2]])
    far_b = np.column_stack([far_x, b[:, 1], b[:, 2]])

    A = np.empty((n, n))
    for i0 in range(0, n, _AJJ_CHUNK):
        i1 = min(i0 + _AJJ_CHUNK, n)
        p = colloc[i0:i1, None, :]
        # Same left-to-right 3-segment sum as horseshoe_influence.
        v = (_biot_savart_batch(p, a, b)
             + _biot_savart_batch(p, b, far_b)
             + _biot_savart_batch(p, far_a, a))
        A[i0:i1, :] = _dot3(v, normal[i0:i1, None, :])
    return A


# ---------------------------------------------------------------------------
# Prandtl–Glauert / Göthert compressibility correction
# ---------------------------------------------------------------------------

def prandtl_glauert_boxes(boxes: list[AeroBox], mach: float) -> list[AeroBox]:
    """Return copies of boxes with y,z scaled by β = √(1−M²) (Göthert compression).

    The compressible AIC is built on the compressed geometry; the caller must
    then scale the resulting AIC inverse by 1/β to recover physical pressures
    (see §2.8 of docs/20_theory/01_aeroelastics_theory.md, Eq. 14).

    Returns the original list unchanged when mach ≤ 0 (incompressible).
    An effective Mach ≥ 1 is rejected (AE9): the steady subsonic VLM cannot
    solve the transonic/supersonic regime, so it errors rather than clamping.
    """
    if mach <= 0.0:
        return boxes
    if mach >= 1.0:
        raise ValueError(
            f"prandtl_glauert_boxes: Mach {mach} ≥ 1.0; steady subsonic VLM "
            "cannot solve M ≥ 1 (needs ZONA51/piston theory)."
        )
    beta = math.sqrt(1.0 - mach ** 2)
    if abs(beta - 1.0) < 1e-10:
        return boxes
    from copy import copy
    scale_yz = np.array([1.0, beta, beta])
    scaled = []
    for b in boxes:
        s = copy(b)
        s.bound_a = b.bound_a * scale_yz
        s.bound_b = b.bound_b * scale_yz
        s.colloc  = b.colloc  * scale_yz
        s.corners = b.corners * scale_yz   # shape (4,3); broadcasts over rows
        s.area    = b.area * beta
        # unit normal direction is invariant under uniform y,z scaling
        scaled.append(s)
    return scaled


# ---------------------------------------------------------------------------
# Rigid-wing solver
# ---------------------------------------------------------------------------

def box_widths(boxes: list[AeroBox]) -> FloatArray:
    """Per-box bound-vortex span ‖Δs⃗‖ (the y-z projected width).  Shape: (n,)."""
    return np.array([
        float(math.sqrt((b.bound_b[1] - b.bound_a[1])**2
                        + (b.bound_b[2] - b.bound_a[2])**2))
        for b in boxes
    ])


def box_circulation(boxes: list[AeroBox], cp: FloatArray) -> FloatArray:
    """Circulation Γ per box from its ΔCp.  Shape: (n,).

    The inverse of ``solve_rigid_cl``'s ``cp = 2Γ/chord_box``, with
    ``chord_box = area/width``:  **Γ_j = cp_j·area_j / (2·width_j)**.  This is
    the one place the factor is written down for callers that hold a ΔCp field
    but not the circulation — SOL 144, whose ``gamma`` variable is the ΔCp the
    corrected operator returns.  Degenerate (zero-width) boxes get Γ = 0.
    """
    width = box_widths(boxes)
    area = np.array([b.area for b in boxes])
    cp = np.asarray(cp, dtype=float)
    return np.where(width > _DEGEN_TOL, cp * area / (2.0 * np.maximum(width, _DEGEN_TOL)), 0.0)


def _trefftz_wake(
    boxes: list[AeroBox], gamma: FloatArray
) -> tuple[IntArray, FloatArray, FloatArray, FloatArray]:
    """Shared Trefftz-plane wake integral: ``(lift_idxs, gamma_l, w_tr, dy_l)``.

    The single owner of the far-field downwash — ``trefftz_cdi`` (the total CDi)
    and ``trefftz_box_drag`` (its per-box breakdown) are both thin readers of
    it, so the induced-drag total and its distribution cannot drift apart.

    Only lift surfaces (|n_z| ≥ |n_y|) shed a wake here, and **decoupled strip
    body panels shed none at all** (no horseshoe vortex): their circulation is
    zeroed, so they contribute nothing to either result.
    """
    lift_idxs = np.array(
        [i for i, b in enumerate(boxes)
         if abs(b.normal[2]) >= abs(b.normal[1])
         and not getattr(b, "is_strip", False)],
        dtype=int,
    )
    if len(lift_idxs) == 0:
        empty = np.zeros(0)
        return lift_idxs, empty, empty, empty

    gamma_l = gamma[lift_idxs]
    ba = np.array([boxes[ii].bound_a for ii in lift_idxs])
    bb = np.array([boxes[ii].bound_b for ii in lift_idxs])
    dy_l = np.sqrt((bb[:, 1] - ba[:, 1])**2 + (bb[:, 2] - ba[:, 2])**2)

    # Trefftz-plane induced downwash at each lift-box bound-vortex midpoint,
    # broadcast over all trailing vortices: +Γ at bound_b, -Γ at bound_a.
    _twopi_inv = 1.0 / (2.0 * math.pi)
    y_i = 0.5 * (ba[:, 1] + bb[:, 1])
    z_i = 0.5 * (ba[:, 2] + bb[:, 2])
    y_v = np.concatenate([bb[:, 1], ba[:, 1]])
    z_v = np.concatenate([bb[:, 2], ba[:, 2]])
    sv = np.concatenate([gamma_l, -gamma_l])

    dy = y_i[:, None] - y_v
    dz = z_i[:, None] - z_v
    r2 = dy * dy + dz * dz
    # u_z from 2-D vortex: -Γ/(2π) · (y - y_v) / r²  (degenerate r² masked out)
    with np.errstate(divide="ignore", invalid="ignore"):
        contrib = -sv * _twopi_inv * dy / r2
    w_tr = np.sum(np.where(r2 > _DEGEN_TOL, contrib, 0.0), axis=1)

    return lift_idxs, gamma_l, w_tr, dy_l


def trefftz_box_drag(boxes: list[AeroBox], gamma: FloatArray) -> FloatArray:
    """Per-box streamwise induced-drag force, force/q units.  Shape: (n_box,).

    The spanwise breakdown of the Trefftz integral: ``d_j = Γ_j·w_T,j·Δy_j``,
    whose sum is ``CDi·S_ref`` by construction (``trefftz_cdi`` forms exactly
    that sum).  Positive is downstream (+x̂), so ``Σ d / S_ref`` is a positive
    drag coefficient.  Zero on non-lift and strip-body boxes.

    **Scope of use (Step 67b).**  This is deliberately NOT added to the baseline
    box forces, ``CX``, ``CD_wind`` or the load export: sbeam reports
    ``CD_wind`` as the Trefftz CDi rather than the unreliable near-field
    projection (see ``solve_rigid_cl``), and folding a near-field drag into the
    load path would contradict that.  It exists to supply the *asymmetry* of the
    drag under a yaw rate — only the asymmetric part makes a yaw moment; the
    symmetric part is already in CDi and contributes no Mz.
    """
    out = np.zeros(len(boxes))
    lift_idxs, gamma_l, w_tr, dy_l = _trefftz_wake(boxes, gamma)
    if len(lift_idxs):
        out[lift_idxs] = gamma_l * w_tr * dy_l
    return out


def trefftz_cdi(
    boxes: list[AeroBox],
    gamma: FloatArray,
    S_ref: float,
    ar: float,
) -> dict[str, float]:
    """Trefftz-plane induced drag coefficient and Oswald span efficiency.

    Integrates the semi-infinite trailing-vortex wake in the far-field y-z
    plane using the 2-D Biot-Savart kernel.  Only lift surfaces
    (|n_z| ≥ |n_y|) contribute.  The wake itself is ``_trefftz_wake``, shared
    with the per-box breakdown ``trefftz_box_drag``.

    S_ref must be consistent with the CL normalisation used by the caller
    (= sum of modelled box areas for heuristic models).
    ar is the physical aspect ratio (full-span²/full-area) and is computed
    by the caller to avoid any ambiguity about half-vs-full-span reference.

    Returns {"CDi": float, "e": float} where e is the Oswald efficiency.
    """
    lift_idxs, gamma_l, w_tr, dy_l = _trefftz_wake(boxes, gamma)
    if len(lift_idxs) == 0 or S_ref < _DEGEN_TOL or ar < _DEGEN_TOL:
        return {"CDi": 0.0, "e": float("nan")}

    # Trefftz-plane formula: Di = ρ/2 · Σ Γ·w_T·Δy  (Katz & Plotkin Eq 12.17)
    # With ρ=V∞=1 → q=0.5:  CDi = Di/(q·S_ref) = 2·(ρ/2·Σ)/S_ref = Σ/S_ref
    # (The ρ/2 and 1/q=2 factors cancel; w_T uses the full 2-D kernel 1/(2π).)
    Di = float(np.dot(gamma_l * w_tr, dy_l))
    CDi = Di / S_ref

    # CL from lift boxes, body-axis (same convention as solve_rigid_cl's CZ, so
    # the documented identity CDi = CZ²/(π·AR·e) holds against the returned CZ).
    # The z-component of the box force is 2·Γ·‖Δs⃗‖·n_z (DEF-M2).
    nz_l = np.array([boxes[ii].normal[2] for ii in lift_idxs])
    CL_l = 2.0 * float(np.dot(gamma_l * dy_l, nz_l)) / S_ref

    e = (CL_l * CL_l) / (math.pi * ar * CDi) if CDi > _DEGEN_TOL else float("nan")

    return {"CDi": CDi, "e": e}


def solve_rigid_cl(
    boxes: list[AeroBox], alpha: float, beta: float = 0.0,
    aeros: Optional[Aeros] = None, xref: float = 0.0, mach: float = 0.0,
    wg: Optional[FloatArray] = None, cp_operator: Optional[FloatArray] = None,
) -> dict[str, Any]:
    """Solve flow-tangency for a rigid configuration at incidence alpha/beta (radians).

    alpha  — angle of attack (rad); loads horizontal surfaces.
    beta   — sideslip angle (rad); loads vertical surfaces (VTP/fins).
    mach   — freestream Mach number; Prandtl–Glauert / Göthert correction applied
             when > 0 (see §2.8 of docs/20_theory/01_aeroelastics_theory.md).
    aeros  — optional Aeros card; if provided, uses aeros.sref for S_ref and
             aeros.cref for c_ref normalisation. If None, a heuristic reference
             geometry is derived from the box mesh.
    xref   — moment reference x-coordinate in CID 0 (default 0.0). CM is about
             xref, normalised by S_ref × c_ref. Set to the quarter-MAC x-coordinate
             for a stability-axis CM.
    wg     — optional (n,) baseline normalwash vector (W2GJ camber/twist/built-in
             incidence), one value per box in mesh order; pass ``aero_model.wg``.
             ``None`` (default) is equivalent to a zero vector — identical to the
             pre-existing rigid-AoA behaviour.  Folded into the boundary condition
             with the **canonical normalwash sign** (theory §2.4–2.5;
             sbeam/solver/sol144.py ``w_total = w_trim + wg``): wg is the downwash
             slope dz/dx, so a POSITIVE entry reduces lift (leading-edge-down /
             washout) and a built-in leading-edge-up incidence is NEGATIVE.  This
             is the single sign carried by the W2gj dataclass, the trim solver,
             and the end-to-end regression in
             tests/integration/test_wg_sign_convention.py, so the viewer Aero tab
             matches the SOL 144 baseline load.
    cp_operator — optional (n, n) corrected ΔCp operator (``AeroModel.ajj_inv_corr``).
             When given, ΔCp = cp_operator @ rhs directly instead of building and
             solving the raw VLM AIC here — so any AIC correction (WKK / WT1 / WT2)
             **and** the Prandtl–Glauert factor baked into ``ajj_inv_corr`` are
             honoured (the SOL 144 path). ``mach`` is then ignored (β already baked
             in). ``None`` (default) keeps the original build-and-solve behaviour;
             with no correction the two paths are numerically identical.

    Boundary condition per panel (ZAERO Eq. 3.28):
      rhs[i] = -(V⃗ · n̂_i) + wg[i]  with V⃗ ≈ [1, β, α] for small angles
             = -(α·n_z[i] + β·n_y[i]) + wg[i]

    Each CAERO1 surface is classified by its dominant outward normal:
      |mean n_z| ≥ |mean n_y|  →  "lift"      (horizontal surface)
      |mean n_y|  > |mean n_z|  →  "sideforce" (vertical surface)
    The classification labels the ``per_surface`` breakdown; it does NOT partition
    the global totals, which are true body-axis sums over every box (DEF-M2).

    **Force convention (DEF-M2).**  Every box force is ``F_j = area_j·n̂_j·cp_j``
    — the same object ``build_skj`` produces — so CX/CY/CZ/CM here are identical
    to the skj-integrated totals used by SOL 144, the f06 and the viewer's S&C
    derivative table.  They are components of the body-axis resultant, not the
    panel-normal force magnitude: on a surface with dihedral Γ the boundary
    condition reduces the pressure by cos Γ and the projection reduces the
    vertical force by a further cos Γ, so CZ scales as cos²Γ (theory §2.9,
    "dihedral enters twice").

    Returns a dict with keys:
      cp            (n,) pressure coefficient per box  (ΔCp = 2Γ / (V∞ · chord_box))
      cl_section    dict mapping i_span → section **normal-force** coefficient cn
                    (all surfaces).  Deliberately NOT projected on body-z: cn is the
                    conventional section quantity and is what ``section_data`` /
                    ``section_correction`` ingest from CFD and test.  Only the global
                    totals below are body-axis.
      CL            **body-axis** vertical-force coefficient — the box forces summed
                    on global/body-z over every box (≡ CZ).  This is the historical
                    key name; it is NOT the wind-axis lift.  Linear in α, so the
                    α-linearity / AoA-equivalence / parallel-axis-CM identities are
                    expressed in terms of it.
      CZ            body-axis vertical-force coefficient (explicit alias of ``CL``)
      CX            body-axis streamwise-force coefficient (≈ 0 for planar geometry —
                    a surface-normal-pressure VLM carries no leading-edge suction, and
                    incidence/camber/controls enter via normalwash, not geometric
                    rotation — but non-zero wherever a panel is tilted in x)
      CL_wind       **wind-axis** lift coefficient (force ⊥ to U∞): the body-axis
                    resultant rotated through α, ``CL_wind = CZ·cosα − CX·sinα``.
                    Equals CZ only at α ≈ 0; this is the genuine CL.
      CD_wind       wind-axis (induced) drag coefficient = Trefftz ``CDi``.  NOT the
                    near-field projection ``CX·cosα + CZ·sinα`` (a no-LE-suction
                    flat-panel VLM gets that wrong); the Trefftz far-field value is
                    the physically meaningful wind-axis drag.
      CY            body-axis sideforce coefficient, summed over every box — so a
                    canted lifting surface's side force is included, not only that
                    of surfaces classified "sideforce"
      CM            pitching moment coefficient about xref, nose-up positive;
                    ``−Σ Fz·(x_force − xref)`` over every box, normalised by
                    S_ref × c_ref — verbatim ``sol144.pitch_moment``.  Each box load
                    acts at its 1/4-chord bound vortex (not the 3/4-chord collocation
                    point) — the physically correct moment arm.
                    (Pitch moment is invariant under the body→wind rotation about y.)
      CDi           Trefftz-plane induced drag coefficient (lift surfaces only)
      e             Oswald span efficiency: CDi = CZ²/(π·AR·e)  (body-axis lift)
      per_surface   dict {caero_eid: {surface_type, CL, CY, CM}} — per-surface
                    ``CL`` is the body-axis (CZ) contribution of that surface.

    Full-span model: every lifting surface is meshed in full, so CL/CY/CM are
    whole-configuration coefficients with no symmetry factor.
    """
    n = len(boxes)

    # Baseline normalwash (W2GJ camber/twist/incidence); zero when not supplied.
    if wg is None:
        wg_vec = np.zeros(n)
    else:
        wg_vec = np.asarray(wg, dtype=float)
        if wg_vec.shape != (n,):
            raise ValueError(
                f"solve_rigid_cl: wg has shape {wg_vec.shape}, expected ({n},) "
                f"(one baseline normalwash value per box)"
            )

    # Flow-tangency: rhs[i] = -(alpha*n_z + beta*n_y) + wg[i] per panel.
    # The +wg term matches the SOL 144 trim sign (w_total = w_trim + wg), so a
    # positive wg (downwash slope) reduces lift exactly as in the trim solver.
    rhs = np.array([-(alpha * b.normal[2] + beta * b.normal[1]) for b in boxes]) + wg_vec

    # Cross-flow width of each box: ‖Δs⃗‖ projected on the y-z plane,
    # sqrt(Δy²+Δz²), so sweep and dihedral are handled correctly.  This is the
    # panel *width* — it sets the box chord below and weights the Trefftz wake
    # integral.  It is NOT the vertical-force lever: the body-axis components of
    # the box force come from the box normal (see f_box), not from this scalar
    # (DEF-M2).
    width = box_widths(boxes)

    # Individual box chord = area / width  (avoids relying on box.chord
    # which stores the CAERO1 macroelement chord, not the VLM panel chord)
    chord_box = np.array([
        boxes[i].area / width[i] if width[i] > _DEGEN_TOL else 1.0
        for i in range(n)
    ])

    # Circulation: either from a supplied corrected ΔCp operator (so WKK/WT1/WT2 and
    # the Prandtl–Glauert factor baked into ajj_inv_corr are honoured — the SOL 144
    # path), or by building and solving the raw VLM AIC here.
    if cp_operator is not None:
        cp_op = np.asarray(cp_operator, dtype=float)
        if cp_op.shape != (n, n):
            raise ValueError(
                f"solve_rigid_cl: cp_operator has shape {cp_op.shape}, expected ({n}, {n})"
            )
        # ajj_inv_corr already maps normalwash → ΔCp (includes 2/chord, 1/β, correction).
        cp_direct = cp_op @ rhs
        gamma = cp_direct * chord_box / 2.0   # back out Γ for K-J lift / Trefftz
    else:
        # Decoupled strip body panels have no horseshoe vortex, so the raw VLM
        # build-and-solve path here cannot represent them — their load is defined by
        # the diagonal operator block in AeroModel.ajj_inv_corr.  Require the operator.
        if any(getattr(b, "is_strip", False) for b in boxes):
            raise ValueError(
                "solve_rigid_cl: model contains decoupled strip body panels (PSTRIP); "
                "pass cp_operator=aero_model.ajj_inv_corr (the raw VLM solve cannot "
                "represent strip panels, which carry no horseshoe vortex)."
            )
        # AE9: M ≥ 1 is rejected by prandtl_glauert_boxes (the steady subsonic VLM
        # cannot solve it); no silent clamp.
        beta_pg = math.sqrt(1.0 - mach ** 2) if 0.0 < mach < 1.0 else 1.0
        A = build_ajj(prandtl_glauert_boxes(boxes, mach))
        gamma = np.linalg.solve(A, rhs)
        gamma /= beta_pg   # Göthert boundary-condition scaling (§2.8 Eq. 14)

    # Pressure coefficient per box: ΔCp = 2Γ / (V∞ · chord_box), V∞ = 1
    cp = 2.0 * gamma / chord_box

    # Per-box body-axis force in force/q units, [Fx, Fy, Fz] per row.  Identical
    # by construction to build_skj(boxes) @ cp — since chord_box = area/width,
    #     F_j = area_j·n̂_j·cp_j = 2·Γ_j·‖Δs⃗_j‖·n̂_j
    # — so this rigid path and the skj path used by SOL 144 cannot drift apart.
    # The z-column is also exactly the Kutta-Joukowski lift ρV∞Γ Δy_raw, because
    # ‖Δs⃗‖·n_z = Δy_raw.  Before DEF-M2 the totals below used the force
    # *magnitude* 2Γ‖Δs⃗‖ as if it were vertical, overstating CZ by 1/cos Γ on a
    # panel with dihedral and disagreeing with every skj-based deliverable.
    normals = np.array([b.normal for b in boxes])            # (n, 3)
    f_box = (2.0 * gamma * width)[:, None] * normals         # (n, 3)

    # Streamwise station at which each box force acts: the ¼-chord bound-vortex
    # midpoint (AE6), the correct pitching-moment arm.  Using the ¾-chord
    # collocation point instead shifts every box load aft by half a box chord and
    # inflates |CM| by CL·(½·box_chord)/c_ref — a mesh-dependent bias that
    # vanishes only as NCHORD→∞.  Validated against AVL/VortexLattice.jl
    # (val_vlm_byu_wing).
    x_force = np.array([b.force_point[0] for b in boxes])

    # -----------------------------------------------------------------------
    # Reference geometry
    # -----------------------------------------------------------------------
    if aeros is not None:
        S_ref = float(aeros.sref)
        c_ref = float(aeros.cref)
        # AEROS sref/bref refer to the full wing; AR is unambiguous.
        _ar = float(aeros.bref) ** 2 / S_ref
    else:
        # Heuristic: total area and mean chord derived from mesh extents.
        # Full-span model — S_ref is the whole modelled area and the span is the
        # full tip-to-tip extent, so AR = span_ref² / S_ref is unambiguous.
        S_ref = sum(b.area for b in boxes)
        colloc_pts = np.array([b.colloc for b in boxes])
        span_ref = float(np.max(np.ptp(colloc_pts[:, 1:], axis=0))) + width.mean()
        if span_ref < _DEGEN_TOL:
            span_ref = 1.0
        c_ref = S_ref / span_ref
        _ar = span_ref * span_ref / S_ref if S_ref > _DEGEN_TOL else 1.0

    # -----------------------------------------------------------------------
    # Trefftz-plane induced drag.  Decoupled strip body boxes shed NO trailing
    # vorticity (no wake), so they contribute nothing to the Trefftz wake integral —
    # `_trefftz_wake` excludes them (it owns that rule for both the total CDi and
    # the per-box breakdown).  Their (real) lift still counts in CL/CZ above; only
    # the induced-drag wake excludes them.
    # -----------------------------------------------------------------------
    _cdi_result = trefftz_cdi(boxes, gamma, S_ref, _ar)

    # -----------------------------------------------------------------------
    # Per-surface classification: horizontal (lift) vs vertical (sideforce)
    # -----------------------------------------------------------------------
    eid_to_indices: dict[int, list[int]] = defaultdict(list)
    for i, box in enumerate(boxes):
        eid_to_indices[box.caero_eid].append(i)

    surfaces: dict[int, dict[str, Any]] = {}
    for eid, idxs in eid_to_indices.items():
        mean_abs_normal = np.abs([boxes[i].normal for i in idxs]).mean(axis=0)
        stype = "lift" if mean_abs_normal[2] >= mean_abs_normal[1] else "sideforce"
        surfaces[eid] = {"type": stype, "indices": idxs}

    # (No flat lift/sideforce index lists: since DEF-M2 the global totals sum
    # every box, and the per-surface breakdown below uses each surface's own
    # index list.  The classification survives only as a per_surface label.)

    # -----------------------------------------------------------------------
    # Section loads: group by i_span (all surfaces, for backward compatibility)
    # -----------------------------------------------------------------------
    strips: dict[int, list[int]] = {}
    for i, box in enumerate(boxes):
        strips.setdefault(box.i_span, []).append(i)

    cl_section: dict[int, float] = {}
    for s, idxs in sorted(strips.items()):
        dy_s = width[idxs[0]]   # all boxes in a strip share the same spanwise width
        chord_strip = sum(boxes[i].area for i in idxs) / dy_s
        if chord_strip < _DEGEN_TOL:
            chord_strip = 1.0
        cl_section[s] = 2.0 * sum(gamma[i] for i in idxs) / chord_strip

    # -----------------------------------------------------------------------
    # Global body-axis force coefficients (DEF-M2).
    #
    # Each is the corresponding column of f_box summed over EVERY box and
    # normalised by S_ref — genuine components of the body-axis resultant, the
    # same quantities `sol144.compute_rigid_derivs` integrates through skj.
    # Before DEF-M2, CZ and CY were partitioned by surface *classification*
    # (lift surfaces → CZ, sideforce surfaces → CY) and each carried the panel-
    # normal force magnitude rather than its projection, so a dihedral wing's
    # real side force was reported nowhere and its CZ was 1/cos Γ too large.
    # The lift/sideforce classification is retained for `per_surface` labelling.
    # -----------------------------------------------------------------------
    CX = float(f_box[:, 0].sum()) / S_ref
    CY = float(f_box[:, 1].sum()) / S_ref
    CL = float(f_box[:, 2].sum()) / S_ref      # body-axis vertical force (≡ CZ)

    # ------------------------------------------------------------------ #
    # Wind-axis lift/drag (genuine CL/CD, ⊥ and ∥ to the freestream U∞).
    # The body-axis resultant is (CX, CZ); rotating through the angle of
    # attack gives CL_wind = CZ·cosα − CX·sinα.  CX is the body-streamwise
    # force — ≈ 0 here because the panels carry only surface-normal pressure
    # (no leading-edge suction) and incidence/camber/controls enter through the
    # normalwash rather than a geometric panel tilt, so for planar geometry
    # CL_wind reduces to CZ·cosα.  The genuine wind-axis (induced) drag is the
    # Trefftz CDi, not the unreliable near-field projection CX·cosα + CZ·sinα.
    # CL_wind = CZ only at α ≈ 0 (see §5.4 of
    # docs/20_theory/01_aeroelastics_theory.md).
    ca, sa = math.cos(alpha), math.sin(alpha)
    CL_wind = CL * ca - CX * sa
    CD_wind = _cdi_result["CDi"]

    # Nose-up-positive pitching moment about xref: −Σ Fz·(x_force − xref) over
    # every box, verbatim `sol144.pitch_moment` — the single source for the
    # moment-arm convention in the trim chain (AE1 Step E).  Before DEF-M2 this
    # used the pressure form cp·area·arm over lift surfaces only, i.e. the
    # normal-force magnitude rather than Fz, diverging from the trim path on any
    # canted deck.
    CM = -float(np.dot(f_box[:, 2], x_force - xref)) / (S_ref * c_ref)

    # -----------------------------------------------------------------------
    # Per-surface coefficients
    # -----------------------------------------------------------------------
    # Same body-axis projection as the global totals, restricted to one CAERO1.
    # The surface_type label still selects which coefficient is reported, so the
    # per-surface breakdown keeps its existing shape; only the convention of the
    # numbers changed (DEF-M2).
    per_surface: dict[int, dict[str, Any]] = {}
    for eid, sinfo in surfaces.items():
        idx_arr = np.array(sinfo["indices"], dtype=int)
        if sinfo["type"] == "lift":
            cl_eid = float(f_box[idx_arr, 2].sum()) / S_ref
            cm_eid = (
                -float(np.dot(f_box[idx_arr, 2], x_force[idx_arr] - xref))
                / (S_ref * c_ref)
            ) if S_ref * c_ref > _DEGEN_TOL else 0.0
            per_surface[eid] = {"surface_type": "lift",      "CL": cl_eid, "CY": 0.0,    "CM": cm_eid}
        else:
            cy_eid = float(f_box[idx_arr, 1].sum()) / S_ref
            per_surface[eid] = {"surface_type": "sideforce", "CL": 0.0,    "CY": cy_eid, "CM": 0.0}

    return {
        "cp":          cp,
        "cl_section":  cl_section,
        "CL":          float(CL),        # body-axis vertical force (≡ CZ; legacy key name)
        "CZ":          float(CL),        # body-axis vertical force (explicit)
        "CX":          float(CX),        # body-axis streamwise force (≈ 0, no LE suction)
        "CL_wind":     float(CL_wind),   # wind-axis lift   = CZ·cosα − CX·sinα
        "CD_wind":     float(CD_wind),   # wind-axis drag   = Trefftz CDi
        "CY":          float(CY),
        "CM":          float(CM),
        "CDi":         _cdi_result["CDi"],
        "e":           _cdi_result["e"],
        "per_surface": per_surface,
    }
