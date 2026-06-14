from dataclasses import dataclass, field


@dataclass
class Aeros:
    acsid: int    # aerodynamic coordinate system (0 = basic)
    rcsid: int    # reference coordinate system for rigid body motion (0 = basic)
    cref:  float  # reference chord length
    bref:  float  # reference span
    sref:  float  # reference area
    symxz: int    # +1 = symmetric about XZ plane, -1 = antisymmetric, 0 = none
    symxy: int    # +1 = symmetric about XY plane, -1 = antisymmetric, 0 = none
    mach:  float = 0.0  # sbeam extension: Mach for Prandtl–Glauert correction (field 8)


@dataclass
class Caero1:
    eid:    int
    pid:    int          # → Paero1
    cp:     int          # coordinate system for P1/P4 (default 0)
    nspan:  int          # spanwise box divisions (0 when LSPAN used)
    nchord: int          # chordwise box divisions (0 when LCHORD used)
    lspan:  int          # AEFACT sid for span fractions (0 when NSPAN used)
    lchord: int          # AEFACT sid for chord fractions (0 when NCHORD used)
    igid:   int          # interference group ID (ignored in Phase A)
    p1:     tuple        # (x, y, z) root leading-edge in CP frame
    x12:    float        # root chord length
    p4:     tuple        # (x, y, z) tip leading-edge in CP frame
    x43:    float        # tip chord length


@dataclass
class Paero1:
    pid: int             # property ID (stub — no body support in Phase A)


@dataclass
class Aefact:
    sid:  int
    data: list = field(default_factory=list)   # decimal fraction list (e.g. span/chord breakpoints)


@dataclass
class W2gj:
    sid:       int
    caero_eid: int           # which CAERO1 element this applies to
    # Dimensionless baseline downwash slopes Δz/Δx (z up, x streamwise), one per
    # box.  Added DIRECTLY to the assembled normalwash (NASTRAN W2GJ convention,
    # not passed through D_jk), so the sign is the normalwash sign:
    #   POSITIVE wg = surface sloping up aft = local nose-down / washout → LESS lift
    #   NEGATIVE wg = leading-edge-up built-in incidence            → MORE lift
    # See docs/20_theory/01_aeroelastics_theory.md §2.4–2.5 (Eq 9).
    data: list = field(default_factory=list)


@dataclass
class Wkk:
    sid:       int
    caero_eid: int           # which CAERO1 element this applies to
    data: list = field(default_factory=list)   # per-box diagonal weights (length = nspan × nchord)


@dataclass
class Aecorr:
    sid:       int
    method:    str           # 'WT1' (force/moment matching) or 'WT2' (pressure matching)
    caero_eid: int           # which CAERO1 element this applies to
    target: list = field(default_factory=list)  # per-box cp (WT2) or per-strip lift (WT1)


@dataclass
class Set1:
    sid:   int
    grids: list = field(default_factory=list)   # list[int] of structural grid IDs


@dataclass
class Spline2:
    eid:   int    # element ID
    caero: int    # CAERO1 EID of the panel being splined
    id1:   int    # first NASTRAN box ID in the box range
    id2:   int    # last NASTRAN box ID in the box range
    setg:  int    # SET1 SID for the structural grids
    dz:    float  # smoothing parameter (0.0 = interpolating)
    dtor:  float  # torsional/bending ratio (default 1.0)
    cid:   int    # CORD2R SID that defines the spline axis (CID x-axis = span)
    dthx:  float  # torsion (Rx) contribution scale (default 1.0)
    dthz:  float  # Rz contribution scale (default 0.0; unused in Phase B)
    usage: str    # "FORCE", "DISP", or "BOTH" (default "BOTH")


@dataclass
class Attach:
    """Rigid attachment of box group to a single master grid (sbeam extension)."""
    eid:   int
    caero: int    # CAERO1 EID
    id1:   int    # first NASTRAN box ID
    id2:   int    # last NASTRAN box ID
    grid:  int    # master structural grid ID
    cid:   int    # coordinate system (default 0)


@dataclass
class Spline0:
    """Zero-displacement constraint — box rows in g_slope / g_disp remain zero."""
    eid:   int
    caero: int
    id1:   int
    id2:   int


@dataclass
class Spline1:
    """Harder–Desmarais infinite-plate spline (IPS) — deferred to Phase C+."""
    eid:   int
    caero: int
    id1:   int
    id2:   int
    setg:  int
    dz:    float
    cid:   int


# ---------------------------------------------------------------------------
# Static aeroelastic trim card set (Step 51 — parsing only; SOL 144 solver deferred)
# ---------------------------------------------------------------------------

@dataclass
class Aestat:
    """Rigid-body aerodynamic extra point (trim DOF label)."""
    id:    int
    label: str   # e.g. ANGLEA, PITCH, ROLL, YAW, SIDES, URDD2–URDD6


@dataclass
class Aesurf:
    """Aerodynamic control surface definition."""
    id:    int
    label: str          # user-defined surface name (e.g. AILERON)
    cid1:  int          # coordinate system for hinge line
    alid1: int          # AELIST SID for boxes on this surface
    cid2:  int   = 0    # optional second hinge CID
    alid2: int   = 0    # optional second AELIST SID (0 = unused)
    eff:   float = 1.0  # control-surface effectiveness (1.0 = full)


@dataclass
class Aelist:
    """List of aerodynamic box IDs forming a control surface."""
    sid:      int
    elements: list = field(default_factory=list)   # list[int] of CAERO1 box IDs


@dataclass
class Trim:
    """Static trim condition — prescribed values for a subset of trim variables."""
    sid:  int
    mach: float
    q:    float          # dynamic pressure
    vars: dict = field(default_factory=dict)   # {label: prescribed_value}


@dataclass
class Diverg:
    """Divergence speed analysis parameters."""
    sid:    int
    nroots: int          # number of divergence roots to find
    rhoref: float = 0.0  # sbeam extension: reference density for V_div (0.0 ⇒ V_div omitted)
    machs:  list = field(default_factory=list)   # list[float] of Mach values


# ---------------------------------------------------------------------------
# sbeam-defined over-determined trim cards (ZAERO-inspired)
# ---------------------------------------------------------------------------

@dataclass
class Trimvar:
    """Per-variable bounds and initial guess for over-determined trim optimisation."""
    id:    int
    label: str    # matching AESTAT or AESURF label
    init:  float  # initial guess
    lb:    float  # lower bound
    ub:    float  # upper bound


@dataclass
class Trimobj:
    """Weighted objective function for over-determined trim."""
    sid:     int
    labels:  list = field(default_factory=list)   # list[str]
    weights: list = field(default_factory=list)   # list[float], parallel to labels


@dataclass
class Trimcon:
    """Inequality constraint for over-determined trim."""
    sid:   int
    label: str    # variable label
    sense: str    # "LE" (≤) or "GE" (≥)
    rhs:   float  # constraint right-hand side


# ---------------------------------------------------------------------------
# Monitor points (MON1) — integrated section-load output cards
# ---------------------------------------------------------------------------

@dataclass
class Aecomp:
    """Named collection of aerodynamic boxes (AELIST) or structural grids (SET1).

    Referenced by MONPNT1 (listtype 'AELIST') and MONPNT3 (listtype 'SET1').
    """
    name:     str          # component name (referenced by MONPNT*.comp)
    listtype: str          # 'AELIST' (box IDs) or 'SET1' (grid IDs)
    list_ids: list = field(default_factory=list)   # list[int] of AELIST SIDs or SET1 SIDs


@dataclass
class Monpnt1:
    """Aero-only integrated load monitor point (NASTRAN MONPNT1)."""
    name:  str             # 8-char monitor name
    label: str             # descriptive label
    axes:  int             # component axes (e.g. 123456)
    comp:  str             # AECOMP name (resolves to an AELIST box collection)
    cp:    int             # CID of the reference point coordinates
    x:     float           # reference point X in cp frame
    y:     float           # reference point Y in cp frame
    z:     float           # reference point Z in cp frame


@dataclass
class Monpnt3:
    """Aero + inertia + reaction integrated load monitor point (NASTRAN MONPNT3).

    Integrated over the structural grids resolved through ``comp`` (an AECOMP that
    points at one or more SET1 grid collections).
    """
    name:  str             # 8-char monitor name
    label: str             # descriptive label
    axes:  int             # component axes (e.g. 123456)
    comp:  str             # AECOMP name (resolves to a SET1 grid collection)
    cp:    int             # CID of the reference point coordinates
    x:     float           # reference point X in cp frame
    y:     float           # reference point Y in cp frame
    z:     float           # reference point Z in cp frame
