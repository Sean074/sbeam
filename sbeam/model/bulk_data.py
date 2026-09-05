from dataclasses import dataclass, field
from typing import Optional

from .aero import (
    Aeros, Caero1, Paero1, Pstrip, Stripk, Aefact, W2gj, Wkk, Chordcp, Aecorr, Set1,
    Spline2, Attach, Spline0, Spline1,
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
    Aecomp, Monpnt1, Monpnt3, Monsect,
)
from .gust import Gustlf
from .maneuver import Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads
from .mass import Massset, Conm2
from .constraint import Spc, Spc1, Suport
from .coordinate_system import Cord2r
from .element import Cbar, Cbush, Plotel, Rbe3, Rbe2, Rbar
from .grid import Grid
from .load import Force, Moment, Load, Grav, Eigrl
from .material import Mat1
from .property import Pbar, Pbush


@dataclass
class BulkData:
    grids: dict[int, Grid] = field(default_factory=dict)
    cbars: dict[int, Cbar] = field(default_factory=dict)
    cbushs: dict[int, Cbush] = field(default_factory=dict)
    plotels: dict[int, Plotel] = field(default_factory=dict)
    rbe3s: dict[int, Rbe3] = field(default_factory=dict)
    rbe2s: dict[int, Rbe2] = field(default_factory=dict)
    rbars: dict[int, Rbar] = field(default_factory=dict)
    pbars: dict[int, Pbar] = field(default_factory=dict)
    pbushs: dict[int, Pbush] = field(default_factory=dict)
    mat1s: dict[int, Mat1] = field(default_factory=dict)
    conm2s: dict[int, Conm2] = field(default_factory=dict)
    masssets: dict[int, Massset] = field(default_factory=dict)   # Step 60 mass cases
    # CONM2 EIDs named by a MASSSET ADD / REPLACE-overlay slot: ordinary CONM2
    # cards that are overlay-only and therefore excluded from the baseline mass.
    overlay_conm2_eids: set[int] = field(default_factory=set)
    spcs: dict[int, list[Spc]] = field(default_factory=dict)
    spc1s: dict[int, list[Spc1]] = field(default_factory=dict)
    forces: dict[int, list[Force]] = field(default_factory=dict)
    moments: dict[int, list[Moment]] = field(default_factory=dict)
    loads: dict[int, Load] = field(default_factory=dict)
    gravs: dict[int, Grav] = field(default_factory=dict)
    eigrls: dict[int, Eigrl] = field(default_factory=dict)
    cord2rs: dict[int, Cord2r] = field(default_factory=dict)
    aeros: Optional[Aeros] = None                 # single AEROS card (reference geometry)
    caero1s: dict[int, Caero1] = field(default_factory=dict)
    paero1s: dict[int, Paero1] = field(default_factory=dict)
    pstrips: dict[int, Pstrip] = field(default_factory=dict)   # decoupled strip body panels
    stripks: dict[int, Stripk] = field(default_factory=dict)   # per-box strip slopes
    aefacts: dict[int, Aefact] = field(default_factory=dict)
    w2gjs:   dict[int, W2gj] = field(default_factory=dict)
    wkks:    dict[int, Wkk] = field(default_factory=dict)
    aecorrs:  dict[int, Aecorr] = field(default_factory=dict)
    chordcps: dict[int, Chordcp] = field(default_factory=dict)  # injected steady Cp
    set1s:    dict[int, Set1] = field(default_factory=dict)
    spline2s: dict[int, Spline2] = field(default_factory=dict)
    attaches: dict[int, Attach] = field(default_factory=dict)
    spline0s: dict[int, Spline0] = field(default_factory=dict)
    spline1s: dict[int, Spline1] = field(default_factory=dict)
    aestats:  dict[int, Aestat] = field(default_factory=dict)
    aesurfs:  dict[int, Aesurf] = field(default_factory=dict)
    aelists:  dict[int, Aelist] = field(default_factory=dict)
    trims:    dict[int, Trim] = field(default_factory=dict)
    divergs:  dict[int, Diverg] = field(default_factory=dict)
    trimvars: dict[int, Trimvar] = field(default_factory=dict)
    trimobjs: dict[int, Trimobj] = field(default_factory=dict)
    trimcons: dict[int, list[Trimcon]] = field(default_factory=dict)
    gustlfs:  dict[int, Gustlf] = field(default_factory=dict)
    aecomps:  dict[str, Aecomp] = field(default_factory=dict)
    monpnt1s: dict[str, Monpnt1] = field(default_factory=dict)
    monpnt3s: dict[str, Monpnt3] = field(default_factory=dict)
    monsects: dict[str, Monsect] = field(default_factory=dict)
    supports: list[Suport] = field(default_factory=list)
    # Phase G0 — ZAERO-style transient maneuver-loads cards
    tabled1s: dict[int, Tabled1] = field(default_factory=dict)
    mldtimes: dict[int, Mldtime] = field(default_factory=dict)
    mldcomds: dict[int, Mldcomd] = field(default_factory=dict)
    mldprnts: dict[int, Mldprnt] = field(default_factory=dict)
    mldtrims: dict[int, Mldtrim] = field(default_factory=dict)
    mloads:   dict[int, Mloads] = field(default_factory=dict)
