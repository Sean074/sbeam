from dataclasses import dataclass, field


@dataclass
class Massset:
    """MASSCASE — a named payload / mass configuration (Step 60).

    Selected per subcase by the case-control ``MASSCASE = sid`` request.  The
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
    add: list[int] = field(default_factory=list)                    # overlay EIDs
    replace: list[tuple[int, int]] = field(default_factory=list)    # (baseline, overlay)
    delete: list[int] = field(default_factory=list)                 # baseline EIDs
    # MSC mass combinations (#102) resolve to a Massset too: ``add`` lists the CONM2s of
    # the selected BEGIN MASSID sections, each scaled by ``add_scale`` (S0·Si); MASSCASE
    # overlays enter unscaled.  ``msc`` marks a case built from an MSC MASSSET entry
    msc: bool = False
    add_scale: dict[int, float] = field(default_factory=dict)


@dataclass
class MassCombination:
    """MSC MASSSET bulk entry: a mass combination (MSC Nastran 2024.1 QRG PDF p.2018).

    ``M_ID = S0 · Σ Si·M_IDi``; ``IDi = 0`` is the base mass, ``IDi > 0`` a BEGIN MASSID
    section.  Selected per subcase by the case-control ``MASSSET = ID`` (p.482).
    """
    sid: int
    s0: float
    terms: list[tuple[float, int]] = field(default_factory=list)   # (Si, IDi)


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
    i21: float = field(default=0.0)  # Product of inertia ∫ρ x1 x2 dV; enters the matrix negated (#66)
    i22: float = field(default=0.0)  # Moment of inertia about axis 2 at CG
    i31: float = field(default=0.0)  # Product of inertia, axes 3-1
    i32: float = field(default=0.0)  # Product of inertia, axes 3-2
    i33: float = field(default=0.0)  # Moment of inertia about axis 3 at CG
