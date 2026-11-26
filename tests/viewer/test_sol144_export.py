"""P12 S6 — driver-export acceptance: zero-loss round-trip and solve-through.

The driver + INCLUDE layout is exercised end-to-end: every aeroelastic
condition card of a sample deck is treated as viewer-authored (emitted inline
in the driver), the structural/aero model remainder becomes the INCLUDE file,
and the re-parsed composition must equal the original deck exactly.
"""

from pathlib import Path

import pytest

from sbeam.model.card_writers import FAMILIES
from sbeam.parser.bdf_reader import parse_bdf
from sbeam_tools.viewer.sol144_authoring import snapshot_family_ids
from sbeam_tools.viewer.sol144_authoring_ui import export_sol144_bdf
from tests.samples import sample_path


# The card each family writes (family keys are internal names; #87 renamed the cards)
_CARD_NAMES = {fam.upper() for fam in FAMILIES} | {
    "MANTRIM", "MANTIME", "MANCMD", "MANPRNT", "MANVR", "TRIMWGT", "TRIMINEQ"}


def _split_sample(deck_path: Path) -> tuple[str, str]:
    """Return (model_only_bulk_text, full_source) for a self-contained deck.

    The model text is the bulk section with every authoring-family card (and
    its continuations) removed — what the INCLUDE file holds when the
    conditions are viewer-authored.
    """
    source = deck_path.read_text()
    lines = source.splitlines()
    bulk_start = next(i for i, ln in enumerate(lines)
                      if ln.strip().upper().startswith("BEGIN")) + 1
    kept: list[str] = []
    skipping = False
    for ln in lines[bulk_start:]:
        stripped = ln.strip()
        if stripped.upper().startswith("ENDDATA"):
            break
        first = stripped.split(",", 1)[0].strip().upper()
        if stripped.startswith("+"):
            if skipping:
                continue
        elif first in _CARD_NAMES:
            skipping = True
            continue
        else:
            skipping = False
        kept.append(ln)
    return "\n".join(kept) + "\n", source


def _families_equal(a, b) -> None:
    for family, (attr, _) in FAMILIES.items():
        assert getattr(a, attr) == getattr(b, attr), family


@pytest.mark.parametrize("deck", ["ha144a_fullspan_mloads.bdf",
                                  "ha144a_mloads_massset.bdf"])
def test_driver_export_roundtrip_zero_loss(deck, tmp_path):
    cc, bulk = parse_bdf(sample_path(deck))
    model_text, _ = _split_sample(sample_path(deck))
    (tmp_path / "model.dat").write_text(model_text)

    authored = snapshot_family_ids(bulk)   # every condition card is "authored"
    driver_text = export_sol144_bdf(cc, bulk, authored,
                                    include_paths=["model.dat"])
    driver = tmp_path / "run.bdf"
    driver.write_text(driver_text)

    cc2, bulk2 = parse_bdf(driver)
    assert cc2.sol == cc.sol
    assert cc2.subcases == cc.subcases
    _families_equal(bulk2, bulk)
    # The structural model survived the split: same grids/elements/CAERO.
    assert bulk2.grids.keys() == bulk.grids.keys()
    assert bulk2.caero1s.keys() == bulk.caero1s.keys()
    assert bulk2.conm2s.keys() == bulk.conm2s.keys()


def test_exported_driver_solves_trim(tmp_path):
    """The authored driver runs through the SOL 144 trim solver unchanged."""
    from sbeam.aero.aero_model import build_aero_model
    from sbeam.assembly.load_vector import build_grid_index
    from sbeam.solver.sol144 import AeroCache, run_sol144_trim

    deck = "ha144a_fullspan_mloads.bdf"
    cc, bulk = parse_bdf(sample_path(deck))
    model_text, _ = _split_sample(sample_path(deck))
    (tmp_path / "model.dat").write_text(model_text)
    driver = tmp_path / "run.bdf"
    driver.write_text(export_sol144_bdf(cc, bulk, snapshot_family_ids(bulk),
                                        include_paths=["model.dat"]))

    cc2, bulk2 = parse_bdf(driver)
    sc = next(s for s in cc2.subcases if s.trim_sid is not None)
    grid_index = build_grid_index(bulk2)
    aero = build_aero_model(bulk2, grid_index=grid_index)
    cache = AeroCache(bulk2, grid_index, seed=aero)
    result = run_sol144_trim(bulk2, sc, aero, aero_cache=cache)
    assert result.trim_sid == sc.trim_sid
    assert "ANGLEA" in result.trim_vars and "ELEV" in result.trim_vars


def test_authoring_form_applies_card_through_ui():
    """AppTest: an AESTAT authored through the actual form lands in the model."""
    from tests.viewer.journey_helpers import _open

    at = _open("ha144a/ha144a_fullspan_mloads.bdf")
    assert not at.exception, [str(e) for e in at.exception]

    at.number_input(key="auth_aestat_id").set_value(901)
    at.selectbox(key="auth_aestat_label").select("SIDES")
    apply_btn = next(b for b in at.button
                     if getattr(b, "key", "") == "FormSubmitter:auth_form_aestat-Apply")
    apply_btn.click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    bulk_after = at.session_state["bulk_data"]
    assert 901 in bulk_after.aestats
    assert bulk_after.aestats[901].label == "SIDES"
    assert 901 in at.session_state["authored_cards"]["aestat"]


def _apply(at, form: str):
    next(b for b in at.button
         if getattr(b, "key", "") == f"FormSubmitter:auth_form_{form}-Apply").click()
    at.run()
    assert not at.exception, [str(e) for e in at.exception]


def _author_aelist(at, sid: int, boxes: str) -> None:
    at.number_input(key="auth_aelist_sid").set_value(sid)
    at.text_input(key="auth_aelist_boxes").set_value(boxes)
    _apply(at, "aelist")
    assert sid in at.session_state["bulk_data"].aelists, [e.value for e in at.error]


def _fill_aesurf(at, alid1: int, alid2: int) -> None:
    at.number_input(key="auth_aesurf_id").set_value(506)
    at.text_input(key="auth_aesurf_label").set_value("AILT")
    at.selectbox(key="auth_aesurf_cid1").select(1)
    at.selectbox(key="auth_aesurf_alid1").select(alid1)
    at.selectbox(key="auth_aesurf_cid2").select(2)
    at.selectbox(key="auth_aesurf_alid2").select(alid2)


def test_aesurf_form_keeps_the_second_hinge_half():
    """G9 (#9): CID2/ALID2 authored through the AESURF form land on the card — the
    form used to rebuild the Aesurf without them, so re-saving an aileron pair
    silently dropped its port half."""
    from tests.viewer.journey_helpers import _open

    at = _open("ha144a/ha144a_fullspan_mloads.bdf")
    _author_aelist(at, 1500, "1100 THRU 1103")
    _author_aelist(at, 1501, "2100 THRU 2103")
    _fill_aesurf(at, 1500, 1501)
    _apply(at, "aesurf")
    assert not at.error, [e.value for e in at.error]
    card = at.session_state["bulk_data"].aesurfs[506]
    assert (card.cid1, card.alid1, card.cid2, card.alid2) == (1, 1500, 2, 1501)


def test_the_form_refuses_what_the_parser_refuses():
    """#113: a card typed into a form goes through the parser.  This AESURF names two
    box lists that share boxes; the parser refuses it, and until #113 the viewer's
    in-memory edit accepted it and ran it."""
    from tests.viewer.journey_helpers import _open

    at = _open("ha144a/ha144a_fullspan_mloads.bdf")
    before = dict(at.session_state["bulk_data"].aesurfs)
    _fill_aesurf(at, 1000, 1400)
    _apply(at, "aesurf")
    assert any("appear in both ALID1=1000 and ALID2=1400" in e.value for e in at.error)
    assert at.session_state["bulk_data"].aesurfs == before
    assert not any(at.session_state["authored_cards"].values())
