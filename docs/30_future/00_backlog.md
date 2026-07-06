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
transient follow-ons and the DLM/flutter work are out of scope and listed under "Future
development" at the bottom of this file. **Update 2026-07-05:** the Phase G0 follow-ons now
carry a detailed development plan (Steps 59–63 + G0-d/G0-e, see the Phase G0 section below)
and are the next major development. GUI work closes the small display
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
moment/ELEV residual was re-scoped as Step AC8 (closed below). See `docs/40_history` and CHANGELOG.

**Step AC8 (AE15 wing-root interference residual) CLOSED 2026-07-05** — investigated and
ACCEPTED as a documented residual (Study A2,
`docs/20_theory/studies/a2_wing_root_interference.md`). sbeam's VLM implementation
exonerated by an independent cross-check (DLR PanelAero agrees to 1.6e-8 at operator level
and to 4+ decimals through the full flexible chain); the q=1200 moment/ELEV residual
(2.9–5.3%) is a canard-wake/wing-root interference discretization difference — MSC's
steady AIC is near-mesh-converged on the coarse 8×4 mesh where a horseshoe VLM is not.
The six q=1200 gates stay `xfail` citing the study. See `docs/40_history` and CHANGELOG.

**Step AC4 (AE12/A7/A8 minor solver warnings) CLOSED 2026-07-05** — SPLINE2 DTOR/DTHZ
now warn when carrying values sbeam ignores; `build_aero_model` warns pre-solve on < 4
chordwise boxes and box AR outside [0.5, 2.0] (VLM panels only; PSTRIP strips exempt);
`panel.cosine_chord_fractions` added for LE-concentrated LCHORD/AEFACT spacing. The
close-out **exonerated AE12 as AC7's prime suspect** (HA144A cards carry only the benign
detached DTHZ=−1.0/default DTOR=1.0 — NASTRAN does no Rz coupling there either).

**Step AC5 (GUI — close the small viewer gaps) CLOSED 2026-07-05** — viewer brought to
parity with the SOL 144 output surface: maneuver MLDPRNT/critical-load download buttons,
a new f06 transient-maneuver block (`build_f06_sol144_maneuver_text`, viewer + CLI), all
six aerodynamic trim totals (CY/CMx/CMz were newly computed in `sol144.py` — the backlog's
"already computed" claim was wrong), body panels colour/legend-distinguished in the 3D
mesh (`is_strip` flag + `body_eids` for cruciform), a bulk-aware run-summary string, the
`sample/ha144a_fullspan_mloads.bdf` MLOADS sample deck, and the viewer-doc reconcile.
See `docs/40_history` and CHANGELOG.

**Step AC6 (Step 54 — CHORDCP steady-pressure injection) CLOSED 2026-07-05** — the trim
mean flow can now be supplied directly from CFD/wind-tunnel steady pressures: a new
`CHORDCP` card (per-box physical Cp + required reference AOA in degrees) is converted at
assembly into an equivalent baseline normalwash over the VLM sub-block
(`corrections.apply_chordcp`, min-norm solve + dead-row reproducibility check), so
`sol144.py` needed no load-path change and the trim perturbs about the injected operating
point with an ABSOLUTE solved ANGLEA. All three acceptance gates pass (identity to 1e-9
incl. WT2-active; exact scaled-wash algebra; integral match), KC7 warnings implemented
(Mach mismatch, >2° trim distance, W2GJ discard), f06 gains an INJECTED OPERATING POINT
echo, `mirror_halfspan` rejects the card. v1 requires full VLM-surface coverage; partial
coverage + viewer authoring are Future-development notes below. See `docs/40_history` and
CHANGELOG.

**All aeroelastic close-out steps (AC1–AC8) are now closed — no open items remain in the
steady close-out plan.**

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

### CHORDCP (Step 54) — follow-ons (open, low priority; deferred 2026-07-05)

- **S54-a — partial per-surface coverage.** v1 requires every VLM CAERO1 to carry a CHORDCP
  card (one shared ALPHREF). Allowing e.g. CFD-wing-only injection with the tail on its W2GJ
  baseline mixes two operating points — the covered surfaces' α_ref re-referencing is exact
  only surface-locally, and the interference bookkeeping between the injected and VLM halves
  needs a documented approximation + warning before it can ship.
- **S54-b — viewer CHORDCP authoring.** `aero_correction_view.py` already ingests CFD/test
  tables to synthesise W2GJ+WT2 cards; a parallel path from a per-box Cp table (CSV) to
  CHORDCP cards + corrected-BDF export would complete the GUI workflow. Includes the
  deferred injected-vs-computed mean-flow overlay in the Aero tab (recorded at AC5).

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

### Phase G0 — transient maneuver loads (DLM-free): follow-on increments — DETAILED PLAN (2026-07-05)

**Increment 1 is CLOSED (2026-06-13)** — Level-1 quasi-steady (`Ω×r`), open-loop, restrained l-set
Newmark-β integration of the ZAERO `MLOADS` card set (`MLOADS`/`MLDTRIM`/`MLDCOMD`/`MLDTIME`/
`MLDPRNT` + `TABLED1`). See `docs/40_history/00_completed_development.md` (Phase G0 increment 1) and
`solver/maneuver_qs.py`. The increments below build on it; all are **DLM-free** and gated only on
Phase C. Full unsteady MLOADS (state-space / RFA / control law) remains Phase G (gated on the DLM).

**Plan of 2026-07-05 (this section):** the next major development. Steps 59–63 supersede the old
G0-b/G0-c one-liners with a ZAERO-MLOADS-style **free-free modal-basis architecture** plus a new
**multi-mass-case (MASSSET) capability**; G0-d/G0-e remain named follow-ons. Sequencing:
**59 (refactor) → 60 (basis + GAFs) → 61 (modal solver, prescribed rigid) → 62 (free-flight) →
63 (MASSSET)**, then G0-d/G0-e.

#### Architecture decisions (confirmed 2026-07-05)

1. **Free-free ZAERO-style basis** `Φ = [Φ_r | Φ_e]` (n_a × n_h) built once from the **baseline**
   mass case:
   - **Φ_r — geometric rigid-body vectors about the SUPORT point** (one column per SUPORT DOF),
     NOT eigensolver zero-modes: free-free `eigh` returns the zero-frequency subspace in arbitrary
     linear combinations, whereas geometric vectors are deterministic, give an **exact algebraic
     map between rigid modal coordinates and the URDD/ANGLEA/PITCH trim labels** (unit-plunge ⇒
     `ξ̈ = URDD3`; unit-pitch ⇒ `ξ̈ = URDD5`, `ξ̇·c_ref/2V = PITCH`), and make
     `M_rr = Φ_rᵀ M_aa Φ_r` exactly the GPWG rigid mass about the SUPORT point. Same reference
     point as `_build_inertial_cols` (`suport_pos`), so `M_ax ≡ −M_aa Φ_r` column-for-column —
     a tested identity.
   - **Φ_e — free-free elastic modes** from `solve_modes(K_aa, M_aa, force_dense=True)`
     (unconstrained a-set), zero modes dropped, then **explicitly mass-orthogonalized against Φ_r**
     (`φ_e ← φ_e − Φ_r M_rr⁻¹ Φ_rᵀ M_aa φ_e`, re-M-orthonormalized). `Φ_eᵀ M_aa Φ_r = 0` holds by
     construction — this **is** the mean-axis condition (ZAERO Ch. 12 Eqs 12.9–12.16; same physics
     as `_compute_unrestrained_derivs`). `M_hh` is block-diagonal `[M_rr, 0; 0, I]` at baseline.
   - SUPORT's role changes: it supplies the rigid-mode reference point / DOF selection, the l-set
     constraint for mode-acceleration recovery, and the trim-label map — it no longer constrains
     the dynamics (`u_r = 0` dropped in the modal solver). SUPORT remains required.
2. **Modal EOM (Level-1 quasi-steady, perturbation about the Step 53 trim IC):**
   `M_hh Δξ̈ + [C_hh − q·B_hh] Δξ̇ + [K_hh − q·Q_hh] Δξ = q·Q_hc·Δδ_c(t)` where
   `K_hh = Φᵀ K_aa Φ`, `Q_hh = build_gaf(Q_aa, Φ)` (reused verbatim), `B_hh` = quasi-steady
   rate-damping GAF (plunge-rate column `−1/V` + the existing `Ω×r` PITCH/ROLL/YAW machinery from
   `build_djx`, rescaled from nondimensional rate; elastic-rate columns zero at Level 1 = the
   G0-d hook), `Q_hc` = control-surface columns of the existing `Q_ax` projected once, and
   `C_hh = diag(2ζωᵢ)` on the elastic partition. Rigid-state trim labels (ANGLEA/PITCH/URDD*)
   become **outputs** recovered from `ξ_r` — not inputs. Newmark-β (¼, ½) on the dense n_h system:
   `K̂` is nonsingular (M_rr ≻ 0) — **free flight = don't constrain the rigid partition; no Schur,
   no per-step re-trim**. Perturbation form keeps gravity implicit and guarantees an exact
   equilibrium start.
3. **Multi-mass-case: fixed Φ, swap M only (ZAERO-style).** Per MASSSET case *i* recompute only
   `M_aa,i` → `M_hh,i = Φᵀ M_aa,i Φ` (full, coupled off-baseline), `M_ax,i`, GPWG/trim mass
   properties, and the Step 53 IC trim. `Φ`, AIC (`ajj/ajj_inv_corr` — geometry+Mach only),
   `skj/djk/wg`, splines, `Q_hh/Q_hc/B_hh`, `K_hh`, `AeroCache` all reused untouched — explicitly
   **no aero-cache invalidation**. Exactness property used in the gates: with all n_a modes
   retained, Φ spans the a-set, so fixed-Φ off-baseline solutions are exact — truncation is the
   only approximation.
4. **Mode-acceleration recovery with inertia relief** (theory Eq. 23, required for load quality),
   per output step: `u_md = Φξ`; residual `r_a = f_ext(t) − M_aa Φξ̈ − C_a Φξ̇ − (K_aa − q·Q_aa)Φξ`;
   `Δu_l = K_eff_ll⁻¹ r_l` (SUPORT r-set held, reusing the increment-1 `K_eff_ll` LU); downstream
   recovery via the existing `_recover_step` with URDD entries of `δ_basic` filled from `ξ̈_r`.

#### Step 59 — Prerequisite refactor: shared a-set reduction + SOL 103 retention (behavior-identical)

**Objective:** Eliminate the 4×-duplicated RBE3+SPC a-set reduction and retain a-set eigendata so
every later step composes one code path. This is the `reduce_to_aset` refactor already specified in
`designs/matrix_gaf_export.md` §6.1 — landing it here serves both features.

**Deliverables:**
- `sbeam/assembly/reduction.py` (new): `reduce_to_aset(bulk, grid_index, spc_sid) → AsetReduction`
  dataclass `{T, dep_dofs, red_dofs, free_local, free_dofs}` + `reduce_matrix` / `reduce_vector` /
  `expand_to_g` (absorbing `sol144._expand_to_g`). Extracted from `sol144._compute_aset_data` /
  `_build_qaa_aset`; `sol103.run_sol103`, `sol144`, and `maneuver_qs._assemble_operators` re-pointed
  (`_compute_aset_data` kept as a thin wrapper — `maneuver_qs` imports it by name).
- `Sol103Result` gains optional `phi_free` (a-set), `free_dofs`, `K_free`, `M_free` (default None).

**Test/Acceptance:** full existing suite passes unchanged; SOL 103/144 f06 and
`sample/ha144a_fullspan_mloads.bdf` maneuver output bit-identical pre/post; unit test that
`reduce_to_aset` products equal the old `_compute_aset_data` outputs on an RBE3+SPC model.

#### Step 60 — Free-free maneuver modal basis + one-time h-set operator set

**Objective:** Build the ZAERO-style basis and precompute every geometry/Mach-only h-set operator
exactly once, validated standalone before any time integration touches it.

**Deliverables:**
- `sbeam/solver/modal_basis.py` (new): `build_rigid_modes(...) → Φ_r`;
  `build_maneuver_basis(...) → ManeuverBasis` dataclass `{phi, n_r, n_e, elastic_freqs_hz, M_hh,
  K_hh, rigid_label_map, suport_pos, orthogonality_residual}` — calls `solve_modes` **once**
  (basis-consistency rule, `matrix_gaf_export.md` §4.3), drops zero modes, mass-orthogonalizes;
  `build_hset_gafs(...) → {Q_hh, Q_hc, B_hh, f_h0}` composing `coupling.build_gaf` + new rigid-rate
  columns (`build_dj_rigidrate` added to `aero/integration.py`, reusing the `Ω×r` code in
  `build_djx`).
- MLOADS card extension (8-field, appended): `MLOADS SID MLDTRIM MLDTIME MLDCOMD MLDPRNT NMODES
  METHOD ZETA` — `METHOD` = EIGRL sid for the basis solve (0 ⇒ internal all-modes default);
  `ZETA` = uniform elastic modal damping ratio (default 0). **NMODES semantics fixed: count of
  retained ELASTIC modes; rigid modes always all included** (0 ⇒ all elastic).

**Test/Acceptance:** `Φᵀ M_aa Φ` block-diagonal ≤1e−10 relative, elastic block = I; `M_rr` = GPWG
rigid mass about `suport_pos` to machine precision; **`M_ax` identity** (a-set-reduced
`_build_inertial_cols` columns = `−M_aa Φ_r` per the rigid map) to machine precision; `Q_hh`
cross-check vs `Sol144Result.q_hh` from the existing static ROM with the same modes; `K_hh` rigid
rows/cols ≤1e−8·‖K_hh‖.

**Key decisions:** geometric rigid vectors over eigensolver zero-modes (rejected alternative
recorded in the theory doc); basis always from the baseline mass configuration.

#### Step 61 — Modal transient solver, prescribed rigid states (increment 1 re-expressed on the basis)

**Objective:** De-risk basis + integration + mode-acceleration recovery with the rigid partition
still *prescribed* (open-loop, exactly increment-1 physics) before freeing it in Step 62 —
isolates truncation behavior from free-flight dynamics.

**Deliverables:**
- `sbeam/solver/maneuver_modal.py` (new): `run_maneuver_modal(bulk, subcase, aero, aero_cache=None)
  → ManeuverResult`, selected in `main.py` when the MLOADS card has METHOD/NMODES set; otherwise
  the legacy `run_maneuver_qs` runs unchanged (kept permanently as the regression anchor; the
  increment-1 NMODES ignored-warning retired). Trim IC via `run_sol144_trim` (unchanged pattern);
  IC projection `ξ_e0 = Φ_eᵀ M_aa u_a,trim`; prescribed ξ_r(t) from the δ(t) URDD/rate histories
  via the rigid map; elastic Newmark with `−M_er,i ξ̈_r` (zero at baseline) + `q·Q_ec·Δδ_c` RHS.
- Recovery per architecture decision 4 (`_recover_step` refactored into a shared helper);
  `ManeuverStep`/`ManeuverResult` gain optional `modal_coords`, `n_modes_used`.
- Docs: theory §7.x (free-free basis, mean-axis orthogonalization, mode-acceleration with inertia
  relief; records the reversal of the increment-1 restrained-basis decision), `05_aeroelastics.md`
  user section, `02_card_reference.md` MLOADS fields.

**Test/Acceptance:** **modal-convergence gate** — all elastic modes retained ⇒ CBAR forces, net
loads, closure, Fz/My histories match `run_maneuver_qs` ≤1e−6 relative (displacements compared
after rigid-projection removal: mean-axis vs `u_r = 0` rigid content differs); convergence table
NMODES ∈ {2, 4, 8, all} with monotone peak-bar-force error decay (documented); mode-acceleration
beats mode-displacement by ≥10× on truncated bar forces; hold-at-trim steady output = Step 53
loads; ζ>0 decays energy, ζ=0 reproduces the gate.

#### Step 62 — G0-b free-flight rigid-body coupling (free the rigid partition)

**Objective:** The self-balancing maneuver: integrate `ξ_r` as states of the coupled h-set Newmark
system so closure ≈ 0 for an arbitrary commanded *control* history — no per-step trim solve.

**Deliverables:**
- Full coupled system (architecture decision 2): rigid rows active, `B_hh` rate damping engaged,
  controls-only `Q_hc`; single `K̂ (n_h×n_h)` LU with `K̂_rr = a0·M_rr − q·(Q_rr + a1·B_rr)`.
- δ bookkeeping: commanded AESURF labels = inputs (MLDCOMD/`_delta_of_t` reused);
  ANGLEA/URDD/PITCH labels = **outputs** from `ξ_r, ξ̇_r, ξ̈_r`; a rigid-state label in MLDCOMD
  under the modal solver ⇒ hard `ValueError` naming the label (the legacy solver remains available
  for prescribed-rigid studies).
- Recovery: `δ_basic` URDD entries from `ξ̈_r` (`_urdd_rcsid_to_basic` reused); MLDPRNT gains
  rigid-state histories (α, pitch rate, Nz).

**Test/Acceptance:** **G0-b gate (unchanged intent):** ELEV ramp-and-hold on the HA144A deck ⇒
closure ≤ tol throughout with O(dt²) decay under dt-halving, and the settled steady state
reproduces the Step 53 trim with ELEV prescribed and ANGLEA/URDD free (trim vars + net loads
≤1e−6 relative, full basis); zero-command free response stays at equilibrium to round-off;
short-period eigenpair of the assembled system matches a rigid 2-DOF hand calculation from the
Step 53 derivatives to ~5%. Determined command sets only (over-determined transient allocation
deferred to G0-e).

**Key decisions:** perturbation-about-trim (gravity implicit, exact equilibrium start); linear
inertial-frame rigid coordinates at fixed V (steady pull-up reachable since `α = θ − ḣ/V`
settles; phugoid/speed DOF out of scope, documented).

#### Step 63 — MASSSET multi-mass-case capability (fixed Φ, swap M)

**Objective:** ZAERO-style mass sweeps: AIC/splines/GAFs/`K_hh`/Φ computed once; each mass case
re-projects only mass-derived quantities and re-runs the cheap n_h-sized trim IC + transient.

**Deliverables:**
- **New `MASSSET` card** (`model/mass.py` dataclass, `bulk.masssets`, `_handle_massset` +
  dispatch elif, validation-pass cross-refs):
  ```
  MASSSET  SID    LABEL    SCALE
  +        ADD     301     302    303
  +        REPLACE 21      22
  +        DELETE  45
  ```
  `LABEL` = case name for output headers; `SCALE` (default 1.0) multiplies the baseline mass
  before ops; continuation rows = op keyword + up to 7 CONM2 EIDs (`ADD` overlays new CONM2s,
  `REPLACE` supersedes a baseline EID, `DELETE` removes one). Overlay CONM2s are ordinary CONM2
  bulk cards; a post-parse pass marks ADD/REPLACE EIDs overlay-only so baseline assembly excludes
  them (ADD of an existing EID / dangling DELETE/REPLACE ⇒ `ValueError`).
- **Case-control `MASSSET = n`** per subcase (`SubcaseControl.massset_sid`) — MSC-style selection
  like SPC/METHOD; works for static SOL 144 too (needed for the IC trim). A mass sweep = one deck,
  N subcases sharing one `AeroCache` + one `ManeuverBasis`/GAF set.
- `model/mass_overlay.py` (new): `effective_conm2s(bulk, massset_sid)`;
  `assemble_global_mass(..., massset_sid=None)`, `_build_inertial_cols(..., massset_sid=None)`,
  GPWG, `run_sol144_trim` and both maneuver solvers threaded. Explicit invariant (code comment +
  doc): **no AeroCache invalidation — AIC is geometry/Mach-only.**
- Output: mass-case LABEL in f06 / `maneuver_output.py` headers and critical-step summaries.
- New sample deck `sample/ha144a_mloads_massset.bdf` (3-mass sweep).

**Test/Acceptance:** parser round-trip + all three ops + negative cases; equivalence gate (MASSSET
overlay ≡ hand-edited deck with the same final CONM2 set: identical `M_gg`, GPWG, Step 53 trim to
machine precision); **fixed-Φ exactness gate** (off-baseline case, all modes ⇒ matches
`run_maneuver_qs` on the equivalent deck ≤1e−6 — mass-case error is pure truncation);
**fixed-Φ approximation gate** (+10% fuel overlay, truncated basis: peak-CBAR-force error vs a
re-solved-modes reference reported, ≤~2% asserted for the sample, guidance recorded in
`05_aeroelastics.md` — "re-solve the basis when case frequencies shift >~5%"); sweep test
(3 subcases / 3 MASSSETs, one basis+GAF build asserted by call count, distinct ICs and peaks).

**Key decisions:** case-control selection (not an MLDTRIM field) so static and transient share the
mechanism; basis always baseline (no per-MASSSET METHOD — basis-drift risk); `SCALE` applies to
the whole baseline mass.

#### G0-d — Unsteady corrections (Levels 2–4) — follow-on (outline; hooks land in Steps 60–62)

**Objective:** Layer the analytic unsteady terms onto the steady VLM forcing as an ordered list of
optional `AeroIncrement` objects each contributing `(ΔM_hh, ΔB_hh, ΔK_hh)` and optional appended
states: (2) 2-D apparent (added) mass per strip (`πρb²` projected to `A_hh`, plus the elastic-rate
`B_hh` columns — the slot left in Step 60); (3) tail downwash-lag delay `τ = l_t/V` (`C_mα̇`; ring
buffer of delayed `D_jx`/`D_jξ̇` arguments); (4) strip Wagner/Theodorsen lift-deficiency (per-strip
2-state R.T. Jones approximation appended to the state vector). Selected by a new `MLDAERO` card
(designed at promotion). Each optional; extends validity beyond `k ≲ 0.05–0.1`. Acceptance sketch:
Level 2 reproduces 2-D `πρb²` exactly on a single strip; Level 4 reproduces Wagner indicial lift to
Jones-approximation accuracy.

#### G0-e — Closed-loop control layer (ASE bridge) — follow-on (outline)

**Objective:** Discrete control-law update `δ_c[n+1] = f(sensor(ξ, ξ̇, ξ̈))` inside the time loop;
actuator lag as a first-order appended state; sensors at grids via the existing spline/recovery
operators. Enables commanded-Nz and the over-determined transient control allocation (reusing the
`TRIMOBJ` null-space QP pattern). ZAERO-ASE-flavoured cards designed at promotion. Bridges to the
full Phase G ASE system. Acceptance sketch: proportional pitch-rate damper reduces short-period
overshoot vs open loop; zero-gain identity to Step 62.

#### Phase G0 plan — risks & open questions

1. **Singular/lumped `M_aa` in the free-free eigensolve** — CONM2-only decks leave massless
   rotational DOFs; the Tikhonov path in `solve_modes` handles the eigensolve, but massless-DOF
   artificial modes must be excluded from Φ_e (frequency-cutoff + generalized-mass sanity filter);
   the mean-axis projection uses the *unregularized* `M_aa`; mode-acceleration recovery is the
   safety net for anything filtered.
2. **Fixed-Φ mass-case error** — quantified by the Step 63 approximation gate; the exactness gate
   proves it is pure truncation. Residual risk: large CG shifts change the mean axis materially —
   warn when an overlay moves the CG by more than a documented fraction of c_ref.
3. **TABLED1 rate discontinuities** — clamped-linear command tables have slope jumps; with `B_hh`
   rate terms the forcing is discontinuous and can ring the highest retained mode. Document
   ramp-smoothing practice; optional cosine-smoothed table evaluation as a future add.
4. **Damping model** — uniform ζ only at Step 60; per-mode TABDMP1 and the `B_hh` asymmetry
   (K̂ unsymmetric — LU already handles it) noted; Rayleigh `damping_alpha` stays legacy-solver-only.
5. **Linear inertial-frame rigid kinematics** — short-period-scale maneuvers at fixed V; no
   phugoid/speed DOF, no large-attitude kinematics. Documented validity envelope alongside the
   existing `k ≲ 0.05–0.1` aero limit.
6. **Control-surface inertia / hinge moments absent** — commanded δ_c produces aero only; surface
   mass reaction / hinge DOFs out of scope (theory-doc note).
7. **SUPORT dependence stands** — the modal solver still requires SUPORT (reference point +
   recovery constraint + rigid DOF selection); a SUPORT-free variant (rigid modes about the GPWG
   CG) is a possible future relaxation, not planned.
8. **NMODES behavior change** — previously parsed-and-ignored with a warning; now activates the
   modal solver. Call out in CHANGELOG as a behavior change.
9. **Basis drift** — one `solve_modes` call per job, enforced structurally (the basis object is
   passed into the GAF/mass-case loops; nothing inside can reach the eigensolver).
10. **Open question:** should `Q_hc` accept AESTAT rigid-state labels a user commands open-loop
    (e.g. prescribed-α studies)? Current answer: hard error under the modal solver; the legacy
    solver covers prescribed-rigid studies. Revisit if a use case appears.

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
