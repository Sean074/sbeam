from dataclasses import dataclass


@dataclass
class Grid:
    gid: int
    x: float
    y: float
    z: float
    ps: str = ""   # Permanent SPC DOFs (e.g. "123456")
    cp: int = 0    # Input coordinate system (resolved to CID 0 after parsing)
    cd: int = 0    # Output coordinate system for results
