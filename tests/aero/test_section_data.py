"""Spanwise section-data ingestion (Option A GUI backend) — acceptance tests.

Covers ``sbeam.aero.section_data``: schema validation, condition listing, the
per-deg/local-chord/¼c → builder-target conversion, spanwise interpolation onto strips,
Mach/region selection (v1), and the operating-region helper.
"""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sbeam.model.aero import Caero1, Paero1, Aeros
from sbeam.model.bulk_data import BulkData
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import build_ajj
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd

PAERO = Paero1(pid=1)
CAERO_EID = 1


def _rect_wing(nspan, nchord, span=5.0, chord=1.0):
    caero = Caero1(
        eid=CAERO_EID, pid=1, cp=0,
        nspan=nspan, nchord=nchord, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=float(chord),
        p4=(0.0, float(span), 0.0), x43=float(chord),
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


def _const_df(boxes, cn_a, a0=0.0, cm_a=0.0, cm0=0.0, mach=0.0,
              a_lo=-2.0, a_hi=8.0, xref=0.25):
    """Section table with constant coefficients at the strip η-stations."""
    df = sd.template_dataframe(boxes, CAERO_EID, mach=mach, a_lo=a_lo, a_hi=a_hi)
    df["cn_a"] = cn_a
    df["a0"] = a0
    df["cm_a"] = cm_a
    df["cm0"] = cm0
    df["xref"] = xref
    return df


# --------------------------------------------------------------------------- validation

class TestValidation:
    def test_template_has_one_row_per_strip(self):
        boxes = _rect_wing(4, 3)
        df = sd.template_dataframe(boxes, CAERO_EID)
        assert list(df.columns) == sd.COLUMNS
        assert len(df) == 4

    def test_missing_column_raises(self):
        df = pd.DataFrame({"caero": [1]})
        with pytest.raises(ValueError, match="missing column"):
            sd.validate_section_data(df)

    def test_non_numeric_raises(self):
        boxes = _rect_wing(2, 2)
        df = _const_df(boxes, 0.1)
        df["cn_a"] = df["cn_a"].astype(object)
        df.loc[0, "cn_a"] = "oops"
        with pytest.raises(ValueError, match="non-numeric"):
            sd.validate_section_data(df)

    def test_bad_var_raises(self):
        boxes = _rect_wing(2, 2)
        df = _const_df(boxes, 0.1)
        df["var"] = "GAMMA"
        with pytest.raises(ValueError, match="ALPHA or BETA"):
            sd.validate_section_data(df)

    def test_inverted_range_raises(self):
        boxes = _rect_wing(2, 2)
        df = _const_df(boxes, 0.1, a_lo=8.0, a_hi=-2.0)
        with pytest.raises(ValueError, match="a_hi must exceed a_lo"):
            sd.validate_section_data(df)

    def test_conditions_listed(self):
        boxes = _rect_wing(3, 2)
        df0 = _const_df(boxes, 0.10, mach=0.4)
        df1 = _const_df(boxes, 0.13, mach=0.8)
        conds = sd.available_conditions(pd.concat([df0, df1], ignore_index=True))
        assert len(conds) == 2
        assert {c.mach for c in conds} == {0.4, 0.8}


# --------------------------------------------------------------------------- conversion

class TestConversion:
    def test_force_slope_conversion(self):
        """f_slope per strip == cn_a[/deg]·(180/π)·area_strip."""
        nspan, nchord = 4, 3
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)
        cn_a = 0.11   # per deg
        df = _const_df(boxes, cn_a)

        res = sd.build_from_section_data(
            boxes, ajj, df, caero_eid=CAERO_EID, mach=0.0, region=(-2.0, 8.0),
            sid_w2gj=1, sid_aecorr=2,
        )
        # independent strip areas
        from collections import defaultdict
        groups = defaultdict(list)
        for k, b in enumerate(boxes):
            groups[b.i_span].append(k)
        area = np.array([sum(boxes[k].area for k in groups[s]) for s in sorted(groups)])
        expect = cn_a * (180.0 / math.pi) * area
        assert res.correction.achieved_f_slope == pytest.approx(expect, rel=1e-8)

    def test_moment_offset_conversion(self):
        """m_0 per strip == cm0·c_strip·area_strip (local-chord normalised)."""
        nspan, nchord = 4, 3
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)
        cm0 = -0.05
        df = _const_df(boxes, cn_a=0.10, cm0=cm0)

        res = sd.build_from_section_data(
            boxes, ajj, df, caero_eid=CAERO_EID, mach=0.0, region=(-2.0, 8.0),
            sid_w2gj=1, sid_aecorr=2,
        )
        from collections import defaultdict
        groups = defaultdict(list)
        for k, b in enumerate(boxes):
            groups[b.i_span].append(k)
        area, chord = [], []
        for s in sorted(groups):
            idx = groups[s]
            a = sum(boxes[k].area for k in idx)
            b0 = boxes[idx[0]]
            dy = math.hypot(b0.bound_b[1] - b0.bound_a[1], b0.bound_b[2] - b0.bound_a[2])
            area.append(a); chord.append(a / dy)
        expect = cm0 * np.array(chord) * np.array(area)
        assert res.correction.achieved_m0 == pytest.approx(expect, rel=1e-8)

    def test_end_to_end_cl_slope_matches_section_value(self):
        """Constant cn_a, no camber/a.c. shift → wing CL_α == cn_a (per rad)."""
        nspan, nchord = 5, 3
        bulk = _rect_bulk(nspan, nchord)
        boxes = _rect_wing(nspan, nchord)
        ajj = build_ajj(boxes)
        cn_a = 0.095   # per deg
        df = _const_df(boxes, cn_a)

        res = sd.build_from_section_data(
            boxes, ajj, df, caero_eid=CAERO_EID, mach=0.0, region=(-2.0, 8.0),
            sid_w2gj=101, sid_aecorr=201,
        )
        bulk.w2gjs[101] = res.correction.w2gj
        bulk.aecorrs[201] = res.correction.aecorr
        model = build_aero_model(bulk)

        a = 0.1
        cp = model.ajj_inv_corr @ np.array([-(a * b.normal[2]) for b in model.boxes])
        fz = (np.array([b.area for b in model.boxes]) * cp).sum()
        cl_alpha = (fz / bulk.aeros.sref) / a
        assert cl_alpha == pytest.approx(cn_a * 180.0 / math.pi, rel=1e-8)


# --------------------------------------------------------------------------- selection

def _two_surface_parts():
    wing = Caero1(eid=1000, pid=1, cp=0, nspan=4, nchord=3, lspan=0, lchord=0, igid=0,
                  p1=(0.0, 0.0, 0.0), x12=1.0, p4=(0.0, 5.0, 0.0), x43=1.0)
    tail = Caero1(eid=2000, pid=1, cp=0, nspan=3, nchord=2, lspan=0, lchord=0, igid=0,
                  p1=(4.0, 0.0, 0.0), x12=0.6, p4=(4.0, 2.0, 0.0), x43=0.6)
    bw = mesh_caero1(wing, PAERO, {}, {}, start_k=0)
    bt = mesh_caero1(tail, PAERO, {}, {}, start_k=len(bw))
    return wing, tail, bw + bt


def _const_rows(boxes, eid, cn_a, mach=0.0, a_lo=-2.0, a_hi=8.0,
                a0=0.0, cm_a=0.0, cm0=0.0):
    df = sd.template_dataframe(boxes, eid, mach=mach, a_lo=a_lo, a_hi=a_hi)
    df["cn_a"] = cn_a; df["a0"] = a0; df["cm_a"] = cm_a; df["cm0"] = cm0
    return df


class TestMultiSurface:
    def test_two_surfaces_built(self):
        wing, tail, boxes = _two_surface_parts()
        from sbeam.aero.vlm import build_ajj
        ajj = build_ajj(boxes)
        df = pd.concat([
            _const_rows(boxes, 1000, 0.10, cm0=-0.03),
            _const_rows(boxes, 2000, 0.09, a0=1.0),
        ], ignore_index=True)

        res = sd.build_from_section_data_multi(
            boxes, ajj, df, mach=0.0, incidence_deg=3.0,
            sid_w2gj_base=100, sid_aecorr_base=200)
        assert set(res.correction.cards) == {1000, 2000}
        assert set(res.conditions) == {1000, 2000}
        # wing force-slope target reproduced (cn_a·180/π·area per strip)
        from collections import defaultdict
        groups = defaultdict(list)
        for k, b in enumerate(boxes):
            if b.caero_eid == 1000:
                groups[b.i_span].append(k)
        area = np.array([sum(boxes[k].area for k in groups[s]) for s in sorted(groups)])
        d = res.correction.per_surface[1000]
        assert d.achieved_f_slope == pytest.approx(0.10 * 180.0 / math.pi * area, rel=1e-8)

    def test_region_selected_per_surface_and_skip(self):
        wing, tail, boxes = _two_surface_parts()
        from sbeam.aero.vlm import build_ajj
        ajj = build_ajj(boxes)
        # Wing has a region covering α=10; tail only covers low α → tail skipped at α=10.
        df = pd.concat([
            _const_rows(boxes, 1000, 0.11, a_lo=-2.0, a_hi=6.0),
            _const_rows(boxes, 1000, 0.06, a_lo=6.0, a_hi=14.0),
            _const_rows(boxes, 2000, 0.09, a_lo=-2.0, a_hi=6.0),
        ], ignore_index=True)
        res = sd.build_from_section_data_multi(
            boxes, ajj, df, mach=0.0, incidence_deg=10.0,
            sid_w2gj_base=100, sid_aecorr_base=200)
        assert set(res.correction.cards) == {1000}
        assert res.conditions[1000].a_lo == 6.0 and res.conditions[1000].a_hi == 14.0
        assert any(eid == 2000 for eid, _ in res.skipped)


class TestSelection:
    def test_extrapolation_flag(self):
        """Strip η outside the table η-range → extrapolated=True."""
        boxes = _rect_wing(6, 3)
        ajj = build_ajj(boxes)
        df = _const_df(boxes, 0.1)
        # Drop the outer stations so the mesh extends beyond the table.
        df = df.sort_values("eta").iloc[1:-1].reset_index(drop=True)
        res = sd.build_from_section_data(
            boxes, ajj, df, caero_eid=CAERO_EID, mach=0.0, region=(-2.0, 8.0),
            sid_w2gj=1, sid_aecorr=2,
        )
        assert res.extrapolated is True

    def test_missing_condition_raises(self):
        boxes = _rect_wing(3, 2)
        ajj = build_ajj(boxes)
        df = _const_df(boxes, 0.1, mach=0.4)
        with pytest.raises(ValueError, match="no rows for CAERO"):
            sd.build_from_section_data(
                boxes, ajj, df, caero_eid=CAERO_EID, mach=0.9, region=(-2.0, 8.0),
                sid_w2gj=1, sid_aecorr=2,
            )

    def test_operating_region(self):
        boxes = _rect_wing(3, 2)
        df_lo = _const_df(boxes, 0.11, a_lo=-2.0, a_hi=6.0)
        df_hi = _const_df(boxes, 0.06, a_lo=6.0, a_hi=14.0)
        df = pd.concat([df_lo, df_hi], ignore_index=True)
        # signature: operating_region(df, caero, mach, incidence_deg)
        assert sd.operating_region(df, CAERO_EID, 0.0, 3.0) == (-2.0, 6.0)
        assert sd.operating_region(df, CAERO_EID, 0.0, 10.0) == (6.0, 14.0)
        assert sd.operating_region(df, CAERO_EID, 0.0, 20.0) is None


class TestValidationBindings:
    """DEF-L1 — the caero column and duplicate eta stations."""

    @staticmethod
    def _df():
        return sd.template_dataframe(_rect_wing(4, 3), CAERO_EID)

    def test_unknown_caero_raises_when_the_model_is_supplied(self):
        """The column used to be only astype(int); a typo matched no boxes."""
        df = self._df()
        df["caero"] = 999
        with pytest.raises(ValueError, match=r"caero \[999\] not in the model"):
            sd.validate_section_data(df, caero_eids={CAERO_EID})

    def test_known_caero_passes(self):
        df = self._df()
        assert len(sd.validate_section_data(df, caero_eids={CAERO_EID})) == len(df)

    def test_caero_unchecked_when_no_model_is_supplied(self):
        """Callers with no model to check against keep the old lenient behaviour."""
        df = self._df()
        df["caero"] = 999
        assert len(sd.validate_section_data(df)) == len(df)

    def test_duplicate_eta_in_one_curve_raises(self):
        """A repeated station makes the downstream np.interp non-monotone."""
        df = self._df()
        dup = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match=r"duplicate eta=.* each spanwise station"):
            sd.validate_section_data(dup)

    def test_same_eta_across_regions_is_legal(self):
        """Grouped, not global: one station legitimately recurs per alpha region."""
        lo = self._df()
        hi = self._df().assign(a_lo=6.0, a_hi=14.0)
        assert len(sd.validate_section_data(pd.concat([lo, hi], ignore_index=True))) \
            == 2 * len(lo)

    def test_same_eta_across_surfaces_and_machs_is_legal(self):
        a = self._df()
        b = self._df().assign(caero=CAERO_EID + 1000)
        c = self._df().assign(mach=0.6)
        merged = pd.concat([a, b, c], ignore_index=True)
        assert len(sd.validate_section_data(merged)) == 3 * len(a)

    def test_shipped_sample_csvs_are_clean_under_the_grouped_rule(self):
        """The grouped rule must not reject either shipped table."""
        from sbeam.aero.body_correction import split_total_rows
        root = Path(__file__).parent.parent.parent / "sample"
        for name in ("cessna210_section_data.csv", "cessna210_body_section_data.csv"):
            flying, _totals = split_total_rows(pd.read_csv(root / name))
            sd.validate_section_data(flying)      # must not raise
