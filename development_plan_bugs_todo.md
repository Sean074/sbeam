# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 39
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Completed steps are recorded in `docs/completed_development.md`.

---

## Code Review — 2026-05-26 (follow-up)

Independent critical pass against `docs/code_review.md`. Status of all prior findings verified.
493/493 tests pass. One CRITICAL (C-1) remains open. M-1 and R9 confirmed resolved; R10 confirmed resolved.
New review found no additional CRITICAL or MAJOR issues.

---

### [CRITICAL] C-1 — `results/f06_writer.py:228` SOL 103 GENERALIZED MASS column hard-coded to `1.0`

**File:** `sbeam/results/f06_writer.py:228`

```
[CRITICAL] f06_writer.py:228 — The GENERALIZED MASS column is always written as 1.0.
WHY: For norm=MASS eigenvectors are M-orthonormal so 1.0 is correct. For norm=MAX
     (peak-component normalisation) the generalised mass is phi^T @ M @ phi, which is not 1.0.
     Any downstream tool that reads the f06 generalized-mass column for norm=MAX receives
     a fabricated value with no warning.
FIX: Pass the reduced mass matrix M_red into _build_f06_sol103_text and compute
     phi_i.T @ M_red @ phi_i per mode. Add a SOL 103 regression test that asserts
     gen_mass == approx(1.0) for norm=MASS and != 1.0 for at least one mode under norm=MAX.
```

---

## Code Review — 2026-05-25

Critical design review performed against `docs/code_review.md`. 15 findings (0 CRITICAL, 4 MAJOR, 7 MINOR, 4 NIT). New items are R12–R22; R9/R10 carry forward. All prior R1–R8 and R11 confirmed resolved. R12 resolved 2026-05-26.

---

### [MAJOR] R13 — EIGRL V1/V2 frequency bounds parsed but never applied ✅ RESOLVED

**Resolved 2026-05-26:** Documented as not implemented. `solve_modes` now emits a
`UserWarning` when V1 or V2 are set; `docs/Modal_analysis.md` corrected to state that
V1/V2 filtering is not supported in Phase 1. V1/V2 filtering is deferred to a future phase.

---

### [MAJOR] R14 — MAT1 G silently set to 0 when only E and nu are supplied ✅ RESOLVED

**Resolved 2026-05-26:** `_handle_mat1` now derives G from the isotropic material relationship
`G = E / (2 × (1 + ν))` when G is blank and both E and NU are non-zero. Supplied G always
takes precedence. `docs/Beam_model.md` updated to document this behaviour explicitly.
Two new parser tests added (`TestMat1GDerivation`).

---

### [MAJOR] R15 — SPC1 reads only one continuation line; extra grids silently dropped ✅ RESOLVED

**Resolved 2026-05-26:** `_handle_spc1` now accepts a list of continuation lines and
accumulates all grid IDs across all continuations, using the same multi-continuation loop
pattern as RBE2/RBE3. Two new parser tests added (`TestSpc1MultiContinuation`).
`docs/Beam_model.md` updated to document multi-continuation support for SPC1.

---

### [MINOR] R16 — `docs/sbeam.md` module table omits `assembly/load_vector.py`; verification table missing V15–V18

**File:** `docs/sbeam.md:28–44`, `docs/sbeam.md:163–178`

```
[MINOR] docs/sbeam.md — load_vector.py is absent from the module structure table.
        Verification cases V15 (GRAV+CBAR mass), V16 (GRAV+CONM2), V17 (GRAV+FORCE via LOAD),
        and V18 (RBE2 lever-arm) exist in test_verification.py but are undocumented.
FIX:    Add load_vector.py row to the assembly/ block; add V15–V18 rows to the
        verification table.
```

---

### [MINOR] R17 — `docs/Beam_model.md:585` "Cards recognised" omits GRAV and RBAR

**File:** `docs/Beam_model.md:585`

```
[MINOR] docs/Beam_model.md:585 — The recognised-cards summary line omits GRAV and RBAR,
        both of which are fully implemented and tested.
FIX:    Add GRAV and RBAR to the comma-separated list on that line.
```

---

### [MINOR] R18 — `docs/Static_analysis.md` "Solver Module" section references stale signatures; omits CBUSH, RBAR, GRAV

**File:** `docs/Static_analysis.md:237–256`

```
[MINOR] docs/Static_analysis.md:237–256 — assemble_load_vector is shown as living in
        sol101.py (it is in assembly/load_vector.py); function signatures are stale;
        CBUSH, RBAR, and GRAV are not mentioned in any verification case.
FIX:    Update module reference, signatures, and add verification cases for GRAV and RBAR.
```

---

### [MINOR] R19 — No integration test for RBAR with non-zero offset

**File:** `tests/`

```
[MINOR] tests/ — V14 covers only the zero-offset RBAR (identity R-matrix); no end-to-end
        BDF + solver test exercises the lever-arm kinematics with a non-coincident RBAR.
FIX:    Add v_rbar_offset.bdf and a corresponding integration test asserting the expected
        lever-arm deflection.
```

---

### [NIT] R21 — `check_spc_enforced_displacements` called unconditionally when `spc_sid` may be `None`

**File:** `sbeam/solver/sol101.py:252–255`

```
[NIT] sol101.py:252–255 — check_spc_enforced_displacements is called even when spc_sid is None.
      bulk.spcs.get(None, []) returns [] safely, so no crash, but the intent is unclear.
FIX:  Add "if spc_sid is not None:" guard before the call.
```

---

### [NIT] R22 — `main.py` imports private (underscore-prefixed) functions from `f06_writer`

**File:** `sbeam/main.py:8`

```
[NIT] main.py:8 — _build_f06_sol101_text and _build_f06_sol103_text are imported by their
      private names. Any rename in f06_writer.py silently breaks the import.
FIX:  Drop leading underscores from both function names in f06_writer.py, or add public
      aliases there.
```

---

## Code Review — 2026-05-24

Critical design review performed against `docs/code_review.md`. All 441 tests passed at review time; 464 pass as of 2026-05-25 (R2–R6 fixes). Findings below; resolved items removed.

---

### [NIT] R9 — `_DENSE_THRESHOLD` is a bare magic number ✅ RESOLVED

**Resolved 2026-05-26 (review confirmation):** `sol103.py:24` already carries the inline
comment `# n_free <= this → use dense eigh (200 elements × 6 DOFs)`. The basis is
explicit and the constant name is self-explanatory in context. No further change required.

---

### [NIT] R10 — RBE3 lever-arm simplification undocumented ✅ RESOLVED

**Resolved 2026-05-26:** Added a block comment in `assembly/rbe3.py` before the RBE3 loop
explaining the same-DOF weighted-averaging formulation and its lever-arm limitation.
`docs/Beam_model.md` updated with a "Known limitation" paragraph in the RBE3 section:
"Use RBAR for kinematically exact rigid connections where the offset lever-arm effect must
be captured."

---

## Open Questions / Risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q2 | CBUSH with coincident GA/GB raises ValueError, but only at assembly not at parse time — parser (bdf_reader.py:396) does check. OK for Phase 1. | Low | Resolved |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |
| Q4 | Sparse eigsh path (#R8) — untested. Risk: SciPy ARPACK update breaks large-model runs silently. | Medium | Resolved |
| Q5 | Does RBE2 non-coincident lever arm affect any shipped example BDFs? All test BDFs use coincident grids — need to verify sample models. | High | Resolved — V18 covers offset RBE2 with 3 analytical assertions; implementation confirmed correct. |

---

## Opportunities

| ID | Opportunity | Effort | Value |
|----|-------------|--------|-------|
| O1 | ~~Fix RBE2 lever arm (R1) — reuse the RBAR R matrix already in the same function~~ **DONE** | Small | High |
| O2 | ~~Add negative-eigenvalue warning (R2) — one `warnings.warn` call~~ **DONE** | Trivial | Medium |
| O3 | ~~Add PBAR/MAT1/LOAD duplicate guards (R3) — three `if id in dict` checks~~ **DONE** | Trivial | Medium |
| O4 | ~~Fix end-A axial stress sign (R4) — change `fx_a` to `-f_local[0]` or `f_local[6]`~~ **DONE** | Trivial | Medium |
| O5 | ~~Extend f06 stress to D/E/F points (R5) — loop over recovery point dict~~ **DONE** | Small | Medium |
| O6 | ~~Warn on missing load SID (R6) — raise ValueError early in assemble_load_vector~~ **DONE** | Trivial | Medium |
| O6 | ~~Cache GRAV mass matrix at call site (R7) — pre-assemble once in assemble_load_vector~~ **DONE** | Small | Low |
| O7 | ~~Test sparse eigsh path (R8) — patch threshold in pytest~~ **DONE** | Small | Medium |

---

## Phase 1 Cleanup

All Phase 1 bugs (B1–B4) are resolved. See `docs/completed_development.md` under Resolved Defects.

---

## Phase A — Static Aeroelastics (VLM)

Steps 39–44 implement the steady vortex-lattice aerodynamic layer.

### Step 39: AEROS card ✅ COMPLETE — see `docs/completed_development.md`

### Step 40: CAERO1/PAERO1/AEFACT parsing + panel.py box meshing ✅ COMPLETE — see `docs/completed_development.md`

### Step 41: Steady VLM AIC `vlm.py` — symmetric + antisymmetric images ✅ COMPLETE — see `docs/completed_development.md`

---

## Phase 2 — Model Enhancements

These items extend BDF card support and solver capability. They are independent of the dynamic
response solvers and can be tackled in any order.

---


---

## Phase 3 — Dynamic Response Solvers

Phase 3 adds frequency- and time-domain response to the existing static and modal capability.
All Phase 3 solvers build on the Phase 1 stiffness, mass, and modal results infrastructure.

---

### Step 26: SOL 108 — Direct Frequency Response

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

### Step 27: SOL 109 — Direct Transient Response

**Objective:** Solve the time-domain equation `[M]{ü} + [C]{u̇} + [K]{u} = {F(t)}` via
numerical time integration.

**Scope:**
- `TLOAD1` / `TLOAD2` cards for time-dependent loading.
- `TSTEP` card for time step and output interval.
- Newmark-β integration (β=0.25, γ=0.5 — unconditionally stable).
- Results: displacement, velocity, acceleration history per DOF.
- Viewer: time-history plot for selected DOF.

---

### Step 28: SOL 111 — Modal Frequency Response

**Objective:** Modal superposition frequency response using SOL 103 mode shapes as basis.

**Scope:**
- Requires prior SOL 103 result (or run internally).
- Modal damping via TABDMP1 or critical damping ratio per mode.
- More efficient than SOL 108 for structures with many DOFs and few modes.
- Same output requests as SOL 108.

---

### Step 29: SOL 112 — Modal Transient Response

**Objective:** Modal superposition transient response using SOL 103 mode shapes as basis.

**Scope:**
- Same modal basis and damping as SOL 111.
- Newmark-β integration in modal coordinates.
- More efficient than SOL 109 for lightly damped structures.
- Same output requests as SOL 109.

---

## Future Development (Phase 3+)

These items are lower priority or require significant new infrastructure.

| Item | Description | Prerequisite |
|------|-------------|--------------|
| PLOAD1 — Distributed Loads | Equivalent nodal load vector for linearly-varying / uniform loads along CBAR; viewer load visualisation. VAL1 now complete — viewer warns when PLOAD1 cards are present. S30 can be implemented. | — |
| Timoshenko Shear (PBAR K1/K2) | Modified stiffness with shear parameter φ = 12EI/(κAGL²); falls back to Euler-Bernoulli when K1=K2=0. Deferred because Euler-Bernoulli is the documented Phase 1 assumption; K1/K2 ignored silently, which is correct for slender beams | Parser update |
| SOL 105 — Buckling | Solve `([K] + λ[K_G]){φ} = 0` for critical load factor; requires geometric stiffness matrix assembled from SOL 101 axial forces | SOL 101 complete |
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
