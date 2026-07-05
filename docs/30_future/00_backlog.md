# sbeam — Development Plan, Bugs & To-Do

Authoritative backlog of open bugs, in-progress work, and planned development. Updated as
part of every session that completes a step — never deferred. Completed steps are recorded
in `docs/40_history/00_completed_development.md`. When an item is promoted to a formal
step, give it a step number continuing from Step 39 and apply the same step format
(Objective, Deliverables, Test/Acceptance).

---

## Aeroelastic completion plan — steady (Phase A/C) close-out

**Reviewed 2026-07-03.** The steady aeroelastic capability (Phase A VLM + Phase C SOL 144
trim) is feature-complete except for the items below. Everything previously closed —
Steps 39–58, AE1 acceptance, AE2–AE7/AE9/AE10/AE11, Step 52/53/55/56/57/58, monitor points
Phase 1, Phase G0 increment 1, AE13, A5 — is recorded in
`docs/40_history/00_completed_development.md` and CHANGELOG `[Unreleased]`.

**Scope decision (2026-07-03):** this plan targets *steady-complete* only. The Phase G0
transient follow-ons (G0-b/c/d/e) and the DLM/flutter work are out of scope and listed
under "Future development" at the bottom of this file. GUI work closes the small display
and export gaps; SOL 144 case *authoring* stays BDF-only (recorded as a future item).

**Step AC1 (documentation scrub) CLOSED 2026-07-03** — widened to a full project-documentation
review (README, card reference completion incl. an RBE2 correctness fix, program overview,
viewer doc, beam-model/card-reference de-duplication); see `docs/40_history` and CHANGELOG.

**Steps AC2 (AE8b) and AC3 (AE8a) CLOSED 2026-07-05** — the MSC unrestrained-derivative
algorithm was sourced (MSC Aeroelastic UG Eqs. 2-111…2-134, `.refs/`) and implemented
(`_compute_unrestrained_derivs`, all six q=40 columns within 1%, operator proven by an
independent ZAERO Ch.12 modal cross-check); AE8a root-caused to a W2GJ sign-convention
inversion (fixed) plus a documented ≤0.31% FS residual. See `docs/40_history` and CHANGELOG.
The close-out surfaced a NEW finding — AC7 below (high-q flexible-coupling fidelity).

**Step AC7 (AE14 high-q flexible-coupling fidelity gap) CLOSED 2026-07-05** — TWO root
causes: (1) the full-span HA144A deck had not doubled the centreline fuselage PBAR when
mirroring (masses doubled, stiffness not) — fuselage flexure ran 2x, driving most of the
5–28% q=1200 derivative errors AND the entire AE8a "accepted trim bias" (now superseded:
q=40 trim matches NASTRAN Listing 7-2 to 5 digits); (2) SPLINE2 rewritten as the NASTRAN
infinite beam spline (MSC UG Eqs. 2-48…2-63; CID y-axis convention, rigid chord arms,
DTOR/DTHX/DTHY/DZ semantics, collinearity restriction removed), with the MSC HA144A
SET1/DTHX card values restored. q=1200 CZα/CZq/CMq gated live (≤2/2.5%); the remaining
moment/ELEV residual is re-scoped as Step AC8 below. See `docs/40_history` and CHANGELOG.

**Step AC4 (AE12/A7/A8 minor solver warnings) CLOSED 2026-07-05** — SPLINE2 DTOR/DTHZ
now warn when carrying values sbeam ignores; `build_aero_model` warns pre-solve on < 4
chordwise boxes and box AR outside [0.5, 2.0] (VLM panels only; PSTRIP strips exempt);
`panel.cosine_chord_fractions` added for LE-concentrated LCHORD/AEFACT spacing. The
close-out **exonerated AE12 as AC7's prime suspect** (HA144A cards carry only the benign
detached DTHZ=−1.0/default DTOR=1.0 — NASTRAN does no Rz coupling there either).

| Step | Item | Kind | Priority | Notes |
|-----:|------|------|----------|-------|
| AC5 | [GUI — close the small viewer gaps](#step-ac5--gui--close-the-small-viewer-gaps) | Code | Medium | Exports, totals, body-panel display, doc reconcile |
| AC6 | [Step 54 — CFD/WT steady-pressure injection (CHORDCP)](#step-ac6--step-54--cfd--wind-tunnel-steady-pressure-injection-mean-flow-trim) | Code | Optional | Steady-complete can be declared without it |
| AC8 | [AE15 — wing-root interference residual](#step-ac8-minor-ae15--wing-root-interference-residual) | Code | MINOR | q=1200 moment/ELEV columns 3–5% off; canard-wake/root region, steady VLM vs k→0 DLM |

---

### Step AC8 [MINOR] AE15 — Wing-root interference residual

**Files:** `sbeam/aero/vlm.py` (horseshoe kernel / trailing legs), `sample/ha144a_fullspan_sbeam.bdf`.

**What remains of AE14 after the AC7 close-out (2026-07-05).** With the fuselage-PBAR
doubling and the NASTRAN beam-spline rewrite, HA144A q=40 restrained columns are all
≤0.2% and q=1200 CZα/CZq/CMq pass live 2/2.5% gates. The residual:

```
[MINOR] EVIDENCE — q=1200 vs Table 7-1 (beam spline + 2x fuselage, 2026-07-05):
        restrained:   CMα +4.30%   CZδe −2.90%   CMδe +5.23%   (CZα −1.53%, CZq −0.95%, CMq +2.02% pass)
        unrestrained: CMα −4.33%   CZδe −3.62%   CMδe +5.28%   (CZα −1.90%, CZq −1.25%, CMq −2.28% pass 2.5%)
ATTRIBUTION (pinned-state per-box comparison vs Listing 7-2 box forces at NASTRAN's
        exact trim state): canard boxes match ≤0.2% each; wing outboard LE columns ≈1.008;
        the mismatch concentrates in the WING-ROOT TE boxes (i_span 0–3, j_chord 2–3,
        y ∈ 0–5 ft) — directly behind the canard. Steady VLM horseshoe trailing legs vs
        NASTRAN k→0 DLM model the canard-wake/wing-root interference differently, and the
        flexible increment weights exactly that region. Structure/spline/operator all
        verified independently (see Step AC7 in docs/40_history).
CANDIDATE APPROACHES: wake-position sensitivity study (trailing-leg geometry through the
        wing root), finer canard/root chordwise mesh comparison, or accept as a kernel
        difference and keep the xfail gates documented.
ACCEPTANCE (to CLOSE): either the six xfailed q=1200 moment/ELEV gates
        (tests/aero/test_ae1_restrained_derivs.py::TestRestrainedDerivsQ1200/
        TestUnrestrainedDerivsQ1200 residual halves) pass at 2%, or a study documents the
        kernel-difference attribution quantitatively and the residual is accepted.
```

---

### Step AC5 — GUI — close the small viewer gaps

**Objective:** Bring the Streamlit viewer up to parity with the solver output surface for the
steady aeroelastic results it already runs. (Audit 2026-07-03 of `sbeam/viewer/` vs solver
capability.)

**Deliverables:**
- **Maneuver exports:** wire `results/maneuver_output.py` into the maneuver results tab
  (`viewer/results_view.py::_render_sol144_maneuver`) — download buttons for the MLDPRNT
  ASCII time-history and the critical-sample `FORCE`/`MOMENT` BDF
  (`<stem>.maneuver_qs_loads.bdf`). Currently the tab is plots-only.
- **F06 export for maneuvers:** `_render_f06_export` covers SOL 101/103 and SOL 144
  trim + divergence only; add the `ManeuverResult` block.
- **Missing trim totals:** `_render_sol144_trim` shows only CZ/CL_wind/CMy metrics; surface
  the total CX/CY and roll/yaw totals already computed in `sol144.py`.
- **Body-panel visualization:** `viewer/aero_view.py::build_aero_box_figure` draws
  strip/cruciform body boxes as ordinary boxes — colour/legend-distinguish body panels
  (`AeroBox.is_strip` flag / PSTRIP PID) so users can see what the body correction acts on.
- **Run-summary string:** `_summarize_sol144` always lists "trim vars, stability derivatives,
  q_div, displacements" — make it reflect hinge moments, monitor loads, and maneuver output
  when the model/case requests them.
- **Viewer doc reconcile:** `docs/10_standard/06_viewer.md` executive-control section
  documents only the SOL 101/103 run paths while a later section documents SOL 144
  (`app.py::_run_sol144`) — reconcile, and document the new export buttons.

**Out of scope (recorded under Future development):** a SOL 144/MLOADS case-control
*authoring* UI — TRIM/AESTAT/AESURF/DIVERG/MLOADS/MLDTIME/MLDCOMD/TABLED1 remain BDF-authored;
the viewer runs and displays them.

**Test/Acceptance:** run the viewer against `sample/ha144a_fullspan_sbeam.bdf` (trim) and an
MLOADS sample end-to-end — trim totals visible, body panels visually distinct on a
strip/cruciform deck, maneuver time-history + critical-load downloads produce the same files
as the CLI run, f06 export includes the maneuver block; AppTest coverage per
`docs/10_standard/06_viewer.md` conventions.

---

### Step AC6 — Step 54 — CFD / wind-tunnel steady-pressure injection (mean-flow trim)

**Optional** — lower priority; steady-complete can be declared without it (it stays open here
if not taken).

**Objective:** Allow the trim mean-flow aerodynamics to be supplied directly from CFD or
wind-tunnel steady pressures, so the trim solution is a perturbation about the measured
operating point.

**Scope/Deliverables:**
- `CHORDCP` card supplies a per-box steady `{cp}` (or per-strip load) at a stated
  reference angle of attack; `Chordcp` dataclass + handler
- `sol144.py` replaces the program-computed mean-flow rigid load with the injected
  distribution, reusing the Step 43 pressure-/force-matching machinery; trim variables
  then perturb about the injected state
- Require the reference AOA on the `CHORDCP` card; document the operating-point
  bookkeeping

**Test/Acceptance:** Injecting the program's own inviscid mean-flow reproduces the
Step 52 result (identity); injecting a scaled distribution shifts the trimmed AOA by
the expected amount; total injected lift/moment matches the supplied integral.

**Risk (KC7):** Operating-point/reference-AOA mismatch — validate and warn.

---

## Open questions / risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |

---

## Future development — out of scope for the steady close-out

### SPLINE9 — FE-consistent Hermite beam spline (design proposal, 2026-07-05)

An sbeam-extension spline card offering the cubic-Hermite transfer (exact reproduction of
the CBAR displacement field between grids, twist directly from grid rotations) as an
alternative to the NASTRAN infinite beam spline SPLINE2 implements since AC7. Rebuilt on
the current CID-y-axis conventions with the AC7-found twist-gradient defect fixed — NOT a
revival of the pre-AC7 code. Go/no-go gate: run the coarse-grid convergence study FIRST
(SPLINE9 vs SPLINE2-with-attached-rotations at 3/5/9 EA stations); if SPLINE2 matches
within noise at realistic station counts, close as "not worth the second code path".
Full proposal: [`designs/spline9_hermite_beam_spline.md`](designs/spline9_hermite_beam_spline.md).

### Viewer — SOL 144 / MLOADS case authoring UI (deferred 2026-07-03)

The viewer runs and displays SOL 144 trim/DIVERG/MLOADS subcases but cannot *author* them —
the case-control editor's SOL selector offers 101/103 only and SOL 144 case control is
read-only. A full authoring UI (TRIM condition builder, AESTAT/AESURF/TRIMVAR editors,
DIVERG setup, MLOADS/MLDTIME/MLDCOMD/TABLED1 command-history editor, BDF export) is a
significant effort deliberately deferred; cases are authored in the bulk-data BDF.

### Body cruciform (A9) — follow-ons (open, low priority)

- **A9-a — match body force as well as moment (optional).** A9 is moment-primary: the body's
  lift/side-force is left at the bare VLM value. Add an optional force target (Cz_α/Cy_β and their
  offsets) so the body's CL/CY contribution can be matched to body-isolated CFD too — a second
  constraint per panel in the slope and offset solves.
- **A9-b — canted body panels.** Today the horizontal (+Z) and vertical (+Y) panels are assumed
  axis-aligned (the vertical panel relies on `n_z = 0` for exact pitch/yaw decoupling). Support a
  canted body panel (blended pitch/yaw) via a 2×2 slope solve over both moment metrics.
- **A9-c — automatic body-panel sizing / mesh guidance.** The bare body load is mesh- and
  proximity-sensitive (a panel overlapping/under the wing or tail couples strongly). Add a helper that
  sizes the cruciform from the fuselage planform/profile **and reports the genuine adverse metric — the
  body's induced ΔCp on the lifting-surface boxes** (`ratio_max` alone is a conditioning gauge, not a
  contamination gauge: WT2 is body-row-only, so a large ratio for clear-of-tail panels is benign).
- **A9-d — multi-Mach body targets.** The CSV `TOTAL` block is read at one Mach; extend to a
  per-Mach sweep consistent with the flying-surface per-Mach corrected-BDF export.

### Body aerodynamic panels (slender body) — proper fuselage element (open, medium priority)

The cruciform (A9) is a **flat-plate tuning device**, not a fuselage model, and its limits are now
understood and documented (`docs/10_standard/05_aeroelastics.md` "Geometry & limitations";
`docs/20_theory/01_aeroelastics_theory.md` §3.6): a flat plate makes a *stabilising* bare pitch (wrong
sign for a fuselage), and its authority to move the total moment is the *same* coupling that
contaminates the real surfaces — so it can only supply a **small** mild increment without either
overlapping the tail (spurious) or running an extreme correction. The **decoupled strip body panel**
(Step A10, `PSTRIP`/`STRIPK`, done) is now the recommended *load-only* body stand-in — it removes the
contamination entirely (diagonal block, zero coupling) but, by the same token, carries **no**
interference/fence effect. Large, *predictive* body effects — the destabilising Munk couple, wing-body
interference/carryover, a several-MAC neutral-point shift, real fuselage airloads into the structure —
still need a genuine body element (below), and the **fence boundary condition** needs the image method
(next item).

- **Tier 1 (recommended) — slender body + interference body (NASTRAN `CAERO2`/`PAERO2` style).** A line
  of acceleration-potential doublets (Munk slender-body theory; z-doublets → lift/pitch, y-doublets →
  side-force/yaw) for the body's own load, plus a cylindrical interference body whose image system
  modifies the wing boxes' boundary condition (captures carryover). New: `CAERO2`/`PAERO2` cards + body
  `AEFACT`; a 3-D line/point-doublet kernel (the horseshoe kernel in `vlm.py` won't do); a **block**
  `build_ajj` (`[wing-wing | wing-body; body-wing | body-body]`); body force integration; a real spline
  to the fuselage beam (replacing the SPLINE0 fudge); viewer + theory/standard docs; tests vs Munk
  closed-form dCm/dα ∝ volume and DATCOM wing-body carryover. The interference-tube image method is the
  research risk / long pole. Predictive (no CFD target needed) and fully in the AIC. **Large effort.**
- **Tier 2 — closed vortex-ring/doublet body (sbeam-native).** Wrap the actual cross-sections in a
  closed surface of vortex-ring panels folded into the existing Biot-Savart `build_ajj`; gets lift +
  interference + real shape with current machinery, but no thickness/volume (no sources) and needs a
  Kutta/wake treatment off the body. **Medium-large effort.**
- **Tier 3 — full source+doublet 3-D panel body (ZAERO `BODY7` style).** Highest fidelity (volume +
  thickness + non-circular sections, fully coupled), but effectively a second solver. **Very large.**

Until then, keep the cruciform compact and clear of the empennage (A9 guidance) and use it only for a
mild increment — or use the decoupled strip body (A10), which is placement-free.

### Body fence / no-through-flow boundary condition via image vortices (open, medium priority)

The complement to the decoupled strip (A10). A strip body carries the body's *load* but is transparent
to the wing's flow — it does **not** enforce that a wing box cannot blow through the fuselage (the
fence / carryover effect). By the §3.7 identity, a fence is *necessarily* coupling (it reacts to the
wing's induced velocity), so it cannot live in the decoupled strip element. The cheap, **unknown-free**
way to add it is the **method of images**: reflect each wing horseshoe across the body surface
(mirrored geometry, reversed circulation, as in ground effect) and add the image's Biot–Savart
contribution into the wing-wing block of `build_ajj`. This is the same machinery as the trailing wake
already in `horseshoe_influence` (extra induced-velocity terms tied to the box's own Γ, no new
unknowns), but enforcing no-penetration (transverse reflection) instead of the Kutta condition
(streamwise shedding) — and it is a *physical* reflection, not the cruciform's wrong-sign
contamination. It composes with the strip load device (load + BC as two independent mechanisms).

- **Scope:** an image variant of `horseshoe_influence` (mirror `bound_a`/`bound_b` + the +X trailing
  legs across a plane, reverse sense); fence planes derived from the body geometry (flanks y≈±w/2,
  waterline z) with **footprint gating** (reflect only behind the body extent); wire into `build_ajj`
  via an optional `fence_planes` argument; tests (a wall in isolation reproduces the textbook image
  result; fence raises wing-root loading; strip + fence compose).
- **Caveats to document:** a plane is not a body (planar image exact only for an infinite flat wall;
  finite/curved fuselage ⇒ first-order; gate to the footprint); sbeam is **full-span** so the y=0
  centreline is already present — fence planes go on the body's *outer* surface, not the centreline; a
  perpendicular corner (flank + waterline) needs the 3-image corner construction to stay exact. The
  proper-but-heavier version is the cylinder image (circle theorem) = the Tier-1 interference body.
- **Effort:** small (AIC augmentation only, no new unknowns / no body solve). **Lands after A10** (done).

### Step 48 — SPLINE1 surface spline (optional — deferrable)

**Objective:** Harder–Desmarais Infinite-Plate Spline for general 2-D grid scatter.

**Scope/Deliverables (deferred — Phase C does not require this):**
- `Spline1` dataclass stub already added in Step 45
- `_handle_spline1` raises `NotImplementedError("SPLINE1 not yet implemented; use SPLINE2")`
- Full IPS kernel `r²·ln r²` and `G_kg` rows: implement when a 2-D scatter case arises

**Test/Acceptance (when implemented):** Reproduces rigid-body and linear fields exactly;
matches a published IPS example (Harder & Desmarais 1972).

### Phase G0 — transient maneuver loads (DLM-free): follow-on increments

**Increment 1 is CLOSED (2026-06-13)** — Level-1 quasi-steady (`Ω×r`), open-loop, restrained l-set
Newmark-β integration of the ZAERO `MLOADS` card set (`MLOADS`/`MLDTRIM`/`MLDCOMD`/`MLDTIME`/
`MLDPRNT` + `TABLED1`). See `docs/40_history/00_completed_development.md` (Phase G0 increment 1) and
`solver/maneuver_qs.py`. The increments below build on it; all are **DLM-free** and gated only on
Phase C. Full unsteady MLOADS (state-space / RFA / control law) remains Phase G (gated on the DLM).

#### G0-b — Free-flight rigid-body coupling (self-balancing maneuver)

**Objective:** Instead of prescribing every trim variable open-loop, re-solve the **free** rigid-body
trim variables (e.g. free `URDD`/`ANGLEA`) at each time step so the net (aero + inertial) load
self-balances (closure ≈ 0) for an arbitrary commanded *control* history — the true free-flight
maneuver. Couple the elastic l-set Newmark step to the SUPORT r-set equilibrium (the Step 53 Schur
structure with the Newmark effective stiffness `K̂_ll = a0·M_ll + a1·C_ll + K_eff_ll`), determined
case first; over-determined transient is a further follow-on.

**Test/Acceptance:** commanding a single control (elevator) produces a balanced (closure ≈ 0)
transient whose steady state equals a Step 53 trim with that control prescribed.

#### G0-c — Modal reduction (Level-1b)

**Objective:** Reduce the l-set integration onto restrained mean-axis elastic modes
(`scipy.linalg.eigh(K_ll, M_ll)` or `solve_modes` on the l-set) with mode-acceleration recovery,
honouring `MLOADS NMODES`. Cheaper than the direct l-set solve for large models; exact identity to
the direct solve when all modes are retained.

#### G0-d — Unsteady corrections (Levels 2–4)

**Objective:** Layer the analytic unsteady terms onto the steady VLM forcing: (2) 2-D apparent
(added) mass per strip (`πρb²`-type loads ∝ `α̇`/`ḧ`); (3) tail downwash-lag delay `τ = l_t/V`
(the `C_mα̇` effect); (4) strip Wagner/Theodorsen lift-deficiency. Each is optional on top of the
previous and extends validity beyond `k ≲ 0.05–0.1`.

#### G0-e — Closed-loop control layer (ASE bridge)

**Objective:** Actuator/sensor/control-law models so commands close the loop (vs the increment-1
prescribed control histories). Bridges to the full Phase G ASE system.

### Monitor points & section loads — follow-ons

> **Phase 1 (static `MONPNT1` + `MONPNT3` integrated section loads) is CLOSED (2026-06-13)** —
> see `docs/40_history/00_completed_development.md` and `docs/10_standard/05_aeroelastics.md`.
> The two follow-on phases below remain open. HDF5 hierarchical export is a small deferred add
> (the f06 block + per-case CSV shipped in Phase 1).

#### [MINOR] MON-SYM — Off-centerline monitors on SYMXZ half-span models

A `SYMXZ ≠ 0` half-span build reconstructs the whole-airplane monitor load by mirroring about
the xz plane (symmetric Fx/Fz/My double, antisymmetric Fy/Mx/Mz cancel — fixed 2026-06-13). That
reconstruction is only valid for a monitor reference **on** the symmetry plane (`y ≈ 0`), so an
off-centerline monitor on a half-span model is currently rejected with an error; a full-span
model must be used for wing-station cuts. Lifting this would require integrating the mirror half
about its own (reflected) reference point rather than the on-plane shortcut — deferred, low
priority now that full-span is the default build.

#### Phase 2 (later) — Section-cut running loads

The actual stress-team deliverable: per-station `{Vz, My, Mt}` tables along the wing,
HTP, VTP. Cut convention: plane normal along the spline-axis `x̂` at user-specified
stations (general normal as override). Builds directly on MON3's per-grid tally — a
section cut is "sum the per-grid loads outboard of the cut plane, project to EA
intercept". Lands after Phase 1 + the maneuver trim case (Step 53) — both done, so this
is now unblocked.

#### Phase 3 (later) — Dynamic monitor extraction

CS-25.341(a) discrete 1-cos gust (H = 30–350 ft sweep) and CS-25.341(b) continuous
turbulence (von Kármán PSD → A·σ envelope) at each monitor, with correlated
companion-load extraction for stress. Built on the same monitor data model as
Phase 1. Lands with the SOL 146 / dynamic-response solvers (program Phase 3).

---

## Phase 2 / Phase 3 / Future development (non-aero)

### Phase 2 — Model enhancements

Independent of the dynamic-response solvers and can be tackled in any order. See the
"Future development" table below for the current Phase 2 candidate list.

### Phase 3 — Dynamic response solvers

Phase 3 adds frequency- and time-domain response to the existing static and modal
capability. All Phase 3 solvers build on the Phase 1 stiffness, mass, and modal results
infrastructure.

| Step | Solver | Objective |
|------|--------|-----------|
| 26 | SOL 108 — Direct frequency response | Solve the steady-state harmonic `([K] − ω²[M]){U} = {F(ω)}` over a user-defined frequency range. Cards: `DLOAD`, `RLOAD1/2`, `FREQ`/`FREQ1`; structural damping via MAT1 GE field. Results: complex displacement per DOF per frequency; `.f06` FRF table; viewer FRF amplitude plot. |
| 27 | SOL 109 — Direct transient response | Solve `[M]{ü} + [C]{u̇} + [K]{u} = {F(t)}` by Newmark-β integration (β=0.25, γ=0.5 — unconditionally stable). Cards: `TLOAD1/2`, `TSTEP`. Results: displacement, velocity, acceleration history per DOF; viewer time-history plot. |
| 28 | SOL 111 — Modal frequency response | Modal superposition frequency response using SOL 103 mode shapes as basis. Modal damping via TABDMP1 or critical damping ratio per mode. More efficient than SOL 108 for structures with many DOFs and few modes. |
| 29 | SOL 112 — Modal transient response | Modal superposition transient response using SOL 103 mode shapes as basis. Newmark-β integration in modal coordinates. More efficient than SOL 109 for lightly damped structures. |

### Future development (Phase 3+)

Lower priority or significant new infrastructure.

| Item | Description | Prerequisite |
|------|-------------|--------------|
| PLOAD1 — Distributed Loads | Equivalent nodal load vector for linearly-varying / uniform loads along CBAR; viewer load visualisation. VAL1 complete — viewer warns when PLOAD1 cards are present. S30 can be implemented. | — |
| Timoshenko Shear (PBAR K1/K2) | Modified stiffness with shear parameter φ = 12EI/(κAGL²); falls back to Euler-Bernoulli when K1=K2=0. Deferred because Euler-Bernoulli is the documented Phase 1 assumption; K1/K2 ignored silently, which is correct for slender beams. | Parser update |
| SOL 105 — Buckling | Solve `([K] + λ[K_G]){φ} = 0` for critical load factor; requires geometric stiffness matrix assembled from SOL 101 axial forces. | SOL 101 complete |
| Results export (CSV/Excel) | Download displacement, force, stress tables from the viewer as spreadsheets. | Viewer complete |
| OP2 results export (pyNastran) | Write an OP2 alongside the f06 using pyNastran's vectorized OP2 writer (displacements, eigenvectors, CBAR forces/stresses; later SOL 144 box pressures/forces). Unlocks pyNastranGUI as an external post-processor — stress fringe plots, animated mode shapes, force/bending-moment diagrams, section cuts, CAERO1 panel + spline display — and makes sbeam results readable by any OP2-consuming tool. pyNastran (BSD-3) as an optional/extra dependency; its OP2 *writing* object model is thinly documented — prototype from the pyNastran test suite first. Acceptance: pyNastran round-trips the written OP2 and values match the f06; pyNastranGUI loads and renders a SOL 101 and SOL 103 result. | SOL 101/103 complete |
| Load case envelope | Post-processing: display max/min results across all subcases in a single table; requires B3 (multi-subcase) to be fixed first. | B3 fix |
| PBARL | Define PBAR cross-section by standard shape (ROD, BAR, BOX, I, L, T, …) with auto-computed A, I, J. | Parser |
| Parametric sweep | Vary a geometry or material parameter and plot response curve (e.g. frequency vs stiffness). | SOL 103 complete |
| MAT1 thermal fields | GE (structural damping) already parsed but unused; A and TREF for thermal expansion. | SOL 108 for GE |
| CBEND | Curved beam element for arches and curved frames. | New element formulation |
| NASTRAN f06 import | Read an existing NASTRAN f06 file into the viewer for display and comparison. | Results parser |
| Model pre-solve validator | Interactive check before running: flag zero-length elements, missing SPC, unsupported cards, inconsistent units, unreferenced load/SPC SIDs — displayed as a warning panel in the viewer. | Viewer complete |
| Sample model library | Curated set of BDF example files (cantilever, simply supported, portal frame, 2D truss, airplane stick, multi-span bridge) bundled with the repository for tutorials and regression testing. | Verification suite |
| f06 results comparison | Load two f06 files side-by-side in the viewer; display difference tables and overlay deformed shapes for design-change comparison. | NASTRAN f06 import |
| Deploy to Streamlit Community Cloud | Provides a live demo URL for the README (nice-to-have). | Viewer complete |
