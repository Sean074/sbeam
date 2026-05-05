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
    i11: float = field(default=0.0)  # Moment of inertia about axis 1 at CG
    i21: float = field(default=0.0)  # Product of inertia, axes 2-1
    i22: float = field(default=0.0)  # Moment of inertia about axis 2 at CG
    i31: float = field(default=0.0)  # Product of inertia, axes 3-1
    i32: float = field(default=0.0)  # Product of inertia, axes 3-2
    i33: float = field(default=0.0)  # Moment of inertia about axis 3 at CG
