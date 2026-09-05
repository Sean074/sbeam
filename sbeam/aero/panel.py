"""CAERO1 box meshing — trapezoidal aerodynamic panels.

Each CAERO1 macroelement is meshed into NSPAN × NCHORD trapezoidal boxes.
Per box: bound vortex segment at the box 1/4-chord, collocation point at the
box 3/4-chord (horseshoe-vortex lattice convention, NASA SP-405).

All coordinates are in global CID 0.
"""

import numpy as np
from dataclasses import dataclass

from sbeam.model.aero import Caero1, Paero1
from sbeam.assembly.coord_transform import get_transform
from sbeam.types import FloatArray
from sbeam.model.aero import Aefact
from sbeam.model.coordinate_system import Cord2r


@dataclass
class AeroBox:
    k:          int           # global sequential index (0-based across all CAERO1 elements)
    caero_eid:  int
    i_span:     int           # spanwise index within parent CAERO1 (0-based)
    j_chord:    int           # chordwise index within parent CAERO1 (0-based)
    corners:    FloatArray    # (4, 3): [root-LE, tip-LE, tip-TE, root-TE] in CID 0
    colloc:     FloatArray    # (3,): 3/4-chord midspan collocation point
    bound_a:     FloatArray    # (3,): 1/4-chord bound vortex, root side
    bound_b:     FloatArray    # (3,): 1/4-chord bound vortex, tip side
    force_point: FloatArray    # (3,): 1/4-chord bound-vortex midpoint = (bound_a + bound_b)/2
    area:        float
    normal:     FloatArray    # (3,) outward unit normal
    chord:      float         # mean chord of the box
    span_frac:  float         # spanwise fraction at box mid-span [0, 1]
    is_strip:   bool = False  # True ⇒ decoupled strip body box (no AIC coupling; set
                              # by build_aero_model from the CAERO1 PID → PSTRIP)


# ---------------------------------------------------------------------------
# NASTRAN box identifiers
# ---------------------------------------------------------------------------
#
# THE single derivation of the NASTRAN box-ID convention.  It lives here, beside
# ``AeroBox``, because every consumer already imports this module and it imports
# nothing from the aero package — so there is no cycle to break.  Before this was
# unified the same formula was reimplemented three times (``spline.py``,
# ``integration.py``, ``sol144._compute_hinge_moments``) and each copy silently
# dropped a box on an ID collision (defect F1).

def nchord_per_caero(boxes: list[AeroBox]) -> dict[int, int]:
    """Return {caero_eid: n_chord_boxes} from the meshed box list.

    Derived from the boxes rather than ``Caero1.nchord`` so the AEFACT/LCHORD
    path needs no special case and no ``BulkData`` argument.
    """
    result: dict[int, int] = {}
    for box in boxes:
        result[box.caero_eid] = max(result.get(box.caero_eid, 0), box.j_chord + 1)
    return result


def nastran_box_id(box: AeroBox, nchord: int) -> int:
    """NASTRAN aero box ID = CAERO1.EID + i_span * NCHORD + j_chord."""
    return box.caero_eid + box.i_span * nchord + box.j_chord


def build_box_id_map(boxes: list[AeroBox]) -> dict[int, int]:
    """Return {nastran_box_id: box.k}, fatal on any ID collision.

    Because a CAERO1 consumes the ``NSPAN * NCHORD`` consecutive IDs starting at
    its EID, two CAERO1s numbered closer together than that overlap.  The map is
    what ``SPLINE2``/``ATTACH`` box ranges, ``AELIST`` control-surface boxes and
    ``MONPNT1`` integrate through, so an overlap silently attributes one box's
    load to another — or drops it entirely.  Detect it once, here, rather than
    letting each consumer resolve a wrong ``k``.

    Raises:
        ValueError: naming both CAERO1s, the first colliding ID and the remedy.
    """
    nchord = nchord_per_caero(boxes)
    id_to_k: dict[int, int] = {}
    owner: dict[int, AeroBox] = {}
    for box in boxes:
        bid = nastran_box_id(box, nchord[box.caero_eid])
        prev = owner.get(bid)
        if prev is not None and prev.caero_eid != box.caero_eid:
            first, second = sorted((prev.caero_eid, box.caero_eid))
            n_first = sum(1 for b in boxes if b.caero_eid == first)
            span = f"{first}..{first + n_first - 1}"
            raise ValueError(
                f"CAERO1 {second}: NASTRAN box ID {bid} collides with CAERO1 "
                f"{first}, which occupies IDs {span} ({n_first} boxes).  Box IDs "
                "are EID + i_span*NCHORD + j_chord, so each CAERO1 must be "
                "numbered at least NSPAN*NCHORD above the previous one — "
                f"renumber CAERO1 {second} to {first + n_first} or higher and "
                "shift its SPLINE/ATTACH/AELIST/MONPNT box ranges by the same "
                "delta."
            )
        owner[bid] = box
        id_to_k[bid] = box.k
    return id_to_k


def cosine_chord_fractions(nchord: int) -> FloatArray:
    """LE-concentrated half-cosine chordwise station fractions ξ ∈ [0, 1].

    Returns ``nchord + 1`` monotone breakpoints ``ξ_i = 1 − cos((π/2)·(i/n))``,
    dense at the leading edge where the chordwise loading gradient is steepest
    (NASA SP-405 / DeJarnette: cosine spacing reaches uniform-spacing accuracy
    with fewer boxes).

    Intended use: generate the fraction list for an ``AEFACT`` card referenced
    by the CAERO1 ``LCHORD`` field (with NCHORD blank/0).  Uniform NCHORD
    meshing is unchanged — cosine spacing is opt-in, preserving NASTRAN
    box-for-box fidelity for decks that use NCHORD.
    """
    if nchord < 1:
        raise ValueError(f"cosine_chord_fractions: nchord must be ≥ 1, got {nchord}")
    i = np.arange(nchord + 1, dtype=float)
    return 1.0 - np.cos(0.5 * np.pi * i / nchord)


def mesh_caero1(
    caero: Caero1,
    paero: Paero1,
    aefacts: dict[int, Aefact],
    cord2rs: dict[int, Cord2r],
    start_k: int = 0,
) -> list[AeroBox]:
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
    origin, R = get_transform(caero.cp, cord2rs)
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

    def _le(e: float) -> FloatArray:
        """Leading-edge point at span fraction e."""
        return p1 + e * (p4 - p1)

    def _chord_len(e: float) -> float:
        """Chord length at span fraction e (linear taper)."""
        return caero.x12 + e * (caero.x43 - caero.x12)

    def _pt(e: float, x: float) -> FloatArray:
        """Point at span fraction e and chord fraction x (0=LE, 1=TE)."""
        return _le(e) + x * _chord_len(e) * x_hat

    boxes: list[AeroBox] = []
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
