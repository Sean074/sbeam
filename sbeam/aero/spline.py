"""Structure-to-aero spline operators — Phase B.

Builds g_slope (n_box × n_g) and g_disp (3·n_box × n_g) from the BDF spline
cards SPLINE2, ATTACH (Step 47), and SPLINE0 (Step 47).  These operators feed
directly into coupling.build_qaa and coupling.build_fg.

Coordinate convention
---------------------
SPLINE2 CID defines the spline axis:
  x_hat = CID x-axis in global frame  (span / spline direction)
  y_hat = CID y-axis in global frame  (bending-slope axis)
  z_hat = CID z-axis in global frame  (surface normal / deflection direction)

All structural DOFs are in global CID 0:
  d=0 Tx, d=1 Ty, d=2 Tz, d=3 Rx, d=4 Ry, d=5 Rz

The streamwise downwash at a box is w = −∂h/∂x.  Using the chain rule with
s = (r − origin)·x_hat, ∂h/∂x = (dh/ds)·x_hat[0], so

    w = −(dh/ds)·x_hat[0]

With the Hermite interpolation h(s) = Σ [φ_f[i]·h_i + φ_d[i]·(dh/ds)_i] the
physical nodal slope is

    (dh/ds)_i = −(ω·y_hat)_i   (AE4b sign convention)

Combining:

  Translation (d<3):   g_slope contribution = −(z_hat[d]·x_hat[0]) · dφ_f[i]/ds
  Rotation (bending):  g_slope contribution = +(y_hat[d-3]·x_hat[0]) · dφ_d[i]/ds
  Rotation (torsion):  g_slope contribution = x_hat[d-3] · φ_f[i]
                       (only when DTHX = 1; DTHX = −1 detaches the DOF)

Both divide by x_hat[0] — or equivalently multiply by (·/x_hat[0]) — via:
  w = −(dh/ds)/x_hat[0] when (dh/ds) is the axis-direction derivative.

Wait, the chain rule gives ∂h/∂x = (dh/ds)·x_hat[0], NOT (dh/ds)/x_hat[0].
The correct formula is therefore:

  g_slope += −z_hat[d] · x_hat[0] · dφ_f/ds       (translation)
  g_slope += +y_hat[d-3] · x_hat[0] · dφ_d/ds     (bending slope, sign-corrected)

For an unswept CID=0 (x_hat[0]=1): translation unchanged, bending slope sign-
flipped from the pre-AE4 code.  For a swept axis: additional factor x_hat[0].

However: the ZAERO Theo §6.3 beam spline uses w = −(dh/ds)/x_hat[0] (division),
which correctly handles the physical meaning:

  physical (dh/ds) along the swept axis = x_hat[0] · (−θ) for rigid pitch θ
  → (dh/ds)/x_hat[0] = −θ  →  w = θ  ✓

The division formula is the correct one; the multiplication formula reproduces
the spline slope but does NOT equal ∂h/∂x when the spline axis is swept (because
the spline only "sees" the 1D projection of the 2D displacement field).

Concretely:
  g_slope (translation d<3):   −(z_hat[d] / x_hat[0]) · dφ_f[i]/ds
  g_slope (bending, d>=3):     +(y_hat[d-3] / x_hat[0]) · dφ_d[i]/ds
  g_slope (torsion, d>=3):     +x_hat[d-3] · φ_f[i]   (when DTHX = 1)

g_disp evaluation: AE6 fix — displacement for virtual-work force transfer is
evaluated at the box force_point (¼-chord bound-vortex midpoint), not at the
¾-chord collocation point.  g_slope stays at the collocation point.

DTHX semantics (AE4c): MSC SPLINE2 DTHX = −1 means "do not attach the
rotational DOF to the spline" (detached).  DTHX = 1 (default) means attached.
Values other than ±1 represent elastic attachment flexibility (not supported;
treated as detached with a warning).

Rigid-body exactness (machine-precision gate for Phase C trim):
  Uniform rigid plunge  — g_slope @ u_g = 0 everywhere.
  Uniform rigid pitch   — g_slope @ u_g = uniform incidence everywhere.
"""

import warnings

import numpy as np
from scipy.interpolate import CubicHermiteSpline

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Spline2, Spline0, Attach
from sbeam.aero.panel import AeroBox
from sbeam.assembly.coord_transform import _get_transform


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _nchord_per_caero(boxes: list) -> dict:
    """Return {caero_eid: n_chord_boxes} from the meshed box list."""
    result: dict = {}
    for box in boxes:
        eid = box.caero_eid
        result[eid] = max(result.get(eid, 0), box.j_chord + 1)
    return result


def _build_id_to_k(boxes: list, nchord: dict) -> dict:
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
    boxes: list,
    id_to_k: dict,
) -> list:
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
    boxes: list,
    grid_index: dict,
    id_to_k: dict,
    covered: list,
    g_slope: np.ndarray,
    g_disp: np.ndarray,
) -> None:
    """Fill g_slope and g_disp rows for all boxes covered by *sp*.

    AE4 fix — corrected sweep projection, nodal-slope sign, and DTHX semantics.
    AE6 fix — g_disp evaluated at box.force_point (¼-chord), not box.colloc (¾-chord).
    """

    # Spline coordinate frame
    origin, R_cid = _get_transform(sp.cid, bulk.cord2rs)
    x_hat = R_cid[:, 0]   # spline axis (span direction)
    y_hat = R_cid[:, 1]   # bending-slope axis
    z_hat = R_cid[:, 2]   # surface normal / deflection direction

    x0 = x_hat[0]   # freestream projection of spline axis (= cos Λ for swept wing)

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

    covered_arr = np.array(covered_gk, dtype=int)

    # --- Evaluation coordinates along the spline axis ---
    # g_slope: flow tangency enforced at ¾-chord collocation point
    t_slope = np.array([
        np.dot(boxes[gk].colloc       - origin, x_hat) for gk in covered_gk
    ])
    # g_disp: virtual-work force transfer at ¼-chord bound-vortex midpoint (AE6)
    t_force = np.array([
        np.dot(boxes[gk].force_point  - origin, x_hat) for gk in covered_gk
    ])

    # Project structural grids onto spline axis and sort
    set1 = bulk.set1s[sp.setg]
    if len(set1.grids) < 2:
        raise ValueError(
            f"SPLINE2 {sp.eid}: SET1 {sp.setg} has fewer than 2 grids; spline is singular"
        )

    s_gid = []
    for gid in set1.grids:
        g = bulk.grids[gid]
        s_i = np.dot(np.array([g.x, g.y, g.z]) - origin, x_hat)
        s_gid.append((s_i, gid))
    s_gid.sort(key=lambda item: item[0])

    s_sorted = np.array([item[0] for item in s_gid])
    gids_sorted = [item[1] for item in s_gid]
    n_s = len(gids_sorted)

    # --- SET1 collinearity check (AE1 Step B3) ---
    # SPLINE2 is a 1-D beam spline: SET1 must lie along the spline axis. Off-axis
    # grids carry a chordwise displacement at the same s that the Hermite cannot
    # back out (proof: nodal slope projection m_i = −ω·ŷ only constrains dh/ds at
    # the node, not h_i; chord-offset δh_i flows through and aliases as spurious
    # bending). Detect and refuse rather than silently corrupting Q_aa.
    s_range = s_sorted[-1] - s_sorted[0]
    if s_range > 1e-12:
        offsets = []
        for s_i, gid in s_gid:
            g = bulk.grids[gid]
            r = np.array([g.x, g.y, g.z]) - origin
            delta_chord = float(np.dot(r, y_hat))
            offsets.append((gid, g.x, g.y, g.z, s_i, delta_chord))
        max_abs_offset = max(abs(o[5]) for o in offsets)
        if max_abs_offset > 0.05 * s_range:
            offenders = [o for o in offsets if abs(o[5]) > 0.05 * s_range]
            lines = [
                f"  GRID {o[0]} at (x={o[1]:.4f}, y={o[2]:.4f}, z={o[3]:.4f}): "
                f"s={o[4]:.4f}, chord offset Δ={o[5]:+.4f}"
                for o in offenders
            ]
            raise ValueError(
                f"SPLINE2 {sp.eid}: SET1 {sp.setg} contains grids that are not "
                f"collinear along the spline axis x̂={tuple(round(v, 6) for v in x_hat)}.\n"
                f"  span range = {s_range:.4f}; tolerance = {0.05 * s_range:.4f} "
                f"(5% of span range)\n"
                f"  max |chord offset| = {max_abs_offset:.4f}\n"
                f"Offending grids (chord offset Δ = (r−origin)·ŷ_spline):\n"
                + "\n".join(lines)
                + "\n"
                "SPLINE2 is a 1-D beam spline; SET1 must lie along the elastic axis. "
                "Either move the offending grids onto the EA, build an EA-only SET1 "
                "(commonly the wing CBAR endpoints), or use SPLINE1 (IPS) for 2-D "
                "grid scatter once it is available."
            )

    # Extrapolation warning (>10% of span range)
    # NB: s_range is computed above for the collinearity check
    if s_range > 1e-12:
        for tj in t_slope:
            if tj < s_sorted[0] - 0.1 * s_range or tj > s_sorted[-1] + 0.1 * s_range:
                warnings.warn(
                    f"SPLINE2 {sp.eid}: a box extrapolates >10% beyond SET1 span",
                    UserWarning,
                    stacklevel=3,
                )
                break

    zeros_n = np.zeros(n_s)

    # DTHX attachment switch (AE4c):
    #   DTHX = 1.0  → attached  (standard torsion coupling)
    #   DTHX = −1.0 → detached  (do not couple rotational DOF to spline)
    #   other       → not supported; warn and treat as detached
    dthx_attached = False
    if sp.dthx == 1.0:
        dthx_attached = True
    elif sp.dthx == -1.0:
        pass   # detached — skip torsion contribution
    else:
        warnings.warn(
            f"SPLINE2 {sp.eid}: DTHX={sp.dthx} rotational attachment flexibility "
            "not supported; treating as detached",
            UserWarning,
            stacklevel=3,
        )

    # DTOR / DTHZ (AE12): parsed and stored but not modelled by the beam spline.
    #   DTOR ≠ 1.0        → torsional-to-bending flexibility ratio is ignored.
    #   DTHZ ∈ {0.0,−1.0} → blank/default or NASTRAN "Rz detached" — matches sbeam's
    #                       behaviour (Rz never coupled), so silent.
    #   other DTHZ        → the card asks for Rz attachment sbeam cannot model.
    if sp.dtor != 1.0:
        warnings.warn(
            f"SPLINE2 {sp.eid}: DTOR={sp.dtor} torsional flexibility ratio "
            "not supported; value ignored (treated as 1.0)",
            UserWarning,
            stacklevel=3,
        )
    if sp.dthz not in (0.0, -1.0):
        warnings.warn(
            f"SPLINE2 {sp.eid}: DTHZ={sp.dthz} Rz rotational attachment "
            "not supported; treating as detached",
            UserWarning,
            stacklevel=3,
        )

    for i, gid in enumerate(gids_sorted):
        grid_i = grid_index[gid]
        base   = 6 * grid_i

        # --- Hermite function-value basis: unit value at node i, zero slopes ---
        y_f = zeros_n.copy()
        y_f[i] = 1.0
        cs_f = CubicHermiteSpline(s_sorted, y_f, zeros_n)
        f_vals_slope  = cs_f(t_slope)                      # shape (n_cov,)
        f_slopes_slope = cs_f.derivative()(t_slope)        # shape (n_cov,)
        f_vals_force  = cs_f(t_force)                      # shape (n_cov,)

        # --- Hermite derivative-value basis: zero values, unit slope at i ---
        dy_f = zeros_n.copy()
        dy_f[i] = 1.0
        cs_d = CubicHermiteSpline(s_sorted, zeros_n, dy_f)
        d_vals_force  = cs_d(t_force)
        d_slopes_slope = cs_d.derivative()(t_slope)

        # ---- Translation DOFs (d = 0 Tx, 1 Ty, 2 Tz) ----
        for d in range(3):
            z_comp = z_hat[d]
            if abs(z_comp) < 1e-15:
                continue
            col = base + d

            # g_slope (AE1 Step B): chordwise-rigid section reconstruction gives
            # u_z(x, y) = h(s(x, y)) along the spline axis. The streamwise
            # downwash is w = −∂u_z/∂x_basic = −(dh/ds)·(∂s/∂x_basic).
            # Since s = (r − origin)·x̂, ∂s/∂x_basic = x̂[0]. Therefore:
            #
            #     w = −x̂[0] · (dh/ds)
            #
            # Multiplication, not division — the previous (z_comp / x0) form was
            # self-consistent only for the "rigid-along-spline-axis" kinematic
            # (V-AE2b) and produced spurious downwash under genuine basic-frame
            # rigid-body modes on a swept spline (V-AE1b).
            g_slope[covered_arr, col] += -z_comp * x0 * f_slopes_slope

            # g_disp: evaluated at force_point (AE6); formula unchanged
            for comp in range(3):
                g_disp[3 * covered_arr + comp, col] += z_comp * z_hat[comp] * f_vals_force

        # ---- Rotation DOFs (d = 3 Rx, 4 Ry, 5 Rz) ----
        for d in range(3):
            col    = base + 3 + d
            y_comp = y_hat[d]   # bending-slope axis projection
            x_comp = x_hat[d]   # spline-axis / torsion projection

            # --- Bending slope contribution ---
            # Physical nodal slope (AE4b sign): (dh/ds)_i = −y_comp · ω_i.
            # AE1 Step B: streamwise downwash uses the multiplication form
            # w = −x̂[0]·(dh/ds), so the nodal contribution becomes
            #
            #     g_slope += +y_comp · x̂[0] · (dφ_d/ds)
            if abs(y_comp) > 1e-15:
                g_slope[covered_arr, col] += y_comp * x0 * d_slopes_slope

                # g_disp: h contribution = φ_d[i]·(dh/ds)_i = φ_d[i]·(−y_comp·ω)
                # → g_disp entry = −y_comp · φ_d[i] · z_hat  (AE4b sign, AE6 force point)
                for comp in range(3):
                    g_disp[3 * covered_arr + comp, col] += (
                        -y_comp * z_hat[comp] * d_vals_force
                    )

            # --- Torsion contribution ---
            # A section rotated about x̂_spline by θ_t produces u_z = θ_t · ζ
            # at a chordwise point with offset ζ along ŷ_spline. The streamwise
            # gradient is ∂u_z/∂x_basic = θ_t · y_hat[0] (since ∂ζ/∂x_basic =
            # y_hat[0] for chordwise-rigid sections), so
            #
            #     w_torsion = −y_hat[0] · θ_t = −y_hat[0] · x_comp · ω_basic[d]
            #
            # AE1 Step B: previously this was just x_comp · f_vals_slope, which
            # is correct only when y_hat[0] = −1 (unswept spline) and happened to
            # match a swept case by accident. With the corrected formula and
            # multiplication-bending above, the spline reproduces all 6 global
            # basic-frame rigid-body modes exactly on planar (z = 0) wings.
            # DTHX = 1: attached; DTHX = −1: detached (skip).
            if dthx_attached and abs(x_comp) > 1e-15:
                g_slope[covered_arr, col] += -y_hat[0] * x_comp * f_vals_slope

                # g_disp: torsion adds u = θ_t · ζ · ẑ_spline at the box force
                # point, distributed back to nodes through the same function-
                # value Hermite basis used for translation. ζ_k is computed at
                # the box force_point (AE6: ¼-chord).
                zeta_force = np.array([
                    float(np.dot(boxes[gk].force_point - origin, y_hat))
                    for gk in covered_gk
                ])
                for comp in range(3):
                    g_disp[3 * covered_arr + comp, col] += (
                        x_comp * zeta_force * z_hat[comp] * f_vals_force
                    )


def _register_spline0(
    sp: Spline0,
    boxes: list,
    id_to_k: dict,
    covered: list,
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
    boxes: list,
    grid_index: dict,
    id_to_k: dict,
    covered: list,
    g_slope: np.ndarray,
    g_disp: np.ndarray,
) -> None:
    """Fill g_slope and g_disp rows for boxes rigidly attached to a master GRID.

    Rigid-body kinematics (CID=0, global frame):
      lever r = box.force_point − master_pos  (¼-chord; AE6 fix)

    g_slope (downwash = −∂u_z/∂x):
      Tz: zero (uniform plunge → zero slope)
      Rx: +1.0 (torsion coupling)
      Ry: −1.0 (pitch → uniform slope −1)

    g_disp (z-component of normal displacement):
      (ω×r)_z = Rx·ry − Ry·rx  evaluated at force_point
      col_Tz: +1.0, col_Rx: +ry, col_Ry: −rx
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

    # g_slope: rigid-body downwash contributions (unchanged from pre-AE6)
    g_slope[covered_arr, col_base + 3] = 1.0    # Rx torsion
    g_slope[covered_arr, col_base + 4] = -1.0   # Ry pitch

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
    boxes: list,
    grid_index: dict,
) -> tuple:
    """Build the displacement and slope spline operators from BDF spline cards.

    Returns (g_slope, g_disp) where:
      g_slope : np.ndarray, shape (n_box, 6 * n_grid) — g-DOF → streamwise incidence
      g_disp  : np.ndarray, shape (3 * n_box, 6 * n_grid) — g-DOF → 3-D box displacement

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

    nchord  = _nchord_per_caero(boxes)
    id_to_k = _build_id_to_k(boxes, nchord)

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
