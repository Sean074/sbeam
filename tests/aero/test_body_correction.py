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

import numpy as np
import pandas as pd
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam_tools.corrections import section_data as sd
from sbeam.aero.body_correction import (
    BodyTargets,
    build_body_correction,
    RATIO_WARN,
    _ref_geometry,
    _total_metrics,
)
from sbeam_tools.corrections import parse_body_targets, split_total_rows
from sbeam.aero.integration import build_djx
from sbeam.model.aero import Aecorr, W2gj
from sbeam.solver.sol144 import pitch_moment

_ROOT = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = _ROOT / "cessna210_flagship_body.bdf"
STRIP_BDF_PATH = _ROOT / "cessna210_flagship_body_strip_drv.bdf"
CSV_PATH = _ROOT / "cessna210_flagship_section_data.csv"

_HORIZ, _VERT = 6000, 7000


@pytest.fixture(scope="module")
def flying(flagship_cruciform_uncorrected):
    """Flying-corrected bulk + its AeroModel + baseline totals.

    The flagship deck ships its flying-surface correction already committed, so
    unlike the retired cessna210_body deck there is nothing to synthesise here —
    the shared fixture just removes the committed BODY cards, leaving exactly the
    input the body-correction builders expect.
    """
    _cc, bulk_f, aero_f, _gi, _w = flagship_cruciform_uncorrected
    df = pd.read_csv(CSV_PATH)
    x_ref, ref_pt = _ref_geometry(bulk_f)
    d_jx = build_djx(aero_f.boxes, ["ANGLEA", "SIDES"], bulk_f)
    base = _total_metrics(aero_f, bulk_f, d_jx, ["ANGLEA", "SIDES"], x_ref, ref_pt)
    return bulk_f, df, aero_f, base


@pytest.fixture(scope="module")
def both_result(flying):
    bulk_f, _df, aero_f, base = flying
    # Increments are exercise values, not physical anchors — but they have to stay
    # inside what this panel pair can legitimately supply.  On the flagship geometry
    # the roll ask is the binding one: +0.04 in Cl_beta drives the WT2 ratio past
    # RATIO_WARN, which is the builder correctly reporting that a flat-plate
    # cruciform is being asked for more than a fuselage stand-in should give.
    tgt = BodyTargets(cm_alpha=base.cm_alpha + 0.30, cm0=base.cm0 - 0.06,
                      cn_beta=base.cn_beta - 0.05, cn0=base.cn0 + 0.004,
                      cl_beta=base.cl_beta + 0.015, cl0=base.cl0 + 0.003)
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
    # Realistic totals = flying-surface baseline + a small fuselage increment (mild
    # destabilising pitch/yaw, ~0 roll); see the deck header and 05_aeroelastics.md.
    assert tgt == BodyTargets(cm_alpha=-1.4921, cm0=-0.0404, cn_beta=0.0772, cn0=0.0,
                              cl_beta=-0.0364, cl0=0.0)
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
    # The WT2 ratio is NOT a contamination metric: WT2 is a post-inverse diagonal on the
    # body rows only, so it never perturbs the lifting surfaces (see test_production_path_
    # and_decoupling).  Panels held clear of the tail are weakly coupled, so a ratio of
    # tens is normal and benign; we only require it stays inside the sane (sub-warn) band.
    assert res.ratio_max < RATIO_WARN


def test_body_cards_shape(both_result):
    _tgt, res = both_result
    w2h, ach = res.cards[_HORIZ]
    assert isinstance(w2h, W2gj) and isinstance(ach, Aecorr)
    assert ach.method == "WT2" and ach.caero_eid == _HORIZ
    assert len(w2h.data) == 16 and len(ach.target) == 16   # horizontal: 2 x 8 boxes
    w2v, acv = res.cards[_VERT]
    assert len(w2v.data) == 32 and len(acv.target) == 32   # vertical: 2 x 16 boxes


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
        return pitch_moment(f, aero.boxes, x_ref) / (bulk.aeros.sref * bulk.aeros.cref)

    assert flying_cm_alpha(aero_f, bulk_f) == pytest.approx(
        flying_cm_alpha(aero_b, bulk_b), abs=1e-9)


def test_single_panel_modes(flying):
    bulk_f, _df, aero_f, base = flying
    # Small increments: the clean (clear-of-tail) vertical panel is weakly coupled, so a
    # large yaw/roll target would need a big (benign) WT2 ratio; keep it in the sane band.
    tgt = BodyTargets(cm_alpha=base.cm_alpha - 0.4, cm0=base.cm0 - 0.05,
                      cn_beta=base.cn_beta + 0.02, cn0=base.cn0 + 0.005,
                      cl_beta=base.cl_beta + 0.008, cl0=base.cl0 + 0.002)
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


def test_eid_int_and_singleton_list_equivalent(flying):
    """A bare int EID and a one-element list must give identical results (backward compat)."""
    bulk_f, _df, aero_f, base = flying
    tgt = BodyTargets(cm_alpha=base.cm_alpha + 0.2, cm0=base.cm0 - 0.01,
                      cn_beta=base.cn_beta, cn0=base.cn0,
                      cl_beta=base.cl_beta, cl0=base.cl0)
    a = build_body_correction(bulk_f, horiz_eid=_HORIZ, targets=tgt, aero=aero_f, mach=0.0)
    b = build_body_correction(bulk_f, horiz_eid=[_HORIZ], targets=tgt, aero=aero_f, mach=0.0)
    assert sorted(a.cards) == sorted(b.cards) == [_HORIZ]
    assert a.achieved.cm_alpha == pytest.approx(b.achieved.cm_alpha, abs=1e-12)
    assert a.ratio_max == pytest.approx(b.ratio_max, abs=1e-12)


def test_multi_surface_body_plane():
    """A body plane may be split across several CAERO1s; all are tuned by one joint solve
    and each emits its own card pair.  Here the vertical body is two panels (the deck's
    7000 plus a ventral piece 8000)."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    for store in (bulk.w2gjs, bulk.aecorrs, bulk.stripks):
        for sid in [s for s, c in store.items() if c.caero_eid in (6000, 7000)]:
            del store[sid]
    c500 = bulk.caero1s[7000]
    # second vertical body panel (ventral, below 7000 — distinct z band, clear of the tail)
    bulk.caero1s[8000] = dataclasses.replace(
        c500, eid=8000, nspan=2, nchord=16,
        p1=(0.30, 0.0, -0.35), x12=4.70, p4=(0.30, 0.0, -0.05), x43=4.70)
    model = build_aero_model(bulk)
    # vertical body is now two panels (both +Y), horizontal one panel (+Z)
    nv510 = [b for b in model.boxes if b.caero_eid == 8000]
    assert len(nv510) == 32 and abs(np.mean([b.normal[1] for b in nv510])) > 0.99

    df = pd.read_csv(CSV_PATH)
    flying_rows, _totals = split_total_rows(df)
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, flying_rows, mach=0.0, incidence_deg=3.0,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    w2 = {w.sid: w for (w, _a) in res.correction.cards.values()}
    ac = {a.sid: a for (_w, a) in res.correction.cards.values()}
    bulk_f = dataclasses.replace(
        bulk, w2gjs={**bulk.w2gjs, **w2}, aecorrs={**bulk.aecorrs, **ac})
    aero_f = build_aero_model(bulk_f)
    x_ref, ref_pt = _ref_geometry(bulk_f)
    d_jx = build_djx(aero_f.boxes, ["ANGLEA", "SIDES"], bulk_f)
    base = _total_metrics(aero_f, bulk_f, d_jx, ["ANGLEA", "SIDES"], x_ref, ref_pt)

    tgt = BodyTargets(cm_alpha=base.cm_alpha + 0.3, cm0=base.cm0 - 0.02,
                      cn_beta=base.cn_beta - 0.03, cn0=base.cn0 + 0.002,
                      cl_beta=base.cl_beta - 0.005, cl0=base.cl0)
    out = build_body_correction(bulk_f, horiz_eid=6000, vert_eid=[7000, 8000],
                                targets=tgt, aero=aero_f, mach=0.0)
    assert out.converged
    assert sorted(out.cards) == [6000, 7000, 8000]            # one card pair per panel
    w2v0, _ = out.cards[7000]
    w2v1, _ = out.cards[8000]
    assert w2v0.sid != w2v1.sid                            # distinct SIDs per panel
    for k in ("cm_alpha", "cm0", "cn_beta", "cn0", "cl_beta", "cl0"):
        assert getattr(out.achieved, k) == pytest.approx(getattr(tgt, k), abs=1e-6)
    assert out.ratio_max < RATIO_WARN


# --------------------------------------------------------------------------- #
# DEF-L1 — required TOTAL columns and cruciform/strip panel binding
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("col", ["cm_a", "cm0", "cn_a", "a0"])
def test_blank_required_total_column_raises(col):
    """A blank required column used to become a silent NaN.

    Only the roll columns (cl_a/cl0) are optional; the other four went through a
    bare float(), so a blank cell produced BodyTargets(cm_alpha=nan, ...) that
    propagated all the way into the min-norm solve without a word.
    """
    df = pd.read_csv(CSV_PATH)
    totals = df["var"].astype(str).str.upper() == "TOTAL"
    df.loc[totals, col] = np.nan
    with pytest.raises(ValueError, match=rf"blank/non-numeric '{col}'"):
        parse_body_targets(df, mach=0.0)


def test_blank_optional_roll_column_still_defaults_to_zero():
    """The documented optional-column behaviour must be preserved."""
    df = pd.read_csv(CSV_PATH)
    totals = df["var"].astype(str).str.upper() == "TOTAL"
    df.loc[totals, "cl_a"] = np.nan
    df.loc[totals, "cl0"] = np.nan
    tgt = parse_body_targets(df, mach=0.0)
    assert tgt is not None
    assert tgt.cl_beta == 0.0 and tgt.cl0 == 0.0


def test_cruciform_builder_rejects_a_strip_panel():
    """A PSTRIP panel has no AIC coupling, so the cruciform solve cannot tune it.

    It used to be accepted and then never actually corrected.
    """
    _cc, bulk = parse_bdf(str(STRIP_BDF_PATH))
    with pytest.raises(ValueError, match=r"CAERO1 6000 is a PSTRIP body panel"):
        build_body_correction(
            bulk, horiz_eid=6000, targets=BodyTargets(cm_alpha=0.1))
