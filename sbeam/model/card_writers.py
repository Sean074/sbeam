"""Serialize aeroelastic input cards back to comma free-field BDF text.

The viewer's SOL 144 / MANVR authoring UI (P12) builds model dataclasses in
memory; these writers turn them into card text the parser reads back
identically, so an authored deck round-trips with zero loss.  The module is
Streamlit-free and importable from the CLI or scripts.

Every real field goes through ``parser.bdf_field.fmt_real8`` — a strict reader
truncates each free-field token to 8 characters, so ``%.6E`` output would be
silently corrupt (DEF-M12).

Covered families (the full SOL 144 + MANVR authoring surface): AESTAT,
AESURF, AELIST, SUPORT, TRIM, TRIMVAR, TRIMWGT, TRIMINEQ, DIVERG, MANVR,
MANTRIM, MANTIME, MANCMD, MANPRNT, TABLED1.
"""

from typing import TYPE_CHECKING, Sequence, Union

from sbeam.model.aero import (
    Aecomp, Aestat, Aesurf, Aelist, Diverg, Monpnt1, Monpnt3, Monsect, Trim, Trimcon,
    Trimobj, Trimvar,
)
from sbeam.model.constraint import Suport
from sbeam.model.gust import Gustlf
from sbeam.model.mass import Massset
from sbeam.model.maneuver import (
    Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads,
)
from sbeam.parser.bdf_field import fmt_real8

if TYPE_CHECKING:
    from sbeam.model.bulk_data import BulkData

Field = Union[int, float, str]

# Value fields per output line (after the card name / '+' marker).
_FIELDS_PER_LINE = 8


def _fld(v: Field) -> str:
    if isinstance(v, bool):
        raise TypeError(f"boolean is not a BDF field value: {v!r}")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return fmt_real8(v)
    return str(v)


def write_card(name: str, fields: Sequence[Field],
               fields_per_line: int = _FIELDS_PER_LINE) -> list[str]:
    """Return comma free-field lines for one card, continuing with '+' lines."""
    toks = [_fld(f) for f in fields]
    lines = [", ".join([name] + toks[:fields_per_line])]
    for i in range(fields_per_line, len(toks), fields_per_line):
        lines.append(", ".join(["+"] + toks[i:i + fields_per_line]))
    return lines


def write_aestat(a: Aestat) -> list[str]:
    return write_card("AESTAT", [a.id, a.label])


def write_aesurf(a: Aesurf) -> list[str]:
    fields: list[Field] = [a.id, a.label, a.cid1, a.alid1]
    if a.cid2 or a.alid2 or a.eff != 1.0:
        fields += [a.cid2, a.alid2, a.eff]
    return write_card("AESURF", fields)


def write_aelist(a: Aelist) -> list[str]:
    return write_card("AELIST", [a.sid] + list(a.elements))


def write_suport(s: Suport) -> list[str]:
    # One card per (GID, DOFs) pair — the SUPORT handler reads base-line
    # fields only, so pairs must not spill onto continuations.
    return write_card("SUPORT", [s.gid, s.dofs])


def write_trim(t: Trim) -> list[str]:
    # MSC's layout: two pairs on the first line, field 9 is AEQR (left blank = 1.0)
    pairs: list[Field] = [x for label, value in t.vars.items() for x in (label, value)]
    fields: list[Field] = [t.sid, t.mach, t.q, *pairs[:4]]
    if len(pairs) > 4:
        fields += [""] * (7 - len(fields)) + [""] + pairs[4:]
    return write_card("TRIM", fields)


def write_trimvar(v: Trimvar) -> list[str]:
    # ZAERO's layout: IDVAR LABEL LOWER UPPER TRIMLNK DMI SYM INITIAL (blank bound = ∓1E30)
    return write_card("TRIMVAR", [v.id, v.label,
                                  "" if v.lb <= -1.0e30 else v.lb,
                                  "" if v.ub >= 1.0e30 else v.ub, "", "", "", v.init])


def write_trimobj(o: Trimobj) -> list[str]:
    fields: list[Field] = [o.sid]
    for label, weight in zip(o.labels, o.weights):
        fields += [label, weight]
    return write_card("TRIMWGT", fields)


def write_trimcon(c: Trimcon) -> list[str]:
    return write_card("TRIMINEQ", [c.sid, c.label, c.sense, c.rhs])


def write_diverg(d: Diverg) -> list[str]:
    return write_card("DIVERG", [d.sid, d.nroots] + list(d.machs))


def write_gustlf(gu: Gustlf) -> list[str]:
    """GUSTLF — the provenance fields are always written, defaults included.

    Unlike MANVR this does *not* trim trailing defaults: the recorded
    derivation is the card's reason for existing, and a card that silently
    dropped ``ALT = 0.0`` (sea level — a real, common condition) would read as
    "not recorded" on the way back in.
    """
    fields: list[Field] = [
        gu.sid, gu.trimid, gu.n, gu.g, gu.ude, gu.veas,
        gu.kg, gu.mu, gu.a, gu.asrc,
        gu.alt if gu.alt is not None else "",
    ]
    return write_card("GUSTLF", fields)


def write_aecomp(a: Aecomp) -> list[str]:
    """AECOMP — NAME, LISTTYPE, then the AELIST or SET1 IDs."""
    return write_card("AECOMP", [a.name, a.listtype, *a.list_ids])


def write_monpnt1(m: "Monpnt1 | Monpnt3") -> list[str]:
    """MONPNT1 in MSC's two-line layout (QRG 2024.1 PDF p.2303; card reference, #86).

    The first line is written in small field with LABEL in fields 3-9: a free-field
    token is limited to 8 characters, and a label is up to 56.  The second line is
    ``AXES, COMP, CP, X, Y, Z``; CD is left blank (output is in CP, MSC's default).
    One card serves both kinds: a structural monitor (held as ``Monpnt3``, the name of
    sbeam's card before #86) is a MONPNT1 whose COMP is a SET1-type AECOMP.
    """
    if len(m.name) > 8 or len(m.label) > 56:
        raise ValueError(
            f"MONPNT1 {m.name}: NAME takes 8 characters and LABEL 56 "
            f"(got {len(m.name)} and {len(m.label)})")
    return [
        f"{'MONPNT1':<8}{m.name:<8}{m.label}".rstrip(),
        ", ".join(["+", _fld(m.axes), m.comp, _fld(m.cp), _fld(m.x), _fld(m.y), _fld(m.z)]),
    ]


def write_monsect(m: Monsect) -> list[str]:
    """MONSECT — header, station rows of 8, then an optional NORMAL row (card reference)."""
    lines = [", ".join([
        "MONSECT", m.name, m.label, m.comp, _fld(m.cid), _fld(m.axis), m.side,
        "" if m.tol is None else _fld(m.tol)])]
    for i in range(0, len(m.stations), _FIELDS_PER_LINE):
        lines.append(", ".join(["+"] + [_fld(v) for v in m.stations[i:i + _FIELDS_PER_LINE]]))
    if m.normal is not None:
        lines.append(", ".join(["+", "NORMAL"] + [_fld(v) for v in m.normal]))
    return lines


def write_masscase(m: Massset) -> list[str]:
    """MASSCASE — the header, then ADD / REPLACE / DELETE rows of CONM2 EIDs.

    Layout: ``docs/10_standard/02_card_reference.md`` (MASSCASE, an sbeam card).  A row
    holds up to 7 EIDs; a REPLACE row holds whole (baseline, overlay) pairs, so 6.  The
    default label ``MASSCASE <sid>`` is written as a blank field, which reads back as
    the same default.  A mass case built from an MSC ``MASSSET`` entry (#102) is a
    different card and is refused here.
    """
    if m.msc:
        raise ValueError(
            f"mass case {m.sid} is an MSC MASSSET combination; it is not written as MASSCASE")
    label = "" if m.label == f"MASSCASE {m.sid}" else m.label
    lines = [", ".join(["MASSCASE", _fld(m.sid), label, _fld(m.scale)])]
    rows = (("ADD", list(m.add), 7),
            ("REPLACE", [eid for pair in m.replace for eid in pair], 6),
            ("DELETE", list(m.delete), 7))
    for op, eids, per_row in rows:
        for i in range(0, len(eids), per_row):
            lines.append(", ".join(["+", op] + [_fld(e) for e in eids[i:i + per_row]]))
    return lines


def write_mloads(m: Mloads) -> list[str]:
    fields: list[Field] = [m.sid, m.mldtrim, m.mldtime,
                           m.mldcomd, m.mldprnt, m.nmodes, m.method, m.zeta]
    # Trim trailing defaults (0 / 0.0) for a compact card; parser re-defaults.
    while len(fields) > 3 and not fields[-1]:
        fields.pop()
    return write_card("MANVR", fields)


def write_mldtrim(m: Mldtrim) -> list[str]:
    return write_card("MANTRIM", [m.sid, m.trim_sid, *([m.rho] if m.rho else [])])


def write_mldtime(m: Mldtime) -> list[str]:
    fields: list[Field] = [m.sid, m.t0, m.tend, m.dt]
    if m.tout:
        fields.append(m.tout)
    return write_card("MANTIME", fields)


def write_mldcomd(m: Mldcomd) -> list[str]:
    fields: list[Field] = [m.sid]
    for label, tabid in m.commands:
        fields += [label, tabid]
    return write_card("MANCMD", fields)


def write_mldprnt(m: Mldprnt) -> list[str]:
    return write_card("MANPRNT", [m.sid] + list(m.items))


def write_tabled1(t: Tabled1) -> list[str]:
    base: list[Field] = [t.tid]
    if t.xaxis != "LINEAR" or t.yaxis != "LINEAR":
        base += [t.xaxis, t.yaxis]
    lines = write_card("TABLED1", base)
    # Data pairs live entirely on continuation lines (base fields 5+ reserved).
    pairs: list[Field] = []
    for x, y in zip(t.xs, t.ys):
        pairs += [x, y]
    pairs.append("ENDT")
    toks = [_fld(p) for p in pairs]
    for i in range(0, len(toks), _FIELDS_PER_LINE):
        lines.append(", ".join(["+"] + toks[i:i + _FIELDS_PER_LINE]))
    return lines


# ---------------------------------------------------------------------------
# Authored-block assembly (viewer export)
# ---------------------------------------------------------------------------

# Family key -> (BulkData attribute, writer).  Order is emission order and is
# chosen so referenced cards appear before their referrers when read top-down.
FAMILIES = {
    "aestat":  ("aestats",  write_aestat),
    "aesurf":  ("aesurfs",  write_aesurf),
    "aelist":  ("aelists",  write_aelist),
    "suport":  ("supports", write_suport),
    "trim":    ("trims",    write_trim),
    "trimvar": ("trimvars", write_trimvar),
    "trimobj": ("trimobjs", write_trimobj),
    "trimcon": ("trimcons", write_trimcon),
    "diverg":  ("divergs",  write_diverg),
    "gustlf":  ("gustlfs",  write_gustlf),
    "masscase": ("masssets", write_masscase),
    # Monitors.  AECOMP first: MONPNT1 and MONSECT name one.  "monpnt3" is the store of
    # the structural MONPNT1s (SET1 component); both stores are written as MONPNT1.
    "aecomp":  ("aecomps",  write_aecomp),
    "monpnt1": ("monpnt1s", write_monpnt1),
    "monpnt3": ("monpnt3s", write_monpnt1),
    "monsect": ("monsects", write_monsect),
    "tabled1": ("tabled1s", write_tabled1),
    "mldtrim": ("mldtrims", write_mldtrim),
    "mldtime": ("mldtimes", write_mldtime),
    "mldcomd": ("mldcomds", write_mldcomd),
    "mldprnt": ("mldprnts", write_mldprnt),
    "mloads":  ("mloads",   write_mloads),
}


def write_authored_block(bulk: "BulkData", authored: dict[str, set[int]],
                         header_comment: str = "") -> str:
    """Serialize the authored cards tracked by the viewer into one text block.

    Args:
        bulk:     BulkData holding the (already-applied) authored cards.
        authored: {family key: set of IDs} — for 'suport' the IDs are GIDs,
                  for 'trimcon' every card sharing the SID is emitted.
        header_comment: optional '$'-comment header text (may be multi-line).

    Returns:
        Card text ending with a newline, or "" when nothing is authored.
    """
    lines: list[str] = []
    for family, (attr, writer) in FAMILIES.items():
        ids = authored.get(family)
        if not ids:
            continue
        store = getattr(bulk, attr)
        for key in sorted(ids):
            if family == "suport":
                for s in store:
                    if s.gid == key:
                        lines += writer(s)
            elif family == "trimcon":
                for c in store.get(key, []):
                    lines += writer(c)
            elif key in store:
                lines += writer(store[key])
    if not lines:
        return ""
    header = []
    if header_comment:
        header = [f"$ {ln}" if not ln.startswith("$") else ln
                  for ln in header_comment.splitlines()]
    return "\n".join(header + lines) + "\n"
