"""mirror_halfspan — unfold a half-span (AEROS SYMXZ/SYMXY) model to full-span.

sbeam is full-span only (see ``aero_model.build_aero_model``).  This utility is
a migration aid for legacy half-span decks: it reflects the off-centerline
structure and aerodynamic panels about the XZ plane (y → −y) and clears the
AEROS symmetry flags, producing a BulkData that ``build_aero_model`` accepts.

Scope and limitations
---------------------
Mirrored automatically: ``GRID``, ``CBAR``, ``CONM2``, ``RBAR``, ``RBE2``,
``CAERO1``.  Grids/elements on the XZ plane (|y| < ``tol``) are shared, not
duplicated.  ``PBAR``/``PBUSH``/``MAT1``/``PAERO1``/``AEFACT``/``CORD2R`` are
passed through unchanged; ``AEROS`` is copied with ``SYMXZ = SYMXY = 0``.

This is a best-effort *geometric* unfold.  Cards whose correct full-span form
depends on model-specific intent — splines (``SPLINE0/1/2``, ``ATTACH``),
control surfaces (``AESURF``/``AELIST``), per-box data (``W2GJ``/``WKK``/
``AECORR``), constraints (``SPC``/``SPC1``/``SUPORT``) and loads — are NOT
auto-converted.  If any are present ``mirror_halfspan`` raises
``NotImplementedError`` listing them, so they can be reviewed and rebuilt by
hand.  In particular a symmetric half-model's plane-of-symmetry SPC must be
*replaced* (not mirrored) in the full model, and the centerline mass convention
(half vs. full mass on the XZ plane) must be checked against the source.
"""

import copy
from dataclasses import replace

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import require_aeros


# Collections that the geometric unfold cannot safely auto-convert.  Mapping of
# BulkData attribute name → human-readable card name for the error message.
_UNSUPPORTED = {
    "spline2s": "SPLINE2", "spline1s": "SPLINE1", "spline0s": "SPLINE0",
    "attaches": "ATTACH", "aesurfs": "AESURF", "aelists": "AELIST",
    "set1s": "SET1", "w2gjs": "W2GJ", "wkks": "WKK", "aecorrs": "AECORR",
    "chordcps": "CHORDCP",
    "spcs": "SPC", "spc1s": "SPC1", "forces": "FORCE", "moments": "MOMENT",
    "loads": "LOAD", "gravs": "GRAV", "trims": "TRIM", "aestats": "AESTAT",
    "divergs": "DIVERG", "trimvars": "TRIMVAR", "trimobjs": "TRIMOBJ",
    "trimcons": "TRIMCON", "rbe3s": "RBE3", "cbushs": "CBUSH",
    "plotels": "PLOTEL",
    # A MASSSET names CONM2 EIDs; whether a payload item mirrors (wing fuel)
    # or does not (a single centreline store) is model intent, not geometry.
    "masssets": "MASSSET",
}


def _next_pow10(n: int) -> int:
    """Smallest power of ten strictly greater than ``n`` (≥ 10)."""
    p = 10
    while p <= n:
        p *= 10
    return p


def mirror_halfspan(bulk: BulkData, tol: float = 1e-9) -> BulkData:
    """Return a full-span copy of ``bulk``, mirrored about the XZ plane.

    Args:
        bulk: Parsed half-span model (AEROS SYMXZ and/or SYMXY non-zero).
        tol:  Grids with ``|y| < tol`` are treated as on the plane of symmetry
              and shared between halves rather than duplicated.

    Returns:
        A new BulkData with the mirror image added and AEROS SYMXZ=SYMXY=0.

    Raises:
        ValueError:          if ``bulk`` is not a half-span model.
        NotImplementedError: if it contains cards outside the supported set.
    """
    if bulk.aeros is None or (require_aeros(bulk).symxz == 0 and require_aeros(bulk).symxy == 0):
        raise ValueError(
            "mirror_halfspan: model is not a half-span model "
            "(AEROS SYMXZ and SYMXY are both 0 — nothing to mirror)."
        )

    present = [name for attr, name in _UNSUPPORTED.items() if getattr(bulk, attr)]
    if present:
        raise NotImplementedError(
            "mirror_halfspan only unfolds GRID/CBAR/CONM2/RBAR/RBE2/CAERO1 "
            "geometry. These cards need a manual full-span rebuild: "
            + ", ".join(sorted(set(present)))
            + ". (A symmetric half-model's plane-of-symmetry SPC must be "
            "replaced, not mirrored; splines/control surfaces/W2GJ reference "
            "box and grid IDs that this tool does not remap.)"
        )

    out = copy.deepcopy(bulk)
    out.aeros = replace(bulk.aeros, symxz=0, symxy=0)

    # ID offset for every mirrored copy — keeps original IDs intact.
    max_id = max(
        [0]
        + list(bulk.grids)
        + list(bulk.cbars)
        + list(bulk.conm2s)
        + list(bulk.rbars)
        + list(bulk.rbe2s)
        + list(bulk.caero1s)
    )
    # The offset must also clear the *box-ID* span of the highest-numbered
    # CAERO1, not just its EID: a CAERO1 owns the NSPAN*NCHORD consecutive
    # NASTRAN box IDs from its EID, so an offset chosen from EIDs alone can
    # place a mirrored surface inside an original surface's box-ID range and
    # trip the collision check in ``panel.build_box_id_map`` on a deck the user
    # numbered perfectly well (F1).
    for eid, ca in bulk.caero1s.items():
        nspan = ca.nspan if ca.nspan > 0 else len(bulk.aefacts[ca.lspan].data) - 1
        nchord = ca.nchord if ca.nchord > 0 else len(bulk.aefacts[ca.lchord].data) - 1
        max_id = max(max_id, eid + nspan * nchord - 1)
    off = _next_pow10(max_id)

    def on_centerline(gid: int) -> bool:
        g = bulk.grids.get(gid)
        return g is not None and abs(g.y) < tol

    def mir_gid(gid: int) -> int:
        """Map a grid ID to its mirror (itself if on the centerline)."""
        return gid if on_centerline(gid) else gid + off

    # --- GRID: duplicate off-centerline grids at −y ---
    for gid, g in bulk.grids.items():
        if on_centerline(gid):
            continue
        out.grids[gid + off] = replace(g, gid=gid + off, y=-g.y)

    # --- CBAR: mirror any bar touching an off-centerline grid ---
    for eid, c in bulk.cbars.items():
        if on_centerline(c.ga) and on_centerline(c.gb):
            continue   # fully on the plane of symmetry — shared
        out.cbars[eid + off] = replace(
            c, eid=eid + off,
            ga=mir_gid(c.ga), gb=mir_gid(c.gb),
            x1=c.x1, x2=-c.x2, x3=c.x3,   # orientation vector reflects in y
        )

    # --- CONM2: mirror off-centerline point masses ---
    for eid, m in bulk.conm2s.items():
        if on_centerline(m.gid):
            continue
        out.conm2s[eid + off] = replace(
            m, eid=eid + off, gid=mir_gid(m.gid),
            x2=-m.x2,            # CG offset reflects in y
            i21=-m.i21, i32=-m.i32,   # products of inertia involving the 2-axis flip
        )

    # --- RBAR / RBE2: mirror rigid elements touching off-centerline grids ---
    for eid, r in bulk.rbars.items():
        if on_centerline(r.ga) and on_centerline(r.gb):
            continue
        out.rbars[eid + off] = replace(
            r, eid=eid + off, ga=mir_gid(r.ga), gb=mir_gid(r.gb))

    for eid, r in bulk.rbe2s.items():
        if on_centerline(r.gn) and all(on_centerline(g) for g in r.gm):
            continue
        out.rbe2s[eid + off] = replace(
            r, eid=eid + off, gn=mir_gid(r.gn),
            gm=[mir_gid(g) for g in r.gm])

    # --- CAERO1: mirror panels about XZ (negate P1/P4 y).  mesh_caero1 re-orients
    #     the box normals and bound vortices, so the reflected panel meshes into a
    #     correct opposite-side lifting surface with no further fix-up. ---
    for eid, ca in bulk.caero1s.items():
        if ca.cp != 0:
            raise NotImplementedError(
                f"mirror_halfspan: CAERO1 {eid} uses CP={ca.cp}; only CP=0 "
                "panels are auto-mirrored."
            )
        p1 = (ca.p1[0], -ca.p1[1], ca.p1[2])
        p4 = (ca.p4[0], -ca.p4[1], ca.p4[2])
        out.caero1s[eid + off] = replace(ca, eid=eid + off, p1=p1, p4=p4)

    return out
