# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 39
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Completed steps are recorded in `docs/40_history/00_completed_development.md`.

---

## Code Review — 2026-06-08 — Aerodynamics (Phase A: steady VLM)

Technical-accuracy review of the implemented `sbeam/aero/` module (`panel.py`, `vlm.py`,
`integration.py`, `corrections.py`, `aero_model.py`, `model/aero.py`, parser handlers).
124 aero/parser tests pass. The VLM **core is structurally correct and internally
consistent** — verified: Biot–Savart kernel matches the standard formula; ¼c bound / ¾c
collocation placement correct; 2D limit CL_α → 6.273 ≈ 2π (0.16%); spanwise load symmetric
to 1e-16 at pure α; the symmetry-image path (half parity=+1 vs full parity=0) matches to
~1e-3; two independent lift integrations (Kutta–Joukowski Σγdy vs Σcp·A) agree exactly;
far-field trailing-leg truncation (1000·chord) is converged; AIC well-conditioned (cond ≈ 12
for AR=8, ≈ 38 for the airplane model). Findings A1–A6 below.

New validation case added: `sample/val_vlm_rect_ar8.bdf` (rectangular AR=8 wing, two CAERO1
half-surfaces, parity=0; references documented in the header).

---

---

### [MINOR] A5 — Aero model is reachable only from the viewer; aero cards inert under the solver

**Files:** `sbeam/aero/aero_model.py`, `sbeam/solver/`, `sbeam/main.py`

```
[MINOR] build_aero_model / solve_rigid_cl are called ONLY from viewer/app.py. No solver or
        CLI path consumes the aero model; there is no SOL 144 (Phase C) and no spline
        (Phase B). Therefore the aero cards in airplane_aero.bdf are inert under its declared
        SOL 101, and any aero BDF must declare SOL 101/103 to clear case-control
        (case_control.py rejects SOL 144). val_vlm_rect_ar8.bdf documents this workaround.
FIX: Expected state until Phase B/C land. Track as the Phase B (spline) → Phase C (SOL 144)
        wiring work; add SOL 144 to the case-control whitelist when Phase C starts.
```

---

### [MINOR] A7 — Default chordwise box count too low; no cosine chordwise spacing

**Files:** `sample/airplane_aero.bdf`, `sample/val_vlm_rect_ar8.bdf`, `sbeam/aero/panel.py`

```
[MINOR] Sample models used NCHORD=2 (airplane) / NCHORD=1 (rect val). Lift converges at
        NCHORD=1 (1/4-3/4 rule is 2D-exact), but a chordwise convergence study showed the
        PITCHING MOMENT is grossly under-resolved at low counts: CM shifts ~50% from
        NCHORD 1->2, ~34% 2->4, and only settles to ~1-2% drift by NCHORD~8 (across 0/18/35
        deg sweep). Chordwise loading/pressure are likewise unconverged.
GUIDANCE: Steady VLM minimum NCHORD = 4; recommended 8 for converged moment/loading
        (NASA SP-405 / DeJarnette NASA NTRS — cosine LE-concentrated chordwise spacing
        reaches the same accuracy with fewer boxes). Phase D (DLM) is frequency-driven:
        ~50 boxes per aerodynamic wavelength (Rodden/MSC), roughly 16*k_max boxes/chord. Thpugh this is typically not done with normal convergence at ~4 boxes per wavelength (Sean).
RESOLVED (samples): both sample BDFs updated to NCHORD=8 with guidance comments; box
        counts now 192 (airplane) and 320 (rect val); verified parse/build, CL unchanged.
OPEN (code): mesh_caero1 supports only uniform chordwise spacing via NCHORD (cosine
        requires hand-built LCHORD/AEFACT). Add a cosine-spacing helper / default, and a
        pre-solve warning when NCHORD < 4 on any CAERO1.
```

---

### [MINOR] A8 — Spanwise box count: aspect ratio must be O(1) (companion to A7)

**Files:** `sample/airplane_aero.bdf`, `sbeam/aero/panel.py`

```
[MINOR] A7 fixes the chordwise count; the spanwise count (NSPAN) is the other half of box
        sizing. airplane_aero.bdf shipped with NSPAN=6/4/4, giving box aspect ratios
        (spanwise edge / streamwise edge) of 4-10 — boxes 4-10x longer spanwise than
        chordwise. High-AR boxes degrade the VLM induced-downwash kernel and bias the
        loading; they are also the prime suspect / stress case for the A1 lift-slope bias.
GUIDANCE: Size NSPAN so each box AR is near 1.0; acceptable band 0.5-2.0 (standard VLM/DLM
        practice, NASA SP-405; Rodden/MSC). NOTE the coupling with A7: raising NCHORD
        shortens the chordwise box length, which forces NSPAN UP to keep AR~1. With
        NCHORD=8 and meaningful chords this drives NSPAN high (tens of boxes/edge), so box
        counts grow fast — size the two together, not independently.
RESOLVED (samples): airplane_aero.bdf NSPAN 6/4/4 -> 38/31/16 (wing/HTP/VTP); all 1232
        boxes now AR 0.64-1.63 (mean 0.99); verified parse/build/solve (CL_a~4.17/rad).
        AR computed by reusing mesh_caero1 corner geometry. val_vlm_rect_ar8.bdf already
        OK (AR~1 by construction). HA144A.bdf left faithful to the MSC deck (do not retune).
OPEN (code): (a) add a pre-solve warning when any box AR is outside [0.5, 2.0].
```

---

## Code Review — 2026-05-25

Critical design review performed against `docs/10_standard/07_code_review_process.md`. 15 findings (0 CRITICAL, 4 MAJOR, 7 MINOR, 4 NIT). New items are R12–R22; R9/R10 carry forward. All prior R1–R8 and R11 confirmed resolved. R12 resolved 2026-05-26.

---

### [MINOR] R16 — `docs/10_standard/00_program_overview.md` module table omits `assembly/load_vector.py`; verification table missing V15–V18

**File:** `docs/10_standard/00_program_overview.md:28–44`, `docs/10_standard/00_program_overview.md:163–178`

```
[MINOR] docs/10_standard/00_program_overview.md — load_vector.py is absent from the module structure table.
        Verification cases V15 (GRAV+CBAR mass), V16 (GRAV+CONM2), V17 (GRAV+FORCE via LOAD),
        and V18 (RBE2 lever-arm) exist in test_verification.py but are undocumented.
FIX:    Add load_vector.py row to the assembly/ block; add V15–V18 rows to the
        verification table.
```

---

### [MINOR] R17 — `docs/10_standard/01_beam_model.md:585` "Cards recognised" omits GRAV and RBAR

**File:** `docs/10_standard/01_beam_model.md:585`

```
[MINOR] docs/10_standard/01_beam_model.md:585 — The recognised-cards summary line omits GRAV and RBAR,
        both of which are fully implemented and tested.
FIX:    Add GRAV and RBAR to the comma-separated list on that line.
```

---

### [MINOR] R18 — `docs/10_standard/03_static_analysis.md` "Solver Module" section references stale signatures; omits CBUSH, RBAR, GRAV

**File:** `docs/10_standard/03_static_analysis.md:237–256`

```
[MINOR] docs/10_standard/03_static_analysis.md:237–256 — assemble_load_vector is shown as living in
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

## Open Questions / Risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |

---

## Phase 1 Cleanup

All Phase 1 bugs (B1–B4) are resolved. See `docs/40_history/00_completed_development.md` under Resolved Defects.

---

## Phase A — Static Aeroelastics (VLM)

Steps 39–46 are complete — see `docs/40_history/00_completed_development.md`. Open Phase A
work: **A7** (cosine chordwise spacing helper + low-NCHORD warning) and **A8** (box
aspect-ratio pre-solve warning).

---

## Phase B — Structure ↔ Aero Splining

Steps 45–49. Goal: two CID-aware spline operators — `g_slope` (n_box × n_g) mapping
structural DOFs → per-box streamwise incidence for the VLM solve, and `g_disp` (3n_box × n_g)
mapping structural DOFs → per-box 3-D displacement for virtual-work force transfer.
These feed directly into `coupling.build_qaa` and `coupling.build_fg`.
Prerequisite for Phase C (SOL 144).

**Steps 45 and 46 are complete.** See `docs/40_history/00_completed_development.md`.

---

### Step 47 — ATTACH rigid-body spline + SPLINE0 zero-displacement

**Objective:** Tie box groups rigidly to a master grid (`ATTACH`) and pin selected boxes
(`SPLINE0`), reusing the RBE2 lever-arm kinematic machinery.

**Scope/Deliverables:**
- `Attach` dataclass: `eid`, `caero`, `id1`, `id2`, `grid` (master GRID ID), `cid` (def 0)
- `Spline0` dataclass: `eid`, `caero`, `id1`, `id2`
- Card format (sbeam-defined, ZAERO-inspired): `ATTACH, EID, CAERO, ID1, ID2, GRID, CID`;
  `SPLINE0, EID, CAERO, ID1, ID2`
- `_handle_attach` / `_handle_spline0` in `bdf_reader.py`
- `build_attach_rows(attach, bulk, boxes, grid_index)` in `spline.py`: for each covered
  box j, lever arm `r = box.colloc − master_grid_pos`; the G_kg row encodes the
  rigid-body downwash contribution using the same R-matrix structure from `assembly/rbe3.py`:
  `Gkg[j, col_Tz] = 0` (pure plunge → no incidence), `Gkg[j, col_Ry] = -1.0` (pitch →
  downwash), `Gkg[j, col_Rx] = dthx` (torsion), plus streamwise-offset corrections via lever
- `SPLINE0`: rows stay zero; boxes registered as covered (suppresses un-splined warning)

**Test/Acceptance (V-B3 — machine precision gate):**
- Rigid translation of master → zero downwash on all `ATTACH` boxes
- Rigid pitch of master → uniform downwash = −Ry across all boxes
- `SPLINE0` boxes: `G_kgᵀ @ (any pressure)` → zero force contribution
- Force transfer: uniform pressure on `ATTACH` boxes → `G_kgᵀ @ F_normal` sums to
  correct total force/moment at master grid (analytical lever-arm check)

**Key decisions/risks (KB3):**
- Import lever-arm R-matrix logic from `assembly/rbe3.py`; do not re-implement
- "Splined more than once" check in `build_Gkg` catches any overlap with SPLINE2 coverage

---

### Step 48 — SPLINE1 surface spline (optional — deferrable)

**Objective:** Harder–Desmarais Infinite-Plate Spline for general 2-D grid scatter.

**Scope/Deliverables (deferred — Phase C does not require this):**
- `Spline1` dataclass stub already added in Step 45
- `_handle_spline1` raises `NotImplementedError("SPLINE1 not yet implemented; use SPLINE2")`
- Full IPS kernel `r²ln r²` and `G_kg` rows: implement when a 2-D scatter case arises

**Test/Acceptance (when implemented):** Reproduces rigid-body and linear fields exactly;
matches a published IPS example (Harder & Desmarais 1972).

---

### Step 49 — Force transfer & coupled smoke test

**Objective:** Wire the full rigid-aero → structural load path end-to-end using the
two spline operators (`g_slope`, `g_disp`) from `spline.py` + `coupling.py`, and verify
against an integration fixture.

**Scope/Deliverables:**
- `compute_structural_loads(aero_model, grid_index, q, aoa) → np.ndarray (n_g,)` in
  `aero_model.py` using the `coupling.build_fg` path:
  ```
  cp    = ajj_inv_corr @ (aoa × ones + w_g)
  f_g   = g_disp.T @ (skj @ cp)              # virtual-work consistent force transfer
  ```
  (`g_disp` is already stored on `AeroModel`; `build_aero_model` must receive `grid_index`)
- BDF integration test fixture `tests/integration/bdf/val_spline2_cantilever.bdf`:
  cantilever beam (3–5 CBARs along y-axis) + single CAERO1 + SPLINE2; root SPC all DOFs
- `tests/integration/test_phase_b.py`: builds `AeroModel` with `grid_index`, runs
  `compute_structural_loads` at fixed AOA, checks force balance

**Test/Acceptance (V-B2):**
- Rigid wing at fixed AOA: `sum(f_g[Tz_dofs])` ≈ `q × CL × sref` (< 1% tolerance)
- Pitching moment about root ≈ VLM pitching moment centroid
- With non-zero `w_g`: additional load matches `w_g` contribution in isolation

**Key decisions/risks:**
- Use `g_disp.T @ (skj @ cp)` for force transfer — this is the virtual-work consistent
  path from `coupling.build_fg`. Do NOT collapse to a scalar area projection (that
  discards the 3D normal direction and breaks for non-horizontal surfaces)
- `build_aero_model` already accepts optional `grid_index` parameter (added in Step 46)

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
| Deploy to Streamlit Community Cloud | Provides a live demo URL for the README (nice-to-have) | Viewer complete |
