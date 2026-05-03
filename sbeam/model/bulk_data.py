from dataclasses import dataclass, field

from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Plotel, Rbe3
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force, Moment, Load, Eigrl
from sbeam.model.constraint import Spc, Spc1
from sbeam.model.mass import Conm2


@dataclass
class BulkData:
    grids: dict = field(default_factory=dict)     # {gid: Grid}
    cbars: dict = field(default_factory=dict)     # {eid: Cbar}
    plotels: dict = field(default_factory=dict)   # {eid: Plotel}
    rbe3s: dict = field(default_factory=dict)     # {eid: Rbe3}
    pbars: dict = field(default_factory=dict)     # {pid: Pbar}
    mat1s: dict = field(default_factory=dict)     # {mid: Mat1}
    conm2s: dict = field(default_factory=dict)    # {eid: Conm2}
    spcs: dict = field(default_factory=dict)      # {sid: list[Spc]}
    spc1s: dict = field(default_factory=dict)     # {sid: list[Spc1]}
    forces: dict = field(default_factory=dict)    # {sid: list[Force]}
    moments: dict = field(default_factory=dict)   # {sid: list[Moment]}
    loads: dict = field(default_factory=dict)     # {sid: Load}
    eigrls: dict = field(default_factory=dict)    # {sid: Eigrl}
