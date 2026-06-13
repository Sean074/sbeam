# sbeam — Development Plan, Bugs & To-Do

Authoritative backlog of open bugs, in-progress work, and planned development. Updated as
part of every session that completes a step — never deferred. Completed steps are recorded
in `docs/40_history/00_completed_development.md`. When an item is promoted to a formal
step, give it a step number continuing from Step 39 and apply the same step format
(Objective, Deliverables, Test/Acceptance).

---

## Recommended action plan

Order reflects what unblocks the most downstream work; close in sequence unless noted.

| # | Item | Severity | Status | What it unblocks |
|--:|------|----------|--------|------------------|
| 1 | [AE1 Step E — Moment-sign reconciliation](#ae1-step-e--moment-sign-reconciliation) | CRITICAL | Open | AE1 Schur r-set equilibrium row |
| 2 | [AE1 Step C — `Q_aa` rigid-body null-space gate](#ae1-step-c--q_aa-rigid-body-null-space-gate) | CRITICAL | Open | Permanent regression for B's spline fix |
| 3 | [AE1 Step D — Parity audit in the trim balance](#ae1-step-d--parity-audit-in-the-trim-balance) | CRITICAL | Open | Hardens Step A's numeric parity fix |
| 4 | [AE1 Step F — Verify V-AE1d elastic trim](#ae1-step-f--verify-v-ae1d-elastic-trim) | CRITICAL | Open | Closes V-AE1 SC1/SC2 ANGLEA/ELEV |
| 5 | [AE1 Step G — Analytic restrained derivatives](#ae1-step-g--analytic-restrained-derivatives) | CRITICAL | Open | Closes V-AE1e and AE8 |
| 6 | [AE9 — Per-TRIM Mach (currently AEROS.mach only)](#major-ae9--mach-is-a-property-of-the-model-not-the-flight-condition) | MAJOR | Open | Multi-Mach subcases (HA144A's 3rd SC) |
| 7 | [AE10 — Wire `parity` from `AEROS.SYMXZ`; SOL 144 CLI dispatch](#major-ae10--parity-not-wired-from-aerossymxz-sol-144-unreachable-from-main) | MAJOR | Open | End-to-end HA144A solve from main.py |
| 8 | [AE11 — D_jx YAW column + AESURF hinge geometry](#minor-ae11--d_jx-yaw-column-duplicates-roll-aesurf-hinge-geometry-ignored) | MINOR | Open | Vertical-fin trim, hinge-moment derivs |
| 9 | [AE12 — PG normals + SPLINE2 DTOR/DTHZ warnings](#minor-ae12--pg-compression-keeps-original-normals-spline2-dtordthz-silently-ignored) | MINOR | Open | Dihedral correctness; user-input safety |
| 10 | [A7 — Cosine chordwise spacing helper + low-NCHORD warning](#minor-a7--default-chordwise-box-count-too-low-no-cosine-chordwise-spacing) | MINOR | Open (code) | Pitching-moment convergence |
| 11 | [A8 — Box-AR pre-solve warning](#minor-a8--spanwise-box-count-aspect-ratio-must-be-o1-companion-to-a7) | MINOR | Open (code) | Lift-slope bias on high-AR boxes |
| 12 | [R16–R19 docs + R21, R22 NITs](#minor-r16r19--documentation-gaps-and-r21r22-nits) | MINOR/NIT | Open | Code-standard documentation hygiene |
| 13 | [Phase C Steps 53–57](#phase-c--sol-144-static-aeroelastics-steps-5357) | Planned | Blocked on AE1 | Maneuver loads, divergence, viewer |
| 14 | [Phase 2 / Phase 3 / Future development](#phase-2--phase-3--future-development) | Planned | Optional | Long-tail capability |

**Closed in this branch (full detail in CHANGELOG `[Unreleased]` and history):** AE2,
AE3, AE4, AE5, AE6, AE7. AE1 Step A (parity + My sign, 2026-06-12). AE1 Step B (RBAR
expansion, EA-only SET1, spline math fix, V-AE1b gate; 2026-06-12 — `g_slope`/`g_disp`
now reproduce all 6 basic-frame rigid-body modes on the swept HA144A spline).

---

## Critical — AE1: Trim solver does not match HA144A Listing 7-2

**Files:** `sbeam/solver/sol144.py:452–513` (`_solve_trim_determined`),
`sbeam/solver/sol144.py:673–953` (`run_sol144_trim`),
`sbeam/solver/sol144.py:596–670` (`_compute_restrained_derivs`),
`tests/aero/test_ae1_keff_trim.py` (V-AE1 gate).

**Current measured state (post Steps A + B, 2026-06-12):**

| Quantity | NASTRAN | sbeam | Status |
|---|---:|---:|---|
| SC1 (q=40) ANGLEA   | +0.169191 rad | +0.086 rad | 51% of target — Steps E/G remaining |
| SC1 (q=40) ELEV     | +0.492457 rad | +0.245 rad | 50% of target — Steps E/G remaining |
| SC2 (q=1200) ANGLEA | +0.001373 rad | +0.0019 rad | 140% — Steps E/G remaining |
| SC2 (q=1200) ELEV   | +0.019325 rad | +0.0081 rad | 42% — Steps E/G remaining |
| SC1 trim lift       | +8 000 lb | +7 999.4 lb | ✓ |
| Rigid CZα           | −5.071    | −5.071     | ✓ |
| Wing incidence (rigid pitch θ=1e-3) | +1.000e-3 | +1.000e-3 ± 1e-10 | ✓ |

The Schur algebra forms `K_eff = K_aa − q·Q_aa` correctly. With Steps A and B closed,
`Q_aa` and the trim aero balance are no longer contaminated, lift balance is exact, and
the spline reproduces global rigid-body modes. Remaining ANGLEA/ELEV error is driven by
two independent defects, addressed by Steps C–G below.

### Sequence at a glance

| Step | Description | Status |
|------|-------------|--------|
| A | Parity (`sym = 2` on symmetric half-models) + nose-up-positive My sign | ✅ APPLIED 2026-06-12 — see CHANGELOG |
| B | RBAR slave-DOF expansion + EA-only SET1 + spline math fix (mult-bending, corrected torsion); V-AE1b gate | ✅ APPLIED 2026-06-12 — see CHANGELOG |
| C | `Q_aa` rigid-body null-space regression gate | Open |
| D | Parity audit (unit-Cp → SUPORT row vs `solve_rigid_cl`) | Open |
| E | Moment-sign single-source helper (closes AE8 sign half) | Open |
| F | V-AE1d elastic trim acceptance gate | Open |
| G | Analytic restrained derivatives via Schur factorisation (closes AE8 deriv half) | Open |

Steps C–G can be worked in parallel except F, which depends on E. Recommended order
matches the action plan table: E (smallest, unblocks the moment row) → C (lock in B's
gains) → D (parity audit; complements Step A) → F (acceptance) → G (post-F polish).

---

### AE1 Step E — Moment-sign reconciliation

**Couples to AE8 (sign half).**

The pitching-moment column used by the Schur Ry SUPORT row is `My = +ΣFz·(x−x_ref)`
(`sol144.py:546, :580, :925`). This is opposite-signed to both `solve_rigid_cl.CM` and
NASTRAN's nose-up-positive Cm convention. With the wrong sign in front of every
ELEV-effectiveness term, the Schur solve converges to the value that *would* balance a
nose-up moment if the sign were correct.

**Fix:** Adopt nose-up positive Cm about RCSID throughout the trim chain. Single-source
the moment-arm formula `(x_ctrl − x_ref)·F_z` with the agreed sign in one helper. Apply
in `_compute_aero_forces.My`, `_compute_rigid_derivs.CMY`, the Schur r-set row for the Ry
SUPORT DOF, and the f06 STABILITY DERIVATIVES block.

**Acceptance:** Post Step E the SC1 ELEV value moves from ≈+0.245 toward NASTRAN's
+0.492 (the sign error currently halves it).

---

### AE1 Step C — `Q_aa` rigid-body null-space gate

With `g_slope`/`g_disp` from Step B correct, lock in the gain with a regression gate
that asserts `Q_aa · u_rb ≈ 0` (Tz and Ry global rigid-body) to machine precision when
the model is unconstrained, or matches an exact rigid-body ghost-force pattern when SPC
is applied. `Q_aa` losing its rigid-body null space would be the defining symptom of any
future regression; this gate must pass for `K_eff = K_aa − q·Q_aa` to carry physical
meaning.

**Acceptance:** `Q_aa · u_rb` residual < 1e-10 on HA144A, val_vlm_rect_ar8, and the
dihedral fixture introduced with V-AE1b.

---

### AE1 Step D — Parity audit in the trim balance

Trace one unit `Cp` on a wing box through `skj·Cp → g_disp^T·f_box → SUPORT row of
f_rhs_r`. Compare against `solve_rigid_cl` applied to the same Cp distribution and
reference point. They must agree numerically *including* the symmetry factor. Establish
a single rule: either (a) `skj` carries the parity multiplier so all downstream paths
see whole-airplane forces, or (b) inertial/weight inputs are halved on symmetric-half
models. Document the choice in `aero/integration.py` and `aero/aero_model.py`; assert at
trim entry.

**Acceptance:** V-AE1c — skj-path SUPORT-row force equals `solve_rigid_cl` lift to 1e-6
for one unit-Cp injection.

---

### AE1 Step F — Verify V-AE1d elastic trim

With A–E green, re-run the V-AE1 gate and tighten tolerances. SC1 and SC2 ANGLEA/ELEV
must match Listing 7-2 to ≤ 1 %, and the q=40 → q=1200 ratio must reproduce the
documented 27 % restrained-CZα flexible increment.

**Acceptance:** V-AE1d — SC1 ANGLEA=+0.169191, ELEV=+0.492457; SC2 ANGLEA=+0.001373,
ELEV=+0.019325; total lift = +8 000 lb; all within 1 %.

---

### AE1 Step G — Analytic restrained derivatives

**Closes AE8 derivative half.**

Replace `_compute_restrained_derivs` finite-difference path with the analytic derivative
from the Schur factorisation: `∂u_l/∂δ_free = K_ll^{−1}·C_ax_l`, then build the
derivative columns from `D_jx + D_jk·G_slope·∂u/∂δ`. Delete the FD machinery entirely.

**Acceptance:** V-AE1e — HA144A Table 7-1 restrained columns (CZα, Cmα, Cmq, …) within
1 %; rigid columns unchanged; documented 27 % restrained-CZα flexible increment
reproduced to ≤ 5 % relative error.

---

### V-AE1 gate (full acceptance, replaces `test_ae1_keff_trim.py` once landed)

- **V-AE1a** (Step A) — Rigid trim (Q_aa=0): SC1 ANGLEA, ELEV, total lift within 1 % of
  NASTRAN's rigid-case column.
- **V-AE1b** (Step B) — `Q_aa·u_rb`/`g_slope·u_rb`/`g_disp·u_rb` rigid-body null-space
  residuals < 1e-10 on HA144A, val_vlm_rect_ar8, dihedral fixture. ✅ PASSING.
- **V-AE1c** (Step D) — skj-path SUPORT-row force = `solve_rigid_cl` lift to 1e-6 on a
  unit-Cp injection.
- **V-AE1d** (Step F) — SC1/SC2 ANGLEA, ELEV, lift within 1 % of NASTRAN.
- **V-AE1e** (Steps F + G) — Table 7-1 restrained derivative columns within 1 %; 27 %
  flexible increment within 5 %.

### What not to do

- Do not pursue tighter tolerances on `test_ae1_keff_trim.py` until Step E lands —
  current failure mode is a wrong matrix sign, not noise.
- Do not re-tune HA144A bulk parameters (NSPAN/NCHORD, spline DTOR, RCSID) to fit V-AE1;
  rigid CLα already reproduces NASTRAN to 4 sig fig at the same mesh.
- Do not delete the existing `K_eff = K_aa − q·Q_aa` line; AE1 is now about what feeds
  into it, not the line itself.

---

## Open findings — Aerodynamics (2026-06-11 review)

207 aero/integration tests passed at review time despite the HA144A trim being grossly
wrong (validation blind spot — see AE13). The VLM core is verified to 4 sig fig vs
NASTRAN rigid CLα; the defects below sit in the integration, spline, and trim layers.
AE1 is tracked above; AE2/AE3/AE4/AE5/AE6/AE7 are resolved (see CHANGELOG).

---

### [MAJOR] AE8 — Stability-derivative formulation internally inconsistent and incomplete

**Files:** `sbeam/solver/sol144.py:482–637`

```
[MAJOR] Restrained derivatives perturb via K_ll⁻¹ (no aero feedback in the re-solve) but
        evaluate forces INCLUDING w_struct — a one-pass hybrid converging to neither
        NASTRAN's restrained nor unrestrained columns. No unrestrained (mean-axis) set
        exists. Moment convention (+ΣFz·(x−xref)) is opposite in sign to both
        solve_rigid_cl.CM and NASTRAN Cm.
FIX:    Sign half resolved by AE1 Step E. Derivative half resolved by AE1 Step G
        (analytic restrained derivs out of K_eff). Add the unrestrained set (mean-axis,
        ZAERO Eq. 12.14/12.15). Acceptance: HA144A Table 7-1 columns.
```

---

### [MAJOR] AE9 — Mach is a property of the model, not the flight condition

**Files:** `sbeam/aero/aero_model.py:77`, `sbeam/model/aero.py` (Aeros.mach),
`sbeam/solver/sol144.py:673`

```
[MAJOR] The AIC is built once from AEROS.mach (an sbeam extension field) while
        TRIM.mach is parsed and silently ignored. Two subcases at different Mach —
        standard SOL 144 usage (HA144A's own third subcase is M=1.3) — are impossible,
        and a mismatch is not even warned about.
FIX:    Build (and cache) the AIC per TRIM Mach; retire the AEROS.mach extension field;
        warn/error on AEROS-vs-TRIM Mach disagreement during the transition.
```

---

### [MAJOR] AE10 — `parity` not wired from `AEROS.SYMXZ`; SOL 144 unreachable from main

**Files:** `sbeam/aero/aero_model.py:44`, `sbeam/main.py`, `sbeam/parser/case_control.py`

```
[MAJOR] Every caller passes parity manually; nothing reads AEROS.symxz, so a
        wrong-parity solve is silent. run_sol144_trim has no caller at all — the HA144A
        deck cannot run end-to-end (overlaps A5 / Step 56, but the symxz wiring is
        independent and one line).
FIX:    Default parity = aeros.symxz inside build_aero_model (explicit argument
        overrides); wire SOL 144 dispatch in main.py as part of Step 56.
```

---

### [MINOR] AE11 — D_jx YAW column duplicates ROLL; AESURF hinge geometry ignored

**Files:** `sbeam/aero/integration.py:122–125, 130–143`, `sbeam/model/aero.py`
(`Aesurf.cid1`)

```
[MINOR] YAW uses −(2/bref)·y_ctrl (same as ROLL); yaw rate on a vertical fin produces
        sidewash ∝ (x − x_ref), not ∝ y. AESURF cid1 is parsed but the control downwash
        is just −n_z·eff — no hinge-sweep projection, no rotation for non-spanwise
        hinges, no hinge-moment output (NASTRAN prints hinge-moment derivatives for
        HA144A — free validation data going unused).
FIX:    Derive the control column from rotation about the actual hinge axis
        (cid1 y-axis); add hinge-moment recovery; correct the YAW column for vertical
        surfaces.
```

---

### [MINOR] AE12 — PG compression keeps original normals; SPLINE2 DTOR/DTHZ silently ignored

**Files:** `sbeam/aero/vlm.py:144–156`, `sbeam/aero/spline.py`, `sbeam/parser/bdf_reader.py`

```
[MINOR] prandtl_glauert_boxes scales y,z but copies the un-recomputed normal — exact
        only for planar surfaces; wrong for dihedral/out-of-plane panels (assert or
        document planarity). Spline2.dtor and dthz are parsed but unused — silently
        accepting and ignoring NASTRAN card fields is how the AE4(c) DTHX
        misinterpretation went unnoticed.
FIX:    Recompute (or validate) normals under PG compression; warn when DTOR/DTHZ carry
        non-default values that will be ignored.
```

---

### [MINOR] AE13 — Validation gap: no swept/coupled/benchmark gates (partially closed)

**Files:** `tests/aero/`, `tests/integration/`, `sample/ha144a_sbeam.bdf`

```
[MINOR] 207 tests passed at review time with every defect above present. Every
        geometric validation case was unswept and uncoupled; the V-B1/V-B3 rigid-body
        gates never exercised a swept spline axis or fore/aft offset grids; no
        dimensional-consistency check tied the coupled force path back to the rigid
        solver.
FIX:    Three permanent gates planned; status today:
        (V-AE1)  HA144A acceptance test — partial: sign/lift/increment tests pass; SC1
                 ANGLEA/ELEV and SC2 ELEV value tests still failing. Closes with AE1
                 Steps E–G.
        (V-AE2)  Swept-spline rigid-body gate — IMPLEMENTED 2026-06-11 (3 tests in
                 TestSweptSplineRigidBody) and updated 2026-06-12 to use EA-only SET1
                 with DTHX=+1 alongside V-AE1b (`TestGlobalRigidBody`).
        (V-AE3)  Unit-consistency gate — g_disp.T @ skj-path total force/moment equals
                 the Kutta-Joukowski resultants from solve_rigid_cl on the same model.
                 Open — schedule with AE1 Step D (closely related parity audit).
```

---

## Open findings — Aerodynamics (2026-06-08 review, code-level)

### [MINOR] A5 — Aero model is reachable only from the viewer; aero cards inert under the solver

**Files:** `sbeam/aero/aero_model.py`, `sbeam/solver/`, `sbeam/main.py`

```
[MINOR] build_aero_model / solve_rigid_cl are called ONLY from viewer/app.py. No solver
        or CLI path consumes the aero model; there is no SOL 144 (Phase C) and no
        spline (Phase B). Therefore the aero cards in airplane_aero.bdf are inert under
        its declared SOL 101, and any aero BDF must declare SOL 101/103 to clear
        case-control (case_control.py rejects SOL 144). val_vlm_rect_ar8.bdf documents
        this workaround.
FIX:    Expected state until Phase B/C land. Track as the Phase B (spline) → Phase C
        (SOL 144) wiring work; add SOL 144 to the case-control whitelist when Phase C
        starts. Overlaps AE10.
```

---

### [MINOR] A7 — Default chordwise box count too low; no cosine chordwise spacing

**Files:** `sample/airplane_aero.bdf`, `sample/val_vlm_rect_ar8.bdf`, `sbeam/aero/panel.py`

```
[MINOR] Sample models used NCHORD=2 (airplane) / NCHORD=1 (rect val). Lift converges at
        NCHORD=1 (1/4-3/4 rule is 2D-exact), but a chordwise convergence study showed
        the PITCHING MOMENT is grossly under-resolved at low counts: CM shifts ~50%
        from NCHORD 1→2, ~34% 2→4, and only settles to ~1-2% drift by NCHORD~8 (across
        0/18/35 deg sweep). Chordwise loading/pressure are likewise unconverged.
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

## Open findings — Documentation & NITs (2026-05-25 review)

### [MINOR] R16–R19 — Documentation gaps; and R21, R22 NITs

| ID | File | Issue | Fix |
|----|------|-------|-----|
| R16 | `docs/10_standard/00_program_overview.md:28–44, 163–178` | Module table omits `assembly/load_vector.py`; verification table missing V15–V18 (GRAV+CBAR, GRAV+CONM2, GRAV+FORCE via LOAD, RBE2 lever-arm). | Add `load_vector.py` row; add V15–V18 rows. |
| R17 | `docs/10_standard/01_beam_model.md:585` | "Cards recognised" summary line omits GRAV and RBAR, both fully implemented and tested. | Add GRAV and RBAR to the comma-separated list. |
| R18 | `docs/10_standard/03_static_analysis.md:237–256` | `assemble_load_vector` shown as living in `sol101.py` (now `assembly/load_vector.py`); function signatures stale; CBUSH, RBAR, GRAV not mentioned in any verification case. | Update module reference, signatures; add GRAV and RBAR verification cases. |
| R19 | `tests/` | V14 covers only the zero-offset RBAR (identity R-matrix); no end-to-end BDF + solver test exercises the lever-arm kinematics with a non-coincident RBAR. | Add `v_rbar_offset.bdf` and a corresponding integration test asserting the expected lever-arm deflection. |
| R21 | `sbeam/solver/sol101.py:252–255` | `check_spc_enforced_displacements` called unconditionally when `spc_sid` may be `None`. `bulk.spcs.get(None, [])` returns `[]` safely, so no crash, but the intent is unclear. | Add `if spc_sid is not None:` guard before the call. |
| R22 | `sbeam/main.py:8` | `_build_f06_sol101_text` and `_build_f06_sol103_text` are imported by their private names. Any rename in `f06_writer.py` silently breaks the import. | Drop leading underscores from both function names in `f06_writer.py`, or add public aliases there. |

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
aspect-ratio pre-solve warning); and from the 2026-06-11 review: **AE9** (per-TRIM
Mach), **AE12** (PG normals).

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

## Phase C — SOL 144 Static Aeroelastics, Steps 53–57

Phase C wires Phases A + B into the structural stiffness to solve the flexible static
aeroelastic problem: trim (determined and over-determined), flexible stability/control
derivatives, optional CFD/WT mean-flow injection, and divergence dynamic pressure.

**Governing equation (g-set reduced to a-set after SPC):**

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg     (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g            (baseline camber/twist/incidence + CFD/WT)
```

**Prerequisite:** AE1 fully closed (Steps E–G). Step 52 (determined trim) exists on the
`aeroelastics` branch as `run_sol144_trim`; over-determined trim and rate-aero columns
are unimplemented.

---

### Step 52 — SOL 144 trim solve + flexible derivatives (`sol144.py`)

**Status (2026-06-12):** determined-case Schur trim solver exists. Resolved defects:
AE2, AE3, AE4, AE5, AE6, AE7, AE1 Steps A and B. Open: AE1 Steps C–G (closes AE8 sign
and derivative halves). Over-determined trim and rate-aero columns remain.

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
- Add SOL 144 to the case-control whitelist in `parser/case_control.py`

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
pressure and mode shape.

**Scope/Deliverables:**
- `sol144.py`: generalised eigenvalue solve (reuse the dense path from `sol103.py`);
  filter to the smallest positive real `q`; report `q_div` and `V_div` (given ρ)
- Divergence depends only on `K_aa` and `Q_aa` (the `w_g`/`Q_ax` RHS does not enter the
  eigenvalue)

**Test/Acceptance (V-C2):** Goland wing and an idealised swept cantilever — `q_div`
matches the published / closed-form Bisplinghoff value within a few %.

**Risk (KC3):** Spurious negative/complex eigenvalues from the unsymmetric `Q_aa`;
document the "smallest positive real" selection rule; test against Goland.

---

### Step 56 — SOL 144 f06 output + flight/maneuver-load export

**Objective:** Write the static aeroelastic results to `.f06`, and export the trimmed
loads as `FORCE`/`MOMENT` cards for downstream stress analysis.

**Scope/Deliverables:**
- New f06 blocks in `results/f06_writer.py`: TRIM VARIABLES, STABILITY DERIVATIVES,
  AERODYNAMIC DIVERGENCE, AERODYNAMIC PRES/FORCES; reuse existing displacement and
  CBAR-force blocks
- `results/results.py`: new `Sol144Result` (trim variables, flexible stability/control
  derivatives, divergence q, box pressures/forces, structural displacement, recovered
  CBAR loads, grid flight-load vectors)
- `SubcaseControl` output requests `AEROF` (aero box forces) and `APRES` (aero box
  pressures)
- **Load export:** grid loads as NASTRAN `FORCE`/`MOMENT` bulk-data cards per subcase;
  for a plain trim this is `G_kgᵀ·q·P_k`; for a maneuver case (Step 53) this is the net
  (aero + inertial) balanced load for downstream stress

**Test/Acceptance:** Snapshot/regression test of the f06 text for a sample SOL 144 run;
the exported `FORCE`/`MOMENT` set sums to the total trimmed lift/moment (plain trim) and
to `n_z · W` with zero residual (maneuver case).

---

### Step 57 — Viewer: SOL 144 results

**Objective:** Display trim solution, derivatives, divergence q, deflected shape, and
box `cp` in the viewer.

**Scope/Deliverables:**
- Extend `viewer/aero_view.py` and `viewer/results_view.py`: trim & derivative tables,
  flexible-vs-rigid overlay, `q_div` readout, injected-vs-computed mean-flow overlay
  when `CHORDCP` is active

**Test/Acceptance:** AppTest integration test loads a SOL 144 result and renders all
panels without error.

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
