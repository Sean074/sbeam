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

**Steps 45, 46, 47, and 49 are complete.** Step 48 (SPLINE1) is deferred. See `docs/40_history/00_completed_development.md`.

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

## Phase C — SOL 144 Static Aeroelastics, Trim & Divergence

**Goal:** Couple Phases A+B into the structural stiffness to solve the flexible static
aeroelastic problem: trim (determined and over-determined), flexible stability/control
derivatives, optional CFD/WT mean-flow injection, and divergence dynamic pressure.
**Prerequisite:** Phases A and B complete (Steps 39–49).

**Governing equation (g-set reduced to a-set after SPC):**

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg     (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g            (baseline camber/twist/incidence + CFD/WT)
```

---

---

### Step 52 — SOL 144 trim solve + flexible derivatives (`sol144.py`)

**Objective:** Solve the flexible trim problem (determined and over-determined) and recover
stability/control derivatives.

**Scope/Deliverables:**
- `solver/sol144.py`: assemble the augmented trim system (structural equilibrium + trim
  constraints + baseline `f_g` + inertia-relief load `f_inertial = −M_aa · a` from
  prescribed maneuver accelerations)
- **Determined case:** solve the square system directly
- **Over-determined case:** solve by constrained minimization of the `TRIMOBJ` objective
  subject to `TRIMCON` constraints and `TRIMVAR` bounds (least-squares core)
- Recover `u_a`, the free trim variables, flexible `C_Lα`, `C_Mα`, control effectiveness,
  and structural deflection + CBAR loads (reuse `recover_bar_forces`)
- **Rate (damping) aero — quasi-steady `Ω×r` incidence (no DLM):** `ROLL`/`PITCH`/`YAW`
  rate variables get aero load columns from the local incidence a rigid-body rate induces
  via the steady VLM; pitch rate `Δα(x) = q·(x−x_ref)/V∞`; roll rate `Δα(y) = p·y/V∞`;
  yaw rate adds spanwise and directional incidence — captures `C_mq`, `C_lp`, `C_nr`
- Add SOL 144 to the case-control whitelist in `parser/case_control.py`

**Test/Acceptance (V-C1):** Trim a forward-swept / straight wing and reproduce the MSC
NASTRAN HA144A-class flexible-to-rigid derivative ratios; closed-form check vs Bisplinghoff
analytical correction. **(V-C4)** An over-determined case (two control effectors, one
equation) returns the objective-minimizing solution and satisfies the constraints.

**Risk (KC2):** Covered by the Step 51 validator. **Risk (KC6):** Over-determined solution
may be a local optimum — document initial-guess sensitivity (`TRIMVAR INITIAL`).

---

### Step 53 — Balanced maneuver loads & inertia relief

**Objective:** Compute balanced static maneuver loads — symmetric pull-up/push-over at a
load factor, steady roll, steady yaw/sideslip — and output the net (aero + inertial) load
for downstream stress analysis.

**Scope/Deliverables:**
- Each maneuver point is a `TRIM` subcase with prescribed `AESTAT` accelerations/rates and
  load factor
- Assemble `f_inertial = −M_aa · a` by distributing the rigid-body acceleration field over
  the structural mass (`M_aa`, `CONM2`, GPWG; `GRAV` for gravity); solve the trim (Step 52)
  so that aero + inertial + gravity is in equilibrium in the body frame
- Recover deflection + CBAR loads (mode-acceleration recovery when the modal ROM is active)
- Steady rotary maneuvers draw their damping aero from the antisymmetric VLM (Step 41)
- Standard maneuver-case presets: symmetric pull-up/push-over, steady roll, steady sideslip

**Test/Acceptance (V-C5):** Symmetric pull-up at load factor `n_z` — net (aero + inertial)
resultant equals `n_z · W` with zero residual force/moment in body frame; recovered CBAR
loads scale linearly with `n_z`. A free-aircraft (SUPORT-referenced) case balances to ≈0
net force/moment.

**Risk (KC9):** Inertia-relief inconsistent with prescribed accelerations (gravity
double-counted; lumped vs consistent mass) → net imbalance — assert force/moment closure
per maneuver case.

---

### Step 54 — CFD / wind-tunnel steady-pressure injection (mean-flow trim)

**Objective:** Allow the trim mean-flow aerodynamics to be supplied directly from CFD or
wind-tunnel steady pressures, so the trim solution is a perturbation about the measured
operating point.

**Scope/Deliverables:**
- `CHORDCP` card supplies a per-box steady `{cp}` (or per-strip load) at a stated reference
  angle of attack; `Chordcp` dataclass + handler
- `sol144.py` replaces the program-computed mean-flow rigid load with the injected
  distribution, reusing the Step 43 pressure-/force-matching machinery; trim variables
  then perturb about the injected state
- Require the reference AOA on the `CHORDCP` card; document the operating-point bookkeeping

**Test/Acceptance:** Injecting the program's own inviscid mean-flow reproduces the Step 52
result (identity); injecting a scaled distribution shifts the trimmed AOA by the expected
amount; total injected lift/moment matches the supplied integral.

**Risk (KC7):** Operating-point/reference-AOA mismatch — validate and warn.

---

### Step 55 — Aeroelastic divergence (`DIVERG`)

**Objective:** Solve `K_aa φ = q · Q_aa φ` for the lowest positive divergence dynamic
pressure and mode shape.

**Scope/Deliverables:**
- `sol144.py`: generalised eigenvalue solve (reuse the dense path from `sol103.py`); filter
  to the smallest positive real `q`; report `q_div` and `V_div` (given ρ)
- Divergence depends only on `K_aa` and `Q_aa` (the `w_g`/`Q_ax` RHS does not enter the
  eigenvalue)

**Test/Acceptance (V-C2):** Goland wing and an idealised swept cantilever — `q_div` matches
the published / closed-form Bisplinghoff value within a few %.

**Risk (KC3):** Spurious negative/complex eigenvalues from the unsymmetric `Q_aa`; document
the "smallest positive real" selection rule; test against Goland.

---

### Step 56 — SOL 144 f06 output + flight/maneuver-load export

**Objective:** Write the static aeroelastic results to `.f06`, and export the trimmed loads
as `FORCE`/`MOMENT` cards for downstream stress analysis.

**Scope/Deliverables:**
- New f06 blocks in `results/f06_writer.py`: TRIM VARIABLES, STABILITY DERIVATIVES,
  AERODYNAMIC DIVERGENCE, AERODYNAMIC PRES/FORCES; reuse existing displacement and
  CBAR-force blocks
- `results/results.py`: new `Sol144Result` (trim variables, flexible stability/control
  derivatives, divergence q, box pressures/forces, structural displacement, recovered CBAR
  loads, grid flight-load vectors)
- `SubcaseControl` output requests `AEROF` (aero box forces) and `APRES` (aero box
  pressures)
- **Load export:** grid loads as NASTRAN `FORCE`/`MOMENT` bulk-data cards per subcase; for
  a plain trim this is `G_kgᵀ·q·P_k`; for a maneuver case (Step 53) this is the net (aero
  + inertial) balanced load for downstream stress

**Test/Acceptance:** Snapshot/regression test of the f06 text for a sample SOL 144 run;
the exported `FORCE`/`MOMENT` set sums to the total trimmed lift/moment (plain trim) and to
`n_z · W` with zero residual (maneuver case).

---

### Step 57 — Viewer: SOL 144 results

**Objective:** Display trim solution, derivatives, divergence q, deflected shape, and box
`cp` in the viewer.

**Scope/Deliverables:**
- Extend `viewer/aero_view.py` and `viewer/results_view.py`: trim & derivative tables,
  flexible-vs-rigid overlay, `q_div` readout, injected-vs-computed mean-flow overlay when
  `CHORDCP` is active

**Test/Acceptance:** AppTest integration test loads a SOL 144 result and renders all panels
without error.

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
