from dataclasses import dataclass, field


@dataclass
class Cord2r:
    """Rectangular coordinate system defined by three points (NASTRAN CORD2R)."""
    cid: int
    rid: int = 0                                      # Reference CID (0 = global)
    a: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))  # Origin
    b: tuple = field(default_factory=lambda: (0.0, 0.0, 1.0))  # Point on local Z-axis
    c: tuple = field(default_factory=lambda: (1.0, 0.0, 0.0))  # Point in local XZ-plane
