from dataclasses import dataclass, field


@dataclass
class Conm2:
    eid: int
    gid: int   # Grid point where mass is applied
    cid: int   # Coordinate system ID (must be 0 in phase 1)
    m: float   # Mass value
    x1: float = field(default=0.0)  # Offset from grid to CG, X component
    x2: float = field(default=0.0)  # Offset from grid to CG, Y component
    x3: float = field(default=0.0)  # Offset from grid to CG, Z component
