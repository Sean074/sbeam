"""Section force + moment correction synthesis (Option A) — acceptance tests.

Covers ``sbeam.aero.section_correction.build_section_correction`` / ``cards_to_bdf``:

  - identity: targets == uncorrected VLM line → r≈1, wg≈0 (no-op)
  - pure slope scaling (a.c. unchanged) → uniform per-strip r (degenerates to WT1),
    wg≈0, chordwise shape untouched
  - full match: arbitrary (slope, a.c., α₀, Cm0) targets are reproduced both in the
    builder diagnostics and end-to-end through build_aero_model
  - guards: NCHORD < 2 raises, multi-surface raises, length mismatch raises
  - cards_to_bdf round-trips through the BDF parser
"""

import numpy as np
import pytest

from sbeam.model.aero import Caero1, Paero1, Aeros
from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.section_correction import (
    build_section_correction,
    build_section_correction_multi,
    SurfaceTargets,
    cards_to_bdf,
)

PAERO = Paero1(pid=1)
CAERO_EID = 1


# --------------------------------------------------------------------------- helpers

def _rect_wing(nspan, nchord, span=5.0, chord=1.0, x_le=0.0):
    caero = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(x_le, 0.0, 0.0), x12=float(chord),
        p4=(x_le, float(span), 0.0), x43=float(chord),
    )
    return mesh_caero1(caero, PAERO, {}, {})


def _rect_bulk(nspan, nchord, span=5.0, chord=1.0):
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=chord, bref=span, sref=span * chord,
                       symxz=0, symxy=0)
    bulk.paero1s[1] = Paero1(pid=1)
    bulk.caero1s[CAERO_EID] = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
    )
    return bulk


def _vlm_section_lines(boxes, ajj, x_mref):
    """Uncorrected per-strip (force slope, moment slope) at the unit reference."""
    n = len(boxes)
    ajj_inv = np.linalg.solve(ajj, np.eye(n))
    gamma_ref = ajj_inv @ (-np.ones(n))
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(boxes):
        groups[b.i_span].append(k)
    strips = sorted(groups)
    f_slope, m_slope = [], []
    for s, sp in enumerate(strips):
        idx = np.array(groups[sp])
        dy = np.array([np.hypot(boxes[k].bound_b[1] - boxes[k].bound_a[1],
                                boxes[k].bound_b[2] - boxes[k].bound_a[2]) for k in idx])
        chord = np.array([boxes[k].area for k in idx]) / dy
        g0 = np.array([boxes[k].area for k in idx]) * 2.0 * gamma_ref[idx] / chord
        arm = np.array([boxes[k].force_point[0] for k in idx]) - x_mref[s]
        f_slope.append(g0.sum())
        m_slope.append(-(g0 * arm).sum())
    return np.array(f_slope), np.array(m_slope)


def _solve_section_lines(model, x_mref, alpha):
    """End-to-end per-strip (force, moment) from the corrected model at incidence α."""
    boxes = model.boxes
    w_aoa = np.array([-(alpha * b.normal[2]) for b in boxes])
    cp = model.ajj_inv_corr @ (w_aoa + model.wg)
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(boxes):
        groups[b.i_span].append(k)
    strips = sorted(groups)
    F, M = [], []
    for s, sp in enumerate(strips):
        idx = np.array(groups[sp])
        fbox = np.array([boxes[k].area for k in idx]) * cp[idx]
        arm = np.array([boxes[k].force_point[0] for k in idx]) - x_mref[s]
        F.append(fbox.sum())
        M.append(-(fbox * arm).sum())
    return np.array(F), np.array(M)


# --------------------------------------------------------------------------- tests

class TestDegeneracy:
    def test_identity_target_is_noop(self):
        """Targets == uncorrected line → r≈1, wg≈0."""
        boxes = _rect_wing(4, 3)
        ajj = build_ajj(boxes)
        # moment ref = strip ¼-chord (the builder default); recompute VLM line there
        res0 = build_section_correction(
            boxes, ajj, f_slope=np.ones(4), alpha_0=np.zeros(4),
            m_slope=np.zeros(4), m_0=np.zeros(4),
            caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
        )
        x_mref = res0.moment_ref
        f_vlm, m_vlm = _vlm_section_lines(boxes, ajj, x_mref)

        res = build_section_correction(
            boxes, ajj, f_slope=f_vlm, alpha_0=np.zeros(4),
            m_slope=m_vlm, m_0=np.zeros(4),
            caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
        )
        assert res.r == pytest.approx(np.ones(len(boxes)), abs=1e-9)
        assert res.wg == pytest.approx(np.zeros(len(boxes)), abs=1e-9)

    def test_pure_slope_scaling_is_uniform(self):
        """Scaling force & moment slopes by the same factor (a.c. fixed) → uniform r."""
        boxes = _rect_wing(4, 3)
        ajj = build_ajj(boxes)
        res0 = build_section_correction(
            boxes, ajj, f_slope=np.ones(4), alpha_0=np.zeros(4),
            m_slope=np.zeros(4), m_0=np.zeros(4),
            caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
        )
        x_mref = res0.moment_ref
        f_vlm, m_vlm = _vlm_section_lines(boxes, ajj, x_mref)
        scale = 0.85

        res = build_section_correction(
            boxes, ajj, f_slope=scale * f_vlm, alpha_0=np.zeros(4),
            m_slope=scale * m_vlm, m_0=np.zeros(4),
            caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
        )
        # No shape change: every box scaled by the same factor → r ≡ scale.
        assert res.r == pytest.approx(np.full(len(boxes), scale), rel=1e-8)
        assert res.wg == pytest.approx(np.zeros(len(boxes)), abs=1e-9)


class TestDiagnosticsMatchTargets:
    def test_full_match_diagnostics(self):
        boxes = _rect_wing(4, 3)
        ajj = build_ajj(boxes)
        n_strip = 4
        f_slope = np.linspace(0.8, 0.95, n_strip)
        alpha_0 = np.full(n_strip, np.deg2rad(-2.0))   # cambered
        m_slope = np.linspace(-0.02, -0.05, n_strip)
        m_0     = np.full(n_strip, -0.03)

        res = build_section_correction(
            boxes, ajj, f_slope=f_slope, alpha_0=alpha_0,
            m_slope=m_slope, m_0=m_0,
            caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
        )
        assert res.achieved_f_slope == pytest.approx(f_slope, rel=1e-8)
        assert res.achieved_m_slope == pytest.approx(m_slope, rel=1e-8)
        assert res.achieved_f0      == pytest.approx(-f_slope * alpha_0, rel=1e-8)
        assert res.achieved_m0      == pytest.approx(m_0, rel=1e-8)


class TestEndToEnd:
    def test_cards_reproduce_section_lines_through_aero_model(self):
        """Insert generated cards into a deck; build_aero_model + solve must
        reproduce the target force/moment line at every incidence."""
        nspan, nchord = 4, 3
        bulk = _rect_bulk(nspan, nchord)
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)

        f_slope = np.linspace(0.8, 0.95, nspan)
        alpha_0 = np.full(nspan, np.deg2rad(-1.5))
        m_slope = np.linspace(-0.02, -0.04, nspan)
        m_0     = np.full(nspan, -0.025)

        res = build_section_correction(
            boxes, ajj, f_slope=f_slope, alpha_0=alpha_0,
            m_slope=m_slope, m_0=m_0,
            caero_eid=CAERO_EID, sid_w2gj=101, sid_aecorr=201,
        )
        bulk.w2gjs[res.w2gj.sid] = res.w2gj
        bulk.aecorrs[res.aecorr.sid] = res.aecorr

        model = build_aero_model(bulk)
        x_mref = res.moment_ref

        # α = 0 → the zero-incidence offsets
        F0, M0 = _solve_section_lines(model, x_mref, 0.0)
        assert F0 == pytest.approx(-f_slope * alpha_0, rel=1e-6, abs=1e-9)
        assert M0 == pytest.approx(m_0, rel=1e-6, abs=1e-9)

        # α = 0.1 rad → slope·α + offset
        a = 0.1
        Fa, Ma = _solve_section_lines(model, x_mref, a)
        assert Fa == pytest.approx(f_slope * a - f_slope * alpha_0, rel=1e-6, abs=1e-9)
        assert Ma == pytest.approx(m_slope * a + m_0, rel=1e-6, abs=1e-9)


class TestGuards:
    def test_nchord_one_raises(self):
        boxes = _rect_wing(4, 1)
        ajj = build_ajj(boxes)
        with pytest.raises(ValueError, match="NCHORD"):
            build_section_correction(
                boxes, ajj, f_slope=np.ones(4), alpha_0=np.zeros(4),
                m_slope=np.zeros(4), m_0=np.zeros(4),
                caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
            )

    def test_multi_surface_raises(self):
        boxes = _rect_wing(2, 2)
        caero2 = Caero1(
            eid=99, pid=1, cp=0, nspan=2, nchord=2, lspan=0, lchord=0, igid=0,
            p1=(0.0, 6.0, 0.0), x12=1.0, p4=(0.0, 11.0, 0.0), x43=1.0,
        )
        boxes2 = mesh_caero1(caero2, PAERO, {}, {}, start_k=len(boxes))
        allboxes = boxes + boxes2
        ajj = build_ajj(allboxes)
        with pytest.raises(ValueError, match="single CAERO1|single surface|multiple CAERO1"):
            build_section_correction(
                allboxes, ajj, f_slope=np.ones(4), alpha_0=np.zeros(4),
                m_slope=np.zeros(4), m_0=np.zeros(4),
                caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
            )

    def test_length_mismatch_raises(self):
        boxes = _rect_wing(4, 3)
        ajj = build_ajj(boxes)
        with pytest.raises(ValueError, match="one value per span strip"):
            build_section_correction(
                boxes, ajj, f_slope=np.ones(3), alpha_0=np.zeros(4),
                m_slope=np.zeros(4), m_0=np.zeros(4),
                caero_eid=CAERO_EID, sid_w2gj=1, sid_aecorr=2,
            )


def _two_surface_parts():
    """Wing (EID 1000) + tail (EID 2000), both horizontal, meshed into one box list.

    EIDs are 1000 apart so the two surfaces' NASTRAN box-ID ranges cannot overlap
    (box ID = EID + i_span*NCHORD + j_chord).
    """
    wing = Caero1(eid=1000, pid=1, cp=0, nspan=4, nchord=3, lspan=0, lchord=0, igid=0,
                  p1=(0.0, 0.0, 0.0), x12=1.0, p4=(0.0, 5.0, 0.0), x43=1.0)
    tail = Caero1(eid=2000, pid=1, cp=0, nspan=3, nchord=2, lspan=0, lchord=0, igid=0,
                  p1=(4.0, 0.0, 0.0), x12=0.6, p4=(4.0, 2.0, 0.0), x43=0.6)
    bw = mesh_caero1(wing, PAERO, {}, {}, start_k=0)
    bt = mesh_caero1(tail, PAERO, {}, {}, start_k=len(bw))
    return wing, tail, bw + bt


def _two_surface_bulk(wing, tail):
    bulk = BulkData()
    bulk.aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=10.0, sref=10.0, symxz=0, symxy=0)
    bulk.paero1s[1] = Paero1(pid=1)
    bulk.caero1s[1000] = wing
    bulk.caero1s[2000] = tail
    return bulk


def _surface_lines(model, eid, x_mref, alpha):
    boxes = model.boxes
    cp = model.ajj_inv_corr @ (np.array([-(alpha * b.normal[2]) for b in boxes]) + model.wg)
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(boxes):
        if b.caero_eid == eid:
            groups[b.i_span].append(k)
    F, M = [], []
    for s, sp in enumerate(sorted(groups)):
        idx = np.array(groups[sp])
        fbox = np.array([boxes[k].area for k in idx]) * cp[idx]
        arm = np.array([boxes[k].force_point[0] for k in idx]) - x_mref[s]
        F.append(fbox.sum()); M.append(-(fbox * arm).sum())
    return np.array(F), np.array(M)


class TestMultiSurface:
    def test_two_surfaces_reproduced(self):
        wing, tail, boxes = _two_surface_parts()
        ajj = build_ajj(boxes)
        tW = SurfaceTargets(1000, f_slope=np.linspace(0.8, 0.95, 4),
                            alpha_0=np.full(4, np.deg2rad(-2.0)),
                            m_slope=np.linspace(-0.02, -0.04, 4), m_0=np.full(4, -0.025))
        tT = SurfaceTargets(2000, f_slope=np.linspace(0.4, 0.5, 3),
                            alpha_0=np.full(3, np.deg2rad(1.0)),
                            m_slope=np.full(3, -0.01), m_0=np.full(3, 0.005))
        res = build_section_correction_multi(
            boxes, ajj, [tW, tT], sid_w2gj_base=100, sid_aecorr_base=200)
        assert set(res.cards) == {1000, 2000}

        # Builder diagnostics reproduce both surfaces' targets.
        for eid, t in [(1000, tW), (2000, tT)]:
            d = res.per_surface[eid]
            assert d.achieved_f_slope == pytest.approx(t.f_slope, rel=1e-8)
            assert d.achieved_m_slope == pytest.approx(t.m_slope, rel=1e-8)
            assert d.achieved_f0 == pytest.approx(-t.f_slope * t.alpha_0, rel=1e-8)
            assert d.achieved_m0 == pytest.approx(t.m_0, rel=1e-8)

        # End-to-end: insert all cards, build_aero_model (combines both WT2 + both W2GJ).
        bulk = _two_surface_bulk(wing, tail)
        for w2, ac in res.cards.values():
            bulk.w2gjs[w2.sid] = w2
            bulk.aecorrs[ac.sid] = ac
        model = build_aero_model(bulk)
        for eid, t in [(1000, tW), (2000, tT)]:
            xref = res.per_surface[eid].moment_ref
            F0, M0 = _surface_lines(model, eid, xref, 0.0)
            assert F0 == pytest.approx(-t.f_slope * t.alpha_0, rel=1e-6, abs=1e-9)
            assert M0 == pytest.approx(t.m_0, rel=1e-6, abs=1e-9)
            a = 0.08
            Fa, Ma = _surface_lines(model, eid, xref, a)
            assert Fa == pytest.approx(t.f_slope * a - t.f_slope * t.alpha_0,
                                       rel=1e-6, abs=1e-9)
            assert Ma == pytest.approx(t.m_slope * a + t.m_0, rel=1e-6, abs=1e-9)

    def test_partial_correction_leaves_other_surface_unchanged(self):
        """Correcting only the wing → tail boxes keep r=1, wg=0."""
        wing, tail, boxes = _two_surface_parts()
        ajj = build_ajj(boxes)
        tW = SurfaceTargets(1000, f_slope=np.full(4, 0.9),
                            alpha_0=np.zeros(4), m_slope=np.zeros(4), m_0=np.zeros(4))
        res = build_section_correction_multi(
            boxes, ajj, [tW], sid_w2gj_base=100, sid_aecorr_base=200)
        assert set(res.cards) == {1000}
        tail_idx = [k for k, b in enumerate(boxes) if b.caero_eid == 2000]
        assert res.r[tail_idx] == pytest.approx(np.ones(len(tail_idx)), abs=1e-12)
        assert res.wg[tail_idx] == pytest.approx(np.zeros(len(tail_idx)), abs=1e-12)

    def test_cards_to_bdf_multi_round_trips(self):
        from sbeam.parser.bdf_reader import parse_bulk_data
        wing, tail, boxes = _two_surface_parts()
        ajj = build_ajj(boxes)
        tW = SurfaceTargets(1000, f_slope=np.full(4, 0.9), alpha_0=np.full(4, np.deg2rad(-1.0)),
                            m_slope=np.full(4, -0.02), m_0=np.full(4, -0.02))
        tT = SurfaceTargets(2000, f_slope=np.full(3, 0.45), alpha_0=np.zeros(3),
                            m_slope=np.full(3, -0.01), m_0=np.zeros(3))
        res = build_section_correction_multi(
            boxes, ajj, [tW, tT], sid_w2gj_base=100, sid_aecorr_base=200)
        bulk = parse_bulk_data(cards_to_bdf(res).splitlines())
        assert set(bulk.w2gjs) == {100, 101}
        assert set(bulk.aecorrs) == {200, 201}
        assert {c.caero_eid for c in bulk.aecorrs.values()} == {1000, 2000}


class TestBdfRoundTrip:
    def test_cards_to_bdf_parses_back(self):
        from sbeam.parser.bdf_reader import parse_bulk_data

        boxes = _rect_wing(4, 3)
        ajj = build_ajj(boxes)
        res = build_section_correction(
            boxes, ajj, f_slope=np.linspace(0.8, 0.95, 4),
            alpha_0=np.full(4, np.deg2rad(-2.0)),
            m_slope=np.linspace(-0.02, -0.05, 4), m_0=np.full(4, -0.03),
            caero_eid=CAERO_EID, sid_w2gj=101, sid_aecorr=201,
        )
        bulk = parse_bulk_data(cards_to_bdf(res).splitlines())

        assert np.array(bulk.w2gjs[101].data) == pytest.approx(np.array(res.w2gj.data), rel=1e-5)
        assert bulk.aecorrs[201].method == "WT2"
        assert np.array(bulk.aecorrs[201].target) == pytest.approx(
            np.array(res.aecorr.target), rel=1e-5)
