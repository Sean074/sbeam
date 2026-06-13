# sbeam — Development Plan, Bugs & To-Do

This file is the authoritative backlog for all open bugs, in-progress work, and planned
development. It is updated as part of every session that completes a step — never deferred.

When a backlog item is promoted to a formal step, give it a step number continuing from Step 39
and apply the same step format (Objective, Deliverables, Test/Acceptance).

Completed steps are recorded in `docs/40_history/00_completed_development.md`.

---

## Code Review — 2026-06-11 — Aeroelastics critical design review (Phases A–C, HA144A benchmark)

Critical design review of the full aeroelastic chain (`aero/`, `solver/sol144.py`) against the
MSC Nastran HA144A benchmark (Aeroelastic Analysis User's Guide Listing 7-2 / Table 7-1) and the
ZAERO 9.2 Theoretical Manual (trim: Ch. 12; splines: Ch. 6). All 207 aero/integration tests pass,
yet the HA144A trim is grossly wrong — the validation suite has a systematic blind spot (every
geometric case is unswept and uncoupled; see AE13). Reproduction script:
`studies/_review_ha144a_check.py`.

**Measured state (sample/ha144a_sbeam.bdf) vs NASTRAN reference:**

| Quantity | NASTRAN | sbeam (2026-06-11) |
|---|---|---|
| SC1 (q=40): ANGLEA, ELEV | +0.169191, +0.492457 rad | −0.0980, −1.1974 rad |
| SC2 (q=1200): ANGLEA, ELEV | +0.001373, +0.019325 rad | −0.00158, −0.0416 rad |
| Trim lift | +8 000 lb (=W) | −8 012 lb (trims to −1g) |
| Rigid CZα (M=0.9) | −5.07097 | −6.339 (sol144 path) / −5.755 (rigid solver) |

**Key positive:** AE3 is resolved — the rigid solver gives CLα = 5.0709 vs NASTRAN
5.07097 at the same 40-box mesh — the Biot–Savart kernel, symmetry image, and Göthert PG
implementation are validated to 4 significant figures. Remaining damage is in the integration,
spline, and trim layers.

---

### [CRITICAL] AE1 — Trim solver does not converge to the HA144A Listing 7-2 reference

**Files:** `sbeam/solver/sol144.py:452–513` (`_solve_trim_determined`),
`sbeam/solver/sol144.py:673–953` (`run_sol144_trim`),
`sbeam/solver/sol144.py:596–670` (`_compute_restrained_derivs`),
`sbeam/aero/spline.py` (g_slope nodal-rotation projection on swept axes),
`sbeam/aero/integration.py` (parity in skj force assembly),
`tests/aero/test_ae1_keff_trim.py` (V-AE1 gate — currently failing every assertion).

**Symptom (governing problem statement):** the trim solver does not reproduce the MSC
NASTRAN Listing 7-2 reference for HA144A.

**Measured state — original (2026-06-12, before any AE1 fixes):**

| Quantity | NASTRAN | sbeam (pre-fix) | Error |
|---|---|---|---|
| SC1 (q=40) ANGLEA   | +0.169191 rad | −0.5698 rad   | wrong sign, 3.4× too large |
| SC1 (q=40) ELEV     | +0.492457 rad | +14.257 rad   | ≈29× too large |
| SC2 (q=1200) ANGLEA | +0.001373 rad | +0.003798 rad | ≈2.8× too large |
| SC2 (q=1200) ELEV   | +0.019325 rad | +0.025496 rad | ≈1.3× too large |
| Trim lift           | +8 000 lb     | +4 299 / +4 794 lb | ≈54 %/60 % (factor-of-2 fingerprint) |

**Measured state — after Step A (parity + My sign fixes, 2026-06-12):**

| Quantity | NASTRAN | sbeam (post Step A) | Status |
|---|---|---|---|
| SC1 (q=40) ANGLEA   | +0.169191 rad | +0.097 rad   | ≈57 % of target — contaminated Q_aa |
| SC1 (q=40) ELEV     | +0.492457 rad | +0.079 rad   | ≈16 % of target — contaminated Q_aa |
| SC2 (q=1200) ANGLEA | +0.001373 rad | +0.00057 rad | ≈42 % of target — Q_aa dominant at high q |
| SC2 (q=1200) ELEV   | +0.019325 rad | +0.013 rad   | ≈67 % of target |
| SC1 trim lift       | +8 000 lb     | +8 140 lb    | ✓ parity fixed |
| Rigid CZα           | −5.071        | −5.071       | ✓ correct |
| Wing incidence (rigid pitch θ=1e-3) | +1.0e-3 everywhere | −9.45e-2 to +4.53e-2 | ✗ g_slope error |

**Originally reported (2026-06-11):** `_solve_trim_determined` received bare `K_aa`; `Q_aa`
was assembled but only stored in the result — no aeroelastic closure. Original fix: form
`K_eff = K_aa − q·Q_aa` and reuse the existing Schur partition. **That fix has been
applied** (`sol144.py:481`; `_solve_trim_determined` now takes `Q_aa` and builds `K_eff`
internally), the Schur algebra is correct, and `run_aeroelastic_static` (Step 50, no-trim
path) was already doing it. The trim solver is **still failing the V-AE1 gate** — the
issue is therefore not the closure formulation itself but the matrices and sign
conventions it operates on.

**Why the existing approach fails to fully resolve the issue.** Four independent defects
compound inside the Schur solve. AE1 cannot close until all four are tracked and gated;
chasing only the `K_eff` algebra polishes the wrong floor.

1. **`Q_aa` is contaminated by upstream swept-spline kinematics (interacts with AE4).**
   The V-AE2 swept-spline tests (`test_spline.py::TestSweptSplineRigidBody`) verify a
   *non-standard* "rigid-along-spline-axis" pitch — `Tz_i = −x̂₀·s_i·θ`, `Ry_i = θ` —
   constructed to make the cubic-Hermite interpolant exact along the spline parameter.
   They do **not** verify the case the trim solver actually feeds into `Q_aa·u_a`: a
   global rigid-body Ry rotation about the basic y-axis. The same study that fails
   V-AE1 shows the wing g_slope returning incidence `[−0.0945, +0.0453]` for a global
   pitch θ=1e-3 that should give uniform `+1.0e-3` everywhere:

   ```
   rigid pitch θ=1e-3:  wing incidence min/max = −9.450e-02  +4.527e-02  (expect 1.0e-03)
   EA twist   φ=1e-3:  wing incidence min/max = −1.103e-01  +1.022e-02  (expect ω_y = 8.660e-04)
   ```

   Root cause: when the swept spline projects a nodal rotation vector onto the spline-
   parameter slope `m_i = dh/ds`, the projection uses `Ry·ŷ[1]` (the y-component of the
   spline y-axis), but the physically correct projection for a node carrying basic-frame
   rotation `ω = (Rx, Ry, Rz)` is `m_i = −(ω × x̂)·ẑ` — the slope of `h` along `x̂`
   induced by `ω`, measured in the spline `ẑ` direction. For an unswept spline
   `x̂=(1,0,0)`, `ŷ=(0,1,0)`, both formulas reduce to `−Ry`; for the HA144A wing spline
   `x̂=(−0.5, 0.866, 0)`, the simplified formula misses the cross term. V-AE2b masks
   this by feeding a kinematic state already pre-projected onto the spline parameter; the
   trim solver feeds in the genuine global mode, which is not.

   Consequence: `Q_aa = g_disp^T · S_kj · A_jj*^(−1) · D_jk · g_slope` is wrong on every
   swept aero box for every structural deformation. `K_eff = K_aa − q·Q_aa` correctly
   subtracts the wrong elastic stiffness, so the q-dependence in V-AE1 (the entire point
   of SC1 vs SC2) is corrupted, not just shifted.

2. **Parity / symmetry-image factor of 2 (independent of AE10).** HA144A is a symmetric
   half-model (`AEROS.SYMXZ=1`); aerodynamic forces from `skj·Cp` represent half the
   airplane, while inertial relief from `M_ax·URDD` and the trim weight target (8 000 lb
   total) are full-airplane. The current `_solve_trim_determined` and
   `_compute_restrained_derivs` apply neither doubling nor halving. Today's measured
   lift ≈ 54 % / 60 % of 8 000 lb is the unmistakable fingerprint of a missing factor of
   2 on the aero side of the trim balance (the residual departure from exactly 50 % is
   the elastic over/undershoot driven by defect 1). This is logically separate from
   AE10 (which wires `parity` into `build_aero_model` from `AEROS.SYMXZ`); even with
   AE10 fixed, the trim solver still needs to know whether to double aero or halve
   inertia.

3. **Moment-convention sign flip in the Schur r-set rows (interacts with AE8).** The
   pitching-moment column the trim equation uses for the Ry SUPORT row is
   `My = +ΣFz·(x−x_ref)` (`sol144.py:546`, `:580`, `:925`). This is *opposite-signed* to
   both `solve_rigid_cl.CM` and NASTRAN's nose-up-positive Cm convention — flagged in
   AE8 for the derivative output, but it lives in the same arithmetic on the *trim
   equation* itself (the r-set equilibrium row). With the wrong sign in front of every
   ELEV-effectiveness term, the Schur solve drives ELEV toward the value that *would*
   balance a nose-up moment if the sign were correct — explaining how SC1 ELEV can land
   at +14.26 rad without the solver becoming singular. The Schur `schur_A` matrix is
   still non-singular because the sign error is uniform across the column; the solve
   converges, but to the wrong root.

4. **`_compute_restrained_derivs` rebuilds the linearisation with an inconsistent
   recovery path (already noted by AE8, restated for completeness).** With AE1's `K_eff`
   in place, the analytic derivative is available directly from the Schur factorisation
   — the finite-difference perturbation should be deleted entirely. Keeping the FD path
   active during AE1 closure is actively misleading: the FD step solves the
   *aeroelastic* l-set system with `K_ll^{−1}` of `K_eff_ll`, then evaluates aero forces
   through the (defect-1) g_slope, then divides by `q·sref` — three multiplications of
   the same defect. The stability-derivative output will not match Table 7-1 until both
   AE1's matrices are correct *and* `_compute_restrained_derivs` is replaced.

**Expanded fix — sequenced; each step has its own gate that must pass before moving on.**
Order matters: defect 1 contaminates the matrices, defect 2 the balance, defect 3 the
sign of one equation, defect 4 the post-process. Closing out of order produces
compensating-error fits that pass V-AE1 on HA144A but fail any other swept-wing case.

  **Step A — Parity + My sign fix. ✅ APPLIED (2026-06-12).** `sym = 2` applied to
  `Q_ax_g`, `Q_gg`, and `f_aero_g` in `run_sol144_trim` for symmetric half-models
  (`aero.parity != 0`). My sign flipped to nose-up-positive in `_compute_aero_forces`,
  `_compute_rigid_derivs`, and total CM in `run_sol144_trim`. SC1 lift now +8 140 lb ✓;
  rigid CZα = 5.071 ✓. ANGLEA/ELEV still wrong because Q_aa is contaminated (Step B
  unresolved). The formal rigid_trim_only=False gate and V-AE1a test were not added —
  parity was confirmed numerically instead.

  **Step B — Global rigid-body kinematic gate for `g_slope` / `g_disp`. ⚠ UNRESOLVED — design below.**

  Investigation 2026-06-12: `g_slope @ u_rigid_pitch` returns wing incidence
  [−9.45e-02, +4.53e-02] for a global θ=1e-3 pitch (expect +1.0e-3 everywhere). The
  canard incidence is exactly correct (+1.0e-3) because the canard SET1 grids lie on
  the EA. SET1 1100 (wing) holds {99, 100, 111, 112, 121, 122}:

  | GRID | (x, y) basic | s = (r−origin)·x̂ | ŷ-offset from EA(s) | Role |
  |-----:|-------------:|------------------:|--------------------:|------|
  | 100 | (30.000, 0)   |  0.00 | 0.00  | EA root |
  | 112 | (29.613, 5)   |  4.52 | 1.87  | RBAR slave of 110 (TE stringer) |
  | 99  | (20.000, 0)   |  5.00 | 8.66  | **Fuselage centerline — not on wing EA at all** |
  | 111 | (24.613, 5)   |  7.02 | 1.87  | RBAR slave of 110 (LE stringer) |
  | 122 | (23.840, 15)  | 16.07 | 1.87  | RBAR slave of 120 (TE stringer) |
  | 121 | (18.840, 15)  | 18.57 | 1.87  | RBAR slave of 120 (LE stringer) |

  The EA grids 100, **110**, **120** carry the wing CBARs; 110 and 120 are NOT in SET1
  1100. The SET1 holds the RBAR-slave stringers (111/112/121/122) and a fuselage grid
  (99) — i.e. the cards that should be the *targets* of the spline, not its supports.
  GRID 99 sitting 8.66 ft off the y=0 spline-axis projection is the dominant
  contaminator: at s=5 it injects a Tz value that the Hermite is forced to fit between
  the two nearby low-s nodes, producing the oscillation that bleeds into every covered
  box.

  **Resolution of the two candidate root causes posed at the previous session:**

  *(1) "Does Tz+Ry self-correct for chord-offset nodes?"* — **No.** Proof: for a node at
  spline parameter s_i with chord offset Δ_i = (r_i − origin)·ŷ in the spline frame,
  the Hermite input is `(s_i, h_i, m_i)` where:

  - `h_i = ẑ · u_i` (z-component of nodal displacement, evaluated AT THE NODE, not at
    the EA point of the same s).
  - `m_i = −ω_i · ŷ` (bending-slope projection of the nodal rotation, no chord coupling).

  Under global pitch θ about y-axis at x_ref:
  - `u_i = (0, 0, −θ·(x_i − x_ref))`, so `h_i = −θ·(x_i − x_ref)`.
  - Along the EA at the same s, the physical h would be `h_EA(s_i) = −θ·(x_EA(s_i) − x_ref)`.
  - The difference is `Δh_i = h_i − h_EA(s_i) = −θ·(x_i − x_EA(s_i))`. For HA144A's GRID 99
    that is `−θ·(20 − 27.5) = +7.5 θ` — exactly the offset the Hermite has no information
    to back out.
  - The Ry projection `m_i = −ŷ[1]·θ = +0.5θ` is the slope of `h_EA(s)`, identical at on-EA
    and off-EA nodes. It only constrains `dh/ds` at the node; it cannot reach back and
    correct the `h_i` value. So the residual `Δh_i` rides through the Hermite untouched
    and aliases as a spurious bending-slope contribution between nodes.

  Corollary: **the projection formula in `spline.py` is correct for collinear SET1
  grids** (V-AE2b proves this), and there is no formula fix that recovers the right
  answer when SET1 contains off-axis grids. The bug is in the *model assumption*: SPLINE2
  is a 1-D beam spline; SET1 must be the EA, not the lifting-surface vertices.

  *(2) "Is RBAR slave-DOF expansion missing in the recovery path?"* — **Yes, and it is a
  separate, independent bug.** In `run_sol144_trim:884–887` the a-set solution is
  scattered to `displacements` by direct indexing on `free_dofs`. The same pattern lives
  in `_compute_restrained_derivs:630–634` and `:652–654`. RBAR slave DOFs (111/112/
  121/122 in HA144A) are left at zero. Then `w_struct = djk @ (aero.g_slope @ displacements)`
  at line 919 — and equally inside `_compute_aero_forces` — sees the stringer grids
  pinned to zero while their masters move. For HA144A the entire wing is RBAR-coupled,
  so under any elastic deformation the spline sees an L-shaped displacement field
  (master moves, slaves don't) instead of a rigid section translation.

  Fix is one line, repeated three times: replace the index-and-fill loop with a T-matrix
  expansion:

  ```python
  # In _compute_aset_data return: also return T, then in run_sol144_trim:
  u_red = np.zeros(len(red_dofs))
  for local_i, red_i in enumerate(free_local):
      u_red[red_i] = u_a[local_i]
  displacements = T @ u_red          # full g-set with RBAR slaves moving with masters
  ```

  Same change inside `_compute_restrained_derivs` for the nominal and perturbed states.

  **Two independent bugs; both must be fixed.** Bug (1) alone defeats V-AE1b on HA144A.
  Bug (2) alone defeats V-AE1d on any HA144A-like model that uses RBARs to attach
  stringers. They compound today.

  **Solution — three deliverables, parallel to each other but all required.**

  **B1. Code: RBAR-expanded recovery in the trim path (bug 2).**
   - `_compute_aset_data` returns `T` alongside the existing tuple.
   - `run_sol144_trim` replaces lines 884–887 with `displacements = T @ u_red` where
     `u_red` is the reduced-set vector with `u_a` placed at `free_local` and SPC rows zero.
   - `_compute_restrained_derivs` (lines 631–634 nominal; 652–654 perturbed) reuses
     the same expansion via a small helper `_expand_to_g(u_a, T, red_dofs, free_local, n_g)`.
   - `_compute_aero_forces` should receive `u_g` (post-expansion) only — callers must
     pass the expanded vector, not the a-set one with zeros at slaves.
   - Acceptance: with B1 alone, on a non-RBAR test model (e.g. `val_vlm_rect_ar8.bdf`)
     trim results are unchanged (regression guard); on HA144A the wing incidence under
     a unit u_a rigid heave at GRID 110 now also moves the RBAR slaves 111/112 to the
     same Tz value (verify by inspecting `displacements[6*grid_index[111] + 2]`).

  **B2. Sample model: fix `sample/ha144a_sbeam.bdf` SET1 1100 to the EA grids (bug 1).**
   - Change `SET1, 1100, 99, 100, 111, 112, 121, 122` to `SET1, 1100, 100, 110, 120`.
     These three grids are the wing-EA CBAR endpoints (100 root, 110 mid, 120 tip).
   - Verify s-coordinates are monotone with no chord offset: GRID 100 → s=0;
     GRID 110 (27.11325, 5) → s = (−2.88675)·(−0.5) + 5·0.866 = 1.44 + 4.33 = 5.77;
     GRID 120 (21.33975, 15) → s = (−8.66025)·(−0.5) + 15·0.866 = 4.33 + 12.99 = 17.32.
     All three on the EA line (chord offset Δ_i ≈ 0 to machine precision).
   - The torsion mode of the EA is then carried by SPLINE2 with DTHX=1 (attached) — the
     current `DTHX=-1` (detached, "twist arrives through fore/aft offset grids") is what
     justified the off-EA SET1 in the first place. With the EA-only SET1 we must flip
     `DTHX=1` so the Rx rotation of the master EA grid drives torsion incidence.
   - Acceptance: with B2 alone, `studies/_review_ha144a_check.py` rigid-pitch test
     prints `wing incidence min/max = +1.0e-03 ± 1e-10` (currently [−9.45e-02, +4.53e-02]).
     This is the single most diagnostic numerical change in the entire AE1 sequence.

  **B3. Code: SPLINE2 SET1 collinearity validator (defence in depth).**
   - In `_build_spline2_block`, after `s_gid` is built, compute the chord offset of each
     SET1 grid: `Δ_i = (r_i − origin)·ŷ_spline`.
   - If `max|Δ_i| > tol · s_range` (tol default 0.05, configurable), raise `ValueError`
     with a message naming the offending grid IDs, their (x,y) positions, their s-
     coordinates, their chord offsets, and the span range. Include the suggestion to
     either move the grids onto the EA or use SPLINE1 (when implemented) for 2-D
     scatter.
   - The validator catches the original SET1 1100 immediately and prevents any future
     user from silently writing the same bug.
   - Acceptance: a regression test `tests/aero/test_spline_validator.py::test_off_axis_set1_raises`
     constructs an HA144A-like bulk with the broken SET1 and asserts the ValueError
     fires with the expected grid IDs in the message.

  **B4. Test gate: V-AE1b — global rigid-body kinematics on the fixed model.**
   New test class `tests/aero/test_spline.py::TestGlobalRigidBody`, using the FIXED
   HA144A wing spline fixture (post-B2). For each of 6 basic-frame rigid-body modes
   d ∈ {Tx, Ty, Tz, Rx, Ry, Rz} applied to *every* grid in the model (not just SET1):
   - Build `u_g` with that DOF set on all grids; for rotations also fill the translation
     DOFs with the rigid-body lever-arm `−ω × r` at every grid relative to a chosen
     reference point.
   - Compute `w = g_slope @ u_g` and `disp = g_disp @ u_g`.
   - Assert against analytic expectations on a flat wing in the xy-plane:
     | Mode | Expected w(box) | Expected disp at box force_point |
     |------|-----------------|----------------------------------|
     | Tx   | 0               | (1, 0, 0)                        |
     | Ty   | 0               | (0, 1, 0)                        |
     | Tz   | 0               | (0, 0, 1)                        |
     | Rx   | 0               | (0, 0, y_fp − y_ref)             |
     | Ry   | 1               | (0, 0, −(x_fp − x_ref))          |
     | Rz   | 0               | (0, 0, 0)                        |
     All within 1e-10. (Rx zero, Rz zero only hold for a flat planar wing — extend with
     a dihedral fixture once the planar case passes.)
   - Repeat the gate on `val_vlm_rect_ar8.bdf` (no RBARs, unswept; should already pass)
     and a new minimal dihedral case `val_vlm_dihedral.bdf` (to be added) to ensure the
     swept-and-dihedral kinematics work, not just the swept-planar case.

  **Order of operations & expected per-step measurements:**
   1. Land B1 first. Run the HA144A check script — bug 1 still present, so wing
      incidence still wildly wrong, BUT the displacement vector now shows RBAR slaves
      moving with masters. Validates B1 in isolation.
   2. Land B2. Re-run — wing incidence now uniform `+1.0e-3` under the rigid-pitch
      probe. The script's "rigid pitch" check passes.
   3. Land B3. The original broken SET1 (preserved as a regression fixture) now raises
      ValueError instead of silently corrupting Q_aa.
   4. Land B4. V-AE1b passes on HA144A, val_vlm_rect_ar8, and val_vlm_dihedral.
   5. Step B is closed. Move to Step C (Q_aa rigid-body null-space gate); B is its
      prerequisite. With B closed, the trim solver should reproduce V-AE1d to first
      order; the elastic increment q=40 → q=1200 (defect-2-class effects) is then the
      next residual to chase.

  **Risks / open questions:**
   - DTHX=1 with the EA-only SET1 means the Rx (torsion) DOF of GRIDs 100/110/120
     drives wing-box incidence directly. Verify that the wing CBARs (running 100→110→120
     with z-orientation (0,0,1)) carry torsional stiffness J = 0.462963 (PBAR 101). They
     do, so torsion mode is structurally represented.
   - With the slave grids no longer in SET1, the spline cannot "see" any LE/TE
     differential motion. Physically there is none for a chordwise-rigid section, which
     the RBAR enforces — so this is consistent. Confirm no test relies on the broken
     SET1 (none should after V-AE2 is updated to use the FIXED fixture).
   - V-AE2 (the legacy along-spline-axis test) becomes redundant once V-AE1b passes,
     but does no harm; leave it as a unit-level check on the Hermite slope projection.

  **Step B next action:** implement B1 (RBAR expansion), then B2 (SET1 fix), in that
  order — B1 is mechanically smaller and unblocks all downstream gates regardless of
  the spline geometry; B2 then exposes the real V-AE1b residual.

  **Step C — `Q_aa` rigid-body null-space gate (NEW).** Replace
  V-AE2b's along-spline-axis kinematic with a *global* basic-frame rigid-body sweep:
  for each of the 6 basic rigid-body modes (Tx, Ty, Tz, Rx, Ry, Rz) applied to *all*
  grids in a swept-spline SET1, assert (i) `g_slope·u_rb` equals the analytically known
  incidence field (uniform = Ry for global pitch, etc.) and (ii) `g_disp·u_rb` evaluated
  at every box force_point equals the kinematic displacement of that point under `u_rb`.
  The current V-AE2b passes by construction because the input field is pre-projected
  onto the spline parameter — that is not the test that catches AE1's residual.

  **Step C — `Q_aa` rigid-body null-space gate (NEW).** With `g_slope`/`g_disp` from
  Step B fixed, assert `Q_aa · u_rb ≈ 0` (Tz and Ry global rigid-body) to machine
  precision when the model is fully unconstrained, or that the residual matches an
  exact rigid-body ghost-force pattern when SPC is applied. `Q_aa` losing its rigid-body
  null space is the *defining* symptom of defect 1; this gate must pass before
  `K_eff = K_aa − q·Q_aa` carries any physical meaning.

  **Step D — Parity audit in the trim balance (NEW, ties into Step A).** Trace one
  unit `Cp` on a wing box through `skj·Cp → g_disp^T·f_box → SUPORT row of f_rhs_r`.
  Compare that path against `solve_rigid_cl` applied to the same Cp distribution and
  reference point. They must agree numerically *including* the symmetry factor.
  Establish a single rule: either (a) `skj` carries the parity multiplier so all
  downstream paths see whole-airplane forces, or (b) inertial / weight inputs are halved
  on symmetric-half models. Document the choice in `aero/integration.py` and
  `aero/aero_model.py`; assert at trim entry.

  **Step E — Moment-sign reconciliation (couples to AE8).** Adopt the rigid solver's
  sign convention (nose-up positive Cm about RCSID) throughout the trim chain: the
  Schur r-set row for any Ry SUPORT DOF, `_compute_aero_forces.My`,
  `_compute_rigid_derivs.CMY`, and the f06 STABILITY DERIVATIVES block must all use the
  same sign. Single-source the moment-arm formula `(x_ctrl − x_ref)·F_z` with the agreed
  sign in one helper.

  **Step F — Re-enable `K_eff` and verify V-AE1 elastic gate.** With A–E green, restore
  the `Q_aa ≠ 0` path. SC1 and SC2 ANGLEA/ELEV must match Listing 7-2 to ≤ 1 % and the
  q=40 → q=1200 ratio must reproduce the documented 27 % restrained-CZα flexible
  increment (defects 1 and 2 each independently break this ratio even when point values
  happen to match at one q).

  **Step G — Analytic restrained derivatives (closes AE8).** Replace
  `_compute_restrained_derivs` finite-difference path with the analytic derivative from
  the Schur factorisation: `∂u_l/∂δ_free = K_ll^{−1}·C_ax_l`, then build the derivative
  columns from `D_jx + D_jk·G_slope·∂u/∂δ`. Acceptance: HA144A Table 7-1 restrained
  columns (CZα, Cmα, Cmq, …) within 1 %; rigid columns unchanged.

**Acceptance — V-AE1 gate (expanded; replaces the current `test_ae1_keff_trim.py`
tolerances once each step lands):**

  - **V-AE1a** (Step A) — Rigid trim (Q_aa=0): SC1 ANGLEA, ELEV, total lift within 1 %
    of NASTRAN's rigid-case column.
  - **V-AE1b** (Steps B, C) — `Q_aa·u_rb`/`g_slope·u_rb`/`g_disp·u_rb` rigid-body null-
    space residuals < 1e-10 on HA144A, val_vlm_rect_ar8, and one out-of-plane (dihedral)
    case added with this gate.
  - **V-AE1c** (Step D) — Parity audit: skj-path SUPORT-row force equals
    `solve_rigid_cl` lift to 1e-6 for one unit-Cp injection.
  - **V-AE1d** (Step F) — Elastic trim: SC1 ANGLEA=+0.169191, ELEV=+0.492457; SC2
    ANGLEA=+0.001373, ELEV=+0.019325; total lift = +8 000 lb; all within 1 %.
  - **V-AE1e** (Steps F, G) — Restrained derivative columns (CZα, Cmα, Cmq) at q=40
    and q=1200 within 1 % of Table 7-1; documented 27 % restrained-CZα flexible
    increment reproduced to ≤ 5 % relative error.

**Notes on what *not* to do**

  - Do not pursue tighter tolerances on `test_ae1_keff_trim.py` until V-AE1a passes —
    the current `ATOL_ANGLEA=1e-3, ATOL_ELEV=5e-3` failing is consistent with a wrong
    matrix, not a noisy one, so tightening tolerances will not surface the root cause.
  - Do not re-tune the HA144A bulk model (NSPAN/NCHORD, spline DTOR, RCSID) to fit
    V-AE1; AE3 already established that rigid CLα reproduces NASTRAN to 4 sig fig at
    the same mesh, so model parameters are not the dial.
  - Do not delete the existing `K_eff = K_aa − q·Q_aa` line — it is correct and needed;
    AE1 is now about *what feeds into it*, not the line itself.

---


### [MAJOR] AE8 — Stability-derivative formulation internally inconsistent and incomplete

**Files:** `sbeam/solver/sol144.py:482–637`

```
[MAJOR] Restrained derivatives perturb via K_ll⁻¹ (no aero feedback in the re-solve) but
        evaluate forces INCLUDING w_struct — a one-pass hybrid converging to neither
        NASTRAN's restrained nor unrestrained columns. No unrestrained (mean-axis) set
        exists. Moment convention (+ΣFz·(x−xref)) is opposite in sign to both
        solve_rigid_cl.CM and NASTRAN Cm.
FIX:    After AE1, restrained derivatives come out of the K_eff solve analytically — delete
        the finite-difference machinery. Add the unrestrained set (mean-axis, ZAERO Eq.
        12.14/12.15) and align the sign convention with the f06 reference (Cz = −CL,
        nose-up-positive Cm about RCSID). Acceptance: HA144A Table 7-1 columns.
```

---

### [MAJOR] AE9 — Mach is a property of the model, not the flight condition

**Files:** `sbeam/aero/aero_model.py:77`, `sbeam/model/aero.py` (Aeros.mach), `sbeam/solver/sol144.py:673`

```
[MAJOR] The AIC is built once from AEROS.mach (an sbeam extension field) while TRIM.mach is
        parsed and silently ignored. Two subcases at different Mach — standard SOL 144 usage
        (HA144A's own third subcase is M=1.3) — are impossible, and a mismatch is not even
        warned about.
FIX:    Build (and cache) the AIC per TRIM Mach; retire the AEROS.mach extension field;
        warn/error on AEROS-vs-TRIM Mach disagreement during the transition.
```

---

### [MAJOR] AE10 — `parity` not wired from AEROS.SYMXZ; SOL 144 unreachable from main

**Files:** `sbeam/aero/aero_model.py:44`, `sbeam/main.py`, `sbeam/parser/case_control.py`

```
[MAJOR] Every caller passes parity manually; nothing reads AEROS.symxz, so a wrong-parity
        solve is silent. run_sol144_trim has no caller at all — the HA144A deck cannot run
        end-to-end (overlaps A5 / Step 56, but the symxz wiring is independent and one line).
FIX:    Default parity = aeros.symxz inside build_aero_model (explicit argument overrides);
        wire SOL 144 dispatch in main.py as part of Step 56.
```

---

### [MINOR] AE11 — D_jx YAW column duplicates ROLL; AESURF hinge geometry ignored

**Files:** `sbeam/aero/integration.py:122–125, 130–143`, `sbeam/model/aero.py` (Aesurf.cid1)

```
[MINOR] YAW uses −(2/bref)·y_ctrl (same as ROLL); yaw rate on a vertical fin produces
        sidewash ∝ (x − x_ref), not ∝ y. AESURF cid1 is parsed but the control downwash is
        just −n_z·eff — no hinge-sweep projection, no rotation for non-spanwise hinges, no
        hinge-moment output (NASTRAN prints hinge-moment derivatives for HA144A — free
        validation data going unused).
FIX:    Derive the control column from rotation about the actual hinge axis (cid1 y-axis);
        add hinge-moment recovery; correct the YAW column for vertical surfaces.
```

---

### [MINOR] AE12 — PG compression keeps original normals; SPLINE2 DTOR/DTHZ silently ignored

**Files:** `sbeam/aero/vlm.py:144–156`, `sbeam/aero/spline.py`, `sbeam/parser/bdf_reader.py`

```
[MINOR] prandtl_glauert_boxes scales y,z but copies the un-recomputed normal — exact only
        for planar surfaces; wrong for dihedral/out-of-plane panels (assert or document
        planarity). Spline2.dtor and dthz are parsed but unused — silently accepting and
        ignoring NASTRAN card fields is how the AE4(c) DTHX misinterpretation went unnoticed.
FIX:    Recompute (or validate) normals under PG compression; warn when DTOR/DTHZ carry
        non-default values that will be ignored.
```

---

### [MINOR] AE13 — Validation gap: suite is green with AE1–AE6 present; no swept/coupled/benchmark gates

**Files:** `tests/aero/`, `tests/integration/`, `sample/ha144a_sbeam.bdf`

```
[MINOR] 207 tests pass with every defect above present. Every geometric validation case is
        unswept and uncoupled; the V-B1/V-B3 rigid-body gates never exercised a swept spline
        axis or fore/aft offset grids; no dimensional-consistency check ties the coupled
        force path back to the rigid solver.
FIX:    Add three permanent gates:
        (V-AE1) HA144A acceptance test — assert SC1 ANGLEA=+0.169191, ELEV=+0.492457 and
                SC2 ANGLEA=+0.001373, ELEV=+0.019325 (loose tolerance first, tighten as
                fixes land); assert trim lift = +8 000 lb; optionally Table 7-1 derivative
                columns (rigid CZα −5.071, Cmα −2.871; restrained q=1200 CZα −6.463).
        (V-AE2) ~~Swept-spline rigid-body gate~~ **IMPLEMENTED** — 3 tests in
                `tests/aero/test_spline.py::TestSweptSplineRigidBody` (plunge=0, beam pitch
                =θ, g_disp at force_point). All pass to 1e-12.
        (V-AE3) Unit-consistency gate — g_disp.T @ skj-path total force/moment equals the
                Kutta-Joukowski resultants from solve_rigid_cl on the same model.
```

---

### Correction plan — recommended fix order

Each step is independently verifiable against a number already measured
(`studies/_review_ha144a_check.py`):

1. ~~**AE3** (lift-width projection)~~ **RESOLVED** — rigid CLα = 5.0709 vs NASTRAN 5.07097 ✓
2. ~~**AE2** (j-set unit Γ vs Cp)~~ **RESOLVED** — skj-path CZα = 5.071 matches rigid solver ✓
3. ~~**AE4 + AE6**~~ **RESOLVED** — swept-spline kinematics reworked (ZAERO §6.3), DTHX semantics fixed, g_disp evaluated at ¼-chord force point; V-AE2 gate passes (711 tests ✓).
4. ~~**AE5 + AE7**~~ **RESOLVED** — RCSID-frame URDD transform + inertial trim columns (`_build_inertial_cols`); 10/10 tests pass, trim lift = +8 000 lb ✓
5. **AE1** — Step A (parity + My sign) **APPLIED (2026-06-12)**; SC1 lift ✓, rigid
   CZα ✓. Step B (g_slope off-axis node incidence error) **BLOCKED** — RBAR slave-DOF
   expansion hypothesis unresolved; see AE1 entry above. Steps C–G remain open. Closing
   AE1 requires resolving Step B before any further matrix work.
6. **AE8–AE10** (derivatives, per-TRIM Mach, wiring) — partially overlap AE1 Steps E and G
   (moment sign, analytic restrained derivs); finish with AE9 per-TRIM Mach and AE10
   parity/CLI wiring. Then close with the V-AE1/2/3 gates as permanent regression tests.

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
work: **A7** (cosine chordwise spacing helper + low-NCHORD warning), **A8** (box
aspect-ratio pre-solve warning), and from the 2026-06-11 review: **AE9** (per-TRIM Mach),
**AE12** (PG normals).

---

## Phase B — Structure ↔ Aero Splining

Steps 45–49. Goal: two CID-aware spline operators — `g_slope` (n_box × n_g) mapping
structural DOFs → per-box streamwise incidence for the VLM solve, and `g_disp` (3n_box × n_g)
mapping structural DOFs → per-box 3-D displacement for virtual-work force transfer.
These feed directly into `coupling.build_qaa` and `coupling.build_fg`.
Prerequisite for Phase C (SOL 144).

**Steps 45, 46, 47, and 49 are complete.** Step 48 (SPLINE1) is deferred. See `docs/40_history/00_completed_development.md`.

**⚠ 2026-06-11 review:** the SPLINE2 operators fail rigid-body kinematics on swept/offset
configurations (**AE4**: sweep projection, Hermite slope sign, DTHX semantics) and apply
forces at the ¾-chord collocation point (**AE6**). Both must be fixed before any Phase C
result can be trusted on a swept surface.

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

**Status (2026-06-11):** a determined-case trim solver (`run_sol144_trim`, Schur-complement
partition over SUPORT DOFs) exists on the `aeroelastics` branch. Resolved defects: **AE2**
(Γ/Cp units), ~~**AE5**~~ (URDD RCSID frame — RESOLVED), **AE6** (¾-chord moment arms),
~~**AE7**~~ (inertial trim columns — RESOLVED), **AE8** (derivative formulation). Open:
**AE1** (no `q·Q_aa` feedback in the solve). The over-determined case and rate-aero columns
below remain unimplemented. Treat the AE correction plan as the prerequisite for closing this
step.

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
| OP2 results export (pyNastran) | Write an OP2 alongside the f06 using pyNastran's vectorized OP2 writer (displacements, eigenvectors, CBAR forces/stresses; later SOL 144 box pressures/forces). Unlocks pyNastranGUI as an external post-processor — stress fringe plots, animated mode shapes, force/bending-moment diagrams, section cuts, CAERO1 panel + spline display — and makes sbeam results readable by any OP2-consuming tool. pyNastran (BSD-3) as an optional/extra dependency; its OP2 *writing* object model is thinly documented — prototype from the pyNastran test suite first. Acceptance: pyNastran round-trips the written OP2 and values match the f06; pyNastranGUI loads and renders a SOL 101 and SOL 103 result | SOL 101/103 complete |
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
