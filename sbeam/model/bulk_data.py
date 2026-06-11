from dataclasses import dataclass, field
from typing import Optional

from .aero import Aeros, Caero1, Paero1, Aefact, W2gj, Wkk, Aecorr, Set1, Spline2, Attach, Spline0, Spline1


@dataclass
class BulkData:
    grids: dict = field(default_factory=dict)     # {gid: Grid}
    cbars: dict = field(default_factory=dict)     # {eid: Cbar}
    cbushs: dict = field(default_factory=dict)    # {eid: Cbush}
    plotels: dict = field(default_factory=dict)   # {eid: Plotel}
    rbe3s: dict = field(default_factory=dict)     # {eid: Rbe3}
    rbe2s: dict = field(default_factory=dict)     # {eid: Rbe2}
    rbars: dict = field(default_factory=dict)     # {eid: Rbar}
    pbars: dict = field(default_factory=dict)     # {pid: Pbar}
    pbushs: dict = field(default_factory=dict)    # {pid: Pbush}
    mat1s: dict = field(default_factory=dict)     # {mid: Mat1}
    conm2s: dict = field(default_factory=dict)    # {eid: Conm2}
    spcs: dict = field(default_factory=dict)      # {sid: list[Spc]}
    spc1s: dict = field(default_factory=dict)     # {sid: list[Spc1]}
    forces: dict = field(default_factory=dict)    # {sid: list[Force]}
    moments: dict = field(default_factory=dict)   # {sid: list[Moment]}
    loads: dict = field(default_factory=dict)     # {sid: Load}
    gravs: dict = field(default_factory=dict)     # {sid: Grav}
    eigrls: dict = field(default_factory=dict)    # {sid: Eigrl}
    cord2rs: dict = field(default_factory=dict)   # {cid: Cord2r}
    aeros: Optional[Aeros] = None                 # single AEROS card (reference geometry)
    caero1s: dict = field(default_factory=dict)   # {eid: Caero1}
    paero1s: dict = field(default_factory=dict)   # {pid: Paero1}
    aefacts: dict = field(default_factory=dict)   # {sid: Aefact}
    w2gjs:   dict = field(default_factory=dict)   # {sid: W2gj}
    wkks:    dict = field(default_factory=dict)   # {sid: Wkk}
    aecorrs:  dict = field(default_factory=dict)   # {sid: Aecorr}
    set1s:    dict = field(default_factory=dict)   # {sid: Set1}
    spline2s: dict = field(default_factory=dict)   # {eid: Spline2}
    attaches: dict = field(default_factory=dict)   # {eid: Attach}
    spline0s: dict = field(default_factory=dict)   # {eid: Spline0}
    spline1s: dict = field(default_factory=dict)   # {eid: Spline1}
