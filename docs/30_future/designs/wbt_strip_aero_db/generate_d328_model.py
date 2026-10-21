"""
generate_d328_model.py — Simplified Dornier 328-class flight-loads test model.

Produces the full data set the WBT_LOADS program needs to exercise flight-loads
analysis (Categories A static flight and B dynamic flight only — ground loads
are out of scope for this model):

  data/lra/                  4 LRA JSON files (wing, htail, vtail, fuselage)
  data/aero/                 4 baseline aero CSVs + 3 increment CSVs
  data/mass/                 2 NASTRAN BDF mass models (MZFW fwd CG, MZFW aft CG)
  data/conditions/static_flight/sfl_sample.csv     6 Category A conditions
  data/conditions/dynamic_flight/dfl_gust_sample.csv  4 Category B conditions

Aerodynamics is synthetic strip theory:
  - Elliptical lift distribution on wing and htail (3D lift slope via
    finite-AR correction; chord-tapered to give realistic peak/avg ratio).
  - Vtail: elliptical sideforce vs. sideslip β.
  - Fuselage: weak slender-body linear-in-α normal force.
  - Pitching moment: small constant Cm0 about local c/4.
  - Chord force (Cc): Cc0 + k × Cn² (parabolic drag polar by strip).
  - Compressibility: Prandtl-Glauert baked into the gridded data so
    aero_db.py interpolation reproduces it directly inside the M-range and
    its own PG extrapolation gives the correct value outside.
  - Control increments: elevator on htail (uniform), aileron on outer wing
    (antisymmetric, only between |y|=4.5..9.0 m), rudder on vtail (sideforce).

Mass model is point masses (CONM2 only, CID=0); written in imperial (ft, slug)
to exercise the unit-conversion path in mass_model.py. Two payload configs
(forward and aft CG) share the same structural mass set.

All geometry in SI (metres). Coordinate frame: structural (x-aft, y-stbd, z-up).
This is a TEST / DEVELOPMENT model — synthetic aero is NOT regulatory credible.
"""

import json
import math
from pathlib import Path

import numpy as np

# ============================================================
# Reference geometry — Do 328 class
# ============================================================

AIRCRAFT_ID = "D328_SIM"

# Wing
B_M             = 21.20   # span [m]
S_REF_M2        = 40.00   # reference area [m^2]
MAC_M           = 2.00    # mean aerodynamic chord [m]
X_LE_MAC_M      = 8.00    # x of LE at MAC [m]
C_ROOT_M        = 2.60    # root chord [m]
C_TIP_M         = 1.40    # tip chord [m]
WING_SWEEP_DEG  = 5.0     # elastic-axis sweep, aft [deg]
WING_DIHED_DEG  = 3.0     # dihedral [deg]
WING_LRA_X_ROOT = 9.00    # LRA root x (≈40% root chord aft of LE) [m]
WING_LRA_Z_ROOT = 1.50    # LRA root z (low-wing) [m]

# Htail
HTAIL_SEMI_M       = 2.00
HTAIL_C_ROOT_M     = 1.50
HTAIL_C_TIP_M      = 0.80
HTAIL_SWEEP_DEG    = 5.0
HTAIL_LRA_X_ROOT   = 19.50
HTAIL_LRA_Z        = 2.50
S_HTAIL_M2         = 5.00

# Vtail
VTAIL_HEIGHT_M     = 3.00
VTAIL_C_ROOT_M     = 1.80
VTAIL_C_TIP_M      = 1.00
VTAIL_SWEEP_DEG    = 30.0
VTAIL_LRA_X_ROOT   = 18.50
VTAIL_LRA_Z_ROOT   = 2.50
S_VTAIL_M2         = 3.50

# Fuselage
FUS_LEN_M          = 21.00
FUS_LRA_Z          = 0.0   # centerline z (matches existing fuselage LRA convention)
FUS_MAX_DIAM_M     = 2.50

# Masses
OEW_KG    = 8920.0
MZFW_KG   = 12400.0
PAYLOAD_KG = MZFW_KG - OEW_KG   # 3480

# Target CGs (from %MAC) — x_cg = X_LE_MAC_M + frac × MAC_M
X_CG_FWD_M = X_LE_MAC_M + 0.15 * MAC_M   # 8.30 m
X_CG_AFT_M = X_LE_MAC_M + 0.35 * MAC_M   # 8.70 m

# Aero parameters (3D lift slopes from finite-AR strip theory)
AR_WING = B_M ** 2 / S_REF_M2                       # 11.236
CL_ALPHA_WING_RAD = 2 * math.pi / (1 + 2 / AR_WING)  # /rad

B_HTAIL = 2 * HTAIL_SEMI_M
AR_HTAIL = B_HTAIL ** 2 / S_HTAIL_M2                 # 3.20
CL_ALPHA_HTAIL_RAD = 2 * math.pi / (1 + 2 / AR_HTAIL)
ETA_HTAIL = 0.90                                    # tail dynamic-pressure factor

AR_VTAIL_EFF = VTAIL_HEIGHT_M ** 2 / S_VTAIL_M2     # 2.57
CY_BETA_VTAIL_RAD = 2 * math.pi / (1 + 2 / AR_VTAIL_EFF)

# Control effectiveness (per rad of deflection, as fraction of surface lift slope)
ELEVATOR_EFFECTIVENESS = 0.40
AILERON_EFFECTIVENESS  = 0.30
RUDDER_EFFECTIVENESS   = 0.40

# Aileron span on each wing (|y| range)
AILERON_Y_INNER_M = 4.5
AILERON_Y_OUTER_M = 9.0

# Tabulation grids
ALPHA_DEG_GRID    = [-8, -4, 0, 4, 8, 12, 16]
BETA_DEG_GRID     = [-10, -5, 0, 5, 10]
MACH_GRID         = [0.20, 0.30, 0.40, 0.50, 0.60]
ELEVATOR_DEG_GRID = [-25, -10, 0, 10, 25]
AILERON_DEG_GRID  = [-20, -10, 0, 10, 20]
RUDDER_DEG_GRID   = [-25, -10, 0, 10, 25]

# Unit conversion (SI → imperial for BDF on-disk)
M_FT    = 3.280839895013123
KG_SLUG = 0.0685217658567918

DATA_ROOT = Path(__file__).parent
LRA_DIR  = DATA_ROOT / "lra"
AERO_DIR = DATA_ROOT / "aero"
MASS_DIR = DATA_ROOT / "mass"
COND_DIR = DATA_ROOT / "conditions"


# ============================================================
# Helpers
# ============================================================

def chord_wing(y_m: float) -> float:
    return C_ROOT_M - (C_ROOT_M - C_TIP_M) * abs(y_m) / (B_M / 2.0)


def chord_htail(y_m: float) -> float:
    return HTAIL_C_ROOT_M - (HTAIL_C_ROOT_M - HTAIL_C_TIP_M) * abs(y_m) / HTAIL_SEMI_M


def chord_vtail(z_above_root_m: float) -> float:
    return VTAIL_C_ROOT_M - (VTAIL_C_ROOT_M - VTAIL_C_TIP_M) * z_above_root_m / VTAIL_HEIGHT_M


def diameter_fuselage(x_m: float) -> float:
    """Smooth nose taper, cylindrical centre section, tail taper."""
    if x_m < 4.0:
        return FUS_MAX_DIAM_M * (x_m / 4.0) ** 0.5
    if x_m < 15.0:
        return FUS_MAX_DIAM_M
    return FUS_MAX_DIAM_M * max(0.30, (FUS_LEN_M - x_m) / 6.0)


def pg(mach: float) -> float:
    return 1.0 / math.sqrt(1.0 - mach ** 2)


# ============================================================
# LRA JSONs
# ============================================================

def gen_wing_lra() -> dict:
    """21 stations: 10 port + root + 10 starboard, 5° aft sweep, 3° dihedral."""
    n_side = 10
    ys = np.linspace(-B_M / 2.0, B_M / 2.0, 2 * n_side + 1)
    sweep = math.radians(WING_SWEEP_DEG)
    dih   = math.radians(WING_DIHED_DEG)
    stations = []
    for y in ys:
        x = WING_LRA_X_ROOT + abs(y) * math.tan(sweep)
        z = WING_LRA_Z_ROOT + abs(y) * math.tan(dih)
        # Normal tilts inboard at stbd (toward -y) and at port (toward +y).
        # At root (y=0) there is no dihedral tilt — normal is pure +z.
        if y > 1e-9:
            ny = -math.sin(dih)
            nz = math.cos(dih)
        elif y < -1e-9:
            ny = +math.sin(dih)
            nz = math.cos(dih)
        else:
            ny = 0.0
            nz = 1.0
        stations.append({
            "station_id": f"WS{y:+07.3f}m",
            "position_m": [float(x), float(y), float(z)],
            "normal_nd":  [0.0, float(ny), float(nz)],
        })
    return {
        "surface": "wing",
        "description": "Do 328-class wing: 21 stations, 5° aft sweep, 3° dihedral",
        "stations": stations,
    }


def gen_htail_lra() -> dict:
    """11 stations: 5 port + root + 5 starboard, 5° aft sweep, no dihedral."""
    n_side = 5
    ys = np.linspace(-HTAIL_SEMI_M, HTAIL_SEMI_M, 2 * n_side + 1)
    sweep = math.radians(HTAIL_SWEEP_DEG)
    stations = []
    for y in ys:
        x = HTAIL_LRA_X_ROOT + abs(y) * math.tan(sweep)
        z = HTAIL_LRA_Z
        stations.append({
            "station_id": f"HS{y:+06.3f}m",
            "position_m": [float(x), float(y), float(z)],
            "normal_nd":  [0.0, 0.0, 1.0],
        })
    return {
        "surface": "htail",
        "description": "Do 328-class horizontal tail: 11 stations, 5° aft sweep",
        "stations": stations,
    }


def gen_vtail_lra() -> dict:
    """5 stations along the vtail elastic axis, 30° aft sweep.
    Convention (matches existing project): position_m[1]=0, spanwise variation
    in position_m[2] (z). station_id labels z above root.
    """
    n = 5
    z_above = np.linspace(0.0, VTAIL_HEIGHT_M, n)
    sweep = math.radians(VTAIL_SWEEP_DEG)
    stations = []
    for za in z_above:
        x = VTAIL_LRA_X_ROOT + za * math.tan(sweep)
        z = VTAIL_LRA_Z_ROOT + za
        stations.append({
            "station_id": f"VS{za:5.3f}m",
            "position_m": [float(x), 0.0, float(z)],
            "normal_nd":  [0.0, 1.0, 0.0],
        })
    return {
        "surface": "vtail",
        "description": "Do 328-class vertical tail: 5 stations, 30° aft sweep",
        "stations": stations,
    }


def gen_fuselage_lra() -> dict:
    """11 stations along centerline from x=0.5 to x=20.5 m.
    Convention (matches existing project): position_m = [x, 0, 0]; normal=+z.
    """
    n = 11
    xs = np.linspace(0.5, 20.5, n)
    stations = []
    for x in xs:
        stations.append({
            "station_id": f"FS{x:06.3f}m",
            "position_m": [float(x), 0.0, FUS_LRA_Z],
            "normal_nd":  [0.0, 0.0, 1.0],
        })
    return {
        "surface": "fuselage",
        "description": "Do 328-class fuselage centerline: 11 stations from FS0.5 to FS20.5",
        "stations": stations,
    }


# ============================================================
# Baseline aero CSVs
# ============================================================

# Cn_sec elliptical helper:
#   cn(y, α) = (4 S_ref CL_α α) / (π b c(y)) × sqrt(1 - (2y/b)^2) × PG
# Integrating gives L = CL × q × S exactly (since ∫ sqrt(1-η²) dy × b/2 over [-1,1] = π/4).

def _aero_lifting_surface(y_arr, chord_fn, s_ref, b_span,
                          cl_alpha_rad, eta_dynp, cm0, primary_angle="alpha"):
    """Common builder for an elliptical-loading lifting surface."""
    rows = []
    for y in y_arr:
        c = chord_fn(y)
        eta = 2.0 * y / b_span
        ell = math.sqrt(max(0.0, 1.0 - eta ** 2))
        for a_deg in ALPHA_DEG_GRID:
            a_rad = math.radians(a_deg)
            for b_deg in BETA_DEG_GRID:
                b_rad = math.radians(b_deg)
                drive = a_rad if primary_angle == "alpha" else b_rad
                drive = eta_dynp * drive
                for m in MACH_GRID:
                    cn = (4.0 * s_ref * cl_alpha_rad * drive) \
                         / (math.pi * b_span * c) * ell * pg(m)
                    cm = cm0 * pg(m)
                    cc = 0.010 + 0.040 * cn * cn
                    rows.append([float(y), float(c), float(a_deg),
                                 float(b_deg), float(m),
                                 float(cn), float(cm), float(cc)])
    return rows


def gen_wing_aero():
    ys = np.linspace(-B_M / 2.0, B_M / 2.0, 21)
    return _aero_lifting_surface(
        ys, chord_wing, S_REF_M2, B_M,
        CL_ALPHA_WING_RAD, 1.0, cm0=-0.05, primary_angle="alpha",
    )


def gen_htail_aero():
    ys = np.linspace(-HTAIL_SEMI_M, HTAIL_SEMI_M, 11)
    return _aero_lifting_surface(
        ys, chord_htail, S_HTAIL_M2, B_HTAIL,
        CL_ALPHA_HTAIL_RAD, ETA_HTAIL, cm0=-0.03, primary_angle="alpha",
    )


def gen_vtail_aero():
    """Vtail spanwise coordinate stored in 'y_m' column is z above root.
    Sideforce vs β (using CY_β); cn here is sideforce coefficient.
    Vtail station load distribution: elliptical between root and tip,
    peak at mid-span (typical for swept fin).
    """
    rows = []
    z_above_arr = np.linspace(0.0, VTAIL_HEIGHT_M, 5)
    b_span = VTAIL_HEIGHT_M
    for za in z_above_arr:
        c = chord_vtail(za)
        # Map to [-1,+1] for elliptical: peaks at mid (za = h/2)
        eta = 2.0 * za / VTAIL_HEIGHT_M - 1.0
        ell = math.sqrt(max(0.0, 1.0 - eta ** 2))
        for a_deg in ALPHA_DEG_GRID:
            for b_deg in BETA_DEG_GRID:
                b_rad = math.radians(b_deg)
                for m in MACH_GRID:
                    cn = (4.0 * S_VTAIL_M2 * CY_BETA_VTAIL_RAD * b_rad) \
                         / (math.pi * b_span * c) * ell * pg(m)
                    cm = -0.02 * pg(m)
                    cc = 0.015 + 0.040 * cn * cn
                    rows.append([float(za), float(c), float(a_deg),
                                 float(b_deg), float(m),
                                 float(cn), float(cm), float(cc)])
    return rows


def gen_fuselage_aero():
    """Slender-body weak vertical lift, linear in α.
    'y_m' column holds the fuselage station x (matches LRA position_m[0]).
    """
    rows = []
    xs = np.linspace(0.5, 20.5, 11)
    for x in xs:
        c = diameter_fuselage(x)
        for a_deg in ALPHA_DEG_GRID:
            a_rad = math.radians(a_deg)
            for b_deg in BETA_DEG_GRID:
                for m in MACH_GRID:
                    cn = 0.50 * a_rad * pg(m)        # weak body vertical force
                    cm = 0.0
                    cc = 0.005 + 0.020 * a_rad * a_rad
                    rows.append([float(x), float(c), float(a_deg),
                                 float(b_deg), float(m),
                                 float(cn), float(cm), float(cc)])
    return rows


# ============================================================
# Increment CSVs (control surfaces)
# Columns: y_m, alpha_deg, beta_deg, mach_nd, deflection_deg,
#          delta_cn_sec_nd, delta_cm_sec_nd, delta_cc_sec_nd
# (Note: no c_m column — increment table format per existing project convention.)
# ============================================================

def gen_elevator_incr():
    """Elevator on htail: uniform Δcn across span proportional to δe."""
    rows = []
    ys = np.linspace(-HTAIL_SEMI_M, HTAIL_SEMI_M, 11)
    cn_d_e_rad = ELEVATOR_EFFECTIVENESS * CL_ALPHA_HTAIL_RAD
    for y in ys:
        for a_deg in ALPHA_DEG_GRID:
            for b_deg in BETA_DEG_GRID:
                for m in MACH_GRID:
                    for de_deg in ELEVATOR_DEG_GRID:
                        de_rad = math.radians(de_deg)
                        d_cn = cn_d_e_rad * de_rad * pg(m)
                        d_cm = -0.50 * cn_d_e_rad * de_rad * pg(m)
                        d_cc = 0.0
                        rows.append([float(y), float(a_deg), float(b_deg),
                                     float(m), float(de_deg),
                                     float(d_cn), float(d_cm), float(d_cc)])
    return rows


def gen_aileron_incr():
    """Aileron on outer wing only (4.5 ≤ |y| ≤ 9.0 m); antisymmetric.
    Sign: positive δa = stbd TE down → +cn on stbd, −cn on port.
    """
    rows = []
    ys = np.linspace(-B_M / 2.0, B_M / 2.0, 21)
    cn_d_a_rad = AILERON_EFFECTIVENESS * CL_ALPHA_WING_RAD
    for y in ys:
        in_aileron = (AILERON_Y_INNER_M <= abs(y) <= AILERON_Y_OUTER_M)
        sign = 1.0 if y > 0.0 else (-1.0 if y < 0.0 else 0.0)
        for a_deg in ALPHA_DEG_GRID:
            for b_deg in BETA_DEG_GRID:
                for m in MACH_GRID:
                    for da_deg in AILERON_DEG_GRID:
                        da_rad = math.radians(da_deg)
                        if in_aileron and sign != 0.0:
                            d_cn = sign * cn_d_a_rad * da_rad * pg(m)
                            d_cm = -0.20 * abs(d_cn)
                            d_cc = 0.0
                        else:
                            d_cn = 0.0
                            d_cm = 0.0
                            d_cc = 0.0
                        rows.append([float(y), float(a_deg), float(b_deg),
                                     float(m), float(da_deg),
                                     float(d_cn), float(d_cm), float(d_cc)])
    return rows


def gen_rudder_incr():
    """Rudder on vtail: positive δr = TE to port → sideforce on tail to port,
    nose-right yawing moment. Vtail normal = +y, so port-going sideforce
    corresponds to NEGATIVE delta_cn in vtail body frame.
    """
    rows = []
    z_above_arr = np.linspace(0.0, VTAIL_HEIGHT_M, 5)
    cy_d_r_rad = RUDDER_EFFECTIVENESS * CY_BETA_VTAIL_RAD
    for za in z_above_arr:
        for a_deg in ALPHA_DEG_GRID:
            for b_deg in BETA_DEG_GRID:
                for m in MACH_GRID:
                    for dr_deg in RUDDER_DEG_GRID:
                        dr_rad = math.radians(dr_deg)
                        d_cn = -cy_d_r_rad * dr_rad * pg(m)
                        d_cm = -0.30 * abs(d_cn)
                        d_cc = 0.0
                        rows.append([float(za), float(a_deg), float(b_deg),
                                     float(m), float(dr_deg),
                                     float(d_cn), float(d_cm), float(d_cc)])
    return rows


# ============================================================
# Mass model (CONM2 + GRID, imperial units on disk)
# ============================================================

# Structural mass points common to both CG cases.
# Sum to OEW = 8920 kg.
STRUCT_POINTS = [
    # (description, mass_kg, x_m, y_m, z_m)
    # Wing structure (10 points, mass tapered by chord)
    ("wing_port_y02",   184.7,  9.175, -2.0,  1.605),
    ("wing_port_y04",   167.3,  9.350, -4.0,  1.710),
    ("wing_port_y06",   149.8,  9.525, -6.0,  1.815),
    ("wing_port_y08",   132.4,  9.700, -8.0,  1.920),
    ("wing_port_y10",   115.7,  9.875, -10.0, 2.025),
    ("wing_stbd_y02",   184.7,  9.175, +2.0,  1.605),
    ("wing_stbd_y04",   167.3,  9.350, +4.0,  1.710),
    ("wing_stbd_y06",   149.8,  9.525, +6.0,  1.815),
    ("wing_stbd_y08",   132.4,  9.700, +8.0,  1.920),
    ("wing_stbd_y10",   115.7,  9.875, +10.0, 2.025),
    # Engines (wing-mounted nacelles, forward of LE)
    ("engine_port",     400.0,  7.0,   -4.0,  1.5),
    ("engine_stbd",     400.0,  7.0,   +4.0,  1.5),
    # Fuselage structure (forward-weighted to keep OEW CG near wing)
    ("fuselage_x03",   1500.0,  3.0,    0.0,  1.0),
    ("fuselage_x06",   1200.0,  6.0,    0.0,  1.0),
    ("fuselage_x09",   1000.0,  9.0,    0.0,  1.0),
    ("fuselage_x13",    500.0, 13.0,    0.0,  1.0),
    ("fuselage_x17",    300.0, 17.0,    0.0,  1.0),
    # Equipment
    ("avionics",        600.0,  2.0,    0.0,  1.5),
    ("fwd_systems",     300.0,  5.0,    0.0,  1.0),
    ("wing_junct_sys",  400.0,  9.0,    0.0,  1.0),
    ("aft_cabin_sys",   100.0, 14.0,    0.0,  1.5),
    ("apu",             120.0, 18.5,    0.0,  2.5),
    # Empennage
    ("htail_struct",    180.0, 19.5,    0.0,  2.5),
    ("vtail_struct",    220.0, 19.0,    0.0,  4.0),
    ("aft_fus_struct",  200.0, 20.0,    0.0,  1.5),
]
# Sum: 749.9 + 749.9 + 800 + 4500 + 1520 + 600 = 8919.8 ≈ 8920 kg ✓

# Payload sets (each totals 3480 kg).
# Positioned to hit MZFW target CGs given the structural CG.
# Fwd-CG case: payload skewed forward; aft-CG case: payload skewed aft.
PAYLOAD_FWD = [
    ("cargo_fwd",        500.0,  5.0,  0.0, 0.8),
    ("pax_fwd",         1173.0,  7.5,  0.0, 1.5),
    ("pax_mid",         1327.0,  9.5,  0.0, 1.5),
    ("cargo_aft",        480.0, 11.0,  0.0, 0.8),
]

PAYLOAD_AFT = [
    ("cargo_fwd",         50.0,  5.0,  0.0, 0.8),
    ("pax_fwd",          171.0,  7.5,  0.0, 1.5),
    ("pax_mid",         2159.0,  9.5,  0.0, 1.5),
    ("cargo_aft",       1100.0, 11.0,  0.0, 0.8),
]


def write_bdf(path: Path, payload_points, title: str, target_cg_m: float):
    """NASTRAN bulk-data file, free-field, imperial units (ft, slug)."""
    lines = []
    lines.append(f"$ {title}")
    lines.append(f"$ target CG x = {target_cg_m:.3f} m (per condition CSV)")
    lines.append("$ generated by data/generate_d328_model.py")
    lines.append("$ units on disk: feet (length), slug (mass) — SI internally")
    lines.append("$")
    lines.append("BEGIN BULK")

    all_points = STRUCT_POINTS + payload_points
    total_m = 0.0
    sum_mx = 0.0
    sum_my = 0.0
    sum_mz = 0.0
    for i, (name, m_kg, x_m, y_m, z_m) in enumerate(all_points, start=1):
        gid = i
        eid = 1000 + i
        x_ft = x_m * M_FT
        y_ft = y_m * M_FT
        z_ft = z_m * M_FT
        m_slug = m_kg * KG_SLUG
        total_m += m_kg
        sum_mx += m_kg * x_m
        sum_my += m_kg * y_m
        sum_mz += m_kg * z_m
        lines.append(f"$ {name}: m={m_kg:.2f} kg  pos=({x_m:.3f},{y_m:.3f},{z_m:.3f}) m")
        lines.append(f"GRID,{gid},0,{x_ft:.6f},{y_ft:.6f},{z_ft:.6f}")
        lines.append(f"CONM2,{eid},{gid},0,{m_slug:.6f},0.0,0.0,0.0")

    lines.append("ENDDATA")
    path.write_text("\n".join(lines) + "\n")

    return {
        "total_mass_kg": total_m,
        "x_cg_m": sum_mx / total_m,
        "y_cg_m": sum_my / total_m,
        "z_cg_m": sum_mz / total_m,
    }


# ============================================================
# Condition CSVs
# ============================================================

def write_sfl_csv(path: Path):
    rows = [
        "condition_id,description,category,maneuver_type,h_m,v_eas_m_s,m_ac_kg,x_cg_nd,nz_nd,elevator_deg,aileron_deg,rudder_deg,fos_nd",
        # Cruise envelope corners
        "C001,Cruise pull-up 2.5g fwd CG FL200,maneuver,symmetric_pullup,6096,138.9,12400,0.15,2.5,0,0,0,1.5",
        "C002,Cruise pushover -1g fwd CG FL200,maneuver,pushover,6096,138.9,12400,0.15,-1.0,0,0,0,1.5",
        "C003,Dive pull-up V_D 2.5g aft CG SL,maneuver,symmetric_pullup,0,185.2,12400,0.35,2.5,0,0,0,1.5",
        "C004,Maneuver speed pull-up V_A aft CG SL,maneuver,symmetric_pullup,0,84.9,12400,0.35,2.5,0,0,0,1.5",
        "C005,Cruise pull-up 2.5g aft CG FL250,maneuver,symmetric_pullup,7620,138.9,12400,0.35,2.5,0,0,0,1.5",
        # Unrealisable: 5g pull-up — must fail trim (used to test ValueError path)
        "C006,UNREALISABLE 5g pull-up (CL_required > CL_max),maneuver,symmetric_pullup,6096,138.9,12400,0.15,5.0,0,0,0,1.5",
    ]
    path.write_text("\n".join(rows) + "\n")


def write_dfl_csv(path: Path):
    # Static-equivalent gust velocity (EAS) per pre-Amendment-25-86 FAR App G:
    #   50 fps EAS (15.24 m/s) at SL → 25 fps EAS (7.62 m/s) at 20,000 ft (6096 m).
    #   Linear interpolation in altitude.
    rows = [
        "condition_id,description,category,maneuver_type,h_m,v_eas_m_s,m_ac_kg,x_cg_nd,nz_nd,u_gust_m_s,fos_nd",
        "G001,Discrete vertical gust SL V_C,gust,discrete_gust_vertical,0,138.9,12400,0.15,1.0,15.24,1.5",
        "G002,Discrete vertical gust FL100 V_C,gust,discrete_gust_vertical,3048,138.9,12400,0.15,1.0,11.43,1.5",
        "G003,Discrete vertical gust FL200 V_C,gust,discrete_gust_vertical,6096,138.9,12400,0.15,1.0,7.62,1.5",
        "G004,Continuous turbulence FL200 V_C aft CG,gust,continuous_turbulence,6096,138.9,12400,0.35,1.0,0.0,1.5",
    ]
    path.write_text("\n".join(rows) + "\n")


# ============================================================
# CSV writer
# ============================================================

def write_csv(path: Path, header: list, rows: list):
    out = [",".join(header)]
    for r in rows:
        out.append(",".join(f"{v:.6f}" if isinstance(v, float) else str(v) for v in r))
    path.write_text("\n".join(out) + "\n")


# ============================================================
# Main
# ============================================================

def main():
    print(f"Generating Do 328-class model data in {DATA_ROOT}")

    LRA_DIR.mkdir(parents=True, exist_ok=True)
    AERO_DIR.mkdir(parents=True, exist_ok=True)
    MASS_DIR.mkdir(parents=True, exist_ok=True)
    (COND_DIR / "static_flight").mkdir(parents=True, exist_ok=True)
    (COND_DIR / "dynamic_flight").mkdir(parents=True, exist_ok=True)

    # LRAs
    for surf, fn in [("wing", gen_wing_lra), ("htail", gen_htail_lra),
                     ("vtail", gen_vtail_lra), ("fuselage", gen_fuselage_lra)]:
        p = LRA_DIR / f"lra_{surf}.json"
        p.write_text(json.dumps(fn(), indent=2) + "\n")
        print(f"  wrote {p.relative_to(DATA_ROOT.parent)}")

    # Baseline aero
    base_header = ["y_m", "c_m", "alpha_deg", "beta_deg", "mach_nd",
                   "cn_sec_nd", "cm_sec_nd", "cc_sec_nd"]
    for surf, fn in [("wing", gen_wing_aero), ("htail", gen_htail_aero),
                     ("vtail", gen_vtail_aero), ("fuselage", gen_fuselage_aero)]:
        p = AERO_DIR / f"aero_{surf}_power_on_flaps_0.csv"
        write_csv(p, base_header, fn())
        print(f"  wrote {p.relative_to(DATA_ROOT.parent)}  ({sum(1 for _ in p.open())-1} rows)")

    # Increments
    incr_header = ["y_m", "alpha_deg", "beta_deg", "mach_nd", "deflection_deg",
                   "delta_cn_sec_nd", "delta_cm_sec_nd", "delta_cc_sec_nd"]
    for name, fn in [("htail_elevator", gen_elevator_incr),
                     ("wing_aileron",   gen_aileron_incr),
                     ("vtail_rudder",   gen_rudder_incr)]:
        p = AERO_DIR / f"aero_incr_{name}.csv"
        write_csv(p, incr_header, fn())
        print(f"  wrote {p.relative_to(DATA_ROOT.parent)}  ({sum(1 for _ in p.open())-1} rows)")

    # Mass BDFs
    fwd_info = write_bdf(MASS_DIR / "mass_d328_mzfw_fwd.bdf", PAYLOAD_FWD,
                         "Do 328-class MZFW forward CG (target 15% MAC)",
                         X_CG_FWD_M)
    aft_info = write_bdf(MASS_DIR / "mass_d328_mzfw_aft.bdf", PAYLOAD_AFT,
                         "Do 328-class MZFW aft CG (target 35% MAC)",
                         X_CG_AFT_M)
    print(f"  wrote data/mass/mass_d328_mzfw_fwd.bdf  "
          f"m={fwd_info['total_mass_kg']:.1f} kg  CG=({fwd_info['x_cg_m']:.3f},"
          f"{fwd_info['y_cg_m']:.3f},{fwd_info['z_cg_m']:.3f}) m")
    print(f"  wrote data/mass/mass_d328_mzfw_aft.bdf  "
          f"m={aft_info['total_mass_kg']:.1f} kg  CG=({aft_info['x_cg_m']:.3f},"
          f"{aft_info['y_cg_m']:.3f},{aft_info['z_cg_m']:.3f}) m")

    # Conditions
    write_sfl_csv(COND_DIR / "static_flight"  / "sfl_sample.csv")
    write_dfl_csv(COND_DIR / "dynamic_flight" / "dfl_gust_sample.csv")
    print("  wrote data/conditions/static_flight/sfl_sample.csv")
    print("  wrote data/conditions/dynamic_flight/dfl_gust_sample.csv")

    # data_summary.json
    summary = {
        "aircraft_id": AIRCRAFT_ID,
        "aircraft_description": "Simplified Dornier 328-class regional turboprop",
        "data_source": "Synthetic — elliptical lift + slender body fuselage; NOT regulatory credible",
        "generator_script": "data/generate_d328_model.py",
        "analyst": "auto-generated",
        "analysis_intent": "test/development model for WBT_LOADS flight-loads pipeline",
        "reference_geometry": {
            "b_m": B_M,
            "s_ref_m2": S_REF_M2,
            "mac_m": MAC_M,
            "x_le_mac_m": X_LE_MAC_M,
            "ar_wing": round(AR_WING, 3),
            "cl_alpha_wing_per_rad": round(CL_ALPHA_WING_RAD, 4),
            "oew_kg": OEW_KG,
            "mzfw_kg": MZFW_KG,
        },
        "in_scope": [
            "Category A: static flight loads",
            "Category B: dynamic flight loads (discrete gust + 2-DOF PSD)",
        ],
        "out_of_scope": [
            "Category C: static ground loads",
            "Category D: dynamic ground loads",
            "Category E: flap / high-lift loads",
            "Category F: control surface design loads",
        ],
        "mass_cases": {
            "mzfw_fwd": {
                "file": "data/mass/mass_d328_mzfw_fwd.bdf",
                "total_mass_kg": round(fwd_info["total_mass_kg"], 2),
                "x_cg_m": round(fwd_info["x_cg_m"], 4),
                "x_cg_pct_mac": round(100 * (fwd_info["x_cg_m"] - X_LE_MAC_M) / MAC_M, 2),
            },
            "mzfw_aft": {
                "file": "data/mass/mass_d328_mzfw_aft.bdf",
                "total_mass_kg": round(aft_info["total_mass_kg"], 2),
                "x_cg_m": round(aft_info["x_cg_m"], 4),
                "x_cg_pct_mac": round(100 * (aft_info["x_cg_m"] - X_LE_MAC_M) / MAC_M, 2),
            },
        },
    }
    (DATA_ROOT / "data_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("  wrote data/data_summary.json")

    print("Done.")


if __name__ == "__main__":
    main()
