"""Aerodynamic bulk-card handlers: reference geometry, panels, corrections, splines,
box lists and monitor points/sections (#48)."""
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import (
    Aeros, Caero1, Paero1, Pstrip, Stripk, Aefact, W2gj, Wkk, Aecorr, Chordcp, Set1,
    Spline2, Attach, Spline0, Aelist, Aecomp, Monpnt1, Monsect,
)
from sbeam.parser.bulk_fields import FieldHandler, ContHandler, MultiHandler, to_float, to_int, to_int_opt, expand_int_list_with_thru, list_fields, refuse_after


def _handle_aeros(fields: list[str], bulk: BulkData) -> None:
    if bulk.aeros is not None:
        raise ValueError("Duplicate AEROS card")
    acsid = to_int_opt(fields[1]) if len(fields) > 1 else 0
    rcsid = to_int_opt(fields[2]) if len(fields) > 2 else 0
    cref  = to_float(fields[3])   if len(fields) > 3 else 0.0
    bref  = to_float(fields[4])   if len(fields) > 4 else 0.0
    sref  = to_float(fields[5])   if len(fields) > 5 else 0.0
    symxz = to_int_opt(fields[6]) if len(fields) > 6 else 0
    symxy = to_int_opt(fields[7]) if len(fields) > 7 else 0
    # MSC's AEROS ends at SYMXY (QRG 2024.1 PDF p.1151).  Field 9 was an sbeam-only
    # MACH until #87; the Mach is TRIM's (or DIVERG's), as in MSC.
    if len(fields) > 8 and fields[8].strip():
        raise ValueError(
            f"AEROS: field 9 ({fields[8].strip()!r}) must be blank — MSC's AEROS ends at "
            "SYMXY (QRG p.1151). sbeam read an sbeam-only MACH there until v0.4.1 (#87); "
            "give the Mach on the TRIM card (or the DIVERG Mach list) instead")
    bulk.aeros = Aeros(
        acsid=acsid, rcsid=rcsid, cref=cref, bref=bref,
        sref=sref, symxz=symxz, symxy=symxy,
    )


def _handle_aefact(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    if sid in bulk.aefacts:
        raise ValueError(f"Duplicate AEFACT SID {sid}")
    data = [to_float(f) for f in list_fields(
        fields[2:], conts, f"AEFACT {sid}",
        "embedded blank fields are not allowed (QRG p.1141 remark 2)")]
    bulk.aefacts[sid] = Aefact(sid=sid, data=data)


def _handle_w2gj(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid       = to_int(fields[1])
    caero_eid = to_int(fields[2])
    if sid in bulk.w2gjs:
        raise ValueError(f"Duplicate W2GJ SID {sid}")
    data = [to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        data += [to_float(f) for f in cont[1:] if f.strip()]
    bulk.w2gjs[sid] = W2gj(sid=sid, caero_eid=caero_eid, data=data)


def _handle_wkk(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid       = to_int(fields[1])
    caero_eid = to_int(fields[2])
    if sid in bulk.wkks:
        raise ValueError(f"Duplicate WKK SID {sid}")
    data = [to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        data += [to_float(f) for f in cont[1:] if f.strip()]
    bulk.wkks[sid] = Wkk(sid=sid, caero_eid=caero_eid, data=data)


def _handle_aecorr(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid       = to_int(fields[1])
    method    = fields[2].strip().upper() if len(fields) > 2 else ""
    caero_eid = to_int(fields[3]) if len(fields) > 3 else 0
    if method == "WT1":
        # DEF-R7 (release boundary): WT1 was deprecated by DEF-H2/H3 (2026-07-31)
        # and is now removed — it achieved f_target/beta^2 instead of f_target at
        # Mach > 0 (DEF-H2), and on multi-CAERO1 decks it rescaled strips on every
        # surface sharing an i_span index (DEF-H3).
        raise ValueError(
            f"AECORR {sid}: METHOD WT1 has been removed — it produced wrong numbers "
            "(f_target/beta^2 at Mach > 0, and strip aliasing across CAERO1s). Use "
            "METHOD WT2 or the section-correction path instead."
        )
    if method != "WT2":
        raise ValueError(f"AECORR {sid}: METHOD must be WT2, got '{method}'")
    if sid in bulk.aecorrs:
        raise ValueError(f"Duplicate AECORR SID {sid}")
    # MACH (field 5, #72): the Mach the target was built at.  It used to be absent, so the
    # target was re-ratioed against the reference at each TRIM Mach.
    mach_s = fields[4].strip() if len(fields) > 4 else ""
    if not mach_s:
        raise ValueError(
            f"AECORR {sid}: MACH (field 5) is blank; give the Mach the WT2 target was "
            "built at. Before #72 the targets started in field 5: insert the build Mach "
            "there and shift the targets one field right")
    mach = to_float(mach_s)
    if not 0.0 <= mach < 1.0:
        raise ValueError(f"AECORR {sid}: MACH={mach_s} must be in [0, 1)")
    target = [to_float(f) for f in fields[5:] if f.strip()]
    for cont in conts:
        target += [to_float(f) for f in cont[1:] if f.strip()]
    bulk.aecorrs[sid] = Aecorr(sid=sid, method=method, caero_eid=caero_eid, mach=mach,
                               target=target)


def _handle_chordcp(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """CPINJ, SID, CAERO_EID, ALPHREF, [MACH] / +, CP1, CP2, ... (row-major).

    ALPHREF (degrees, REQUIRED) is the reference angle of attack the injected
    Cp distribution was measured at; stored in radians on the dataclass.
    """
    import math
    sid       = to_int(fields[1])
    caero_eid = to_int(fields[2])
    if sid in bulk.chordcps:
        raise ValueError(f"Duplicate CPINJ SID {sid}")
    alphref_field = fields[3].strip() if len(fields) > 3 else ""
    if not alphref_field:
        raise ValueError(
            f"CPINJ {sid}: ALPHREF (reference angle of attack, degrees) is required"
        )
    alpha_ref = math.radians(to_float(alphref_field))
    mach = to_float(fields[4]) if len(fields) > 4 and fields[4].strip() else 0.0
    data = [to_float(f) for f in fields[5:] if f.strip()]
    for cont in conts:
        data += [to_float(f) for f in cont[1:] if f.strip()]
    if not data:
        raise ValueError(f"CPINJ {sid}: no Cp data fields found")
    bulk.chordcps[sid] = Chordcp(
        sid=sid, caero_eid=caero_eid, alpha_ref=alpha_ref, mach=mach, data=data
    )


def _handle_paero1(fields: list[str], bulk: BulkData) -> None:
    pid = to_int(fields[1])
    if pid in bulk.paero1s:
        raise ValueError(f"Duplicate PAERO1 PID {pid}")
    bulk.paero1s[pid] = Paero1(pid=pid)


def _handle_pstrip(fields: list[str], bulk: BulkData) -> None:
    """PSTRIP, pid, [slope0] — decoupled strip body-panel property."""
    pid = to_int(fields[1])
    if pid in bulk.pstrips:
        raise ValueError(f"Duplicate PSTRIP PID {pid}")
    slope_field = fields[2].strip() if len(fields) > 2 else ""
    if slope_field:
        bulk.pstrips[pid] = Pstrip(pid=pid, slope0=to_float(slope_field))
    else:
        bulk.pstrips[pid] = Pstrip(pid=pid)


def _handle_stripk(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """STRIPK, sid, caero, s1, s2, … — per-box strip lift-curve slopes."""
    sid       = to_int(fields[1])
    caero_eid = to_int(fields[2])
    if sid in bulk.stripks:
        raise ValueError(f"Duplicate STRIPK SID {sid}")
    data = [to_float(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        data += [to_float(f) for f in cont[1:] if f.strip()]
    bulk.stripks[sid] = Stripk(sid=sid, caero_eid=caero_eid, data=data)


def _handle_caero1(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    eid    = to_int(fields[1])
    pid    = to_int(fields[2])
    cp     = to_int_opt(fields[3]) if len(fields) > 3 else 0
    nspan  = to_int_opt(fields[4]) if len(fields) > 4 else 0
    nchord = to_int_opt(fields[5]) if len(fields) > 5 else 0
    lspan  = to_int_opt(fields[6]) if len(fields) > 6 else 0
    lchord = to_int_opt(fields[7]) if len(fields) > 7 else 0
    igid   = to_int_opt(fields[8]) if len(fields) > 8 else 0

    if cont is None:
        raise ValueError(f"CAERO1 {eid}: continuation line required (P1/X12/P4/X43 missing)")

    x1  = to_float(cont[1]) if len(cont) > 1 else 0.0
    y1  = to_float(cont[2]) if len(cont) > 2 else 0.0
    z1  = to_float(cont[3]) if len(cont) > 3 else 0.0
    x12 = to_float(cont[4]) if len(cont) > 4 else 0.0
    x4  = to_float(cont[5]) if len(cont) > 5 else 0.0
    y4  = to_float(cont[6]) if len(cont) > 6 else 0.0
    z4  = to_float(cont[7]) if len(cont) > 7 else 0.0
    x43 = to_float(cont[8]) if len(cont) > 8 else 0.0

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


def _handle_set1(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid   = to_int(fields[1])
    grids = [to_int(f) for f in fields[2:] if f.strip()]
    for cont in conts:
        grids += [to_int(f) for f in cont[1:] if f.strip()]
    if sid in bulk.set1s:
        raise ValueError(f"Duplicate SET1 SID {sid}")
    bulk.set1s[sid] = Set1(sid=sid, grids=grids)


def _handle_spline2(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    eid   = to_int(fields[1])
    caero = to_int(fields[2])
    id1   = to_int(fields[3])
    id2   = to_int(fields[4])
    setg  = to_int(fields[5])
    dz    = to_float(fields[6]) if len(fields) > 6 and fields[6].strip() else 0.0
    dtor  = to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 1.0
    cid   = to_int_opt(fields[8]) if len(fields) > 8 else 0
    dthx  = 0.0
    dthy  = 0.0
    usage = "BOTH"
    if cont is not None:
        dthx  = to_float(cont[1]) if len(cont) > 1 and cont[1].strip() else 0.0
        dthy  = to_float(cont[2]) if len(cont) > 2 and cont[2].strip() else 0.0
        if cont[3].strip():
            raise ValueError(
                f"SPLINE2 {eid}: field 4 of the continuation holds '{cont[3].strip()}'; "
                "that field is blank in NASTRAN's layout (DTHX, DTHY, blank, USAGE; QRG "
                "2024.1 PDF p.2849)")
        usage = cont[4].strip().upper() if len(cont) > 4 and cont[4].strip() else "BOTH"
    # MSC Nastran 2024.1 QRG PDF p.2849: "DZ ... (Real >= 0.0)", "DTOR ... (Real > 0.0)".
    # The spline builder used to replace an out-of-range value with a warning (#75)
    if dz < 0.0:
        raise ValueError(f"SPLINE2 {eid}: DZ={dz:g} must be >= 0.0 (QRG p.2849)")
    if dtor <= 0.0:
        raise ValueError(f"SPLINE2 {eid}: DTOR={dtor:g} must be > 0.0 (QRG p.2849)")
    # USAGE = FORCE or DISP puts the spline in only one of the two transforms (QRG
    # p.2848 remark 5, p.2850 remark 9).  sbeam uses every spline for both, so either
    # would be solved as BOTH; any other word is not a NASTRAN value
    if usage in ("FORCE", "DISP"):
        raise ValueError(
            f"SPLINE2 {eid}: USAGE={usage} is not supported; sbeam uses every spline for "
            "both the force and the displacement transform (USAGE=BOTH). A force-only "
            "surface can be carried with LOADINJ")
    if usage != "BOTH":
        raise ValueError(
            f"SPLINE2 {eid}: USAGE='{usage}' must be BOTH or blank (NASTRAN also has FORCE "
            "and DISP, which sbeam does not support; QRG p.2850 remark 9)")
    if eid in bulk.spline2s:
        raise ValueError(f"Duplicate SPLINE2 EID {eid}")
    bulk.spline2s[eid] = Spline2(
        eid=eid, caero=caero, id1=id1, id2=id2, setg=setg,
        dz=dz, dtor=dtor, cid=cid, dthx=dthx, dthy=dthy, usage=usage,
    )


def _handle_attach(fields: list[str], bulk: BulkData) -> None:
    eid   = to_int(fields[1])
    caero = to_int(fields[2])
    id1   = to_int(fields[3])
    id2   = to_int(fields[4])
    grid  = to_int(fields[5])
    cid   = to_int_opt(fields[6]) if len(fields) > 6 else 0
    refuse_after(fields, 7, f"BODYATT {eid}")
    if eid in bulk.attaches:
        raise ValueError(f"Duplicate BODYATT EID {eid}")
    bulk.attaches[eid] = Attach(eid=eid, caero=caero, id1=id1, id2=id2, grid=grid, cid=cid)


def _handle_spline0(fields: list[str], bulk: BulkData) -> None:
    eid   = to_int(fields[1])
    caero = to_int(fields[2])
    id1   = to_int(fields[3])
    id2   = to_int(fields[4])
    grid  = to_int_opt(fields[5]) if len(fields) > 5 else 0
    refuse_after(fields, 6, f"LOADINJ {eid}")
    if eid in bulk.spline0s:
        raise ValueError(f"Duplicate LOADINJ EID {eid}")
    bulk.spline0s[eid] = Spline0(eid=eid, caero=caero, id1=id1, id2=id2, grid=grid)


def _handle_spline1(fields: list[str], bulk: BulkData) -> None:
    raise NotImplementedError(
        "SPLINE1 (Harder–Desmarais infinite-plate spline) is not yet implemented; "
        "use SPLINE2 or BODYATT instead"
    )

def _handle_aelist(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid    = to_int(fields[1])
    tokens = list_fields(fields[2:], conts, f"AELIST {sid}",
                         "intervening blank fields are not allowed (QRG p.1145 remark 3)")
    elements = expand_int_list_with_thru(tokens)
    if sid in bulk.aelists:
        raise ValueError(f"Duplicate AELIST SID {sid}")
    bulk.aelists[sid] = Aelist(sid=sid, elements=elements)

def _handle_aecomp(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
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
    list_ids = [to_int(f) for f in fields[3:] if f.strip()]
    for cont in conts:
        list_ids += [to_int(f) for f in cont[1:] if f.strip()]
    if name in bulk.aecomps:
        raise ValueError(f"Duplicate AECOMP NAME {name}")
    bulk.aecomps[name] = Aecomp(name=name, listtype=listtype, list_ids=list_ids)

def _handle_monpnt1(fields: list[str], cont: Optional[list[str]], bulk: BulkData) -> None:
    """MONPNT1 in MSC's two-line layout (MSC Nastran 2024.1 QRG PDF p.2303-2304; #86).

    ``MONPNT1 NAME LABEL`` (LABEL in fields 3-9) / ``AXES COMP CP X Y Z CD``.  MSC makes
    it "either an aerodynamic or a structural MONPNT1, depending on the data provided in
    the COMP field" (remark 2): an AELIST-type AECOMP sums aero box loads, a SET1-type
    AECOMP sums the structural loads on its grids.  The cross-reference pass files each
    one by its AECOMP (``bulk_xref._check_monitors``).  Until #86 sbeam read its own
    one-line layout, and the structural kind was a card of its own, ``MONPNT3``.
    """
    name = fields[1].strip()
    if not name:
        raise ValueError("MONPNT1: NAME must not be blank")
    if cont is None or not any(f.strip() for f in cont[1:]):
        raise ValueError(
            f"MONPNT1 {name}: the second line (AXES COMP CP X Y Z CD) is missing. MONPNT1 "
            "is read in MSC's two-line layout (QRG p.2303): `MONPNT1, NAME, LABEL` then "
            "`+, AXES, COMP, CP, X, Y, Z`. Before #86 sbeam read AXES-Z on the first line; "
            "move them to the continuation")
    # LABEL spans fields 3-9 (56 characters); fixed-field slices keep their spaces
    label = "".join(getattr(f, "raw", f) for f in fields[2:9]).strip()
    if not cont[1].strip() or not cont[2].strip():
        raise ValueError(f"MONPNT1 {name}: AXES and COMP are required (QRG p.2303)")
    axes = to_int(cont[1])
    comp = cont[2].strip()
    cp   = to_int_opt(cont[3]) if len(cont) > 3 else 0
    x, y, z = (to_float(cont[i]) if len(cont) > i and cont[i].strip() else 0.0
               for i in (4, 5, 6))
    cd_s = cont[7].strip() if len(cont) > 7 else ""
    if cd_s and to_int(cd_s) != cp:
        raise ValueError(
            f"MONPNT1 {name}: CD={cd_s} differs from CP={cp}; sbeam outputs a monitor's "
            "loads in its CP frame (MSC's default, CD = CP). Leave CD blank")
    if name in bulk.monpnt1s:
        raise ValueError(
            f"Duplicate MONPNT1 NAME {name}. MSC lets an aerodynamic and a structural "
            "MONPNT1 share a name (QRG p.2303 remark 2); sbeam keys monitor output by "
            "name, so rename one")
    bulk.monpnt1s[name] = Monpnt1(name=name, label=label, axes=axes, comp=comp,
                                  cp=cp, x=x, y=y, z=z)


def _handle_monpnt3(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MONPNT3 is refused (#86).

    MSC's MONPNT3 "Sums select Grid Point Forces to a user chosen monitor point":
    ``NAME LABEL`` / ``AXES GRIDSET ELEMSET CP X Y Z XFLAG`` / ``CD`` (QRG 2024.1 PDF
    p.2307-2308).  sbeam has no grid point force output.  sbeam's own MONPNT3 (a
    structural sum over SET1 grids) is MSC's structural MONPNT1.
    """
    name = fields[1].strip() if len(fields) > 1 else ""
    raise ValueError(
        f"MONPNT3 {name}: not supported. MSC's MONPNT3 sums grid point forces at a cut "
        "(QRG p.2307), which sbeam does not compute. For the structural sum sbeam's "
        "MONPNT3 used to give (aero + inertia + applied + reaction over SET1 grids), "
        "write an MSC MONPNT1 whose COMP is a SET1-type AECOMP: `MONPNT1, NAME, LABEL` "
        "then `+, AXES, COMP, CP, X, Y, Z` (#86)")


def _handle_monsect(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MONSECT NAME LABEL COMP CID AXIS SIDE TOL + station continuations.

    Continuation lines carry the cut stations, except one optionally led by the
    literal ``NORMAL`` which carries the cut-plane normal in the CID frame::

        MONSECT, SECRW, RIGHT WING, RWING, 70, 2, POS
        +,       0.30, 1.20, 2.10, 3.00
        +,       NORMAL, 0.26, 1.0, 0.0

    The keyword makes the normal line unambiguous against a station line — a
    station list is pure numbers, so a leading alpha token cannot be misread.
    """
    name  = fields[1].strip()
    label = fields[2].strip() if len(fields) > 2 else ""
    comp  = fields[3].strip() if len(fields) > 3 else ""
    cid   = to_int_opt(fields[4]) if len(fields) > 4 else 0
    axis  = to_int(fields[5]) if len(fields) > 5 and fields[5].strip() else 2
    side  = fields[6].strip().upper() if len(fields) > 6 and fields[6].strip() else "POS"
    tol   = to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else None

    if not name:
        raise ValueError("MONSECT: NAME must not be blank")
    if name in bulk.monsects:
        raise ValueError(f"Duplicate MONSECT NAME {name}")
    if axis not in (1, 2, 3):
        raise ValueError(f"MONSECT {name}: AXIS must be 1, 2 or 3 (got {axis})")
    if side not in ("POS", "NEG"):
        raise ValueError(f"MONSECT {name}: SIDE must be 'POS' or 'NEG' (got '{side}')")
    if tol is not None and tol < 0.0:
        raise ValueError(f"MONSECT {name}: TOL must be non-negative (got {tol})")

    stations: list[float] = []
    normal: Optional[tuple[float, float, float]] = None
    for cont in conts:
        tokens = [f for f in cont[1:] if f.strip()]
        if not tokens:
            continue
        if tokens[0].strip().upper() == "NORMAL":
            if normal is not None:
                raise ValueError(f"MONSECT {name}: more than one NORMAL continuation")
            comps = [to_float(t) for t in tokens[1:4]]
            if len(comps) != 3:
                raise ValueError(
                    f"MONSECT {name}: NORMAL needs three components NX, NY, NZ"
                )
            normal = (comps[0], comps[1], comps[2])
            continue
        stations += [to_float(t) for t in tokens]

    if not stations:
        raise ValueError(f"MONSECT {name}: at least one station is required")
    for prev, cur in zip(stations, stations[1:]):
        if cur <= prev:
            raise ValueError(
                f"MONSECT {name}: stations must be strictly increasing "
                f"({prev:g} followed by {cur:g})"
            )
    if normal is not None:
        nsq = sum(c * c for c in normal)
        if nsq < 1e-24:
            raise ValueError(f"MONSECT {name}: NORMAL vector is zero-length")
        # The station axis and the normal are both given in the CID frame, so
        # the cosine needs no coordinate resolution.  A cut plane near-parallel
        # to the reference line either misses it or meets it at an
        # ill-conditioned point, so the reference point would be meaningless.
        cos_an = abs(normal[axis - 1]) / nsq ** 0.5
        if cos_an < 0.1:
            raise ValueError(
                f"MONSECT {name}: NORMAL is within 84 deg of perpendicular to the "
                f"AXIS={axis} reference line (|cos|={cos_an:.3g} < 0.1) — the cut "
                "plane has no usable intercept with it"
            )

    bulk.monsects[name] = Monsect(
        name=name, label=label, comp=comp, cid=cid, axis=axis, side=side,
        tol=tol, stations=stations, normal=normal,
    )


# Dispatch registration (#48): every keyword handled in this module, in one table each.
FIELD_HANDLERS: dict[str, FieldHandler] = {
    "AEROS": _handle_aeros,
    "PAERO1": _handle_paero1,
    "PSTRIP": _handle_pstrip,
    "BODYATT": _handle_attach,
    "LOADINJ": _handle_spline0,
    "SPLINE1": _handle_spline1,
}
CONT_HANDLERS: dict[str, ContHandler] = {
    "MONPNT1": _handle_monpnt1,
    "CAERO1": _handle_caero1,
    "SPLINE2": _handle_spline2,
}
MULTI_HANDLERS: dict[str, MultiHandler] = {
    "AEFACT": _handle_aefact,
    "W2GJ": _handle_w2gj,
    "WKK": _handle_wkk,
    "AECORR": _handle_aecorr,
    "CPINJ": _handle_chordcp,
    "STRIPK": _handle_stripk,
    "SET1": _handle_set1,
    "AELIST": _handle_aelist,
    "AECOMP": _handle_aecomp,
    "MONSECT": _handle_monsect,
    # Refused whatever its lines hold (#86); multi-line so MSC's three-line card gets
    # this message rather than the generic unread-continuation one
    "MONPNT3": _handle_monpnt3,
}
