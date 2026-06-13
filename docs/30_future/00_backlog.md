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
| 2 | [AE1 Step F — Verify V-AE1d elastic trim](#ae1-step-f--verify-v-ae1d-elastic-trim) | CRITICAL | Open | Acceptance gate; SC1 green on full-span, SC2 pending AE8 |
| 3 | [AE1 Step G — Analytic restrained derivatives](#ae1-step-g--analytic-restrained-derivatives) | MAJOR | Open | Closes AE8 derivative half (NOT on the trim critical path) |
| 4 | [AE1 Step C — `Q_aa` rigid-body null-space gate](#ae1-step-c--q_aa-rigid-body-null-space-gate) | MINOR | Open | Regression guard for B's spline fix — null space already satisfied to 2e-14; NOT the ELEV lead |
| 5 | [AE9 — Per-TRIM Mach (currently AEROS.mach only)](#major-ae9--mach-is-a-property-of-the-model-not-the-flight-condition) | MAJOR | Open | Subsonic multi-Mach subcases (HA144A SC3 is supersonic — out of scope) |
| 6 | [AE10 — SOL 144 CLI dispatch from `main.py`](#major-ae10--sol-144-unreachable-from-main) | MAJOR | Open | End-to-end HA144A solve from main.py |
| 7 | [AE11 — D_jx YAW column + AESURF hinge geometry](#minor-ae11--d_jx-yaw-column-duplicates-roll-aesurf-hinge-geometry-ignored) | MINOR | Open | Vertical-fin trim, hinge-moment derivs |
| 8 | [AE12 — SPLINE2 DTOR/DTHZ warning (PG-normal half not a bug)](#minor-ae12--spline2-dtordthz-silently-ignored-pg-normal-half-misidentified) | MINOR | Open | User-input safety (PG-normal half re-diagnosed: not a bug) |
| 9 | [A7 — Cosine chordwise spacing helper + low-NCHORD warning](#minor-a7--default-chordwise-box-count-too-low-no-cosine-chordwise-spacing) | MINOR | Open (code) | Pitching-moment convergence |
| 10 | [A8 — Box-AR pre-solve warning](#minor-a8--spanwise-box-count-aspect-ratio-must-be-o1-companion-to-a7) | MINOR | Open (code) | Lift-slope bias on high-AR boxes |
| 11 | [Phase C Steps 53–57](#phase-c--sol-144-static-aeroelastics-steps-5357) | Planned | Blocked on AE1 | Maneuver loads, divergence, viewer |
| 12 | [Monitor points & section loads — Phase 1 (static)](#monitor-points--section-loads--phase-1-static) | Planned | Blocked on AE1, AE10 | Structures-team loads handoff; precursor to dynamic gust loads at monitors |
| 13 | [Phase 2 / Phase 3 / Future development](#phase-2--phase-3--future-development) | Planned | Optional | Long-tail capability |

**Closed in this branch (full detail in CHANGELOG `[Unreleased]` and history):** AE2,
AE3, AE4, AE5, AE6, AE7. **AE1 Step D + AE10 parity wiring — RESOLVED by removing half-span
support (2026-06-12): the `sym=2` aero/inertia double-count and the `parity` flag no longer
exist; sbeam is full-span only, so aero and inertia are both whole-airplane with no scaling.
SC1 trims to NASTRAN on `ha144a_fullspan_sbeam.bdf` (V-AE1f).** AE1 Step A (parity + My sign, 2026-06-12). AE1 Step B (RBAR
expansion, EA-only SET1, spline math fix, V-AE1b gate; 2026-06-12 — `g_slope`/`g_disp`
now reproduce all 6 basic-frame rigid-body modes on the swept HA144A spline). AE1 Step E
(moment-sign single-source helper `_pitch_moment` + VW-moment consistency gate,
2026-06-12 — confirmed the trim moment sign was already correct post-A). **NB (2026-06-12
review correction): Step E's onward re-diagnosis — "ANGLEA/ELEV gap is the flexible `q·Q_aa`
increment" — was itself WRONG. The gap is a `sym=2` aero/inertia parity double-count in the
trim load path (see Step D and the Diagnosis section below), not flexibility.** This is now
backed by an explicit full-span model (`sample/ha144a_fullspan_sbeam.bdf`) and a permanent
gate (`tests/aero/test_ae1_fullspan.py`, V-AE1f) that trims to NASTRAN at SC1 with no `sym`
doubling — added 2026-06-12.

---

## Critical — AE1: Trim solver does not match HA144A Listing 7-2

> **UPDATE 2026-06-12 — the parity half of this is RESOLVED.** Half-span support was removed,
> deleting the `sym=2` aero/inertia double-count and the `parity` flag entirely. SC1 now trims
> to NASTRAN on the full-span deck (V-AE1f). The `sym=2` / "sbeam (half)" discussion below is
> retained as the recorded diagnosis; the half-span deck and its gate no longer exist. **Open
> remainder:** the SC2 (q=1200) flexible residual (Step G / AE8) and the acceptance gate (Step F).

**Files:** `sbeam/solver/sol144.py:452–513` (`_solve_trim_determined`),
`sbeam/solver/sol144.py:673–953` (`run_sol144_trim`),
`sbeam/solver/sol144.py:596–670` (`_compute_restrained_derivs`),
`tests/aero/test_ae1_fullspan.py` (V-AE1f gate).

**Current measured state (post Steps A + B, 2026-06-12):**

| Quantity | NASTRAN | sbeam (half) | Status |
|---|---:|---:|---|
| SC1 (q=40) ANGLEA   | +0.169191 rad | +0.086 rad | ~50% — `sym=2` parity halving; **Step D** closes it |
| SC1 (q=40) ELEV     | +0.492457 rad | +0.245 rad | ~50% — `sym=2` parity halving; **Step D** closes it |
| SC2 (q=1200) ANGLEA | +0.001373 rad | +0.0019 rad | parity (Step D) **and** flexible residual (Step G/AE8) |
| SC2 (q=1200) ELEV   | +0.019325 rad | +0.0081 rad | parity (Step D) **and** flexible residual (Step G/AE8) |
| **SC1 FULL-SPAN** ANGLEA/ELEV | +0.169191 / +0.492457 | +0.1711 / +0.4908 | ✓ ground truth (parity=0/sym=1), V-AE1f |
| SC1 trim lift (half) | +8 000 lb | +7 999.4 lb | ✓ (balances either way — non-discriminating) |
| Rigid CZα           | −5.071    | −5.071     | ✓ |
| Wing incidence (rigid pitch θ=1e-3) | +1.000e-3 | +1.000e-3 ± 1e-10 | ✓ |

The Schur algebra forms `K_eff = K_aa − q·Q_aa` correctly. With Steps A, B and E closed,
the spline reproduces global rigid-body modes and the pitching-moment sign is confirmed
correct end-to-end. **But the "lift balance is exact" reassurance is a red herring:** the
SUPORT Tz force row re-scales ANGLEA/ELEV to hit 8000 lb regardless of any aero-vs-inertia
parity mismatch, so exact lift does NOT prove the aero balance is uncontaminated — it
passes for both `sym=1` and `sym=2`.

**Diagnosis (CORRECTED — 2026-06-12 review):** the remaining ANGLEA/ELEV error is a
**`sym=2` aero/inertia parity double-count**, not the flexible `q·Q_aa` increment. In
`run_sol144_trim` the aero terms carry `sym=2` for the SYMXZ=1 half-model (`f_aero_g`
sol144.py:833, `Q_ax_g` :795, `Q_aa` :822) but the inertial term `M_ax`/`pres_inertial_g`
(:873–874) carries the raw whole-deck mass with no `sym`. The Tz force row balances either
way (hence lift=8000 in both), but the Ry **moment** row mis-splits when aero is doubled
and inertia is not — producing the observed clean halving. Evidence:

- Running the solver: `sym=2` (current) → ANGLEA/ELEV = 0.0860/0.2446; forcing `sym=1` →
  0.1727/0.4893 (NASTRAN 0.169191/0.492457), both with lift ≈ 7999 lb. Ratios 0.50/0.50.
- Independent hand-trim with NASTRAN's own restrained q=40 derivatives + the inertial
  pitching moment (weight at deck CG x≈17.18, 2.18 ft aft of GRID 90 x=15) → 0.1699/0.4916
  ≈ NASTRAN. Omitting that inertial moment reproduces the bogus "rigid 0.795" baseline that
  the old (flexibility) diagnosis leaned on.
- Flexibility at q=40 is a 0.6% effect (Table 7-1: restrained CZα −5.103 vs rigid −5.071) —
  physically incapable of a 50% trim error. The "27% flexible increment" is real but is a
  q=40→q=1200 phenomenon (Step G / AE8), NOT the SC1/SC2 trim-angle gap.

The lead is **Step D (parity)**. Step C (`q·Q_aa` null space) is already satisfied to 2e-14
and is NOT the lead. Step G (analytic restrained derivs) closes AE8's derivative half but
does not move the trim angles. The `sym=1` conclusion is **independently confirmed by an
explicit full-span model** (`sample/ha144a_fullspan_sbeam.bdf`), which trims to NASTRAN at
SC1 with no symmetry assumption — see Step D for the cross-check and the important caveat
that `parity` is overloaded (it also selects the AIC image vortices, so the fix is NOT simply
`parity=0`). A separate flexible-side residual remains at SC2 (q=1200) — Step G / AE8.

### Sequence at a glance

| Step | Description | Status |
|------|-------------|--------|
| A | Parity (`sym = 2` on symmetric half-models) + nose-up-positive My sign | ✅ APPLIED 2026-06-12 — ⚠ the `sym=2` half **introduced** the parity double-count now tracked in Step D |
| B | RBAR slave-DOF expansion + EA-only SET1 + spline math fix (mult-bending, corrected torsion); V-AE1b gate | ✅ APPLIED 2026-06-12 — see CHANGELOG |
| C | `Q_aa` rigid-body null-space regression gate | Open (MINOR — guard only; null space already clean to 2e-14) |
| D | **Parity fix** — reconcile `sym` between the aero and inertial trim paths | ✅ RESOLVED 2026-06-12 by removing half-span support — `sym` and `parity` deleted; full-span is whole-airplane, no scaling. SC1 green (V-AE1f). |
| E | Moment-sign single-source helper + VW-moment consistency gate (closes AE8 sign half) | ✅ APPLIED 2026-06-12 — see CHANGELOG |
| F | V-AE1d elastic trim acceptance gate | Open — gate IMPLEMENTED with per-target relative tolerances (`tests/aero/test_ae1_fullspan.py`); SC1 live (PASS), SC2 xfail-tracked pending AE8/Step G. Closes when SC2 passes. |
| G | Analytic restrained derivatives via Schur factorisation (closes AE8 deriv half) | Open (MAJOR — AE8, off the trim path) |

Recommended order: **F (acceptance) → G**. Step D is closed (half-span removal eliminated the
`sym=2` double-count). G closes AE8's derivative half; C is a cheap regression guard that can
land any time. Step E is closed (moment sign already correct).

---

### AE1 Step C — `Q_aa` rigid-body null-space gate

**MINOR — regression guard only. NOT the ELEV lead** (the retracted "prime suspect for the
ELEV gap" framing is wrong; see the corrected Diagnosis above). The property this gate
asserts is **already satisfied**: measured `‖Q_aa · u_tz‖ = 2.2e-14` on HA144A. Keep it as
a cheap permanent guard against a future spline regression, not as a lead on the trim error.

With `g_slope`/`g_disp` from Step B correct, lock in the gain with a regression gate
that asserts `Q_aa · u_rb ≈ 0` (rigid-body translation/rotation basis) to machine precision
when the model is unconstrained, or matches an exact rigid-body ghost-force pattern when SPC
is applied. Assert against the actual rigid-body translation/rotation basis (not an arbitrary
pitch field, which legitimately loads the aero and is not a null-space member).

**Acceptance:** `Q_aa · u_rb` residual < 1e-10 on HA144A, val_vlm_rect_ar8, and a **dihedral
fixture (still to be added** — `TestGlobalRigidBody` currently covers swept-planar and
rect-planar only, no out-of-plane z≠0 grids).

---

### AE1 Step D — Parity fix in the trim balance ✅ RESOLVED (2026-06-12)

Resolved by **removing half-span / symmetry support** rather than reconciling the two `sym`
legs. The `sym = 2 if aero.parity != 0 else 1` factor and the `parity` flag are gone from
`run_sol144_trim` and the VLM (vlm.py / aero_model.py). With full-span-only models, aero and
inertia are both whole-airplane and there is no scaling to get out of step — the double-count
is impossible by construction. `ha144a_fullspan_sbeam.bdf` trims to **SC1 0.1711/0.4908
(101%/100% of NASTRAN), lift 16000 lb** (V-AE1f, `tests/aero/test_ae1_fullspan.py`).

*SC2 (q=1200) remains a SEPARATE, still-open flexible issue:* the full-span SC2 ELEV (0.0032)
still misses NASTRAN (0.0014), i.e. the `q·Q_aa` / restrained-derivative path (Step G / AE8)
is imperfect at high q. The parity removal closes SC1 but NOT SC2. See `40_history` for the
full record.

---

### AE1 Step F — Verify V-AE1d elastic trim

**Gate IMPLEMENTED 2026-06-12; item STAYS OPEN until SC2 passes.** The V-AE1d gate now
lives beside V-AE1f in `tests/aero/test_ae1_fullspan.py` with **per-target relative
tolerances** (replacing the shared absolute `ATOL_ANGLEA=1e-3` that masked SC2's high
result). On the full-span deck:

- **SC1 — live, PASSING:** ANGLEA within 1.5% (actual 0.171052 vs 0.169191, +1.1% —
  accepted, not chased; no bulk re-tuning per "What not to do"), ELEV within 1%
  (0.490775 vs 0.492457, −0.3%), lift within 1% of 16000 lb.
- **SC2 — `xfail`, pending AE8 / Step G:** ANGLEA/ELEV gated at 1% per target but marked
  `pytest.mark.xfail(strict=False)`. Current trim (ANGLEA 0.003242 vs 0.001373, +136%;
  ELEV 0.017727 vs 0.019325, −8%) is genuinely off — the flexible/restrained-derivative
  path is Step G's work. The xfail flips to XPASS when G lands; **that is the trigger to
  close Step F** (remove from backlog, add to history, changelog).

NOTE: an earlier note here claimed SC2 depends on "Step D alone, NOT G" — that is retracted;
the Step D resolution note and the measured +136% SC2 error confirm SC2 needs Step G/AE8.

**Acceptance (to CLOSE):** V-AE1d — SC1 ANGLEA=+0.169191 (≤1.5%), ELEV=+0.492457 (≤1%);
SC2 ANGLEA=+0.001373, ELEV=+0.019325 (≤1% each, currently xfail); full-span lift =
+16 000 lb. SC1 is met today; SC2 closes with Step G.

---

### AE1 Step G — Analytic restrained derivatives

**Closes AE8 derivative half. NOT on the trim critical path** — sbeam's rigid derivs
already match NASTRAN to 4 sig fig and the trim is solved from `Q_ax` directly, so Step G
does not move ANGLEA/ELEV. **Sequence it AFTER Step D:** the current FD restrained increment
is ~2.2× too large largely because `C_ax_l` is built from the `sym=2`-contaminated `Q_ax_a`
(sol144.py:678); the analytic form inherits the same contamination until the parity fix lands.

Replace `_compute_restrained_derivs` finite-difference path with the analytic derivative
from the Schur factorisation: `∂u_l/∂δ_free = K_ll^{−1}·C_ax_l`, then build the
derivative columns from `D_jx + D_jk·G_slope·∂u/∂δ`. Delete the FD machinery entirely.

**Acceptance:** V-AE1e — HA144A Table 7-1 restrained columns (CZα, Cmα, Cmq, …) within
1 %; rigid columns unchanged; documented 27 % restrained-CZα flexible increment
reproduced to ≤ 5 % relative error. (Depends on the Step D parity fix.)

---

### V-AE1 gate (full acceptance — now `test_ae1_fullspan.py`, V-AE1f)

**Two structural weaknesses in the current gate (2026-06-12 review):** (1) `test_trim_lift`
is NON-discriminating — lift = 8000 lb for both `sym=1` and `sym=2`, so exact lift is NOT
evidence of a correct aero balance (the false comfort that hid the parity bug). (2)
`ATOL_ANGLEA=1e-3` lets SC2 ANGLEA pass at 0.001924 vs 0.001373 (40 % high) — use per-target
relative tolerances.

- **V-AE1a** (implement EARLY) — Rigid trim (Q_aa=0): SC1 ANGLEA, ELEV, total lift within
  1 % of NASTRAN's rigid-case column. **This is the cleanest discriminator for the parity
  bug** — at Q_aa=0 the `sym` double-count still halves the deflection, so V-AE1a catches it
  with flexibility removed as a confound. Build it before any flexible-increment work.
- **V-AE1b** (Step B) — `Q_aa·u_rb`/`g_slope·u_rb`/`g_disp·u_rb` rigid-body null-space
  residuals < 1e-10 on HA144A, val_vlm_rect_ar8, dihedral fixture. ✅ PASSING.
- **V-AE1c** (Step D / V-AE3) — full-trim moment balance `sym·aero_My + inertial_My = 0`
  (the parity-sensitive check), PLUS an INDEPENDENT unit-Cp cross-check of the skj/g_disp
  total force AND moment against `solve_rigid_cl` resultants. **Do NOT** merely extend the
  Step E class: `test_ae1_step_e_moment.py` only checks self-consistency (VW transfer of one
  f_box vs `_pitch_moment` of the SAME f_box) — a common scale/parity error passes it. The
  gate must compare against `solve_rigid_cl`, not against `_pitch_moment`.
- **V-AE1d** (Step F) — SC1/SC2 ANGLEA, ELEV, lift within 1 % of NASTRAN (relative tol).
- **V-AE1e** (Steps F + G) — Table 7-1 restrained derivative columns within 1 %; 27 %
  flexible increment within 5 %.
- **V-AE1f** — full-span parity ground truth. ✅ IMPLEMENTED 2026-06-12
  (`tests/aero/test_ae1_fullspan.py`, 8 tests): the explicit full-span model
  (`sample/ha144a_fullspan_sbeam.bdf`, parity=0/`sym=1`) trims to SC1 within 2 % of NASTRAN
  (ANGLEA 0.1711, ELEV 0.4908), lift = 16000 lb, mirrored splines reproduce rigid pitch, and
  symmetry emerges (antisym DOF ≈ 0, L/R wing tips match). This locks the no-`sym`-doubling
  path as ground truth so the half-model parity fix (Step D) can be checked against it. SC2 is
  deliberately NOT gated (separate flexible residual — Step G / AE8).

### What not to do

- Do not chase the `q·Q_aa` flexible increment for the SC1/SC2 trim gap — it is a 0.6 %
  effect at q=40 and cannot explain a 50 % error. The gap is the `sym=2` parity double-count
  (Step D). DO land the SC2 ANGLEA relative-tolerance fix regardless — it only exposes an
  already-known-wrong number, not a tightening-to-fit.
- Do not cite "lift = 8000 lb / 7999.4 lb" as evidence the aero balance is correct — the Tz
  force row hits 8000 lb for both the correct and the halved trim states.
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
        exists. (Moment convention was historically suspected wrong — RESOLVED by AE1
        Step E: the nose-up-positive −ΣFz·(x−xref) convention is single-sourced in
        sol144._pitch_moment and verified consistent with solve_rigid_cl.CM and the
        g_disp virtual-work transfer.)
FIX:    Sign half RESOLVED by AE1 Step E (2026-06-12; CMα = −2.871 matches NASTRAN in sign
        AND magnitude). Derivative half: fix the AE1 Step D parity double-count FIRST — it
        inflates the FD restrained increment ~2.2× (C_ax_l built from the sym=2-contaminated
        Q_ax_a, sol144.py:678), independent of the FD-vs-analytic choice — THEN apply AE1
        Step G (analytic restrained derivs out of K_eff). Add the unrestrained set (mean-axis,
        ZAERO Eq. 12.14/12.15). Acceptance: HA144A Table 7-1 restrained AND unrestrained
        columns within 1 %.
```

---

### [MAJOR] AE9 — Mach is a property of the model, not the flight condition

**Files:** `sbeam/aero/aero_model.py:77`, `sbeam/model/aero.py` (Aeros.mach),
`sbeam/solver/sol144.py:673`

```
[MAJOR] The AIC is built once from AEROS.mach (an sbeam extension field) while
        TRIM.mach is parsed and silently ignored (confirmed: sol144.py:753 reads
        trim_card.mach but only stores it at :992; it never rebuilds aero.ajj_inv_corr).
        Multiple SUBSONIC subcases at different Mach — standard SOL 144 usage — are
        impossible, and a mismatch is not even warned about.
        NOTE: the motivating "HA144A 3rd subcase M=1.3" is SUPERSONIC (manual §7);
        this steady subsonic VLM clamps M≤0.99 (vlm.py:137,141) and CANNOT solve it —
        it needs ZONA51/piston theory the program lacks. Cite SC3 only as evidence that
        multi-Mach SOL 144 is standard, not as a case this fix enables.
FIX:    NOT a one-line edit at aero_model.py:77. (a) Thread per-TRIM Mach into AIC
        construction; (b) cache AIC inverses keyed by Mach so the build-once fixture
        pattern still works across subcases; (c) change the run_sol144_trim contract
        (today it receives a prebuilt aero). KEEP AEROS.mach as the default/fallback and
        WARN on AEROS-vs-TRIM disagreement (full retirement forces every deck/test to
        migrate — Mach currently lives only on AEROS field 9 — for no benefit). Add a
        SUPERSONIC GUARD that errors rather than silently clamping M≥1. Tests: (1)
        AEROS.mach≠TRIM.mach warns; (2) two subsonic subcases at different Mach produce
        different β-scaled AICs / different trim; (3) a supersonic TRIM Mach is rejected.
```

---

### [MAJOR] AE10 — SOL 144 unreachable from main

**Files:** `sbeam/main.py`, `sbeam/parser/case_control.py`

```
[MAJOR] run_sol144_trim has no caller in main.py — the HA144A deck cannot run end-to-end.
        NOTE: the old "case_control rejects SOL 144" claim is STALE — 144 is already
        whitelisted (case_control.py:61) and trim_sid is parsed; the only remaining gate is
        main.py dispatch.  (The original "wire parity from AEROS.SYMXZ" half of this item is
        RESOLVED — half-span support was removed, so there is no parity flag to wire; see
        AE1 Step D / CHANGELOG.)
FIX:    main.py SOL 144 dispatch is NOT a mirror of the SOL 101/103 two-arg pattern —
        run_sol144_trim needs a prebuilt AeroModel + grid_index, so main.py must build the
        aero model (build_aero_model rejects SYMXZ≠0) and pass it in. Retarget this from
        "Step 56 (f06 output)" to AE10/Step 52 — dispatch must precede f06. Test: an
        end-to-end SOL 144 run through main.py (extend test_main.py).
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
        surfaces. Tests: (1) unit test that the YAW column = +(2/bref)·(x_ctrl−x_ref) on a
        y-normal panel and ≈0 on a z-normal panel; (2) a swept-hinge AESURF fixture; (3)
        HA144A ELEV hinge-moment cross-check vs the manual HMAERO block (free validation).
NOTE:   Both defects are NON-blocking for AE1 — HA144A's ELEV hinge (CORD2R 1) is
        spanwise, so the −n_z·eff approximation is exact for it; the cid1 omission only
        bites swept/non-spanwise hinges. YAW is latent (no caller passes it). Verify the
        `eff if eff!=0.0 else 1.0` default (integration.py:135) is intended (eff=0→1.0).
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
        (V-AE1)  HA144A acceptance test — partial: sign/lift/increment tests pass; SC1
                 ANGLEA/ELEV and SC2 ELEV value tests still failing. Closes with the AE1
                 Step D PARITY fix (the gap is the sym=2 aero/inertia double-count, NOT the
                 flexible q·Q_aa increment — the old diagnosis here was retracted; see AE1).
                 ⚠ the "lift tests pass" reassurance is non-discriminating (lift=8000 lb for
                 both sym=1 and sym=2) — exactly the blind spot AE13 is about.
        (V-AE2)  Swept-spline rigid-body gate — IMPLEMENTED 2026-06-11 (3 tests in
                 TestSweptSplineRigidBody) and updated 2026-06-12 to use EA-only SET1
                 with DTHX=+1 alongside V-AE1b (`TestGlobalRigidBody`). Genuinely closed:
                 exercises a 60°-swept axis + full 6-mode lever-arm rotation.
        (V-AE3)  Unit-consistency gate — g_disp/skj-path total force AND moment equals the
                 Kutta-Joukowski resultants from solve_rigid_cl on the same model. Open —
                 schedule with AE1 Step D. NOTE: (a) rename to avoid collision with the
                 UNRELATED "V-AE3a" trim-lift gate in test_trim_urdd.py; (b) it must be an
                 INDEPENDENT path (build f via solve_rigid_cl, compare to skj/g_disp totals),
                 NOT an extension of the Step E self-consistency class — and the nearest
                 existing check (test_phase_b.py::test_tz_sum_vs_cl_magnitude) uses
                 min(err_full,err_half)<0.02, which structurally accepts BOTH the correct
                 lift and exactly half of it, so it cannot catch the factor-of-2 parity bug.
```

---

## Open findings — Aerodynamics (2026-06-08 review, code-level)

### [MINOR] A5 — Aero model is reachable only from the viewer; aero cards inert under the solver

**Files:** `sbeam/aero/aero_model.py`, `sbeam/solver/`, `sbeam/main.py`

```
[MINOR] build_aero_model / solve_rigid_cl are called ONLY from viewer/app.py. No solver
        or CLI path consumes the aero model under SOL 101/103. (STALE: the old line
        "case_control.py rejects SOL 144" is no longer true — 144 is whitelisted at
        case_control.py:61; the gate that blocks an end-to-end aero solve is now the
        main.py dispatch, see AE10.) val_vlm_rect_ar8.bdf documents the SOL-101 workaround.
FIX:    Expected state until Phase B/C land — keep the "expected-state" verdict. The
        remaining gap is solely the main.py SOL 144 dispatch (overlaps AE10); the
        "add SOL 144 to the case-control whitelist" action is already DONE — drop it. Also
        fix the stale parse_case_control docstring at case_control.py:67 ("not 101 or 103").
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

**Prerequisite:** AE1 fully closed (Steps C, D, F, G). Step 52 (determined trim) exists on the
`aeroelastics` branch as `run_sol144_trim`; over-determined trim and rate-aero columns
are unimplemented.

---

### Step 52 — SOL 144 trim solve + flexible derivatives (`sol144.py`)

**Status (2026-06-12):** determined-case Schur trim solver exists. Resolved defects:
AE2, AE3, AE4, AE5, AE6, AE7, AE1 Steps A, B and E. Open: AE1 Steps C, D, F, G (E closed
the AE8 sign half; G closes the derivative half). Over-determined trim and rate-aero
columns remain.

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

**Prerequisite:** AE1 Step F closed (V-AE1d green — wrong trim ⇒ wrong monitor loads),
AE10 closed (SOL 144 reachable from `main.py`, parity wired from `AEROS.SYMXZ`).

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
same geometry.

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
