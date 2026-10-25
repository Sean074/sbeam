# Loads Aerodynamic Database — Format and Methods

This document is the authoritative standard for the aerodynamic strip load
database consumed by `src/aero_db.py`. It defines the CSV file format, column
schema, interpolation method, and Mach extrapolation policy.

All other documents (`doc/analysis_code.md`, `doc/architecture.md`) defer to
this document for aero database specifics.

---

## Purpose

The aerodynamic database provides strip load coefficients
(`cn_sec_nd`, `cm_sec_nd`, `cc_sec_nd`) as a function of flight state at each
spanwise station on each lifting surface. These are the primary aerodynamic
inputs to the loads summation (`loads.py`) and trim solver (`trim.py`).

Surfaces covered: wing, horizontal stabiliser, vertical stabiliser, fuselage.

---

## Database structure — two tiers

The database is organised as two types of CSV files per lifting surface:

| Tier | Purpose | File naming |
|---|---|---|
| **Baseline** | Full strip coefficients at a given aerodynamic configuration (power state × flap setting) | `aero_<surface>_<config_tag>.csv` |
| **Increment** | Delta coefficients for a control surface deflection | `aero_incr_<surface>_<control>.csv` |

`aero_db.py` reads one baseline file for the active configuration, then adds
any applicable increment files. Total strip coefficients at each station are:

```
cn_sec_nd_total = cn_sec_nd_baseline + Σ delta_cn_sec_nd_i
cm_sec_nd_total = cm_sec_nd_baseline + Σ delta_cm_sec_nd_i
cc_sec_nd_total = cc_sec_nd_baseline + Σ delta_cc_sec_nd_i
```

---

## Baseline table format

### Columns

| Column | Variable | Units | Notes |
|---|---|---|---|
| Spanwise station | `y_m` | metres | Along the surface LRA |
| Local chord | `c_m` | metres | At this strip station |
| Angle of attack | `alpha_deg` | degrees | Converted to `alpha_rad` at ingestion |
| Sideslip angle | `beta_deg` | degrees | Converted to `beta_rad` at ingestion |
| Mach number | `mach_nd` | dimensionless | From CFD or wind-tunnel data |
| Normal force coefficient | `cn_sec_nd` | dimensionless | Section body-normal axis |
| Pitching moment coefficient | `cm_sec_nd` | dimensionless | Referenced to local 25% chord (c/4) |
| Chordwise force coefficient | `cc_sec_nd` | dimensionless | Section body-chord axis |

### File naming

```
aero_<surface>_<config_tag>.csv
```

`<surface>` — one of: `wing`, `htail`, `vtail`, `fuselage`

`<config_tag>` — underscore-separated description of the configuration state:
`power_on_flaps_0`, `power_on_flaps_10`, `power_off_flaps_0`, etc.

Example: `aero_wing_power_on_flaps_0.csv`

### Data requirements

- All geometry in SI (metres). No feet.
- All coefficients are dimensionless strip values **corrected to jig shape**.
- Data sourced from CFD runs or wind-tunnel tests. The alpha and beta ranges
  must fully bracket the condition list flight envelope.
- `c_m` values are repeated across all alpha/beta/Mach rows for a given
  spanwise station (chord does not vary with flight state).

---

## Increment table format

### Columns

| Column | Variable | Units | Notes |
|---|---|---|---|
| Spanwise station | `y_m` | metres | |
| Angle of attack | `alpha_deg` | degrees | |
| Sideslip angle | `beta_deg` | degrees | |
| Mach number | `mach_nd` | dimensionless | |
| Control deflection | `deflection_deg` | degrees | Positive trailing-edge down |
| Delta Cn | `delta_cn_sec_nd` | dimensionless | Increment on baseline |
| Delta Cm | `delta_cm_sec_nd` | dimensionless | Increment on baseline |
| Delta Cc | `delta_cc_sec_nd` | dimensionless | Increment on baseline |

### File naming

```
aero_incr_<surface>_<control>.csv
```

`<surface>` — the surface that carries the control (e.g. `wing`, `htail`, `vtail`)

`<control>` — one of: `aileron`, `spoiler`, `elevator`, `rudder`, `flap`

Example: `aero_incr_wing_aileron.csv`

---

## Interpolation method

`aero_db.py` builds a 4-D interpolant over the independent variables:

```
(y_m, alpha_deg, beta_deg, mach_nd)
```

Implementation: `scipy.interpolate.RegularGridInterpolator` with
`method='linear'`, using the structured grid of the CSV data after pivoting
into a regular array.

The interpolation is performed in degrees for alpha and beta (as stored in
the file). Calling modules pass `alpha_rad` and `beta_rad`; `aero_db.py`
converts these to degrees via `unit_convert.RAD_DEG` before the lookup.

Rate increments (pitch `q_pitch_rad_s`, roll `p_roll_rad_s`, yaw `r_yaw_rad_s`)
are applied as linear per-unit-rate multipliers. Their table format is defined
in a separate section pending decision.md §11.

---

## Mach extrapolation fallback

When a requested Mach falls **outside** the range of tabulated data,
`aero_db.py` applies the Prandtl-Glauert correction to extend from the nearest
table edge:

```
cn_extrap = cn_edge / sqrt(1 - mach_nd²)
```

This fallback **must** emit a yellow TUI warning before returning:

```
[yellow]Warning: Mach {mach_nd:.3f} outside aero database range
[{mach_min:.2f} – {mach_max:.2f}]. Prandtl-Glauert extrapolation applied.[/yellow]
```

Prandtl-Glauert is **not** applied within the table range — interpolation
uses the CFD/test data directly.

---

## Coefficient sign and reference conventions

- `cn_sec_nd` — positive in the direction of positive surface normal (upward
  for the wing under positive lift).
- `cm_sec_nd` — positive nose-up; referenced to the local 25% chord point
  (c/4). `aero_db.py` transfers Cm to the LRA station before returning values
  to `loads.py`.
- `cc_sec_nd` — positive toward the trailing edge.

---

## Sample data (BAe 146-sized aircraft)

A synthetic baseline dataset consistent with the project LRA geometry is
provided in `data/aero/`. It is generated by
`data/aero/generate_sample_aero.py` using 2-D strip theory with
Prandtl-Glauert compressibility correction.

| File | Surface | Rows |
|---|---|---|
| `aero_wing_power_on_flaps_0.csv` | Wing | 3 800 |
| `aero_htail_power_on_flaps_0.csv` | Horizontal tail | 2 200 |
| `aero_vtail_power_on_flaps_0.csv` | Vertical tail | 1 200 |
| `aero_fuselage_power_on_flaps_0.csv` | Fuselage | 2 200 |
| `aero_incr_htail_elevator.csv` | Elevator increment | 11 000 |

Parameter grid: alpha [-6, -3, 0, 3, 6, 9, 12, 15]°, beta [-10, -5, 0, 5, 10]°,
Mach [0.30, 0.50, 0.65, 0.72, 0.80].

**Vtail note:** because all vtail LRA stations share structural y = 0, the
`y_m` column in the vtail baseline file holds the *local surface span
coordinate* (0–4.90 m from vtail root), not the structural y.

**Fuselage note:** the `y_m` column holds the *structural x position*
(fuselage longitudinal station, 2.0–27.0 m), which is the fuselage LRA axis.

These files are synthetic and intended for development and testing only. They
should be replaced with CFD or wind-tunnel data before any regulatory
submission.
