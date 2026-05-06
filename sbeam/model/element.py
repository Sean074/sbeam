from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Cbar:
    eid: int
    pid: int
    ga: int    # End A grid ID
    gb: int    # End B grid ID
    x1: float  # Orientation vector component
    x2: float
    x3: float
    offt: str = "GGG"
    pa: str = ""  # Pin releases at end A (e.g. "456")
    pb: str = ""  # Pin releases at end B


@dataclass
class Plotel:
    eid: int
    g1: int
    g2: int


@dataclass
class Rbe3:
    eid: int
    refgrid: int  # Reference (dependent) grid ID
    refc: str     # Reference grid DOF string
    wt_gc: list = field(default_factory=list)  # list of (weight, dofs, [grid_ids])


@dataclass
class Rbe2:
    eid: int
    gn: int       # Independent grid
    cm: str       # Coupled DOF string (e.g. "123456")
    gm: list = field(default_factory=list)  # Dependent grid IDs


@dataclass
class Rbar:
    eid: int
    ga: int         # End A grid (independent)
    gb: int         # End B grid (dependent)
    cna: str = "123456"  # Independent DOFs at GA
    cnb: str = ""        # Independent DOFs at GB (Phase 1: must be blank)


@dataclass
class Cbush:
    eid: int
    pid: int
    ga: int            # End A grid ID
    gb: Optional[int]  # End B grid ID; None = grounded at GA
    x1: float = 0.0   # Orientation vector (XZ-plane definition, same role as CBAR)
    x2: float = 0.0
    x3: float = 0.0
