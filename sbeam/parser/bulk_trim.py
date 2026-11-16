"""Trim, divergence, gust and transient maneuver-loads bulk-card handlers (#48)."""
import math

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aestat, Aesurf, Trim, Diverg, Trimvar, Trimobj, Trimcon
from sbeam.model.gust import Gustlf, KG_MAX
from sbeam.model.maneuver import Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads
from sbeam.parser.bulk_fields import FieldHandler, ContHandler, MultiHandler, to_float, to_int, to_int_opt, to_float_or_none


# ---------------------------------------------------------------------------
# Trim card set handlers (Step 51)
# ---------------------------------------------------------------------------

def _handle_aestat(fields: list[str], bulk: BulkData) -> None:
    aid   = to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    if not label:
        raise ValueError(f"AESTAT {aid}: LABEL must not be blank")
    if aid in bulk.aestats:
        raise ValueError(f"Duplicate AESTAT ID {aid}")
    bulk.aestats[aid] = Aestat(id=aid, label=label)


def _handle_aesurf(fields: list[str], bulk: BulkData) -> None:
    aid   = to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    cid1  = to_int(fields[3]) if len(fields) > 3 else 0
    alid1 = to_int(fields[4]) if len(fields) > 4 else 0
    cid2  = to_int_opt(fields[5]) if len(fields) > 5 and fields[5].strip() else 0
    alid2 = to_int_opt(fields[6]) if len(fields) > 6 and fields[6].strip() else 0
    eff   = to_float(fields[7]) if len(fields) > 7 and fields[7].strip() else 1.0
    ldw   = fields[8].strip().upper() or "LDW"
    if not label:
        raise ValueError(f"AESURF {aid}: LABEL must not be blank")
    if ldw != "LDW":
        # NOLDW: the user supplies the control's induced forces (QRG p.1156 remark 2); sbeam
        # always derives them from the deflected boxes.  Field 9 was never read (#63)
        raise ValueError(f"AESURF {aid}: LDW = '{ldw}' is not supported (only LDW)")
    if aid in bulk.aesurfs:
        raise ValueError(f"Duplicate AESURF ID {aid}")
    bulk.aesurfs[aid] = Aesurf(id=aid, label=label, cid1=cid1, alid1=alid1,
                                cid2=cid2, alid2=alid2, eff=eff)

def _handle_trim(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid  = to_int(fields[1])
    mach = to_float(fields[2]) if len(fields) > 2 else 0.0
    q    = to_float(fields[3]) if len(fields) > 3 else 0.0
    if sid in bulk.trims:
        raise ValueError(f"Duplicate TRIM SID {sid}")
    if mach < 0.0:  # β = √(1−M²) would silently run |M| (#58 sweep)
        raise ValueError(f"TRIM {sid}: MACH={mach} must be non-negative")
    # Collect alternating LABEL/VALUE pairs from remainder of base line + continuations
    raw_pairs: list[str] = list(fields[4:])
    for cont in conts:
        raw_pairs += list(cont[1:])
    vars_: dict[str, float] = {}
    rhoref = 0.0
    raw_pairs = [f for f in raw_pairs if f.strip()]
    if len(raw_pairs) % 2 != 0:
        raise ValueError(f"TRIM {sid}: odd number of LABEL/VALUE tokens — must be paired")
    for i in range(0, len(raw_pairs), 2):
        lbl = raw_pairs[i].strip().upper()
        val = to_float(raw_pairs[i + 1])
        # RHOREF is an sbeam extension (Step 61): a pseudo-label carrying the
        # freestream density so V = sqrt(2q/rho) is available to the transient
        # maneuver rate terms.  It is not a trim variable and never enters vars_.
        if lbl == "RHOREF":
            if rhoref:
                raise ValueError(f"TRIM {sid}: duplicate label 'RHOREF'")
            if val <= 0.0:
                raise ValueError(
                    f"TRIM {sid}: RHOREF must be positive; got {val}")
            rhoref = val
            continue
        if lbl in vars_:
            raise ValueError(f"TRIM {sid}: duplicate label '{lbl}'")
        vars_[lbl] = val
    bulk.trims[sid] = Trim(sid=sid, mach=mach, q=q, vars=vars_, rhoref=rhoref)


def _handle_diverg(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    # DIVERG  SID  NROOTS  RHOREF  M1  M2  ...   (RHOREF is an sbeam extension in
    # field 4 used only to map q_div -> V_div; leave blank/0.0 to omit V_div).
    sid    = to_int(fields[1])
    nroots = to_int(fields[2]) if fields[2].strip() else 1  # QRG p.1603: Default = 1
    if nroots < 1:
        raise ValueError(f"DIVERG {sid}: NROOTS must be >= 1, got {nroots}")
    rhoref = to_float(fields[3]) if len(fields) > 3 and fields[3].strip() else 0.0
    machs  = [to_float(f) for f in fields[4:] if f.strip()]
    for cont in conts:
        machs += [to_float(f) for f in cont[1:] if f.strip()]
    if sid in bulk.divergs:
        raise ValueError(f"Duplicate DIVERG SID {sid}")
    if any(m < 0.0 for m in machs):
        raise ValueError(f"DIVERG {sid}: every Mach must be non-negative (got {machs})")
    bulk.divergs[sid] = Diverg(sid=sid, nroots=nroots, rhoref=rhoref, machs=machs)

# ---------------------------------------------------------------------------
# Phase G0 — ZAERO-style transient maneuver-loads cards
# ---------------------------------------------------------------------------

def _handle_tabled1(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """TABLED1 — tabular function: TID then (x, y) pairs terminated by ENDT."""
    tid   = to_int(fields[1])
    xaxis = fields[2].strip().upper() if len(fields) > 2 and fields[2].strip() else "LINEAR"
    yaxis = fields[3].strip().upper() if len(fields) > 3 and fields[3].strip() else "LINEAR"
    if tid in bulk.tabled1s:
        raise ValueError(f"Duplicate TABLED1 TID {tid}")
    # Data pairs live entirely on the continuation line(s); fields[4:] of the
    # base line are reserved/blank in the NASTRAN layout.
    tokens: list[str] = [f for f in fields[4:]]
    for cont in conts:
        tokens += list(cont[1:])
    tokens = [t.strip() for t in tokens if t.strip()]
    xs: list[float] = []
    ys: list[float] = []
    k = 0
    while k < len(tokens):
        if tokens[k].upper() == "ENDT":
            break
        if k + 1 >= len(tokens):
            raise ValueError(f"TABLED1 {tid}: dangling abscissa with no ordinate")
        xs.append(to_float(tokens[k]))
        ys.append(to_float(tokens[k + 1]))
        k += 2
    if len(xs) < 2:
        raise ValueError(f"TABLED1 {tid}: needs at least two (x, y) points")
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        raise ValueError(f"TABLED1 {tid}: abscissae must be strictly increasing")
    bulk.tabled1s[tid] = Tabled1(tid=tid, xs=xs, ys=ys, xaxis=xaxis, yaxis=yaxis)


def _handle_mldtime(fields: list[str], bulk: BulkData) -> None:
    """MLDTIME — integration window: SID T0 TEND DT [TOUT]."""
    sid  = to_int(fields[1])
    t0   = to_float(fields[2]) if len(fields) > 2 else 0.0
    tend = to_float(fields[3]) if len(fields) > 3 else 0.0
    dt   = to_float(fields[4]) if len(fields) > 4 else 0.0
    tout = to_float(fields[5]) if len(fields) > 5 and fields[5].strip() else 0.0
    if dt <= 0.0:
        raise ValueError(f"MLDTIME {sid}: DT must be positive")
    if tend <= t0:
        raise ValueError(f"MLDTIME {sid}: TEND must exceed T0")
    if sid in bulk.mldtimes:
        raise ValueError(f"Duplicate MLDTIME SID {sid}")
    bulk.mldtimes[sid] = Mldtime(sid=sid, t0=t0, tend=tend, dt=dt, tout=tout)


def _handle_mldcomd(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MLDCOMD — pilot commands: SID then (LABEL, TABID) pairs."""
    sid = to_int(fields[1])
    if sid in bulk.mldcomds:
        raise ValueError(f"Duplicate MLDCOMD SID {sid}")
    tokens: list[str] = list(fields[2:])
    for cont in conts:
        tokens += list(cont[1:])
    tokens = [t for t in tokens if t.strip()]
    if len(tokens) % 2 != 0:
        raise ValueError(f"MLDCOMD {sid}: odd number of LABEL/TABID tokens — must be paired")
    commands: list[tuple[str, int]] = []
    for i in range(0, len(tokens), 2):
        label = tokens[i].strip().upper()
        tabid = to_int(tokens[i + 1])
        commands.append((label, tabid))
    bulk.mldcomds[sid] = Mldcomd(sid=sid, commands=commands)


def _handle_mldprnt(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """MLDPRNT — ASCII time-history output request: SID then optional item keywords."""
    sid = to_int(fields[1])
    if sid in bulk.mldprnts:
        raise ValueError(f"Duplicate MLDPRNT SID {sid}")
    items: list[str] = [f.strip().upper() for f in fields[2:] if f.strip()]
    for cont in conts:
        items += [f.strip().upper() for f in cont[1:] if f.strip()]
    bulk.mldprnts[sid] = Mldprnt(sid=sid, items=items)


def _handle_mldtrim(fields: list[str], bulk: BulkData) -> None:
    """MLDTRIM — initial steady-state condition: SID TRIMID (a static TRIM sid)."""
    sid      = to_int(fields[1])
    trim_sid = to_int(fields[2])
    if sid in bulk.mldtrims:
        raise ValueError(f"Duplicate MLDTRIM SID {sid}")
    bulk.mldtrims[sid] = Mldtrim(sid=sid, trim_sid=trim_sid)


def _handle_mloads(fields: list[str], bulk: BulkData) -> None:
    """MLOADS — transient driver.

    SID MLDTRIM MLDTIME [MLDCOMD] [MLDPRNT] [NMODES] [METHOD] [ZETA]

    NMODES/METHOD/ZETA configure the free-free modal basis (retained ELASTIC
    mode count, EIGRL sid for the basis solve, uniform elastic damping ratio).
    All three are optional and default to "internal default / all modes /
    undamped".  Any of the three nonzero selects the Step 62 modal transient
    solver; METHOD=-1 is the sentinel for "modal solver with the internal
    all-modes EIGRL default" (the all-defaults modal case).  All-zeros runs
    the legacy direct l-set solver.
    """
    sid     = to_int(fields[1])
    mldtrim = to_int(fields[2])
    mldtime = to_int(fields[3])
    mldcomd = to_int(fields[4]) if len(fields) > 4 and fields[4].strip() else 0
    mldprnt = to_int(fields[5]) if len(fields) > 5 and fields[5].strip() else 0
    nmodes  = to_int(fields[6]) if len(fields) > 6 and fields[6].strip() else 0
    method  = to_int(fields[7]) if len(fields) > 7 and fields[7].strip() else 0
    zeta    = to_float(fields[8]) if len(fields) > 8 and fields[8].strip() else 0.0
    if sid in bulk.mloads:
        raise ValueError(f"Duplicate MLOADS SID {sid}")
    if nmodes < 0:
        raise ValueError(f"MLOADS {sid}: NMODES must be >= 0; got {nmodes}")
    if method < -1:
        raise ValueError(
            f"MLOADS {sid}: METHOD must be an EIGRL sid, 0 (default) or -1 "
            f"(modal solver, internal all-modes default); got {method}")
    if zeta < 0.0:
        raise ValueError(f"MLOADS {sid}: ZETA must be >= 0; got {zeta}")
    bulk.mloads[sid] = Mloads(
        sid=sid, mldtrim=mldtrim, mldtime=mldtime,
        mldcomd=mldcomd, mldprnt=mldprnt, nmodes=nmodes,
        method=method, zeta=zeta,
    )


def _handle_gustlf(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    """GUSTLF — quasi-static gust load-factor case (FAR/CS 23.341).

    SID TRIMID N G [UDE] [VEAS] [KG] [MU] / [A] [ASRC] [ALT]

    Only TRIMID, N and G affect the solution (``URDD3 = -N*G`` on the referenced
    TRIM); every other field is provenance recorded by
    ``sbeam_tools/cases/gust.py`` and echoed to the f06.  The card carries no
    dimensional semantics sbeam acts on — see ``model/gust.py``.
    """
    vals = list(fields[1:])
    for cont in conts:
        vals += list(cont[1:])

    def _opt_float(idx: int) -> float:
        return to_float(vals[idx]) if len(vals) > idx and vals[idx].strip() else 0.0

    if len(vals) < 4 or not all(v.strip() for v in vals[:4]):
        raise ValueError("GUSTLF: SID, TRIMID, N and G are required")

    sid    = to_int(vals[0])
    trimid = to_int(vals[1])
    n      = to_float(vals[2])
    g      = to_float(vals[3])
    ude    = _opt_float(4)
    veas   = _opt_float(5)
    kg     = _opt_float(6)
    mu     = _opt_float(7)
    a      = _opt_float(8)
    asrc   = vals[9].strip().upper() if len(vals) > 9 and vals[9].strip() else "RIGID"
    # ALT is Optional, unlike the other provenance fields: sea level is a real
    # condition, so 0.0 cannot double as "not recorded" here (see model/gust.py).
    alt    = to_float_or_none(vals[10]) if len(vals) > 10 else None

    if sid in bulk.gustlfs:
        raise ValueError(f"Duplicate GUSTLF SID {sid}")
    if not math.isfinite(n):
        raise ValueError(f"GUSTLF {sid}: N must be finite; got {n}")
    if g <= 0.0:
        raise ValueError(f"GUSTLF {sid}: G must be > 0; got {g}")
    if asrc not in ("RIGID", "RESTRAINED"):
        raise ValueError(
            f"GUSTLF {sid}: ASRC must be RIGID or RESTRAINED; got {asrc!r}"
        )
    for name, value in (("UDE", ude), ("VEAS", veas), ("MU", mu), ("A", a)):
        if value < 0.0:
            raise ValueError(f"GUSTLF {sid}: {name} must be >= 0 when recorded; got {value}")
    # K_g = 0.88 mu / (5.3 + mu) is strictly inside (0, 0.88); a recorded value
    # outside it cannot have come from the regulation's formula.  This is the one
    # part of the derivation the parser can falsify without owning the arithmetic.
    if kg != 0.0 and not (0.0 < kg < KG_MAX):
        raise ValueError(
            f"GUSTLF {sid}: KG must lie in (0, {KG_MAX}) when recorded; got {kg}"
        )

    bulk.gustlfs[sid] = Gustlf(
        sid=sid, trimid=trimid, n=n, g=g, ude=ude, veas=veas,
        kg=kg, mu=mu, a=a, asrc=asrc, alt=alt,
    )

def _handle_trimvar(fields: list[str], bulk: BulkData) -> None:
    vid   = to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    init  = to_float(fields[3]) if len(fields) > 3 else 0.0
    # Blank, not absent: every line arrives padded to 9 fields (#64), and a blank bound
    # read as 0.0 would pin the variable (#77)
    lb    = to_float(fields[4]) if fields[4].strip() else -1.0e30
    ub    = to_float(fields[5]) if fields[5].strip() else  1.0e30
    if not label:
        raise ValueError(f"TRIMVAR {vid}: LABEL must not be blank")
    if vid in bulk.trimvars:
        raise ValueError(f"Duplicate TRIMVAR ID {vid}")
    bulk.trimvars[vid] = Trimvar(id=vid, label=label, init=init, lb=lb, ub=ub)


def _handle_trimobj(fields: list[str], conts: list[list[str]], bulk: BulkData) -> None:
    sid = to_int(fields[1])
    if sid in bulk.trimobjs:
        raise ValueError(f"Duplicate TRIMOBJ SID {sid}")
    raw_pairs: list[str] = list(fields[2:])
    for cont in conts:
        raw_pairs += list(cont[1:])
    raw_pairs = [f for f in raw_pairs if f.strip()]
    if len(raw_pairs) % 2 != 0:
        raise ValueError(f"TRIMOBJ {sid}: odd number of LABEL/WEIGHT tokens — must be paired")
    labels:  list[str] = []
    weights: list[float] = []
    for i in range(0, len(raw_pairs), 2):
        labels.append(raw_pairs[i].strip().upper())
        weights.append(to_float(raw_pairs[i + 1]))
    bulk.trimobjs[sid] = Trimobj(sid=sid, labels=labels, weights=weights)


def _handle_trimcon(fields: list[str], bulk: BulkData) -> None:
    sid   = to_int(fields[1])
    label = fields[2].strip().upper() if len(fields) > 2 else ""
    sense = fields[3].strip().upper() if len(fields) > 3 else ""
    rhs   = to_float(fields[4]) if len(fields) > 4 else 0.0
    if sense not in ("LE", "GE"):
        raise ValueError(f"TRIMCON {sid}: SENSE must be LE or GE, got '{sense}'")
    # Multiple TRIMCON cards share a SID — collect as list
    bulk.trimcons.setdefault(sid, []).append(Trimcon(sid=sid, label=label, sense=sense, rhs=rhs))


# Dispatch registration (#48): every keyword handled in this module, in one table each.
FIELD_HANDLERS: dict[str, FieldHandler] = {
    "AESTAT": _handle_aestat,
    "AESURF": _handle_aesurf,
    "TRIMVAR": _handle_trimvar,
    "TRIMCON": _handle_trimcon,
    "MLDTIME": _handle_mldtime,
    "MLDTRIM": _handle_mldtrim,
    "MLOADS": _handle_mloads,
}
CONT_HANDLERS: dict[str, ContHandler] = {}
MULTI_HANDLERS: dict[str, MultiHandler] = {
    "TRIM": _handle_trim,
    "GUSTLF": _handle_gustlf,
    "DIVERG": _handle_diverg,
    "TRIMOBJ": _handle_trimobj,
    "TABLED1": _handle_tabled1,
    "MLDCOMD": _handle_mldcomd,
    "MLDPRNT": _handle_mldprnt,
}
