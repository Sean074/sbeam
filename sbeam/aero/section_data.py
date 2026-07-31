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
``section_correction`` / ``sol144.pitch_moment``.

Per-region (v1): a single operating region is selected and one W2GJ+WT2 pair is built; the
caller warns if the trimmed incidence falls outside ``[a_lo, a_hi]``.  Mach is selected by
exact match against the table (no Mach interpolation in v1).
"""

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple, cast

import numpy as np
import pandas as pd

from sbeam.aero.section_correction import (
    build_section_correction,
    build_section_correction_multi,
    SurfaceTargets,
    SectionCorrectionResult,
    MultiSectionCorrectionResult,
)
from sbeam.types import FloatArray
from sbeam.aero.panel import AeroBox

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


def template_dataframe(boxes: list[AeroBox], caero_eid: int, mach: float = 0.0,
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
    return pd.DataFrame(rows, columns=pd.Index(COLUMNS))


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
    if bool(out[_NUMERIC].isna().to_numpy().any()):
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


def available_conditions(df: pd.DataFrame) -> list[Condition]:
    """List the distinct (caero, mach, region) blocks, for a GUI selector."""
    out = validate_section_data(df)
    conds: list[Condition] = []
    keys = ["caero", "mach", "var", "a_lo", "a_hi"]
    for key, grp in out.groupby(keys, sort=True):
        caero, mach, var, a_lo, a_hi = cast(Tuple[Any, ...], key)
        conds.append(Condition(int(caero), float(mach), str(var),
                               float(a_lo), float(a_hi), len(grp)))
    return conds


def _strip_geometry(
    boxes: list[AeroBox], caero_eid: int
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray]:
    """Per-strip (one CAERO1, sorted by i_span): η, area, local chord, leading-edge x."""
    from collections import defaultdict
    groups = defaultdict(list)
    for k, b in enumerate(boxes):
        if b.caero_eid == caero_eid:
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


def _beta_pg(mach: float) -> float:
    return math.sqrt(1.0 - mach * mach) if 0.0 < mach < 1.0 else 1.0


def _select_block(
    data: pd.DataFrame, caero_eid: int, mach: float,
    region: tuple[float, float], mach_tol: float = 1e-6,
) -> pd.DataFrame:
    a_lo, a_hi = float(region[0]), float(region[1])
    sel = data[(data["caero"] == caero_eid)
               & (np.abs(data["mach"] - mach) <= mach_tol)
               & (np.abs(data["a_lo"] - a_lo) <= 1e-9)
               & (np.abs(data["a_hi"] - a_hi) <= 1e-9)]
    return cast(pd.DataFrame, sel).sort_values(by="eta")


def _surface_targets(boxes: list[AeroBox], sel: pd.DataFrame, caero_eid: int):
    """Interpolate a selected block onto a surface's strips and convert to targets.

    Returns (SurfaceTargets, extrapolated, var).
    """
    eta_s, area_s, chord_s, le_x_s = _strip_geometry(boxes, caero_eid)
    eta_d = sel["eta"].to_numpy()
    extrapolated = bool(eta_s.min() < eta_d.min() - 1e-9
                        or eta_s.max() > eta_d.max() + 1e-9)

    def interp(col: str) -> FloatArray:
        return np.interp(eta_s, eta_d, sel[col].to_numpy())  # clamps at the ends

    cn_a, a0, cm_a, cm0, xref = (interp(c) for c in ("cn_a", "a0", "cm_a", "cm0", "xref"))
    # Coefficients (local-chord normalised, per deg) → builder targets (per rad).
    tgt = SurfaceTargets(
        caero_eid=caero_eid,
        f_slope=(cn_a * _RAD2DEG) * area_s,
        alpha_0=a0 * _DEG2RAD,
        m_slope=(cm_a * _RAD2DEG) * chord_s * area_s,
        m_0=cm0 * chord_s * area_s,
        moment_ref=le_x_s + xref * chord_s,
    )
    return tgt, extrapolated, str(sel["var"].iloc[0])


@dataclass
class SectionDataBuildResult:
    correction:  SectionCorrectionResult
    condition:   Condition
    extrapolated: bool          # any strip η outside the table's η-range (clamped)


@dataclass
class MultiSectionDataBuildResult:
    correction:   MultiSectionCorrectionResult
    conditions:   dict[int, Condition]
    extrapolated: dict[int, bool]
    skipped:      list[tuple[int, str]]   # surfaces with no usable region


def build_from_section_data(
    boxes: list[AeroBox],
    ajj: FloatArray,
    df: pd.DataFrame,
    *,
    caero_eid: int,
    mach: float,
    region: tuple[float, float],
    sid_w2gj: int,
    sid_aecorr: int,
    mach_tol: float = 1e-6,
) -> SectionDataBuildResult:
    """Single-surface build: interpolate the selected (caero, mach, region) block onto the
    mesh strips, convert section coefficients to targets, and build the correction.

    Args:
        boxes:    AeroBox list for one CAERO1 (mesh order) — the whole AIC.
        ajj:      raw PG AIC ``ajj_pg`` at *mach* (e.g. ``build_aero_model(bulk, mach).ajj``).
                  The Prandtl–Glauert 1/β factor is applied internally from *mach*.
        region:   (a_lo, a_hi) selecting the linearised incidence region.

    Returns:
        SectionDataBuildResult with the generated cards and an extrapolation flag.
    """
    data = validate_section_data(df)
    a_lo, a_hi = float(region[0]), float(region[1])
    sel = _select_block(data, caero_eid, mach, region, mach_tol)
    if sel.empty:
        raise ValueError(
            f"build_from_section_data: no rows for CAERO {caero_eid}, Mach {mach}, "
            f"region [{a_lo}, {a_hi}]. Available: "
            f"{[c.label for c in available_conditions(data)]}"
        )
    tgt, extrapolated, var = _surface_targets(boxes, sel, caero_eid)
    corr = build_section_correction(
        boxes, ajj,
        f_slope=tgt.f_slope, alpha_0=tgt.alpha_0, m_slope=tgt.m_slope, m_0=tgt.m_0,
        caero_eid=caero_eid, sid_w2gj=sid_w2gj, sid_aecorr=sid_aecorr,
        moment_ref=tgt.moment_ref, beta=_beta_pg(mach),
    )
    cond = Condition(caero_eid, float(mach), var, a_lo, a_hi, len(sel))
    return SectionDataBuildResult(correction=corr, condition=cond,
                                  extrapolated=extrapolated)


def surface_var(
    df: pd.DataFrame, caero_eid: int, mach: float, mach_tol: float = 1e-6
) -> Optional[str]:
    """Return the single incidence variable ('ALPHA'/'BETA') for a surface at *mach*.

    Returns ``None`` if the surface has no rows at this Mach, or the string
    ``"MIXED"`` if it carries more than one ``var`` (one axis per surface is
    required — the caller skips such a surface).
    """
    data = validate_section_data(df)
    sel = data[(data["caero"] == caero_eid) & (np.abs(data["mach"] - mach) <= mach_tol)]
    vs = sorted(set(sel["var"]))
    if not vs:
        return None
    if len(vs) > 1:
        return "MIXED"
    return vs[0]


def build_from_section_data_multi(
    boxes: list[AeroBox],
    ajj: FloatArray,
    df: pd.DataFrame,
    *,
    mach: float,
    incidence_deg: Optional[float] = None,
    alpha_deg: Optional[float] = None,
    beta_deg: Optional[float] = None,
    sid_w2gj_base: int,
    sid_aecorr_base: int,
    caeros: Optional[Iterable[int]] = None,
    mach_tol: float = 1e-6,
) -> MultiSectionDataBuildResult:
    """Multi-surface build at one flight point (Mach + operating α and β).

    For every CAERO1 present in the table at *mach* (or the subset *caeros*), the surface's
    incidence variable (``var`` = ALPHA or BETA) selects which operating angle applies —
    ``alpha_deg`` for an ALPHA surface, ``beta_deg`` for a BETA surface (each falls back to
    ``incidence_deg`` when its own value is not given, preserving the single-axis call).
    The region whose range contains that angle is selected (v1: one region per surface),
    its block is interpolated onto the surface's strips and converted, and a single
    **global** correction is built (one W2GJ + WT2 card pair per surface).

    Surfaces are skipped (reported in ``.skipped``) when: they carry more than one ``var``
    (one axis per surface required); the relevant operating angle was not supplied; or no
    region covers that angle.

    Args:
        boxes: whole-model AeroBox list (full AIC).
        ajj:   raw PG AIC ``ajj_pg`` at *mach* (``build_aero_model(bulk, mach).ajj``);
               the 1/β factor is applied internally from *mach*.
    """
    data = validate_section_data(df)
    table_caeros = sorted(set(int(c) for c in data["caero"].unique()))
    want = table_caeros if caeros is None else [int(c) for c in caeros]

    targets, conditions, extrap, skipped = [], {}, {}, []
    for eid in want:
        var = surface_var(data, eid, mach, mach_tol)
        if var is None:
            skipped.append((eid, "no rows at this Mach"))
            continue
        if var == "MIXED":
            skipped.append((eid, "surface has both ALPHA and BETA rows (one axis per surface)"))
            continue
        # Pick the operating angle for this surface's axis; fall back to incidence_deg.
        angle = (alpha_deg if var == "ALPHA" else beta_deg)
        if angle is None:
            angle = incidence_deg
        if angle is None:
            axis = "α" if var == "ALPHA" else "β"
            skipped.append((eid, f"no operating {axis} supplied for this {var} surface"))
            continue
        region = operating_region(data, eid, mach, angle, mach_tol)
        if region is None:
            axis = "α" if var == "ALPHA" else "β"
            skipped.append((eid, f"no region contains {axis}={angle}° at Mach {mach}"))
            continue
        sel = _select_block(data, eid, mach, region, mach_tol)
        if sel.empty:
            skipped.append((eid, "no rows at this Mach"))
            continue
        tgt, ex, var = _surface_targets(boxes, sel, eid)
        targets.append(tgt)
        conditions[eid] = Condition(eid, float(mach), var, region[0], region[1], len(sel))
        extrap[eid] = ex

    if not targets:
        raise ValueError(
            f"build_from_section_data_multi: no surfaces usable at Mach {mach}, "
            f"incidence {incidence_deg}°. Skipped: {skipped}"
        )

    corr = build_section_correction_multi(
        boxes, ajj, targets,
        sid_w2gj_base=sid_w2gj_base, sid_aecorr_base=sid_aecorr_base, beta=_beta_pg(mach),
    )
    return MultiSectionDataBuildResult(correction=corr, conditions=conditions,
                                       extrapolated=extrap, skipped=skipped)


def operating_region(df: pd.DataFrame, caero_eid: int, mach: float,
                     incidence_deg: float, mach_tol: float = 1e-6):
    """Return the (a_lo, a_hi) region whose range contains *incidence_deg*, or None.

    Helper for the GUI to pick / validate the operating region against a trim incidence.
    """
    data = validate_section_data(df)
    sel = data[(data["caero"] == caero_eid)
               & (np.abs(data["mach"] - mach) <= mach_tol)]
    for key, _ in sel.groupby(["a_lo", "a_hi"]):
        a_lo, a_hi = cast(Tuple[float, float], key)
        if a_lo - 1e-9 <= incidence_deg <= a_hi + 1e-9:
            return (float(a_lo), float(a_hi))
    return None
