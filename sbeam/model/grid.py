from dataclasses import dataclass


@dataclass
class Grid:
    gid: int
    x: float
    y: float
    z: float
    ps: str = ""  # Permanent SPC DOFs (e.g. "123456")
