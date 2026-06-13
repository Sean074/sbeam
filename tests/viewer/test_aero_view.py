"""S44 — Aero viewer smoke tests.

Acceptance: AppTest renders without at.exception for a sample 4×10 rectangular-wing
BulkData; no numerical values asserted.
"""
from __future__ import annotations

import numpy as np
import pytest
import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros, Caero1, Paero1
from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.aero.vlm import solve_rigid_cl
from sbeam.viewer.aero_view import build_aero_box_figure


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
