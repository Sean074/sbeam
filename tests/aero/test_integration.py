"""Integration-matrix acceptance tests for S42 (V-A4).

Covers:
  - build_skj shape and force-consistency round-trip (T4)
  - build_djk is negative identity at k=0
  - build_wg: zero when no W2GJ present (T1)
  - build_wg: uniform W2GJ downwash slope reproduces S41 rigid-AOA cp via the
    production combination, no -wg negation (T2)
  - build_wg: linear built-in incidence (negative wg) → monotonically varying
    section loads (T3)
  - build_wg: wrong caero_eid returns zeros
"""

import numpy as np
import pytest

from sbeam.model.aero import Caero1, Paero1, W2gj
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj, solve_rigid_cl
from sbeam.aero.integration import build_skj, build_djk, build_wg

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

PAERO = Paero1(pid=1)
NO_AEFACTS = {}
NO_CORD2RS = {}
CAERO_EID = 1


def _rect_wing(nspan: int, nchord: int, span: float = 5.0, chord: float = 1.0) -> list:
    """Rectangular CAERO1 panel in the XY plane, chord in +X, span in +Y."""
    caero = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord,
        lspan=0, lchord=0,
        igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
    )
    return mesh_caero1(caero, PAERO, NO_AEFACTS, NO_CORD2RS)


# ---------------------------------------------------------------------------
# build_skj
# ---------------------------------------------------------------------------

class TestBuildSkj:
    @pytest.fixture(scope="class")
    def boxes_4x2(self):
        return _rect_wing(nspan=4, nchord=2)

    def test_shape(self, boxes_4x2):
        n = len(boxes_4x2)
        skj = build_skj(boxes_4x2)
        assert skj.shape == (3 * n, n)

    def test_fz_consistency_round_trip(self, boxes_4x2):
        """T4: Skj @ cp total Fz == direct area*normal*cp loop."""
        alpha = 0.05
        cp = solve_rigid_cl(boxes_4x2, alpha)["cp"]
        skj = build_skj(boxes_4x2)
        F_vec = skj @ cp
        fz_matrix = np.sum(F_vec[2::3])
        fz_direct = sum(
            boxes_4x2[j].area * cp[j] * boxes_4x2[j].normal[2]
            for j in range(len(boxes_4x2))
        )
        assert fz_matrix == pytest.approx(fz_direct, rel=1e-10)

    def test_off_diagonal_columns_zero(self, boxes_4x2):
        """Each box j only contributes to rows 3j, 3j+1, 3j+2."""
        skj = build_skj(boxes_4x2)
        n = len(boxes_4x2)
        for j in range(n):
            col = skj[:, j].copy()
            col[3 * j : 3 * j + 3] = 0.0
            assert np.all(col == 0.0), f"Column {j} has non-zero outside its block"

    def test_column_equals_area_times_normal(self, boxes_4x2):
        skj = build_skj(boxes_4x2)
        for j, box in enumerate(boxes_4x2):
            expected = box.area * box.normal
            np.testing.assert_allclose(skj[3 * j : 3 * j + 3, j], expected, atol=1e-14)


# ---------------------------------------------------------------------------
# build_djk
# ---------------------------------------------------------------------------

class TestBuildDjk:
    def test_shape(self):
        boxes = _rect_wing(nspan=3, nchord=2)
        djk = build_djk(boxes)
        n = len(boxes)
        assert djk.shape == (n, n)

    def test_is_negative_identity(self):
        boxes = _rect_wing(nspan=4, nchord=3)
        djk = build_djk(boxes)
        n = len(boxes)
        np.testing.assert_array_equal(djk, -np.eye(n))

    def test_unit_slope_gives_unit_downwash(self):
        """Unit positive slope at box k → normalwash −1 at box k, 0 elsewhere."""
        boxes = _rect_wing(nspan=2, nchord=2)
        djk = build_djk(boxes)
        slope = np.zeros(len(boxes))
        slope[0] = 1.0
        w = djk @ slope
        assert w[0] == pytest.approx(-1.0)
        np.testing.assert_array_equal(w[1:], 0.0)


# ---------------------------------------------------------------------------
# build_wg
# ---------------------------------------------------------------------------

class TestBuildWg:
    @pytest.fixture(scope="class")
    def boxes(self):
        return _rect_wing(nspan=4, nchord=2)

    # T1 — no W2GJ present → zero vector
    def test_zero_without_w2gj(self, boxes):
        wg = build_wg(boxes, {}, CAERO_EID)
        np.testing.assert_array_equal(wg, 0.0)

    def test_zero_for_wrong_caero_eid(self, boxes):
        n = len(boxes)
        w2gj = W2gj(sid=1, caero_eid=999, data=[0.1] * n)
        wg = build_wg(boxes, {1: w2gj}, CAERO_EID)
        np.testing.assert_array_equal(wg, 0.0)

    # T2 — a uniform W2GJ incidence reproduces the rigid-AOA cp from S41,
    #      through the PRODUCTION combination (gamma = Ajj^-1 @ wg, no local
    #      negation — exactly as sol144._compute_aero_forces / aero_model /
    #      coupling combine wg).
    def test_uniform_w2gj_matches_rigid_cl(self, boxes):
        """W2GJ card data = +alpha (NASTRAN convention: nose-up incidence,
        like ANGLEA) reproduces solve_rigid_cl(alpha) when solved the way
        production does: gamma = solve(Ajj, wg), with NO further negation.

        build_wg negates card data into the internal normalwash (positive wg =
        washout = less lift), matching the ANGLEA column / build_djk sign.
        This pins the card sign to the MSC HA144A convention (W2GJ = +0.001745
        is "+0.1 deg wing incidence", more lift)."""
        alpha = 0.1
        n = len(boxes)
        # NASTRAN convention: nose-up incidence alpha => POSITIVE card data.
        w2gj = W2gj(sid=1, caero_eid=CAERO_EID, data=[alpha] * n)
        wg = build_wg(boxes, {1: w2gj}, CAERO_EID)

        ajj = build_ajj(boxes)
        gamma_wg = np.linalg.solve(ajj, wg)   # production combination — no -wg

        # Recover cp from gamma using the same formula as solve_rigid_cl
        dy = np.array([
            np.sqrt((b.bound_b[1] - b.bound_a[1])**2 + (b.bound_b[2] - b.bound_a[2])**2)
            for b in boxes
        ])
        chord_box = np.array([boxes[i].area / dy[i] for i in range(n)])
        cp_wg = 2.0 * gamma_wg / chord_box

        cp_ref = solve_rigid_cl(boxes, alpha)["cp"]
        np.testing.assert_allclose(cp_wg, cp_ref, rtol=1e-10)

    # T3 — linear twist → section loads vary monotonically with span
    def test_linear_twist_monotonic_section_load(self):
        """Linearly increasing built-in incidence toward the tip → monotonically
        increasing section CL (interior).

        Built-in nose-up incidence growing toward the tip is an increasingly
        POSITIVE W2GJ card value (NASTRAN convention); build_wg negates it into
        the internal washout-positive normalwash.  Solved as production does
        (gamma = solve(Ajj, wg)), the section circulation grows toward the tip.

        The outermost tip strip is excluded: VLM always shows tip-vortex rolloff
        that reduces circulation there regardless of incidence.
        """
        nspan, nchord = 5, 1
        boxes = _rect_wing(nspan=nspan, nchord=nchord, span=5.0, chord=1.0)
        n = len(boxes)

        # Per-strip card data: nose-up incidence ∝ (i+1) → positive W2GJ ∝ (i+1)
        slopes = [0.02 * (box.i_span + 1) for box in boxes]

        w2gj = W2gj(sid=1, caero_eid=CAERO_EID, data=slopes)
        wg = build_wg(boxes, {1: w2gj}, CAERO_EID)
        ajj = build_ajj(boxes)
        gamma = np.linalg.solve(ajj, wg)   # production combination — no -wg

        # Check interior strips (nchord=1 so strip index == box index).
        # Skip the last pair: tip rolloff physically reduces tip gamma below strip n-2.
        for i in range(n - 2):
            assert gamma[i + 1] > gamma[i], (
                f"Section gamma not increasing: strip {i}={gamma[i]:.6f}, "
                f"strip {i+1}={gamma[i+1]:.6f}"
            )

    def test_partial_w2gj_data_fills_remaining_zeros(self):
        """W2GJ with fewer values than boxes leaves untouched entries as zero.

        Card data is negated into the internal normalwash (NASTRAN convention:
        positive card = incidence; internal positive = washout)."""
        boxes = _rect_wing(nspan=2, nchord=2)  # 4 boxes
        w2gj = W2gj(sid=1, caero_eid=CAERO_EID, data=[0.1, 0.2])  # only 2 values
        wg = build_wg(boxes, {1: w2gj}, CAERO_EID)
        assert wg[0] == pytest.approx(-0.1)
        assert wg[1] == pytest.approx(-0.2)
        assert wg[2] == pytest.approx(0.0)
        assert wg[3] == pytest.approx(0.0)

    def test_w2gj_length_matches_n_boxes(self):
        boxes = _rect_wing(nspan=3, nchord=2)
        n = len(boxes)
        data = [float(j) * 0.01 for j in range(n)]
        w2gj = W2gj(sid=1, caero_eid=CAERO_EID, data=data)
        wg = build_wg(boxes, {1: w2gj}, CAERO_EID)
        np.testing.assert_allclose(wg, [-d for d in data])
