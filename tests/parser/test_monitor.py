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
MONPNT1 MWAERO  WING AERO
+, 123456, WINGAERO, 0, 1.0, 2.0, 3.0
MONPNT1 MWING   FULL WING
+, 123456, WINGGRID, 0, 1.5, 0.0, 0.0
MONPNT1 MROOT   WING ROOT
+, 123, ROOTGRID, 7, 0.0, 0.0, 0.0
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


def test_monpnt1_on_a_set1_aecomp_is_structural():
    """#86: MSC's MONPNT1 is aerodynamic or structural by its COMP (QRG p.2303 remark 2)."""
    bulk = parse_bulk_data(_BDF + ["MONPNT1,MSTR,LBL", "+,123456,WINGGRID,0,0.0,0.0,0.0"])
    assert "MSTR" in bulk.monpnt3s and "MSTR" not in bulk.monpnt1s


def test_monpnt1_missing_comp_rejected():
    bad = _BDF + ["MONPNT1,MBAD,LBL", "+,123456,NOPE,0,0.0,0.0,0.0"]
    with pytest.raises(ValueError, match="not found in AECOMP"):
        parse_bulk_data(bad)


def test_the_old_one_line_monpnt1_is_refused():
    bad = _BDF + ["MONPNT1,MBAD,LBL,123456,WINGAERO,0,0.0,0.0,0.0"]
    with pytest.raises(ValueError, match="MONPNT1 MBAD: the second line .* is missing.*#86"):
        parse_bulk_data(bad)


@pytest.mark.parametrize("lines", [
    ["MONPNT3,MBAD,LBL,123456,WINGGRID,0,0.0,0.0,0.0"],               # sbeam's old card
    ["MONPNT3,T0,Fuselage station 1105", "+,123456,1,2,0,30.0,,,ASM"],  # QRG p.2307 example
])
def test_monpnt3_is_refused(lines):
    with pytest.raises(ValueError, match="MONPNT3 .*: not supported.*grid point forces"):
        parse_bulk_data(_BDF + lines)


def test_qrg_example_label_spans_fields_3_to_9():
    """QRG p.2303 example, small field: LABEL keeps its spaces across field edges."""
    f8 = "".join
    lines = _BDF + [f8(f"{x:<8}" for x in ("MONPNT1", "WING155")) + "Wing Integrated Load to Butline 155",
                    f8(f"{x:<8}" for x in ("", "34", "WINGAERO", "", "0.0", "155.0", "15.0"))]
    m = parse_bulk_data(lines).monpnt1s["WING155"]
    assert (m.label, m.axes, m.comp, m.cp, m.y, m.z) == (
        "Wing Integrated Load to Butline 155", 34, "WINGAERO", 0, 155.0, 15.0)


def test_cd_other_than_cp_is_refused():
    bad = _BDF + ["MONPNT1,MBAD,LBL", "+,123456,WINGAERO,0,0.0,0.0,0.0,7"]
    with pytest.raises(ValueError, match="MONPNT1 MBAD: CD=7 differs from CP=0"):
        parse_bulk_data(bad)


def test_aecomp_missing_list_rejected():
    bad = _BDF + ["AECOMP,DANGLE,SET1,999"]
    with pytest.raises(ValueError, match="SET1 SID 999 not found"):
        parse_bulk_data(bad)
