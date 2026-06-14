import os
import re
import warnings
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Plotel, Rbe3, Rbe2, Cbush, Rbar
from sbeam.model.property import Pbar, Pbush
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2
from sbeam.model.load import Force, Moment, Load, Grav, Eigrl
from sbeam.model.constraint import Spc, Spc1, Suport
from sbeam.model.aero import (
    Aeros, Caero1, Paero1, Aefact, W2gj, Wkk, Aecorr, Set1,
    Spline2, Attach, Spline0, Spline1,
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
    Aecomp, Monpnt1, Monpnt3,
)
from sbeam.model.maneuver import Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads
from sbeam.parser.case_control import parse_case_control

_IGNORED_KEYWORDS = frozenset({"BEGIN", "BEGINBULK", "ENDDATA"})


def _split_free_field(line: str) -> list:
    return [f.strip() for f in line.split(",")]


def _split_fixed_field(line: str) -> list:
    line = line.ljust(72)
    return [line[i : i + 8].strip() for i in range(0, 72, 8)]


def _split_line(line: str) -> list:
    return _split_free_field(line) if "," in line else _split_fixed_field(line)


_NASTRAN_SCI = re.compile(r'([^eEdD+\-])([+-]\d+)$')


def _to_float(s: str) -> float:
    """Convert a BDF field string to float.

    Handles NASTRAN short scientific notation (e.g. '1.44+9' → 1.44e9)
    in addition to standard Python float literals.
    """
    s = s.strip()
    if not s:
        return 0.0
    m = _NASTRAN_SCI.search(s)
    if m:
        s = s[:m.start(2)] + 'e' + s[m.start(2):]
    return float(s)


def _to_int(s: str) -> int:
    return int(s.strip())


def _to_int_opt(s: str, default: int = 0) -> int:
    s = s.strip()
    return int(s) if s else default


def _to_float_or_none(s: str) -> Optional[float]:
    s = s.strip()
    return float(s) if s else None


def _to_int_or_none(s: str) -> Optional[int]:
    s = s.strip()
    return int(s) if s else None


def _is_continuation(fields: list) -> bool:
    if not fields:
        return False
    if fields[0].startswith("+"):
        return True
    # Unnamed continuation: blank first field with subsequent non-blank content
    if not fields[0].strip() and any(f.strip() for f in fields[1:]):
        return True
    return False


def _validate_dof(c: str, context: str) -> None:
    if not c or any(ch not in "123456" for ch in c):
        raise ValueError(f"{context}: invalid DOF string '{c}'")


def _handle_cord2r(fields: list, cont, bulk: BulkData) -> None:
    cid = _to_int(fields[1])
    rid = _to_int_opt(fields[2]) if len(fields) > 2 else 0
    a1  = _to_float(fields[3]) if len(fields) > 3 else 0.0
    a2  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    a3  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    b1  = _to_float(fields[6]) if len(fields) > 6 else 0.0
    b2  = _to_float(fields[7]) if len(fields) > 7 else 0.0
    b3  = _to_float(fields[8]) if len(fields) > 8 else 0.0

    if cont is None:
        raise ValueError(f"CORD2R {cid}: continuation line required (C1 C2 C3 missing)")

    c1  = _to_float(cont[1]) if len(cont) > 1 else 0.0
    c2  = _to_float(cont[2]) if len(cont) > 2 else 0.0
    c3  = _to_float(cont[3]) if len(cont) > 3 else 0.0

    if cid <= 0:
        raise ValueError(f"CORD2R CID must be > 0, got {cid}")
    if cid in bulk.cord2rs:
        raise ValueError(f"Duplicate coordinate system CID {cid}")

    bulk.cord2rs[cid] = Cord2r(
        cid=cid, rid=rid,
        a=(a1, a2, a3),
        b=(b1, b2, b3),
        c=(c1, c2, c3),
    )


def _handle_grid(fields: list, bulk: BulkData) -> None:
    gid = _to_int(fields[1])
    if gid in bulk.grids:
        raise ValueError(f"Duplicate GID {gid}")
    cp  = _to_int_opt(fields[2]) if len(fields) > 2 else 0
    x   = _to_float(fields[3]) if len(fields) > 3 else 0.0
    y   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    z   = _to_float(fields[5]) if len(fields) > 5 else 0.0
    cd  = _to_int_opt(fields[6]) if len(fields) > 6 else 0
    ps  = fields[7].strip() if len(fields) > 7 else ""
    bulk.grids[gid] = Grid(gid=gid, x=x, y=y, z=z, ps=ps, cp=cp, cd=cd)


def _handle_pbar(fields: list, cont, bulk: BulkData) -> None:
    pid = _to_int(fields[1])
    if pid in bulk.pbars:
        raise ValueError(f"Duplicate PID {pid}")
    mid = _to_int(fields[2])
    A   = _to_float(fields[3])
    I1  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    I2  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    J   = _to_float(fields[6]) if len(fields) > 6 else 0.0
    nsm = _to_float(fields[7]) if len(fields) > 7 else 0.0

    c1 = c2 = d1 = d2 = e1 = e2 = f1 = f2 = 0.0
    if cont is not None:
        def g(n):
            return _to_float(cont[n]) if len(cont) > n else 0.0
        c1, c2, d1, d2, e1, e2, f1, f2 = g(1), g(2), g(3), g(4), g(5), g(6), g(7), g(8)

    bulk.pbars[pid] = Pbar(
        pid=pid, mid=mid, A=A, I1=I1, I2=I2, J=J, nsm=nsm,
        c1=c1, c2=c2, d1=d1, d2=d2, e1=e1, e2=e2, f1=f1, f2=f2,
    )


def _handle_mat1(fields: list, bulk: BulkData) -> None:
    mid = _to_int(fields[1])
    if mid in bulk.mat1s:
        raise ValueError(f"Duplicate MID {mid}")
    E   = _to_float(fields[2])
    G   = _to_float(fields[3]) if len(fields) > 3 else 0.0
    nu  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    rho = _to_float(fields[5]) if len(fields) > 5 else 0.0
    # When G is not supplied, derive from the isotropic material relationship G = E / (2(1+ν))
    if G == 0.0 and nu != 0.0 and E != 0.0:
        G = E / (2.0 * (1.0 + nu))
    bulk.mat1s[mid] = Mat1(mid=mid, E=E, G=G, nu=nu, rho=rho)


def _handle_cbar(fields: list, cont, bulk: BulkData) -> None:
    eid  = _to_int(fields[1])
    pid  = _to_int(fields[2])
    ga   = _to_int(fields[3])
    gb   = _to_int(fields[4])
    x1   = _to_float(fields[5]) if len(fields) > 5 else 0.0
    x2   = _to_float(fields[6]) if len(fields) > 6 else 0.0
    x3   = _to_float(fields[7]) if len(fields) > 7 else 0.0
    offt = fields[8] if len(fields) > 8 and fields[8] else "GGG"
    pa   = cont[1] if cont is not None and len(cont) > 1 else ""
    pb   = cont[2] if cont is not None and len(cont) > 2 else ""

    if ga not in bulk.grids:
        raise ValueError(f"CBAR {eid}: grid GA={ga} not found")
    if gb not in bulk.grids:
        raise ValueError(f"CBAR {eid}: grid GB={gb} not found")
    if pid not in bulk.pbars:
        raise ValueError(f"CBAR {eid}: property PID={pid} not found")
    bulk.cbars[eid] = Cbar(eid=eid, pid=pid, ga=ga, gb=gb,
                           x1=x1, x2=x2, x3=x3, offt=offt, pa=pa, pb=pb)


def _handle_plotel(fields: list, bulk: BulkData) -> None:
    eid = _to_int(fields[1])
    g1  = _to_int(fields[2])
    g2  = _to_int(fields[3])
    if g1 not in bulk.grids:
        raise ValueError(f"PLOTEL {eid}: grid G1={g1} not found")
    if g2 not in bulk.grids:
        raise ValueError(f"PLOTEL {eid}: grid G2={g2} not found")
    bulk.plotels[eid] = Plotel(eid=eid, g1=g1, g2=g2)


def _handle_rbe3(fields: list, conts: list, bulk: BulkData) -> None:
    eid     = _to_int(fields[1])
    # fields[2] is always blank on an RBE3 card
    refgrid = _to_int(fields[3])
    refc    = fields[4].strip()

    all_fields = [f.strip() for f in fields[5:] if f.strip()]
    for cont in conts:
        all_fields += [f.strip() for f in cont[1:] if f.strip()]

    wt_gc: list = []
    k = 0
    while k < len(all_fields):
        wt = _to_float(all_fields[k]); k += 1
        if k >= len(all_fields):
            break
        c = all_fields[k].strip(); k += 1
        grids: list = []
        while k < len(all_fields):
            f = all_fields[k]
            if '.' in f or 'e' in f.lower() or 'E' in f:
                break  # next WT value (float)
            try:
                grids.append(int(f)); k += 1
            except ValueError:
                k += 1
        wt_gc.append((wt, c, grids))

    bulk.rbe3s[eid] = Rbe3(eid=eid, refgrid=refgrid, refc=refc, wt_gc=wt_gc)


def _handle_rbe2(fields: list, conts: list, bulk: BulkData) -> None:
    eid = _to_int(fields[1])
    gn  = _to_int(fields[2])
    cm  = fields[3].strip()
    _validate_dof(cm, f"RBE2 {eid}")

    gm: list = []
    for f in fields[4:]:
        if f.strip():
            gm.append(_to_int(f))
    for cont in conts:
        for f in cont[1:]:
            if f.strip():
                gm.append(_to_int(f))

    if gn not in bulk.grids:
        raise ValueError(f"RBE2 {eid}: independent grid GN={gn} not found")
    for dep_gid in gm:
        if dep_gid not in bulk.grids:
            raise ValueError(f"RBE2 {eid}: dependent grid GM={dep_gid} not found")

    bulk.rbe2s[eid] = Rbe2(eid=eid, gn=gn, cm=cm, gm=gm)


def _handle_rbar(fields: list, bulk: BulkData) -> None:
    eid = _to_int(fields[1])
    ga  = _to_int(fields[2])
    gb  = _to_int(fields[3])
    cna = fields[4].strip() if len(fields) > 4 and fields[4].strip() else "123456"
    cnb = fields[5].strip() if len(fields) > 5 and fields[5].strip() else ""

    if cna != "123456" or cnb not in ("", "0"):
        raise ValueError(
            f"RBAR {eid}: only CNA=123456/CNB=blank supported in Phase 1 "
            f"(got CNA={cna!r}, CNB={cnb!r})"
        )
    if ga not in bulk.grids:
        raise ValueError(f"RBAR {eid}: grid GA={ga} not found")
    if gb not in bulk.grids:
        raise ValueError(f"RBAR {eid}: grid GB={gb} not found")
    if ga == gb:
        raise ValueError(f"RBAR {eid}: GA and GB must be different grids")
    if eid in bulk.rbars:
        raise ValueError(f"Duplicate RBAR EID {eid}")

    bulk.rbars[eid] = Rbar(eid=eid, ga=ga, gb=gb, cna=cna, cnb=cnb)


def _handle_conm2(fields: list, cont, bulk: BulkData) -> None:
    eid = _to_int(fields[1])
    gid = _to_int(fields[2])
    cid = _to_int_opt(fields[3]) if len(fields) > 3 else 0
    m   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    x1  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    x2  = _to_float(fields[6]) if len(fields) > 6 else 0.0
    x3  = _to_float(fields[7]) if len(fields) > 7 else 0.0

    # Inertia tensor: fields 8-13 in free-field, or continuation line fields 1-6 in fixed-field
    def _gi(n: int) -> float:
        if len(fields) > n and fields[n].strip():
            return _to_float(fields[n])
        if cont is not None:
            k = n - 7  # fields[8] → cont[1], ..., fields[13] → cont[6]
            if len(cont) > k:
                return _to_float(cont[k])
        return 0.0

    bulk.conm2s[eid] = Conm2(
        eid=eid, gid=gid, cid=cid, m=m, x1=x1, x2=x2, x3=x3,
        i11=_gi(8), i21=_gi(9), i22=_gi(10),
        i31=_gi(11), i32=_gi(12), i33=_gi(13),
    )


def _handle_spc(fields: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    g1  = _to_int(fields[2])
    c1  = fields[3] if len(fields) > 3 else ""
    _validate_dof(c1, f"SPC {sid}")
    d1  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    g2  = _to_int_or_none(fields[5]) if len(fields) > 5 else None
    c2  = fields[6].strip() if len(fields) > 6 and fields[6].strip() else None
    if c2:
        _validate_dof(c2, f"SPC {sid}")
    d2  = _to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.spcs:
        bulk.spcs[sid] = []
    bulk.spcs[sid].append(Spc(sid=sid, g1=g1, c1=c1, d1=d1, g2=g2, c2=c2, d2=d2))


def _handle_spc1(fields: list, conts: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    c   = fields[2].strip()
    _validate_dof(c, f"SPC1 {sid}")
    grids = [_to_int(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        grids += [_to_int(f) for f in cont[1:] if f.strip()]
    if sid not in bulk.spc1s:
        bulk.spc1s[sid] = []
    bulk.spc1s[sid].append(Spc1(sid=sid, c=c, grids=grids))


def _handle_force(fields: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    gid = _to_int(fields[2])
    cid = _to_int_opt(fields[3]) if len(fields) > 3 else 0
    f   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    n1  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    n2  = _to_float(fields[6]) if len(fields) > 6 else 0.0
    n3  = _to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.forces:
        bulk.forces[sid] = []
    bulk.forces[sid].append(Force(sid=sid, gid=gid, cid=cid, f=f, n1=n1, n2=n2, n3=n3))


def _handle_moment(fields: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    gid = _to_int(fields[2])
    cid = _to_int_opt(fields[3]) if len(fields) > 3 else 0
    m   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    n1  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    n2  = _to_float(fields[6]) if len(fields) > 6 else 0.0
    n3  = _to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.moments:
        bulk.moments[sid] = []
    bulk.moments[sid].append(Moment(sid=sid, gid=gid, cid=cid, m=m, n1=n1, n2=n2, n3=n3))


def _handle_load(fields: list, cont, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    if sid in bulk.loads:
        raise ValueError(f"Duplicate LOAD SID {sid}")
    s   = _to_float(fields[2])
    raw = list(fields[3:])
    if cont is not None:
        raw += list(cont[1:])
    components = []
    for k in range(0, len(raw) - 1, 2):
        sf, lf = raw[k].strip(), raw[k + 1].strip()
        if sf and lf:
            components.append((_to_float(sf), _to_int(lf)))
    bulk.loads[sid] = Load(sid=sid, s=s, components=components)


def _handle_pbush(fields: list, bulk: BulkData) -> None:
    pid = _to_int(fields[1])
    if pid in bulk.pbushs:
        raise ValueError(f"Duplicate PBUSH PID {pid}")
    # Field layout: PBUSH, PID, K, K1, K2, K3, K4, K5, K6
    # fields[2] is the literal "K" keyword; K values start at fields[3]
    if len(fields) > 2 and fields[2].strip().upper() == "B":
        raise ValueError(f"PBUSH {pid}: B (damping) keyword not supported in Phase 2")
    k1 = _to_float(fields[3]) if len(fields) > 3 else 0.0
    k2 = _to_float(fields[4]) if len(fields) > 4 else 0.0
    k3 = _to_float(fields[5]) if len(fields) > 5 else 0.0
    k4 = _to_float(fields[6]) if len(fields) > 6 else 0.0
    k5 = _to_float(fields[7]) if len(fields) > 7 else 0.0
    k6 = _to_float(fields[8]) if len(fields) > 8 else 0.0
    bulk.pbushs[pid] = Pbush(pid=pid, k1=k1, k2=k2, k3=k3, k4=k4, k5=k5, k6=k6)


def _handle_cbush(fields: list, cont, bulk: BulkData) -> None:
    eid = _to_int(fields[1])
    pid = _to_int(fields[2])
    ga  = _to_int(fields[3])
    gb  = _to_int_or_none(fields[4]) if len(fields) > 4 else None
    # fields[5] = S (spring location ratio) — ignored
    # fields[6] = CID — must be 0 or blank
    if len(fields) > 6 and fields[6].strip():
        cid_val = fields[6].strip()
        if cid_val not in ("0",):
            try:
                if int(cid_val) != 0:
                    raise ValueError(f"CBUSH {eid}: CID={cid_val} not supported; only CID=0 is implemented")
            except ValueError as exc:
                if "not supported" in str(exc):
                    raise
    # Orientation vector from continuation line
    x1 = x2 = x3 = 0.0
    if cont is not None:
        x1 = _to_float(cont[1]) if len(cont) > 1 else 0.0
        x2 = _to_float(cont[2]) if len(cont) > 2 else 0.0
        x3 = _to_float(cont[3]) if len(cont) > 3 else 0.0

    if ga not in bulk.grids:
        raise ValueError(f"CBUSH {eid}: grid GA={ga} not found")
    if gb is not None and gb not in bulk.grids:
        raise ValueError(f"CBUSH {eid}: grid GB={gb} not found")
    if ga == gb:
        raise ValueError(f"CBUSH {eid}: GA and GB must be different grids")
    if pid not in bulk.pbushs:
        raise ValueError(f"CBUSH {eid}: property PID={pid} not found (PBUSH must precede CBUSH)")

    bulk.cbushs[eid] = Cbush(eid=eid, pid=pid, ga=ga, gb=gb, x1=x1, x2=x2, x3=x3)


def _handle_grav(fields: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    cid = _to_int_opt(fields[2]) if len(fields) > 2 else 0
    g   = _to_float(fields[3]) if len(fields) > 3 else 0.0
    n1  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    n2  = _to_float(fields[5]) if len(fields) > 5 else 0.0
    n3  = _to_float(fields[6]) if len(fields) > 6 else 0.0
    if cid != 0:
        raise ValueError(f"GRAV {sid}: CID={cid} not supported in Phase 1 (only CID=0)")
    if sid in bulk.gravs:
        raise ValueError(f"Duplicate GRAV SID {sid}")
    bulk.gravs[sid] = Grav(sid=sid, cid=cid, g=g, n1=n1, n2=n2, n3=n3)


def _handle_aeros(fields: list, bulk: BulkData) -> None:
    if bulk.aeros is not None:
        raise ValueError("Duplicate AEROS card")
    acsid = _to_int_opt(fields[1]) if len(fields) > 1 else 0
    rcsid = _to_int_opt(fields[2]) if len(fields) > 2 else 0
    cref  = _to_float(fields[3])   if len(fields) > 3 else 0.0
    bref  = _to_float(fields[4])   if len(fields) > 4 else 0.0
    sref  = _to_float(fields[5])   if len(fields) > 5 else 0.0
    symxz = _to_int_opt(fields[6]) if len(fields) > 6 else 0
    symxy = _to_int_opt(fields[7]) if len(fields) > 7 else 0
    # Field 8 is an sbeam extension; NASTRAN AEROS has no MACH field.
    mach  = _to_float(fields[8])   if len(fields) > 8 else 0.0
    bulk.aeros = Aeros(
        acsid=acsid, rcsid=rcsid, cref=cref, bref=bref,
        sref=sref, symxz=symxz, symxy=symxy, mach=mach,
    )


def _handle_aefact(fields: list, conts: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    if sid in bulk.aefacts:
        raise ValueError(f"Duplicate AEFACT SID {sid}")
    data = [_to_float(f) for f in fields[2:] if f.strip()]
    for cont in conts:
        data += [_to_float(f) for f in cont[1:] if f.strip()]
    bulk.aefacts[sid] = Aefact(sid=sid, data=data)


def _handle_w2gj(fields: list, conts: list, bulk: BulkData) -> None:
    sid       = _to_int(fields[1])
    caero_eid = _to_int(fields[2])
    if sid in bulk.w2gjs:
        raise ValueError(f"Duplicate W2GJ SID {sid}")
    data = [_to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        data += [_to_float(f) for f in cont[1:] if f.strip()]
    bulk.w2gjs[sid] = W2gj(sid=sid, caero_eid=caero_eid, data=data)


def _handle_wkk(fields: list, conts: list, bulk: BulkData) -> None:
    sid       = _to_int(fields[1])
    caero_eid = _to_int(fields[2])
    if sid in bulk.wkks:
        raise ValueError(f"Duplicate WKK SID {sid}")
    data = [_to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        data += [_to_float(f) for f in cont[1:] if f.strip()]
    bulk.wkks[sid] = Wkk(sid=sid, caero_eid=caero_eid, data=data)


def _handle_aecorr(fields: list, conts: list, bulk: BulkData) -> None:
    sid       = _to_int(fields[1])
    method    = fields[2].strip().upper() if len(fields) > 2 else ""
    caero_eid = _to_int(fields[3]) if len(fields) > 3 else 0
    if method not in ("WT1", "WT2"):
        raise ValueError(f"AECORR {sid}: METHOD must be WT1 or WT2, got '{method}'")
    if sid in bulk.aecorrs:
        raise ValueError(f"Duplicate AECORR SID {sid}")
    target = [_to_float(f) for f in fields[4:] if f.strip()]
    for cont in conts:
        target += [_to_float(f) for f in cont[1:] if f.strip()]
    bulk.aecorrs[sid] = Aecorr(sid=sid, method=method, caero_eid=caero_eid, target=target)


def _handle_paero1(fields: list, bulk: BulkData) -> None:
    pid = _to_int(fields[1])
    if pid in bulk.paero1s:
        raise ValueError(f"Duplicate PAERO1 PID {pid}")
    bulk.paero1s[pid] = Paero1(pid=pid)


def _handle_caero1(fields: list, cont, bulk: BulkData) -> None:
    eid    = _to_int(fields[1])
    pid    = _to_int(fields[2])
    cp     = _to_int_opt(fields[3]) if len(fields) > 3 else 0
    nspan  = _to_int_opt(fields[4]) if len(fields) > 4 else 0
    nchord = _to_int_opt(fields[5]) if len(fields) > 5 else 0
    lspan  = _to_int_opt(fields[6]) if len(fields) > 6 else 0
    lchord = _to_int_opt(fields[7]) if len(fields) > 7 else 0
    igid   = _to_int_opt(fields[8]) if len(fields) > 8 else 0

    if cont is None:
        raise ValueError(f"CAERO1 {eid}: continuation line required (P1/X12/P4/X43 missing)")

    x1  = _to_float(cont[1]) if len(cont) > 1 else 0.0
    y1  = _to_float(cont[2]) if len(cont) > 2 else 0.0
    z1  = _to_float(cont[3]) if len(cont) > 3 else 0.0
    x12 = _to_float(cont[4]) if len(cont) > 4 else 0.0
    x4  = _to_float(cont[5]) if len(cont) > 5 else 0.0
    y4  = _to_float(cont[6]) if len(cont) > 6 else 0.0
    z4  = _to_float(cont[7]) if len(cont) > 7 else 0.0
    x43 = _to_float(cont[8]) if len(cont) > 8 else 0.0

    if nspan == 0 and lspan == 0:
        raise ValueError(f"CAERO1 {eid}: exactly one of NSPAN or LSPAN must be non-zero")
    if nspan != 0 and lspan != 0:
        raise ValueError(f"CAERO1 {eid}: NSPAN and LSPAN cannot both be non-zero")
    if nchord == 0 and lchord == 0:
        raise ValueError(f"CAERO1 {eid}: exactly one of NCHORD or LCHORD must be non-zero")
    if nchord != 0 and lchord != 0:
        raise ValueError(f"CAERO1 {eid}: NCHORD and LCHORD cannot both be non-zero")
    if eid in bulk.caero1s:
        raise ValueError(f"Duplicate CAERO1 EID {eid}")

    bulk.caero1s[eid] = Caero1(
        eid=eid, pid=pid, cp=cp,
        nspan=nspan, nchord=nchord,
        lspan=lspan, lchord=lchord,
        igid=igid,
        p1=(x1, y1, z1), x12=x12,
        p4=(x4, y4, z4), x43=x43,
    )


def _handle_set1(fields: list, conts: list, bulk: BulkData) -> None:
    sid   = _to_int(fields[1])
    grids = [_to_int(f) for f in fields[2:] if f.strip()]
    for cont in conts:
        grids += [_to_int(f) for f in cont[1:] if f.strip()]
    if sid in bulk.set1s:
        raise ValueError(f"Duplicate SET1 SID {sid}")
    bulk.set1s[sid] = Set1(sid=sid, grids=grids)


def _handle_spline2(fields: list, cont, bulk: BulkData) -> None:
    eid   = _to_int(fields[1])
    caero = _to_int(fields[2])
    id1   = _to_int(fields[3])
    id2   = _to_int(fields[4])
    setg  = _to_int(fields[5])
    dz    = _to_float(fields[6]) if len(fields) > 6 and fields[6].strip() else 0.0
    dtor  = _to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 1.0
    cid   = _to_int_opt(fields[8]) if len(fields) > 8 else 0
    dthx  = 1.0
    dthz  = 0.0
    usage = "BOTH"
    if cont is not None:
        dthx  = _to_float(cont[1]) if len(cont) > 1 and cont[1].strip() else 1.0
        dthz  = _to_float(cont[2]) if len(cont) > 2 and cont[2].strip() else 0.0
        usage = cont[4].strip() if len(cont) > 4 and cont[4].strip() else "BOTH"
    if eid in bulk.spline2s:
        raise ValueError(f"Duplicate SPLINE2 EID {eid}")
    bulk.spline2s[eid] = Spline2(
        eid=eid, caero=caero, id1=id1, id2=id2, setg=setg,
        dz=dz, dtor=dtor, cid=cid, dthx=dthx, dthz=dthz, usage=usage,
    )


def _handle_attach(fields: list, bulk: BulkData) -> None:
    eid   = _to_int(fields[1])
    caero = _to_int(fields[2])
    id1   = _to_int(fields[3])
    id2   = _to_int(fields[4])
    grid  = _to_int(fields[5])
    cid   = _to_int_opt(fields[6]) if len(fields) > 6 else 0
    if eid in bulk.attaches:
        raise ValueError(f"Duplicate ATTACH EID {eid}")
    bulk.attaches[eid] = Attach(eid=eid, caero=caero, id1=id1, id2=id2, grid=grid, cid=cid)


def _handle_spline0(fields: list, bulk: BulkData) -> None:
    eid   = _to_int(fields[1])
    caero = _to_int(fields[2])
    id1   = _to_int(fields[3])
    id2   = _to_int(fields[4])
    if eid in bulk.spline0s:
        raise ValueError(f"Duplicate SPLINE0 EID {eid}")
    bulk.spline0s[eid] = Spline0(eid=eid, caero=caero, id1=id1, id2=id2)


def _handle_spline1(fields: list, bulk: BulkData) -> None:
    raise NotImplementedError(
        "SPLINE1 (Harder–Desmarais infinite-plate spline) is not yet implemented; "
        "use SPLINE2 or ATTACH instead"
    )


# ---------------------------------------------------------------------------
# Trim card set handlers (Step 51)
# ---------------------------------------------------------------------------

def _handle_aestat(fields: list, bulk: BulkData) -> None:
    aid   = _to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    if not label:
        raise ValueError(f"AESTAT {aid}: LABEL must not be blank")
    if aid in bulk.aestats:
        raise ValueError(f"Duplicate AESTAT ID {aid}")
    bulk.aestats[aid] = Aestat(id=aid, label=label)


def _handle_aesurf(fields: list, bulk: BulkData) -> None:
    aid   = _to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    cid1  = _to_int(fields[3]) if len(fields) > 3 else 0
    alid1 = _to_int(fields[4]) if len(fields) > 4 else 0
    cid2  = _to_int_opt(fields[5]) if len(fields) > 5 and fields[5].strip() else 0
    alid2 = _to_int_opt(fields[6]) if len(fields) > 6 and fields[6].strip() else 0
    eff   = _to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 1.0
    if not label:
        raise ValueError(f"AESURF {aid}: LABEL must not be blank")
    if aid in bulk.aesurfs:
        raise ValueError(f"Duplicate AESURF ID {aid}")
    bulk.aesurfs[aid] = Aesurf(id=aid, label=label, cid1=cid1, alid1=alid1,
                                cid2=cid2, alid2=alid2, eff=eff)


def _expand_int_list_with_thru(tokens: list) -> list:
    """Expand a token list that may contain THRU keywords into a flat integer list."""
    result = []
    k = 0
    while k < len(tokens):
        t = tokens[k].strip()
        if not t:
            k += 1
            continue
        if t.upper() == "THRU":
            start = result[-1]
            end = _to_int(tokens[k + 1])
            result.extend(range(start + 1, end + 1))
            k += 2
        else:
            result.append(_to_int(t))
            k += 1
    return result


def _handle_suport(fields: list, bulk: BulkData) -> None:
    """SUPORT card — pairs of GID/DOF starting at fields[1]."""
    i = 1
    while i + 1 < len(fields) and fields[i].strip():
        gid  = _to_int(fields[i])
        dofs = fields[i + 1].strip()
        if not dofs:
            raise ValueError(f"SUPORT: blank DOF string for GID {gid}")
        bulk.supports.append(Suport(gid=gid, dofs=dofs))
        i += 2


def _handle_aelist(fields: list, conts: list, bulk: BulkData) -> None:
    sid    = _to_int(fields[1])
    tokens = [f for f in fields[2:]]
    for cont in conts:
        tokens += list(cont[1:])
    elements = _expand_int_list_with_thru(tokens)
    if sid in bulk.aelists:
        raise ValueError(f"Duplicate AELIST SID {sid}")
    bulk.aelists[sid] = Aelist(sid=sid, elements=elements)


def _handle_aecomp(fields: list, conts: list, bulk: BulkData) -> None:
    """AECOMP NAME LISTTYPE LISTID1 LISTID2 ... (continuations add more list IDs).

    LISTTYPE is 'AELIST' (box-ID collection, used by MONPNT1) or 'SET1'
    (grid-ID collection, used by MONPNT3).
    """
    name     = fields[1].strip()
    listtype = fields[2].strip().upper() if len(fields) > 2 else ""
    if not name:
        raise ValueError("AECOMP: NAME must not be blank")
    if listtype not in ("AELIST", "SET1"):
        raise ValueError(f"AECOMP {name}: LISTTYPE must be 'AELIST' or 'SET1', got '{listtype}'")
    list_ids = [_to_int(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        list_ids += [_to_int(f) for f in cont[1:] if f.strip()]
    if name in bulk.aecomps:
        raise ValueError(f"Duplicate AECOMP NAME {name}")
    bulk.aecomps[name] = Aecomp(name=name, listtype=listtype, list_ids=list_ids)


def _handle_monpnt1(fields: list, bulk: BulkData) -> None:
    """MONPNT1 NAME LABEL AXES COMP CP X Y Z (aero-only integrated load)."""
    name  = fields[1].strip()
    label = fields[2].strip() if len(fields) > 2 else ""
    axes  = _to_int(fields[3]) if len(fields) > 3 and fields[3].strip() else 0
    comp  = fields[4].strip() if len(fields) > 4 else ""
    cp    = _to_int_opt(fields[5]) if len(fields) > 5 else 0
    x     = _to_float(fields[6]) if len(fields) > 6 and fields[6].strip() else 0.0
    y     = _to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 0.0
    z     = _to_float(fields[8]) if len(fields) > 8 and fields[8].strip() else 0.0
    if not name:
        raise ValueError("MONPNT1: NAME must not be blank")
    if name in bulk.monpnt1s:
        raise ValueError(f"Duplicate MONPNT1 NAME {name}")
    bulk.monpnt1s[name] = Monpnt1(name=name, label=label, axes=axes, comp=comp,
                                  cp=cp, x=x, y=y, z=z)


def _handle_monpnt3(fields: list, bulk: BulkData) -> None:
    """MONPNT3 NAME LABEL AXES COMP CP X Y Z (aero + inertia + reaction)."""
    name  = fields[1].strip()
    label = fields[2].strip() if len(fields) > 2 else ""
    axes  = _to_int(fields[3]) if len(fields) > 3 and fields[3].strip() else 0
    comp  = fields[4].strip() if len(fields) > 4 else ""
    cp    = _to_int_opt(fields[5]) if len(fields) > 5 else 0
    x     = _to_float(fields[6]) if len(fields) > 6 and fields[6].strip() else 0.0
    y     = _to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 0.0
    z     = _to_float(fields[8]) if len(fields) > 8 and fields[8].strip() else 0.0
    if not name:
        raise ValueError("MONPNT3: NAME must not be blank")
    if name in bulk.monpnt3s:
        raise ValueError(f"Duplicate MONPNT3 NAME {name}")
    bulk.monpnt3s[name] = Monpnt3(name=name, label=label, axes=axes, comp=comp,
                                  cp=cp, x=x, y=y, z=z)


def _handle_trim(fields: list, conts: list, bulk: BulkData) -> None:
    sid  = _to_int(fields[1])
    mach = _to_float(fields[2]) if len(fields) > 2 else 0.0
    q    = _to_float(fields[3]) if len(fields) > 3 else 0.0
    if sid in bulk.trims:
        raise ValueError(f"Duplicate TRIM SID {sid}")
    # Collect alternating LABEL/VALUE pairs from remainder of base line + continuations
    raw_pairs: list = list(fields[4:])
    for cont in conts:
        raw_pairs += list(cont[1:])
    vars_: dict = {}
    raw_pairs = [f for f in raw_pairs if f.strip()]
    if len(raw_pairs) % 2 != 0:
        raise ValueError(f"TRIM {sid}: odd number of LABEL/VALUE tokens — must be paired")
    for i in range(0, len(raw_pairs), 2):
        lbl = raw_pairs[i].strip().upper()
        val = _to_float(raw_pairs[i + 1])
        if lbl in vars_:
            raise ValueError(f"TRIM {sid}: duplicate label '{lbl}'")
        vars_[lbl] = val
    bulk.trims[sid] = Trim(sid=sid, mach=mach, q=q, vars=vars_)


def _handle_diverg(fields: list, conts: list, bulk: BulkData) -> None:
    sid    = _to_int(fields[1])
    nroots = _to_int(fields[2]) if len(fields) > 2 else 1
    machs  = [_to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        machs += [_to_float(f) for f in cont[1:] if f.strip()]
    if sid in bulk.divergs:
        raise ValueError(f"Duplicate DIVERG SID {sid}")
    bulk.divergs[sid] = Diverg(sid=sid, nroots=nroots, machs=machs)


# ---------------------------------------------------------------------------
# Phase G0 — ZAERO-style transient maneuver-loads cards
# ---------------------------------------------------------------------------

def _handle_tabled1(fields: list, conts: list, bulk: BulkData) -> None:
    """TABLED1 — tabular function: TID then (x, y) pairs terminated by ENDT."""
    tid   = _to_int(fields[1])
    xaxis = fields[2].strip().upper() if len(fields) > 2 and fields[2].strip() else "LINEAR"
    yaxis = fields[3].strip().upper() if len(fields) > 3 and fields[3].strip() else "LINEAR"
    if tid in bulk.tabled1s:
        raise ValueError(f"Duplicate TABLED1 TID {tid}")
    # Data pairs live entirely on the continuation line(s); fields[4:] of the
    # base line are reserved/blank in the NASTRAN layout.
    tokens: list = [f for f in fields[4:]]
    for cont in conts:
        tokens += list(cont[1:])
    tokens = [t.strip() for t in tokens if t.strip()]
    xs: list = []
    ys: list = []
    k = 0
    while k < len(tokens):
        if tokens[k].upper() == "ENDT":
            break
        if k + 1 >= len(tokens):
            raise ValueError(f"TABLED1 {tid}: dangling abscissa with no ordinate")
        xs.append(_to_float(tokens[k]))
        ys.append(_to_float(tokens[k + 1]))
        k += 2
    if len(xs) < 2:
        raise ValueError(f"TABLED1 {tid}: needs at least two (x, y) points")
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        raise ValueError(f"TABLED1 {tid}: abscissae must be strictly increasing")
    bulk.tabled1s[tid] = Tabled1(tid=tid, xs=xs, ys=ys, xaxis=xaxis, yaxis=yaxis)


def _handle_mldtime(fields: list, bulk: BulkData) -> None:
    """MLDTIME — integration window: SID T0 TEND DT [TOUT]."""
    sid  = _to_int(fields[1])
    t0   = _to_float(fields[2]) if len(fields) > 2 else 0.0
    tend = _to_float(fields[3]) if len(fields) > 3 else 0.0
    dt   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    tout = _to_float(fields[5]) if len(fields) > 5 and fields[5].strip() else 0.0
    if dt <= 0.0:
        raise ValueError(f"MLDTIME {sid}: DT must be positive")
    if tend <= t0:
        raise ValueError(f"MLDTIME {sid}: TEND must exceed T0")
    if sid in bulk.mldtimes:
        raise ValueError(f"Duplicate MLDTIME SID {sid}")
    bulk.mldtimes[sid] = Mldtime(sid=sid, t0=t0, tend=tend, dt=dt, tout=tout)


def _handle_mldcomd(fields: list, conts: list, bulk: BulkData) -> None:
    """MLDCOMD — pilot commands: SID then (LABEL, TABID) pairs."""
    sid = _to_int(fields[1])
    if sid in bulk.mldcomds:
        raise ValueError(f"Duplicate MLDCOMD SID {sid}")
    tokens: list = list(fields[2:])
    for cont in conts:
        tokens += list(cont[1:])
    tokens = [t for t in tokens if t.strip()]
    if len(tokens) % 2 != 0:
        raise ValueError(f"MLDCOMD {sid}: odd number of LABEL/TABID tokens — must be paired")
    commands: list = []
    for i in range(0, len(tokens), 2):
        label = tokens[i].strip().upper()
        tabid = _to_int(tokens[i + 1])
        commands.append((label, tabid))
    bulk.mldcomds[sid] = Mldcomd(sid=sid, commands=commands)


def _handle_mldprnt(fields: list, conts: list, bulk: BulkData) -> None:
    """MLDPRNT — ASCII time-history output request: SID then optional item keywords."""
    sid = _to_int(fields[1])
    if sid in bulk.mldprnts:
        raise ValueError(f"Duplicate MLDPRNT SID {sid}")
    items: list = [f.strip().upper() for f in fields[2:] if f.strip()]
    for cont in conts:
        items += [f.strip().upper() for f in cont[1:] if f.strip()]
    bulk.mldprnts[sid] = Mldprnt(sid=sid, items=items)


def _handle_mldtrim(fields: list, bulk: BulkData) -> None:
    """MLDTRIM — initial steady-state condition: SID TRIMID (a static TRIM sid)."""
    sid      = _to_int(fields[1])
    trim_sid = _to_int(fields[2])
    if sid in bulk.mldtrims:
        raise ValueError(f"Duplicate MLDTRIM SID {sid}")
    bulk.mldtrims[sid] = Mldtrim(sid=sid, trim_sid=trim_sid)


def _handle_mloads(fields: list, bulk: BulkData) -> None:
    """MLOADS — transient driver: SID MLDTRIM MLDTIME [MLDCOMD] [MLDPRNT] [NMODES]."""
    sid     = _to_int(fields[1])
    mldtrim = _to_int(fields[2])
    mldtime = _to_int(fields[3])
    mldcomd = _to_int(fields[4]) if len(fields) > 4 and fields[4].strip() else 0
    mldprnt = _to_int(fields[5]) if len(fields) > 5 and fields[5].strip() else 0
    nmodes  = _to_int(fields[6]) if len(fields) > 6 and fields[6].strip() else 0
    if sid in bulk.mloads:
        raise ValueError(f"Duplicate MLOADS SID {sid}")
    bulk.mloads[sid] = Mloads(
        sid=sid, mldtrim=mldtrim, mldtime=mldtime,
        mldcomd=mldcomd, mldprnt=mldprnt, nmodes=nmodes,
    )


def _handle_trimvar(fields: list, bulk: BulkData) -> None:
    vid   = _to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    init  = _to_float(fields[3]) if len(fields) > 3 else 0.0
    lb    = _to_float(fields[4]) if len(fields) > 4 else -1.0e30
    ub    = _to_float(fields[5]) if len(fields) > 5 else  1.0e30
    if not label:
        raise ValueError(f"TRIMVAR {vid}: LABEL must not be blank")
    if vid in bulk.trimvars:
        raise ValueError(f"Duplicate TRIMVAR ID {vid}")
    bulk.trimvars[vid] = Trimvar(id=vid, label=label, init=init, lb=lb, ub=ub)


def _handle_trimobj(fields: list, conts: list, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    if sid in bulk.trimobjs:
        raise ValueError(f"Duplicate TRIMOBJ SID {sid}")
    raw_pairs: list = list(fields[2:])
    for cont in conts:
        raw_pairs += list(cont[1:])
    raw_pairs = [f for f in raw_pairs if f.strip()]
    if len(raw_pairs) % 2 != 0:
        raise ValueError(f"TRIMOBJ {sid}: odd number of LABEL/WEIGHT tokens — must be paired")
    labels:  list = []
    weights: list = []
    for i in range(0, len(raw_pairs), 2):
        labels.append(raw_pairs[i].strip().upper())
        weights.append(_to_float(raw_pairs[i + 1]))
    bulk.trimobjs[sid] = Trimobj(sid=sid, labels=labels, weights=weights)


def _handle_trimcon(fields: list, bulk: BulkData) -> None:
    sid   = _to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    sense = fields[3].strip().upper() if len(fields) > 3 else ""
    rhs   = _to_float(fields[4]) if len(fields) > 4 else 0.0
    if sense not in ("LE", "GE"):
        raise ValueError(f"TRIMCON {sid}: SENSE must be LE or GE, got '{sense}'")
    # Multiple TRIMCON cards share a SID — collect as list
    bulk.trimcons.setdefault(sid, []).append(Trimcon(sid=sid, label=label, sense=sense, rhs=rhs))


def _handle_eigrl(fields: list, bulk: BulkData) -> None:
    sid  = _to_int(fields[1])
    v1   = _to_float_or_none(fields[2]) if len(fields) > 2 else None
    v2   = _to_float_or_none(fields[3]) if len(fields) > 3 else None
    nd   = _to_int_or_none(fields[4]) if len(fields) > 4 else None
    # fields[5–7] are MSGLVL, MAXSET, SHFSCL — not used in phase 1
    norm = fields[8].strip() if len(fields) > 8 and fields[8].strip() else "MASS"
    bulk.eigrls[sid] = Eigrl(sid=sid, v1=v1, v2=v2, nd=nd, norm=norm)


def parse_bulk_data(lines: list) -> BulkData:
    """Parse BDF bulk data lines into a BulkData object.

    Supports free-field (comma-separated) and fixed-field (8-character column) formats.
    Issues UserWarning for unrecognised card keywords.
    Raises ValueError for duplicate GIDs, invalid DOF strings, and unresolved LOAD references.
    """
    bulk = BulkData()

    # Strip $ comments; a $ anywhere on the line starts a comment
    processed = []
    for raw in lines:
        idx = raw.find("$")
        processed.append(raw[:idx].rstrip() if idx >= 0 else raw.rstrip())

    i = 0
    while i < len(processed):
        line = processed[i]

        if not line.strip():
            i += 1
            continue

        fields = _split_line(line)
        if not fields or not fields[0]:
            i += 1
            continue

        keyword = fields[0].upper()

        if keyword in _IGNORED_KEYWORDS:
            i += 1
            continue

        if _is_continuation(fields):
            i += 1
            continue

        # Look ahead for a continuation line (skip intervening blank lines)
        cont = None
        j = i + 1
        while j < len(processed) and not processed[j].strip():
            j += 1
        if j < len(processed):
            nf = _split_line(processed[j])
            if _is_continuation(nf):
                cont = nf

        if keyword == "CORD2R":
            _handle_cord2r(fields, cont, bulk)
        elif keyword == "GRID":
            _handle_grid(fields, bulk)
        elif keyword == "PBAR":
            _handle_pbar(fields, cont, bulk)
        elif keyword == "MAT1":
            _handle_mat1(fields, bulk)
        elif keyword == "PBUSH":
            _handle_pbush(fields, bulk)
        elif keyword == "CBUSH":
            _handle_cbush(fields, cont, bulk)
        elif keyword == "CBAR":
            _handle_cbar(fields, cont, bulk)
        elif keyword == "PLOTEL":
            _handle_plotel(fields, bulk)
        elif keyword == "RBE3":
            conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    conts.append(nf)
                    k += 1
                else:
                    break
            _handle_rbe3(fields, conts, bulk)
        elif keyword == "RBE2":
            conts2: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    conts2.append(nf)
                    k += 1
                else:
                    break
            _handle_rbe2(fields, conts2, bulk)
        elif keyword == "RBAR":
            _handle_rbar(fields, bulk)
        elif keyword == "CONM2":
            _handle_conm2(fields, cont, bulk)
        elif keyword == "SPC":
            _handle_spc(fields, bulk)
        elif keyword == "SPC1":
            spc1_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    spc1_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_spc1(fields, spc1_conts, bulk)
        elif keyword == "FORCE":
            _handle_force(fields, bulk)
        elif keyword == "MOMENT":
            _handle_moment(fields, bulk)
        elif keyword == "LOAD":
            _handle_load(fields, cont, bulk)
        elif keyword == "GRAV":
            _handle_grav(fields, bulk)
        elif keyword == "EIGRL":
            _handle_eigrl(fields, bulk)
        elif keyword == "AEROS":
            _handle_aeros(fields, bulk)
        elif keyword == "AEFACT":
            aefact_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    aefact_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_aefact(fields, aefact_conts, bulk)
        elif keyword == "W2GJ":
            w2gj_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    w2gj_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_w2gj(fields, w2gj_conts, bulk)
        elif keyword == "WKK":
            wkk_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    wkk_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_wkk(fields, wkk_conts, bulk)
        elif keyword == "AECORR":
            aecorr_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    aecorr_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_aecorr(fields, aecorr_conts, bulk)
        elif keyword == "PAERO1":
            _handle_paero1(fields, bulk)
        elif keyword == "CAERO1":
            _handle_caero1(fields, cont, bulk)
        elif keyword == "SET1":
            set1_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    set1_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_set1(fields, set1_conts, bulk)
        elif keyword == "SPLINE2":
            _handle_spline2(fields, cont, bulk)
        elif keyword == "ATTACH":
            _handle_attach(fields, bulk)
        elif keyword == "SPLINE0":
            _handle_spline0(fields, bulk)
        elif keyword == "SPLINE1":
            _handle_spline1(fields, bulk)
        elif keyword == "AESTAT":
            _handle_aestat(fields, bulk)
        elif keyword == "AESURF":
            _handle_aesurf(fields, bulk)
        elif keyword == "AELIST":
            aelist_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    aelist_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_aelist(fields, aelist_conts, bulk)
        elif keyword == "TRIM":
            trim_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    trim_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_trim(fields, trim_conts, bulk)
        elif keyword == "DIVERG":
            diverg_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    diverg_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_diverg(fields, diverg_conts, bulk)
        elif keyword == "TRIMVAR":
            _handle_trimvar(fields, bulk)
        elif keyword == "TRIMOBJ":
            trimobj_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    trimobj_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_trimobj(fields, trimobj_conts, bulk)
        elif keyword == "TRIMCON":
            _handle_trimcon(fields, bulk)
        elif keyword == "AECOMP":
            aecomp_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    aecomp_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_aecomp(fields, aecomp_conts, bulk)
        elif keyword == "MONPNT1":
            _handle_monpnt1(fields, bulk)
        elif keyword == "MONPNT3":
            _handle_monpnt3(fields, bulk)
        elif keyword == "SUPORT":
            _handle_suport(fields, bulk)
        elif keyword == "TABLED1":
            tabled1_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    tabled1_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_tabled1(fields, tabled1_conts, bulk)
        elif keyword == "MLDTIME":
            _handle_mldtime(fields, bulk)
        elif keyword == "MLDCOMD":
            mldcomd_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    mldcomd_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_mldcomd(fields, mldcomd_conts, bulk)
        elif keyword == "MLDPRNT":
            mldprnt_conts: list = []
            k = i + 1
            while k < len(processed):
                if not processed[k].strip():
                    k += 1
                    continue
                nf = _split_line(processed[k])
                if _is_continuation(nf):
                    mldprnt_conts.append(nf)
                    k += 1
                else:
                    break
            _handle_mldprnt(fields, mldprnt_conts, bulk)
        elif keyword == "MLDTRIM":
            _handle_mldtrim(fields, bulk)
        elif keyword == "MLOADS":
            _handle_mloads(fields, bulk)
        else:
            warnings.warn(f"Unknown BDF card '{keyword}' — skipped", UserWarning, stacklevel=2)

        i += 1

    # CAERO1 cards require an AEROS card to provide reference geometry
    if bulk.caero1s and bulk.aeros is None:
        raise ValueError("CAERO1 card(s) present but no AEROS card found")

    # Validate CAERO1 cross-references (deferred because AEFACT/PAERO1 may appear after CAERO1)
    for eid, caero in bulk.caero1s.items():
        if caero.pid not in bulk.paero1s:
            raise ValueError(f"CAERO1 {eid}: PID={caero.pid} not found in PAERO1")
        if caero.lspan and caero.lspan not in bulk.aefacts:
            raise ValueError(f"CAERO1 {eid}: LSPAN={caero.lspan} not found in AEFACT")
        if caero.lchord and caero.lchord not in bulk.aefacts:
            raise ValueError(f"CAERO1 {eid}: LCHORD={caero.lchord} not found in AEFACT")

    # Validate SPLINE2 cross-references (SET1 SID, CAERO1 EID, grid IDs)
    for eid, sp in bulk.spline2s.items():
        if sp.setg not in bulk.set1s:
            raise ValueError(f"SPLINE2 {eid}: SETG={sp.setg} not found in SET1")
        if sp.caero not in bulk.caero1s:
            raise ValueError(f"SPLINE2 {eid}: CAERO={sp.caero} not found in CAERO1")
    for sid, s1 in bulk.set1s.items():
        for gid in s1.grids:
            if gid not in bulk.grids:
                raise ValueError(f"SET1 {sid}: grid ID {gid} not found in GRID")

    # Validate LOAD component references after all cards are parsed
    for load_sid, load in bulk.loads.items():
        for _, comp_sid in load.components:
            if (comp_sid not in bulk.forces
                    and comp_sid not in bulk.moments
                    and comp_sid not in bulk.gravs):
                raise ValueError(
                    f"LOAD {load_sid}: component SID {comp_sid} not found in FORCE, MOMENT, or GRAV sets"
                )

    # Validate AESURF → AELIST references
    for aid, aesurf in bulk.aesurfs.items():
        if aesurf.alid1 not in bulk.aelists:
            raise ValueError(f"AESURF {aid}: ALID1={aesurf.alid1} not found in AELIST")
        if aesurf.alid2 and aesurf.alid2 not in bulk.aelists:
            raise ValueError(f"AESURF {aid}: ALID2={aesurf.alid2} not found in AELIST")

    # Validate AELIST box IDs fall within declared CAERO1 ranges
    if bulk.aelists and bulk.caero1s:
        caero_ranges = [
            range(c.eid, c.eid + c.nspan * c.nchord)
            for c in bulk.caero1s.values()
        ]
        for sid, aelist in bulk.aelists.items():
            for box_id in aelist.elements:
                if not any(box_id in r for r in caero_ranges):
                    raise ValueError(
                        f"AELIST {sid}: box ID {box_id} not within any CAERO1 range"
                    )

    # Validate AECOMP list references and MONPNT1/MONPNT3 cross-references
    for name, aecomp in bulk.aecomps.items():
        target = bulk.aelists if aecomp.listtype == "AELIST" else bulk.set1s
        for lid in aecomp.list_ids:
            if lid not in target:
                raise ValueError(
                    f"AECOMP {name}: {aecomp.listtype} SID {lid} not found"
                )
    for name, mon in bulk.monpnt1s.items():
        if mon.comp not in bulk.aecomps:
            raise ValueError(f"MONPNT1 {name}: COMP '{mon.comp}' not found in AECOMP")
        if bulk.aecomps[mon.comp].listtype != "AELIST":
            raise ValueError(
                f"MONPNT1 {name}: COMP '{mon.comp}' must reference an AELIST-type AECOMP"
            )
        if mon.cp and mon.cp not in bulk.cord2rs:
            raise ValueError(f"MONPNT1 {name}: CP={mon.cp} not found in CORD2R")
    for name, mon in bulk.monpnt3s.items():
        if mon.comp not in bulk.aecomps:
            raise ValueError(f"MONPNT3 {name}: COMP '{mon.comp}' not found in AECOMP")
        if bulk.aecomps[mon.comp].listtype != "SET1":
            raise ValueError(
                f"MONPNT3 {name}: COMP '{mon.comp}' must reference a SET1-type AECOMP"
            )
        if mon.cp and mon.cp not in bulk.cord2rs:
            raise ValueError(f"MONPNT3 {name}: CP={mon.cp} not found in CORD2R")

    # Validate TRIM label cross-references and emit DOF-count diagnostics
    all_trim_labels = (
        {a.label for a in bulk.aestats.values()}
        | {s.label for s in bulk.aesurfs.values()}
    )
    for sid, trim in bulk.trims.items():
        for lbl in trim.vars:
            if lbl not in all_trim_labels:
                raise ValueError(
                    f"TRIM {sid}: label '{lbl}' not defined in any AESTAT or AESURF card"
                )
        prescribed = set(trim.vars.keys())
        free = all_trim_labels - prescribed
        if len(free) == 0:
            warnings.warn(
                f"TRIM {sid}: all trim variables are prescribed — no DOFs remain to solve",
                UserWarning, stacklevel=2,
            )
        elif len(free) > len(prescribed):
            obj_sids = set(bulk.trimobjs.keys())
            if not obj_sids:
                warnings.warn(
                    f"TRIM {sid}: over-determined ({len(free)} free vs {len(prescribed)} "
                    "equations) but no TRIMOBJ card present — add TRIMOBJ to specify the "
                    "weighted objective",
                    UserWarning, stacklevel=2,
                )

    # Validate ZAERO transient maneuver-loads (Phase G0) cross-references
    for sid, mc in bulk.mldcomds.items():
        for label, tabid in mc.commands:
            if label not in all_trim_labels:
                raise ValueError(
                    f"MLDCOMD {sid}: command label '{label}' not defined in any "
                    "AESTAT or AESURF card"
                )
            if tabid not in bulk.tabled1s:
                raise ValueError(f"MLDCOMD {sid}: TABID {tabid} not found in TABLED1")
    for sid, mt in bulk.mldtrims.items():
        if mt.trim_sid not in bulk.trims:
            raise ValueError(f"MLDTRIM {sid}: TRIMID {mt.trim_sid} not found in TRIM")
    for sid, ml in bulk.mloads.items():
        if ml.mldtrim not in bulk.mldtrims:
            raise ValueError(f"MLOADS {sid}: MLDTRIM {ml.mldtrim} not found")
        if ml.mldtime not in bulk.mldtimes:
            raise ValueError(f"MLOADS {sid}: MLDTIME {ml.mldtime} not found")
        if ml.mldcomd and ml.mldcomd not in bulk.mldcomds:
            raise ValueError(f"MLOADS {sid}: MLDCOMD {ml.mldcomd} not found")
        if ml.mldprnt and ml.mldprnt not in bulk.mldprnts:
            raise ValueError(f"MLOADS {sid}: MLDPRNT {ml.mldprnt} not found")

    # Resolve all grid positions from their CP system into global CID 0
    from sbeam.assembly.coord_transform import resolve_grid_positions
    resolve_grid_positions(bulk)

    return bulk


def parse_bulk_file(filepath: str) -> BulkData:
    """Parse a bulk-data-only file and return a BulkData object.

    Handles files with or without a BEGIN BULK header line.  Does not
    require or parse any case control section — useful for loading model
    geometry into the viewer before case control has been defined.

    Raises FileNotFoundError if the file does not exist.
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    # If a BEGIN BULK line is present, discard everything before it
    bulk_start = 0
    for i, line in enumerate(lines):
        idx = line.find("$")
        clean = (line[:idx] if idx >= 0 else line).strip()
        if clean.upper().startswith("BEGIN"):
            bulk_start = i + 1
            break

    return parse_bulk_data([line.rstrip("\n") for line in lines[bulk_start:]])


def parse_bdf(filepath: str) -> tuple:
    """Read a BDF file and return (CaseControl, BulkData).

    Handles single-file models (bulk data after BEGIN BULK in the same file)
    and two-file models (INCLUDE in the case control section points to a
    separate bulk data file).

    Raises FileNotFoundError if the main file or an INCLUDE file does not exist.
    Raises ValueError if the SOL value is not supported (101 or 103).
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    # Split on the first BEGIN BULK line
    begin_bulk_idx = None
    for i, line in enumerate(lines):
        idx = line.find("$")
        clean = (line[:idx] if idx >= 0 else line).strip()
        if clean.upper().startswith("BEGIN"):
            begin_bulk_idx = i
            break

    if begin_bulk_idx is None:
        cc_lines = lines
        bulk_lines = []
    else:
        cc_lines = lines[:begin_bulk_idx]
        bulk_lines = lines[begin_bulk_idx + 1:]

    cc = parse_case_control([line.rstrip("\n") for line in cc_lines])

    if cc.include is not None:
        base_dir = os.path.dirname(os.path.abspath(filepath))
        include_path = (
            cc.include if os.path.isabs(cc.include)
            else os.path.join(base_dir, cc.include)
        )
        if not os.path.exists(include_path):
            raise FileNotFoundError(f"INCLUDE file not found: {cc.include!r}")
        with open(include_path, "r") as fh:
            bulk_lines = fh.readlines()

    bulk = parse_bulk_data([line.rstrip("\n") for line in bulk_lines])
    return cc, bulk
