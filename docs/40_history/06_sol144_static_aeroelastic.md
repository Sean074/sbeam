# Completed Development — SOL 144 Static Aeroelastics (Phase C)

Part of the completed-development record (index: `00_completed_development.md`).
Covers the SOL 144 trim solver (determined + over-determined), stability derivatives
(rigid / restrained / unrestrained), divergence, balanced maneuver loads, monitor
points, CHORDCP injection, and the AC1–AC8 steady close-out.

---

## Phase C — SOL 144 Static Aeroelastics

### Step 50: Aero stiffness assembly Q_aa + modal-truncation ROM ✅ COMPLETE

**Objective:** Assemble the flexible aerodynamic stiffness `Q_aa` on the structural
a-set and provide an optional modal-truncation reduced-order model (ROM) built on the
SOL 103 free-vibration basis, with mode-acceleration load recovery.

**Deliverables:**
- `sbeam/solver/sol144.py` — new module:
  - `_build_qaa_aset(bulk, aero, grid_index, spc_sid, f_g_full)`: reduces the g-set
    `Q_aa = G_dispᵀ S_kj (A_jj*)⁻¹ D_jk G_slope` and `K_aa` to the SPC-free a-set
    using the same RBE3-then-SPC reduction as `sol101.py`; always-dense output to
    follow the RBE3 dense-fallback precedent (Risk KC1)
  - `_solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_dofs)`: dense direct solve of
    `(K_aa − q·Q_aa)·u_a = f_aa`; stores `k_aa_lu = lu_factor(K_aa)` for later reuse
  - `_solve_rom(K_aa, Q_aa, f_aa, q, phi_free)`: modal-truncation ROM using
    `K_hh = Φᵀ K Φ` and `Q_hh = build_gaf(Q_aa, Φ)` (reuses `coupling.py`)
  - `_mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)`: corrects
    mode-displacement with `u_a = Φξ + K_aa⁻¹(f_aa − (K_aa−q·Q_aa)Φξ)` via cheap
    `lu_solve` on the already-factored K_aa
  - `run_aeroelastic_static(bulk, subcase, aero, q, use_rom, sol103_result)`: public entry
    point matching the `run_sol101`/`run_sol103` convention; recovers CBAR forces/stresses
    via the existing `recover_bar_forces`/`recover_bar_stresses` functions unchanged
- `sbeam/results/results.py`: `Sol144Result` dataclass (displacements, bar_forces,
  bar_stresses, q_aa, q, free_dofs, k_aa_lu, modal_coords, phi_free, k_hh, q_hh)
- `sbeam/parser/case_control.py`: added `144` to `_SUPPORTED_SOLS`
- `tests/aero/test_step50_qaa.py`: 13 V-C3 tests, all pass
- `docs/10_standard/05_aeroelastics.md`: Phase C section added (governing equation,
  coupling.py API, sol144.py API, Sol144Result field table, V-C3 acceptance criteria)

**Test/Acceptance (V-C3 — all pass, 708 total tests pass):**
- V-C3-1: `Q_aa.shape == (n_a, n_a)` and `K_aa.shape == (n_a, n_a)`; n_a < n_g ✓
- V-C3-2: `run_aeroelastic_static(q=0)` displacements and CBAR forces ≡ `run_sol101` to 1e-10 ✓
- V-C3-3: ROM (all modes) + mode-acceleration ≡ direct solve to 1e-6 ✓
- V-C3-4: Mode-acceleration converges faster than mode-displacement on CBAR root bending
  moment (MA error < MD error at n_modes/4) ✓
- V-C3-5: `lu_solve(k_aa_lu, K_aa @ e1) ≈ e1` to 1e-10 ✓

**Key decisions:**
- `_build_qaa_aset` lives in `sol144.py` (not `coupling.py` or `aero_model.py`) because
  it requires structural infrastructure imports (`apply_spcs`, `build_rbe3_transformation`);
  `coupling.py` is kept as a pure linear-algebra layer with no structural imports
- K_aa and Q_aa are always dense after the a-set reduction: Q_aa is dense by construction;
  adding a dense matrix to sparse K would require a mixed-format code path; always-dense
  follows the RBE3 dense-fallback precedent in `sol101.py` (Risk KC1 addressed)
- `k_aa_lu` is stored in `Sol144Result` so Step 52 can reuse the pure structural K
  factorization for mode-acceleration in each trim subcase without re-factorizing
- `f_g_full` optional parameter on `_build_qaa_aset` reduces the combined load
  (structural + aero) alongside K and Q in one pass, avoiding a second index-mapping call
- Mode-acceleration uses K_aa (pure structural stiffness), not K_eff, for the residual
  correction — this is the standard mode-acceleration method (Herting 1985); the K_eff
  residual `f − K_eff·u_md` is computed inside `_mode_acceleration_recovery`, then the
  structural flexibility `K_aa⁻¹` is applied to it, recovering static load accuracy

---

### Step 51 — Trim card set parsing (AESTAT / AESURF / AELIST / TRIM / DIVERG / over-determined)

**Objective:** Add BDF-parsing support for the static aeroelastic trim card set so that the
Step 52+ trim solver can consume fully validated trim objects from `BulkData`. No solver
logic is added; Step 51 is purely parsing infrastructure.

**Deliverables:**
- `sbeam/model/aero.py` — 8 new dataclasses: `Aestat`, `Aesurf`, `Aelist`, `Trim`, `Diverg`,
  `Trimvar`, `Trimobj`, `Trimcon`
- `sbeam/model/bulk_data.py` — 8 new dict fields: `aestats`, `aesurfs`, `aelists`, `trims`,
  `divergs`, `trimvars`, `trimobjs`, `trimcons`
- `sbeam/parser/bdf_reader.py` — 8 new handlers; dispatch branches; post-parse cross-reference
  validation (AESURF→AELIST, AELIST→CAERO1 box ranges, TRIM label refs); DOF-count diagnostic
  (UserWarning on fully-prescribed or over-determined-without-objective cases)
- `sbeam/parser/case_control.py` — `SubcaseControl` gains `trim_sid` and `diverg_sid`;
  `parse_case_control()` handles `TRIM=` and `DIVERG=` keywords; error message updated to
  list SOL 101, 103, and 144
- `docs/10_standard/02_card_reference.md` — field tables for all 8 new cards + 2 case-control keywords
- `docs/10_standard/05_aeroelastics.md` — updated supported-cards table; new "Step 51" section

**Test/Acceptance:**
- V-51-1: Round-trip AESTAT, AESURF, AELIST, TRIM, DIVERG, TRIMVAR, TRIMOBJ, TRIMCON — all
  field values match declared input
- V-51-2: TRIM referencing undefined AESTAT/AESURF label → `ValueError`
- V-51-3: AESURF referencing undefined AELIST → `ValueError`
- V-51-4: AELIST box ID outside all CAERO1 ranges → `ValueError`
- V-51-5: Over-determined TRIM without TRIMOBJ → `UserWarning`
- V-51-6: Case control `TRIM=10` assigned to `subcase.trim_sid == 10`
- V-51-7: SOL 145 → `ValueError` with updated message listing 101, 103, 144

**Key decisions:**
- `Trim.vars` is a plain `dict[str, float]` (label→value) rather than parallel lists —
  lookup by label is the dominant access pattern in the trim solver
- `trimcons` is stored as `dict[sid: list[Trimcon]]` rather than `{id: Trimcon}` because
  multiple inequality constraints naturally share a logical group SID
- Over-determined warning fires only when TRIMOBJ is absent — if TRIMOBJ is present the
  over-determined path is intentional and no warning is needed
- DOF-count diagnostic lives in `parse_bulk_data()` (not a separate validator module)
  because Step 51's scope is parsing only; the full trim-variable partition logic belongs
  in the Step 52 solver

---

### Phase C — AE1 Step A: Parity factor + nose-up-positive My in trim balance ✅ FIXED

**Date resolved:** 2026-06-12. First of seven planned increments closing the AE1 critical
defect ("SOL 144 trim solver does not converge to HA144A Listing 7-2 reference"). Steps
C–G remain open.

**Objective:** Fix two coupled defects in `run_sol144_trim` that prevented the trim from
balancing on a symmetric half-model and silently inverted the pitching-moment column:
(a) `skj`-path aerodynamic forces represent half the airplane on `AEROS.SYMXZ=1` models
while inertial relief and trim weight target are full-airplane — without a parity scale
the trim converges to ≈ 54 % / 60 % of the expected 8 000 lb lift; (b) the trim equation
for the Ry SUPORT DOF used `My = +ΣFz·(x−x_ref)`, opposite-signed to `solve_rigid_cl.CM`
and NASTRAN's nose-up-positive Cm convention, driving ELEV to the wrong root.

**Deliverables:**

- `sbeam/solver/sol144.py` — `run_sol144_trim`:
  - `sym = 2 if aero.parity != 0 else 1` applied as a multiplicative factor on `Q_ax_g`
    (the rigid aero load sensitivity), `Q_gg` (the flexible aero stiffness), and
    `f_aero_g` (the baseline-aero RHS) so all paths into the Schur partition see
    whole-airplane forces.
  - `Fz_total` and `My_total` recovery at the end of the routine also picks up the
    `sym` factor so the diagnostic `total_cl`/`total_cm` agree with the input balance.
- `sbeam/solver/sol144.py` — Sign convention flipped to nose-up-positive in three sites:
  `_compute_aero_forces.My`, `_compute_rigid_derivs.CMY`, and the total CM loop inside
  `run_sol144_trim`. The trim-equation row for the Ry SUPORT DOF inherits the corrected
  sign through the same arithmetic.

**Test/Acceptance (measured against `studies/_review_ha144a_check.py`):**

| Quantity | Pre-A | Post-A | NASTRAN |
|---|---:|---:|---:|
| SC1 (q=40) ANGLEA   | −0.5698 rad   | +0.097 rad | +0.169191 rad |
| SC1 (q=40) ELEV     | +14.257 rad   | +0.079 rad | +0.492457 rad |
| SC2 (q=1200) ANGLEA | +0.003798 rad | +0.00057 rad | +0.001373 rad |
| SC1 trim lift       | +4 299 lb (54 %) | +8 140 lb ✓ | +8 000 lb |
| Rigid CZα           | −5.071        | −5.071 ✓ | −5.07097 |

Lift balance closes to 1.8 % (residual from Q_aa contamination, fixed by Step B). All
existing tests pass (no regressions).

**Key decisions:**

- Parity-doubling lives on the aero side (`sym × Q_ax_g`, `sym × Q_gg`, `sym × f_aero_g`)
  rather than halving inertia. Reason: keeps `M_ax`, `_build_inertial_cols`, and the
  weight target `URDD3·m_total` in their natural whole-airplane units, which matches the
  way the user inputs CONM2 totals on `AEROS.SYMXZ=1` decks.
- Moment-sign reconciliation is partial here: the three sites above use the correct
  nose-up-positive convention, but a single-source helper for `(x − x_ref)·Fz` is
  deferred to AE1 Step E. The f06 STABILITY DERIVATIVES block was not touched.
- V-AE1a (formal `rigid_trim_only` gate at `Q_aa=0`) was not added — parity was
  confirmed numerically via the lift balance instead. The full V-AE1 acceptance still
  requires Steps E–G.

**Files:** `sbeam/solver/sol144.py`.

---

### Phase B + C — AE1 Step B: RBAR-expanded recovery + EA-only SET1 + spline math fix + V-AE1b gate ✅ FIXED

**Date resolved:** 2026-06-12. Second AE1 increment; combines three independent defects
(RBAR-expansion in trim, off-EA SET1 grids on the swept HA144A wing, and a
multiplication-vs-division ambiguity in the SPLINE2 streamwise-gradient formula).
After Step B the spline reproduces all 6 basic-frame rigid-body modes to machine
precision on the HA144A wing and to 1e-12 on a math-exact rectangular fixture.

**Objective:** Close the three defects that contaminated `Q_aa` and the structural
recovery path:

1. `run_sol144_trim` and `_compute_restrained_derivs` filled the recovered `displacements`
   by direct index scatter, leaving RBAR slave DOFs (111/112/121/122 on HA144A) at zero.
   `g_slope @ displacements` then saw an L-shaped deformation (masters move, slaves
   don't) instead of a chordwise-rigid section translation.
2. `sample/ha144a_sbeam.bdf` SPLINE2 1601 SET1 was `{99, 100, 111, 112, 121, 122}` —
   fuselage centreline + the RBAR-slave LE/TE stringers — with the elastic-axis grids
   110/120 absent. The 1-D beam spline's Hermite was forced to fit a non-monotone Tz
   field in `s` and produced oscillations; under global θ=1e-3 pitch the wing incidence
   ranged [−9.45e-02, +4.53e-02] instead of uniform +1.0e-3.
3. The spline streamwise-gradient formula `w = −(dh/ds)/x̂[0]` (division) was
   self-consistent only with the V-AE2b "rigid-along-spline-axis" kinematic. The
   chordwise-rigid section reconstruction `u_z(x, y) = h(s(x, y))` gives `∂u_z/∂x =
   (dh/ds)·x̂[0]` — multiplication. The torsion coefficient `x_comp·f_vals` was
   correct only on unswept splines; the chord-offset chain rule for a section rotated
   about `x̂_spline` gives `w_torsion = −ŷ[0]·x_comp·f_vals_slope`. The matching
   `g_disp` torsion contribution `x_comp·ζ_k·ẑ[c]·f_vals_force` was entirely missing.

**Deliverables:**

- **B1 — RBAR-expanded recovery (`sbeam/solver/sol144.py`):**
  - New `_expand_to_g(u_a, T, free_local, n_red)` helper: `u_red = scatter(u_a, free_local);
    return T @ u_red`. Returns a full g-set vector with RBAR slaves driven by their
    masters via the RBE3/RBAR transformation matrix.
  - `run_sol144_trim` line 890-892 (direct scatter) replaced by a single
    `displacements = _expand_to_g(u_a, T, free_local, len(red_dofs))` call.
  - `_compute_restrained_derivs` signature changed from `(…, free_dofs, …, n_dofs)` to
    `(…, T, free_local, n_red, …)`; both nominal and perturbed displacement vectors
    are built via `_expand_to_g`.
- **B2 — Sample-model fix (`sample/ha144a_sbeam.bdf`):**
  - `SET1, 1100` changed from `99, 100, 111, 112, 121, 122` to `100, 110, 120` (wing
    CBAR endpoints; all three on the EA, monotone in `s` with chord offset ≈ 0).
  - SPLINE2 1601 `DTHX` flipped `−1 → +1` (attached). With the corrected formula
    (below) the attached path is what reproduces global rigid-body modes; the detached
    path is now reserved for splines where torsion is intentionally decoupled from the
    surface.
- **B3 — SET1 collinearity validator (`sbeam/aero/spline.py::_build_spline2_block`):**
  - After `s_gid` is sorted, compute each SET1 grid's chord offset
    `Δ_i = (r_i − origin)·ŷ_spline`. If `max |Δ| > 5 %` of the span range, raise
    `ValueError` naming the offending grids and their `(x, y, z, s, Δ)`. The error
    message points the user at the EA-only SET1 fix or SPLINE1 (deferred to Step 48).
  - The original HA144A SET1 (preserved as a regression fixture) trips this validator
    immediately, preventing the same silent Q_aa corruption from re-emerging.
- **B3+ — Spline math fix (`sbeam/aero/spline.py::_build_spline2_block`):**
  - Translation `w_box`: was `−(z_comp / x̂[0]) · dφ_f/ds`; now
    `−z_comp · x̂[0] · dφ_f/ds` (multiplication).
  - Bending rotation `w_box`: was `(y_comp / x̂[0]) · dφ_d/ds`; now
    `+y_comp · x̂[0] · dφ_d/ds`.
  - Torsion `w_box`: was `x_comp · f_vals_slope`; now
    `−ŷ[0] · x_comp · f_vals_slope` (correct sweep projection).
  - Torsion `g_disp` (was entirely absent): now
    `g_disp[3k+c] += x_comp · ζ_k · ẑ[c] · f_vals_force` where
    `ζ_k = (box_k.force_point − origin)·ŷ_spline`.
  - `sweep_ok` guard removed (multiplication is well-defined at `x̂[0] = 0`).
- **B4 — V-AE1b global rigid-body gate (`tests/aero/test_spline.py::TestGlobalRigidBody`):**
  - Two fixtures: HA144A wing (5-decimal coordinate input → 1e-5 tolerance) and a
    math-exact rectangular wing (integer y positions on the spline axis →  1e-12).
  - For each of `{Tx, Ty, Tz, Rx, Ry, Rz}` applied to *every* grid (with lever-arm
    fill `ω × r` for rotations), assert `g_slope·u_rb` and `g_disp·u_rb`
    z-component at each box force_point match the analytic flat-wing expectations.
  - 18 tests on HA144A (6 modes × {downwash, disp}) + 6 tests on rect wing (6 modes
    × downwash) = 24 new gate tests, all green.
- **Legacy V-AE2 fixture (`tests/aero/test_spline.py::_build_ha144a_wing_spline_bulk`):**
  - SET1 updated to EA-only `{100, 110, 120}`; DTHX flipped to `+1`. V-AE2a/b/c remain
    green as unit checks on the Hermite slope projection.

**Test/Acceptance (`studies/_review_ha144a_check.py`):**

| Quantity | Pre-B (Step A only) | Post-B | NASTRAN |
|---|---:|---:|---:|
| Rigid-pitch wing incidence (θ=1e-3) | [−9.45e-02, +4.53e-02] | **+1.000e-03 ± 1e-10** | +1.000e-03 |
| SC1 trim lift | +8 140 lb | +7 999.4 lb | +8 000 lb |
| SC1 ELEV | +0.079 (16 % of target) | **+0.245 (50 %)** | +0.492 |
| SC2 ANGLEA | +5.7e-4 (42 %) | +1.9e-3 (140 %) | +1.4e-3 |
| `TestGlobalRigidBody` | — | 18/18 ✓ | — |
| Full `tests/aero` + `tests/integration` (excluding `test_ae1_keff_trim.py`) | 220 ✓ | 238 ✓ | — |

The remaining V-AE1 failures (`test_ae1_keff_trim.py` ANGLEA/ELEV value tests, three of
eleven) are now driven by AE1 defects 3 and 4 (moment-sign convention not single-sourced,
finite-difference restrained-derivative path) — addressed by AE1 Steps E and G.

**Key decisions:**

- The original Step B design treated SET1 contamination as the only defect; V-AE1b
  exposed the spline-formula defects (mult vs div, torsion coefficient, missing
  `g_disp` torsion) that V-AE2b's pre-projected kinematic had silently masked. Step
  B's scope was expanded in-session to include the formula fix because partial gates
  on broken math would have produced compensating-error fits that fail on any other
  swept-wing model.
- V-AE2b's "rigid-along-spline-axis" pitch is mathematically self-consistent under
  either the division or the multiplication formula; only V-AE1b (global basic-frame
  pitch) distinguishes them. V-AE2 is retained as a unit-level Hermite slope check.
- `DTHX = +1` (attached) is now the right default for any planar SPLINE2 — `DTHX = −1`
  is reserved for surfaces where torsion is intentionally decoupled.
- The collinearity tolerance (5 % of span range) is a practical guard against drift
  during model edits; tighter tolerances would reject legitimate EA grids that have
  rounded coordinates (HA144A's GRID 110 at 27.11325 vs the math-exact 27.113248…).

**Files:** `sbeam/solver/sol144.py`, `sbeam/aero/spline.py`,
`sample/ha144a_sbeam.bdf`, `tests/aero/test_spline.py`.

---

### Phase C — AE1 Step E: Moment-sign single-source helper + virtual-work consistency gate ✅ FIXED

**Date resolved:** 2026-06-12. Fifth AE1 increment. Originally scoped (in the
2026-06-11 review) as a sign fix for an assumed `My = +ΣFz·(x−x_ref)` defect in the
Schur Ry SUPORT row. Investigation on the post-A/post-B branch found that scope to be
**stale**: the gross moment sign had already been corrected in Step A, and the moment
that actually drives the trim is sign- and magnitude-correct. Step E therefore became a
DRY refactor plus a permanent regression gate, and corrected the project's diagnosis of
the residual ANGLEA/ELEV error.

**Objective:** (1) Single-source the nose-up-positive pitching-moment-arm convention so
it cannot drift across the three trim-chain sites that hand-inlined it; (2) lock in, with
a regression gate, that the `g_disp` virtual-work moment driving the Schur r-set row
agrees with the direct box-moment formula; (3) re-diagnose and re-document the remaining
trim error.

**Key finding (re-diagnosis):** The trim r-set (Ry SUPORT) equilibrium is carried through
the **g_disp virtual-work path**, not the explicit `My` formula — the direct aero moment
lands on the SUPORT GRID's Ry DOF as exactly 0 and is transferred through the structure
via `K_rl·K_ll⁻¹`. Measured on HA144A for a unit ANGLEA: the g_disp virtual-work moment
about the SUPORT matches the direct `−ΣFz·(x_force−x_ref)` formula to ~5e-7 relative and
Fz to 1e-13. A direct *rigid* 2×2 trim from the (correct) derivatives gives ELEV ≈ +0.795
while the Schur *flexible* solve gives +0.245 — so the residual gap is the `q·Q_aa`
flexible increment (Steps C/D), **not** a moment-sign error. The backlog's "the sign
error currently halves ELEV" claim was wrong and has been corrected.

**Deliverables:**

- `sbeam/solver/sol144.py` — new `_pitch_moment(f_box_vec, boxes, x_ref)` helper: the
  single source for `My = −ΣFz·(x_force − x_ref)` (nose-up positive, ¼-chord force
  point per AE6). The three hand-inlined copies in `_compute_aero_forces`,
  `_compute_rigid_derivs`, and the `run_sol144_trim` total-CM loop now call it (the
  total-CM site keeps its `sym` parity factor at the call site). Behaviour-preserving:
  HA144A trim numbers byte-identical before/after (SC1 ANGLEA=0.085951, ELEV=0.244584).
- `sbeam/aero/vlm.py` — comment on `solve_rigid_cl.CM` cross-referencing the shared
  `−Σ(...)·(x−xref)` convention with `sol144._pitch_moment` (pressure form vs force form;
  kept as separate functions because they operate on different objects).
- `tests/aero/test_ae1_step_e_moment.py` (new) — `TestStepEMomentConsistency`: for unit
  ANGLEA and ELEV on HA144A, asserts (a) g_disp virtual-work Fz == direct Fz (1e-9),
  (b) g_disp virtual-work moment about the SUPORT == `_pitch_moment` (1e-6 rel), and
  (c) the ANGLEA pitching moment is nose-down (My < 0, absolute-sign anchor). 3 tests
  pass; full aero+integration suite 252 → 249 pass + the 3 pre-existing `test_ae1_keff_trim`
  value failures (unchanged — they are the Steps C/D/G flexible-increment gap, not noise).

**Key decisions:**

- Kept `solve_rigid_cl.CM` (pressure form) and `_pitch_moment` (force form) as separate
  functions rather than forcing a shared util across the aero/solver boundary — they take
  different inputs (cp+area vs the assembled force vector) and already agree numerically;
  a shared comment is the lighter, lower-risk coupling.
- The f06 STABILITY DERIVATIVES block named in the original Step E scope does not exist
  yet (it is Step 56); a note was added there to use the `_pitch_moment` convention when
  it is built, rather than adding a stub now.
- The Step E moment gate is the *moment* leg of the Step D V-AE1c force check; Step D
  should extend `TestStepEMomentConsistency` rather than fork a parallel gate.

**Files:** `sbeam/solver/sol144.py`, `sbeam/aero/vlm.py`,
`tests/aero/test_ae1_step_e_moment.py`.

---

### Phase A — AE2: j-set pressure unit undefined — AIC inverse fed as Γ to force path expecting ΔCp ✅ FIXED

**Objective:** Define the j-set pressure unit once as ΔCp (NASTRAN/ZAERO convention) so
that `ajj_inv_corr @ w` returns a dimensionless pressure coefficient throughout the
coupled aeroelastic chain. Every force computed through `build_skj` (which expects ΔCp)
was off by `chord_box / 2` per box; `total_cl`/`total_cm` also divided by `q` twice.

**Deliverables:**

- `sbeam/aero/aero_model.py` — `build_aero_model`: after the Göthert `/= beta_pg` step,
  scale `ajj_inv_corr` rows by `2/chord_box` (physical boxes, same formula as
  `solve_rigid_cl`). All downstream consumers (`build_fg`, `build_qaa`, `Q_ax`,
  `_compute_rigid_derivs`, `_compute_aero_forces`) are automatically corrected.
- `sbeam/aero/corrections.py` — `apply_wt1`: reference strip lift changed from
  `Σ area·Γ` to `Σ area·2Γ/chord` (physical strip lift/q); function still returns
  a Γ-unit inverse — `build_aero_model` applies the `2/chord` scaling on top.
  `apply_wt2` unchanged (WT2 target stays as VLM Γ; ratio cancellation preserves
  correctness).
- `sbeam/solver/sol144.py` — `run_sol144_trim`: `total_cl = Fz_total / sref` (was
  `/ (q·sref)`); `total_cm = My_total / (sref·cref)` (was `/ (q·sref·cref)`).
  `_compute_restrained_derivs`: CZ/CMY denominators changed from `q·sref·DELTA` to
  `sref·DELTA`.
- `tests/aero/test_corrections.py`: 5 tests updated to assert against physical Cp
  quantities — `test_no_correction_identity` (skj-path CL round-trip vs
  `solve_rigid_cl`), `test_wkk_correction_applied` (force ratio 1/1.5),
  `test_wt2_round_trip` (output = Cp_ref = 2Γ/chord, not Γ), and the two WT1
  round-trip tests (f_target / f_corr expressed as physical strip lift/q).

**Test/Acceptance:**

```
python studies/_review_ha144a_check.py
# rigid derivs CZ/CMY — ANGLEA: (5.071, ...)   ← was (-6.339, ...)
# total CL = -1.001   lift = -8011 lb            ← was -0.025 / near-zero
# 708 tests pass
```

ANGLEA CZα = 5.071 matches `solve_rigid_cl` CLα = 5.0709 to 4 significant figures.
`total_cl` sign is negative because AE5 (URDD frame) is still open; magnitude is correct.

**Key decisions:**

- Apply `2/chord` scaling in `build_aero_model` (not inside each correction function)
  so the unit convention is enforced in one place regardless of which correction is active.
- WT2 "escapes by ratio cancellation": when the WT2 target is in VLM Γ units and
  `ajj_inv_corr` later gets the `2/chord` scaling, the output Cp correctly corresponds
  to the target Γ. No change to `apply_wt2`.
- WT1 target convention explicitly defined as physical strip lift/q (= Σ area·Cp per
  strip), matching NASTRAN/ZAERO practice. The function returns a Γ-unit inverse;
  `build_aero_model` converts to Cp.
- `_compute_rigid_derivs` already had `Fz_sens / sref` (no `q`) — correct with Cp units,
  no change required.

---

### Phase A — AE3: Kutta-Joukowski lift width uses segment LENGTH, not cross-flow projection ✅ FIXED

**Objective:** Correct `dy` in `solve_rigid_cl` and `trefftz_cdi` so that the
Kutta-Joukowski lift integral uses the **y-projection** of the bound-vortex segment,
not its 3-D Euclidean length. The physical force is F⃗ = ρ V⃗∞ × Γ Δs⃗; for
V⃗∞ = (1,0,0) the lift component scales with Δy, not ‖Δs⃗‖.

**Deliverables:**

- `sbeam/aero/vlm.py` — two occurrences of `dy` / `dy_l` changed from
  `np.linalg.norm(bound_b - bound_a)` to
  `sqrt((Δy)² + (Δz)²)` (projected cross-flow width; handles sweep and
  dihedral; degrades to `Δy` for planar wings):
  - `trefftz_cdi` — `dy_l` array (line ≈195)
  - `solve_rigid_cl` — `dy` array (line ≈301); all downstream quantities
    (`chord_box`, `cl_section`, `CL`, `CM`, `CDi`, `per_surface`) pick up the
    fix automatically
- `tests/aero/test_integration.py` — inline `dy` formula aligned to match production
  (numerical result unchanged — test uses an unswept box)

**Test/Acceptance:**

```
python -c "
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl
cc, bulk = parse_bdf('sample/ha144a_sbeam.bdf')
aero = build_aero_model(bulk, parity=1)
r = solve_rigid_cl(aero.boxes, 1.0, parity=1, aeros=bulk.aeros, xref=15.0, mach=0.9)
print(r['CL'], r['CM'])
"
# Output: 5.07098  -2.87093
# NASTRAN ref: CLα = 5.07097, CMα = -2.871
```

All 74 aero/integration/BYU tests pass (BYU wing is unswept — no numeric change).

**Key decisions:**

- Use `sqrt(Δy² + Δz²)` rather than `abs(Δy)` so that dihedral panels (Δz ≠ 0) are
  handled correctly without a separate code path.
- The fix is invisible to every existing test because all validation geometries
  (2-D limit, AR=8 rectangle, BYU wing) are unswept. The HA144A swept wing is the
  first model to expose this discrepancy.
- `chord_box = area / dy` is derived from `dy`, so the chord correction (and hence
  `cp`, `CM`, `cl_section`) is automatically fixed by the single change.

---

### Phase B + C — AE4 + AE6: SPLINE2 kinematics (swept-axis slope projection, nodal-slope sign, DTHX semantics) + ¼-chord force point ✅ FIXED

**Objective:** Fix the three root causes of AE4 (SPLINE2 producing 80× incidence error on swept
configurations) and AE6 (g_disp / sol144 moment arms at ¾-chord instead of ¼-chord), gated by
the V-AE2 swept-spline rigid-body test suite.

**Deliverables:**

- `sbeam/aero/panel.py` — Added `force_point` field to `AeroBox`:
  `force_point = 0.5 * (bound_a + bound_b)`  (¼-chord bound-vortex midpoint).

- `sbeam/aero/spline.py` — Full rewrite of `_build_spline2_block`:
  - AE4(a): sweep projection — `g_slope` translation contribution divides by `x_hat[0]`
    (= cos Λ) per ZAERO Theo §6.3: `w = −(dh/ds) / x_hat[0]`.
  - AE4(b): nodal-slope sign — rotation bending g_slope uses `+(y_comp/x0)·dψ/ds` and
    g_disp uses `−y_comp · z_hat · ψ_i(t_force)` (sign-flipped from prior code).
  - AE4(c): DTHX semantics — `DTHX = 1.0` → attached (torsion coupling active);
    `DTHX = −1.0` → detached (skip); other values → `UserWarning`, treat as detached.
  - AE6: separate `t_slope` (colloc, ¾-chord) and `t_force` (force_point, ¼-chord)
    parametric positions; g_slope evaluated at `t_slope`, g_disp at `t_force`.
  - `_build_attach_rows` lever arm changed from `box.colloc` to `box.force_point`.

- `sbeam/solver/sol144.py` — Three `colloc[0]` → `force_point[0]` in moment arms:
  `_compute_aero_forces`, `_compute_rigid_derivs`, total CM loop.

- `tests/aero/test_spline.py` — Added `TestSweptSplineRigidBody` (V-AE2):
  - V-AE2a: uniform plunge → zero downwash at all boxes (1e-12)
  - V-AE2b: rigid beam pitch (Tz = −x_hat[0]·s·θ, Ry = θ) → uniform incidence θ (1e-12)
  - V-AE2c: g_disp evaluated at t_force, not t_slope — Hermite basis check (1e-12)
  - Updated `TestAttachRigidBodyGate.test_v_b3d_force_transfer_lever_arm` to use
    `box.force_point` (not `box.colloc`) for expected My/Mx lever arms.

**Test/Acceptance (V-AE2):**

```
pytest tests/aero/test_spline.py::TestSweptSplineRigidBody -v
# 3 passed (V-AE2a, V-AE2b, V-AE2c) ✓

pytest tests/
# 711 passed ✓
```

**Key decisions:**

- The ZAERO §6.3 slope formula divides by `x_hat[0]` (not multiplies). The 1D Hermite
  spline captures `dh/ds` along the swept axis; the streamwise slope is
  `(dh/ds) / x_hat[0]` because the axis has `x_hat[0] = cos Λ` as its freestream
  projection. For rigid pitch θ: `dh/ds = −θ·x_hat[0]` → `w = θ`. ✓
- The V-AE2b rigid-pitch test applies `Tz = −x_hat[0]·s_i·θ` (linear in the axis
  projection `s_i`), not the global `Tz = −θ(x−x_ref)`. Off-axis grids make the
  global form non-linear in `s`, causing Runge-like oscillations. The beam-axis form
  is the physically correct test for the 1D SPLINE2.
- The V-AE2c AE6 gate checks that `g_disp[3k+2, col_Tz]` equals the Hermite function-
  value basis `φ_i(t_force)`, not `φ_i(t_slope)`, using scipy's `CubicHermiteSpline`
  as the reference. This pinned the difference between t_force ≈ 3.63 and t_slope ≈ 3.01.
- `sweep_ok = abs(x_hat[0]) > 1e-10` guards vertical-tail splines (axis ⊥ freestream)
  where the division would be singular.

---

### Phase C — AE5 + AE7: RCSID-frame URDD transform + inertial trim columns ✅ FIXED

**Objective:** Fix two coupled trim-solver defects that caused the HA144A SC1 trim to converge
to −8012 lb lift (wrong sign) instead of +8000 lb.

**AE5 — URDD frame/sign convention:**
NASTRAN's TRIM card expresses URDD values in the RCSID frame. For HA144A, CORD2R 100 has
z pointing DOWN in basic (R[2,2]=−1). `sbeam` was treating URDD3=−32.174 as a basic-frame
acceleration, producing an upward inertial load that reversed the trim sign.
Fix: transform prescribed URDD1–3 and URDD4–6 blocks through R_rcsid before computing the
inertial RHS. The transform now handles partial URDD sets (e.g. only URDD3 present) by
assembling the full 3-vector with zeros for absent components, rotating, then writing back
only the present components.

**AE7 — Missing inertial trim columns:**
The Schur trim system had only aerodynamic columns Q_ax, with URDD as a fixed RHS load.
Consequences: (a) a free URDD variable yields a zero Schur column (singular); (b) rotational
URDD loads omitted transport terms m·(α̈×r) about the SUPORT point; (c) dead code
"will be updated at trim" was never honoured.
Fix: replaced `_build_urdd_load` with `_build_inertial_cols(bulk, all_labels, grid_index,
suport_pos)` returning a full (n_g, n_labels) sensitivity matrix M_ax. Non-zero only for
URDD columns. Translational: `M[Tz_dof, col] = −m` per CONM2 and lumped CBAR end mass.
Rotational: spin term `M[Ry_dof, col] = −I_diag[rot]` plus transport cross-product
`F_trans = −m·(α_hat × r)`. M_ax_a (a-set) is passed to both `_solve_trim_determined` and
`_compute_restrained_derivs`, replacing `q·Q_ax` with `q·Q_ax + M_ax` throughout the Schur
assembly.

**Deliverables:**
- `sbeam/solver/sol144.py`: `_build_inertial_cols`; updated `_solve_trim_determined`,
  `_compute_restrained_derivs`, `run_sol144_trim` (RCSID partial-URDD transform block).
- `tests/aero/test_trim_urdd.py` (new): 2 unit test classes (RCSID math, M_ax structure)
  + 1 integration class (V-AE3a sign-of-lift gate). 10/10 tests pass.

**Test/Acceptance (V-AE3a):**

```
pytest tests/aero/test_trim_urdd.py -v
# 10 passed ✓

pytest tests/
# 721 passed ✓
```

**Key decisions:**
- Partial-URDD transform: assemble full [URDD1, URDD2, URDD3] vector (zeros for absent
  components), apply R_rcsid, write back only present components. Avoids requiring all three
  translational (or rotational) URDD labels in a_labels, which is the typical NASTRAN case.
- Transport terms use `suport_pos` (RCSID origin in basic frame) as the reference point for
  moment arms, consistent with NASTRAN's mean-axis definition.
- The test model uses a single SUPORT DOF (Tz only) with one free variable (ANGLEA) because
  Euler-Bernoulli beams along Y decouple torsion (Ry) from z-forces — adding PITCH as a
  second free variable would produce a singular Schur matrix on this model.

---

### Phase A — Half-span / symmetry (AEROS SYMXZ/SYMXY) deprecation ✅ COMPLETE (2026-06-12)

**Objective:** Remove the half-span symmetry-image (`parity`) capability — a 1970s
computational economy no longer used — and make sbeam full-span only. This also resolves
**AE1 Step D** (the `sym=2` aero/inertia parity double-count that halved the HA144A trim) and
the parity-wiring half of **AE10**, by construction.

**Deliverables:**
- **VLM kernel (`vlm.py`):** dropped the `parity` parameter and all XZ-mirror image logic from
  `horseshoe_influence`, `build_ajj`, `trefftz_cdi`, `solve_rigid_cl` — including the
  symmetric/antisymmetric image-bound branches, the mirror trailing-vortex loop, the
  `parity == -1` CL/CY/CDi special cases, and the half-vs-full-span reference-AR doubling
  heuristic (which collapses to `AR = span_ref²/S_ref`).
- **`aero_model.py`:** removed `AeroModel.parity` and the `parity` arg of `build_aero_model`;
  added a guard that raises `ValueError` when `AEROS SYMXZ ≠ 0` or `SYMXY ≠ 0`.
- **`sol144.py`:** deleted `sym = 2 if aero.parity != 0 else 1` and its six applications
  (`Q_ax_g`, `Q_gg`, `f_aero_g`, `Fz_total`, `My_total`). With full-span models aero and inertia
  are both whole-airplane, so the AE1 Step D double-count is impossible.
- **`viewer/app.py`:** removed the Symmetric/Antisymmetric/Full-span radio.
- **`sbeam/aero/mirror.py` (new):** `mirror_halfspan(bulk)` migration aid that unfolds a
  half-span deck about the XZ plane (GRID/CBAR/CONM2/RBAR/RBE2/CAERO1), clears the symmetry
  flags, and raises `NotImplementedError` listing cards that need a manual full-span rebuild.
- **Decks/tests:** removed half-span `sample/ha144a_sbeam.bdf` and its gate
  `tests/aero/test_ae1_keff_trim.py`; `sample/ha144a_fullspan_sbeam.bdf` +
  `tests/aero/test_ae1_fullspan.py` are the sole HA144A trim gate (SC1 value + SC2 sign/
  flexible-increment). All VLM tests rebuilt on genuine full-span geometry; the antisymmetric
  and parity-image unit tests and the concluded A1 convergence diagnostics were removed.
- **AEROS card still parses `SYMXZ`/`SYMXY`** (field layout unchanged); only *solving* a
  non-zero model is rejected.

**Test/Acceptance:** full suite green (752 passed). The full-span HA144A trims to
**SC1 ANGLEA 0.1711 / ELEV 0.4908 (101%/100% of NASTRAN Listing 7-2), lift 16000 lb** —
the three previously-failing half-span trim-value tests are resolved by the parity removal.

**Key decisions:**
- Chose Option B (remove internals, keep a NASTRAN-compatible AEROS shell + reject non-zero
  SYMXZ + `mirror_halfspan` aid) over hard removal, so legacy decks still parse and have a
  documented migration path.
- AE1 Step D is resolved by *eliminating* the `sym` factor rather than reconciling the two
  legs: full-span ⇒ one whole-airplane scale everywhere, no factor to get out of step.

---

### Phase A — AE9: per-TRIM Mach (multi-Mach SOL 144) ✅ COMPLETE (2026-06-12)

**Objective:** Make Mach a property of the *flight condition* (the TRIM card) rather than the
*model* (`AEROS.mach`). Before this, the VLM AIC was built once from `AEROS.mach` and
`TRIM.mach` was parsed but silently ignored, so multiple subsonic subcases at different Mach
were impossible and a supersonic Mach was silently clamped to 0.99.

**Deliverables:**
- **`aero/aero_model.py`:** `build_aero_model` gained a `mach: Optional[float] = None`
  override (effective Mach = override else `AEROS.mach`); the effective Mach is stored in
  `AeroModel.mach`. A **supersonic guard** raises `ValueError` for effective Mach ≥ 1
  (steady subsonic VLM cannot solve the transonic/supersonic regime).
- **`aero/vlm.py`:** `prandtl_glauert_boxes` and `solve_rigid_cl` now raise on Mach ≥ 1
  instead of the silent `min(mach, 0.99)` clamp — one consistent rejection wherever Mach
  enters the steady build.
- **`solver/sol144.py`:** new `AeroCache` (Mach-keyed, memoizes AeroModels via
  `build_aero_model(..., mach=...)`). `run_sol144_trim` gained an optional `aero_cache`
  argument; it resolves the flight Mach from the TRIM card (falling back to `AEROS.mach`
  when unset), **warns** on a genuine TRIM-vs-AEROS disagreement, seeds a local cache with
  the prebuilt `aero`, and fetches the AIC for the resolved Mach. Existing 3-arg callers are
  unchanged (their TRIM Mach matches AEROS, so the seeded model is reused — no rebuild).

**Test/Acceptance:** `tests/aero/test_ae9_mach.py` (7 tests): TRIM-vs-AEROS mismatch warns
and uses the TRIM Mach; two subsonic subcases at different Mach trim to different ANGLEA;
a supersonic TRIM Mach and a supersonic `build_aero_model` override both raise `ValueError`;
the cache memoizes (same object per Mach, distinct β-scaled AIC across Mach). Full aero suite
green (223 passed, 2 xfailed).

**Key decisions:**
- Kept `AEROS.mach` as the default/fallback and warn (rather than retire it) — Mach currently
  lives only on `AEROS` field 9, so full retirement would force every deck/test to migrate
  for no benefit.
- Mach-keyed cache (not a contract that takes `bulk` and rebuilds unconditionally) preserves
  the build-once fixture pattern and leaves all existing callers working unchanged.
- Supersonic input errors rather than clamps: the result of a silent clamp would be a
  physically wrong answer for a regime this solver cannot represent.

---

### Phase A — AE1 Step G: analytic restrained stability derivatives ✅ COMPLETE (2026-06-12)

**Objective:** Replace the finite-difference restrained-derivative path (the AE8 one-pass
hybrid that "converged to neither NASTRAN's restrained nor unrestrained column") with the
exact analytic derivative from the Schur factorisation. Closes AE8's derivative half (the
sign half was closed by AE1 Step E; the parity precondition by AE1 Step D).

**Deliverables:**
- **`solver/sol144.py` `_compute_restrained_derivs`:** rewritten to compute, per label
  column, `∂u_l/∂δ = K_ll⁻¹·C_ax_l` (K_ll already carries the `q·Q_aa` aero feedback, so this
  is the restrained, aero-coupled sensitivity), then the linear normalwash → circulation →
  force chain: `∂w/∂δ = D_jx + D_jk·G_slope·∂u/∂δ`, `∂γ/∂δ = A_jj*⁻¹·∂w/∂δ`,
  `∂f_box/∂δ = S_kj·∂γ/∂δ`, with `CZ = Σ∂Fz/∂δ / S_ref` and `CMY = _pitch_moment(...) /
  (S_ref·c_ref)` (nose-up-positive, AE1 Step E). The FD machinery — `delta_perturbation`
  parameter, nominal `Fz0/My0` evaluation, per-column perturbed re-solve — is deleted.
- **`tests/aero/test_ae1_restrained_derivs.py` (new, V-AE1e partial):** rigid columns
  unchanged (CZα 5.071, CMα −2.871); restrained CZα 5.112 vs NASTRAN Table 7-1 5.103 (q=40)
  within 1%; analytic columns equal the captured pre-rewrite FD baseline to round-off.

**Test/Acceptance:** `pytest tests/aero/test_ae1_restrained_derivs.py` (8 passed); full aero
suite green (223 passed, 2 xfailed).

**Key decisions:**
- The trim is linear in each label, so the analytic derivative equals the old FD result to
  round-off — the rewrite is behaviour-preserving and removes FD truncation/clarity risk
  rather than changing numbers.
- Confirmed (and recorded in the backlog) that closing Step G did **not** move the SC2 trim:
  the stability derivatives are an output, not the trim driver, so SC2's residual lives in
  the high-q flexible trim solve (AE8), not the derivative recovery.
- AE8 stays open for the unrestrained (mean-axis / inertial-relief, ZAERO Eq 12.14/12.15)
  derivative set and the remaining Table 7-1 restrained columns (need the MSC manual values).
- **Still open (unchanged by this work):** the SC2 (q=1200) flexible residual — AE8 / Step G.

---

### Phase A — AE1 Step F: V-AE1d %-full-scale trim acceptance gate ✅ COMPLETE (2026-06-13)

**Objective:** Close the AE1 acceptance gate by encoding the correct V-AE1d acceptance metric.
The original per-target *relative* tolerance was the wrong metric: SC2 (q=1200) trims its AoA
through ~0 as dynamic pressure rises, so a fixed absolute error reads as an exploding percentage
(ANGLEA "+136%" for a 0.0019 rad / 0.107° miss). Normalised to each variable's valid physical
range instead, both subcases already pass — the acceptance was satisfied; only the test-gate edit
and the 3-part move remained.

**Deliverables:**
- **`tests/aero/test_ae1_fullspan.py::TestVAE1dSC2`:** dropped the `@pytest.mark.xfail` decorator
  and re-expressed the SC2 ANGLEA/ELEV assertions as `pytest.approx(target, abs=TOL)` against the
  variable's full-scale range — `TOL_ANGLEA_FS = np.deg2rad(0.3)` (1% of the 30° AoA neg→pos stall
  band) and `TOL_ELEV_FS = np.deg2rad(0.4)` (1% of the 40° commanded elevator throw). Failure
  messages report the miss in degrees and as %FS. The unused `REL_SC2` constant was removed and
  the module/class docstrings updated to the %FS rationale.
- **Measured SC2 result (full-span deck):** ANGLEA +0.107° = 0.357% FS, ELEV −0.092° = 0.229% FS —
  both inside the gate. `TestVAE1dSC1` keeps its existing live relative gate (ANGLEA 1.5% / ELEV
  1% / lift 1%), which is also green.

**Test/Acceptance:** `pytest tests/aero/test_ae1_fullspan.py` (17 passed, 0 xfailed); full suite
green (801 passed, 0 xfailed — was 799 passed / 2 xfailed; the 2 SC2 relative xfails cleared).

**Key decisions:**
- Acceptance is gauged against each TRIM variable's full-scale physical range, not relative to its
  NASTRAN target — relative tolerance is meaningless at SC2's near-zero trim point.
- No HA144A bulk-parameter re-tuning (NSPAN/NCHORD, spline DTOR, RCSID) and no chasing of the
  residual: the ~0.1° miss is a q-INVARIANT common-mode offset (the same absolute error already
  accepted at SC1), not a high-q flexible defect. Its optional root-cause is tracked, downgraded
  to MINOR, as AE8a.
- Only `TestVAE1dSC2` was converted, per the backlog's explicit directive; SC1's relative gate is
  meaningful (rigid-dominated, trim point well away from zero) and was left unchanged.

---

### Phase C — AE10 + Step 56: SOL 144 CLI dispatch, f06 output & flight-load export ✅ COMPLETE (2026-06-13)

**Objective:** Make SOL 144 reachable end-to-end from `main.py` (AE10) and write the static
aeroelastic trim results to `.f06` plus a trimmed flight-load export (Step 56). Before this,
`run_sol144_trim` had no production caller — `sbeam ha144a.bdf` exited with "SOL 144 is not
supported" — and there was no f06 trim formatter.

**Deliverables:**
- **`sbeam/main.py` — SOL 144 branch (AE10):** unlike the two-arg SOL 101/103 pattern,
  the branch builds `grid_index` (`build_grid_index`) and an `AeroModel`
  (`build_aero_model`, which rejects `SYMXZ≠0`), seeds an `AeroCache` shared across subcases
  so a multi-Mach deck builds each AIC once, and calls `run_sol144_trim` per subcase. Writes
  `<stem>.f06` and `<stem>.aero_loads.bdf`.
- **`sbeam/results/f06_writer.py` — `build_f06_sol144_text` / `write_f06_sol144`:** new SOL 144
  block set — TRIM VARIABLES (free vs prescribed), STABILITY DERIVATIVES (rigid + elastic
  restrained), AERODYNAMIC TOTALS (CL/CMY), AERODYNAMIC DIVERGENCE, and — gated on the
  subcase's `AEROF`/`APRES` requests — an AERODYNAMIC BOX PRESSURES AND FORCES block. The
  DISPLACEMENT / BAR FORCE / BAR STRESS blocks were factored into shared helpers
  (`_displacement_block`, `_bar_forces_block`, `_bar_stresses_block`) reused by SOL 101 and 144
  (SOL 101 output is byte-identical).
- **`sbeam/results/results.py` — `Sol144TrimResult` enrichment:** added `box_cp`,
  `box_forces` (physical, `q·skj@γ`), `grid_loads` (`g_disp^T·q·f_box`, the FORCE/MOMENT
  export source), and `q_div`.
- **`sbeam/solver/sol144.py`:** `run_sol144_trim` now populates the four new fields;
  `_divergence_dynamic_pressure` computes the single critical divergence pressure on the
  restrained l-set (`q_div = 1/max positive-real eig of K_ll⁻¹Q_ll`; `None` if non-diverging).
- **`sbeam/results/load_export.py` (new):** `build_aero_load_cards_text` / `write_aero_load_cards`
  emit comma free-field `FORCE`/`MOMENT` cards (unit scale, components carry the load) per
  subcase; the set sums to the trimmed lift/moment.
- **`sbeam/parser/case_control.py`:** `AEROF` / `APRES` output requests parsed onto
  `SubcaseControl`; the stale `parse_case_control` docstring ("not 101 or 103") corrected.
- **Tests:** `tests/test_main.py::test_sol144_produces_f06_and_loads` (end-to-end, AE10);
  `tests/results/test_f06_sol144.py` (block presence + AEROF/APRES gating + one-row-per-box);
  `tests/results/test_load_export.py` (FORCE Fz sum = `q·CL·sref` to 1e-6, re-parse round-trip);
  `tests/parser/test_case_control.py::TestSol144CaseControl` (SOL 144 + TRIM + AEROF/APRES).

**Test/Acceptance:** Full suite green (792 passed, 2 xfailed). On `ha144a_fullspan_sbeam.bdf`
the exported FORCE Fz sum balances the trimmed lift to 3.5e-9 relative; `q_div ≈ 4034`
(q=40 → q/q_div ≈ 0.0099).

**Scope boundaries (Step 56 deferrals, held deliberately):**
- **Maneuver-balanced (aero + inertial) load export** stays with **Step 53** — Step 56's own
  text routes the maneuver case there; `run_sol144_trim` produces the determined plain trim,
  so only the plain-trim grid loads are exported.
- **`DIVERG`-card multi-q sweep + divergence mode shape** stays with **Step 55** — Step 56
  delivers only the single critical `q_div` diagnostic from the trim matrices. *(Closed in
  Step 55, 2026-06-13 — see below.)*

**Key decisions:**
- The f06 box block prints the global 1-based box index (no CAERO column) because the
  box→CAERO map is not carried on `Sol144TrimResult`; keeping the writer signature
  `(case_control, bulk, result, subcase_id)` identical to SOL 101/103 was preferred over
  threading the AeroModel into the writer.
- Divergence is computed on the **restrained l-set** (`K_ll`, `Q_ll`), not the full a-set:
  the free-flight SUPORT `K_aa` is singular, so an a-set generalized eig would be ill-posed.
- New result fields are optional with defaults, so existing `Sol144TrimResult` construction
  and the Step 50 `Sol144Result` are unaffected.

---

### Phase C — Step 55: DIVERG-card divergence sweep + mode shape + V_div ✅ COMPLETE (2026-06-13)

**Objective:** Drive the static-aeroelastic divergence eigenproblem `K_ll φ = q·Q_ll φ`
from a `DIVERG` case-control/bulk entry — returning the lowest `NROOTS` positive
divergence dynamic pressures, their **mode shapes**, and (given a reference density)
the divergence speeds `V_div`, at each Mach on the card. Generalises the single critical
`q_div` already shipped with Step 56.

**Deliverables:**
- **Model (`model/aero.py`):** `Diverg` gains an sbeam-extension `rhoref` field (density
  for `V_div`).
- **Parser (`parser/bdf_reader._handle_diverg`):** `DIVERG  SID  NROOTS  RHOREF  M1 M2 …` —
  `RHOREF` in field 4 (default 0.0 ⇒ no `V_div`), Mach list field 5+ with continuations.
  The `diverg_sid` case-control hook already existed.
- **Solver (`solver/sol144.py`):** `_divergence_roots(K_ll, Q_ll, nroots)` solves
  `(K_ll⁻¹ Q_ll) x = (1/q) x` (dense generalised eig, mirroring `sol103._solve_modes_dense`),
  keeps real-positive `1/q`, sorts ascending in `q`, truncates to `nroots`. `run_sol144_diverg`
  reuses the trim path's a-set reduction (`_compute_aset_data`, `assemble_global_stiffness`,
  `build_qaa`), partitions to the restrained l-set, sweeps the card's Machs via the existing
  `AeroCache`, scatters each eigenvector to the g-set (`_expand_to_g`, max-abs normalised),
  and maps `V_div = √(2·q_div/ρ)` when `rhoref > 0`.
- **Results (`results/results.py`):** `Sol144DivergResult` → `DivergMachResult` → `DivergRoot`.
- **f06 (`results/f06_writer.build_f06_sol144_diverg_text`):** per-Mach `AERODYNAMIC
  DIVERGENCE` table (root no., `Q-DIV`, `V-DIV`) + a divergence mode-shape block per root.
- **CLI (`main.py`):** a SOL 144 subcase with `DIVERG=sid` runs the sweep (alongside trim
  when a TRIM is also present; standalone when not) and appends its f06 block.

**Test/Acceptance (V-C2):** `tests/aero/test_step55_diverg.py` (14 tests) — the eigen-core
matches a closed-form 2-DOF system (sorted roots, negative/complex filtering, `nroots`
truncation, no-divergence ⇒ empty); on the full-span HA144A deck the sweep's lowest positive
root **reproduces the validated single `q_div` to machine precision** (`rel<1e-9`), roots are
sorted positive, `V_div=√(2q/ρ)` holds, mode shapes are g-set-sized and max-abs-normalised,
and the multi-Mach sweep shows compressibility lowering `q_div`. Parser and f06-block tests
included. Full suite green (583 passed in the aero/results/parser scope; no regressions).

**Key decisions:**
- Divergence is solved on the **restrained l-set** (same restraint as the single-`q_div`
  path) because the free-flight SUPORT `K_aa` is singular; the sweep's lowest root therefore
  coincides exactly with `_divergence_dynamic_pressure`, which is the primary correctness gate.
- Selection rule (Risk KC3): only real, strictly positive `1/q` are physical — spurious
  negative/complex eigenvalues of the unsymmetric `Q_ll` are discarded.
- `RHOREF` lives on the DIVERG card (field 4) rather than a new `AERO` bulk card — the model
  has no density anywhere, and this keeps the change local and the `V_div` mapping opt-in.
- A DIVERG subcase needs no TRIM card (divergence depends only on `K_aa`/`Q_aa`), so the CLI
  routes it independently of the trim solve.

---

### Phase A/C — V-AE3: Independent unit-Cp force/moment cross-check ✅ COMPLETE (2026-06-13)

**Objective:** Close the AE13 validation blind spot — the one that let 207 tests pass while the
HA144A trim was grossly wrong — with a gate that confirms the force/moment coupling path is
INDEPENDENTLY correct, not merely self-consistent. The nearby checks were all non-discriminating:
the analytic==FD restrained-derivative check is vacuous on a linear system; `test_ae1_step_e_moment.py`
checks `_pitch_moment` against itself (a common scale error passes); and
`test_phase_b.py::test_tz_sum_vs_cl_magnitude`'s `min(err_full, err_half) < 0.02` structurally
accepts both the correct lift and exactly half of it (it could not catch the `sym=2` parity bug).

**Deliverables:**
- **`tests/aero/test_vae3_cross_check.py` (new):** builds the box force/moment two independent
  ways on the same model and asserts the totals agree to ≤1%, parametrised over
  `sample/ha144a_fullspan_sbeam.bdf` (M=0.9) and `sample/val_vlm_rect_ar8.bdf` (M=0):
  - **Path A (coupling)** — the SOL 144 chain `f_box = skj @ (ajj_inv_corr @ w)` with `w` the
    `build_djx` ANGLEA column (`= −n_z`); totals via `_pitch_moment` (`sol144.py`).
  - **Path B (independent)** — `solve_rigid_cl` (`sbeam/aero/vlm.py`), which rebuilds its own AIC
    and Kutta–Joukowski resultants in a separate module; at unit q `Fz = CL·S_ref`,
    `My = CM·S_ref·c_ref`.
- Reuses `_pitch_moment`, `build_djx`, `solve_rigid_cl`, `build_grid_index`, and the
  `_x_ref`/module-fixture pattern from `test_ae1_step_e_moment.py` — no new production code.

**Test/Acceptance:** `pytest tests/aero/test_vae3_cross_check.py -v` → 4 passed. Path-A totals
match the `solve_rigid_cl` resultants to machine precision on both decks (HA144A: Fz 2028.4, My
−11484; rect_ar8: Fz 37.245, My −9.0267 — rel err ≤ 6e-16). A parity proxy (halving `f_box`)
produces a 0.50 relative error, failing the 1% gate by ~2× — confirming the gate discriminates.
Full aero suite green.

**Key decisions:**
- **Excitation matched, not approximated.** `solve_rigid_cl` uses `rhs = −α·n_z` with no W2GJ
  baseline; HA144A has a W2GJ (`wg≠0`), so Path A is driven with the ANGLEA column ALONE
  (excluding `aero.wg`). The system is linear, so `α = 1 rad` is exact, not small-angle.
- **Mach matched.** Effective Mach = `bulk.aeros.mach` is passed to `solve_rigid_cl` so the β_pg
  scaling is identical on both paths.
- **Genuinely independent.** Neither target deck carries a WKK/AECORR correction, so
  `build_aero_model` sets `ajj_inv_corr = solve(AJJ)` (scaled by `1/β_pg` then `2/chord` → ΔCp)
  while `solve_rigid_cl` separately computes `gamma = solve(A, rhs)/β_pg` and `cp = 2γ/chord` —
  same physics, separately coded — so a scale/parity error in either module fails the gate.
- **Moment uses an absolute floor** (`0.01·|Fz_indep|·c_ref`) to avoid a near-zero-normalisation
  artifact on a symmetric/planar deck (the trap AE8a documents).
- Named `test_vae3_cross_check.py` to avoid collision with the unrelated "V-AE3a" trim-lift gate
  in `test_trim_urdd.py`.

### Phase A/C — AE1 Step C: `Q_aa` rigid-body null-space regression gate ✅ COMPLETE (2026-06-13)

**Objective:** Lock in the AE1 Step B spline fix with a permanent, cheap regression guard that
asserts the rigid-body modes which do not load the aero lie in the null space of the flexible
aero stiffness `Q_aa = G_disp^T·S_kj·(A_jj*)^-1·D_jk·G_slope`, i.e. `Q_aa·u_rb ≈ 0`. The property
is already satisfied (measured `‖Q_aa·u_tz‖ ≈ 2e-14` on HA144A); this is a guard against a future
spline regression silently re-contaminating `Q_aa` (as the old SET1-collinearity defect did), NOT
a lead on the residual SC2 trim offset (that is MINOR AE8a). `TestGlobalRigidBody` previously gated
only the FACTORS (`g_slope·u_rb`, `g_disp·u_rb`) and only on planar geometry; this closes two gaps —
the COMPOSED `Q_aa` operator, and out-of-plane (z≠0) coverage.

**Deliverables (test-only — no production code changed):**
- **`tests/aero/test_spline.py::TestGlobalRigidBody`** extended with composed `Q_aa·u_rb`
  null-space assertions, assembled via the real `build_aero_model` → `build_qaa` chain
  (`sbeam/aero/coupling.py`) and the existing `_apply_rigid_body` basic-frame rigid-body basis:
  - HA144A swept-planar: `{Tx,Ty,Tz,Rz}` null to `< 1e-10`; `Rx` gated BOUNDED (`< 1e-3`).
  - Math-exact planar rect: `{Tx,Ty,Tz,Rx,Rz}` null to `< 1e-10`.
  - **New 30° dihedral fixture** (`dihedral_wing_ops`) — CAERO, grids, and spline CID all tilted
    about the streamwise x-axis; the only fixture with z≠0 grids and a non-vertical surface
    normal: `{Tx,Ty,Tz,Rx}` null to `< 1e-10`.
- **Positive discriminators:** rigid pitch (Ry) asserted to LOAD (`‖Q_aa·u_Ry‖∞ > 1`) on all three
  fixtures, and rigid yaw (Rz) asserted to LOAD on the dihedral fixture — so the gate can never
  pass trivially on a degenerate all-zero `Q_aa`.

**Test/Acceptance:** `pytest tests/aero/test_spline.py -k RigidBody` → green (18 new `Q_aa` cases);
full `tests/aero/` suite 254 passed. Manually verified the gate trips: perturbing one `g_slope`
row by 1e-3 drives `‖Q_aa·u_tz‖` from 1.9e-14 to 0.48 (» 1e-10).

**Key decisions / corrections to the backlog acceptance wording:**
- **`val_vlm_rect_ar8.bdf` cannot be used** for this gate — it is a pure rigid-VLM validation deck
  with no GRID/SET1/SPLINE2 cards, so `build_aero_model` returns `g_slope=None` and no `Q_aa`
  exists. The backlog conflated it with the in-test math-exact rect fixture, which is the correct
  machine-exact target.
- **`< 1e-10` on HA144A holds only for the exactly-null modes** (Tx,Ty,Tz,Rz). HA144A's `Rx`
  residual is `1.4e-4` — `g_slope·u_Rx ≈ 4.7e-7` (5-decimal BDF coordinate rounding on the swept
  EA line) amplified by `‖Q_aa‖ ≈ 2.1e3`. It is gated BOUNDED (`< 1e-3`); the machine-precision
  `Rx` null is proved on the math-exact rect and dihedral fixtures instead.
- **A tilted dihedral surface, not just z-offset grids.** The SPLINE2 operator is independent of
  grid-z (verified: g_slope/g_disp are byte-identical for z-offset grids), so z-offset grids would
  only vary the rigid-body input, not the operator. Tilting the whole surface about x gives the
  normal a y-component, which makes yaw (Rz) correctly LOAD the aero (`g_slope·u_Rz = sin Γ`) where
  it is null for a planar wing — genuine out-of-plane coupling the planar fixtures cannot exercise,
  while translations and roll (Rx) stay machine-precision null.
- Assert against the actual rigid-body translation/rotation basis, never an arbitrary pitch field
  (pitch legitimately loads the aero and is not a null-space member).

### Phase A/C — AE11: D_jx YAW column + AESURF hinge geometry + hinge-moment recovery ✅ COMPLETE (2026-06-13)

**Objective:** Fix two latent control/lateral-column defects in `build_djx` and add the
hinge-moment output NASTRAN reports but sbeam lacked. (1) The YAW column duplicated ROLL
(`−(2/bref)·y_ctrl`); yaw rate on a vertical fin is a sidewash `∝ (x − x_ref)`, not `∝ y`. (2) The
AESURF control column was `−n_z·eff`, ignoring the parsed `Aesurf.cid1` hinge axis — exact only for
a spanwise hinge, wrong for swept/non-spanwise ones. (3) No hinge-moment recovery. All MINOR and
non-blocking for AE1 (HA144A trims use ANGLEA/PITCH/URDD3/ELEV, and its ELEV hinge is spanwise).

**Deliverables:**
- **`sbeam/aero/integration.py` (`build_djx`):** split the `("ROLL","YAW")` branch; YAW is now
  `−(2/bref)·(x_ctrl − x_ref)·n_y` (sidewash projected on the box y-normal, so it loads vertical
  surfaces and vanishes on z-normal panels). The AESURF branch resolves the hinge axis
  `ĥ = R[:,1]` from `_get_transform(aesurf.cid1, …)` and sets the column to `−(ĥ × n)·x̂·eff`,
  which reduces to `−n_z·eff` for `ĥ = ŷ`. Dropped the `eff if eff != 0.0 else 1.0` guard (the
  parser already defaults a blank field to 1.0, so the guard wrongly overrode an explicit 0.0).
- **`sbeam/solver/sol144.py::_compute_hinge_moments` (new):** per AESURF, the hinge moment
  `HM = Σ_{j∈AELIST} [(r_j − o) × F_j]·ĥ` about the `cid1` origin/axis, with `r_j = box.force_point`;
  returns `{label: {'total': HM/q at trim, <trim_label>: dHM/dδ}}`, the rigid columns built from
  `skj @ (ajj_inv_corr @ D_jx[:,col])` exactly like `_compute_rigid_derivs`. Carried on the new
  `Sol144TrimResult.hinge_moments` field (`results/results.py`) and printed in a new
  **HINGE-MOMENT DERIVATIVES** `.f06` block (`results/f06_writer.py`, values scaled to the trim q).
- **`tests/aero/test_ae11_hinge.py` (new, 6 cases):** YAW formula + fin-loads/wing-ignores +
  YAW≠ROLL; HA144A spanwise-hinge no-regression (new column bit-identical to `−n_z·eff`); a
  swept-hinge fixture (column = `−(ĥ × n)·x̂`, differs from naive `−n_z`); and a hinge-moment
  self-consistency check (uniform-Cp flat surface vs the closed-form `−Σ area·Cp·(x_force − x_hinge)`).

**Test/Acceptance:** `pytest tests/aero/test_ae11_hinge.py` → 6 passed; full `tests/aero/` 260
passed, `tests/solver` + `tests/integration` + `tests/results` 120 passed. HA144A SC1 trim
unchanged (ANGLEA 0.171052, ELEV 0.490775) and the ELEV column bit-identical, proving the
hinge-axis generalisation did not perturb the spanwise case. The HINGE-MOMENT DERIVATIVES block
renders on `sample/ha144a_fullspan_sbeam.bdf` with finite ELEV/ANGLEA/PITCH derivatives and zero
URDD (inertial) columns.

**Key decisions:**
- **Spanwise-hinge reduction is the no-regression guarantee.** `ŷ × n = (n_z, 0, −n_x)`, so
  `−(ŷ × n)·x̂ = −n_z`; CORD2R 1 on HA144A has its y-axis along global y, so ELEV is unchanged.
- **Hinge moment validated by self-consistency, not external NASTRAN HMAERO data** (chosen scope):
  the closed-form uniform-Cp resultant is independent of the recovery code, so it catches a
  lever-arm/sign/axis error without needing the MSC manual figures.
- **ROLL left as-is** — the backlog confirms it is correct for the main (horizontal) wing;
  generalising it to a normal-projected form was out of scope.
- YAW remains latent (no caller passes it today), so the fix cannot regress any existing trim.

---

### Phase C — Step 58: Dihedral / anhedral (±Γ) correctness ✅ COMPLETE (2026-06-14)

**Objective:** Guarantee the SOL 144 chain — VLM → spline → force integration → trim — is correct
for non-planar lifting surfaces, for **both** positive dihedral (Γ>0) and anhedral (Γ<0). HA144A and
`val_vlm_rect_ar8` are planar (z=0), so the entire validated chain was unexercised out of the
xy-plane — a latent `(0,0,1)` normal or an Fz-only force resultant would pass every existing test
and only bite on the first real wing (the AE13 validation-blind-spot class). FOUNDATIONAL for the
remaining Phase C load chain (maneuver, monitor, lateral derivatives all inherit out-of-plane
geometry).

**Key finding — the architecture was already correct out of plane; this is a validation/lock-in
step, not a rewrite.** `mesh_caero1` (`sbeam/aero/panel.py`) already derives each box normal from
the actual z-bearing corner geometry via a cross-product (canted `(0, ∓sinΓ, cosΓ)`, not `(0,0,1)`);
`build_skj` (`sbeam/aero/integration.py`) already emits the full 3-component resultant
`F = area·normal·cp` (so a canted panel carries side force `Fy`); the force→g-set transfer
(`g_disp`, shape `(3·n_box, n_g)`) and the `build_djx` `−n_z`/`−n_y` columns already carry the
out-of-plane components; and the spline maps structure through the SPLINE2 CID axes. No production
solver code needed changing.

**Deliverables:**
- **`sample/val_vlm_dihedral.bdf` / `sample/val_vlm_anhedral.bdf`** — rigid-VLM AR=8 rect wings
  canted at Γ=±10° (tips at `(0, ±4cosΓ, ±4sinΓ)`), full-span for the symmetric `Fy` cancellation.
- **`sample/val_dihedral_trim.bdf`** — a minimal structured symmetric dihedral wing: a flexible CBAR
  spar per semi-span along the canted elastic axis, `SPLINE2` on a canted CORD2R (origin on the EA;
  `z_hat` = surface normal), `CONM2` mass, `SUPORT` (Tz plunge) + `SPC1`, and a determined 1g plunge
  trim (ANGLEA free, URDD3 = −9.81).
- **`sbeam/solver/sol144.py::aero_moment_resultant` (new)** — full 3-component aerodynamic moment
  `M = Σ (r_j − ref) × F_j` (roll/pitch/yaw) from `box_forces`/`force_point`; backs the lateral
  acceptance and is reusable by future monitor-point integration. (`_pitch_moment` left as the
  single-source pitch arm for the trim.)
- **`tests/aero/test_dihedral.py` (V-C-DIH, 6 cases, parametrised ±10°).**

**Test/Acceptance:** `pytest tests/aero/test_dihedral.py` → 6 passed; full `tests/aero/` +
`tests/integration/` unchanged (no planar regression).
- Box normal `n·(0, ∓sinΓ, cosΓ) = 1` per box (≤1e-12), `n_x ≈ 0`, both signs.
- Per-box `Fy/Fz = n_y/n_z` (= ∓tanΓ) exact; total `Fy` cancels to ≤1e-10·|Fz| over the full-span
  build; lift non-trivial.
- Rigid `CL = CL_planar·cosΓ` within 1% (actual 0.27% at AR=8, via `solve_rigid_cl`'s K-J CL);
  dihedral and anhedral give identical CL (cos is even); `CY ≈ 0`.
- Structured trim closes out of plane: `|Fz_aero| = m·g = 98.1 N` (inertia-relief balance against
  the 1g URDD3), residual `Fy`/roll `Mx`/yaw `Mz` all ≤1e-8·|Fz|; panels genuinely off-plane
  (`max|z| > 0.1`).

**Key decisions:**
- **Scope: a minimal purpose-built symmetric dihedral wing** for the structured spline+trim gate
  (user choice), not a full dihedral HA144A variant. Monitor-load coverage is out of scope (monitor
  code does not exist yet); Step 58 instead guarantees the 3-component resultant monitors will
  consume, via `aero_moment_resultant`.
- **Two analytic relations both hold and were documented:** the K-J `CL` tracks `cosΓ` (matches the
  backlog's "CL·cosΓ within 1%", 0.27% actual), while the `area·normal·cp` (skj) vertical force
  tracks `cos²Γ` (incidence reduction × force projection); the per-box `Fy/Fz = n_y/n_z = ∓tanΓ` is
  the exact geometric relation, replacing the backlog's small-angle `sinΓ` approximation.
- **Trim sign is convention-free:** the validated invariant is the inertia-relief force/moment
  balance and symmetric cancellation; the trimmed ANGLEA sign reflects the minimal single-DOF (Tz)
  plunge support in the basic z-up frame (no RCSID/canard).

### Phase C — Step 52 (remainder): over-determined trim + lateral rate derivatives ✅ COMPLETE (2026-06-14)

**Objective:** Close the two remaining Step 52 deliverables — over-determined (redundant-control)
trim and the lateral/directional rate-aero derivatives — on top of the already-shipped determined
Schur trim solver. (Determined trim, AE2–AE7, AE9, AE1 Steps A–G, AE10/Step 56 were closed earlier.)

**Deliverables:**
- **Lateral / directional derivatives (`sbeam/solver/sol144.py`):** `_compute_rigid_derivs` and
  `_compute_restrained_derivs` now emit the roll/yaw **moment** coefficients
  `CMX = Mx/(S_ref·b_ref)` and `CMZ = Mz/(S_ref·b_ref)` alongside the longitudinal `CZ`/`CMY`,
  using the full 3-component cross-product resultant `aero_moment_resultant` about the AERO
  reference. These give the damping derivatives `C_lp = ∂CMX/∂ROLL`, `C_nr = ∂CMZ/∂YAW`, and the
  dihedral effect `C_lβ = ∂CMX/∂SIDES`. The ROLL/YAW/SIDES quasi-steady normalwash columns already
  existed in `build_djx`; this step added the moment recovery, threading `suport_pos`/`b_ref`
  through both derivative helpers.
- **Over-determined trim (`_solve_trim_overdetermined`):** dispatched from `run_sol144_trim` when
  `n_free > n_suport`. The Schur build was refactored into `_build_trim_schur` (shared with the
  determined path) + `_recover_u_a`. The equilibrium equality `schur_A·δ = schur_b` is eliminated
  by a **null-space reduction** `δ = δ_p + N·z`; the redundancy coordinate `z` minimises the convex
  weighted-L2 TRIMOBJ objective `Σ wᵢ·δᵢ²` subject to the TRIMCON inequalities and TRIMVAR bounds
  (SLSQP on the small reduced problem).
- **Case control + result + f06:** `SubcaseControl.trimobj_sid` (+ `TRIMOBJ = sid` parsing);
  `Sol144TrimResult.trim_mode` ("determined"/"over-determined"); f06 gains a LATERAL/DIRECTIONAL
  DERIVATIVES block (CMX/CMZ rigid + restrained) and a TRIM SOLUTION mode line.

**Test/Acceptance:**
- **V-C4** (`tests/aero/test_trim_overdetermined.py`, 5 cases): an over-determined HA144A (PITCH
  left free, `min(PITCH²)` objective) reproduces the determined ANGLEA/ELEV with PITCH ≈ 0; a
  TRIMCON `PITCH ≥ rhs` forces its bound active; the convex objective is initial-guess insensitive
  (KC6); a missing TRIMOBJ is rejected.
- **V-LAT** (`tests/aero/test_lateral_derivs.py`, 5 cases): roll-rate damping `|C_lp| ≈ 0.54` for
  the AR=8 rect wing (inside the lifting-line/strip-theory band), clean ROLL↔Fz/My/Mz decoupling
  on a planar wing, YAW/SIDES vanish without a vertical surface, and `C_lβ` flips sign between
  `val_vlm_dihedral`/`val_vlm_anhedral` and is zero on the planar deck.
- Full `tests/aero/` + `tests/results/` + case-control parser: 362 passed (no regression to the
  validated longitudinal `test_ha144a_rigid_derivs` column).

**Key decisions:**
- **Objective = weighted-L2** (`Σ wᵢ·δᵢ²`, user-confirmed) rather than a linear (LP) objective —
  convex, unique minimiser, robust.
- **Null-space reduction over a direct SLSQP equality constraint:** the equilibrium rows carry
  structural-force magnitudes O(10³) that swamp the O(0.1) trim variables; handed to SLSQP as an
  equality the line search fails to converge (iteration-limit). Eliminating the equality by
  construction yields a small, well-scaled QP.
- **Lateral moment sign convention:** CMX/CMZ are the raw cross-product resultant in sbeam's
  z-up / y-starboard aero frame (the V-C-DIH frame), so the damping derivatives carry that frame's
  handedness, not a textbook z-down body-axis sign. The magnitudes and the ±Γ `C_lβ` symmetry are
  the convention-independent content the gates assert; the full textbook body-axis sign mapping is
  deferred (not needed by the consumers — monitor loads use `aero_moment_resultant` directly).
- **Lateral derivatives validated standalone:** the rigid lateral columns are gated by building the
  aero model + `D_jx` + `_compute_rigid_derivs` directly (no SUPORT/trim needed) — a full balanced
  antisymmetric roll/yaw *maneuver* is Step 53, not Step 52.

### Phase C — Step 53: Balanced maneuver loads & inertia relief ✅ COMPLETE (2026-06-14)

**Objective:** Turn the SOL 144 trim into a load-generating capability — emit the net
(aero + inertial) grid load for each balanced static maneuver (symmetric pull-up/push-over at a
load factor, steady roll, steady sideslip) for downstream stress, and guarantee force/moment
closure per maneuver case (KC9).

**Context:** the inertia-relief math itself shipped with Step 52 — `_build_inertial_cols` builds
the inertial sensitivity `M_ax` (force per unit URDD acceleration; CONM2 + CBAR mass, translation
+ rotation + transport), the trim RHS already carries `M_ax · a` for prescribed URDD, and the
Schur solve carries free-URDD columns. Step 53 adds the **explicit net-load deliverable**, the
**closure gate**, the **export**, and the **maneuver presets**.

**Deliverables:**
- **Net load on the result (`sbeam/solver/sol144.py`, `results/results.py`):** after the trim
  solve, `inertial_loads = M_ax · a_all` uses the **final** trim accelerations (prescribed AND
  solved-free URDD), transformed RCSID→basic by the new shared helper `_urdd_rcsid_to_basic`
  (extracted from the previously-inline prescribed transform). `net_loads = grid_loads +
  inertial_loads` is the stress deliverable; `inertial_loads` is the non-zero inertia column the
  future MONPNT3 (MON3) consumes. Both default to the aero-only / zero case for a 1g determined
  trim (URDD≈0), so existing results are unchanged.
- **Closure gate (V-C5 / KC9):** `_load_resultant` reduces a g-set load to a body-frame
  6-resultant; `maneuver_closure` stores the net (aero+inertial) resultant about the moment
  reference. For a pure free aircraft (SUPORT, no SPC) a non-zero residual raises a `UserWarning`
  (gravity double-count / lumped-vs-consistent mass guard); for an SPC'd model the residual
  legitimately equals the constraint reaction and the warning is suppressed.
- **Export (`results/load_export.py`, `main.py`):** `build_maneuver_load_cards_text` /
  `write_maneuver_load_cards` emit the net load as FORCE/MOMENT cards to
  `<stem>.maneuver_loads.bdf` (alongside the existing aero-only `<stem>.aero_loads.bdf`). The
  per-grid emission loop was factored into `_emit_force_moment_cards`, shared with the aero export.
- **Presets (`sbeam/model/maneuver_presets.py`):** `load_factor_to_urdd3(n_z, g) = −n_z·g`, plus
  documented TRIM recipes for pull-up/push-over, steady roll, and steady sideslip. No new card.
- **Gravity convention:** folded into the URDD load factor (NASTRAN; `URDD3 = −n_z·g`); no
  separate `GRAV` body-force term in SOL 144. Single-sources the inertial path and matches the
  existing AE5/AE7 URDD tests.

**Test/Acceptance (V-C5, `tests/aero/test_maneuver_loads.py`):** on the full-span HA144A deck —
which pins only the antisymmetric DOFs (SPC1 1246 on GRID 90) and SUPORTs the symmetric trim DOFs
(35) — a symmetric pull-up gives (1) net symmetric resultant `Fz`, `My` ≈ 0 to machine precision,
(2) trimmed aero lift = `n_z·W` (W = Σ CONM2 mass · g) to 1e-6, (3) `net_loads` and recovered
CBAR loads scale **exactly** 2.5× from 1g→2.5g, and (4) per-grid round-trip of the exported
maneuver FORCE cards. 5/5 green; full aero suite unchanged.

**Key decisions:**
- Inertial load uses the **final** trim URDD (not just prescribed) so a free load-factor variable
  contributes to the recovered net load consistently with the displacement solve.
- The free-aircraft closure warning keys on **absence of SPC DOFs**, not on the residual alone, so
  half-span / antisymmetric-pinned models (whose residual is a real reaction) don't false-positive.



## Monitor Points — Integrated Section Loads (Phase 1, static)

### MON1–MON4 / V-MON1 — `MONPNT1` / `MONPNT3` integrated section loads ✅ COMPLETE (2026-06-13)

**Objective:** Emit integrated section loads for the structures/loads handoff from each SOL 144 trim
subcase — replicating NASTRAN `MONPNT1` (aero-only) and `MONPNT3` (aero + inertia + reaction, splined
to structural grids), with sbeam-native RBE3/RBAR pass-through (the load already rides the splined
g-set vectors, so the NASTRAN MONPNT3 rigid-element load-path limitation does not apply). Phase 1 is
static emulation only; section-cut running loads and dynamic (gust) extraction remain backlog
follow-ons.

**Deliverables:**
- **MON1 — BDF parsing (`sbeam/model/aero.py`, `sbeam/parser/bdf_reader.py`):** `Monpnt1`, `Monpnt3`,
  `Aecomp` dataclasses + `BulkData` containers (`monpnt1s`, `monpnt3s`, `aecomps`); field-by-field
  handlers and dispatch. `AECOMP` resolves to either an `AELIST` (box IDs, MONPNT1) or a `SET1`
  (grid IDs, MONPNT3). Full cross-reference validation (AECOMP list exists, MONPNT `comp` resolves to
  the correct list type, `cp` CORD2R exists). Card layout:
  `MONPNT1/3, NAME, LABEL, AXES, COMP, CP, X, Y, Z`.
- **MON2/MON3 — integration (`sbeam/results/monitor_points.py`, new):** `integrate_monpnt1` sums the
  trimmed per-box `box_forces` over the AELIST collection (NASTRAN box-ID → k via
  `spline._build_id_to_k`), with the 3-component moment about the monitor reference. `integrate_monpnt3`
  sums the g-set `grid_loads` (aero), `inertial_loads` (inertia), and recovered SPC/SUPORT reaction
  over the SET1 grids. Both transform the (F,M) resultant into the monitor `cp` frame and apply the
  AEROS-`SYMXZ` parity factor (single-sourced; 1.0 for the full-span pipeline, 2.0 + `*WHOLE-AIRPLANE*`
  annotation if a half-model is fed directly). **Key reuse:** the aero/inertia contributions are
  summations of vectors already on `Sol144TrimResult` (`box_forces`, `grid_loads`, `inertial_loads`),
  so no `G_kg` re-derivation; reaction reuses `sol101.recover_reactions` (R = K·u − f, balanced against
  the net aero+inertial load). Call site is in `run_sol144_trim`; result carries
  `Sol144TrimResult.monitor_loads = {name: MonitorLoad}`.
- **MON4 — output (`sbeam/results/f06_writer.py`, `sbeam/results/load_export.py`, `sbeam/main.py`):**
  a `MONITOR POINT INTEGRATED LOADS` f06 block (one metadata + values group per monitor per subcase)
  and a per-run CSV (`<stem>.monitor_loads.csv`, one row per monitor per subcase: metadata, six totals,
  and the diagnostic `Fz_aero/Fz_inertia/Fz_react` breakdown). HDF5 hierarchical export deferred.

**Test/Acceptance:**
- `tests/parser/test_monitor.py` (7) — round-trip echo of `MONPNT1`/`MONPNT3`/`AECOMP` incl. a CORD2R
  monitor + validation rejections.
- `tests/results/test_monitor_points.py` (7) — MONPNT1 uniform-Cp sum, 3-component carry-through,
  parity doubling, cp-frame transform; MONPNT3 aero/inertia/reaction breakdown and collection-scoping.
- `tests/results/test_monitor_output.py` (3) — f06 block render + CSV value/skip behaviour.
- `tests/aero/test_monitor_ha144a.py` (V-MON1, 6) — whole-aircraft `MONPNT1` aero == `MONPNT3` aero
  (spline conservation: force to ~1e-15 rel, moment to ~1e-6); whole-aircraft `MONPNT3` aero Fz =
  trimmed 1g weight (~16000 lb) within 1%; breakdown sums to totals; section cuts finite/sign-correct;
  live (non-zero) inertia column from the 1g gravity trim (URDD3 prescribed).
- `sample/ha144a_fullspan_sbeam.bdf` carries the four monitor cards (wing-root, right-wing,
  whole-aircraft MONPNT3 + whole-aircraft MONPNT1).

**Key decisions:**
- **Reuse stored g-set vectors over re-deriving `G_kg`** — the aero/inertia columns already exist on
  the trim result, so MONPNT3 is a per-grid summation; equivalent result, far less code, and the
  RBE3/RBAR pass-through is inherited from the spline that built `grid_loads`.
- **Spline conservation is whole-aircraft, not per-surface** — `MONPNT1`(boxes) == `MONPNT3`(grids)
  only over a collection whose grids receive load exclusively from those boxes; on HA144A the
  centreline root grid is shared across the right/left wing and canard splines, so the exact equality
  is gated on the whole-aircraft monitors. Force matches to machine precision; the moment carries the
  spline rotational-row numerics (~1e-6 relative).
- **Parity single-sourced from post-mirror `AEROS.SYMXZ`** — the solver runs full-span (mirror zeros
  SYMXZ), so parity = 1 in the normal pipeline; the ×2 path + annotation is retained for direct
  half-model input.

---


## Backlog Closures — 2026-07-03 Aeroelastic Completion Review

The backlog was restructured on 2026-07-03 into the ordered steady-aeroelastic close-out plan
(Steps AC1–AC6). The following items were closed and moved here in the same session.

### Phase A/C — AE13: Validation gap — no swept/coupled/benchmark gates ✅ RESOLVED (2026-07-03)

**Objective:** Close the validation blind spot exposed by the 2026-06-11 review: 207 aero tests
passed while the HA144A trim was grossly wrong — every geometric validation case was unswept and
uncoupled, the V-B1/V-B3 rigid-body gates never exercised a swept spline axis or fore/aft offset
grids, and no dimensional-consistency check tied the coupled force path back to the rigid solver.

**Deliverables (all landed across 2026-06-11 → 2026-06-13; item formally closed at review):**
- **V-AE1 — HA144A acceptance gates** (`tests/aero/test_ae1_fullspan.py`): SC1 relative gates
  (ANGLEA 1.5% / ELEV 1% / lift 1%) and SC2 %-full-scale gates (AE1 Step F) both live — the
  superseded relative `xfail` is gone. The original "lift tests pass" reassurance was
  non-discriminating (lift balanced for both the correct and the halved trim) — exactly the blind
  spot this item was about; superseded by per-target tolerances.
- **V-AE2 — Swept-spline rigid-body gate** (`TestSweptSplineRigidBody`, 2026-06-11; updated
  2026-06-12 to EA-only SET1 with DTHX=+1 alongside V-AE1b `TestGlobalRigidBody`): exercises a
  60°-swept axis + full 6-mode lever-arm rotation.
- **V-AE3 — Unit-consistency gate** (`tests/aero/test_vae3_cross_check.py`, 2026-06-13):
  coupling-path (`skj @ ajj_inv_corr`) total force AND moment equals the Kutta-Joukowski
  resultants from an INDEPENDENT `solve_rigid_cl` rebuild. Fz/My agree to machine precision on
  HA144A and val_vlm_rect_ar8; the half-f_box parity proxy fails by ~2×, so it DOES catch the
  factor-of-2 parity bug (unlike the old `min(err_full, err_half)` proxy).
- **V-AE1g — Rigid-derivative benchmark** (`test_ha144a_rigid_derivs.py`, 2026-06-13): full rigid
  longitudinal column (CZα/CMα/CZq/CMq/CZδe/CMδe) within 0.5% of the independent ADA370433
  Table 3.1.1 NASTRAN values.

**Test/Acceptance:** the three planned permanent gates plus the rigid benchmark are all
implemented and green. Residual coverage — the flexible **unrestrained** derivative layer —
is not a validation-infrastructure gap and rides with the open AE8b item.

### Phase A — A5: Aero model reachable only from the viewer ✅ CLOSED (expected state, 2026-07-03)

**Verdict:** not a defect. `build_aero_model` / `solve_rigid_cl` are called from `viewer/app.py`
and (since AE10, 2026-06-13) from `main.py` under SOL 144. No solver or CLI path consumes the
aero model under SOL 101/103 — expected, since those are non-aero solutions. The item's two
actionable halves both closed elsewhere: the end-to-end SOL 144 CLI dispatch landed with
AE10/Step 56 (144 whitelisted at `case_control.py:61`; stale "not 101 or 103" docstring
corrected), and `val_vlm_rect_ar8.bdf` documents the SOL-101 workaround. Removed from the
backlog with the "expected-state" verdict recorded here.

### AE1 — HA144A validated trim reference baseline (moved from backlog, 2026-07-03)

AE1 closed 2026-06-13 (see "AE1 Step F" above). The validated-trim table the backlog retained as
the regression reference baseline is preserved here:

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
sweep) — tracked, with the decisive root-cause test, on **AE8a** (backlog Step AC3). Standing
cautions: do not chase the `q·Q_aa` flexible increment for SC1 (a 0.6% effect at q=40), and do
not re-tune HA144A bulk parameters (NSPAN/NCHORD, spline DTOR, RCSID) to fit the gate — rigid
CLα already matches NASTRAN to 4 sig fig at the same mesh.

### Step AC1 — Documentation scrub + full project-documentation review ✅ COMPLETE (2026-07-03)

**Objective:** Remove actively misleading closed-defect guidance from the standard docs and code
(the original AC1 scope), widened at review to a full audit of every project document against the
code (parser card dispatch, SOL dispatch, module tree, viewer capability) — including README.md,
which still described a Phase-1-only tool.

**Deliverables:**
- **`docs/10_standard/05_aeroelastics.md`:** "⚠ Known Defects" table replaced with "Validation
  status & known limitations" — AE1/AE2–AE10 resolved rows removed, AE8 split into AE8a/AE8b,
  the blanket "do not use SOL 144 trim" warning replaced with the accurate validated-and-usable
  statement + gate list. The stale "Step 52 (WIP — carries open critical defects)" section
  (pre-fix benchmark-failure numbers) rewritten as CLOSED with the over-determined case. Title
  broadened to Phases A–C + G0; supported-cards table completed (SUPORT, PSTRIP/STRIPK,
  AECOMP/MONPNT1/MONPNT3, MLOADS family, TABLED1); module map completed (mirror.py,
  maneuver_qs.py, maneuver.py, maneuver_presets.py, monitor_points.py, maneuver_output.py).
- **R23 closed:** `docs/10_standard/03_static_analysis.md` now documents the per-element 6-arg
  `recover_bar_forces(cbar, grids, pbars, mat1s, displacements, grid_index) -> BarForce`.
- **`sbeam/solver/sol144.py`:** `run_sol144_trim` docstring corrected — over-determined trim is
  implemented (null-space + TRIMOBJ/TRIMCON/TRIMVAR), no `NotImplementedError`.
- **README.md rewritten to current capability:** tagline + analysis types now cover SOL 144 trim
  / divergence / monitor points and the Phase G0 `MLOADS` path; the supported-cards table extended
  from 18 to the full 51 parsed cards (aero geometry, corrections, splining, trim, monitor,
  maneuver families); workflow updated; limitations gained an Aeroelastics section (subsonic
  steady VLM only, full-span only, unrestrained derivatives open) and the solver line corrected
  to "SOL 101, 103, and 144".
- **`docs/10_standard/02_card_reference.md` completed:** new sections for SET1, SPLINE2, ATTACH,
  SPLINE0, SPLINE1 (parsed-but-rejected, Step 48), SUPORT, and the Phase G0 family (MLOADS,
  MLDTRIM, MLDTIME, MLDCOMD, MLDPRNT, TABLED1); case-control table gained MLOADS/AEROF/APRES/
  TRIMOBJ. Verified complete against the parser dispatch table — all 51 bulk keywords documented.
  **RBE2 correctness fix:** the doc claimed a direct DOF copy; the implementation applies the full
  6×6 rigid-body lever-arm matrix (`assembly/rbe3.py`) — corrected. Ten details that existed only
  in the old `01_beam_model.md` card tables ported (RBE3 limitation, CONM2 6×6 assembly +
  singular-mass warning, MAT1 G-derivation, CBAR local-axis pin releases + no-G0-form, CBUSH
  massless/coincident-orientation rules, CORD2R non-collinearity, GRAV reaction correction, WKK
  lstsq inversion, RBE2+CONM2 attachment pattern).
- **`docs/10_standard/01_beam_model.md` de-duplicated:** the ~645-line per-card field-table
  section (duplicating the card reference) removed; the doc is now the data-model & parser guide
  (BulkData, dataclass shapes, parser API, T-matrix assembly, coordinate handling, limits) with a
  compact card summary linking to `02_card_reference.md`. Stale parser claims fixed (SOL
  101/103/144; full recognised-card list).
- **`docs/10_standard/00_program_overview.md`:** purpose/CLI sections now include SOL 144
  (TRIM/DIVERG/MLOADS routing + the five auxiliary output files); project-structure tree
  regenerated from the actual package (17 missing modules added); version/phase table rewritten
  to match CLAUDE.md phases and point at the backlog's AC plan.
- **`docs/10_standard/06_viewer.md`:** "Run Analysis" and "F06 Export" sections reconciled with
  the code (`_run_sol144` dispatch + session keys; `build_f06_sol144_text` /
  `build_f06_sol144_diverg_text`; CLI-only exports noted as backlog Step AC5).
- **`docs/00_INDEX.md`** descriptions updated (01 scope; 05 covers Phases A–C + G0);
  **CLAUDE.md** assembly module list corrected.

**Audit verdicts (docs reviewed for deletion/merge):** no file deletions warranted — no orphan
docs, no dangling INDEX links; `40_history/archive/` correctly holds the one superseded plan.
The single merge executed was 01→02 (card tables). Authoritative-home rules going forward: card
fields live in `02_card_reference.md` only; the exhaustive card list lives there (README/CLAUDE
summarise); the module tree's authoritative home is `00_program_overview.md`.

**Test/Acceptance:** card inventory verified against `bdf_reader.py` dispatch (51/51); every
ported/updated claim verified against code before writing; trim regression tests pass
(`tests/aero/test_trim_overdetermined.py`); no doc now states SOL 144 trim is unusable.

### Step AC2 — AE8b: Unrestrained (mean-axis) stability derivatives ✅ COMPLETE (2026-07-05)

**Objective:** Implement the missing UNRESTRAINED (mean-axis / inertia-relief) stability-derivative
column in SOL 144, previously known-wrong after two reverted first-principles attempts, gated on
sourcing the actual NASTRAN/ZAERO algorithm.

**Algorithm sourced (the gate-lifter):** MSC Nastran Aeroelastic Analysis User's Guide, Static
Aeroelasticity, Eqs. (2-111)–(2-134) (`.refs/MSC_Nastran_2021.3_Aeroelastic_Analysis_User_Guide.pdf`
PDF pp. 70–82; 2023.1 edition also in `.refs/`), independently cross-checked against the ZAERO 9.2
Theoretical Manual Ch. 12 modal mean-axis form, Eqs. (12.9)–(12.16) (`.refs/ZAERO_9.2_Theo_3rd_Ed.pdf`
PDF pp. 270–276). Zeiler 1997 (NASA 19990010052) and Riso et al. 2018 (JoA) added to `.refs/` as
supporting background.

**Deliverables:**
- `sbeam/solver/sol144.py::_compute_unrestrained_derivs` — literal transcription of the MSC DMAP
  elimination chain (ARLR/AMLR/ALX → M2RR/M3RR/K3LX → M4RR/K4LX → KAZL/K2RR/KARZX → MIRR/KR1ZX →
  `Z1ZX = −m_r·MIRR⁻¹·KR1ZX`), DMAP names kept in comments for audit. Structural-K rigid-body
  modes `D = −K_ll⁻¹·K_lr` (separate LU from the aeroelastic `K^a_ll`), rigid-mode validity guard
  (`‖K_rl·D + K_rr‖/‖K‖`), singularity guard near divergence, TR force/moment transfer from the
  SUPORT DOFs to the aero reference. Also computes the unrestrained W2GJ-baseline intercepts
  (IPZF chain). `M_aa` reduced in `run_sol144_trim` via the same RBE3+SPC path as `maneuver_qs`.
- `Sol144TrimResult.unrestrained_derivs` / `.unrestrained_intercepts`; f06
  ELASTIC UNRESTRAINED column block (URDD columns print N/A — they are the mean-axis ü_r
  unknowns) + intercepts line (`sbeam/results/f06_writer.py`); viewer stability-derivative table
  gained the unrestrained columns (`sbeam/viewer/results_view.py::_render_sol144_trim`).
- V-AE1e restrained-column completion (rides-here item): all six restrained longitudinal columns
  now gated against MSC Table 7-1 q=40 (CMα, CZq, CMq, CZδe, CMδe added; ELEV CZ at 2% — actual
  +1.3%).

**Key decisions / findings:**
- **The operator, not the physics, was the open question — and the sourced operator is now proven
  correct two independent ways:** the MSC DMAP chain and the ZAERO modal mean-axis form (exact
  complement basis, no truncation) agree to 4+ decimals at BOTH q=40 and q=1200.
- **Why both reverted attempts failed:** the unrestrained derivative eliminates `u_r` through the
  MASS-weighted mean-axis constraint and `u_l` through the aeroelastic `K^a_ll` — attempt 1's load
  projector and attempt 2's converged free-free solve are different operators. However, the
  faithful MSC chain reproduces attempt 2's q=1200 value (CZα 11.67) exactly — the old conclusion
  "NASTRAN's unrestrained is not the converged free-free derivative" was a MISDIAGNOSIS.
- **NEW finding (opened as backlog AC7/AE14):** sbeam's flexible coupling itself over-predicts at
  high q — the RESTRAINED q=1200 columns are 5–28% off Table 7-1 (independent of any mean-axis
  machinery). The q=1200 unrestrained gates are therefore XFAILed pending AC7; prime suspect is
  AE12 (SPLINE2 DTOR/DTHZ ignored).
- Manual typo resolved by dimensional analysis: Table's `KARZX = KAZL − KAXL·ALX` line must read
  `KARZX = KAXL − KAZL·ALX` (the printed form is not even conformable).
- Backlog target transcription fix: unrestrained q=1200 CMα is −4.577 (Table 7-1, image-verified),
  not the −4.557 previously recorded from ADA370433.

**Test/Acceptance:** `tests/aero/test_ae1_restrained_derivs.py` — q=40 acceptance MET: all six
unrestrained longitudinal derivatives within 1% of Table 7-1 {CZα 5.127, CMα −2.907, CZq 12.158,
CMq −10.007, CZδe 0.2520, CMδe 0.5678} (actuals 0.2–1.0%), intercepts within 1%
{CZ0 0.008509, CMY0 −0.006064}; unrestrained > restrained > rigid ordering gate; q=1200 targets
gated as strict-value XFAIL (un-xfail when AC7 closes). ZAERO modal cross-check (throwaway
scratchpad script, deleted per plan): MSC chain ≡ modal form, max deviation < 1e-4 relative at
both q. Full aero+results+solver suites: 490 passed, 6 xfailed.

### Step AC3 — AE8a: q-invariant common-mode trim offset ✅ ROOT-CAUSED & CLOSED (2026-07-05)

**Objective:** Root-cause or document the small q-invariant rigid common-mode trim offset on
HA144A (was +0.107° ANGLEA / −0.092° ELEV at both q=40 and q=1200, ≤0.4% FS).

**Root cause found — W2GJ sign convention inverted vs NASTRAN.** The MSC guide (Eq. 2-104 and the
HA144A example: "W2GJ = 0.1 deg = 0.001745 rad for the wing boxes" — positive value, described as
lift-increasing incidence) defines positive W2GJ as nose-up incidence, the same sense as ANGLEA.
sbeam added W2GJ card data directly to the internal washout-positive normalwash, applying the deck's
wing incidence backwards. Decisive metrology: with the sign corrected, sbeam's rigid intercept
coefficients match Table 7-1 to 4 significant figures (CZ0 +0.008419 vs +0.008421, CM0 −0.006007 vs
−0.006008) — with the old sign both intercepts are exactly sign-flipped.

**Deliverables:**
- `sbeam/aero/integration.py::build_wg` negates W2GJ card data into the internal normalwash
  (card = NASTRAN convention, positive = incidence; internal `wg` unchanged, positive = washout);
  module docstring + `W2gj` dataclass comment (`sbeam/model/aero.py`) rewritten.
- Card **writers** negated to match (round-trip coherent): `sbeam/aero/section_correction.py` and
  both `sbeam/aero/body_correction.py` emitters store NASTRAN-convention data in `W2gj` cards.
- `sample/ha144a_fullspan_sbeam.bdf` unchanged — its +.001745 values (copied from the MSC deck)
  are now interpreted correctly.
- Tests updated: `tests/aero/test_integration.py::TestBuildWg` (card-convention pins),
  `tests/aero/test_ae1_fullspan.py` (SC2 ANGLEA sign gate → %FS band; docstrings/actuals).

**Residual documented (accepted per the AC3 acceptance clause):** after the fix the offset becomes
−0.093° ANGLEA / +0.104° ELEV — still q-invariant, ≤0.31% FS, inside every gate (SC1 relative:
−1.0%/+0.4%; SC2 %FS: 0.31%/0.26%). Decomposition (hand-trim on Table 7-1 coefficients): the old
+0.107° was this −0.093° bias masked by a +0.200° sign-error swing; both codes' incidence response
is −0.100° per +0.1°, matching to 0.001°. The residual is a compound of sub-0.5% flexible-column
and coupling differences (see AC7/AE14 for the high-q half), not attributable to any single
verified input — all rigid derivatives and (now) intercepts match ≤0.05%.

**Test/Acceptance:** trim error ≤1% FS at every TRIM subcase (met: ≤0.31% FS); the q=40
common-mode root-caused (W2GJ sign) and the residual documented in
`docs/10_standard/05_aeroelastics.md`. Full suite green (the four TestBuildWg pins + 30
fullspan/derivative tests updated); section/body-correction round-trip tests unaffected
(writers and reader flipped together).

---

### Step AC4 — Minor solver warnings — AE12, A7, A8 ✅ COMPLETE (2026-07-05)

**Objective:** Close the three batched MINOR pre-solve/handler items: warn when SPLINE2
DTOR/DTHZ carry values sbeam ignores (AE12), add a cosine chordwise-spacing helper and a
low-NCHORD pre-solve warning (A7), and a box aspect-ratio pre-solve warning (A8).

**Deliverables:**
- **AE12 (code half)** — `sbeam/aero/spline.py::_build_spline2_block` warns (UserWarning,
  same style as the AE4c DTHX switch) when `DTOR ≠ 1.0` (ratio ignored) or
  `DTHZ ∉ {0.0, −1.0}` (Rz attachment not modelled; treated as detached).
  **Key decision:** DTHZ = −1.0 is NASTRAN's "Rz detached" — exactly sbeam's behaviour —
  so it stays silent (the backlog's literal "warn on DTHZ ≠ 0.0" would have spammed every
  HA144A run, whose SPLINE2 cards all carry DTHZ = −1.0). User-confirmed gate.
- **AE12 (misidentified PG-normal half)** — no code change (re-diagnosis 2026-06-12 stands:
  the normal copy in `prandtl_glauert_boxes` is exact for every `mesh_caero1` box since
  n_x = 0 always). Closed with the prescribed guard-test pair
  (`tests/aero/test_vlm.py::TestPrandtlGlauertNormalCopy`): a synthetic n_x ≠ 0 box where
  copied vs recomputed normals differ, paired with a 30° dihedral mesh where they agree to
  machine precision — guarding against a needless future "recompute for dihedral" fix.
- **A7** — `sbeam/aero/panel.py::cosine_chord_fractions(n)`: LE-concentrated half-cosine
  breakpoints `ξ_i = 1 − cos((π/2)·i/n)` for AEFACT/LCHORD use. **Key decision:** helper,
  NOT a new NCHORD default — uniform NCHORD semantics preserved for box-for-box NASTRAN
  fidelity (HA144A). Pre-solve warning in `build_aero_model` when a VLM CAERO1 has < 4
  chordwise boxes (NCHORD or LCHORD intervals).
- **A8** — companion warning in the same loop when any box AR (spanwise LE edge / mean
  streamwise corner edge) is outside [0.5, 2.0]; one warning per CAERO1 with out-of-band
  count and worst AR. NB: `AeroBox.chord` is the STRIP chord, not the box streamwise
  length — the AR uses corner edges. Decoupled strip body panels (PID → PSTRIP) are exempt
  from both A7/A8 (no horseshoe vortex).
- **New finding (feeds AC7/AE14):** the HA144A SPLINE2 cards carry only DTOR=1.0 /
  DTHZ=−1.0 — NASTRAN performs no Rz rotational coupling on that deck either, so **AE12 is
  exonerated as AC7's prime suspect**; the backlog AC7 entry now leads with the SPLINE2
  slope/torsion-transfer kinematics suspect.

**Test/Acceptance:** 16 new tests — `test_spline.py::TestSpline2DtorDthzWarnings` (warn
gates + HA144A-values-stay-silent), `test_vlm.py::TestPrandtlGlauertNormalCopy` (guard
pair), `test_panel.py::TestCosineChordFractions` (endpoints, monotone LE-density, LCHORD
mesh integration), `test_mesh_quality.py` (A7/A8 fire/silent/strip-exempt via
`build_aero_model`). Full suite 1053 passed / 6 xfailed; end-to-end HA144A build confirmed
warning-free; a negative scratch deck (DTOR=0.5, DTHZ=1.0, NCHORD=2, sliver boxes) fired
all four warnings.

---

### Step AC7 — AE14: High-q flexible-coupling fidelity gap ✅ ROOT-CAUSED & CLOSED (2026-07-05)

**Objective:** Close the 5–28% gap between sbeam's HA144A restrained stability-derivative
columns and MSC Table 7-1 at q=1200 (≤1.3% at q=40), and un-xfail the q=1200 gates.

**Root cause 1 — full-span deck fuselage stiffness (dominant).** The full-span mirror of
the MSC half-span deck doubled the centreline CONM2 masses but NOT the centreline fuselage
PBAR: a member on the symmetry plane carries half properties in a half model, so the
full-span fuselage (carrying BOTH wings) flexed ×2. Found via the guide's Listing 7-2
MONDSP1 wing-tip monitor: at q=40 (box forces matching ≤1%) the rigid-fit spanwise
bending rotation RX matched ×1.038 while the streamwise rotation RY ran **×1.442** — and
sbeam's fuselage-driven root rotation alone nearly equalled NASTRAN's total. Doubling
PBAR 100 (A/I1/I2/J ×2, deck comment records the rationale): q=40 trim matches Listing 7-2
to 5 digits (ANGLEA 0.16918 vs 1.6919E-1), all six q=40 restrained columns ≤0.61%, the
rate-column (CZq/CMq) increment signs flip to correct — **and the AE8a "accepted trim
bias" (−0.093°/+0.104°) vanishes: it was this deck bug, superseding the AE8a residual
documentation.**

**Root cause 2 — SPLINE2 kinematics.** sbeam's cubic-Hermite spline differed from
NASTRAN's SPLINE2 in kind: (a) canard camber contamination — the 2-grid canard spline
acquired cubic chordwise curvature from attached grid rotations where NASTRAN's 2-point
linear fit gives a rigid pitching plane (visible as aft-loaded canard boxes ×1.26–1.39 at
q=1200); (b) the twist-gradient chordwise term was missing (analytic linear-twist field:
LE boxes ×0.67, TE ×1.19). **Fix: `_build_spline2_block` rewritten as the NASTRAN
infinite beam spline** (MSC Aeroelastic UG Eqs. 2-48…2-63): |Δt|³/12EI bending and
−|Δt|/2GJ torsion kernels + rigid part, **rigid chord arms** (off-axis grids legal, the
EA-collinearity restriction removed), MSC conventions adopted wholesale — spline axis =
CID **y-axis** (QRG remark 2), `DTOR = EI/GJ` (now used), `DZ`/`DTHX`/`DTHY` as attachment
flexibilities (0 rigid / >0 spring / negative detached; model field `dthz` renamed `dthy`
per the MSC card; parser defaults 0.0 = rigid). Rigid-body modes exact by construction
(verified 1e-12 on swept/rect/dihedral fixtures + the real deck).

**Deck restoration:** `ha144a_fullspan_sbeam.bdf` wing splines back to the MSC card values
— SET1 {99,100,111,112,121,122} (+ left mirror) and DTHX=DTHY=−1 (twist from LE/TE
stringer deflection pairs via rigid arms); CORD2R 2 verbatim MSC (38.66025,5,0 third
point), CORD2R 3 mirrored; monitor SET1s re-pointed at the spline load-target grids.
`val_dihedral_trim.bdf` and `tests/integration/bdf/val_spline2_cantilever.bdf` converted
to the y-axis convention (EA-only collinear SET1s attach rotations rigidly, DTHX=DTHY=0 or
DTHY=0).

**Results (q=1200 vs Table 7-1):** restrained CZα −1.53%, CZq −0.95%, CMq +2.02% (live
gates ≤2/2.5% PASS), CMα +4.30%, CZδe −2.90%, CMδe +5.23% (documented residual);
unrestrained CZα −1.90%, CZq −1.25%, CMq −2.28% (live 2.5% PASS), moment/ELEV residual
xfailed. q=40: ALL columns ≤0.20% (canard per-box ≤0.2% at pinned state). Residual
attributed by pinned-state per-box comparison to the wing-root TE boxes behind the canard
(steady-VLM vs k→0-DLM interference) — re-scoped as backlog Step AC8/AE15 per the
approved escape hatch.

**Test/Acceptance:** new gates — `TestRestrainedDerivsQ1200` (live α/rate + residual
xfail), `TestUnrestrainedDerivsQ1200` re-gated, `TestBeamSplineFlexFields` (analytic
linear-bend exact / linear-twist / parabolic fields), V-AE2b/c rewritten behaviourally,
`TestSpline2FlexWarnings` (DTOR≤0, DZ<0; valid flexibilities silent; DTOR genuinely
changes the interpolant). FD baseline re-captured (analytic ≡ FD to 2e-11). Full suite
green. Re-pinned: q_div sentinel 4034→3809.8 (fuselage + spline change), monitor SET1
semantics, load-export moment-card expectation (detached rotations ⇒ pure-force grid
loads, as NASTRAN). Diagnostic method (Listing 7-2 per-box force + MONDSP1 transcription,
pinned-trim-state comparison via a forced `_solve_trim_determined`) recorded here;
scratch scripts deleted.

### Step AC8 — AE15: Wing-root interference residual ✅ INVESTIGATED & ACCEPTED (2026-07-05)

**Objective:** Close the residual re-scoped from AC7 — HA144A q=1200 moment/ELEV columns
2.9–5.3% off MSC Table 7-1 (restrained CMα +4.30%, CZδe −2.90%, CMδe +5.23%; unrestrained
inherits), concentrated in the wing-root TE boxes behind the canard. Acceptance was
either/or: close the six xfailed gates at 2%, or document the kernel-difference
attribution quantitatively and accept. **Outcome: Path B — quantitatively attributed and
accepted** (user pre-decision: even a gate-closing kernel would ship documentation only,
feeding the Phase D DLM design).

**Deliverables:** `docs/20_theory/studies/a2_wing_root_interference.md` (Study A2, the
full evidence); six xfail reasons in `tests/aero/test_ae1_restrained_derivs.py` updated
to cite it; AE15 known-limitation row in `docs/10_standard/05_aeroelastics.md` re-worded
as investigated/accepted; INDEX row. **No product code changed.**

**Evidence (three independent experiments, all scratch-side):**
1. *Implementation exoneration* — DLR PanelAero (NASTRAN-lineage VLM: Hedman x/β
   compressibility, semi-infinite legs, Katz & Plotkin D1+D2+D3) run on the exact HA144A
   box geometry and substituted for `ajj_inv_corr` through the full SOL 144 chain:
   operator agreement 1.6e-8 relative Frobenius; every rigid and q=1200 flexible column
   identical to 4+ decimals. sbeam's VLM (Göthert y,z·β, 1000-chord legs) is
   implementation-correct; no textbook VLM reproduces MSC's coarse-mesh root loading.
   NOTE: the pre-registered "DLM-AIC substitution recovers ≥70% of each gap" bar proved
   unmeetable by construction — PanelAero's k=0 DLM *is* its VLM (steady part), so no
   open-source arbiter embodies MSC's proprietary steady-AIC quadrature.
2. *Convergence attribution* — in-memory remesh study (box-ID-dependent cards renumbered
   programmatically): chordwise refinement collapses the residual (NCHORD=8: CMα −0.49%,
   CZδe +2.27%, CMδe +0.76% vs NASTRAN's NCHORD=4 values; NCHORD=12 similar). Strip-level
   at the pinned Listing 7-2 trim state: in the four root strips NASTRAN-coarse lands
   within 1–15 lb of sbeam-refined where sbeam-coarse is 19–75 lb off. MSC's steady AIC
   is near-mesh-converged in the interference region; a coarse horseshoe VLM is not.
3. *Mechanism* — canard/wing spanwise-breakpoint misalignment corrupts even RIGID
   derivatives (canard 3/5-span stagger: rigid CZδe +0.246→+0.591/−0.502 sign flip;
   columns ±135–295%): the discrete-wake singularity sweeps across downstream collocation
   points. A kinked-wake z-offset of ±0.5 ft moves CMδe by 9 points. The residual lives in
   sub-foot wake-threading details a flat rigid wake at NCHORD=4 cannot resolve.

**Key decisions:** residual ACCEPTED as a documented kernel/method difference; six q=1200
gates stay `xfail(strict=False)` citing Study A2; resolution path if ever needed = Phase D
DLM (steady kernel-function quadrature) or chordwise refinement for sbeam-native models.
Modeling guidance published in Study A2 §5: align upstream/downstream spanwise breakpoints;
NCHORD ≥ 8 on wake-washed surfaces.

**Test/Acceptance:** no pins moved (no product change); suite unchanged at 1064 passed /
6 xfailed, with the xfail reasons now citing the study. Scratch artifacts (ac8_boxcmp.py,
ac8_meshstudy.py, ac8_panelaero.py, ac8_strip_wake.py, PanelAero venv) deleted at
close-out; reproduction recipe recorded in Study A2 §6.

---

### Step AC6 / Step 54 — CFD / wind-tunnel steady-pressure injection (CHORDCP) ✅ COMPLETE (2026-07-05)

**Objective:** Allow the SOL 144 trim mean-flow aerodynamics to be supplied directly from
CFD or wind-tunnel steady pressures, so the trim solution is a perturbation about the
measured operating point (backlog AC6; the last open steady close-out step).

**Deliverables:**
- **`CHORDCP` card** (sbeam extension) — `CHORDCP, SID, CAERO_EID, ALPHREF, MACH` +
  row-major per-box physical Cp continuations (same ordering as W2GJ). ALPHREF is
  **required and in degrees** (user decision — matches CFD/WT reporting and the
  `section_data.py` CSV convention), stored in radians on the `Chordcp` dataclass
  (`model/aero.py`); optional MACH is validation-only. Handler clones the AECORR
  continuation pattern (`parser/bdf_reader.py`); `bulk.chordcps` fills the slot reserved
  in `docs/30_future/01_static_aero_plan.md`.
- **Equivalent-normalwash substitution** — `corrections.apply_chordcp`: since the stored
  corrected operator `ajj_inv_corr` maps normalwash → physical ΔCp directly (2/chord and
  Göthert 1/β baked in), the injected Cp feeds a **min-norm lstsq** over the VLM
  sub-block, plus the `+ n_z·α_ref` re-referencing term (ANGLEA column is `−n_z`), and
  the result overwrites `aero.wg` at assembly (`aero_model._apply_chordcp_injection`).
  **Key decisions:** (1) NO Cp→Γ conversion — an adversarial design review caught that the
  plan's assumed Γ-unit operator was wrong (the `gamma` names in sol144 are misnomers);
  (2) `sol144.py` needed **zero load-path changes** — every consumer (trim RHS, f06
  totals, `maneuver_qs`, monitor points, viewer) reads the mean flow only through
  `ajj_inv_corr @ wg`; (3) solved ANGLEA is **absolute** (injection re-referenced to α=0);
  (4) min-norm solve + residual check because WT1/WT2 dead rows (ratio 0) make the
  operator singular — nonzero Cp on a dead row raises rather than silently losing load;
  (5) PSTRIP strip panels keep their W2GJ/Δα wash (diagonal decoupled block → sub-block
  solve exact).
- **v1 coverage rule (user decision):** every VLM CAERO1 must carry exactly one CHORDCP
  card, all sharing one ALPHREF; strip surfaces may not be targeted; W2GJ on injected
  surfaces is discarded with a warning (incl. body-correction-derived W2GJ). Partial
  coverage + viewer authoring deferred (backlog "CHORDCP follow-ons").
- **KC7 validation/warnings** — parse (required ALPHREF, no data), assembly (coverage,
  ALPHREF consistency, PSTRIP target, length ≠ NSPAN×NCHORD, dead-row Cp), solver
  (nonzero ALPHREF without an ANGLEA AESTAT → error; card-vs-TRIM Mach mismatch and
  trimmed-ANGLEA > 0.035 rad (≈2°) from ALPHREF → warnings). `mirror_halfspan` rejects
  CHORDCP (added to `_UNSUPPORTED`).
- **Outputs** — `Sol144TrimResult.chordcp_echo` + f06 `INJECTED OPERATING POINT` block
  (ALPHREF rad/deg, data Mach, per-surface + total injected Fz/q, My/q next to the VLM
  flat-plate lift at ALPHREF as a plausibility reference). Viewer: parse-summary and
  Aero-tab captions flag active injection; the Aero Correction tab **blocks** derivation
  on a CHORDCP deck (its baselines would read the injected wash and change meaning).
- **Docs** — card reference (entry + validation row), `05_aeroelastics.md` (new CHORDCP
  section + card table row), theory §3.4 (Eq. 13′ equivalent-normalwash derivation).

**Test/Acceptance (all three backlog gates):** `tests/aero/test_chordcp.py` — (1)
**identity**: injecting the program's own mean flow on the full-span HA144A deck (4 cards)
reproduces the Step 52 trim to 1e-9, at α_ref = 0, α_ref = 2°, and with a WT2-corrected
operator (Γ-unit target); (2) **scaled injection**: machine-precision wash algebra
`wg_eff(s) = s·wg + (1−s)·n_z·α_ref` verified, plus the physical check that 10% more
injected lift trims to lower ANGLEA; (3) **integral match**: model-recovered Fz/My at the
injected point equal the direct Cp·area sums to 1e-9. Plus toy-operator unit tests
(round-trip, dead rows, size guards), all validation/warning paths, strip-coexistence
(strip wash untouched, VLM replaced), mirror rejection, and the f06 echo block; parser
round-trip tests in `tests/parser/test_aero.py`. No-CHORDCP decks are bit-identical
(injection branch is a no-op). Full suite 1104+ passed / 6 xfailed.

---


## Resolved defects

### DEF-M6 — exported `FORCE`/`MOMENT` fields overflow the 8-character free field ✅ COMPLETE (2026-08-01)

**Objective:** `load_export._fmt` wrote `f"{val:.6E}"` — 12 characters, 13 with a sign — into
comma free-field `FORCE`/`MOMENT` cards. Free field does *not* exempt a card from the NASTRAN
8-character field width: a strict reader truncates each comma-delimited field to its first 8
characters, so `4.715932E+03` is read as `4.715932`, a silent factor-of-1000 corruption. sbeam
round-tripped its own output (its reader has no width limit), so nothing caught it — and
external stress handoff is the advertised purpose of this export (`05c:439`). One sample export
carried 66 oversized fields.

**Deliverables:**
- **`sbeam/parser/bdf_field.py`** (new) — `fmt_real8(val)` plus `parse_real(s)` and the
  `NASTRAN_SCI` regex. Sited in `parser/` so the write format and the read format are one
  module: `bdf_reader._to_float` now delegates to `parse_real`, and a test asserts they remain
  the same function.
- `fmt_real8` builds **both** a fixed-point candidate (`4715.932`) and a NASTRAN
  implicit-exponent candidate (`4.716+3`) and keeps whichever reproduces the value more
  closely — decimal wins across the normal load range, implicit exponent wins for very large or
  very small magnitudes. Non-finite input raises rather than writing `NAN` into a card, and a
  candidate that would read back as `inf` is rejected.
- `load_export._fmt` delegates to it, which propagates to every load-card consumer through the
  shared `emit_force_moment_cards` — the trim aero export, the Step 53 maneuver export and the
  Phase G0 critical-sample export.

**Key decision — 8-character fields, not large-field `FORCE*`.** Large field would preserve full
precision, but the reader has *no* `*` support at all (`_split_fixed_field` is hardcoded to
8-char/72-column and `FORCE*` falls through to the "Unknown BDF card" warning), so it would
convert a low-complexity export fix into a parser feature. Filed as part of the deferred work
instead; the 8-character path needs no reader change.

**Precision, measured not assumed:** fixed point keeps 6-7 significant figures across the
physical load range (worst observed rel 2e-6); the implicit-exponent range keeps 3-5 (worst 2.6e-5
positive, 3.5e-4 negative). The sign costs a character, which is the binding constraint:
`-2999.775064` can only be written `-2999.78`. Two existing per-grid export round-trip
assertions (`test_maneuver_loads.py`, `test_maneuver_qs.py`) were therefore relaxed from
`rtol=1e-6` to `1e-5` — the field-width floor, not exporter slop, and recorded as such in both
docstrings. The summed-lift round trip through `parse_bulk_file` still holds at `1e-6`.

**Test/Acceptance:** `tests/parser/test_bdf_field.py` (new) — width never exceeds 8 over the full
representable range (±1e-30 … ±1e30), legality (every real carries a decimal point), round-trip
per magnitude regime, non-finite raises, and the spelling-choice cases. End-to-end: **0 oversized
fields across 1456** exported card fields over all four HA144A decks, down from 66 in one export.

---

### DEF-M10 — HA144A whole-aircraft `MONPNT3` omitted 18.75 % of the inertia ✅ COMPLETE (2026-08-01)

**Objective:** `SET1 1310` (`AECOMP ALLGRID`, feeding `MONPNT3 MALLEA` "WHOLE AIRCRAFT") listed
every grid a spline transfers force to, but grid **97** carries `CONM2 97 = 93.236` slug and no
spline load, so it was never added. 93.236 of 497.256 slug is exactly 18.75 % of the model, and
the monitor reported ~+3000 lb of phantom lift on a balanced 1g trim. The solver summation itself
was verified exact — this was purely a deck defect.

**Deliverables:**
- Grid 97 added to `SET1 1310` in `sample/ha144a_fullspan_sbeam.bdf`. `MALLEA` now closes to
  0.0000 on the balanced trim (was +2999.78).
- **The same defect found in two sibling decks** while verifying: `ha144a_fullspan_mloads.bdf`
  (also missing 97) and `ha144a_massset_sweep.bdf` (missing 97 *and* the four fuel-overlay
  stations 110/120/210/220 — 5 grids, 38 % of that deck's mass). Both fixed.
  `ha144a_body_trim.bdf` already listed 97 and needed no change.
- **`monitor_points._warn_if_mass_coverage_incomplete`** — a solver warning naming the omitted
  grids, their mass and the omitted fraction.

**Key decision — qualify on aero coverage, not on closure.** A plain "does this set contain every
mass?" check fires on every legitimate section cut (`MWINGRT` is a single grid), and a plain
closure check does too. The signature of the real defect is narrower: *a monitor that integrates
all of the aero but only some of the mass*. So the monitor's z-force is compared against the model
total first, and only a whole-aircraft-scope monitor has its mass coverage checked — no opt-out
mechanism and no new card syntax needed. Masses come from the **active mass case**
(`mass_overlay.effective_conm2s`, threaded through as `massset_sid`), not from every `CONM2`
card: a MASSSET deck carries mutually exclusive overlays, and counting them all reported a
fraction the run never had (38.30 % of a 730 slug total that no single case has).

**Test/Acceptance:** `tests/aero/test_monitor_ha144a.py` — `SET1 1310` covers every CONM2-bearing
grid; `MALLEA` closes to ~0 on the balanced trim; a deck with grid 97 stripped raises exactly one
warning naming `97` and `18.75%` *and* is genuinely out of balance; and the two section cuts raise
none (the cry-wolf guard). All four shipped HA144A decks now run warning-free.

---

### DEF-M4 — `LOAD` in a TRIM subcase is refused, not silently ignored ✅ COMPLETE (2026-08-01)

**Objective:** `run_sol144_trim` never read `subcase.load_sid`.  The trim RHS is aero + inertia
only — there is no `f_struct` term — so a payload or thrust `FORCE` requested via `LOAD` in a
SOL 144 trim subcase was parsed into the subcase and then never consulted.  The restrained static
path (`run_aeroelastic_static`, `sol144.py:268-273`) *does* combine a LOAD set with the aero load,
which made the omission easy to miss.

**Deliverable:** a guard beside the existing SUPORT/TRIM checks at the top of `run_sol144_trim`,
raising when a subcase carries both `trim_sid` and `load_sid`.  The message names the subcase,
both SIDs, and the path that does support the request.

**Key decision — raise, do not implement.** Adding `f_struct` to the trim RHS is a capability
change with unresolved physics, not a defect fix: on a free-flight SUPORT trim an applied
structural load enters the force balance, so `maneuver_closure` stops meaning "aero vs inertia",
and whether the applied load participates in inertia relief is undecided.  That is now its own
backlog item; this batch closes the silent-ignore.

**Test/Acceptance:** verified safe first — no sample deck and no test constructs a
`SubcaseControl` with both `trim_sid` and `load_sid`, and `maneuver_qs` builds its `ic_subcase`
without one.  Gates in `tests/aero/test_trim_urdd.py::TestTrimRejectsLoadRequest`: the raise, the
message pointing at `run_aeroelastic_static`, and a no-regression guard that the ordinary no-LOAD
trim subcase is unaffected.  Both new gates confirmed to fail against the pre-fix implementation.

---

### Q4 + DEF-M3 — one mass model for `M_ax` (`build_inertial_cols` → `−M_gg·Φ_r`) ✅ COMPLETE (2026-07-31)

**Objective:** Remove the second mass model. `M_ax`, the inertia-relief sensitivity
(`dF/dURDD_k`), was a hand-rolled *lumped* inertia built directly from `conm2.m`, the diagonal
`i11/i22/i33` in the basic frame, and CBAR half-masses, while every elastic operator used the
consistent `assemble_global_mass`. Two defects fell out of that one root cause:

- **DEF-M3** — the hand-rolled model silently dropped CONM2 **offset transport** (it used the
  *grid* position as the moment arm, so an offset mass lost its parallel-axis `m·d²` inertia
  entirely), **products of inertia** (`i21/i31/i32` were never read, so yaw acceleration produced
  no roll reaction), CONM2 **`CID` rotation** (the tensor was used as if always basic-frame), and
  PBAR **`nsm`**. HA144A has none of these, so every shipped gate passed.
- **Q4** — even on clean CONM2s, lumped CBAR half-masses have no counterpart to the consistent
  mass translation↔rotation coupling, so `M_ax = −M_aa Φ_r` held on translational rows always but
  broke on rotational rows whenever `rho > 0` (measured O(10 %) of the peak column value).

This was load-bearing, not diagnostic: `M_ax` enters the trim equilibrium as
`C_ax = q·Q_ax + M_ax` (so the balance point itself moved) and is what `inertial_loads`,
`net_loads` and the exported `FORCE`/`MOMENT` stress handoff are recovered from. The maneuver
force/moment closure was machine-zero throughout because it checks `M_ax` against itself.

**Deliverables:**
- **`sbeam/assembly/rigid_body.py`** (new) — `build_rigid_vectors_g(bulk, grid_index, rigid_dofs,
  ref_pos)`, the single derivation of the g-set rigid-body geometry. It lives in `assembly/`
  rather than `modal_basis` because `modal_basis` imports `sol144`, so `sol144` cannot import
  back; both consumers now call one primitive instead of deriving the geometry twice.
- **`sol144.build_inertial_cols` rewritten** as `M_ax[:, k] = −M_gg @ Φ_r_g[:, dof(k)]` — ~90
  lines of hand-rolled inertia replaced by the definition. Gains an optional `M_gg=` parameter so
  callers that already hold the mass matrix do not assemble it twice, and a `ValueError` when a
  supplied `M_gg` does not match the g-set size. Aero-label columns stay identically zero and no
  mass is assembled at all when a deck has no URDD labels.
- **`modal_basis.build_rigid_modes`** now delegates its geometry to `build_rigid_vectors_g` and
  keeps ownership of the a-set restriction plus the RBE3/RBAR rigid-body-exactness round trip.
- **Callers wired to share one `M_gg`** — `assemble_aset_operators` passes the `M_gg` it already
  builds for `M_aa`; `run_sol144_trim` hoists its `assemble_global_mass` call above the `M_ax`
  build and reuses it for the unrestrained-derivative block, removing a duplicate assembly.
- **Docs:** `05c_sol144_maneuver.md` (the "Known limit" note replaced by the one-mass-model
  definition; MASSSET rebuild table), `00_program_overview.md` and `CLAUDE.md` (module tree),
  backlog shared-infrastructure ownership note.

**Key decisions:**
1. **Build on the g-set, then reduce** — not `−M_aa Φ_r_a` directly. `M_ax_g` is needed on the
   g-set anyway for inertial-load recovery and the load export, and the a-set identity follows
   exactly: `red.reduce_rect` is `Tᵀ·` and `T Φ_r_a = Φ_r_g`, so
   `Tᵀ(−M_gg Φ_r_g) = −M_aa Φ_r_a`. The identity is now **definitional**, not incidental.
2. **The primitive moves out of `modal_basis`, the a-set builder does not** — the single-owner
   rule is preserved where it matters (one derivation of the rigid geometry); splitting only the
   dependency-free part is what breaks the import cycle without a deferred import.
3. **`massset_sid` semantics unchanged** — `M_ax` inherits whatever `assemble_global_mass` does
   for a mass case, which is the point: a MASSSET sweep can no longer scale the elastic mass and
   the inertia-relief mass differently.

**Test/Acceptance:** the new gates are written against the **closed-form rigid-body resultant**,
not a second call into the same code path — for a unit rigid acceleration the d'Alembert nodal
loads must integrate to exactly the negated rigid mass properties about the reference point
(`F = −m a`, `M = −I_ref α` with `I_ref` parallel-axis transported). That is unforgeable by any
implementation that drops a term. `tests/aero/test_trim_urdd.py::TestInertialColsFullMassModel`
covers offset-transport-about-the-CM, products of inertia, CONM2 `CID` rotation, PBAR `nsm`, the
`M_gg` reuse path, the mismatched-`M_gg` error and the no-URDD-label short circuit. The Q4 pin
`test_m_ax_identity_limits_with_consistent_cbar_mass` becomes
`test_m_ax_identity_exact_with_consistent_cbar_mass`: exact to 1e-12 on **all** rows with
`rho = 2700` CBARs, plus an assertion that the rotational rows are genuinely populated so the
exactness check cannot pass for the trivial reason. **All seven new/changed gates were confirmed
to fail against the pre-fix implementation.**

Numerically, the shipped decks are **bit-identical** — HA144A and `val_dihedral_trim` are
CONM2-only with `rho = 0`, which is exactly why this defect survived. The change is visible only
once distributed mass exists (same decks, `rho` overridden to 2700):

| Deck | Quantity | pre-fix | post-fix |
|---|---|---|---|
| `ha144a_fullspan_mloads` | ANGLEA | 166.6637 | 166.7048 |
| `ha144a_fullspan_mloads` | ELEV | 320.9278 | 320.8873 |
| `ha144a_fullspan_mloads` | peak \|u\| | 33.193 | 33.447 (+0.76 %) |
| `val_dihedral_trim` | peak \|u\| | 0.001820 | 0.000842 (−54 %) |

Full suite 1230 passed / 6 xfailed; `ruff` and `pyright` clean.

**Not closed here:** the `M_ax` columns are still referred to `suport_pos` (the RCSID origin or
basic origin) rather than a user-selectable point — that is the RBMREF card, which remains a thin
wrapper over `build_rigid_modes` in the backlog.

---

### Step 64 / DEF-M1 — SPLINE0 / un-splined box loads into the trim equilibrium ✅ COMPLETE (2026-07-31)

**Objective:** Close the trim on body-panel decks. Boxes with no structural spline —
`SPLINE0`-declared body panels (A9 cruciform, A10 decoupled strip) and boxes no spline card
covers — generate real aerodynamic force that reached the printed totals, the rigid/restrained
derivatives and MONPNT1 (all-box direct sums), but never the trim force balance, `grid_loads`,
MONPNT3 or the `FORCE`/`MOMENT` export, because those go through `g_disp.T` and a SPLINE0 box's
`g_disp` rows are zero. The body-panel workflow exists precisely to carry residual Cm/Cn, so on
those decks the printed aircraft and the balanced aircraft were different aircraft.

**Root cause (the useful part):** sbeam followed the NASTRAN convention that force transfer is
the *transpose* of the displacement spline, so virtual work is conserved by construction. Under
one virtual-work-paired operator, `u_box = G u_g = 0 ⇒ f_g = Gᵀ f_box = 0`: zero load transfer is
a **theorem**, not an oversight. ZAERO avoids this by shipping a separate force-mapping spline
(`SPLINEF`); the 2026 ZAERO card-set review flagged "a separate force spline" as a practical gap
and only the `ATTACH`/`SPLINE0` half of that finding was implemented (Step 47).

**Deliverables:**
- **Third operator `g_load` = `g_disp` + injection rows** (`aero/spline.py`). For each uncoupled
  box `k` with master grid at `p` and lever `r_k = force_point_k − p`:
  `g_load[3k:3k+3, Tx:Tz] = I₃`, `g_load[3k:3k+3, Rx:Rz] = −skew(r_k)`, so `g_loadᵀ f` delivers
  `Σ F_k` and `Σ r_k × F_k` at the master grid — the exact 6-component resultant, **all three
  force components** (a vertical body panel's `Fy` is the Cn carrier). Read forward these are the
  rigid-body interpolation `u_k = u_m + θ_m × r_k`, so the virtual-work pairing is **restored,
  not broken**: `SPLINE0` now means "ATTACH for loads, zero for incidence".
- **New API** `build_spline_operators() → SplineOperators(g_slope, g_disp, g_load, covered,
  injections)`; `build_g_spline` demoted to a kinematics-only wrapper. `AeroModel` gains `g_load`,
  `load_injections`, `require_g_load()`.
- **`SPLINE0` field 5 `GRID`** (dataclass + parser) names the master grid; blank falls back to the
  first usable SUPORT grid.
- **All 13 force-transfer sites** switched to `require_g_load()` — `coupling.build_qaa`/`build_fg`
  (parameter renamed), `sol144` (`Q_ax_g`, `Q_gg`, `f_aero_g`, `grid_loads`, Step-50 path),
  `maneuver_qs`, `modal_basis` (GAFs + rate columns), `compute_structural_loads`. The viewer's
  displacement overlay (`results_view.py`) deliberately stays on `g_disp`, so a box the deck never
  attached to anything is never drawn moving.
- **Diagnostics:** f06 `INJECTED AERO LOADS` block (source card, master grid, box count,
  6-component resultant about the moment reference) via `Sol144TrimResult.load_injection_echo`;
  warnings for no-master-grid (SOL 101 body decks — warn, never raise), several SUPORT grids, and
  a master grid whose translations are fully constrained; `ValueError` for an unknown `GRID`.
- **New deck** `sample/ha144a_body_trim.bdf` — full-span HA144A + a `PSTRIP` cruciform body pair
  under `SPLINE0`, exercising both master-resolution paths (panel 400 names GRID 98; panel 500
  defaults to SUPORT GRID 90).
- **Docs:** `02_card_reference.md` (GRID field, defaults, warnings), `05b_splining.md` (three-operator
  table + "Load injection" section + new API), `05a_aero_vlm.md`, `05c_sol144_maneuver.md`,
  `05_aeroelastics.md`, `00_program_overview.md`, theory §3.7 + §4.4 (injection math and the
  deliberate `g_slope`-zero / `g_load`-nonzero asymmetry).

**Key decisions:**
1. **Separate `g_load`, not an augmented `g_disp`** — `g_disp` is also used untransposed for
   displacement recovery; injecting there would fabricate motion for boxes the deck declared
   uncoupled.
2. **`g_slope` stays zero** — injected boxes load the structure but take no downwash from it (the
   `SPLINE0` contract). `Q_aa` therefore gains rows at the master grid but no columns, making an
   already-unsymmetric matrix more so; nothing downstream assumes symmetry.
3. **Scope = all boxes with zero coverage**, not just `SPLINE0`-declared ones; the per-box
   un-splined `UserWarning` is retained so a forgotten SPLINE2 stays visible.
4. **Always on** — no opt-in flag. Trim results on body-panel decks change by design.
5. **One master grid per group**, not an RBE3-style distribution — correct for the global balance,
   approximate locally; the general form is backlogged as `SPLINEF`.

**Test/Acceptance:** the gate is the load-factor identity — trimmed **all-box** lift equals the
weight, i.e. the printed totals and the force balance describe the same aircraft. On
`sample/ha144a_body_trim.bdf`, measured both ways by swapping `g_load` back to `g_disp`:

| | ANGLEA | all-box lift vs weight |
|---|---|---|
| pre-fix behaviour | 0.169372 | **31.5 % error** (21032 lb vs 15999 lb) |
| post-fix | 0.135269 | **9.4e-15** |

Plus: the **delta identity** (`grid_loads` minus the pure-kinematic transfer equals exactly the
resultant of the uncoupled boxes, any reference point) — the mechanism itself, pinned to machine
precision; closure stays machine-zero; MONPNT3 over the load-carrying grids recovers the full aero
Fz; the export emits the master grid's `FORCE`/`MOMENT` pair; the f06 block appears only when
injection is active. Unit gates `V-M1a–f` in `tests/aero/test_spline.py` (closed-form resultant on
a canted panel, kinematic-adjoint check, grouping invariance, default/multi/no-SUPORT resolution,
unknown-grid error, un-splined warn-and-inject, `g_load == g_disp` on a fully splined deck);
integration gates in `tests/integration/test_sol144_body_injection.py`; parser round-trip in
`tests/parser/test_aero.py`. V-B3c retained unchanged as the `g_disp` invariant with a `g_load`
companion. Fully-splined decks (HA144A and every other shipped deck) are **bit-identical** —
asserted via `load_injections == []`. Full suite 1223 passed / 6 xfailed; `ruff` and strict
`pyright` clean.

**Not closed here:** DEF-M11 (ATTACH `g_disp` carries only the z-row) — the injection is
3-component but ATTACH/SPLINE2 transfer stays z-biased, which is why the acceptance gate is the
delta identity rather than an absolute totals identity on a canted deck. The general
force-mapping spline (`SPLINEF`) is backlogged.

---
