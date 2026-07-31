"""Structure-to-aero spline operators — Phase B.

Builds g_slope (n_box × n_g) and g_disp (3·n_box × n_g) from the BDF spline
cards SPLINE2, ATTACH (Step 47), and SPLINE0 (Step 47).  These operators feed
directly into coupling.build_qaa and coupling.build_fg.

SPLINE2 — NASTRAN infinite beam (linear) spline (AC7/AE14 rewrite, 2026-07-05)
------------------------------------------------------------------------------
Implements the MSC formulation exactly (MSC Aeroelastic Analysis User's Guide,
"Theory of Infinite Beam Splines" + "Summary of Matrices for Infinite Surface
and Beam Spline Interpolation", Eqs. 2-48…2-63):

  * Spline axis = the **CID y-axis** (MSC convention; QRG SPLINE2 remark 2).
    ŝ = R_cid[:,1] (axis), ĉ = R_cid[:,0] (chord / rigid-arm direction),
    ẑ = R_cid[:,2] (deflection direction).
  * Each SET1 grid attaches its DEFLECTION w_g = u·ẑ at axis station
    t = (r−origin)·ŝ with rigid chord arm χ = (r−origin)·ĉ.  Off-axis grids
    are legal — the rigid arm converts their deflection into twist information
    (the pre-AC7 Hermite collinearity restriction is gone).
  * The interpolant is an infinite beam on point supports: bending kernels
    |Δt|³/12EI (force) and −Δt|Δt|/4EI (moment), torsion kernel −|Δt|/2GJ,
    plus the rigid part a₀ + a₁·t − a₂·χ, closed by the equilibrium rows
    Rᵀq = 0 with R_i = [1, tᵢ, −χᵢ; 0,1,0; 0,0,1].
  * `DTOR = EI/GJ` (only the ratio matters; EI ≡ 1, GJ ≡ 1/DTOR).
  * `DZ` / `DTHX` / `DTHY` are ATTACHMENT FLEXIBILITIES added to the A-matrix
    diagonal: 0 → rigid attachment, > 0 → spring, negative (−1 conventionally)
    → DOF not attached.  DTHX attaches the grid rotation about ĉ (bending
    slope dw/dt); DTHY attaches the rotation about ŝ (torsion).
  * Deformed surface height at a box point: z(t, χ) = w(t) − χ·φ(t).
    g_slope row (streamwise incidence, nose-up positive)
        = −∂z/∂x = −[ ŝ[0]·(w′ − χ·φ′) − ĉ[0]·φ ]
    evaluated at the ¾-chord collocation point; g_disp rows carry z·ẑ at the
    ¼-chord force point (AE6), so force transfer is virtual-work paired.

All structural DOFs are in global CID 0 (d = 0…5 = Tx Ty Tz Rx Ry Rz).

Rigid-body exactness: any rigid motion gives grid data w = c₀ + c₁t + c₂χ
with matching attached rotations, which the rigid part (a₀, a₁, a₂) fits with
zero point loads — all six global rigid-body modes are reproduced to machine
precision by construction.
"""

import warnings

from typing import Optional

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Spline2, Spline0, Attach
from sbeam.assembly.coord_transform import get_transform
from sbeam.types import FloatArray
from sbeam.aero.panel import AeroBox


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def nchord_per_caero(boxes: list[AeroBox]) -> dict[int, int]:
    """Return {caero_eid: n_chord_boxes} from the meshed box list."""
    result: dict[int, int] = {}
    for box in boxes:
        eid = box.caero_eid
        result[eid] = max(result.get(eid, 0), box.j_chord + 1)
    return result


def build_id_to_k(boxes: list[AeroBox], nchord: dict[int, int]) -> dict[int, int]:
    """Return {nastran_box_id: box.k} for all boxes.

    NASTRAN box ID = CAERO1.EID + i_span * nchord + j_chord.
    """
    return {
        box.caero_eid + box.i_span * nchord[box.caero_eid] + box.j_chord: box.k
        for box in boxes
    }


def _covered_gk_for_range(
    caero_eid: int,
    id1: int,
    id2: int,
    boxes: list[AeroBox],
    id_to_k: dict[int, int],
) -> list[int]:
    """Return sorted list of global box indices (k) in the NASTRAN ID range."""
    result = []
    for nastran_id, gk in id_to_k.items():
        if boxes[gk].caero_eid == caero_eid and id1 <= nastran_id <= id2:
            result.append(gk)
    return sorted(result)


# ---------------------------------------------------------------------------
# SPLINE2 block builder
# ---------------------------------------------------------------------------

def _build_spline2_block(
    sp: Spline2,
    bulk: BulkData,
    boxes: list[AeroBox],
    grid_index: dict[int, int],
    id_to_k: dict[int, int],
    covered: list[bool],
    g_slope: FloatArray,
    g_disp: FloatArray,
) -> None:
    """Fill g_slope and g_disp rows for all boxes covered by *sp*.

    AE4 fix — corrected sweep projection, nodal-slope sign, and DTHX semantics.
    AE6 fix — g_disp evaluated at box.force_point (¼-chord), not box.colloc (¾-chord).
    """

    # Spline coordinate frame (MSC convention: axis = CID y-axis)
    origin, R_cid = get_transform(sp.cid, bulk.cord2rs)
    c_hat = R_cid[:, 0]   # chord / rigid-arm direction (CID x)
    s_hat = R_cid[:, 1]   # spline axis (CID y)
    z_hat = R_cid[:, 2]   # deflection direction (CID z)

    # Identify covered boxes
    covered_gk = _covered_gk_for_range(sp.caero, sp.id1, sp.id2, boxes, id_to_k)
    if not covered_gk:
        warnings.warn(
            f"SPLINE2 {sp.eid}: no boxes found in ID range "
            f"[{sp.id1}, {sp.id2}] for CAERO1 {sp.caero}",
            UserWarning,
            stacklevel=3,
        )
        return

    for gk in covered_gk:
        if covered[gk]:
            raise ValueError(
                f"SPLINE2 {sp.eid}: box k={gk} is already covered by another spline"
            )
        covered[gk] = True

    # --- SET1 grid stations and rigid-arm offsets ---
    set1 = bulk.set1s[sp.setg]
    if len(set1.grids) < 2:
        raise ValueError(
            f"SPLINE2 {sp.eid}: SET1 {sp.setg} has fewer than 2 grids; spline is singular"
        )
    gids = list(set1.grids)
    t_g = np.empty(len(gids))
    chi_g = np.empty(len(gids))
    for idx, gid in enumerate(gids):
        g = bulk.grids[gid]
        r = np.array([g.x, g.y, g.z]) - origin
        t_g[idx] = r @ s_hat
        chi_g[idx] = r @ c_hat

    # --- Attachment flexibilities (QRG SPLINE2 remark 3) ---
    #   0 → rigid, > 0 → spring flexibility, negative → not attached.
    dz_flex = sp.dz if sp.dz > 0.0 else 0.0
    if sp.dz < 0.0:
        warnings.warn(
            f"SPLINE2 {sp.eid}: DZ={sp.dz} < 0 is invalid; treating as rigid (0.0)",
            UserWarning,
            stacklevel=3,
        )
    dthx_attached = sp.dthx >= 0.0    # bending-slope rotation about c_hat
    dthy_attached = sp.dthy >= 0.0    # torsion rotation about s_hat

    # DTOR = EI/GJ (torsional flexibility ratio; only the ratio matters)
    dtor = sp.dtor
    if dtor <= 0.0:
        warnings.warn(
            f"SPLINE2 {sp.eid}: DTOR={sp.dtor} must be > 0; using 1.0",
            UserWarning,
            stacklevel=3,
        )
        dtor = 1.0
    EI = 1.0
    GJ = 1.0 / dtor

    # Extrapolation warning (>10% of the station range)
    t_range = t_g.max() - t_g.min()
    if t_range > 1e-12:
        for gk in covered_gk:
            tj = float((boxes[gk].colloc - origin) @ s_hat)
            if tj < t_g.min() - 0.1 * t_range or tj > t_g.max() + 0.1 * t_range:
                warnings.warn(
                    f"SPLINE2 {sp.eid}: a box extrapolates >10% beyond SET1 span",
                    UserWarning,
                    stacklevel=3,
                )
                break

    # ------------------------------------------------------------------ #
    # Attached-DOF bookkeeping.
    #   Each entry: (kind, grid_list_idx) with kind ∈ {"w", "thx", "thy"}.
    #   w   — grid deflection u·ẑ            (load: point force  P)
    #   thx — grid rotation ω·ĉ (bend slope) (load: bending moment M)
    #   thy — grid rotation ω·ŝ (torsion)    (load: torque        T)
    # ------------------------------------------------------------------ #
    dofs = [("w", i) for i in range(len(gids))]
    if dthx_attached:
        dofs += [("thx", i) for i in range(len(gids))]
    if dthy_attached:
        dofs += [("thy", i) for i in range(len(gids))]
    m = len(dofs)

    def _flex(kind: str) -> float:
        if kind == "w":
            return dz_flex
        if kind == "thx":
            return max(sp.dthx, 0.0)
        return max(sp.dthy, 0.0)

    # ------------------------------------------------------------------ #
    # Spline system  [[0, Rᵀ], [R, A + diag(flex)]] · [a; q] = [0; u]
    # (MSC Eqs. 2-54 / 2-58 / 2-59…2-63 with rigid arms.)
    #
    # Flexibility kernels between attached DOFs (Δ = t_d − t_e, D = |Δ|):
    #   (w, w)     :  D³/12EI − χ_d·χ_e·D/2GJ
    #   (w, thx)   : −Δ·D/4EI              (w at d due to unit moment at e)
    #   (thx, w)   : +Δ·D/4EI
    #   (thx, thx) : −D/2EI
    #   (w, thy)   : +χ_d·D/2GJ            (z = w − χφ; φ from unit torque = −D/2GJ)
    #   (thy, w)   : +χ_e·D/2GJ            (φ at d from arm torque −χ_e·P_e)
    #   (thy, thy) : −D/2GJ
    #   (thx, thy) :  0
    # A force P_e on a rigid arm χ_e applies axis loads (P_e, torque −χ_e·P_e).
    # ------------------------------------------------------------------ #
    n_sys = 3 + m
    sys_mat = np.zeros((n_sys, n_sys))
    for a_idx, (kd, i) in enumerate(dofs):
        # R row (rigid part): w = a0 + a1·t − a2·χ ; thx = a1 ; thy = a2
        if kd == "w":
            R_row = (1.0, t_g[i], -chi_g[i])
        elif kd == "thx":
            R_row = (0.0, 1.0, 0.0)
        else:
            R_row = (0.0, 0.0, 1.0)
        sys_mat[3 + a_idx, 0:3] = R_row
        sys_mat[0:3, 3 + a_idx] = R_row

        for b_idx, (ke, j) in enumerate(dofs):
            dt = t_g[i] - t_g[j]
            D = abs(dt)
            if kd == "w" and ke == "w":
                val = D**3 / (12.0 * EI) - chi_g[i] * chi_g[j] * D / (2.0 * GJ)
            elif kd == "w" and ke == "thx":
                val = -dt * D / (4.0 * EI)
            elif kd == "thx" and ke == "w":
                val = +dt * D / (4.0 * EI)
            elif kd == "thx" and ke == "thx":
                val = -D / (2.0 * EI)
            elif kd == "w" and ke == "thy":
                val = +chi_g[i] * D / (2.0 * GJ)
            elif kd == "thy" and ke == "w":
                val = +chi_g[j] * D / (2.0 * GJ)
            elif kd == "thy" and ke == "thy":
                val = -D / (2.0 * GJ)
            else:   # thx ↔ thy uncoupled
                val = 0.0
            sys_mat[3 + a_idx, 3 + b_idx] = val
        sys_mat[3 + a_idx, 3 + a_idx] += _flex(kd)

    # Scale-aware singularity guard: an EA-only SET1 (all arms ≈ 0) with
    # DTHY detached leaves the rigid twist a₂ unconstrained, which shows up
    # as a (near-)singular system rather than an exception from inv().
    if np.linalg.cond(sys_mat) > 1e12:
        raise ValueError(
            f"SPLINE2 {sp.eid}: singular beam-spline system (SET1 {sp.setg}). "
            "Common causes: all grids on the spline axis (no chord arms) with "
            "torsion detached (DTHY < 0) — attach torsion with DTHY ≥ 0 or add "
            "off-axis grids; all grids at one axis station with bending "
            "rotations detached (DTHX < 0). See MSC Aeroelastic UG "
            "'Attachment of Splines with Elastic Springs'."
        )
    sys_inv = np.linalg.inv(sys_mat)

    # ------------------------------------------------------------------ #
    # Structural-DOF → attached-DOF value matrix B  (m × 6·n_grid columns
    # touched).  w = u·ẑ (translations), thx = ω·ĉ, thy = ω·ŝ (rotations).
    # ------------------------------------------------------------------ #
    # Solution operator: [a; q] = sys_inv @ [0; u_dof] — only the last m
    # columns of sys_inv matter:
    sol_op = sys_inv[:, 3:]                       # (n_sys, m)

    # ------------------------------------------------------------------ #
    # Box evaluation rows.
    #   z(t, χ)      = a0 + a1·t − a2·χ + Σ_e K_z(e)·q_e
    #   ∂z/∂x_basic  = ŝ[0]·(w′ − χ·φ′) − ĉ[0]·φ
    # with per-load kernels (Δ = t − t_e, D = |Δ|, sg = sign(Δ)):
    #   w:  P → D³/12EI ; M → −Δ·D/4EI ; T → 0
    #   w′: P → Δ·D/4EI ; M → −D/2EI   ; T → 0
    #   φ:  P → +χ_e·D/2GJ ; T → −D/2GJ ; M → 0
    #   φ′: P → +χ_e·sg/2GJ ; T → −sg/2GJ ; M → 0
    # ------------------------------------------------------------------ #
    def _eval_rows(pt: FloatArray) -> tuple[FloatArray, FloatArray]:
        r = pt - origin
        t = float(r @ s_hat)
        chi = float(r @ c_hat)
        E_z = np.zeros(n_sys)
        E_dzdx = np.zeros(n_sys)
        # rigid part
        E_z[0:3] = (1.0, t, -chi)
        E_dzdx[0:3] = (0.0, s_hat[0], -c_hat[0])
        for b_idx, (ke, j) in enumerate(dofs):
            dt = t - t_g[j]
            D = abs(dt)
            sg = np.sign(dt)
            if ke == "w":
                w_v, wp = D**3 / (12.0 * EI), dt * D / (4.0 * EI)
                ph, php = chi_g[j] * D / (2.0 * GJ), chi_g[j] * sg / (2.0 * GJ)
            elif ke == "thx":
                w_v, wp = -dt * D / (4.0 * EI), -D / (2.0 * EI)
                ph, php = 0.0, 0.0
            else:   # thy
                w_v, wp = 0.0, 0.0
                ph, php = -D / (2.0 * GJ), -sg / (2.0 * GJ)
            E_z[3 + b_idx] = w_v - chi * ph
            E_dzdx[3 + b_idx] = s_hat[0] * (wp - chi * php) - c_hat[0] * ph
        return E_z, E_dzdx

    # Weight rows through the solution operator once per box, then scatter
    # into the global g_slope / g_disp columns per structural DOF.
    for gk in covered_gk:
        box = boxes[gk]
        _, E_dzdx = _eval_rows(box.colloc)
        E_zf, _ = _eval_rows(box.force_point)
        w_slope = -(E_dzdx @ sol_op)              # (m,) incidence weights
        w_force = E_zf @ sol_op                   # (m,) deflection weights
        for a_idx, (kd, i) in enumerate(dofs):
            base = 6 * grid_index[gids[i]]
            if kd == "w":
                vecs = z_hat
                col0 = base
            elif kd == "thx":
                vecs = c_hat
                col0 = base + 3
            else:
                vecs = s_hat
                col0 = base + 3
            for d in range(3):
                if abs(vecs[d]) < 1e-15:
                    continue
                g_slope[gk, col0 + d] += vecs[d] * w_slope[a_idx]
                for comp in range(3):
                    if abs(z_hat[comp]) < 1e-15:
                        continue
                    g_disp[3 * gk + comp, col0 + d] += (
                        vecs[d] * z_hat[comp] * w_force[a_idx]
                    )


def _register_spline0(
    sp: Spline0,
    boxes: list[AeroBox],
    id_to_k: dict[int, int],
    covered: list[bool],
) -> None:
    """Mark SPLINE0 boxes as covered (rows stay zero — no structural coupling)."""
    covered_gk = _covered_gk_for_range(sp.caero, sp.id1, sp.id2, boxes, id_to_k)
    if not covered_gk:
        warnings.warn(
            f"SPLINE0 {sp.eid}: no boxes found in ID range "
            f"[{sp.id1}, {sp.id2}] for CAERO1 {sp.caero}",
            UserWarning,
            stacklevel=3,
        )
        return
    for gk in covered_gk:
        if covered[gk]:
            raise ValueError(
                f"SPLINE0 {sp.eid}: box k={gk} is already covered by another spline"
            )
        covered[gk] = True


def _build_attach_rows(
    attach: Attach,
    bulk: BulkData,
    boxes: list[AeroBox],
    grid_index: dict[int, int],
    id_to_k: dict[int, int],
    covered: list[bool],
    g_slope: FloatArray,
    g_disp: FloatArray,
) -> None:
    """Fill g_slope and g_disp rows for boxes rigidly attached to a master GRID.

    Rigid-body kinematics (CID=0, global frame):
      lever r = box.force_point − master_pos  (¼-chord; AE6 fix)

    g_slope (streamwise incidence, nose-up positive — same sense as SPLINE2 and
    the ANGLEA column; build_djk = −I turns it into normalwash).  For a rigid
    rotation ω the surface displacement is u = ω×r, so

        ∂u/∂x = ω × x̂ = (0, ω_z, −ω_y)
        α = −(∂u/∂x)·n̂ = ω_y·n_z − ω_z·n_y

    giving, per box normal n̂ (DEF-H1, 2026-07-31):
      Tx/Ty/Tz: zero (uniform translation → zero slope)
      Rx: zero (roll about the streamwise axis induces no streamwise slope)
      Ry: +n_z  (pitch; +1 for a z-normal box — nose-up ⇒ nose-up incidence)
      Rz: −n_y  (yaw; drives incidence on fins and other y-normal boxes)

    g_disp (z-component of normal displacement):
      (ω×r)_z = Rx·ry − Ry·rx  evaluated at force_point
      col_Tz: +1.0, col_Rx: +ry, col_Ry: −rx

    Note g_disp carries only the z-row, so force transfer of the in-plane Fx/Fy
    components (non-z-normal boxes) is not yet implemented — see backlog DEF-M11.
    """
    if attach.cid != 0:
        raise NotImplementedError(
            f"ATTACH {attach.eid}: CID={attach.cid} != 0 not supported; use CID=0"
        )
    if attach.grid not in bulk.grids or attach.grid not in grid_index:
        raise ValueError(
            f"ATTACH {attach.eid}: master GRID {attach.grid} not found in structural model"
        )

    covered_gk = _covered_gk_for_range(attach.caero, attach.id1, attach.id2, boxes, id_to_k)
    if not covered_gk:
        warnings.warn(
            f"ATTACH {attach.eid}: no boxes found in ID range "
            f"[{attach.id1}, {attach.id2}] for CAERO1 {attach.caero}",
            UserWarning,
            stacklevel=3,
        )
        return

    for gk in covered_gk:
        if covered[gk]:
            raise ValueError(
                f"ATTACH {attach.eid}: box k={gk} is already covered by another spline"
            )
        covered[gk] = True

    g = bulk.grids[attach.grid]
    master_pos = np.array([g.x, g.y, g.z])
    col_base = 6 * grid_index[attach.grid]
    covered_arr = np.array(covered_gk, dtype=int)

    # Lever arm from master to ¼-chord force point (AE6: was box.colloc)
    force_pts = np.array([boxes[gk].force_point for gk in covered_gk])
    r = force_pts - master_pos      # (n_cov, 3)
    rx = r[:, 0]                    # streamwise lever
    ry = r[:, 1]                    # spanwise lever

    # g_slope: rigid-rotation incidence α = ω_y·n_z − ω_z·n_y (DEF-H1).
    # The Rx column stays zero — roll induces no streamwise slope.
    normals = np.array([boxes[gk].normal for gk in covered_gk])   # (n_cov, 3)
    g_slope[covered_arr, col_base + 4] = normals[:, 2]    # Ry: +n_z
    g_slope[covered_arr, col_base + 5] = -normals[:, 1]   # Rz: −n_y

    # g_disp: z-component of normal displacement
    row_z = 3 * covered_arr + 2
    g_disp[row_z, col_base + 2] = 1.0   # Tz
    g_disp[row_z, col_base + 3] = ry    # Rx: (ω×r)_z = ry
    g_disp[row_z, col_base + 4] = -rx   # Ry: (ω×r)_z = −rx


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_g_spline(
    bulk: BulkData,
    boxes: list[AeroBox],
    grid_index: dict[int, int],
) -> tuple[Optional[FloatArray], Optional[FloatArray]]:
    """Build the displacement and slope spline operators from BDF spline cards.

    Returns (g_slope, g_disp) where:
      g_slope : FloatArray, shape (n_box, 6 * n_grid) — g-DOF → streamwise incidence
      g_disp  : FloatArray, shape (3 * n_box, 6 * n_grid) — g-DOF → 3-D box displacement

    Returns (None, None) when no spline cards are present.

    Raises ValueError if:
      - A box is covered by more than one spline
      - A SPLINE2 SET1 has fewer than 2 grids
    Issues UserWarning if:
      - A SPLINE2 box range contains no boxes
      - Any box has no spline coverage (g_slope / g_disp rows will be zero)
      - A box collocation point extrapolates >10% beyond the SET1 span range
      - SPLINE2 DTHX carries a non-±1 value (treated as detached)
      - SPLINE2 DTOR ≠ 1.0 (torsional flexibility ratio ignored)
      - SPLINE2 DTHZ carries a value other than 0.0 / −1.0 (Rz attachment not
        modelled; treated as detached)
    """
    has_splines = bool(bulk.spline2s or bulk.attaches or bulk.spline0s)
    if not has_splines:
        return None, None

    n_k = len(boxes)
    n_g = 6 * len(grid_index)
    g_slope = np.zeros((n_k, n_g))
    g_disp  = np.zeros((3 * n_k, n_g))
    covered = [False] * n_k

    nchord  = nchord_per_caero(boxes)
    id_to_k = build_id_to_k(boxes, nchord)

    for sp in bulk.spline2s.values():
        _build_spline2_block(sp, bulk, boxes, grid_index, id_to_k, covered, g_slope, g_disp)

    for attach in bulk.attaches.values():
        _build_attach_rows(attach, bulk, boxes, grid_index, id_to_k, covered, g_slope, g_disp)

    for sp0 in bulk.spline0s.values():
        _register_spline0(sp0, boxes, id_to_k, covered)

    # Warn on un-splined boxes
    for gk, is_covered in enumerate(covered):
        if not is_covered:
            box = boxes[gk]
            warnings.warn(
                f"Box k={gk} (CAERO1 {box.caero_eid}, "
                f"i_span={box.i_span}, j_chord={box.j_chord}) "
                f"has no spline coverage — g_slope / g_disp rows are zero",
                UserWarning,
                stacklevel=2,
            )

    return g_slope, g_disp
