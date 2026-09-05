"""P-SEC — round-trip parse and validation of the MONSECT section-cut card."""
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data

# Synthetic model shared with tests/parser/test_monitor.py: 3 grids on a spanwise
# line, one CORD2R, an AELIST-backed and a SET1-backed AECOMP.
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
AECOMP,WINGAERO,AELIST,200
AECOMP,WINGGRID,SET1,300
MONPNT3,MWING,FULL WING,123456,WINGGRID,0,1.5,0.0,0.0
MONSECT,SECRW,RIGHT WING,WINGGRID,0
+,0.0,5.0,10.0,15.0
MONSECT,SECAE,WING AERO CUT,WINGAERO,7,1,NEG,0.001
+,2.0,4.0
+,NORMAL,1.0,0.25,0.0
""".splitlines()


@pytest.fixture(scope="module")
def bulk():
    return parse_bulk_data(_BDF)


def test_monsect_defaults(bulk):
    """Omitted AXIS/SIDE/TOL fall back to the documented defaults (2/POS/auto)."""
    cut = bulk.monsects["SECRW"]
    assert cut.label == "RIGHT WING"
    assert cut.comp == "WINGGRID"
    assert cut.cid == 0
    assert cut.axis == 2           # CID y — the SPLINE2 spline-axis convention
    assert cut.side == "POS"
    assert cut.tol is None
    assert cut.stations == [0.0, 5.0, 10.0, 15.0]
    assert cut.normal is None


def test_monsect_explicit_fields_and_normal(bulk):
    cut = bulk.monsects["SECAE"]
    assert cut.comp == "WINGAERO"
    assert cut.cid == 7
    assert cut.axis == 1
    assert cut.side == "NEG"
    assert cut.tol == 0.001
    assert cut.stations == [2.0, 4.0]
    assert cut.normal == (1.0, 0.25, 0.0)


def test_stations_must_increase():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0", "+,0.0,5.0,3.0"]
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_bulk_data(bad)


def test_duplicate_station_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0", "+,0.0,5.0,5.0"]
    with pytest.raises(ValueError, match="strictly increasing"):
        parse_bulk_data(bad)


def test_no_stations_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0"]
    with pytest.raises(ValueError, match="at least one station"):
        parse_bulk_data(bad)


def test_missing_comp_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,NOPE,0", "+,1.0"]
    with pytest.raises(ValueError, match="not found in AECOMP"):
        parse_bulk_data(bad)


def test_missing_cid_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,99", "+,1.0"]
    with pytest.raises(ValueError, match="CID=99 not found"):
        parse_bulk_data(bad)


def test_bad_axis_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0,4", "+,1.0"]
    with pytest.raises(ValueError, match="AXIS must be 1, 2 or 3"):
        parse_bulk_data(bad)


def test_bad_side_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0,2,UP", "+,1.0"]
    with pytest.raises(ValueError, match="SIDE must be"):
        parse_bulk_data(bad)


def test_degenerate_normal_rejected():
    """A normal near-perpendicular to the station axis has no usable intercept."""
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0,2", "+,1.0", "+,NORMAL,1.0,0.05,0.0"]
    with pytest.raises(ValueError, match="no usable intercept"):
        parse_bulk_data(bad)


def test_zero_normal_rejected():
    bad = _BDF + ["MONSECT,SBAD,L,WINGGRID,0,2", "+,1.0", "+,NORMAL,0.0,0.0,0.0"]
    with pytest.raises(ValueError, match="zero-length"):
        parse_bulk_data(bad)


def test_name_collision_with_monpnt_rejected():
    """Monitor names are unique across MONPNT1/MONPNT3/MONSECT (one output namespace)."""
    bad = _BDF + ["MONSECT,MWING,L,WINGGRID,0", "+,1.0"]
    with pytest.raises(ValueError, match="collides with an existing MONPNT"):
        parse_bulk_data(bad)


def test_duplicate_monsect_name_rejected():
    bad = _BDF + ["MONSECT,SECRW,L,WINGGRID,0", "+,1.0"]
    with pytest.raises(ValueError, match="Duplicate MONSECT NAME"):
        parse_bulk_data(bad)
