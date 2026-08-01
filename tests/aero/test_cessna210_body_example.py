"""Refined Cessna 210 worked example — cruciform body panels (Step A9).

Validates that ``sample/cessna210_body.bdf`` + ``sample/cessna210_body_section_data.csv``:
  - parse and mesh into a 7-surface, full-span VLM model (wing/HTP/VTP + body cruciform);
  - place the vertical tail so it intersects the horizontal tail (no gap);
  - orient the body panels as a cruciform (horizontal normal +Z, vertical normal +Y);
  - drive the end-to-end two-stage correction (flying section data → body residual) so
    the TOTAL airplane Cm/Cn reach the CSV ``TOTAL`` targets.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd
from sbeam.aero.body_correction import (
    build_body_correction,
    parse_body_targets,
    split_total_rows,
    RATIO_WARN,
)

_ROOT = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = _ROOT / "cessna210_body.bdf"
CSV_PATH = _ROOT / "cessna210_body_section_data.csv"


@pytest.fixture(scope="module")
def deck():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    return bulk, build_aero_model(bulk)


def test_deck_meshes_seven_surfaces(deck):
    bulk, model = deck
    assert sorted(bulk.caero1s) == [1000, 2000, 3000, 4000, 5000, 6000, 7000]
    # wing 2*16*6 + HTP 2*8*6 + VTP 6*6 + body-H 2*8 + body-V 4*8 = 192+96+36+16+32
    assert len(model.boxes) == 372
    assert sorted(bulk.spline0s) == [9400, 9500]


def test_vtp_intersects_htp(deck):
    _bulk, model = deck
    vtp_z = [c[2] for b in model.boxes if b.caero_eid == 5000 for c in b.corners]
    # the fin now spans through the HTP plane (z = 0.70), no gap
    assert min(vtp_z) <= 0.60 + 1e-9
    assert min(vtp_z) < 0.70 < max(vtp_z)


def test_body_panels_are_a_cruciform(deck):
    _bulk, model = deck
    nh = np.mean([b.normal for b in model.boxes if b.caero_eid == 6000], axis=0)
    nv = np.mean([b.normal for b in model.boxes if b.caero_eid == 7000], axis=0)
    assert abs(nh[2]) > 0.99 and abs(nh[0]) < 1e-6 and abs(nh[1]) < 1e-6   # +Z
    assert abs(nv[1]) > 0.99 and abs(nv[0]) < 1e-6 and abs(nv[2]) < 1e-6   # +Y


def test_body_panels_clear_of_empennage(deck):
    """The fix: no body box — and (since trailing legs run downstream in +X) no body
    box's wake — may reach the empennage, so the panels cannot spuriously load the tail.
    """
    _bulk, model = deck
    body_x = [c[0] for b in model.boxes if b.caero_eid in (6000, 7000) for c in b.corners]
    emp_x = [c[0] for b in model.boxes if b.caero_eid in (3000, 4000, 5000) for c in b.corners]
    # every body box (hence its +X trailing wake's origin) ends well ahead of the
    # most-forward empennage leading edge — wakes pass the tail x-station having already
    # cleared it in z/y (checked below), never through an empennage box
    assert max(body_x) < min(emp_x) - 1.0
    # vertical body panel shares the fin's y=0 plane, so it must stay BELOW the VTP root
    vtp_z = [c[2] for b in model.boxes if b.caero_eid == 5000 for c in b.corners]
    vbody_z = [c[2] for b in model.boxes if b.caero_eid == 7000 for c in b.corners]
    assert max(vbody_z) < min(vtp_z) + 1e-9
    # horizontal body panel stays below the HTP plane
    htp_z = [c[2] for b in model.boxes if b.caero_eid in (3000, 4000) for c in b.corners]
    hbody_z = [c[2] for b in model.boxes if b.caero_eid == 6000 for c in b.corners]
    assert max(hbody_z) < min(htp_z)


def test_two_stage_correction_reaches_total_targets(deck):
    bulk, model = deck
    df = pd.read_csv(CSV_PATH)
    flying, totals = split_total_rows(df)
    assert len(totals) == 1

    # stage 1 — flying surfaces from spanwise section data
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, flying, mach=0.0, incidence_deg=3.0,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    assert sorted(res.correction.cards) == [1000, 2000, 3000, 4000, 5000]
    assert res.skipped == []
    w2 = {w.sid: w for (w, _a) in res.correction.cards.values()}
    ac = {a.sid: a for (_w, a) in res.correction.cards.values()}
    bulk_f = dataclasses.replace(
        bulk, w2gjs={**bulk.w2gjs, **w2}, aecorrs={**bulk.aecorrs, **ac})

    # stage 2 — body panels absorb the residual to the CSV TOTAL targets
    tgt = parse_body_targets(df, mach=0.0)
    out = build_body_correction(bulk_f, horiz_eid=6000, vert_eid=7000,
                                targets=tgt, mach=0.0)
    assert out.converged
    for k in ("cm_alpha", "cm0", "cn_beta", "cn0", "cl_beta", "cl0"):
        assert getattr(out.achieved, k) == pytest.approx(getattr(tgt, k), abs=1e-6)
    # the body genuinely moves the airplane totals toward the realistic fuselage increment
    # (mild destabilising pitch + yaw); roll is ~0 by design — a slender body adds no roll.
    assert abs(out.achieved.cm_alpha - out.baseline.cm_alpha) > 0.1   # pitch destabilised
    assert abs(out.achieved.cn_beta - out.baseline.cn_beta) > 0.01    # yaw destabilised
    # ratio_max is NOT a contamination metric: WT2 is a post-inverse diagonal on the body
    # rows only, so it never perturbs the lifting surfaces.  Panels held clear of the tail
    # are weakly coupled, so a ratio of tens is normal and benign — only the sane band is
    # required (see docs/10_standard/05_aeroelastics.md "Cruciform limitations").
    assert out.ratio_max < RATIO_WARN
