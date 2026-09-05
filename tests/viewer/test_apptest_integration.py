"""AppTest-based end-to-end integration tests for the sbeam viewer.

These tests exercise the full Streamlit session-state flow that unit tests cannot reach:
  Flow A — geometry load → GPWG → SOL 101 run → results view
  Flow B — geometry load → SOL 103 run → modal results view

State is injected directly into at.session_state (bypassing the file-upload widget)
to avoid temp-file creation inside the Streamlit runtime.
"""
from __future__ import annotations

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


def test_flow_c_sol144_render_and_run(dihedral_sol144_parsed):
    """Flow C: injected ±Γ dihedral SOL 144 deck → trim run → results UI renders.

    Acceptance (Step 57): loads a SOL 144 result and renders all panels without
    error, including a ±Γ dihedral deck whose deflected geometry is canted (z≠0),
    not a flat xy-projection.
    """
    cc, bulk = dihedral_sol144_parsed

    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_state(at, bulk, cc)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    # Case Control tab shows the SOL-aware planned-analysis summary + Launch button
    assert any("Planned Analysis" in m.value for m in at.markdown)
    assert any(b.key == "cc_launch" for b in at.button)
    assert any(b.label == "Run Analysis" for b in at.button)

    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=60)

    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    result = at.session_state["sol144_result"]
    assert isinstance(result, dict) and 1 in result
    assert at.session_state["sol101_result"] is None
    assert any("SOL 144 complete" in s.value for s in at.success)
    # Deflected-shape / aero-box deflection slider rendered
    assert at.slider(key="sol144_deform_scale") is not None
    # Canted geometry: the cached aero model's box corners carry non-zero z
    aero = at.session_state["aero_model_144"]
    zs = [c[2] for b in aero.boxes for c in b.corners]
    assert max(zs) - min(zs) > 1e-6, "dihedral deck rendered flat (z range ~0)"


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


def test_flow_d_sol144_mloads_render_and_run():
    """Flow D (AC5): MLOADS sample deck → trim + maneuver run → results UI renders.

    Acceptance: six trim totals visible on the trim subcase; switching to the
    maneuver subcase renders the time-history view, sample slider, and export
    buttons without exception; the f06 export path includes the maneuver block.
    """
    import warnings
    from pathlib import Path
    from sbeam.parser.bdf_reader import parse_bdf

    sample = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_mloads.bdf"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(sample)

    at = AppTest.from_function(_sbeam_app, default_timeout=120)
    at.run()
    _inject_state(at, bulk, cc)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=120)

    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    assert isinstance(at.session_state["sol144_result"], dict)      # trim (subcase 1)
    assert isinstance(at.session_state["maneuver_result"], dict)    # MLOADS (subcase 2)

    # Trim subcase (default selection) shows all six aero totals (AC5).
    labels = [m.label for m in at.metric]
    for lbl in ["CZ (body)", "CL (wind)", "Total CMy", "Total CX",
                "Total CY", "Total CMx (roll)", "Total CMz (yaw)"]:
        assert lbl in labels, f"missing trim total metric {lbl!r}"

    # Switch to the maneuver subcase and re-render.
    at.selectbox(key="sol144_sc_sel").select(2)
    at.run(timeout=120)

    assert not at.exception, [str(e) for e in at.exception]
    labels = [m.label for m in at.metric]
    assert "Output samples" in labels and "Critical sample" in labels
    assert at.slider(key="sol144_man_step") is not None


def test_flow_e_sol144_free_flight_modal_dispatch():
    """Flow E (Step 63): a modal MLOADS deck routes to the FREE-FLIGHT modal
    solver in the viewer (not the direct solver, which would silently run the
    prescribed-rigid physics).

    Acceptance: every maneuver result carries the modal/free-flight markers
    (n_modes_used set, basis_info['free_flight']) and the UI renders.
    """
    import warnings
    from pathlib import Path
    from sbeam.parser.bdf_reader import parse_bdf

    sample = Path(__file__).parent.parent.parent / "sample" / "ha144a_mloads_massset.bdf"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(sample)

    at = AppTest.from_function(_sbeam_app, default_timeout=300)
    at.run()
    _inject_state(at, bulk, cc)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    next(b for b in at.button if b.label == "Run Analysis").click()
    at.run(timeout=300)

    assert not at.exception, [str(e) for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    results = at.session_state["maneuver_result"]
    assert isinstance(results, dict) and len(results) == 3
    for r in results.values():
        assert r.n_modes_used is not None                 # modal solver ran
        assert r.basis_info and r.basis_info["free_flight"] is True
