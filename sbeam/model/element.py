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
class Crod:
    """Rod element: axial ``EA/L`` and torsion ``GJ/L`` along GA→GB, no bending.

    No orientation vector: the element frame's ``e_y``/``e_z`` are irrelevant to a rod
    (``designs/rod_element_crod.md`` D2). Section data comes from the PROD.
    """
    eid: int
    pid: int
    ga: int    # End A grid ID
    gb: int    # End B grid ID


@dataclass
class Conrod:
    """Rod element with inline section and material (NASTRAN ``CONROD``).

    Physically identical to :class:`Crod`; ``rod_section`` in ``assembly/elements.py``
    is the only code that distinguishes the two (D4).
    """
    eid: int
    ga: int
    gb: int
    mid: int
    A: float          # Cross-sectional area
    J: float = 0.0    # Torsional constant
    c: float = 0.0    # Torsional stress coefficient: tau = T * C / J
    nsm: float = 0.0  # Non-structural mass per unit length


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
    # (weight, DOF string, [grid IDs]) triples
    wt_gc: list[tuple[float, str, list[int]]] = field(default_factory=list)


@dataclass
class Rbe2:
    eid: int
    gn: int       # Independent grid
    cm: str       # Coupled DOF string (e.g. "123456")
    gm: list[int] = field(default_factory=list)  # Dependent grid IDs


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
