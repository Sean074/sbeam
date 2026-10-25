"""
aero_db.py — Aerodynamic database loader and interpolator.

Loads baseline strip-coefficient CSVs and optional control-surface increment
tables, builds 4-D/5-D scipy.interpolate.RegularGridInterpolator objects over
(y_m, alpha_deg, beta_deg, mach_nd[, deflection_deg]), and evaluates strip
coefficients at a query flight state. Applies Prandtl-Glauert correction when
the query Mach lies outside the tabulated range.

Coordinate frame: structural frame (x-aft, y-starboard, z-up).
Coefficients are body-axis section quantities: cn_sec_nd (normal force),
cm_sec_nd (pitching moment about c/4, LE-up positive), cc_sec_nd (chord force,
positive in the drag direction per body-axis convention).
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

from .unit_convert import RAD_DEG

_KNOWN_SURFACES = {"wing", "htail", "vtail", "fuselage"}

_BASELINE_REQUIRED = {
    "y_m", "c_m", "alpha_deg", "beta_deg", "mach_nd",
    "cn_sec_nd", "cm_sec_nd", "cc_sec_nd",
}
_INCR_REQUIRED = {
    "y_m", "alpha_deg", "beta_deg", "mach_nd", "deflection_deg",
    "delta_cn_sec_nd", "delta_cm_sec_nd", "delta_cc_sec_nd",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_aero_db(
    baseline_path: Path,
    incr_paths: Optional[list] = None,
) -> dict:
    """
    Load baseline and optional increment aerodynamic databases.

    Parameters
    ----------
    baseline_path : Path to aero_<surface>_<config>.csv
    incr_paths    : Optional list of Paths to aero_incr_<surface>_<control>.csv

    Returns
    -------
    dict with keys:
        'surface', 'config_tag'      : str
        'y_m'                        : ndarray (M,) unique spanwise stations
        'c_m'                        : ndarray (M,) local chord at each station
        'alpha_deg', 'beta_deg',
        'mach_nd'                    : ndarrays of unique grid breakpoints
        'cn_interp', 'cm_interp',
        'cc_interp'                  : RegularGridInterpolator (M,P,Q,R)
        'mach_min_nd', 'mach_max_nd' : float
        'incr_data'                  : list of dicts — one per increment file
        'incr_count'                 : int

    Raises
    ------
    FileNotFoundError, ValueError
    """
    baseline_path = Path(baseline_path)
    if not baseline_path.exists():
        raise FileNotFoundError(f"Aero database not found: {baseline_path}")

    surface, config_tag = _extract_surface_config(baseline_path.name)
    df = _parse_baseline_csv(baseline_path)

    y_vals     = np.sort(df["y_m"].unique())
    alpha_vals = np.sort(df["alpha_deg"].unique())
    beta_vals  = np.sort(df["beta_deg"].unique())
    mach_vals  = np.sort(df["mach_nd"].unique())

    c_m_by_y = df.groupby("y_m")["c_m"].first()
    c_m = np.array([c_m_by_y[y] for y in y_vals])

    cn_interp = _build_interp4(df, y_vals, alpha_vals, beta_vals, mach_vals, "cn_sec_nd")
    cm_interp = _build_interp4(df, y_vals, alpha_vals, beta_vals, mach_vals, "cm_sec_nd")
    cc_interp = _build_interp4(df, y_vals, alpha_vals, beta_vals, mach_vals, "cc_sec_nd")

    incr_data = []
    for ipath in (incr_paths or []):
        ipath = Path(ipath)
        if not ipath.exists():
            raise FileNotFoundError(f"Increment file not found: {ipath}")
        incr_data.append(_load_incr(ipath))

    return {
        "surface":     surface,
        "config_tag":  config_tag,
        "y_m":         y_vals,
        "c_m":         c_m,
        "alpha_deg":   alpha_vals,
        "beta_deg":    beta_vals,
        "mach_nd":     mach_vals,
        "cn_interp":   cn_interp,
        "cm_interp":   cm_interp,
        "cc_interp":   cc_interp,
        "mach_min_nd": float(mach_vals[0]),
        "mach_max_nd": float(mach_vals[-1]),
        "incr_data":   incr_data,
        "incr_count":  len(incr_data),
    }


def interpolate_strips(
    aero_db: dict,
    alpha_rad: float,
    beta_rad: float,
    mach_nd: float,
    deflections_rad: Optional[dict] = None,
) -> tuple:
    """
    Evaluate strip coefficients at a flight state.

    Parameters
    ----------
    aero_db         : dict from load_aero_db()
    alpha_rad       : angle of attack [rad]
    beta_rad        : sideslip angle [rad]
    mach_nd         : Mach number
    deflections_rad : optional {control_tag: deflection [rad]}

    Returns
    -------
    (cn_sec_nd, cm_sec_nd, cc_sec_nd, pg_applied)
    Shapes (M,), (M,), (M,), bool.
    pg_applied=True when mach_nd was outside the tabulated range.
    """
    alpha_deg = float(alpha_rad) * RAD_DEG
    beta_deg  = float(beta_rad)  * RAD_DEG
    y_vals = aero_db["y_m"]
    M = len(y_vals)

    mach_min = aero_db["mach_min_nd"]
    mach_max = aero_db["mach_max_nd"]
    pg_applied = bool(mach_nd < mach_min or mach_nd > mach_max)
    mach_eval = float(np.clip(mach_nd, mach_min, mach_max))

    pts = np.column_stack([
        y_vals,
        np.full(M, alpha_deg),
        np.full(M, beta_deg),
        np.full(M, mach_eval),
    ])

    cn_sec_nd = aero_db["cn_interp"](pts).copy()
    cm_sec_nd = aero_db["cm_interp"](pts).copy()
    cc_sec_nd = aero_db["cc_interp"](pts).copy()

    if pg_applied:
        cn_sec_nd = prandtl_glauert_extrapolate(cn_sec_nd, mach_eval, mach_nd)
        cm_sec_nd = prandtl_glauert_extrapolate(cm_sec_nd, mach_eval, mach_nd)
        cc_sec_nd = prandtl_glauert_extrapolate(cc_sec_nd, mach_eval, mach_nd)

    for incr in aero_db["incr_data"]:
        ctrl_tag = incr["control_tag"]
        defl_rad = (deflections_rad or {}).get(ctrl_tag, 0.0)
        defl_deg = float(defl_rad) * RAD_DEG
        defl_clamped = float(np.clip(defl_deg, incr["defl_min_deg"], incr["defl_max_deg"]))
        pts5 = np.column_stack([
            y_vals,
            np.full(M, alpha_deg),
            np.full(M, beta_deg),
            np.full(M, mach_eval),
            np.full(M, defl_clamped),
        ])
        cn_sec_nd = cn_sec_nd + incr["cn_interp5"](pts5)
        cm_sec_nd = cm_sec_nd + incr["cm_interp5"](pts5)
        cc_sec_nd = cc_sec_nd + incr["cc_interp5"](pts5)

    return cn_sec_nd, cm_sec_nd, cc_sec_nd, pg_applied


def prandtl_glauert_extrapolate(
    cn_edge_nd: np.ndarray,
    mach_edge_nd: float,
    mach_nd: float,
) -> np.ndarray:
    """
    Apply Prandtl-Glauert compressibility correction from a tabulated edge Mach
    to a query Mach outside the database range.

    cn_extrap = cn_edge × sqrt(1 - mach_edge²) / sqrt(1 - mach²)

    Both Mach values are clamped to [0, 0.95] to avoid division by zero near M=1.
    """
    m_edge = min(float(mach_edge_nd), 0.95)
    m_q    = min(float(mach_nd), 0.95)
    beta_edge  = np.sqrt(max(1.0 - m_edge**2, 1e-6))
    beta_query = np.sqrt(max(1.0 - m_q**2,    1e-6))
    return cn_edge_nd * (beta_edge / beta_query)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_baseline_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    missing = _BASELINE_REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing required columns {sorted(missing)}")
    return df


def _parse_incr_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    missing = _INCR_REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing required columns {sorted(missing)}")
    df = df.rename(columns={
        "delta_cn_sec_nd": "cn_sec_nd",
        "delta_cm_sec_nd": "cm_sec_nd",
        "delta_cc_sec_nd": "cc_sec_nd",
    })
    return df


def _build_interp4(
    df: pd.DataFrame,
    y_vals: np.ndarray,
    alpha_vals: np.ndarray,
    beta_vals: np.ndarray,
    mach_vals: np.ndarray,
    coeff_col: str,
) -> RegularGridInterpolator:
    """Build a 4-D RegularGridInterpolator for one baseline coefficient."""
    shape = (len(y_vals), len(alpha_vals), len(beta_vals), len(mach_vals))
    arr = np.zeros(shape)

    y_idx = {v: i for i, v in enumerate(y_vals)}
    a_idx = {v: i for i, v in enumerate(alpha_vals)}
    b_idx = {v: i for i, v in enumerate(beta_vals)}
    m_idx = {v: i for i, v in enumerate(mach_vals)}

    for _, row in df.iterrows():
        i = y_idx.get(row["y_m"])
        j = a_idx.get(row["alpha_deg"])
        k = b_idx.get(row["beta_deg"])
        l = m_idx.get(row["mach_nd"])
        if None not in (i, j, k, l):
            arr[i, j, k, l] = row[coeff_col]

    return RegularGridInterpolator(
        (y_vals, alpha_vals, beta_vals, mach_vals),
        arr,
        method="linear",
        bounds_error=False,
        fill_value=None,
    )


def _build_interp5(
    df: pd.DataFrame,
    y_vals: np.ndarray,
    alpha_vals: np.ndarray,
    beta_vals: np.ndarray,
    mach_vals: np.ndarray,
    defl_vals: np.ndarray,
    coeff_col: str,
) -> RegularGridInterpolator:
    """Build a 5-D RegularGridInterpolator for one increment coefficient."""
    shape = (len(y_vals), len(alpha_vals), len(beta_vals), len(mach_vals), len(defl_vals))
    arr = np.zeros(shape)

    y_idx = {v: i for i, v in enumerate(y_vals)}
    a_idx = {v: i for i, v in enumerate(alpha_vals)}
    b_idx = {v: i for i, v in enumerate(beta_vals)}
    m_idx = {v: i for i, v in enumerate(mach_vals)}
    d_idx = {v: i for i, v in enumerate(defl_vals)}

    for _, row in df.iterrows():
        i = y_idx.get(row["y_m"])
        j = a_idx.get(row["alpha_deg"])
        k = b_idx.get(row["beta_deg"])
        l = m_idx.get(row["mach_nd"])
        p = d_idx.get(row["deflection_deg"])
        if None not in (i, j, k, l, p):
            arr[i, j, k, l, p] = row[coeff_col]

    return RegularGridInterpolator(
        (y_vals, alpha_vals, beta_vals, mach_vals, defl_vals),
        arr,
        method="linear",
        bounds_error=False,
        fill_value=None,
    )


def _load_incr(path: Path) -> dict:
    """Load one increment file and build 5-D interpolants."""
    _, control_tag = _extract_incr_surface_control(path.name)
    df = _parse_incr_csv(path)

    y_vals     = np.sort(df["y_m"].unique())
    alpha_vals = np.sort(df["alpha_deg"].unique())
    beta_vals  = np.sort(df["beta_deg"].unique())
    mach_vals  = np.sort(df["mach_nd"].unique())
    defl_vals  = np.sort(df["deflection_deg"].unique())

    return {
        "control_tag": control_tag,
        "y_m":         y_vals,
        "cn_interp5":  _build_interp5(df, y_vals, alpha_vals, beta_vals, mach_vals, defl_vals, "cn_sec_nd"),
        "cm_interp5":  _build_interp5(df, y_vals, alpha_vals, beta_vals, mach_vals, defl_vals, "cm_sec_nd"),
        "cc_interp5":  _build_interp5(df, y_vals, alpha_vals, beta_vals, mach_vals, defl_vals, "cc_sec_nd"),
        "defl_min_deg": float(defl_vals[0]),
        "defl_max_deg": float(defl_vals[-1]),
    }


def _extract_surface_config(filename: str) -> tuple:
    """Extract (surface, config_tag) from 'aero_<surface>_<config>.csv'."""
    stem = Path(filename).stem
    if not stem.startswith("aero_"):
        return "", stem
    rest = stem[5:]
    for surf in _KNOWN_SURFACES:
        if rest == surf:
            return surf, ""
        if rest.startswith(surf + "_"):
            return surf, rest[len(surf) + 1:]
    parts = rest.split("_", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _extract_incr_surface_control(filename: str) -> tuple:
    """Extract (surface, control_tag) from 'aero_incr_<surface>_<control>.csv'."""
    stem = Path(filename).stem
    if not stem.startswith("aero_incr_"):
        return "", stem
    rest = stem[10:]
    for surf in _KNOWN_SURFACES:
        if rest == surf:
            return surf, ""
        if rest.startswith(surf + "_"):
            return surf, rest[len(surf) + 1:]
    parts = rest.split("_", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""
