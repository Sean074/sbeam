"""Opening a deck in the viewer: from the sample picker, from a path, by upload (#111).

A deck opened from its path is parsed where it stands, so a relative ``INCLUDE`` resolves.
An upload is parsed from a temporary file and cannot resolve one; the six flagship drivers
were unopenable before #111.
"""
from __future__ import annotations

import shutil

import pytest
from streamlit.testing.v1 import AppTest

from sbeam_tools.viewer.app import SAMPLE_ROOT, _session_defaults, list_sample_decks

SAMPLES = list_sample_decks()
INCLUDE_DRIVERS = sorted(
    name for name, path in SAMPLES.items()
    if any(line.upper().startswith("INCLUDE") for line in path.read_text().splitlines())
)


def _sbeam_app():
    from sbeam_tools.viewer.app import main
    main()


def _fresh() -> AppTest:
    at = AppTest.from_function(_sbeam_app, default_timeout=120)
    at.run()
    return at


def _open_sample(at: AppTest, name: str) -> AppTest:
    at.selectbox(key="sample_pick").set_value(name)
    at.button(key="open_deck").click()
    return at.run()


def test_the_picker_lists_every_sample_deck():
    on_disk = {p.relative_to(SAMPLE_ROOT).as_posix()
               for p in SAMPLE_ROOT.rglob("*") if p.suffix in (".bdf", ".dat")}
    assert set(SAMPLES) == on_disk
    assert len(INCLUDE_DRIVERS) >= 6, INCLUDE_DRIVERS


# Files under sample/ that are not decks to open on their own (sample/README.md): the picker
# lists them, and opening one reports the parser's reason instead of raising.
NOT_STANDALONE = {
    "cessna210_flagship/cessna210_flagship_body_cruciform.bdf": "no AEROS card",   # overlay
    "cessna210_flagship/cessna210_flagship_body_strip.bdf": "no AEROS card",       # overlay
    "ha144a/HA144A.bdf": "PARAM,WTMASS",                 # MSC archive listing, refused by design
}


@pytest.mark.parametrize("name", sorted(set(SAMPLES) - set(NOT_STANDALONE)))
def test_every_sample_deck_opens_from_the_picker(name):
    at = _open_sample(_fresh(), name)
    assert not at.exception, at.exception
    assert at.session_state["_parse_error"] is None, at.session_state["_parse_error"]
    assert at.session_state["bulk_data"] is not None
    assert at.session_state["_deck_path"] == str(SAMPLES[name].resolve())
    assert not at.error, [e.value for e in at.error]


@pytest.mark.parametrize("name", sorted(NOT_STANDALONE))
def test_a_file_that_is_not_a_deck_reports_the_parsers_reason(name):
    at = _open_sample(_fresh(), name)
    assert not at.exception, at.exception
    assert at.session_state["bulk_data"] is None
    assert NOT_STANDALONE[name] in at.session_state["_parse_error"]
    assert any("Parse error" in e.value for e in at.error)


def test_the_gust_deck_runs_from_the_viewer():
    """A GUSTLF subcase has no TRIM selector; the viewer once refused it as driverless."""
    at = _open_sample(_fresh(), "cessna210_flagship/cessna210_flagship_gust.bdf")
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=300)
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]
    results = at.session_state["sol144_result"]
    cc = at.session_state["case_control"]
    assert set(results) == {sc.subcase_id for sc in cc.subcases}
    assert all(r.gust_echo for r in results.values())


def test_a_second_deck_leaves_nothing_of_the_first():
    """Every model-dependent key is back at its default apart from what the loader sets."""
    at = _open_sample(_fresh(), "validation/val_cantilever_static.bdf")
    at.session_state["sol101_result"] = object()
    at.session_state["sol144_result"] = object()
    at.session_state["authored_cards"] = {"trim": {1}}
    at.session_state["aero_corr_sids"] = {7}
    at.session_state["selected_gid"] = 3
    first_cc = at.session_state["case_control"]

    at = _open_sample(at, "validation/val_free_free_modes.bdf")
    set_by_loader = {
        "bulk_data", "case_control", "_loaded_from_file_cc", "_uploaded_filename",
        "_uploaded_source_text", "_deck_path", "file_card_sids", "selected_subcase_id",
        "_parse_warnings", "_uploaded_file_id", "cc_subcases",
    }
    for key, default in _session_defaults().items():
        if key not in set_by_loader:
            assert at.session_state[key] == default, key
    assert at.session_state["case_control"] is not first_cc
    assert at.session_state["case_control"].sol == 103
    assert at.session_state["_uploaded_filename"] == "val_free_free_modes.bdf"


def test_a_typed_path_opens_a_deck_outside_the_samples(tmp_path):
    """A driver and its INCLUDE target copied elsewhere open by path."""
    src = SAMPLE_ROOT / "cessna210_flagship"
    for name in ("cessna210_flagship_gust.bdf", "cessna210_flagship_bulk.bdf"):
        shutil.copy(src / name, tmp_path / name)
    at = _fresh()
    at.text_input(key="deck_path_input").set_value(str(tmp_path / "cessna210_flagship_gust.bdf"))
    at.button(key="open_deck").click()
    at.run()
    assert at.session_state["_parse_error"] is None
    assert at.session_state["bulk_data"].gustlfs


def test_a_missing_path_is_reported_not_raised(tmp_path):
    at = _fresh()
    at.text_input(key="deck_path_input").set_value(str(tmp_path / "nope.bdf"))
    at.button(key="open_deck").click()
    at.run()
    assert not at.exception
    assert at.session_state["bulk_data"] is None
    assert "Cannot read" in at.session_state["_parse_error"]


def test_an_uploaded_include_driver_says_to_open_it_by_path():
    """The upload route parses from a temporary file; the error names the way out."""
    from sbeam_tools.viewer import app

    class _Upload:
        name = "cessna210_flagship_gust.bdf"

        def read(self) -> bytes:
            return (SAMPLE_ROOT / "cessna210_flagship" / self.name).read_bytes()

    class _State(dict):
        """A stand-in for ``st.session_state``: a mapping that also takes attributes.
        (AppTest's own state object has no ``keys()`` on streamlit 1.50, the CI pin.)"""
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    script_state = _State(app._session_defaults())

    class _St:
        session_state = script_state
    real = app.st
    app.st = _St                       # the loader only touches st.session_state
    try:
        app._handle_upload(_Upload())
    finally:
        app.st = real
    message = script_state["_parse_error"]
    assert "INCLUDE file not found" in message and "open the deck by its path" in message
