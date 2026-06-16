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

import numpy as np

from sbeam.aero.panel import AeroBox

_FAR_FIELD_FACTOR = 1000.0   # trailing leg length = factor × box chord
_DEGEN_TOL = 1e-14           # near-zero threshold for Biot-Savart guards


# ---------------------------------------------------------------------------
# Core Biot-Savart kernel
# ---------------------------------------------------------------------------

def biot_savart_seg(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
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

def horseshoe_influence(colloc: np.ndarray, colloc_normal: np.ndarray,
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
# AIC matrix assembly
# ---------------------------------------------------------------------------

def build_ajj(boxes: list) -> np.ndarray:
    """Build the n_box × n_box aerodynamic influence coefficient matrix.

    A[i, j] = normalwash at colloc_i per unit circulation at horseshoe_j.
    Uses the receiving panel's outward normal (ZAERO Eq. 3.49a), supporting
    arbitrary surface orientations (horizontal wings, vertical fins, etc.).
    """
    n = len(boxes)
    A = np.zeros((n, n))
    for i, box_i in enumerate(boxes):
        for j, box_j in enumerate(boxes):
            A[i, j] = horseshoe_influence(box_i.colloc, box_i.normal, box_j)
    return A


# ---------------------------------------------------------------------------
# Prandtl–Glauert / Göthert compressibility correction
# ---------------------------------------------------------------------------

def prandtl_glauert_boxes(boxes: list, mach: float) -> list:
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

def trefftz_cdi(
    boxes: list,
    gamma: np.ndarray,
    S_ref: float,
    ar: float,
) -> dict:
    """Trefftz-plane induced drag coefficient and Oswald span efficiency.

    Integrates the semi-infinite trailing-vortex wake in the far-field y-z
    plane using the 2-D Biot-Savart kernel.  Only lift surfaces
    (|n_z| ≥ |n_y|) contribute.

    S_ref must be consistent with the CL normalisation used by the caller
    (= sum of modelled box areas for heuristic models).
    ar is the physical aspect ratio (full-span²/full-area) and is computed
    by the caller to avoid any ambiguity about half-vs-full-span reference.

    Returns {"CDi": float, "e": float} where e is the Oswald efficiency.
    """
    lift_idxs = np.array(
        [i for i, b in enumerate(boxes) if abs(b.normal[2]) >= abs(b.normal[1])],
        dtype=int,
    )
    if len(lift_idxs) == 0 or S_ref < _DEGEN_TOL or ar < _DEGEN_TOL:
        return {"CDi": 0.0, "e": float("nan")}

    n = len(lift_idxs)
    gamma_l = gamma[lift_idxs]
    dy_l = np.array([
        float(math.sqrt((boxes[ii].bound_b[1] - boxes[ii].bound_a[1])**2
                      + (boxes[ii].bound_b[2] - boxes[ii].bound_a[2])**2))
        for ii in lift_idxs
    ])

    # Trefftz-plane induced downwash at each lift-box bound-vortex midpoint
    w_tr = np.zeros(n)
    _twopi_inv = 1.0 / (2.0 * math.pi)

    for i, ii in enumerate(lift_idxs):
        bi = boxes[ii]
        y_i = 0.5 * (bi.bound_a[1] + bi.bound_b[1])
        z_i = 0.5 * (bi.bound_a[2] + bi.bound_b[2])

        for j, jj in enumerate(lift_idxs):
            bj = boxes[jj]
            Gj = gamma[jj]

            # Direct trailing: +Gj at bound_b, -Gj at bound_a
            for (y_v, z_v, sv) in (
                (bj.bound_b[1], bj.bound_b[2],  Gj),
                (bj.bound_a[1], bj.bound_a[2], -Gj),
            ):
                dy = y_i - y_v
                dz = z_i - z_v
                r2 = dy * dy + dz * dz
                if r2 > _DEGEN_TOL:
                    # u_z from 2-D vortex: -Γ/(2π) · (y - y_v) / r²
                    w_tr[i] += -sv * _twopi_inv * dy / r2

    # Trefftz-plane formula: Di = ρ/2 · Σ Γ·w_T·Δy  (Katz & Plotkin Eq 12.17)
    # With ρ=V∞=1 → q=0.5:  CDi = Di/(q·S_ref) = 2·(ρ/2·Σ)/S_ref = Σ/S_ref
    # (The ρ/2 and 1/q=2 factors cancel; w_T uses the full 2-D kernel 1/(2π).)
    Di = float(np.dot(gamma_l * w_tr, dy_l))
    CDi = Di / S_ref

    # CL from lift boxes (same normalisation as solve_rigid_cl: CL = 2·L/S_ref)
    CL_l = 2.0 * float(np.dot(gamma_l, dy_l)) / S_ref

    e = (CL_l * CL_l) / (math.pi * ar * CDi) if CDi > _DEGEN_TOL else float("nan")

    return {"CDi": CDi, "e": e}


def solve_rigid_cl(boxes: list, alpha: float, beta: float = 0.0,
                   aeros=None, xref: float = 0.0,
                   mach: float = 0.0, wg=None, cp_operator=None) -> dict:
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
      |mean n_z| ≥ |mean n_y|  →  "lift"      (horizontal surface; contributes to CL/CM)
      |mean n_y|  > |mean n_z|  →  "sideforce" (vertical surface; contributes to CY)

    Returns a dict with keys:
      cp            (n,) pressure coefficient per box  (ΔCp = 2Γ / (V∞ · chord_box))
      cl_section    dict mapping i_span → section load coefficient (all surfaces)
      CL            **body-axis** vertical-force coefficient from horizontal (lift)
                    surfaces (≡ CZ; the force summed on global/body-z).  This is the
                    historical key name; it is NOT the wind-axis lift.  Linear in α,
                    so the α-linearity / AoA-equivalence / parallel-axis-CM identities
                    are expressed in terms of it.
      CZ            body-axis vertical-force coefficient (explicit alias of ``CL``)
      CX            body-axis streamwise-force coefficient (≈ 0 — a surface-normal-
                    pressure VLM carries no leading-edge suction, and incidence/
                    camber/controls enter via normalwash, not geometric rotation)
      CL_wind       **wind-axis** lift coefficient (force ⊥ to U∞): the body-axis
                    resultant rotated through α, ``CL_wind = CZ·cosα − CX·sinα``.
                    Equals CZ only at α ≈ 0; this is the genuine CL.
      CD_wind       wind-axis (induced) drag coefficient = Trefftz ``CDi``.  NOT the
                    near-field projection ``CX·cosα + CZ·sinα`` (a no-LE-suction
                    flat-panel VLM gets that wrong); the Trefftz far-field value is
                    the physically meaningful wind-axis drag.
      CY            sideforce coefficient from vertical (sideforce) surfaces
      CM            pitching moment coefficient about xref, nose-up positive;
                    lift surfaces only; normalised by S_ref × c_ref. Each box
                    load acts at its 1/4-chord bound vortex (not the 3/4-chord
                    collocation point) — the physically correct moment arm.
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

    # Spanwise width of each box (used for Kutta-Joukowski lift).
    # K-J: F⃗ = ρ V⃗∞ × Γ Δs⃗; for V⃗∞ = (1,0,0), lift scales with Δy, not ‖Δs⃗‖.
    # Use the projected cross-flow width sqrt(Δy²+Δz²) so sweep and dihedral
    # are handled correctly without changing any caller.
    dy = np.array([
        float(math.sqrt((b.bound_b[1] - b.bound_a[1])**2
                      + (b.bound_b[2] - b.bound_a[2])**2))
        for b in boxes
    ])

    # Individual box chord = area / spanwise_width  (avoids relying on box.chord
    # which stores the CAERO1 macroelement chord, not the VLM panel chord)
    chord_box = np.array([
        boxes[i].area / dy[i] if dy[i] > _DEGEN_TOL else 1.0
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

    # Quarter-chord (bound-vortex) x of each box: the point at which the
    # Kutta-Joukowski force physically acts, and hence the correct moment arm
    # for the pitching moment.  Using the 3/4-chord collocation point instead
    # shifts every box load aft by half a box chord and inflates |CM| by
    # CL·(½·box_chord)/c_ref — a mesh-dependent bias that vanishes only as
    # NCHORD→∞.  Validated against AVL/VortexLattice.jl (val_vlm_byu_wing).
    x_qc = np.array([0.5 * (boxes[i].bound_a[0] + boxes[i].bound_b[0]) for i in range(n)])

    # Pressure coefficient per box: ΔCp = 2Γ / (V∞ · chord_box), V∞ = 1
    cp = 2.0 * gamma / chord_box

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
        span_ref = float(np.max(np.ptp(colloc_pts[:, 1:], axis=0))) + dy.mean()
        if span_ref < _DEGEN_TOL:
            span_ref = 1.0
        c_ref = S_ref / span_ref
        _ar = span_ref * span_ref / S_ref if S_ref > _DEGEN_TOL else 1.0

    # -----------------------------------------------------------------------
    # Trefftz-plane induced drag.  Decoupled strip body boxes shed NO trailing
    # vorticity (no wake), so they contribute nothing to the Trefftz wake integral —
    # zero their reconstructed circulation here.  Their (real) lift still counts in
    # CL/CZ above; only the induced-drag wake excludes them.
    # -----------------------------------------------------------------------
    gamma_wake = gamma
    if any(getattr(b, "is_strip", False) for b in boxes):
        gamma_wake = gamma.copy()
        gamma_wake[[i for i, b in enumerate(boxes) if getattr(b, "is_strip", False)]] = 0.0
    _cdi_result = trefftz_cdi(boxes, gamma_wake, S_ref, _ar)

    # -----------------------------------------------------------------------
    # Per-surface classification: horizontal (lift) vs vertical (sideforce)
    # -----------------------------------------------------------------------
    eid_to_indices: dict = defaultdict(list)
    for i, box in enumerate(boxes):
        eid_to_indices[box.caero_eid].append(i)

    surfaces: dict = {}
    for eid, idxs in eid_to_indices.items():
        mean_abs_normal = np.abs([boxes[i].normal for i in idxs]).mean(axis=0)
        stype = "lift" if mean_abs_normal[2] >= mean_abs_normal[1] else "sideforce"
        surfaces[eid] = {"type": stype, "indices": idxs}

    lift_indices = [i for s in surfaces.values() if s["type"] == "lift"  for i in s["indices"]]
    sf_indices   = [i for s in surfaces.values() if s["type"] == "sideforce" for i in s["indices"]]

    # -----------------------------------------------------------------------
    # Section loads: group by i_span (all surfaces, for backward compatibility)
    # -----------------------------------------------------------------------
    strips: dict = {}
    for i, box in enumerate(boxes):
        strips.setdefault(box.i_span, []).append(i)

    cl_section: dict = {}
    for s, idxs in sorted(strips.items()):
        dy_s = dy[idxs[0]]   # all boxes in a strip share the same spanwise width
        chord_strip = sum(boxes[i].area for i in idxs) / dy_s
        if chord_strip < _DEGEN_TOL:
            chord_strip = 1.0
        cl_section[s] = 2.0 * sum(gamma[i] for i in idxs) / chord_strip

    # -----------------------------------------------------------------------
    # Global CL (lift surfaces), CY (sideforce surfaces), CM (lift, about xref)
    # -----------------------------------------------------------------------
    lift_idx = np.array(lift_indices, dtype=int)
    sf_idx   = np.array(sf_indices,   dtype=int)

    L_lift = float(np.dot(gamma[lift_idx], dy[lift_idx])) if len(lift_idx) else 0.0
    L_sf   = float(np.dot(gamma[sf_idx],   dy[sf_idx]))   if len(sf_idx)   else 0.0

    CL = 2.0 * L_lift / S_ref      # body-axis vertical force (≡ CZ)
    CY = 2.0 * L_sf   / S_ref

    # ------------------------------------------------------------------ #
    # Wind-axis lift/drag (genuine CL/CD, ⊥ and ∥ to the freestream U∞).
    # The body-axis resultant is (CX, CZ); rotating through the angle of
    # attack gives CL_wind = CZ·cosα − CX·sinα.  CX = 2·Σ Γ·Δy·n_x / S_ref is
    # the body-streamwise force — ≈ 0 here because the panels carry only
    # surface-normal pressure (no leading-edge suction) and incidence/camber/
    # controls enter through the normalwash rather than a geometric panel tilt,
    # so for planar geometry CL_wind reduces to CZ·cosα.  The genuine wind-axis
    # (induced) drag is the Trefftz CDi, not the unreliable near-field
    # projection CX·cosα + CZ·sinα.  CL_wind = CZ only at α ≈ 0 (see §5.4 of
    # docs/20_theory/01_aeroelastics_theory.md).
    n_x = np.array([b.normal[0] for b in boxes])
    CX = 2.0 * float(np.dot(gamma * dy, n_x)) / S_ref
    ca, sa = math.cos(alpha), math.sin(alpha)
    CL_wind = CL * ca - CX * sa
    CD_wind = _cdi_result["CDi"]

    # Nose-up-positive pitching moment about xref.  Pressure form here
    # (cp·area·arm); the equivalent force form (Fz·arm) lives in
    # sol144._pitch_moment — the single source for the trim chain.  Both share
    # this `−Σ(...)·(x − xref)` sign convention (AE1 Step E); keep them aligned.
    CM = (
        -sum(cp[i] * boxes[i].area * (x_qc[i] - xref) for i in lift_indices)
        / (S_ref * c_ref)
    ) if lift_indices else 0.0

    # -----------------------------------------------------------------------
    # Per-surface coefficients
    # -----------------------------------------------------------------------
    per_surface: dict = {}
    for eid, sinfo in surfaces.items():
        idxs = sinfo["indices"]
        idx_arr = np.array(idxs, dtype=int)
        L_eid = float(np.dot(gamma[idx_arr], dy[idx_arr]))
        if sinfo["type"] == "lift":
            cl_eid = 2.0 * L_eid / S_ref
            cm_eid = (
                -sum(cp[i] * boxes[i].area * (x_qc[i] - xref) for i in idxs)
                / (S_ref * c_ref)
            ) if S_ref * c_ref > _DEGEN_TOL else 0.0
            per_surface[eid] = {"surface_type": "lift",      "CL": cl_eid, "CY": 0.0,    "CM": cm_eid}
        else:
            cy_eid = 2.0 * L_eid / S_ref
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
