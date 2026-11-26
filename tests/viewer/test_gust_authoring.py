"""Gust cases in the viewer: the GUSTLF card form and the generator panel (#117).

The panel computes nothing.  It collects the inputs ``sbeam-cases`` takes on the command
line and calls ``sbeam_tools.cases.gust``; the target of these tests is the deck the
command line wrote, ``cessna210_flagship_gust.bdf``.
"""
from __future__ import annotations

import copy

from streamlit.testing.v1 import AppTest

from sbeam.model.card_writers import write_gustlf, write_trim
from sbeam.parser.bdf_reader import parse_bdf
from sbeam_tools.cases import cli
from tests.samples import sample_path
from tests.viewer.journey_helpers import _open, _submit, differences

GUST_DECK = sample_path("cessna210_flagship_gust.bdf")
# The inputs recorded in the gust deck's own header.
RECORDED = ["sample/cessna210_flagship/cessna210_flagship_trim.bdf", "--units", "SI",
            "--trim-template", "1", "--vc", "86.0", "--vd", "105.0", "--altitude", "0",
            "--massset", "10,20,30", "--g", "9.81", "--sid-base", "9000",
            "--title", "Cessna 210 flagship - FAR/CS 23.341 gust cases at V_C and V_D"]


def _generate(at: AppTest) -> AppTest:
    """Fill the panel with the recorded inputs and press the button."""
    at.selectbox(key="auth_gust_units").set_value("SI")
    at.run()
    at.selectbox(key="auth_gust_template").set_value(1)
    at.number_input(key="auth_gust_g_SI").set_value(9.81)
    at.number_input(key="auth_gust_vc").set_value(86.0)
    at.number_input(key="auth_gust_vd").set_value(105.0)
    at.text_input(key="auth_gust_alts").set_value("0")
    at.multiselect(key="auth_gust_mass").set_value([10, 20, 30])
    at.number_input(key="auth_gust_sid_base").set_value(9000)
    at.button(key="auth_gust_add").click()
    return at.run()


def test_the_committed_gust_deck_is_what_the_emitter_writes(tmp_path, monkeypatch, capsys):
    """The deck says "GENERATED ... do not hand-edit; regenerate".  Regenerating from the
    command in its header gives the file, apart from the line that records ``-o``."""
    monkeypatch.chdir(sample_path("cessna210_flagship_trim.bdf").parents[2])
    out = tmp_path / "regenerated.bdf"
    assert cli.main([*RECORDED, "-o", str(out)]) == 0
    capsys.readouterr()
    fresh, committed = out.read_text().splitlines(), GUST_DECK.read_text().splitlines()
    assert len(fresh) == len(committed)
    differing = [i for i, (a, b) in enumerate(zip(fresh, committed)) if a != b]
    assert differing == [4], [committed[i] for i in differing[:3]]
    assert committed[4].lstrip("$ ").startswith("sbeam-cases ")


def test_the_panel_writes_the_cards_the_command_line_wrote():
    """Same inputs, two front ends, one generator: card for card."""
    at = _open("cessna210_flagship/cessna210_flagship_trim.bdf")
    loaded_cc = copy.deepcopy(at.session_state["case_control"])
    at = _generate(at)
    assert not at.exception and not at.error, [e.value for e in at.error]
    cc_cli, bulk_cli = parse_bdf(GUST_DECK)
    bulk = at.session_state["bulk_data"]
    cc = at.session_state["case_control"]

    assert sorted(bulk.gustlfs) == sorted(bulk_cli.gustlfs) and len(bulk.gustlfs) == 12
    for sid in bulk_cli.gustlfs:
        assert differences(bulk_cli.gustlfs[sid], bulk.gustlfs[sid], f"GUSTLF {sid}") == []
        assert differences(bulk_cli.trims[sid], bulk.trims[sid], f"TRIM {sid}") == []
        # identical text, not only equal values
        assert write_gustlf(bulk.gustlfs[sid]) == write_gustlf(bulk_cli.gustlfs[sid])
        assert write_trim(bulk.trims[sid]) == write_trim(bulk_cli.trims[sid])
    # the gust subcases are the command line's; the deck's own subcases are kept before them
    n = len(loaded_cc.subcases)
    assert differences(loaded_cc.subcases, cc.subcases[:n], "loaded subcases") == []
    assert differences(cc_cli.subcases, cc.subcases[n:], "gust subcases") == []
    assert at.session_state["authored_cards"] == {
        "trim": set(bulk_cli.gustlfs), "gustlf": set(bulk_cli.gustlfs)}
    assert any("12 gust case(s) added" in s.value for s in at.success)
    assert any("K_G" in c.value and "9011" in c.value for c in at.code)   # the tool's table


def test_the_generated_cases_run_and_match_the_gust_decks_results():
    """What the panel added solves to the load factors the gust deck solves to."""
    at = _generate(_open("cessna210_flagship/cessna210_flagship_trim.bdf"))
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    assert not at.exception and not at.error, [e.value for e in at.error]
    results = at.session_state["sol144_result"]
    _, bulk_cli = parse_bdf(GUST_DECK)
    for sid, card in bulk_cli.gustlfs.items():
        echo = results[sid].gust_echo
        assert echo["n"] == card.n and echo["urdd3"] == -card.n * card.g


def test_the_panel_refuses_a_first_sid_that_is_taken():
    at = _open("cessna210_flagship/cessna210_flagship_trim.bdf")
    before = at.session_state["bulk_data"]
    at.number_input(key="auth_gust_vc").set_value(86.0)
    at.number_input(key="auth_gust_sid_base").set_value(
        at.session_state["case_control"].subcases[0].subcase_id)
    at.button(key="auth_gust_add").click()
    at.run()
    assert any("already exist" in e.value for e in at.error)
    assert at.session_state["bulk_data"] is before


def test_the_panel_needs_a_speed():
    at = _open("cessna210_flagship/cessna210_flagship_trim.bdf")
    at.button(key="auth_gust_add").click()
    at.run()
    assert any("at least one of V_C, V_D and V_B" in e.value for e in at.error)


def test_gustlf_form_one_gust_case_per_trim():
    """The plain card form: a new GUSTLF needs its own TRIM, and the parser says so."""
    at = _open("cessna210_flagship/cessna210_flagship_gust.bdf")
    at.selectbox(key="auth_sel_gustlf").set_value(9000)
    at.run()
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_gustlf").click()
    at.run()
    assert any("TRIM 9000 is already driven by GUSTLF 9000" in e.value for e in at.error)
    assert not any(at.session_state["authored_cards"].values())

    # a copy of TRIM 9000, then the gust case on the copy
    at.selectbox(key="auth_sel_trim").set_value(9000)
    at.run()
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_trim").click()
    at.run()
    new_trim = max(at.session_state["bulk_data"].trims)
    at.selectbox(key="auth_sel_gustlf").set_value(9000)
    at.run()
    at.selectbox(key="auth_gustlf_trimid@9000").set_value(new_trim)
    at.number_input(key="auth_gustlf_n@9000").set_value(2.25)
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_gustlf").click()
    at.run()
    assert not at.error, [e.value for e in at.error]
    bulk = at.session_state["bulk_data"]
    new_gust = max(bulk.gustlfs)
    made, source = bulk.gustlfs[new_gust], bulk.gustlfs[9000]
    assert (made.trimid, made.n) == (new_trim, 2.25)
    # every recorded field came through the form unchanged, sea-level altitude included
    assert (made.g, made.ude, made.veas, made.kg, made.mu, made.a, made.asrc, made.alt) == (
        source.g, source.ude, source.veas, source.kg, source.mu, source.a, source.asrc,
        source.alt)
    assert source.alt == 0.0


def test_gustlf_form_keeps_blank_altitude_apart_from_sea_level():
    at = _open("cessna210_flagship/cessna210_flagship_gust.bdf")
    at.selectbox(key="auth_sel_gustlf").set_value(9000)
    at.run()
    assert at.text_input(key="auth_gustlf_alt@9000").value == "0.0"
    _submit(at, "auth_form_gustlf")
    assert any(i.value == "No change." for i in at.info)
