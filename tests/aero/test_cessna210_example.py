"""Cessna 210-like worked example — deck + multi-surface section correction.

Validates that `sample/cessna210_aero.bdf` + `sample/cessna210_section_data.csv`:
  - parse and mesh into a 5-surface, full-span VLM model;
  - drive `build_from_section_data_multi` to a card pair per surface (no skips);
  - reproduce the section targets, and that the WT2 slope + W2GJ camber take effect
    through the SOL 144 corrected-operator path.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd

_ROOT = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = _ROOT / "cessna210_aero.bdf"
CSV_PATH = _ROOT / "cessna210_section_data.csv"
_RAD2DEG = 180.0 / math.pi


@pytest.fixture(scope="module")
def model_and_data():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    model = build_aero_model(bulk)
    df = pd.read_csv(CSV_PATH)
    return bulk, model, df


def test_deck_meshes_five_surfaces(model_and_data):
    bulk, model, _df = model_and_data
    assert sorted(bulk.caero1s) == [100, 150, 200, 250, 300]
    # wing 2*16*6 + HTP 2*8*6 + VTP 6*6 = 192 + 96 + 36
    assert len(model.boxes) == 324
    assert bulk.aeros.sref == pytest.approx(16.24)
    assert bulk.aeros.symxz == 0 and bulk.aeros.symxy == 0   # full-span


def test_multi_correction_all_surfaces(model_and_data):
    bulk, model, df = model_and_data
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, df, mach=0.0, incidence_deg=3.0,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    assert sorted(res.correction.cards) == [100, 150, 200, 250, 300]
    assert res.skipped == []
    # wing picks the low-α region; VTP is the BETA surface
    assert (res.conditions[100].a_lo, res.conditions[100].a_hi) == (-4.0, 8.0)
    assert res.conditions[300].var == "BETA"

    # Wing per-strip force slope reproduces cn_a (0.105/deg) × area_strip.
    d = res.correction.per_surface[100]
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(model.boxes):
        if b.caero_eid == 100:
            groups[b.i_span].append(k)
    area = np.array([sum(model.boxes[k].area for k in groups[s]) for s in sorted(groups)])
    assert d.achieved_f_slope == pytest.approx(0.105 * _RAD2DEG * area, rel=1e-8)
    # Wing has camber moment (cm0 = -0.065 → nonzero m_0); HTP is symmetric (≈0).
    assert np.all(np.abs(d.achieved_m0) > 1e-6)
    assert np.allclose(res.correction.per_surface[200].achieved_m0, 0.0, atol=1e-9)


def test_correction_takes_effect_through_operator(model_and_data):
    bulk, model, df = model_and_data
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, df, mach=0.0, incidence_deg=3.0,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    for w2, ac in res.correction.cards.values():
        bulk.w2gjs[w2.sid] = w2
        bulk.aecorrs[ac.sid] = ac
    model2 = build_aero_model(bulk)
    area = np.array([b.area for b in model2.boxes])

    def cl(alpha):
        w = np.array([-(alpha * b.normal[2]) for b in model2.boxes]) + model2.wg
        cp = model2.ajj_inv_corr @ w
        return float((area * cp).sum() / bulk.aeros.sref)

    cl0 = cl(0.0)
    slope = (cl(math.radians(3.0)) - cl0) / 3.0
    # Camber (wing a0=-2.5°) gives positive lift at α=0.
    assert cl0 > 0.2
    # WT2 raises the lift slope toward the section value (wing 0.105 + tail) — well
    # above the uncorrected VLM (~0.091/deg).
    assert slope > 0.11
