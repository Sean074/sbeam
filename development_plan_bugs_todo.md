# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 39
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Completed steps are recorded in `docs/completed_development.md`.

---

## Code Review — 2026-05-24

Critical design review performed against `docs/code_review.md`. All 441 tests pass. Findings below.

---

### [MINOR] R2 — Negative eigenvalues silently clipped to 0 Hz

**File:** `sbeam/solver/sol103.py:117`

```
[MINOR] solver/sol103.py:117 — np.maximum(eigenvalues, 0.0) clips negative λ without warning.
WHY:    A negative eigenvalue indicates a non-positive-definite reduced K — typically an
        unconstrained mechanism (model error). Silently returning 0 Hz masks the defect.
        The review standard states: "do not silently take abs(λ)".
FIX:    Before clipping, check: if np.any(eigenvalues < -tol): warnings.warn(...)
        with the number and magnitude of negative eigenvalues.
```

---

### [MINOR] R3 — Duplicate PBAR, MAT1, LOAD SIDs silently overwrite

**Files:** `sbeam/parser/bdf_reader.py:130, 142, 348`

```
[MINOR] parser/bdf_reader.py:130,142,348 — _handle_pbar, _handle_mat1, _handle_load
        overwrite bulk dicts without checking for duplicate IDs.
WHY:    GRID raises ValueError on duplicate GID (line 104); CORD2R, PBUSH, RBAR do too.
        PBAR, MAT1, LOAD, CONM2 are inconsistently unguarded — silent overwrite changes
        the model without any user-visible signal.
FIX:    Add `if pid in bulk.pbars: raise ValueError(...)` before each assignment,
        mirroring the existing duplicate-GRID guard.
```

---

### [MINOR] R4 — Axial stress sign wrong at end A for combined axial+bending

**File:** `sbeam/solver/sol101.py:149`

```
[MINOR] solver/sol101.py:149 — _stress_at_point called with fx_a = f_local[0] for end A.
WHY:    f_local[0] is the force the element exerts on node A in the local +x direction.
        For tension (u_B > 0, u_A = 0): f_local[0] = −EA/L·u_B < 0 and
        f_local[6] = +EA/L·u_B > 0.  The internal axial force P = f_local[6] = −f_local[0].
        Using f_local[0] directly gives σ = f_local[0]/A = −P/A — wrong sign at end A.
        Pure bending (no axial) is unaffected; all current verification tests are bending-only.
FIX:    Use P = f_local[6] (or equivalently −f_local[0]) as the axial resultant
        when computing stress at BOTH ends. Rename the parameter in _stress_at_point
        to `axial_resultant` to remove the ambiguity.
```

---

### [MINOR] R5 — f06 BAR STRESSES writes only recovery point C; D/E/F omitted

**File:** `sbeam/results/f06_writer.py:140–148`

```
[MINOR] results/f06_writer.py:140 — f06 stress table header says "SA(END-A) SB(END-B)"
        and writes only bs.sa and bs.sb (C recovery point). bs.sa_d/sb_d/sa_e/sb_e/sa_f/sb_f
        are computed in recover_bar_stresses but never appear in the output.
WHY:    Users who define PBAR D/E/F recovery points get no output for those points,
        with no warning that they are absent.
FIX:    Extend the f06 block to a multi-line format that lists all four PBAR recovery
        points (C/D/E/F) for each end, or at minimum emit all four points on separate
        rows in the existing table.
```

---

### [MINOR] R6 — Unknown load SID returns zero load vector without warning

**File:** `sbeam/assembly/load_vector.py:68`

```
[MINOR] assembly/load_vector.py:68 — if load_sid is not in bulk.loads, bulk.forces,
        bulk.moments, or bulk.gravs, assemble_load_vector silently returns a zero vector.
WHY:    A typo in the case control LOAD SID will produce a zero-load solution with no
        diagnostic. The solver then reports "successful" with trivially zero displacements.
FIX:    After the if/else, check `if not np.any(f_vec):` and whether load_sid was
        actually found in any load dict; emit warnings.warn if no loads contributed.
        Better: validate load_sid exists before assembly and raise ValueError early.
```

---

### [MINOR] R7 — GRAV assembles mass matrix on every call (performance)

**File:** `sbeam/assembly/load_vector.py:64`

```
[MINOR] assembly/load_vector.py:64 — _apply_grav_to_vector calls assemble_global_mass(bulk)
        on every invocation.  A LOAD card combining two GRAV SIDs assembles mass twice.
WHY:    Assembly is O(n_elements) and for large models with multiple GRAV components is
        unnecessarily repeated.
FIX:    Accept an optional pre-assembled M argument or cache the assembled mass at the
        call site in assemble_load_vector before iterating over LOAD components.
```

---

### [MINOR] R8 — Sparse eigsh path (n > 1,200 DOFs) has no test coverage

**File:** `sbeam/solver/sol103.py:84–112`

```
[MINOR] solver/sol103.py:84 — _solve_modes_sparse is unreachable in all current tests
        because _DENSE_THRESHOLD=1200 exceeds every test model size.
WHY:    The sigma=0 shift-invert path, ArpackNoConvergence fallback, and sparse Tikhonov
        regularisation are all untested.  A regression in ARPACK version or SciPy update
        could break large-model runs silently.
FIX:    Add a unit test that patches _DENSE_THRESHOLD to 0 (or builds a 2-element model
        with n_free > 0) and forces the sparse path, verifying the same frequency result
        as the dense path.
```

---

### [NIT] R9 — `_DENSE_THRESHOLD` is a bare magic number

**File:** `sbeam/solver/sol103.py:24`

```
[NIT] solver/sol103.py:24 — _DENSE_THRESHOLD = 1200 is undocumented.
FIX:   Add a comment: # 200 elements × 6 DOFs/node (already exists as inline comment
       in the conditional); or make the basis explicit in the constant name.
```

---

### [NIT] R10 — RBE3 lever-arm simplification undocumented

**File:** `sbeam/assembly/rbe3.py:27–55`

```
[NIT] assembly/rbe3.py:27 — RBE3 maps each reference DOF to a weighted average of the
      same-numbered DOF at independent grids, with no rigid-body lever-arm coupling.
      This is the common simplified formulation (not all codes include cross-DOF coupling).
FIX:  Document the limitation in rbe3.py and in docs/Beam_model.md:
      "RBE3 uses same-DOF weighted averaging; rotation-to-translation coupling across an
      offset is not applied. Use RBAR for kinematically exact rigid connections."
```

---

### [NIT] R11 — `main.py` CLI untested (0% coverage)

**File:** `sbeam/main.py`

```
[NIT] main.py:3–48 — CLI entry point at 0% coverage; no test exercises it end-to-end.
FIX:  Add a smoke test that calls main.main() with a known BDF path and checks that
      a .f06 file is produced without error.
```

---

## Open Questions / Risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q2 | CBUSH with coincident GA/GB raises ValueError, but only at assembly not at parse time — parser (bdf_reader.py:396) does check. OK for Phase 1. | Low | Resolved |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |
| Q4 | Sparse eigsh path (#R8) — untested. Risk: SciPy ARPACK update breaks large-model runs silently. | Medium | Open |
| Q5 | Does RBE2 non-coincident lever arm affect any shipped example BDFs? All test BDFs use coincident grids — need to verify sample models. | High | Open |

---

## Opportunities

| ID | Opportunity | Effort | Value |
|----|-------------|--------|-------|
| O1 | ~~Fix RBE2 lever arm (R1) — reuse the RBAR R matrix already in the same function~~ **DONE** | Small | High |
| O2 | Add negative-eigenvalue warning (R2) — one `warnings.warn` call | Trivial | Medium |
| O3 | Add PBAR/MAT1/LOAD duplicate guards (R3) — three `if id in dict` checks | Trivial | Medium |
| O4 | Fix end-A axial stress sign (R4) — change `fx_a` to `-f_local[0]` or `f_local[6]` | Trivial | Medium |
| O5 | Extend f06 stress to D/E/F points (R5) — loop over recovery point dict | Small | Medium |
| O6 | Warn on missing load SID (R6) — one `warnings.warn` call after assembly | Trivial | Medium |
| O7 | Test sparse eigsh path (R8) — patch threshold in pytest | Small | Medium |

---

## Phase 1 Cleanup

All Phase 1 bugs (B1–B4) are resolved. See `docs/completed_development.md` under Resolved Defects.

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
| PLOAD1 — Distributed Loads | Equivalent nodal load vector for linearly-varying / uniform loads along CBAR; viewer load visualisation. Deferred because VAL1 pre-solve validator must warn on unsupported cards before silent-drop risk is acceptable | VAL1 complete |
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
