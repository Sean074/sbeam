# sbeam — Development Plan, Bugs & To-Do

Authoritative backlog of open bugs, in-progress work, and planned development. Updated as
part of every session that completes a step — never deferred. Completed steps are recorded
in `docs/40_history/00_completed_development.md`. When an item is promoted to a formal
step, give it a step number continuing from Step 39 and apply the same step format
(Objective, Deliverables, Test/Acceptance).

---

## Phase C closure roadmap — to a fully functioning SOL 144 + interface

Phase C (SOL 144 static aeroelastic trim) is the active program phase. **Done already** (see
CHANGELOG `[Unreleased]` and `docs/40_history`): the determined-trim Schur solver, rigid +
restrained stability/control derivatives, single critical divergence `q_div`, SOL 144 CLI
dispatch, f06 output, and trimmed flight-load export (AE10 / Step 56); and the **AE1 acceptance
gate is CLOSED** — both HA144A subcases trim within the %-full-scale gate (2026-06-13), AE1
Steps A–G + the Step C null-space guard complete.

**What remains to a fully functioning SOL 144 with a usable interface, in dependency order:**

| # | Item | Kind | Status | Why here / what it unblocks |
|--:|------|------|--------|------------------------------|
| 1 | [Step 52 remainder — over-determined trim + ROLL/YAW rate columns](#step-52--sol-144-trim-solve--flexible-derivatives-sol144py) | Code | Open | Lateral / over-determined trim; `C_lp`, `C_nr`; precursor to roll/yaw maneuvers. (Dihedral effect `C_lβ` enters here.) |
| 2 | [Step 53 — balanced maneuver loads & inertia relief](#step-53--balanced-maneuver-loads--inertia-relief) | Code | Open | The load-generating capability; non-zero inertia column feeds monitor loads |
| 3 | [Monitor points MON1–MON4 / V-MON1](#monitor-points--section-loads--phase-1-static) | Code | Open | Structures-team loads handoff per trim case; needs trim (1–2), benefits from maneuver (3) |
| 4 | [AE8b — unrestrained (mean-axis) derivative column](#major-ae8b--unrestrained-mean-axis-derivative-formulation-known-wrong) | Code | Open (known-wrong first attempt) | Completes the derivative deliverable; off the trim critical path — can run in parallel |
| 5 | [Step 55 — DIVERG q-sweep + mode shape + V_div](#step-55--aeroelastic-divergence-diverg) | Code | Open (single `q_div` done) | `DIVERG`-card-driven sweep and the divergence eigenvector |
| 6 | [Step 54 — CFD / wind-tunnel mean-flow injection](#step-54--cfd--wind-tunnel-steady-pressure-injection-mean-flow-trim) | Code | Open | Optional mean-flow enhancement; lower priority |
| 7 | [Step 57 — Viewer: SOL 144 results (THE INTERFACE)](#step-57--viewer-sol-144-results) | Code | Open | **CLOSING ITEM** — surfaces trim, derivatives, `q_div`, deflected shape, box `cp`, monitor loads in the UI |

**Step 58 (dihedral / anhedral ±Γ correctness) is CLOSED (2026-06-14)** — the
VLM→spline→force→trim chain is now permanently gated out of the xy-plane by **V-C-DIH**
(`tests/aero/test_dihedral.py`) for Γ = +10° AND −10°: geometric box normal `(0, ∓sinΓ, cosΓ)`,
3-component force with side force `Fy`, rigid `CL ≈ CL_planar·cosΓ`, symmetric `Fy`/roll/yaw
cancellation, and a structured determined trim (`sample/val_dihedral_trim.bdf`) that closes the
inertia-relief balance out of plane. Key finding: the force/normal architecture was already
3-component and geometry-driven, so no production rewrite was needed — only the ±Γ decks, the gate,
and a reusable `aero_moment_resultant` helper. **Dihedral still rides the remaining steps:** the
lateral derivatives pick up the dihedral effect `C_lβ` once ROLL/YAW lands (Step 52); monitor
section loads must carry the now-validated `Fy`/`Fz` split (MON2/MON3); and the viewer must render
the canted deflected geometry and box `cp` (Step 57). The V-C-DIH gate is the permanent regression
guard against the `(0,0,1)`-normal / Fz-only-resultant blind spot.

**Non-blocking polish (close opportunistically, off the critical path):** AE8a (MINOR — optional
root-cause of the ~0.1° q-invariant common-mode trim offset, already ≤0.4% FS), AE12 (MINOR —
SPLINE2 DTOR/DTHZ ignored-warning), A7 (cosine chordwise helper + low-NCHORD warning), A8 (box-AR
pre-solve warning), R23 (NIT — stale doc signature). Phase 2 / Phase 3 / long-tail development is
out of Phase C scope (bottom of file).

**Closed in this branch (one line; full detail in CHANGELOG `[Unreleased]` + `docs/40_history`):**
AE2–AE7; AE9 (per-TRIM Mach AIC cache + supersonic guard); AE10 + Step 56 (SOL 144 CLI / f06 /
flight-load export); R16–R22; AE1 Steps A, B, C, D (half-span removed — full-span only), E, F, G;
V-AE1b/c/e/f/g and V-AE2/V-AE3 acceptance gates. The retracted "flexible `q·Q_aa`" SC1 re-diagnosis
is closed history and no longer load-bearing (the SC1 gap was the parity double-count, removed by
construction).

---

## AE1 — HA144A trim acceptance: CLOSED (reference baseline)

> **Status — CLOSED 2026-06-13.** Both HA144A subcases trim within the %-full-scale gate
> (`tests/aero/test_ae1_fullspan.py`). AE1 Steps A, B, D, E, F, G and the Step C null-space
> regression guard are done; the V-AE1b/c/d/e/f/g acceptance gates are green. Full detail lives in
> `docs/40_history` and CHANGELOG `[Unreleased]`. This block is retained only as the validated-trim
> **reference baseline** the open Phase C work (dihedral, maneuver, monitor) regresses against. The
> only open AE1-lineage items are **AE8b** (unrestrained derivative column, MAJOR) and **AE8a**
> (the ~0.1° q-invariant common-mode trim offset, MINOR) — in their own sections below.

**Validated trim (full-span deck, NASTRAN Listing 7-2 vs sbeam):**

| Quantity | NASTRAN | sbeam | Status |
|---|---:|---:|---|
| SC1 (q=40) ANGLEA     | +0.169191 rad | +0.171052 rad (+1.1%) | ✓ |
| SC1 (q=40) ELEV       | +0.492457 rad | +0.490775 rad (−0.3%) | ✓ |
| SC1 trim lift         | +16 000 lb    | +16 000 lb            | ✓ |
| SC2 (q=1200) ANGLEA   | +0.001373 rad | +0.003242 rad (0.36% FS) | ✓ ≤1% FS |
| SC2 (q=1200) ELEV     | +0.019325 rad | +0.017727 rad (0.23% FS) | ✓ ≤1% FS |
| Rigid CZα             | −5.071        | −5.071                | ✓ |
| Restrained CZα (q=40) | −5.103        | −5.112 (within 1%)    | ✓ V-AE1e |

The SC2 "+136%" relative figure was a near-zero-normalization artifact; the real SC2 error is the
same ~0.1° q-invariant common-mode offset already accepted at SC1 (≤0.4% FS, flat across a 30:1 q
sweep) — tracked, with the decisive root-cause test, on **AE8a**. Two standing cautions for the
open work: do not chase the `q·Q_aa` flexible increment for SC1 (a 0.6% effect at q=40), and do not
re-tune HA144A bulk parameters (NSPAN/NCHORD, spline DTOR, RCSID) to fit the gate — rigid CLα
already matches NASTRAN to 4 sig fig at the same mesh.

---

## Open findings — Aerodynamics (2026-06-11 review)

207 aero/integration tests passed at review time despite the HA144A trim being grossly
wrong (validation blind spot — see AE13). The VLM core is verified to 4 sig fig vs
NASTRAN rigid CLα; the defects below sit in the integration, spline, and trim layers.
AE1 is tracked above; AE2/AE3/AE4/AE5/AE6/AE7 are resolved (see CHANGELOG).

---

### [MINOR] AE8a — q-invariant common-mode trim offset

**Files:** `sbeam/aero/coupling.py` (`build_fg` baseline aero load), `sbeam/aero/integration.py`
(`build_wg` rigid normalwash / incidence), `sbeam/solver/sol144.py` (`run_sol144_trim`),
`sample/ha144a_fullspan_sbeam.bdf` (canard / baseline-incidence setting).

**Reframed and DOWNGRADED 2026-06-13 (was "MAJOR flexible-coupling fidelity gap, ~1.4×").** New
metrology evidence shows the SC2 residual is a small, q-INDEPENDENT rigid common-mode trim offset
(~0.1°, ≤0.4% FS) — the same offset already accepted at SC1, within fitness tolerance. It is NOT a
flexible-coupling defect and NOT a blocker on AE1 Step F or Phase C. The spline-kernel /
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

---

### [MAJOR] AE8b — Unrestrained (mean-axis) derivative formulation (known-wrong)

**Files:** `sbeam/solver/sol144.py` (`_compute_rigid_derivs`, `_compute_restrained_derivs` —
add the unrestrained path here).

**MAJOR but NOT on the Step F critical path.** Derivatives are an OUTPUT, not the trim driver
(closing Step G did not move SC2), so AE8b does not block AE1 Step F, Phase C, or monitor loads.
It is the missing unrestrained derivative *column* — a Phase C derivative deliverable in its own
right. Tracked separately from AE8a (the SC2 trim residual) since 2026-06-13.

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
```

---

### [MINOR] AE12 — SPLINE2 DTOR/DTHZ silently ignored (PG-normal half MISIDENTIFIED)

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
        CAERO1 — so the normal-copy is EXACT over the entire current box space. Verified
        numerically: a 30° dihedral panel → 0.0° normal change; a panel with geometric
        incidence (n_x≠0) → ~0.94° at M=0.6. The real condition is n_x≈0, NOT planarity.
        Latent (no current geometry triggers it). If hardened at all: `assert n_x≈0` (or
        recompute only the n_x-bearing case), NOT "recompute for dihedral". Test should
        pair an n_x≠0 panel (copied vs recomputed differ) with a dihedral panel (agree to
        machine precision) to guard against a needless future "fix".
```

---

### [MINOR] AE13 — Validation gap: no swept/coupled/benchmark gates (partially closed)

**Files:** `tests/aero/`, `tests/integration/`, `sample/ha144a_fullspan_sbeam.bdf`

```
[MINOR] 207 tests passed at review time with every defect above present. Every
        geometric validation case was unswept and uncoupled; the V-B1/V-B3 rigid-body
        gates never exercised a swept spline axis or fore/aft offset grids; no
        dimensional-consistency check tied the coupled force path back to the rigid
        solver.
FIX:    Three permanent gates planned; status today:
        (V-AE1)  HA144A acceptance test — SC1 and SC2 both CLOSED: the sym=2 aero/inertia
                 parity double-count was removed with half-span support, and SC1 ANGLEA/ELEV/lift
                 trim within tolerance on the full-span deck (V-AE1d/V-AE1f). SC2 value
                 tests are now live %-full-scale gates (AE1 Step F, 2026-06-13) — the superseded
                 relative `xfail` is gone. ⚠ the original "lift tests pass"
                 reassurance was non-discriminating (lift balanced for both the correct and
                 the halved trim) — exactly the blind spot AE13 is about; now superseded by
                 per-target SC1 relative + SC2 %-full-scale tolerances.
        (V-AE2)  Swept-spline rigid-body gate — IMPLEMENTED 2026-06-11 (3 tests in
                 TestSweptSplineRigidBody) and updated 2026-06-12 to use EA-only SET1
                 with DTHX=+1 alongside V-AE1b (`TestGlobalRigidBody`). Genuinely closed:
                 exercises a 60°-swept axis + full 6-mode lever-arm rotation.
        (V-AE3)  Unit-consistency gate — coupling-path (skj @ ajj_inv_corr) total force AND
                 moment equals the Kutta-Joukowski resultants from solve_rigid_cl on the same
                 model. CLOSED 2026-06-13 (tests/aero/test_vae3_cross_check.py): named to avoid
                 collision with the UNRELATED "V-AE3a" trim-lift gate in test_trim_urdd.py; built
                 as an INDEPENDENT path (solve_rigid_cl rebuilds its own AIC + K–J resultants),
                 NOT an extension of the Step E self-consistency class. Fz/My agree to machine
                 precision on HA144A and val_vlm_rect_ar8; the half-f_box parity proxy fails by
                 ~2×, so unlike test_phase_b.py::test_tz_sum_vs_cl_magnitude (min(err_full,
                 err_half)<0.02) it DOES catch the factor-of-2 parity bug.
        (V-AE1g) Rigid-derivative benchmark — CLOSED 2026-06-13 (test_ha144a_rigid_derivs.py):
                 the full rigid longitudinal column (CZα/CMα/CZq/CMq/CZδe/CMδe) gated within
                 0.5% of the independent ADA370433 Table 3.1.1 NASTRAN values — adds the
                 benchmark derivative coverage this item flagged as missing (rigid layer only;
                 the flexible derivative layer remains on AE8b; the coupling-path check on V-AE3).
```

---

## Open findings — Aerodynamics (2026-06-08 review, code-level)

### [MINOR] A5 — Aero model is reachable only from the viewer; aero cards inert under the solver

**Files:** `sbeam/aero/aero_model.py`, `sbeam/solver/`, `sbeam/main.py`

```
[MINOR] build_aero_model / solve_rigid_cl are called from viewer/app.py and (since AE10)
        from main.py under SOL 144. No solver or CLI path consumes the aero model under
        SOL 101/103 — expected, since those are non-aero solutions. (STALE: the old line
        "case_control.py rejects SOL 144" is no longer true — 144 is whitelisted at
        case_control.py:61; and AE10 has landed the main.py SOL 144 dispatch, so the
        end-to-end aero solve now runs from the CLI.) val_vlm_rect_ar8.bdf documents the
        SOL-101 workaround.
FIX:    Expected state for SOL 101/103 — keep the "expected-state" verdict. The end-to-end
        SOL 144 dispatch gap is CLOSED (AE10). The stale parse_case_control docstring
        ("not 101 or 103") was corrected when AE10 / Step 56 landed.
```

---

### [MINOR] A7 — Default chordwise box count too low; no cosine chordwise spacing

**Files:** `sample/airplane_aero.bdf`, `sample/val_vlm_rect_ar8.bdf`, `sbeam/aero/panel.py`

```
[MINOR] Sample models used NCHORD=2 (airplane) / NCHORD=1 (rect val). Lift converges at
        NCHORD=1 (1/4-3/4 rule is 2D-exact). Chordwise loading/pressure are under-resolved
        at low NCHORD and benefit from refinement.
        ⚠ NUMBERS RETRACTED (2026-06-12 review): the previously cited "CM shifts ~50%
        NCHORD 1→2, ~34% 2→4" does NOT reproduce. Re-running solve_rigid_cl at NCHORD=
        1,2,4,8,16 over 0/18/35° sweep gives ≤~1.9% CM shift 1→2 (worst case) — because each
        box load already acts at its own ¼-chord (vlm.py:283-284), so chordwise CoP is
        2D-correct at NCHORD=1 (val_vlm_rect_ar8.bdf:55 self-documents this). No checked-in
        chordwise study exists. The guidance below stands on standards, not on those numbers.
GUIDANCE: Steady VLM minimum NCHORD = 4; recommended 8 for converged moment/loading
        (NASA SP-405 / DeJarnette NASA NTRS — cosine LE-concentrated chordwise spacing
        reaches the same accuracy with fewer boxes). Phase D (DLM) is frequency-driven:
        ~50 boxes per aerodynamic wavelength (Rodden/MSC), roughly 16·k_max boxes/chord
        — though this is typically not done with normal convergence at ~4 boxes per
        wavelength (Sean).
RESOLVED (samples): both sample BDFs updated to NCHORD=8 with guidance comments; box
        counts now 192 (airplane) and 320 (rect val); verified parse/build, CL unchanged.
OPEN (code): mesh_caero1 supports only uniform chordwise spacing via NCHORD (cosine
        requires hand-built LCHORD/AEFACT). Add a cosine-spacing helper / default, and
        a pre-solve warning when NCHORD < 4 on any CAERO1.
```

---

### [MINOR] A8 — Spanwise box count: aspect ratio must be O(1) (companion to A7)

**Files:** `sample/airplane_aero.bdf`, `sbeam/aero/panel.py`

```
[MINOR] A7 fixes the chordwise count; the spanwise count (NSPAN) is the other half of
        box sizing. airplane_aero.bdf shipped with NSPAN=6/4/4, giving box aspect
        ratios (spanwise edge / streamwise edge) of 4–10 — boxes 4–10× longer spanwise
        than chordwise. High-AR boxes degrade the VLM induced-downwash kernel and bias
        the loading; they are also the prime suspect / stress case for the A1
        lift-slope bias.
GUIDANCE: Size NSPAN so each box AR is near 1.0; acceptable band 0.5–2.0 (standard
        VLM/DLM practice, NASA SP-405; Rodden/MSC). NOTE the coupling with A7: raising
        NCHORD shortens the chordwise box length, which forces NSPAN UP to keep AR ≈ 1.
        With NCHORD=8 and meaningful chords this drives NSPAN high (tens of
        boxes/edge), so box counts grow fast — size the two together, not independently.
RESOLVED (samples): airplane_aero.bdf NSPAN 6/4/4 → 38/31/16 (wing/HTP/VTP); all 1232
        boxes now AR 0.64–1.63 (mean 0.99); verified parse/build/solve (CL_α ~ 4.17/rad).
        AR computed by reusing mesh_caero1 corner geometry. val_vlm_rect_ar8.bdf
        already OK (AR ≈ 1 by construction). HA144A.bdf left faithful to the MSC deck
        (do not retune).
OPEN (code): add a pre-solve warning when any box AR is outside [0.5, 2.0].
```

---

## Open findings — Documentation & NITs

### [NIT] R23 — Stale `recover_bar_forces` signature in the static-analysis doc

`docs/10_standard/03_static_analysis.md:307` documents `recover_bar_forces(bulk, u) -> dict`,
but the code is the per-element 6-arg form `recover_bar_forces(cbar, grids, pbars, mat1s,
displacements, grid_index) -> BarForce` (sol101.py:91), called in a loop at sol101.py:290.
Fix: correct the documented signature. (Surfaced 2026-06-12 while verifying R18.)

*R16–R22 closed and removed 2026-06-12 (per CLAUDE.md backlog hygiene; detail in CHANGELOG /
`docs/40_history/00_completed_development.md`): R16 & R18 were valid doc gaps at filing,
fixed by the 2026-06-10 doc restructure; R17 & R19 were misidentified (already present —
`01_beam_model.md:761` lists GRAV/RBAR; `TestV19RbarLeverArm` + `v19_rbar_offset.bdf`
already exist); R21 (spc_sid guard) and R22 (public f06 text aliases) fixed in this session.*

---

## Open questions / risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |

---

## Phase A status

Steps 39–46 complete — see `docs/40_history/00_completed_development.md`. Open Phase A
work: **A7** (cosine chordwise spacing helper + low-NCHORD warning), **A8** (box
aspect-ratio pre-solve warning); and from the 2026-06-11 review: **AE12** (SPLINE2
DTOR/DTHZ ignored-warning — the PG-normals half is re-diagnosed NOT-A-BUG, see AE12).
**AE9** (per-TRIM Mach) is closed (2026-06-12 — Mach-keyed AIC cache, supersonic guard).

---

## Phase B status

Steps 45, 46, 47, 49 complete; Step 48 (SPLINE1) deferred. The SPLINE2 swept/offset
kinematics and force-transfer point defects flagged on 2026-06-11 (AE4, AE6) are
resolved; the AE1 Step B follow-up (multiplication-bending, corrected torsion, EA-only
SET1, RBAR-expanded recovery) is also resolved. The `TestGlobalRigidBody` (V-AE1b) gate
and the SET1 collinearity validator in `_build_spline2_block` are in place as
regressions.

---

### Step 48 — SPLINE1 surface spline (optional — deferrable)

**Objective:** Harder–Desmarais Infinite-Plate Spline for general 2-D grid scatter.

**Scope/Deliverables (deferred — Phase C does not require this):**
- `Spline1` dataclass stub already added in Step 45
- `_handle_spline1` raises `NotImplementedError("SPLINE1 not yet implemented; use SPLINE2")`
- Full IPS kernel `r²·ln r²` and `G_kg` rows: implement when a 2-D scatter case arises

**Test/Acceptance (when implemented):** Reproduces rigid-body and linear fields exactly;
matches a published IPS example (Harder & Desmarais 1972).

---

## Phase C — SOL 144 Static Aeroelastics (remaining: Step 52 rem., 53–55, 57)

Phase C wires Phases A + B into the structural stiffness to solve the flexible static
aeroelastic problem: trim (determined and over-determined), flexible stability/control
derivatives, optional CFD/WT mean-flow injection, and divergence dynamic pressure. The
determined-trim core is done (see the closure roadmap at the top of this file); the steps below
are the remaining work, in numeric order — execution order is set by the roadmap table.
**Step 58 (dihedral / anhedral ±Γ correctness) is CLOSED (2026-06-14)** — the foundational
out-of-plane gate the rest of the load chain inherits is now locked by V-C-DIH
(`tests/aero/test_dihedral.py`); the steps below build on it.

**Governing equation (g-set reduced to a-set after SPC):**

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg     (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g            (baseline camber/twist/incidence + CFD/WT)
```

**Prerequisite:** AE1 acceptance closed (Steps A–G done, including the Step C regression guard). Step 52 (determined trim) exists on the
`aeroelastics` branch as `run_sol144_trim`; over-determined trim and rate-aero columns
are unimplemented.

---

### Step 52 — SOL 144 trim solve + flexible derivatives (`sol144.py`)

**Status (2026-06-12):** determined-case Schur trim solver exists. Resolved defects:
AE2–AE7, AE9, and AE1 Steps A, B, C, D, E, F, G. Over-determined trim and
rate-aero columns remain.

**Objective:** Solve the flexible trim problem (determined and over-determined) and
recover stability/control derivatives.

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
- ✅ SOL 144 case-control whitelist (`parser/case_control.py:61`), CLI dispatch, f06 output,
  and FORCE/MOMENT flight-load export — **done (AE10 / Step 56, 2026-06-13)**; see
  `docs/40_history`. (The PITCH rate-aero column already matches NASTRAN `C_Mq` rigid — see
  `tests/aero/test_ha144a_rigid_derivs.py`; ROLL/YAW columns ride with over-determined trim.)

**Test/Acceptance (V-C1):** Trim a forward-swept / straight wing and reproduce the MSC
NASTRAN HA144A-class flexible-to-rigid derivative ratios; closed-form check vs
Bisplinghoff analytical correction. **(V-C4)** An over-determined case (two control
effectors, one equation) returns the objective-minimizing solution and satisfies the
constraints.

**Risk (KC6):** Over-determined solution may be a local optimum — document initial-guess
sensitivity (`TRIMVAR INITIAL`).

---

### Step 53 — Balanced maneuver loads & inertia relief

**Objective:** Compute balanced static maneuver loads — symmetric pull-up/push-over at a
load factor, steady roll, steady yaw/sideslip — and output the net (aero + inertial)
load for downstream stress analysis.

**Scope/Deliverables:**
- Each maneuver point is a `TRIM` subcase with prescribed `AESTAT`
  accelerations/rates and load factor
- Assemble `f_inertial = −M_aa · a` by distributing the rigid-body acceleration field
  over the structural mass (`M_aa`, `CONM2`, GPWG; `GRAV` for gravity); solve the trim
  (Step 52) so that aero + inertial + gravity is in equilibrium in the body frame
- Recover deflection + CBAR loads (mode-acceleration recovery when the modal ROM is
  active)
- Steady rotary maneuvers draw their damping aero from the antisymmetric VLM (Step 41)
- Standard maneuver-case presets: symmetric pull-up/push-over, steady roll, steady
  sideslip

**Test/Acceptance (V-C5):** Symmetric pull-up at load factor `n_z` — net
(aero + inertial) resultant equals `n_z · W` with zero residual force/moment in body
frame; recovered CBAR loads scale linearly with `n_z`. A free-aircraft
(SUPORT-referenced) case balances to ≈ 0 net force/moment.

**Risk (KC9):** Inertia-relief inconsistent with prescribed accelerations (gravity
double-counted; lumped vs consistent mass) → net imbalance — assert force/moment closure
per maneuver case.

---

### Step 54 — CFD / wind-tunnel steady-pressure injection (mean-flow trim)

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

### Step 55 — Aeroelastic divergence (`DIVERG`)

**Objective:** Solve `K_aa φ = q · Q_aa φ` for the lowest positive divergence dynamic
pressure and mode shape, driven by a `DIVERG` case-control/bulk entry (multi-q sweep
and the divergence eigenvector).

**Already delivered (Step 56):** the *single* critical divergence dynamic pressure
`q_div` is computed on the restrained l-set (`sol144._divergence_dynamic_pressure`) and
emitted in the SOL 144 f06 AERODYNAMIC DIVERGENCE block. Step 55 remains for the
`DIVERG`-card-driven q-sweep, the divergence mode shape, and `V_div`.

**Scope/Deliverables:**
- `DIVERG` card parsing + case-control hook; multi-q divergence sweep
- `sol144.py`: generalised eigenvalue solve (reuse the dense path from `sol103.py`);
  filter to the smallest positive real `q`; report the divergence **mode shape** and
  `V_div` (given ρ) in addition to the `q_div` already emitted
- Divergence depends only on `K_aa` and `Q_aa` (the `w_g`/`Q_ax` RHS does not enter the
  eigenvalue)

**Test/Acceptance (V-C2):** Goland wing and an idealised swept cantilever — `q_div`
matches the published / closed-form Bisplinghoff value within a few %.

**Risk (KC3):** Spurious negative/complex eigenvalues from the unsymmetric `Q_aa`;
document the "smallest positive real" selection rule; test against Goland.

---

### Step 57 — Viewer: SOL 144 results

**Objective:** Display trim solution, derivatives, divergence q, deflected shape, and
box `cp` in the viewer.

**Scope/Deliverables:**
- Extend `viewer/aero_view.py` and `viewer/results_view.py`: trim & derivative tables,
  flexible-vs-rigid overlay, `q_div` readout, injected-vs-computed mean-flow overlay
  when `CHORDCP` is active
- Render the **canted (±Γ dihedral/anhedral) deflected geometry** and per-box `cp` in 3-D, not a
  flattened xy-projection — the box normals and panel z-coordinates come straight from the Step 58
  geometry; a planar-only renderer would silently mis-draw any real wing
- Monitor-point integrated-load table (Fx…Mz per monitor per subcase) once MON4 lands

**Test/Acceptance:** AppTest integration test loads a SOL 144 result and renders all panels
without error, including a ±Γ dihedral deck (deflected shape shows the canted geometry, not a flat
projection).

---

## Monitor points & section loads — Phase 1 (static)

**Files (new/extended):** `sbeam/model/aero.py` (dataclasses), `sbeam/parser/bdf_reader.py`
(handlers), `sbeam/results/monitor_points.py` (new — integration logic),
`sbeam/solver/sol144.py` (call site after trim solve), `sbeam/results/f06_writer.py`
(output block), `sbeam/results/results.py` (`Sol144Result.monitor_loads`).

**Objective:** Emit integrated section loads for structures handoff from each SOL 144
trim solution — replicating NASTRAN `MONPNT1` (aero-only) and `MONPNT3` (aero +
inertia + reaction, splined to structural grids) semantics, with sbeam-native RBAR/RBE3
pass-through that avoids NASTRAN MONPNT3's known limitation with rigid-element load
paths. This becomes the standard loads-team deliverable per trim case and is the
foundation for the dynamic monitor extraction needed for CS-25.341 gust loads later.

**Prerequisite:** AE1 Step F is closed (V-AE1d green under the %-full-scale gate, 2026-06-13 —
wrong trim ⇒ wrong monitor loads). AE10 is closed (SOL 144 runs end-to-end from `main.py`;
Step 56 emits the f06 + trimmed flight loads the monitor integration builds on).

**Scope of Phase 1 (this entry):** Static `MONPNT1` + `MONPNT3` emulation only.
Section-cut running-loads tables ({V, M, T} per spanwise station) tracked as Phase 2;
dynamic monitor extraction (CS-25.341(a) discrete gust, CS-25.341(b) continuous
turbulence) tracked as Phase 3 — both pointers at the end of this section.

### Sequence at a glance

| Step | Description | Status |
|------|-------------|--------|
| MON1 | BDF parse: `MONPNT1`, `MONPNT3`, `AECOMP`, `AELIST` (SET1 already supported) | Open |
| MON2 | `MONPNT1` aero-only integrated load over AECOMP/AELIST collection | Open |
| MON3 | `MONPNT3` aero + inertia + reaction over SET1 grid collection, RBAR-expanded | Open |
| MON4 | f06 `MONITOR POINT INTEGRATED LOADS` block + CSV + HDF5 per case | Open |
| V-MON1 | HA144A SC1 cross-check — wing-root + full-wing MONPNT3 vs MSC NASTRAN | Open |

MON1 is a prerequisite for MON2/MON3; MON2 and MON3 are independent. MON4 can be
landed incrementally as MON2/MON3 come online. V-MON1 is the closing gate.

---

### MON1 — BDF parsing: `MONPNT1`, `MONPNT3`, `AECOMP`, `AELIST`

Add `Monpnt1`, `Monpnt3`, `Aecomp`, `Aelist` dataclasses to `sbeam/model/aero.py`.
Extend `parser/bdf_reader.py` with field-by-field handlers; SET1 handler already exists
(reused by MONPNT3). `AECOMP` resolves to either an AELIST (box IDs) or a SET1 (grid
IDs) — implement both lookup paths.

**Acceptance:** Round-trip echo on a synthetic BDF containing one `MONPNT1` (wing
aero-only, AECOMP→AELIST), two `MONPNT3` (wing root, HTP root; AECOMP→SET1), with one
monitor in `CID 0` and one in a user-defined CORD2R; parsed fields exactly equal the
input.

---

### MON2 — `MONPNT1`: aero-only integrated load

Sum per-box aero `F`, `M` (already computed during SOL 144 trim — wing/HTP/VTP boxes
in box CSYS) over the AECOMP/AELIST collection. Transform to the monitor reference
point and `MONPNT1.cp` CSYS. Apply parity from `AEROS.SYMXZ` consistent with AE1
Step A — same `sym` factor, single-source.

**Acceptance:** Synthetic uniform-Cp rectangular wing — analytical `L = ½ρV²S·Cp` and
moment about the reference vs `MONPNT1` integrated sum: agreement to 1e-8 relative.
Symmetric-half model with `SYMXZ=1` doubles the sum vs. the full-model build of the
same geometry. **Dihedral:** on a ±Γ deck (Step 58) the integrated `Fz` reduces by `cosΓ` and a
non-zero `Fy` appears per semi-span (`∝ sinΓ`), cancelling over the full-span build — the monitor
sum must carry the full 3-component force, not an Fz-only projection.

---

### MON3 — `MONPNT3`: aero + inertia + reaction at structural grids

Per-grid force tally over the user `SET1` collection:

- **Aero contribution:** `(G_kgᵀ · q · P_k)_g` per grid `g`, where `G_kg` is the spline
  matrix from Phase B and `P_k` is the trimmed box force. **RBAR/RBE3 pass-through uses
  the same T matrix as AE1 Step B1's `_expand_to_g`** — load on a slave grid maps to
  the master via the kinematic transform. This is where sbeam beats NASTRAN MONPNT3.
- **Inertia contribution:** `(M_gg · ü_g)` from the prescribed rigid-body acceleration
  field of the trim case. Zero by construction for the determined plain trim (Step 52);
  becomes load-bearing once Step 53 maneuver trim lands. Phase 1 emits the inertia
  column unconditionally — it's just zero in the steady case.
- **Reaction contribution:** SPC reaction at the SUPORT grids only (avoid
  double-counting — reaction is already in equilibrium with aero+inertia per the
  Schur r-set row).

Sum the three contributions over `SET1`, transform to `MONPNT3.cp` CSYS, apply parity.
Output `Fx, Fy, Fz, Mx, My, Mz` plus a per-contribution breakdown (`Fz_aero`,
`Fz_inertia`, `Fz_react`) for diagnostic use.

**Acceptance:** HA144A SC1 trim — `MONPNT3` defined as `SET1 = {100, 110, 120}` (the
full wing EA) returns `Fz = 8 000 lb · parity` within 1 %, and `My` matching the NASTRAN
MONPNT3 output for the same SET1 within 1 %. Symmetric-half parity treated identically
to AE1 Step A.

---

### MON4 — Output: f06 block + CSV + HDF5 per trim case

- New f06 block `MONITOR POINT INTEGRATED LOADS` in `results/f06_writer.py` matching
  the NASTRAN layout (header + one row per monitor per subcase: `LABEL`, `AXES`,
  `COMP`, `CID`, `X/Y/Z`, six force/moment values).
- **CSV per trim case:** one row per monitor; columns
  `case, name, x_ref, y_ref, z_ref, cid, Fx, Fy, Fz, Mx, My, Mz` plus the diagnostic
  `Fz_aero / Fz_inertia / Fz_react` breakdown.
- **HDF5 hierarchical:** `/monitors/{name}/{case}` storing the six components plus
  metadata (CSYS, reference point, parity factor, AECOMP/SET1 source IDs). Same file
  the structures team will reuse for the Phase 3 time-domain extension.

**Acceptance:** Snapshot test of the f06 block against a reference text file;
CSV/HDF5 values identical to the f06 to 1e-12; HDF5 schema documented in
`docs/10_standard/05_aeroelastics.md`.

---

### V-MON1 — HA144A cross-check (closing gate)

Add two `MONPNT3` cards to `sample/ha144a_fullspan_sbeam.bdf`:
1. Wing-root cut — `SET1 = {100}` (inboard EA grid only).
2. Full wing — `SET1 = {100, 110, 120}` (all three EA grids, matches the EA-only SET1
   landed under AE1 Step B).

Plus one `MONPNT1` summing the wing CAERO1 boxes (aero-only sanity check).

**Acceptance:**

- Full-wing `MONPNT3 Fz` = total trimmed lift · parity within 1 % (8 000 lb · sym).
- Full-wing `MONPNT3 My` about the AERO ref point matches NASTRAN `MONPNT3` output
  within 1 %.
- Wing-root `MONPNT3 Fz / My` matches NASTRAN within 1 %.
- `MONPNT1` aero-only sum equals the aero contribution of the full-wing `MONPNT3`
  to 1e-8 (no inertia in determined trim).

---

### Open decisions before MON1 starts

1. **Coordinate frames.** Support `CID = 0` (basic), `AEROS.RCSID` (aero), and
   user-defined `CORD2R` from day 1 — no incremental rollout.
2. **Inertia source.** For Phase 1, `ü` is taken from the trim case (zero for plain
   trim, non-zero only when Step 53 maneuver lands). No external mass-distribution
   overlay in Phase 1; defer the typical loads-workflow "fuel/payload sweep" to a
   later add.
3. **Parity.** Single-source via the same `sym` factor used in AE1 Step A. Annotate
   the f06 output with `*whole-airplane*` when `SYMXZ = 1` so the structures team
   doesn't double-up downstream.
4. **AECOMP composition.** Both `AELIST` (box ID set) and `SET1` (grid ID set) lookup
   paths required — used by `MONPNT1` and `MONPNT3` respectively in NASTRAN
   convention.
5. **Diagnostic breakdown.** Always emit `Fz_aero`, `Fz_inertia`, `Fz_react`
   alongside the totals — cheap, and the only way to debug a wrong sum after the fact.

---

### Phase 2 (later) — Section-cut running loads

The actual stress-team deliverable: per-station `{Vz, My, Mt}` tables along the wing,
HTP, VTP. Cut convention: plane normal along the spline-axis `x̂` at user-specified
stations (general normal as override). Builds directly on MON3's per-grid tally — a
section cut is "sum the per-grid loads outboard of the cut plane, project to EA
intercept". Lands after Phase 1 + the maneuver trim case (Step 53), so the inertia
column is non-trivial.

### Phase 3 (later) — Dynamic monitor extraction

CS-25.341(a) discrete 1-cos gust (H = 30–350 ft sweep) and CS-25.341(b) continuous
turbulence (von Kármán PSD → A·σ envelope) at each monitor, with correlated
companion-load extraction for stress. Built on the same monitor data model as
Phase 1. Lands with the SOL 146 / dynamic-response solvers (program Phase 3).

---

## Phase 2 / Phase 3 / Future development

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
