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
from sbeam.viewer.sol144_authoring import snapshot_family_ids
from sbeam.viewer.sol144_authoring_ui import export_sol144_bdf

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"

_CARD_NAMES = {fam.upper() for fam in FAMILIES}


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
    cc, bulk = parse_bdf(SAMPLE_DIR / deck)
    model_text, _ = _split_sample(SAMPLE_DIR / deck)
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
    cc, bulk = parse_bdf(SAMPLE_DIR / deck)
    model_text, _ = _split_sample(SAMPLE_DIR / deck)
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
    from streamlit.testing.v1 import AppTest

    def _app():
        from sbeam.viewer.app import main
        main()

    cc, bulk = parse_bdf(SAMPLE_DIR / "ha144a_fullspan_mloads.bdf")
    at = AppTest.from_function(_app, default_timeout=30)
    at.run()
    at.session_state["bulk_data"] = bulk
    at.session_state["case_control"] = cc
    at.session_state["_loaded_from_file_cc"] = cc
    at.session_state["cc_subcases"] = None
    at.session_state["selected_subcase_id"] = cc.subcases[0].subcase_id
    at.session_state["_uploaded_filename"] = "ha144a_fullspan_mloads.bdf"
    at.run()
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
