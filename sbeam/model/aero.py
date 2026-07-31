import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sbeam.model.bulk_data import BulkData


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
    p1:     tuple[float, float, float]   # root leading-edge in CP frame
    x12:    float        # root chord length
    p4:     tuple[float, float, float]   # tip leading-edge in CP frame
    x43:    float        # tip chord length


@dataclass
class Paero1:
    pid: int             # property ID (stub — no body support in Phase A)


@dataclass
class Pstrip:
    """Decoupled strip-body panel property (sbeam extension).

    A CAERO1 whose PID points to a PSTRIP (instead of a PAERO1) is a **decoupled
    strip body panel**: it carries NO horseshoe vortex, NO trailing wake, and NO
    AIC coupling (zero off-diagonal influence to or from any other box).  Each box
    is an independent 2-D section whose load depends only on its own local incidence:

        ΔCp_box = slope_box · (α·n_z + β·n_y + Δα_box)

    ``slope0`` is the nominal per-box lift-curve slope dΔCp/dα_local.  The default
    ≈ π gives a sectional lift-curve slope of π — half the 2π flat-plate value
    ("50% normal surface"); a body fudge that cannot contaminate the lifting
    surfaces because it has no coupling to them (see sbeam.aero.strip).  The body
    correction overrides ``slope0`` per box with a STRIPK card and sets Δα_box with
    a W2GJ card so the total airplane Cm/Cn/Cl match CFD/wind tunnel.
    """
    pid:    int
    slope0: float = math.pi   # nominal per-box lift-curve slope (dΔCp/dα_local)


@dataclass
class Stripk:
    """Per-box strip lift-curve slopes for a PSTRIP panel (sbeam extension).

    Overrides the uniform PSTRIP ``slope0`` box-by-box; emitted by the strip body
    correction.  ``data`` is the per-box slope dΔCp/dα_local (signed — the
    correction may drive a box negative), ordered row-major like W2GJ/WKK, length
    nspan × nchord.  Absent → every box uses the PSTRIP ``slope0``.
    """
    sid:       int
    caero_eid: int           # which (strip) CAERO1 element this applies to
    data: list[float] = field(default_factory=list)


@dataclass
class Aefact:
    sid:  int
    data: list[float] = field(default_factory=list)   # decimal fractions (span/chord breakpoints)


@dataclass
class W2gj:
    sid:       int
    caero_eid: int           # which CAERO1 element this applies to
    # Card values in the NASTRAN W2GJ convention (MSC Aeroelastic UG Eq 2-104,
    # HA144A: W2GJ = +0.001745 rad is "+0.1 deg wing incidence"):
    #   POSITIVE data = leading-edge-up built-in incidence/camber → MORE lift
    #   NEGATIVE data = local nose-down washout                   → LESS lift
    # This is the OPPOSITE sign to sbeam's internal normalwash slope wg
    # (positive = washout); ``build_wg`` negates card data on assembly.
    # See docs/20_theory/01_aeroelastics_theory.md §2.4–2.5 (Eq 9).
    data: list[float] = field(default_factory=list)


@dataclass
class Wkk:
    sid:       int
    caero_eid: int           # which CAERO1 element this applies to
    data: list[float] = field(default_factory=list)   # per-box diagonal weights (nspan × nchord)


@dataclass
class Chordcp:
    """CFD/wind-tunnel steady-pressure injection (Step 54, sbeam extension).

    Supplies the per-box physical steady Cp distribution of one CAERO1 at a
    stated reference angle of attack.  At assembly the injected pressures
    replace the program-computed mean flow (the W2GJ-driven baseline) via an
    equivalent-normalwash substitution; the trim solution then perturbs about
    the injected operating point.  ``alpha_ref`` is given in DEGREES on the
    card and stored here in RADIANS.  ``mach`` (optional, 0.0 = unset) is the
    Mach the data was measured at — validation only.
    """
    sid:       int
    caero_eid: int
    alpha_ref: float          # radians (card field is degrees)
    mach:      float = 0.0    # measurement Mach; 0.0 = not stated
    data: list[float] = field(default_factory=list)  # per-box Cp, row-major (span slowest)


@dataclass
class Aecorr:
    sid:       int
    method:    str           # 'WT1' (force/moment matching) or 'WT2' (pressure matching)
    caero_eid: int           # which CAERO1 element this applies to
    target: list[float] = field(default_factory=list)  # per-box cp (WT2) or per-strip lift (WT1)


@dataclass
class Set1:
    sid:   int
    grids: list[int] = field(default_factory=list)   # structural grid IDs


@dataclass
class Spline2:
    eid:   int    # element ID
    caero: int    # CAERO1 EID of the panel being splined
    id1:   int    # first NASTRAN box ID in the box range
    id2:   int    # last NASTRAN box ID in the box range
    setg:  int    # SET1 SID for the structural grids
    dz:    float  # linear (deflection) attachment flexibility (0 = rigid)
    dtor:  float  # torsional flexibility ratio EI/GJ (default 1.0)
    cid:   int    # CORD2R SID; the CID *y-axis* is the spline axis (MSC convention)
    dthx:  float  # bending-slope (rotation about CID x) attachment flexibility
                  # (0 = rigid, > 0 = spring, negative = not attached)
    dthy:  float  # torsion (rotation about CID y = spline axis) attachment
                  # flexibility (same convention)
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
    elements: list[int] = field(default_factory=list)   # CAERO1 box IDs


@dataclass
class Trim:
    """Static trim condition — prescribed values for a subset of trim variables.

    ``rhoref`` is an sbeam extension (Step 61) entered as a pseudo-label in the
    LABEL/VALUE pair list (``TRIM, 1, 0.9, 1200.0, RHOREF, 0.002377, ...``).  It
    is the freestream density for this flight condition and exists solely to map
    the dynamic pressure to a true airspeed ``V = sqrt(2q/rho)``; the static trim
    (Step 52/53) never needs it.  ``0.0`` means "not supplied".
    """
    sid:  int
    mach: float
    q:    float          # dynamic pressure
    vars: dict[str, float] = field(default_factory=dict)   # {label: prescribed_value}
    rhoref: float = 0.0  # sbeam extension: freestream density (0.0 ⇒ not supplied)

    def velocity(self) -> float:
        """True airspeed V = sqrt(2q/rho) from the RHOREF pseudo-label.

        Raises:
            ValueError if RHOREF was not supplied on the card — the transient
            maneuver rate terms (Step 61 ``build_dj_rigidrate``) are undefined
            without a physical velocity.
        """
        if self.rhoref <= 0.0:
            raise ValueError(
                f"TRIM {self.sid}: a freestream velocity is required but RHOREF "
                "is not set on the card.  Add the RHOREF pseudo-label "
                "(e.g. 'TRIM, {sid}, MACH, Q, RHOREF, 0.002377, ...') so "
                "V = sqrt(2q/rho) can be formed.".replace("{sid}", str(self.sid))
            )
        return float(math.sqrt(2.0 * self.q / self.rhoref))


@dataclass
class Diverg:
    """Divergence speed analysis parameters."""
    sid:    int
    nroots: int          # number of divergence roots to find
    rhoref: float = 0.0  # sbeam extension: reference density for V_div (0.0 ⇒ V_div omitted)
    machs:  list[float] = field(default_factory=list)   # Mach values


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
    labels:  list[str] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)   # parallel to labels


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
    list_ids: list[int] = field(default_factory=list)   # AELIST SIDs or SET1 SIDs


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


def require_aeros(bulk: "BulkData") -> Aeros:
    """Return ``bulk.aeros``, raising if the deck has no AEROS card.

    Every aerodynamic operator needs the reference geometry (SREF/CREF/BREF and
    the RCSID reference point).  ``BulkData.aeros`` is ``Optional`` because a
    pure SOL 101/103 deck has no AEROS card, so aero code funnels through this
    guard instead of dereferencing ``None`` and raising a bare AttributeError.
    """
    if bulk.aeros is None:
        raise ValueError(
            "An AEROS card is required for aerodynamic analysis "
            "(reference chord/span/area and the rigid-body reference system)."
        )
    return bulk.aeros
