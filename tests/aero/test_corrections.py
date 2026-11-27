"""AIC correction acceptance tests for S43 (V-A3).

Covers:
  - No correction: AJJ*⁻¹ @ AJJ ≈ I (identity round-trip)
  - apply_wkk: MSC placement — a box's lift scales by its weight, others unchanged (#71)
  - apply_wt2 round-trip: feed VLM cp as target → corrected cp reproduced to tol
  - apply_wt2 conditioning warning: near-singular AJJ triggers UserWarning
  - build_aero_model: identity (no correction) — AJJ*⁻¹ @ AJJ ≈ I
  - build_aero_model: WKK correction wired end-to-end
  - WT1 removal (DEF-R7): an ``AECORR METHOD=WT1`` card is rejected at read time
  - WKK per-surface binding (DEF-M8b) on a two-surface deck
  - WT2 per-axis reference (#52): a fin no longer makes the corrected tailplane
    asymmetric at beta = 0; decks without a vertical surface are unchanged
"""


import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.model.aero import Caero1, Paero1, Wkk, Aecorr
from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj, solve_rigid_cl
from pathlib import Path

from sbeam.aero.corrections import apply_wkk, apply_wt2, wt2_reference_cp
from sbeam.aero.aero_model import build_aero_model
from tests.samples import sample_path

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
    """WKK multiplies box forces after the pressure solve (#71).

    MSC: ``{P_k} = q [W_kk][S_kj][A_jj]⁻¹{w_j}`` (MSC Nastran 2023.1 Aeroelastic Analysis
    User's Guide PDF p.40 eq 2-21, p.70 eq 2-106).  Before #71 sbeam inverted
    ``diag(w) @ AJJ``, which applied 1/w on the downwash side.
    """

    def test_unit_weights_return_the_inverse_unchanged(self):
        _, ajj_inv = _ajj_and_inv(_rect_wing(4, 4))
        n = ajj_inv.shape[0]
        assert apply_wkk(ajj_inv, [1.0] * n) == pytest.approx(ajj_inv, rel=1e-12)

    def test_first_box_lift_scales_by_1_5_and_no_other_box_changes(self):
        """The Step 43 plan's own acceptance test, which its tests replaced with algebra."""
        _, ajj_inv = _ajj_and_inv(_rect_wing(2, 2))
        n = ajj_inv.shape[0]
        w_ref = -np.full(n, 0.05)
        cp_ref = ajj_inv @ w_ref
        cp_corr = apply_wkk(ajj_inv, [1.5] + [1.0] * (n - 1)) @ w_ref
        assert cp_corr[0] == pytest.approx(1.5 * cp_ref[0], rel=1e-12)
        assert cp_corr[1:] == pytest.approx(cp_ref[1:], rel=1e-12)

    def test_zero_weight_removes_that_box_lift(self):
        """Zero is a legal MSC factor; it used to make the corrected AIC singular."""
        _, ajj_inv = _ajj_and_inv(_rect_wing(2, 2))
        n = ajj_inv.shape[0]
        cp = apply_wkk(ajj_inv, [0.0] + [1.0] * (n - 1)) @ -np.ones(n)
        assert cp[0] == 0.0 and cp[1:] == pytest.approx((ajj_inv @ -np.ones(n))[1:])


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
        """Uniform WKK = 1.5 raises the corrected total lift by 1.5 (#71; was ÷ 1.5)."""
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
        assert fz_wkk == pytest.approx(1.5 * fz_base, rel=1e-8)

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
            sid=20, method="WT2", caero_eid=CAERO_EID, mach=0.0,
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
        """Uniform WKK=1.5 → corrected-operator CL is 1.5 × the uncorrected CL (#71)."""
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
        assert cl_wkk == pytest.approx(1.5 * cl_base, rel=1e-8)

    def test_cp_operator_shape_validated(self):
        boxes = _rect_wing(2, 2)
        with pytest.raises(ValueError, match="cp_operator has shape"):
            solve_rigid_cl(boxes, alpha=0.05, cp_operator=np.eye(3))


# ---------------------------------------------------------------------------
# Multi-surface decks — WT1 removal (DEF-R7) and WKK per-surface binding (DEF-M8b)
# ---------------------------------------------------------------------------

# 1000 clear of CAERO_EID=1's box-ID range: a CAERO1 owns the NSPAN*NCHORD
# consecutive IDs from its EID, so EID 2 would overlap the wing (F1).
TAIL_EID = 1000


def _strip_forces(model, caero_eid=None) -> np.ndarray:
    """Physical strip lift/q (Σ area·Cp) at unit reference incidence, by i_span.

    Restricted to one CAERO1 when ``caero_eid`` is given.  Ordered by ascending
    i_span.
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



class TestWt1Removed:
    """DEF-R7 — ``AECORR METHOD=WT1`` is rejected at read time, not warned about.

    DEF-H2/H3 (2026-07-31) deprecated WT1 with a parser ``UserWarning`` but left
    it working; the release boundary completes the retirement.  A legacy deck
    carrying the card now fails loudly instead of producing wrong numbers.
    """

    def test_parser_rejects_wt1_card(self):
        wt1 = ["AECORR, 30, WT1, 100, 0.80, 0.75, 0.65, 0.50"]
        with pytest.raises(ValueError, match="METHOD WT1 has been removed"):
            parse_bulk_data(wt1)

    def test_parser_still_accepts_wt2_card(self):
        # The CAERO1 it corrects must exist: an AECORR on an unknown panel is refused (#51)
        wt2 = ["AEROS, 0, 0, 1.0, 4.0, 4.0", "PAERO1, 1",
               "CAERO1, 100, 1, 0, 4, 1, 0, 0, 1", "+, 0., 0., 0., 1., 0., 4., 0., 1.",
               "AECORR, 30, WT2, 100, 0.0, 0.80, 0.75, 0.65, 0.50"]
        bulk = parse_bulk_data(wt2)
        assert bulk.aecorrs[30].method == "WT2"

    def test_unknown_method_still_rejected(self):
        bad = ["AECORR, 30, WT9, 100, 0.80"]
        with pytest.raises(ValueError, match="METHOD must be WT2"):
            parse_bulk_data(bad)


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
        """Unlisted surfaces get weight 1, so their rows of AJJ*⁻¹ are untouched.

        This compared the raw ``ajj`` before #71, which WKK never changes.
        """
        nspan = nchord = 3
        n_surf = nspan * nchord
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.5] * n_surf)
        corr = build_aero_model(bulk, mach=0.0)
        base = build_aero_model(self._two_surface(nspan, nchord), mach=0.0)
        wing = [k for k, b in enumerate(corr.boxes) if b.caero_eid == CAERO_EID]
        tail = [k for k, b in enumerate(corr.boxes) if b.caero_eid == TAIL_EID]
        np.testing.assert_allclose(corr.ajj_inv_corr[tail], base.ajj_inv_corr[tail], rtol=1e-12)
        np.testing.assert_allclose(corr.ajj_inv_corr[wing], 0.5 * base.ajj_inv_corr[wing],
                                   rtol=1e-12)

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

    def test_zero_weight_is_accepted(self):
        """MSC's factor 0 removes a box's lift (#71); it used to be refused as singular."""
        nspan = nchord = 3
        n_surf = nspan * nchord
        data = [0.9] * n_surf
        data[2] = 0.0
        bulk = self._two_surface(nspan, nchord)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=data)
        model = build_aero_model(bulk, mach=0.0)
        assert not model.ajj_inv_corr[2].any()


# ---------------------------------------------------------------------------
# WT2 per-axis reference (#52)
# ---------------------------------------------------------------------------



class TestWt2PerAxisReference:
    """The WT2 ratio is calibrated per incidence axis, never by sideslipping a fin.

    Before #52 the reference was a normalwash of -1 on EVERY box.  On the flagship's
    vertical fin that is a sideslip; the fin's side load induced an antisymmetric
    normalwash on the HTP, so the corrected HTP at alpha = 3 deg, beta = 0 carried 55 %
    more load on the port side than the starboard (strip sums 7.70 vs 4.98).
    """

    @pytest.mark.parametrize("deck", ["cessna210_flagship_trim.bdf",
                                      "cessna210_flagship_body.bdf"])
    def test_corrected_loading_is_symmetric_at_zero_sideslip(self, deck):
        from sbeam.assembly.load_vector import build_grid_index
        from sbeam.parser.bdf_reader import parse_bdf

        _cc, bulk = parse_bdf(str(sample_path(deck)))
        assert bulk.aecorrs, "deck must carry WT2 cards for this gate to mean anything"
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
        eid = np.array([b.caero_eid for b in aero.boxes])
        isp = np.array([b.i_span for b in aero.boxes])
        ich = np.array([b.j_chord for b in aero.boxes])
        nz = np.array([b.normal[2] for b in aero.boxes])
        cp = aero.ajj_inv_corr @ (-np.radians(3.0) * nz + aero.wg)

        # Port/starboard partners share (i_span, i_chord): wing 1000/2000, HTP 3000/4000.
        for stbd, port in ((1000, 2000), (3000, 4000)):
            for s, c in zip(isp[eid == stbd], ich[eid == stbd]):
                a = cp[(eid == stbd) & (isp == s) & (ich == c)]
                b = cp[(eid == port) & (isp == s) & (ich == c)]
                assert a == pytest.approx(b, abs=1e-10), (
                    f"CAERO {stbd}/{port} box ({s},{c}) asymmetric at beta = 0")
        assert abs(cp[eid == 5000].sum()) < 1e-10, "fin loaded at beta = 0"

    def test_no_vertical_surface_reference_is_the_uniform_one(self):
        """Invariant: with no y-dominant surface the per-axis rule IS -ones, exactly."""
        boxes = _rect_wing(4, 3)
        _ajj, ajj_inv = _ajj_and_inv(boxes)
        np.testing.assert_array_equal(wt2_reference_cp(boxes, ajj_inv),
                                      ajj_inv @ -np.ones(len(boxes)))

    def test_vertical_surface_is_calibrated_in_beta(self):
        """A y-normal surface takes its reference from w_beta, the wing from w_alpha."""
        wing = _rect_wing(4, 3)
        fin = mesh_caero1(Caero1(
            eid=2, pid=1, cp=0, nspan=3, nchord=3, lspan=0, lchord=0, igid=0,
            p1=(3.0, 0.0, 0.2), x12=1.0, p4=(3.0, 0.0, 1.7), x43=1.0,
        ), PAERO, NO_AEFACTS, NO_CORD2RS, start_k=len(wing))
        boxes = wing + fin
        _ajj, ajj_inv = _ajj_and_inv(boxes)
        is_fin = np.array([b.caero_eid == 2 for b in boxes])
        ref = wt2_reference_cp(boxes, ajj_inv)
        np.testing.assert_allclose(ref[~is_fin], (ajj_inv @ np.where(is_fin, 0.0, -1.0))[~is_fin])
        np.testing.assert_allclose(ref[is_fin], (ajj_inv @ np.where(is_fin, -1.0, 0.0))[is_fin])



class TestWkkAtTheOperatingPoint:
    """End-to-end gate (#71): a flexible SOL 144 trim of MSC's HA144A airplane.

    MSC's aero forces are ``q [W_kk][S_kj][A_jj]⁻¹{w_j}`` (AAUG 2023.1 PDF p.70 eq 2-106),
    so a uniform WKK = w on every box is the same airplane at dynamic pressure q·w.
    Scored against a run with no WKK at all, so the reference never touches WKK.
    """

    W = 1.25

    @staticmethod
    def _trim(bulk, subcase):
        import warnings

        from sbeam.assembly.load_vector import build_grid_index
        from sbeam.solver.sol144 import run_sol144_trim
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
            return run_sol144_trim(bulk, subcase, aero)

    def test_uniform_wkk_equals_scaled_dynamic_pressure(self):
        from sbeam.parser.bdf_reader import parse_bdf
        deck = Path(__file__).resolve().parents[2] / "sample/ha144a/ha144a_fullspan_sbeam.bdf"
        cc, bulk = parse_bdf(deck)
        sc = cc.subcases[0]
        q = bulk.trims[sc.trim_sid].q

        model = build_aero_model(bulk)
        for sid, eid in enumerate(sorted(bulk.caero1s), start=900):
            n_boxes = sum(b.caero_eid == eid for b in model.boxes)
            bulk.wkks[sid] = Wkk(sid=sid, caero_eid=eid, data=[self.W] * n_boxes)
        with_wkk = self._trim(bulk, sc)

        _, ref_bulk = parse_bdf(deck)
        ref_bulk.trims[sc.trim_sid].q = q * self.W
        ref = self._trim(ref_bulk, sc)

        for label, value in ref.trim_vars.items():
            assert with_wkk.trim_vars[label] == pytest.approx(value, rel=1e-8, abs=1e-12), label
        np.testing.assert_allclose(with_wkk.displacements, ref.displacements,
                                   rtol=1e-8, atol=1e-14)
        np.testing.assert_allclose(with_wkk.net_loads, ref.net_loads, rtol=1e-8, atol=1e-8)


class TestWkkAndWt2Together:
    """#96 — a WKK card used to switch off every AECORR WT2 card, on every surface.

    ``if wkk_cards: … elif wt2_cards: …`` meant a unit-weight WKK on the wing left the
    tail's WT2 calibration unapplied without a message.  Both corrections act after the
    solve (#71), so they now combine across surfaces; one surface takes one of them.
    """

    @staticmethod
    def _tail_wt2(bulk, base):
        tail = [k for k, b in enumerate(base.boxes) if b.caero_eid == TAIL_EID]
        bulk.aecorrs[20] = Aecorr(sid=20, method="WT2", caero_eid=TAIL_EID, mach=0.0,
                                  target=[5.0] * len(tail))
        return tail

    def test_wt2_on_the_tail_survives_a_wkk_on_the_wing(self):
        """The issue's probe: tail rows equal the WT2-alone rows, wing rows the WKK ones."""
        nspan = nchord = 3
        base = build_aero_model(_wing_and_tail_bulk(nspan, nchord), mach=0.0)
        alone = _wing_and_tail_bulk(nspan, nchord)
        tail = self._tail_wt2(alone, base)
        wt2_only = build_aero_model(alone, mach=0.0)
        both = _wing_and_tail_bulk(nspan, nchord)
        self._tail_wt2(both, base)
        both.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[1.0] * nspan * nchord)
        model = build_aero_model(both, mach=0.0)
        assert not np.allclose(wt2_only.ajj_inv_corr[tail], base.ajj_inv_corr[tail])
        np.testing.assert_array_equal(model.ajj_inv_corr, wt2_only.ajj_inv_corr)

    def test_a_non_unit_wkk_scales_only_its_own_surface(self):
        nspan = nchord = 3
        base = build_aero_model(_wing_and_tail_bulk(nspan, nchord), mach=0.0)
        alone = _wing_and_tail_bulk(nspan, nchord)
        tail = self._tail_wt2(alone, base)
        wt2_only = build_aero_model(alone, mach=0.0)
        both = _wing_and_tail_bulk(nspan, nchord)
        self._tail_wt2(both, base)
        both.wkks[10] = Wkk(sid=10, caero_eid=CAERO_EID, data=[0.5] * nspan * nchord)
        model = build_aero_model(both, mach=0.0)
        wing = [k for k, b in enumerate(model.boxes) if b.caero_eid == CAERO_EID]
        np.testing.assert_allclose(model.ajj_inv_corr[tail], wt2_only.ajj_inv_corr[tail],
                                   rtol=1e-12)
        np.testing.assert_allclose(model.ajj_inv_corr[wing], 0.5 * base.ajj_inv_corr[wing],
                                   rtol=1e-12)

    def test_wkk_and_wt2_on_one_surface_are_refused(self):
        nspan = nchord = 3
        base = build_aero_model(_wing_and_tail_bulk(nspan, nchord), mach=0.0)
        bulk = _wing_and_tail_bulk(nspan, nchord)
        self._tail_wt2(bulk, base)
        bulk.wkks[10] = Wkk(sid=10, caero_eid=TAIL_EID, data=[1.0] * nspan * nchord)
        with pytest.raises(ValueError, match=r"AECORR 20 \(WT2\) and WKK 10 both correct "
                                             r"CAERO1 1000"):
            build_aero_model(bulk, mach=0.0)

    def test_two_wt2_cards_on_one_surface_are_refused(self):
        """The second card used to overwrite the first without a message."""
        nspan = nchord = 3
        base = build_aero_model(_wing_and_tail_bulk(nspan, nchord), mach=0.0)
        bulk = _wing_and_tail_bulk(nspan, nchord)
        tail = self._tail_wt2(bulk, base)
        bulk.aecorrs[21] = Aecorr(sid=21, method="WT2", caero_eid=TAIL_EID, mach=0.0,
                                  target=[4.0] * len(tail))
        with pytest.raises(ValueError, match=r"AECORR 21: CAERO1 1000 already has a WT2 "
                                             r"AECORR \(SID 20\)"):
            build_aero_model(bulk, mach=0.0)
