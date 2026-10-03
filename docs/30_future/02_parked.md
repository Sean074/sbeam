# sbeam — Parked Items

Created 2026-08-04 (development process review, `docs/50_reviews/2026-08-04_development_process_review.md`,
R1/R12). Items here are genuine and retain their full write-ups, but they are **not on the
path to the loads mission** stated in `00_backlog.md` — general-FEA completeness, fidelity
completion beyond early-design loads accuracy, tooling polish, and NASTRAN-compat niceties.
Nothing here is scheduled or ranked, and parked items are deliberately **not** GitHub
issues (the tracker holds only open, on-mission work — migration 2026-09-05). To activate
an item, open a GitHub issue carrying its write-up (with a milestone or the
`opportunistic` label and a mission tag) and delete the entry here; do not work parked
items opportunistically without activating them first.

---

## Declared out of scope (2026-08-04)

Recorded so their absence from the plan is a decision, not an oversight. Revisit only if the
mission statement changes:

- **Ground / landing loads** (23.471–.511) — needs landing-gear modeling sbeam does not have.
- **Engine torque / gyroscopic load cases** (23.361/.363) as a case set — the enabling
  thrust-in-trim item (DEF-M4 follow-on) *is* in the backlog; the certification case matrix
  around it is not planned.
- **Unsymmetric gust and one-engine-out lateral case sets** — beyond the steady
  sideslip/yaw-rate trim capability already delivered.
- **Closed-loop control / ASE** — see G0-e below; deferred with Phase G.

---

## Aero fidelity follow-ons

### G0-e — Closed-loop control layer (ASE bridge)

**Objective:** Discrete control-law update `δ_c[n+1] = f(sensor(ξ, ξ̇, ξ̈))` inside the time loop;
actuator lag as a first-order appended state; sensors at grids via the existing spline/recovery
operators. Enables commanded-Nz and the over-determined transient control allocation (reusing the
`TRIMOBJ` null-space QP pattern). ZAERO-ASE-flavoured cards designed at promotion. Bridges to the
full Phase G ASE system. Acceptance sketch: proportional pitch-rate damper reduces short-period
overshoot vs open loop; zero-gain identity to Step 63.

### Propeller whirl flutter (follow-on to #14; recorded 2026-10-02)

**What it is:** a rigid propeller on a flexible nacelle/pylon mount. The pitch and yaw of the
hub couple through:
- gyroscopic damping `J_p·Ω`, a skew-symmetric matrix on the hub rotations;
- propeller aerodynamic stiffness and damping derivatives (Houbolt–Reed / Ribner strip
  integrals).

**How it fits:** the mount already fits the stick model: CBUSH/CBAR pylon (CROD struts, #38), with the rotor inertia on a CONM2. What is missing is a way to add hub-grid `B` and
`K` terms to the PK flutter equation of #14. Two options:
- a generic direct-matrix card (DMIG/B2PP/K2PP style);
- a dedicated propeller card that builds the terms from Ω, `J_p` and the propeller
  derivatives.

**Validation:** Houbolt & Reed, NASA TR R-106 (whirl-flutter stability boundaries), and
Reed's Electra-era results.

**Not from NASTRAN-95:** its rotor/turboprop aero (cascade theories 6/7, rotating-frame
cyclic symmetry, `fvrst1.f` Coriolis) is blade aeroelasticity, not whirl flutter.

**Related:** the out-of-scope engine torque/gyroscopic load cases (23.361/.363) need the same
gyroscopic term.

**Prerequisite:** #14 PK flutter. **Physics step:** needs a design note.

### Body fence / no-through-flow boundary condition via image vortices (small)

The complement to the decoupled strip (A10). A strip body carries the body's *load* but is
transparent to the wing's flow — it does **not** enforce that a wing box cannot blow through the
fuselage (the fence / carryover effect). By the §3.7 identity, a fence is *necessarily* coupling
(it reacts to the wing's induced velocity), so it cannot live in the decoupled strip element. The
cheap, **unknown-free** way to add it is the **method of images**: reflect each wing horseshoe
across the body surface (mirrored geometry, reversed circulation, as in ground effect) and add the
image's Biot–Savart contribution into the wing-wing block of `build_ajj`.

- **Scope:** an image variant of `horseshoe_influence` (mirror `bound_a`/`bound_b` + the +X trailing
  legs across a plane, reverse sense); fence planes derived from the body geometry (flanks y≈±w/2,
  waterline z) with **footprint gating** (reflect only behind the body extent); wire into `build_ajj`
  via an optional `fence_planes` argument; tests (a wall in isolation reproduces the textbook image
  result; fence raises wing-root loading; strip + fence compose).
- **Caveats to document:** a plane is not a body (planar image exact only for an infinite flat wall;
  finite/curved fuselage ⇒ first-order; gate to the footprint); sbeam is **full-span** so the y=0
  centreline is already present — fence planes go on the body's *outer* surface, not the centreline; a
  perpendicular corner (flank + waterline) needs the 3-image corner construction to stay exact.
- **Effort:** small (AIC augmentation only, no new unknowns / no body solve).

### Body aerodynamic panels (slender body) — proper fuselage element

The cruciform (A9) is a **flat-plate tuning device**, not a fuselage model, and its limits are
documented (`docs/10_standard/05a_aero_vlm.md` "Geometry & limitations";
`docs/20_theory/01_aeroelastics_theory.md` §3.6). The **decoupled strip body panel** (Step A10,
`PSTRIP`/`STRIPK`, done) is the recommended *load-only* body stand-in. Large, *predictive* body
effects — the destabilising Munk couple, wing-body interference/carryover, a several-MAC
neutral-point shift, real fuselage airloads into the structure — still need a genuine body element:

- **Tier 1 (recommended) — slender body + interference body (NASTRAN `CAERO2`/`PAERO2` style).** A line
  of acceleration-potential doublets (Munk slender-body theory) for the body's own load, plus a
  cylindrical interference body whose image system modifies the wing boxes' boundary condition. New
  cards + a 3-D line/point-doublet kernel + a block `build_ajj` + a real fuselage spline. The
  interference-tube image method is the research risk / long pole. **Large effort.**
- **Tier 2 — closed vortex-ring/doublet body (sbeam-native).** Wrap the cross-sections in closed
  vortex-ring panels folded into the existing Biot-Savart `build_ajj`; no thickness/volume, needs a
  Kutta/wake treatment. **Medium-large effort.**
- **Tier 3 — full source+doublet 3-D panel body (ZAERO `BODY7` style).** Highest fidelity, effectively
  a second solver. **Very large.**

Until then, keep the cruciform compact and clear of the empennage (A9 guidance) and use it only for
a mild increment — or use the decoupled strip body (A10), which is placement-free.

### Body cruciform (A9) — follow-ons

- **A9-a — match body force as well as moment (optional).** Add an optional force target (Cz_α/Cy_β
  and offsets) so the body's CL/CY contribution can be matched to body-isolated CFD too.
- **A9-b — canted body panels.** Support a canted body panel (blended pitch/yaw) via a 2×2 slope
  solve over both moment metrics.
- **A9-c — automatic body-panel sizing / mesh guidance.** Size the cruciform from the fuselage
  planform/profile and report the genuine adverse metric — the body's induced ΔCp on the
  lifting-surface boxes.
- **A9-d — multi-Mach body targets.** Extend the CSV `TOTAL` block to a per-Mach sweep consistent
  with the flying-surface per-Mach corrected-BDF export.

### CHORDCP (Step 54) — follow-ons

- **S54-a — partial per-surface coverage.** v1 requires every VLM CAERO1 to carry a CHORDCP card
  (one shared ALPHREF). CFD-wing-only injection with the tail on its W2GJ baseline mixes two
  operating points — needs a documented approximation + warning before it can ship.
- **S54-b — viewer CHORDCP authoring.** A path from a per-box Cp table (CSV) to CHORDCP cards +
  corrected-BDF export, parallel to the existing W2GJ+WT2 synthesis in
  `aero_correction_view.py`. Includes the deferred injected-vs-computed mean-flow overlay.

### Monitor points — MON-SYM

Off-centerline monitors on `SYMXZ ≠ 0` half-span models are rejected (the mirror
reconstruction is only valid on the symmetry plane); lifting this needs the mirror half
integrated about its own reflected reference point. Low priority now that full-span is the
default build.

### SPLINE1 surface spline (Step 48 — deferred)

Harder–Desmarais Infinite-Plate Spline for general 2-D grid scatter. `Spline1` dataclass
stub exists; `_handle_spline1` raises `NotImplementedError`. Implement when a 2-D scatter
case arises. Acceptance: reproduces rigid-body and linear fields exactly; matches a
published IPS example (Harder & Desmarais 1972). **Named future consumer (2026-10-02):** the
far-future rod/shear-panel box model (Structural-fidelity route, below), where a beam spline
cannot carry aero loads onto the box.

### SPLINE9 — FE-consistent Hermite beam spline (go/no-go study only)

Per `designs/spline9_hermite_beam_spline.md`: run the coarse-grid convergence study FIRST
(SPLINE9 vs SPLINE2-with-attached-rotations at 3/5/9 EA stations, ~1 d); if SPLINE2 matches
within noise at realistic station counts, **close as "not worth the second code path"
without implementing**. No card plumbing before the study. HA144A validation decks stay on
SPLINE2 either way.

### RBMREF card — thin reporting wrapper

`designs/rbmref_card.md`'s `B_target` construction is owned by Step 61's
`build_rigid_modes`. The RBMREF *card* (user CORD2R reference point, MECH/MASS
normalization, f06 rigid-body block) remains available as a thin optional wrapper
afterwards if the reporting feature is still wanted — do not build a second rigid-basis
path.

---

## Phase 3 — structural dynamic response solvers (SOL 108/109/111/112)

Frequency- and time-domain structural response (no aero). **Superseded for the loads
mission** — the G0 solvers cover transient maneuver response and Phase D's SOL 146 covers
gust — but they remain the right home for structural-only dynamics (ground shake, hammer
tests), and SOL 111/112 share the modal machinery Steps 61–62 built.

| Step | Solver | Objective |
|------|--------|-----------|
| 26 | SOL 108 — Direct frequency response | Solve `([K] − ω²[M]){U} = {F(ω)}` over a frequency range. Cards: `DLOAD`, `RLOAD1/2`, `FREQ`/`FREQ1`; damping via MAT1 GE. |
| 27 | SOL 109 — Direct transient response | Newmark-β (β=0.25, γ=0.5). Cards: `TLOAD1/2`, `TSTEP`. |
| 28 | SOL 111 — Modal frequency response | Modal superposition on the SOL 103 basis; TABDMP1 modal damping. |
| 29 | SOL 112 — Modal transient response | Modal superposition transient; Newmark-β in modal coordinates. |

---

## Phase 2+ — non-aero model enhancements

| Item | Description | Prerequisite |
|------|-------------|--------------|
| PLOAD1 — Distributed Loads | Equivalent nodal load vector for linearly-varying / uniform loads along CBAR; viewer load visualisation. VAL1 complete — viewer warns when PLOAD1 cards are present. S30 can be implemented. On a pin-flagged CBAR the equivalent nodal loads must be condensed with the same transformation as K (`f' = Tᵀf`; `designs/cbar_pin_release_condensation.md` D6). | — |
| Timoshenko Shear (PBAR K1/K2) | Modified stiffness with shear parameter φ = 12EI/(κAGL²); falls back to Euler-Bernoulli when K1=K2=0. K1/K2 currently ignored silently — correct for slender beams. | Parser update |
| CBAR end offsets (WA/WB) | Rigid offset of the element axis from the grid points, applied to stiffness, mass and load recovery (the standard NASTRAN WA/WB fields; `OFFT` is parsed but unused and WA/WB are not parsed). Today an off-axis beam or an off-center applied force must be modeled with explicit RBE2/RBAR lever arms. Found in the 2026-08-01 torsion-capability review. | Parser update |
| Shear-center offset / bend–twist coupling (PBAR I12) | The elastic axis is the grid line by construction: a transverse `FORCE` at a grid produces no twist, which is wrong for sections whose shear center is off the section reference (channels, open sections), and `PBAR` carries no I12, so unsymmetric-section cross-plane bending coupling is absent. Needs the coupled 12-DOF stiffness (I12 terms) and a shear-center eccentricity in the element formulation; until then, model the eccentricity with rigid links. Found in the 2026-08-01 torsion-capability review. | New element formulation |
| Restrained warping (open thin-walled sections) | Torsion is uniform St. Venant `GJ/L` only — no warping DOF, so restrained torsion of open thin-walled sections (I, channel, Z) is predicted too flexible, and warping-driven torsional frequencies come out low. Needs a 7th warping DOF per node (14-DOF element, PBEAM CWA/CWB-style warping constant) or stays a documented limitation. Found in the 2026-08-01 torsion-capability review. | New element formulation |
| SOL 105 — Buckling | Solve `([K] + λ[K_G]){φ} = 0`; requires geometric stiffness from SOL 101 axial forces. Stress-adjacent — the first parked item to revisit once the loads process feeds a stress model. **Validation target (2026-10-02, NASTRAN-95 demo D13-01-1A, `inp/d13011a.inp`):** 100-CBAR hinged–hinged beam, L = 100, A = 2.0, I = 0.666667, E = 10.4e6, ρ = 2.0e-4, axial compression F = 3423.17 (≈ P_cr/2, P_cr = π²EI/L² = 6842.93); prestressed modes f_n = f₀ₙ·√(1 − F/(n²P_cr)) = 14.6197 / 77.3766 / 180.878 Hz (N95: 14.61968 / 77.37659 / 180.8778) — a K + K_G modal gate (rebuild the deck from these numbers; N95 is NOSA 1.3, reference only). | SOL 101 complete |
| PBARL | Define PBAR cross-section by standard shape (ROD, BAR, BOX, I, L, T, …) with auto-computed A, I, J. | Parser |
| MAT1 thermal fields | GE (structural damping) parsed but unused; A and TREF for thermal expansion. | SOL 108 for GE |
| CBEND | Curved beam element. | New element formulation |

---

## Structural-fidelity route (decided 2026-10-02)

**Aim (user decision, 2026-10-02):** better loads *on the stick model*. The primary means are
**rods plus reduction**, not shells. **Far future:** loads may be generated directly on a
more detailed aeroelastic FEM, idealised as rods and shear panels, with no derived beam
model. General shells (CQUAD4/CTRIA3, PSHELL/PCOMP), solids and heat transfer are not on
this route.

The route came out of the 2026-10-02 NASTRAN-95 review. NASTRAN-95 (github.com/nasa/NASTRAN-95,
NOSA 1.3) is used as a theory and benchmark reference only: no code is copied, and decks are
rebuilt from published numbers.

**Activated 2026-10-02:** the element interface and CROD/PROD/CONROD (consumer: engine pylon
struts) moved to issue #38 (v0.3.0) — the write-up lives there.

### Model reduction — ASET/OMIT (Guyan), then Craig–Bampton (near)

Reduce a detailed component (pylon, strut-braced or truss structure) onto the stick/a-set
grids that feed the VLM/DLM chain. It builds on the existing `assembly/reduction.py`
`reduce_to_aset`.

- **Guyan (static condensation)** first.
- **Craig–Bampton** (fixed-interface modes) when component dynamics matter (flutter, #14;
  dynamic gust, #16).

**Validation:**
- the reduced model reproduces full-model static deflections at retained DOFs exactly (Guyan);
- the reduced model's modes converge to the full model's modes as the number of component
  modes grows (Craig–Bampton);
- NASTRAN-95 automated modal synthesis demos `d02031a`+ (reference output in `demoout/`).

*Superelement/substructure-database machinery is not wanted* (already rejected in
`designs/amode_card.md`).

### Rod / shear-panel aeroelastic box model, no beam (far future)

A wing/fuselage box idealised as rods (caps, stringers) plus CSHEAR/PSHEAR webs, with
membrane skins (CQDMEM/CTRMEM-class, in-plane only).

Prerequisites:
- the element interface (delivered with #38);
- an AUTOSPC-style treatment of rotational DOFs that have no stiffness;
- SPLINE1 (or an SPLINE4-type surface spline) to carry aero loads onto the box;
- element-level recovery (shear flows, rod loads) for the stress hand-off.

Monitor points and section cuts need **no** change: they are free-body sums of grid loads and do
not depend on the element type (see the guardrail in `00_program_overview.md`, Architecture).
A grid-point force balance (MSC `GPFORCE`) is needed only for per-element load paths to stress.
NASTRAN-95 has none, so design it from MSC documentation.

**Benchmark:** NASTRAN-95 delta-wing series `d01011a`–`d01014a`. This is a quarter delta wing,
biconvex section: 36 CSHEAR, 48 CROD/CONROD, 17 membranes, with reference output.

---

## Tooling / viewer ideas

| Item | Description | Prerequisite |
|------|-------------|--------------|
| Results export (CSV/Excel) | Download displacement, force, stress tables from the viewer as spreadsheets. | Viewer complete |
| OP1 results export (pyNastran) | Write an OP1 alongside the f06 (displacements, eigenvectors, CBAR forces/stresses; later SOL 144 box pressures/forces). Unlocks pyNastranGUI as an external post-processor. pyNastran (BSD-3) optional dependency; prototype from its test suite first. Acceptance: pyNastran round-trips the OP1; pyNastranGUI renders SOL 101/103 results. | SOL 101/103 complete |
| Parametric sweep | Vary a geometry/material parameter and plot the response curve. | SOL 103 complete |
| NASTRAN f06 import | Read an existing NASTRAN f06 into the viewer for display and comparison. | Results parser |
| f06 results comparison | Two f06 files side-by-side; difference tables and overlaid deformed shapes. | NASTRAN f06 import |
| Model pre-solve validator | Pre-run checks: zero-length elements, missing SPC, unsupported cards, inconsistent units, unreferenced SIDs — viewer warning panel. | Viewer complete |
| Sample model library | Curated BDF examples (cantilever, portal frame, truss, airplane stick, …) for tutorials and regression. | Verification suite |
| Deploy to Streamlit Community Cloud | Live demo URL for the README (nice-to-have). | Viewer complete |

---

## Sample-deck consolidation (opportunistic NITs, 2026-07-31 sample review remainder)

- `val_vlm_anhedral.bdf` is a 2-coordinate sign flip of `_dihedral` that 2 test files
  could mirror in memory — consolidate or keep.
- `ha144a_fullspan` ×3 INCLUDE consolidation (superset bulk + 3 drivers, ~280 duplicated
  lines each, already drifting). The last technical objection is gone — Step 65 proved the
  whole-bulk-INCLUDE driver pattern and Step 66 added multi-INCLUDE support — but the
  ripple is still ~24 test files + 6 docs.
- **Constrained-grid-mass CI deck.** The Step 68 reaction recovery uses the full applied
  load, which only differs from `net_loads` when a constrained grid carries mass; no sample
  deck has that. A deck that does would be cheap CI insurance.
