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

**Execution order** (rationale: AE8b first — the long pole, may need reference-hunting time;
AE8a and the warnings can run in parallel or after; GUI last since it partly displays AE8b
output):

| Step | Item | Kind | Priority | Notes |
|-----:|------|------|----------|-------|
| AC2 | [Unrestrained (mean-axis) derivative formulation (known-wrong)](#step-ac2-major-ae8b--unrestrained-mean-axis-derivative-formulation-known-wrong) | Code | MAJOR | Gated on sourcing the NASTRAN/ZAERO algorithm |
| AC3 | [AE8a — q-invariant common-mode trim offset](#step-ac3-minor-ae8a--q-invariant-common-mode-trim-offset) | Code | MINOR | Root-cause or document; either closes it |
| AC4 | [Minor solver warnings — AE12, A7, A8](#step-ac4--minor-solver-warnings--ae12-a7-a8) | Code | MINOR | Small, batchable |
| AC5 | [GUI — close the small viewer gaps](#step-ac5--gui--close-the-small-viewer-gaps) | Code | Medium | Exports, totals, body-panel display, doc reconcile |
| AC6 | [Step 54 — CFD/WT steady-pressure injection (CHORDCP)](#step-ac6--step-54--cfd--wind-tunnel-steady-pressure-injection-mean-flow-trim) | Code | Optional | Steady-complete can be declared without it |

**Fallback:** AC2 (AE8b) is the only item with external risk — it is gated on obtaining
the MSC/NASTRAN unrestrained-derivative formulation. If the reference cannot be sourced,
document the column as unavailable and keep AE8b open; AC3–AC5 still complete
everything else.

---

### Step AC2 [MAJOR] AE8b — Unrestrained (mean-axis) derivative formulation (known-wrong)

**Files:** `sbeam/solver/sol144.py` (`_compute_rigid_derivs`, `_compute_restrained_derivs` —
add the unrestrained path here).

**MAJOR but NOT on the trim critical path.** Derivatives are an OUTPUT, not the trim driver
(closing Step G did not move SC2), so AE8b does not block Phase C trim or monitor loads.
It is the missing unrestrained derivative *column* — a Phase C derivative deliverable in its
own right. Tracked separately from AE8a (the SC2 trim residual) since 2026-06-13.

```
[MAJOR] The stability-derivative chain has consistent RIGID and RESTRAINED columns but no
        UNRESTRAINED (mean-axis / inertial-relief) set. NASTRAN HA144A Table 7-1 prints both
        restrained and unrestrained columns; sbeam reproduces only the restrained half.
RESOLVED HALVES (do NOT re-open):
  * Sign — AE1 Step E (2026-06-12): nose-up-positive −ΣFz·(x−xref) single-sourced in
    sol144._pitch_moment; CMα = −2.871 matches NASTRAN.
  * Parity precondition — AE1 Step D (2026-06-12): half-span removed, so the old sym=2
    contamination of C_ax_l is gone.
  * Restrained half — AE1 Step G (2026-06-12): _compute_restrained_derivs replaced with the
    exact analytic Schur derivative (∂u_l/∂δ = K_ll⁻¹·C_ax_l → linear normalwash/force chain);
    FD machinery deleted; V-AE1e confirms restrained CZα = 5.112 vs Table 7-1 5.103 (q=40)
    within 1%.

KNOWN-WRONG FIRST ATTEMPT (2026-06-13) — discard, do NOT iterate: a mean-axis inertia-relief
        derivative (P_l = I − MΦ m_r⁻¹ Φᵀ, mean-axis gauge) yields q=1200 CZα 11.67 vs
        ADA370433 7.772 (~1.5× HIGH — overshooting in the OPPOSITE direction from AE8a's
        coupling deficit, so it is a genuine FORMULATION error, not inherited coupling error).
        The analytic==FD self-consistency check is VACUOUS on a linear system — it cannot
        catch this.

SECOND ATTEMPT (2026-06-14) — first-principles free-free mean-axis; REVERTED, not committed.
        Derived the rigorous free-free inertia-relief column from scratch (NOT a patch of the
        first attempt): structural-K rigid-body modes D = [[−K_ll⁻¹K_lr],[I]] from the SUPORT
        partition (verified ‖K_aa·D‖/‖K‖ = 1.3e-16); rigid mass m_r = DᵀM_aaD (SPD); the
        basis-invariant M-orthogonal inertia-relief projector P = I − M_aaD·m_r⁻¹·Dᵀ; and the
        coupled free-free aeroelastic solve (K_aa − P·qQ_aa)u = P·(qQ_ax)δ with the Step-G force
        chain.  RESULT: EXACT at q=40 — all six {CZα CMα CZq CMq CZδe CMδe} within 1% — but at
        q=1200 the rigorously-coupled column overshoots to CZα 11.67–12.44 vs target 7.772
        (~+50%).  The operator reduces correctly to the restrained column as mass→∞, so the
        derivation is internally sound.
        KEY DIAGNOSTIC (q=1200, CZα; target 7.772): restrained-only 6.819 (−12%, too stiff);
        rigorous free-free coupled 11.67–12.44 (+50–60%, too soft); a structural-K single-aero-pass
        variant 7.87 (+1.2% on CZα but −4.7% on CMα).  The target sits BETWEEN restrained and
        free-free, so NASTRAN's "unrestrained" value is NOT the literal converged free-free
        aeroelastic-feedback derivative.  q_div(restrained) = 4034 (q=1200 is 30% of divergence —
        the overshoot is formulation, not a near-singular q).  Note the SUPORT r-row reaction form
        is unavailable here: (M_aa·D)[r,:] is singular (GRID 90 carries ~no direct mass).
CONCLUSION / NEXT: closing this needs the ACTUAL NASTRAN/ZAERO unrestrained-derivative algorithm
        (MSC Aeroelastic Analysis User's Guide §2 mean-axis/inertia-relief DMAP, or the explicit
        ADA370433 Table 3.1.1 derivation) — it cannot be reverse-engineered from the six target
        values without curve-fitting, which is exactly the first-attempt trap.  Building blocks
        (M_aa reduction, rigid modes, m_r, projector, force chain) are all verified and ready to
        reuse once the correct operator is sourced.

FIX:    Re-derive the unrestrained mean-axis set from the ASTROS/ZAERO theory behind ADA370433
        Table 3.1.1 (inertial relief transforming to the free-flight mean axis) from first
        principles — not by patching the discarded attempt. Gate on the SOURCED independent
        values, never on FD self-consistency.
ACCEPTANCE (to CLOSE): HA144A UNRESTRAINED columns within 1% of NASTRAN_UNRESTRAINED
        (tests/aero/test_ae1_restrained_derivs.py): q=40 {CZα 5.127, CMα −2.907, CZq 12.158,
        CMq −10.007, CZδe 0.2520, CMδe 0.5678}; q=1200 {CZα 7.772, CMα −4.557, CZq 16.100,
        CMq −12.499, CZδe 0.5219, CMδe 0.3956}. (UNRESTRAINED — distinct from the MSC Table 7-1
        RESTRAINED column gated by V-AE1e; do not conflate.)
RIDES HERE: completing V-AE1e's remaining RESTRAINED columns (Cmα, Cmq, CZδe, Cmδe) needs the
        MSC Table 7-1 values (not ADA370433) and rides with AE8b.
GUI RIDER: once computed, add the unrestrained column to the stability-derivative table in
        viewer/results_view.py::_render_sol144_trim (alongside rigid + restrained).
```

---

### Step AC3 [MINOR] AE8a — q-invariant common-mode trim offset

**Files:** `sbeam/aero/coupling.py` (`build_fg` baseline aero load), `sbeam/aero/integration.py`
(`build_wg` rigid normalwash / incidence), `sbeam/solver/sol144.py` (`run_sol144_trim`),
`sample/ha144a_fullspan_sbeam.bdf` (canard / baseline-incidence setting).

**Reframed and DOWNGRADED 2026-06-13 (was "MAJOR flexible-coupling fidelity gap, ~1.4×").** New
metrology evidence shows the SC2 residual is a small, q-INDEPENDENT rigid common-mode trim offset
(~0.1°, ≤0.4% FS) — the same offset already accepted at SC1, within fitness tolerance. It is NOT a
flexible-coupling defect and NOT a blocker on Phase C. The spline-kernel /
"obtain the NASTRAN flexible displacement field first" framing is superseded.

```
EVIDENCE — three independent metrology lenses, same conclusion:
  (1) ABSOLUTE: the SC2 trim error is ~0.1° per DOF (ANGLEA +0.107°, ELEV −0.092°), not the
      "+136%" the relative-to-near-zero metric reports.
  (2) q-INVARIANT: the absolute error barely moves from q=40 to q=1200 —
        ANGLEA  q=40 +0.1066°   q=1200 +0.1071°   (identical to 4 sig figs)
        ELEV    q=40 −0.0964°   q=1200 −0.0916°
      A flexible (q·Q_aa) defect would scale ~30× with q; this does not scale at all.
  (3) FULL-SCALE: ~0.36% of the 30° (neg→pos stall) AoA range, flat across a 30:1 q sweep.

WHY RIGID, NOT FLEXIBLE: q=40 is independently a ~pure-rigid trim (flex effect 0.6%: restrained
      CZα 5.103 vs rigid 5.071), so its +0.107° error IS the rigid baseline offset. The SAME
      error at q=1200 ⇒ flexible_error(1200) ≈ 0.107° − 0.107° ≈ 0 — the high-q flexible coupling
      is essentially CORRECT. The earlier "Q_aa×1.41 reproduces both SC2 targets" fit is read as
      NON-UNIQUE, not causal: at high q the flexible term is the dominant lever on the response
      and can absorb a small residual of any origin, but it is INERT at q=40 where the identical
      error appears. "No structural parameter fixes it" is consistent with a rigid AERO-baseline
      source (incidence/camber w_g, canard setting, chordwise box bias) — which the
      structural-parameter sweep never touched.

DECISIVE TEST (cheap, no NASTRAN flex data needed): diagnose the +0.107° offset at SC1 — a
      pure-rigid trim there — in the rigid baseline (build_fg / build_wg incidence, canard
      setting, chordwise discretization). Correct it and re-run SC2: if SC2 collapses too, it is
      a single q-independent common-mode and the flexible/spline hypothesis is closed for good.

NOT A BLOCKER: under the corrected %-full-scale acceptance gate (AE1 Step F) both subcases
      already pass at ≤0.4% FS, so Phase C and monitor loads are not gated on this.

ACCEPTANCE (to CLOSE): trim error ≤1% of full-scale range at every TRIM subcase (already met:
      SC1 and SC2 both ≤0.4% FS) AND the q=40 common-mode either root-caused (trim error ≲0.1% FS)
      or DOCUMENTED as a known ≤0.4% FS trim bias in docs/10_standard/05_aeroelastics.md.
```

Standing cautions (from the closed AE1 baseline — full table in `docs/40_history`): do not
chase the `q·Q_aa` flexible increment for SC1 (a 0.6% effect at q=40), and do not re-tune
HA144A bulk parameters (NSPAN/NCHORD, spline DTOR, RCSID) to fit the gate — rigid CLα already
matches NASTRAN to 4 sig fig at the same mesh.

---

### Step AC4 — Minor solver warnings — AE12, A7, A8

Small, batchable pre-solve/handler warnings. Each closure follows the three-part
step-completion rule individually.

#### [MINOR] AE12 — SPLINE2 DTOR/DTHZ silently ignored (PG-normal half MISIDENTIFIED)

**Files:** `sbeam/aero/spline.py`, `sbeam/parser/bdf_reader.py:576,583`, `sbeam/aero/vlm.py:144–156`

```
[MINOR — REAL] Spline2.dtor (default 1.0) and dthz (default 0.0) are parsed
        (bdf_reader.py:576,583) and stored on Spline2 (model/aero.py:79,82) but NEVER
        referenced in spline.py — silently accepted and ignored, the same failure class as
        the AE4(c) DTHX misinterpretation. No warning fires when DTOR≠1.0 or DTHZ≠0.0.
        (The existing V-AE2 fixture test_spline.py:673 already sets dthz=−1.0, so a warning
        gate there would currently be silent — good evidence the omission is real.)
FIX:    Warn when DTOR/DTHZ carry non-default values that will be ignored. Add a
        parser/handler test asserting a UserWarning fires for DTOR≠1.0 and DTHZ≠0.0.

[NOT A BUG — PG normals, re-diagnosed 2026-06-12] The original claim "prandtl_glauert_boxes
        copies the un-recomputed normal — wrong for dihedral/out-of-plane panels" is WRONG.
        Under S=diag(1,β,β) the normal DIRECTION changes only if n_x≠0; it is INVARIANT for
        any n_x=0 panel, dihedral included. mesh_caero1 advances every box chord purely
        along x̂=(1,0,0) (panel.py:78,90), forcing n_x=0 for ANY swept/tapered/dihedral
        CAERO1 — so the normal-copy is EXACT over the entire current box space. Latent (no
        current geometry triggers it). If hardened at all: `assert n_x≈0` (or recompute only
        the n_x-bearing case), NOT "recompute for dihedral". Test should pair an n_x≠0 panel
        (copied vs recomputed differ) with a dihedral panel (agree to machine precision) to
        guard against a needless future "fix".
```

#### [MINOR] A7 — Cosine chordwise spacing + low-NCHORD warning (code half)

**Files:** `sbeam/aero/panel.py` (samples already RESOLVED 2026-06-12: both BDFs at NCHORD=8)

```
GUIDANCE: Steady VLM minimum NCHORD = 4; recommended 8 for converged moment/loading
        (NASA SP-405 / DeJarnette NASA NTRS — cosine LE-concentrated chordwise spacing
        reaches the same accuracy with fewer boxes). Lift converges at NCHORD=1 (each box
        load already acts at its own ¼-chord, so chordwise CoP is 2D-correct); chordwise
        loading/pressure are what need refinement. Phase D (DLM) is frequency-driven:
        ~50 boxes per aerodynamic wavelength (Rodden/MSC), roughly 16·k_max boxes/chord —
        though typically done with normal convergence at ~4 boxes per wavelength (Sean).
OPEN (code): mesh_caero1 supports only uniform chordwise spacing via NCHORD (cosine
        requires hand-built LCHORD/AEFACT). Add a cosine-spacing helper / default, and
        a pre-solve warning when NCHORD < 4 on any CAERO1.
```

#### [MINOR] A8 — Box aspect-ratio pre-solve warning (code half, companion to A7)

**Files:** `sbeam/aero/panel.py` (samples already RESOLVED 2026-06-12: airplane_aero.bdf
NSPAN 38/31/16, all 1232 boxes AR 0.64–1.63; HA144A left faithful to the MSC deck — do not retune)

```
GUIDANCE: Size NSPAN so each box AR (spanwise edge / streamwise edge) is near 1.0;
        acceptable band 0.5–2.0 (standard VLM/DLM practice, NASA SP-405; Rodden/MSC).
        High-AR boxes degrade the VLM induced-downwash kernel and bias the loading.
        NOTE the coupling with A7: raising NCHORD shortens the chordwise box length,
        which forces NSPAN UP to keep AR ≈ 1 — size the two together, not independently.
OPEN (code): add a pre-solve warning when any box AR is outside [0.5, 2.0].
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
