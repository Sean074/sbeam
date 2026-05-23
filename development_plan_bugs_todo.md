# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 40
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Step 39 (Viewer — Case Control UI Redesign) is complete — see `docs/completed_development.md`.

Completed steps are recorded in `docs/completed_development.md`.

---

## Phase 1 Cleanup

All Phase 1 bugs (B1–B4) are resolved. See `docs/completed_development.md` under Resolved Defects.

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

### Step 39: CSHEAR — Shear Panel Element

**Objective:** Add a flat quadrilateral shear-panel element that carries in-plane shear only,
complementing CBAR frames with membrane shear bracing (wing skins, fuselage panels, shear walls).

**Property card:** `PSHEAR` — thickness `T` and material reference `MID`.

**Scope:**
- `CSHEAR` card: EID, PID, G1, G2, G3, G4 (four corner nodes, ordered CCW when viewed from the
  element normal).
- `PSHEAR` card: PID, MID, T (uniform thickness).
- 8×8 local stiffness matrix (two in-plane translational DOFs u, v per node); no bending or
  drilling stiffness contributed.
- Local frame: e_x = G1→G2, e_z = panel normal (cross product), e_y = e_z × e_x.
- Transform 8×8 local K to global 24×24 block (scatter to Tx/Ty/Tz columns only; rotational DOF
  rows/cols left at zero contribution).
- Assemble into existing 6N×6N global stiffness using the same scatter pattern as CBAR.
- `f06` output: element shear flow q = G·t·γ and shear stress τ = q/t.
- Viewer: render CSHEAR quads as filled semi-transparent polygons; colour by shear stress.

**Implementation options (choose one before starting):**

**Option A — Classical Constant-Shear-Flow (Recommended for Phase 2)**
- Closed-form: assume uniform shear flow throughout the panel.
- Panel area A = ½|d₁ × d₂| where d₁, d₂ are the two diagonals.
- Stiffness coefficient c = G·t·A.
- 8×8 stiffness matrix in local u,v coordinates (standard parallelogram shear panel formula):
  `K_local = c/(2A) × S` where S is the known 8×8 symmetric sign matrix.
- Non-planar quads: project nodes onto best-fit plane before computing local K, then unproject.
- Pros: single closed-form expression, no integration loop, identical to classic NASTRAN behaviour
  for rectangular and parallelogram panels.
- Cons: less accurate for heavily distorted quads.

**Option B — Isoparametric with 2×2 Gauss Quadrature**
- Bilinear shape functions N_i(ξ,η) = ¼(1±ξ)(1±η).
- B-matrix from shape function gradients via Jacobian J(ξ,η).
- Integrate K = ∫∫ B^T · D · B · |J| dξ dη over [-1,1]² with 2×2 Gauss points.
- D = G·t (scalar shear modulus × thickness for pure shear panel).
- Pros: handles general (non-parallelogram) quadrilaterals accurately; more extensible if
  membrane stiffness is added later.
- Cons: Gauss integration loop, ~4× more computation per element.

**Option C — Reduced Integration (1×1 Gauss) with Hourglass Stabilisation**
- Single Gauss point at (ξ,η)=(0,0); avoids shear locking in thin panels.
- Add Hallquist-style hourglass stiffness K_hg = α·G·t·A·H^T·H where H is the hourglass base
  vector and α ≈ 0.03.
- Pros: computationally cheapest; used in production explicit codes.
- Cons: requires tuning of α; overkill for the static/modal use case in sbeam.

**New modules / files:**
- `sbeam/model/element.py` — add `Cshear` dataclass (eid, pid, g1, g2, g3, g4).
- `sbeam/model/property.py` — add `Pshear` dataclass (pid, mid, t).
- `sbeam/model/bulk_data.py` — add `cshears: dict[int, Cshear]`, `pshears: dict[int, Pshear]`.
- `sbeam/parser/bdf_reader.py` — parse CSHEAR and PSHEAR cards.
- `sbeam/assembly/stiffness.py` — add `cshear_stiffness()` and scatter logic.
- `sbeam/results/f06_writer.py` — shear flow / stress output per element.
- `sbeam/viewer/geometry.py` — render CSHEAR quads.
- Docs: `docs/sbeam.md`, `docs/Beam_model.md`, `docs/Static_analysis.md`.

**Test / Acceptance:**
- Unit: 1×1 m square panel (G=80 GPa, t=0.001 m) with two nodes fixed and opposite two nodes
  loaded in shear; compare tip displacement to analytical δ = q·L/(G·t).
- Integration: mixed CBAR frame + CSHEAR panel; verify that panel shear stiffness reduces sway
  displacement vs. frame alone.
- f06: shear flow matches hand-calculation for simple uniform shear loading.

**Why this matters:** Shear panels are ubiquitous in aircraft stick models and structural frames.
Adding CSHEAR lets sbeam handle fuselage/wing hybrid models without a full shell solver.

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
| CTRIA3 — Triangular Shell | Constant-strain triangle (CST membrane + DKT bending); 3-node, 6 DOF/node; property PSHELL; simpler than CQUAD4 and the natural first shell element; no distortion sensitivity; establishes PSHELL property infrastructure for CQUAD4 | CSHEAR complete |
| CQUAD4 — Quadrilateral Shell | Bilinear membrane + Kirchhoff/Mindlin bending shell; 4-node, 6 DOF/node; property PSHELL; combined membrane B-matrix with bending; drilling DOF treatment required for proper in-plane coupling; significantly more infrastructure than CSHEAR or CTRIA3 | CTRIA3 complete |
