"""AECORR's build Mach (#72).

The WT2 target is an absolute loading in circulation units on the Prandtl–Glauert
geometry *at the Mach it was built at*.  Without a Mach on the card the solver
re-ratioed it against the reference at each TRIM Mach, so a card built at M1 and used at
M2 gave the bare 1/β trend instead of the VLM's three-dimensional Mach trend.  The ratio
is now formed once at the card's MACH and applied at every TRIM Mach, as MSC applies a
WKK ("a single vector that applies to all subcases", AAUG 2023.1 PDF p.144).

Independent prediction: a uniform target of 1.2 × the reference at M1 is the ratio
r = 1.2 on every box, so the corrected lift slope at M2 is 1.2 × the bare VLM slope at
M2 and CLα_corr(M2) / CLα_corr(M1) = CLα_VLM(M2) / CLα_VLM(M1).  The re-ratioing code
gave β1/β2 instead (0.9798/0.8 = 1.2247 for M = 0.2 → 0.6; the VLM ratio on this
20 × 4 wing is 1.1292).
"""
import math

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.corrections import wt2_reference_cp
from sbeam.aero.vlm import build_ajj, prandtl_glauert_boxes
from sbeam.model.aero import Aecorr
from sbeam.parser.bdf_reader import parse_bulk_data
from tests.aero.test_corrections import CAERO_EID, _rect_bulk

M1, M2 = 0.2, 0.6


def _cl_alpha(bulk, mach):
    model = build_aero_model(bulk, mach=mach)
    n = len(model.boxes)
    return float((model.skj @ (model.ajj_inv_corr @ -np.ones(n)))[2::3].sum())


def _with_target(scale, mach_card):
    bulk = _rect_bulk(20, 4)
    boxes = build_aero_model(_rect_bulk(20, 4), mach=mach_card).boxes
    ajj = build_ajj(prandtl_glauert_boxes(boxes, mach_card))
    ref = wt2_reference_cp(boxes, np.linalg.inv(ajj))
    bulk.aecorrs[20] = Aecorr(sid=20, method="WT2", caero_eid=CAERO_EID, mach=mach_card,
                              target=(scale * ref).tolist())
    return bulk


def test_card_built_at_m1_follows_the_vlm_mach_trend_at_m2():
    bulk = _with_target(1.2, M1)
    corrected = _cl_alpha(bulk, M2) / _cl_alpha(bulk, M1)
    bare = _cl_alpha(_rect_bulk(20, 4), M2) / _cl_alpha(_rect_bulk(20, 4), M1)
    assert corrected == pytest.approx(bare, rel=1e-9)
    beta_ratio = math.sqrt(1 - M1**2) / math.sqrt(1 - M2**2)
    assert abs(corrected - beta_ratio) > 1e-2        # the old bare 1/β trend


def test_at_the_build_mach_the_target_is_met():
    bulk = _with_target(1.2, M2)
    assert _cl_alpha(bulk, M2) == pytest.approx(1.2 * _cl_alpha(_rect_bulk(20, 4), M2),
                                                rel=1e-12)


def test_card_mach_is_read_and_required():
    deck = ["AEROS, 0, 0, 1.0, 4.0, 4.0", "PAERO1, 1",
            "CAERO1, 100, 1, 0, 4, 1, 0, 0, 1", "+, 0., 0., 0., 1., 0., 4., 0., 1."]
    bulk = parse_bulk_data(deck + ["AECORR, 30, WT2, 100, 0.3, 0.80, 0.75, 0.65, 0.50"])
    assert (bulk.aecorrs[30].mach, bulk.aecorrs[30].target) == (0.3, [0.8, 0.75, 0.65, 0.5])
    with pytest.raises(ValueError, match="AECORR 30: MACH .field 5. is blank"):
        parse_bulk_data(deck + ["AECORR, 30, WT2, 100, , 0.80, 0.75, 0.65, 0.50"])
    with pytest.raises(ValueError, match="AECORR 30: MACH=1.2 must be in"):
        parse_bulk_data(deck + ["AECORR, 30, WT2, 100, 1.2, 0.80, 0.75, 0.65, 0.50"])


def test_a_card_in_the_old_layout_is_refused_by_its_length():
    """Before #72 the targets started in field 5: the first is now read as MACH, one
    target goes missing, and the length check names the new layout."""
    bulk = parse_bulk_data(["AEROS, 0, 0, 1.0, 4.0, 4.0", "PAERO1, 1",
                            "CAERO1, 100, 1, 0, 4, 1, 0, 0, 1",
                            "+, 0., 0., 0., 1., 0., 4., 0., 1.",
                            "AECORR, 30, WT2, 100, 0.80, 0.75, 0.65, 0.50"])
    with pytest.raises(ValueError, match="target length 3 != 4 boxes.*field 5 is MACH"):
        build_aero_model(bulk)
