# Completed Development — Viewer / GUI

Part of the completed-development record (index: `00_completed_development.md`).
Covers the Streamlit/Plotly viewer: model display and interrogation, case-control UI,
in-process runs, results display (SOL 101/103/144), the aero and aero-correction tabs,
and resolved viewer defects.

---

## Phase 5 — Viewer

### Step 17: Viewer — Model Load and 3D Display ✅ COMPLETE

**Objective:** Build the Streamlit app skeleton with file upload, BDF parsing, and basic Plotly 3D model display. The viewer must handle **both** bulk-data-only files and full run files.

**Deliverables:**
- `viewer/app.py` — page routing, session state initialisation.
  - `_has_case_control(content: str) -> bool` helper.
  - `_handle_upload()` dispatcher: calls `parse_bdf()` or `parse_bulk_file()` depending on file content.
- `viewer/geometry.py` — Plotly 3D figure: GRID scatter, CBAR lines, PLOTEL dashed lines.
- `tests/viewer/test_geometry.py`
- `sample/simple_beam.dat` — bulk-data-only version for demonstrating geometry-only upload.

---

### Step 18: Viewer — Model Interrogation Panel ✅ COMPLETE

**Objective:** Add tabbed properties panel and GPWG summary.

**Deliverables:**
- `viewer/geometry.py` extended — click-to-select grid/element; selected item details shown in sidebar.
- Tables: Grids, Elements, Properties, Materials, Loads, Constraints.
- GPWG summary panel (total mass, CG).

---

### Step 19: Viewer — Case Control UI and BDF Export ✅ COMPLETE

**Objective:** Build the case control form and BDF export capability.

**Deliverables:**
- `viewer/case_control_ui.py` — Streamlit form: SOL, TITLE, SUBCASE, LOAD dropdown, SPC dropdown, METHOD dropdown (SOL 103), output request checkboxes, INCLUDE path, Add Subcase, Export buttons.
- Export writes a valid `*.bdf` case control file with INCLUDE statement.

---

### Step 20: Viewer — Run Analysis In-Process ✅ COMPLETE

**Objective:** Add a Run Analysis button that calls the solver directly from the viewer and loads results into session state.

**Deliverables:**
- `viewer/app.py` extended — Run button calls `sol101.run_sol101` or `sol103.run_sol103`; result stored in session state.
- Error banners for solver failures.

---

### Step 21: Viewer — SOL 101 Results Display ✅ COMPLETE

**Objective:** Display deformed shape and results tables for SOL 101.

**Deliverables:**
- `viewer/results_view.py` — deformed shape overlay on Plotly 3D figure; scale factor slider; displacement, reaction, bar force, and stress tables.

---

### Step 22: Viewer — SOL 103 Results Display ✅ COMPLETE

**Objective:** Display mode shapes for SOL 103 with mode selector and animation.

**Deliverables:**
- `viewer/results_view.py` extended — mode selector dropdown; animated mode shape (Plotly animation frames cycling ±max); frequency display; modal mass fraction bar chart.

---


## Resolved defects (Phase 1 viewer)

### B1: Viewer — Case Control UI Export ✅ FIXED

**Root cause:** The case control panel uses `st.form()`. On form submission Streamlit
commits widget values to `st.session_state[widget_key]`, then reruns the script. During
the rerun the render loop re-renders each subcase widget with `value=sc_data["field"]`
(the OLD value from `cc_subcases`). In some Streamlit versions this `value=` argument
overwrites the just-committed session state, so the widget returns the old value and
writes it back into `cc_subcases`. The `if submitted:` block then reads the stale values.

**Fix (`sbeam/viewer/case_control_ui.py`):** Changed the `if submitted:` block to
enumerate `cc_subcases` and read every subcase field directly from
`st.session_state.get(widget_key, fallback)` instead of from the `cc_subcases` dict.
`st.session_state[widget_key]` is guaranteed to hold the committed value after form
submission regardless of any render-loop overwrites. The global `sol`, `title`, and
`include_path` widgets (no `key=`) are unaffected and continue to use their direct
return values.

**Acceptance test:** `tests/viewer/test_case_control_ui.py::TestMultiSubcaseRoundTrip`
— builds a 2-subcase SOL 101 `CaseControl` with distinct per-subcase `load_sid`,
`spcforce`, `force`, and `stress` values; exports via `export_bdf_text`; parses back
via `parse_case_control`; asserts all fields on both subcases match exactly.

---

### B2: Viewer — Results Display ✅ FIXED

Deformed-node trace in `build_deformed_figure` now carries `customdata=[gid, Tx, Ty, Tz]` and a `hovertemplate` showing raw physical displacements. Hover no longer shows scaled coordinates.

---

### B4: Viewer — f06 Import ✅ CLOSED (Doc-Only)

**Description:** `docs/10_standard/06_viewer.md` was reported to describe a post-processing upload path for
`.f06` files — a feature that was never implemented and is out of scope for Phase 1.

**Resolution:** Confirmed that `docs/10_standard/06_viewer.md` contains no f06 import documentation. The
text was either removed in an earlier session or never formally written into the doc. No code
changes required. The "NASTRAN f06 import" item remains in the Future Development table in
`docs/30_future/00_backlog.md` and will be addressed in Phase 3+.


## Case Control UI redesign

### Step 39: Viewer — Case Control UI Redesign ✅ COMPLETE

**Objective:** Restructure the Case Control tab so it has clear sections, shows what was loaded
from the file, filters output requests per SOL, and is extensible for Phase 2 SOLs.

**Deliverables:**
- `sbeam/viewer/case_control_ui.py` — full redesign of `render_case_control_panel`:
  - `_SOL_LABELS` dict: human-readable SOL labels (`101 — Static`, `103 — Normal Modes`); Phase 2 SOLs added here.
  - `_SOL_OUTPUT_FIELDS` dict: maps SOL → list of output request field names; SOLs absent show no checkboxes.
  - `_OUTPUT_LABELS` dict: maps field name → BDF token string.
  - **Loaded BDF expander** (outside form): shows the re-serialised CC parsed from the uploaded file; shows an info banner when no CC was in the file.
  - **Executive Control** section: SOL selectbox (with descriptive label) and Title text input in a `[1, 3]` column layout.
  - **Subcases** section: per-subcase expanders with LOAD/SPC in two columns; METHOD (EIGRL) for SOL 103 only; output checkboxes only for SOLs in `_SOL_OUTPUT_FIELDS`; SOL 103 shows "output automatic" info.
  - **Advanced** expander (collapsed): INCLUDE path text input.
  - **Action row**: `+ Add subcase`, `− Remove last`, `Apply` all as `form_submit_button` on one row.
  - **Export section** (below form): Download BDF button + collapsible BDF preview.
  - New-CC default: first available LOAD and SPC SIDs pre-populated when no CC exists.
- `sbeam/viewer/app.py`:
  - `_init_session_state`: added `"_loaded_from_file_cc": None` key.
  - `_handle_upload`: added `st.session_state._loaded_from_file_cc = cc` to store the immutable file snapshot.
- `docs/10_standard/06_viewer.md` — Case Control UI section rewritten; `_loaded_from_file_cc` added to Session State table.

**Test/Acceptance:**
- Geometry-only file upload: "No case control found…" banner; first available LOAD/SPC SIDs pre-selected.
- Run-file upload: "Loaded BDF" expander shows the parsed CC text; editor initialises from parsed values; editing and Apply does not change the loaded snapshot.
- SOL 101: 5 output checkboxes present; METHOD (EIGRL) absent.
- SOL 103: output checkboxes replaced by "output automatic" info; METHOD (EIGRL) selectbox present.
- Add / Remove subcase: entries added/removed; existing field values preserved.
- Download BDF: exported file round-trips through `parse_bdf()` without error.
- INCLUDE path: Advanced expander collapsed by default; change reflected in BDF preview.

**Key decisions:**
- `_loaded_from_file_cc` stored as a separate session state key (not derived from `case_control`) so the "loaded" view is never overwritten by editor changes.
- `_SOL_OUTPUT_FIELDS` dict (SOL → field list) is the single extension point for Phase 2: adding SOL 108 requires one dict entry; no conditionals in the render loop.
- INCLUDE path moved to a collapsed "Advanced" expander: users rarely change it; keeping it visible was visual noise.
- Output flags for SOLs not in `_SOL_OUTPUT_FIELDS` are forced to `False` during render so the `SubcaseControl` object never carries stale output flags from a prior SOL selection.

---


---

## Aero viewer & Aero Correction tabs (Phase A GUI)

### Step 44: Aero Viewer — Box Mesh + cp Overlay ✅ COMPLETE

**Objective:** Add a visual layer for the Phase A VLM results: a new "Aero" tab in the
Streamlit viewer showing the aerodynamic box mesh in 3D, per-panel cp colouring, and a
spanwise section-CL strip chart.

**Deliverables:**
- `sbeam/viewer/aero_view.py` *(new)* — five functions:
  - `build_aero_box_figure(bulk, aero_model, cp=None, cl_section=None, cp_corr=None) -> go.Figure`
    — `make_subplots` figure with a 3D scene (row 1) and a 2D xy strip chart (row 2).
  - `_add_box_mesh(fig, boxes)` — single `go.Scatter3d` wire-frame trace; each quad walked
    as `[0,1,2,3,0, None]` (root-LE → tip-LE → tip-TE → root-TE → close).
  - `_add_cp_contour(fig, boxes, cp)` — `go.Mesh3d` with triangulated quads; per-box cp
    applied to all 4 vertices as `intensity`; `colorscale="RdBu_r"`.
  - `_add_section_load_strip(fig, boxes, cl_section)` — `go.Bar` of spanwise fraction vs
    section CL; span fraction taken from `box.span_frac` for each `i_span`.
  - `_add_corrected_vs_inviscid(fig, boxes, cp_inv, cp_corr)` — two `go.Scatter` traces
    (spanwise mean cp per strip) overlaid on the strip chart when AECORR is active.
- `sbeam/viewer/app.py` — session state keys `"aero_model"` and `"aero_result"` added
  (initialised to `None`; reset on new file upload). Tab list is conditionally extended to
  four tabs when `bulk.caero1s` is non-empty; `_render_aero_tab(bulk)` renders controls
  (AoA input, symmetry radio, Compute button), CL/CM metrics, and the figure.
- `tests/viewer/test_aero_view.py` *(new)* — 4 tests: three figure-builder unit tests
  (no cp, with cp+cl_section, with cp_corr overlay) and one AppTest smoke test asserting
  no exception and "Compute Aero" button presence.

**Key decisions:**
- **`make_subplots` with mixed `scene`/`xy` types**: the 3D scene and 2D strip chart
  share a single `go.Figure` as specified. `specs=[[{"type":"scene"}],[{"type":"xy"}]]`
  with `row_heights=[0.75, 0.25]`.
- **Conditional tab list**: `st.tabs(["Model","Case Control","Results","Aero"])` is
  only created when `bulk.caero1s` is non-empty, avoiding an empty Aero tab for
  structural-only models. `tab_aero = None` for models without aero cards.
- **`build_aero_model` / `solve_rigid_cl` called inside the app** (not in the view
  module) so the view module stays free of Streamlit imports and is fully testable
  without a running Streamlit server.
- **`cp_corr` overlay is optional** (`None` by default): it appears on the strip chart
  only when an AECORR-corrected cp array is explicitly passed in.

**Test / Acceptance (S44):**
- `test_build_aero_box_figure_no_crash`: `isinstance(fig, go.Figure)` with mesh only.
- `test_build_aero_box_figure_with_cp_no_crash`: figure builds with real cp + cl_section from `solve_rigid_cl`.
- `test_build_aero_box_figure_with_corr_no_crash`: figure builds with synthetic cp_corr overlay.
- `test_apptest_aero_tab_no_exception`: AppTest with 4×10 rectangular-wing bulk — no `at.exception`; "Compute Aero" button present.
- **620 tests pass, 0 skipped, 0 failures.**


---

### Step A-GUI: Aero tab honours AIC corrections + section-correction preview plots ✅ COMPLETE

**Objective:** Make the viewer reflect the section force+moment correction. The Aero tab used
`solve_rigid_cl`, which rebuilt the *raw* AIC and applied only W2GJ — so WKK/WT1/WT2 (and hence the
whole correction) were invisible in the GUI. Also add spanwise preview plots for the
section-correction page.

**Deliverables:**
1. **`sbeam/aero/vlm.py`** — `solve_rigid_cl` gains optional `cp_operator` (the corrected ΔCp
   operator `AeroModel.ajj_inv_corr`): when supplied, `ΔCp = cp_operator @ rhs` directly, honouring
   WKK/WT1/WT2 + the baked-in Prandtl–Glauert factor; `mach` then ignored. No-correction path is
   numerically identical to before.
2. **`sbeam/viewer/app.py`** — Aero tab passes `cp_operator=aero_model.ajj_inv_corr`; a caption
   flags the active correction method.
3. **`sbeam/viewer/aero_view.py`** — `build_section_correction_figure(boxes, df, data_result,
   caero_eid)`: two-panel spanwise preview (`cn_α(η)`, `cm0(η)`) overlaying user input (markers at
   table η-stations) vs achieved-on-strips (line), exposing interpolation/end-clamping.
4. **Tests** — `test_corrections.py::TestSolveRigidClCorrectedOperator` (no-correction identity;
   WKK=1.5 → CL/1.5; shape guard); `test_cessna210_example.py::test_section_preview_figure`
   (trace count + achieved==input). Cleaned pre-existing lint in `test_corrections.py`.
5. **Docs** — 05_aeroelastics.md (`solve_rigid_cl` signature, Aero-tab section, worked-example
   note), 06_viewer.md.

**Key decisions:**
- The corrected operator is the single source of truth: rather than re-deriving corrections in the
  rigid solver, `solve_rigid_cl` consumes `ajj_inv_corr` (which already carries WKK/WT1/WT2 and
  1/β). Backward compatible — `cp_operator=None` keeps the build-and-solve path.
- The Aero tab always passes `ajj_inv_corr`; with no correction card it equals the plain PG
  operator, so uncorrected decks are unchanged to floating point.

**Test / Acceptance:**
- New tests pass; full aero + viewer suites green; ruff clean.

---

### Step A-GUI2: Aero tab — full rigid S&C derivative table, uncorrected-vs-corrected span loading ✅ COMPLETE

**Objective:** Make the Aero tab's coefficient output a first-class, full-width panel. Previously
the CL/CY/CM metrics + per-surface table were crammed into the narrow control column, only the
corrected solution was shown, and the span-load strip was a single bar series keyed by a *global*
`i_span` — which silently merged strips from different CAERO1 surfaces and showed force only.

**Deliverables:**
1. **`sbeam/viewer/aero_view.py`** —
   - `rigid_derivative_table(aero_model, bulk, naming)`: the full rigid stability & control
     derivative matrix (rows ANGLEA/SIDES/ROLL/PITCH/YAW + AESURF controls; columns the six
     force/moment coefficients per radian/label). Reuses `build_djx` + `sol144._compute_rigid_derivs`
     (rigid, `u_a = 0`) — matches the SOL 144 f06 derivatives with no trim/structure solve. `naming`
     toggles conventional aero symbols (CL/CY/Cl/Cm/Cn/CX) ↔ raw SOL 144 names (CZ/CY/CMX/CMY/CMZ/CX).
     Returns `None` when no AEROS card.
   - `build_span_loading_figure(boxes, cp_corr, cp_unc=None, aeros=None)` + helper `_strip_cn_cm`:
     per-surface spanwise section `cn(η)` (area-weighted normal force) and `cm(η)` about each strip's
     **local ¼-chord** (nose-up +ve), grouped by `(caero_eid, i_span)` — one line per surface, two
     subplots, corrected solid / uncorrected dashed.
   - `build_aero_box_figure` gains `strip: bool = True`; `strip=False` returns a scene-only figure
     (Aero tab) — the SOL 144 results view keeps the default, so it and the crash tests are unchanged.
2. **`sbeam/viewer/app.py`** — `_render_aero_tab`: on Compute also solves the uncorrected baseline
   (`cp_operator=None, mach=aero_model.mach`) when a correction card is present (new `aero_result_unc`
   session key); the derivative table, span-loading figure, and per-surface table move to a
   full-width section below the 3D view; a **Naming** radio drives `rigid_derivative_table`; the 3D
   mesh is rendered `strip=False`.
3. **Tests** — `test_aero_view.py`: derivative-table shape/naming (both modes same numbers),
   `ANGLEA→CL` ≈ single-point CL/α cross-check, `None` without AEROS, AESURF rows present
   (`ha144a_fullspan_sbeam.bdf`); span figure single- and multi-surface trace counts;
   `build_aero_box_figure(strip=False)`. `test_cessna210_example.py`: rigid CLα ≈ 5.2/rad +
   5-surface span figure.
4. **Docs** — 06_viewer.md (Aero-tab rewrite, module-map row), 05_aeroelastics.md (Aero-tab section,
   `build_aero_box_figure` signature, helper table, usage example).

**Key decisions:**
- Reuse the SOL 144 rigid-derivative path verbatim (`_compute_rigid_derivs`) rather than a separate
  finite-difference set, so the Aero tab and the f06 cannot drift; the cross-check test pins
  ANGLEA→CL to the single-point lift slope (agree to ~0.03 % on the Cessna deck).
- Section moment about the **local ¼-chord** (not the airplane reference) so the span-load plot
  validates WT2/W2GJ corrections strip-by-strip, consistent with the section-correction preview.
- Uncorrected baseline uses `aero_model.mach` so Prandtl–Glauert matches the corrected operator; it
  is only computed/overlaid when a correction card exists (otherwise the curves coincide).

**Test / Acceptance:**
- `tests/viewer/ tests/aero/` → 437 passed (was 429; +8); ruff clean on all changed files.

---

### Resolved Defect A-GUI2a: rigid S&C table mislabelled body-axis `CZ` as wind-axis `CL` ✅ RESOLVED (2026-06-14)

**Symptom (user-reported):** in the Aero tab's "Rigid stability & control derivatives" table the
**RAW** and **Aero** naming toggles produced identical numbers, yet the Aero toggle relabelled the
vertical-force column `CZ` → `CL` — and `CL` (wind axis) is not the same quantity as `CZ` (body axis).

**Diagnosis:** the integrated force is `f_box_vec = skj @ gamma`, summed on the global/body z-axis
(`CZ = Fz/Sref`, `sol144._compute_rigid_derivs`). Per theory §5.4 this is explicitly *not* the
wind-axis lift `C_L` (force ⊥ to U∞); `CL = CZ·cosα + CX·sinα`, equal only at α≈0. The toggle
(`_DERIV_AERO_COLS` in `sbeam/viewer/aero_view.py`) performed a cosmetic relabel with no body→wind
rotation (a test even pins `np.allclose(df_aero, df_raw)`), and the table carries no reference
incidence from which a wind-axis `CL` could be formed. The internal inconsistency was visible in the
header set itself — `CL` (wind symbol) alongside `CX` (body symbol). Numerically harmless for the
α-row at the α≈0 linearisation point (CLα≈CZα, the difference being O(CX)≈0 in inviscid VLM), but a
genuine terminology error that becomes material at nonzero reference α / with base axial force.

**Fix:** the Aero naming keeps the body-axis symbol `CZ` for the vertical-force column (moments stay
the conventional body-axis `Cl/Cm/Cn`); no wind-axis transform is invented. `app.py`'s Naming radio
illustration switched to symbols that actually differ between modes (`Aero (α, Cm…)` ↔
`Raw (ANGLEA, CMY…)`). `test_aero_view.py` (and `test_cessna210_example.py::test_rigid_derivative_table_and_span_figure`)
expect the `CZ` header and cross-check `df.loc["α","CZ"]`;
05_aeroelastics.md / 06_viewer.md note the column is body-axis `CZ`, not wind-axis `CL`.

---

### Step A-GUI2b: report genuine wind-axis CL/CD alongside body-axis CZ ✅ COMPLETE (2026-06-14)

**Objective:** Follow-on to A-GUI2a. Rather than only relabelling the body-axis force as `CZ`,
actually compute and report the **wind-axis** lift `CL` (⊥ to U∞) and drag `CD` (∥ to U∞) at the
flight condition, so the Aero tab and f06 carry the genuine aerodynamic coefficients (not just a
honestly-named body-axis number).

**Deliverables:**
1. **`sbeam/aero/vlm.py`** — `solve_rigid_cl` returns, additively: `CZ` (explicit body-axis alias
   of legacy `CL`), `CX` (body streamwise = `2·Σ Γ·Δy·n_x / S_ref`), `CL_wind = CZ·cosα − CX·sinα`,
   and `CD_wind = CDi` (Trefftz). The legacy `CL` key keeps its body-axis value so every existing
   identity/validation test is untouched.
2. **`sbeam/solver/sol144.py` + `results.py`** — trim path adds `total_cx` and `total_cl_wind`
   (`= total_cl·cosα_trim − total_cx·sinα_trim`, α_trim = trimmed `ANGLEA`); `total_cl` unchanged
   (body-axis CZ, balances weight).
3. **Viewer / f06** — Aero tab shows CL (wind) / CD (induced) / CZ (body) / CY / CM with an
   axis-convention caption; per-surface table labelled body-axis (CZ). SOL 144 trim summary shows
   CZ (body) + CL (wind). f06 prints `TOTAL CZ (BODY)` and `TOTAL CL (WIND)`.
4. **Tests/docs** — `test_vlm.py` wind-axis cases (CZ alias; CX≈0 on a planar wing;
   `CL_wind = CZ·cosα − CX·sinα < CZ`; `CD_wind == CDi`). Theory §5.4, 05/06 standard docs updated.

**Key decisions:**
- **Additive, not a rename.** `result["CL"]` is used across the suite as the body-axis quantity in
  exact identities (α-linearity `r2 == r1/2`, AoA-equivalence, parallel-axis CM, `Fz = CL·Sref`,
  dihedral cosΓ). Changing its meaning would break correct body-axis physics; new keys avoid that.
- **Wind-axis drag = Trefftz `CDi`, not the near-field projection.** A surface-normal-pressure VLM
  has no leading-edge suction (so body `CX≈0`); the near-field `CX·cosα + CZ·sinα` over-predicts
  induced drag. The far-field Trefftz value is the physically meaningful wind-axis drag.

**Test / Acceptance:** focused suite (`test_vlm`, `test_f06_sol144`, `test_ae1_fullspan`,
`tests/viewer/`) → 96 passed incl. 4 new wind-axis cases; broader aero/results/viewer/integration
set → 222 passed (no regressions from the additive keys / f06 relabel).

---

### Step A-GUI3: Aero Correction tab — build correction cards from CFD/test section data ✅ COMPLETE

**Objective:** Expose the (already built, already tested) section-data → correction-card pipeline
as a viewer page. Previously `aero/section_data.py` + `aero/section_correction.py` (CSV ingestion,
`build_from_section_data_multi`, `cards_to_bdf`) and `aero_view.build_section_correction_figure`
existed but were unwired — there was no GUI to view experimental/CFD section lift & moment data,
generate the W2GJ + AECORR(WT2) cards for a condition, and add them to the model so the existing
Aero page runs the corrected solve.

**Deliverables:**
1. **`sbeam/viewer/aero_correction_view.py`** (new) — `render_aero_correction_tab(bulk)`:
   - **CSV template/upload** — `_template_csv(aero_model)` concatenates `template_dataframe` over
     all CAERO1s for a download; `st.file_uploader` → `section_data.validate_section_data`
     (errors inline) → `aero_corr_df`. (Confirmed scope: CSV upload + template, no in-app grid.)
   - **Condition** — `available_conditions` block list; a **Mach** selectbox + **operating
     incidence** input; per-surface coverage via `operating_region`. **Build correction cards** →
     `build_from_section_data_multi(aero_model.boxes, build_aero_model(bulk, mach=mach).ajj, df,
     mach=, incidence_deg=, sid_w2gj_base=9001, sid_aecorr_base=9101)` → `aero_corr_result`.
   - **Preview/diagnostics** — extrapolation/skip warnings; `build_section_correction_figure`
     input-vs-achieved per surface + a per-strip achieved-targets table.
   - **Apply / export** — `_apply_cards` injects each `(W2gj, Aecorr)` into `bulk.w2gjs` /
     `bulk.aecorrs`, clearing the tool's own previously-injected SIDs (tracked in `aero_corr_sids`)
     so a re-apply replaces rather than stacks, and nulls `aero_model`/`aero_result`/
     `aero_result_unc`; `_warn_conflicts` flags a pre-existing WKK (WKK precedence shadows WT2) or a
     non-generated WT2 on a corrected surface. **Download cards (.bdf)** via `cards_to_bdf`.
2. **`sbeam/viewer/app.py`** — new **Aero Correction** tab (5th, when `bulk.caero1s`); imports the
   renderer; adds + resets session keys `aero_corr_model`/`aero_corr_df`/`aero_corr_result`/
   `aero_corr_sids`.
3. **Tests** — new `tests/viewer/test_aero_correction_view.py` (5): template CSV schema round-trip;
   build→inject→rebuild corrected CL reaches the prescribed section slope (π·α target, below the
   finite-wing VLM slope); AppTest renders, Build button appears with a table, Apply injects cards
   and a re-apply does not stack.
4. **Docs** — 06_viewer.md ("Aero Correction Tab" section + module-map row + test table),
   05_aeroelastics.md ("Aero Correction page" paragraph), CHANGELOG `[Unreleased]`.

**Key decisions:**
- A "condition" = one flight point (exact Mach + operating incidence) → `build_from_section_data_multi`
  corrects every surface in one global build; matches the engine's v1 limits (no Mach interpolation,
  one region per surface).
- Persistence = inject into the in-session model (the Aero tab already keys off
  `bulk.wkks`/`bulk.aecorrs`, so no further wiring) **and** a downloadable `.bdf` snippet — no
  full-BDF writer needed.
- Reserved SID bases (9001/9101) + per-session SID tracking so the tool owns and replaces its own
  cards instead of accumulating duplicate WT2 on a surface.

**Test / Acceptance:**
- `tests/viewer/ tests/aero/` green (was 438; +5); ruff clean on changed files.

---

### Step A-GUI4: Aero Correction page fixups — α/β split, cp comparison, formatting, corrected-BDF export ✅ COMPLETE (2026-06-14)

**Objective:** Address five usability/correctness issues raised on the A-GUI3 Aero Correction page:
(1) one operating angle was applied to every surface regardless of its `var`, so a BETA (fin)
surface's region was selected by the α value; (2) changing the **Preview surface** wiped the build;
(3)/(4) plot and table numbers showed 10–12 digits; (5) the only persistence was an in-session apply
+ card snippet — no toggleable pre/post comparison and no self-contained corrected BDF to run/share.

**Deliverables:**
1. **Separate α / β operating points.** `section_data.build_from_section_data_multi` gains
   `alpha_deg`/`beta_deg`; each surface picks its angle from its `var` (new `section_data.surface_var`;
   ALPHA→α, BETA→β; `incidence_deg` retained as a single-axis fallback). A `MIXED` (both-axis) surface
   is skipped. The build UI exposes two inputs and a per-surface status table (var / axis / operating /
   region / Γ).
2. **Canted-surface warning.** New `aero_view.surface_dihedral_deg` (length-weighted |Γ| from box span
   edges); the status table warns when `20° ≤ Γ ≤ 70°` (single-axis correction blends α/β).
3. **Preview persistence (#2 fix).** Root cause: `st.file_uploader` returns the file on every rerun, so
   the upload block re-ran `aero_corr_result = None` each time. Guarded with an upload-id check
   (`aero_corr_upload_id`); the preview chart also gets a stable key.
4. **5-sig-fig formatting** — new `viewer/format_utils.py` (`fmt` decimal-down-to-exp-−4 / uppercase-E;
   `fmt_mass` 0.1-unit; `style_numeric` Styler). Applied across all viewer tables/metrics (model-data
   tabs, GPWG, inspector, SOL 101/103/144 results, rigid-derivative + per-surface tables) and the
   Aero/Aero-Correction Plotly hovers/ticks (`.5~g`); masses keep `fmt_mass`.
5. **Cp view toggle (#5).** Aero tab radio Corrected / Uncorrected / **Δ** drives the 3D mesh
   (`build_aero_box_figure(cp_cmid=, cp_title=)`, Δ = zero-centred diverging scale) and the span plot
   (`build_span_loading_figure(mode=)`).
5b. **Span-load per-surface show/hide.** A **Show surfaces** multiselect (default all) thins a busy
    multi-surface span plot via `build_span_loading_figure(..., surfaces=)`; colours are assigned from
    the full surface set so hiding one surface does not recolour the others. Stale stored selections
    (after a model change) are filtered to the current surfaces.
6. **Full corrected BDF export (#5).** `aero_correction_view.build_corrected_bdf` splices the cards into
   the uploaded model text before `ENDDATA` with a provenance header (source CSV, date, Mach/α/β,
   CAEROs); editable filename via `suggest_corrected_name` (`<stem>_M0p30_A2p0_B0p0.bdf`); raw upload
   text stashed in `_uploaded_source_text`. One file per Mach.
7. **Tests** — `test_format_utils.py` (new, 5); +9 in `test_aero_correction_view.py` (surface_var/mixed,
   separate α/β, mixed skip, dihedral, canted warning, preview persistence, filename, corrected-BDF
   round-trip via `parse_bulk_file`); +3 in `test_aero_view.py` (span modes, Δcp diverging mesh,
   per-surface filter + stable colours).
8. **Docs** — 06_viewer.md (Aero + Aero Correction sections, module map, test table), 05_aeroelastics.md,
   CHANGELOG, CLAUDE.md module map.

**Key decisions:**
- **Self-contained corrected BDF, not a separate file + `INCLUDE`.** sbeam's parser honours only one
  case-control INCLUDE that *replaces* the whole bulk (`bdf_reader.parse_bdf`), and browser uploads are
  single in-memory files — so a separate correction file pulled in via INCLUDE would not run. The
  self-contained splice is also the literal reading of "update the loaded BDF with the correction." The
  DRY include layout is deferred (would need a bulk-section/multi-INCLUDE parser enhancement).
- One axis per surface (ALPHA *or* BETA); canted surfaces only warned, not auto-resolved.

**Test / Acceptance:**
- `tests/viewer/ tests/aero/` green (was 443; +17 → 463); full suite green; ruff clean on changed files.

---

### Step A-GUI5: Aero tab — corrected / uncorrected / Δ rigid-derivative table ✅ COMPLETE (2026-06-14)

**Objective:** On the Aero tab's **Rigid stability & control derivatives** table, the radio
switched between conventional aero names and raw SOL 144 names — a low-value cross-check toggle.
Replace it with a Corrected / Uncorrected / **Δ (corr − uncorr)** selector so the correction's
effect on the rigid stability & control derivatives is visible directly, matching the Cp-view
vocabulary already used for the 3D pressure mesh and span-load curves (A-GUI4).

**Deliverables:**
1. **`state` argument on `rigid_derivative_table`** (`aero_view.py`) — `"corrected"` (default; the
   corrected ΔCp operator with WKK/WT1/WT2 applied — what SOL 144 integrates), `"uncorrected"`
   (raw VLM baseline at the same Mach), or `"diff"` (corrected − uncorrected, column-for-column).
2. **`_uncorrected_cp_operator(aero_model)`** — rebuilds the raw ΔCp operator by inverting the
   stored PG-compressed `aero_model.ajj` and re-applying the Göthert `1/β` factor and Γ→ΔCp
   `2/chord` conversion (exactly the no-correction branch of `build_aero_model`). Swapped into the
   model via `dataclasses.replace` so the unchanged `sol144._compute_rigid_derivs` integrates
   against it — single source of truth, no duplicated derivative maths.
3. **UI (`app.py` `_render_aero_tab`)** — the **Naming** radio (`aero_deriv_naming`) is removed; a
   **Values** radio (`aero_deriv_state`, Corrected / Uncorrected / Δ) appears only when an
   uncorrected baseline exists (`aero_result_unc is not None`, i.e. a correction card is present).
   The table always uses conventional aero names; the Δ caption notes "Δ = corrected − uncorrected".
   `naming="raw"` remains callable for f06 cross-checks but is no longer a UI control.
4. **Tests** — +2 in `test_aero_view.py`: `test_rigid_derivative_table_state_no_correction`
   (no cards → uncorrected ≡ corrected, Δ all-zero) and `test_rigid_derivative_table_state_with_correction`
   (a non-uniform WKK diagonal moves the derivatives; uncorrected reconstructs the no-WKK baseline;
   Δ = corrected − uncorrected).
5. **Docs** — 06_viewer.md (Aero-tab derivative section, module map, test table), 05_aeroelastics.md.

**Key decisions:**
- **Replace, not augment.** The Aero/Raw naming toggle is dropped from the UI (per user direction)
  rather than kept alongside the new control; the raw naming stays available programmatically.
- The Values radio is hidden when there is no correction (corrected and uncorrected coincide, so a
  toggle would be meaningless) — same gate as the Cp-view radio.

**Test / Acceptance:**
- `tests/viewer/ tests/aero/` green (was 463; +2 → 465); ruff clean on changed files.

---


---

## SOL 144 results display

### Phase C — Step 57: Viewer SOL 144 results + Case Control rework ✅ COMPLETE (2026-06-13)

**Objective:** Surface the full SOL 144 chain (trim, stability derivatives, divergence,
hinge/monitor loads, deflected shape, box `cp`, transient maneuver loads) in the Streamlit
viewer — the closing interface item — and re-purpose the Case Control tab into a readable,
SOL-aware analysis-plan summary with a Launch button.

**Deliverables:**
- **Run wiring (`viewer/app.py`):** `_run_sol144` mirrors the `main.py` routing — one
  `AeroModel` + `AeroCache` shared across subcases, each subcase dispatched to
  `run_sol144_trim` / `run_sol144_diverg` / `run_maneuver_qs`. Session keys
  `sol144_result` / `sol144_diverg_result` / `maneuver_result` / `aero_model_144`; Results-tab
  dispatch + SOL 144 f06 export (trim + diverg). Pre-solve "no SPC" warning gated off for 144.
- **Results view (`viewer/results_view.py`):** `render_sol144_results` + `_render_sol144_trim`
  / `_render_sol144_diverg` / `_render_sol144_maneuver` / `_render_sol144_deflected`. Trim
  metrics, free/prescribed trim-variable table, rigid-vs-elastic derivative table, `q_div`
  readout, hinge-moment & monitor-point tables, maneuver closure, DIVERG per-Mach roots, and
  transient time histories with a per-sample deflected shape. Mirrors the f06 block layout in
  `results/f06_writer.py::_build_f06_sol144_text`.
- **Canted, spline-deflected aero mesh (`viewer/aero_view.py`):** `build_aero_box_figure` gains
  an optional `box_disp` arg that rigidly translates each box's corners (and cp `Mesh3d`
  vertices) by the spline-interpolated structural displacement `g_disp @ u_g`. Drawn from the
  z-bearing box corners → ±Γ dihedral geometry renders canted, never flattened.
- **Case Control rework (`viewer/case_control_ui.py`):** SOL-aware `summarize_case_control` +
  `_SOL_SUMMARY` registry (101/103/144 + generic fallback) leads the tab as a read-only
  **Planned Analysis** summary with a **Launch Analysis** button (`on_launch` callback); the
  subcase editor is demoted behind an "Edit case control" toggle (a toggle, not an expander —
  the editor nests its own expanders). SOL 144 case control is launch-only in the editor.

**Test/Acceptance:** `tests/viewer/test_apptest_integration.py::test_flow_c_sol144_render_and_run`
loads `sample/val_dihedral_trim.bdf` (SOL 144, TRIM 1, ±Γ=+10° dihedral CAERO1s), runs the trim,
and asserts all panels render without error, the summary + Launch button are present, and the
cached aero mesh is canted (box-corner z range > 0 — the flattening-regression guard).
`tests/viewer/test_case_control_summary.py` covers the summary registry across SOL 101/103/144.
Full viewer suite (→75) and aero suite (321, incl. V-C-DIH) green.

**Key decisions:**
- Reused the already-3-D `build_aero_box_figure` (box corners carry z from Step 58 geometry), so
  no planar renderer existed to replace — the work was wiring + the `box_disp` deflection.
- Aero-mesh deflection is a **rigid per-box translation** by the spline `g_disp` displacement
  (no panel-incidence rotation) — meets the canted-geometry acceptance with the existing operator.
- The Case Control editor stays SOL 101/103 only; authoring 144 TRIM/DIVERG/MLOADS cards in the UI
  is out of scope. The summary + Launch path works for any parsed SOL including 144.
- Deferred (noted in code): injected-vs-computed mean-flow overlay when `CHORDCP` is active, and
  per-panel incidence rotation of the deflected aero mesh. Neither is in the acceptance.



---

## Steady close-out

### Step AC5 — GUI — close the small viewer gaps ✅ COMPLETE (2026-07-05)

**Objective:** Bring the Streamlit viewer up to parity with the solver output surface for
the steady aeroelastic results it already runs (audit 2026-07-03 of `sbeam/viewer/` vs
solver capability): maneuver exports, f06 maneuver block, all trim totals, body-panel
visualization, run-summary string, and the viewer-doc reconcile.

**Deliverables:**
- **Maneuver exports** — `_render_sol144_maneuver` (`viewer/results_view.py`) gained an
  **Exports** row with two in-memory download buttons reusing the CLI's own builders
  (`results/maneuver_output.py::build_maneuver_time_history_text` /
  `build_maneuver_critical_load_cards_text`), so `<stem>.mldprnt.txt` and
  `<stem>.maneuver_qs_loads.bdf` match the CLI files exactly.
- **F06 maneuver block** — new `f06_writer.py::build_f06_sol144_maneuver_text` (run
  summary, MANEUVER TIME HISTORY table with the critical sample marked, critical-sample
  detail: closure resultant + shared displacement/bar-force blocks). **Key decision
  (user-confirmed):** wired into BOTH the viewer f06 export (`app.py::_render_f06_export`,
  which previously never read `maneuver_result`) and the CLI (`main.py`) for parity — no
  maneuver f06 block had existed anywhere. Full per-sample field data stays in MLDPRNT.
- **All six trim totals** — the backlog's "already computed in sol144.py" claim was wrong:
  only CZ/CX/CMy/CL_wind were stored. `sol144.py` now also computes total CY and the full
  3-component `aero_moment_resultant` roll/yaw moments about the RCSID origin (same
  convention as the CMX/CMZ derivative columns), stored as
  `Sol144TrimResult.total_cy/total_cmx/total_cmz`; shown as a second metrics row in
  `_render_sol144_trim` and added to the f06 AERODYNAMIC TOTALS block.
- **Body-panel visualization** — `build_aero_box_figure(..., body_eids=)` splits the
  wire-frame into "Aero mesh" + purple "Body panels" traces (deflected copies too). A box
  is a body box when `AeroBox.is_strip` (PSTRIP — automatic) or its CAERO EID ∈
  `body_eids`. **Key decision:** cruciform bodies carry no per-box flag, so the Aero
  Correction tab persists the user-selected body EIDs to
  `st.session_state.aero_body_eids` on a successful **Build body correction**; the Aero
  tab and SOL 144 deflected view pass the set through (highlight-EIDs approach — no
  model-layer changes).
- **Run-summary string** — `_summarize_sol144` is bulk-aware: appends "hinge moments"
  (AESURF present), "monitor loads" (MONPNT1/MONPNT3 present), "aero totals"; the MLOADS
  branch now advertises "time histories, MLDPRNT export, critical-sample loads".
  **Key decision:** it stays a PRE-solve summary keyed off cards present, not solved
  result attributes.
- **MLOADS sample deck** — `sample/ha144a_fullspan_mloads.bdf` (none existed): the
  full-span HA144A bulk + MLOADS/MLDTRIM/MLDTIME/MLDCOMD/MLDPRNT/TABLED1; SUBCASE 1 =
  static TRIM 1, SUBCASE 2 = MLOADS ELEV ramp (+0.1 rad over 0.2 s, hold to 1.0 s) — an
  open-loop quasi-steady pitch-up that settles quasi-statically.
- **Viewer doc reconcile** — `docs/10_standard/06_viewer.md`: executive-control section
  now states the SOL 144 BDF-authored/read-only run path and cross-links the SOL 144
  sections; new export buttons, six totals, body-panel colouring, bulk-aware summary,
  session-state key, and testing table documented. `05_aeroelastics.md` + `CLAUDE.md`
  output lists updated.

**Out of scope (unchanged):** SOL 144/MLOADS case-control *authoring* UI — remains a
Future-development backlog item.

**Test/Acceptance:** new `tests/results/test_f06_maneuver.py` (block content, critical
marker, empty-steps), `tests/aero/test_ac5_totals.py` (lateral totals vanish on the
symmetric HA144A trim; CY cross-checked against the per-box force sum; CZ weight-balance
regression), body-panel trace-split tests in `test_aero_view.py`, bulk-aware summary tests
in `test_case_control_summary.py`, and AppTest Flow D
(`test_flow_d_sol144_mloads_render_and_run`: MLOADS deck end-to-end — six totals visible,
maneuver subcase renders time history/slider/exports). CLI run of the new sample verified
(f06 trim + maneuver blocks, MLDPRNT, critical-load BDF, physically sane ELEV-ramp
response). Full suite 1075 passed / 6 xfailed.

---

