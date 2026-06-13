"""Phase G0 B1 — ZAERO transient maneuver-loads card parsing (round-trip echo).

Verifies the MLOADS / MLDTRIM / MLDTIME / MLDCOMD / MLDPRNT / TABLED1 family
parses into the expected dataclasses, that cross-references resolve, and that
malformed decks raise.  The TABLED1.evaluate interpolation contract is also
checked here since the transient solver depends on it.
"""

import warnings

import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.parser.case_control import parse_case_control


# A minimal but complete maneuver deck (free-field), with the AESTAT/AESURF/TRIM
# scaffolding the maneuver cards cross-reference.
_DECK = """\
AEROS,0,0,10.0,40.0,400.0,1,0
AESTAT,1,ANGLEA
AESTAT,2,PITCH
AESTAT,3,URDD3
AESTAT,4,URDD5
AESURF,10,ELEV,0,100
AELIST,100,1,THRU,4
TRIM,50,0.5,1.5,URDD3,-80.435,PITCH,0.0,URDD5,0.0
TABLED1,200,LINEAR,LINEAR,
+,0.0,0.0,0.5,0.1,1.0,0.1,ENDT
TABLED1,201,,,
+,0.0,0.0,2.0,5.0,ENDT
MLDTIME,300,0.0,1.0,0.01,0.05
MLDCOMD,400,ELEV,200,ANGLEA,201
MLDPRNT,500,STATE,CONTROL,LOADS
MLDTRIM,600,50
MLOADS,700,600,300,400,500,4
"""


def _parse(deck):
    return parse_bulk_data(deck.splitlines())


def test_tabled1_roundtrip():
    bulk = _parse(_DECK)
    t = bulk.tabled1s[200]
    assert t.tid == 200
    assert t.xaxis == "LINEAR" and t.yaxis == "LINEAR"
    assert t.xs == [0.0, 0.5, 1.0]
    assert t.ys == [0.0, 0.1, 0.1]
    # default axes when blank
    assert bulk.tabled1s[201].xaxis == "LINEAR"


def test_tabled1_evaluate():
    bulk = _parse(_DECK)
    t = bulk.tabled1s[201]              # (0,0) -> (2,5), slope 2.5
    assert t.evaluate(1.0) == pytest.approx(2.5)
    # constant (held) extrapolation outside the range
    assert t.evaluate(-1.0) == pytest.approx(0.0)
    assert t.evaluate(10.0) == pytest.approx(5.0)


def test_mldtime_roundtrip():
    mt = _parse(_DECK).mldtimes[300]
    assert (mt.t0, mt.tend, mt.dt, mt.tout) == (0.0, 1.0, 0.01, 0.05)


def test_mldcomd_roundtrip():
    mc = _parse(_DECK).mldcomds[400]
    assert mc.commands == [("ELEV", 200), ("ANGLEA", 201)]


def test_mldprnt_roundtrip():
    mp = _parse(_DECK).mldprnts[500]
    assert mp.items == ["STATE", "CONTROL", "LOADS"]


def test_mldtrim_and_mloads_roundtrip():
    bulk = _parse(_DECK)
    assert bulk.mldtrims[600].trim_sid == 50
    ml = bulk.mloads[700]
    assert (ml.mldtrim, ml.mldtime, ml.mldcomd, ml.mldprnt, ml.nmodes) == (
        600, 300, 400, 500, 4
    )


def test_case_control_mloads_hook():
    cc = parse_case_control([
        "SOL 144",
        "SUBCASE 1",
        "  MLOADS = 700",
        "BEGIN BULK",
    ])
    assert cc.subcases[0].mloads_sid == 700


# ---- cross-reference + validation failures -------------------------------

def test_mldcomd_bad_label_raises():
    deck = _DECK.replace("MLDCOMD,400,ELEV,200,ANGLEA,201",
                         "MLDCOMD,400,NOPE,200")
    with pytest.raises(ValueError, match="not defined in any"):
        _parse(deck)


def test_mldcomd_bad_tabid_raises():
    deck = _DECK.replace("MLDCOMD,400,ELEV,200,ANGLEA,201",
                         "MLDCOMD,400,ELEV,999")
    with pytest.raises(ValueError, match="TABID 999 not found"):
        _parse(deck)


def test_mldtrim_bad_trim_raises():
    deck = _DECK.replace("MLDTRIM,600,50", "MLDTRIM,600,51")
    with pytest.raises(ValueError, match="TRIMID 51 not found"):
        _parse(deck)


def test_mloads_bad_mldtime_raises():
    deck = _DECK.replace("MLOADS,700,600,300,400,500,4",
                         "MLOADS,700,600,301,400,500,4")
    with pytest.raises(ValueError, match="MLDTIME 301 not found"):
        _parse(deck)


def test_mldtime_bad_window_raises():
    deck = _DECK.replace("MLDTIME,300,0.0,1.0,0.01,0.05",
                         "MLDTIME,300,1.0,0.0,0.01,0.05")
    with pytest.raises(ValueError, match="TEND must exceed T0"):
        _parse(deck)


def test_tabled1_nonmonotonic_raises():
    deck = _DECK.replace("+,0.0,0.0,0.5,0.1,1.0,0.1,ENDT",
                         "+,0.0,0.0,0.5,0.1,0.4,0.1,ENDT")
    with pytest.raises(ValueError, match="strictly increasing"):
        _parse(deck)
