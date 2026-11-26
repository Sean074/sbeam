"""Authored cards go through the deck text and the parser (#113).

Three things are held here:

1. **The parser owns the card rules.**  ``validate_sol144_authoring`` re-implemented
   them for cards the viewer put into the model in memory.  It is gone; this file
   records, rule by rule, that the parser refuses each one, and which checks the
   parser does not make (they stay in ``check_case_control``).
2. **A card survives the round trip** form -> text -> parser for every card family.
3. **What runs is what exports**: after an edit the session model equals the parse of
   the export.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from sbeam.model.aero import Diverg, Trimcon, Trimobj, Trimvar
from sbeam.model.card_writers import FAMILIES
from sbeam.parser.bdf_reader import parse_bdf
from sbeam_tools.viewer import session_deck
from sbeam_tools.viewer import sol144_authoring as logic
from sbeam_tools.viewer.sol144_authoring import check_case_control
from tests.samples import sample_path
from tests.viewer.journey_helpers import _open, differences

MLOADS = sample_path("ha144a_fullspan_mloads.bdf")
SOURCE = MLOADS.read_text()


def _mutated(*pairs: tuple[str, str], add: str = "") -> str:
    text = SOURCE
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new, 1)
    if add:
        text = text.replace("ENDDATA", add + "\nENDDATA")
    return text


_TABLE = "+, 0.0, 0.492457, 0.2, 0.592457, 1.0, 0.592457, ENDT"
_MODAL = ("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 1, 1, 1, 6, -1")

# Each rule validate_sol144_authoring checked on cards, the deck that breaks it, and a
# fragment of the parser's refusal.
PARSER_OWNS = {
    "TRIM label not defined": (
        _mutated(("TRIM, 1, 0.9, 40.0, PITCH", "TRIM, 1, 0.9, 40.0, BOGUS")),
        "TRIM 1: label 'BOGUS' not defined"),
    "MANVR names a missing MANTRIM": (
        _mutated(("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 77, 1, 1, 1")), "MANTRIM 77 not found"),
    "MANTRIM names a missing TRIM": (
        _mutated(("MANTRIM, 1, 1,", "MANTRIM, 1, 77,")), "TRIMID 77 not found"),
    "MANVR names a missing MANTIME": (
        _mutated(("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 77, 1, 1")), "MANTIME 77 not found"),
    "MANTIME DT not positive": (
        _mutated(("MANTIME, 1, 0.0, 1.0, 0.01", "MANTIME, 1, 0.0, 1.0, 0.0")),
        "DT must be positive"),
    "MANTIME TEND not after T0": (
        _mutated(("MANTIME, 1, 0.0, 1.0,", "MANTIME, 1, 2.0, 1.0,")), "TEND must exceed T0"),
    "MANVR names a missing MANCMD": (
        _mutated(("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 1, 77, 1")), "MANCMD 77 not found"),
    "MANVR names a missing MANPRNT": (
        _mutated(("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 1, 1, 77")), "MANPRNT 77 not found"),
    "MANCMD label not defined": (
        _mutated(("MANCMD, 1, ELEV, 300", "MANCMD, 1, BOGUS, 300")),
        "command label 'BOGUS' not defined"),
    "MANCMD names a missing TABLED1": (
        _mutated(("MANCMD, 1, ELEV, 300", "MANCMD, 1, ELEV, 377")), "TABID 377 not found"),
    "TABLED1 with one point": (
        _mutated((_TABLE, "+, 0.0, 0.492457, ENDT")), "needs at least two"),
    "TABLED1 abscissae not increasing": (
        _mutated((_TABLE, "+, 0.0, 0.492457, 0.2, 0.592457, 0.1, 0.592457, ENDT")),
        "strictly increasing"),
    "MANVR METHOD is not an EIGRL": (
        _mutated(("MANVR, 1, 1, 1, 1, 1", "MANVR, 1, 1, 1, 1, 1, 6, 55")),
        "METHOD 55 not found in EIGRL"),
    "modal MANVR commands a rigid state": (
        _mutated(_MODAL, ("MANCMD, 1, ELEV, 300", "MANCMD, 1, ANGLEA, 300")),
        "rigid-state label 'ANGLEA'"),
    "AELIST box outside every CAERO1": (
        _mutated(("AELIST, 1000, 1000, 1001", "AELIST, 1000, 999999, 1001")),
        "box ID 999999 not within any CAERO1 range"),
    "authored card repeats a loaded TRIM": (
        _mutated(add="TRIM, 1, 0.9, 40.0, PITCH, 0.0, URDD3, -32.174\n+, URDD5, 0.0"),
        "Duplicate TRIM SID 1"),
    "authored card repeats a loaded AESTAT": (
        _mutated(add="AESTAT, 501, ANGLEA"), "Duplicate AESTAT ID 501"),
    "authored card repeats a loaded TABLED1": (
        _mutated(add="TABLED1, 300\n+, 0.0, 0.0, 1.0, 1.0, ENDT"), "Duplicate TABLED1 TID 300"),
}

# What the parser accepts and the viewer reports before Launch (check_case_control).
VIEWER_KEEPS = {
    "subcase with no driver": (_mutated(("  TRIM   = 1\n", "")), "needs a driver"),
    "TRIM selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 77")), "TRIM 77 not found"),
    "MANVR selector names no card": (
        _mutated(("  MANVR = 1", "  MANVR = 77")), "MANVR 77 not found"),
    "MANVR with TRIM in one subcase": (
        _mutated(("  MANVR = 1", "  MANVR = 1\n  TRIM = 1")), "cannot combine"),
    "LOAD selector names no set": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  LOAD = 777")), "LOAD 777 not found"),
    "LOAD on a MANVR subcase": (
        _mutated(("  MANVR = 1", "  MANVR = 1\n  LOAD = 777")),
        "LOAD combines only with a TRIM subcase"),
    "MASSCASE selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  MASSCASE = 777")), "MASSCASE 777 not found"),
    "GUSTLF selector names no card": (
        _mutated(("  TRIM   = 1", "  GUSTLF = 777")), "GUSTLF 777 not found"),
    "DIVERG selector names no card": (
        _mutated(("  TRIM   = 1", "  DIVERG = 777")), "DIVERG 777 not found"),
    "TRIMWGT selector names no card": (
        _mutated(("  TRIM   = 1", "  TRIM   = 1\n  TRIMWGT = 777")), "TRIMWGT 777 not found"),
    "MANVR subcase with no SUPORT": (
        _mutated(("SUPORT, 90, 35", "$SUPORT, 90, 35")), "needs a SUPORT card"),
    "modal MANVR, MANTRIM without RHO": (
        _mutated(_MODAL, ("MANTRIM, 1, 1, 2.3769-3", "MANTRIM, 1, 1")), "needs RHO"),
}


@pytest.mark.parametrize("rule", sorted(PARSER_OWNS))
def test_the_parser_refuses_each_card_rule_the_viewer_used_to_restate(rule):
    text, fragment = PARSER_OWNS[rule]
    with pytest.raises(ValueError) as refusal:
        parse_bdf(MLOADS, text=text)
    assert fragment in str(refusal.value)


@pytest.mark.parametrize("rule", sorted(VIEWER_KEEPS))
def test_what_the_parser_accepts_the_viewer_reports_before_launch(rule):
    text, fragment = VIEWER_KEEPS[rule]
    cc, bulk = parse_bdf(MLOADS, text=text)            # the parser does not check this
    errors, _ = check_case_control(bulk, cc)
    assert any(fragment in e for e in errors), errors


# --- every family: card -> text -> parser ---------------------------------------------

def _one_card_per_family() -> dict[str, tuple[Path, object]]:
    """A deck and a card of each family: from the samples where one has it, else built."""
    found: dict[str, tuple[Path, object]] = {}
    for name in ("ha144a_mloads_massset.bdf", "cessna210_flagship_gust.bdf"):
        path = sample_path(name)
        _, bulk = parse_bdf(path)
        for family in FAMILIES:
            store = logic.family_store(bulk, family)
            if family in found or not store:
                continue
            card = store[0] if family == "suport" else store[sorted(store)[0]]
            found[family] = (path, card)
    base = sample_path("ha144a_mloads_massset.bdf")
    found["trimvar"] = (base, Trimvar(id=1, label="ELEV", init=0.01, lb=-0.4, ub=0.4))
    found["trimobj"] = (base, Trimobj(sid=1, labels=["ELEV", "ANGLEA"], weights=[1.0, 2.5]))
    found["trimcon"] = (base, [Trimcon(sid=1, label="ELEV", sense="LE", rhs=0.3),
                               Trimcon(sid=1, label="ANGLEA", sense="GE", rhs=-0.1)])
    found["diverg"] = (base, Diverg(sid=1, nroots=2, machs=[0.5, 0.9]))
    return found


CARDS = _one_card_per_family()


def test_a_card_of_every_family_is_at_hand():
    assert set(CARDS) == set(FAMILIES)


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_card_survives_text_and_parser(family):
    """The card written into the deck text is the card the parser hands back."""
    path, card = CARDS[family]
    cc, bulk = parse_bdf(path)
    new = copy.deepcopy(card)
    if family != "suport":                  # SUPORT's key is its grid: keep the grid
        key = logic.next_free_sid(bulk, family)
        for one in (new if isinstance(new, list) else [new]):
            setattr(one, logic.key_attr(family, one), key)
        changes = [(family, new)]
        if family == "gustlf":              # one gust case per TRIM: give it its own
            trim = copy.deepcopy(bulk.trims[new.trimid])
            trim.sid = new.trimid = logic.next_free_sid(bulk, "trim")
            changes.insert(0, ("trim", trim))
        trial, record = logic.candidate(bulk, {}, changes)
    else:                                   # ...and write it in place of the loaded one
        key = new.gid
        source_without = "\n".join(
            line for line in path.read_text().splitlines()
            if not line.upper().startswith("SUPORT"))
        trial, record = logic.candidate(bulk, {}, [(family, new)])
        text = session_deck.deck_text(cc, source_without, logic.cards_text(trial, record))
        parsed, _ = session_deck.parse_deck_text(text, True, str(path), path.name)
        assert parsed.supports == [new]
        return
    text = session_deck.deck_text(cc, path.read_text(), logic.cards_text(trial, record))
    parsed, _ = session_deck.parse_deck_text(text, True, str(path), path.name)
    back = logic.family_store(parsed, family)[key]
    assert differences(new, back, family) == []
    assert record[family] == {key}


# --- through the viewer ---------------------------------------------------------------

def _export_parses_to_the_session_model(at, tmp_path: Path, source: Path) -> None:
    """What runs is what exports: the session model equals the parse of the export."""
    text = [c.value for c in at.code if "BEGIN BULK" in c.value][-1]
    _, exported = parse_bdf(source.with_name("exported.bdf"), text=text)
    assert differences(at.session_state["bulk_data"], exported, "bulk") == []


def test_save_as_new_for_every_family_the_deck_has(tmp_path):
    name = "ha144a/ha144a_mloads_massset.bdf"
    at = _open(name)
    loaded = copy.deepcopy(at.session_state["bulk_data"])
    made: dict[str, int] = {}
    for family in FAMILIES:
        keys = sorted(logic.family_store(loaded, family)) if family != "suport" else []
        if not keys:
            continue
        at.selectbox(key=f"auth_sel_{family}").set_value(keys[0])
        at.run()
        next(b for b in at.button if b.label == "Save as new SID"
             and b.form_id == f"auth_form_{family}").click()
        at.run()
        assert not at.exception and not at.error, (family, [e.value for e in at.error])
        new_key = max(logic.family_store(at.session_state["bulk_data"], family))
        assert new_key not in keys
        made[family] = new_key
        # the copy equals the original apart from its ID
        original = copy.deepcopy(logic.family_store(loaded, family)[keys[0]])
        setattr(original, logic.key_attr(family, original), new_key)
        assert differences(
            original, logic.family_store(at.session_state["bulk_data"], family)[new_key],
            family) == []
        at.selectbox(key=f"auth_sel_{family}").set_value("— new —")
        at.run()
    assert len(made) >= 10, made
    assert at.session_state["authored_cards"] == {f: {k} for f, k in made.items()}
    # every loaded card is still the loaded card
    for family in FAMILIES:
        store, now = (logic.family_store(b, family) for b in (loaded, at.session_state["bulk_data"]))
        if family == "suport":
            assert store == now
        else:
            assert all(differences(store[k], now[k]) == [] for k in store)
    at.checkbox(key="cc_show_editor").check()
    at.run()
    _export_parses_to_the_session_model(at, tmp_path, sample_path("ha144a_mloads_massset.bdf"))


def test_the_session_model_is_the_parsers_not_the_forms():
    """After an edit the session holds a new model object, parsed from the deck text."""
    at = _open("validation/val_dihedral_trim.bdf")
    before = at.session_state["bulk_data"]
    at.selectbox(key="auth_sel_trim").set_value(1)
    at.run()
    at.number_input(key="auth_trim_q@1").set_value(77.5)
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_trim").click()
    at.run()
    after = at.session_state["bulk_data"]
    assert after is not before
    assert after.trims[2].q == 77.5 and after.trims[1].q == before.trims[1].q
    assert any("TRIM 2 applied to the deck." in s.value for s in at.success)
    assert at.session_state["sol144_result"] is None


def test_an_authored_card_can_be_edited_and_deleted():
    at = _open("validation/val_dihedral_trim.bdf")
    at.selectbox(key="auth_sel_trim").set_value(1)
    at.run()
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_trim").click()
    at.run()
    at.selectbox(key="auth_sel_trim").set_value(2)
    at.run()
    at.number_input(key="auth_trim_q@2").set_value(12.0)
    next(b for b in at.button if b.label == "Apply" and b.form_id == "auth_form_trim").click()
    at.run()
    assert not at.error, [e.value for e in at.error]
    assert at.session_state["bulk_data"].trims[2].q == 12.0
    next(b for b in at.button if b.key == "auth_del_trim").click()
    at.run()
    assert 2 not in at.session_state["bulk_data"].trims
    assert not any(at.session_state["authored_cards"].values())


def test_the_parsers_refusal_reaches_the_form():
    """SUPORT saved as new lands on the next grid number, which is no grid.  The old
    in-memory edit accepted it; the parser does not."""
    at = _open("validation/val_dihedral_trim.bdf")
    before = at.session_state["bulk_data"]
    at.selectbox(key="auth_sel_suport").set_value(90)
    at.run()
    next(b for b in at.button if b.label == "Save as new SID"
         and b.form_id == "auth_form_suport").click()
    at.run()
    assert any("The deck would not parse: SUPORT: grid GID=91 not found" in e.value
               for e in at.error)
    assert at.session_state["bulk_data"] is before
    assert not any(at.session_state["authored_cards"].values())


def test_two_pass_builder_on_a_loaded_manvr_writes_new_cards_and_repoints_the_subcase():
    """#114: MANVR 10 and its MANCMD are cards of the loaded deck, so the second pass
    adds a new TABLED1, MANCMD and MANVR and selects the new MANVR in subcase 1."""
    at = _open("ha144a/ha144a_mloads_massset.bdf")
    loaded = copy.deepcopy(at.session_state["bulk_data"])
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run()
    assert at.session_state["maneuver_result"], [e.value for e in at.error]

    at.selectbox(key="auth_inc_mloads").set_value(10)
    at.run()
    at.button(key="auth_inc_add").click()
    at.run()
    assert list(at.session_state["mldcomd_increments"]) == [(10, "ELEV")]
    at.button(key="auth_inc_resolve").click()
    at.run()
    assert not at.exception and not at.error, [e.value for e in at.error]

    bulk = at.session_state["bulk_data"]
    cc = at.session_state["case_control"]
    new_manvr = cc.subcases[0].mloads_sid
    assert new_manvr not in loaded.mloads and new_manvr in bulk.mloads
    assert [sc.mloads_sid for sc in cc.subcases[1:]] == [20, 30]
    assert differences(loaded.mloads[10], bulk.mloads[10]) == []          # untouched
    assert differences(loaded.mldcomds[11], bulk.mldcomds[11]) == []
    command = dict(bulk.mldcomds[bulk.mloads[new_manvr].mldcomd].commands)
    table = bulk.tabled1s[command["ELEV"]]
    assert command["ELEV"] not in loaded.tabled1s
    # the table starts at the trim elevator the run just solved for subcase 1
    assert table.ys[0] == pytest.approx(loaded.tabled1s[310].ys[0], abs=1e-6)
    assert at.session_state["mldcomd_increments"] == {}
    assert at.session_state["authored_cards"] == {
        "tabled1": {command["ELEV"]}, "mldcomd": {bulk.mloads[new_manvr].mldcomd},
        "mloads": {new_manvr}}
    assert any(f"MANVR {new_manvr}" in s.value for s in at.success)
    at.checkbox(key="cc_show_editor").check()
    at.run()
    text = [c.value for c in at.code if "BEGIN BULK" in c.value][-1]
    cc_out, bulk_out = parse_bdf(sample_path("ha144a_mloads_massset.bdf").with_name("x.bdf"),
                                 text=text)
    assert cc_out.subcases[0].mloads_sid == new_manvr
    assert differences(bulk, bulk_out, "bulk") == []
