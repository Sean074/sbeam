"""S44 — Aero viewer smoke tests.

Acceptance: AppTest renders without at.exception for a sample 4×10 rectangular-wing
BulkData; no numerical values asserted.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros, Caero1, Paero1
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.viewer.aero_view import (
    build_aero_box_figure, build_span_loading_figure, rigid_derivative_table,
)

_SAMPLE = Path(__file__).parent.parent.parent / "sample"


@pytest.fixture
def aero_bulk() -> BulkData:
    """Flat rectangular wing: 1 m chord × 4 m span, 4 spanwise × 10 chordwise boxes."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=4.0, sref=4.0, symxz=0, symxy=0)
    bulk.caero1s[100] = Caero1(
        eid=100, pid=1, cp=0,
        nspan=4, nchord=10,
        lspan=0, lchord=0,
        igid=1,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 4.0, 0.0), x43=1.0,
    )
    bulk.paero1s[1] = Paero1(pid=1)
    return bulk


def test_build_aero_box_figure_no_crash(aero_bulk):
    """Figure builder does not raise with no cp data."""
    aero_model = build_aero_model(aero_bulk)
    fig = build_aero_box_figure(aero_bulk, aero_model)
    assert isinstance(fig, go.Figure)


def test_build_aero_box_figure_with_cp_no_crash(aero_bulk):
    """Figure builder does not raise when cp and cl_section are provided."""
    aero_model = build_aero_model(aero_bulk)
    result = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    fig = build_aero_box_figure(
        aero_bulk, aero_model,
        cp=result["cp"],
        cl_section=result["cl_section"],
    )
    assert isinstance(fig, go.Figure)


def test_build_aero_box_figure_with_corr_no_crash(aero_bulk):
    """Figure builder does not raise when cp_corr overlay is provided."""
    aero_model = build_aero_model(aero_bulk)
    result = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    cp = result["cp"]
    cp_corr = cp * 1.1  # synthetic corrected values
    fig = build_aero_box_figure(
        aero_bulk, aero_model,
        cp=cp,
        cp_corr=cp_corr,
    )
    assert isinstance(fig, go.Figure)


def test_build_aero_box_figure_strip_false_no_crash(aero_bulk):
    """Scene-only figure (strip=False) for the Aero tab does not raise."""
    aero_model = build_aero_model(aero_bulk)
    result = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    fig = build_aero_box_figure(aero_bulk, aero_model, cp=result["cp"], strip=False)
    assert isinstance(fig, go.Figure)


# ---- rigid_derivative_table -------------------------------------------------

def test_rigid_derivative_table_shape_and_naming(aero_bulk):
    """Full S&C matrix: 5 rigid-body rows × 6 coefficient columns, both namings."""
    aero_model = build_aero_model(aero_bulk)
    df_aero = rigid_derivative_table(aero_model, aero_bulk, naming="aero")
    df_raw = rigid_derivative_table(aero_model, aero_bulk, naming="raw")
    assert isinstance(df_aero, pd.DataFrame)
    assert list(df_aero.index) == ["α", "β", "p", "q", "r"]
    assert list(df_aero.columns) == ["CZ", "CY", "Cl", "Cm", "Cn", "CX"]
    assert list(df_raw.index) == ["ANGLEA", "SIDES", "ROLL", "PITCH", "YAW"]
    assert list(df_raw.columns) == ["CZ", "CY", "CMX", "CMY", "CMZ", "CX"]
    # Toggle only relabels — the numbers are identical.
    assert np.allclose(df_aero.to_numpy(), df_raw.to_numpy())


def test_rigid_derivative_table_clalpha_crosscheck(aero_bulk):
    """ANGLEA→CZ (per rad, Skj integration) matches the single-point CL/α (K-J).

    The table column is the body-axis vertical-force coefficient CZ; at the α≈0
    linearisation point it equals the wind-axis lift slope to first order, so it
    cross-checks against ``solve_rigid_cl``'s ``CL`` (also a body-z vertical-force sum).
    """
    aero_model = build_aero_model(aero_bulk)
    alpha = np.radians(3.0)
    res = solve_rigid_cl(
        aero_model.boxes, alpha, aeros=aero_model.aeros,
        cp_operator=aero_model.ajj_inv_corr,
    )
    df = rigid_derivative_table(aero_model, aero_bulk, naming="aero")
    cla_table = df.loc["α", "CZ"]
    cla_pt = res["CL"] / alpha
    assert cla_table == pytest.approx(cla_pt, rel=1e-2)
    assert cla_table > 0.0


def test_rigid_derivative_table_none_without_aeros(aero_bulk):
    """No AEROS reference → no normalisation → None."""
    aero_model = build_aero_model(aero_bulk)
    aero_bulk.aeros = None
    assert rigid_derivative_table(aero_model, aero_bulk) is None


def test_rigid_derivative_table_includes_aesurf_rows():
    """AESURF control labels appear as rows below the rigid-body labels."""
    _cc, bulk = parse_bdf(str(_SAMPLE / "ha144a_fullspan_sbeam.bdf"))
    aero_model = build_aero_model(bulk)
    df = rigid_derivative_table(aero_model, bulk, naming="raw")
    assert df.index[:5].tolist() == ["ANGLEA", "SIDES", "ROLL", "PITCH", "YAW"]
    assert "ELEV" in df.index.tolist()


# ---- build_span_loading_figure ---------------------------------------------

def test_build_span_loading_figure_single_surface(aero_bulk):
    """One surface → cn + cm subplots = 2 traces; +uncorrected overlay = 4."""
    aero_model = build_aero_model(aero_bulk)
    res = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    fig = build_span_loading_figure(aero_model.boxes, res["cp"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2          # cn(η) + cm(η), one surface
    fig2 = build_span_loading_figure(aero_model.boxes, res["cp"], cp_unc=res["cp"] * 0.9)
    assert len(fig2.data) == 4         # corrected + uncorrected, two subplots


def test_build_span_loading_figure_multi_surface():
    """Each CAERO1 surface gets its own line in both subplots (no i_span merge)."""
    _cc, bulk = parse_bdf(str(_SAMPLE / "ha144a_fullspan_sbeam.bdf"))
    aero_model = build_aero_model(bulk)
    res = solve_rigid_cl(
        aero_model.boxes, np.radians(3.0), aeros=aero_model.aeros,
        cp_operator=aero_model.ajj_inv_corr,
    )
    n_surf = len({b.caero_eid for b in aero_model.boxes})
    fig = build_span_loading_figure(aero_model.boxes, res["cp"])
    assert len(fig.data) == 2 * n_surf


def test_build_span_loading_figure_modes(aero_bulk):
    """uncorrected/diff modes draw one curve pair per surface (no dashed overlay)."""
    aero_model = build_aero_model(aero_bulk)
    res = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    cp = res["cp"]
    unc = cp * 0.9
    # uncorrected: single pair (no overlay); diff: single pair of difference curves.
    assert len(build_span_loading_figure(aero_model.boxes, cp, cp_unc=unc,
                                         mode="uncorrected").data) == 2
    fig_diff = build_span_loading_figure(aero_model.boxes, cp, cp_unc=unc, mode="diff")
    assert len(fig_diff.data) == 2
    assert "Δcn" in fig_diff.layout.annotations[0].text
    # diff with no baseline falls back to corrected (no crash, single pair here).
    assert isinstance(build_span_loading_figure(aero_model.boxes, cp, mode="diff"), go.Figure)


def test_build_aero_box_figure_cp_diff_diverging(aero_bulk):
    """Δcp view: centred diverging colour scale and ΔCp colour-bar title, no crash."""
    aero_model = build_aero_model(aero_bulk)
    res = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
    dcp = res["cp"] - res["cp"] * 0.9
    fig = build_aero_box_figure(aero_bulk, aero_model, cp=dcp, strip=False,
                                cp_cmid=0.0, cp_title="ΔCp")
    mesh = next(t for t in fig.data if isinstance(t, go.Mesh3d))
    assert mesh.cmid == 0.0
    assert mesh.colorbar.title.text == "ΔCp"


def _sbeam_app():
    from sbeam.viewer.app import main
    main()


def _inject_aero_state(at: AppTest, bulk: BulkData) -> None:
    """Inject an aero-capable BulkData into session state without case control."""
    at.session_state["bulk_data"] = bulk
    at.session_state["case_control"] = None
    at.session_state["_loaded_from_file_cc"] = None
    at.session_state["sol101_result"] = None
    at.session_state["sol103_result"] = None
    at.session_state["aero_model"] = None
    at.session_state["aero_result"] = None
    at.session_state["selected_gid"] = None
    at.session_state["selected_eid"] = None
    at.session_state["cc_subcases"] = None
    at.session_state["selected_subcase_id"] = None
    at.session_state["_parse_warnings"] = []
    at.session_state["_parse_error"] = None
    at.session_state["_uploaded_file_id"] = None
    at.session_state["_uploaded_filename"] = "test_aero.dat"


def test_apptest_aero_tab_no_exception(aero_bulk):
    """AppTest: aero tab renders without exception for a 4×10 rectangular-wing bulk."""
    at = AppTest.from_function(_sbeam_app, default_timeout=30)
    at.run()
    _inject_aero_state(at, aero_bulk)
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any(b.label == "Compute Aero" for b in at.button)


def test_apptest_aero_tab_renders_results(aero_bulk):
    """AppTest: the full-width derivative table (Styler), naming radio, and span-load
    figure render without exception when a precomputed aero result is in session."""
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_aero_state(at, aero_bulk)
    aero_model = build_aero_model(aero_bulk)
    result = solve_rigid_cl(
        aero_model.boxes, np.radians(3.0), aeros=aero_model.aeros,
        wg=aero_model.wg, cp_operator=aero_model.ajj_inv_corr,
    )
    at.session_state["aero_model"] = aero_model
    at.session_state["aero_result"] = result
    at.session_state["aero_result_unc"] = None
    at.run()

    assert not at.exception, [str(e) for e in at.exception]
    assert any(r.label == "Naming" for r in at.radio)
