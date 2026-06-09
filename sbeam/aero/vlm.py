"""Steady vortex-lattice aerodynamics — AIC matrix and rigid-wing solver.

Horseshoe-vortex convention (NASA SP-405):
  - Bound vortex at 1/4-chord of each box (from AeroBox.bound_a to bound_b)
  - Collocation (flow-tangency) point at 3/4-chord midspan (AeroBox.colloc)
  - Trailing legs extend downstream in +X to a finite far-field cutoff

Symmetry:
  parity=+1  symmetric lift (mirror image adds same-sign contribution)
  parity=-1  antisymmetric / roll (mirror image adds opposite-sign contribution)
  parity=0   no image (full-span model, or unsymmetric geometry)

All coordinates in global CID 0. Freestream V∞ = 1 in +X direction.
"""

import math
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
                        box: AeroBox, parity: int = 1) -> float:
    """Normalwash at colloc from a unit-strength horseshoe vortex at box.

    The horseshoe consists of:
      • bound segment  bound_a → bound_b
      • right trailing bound_b → far-field (+x)
      • left trailing  far-field (+x) → bound_a

    When parity != 0 an XZ-mirror image is added (symmetric/antisymmetric).
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
    w = float(np.dot(v, colloc_normal))

    if parity != 0:
        # Mirror about XZ plane: y → -y
        a_img = np.array([a[0], -a[1], a[2]])
        b_img = np.array([b[0], -b[1], b[2]])
        far_ai = np.array([far_x, -a[1], a[2]])
        far_bi = np.array([far_x, -b[1], b[2]])
        if parity > 0:
            # Symmetric: image bound reversed (b_img→a_img) so the left-wing
            # vortex produces the same-sign lift as the right wing.
            # The root trailing legs (y=0) cancel with the direct root trailing.
            v_img = (biot_savart_seg(colloc, b_img, a_img)
                     + biot_savart_seg(colloc, a_img, far_ai)
                     + biot_savart_seg(colloc, far_bi, b_img))
        else:
            # Antisymmetric: image bound in same-reflection direction (a_img→b_img)
            # so the left-wing vortex produces opposite-sign lift; root trailing doubles.
            v_img = (biot_savart_seg(colloc, a_img, b_img)
                     + biot_savart_seg(colloc, b_img, far_bi)
                     + biot_savart_seg(colloc, far_ai, a_img))
        w += float(np.dot(v_img, colloc_normal))

    return w


# ---------------------------------------------------------------------------
# AIC matrix assembly
# ---------------------------------------------------------------------------

def build_ajj(boxes: list, parity: int = 1) -> np.ndarray:
    """Build the n_box × n_box aerodynamic influence coefficient matrix.

    A[i, j] = normalwash at colloc_i per unit circulation at horseshoe_j.
    Uses the receiving panel's outward normal (ZAERO Eq. 3.49a), supporting
    arbitrary surface orientations (horizontal wings, vertical fins, etc.).
    """
    n = len(boxes)
    A = np.zeros((n, n))
    for i, box_i in enumerate(boxes):
        for j, box_j in enumerate(boxes):
            A[i, j] = horseshoe_influence(box_i.colloc, box_i.normal, box_j, parity)
    return A


# ---------------------------------------------------------------------------
# Rigid-wing solver
# ---------------------------------------------------------------------------

def solve_rigid_cl(boxes: list, alpha: float, beta: float = 0.0,
                   parity: int = 1) -> dict:
    """Solve flow-tangency for a rigid configuration at incidence alpha/beta (radians).

    alpha  — angle of attack (rad); loads horizontal surfaces.
    beta   — sideslip angle (rad); loads vertical surfaces (VTP/fins).

    Boundary condition per panel (ZAERO Eq. 3.28):
      rhs[i] = -(V⃗ · n̂_i)  with V⃗ ≈ [1, β, α] for small angles
             = -(α·n_z[i] + β·n_y[i])

    Returns a dict with keys:
      cp          (n,) pressure coefficient per box  (ΔCp = 2Γ / (V∞ · chord_box))
      cl_section  dict mapping i_span → section load coefficient
      CL          total normal-force coefficient (lift for wings; sideforce for fins)
      CM          pitching moment coefficient about x=0 (nose-up positive)

    ``parity`` controls the symmetry image (see module docstring).
    For parity=-1 the left and right wings cancel and CL = 0 exactly.
    """
    n = len(boxes)
    A = build_ajj(boxes, parity)

    # Flow-tangency: rhs[i] = -(alpha*n_z + beta*n_y) per panel
    rhs = np.array([-(alpha * b.normal[2] + beta * b.normal[1]) for b in boxes])
    gamma = np.linalg.solve(A, rhs)

    # Spanwise width of each box (used for Kutta-Joukowski lift)
    dy = np.array([float(np.linalg.norm(b.bound_b - b.bound_a)) for b in boxes])

    # Individual box chord = area / spanwise_width  (avoids relying on box.chord
    # which stores the CAERO1 macroelement chord, not the VLM panel chord)
    chord_box = np.array([
        boxes[i].area / dy[i] if dy[i] > _DEGEN_TOL else 1.0
        for i in range(n)
    ])

    # Pressure coefficient per box: ΔCp = 2Γ / (V∞ · chord_box), V∞ = 1
    cp = 2.0 * gamma / chord_box

    # Reference geometry — use the widest extent across Y and Z to handle
    # models that mix horizontal (Y-span) and vertical (Z-span) surfaces.
    S_ref = sum(b.area for b in boxes)
    colloc_pts = np.array([b.colloc for b in boxes])
    span_ref = float(np.max(np.ptp(colloc_pts[:, 1:], axis=0))) + dy.mean()
    if span_ref < _DEGEN_TOL:
        span_ref = 1.0
    c_ref = S_ref / span_ref

    # Section CL: group by i_span, use Kutta-Joukowski per strip
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

    # Full-span lift: right-half lift via Kutta-Joukowski; left-half = parity × right
    # CL = (1 + parity) × L_half / (0.5 × V² × S_full)
    # For parity ∈ {0, 1}: simplifies to 2 × L_half / S_ref
    # For parity = -1: left cancels right → CL = 0
    L_half = float(np.dot(gamma, dy))
    if parity == -1:
        CL = 0.0
    else:
        CL = 2.0 * L_half / S_ref

    # Pitching moment about x = 0 (nose-up positive)
    CM = -sum(cp[i] * boxes[i].area * boxes[i].colloc[0]
              for i in range(n)) / (S_ref * c_ref)

    return {"cp": cp, "cl_section": cl_section, "CL": float(CL), "CM": float(CM)}
