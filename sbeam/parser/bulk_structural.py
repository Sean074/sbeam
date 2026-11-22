"""Structural bulk-card handlers: frames, grids, properties, materials, elements,
mass, constraints, static loads and solver parameters (#48)."""
import math
import warnings
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Conrod, Crod, Plotel, Rbe3, Rbe2, Cbush, Rbar
from sbeam.model.property import Pbar, Pbush, Prod
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2, MassCombination, Massset
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
    if ps:
        # "Any of the Integers 1 through 6 with no embedded blanks, or blank" (QRG PDF
        # p.1944).  PS = 7 used to constrain DOF 1 of the next grid (#68)
        validate_dof(ps, f"GRID {gid} PS")
    # SEID was documented "must be blank" but never read, so a superelement grid
    # silently joined the residual structure (#58 sweep); 0 is the residual, as in NASTRAN
    seid = fields[8].strip() if len(fields) > 8 else ""
    if seid and seid != "0":
        raise ValueError(f"GRID {gid}: SEID={seid} not supported; sbeam has no "
                         f"superelements (leave SEID blank or 0)")
    bulk.grids[gid] = Grid(gid=gid, x=x, y=y, z=z, ps=ps, cp=cp, cd=cd)


def _handle_pbar(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
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
    if conts:
        c1, c2, d1, d2, e1, e2, f1, f2 = (to_float(f) for f in conts[0][1:9])
    if len(conts) > 1:
        # K1, K2 (shear area factors, NASTRAN default infinite = no shear flexibility) and
        # I12 (coupled bending) used to be dropped with the line (QRG p.2431; #63)
        k1, k2, i12 = conts[1][1:4]
        if k1.strip() or k2.strip():
            raise ValueError(f"PBAR {pid}: K1/K2 shear factors are not supported "
                             "(Euler-Bernoulli only); leave them blank")
        if i12.strip() and to_float(i12) != 0.0:
            raise ValueError(f"PBAR {pid}: I12 = {i12} (coupled bending) is not supported")
        if any(f.strip() for f in conts[1][4:]):
            raise ValueError(f"PBAR {pid}: fields after I12 on the third line must be blank")
    if len(conts) > 2:
        raise ValueError(f"PBAR {pid}: more than three lines; PBAR has two continuations")

    bulk.pbars[pid] = Pbar(
        pid=pid, mid=mid, A=A, I1=I1, I2=I2, J=J, nsm=nsm,
        c1=c1, c2=c2, d1=d1, d2=d2, e1=e1, e2=e2, f1=f1, f2=f2,
    )


def _handle_mat1(fields: list[str], bulk: BulkData) -> None:
    mid = to_int(fields[1])
    if mid in bulk.mat1s:
        raise ValueError(f"Duplicate MID {mid}")
    # E, G and NU by MSC's blank rules (QRG 2024.1 PDF p.2020-2021, remark 2).  Before
    # #68 a blank E stayed 0.0 (MSC computes it), E and G both blank was accepted, and NU
    # was not derived from E and G.
    def _blank_or(k: int, name: str, low: float, high: float) -> Optional[float]:
        if len(fields) <= k or not fields[k].strip():
            return None
        value = to_float(fields[k])
        if not low < value < high:
            limits = "> 0.0" if high == math.inf else f"between {low:g} and {high:g}"
            raise ValueError(f"MAT1 {mid}: {name}={value:g} must be {limits} or blank "
                             "(QRG p.2020)")
        return value

    E_in = _blank_or(2, "E", 0.0, math.inf)
    G_in = _blank_or(3, "G", 0.0, math.inf)
    nu_in = _blank_or(4, "NU", -1.0, 0.5)
    rho = to_float(fields[5]) if len(fields) > 5 else 0.0
    if E_in is None and G_in is None:
        raise ValueError(f"MAT1 {mid}: E and G may not both be blank (QRG p.2020 remark 2)")
    if nu_in is None and (E_in is None or G_in is None):
        # "If NU and E, or NU and G, are both blank, then both are set to 0.0"
        E, G, nu = E_in or 0.0, G_in or 0.0, 0.0
    elif E_in is None:
        assert G_in is not None and nu_in is not None
        E, G, nu = 2.0 * (1.0 + nu_in) * G_in, G_in, nu_in     # E = 2(1+NU)G
    elif G_in is None:
        assert nu_in is not None
        E, G, nu = E_in, E_in / (2.0 * (1.0 + nu_in)), nu_in
    elif nu_in is None:
        E, G, nu = E_in, G_in, E_in / (2.0 * G_in) - 1.0
    else:
        E, G, nu = E_in, G_in, nu_in
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
    pid = to_int_opt(fields[2], eid)   # "Default = EID" (QRG 2024.1 PDF p.1522)
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
    # "Default = EID unless BAROR entry has nonzero entry in field 3" (QRG 2024.1 PDF
    # p.1360); sbeam has no BAROR.  A blank PID used to fail with int('') (#67)
    pid  = to_int_opt(fields[2], eid)
    ga   = to_int(fields[3])
    gb   = to_int(fields[4])
    # "If an integer is specified in field 6, then G0 is used; if field 6 is blank or
    # real, then X1, X2, X3 is used" (QRG p.1362).  The type of field 6 alone decides:
    # `13 0 0` is G0 = 13, which the X2/X3-blank test of #58 read as the vector (13, 0, 0).
    if len(fields) > 5 and _field_kind(fields[5].strip()) == "int":
        raise ValueError(
            f"CBAR {eid}: field 6 is the integer {fields[5].strip()}, which NASTRAN reads "
            "as the grid G0 (QRG p.1362); the G0 orientation form is not supported. Give "
            "the orientation vector X1, X2, X3 as reals (with a decimal point)")
    x1   = to_float(fields[5]) if len(fields) > 5 else 0.0
    x2   = to_float(fields[6]) if len(fields) > 6 else 0.0
    x3   = to_float(fields[7]) if len(fields) > 7 else 0.0
    offt = fields[8].strip().upper() if len(fields) > 8 and fields[8].strip() else "GGG"
    if offt not in _CBAR_OFFT:
        raise ValueError(
            f"CBAR {eid}: OFFT='{offt}' is not one of {', '.join(sorted(_CBAR_OFFT))} "
            "(QRG p.1363 remark 7)")
    pa   = cont[1] if cont is not None and len(cont) > 1 else ""
    pb   = cont[2] if cont is not None and len(cont) > 2 else ""
    # Offsets W1A W2A W3A W1B W2B W3B (continuation fields 4-9, QRG p.1360-1361) move the
    # bar's ends off its grids; sbeam has no offsets, and dropped them without a message
    if cont is not None:
        for name, value in zip(("W1A", "W2A", "W3A", "W1B", "W2B", "W3B"), cont[3:9]):
            if value.strip() and to_float(value) != 0.0:
                raise ValueError(
                    f"CBAR {eid}: offset {name}={value.strip()} is not supported; sbeam "
                    "bars run grid to grid. Move the grids to the bar's ends, or join each "
                    "end to its grid with an RBAR")

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


# QRG 2024.1 PDF p.1363 remark 7.  First letter: orientation vector in the displacement
# (G) or basic (B) system; second and third: end A / end B offset in the displacement
# (G) or offset (O) system.  Offsets are refused, so only the first letter matters.
_CBAR_OFFT = frozenset({"GGG", "BGG", "GGO", "BGO", "GOG", "BOG", "GOO", "BOO"})


def _handle_plotel(fields: list[str], bulk: BulkData) -> None:
    eid = to_int(fields[1])
    g1  = to_int(fields[2])
    g2  = to_int(fields[3])
    if eid in bulk.plotels:
        raise ValueError(f"Duplicate PLOTEL EID {eid}")
    bulk.plotels[eid] = Plotel(eid=eid, g1=g1, g2=g2)


def _field_kind(token: str) -> str:
    """'int', 'real' or 'other' — the NASTRAN field type (RBE3 tells a WT from a grid ID
    by it)."""
    try:
        int(token)
        return "int"
    except ValueError:
        pass
    try:
        to_float(token)
        return "real"
    except ValueError:
        return "other"


def _rbe3_tokens(fields: list[str], conts: list[list[str]]) -> list[str]:
    """Non-blank fields after REFC, with continuation markers (a non-numeric ``+...``
    in the last field of a line) dropped."""
    tokens: list[str] = []
    for line in [fields[5:], *(cont[1:] for cont in conts)]:
        line = [f.strip() for f in line if f.strip()]
        if line and line[-1].startswith("+") and _field_kind(line[-1]) == "other":
            line.pop()
        tokens += line
    return tokens


def _handle_rbe3(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """RBE3 read strictly by field type, as NASTRAN does (#59): each group is a real WT,
    a DOF string C and at least one grid ID.  Any field that fits nowhere refuses the
    card; nothing is skipped."""
    eid     = to_int(fields[1])
    if len(fields) > 2 and fields[2].strip():
        raise ValueError(f"RBE3 {eid}: field 2 must be blank (got {fields[2].strip()!r})")
    refgrid = to_int(fields[3])
    refc    = fields[4].strip() if len(fields) > 4 else ""
    validate_dof(refc, f"RBE3 {eid} REFC")

    tokens = _rbe3_tokens(fields, conts)
    wt_gc: list[tuple[float, str, list[int]]] = []
    k = 0
    while k < len(tokens):
        tok = tokens[k]
        key = tok.upper()
        if key == "UM":
            raise ValueError(f"RBE3 {eid}: the UM section is not supported; "
                             f"the dependent DOFs must be REFGRID's REFC")
        if key == "ALPHA":
            # "ALPHA", ALPHA, TREF ends the card; both are thermal and sbeam has none
            rest = [t for t in tokens[k + 1:] if t.upper() != "TREF"]
            if len(rest) > 2 or any(_field_kind(t) == "other" for t in rest):
                raise ValueError(f"RBE3 {eid}: cannot read the ALPHA section {tokens[k:]!r}; "
                                 f"it must be the last section: ALPHA, value[, TREF]")
            warnings.warn(f"RBE3 {eid}: ALPHA/TREF ignored (sbeam has no thermal loads)",
                          UserWarning, stacklevel=4)
            break
        group = len(wt_gc) + 1
        kind = _field_kind(tok)
        if kind != "real":
            hint = (" (an integer here would be a grid ID; NASTRAN requires a real WT, "
                    "e.g. 1.0)" if kind == "int" else "")
            raise ValueError(f"RBE3 {eid}: expected weight WT{group}, got {tok!r}{hint}")
        wt = to_float(tok)
        if k + 1 >= len(tokens):
            raise ValueError(f"RBE3 {eid}: weight WT{group} has no DOF string C{group}")
        c = tokens[k + 1]
        validate_dof(c, f"RBE3 {eid} C{group}")
        k += 2
        grids: list[int] = []
        while k < len(tokens) and _field_kind(tokens[k]) == "int":
            grids.append(int(tokens[k]))
            k += 1
        if k < len(tokens) and _field_kind(tokens[k]) == "other" \
                and tokens[k].upper() not in ("UM", "ALPHA"):
            raise ValueError(f"RBE3 {eid}: cannot read {tokens[k]!r} in group {group} "
                             f"(expected a grid ID, a real WT, UM or ALPHA)")
        if not grids:
            raise ValueError(f"RBE3 {eid}: group {group} (WT={tok}, C={c}) has no grids")
        wt_gc.append((wt, c, grids))
    if not wt_gc:
        raise ValueError(f"RBE3 {eid}: no independent grids (WT, C, G...) given")

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
    cma = fields[6].strip() if len(fields) > 6 else ""
    cmb = fields[7].strip() if len(fields) > 7 else ""

    if cna != "123456" or cnb not in ("", "0"):
        raise ValueError(
            f"RBAR {eid}: only CNA=123456/CNB=blank supported in Phase 1 "
            f"(got CNA={cna!r}, CNB={cnb!r})"
        )
    # sbeam makes all six DOFs of GB dependent.  That is NASTRAN's rule only "if both CMA
    # and CMB are zero or blank" (QRG 2024.1 PDF p.2692 remark 4), or when CMB lists all
    # six; CMB = 123 makes only those three dependent and was ignored (#68)
    if cma not in ("", "0") or cmb not in ("", "0", "123456"):
        raise ValueError(
            f"RBAR {eid}: CMA={cma or 'blank'}, CMB={cmb or 'blank'} selects a partial set of "
            "dependent DOFs, which is not supported; sbeam makes all six DOFs of GB "
            "dependent (leave CMA and CMB blank, or use an RBE2 with CM for a partial set)"
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

    # Inertia tensor: continuation fields 2-7.  A long free-field line arrives here
    # already split (field 9 of the parent is blank in NASTRAN; #64)
    def _gi(k: int) -> float:
        return to_float(cont[k]) if cont is not None else 0.0

    if fields[8].strip():
        # sbeam once read I11 here; NASTRAN leaves field 9 blank (QRG p.1449), so a
        # one-line free-field CONM2 needs ', ,' before I11 (#64)
        raise ValueError(f"CONM2 {eid}: field 9 must be blank; I11 starts the continuation")
    # Own ID space: MSC's HA144A gives CONM2 100 and CBAR 100 the same EID (#57)
    if eid in bulk.conm2s:
        raise ValueError(f"Duplicate CONM2 EID {eid}")
    bulk.conm2s[eid] = Conm2(
        eid=eid, gid=gid, cid=cid, m=m, x1=x1, x2=x2, x3=x3,
        i11=_gi(1), i21=_gi(2), i22=_gi(3),
        i31=_gi(4), i32=_gi(5), i33=_gi(6),
    )


def _handle_mass_combination(fields: list[str], conts: list[list[str]],
                             bulk: BulkData) -> None:
    """MSC MASSSET, a mass combination (MSC Nastran 2024.1 QRG PDF p.2018; #102).

    ``MASSSET ID S0 S1 ID1 S2 ID2 S3 ID3`` / ``S4 ID4 ...``: ``M_ID = S0 · Σ Si·M_IDi``,
    ``IDi = 0`` the base mass and ``IDi > 0`` a BEGIN MASSID section.  S0 and Si are
    "Real >= 0.0; Default = 0.0", IDi "Integer > 0; No Default" (0 names the base, per
    the formula's i = 0).  The IDs are checked against the sections in ``bulk_xref``.
    """
    sid = to_int(fields[1])
    if sid <= 0:
        raise ValueError(f"MASSSET {sid}: ID must be an integer > 0 (QRG p.2018)")
    if fields[2].strip() and _field_kind(fields[2].strip()) == "other":
        raise ValueError(
            f"MASSSET {sid}: S0={fields[2].strip()} is not a number. MASSSET is MSC's mass "
            "combination (ID S0 S1 ID1 ..., QRG p.2018); sbeam's payload card "
            "(MASSSET SID LABEL SCALE before #78) is MASSCASE: rename the card")
    s0 = to_float(fields[2]) if fields[2].strip() else 0.0
    rest = [f.strip() for f in fields[3:]] + [f.strip() for c in conts for f in c[1:]]
    while rest and not rest[-1]:
        rest.pop()
    if len(rest) % 2:
        rest.append("")
    terms: list[tuple[float, int]] = []
    for k in range(0, len(rest), 2):
        s_txt, id_txt = rest[k], rest[k + 1]
        if not s_txt and not id_txt:
            continue
        if not id_txt:
            raise ValueError(f"MASSSET {sid}: S{k // 2 + 1}={s_txt} has no ID "
                             "(IDi has no default, QRG p.2018)")
        terms.append((to_float(s_txt) if s_txt else 0.0, to_int(id_txt)))
    if s0 < 0.0 or any(si < 0.0 for si, _ in terms):
        raise ValueError(f"MASSSET {sid}: scale factors must be >= 0.0 (QRG p.2018)")
    if not terms:
        raise ValueError(f"MASSSET {sid}: no mass case is combined")
    if sid in bulk.mass_combinations:
        raise ValueError(f"Duplicate MASSSET ID {sid}")
    bulk.mass_combinations[sid] = MassCombination(sid=sid, s0=s0, terms=terms)


def _handle_massset(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MASSCASE — payload / mass case (Step 60).

    ``MASSCASE SID LABEL SCALE`` followed by continuation rows of
    ``op-keyword + EIDs``:

        MASSCASE  10      FULLFUEL 1.0
        +        ADD     9301    9302
        +        REPLACE 21      9021    22      9022
        +        DELETE  45

    ADD / DELETE rows carry up to 7 CONM2 EIDs; REPLACE rows carry
    (baseline EID, overlay EID) pairs and so must hold an even count.
    """
    sid = to_int(fields[1])
    if sid in bulk.masssets:
        raise ValueError(f"Duplicate MASSCASE SID {sid}")
    label = fields[2].strip() if len(fields) > 2 and fields[2].strip() else f"MASSCASE {sid}"
    scale = to_float(fields[3]) if len(fields) > 3 and fields[3].strip() else 1.0
    if scale < 0.0:
        raise ValueError(f"MASSCASE {sid}: SCALE must be >= 0, got {scale}")

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
                f"MASSCASE {sid}: unknown op '{entries[0]}' "
                "(expected ADD, REPLACE, or DELETE)"
            )
        eids = [to_int(f) for f in entries[1:]]
        if not eids:
            raise ValueError(f"MASSCASE {sid}: {op} row lists no CONM2 EIDs")
        for eid in eids:
            if eid in seen:
                raise ValueError(
                    f"MASSCASE {sid}: CONM2 EID {eid} referenced more than once "
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
                    f"MASSCASE {sid}: REPLACE takes (baseline EID, overlay EID) pairs — "
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
    # No solver applies an enforced displacement.  SOL 101 and 103 refused it at run
    # time; SOL 144 and MANVR took D = 0 without a message (#68)
    for gid, d in ((g1, d1), (g2, d2)):
        if d != 0.0:
            raise ValueError(
                f"SPC {sid}: enforced displacement D={d:g} on grid {gid} is not supported; "
                "sbeam constraints hold the DOF at zero")
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


def _handle_load(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    if sid in bulk.loads:
        raise ValueError(f"Duplicate LOAD SID {sid}")
    s   = to_float(fields[2])
    # Any number of continuations (QRG p.2008); only the first was read before #63
    raw = list(fields[3:])
    for cont in conts:
        raw += list(cont[1:])
    components = []
    for k in range(0, len(raw) - 1, 2):
        sf, lf = raw[k].strip(), raw[k + 1].strip()
        if bool(sf) != bool(lf):
            raise ValueError(
                f"LOAD {sid}: pair {k // 2 + 1} has S='{sf}' and L='{lf}'; give both the "
                "scale factor and the load set ID")
        if sf and lf:
            lid = to_int(lf)
            # "Load set IDs (Li) must be unique" (QRG 2024.1 PDF p.2008 remark 2); a
            # repeated Li used to be summed twice (#68)
            if any(lid == other for _, other in components):
                raise ValueError(
                    f"LOAD {sid}: load set {lid} is listed twice; the Li must be unique "
                    "(QRG p.2008 remark 2)")
            components.append((to_float(sf), lid))
    bulk.loads[sid] = Load(sid=sid, s=s, components=components)


#: PBUSH flag lines sbeam cannot honour: any non-zero value refuses the card (#63)
_PBUSH_UNSUPPORTED = {"B": "viscous damping", "GE": "structural damping",
                      "M": "lumped mass (use a CONM2)", "T": "thermal properties"}


def _handle_pbush(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """PBUSH — flag lines K, B, GE, RCV, M, T in any order (QRG p.2493–2494, remark 6).

    The flag is field 3 of every line and its values fields 4–9.  K is read; RCV (stress
    and strain recovery) is output only and ignored; B, GE, M and T are refused unless all
    their values are blank or zero.  Before #63 fields 4–9 of the first line were read as
    K whatever the flag (``PBUSH 1 M 5.`` gave K1 = 5) and every continuation was dropped.
    """
    pid = to_int(fields[1])
    if pid in bulk.pbushs:
        raise ValueError(f"Duplicate PBUSH PID {pid}")
    k = [0.0] * 6
    seen: set[str] = set()
    for row in [fields, *conts]:
        flag = row[2].strip().upper()
        values = row[3:9]
        if not flag:
            if any(f.strip() for f in row[1:]):
                raise ValueError(f"PBUSH {pid}: a line with values has no K/B/GE/RCV/M/T flag")
            continue
        if flag in seen:
            raise ValueError(f"PBUSH {pid}: flag {flag} given twice")
        seen.add(flag)
        if flag == "K":
            k = [to_float(f) for f in values]
        elif flag in _PBUSH_UNSUPPORTED:
            if any(f.strip() and to_float(f) != 0.0 for f in values):
                raise ValueError(f"PBUSH {pid}: {flag} ({_PBUSH_UNSUPPORTED[flag]}) is "
                                 "not supported; only K is honoured")
        elif flag != "RCV":
            raise ValueError(f"PBUSH {pid}: unknown flag '{flag}' (K, B, GE, RCV, M or T)")
    bulk.pbushs[pid] = Pbush(pid=pid, k1=k[0], k2=k[1], k3=k[2], k4=k[3], k5=k[4], k6=k[5])


def _handle_cbush(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    """CBUSH in MSC's layout (MSC Nastran 2024.1 QRG PDF p.1378-1380; #62).

    ``CBUSH EID PID GA GB GO/X1 X2 X3 CID`` / ``S OCID S1 S2 S3``.  Until #62 sbeam read
    its own layout: field 7 as CID, the orientation vector from the continuation, and
    fields 6, 8 and 9 not at all, so a NASTRAN card's GO and CID were dropped.
    """
    eid = to_int(fields[1])
    pid = to_int_opt(fields[2], eid)             # "Default = EID" (p.1378)
    ga  = to_int(fields[3])
    gb  = to_int_or_none(fields[4]) or None      # blank or 0: grounded
    orient = [f.strip() for f in fields[5:8]]
    # The type of field 6 decides GO or X1, as on the CBAR
    if _field_kind(orient[0]) == "int":
        raise ValueError(
            f"CBUSH {eid}: field 6 is the integer {orient[0]}, which NASTRAN reads as the "
            "grid GO (QRG p.1378); the GO orientation form is not supported. Give the "
            "orientation vector X1, X2, X3 as reals (with a decimal point), or a CID")
    x1, x2, x3 = (to_float(f) if f else 0.0 for f in orient)
    cid: Optional[int] = None
    cid_s = fields[8].strip()
    if cid_s:
        if _field_kind(cid_s) != "int" or int(cid_s) < 0:
            raise ValueError(f"CBUSH {eid}: CID={cid_s} must be an integer >= 0 or blank")
        cid = int(cid_s)

    s = 0.5                                       # "Default = 0.5" (p.1378)
    if cont is not None:
        old = ("sbeam's layout before #62 put the orientation vector X1 X2 X3 on this "
               "line; it now goes in fields 6-8 of the first line, as in NASTRAN")
        s_loc, ocid = cont[1].strip(), cont[2].strip()
        if s_loc:
            s = to_float(s_loc)       # the spring point is GA + S·(GB − GA) (Figure 9-20)
        if ocid and (_field_kind(ocid) != "int" or int(ocid) != -1):
            raise ValueError(
                f"CBUSH {eid}: OCID={ocid} is not supported; sbeam places the spring on "
                f"the line GA-GB at S (leave OCID blank or -1). Note: {old}")
        # S1-S3 are ignored when OCID is -1 or blank (p.1379 remark 9), as here

    # CBUSH shares the element-ID space; it used to skip this check, so a CBUSH
    # after a CBAR of the same EID was accepted while the reverse order was not (#51)
    _check_unique_eid(bulk, "CBUSH", eid)
    _check_distinct_ends("CBUSH", eid, ga, gb)

    bulk.cbushs[eid] = Cbush(eid=eid, pid=pid, ga=ga, gb=gb, x1=x1, x2=x2, x3=x3, cid=cid,
                             s=s)


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
    # Up to four ID/C pairs (QRG 2024.1 PDF p.2870).  The read used to stop at the first
    # blank ID, dropping any pair after it, and C was not checked: C = 0 or 7 indexed a
    # DOF of the neighbouring grid (#68)
    pairs = [(fields[i].strip(), fields[i + 1].strip()) for i in range(1, 9, 2)]
    while pairs and pairs[-1] == ("", ""):
        pairs.pop()
    for k, (gid_s, dofs) in enumerate(pairs):
        if not gid_s:
            raise ValueError(
                "SUPORT: blank ID in pair "
                f"{k + 1} with data after it ({', '.join(g for g, _ in pairs[k + 1:] if g)}); "
                "remove the blank fields")
        gid = to_int(gid_s)
        if not dofs:
            raise ValueError(f"SUPORT: blank DOF string for GID {gid}")
        validate_dof(dofs, f"SUPORT grid {gid}")
        bulk.supports.append(Suport(gid=gid, dofs=dofs))

def _handle_eigrl(fields: list[str], bulk: BulkData) -> None:
    """EIGRL: sbeam finds the lowest ND modes (MSC Nastran 2024.1 QRG PDF p.1801-1803).

    MSC selects roots from V1, V2 and ND together (p.1802, Table 9-13).  sbeam has only
    the "blank, blank, ND" row, so the other rows are refused: until #70 V1/V2 were
    warned and not applied, and a blank ND returned every mode where MSC returns the
    lowest root.  MSGLVL, MAXSET and SHFSCL (fields 6-8) are diagnostic and
    performance settings and are ignored.
    """
    sid  = to_int(fields[1])
    v1   = to_float_or_none(fields[2]) if len(fields) > 2 else None
    v2   = to_float_or_none(fields[3]) if len(fields) > 3 else None
    nd   = to_int_or_none(fields[4]) if len(fields) > 4 else None
    norm = fields[8].strip().upper() if len(fields) > 8 and fields[8].strip() else "MASS"
    for name, value in (("V1", v1), ("V2", v2)):
        if value is not None:
            raise ValueError(
                f"EIGRL {sid}: {name}={value:g} is not supported; sbeam returns the lowest "
                "ND modes and does not select by frequency range (QRG p.1802, Table "
                f"9-13). Leave {name} blank and set ND")
    if nd is None:
        raise ValueError(
            f"EIGRL {sid}: ND is blank. NASTRAN then returns the lowest root only (QRG "
            "p.1802, Table 9-13); give the number of modes wanted in ND")
    if nd < 1:
        raise ValueError(f"EIGRL {sid}: ND={nd} must be > 0 (QRG p.1801)")
    if norm not in ("MASS", "MAX"):
        raise ValueError(f"EIGRL {sid}: NORM='{norm}' must be MASS or MAX (QRG p.1801)")
    if sid in bulk.eigrls:
        raise ValueError(f"Duplicate EIGRL SID {sid}")
    bulk.eigrls[sid] = Eigrl(sid=sid, v1=v1, v2=v2, nd=nd, norm=norm)


def _handle_param(fields: list[str], bulk: BulkData) -> None:
    grdpnt = check_param(fields)
    if grdpnt is not None:
        bulk.grdpnt = grdpnt


def check_param(fields: list[str]) -> Optional[int]:
    """Refuse or warn about one PARAM; return GRDPNT's value when it is GRDPNT.

    Shared by the bulk card and the case-control PARAM command (#80), so both
    places apply the same rules.  GRDPNT is the only PARAM that is stored: it asks
    for the grid point weight generator printout (QRG p.885; #90).
    """
    name = fields[1].strip().upper() if len(fields) > 1 else ""
    if name == "GRDPNT":
        # -1 (default) suppresses the printout; 0 or an undefined grid is the basic origin
        return to_int(fields[2]) if len(fields) > 2 and fields[2].strip() else -1
    if name == "WTMASS":
        # WTMASS scales the mass matrix in Nastran; sbeam never converts units (charter §7)
        value = to_float(fields[2]) if fields[2].strip() else 1.0
        if value != 1.0:
            raise ValueError(
                f"PARAM,WTMASS,{value:g} is not supported: sbeam does not scale mass; "
                "enter mass in the deck's consistent mass unit (charter §7)"
            )
        return
    if name == "AUNITS":
        # AUNITS (MSC) makes TRIM URDD* read in g; ignored, URDD3 = 1.0 would trim at
        # 1.0 model-unit/s² instead of 1 g (#55; same charter §7 rule as WTMASS)
        value = to_float(fields[2]) if fields[2].strip() else 1.0
        if value != 1.0:
            raise ValueError(
                f"PARAM,AUNITS,{value:g} is not supported: sbeam does not convert "
                "accelerations; enter URDD* in the deck's consistent units (charter §7)"
            )
        return
    if name == "COUPMASS":
        # NASTRAN's default (-1) and any value <= 0 ask for lumped mass; sbeam always
        # assembles the consistent mass matrix, which is what a positive value asks for (#55)
        value = to_int(fields[2]) if len(fields) > 2 and fields[2].strip() else -1
        if value <= 0:
            raise ValueError(
                f"PARAM,COUPMASS,{value} asks for lumped mass; sbeam always uses the "
                "consistent mass matrix (remove the PARAM, or set it to 1)"
            )
        return
    value_s = fields[2].strip() if len(fields) > 2 else ""
    if name in _REFUSED_PARAMS:
        default, what = _REFUSED_PARAMS[name]
        try:
            value = to_float(value_s) if value_s else default
        except ValueError:
            value = math.nan                      # not a number: not the default either
        if value != default:
            raise ValueError(
                f"PARAM,{name},{value_s} is not supported: {what}. sbeam would run "
                "without it and give a different answer from NASTRAN; remove the PARAM "
                "if the model does not need it")
        return
    if name in _IGNORED_PARAMS:
        warnings.warn(f"BDF card 'PARAM,{name}' ignored ({_IGNORED_PARAMS[name]})",
                      UserWarning, stacklevel=5)
        return
    # Any other PARAM is skipped and says so: tool-written decks carry many output and
    # solution-control PARAMs, so a PARAM is refused only when listed above
    warnings.warn(f"Unknown BDF card 'PARAM,{name}' — skipped", UserWarning, stacklevel=5)


# PARAMs that change NASTRAN's answer and that sbeam has no counterpart for (#69): any
# value but the default is refused.  name -> (NASTRAN default, what it asks for).  Page
# numbers are PDF pages of the MSC Nastran 2024.1 Quick Reference Guide, Parameters.
_REFUSED_PARAMS: dict[str, tuple[float, str]] = {
    "INREL": (0.0, "INREL = -1, -2 or -4 requests inertia relief in static analysis "
                   "(QRG p.888), and sbeam's SOL 101 has none"),
    "G": (0.0, "G is the uniform structural damping coefficient (QRG p.884), and sbeam "
               "has no structural damping"),
    "W3": (0.0, "W3 converts structural damping to viscous damping in transient analysis "
                "(QRG p.956), and sbeam has no structural damping"),
    "W4": (0.0, "W4 converts element structural damping to viscous damping in transient "
                "analysis (QRG p.956), and sbeam has no structural damping"),
    "LMODES": (0.0, "LMODES is the number of lowest modes kept in a modal formulation "
                    "(QRG p.895); sbeam takes the mode count from EIGRL ND"),
}

# PARAMs that change no result sbeam computes: accepted with a warning that names why.
_IGNORED_PARAMS: dict[str, str] = {
    "POST": "post-processor output files, QRG p.922; sbeam writes its own f06, CSV and BDF",
    "PRTMAXIM": "printout of maximum loads and displacements, QRG p.929",
    "AUTOSPC": "automatic constraint of singular DOFs, QRG p.850; sbeam has none and "
               "reports a singular stiffness",
    "MAXRATIO": "singularity threshold of the stiffness factor, QRG p.897; sbeam uses its "
                "own conditioning check",
    "BAILOUT": "continue past a near-singular matrix, QRG p.851 and p.897",
}


# Dispatch registration (#48): every keyword handled in this module, in one table each.
FIELD_HANDLERS: dict[str, FieldHandler] = {
    "GRID": _handle_grid,
    "MAT1": _handle_mat1,
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
    "CBUSH": _handle_cbush,
    "CBAR": _handle_cbar,
    "CONM2": _handle_conm2,
}
MULTI_HANDLERS: dict[str, MultiHandler] = {
    "PBAR": _handle_pbar,
    "PBUSH": _handle_pbush,
    "LOAD": _handle_load,
    "RBE3": _handle_rbe3,
    "RBE2": _handle_rbe2,
    "MASSCASE": _handle_massset,
    "MASSSET": _handle_mass_combination,
    "SPC1": _handle_spc1,
}
