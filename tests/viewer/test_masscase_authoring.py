"""MASSCASE authored in the viewer (#115).

The target is ``ha144a_massset_sweep.bdf``, written by hand: its header gives the three
weights, and its trim results are what a deck authored in the viewer must reproduce.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from sbeam.gpwg import compute_gpwg
from sbeam.model.card_writers import write_masscase
from sbeam.model.mass import Massset
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from tests.samples import sample_path
from tests.viewer.journey_helpers import _open, _submit, differences

SWEEP = sample_path("ha144a_massset_sweep.bdf")
# Weights stated in the deck's header, lb.
HEADER_WEIGHTS = {10: 16000.0, 20: 18500.0, 30: 21000.0}


def _sbeam_app():
    from sbeam_tools.viewer.app import main
    main()


def _without_mass_cases(sids: set[int]) -> str:
    """The sweep deck with the named MASSCASE cards and their selectors taken out."""
    out: list[str] = []
    dropping = False
    for line in SWEEP.read_text().splitlines():
        head = re.match(r"MASSCASE\s*,\s*(\d+)", line)
        if head:
            dropping = int(head.group(1)) in sids
        elif dropping and not line.startswith("+"):
            dropping = False
        selector = re.match(r"\s+MASSCASE\s*=\s*(\d+)", line)
        if dropping or (selector and int(selector.group(1)) in sids):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def _open_path(path: Path) -> AppTest:
    at = AppTest.from_function(_sbeam_app, default_timeout=300)
    at.run()
    at.text_input(key="deck_path_input").set_value(str(path))
    at.button(key="open_deck").click()
    at.run()
    assert at.session_state["_parse_error"] is None, at.session_state["_parse_error"]
    return at


def _author(at: AppTest, sid: int, label: str, add=(), delete=()) -> None:
    at.number_input(key="auth_masscase_sid").set_value(sid)
    at.text_input(key="auth_masscase_label").set_value(label)
    at.multiselect(key="auth_masscase_add").set_value(list(add))
    at.multiselect(key="auth_masscase_delete").set_value(list(delete))
    _submit(at, "auth_form_masscase")
    assert not at.error, [e.value for e in at.error]


def _run(at: AppTest) -> dict:
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    return at.session_state["sol144_result"]


def test_the_header_weights_are_the_mass_cases():
    """The independent numbers: 16000, 18500 and 21000 lb, from the deck's own header.

    The header rounds the empty weight to the pound (the model's is 15998.7 lb), so the
    ratios hold to 1e-4.  The fuel increments are exact: 2500 lb is half of 5000 lb.
    """
    _, bulk = parse_bdf(SWEEP)
    mass = {sid: compute_gpwg(bulk, sid).total_mass for sid in HEADER_WEIGHTS}
    for sid, weight in HEADER_WEIGHTS.items():
        assert mass[sid] / mass[10] == pytest.approx(weight / HEADER_WEIGHTS[10], rel=1e-4)
    assert (mass[20] - mass[10]) / (mass[30] - mass[10]) == pytest.approx(0.5, rel=1e-9)


def test_mass_cases_authored_in_the_viewer_reproduce_the_hand_written_deck(tmp_path):
    """MASSCASE 10 and 20 are removed from the deck and authored through the form;
    the export has the original's cards and the run has the original's trim."""
    deck = tmp_path / "sweep_without_10_20.bdf"
    deck.write_text(_without_mass_cases({10, 20}))
    cc_orig, bulk_orig = parse_bdf(SWEEP)
    _, stripped = parse_bdf(deck)
    assert sorted(stripped.masssets) == [30]
    # without their MASSCASE, the fuel CONM2s of case 20 sit in the baseline
    assert compute_gpwg(stripped).total_mass > compute_gpwg(bulk_orig).total_mass

    at = _open_path(deck)
    _author(at, 10, "EMPTY", delete=[5000])
    _author(at, 20, "HALFFUEL", add=[6001, 6002, 6003, 6004])
    bulk = at.session_state["bulk_data"]
    for sid in (10, 20, 30):
        assert differences(bulk_orig.masssets[sid], bulk.masssets[sid], f"MASSCASE {sid}") == []
    assert at.session_state["authored_cards"] == {"masscase": {10, 20}}

    # select them in the subcases, as the original does
    at.checkbox(key="cc_show_editor").check()
    at.run()
    at.selectbox(key="sc_massset_sid_0").set_value(10)
    at.selectbox(key="sc_massset_sid_1").set_value(20)
    _submit(at, "cc_form")
    cc = at.session_state["case_control"]
    assert [sc.massset_sid for sc in cc.subcases] == [10, 20, 30]

    # the export parses to the original's mass cases and selectors
    text = [c.value for c in at.code if "BEGIN BULK" in c.value][-1]
    cc_out, bulk_out = parse_bdf(deck.with_name("exported.bdf"), text=text)
    assert differences(bulk_orig.masssets, bulk_out.masssets, "masssets") == []
    assert [sc.massset_sid for sc in cc_out.subcases] == [sc.massset_sid for sc in cc_orig.subcases]
    assert bulk_out.overlay_conm2_eids == bulk_orig.overlay_conm2_eids

    # and the run gives the original deck's trim, subcase by subcase
    authored = _run(at)
    original = _run(_open("ha144a/ha144a_massset_sweep.bdf"))
    assert sorted(authored) == sorted(original) == [1, 2, 3]
    for sc_id in original:
        for label, value in original[sc_id].trim_vars.items():
            assert authored[sc_id].trim_vars[label] == pytest.approx(value, rel=1e-12, abs=1e-14)
    # the three trims differ, so the comparison is not vacuous
    alphas = [original[i].trim_vars["ANGLEA"] for i in (1, 2, 3)]
    assert alphas[0] < alphas[1] < alphas[2]


def test_the_mass_summary_shows_each_case():
    at = _open("ha144a/ha144a_massset_sweep.bdf")
    bulk = at.session_state["bulk_data"]
    table = next(d.value for d in at.dataframe
                 if {"Case", "Card", "Mass", "CG x"} <= set(map(str, d.value.columns)))
    assert list(table["Case"]) == ["baseline", "10", "20", "30"]
    assert list(table["Label"]) == ["BASELINE", "EMPTY", "HALFFUEL", "FULLFUEL"]
    assert table["Mass"].tolist() == pytest.approx(
        [compute_gpwg(bulk, sid).total_mass for sid in (None, 10, 20, 30)])
    ratio = table["Mass"].iloc[3] / table["Mass"].iloc[1]
    assert ratio == pytest.approx(HEADER_WEIGHTS[30] / HEADER_WEIGHTS[10], rel=1e-4)


def test_the_parsers_baseline_overlay_rule_reaches_the_form():
    """CONM2 5000 is a baseline mass (case 10 deletes it), so it cannot also be an overlay."""
    at = _open("ha144a/ha144a_massset_sweep.bdf")
    before = at.session_state["bulk_data"]
    at.number_input(key="auth_masscase_sid").set_value(40)
    at.multiselect(key="auth_masscase_add").set_value([5000])
    _submit(at, "auth_form_masscase")
    assert any("named as an overlay" in e.value and "5000" in e.value for e in at.error)
    assert at.session_state["bulk_data"] is before


def test_an_msc_mass_combination_is_listed_but_not_opened():
    """``MASSSET`` (MSC, #102) is another card: shown in the summary, not in the form."""
    at = _open("ha144a/ha144a_mass_combination_sweep.bdf")
    bulk = at.session_state["bulk_data"]
    msc = sorted(sid for sid, case in bulk.masssets.items() if case.msc)
    assert msc
    table = next(d.value for d in at.dataframe
                 if {"Case", "Card", "Mass"} <= set(map(str, d.value.columns)))
    assert set(table["Card"][1:]) == {"MASSSET (MSC)"}
    assert at.selectbox(key="auth_sel_masscase").options == ["— new —"]
    with pytest.raises(ValueError, match="MSC MASSSET combination"):
        write_masscase(bulk.masssets[msc[0]])


def test_writer_rows_and_default_label():
    case = Massset(sid=7, label="MASSCASE 7", scale=0.5, add=list(range(1, 10)),
                   replace=[(20, 21), (22, 23), (24, 25), (26, 27)], delete=[30])
    lines = write_masscase(case)
    assert lines == [
        "MASSCASE, 7, , 0.500000",
        "+, ADD, 1, 2, 3, 4, 5, 6, 7", "+, ADD, 8, 9",
        "+, REPLACE, 20, 21, 22, 23, 24, 25", "+, REPLACE, 26, 27",
        "+, DELETE, 30",
    ]
    conm2s = [f"CONM2, {eid}, 1, , 1.0" for eid in (*case.add, *(e for p in case.replace for e in p), *case.delete)]
    back = parse_bulk_data(["GRID, 1, , 0., 0., 0.", *conm2s, *lines]).masssets[7]
    assert differences(case, back, "MASSCASE 7") == []
