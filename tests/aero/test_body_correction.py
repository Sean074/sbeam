"""Cruciform body-panel total-aircraft moment correction (Step A9).

Validates ``sbeam.aero.body_correction`` on the refined Cessna 210 deck:
  - the body panels drive the TOTAL airplane Cm_α, Cm0, Cn_β, Cn0 onto the targets;
  - the analytic ``achieved`` matches what ``build_aero_model`` actually assembles
    (production-path cross-check) and the flying-surface load is untouched (decoupling);
  - the emitted W2GJ/WT2 cards have the right shape;
  - horizontal-only / vertical-only modes and the CSV TOTAL block parse correctly.

To keep AIC rebuilds down, the flying-corrected model is built once (module fixture)
and reused via the ``aero=`` argument of ``build_body_correction``.
"""

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd
from sbeam.aero.body_correction import (
    BodyTargets,
    build_body_correction,
    parse_body_targets,
    split_total_rows,
    _ref_geometry,
    _total_metrics,
)
from sbeam.aero.integration import build_djx
from sbeam.model.aero import Aecorr, W2gj
from sbeam.solver.sol144 import _pitch_moment

_ROOT = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = _ROOT / "cessna210_body.bdf"
CSV_PATH = _ROOT / "cessna210_body_section_data.csv"

_HORIZ, _VERT = 400, 500


@pytest.fixture(scope="module")
def flying():
    """Flying-corrected bulk + its AeroModel + baseline totals (built once)."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    model = build_aero_model(bulk)
    df = pd.read_csv(CSV_PATH)
    flying_rows, _totals = split_total_rows(df)
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, flying_rows, mach=0.0, incidence_deg=3.0,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    assert res.skipped == []
    w2 = {w.sid: w for (w, _a) in res.correction.cards.values()}
    ac = {a.sid: a for (_w, a) in res.correction.cards.values()}
    bulk_f = dataclasses.replace(
        bulk, w2gjs={**bulk.w2gjs, **w2}, aecorrs={**bulk.aecorrs, **ac})
    aero_f = build_aero_model(bulk_f)
    x_ref, ref_pt = _ref_geometry(bulk_f)
    d_jx = build_djx(aero_f.boxes, ["ANGLEA", "SIDES"], bulk_f)
    base = _total_metrics(aero_f, bulk_f, d_jx, ["ANGLEA", "SIDES"], x_ref, ref_pt)
    return bulk_f, df, aero_f, base


@pytest.fixture(scope="module")
def both_result(flying):
    bulk_f, _df, aero_f, base = flying
    tgt = BodyTargets(cm_alpha=base.cm_alpha + 0.30, cm0=base.cm0 - 0.06,
                      cn_beta=base.cn_beta - 0.05, cn0=base.cn0 + 0.004,
                      cl_beta=base.cl_beta + 0.04, cl0=base.cl0 + 0.003)
    res = build_body_correction(bulk_f, horiz_eid=_HORIZ, vert_eid=_VERT,
                                targets=tgt, aero=aero_f, mach=0.0)
    return tgt, res


def test_split_and_parse_total_block():
    df = pd.read_csv(CSV_PATH)
    flying_rows, totals = split_total_rows(df)
    assert len(totals) == 1 and len(flying_rows) == len(df) - 1
    assert not (flying_rows["var"].astype(str).str.upper() == "TOTAL").any()
    sd.validate_section_data(flying_rows)   # flying rows pass the ordinary validator
    tgt = parse_body_targets(df, mach=0.0)
    assert tgt == BodyTargets(cm_alpha=-6.9, cm0=-0.55, cn_beta=0.52, cn0=0.005,
                              cl_beta=-0.24, cl0=0.003)
    assert parse_body_targets(df, mach=0.7) is None   # no TOTAL row at this Mach


def test_body_correction_hits_all_targets(both_result):
    tgt, res = both_result
    assert res.converged
    assert res.achieved.cm_alpha == pytest.approx(tgt.cm_alpha, abs=1e-6)
    assert res.achieved.cm0 == pytest.approx(tgt.cm0, abs=1e-6)
    assert res.achieved.cn_beta == pytest.approx(tgt.cn_beta, abs=1e-6)
    assert res.achieved.cn0 == pytest.approx(tgt.cn0, abs=1e-6)
    assert res.achieved.cl_beta == pytest.approx(tgt.cl_beta, abs=1e-6)
    assert res.achieved.cl0 == pytest.approx(tgt.cl0, abs=1e-6)
    assert sorted(res.cards) == [_HORIZ, _VERT]
    assert res.ratio_max < 5.0


def test_body_cards_shape(both_result):
    _tgt, res = both_result
    w2h, ach = res.cards[_HORIZ]
    assert isinstance(w2h, W2gj) and isinstance(ach, Aecorr)
    assert ach.method == "WT2" and ach.caero_eid == _HORIZ
    assert len(w2h.data) == 16 and len(ach.target) == 16   # horizontal: 2 x 8 boxes
    w2v, acv = res.cards[_VERT]
    assert len(w2v.data) == 32 and len(acv.target) == 32   # vertical: 4 x 8 boxes


def test_production_path_and_decoupling(flying, both_result):
    """One real rebuild: the analytic achieved must equal the assembled model, and
    the flying surfaces' own contribution must be untouched by the body cards."""
    bulk_f, _df, aero_f, _base = flying
    tgt, res = both_result
    bw2 = {w.sid: w for (w, _a) in res.cards.values()}
    bac = {a.sid: a for (_w, a) in res.cards.values()}
    bulk_b = dataclasses.replace(
        bulk_f, w2gjs={**bulk_f.w2gjs, **bw2}, aecorrs={**bulk_f.aecorrs, **bac})
    aero_b = build_aero_model(bulk_b)
    x_ref, ref_pt = _ref_geometry(bulk_b)
    d_jx = build_djx(aero_b.boxes, ["ANGLEA", "SIDES"], bulk_b)
    assembled = _total_metrics(aero_b, bulk_b, d_jx, ["ANGLEA", "SIDES"], x_ref, ref_pt)

    # production assembly == analytic achieved == target (all six)
    for k in ("cm_alpha", "cm0", "cn_beta", "cn0", "cl_beta", "cl0"):
        assert getattr(assembled, k) == pytest.approx(getattr(res.achieved, k), abs=1e-9)
    assert assembled.cm0 == pytest.approx(tgt.cm0, abs=1e-6)
    assert assembled.cl_beta == pytest.approx(tgt.cl_beta, abs=1e-6)

    # decoupling: the flying surfaces' own pitch contribution is unchanged
    def flying_cm_alpha(aero, bulk):
        f = aero.skj @ (aero.ajj_inv_corr @ d_jx[:, 0])
        for k, b in enumerate(aero.boxes):
            if b.caero_eid in (_HORIZ, _VERT):
                f[3 * k:3 * k + 3] = 0.0
        return _pitch_moment(f, aero.boxes, x_ref) / (bulk.aeros.sref * bulk.aeros.cref)

    assert flying_cm_alpha(aero_f, bulk_f) == pytest.approx(
        flying_cm_alpha(aero_b, bulk_b), abs=1e-9)


def test_single_panel_modes(flying):
    bulk_f, _df, aero_f, base = flying
    tgt = BodyTargets(cm_alpha=base.cm_alpha - 0.4, cm0=base.cm0 - 0.05,
                      cn_beta=base.cn_beta + 0.08, cn0=base.cn0 + 0.01,
                      cl_beta=base.cl_beta + 0.03, cl0=base.cl0 + 0.002)
    rh = build_body_correction(bulk_f, horiz_eid=_HORIZ, targets=tgt,
                               aero=aero_f, mach=0.0)
    assert sorted(rh.cards) == [_HORIZ] and rh.converged
    assert rh.achieved.cm_alpha == pytest.approx(tgt.cm_alpha, abs=1e-6)
    # vertical panel alone matches the full sideslip set: yaw AND roll
    rv = build_body_correction(bulk_f, vert_eid=_VERT, targets=tgt,
                               aero=aero_f, mach=0.0)
    assert sorted(rv.cards) == [_VERT] and rv.converged
    assert rv.achieved.cn_beta == pytest.approx(tgt.cn_beta, abs=1e-6)
    assert rv.achieved.cl_beta == pytest.approx(tgt.cl_beta, abs=1e-6)


def test_requires_a_panel(flying):
    bulk_f, _df, aero_f, _base = flying
    with pytest.raises(ValueError):
        build_body_correction(bulk_f, targets=BodyTargets(), aero=aero_f, mach=0.0)
