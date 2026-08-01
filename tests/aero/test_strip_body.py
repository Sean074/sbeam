"""Decoupled strip body panels (PSTRIP/STRIPK) + strip body correction.

Validates the new strip panel type and ``build_strip_body_correction``:
  - the parser round-trips PSTRIP (marker + default slope) and STRIPK (per-box slope),
    and rejects an out-of-place STRIPK / a PID that is neither PAERO1 nor PSTRIP;
  - the assembled operator's strip block is purely DIAGONAL with zero coupling to or
    from the lifting surfaces, and the lifting-surface inverse is bit-identical with or
    without the strip present (exact decoupling — overlap is harmless);
  - a nominal π-slope strip yields a sectional lift-curve slope of π ("50% normal");
  - the correction drives the TOTAL airplane Cm_α/Cm0/Cn_β/Cn0/Cl_β/Cl0 onto the targets,
    verified by a full rebuild from the emitted STRIPK + W2GJ cards.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl
from sbeam.aero.integration import build_djx
from sbeam.aero.strip import strip_box_mask, strip_box_slopes, is_strip_caero
from sbeam.aero.body_correction import (
    BodyTargets,
    build_strip_body_correction,
    strip_body_cards_to_bdf,
    _ref_geometry,
    _total_metrics,
)
from sbeam.model.aero import Stripk, W2gj

_ROOT = Path(__file__).parent.parent.parent / "sample"
STRIP_BDF = _ROOT / "cessna210_strip.bdf"
BODY_BDF = _ROOT / "cessna210_body.bdf"

_HORIZ, _VERT = 6000, 7000


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def _parse(text: str):
    return parse_bulk_data(text.splitlines())


def test_pstrip_default_slope():
    bulk = _parse(
        "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
        "PSTRIP, 20\n"
        "CAERO1, 400, 20, 0, 1, 1, 0, 0, 1\n"
        "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
    )
    assert 20 in bulk.pstrips
    assert bulk.pstrips[20].slope0 == pytest.approx(np.pi)


def test_pstrip_explicit_slope_and_stripk():
    bulk = _parse(
        "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
        "PSTRIP, 20, 2.5\n"
        "CAERO1, 400, 20, 0, 1, 2, 0, 0, 1\n"
        "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
        "STRIPK, 9501, 400, 3.0, 4.0\n"
    )
    assert bulk.pstrips[20].slope0 == pytest.approx(2.5)
    assert bulk.stripks[9501].caero_eid == 400
    assert bulk.stripks[9501].data == [3.0, 4.0]


def test_stripk_must_target_a_strip_panel():
    with pytest.raises(ValueError, match="not a strip panel"):
        _parse(
            "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
            "PAERO1, 10\n"
            "CAERO1, 100, 10, 0, 1, 1, 0, 0, 1\n"
            "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
            "STRIPK, 9501, 100, 3.0\n"
        )


def test_caero_pid_must_resolve_to_paero1_or_pstrip():
    with pytest.raises(ValueError, match="not found in PAERO1 or PSTRIP"):
        _parse(
            "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
            "CAERO1, 100, 99, 0, 1, 1, 0, 0, 1\n"
            "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
        )


def test_pstrip_pid_collision_with_paero1():
    with pytest.raises(ValueError, match="collides with a PAERO1"):
        _parse(
            "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
            "PAERO1, 20\n"
            "PSTRIP, 20\n"
        )


# --------------------------------------------------------------------------- #
# Operator structure — decoupling
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def strip_model():
    _cc, bulk = parse_bdf(str(STRIP_BDF))
    return bulk, build_aero_model(bulk)


def test_strip_boxes_flagged(strip_model):
    bulk, model = strip_model
    mask = strip_box_mask(bulk, model.boxes)
    # 6000: 2x8=16 boxes, 7000: 4x8=32 boxes → 48 strip boxes
    assert mask.sum() == 48
    assert all(b.is_strip == m for b, m in zip(model.boxes, mask))
    assert is_strip_caero(bulk, _HORIZ) and is_strip_caero(bulk, _VERT)
    assert not is_strip_caero(bulk, 1000)   # wing is ordinary VLM


def test_strip_block_is_diagonal_and_uncoupled(strip_model):
    bulk, model = strip_model
    mask = strip_box_mask(bulk, model.boxes)
    s = np.where(mask)[0]
    v = np.where(~mask)[0]
    A = model.ajj_inv_corr
    # No coupling either direction between lifting surfaces and the strip body.
    assert np.abs(A[np.ix_(v, s)]).max() == 0.0
    assert np.abs(A[np.ix_(s, v)]).max() == 0.0
    # Strip block is purely diagonal.
    sblk = A[np.ix_(s, s)]
    assert np.abs(sblk - np.diag(np.diag(sblk))).max() == 0.0
    # Diagonal equals -slope (default π, incompressible).
    assert np.allclose(np.diag(sblk), -np.pi)


def test_lifting_surface_inverse_unchanged_by_strip(strip_model):
    """The wing/HTP/VTP block is bit-identical to a flying-surface-only build."""
    bulk, model = strip_model
    mask = strip_box_mask(bulk, model.boxes)
    v = np.where(~mask)[0]
    wing_block = model.ajj_inv_corr[np.ix_(v, v)]

    flying = dataclasses.replace(
        bulk,
        caero1s={e: c for e, c in bulk.caero1s.items() if e not in (_HORIZ, _VERT)},
        spline0s={},
    )
    model_f = build_aero_model(flying)
    assert model_f.ajj_inv_corr.shape == wing_block.shape
    assert np.array_equal(model_f.ajj_inv_corr, wing_block)


def test_overlap_is_harmless(strip_model):
    """Moving a strip panel on top of the wing changes the wing loads by exactly zero."""
    bulk, model = strip_model
    mask = strip_box_mask(bulk, model.boxes)
    v = np.where(~mask)[0]
    base_wing = model.ajj_inv_corr[np.ix_(v, v)]

    # Relocate the horizontal strip body so it sits squarely inside the wing planform.
    moved = dataclasses.replace(bulk, caero1s=dict(bulk.caero1s))
    h = moved.caero1s[_HORIZ]
    moved.caero1s[_HORIZ] = dataclasses.replace(
        h, p1=(2.05, 0.0, 1.30), p4=(2.05, 5.0, 1.40))
    model_m = build_aero_model(moved)
    mask_m = strip_box_mask(moved, model_m.boxes)
    v_m = np.where(~mask_m)[0]
    assert np.array_equal(model_m.ajj_inv_corr[np.ix_(v_m, v_m)], base_wing)


# --------------------------------------------------------------------------- #
# Strip slope semantics
# --------------------------------------------------------------------------- #

def test_pi_slope_gives_sectional_cl_slope_pi():
    """A nominal π-slope horizontal strip ⇒ sectional lift-curve slope π."""
    bulk = _parse(
        "AEROS, 0, 0, 1.0, 2.0, 2.0, 0, 0, 0.0\n"
        "PSTRIP, 20\n"
        "CAERO1, 400, 20, 0, 2, 4, 0, 0, 1\n"
        "+, 0.0, -1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0\n"
    )
    model = build_aero_model(bulk)
    alpha = 0.1
    res = solve_rigid_cl(model.boxes, alpha, aeros=model.aeros, wg=model.wg,
                         cp_operator=model.ajj_inv_corr)
    for cl in res["cl_section"].values():
        assert cl == pytest.approx(np.pi * alpha, rel=1e-9)


def test_raw_solve_rejects_strip_without_operator(strip_model):
    _bulk, model = strip_model
    with pytest.raises(ValueError, match="decoupled strip body panels"):
        solve_rigid_cl(model.boxes, 0.05, aeros=model.aeros, cp_operator=None)


def test_strip_box_slopes_uses_stripk_override():
    bulk = _parse(
        "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
        "PSTRIP, 20, 2.0\n"
        "CAERO1, 400, 20, 0, 1, 3, 0, 0, 1\n"
        "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
        "STRIPK, 9501, 400, 1.1, 1.2, 1.3\n"
    )
    model = build_aero_model(bulk)
    slopes = strip_box_slopes(bulk, model.boxes)
    assert list(slopes) == [1.1, 1.2, 1.3]
    # operator diagonal = -slope
    assert np.allclose(np.diag(model.ajj_inv_corr), [-1.1, -1.2, -1.3])


# --------------------------------------------------------------------------- #
# Strip body correction
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def strip_baseline(strip_model):
    bulk, model = strip_model
    labels = ["ANGLEA", "SIDES"]
    djx = build_djx(model.boxes, labels, bulk)
    x_ref, ref_pt = _ref_geometry(bulk)
    base = _total_metrics(model, bulk, djx, labels, x_ref, ref_pt)
    return base, labels, x_ref, ref_pt


def test_strip_correction_hits_all_targets_on_rebuild(strip_model, strip_baseline):
    bulk, model = strip_model
    base, labels, x_ref, ref_pt = strip_baseline
    tgt = BodyTargets(
        cm_alpha=base.cm_alpha - 0.15, cm0=base.cm0 + 0.02,
        cn_beta=base.cn_beta + 0.05, cn0=base.cn0 - 0.01,
        cl_beta=base.cl_beta - 0.01, cl0=base.cl0 + 0.005,
    )
    res = build_strip_body_correction(
        bulk, horiz_eid=_HORIZ, vert_eid=_VERT, targets=tgt, aero=model)
    assert res.converged
    assert max(abs(v) for v in res.residual.values()) < 1e-9

    # Apply the emitted STRIPK + W2GJ cards and rebuild from scratch.
    w2 = {w.sid: w for (w, _sk) in res.cards.values()}
    sk = {s.sid: s for (_w, s) in res.cards.values()}
    bulk_c = dataclasses.replace(
        bulk, w2gjs={**bulk.w2gjs, **w2}, stripks={**bulk.stripks, **sk})
    model_c = build_aero_model(bulk_c)
    djx = build_djx(model_c.boxes, labels, bulk_c)
    ach = _total_metrics(model_c, bulk_c, djx, labels, x_ref, ref_pt)
    for name, t in (("cm_alpha", tgt.cm_alpha), ("cm0", tgt.cm0),
                    ("cn_beta", tgt.cn_beta), ("cn0", tgt.cn0),
                    ("cl_beta", tgt.cl_beta), ("cl0", tgt.cl0)):
        assert getattr(ach, name) == pytest.approx(t, abs=1e-9), name


def test_strip_correction_emits_w2gj_and_stripk_cards(strip_model, strip_baseline):
    bulk, model = strip_model
    base, *_ = strip_baseline
    tgt = BodyTargets(cm_alpha=base.cm_alpha - 0.1, cn_beta=base.cn_beta + 0.02,
                      cl_beta=base.cl_beta)
    res = build_strip_body_correction(
        bulk, horiz_eid=_HORIZ, vert_eid=_VERT, targets=tgt, aero=model)
    assert sorted(res.cards) == [_HORIZ, _VERT]
    for eid, (w2, sk) in res.cards.items():
        assert isinstance(w2, W2gj)
        assert isinstance(sk, Stripk)
        nbox = sum(1 for b in model.boxes if b.caero_eid == eid)
        assert len(w2.data) == nbox and len(sk.data) == nbox
        assert w2.caero_eid == eid and sk.caero_eid == eid
    # distinct SIDs for the two panels
    sids = [sk.sid for (_w, sk) in res.cards.values()]
    assert len(set(sids)) == 2
    # round-trips to bulk-data text
    assert "STRIPK" in strip_body_cards_to_bdf(res)


def test_strip_correction_rejects_non_strip_panel():
    _cc, bulk = parse_bdf(str(BODY_BDF))   # cruciform deck: 6000/7000 are PAERO1
    with pytest.raises(ValueError, match="not a strip panel"):
        build_strip_body_correction(
            bulk, horiz_eid=6000, targets=BodyTargets(cm_alpha=0.1))


def test_strip_correction_does_not_touch_flying_surfaces(strip_model, strip_baseline):
    """Flying-surface span loads are identical before/after the body build (decoupling)."""
    bulk, model = strip_model
    base, *_ = strip_baseline
    mask = strip_box_mask(bulk, model.boxes)
    v = np.where(~mask)[0]

    res = build_strip_body_correction(
        bulk, horiz_eid=_HORIZ, vert_eid=_VERT,
        targets=BodyTargets(cm_alpha=base.cm_alpha - 0.2, cn_beta=base.cn_beta + 0.1,
                            cl_beta=base.cl_beta), aero=model)
    w2 = {w.sid: w for (w, _sk) in res.cards.values()}
    sk = {s.sid: s for (_w, s) in res.cards.values()}
    bulk_c = dataclasses.replace(
        bulk, w2gjs={**bulk.w2gjs, **w2}, stripks={**bulk.stripks, **sk})
    model_c = build_aero_model(bulk_c)
    # The lifting-surface rows of the operator are unchanged by the body correction.
    assert np.array_equal(model.ajj_inv_corr[np.ix_(v, v)],
                          model_c.ajj_inv_corr[np.ix_(v, v)])


# --------------------------------------------------------------------------- #
# DEF-L1 — STRIPK binding and length must not be silently lenient
# --------------------------------------------------------------------------- #

_STRIP_DECK = (
    "AEROS, 0, 0, 1.0, 1.0, 1.0, 0, 0, 0.0\n"
    "PSTRIP, 20, 2.5\n"
    "CAERO1, 400, 20, 0, 1, 4, 0, 0, 1\n"
    "+, 0.0, -0.5, 0.0, 1.0, 0.0, 0.5, 0.0, 1.0\n"
)


def _strip_boxes(bulk):
    from sbeam.aero.panel import mesh_caero1
    from sbeam.model.aero import Paero1
    caero = bulk.caero1s[400]
    return mesh_caero1(caero, Paero1(pid=caero.pid), bulk.aefacts, bulk.cord2rs)


def test_short_stripk_raises_instead_of_falling_back_to_slope0():
    """A short STRIPK used to silently use PSTRIP SLOPE0 for the rest.

    That is indistinguishable from a deck that meant the default, so a
    miscounted card quietly changed the body lift-curve slope.
    """
    bulk = _parse(_STRIP_DECK + "STRIPK, 9501, 400, 1.1, 1.2\n")   # 2 of 4
    with pytest.raises(ValueError, match=r"STRIPK 9501: 2 slope values .* 4 boxes"):
        strip_box_slopes(bulk, _strip_boxes(bulk))


def test_long_stripk_raises():
    bulk = _parse(_STRIP_DECK + "STRIPK, 9501, 400, 1.1, 1.2, 1.3, 1.4, 1.5\n")
    with pytest.raises(ValueError, match=r"STRIPK 9501: 5 slope values .* 4 boxes"):
        strip_box_slopes(bulk, _strip_boxes(bulk))


def test_duplicate_stripk_per_caero_raises():
    """Two STRIPKs on one CAERO1: the second used to lose to `setdefault`."""
    bulk = _parse(_STRIP_DECK
                  + "STRIPK, 9501, 400, 1.1, 1.2, 1.3, 1.4\n"
                  + "STRIPK, 9502, 400, 9.1, 9.2, 9.3, 9.4\n")
    with pytest.raises(ValueError, match=r"STRIPK 9502: CAERO1 400 already has"):
        strip_box_slopes(bulk, _strip_boxes(bulk))


def test_exact_length_stripk_is_applied():
    bulk = _parse(_STRIP_DECK + "STRIPK, 9501, 400, 1.1, 1.2, 1.3, 1.4\n")
    np.testing.assert_allclose(
        strip_box_slopes(bulk, _strip_boxes(bulk)), [1.1, 1.2, 1.3, 1.4])


def test_no_stripk_still_uses_the_pstrip_default():
    """Omitting the card entirely stays the documented way to take SLOPE0."""
    bulk = _parse(_STRIP_DECK)
    np.testing.assert_allclose(
        strip_box_slopes(bulk, _strip_boxes(bulk)), [2.5] * 4)
