"""Structural bulk-card handlers: frames, grids, properties, materials, elements,
mass, constraints, static loads and solver parameters (#48)."""
import warnings
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Conrod, Crod, Plotel, Rbe3, Rbe2, Cbush, Rbar
from sbeam.model.property import Pbar, Pbush, Prod
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2, Massset
from sbeam.model.load import Force, Moment, Load, Grav, Eigrl
from sbeam.model.constraint import Spc, Spc1, Suport
from sbeam.parser.bulk_fields import (
    FieldHandler, ContHandler, MultiHandler,
    to_float, to_int, to_int_opt, to_float_or_none, to_int_or_none, validate_dof,
)


def _handle_cord2r(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    cid = to_int(fields[1])
    rid = to_int_opt(fields[2]) if len(fields) > 2 else 0
    a1  = to_float(fields[3]) if len(fields) > 3 else 0.0
    a2  = to_float(fields[4]) if len(fields) > 4 else 0.0
    a3  = to_float(fields[5]) if len(fields) > 5 else 0.0
    b1  = to_float(fields[6]) if len(fields) > 6 else 0.0
    b2  = to_float(fields[7]) if len(fields) > 7 else 0.0
    b3  = to_float(fields[8]) if len(fields) > 8 else 0.0

    if cont is None:
        raise ValueError(f"CORD2R {cid}: continuation line required (C1 C2 C3 missing)")

    c1  = to_float(cont[1]) if len(cont) > 1 else 0.0
    c2  = to_float(cont[2]) if len(cont) > 2 else 0.0
    c3  = to_float(cont[3]) if len(cont) > 3 else 0.0

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


def _handle_grid(fields: list[str], bulk: BulkData) -> None:
    gid = to_int(fields[1])
    if gid in bulk.grids:
        raise ValueError(f"Duplicate GID {gid}")
    cp  = to_int_opt(fields[2]) if len(fields) > 2 else 0
    x   = to_float(fields[3]) if len(fields) > 3 else 0.0
    y   = to_float(fields[4]) if len(fields) > 4 else 0.0
    z   = to_float(fields[5]) if len(fields) > 5 else 0.0
    cd  = to_int_opt(fields[6]) if len(fields) > 6 else 0
    ps  = fields[7].strip() if len(fields) > 7 else ""
    bulk.grids[gid] = Grid(gid=gid, x=x, y=y, z=z, ps=ps, cp=cp, cd=cd)


def _handle_pbar(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    pid = to_int(fields[1])
    if pid in bulk.pbars or pid in bulk.prods:
        raise ValueError(f"Duplicate PID {pid}")
    mid = to_int(fields[2])
    A   = to_float(fields[3])
    I1  = to_float(fields[4]) if len(fields) > 4 else 0.0
    I2  = to_float(fields[5]) if len(fields) > 5 else 0.0
    J   = to_float(fields[6]) if len(fields) > 6 else 0.0
    nsm = to_float(fields[7]) if len(fields) > 7 else 0.0

    c1 = c2 = d1 = d2 = e1 = e2 = f1 = f2 = 0.0
    if cont is not None:
        def g(n: int) -> float:
            return to_float(cont[n]) if len(cont) > n else 0.0
        c1, c2, d1, d2, e1, e2, f1, f2 = g(1), g(2), g(3), g(4), g(5), g(6), g(7), g(8)

    bulk.pbars[pid] = Pbar(
        pid=pid, mid=mid, A=A, I1=I1, I2=I2, J=J, nsm=nsm,
        c1=c1, c2=c2, d1=d1, d2=d2, e1=e1, e2=e2, f1=f1, f2=f2,
    )


def _handle_mat1(fields: list[str], bulk: BulkData) -> None:
    mid = to_int(fields[1])
    if mid in bulk.mat1s:
        raise ValueError(f"Duplicate MID {mid}")
    E   = to_float(fields[2])
    G   = to_float(fields[3]) if len(fields) > 3 else 0.0
    nu  = to_float(fields[4]) if len(fields) > 4 else 0.0
    rho = to_float(fields[5]) if len(fields) > 5 else 0.0
    # When G is not supplied, derive from the isotropic material relationship G = E / (2(1+ν))
    if G == 0.0 and nu != 0.0 and E != 0.0:
        G = E / (2.0 * (1.0 + nu))
    bulk.mat1s[mid] = Mat1(mid=mid, E=E, G=G, nu=nu, rho=rho)


def _check_unique_eid(bulk: BulkData, card: str, eid: int) -> None:
    """Element IDs share one space across the structural element cards (#38 D7)."""
    for name, coll in (("CBAR", bulk.cbars), ("CROD", bulk.crods),
                       ("CONROD", bulk.conrods), ("CBUSH", bulk.cbushs)):
        if eid in coll:
            raise ValueError(f"{card} {eid}: duplicate element ID (already defined by {name} {eid})")


def _check_distinct_ends(card: str, eid: int, ga: int, gb: Optional[int]) -> None:
    if ga == gb:
        raise ValueError(f"{card} {eid}: GA and GB must be different grids")


def _check_rod_section(card: str, ident: int, A: float, J: float) -> None:
    if A <= 0.0:
        raise ValueError(f"{card} {ident}: A must be positive (got {A})")
    if J < 0.0:
        raise ValueError(f"{card} {ident}: J must be non-negative (got {J})")


def _handle_prod(fields: list[str], bulk: BulkData) -> None:
    pid = to_int(fields[1])
    if pid in bulk.prods or pid in bulk.pbars:
        raise ValueError(f"Duplicate PID {pid}")
    mid = to_int(fields[2])
    A   = to_float(fields[3])
    J   = to_float(fields[4]) if len(fields) > 4 else 0.0
    c   = to_float(fields[5]) if len(fields) > 5 else 0.0
    nsm = to_float(fields[6]) if len(fields) > 6 else 0.0
    _check_rod_section("PROD", pid, A, J)
    bulk.prods[pid] = Prod(pid=pid, mid=mid, A=A, J=J, c=c, nsm=nsm)


def _handle_crod(fields: list[str], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    pid = to_int(fields[2])
    ga  = to_int(fields[3])
    gb  = to_int(fields[4])
    _check_unique_eid(bulk, "CROD", eid)
    _check_distinct_ends("CROD", eid, ga, gb)
    bulk.crods[eid] = Crod(eid=eid, pid=pid, ga=ga, gb=gb)


def _handle_conrod(fields: list[str], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    ga  = to_int(fields[2])
    gb  = to_int(fields[3])
    mid = to_int(fields[4])
    A   = to_float(fields[5])
    J   = to_float(fields[6]) if len(fields) > 6 else 0.0
    c   = to_float(fields[7]) if len(fields) > 7 else 0.0
    nsm = to_float(fields[8]) if len(fields) > 8 else 0.0
    _check_unique_eid(bulk, "CONROD", eid)
    _check_distinct_ends("CONROD", eid, ga, gb)
    _check_rod_section("CONROD", eid, A, J)
    bulk.conrods[eid] = Conrod(eid=eid, ga=ga, gb=gb, mid=mid, A=A, J=J, c=c, nsm=nsm)


def _handle_cbar(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    eid  = to_int(fields[1])
    pid  = to_int(fields[2])
    ga   = to_int(fields[3])
    gb   = to_int(fields[4])
    x1   = to_float(fields[5]) if len(fields) > 5 else 0.0
    x2   = to_float(fields[6]) if len(fields) > 6 else 0.0
    x3   = to_float(fields[7]) if len(fields) > 7 else 0.0
    offt = fields[8] if len(fields) > 8 and fields[8] else "GGG"
    pa   = cont[1] if cont is not None and len(cont) > 1 else ""
    pb   = cont[2] if cont is not None and len(cont) > 2 else ""

    _check_unique_eid(bulk, "CBAR", eid)
    if pa:
        validate_dof(pa, f"CBAR {eid} PA")
    if pb:
        validate_dof(pb, f"CBAR {eid} PB")
    # Releasing the same translation or torsion at both ends leaves an internal
    # mechanism (designs/cbar_pin_release_condensation.md D5).
    for d in "1234":
        if d in pa and d in pb:
            raise ValueError(
                f"CBAR {eid}: DOF {d} released at both ends (PA={pa}, PB={pb}) leaves "
                f"an internal mechanism; release only bending rotations (e.g. PA=PB=56) "
                f"for a two-force member"
            )
    bulk.cbars[eid] = Cbar(eid=eid, pid=pid, ga=ga, gb=gb,
                           x1=x1, x2=x2, x3=x3, offt=offt, pa=pa, pb=pb)


def _handle_plotel(fields: list[str], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    g1  = to_int(fields[2])
    g2  = to_int(fields[3])
    if eid in bulk.plotels:
        raise ValueError(f"Duplicate PLOTEL EID {eid}")
    bulk.plotels[eid] = Plotel(eid=eid, g1=g1, g2=g2)


def _handle_rbe3(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    eid     = to_int(fields[1])
    # fields[2] is always blank on an RBE3 card
    refgrid = to_int(fields[3])
    refc    = fields[4].strip()

    all_fields = [f.strip() for f in fields[5:] if f.strip()]
    for cont in conts:
        all_fields += [f.strip() for f in cont[1:] if f.strip()]

    wt_gc: list[tuple[float, str, list[int]]] = []
    k = 0
    while k < len(all_fields):
        wt = to_float(all_fields[k]); k += 1
        if k >= len(all_fields):
            break
        c = all_fields[k].strip(); k += 1
        grids: list[int] = []
        while k < len(all_fields):
            f = all_fields[k]
            if '.' in f or 'e' in f.lower() or 'E' in f:
                break  # next WT value (float)
            try:
                grids.append(int(f)); k += 1
            except ValueError:
                k += 1
        wt_gc.append((wt, c, grids))

    if eid in bulk.rbe3s:
        raise ValueError(f"Duplicate RBE3 EID {eid}")
    bulk.rbe3s[eid] = Rbe3(eid=eid, refgrid=refgrid, refc=refc, wt_gc=wt_gc)


def _handle_rbe2(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    gn  = to_int(fields[2])
    cm  = fields[3].strip()
    validate_dof(cm, f"RBE2 {eid}")

    gm: list[int] = []
    for f in fields[4:]:
        if f.strip():
            gm.append(to_int(f))
    for cont in conts:
        for f in cont[1:]:
            if f.strip():
                gm.append(to_int(f))

    if eid in bulk.rbe2s:
        raise ValueError(f"Duplicate RBE2 EID {eid}")
    bulk.rbe2s[eid] = Rbe2(eid=eid, gn=gn, cm=cm, gm=gm)


def _handle_rbar(fields: list[str], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    ga  = to_int(fields[2])
    gb  = to_int(fields[3])
    cna = fields[4].strip() if len(fields) > 4 and fields[4].strip() else "123456"
    cnb = fields[5].strip() if len(fields) > 5 and fields[5].strip() else ""

    if cna != "123456" or cnb not in ("", "0"):
        raise ValueError(
            f"RBAR {eid}: only CNA=123456/CNB=blank supported in Phase 1 "
            f"(got CNA={cna!r}, CNB={cnb!r})"
        )
    _check_distinct_ends("RBAR", eid, ga, gb)
    if eid in bulk.rbars:
        raise ValueError(f"Duplicate RBAR EID {eid}")

    bulk.rbars[eid] = Rbar(eid=eid, ga=ga, gb=gb, cna=cna, cnb=cnb)


def _handle_conm2(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    gid = to_int(fields[2])
    cid = to_int_opt(fields[3]) if len(fields) > 3 else 0
    m   = to_float(fields[4]) if len(fields) > 4 else 0.0
    x1  = to_float(fields[5]) if len(fields) > 5 else 0.0
    x2  = to_float(fields[6]) if len(fields) > 6 else 0.0
    x3  = to_float(fields[7]) if len(fields) > 7 else 0.0

    # Inertia tensor: fields 8-13 in free-field, or continuation line fields 1-6 in fixed-field
    def _gi(n: int) -> float:
        if len(fields) > n and fields[n].strip():
            return to_float(fields[n])
        if cont is not None:
            k = n - 7  # fields[8] → cont[1], ..., fields[13] → cont[6]
            if len(cont) > k:
                return to_float(cont[k])
        return 0.0

    # Own ID space: MSC's HA144A gives CONM2 100 and CBAR 100 the same EID (#57)
    if eid in bulk.conm2s:
        raise ValueError(f"Duplicate CONM2 EID {eid}")
    bulk.conm2s[eid] = Conm2(
        eid=eid, gid=gid, cid=cid, m=m, x1=x1, x2=x2, x3=x3,
        i11=_gi(8), i21=_gi(9), i22=_gi(10),
        i31=_gi(11), i32=_gi(12), i33=_gi(13),
    )


def _handle_massset(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MASSSET — payload / mass case (Step 60).

    ``MASSSET SID LABEL SCALE`` followed by continuation rows of
    ``op-keyword + EIDs``:

        MASSSET  10      FULLFUEL 1.0
        +        ADD     9301    9302
        +        REPLACE 21      9021    22      9022
        +        DELETE  45

    ADD / DELETE rows carry up to 7 CONM2 EIDs; REPLACE rows carry
    (baseline EID, overlay EID) pairs and so must hold an even count.
    """
    sid = to_int(fields[1])
    if sid in bulk.masssets:
        raise ValueError(f"Duplicate MASSSET SID {sid}")
    label = fields[2].strip() if len(fields) > 2 and fields[2].strip() else f"MASSSET {sid}"
    scale = to_float(fields[3]) if len(fields) > 3 and fields[3].strip() else 1.0
    if scale < 0.0:
        raise ValueError(f"MASSSET {sid}: SCALE must be >= 0, got {scale}")

    add: list[int] = []
    replace: list[tuple[int, int]] = []
    delete: list[int] = []
    seen: dict[int, str] = {}   # eid -> op that first named it (duplicate-reference guard)

    for cont in conts:
        entries = [f.strip() for f in cont[1:] if f.strip()]
        if not entries:
            continue
        op = entries[0].upper()
        if op not in ("ADD", "REPLACE", "DELETE"):
            raise ValueError(
                f"MASSSET {sid}: unknown op '{entries[0]}' "
                "(expected ADD, REPLACE, or DELETE)"
            )
        eids = [to_int(f) for f in entries[1:]]
        if not eids:
            raise ValueError(f"MASSSET {sid}: {op} row lists no CONM2 EIDs")
        for eid in eids:
            if eid in seen:
                raise ValueError(
                    f"MASSSET {sid}: CONM2 EID {eid} referenced more than once "
                    f"(already named by {seen[eid]})"
                )
            seen[eid] = op

        if op == "ADD":
            add.extend(eids)
        elif op == "DELETE":
            delete.extend(eids)
        else:
            if len(eids) % 2 != 0:
                raise ValueError(
                    f"MASSSET {sid}: REPLACE takes (baseline EID, overlay EID) pairs — "
                    f"got an odd count ({len(eids)}) on one row"
                )
            replace.extend(zip(eids[0::2], eids[1::2]))

    bulk.masssets[sid] = Massset(
        sid=sid, label=label, scale=scale,
        add=add, replace=replace, delete=delete,
    )


def _handle_spc(fields: list[str], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    g1  = to_int(fields[2])
    c1  = fields[3] if len(fields) > 3 else ""
    validate_dof(c1, f"SPC {sid}")
    d1  = to_float(fields[4]) if len(fields) > 4 else 0.0
    g2  = to_int_or_none(fields[5]) if len(fields) > 5 else None
    c2  = fields[6].strip() if len(fields) > 6 and fields[6].strip() else None
    if c2:
        validate_dof(c2, f"SPC {sid}")
    d2  = to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.spcs:
        bulk.spcs[sid] = []
    bulk.spcs[sid].append(Spc(sid=sid, g1=g1, c1=c1, d1=d1, g2=g2, c2=c2, d2=d2))


def _handle_spc1(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    c   = fields[2].strip()
    validate_dof(c, f"SPC1 {sid}")
    grids = [to_int(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        grids += [to_int(f) for f in cont[1:] if f.strip()]
    if sid not in bulk.spc1s:
        bulk.spc1s[sid] = []
    bulk.spc1s[sid].append(Spc1(sid=sid, c=c, grids=grids))


def _handle_force(fields: list[str], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    gid = to_int(fields[2])
    cid = to_int_opt(fields[3]) if len(fields) > 3 else 0
    f   = to_float(fields[4]) if len(fields) > 4 else 0.0
    n1  = to_float(fields[5]) if len(fields) > 5 else 0.0
    n2  = to_float(fields[6]) if len(fields) > 6 else 0.0
    n3  = to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.forces:
        bulk.forces[sid] = []
    bulk.forces[sid].append(Force(sid=sid, gid=gid, cid=cid, f=f, n1=n1, n2=n2, n3=n3))


def _handle_moment(fields: list[str], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    gid = to_int(fields[2])
    cid = to_int_opt(fields[3]) if len(fields) > 3 else 0
    m   = to_float(fields[4]) if len(fields) > 4 else 0.0
    n1  = to_float(fields[5]) if len(fields) > 5 else 0.0
    n2  = to_float(fields[6]) if len(fields) > 6 else 0.0
    n3  = to_float(fields[7]) if len(fields) > 7 else 0.0
    if sid not in bulk.moments:
        bulk.moments[sid] = []
    bulk.moments[sid].append(Moment(sid=sid, gid=gid, cid=cid, m=m, n1=n1, n2=n2, n3=n3))


def _handle_load(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    if sid in bulk.loads:
        raise ValueError(f"Duplicate LOAD SID {sid}")
    s   = to_float(fields[2])
    raw = list(fields[3:])
    if cont is not None:
        raw += list(cont[1:])
    components = []
    for k in range(0, len(raw) - 1, 2):
        sf, lf = raw[k].strip(), raw[k + 1].strip()
        if sf and lf:
            components.append((to_float(sf), to_int(lf)))
    bulk.loads[sid] = Load(sid=sid, s=s, components=components)


def _handle_pbush(fields: list[str], bulk: BulkData) -> None:
    pid = to_int(fields[1])
    if pid in bulk.pbushs:
        raise ValueError(f"Duplicate PBUSH PID {pid}")
    # Field layout: PBUSH, PID, K, K1, K2, K3, K4, K5, K6
    # fields[2] is the literal "K" keyword; K values start at fields[3]
    if len(fields) > 2 and fields[2].strip().upper() == "B":
        raise ValueError(f"PBUSH {pid}: B (damping) keyword not supported in Phase 2")
    k1 = to_float(fields[3]) if len(fields) > 3 else 0.0
    k2 = to_float(fields[4]) if len(fields) > 4 else 0.0
    k3 = to_float(fields[5]) if len(fields) > 5 else 0.0
    k4 = to_float(fields[6]) if len(fields) > 6 else 0.0
    k5 = to_float(fields[7]) if len(fields) > 7 else 0.0
    k6 = to_float(fields[8]) if len(fields) > 8 else 0.0
    bulk.pbushs[pid] = Pbush(pid=pid, k1=k1, k2=k2, k3=k3, k4=k4, k5=k5, k6=k6)


def _handle_cbush(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    pid = to_int(fields[2])
    ga  = to_int(fields[3])
    gb  = to_int_or_none(fields[4]) if len(fields) > 4 else None
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
        x1 = to_float(cont[1]) if len(cont) > 1 else 0.0
        x2 = to_float(cont[2]) if len(cont) > 2 else 0.0
        x3 = to_float(cont[3]) if len(cont) > 3 else 0.0

    # CBUSH shares the element-ID space; it used to skip this check, so a CBUSH
    # after a CBAR of the same EID was accepted while the reverse order was not (#51)
    _check_unique_eid(bulk, "CBUSH", eid)
    _check_distinct_ends("CBUSH", eid, ga, gb)

    bulk.cbushs[eid] = Cbush(eid=eid, pid=pid, ga=ga, gb=gb, x1=x1, x2=x2, x3=x3)


def _handle_grav(fields: list[str], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    cid = to_int_opt(fields[2]) if len(fields) > 2 else 0
    g   = to_float(fields[3]) if len(fields) > 3 else 0.0
    n1  = to_float(fields[4]) if len(fields) > 4 else 0.0
    n2  = to_float(fields[5]) if len(fields) > 5 else 0.0
    n3  = to_float(fields[6]) if len(fields) > 6 else 0.0
    if cid != 0:
        raise ValueError(f"GRAV {sid}: CID={cid} not supported in Phase 1 (only CID=0)")
    if sid in bulk.gravs:
        raise ValueError(f"Duplicate GRAV SID {sid}")
    bulk.gravs[sid] = Grav(sid=sid, cid=cid, g=g, n1=n1, n2=n2, n3=n3)

def _handle_suport(fields: list[str], bulk: BulkData) -> None:
    """SUPORT card — pairs of GID/DOF starting at fields[1]."""
    i = 1
    while i + 1 < len(fields) and fields[i].strip():
        gid  = to_int(fields[i])
        dofs = fields[i + 1].strip()
        if not dofs:
            raise ValueError(f"SUPORT: blank DOF string for GID {gid}")
        bulk.supports.append(Suport(gid=gid, dofs=dofs))
        i += 2

def _handle_eigrl(fields: list[str], bulk: BulkData) -> None:
    sid  = to_int(fields[1])
    v1   = to_float_or_none(fields[2]) if len(fields) > 2 else None
    v2   = to_float_or_none(fields[3]) if len(fields) > 3 else None
    nd   = to_int_or_none(fields[4]) if len(fields) > 4 else None
    # fields[5–7] are MSGLVL, MAXSET, SHFSCL — not used in phase 1
    norm = fields[8].strip() if len(fields) > 8 and fields[8].strip() else "MASS"
    if sid in bulk.eigrls:
        raise ValueError(f"Duplicate EIGRL SID {sid}")
    bulk.eigrls[sid] = Eigrl(sid=sid, v1=v1, v2=v2, nd=nd, norm=norm)


def _handle_param(fields: list[str], bulk: BulkData) -> None:
    name = fields[1].strip().upper() if len(fields) > 1 else ""
    if name == "WTMASS":
        # WTMASS scales the mass matrix in Nastran; sbeam never converts units (charter §7)
        value = to_float(fields[2]) if len(fields) > 2 else 1.0
        if value != 1.0:
            raise ValueError(
                f"PARAM,WTMASS,{value:g} is not supported: sbeam does not scale mass; "
                "enter mass in the deck's consistent mass unit (charter §7)"
            )
        return
    # Every other PARAM is still ignored, and says so like any unhandled card (#45 class)
    warnings.warn(f"Unknown BDF card 'PARAM,{name}' — skipped", UserWarning, stacklevel=4)


# Dispatch registration (#48): every keyword handled in this module, in one table each.
FIELD_HANDLERS: dict[str, FieldHandler] = {
    "GRID": _handle_grid,
    "MAT1": _handle_mat1,
    "PBUSH": _handle_pbush,
    "PROD": _handle_prod,
    "CROD": _handle_crod,
    "CONROD": _handle_conrod,
    "PLOTEL": _handle_plotel,
    "RBAR": _handle_rbar,
    "SPC": _handle_spc,
    "FORCE": _handle_force,
    "MOMENT": _handle_moment,
    "GRAV": _handle_grav,
    "EIGRL": _handle_eigrl,
    "SUPORT": _handle_suport,
    "PARAM": _handle_param,
}
CONT_HANDLERS: dict[str, ContHandler] = {
    "CORD2R": _handle_cord2r,
    "PBAR": _handle_pbar,
    "CBUSH": _handle_cbush,
    "CBAR": _handle_cbar,
    "CONM2": _handle_conm2,
    "LOAD": _handle_load,
}
MULTI_HANDLERS: dict[str, MultiHandler] = {
    "RBE3": _handle_rbe3,
    "RBE2": _handle_rbe2,
    "MASSSET": _handle_massset,
    "SPC1": _handle_spc1,
}
