"""CAERO1 box meshing — trapezoidal aerodynamic panels.

Each CAERO1 macroelement is meshed into NSPAN × NCHORD trapezoidal boxes.
Per box: bound vortex segment at the box 1/4-chord, collocation point at the
box 3/4-chord (horseshoe-vortex lattice convention, NASA SP-405).

All coordinates are in global CID 0.
"""

import numpy as np
from dataclasses import dataclass

from sbeam.model.aero import Caero1, Paero1
from sbeam.assembly.coord_transform import _get_transform


@dataclass
class AeroBox:
    k:          int           # global sequential index (0-based across all CAERO1 elements)
    caero_eid:  int
    i_span:     int           # spanwise index within parent CAERO1 (0-based)
    j_chord:    int           # chordwise index within parent CAERO1 (0-based)
    corners:    np.ndarray    # (4, 3): [root-LE, tip-LE, tip-TE, root-TE] in CID 0
    colloc:     np.ndarray    # (3,): 3/4-chord midspan collocation point
    bound_a:     np.ndarray    # (3,): 1/4-chord bound vortex, root side
    bound_b:     np.ndarray    # (3,): 1/4-chord bound vortex, tip side
    force_point: np.ndarray    # (3,): 1/4-chord bound-vortex midpoint = (bound_a + bound_b)/2
    area:        float
    normal:     np.ndarray    # (3,) outward unit normal
    chord:      float         # mean chord of the box
    span_frac:  float         # spanwise fraction at box mid-span [0, 1]
    is_strip:   bool = False  # True ⇒ decoupled strip body box (no AIC coupling; set
                              # by build_aero_model from the CAERO1 PID → PSTRIP)


def mesh_caero1(
    caero: Caero1,
    paero: Paero1,
    aefacts: dict,
    cord2rs: dict,
    start_k: int = 0,
) -> list:
    """Mesh one CAERO1 macroelement into a flat list of AeroBox objects.

    Bound vortex at 1/4 of the box chord; collocation at 3/4 of the box chord.
    P1/P4 are transformed from the CP coordinate system to global CID 0.
    The freestream direction is assumed to be +X in CID 0 (ACSID=0).

    Args:
        caero:    Parsed CAERO1 card.
        paero:    Corresponding PAERO1 (stub in Phase A, unused).
        aefacts:  Dict of {sid: Aefact} for LSPAN/LCHORD lookups.
        cord2rs:  Dict of {cid: Cord2r} for CP coordinate transform.
        start_k:  Starting value for the global box index k.

    Returns:
        List of AeroBox in row-major order (span varies slowest, chord fastest).
    """
    # Resolve P1 and P4 from the CP coordinate system to global CID 0
    origin, R = _get_transform(caero.cp, cord2rs)
    p1 = origin + R @ np.array(caero.p1, dtype=float)
    p4 = origin + R @ np.array(caero.p4, dtype=float)

    # Build span fraction breakpoints η ∈ [0, 1], length nspan+1
    if caero.nspan > 0:
        eta = np.linspace(0.0, 1.0, caero.nspan + 1)
    else:
        eta = np.asarray(aefacts[caero.lspan].data, dtype=float)

    # Build chord fraction breakpoints ξ ∈ [0, 1], length nchord+1
    if caero.nchord > 0:
        xi = np.linspace(0.0, 1.0, caero.nchord + 1)
    else:
        xi = np.asarray(aefacts[caero.lchord].data, dtype=float)

    nspan_boxes  = len(eta) - 1
    nchord_boxes = len(xi) - 1

    # Freestream direction: +X in CID 0 (ACSID=0 assumed in Phase A)
    x_hat = np.array([1.0, 0.0, 0.0])

    def _le(e: float) -> np.ndarray:
        """Leading-edge point at span fraction e."""
        return p1 + e * (p4 - p1)

    def _chord_len(e: float) -> float:
        """Chord length at span fraction e (linear taper)."""
        return caero.x12 + e * (caero.x43 - caero.x12)

    def _pt(e: float, x: float) -> np.ndarray:
        """Point at span fraction e and chord fraction x (0=LE, 1=TE)."""
        return _le(e) + x * _chord_len(e) * x_hat

    boxes: list = []
    k = start_k

    for i in range(nspan_boxes):
        eta_lo, eta_hi = eta[i], eta[i + 1]
        eta_mid = 0.5 * (eta_lo + eta_hi)

        for j in range(nchord_boxes):
            xi_lo, xi_hi = xi[j], xi[j + 1]

            # Corner coords: [root-LE, tip-LE, tip-TE, root-TE]
            c0 = _pt(eta_lo, xi_lo)   # root-LE
            c1 = _pt(eta_hi, xi_lo)   # tip-LE
            c2 = _pt(eta_hi, xi_hi)   # tip-TE
            c3 = _pt(eta_lo, xi_hi)   # root-TE
            corners = np.array([c0, c1, c2, c3])

            # Box 1/4-chord and 3/4-chord fractions
            xi_qc = xi_lo + 0.25 * (xi_hi - xi_lo)   # quarter-chord
            xi_tc = xi_lo + 0.75 * (xi_hi - xi_lo)   # three-quarter-chord

            # Bound vortex at 1/4-chord, spanning root to tip of this box
            bound_a = _pt(eta_lo, xi_qc)
            bound_b = _pt(eta_hi, xi_qc)

            # Collocation at 3/4-chord, midspan of this box
            colloc = 0.5 * (_pt(eta_lo, xi_tc) + _pt(eta_hi, xi_tc))

            # Area via cross-product of diagonals (works for general quadrilateral)
            d1 = c2 - c0   # tip-TE − root-LE
            d2 = c1 - c3   # tip-LE − root-TE
            cross = np.cross(d1, d2)
            norm_len = np.linalg.norm(cross)
            if norm_len < 1e-14:
                raise ValueError(
                    f"CAERO1 {caero.eid}: degenerate box at i_span={i}, j_chord={j}"
                )
            area = 0.5 * norm_len

            # Outward normal: orient so the dominant component is positive.
            # Horizontal surfaces (Z-dominant) point +Z; vertical (Y-dominant) point +Y.
            normal = cross / norm_len
            i_dom = int(np.argmax(np.abs(normal)))
            if normal[i_dom] < 0.0:
                normal = -normal

            # Orient bound vortex so the AIC self-influence (diagonal) is negative,
            # ensuring consistent sign convention for arbitrary surface orientations.
            # Condition: (bound_b − bound_a) × x_hat · n̂ < 0.
            if np.dot(np.cross(bound_b - bound_a, x_hat), normal) > 0.0:
                bound_a, bound_b = bound_b, bound_a

            chord = 0.5 * (_chord_len(eta_lo) + _chord_len(eta_hi))

            boxes.append(AeroBox(
                k=k,
                caero_eid=caero.eid,
                i_span=i,
                j_chord=j,
                corners=corners,
                colloc=colloc,
                bound_a=bound_a,
                bound_b=bound_b,
                force_point=0.5 * (bound_a + bound_b),
                area=float(area),
                normal=normal,
                chord=float(chord),
                span_frac=float(eta_mid),
            ))
            k += 1

    return boxes
