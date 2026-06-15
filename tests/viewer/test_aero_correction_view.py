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
from sbeam.aero.section_correction import cards_to_bdf
from sbeam.parser.bdf_reader import parse_bulk_file
from sbeam.viewer.aero_view import surface_dihedral_deg
from sbeam.aero import body_correction as bc
from sbeam.aero.integration import build_djx
from sbeam.viewer.aero_correction_view import (
    _template_csv, _W2GJ_BASE, _AECORR_BASE,
    _BODY_W2GJ_BASE, _BODY_AECORR_BASE, _guess_body_panels,
    build_corrected_bdf, suggest_corrected_name,
)


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


@pytest.fixture
def multi_bulk() -> BulkData:
    """Horizontal wing (CAERO 100, α) + a 45°-canted V-tail (CAERO 300, β)."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=4.0, sref=4.0, symxz=0, symxy=0)
    bulk.caero1s[100] = Caero1(
        eid=100, pid=1, cp=0,
        nspan=4, nchord=6, lspan=0, lchord=0, igid=1,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 4.0, 0.0), x43=1.0,
    )
    s = 2.0 ** 0.5 / 2.0 * 2.0  # span 2 at 45° → Δy = Δz = √2
    bulk.caero1s[300] = Caero1(
        eid=300, pid=1, cp=0,
        nspan=3, nchord=4, lspan=0, lchord=0, igid=2,
        p1=(3.0, 0.0, 0.0), x12=0.6,
        p4=(3.0, s, s), x43=0.6,
    )
    bulk.paero1s[1] = Paero1(pid=1)
    return bulk


def _multi_df(boxes) -> pd.DataFrame:
    """Section table: wing as ALPHA (region covers α=2), tail as BETA (covers β=-4 only)."""
    df_w = sd.template_dataframe(boxes, 100, mach=0.0, var="ALPHA", a_lo=-2.0, a_hi=8.0)
    df_t = sd.template_dataframe(boxes, 300, mach=0.0, var="BETA", a_lo=-8.0, a_hi=-2.0)
    return sd.validate_section_data(pd.concat([df_w, df_t], ignore_index=True))


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


# ---- separate α / β operating points ----------------------------------------

def test_surface_var_and_mixed(multi_bulk):
    """surface_var reports the per-surface axis; a mixed surface returns 'MIXED'."""
    aero_model = build_aero_model(multi_bulk)
    df = _multi_df(aero_model.boxes)
    assert sd.surface_var(df, 100, 0.0) == "ALPHA"
    assert sd.surface_var(df, 300, 0.0) == "BETA"
    assert sd.surface_var(df, 999, 0.0) is None

    n300 = int((df["caero"] == 300).sum())
    mixed = df.copy()
    mixed.loc[mixed["caero"] == 300, "var"] = (["ALPHA", "BETA"] * n300)[:n300]
    assert sd.surface_var(mixed, 300, 0.0) == "MIXED"


def test_separate_alpha_beta_selects_region_per_var(multi_bulk):
    """α and β pick each surface's own region; a single incidence skips the β surface."""
    aero_model = build_aero_model(multi_bulk)
    df = _multi_df(aero_model.boxes)

    # α=2 (in the wing's region) and β=−4 (in the tail's region) → both surfaces build.
    both = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, alpha_deg=2.0, beta_deg=-4.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    assert set(both.correction.cards) == {100, 300}
    assert both.conditions[100].var == "ALPHA"
    assert both.conditions[300].var == "BETA"

    # Single-axis incidence=2: the wing builds; the tail's β region [-8,-2] excludes 2.
    one = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, incidence_deg=2.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    assert set(one.correction.cards) == {100}
    assert any(eid == 300 for eid, _ in one.skipped)


def test_mixed_var_surface_is_skipped(multi_bulk):
    aero_model = build_aero_model(multi_bulk)
    df = _multi_df(aero_model.boxes)
    df.loc[df["caero"] == 300, "var"] = (["ALPHA", "BETA"]
                                         * len(df[df["caero"] == 300]))[: len(df[df["caero"] == 300])]
    res = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, alpha_deg=2.0, beta_deg=-4.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    assert set(res.correction.cards) == {100}
    assert any(eid == 300 and "one axis" in why for eid, why in res.skipped)


# ---- dihedral helper + canted warning ---------------------------------------

def test_surface_dihedral_deg(multi_bulk):
    aero_model = build_aero_model(multi_bulk)
    assert surface_dihedral_deg(aero_model.boxes, 100) == pytest.approx(0.0, abs=1.0)
    assert surface_dihedral_deg(aero_model.boxes, 300) == pytest.approx(45.0, abs=2.0)


def test_apptest_canted_surface_warns(multi_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_bulk(at, multi_bulk)
    aero_model = build_aero_model(multi_bulk)
    at.session_state["aero_corr_df"] = _multi_df(aero_model.boxes)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("canted" in w.value for w in at.warning)


# ---- #2 regression: preview persists across surface change ------------------

def test_apptest_preview_persists_on_surface_change(multi_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=60)
    at.run()
    _inject_bulk(at, multi_bulk)
    aero_model = build_aero_model(multi_bulk)
    df = _multi_df(aero_model.boxes)
    res = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, alpha_deg=2.0, beta_deg=-4.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    at.session_state["aero_corr_df"] = df
    at.session_state["aero_corr_result"] = res
    at.session_state["aero_corr_cond"] = (0.0, 2.0, -4.0)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Switch the preview surface — the build result must survive the rerun.
    sel = next(s for s in at.selectbox if s.key == "aero_corr_preview")
    sel.set_value(300).run()
    assert not at.exception, [str(e) for e in at.exception]
    assert at.session_state["aero_corr_result"] is not None
    assert set(at.session_state["aero_corr_result"].correction.cards) == {100, 300}


# ---- full corrected BDF export ----------------------------------------------

def test_suggest_corrected_name():
    assert suggest_corrected_name("wing", 0.30, 2.0, 0.0) == "wing_M0p30_A2p0_B0p0.bdf"
    assert suggest_corrected_name("w", 0.0, -2.0, 1.5) == "w_M0p00_Am2p0_B1p5.bdf"


def test_full_corrected_bdf_roundtrips(aero_bulk, tmp_path):
    """The exported corrected BDF carries provenance and re-parses with the cards."""
    aero_model = build_aero_model(aero_bulk)
    df = _half_slope_df(aero_model)
    res = sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df,
        mach=0.0, alpha_deg=2.0, beta_deg=0.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
    )
    source = "BEGIN BULK\nGRID,1,,0.,0.,0.\nENDDATA\n"
    text = build_corrected_bdf(
        source, cards_to_bdf(res.correction),
        source_csv="cfd_wing_M030.csv", mach=0.0, alpha=2.0, beta=0.0,
        eids=[100], out_name="wing_M0p00_A2p0_B0p0.bdf", date="2026-06-14",
    )
    # Provenance header + condition recorded.
    assert "cfd_wing_M030.csv" in text
    assert "2026-06-14" in text
    assert "Mach 0" in text
    # Re-parses, and the correction cards are recovered.
    out = tmp_path / "corrected.bdf"
    out.write_text(text, encoding="utf-8")
    bulk2 = parse_bulk_file(str(out))
    assert _W2GJ_BASE in bulk2.w2gjs
    assert _AECORR_BASE in bulk2.aecorrs


# ---- Stage 6 · cruciform body panels ----------------------------------------

@pytest.fixture
def body_bulk() -> BulkData:
    """Wing (CAERO 100, +Z) + horizontal body panel (400, +Z) + vertical body
    panel (500, +Y), the two body panels running the full length (long chord)."""
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=4.0, sref=4.0, symxz=0, symxy=0)
    bulk.caero1s[100] = Caero1(
        eid=100, pid=1, cp=0, nspan=4, nchord=4, lspan=0, lchord=0, igid=1,
        p1=(1.0, 0.0, 0.0), x12=1.0, p4=(1.0, 4.0, 0.0), x43=1.0)
    bulk.caero1s[400] = Caero1(   # horizontal body panel (+Z), long chord
        eid=400, pid=1, cp=0, nspan=2, nchord=4, lspan=0, lchord=0, igid=1,
        p1=(0.0, -0.4, -0.2), x12=4.0, p4=(0.0, 0.4, -0.2), x43=4.0)
    bulk.caero1s[500] = Caero1(   # vertical body panel (+Y), long chord
        eid=500, pid=1, cp=0, nspan=2, nchord=4, lspan=0, lchord=0, igid=1,
        p1=(0.0, 0.0, -0.5), x12=4.0, p4=(0.0, 0.0, 0.5), x43=4.0)
    bulk.paero1s[1] = Paero1(pid=1)
    return bulk


def _wing_flying_result(aero_model):
    """A flying-surface section-correction result for the wing only (CAERO 100)."""
    df = sd.template_dataframe(aero_model.boxes, 100, mach=0.0, a_lo=-2.0, a_hi=8.0)
    df = sd.validate_section_data(df)
    return df, sd.build_from_section_data_multi(
        aero_model.boxes, aero_model.ajj, df, mach=0.0, incidence_deg=2.0,
        sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE)


def test_guess_body_panels(body_bulk):
    model = build_aero_model(body_bulk)
    assert _guess_body_panels(model) == (400, 500)   # largest-chord +Z / +Y surfaces


def test_apptest_body_stage_renders(body_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=90)
    at.run()
    _inject_bulk(at, body_bulk)
    model = build_aero_model(body_bulk)
    df, res = _wing_flying_result(model)
    at.session_state["aero_corr_df"] = df
    at.session_state["aero_corr_result"] = res
    at.session_state["aero_corr_cond"] = (0.0, 2.0, 0.0)
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    assert any("Body panels" in m.value for m in at.markdown)
    # horizontal/vertical body-panel pickers are multiselects (a plane may be several panels)
    keys = {s.key for s in at.multiselect}
    assert "aero_body_horiz" in keys and "aero_body_vert" in keys


def test_apptest_body_build_and_apply(body_bulk):
    at = AppTest.from_function(_sbeam_app, default_timeout=120)
    at.run()
    _inject_bulk(at, body_bulk)
    model = build_aero_model(body_bulk)
    df, res = _wing_flying_result(model)

    # flying-corrected baseline → gentle targets the body can reach
    fw2 = {w.sid: w for (w, _a) in res.correction.cards.values()}
    fac = {a.sid: a for (_w, a) in res.correction.cards.values()}
    import dataclasses
    bulk_f = dataclasses.replace(
        body_bulk, w2gjs={**body_bulk.w2gjs, **fw2},
        aecorrs={**body_bulk.aecorrs, **fac})
    aero_f = build_aero_model(bulk_f)
    d_jx = build_djx(aero_f.boxes, ["ANGLEA", "SIDES"], bulk_f)
    x_ref, ref_pt = bc._ref_geometry(bulk_f)
    base = bc._total_metrics(aero_f, bulk_f, d_jx, ["ANGLEA", "SIDES"], x_ref, ref_pt)

    at.session_state["aero_corr_df"] = df
    at.session_state["aero_corr_result"] = res
    at.session_state["aero_corr_cond"] = (0.0, 2.0, 0.0)
    # Small increments: panels held clear of the tail are weakly coupled, so a large
    # yaw/roll target would need a big (benign) WT2 ratio; keep it in the sane band.
    at.session_state["aero_body_cma"] = base.cm_alpha + 0.05
    at.session_state["aero_body_cm0"] = base.cm0 - 0.02
    at.session_state["aero_body_cnb"] = base.cn_beta - 0.01
    at.session_state["aero_body_cn0"] = base.cn0 + 0.005
    at.session_state["aero_body_clb"] = base.cl_beta + 0.005
    at.session_state["aero_body_cl0"] = base.cl0 + 0.002
    at.run()

    next(b for b in at.button if b.key == "aero_body_build").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    bres = at.session_state["aero_body_result"]
    assert bres is not None and bres.converged
    assert sorted(bres.cards) == [400, 500]
    assert bres.achieved.cl_beta == pytest.approx(base.cl_beta + 0.005, abs=1e-6)

    next(b for b in at.button if b.key == "aero_body_apply").click().run()
    assert not at.exception, [str(e) for e in at.exception]
    bulk_after = at.session_state["bulk_data"]
    # flying pairs + body pairs both present
    assert _AECORR_BASE in bulk_after.aecorrs and _W2GJ_BASE in bulk_after.w2gjs
    assert _BODY_W2GJ_BASE in bulk_after.w2gjs
    assert _BODY_AECORR_BASE in bulk_after.aecorrs
