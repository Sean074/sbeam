# Completed Development — SOL 101 Static Solver

Part of the completed-development record (index: `00_completed_development.md`).
Covers the SOL 101 static solve path: stiffness assembly, loads/SPC, displacement and
force/stress recovery, f06 output, GPWG, and resolved SOL 101 defects.

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


## Resolved defects

### Q1 — SPC reactions written in basic CID 0 instead of the grid CD frame ✅ FIXED (2026-08-03)

**Objective:** Q1 sat in the backlog as "verify intentional", on the premise that *NASTRAN
outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame*, so the code
already matched. The premise is wrong. In MSC/NX Nastran the **global coordinate system is
the assembly of the per-grid `CD` frames**, not basic CID 0 — displacements, SPC forces and
grid point forces are all reported there. So the accepted "close it with a doc line" outcome
would have documented a defect as a convention. Reopened as a fix.

The symptom is also internally visible: `f06_writer.py` applied `_transform_to_cd` to the
DISPLACEMENT block but not to the SPCFORCE block, so a deck with `CD ≠ 0` on a constrained
grid emitted displacements and reactions in **different frames** in the same listing. It
further contradicted `01_beam_model.md`, which already claimed `cd` was "preserved for
output transformation of nodal results".

**Deliverables:**
- `results/f06_writer.py` — the SPCFORCE loop rotates through the existing
  `_transform_to_cd` helper, matching the displacement block.
- The rotation is **write-time only**. `Sol101Result.reactions` stays in basic CID 0:
  `results/section_cuts.py` (`_scatter_reactions`) and the MONPNT3 integrators consume
  those vectors as basic-frame quantities, and rotating the stored values would corrupt
  every section cut and monitor point on a `CD ≠ 0` model.
- `docs/10_standard/03_static_analysis.md` — "SPC Reaction Forces" now states the
  recovery frame, the output frame and why they differ.

**Key decision — recover in basic, report in CD.** Basic is the correct *recovery* frame
because SPC/SPC1 DOF digits are themselves basic: nothing in `model/constraint.py` or
`assembly/reduction.py` reads `grid.cd`. That residual asymmetry (a `CD ≠ 0` grid is
restrained along basic axes but reported along `CD`) is a real limitation rather than a
bug, and is now documented in the Known Limitations index rather than silently implied.

**Test/Acceptance:** `tests/results/test_f06_sol101.py::TestSpcForceCdFrame` — three cases
on the reference cantilever: `CD = 0` still writes the raw basic reaction (guards against
an unwanted rotation on the overwhelmingly common path); `CD = 90°` about Z writes
`(Fy, −Fx, Fz, My, −Mx, Mz)`, checked component-by-component against the basic vector; and
`result.reactions` is byte-identical before and after the write, pinning the
presentation-only contract that `section_cuts` depends on. Full suite green
(1744 passed, 6 xfailed) — no existing test asserted the old frame, since every
verification deck uses `CD = 0`.

---

### DEF-R6 (SOL 101 share) — full-SVD `np.linalg.cond(K_free)` on the dense RBE3 path ✅ COMPLETE (2026-08-02)

**Objective:** The dense solve branch (RBE3 transformation collapses K to dense) ran a full
SVD for the singularity check, then solved the same matrix again with `scipy.linalg.solve`.

**Deliverables:** `solver/sol101.py` — one `estimate_cond_1norm(K_free)` (LU + LAPACK
`gecon` 1-norm estimate, `sbeam/linalg_utils.py`) whose LU is reused by `lu_solve` for the
solve. The 1e15 threshold and the "unconstrained DOFs" error are unchanged; the sparse
`spsolve` path is untouched.

**Test/Acceptance:** SOL 101 suite (incl. RBE3 cases) unchanged and green. Part of the P9
batch — see `05_aero_vlm_spline.md` "Performance".

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

