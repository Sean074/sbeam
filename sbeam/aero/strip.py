"""Decoupled strip body panels — independent 2-D section aero (no AIC coupling).

A CAERO1 whose PID points to a ``PSTRIP`` (sbeam extension) is a *decoupled strip
body panel*.  Unlike an ordinary VLM panel it has NO horseshoe vortex, NO trailing
wake, and NO aerodynamic influence to or from any other box: its block of the
influence operator is **diagonal**.  Each box is an independent 2-D strip whose load
is purely local,

    ΔCp_box = slope_box · (α·n_z + β·n_y + Δα_box),

so in the operator that maps normalwash → ΔCp (``AeroModel.ajj_inv_corr``) a strip
box's row is a single diagonal entry and every off-diagonal entry (to and from the
lifting surfaces) is exactly zero.  Two consequences:

  * **It cannot contaminate the lifting surfaces.**  There is no wing↔body coupling
    block, so adding — or moving, or even overlapping — a strip body panel changes the
    wing/HTP/VTP loads by *exactly* zero.  This is the clean resolution of the
    flat-plate cruciform's "authority equals contamination" limit (docs/20_theory
    §3.6): a panel with no coupling cannot contaminate.
  * **It carries no induced/interference effect either** — a decoupled element is
    transparent to the wing's flow.  A strip body is a pure *load* device, tuned by the
    body correction to match the total airplane Cm/Cn/Cl.  The body's *effect on* the
    lifting surfaces (the fence / no-through-flow boundary condition) is a separate,
    composable mechanism (backlog "image fence"); it deliberately does not live here.

Sign / units.  ``ajj_inv_corr`` maps the boundary-condition normalwash
``rhs[i] = -(α·n_z + β·n_y) + wg[i]`` to ΔCp, so the diagonal entry that yields
``ΔCp = slope·(α·n_z + β·n_y) - slope·wg`` is **-slope** (positive ``wg`` is washout /
less lift, matching the W2GJ convention).  The Göthert ``1/β`` factor is applied to the
slope for consistency with the compressible VLM surfaces.

Slope magnitude.  The PSTRIP default ``slope0`` ≈ π is the per-box dΔCp/dα_local; with
a uniform per-box slope the sectional lift-curve slope equals that value, so π is the
"50% of the 2π flat-plate" body fudge.  A ``STRIPK`` card overrides the slope
box-by-box (emitted by the correction).
"""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.types import FloatArray
from sbeam.aero.panel import AeroBox
from sbeam.model.aero import Stripk


def is_strip_caero(bulk: BulkData, caero_eid: int) -> bool:
    """True if CAERO1 *caero_eid* is a decoupled strip body panel (PID → PSTRIP)."""
    caero = bulk.caero1s.get(caero_eid)
    return caero is not None and caero.pid in bulk.pstrips


def strip_box_mask(bulk: BulkData, boxes: list[AeroBox]) -> FloatArray:
    """Boolean mask (length n_box) — True for boxes belonging to a strip panel."""
    return np.array([is_strip_caero(bulk, b.caero_eid) for b in boxes], dtype=bool)


def strip_box_slopes(bulk: BulkData, boxes: list[AeroBox]) -> FloatArray:
    """Per-box lift-curve slope dΔCp/dα_local for every strip box (0 for non-strip).

    Resolves, per strip box, the ``STRIPK`` per-box value if a STRIPK card exists for
    the box's CAERO1, else the ``PSTRIP`` ``slope0``.  Row-major ordering (matching
    ``mesh_caero1`` / W2GJ / WKK).  Non-strip boxes return 0.0 — their slope is
    meaningless (they use the VLM AIC, not the diagonal block).
    """
    n = len(boxes)
    slopes = np.zeros(n)
    stripk_by_caero: dict[int, Stripk] = {}
    for sk in bulk.stripks.values():
        stripk_by_caero.setdefault(sk.caero_eid, sk)   # one card per CAERO1
    local_count: dict[int, int] = {}
    for j, b in enumerate(boxes):
        if not is_strip_caero(bulk, b.caero_eid):
            continue
        eid = b.caero_eid
        local_k = local_count.get(eid, 0)
        local_count[eid] = local_k + 1
        sk = stripk_by_caero.get(eid)
        if sk is not None and local_k < len(sk.data):
            slopes[j] = sk.data[local_k]
        else:
            slopes[j] = bulk.pstrips[bulk.caero1s[eid].pid].slope0
    return slopes
