"""Spanwise section-data ingestion for the section force+moment correction (Option A GUI).

Turns a user-supplied table of **section coefficients** — a function of span, Mach, and a
linearised α/β region — into the per-strip dimensional targets that
``section_correction.build_section_correction`` consumes, and drives the build.

Input schema (tidy / "long" CSV — one row per surface × span-station × Mach × region):

  | column | meaning                                                              |
  |--------|----------------------------------------------------------------------|
  | caero  | CAERO1 EID the row applies to                                         |
  | eta    | span fraction within that CAERO1, 0 (root) … 1 (tip)                  |
  | mach   | freestream Mach for this block                                        |
  | var    | incidence variable: 'ALPHA' (lift surface) or 'BETA' (vertical)       |
  | a_lo   | region lower incidence bound (deg) — validity range                   |
  | a_hi   | region upper incidence bound (deg)                                    |
  | cn_a   | section normal-force-curve slope dC_n/d(var)   [per DEGREE]           |
  | a0     | zero-normal-force incidence (deg)                                     |
  | cm_a   | section pitch-moment slope dC_m/d(var) about `xref` [per DEGREE]      |
  | cm0    | section pitch moment at zero incidence (nose-up +)                    |
  | xref   | moment reference as a chord fraction (default 0.25 = ¼-chord)         |

Conventions
-----------
Coefficients are **local-chord** normalised (airfoil-polar convention): for a strip of
local chord ``c`` and area ``A = c·dy``,

    f_slope = (cn_a · 180/π) · A                  [force/q per rad]
    alpha_0 = a0 · π/180                          [rad]   → F₀ = −f_slope·alpha_0
    m_slope = (cm_a · 180/π) · c · A              [moment/q per rad, nose-up +]
    m_0     = cm0 · c · A                         [moment/q, nose-up +]

Pitching moment is **nose-up positive** about ``xref`` (chord fraction), matching
``section_correction`` / ``sol144._pitch_moment``.

Per-region (v1): a single operating region is selected and one W2GJ+WT2 pair is built; the
caller warns if the trimmed incidence falls outside ``[a_lo, a_hi]``.  Mach is selected by
exact match against the table (no Mach interpolation in v1).
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from sbeam.aero.section_correction import (
    build_section_correction,
    SectionCorrectionResult,
)

COLUMNS = ["caero", "eta", "mach", "var", "a_lo", "a_hi",
           "cn_a", "a0", "cm_a", "cm0", "xref"]
_NUMERIC = ["eta", "mach", "a_lo", "a_hi", "cn_a", "a0", "cm_a", "cm0", "xref"]
_VALID_VARS = {"ALPHA", "BETA"}
_DEG2RAD = math.pi / 180.0
_RAD2DEG = 180.0 / math.pi


@dataclass
class Condition:
    """One selectable (surface, Mach, region) block in a section-data table."""
    caero: int
    mach:  float
    var:   str
    a_lo:  float
    a_hi:  float
    n_stations: int

    @property
    def label(self) -> str:
        return (f"CAERO {self.caero} · M{self.mach:g} · {self.var} "
                f"[{self.a_lo:g}°,{self.a_hi:g}°] · {self.n_stations} stns")


def template_dataframe(boxes: list, caero_eid: int, mach: float = 0.0,
                       var: str = "ALPHA", a_lo: float = -2.0,
                       a_hi: float = 8.0) -> pd.DataFrame:
    """Starter table: one row per span strip of *caero_eid*, flat-plate defaults.

    Pre-fills ``eta`` from the actual strip mid-span fractions so the user only has to
    overwrite the coefficient columns.  Suitable for an ``st.data_editor`` seed and the
    template download.
    """
    etas = sorted({round(float(b.span_frac), 6)
                   for b in boxes if b.caero_eid == caero_eid})
    if not etas:
        etas = [0.0, 1.0]
    rows = [{
        "caero": caero_eid, "eta": e, "mach": float(mach), "var": var,
        "a_lo": a_lo, "a_hi": a_hi,
        "cn_a": round(2.0 * math.pi * _DEG2RAD, 5),  # thin-airfoil 2π/rad → per deg
        "a0": 0.0, "cm_a": 0.0, "cm0": 0.0, "xref": 0.25,
    } for e in etas]
    return pd.DataFrame(rows, columns=COLUMNS)


def validate_section_data(df: pd.DataFrame) -> pd.DataFrame:
    """Return a cleaned, type-coerced copy; raise ValueError on a malformed table."""
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"section data: missing column(s) {missing}; expected {COLUMNS}")
    out = df.copy()
    out["caero"] = out["caero"].astype(int)
    out["var"] = out["var"].astype(str).str.strip().str.upper()
    for c in _NUMERIC:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if out[_NUMERIC].isna().any().any():
        bad = out.index[out[_NUMERIC].isna().any(axis=1)].tolist()
        raise ValueError(f"section data: non-numeric/blank value in row(s) {bad}")
    badvar = sorted(set(out["var"]) - _VALID_VARS)
    if badvar:
        raise ValueError(f"section data: var must be ALPHA or BETA, got {badvar}")
    if (out["a_hi"] <= out["a_lo"]).any():
        bad = out.index[out["a_hi"] <= out["a_lo"]].tolist()
        raise ValueError(f"section data: a_hi must exceed a_lo in row(s) {bad}")
    if ((out["eta"] < -1e-9) | (out["eta"] > 1 + 1e-9)).any():
        raise ValueError("section data: eta must lie in [0, 1]")
    return out


def available_conditions(df: pd.DataFrame) -> list:
    """List the distinct (caero, mach, region) blocks, for a GUI selector."""
    out = validate_section_data(df)
    conds = []
    keys = ["caero", "mach", "var", "a_lo", "a_hi"]
    for key, grp in out.groupby(keys, sort=True):
        caero, mach, var, a_lo, a_hi = key
        conds.append(Condition(int(caero), float(mach), str(var),
                               float(a_lo), float(a_hi), len(grp)))
    return conds


def _strip_geometry(boxes: list):
    """Per-strip (sorted by i_span): η, area, local chord, leading-edge x."""
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(boxes):
        groups[b.i_span].append(k)
    strips = sorted(groups)
    eta, area, chord, le_x = [], [], [], []
    for s in strips:
        idx = groups[s]
        a = sum(boxes[k].area for k in idx)
        b0 = boxes[idx[0]]
        dy = math.hypot(b0.bound_b[1] - b0.bound_a[1], b0.bound_b[2] - b0.bound_a[2])
        eta.append(float(b0.span_frac))
        area.append(a)
        chord.append(a / max(dy, 1e-14))
        le_x.append(min(min(boxes[k].corners[0][0], boxes[k].corners[1][0]) for k in idx))
    return (np.array(eta), np.array(area), np.array(chord), np.array(le_x))


@dataclass
class SectionDataBuildResult:
    correction:  SectionCorrectionResult
    condition:   Condition
    extrapolated: bool          # any strip η outside the table's η-range (clamped)


def build_from_section_data(
    boxes: list,
    ajj: np.ndarray,
    df: pd.DataFrame,
    *,
    caero_eid: int,
    mach: float,
    region: tuple,
    sid_w2gj: int,
    sid_aecorr: int,
    mach_tol: float = 1e-6,
) -> SectionDataBuildResult:
    """Interpolate the selected (caero, mach, region) block onto the mesh strips,
    convert section coefficients to dimensional targets, and build the correction.

    Args:
        boxes:    AeroBox list for one CAERO1 (mesh order) — the whole AIC.
        ajj:      PG-consistent raw AIC at *mach* (pass ``β·ajj_pg`` so the reference
                  VLM solve matches the solver's 1/β-scaled operator; at M=0, ``β=1``).
        df:       section-data table (validated or raw).
        region:   (a_lo, a_hi) selecting the linearised incidence region.
        mach_tol: tolerance for the exact-Mach row match.

    Returns:
        SectionDataBuildResult with the generated cards and an extrapolation flag.
    """
    data = validate_section_data(df)
    a_lo, a_hi = float(region[0]), float(region[1])
    sel = data[(data["caero"] == caero_eid)
               & (np.abs(data["mach"] - mach) <= mach_tol)
               & (np.abs(data["a_lo"] - a_lo) <= 1e-9)
               & (np.abs(data["a_hi"] - a_hi) <= 1e-9)]
    if sel.empty:
        raise ValueError(
            f"build_from_section_data: no rows for CAERO {caero_eid}, Mach {mach}, "
            f"region [{a_lo}, {a_hi}]. Available: "
            f"{[c.label for c in available_conditions(data)]}"
        )
    sel = sel.sort_values("eta")
    var = str(sel["var"].iloc[0])

    eta_s, area_s, chord_s, le_x_s = _strip_geometry(boxes)

    eta_d = sel["eta"].to_numpy()
    extrapolated = bool(eta_s.min() < eta_d.min() - 1e-9
                        or eta_s.max() > eta_d.max() + 1e-9)

    def interp(col):
        return np.interp(eta_s, eta_d, sel[col].to_numpy())  # clamps at the ends

    cn_a = interp("cn_a")     # per deg
    a0   = interp("a0")       # deg
    cm_a = interp("cm_a")     # per deg
    cm0  = interp("cm0")
    xref = interp("xref")     # chord fraction

    # Coefficients (local-chord normalised, per deg) → builder targets (per rad).
    f_slope = (cn_a * _RAD2DEG) * area_s
    alpha_0 = a0 * _DEG2RAD
    m_slope = (cm_a * _RAD2DEG) * chord_s * area_s
    m_0     = cm0 * chord_s * area_s
    moment_ref = le_x_s + xref * chord_s

    corr = build_section_correction(
        boxes, ajj,
        f_slope=f_slope, alpha_0=alpha_0, m_slope=m_slope, m_0=m_0,
        caero_eid=caero_eid, sid_w2gj=sid_w2gj, sid_aecorr=sid_aecorr,
        moment_ref=moment_ref,
    )
    cond = Condition(caero_eid, float(mach), var, a_lo, a_hi, len(sel))
    return SectionDataBuildResult(correction=corr, condition=cond,
                                  extrapolated=extrapolated)


def operating_region(df: pd.DataFrame, caero_eid: int, mach: float,
                     incidence_deg: float, mach_tol: float = 1e-6):
    """Return the (a_lo, a_hi) region whose range contains *incidence_deg*, or None.

    Helper for the GUI to pick / validate the operating region against a trim incidence.
    """
    data = validate_section_data(df)
    sel = data[(data["caero"] == caero_eid)
               & (np.abs(data["mach"] - mach) <= mach_tol)]
    for (a_lo, a_hi), _ in sel.groupby(["a_lo", "a_hi"]):
        if a_lo - 1e-9 <= incidence_deg <= a_hi + 1e-9:
            return (float(a_lo), float(a_hi))
    return None
