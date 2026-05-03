from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Spc:
    sid: int
    g1: int
    c1: str          # DOF string (e.g. "123456")
    d1: float = 0.0  # Enforced displacement (must be 0 in phase 1)
    g2: Optional[int] = None
    c2: Optional[str] = None
    d2: float = 0.0


@dataclass
class Spc1:
    sid: int
    c: str              # DOF string applied to all listed grids
    grids: list = field(default_factory=list)  # list of grid IDs
