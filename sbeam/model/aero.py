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
