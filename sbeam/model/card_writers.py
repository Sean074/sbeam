"""Serialize aeroelastic input cards back to comma free-field BDF text.

The viewer's SOL 144 / MLOADS authoring UI (P12) builds model dataclasses in
memory; these writers turn them into card text the parser reads back
identically, so an authored deck round-trips with zero loss.  The module is
Streamlit-free and importable from the CLI or scripts.

Every real field goes through ``parser.bdf_field.fmt_real8`` — a strict reader
truncates each free-field token to 8 characters, so ``%.6E`` output would be
silently corrupt (DEF-M12).

Covered families (the full SOL 144 + MLOADS authoring surface): AESTAT,
AESURF, AELIST, SUPORT, TRIM, TRIMVAR, TRIMOBJ, TRIMCON, DIVERG, MLOADS,
MLDTRIM, MLDTIME, MLDCOMD, MLDPRNT, TABLED1.
"""

from typing import TYPE_CHECKING, Sequence, Union

from sbeam.model.aero import (
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
)
from sbeam.model.constraint import Suport
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
    fields: list[Field] = [t.sid, t.mach, t.q]
    if t.rhoref:
        fields += ["RHOREF", t.rhoref]
    for label, value in t.vars.items():
        fields += [label, value]
    return write_card("TRIM", fields)


def write_trimvar(v: Trimvar) -> list[str]:
    return write_card("TRIMVAR", [v.id, v.label, v.init, v.lb, v.ub])


def write_trimobj(o: Trimobj) -> list[str]:
    fields: list[Field] = [o.sid]
    for label, weight in zip(o.labels, o.weights):
        fields += [label, weight]
    return write_card("TRIMOBJ", fields)


def write_trimcon(c: Trimcon) -> list[str]:
    return write_card("TRIMCON", [c.sid, c.label, c.sense, c.rhs])


def write_diverg(d: Diverg) -> list[str]:
    return write_card("DIVERG", [d.sid, d.nroots, d.rhoref] + list(d.machs))


def write_mloads(m: Mloads) -> list[str]:
    fields: list[Field] = [m.sid, m.mldtrim, m.mldtime,
                           m.mldcomd, m.mldprnt, m.nmodes, m.method, m.zeta]
    # Trim trailing defaults (0 / 0.0) for a compact card; parser re-defaults.
    while len(fields) > 3 and not fields[-1]:
        fields.pop()
    return write_card("MLOADS", fields)


def write_mldtrim(m: Mldtrim) -> list[str]:
    return write_card("MLDTRIM", [m.sid, m.trim_sid])


def write_mldtime(m: Mldtime) -> list[str]:
    fields: list[Field] = [m.sid, m.t0, m.tend, m.dt]
    if m.tout:
        fields.append(m.tout)
    return write_card("MLDTIME", fields)


def write_mldcomd(m: Mldcomd) -> list[str]:
    fields: list[Field] = [m.sid]
    for label, tabid in m.commands:
        fields += [label, tabid]
    return write_card("MLDCOMD", fields)


def write_mldprnt(m: Mldprnt) -> list[str]:
    return write_card("MLDPRNT", [m.sid] + list(m.items))


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
_FAMILIES = {
    "aestat":  ("aestats",  write_aestat),
    "aesurf":  ("aesurfs",  write_aesurf),
    "aelist":  ("aelists",  write_aelist),
    "suport":  ("supports", write_suport),
    "trim":    ("trims",    write_trim),
    "trimvar": ("trimvars", write_trimvar),
    "trimobj": ("trimobjs", write_trimobj),
    "trimcon": ("trimcons", write_trimcon),
    "diverg":  ("divergs",  write_diverg),
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
    for family, (attr, writer) in _FAMILIES.items():
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
