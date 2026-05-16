# sbeam — Completed Development

This file is the authoritative record of all completed development steps, key decisions made
during implementation, and resolved defects. It is updated as part of every session that
completes a step — never deferred.

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
- `sbeam/` directory tree matching `docs/sbeam.md` module structure (empty `__init__.py` files, placeholder modules)
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
- `docs/Methods.ipynb` — analytical derivations for Euler-Bernoulli stiffness matrix, consistent mass matrix, coordinate transformation, eigenvalue solution.
- Review and update `docs/sbeam.md`, `docs/Beam_model.md`, `docs/Static_analysis.md`, `docs/Modal_analysis.md`, `docs/viewer.md`.

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
- `tests/integration/test_verification.py` — `TestV14RbarZeroOffset` class.
- `docs/Beam_model.md`, `docs/card_definition.md`, `docs/sbeam.md` — updated.

**Test / Acceptance:**
- V14: zero-offset RBAR — Ty[GID2] matches PL³/3EI; u[GID3] == u[GID2] exactly ✓
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

### B4: Viewer — f06 Import ✅ CLOSED (Doc-Only)

**Description:** `docs/viewer.md` was reported to describe a post-processing upload path for
`.f06` files — a feature that was never implemented and is out of scope for Phase 1.

**Resolution:** Confirmed that `docs/viewer.md` contains no f06 import documentation. The
text was either removed in an earlier session or never formally written into the doc. No code
changes required. The "NASTRAN f06 import" item remains in the Future Development table in
`development_plan_bugs_todo.md` and will be addressed in Phase 3+.

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
- `docs/sbeam.md` — Corrected Python version requirement from 3.10+ to 3.9+ (matching `pyproject.toml` and `README.md`).
- `docs/viewer.md` — Updated `build_deformed_figure` and `build_mode_figure` descriptions to include CBUSH and RBAR in ghost element lists; corrected animation trace indices from `[4,5,6,7,8]` to `[6,7,8,9,10,11]` and added RBAR to the animated trace list.

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
- `docs/card_definition.md` — 17 bulk data cards (CORD2R, GRID, MAT1, PBAR, PBUSH, CBAR, CBUSH, PLOTEL, RBE2, RBE3, CONM2, SPC, SPC1, FORCE, MOMENT, LOAD, EIGRL) plus all case control keywords.
- `docs/sbeam.md` — added reference link to `docs/card_definition.md` in the Purpose section.

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
- `docs/Beam_model.md` — new GRAV card section documenting fields, method, reaction correction, and LOAD combination rules.
- `docs/sbeam.md`, `CLAUDE.md` — GRAV added to supported BDF cards table.
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
