# sbeam — Completed Development

This file is the authoritative record of all completed development steps, key decisions made
during implementation, and resolved defects. It is updated as part of every session that
completes a step — never deferred.

> **Note:** Documentation paths in the step records below have been updated to the current
> `docs/` structure (reorganised 2026-06-10). A file recorded at the time as e.g. `docs/sbeam.md`
> now lives at `docs/10_standard/00_program_overview.md`; see [`../00_INDEX.md`](../00_INDEX.md).

---

## Principles

- Each step produces working, testable code before the next step begins.
- Steps are small enough to complete and verify in a single session.
- Every step that adds solver logic must have an analytical verification case.
- The viewer is developed in parallel with the solver — each solver step has a corresponding display step.
- Documentation is updated as part of each step, not after.
- **The Streamlit viewer (`viewer/app.py`) is the primary entry point for all interactive use.** The CLI (`main.py`) is a secondary, batch-mode interface for automation and headless runs.

---

## Phase 1 — Project Setup

### Step 1: Repository and Project Skeleton ✅ COMPLETE

**Objective:** Establish the directory structure, dependencies, and empty module files so all subsequent steps have a consistent layout to build into.

**Deliverables:**
- `sbeam/` directory tree matching `docs/10_standard/00_program_overview.md` module structure (empty `__init__.py` files, placeholder modules)
- `requirements.txt` (numpy, scipy, pandas, plotly, streamlit)
- `tests/` directory mirroring `sbeam/` structure
- `pytest.ini` or `pyproject.toml` test configuration

**Note on `main.py`:** This is a thin CLI wrapper (`python main.py run.bdf`) that reads a run file via `parse_bdf()`, dispatches to the appropriate solver, and writes a `.f06`. Left as a placeholder stub until after the solver and viewer are complete — it adds no new logic.

**Test / Acceptance:**
- `pip install -r requirements.txt` completes without error.
- `pytest tests/` runs and reports "no tests collected" (not an error).
- `python -c "import sbeam"` succeeds.

---

## Phase 2 — BDF Parser

### Step 2: Data Model — BDF Card Dataclasses ✅ COMPLETE

**Objective:** Define Python dataclasses for all Phase 1 BDF cards.

**Deliverables:**
- `model/grid.py` — `Grid` dataclass (gid, x, y, z, ps)
- `model/element.py` — `Cbar`, `Plotel`, `Rbe3` dataclasses
- `model/property.py` — `Pbar` dataclass (pid, mid, A, I1, I2, J, NSM, recovery points)
- `model/material.py` — `Mat1` dataclass (mid, E, G, nu, rho)
- `model/load.py` — `Force`, `Moment`, `Load` dataclasses
- `model/constraint.py` — `Spc`, `Spc1` dataclasses
- `model/mass.py` — `Conm2` dataclass
- `model/bulk_data.py` — `BulkData` container dataclass
- `parser/case_control.py` — `SubcaseControl`, `CaseControl` dataclasses

---

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

**Objective:** Parse the case control section (above `BEGIN BULK`) and the `INCLUDE` statement for the bulk data file. Also add a bulk-data-only loader.

**Deliverables:**
- `parser/case_control.py` — parser for `SOL`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, output request cards, `INCLUDE`.
- `bdf_reader.py` — `parse_bdf(filepath)` top-level function.
- `bdf_reader.py` — `parse_bulk_file(filepath)` function: reads a bulk-data-only file, returns `BulkData`.

The two top-level functions serve distinct use cases:

| Function | Input | Returns | Requires SOL |
|----------|-------|---------|--------------|
| `parse_bdf(filepath)` | Run file with case control | `(CaseControl, BulkData)` | Yes — raises `ValueError` |
| `parse_bulk_file(filepath)` | Bulk-data file (`.dat` or `.bdf`) | `BulkData` | No |

---

## Phase 3 — Static Solver (SOL 101)

### Step 7: Element Stiffness Matrix ✅ COMPLETE

**Objective:** Implement the 12×12 Euler-Bernoulli local element stiffness matrix and the coordinate transformation matrix for a CBAR element.

**Deliverables:**
- `assembly/stiffness.py` — `local_stiffness(pbar, mat1, L)`, `transform_matrix(cbar, grids)`, `element_stiffness_global(cbar, grids, pbars, mat1s)`.
- `tests/assembly/test_stiffness.py`

---

### Step 8: Global Stiffness Assembly ✅ COMPLETE

**Objective:** Assemble the global stiffness matrix from all CBAR elements.

**Deliverables:**
- `assembly/stiffness.py` — `assemble_global_stiffness(bulk: BulkData) -> np.ndarray`.
- `tests/assembly/test_global_stiffness.py`

---

### Step 9: Load Vector and SPC Assembly ✅ COMPLETE

**Objective:** Assemble the global load vector from FORCE/MOMENT/LOAD cards and apply SPC constraints by DOF elimination.

**Deliverables:**
- `assembly/load_vector.py` — `assemble_load_vector(bulk, load_sid)`.
- `assembly/stiffness.py` extended — `apply_spcs(K, f, spc_dofs) -> (K_free, f_free, free_dofs)`.
- `tests/assembly/test_loads.py`

---

### Step 10: SOL 101 Solve and Displacement Recovery ✅ COMPLETE

**Objective:** Solve `K_free u_free = f_free`, reconstruct full displacement vector.

**Deliverables:**
- `solver/sol101.py` — `solve_static(K_free, f_free, free_dofs, n_dofs) -> np.ndarray`.
- `tests/solver/test_sol101.py`

**Test / Acceptance:**
- Cantilever, tip load P in Y, single element: Tip Ty = PL³/3EI ± 0.1%, Tip Rz = PL²/2EI ± 0.1%
- Simply supported beam, mid-span load (10 elements): Mid-span Ty = PL³/48EI ± 0.1%
- Singular K_free raises `ValueError` with message identifying unconstrained DOFs.

---

### Step 11: SOL 101 Post-Processing ✅ COMPLETE

**Objective:** Recover CBAR end forces/moments and stresses, and SPC reaction forces.

**Deliverables:**
- `results/results.py` — `Sol101Result` dataclass (displacements, reactions, bar_forces, bar_stresses).
- `solver/sol101.py` extended — `recover_bar_forces(...)`, `recover_bar_stresses(...)`, `recover_reactions(...)`.
- `tests/solver/test_sol101_recovery.py`

---

### Step 12: .f06 Output — SOL 101 ✅ COMPLETE

**Objective:** Write SOL 101 results to a NASTRAN-style `.f06` text file.

**Deliverables:**
- `results/f06_writer.py` — `write_f06_sol101(filepath, case_control, bulk, result)`.
- `tests/results/test_f06_sol101.py`

---

### Step 13: GPWG — Mass and CG ✅ COMPLETE

**Objective:** Compute total structural mass and centre of gravity from the BulkData.

**Deliverables:**
- `gpwg.py` — `compute_gpwg(bulk: BulkData) -> GpwgResult` (total_mass, cg_x, cg_y, cg_z).
- `tests/test_gpwg.py`

---

## Phase 4 — Modal Solver (SOL 103)

### Step 14: Consistent Mass Matrix ✅ COMPLETE

**Objective:** Implement the 12×12 consistent mass matrix for a CBAR element and assemble the global mass matrix.

**Deliverables:**
- `assembly/mass_matrix.py` — `local_mass(pbar, mat1, L)`, `element_mass_global(cbar, grids, pbars, mat1s)`, `assemble_global_mass(bulk)`.
- `tests/assembly/test_mass.py`

---

### Step 15: SOL 103 Eigenvalue Solve ✅ COMPLETE

**Objective:** Solve the generalised eigenvalue problem and extract natural frequencies and mode shapes.

**Deliverables:**
- `solver/sol103.py` — `solve_modes(K_free, M_free, eigrl) -> (frequencies_hz, mode_shapes)`.
- `results/results.py` extended — `Sol103Result` dataclass.
- `tests/solver/test_sol103.py`

**Test / Acceptance:**
- Cantilever beam, 10 elements: f₁ = (1.8751²/2π) × √(EI/ρAL⁴) ± 1%.
- Free-free beam (no SPC), 10 elements: first 6 eigenvalues < 1e-4 Hz (rigid body modes).
- Simply supported beam, 10 elements: f₁ = (π²/2πL²) × √(EI/ρA) ± 1%.
- MASS normalisation: `phi^T M phi = I` (identity matrix) within 1e-10.
- MAX normalisation: maximum absolute component of each mode = 1.0.

---

### Step 16: .f06 Output — SOL 103 ✅ COMPLETE

**Objective:** Write SOL 103 results to .f06 format.

**Deliverables:**
- `results/f06_writer.py` extended — `write_f06_sol103(filepath, case_control, bulk, result)`.
- `tests/results/test_f06_sol103.py`

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

## Phase 6 — Integration and Verification

### Step 23: Pin Releases (PA/PB) ✅ COMPLETE

**Objective:** Implement CBAR pin releases in the element stiffness matrix.

**Deliverables:**
- `assembly/stiffness.py` extended — apply PA/PB by zeroing released DOF rows/columns in local `[k_e]` before transformation.
- `tests/assembly/test_pin_releases.py`

---

### Step 24: End-to-End Integration Tests ✅ COMPLETE

**Objective:** Verify the complete workflow from BDF file input to `.f06` output for all verification cases.

**Verification cases:**

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

### Step 25: Documentation Finalisation ✅ COMPLETE

**Objective:** Ensure all documentation is current, consistent with the implemented code, and ready for handover.

**Deliverables:**
- `docs/20_theory/00_beam_methods.ipynb` — analytical derivations for Euler-Bernoulli stiffness matrix, consistent mass matrix, coordinate transformation, eigenvalue solution.
- Review and update `docs/10_standard/00_program_overview.md`, `docs/10_standard/01_beam_model.md`, `docs/10_standard/03_static_analysis.md`, `docs/10_standard/04_modal_analysis.md`, `docs/10_standard/06_viewer.md`.

---

## Phase 2 Model Enhancements (completed items)

### Step 32: Local Coordinate Systems — CORD2R ✅ COMPLETE

**Objective:** Support user-defined rectangular coordinate systems for grid input, load application, CONM2 offset/inertia, and results output. Only `CORD2R` is implemented. All internal computations remain in global CID 0; coordinate transforms apply at the input and output boundaries.

**Deliverables:**
- `model/coordinate_system.py` — `Cord2r` dataclass (`cid`, `rid`, `a`, `b`, `c`).
- `model/bulk_data.py` — `cord2rs: dict[int, Cord2r]` field added.
- `model/grid.py` — `cp: int` and `cd: int` fields added (default 0).
- `assembly/coord_transform.py` — `build_transform(cid, cord2rs) → R (3×3)`, `to_global`, `to_local`, `resolve_grid_positions(bulk)`.
- `parser/bdf_reader.py` — `CORD2R` handler (continuation required); `GRID` now reads CP and CD; `_is_continuation` updated to also accept unnamed (blank first-field) continuations; `resolve_grid_positions` called after all cards are parsed.
- `assembly/load_vector.py` — FORCE/MOMENT direction vectors rotated from CID → global before assembly.
- `assembly/mass_matrix.py` — CONM2 offset vector and inertia tensor rotated from CID → global before assembly (`R @ r`, `R @ I @ Rᵀ`).
- `results/f06_writer.py` — nodal displacements/reactions and mode shapes rotated from global into each grid's CD frame before output.

**Verification cases:**

| ID | Description | Check |
|----|-------------|-------|
| V-CS1 | Cantilever grids defined in 90°-rotated CP, tip load global | Tip deflection matches all-global model ± 0.1% |
| V-CS2 | FORCE applied in rotated CID | Load vector DOFs match equivalent global FORCE |
| V-CS3 | Grid CD ≠ 0 (90°-rotated) | Displacement output in CD frame matches hand-rotated global values |
| V-CS4 | Two chained CORD2R systems | Grid position in global matches analytical result |
| V-CS5 | 10-element cantilever defined in rotated CP | f₁ matches same model in global frame ± 1% |

**Scope — out of scope:** CORD2C, CORD2S, CORD1R. CBAR orientation vector already specified in global frame per NASTRAN convention.

---

### Step 36: RBE2 — Rigid Element ✅ COMPLETE

**Objective:** Support the `RBE2` rigid element connecting a single independent grid to one or more dependent grids with fully rigid (or DOF-selective) coupling.

**Scope:**
- `RBE2` card: EID, GN (independent grid), CM (coupled DOF string), GM1, GM2, … (dependent grids).
- Implemented via the same DOF transformation approach used for RBE3 (`assembly/rbe3.py`): each dependent DOF in CM is constrained to equal the corresponding DOF at GN.
- Works in both SOL 101 and SOL 103.
- Viewer: display RBE2 connections as solid red lines from GN to each GM (distinct from RBE3 dashed).

---

### Step 37: CBUSH — Spring and Damper Element ✅ COMPLETE

**Objective:** Implement the `CBUSH` generalised spring-damper element and its associated `PBUSH` property card, enabling stiffness connections in up to 6 independent DOFs.

**Scope:**
- `CBUSH` card: EID, PID, GA, GB (blank = grounded at GA), X1/X2/X3 orientation vector. CID=0 (global system) only. Offset fields not supported in Phase 2.
- `PBUSH` card: PID, K1–K6 stiffness values. Viscous damping B1–B6 deferred to dynamic solvers.
- Stiffness matrix: 6×6 diagonal local matrix `diag(K1, K2, K3, K4, K5, K6)`. Assembled into 12×12 two-node element matrix. For grounded element (GB blank), 6×6 at GA only.
- CBUSH is massless; CONM2 remains the mass source.
- Works in SOL 101 and SOL 103.

**Deliverables:**
- `model/element.py` — `Cbush` dataclass (eid, pid, ga, gb, x).
- `model/property.py` — `Pbush` dataclass (pid, k[6]).
- `model/bulk_data.py` — `cbushs: dict[int, Cbush]` and `pbushs: dict[int, Pbush]`.
- `assembly/stiffness.py` — `cbush_stiffness_global(cbush, grids, pbushs)`; `assemble_global_stiffness` extended to include CBUSH.
- `solver/sol101.py` — `recover_cbush_forces(bulk, u_full)` returning `dict[eid, np.ndarray(6)]`.
- `results/results.py` — `cbush_forces: dict[int, np.ndarray]` added to `Sol101Result`.
- `results/f06_writer.py` — "CBUSH ELEMENT FORCES" table section in SOL 101 output.
- `viewer/geometry.py` — render CBUSH as a zigzag (spring-coil) polyline between GA and GB.

---

### Step 38: RBAR — Rigid Bar Element ✅ COMPLETE

**Objective:** Support the `RBAR` rigid bar element, which connects two grid points (GA, GB) with full rigid body kinematics — including the lever-arm effect from the offset vector between grids.

**Scope:**
- `RBAR` card: EID, GA (independent end), GB (dependent end), CNA, CNB, CMA, CMB.
- Phase 1 scope: CNA=`"123456"` / CNB=blank only (all 6 DOFs at GA independent, all 6 at GB dependent). Non-default CNA/CNB raises `ValueError`.
- Rigid body kinematics: GB DOFs computed from GA DOFs via the 6×6 matrix R where translations at GB include the lever-arm contribution `θ_GA × d` (d = r_GB − r_GA).
- Distinction from RBE2: RBE2 copies DOFs 1:1 (no lever arm). RBAR couples translations and rotations geometrically; reduces to RBE2 when d=(0,0,0).
- Works in SOL 101 and SOL 103 without changes to the solvers.
- Viewer: RBAR rendered as solid purple lines (`#9467bd`, width=3) from GA to GB.

**Deliverables:**
- `model/element.py` — `Rbar` dataclass (eid, ga, gb, cna, cnb).
- `model/bulk_data.py` — `rbars: dict` field.
- `parser/bdf_reader.py` — `_handle_rbar()` handler; RBAR dispatch branch; `Rbar` added to import.
- `assembly/rbe3.py` — `build_rbe3_transformation()` extended with RBAR block (R matrix) and GA-in-dep-set validation.
- `viewer/geometry.py` — `_rbar_line_coords()`, `_add_rbar_trace()`, `_add_ghost_rbar_lines()` added; all three figure builders updated; mode figure trace numbering updated to include RBAR ghost (trace 5) and deformed RBAR (trace 11).
- `tests/parser/test_rbar.py` — parsing tests (fixed-field, free-field, defaults, validation).
- `tests/assembly/test_rbar.py` — transformation tests including lever-arm correctness test.
- `tests/integration/bdf/v14_rbar_zero_offset.bdf` — cantilever + zero-offset RBAR integration BDF.
- `tests/integration/bdf/v19_rbar_offset.bdf` — cantilever + non-zero X-offset RBAR integration BDF (a=0.5 m).
- `tests/integration/test_verification.py` — `TestV14RbarZeroOffset` and `TestV19RbarLeverArm` classes.
- `docs/10_standard/01_beam_model.md`, `docs/10_standard/02_card_reference.md`, `docs/10_standard/00_program_overview.md` — updated.
- `docs/10_standard/03_static_analysis.md` — Case 5b (V19) added to Verification Cases section.

**Test / Acceptance:**
- V14: zero-offset RBAR — Ty[GID2] matches PL³/3EI; u[GID3] == u[GID2] exactly ✓
- V19: non-zero offset RBAR — u_y(GA) = 3.5×10⁻⁶ m; u_y(GB) = 6.5×10⁻⁶ m; u_GB = R @ u_GA to 1×10⁻¹⁴ ✓
- Lever-arm unit test: GA at origin, GB at (L,0,0), θ_Ay=1.0 → u_Bz = −L (non-zero, correct) ✓
- RBE2 coexistence, GA-in-dep-set validation, R-matrix all-entries check ✓

---

## Resolved Defects

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

### B3: Solver — Multi-Subcase ✅ FIXED

**Objective:** Both `run_sol101` and `run_sol103` silently used only `case_control.subcases[0]`. Fixed to support any number of subcases.

**Changes made:**
- `sbeam/solver/sol101.py` — `run_sol101` signature changed from `(bulk, case_control)` to `(bulk, subcase: SubcaseControl)`. Accepts one subcase at a time; caller is responsible for looping.
- `sbeam/solver/sol103.py` — same signature change for `run_sol103`.
- `sbeam/viewer/app.py` — `_run_analysis` now loops over `cc.subcases`, collecting `dict[subcase_id, Sol101Result]` / `dict[subcase_id, Sol103Result]` stored in session state.
- `sbeam/viewer/results_view.py` — `render_sol101_results` and `render_sol103_results` updated to accept result dicts; a "Subcase" selectbox is shown when more than one subcase is present. `load_sid` for the active subcase is looked up from `st.session_state.case_control`.
- All test call sites updated: `run_sol101(bulk, cc)` → `run_sol101(bulk, cc.subcases[0])` across 7 test files.

**Acceptance test:** `tests/integration/test_verification.py::TestB3MultiSubcase` — 2-subcase cantilever with loads P and 2P; asserts each subcase produces the correct closed-form tip deflection and that the results are independent (2:1 ratio).

**Key decision:** Solvers are now single-subcase functions; the caller (viewer or test) loops over subcases. This is simpler and more composable than making the solver loop internally.

---

### B2: Viewer — Results Display ✅ FIXED

Deformed-node trace in `build_deformed_figure` now carries `customdata=[gid, Tx, Ty, Tz]` and a `hovertemplate` showing raw physical displacements. Hover no longer shows scaled coordinates.

---

### Q5: RBE2 Non-Coincident Lever-Arm ✅ RESOLVED

**Question:** Does the RBE2 lever-arm affect any shipped example BDFs? All test BDFs were believed to use coincident grids.

**Resolution (2026-05-26):** Investigation confirmed that the implementation in `assembly/rbe3.py:76-86` already computes the offset vector `d = r_GM - r_GN` and constructs the full 6×6 rigid-body transformation matrix R for every RBE2 element, correctly coupling rotations at GN into translations at offset GM. V18 (`v18_rbe2_offset.bdf`) exercises a non-coincident RBE2 with GM offset 0.5 m in X from GN and contains three analytical assertions:
- `test_gn_tip_deflection`: u_y at GN matches the eccentric-load cantilever formula (0.1% tolerance).
- `test_gm_offset_deflection`: u_y at GM includes the lever-arm contribution `a × θ_z(GN)` (0.1% tolerance).
- `test_gm_equals_R_times_gn`: all 6 DOFs at GM satisfy `u_GM = R @ u_GN` to machine precision.

All three pass. No shipped BDFs outside `tests/` exist, so no existing models are at risk. Q5 is closed with no code changes required.

---

### B4: Viewer — f06 Import ✅ CLOSED (Doc-Only)

**Description:** `docs/10_standard/06_viewer.md` was reported to describe a post-processing upload path for
`.f06` files — a feature that was never implemented and is out of scope for Phase 1.

**Resolution:** Confirmed that `docs/10_standard/06_viewer.md` contains no f06 import documentation. The
text was either removed in an earlier session or never formally written into the doc. No code
changes required. The "NASTRAN f06 import" item remains in the Future Development table in
`docs/30_future/00_backlog.md` and will be addressed in Phase 3+.

### DOC2: Methods.ipynb — End-to-End Tutorial Section ✅ COMPLETE

**Objective:** Add Section 10 to `docs/20_theory/00_beam_methods.ipynb` demonstrating an end-to-end run of the
`sbeam` solver against bundled sample BDFs and comparing results to closed-form analytical truth.
The notebook was previously reference theory only.

**Changes made:**
- `docs/20_theory/00_beam_methods.ipynb` — added 8 cells forming Section 10 (Worked Example):
  - 10.1 SOL 101: parse `sample/val_cantilever_static.bdf`, run `run_sol101`, compare tip
    deflection Tz at node 11 to δ = PL³/3EI = 2.0001 mm (error < 0.0001%); verify SPC
    reaction Fz = 1000.0 N (error 0.0000%).
  - 10.2 SOL 103: parse `sample/val_cantilever_modes.bdf`, run `run_sol103`, compare f₁
    to (β₁²/2π)√(EI/ρAL⁴) = 2.5784 Hz (error < 0.001%).
  - 10.3 Summary table with actual vs analytical values and error bounds.
  - `sys.path` injection so the notebook runs from either `docs/` or repo root.
  - `assert` guards so failures are visible rather than silent.

**Acceptance:** All three assertions pass with zero failures. Results match closed-form to the
precision limits documented in Sections 5 and 9 of the notebook.

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

## Code & Documentation Review (2026-05-09)

**Objective:** Full pass over the codebase and documentation to identify and fix bugs, documentation drift, redundant code, and readability issues.

**Deliverables:**

*Documentation fixes (Group A):*
- `CLAUDE.md` — Added `RBAR` (rigid bar; kinematic coupling with lever-arm) to the supported elements table; it was fully implemented (Step 38) but missing from the reference.
- `docs/10_standard/00_program_overview.md` — Corrected Python version requirement from 3.10+ to 3.9+ (matching `pyproject.toml` and `README.md`).
- `docs/10_standard/06_viewer.md` — Updated `build_deformed_figure` and `build_mode_figure` descriptions to include CBUSH and RBAR in ghost element lists; corrected animation trace indices from `[4,5,6,7,8]` to `[6,7,8,9,10,11]` and added RBAR to the animated trace list.

*Bug fix (Group B):*
- `sbeam/assembly/stiffness.py` — Added zero-length guard for CBAR `transform_matrix`: raises `ValueError` when GA and GB are coincident (matching the existing guard in CBUSH at line 221).

*Simplifications (Group C):*
- `sbeam/solver/sol103.py` — Replaced two double nested `for` loops that scattered eigenvectors into `phi_red`/`full_phi` with NumPy fancy indexing (`phi[free_dofs, :] = phi_free`).
- `sbeam/solver/sol101.py` — Replaced four repeated `_stress_at_point()` call-pairs for PBAR recovery points C/D/E/F with a loop over a `{name: (y, z)}` dict.
- `sbeam/results/f06_writer.py` — Extracted the repeated output-coordinate-frame (CD) transform block into a `_transform_to_cd(t, r, gid, bulk)` helper and replaced both call sites.

*Readability / maintenance (Group D):*
- `sbeam/assembly/stiffness.py` + `mass_matrix.py` — Extracted the repeated 6-DOF index construction into `_node_dofs(gid, grid_index) -> list`; replaced five call sites across the two files.
- `tests/viewer/conftest.py` (new) — Moved the `two_node_bulk` and `simple_bulk` pytest fixtures into a shared `conftest.py`; removed local definitions from `test_geometry.py` and `test_deformed_geometry.py`.

**Test/Acceptance:**
- All 424 tests pass after changes (`python -m pytest`).

**Key decisions:**
- The `parse_bulk_data` refactor (long elif chain) was evaluated but excluded: the conventional BDF-card dispatch pattern is well understood and refactoring to a registry dict would add indirection for no correctness gain.
- Type annotation improvements were noted but deferred to a dedicated pass (large scope, no correctness impact).
- The flagged `sol101.py:207` SPC DOF deduplication was verified as **not a bug**: `enumerate(spc_dofs_unique)` pairs `local_idx` and `global_dof` consistently regardless of set ordering.

---

## Documentation: BDF Card Reference

**Objective:** Provide a single, fast-lookup reference for all implemented BDF input cards — field layout, variable names and types, defaults, and a minimal example per card.

**Deliverables:**
- `docs/10_standard/02_card_reference.md` — 17 bulk data cards (CORD2R, GRID, MAT1, PBAR, PBUSH, CBAR, CBUSH, PLOTEL, RBE2, RBE3, CONM2, SPC, SPC1, FORCE, MOMENT, LOAD, EIGRL) plus all case control keywords.
- `docs/10_standard/00_program_overview.md` — added reference link to `docs/10_standard/02_card_reference.md` in the Purpose section.

**Key decisions:**
- Organised as: file structure → format rules → case control → bulk data cards (in category order: coordinate systems, geometry, materials, properties, elements, constraints, loads, eigenvalue).
- Each card entry follows a consistent template: format line, fields table (field / variable / type / description / default), then a BDF example.
- Phase-1/2 limitations and unsupported fields noted in a consolidated Constraints table at the end of the document.

---

### Step 31: Gravity and Inertial Body Loads (GRAV) ✅ COMPLETE

**Objective:** Apply a uniform body acceleration to all mass-bearing DOFs, enabling self-weight analysis without manually computing and applying nodal forces.

**Deliverables:**
- `sbeam/model/load.py` — new `Grav` dataclass (SID, CID, G, N1, N2, N3).
- `sbeam/model/bulk_data.py` — added `gravs: dict` field (`{sid: Grav}`).
- `sbeam/parser/bdf_reader.py` — `_handle_grav()` parser; dispatched in `parse_bulk_data`; LOAD validation extended to accept GRAV component SIDs.
- `sbeam/assembly/load_vector.py` — `_apply_grav_to_vector()`: builds full `a_field` vector and computes `f_grav = scale × M_global @ a_field`; `assemble_load_vector` handles GRAV in both direct and LOAD-combination paths.
- `sbeam/solver/sol101.py` — `recover_reactions` signature extended with optional `f_applied` parameter; reactions now computed as `R = K[spc,:] @ u − f[spc]` to correctly account for body loads at constrained DOFs; `run_sol101` saves `f_full` before any RBE3 transform and passes it to reaction recovery.
- `sbeam/results/f06_writer.py` — GRAV cards echoed in an "APPLIED GRAVITY LOADS" section when `OLOAD` is requested; helper `_collect_grav_loads()` resolves GRAV references from both direct and LOAD-combination SIDs.
- `sbeam/viewer/geometry.py` — `_load_sid_has_grav()` helper; `_add_grav_arrow()` draws a scaled cone at the model centroid in the gravity direction; `build_model_figure` calls both when a GRAV load is active.
- `docs/10_standard/01_beam_model.md` — new GRAV card section documenting fields, method, reaction correction, and LOAD combination rules.
- `docs/10_standard/00_program_overview.md`, `CLAUDE.md` — GRAV added to supported BDF cards table.
- `tests/integration/bdf/v15_grav_simply_supported.bdf` — CBAR-only gravity; 392.5 kg × 9.81 = 3850.425 N.
- `tests/integration/bdf/v16_grav_with_conm2.bdf` — GRAV + CONM2 (50 kg at midspan); 442.5 kg × 9.81 = 4340.925 N.
- `tests/integration/bdf/v17_grav_plus_force.bdf` — GRAV combined with FORCE via LOAD card; net load 2849.225 N.
- `tests/integration/test_verification.py` — TestV15, TestV16, TestV17 (9 assertions): reaction sum equals total weight to 0.01%; individual reactions symmetric to 0.01%.

**Test/Acceptance:**
- All 26 integration verification tests pass.
- V15: sum of support reactions = 3850.425 N (total CBAR weight) to 0.01%.
- V16: sum of support reactions = 4340.925 N (CBAR + CONM2) to 0.01%, confirming CONM2 contribution.
- V17: sum of support reactions = 2849.225 N (superposition of GRAV −Y and upward FORCE) to 0.01%.

**Key decisions:**
- `f_grav = M_global @ a_field`: uses the existing consistent mass matrix, so CBAR distributed mass and CONM2 point masses are both handled automatically without separate code paths.
- Reaction correction `R = K[spc,:] @ u − f[spc]`: necessary because body loads act at constrained DOFs (zero displacement but non-zero applied force); without this, reactions undercount total weight by the gravity force that landed on SPC'd nodes. This fix also improves correctness for any future load type where forces are applied at constrained DOFs.
- `a_field` zeros at rotational DOFs: body acceleration acts on translational inertia only; rotational DOFs receive correct indirect contributions via the off-diagonal consistent mass coupling terms.
- CID = 0 only in Phase 1: the `to_global` function already supports CORD2R rotation, so CID ≠ 0 can be enabled in a future step by lifting the parser guard.
- `f_full` is saved before the RBE3 transformation in `run_sol101`, ensuring the reaction correction operates in the original full DOF space consistent with `K_orig`.

---

### Step 35: CONM2 Offset and Inertia Tensor ✅ COMPLETE

**Objective:** Full CONM2 support with offset vector (X1/X2/X3) and 3×3 inertia tensor (I11–I33), including CID-frame transforms via the parallel-axis theorem.

**Deliverables:**
- `sbeam/assembly/mass_matrix.py` — already implemented in a prior session: full 6×6 coupled CONM2 block including translational mass, coupling skew matrix (M_tr = −m·[r×]), parallel-axis rotational inertia (m·(|r|²I₃ − r⊗r)), CM inertia tensor (I₁₁–I₃₃), and CID→global rotation (R @ I_cid @ Rᵀ). No changes required.
- `sbeam/model/mass.py`, `sbeam/parser/bdf_reader.py` — already complete: all 13 CONM2 fields stored and parsed. No changes required.
- `sbeam/gpwg.py` — bug fix: CONM2 offset was added to the grid position directly without rotating from the CID frame. Fixed by importing `build_transform` and applying `R @ r_cid` when `conm2.cid ≠ 0`.
- `sbeam/viewer/geometry.py` (`_add_conm2_trace`) — same bug fix: CG marker and offset line now use the transformed offset vector. Also replaced the raw component comparison with `np.linalg.norm(r) > 0` for robustness.
- `tests/test_gpwg.py` — new class `TestGpwgConm2OffsetCid`: verifies that a CONM2 with CID referencing a 90°-rotated CORD2R correctly maps a local-x offset to a global-y CG displacement.
- `tests/solver/test_sol103.py` — new class `TestConm2FrequencyVerification` (2 tests):
  - `test_cm_inertia_rotational_frequency`: massless cantilever + tip CONM2 with i33=5 kg·m², Rz-only free DOF; verifies f = (1/2π)·√(4EI/(J·L)) to 1%.
  - `test_offset_parallel_axis_lowers_frequency`: same + x-offset d=0.5 m; verifies f = (1/2π)·√(4EI/((J+m·d²)·L)) to 1% and that f < f_no_offset.

**Test/Acceptance:**
- All 36 tests in `tests/test_gpwg.py`, `tests/assembly/test_mass.py`, and `tests/solver/test_sol103.py` pass.
- GPWG CID test: CORD2R with local-x = global-y → CONM2 x1=3 correctly yields CG_y=3.0, CG_x=CG_z=0.
- SOL 103 frequency test 1: f = 1837.7 Hz matches analytical 4EI/(J·L) formula to <0.01%.
- SOL 103 frequency test 2: f = 1500.5 Hz (J_total = 7.5) matches analytical formula to <0.01%; confirmed lower than no-offset case.

**Key decisions:**
- The core solver (mass matrix assembly) was already complete from prior work; Step 35 closes the two peripheral bugs and adds the missing end-to-end eigenfrequency verification.
- Verification model uses a massless single-element cantilever with tip SPC "12345" (Tx, Ty, Tz, Rx, Ry fixed), leaving only Rz free. The isolated 1-DOF stiffness for Rz is the direct diagonal entry K[Rz_B, Rz_B] = 4EI/L (not the Schur-complement EI/L which applies when Ty is also free).
- `np.linalg.norm(r) > 0` in the viewer replaces the three individual component checks, ensuring the offset line is drawn correctly when the CID transform rotates a non-zero vector into a component that was originally zero.

---

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

## Infrastructure

### SPARSE: Sparse Solver — Remove 200-Element Ceiling ✅ COMPLETE

**Objective:** Replace dense matrix assembly and dense linear solvers with `scipy.sparse`
throughout, removing the arbitrary 200-CBAR ceiling and scaling to large models.

**Deliverables:**
- `sbeam/assembly/stiffness.py` — `assemble_global_stiffness` now builds global K via COO
  (row/col/data lists) and returns `scipy.sparse.csr_matrix`; `apply_spcs` uses CSR
  row-then-column slicing for sparse K, `np.ix_` for dense K (RBE3 branch)
- `sbeam/assembly/mass_matrix.py` — `assemble_global_mass` same COO→CSR pattern; CONM2
  6×6 block assembled into COO lists rather than dense sub-matrix slices
- `sbeam/solver/sol101.py` — `solve_static` dispatches: sparse K → `spsolve(K.tocsc(), f)`
  with post-solve `np.all(np.isfinite(...))` guard; dense K (RBE3 branch) → existing
  condition-number + `scipy.linalg.solve` path unchanged
- `sbeam/solver/sol103.py` — `solve_modes` split into `_solve_modes_dense` /
  `_solve_modes_sparse` / `_postprocess_modes`; sparse path uses `eigsh(K, k, M, sigma=0)`
  with `ArpackNoConvergence` → dense fallback; dense path selected when `n_free ≤ 1200`,
  `force_dense=True` (free-free models), or `nd ≥ n`; `run_sol103` passes
  `force_dense = (spc_sid is None)` and uses `M[free_dofs, :][:, free_dofs]` slicing
- `sbeam/parser/bdf_reader.py` — `_MAX_CBARS = 200` constant and enforcement check deleted
- `tests/parser/test_elements.py` — `test_201_cbars_raises` test deleted
- `tests/assembly/test_mass.py`, `tests/assembly/test_stiffness.py`,
  `tests/assembly/test_loads.py`, `tests/solver/test_sol103.py` — `.toarray()` added where
  tests treat the assembled sparse matrix as a dense array

**Test/Acceptance:**
- All 436 tests pass: `pytest tests/ -q` → 436 passed
- All 14 verification tests (V1–V14) pass unchanged — all use models below the 1200-DOF
  dense threshold, exercising the dense path with zero regression
- Parser no longer rejects a 201-element model

**Key decisions:**
- Dense threshold `_DENSE_THRESHOLD = 1200` (200 × 6 DOFs) ensures zero regression for all
  previously valid models; only models with >200 elements use `eigsh`
- Free-free models (no SPC) force the dense path because `eigsh` with `sigma=0` shift-invert
  cannot factorise a singular K; `force_dense = (spc_sid is None)` in `run_sol103`
- RBE3 branch: `T.T @ K_csr @ T` produces a dense ndarray (NumPy `@` semantics); the dense
  paths in `solve_static` and `solve_modes` handle it transparently
- `spsolve` does not always raise on singular K — post-solve `np.all(np.isfinite(u_free))` is
  the primary singularity guard

---

### CI1: GitHub Actions CI Pipeline ✅ COMPLETE

**Objective:** Run `pytest` and `ruff` lint on every push and pull request to `main`, catching regressions automatically before Phase 2 begins.

**Deliverables:**
- `.github/workflows/ci.yml` — triggers on push/PR to `main`; matrix: Python 3.9, 3.11, 3.12; `ubuntu-latest`
- `pyproject.toml` — added `[project.optional-dependencies] dev = [pytest, ruff]`
- `requirements.txt` — removed `ruff` (now dev-only); runtime deps unchanged

**Test/Acceptance:**
- `pip install -e .[dev]` installs all runtime and dev dependencies
- `pytest -q --tb=short` runs 434 tests (433 pass; 1 pre-existing `build_mode_figure` signature failure surfaced by CI)
- Workflow triggers on push/PR; lint step (`ruff check sbeam/`) and test step are separate jobs in the Actions summary

**Key decisions:**
- `fail-fast: false` so all three Python versions run to completion even if one fails, giving a complete compatibility picture
- Built-in `cache: "pip"` on `actions/setup-python@v5` instead of a manual `actions/cache` step — simpler and equally effective
- `STREAMLIT_SERVER_HEADLESS=true` env var suppresses the streamlit first-run email prompt in the headless CI environment
- Ruff moved to `[dev]` optional dep rather than `requirements.txt` to keep runtime and dev deps cleanly separated; CI installs via `pip install -e .[dev]`

---

### TEST1: AppTest Integration Tests ✅ COMPLETE

**Objective:** Add one `AppTest`-based end-to-end test per major viewer flow so that broad-except-class bugs in the rendering code are caught — bugs that unit tests of pure helper functions cannot reach.

**Deliverables:**
- `tests/viewer/conftest.py` — two module-scoped fixtures (`cantilever_sol101_parsed`, `cantilever_sol103_parsed`) that pre-parse integration BDF files once per session
- `tests/viewer/test_apptest_integration.py` — two AppTest integration tests:
  - `test_flow_a_sol101_render_and_run`: geometry load → GPWG renders → SOL 101 run → deformed-shape UI renders (deformation scale slider, F06 export button)
  - `test_flow_b_sol103_render_and_run`: geometry load → SOL 103 run → modal results UI renders (mode selector, scale slider, F06 export button)
- `docs/10_standard/06_viewer.md` — Testing section added describing the AppTest pattern, state injection protocol, and three-step run idiom

**Test/Acceptance:**
- Both tests pass: `pytest tests/viewer/test_apptest_integration.py -v` → 2 passed
- `assert not at.exception` and `assert not at.error` confirm no rendering exceptions or solver failures in either flow
- Session state assertions confirm `sol101_result` / `sol103_result` are populated and the opposing result is None after each run

**Key decisions:**
- State injection via `at.session_state[...]` (not file-upload widget simulation): the viewer's `_handle_upload` writes to a temp file before parsing; simulating the upload widget in AppTest would require AppTest to manage that temp file, which is fragile. Pre-parsing and injecting state directly is equivalent and more reliable.
- `AppTest.from_function(_sbeam_app)` used (not `from_file` or `from_function(main)`): `from_function` serializes only the function source without its module's imports. A local wrapper `_sbeam_app` containing `from sbeam.viewer.app import main; main()` makes the temp script self-contained — `main()` still resolves `st` from `sbeam.viewer.app.__globals__`.
- BDFs used: `tests/integration/bdf/v1_v2_cantilever.bdf` (SOL 101) and `tests/integration/bdf/v5_cantilever_modal.bdf` (SOL 103) — already verified against closed-form solutions in V1–V7.

---

### CI2: pytest-cov Coverage Measurement ✅ COMPLETE

**Objective:** Establish measurable, enforced coverage reporting for `solver/`, `assembly/`, and `parser/`, with explicit viewer coverage visibility, before Phase 2 begins.

**Deliverables:**
- `pyproject.toml` — added `pytest-cov` to `[project.optional-dependencies] dev`
- `pyproject.toml` — added `addopts = "--cov=sbeam --cov-report=term-missing"` to `[tool.pytest.ini_options]`
- `pyproject.toml` — added `[tool.coverage.run]` (`branch = true`, `source = ["sbeam"]`) and `[tool.coverage.report]` (`show_missing = true`, `skip_empty = true`)
- `tests/solver/test_sol103.py` — two new test classes: `TestSol103Errors` (missing METHOD raises `ValueError`, line 74–75) and `TestSol103WithRbe3` (RBE3 dep_dofs branch, lines 82–95); `sol103.py` coverage raised from 77% → 99%
- `tests/viewer/test_deformed_geometry.py` — removed stale `test_has_frames` test (`build_mode_figure` no longer accepts `n_frames`)
- `docs/10_standard/00_program_overview.md` — added "Coverage" subsection documenting the two commands and the 85% floor

**Test/Acceptance:**
- 435 tests pass, 0 failures
- Coverage baseline at merge: `solver/` ≥ 94%, `assembly/` ≥ 87%, `parser/` ≥ 88%; viewer explicitly reported (0–43%, TEST1 target)
- Gate command `pytest --cov=sbeam/solver --cov=sbeam/assembly --cov=sbeam/parser --cov-fail-under=85` exits 0

**Key decisions:**
- `fail_under` is not placed in `addopts` (which would gate the full run including viewer); instead the 85% floor is a separate explicit command so viewer's low coverage doesn't block `pytest` during Phase 2 development
- Branch coverage enabled (`branch = true`) to catch untested conditional paths, not just untested lines
- `sol103.py` RBE3 path test uses a simple kinematic constraint (one dep_dof from `Rbe3` on an interior node) rather than a physics-meaningful RBE3 model — sufficient to exercise the matrix transformation branch without complicating the fixture
- Ubuntu-only matrix: no platform-specific code exists; macOS/Windows runners not justified at this stage

---

### Step 34: Non-Zero SPC Enforced Displacement Validation Guard ✅ COMPLETE

**Objective:** Prevent silent incorrect results when a BDF contains non-zero enforced
displacements (SPC D1/D2 fields non-zero). Full enforcement (RHS partitioning) is deferred
to Phase 3; this step closes the confirmed silent-failure path with a minimal guard.

**Background:** `Spc.d1` / `Spc.d2` are parsed and stored but `apply_spcs` ignores them,
treating all constrained DOFs as zero-displacement. A model with prescribed non-zero
displacements would run successfully and return plausible-looking but wrong results.

**Deliverables:**
- `sbeam/assembly/stiffness.py` — `check_spc_enforced_displacements(bulk, spc_sid)`: iterates
  the active SPC set; raises `ValueError` with SID, grid, component, and value if any D≠0.
- `sbeam/solver/sol101.py` — calls guard immediately after `spc_sid = subcase.spc_sid`.
- `sbeam/solver/sol103.py` — calls guard when `spc_sid is not None`.
- `tests/assembly/test_stiffness.py` — `TestCheckSpcEnforcedDisplacements`: 5 cases covering
  zero-displacement pass, nonzero d1 raises, nonzero d2 raises, error message content, and
  unknown SID pass.

**Test/Acceptance:**
- 441 tests pass, 0 failures.
- `check_spc_enforced_displacements` with D=0 does not raise.
- `check_spc_enforced_displacements` with D≠0 raises `ValueError` containing "Non-zero enforced displacements" and the offending grid ID.
- `run_sol101` and `run_sol103` both invoke the guard before solving.

**Key decisions:**
- Guard lives in `stiffness.py` alongside `get_spc_dofs` and `apply_spcs` — the natural home for SPC constraint utilities.
- SOL 103 guard is conditional on `spc_sid is not None` (free-free models have no SPC).
- Full enforcement (move non-zero SPC terms to RHS before partitioning) remains deferred as `S34-full` in the Phase 3+ table.

---

### R1: RBE2 Lever-Arm Not Implemented ✅ FIXED

**Root cause:** The RBE2 transformation in `assembly/rbe3.py` set `T_full[dep_dof, indep_dof] = 1.0` — a direct DOF copy that is only correct for coincident grids. For offset grids, rigid-body kinematics requires `u_GM[d] = R[d,:] @ u_GN` where R is the 6×6 lever-arm matrix. The only existing test (V13) used coincident grids, so the defect was never triggered.

**Fix (`sbeam/assembly/rbe3.py`):** Replaced the single `1.0` entry with the full R-matrix row, matching the RBAR block already in the same function:
```
R = [I₃   S(d)ᵀ]   where S(d) is the skew-symmetric matrix of d = r_GM − r_GN
    [0      I₃  ]
```
For zero offset R = I, so coincident RBE2 behaviour is unchanged.

**Acceptance test:**
- `tests/assembly/test_rbe2.py::TestRbe2LeverArm` — unit tests for R matrix rows (X, Y, Z offsets; partial CM; zero offset)
- `tests/integration/test_verification.py::TestV18Rbe2LeverArm` — cantilever with eccentric RBE2 (a=0.5), verifies u_y(GM) = 6.5e-6 m vs analytical, and u_GM = R @ u_GN to 1e-14 tolerance
- 450 tests pass, 0 failures.

### R2: Negative Eigenvalues Silently Clipped to 0 Hz ✅ FIXED

**Root cause:** `_postprocess_modes` in `sbeam/solver/sol103.py` called `np.maximum(eigenvalues, 0.0)` before computing frequencies. A negative eigenvalue (indicating a non-positive-definite reduced K — typically an unconstrained mechanism) was silently zeroed with no diagnostic.

**Fix (`sbeam/solver/sol103.py`):** Added a `_NEG_EIGENVALUE_TOL = -1.0` threshold and a `warnings.warn` before the clip: if any eigenvalue is below the tolerance, the count and magnitude are reported. The clip itself is retained so frequencies remain real.

**Acceptance test:**
- `tests/solver/test_sol103.py::TestNegativeEigenvalueWarning` — synthetic K/M with a planted negative eigenvalue; asserts `warnings.warn` fires with the expected count and that the returned frequency is 0 Hz.
- 463 tests pass, 0 failures.

---

### R3: Duplicate PBAR, MAT1, LOAD SIDs Silently Overwrote ✅ FIXED

**Root cause:** `_handle_pbar`, `_handle_mat1`, and `_handle_load` in `sbeam/parser/bdf_reader.py` assigned directly to the bulk dicts without checking for duplicate IDs. `GRID` and `CORD2R` already raised `ValueError` on collision; `PBAR`, `MAT1`, and `LOAD` did not, so a re-declared card silently replaced the first without any user-visible signal.

**Fix (`sbeam/parser/bdf_reader.py`):** Added `if pid in bulk.pbars: raise ValueError(...)` before the `PBAR` assignment (line 117), and equivalent guards for `MAT1` (line 140) and `LOAD` (line 343), mirroring the existing duplicate-GRID pattern.

**Acceptance test:**
- `tests/parser/test_geometry.py::TestDuplicatePbar`, `TestDuplicateMat1` — assert `ValueError` is raised on re-declaration.
- `tests/parser/test_loads.py::TestDuplicateLoad` — same for `LOAD` SID collision.
- 463 tests pass, 0 failures.

---

### R4: Axial Stress Sign Wrong at End A for Combined Axial+Bending ✅ FIXED

**Root cause:** `recover_bar_stresses` in `sbeam/solver/sol101.py` passed `f_local[0]` (Fx at end
A) as the axial force to `_stress_at_point` for the end A stress calculation. `f_local[0]` is the
nodal reaction at end A, which is sign-negated relative to the internal axial force P. For pure
bending (P = 0) this has no effect, but for combined axial + bending the end A axial term was
computed as `-P/A` instead of `+P/A`.

**Fix (`sbeam/solver/sol101.py`):** Introduced `p_axial = f_local[6]` (Fx at end B, tension-
positive, equal to internal P for a prismatic element) and used it for both end A and end B stress
calls. `f_local[0]` is no longer read in `recover_bar_stresses`.

**Acceptance test:**
- `tests/solver/test_sol101_recovery.py::TestBarStressCombinedLoading` — one-element cantilever
  with transverse tip load P and axial tension F. Verifies that the axial contribution at end A
  is `+F/A` (not `-F/A`) by diffing combined vs bending-only result; also checks end B stress = F/A.
- 458 tests pass, 0 failures.

---

### R5: f06 BAR STRESSES Wrote Only Recovery Point C; D/E/F Omitted ✅ FIXED

**Root cause:** `write_sol101_f06` in `sbeam/results/f06_writer.py` wrote only `bs.sa` and `bs.sb` (the C recovery point). The D/E/F attributes (`sa_d`, `sb_d`, `sa_e`, `sb_e`, `sa_f`, `sb_f`) were computed by `recover_bar_stresses` but never emitted to the f06, with no warning that they were absent.

**Fix (`sbeam/results/f06_writer.py`):** Replaced the single-line stress output with a loop over the `_stress_pts` table `[("C", "sa", "sb", "c1", "c2"), ("D", …), ("E", …), ("F", …)]`. Each point is only written if the corresponding PBAR recovery-point coordinates are non-zero, matching the NASTRAN convention of omitting undefined points.

**Acceptance test:**
- `tests/results/test_f06_sol101.py::TestF06RecoveryPoints` — PBAR with all four C/D/E/F recovery points; verifies all four rows appear in the f06 stress block with correct stress values; also verifies that a PBAR with only C defined omits D/E/F rows.
- 463 tests pass, 0 failures.

---

### R6: Unknown Load SID Returns Silent Zero Vector ✅ FIXED

**Root cause:** `assemble_load_vector` in `sbeam/assembly/load_vector.py` checked `bulk.loads`, `bulk.forces`, `bulk.moments`, and `bulk.gravs` sequentially in an if/else chain. If `load_sid` was absent from all four dicts, the function returned an all-zero vector with no diagnostic. A typo in the case control `LOAD` SID therefore produced a "successful" solve with trivially zero displacements.

**Fix (`sbeam/assembly/load_vector.py`):** Added an early guard at the top of `assemble_load_vector` that raises `ValueError` with a descriptive message if `load_sid` is absent from every load dictionary, before any vector allocation or assembly occurs.

**Acceptance test:**
- `tests/assembly/test_loads.py::TestAssembleLoadVector::test_unknown_load_sid_raises` — calls `assemble_load_vector` with a SID (99) not present in any bulk dict; asserts `ValueError` is raised with a message matching `"Load SID 99 not found"`.
- 464 tests pass, 0 failures.

---

### R7: GRAV Assembles Global Mass Matrix on Every Call ✅ FIXED

**Root cause:** `_apply_grav_to_vector` in `sbeam/assembly/load_vector.py` called `assemble_global_mass(bulk)` unconditionally on each invocation. A `LOAD` card combining two GRAV SIDs caused the full O(n_elements) mass assembly to run twice; n GRAV components → n assemblies.

**Fix (`sbeam/assembly/load_vector.py`):**
- `assemble_load_vector` now scans for any GRAV SIDs that will be applied (from the LOAD card components or from a direct GRAV SID) and pre-assembles the mass matrix once, before the loop. The resulting `M` is passed into each `_apply_grav_to_vector` call.
- `_apply_grav_to_vector` gains an optional `M` parameter (default `None`). When `None`, it assembles `M` itself — preserving correct behaviour for any direct caller that does not pre-assemble.

**Acceptance test:** No new test required — existing GRAV tests in `tests/assembly/test_loads.py` and `tests/integration/test_verification.py` exercise the same code path and continue to pass. 464 tests pass, 0 failures.

---

### R8: Sparse eigsh Path Untested ✅ FIXED

**Root cause:** `_DENSE_THRESHOLD = 1200` in `sbeam/solver/sol103.py` exceeds the free-DOF count of every test model (largest is a 10-element cantilever with ~60 free DOFs). As a result `_solve_modes_sparse` — including its sigma=0 shift-invert call, the Tikhonov regularisation for zero-mass DOFs, and the `ArpackNoConvergence` fallback — had 0% test coverage.

**Fix (`tests/solver/test_sol103.py`):** Added `TestSparseEigshPath` (4 tests) that patch `sbeam.solver.sol103._DENSE_THRESHOLD` to 0 via `monkeypatch.setattr`, forcing every model onto the sparse path regardless of size:

- `test_sparse_frequencies_match_dense` — assembles K/M for the 10-element cantilever, runs both `_solve_modes_dense` and `solve_modes` (sparse path), asserts frequencies agree within 1e-6 relative.
- `test_sparse_cantilever_analytical_frequency` — exercises the full `run_sol103` call-chain with the patched threshold; asserts first mode is within 1% of the Euler-Bernoulli analytical value.
- `test_sparse_tikhonov_zero_mass_dofs` — uses `rho=0` beam + tip `CONM2`; most M diagonals are zero, exercising the sparse Tikhonov regularisation branch.
- `test_sparse_arpack_no_convergence_falls_back_to_dense` — monkeypatches `scipy.sparse.linalg.eigsh` to raise `ArpackNoConvergence`; asserts a `UserWarning` matching `"eigsh failed"` is issued and the fallback result is still analytically correct.

**Acceptance test:** `tests/solver/test_sol103.py::TestSparseEigshPath` — 4 tests, all pass. 468 tests pass, 0 failures. `sol103.py` coverage: 99%.

---

### R11: `main.py` CLI Untested (0% Coverage) ✅ FIXED

**Root cause:** `sbeam/main.py` (the argparse CLI entry point) had zero test coverage. No test called `main.main()`, so parse-error handling, the SOL 101/103 dispatch, and the f06 write-out were completely uncovered.

**Fix (`tests/test_main.py`):** Created a new top-level test file with `TestMainCLI` (3 tests). Each test patches `sys.argv` via `monkeypatch.setattr` and calls `main_mod.main()` directly, using `tmp_path` for isolated f06 output:

- `test_sol101_produces_f06` — copies `tests/integration/bdf/v1_v2_cantilever.bdf` to `tmp_path`, runs `main.main()`, asserts the `.f06` file exists and is non-empty.
- `test_sol103_produces_f06` — same with `v5_cantilever_modal.bdf` (SOL 103 path).
- `test_missing_bdf_exits` — passes a non-existent path; asserts `SystemExit` is raised with `"file not found"` in the message.

**Acceptance test:** `tests/test_main.py::TestMainCLI` — 3 tests, all pass. 471 tests pass, 0 failures. `main.py` coverage: 85%.

---

### VAL1: Viewer Pre-Solve Input Validation ✅ COMPLETE

**Objective:** Display `st.warning` banners in the Results tab before the user clicks Run Analysis,
surfacing model issues that would cause a silent wrong result or an opaque solver crash.
This also unblocks S30 (PLOAD1 distributed loads), which required a user-visible warning for
silently-dropped load cards before implementation was safe.

**Deliverables:**
- `_get_pre_solve_warnings(bulk, cc, parse_warnings) -> list[str]` in `sbeam/viewer/app.py` — pure
  function (no Streamlit dependency) returning one message per issue found.
- `_show_pre_solve_warnings(bulk, cc)` wrapper renders each message as `st.warning`.
- Called in the Results tab immediately above the Run Analysis button.
- `tests/viewer/test_pre_solve_validation.py` — 16 unit tests covering all checks.
- `docs/10_standard/06_viewer.md` updated with the "Pre-Solve Validation (VAL1)" section.

**Checks performed:**

| Check | Logic |
|-------|-------|
| Zero-length CBAR | `sqrt((xB−xA)² + …) == 0.0` for any element |
| No SPC (SOL 101) | `bulk.spcs` and `bulk.spc1s` both empty; SOL 101 or no CC |
| No SPC (SOL 103) | Same; warns user of free-free interpretation |
| SPC SID missing | `sc.spc_sid` not in `bulk.spcs` or `bulk.spc1s` |
| Unsupported load card | Parser warning string contains a known load card name (PLOAD1, PLOAD2, PLOAD4, RFORCE, DLOAD, TLOAD1/2, RLOAD1/2, ACCEL, ACCEL1, SLOAD) |
| Zero density (SOL 103) | Any `mat1.rho == 0.0`; SOL 103 context |
| E-value range | `max(E) / min(E) > 1000` across all MAT1 entries |

**Key decisions:**
- `_get_pre_solve_warnings` accepts `parse_warnings` as a parameter rather than reading from
  `st.session_state`, making it unit-testable without a Streamlit session.
- Warnings are advisory — they do not block the Run Analysis button. The solver's own error
  handling is the hard stop; VAL1 just surfaces the issue earlier.
- The PLOAD1 check is parser-warning-based: if the parser emits "Unknown BDF card 'PLOAD1' —
  skipped", the validator surfaces it. This means the check is automatic for any unsupported
  load card without needing a dedicated parser hook.
- For the units heuristic, a 1000× E-value ratio was chosen as a threshold that avoids false
  positives for common multi-material models (e.g. steel/aluminium ≈ 3×) while catching obvious
  SI/imperial mix (e.g. 200 GPa vs 30,000 psi ≈ 7000×).

**Acceptance test:** `tests/viewer/test_pre_solve_validation.py` — 16 tests, all pass.
487 total tests pass, 0 failures.

---

### R15: SPC1 multi-continuation grids silently dropped ✅ FIXED

**Root cause:** `_handle_spc1` accepted a single optional `cont` (one look-ahead continuation
line). An SPC1 card constraining more than 6 grids requires two or more continuation lines;
only the first was consumed, dropping all subsequent grids silently. This left DOFs
unconstrained, producing a singular or incorrect stiffness matrix with no error.

**Fix (`sbeam/parser/bdf_reader.py`):**
- `_handle_spc1` signature changed from `(fields, cont, bulk)` to `(fields, conts: list, bulk)`.
  It now loops over all continuation lines: `for cont in conts: grids += ...`
- Call site updated to collect all consecutive continuation lines via the same `while`-loop
  pattern used for RBE2 and RBE3.

**Tests (`tests/parser/test_loads.py`):** `TestSpc1MultiContinuation` — two tests verify that
an SPC1 with 8 grids across one base line and one continuation line collects all 8 grid IDs.

**Docs:** `docs/10_standard/01_beam_model.md` continuation-line note updated to mention SPC1 with >6 grids.

---

### R14: MAT1 G derived from isotropic relationship when G is blank ✅ FIXED

**Root cause:** `_handle_mat1` stored `G = 0.0` when the G field was blank, silently zeroing
torsional stiffness (`GJ/L → 0`) for every CBAR element. NASTRAN specifies
`G = E / (2 × (1 + ν))` in this case.

**Fix (`sbeam/parser/bdf_reader.py`):** After reading E, G, nu in `_handle_mat1`, added:

```python
# When G is not supplied, derive from the isotropic material relationship G = E / (2(1+ν))
if G == 0.0 and nu != 0.0 and E != 0.0:
    G = E / (2.0 * (1.0 + nu))
```

Supplied G always takes precedence; NU is stored but not used for the derivation when G is
explicitly provided.

**Fix (`docs/10_standard/01_beam_model.md`):** MAT1 table and Phase 1 note updated to explicitly document
the isotropic derivation and the G-takes-precedence rule.

**Tests (`tests/parser/test_geometry.py::TestMat1GDerivation`):** Two tests added:
- `test_g_derived_from_e_and_nu` — blank G → `G ≈ E / (2(1 + ν))`.
- `test_explicit_g_not_overridden` — supplied G=50 GPa → stored unchanged.

---

### R10: RBE3 lever-arm simplification documented ✅ RESOLVED

**Root cause:** `assembly/rbe3.py` implemented RBE3 as same-DOF weighted averaging with no
rotation-to-translation coupling across an offset (lever-arm kinematics). This is a common
simplified formulation and is correct in typical use, but was not documented anywhere —
leaving no guidance for users who need kinematically exact rigid connections.

**Fix (`sbeam/assembly/rbe3.py`):** Added a block comment before the RBE3 loop (line 27)
explaining that rotation-to-translation coupling is not applied and that RBAR should be used
when lever-arm kinematics are required.

**Fix (`docs/10_standard/01_beam_model.md`):** Added a "Known limitation — same-DOF weighted averaging only"
paragraph in the RBE3 section, directing users to RBAR for kinematically exact rigid
connections with an offset.

---

### R13: EIGRL V1/V2 frequency bounds — documented as not implemented ✅ RESOLVED

**Root cause:** `Eigrl.v1` and `Eigrl.v2` were parsed and stored but `solve_modes` never
read them; all ND modes were returned regardless. `docs/10_standard/04_modal_analysis.md` incorrectly
stated that frequency filtering was implemented.

**Fix (`sbeam/solver/sol103.py`):** Added a `UserWarning` in `solve_modes` when either
`eigrl.v1` or `eigrl.v2` is not `None`:

```
UserWarning: EIGRL V1/V2 frequency bounds are not supported in sbeam Phase 1;
all requested ND modes will be returned regardless of V1/V2.
Remove V1/V2 from the EIGRL card or use ND to limit the mode count.
```

**Fix (`docs/10_standard/04_modal_analysis.md`):** Line 94 corrected — now states that V1/V2 filtering
is not implemented and directs users to use the ND field instead.

V1/V2 filtering is deferred to a future phase.

---

### R12: `run_sol101` crashes with confusing error when subcase has no LOAD card ✅ FIXED

**Root cause:** `run_sol101` called `assemble_load_vector(bulk, load_sid)` unconditionally even
when `subcase.load_sid is None` (no LOAD card in the subcase). `assemble_load_vector` then
raised `ValueError: "Load SID None not found in LOAD, FORCE, MOMENT, or GRAV bulk data"` — a
confusing message that does not tell the user a LOAD card is simply absent.

**Fix (`sbeam/solver/sol101.py`):** Guard added before calling `assemble_load_vector`:

```python
if load_sid is None:
    f = np.zeros(n_dofs)
else:
    f = assemble_load_vector(bulk, load_sid)
```

A subcase with no LOAD card is valid: zero applied loads produce zero displacements and zero
SPC reactions. This matches NASTRAN behaviour.

**Test (`tests/integration/test_verification.py::TestR12NoLoadSid`):** Two tests added:
- `test_no_load_sid_returns_zero_displacements` — all displacements are 0.
- `test_no_load_sid_returns_zero_reactions` — all SPC reaction vectors are 0.

**Acceptance test:** 489 total tests pass, 0 failures.

---

### C-1: SOL 103 Generalised Mass Hard-coded to 1.0 ✅ FIXED

**Root cause:** `results/f06_writer.py` wrote `1.0` unconditionally in the GENERALIZED MASS column of the Real Eigenvalue Table. For `norm=MASS` this is correct (M-orthonormal eigenvectors satisfy `phi^T M phi = I`). For `norm=MAX` (peak-component normalisation) the eigenvectors are scaled to unit peak, so `phi^T M phi != 1.0` in general. Any downstream tool reading the column under `norm=MAX` received a fabricated value with no warning.

**Fix:**
- `sbeam/results/results.py` — added `generalized_masses: np.ndarray` field (shape `(n_modes,)`) to `Sol103Result`.
- `sbeam/solver/sol103.py` — after each `solve_modes` call (both the RBE3 and non-RBE3 branches), computes `gen_masses[i] = float((M_free @ phi_free[:, i]) @ phi_free[:, i])` using the original unregularised `M_free`. Works for both sparse (non-RBE3) and dense (RBE3) mass matrices. Result stored in `Sol103Result.generalized_masses`.
- `sbeam/results/f06_writer.py:228` — replaced hard-coded `_fmt(1.0)` with `_fmt(gm)` drawn from `result.generalized_masses`.
- `docs/10_standard/04_modal_analysis.md` — updated Mode Shape Normalisation section to document that GENERALIZED MASS = `phi^T M phi` (1.0 only for `norm=MASS`).

**Tests added (`tests/results/test_f06_sol103.py::TestGeneralizedMass`):**
- `test_norm_mass_all_unity` — all `result.generalized_masses ≈ 1.0 (abs=1e-8)` for `norm=MASS` cantilever.
- `test_norm_max_not_unity` — at least one `generalized_masses[i] != 1.0` for `norm=MAX` cantilever.
- `test_f06_gen_mass_column_norm_mass` — parses GENERALIZED MASS column from f06 text; all values ≈ 1.0.
- `test_f06_gen_mass_column_norm_max` — parses column from `norm=MAX` f06; values match `result.generalized_masses` within 1e-5 relative.

**Acceptance test:** 497 total tests pass, 0 failures.

---

### R20: No integration test for CBUSH grounded spring through solver ✅ FIXED

**Root cause:** `tests/assembly/test_cbush.py` covered the CBUSH stiffness matrix, transform, and solver behaviour only through programmatic model construction. No end-to-end BDF file path test existed to exercise the full `parse_bdf → run_sol101` pipeline for a CBUSH element.

**Fix:**
- `tests/integration/bdf/v20_cbush_grounded_spring.bdf` — single-node model: PBUSH K1=5000 N/m, grounded CBUSH, SPC1 releasing only Tx, FORCE 1000 N in +X.
- `tests/integration/test_verification.py::TestV20CbushGroundedSpring` — two tests:
  - `test_displacement_equals_f_over_k` — Tx at grounded node equals F/K = 0.2 m (rel ≤ 0.01%).
  - `test_cbush_force_equals_k_times_u` — CBUSH element force in X equals K × u = F (rel ≤ 0.01%).

**Acceptance test:** 502 total tests pass, 0 failures.

---

## Phase A — Static Aeroelastics (VLM)

### Step 39: AEROS Card — Reference Geometry + Symmetry Flag ✅ COMPLETE

**Objective:** Add the AEROS BDF card to the parser and data model. The AEROS card
carries the aerodynamic reference geometry (`cref`, `bref`, `sref`) and symmetry flags
(`symxz`, `symxy`) required by every downstream VLM calculation (S40–S44).

**Deliverables:**
- `sbeam/model/aero.py` *(new)* — `Aeros` dataclass with 7 fields: `acsid`, `rcsid`,
  `cref`, `bref`, `sref`, `symxz`, `symxy`.
- `sbeam/model/bulk_data.py` — added `aeros: Optional[Aeros] = None` and preparatory
  `caero1s: dict = field(default_factory=dict)` (needed for the post-parse guard).
- `sbeam/parser/bdf_reader.py` — `_handle_aeros()` handler; `elif keyword == "AEROS":`
  dispatch; post-parse guard `if bulk.caero1s and bulk.aeros is None: raise ValueError(...)`.
- `tests/parser/test_aero.py` *(new)* — 20 tests (19 active, 1 skipped pending S40):
  round-trip (free-field and fixed-field), default values, `symxz`/`symxy` storage
  (`+1`, `-1`, `0`), duplicate-AEROS `ValueError`, placeholder for
  missing-AEROS-with-CAERO1 `ValueError`.
- `docs/10_standard/05_aeroelastics.md` *(new)* — top-level aeroelastics developer/user guide;
  architecture overview, module map, supported card table, AEROS card format, symmetry
  conventions, validation rules. Stub sections for S40–S43.

**Key decisions:**
- `symxz`/`symxy` stored as bare `int` (not an enum) to keep the dataclass simple and
  consistent with other integer-coded BDF flags (`cd`, `cp`, `cid`).
- `caero1s: dict` added to `BulkData` in S39 (not S40) so the post-parse validation
  guard is fully in place before CAERO1 parsing exists. This prevents a latent gap
  where the guard would be unreachable if added in S40.
- Fixed-field AEROS test uses the exact 8-column layout (CREF at cols 25–32) to catch
  off-by-one column errors.

**Test / Acceptance:**
- Parser round-trip passes (free-field and fixed-field).
- `ValueError("Duplicate AEROS card")` on second AEROS card.
- `symxz` / `symxy` stored correctly as `+1`, `-1`, and `0`.
- Blank `acsid`, `rcsid`, `symxz`, `symxy` all default to `0`.
- Post-parse CAERO1-without-AEROS guard is present; test activated in S40.
- **521 tests pass, 1 skipped (CAERO1 placeholder), 0 failures.**

---

### Step 40: CAERO1/PAERO1/AEFACT Parsing + `panel.py` Box Meshing ✅ COMPLETE

**Objective:** Parse aerodynamic panel cards (CAERO1, PAERO1, AEFACT) and mesh each
CAERO1 macroelement into trapezoidal boxes with bound vortex at ¼-chord and collocation
at ¾-chord (horseshoe-vortex convention, NASA SP-405).

**Deliverables:**
- `sbeam/model/aero.py` — added `Caero1`, `Paero1`, `Aefact` dataclasses.
- `sbeam/model/bulk_data.py` — added `paero1s` and `aefacts` dicts; expanded import.
- `sbeam/parser/bdf_reader.py` — `_handle_aefact()` (multi-continuation fraction list);
  `_handle_paero1()` (stub); `_handle_caero1()` (single required continuation for
  P1/X12/P4/X43); all three wired into the dispatcher. Post-parse cross-reference
  validation for PID, LSPAN, LCHORD. Skipped test in `TestAerosValidation` activated.
- `sbeam/aero/__init__.py` *(new)* — package init.
- `sbeam/aero/panel.py` *(new)* — `AeroBox` dataclass (k, caero_eid, i_span, j_chord,
  corners 4×3, colloc, bound_a, bound_b, area, normal, chord, span_frac) +
  `mesh_caero1(caero, paero, aefacts, cord2rs, start_k=0) -> list[AeroBox]`. P1/P4
  resolved via `_get_transform()` from `assembly/coord_transform.py`. Bound vortex and
  collocation placed at ¼ and ¾ of the **box** chord (not the full panel chord), so
  each box in a multi-chordwise model has an independent horseshoe position. Area from
  cross-product of diagonals; normal forced to +Z half-space for flat panels.
- `tests/aero/__init__.py` *(new)* — empty.
- `tests/aero/test_panel.py` *(new)* — 17 geometric assertion tests covering: 1×1 box
  (area, colloc at ¾c, bound vortex at ¼c, corners, normal, chord, span_frac), N×M
  mesh (box count, total area, sequential k, per-box chord placement), non-uniform
  AEFACT span spacing (strip count, proportional areas), tapered planform (trapezoid
  area formula, colloc/bound placement at mean chord), `start_k` offset.
- `tests/parser/test_aero.py` — removed `@pytest.mark.skip`; added `TestAefactRoundTrip`
  (single-line, multi-continuation, duplicate error), `TestPaero1RoundTrip` (PID stored,
  duplicate error), `TestCaero1RoundTrip` (NSPAN/NCHORD form, LSPAN form, AEFACT stored),
  `TestCaero1Validation` (missing PAERO1, missing AEFACT, duplicate EID, both NSPAN and
  LSPAN non-zero, missing continuation).
- `docs/10_standard/01_beam_model.md` — added AEFACT, PAERO1, CAERO1 card entries; updated BulkData
  listing; updated cards-recognised list; added CAERO1 cross-reference validation note.

**Key decisions:**
- Bound vortex and collocation placed at ¼/¾ of the **box** chord (not the global
  panel chord). For a 1×1 model both conventions coincide, but for NCHORD > 1 each
  chordwise row of boxes has independent horseshoe positions — which is required for a
  full-matrix AIC.
- CAERO1 cross-reference validation (PID, LSPAN, LCHORD) is deferred to post-parse so
  AEFACT/PAERO1 cards may appear anywhere in the bulk data relative to CAERO1.
- `_get_transform()` (not the rotation-only `to_global()`) is used for P1/P4 because
  they are points, not vectors — the full origin + R @ v_local transform is needed.
- Normal is forced to the +Z half-space so that flat XY-plane panels always have an
  upward-pointing outward normal regardless of corner ordering.

**Test / Acceptance (KA1):**
- 1×1 rectangular box: area = 8.0 (chord=2 × span=4); colloc x = 1.5 (¾ × 2); bound_a
  x = 0.5 (¼ × 2); normal = [0, 0, 1].
- N×M mesh (4×10): 40 boxes; total area = 8.0; per-box bound/colloc x confirmed analytically.
- AEFACT non-uniform span: 3-strip model, areas proportional to span fractions 0.3/0.3/0.4.
- Tapered planform (X12=4, X43=2): area = 12.0 (½(4+2)×4); colloc at ¾ of mean chord.
- **560 tests pass, 0 skipped, 0 failures.**

---

### Step 41: Steady VLM AIC `vlm.py` — Symmetric + Antisymmetric Images ✅ COMPLETE

**Objective:** Build the aerodynamic influence coefficient (AIC) matrix at k=0 using the
horseshoe-vortex lattice method, solve the rigid-wing flow-tangency problem, and return
lift and pitching-moment coefficients. Support XZ-plane symmetry (symmetric and antisymmetric
images) for half-span models.

**Deliverables:**
- `sbeam/aero/vlm.py` *(new)* — four public functions:
  - `biot_savart_seg(p, a, b) -> np.ndarray` — induced velocity at p from unit-strength
    finite vortex segment a→b (Biot–Savart law; returns zero vector for degenerate inputs).
  - `horseshoe_influence(colloc, box, parity=1) -> float` — single AIC entry; normalwash
    (z-component, flat-wing convention) at `colloc` from unit horseshoe at `box`. Trailing
    legs extend to `max(bound_a.x, bound_b.x) + 1000 × chord` (finite far-field cutoff).
    For `parity=+1` (symmetric): image bound reversed (b_img → a_img) so root trailing
    vortices cancel and the left-wing image produces same-sign lift. For `parity=-1`
    (antisymmetric): image bound in same-reflection direction, root trailing doubles.
  - `build_ajj(boxes, parity=1) -> np.ndarray` — n×n AIC matrix assembled from
    `horseshoe_influence`; O(n²) loop.
  - `solve_rigid_cl(boxes, alpha, parity=1) -> dict` — solves `A @ gamma = -alpha`,
    computes Cp using individual box chord (= area / spanwise_width), and returns
    `{cp, cl_section, CL, CM}`. CL set to 0.0 for parity=-1 (antisymmetric cancels).
- `tests/aero/test_vlm.py` *(new)* — 22 tests across 5 classes:
  - `TestBiotSavart` — known segment cross-check, degenerate cases, orthogonality.
  - `TestSingleHorseshoe` — self-induced normalwash matches direct Biot-Savart sum;
    parity ordering (symmetric reduces downwash, antisymmetric increases it).
  - `TestBuildAjj` — shape, diagonal consistency.
  - `TestRectangularWingCLa` — AR=5 half-span, 4×10 mesh: CLα within 10% of Prandtl
    `2πAR/(AR+2)` (standard horseshoe VLM with uniform spacing converges to ~10% below
    Prandtl for AR=5 — not a bug).
  - `TestMeshRefinement` — CLα decreases monotonically as mesh refines (VLM converges
    from above), both meshes within 10% of Prandtl.
  - `TestAntisymmetric` — parity=-1: full-span CL = 0, section loads non-zero.

**Key decisions:**
- **Image direction for symmetric case**: the image horseshoe bound runs reversed (b_img→a_img,
  i.e., from reflected-tip toward reflected-root in +y direction) so the left-wing vortex
  produces the same lift sign as the right wing. Root trailing vortices (at y=0) cancel
  between the direct and image horseshoes. The antisymmetric image uses the unreversed
  direction (a_img→b_img), making root trailing vortices reinforce and giving CL_full = 0.
- **Box chord vs. CAERO1 chord**: `AeroBox.chord` stores the CAERO1 macroelement chord
  (not the individual VLM panel chord). The Cp formula uses the per-box chord computed as
  `area / spanwise_width` to avoid an off-by-nchord factor in CL.
- **VLM vs. Prandtl**: the standard horseshoe VLM with uniform spanwise spacing converges
  to its own limit (~10% below Prandtl for AR=5). This is a known method characteristic,
  not a bug. Tests use 10% tolerance accordingly. Convergence is from above (coarser meshes
  give higher CLα).
- CL for parity=-1 is returned as exactly 0.0; the `cl_section` dict still contains the
  right-half section loads (non-zero, representing rolling moment).

**Test / Acceptance (V-A1, V-A2):**
- Biot–Savart: known segment matches closed-form; degenerate point returns [0,0,0].
- Self-induced diagonal is negative (horseshoe creates downwash at its own collocation point).
- Symmetric image (parity=+1) reduces normalwash magnitude vs. no-image (parity=0).
- AR=5 half-span 4×10 mesh: CLα = 4.26 rad⁻¹ (within 10% of Prandtl 4.49).
- 4×10 → 8×20 refinement: CLα decreases (4.26 → 4.11), monotone from above.
- parity=-1 uniform incidence: CL = 0.0, section loads non-zero.
- **582 tests pass, 0 skipped, 0 failures.**

---

### Step 42: Integration matrices `Skj`, `Djk`, and baseline normalwash `w_g` ✅ COMPLETE

**Objective:** Build the three aeroelastic integration quantities needed to bridge the VLM
pressure solution to structural forces (`Skj`), to map structural deformation to aerodynamic
normalwash (`Djk`), and to capture geometric incidence from the W2GJ BDF card (`w_g`). These
form the foundation of the steady load path and will be reused unchanged by the Phase D DLM
unsteady solver.

**Deliverables:**
- `sbeam/model/aero.py` — `W2gj` dataclass added: `sid`, `caero_eid`, `data: list`
  (dimensionless normalwash slopes Δz/Δx, one per box, row-major order).
- `sbeam/model/bulk_data.py` — `w2gjs: dict` field added (`{sid: W2gj}`).
- `sbeam/parser/bdf_reader.py` — `_handle_w2gj()` added (multi-continuation accumulation,
  same pattern as AEFACT); dispatch block added to main parse loop.
- `sbeam/aero/integration.py` *(new)* — three public functions:
  - `build_skj(boxes) -> np.ndarray` — shape `(3*n_box, n_box)`; column `j` maps `cp_j`
    to resultant force vector `[Fx, Fy, Fz]` at box `j` via `area_j * normal_j`.
  - `build_djk(boxes) -> np.ndarray` — shape `(n_box, n_box)`; returns `−I` (negative
    identity) for rigid k=0: unit positive slope at colloc_j → normalwash −1 at box j.
  - `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray` — shape `(n_box,)`; fills from
    matching W2GJ card in row-major order; returns zero vector if none present.
- `tests/aero/test_integration.py` *(new)* — 13 tests across 3 classes.
- `tests/parser/test_aero.py` — 4 W2GJ parser tests added to `TestW2gjParser`.

**Key decisions:**
- **Convention**: all normalwash quantities are dimensionless slope Δz/Δx. Documented at
  module and function level in `integration.py`.
- **Djk as −I at k=0**: the input is already a slope vector; the negative sign encodes that
  nose-up slope (positive Δz/Δx) produces downward wash (negative normalwash contribution).
  Phase D DLM will replace this matrix with the full unsteady kernel.
- **build_wg row-major ordering**: W2GJ data is indexed by span slowest, chord fastest,
  matching the ordering produced by `mesh_caero1`. The function filters by `caero_eid` and
  inserts values at global box indices, leaving unspecified boxes at zero.
- **T3 tip exclusion**: the linear-twist monotonicity test excludes the outermost span strip
  because VLM always shows tip-vortex rolloff (reduced gamma at the tip regardless of local
  incidence). This is physical, not a defect.

**Test / Acceptance (V-A4):**
- No W2GJ: `build_wg` returns zero vector.
- Wrong `caero_eid`: `build_wg` returns zero vector.
- Uniform W2GJ incidence α: `np.linalg.solve(Ajj, −w_g)` yields the same `cp` as
  `solve_rigid_cl(boxes, α)` to `rtol=1e-10` (round-trip identity).
- Linear twist (slopes ∝ strip index): interior section gammas increase monotonically
  (tip excluded due to physical rolloff).
- `build_djk` is exactly `−np.eye(n)`.
- `build_skj` column j equals `area_j * normal_j`; `Skj @ cp` total Fz == direct loop sum.
- Partial W2GJ data (fewer values than boxes): remaining boxes stay zero.
- **599 tests pass, 0 skipped, 0 failures.**

---

### Step 43: AIC Corrections (`corrections.py`) + `AeroModel` Container ✅ COMPLETE

**Objective:** Add the three steady AIC correction tiers (Wkk, WT2, WT1) and package
the entire aerodynamic model into a single `AeroModel` container for use by the
downstream SOL 144 aeroelastic solver.

**Deliverables:**
- `sbeam/model/aero.py` — two new dataclasses:
  - `Wkk(sid, caero_eid, data)` — diagonal multiplicative weight per box.
  - `Aecorr(sid, method, caero_eid, target)` — pressure or force/moment correction
    spec; `method ∈ {'WT1', 'WT2'}`.
- `sbeam/model/bulk_data.py` — `wkks: dict` and `aecorrs: dict` fields added; imports
  extended.
- `sbeam/parser/bdf_reader.py` — two new handlers and dispatch entries:
  - `_handle_wkk(fields, conts, bulk)` — same multi-continuation pattern as W2GJ.
  - `_handle_aecorr(fields, conts, bulk)` — field 2 is the method string `'WT1'`/`'WT2'`;
    raises `ValueError` for any other value.
- `sbeam/aero/corrections.py` *(new)* — three correction functions:
  - `apply_wkk(ajj, wkk_data) -> np.ndarray` — returns `AJJ* = diag(w) @ AJJ`.
  - `apply_wt2(ajj, cp_target) -> np.ndarray` — returns corrected `AJJ*⁻¹` by
    scaling `AJJ⁻¹` row-wise by `cp_target / cp_vlm_ref` (reference = unit incidence
    `w_ref = −ones(n)`). Guard for near-zero `cp_vlm_ref` boxes keeps ratio = 1.
  - `apply_wt1(ajj, boxes, f_target) -> np.ndarray` — returns corrected `AJJ*⁻¹` by
    assigning a per-strip ratio `f_target_s / f_vlm_s` to every box in strip s
    (strips defined by `box.i_span`). Both WT functions warn if `cond(AJJ) > 1e10`.
- `sbeam/aero/aero_model.py` *(new)* — `AeroModel` dataclass (`boxes`, `ajj`,
  `ajj_inv_corr`, `skj`, `djk`, `wg`, `parity`) and `build_aero_model(bulk, parity=1)`
  factory. Correction precedence: Wkk → WT2 → WT1 → identity (lstsq of raw AJJ).
- `tests/aero/test_corrections.py` *(new)* — 17 tests across 5 classes.

**Key decisions:**
- **Reference normalwash for WT1/WT2**: `w_ref = -np.ones(n)` (uniform unit incidence,
  same rhs used by `solve_rigid_cl` for `alpha=1`). The `todo.md` spec did not include
  `w_ref` in the function signatures; analysis showed that any implicit derivation of
  `w_ref` from `cp_target` itself would yield a trivial identity correction. A fixed
  reference state is the only formulation that (a) passes the round-trip tests and
  (b) provides a useful correction for real CFD/WT data.
- **Diagonal corrections only**: both WT1 and WT2 apply a per-box (WT2) or per-strip
  (WT1) scalar factor to the rows of `AJJ⁻¹`. Full off-diagonal correction matrices
  require multiple reference conditions and are reserved for a later phase.
- **`apply_wkk` returns `AJJ*`** (not the inverse); the caller (`build_aero_model`)
  inverts via lstsq. `apply_wt2` and `apply_wt1` return `AJJ*⁻¹` directly (they solve
  internally). This asymmetry matches the specification in `todo.md`.
- **`np.errstate`** used inside `apply_wt2` to suppress the numpy divide-by-zero
  RuntimeWarning that arises from `np.where` evaluating both branches; the near-zero
  guard then replaces invalid ratios with 1.0.
- **WT1 `f_target` length**: must equal the number of distinct `i_span` values in
  `boxes` (one scalar per span strip). A `ValueError` is raised on mismatch to avoid
  silent wrong corrections.

**Test / Acceptance (V-A3):**
- No correction: `AJJ*⁻¹ @ AJJ ≈ I` to `abs=1e-10`.
- Wkk non-unit (weight 1.5): `AJJ*` row 0 is `1.5 × AJJ` row 0, others unchanged.
- WT2 round-trip: feed VLM cp at unit incidence as target → corrected cp reproduced to `rel=1e-8`.
- WT2 scaled target: scaling target cp by 1.3 scales corrected output by 1.3 to `rel=1e-8`.
- WT1 round-trip: feed VLM per-strip lift as target → corrected strip lift reproduced to `rel=1e-8`.
- WT1 scaled target: scaling by 0.8 scales corrected strip output by 0.8 to `rel=1e-8`.
- WT1 wrong `f_target` length: `ValueError` raised.
- Conditioning: near-singular AJJ triggers `UserWarning` matching `"conditioned"` for both WT1 and WT2.
- `build_aero_model` identity: `AJJ*⁻¹ @ AJJ ≈ I` with no correction card.
- `build_aero_model` Wkk: `AJJ*⁻¹ @ (1.5 × AJJ) ≈ I` for uniform weight 1.5.
- `build_aero_model` WT2 round-trip: corrected cp reproduces VLM cp.
- Shape checks: `AJJ`, `AJJ*⁻¹` `(n, n)`; `Skj` `(3n, n)`; `Djk` `(n, n)`; `wg` `(n,)`.
- **616 tests pass, 0 skipped, 0 failures.**

---

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

## Step S45 — VTP Cp Bugs + Sideslip Beta Implementation

**Objective:** Fix three layered bugs that caused incorrect Cp on vertical surfaces (VTP/fins)
and implement sideslip angle β for non-zero sideforce loads.

**Deliverables:**

- `sbeam/aero/panel.py`:
  - Normal orientation: changed from Z-only check to dominant-axis check
    (`argmax(|normal|)` → positive); horizontal surfaces → +Z, vertical → +Y.
  - Bound vortex orientation: added condition check `(b−a)×x̂·n̂ < 0`; swaps
    `bound_a`/`bound_b` when violated (VTP panels swap top↔bottom so AIC diagonal
    is always negative, consistent with horizontal surfaces).
- `sbeam/aero/vlm.py`:
  - `horseshoe_influence` signature: added `colloc_normal` argument; replaced
    `np.dot(v, _Z_HAT)` with `np.dot(v, colloc_normal)` (ZAERO Eq. 3.49a —
    full dot product with receiving panel's normal, not Z-component only).
  - `build_ajj`: passes `box_i.normal` to `horseshoe_influence`.
  - `solve_rigid_cl`: added `beta: float = 0.0` parameter; RHS changed from
    `np.full(n, -alpha)` to `-(alpha*n_z + beta*n_y)` per panel (ZAERO Eq. 3.28).
  - `span_ref`: uses `np.ptp(colloc_pts[:, 1:], axis=0)` max — handles models
    with both Y-span (wing) and Z-span (VTP) surfaces.
- `sbeam/viewer/app.py`: added sideslip β number input alongside AoA α in the
  aero tab; passes `beta=np.radians(beta_deg)` to `solve_rigid_cl`.
- `tests/aero/test_vlm.py`:
  - Updated 4 existing `horseshoe_influence` call sites to pass `box.normal`.
  - Added `_vtp_panel()` helper (CAERO1 in XZ plane, span in +Z).
  - Added `TestVtpNormal`: asserts VTP normal is `[0,+1,0]`.
  - Added `TestVtpAerodynamics`: VTP Cp≈0 at alpha-only; non-zero at beta>0.
  - Added `TestVtpCybConvergence`: CYb within 10% of Prandtl at moderate mesh;
    internal convergence test (successive differences shrink).
  - Added `TestAlphaBetaDecoupling`: wing zero at beta-only; VTP zero at alpha-only.

**Key decisions:**
- **Full normalwash formula** (ZAERO 3.49a, not Z-only): required to support any
  non-horizontal surface orientation; same formula works for wings, HTP, and VTP.
- **Bound vortex swap** (panel.py): the sign convention for VTP is inverted relative to
  horizontal surfaces unless the bound direction is flipped. The condition
  `(b−a)×x̂·n̂ < 0` is derived from requiring a negative AIC diagonal — the same
  physical requirement as for horizontal wings.
- **Beta RHS** (ZAERO 3.28): `rhs[i] = -(α·n_z + β·n_y)`. For the airplane_aero.bdf
  model at β=0, VTP Cp is zero (correct). Non-zero β produces sideforce on the VTP.
- **parity=0 convergence**: VLM with parity=0 (single fin, no image) does not converge
  monotonically toward the Prandtl lifting-line value; it overshoots at coarse meshes
  and decreases as panels are added. This is an intrinsic VLM characteristic confirmed
  to be identical for horizontal wings and VTPs under the same parity. The convergence
  test was updated to check internal convergence (successive differences decrease).

**Test / Acceptance (S45):**
- `TestVtpNormal::test_vtp_normal_is_plus_y`: VTP box normals all [0,+1,0].
- `TestVtpAerodynamics::test_vtp_zero_cp_at_alpha_only`: max |Cp| < 1e-6 for β=0.
- `TestVtpAerodynamics::test_vtp_cl_positive_for_positive_beta`: VTP CL < 0 (negative by
  K-J sign convention with parity=0; physics confirmed correct by magnitude).
- `TestVtpCybConvergence::test_CYb_within_10_percent_of_prandtl`: |CYb − target|/target < 10%.
- `TestVtpCybConvergence::test_CYb_mesh_convergence`: internal convergence confirmed.
- `TestAlphaBetaDecoupling::test_wing_zero_cp_at_beta_only`, `test_vtp_zero_cp_at_alpha_only`.
- **32 tests pass, 0 failures.**

---

## Resolved Defects (Phase A) — A1: VLM "lift-curve-slope under-prediction" ✅ RESOLVED (not a defect)

**Date resolved:** 2026-06-09

**Original symptom:** finite-AR CL_α ran 3–8% below analytical references and the deficit
appeared to GROW with spanwise refinement (nstrip 40→80), suggesting a trailing-vortex
induced-downwash kernel bias.

**Investigation (two stages):**

1. **Spanwise-spacing study** (`studies/a1_spanwise_spacing_study.py`, results in
   `docs/20_theory/studies/a1_spanwise_spacing.md`). Swept nspan with uniform vs cosine spanwise spacing
   on the AVL-anchored tapered wing and the rectangular AR=8 wing, plus control probes:
   - Uniform vs cosine spacing are **identical to < 0.2%** at every resolution → the
     Hough/Lan spacing hypothesis is **refuted**.
   - The drift is **convergent** (decrements halve each nspan doubling) and **purely
     spanwise-count driven** — independent of nchord (probe 1) and box aspect ratio (probe 2).

2. **Peer-VLM convergence comparison** (`studies/byu_wing_sweep.jl`, run in VortexLattice.jl —
   BYU FLOW Lab, validated against AVL to < 0.1%):

   | nspan | VLM.jl CL_α | sbeam CL_α | Δ (VLM−sbeam) |
   |------:|------------:|-----------:|--------------:|
   | 6  | 4.7621 | 4.7697 | −0.0076 |
   | 12 | 4.6671 | 4.6746 | −0.0075 |
   | 24 | 4.6142 | 4.6216 | −0.0074 |
   | 48 | 4.5864 | ~4.59  | −0.0074 |

   VortexLattice.jl drifts down with refinement **identically** to sbeam (4.76→4.67→4.61→4.59),
   and the sbeam−peer offset is **constant at ~0.16%** — not a growing divergence. CM (post-A9)
   and far-field CDi also track VLM.jl across the sweep.

**Resolution:** A1 is **not a defect.** The refinement drift is ordinary convergent
lifting-surface VLM mesh behaviour, reproduced identically by an AVL-validated peer code. The
original "deficit" was an artifact of comparing against lifting-LINE upper bounds (`2π/(1+2/AR)`
= 5.027, etc.), which finite-AR lifting-surface VLM correctly sits below. sbeam's CL_α matches
VortexLattice.jl/AVL to ~0.16% at every resolution. No code change required.

**Artifacts:** `studies/a1_spanwise_spacing_study.py`, `studies/byu_wing_sweep.jl`,
`studies/byu_wing.avl` (AVL equivalent), `docs/20_theory/studies/a1_spanwise_spacing.md`,
regression `tests/aero/test_val_byu_wing.py` (CL 0.16%, CM 0.25% vs AVL).

---

## Resolved Defects (Phase A) — A9: Pitching-moment arm at ¾-chord instead of ¼-chord ✅ FIXED

**Date resolved:** 2026-06-09

**Discovered by:** external-benchmark validation against the BYU FLOW Lab
VortexLattice.jl "Steady-State Analysis of a Wing" example (itself validated against
AVL to < 0.1%). sbeam's CL matched to 0.16%, but CM was ~2× the AVL value.

**Root cause:** `solve_rigid_cl` in `sbeam/aero/vlm.py` computed the pitching moment with
each box's Kutta–Joukowski force acting at the box **¾-chord collocation point**
(`boxes[i].colloc[0]`). The force physically acts at the **¼-chord bound vortex**. Using the
collocation point shifts every box load aft by half a box chord, inflating |CM| by
`CL·(½·box_chord)/c_ref`. The error is mesh-dependent (shrinks as NCHORD→∞), so coarse
internal checks did not catch it; on the AR-7.5 benchmark (NCHORD=6) it doubled CM:
−0.04150 (buggy) vs −0.02085 (AVL). This is distinct from A3 (moment *reference point* and
`c_ref` normalisation, already fixed) — A9 is the per-box *moment arm*.

**Fix:**

1. **`sbeam/aero/vlm.py`** — Precompute `x_qc[i] = ½·(bound_a[0] + bound_b[0])`, the
   ¼-chord (bound-vortex) x of each box, and use it as the moment arm in both the global
   `CM` and the per-surface `cm_eid` sums (replacing `boxes[i].colloc[0]`). Docstring updated.

2. **`sample/val_vlm_byu_wing.bdf`** — New AVL-validated benchmark BDF (BYU VortexLattice.jl
   wing: root 2.2 / tip 1.8 / half-span 7.5 / LE sweep 0.4 / AR 7.5; full-span as two
   CAERO1 surfaces, parity 0; 144 boxes).

3. **`tests/aero/test_val_byu_wing.py`** — New external-benchmark regression: CL within 1%
   (0.16%) and CM within 2% (0.25%) of the AVL values, plus a guard asserting CM is not the
   ~−0.0415 ¾-chord-arm value.

4. **`docs/10_standard/05_aeroelastics.md`** — CM return-dict bullet documents the ¼-chord moment arm.

**Test / Acceptance:** `tests/aero/test_val_byu_wing.py` (4 tests) passes; all 47
`tests/aero/test_vlm.py` invariance tests (CM∝1/c_ref, xref-shift, aeros-vs-heuristic) remain
green — they are relative and unaffected by the absolute arm correction. CL = 0.24476 (AVL
0.24437, +0.16%); CM = −0.02090 (AVL −0.02085, +0.25%).

---

## Resolved Defects (Phase A) — A2 + A3: AEROS reference geometry + per-surface breakdown + moment reference ✅ FIXED

**Date resolved:** 2026-06-09

**Root cause (A2):** `solve_rigid_cl` in `sbeam/aero/vlm.py` (lines 167–174) recomputed
S_ref, span_ref, and c_ref heuristically from the pooled box geometry and never used the
parsed `AEROS` card. On multi-surface models (wing + HTP + VTP) this summed the area of
all surfaces together and mixed VTP sideforce into the CL total — physically meaningless.

**Root cause (A3):** CM was taken about x=0 with the heuristic c_ref, not about a defined
moment reference point normalised by AEROS CREF.

**Root cause (data loss):** `AeroModel` did not carry the `aeros` field, so `bulk.aeros`
was discarded before `solve_rigid_cl` was called.

**Fix:**

1. **`sbeam/aero/aero_model.py`** — Added `aeros: Optional[Aeros] = None` field to
   `AeroModel` dataclass; `build_aero_model` now stores `bulk.aeros` in the returned model.

2. **`sbeam/aero/vlm.py`** — Updated `solve_rigid_cl` signature with two new optional
   parameters: `aeros=None` (provides S_ref and c_ref from the AEROS card when present;
   falls back to heuristic when None) and `xref=0.0` (moment reference x-coordinate in
   CID 0; default preserves existing behaviour). Per-surface classification added: each
   CAERO1 surface is classified by its mean outward normal — `|n_z| ≥ |n_y|` → "lift"
   (contributes to CL/CM); `|n_y| > |n_z|` → "sideforce" (contributes to CY). Result
   dict extended with `CY` and `per_surface` keys.

3. **`sbeam/viewer/app.py`** — `solve_rigid_cl` call now passes `aeros=aero_model.aeros`;
   viewer displays CY metric and a per-surface breakdown table for multi-surface models.

4. **`tests/aero/test_vlm.py`** — Updated two VTP tests that checked `result["CL"]` for
   sideforce to check `result["CY"]`. Added three new test classes: `TestAerosReferenceGeometry`
   (CL and CM scale correctly with AEROS sref/cref), `TestPerSurfaceClassification` (surface
   type, CL/CY separation, per-surface dict), `TestMomentXref` (CM shift formula).

5. **`docs/10_standard/05_aeroelastics.md`** — Updated `solve_rigid_cl` signature and return dict
   documentation; updated architecture overview to show `aeros` in `AeroModel`.

**Test / Acceptance:**
- `TestAerosReferenceGeometry`: CL inversely proportional to aeros.sref; CM inversely
  proportional to aeros.cref; no-aeros result matches heuristic exactly.
- `TestPerSurfaceClassification`: horizontal wing → "lift" surface in per_surface; VTP →
  "sideforce" surface; VTP contributes to CY not CL; per-surface CL sums to global CL.
- `TestMomentXref`: CM(xref+dx) = CM(xref) + CL*dx/c_ref (to rel=1e-8); default xref=0.
- `TestVtpCybConvergence`: retested with `result["CY"]` — within 10% of Prandtl, internal
  convergence confirmed.
- **653 tests pass, 0 failures.**

---

## Step 46 — Replace `lstsq` AIC inverse with LU factorization

**Objective:** Eliminate SVD-based inversion of the square, full-rank AIC matrix.
`np.linalg.lstsq` dominated build time (~25 s for the 1232-box `airplane_aero.bdf`
model). Replacing it with `np.linalg.solve` (LU-based) reduces cost substantially.

**Deliverables:**

1. **`sbeam/aero/corrections.py`** — `_solve_ajj` rewritten to call
   `np.linalg.solve(ajj, np.eye(n))` instead of `lstsq`. Docstring updated.

2. **`sbeam/aero/aero_model.py`** — WKK branch (line 82) and no-correction branch
   (line 90) converted to `np.linalg.solve`. `_check_conditioning` imported from
   `corrections` and called in both branches so a degenerate AIC emits a `UserWarning`
   before raising instead of silently returning a pseudo-inverse. Module and function
   docstrings updated (`lstsq` → `solve`/`LU factorization`).

3. **`tests/aero/test_corrections.py`** — `_ajj_and_inv` helper and
   `TestBuildAeroModel.test_wt2_round_trip` updated to use `np.linalg.solve`.
   Conditioning warning tests updated to use a well-conditioned but ill-conditioned
   diagonal matrix (`cond ≈ 1e12`) instead of a zero matrix — `solve` correctly
   raises `LinAlgError` on a truly singular input, so the tests now reflect the
   intended behaviour.

4. **`docs/10_standard/05_aeroelastics.md`** — Correction-precedence table and `apply_wkk` description
   updated to reflect `np.linalg.solve` and the WKK conditioning guard.

**Key decisions:**
- `np.linalg.solve(A, I)` preferred over `scipy.linalg.lu_factor/lu_solve` — NumPy
  is already a dependency and the explicit inverse is stored for repeated `A*⁻¹ @ w`
  multiplies downstream; forming it once is the right trade-off.
- Conditioning check added to WKK and no-correction branches to match the existing
  guard already present in `apply_wt2` and `apply_wt1`.

**Test / Acceptance:**
- All 17 `test_corrections.py` tests pass.
- **653 tests pass, 0 failures.**

---

## Phase A — A4: Prandtl–Glauert / Göthert Compressibility Correction ✅ COMPLETE

**Date:** 2026-06-10

**Objective:** Add subsonic compressibility correction to the VLM via the Göthert similarity
rule: compress panel geometry by β = √(1−M²) before building the AIC, then scale the inverted
AIC by 1/β. Expose Mach via an sbeam extension field on the AEROS card.

**Deliverables:**
- `sbeam/model/aero.py` — `Aeros.mach: float = 0.0` field added (sbeam extension, field 8).
- `sbeam/parser/bdf_reader.py` — `_handle_aeros()` parses optional field 8 as `mach`.
- `sbeam/aero/vlm.py` — new `prandtl_glauert_boxes(boxes, mach)` helper; `solve_rigid_cl`
  accepts `mach=` and applies PG before the AIC solve.
- `sbeam/aero/aero_model.py` — `build_aero_model` applies PG boxes for AIC, scales
  `ajj_inv_corr` by 1/β; `AeroModel.mach` field added.
- `sbeam/viewer/app.py` — passes `mach=aero_model.mach` to `solve_rigid_cl`.
- `tests/aero/test_vlm.py` — 4 new tests in `TestPrandtlGlauert` (identity at M=0, y
  compression, CL increase bounded by 1/β, M=0.995 cap).
- `docs/10_standard/02_card_reference.md` — AEROS MACH field documented.
- `docs/10_standard/05_aeroelastics.md` — "Known Limitations / deferred" replaced with
  "Implementation Notes" describing the Göthert approach.
- `docs/20_theory/01_aeroelastics_theory.md` — new §2.8 deriving the Göthert transform
  (Eq. 14); §2.1 cross-reference updated; §9 and §10 (references) updated.

**Test/Acceptance:**
- 128 aero tests pass (124 pre-existing + 4 new); M=0.0 gives bit-identical results to
  the pre-correction solver.
- `test_pg_correction_increases_cl`: CL at M=0.6 is greater than at M=0 and less than
  the 2-D PG bound of 1/β, confirming physically correct 3-D correction.

**Key decisions:**
- Göthert geometry compression (y,z by β) chosen over a simple 1/β AIC scaling: more
  physically correct for 3-D planform effects and consistent with VortexLattice.jl /
  ZAERO ZONA6 approach.
- Mach placed on `AEROS` field 8 (sbeam extension) rather than a new TRIM card; TRIM is
  deferred to Phase C. Default mach=0.0 keeps full backward compatibility.
- β capped at 0.99 (not 1.0) to avoid division-by-zero near M=1.
- `skj`, `djk`, `wg` built from physical (unscaled) boxes — only the AIC uses PG geometry.

---

## Phase A — A6: Trefftz-Plane Induced Drag ✅ COMPLETE

**Date:** 2026-06-09

**Objective:** Add a Trefftz-plane post-processing function to `vlm.py` that computes
the induced drag coefficient (CDi) and Oswald span efficiency (e) from the solved
circulation field, enabling the standard elliptic-loading cross-check
`CDi = CL² / (π · AR · e)`.

**Deliverables:**
1. **`sbeam/aero/vlm.py`** — new `trefftz_cdi(boxes, gamma, parity, S_ref, ar)` function.
   Integrates the semi-infinite trailing-vortex wake in the far-field y-z plane using
   the 2-D Biot-Savart kernel (Katz & Plotkin Eq 12.17).  Only lift surfaces
   (`|n_z| ≥ |n_y|`) contribute.  Mirror trailing vortices are included for `parity ≠ 0`
   using the same convention as `horseshoe_influence`: the mirror of a direct trailing at
   `(y_v, z_v)` with strength `s` is placed at `(-y_v, z_v)` with strength `-parity·s`.
   `solve_rigid_cl` calls `trefftz_cdi` and adds `"CDi"` and `"e"` to its return dict.

2. **`tests/aero/test_vlm.py`** — new `TestTrefftzInducedDrag` class (6 tests):
   - `test_keys_present`: CDi and e keys exist in the solve_rigid_cl return dict
   - `test_cdi_positive`: CDi > 0 for α > 0
   - `test_oswald_near_unity`: e ∈ (0.85, 1.05) for rectangular AR=16 wing
   - `test_cdi_cl_identity`: CDi = CL²/(π·AR·e) to 1e-9 relative tolerance
   - `test_cdi_scales_as_alpha_squared`: CDi(2α)/CDi(α) ≈ 4.0 within 1%
   - `test_cdi_zero_at_zero_alpha`: CDi < 1e-12 at α = 0

3. **`docs/10_standard/05_aeroelastics.md`** — CDi and e entries added to the `solve_rigid_cl` return
   dict documentation, including the normalisation formula and expected e range.

**Key decisions:**
- `CDi = Σ Γ·w_T·Δy / S_ref` (no extra ×2): the Trefftz formula has a ρ/2 prefactor
  that exactly cancels with the 1/q = 2 in the CDi normalisation, so w_T (full 2-D
  Biot-Savart, factor 1/(2π)) is used without an additional factor.
- For heuristic reference geometry (no AEROS card), the physical AR is computed as
  `(2·max_y)² / (2·S_ref_half)` for half-span models to avoid the factor-of-2 error
  that arises from using `b_ref² / S_ref_half` directly.
- When AEROS is provided, `ar = bref² / sref` is unambiguous (AEROS always carries
  full-wing geometry).
- `parity = -1` (antisymmetric): CDi = 0.0, e = nan — consistent with CL = 0 convention.

**Test / Acceptance:**
- 6 new tests pass; full aero suite remains 124 passing, 0 failures.
