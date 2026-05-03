from dataclasses import dataclass


@dataclass
class Conm2:
    eid: int
    gid: int  # Grid point where mass is applied
    cid: int  # Coordinate system ID (must be 0 in phase 1)
    m: float  # Mass value
