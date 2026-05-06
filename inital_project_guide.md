# Simple Beam FEA — Development Plan

> **Note:** This is the living development plan and project backlog for `sbeam`.
> Phase 1 solver and viewer steps (1–25) are implemented. Four known defects and incomplete
> features remain (B1–B4 in the Phase 7 cleanup section) and should be resolved before Phase 2
> dynamic-response work begins.
>
> Refer to the subsystem documentation for full technical specification:
> `sbeam.md`, `Beam_model.md`, `Static_analysis.md`, `Modal_analysis.md`, `viewer.md`

---

## Principles

- Each step produces working, testable code before the next step begins.
- Steps are small enough to complete and verify in a single session.
- Every step that adds solver logic must have an analytical verification case.
- The viewer is developed in parallel with the solver — each solver step has a corresponding display step.
- Documentation is updated as part of each step, not after.
- **The Streamlit viewer (`viewer/app.py`) is the primary entry point for all interactive use.** The CLI (`main.py`) is a secondary, batch-mode interface for automation and headless runs. It is implemented last because it adds no new logic — it simply chains existing components.

---

## Phase 1 — Project Setup

### Step 1: Repository and Project Skeleton ✅ COMPLETE

**Objective:** Establish the directory structure, dependencies, and empty module files so all subsequent steps have a consistent layout to build into.

**Deliverables:**
- `sbeam/` directory tree matching `sbeam.md` module structure (empty `__init__.py` files, placeholder modules)
- `requirements.txt` (numpy, scipy, pandas, plotly, streamlit)
- `tests/` directory mirroring `sbeam/` structure
- `pytest.ini` or `pyproject.toml` test configuration

> **Note on `main.py`:** This is a thin CLI wrapper (`python main.py run.bdf`) that reads a run file via `parse_bdf()`, dispatches to the appropriate solver, and writes a `.f06`. It is left as a placeholder stub until after the solver and viewer are complete, because it adds no new logic. The viewer is the canonical interface throughout development.

**Test / Acceptance:**
- `pip install -r requirements.txt` completes without error.
- `pytest tests/` runs and reports "no tests collected" (not an error).
- `python -c "import sbeam"` succeeds.

**Documentation update:** None required (structure described in `sbeam.md` already).

---

### Step 2: Data Model — BDF Card Dataclasses ✅ COMPLETE

**Objective:** Define Python dataclasses for all Phase 1 BDF cards. No parsing yet — just the data structures that the parser will populate and the solver will consume.

**Deliverables:**
- `model/grid.py` — `Grid` dataclass (gid, x, y, z, ps)
- `model/element.py` — `Cbar`, `Plotel`, `Rbe3` dataclasses
- `model/property.py` — `Pbar` dataclass (pid, mid, A, I1, I2, J, NSM, recovery points)
- `model/material.py` — `Mat1` dataclass (mid, E, G, nu, rho)
- `model/load.py` — `Force`, `Moment`, `Load` dataclasses
- `model/constraint.py` — `Spc`, `Spc1` dataclasses
- `model/mass.py` — `Conm2` dataclass
- `model/bulk_data.py` — `BulkData` container dataclass holding dicts of all above
- `parser/case_control.py` — `SubcaseControl`, `CaseControl` dataclasses

**Test / Acceptance:**
- Instantiate each dataclass with representative values; no exceptions.
- All fields have correct types and defaults.
- `BulkData` can be constructed empty and have cards added to its dicts.

---

## Phase 2 — BDF Parser

### Step 3: Parser — Geometry and Properties ✅ COMPLETE

**Objective:** Read GRID, PBAR, MAT1 cards from a bulk data section into a `BulkData` object.

**Deliverables:**
- `parser/bdf_reader.py` — free-field and fixed-field BDF line parsing; `GRID`, `PBAR`, `MAT1` card handlers.
- `tests/parser/test_geometry.py`

**Test / Acceptance:**
- Parse a hand-written 3-node, 2-element BDF snippet. Verify GIDs, coordinates, property, and material values match input exactly.
- Duplicate GID raises `ValueError`.
- Unknown card issues `warnings.warn` and is skipped.

---

### Step 4: Parser — Elements ✅ COMPLETE

**Objective:** Add CBAR, PLOTEL, and CONM2 card parsing.

**Deliverables:**
- `bdf_reader.py` extended with `CBAR`, `PLOTEL`, `CONM2` handlers (including orientation vector X1/X2/X3 and pin flags PA/PB).
- `tests/parser/test_elements.py`

**Test / Acceptance:**
- Parse a cantilever model BDF (5 CBAR elements); verify EIDs, GA/GB, PID, orientation vector, and pin flags.
- CBAR referencing a non-existent GRID raises `ValueError`.
- CBAR referencing a non-existent PID raises `ValueError`.
- More than 200 CBAR elements raises `ValueError`.

---

### Step 5: Parser — Loads and Constraints ✅ COMPLETE

**Objective:** Add SPC/SPC1, FORCE, MOMENT, LOAD, and EIGRL card parsing.

**Deliverables:**
- `bdf_reader.py` extended with `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `EIGRL` handlers.
- `tests/parser/test_loads.py`

**Test / Acceptance:**
- Parse a model with two load sets, one SPC set, and an EIGRL. Verify all SIDs and values.
- LOAD card referencing a non-existent component SID raises `ValueError`.
- DOF string "0" (invalid) raises `ValueError`.

---

### Step 6: Parser — Case Control and INCLUDE ✅ COMPLETE

**Objective:** Parse the case control section (above `BEGIN BULK`) and the `INCLUDE` statement for the bulk data file. Also add a bulk-data-only loader so the viewer can open model files before any case control has been defined.

**Deliverables:**
- `parser/case_control.py` — parser for `SOL`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, output request cards, `INCLUDE`.
- `bdf_reader.py` — `parse_bdf(filepath)` top-level function: reads case control, follows INCLUDE to load bulk data, returns `(CaseControl, BulkData)`.
- `bdf_reader.py` — `parse_bulk_file(filepath)` function: reads a bulk-data-only file (with or without a `BEGIN BULK` header), returns `BulkData`. Does **not** require or call `parse_case_control()`.
- `tests/parser/test_case_control.py`

The two top-level functions serve distinct use cases:

| Function | Input | Returns | Requires SOL |
|----------|-------|---------|--------------|
| `parse_bdf(filepath)` | Run file with case control | `(CaseControl, BulkData)` | Yes — raises `ValueError` |
| `parse_bulk_file(filepath)` | Bulk-data file (`.dat` or `.bdf`) | `BulkData` | No |

**Test / Acceptance:**
- Parse a complete two-file model (run.bdf + model.dat) end-to-end. Verify SOL, subcase IDs, LOAD SIDs, SPC SIDs, and METHOD SIDs resolve correctly.
- Missing INCLUDE file raises `FileNotFoundError`.
- SOL value other than 101 or 103 raises `ValueError` (phase 1 scope).
- `parse_bulk_file()` on a raw bulk-data `.dat` file (no `SOL`, no `BEGIN BULK`) returns correct `BulkData` with no exception.
- `parse_bulk_file()` on a `.bdf` file that has a `BEGIN BULK` header but no case control returns correct `BulkData` with no exception.

---

## Phase 3 — Static Solver (SOL 101)

### Step 7: Element Stiffness Matrix ✅ COMPLETE

**Objective:** Implement the 12×12 Euler-Bernoulli local element stiffness matrix and the coordinate transformation matrix for a CBAR element.

**Deliverables:**
- `assembly/stiffness.py` — `local_stiffness(pbar, mat1, L)`, `transform_matrix(cbar, grids)`, `element_stiffness_global(cbar, grids, pbars, mat1s)`.
- `tests/assembly/test_stiffness.py`

**Test / Acceptance:**
- Axial-only element (I1=I2=J=0): verify K matches the 2-DOF axial stiffness `EA/L`.
- Pure bending element (A=0, I2=J=0): verify 4×4 bending sub-matrix matches Euler-Bernoulli beam bending stiffness terms exactly.
- Full 12×12 matrix is symmetric: `K == K.T` within 1e-12.
- Transformation: element aligned with global X axis — transform produces same matrix as local.
- Element at 45° to global axes: transformation preserves symmetry and all eigenvalues remain non-negative.

---

### Step 8: Global Stiffness Assembly ✅ COMPLETE

**Objective:** Assemble the global stiffness matrix from all CBAR elements.

**Deliverables:**
- `assembly/stiffness.py` — `assemble_global_stiffness(bulk: BulkData) -> np.ndarray`.
- `tests/assembly/test_global_stiffness.py`

**Test / Acceptance:**
- 1-element cantilever: assembled 12×12 global K is symmetric and positive semi-definite.
- 2-element collinear cantilever: assembled 18×18 K is symmetric. Compare against hand-assembled result.
- DOF ordering: verify that grid index mapping (`6*i + d`) places values at correct rows/columns.

---

### Step 9: Load Vector and SPC Assembly ✅ COMPLETE

**Objective:** Assemble the global load vector from FORCE/MOMENT/LOAD cards and apply SPC constraints by DOF elimination.

**Deliverables:**
- `assembly/load_vector.py` — `assemble_load_vector(bulk, load_sid)`.
- `assembly/stiffness.py` extended — `apply_spcs(K, f, spc_dofs) -> (K_free, f_free, free_dofs)`.
- `tests/assembly/test_loads.py`

**Test / Acceptance:**
- Point force in Y at tip grid: verify DOF `6*tip_index + 1` equals the force value; all others zero.
- LOAD combination (S=1.0, two component sets): verify superposition.
- SPC elimination: constrained DOFs removed from K and f; K_free size is `(6N - n_spc) × (6N - n_spc)`.
- K_free is positive definite after applying full cantilever SPCs.

---

### Step 10: SOL 101 Solve and Displacement Recovery ✅ COMPLETE

**Objective:** Solve `K_free u_free = f_free`, reconstruct full displacement vector.

**Deliverables:**
- `solver/sol101.py` — `solve_static(K_free, f_free, free_dofs, n_dofs) -> np.ndarray`.
- `tests/solver/test_sol101.py`

**Test / Acceptance:**
- **Cantilever, tip load P in Y, single element:**
  - Tip Ty = PL³/3EI ± 0.1%
  - Tip Rz = PL²/2EI ± 0.1%
- **Simply supported beam, mid-span load (10 elements):**
  - Mid-span Ty = PL³/48EI ± 0.1%
- Singular K_free raises `ValueError` with message identifying unconstrained DOFs.

---

### Step 11: SOL 101 Post-Processing ✅ COMPLETE

**Objective:** Recover CBAR end forces/moments and stresses, and SPC reaction forces.

**Deliverables:**
- `results/results.py` — `Sol101Result` dataclass (displacements, reactions, bar_forces, bar_stresses).
- `solver/sol101.py` extended — `recover_bar_forces(...)`, `recover_bar_stresses(...)`, `recover_reactions(...)`.
- `tests/solver/test_sol101_recovery.py`

**Test / Acceptance:**
- Cantilever, tip load P:
  - Fixed-end bending moment = P×L ± 0.1%.
  - Shear force along beam = P (constant) ± 0.1%.
  - Reaction forces at fixed end sum to P in Y and P×L as moment.
- Stress at recovery point C on PBAR: sigma = M×z/I ± 0.1% (with known z from PBAR).
- Sum of all SPC reactions equals negative of applied load (equilibrium check).

---

### Step 12: .f06 Output — SOL 101 ✅ COMPLETE

**Objective:** Write SOL 101 results to a NASTRAN-style `.f06` text file.

**Deliverables:**
- `results/f06_writer.py` — `write_f06_sol101(filepath, case_control, bulk, result)`.
- `tests/results/test_f06_sol101.py`

**Test / Acceptance:**
- Output file contains expected section headers (DISPLACEMENT, SPCFORCE, BAR FORCES, BAR STRESSES).
- Parse the written file and verify numeric values round-trip within print precision (6 significant figures).
- File is human-readable and sections are separated as per NASTRAN f06 convention.

---

### Step 13: GPWG — Mass and CG ✅ COMPLETE

**Objective:** Compute total structural mass and centre of gravity from the BulkData.

**Deliverables:**
- `gpwg.py` — `compute_gpwg(bulk: BulkData) -> GpwgResult` (total_mass, cg_x, cg_y, cg_z).
- `tests/test_gpwg.py`

**Test / Acceptance:**
- 1-element beam (rho, A, L known): total mass = rho × A × L ± 0.01%.
- CONM2 at tip: total mass = element mass + point mass; CG shifts toward tip.
- Zero-density model (rho=0, no CONM2): total mass = 0; CG = (0, 0, 0).

---

## Phase 4 — Modal Solver (SOL 103)

### Step 14: Consistent Mass Matrix ✅ COMPLETE

**Objective:** Implement the 12×12 consistent mass matrix for a CBAR element and assemble the global mass matrix.

**Deliverables:**
- `assembly/mass_matrix.py` — `local_mass(pbar, mat1, L)`, `element_mass_global(cbar, grids, pbars, mat1s)`, `assemble_global_mass(bulk)`.
- `tests/assembly/test_mass.py`

**Test / Acceptance:**
- Single element: total mass `= rho × A × L`; verify by summing appropriately-weighted diagonal terms.
- Global mass matrix is symmetric and positive definite for a model with non-zero density.
- CONM2 mass added to correct translational DOF diagonal entries.
- Transform of mass matrix preserves total mass (trace invariance check).

---

### Step 15: SOL 103 Eigenvalue Solve ✅ COMPLETE

**Objective:** Solve the generalised eigenvalue problem and extract natural frequencies and mode shapes.

**Deliverables:**
- `solver/sol103.py` — `solve_modes(K_free, M_free, eigrl) -> (frequencies_hz, mode_shapes)`.
- `results/results.py` extended — `Sol103Result` dataclass.
- `tests/solver/test_sol103.py`

**Test / Acceptance:**
- **Cantilever beam, 10 elements:**
  - f₁ = (1.8751²/2π) × √(EI/ρAL⁴) ± 1%.
- **Free-free beam (no SPC), 10 elements:**
  - First 6 eigenvalues < 1e-4 Hz (rigid body modes).
  - 7th mode is the first elastic mode.
- **Simply supported beam, 10 elements:**
  - f₁ = (π²/2πL²) × √(EI/ρA) ± 1%.
- MASS normalisation: `phi^T M phi = I` (identity matrix) within 1e-10.
- MAX normalisation: maximum absolute component of each mode = 1.0.

---

### Step 16: .f06 Output — SOL 103 ✅ COMPLETE

**Objective:** Write SOL 103 results to .f06 format.

**Deliverables:**
- `results/f06_writer.py` extended — `write_f06_sol103(filepath, case_control, bulk, result)`.
- `tests/results/test_f06_sol103.py`

**Test / Acceptance:**
- Output file contains REAL EIGENVALUE table (mode number, eigenvalue, frequency Hz).
- Mode shape tables present for each mode.
- Numeric round-trip within print precision.

---

## Phase 5 — Viewer

### Step 17: Viewer — Model Load and 3D Display ✅ COMPLETE

**Objective:** Build the Streamlit app skeleton with file upload, BDF parsing, and basic Plotly 3D model display. The viewer must handle **both** bulk-data-only files and full run files (case control + bulk data).

**Deliverables:**
- `viewer/app.py` — page routing, session state initialisation.
  - `_has_case_control(content: str) -> bool` helper: scans lines before `BEGIN BULK` for a `SOL` statement (ignoring `$` comments). Five lines of code.
  - `_handle_upload()` dispatcher: if `_has_case_control()` returns `True`, call `parse_bdf()` and store both `CaseControl` and `BulkData`; otherwise call `parse_bulk_file()` and store only `BulkData` with `CaseControl = None`.
  - Parse summary shows SOL type and subcase count when case control is loaded; shows a caption "No case control — define via Case Control tab" when loading bulk-data-only.
- `viewer/geometry.py` — Plotly 3D figure: GRID scatter, CBAR lines, PLOTEL dashed lines.
- `tests/viewer/test_geometry.py` (unit test on figure data, not UI).
- `sample/simple_beam.dat` — bulk-data-only version of `simple_beam.bdf` (case control section stripped), for demonstrating the geometry-only upload path.

**Test / Acceptance (manual):**
- Upload `sample/simple_beam.bdf` (combined run file); model renders in 3D; parse summary shows `SOL 101` and subcase count.
- Upload a bulk-data-only `.dat` file (no `SOL`); model renders in 3D; parse summary shows "No case control" caption; no error banner.
- Upload `sample/simple_beam.dat` (bulk data only, no case control): model renders, "No case control" caption shown, load sets = 1, SPC sets = 1; no error banner.
- Hover over a GRID shows GID and coordinates.
- Hover over a CBAR shows EID and property summary.
- PLOTEL elements visually distinct from CBAR elements.

**Iteration checkpoint:** Review display quality, adjust Plotly trace styles, colours, label placement before proceeding.

---

### Step 18: Viewer — Model Interrogation Panel ✅ COMPLETE

**Objective:** Add tabbed properties panel and GPWG summary.

**Deliverables:**
- `viewer/geometry.py` extended — click-to-select grid/element; selected item details shown in sidebar.
- Tables: Grids, Elements, Properties, Materials, Loads, Constraints.
- GPWG summary panel (total mass, CG).

**Test / Acceptance (manual):**
- Click on a node: sidebar shows GID, X, Y, Z, SPC status.
- Click on an element: sidebar shows EID, GA, GB, L, PBAR and MAT1 data.
- GPWG panel shows correct total mass and CG for the loaded model.

**Iteration checkpoint:** Confirm interaction model is usable before building the case control UI on top.

---

### Step 19: Viewer — Case Control UI and BDF Export ✅ COMPLETE

**Objective:** Build the case control form and BDF export capability.

**Deliverables:**
- `viewer/case_control_ui.py` — Streamlit form: SOL, TITLE, SUBCASE, LOAD dropdown, SPC dropdown, METHOD dropdown (SOL 103), output request checkboxes, INCLUDE path, Add Subcase, Export buttons.
- Export writes a valid `*.bdf` case control file with INCLUDE statement.

**Test / Acceptance:**
- Export a SOL 101 subcase BDF; parse it back through `parser/bdf_reader.py`; verify round-trip produces same `CaseControl` object.
- Export a SOL 103 subcase BDF; verify METHOD and EIGRL are present.
- LOAD and SPC dropdowns are populated from available SIDs in the loaded model.

---

### Step 20: Viewer — Run Analysis In-Process ✅ COMPLETE

**Objective:** Add a Run Analysis button that calls the solver directly from the viewer and loads results into session state.

**Deliverables:**
- `viewer/app.py` extended — Run button calls `sol101.run_sol101` or `sol103.run_sol103`; result stored in session state.
- Error banners for solver failures.

**Test / Acceptance (manual):**
- Load cantilever model, define SOL 101 case, click Run; no error; session state contains `Sol101Result`.
- Deliberate error (no SPC defined): red error banner with message, no crash.

---

### Step 21: Viewer — SOL 101 Results Display ✅ COMPLETE

**Objective:** Display deformed shape and results tables for SOL 101.

**Deliverables:**
- `viewer/results_view.py` — deformed shape overlay on Plotly 3D figure; scale factor slider; displacement, reaction, bar force, and stress tables.

**Test / Acceptance (manual):**
- Cantilever tip load: deformed shape curves toward applied load direction.
- Scale factor slider changes deformation magnitude; model does not distort at extreme values.
- Displacement table values match `.f06` output.
- Results tables are sortable and searchable.

**Iteration checkpoint:** Validate visual output against analytical cantilever deflection shape before proceeding to SOL 103 display.

---

### Step 22: Viewer — SOL 103 Results Display ✅ COMPLETE

**Objective:** Display mode shapes for SOL 103 with mode selector and animation.

**Deliverables:**
- `viewer/results_view.py` extended — mode selector dropdown; animated mode shape (Plotly animation frames cycling ±max); frequency display; modal mass fraction bar chart.

**Test / Acceptance (manual):**
- First bending mode of cantilever: animated shape shows correct first-mode curvature.
- Mode selector cycles through all extracted modes without error.
- Frequency displayed in Hz matches `.f06` output.
- Rigid body modes (free-free) are labelled as such.

**Iteration checkpoint:** Confirm animation performance is acceptable in Streamlit before integration step.

---

## Phase 6 — Integration and Verification

### Step 23: Pin Releases (PA/PB) ✅ COMPLETE

**Objective:** Implement CBAR pin releases in the element stiffness matrix.

**Deliverables:**
- `assembly/stiffness.py` extended — apply PA/PB by zeroing released DOF rows/columns in local `[k_e]` before transformation.
- `tests/assembly/test_pin_releases.py`

**Test / Acceptance:**
- Beam with both ends pinned in bending (PA=PB="456"): element provides axial and torsional stiffness only; bending stiffness terms are zero.
- Simple truss-like model using pinned CBAR elements: tip deflection matches truss analytical solution.

---

### Step 24: End-to-End Integration Tests ✅ COMPLETE

**Objective:** Verify the complete workflow from BDF file input to `.f06` output for all verification cases.

**Deliverables:**
- `tests/integration/` — BDF input files for each verification case.
- `tests/integration/test_verification.py` — automated pass/fail against analytical values.

**Verification cases (all must pass before release):**

| ID | Model | SOL | Check | Tolerance |
|----|-------|-----|-------|-----------|
| V1 | Cantilever, tip load P | 101 | Tip deflection = PL³/3EI | < 0.1% |
| V2 | Cantilever, tip load P | 101 | Fixed-end moment = PL | < 0.1% |
| V3 | Simply supported, mid-span load | 101 | Mid deflection = PL³/48EI | < 0.1% |
| V4 | Fixed-fixed, UDL (nodal approx.) | 101 | Reactions sum to total load | < 0.1% |
| V5 | Cantilever | 103 | f₁ = (1.8751²/2π)√(EI/ρAL⁴) | < 1% |
| V6 | Free-free beam | 103 | First 6 modes < 1e-4 Hz | — |
| V7 | Simply supported | 103 | f₁ = (π²/2πL²)√(EI/ρA) | < 1% |
| V8  | Massless CBAR + CONM2 i11 | 103 | f = √(GJ/L·I11)/(2π) | < 1% |
| V9  | Massless CBAR + CONM2 x1 offset + i22 | 103 | Coupled 2-DOF f₁, f₂ | < 1% |
| V10 | Zero-density cantilever + tip CONM2 | 103 | f = √(3EI/mL³)/(2π) | < 1% |
| V11 | Cantilever tip torque | 101 | θ_x = T·L/(G·J) | < 0.1% |
| V12 | Massless CBAR + CONM2 transverse offset | 103 | f = √(GJ/L·m·d²)/(2π) | < 1% |

---

### Step 25: Documentation Finalisation

**Objective:** Ensure all documentation is current, consistent with the implemented code, and ready for handover.

**Deliverables:**
- `Methods.ipynb` — analytical derivations for Euler-Bernoulli stiffness matrix, consistent mass matrix, coordinate transformation, eigenvalue solution. Developed incrementally through the project; finalised here.
- Review and update `sbeam.md`, `Beam_model.md`, `Static_analysis.md`, `Modal_analysis.md`, `viewer.md` for any implementation details that changed during development.
- Revise `inital_project_guide.md`: remove the "should be deleted" note; add Phase 7 section capturing known bugs, Phase 2 scope, and future development backlog so it remains the active project roadmap.

---

## Dependency Map

```
Step 1  (setup)
  └─ Step 2  (dataclasses)
       └─ Step 3  (parser: geometry/properties)
            └─ Step 4  (parser: elements)
                 └─ Step 5  (parser: loads/constraints)
                      └─ Step 6  (parser: case control + INCLUDE)
                           │        ├─ parse_bdf()        ──────────────────────────────────┐
                           │        └─ parse_bulk_file()  ──► Step 17 (viewer: model load)  │
                           ├─ Step 7  (element stiffness) ◄────────────────────────────────┘
                           │    └─ Step 8  (global stiffness)
                           │         └─ Step 9  (load vector + SPC)
                           │              └─ Step 10 (SOL 101 solve)
                           │                   └─ Step 11 (SOL 101 post-processing)
                           │                        ├─ Step 12 (f06 SOL 101)
                           │                        ├─ Step 13 (GPWG)
                           │                        └─ Step 23 (pin releases)
                           ├─ Step 14 (mass matrix)
                           │    └─ Step 15 (SOL 103 solve)
                           │         └─ Step 16 (f06 SOL 103)
                           └─ Steps 17–22 (viewer, parallel with solver steps)
                                └─ Step 24 (integration verification)
                                     └─ Step 25 (documentation finalisation)
```

---

## Reference Material

- NASA-CR-145949
- https://www.sesamx.io/blog/beam_finite_element/
- https://mechanicalc.com/reference/finite-element-analysis

---

## Phase 7 — Backlog: Phase 1 Cleanup, Phase 2, and Future Development

> This section is the active project roadmap. Add new items here as they are identified.
> When a backlog item is promoted to a formal step, give it a step number continuing from Step 25
> and apply the same step format (Objective, Deliverables, Test/Acceptance).

---

### Phase 1 Cleanup

These items represent defects and incomplete scope within Phase 1. Resolve before starting Phase 2.

**Recommended fix order: B3 → B1 → B4 (close as doc-only)**

#### Known Bugs

| ID | Area | Description |
|----|------|-------------|
| B1 | Viewer — Case Control UI | Case control BDF export produces incorrect output in some configurations. Root cause: Streamlit form reads widget values from `st.session_state.cc_subcases` at Submit time, but widget values (selectbox, checkbox) may not have been committed to that list yet. **Fix:** at Submit time, read values directly from widget keys (`st.session_state[f"sc_load_{idx}"]`, etc.) rather than from the pre-existing session state list. **Acceptance:** define a multi-subcase case control, modify SID dropdowns, export BDF, parse back through `parse_bdf()`, assert round-trip equality. |
| B2 ✅ | Viewer — Results display | **FIXED.** Deformed-node trace in `build_deformed_figure` now carries `customdata=[gid, Tx, Ty, Tz]` and a `hovertemplate` showing raw physical displacements. Hover no longer shows scaled coordinates. |
| B3 | Solver — Multi-subcase | **Highest priority — correctness bug.** Both `run_sol101` and `run_sol103` silently use only `case_control.subcases[0]`. **Fix:** change both functions to accept a single `SubcaseControl` argument; update `_run_analysis` in `viewer/app.py` to loop over all subcases and collect `dict[subcase_id, Sol101Result]` / `dict[subcase_id, Sol103Result]`; update session state and viewer (`results_view.py`) to show a subcase selector with per-subcase results. **Acceptance:** define a 2-subcase SOL 101 case; both subcases appear in the results dropdown with independent, correct displacement values. |
| B4 | Viewer — f06 import | **Resolve by closing (doc-only).** `viewer.md` documents a post-processing path that accepts an uploaded `.f06` file and populates results from it. This feature was never implemented and is out of scope for Phase 1. **Resolution:** remove the f06 import description from `viewer.md`; the "NASTRAN f06 import" item already exists in the Future Development table below and will be addressed there. No code changes required. |

---

### Phase 2 — Dynamic Response Solvers

Phase 2 adds frequency- and time-domain response to the existing static and modal capability.
All Phase 2 solvers build on the Phase 1 stiffness, mass, and modal results infrastructure.

#### Step 26: SOL 108 — Direct Frequency Response

**Objective:** Solve the steady-state harmonic response `([K] - ω²[M]){U} = {F(ω)}` over a
user-defined frequency range.

**Scope:**
- `DLOAD` / `RLOAD1` / `RLOAD2` cards for frequency-dependent loading.
- `FREQ` / `FREQ1` card for the excitation frequency set.
- `SDAMPING` or structural damping via MAT1 GE field.
- Results: complex displacement amplitude and phase per DOF per frequency.
- `.f06` output: frequency response table (real/imaginary or amplitude/phase).
- Viewer: frequency response function (FRF) plot — amplitude vs frequency for selected DOF.

---

#### Step 27: SOL 109 — Direct Transient Response

**Objective:** Solve the time-domain equation `[M]{ü} + [C]{u̇} + [K]{u} = {F(t)}` via
numerical time integration.

**Scope:**
- `TLOAD1` / `TLOAD2` cards for time-dependent loading.
- `TSTEP` card for time step and output interval.
- Newmark-β integration (β=0.25, γ=0.5 — unconditionally stable).
- Results: displacement, velocity, acceleration history per DOF.
- Viewer: time-history plot for selected DOF.

---

#### Step 28: SOL 111 — Modal Frequency Response

**Objective:** Modal superposition frequency response using SOL 103 mode shapes as basis.

**Scope:**
- Requires prior SOL 103 result (or run internally).
- Modal damping via TABDMP1 or critical damping ratio per mode.
- More efficient than SOL 108 for structures with many DOFs and few modes.
- Same output requests as SOL 108.

---

#### Step 29: SOL 112 — Modal Transient Response

**Objective:** Modal superposition transient response using SOL 103 mode shapes as basis.

**Scope:**
- Same modal basis and damping as SOL 111.
- Newmark-β integration in modal coordinates.
- More efficient than SOL 109 for lightly damped structures.
- Same output requests as SOL 109.

---

### Phase 2 — Model Enhancements

These items extend the BDF card support and solver capability. They are independent of the
dynamic response solvers and can be tackled in any order.

#### Step 30: Distributed Loads (PLOAD1)

**Objective:** Apply linearly-varying or uniform distributed loads along CBAR elements.

**Scope:**
- `PLOAD1` card: EID, load type (FX/FY/FZ/MX/MY/MZ in local or global), scale, x1/p1, x2/p2.
- Equivalent nodal load vector via integration of the distributed load against shape functions.
- Viewer: distributed load visualisation along element (hatching or shaded arrow strip).

**Why this matters:** uniform distributed loads (self-weight, wind pressure, snow) are the
most common beam load in bridge, building, and wing models.

---

#### Step 31: Gravity and Inertial Body Loads (GRAV)

**Objective:** Apply a body acceleration load to all mass-bearing DOFs, enabling self-weight
analysis without manually computing and applying nodal forces.

**Scope:**
- `GRAV` card: SID, CID (phase 2: CID=0 only), N1/N2/N3 acceleration vector, G (magnitude in units/s²).
- Applied load = mass × acceleration, assembled from CBAR element distributed mass and CONM2 masses.
- GRAV can be combined with FORCE/MOMENT sets via a `LOAD` combination card.
- `.f06` output: echo GRAV card in applied-load section.
- Viewer: display gravity arrow in model view when GRAV is the active load.

**Why this matters:** self-weight is the primary load in bridge, building, and landing-gear
models. It is also used for aircraft 1g manoeuvre load cases and qualification test simulations.

**Verification:** 1g vertical load on a simply-supported beam; reactions = total structural mass × g.

---

#### Step 32: Local Coordinate Systems (CID ≠ 0)

**Objective:** Support user-defined rectangular coordinate systems for grid input and load
application.

**Scope:**
- `CORD2R` card (rectangular coordinate system defined by three points).
- `GRID` CP and CD fields — transform input coordinates and output results to/from local CID.
- `FORCE` / `MOMENT` CID field — apply loads in a local system.
- Coordinate system manager in the parser.

**Why this matters:** needed for angled frames, grid-based building models, and inclined
support conditions where local orientations differ from global.

---

#### Step 33: Timoshenko Shear Correction (PBAR K1/K2)

**Objective:** Include transverse shear deformation for stocky beam members.

**Scope:**
- `PBAR` K1 and K2 fields (shear area factors).
- Modified stiffness matrix: Timoshenko beam with shear parameter `φ = 12EI/(κAGL²)`.
- Falls back to Euler-Bernoulli when K1=K2=0 (or blank).
- Verification: short cantilever (L/d = 2) with known Timoshenko tip deflection.

**Why this matters:** important for short, deep members common in bridges and building frames.
Euler-Bernoulli overestimates stiffness significantly when L/d < 10.

---

#### Step 34: Non-Zero Enforced Displacements

**Objective:** Support prescribed non-zero displacements at SPC-constrained DOFs.

**Scope:**
- `SPC` D1/D2 fields (currently must be 0 in Phase 1).
- Modify load vector assembly: move non-zero SPC terms to RHS before partitioning.
- Verification: beam with prescribed end rotation reproducing known deflection shape.

**Why this matters:** foundation settlement, support yielding, and displacement-controlled
loading are standard structural assessment scenarios.

---

#### 


**Objective:** Full CONM2 support with offset vector and 3×3 inertia tensor.

**Scope:**
- `CONM2` X1/X2/X3 offset fields and I11/I21/I22/I31/I32/I33 inertia terms.
- Offset mass contributes to both translational and rotational DOFs via the parallel-axis theorem.
- Verification: off-axis point mass eigenfrequency compared to analytical value.

**Why this matters:** payload/fuel mass in aircraft stick models is almost never located
exactly at a grid point.

---

#### Step 36: RBE2 — Rigid Element

**Objective:** Support the `RBE2` rigid element connecting a single independent grid to one
or more dependent grids with fully rigid (or DOF-selective) coupling.

**Scope:**
- `RBE2` card: EID, GN (independent grid), CM (coupled DOF string), GM1, GM2, … (dependent grids).
- Implement via the same DOF transformation approach used for RBE3 (`assembly/rbe3.py`): each
  dependent DOF in CM is constrained to equal the corresponding DOF at GN.
- Works in both SOL 101 and SOL 103.
- Viewer: display RBE2 connections as solid red lines from GN to each GM (distinct from RBE3 dashed).
- Verification: two-span beam with a rigid link; tip displacement matches analytical value.

**Why this matters:** rigid connections between beam axes are needed for aircraft frame joints,
eccentrically attached stiffeners, and building column–beam rigid connections.

---

#### Step 37: CBUSH — Spring and Damper Element

**Objective:** Implement the `CBUSH` generalised spring-damper element and its associated
`PBUSH` property card, enabling stiffness connections in up to 6 independent DOFs.

**Scope (Phase 2):**
- `CBUSH` card: EID, PID, GA, GB (blank = grounded at GA), X1/X2/X3 orientation vector.
  - CID=0 (global system) only — user coordinate systems deferred to Step 32.
  - Offset fields (S, OCID, S1–S3) not supported in Phase 2.
- `PBUSH` card: PID, K1–K6 stiffness values (any may be 0/blank). Viscous damping B1–B6
  deferred to the dynamic solvers (SOL 108/109).
- Stiffness matrix: 6×6 diagonal local matrix `diag(K1, K2, K3, K4, K5, K6)`. For a
  two-node element, assembled into a 12×12 element matrix:
  ```
  K_e = [ K_local  -K_local ]
        [-K_local   K_local ]
  ```
  For a grounded element (GB blank), 6×6 at GA only. Transformed to global via
  `T^T @ K_e @ T` using the same rotation-matrix approach as CBAR.
- Element X-axis = unit vector GA→GB (non-coincident nodes). The X1/X2/X3 vector defines
  the XZ-plane (equivalent to the CBAR v-vector). Coincident nodes require X1/X2/X3.
- CBUSH is massless; CONM2 remains the mass source.
- Works in SOL 101 and SOL 103.

**Deliverables:**
- `model/element.py` — `Cbush` dataclass (eid, pid, ga, gb, x).
- `model/property.py` — `Pbush` dataclass (pid, k[6]).
- `model/bulk_data.py` — add `cbushs: dict[int, Cbush]` and `pbushs: dict[int, Pbush]`.
- `parser/bdf_reader.py` — `CBUSH` and `PBUSH` card handlers; raise `ValueError` if PID or
  GA references a non-existent card; raise `ValueError` if nodes are coincident and no
  orientation vector or CID is provided.
- `assembly/stiffness.py` — `cbush_stiffness_global(cbush, grids, pbushs)`;
  extend `assemble_global_stiffness` to include CBUSH contributions.
- `solver/sol101.py` — `recover_cbush_forces(bulk, u_full)` returning `dict[eid, np.ndarray(6)]`
  (element local forces F1–F3, M1–M3).
- `results/results.py` — add `cbush_forces: dict[int, np.ndarray]` to `Sol101Result`.
- `results/f06_writer.py` — "CBUSH ELEMENT FORCES" table section in SOL 101 output.
- `viewer/geometry.py` — render CBUSH as a zigzag (spring-coil) polyline between GA and GB,
  visually distinct from CBAR and PLOTEL; hover shows EID, GA, GB, K1–K6.
- `viewer/app.py` — add PBUSH table in the Properties data tab.
- `tests/assembly/test_cbush.py`, `tests/parser/test_cbush.py`.
- `CLAUDE.md` supported cards table — add CBUSH and PBUSH rows.

**Test / Acceptance:**
- Single CBUSH, K1 only (axial), SPC at GA: applied force F at GB → displacement = F/K1 ± 0.01%.
- Single CBUSH, K4 only (torsional): applied moment M at GB → rotation = M/K4 ± 0.01%.
- Grounded CBUSH (GB blank): single grid spring to ground; stiffness assembled to GA DOFs only.
- CBUSH at 45° to global X-axis: stiffness in global frame matches hand-transformed result.
- Mixed model — CBAR cantilever with CBUSH at mid-span support: tip deflection matches
  analytical two-spring-in-series solution ± 0.1%.
- Unknown PID raises `ValueError`. Coincident nodes with no orientation raises `ValueError`.

**Why this matters:** CBUSH is the most commonly used spring element in NASTRAN models.
It is required for fasteners, bolt patterns, structural joints, bushing connections, landing
gear, and any connection where translational and rotational stiffness must be specified
independently. Without CBUSH, structural connections can only be modelled using artificially
stiff CBAR stubs, which distort mode shapes and static deflections.

**Reference:**
- https://www.stressebook.com/spring-elements-in-nastran/
- Altair HyperWorks: CBUSH and PBUSH bulk data card definitions.

---

### Future Development (Phase 3+)

These items are lower priority or require significant new infrastructure. Record them here
so they are not lost.

| Item | Description | Prerequisite |
|------|-------------|--------------|
| SOL 105 — Buckling | Solve `([K] + λ[K_G]){φ} = 0` for critical load factor; requires geometric stiffness matrix assembled from SOL 101 axial forces | SOL 101 complete |
| Sparse solver | Replace `numpy.linalg.solve` with `scipy.sparse.linalg.spsolve`; removes the 200-element ceiling | None |
| Results export (CSV/Excel) | Download displacement, force, stress tables from the viewer as spreadsheets | Viewer complete |
| Load case envelope | Post-processing: display max/min results across all subcases in a single table; requires B3 (multi-subcase) to be fixed first | B3 fix |
| PBARL | Define PBAR cross-section by standard shape (ROD, BAR, BOX, I, L, T, …) with auto-computed A, I, J | Parser |
| Parametric sweep | Vary a geometry or material parameter and plot response curve (e.g. frequency vs stiffness) | SOL 103 complete |
| MAT1 thermal fields | GE (structural damping) already parsed but unused; A and TREF for thermal expansion | SOL 108 for GE |
| CBEND | Curved beam element for arches and curved frames | New element formulation |
| NASTRAN f06 import | Read an existing NASTRAN f06 file into the viewer for display and comparison | Results parser |
| Model pre-solve validator | Interactive check before running: flag zero-length elements, missing SPC, unsupported cards, inconsistent units, unreferenced load/SPC SIDs — displayed as a warning panel in the viewer | Viewer complete |
| Sample model library | Curated set of BDF example files (cantilever, simply supported, portal frame, 2D truss, airplane stick, multi-span bridge) bundled with the repository for tutorials and regression testing | Verification suite |
| f06 results comparison | Load two f06 files side-by-side in the viewer; display difference tables and overlay deformed shapes for design-change comparison | NASTRAN f06 import |
