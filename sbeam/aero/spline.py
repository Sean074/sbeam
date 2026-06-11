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

Hermite basis functions (one per structural node i):
  phi_f[i]:  CubicHermiteSpline — unit function value at node i, zero slopes
  phi_d[i]:  CubicHermiteSpline — zero function values, unit slope at node i

g_slope contributions (streamwise incidence at box j from DOF d at grid i):
  Translation d<3: -z_hat[d] × d(phi_f[i])/ds  at t_j
  Rotation d>=3:   -y_hat[d-3] × d(phi_d[i])/ds  at t_j   (bending slope)
                   +dthx × x_hat[d-3] × phi_f[i](t_j)      (torsion)

g_disp contributions (3-D box displacement at box j from DOF d at grid i):
  Translation d<3: z_hat[d] × phi_f[i](t_j) × z_hat  (normal deflection)
  Rotation d>=3:   y_hat[d-3] × phi_d[i](t_j) × z_hat (from bending slope)

Rigid-body exactness (machine-precision gate for Phase C trim):
  Uniform rigid translation — g_slope @ u_g = 0 everywhere.
  Uniform rigid pitch       — g_slope @ u_g = uniform incidence everywhere.
"""

import warnings

import numpy as np
from scipy.interpolate import CubicHermiteSpline

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Spline2, Spline0
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
    """Fill g_slope and g_disp rows for all boxes covered by *sp*."""

    # Spline coordinate frame
    origin, R_cid = _get_transform(sp.cid, bulk.cord2rs)
    x_hat = R_cid[:, 0]   # spline axis (span)
    y_hat = R_cid[:, 1]   # bending-slope axis
    z_hat = R_cid[:, 2]   # surface normal / deflection direction

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

    # Project box collocation points onto spline axis
    t_covered = np.array([
        np.dot(boxes[gk].colloc - origin, x_hat) for gk in covered_gk
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

    # Extrapolation warning (>10% of span range)
    s_range = s_sorted[-1] - s_sorted[0]
    if s_range > 1e-12:
        for j_loc, (tj, gk) in enumerate(zip(t_covered, covered_gk)):
            if tj < s_sorted[0] - 0.1 * s_range or tj > s_sorted[-1] + 0.1 * s_range:
                warnings.warn(
                    f"SPLINE2 {sp.eid}: box k={gk} extrapolates >10% beyond SET1 span",
                    UserWarning,
                    stacklevel=3,
                )

    zeros_n = np.zeros(n_s)

    for i, gid in enumerate(gids_sorted):
        grid_i = grid_index[gid]
        base   = 6 * grid_i

        # --- Hermite function-value basis: unit value at node i, zero slopes ---
        y_f = zeros_n.copy()
        y_f[i] = 1.0
        cs_f       = CubicHermiteSpline(s_sorted, y_f, zeros_n)
        f_vals     = cs_f(t_covered)                  # shape (n_cov,)
        f_slopes   = cs_f.derivative()(t_covered)     # shape (n_cov,)

        # --- Hermite derivative-value basis: zero values, unit slope at i ---
        dy_f = zeros_n.copy()
        dy_f[i] = 1.0
        cs_d       = CubicHermiteSpline(s_sorted, zeros_n, dy_f)
        d_vals     = cs_d(t_covered)
        d_slopes   = cs_d.derivative()(t_covered)

        # ---- Translation DOFs (d = 0 Tx, 1 Ty, 2 Tz) ----
        for d in range(3):
            z_comp = z_hat[d]
            if abs(z_comp) < 1e-15:
                continue
            col = base + d
            # g_slope: downwash = -(z_hat projection) × d(phi_f)/ds
            g_slope[covered_arr, col] += -z_comp * f_slopes
            # g_disp: 3D box displacement = (z_hat projection) × phi_f × z_hat
            for comp in range(3):
                g_disp[3 * covered_arr + comp, col] += z_comp * z_hat[comp] * f_vals

        # ---- Rotation DOFs (d = 3 Rx, 4 Ry, 5 Rz) ----
        for d in range(3):
            col    = base + 3 + d
            y_comp = y_hat[d]   # bending-slope axis projection
            x_comp = x_hat[d]   # spline-axis / torsion projection

            # Bending slope contribution
            if abs(y_comp) > 1e-15:
                # g_slope: downwash = -(y_hat projection) × d(phi_d)/ds
                g_slope[covered_arr, col] += -y_comp * d_slopes
                # g_disp: 3D box displacement = (y_hat projection) × phi_d × z_hat
                for comp in range(3):
                    g_disp[3 * covered_arr + comp, col] += y_comp * z_hat[comp] * d_vals

            # Torsion contribution (incidence only, no normal displacement)
            if abs(x_comp) > 1e-15:
                g_slope[covered_arr, col] += sp.dthx * x_comp * f_vals


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

    # ATTACH (Step 47): not yet implemented — silently skip placeholder entries
    if bulk.attaches:
        warnings.warn(
            "ATTACH cards present but not yet implemented (Step 47); "
            "those boxes will have zero spline rows",
            UserWarning,
            stacklevel=2,
        )

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
