"""MON1 — round-trip parse of MONPNT1/MONPNT3/AECOMP/AELIST cards."""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# Synthetic model: 3 grids, one CORD2R, a CAERO1 box range covered by an AELIST,
# one MONPNT1 (AECOMP -> AELIST), two MONPNT3 (AECOMP -> SET1), one in CID 0 and
# one in the user CORD2R.
_BDF = """\
GRID,100,,0.0,0.0,0.0
GRID,110,,0.0,10.0,0.0
GRID,120,,0.0,20.0,0.0
CORD2R,7,0,0.0,0.0,0.0,0.0,0.0,1.0
+,1.0,0.0,0.0
AEROS,0,0,10.0,40.0,400.0,1,0
PAERO1,1
CAERO1,1001,1,,4,2,,,0
+,0.0,0.0,0.0,10.0,0.0,20.0,0.0,10.0
AELIST,200,1001,THRU,1008
SET1,300,100,110,120
SET1,310,100
AECOMP,WINGAERO,AELIST,200
AECOMP,WINGGRID,SET1,300
AECOMP,ROOTGRID,SET1,310
MONPNT1,MWAERO,WING AERO,123456,WINGAERO,0,1.0,2.0,3.0
MONPNT3,MWING,FULL WING,123456,WINGGRID,0,1.5,0.0,0.0
MONPNT3,MROOT,WING ROOT,123,ROOTGRID,7,0.0,0.0,0.0
""".splitlines()


@pytest.fixture(scope="module")
def bulk():
    return parse_bulk_data(_BDF)


def test_aecomp_parsed(bulk):
    assert set(bulk.aecomps) == {"WINGAERO", "WINGGRID", "ROOTGRID"}
    assert bulk.aecomps["WINGAERO"].listtype == "AELIST"
    assert bulk.aecomps["WINGAERO"].list_ids == [200]
    assert bulk.aecomps["WINGGRID"].listtype == "SET1"
    assert bulk.aecomps["WINGGRID"].list_ids == [300]


def test_monpnt1_parsed(bulk):
    m = bulk.monpnt1s["MWAERO"]
    assert m.label == "WING AERO"
    assert m.axes == 123456
    assert m.comp == "WINGAERO"
    assert m.cp == 0
    assert (m.x, m.y, m.z) == (1.0, 2.0, 3.0)


def test_monpnt3_parsed_cid0(bulk):
    m = bulk.monpnt3s["MWING"]
    assert m.label == "FULL WING"
    assert m.axes == 123456
    assert m.comp == "WINGGRID"
    assert m.cp == 0
    assert (m.x, m.y, m.z) == (1.5, 0.0, 0.0)


def test_monpnt3_parsed_cord2r(bulk):
    m = bulk.monpnt3s["MROOT"]
    assert m.comp == "ROOTGRID"
    assert m.axes == 123
    assert m.cp == 7
    assert (m.x, m.y, m.z) == (0.0, 0.0, 0.0)


def test_monpnt1_bad_comp_type_rejected():
    bad = _BDF + ["MONPNT1,MBAD,LBL,123456,WINGGRID,0,0.0,0.0,0.0"]
    with pytest.raises(ValueError, match="must reference an AELIST"):
        parse_bulk_data(bad)


def test_monpnt3_missing_comp_rejected():
    bad = _BDF + ["MONPNT3,MBAD,LBL,123456,NOPE,0,0.0,0.0,0.0"]
    with pytest.raises(ValueError, match="not found in AECOMP"):
        parse_bulk_data(bad)


def test_aecomp_missing_list_rejected():
    bad = _BDF + ["AECOMP,DANGLE,SET1,999"]
    with pytest.raises(ValueError, match="SET1 SID 999 not found"):
        parse_bulk_data(bad)
