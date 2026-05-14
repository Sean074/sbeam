from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Force:
    sid: int
    gid: int
    cid: int
    f: float   # Scale factor
    n1: float  # Direction cosine X
    n2: float  # Direction cosine Y
    n3: float  # Direction cosine Z


@dataclass
class Moment:
    sid: int
    gid: int
    cid: int
    m: float   # Scale factor
    n1: float  # Direction cosine X
    n2: float  # Direction cosine Y
    n3: float  # Direction cosine Z


@dataclass
class Load:
    sid: int
    s: float                          # Overall scale factor
    components: list = field(default_factory=list)  # list of (scale, load_sid)


@dataclass
class Grav:
    sid: int
    cid: int    # Coordinate system ID (Phase 1: CID=0 only)
    g: float    # Acceleration magnitude
    n1: float   # Direction vector X (in CID frame)
    n2: float   # Direction vector Y
    n3: float   # Direction vector Z


@dataclass
class Eigrl:
    sid: int
    v1: Optional[float] = None  # Lower frequency bound (Hz)
    v2: Optional[float] = None  # Upper frequency bound (Hz)
    nd: Optional[int] = None    # Number of modes to extract
    norm: str = "MASS"          # Normalisation: MASS or MAX
