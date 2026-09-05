"""Cessna 210 worked example — multi-surface section correction + viewer aero tab.

Points at the flagship family (`sample/cessna210_flagship_bulk.bdf` +
`sample/cessna210_flagship_section_data.csv`), which replaced the standalone
`cessna210_aero.bdf` / `cessna210_section_data.csv` pair at Step 65.

Scope here is the CORRECTION SYNTHESISER and the VIEWER surfaces that render it; the
deck-level, trim-level and transient gates live in `test_cessna210_flagship.py`.

The numbers below are re-derived for the flagship's 3D-informed table and are NOT the
old deck's: that table was flat 2D-polar data (0.105/deg at every station), which is
precisely what this example now exists to warn against.
"""

import math
import warnings
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam_tools.corrections import section_data as sd
from sbeam.aero.aero_model import build_aero_model
from sbeam_tools.corrections import split_total_rows
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf

_ROOT = Path(__file__).parent.parent.parent / "sample"
BDF_PATH = _ROOT / "cessna210_flagship_trim.bdf"
CSV_PATH = _ROOT / "cessna210_flagship_section_data.csv"
_RAD2DEG = 180.0 / math.pi
_ALPHA_REF = 2.3904          # the incidence the committed correction is baked about


@pytest.fixture(scope="module")
def model_and_data():
    warnings.simplefilter("ignore")
    _cc, bulk = parse_bdf(str(BDF_PATH))
    model = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    # Since Step 66 the CSV also carries the body-panel TOTAL block; the
    # flying-surface synthesiser only accepts var in {ALPHA, BETA}.
    df, _totals = split_total_rows(pd.read_csv(CSV_PATH))
    return bulk, model, df


@pytest.fixture(scope="module")
def uncorrected(model_and_data):
    """The same model with the committed W2GJ/AECORR cards stripped back out."""
    bulk, _model, _df = model_and_data
    bare = deepcopy(bulk)
    bare.w2gjs.clear()
    bare.aecorrs.clear()
    return build_aero_model(bare, grid_index=build_grid_index(bare))


def _strip_areas(model, caero_eid):
    """Per-strip (span_frac, area) for one CAERO1 — the same geometry, in the same
    order, that `section_data._strip_geometry` interpolates the table onto."""
    groups = defaultdict(list)
    for k, b in enumerate(model.boxes):
        if b.caero_eid == caero_eid:
            groups[b.i_span].append(k)
    order = sorted(groups)
    areas = np.array([sum(model.boxes[k].area for k in groups[s]) for s in order])
    etas = np.array([float(model.boxes[groups[s][0]].span_frac) for s in order])
    return etas, areas


def test_deck_meshes_five_surfaces(model_and_data):
    bulk, model, _df = model_and_data
    assert sorted(bulk.caero1s) == [1000, 2000, 3000, 4000, 5000]
    # wing 2*16*6 + HTP 2*8*6 + VTP 6*6 = 192 + 96 + 36
    assert len(model.boxes) == 324
    assert bulk.aeros.sref == pytest.approx(16.24)
    assert bulk.aeros.cref == pytest.approx(1.4707)
    assert bulk.aeros.symxz == 0 and bulk.aeros.symxy == 0   # full-span


def test_multi_correction_all_surfaces(model_and_data):
    bulk, model, df = model_and_data
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, df, mach=0.0, incidence_deg=_ALPHA_REF,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    assert sorted(res.correction.cards) == [1000, 2000, 3000, 4000, 5000]
    assert res.skipped == []
    # the wing picks the low-incidence region; the VTP is the BETA surface
    assert (res.conditions[1000].a_lo, res.conditions[1000].a_hi) == (-4.0, 8.0)
    assert res.conditions[5000].var == "BETA"
    assert res.conditions[3000].var == "ALPHA"

    # Per-strip force slope reproduces the TABULATED, SPANWISE-VARYING cn_a.
    # (The old flat-CSV version of this test compared against a single constant.)
    d = res.correction.per_surface[1000]
    wing = df[(df.caero == 1000) & (df.a_hi == 8.0)]
    etas, areas = _strip_areas(model, 1000)
    cn_a = np.interp(etas, wing.eta.to_numpy(), wing.cn_a.to_numpy())
    assert d.achieved_f_slope == pytest.approx(cn_a * _RAD2DEG * areas, rel=1e-8)
    # the distribution really is tapered, not a constant dressed up as one
    assert cn_a[-1] < 0.6 * cn_a.max()

    # Wing carries camber moment (cm0 < 0); the symmetric HTP does not.
    assert np.all(np.abs(d.achieved_m0) > 1e-6)
    assert np.allclose(res.correction.per_surface[3000].achieved_m0, 0.0, atol=1e-9)


def test_correction_takes_effect_through_operator(model_and_data, uncorrected):
    """Camber shows up as lift at zero incidence, and the slope moves only slightly.

    This is the worked example's headline result.  The wing is cambered (a0 = -2.5 deg
    at the root, washing out to +0.5 deg at the tip), so the corrected operator carries
    lift at alpha = 0 where the bare VLM carries none.  The lift SLOPE, though, barely
    moves: the table is anchored to the model's own 3D strip loading, so WT2 has almost
    nothing to correct.  Feed the same machinery a raw 2D polar (0.105/deg) instead and
    the slope is driven to ~0.105/deg = 6.0/rad on the wing alone — an unphysical
    finite-wing lift slope, because the VLM's downwash gets counted twice.
    """
    bulk, model, _df = model_and_data
    area = np.array([b.area for b in model.boxes])

    def cl(m, alpha):
        w = np.array([-(alpha * b.normal[2]) for b in m.boxes]) + m.wg
        return float((area * (m.ajj_inv_corr @ w)).sum() / bulk.aeros.sref)

    def slope(m):
        return (cl(m, math.radians(3.0)) - cl(m, 0.0)) / 3.0

    assert cl(uncorrected, 0.0) == pytest.approx(0.0, abs=1e-12)   # flat plate
    assert cl(model, 0.0) == pytest.approx(0.0994, abs=0.01)       # camber lift

    bare_slope, corr_slope = slope(uncorrected), slope(model)
    assert bare_slope == pytest.approx(0.0910, abs=0.002)
    assert corr_slope == pytest.approx(0.0931, abs=0.002)
    # 3D-informed data nudges the slope by a couple of percent, not by a third
    assert abs(corr_slope / bare_slope - 1.0) < 0.05
    assert corr_slope * _RAD2DEG < 5.8, "corrected lift slope drifted into 2D territory"


def test_rigid_derivative_table_and_span_figure(model_and_data):
    """Aero-tab rigid S&C table + 5-surface span loading on the worked example."""
    from sbeam.aero.vlm import solve_rigid_cl
    from sbeam.viewer.aero_view import (
        rigid_derivative_table, build_span_loading_figure,
    )
    bulk, model, _df = model_and_data

    tab = rigid_derivative_table(model, bulk, naming="aero")
    assert list(tab.columns) == ["CZ", "CY", "Cl", "Cm", "Cn", "CX"]
    # corrected rigid CZ_alpha (body-axis vertical-force column; wind-axis CL only
    # near alpha = 0 — see A-GUI2a)
    assert tab.loc["α", "CZ"] == pytest.approx(5.33, abs=0.4)
    assert tab.loc["α", "Cm"] < 0.0          # statically stable: pitch-down with alpha

    # Span loading: one cn + one cm line per CAERO1 surface (5 surfaces → 10 traces).
    res = solve_rigid_cl(model.boxes, np.radians(3.0), aeros=model.aeros,
                         cp_operator=model.ajj_inv_corr)
    fig = build_span_loading_figure(model.boxes, res["cp"])
    assert len(fig.data) == 2 * 5


def test_section_preview_figure(model_and_data):
    from sbeam.viewer.aero_view import build_section_correction_figure
    _bulk, model, df = model_and_data
    res = sd.build_from_section_data_multi(
        model.boxes, model.ajj, df, mach=0.0, incidence_deg=_ALPHA_REF,
        sid_w2gj_base=9100, sid_aecorr_base=9200)
    fig = build_section_correction_figure(model.boxes, df, res, caero_eid=1000)
    assert len(fig.data) == 4   # input cn, achieved cn, input cm0, achieved cm0

    # The achieved curves (traces 1, 3) reproduce the tabulated inputs across the whole
    # span.  The input covers eta 0..1 so nothing is extrapolated; with a SPANWISE
    # table the check is against the interpolated distribution, not a constant.
    wing = df[(df.caero == 1000) & (df.a_hi == 8.0)]
    for achieved, column in ((fig.data[1], "cn_a"), (fig.data[3], "cm0")):
        x = np.asarray(achieved.x, dtype=float)
        expected = np.interp(x, wing.eta.to_numpy(), wing[column].to_numpy())
        np.testing.assert_allclose(np.asarray(achieved.y, dtype=float),
                                   expected, rtol=1e-5, atol=1e-8)
