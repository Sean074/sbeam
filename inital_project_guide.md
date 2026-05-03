# Simple Beam FEA — Development Plan

> **Note:** This is the step-by-step development plan. Once the project is complete and all documentation files are fully developed and verified, this file SHOULD be deleted.
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

### Step 24: End-to-End Integration Tests

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

---

### Step 25: Documentation Finalisation

**Objective:** Ensure all documentation is current, consistent with the implemented code, and ready for handover.

**Deliverables:**
- `Methods.ipynb` — analytical derivations for Euler-Bernoulli stiffness matrix, consistent mass matrix, coordinate transformation, eigenvalue solution. Developed incrementally through the project; finalised here.
- Review and update `sbeam.md`, `Beam_model.md`, `Static_analysis.md`, `Modal_analysis.md`, `viewer.md` for any implementation details that changed during development.
- Delete `inital_project_guide.md` once all above is confirmed complete.

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
