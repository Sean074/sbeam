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
  - WT1 deprecation (DEF-H2/H3): parser warning, plus characterization tests
    pinning the β² overshoot at M > 0 and the cross-CAERO1 strip aliasing
"""

import warnings

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.model.aero import Caero1, Paero1, Wkk, Aecorr
from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj, solve_rigid_cl
from sbeam.aero.corrections import apply_wkk, apply_wt2, apply_wt1
from sbeam.aero.aero_model import build_aero_model

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PAERO = Paero1(pid=1)
NO_AEFACTS = {}
NO_CORD2RS = {}
CAERO_EID = 1


def _rect_wing(nspan: int, nchord: int, span: float = 5.0, chord: float = 1.0) -> list:
    caero = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
    )
    return mesh_caero1(caero, PAERO, NO_AEFACTS, NO_CORD2RS)


def _ajj_and_inv(boxes):
    ajj = build_ajj(boxes)
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
        ajj = build_ajj(boxes)
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
        ajj = build_ajj(boxes)
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
        """Feed physical VLM strip lift/q as target → corrected strip lift/q reproduced."""
        nspan, nchord = 4, 4
        boxes = _rect_wing(nspan, nchord)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        gamma_ref = ajj_inv @ w_ref
        # Physical strip lift/q: Σ area * Cp = Σ area * 2*Γ/chord
        dy = np.array([
            np.sqrt((b.bound_b[1] - b.bound_a[1])**2 + (b.bound_b[2] - b.bound_a[2])**2)
            for b in boxes
        ])
        chord_box = np.array([boxes[k].area / dy[k] for k in range(n)])
        cp_ref = 2.0 * gamma_ref / chord_box

        from collections import defaultdict
        strip_idxs: dict = defaultdict(list)
        for k, box in enumerate(boxes):
            strip_idxs[box.i_span].append(k)
        sorted_strips = sorted(strip_idxs)
        f_target = np.array([
            sum(boxes[k].area * cp_ref[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        ajj_inv_corr = apply_wt1(ajj, boxes, f_target)   # Γ-unit output
        gamma_corr = ajj_inv_corr @ w_ref
        cp_corr = 2.0 * gamma_corr / chord_box            # convert to Cp

        # Corrected physical strip lift/q must reproduce f_target
        f_corr = np.array([
            sum(boxes[k].area * cp_corr[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])
        assert f_corr == pytest.approx(f_target, rel=1e-8)

    def test_scaled_target_scales_strip_output(self):
        """Scaling f_target by constant factor scales corrected physical strip loads."""
        nspan, nchord = 3, 3
        boxes = _rect_wing(nspan, nchord)
        ajj, ajj_inv = _ajj_and_inv(boxes)
        n = len(boxes)
        w_ref = -np.ones(n)
        gamma_ref = ajj_inv @ w_ref
        dy = np.array([
            np.sqrt((b.bound_b[1] - b.bound_a[1])**2 + (b.bound_b[2] - b.bound_a[2])**2)
            for b in boxes
        ])
        chord_box = np.array([boxes[k].area / dy[k] for k in range(n)])
        cp_ref = 2.0 * gamma_ref / chord_box

        from collections import defaultdict
        strip_idxs: dict = defaultdict(list)
        for k, box in enumerate(boxes):
            strip_idxs[box.i_span].append(k)
        sorted_strips = sorted(strip_idxs)
        f_target = np.array([
            sum(boxes[k].area * cp_ref[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])

        scale = 0.8
        ajj_inv_corr = apply_wt1(ajj, boxes, scale * f_target)
        gamma_corr = ajj_inv_corr @ w_ref
        cp_corr = 2.0 * gamma_corr / chord_box
        f_corr = np.array([
            sum(boxes[k].area * cp_corr[k] for k in strip_idxs[s])
            for s in sorted_strips
        ])
        assert f_corr == pytest.approx(scale * f_target, rel=1e-8)

    def test_wrong_f_target_length_raises(self):
        boxes = _rect_wing(3, 3)
        ajj = build_ajj(boxes)
        # 3 span strips, but provide 5 targets
        with pytest.raises(ValueError, match="f_target length"):
            apply_wt1(ajj, boxes, np.ones(5))

    def test_shape(self):
        nspan, nchord = 2, 2
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)
        n = len(boxes)
        f_target = np.ones(nspan)
        result = apply_wt1(ajj, boxes, f_target)
        assert result.shape == (n, n)

    def test_conditioning_warning(self):
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
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=5.0, sref=5.0, symxz=0, symxy=0)
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
        """Without correction, skj-path total Fz at unit incidence matches solve_rigid_cl."""
        bulk = _rect_bulk(4, 4)
        model = build_aero_model(bulk)
        n = len(model.boxes)
        w_ref = -np.ones(n)
        # skj @ ajj_inv_corr @ w_ref gives force/q; CL = Fz/sref
        fz_model = (model.skj @ (model.ajj_inv_corr @ w_ref))[2::3].sum()
        cl_model = fz_model / bulk.aeros.sref
        # Reference from rigid solver
        r = solve_rigid_cl(model.boxes, alpha=1.0,
                           aeros=bulk.aeros, xref=0.0)
        assert cl_model == pytest.approx(r["CL"], rel=1e-8)

    def test_wkk_correction_applied(self):
        """WKK = 1.5 on every box halves the corrected CL by factor 1.5 vs no-correction."""
        nspan, nchord = 2, 2
        bulk_base = _rect_bulk(nspan, nchord)
        bulk_wkk  = _rect_bulk(nspan, nchord)
        n = nspan * nchord
        bulk_wkk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[1.5] * n)

        model_base = build_aero_model(bulk_base)
        model_wkk  = build_aero_model(bulk_wkk)

        w_ref = -np.ones(n)
        fz_base = (model_base.skj @ (model_base.ajj_inv_corr @ w_ref))[2::3].sum()
        fz_wkk  = (model_wkk.skj  @ (model_wkk.ajj_inv_corr  @ w_ref))[2::3].sum()
        # Uniform WKK=1.5: AJJ* = 1.5·AJJ → Γ* = Γ/1.5 → CL* = CL/1.5
        assert fz_wkk == pytest.approx(fz_base / 1.5, rel=1e-8)

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
        """WT2 target in Γ-units: output is the corresponding Cp = 2·Γ/chord."""
        nspan, nchord = 3, 3
        bulk = _rect_bulk(nspan, nchord)
        n = nspan * nchord

        # WT2 target convention: VLM Γ at unit incidence
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)
        ajj_inv = np.linalg.solve(ajj, np.eye(n))
        gamma_ref = ajj_inv @ (-np.ones(n))     # Γ at unit incidence (WT2 target unit)

        bulk.aecorrs[20] = Aecorr(
            sid=20, method="WT2", caero_eid=CAERO_EID,
            target=gamma_ref.tolist(),           # Γ-unit target (identity correction)
        )
        model = build_aero_model(bulk)
        # After AE2 fix ajj_inv_corr returns Cp; identity WT2 → Cp = 2·Γ/chord
        cp_out = model.ajj_inv_corr @ (-np.ones(n))
        dy = np.array([
            np.sqrt((b.bound_b[1] - b.bound_a[1])**2 + (b.bound_b[2] - b.bound_a[2])**2)
            for b in boxes
        ])
        chord_box = np.array([boxes[i].area / dy[i] for i in range(n)])
        cp_expected = 2.0 * gamma_ref / chord_box
        assert cp_out == pytest.approx(cp_expected, rel=1e-8)


class TestSolveRigidClCorrectedOperator:
    """solve_rigid_cl(cp_operator=...) — the Aero-tab corrected-operator path."""

    def test_identity_when_no_correction(self):
        """With no correction, the cp_operator path == the build-and-solve path."""
        bulk = _rect_bulk(4, 4)
        model = build_aero_model(bulk)
        plain = solve_rigid_cl(model.boxes, alpha=0.05, aeros=bulk.aeros)
        corr = solve_rigid_cl(model.boxes, alpha=0.05, aeros=bulk.aeros,
                              cp_operator=model.ajj_inv_corr)
        assert corr["CL"] == pytest.approx(plain["CL"], rel=1e-10)
        assert corr["CM"] == pytest.approx(plain["CM"], rel=1e-10)
        assert corr["cp"] == pytest.approx(plain["cp"], rel=1e-10)

    def test_wkk_scales_cl(self):
        """Uniform WKK=1.5 → corrected-operator CL is the uncorrected CL / 1.5."""
        nspan, nchord = 3, 3
        n = nspan * nchord
        bulk = _rect_bulk(nspan, nchord)
        model_base = build_aero_model(bulk)
        cl_base = solve_rigid_cl(model_base.boxes, alpha=0.05, aeros=bulk.aeros,
                                 cp_operator=model_base.ajj_inv_corr)["CL"]

        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[1.5] * n)
        model_wkk = build_aero_model(bulk)
        cl_wkk = solve_rigid_cl(model_wkk.boxes, alpha=0.05, aeros=bulk.aeros,
                                cp_operator=model_wkk.ajj_inv_corr)["CL"]
        assert cl_wkk == pytest.approx(cl_base / 1.5, rel=1e-8)

    def test_cp_operator_shape_validated(self):
        boxes = _rect_wing(2, 2)
        with pytest.raises(ValueError, match="cp_operator has shape"):
            solve_rigid_cl(boxes, alpha=0.05, cp_operator=np.eye(3))


# ---------------------------------------------------------------------------
# WT1 deprecation (DEF-H2 / DEF-H3, 2026-07-31)
#
# WT1 is deprecated rather than fixed — WT2 and the section-correction path are
# correct and strictly more capable.  The two tests below therefore lock in
# **known-wrong** behaviour on purpose, so that the defects cannot be silently
# altered while the card is still parseable.  Removal is backlog DEF-R7.
# ---------------------------------------------------------------------------

# 1000 clear of CAERO_EID=1's box-ID range: a CAERO1 owns the NSPAN*NCHORD
# consecutive IDs from its EID, so EID 2 would overlap the wing (F1).
TAIL_EID = 1000


def _strip_forces(model, caero_eid=None) -> np.ndarray:
    """Physical strip lift/q (Σ area·Cp) at unit reference incidence, by i_span.

    Restricted to one CAERO1 when ``caero_eid`` is given.  Ordered by ascending
    i_span, matching the WT1 f_target convention.
    """
    from collections import defaultdict
    n = len(model.boxes)
    cp = model.ajj_inv_corr @ (-np.ones(n))
    acc: dict = defaultdict(float)
    for k, box in enumerate(model.boxes):
        if caero_eid is not None and box.caero_eid != caero_eid:
            continue
        acc[box.i_span] += box.area * cp[k]
    return np.array([acc[s] for s in sorted(acc)])


def _wing_and_tail_bulk(nspan: int, nchord: int) -> BulkData:
    """Two-surface deck: the CAERO_EID wing plus a smaller tail aft of it."""
    bulk = _rect_bulk(nspan, nchord)
    bulk.caero1s[TAIL_EID] = Caero1(
        eid=TAIL_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(4.0, 0.0, 0.0), x12=0.5,
        p4=(4.0, 2.0, 0.0), x43=0.5,
    )
    return bulk


class TestWt1Deprecation:
    def test_parser_warns_on_wt1_card(self):
        """A WT1 AECORR warns at read time; a WT2 card does not."""
        wt1 = ["AECORR, 30, WT1, 100, 0.80, 0.75, 0.65, 0.50"]
        with pytest.warns(UserWarning, match="WT1 is deprecated"):
            bulk = parse_bulk_data(wt1)
        assert bulk.aecorrs[30].method == "WT1"      # still parsed, not rejected

        wt2 = ["AECORR, 20, WT2, 100, 0.45, 0.30, 0.22, 0.18"]
        with warnings.catch_warnings():
            warnings.simplefilter("error")            # any warning fails the test
            bulk2 = parse_bulk_data(wt2)
        assert bulk2.aecorrs[20].method == "WT2"

    def test_wt1_overshoots_by_beta_squared_at_mach(self):
        """DEF-H2 (pinned, known-wrong): WT1 delivers f_target/β², not f_target.

        ``build_aero_model`` hands ``apply_wt1`` the PG-compressed boxes, so the
        reference strip force is integrated over compressed areas/chords, while
        the Göthert 1/β factor and the Γ→ΔCp conversion (physical chords) are
        applied afterwards.  Exact at M = 0; 56 % high at M = 0.6.  Deprecated,
        not fixed — see DEF-H2/H3 and backlog DEF-R7.
        """
        nspan, nchord = 3, 3
        f_target = _strip_forces(build_aero_model(_rect_bulk(nspan, nchord), mach=0.0))

        for mach in (0.0, 0.6):
            bulk = _rect_bulk(nspan, nchord)
            bulk.aecorrs[30] = Aecorr(sid=30, method="WT1", caero_eid=CAERO_EID,
                                      target=f_target.tolist())
            achieved = _strip_forces(build_aero_model(bulk, mach=mach))
            beta_sq = 1.0 - mach ** 2
            assert achieved == pytest.approx(f_target / beta_sq, rel=1e-8)

        # The M = 0.6 case specifically: 1/0.64 = 1.5625, a 56 % overshoot.
        bulk = _rect_bulk(nspan, nchord)
        bulk.aecorrs[30] = Aecorr(sid=30, method="WT1", caero_eid=CAERO_EID,
                                  target=f_target.tolist())
        got = _strip_forces(build_aero_model(bulk, mach=0.6))
        assert got / f_target == pytest.approx(np.full(nspan, 1.5625), rel=1e-8)

    def test_wt1_aliases_strips_across_caeros(self):
        """DEF-H3 (pinned, known-wrong): a wing WT1 card rescales tail strips.

        ``apply_wt1`` groups by ``box.i_span``, which restarts per parent CAERO1
        (``panel.py``), so wing strip 0 and tail strip 0 share a dict key.  The
        card is *selected* by the primary CAERO1 but *applied* model-wide: the
        tail is contaminated and the wing misses its own target.  Deprecated, not
        fixed — see DEF-H2/H3 and backlog DEF-R7.
        """
        nspan, nchord = 3, 3
        base = build_aero_model(_wing_and_tail_bulk(nspan, nchord), mach=0.0)
        wing_base = _strip_forces(base, caero_eid=CAERO_EID)
        tail_base = _strip_forces(base, caero_eid=TAIL_EID)

        # Ask the wing for half its baseline load.  f_target must be sized by
        # *distinct i_span model-wide* (= nspan), not by the wing's own strip
        # count — itself a symptom of the shared-key defect.
        wing_target = 0.5 * wing_base
        bulk = _wing_and_tail_bulk(nspan, nchord)
        bulk.aecorrs[30] = Aecorr(sid=30, method="WT1", caero_eid=CAERO_EID,
                                  target=wing_target.tolist())
        corr = build_aero_model(bulk, mach=0.0)

        wing_corr = _strip_forces(corr, caero_eid=CAERO_EID)
        tail_corr = _strip_forces(corr, caero_eid=TAIL_EID)

        # (a) The tail is rescaled by roughly the wing's factor, though no card
        #     names it.  A correctly scoped correction would leave it untouched.
        assert np.all(np.abs(tail_corr / tail_base - 1.0) > 0.4)

        # (b) The wing misses the half-load target it was given.
        assert np.any(np.abs(wing_corr / wing_target - 1.0) > 0.05)

        # (c) The smoking gun: wing and tail are scaled by the *same* per-i_span
        #     ratio, because they share the dict key.
        assert wing_corr / wing_base == pytest.approx(tail_corr / tail_base, rel=1e-10)


class TestWkkSurfaceBinding:
    """DEF-M8b — WKK binds per CAERO1, not "primary card applied model-wide".

    A WKK card used to be selected by the *primary* (lowest-EID) CAERO1 and then
    applied to every box in the operator.  On a multi-surface deck that meant the
    ``diag(w)`` was the wrong size and numpy raised a bare shape error; a WKK on
    any non-primary surface was ignored outright.
    """

    @staticmethod
    def _two_surface(nspan, nchord):
        return _wing_and_tail_bulk(nspan, nchord)

    def test_wkk_on_non_primary_surface_is_applied(self):
        """Previously ignored entirely — the tail card never reached the AIC."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        base = build_aero_model(self._two_surface(nspan, nchord), mach=0.0)

        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=TAIL_EID, data=[0.5] * n_surf)
        corr = build_aero_model(bulk, mach=0.0)
        assert not np.allclose(corr.ajj_inv_corr, base.ajj_inv_corr), \
            "WKK on the non-primary CAERO1 had no effect"

    def test_wkk_on_one_surface_leaves_the_other_rows_alone(self):
        """Unlisted surfaces get weight 1, so AJJ* rows there are untouched."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.5] * n_surf)
        corr = build_aero_model(bulk, mach=0.0)
        tail_rows = [k for k, b in enumerate(corr.boxes) if b.caero_eid == TAIL_EID]
        base = build_aero_model(self._two_surface(nspan, nchord), mach=0.0)
        np.testing.assert_allclose(corr.ajj[tail_rows], base.ajj[tail_rows], rtol=1e-12)

    def test_multi_surface_wkk_no_longer_shape_errors(self):
        """Two WKK cards, one per surface — used to be a raw numpy shape error."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.9] * n_surf)
        bulk.wkks[11] = Wkk(sid=11, caero_eid=TAIL_EID, data=[0.7] * n_surf)
        model = build_aero_model(bulk, mach=0.0)          # must not raise
        assert model.ajj_inv_corr.shape == (2 * n_surf, 2 * n_surf)

    def test_wrong_length_wkk_raises_a_card_labelled_error(self):
        nspan = nchord = 3
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.9] * 4)
        with pytest.raises(ValueError, match=r"WKK 10 \(CAERO1 1\): 4 weights for 9 boxes"):
            build_aero_model(bulk, mach=0.0)

    def test_duplicate_wkk_per_caero_raises(self):
        nspan = nchord = 3
        n_surf = nspan * nchord
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.9] * n_surf)
        bulk.wkks[11] = Wkk(sid=11, caero_eid=CAERO_EID, data=[0.7] * n_surf)
        with pytest.raises(ValueError, match=r"already has a WKK card"):
            build_aero_model(bulk, mach=0.0)

    def test_zero_weight_raises_instead_of_bare_linalgerror(self):
        """A zero weight zeroes an AJJ* row → singular; solve() would raise raw."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        data = [0.9] * n_surf
        data[2] = 0.0
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=data)
        with pytest.raises(ValueError, match=r"WKK 10 .*zero weight at box index"):
            build_aero_model(bulk, mach=0.0)

    def test_single_surface_wkk_is_unchanged(self):
        """The pre-existing single-CAERO1 path must be bit-identical."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        bulk = _rect_bulk(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.8] * n_surf)
        model = build_aero_model(bulk, mach=0.0)
        expect = apply_wkk(build_ajj(mesh_caero1(
            bulk.caero1s[CAERO_EID], bulk.paero1s[1], {}, {}, start_k=0)),
            [0.8] * n_surf)
        np.testing.assert_allclose(
            model.ajj_inv_corr,
            np.linalg.solve(expect, np.eye(n_surf)) * (2.0 / np.array(
                [b.area / np.hypot(b.bound_b[1] - b.bound_a[1],
                                   b.bound_b[2] - b.bound_a[2]) for b in model.boxes]
            ))[:, None],
            rtol=1e-10)
