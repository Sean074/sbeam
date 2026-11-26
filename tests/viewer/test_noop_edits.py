"""An interaction that should change nothing changes nothing (#123).

The journey test (``test_journey.py``, #112) holds these across every sample deck.  Each
test here names one defect it found, on the deck that showed it.
"""
from __future__ import annotations

import copy

from streamlit.testing.v1 import AppTest

from sbeam_tools.viewer.case_control_ui import deck_bulk_section, export_bdf_text
from sbeam.parser.case_control import CaseControl, SubcaseControl
from tests.viewer.journey_helpers import _open, _submit, differences


def _apply_case_control_unchanged(at: AppTest) -> None:
    at.checkbox(key="cc_show_editor").check()
    at.run()
    _submit(at, "cc_form")


# --- #123: case-control Apply and export --------------------------------------------------

def test_apply_keeps_the_applied_load_of_a_trim_subcase():
    """Thrust in trim (#6): LOAD on a SOL 144 trim subcase was set to None by every Apply."""
    at = _open("validation/val_thrust_trim.bdf")
    before = {sc.subcase_id: sc.load_sid for sc in at.session_state["case_control"].subcases}
    assert any(v is not None for v in before.values())
    _apply_case_control_unchanged(at)
    after = {sc.subcase_id: sc.load_sid for sc in at.session_state["case_control"].subcases}
    assert after == before


def test_apply_keeps_what_the_editor_has_no_widget_for():
    """LABEL, SET and MODEXP have no widget; Apply rebuilt the subcase without them."""
    at = _open("goland_wing/goland_wing_modes.bdf")
    cc = copy.deepcopy(at.session_state["case_control"])
    assert cc.sets and cc.subcases[0].modexp_set is not None
    _apply_case_control_unchanged(at)
    assert differences(cc, at.session_state["case_control"]) == []

    at = _open("validation/val_thrust_trim.bdf")
    labels = [sc.label for sc in at.session_state["case_control"].subcases]
    assert all(labels)
    _apply_case_control_unchanged(at)
    assert [sc.label for sc in at.session_state["case_control"].subcases] == labels


def test_a_grav_only_load_set_stays_selected():
    """LOAD = 20 names a GRAV; the picker listed FORCE, MOMENT and LOAD sets only."""
    at = _open("beam/pylon_strut_engine.bdf")
    bulk = at.session_state["bulk_data"]
    assert 20 in bulk.gravs and 20 not in bulk.forces and 20 not in bulk.loads
    _apply_case_control_unchanged(at)
    assert [sc.load_sid for sc in at.session_state["case_control"].subcases] == [100, 20]


def test_a_single_file_deck_keeps_no_include_after_apply():
    """Apply used to give every single-file deck ``INCLUDE 'model.dat'``."""
    at = _open("validation/val_cantilever_static.bdf")
    _apply_case_control_unchanged(at)
    cc = at.session_state["case_control"]
    assert cc.includes == [] and cc.include is None
    preview = [c.value for c in at.code if "BEGIN BULK" in c.value][-1]
    assert "INCLUDE" not in preview and "GRID" in preview


def test_deck_bulk_section():
    text = "SOL 101\nCEND\nSUBCASE 1\nBEGIN BULK $ here\nINCLUDE 'a.bdf'\n$ note\nGRID,1\nENDDATA\nafter"
    assert deck_bulk_section(text) == "INCLUDE 'a.bdf'\n$ note\nGRID,1"
    assert deck_bulk_section("GRID,1\nENDDATA\n") is None      # bulk-data-only file
    assert deck_bulk_section("$ BEGIN BULK in a comment\nGRID,1\n") is None
    assert deck_bulk_section(None) is None


def test_export_writes_the_decks_bulk_section_unchanged():
    """The gust driver's own TRIM and GUSTLF cards follow its INCLUDE; the export, built
    from the INCLUDE list alone, left them out."""
    cc = CaseControl(sol=144, subcases=[SubcaseControl(subcase_id=1, gustlf_sid=9000)],
                     includes=["bulk.bdf"])
    section = "INCLUDE 'bulk.bdf'\nTRIM, 9000, 0.0, 4530.05, PITCH, 0.0\nGUSTLF, 9000, 9000"
    text = export_bdf_text(cc, bulk_section=section, authored_block="AESTAT, 7, ANGLEA\n")
    body = text.split("BEGIN BULK\n", 1)[1]
    assert body == section + "\nAESTAT, 7, ANGLEA\nENDDATA\n"
    assert text.count("INCLUDE") == 1                        # the deck's own, not a second


def test_a_second_deck_does_not_inherit_the_first_decks_widget_values():
    """With the editor open on deck A, Apply on deck B wrote A's TRIM selections into B."""
    at = _open("validation/val_thrust_trim.bdf")
    at.checkbox(key="cc_show_editor").check()
    at.run()
    at.session_state["aero_body_sids"] = {1}                 # panel data kept under its own key
    at.selectbox(key="sample_pick").set_value("validation/val_lateral_aileron_rudder.bdf")
    at.button(key="open_deck").click()
    at.run()
    assert "aero_body_sids" not in at.session_state
    cc = copy.deepcopy(at.session_state["case_control"])
    assert len({sc.trim_sid for sc in cc.subcases}) > 1
    show = next(c for c in at.checkbox if (c.key or "").startswith("cc_show_editor"))
    assert show.value is False                               # a new widget, not deck A's
    show.check()
    at.run()
    _submit(at, "cc_form")
    assert differences(cc, at.session_state["case_control"]) == []


# --- #123: the card editors -----------------------------------------------------------------

def test_edit_existing_shows_the_selected_card():
    """SUPORT 90 has DOFs '3'.  The form kept its new-card default '35', and Apply wrote it."""
    at = _open("validation/val_dihedral_trim.bdf")
    assert at.session_state["bulk_data"].supports[0].dofs == "3"
    at.selectbox(key="auth_sel_suport").set_value(90)
    at.run()
    assert at.text_input(key="auth_suport_dofs@90").value == "3"
    _submit(at, "auth_form_suport")
    assert at.session_state["bulk_data"].supports[0].dofs == "3"
    assert not any(at.session_state["authored_cards"].values())


def test_an_edit_to_a_loaded_card_is_applied_and_tracked():
    at = _open("validation/val_dihedral_trim.bdf")
    at.selectbox(key="auth_sel_suport").set_value(90)
    at.run()
    at.text_input(key="auth_suport_dofs@90").set_value("35")
    _submit(at, "auth_form_suport")
    assert at.session_state["bulk_data"].supports[0].dofs == "35"
    assert at.session_state["authored_cards"] == {"suport": {90}}


def test_choosing_another_card_shows_that_card():
    """Two TRIMs with different q: the form follows the selection both ways."""
    at = _open("ha144a/ha144a_fullspan_sbeam.bdf")
    trims = at.session_state["bulk_data"].trims
    assert trims[1].q != trims[2].q
    for sid in (1, 2, 1):
        at.selectbox(key="auth_sel_trim").set_value(sid)
        at.run()
        assert at.number_input(key=f"auth_trim_q@{sid}").value == trims[sid].q


def test_tabled1_can_be_applied_and_saved_as_new():
    """TABLED1's key field is TID; the editor looked for SID or ID and raised."""
    at = _open("ha144a/ha144a_fullspan_mloads.bdf")
    tables = at.session_state["bulk_data"].tabled1s
    tid = sorted(tables)[0]
    at.selectbox(key="auth_sel_tabled1").set_value(tid)
    at.run()
    _submit(at, "auth_form_tabled1")
    assert not at.exception, [str(e.value) for e in at.exception]
    save = [b for b in at.button if b.label == "Save as new SID"
            and b.form_id == "auth_form_tabled1"]
    save[0].click()
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    new = max(at.session_state["bulk_data"].tabled1s)
    assert new != tid and at.session_state["authored_cards"] == {"tabled1": {new}}
    assert at.session_state["bulk_data"].tabled1s[new].ys == tables[tid].ys
