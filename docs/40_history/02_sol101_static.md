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


## Issue #38: CROD / PROD / CONROD rod element + line-element registry ✅ COMPLETE (2026-10-24)

**Tier L** (new cards, new element physics, first per-element interface). Milestone v0.3.0.
Design note agreed before code per CLAUDE.md rule 1:
`docs/30_future/designs/rod_element_crod.md`. Activated from the Structural-fidelity route
of `30_future/02_parked.md` (consumer: engine-pylon struts, previously `CBAR PA=PB=56`).

**Objective:** a true axial + torsion rod (`EA/L`, `GJ/L` along GA→GB, no bending, no
orientation vector) and the minimal per-element interface that lets assembly, GPWG,
recovery and the f06 pick up a second line element without another hard-coded loop.

**Deliverables:**
- `sbeam/model/element.py` (`Crod`, `Conrod`), `model/property.py` (`Prod`),
  `model/bulk_data.py` (`crods`, `conrods`, `prods`); parser handlers `_handle_prod`,
  `_handle_crod`, `_handle_conrod`, shared `_check_unique_eid` (EIDs one space across
  CBAR/CROD/CONROD/CBUSH) and the PBAR/PROD PID space.
- `sbeam/assembly/elements.py` — the registry: `LineElement` record, `line_element`,
  `iter_line_elements`, `line_element_mass_global`, `line_element_mass_per_length`,
  `rod_frame`, `rod_local_stiffness`, `rod_local_mass`, `rod_section`. `stiffness.py`,
  `mass_matrix.py` and `gpwg.py` loop through it (CBAR entry wraps the #20 helpers, bit-identical).
- `sbeam/solver/element_recovery.py` — `local_end_forces`, `rod_force_from_local`,
  `rod_stress_from_force`, `recover_line_elements`; the four solver loops (SOL 101, SOL 144
  trim, SOL 144 static, MLOADS) collapsed onto it. `RodForce`/`RodStress` and
  `rod_forces`/`rod_stresses` on every result type.
- `results/f06_writer.py` — `FORCES / STRESSES IN ROD ELEMENTS` blocks (`( C R O D )`,
  `( C O N R O D )`), emitted only when rods exist, after the CBAR blocks, in SOL 101, SOL
  144 and the MLOADS critical sample.
- Viewer: dashed rod traces (model, deformed, mode views), rod table, "Rod Forces" tab,
  rod-only-grid rotation warning. `sbeam_tools/common/mirror.py` unfolds CROD/CONROD.
- `sample/pylon_strut_engine.bdf` — wing stick + CBAR spine + CROD and CONROD struts +
  CONM2 engine, 1g + thrust and 1g subcases.
- Docs: card reference (PROD, CROD, CONROD + limitation row), `03`/`04` guides,
  `01_beam_model.md`, `00_program_overview.md` (tree, V24–V27, limitations, phase table),
  `09_conventions.md` §8 row + §9 bullet, `CLAUDE.md`, `00_INDEX.md`, `02_parked.md`.

**Test/acceptance:** all design-note gates green on first run with the predicted numbers.
V24 δ = 1.0e-4, θ = 1.25e-2, σ = 1.0e7, τ = 1.0e6 (1e-10); V25 N1 = 1060.660172,
N2 = 353.553391 (1e-9); V26 35.588127 / 61.640444 Hz exact (1e-8), 35.403 / 61.320 Hz with
ρ = 7850 (−0.5 %); V27 CROD ≡ CBAR 56 at 1e-12. `tests/assembly/test_rod_element.py` (G5
invariants, G5b frame independence, registry bit-identity, G7 assembly coverage),
`tests/solver/test_rod_recovery.py` (G6 `srod1.f`/`srod2.f` mapping at 1e-13, G7 recovery
coverage), `tests/parser/test_rod_cards.py` (G8), `tests/results/test_f06_rod_blocks.py`
(labels, DEF-M13 alignment, rodless listing unchanged), `TestValPylonStrutEngine`
(engine-grid free body to 1e-9, reactions = GPWG weight and thrust, both rod blocks).
Non-regression: the seven shipped sample outputs (f06, loads BDF, CSV) byte-identical to
`0108f76`; `TestG5SingleSource` and the import-boundary gate untouched.

**Key decisions:**

1. **Registry, not Protocol (D1).** Per-type functions in `assembly/`, model dataclasses
   stay plain data; the CBAR entry is the old arithmetic verbatim.
2. **Rod frame independence (D2).** Full 12-DOF frame with a deterministic `e_y`; the rod's
   `K` and `M` make the global matrices independent of it (gate G5b), so the rod reuses the
   scatter, `K·T·u` recovery and `bar_internal_resultants` unchanged.
3. **Consistent translational mass, no torsional inertia (D3).** MSC `COUPMASS` form; a
   strut and its CBAR spine share one mass formulation.
4. **CONROD natively (D4).** `rod_section` is the only code that knows the difference; no
   synthetic PIDs.
5. **Rod-only grids are the user's SPC (D7).** No AUTOSPC; documented in three places and
   flagged by the viewer.
6. **Rod CSV deferred to #31 (D8);** no CBAR element-force CSV exists either.

## Resolved defects

- **DEF-M18** (#21, 2026-10-24, Tier M) — CBAR force table printed raw nodal moments (end A on the opposite face from end B) under half-swapped plane labels (`BENDING-1` = My = MSC plane 2), and the stress table printed totals under NASTRAN's bending-only column names; both outputs moved to the NASTRAN/MSC layout on `bar_internal_resultants` (`M1 = +Mz⁺`, `M2 = −My⁺`; bending-only `SA1–4` + `AXIAL` + `SA/SB-MAX/MIN`), fields renamed (`BarForce.m1_a…`, `BarStress.sa1…`), shipped as a pre-1.0 MINOR breaking change; gates G1–G7 in `tests/solver/test_cbar_force_layout.py` + f06 tests. Design note `30_future/designs/cbar_force_stress_output_layout.md`.
- **DEF-M21** (#37, 2026-10-23, Tier M) — CBAR end-B bending stress sign flipped (one formula on raw nodal moments at both ends) and PBAR I1/I2 planes mislabelled in the card reference; stresses now from +x-face internal resultants via `bar_internal_resultants`, `σ = P/A − Mz·y/I1 + My·z/I2` at both ends, end A bit-identical; gates G1–G6 in `tests/solver/test_cbar_stress_sign.py` and `tests/aero/test_cbar_stress_sign_sol144.py`. Design note `30_future/designs/cbar_stress_recovery_sign.md`.
- **DEF-M17** (#20, 2026-10-23, Tier M) — CBAR PA/PB releases zeroed instead of condensed (element over-stiff, released end forces non-zero); replaced by static condensation of K and congruent M from one helper shared by assembly and recovery, D5 both-ends mechanism check at parse time, gates V21–V23 + 121-combination invariants. Design note `30_future/designs/cbar_pin_release_condensation.md`.

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

