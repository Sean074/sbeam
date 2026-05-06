# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 37
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Completed steps are recorded in `docs/completed_development.md`.

---

## Phase 1 Cleanup

These items are defects and incomplete scope within Phase 1. Resolve before starting Phase 2
dynamic-response work.

**Recommended fix order: B4 (close as doc-only)**

### Open Bugs

| ID | Area | Status |
|----|------|--------|
| B4 | Viewer — f06 import | Close as doc-only |

---

#### B4: Viewer — f06 Import (Close as Doc-Only)

**Description:** `docs/viewer.md` documents a post-processing path that accepts an uploaded `.f06`
file and populates results from it. This feature was never implemented and is out of scope for
Phase 1.

**Resolution:** Remove the f06 import description from `docs/viewer.md`. The "NASTRAN f06 import"
item already exists in the Future Development table below and will be addressed there. No code
changes required.

---

## Phase 2 — Dynamic Response Solvers

Phase 2 adds frequency- and time-domain response to the existing static and modal capability.
All Phase 2 solvers build on the Phase 1 stiffness, mass, and modal results infrastructure.

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

## Phase 2 — Model Enhancements

These items extend BDF card support and solver capability. They are independent of the dynamic
response solvers and can be tackled in any order.

---

### Step 30: Distributed Loads (PLOAD1)

**Objective:** Apply linearly-varying or uniform distributed loads along CBAR elements.

**Scope:**
- `PLOAD1` card: EID, load type (FX/FY/FZ/MX/MY/MZ in local or global), scale, x1/p1, x2/p2.
- Equivalent nodal load vector via integration of the distributed load against shape functions.
- Viewer: distributed load visualisation along element (hatching or shaded arrow strip).

**Why this matters:** uniform distributed loads (self-weight, wind pressure, snow) are the
most common beam load in bridge, building, and wing models.

---

### Step 31: Gravity and Inertial Body Loads (GRAV)

**Objective:** Apply a body acceleration load to all mass-bearing DOFs, enabling self-weight
analysis without manually computing and applying nodal forces.

**Scope:**
- `GRAV` card: SID, CID (phase 2: CID=0 only), N1/N2/N3 acceleration vector, G (magnitude in units/s²).
- Applied load = mass × acceleration, assembled from CBAR element distributed mass and CONM2 masses.
- GRAV can be combined with FORCE/MOMENT sets via a `LOAD` combination card.
- `.f06` output: echo GRAV card in applied-load section.
- Viewer: display gravity arrow in model view when GRAV is the active load.

**Verification:** 1g vertical load on a simply-supported beam; reactions = total structural mass × g.

---

### Step 33: Timoshenko Shear Correction (PBAR K1/K2)

**Objective:** Include transverse shear deformation for stocky beam members.

**Scope:**
- `PBAR` K1 and K2 fields (shear area factors).
- Modified stiffness matrix: Timoshenko beam with shear parameter `φ = 12EI/(κAGL²)`.
- Falls back to Euler-Bernoulli when K1=K2=0 (or blank).
- Verification: short cantilever (L/d = 2) with known Timoshenko tip deflection.

**Why this matters:** important for short, deep members common in bridges and building frames.
Euler-Bernoulli overestimates stiffness significantly when L/d < 10.

---

### Step 34: Non-Zero Enforced Displacements

**Objective:** Support prescribed non-zero displacements at SPC-constrained DOFs.

**Scope:**
- `SPC` D1/D2 fields (currently must be 0 in Phase 1).
- Modify load vector assembly: move non-zero SPC terms to RHS before partitioning.
- Verification: beam with prescribed end rotation reproducing known deflection shape.

**Why this matters:** foundation settlement, support yielding, and displacement-controlled
loading are standard structural assessment scenarios.

---

### Step 35: CONM2 Offset and Inertia Tensor

**Objective:** Full CONM2 support with offset vector and 3×3 inertia tensor.

**Scope:**
- `CONM2` X1/X2/X3 offset fields and I11/I21/I22/I31/I32/I33 inertia terms.
- Offset mass contributes to both translational and rotational DOFs via the parallel-axis theorem.
- Verification: off-axis point mass eigenfrequency compared to analytical value.

**Why this matters:** payload/fuel mass in aircraft stick models is almost never located
exactly at a grid point.

---

## Future Development (Phase 3+)

These items are lower priority or require significant new infrastructure.

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
