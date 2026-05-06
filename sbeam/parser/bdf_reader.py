import os
import warnings
from typing import Optional

from sbeam.model.bulk_data import BulkData
from sbeam.model.coordinate_system import Cord2r
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar, Plotel, Rbe3, Rbe2
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.mass import Conm2
from sbeam.model.load import Force, Moment, Load, Eigrl
from sbeam.model.constraint import Spc, Spc1
from sbeam.parser.case_control import parse_case_control

_IGNORED_KEYWORDS = frozenset({"BEGIN", "BEGINBULK", "ENDDATA"})
_MAX_CBARS = 200


def _split_free_field(line: str) -> list:
    return [f.strip() for f in line.split(",")]


def _split_fixed_field(line: str) -> list:
    line = line.ljust(72)
    return [line[i : i + 8].strip() for i in range(0, 72, 8)]


def _split_line(line: str) -> list:
    return _split_free_field(line) if "," in line else _split_fixed_field(line)


def _to_float(s: str) -> float:
    s = s.strip()
    return float(s) if s else 0.0


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
    E   = _to_float(fields[2])
    G   = _to_float(fields[3]) if len(fields) > 3 else 0.0
    nu  = _to_float(fields[4]) if len(fields) > 4 else 0.0
    rho = _to_float(fields[5]) if len(fields) > 5 else 0.0
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
    if len(bulk.cbars) >= _MAX_CBARS:
        raise ValueError(f"CBAR count exceeds maximum of {_MAX_CBARS}")

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


def _handle_spc1(fields: list, cont, bulk: BulkData) -> None:
    sid = _to_int(fields[1])
    c   = fields[2].strip()
    _validate_dof(c, f"SPC1 {sid}")
    grids = [_to_int(f) for f in fields[3:] if f.strip()]
    if cont is not None:
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
        elif keyword == "CONM2":
            _handle_conm2(fields, cont, bulk)
        elif keyword == "SPC":
            _handle_spc(fields, bulk)
        elif keyword == "SPC1":
            _handle_spc1(fields, cont, bulk)
        elif keyword == "FORCE":
            _handle_force(fields, bulk)
        elif keyword == "MOMENT":
            _handle_moment(fields, bulk)
        elif keyword == "LOAD":
            _handle_load(fields, cont, bulk)
        elif keyword == "EIGRL":
            _handle_eigrl(fields, bulk)
        else:
            warnings.warn(f"Unknown BDF card '{keyword}' — skipped", UserWarning, stacklevel=2)

        i += 1

    # Validate LOAD component references after all cards are parsed
    for load_sid, load in bulk.loads.items():
        for _, comp_sid in load.components:
            if comp_sid not in bulk.forces and comp_sid not in bulk.moments:
                raise ValueError(
                    f"LOAD {load_sid}: component SID {comp_sid} not found in FORCE or MOMENT sets"
                )

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
