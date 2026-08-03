"""P12 S1 — aeroelastic card serializers round-trip through the parser.

Every writer in ``sbeam/model/card_writers.py`` must produce text the parser
reads back into an equal dataclass (dataclass -> text -> parse -> ==), for
each of the 15 authoring families and for every family instance in the two
MLOADS sample decks.
"""

from pathlib import Path

import pytest

from sbeam.model.aero import (
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
)
from sbeam.model.constraint import Suport
from sbeam.model.maneuver import (
    Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads,
)
from sbeam.model import card_writers as cw
from sbeam.parser.bdf_reader import parse_bulk_data, parse_bdf

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"

# Scaffolding so cross-reference validation passes when parsing writer output.
_SCAFFOLD = [
    "AESTAT,1,ANGLEA",
    "AESTAT,2,PITCH",
    "AESTAT,3,URDD3",
    "AESTAT,4,URDD5",
    "AESURF,10,ELEV,0,100",
    "AELIST,100,1,THRU,4",
]


def _reparse(lines, scaffold=True):
    deck = (_SCAFFOLD if scaffold else []) + lines
    return parse_bulk_data(deck)


def test_aestat_roundtrip():
    a = Aestat(id=501, label="SIDES")
    assert _reparse(cw.write_aestat(a)).aestats[501] == a


def test_aesurf_roundtrip_defaults_omitted():
    a = Aesurf(id=505, label="AILERON", cid1=7, alid1=100)
    lines = cw.write_aesurf(a)
    assert len(lines) == 1 and lines[0].count(",") == 4   # trailing defaults dropped
    assert _reparse(lines).aesurfs[505] == a


def test_aesurf_roundtrip_full():
    a = Aesurf(id=505, label="RUDDER", cid1=7, alid1=100, cid2=8, alid2=100, eff=0.85)
    assert _reparse(cw.write_aesurf(a)).aesurfs[505] == a


def test_aelist_long_continuation():
    a = Aelist(sid=900, elements=list(range(1101, 1131)))   # 30 boxes -> continuations
    lines = cw.write_aelist(a)
    assert len(lines) > 1 and lines[1].startswith("+")
    assert _reparse(lines).aelists[900] == a


def test_suport_roundtrip():
    s = Suport(gid=90, dofs="35")
    assert _reparse(cw.write_suport(s)).supports == [s]


def test_trim_roundtrip_rhoref_and_negatives():
    t = Trim(sid=1, mach=0.9, q=40.0,
             vars={"PITCH": 0.0, "URDD3": -32.174, "URDD5": 0.0},
             rhoref=2.3769e-3)
    got = _reparse(cw.write_trim(t)).trims[1]
    assert got.vars == t.vars
    assert got.rhoref == pytest.approx(t.rhoref)
    assert (got.mach, got.q) == (t.mach, t.q)


def test_trim_roundtrip_no_rhoref():
    t = Trim(sid=2, mach=0.3, q=100.0, vars={"ANGLEA": 0.05})
    got = _reparse(cw.write_trim(t)).trims[2]
    assert got == t


def test_trimvar_roundtrip():
    v = Trimvar(id=3, label="ELEV", init=0.1, lb=-0.5, ub=0.5)
    assert _reparse(cw.write_trimvar(v)).trimvars[3] == v


def test_trimobj_roundtrip():
    o = Trimobj(sid=4, labels=["ELEV", "ANGLEA"], weights=[1.0, 0.25])
    assert _reparse(cw.write_trimobj(o)).trimobjs[4] == o


def test_trimcon_multicard_same_sid():
    cons = [Trimcon(sid=5, label="ELEV", sense="LE", rhs=0.4),
            Trimcon(sid=5, label="ELEV", sense="GE", rhs=-0.4)]
    lines = [ln for c in cons for ln in cw.write_trimcon(c)]
    assert _reparse(lines).trimcons[5] == cons


def test_diverg_roundtrip():
    d = Diverg(sid=6, nroots=2, rhoref=1.225, machs=[0.0, 0.5, 0.8])
    assert _reparse(cw.write_diverg(d)).divergs[6] == d


def test_tabled1_roundtrip_default_axes():
    t = Tabled1(tid=300, xs=[0.0, 0.2, 1.0], ys=[0.492457, 0.592457, 0.592457])
    lines = cw.write_tabled1(t)
    assert lines[0] == "TABLED1, 300"          # data must not sit on the base line
    assert lines[-1].endswith("ENDT")
    assert _reparse(lines).tabled1s[300] == t


def test_tabled1_long_table_continuations():
    xs = [i * 0.05 for i in range(21)]
    ys = [x * x for x in xs]
    t = Tabled1(tid=301, xs=xs, ys=ys)
    got = _reparse(cw.write_tabled1(t)).tabled1s[301]
    assert got.xs == pytest.approx(t.xs)
    assert got.ys == pytest.approx(t.ys)


def _maneuver_scaffold():
    return _SCAFFOLD + [
        "TRIM,50,0.5,1.5,RHOREF,1.1-3,URDD3,-80.435,PITCH,0.0",
        "TABLED1,200",
        "+,0.0,0.0,0.5,0.1,1.0,0.1,ENDT",
        "MLDTRIM,600,50",
        "MLDTIME,300,0.0,1.0,0.01,0.05",
        "MLDCOMD,400,ELEV,200",
        "MLDPRNT,500",
    ]


def test_mloads_roundtrip_trailing_defaults():
    m = Mloads(sid=700, mldtrim=600, mldtime=300)
    lines = cw.write_mloads(m)
    assert lines == ["MLOADS, 700, 600, 300"]
    got = parse_bulk_data(_maneuver_scaffold() + lines).mloads[700]
    assert got == m


def test_mloads_roundtrip_modal_fields():
    m = Mloads(sid=701, mldtrim=600, mldtime=300, mldcomd=400, mldprnt=500,
               nmodes=0, method=-1, zeta=0.02)
    got = parse_bulk_data(_maneuver_scaffold() + cw.write_mloads(m)).mloads[701]
    assert got == m and got.selects_modal


def test_mldtrim_mldtime_mldcomd_mldprnt_roundtrip():
    for card, writer, store in [
        (Mldtrim(sid=601, trim_sid=50), cw.write_mldtrim, "mldtrims"),
        (Mldtime(sid=301, t0=0.0, tend=2.0, dt=0.01, tout=0.1), cw.write_mldtime, "mldtimes"),
        (Mldcomd(sid=401, commands=[("ELEV", 200), ("ANGLEA", 200)]), cw.write_mldcomd, "mldcomds"),
        (Mldprnt(sid=501, items=["STATE", "LOADS"]), cw.write_mldprnt, "mldprnts"),
    ]:
        got = parse_bulk_data(_maneuver_scaffold() + writer(card))
        assert getattr(got, store)[card.sid] == card


# ---------------------------------------------------------------------------
# Golden round-trips: every family instance in the two MLOADS sample decks
# ---------------------------------------------------------------------------

_FAMILY_ATTRS = [a for a, _ in cw._FAMILIES.values()]


@pytest.mark.parametrize("deck", ["ha144a_fullspan_mloads.bdf",
                                  "ha144a_mloads_massset.bdf"])
def test_sample_deck_golden_roundtrip(deck):
    _, bulk = parse_bdf(SAMPLE_DIR / deck)
    lines: list[str] = []
    for family, (attr, writer) in cw._FAMILIES.items():
        store = getattr(bulk, attr)
        if family == "suport":
            lines += [ln for s in store for ln in writer(s)]
        elif family == "trimcon":
            lines += [ln for cons in store.values() for c in cons for ln in writer(c)]
        else:
            lines += [ln for card in store.values() for ln in writer(card)]
    reparsed = parse_bulk_data(lines)
    for attr in _FAMILY_ATTRS:
        assert getattr(reparsed, attr) == getattr(bulk, attr), attr


def test_write_authored_block_header_and_specials():
    bulk = parse_bulk_data(_maneuver_scaffold() + [
        "SUPORT,90,35",
        "TRIMCON,5,ELEV,LE,0.4",
        "TRIMCON,5,ELEV,GE,-0.4",
    ])
    authored = {"trim": {50}, "suport": {90}, "trimcon": {5}, "tabled1": {200}}
    block = cw.write_authored_block(bulk, authored, "authored by viewer\nP12")
    assert block.startswith("$ authored by viewer\n$ P12\n")
    reparsed = parse_bulk_data(_SCAFFOLD + block.splitlines())
    assert reparsed.trims[50] == bulk.trims[50]
    assert reparsed.supports == bulk.supports
    assert reparsed.trimcons[5] == bulk.trimcons[5]
    assert reparsed.tabled1s[200] == bulk.tabled1s[200]
    assert cw.write_authored_block(bulk, {}, "hdr") == ""
