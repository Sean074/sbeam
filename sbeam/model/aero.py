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
    data: list = field(default_factory=list)   # dimensionless normalwash slopes (Δz/Δx), one per box


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
