# viewer.md — Pre/Post-Processing Viewer

## Overview

The sbeam viewer is a **Streamlit** web application providing:
- Model display and interrogation (pre-processing)
- GPWG mass and CG summary
- Case control definition and BDF export
- Results display (post-processing)

The viewer is launched with:

```
streamlit run viewer/app.py
```

---

## Module Structure

```
viewer/
├── app.py              # Main Streamlit app; routing and session state
├── geometry.py         # 3D model display functions (Plotly)
├── results_view.py     # Results post-processing display
└── case_control_ui.py  # Case control form and BDF export
```

---

## Pre-Processing Pages

### 1. Model Load

The viewer accepts two file types via the file uploader (`*.bdf` or `*.dat`). File type is detected automatically by scanning for a `SOL` statement before the first `BEGIN BULK` line (`_has_case_control(content: str) -> bool` in `app.py`).

| File type | Parser called | Session state result |
|-----------|--------------|---------------------|
| Bulk-data file (no `SOL`) | `parse_bulk_file()` | `bulk_data` set; `case_control = None` |
| Run file (has `SOL`) | `parse_bdf()` | `bulk_data` and `case_control` both set |

**Parse summary (shown after upload):**
- Bulk-data load: grid count, CBAR count, material count, load sets, SPC sets; caption "No case control — define via Case Control tab."
- Run file load: SOL type, subcase count, grid count, CBAR count, load sets, SPC sets.
- Parser warnings (unrecognised cards) shown in an expandable section.

### 2. Model Display

Implemented in `geometry.py` using **Plotly** 3D scatter and line traces.

**Public API:**

```python
build_model_figure(bulk: BulkData) -> go.Figure
```

Builds a Plotly 3D figure from a parsed `BulkData` object. Contains no Streamlit imports — safe to call in unit tests.

**Trace strategy:**
- GRIDs: one `Scatter3d` with all nodes, `mode="markers+text"`.
- CBArs: one `Scatter3d` per PID (colour-coded), using `[x_A, x_B, None]` segment encoding. A second invisible midpoint-marker trace (`opacity=0`) carries per-element hover data (EID, PID, MID, A, I1, I2, J, L, PA, PB).
- PLOTELs: one `Scatter3d` with `line.dash="dash"` to distinguish from CBArs.
- Coordinate triad: three short line traces (X/Y/Z in R/G/B), length = max(10% bounding-box diagonal, 1.0).

**Display items:**
- GRID points: scatter markers labelled with GID.
- CBAR elements: line traces between GA and GB nodes. Colour-coded by property (PID).
- PLOTEL elements: dashed line traces (distinct colour/style from CBAR).
- Coordinate triad at origin.

**Interactions:**
- Hover on grid: show GID, X, Y, Z, and any permanent SPC constraints.
- Hover on CBAR: show EID, PID, MID, A, I1, I2, J, length, PA, PB.
- Hover on PBAR/MAT1: show cross-section and material properties.
- Click-to-select: highlight selected grid or element; show full card data in a side panel.
- Toggle visibility: grids, CBAR, PLOTEL, grid labels, element labels.

**Display controls:**
- Zoom, pan, rotate (Plotly default 3D controls).
- Reset view button.
- Element/grid label toggle.

### 3. Model Properties Panel

Tabbed panel showing:
- **Grids tab:** table of all GIDs, X, Y, Z, PS.
- **Elements tab:** table of all CBARs, EID, GA, GB, PID, length.
- **Properties tab:** table of all PBARs, PID, MID, A, I1, I2, J.
- **Materials tab:** table of all MAT1s, MID, E, G, nu, rho.
- **Loads tab:** table of FORCE and MOMENT cards per load set.
- **Constraints tab:** table of SPC constraints per set.

---

## GPWG — Mass and CG

Calls `gpwg.py` to compute:
- Total structural mass (from CBAR element distributed mass + CONM2 lumped masses).
- Centre of gravity (X_cg, Y_cg, Z_cg).

Displayed as a summary table in the viewer. No input required; computed directly from loaded `BulkData`.

---

## Case Control UI

Implemented in `case_control_ui.py`.

**Form fields:**

| Field | Input Type | Description |
|-------|-----------|-------------|
| SOL | Dropdown | 101 or 103 |
| TITLE | Text | Model title string |
| SUBCASE ID | Integer | Subcase number |
| Subcase label | Text | Optional label |
| LOAD | Dropdown | Select from available load set SIDs |
| SPC | Dropdown | Select from available SPC set SIDs |
| METHOD (SOL 103) | Dropdown | Select EIGRL SID |
| Output requests | Checkboxes | DISPLACEMENT, SPCFORCE, OLOAD, FORCE, STRESS |
| Include file path | Text | Path to bulk data `*.dat` file |

**Export button:** Generates and downloads a `*.bdf` case control file with:
```
SOL <sol>
CEND
TITLE = <title>
SUBCASE <id>
  LABEL = <label>
  LOAD = <sid>
  SPC = <sid>
  DISPLACEMENT(PRINT) = ALL
  ...
BEGIN BULK
INCLUDE '<bulk_data_file>'
ENDDATA
```

Multiple subcases can be defined and added to the list before export.

---

## Post-Processing Pages

### Results Load

- File uploader or automatic detection: accepts `*.f06` results file.
- Parses results into `Results` object; stores in session state.
- Displays available subcases and SOL type.

### SOL 101 — Deformed Shape Display

In `results_view.py`:

- Deformed shape overlay on undeformed geometry.
- Scale factor slider (default: auto-scaled to 10% of model bounding box).
- Deformed grid positions: `X_def = X_orig + scale * [Tx, Ty, Tz]`.
- PLOTEL elements deformed using interpolated displacements.
- Colour bar showing displacement magnitude.
- Toggle undeformed ghost model.

**Results tables (SOL 101):**
- Nodal displacements: GID, T1, T2, T3, R1, R2, R3.
- SPC reaction forces: GID, DOF, force value.
- CBAR end forces: EID, end A (F1, F2, F3, M1, M2, M3), end B.
- CBAR stresses: EID, point C, D, E, F (axial + bending).

### SOL 103 — Mode Shape Display

- Mode selector: dropdown or slider (mode 1 through ND).
- Frequency displayed for selected mode (Hz and rad/s).
- Animated mode shape: Plotly animation cycling through deformation from -max to +max.
- Scale factor slider.
- Modal mass fraction bar chart (per direction, per mode).

**Results table (SOL 103):**
- Mode summary: mode number, frequency (Hz), frequency (rad/s), generalised mass.
- Mode shape: GID, T1, T2, T3, R1, R2, R3.

---

## Session State

Streamlit session state keys used:

| Key | Type | Content |
|-----|------|---------|
| `bulk_data` | `BulkData` | Parsed model |
| `case_controls` | `list[SubcaseControl]` | Defined subcases |
| `sol101_results` | `Sol101Result` | SOL 101 results |
| `sol103_results` | `Sol103Result` | SOL 103 results |
| `selected_gid` | `int \| None` | Currently selected grid |
| `selected_eid` | `int \| None` | Currently selected element |
| `deform_scale` | `float` | Deformed shape scale factor |
| `active_mode` | `int` | Selected mode number (SOL 103) |

---

## Run Analysis from Viewer

A **Run Analysis** button in the viewer can:
1. Validate that a model is loaded and case control is defined.
2. Call `solver/sol101.py` or `solver/sol103.py` directly (in-process).
3. Display results immediately without requiring a separate CLI run.
4. Optionally write the `.f06` output file.

This avoids requiring the user to use the CLI for typical interactive workflows.

---

## Error Display

- Parse errors and warnings are shown as Streamlit warning/error banners.
- Solver errors (singular matrix, etc.) are shown with the error message in a red banner.
- Skipped BDF cards are listed in an expandable "Warnings" section.
