# Completed Development — Program Foundation, Parser & Infrastructure

Part of the completed-development record (index: `00_completed_development.md`).
Covers project setup, the BDF parser, model enhancements (CORD2R/RBE2/CBUSH/RBAR),
integration & verification, infrastructure (sparse solver, CI, coverage, R-defects),
card-reference documentation steps, and process/documentation reviews.

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


## Resolved defects (documentation / model)

### Pyright-gate restoration (Tier S, hygiene) ✅ COMPLETE (2026-09-05)

Cleared all 127 strict-mode pyright errors so the documented CI type-check gate passes
again: bool/int mask and index arrays retyped (`BoolArray`/`IntArray` instead of
`FloatArray`), missing viewer/results annotations added, Optional accesses guarded,
possibly-unbound variables initialised, and the shared `_FAMILIES` /
`_expand_int_list_with_thru` names made public (`FAMILIES`, `expand_int_list_with_thru`).
No behavior change; full suite 1741 passed / 6 xfailed before and after.

### DEF-M13 (P3, release hygiene batch) — f06 header/data column drift ✅ COMPLETE (2026-08-03)

**Objective:** DEF-M7 fixed the maneuver time-history table's 15-character headers over
13-character `_fmt` data; the identical drift was then measured in five more blocks of
`sbeam/results/f06_writer.py`. Fix them all in one pass and make the class of defect
non-recurring, rather than pinning each block's spacing individually.

**Deliverables:**
- `f06_writer._hdr(lead, *labels)` — new shared helper. `lead` spans the non-numeric
  prefix columns (grid/element ID, TYPE); every remaining label is right-justified in one
  `_FIELD_W` cell, truncated so adjacent cells cannot abut. `_GRID_LEAD` / `_DISP_HDR`
  hoist the grid-row header out as a module constant.
- Converted blocks: `DISPLACEMENT VECTOR` (**four** hand-written copies of the same
  header — SOL 101 displacement, SOL 101 SPCFORCE, SOL 103 eigenvector, SOL 144 divergence
  mode shape — now one constant), CBAR forces, CBAR stresses (including the 7-character
  `PT` column), `MONITOR POINT INTEGRATED LOADS` totals, CBUSH forces, the SPLINE0
  body-load injection echo and the aero box-pressure block. The maneuver table was
  re-routed through `_hdr` too, so there is a single layout mechanism.
- ID labels now end where the ID data ends (`ELEMENT ID.` at 14+2, `BOX ID` at 12+2)
  instead of overhanging by two columns.
- New gate `tests/results/test_f06_column_alignment.py`: over a real full-span HA144A
  SOL 144 listing with `AEROF`/`APRES` on, for every header line the `_FIELD_W` characters
  ending at each numeric column label must parse as a float, and adjacent labels must keep
  at least one space. A `checked >= 30` assertion stops the gate passing vacuously if the
  header parser ever stops recognising headers.

**Test/Acceptance:** the new gate was run against the pre-fix writer and **fails** there
(`column 'FY' … cell '+00 0.000000E' is not a float` on the monitor totals block), and
passes after. Full suite green (1741 passed, 6 xfailed) — no existing layout assertion in
`test_f06_sol101.py` needed changing, because those slice the *data* rows.

**Key decisions:**
- **State the invariant, don't pin the spacing.** The backlog proposed updating the
  assertions that encode current spacing; a general gate is strictly stronger and is what
  would have caught DEF-M7 and DEF-M13 at authoring time. Per-block spacing assertions
  would have to be rewritten by anyone adding a column.
- **The listing format is a deliberate breaking change**, recorded in `CHANGELOG.md`:
  columns move, so anything parsing the `.f06` by fixed column index is affected. Numbers
  were never wrong.
- **Scope taken wider than filed.** The backlog named four blocks and flagged two more to
  "check"; the CBUSH force block was found in the same pass and is the same root cause. A
  partial conversion would have left the defect class alive.

### Doc-pointer sweep (P3, release hygiene batch) ✅ COMPLETE (2026-08-03)

**Objective:** Close the two stale doc pointers from the 2026-07-31 sample-problem review.

**Deliverables:**
- `sample/ha144a_sbeam.bdf` (the half-span HA144A deck, removed by the full-span
  migration) was still named in two sample-deck provenance comments
  (`ha144a_fullspan_sbeam.bdf`, `ha144a_body_trim.bdf`) — reworded to say the deck was
  since removed — and in a copy-pasteable `Test/Acceptance` snippet in
  `docs/40_history/06_sol144_static_aeroelastic.md`, which is now annotated as a
  non-runnable historical record pointing at the full-span equivalent.
- `05a_aero_vlm.md` overstated `tests/aero/test_strip_body.py`'s coupling to
  `sample/cessna210_flagship_section_data.csv`. Verified: that test constructs
  `BodyTargets` programmatically and reads no CSV. The pointer now names the tests that do
  exercise the deck-plus-CSV pair (`test_body_correction.py`,
  `test_cessna210_flagship_body.py`) and says explicitly what `test_strip_body.py` gates.
  (The backlog also mis-named the CSV as `cessna210_body_section_data.csv`; the shipped
  file is `cessna210_flagship_section_data.csv`.)

**Key decision:** **`docs/40_history/` is not rewritten.** Most `ha144a_sbeam.bdf`
citations there are legitimately historical — one of them records the very step that
removed the deck. Only the citation that hands a reader a command that cannot run was
touched, and it was annotated rather than edited, preserving the record of what was
actually executed at the time.

### Q3 — program-level "Known Limitations" section ✅ COMPLETE (2026-08-03)

**Objective:** Q3 asked for the `GRAV` `CID = 0` restriction to be added to "Known
Limitations". On inspection the restriction was already documented — `02_card_reference.md`,
"Constraints and Limitations", `| GRAV | CID must be 0 (global frame only) in Phase 1–2 |`
— and the parser fails loudly rather than silently (`bdf_reader.py:_handle_grav` raises
`ValueError`). The actual gap was structural: **there was no program-level Known Limitations
section at all.** The only such heading in the doc set was aeroelastics-specific
(`05_aeroelastics.md`), so a new user had nowhere to look for "what can this program not
do", and per-card restrictions were discoverable only by reading a 60-row table at the
bottom of the card reference.

**Deliverables:** `docs/10_standard/00_program_overview.md` — a new **Known Limitations**
section (before "Version and Phase") grouped as Theory / Coordinate systems / Loads and
constraints / Output, covering Euler-Bernoulli-only, uniform cross-section, consistent mass,
linear-only, `CORD2R`-only, basic-frame computation, `GRAV` `CID = 0`, `SPC` `D = 0.0`,
CBAR offsets and G0 form, CBUSH restrictions, `MAT1` thermal fields, and the results output
frames. Aeroelastic limitations are linked out rather than restated.

**Key decision — index, not a second source of truth.** The section states each limitation
in one line and links to the authoritative per-card table; it explicitly instructs that new
restrictions be added to `02_card_reference.md` first and linked here. Duplicating the
constraint text would have created two copies to keep in sync, which is how the original
gap (documented in one place, invisible from the other) arose.

Two limitations documented here were **not previously written down anywhere**: that
`SPC`/`SPC1` DOF digits are always basic-frame regardless of the grid's `CD` (surfaced by
the Q1 investigation), and the per-block results output frames — `.f06` displacements and
reactions in `CD`, CBAR forces in element local axes, CBUSH forces in basic, viewer tables
in basic throughout.

**Test/Acceptance:** Documentation only; no code change. Cross-checked every claim against
the source (`bdf_reader.py`, `coord_transform.py`, `f06_writer.py`, `results_view.py`)
rather than against CLAUDE.md.

---

### DEF-R5 + DEF-M9 — one a-set reduction, and SPC-on-a-rigid-DOF is fatal ✅ COMPLETE (2026-08-01)

**Objective:** Close the structural half of the P3 silent-input batch. `reduce_to_aset`
(`assembly/reduction.py`) filtered out any SPC DOF that a rigid element had already eliminated —
silently. The constraint was never applied, the DOF stayed free to follow its master, and no
reaction was reported. Reproduction from the defect report: a 2-CBAR cantilever with grid 3
RBE2-slaved to grid 2 and `SPC1,5,123456,3` solved with `u_z(3) = −8.33e-3` and zero warnings.
NASTRAN fatals on the same m-set/s-set overlap.

**DEF-R5 first (pure refactor, no behaviour change).** `sol101.py:294-311` hand-rolled the same
reduction — including its own copy of the bug — so the fix had to land twice. SOL 103, 144 and
the maneuver solvers were already on the shared path; SOL 101 was the last holdout. Ported onto
`reduce_to_aset`. It is **not** a drop-in: `recover_reactions` needs the unreduced g-set-sized
sparse stiffness, the unreduced load vector and the *raw* SPC DOF list, none of which live on
`AsetReduction`. Resolved by not rebinding `K` at all (so the old `K_orig` copy collapses away)
and calling `get_spc_dofs` directly.

**Fixed in the same commit:** `AsetReduction.expand_to_g` always evaluated `T @ u_red`, and with
no rigid elements `T` is a dense identity — the port would have turned SOL 101's cheap scatter
into an O(n_g²) matvec on every static solve. Added a no-`dep_dofs` scatter fast path (exact:
multiplying by an exact identity is exact).

**DEF-M9.** `rbe3.py` recorded *which* DOFs a rigid element eliminates but not *which element*
owned each one, so the error could not name it. Rather than add a fourth return value —
`build_rbe3_transformation` has 30+ `T, dep_dofs, red_dofs = ...` unpackings across the tests —
the body moved into `_build_rigid_transform(bulk, grid_index) -> (T_full, dep_owner)`, with
`build_rbe3_transformation` (signature unchanged) and a new `dep_dof_owners` as thin wrappers.
`dep_dofs` is literally `sorted()` of the owner map's keys, so the two cannot drift.
`reduce_to_aset` now raises, naming every offending grid/DOF and its owning element, and calls
`dep_dof_owners` **only on the error path** so the happy path pays nothing.

**Key decisions:**
1. **R5 before M9.** Landing the pure refactor first keeps the largest regression surface
   (`test_sol101_recovery::TestReactionRecovery`, the `test_verification` reaction-equilibrium
   cases, V13/V14/V18/V19) bisectable against a known no-op.
2. **Raise, not warn.** Pre-flight over every `.bdf` in `sample/` and `tests/` **and** every
   inline Python-built fixture in `tests/assembly`, `tests/solver` and `tests/integration` found
   **zero** SPC-on-dependent-DOF overlaps, so nothing depended on the silent behaviour.

**Test/Acceptance:** the R5 port was verified numerically inert by hashing displacements,
reactions and CBAR end forces across **31 decks** before and after — bit-identical. New gates in
`tests/assembly/test_reduction.py`: `TestSpcOnDependentDof` (RBE2/RBAR/RBE3 each named in the
message, plus the legitimate SPC-on-the-independent-grid and no-SPC cases) and
`TestDepOwnerMapAgreesWithDepDofs`, which pins the owner map's keys to `dep_dofs` permanently.
All eight new gates confirmed to fail against the pre-fix implementation.

---


### R16–R22: Documentation gaps + NITs (2026-06-12 backlog review) ✅ RESOLVED / removed

Closed and removed from `docs/30_future/00_backlog.md` during the 2026-06-12 backlog
validation review (validated against the MSC HA144A reference).

- **R16** (program_overview.md — module table omits `load_vector.py`; verification table
  missing V15–V18): valid gap at filing (2026-05-25); FIXED by the 2026-06-10 doc
  restructure (`00_program_overview.md:33` row; V15–V18 at lines 190–193). Confirmed via git.
- **R17** (beam_model.md "Cards recognised" omits GRAV/RBAR): MISIDENTIFIED — cited line 585
  is a CAERO1 continuation note; the real summary line (`01_beam_model.md:761`) already
  lists GRAV and RBAR. No edit required.
- **R18** (static_analysis.md stale module ref + missing CBUSH/RBAR/GRAV verification): valid
  gap at filing; FIXED by the 2026-06-07/06-10 restructure. One residual carried forward as
  backlog **R23** (`03_static_analysis.md:307` `recover_bar_forces` signature mismatch).
- **R19** (no non-coincident RBAR lever-arm integration test): MISIDENTIFIED — already
  covered by `tests/integration/test_verification.py::TestV19RbarLeverArm` +
  `tests/integration/bdf/v19_rbar_offset.bdf`.
- **R21** (`check_spc_enforced_displacements` called with possibly-None `spc_sid`): FIXED —
  `if spc_sid is not None:` guard at `sbeam/solver/sol101.py:255`.
- **R22** (`main.py` imports `_build_f06_*` by private name): FIXED — added public aliases
  `build_f06_sol101_text` / `build_f06_sol103_text` in `sbeam/results/f06_writer.py`;
  updated `main.py` and `viewer/app.py` (both were private importers).

**Acceptance:** `tests/solver/` + `tests/results/` pass (59) after the R21/R22 edits;
`import sbeam.main` and the new public aliases verified.

---

### Q5: RBE2 Non-Coincident Lever-Arm ✅ RESOLVED

**Question:** Does the RBE2 lever-arm affect any shipped example BDFs? All test BDFs were believed to use coincident grids.

**Resolution (2026-05-26):** Investigation confirmed that the implementation in `assembly/rbe3.py:76-86` already computes the offset vector `d = r_GM - r_GN` and constructs the full 6×6 rigid-body transformation matrix R for every RBE2 element, correctly coupling rotations at GN into translations at offset GM. V18 (`v18_rbe2_offset.bdf`) exercises a non-coincident RBE2 with GM offset 0.5 m in X from GN and contains three analytical assertions:
- `test_gn_tip_deflection`: u_y at GN matches the eccentric-load cantilever formula (0.1% tolerance).
- `test_gm_offset_deflection`: u_y at GM includes the lever-arm contribution `a × θ_z(GN)` (0.1% tolerance).
- `test_gm_equals_R_times_gn`: all 6 DOFs at GM satisfy `u_GM = R @ u_GN` to machine precision.

All three pass. No shipped BDFs outside `tests/` exist, so no existing models are at risk. Q5 is closed with no code changes required.

---

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

### VAL2: Closed-Form CI Gates for the Four Sample Verification Decks ✅ COMPLETE

**Objective:** Put the four `CLAUDE.md` "Verification Test Cases" under CI. The decks that
embody them — `sample/val_cantilever_static.bdf`, `val_ss_static.bdf`,
`val_cantilever_modes.bdf`, `val_free_free_modes.bdf` — reproduced their closed forms, but
nothing automated executed them: the only exercise was `docs/20_theory/00_beam_methods.ipynb`,
which CI never runs, and the V1–V20 suite in `tests/integration/test_verification.py` gates
its own private decks in `tests/integration/bdf/` (L = 1 m, A = 0.05), not the shipped ones.
A regression in the decks users copy and the docs cite would have reached a release silently.

**Deliverables:**
- `tests/integration/test_sample_verification.py` — 11 tests in four classes, one per deck.
  Solves at the library level (`parse_bdf` → `run_sol101`/`run_sol103`), not through
  `main()`, which swallows solver exceptions into `sys.exit("Solver error: …")`; the CLI/f06
  path is already covered by `tests/test_main.py`. Module-scoped fixture per deck (four
  solves total, 0.6 s).
- Gates: cantilever tip Tz = PL³/3EI, tip Ry = PL²/2EI, root reactions Fz = P and
  My = −P·L; simply-supported mid-span Tz = PL³/48EI and P/2 at each support; cantilever
  f₁ (β₁ = 1.875104) and f₂ (β₂ = 4.694091) with an ascending-order guard; free-free six
  rigid-body modes < 1e-3 Hz, mode 7 elastic with a >1e3 separation ratio, and f₇ against the
  free-free closed form (β = 4.730041).
- No production-code and no CI-config change — `.github/workflows/ci.yml` already runs
  `pytest` over `testpaths = ["tests"]`.

**Test/Acceptance:** 11 tests pass. Measured errors against the closed forms:
tip deflection and tip rotation 1.8e-11 %, mid-span deflection 2.8e-13 %, reactions exact,
f₁ 9.3e-5 %, f₂ 3.3e-3 %, rigid-body modes ≤ 4.6e-5 Hz, f₇ 3.4e-3 %. Each gate was
negative-controlled — perturbing the expected value by the tolerance fails the test.

**Key decisions:**
- **Properties are read back out of the parsed deck** (`_beam_props`), never declared as
  module constants. `test_verification.py:20-26` hardcodes `E`/`I`/`A`/`rho`/`L`/`P` with a
  comment "must match the BDF files" — a silent-drift hazard this module deliberately avoids.
  A physically consistent deck edit therefore keeps the gate honest rather than breaking it.
- **Static tolerance is `rel = 1e-9`, not an engineering tolerance.** The consistent
  Euler-Bernoulli formulation is *exact at the nodes* for point loads, so the measured error is
  round-off (~1e-13 relative); 1e-9 is three decades above round-off and five decades tighter
  than the `rel=1e-3` used by V1–V20. Modal gates carry real discretisation error and run at
  `rel = 1e-5` (f₁) and `2e-4` (f₂, f₇) — 6–11× the measured error.
- **f₂ = 16.16 Hz, not the 2.58 Hz the deck header claims.** `val_cantilever_modes.bdf`'s own
  `SPC1, 1, 12, …` suppresses the XY bending family, so mode 2 is the *second XZ* bending
  mode; mode 4 (71.95 Hz) is the first torsion mode. The stale header comment is left for the
  sample-hygiene batch in `docs/30_future/00_backlog.md`; the module docstring cross-references
  it so the two changes do not collide.
- Deck signs are gated, not just magnitudes: the sample decks load −Z (unlike V1/V3, which
  load −Y), so a convention flip fails rather than passing on an absolute value.

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

### R20: No integration test for CBUSH grounded spring through solver ✅ FIXED

**Root cause:** `tests/assembly/test_cbush.py` covered the CBUSH stiffness matrix, transform, and solver behaviour only through programmatic model construction. No end-to-end BDF file path test existed to exercise the full `parse_bdf → run_sol101` pipeline for a CBUSH element.

**Fix:**
- `tests/integration/bdf/v20_cbush_grounded_spring.bdf` — single-node model: PBUSH K1=5000 N/m, grounded CBUSH, SPC1 releasing only Tx, FORCE 1000 N in +X.
- `tests/integration/test_verification.py::TestV20CbushGroundedSpring` — two tests:
  - `test_displacement_equals_f_over_k` — Tx at grounded node equals F/K = 0.2 m (rel ≤ 0.01%).
  - `test_cbush_force_equals_k_times_u` — CBUSH element force in X equals K × u = F (rel ≤ 0.01%).

**Acceptance test:** 502 total tests pass, 0 failures.

---


---

## Process & documentation reviews

### Documentation — critical design review of `30_future` + backlog restructure + H1/H2 housekeeping ✅ COMPLETE (2026-07-05)

**Objective:** Review every document and design proposal in `docs/30_future/`, assess
viability, and restructure `00_backlog.md` into a priority-ordered plan toward the
strategic aim: a production-like aeroelastic process for different maneuvers and payload
conditions — SOL 144 developed to early-design sufficiency first, then SOL 145 + DLM.

**Deliverables:**
- **`docs/30_future/00_backlog.md` rewritten** as a priority-ordered plan: strategic-aim
  statement; P1–P12 priority table across four tiers (Tier 1 SOL 144 production process =
  Steps 59–63 Phase G0 plan + monitor section cuts + viewer authoring; Tier 2 GAF export /
  matrix reuse / SPLINE9 study; Tier 3 AMODE + DLM/SOL 145/SOL 146; Tier 4 lower priority);
  recorded design-review verdicts for all six `designs/*` proposals; single-owner
  assignments for infrastructure claimed by multiple designs (`reduce_to_aset` → Step 59;
  rigid-basis builder → Step 61, RBMREF folded in; MKAERO1/export bundle →
  `matrix_gaf_export`; SOL 144 dispatch → already exists, Step 56/AC5).
- **Key review findings:** `MASSSET` pulled forward to Step 60 (its static half delivers
  payload sweeps with no modal work); stale prerequisites flagged — the AE4 spline gate in
  `matrix_gaf_export.md`/`dlm_rfa_flutter_gust.md` closed with AC7, and `matrix_reuse_store`
  Phase 0 (SOL 144 production dispatch) already delivered; RBMREF's `B_target` and the G0
  plan's `Φ_r` identified as the same object (previously unmanaged duplication); SOL 108–112
  noted as largely superseded for aero purposes by the G0 solvers + SOL 146; SPLINE9 held to
  its own go/no-go study; G0-d demoted to opportunistic (DLM supersedes), G0-e deferred with
  Phase G.
- **Closed-item summaries removed from the backlog** (AC1–AC8, Phase G0 increment 1,
  monitor Phase 1, Steps 50–58) — verified beforehand that every one has a full entry in
  this file; the backlog now contains open work only.
- **H2 — `02_static_aero_zaero_review.md` archived** to `docs/40_history/archive/`: all 8
  ranked goals had been folded into Steps 39–58 (see the mapping appendix it shipped with),
  all closed — fully actioned review artifact.
- **H1 — `01_static_aero_plan.md` pruned** per its own self-removal rule: the closed
  Step 39–58 bodies (duplicated here) replaced by a one-line delivered-step map; the
  Phase D/E/F/G0/G placeholders retired in favour of `designs/dlm_rfa_flutter_gust.md` and
  the backlog. Retained as a compact architecture reference: layer diagram, matrix
  nomenclature (as-built module map), references, validation-case index (V-A1…V-C6).
- **`docs/00_INDEX.md`** updated for the moved/re-scoped documents; **`CHANGELOG.md`**
  `[Unreleased]` Documentation entry added.

**Test/Acceptance:** documentation-only change — no code touched; backlog contains open
items only (spot-check: no `✅`/CLOSED step bodies remain); all removed summaries verified
present in this file before deletion; INDEX links resolve.

**Key decisions:** the backlog is the single forward plan (the static-aero plan no longer
carries open steps); design proposals keep their own files but their scheduling/verdicts
live in the backlog; housekeeping H3 (stale-prerequisite annotations inside the design
docs) deliberately left open until P8/P10 start, so the docs are corrected when actually
picked up.
