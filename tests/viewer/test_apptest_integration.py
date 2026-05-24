"""AppTest-based end-to-end integration tests for the sbeam viewer.

These tests exercise the full Streamlit session-state flow that unit tests cannot reach:
  Flow A — geometry load → GPWG → SOL 101 run → results view
  Flow B — geometry load → SOL 103 run → modal results view

State is injected directly into at.session_state (bypassing the file-upload widget)
to avoid temp-file creation inside the Streamlit runtime.
"""
from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest


def _sbeam_app():
    """Entry point for AppTest — imports main locally so the temp script is self-contained."""
    from sbeam.viewer.app import main
    main()


def _inject_state(at: AppTest, bulk, cc) -> None:
    """Populate session state as _handle_upload would after a successful parse."""
    at.session_state["bulk_data"] = bulk
    at.session_state["case_control"] = cc
    at.session_state["_loaded_from_file_cc"] = cc
    at.session_state["sol101_result"] = None
    at.session_state["sol103_result"] = None
    at.session_state["selected_gid"] = None
    at.session_state["selected_eid"] = None
    at.session_state["cc_subcases"] = None  # triggers rebuild from cc.subcases on next run
    at.session_state["selected_subcase_id"] = cc.subcases[0].subcase_id
    at.session_state["_parse_warnings"] = []
    at.session_state["_parse_error"] = None
    at.session_state["_uploaded_file_id"] = None
    at.session_state["_uploaded_filename"] = "test_input.bdf"


def test_flow_a_sol101_render_and_run(cantilever_sol101_parsed):
    """Flow A: injected geometry → GPWG → SOL 101 run → results UI renders."""
    cc, bulk = cantilever_sol101_parsed

    at = AppTest.from_function(_sbeam_app, default_timeout=30)
    at.run()                  # cold start — shows "Upload a BDF or DAT file to begin."
    _inject_state(at, bulk, cc)
    at.run()                  # renders with injected state

    assert not at.exception, [str(e) for e in at.exception]
    # GPWG sidebar metrics
    assert any(m.label == "Total mass" for m in at.sidebar.metric)
    assert any(m.label == "CG X" for m in at.sidebar.metric)
    # Parse-summary metrics (Model tab header)
    assert any(m.label == "Grids" for m in at.metric)
    assert any(m.label == "SOL" for m in at.metric)
    # Run Analysis button is present in Results tab
    assert any(b.label == "Run Analysis" for b in at.button)
    assert at.session_state["sol101_result"] is None

    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=30)

    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    result = at.session_state["sol101_result"]
    assert isinstance(result, dict) and 1 in result
    assert at.session_state["sol103_result"] is None
    assert any("SOL 101 complete" in s.value for s in at.success)
    assert at.slider(key="sol101_deform_scale") is not None
    assert any(b.key == "write_f06_btn" for b in at.button)


def test_flow_b_sol103_render_and_run(cantilever_sol103_parsed):
    """Flow B: injected geometry → SOL 103 run → modal results UI renders."""
    cc, bulk = cantilever_sol103_parsed

    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_state(at, bulk, cc)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any(m.label == "Total mass" for m in at.sidebar.metric)
    assert any(b.label == "Run Analysis" for b in at.button)

    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=60)       # modal solve takes longer than static

    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    result = at.session_state["sol103_result"]
    assert isinstance(result, dict) and 1 in result
    assert at.session_state["sol101_result"] is None
    assert any("SOL 103 complete" in s.value for s in at.success)
    assert at.selectbox(key="mode_sel") is not None
    assert at.slider(key="mode_scale") is not None
    assert any(b.key == "write_f06_btn" for b in at.button)
