"""Geometric acceptance tests for CAERO1 box meshing (S40 KA1).

Off-by-half-box errors in 1/4-chord and 3/4-chord placement are the classic VLM
bug — coordinates are asserted directly against closed-form values.
"""

import pytest
import numpy as np

from sbeam.model.aero import Caero1, Paero1, Aefact
from sbeam.aero.panel import AeroBox, mesh_caero1

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

PAERO_STUB = Paero1(pid=1)
NO_CORD2RS = {}   # cp=0 → identity transform
NO_AEFACTS = {}


def _rect_caero(nspan, nchord, span=4.0, chord=2.0, lspan=0, lchord=0):
    """Flat rectangular CAERO1 in the XY plane.

    P1 at origin, span in +Y, chord (x12=x43) in +X (freestream direction).
    """
    return Caero1(
        eid=100, pid=1, cp=0,
        nspan=nspan, nchord=nchord,
        lspan=lspan, lchord=lchord,
        igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1×1 flat rectangular box (KA1: single-box sanity)
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleBox:
    @pytest.fixture(scope="class")
    def box(self):
        caero = _rect_caero(nspan=1, nchord=1, span=4.0, chord=2.0)
        boxes = mesh_caero1(caero, PAERO_STUB, NO_AEFACTS, NO_CORD2RS)
        assert len(boxes) == 1
        return boxes[0]

    def test_count(self):
        caero = _rect_caero(nspan=1, nchord=1)
        assert len(mesh_caero1(caero, PAERO_STUB, NO_AEFACTS, NO_CORD2RS)) == 1

    def test_area(self, box):
        # Rectangle 2 × 4 = 8
        assert box.area == pytest.approx(8.0)

    def test_colloc_at_three_quarter_chord(self, box):
        # 3/4 of chord 2.0 → x = 1.5; midspan y = 2.0
        assert box.colloc[0] == pytest.approx(1.5)
        assert box.colloc[1] == pytest.approx(2.0)
        assert box.colloc[2] == pytest.approx(0.0)

    def test_bound_vortex_at_quarter_chord(self, box):
        # 1/4 of chord 2.0 → x = 0.5; root at y=0, tip at y=4
        assert box.bound_a[0] == pytest.approx(0.5)
        assert box.bound_a[1] == pytest.approx(0.0)
        assert box.bound_b[0] == pytest.approx(0.5)
        assert box.bound_b[1] == pytest.approx(4.0)

    def test_normal_points_upward(self, box):
        n = box.normal
        assert np.linalg.norm(n) == pytest.approx(1.0)
        assert n[2] > 0.99   # should be [0, 0, 1] for flat XY panel

    def test_corners_shape(self, box):
        assert box.corners.shape == (4, 3)

    def test_root_le_corner(self, box):
        # corners[0] = root-LE = P1 = (0, 0, 0)
        np.testing.assert_allclose(box.corners[0], [0.0, 0.0, 0.0], atol=1e-12)

    def test_tip_te_corner(self, box):
        # corners[2] = tip-TE = P4 + chord * x_hat = (2, 4, 0)
        np.testing.assert_allclose(box.corners[2], [2.0, 4.0, 0.0], atol=1e-12)

    def test_global_index(self, box):
        assert box.k == 0
        assert box.caero_eid == 100
        assert box.i_span == 0
        assert box.j_chord == 0

    def test_chord_field(self, box):
        assert box.chord == pytest.approx(2.0)

    def test_span_frac_field(self, box):
        assert box.span_frac == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# N×M rectangular mesh (KA1: area conservation and box count)
# ─────────────────────────────────────────────────────────────────────────────

class TestNxMRectangularMesh:
    NSPAN, NCHORD = 4, 10
    SPAN, CHORD = 4.0, 2.0

    @pytest.fixture(scope="class")
    def boxes(self):
        caero = _rect_caero(nspan=self.NSPAN, nchord=self.NCHORD,
                            span=self.SPAN, chord=self.CHORD)
        return mesh_caero1(caero, PAERO_STUB, NO_AEFACTS, NO_CORD2RS)

    def test_box_count(self, boxes):
        assert len(boxes) == self.NSPAN * self.NCHORD

    def test_total_area(self, boxes):
        planform_area = self.SPAN * self.CHORD   # 8.0
        assert sum(b.area for b in boxes) == pytest.approx(planform_area)

    def test_global_indices_sequential(self, boxes):
        assert [b.k for b in boxes] == list(range(self.NSPAN * self.NCHORD))

    def test_per_box_chord_placement(self, boxes):
        # For box j, xi_lo=j/nchord, xi_hi=(j+1)/nchord
        # bound x = (xi_lo + 0.25*(xi_hi-xi_lo)) * chord
        # colloc x = (xi_lo + 0.75*(xi_hi-xi_lo)) * chord
        dxi = 1.0 / self.NCHORD
        for b in boxes:
            j = b.j_chord
            xi_lo = j * dxi
            xi_qc = xi_lo + 0.25 * dxi
            xi_tc = xi_lo + 0.75 * dxi
            assert b.bound_a[0] == pytest.approx(xi_qc * self.CHORD, rel=1e-9)
            assert b.colloc[0]  == pytest.approx(xi_tc * self.CHORD, rel=1e-9)

    def test_normals_unit_upward(self, boxes):
        for b in boxes:
            assert np.linalg.norm(b.normal) == pytest.approx(1.0, abs=1e-12)
            assert b.normal[2] > 0.99


# ─────────────────────────────────────────────────────────────────────────────
# Non-uniform AEFACT span spacing
# ─────────────────────────────────────────────────────────────────────────────

class TestAefactSpanSpacing:
    SPAN, CHORD = 4.0, 2.0
    ETA = [0.0, 0.3, 0.6, 1.0]   # 3 strips with widths 0.3, 0.3, 0.4

    @pytest.fixture(scope="class")
    def boxes(self):
        aefact = Aefact(sid=10, data=list(self.ETA))
        caero = Caero1(
            eid=200, pid=1, cp=0,
            nspan=0, nchord=1,
            lspan=10, lchord=0,
            igid=0,
            p1=(0.0, 0.0, 0.0), x12=self.CHORD,
            p4=(0.0, self.SPAN, 0.0), x43=self.CHORD,
        )
        return mesh_caero1(caero, PAERO_STUB, {10: aefact}, NO_CORD2RS)

    def test_count(self, boxes):
        assert len(boxes) == 3   # 3 spanwise strips, 1 chordwise box each

    def test_total_area(self, boxes):
        assert sum(b.area for b in boxes) == pytest.approx(self.SPAN * self.CHORD)

    def test_strip_areas_proportional(self, boxes):
        widths = [0.3, 0.3, 0.4]
        for b, w in zip(boxes, widths):
            expected = w * self.SPAN * self.CHORD
            assert b.area == pytest.approx(expected, rel=1e-9)

    def test_span_fractions(self, boxes):
        eta = self.ETA
        for i, b in enumerate(boxes):
            expected = 0.5 * (eta[i] + eta[i + 1])
            assert b.span_frac == pytest.approx(expected, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Tapered planform (X12 ≠ X43)
# ─────────────────────────────────────────────────────────────────────────────

class TestTaperedPlanform:
    SPAN = 4.0
    ROOT_CHORD = 4.0
    TIP_CHORD  = 2.0

    @pytest.fixture(scope="class")
    def box(self):
        caero = Caero1(
            eid=300, pid=1, cp=0,
            nspan=1, nchord=1,
            lspan=0, lchord=0,
            igid=0,
            p1=(0.0, 0.0, 0.0), x12=self.ROOT_CHORD,
            p4=(0.0, self.SPAN, 0.0), x43=self.TIP_CHORD,
        )
        boxes = mesh_caero1(caero, PAERO_STUB, NO_AEFACTS, NO_CORD2RS)
        assert len(boxes) == 1
        return boxes[0]

    def test_area_trapezoid(self, box):
        # Area = 0.5 * (root_chord + tip_chord) * span
        expected = 0.5 * (self.ROOT_CHORD + self.TIP_CHORD) * self.SPAN
        assert box.area == pytest.approx(expected)

    def test_colloc_x_at_root_3qc(self, box):
        # Midspan colloc: eta=0.5 → chord = 3.0; 3/4 of 3.0 = 2.25
        mid_chord = 0.5 * (self.ROOT_CHORD + self.TIP_CHORD)   # 3.0
        assert box.colloc[0] == pytest.approx(0.75 * mid_chord)

    def test_bound_vortex_x_at_root_qc(self, box):
        mid_chord = 0.5 * (self.ROOT_CHORD + self.TIP_CHORD)
        assert box.bound_a[0] == pytest.approx(0.25 * self.ROOT_CHORD)
        assert box.bound_b[0] == pytest.approx(0.25 * self.TIP_CHORD)

    def test_mean_chord_field(self, box):
        assert box.chord == pytest.approx(0.5 * (self.ROOT_CHORD + self.TIP_CHORD))


# ─────────────────────────────────────────────────────────────────────────────
# start_k offset
# ─────────────────────────────────────────────────────────────────────────────

class TestStartK:
    def test_global_index_offset(self):
        caero = _rect_caero(nspan=2, nchord=3)
        boxes = mesh_caero1(caero, PAERO_STUB, NO_AEFACTS, NO_CORD2RS, start_k=50)
        assert boxes[0].k == 50
        assert boxes[-1].k == 55
