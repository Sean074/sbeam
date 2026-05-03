from dataclasses import dataclass, field


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
