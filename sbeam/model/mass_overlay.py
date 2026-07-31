"""MASSSET mass-case resolution (Step 60).

Resolves a case-control ``MASSSET = sid`` request into the effective CONM2 set
and structural-mass scale factor used by the mass-derived operators
(``assemble_global_mass``, ``compute_gpwg``, ``build_inertial_cols``).

The case mass is the baseline model mass — CBAR distributed mass plus the
baseline CONM2s — multiplied by ``SCALE``, then modified by the MASSSET ops:
ADD overlays new CONM2s, REPLACE swaps a baseline card for an overlay card,
DELETE drops a baseline card.  Overlay cards are *not* scaled: SCALE is a
baseline-mass factor, and the overlay is the payload the user is defining
explicitly.

**Invariant — no AeroCache invalidation.**  Nothing here touches geometry or
Mach, so the AIC (``ajj`` / ``ajj_inv_corr``), the spline matrices, and every
other entry of the ``AeroCache`` are mass-independent and are reused verbatim
across mass cases.  A MASSSET sweep rebuilds only mass-derived quantities.
"""

from dataclasses import dataclass, replace
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.mass import Conm2


@dataclass
class MassCase:
    """Resolved mass configuration for one subcase."""
    sid: Optional[int]   # MASSSET SID, or None for the baseline configuration
    label: str           # case name for output headers
    scale: float         # multiplies the baseline (CBAR + baseline CONM2) mass
    conm2s: dict[int, Conm2]   # baseline members already scaled

    @property
    def is_baseline(self) -> bool:
        return self.sid is None


def _scaled(conm2: Conm2, scale: float) -> Conm2:
    """Copy of a CONM2 with mass and inertia tensor scaled (offsets unchanged).

    The 6x6 CONM2 mass block is linear in (m, I), so scaling both scales the
    whole block — including the offset-induced coupling and parallel-axis terms.
    """
    if scale == 1.0:
        return conm2
    return replace(
        conm2,
        m=conm2.m * scale,
        i11=conm2.i11 * scale, i21=conm2.i21 * scale, i22=conm2.i22 * scale,
        i31=conm2.i31 * scale, i32=conm2.i32 * scale, i33=conm2.i33 * scale,
    )


def resolve_mass_case(bulk: BulkData, massset_sid: Optional[int] = None) -> MassCase:
    """Resolve ``massset_sid`` into a MassCase.

    ``massset_sid=None`` returns the baseline configuration: every CONM2 that
    is not overlay-only, unscaled.  With no MASSSET cards in the deck this is
    exactly ``bulk.conm2s`` and every downstream operator is unchanged.

    Raises ValueError if ``massset_sid`` names no MASSSET card.
    """
    if massset_sid is None:
        baseline = {
            eid: c for eid, c in bulk.conm2s.items()
            if eid not in bulk.overlay_conm2_eids
        }
        return MassCase(sid=None, label="BASELINE", scale=1.0, conm2s=baseline)

    ms = bulk.masssets.get(massset_sid)
    if ms is None:
        raise ValueError(f"MASSSET {massset_sid} selected in case control but not defined")

    dropped = set(ms.delete) | {old for old, _ in ms.replace}
    overlays = set(ms.add) | {new for _, new in ms.replace}

    # Iterate bulk.conm2s so the effective set keeps deck (card) order — the
    # assembly sums contributions in this order, which keeps mass-case results
    # reproducible and comparable with a hand-edited deck.
    conm2s: dict[int, Conm2] = {}
    for eid, c in bulk.conm2s.items():
        if eid in overlays:
            conm2s[eid] = c                       # overlay — unscaled
        elif eid in bulk.overlay_conm2_eids or eid in dropped:
            continue                              # another case's overlay, or dropped here
        else:
            conm2s[eid] = _scaled(c, ms.scale)    # baseline member — scaled

    return MassCase(sid=ms.sid, label=ms.label, scale=ms.scale, conm2s=conm2s)


def effective_conm2s(bulk: BulkData, massset_sid: Optional[int] = None) -> dict[int, Conm2]:
    """The effective ``{eid: Conm2}`` set for a mass case (see resolve_mass_case)."""
    return resolve_mass_case(bulk, massset_sid).conm2s
