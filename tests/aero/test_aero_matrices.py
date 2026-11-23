"""#104 — MSC's DMIJ W2GJ / DMIK WKK read onto the native per-CAERO1 corrections.

MSC enters W2GJ and WKK as matrices on aero box IDs (AAUG 2023.1 PDF p.144; QRG 2024.1
PDF p.1617 DMIJ, p.1623 DMIK).  Benchmark: ``sample/ha144a_fullspan_dmij.bdf`` (the
full-span HA144A deck with its corrections in MSC's form) trims to the native deck's
numbers to round-off.  Everything the mapping cannot represent is refused.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_field import parse_real
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol144 import run_sol144_trim

SAMPLE = Path(__file__).resolve().parents[2] / "sample"
NATIVE, MATRIX = SAMPLE / "ha144a_fullspan_sbeam.bdf", SAMPLE / "ha144a_fullspan_dmij.bdf"


def _trim(deck: Path, subcase_id: int):
    _cc, bulk = parse_bdf(str(deck))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index, mach=0.9)
        sc = SubcaseControl(subcase_id=subcase_id, spc_sid=1, trim_sid=subcase_id)
        return run_sol144_trim(bulk, sc, aero)


@pytest.mark.parametrize("subcase_id", [1, 2])
def test_matrix_deck_trims_as_the_native_deck(subcase_id):
    """The benchmark: q = 40 and 1200 psf, same trim and deflection to round-off."""
    native, matrix = _trim(NATIVE, subcase_id), _trim(MATRIX, subcase_id)
    assert matrix.trim_vars.keys() == native.trim_vars.keys()
    for label, value in native.trim_vars.items():
        assert matrix.trim_vars[label] == pytest.approx(value, rel=1e-12, abs=1e-15), label
    np.testing.assert_allclose(matrix.displacements, native.displacements,
                               rtol=1e-12, atol=1e-15)
    # and the 0.1 deg incidence is acting: ANGLEA is the published 0.169 rad (q = 40)
    if subcase_id == 1:
        assert matrix.trim_vars["ANGLEA"] == pytest.approx(0.1692, abs=5e-4)


def test_matrix_deck_maps_onto_the_native_cards():
    _cc, native = parse_bdf(str(NATIVE))
    _cc, matrix = parse_bdf(str(MATRIX))
    assert matrix.w2gjs[1100].data == native.w2gjs[1].data
    assert matrix.w2gjs[2100].data == native.w2gjs[2].data
    assert set(matrix.w2gjs) == {1100, 2100}          # no terms on the canards
    assert {eid: len(w.data) for eid, w in matrix.wkks.items()} == \
        {1000: 8, 1100: 32, 2000: 8, 2100: 32}
    assert all(v == 1.0 for w in matrix.wkks.values() for v in w.data)


# ---------------------------------------------------------------- a non-trivial WKK

def _native_bulk_lines() -> list[str]:
    text = NATIVE.read_text()
    return text[text.index("BEGIN BULK"):].splitlines()


def _wing_weights() -> list[float]:
    return [1.0 + 0.01 * k for k in range(32)]      # non-uniform, boxes 1100–1131


def test_dmik_wkk_equals_the_native_wkk():
    """Per-box weights on one surface, others 1: the corrected operator is identical."""
    w = _wing_weights()
    native_card = ["WKK, 77, 1100"] + [
        "+, " + ", ".join(repr(v) for v in w[k:k + 8]) for k in range(0, 32, 8)]
    dmik = ["DMIK, WKK, 0, 1, 2, 0"]
    for first, n in ((1000, 8), (1100, 32), (2000, 8), (2100, 32)):
        for box in range(first, first + n):
            value = w[box - 1100] if first == 1100 else 1.0
            for c in (3, 5):
                dmik.append(f"DMIK, WKK, {box}, {c}, , {box}, {c}, {value!r}")
    lines = _native_bulk_lines()
    end = lines.index("ENDDATA")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        a = build_aero_model(parse_bulk_data(lines[:end] + native_card + ["ENDDATA"]), mach=0.9)
        b = build_aero_model(parse_bulk_data(lines[:end] + dmik + ["ENDDATA"]), mach=0.9)
    np.testing.assert_array_equal(a.ajj_inv_corr, b.ajj_inv_corr)


def test_an_omitted_wkk_term_is_zero():
    """MSC's matrix is what is entered: a box with no WKK term has weight 0, no lift."""
    lines = _native_bulk_lines()
    end = lines.index("ENDDATA")
    dmik = ["DMIK, WKK, 0, 1, 1, 0"] + [
        f"DMIK, WKK, {b}, {c}, , {b}, {c}, 1.0" for b in range(1100, 1132) for c in (3, 5)]
    bulk = parse_bulk_data(lines[:end] + dmik + ["ENDDATA"])
    assert bulk.wkks[1100].data == [1.0] * 32
    assert bulk.wkks[1000].data == [0.0] * 8 and bulk.wkks[2100].data == [0.0] * 32


# ---------------------------------------------------------------- reading and refusals

_PANEL = ["AEROS, 0, 0, 1.0, 2.0, 2.0", "PAERO1, 1", "CAERO1, 100, 1, 0, 2, 2, 0, 0, 1",
          "+, 0.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 1.0"]          # boxes 100–103
_W2GJ = ["DMIJ, W2GJ, 0, 9, 2, 0, , , 1", "DMIJ, W2GJ, 1, , , 101, 3, 2.5D-2"]


def test_w2gj_column_in_double_precision():
    """TIN 2 terms need a D exponent (QRG p.1619 remark 9)."""
    bulk = parse_bulk_data(_PANEL + _W2GJ)
    assert bulk.w2gjs[100].data == [0.0, 0.025, 0.0, 0.0]


def test_d_exponent_reals():
    assert parse_real("1.0D0") == 1.0 and parse_real("-1.5d-3") == -0.0015
    assert parse_real("2.5D+2") == 250.0


def test_continuation_rows_and_term_order():
    """Terms may come in any order and run on to continuation lines (remark 3)."""
    bulk = parse_bulk_data(_PANEL + [
        "DMIJ, W2GJ, 0, 2, 1, 0", "DMIJ, W2GJ, 1, , , 103, 3, 0.4", "+, 100, 3, 0.1, , 102, 3, 0.3"])
    assert bulk.w2gjs[100].data == [0.1, 0.0, 0.3, 0.4]


_HEAD_K = "DMIK, WKK, 0, 1, 1, 0"


@pytest.mark.parametrize("cards, match", [
    (["DMIJ, FA2J, 0, 2, 1, 0"], r"DMIJ FA2J: sbeam reads DMIJ only for MSC's reserved name W2GJ"),
    (["DMIK, WTFACT, 0, 1, 1, 0"], r"DMIK WTFACT: sbeam reads DMIK only .* WKK"),
    (["DMIJ, W2GJ, 0, 9, 3, 0, , , 1"], r"TIN=3; sbeam reads real matrices only"),
    (["DMIJ, W2GJ, 0, 9, 1, 0, 1, , 1"], r"POLAR=1 applies to complex terms only"),
    (["DMIJ, W2GJ, 0, 9, 1, 0, , 7, 1"], r"header: field 8 \('7'\) must be blank"),
    (["DMIJ, W2GJ, 0, 9, 1, 0, , , 1", "DMIJ, W2GJ, 0, 9, 1, 0, , , 1"], r"given twice"),
    (["DMIJ, W2GJ, 1, , , 101, 3, 0.1"], r"column entries but no header entry"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , , 101, 3, 0.1, 1.0"], r"Bi must be blank"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , 9, 101, 3, 0.1"], r"field 5 \('9'\) must be blank"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , , 101, 3, 0.1", "DMIJ, W2GJ, 1, , , 101, 3, 0.2"],
     r"row \(101, 3\) given twice"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , , 101, 3, 0.1", "DMIJ, W2GJ, 2, , , 102, 3, 0.1"],
     r"2 column\(s\). W2GJ is a single column"),
    (["DMIJ, W2GJ, 0, 1, 1, 0", "DMIJ, W2GJ, 1, , , 101, 3, 0.1"], r"IFO=1, .* single column"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , , 101, 5, 0.1"], r"component 5; a CAERO1 box has component 3"),
    ([_W2GJ[0], "DMIJ, W2GJ, 1, , , 104, 3, 0.1"], r"box 104 is not on any CAERO1"),
    ([_HEAD_K, "DMIK, WKK, 101, 3, , 102, 3, 0.5"], r"off-diagonal term"),
    ([_HEAD_K, "DMIK, WKK, 101, 3, , 101, 3, 1.1"], r"box 101 has force weight .* 1.1 and moment .* 0.0"),
    ([_HEAD_K, "DMIK, WKK, 101, 1, , 101, 1, 1.0"], r"component 1; a CAERO1 box has component 3 and 5"),
    (["DMIK, WKK, 0, 2, 1, 0"], r"IFO=2. WKK is a square matrix"),
    (_W2GJ + ["W2GJ, 9, 100, 0.0, 0.0, 0.0, 0.0"], r"DMIJ W2GJ and native W2GJ card\(s\) \(SID \[9\]\)"),
], ids=["FA2J", "WTFACT", "complex", "polar", "header-field-8", "two-headers", "no-header",
        "imaginary", "column-field-5", "term-twice", "two-columns", "W2GJ-square",
        "W2GJ-moment-DOF", "unknown-box", "WKK-off-diagonal", "WKK-force-only",
        "WKK-in-plane-DOF", "WKK-rectangular", "native-and-matrix"])
def test_refused(cards, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_PANEL + cards)


_STRIP = ["PSTRIP, 20", "CAERO1, 400, 20, 0, 2, 2, 0, 0, 1",
          "+, 0.0, 5.0, 0.0, 1.0, 0.0, 6.0, 0.0, 1.0"]


@pytest.mark.parametrize("card, match", [
    ("WKK, 5, 400, 0.0, 0.0, 0.0, 0.0", r"WKK 5: CAERO1 400 is a PSTRIP strip panel"),
    ("AECORR, 5, WT2, 400, 0.0, 0.1, 0.1, 0.1, 0.1", r"AECORR 5: CAERO1 400 is a PSTRIP"),
    ("DMIK, WKK, 0, 1, 1, 0", r"DMIK WKK: the model has PSTRIP strip panels"),
], ids=["native-WKK", "WT2", "DMIK"])
def test_strip_panel_corrections_are_refused(card, match):
    """WKK and WT2 scale the VLM operator; on a strip panel they changed nothing (#104)."""
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_PANEL + _STRIP + [card])
