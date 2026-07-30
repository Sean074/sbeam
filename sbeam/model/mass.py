from dataclasses import dataclass, field


@dataclass
class Massset:
    """MASSSET — a named payload / mass configuration (Step 60).

    Selected per subcase by the case-control ``MASSSET = sid`` request.  The
    case mass is built from the baseline model mass (CBAR distributed mass +
    baseline CONM2s), multiplied by ``scale``, then modified by the three ops:

      ``add``      — overlay CONM2 EIDs layered on top of the baseline
      ``replace``  — (baseline EID, overlay EID) pairs; the baseline card is
                     dropped and the overlay card takes its place
      ``delete``   — baseline CONM2 EIDs removed from the case

    EIDs named by ``add`` and by the overlay half of ``replace`` are
    overlay-only: they are ordinary CONM2 bulk cards but are excluded from
    the baseline mass (see ``BulkData.overlay_conm2_eids``).
    """
    sid: int
    label: str = ""
    scale: float = 1.0
    add: list = field(default_factory=list)      # list[int] overlay EIDs
    replace: list = field(default_factory=list)  # list[(baseline_eid, overlay_eid)]
    delete: list = field(default_factory=list)   # list[int] baseline EIDs


@dataclass
class Conm2:
    eid: int
    gid: int   # Grid point where mass is applied
    cid: int   # Coordinate system for offset vector and inertia tensor
    m: float   # Mass value
    x1: float = field(default=0.0)  # Offset from grid to CG, X component
    x2: float = field(default=0.0)  # Offset from grid to CG, Y component
    x3: float = field(default=0.0)  # Offset from grid to CG, Z component
    i11: float = field(default=0.0)  # Moment of inertia about axis 1 at CG
    i21: float = field(default=0.0)  # Product of inertia, axes 2-1
    i22: float = field(default=0.0)  # Moment of inertia about axis 2 at CG
    i31: float = field(default=0.0)  # Product of inertia, axes 3-1
    i32: float = field(default=0.0)  # Product of inertia, axes 3-2
    i33: float = field(default=0.0)  # Moment of inertia about axis 3 at CG
