"""Cross-parse every repo deck with pyNastran and require field agreement (#83).

pyNastran (BSD-3) is an independent reader of MSC NASTRAN bulk data.  For every deck
``parse_bdf`` accepts, the exact bulk lines sbeam reads are handed to pyNastran as a
bulk-only (punch) file, and both readers' values are compared card by card:

- a field both read must agree (rtol 1e-9; blank, 0 and None are equal);
- a field pyNastran stores and sbeam does not read (CBAR offsets, PBAR I12/K1/K2, RBAR
  CMA/CMB, PBUSH B/GE …) must hold NASTRAN's default — otherwise sbeam accepted a card
  and dropped a value, the class of #62–#64;
- a card pyNastran cannot parse must be an sbeam extension listed in
  ``_SBEAM_EXTENSIONS`` with the issue that tracks it.

``_KNOWN`` lists open disagreements, each with its issue; remove an entry when the issue
is fixed (``test_known_disagreements_still_exist`` fails on a stale entry).  The
crafted-card tests pin the 2026-11-16 audit's probes.

Optional: skipped unless pyNastran is installed.  CI runs it in its own job, because
pyNastran 1.4.1 requires numpy < 2 (``.github/workflows/ci.yml``, ``compat``).  It is a
test-only dependency; ``sbeam/`` never imports it.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

import pytest

pytest.importorskip("pyNastran")
from pyNastran.bdf.bdf import BDF  # noqa: E402

from sbeam.model.bulk_data import BulkData  # noqa: E402
from sbeam.parser import bdf_reader  # noqa: E402
from sbeam.parser.bdf_reader import _read_cards, parse_bdf  # noqa: E402
from sbeam.parser.bulk_fields import is_continuation, split_line  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DECKS = sorted([*(REPO / "sample").glob("*.bdf"), *(REPO / "sample").glob("*.dat"),
                *(REPO / "tests/integration/bdf").glob("*.bdf")])

#: Cards whose sbeam form puts an sbeam-only value in a field MSC defines, so pyNastran
#: rightly rejects them.  Tracked for alignment or renaming.
_SBEAM_EXTENSIONS = {
    "AEROS": "#87: sbeam reads MACH from field 9, blank in MSC",
    "TRIM": "#87/#88: sbeam's RHOREF pseudo-label and label pairs in field 9 (MSC AEQR)",
    "MASSSET": "#78: MSC name, different layout",
}

#: sbeam cards pyNastran cannot read at all (it raises instead of storing an error): they
#: are removed before pyNastran reads the deck.
_NOT_FOR_PYNASTRAN = {
    "MONPNT1": "#86: sbeam's one-line layout; MSC's has a label line",
    "MONPNT3": "#86: sbeam's one-line layout; MSC's is a grid-point-force monitor",
}

#: (card, field) disagreements left open, with the issue fixing each.
_KNOWN: dict[tuple[str, str], str] = {}


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------

def _bulk_lines(path: Path) -> list[str]:
    """The exact bulk lines ``parse_bdf`` hands to ``parse_bulk_data`` (INCLUDEs resolved)."""
    captured: list[list[str]] = []
    real = bdf_reader.parse_bulk_data

    def capture(lines: list[str]):
        captured.append(list(lines))
        return real(lines)

    bdf_reader.parse_bulk_data = capture
    try:
        parse_bdf(path)
    finally:
        bdf_reader.parse_bulk_data = real
    return captured[0]


def _qrg_overflow(line: str) -> list[str]:
    """Split a free-field line longer than 10 fields into explicit continuations (QRG p.1049).

    pyNastran 1.4.1 drops data past field 9 of a free-field line (``SET1,1310,1,900,2,3,4,
    5,10,11`` loses 11) where NASTRAN runs it on to a continuation.  Written out per the
    QRG here, independently of sbeam's reader, so the comparison stays a check of field
    meaning; sbeam's own handling of the rule is gated by ``test_card_normaliser.py``.
    """
    body = line.split("$", 1)[0].rstrip()
    if "," not in body:
        return [line]
    tokens = [t.strip() for t in body.split(",")]
    while tokens and not tokens[-1]:
        tokens.pop()
    if len(tokens) <= 9 or (len(tokens) == 10 and tokens[9].startswith(("+", "*"))
                            and not tokens[9][1:2].isdigit()):
        return [line]                       # fits, or field 10 is only a marker
    head, data = tokens[0], tokens[1:]
    rows = [data[i:i + 8] for i in range(0, len(data), 8)]
    return [",".join([head, *rows[0]])] + [",".join(["+", *row]) for row in rows[1:]]


def _pynastran(lines: list[str], tmp: Path) -> tuple[Any, set[str]]:
    """pyNastran model of bulk lines, and the card types it failed to parse."""
    kept, skip = [], False
    for line in lines:
        body = line.split("$", 1)[0]
        if not body.strip():
            continue
        fields = split_line(body)
        if not is_continuation(fields):
            name = fields[0].strip().upper().rstrip("*")
            skip = name in _NOT_FOR_PYNASTRAN or body.strip().upper() in ("BEGIN BULK", "ENDDATA")
        if not skip:
            kept.extend(_qrg_overflow(line))
    path = tmp / "bulk.pch"
    path.write_text("\n".join(kept) + "\n")
    model = BDF(debug=None)
    model.set_error_storage(nparse_errors=10000, stop_on_parsing_error=False)
    model.read_bdf(str(path), punch=True, xref=False, validate=False)
    failed = {err[0] for err in getattr(model, "_stored_parse_errors", [])}
    return model, failed


def _parseable() -> list[Path]:
    ok = []
    for deck in DECKS:
        try:
            parse_bdf(deck)
        except Exception:
            continue
        ok.append(deck)
    return ok


PARSEABLE = _parseable()


# ---------------------------------------------------------------------------
# common view: {card: {key: {field: value}}}
# ---------------------------------------------------------------------------

def _f(x: Any) -> Any:
    """numpy scalars/arrays and tuples to plain Python."""
    if x is None or isinstance(x, (str, bool)):
        return x
    if hasattr(x, "tolist"):
        return x.tolist()
    if isinstance(x, (list, tuple)):
        return [_f(v) for v in x]
    return x


def _sbeam_view(b: BulkData) -> dict[str, dict[Any, dict[str, Any]]]:
    v: dict[str, dict[Any, dict[str, Any]]] = {
        "GRID": {k: dict(cp=g.cp, x=g.x, y=g.y, z=g.z, cd=g.cd, ps=g.ps) for k, g in b.grids.items()},
        "CBAR": {k: dict(pid=e.pid, ga=e.ga, gb=e.gb, x=[e.x1, e.x2, e.x3], offt=e.offt,
                         pa=e.pa, pb=e.pb) for k, e in b.cbars.items()},
        "CBUSH": {k: dict(pid=e.pid, ga=e.ga, gb=e.gb, cid=e.cid,
                          x=[e.x1, e.x2, e.x3] if e.cid is None else None)
                  for k, e in b.cbushs.items()},
        "CROD": {k: dict(pid=e.pid, ga=e.ga, gb=e.gb) for k, e in b.crods.items()},
        "CONROD": {k: dict(ga=e.ga, gb=e.gb, mid=e.mid, A=e.A, J=e.J, c=e.c, nsm=e.nsm)
                   for k, e in b.conrods.items()},
        "PLOTEL": {k: dict(g1=e.g1, g2=e.g2) for k, e in b.plotels.items()},
        "RBE2": {k: dict(gn=e.gn, cm=e.cm, gm=list(e.gm)) for k, e in b.rbe2s.items()},
        "RBAR": {k: dict(ga=e.ga, gb=e.gb, cna=e.cna, cnb=e.cnb) for k, e in b.rbars.items()},
        "PBAR": {k: dict(mid=p.mid, A=p.A, I1=p.I1, I2=p.I2, J=p.J, nsm=p.nsm,
                         c=[p.c1, p.c2, p.d1, p.d2, p.e1, p.e2, p.f1, p.f2])
                 for k, p in b.pbars.items()},
        "PROD": {k: dict(mid=p.mid, A=p.A, J=p.J, c=p.c, nsm=p.nsm) for k, p in b.prods.items()},
        "PBUSH": {k: dict(k=[p.k1, p.k2, p.k3, p.k4, p.k5, p.k6]) for k, p in b.pbushs.items()},
        "MAT1": {k: dict(E=m.E, G=m.G, nu=m.nu, rho=m.rho) for k, m in b.mat1s.items()},
        "CONM2": {k: dict(gid=c.gid, cid=c.cid, m=c.m, x=[c.x1, c.x2, c.x3],
                          I=[c.i11, c.i21, c.i22, c.i31, c.i32, c.i33])
                  for k, c in b.conm2s.items()},
        "FORCE": {k: dict(v=sorted((x.gid, x.cid, x.f, x.n1, x.n2, x.n3) for x in L))
                  for k, L in b.forces.items()},
        "MOMENT": {k: dict(v=sorted((x.gid, x.cid, x.m, x.n1, x.n2, x.n3) for x in L))
                   for k, L in b.moments.items()},
        "LOAD": {k: dict(s=x.s, comp=[list(c) for c in x.components]) for k, x in b.loads.items()},
        "GRAV": {k: dict(cid=x.cid, g=x.g, N=[x.n1, x.n2, x.n3]) for k, x in b.gravs.items()},
        "EIGRL": {k: dict(v1=x.v1, v2=x.v2, nd=x.nd, norm=x.norm) for k, x in b.eigrls.items()},
        "CORD2R": {k: dict(rid=c.rid, a=list(c.a), b=list(c.b), c=list(c.c))
                   for k, c in b.cord2rs.items()},
        "CAERO1": {k: dict(pid=c.pid, cp=c.cp, nspan=c.nspan, nchord=c.nchord, lspan=c.lspan,
                           lchord=c.lchord, igid=c.igid, p1=list(c.p1), x12=c.x12,
                           p4=list(c.p4), x43=c.x43) for k, c in b.caero1s.items()},
        "AEFACT": {k: dict(d=list(a.data)) for k, a in b.aefacts.items()},
        "SET1": {k: dict(g=sorted(s.grids)) for k, s in b.set1s.items()},
        "SPLINE2": {k: dict(caero=s.caero, id1=s.id1, id2=s.id2, setg=s.setg, dz=s.dz,
                            dtor=s.dtor, cid=s.cid, dthx=s.dthx, dthy=s.dthy, usage=s.usage)
                    for k, s in b.spline2s.items()},
        "AELIST": {k: dict(e=sorted(a.elements)) for k, a in b.aelists.items()},
        "AESTAT": {k: dict(label=a.label) for k, a in b.aestats.items()},
        "AESURF": {k: dict(label=a.label, cid1=a.cid1, alid1=a.alid1, cid2=a.cid2,
                           alid2=a.alid2, eff=a.eff) for k, a in b.aesurfs.items()},
        "TRIM": {k: dict(mach=t.mach, q=t.q, vars=sorted(t.vars.items()))
                 for k, t in b.trims.items()},
        "TABLED1": {k: dict(x=list(t.xs), y=list(t.ys)) for k, t in b.tabled1s.items()},
        "DIVERG": {k: dict(nroots=d.nroots, machs=list(d.machs)) for k, d in b.divergs.items()},
        "SPC": {"all": dict(v=_sbeam_spcs(b))},
        "SUPORT": {"all": dict(v=sorted((s.gid, s.dofs) for s in b.supports))},
    }
    return v


def _sbeam_spcs(b: BulkData) -> list[tuple]:
    out = set()
    for sid, L in b.spcs.items():
        for c in L:
            for g, cc, d in ((c.g1, c.c1, c.d1), (c.g2, c.c2, c.d2)):
                if g:
                    out |= {(sid, g, ch, float(d)) for ch in (cc or "")}
    for sid, L1 in b.spc1s.items():
        for c1 in L1:
            out |= {(sid, g, ch, 0.0) for g in c1.grids for ch in c1.c}
    return sorted(out)


def _pyn_view(m: Any) -> dict[str, dict[Any, dict[str, Any]]]:
    v: dict[str, dict[Any, dict[str, Any]]] = {k: {} for k in (
        "CBAR", "CBUSH", "CROD", "CONROD", "PLOTEL", "RBE2", "RBAR", "PBAR", "PROD", "PBUSH")}
    v["GRID"] = {k: dict(cp=n.cp, x=_f(n.xyz[0]), y=_f(n.xyz[1]), z=_f(n.xyz[2]), cd=n.cd,
                         ps=n.ps) for k, n in m.nodes.items()}
    for k, e in m.elements.items():
        if e.type == "CBAR":
            v["CBAR"][k] = dict(pid=e.pid, ga=e.ga, gb=e.gb, x=_f(e.x), offt=e.offt,
                                pa=e.pa, pb=e.pb)
        elif e.type == "CBUSH":
            # CID >= 0 overrides the vector (QRG p.1379 remark 3), so compare one of them
            v["CBUSH"][k] = dict(pid=e.pid, ga=e.nodes[0], gb=e.nodes[1], cid=e.cid,
                                 x=_f(e.x) if e.cid is None else None)
        elif e.type == "CROD":
            v["CROD"][k] = dict(pid=e.pid, ga=e.nodes[0], gb=e.nodes[1])
        elif e.type == "CONROD":
            v["CONROD"][k] = dict(ga=e.nodes[0], gb=e.nodes[1], mid=e.mid, A=e.A, J=e.j,
                                  c=e.c, nsm=e.nsm)
    v["PLOTEL"] = {k: dict(g1=e.nodes[0], g2=e.nodes[1]) for k, e in m.plotels.items()}
    for k, e in m.rigid_elements.items():
        if e.type == "RBE2":
            v["RBE2"][k] = dict(gn=e.gn, cm=e.cm, gm=list(e.Gmi))
        elif e.type == "RBAR":
            v["RBAR"][k] = dict(ga=e.ga, gb=e.gb, cna=e.cna, cnb=e.cnb)
    for k, p in m.properties.items():
        if p.type == "PBAR":
            v["PBAR"][k] = dict(mid=p.mid, A=p.A, I1=p.i1, I2=p.i2, J=p.j, nsm=p.nsm,
                                c=[p.c1, p.c2, p.d1, p.d2, p.e1, p.e2, p.f1, p.f2])
        elif p.type == "PROD":
            v["PROD"][k] = dict(mid=p.mid, A=p.A, J=p.j, c=p.c, nsm=p.nsm)
        elif p.type == "PBUSH":
            v["PBUSH"][k] = dict(k=_f(p.Ki))
    v["MAT1"] = {k: dict(E=x.e, G=x.g, nu=x.nu, rho=x.rho)
                 for k, x in m.materials.items() if x.type == "MAT1"}
    v["CONM2"] = {k: dict(gid=c.nid, cid=c.cid, m=c.mass, x=_f(c.X), I=_f(c.I))
                  for k, c in m.masses.items() if c.type == "CONM2"}
    v["FORCE"], v["MOMENT"], v["LOAD"], v["GRAV"] = {}, {}, {}, {}
    for sid, loads in m.loads.items():
        for x in loads:
            if x.type in ("FORCE", "MOMENT"):
                v[x.type].setdefault(sid, dict(v=[]))["v"].append(
                    (x.node, x.cid, x.mag, *_f(x.xyz)))
            elif x.type == "GRAV":
                v["GRAV"][sid] = dict(cid=x.cid, g=x.scale, N=_f(x.N))
    for sid, combos in m.load_combinations.items():
        for x in combos:
            if x.type == "LOAD":
                v["LOAD"][sid] = dict(s=x.scale, comp=[[_f(s), i] for s, i in
                                                      zip(x.scale_factors, x.load_ids)])
    for typ in ("FORCE", "MOMENT"):
        for d in v[typ].values():
            d["v"] = sorted(d["v"])
    v["EIGRL"] = {k: dict(v1=x.v1, v2=x.v2, nd=x.nd, norm=x.norm or "MASS")   # QRG default
                  for k, x in m.methods.items() if x.type == "EIGRL"}
    v["CORD2R"] = {k: dict(rid=c.rid, a=_f(c.e1), b=_f(c.e2), c=_f(c.e3))
                   for k, c in m.coords.items() if c.type == "CORD2R"}
    v["CAERO1"] = {k: dict(pid=c.pid, cp=c.cp, nspan=c.nspan, nchord=c.nchord, lspan=c.lspan,
                           lchord=c.lchord, igid=c.igroup, p1=_f(c.p1), x12=c.x12,
                           p4=_f(c.p4), x43=c.x43)
                   for k, c in m.caeros.items() if c.type == "CAERO1"}
    v["AEFACT"] = {k: dict(d=_f(a.fractions)) for k, a in m.aefacts.items()}
    v["SET1"] = {k: dict(g=sorted(s.ids)) for k, s in m.sets.items() if s.type == "SET1"}
    v["SPLINE2"] = {k: dict(caero=s.caero, id1=s.box1, id2=s.box2, setg=s.setg, dz=s.dz,
                            dtor=s.dtor, cid=s.cid, dthx=s.dthx, dthy=s.dthy, usage=s.usage)
                    for k, s in m.splines.items() if s.type == "SPLINE2"}
    v["AELIST"] = {k: dict(e=sorted(a.elements)) for k, a in m.aelists.items()}
    v["AESTAT"] = {k: dict(label=a.label) for k, a in m.aestats.items()}
    v["AESURF"] = {k: dict(label=a.label, cid1=a.cid1, alid1=a.aelist_id1, cid2=a.cid2,
                           alid2=a.aelist_id2, eff=a.eff) for k, a in m.aesurf.items()}
    # RHOREF is sbeam's pseudo-label, not a trim variable (#87)
    v["TRIM"] = {k: dict(mach=t.mach, q=t.q, vars=sorted(
        (lbl, ux) for lbl, ux in zip(t.labels, _f(t.uxs)) if lbl != "RHOREF"))
                 for k, t in m.trims.items()}
    v["TABLED1"] = {k: dict(x=_f(t.x), y=_f(t.y))
                    for k, t in m.tables_d.items() if t.type == "TABLED1"}
    v["DIVERG"] = {k: dict(nroots=d.nroots, machs=_f(d.machs)) for k, d in m.divergs.items()}
    spcs = set()
    for sid, L in m.spcs.items():
        for c in L:
            if c.type == "SPC":
                for g, cc, d in zip(c.nodes, c.components, c.enforced):
                    spcs |= {(sid, g, ch, float(d)) for ch in str(cc)}
            elif c.type == "SPC1":
                spcs |= {(sid, g, ch, 0.0) for g in c.nodes for ch in str(c.components)}
    v["SPC"] = {"all": dict(v=sorted(spcs))}
    v["SUPORT"] = {"all": dict(v=sorted((g, str(c)) for s in m.suport
                                        for g, c in zip(s.nodes, s.Cs)))}
    return v


def _blank(x: Any) -> bool:
    x = _f(x)
    if isinstance(x, list):
        return all(_blank(y) for y in x)
    return x in (None, "", 0, 0.0)


def _rbar_dependent_as_assumed(e: Any) -> bool:
    """sbeam makes the complement of CNA (at A) and CNB (at B) dependent; MSC does that
    only when CMA and CMB are both blank, else exactly CMA/CMB (QRG p.2691–2692 remark 4)."""
    def comp(c: Any) -> set[str]:
        return set("123456") - set(str(c or ""))
    cma, cmb = str(e.cma or "").strip("0"), str(e.cmb or "").strip("0")
    if not cma and not cmb:
        return True
    return set(cma) == comp(e.cna) and set(cmb) == comp(e.cnb)


#: Values pyNastran stores that sbeam does not read: on a card sbeam accepted, each must
#: be what sbeam assumes.  (card, check, what sbeam would have dropped)
_UNREAD: list[tuple[str, Callable[[Any], bool], str]] = [
    ("CBAR", lambda e: _blank(e.wa) and _blank(e.wb), "offsets W1A-W3B"),
    ("CBAR", lambda e: _blank(e.g0), "orientation grid G0"),
    ("CBUSH", lambda e: _blank(e.g0), "orientation grid GO"),
    ("CBUSH", lambda e: e.ocid in (None, -1), "spring offset OCID"),
    ("CBUSH", lambda e: e.s in (None, 0.5), "spring location S"),
    ("PBAR", lambda p: _blank(p.i12), "I12"),
    # pyNastran 1.4.1 stores a blank K1/K2 as 1e8 (NASTRAN: infinite)
    ("PBAR", lambda p: all(k is None or k >= 1.0e8 for k in (p.k1, p.k2)), "K1/K2"),
    ("RBAR", _rbar_dependent_as_assumed, "CMA/CMB"),
    ("RBE2", lambda e: _blank(e.alpha), "ALPHA"),
    ("PBUSH", lambda p: _blank(p.Bi), "B (damping)"),
    ("PBUSH", lambda p: _blank(p.GEi), "GE (structural damping)"),
]


def _eq(a: Any, b: Any) -> bool:
    a, b = _f(a), _f(b)
    if a in (None, "", 0) and b in (None, "", 0):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, str) or isinstance(b, str):
        return str(a).strip().upper() == str(b).strip().upper()
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    return a == b


def _diffs(deck: Path, tmp: Path) -> tuple[list[str], set[str]]:
    lines = _bulk_lines(deck)
    sb = _sbeam_view(_read_cards(lines))
    model, failed = _pynastran(lines, tmp)
    pn = _pyn_view(model)
    out: list[str] = []
    for card, rows in sb.items():
        if card in failed:
            continue                                   # judged by the extension test
        for key, fields in rows.items():
            other = pn.get(card, {}).get(key)
            if other is None:
                if fields != {"v": []}:
                    out.append(f"{card} {key}: read by sbeam, not by pyNastran")
                continue
            for name, value in fields.items():
                if (card, name) in _KNOWN:
                    continue
                if not _eq(value, other.get(name)):
                    out.append(f"{card} {key}.{name}: sbeam {value!r} != pyNastran "
                               f"{other.get(name)!r}")
    for card, ok, what in _UNREAD:
        source = {"PBAR": model.properties, "PBUSH": model.properties,
                  "RBAR": model.rigid_elements, "RBE2": model.rigid_elements}.get(
                      card, model.elements)
        for key, obj in source.items():
            if obj.type == card and not ok(obj):
                out.append(f"{card} {key}: sbeam accepted it but does not read its {what}")
    return out, failed


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def test_enough_decks_are_compared():
    assert len(PARSEABLE) >= 50


@pytest.mark.parametrize("deck", PARSEABLE, ids=lambda p: p.name)
def test_repo_deck_fields_agree_with_pynastran(deck, tmp_path):
    diffs, failed = _diffs(deck, tmp_path)
    assert not diffs, "\n".join(diffs)
    unexplained = failed - set(_SBEAM_EXTENSIONS)
    assert not unexplained, f"pyNastran could not parse {sorted(unexplained)}"


def test_known_disagreements_still_exist(tmp_path):
    """A _KNOWN entry whose issue is fixed must be removed (it would hide a regression)."""
    seen = set()
    for i, deck in enumerate(PARSEABLE):
        sub = tmp_path / str(i)
        sub.mkdir()
        lines = _bulk_lines(deck)
        sb = _sbeam_view(_read_cards(lines))
        pn = _pyn_view(_pynastran(lines, sub)[0])
        for card, name in _KNOWN:
            for key, fields in sb.get(card, {}).items():
                other = pn.get(card, {}).get(key)
                if other is not None and not _eq(fields[name], other.get(name)):
                    seen.add((card, name))
    assert seen == set(_KNOWN), f"stale _KNOWN entries: {set(_KNOWN) - seen}"


# ---------------------------------------------------------------------------
# crafted cards (the audit's probes)
# ---------------------------------------------------------------------------

_GRIDS = ["GRID,1,,0.,0.,0.", "GRID,2,,1.,0.,0.", "GRID,13,,0.,1.,0.",
          "MAT1,1,1.e7,4.e6,.3", "PBAR,1,1,1.,1.,1.,1."]


def _crafted(lines: list[str], tmp: Path) -> list[str]:
    deck = tmp / "crafted.bdf"
    deck.write_text("SOL 101\nCEND\nSUBCASE 1\nBEGIN BULK\n" + "\n".join(lines) + "\nENDDATA\n")
    return _diffs(deck, tmp)[0]


@pytest.mark.parametrize("lines", [
    ["CONM2,1,2,,10.,0.,0.,0.,,1.,0.,2.,0.,0.,3."],                       # #64 overflow
    ["CBAR,1,1,1,2,0.,1.,0.,,56,56"],                                     # #64 pin flags
    ["LOAD,10,1.,1.,1,1.,2,1.,3,+L1", "+L1,1.,4,1.,5,1.,6,1.,7", "+,1.,8",  # #63/#64
     *(f"FORCE,{i},1,0,1.,1.,0.,0." for i in range(1, 9))],
    ["PBUSH,7,K,1.,2.", "+,,RCV,1.,1."],                                  # #63 flags
    ["GRID*,20,,1.0,-2.0,*G", "*G,3.0,,136"],                              # #64 large field
    ["SPC1,100,12456,1,2,13"],
    ["DIVERG,70,2,.5,.8,.9"],                                             # #73 QRG p.1603
    ["DIVERG     100      5       0.0"],                                  # #73 AAUG p.148
    ["PBUSH,7,K,1.,2.,3.", "CBUSH,4,7,1,2,0.,1.,0."],                      # #62 vector
    ["PBUSH,7,K,1.,2.,3.", "CBUSH,4,7,1,,,,,0"],                           # #62 QRG example 2
    ["PBUSH,7,K,1.,2.,3.", "CBUSH,4,7,1,2,,,,6",                           # #62 CID, field 9
     "CORD2R,6,0,0.,0.,0.,0.,0.,1.", "+,0.,1.,0."],
    ["PBUSH,7,K,1.,2.,3.", "CBUSH,7,,1,2,0.,1.,0.", "+,0.5,-1"],            # #62 PID, S, OCID
    ["CBAR,1,,1,2,0.,1.,0.,BGG"],                                         # #67 PID, OFFT
], ids=["conm2-overflow", "cbar-pins", "load-3-lines", "pbush-flags", "grid-large", "spc1",
        "diverg-qrg", "diverg-aaug", "cbush-vector", "cbush-grounded-cid0", "cbush-cid",
        "cbush-defaults", "cbar-pid-offt"])
def test_crafted_cards_agree(lines, tmp_path):
    assert _crafted(_GRIDS + lines, tmp_path) == []


@pytest.mark.parametrize("lines, match", [
    (["CBAR,1,1,1,2,13,0,0"], "reads as the grid G0"),                    # #67
    (["CBAR,1,1,1,2,0.,1.,0.", "+,,,0.,0.,5.,0.,0.,5."], "offset W3A"),    # #67
    (["RBAR,5,1,2,123456,,,123"], "partial set of dependent DOFs"),       # #68
    (["PBUSH,7,K,1.", "CBUSH,4,7,1,2,13"], "reads as the grid GO"),        # #62
    (["PBUSH,7,K,1.", "CBUSH,4,7,1,2,0.,1.,0.", "+,0.25,10,0.,1.,1."], "S=0.25"),   # #62
], ids=["cbar-g0-zeros", "cbar-offsets", "rbar-cmb", "cbush-go", "cbush-offset"])
def test_cards_pynastran_reads_and_sbeam_cannot_honour_are_refused(lines, match, tmp_path):
    """pyNastran stores a value here that sbeam has no model for.  These were silent
    disagreements (the audit's probes); sbeam now refuses the card."""
    deck = tmp_path / "crafted.bdf"
    deck.write_text("SOL 101\nCEND\nSUBCASE 1\nBEGIN BULK\n" + "\n".join(_GRIDS + lines)
                    + "\nENDDATA\n")
    _model, failed = _pynastran(_GRIDS + lines, tmp_path)
    assert not failed, f"pyNastran could not parse {sorted(failed)}"
    with pytest.raises(ValueError, match=match):
        parse_bdf(deck)


# ---------------------------------------------------------------------------
# file structure: pyNastran reads each multi-file deck itself (#81)
# ---------------------------------------------------------------------------

MULTI_FILE = [d for d in PARSEABLE if parse_bdf(d)[0].includes]


def _for_pynastran(src: Path, dst: Path) -> None:
    """Copy a deck without the cards pyNastran raises on; CEND after SOL for a driver."""
    out = []
    for line in src.read_text().splitlines():
        body = line.split("$", 1)[0].strip()
        if body and split_line(body)[0].upper() in _NOT_FOR_PYNASTRAN:
            continue
        out.append(line)
        if body.upper().startswith("SOL "):
            out.append("CEND")
    dst.write_text("\n".join(out) + "\n")


def test_enough_multi_file_decks():
    assert len(MULTI_FILE) >= 6


@pytest.mark.parametrize("deck", MULTI_FILE, ids=lambda p: p.name)
def test_multi_file_deck_reads_the_same_model_in_pynastran(deck, tmp_path):
    """INCLUDE placement and ENDDATA as NASTRAN reads them (QRG p.465, p.1808).

    Before #81 the drivers INCLUDEd their bulk above BEGIN BULK and the included bulk
    ended in ENDDATA: pyNastran found no grids, and stopped before any overlay.
    """
    cc, bulk = parse_bdf(deck)
    for name in cc.includes:
        _for_pynastran(deck.parent / name, tmp_path / name)
    _for_pynastran(deck, tmp_path / deck.name)
    model = BDF(debug=None)
    model.set_error_storage(nparse_errors=10000, stop_on_parsing_error=False)
    model.read_bdf(str(tmp_path / deck.name), xref=False, validate=False)
    assert sorted(model.nodes) == sorted(bulk.grids)
    assert sorted(model.caeros) == sorted(bulk.caero1s)
    assert sorted(model.masses) == sorted(bulk.conm2s)
    assert sorted(k for k, e in model.elements.items() if e.type == "CBAR") == sorted(bulk.cbars)
