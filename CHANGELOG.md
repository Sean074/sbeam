# Changelog

All notable changes to sbeam are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Post-Phase-1 additions built on top of v0.1.0. Will be released as v0.2.0 on Phase 2 completion.

### Added

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
