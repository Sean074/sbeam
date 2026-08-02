"""Vectorized-vs-scalar equivalence for the broadcast Biot-Savart AIC build (P9).

The vectorized ``build_ajj`` reproduces the scalar ``horseshoe_influence`` loop
op-for-op on float64, so the equivalence assertions here are BIT-FOR-BIT
(``assert_array_equal``).  If a platform/BLAS quirk ever breaks exactness, the
documented fallback is ``assert_allclose(atol=1e-15, rtol=1e-14)`` — well
inside every downstream tolerance (the tightest existing gate on build_ajj
output is the diagonal check at rel=1e-12).
"""

import math

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from sbeam.aero.integration import build_skj
from sbeam.aero.panel import AeroBox
from sbeam.aero.vlm import (
    _DEGEN_TOL,
    build_ajj,
    horseshoe_influence,
    trefftz_cdi,
)


def _make_box(k, corners, chord, caero_eid=1, i_span=0, j_chord=0, normal=None):
    """AeroBox from 4 corners [root-LE, tip-LE, tip-TE, root-TE] (CID 0)."""
    c = np.asarray(corners, dtype=float)
    root_le, tip_le, tip_te, root_te = c
    bound_a = root_le + 0.25 * (root_te - root_le)
    bound_b = tip_le + 0.25 * (tip_te - tip_le)
    colloc = 0.5 * (root_le + tip_le) + 0.75 * (0.5 * (root_te + tip_te)
                                                - 0.5 * (root_le + tip_le))
    if normal is None:
        n = np.cross(c[2] - c[0], c[3] - c[1])
        normal = n / np.linalg.norm(n)
    area = 0.5 * float(np.linalg.norm(np.cross(c[2] - c[0], c[3] - c[1])))
    return AeroBox(
        k=k, caero_eid=caero_eid, i_span=i_span, j_chord=j_chord,
        corners=c, colloc=colloc, bound_a=bound_a, bound_b=bound_b,
        force_point=0.5 * (bound_a + bound_b), area=area,
        normal=np.asarray(normal, dtype=float), chord=chord,
        span_frac=0.5,
    )


def _random_boxes(n=30, seed=1234):
    """Irregular boxes: random sweep, dihedral, twist, chord, mixed normals."""
    rng = np.random.default_rng(seed)
    boxes = []
    for k in range(n):
        x0 = rng.uniform(-5.0, 5.0)
        y0 = rng.uniform(-10.0, 10.0)
        z0 = rng.uniform(-2.0, 2.0)
        span = rng.uniform(0.3, 2.0)
        chord = rng.uniform(0.4, 3.0)
        sweep = rng.uniform(-0.5, 0.5) * chord
        dihedral = rng.uniform(-0.4, 0.4) * span
        twist = rng.uniform(-0.1, 0.1) * chord
        root_le = np.array([x0, y0, z0])
        tip_le = np.array([x0 + sweep, y0 + span, z0 + dihedral])
        root_te = root_le + np.array([chord, 0.0, twist])
        tip_te = tip_le + np.array([chord * rng.uniform(0.7, 1.3), 0.0, -twist])
        boxes.append(_make_box(k, [root_le, tip_le, tip_te, root_te], chord,
                               i_span=k, j_chord=0))
    return boxes


def _scalar_ajj(boxes):
    """The pre-P9 scalar double loop, kept as the reference implementation."""
    n = len(boxes)
    A = np.zeros((n, n))
    for i, box_i in enumerate(boxes):
        for j, box_j in enumerate(boxes):
            A[i, j] = horseshoe_influence(box_i.colloc, box_i.normal, box_j)
    return A


class TestBuildAjjEquivalence:
    def test_random_geometry_bit_for_bit(self):
        boxes = _random_boxes(n=30)
        assert_array_equal(build_ajj(boxes), _scalar_ajj(boxes))

    def test_planar_wing_bit_for_bit(self):
        boxes = []
        k = 0
        for i in range(6):
            for j in range(4):
                boxes.append(_make_box(
                    k,
                    [[j * 0.5, i * 1.0, 0.0], [j * 0.5, (i + 1) * 1.0, 0.0],
                     [(j + 1) * 0.5, (i + 1) * 1.0, 0.0], [(j + 1) * 0.5, i * 1.0, 0.0]],
                    chord=2.0, i_span=i, j_chord=j))
                k += 1
        assert_array_equal(build_ajj(boxes), _scalar_ajj(boxes))

    def test_chunking_matches_unchunked(self, monkeypatch):
        """A chunk size smaller than n exercises the blocked path."""
        import sbeam.aero.vlm as vlm
        boxes = _random_boxes(n=25)
        full = build_ajj(boxes)
        monkeypatch.setattr(vlm, "_AJJ_CHUNK", 7)
        assert_array_equal(vlm.build_ajj(boxes), full)

    def test_empty_box_list(self):
        assert build_ajj([]).shape == (0, 0)


class TestDegenerateGuards:
    def test_colloc_on_bound_endpoint(self):
        """Receiver colloc exactly at a sender's bound-vortex endpoint (n1/n2
        guard): the bound-segment term is exactly zero, matching the scalar."""
        boxes = _random_boxes(n=4)
        boxes[0].colloc = boxes[1].bound_a.copy()
        A = build_ajj(boxes)
        assert_array_equal(A, _scalar_ajj(boxes))
        assert np.all(np.isfinite(A))

    def test_colloc_on_segment_line(self):
        """Receiver colloc on the extended bound-vortex line (|r1×r2|² guard):
        entry finite and bit-for-bit with the scalar path."""
        boxes = _random_boxes(n=4)
        a, b = boxes[2].bound_a, boxes[2].bound_b
        boxes[0].colloc = a + 2.5 * (b - a)   # collinear, beyond the tip end
        A = build_ajj(boxes)
        assert_array_equal(A, _scalar_ajj(boxes))
        assert np.all(np.isfinite(A))

    def test_degenerate_entries_are_exact_zero_per_segment(self):
        """A colloc on the bound segment interior zeroes that segment's
        contribution exactly (both scalar guards return exact zeros)."""
        boxes = _random_boxes(n=2)
        a, b = boxes[1].bound_a, boxes[1].bound_b
        boxes[0].colloc = 0.5 * (a + b)       # on the bound segment
        A = build_ajj(boxes)
        assert_array_equal(A, _scalar_ajj(boxes))


class TestTrefftzCdiEquivalence:
    @staticmethod
    def _scalar_trefftz(boxes, gamma, S_ref, ar):
        """Verbatim copy of the pre-P9 scalar trefftz_cdi loop."""
        lift_idxs = np.array(
            [i for i, b in enumerate(boxes) if abs(b.normal[2]) >= abs(b.normal[1])],
            dtype=int,
        )
        if len(lift_idxs) == 0 or S_ref < _DEGEN_TOL or ar < _DEGEN_TOL:
            return {"CDi": 0.0, "e": float("nan")}
        n = len(lift_idxs)
        gamma_l = gamma[lift_idxs]
        dy_l = np.array([
            float(math.sqrt((boxes[ii].bound_b[1] - boxes[ii].bound_a[1])**2
                          + (boxes[ii].bound_b[2] - boxes[ii].bound_a[2])**2))
            for ii in lift_idxs
        ])
        w_tr = np.zeros(n)
        _twopi_inv = 1.0 / (2.0 * math.pi)
        for i, ii in enumerate(lift_idxs):
            bi = boxes[ii]
            y_i = 0.5 * (bi.bound_a[1] + bi.bound_b[1])
            z_i = 0.5 * (bi.bound_a[2] + bi.bound_b[2])
            for jj in lift_idxs:
                bj = boxes[jj]
                Gj = gamma[jj]
                for (y_v, z_v, sv) in (
                    (bj.bound_b[1], bj.bound_b[2],  Gj),
                    (bj.bound_a[1], bj.bound_a[2], -Gj),
                ):
                    dy = y_i - y_v
                    dz = z_i - z_v
                    r2 = dy * dy + dz * dz
                    if r2 > _DEGEN_TOL:
                        w_tr[i] += -sv * _twopi_inv * dy / r2
        Di = float(np.dot(gamma_l * w_tr, dy_l))
        CDi = Di / S_ref
        nz_l = np.array([boxes[ii].normal[2] for ii in lift_idxs])
        CL_l = 2.0 * float(np.dot(gamma_l * dy_l, nz_l)) / S_ref
        e = (CL_l * CL_l) / (math.pi * ar * CDi) if CDi > _DEGEN_TOL else float("nan")
        return {"CDi": CDi, "e": e}

    def test_random_geometry(self):
        """Row-sum order differs from the interleaved scalar accumulation, so
        this comparison is tolerance-based (rtol=1e-12), not bit-for-bit."""
        boxes = _random_boxes(n=30)
        rng = np.random.default_rng(99)
        gamma = rng.normal(size=len(boxes))
        got = trefftz_cdi(boxes, gamma, S_ref=20.0, ar=6.0)
        want = self._scalar_trefftz(boxes, gamma, S_ref=20.0, ar=6.0)
        assert got["CDi"] == pytest.approx(want["CDi"], rel=1e-12)
        assert got["e"] == pytest.approx(want["e"], rel=1e-12)

    def test_coincident_trailing_vortices_masked(self):
        """Two boxes sharing a bound endpoint put a receiver midpoint on top of
        a trailing vortex only in contrived meshes; force the degenerate case
        by duplicating a box so r² = 0 lanes exist, and expect finite output."""
        boxes = _random_boxes(n=3)
        import copy
        boxes.append(copy.deepcopy(boxes[0]))
        boxes[-1].k = 3
        gamma = np.array([0.5, -0.2, 0.3, 0.5])
        got = trefftz_cdi(boxes, gamma, S_ref=10.0, ar=5.0)
        want = self._scalar_trefftz(boxes, gamma, S_ref=10.0, ar=5.0)
        assert np.isfinite(got["CDi"])
        assert got["CDi"] == pytest.approx(want["CDi"], rel=1e-12)


class TestGeconConditioning:
    """DEF-R6: the LU + gecon 1-norm estimate replaces the full-SVD cond."""

    def test_near_singular_warns(self):
        from sbeam.aero.corrections import check_conditioning
        a = np.eye(4)
        a[3, 3] = 1e-13                     # cond ≈ 1e13 > 1e10 threshold
        with pytest.warns(UserWarning, match="poorly conditioned"):
            check_conditioning(a)

    def test_well_conditioned_silent_and_lu_reusable(self):
        import warnings as _warnings
        from scipy.linalg import lu_solve
        from sbeam.aero.corrections import check_conditioning
        rng = np.random.default_rng(7)
        a = np.eye(6) + 0.1 * rng.normal(size=(6, 6))
        with _warnings.catch_warnings():
            _warnings.simplefilter("error")
            lu_piv = check_conditioning(a)
        x = lu_solve(lu_piv, np.ones(6))
        np.testing.assert_allclose(a @ x, np.ones(6), atol=1e-12)

    def test_estimate_close_to_true_1norm_cond(self):
        from sbeam.linalg_utils import estimate_cond_1norm
        rng = np.random.default_rng(3)
        a = rng.normal(size=(20, 20))
        cond, _ = estimate_cond_1norm(a)
        true = np.linalg.cond(a, 1)
        assert cond == pytest.approx(true, rel=1.0)   # gecon is an estimate

    def test_exactly_singular_returns_inf(self):
        from sbeam.linalg_utils import estimate_cond_1norm
        a = np.zeros((3, 3))
        cond, _ = estimate_cond_1norm(a)
        assert cond == float("inf")


class TestBuildSkjEquivalence:
    def test_bit_for_bit(self):
        boxes = _random_boxes(n=12)
        n = len(boxes)
        want = np.zeros((3 * n, n))
        for j, box in enumerate(boxes):
            want[3 * j: 3 * j + 3, j] = box.area * box.normal
        assert_array_equal(build_skj(boxes), want)

    def test_empty(self):
        assert build_skj([]).shape == (0, 0)
