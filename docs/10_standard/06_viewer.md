# Viewer — Pre/Post-Processing

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
├── case_control_ui.py  # Case control form and BDF export
├── aero_view.py        # Aero box mesh + cp colour map (S44); spline-deflected box overlay (S57); per-surface span-loading figure + rigid S&C derivative table (A-GUI2); cp corrected/uncorrected/Δ views + dihedral helper (A-GUI4); corrected/uncorrected/Δ rigid-derivative table (A-GUI5); body-panel colour/legend split (AC5)
├── aero_correction_view.py  # Aero Correction tab: CFD/test section data → W2GJ+AECORR(WT2) cards, injected into the model + full corrected-BDF export (A-GUI3/A-GUI4); Stage 6 = cruciform body-panel total-moment match (A9)
└── format_utils.py     # Shared 5-sig-fig number formatting for tables/metrics (fmt / fmt_mass / style_numeric) (A-GUI4)
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
- Bulk-data load: grid count, CBAR count, RBE3 count, RBE2 count, CONM2 count, material count, load sets, SPC sets; caption "No case control — define via Case Control tab."
- Run file load: SOL type, subcase count, grid count, CBAR count, RBE3 count, RBE2 count, CONM2 count, load sets, SPC sets.
- Parser warnings (unrecognised cards) shown in an expandable section.

### 2. Model Display

Implemented in `geometry.py` using **Plotly** 3D scatter and line traces.

**Public API:**

```python
build_model_figure(bulk: BulkData, selected_gid=None, selected_eid=None, load_sid=None) -> go.Figure
build_deformed_figure(bulk, displacements, grid_index, scale=1.0, load_sid=None) -> go.Figure
build_mode_figure(bulk, mode_shape, grid_index, scale=1.0, freq_hz=0.0, camera=None, height=600, phase=0.25) -> go.Figure
```

Builds Plotly 3D figures from BulkData. Contains no Streamlit imports — safe to call in unit tests.

- `build_model_figure`: original (undeformed) model. `selected_gid` / `selected_eid` highlight the item in orange. Optional `load_sid` renders force/moment arrows.
- `build_deformed_figure`: undeformed ghost (grey, semi-transparent) + deformed overlay for SOL 101 results. Ghost includes CBAR, PLOTEL (grey dashed), RBE3 (red dashed), RBE2 (red solid, opacity 0.5), CBUSH (zigzag grey), and RBAR (solid grey). Deformed overlay includes CBAR lines (orange), grid nodes, PLOTEL (grey dashed), RBE3 (red dashed), RBE2 (red solid), and RBAR — all displaced with the solution. Optional `load_sid` renders force/moment arrows.
- `build_mode_figure`: undeformed ghost (CBAR grey, PLOTEL grey dashed, RBE3 red dashed, RBE2 red solid, CBUSH zigzag grey, RBAR solid grey, all semi-transparent) + static mode shape for SOL 103. `phase` (0.0–1.0) controls amplitude as `scale * sin(2π × phase)` — 0.25 = +max, 0.75 = −max. Optional `camera` (Plotly camera dict) sets the initial view orientation. Optional `height` (px) sets the chart height. Scene axis ranges are locked to the ±`scale` amplitude extent with 15% padding via `autorange=False` so the view does not shift as the user scrubs the phase slider.

**Trace strategy:**
- GRIDs: split across two legend-visible `Scatter3d` traces. `"GRIDs"` (unconstrained): solid dark grey `#333333`, size 6. `"GRIDs (SPC)"` (constrained by any SPC/SPC1/Grid.ps): red fill `#cc2222` with grey outline `#888888` width 2, size 12, label includes DOF string (e.g. `G1\n123456`). Selected GRID: separate `showlegend=False` trace, orange `#ff8800`, size 10.
- CBArs: one `Scatter3d` per PID (colour-coded), using `[x_A, x_B, None]` segment encoding. A second invisible midpoint-marker trace (`opacity=0`) carries per-element hover data (EID, PID, MID, A, I1, I2, J, L, PA, PB). Selected EID gets an additional trace in orange at width 8.
- PLOTELs: one `Scatter3d` with `line.dash="dash"` to distinguish from CBArs.
- RBE3s: one `Scatter3d` with `line.color="#cc2222"` (red) and `line.dash="dash"`. One segment per (refgrid → independent grid) connection across all `wt_gc` groups. `hoverinfo="skip"`.
- RBE2s: one `Scatter3d` with `line.color="#cc2222"` (red), solid (no dash). One segment per (GN → GM) connection. `hoverinfo="skip"`. Solid style distinguishes from RBE3 dashed.
- CONM2s: one `Scatter3d` marker trace per CONM2, plotted at the centre of gravity location. Style: open white circle, `marker.symbol="circle-open"`, `marker.color="white"`, `marker.line.color="#333333"` (dark grey outline), `marker.line.width=2`, `marker.size=14` (larger than both unconstrained GRID size 6 and SPC size 12). When the CONM2 has a non-zero offset (`X2` field), the CG is at `grid_position + offset`; an additional `Scatter3d` line segment traces from the grid reference point to the offset CG location, `line.color="#333333"`, `line.width=1`, `hoverinfo="skip"`. Hover text shows: `CONM2 EID\nGID, Mass`. Legend entry: `"CONM2"`.
- Coordinate triad: three short line traces (X/Y/Z in R/G/B), length = max(10% bounding-box diagonal, 1.0).
- Load arrows (`load_sid` provided): one `go.Cone` trace for FORCE loads (green `#22aa44`) and one for MOMENT loads (blue `#3366cc`), both `showlegend=False`. Arrow vectors are the actual force/moment vectors; `sizeref = max_magnitude / (0.15 × model_span)` so the largest arrow spans ~15% of the model. LOAD combination cards are expanded recursively.

**Display items:**
- GRID points: scatter markers labelled with GID; constrained nodes shown in red with DOF string.
- CBAR elements: line traces between GA and GB nodes. Colour-coded by property (PID).
- PLOTEL elements: dashed line traces (distinct colour/style from CBAR).
- RBE3 elements: dashed red line traces from the dependent (reference) grid to each independent grid.
- CONM2 masses: open white circle at the CG location; offset line from grid reference to CG when a non-zero offset is defined.
- Coordinate triad at origin.
- Force/moment arrows (when active subcase has a load set).

**Scene layout (`_apply_layout`):**
All three figure types use `_apply_layout`, which sets `scene.aspectmode = "data"` (preserves physical proportions) and `scene.camera.projection.type = "orthographic"` (eliminates perspective foreshortening). Mode shape figures additionally receive explicit locked axis ranges via `autorange=False`.

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
- **Show applied forces** checkbox: hides/shows force and moment arrow traces. Defaults to on. When unchecked, `load_sid=None` is passed so no cone traces are added.

### 3. Model Properties Panel

Tabbed panel showing:
- **Grids tab:** table of all GIDs, X, Y, Z, PS.
- **Elements tab:** table of all CBARs (EID, GA, GB, PID, length, PA, PB); followed by an RBE3 sub-table (EID, RefGrid, RefDOFs, Num Indep. Grids) shown only when RBE3 elements are present; followed by an RBE2 sub-table (EID, GN (indep), CM (DOFs), Num Dep. Grids) shown only when RBE2 elements are present; followed by a CONM2 sub-table (EID, GID, Mass, X1, X2, X3) shown only when CONM2 entries are present.
- **Properties tab:** table of all PBARs, PID, MID, A, I1, I2, J.
- **Materials tab:** table of all MAT1s, MID, E, G, nu, rho.
- **Loads tab:** table of FORCE and MOMENT cards per load set.
- **Constraints tab:** table of SPC constraints per set.

### 4. Aero Tab (S44)

Present only when `bulk.caero1s` is non-empty. Renders aerodynamic mesh visualisation and
a rigid steady-state solve at a user-specified angle of attack.

**Controls (left column):**
- **AoA α (°)** / **Sideslip β (°)** — `st.number_input`, defaults 3° / 0°, step 0.5°.
- **Compute Aero** — builds `AeroModel` (AIC matrix) and calls
  `solve_rigid_cl(..., wg=aero_model.wg, cp_operator=aero_model.ajj_inv_corr)` (the **corrected**
  solve, stored in `aero_result`). When the deck carries a correction card (`bulk.wkks` or
  `bulk.aecorrs`) it *also* runs the **uncorrected** baseline
  `solve_rigid_cl(..., cp_operator=None, mach=aero_model.mach)` (same `wg`, raw VLM + Prandtl–Glauert)
  and stores it in `aero_result_unc` for the span-load overlay. The corrected solve reflects both
  the W2GJ baseline incidence (camber/twist/built-in incidence) **and** any AIC correction
  (WKK / WT1 / WT2) in CL/CM/cp/section loads — matching the SOL 144 path. Positive `wg` reduces
  lift (SOL 144 sign). Captions flag an active `wg` and/or correction method.
- **Show surface normals** — `st.checkbox` (`key="aero_show_normals"`, default off). When
  ticked, draws each box's outward unit normal (`AeroBox.normal`) as a green arrow rooted
  at its collocation point. Re-renders the cached `aero_model` instantly (no AIC recompute).
- **Cp view** — `st.radio` (`key="aero_cp_view"`), shown only when an uncorrected baseline
  exists (`aero_result_unc`). Selects **Corrected** / **Uncorrected** / **Δ (corr − uncorr)** and
  drives *both* the 3D box-pressure mesh and the span-load curves. Δ subtracts the two cp fields
  per box and renders the 3D mesh with a zero-centred diverging scale (`cp_cmid=0`, colour-bar
  **ΔCp**).
- After compute: **CL (wind)**, **CD (induced)**, **CZ (body)**, **CY**, **CM**, and **Boxes**
  count displayed as `st.metric` (5-sig-fig `format_utils.fmt`). CL/CD are wind-axis (⊥ / ∥ to U∞); CZ is the body-axis
  vertical-force coefficient, `CL = CZ·cosα − CX·sinα` (equal only at α ≈ 0); CD is the Trefftz
  induced drag (`CDi`). A caption restates the axis convention.

**3D figure (right column):** built by `build_aero_box_figure(..., strip=False, cp_cmid=…, cp_title=…)`
— a scene-only mesh: `_add_box_mesh` (Scatter3d wire-frame) + `_add_cp_contour` (Mesh3d quads,
`RdBu_r`) + optional `_add_normal_vectors`. The cp field shown follows the **Cp view** toggle
(corrected / uncorrected / Δcp); for Δcp the contour passes `cmid=0` for a symmetric scale and the
**ΔCp** colour-bar title. The `strip=True` default (used by the SOL 144 results view) keeps the
legacy bottom xy panel; the Aero tab passes `strip=False` because span loading has its own
full-width figure below.

**Body-panel colouring (AC5):** `build_aero_box_figure(..., body_eids=set[int] | None)` splits the
grey wire-frame into an **Aero mesh** trace and a purple (`#9467bd`) **Body panels** trace (own
legend entry; the deflected copy is light purple `#c5b0d5`). A box counts as a body box when
`AeroBox.is_strip` is set (PSTRIP decoupled strip bodies — automatic, no argument needed) **or**
its `caero_eid` is in `body_eids`. Cruciform body panels are plain CAERO1/PAERO1 boxes with no
per-box marker, so their EIDs are remembered in `st.session_state.aero_body_eids` when the Aero
Correction tab's **Build body correction** succeeds; the Aero tab and the SOL 144 deflected view
pass that set through. Before a body correction is built in the session, only strip bodies are
highlighted.

**Full-width results (below the columns), shown after a Compute:**
- **Spanwise loading** — `build_span_loading_figure(boxes, cp_corr, cp_unc=..., aeros=..., mode=…)`:
  two stacked subplots, **one line per CAERO1 surface** — section normal-force coefficient `cn(η)`
  and section pitching-moment coefficient `cm(η)` about each strip's **local ¼-chord** (nose-up +ve).
  Boxes are grouped by `(caero_eid, i_span)` so multi-surface decks no longer merge strips that
  share an `i_span`. `mode` follows the **Cp view** toggle: *corrected* draws corrected solid +
  uncorrected dashed (when present); *uncorrected* draws the baseline solid; *diff* draws the
  per-strip Δcn/Δcm. Hover/tick values use 5-sig-fig (`.5~g`) formatting. A **Show surfaces**
  `st.multiselect` (`key="aero_span_surfaces"`, default all, shown only for >1 surface) thins a busy
  multi-surface plot to a chosen subset via `build_span_loading_figure(..., surfaces=)`; each surface
  keeps a fixed colour (assigned from the full surface set) so hiding one does not recolour the rest.
  Deselecting all shows an info prompt instead of an empty chart.
- **Rigid stability & control derivatives** — `rigid_derivative_table(aero_model, bulk, naming,
  state)` rendered full-width via `st.dataframe`. Reuses the SOL 144 machinery (`build_djx` +
  `compute_rigid_derivs`, rigid `u_a = 0`) so the matrix matches the f06 rigid derivatives. Rows
  are α, β, roll p, pitch q, yaw r + every AESURF control; columns are the six force/moment
  coefficients per radian/label (conventional aero symbols CZ, CY, Cl, Cm, Cn, CX). The
  vertical-force column is body-axis `CZ` — not wind-axis `CL` (which equals `CZ` only at α≈0).
  A **Values** radio (`key="aero_deriv_state"`) selects the AIC operator the derivatives are
  integrated against: **Corrected** (the corrected ΔCp operator, default), **Uncorrected** (the
  raw VLM baseline at the same Mach, via `_uncorrected_cp_operator` — inverts the stored raw
  `aero_model.ajj` with the Göthert 1/β + Γ→ΔCp 2/chord scaling, swapped in through
  `dataclasses.replace`), or **Δ (corr − uncorr)**. The radio appears only when an uncorrected
  baseline exists (a correction card is present); otherwise the corrected table shows alone.
  (`naming="raw"` for the SOL 144 names ANGLEA/CMY… remains available programmatically for f06
  cross-checks but is no longer surfaced as a UI toggle.) Hidden when no AEROS card is present.
- **Per-surface coefficients (body axis)** — the multi-surface CZ/CY/CM breakdown table (when
  >1 surface). Per-surface contributions are body-axis (so they sum to the body-axis totals);
  the whole-aircraft wind-axis `CL` is the rotated total shown in the metrics above.

**Session state keys:**
| Key | Type | Description |
|-----|------|-------------|
| `aero_model` | `AeroModel \| None` | Built by `build_aero_model(bulk)` |
| `aero_result` | `dict \| None` | Corrected `{cp, cl_section, CL≡CZ, CX, CL_wind, CD_wind, CY, CM, per_surface, …}` from `solve_rigid_cl` |
| `aero_result_unc` | `dict \| None` | Uncorrected baseline solve (only when a correction card is present), else `None` |

All three keys are reset to `None` on new file upload (same pattern as `sol101_result`).

### 5. Aero Correction Tab (A-GUI3 / A-GUI4)

Present only when `bulk.caero1s` is non-empty (the tab immediately right of **Aero**).
Implemented in `aero_correction_view.py` (`render_aero_correction_tab(bulk)`); a front end over
`sbeam.aero.section_data` / `section_correction` that turns a table of **experimental / CFD section
coefficients** into **W2GJ + AECORR(WT2)** correction cards for one flight **condition** (Mach +
operating α and β) and injects them into the in-session model so the **Aero** tab runs the corrected
solve, and/or exports a self-contained corrected BDF.

**Workflow (top to bottom):**
1. **Section-data table** — **Download section-data template (CSV)** (`_template_csv`, one row per
   span strip of every CAERO1, flat-plate defaults) and an expander documenting the schema, then an
   **Upload section-data CSV** `st.file_uploader`. Uploads are run through
   `section_data.validate_section_data` (errors shown inline) and stored in `aero_corr_df`. The
   loaded table is echoed via `st.dataframe`. The tidy schema is
   `caero, eta, mach, var, a_lo, a_hi, cn_a, a0, cm_a, cm0, xref` — local-chord-normalised
   coefficients, slopes **per degree**, moment **nose-up +**.
2. **Blocks in the table** — `available_conditions(df)` listed as a table (CAERO × Mach × region).
3. **Build condition** — a **Mach** selectbox plus **two** operating-angle inputs, **Operating α (°)**
   and **Operating β (°)** (they can differ). Each surface is corrected on **one** axis chosen by its
   table `var`: an ALPHA surface uses α, a BETA surface uses β (`section_data.surface_var`). A
   per-surface status table shows `var`, the axis, the operating value, the resolved `[a_lo, a_hi]`
   region (`operating_region`, or ✗ none), and the surface dihedral **Γ** (`aero_view.surface_dihedral_deg`,
   length-weighted |Γ|). A **canted-surface warning** fires for any surface with `20° ≤ Γ ≤ 70°` —
   there a single-axis section correction blends both α and β responses. **Build correction cards**
   calls `build_from_section_data_multi(boxes, build_aero_model(bulk, mach=mach).ajj, df,
   alpha_deg=…, beta_deg=…, …)` at reserved SID bases (`_W2GJ_BASE = 9001`, `_AECORR_BASE = 9101`),
   storing the result in `aero_corr_result` and the condition in `aero_corr_cond`. Surfaces with a
   `MIXED` var (both axes in one table) or no region covering their angle are skipped.
4. **Generated cards** — extrapolation / skipped-surface warnings, a per-surface input-vs-achieved
   preview (`aero_view.build_section_correction_figure`) selected by a **Preview surface** box (the
   chart carries a stable `key` and the upload is re-parsed only on change, so switching surfaces no
   longer wipes the build), and a 5-sig-fig per-strip achieved-targets `st.dataframe`
   (`moment_ref_x, f_slope, m_slope, f0, m0`).
5. **Apply / export** — **Apply to model** (`_apply_cards`) injects each `(W2gj, Aecorr)` into
   `bulk.w2gjs` / `bulk.aecorrs`, **clearing any cards this tool injected on a prior build** (tracked
   in `aero_corr_sids`) so re-applies replace rather than stack, then nulls `aero_model` /
   `aero_result` / `aero_result_unc` so the Aero tab recomputes. `_warn_conflicts` flags a
   pre-existing **WKK** on a corrected surface (WKK precedence in `build_aero_model` shadows WT2) or a
   non-generated WT2 on the same surface. **Download cards (.bdf)** emits the bulk-data snippet via
   `section_correction.cards_to_bdf`. **Full corrected BDF** (`build_corrected_bdf`) splices those
   cards into the originally uploaded model text (before `ENDDATA`) with a provenance header (source
   CSV, date, Mach/α/β, corrected CAEROs) — a self-contained, re-parseable model. The filename input
   defaults to `suggest_corrected_name` (`<stem>_M0p30_A2p0_B0p0.bdf`); build one per Mach. A
   separate-correction-file + `INCLUDE` layout is *not* used because sbeam's parser honours only a
   single whole-bulk INCLUDE (`bdf_reader.parse_bdf`).
6. **Body panels — total-aircraft moment match (Step A9)** — shown only when the model has a
   plausible body panel (`_guess_body_panels` finds the largest-chord +Z / +Y surfaces — the
   fuselage cruciform). After the flying surfaces are matched (step 5), the body panels absorb the
   residual so the **total** airplane Cm/Cn/Cl match CFD/WT. Two **multiselects** pick the horizontal
   (Cm) and vertical (Cn, Cl) body panels — a plane may be **one panel or several** (e.g. a fuselage
   side split into pieces; they are tuned jointly), pre-set to the guesses and either may be left
   empty; six **target inputs** (Cm_α/Cm0 pitch, Cn_β/Cn0 yaw, Cl_β/Cl0 roll) seed from the CSV `TOTAL` block
   (`body_correction.parse_body_targets`; the block is split off the upload before validation by
   `split_total_rows`). **Build body correction** runs `build_body_correction(bulk + flying cards,
   …, aero=…)` and shows a baseline / target / achieved / residual `st.dataframe` plus the **max body
   WT2 ratio** (a *conditioning* gauge, not a contamination metric — WT2 scales body boxes only;
   warned past `RATIO_WARN`=200, the point where targets exceed a flat-plate cruciform and a
   slender-body element is needed, or if it could not converge). **Apply body
   panels to model** (`_apply_body_cards`) injects the flying pairs (idempotent) and the body
   `(W2gj, Aecorr)` pairs at reserved SIDs (`_BODY_W2GJ_BASE = 9301`, `_BODY_AECORR_BASE = 9401`),
   then nulls the Aero-tab cache; **Download body cards (.bdf)** emits them
   (`body_correction.body_cards_to_bdf`). The body panels carry `SPLINE0` (zero structural
   coupling); they drive the total/trim Cm/Cn but inject no fictitious load into the fuselage beam.

   **Panel kind is auto-detected from the deck (Step A10).** If the selected body panels are
   **decoupled strip bodies** (CAERO1 PID → `PSTRIP`) the stage routes to
   `build_strip_body_correction` instead, emits `(W2gj, Stripk)` pairs at
   `_BODY_W2GJ_BASE = 9301` / `_BODY_STRIPK_BASE = 9501`, and replaces the WT2-ratio readout with a
   "max slope scaling" line (no contamination is possible for a strip, so any value is benign). A
   mix of strip and cruciform panels in one build is rejected. Cruciform (`PAERO1`) panels keep the
   behaviour above.

v1 limits (inherited from the engine): exact-Mach match (no Mach interpolation); one operating
region per surface (the region whose `[a_lo, a_hi]` contains the operating angle); one axis per
surface. Body correction is moment-primary (body lift/side-force is a minimum-norm by-product).

**Session state keys:**
| Key | Type | Description |
|-----|------|-------------|
| `aero_corr_model` | `AeroModel \| None` | Cached `build_aero_model(bulk)` for template strips / box list |
| `aero_corr_df` | `DataFrame \| None` | Validated section-data table from the CSV upload |
| `aero_corr_result` | `MultiSectionDataBuildResult \| None` | Last build (cards + diagnostics) |
| `aero_corr_sids` | `set[int]` | SIDs this tool last injected, so Apply can replace them |
| `aero_corr_upload_id` | `tuple \| None` | `(name, size)` of the parsed CSV — re-parse only on change |
| `aero_corr_csv_name` | `str \| None` | Source CSV filename, for the export provenance header |
| `aero_corr_cond` | `tuple \| None` | `(mach, alpha, beta)` of the last build, for naming / provenance |
| `aero_corr_raw_df` | `DataFrame \| None` | Unsplit upload (incl. the `TOTAL` block) — seeds the body-stage targets |
| `aero_body_result` | `BodyCorrectionResult \| None` | Last body-panel build (Step A9 / Stage 6) |
| `aero_body_sids` | `set[int]` | Body-card SIDs last injected, so Apply replaces them |

All are reset on new file upload. The full-BDF export also reads `_uploaded_source_text` (the raw
uploaded model text, stashed in `_handle_upload`).

### 6. Sidebar — Item Inspector

Selectboxes in the sidebar allow inspecting individual cards:

- **Inspect GRID:** shows X, Y, Z, PS, and active SPC constraints.
- **Inspect CBAR:** shows EID, PID, MID, GA, GB, L, A, I1, I2, J, PA, PB.
- **Inspect RBE3** (shown only when RBE3 elements are present): shows EID, RefGrid, RefDOFs (REFC), and per-group details (weight, DOF string, independent grid IDs).
- **Inspect RBE2** (shown only when RBE2 elements are present): shows EID, GN (independent grid), CM (coupled DOFs), and list of dependent GM grids.

Selecting a GRID or CBAR also highlights it in the 3D view (orange). RBE3 and RBE2 inspection is read-only and does not affect the 3D selection highlight.

---

## GPWG — Mass and CG

Calls `gpwg.py` to compute:
- Total structural mass (from CBAR element distributed mass + CONM2 lumped masses).
- Centre of gravity (X_cg, Y_cg, Z_cg).

Displayed as a summary table in the viewer. No input required; computed directly from loaded `BulkData`.

---

## Case Control UI

Implemented in `case_control_ui.py`.

### Page layout (top to bottom)

**Planned Analysis summary (read-only, Step 57):** When a case control is present, the tab
leads with a SOL-aware, human-readable summary — SOL number + title and one line per subcase
describing what runs and what is output (e.g. "Subcase 1 — Aeroelastic trim @ q=51, M=0
(TRIM 1); DIVERG 1; outputs trim vars, stability derivatives, aero totals, q_div,
displacements"). The SOL 144 summary is bulk-aware (AC5): it appends "hinge moments" when
AESURF cards are present, "monitor loads" when MONPNT1/MONPNT3 cards are present, and "box
ΔCp/forces" on an AEROF/APRES request; an MLOADS subcase reads "Transient maneuver loads
(MLOADS n); outputs time histories, MLDPRNT export, critical-sample loads[, monitor loads]".
Built by
`summarize_case_control(cc, bulk)` via the `_SOL_SUMMARY` registry (`{101, 103, 144}` with a
generic field-dump fallback for unknown SOLs — new solutions slot in by adding a registry
entry). A **▶ Launch Analysis** button (primary) runs the analysis via an `on_launch` callback
supplied by `app.py` (`lambda: _run_analysis(bulk)`); results appear on the Results tab. The
subcase **editor** is demoted behind an "Edit case control" checkbox toggle (a toggle, not an
expander, because the editor itself nests expanders and Streamlit forbids expander-in-expander),
default-on only when no case control exists. SOL 144 case control is **read-only** in the editor
(an info banner directs the user to launch from the summary); the editor's SOL selector stays
101/103.

**Loaded BDF preview (outside form):** When a run file (with case control) is uploaded, a
collapsible `st.expander` ("Loaded BDF — Executive & Case Control") shows the re-serialised
text of the parsed case control. This is the immutable snapshot stored at upload time
(`_loaded_from_file_cc` in session state) and is not affected by edits in the form below.
When a geometry-only (bulk-data) file is loaded, an info banner reads "No case control found
in the loaded file — define one below."

**Executive Control:** Two-column row — SOL dropdown (left, narrow) and Title text input
(right, wide). SOL options display descriptive labels:

| SOL value | Label |
|-----------|-------|
| 101 | `101 — Static` |
| 103 | `103 — Normal Modes` |

Extending to Phase 2 SOLs (108, 109, 111, 112) requires only adding entries to `_SOL_LABELS`
and `_SOL_OUTPUT_FIELDS` in `case_control_ui.py`.

The editor's SOL selector deliberately stays 101/103: SOL 144 case control (TRIM / DIVERG /
MLOADS and their bulk card sets) is **BDF-authored, not editor-authored** — a SOL 144 deck is
uploaded as a run file, shown read-only in the editor, and launched from the Planned-Analysis
summary (or the Results tab's **Run Analysis**). The run path is `app.py::_run_sol144` — see
[Run Analysis from Viewer](#run-analysis-from-viewer) and
[SOL 144 — Static Aeroelastic Results](#sol-144--static-aeroelastic-results-step-57). A SOL
144/MLOADS authoring UI is recorded under Future development in the backlog.

**Subcases:** One `st.expander` per subcase. Expander label shows the subcase ID and title
(if set). Within each subcase:

| Field | Layout | Condition |
|-------|--------|-----------|
| Subcase title | Full-width text input | Always |
| LOAD SID | Left column selectbox | Always |
| SPC SID | Right column selectbox | Always |
| METHOD (EIGRL) SID | Full-width selectbox | SOL 103 only |
| Output requests | One checkbox per field, equal columns | SOL defined in `_SOL_OUTPUT_FIELDS` |
| Auto-output info | Info banner | SOLs not in `_SOL_OUTPUT_FIELDS` (e.g. SOL 103) |

Output request checkboxes per SOL:
- **SOL 101:** DISPLACEMENT, SPCFORCE, OLOAD, FORCE, STRESS
- **SOL 103:** No checkboxes — info message: "All modal results … output automatically."

**Advanced expander (collapsed by default):** Contains the INCLUDE path text input
(path to the bulk-data `*.dat` file). Defaults to `model.dat` or the path parsed from
the loaded run file.

**Action row (bottom of form):**
```
[+ Add subcase]  [− Remove last]  [          ]  [Apply ▶]
```
All three are `form_submit_button` widgets so they submit without triggering intermediate
reruns. Add/Remove handlers run after the form closes and call `st.rerun()`.

**Export (below form, only when case control is applied):**
- Download BDF button — triggers browser download of `run.bdf`.
- Collapsible "Preview BDF" expander — shows the full case control text in a code block.

### BDF export

`export_bdf_text(cc: CaseControl, include_path: str) -> str` in `case_control_ui.py`
serialises a `CaseControl` object to a parseable BDF string. Example output:

```
SOL 101
TITLE = My analysis
SUBCASE 1
  LOAD = 10
  SPC = 20
  DISPLACEMENT = ALL
  SPCFORCE = ALL
  FORCE = ALL
  STRESS = ALL
INCLUDE 'model.dat'
BEGIN BULK
ENDDATA
```

The function has no Streamlit dependency and is usable in tests.

### Smart defaults for new case control

When a geometry-only file is loaded (no existing case control), the first subcase is
pre-populated with the first available LOAD SID and first available SPC SID from the bulk
data, so the user can click Apply immediately without any manual selection.

**Subcase selector (sidebar):** When a run file (with case control) is loaded, an **Active subcase** dropdown appears in the sidebar. The selected subcase determines which load set is visualised as force/moment arrows in the 3D model view and on the deformed shape. The active subcase ID is stored in `st.session_state.selected_subcase_id`; initialised to the first subcase on upload.

---

## Post-Processing Pages

### Results Load

Results are produced in-process by clicking **Run Analysis** in the Results tab (see [Run Analysis from Viewer](#run-analysis-from-viewer)). After a successful run, the result is stored in session state and the display updates automatically.

### SOL 101 — Deformed Shape Display

`render_sol101_results(bulk, result, load_sid=None)` in `results_view.py`:

- Deformed shape overlay on undeformed ghost geometry (`build_deformed_figure`).
- **Show applied forces** checkbox: hides/shows force/moment arrows on the deformed shape plot. Defaults to on.
- Scale factor slider: auto-initialised so max displacement = 10% of model span.
- Deformed grid positions: `X_def = X_orig + scale × [Tx, Ty, Tz]`.

**Results tables (SOL 101)** — four sub-tabs:
- **Displacements:** GID, Tx, Ty, Tz, Rx, Ry, Rz.
- **Reactions:** GID, Fx, Fy, Fz, Mx, My, Mz.
- **Bar Forces:** EID, Axial, Shear1, Shear2, Torque, BM1_A, BM2_A, BM1_B, BM2_B.
- **Bar Stresses:** EID, Axial, SA_C/D/E/F, SB_C/D/E/F.

### SOL 103 — Mode Shape Display

`render_sol103_results(bulk, result)` in `results_view.py`:

Two-column layout — all controls in the left column (30%), 3D plot in the right column (70%). Everything fits on a single screen without scrolling.

**Left column controls:**
- Mode selector dropdown (shows mode number and frequency).
- **Scale** slider: auto-initialised so max component = 20% of model span.
- **Phase (°)** slider (0–360°, default 90° = +max amplitude, 270° = −max amplitude). Scrub to step through the mode shape cycle. `amplitude = scale × sin(2π × phase/360)`.
- **Camera** dropdown: Isometric (default), ±X view, ±Y view, +Z view (top), -Z view (bottom), XZ plane, YZ plane. Sets the initial camera orientation; user can still rotate interactively.
- **Height (px)** slider: 400–1400 px, default 580.
- **Natural frequencies** collapsible expander: table of mode, Hz, ω rad/s, eigenvalue λ.
- **Modal participation** collapsible expander: bar chart of effective translational mass fraction (Tx DOFs) per mode.

**Right column:**
- Static 3D mode shape figure built by `build_mode_figure`. Axis ranges locked to ±scale extent (`autorange=False`) so the view does not rescale as phase changes.

**Session state:** `sol101_result` / `sol103_result` in session state; cleared on new file upload.

### SOL 144 — Static Aeroelastic Results (Step 57)

`render_sol144_results(bulk, trim_results, diverg_results, maneuver_results)` in
`results_view.py`. A subcase selector spans all three result dicts; the selected subcase
renders whichever result types it produced:

- **Trim** (`Sol144TrimResult`, `_render_sol144_trim`): summary metrics — q, Mach, trim mode,
  and all six aerodynamic totals (AC5): CZ (body), CL (wind), total CMy on the first metric
  row; total CX, CY, CMx (roll), CMz (yaw) on a second row (`total_cx/total_cy/total_cmx/
  total_cmz` on `Sol144TrimResult`; the lateral set is the full 3-component
  `aero_moment_resultant` about the RCSID origin, ≈0 for a symmetric model at a symmetric
  trim); trim-variable table (FREE/PRESCRIBED, value); stability-derivative table with
  rigid, elastic-restrained, and elastic-unrestrained (mean-axis, AE8b) columns
  (CZ/CMY/CX/CY/CMX/CMZ; unrestrained CZ/CMY blank on URDD rows); `q_div` readout with q/q_div ratio
  ("No divergence found" when `None`); per-AESURF hinge-moment table; monitor-point integrated
  loads (Fx…Mz, from `MonitorLoad.totals`); maneuver-closure resultant. Layout mirrors the
  f06 blocks in `results/f06_writer.py::_build_f06_sol144_text`.
- **Deflected shape + canted aero boxes** (`_render_sol144_deflected`): a deflection-scale
  slider, the deformed structure (`build_deformed_figure`), and the aero box mesh from
  `build_aero_box_figure` with `box_disp = scale · (g_disp @ u_g)` — each box's corners are
  rigidly translated by its spline-interpolated structural displacement. Box corners are
  z-bearing, so ±Γ dihedral geometry renders **canted in 3-D, never flattened**. Per-box ΔCp
  colour is shown only when the subcase requested AEROF/APRES (`result.box_cp`); the cached
  `aero_model_144` supplies `g_disp` and the box geometry.
- **Divergence sweep** (`Sol144DivergResult`, `_render_sol144_diverg`): per-Mach roots table
  (root #, q-div, V-div when RHOREF > 0).
- **Transient maneuver** (`ManeuverResult`, `_render_sol144_maneuver`): time histories of
  Fz_aero, My_aero, and peak grid force (`results.peak_grid_force`, the DEF-M5 severity metric) with the critical sample marked; a 1-based sample slider scrubs
  the per-step deflected shape. An **Exports** row (AC5) offers two download buttons built
  in-memory from `results/maneuver_output.py` — **Download MLDPRNT time history**
  (`build_maneuver_time_history_text`, `<stem>.mldprnt.txt`) and **Download critical-sample
  loads (BDF)** (`build_maneuver_critical_load_cards_text`, `<stem>.maneuver_qs_loads.bdf`) —
  the same builders the CLI's `write_maneuver_outputs` uses, so the content matches the CLI
  files exactly (the CLI concatenates one block per subcase; the viewer downloads the selected
  subcase's block).

Run wiring lives in `app.py::_run_sol144` (mirrors `main.py` routing — one shared `AeroModel`
+ `AeroCache`, per-subcase dispatch to `run_sol144_trim` / `run_sol144_diverg` /
`run_maneuver_qs`). F06 export covers SOL 144 trim + divergence + transient maneuver blocks.

---

## Session State

Streamlit session state keys used:

| Key | Type | Content |
|-----|------|---------|
| `bulk_data` | `BulkData \| None` | Parsed model |
| `case_control` | `CaseControl \| None` | Active case control (may be edited) |
| `_loaded_from_file_cc` | `CaseControl \| None` | Immutable snapshot of CC parsed from file; shown in "Loaded BDF" expander; `None` for bulk-data-only uploads |
| `cc_subcases` | `list[dict] \| None` | Editable subcase list in CC form |
| `selected_subcase_id` | `int \| None` | Active subcase ID for load/force display |
| `sol101_result` | `Sol101Result \| None` | SOL 101 results |
| `sol103_result` | `Sol103Result \| None` | SOL 103 results |
| `sol144_result` | `dict[int, Sol144TrimResult] \| None` | SOL 144 trim results per subcase |
| `sol144_diverg_result` | `dict[int, Sol144DivergResult] \| None` | SOL 144 divergence-sweep results per subcase |
| `maneuver_result` | `dict[int, ManeuverResult] \| None` | Phase G0 transient maneuver results per subcase |
| `aero_model_144` | `AeroModel \| None` | Aero model built for the SOL 144 run (supplies `g_disp` + boxes to the deflected-mesh view) |
| `aero_body_eids` | `set[int]` | CAERO1 EIDs selected as body panels when the Aero Correction tab's **Build body correction** succeeds; colours the body panels in the Aero-tab / SOL 144 3D mesh (AC5) |
| `selected_gid` | `int \| None` | Currently selected grid (from sidebar inspector) |
| `selected_eid` | `int \| None` | Currently selected element (from sidebar inspector) |
| `_parse_warnings` | `list[str]` | Warnings from last file upload |
| `_parse_error` | `str \| None` | Error message from last failed upload |
| `sol101_deform_scale` | `float` | SOL 101 deformation scale slider value (widget key) |
| `sol101_show_forces` | `bool` | SOL 101 show-forces checkbox state (widget key) |
| `mode_sel` | `int` | SOL 103 selected mode index (widget key) |
| `mode_scale` | `float` | SOL 103 mode shape scale slider value (widget key) |
| `mode_phase` | `int` | SOL 103 phase in degrees (0–360) slider value (widget key) |
| `mode_camera_preset` | `str` | SOL 103 camera preset selection (widget key) |
| `mode_chart_height` | `int` | SOL 103 chart height px slider value (widget key) |

All interactive result widgets **must** carry a `key=` parameter so Streamlit persists their value across reruns. Without a key, each rerun resets the widget to its `value=` default.

---

## Pre-Solve Validation (VAL1)

Before the **Run Analysis** button in the Results tab, `_show_pre_solve_warnings(bulk, cc)` runs
`_get_pre_solve_warnings(bulk, cc, parse_warnings)` and displays each issue as a yellow
`st.warning` banner. The user can still run the solver; warnings do not block execution.

**Checks performed:**

| Check | Trigger | Impact |
|-------|---------|--------|
| Zero-length CBAR | `L = 0` for any element | Singular stiffness matrix → solver fails |
| No SPC (SOL 101) | `bulk.spcs` and `bulk.spc1s` both empty, SOL 101 | Unconstrained model → singular K |
| No SPC (SOL 103) | Same but SOL 103 | Valid for free-free; warns first 6 modes ~0 Hz |
| SPC SID missing | `sc.spc_sid` not in bulk | Subcase references non-existent constraint set |
| Unsupported load card | Parser warning contains PLOAD1 / PLOAD2 / PLOAD4 / RFORCE / DLOAD / TLOAD1 / TLOAD2 / RLOAD1 / RLOAD2 / ACCEL / ACCEL1 / SLOAD | Card silently dropped; load vector incomplete |
| Zero density (SOL 103) | `mat1.rho == 0` for any material, SOL 103 | Mass matrix zero → unreliable frequencies |
| E-value range | `max(E) / min(E) > 1000` across materials | Possible unit system mismatch |

`_get_pre_solve_warnings` takes `parse_warnings` as an explicit parameter (not session state)
so it is testable without a running Streamlit session. Unit tests live in
`tests/viewer/test_pre_solve_validation.py`.

---

## Run Analysis from Viewer

A **Run Analysis** button in the Results tab:
1. Validates that a model and case control are loaded.
2. Calls `run_sol101(bulk, cc)` or `run_sol103(bulk, cc)` directly in-process. For SOL 144,
   `app.py::_run_sol144` mirrors the `main.py` routing: it builds one shared `AeroModel` +
   `AeroCache`, then dispatches each subcase to `run_sol144_trim` (TRIM), `run_sol144_diverg`
   (DIVERG), or `run_maneuver_qs` (MLOADS).
3. Stores the result in `st.session_state.sol101_result` or `sol103_result`. SOL 144 fills
   `sol144_result` / `sol144_diverg_result` / `maneuver_result` (per-subcase dicts, `None` when
   empty) plus `aero_model_144`, and clears the SOL 101/103 keys (and vice versa).
4. Displays results immediately without requiring CLI.

Solver errors (e.g. singular K, no SPC defined) are caught and shown as a red Streamlit error banner.

---

## F06 Export from Viewer

After a successful analysis run, an **Export F06** section appears below the results in the Results tab. It provides two export options:

1. **Write F06** — writes the `.f06` file directly to disk. The output path text input defaults to `<cwd>/<uploaded-stem>.f06` (i.e. the current working directory where `streamlit run` was invoked, using the uploaded filename stem). The path can be edited to any location before writing.

2. **Download F06** — triggers a browser download of the `.f06` content as a text file named `<uploaded-stem>.f06`.

Multiple subcases are written sequentially into a single `.f06` file. The f06 text is generated by `build_f06_sol101_text` / `build_f06_sol103_text` in `sbeam/results/f06_writer.py`; for SOL 144 runs, `build_f06_sol144_text` (trim blocks), `build_f06_sol144_diverg_text` (divergence-sweep blocks), and `build_f06_sol144_maneuver_text` (Phase G0 transient maneuver blocks, AC5) are used instead. The maneuver block carries the run summary, a per-output-time MANEUVER TIME HISTORY table with the critical sample marked, and the critical-sample detail (closure resultant + displacement/bar-force blocks); the full per-sample field data stays in the MLDPRNT ASCII export. The same three SOL 144 builders feed the CLI f06 (`main.py`), so viewer and CLI f06 files match. The public `write_f06_sol101` / `write_f06_sol103` functions remain available as thin wrappers for programmatic use.

**In-viewer vs CLI-only exports:** the viewer f06 export covers SOL 101/103 and SOL 144 trim +
divergence + transient maneuver. The Phase G0 maneuver time-history / critical-load exports
(`<stem>.mldprnt.txt`, `<stem>.maneuver_qs_loads.bdf`) are available as download buttons on the
maneuver results view (AC5) as well as from the CLI. The remaining SOL 144 auxiliary exports
(`<stem>.aero_loads.bdf`, `<stem>.maneuver_loads.bdf`, `<stem>.monitor_loads.csv`) are
**CLI-only** (written by `main.py`).

**Session state:** `_uploaded_filename` stores the original uploaded filename so the default output path can be derived.

---

## Error Display

- Parse errors and warnings are shown as Streamlit warning/error banners.
- Solver errors (singular matrix, etc.) are shown with the error message in a red banner.

---

## Testing

**Pre-solve validation unit tests** live in `tests/viewer/test_pre_solve_validation.py`.
They call `_get_pre_solve_warnings` directly (no Streamlit session required) and cover all
five checks: zero-length CBAR, SPC coverage, unsupported load cards, zero density, E-value
range heuristic.

**Integration tests** for the viewer live in `tests/viewer/test_apptest_integration.py` and use Streamlit's `AppTest` framework.

**Covered flows:**

| Test | Flow |
|------|------|
| `test_flow_a_sol101_render_and_run` | Injected geometry → GPWG sidebar → SOL 101 run → deformed-shape UI |
| `test_flow_b_sol103_render_and_run` | Injected geometry → SOL 103 run → mode-shape UI |
| `test_flow_c_sol144_render_and_run` | Injected ±Γ dihedral SOL 144 deck → trim run → canted deflected-mesh UI |
| `test_flow_d_sol144_mloads_render_and_run` | Injected MLOADS sample deck → trim + maneuver run → six trim totals visible; maneuver subcase renders time history, sample slider, exports (AC5) |
| `test_body_eids_split_mesh_traces` / `test_strip_boxes_marked_body_without_eids` / `test_no_body_trace_without_bodies` | Body-panel trace split in `build_aero_box_figure` (AC5) |
| `test_summary_sol144_advertises_hinge_and_monitor_outputs` / `test_summary_sol144_maneuver_advertises_exports` | Bulk-aware SOL 144 run summary (AC5) |
| `test_apptest_aero_tab_no_exception` | Injected aero bulk → Aero tab renders without exception |
| `test_apptest_correction_tab_renders` | Injected aero bulk → Aero Correction tab renders without exception |
| `test_apptest_build_button_appears_with_table` | Section table in session → **Build correction cards** button present |
| `test_apptest_apply_injects_without_stacking` | Click **Apply to model** → W2GJ/AECORR injected; re-apply replaces (one pair) |
| `test_built_cards_change_corrected_solve` | Build → inject → rebuild: corrected CL hits the prescribed section slope |
| `test_template_csv_roundtrips_schema` | `_template_csv` parses back to the section_data schema (one row per strip) |
| `test_surface_var_and_mixed` | `surface_var` reports per-surface axis; mixed-axis surface → `MIXED` |
| `test_separate_alpha_beta_selects_region_per_var` | α and β pick each surface's own region; single incidence skips the β surface |
| `test_mixed_var_surface_is_skipped` | A surface with both ALPHA and BETA rows is skipped (one axis per surface) |
| `test_surface_dihedral_deg` | Dihedral helper: horizontal ≈0°, 45°-canted ≈45° |
| `test_apptest_canted_surface_warns` | Canted surface (20–70°) raises the blended-axis warning |
| `test_apptest_preview_persists_on_surface_change` | Changing **Preview surface** keeps the build result (upload-id guard) |
| `test_suggest_corrected_name` / `test_full_corrected_bdf_roundtrips` | Default filename + corrected BDF carries provenance and re-parses with the cards |
| `test_rigid_derivative_table_state_no_correction` | No correction cards → uncorrected table equals corrected, Δ table is all zeros |
| `test_rigid_derivative_table_state_with_correction` | A WKK correction moves the derivatives; uncorrected reconstructs the no-WKK baseline; Δ = corrected − uncorrected |
| `test_guess_body_panels` | Largest-chord +Z / +Y surfaces are picked as the horizontal / vertical body panels (Step A9) |
| `test_apptest_body_stage_renders` | With a body panel + flying result, Stage 6 renders its header and the two body-panel selectboxes |
| `test_apptest_body_build_and_apply` | **Build body correction** converges to the targets; **Apply** injects flying + body (9301/9401) card pairs |

(The Aero Correction tests live in `tests/viewer/test_aero_correction_view.py`; the
`rigid_derivative_table` / span-loading figure tests in `tests/viewer/test_aero_view.py`.)

**State injection pattern.** Tests do not simulate the file-upload widget (fragile with the temp-file-based parser). Instead, `BulkData` and `CaseControl` are pre-parsed from integration BDF files in module-scoped fixtures (`cantilever_sol101_parsed`, `cantilever_sol103_parsed` in `tests/viewer/conftest.py`), then written directly into `at.session_state` after the first `at.run()`. This replicates exactly what `_handle_upload` sets.

**Three-step run protocol:**
1. `at.run()` — cold start (shows upload prompt, initialises all session state keys via `_init_session_state`).
2. Write `at.session_state[...]` — inject parsed `bulk_data`, `case_control`, and associated flags.
3. `at.run()` — render with injected state (GPWG, tabs, Model tab content).
4. Click "Run Analysis" via `next(b for b in at.button if b.label == "Run Analysis").click()`.
5. `at.run(timeout=...)` — verify solver completes and results UI renders.

**Entry point.** `AppTest.from_function(_sbeam_app)` is used (not `from_file`) where `_sbeam_app` is a local wrapper that imports and calls `main`. This avoids the `NameError` that occurs when `from_function` serializes a function whose imports come from the module scope.

**Run the tests:**

```
pytest tests/viewer/test_apptest_integration.py -v
```
- Skipped BDF cards are listed in an expandable "Warnings" section.
