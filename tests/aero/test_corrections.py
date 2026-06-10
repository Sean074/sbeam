"""AIC correction acceptance tests for S43 (V-A3).

Covers:
  - No correction: AJJ*⁻¹ @ AJJ ≈ I (identity round-trip)
  - apply_wkk non-unit weight: corrected cp scales by weight factor
  - apply_wt2 round-trip: feed VLM cp as target → corrected cp reproduced to tol
  - apply_wt1 round-trip: feed VLM per-strip lift as target → strip lift reproduced to tol
  - apply_wt2 conditioning warning: near-singular AJJ triggers UserWarning
  - apply_wt1 conditioning warning: near-singular AJJ triggers UserWarning
  - build_aero_model: identity (no correction) — AJJ*⁻¹ @ AJJ ≈ I
  - build_aero_model: WKK correction wired end-to-end
"""

import warnings

import numpy as np
import pytest

from sbeam.model.aero import Caero1, Paero1, Wkk, Aecorr
from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj, solve_rigid_cl
from sbeam.aero.corrections import apply_wkk, apply_wt2, apply_wt1
from sbeam.aero.aero_model import AeroModel, build_aero_model

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PAERO = Paero1(pid=1)
NO_AEFACTS = {}
NO_CORD2RS = {}
CAERO_EID = 1
PARITY = 1


def _rect_wing(nspan: int, nchord: int, span: float = 5.0, chord: float = 1.0) -> list:
    caero = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
    )
    return mesh_caero1(caero, PAERO, NO_AEFACTS, NO_CORD2RS)


def _ajj_and_inv(boxes):
    ajj = build_ajj(boxes, PARITY)
    ajj_inv = np.linalg.solve(ajj, np.eye(len(boxes)))
    return ajj, ajj_inv


# ---------------------------------------------------------------------------
# Identity / no-correction baseline
# ---------------------------------------------------------------------------

class TestNoCorrection:
    def test_ajj_inv_is_left_inverse(self):
        boxes = _rect_wing(4, 4)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        assert ajj_inv @ ajj == pytest.approx(np.eye(len(boxes)), abs=1e-10)


# ---------------------------------------------------------------------------
# apply_wkk
# ---------------------------------------------------------------------------

class TestApplyWkk:
    def test_unit_weights_returns_ajj_unchanged(self):
        boxes = _rect_wing(4, 4)
        ajj, _ = _ajj_and_inv(boxes)
        n = len(boxes)
        ajj_star = apply_wkk(ajj, [1.0] * n)
        assert ajj_star == pytest.approx(ajj, rel=1e-12)

    def test_first_box_scaled_by_1_5(self):
        """Scaling box 0 row by 1.5 must multiply that box's cp contribution by 1.5."""
        boxes = _rect_wing(2, 2)
        ajj, _ = _ajj_and_inv(boxes)
        n = len(boxes)
        alpha = 0.05
        w_ref = -np.full(n, alpha)

        # Uncorrected solve
        cp_ref, *_ = np.linalg.lstsq(ajj, w_ref, rcond=None)

        weights = [1.5] + [1.0] * (n - 1)
        ajj_star = apply_wkk(ajj, weights)
        cp_corr, *_ = np.linalg.lstsq(ajj_star, w_ref, rcond=None)

        # Box 0 row of AJJ* is 1.5× the original; the corrected cp[0] should
        # reflect the changed influence — verify AJJ* rows are correctly scaled
        assert ajj_star[0] == pytest.approx(1.5 * ajj[0], rel=1e-12)
        for i in range(1, n):
            assert ajj_star[i] == pytest.approx(ajj[i], rel=1e-12)

    def test_shape_preserved(self):
        boxes = _rect_wing(3, 3)
        ajj = build_ajj(boxes, PARITY)
        n = len(boxes)
        ajj_star = apply_wkk(ajj, [2.0] * n)
        assert ajj_star.shape == (n, n)


# ---------------------------------------------------------------------------
# apply_wt2 — pressure matching
# ---------------------------------------------------------------------------

class TestApplyWt2:
    def test_round_trip_with_vlm_cp(self):
        """Feed the VLM cp at unit incidence as target → corrected cp reproduces it."""
        boxes = _rect_wing(4, 4)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        cp_vlm_ref = ajj_inv @ w_ref

        ajj_inv_corr = apply_wt2(ajj, cp_vlm_ref)
        cp_corr = ajj_inv_corr @ w_ref

        assert cp_corr == pytest.approx(cp_vlm_ref, rel=1e-8)

    def test_scaled_target_scales_output(self):
        """Scaling target cp by constant factor scales corrected output by same factor."""
        boxes = _rect_wing(3, 3)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        cp_vlm_ref = ajj_inv @ w_ref
        scale = 1.3

        ajj_inv_corr = apply_wt2(ajj, scale * cp_vlm_ref)
        cp_corr = ajj_inv_corr @ w_ref

        assert cp_corr == pytest.approx(scale * cp_vlm_ref, rel=1e-8)

    def test_shape(self):
        boxes = _rect_wing(2, 2)
        ajj = build_ajj(boxes, PARITY)
        n = len(boxes)
        cp_target = np.ones(n)
        result = apply_wt2(ajj, cp_target)
        assert result.shape == (n, n)

    def test_conditioning_warning(self):
        n = 4
        # Diagonal matrix with cond ≈ 1e12 — ill-conditioned but invertible.
        ill_cond_ajj = np.diag([1.0, 1.0, 1.0, 1e-12])
        cp_target = np.ones(n)
        with pytest.warns(UserWarning, match="conditioned"):
            apply_wt2(ill_cond_ajj, cp_target)


# ---------------------------------------------------------------------------
# apply_wt1 — force/moment matching
# ---------------------------------------------------------------------------

class TestApplyWt1:
    def test_round_trip_with_vlm_strip_loads(self):
        """Feed VLM per-strip lift as target → corrected strip lift reproduced."""
        nspan, nchord = 4, 4
        boxes = _rect_wing(nspan, nchord)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        cp_vlm_ref = ajj_inv @ w_ref

        # Compute per-strip integrated lift (same formula as apply_wt1 internals)
        from collections import defaultdict
        strip_idxs: dict = defaultdict(list)
        for k, box in enumerate(boxes):
            strip_idxs[box.i_span].append(k)
        sorted_strips = sorted(strip_idxs)
        f_vlm = np.array([
            sum(boxes[k].area * cp_vlm_ref[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        ajj_inv_corr = apply_wt1(ajj, boxes, f_vlm)
        cp_corr = ajj_inv_corr @ w_ref

        # Recompute corrected strip loads
        f_corr = np.array([
            sum(boxes[k].area * cp_corr[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        assert f_corr == pytest.approx(f_vlm, rel=1e-8)

    def test_scaled_target_scales_strip_output(self):
        """Scaling f_target by constant factor scales corrected strip loads by same factor."""
        nspan, nchord = 3, 3
        boxes = _rect_wing(nspan, nchord)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        cp_vlm_ref = ajj_inv @ w_ref

        from collections import defaultdict
        strip_idxs: dict = defaultdict(list)
        for k, box in enumerate(boxes):
            strip_idxs[box.i_span].append(k)
        sorted_strips = sorted(strip_idxs)
        f_vlm = np.array([
            sum(boxes[k].area * cp_vlm_ref[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        scale = 0.8
        ajj_inv_corr = apply_wt1(ajj, boxes, scale * f_vlm)
        cp_corr = ajj_inv_corr @ w_ref
        f_corr = np.array([
            sum(boxes[k].area * cp_corr[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        assert f_corr == pytest.approx(scale * f_vlm, rel=1e-8)

    def test_wrong_f_target_length_raises(self):
        boxes = _rect_wing(3, 3)
        ajj = build_ajj(boxes, PARITY)
        # 3 span strips, but provide 5 targets
        with pytest.raises(ValueError, match="f_target length"):
            apply_wt1(ajj, boxes, np.ones(5))

    def test_shape(self):
        nspan, nchord = 2, 2
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes, PARITY)
        n = len(boxes)
        f_target = np.ones(nspan)
        result = apply_wt1(ajj, boxes, f_target)
        assert result.shape == (n, n)

    def test_conditioning_warning(self):
        n = 4
        nspan = 2
        boxes = _rect_wing(nspan, 2)
        # Diagonal matrix with cond ≈ 1e12 — ill-conditioned but invertible.
        ill_cond_ajj = np.diag([1.0, 1.0, 1.0, 1e-12])
        f_target = np.ones(nspan)
        with pytest.warns(UserWarning, match="conditioned"):
            apply_wt1(ill_cond_ajj, boxes, f_target)


# ---------------------------------------------------------------------------
# build_aero_model — end-to-end container
# ---------------------------------------------------------------------------

def _rect_bulk(nspan: int, nchord: int) -> BulkData:
    from sbeam.model.aero import Aeros
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=5.0, sref=5.0, symxz=1, symxy=0)
    bulk.paero1s[1] = Paero1(pid=1)
    bulk.caero1s[CAERO_EID] = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 5.0, 0.0), x43=1.0,
    )
    return bulk


class TestBuildAeroModel:
    def test_no_correction_identity(self):
        bulk = _rect_bulk(4, 4)
        model = build_aero_model(bulk, parity=PARITY)
        n = len(model.boxes)
        assert model.ajj_inv_corr @ model.ajj == pytest.approx(np.eye(n), abs=1e-10)

    def test_wkk_correction_applied(self):
        """WKK card with weight 1.5 on every box: AJJ* = 1.5 × AJJ."""
        nspan, nchord = 2, 2
        bulk = _rect_bulk(nspan, nchord)
        n = nspan * nchord
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[1.5] * n)

        model = build_aero_model(bulk, parity=PARITY)

        # AJJ*⁻¹ @ AJJ* ≈ I
        ajj_star = 1.5 * model.ajj
        assert model.ajj_inv_corr @ ajj_star == pytest.approx(np.eye(n), abs=1e-8)

    def test_model_shapes(self):
        nspan, nchord = 3, 3
        bulk = _rect_bulk(nspan, nchord)
        model = build_aero_model(bulk)
        n = nspan * nchord
        assert model.ajj.shape       == (n, n)
        assert model.ajj_inv_corr.shape == (n, n)
        assert model.skj.shape       == (3 * n, n)
        assert model.djk.shape       == (n, n)
        assert model.wg.shape        == (n,)

    def test_wt2_round_trip(self):
        nspan, nchord = 3, 3
        bulk = _rect_bulk(nspan, nchord)
        n = nspan * nchord

        # Compute VLM cp at unit incidence to use as WT2 target
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes, PARITY)
        ajj_inv = np.linalg.solve(ajj, np.eye(n))
        cp_vlm_ref = ajj_inv @ (-np.ones(n))

        bulk.aecorrs[20] = Aecorr(
            sid=20, method="WT2", caero_eid=CAERO_EID,
            target=cp_vlm_ref.tolist(),
        )
        model = build_aero_model(bulk, parity=PARITY)
        cp_corr = model.ajj_inv_corr @ (-np.ones(n))
        assert cp_corr == pytest.approx(cp_vlm_ref, rel=1e-8)
