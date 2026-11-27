"""Phase G0 B1 — sbeam transient maneuver-loads card parsing (round-trip echo).

Verifies the MANVR / MANTRIM / MANTIME / MANCMD / MANPRNT / TABLED1 family
parses into the expected dataclasses, that cross-references resolve, and that
malformed decks raise.  The TABLED1.evaluate interpolation contract is also
checked here since the transient solver depends on it.
"""


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
TRIM,50,0.5,1.5,URDD3,-80.435,PITCH,0.0,,URDD5,0.0
TABLED1,200,LINEAR,LINEAR,
+,0.0,0.0,0.5,0.1,1.0,0.1,ENDT
TABLED1,201,,,
+,0.0,0.0,2.0,5.0,ENDT
MANTIME,300,0.0,1.0,0.01,0.05
MANCMD,400,ELEV,200
MANCMD,401,ELEV,200,ANGLEA,201
MANPRNT,500,STATE,CONTROL,LOADS
MANTRIM,600,50
MANVR,700,600,300,400,500,4
"""
# MANVR 700 selects the modal (free-flight, Step 63) solver via NMODES=4, so
# its MANCMD 400 may command AESURF controls only; MANCMD 401 keeps the
# mixed AESTAT+AESURF command list (legal for the direct solver) for the
# round-trip test without being referenced by a modal MANVR.


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
    # linear extrapolation from the end points (QRG 2024.1 PDF p.2897 remark 6; #70)
    assert t.evaluate(-1.0) == pytest.approx(-2.5)
    assert t.evaluate(10.0) == pytest.approx(25.0)


def test_mldtime_roundtrip():
    mt = _parse(_DECK).mldtimes[300]
    assert (mt.t0, mt.tend, mt.dt, mt.tout) == (0.0, 1.0, 0.01, 0.05)


def test_mldcomd_roundtrip():
    mc = _parse(_DECK).mldcomds[401]
    assert mc.commands == [("ELEV", 200), ("ANGLEA", 201)]


def test_modal_mloads_rejects_rigid_state_command():
    """Step 63: a modal MANVR whose MANCMD commands an AESTAT (rigid-state)
    label fails at parse; the same command set is legal for the direct solver."""
    deck = _DECK.replace("MANVR,700,600,300,400,500,4",
                         "MANVR,700,600,300,401,500,4")
    with pytest.raises(ValueError, match="ANGLEA"):
        _parse(deck)
    direct = _DECK.replace("MANVR,700,600,300,400,500,4",
                           "MANVR,700,600,300,401,500")
    assert _parse(direct).mloads[700].selects_modal is False


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
        "  MANVR = 700",
        "BEGIN BULK",
    ])
    assert cc.subcases[0].mloads_sid == 700


# ---- cross-reference + validation failures -------------------------------

def test_mldcomd_bad_label_raises():
    deck = _DECK.replace("MANCMD,401,ELEV,200,ANGLEA,201",
                         "MANCMD,401,NOPE,200")
    with pytest.raises(ValueError, match="not defined in any"):
        _parse(deck)


def test_mldcomd_bad_tabid_raises():
    deck = _DECK.replace("MANCMD,401,ELEV,200,ANGLEA,201",
                         "MANCMD,401,ELEV,999")
    with pytest.raises(ValueError, match="TABID 999 not found"):
        _parse(deck)


def test_mldtrim_bad_trim_raises():
    deck = _DECK.replace("MANTRIM,600,50", "MANTRIM,600,51")
    with pytest.raises(ValueError, match="TRIMID 51 not found"):
        _parse(deck)


def test_mloads_bad_mldtime_raises():
    deck = _DECK.replace("MANVR,700,600,300,400,500,4",
                         "MANVR,700,600,301,400,500,4")
    with pytest.raises(ValueError, match="MANTIME 301 not found"):
        _parse(deck)


def test_mldtime_bad_window_raises():
    deck = _DECK.replace("MANTIME,300,0.0,1.0,0.01,0.05",
                         "MANTIME,300,1.0,0.0,0.01,0.05")
    with pytest.raises(ValueError, match="TEND must exceed T0"):
        _parse(deck)


def test_tabled1_nonmonotonic_raises():
    deck = _DECK.replace("+,0.0,0.0,0.5,0.1,1.0,0.1,ENDT",
                         "+,0.0,0.0,0.5,0.1,0.4,0.1,ENDT")
    with pytest.raises(ValueError, match="strictly increasing"):
        _parse(deck)


# ---------------------------------------------------------------------------
# Step 61 — MANVR METHOD / ZETA (free-free modal basis configuration)
# ---------------------------------------------------------------------------

def test_mloads_method_and_zeta_default_to_off():
    """The pre-Step-61 six-field card still parses, with the new fields off."""
    bulk = _parse(_DECK)
    ml = bulk.mloads[700]
    assert ml.nmodes == 4
    assert ml.method == 0
    assert ml.zeta == 0.0


def test_mloads_method_and_zeta_roundtrip():
    deck = _DECK.replace("MANVR,700,600,300,400,500,4",
                         "EIGRL,900,,,20\nMANVR,700,600,300,400,500,4,900,0.02")
    ml = _parse(deck).mloads[700]
    assert ml.nmodes == 4
    assert ml.method == 900
    assert ml.zeta == pytest.approx(0.02)


def test_mloads_unknown_method_raises():
    deck = _DECK.replace("MANVR,700,600,300,400,500,4",
                         "MANVR,700,600,300,400,500,4,999")
    with pytest.raises(ValueError, match="METHOD 999 not found"):
        _parse(deck)


def test_mloads_negative_zeta_raises():
    deck = _DECK.replace("MANVR,700,600,300,400,500,4",
                         "MANVR,700,600,300,400,500,4,0,-0.1")
    with pytest.raises(ValueError, match="ZETA"):
        _parse(deck)


# ---------------------------------------------------------------------------
# Freestream density: MANTRIM field 4 (#87; a TRIM RHOREF pseudo-label until then)
# ---------------------------------------------------------------------------

def test_mantrim_rho_gives_the_velocity():
    deck = _DECK.replace("MANTRIM,600,50", "MANTRIM,600,50,0.5")
    bulk = _parse(deck)
    assert bulk.mldtrims[600].rho == pytest.approx(0.5)
    # V = sqrt(2q/rho) = sqrt(2*1.5/0.5)
    assert bulk.mldtrims[600].velocity(bulk.trims[50].q) == pytest.approx((2 * 1.5 / 0.5) ** 0.5)


def test_mantrim_without_rho_has_no_velocity():
    mt = _parse(_DECK).mldtrims[600]
    assert mt.rho == 0.0
    with pytest.raises(ValueError, match="MANTRIM 600: .* RHO"):
        mt.velocity(1.5)


def test_mantrim_negative_rho_raises():
    with pytest.raises(ValueError, match="RHO must be positive"):
        _parse(_DECK.replace("MANTRIM,600,50", "MANTRIM,600,50,-1.0"))


def test_trim_rhoref_label_is_refused():
    """#87: MSC's TRIM has no density; the old pseudo-label names its new home."""
    deck = _DECK.replace("TRIM,50,0.5,1.5,", "TRIM,50,0.5,1.5,RHOREF,0.5,")
    with pytest.raises(ValueError, match="RHOREF is not a TRIM label .* MANTRIM"):
        _parse(deck)


@pytest.mark.parametrize("old, new", [
    ("MANVR", "MLOADS"), ("MANTRIM", "MLDTRIM"), ("MANTIME", "MLDTIME"),
    ("MANCMD", "MLDCOMD"), ("MANPRNT", "MLDPRNT")])
def test_old_zaero_names_are_refused(old, new):
    """#87: the ZAERO names sbeam borrowed are refused, naming sbeam's card."""
    with pytest.raises(ValueError, match=rf"{new} x\d .*now {old}"):
        _parse(_DECK.replace(f"{old},", f"{new},"))


def test_mantime_unread_field_is_refused():
    """ZAERO's MLDTIME has PRINT and METHOD in fields 7-8; MANTIME reads neither."""
    with pytest.raises(ValueError, match="MANTIME 300: field 7"):
        _parse(_DECK.replace("MANTIME,300,0.0,1.0,0.01,0.05", "MANTIME,300,0.0,1.0,0.01,0.05,-1"))


def test_aestat_named_rhoref_is_rejected():
    deck = _DECK.replace("AESTAT,1,ANGLEA", "AESTAT,1,ANGLEA\nAESTAT,5,RHOREF")
    with pytest.raises(ValueError, match="RHOREF"):
        _parse(deck)
