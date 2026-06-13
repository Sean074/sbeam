# Changelog

All notable changes to sbeam are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Post-Phase-1 additions built on top of v0.1.0. Will be released as v0.2.0 on Phase 2 completion.

### Removed

**Half-span / symmetry (AEROS SYMXZ/SYMXY) support removed — sbeam is full-span only (2026-06-12)**

The half-span symmetry-image capability — a 1970s computational economy no longer needed —
was removed. Every lifting surface is now meshed in full.

- **VLM kernel simplified.** Removed the `parity` parameter and the XZ-mirror image logic from
  `horseshoe_influence`, `build_ajj`, `trefftz_cdi`, and `solve_rigid_cl` (vlm.py), including the
  symmetric/antisymmetric image-bound branches, the mirror trailing-vortex loop, the
  `parity == -1` CL/CY/CDi special cases, and the half-vs-full-span reference-AR doubling
  heuristic. `AeroModel.parity` and the `parity` argument of `build_aero_model` are gone.
- **AE1 Step D fixed by construction.** Removing the `sym = 2` half-span force-doubling factor
  from `run_sol144_trim` eliminates the aero/inertia parity double-count that halved the HA144A
  trim. SC1 now trims to NASTRAN Listing 7-2 within ~2% on the full-span deck.
- **SYMXZ guard + migration aid.** `build_aero_model` now raises if `AEROS SYMXZ`/`SYMXY` ≠ 0,
  pointing at the new `sbeam.aero.mirror.mirror_halfspan()` utility, which unfolds a legacy
  half-span deck (GRID/CBAR/CONM2/RBAR/RBE2/CAERO1) to full-span about the XZ plane. The AEROS
  card still *parses* SYMXZ/SYMXY (the field layout is unchanged); only solving a non-zero model
  is rejected.
- **Viewer.** Removed the Symmetric/Antisymmetric/Full-span radio from the aero tab.
- **Decks & tests.** Half-span `sample/ha144a_sbeam.bdf` and its gate `test_ae1_keff_trim.py`
  removed; `sample/ha144a_fullspan_sbeam.bdf` + `test_ae1_fullspan.py` are now the sole HA144A
  trim gate (SC1 value + SC2 sign/flexible-increment coverage folded in). All VLM tests rebuilt
  on genuine full-span geometry; the antisymmetric and parity-image unit tests and the concluded
  A1 convergence diagnostics were removed.

### Fixed

**Backlog validation review — AE1 re-diagnosis corrected; R16–R22 closed (2026-06-12)**

Full validation pass over `docs/30_future/00_backlog.md` against the MSC HA144A reference
(Table 7-1 / Listing 7-2). No solver behaviour changed except the two NIT fixes below.

- **AE1 root cause re-diagnosed (CRITICAL).** The SC1/SC2 ANGLEA/ELEV trim gap is a `sym=2`
  aero/inertia parity double-count in `run_sol144_trim` (aero terms ×2 at
  sol144.py:795/822/833; inertial `M_ax` at :873–874 not doubled), **not** the flexible
  `q·Q_aa` increment. Forcing `sym=1` yields the correct trim (0.1727/0.4893 vs NASTRAN
  0.169191/0.492457) and 8000 lb lift; flexibility at q=40 is a 0.6% effect (Table 7-1),
  incapable of a 50% error. Rewrote the backlog Diagnosis, step sequence (lead = Step D
  parity fix, not Step C), Steps C/D/F/G, AE8, AE13 (V-AE1/V-AE3), and the V-AE1 acceptance.
  The actual `sym` code fix is left for a dedicated change (confirm the HA144A REFS
  convention first).
- **Full-span cross-check added (`sample/ha144a_fullspan_sbeam.bdf`).** Explicit 2× mirror of
  HA144A (both wings/canards, SYMXZ=0, fuselage mass doubled → 16000 lb, CG_x=17.18 matched).
  Ground truth with no symmetry assumption: uses a single-point ground (`SPC1 1246` at GRID 90
  + `SUPORT 35`) rather than the half-model's centreline symmetry SPCs, so symmetry EMERGES
  (antisymmetric centreline DOF = 1e-18, L/R wing tips identical). Passes the rigid-pitch
  spline check and trims to **SC1 0.1711/0.4908 (101%/100% of NASTRAN), lift 16000 lb**,
  independently confirming the parity diagnosis. It also REFINED the fix: `parity` is overloaded (it also selects the AIC
  symmetry image vortices, which are required), so the fix decouples the force-scale (`sym=1`)
  from the AIC parity — NOT simply `parity=0` (which removes the images and gives 0.302).
  Surfaced a SEPARATE, still-open flexible residual at SC2 (q=1200): corrected half (0.0049)
  and full-span (0.0032) both miss NASTRAN (0.0014) — Step G / AE8 territory, not parity.
- **Test-gate weaknesses documented:** `test_trim_lift` is non-discriminating (lift=8000 lb
  for both sym=1 and sym=2); SC2 ANGLEA passes at 140% of target under the shared
  `ATOL_ANGLEA=1e-3`. Flagged for per-target relative tolerances.
- **R21** fixed: `if spc_sid is not None:` guard before `check_spc_enforced_displacements`
  (`sbeam/solver/sol101.py:255`).
- **R22** fixed: public `build_f06_sol101_text` / `build_f06_sol103_text` aliases in
  `sbeam/results/f06_writer.py`; `sbeam/main.py` and `sbeam/viewer/app.py` import the public
  names instead of the private `_build_f06_*`.
- **R16, R17, R18, R19 removed** from the backlog (R16/R18 fixed by the prior doc
  restructure; R17/R19 misidentified — already present). New NIT **R23** logged for a
  residual `recover_bar_forces` doc-signature mismatch (`03_static_analysis.md:307`).
- **Backlog reframes** (still open, corrected): AE9 (subsonic multi-Mach; HA144A SC3 is
  supersonic/out-of-scope; add a supersonic guard, not a one-line fix), AE10 (dispatch needs
  a prebuilt AeroModel; case-control already whitelists SOL 144), AE11 (non-blocking for AE1;
  YAW latent), AE12 (PG-normal half re-diagnosed as **not a bug** — exact for n_x=0 incl.
  dihedral; DTOR/DTHZ-warning half kept), A5 (stale "case_control rejects SOL 144" claim),
  A7 (CM-convergence numbers retracted — ~50%/34% do not reproduce; ≤~1.9% measured).

**AE1 Step E — Moment-sign single-source helper + virtual-work consistency gate (2026-06-12)**

Closed the AE1 Step E increment and corrected its diagnosis. The gross pitching-moment
sign was already fixed in Step A; investigation showed the moment that drives the Schur
trim (the `g_disp` virtual-work path onto the SUPORT Ry DOF) was already sign- and
magnitude-correct, so Step E became a DRY refactor plus a permanent regression gate.

- `sbeam/solver/sol144.py`: new `_pitch_moment(f_box_vec, boxes, x_ref)` — single source
  for the nose-up-positive moment-arm convention `My = −ΣFz·(x_force − x_ref)` (¼-chord
  force point). Replaced the three hand-inlined copies in `_compute_aero_forces`,
  `_compute_rigid_derivs`, and the `run_sol144_trim` total-CM loop (latter keeps its
  `sym` parity factor at the call site). Behaviour-preserving — HA144A trim numbers are
  byte-identical (SC1 ANGLEA=0.085951, ELEV=0.244584).
- `sbeam/aero/vlm.py`: comment on `solve_rigid_cl.CM` cross-referencing the shared
  `−Σ(...)·(x−xref)` convention with `sol144._pitch_moment` (pressure form vs force form).
- `tests/aero/test_ae1_step_e_moment.py` (new): `TestStepEMomentConsistency` — for unit
  ANGLEA/ELEV on HA144A, asserts g_disp virtual-work Fz == direct Fz (1e-9), virtual-work
  moment about the SUPORT == `_pitch_moment` (1e-6 rel), and ANGLEA moment is nose-down.
  3 tests pass.
- **Re-diagnosis:** the residual SC1/SC2 ANGLEA/ELEV gap (e.g. ELEV 0.245 vs NASTRAN
  0.492) is the flexible `q·Q_aa` increment, **not** a moment-sign error (a direct rigid
  2×2 trim gives ELEV ≈ 0.795; the Schur flexible solve gives 0.245). The
  `test_ae1_keff_trim.py` value tests remain failing pending Steps C/D/G. Backlog updated:
  Step E removed, AE8 sign half marked resolved, action-plan/sequence/measured-state and
  "What not to do" notes corrected to point the ANGLEA/ELEV gap at Steps C/D/G.

**AE1 Step B — Spline kinematic correctness on swept SPLINE2 (B1–B4, 2026-06-12)**

Resolved three independent defects that together prevented `g_slope`/`g_disp` from
reproducing global basic-frame rigid-body modes on a swept SPLINE2. The HA144A wing,
under a global θ=1e-3 pitch about y, now returns uniform incidence +1.000e-3 (was
[−9.45e-02, +4.53e-02]). All 18 `TestGlobalRigidBody` (V-AE1b) tests pass; the full
non-V-AE1 suite holds at 238 passed.

- **B1 — RBAR-expanded recovery in the trim path.** Added `_expand_to_g(u_a, T,
  free_local, n_red)` to `sbeam/solver/sol144.py` and replaced the three
  direct-index scatters in `run_sol144_trim` and `_compute_restrained_derivs`
  (nominal + perturbed) with `displacements = T @ u_red`. RBAR slave DOFs now move
  with their masters before `g_slope @ displacements` is evaluated. The
  `_compute_restrained_derivs` signature changed from `(free_dofs, …, n_dofs)` to
  `(T, free_local, n_red, …)`.
- **B2 — Sample HA144A SET1 fixed to the elastic axis.**
  `sample/ha144a_sbeam.bdf` SPLINE2 1601 SET1 changed from `{99, 100, 111, 112,
  121, 122}` (fuselage centreline + RBAR-slave LE/TE stringers) to the EA-only
  `{100, 110, 120}` (wing-CBAR endpoints); SPLINE2 DTHX flipped −1 → +1 (attached)
  so torsion rides through the master Rx DOF with the corrected formula.
- **B3 — SPLINE2 SET1 collinearity validator.** `sbeam/aero/spline.py
  ::_build_spline2_block` now computes each SET1 grid's chord offset
  `Δ_i = (r_i − origin)·ŷ_spline` and raises `ValueError` when
  `max |Δ| > 5%` of the span range, naming the offending grids and their (x, y,
  s, Δ). Prevents silent Q_aa contamination from future off-EA SET1 layouts.
- **B3+ — Spline-math fix (multiplication-bending + corrected torsion).**
  `_build_spline2_block` now uses `w = −x̂[0]·(dh/ds)` for the bending /
  translation contribution (was `−(dh/ds)/x̂[0]`, self-consistent only on the
  V-AE2b along-spline-axis kinematic). Torsion uses
  `w_torsion = −ŷ[0]·x_comp·f_vals_slope` (was `x_comp·f_vals_slope`, correct
  only for unswept splines). Added matching torsion contribution to `g_disp`:
  `g_disp[3k+c] += x_comp·ζ_k·ẑ[c]·f_vals_force`. The `sweep_ok`
  gate is removed (multiplication is well-defined at `x̂[0]=0`). With the new
  formulas the attached (`DTHX=+1`) path reproduces all six basic-frame rigid-body
  modes exactly on planar wings.
- **B4 — V-AE1b gate added (`tests/aero/test_spline.py::TestGlobalRigidBody`).**
  For each of `{Tx, Ty, Tz, Rx, Ry, Rz}` applied to *every* grid (with lever-arm
  fill for rotations), asserts `g_slope·u_rb` and `g_disp·u_rb` (z-component at
  every box force_point) against analytic expectations. Tolerances: 1e-5 on
  HA144A (limited by 5-decimal coordinate input), 1e-12 on the math-exact
  rectangular fixture.
- The legacy V-AE2 swept-spline fixture was updated to the EA-only SET1 and
  `DTHX=+1` to align with the corrected spline; V-AE2a/b/c remain green as unit
  checks on the Hermite slope projection.

### Added

**Critical design review — aeroelastics, HA144A benchmark (2026-06-11)**
- Reviewed the full aeroelastic chain (`aero/`, `solver/sol144.py`) against MSC Nastran
  HA144A (Aeroelastic Analysis User's Guide Listing 7-2 / Table 7-1) and the ZAERO 9.2
  Theoretical Manual (trim Ch. 12, splines Ch. 6). Verified the VLM core (Biot–Savart
  kernel, symmetry image, Göthert PG) matches the NASTRAN rigid CZα to 4 significant
  figures once the swept lift-width defect is corrected; found 5 CRITICAL and 5 MAJOR
  defects in the integration/spline/trim layers (trim currently fails HA144A on both
  subcases and trims to −1g).
- `docs/30_future/00_backlog.md`: new "Code Review — 2026-06-11" section with findings
  AE1–AE13, measured-vs-reference table, and a 6-step correction plan with per-step
  verification targets; Phase A/B and Step 52 entries annotated with their open AE items.
- `docs/10_standard/05_aeroelastics.md`: "Known Defects" banner; corrected the false
  "skj calibrated to consume Γ" claim (AE2); documented MSC vs sbeam SPLINE2 DTHX
  semantics divergence (AE4c); swept-axis projection and Hermite slope-sign defects
  (AE4a/b); ¼-vs-¾-chord force application caveat (AE6); swept K-J lift-width caveat on
  the validated CL/CM claims (AE3); new Step 52 WIP status section for `run_sol144_trim`.
- `studies/_review_ha144a_check.py`: reproduction script — HA144A trim both subcases,
  rigid-body spline kinematics checks, force-transfer-point check, rigid-derivative
  cross-check against `solve_rigid_cl`.

**AE2 — Fixed j-set pressure unit: `ajj_inv_corr` now returns ΔCp, not Γ**
- `sbeam/aero/aero_model.py`: `build_aero_model` scales `ajj_inv_corr` rows by
  `2/chord_box` (physical boxes) immediately after the Prandtl–Glauert step, so that
  `ajj_inv_corr @ w` returns dimensionless ΔCp throughout. All downstream consumers
  (`build_fg`, `build_qaa`, `Q_ax`, `_compute_rigid_derivs`, `_compute_aero_forces`)
  are now unit-consistent with no caller changes.
- `sbeam/aero/corrections.py`: `apply_wt1` reference strip force changed from
  `Σ area·Γ` to `Σ area·2Γ/chord` (physical strip lift/q), so the WT1 correction ratio
  is computed against the correct physical reference. `apply_wt2` unchanged (WT2 target
  convention stays as VLM Γ — ratio cancellation makes it transparent).
- `sbeam/solver/sol144.py`: `run_sol144_trim` `total_cl`/`total_cm` now divide by
  `sref` (not `q·sref`) because `skj @ Cp` is force/q; `_compute_restrained_derivs`
  CZ/CMY denominators likewise drop the spurious `q`.
- `tests/aero/test_corrections.py`: 5 tests updated to assert against physical Cp
  quantities (skj-path CL round-trip, WKK force ratio, WT2 Cp output, WT1 physical
  strip-force round-trip and scaled variant).
- Verified: HA144A rigid CZα (ANGLEA) via `_compute_rigid_derivs` = 5.071, matching
  `solve_rigid_cl` CLα = 5.0709. Previously 6.339 (≈25% error). `total_cl` at SC1
  trim = −1.001; lift = −8011 lb ≈ −W (sign fixed by AE5, still open).

**AE5 + AE7 — Fixed RCSID-frame URDD transform and inertial trim columns**
- `sbeam/solver/sol144.py`: replaced `_build_urdd_load` with `_build_inertial_cols(bulk,
  all_labels, grid_index, suport_pos)` returning a full (n_g, n_labels) inertial sensitivity
  matrix M_ax (non-zero only for URDD columns). Translational URDD: `M[Tz_dof, col] = −m`
  per CONM2 and lumped CBAR half-mass. Rotational URDD: spin term `M[Ry_dof] = −I_diag`
  plus transport cross-product `F = −m·(α̂×r)` about `suport_pos`. M_ax_a (a-set) is now
  passed to both `_solve_trim_determined` and `_compute_restrained_derivs`, replacing bare
  `q·Q_ax` with `q·Q_ax + M_ax` throughout the Schur assembly.
- RCSID transform block in `run_sol144_trim` now handles partial URDD sets (e.g. only URDD3
  present without URDD1/2): assembles the full 3-vector with zeros for absent components,
  applies R_rcsid, writes back only present components. Previously required all three of
  URDD1/2/3 before applying the transform, causing the sign inversion to persist when only
  URDD3 was in `all_labels`.
- `tests/aero/test_trim_urdd.py` (new file): 10 tests — `TestUrddRcsidTransform` (2 unit),
  `TestInertialCols` (5 unit), `TestTrimSignAe5` (3 integration). V-AE3a gate:
  `total_cl > 0` for RCSID z-down 1g trim. All 10 pass; full suite 721 tests pass.

**AE4 + AE6 — Fixed SPLINE2 swept-axis kinematics and ¼-chord force point**
- `sbeam/aero/panel.py`: added `force_point` field to `AeroBox` — midpoint of the ¼-chord
  bound-vortex segment `(bound_a + bound_b) / 2`.
- `sbeam/aero/spline.py` (full rewrite of `_build_spline2_block`):
  - AE4(a): slope projection now divides by `x_hat[0]` (ZAERO §6.3: `w = −(dh/ds)/x̂₀`).
  - AE4(b): nodal-slope sign corrected: `(dh/ds)_i = −(ω·ŷ)_i`; bending g_slope gains
    `+(y_comp/x0)·dψ/ds`, bending g_disp changes to `−y_comp·ẑ·ψ(t_force)`.
  - AE4(c): `DTHX = −1.0` now correctly means "detach rotation DOF" (skip torsion
    coupling); `DTHX = 1.0` attaches; other values warn and treat as detached.
  - AE6: g_disp evaluated at `t_force = (force_point − origin)·x_hat` (¼-chord), not
    `t_slope = (colloc − origin)·x_hat` (¾-chord); g_slope unchanged at colloc.
  - `_build_attach_rows` lever arm changed from `box.colloc` to `box.force_point`.
- `sbeam/solver/sol144.py`: three `colloc[0]` → `force_point[0]` in moment arms
  (`_compute_aero_forces`, `_compute_rigid_derivs`, total CM loop).
- `tests/aero/test_spline.py`: new `TestSweptSplineRigidBody` class (V-AE2a/b/c) passing
  to 1e-12; `TestAttachRigidBodyGate.test_v_b3d_force_transfer_lever_arm` expected moment
  arm updated to use `force_point` (¼-chord at 0.25 ft, not colloc at 0.75 ft).
- All 711 tests pass.

**AE3 — Fixed Kutta-Joukowski lift-width projection for swept wings**
- `sbeam/aero/vlm.py`: `solve_rigid_cl` and `trefftz_cdi` now use the cross-flow projected
  width `sqrt(Δy² + Δz²)` as the spanwise width `dy` of each bound-vortex segment, instead
  of the 3-D Euclidean length `‖bound_b − bound_a‖`. This is required by the K-J theorem
  (F = ρ V∞ × Γ Δs; lift scales with Δy, not ‖Δs‖). The fix also corrects `chord_box`,
  `cl_section`, `CM`, `CDi`, and per-surface breakdowns, all of which derived from `dy`.
- `tests/aero/test_integration.py`: aligned inline `dy` formula to match production code.
- Verified: HA144A (Λ = 30°) rigid CLα = 5.07098 vs NASTRAN −CZα = 5.07097; CMα = −2.87093
  vs NASTRAN −2.871. Previously CLα = 5.757 (×1/cos30° = 1.155 overprediction).
  Unswept validation cases (BYU wing, AR=8 rectangle) are numerically unchanged.

**Step 51 — Trim card set parsing (AESTAT / AESURF / AELIST / TRIM / DIVERG / over-determined)**
- `sbeam/model/aero.py`: 8 new dataclasses — `Aestat`, `Aesurf`, `Aelist`, `Trim`, `Diverg`,
  `Trimvar`, `Trimobj`, `Trimcon`.
- `sbeam/model/bulk_data.py`: 8 new dict fields (`aestats`, `aesurfs`, `aelists`, `trims`,
  `divergs`, `trimvars`, `trimobjs`, `trimcons`).
- `sbeam/parser/bdf_reader.py`: 8 new handlers; dispatch branches for all new keywords;
  post-parse cross-reference validation (AESURF→AELIST, AELIST→CAERO1 box ranges, TRIM label
  refs); DOF-count diagnostic warns on fully-prescribed or over-determined-without-objective TRIM.
- `sbeam/parser/case_control.py`: `SubcaseControl` gains `trim_sid` and `diverg_sid`; parser
  handles `TRIM=` and `DIVERG=` case-control keywords; error message updated to include SOL 144.
- `docs/10_standard/02_card_reference.md`: field tables for AESTAT, AESURF, AELIST, TRIM,
  DIVERG, TRIMVAR, TRIMOBJ, TRIMCON; `TRIM=`/`DIVERG=` added to case-control keyword table.
- `docs/10_standard/05_aeroelastics.md`: updated supported-cards table; Step 51 section
  (data model, cross-reference rules, DOF-count diagnostic, over-determined trim design).

**Phase C — Aero stiffness assembly Q_aa + modal-truncation ROM (Step 50)**
- `sbeam/solver/sol144.py` new module: `run_aeroelastic_static(bulk, subcase, aero, q,
  use_rom, sol103_result)` solves `(K_aa − q·Q_aa)·u_a = q·f_g + f_struct`; recovers
  CBAR forces/stresses. Private helpers: `_build_qaa_aset` (g-set → a-set reduction via
  RBE3 + SPC, always-dense), `_solve_direct`, `_solve_rom` (modal-truncation ROM via
  `coupling.build_gaf`), `_mode_acceleration_recovery` (corrects mode-displacement with
  static flexibility residual using stored `k_aa_lu`).
- `sbeam/results/results.py`: `Sol144Result` dataclass (displacements, bar_forces,
  bar_stresses, q_aa, q, free_dofs, k_aa_lu, modal_coords, phi_free, k_hh, q_hh).
- `sbeam/parser/case_control.py`: SOL 144 added to `_SUPPORTED_SOLS`.
- `tests/aero/test_step50_qaa.py`: 13 V-C3 acceptance tests (all pass).
- `docs/10_standard/05_aeroelastics.md`: Phase C section (governing equation, coupling.py
  API, sol144.py API, Sol144Result fields, V-C3 acceptance criteria).

**Phase B — Force transfer & coupled smoke test (Step 49)**
- `compute_structural_loads(aero_model, q, alpha)` added to `sbeam/aero/aero_model.py`:
  wires the full rigid-aero → structural load path via
  `w_total = -(alpha·normal_z) + wg`, `gamma = ajj_inv_corr @ w_total`,
  `f_box = skj @ gamma`, `f_g = q * g_disp.T @ f_box`.
  Raises `ValueError` if `g_disp is None` (caller must supply `grid_index` to `build_aero_model`).
- BDF integration fixture `tests/integration/bdf/val_spline2_cantilever.bdf`:
  4-CBAR cantilever, 4-box CAERO1, SPLINE2 via CORD2R CID=1, full-span AEROS.
- `tests/integration/test_phase_b.py` (V-B2a–d): virtual-work force balance (< 1e-10),
  CL magnitude plausibility (< 2%), alpha=0 agreement with `build_fg` (< 1e-12),
  and `ValueError` guard. 194 total tests pass.

**Phase B — ATTACH rigid-body spline (Step 47)**
- `_build_attach_rows()` implemented in `sbeam/aero/spline.py`: rigid lever-arm coupling
  of a box group to a single master GRID via `ATTACH` card. Fills `g_slope`
  (`col_Rx = +1.0` torsion, `col_Ry = -1.0` pitch) and `g_disp` normal z-rows with
  lever-arm cross-product `(ω×r)_z = Rx·ry − Ry·rx`.
- ATTACH loop in `build_g_spline()` replaces Step 46 placeholder warning.
- `NotImplementedError` raised for `CID ≠ 0`; `ValueError` for unknown master GRID.
- V-B3 test class (4 tests) in `tests/aero/test_spline.py`: machine-precision rigid-body
  gate (Tz→0, Ry→-1) and force-transfer lever-arm check (Fz/Mx/My vs analytical).
  SPLINE0 zero-force and zero-slope verified alongside ATTACH. 20 total tests pass.

**Phase B — Structure ↔ Aero Splining (Steps 45–46)**
- `SET1` card parsed (Pattern B multi-continuation, same template as `SPC1`/`RBE2`);
  `Set1` dataclass added to `model/aero.py` and `BulkData`.
- `SPLINE2` card parsed (Pattern A with optional DTHX/DTHZ/USAGE continuation);
  `Spline2` dataclass with full field set including defaults (DZ=0.0, DTOR=1.0,
  DTHX=1.0, DTHZ=0.0, USAGE="BOTH"); cross-reference validation at end of
  `parse_bulk_data` (SETG → SET1, CAERO → CAERO1, SET1 grids → GRID).
- `Attach`, `Spline0`, `Spline1` stub dataclasses added; `SPLINE1` parser handler raises
  `NotImplementedError`; `ATTACH` and `SPLINE0` parse to their dataclasses (builders in Step 47).
- `BulkData` gains: `set1s`, `spline2s`, `attaches`, `spline0s`, `spline1s`.
- New module `sbeam/aero/spline.py` — `build_g_spline(bulk, boxes, grid_index)`:
  - Builds two CID-aware spline operators from SPLINE2 cards using `CubicHermiteSpline`
  - `g_slope` (n_box × 6·n_grid): maps structural g-set DOFs → per-box streamwise incidence
    for the VLM solve (consumed by `coupling.build_qaa`)
  - `g_disp` (3·n_box × 6·n_grid): maps structural g-set DOFs → per-box 3-D displacement
    for virtual-work force transfer back to structure (consumed by `coupling.build_fg`)
  - CID-aware projections via x_hat/y_hat/z_hat from CORD2R: correct for any spline axis
    orientation (standard NASTRAN SPLINE2 convention)
  - Unit-impulse Hermite approach: column-by-column fill using scipy phi_f / phi_d basis
    functions; exact for the cubic Hermite space
  - Coverage tracking: error on doubly-splined box; UserWarning on un-splined box and
    on >10% extrapolation beyond SET1 span range
- `AeroModel` gains `g_slope` and `g_disp` optional fields; `build_aero_model` accepts
  optional `grid_index` parameter and populates both operators when spline cards are present.
- 15 new tests in `tests/aero/test_spline.py`:
  - Parser round-trips and error cases for SET1 and SPLINE2
  - Operator shape validation
  - V-B1 rigid-body gate: uniform Tz → zero downwash (< 1e-12); uniform Ry → uniform
    downwash = 1.0 (< 1e-12); both verify partition-of-unity property of Hermite bases
  - Energy round-trip: `g_disp.T @ (Skj @ cp_unit)` Z-component equals total panel area

**Phase A — Prandtl–Glauert compressibility correction (A4)**
- `AEROS` card now accepts optional field 8 `MACH` (sbeam extension; default 0.0). Specifying
  a Mach number triggers the Göthert similarity correction: panel y,z coordinates are
  compressed by β = √(1−M²) before AIC assembly, and the inverted AIC is scaled by 1/β,
  giving the correct subsonic compressible pressure distribution (§2.8 of theory doc, Eq. 14).
  M = 0.0 gives bit-identical results to the incompressible solver; Mach is capped at 0.99.
- `solve_rigid_cl` and `build_aero_model` both accept `mach=` and apply the correction.
- 4 new tests in `TestPrandtlGlauert` verify identity at M=0, y-compression, CL increase
  bounded by 1/β, and the M=0.99 cap.

**Phase A — Steady VLM Aeroelastics (Steps 39–46)**
- `AEROS` card — reference geometry (`cref`, `bref`, `sref`) and symmetry flags (`symxz`,
  `symxy`); enforces CAERO1-without-AEROS validation at parse time.
- `CAERO1`, `PAERO1`, `AEFACT`, `W2GJ` cards — aerodynamic panel definition, box meshing
  (quarter-chord bound vortex / three-quarter-chord collocation), and geometric incidence input.
- `sbeam/aero/vlm.py` — steady horseshoe VLM: Biot-Savart kernel, AIC matrix assembly,
  symmetric (+1) and antisymmetric (-1) XZ-plane image vortices, `solve_rigid_cl` for
  rigid-wing CL/CM/CDi/e at a given alpha/beta; `trefftz_cdi` for Trefftz-plane induced drag
  coefficient (CDi) and Oswald span efficiency (e).
- `sbeam/aero/integration.py` — integration matrices `Skj` (force recovery), `Djk`
  (normalwash mapping), and baseline normalwash vector `w_g`.
- `sbeam/aero/corrections.py` — AIC correction tiers: diagonal box weight (Wkk), pressure
  correction (WT2), and strip force correction (WT1). LU-factored AIC inverse
  (`np.linalg.solve`) replaces prior SVD (`np.linalg.lstsq`), reducing build time approx. 25x on
  large panel models.
- `sbeam/aero/aero_model.py` — `AeroModel` container; `build_aero_model` factory.
- Sideslip angle beta: VTP/fin surfaces produce sideforce (CY) at non-zero beta; lift (CL/CM) and
  sideforce (CY) separated by surface normal in `solve_rigid_cl` result dict.
- Viewer Aero tab: 3D aerodynamic box mesh, per-panel Cp colour overlay, spanwise section-CL
  strip chart, optional corrected vs inviscid Cp overlay.
- `sample/val_vlm_rect_ar8.bdf` — rectangular AR=8 validation case.
- `sample/val_vlm_byu_wing.bdf` — AVL-validated AR-7.5 tapered/swept benchmark; CL within
  0.16%, CM within 0.25% of AVL.

**BDF cards**
- `CORD2R` — user-defined rectangular coordinate systems for grid input positions (CP),
  result output frames (CD), load directions, and CONM2 offset/inertia. Chained RID
  references supported. All internal computation remains in global CID 0.
- `GRAV` — uniform body acceleration applied to all mass-bearing DOFs; works with CBAR
  distributed mass and CONM2 point masses; combinable via LOAD card; echoed in f06 OLOAD
  output.
- `RBE2` — rigid element: all dependent DOFs (CM string) at each GM grid are set equal to
  the corresponding DOF at the independent grid GN. Displayed as solid red lines in the viewer.
- `CBUSH` — generalised spring-damper element with up to 6 independent stiffness values
  (K1–K6 via PBUSH). Grounded elements (GB blank) supported. Displayed as a spring-coil
  polyline in the viewer. CBUSH element forces recovered and written to f06 under SOL 101.
- `RBAR` — rigid bar element with full lever-arm kinematics: translations at the dependent
  end (GB) include the cross-product contribution `θ_GA × d` where `d = r_GB − r_GA`.
  Displayed as solid purple lines in the viewer.
- `CONM2` offset and inertia tensor fully verified: 3×3 inertia tensor (I11–I33), CID-frame
  offset vector (X1/X2/X3) rotated to global via `R @ r_cid`, and parallel-axis theorem
  applied in the mass matrix. GPWG and viewer geometry corrected to apply the same CID→global
  transform when computing CG position and offset line.

**Viewer**
- Case Control UI redesign: separate Executive Control and Subcases sections; SOL-dependent
  output request checkboxes (only fields relevant to the active SOL are shown); collapsed
  Advanced expander for INCLUDE path; Download BDF button with inline BDF preview; immutable
  "Loaded BDF" snapshot shown in a read-only expander when a run file is uploaded.
- GRAV load direction visualised as a scaled arrow cone at the model centroid.
- CBUSH rendered as spring-coil polyline; RBE2 as solid red lines; RBAR as solid purple lines.

**Infrastructure**
- GitHub Actions CI pipeline: `pytest` + `ruff` lint on every push and PR to `main`;
  matrix covers Python 3.9, 3.11, 3.12.
- `pytest-cov` coverage measurement with branch coverage; explicit 85% floor gate command
  for `solver/`, `assembly/`, and `parser/` modules.
- AppTest end-to-end viewer tests covering the full SOL 101 and SOL 103 render+run flows.
- `docs/10_standard/02_card_reference.md` — field-level BDF card reference for all 17 implemented bulk
  data cards and all case control keywords.

### Changed
- **Documentation reorganised** into four numbered sections under `docs/` by document type:
  `10_standard/` (code standard), `20_theory/` (theory & worked examples), `30_future/`
  (backlog, plans, design proposals), and `40_history/` (completed-development record and
  archive). Added `docs/00_INDEX.md` as the navigation entry point. The root planning files
  (`development_plan_bugs_todo.md`, `static_aero_plan.md`, `static_aero_plan_zaero_review.md`)
  moved into `docs/30_future/`; the redundant root `todo.md` was merged into the backlog and
  removed. All internal cross-references updated.

### Fixed

**Phase A fixes**
- **A2/A3 — AEROS reference geometry and moment reference point:** `solve_rigid_cl` now
  uses AEROS `sref`/`cref` for CL/CM normalisation; per-surface classification separates
  lift surfaces (contribute to CL/CM) from sideforce surfaces (contribute to CY); moment
  reference `xref` parameter added (default 0.0).
- **A9 — CM moment arm corrected from three-quarter-chord to quarter-chord:** pitching-moment
  arm changed from the three-quarter-chord collocation point to the quarter-chord bound-vortex
  location where the Kutta-Joukowski force acts. Error was mesh-dependent (bias = CL * half-box-chord /
  c_ref, vanishing as NCHORD tends to infinity). CM now matches AVL to 0.25% on the BYU AR-7.5 benchmark.
- **A1 confirmed non-defect:** VLM lift-slope deficit (A1) validated against BYU
  VortexLattice.jl (AVL-validated); sbeam tracks the peer code to a constant 0.16% offset at
  every spanwise resolution. Deficit was an artefact of comparing to lifting-line upper bounds.

**Code review fixes**
- **C-1 — SOL 103 generalised mass hard-coded:** f06 GENERALIZED MASS column was always
  written as `1.0`. Now computed as `phi^T M phi` per mode. Correct (1.0) for `norm=MASS`;
  non-trivial for `norm=MAX`. `Sol103Result.generalized_masses` field added.
- **R13 — EIGRL V1/V2 frequency bounds:** V1/V2 were parsed and stored but silently ignored.
  `solve_modes` now emits a `UserWarning`; `docs/10_standard/04_modal_analysis.md` corrected to state
  that V1/V2 filtering is not implemented; use the `ND` field to limit mode count.
- **R14 — MAT1 G derived from isotropic relationship:** G was silently stored as 0.0 when
  the G field was blank, zeroing torsional stiffness. Now derived as `G = E / (2(1+nu))` when
  G is blank and both E and nu are non-zero. Supplied G always takes precedence.
- **R15 — SPC1 multi-continuation grids:** only the first continuation line was consumed;
  grids on subsequent lines were silently dropped. Now accumulates all continuation lines using
  the same loop pattern as RBE2/RBE3.
- **R10 — RBE3 lever-arm limitation documented:** block comment added in `assembly/rbe3.py`;
  "Known limitation" paragraph added to `docs/10_standard/01_beam_model.md` directing users to RBAR for
  kinematically exact rigid connections with offset.

**Existing fixes (Phase 1 bugs)**
- **Case control UI subcase export (B1):** Per-subcase field values (LOAD, SPC, output
  flags) now read from `st.session_state` after form submission, not from the pre-submission
  dict. Eliminates stale-value export when multiple subcases are defined.
- **Multi-subcase solver (B3):** `run_sol101` and `run_sol103` previously silently used only
  the first subcase. Solvers now accept a single `SubcaseControl` argument; the viewer loops
  over all subcases and stores results as `dict[subcase_id, result]`; the results panel shows
  a Subcase selector when more than one result is present.
- **Deformed shape hover (B2):** Hover tooltip on deformed nodes now shows raw physical
  displacements (Tx, Ty, Tz) instead of scaled plot coordinates.
- **CONM2 CG in GPWG and viewer:** CG marker and offset line for CONM2 with CID not equal to 0 now
  correctly apply the CID-to-global rotation before adding the offset to the grid position.
- **CBAR zero-length guard:** `transform_matrix` raises `ValueError` when GA and GB are
  coincident, matching the existing guard for CBUSH.
- **SPC reaction recovery with body loads (GRAV):** Reactions now computed as
  `R = K[spc,:] @ u - f[spc]` so that forces applied at constrained DOFs (which contribute
  to equilibrium but produce zero displacement) are correctly included in the reaction sum.

---

## [0.1.0] — Phase 1 Complete

Initial release: SOL 101 static analysis and SOL 103 normal modes for Euler-Bernoulli beam
models in NASTRAN BDF input format.

### Added

**BDF parser**
- Free-field and fixed-field BDF line parsing.
- Bulk data cards: `GRID`, `CBAR` (with orientation vector and pin releases PA/PB), `PLOTEL`,
  `CONM2` (point mass), `PBAR`, `MAT1`, `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `EIGRL`.
- Case control section: `SOL`, `TITLE`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `DISPLACEMENT`,
  `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `BEGIN BULK`, `ENDDATA`.
- `INCLUDE` statement for separating bulk data from case control.
- `parse_bdf(filepath)` — reads a full run file (case control + bulk data via INCLUDE).
- `parse_bulk_file(filepath)` — reads a bulk-data-only `.dat` or `.bdf` file.
- Validation: duplicate GIDs, missing PIDs/GIDs, invalid DOF strings all raise `ValueError`;
  unknown cards issue a warning and are skipped.

**SOL 101 — Static Analysis**
- 12×12 Euler-Bernoulli local element stiffness matrix with coordinate transformation.
- Global stiffness assembly from all CBAR elements.
- Load vector assembly from `FORCE`, `MOMENT`, and `LOAD` combination cards.
- SPC constraint application by DOF elimination.
- Direct solve via `scipy.linalg.solve`; singular matrix raises `ValueError` identifying
  unconstrained DOFs.
- CBAR end forces/moments and stresses at PBAR recovery points C/D/E/F recovered in element
  local frame.
- SPC reaction forces recovered.
- Verified: cantilever tip deflection `PL³/3EI` < 0.1%; simply-supported mid-span deflection
  `PL³/48EI` < 0.1%; fixed-end moment `PL` < 0.1%; reactions sum to applied load < 0.1%;
  cantilever tip torque `θ_x = TL/GJ` < 0.1%.

**SOL 103 — Normal Modes**
- 12×12 consistent mass matrix per CBAR element; CONM2 point mass assembled into global
  mass matrix.
- Generalised eigenvalue solve via `scipy.linalg.eigh`; EIGRL frequency range and mode
  count limits applied.
- MASS and MAX normalisation modes.
- Verified: cantilever f₁ = `(1.875²/2π)√(EI/ρAL⁴)` < 1%; free-free first 6 modes
  < 1×10⁻⁴ Hz; simply-supported f₁ = `(π²/2πL²)√(EI/ρA)` < 1%.

**CBAR pin releases**
- PA/PB DOF release flags zero the released rows/columns in the local stiffness matrix
  before transformation, enabling pinned-end connections and simply-supported models.

**GPWG — Mass and CG**
- Total structural mass and centre of gravity computed from CBAR distributed mass (via
  consistent mass matrix diagonal) and CONM2 point masses.

**f06 output**
- SOL 101: applied load echo, nodal displacements, SPC reactions, CBAR end forces/moments,
  CBAR stresses at recovery points — NASTRAN-compatible column format.
- SOL 103: natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions.
- Displacement and mode-shape output rotated into each grid's CD output frame.

**Streamlit viewer**
- 3D Plotly model display: GRID nodes, CBAR beam lines, PLOTEL dashed lines, RBE3 dashed
  cyan, CONM2 markers.
- Click-to-select grid/element with details panel.
- Tabbed properties tables: Grids, Elements, Properties, Materials, Loads, Constraints.
- GPWG summary panel.
- Case control form: SOL selection, TITLE, subcase LOAD/SPC assignment, METHOD (EIGRL),
  output request checkboxes; BDF export with INCLUDE.
- Run Analysis button: calls solver in-process; errors shown as banners.
- SOL 101 results: deformed shape overlay with scale factor slider; displacement, reaction,
  bar force, and stress tables.
- SOL 103 results: mode selector; animated mode shape cycling ±maximum; frequency display;
  modal mass fraction bar chart.
- Handles both bulk-data-only files and full run files on upload.

**Sample model**
- `sample/simple_beam.dat` — 10 m steel cantilever, 5 CBAR elements, SI units.

**Documentation**
- `docs/10_standard/00_program_overview.md` — developer and user guide; module structure; coding standards; testing.
- `docs/10_standard/01_beam_model.md` — BDF card reference; data model.
- `docs/10_standard/03_static_analysis.md` — SOL 101 algorithm; stiffness matrix derivation; load assembly.
- `docs/10_standard/04_modal_analysis.md` — SOL 103 algorithm; mass matrix derivation; eigenvalue solution.
- `docs/10_standard/06_viewer.md` — viewer architecture; session state; Plotly figure structure.
- `docs/20_theory/00_beam_methods.ipynb` — Euler-Bernoulli theory; stiffness and mass matrix derivations;
  coordinate transformation; eigenvalue solution.
