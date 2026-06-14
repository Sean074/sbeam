"""Aero Correction tab — section data → correction cards GUI front end.

Acceptance:
  * the CSV template round-trips back to the section_data schema (one row per strip
    per surface);
  * cards built from a section table, when injected into the model, are picked up by
    ``build_aero_model`` and drive the corrected solve to the prescribed section slope
    (the "run in the Aero tab" path);
  * the AppTest page renders, exposes the Build button once a table is loaded, and the
    Apply button injects W2GJ/AECORR cards into the in-session model without stacking on
    a re-apply.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from sbeam.model.bulk_data import BulkData
from sbeam.model.aero import Aeros, Caero1, Paero1
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl
from sbeam.aero import section_data as sd
from sbeam.viewer.aero_correction_view import _template_csv, _W2GJ_BASE, _AECORR_BASE


@pytest.fixture
def aero_bulk() -> BulkData:
    """Flat rectangular wing: 1 m chord × 4 m span, 4 spanwise × 10 chordwise boxes."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=4.0, sref=4.0, symxz=0, symxy=0)
    bulk.caero1s[100] = Caero1(
        eid=100, pid=1, cp=0,
        nspan=4, nchord=10, lspan=0, lchord=0, igid=1,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 4.0, 0.0), x43=1.0,
    )
    bulk.paero1s[1] = Paero1(pid=1)
    return bulk


def _half_slope_df(aero_model) -> pd.DataFrame:
    """Template seeded onto the mesh strips with the section slope halved (offsets 0).

    The default template slope is the 2-D thin-airfoil value 2π/rad; halving it gives a
    uniform target section slope of π/rad, so the corrected CL integrates to π·α.
    """
    df = sd.template_dataframe(aero_model.boxes, 100, mach=0.0, a_lo=-2.0, a_hi=8.0)
    df["cn_a"] = df["cn_a"] * 0.5
    return sd.validate_section_data(df)


# ---- _template_csv ----------------------------------------------------------

def test_template_csv_roundtrips_schema(aero_bulk):
    aero_model = build_aero_model(aero_bulk)
    csv = _template_csv(aero_model)
    df = sd.validate_section_data(pd.read_csv(io.StringIO(csv)))
    assert list(df.columns) == sd.COLUMNS
    n_strips = len({b.i_span for b in aero_model.boxes})
    assert len(df) == n_strips          # one row per span strip of the single surface
    assert set(df["caero"]) == {100}


# ---- build → inject → corrected solve round-trip ----------------------------

def test_built_cards_change_corrected_solve(aero_bulk):
    """Injecting the generated cards drives the corrected CL to the target section slope."""
    aero_model = build_aero_model(aero_bulk)
    df = _half_slope_df(aero_model)
    res = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, incidence_deg=2.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    assert set(res.correction.cards) == {100}

    alpha = np.radians(2.0)
    cl_unc = solve_rigid_cl(
        aero_model.boxes, alpha, aeros=aero_model.aeros,
        cp_operator=aero_model.ajj_inv_corr,        # no cards yet → raw VLM
    )["CL"]

    # Inject the generated pair and rebuild — the Aero tab's exact path.
    w2, ac = res.correction.cards[100]
    aero_bulk.w2gjs[w2.sid] = w2
    aero_bulk.aecorrs[ac.sid] = ac
    corr_model = build_aero_model(aero_bulk)
    cl_corr = solve_rigid_cl(
        corr_model.boxes, alpha, aeros=corr_model.aeros,
        wg=corr_model.wg, cp_operator=corr_model.ajj_inv_corr,
    )["CL"]

    # Target section slope is π/rad uniformly → CL_corr = π·α; and below the finite-wing
    # VLM slope (~4/rad), so the correction reduces lift.
    assert cl_corr < cl_unc
    assert cl_corr == pytest.approx(np.pi * alpha, rel=0.02)


# ---- AppTest smoke ----------------------------------------------------------

def _sbeam_app():
    from sbeam.viewer.app import main
    main()


def _inject_bulk(at: AppTest, bulk: BulkData) -> None:
    at.session_state["bulk_data"] = bulk
    at.session_state["case_control"] = None
    at.session_state["_loaded_from_file_cc"] = None
    at.session_state["_parse_warnings"] = []
    at.session_state["_parse_error"] = None
    at.session_state["_uploaded_file_id"] = None
    at.session_state["_uploaded_filename"] = "test_aero.dat"


def test_apptest_correction_tab_renders(aero_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_bulk(at, aero_bulk)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Tab body rendered (section-data step header present).
    assert any("Section-data table" in m.value for m in at.markdown)


def test_apptest_build_button_appears_with_table(aero_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_bulk(at, aero_bulk)
    aero_model = build_aero_model(aero_bulk)
    at.session_state["aero_corr_df"] = _half_slope_df(aero_model)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any(b.label == "Build correction cards" for b in at.button)


def test_apptest_apply_injects_without_stacking(aero_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_bulk(at, aero_bulk)
    aero_model = build_aero_model(aero_bulk)
    df = _half_slope_df(aero_model)
    res = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, incidence_deg=2.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    at.session_state["aero_corr_df"] = df
    at.session_state["aero_corr_result"] = res
    at.run()
    assert not at.exception, [str(e) for e in at.exception]

    next(b for b in at.button if b.key == "aero_corr_apply").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    bulk_after = at.session_state["bulk_data"]
    assert _AECORR_BASE in bulk_after.aecorrs
    assert _W2GJ_BASE in bulk_after.w2gjs

    # Re-apply: the tool clears its prior SIDs first, so the model holds exactly one pair.
    next(b for b in at.button if b.key == "aero_corr_apply").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    bulk_after = at.session_state["bulk_data"]
    assert len(bulk_after.w2gjs) == 1
    assert len(bulk_after.aecorrs) == 1
