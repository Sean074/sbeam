"""Spanwise section-data ingestion (Option A GUI backend) — acceptance tests.

Covers ``sbeam.aero.section_data``: schema validation, condition listing, the
per-deg/local-chord/¼c → builder-target conversion, spanwise interpolation onto strips,
Mach/region selection (v1), and the operating-region helper.
"""

import math

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
