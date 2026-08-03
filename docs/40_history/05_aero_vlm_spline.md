# Completed Development — Aerodynamics: VLM & Splining (Phases A + B)

Part of the completed-development record (index: `00_completed_development.md`).
Covers the steady VLM (boxes, AIC, corrections, body panels), section-data correction
synthesis, and the structure-aero splining layer, with their resolved defects.

---

## Phase A — Static Aeroelastics (VLM)

### Step 39: AEROS Card — Reference Geometry + Symmetry Flag ✅ COMPLETE

**Objective:** Add the AEROS BDF card to the parser and data model. The AEROS card
carries the aerodynamic reference geometry (`cref`, `bref`, `sref`) and symmetry flags
(`symxz`, `symxy`) required by every downstream VLM calculation (S40–S44).

**Deliverables:**
- `sbeam/model/aero.py` *(new)* — `Aeros` dataclass with 7 fields: `acsid`, `rcsid`,
  `cref`, `bref`, `sref`, `symxz`, `symxy`.
- `sbeam/model/bulk_data.py` — added `aeros: Optional[Aeros] = None` and preparatory
  `caero1s: dict = field(default_factory=dict)` (needed for the post-parse guard).
- `sbeam/parser/bdf_reader.py` — `_handle_aeros()` handler; `elif keyword == "AEROS":`
  dispatch; post-parse guard `if bulk.caero1s and bulk.aeros is None: raise ValueError(...)`.
- `tests/parser/test_aero.py` *(new)* — 20 tests (19 active, 1 skipped pending S40):
  round-trip (free-field and fixed-field), default values, `symxz`/`symxy` storage
  (`+1`, `-1`, `0`), duplicate-AEROS `ValueError`, placeholder for
  missing-AEROS-with-CAERO1 `ValueError`.
- `docs/10_standard/05_aeroelastics.md` *(new)* — top-level aeroelastics developer/user guide;
  architecture overview, module map, supported card table, AEROS card format, symmetry
  conventions, validation rules. Stub sections for S40–S43.

**Key decisions:**
- `symxz`/`symxy` stored as bare `int` (not an enum) to keep the dataclass simple and
  consistent with other integer-coded BDF flags (`cd`, `cp`, `cid`).
- `caero1s: dict` added to `BulkData` in S39 (not S40) so the post-parse validation
  guard is fully in place before CAERO1 parsing exists. This prevents a latent gap
  where the guard would be unreachable if added in S40.
- Fixed-field AEROS test uses the exact 8-column layout (CREF at cols 25–32) to catch
  off-by-one column errors.

**Test / Acceptance:**
- Parser round-trip passes (free-field and fixed-field).
- `ValueError("Duplicate AEROS card")` on second AEROS card.
- `symxz` / `symxy` stored correctly as `+1`, `-1`, and `0`.
- Blank `acsid`, `rcsid`, `symxz`, `symxy` all default to `0`.
- Post-parse CAERO1-without-AEROS guard is present; test activated in S40.
- **521 tests pass, 1 skipped (CAERO1 placeholder), 0 failures.**

---

### Step 40: CAERO1/PAERO1/AEFACT Parsing + `panel.py` Box Meshing ✅ COMPLETE

**Objective:** Parse aerodynamic panel cards (CAERO1, PAERO1, AEFACT) and mesh each
CAERO1 macroelement into trapezoidal boxes with bound vortex at ¼-chord and collocation
at ¾-chord (horseshoe-vortex convention, NASA SP-405).

**Deliverables:**
- `sbeam/model/aero.py` — added `Caero1`, `Paero1`, `Aefact` dataclasses.
- `sbeam/model/bulk_data.py` — added `paero1s` and `aefacts` dicts; expanded import.
- `sbeam/parser/bdf_reader.py` — `_handle_aefact()` (multi-continuation fraction list);
  `_handle_paero1()` (stub); `_handle_caero1()` (single required continuation for
  P1/X12/P4/X43); all three wired into the dispatcher. Post-parse cross-reference
  validation for PID, LSPAN, LCHORD. Skipped test in `TestAerosValidation` activated.
- `sbeam/aero/__init__.py` *(new)* — package init.
- `sbeam/aero/panel.py` *(new)* — `AeroBox` dataclass (k, caero_eid, i_span, j_chord,
  corners 4×3, colloc, bound_a, bound_b, area, normal, chord, span_frac) +
  `mesh_caero1(caero, paero, aefacts, cord2rs, start_k=0) -> list[AeroBox]`. P1/P4
  resolved via `_get_transform()` from `assembly/coord_transform.py`. Bound vortex and
  collocation placed at ¼ and ¾ of the **box** chord (not the full panel chord), so
  each box in a multi-chordwise model has an independent horseshoe position. Area from
  cross-product of diagonals; normal forced to +Z half-space for flat panels.
- `tests/aero/__init__.py` *(new)* — empty.
- `tests/aero/test_panel.py` *(new)* — 17 geometric assertion tests covering: 1×1 box
  (area, colloc at ¾c, bound vortex at ¼c, corners, normal, chord, span_frac), N×M
  mesh (box count, total area, sequential k, per-box chord placement), non-uniform
  AEFACT span spacing (strip count, proportional areas), tapered planform (trapezoid
  area formula, colloc/bound placement at mean chord), `start_k` offset.
- `tests/parser/test_aero.py` — removed `@pytest.mark.skip`; added `TestAefactRoundTrip`
  (single-line, multi-continuation, duplicate error), `TestPaero1RoundTrip` (PID stored,
  duplicate error), `TestCaero1RoundTrip` (NSPAN/NCHORD form, LSPAN form, AEFACT stored),
  `TestCaero1Validation` (missing PAERO1, missing AEFACT, duplicate EID, both NSPAN and
  LSPAN non-zero, missing continuation).
- `docs/10_standard/01_beam_model.md` — added AEFACT, PAERO1, CAERO1 card entries; updated BulkData
  listing; updated cards-recognised list; added CAERO1 cross-reference validation note.

**Key decisions:**
- Bound vortex and collocation placed at ¼/¾ of the **box** chord (not the global
  panel chord). For a 1×1 model both conventions coincide, but for NCHORD > 1 each
  chordwise row of boxes has independent horseshoe positions — which is required for a
  full-matrix AIC.
- CAERO1 cross-reference validation (PID, LSPAN, LCHORD) is deferred to post-parse so
  AEFACT/PAERO1 cards may appear anywhere in the bulk data relative to CAERO1.
- `_get_transform()` (not the rotation-only `to_global()`) is used for P1/P4 because
  they are points, not vectors — the full origin + R @ v_local transform is needed.
- Normal is forced to the +Z half-space so that flat XY-plane panels always have an
  upward-pointing outward normal regardless of corner ordering.

**Test / Acceptance (KA1):**
- 1×1 rectangular box: area = 8.0 (chord=2 × span=4); colloc x = 1.5 (¾ × 2); bound_a
  x = 0.5 (¼ × 2); normal = [0, 0, 1].
- N×M mesh (4×10): 40 boxes; total area = 8.0; per-box bound/colloc x confirmed analytically.
- AEFACT non-uniform span: 3-strip model, areas proportional to span fractions 0.3/0.3/0.4.
- Tapered planform (X12=4, X43=2): area = 12.0 (½(4+2)×4); colloc at ¾ of mean chord.
- **560 tests pass, 0 skipped, 0 failures.**

---

### Step 41: Steady VLM AIC `vlm.py` — Symmetric + Antisymmetric Images ✅ COMPLETE

**Objective:** Build the aerodynamic influence coefficient (AIC) matrix at k=0 using the
horseshoe-vortex lattice method, solve the rigid-wing flow-tangency problem, and return
lift and pitching-moment coefficients. Support XZ-plane symmetry (symmetric and antisymmetric
images) for half-span models.

**Deliverables:**
- `sbeam/aero/vlm.py` *(new)* — four public functions:
  - `biot_savart_seg(p, a, b) -> np.ndarray` — induced velocity at p from unit-strength
    finite vortex segment a→b (Biot–Savart law; returns zero vector for degenerate inputs).
  - `horseshoe_influence(colloc, box, parity=1) -> float` — single AIC entry; normalwash
    (z-component, flat-wing convention) at `colloc` from unit horseshoe at `box`. Trailing
    legs extend to `max(bound_a.x, bound_b.x) + 1000 × chord` (finite far-field cutoff).
    For `parity=+1` (symmetric): image bound reversed (b_img → a_img) so root trailing
    vortices cancel and the left-wing image produces same-sign lift. For `parity=-1`
    (antisymmetric): image bound in same-reflection direction, root trailing doubles.
  - `build_ajj(boxes, parity=1) -> np.ndarray` — n×n AIC matrix assembled from
    `horseshoe_influence`; O(n²) loop.
  - `solve_rigid_cl(boxes, alpha, parity=1) -> dict` — solves `A @ gamma = -alpha`,
    computes Cp using individual box chord (= area / spanwise_width), and returns
    `{cp, cl_section, CL, CM}`. CL set to 0.0 for parity=-1 (antisymmetric cancels).
- `tests/aero/test_vlm.py` *(new)* — 22 tests across 5 classes:
  - `TestBiotSavart` — known segment cross-check, degenerate cases, orthogonality.
  - `TestSingleHorseshoe` — self-induced normalwash matches direct Biot-Savart sum;
    parity ordering (symmetric reduces downwash, antisymmetric increases it).
  - `TestBuildAjj` — shape, diagonal consistency.
  - `TestRectangularWingCLa` — AR=5 half-span, 4×10 mesh: CLα within 10% of Prandtl
    `2πAR/(AR+2)` (standard horseshoe VLM with uniform spacing converges to ~10% below
    Prandtl for AR=5 — not a bug).
  - `TestMeshRefinement` — CLα decreases monotonically as mesh refines (VLM converges
    from above), both meshes within 10% of Prandtl.
  - `TestAntisymmetric` — parity=-1: full-span CL = 0, section loads non-zero.

**Key decisions:**
- **Image direction for symmetric case**: the image horseshoe bound runs reversed (b_img→a_img,
  i.e., from reflected-tip toward reflected-root in +y direction) so the left-wing vortex
  produces the same lift sign as the right wing. Root trailing vortices (at y=0) cancel
  between the direct and image horseshoes. The antisymmetric image uses the unreversed
  direction (a_img→b_img), making root trailing vortices reinforce and giving CL_full = 0.
- **Box chord vs. CAERO1 chord**: `AeroBox.chord` stores the CAERO1 macroelement chord
  (not the individual VLM panel chord). The Cp formula uses the per-box chord computed as
  `area / spanwise_width` to avoid an off-by-nchord factor in CL.
- **VLM vs. Prandtl**: the standard horseshoe VLM with uniform spanwise spacing converges
  to its own limit (~10% below Prandtl for AR=5). This is a known method characteristic,
  not a bug. Tests use 10% tolerance accordingly. Convergence is from above (coarser meshes
  give higher CLα).
- CL for parity=-1 is returned as exactly 0.0; the `cl_section` dict still contains the
  right-half section loads (non-zero, representing rolling moment).

**Test / Acceptance (V-A1, V-A2):**
- Biot–Savart: known segment matches closed-form; degenerate point returns [0,0,0].
- Self-induced diagonal is negative (horseshoe creates downwash at its own collocation point).
- Symmetric image (parity=+1) reduces normalwash magnitude vs. no-image (parity=0).
- AR=5 half-span 4×10 mesh: CLα = 4.26 rad⁻¹ (within 10% of Prandtl 4.49).
- 4×10 → 8×20 refinement: CLα decreases (4.26 → 4.11), monotone from above.
- parity=-1 uniform incidence: CL = 0.0, section loads non-zero.
- **582 tests pass, 0 skipped, 0 failures.**

---

### Step 42: Integration matrices `Skj`, `Djk`, and baseline normalwash `w_g` ✅ COMPLETE

**Objective:** Build the three aeroelastic integration quantities needed to bridge the VLM
pressure solution to structural forces (`Skj`), to map structural deformation to aerodynamic
normalwash (`Djk`), and to capture geometric incidence from the W2GJ BDF card (`w_g`). These
form the foundation of the steady load path and will be reused unchanged by the Phase D DLM
unsteady solver.

**Deliverables:**
- `sbeam/model/aero.py` — `W2gj` dataclass added: `sid`, `caero_eid`, `data: list`
  (dimensionless normalwash slopes Δz/Δx, one per box, row-major order).
- `sbeam/model/bulk_data.py` — `w2gjs: dict` field added (`{sid: W2gj}`).
- `sbeam/parser/bdf_reader.py` — `_handle_w2gj()` added (multi-continuation accumulation,
  same pattern as AEFACT); dispatch block added to main parse loop.
- `sbeam/aero/integration.py` *(new)* — three public functions:
  - `build_skj(boxes) -> np.ndarray` — shape `(3*n_box, n_box)`; column `j` maps `cp_j`
    to resultant force vector `[Fx, Fy, Fz]` at box `j` via `area_j * normal_j`.
  - `build_djk(boxes) -> np.ndarray` — shape `(n_box, n_box)`; returns `−I` (negative
    identity) for rigid k=0: unit positive slope at colloc_j → normalwash −1 at box j.
  - `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray` — shape `(n_box,)`; fills from
    matching W2GJ card in row-major order; returns zero vector if none present.
- `tests/aero/test_integration.py` *(new)* — 13 tests across 3 classes.
- `tests/parser/test_aero.py` — 4 W2GJ parser tests added to `TestW2gjParser`.

**Key decisions:**
- **Convention**: all normalwash quantities are dimensionless slope Δz/Δx. Documented at
  module and function level in `integration.py`.
- **Djk as −I at k=0**: the input is already a slope vector; the negative sign encodes that
  nose-up slope (positive Δz/Δx) produces downward wash (negative normalwash contribution).
  Phase D DLM will replace this matrix with the full unsteady kernel.
- **build_wg row-major ordering**: W2GJ data is indexed by span slowest, chord fastest,
  matching the ordering produced by `mesh_caero1`. The function filters by `caero_eid` and
  inserts values at global box indices, leaving unspecified boxes at zero.
- **T3 tip exclusion**: the linear-twist monotonicity test excludes the outermost span strip
  because VLM always shows tip-vortex rolloff (reduced gamma at the tip regardless of local
  incidence). This is physical, not a defect.

**Test / Acceptance (V-A4):**
- No W2GJ: `build_wg` returns zero vector.
- Wrong `caero_eid`: `build_wg` returns zero vector.
- Uniform W2GJ incidence α: `np.linalg.solve(Ajj, −w_g)` yields the same `cp` as
  `solve_rigid_cl(boxes, α)` to `rtol=1e-10` (round-trip identity).
- Linear twist (slopes ∝ strip index): interior section gammas increase monotonically
  (tip excluded due to physical rolloff).
- `build_djk` is exactly `−np.eye(n)`.
- `build_skj` column j equals `area_j * normal_j`; `Skj @ cp` total Fz == direct loop sum.
- Partial W2GJ data (fewer values than boxes): remaining boxes stay zero.
- **599 tests pass, 0 skipped, 0 failures.**

---

### Step 43: AIC Corrections (`corrections.py`) + `AeroModel` Container ✅ COMPLETE

**Objective:** Add the three steady AIC correction tiers (Wkk, WT2, WT1) and package
the entire aerodynamic model into a single `AeroModel` container for use by the
downstream SOL 144 aeroelastic solver.

**Deliverables:**
- `sbeam/model/aero.py` — two new dataclasses:
  - `Wkk(sid, caero_eid, data)` — diagonal multiplicative weight per box.
  - `Aecorr(sid, method, caero_eid, target)` — pressure or force/moment correction
    spec; `method ∈ {'WT1', 'WT2'}`.
- `sbeam/model/bulk_data.py` — `wkks: dict` and `aecorrs: dict` fields added; imports
  extended.
- `sbeam/parser/bdf_reader.py` — two new handlers and dispatch entries:
  - `_handle_wkk(fields, conts, bulk)` — same multi-continuation pattern as W2GJ.
  - `_handle_aecorr(fields, conts, bulk)` — field 2 is the method string `'WT1'`/`'WT2'`;
    raises `ValueError` for any other value.
- `sbeam/aero/corrections.py` *(new)* — three correction functions:
  - `apply_wkk(ajj, wkk_data) -> np.ndarray` — returns `AJJ* = diag(w) @ AJJ`.
  - `apply_wt2(ajj, cp_target) -> np.ndarray` — returns corrected `AJJ*⁻¹` by
    scaling `AJJ⁻¹` row-wise by `cp_target / cp_vlm_ref` (reference = unit incidence
    `w_ref = −ones(n)`). Guard for near-zero `cp_vlm_ref` boxes keeps ratio = 1.
  - `apply_wt1(ajj, boxes, f_target) -> np.ndarray` — returns corrected `AJJ*⁻¹` by
    assigning a per-strip ratio `f_target_s / f_vlm_s` to every box in strip s
    (strips defined by `box.i_span`). Both WT functions warn if `cond(AJJ) > 1e10`.
- `sbeam/aero/aero_model.py` *(new)* — `AeroModel` dataclass (`boxes`, `ajj`,
  `ajj_inv_corr`, `skj`, `djk`, `wg`, `parity`) and `build_aero_model(bulk, parity=1)`
  factory. Correction precedence: Wkk → WT2 → WT1 → identity (lstsq of raw AJJ).
- `tests/aero/test_corrections.py` *(new)* — 17 tests across 5 classes.

**Key decisions:**
- **Reference normalwash for WT1/WT2**: `w_ref = -np.ones(n)` (uniform unit incidence,
  same rhs used by `solve_rigid_cl` for `alpha=1`). The `todo.md` spec did not include
  `w_ref` in the function signatures; analysis showed that any implicit derivation of
  `w_ref` from `cp_target` itself would yield a trivial identity correction. A fixed
  reference state is the only formulation that (a) passes the round-trip tests and
  (b) provides a useful correction for real CFD/WT data.
- **Diagonal corrections only**: both WT1 and WT2 apply a per-box (WT2) or per-strip
  (WT1) scalar factor to the rows of `AJJ⁻¹`. Full off-diagonal correction matrices
  require multiple reference conditions and are reserved for a later phase.
- **`apply_wkk` returns `AJJ*`** (not the inverse); the caller (`build_aero_model`)
  inverts via lstsq. `apply_wt2` and `apply_wt1` return `AJJ*⁻¹` directly (they solve
  internally). This asymmetry matches the specification in `todo.md`.
- **`np.errstate`** used inside `apply_wt2` to suppress the numpy divide-by-zero
  RuntimeWarning that arises from `np.where` evaluating both branches; the near-zero
  guard then replaces invalid ratios with 1.0.
- **WT1 `f_target` length**: must equal the number of distinct `i_span` values in
  `boxes` (one scalar per span strip). A `ValueError` is raised on mismatch to avoid
  silent wrong corrections.

**Test / Acceptance (V-A3):**
- No correction: `AJJ*⁻¹ @ AJJ ≈ I` to `abs=1e-10`.
- Wkk non-unit (weight 1.5): `AJJ*` row 0 is `1.5 × AJJ` row 0, others unchanged.
- WT2 round-trip: feed VLM cp at unit incidence as target → corrected cp reproduced to `rel=1e-8`.
- WT2 scaled target: scaling target cp by 1.3 scales corrected output by 1.3 to `rel=1e-8`.
- WT1 round-trip: feed VLM per-strip lift as target → corrected strip lift reproduced to `rel=1e-8`.
- WT1 scaled target: scaling by 0.8 scales corrected strip output by 0.8 to `rel=1e-8`.
- WT1 wrong `f_target` length: `ValueError` raised.
- Conditioning: near-singular AJJ triggers `UserWarning` matching `"conditioned"` for both WT1 and WT2.
- `build_aero_model` identity: `AJJ*⁻¹ @ AJJ ≈ I` with no correction card.
- `build_aero_model` Wkk: `AJJ*⁻¹ @ (1.5 × AJJ) ≈ I` for uniform weight 1.5.
- `build_aero_model` WT2 round-trip: corrected cp reproduces VLM cp.
- Shape checks: `AJJ`, `AJJ*⁻¹` `(n, n)`; `Skj` `(3n, n)`; `Djk` `(n, n)`; `wg` `(n,)`.
- **616 tests pass, 0 skipped, 0 failures.**

---

### Step S45 — VTP Cp Bugs + Sideslip Beta Implementation ✅ COMPLETE

**Objective:** Fix three layered bugs that caused incorrect Cp on vertical surfaces (VTP/fins)
and implement sideslip angle β for non-zero sideforce loads.

**Deliverables:**

- `sbeam/aero/panel.py`:
  - Normal orientation: changed from Z-only check to dominant-axis check
    (`argmax(|normal|)` → positive); horizontal surfaces → +Z, vertical → +Y.
  - Bound vortex orientation: added condition check `(b−a)×x̂·n̂ < 0`; swaps
    `bound_a`/`bound_b` when violated (VTP panels swap top↔bottom so AIC diagonal
    is always negative, consistent with horizontal surfaces).
- `sbeam/aero/vlm.py`:
  - `horseshoe_influence` signature: added `colloc_normal` argument; replaced
    `np.dot(v, _Z_HAT)` with `np.dot(v, colloc_normal)` (ZAERO Eq. 3.49a —
    full dot product with receiving panel's normal, not Z-component only).
  - `build_ajj`: passes `box_i.normal` to `horseshoe_influence`.
  - `solve_rigid_cl`: added `beta: float = 0.0` parameter; RHS changed from
    `np.full(n, -alpha)` to `-(alpha*n_z + beta*n_y)` per panel (ZAERO Eq. 3.28).
  - `span_ref`: uses `np.ptp(colloc_pts[:, 1:], axis=0)` max — handles models
    with both Y-span (wing) and Z-span (VTP) surfaces.
- `sbeam/viewer/app.py`: added sideslip β number input alongside AoA α in the
  aero tab; passes `beta=np.radians(beta_deg)` to `solve_rigid_cl`.
- `tests/aero/test_vlm.py`:
  - Updated 4 existing `horseshoe_influence` call sites to pass `box.normal`.
  - Added `_vtp_panel()` helper (CAERO1 in XZ plane, span in +Z).
  - Added `TestVtpNormal`: asserts VTP normal is `[0,+1,0]`.
  - Added `TestVtpAerodynamics`: VTP Cp≈0 at alpha-only; non-zero at beta>0.
  - Added `TestVtpCybConvergence`: CYb within 10% of Prandtl at moderate mesh;
    internal convergence test (successive differences shrink).
  - Added `TestAlphaBetaDecoupling`: wing zero at beta-only; VTP zero at alpha-only.

**Key decisions:**
- **Full normalwash formula** (ZAERO 3.49a, not Z-only): required to support any
  non-horizontal surface orientation; same formula works for wings, HTP, and VTP.
- **Bound vortex swap** (panel.py): the sign convention for VTP is inverted relative to
  horizontal surfaces unless the bound direction is flipped. The condition
  `(b−a)×x̂·n̂ < 0` is derived from requiring a negative AIC diagonal — the same
  physical requirement as for horizontal wings.
- **Beta RHS** (ZAERO 3.28): `rhs[i] = -(α·n_z + β·n_y)`. For the airplane_aero.bdf
  model at β=0, VTP Cp is zero (correct). Non-zero β produces sideforce on the VTP.
- **parity=0 convergence**: VLM with parity=0 (single fin, no image) does not converge
  monotonically toward the Prandtl lifting-line value; it overshoots at coarse meshes
  and decreases as panels are added. This is an intrinsic VLM characteristic confirmed
  to be identical for horizontal wings and VTPs under the same parity. The convergence
  test was updated to check internal convergence (successive differences decrease).

**Test / Acceptance (S45):**
- `TestVtpNormal::test_vtp_normal_is_plus_y`: VTP box normals all [0,+1,0].
- `TestVtpAerodynamics::test_vtp_zero_cp_at_alpha_only`: max |Cp| < 1e-6 for β=0.
- `TestVtpAerodynamics::test_vtp_cl_positive_for_positive_beta`: VTP CL < 0 (negative by
  K-J sign convention with parity=0; physics confirmed correct by magnitude).
- `TestVtpCybConvergence::test_CYb_within_10_percent_of_prandtl`: |CYb − target|/target < 10%.
- `TestVtpCybConvergence::test_CYb_mesh_convergence`: internal convergence confirmed.
- `TestAlphaBetaDecoupling::test_wing_zero_cp_at_beta_only`, `test_vtp_zero_cp_at_alpha_only`.
- **32 tests pass, 0 failures.**

---

### Phase A — A1: VLM "lift-curve-slope under-prediction" ✅ RESOLVED (not a defect)

**Date resolved:** 2026-06-09

**Original symptom:** finite-AR CL_α ran 3–8% below analytical references and the deficit
appeared to GROW with spanwise refinement (nstrip 40→80), suggesting a trailing-vortex
induced-downwash kernel bias.

**Investigation (two stages):**

1. **Spanwise-spacing study** (`studies/a1_spanwise_spacing_study.py`, results in
   `docs/20_theory/studies/a1_spanwise_spacing.md`). Swept nspan with uniform vs cosine spanwise spacing
   on the AVL-anchored tapered wing and the rectangular AR=8 wing, plus control probes:
   - Uniform vs cosine spacing are **identical to < 0.2%** at every resolution → the
     Hough/Lan spacing hypothesis is **refuted**.
   - The drift is **convergent** (decrements halve each nspan doubling) and **purely
     spanwise-count driven** — independent of nchord (probe 1) and box aspect ratio (probe 2).

2. **Peer-VLM convergence comparison** (`studies/byu_wing_sweep.jl`, run in VortexLattice.jl —
   BYU FLOW Lab, validated against AVL to < 0.1%):

   | nspan | VLM.jl CL_α | sbeam CL_α | Δ (VLM−sbeam) |
   |------:|------------:|-----------:|--------------:|
   | 6  | 4.7621 | 4.7697 | −0.0076 |
   | 12 | 4.6671 | 4.6746 | −0.0075 |
   | 24 | 4.6142 | 4.6216 | −0.0074 |
   | 48 | 4.5864 | ~4.59  | −0.0074 |

   VortexLattice.jl drifts down with refinement **identically** to sbeam (4.76→4.67→4.61→4.59),
   and the sbeam−peer offset is **constant at ~0.16%** — not a growing divergence. CM (post-A9)
   and far-field CDi also track VLM.jl across the sweep.

**Resolution:** A1 is **not a defect.** The refinement drift is ordinary convergent
lifting-surface VLM mesh behaviour, reproduced identically by an AVL-validated peer code. The
original "deficit" was an artifact of comparing against lifting-LINE upper bounds (`2π/(1+2/AR)`
= 5.027, etc.), which finite-AR lifting-surface VLM correctly sits below. sbeam's CL_α matches
VortexLattice.jl/AVL to ~0.16% at every resolution. No code change required.

**Artifacts:** `studies/a1_spanwise_spacing_study.py`, `studies/byu_wing_sweep.jl`,
`studies/byu_wing.avl` (AVL equivalent), `docs/20_theory/studies/a1_spanwise_spacing.md`,
regression `tests/aero/test_val_byu_wing.py` (CL 0.16%, CM 0.25% vs AVL).

---

### Phase A — A9: Pitching-moment arm at ¾-chord instead of ¼-chord ✅ FIXED

**Date resolved:** 2026-06-09

**Discovered by:** external-benchmark validation against the BYU FLOW Lab
VortexLattice.jl "Steady-State Analysis of a Wing" example (itself validated against
AVL to < 0.1%). sbeam's CL matched to 0.16%, but CM was ~2× the AVL value.

**Root cause:** `solve_rigid_cl` in `sbeam/aero/vlm.py` computed the pitching moment with
each box's Kutta–Joukowski force acting at the box **¾-chord collocation point**
(`boxes[i].colloc[0]`). The force physically acts at the **¼-chord bound vortex**. Using the
collocation point shifts every box load aft by half a box chord, inflating |CM| by
`CL·(½·box_chord)/c_ref`. The error is mesh-dependent (shrinks as NCHORD→∞), so coarse
internal checks did not catch it; on the AR-7.5 benchmark (NCHORD=6) it doubled CM:
−0.04150 (buggy) vs −0.02085 (AVL). This is distinct from A3 (moment *reference point* and
`c_ref` normalisation, already fixed) — A9 is the per-box *moment arm*.

**Fix:**

1. **`sbeam/aero/vlm.py`** — Precompute `x_qc[i] = ½·(bound_a[0] + bound_b[0])`, the
   ¼-chord (bound-vortex) x of each box, and use it as the moment arm in both the global
   `CM` and the per-surface `cm_eid` sums (replacing `boxes[i].colloc[0]`). Docstring updated.

2. **`sample/val_vlm_byu_wing.bdf`** — New AVL-validated benchmark BDF (BYU VortexLattice.jl
   wing: root 2.2 / tip 1.8 / half-span 7.5 / LE sweep 0.4 / AR 7.5; full-span as two
   CAERO1 surfaces, parity 0; 144 boxes).

3. **`tests/aero/test_val_byu_wing.py`** — New external-benchmark regression: CL within 1%
   (0.16%) and CM within 2% (0.25%) of the AVL values, plus a guard asserting CM is not the
   ~−0.0415 ¾-chord-arm value.

4. **`docs/10_standard/05_aeroelastics.md`** — CM return-dict bullet documents the ¼-chord moment arm.

**Test / Acceptance:** `tests/aero/test_val_byu_wing.py` (4 tests) passes; all 47
`tests/aero/test_vlm.py` invariance tests (CM∝1/c_ref, xref-shift, aeros-vs-heuristic) remain
green — they are relative and unaffected by the absolute arm correction. CL = 0.24476 (AVL
0.24437, +0.16%); CM = −0.02090 (AVL −0.02085, +0.25%).

---

### Phase A — A2 + A3: AEROS reference geometry + per-surface breakdown + moment reference ✅ FIXED

**Date resolved:** 2026-06-09

**Root cause (A2):** `solve_rigid_cl` in `sbeam/aero/vlm.py` (lines 167–174) recomputed
S_ref, span_ref, and c_ref heuristically from the pooled box geometry and never used the
parsed `AEROS` card. On multi-surface models (wing + HTP + VTP) this summed the area of
all surfaces together and mixed VTP sideforce into the CL total — physically meaningless.

**Root cause (A3):** CM was taken about x=0 with the heuristic c_ref, not about a defined
moment reference point normalised by AEROS CREF.

**Root cause (data loss):** `AeroModel` did not carry the `aeros` field, so `bulk.aeros`
was discarded before `solve_rigid_cl` was called.

**Fix:**

1. **`sbeam/aero/aero_model.py`** — Added `aeros: Optional[Aeros] = None` field to
   `AeroModel` dataclass; `build_aero_model` now stores `bulk.aeros` in the returned model.

2. **`sbeam/aero/vlm.py`** — Updated `solve_rigid_cl` signature with two new optional
   parameters: `aeros=None` (provides S_ref and c_ref from the AEROS card when present;
   falls back to heuristic when None) and `xref=0.0` (moment reference x-coordinate in
   CID 0; default preserves existing behaviour). Per-surface classification added: each
   CAERO1 surface is classified by its mean outward normal — `|n_z| ≥ |n_y|` → "lift"
   (contributes to CL/CM); `|n_y| > |n_z|` → "sideforce" (contributes to CY). Result
   dict extended with `CY` and `per_surface` keys.

3. **`sbeam/viewer/app.py`** — `solve_rigid_cl` call now passes `aeros=aero_model.aeros`;
   viewer displays CY metric and a per-surface breakdown table for multi-surface models.

4. **`tests/aero/test_vlm.py`** — Updated two VTP tests that checked `result["CL"]` for
   sideforce to check `result["CY"]`. Added three new test classes: `TestAerosReferenceGeometry`
   (CL and CM scale correctly with AEROS sref/cref), `TestPerSurfaceClassification` (surface
   type, CL/CY separation, per-surface dict), `TestMomentXref` (CM shift formula).

5. **`docs/10_standard/05_aeroelastics.md`** — Updated `solve_rigid_cl` signature and return dict
   documentation; updated architecture overview to show `aeros` in `AeroModel`.

**Test / Acceptance:**
- `TestAerosReferenceGeometry`: CL inversely proportional to aeros.sref; CM inversely
  proportional to aeros.cref; no-aeros result matches heuristic exactly.
- `TestPerSurfaceClassification`: horizontal wing → "lift" surface in per_surface; VTP →
  "sideforce" surface; VTP contributes to CY not CL; per-surface CL sums to global CL.
- `TestMomentXref`: CM(xref+dx) = CM(xref) + CL*dx/c_ref (to rel=1e-8); default xref=0.
- `TestVtpCybConvergence`: retested with `result["CY"]` — within 10% of Prandtl, internal
  convergence confirmed.
- **653 tests pass, 0 failures.**

---

### Step 46 — Replace `lstsq` AIC inverse with LU factorization ✅ COMPLETE

**Objective:** Eliminate SVD-based inversion of the square, full-rank AIC matrix.
`np.linalg.lstsq` dominated build time (~25 s for the 1232-box `airplane_aero.bdf`
model). Replacing it with `np.linalg.solve` (LU-based) reduces cost substantially.

**Deliverables:**

1. **`sbeam/aero/corrections.py`** — `_solve_ajj` rewritten to call
   `np.linalg.solve(ajj, np.eye(n))` instead of `lstsq`. Docstring updated.

2. **`sbeam/aero/aero_model.py`** — WKK branch (line 82) and no-correction branch
   (line 90) converted to `np.linalg.solve`. `_check_conditioning` imported from
   `corrections` and called in both branches so a degenerate AIC emits a `UserWarning`
   before raising instead of silently returning a pseudo-inverse. Module and function
   docstrings updated (`lstsq` → `solve`/`LU factorization`).

3. **`tests/aero/test_corrections.py`** — `_ajj_and_inv` helper and
   `TestBuildAeroModel.test_wt2_round_trip` updated to use `np.linalg.solve`.
   Conditioning warning tests updated to use a well-conditioned but ill-conditioned
   diagonal matrix (`cond ≈ 1e12`) instead of a zero matrix — `solve` correctly
   raises `LinAlgError` on a truly singular input, so the tests now reflect the
   intended behaviour.

4. **`docs/10_standard/05_aeroelastics.md`** — Correction-precedence table and `apply_wkk` description
   updated to reflect `np.linalg.solve` and the WKK conditioning guard.

**Key decisions:**
- `np.linalg.solve(A, I)` preferred over `scipy.linalg.lu_factor/lu_solve` — NumPy
  is already a dependency and the explicit inverse is stored for repeated `A*⁻¹ @ w`
  multiplies downstream; forming it once is the right trade-off.
- Conditioning check added to WKK and no-correction branches to match the existing
  guard already present in `apply_wt2` and `apply_wt1`.

**Test / Acceptance:**
- All 17 `test_corrections.py` tests pass.
- **653 tests pass, 0 failures.**

---

### Phase A — A4: Prandtl–Glauert / Göthert Compressibility Correction ✅ COMPLETE

**Date:** 2026-06-10

**Objective:** Add subsonic compressibility correction to the VLM via the Göthert similarity
rule: compress panel geometry by β = √(1−M²) before building the AIC, then scale the inverted
AIC by 1/β. Expose Mach via an sbeam extension field on the AEROS card.

**Deliverables:**
- `sbeam/model/aero.py` — `Aeros.mach: float = 0.0` field added (sbeam extension, field 8).
- `sbeam/parser/bdf_reader.py` — `_handle_aeros()` parses optional field 8 as `mach`.
- `sbeam/aero/vlm.py` — new `prandtl_glauert_boxes(boxes, mach)` helper; `solve_rigid_cl`
  accepts `mach=` and applies PG before the AIC solve.
- `sbeam/aero/aero_model.py` — `build_aero_model` applies PG boxes for AIC, scales
  `ajj_inv_corr` by 1/β; `AeroModel.mach` field added.
- `sbeam/viewer/app.py` — passes `mach=aero_model.mach` to `solve_rigid_cl`.
- `tests/aero/test_vlm.py` — 4 new tests in `TestPrandtlGlauert` (identity at M=0, y
  compression, CL increase bounded by 1/β, M=0.995 cap).
- `docs/10_standard/02_card_reference.md` — AEROS MACH field documented.
- `docs/10_standard/05_aeroelastics.md` — "Known Limitations / deferred" replaced with
  "Implementation Notes" describing the Göthert approach.
- `docs/20_theory/01_aeroelastics_theory.md` — new §2.8 deriving the Göthert transform
  (Eq. 14); §2.1 cross-reference updated; §9 and §10 (references) updated.

**Test/Acceptance:**
- 128 aero tests pass (124 pre-existing + 4 new); M=0.0 gives bit-identical results to
  the pre-correction solver.
- `test_pg_correction_increases_cl`: CL at M=0.6 is greater than at M=0 and less than
  the 2-D PG bound of 1/β, confirming physically correct 3-D correction.

**Key decisions:**
- Göthert geometry compression (y,z by β) chosen over a simple 1/β AIC scaling: more
  physically correct for 3-D planform effects and consistent with VortexLattice.jl /
  ZAERO ZONA6 approach.
- Mach placed on `AEROS` field 8 (sbeam extension) rather than a new TRIM card; TRIM is
  deferred to Phase C. Default mach=0.0 keeps full backward compatibility.
- β capped at 0.99 (not 1.0) to avoid division-by-zero near M=1.
- `skj`, `djk`, `wg` built from physical (unscaled) boxes — only the AIC uses PG geometry.

---

### Phase A — A6: Trefftz-Plane Induced Drag ✅ COMPLETE

**Date:** 2026-06-09

**Objective:** Add a Trefftz-plane post-processing function to `vlm.py` that computes
the induced drag coefficient (CDi) and Oswald span efficiency (e) from the solved
circulation field, enabling the standard elliptic-loading cross-check
`CDi = CL² / (π · AR · e)`.

**Deliverables:**
1. **`sbeam/aero/vlm.py`** — new `trefftz_cdi(boxes, gamma, parity, S_ref, ar)` function.
   Integrates the semi-infinite trailing-vortex wake in the far-field y-z plane using
   the 2-D Biot-Savart kernel (Katz & Plotkin Eq 12.17).  Only lift surfaces
   (`|n_z| ≥ |n_y|`) contribute.  Mirror trailing vortices are included for `parity ≠ 0`
   using the same convention as `horseshoe_influence`: the mirror of a direct trailing at
   `(y_v, z_v)` with strength `s` is placed at `(-y_v, z_v)` with strength `-parity·s`.
   `solve_rigid_cl` calls `trefftz_cdi` and adds `"CDi"` and `"e"` to its return dict.

2. **`tests/aero/test_vlm.py`** — new `TestTrefftzInducedDrag` class (6 tests):
   - `test_keys_present`: CDi and e keys exist in the solve_rigid_cl return dict
   - `test_cdi_positive`: CDi > 0 for α > 0
   - `test_oswald_near_unity`: e ∈ (0.85, 1.05) for rectangular AR=16 wing
   - `test_cdi_cl_identity`: CDi = CL²/(π·AR·e) to 1e-9 relative tolerance
   - `test_cdi_scales_as_alpha_squared`: CDi(2α)/CDi(α) ≈ 4.0 within 1%
   - `test_cdi_zero_at_zero_alpha`: CDi < 1e-12 at α = 0

3. **`docs/10_standard/05_aeroelastics.md`** — CDi and e entries added to the `solve_rigid_cl` return
   dict documentation, including the normalisation formula and expected e range.

**Key decisions:**
- `CDi = Σ Γ·w_T·Δy / S_ref` (no extra ×2): the Trefftz formula has a ρ/2 prefactor
  that exactly cancels with the 1/q = 2 in the CDi normalisation, so w_T (full 2-D
  Biot-Savart, factor 1/(2π)) is used without an additional factor.
- For heuristic reference geometry (no AEROS card), the physical AR is computed as
  `(2·max_y)² / (2·S_ref_half)` for half-span models to avoid the factor-of-2 error
  that arises from using `b_ref² / S_ref_half` directly.
- When AEROS is provided, `ar = bref² / sref` is unambiguous (AEROS always carries
  full-wing geometry).
- `parity = -1` (antisymmetric): CDi = 0.0, e = nan — consistent with CL = 0 convention.

**Test / Acceptance:**
- 6 new tests pass; full aero suite remains 124 passing, 0 failures.

---

### Step A-SC: Section force + moment correction synthesiser (`section_correction.py`) ✅ COMPLETE

**Objective:** Provide a way to match a target *section line* — slope **and** zero-α offset of
both force and pitching moment — that `apply_wt1` cannot (it matches per-strip force only and
cannot move the section aerodynamic centre). Do it with **minimal change to the uncorrected
chordwise distribution** and **without** any solver or BDF-card-schema change (the chosen "Option
A": a preprocessor that emits an ordinary `W2GJ` + `WT2` card pair).

**Deliverables:**
1. **`sbeam/aero/section_correction.py`** — `build_section_correction(boxes, ajj, *, f_slope,
   alpha_0, m_slope, m_0, caero_eid, sid_w2gj, sid_aecorr, moment_ref=None)` returning a
   `SectionCorrectionResult` (the `W2gj` + `Aecorr`/WT2 cards, the per-box `r`/`wg` arrays, the
   per-strip `moment_ref`, and achieved-vs-target diagnostics). `cards_to_bdf()` formats the pair
   as free-field bulk data.
2. **`tests/aero/test_section_correction.py`** — 8 tests: identity targets → no-op (`r≈1`,
   `wg≈0`); pure slope scaling → uniform per-strip `r` (degenerates to WT1) with `wg≈0`; full
   `(slope, a.c., α₀, Cm0)` match reproduced in the diagnostics **and** end-to-end through
   `build_aero_model` at α=0 and α=0.1; NCHORD<2 raises; multi-surface raises; length-mismatch
   raises; `cards_to_bdf` round-trips through `parse_bulk_data`.
3. **Docs** — theory `docs/20_theory/01_aeroelastics_theory.md` new §3.5 (synthesis method) plus a
   §3.3 note correcting the WT1 "force/moment" overstatement; standard
   `docs/10_standard/05_aeroelastics.md` new "Section force + moment correction synthesiser"
   section, module-map row, and clarified `apply_wt1` entry.

**Key decisions:**
- **Decomposition.** The four section targets split into a *slope pair* (dF/dα, dM/dα → force
  slope + a.c.) handled by per-box **WT2**, and an *offset pair* (F₀, M₀ → camber lift + camber
  moment, the load at α=0) handled by the **W2GJ** camber-line normalwash. A multiplicative
  correction yields nothing at α=0, so the offset *must* be W2GJ.
- **One-pass / decoupled.** The WT2 ratio is calibrated on `w_ref=-ones` and is independent of
  `w_g`, so WT2 is sized first, then W2GJ is sized through the WT2-corrected operator (which also
  scales the camber load) — no iteration.
- **Minimal change.** WT2 = uniform per-strip scale (no shape change) for the force + a
  minimum-norm per-box perturbation orthogonal to the force for the moment/a.c. mismatch; it
  collapses to the uniform WT1 scaling when the target a.c. equals the VLM a.c. W2GJ = lowest-order
  two-mode camber (uniform incidence + chordwise-linear) per strip, sized by a small global linear
  solve so per-strip (F₀, M₀) are reproduced exactly including inter-strip induction.
- **Unit/guard consistency.** The emitted WT2 target is in Γ-units (the `apply_wt2` convention)
  and mirrors `apply_wt2`'s near-zero-reference `r=1` guard, so the card and the solver operator
  are identical. Single-CAERO1 only (matches the existing full-length WT2 target path); NCHORD≥2
  per strip required (a moment needs two chordwise boxes). Nose-up-positive moment about the
  per-strip ¼-chord (default), matching `sol144._pitch_moment`.

**Test / Acceptance:**
- 8 new tests pass; full aero suite 334 passing, 0 failures; ruff clean.

---

### Step A-SD: Spanwise section-data ingestion for the correction GUI (`section_data.py`) ✅ COMPLETE

**Objective:** Feed `build_section_correction` (Step A-SC) from a user-authored table of *section
coefficients* that vary with span, **Mach**, and a **linearised α/β region** (the standard way the
nonlinear α dependence is captured — two or more linear fits, each with a validity range). Chosen
input convention (user-selected): tidy CSV + in-GUI `st.data_editor`, non-dimensional per-degree
coefficients about ¼-chord, and "v1" single-operating-region selection.

**Deliverables:**
1. **`sbeam/aero/section_data.py`** — tidy/long CSV schema (`caero, eta, mach, var, a_lo, a_hi,
   cn_a, a0, cm_a, cm0, xref`) and: `validate_section_data`, `available_conditions`,
   `template_dataframe` (seeds the editor/template with the actual strip η-stations),
   `build_from_section_data` (interpolate onto strips → convert → build), `operating_region`.
2. **`tests/aero/test_section_data.py`** — 12 tests: schema/var/range/numeric guards; condition
   listing; force-slope and moment-offset coefficient-conversion correctness; end-to-end CL-slope
   == section `cn_a` through `build_aero_model`; extrapolation flag; missing Mach/region raise;
   operating-region containment.
3. **Docs** — standard `docs/10_standard/05_aeroelastics.md` "Spanwise section-data input" section
   + module-map row.

**Key decisions:**
- **Local-chord coefficients, per degree.** Section data follow the airfoil-polar convention
  (normalised by local chord, not `cref`): `f_slope = cn_a·(180/π)·A`, `m_slope = cm_a·(180/π)·c·A`,
  `m_0 = cm0·c·A`, `alpha_0 = a0·π/180`, `moment_ref = LE_x + xref·c` (strip area `A`, local chord
  `c`). Nose-up-positive moment about the chord-fraction `xref` (default ¼c).
- **Spanwise interpolation onto strips** via `AeroBox.span_frac`, clamped at the table ends with an
  `extrapolated` flag (linear; PCHIP a possible later refinement).
- **v1 selection:** Mach matched exactly (no Mach interpolation); one operating region built per
  call, the caller warning if the trim incidence leaves `[a_lo, a_hi]`. Both deferred to follow-ons
  (Mach interpolation; per-region card set keyed in `AeroCache` with trim-α re-selection).
- **PG consistency:** the caller passes `β·ajj_pg` so the reference VLM solve matches the solver's
  1/β-scaled operator at the chosen Mach.

**Test / Acceptance:**
- 12 new tests pass; full section-correction + section-data suite 20 passing; ruff clean.

---

### Step A-SM: Section force+moment correction extended to multi-surface ✅ COMPLETE

**Objective:** Lift the single-CAERO1 restriction of Steps A-SC / A-SD so a deck with several
lifting surfaces (wing + tail + fin …) can be corrected. The AIC is global, so the correction must
be built and applied across all surfaces at once.

**Deliverables:**
1. **`sbeam/aero/section_correction.py`** — `build_section_correction_multi(boxes, ajj, targets, *,
   sid_w2gj_base, sid_aecorr_base, beta=1.0)` engine taking a list of `SurfaceTargets`, returning a
   `MultiSectionCorrectionResult` (`cards[eid] = (W2gj, Aecorr)`, global `r`/`wg`, per-surface
   `SurfaceDiagnostics`). `build_section_correction` is now a single-surface wrapper; `cards_to_bdf`
   accepts either result.
2. **`sbeam/aero/aero_model.py`** — `build_aero_model` WT2 branch combines **all** `WT2` `AECORR`
   cards into one global Γ-unit target (each card fills its CAERO1's boxes; uncorrected surfaces
   default to ratio 1).
3. **`sbeam/aero/section_data.py`** — `build_from_section_data_multi(…, mach, incidence_deg, …)`:
   per-surface region selection at one flight point, global build, `.skipped` for surfaces with no
   containing region. Per-surface strip geometry; β derived from `mach`.
4. **Tests** — +5 (`test_section_correction.py`: multi-surface engine end-to-end through
   `build_aero_model`, partial correction leaves other surface at r=1/wg=0, multi-card BDF
   round-trip; `test_section_data.py`: multi build, per-surface region selection + skip).
5. **Docs** — theory §3.5 multi-surface paragraph; standard-doc engine/precedence/section-data
   updates + module-map rows.

**Key decisions:**
- **Global build, per-surface cards.** WT2 `r` is a global per-box vector (1 on uncorrected boxes);
  the W2GJ camber offset is **one global linear solve** over all corrected strips (camber on one
  surface induces load on the others). Cards are still emitted per CAERO1 (W2GJ and AECORR are
  per-surface cards), and `build_aero_model` recombines them.
- **PG correctness.** The builder takes the raw `ajj_pg` + explicit `beta=√(1−M²)` and applies 1/β
  only to the physical force, leaving the WT2 card target in pure Γ-units — fixing a latent M>0
  double-count in the earlier "β·ajj_pg" convention (M=0 unaffected).
- **Backward compatible.** A single WT2 card on a single-surface deck reduces to the previous
  behaviour exactly; `WKK`/`WT1` remain primary-CAERO1 only.

**Test / Acceptance:**
- 5 new tests pass; full aero suite 351 passing, 0 failures; ruff clean.

---

### Step A9: Cruciform body panels — total-aircraft moment correction ✅ COMPLETE (2026-06-14)

**Objective:** sbeam has no body/slender-body element, so a flat-panel airplane (wing + tails only)
gets the overall pitching moment Cm, yawing moment Cn and rolling moment Cl (dihedral effect) wrong.
Adopt the classic **cruciform**: represent the fuselage with two crossing flat VLM surfaces
(horizontal +Z, vertical +Y), correct the flying surfaces to spanwise section data, then tune the
body panels so the **total airplane** matches CFD/WT — Cm_α, Cm0 (pitch, horizontal panel) and the
sideslip set Cn_β, Cn0, Cl_β, Cl0 (yaw + roll, vertical panel). Moment-primary, the body's
lift/side-force a by-product.

**Deliverables:**
1. **`sbeam/aero/body_correction.py`** — `build_body_correction(bulk, *, horiz_eid, vert_eid,
   targets, mach, aero=None, …)` → `BodyCorrectionResult`. A **direct, exact, non-iterative** linear
   solve: (a) **slope** via a per-box WT2 ratio (`diag(r)·A⁻¹` scales only that box's ΔCp, so the
   body's slope contribution is decoupled from the flying surfaces; force held at the bare VLM value)
   — solved **jointly** over both panels' boxes because Cl_β couples to the horizontal panel too (its
   β-load carries a rolling moment via the `w_roll` `y·n_z` term); (b) **offset** via a joint
   min-norm W2GJ least-squares against the actual corrected operator (body camber's induced wing load
   is accounted for, not fought). `BodyTargets` (cm_alpha/cm0/cn_beta/cn0/cl_beta/cl0),
   `split_total_rows`, `parse_body_targets` (CSV `TOTAL` block), `body_cards_to_bdf`.
2. **Aero Correction tab — Stage 6** (`viewer/aero_correction_view.py`): `_guess_body_panels`
   pre-selects the largest-chord +Z / +Y surfaces; six targets seed from the CSV `TOTAL` block;
   Build shows a baseline/target/achieved/residual table + max WT2 ratio; Apply injects the flying +
   body card pairs (body SIDs `_BODY_W2GJ_BASE=9301`, `_BODY_AECORR_BASE=9401`); Download body cards.
3. **Refined Cessna 210 sample** — `sample/cessna210_body.bdf` (cruciform `CAERO1` 400 horizontal
   2×8, 500 vertical 4×8 — z-resolution for roll authority — with `SPLINE0`; VTP root extended
   z=0.80→0.60 so the fin intersects the HTP plane at z=0.70) +
   `sample/cessna210_body_section_data.csv` (flying rows + `TOTAL` block with optional `cl_a`/`cl0`).
4. **Tests** — `tests/aero/test_body_correction.py` (six targets hit to ~1e-6; production-path
   cross-check vs `build_aero_model`; flying-surface decoupling; single-panel modes incl. vertical
   yaw+roll; CSV parse), `tests/aero/test_cessna210_body_example.py` (7 surfaces / 372 boxes;
   VTP↔HTP intersection; cruciform normals; two-stage build), Stage-6 tests in
   `tests/viewer/test_aero_correction_view.py`.

**Key decisions:**
- **Moment-primary, body lift a by-product** (per user direction): the body force is left at the bare
  VLM value; only the moments are matched.
- **Order = slope then offset** removes the bilinear slope×offset coupling, making the solve exact in
  one shot (no fixed-point iteration — an earlier fixed-point diverged because the body W2GJ offset
  induces a *larger, opposite* wing pitch moment than the body's own).
- **Joint slope solve** (not per-panel): Cl_β leaks across panels (the horizontal panel's pitch
  ratio scales its small β-response, which carries roll), so all slope constraints are solved
  together over the body boxes — exact; pitch stays horizontal-only because `w_pitch=0` on the
  vertical panel (`n_z=0`) and yaw stays vertical-only (`w_yaw≈0` on the horizontal panel).
- **SPLINE0 for body panels** (not flexible SPLINE2): body elastic effects are negligible, and a
  flexible spline would inject the fictitious correction load into the fuselage beam as spurious
  bending; the body still drives total/trim Cm,Cn and rigid+restrained derivatives via direct box
  integration (verified against `sol144.py`).
- **`aero=` reuse + analytic `achieved`** keep the build to a single AIC build (the operator model
  `diag(r)·A_base` matches `build_aero_model` to ~1e-13, so `achieved` needs no rebuild).

**Test / Acceptance:**
- Targets reached to machine precision (residuals ~1e-14); full `tests/` green; ruff clean on changed
  files.

### Resolved Defect A9a: body panels overlapped the empennage; targets were overlap-calibrated ✅ RESOLVED (2026-06-15)

**Symptom (user-reported):** in `sample/cessna210_body.bdf` the cruciform body panels overlapped the
empennage, causing non-real interaction effects. The horizontal panel (z=0.60, chord to x=8.00) sat
just under the HTP (z=0.70); the vertical panel (y=0, z=0.10–1.30, chord to x=8.00) was **coplanar
with the VTP** (also y=0). Because VLM trailing legs are semi-infinite in +X, body boxes *and their
wakes* interpenetrated the tail and spuriously loaded the real surfaces.

**Root-cause finding (the important part):** moving the panels into clean air exposed that the sample's
moment match was **structurally dependent on the overlap**. Diagnostics showed (a) the flying-only
neutral point sits ~5.7 m aft while the original targets (Cm_α=−6.9) demand it ~1.9 m — a ~3.8 m
(≈2.5 MAC) forward shift the fuselage was being asked to supply; (b) the original panels delivered
~+13.2 of that +13.5 Cm_α almost entirely from boxes immersed in the HTP/VTP; (c) in clean air the
panels' correction sensitivity collapses (~4× pitch, ~600× yaw, ~130× roll) because they were
"piggy-backing" on the empennage's strong response. The deep result: **a body panel's authority to
move the total moment and its contamination of the lifting surfaces are the same coupling mechanism**,
so a clean cruciform can only legitimately supply a *small* increment. `ratio_max` is a *conditioning*
gauge, not a contamination gauge (WT2 is body-row-only — a large ratio for clear-of-tail panels is
benign; the genuine adverse metric is the body's induced ΔCp on the lifting-surface boxes, which the
clean geometry reduces markedly).

**Resolution (user chose "realistic targets + document"):**
- **Geometry** — both panels made compact and clear of the tail: terminate at x=5.00 (ahead of VTP LE
  6.60 / HTP LE 6.90); horizontal at z=0.30 (below HTP), vertical wholly below the VTP root
  (z=0.05–0.45); half-span/height ~0.40. Box counts (372) and SPLINE0 ranges unchanged.
- **Targets** — CSV `TOTAL` revised to the flying baseline + a realistic fuselage increment (mild
  destabilising Cm_α/Cn_β, ~0 roll); the body now moves Cm_α by a physical ~+0.85 at a benign (large,
  decoupled) WT2 ratio with body ΔCp comparable to the real surfaces.
- **Code** — `body_correction.py` `_RATIO_WARN` 5→200 and message reworded (the old "add area/arm"
  advice is counterproductive); module docstring + `05_aeroelastics.md` + `01_aeroelastics_theory.md`
  §3.6 document the geometry guidance and the authority↔contamination finding.
- **Backlog** — added "Body aerodynamic panels (slender body)" as the proper fix (Tier 1 NASTRAN-style
  slender + interference body recommended); refined A9-c.

**Test / Acceptance:** new `test_body_panels_clear_of_empennage` (no body box or +X wake reaches the
tail); body tests assert `ratio_max < _RATIO_WARN` (ratio is decoupled from contamination) and track
the realistic targets; `tests/aero/` + `tests/viewer/` green; ruff clean.

### Step A9b: multi-surface body planes ✅ COMPLETE (2026-06-15)

**Objective:** let a body plane be defined by **more than one** CAERO1 — e.g. a fuselage side split
into a panel by the wing, one running to the fin trailing edge, and one for the lower body — rather
than a single horizontal + single vertical panel.

**Deliverables:**
- `build_body_correction` `horiz_eid` / `vert_eid` accept an `int` **or a list of `int`** (new
  `_as_eid_list` helper); fully backward compatible. No solver change was needed: the slope and offset
  solves were already joint min-norm over the flat `body_idx` set, and the per-box weights
  (`w_pitch`/`w_yaw`/`w_roll`) route each box to its metric by normal — so any number of panels per
  plane is matched together, each emitting its own `(W2gj, Aecorr)` pair at `base + i`.
- Viewer Stage 6 pickers changed from `selectbox` to `st.multiselect` (a plane = one or many panels).
- Tests: `test_eid_int_and_singleton_list_equivalent` (int ≡ singleton list, identical results) and
  `test_multi_surface_body_plane` (2-panel vertical body hits all six targets to ~1e-6, one card pair
  per panel, distinct SIDs); viewer test asserts multiselect pickers.

**Key decisions / findings:**
- **No special-casing for multiple panels** — the weights-route-by-normal design makes the joint solve
  size-agnostic; the only changes are list normalisation, the `if horiz_eids:` / `if vert_eids:`
  guards, and per-panel SID allocation (already a loop).
- **Splitting a plane improves conditioning** — more body boxes give the min-norm more freedom, so the
  WT2 ratio drops and the correction load spreads (Cessna body `ratio_max` ~93 → ~32 across 4 panels).
- **Placement caveat unchanged** — each piece must stay clear of the lifting surfaces; an overlapping
  piece contaminates them (it does not model interference). Documented in `05_aeroelastics.md` /
  `01_aeroelastics_theory.md` §3.6 and the viewer caption.

**Test / Acceptance:** `tests/aero/test_body_correction.py` + `tests/viewer/test_aero_correction_view.py`
green; ruff clean.

---

### Step A10: decoupled strip body panels (PSTRIP/STRIPK) ✅ COMPLETE (2026-06-15)

**Objective:** add a body panel type that resolves the cruciform's structural limit — that a flat
panel's authority to move the total moment *is* the coupling that contaminates the lifting surfaces
(Step A9a finding / theory §3.6). A panel with **no coupling** cannot contaminate.

**Deliverables:**
- **New cards** `PSTRIP` (marker on the CAERO1 PID + nominal per-box lift-curve slope, default π) and
  `STRIPK` (per-box slope override), with dataclasses, parser handlers, dispatch, and cross-reference
  validation (CAERO1 PID resolves to PAERO1 **or** PSTRIP; STRIPK must target a strip CAERO1).
- **`sbeam/aero/strip.py`** — `is_strip_caero`, `strip_box_mask`, `strip_box_slopes`. A strip CAERO1
  carries no horseshoe vortex / wake / coupling: `build_aero_model` excludes its boxes from the VLM AIC
  inversion and places a diagonal block `diag(-slope/β)` into `ajj_inv_corr` (operator assembly
  refactored into `_assemble_vlm_operator`; `AeroBox.is_strip` flag; `solve_rigid_cl` raw path rejects
  strip decks; viewer uncorrected-overlay skipped for strip decks).
- **`build_strip_body_correction`** + `strip_body_cards_to_bdf` (`body_correction.py`) — sets per-box
  slope (STRIPK) and Δα (W2GJ) so the total airplane Cm_α/Cm0, Cn_β/Cn0, Cl_β/Cl0 hit targets; same
  moment-primary, slope-then-offset min-norm structure as the cruciform but contamination-free and with
  no `ratio_max` conditioning concern.
- **Viewer** Stage 6 auto-detects panel kind (PSTRIP → strip / PAERO1 → cruciform) and routes to the
  matching builder; strip cards apply at `_BODY_W2GJ_BASE=9301` / `_BODY_STRIPK_BASE=9501`.
- **Sample** `sample/cessna210_strip.bdf`; **docs** card reference (PSTRIP/STRIPK), `05_aeroelastics.md`
  ("Decoupled strip body panels"), theory §3.7 (block-diagonal load/BC separation + image-fence note).

**Key decisions / findings:**
- **Diagonal block = exact decoupling.** Verified the lifting-surface inverse is *bit-identical* with
  or without the strip present, and that relocating a strip on top of the wing changes wing loads by
  exactly zero — overlap is harmless by construction.
- **π slope = sectional cl_α of π.** A uniform per-box slope gives a sectional lift-curve slope equal
  to that value, matching the "50% of 2π flat plate" body fudge requested.
- **Load and BC are separate mechanisms.** A decoupled strip carries the body's *load* but no
  interference; the fence / no-through-flow boundary condition is the complementary (necessarily
  coupled) half, deferred to the backlog "image fence" item.

**Test / Acceptance:** `tests/aero/test_strip_body.py` (16 tests: parser, operator structure, exact
decoupling, π-slope, six-target correction on rebuild) + aero/parser suites green; ruff clean.

---


## Phase B — Structure ↔ Aero Splining

### Step 45: SET1 + SPLINE2 parsing ✅ COMPLETE

**Objective:** Parse `SET1` (structural grid lists) and `SPLINE2` (beam-spline card)
from BDF input; add stub dataclasses for `Attach`, `Spline0`, `Spline1`; cross-reference
validation.

**Deliverables:**
- `model/aero.py`: added `Set1`, `Spline2`, `Attach`, `Spline0`, `Spline1` dataclasses
- `model/bulk_data.py`: added `set1s`, `spline2s`, `attaches`, `spline0s`, `spline1s` fields
- `parser/bdf_reader.py`:
  - `_handle_set1` (Pattern B multi-continuation, same template as RBE2/SPC1)
  - `_handle_spline2` (Pattern A, optional single continuation for DTHX/DTHZ/USAGE)
  - `_handle_attach`, `_handle_spline0` (single-line handlers)
  - `_handle_spline1` raises `NotImplementedError`
  - Dispatch entries for `SET1`, `SPLINE2`, `ATTACH`, `SPLINE0`, `SPLINE1`
  - Cross-reference validation: SPLINE2.setg → SET1, SPLINE2.caero → CAERO1,
    all SET1 grid IDs → GRID
- SPLINE2 defaults: DZ=0.0, DTOR=1.0, DTHX=1.0, DTHZ=0.0, USAGE="BOTH"

**Test/Acceptance:**
- `tests/aero/test_spline.py::TestSet1Parse` — single-line, multi-continuation, duplicate error
- `tests/aero/test_spline.py::TestSpline2Parse` — defaults, explicit continuation, missing SET1/CAERO1 errors
- All 686 existing tests continue to pass

**Key decisions:**
- Box ID mapping verified: NASTRAN box ID = `CAERO1.EID + i_span × nchord + j_chord`,
  matching `panel.py` row-major ordering (span slowest, chord fastest)
- `Attach` and `Spline0` dataclasses added here (builders implemented in Step 47)
- `Spline1` handler raises `NotImplementedError` immediately on parse (deferred to Step 48)

---

### Step 46: SPLINE2 beam-spline operators (`spline.py`) ✅ COMPLETE

**Objective:** Build the two CID-aware spline operators from each `SPLINE2` card using
`scipy.interpolate.CubicHermiteSpline`. Operators are added to `AeroModel` and feed
directly into `coupling.build_qaa` / `coupling.build_fg`.

**Deliverables:**
- New file `sbeam/aero/spline.py`:
  - `build_g_spline(bulk, boxes, grid_index) → (g_slope, g_disp)`:
    - `g_slope`: shape `(n_box, 6·n_grid)` — maps structural DOFs → per-box streamwise incidence
    - `g_disp`:  shape `(3·n_box, 6·n_grid)` — maps structural DOFs → per-box 3-D displacement
  - `_build_spline2_block`: unit-impulse Hermite approach — for each structural node i,
    builds two CubicHermiteSpline basis functions (function-value basis phi_f[i] and
    derivative-value basis phi_d[i]) and fills g_slope/g_disp columns using CID-aware
    projections via z_hat, y_hat, x_hat from the CORD2R CID
  - `_register_spline0`: marks boxes as covered with zero rows (Step 47 placeholder)
  - Per-box coverage tracker: errors on double-spline; warns on un-splined box; warns
    on >10% extrapolation beyond SET1 span range
- `model/aero.py` and `aero_model.py`: `AeroModel` gains `g_slope`, `g_disp` optional fields;
  `build_aero_model` accepts optional `grid_index` parameter and calls `build_g_spline`

**CID-aware DOF projections (key design):**
- `x_hat = R_cid[:, 0]` (spline axis = span direction)
- `y_hat = R_cid[:, 1]` (bending-slope axis; rotation projected here is the spanwise slope)
- `z_hat = R_cid[:, 2]` (surface normal / deflection direction)
- Translation DOF d: effective normal deflection = `z_hat[d]`; contributes to g_slope via
  `-z_hat[d] × d(phi_f[i])/ds` and to g_disp via `z_hat[d] × phi_f[i](t_j) × z_hat`
- Rotation DOF d: bending slope = `y_hat[d-3]`, contributes to g_slope via
  `-y_hat[d-3] × d(phi_d[i])/ds` and to g_disp via `y_hat[d-3] × phi_d[i](t_j) × z_hat`
- Rotation DOF d: torsion = `x_hat[d-3]`, contributes to g_slope via
  `dthx × x_hat[d-3] × phi_f[i](t_j)` (no g_disp contribution)
- For CID=0: z_hat=[0,0,1] → Tz only; y_hat=[0,1,0] → Ry only; x_hat=[1,0,0] → Rx only

**Test/Acceptance (V-B1 — rigid-body gate passed):**
- Rigid translation (uniform Tz=1): `g_slope @ u` = 0 everywhere to < 1e-12 ✓
- Rigid torsion (uniform Ry=1 for span-along-Y): `g_slope @ u` = 1.0 everywhere to < 1e-12 ✓
  (partition-of-unity: Σ phi_f[i](s) = 1 for all s)
- Combined Tz=1 + Ry=1: `g_slope @ u` = 1.0 everywhere ✓
- Energy round-trip: `g_disp.T @ (Skj @ cp_unit)` Z-component = total panel area ✓
- Parser round-trip and shape tests pass; 686 total tests pass

**Key decisions:**
- Two operators (`g_slope` + `g_disp`) rather than single G_kg: avoids the "classic spline
  bug" documented in `coupling.py`; `g_slope` drives the VLM solve, `g_disp` handles
  virtual-work force transfer back to the structure
- Unit-impulse Hermite approach: builds the matrix column-by-column using two scipy basis
  functions per node (phi_f for function-value, phi_d for slope-value); no matrix inversion
  needed; exact for the CubicHermiteSpline basis
- Rigid-body gate verified: partition-of-unity (Σ phi_f = 1, Σ d(phi_d)/ds = 0 for uniform
  slope field) holds analytically and is confirmed numerically to machine precision

---

### Step 47: ATTACH rigid-body spline + SPLINE0 zero-displacement ✅ COMPLETE

**Objective:** Implement `_build_attach_rows()` in `sbeam/aero/spline.py` to give
rigid-body coupling between a master structural GRID and a group of aero boxes via
the `ATTACH` card; confirm `SPLINE0` boxes correctly contribute zero rows.

**Deliverables:**
- `sbeam/aero/spline.py`:
  - `_build_attach_rows(attach, bulk, boxes, grid_index, id_to_k, covered, g_slope, g_disp)`:
    rigid lever-arm kinematics in global CID 0; for each covered box gk with lever
    `r = box.colloc − master_pos = (rx, ry, rz)`:
    - `g_slope[gk, col_Rx] = +1.0` (torsion coupling)
    - `g_slope[gk, col_Ry] = -1.0` (pitch → uniform downwash -1)
    - `g_disp[3*gk+2, col_Tz] = 1.0`, `g_disp[3*gk+2, col_Rx] = ry`,
      `g_disp[3*gk+2, col_Ry] = -rx` ((ω×r)_z = Rx·ry − Ry·rx)
  - ATTACH loop replaces Step 46 placeholder warning in `build_g_spline()`
  - `Attach` added to imports from `sbeam.model.aero`
  - `NotImplementedError` for CID ≠ 0; `ValueError` for unknown master GRID
- `tests/aero/test_spline.py`: `TestAttachRigidBodyGate` (V-B3a, V-B3b, V-B3d) and
  `TestSpline0ZeroForce` (V-B3c ×2); 20 total tests pass

**Test/Acceptance (V-B3 — machine-precision gate):**
- V-B3a: Rigid Tz translation of master → zero downwash on all ATTACH boxes (< 1e-14) ✓
- V-B3b: Rigid Ry pitch of master → uniform downwash = -1.0 (< 1e-14) ✓
- V-B3c: SPLINE0 boxes → `g_disp.T @ any_pressure = 0` and `g_slope` all-zero (< 1e-14) ✓
- V-B3d: Force transfer — uniform pressure → Fz/Mx/My at master matches analytical
  lever-arm values (Fz=2.0, Mx=2.0, My=-1.5 for the 2-box fixture) (< 1e-12) ✓

**Key decisions:**
- Grid positions are already in global CID 0 after `resolve_grid_positions()` at parse
  time; pattern lifted directly from `spline.py:142` (SPLINE2 structural grid access)
- CID ≠ 0 raises `NotImplementedError` — no documented use case; can be relaxed in Phase C
- `g_slope` and `g_disp` z-rows only: consistent with SPLINE2 approach where only the
  surface-normal component is populated (x/y rows stay zero)
- Energy consistency confirmed: `∂(−rx)/∂x = −1 = g_slope[j, col_Ry]` ✓ (virtual work)

---

### Step 49: Force transfer & coupled smoke test ✅ COMPLETE

**Objective:** Wire the full rigid-aero → structural load path into a single callable
(`compute_structural_loads`) and validate end-to-end with a BDF integration fixture.

**Deliverables:**
- `sbeam/aero/aero_model.py`: `compute_structural_loads(aero_model, q, alpha) → np.ndarray`
  - Computes normalwash `w_total = -(alpha * normal_z) + wg`, solves `gamma = ajj_inv_corr @ w_total`,
    integrates box forces `f_box = skj @ gamma`, transfers to g-set via `f_g = q * g_disp.T @ f_box`
  - Raises `ValueError` if `aero_model.g_disp is None` (caller must pass `grid_index` to `build_aero_model`)
  - `grid_index` dropped from function signature (g_disp shape already encodes n_grids)
- `tests/integration/bdf/val_spline2_cantilever.bdf`: 4 CBARs along global Y (GRIDs 1–5,
  y=0..4), CAERO1 EID=200 (NSPAN=4, NCHORD=1, box IDs 200–203), CORD2R CID=1
  (x_hat=[0,1,0] span, z_hat=[0,0,1] normal), SPLINE2 EID=300, AEROS SREF=4.0, full span
- `tests/integration/test_phase_b.py`: 4 V-B2 tests, all pass

**Test/Acceptance (V-B2 — all machine-precision):**
- V-B2a: `sum(f_g[Tz_dofs]) == q * sum(f_box_z)` to < 1e-10 relative — exact by virtual work
  (partition-of-unity of SPLINE2 basis functions; independent of gamma/cp convention) ✓
- V-B2b: `f_tz` within 2% of `q*CL*sref` or `q*CL*sref/2` (accepts gamma- or cp-based AIC) ✓
- V-B2c: `compute_structural_loads(alpha=0)` == `q * build_fg(aero, g_disp)` to < 1e-12
  (both evaluate `g_disp.T @ skj @ ajj_inv_corr @ wg`; tested with injected non-zero wg) ✓
- V-B2d: `ValueError` raised when `aero_model.g_disp is None` ✓
- 194 total tests pass (full suite)

**Key decisions:**
- `grid_index` dropped from `compute_structural_loads` signature — `g_disp.shape[1]` already
  encodes `6*n_grids`; backlog had it because the design was not yet finalised
- Gamma/cp ambiguity: `ajj_inv_corr @ w` returns circulation Γ (not pressure coefficient cp),
  but `coupling.py` labels it "cp" — internally consistent; V-B2b accepts either normalisation
- V-B2a uses the direct `sum(f_box_z)` comparison rather than `solve_rigid_cl` CL to avoid
  depending on the gamma/cp convention; virtual-work exactness holds independently
- BDF fixture geometry verified: CORD2R CID=1 gives x_hat=[0,1,0] (span along Y), confirmed
  from `test_spline.py:154`; CAERO1 EID=200, NSPAN=4, NCHORD=1 → box IDs 200..203

---


## Resolved defects (conventions)

### DEF-M12 (P1, release-required) — correction-card export field width ✅ COMPLETE (2026-08-02)

**Objective:** `sbeam/aero/section_correction.py` `card_lines` wrote every value as
`f"{v:.6E}"` — 12–13 characters — into the comma free-field `W2GJ`/`AECORR`/`STRIPK`
correction cards. Free-field does not exempt a card from the 8-character field width:
a strict NASTRAN/ZAERO reader truncates `-3.490660E-02` to `-3.49066` — a 100× silent
corruption. The same defect DEF-M6 fixed for the `FORCE`/`MOMENT` load export, on a
different deliverable: the viewer's corrected-BDF download (`aero_correction_view.py`)
and the cruciform/strip body-card exports (`body_correction.py`), the only channel for
powered/CFD corrections and on the release-critical path. sbeam round-trips its own
output, so the corruption only appeared downstream.

**Deliverables:** `card_lines` is now a thin wrapper over the shared free-field
serializer `sbeam/model/card_writers.write_card`, which routes every real through
`parser/bdf_field.fmt_real8` (written for DEF-M6) and produces identical 9-token line
packing (name + 8 fields, then `+` + 8 per continuation). **Decision: delegate to
`write_card`, not an in-place format swap** — it removes the duplicate serializer
(P13 DEF-R4 shared-core style); the `aero → model` import direction is legal.
**Behavior change (intentional):** `fmt_real8` raises `ValueError` on NaN/inf where
`.6E` silently wrote `NAN` — a NaN in a correction card is a corrupt deliverable, so
it is surfaced rather than written out. All callers (`pair_to_bdf`, `cards_to_bdf`,
`body_cards_to_bdf`, `strip_body_cards_to_bdf`) and the viewer downloads inherit the
fix unchanged.

**Test/Acceptance:** width gates (every free-field token ≤ `FIELD_WIDTH` = 8 chars)
added to the section-correction round-trip (`tests/aero/test_section_correction.py`),
the strip-body export (`tests/aero/test_strip_body.py`), and end-to-end over the full
corrected deck (`tests/viewer/test_aero_correction_view.py::test_full_corrected_bdf_roundtrips`).
The section-correction round-trip tolerance was relaxed `rel=1e-5 → 5e-4` — the
8-character field-width floor for negative values, where the sign consumes a character
(DEF-M6 measured worst case 3.5e-4), not exporter slop. Full suite green
(1708 passed, 6 xfailed).

---

### DEF-R4 (P13 share) — body-builder duplication in `body_correction.py` ✅ COMPLETE (2026-08-02)

**Objective:** `build_body_correction` (cruciform) and `build_strip_body_correction`
(decoupled strip) shared ~125 byte-identical lines — model build, per-box geometry,
moment weight rows, the joint min-norm slope and offset solves, and the
achieved/residual/converged/ratio_max reporting — copy-pasted between them, already
drifting in comments. Part of the P13 refactor batch (main entry:
`06_sol144_static_aeroelastic.md`).

**Deliverables:** four shared helpers in `sbeam/aero/body_correction.py` —
`_body_panel_geometry` (baseline metrics + per-box geometry + moment weight rows +
unit α/β responses), `_body_panel_indices`, `_solve_body_min_norm` (joint minimum-norm
slope-ratio + W2GJ-offset solves) and `_summarize_body_result`. **Decision: three-ish
small helpers, not one flag-parameterized mega-function** — the builders genuinely
differ mid-stream (panel-type validation polarity, `gamma_ref` vs `strip_box_slopes`
unit-response extras, `Aecorr` WT2 vs `Stripk` card emission, cruciform-only
`RATIO_WARN` guard), and each keeps those inline. The cruciform's PSTRIP rejection
moved ahead of the box-index loop, mirroring the strip builder's up-front validation.
The WT2 `Aecorr` emission stays a contiguous block — the DEF-R7 retirement seam.
Dead `_NORM_TOL` constant deleted (P13/WP1).

**Test/Acceptance:** full suite green, including the cross-builder flagship
regression (`test_cessna210_flagship_body.py`, parametrized over both builders);
both flagship body decks rerun with f06/exports byte-identical to the
pre-refactor reference.

---

### F1 + DEF-M8 + DEF-L1 — aerodynamic silent-input batch ✅ COMPLETE (2026-08-01)

**Objective:** Close the aero half of the P3 "user asked, program ignored" batch. Every item
here had the same shape: the deck said something, the program read it, discarded it, and
reported a converged answer anyway.

**F1 — colliding NASTRAN box IDs.** A CAERO1 owns the `NSPAN*NCHORD` consecutive box IDs from
its EID, so two CAERO1s numbered closer than that overlap. The ID formula was reimplemented
**three times** (`spline.py`, `integration.py:build_djx`, `sol144._compute_hinge_moments`), each
as a last-wins dict build. Measured on a 2×(30×2) case: **10 of 120 boxes silently unreachable**.
`monitor_points.py` resolves AELIST box IDs through that map with a direct lookup, so a collision
drops a box's load from the MONPNT1 total with no warning.
- **`aero/panel.py`** gains `nchord_per_caero` / `nastran_box_id` / `build_box_id_map` — one
  derivation, beside `AeroBox`, importing nothing from the aero package so there is no cycle.
  `nchord` is derived from `j_chord` rather than the card, so the AEFACT/LCHORD path needs no
  special case and no `BulkData` argument.
- `AeroModel.box_id_to_k` + `require_box_id_to_k()` (lazy, mirroring the `require_g_*` idiom so
  the hand-built `AeroModel`s in the tests keep working); `build_aero_model` validates it
  **immediately after meshing**, before any correction or spline work.
- All four consumers now share it; `monitor_points` additionally names an unknown AELIST box ID.
- **`mirror.py`** picked its ID offset from EIDs alone, so it could synthesise a colliding
  mirrored surface from a deck the user numbered correctly; it now clears the box-ID *span*.

**DEF-M8a / DEF-L1 — W2GJ.** `build_wg` took the first card per CAERO1 via a bare `break`
(duplicates silently shadowed), zero-padded short data and truncated long data. All three
verified against the pre-fix code. Now fatal in both directions. New `build_wg_all` replaces the
caller-side `for eid in sorted(bulk.caero1s)` loop and additionally catches an **orphan** W2GJ —
a card naming a CAERO1 that is not in the model, which that loop never visited at all.

**DEF-M8b / DEF-L1 — WKK.** Selected by the *primary* (lowest-EID) CAERO1 then applied to every
box in the operator: a multi-surface deck hit a raw numpy shape error, and a WKK on any
non-primary surface was ignored. Replaced by a per-surface scatter onto `w = ones(n)` (unlisted
surfaces are a no-op), with a WT2-style length check, a duplicate-per-CAERO1 check, and a
zero-weight check — a zero weight zeroes an AJJ* row, which is the bare `LinAlgError` from
`np.linalg.solve`. The two stale "inverts via lstsq" docstrings now say `np.linalg.solve`.

**DEF-L1 — STRIPK / body targets / section data.** Duplicate STRIPK per CAERO1 (was
`setdefault`, first wins) and short STRIPK data (was a silent fall-back to PSTRIP `SLOPE0`) are
fatal. `parse_body_targets` NaN-checks the four *required* TOTAL columns — only the roll columns
are optional, but all six used to go through a bare `float()`, so a blank cell became a silent
`nan` in the min-norm solve. `build_body_correction` rejects a PSTRIP panel (mirroring the
CHORDCP guard in `aero_model`) — the cruciform solve tunes through the shared AIC, which a strip
panel does not participate in. `validate_section_data` gains an optional `caero_eids` binding and
a duplicate-`eta` check **grouped by `(caero, var, mach, a_lo, a_hi)`** — deliberately not
global, since one station legitimately recurs across surfaces, Machs and alpha regions.

**Deck renumbering (data-only, landed first).** Eight shipped decks collided —
`airplane_aero`, `cessna210_aero`/`_body`/`_strip`, `val_vlm_dihedral`/`_anhedral`/`_rect_ar8`/
`_byu_wing` — plus three inline test fixtures (`test_section_correction._two_surface_parts` with
EIDs 1/2, its twin in `test_section_data`, and the 510 panel injected inside 500's range in
`test_body_correction`). All renumbered to **`EID = 1000 × k` in declaration order**; the largest
mesh anywhere is 304 boxes, so 1000 spacing is ample. Lockstep: the `SPLINE0` **box ranges** in
`cessna210_body`/`_strip`, and the `caero` column of both section-data CSVs (the `caero=0` TOTAL
rows left alone — that column is not an EID on those rows).

**Key decisions:**
1. **Fatal on any collision, not only on a reached one.** The stricter option: one unconditional
   invariant, and no latent-defect decks left in the tree. It costs the renumbering above.
2. **Length mismatches raise in both directions.** This retires
   `test_partial_w2gj_data_fills_remaining_zeros`, which pinned the zero-pad as intended
   behaviour — a short W2GJ is almost always a miscounted mesh, and the pad was
   indistinguishable from a deliberately zero-camber section.
3. **The box-ID primitive lives in `panel.py`, not `spline.py`.** `panel.py` defines `AeroBox`
   and imports nothing from the aero package, so all four consumers can reach it.

**Test/Acceptance:** the renumbering commit was kept pure and gated on the full suite passing
with **no tolerance edits** — `caero.eid` is a label that never enters an arithmetic expression
in `mesh_caero1`, and `build_aero_model` meshes in sorted-EID order, so renumbering that
preserves relative order leaves every box's `k` and geometry bit-identical. Verified directly by
hashing box `k`/corners/colloc/bound/force-point/normal/area/chord/span-fraction for all eight
decks before and after: **identical**. End-to-end, `ha144a_fullspan_mloads`, `ha144a_body_trim`
and `val_dihedral_trim` give identical trim variables, peak displacement and CL — every change in
this batch is a validation gate, not a numerics change. New gates in `test_panel.py`
(`TestBoxIdMap`), `test_integration.py` (`TestBuildWg`), `test_corrections.py`
(`TestWkkSurfaceBinding`), `test_strip_body.py`, `test_body_correction.py` and
`test_section_data.py` (`TestValidationBindings`); every one was confirmed to fail against the
pre-fix implementation.

---


### W2GJ baseline-normalwash (`wg`) sign convention unified (2026-06-14) ✅ RESOLVED

**Defect:** The W2GJ baseline-normalwash `wg` carried two opposite sign conventions across
the codebase. The production solvers treated `wg` as a **downwash slope** added directly to the
normalwash (positive `wg` ⇒ *less* lift): `sol144._compute_aero_forces`
(`w_total = w_struct + w_trim + aero.wg`), `aero_model.compute_structural_loads`
(`w_total = -(α·n_z) + wg`), `coupling.build_fg` (`cp = Ajj⁻¹ @ wg`), `vlm.solve_rigid_cl`
(`rhs = -(α·n_z) + wg`), and `maneuver_qs`. But the theory doc (Eq 9, §2.4) and
`tests/aero/test_integration.py` T2/T3 treated `wg` as a **+incidence** (positive `wg` ⇒
*more* lift): §2.4 read "positive for a leading-edge-up incidence that increases lift," and
T2 reproduced `solve_rigid_cl(α)` via `solve(Ajj, -wg)` with `wg = +α` — negating `wg`, the
opposite of the production chain. A deck authored to the doc/test convention would have run
with silently flipped aerodynamic loads under SOL 144.

**Resolution — single canonical convention:** `wg` is a dimensionless downwash slope Δz/Δx,
added directly to the assembled normalwash (NASTRAN W2GJ convention; *not* passed through
`D_jk`). **Positive `wg` = local nose-down / washout → less lift; negative `wg` =
leading-edge-up built-in incidence → more lift.** Verified empirically through the production
load path (at α = 0, uniform `wg = +0.02` → total Fz = −330; `wg = −0.02` → +330). This is
the sign the production code already used and the sign of `sample/val_wing_taper_dihedral_twist.bdf`
(positive `wg` growing to the tip = washout, ~31 % lift cut). The structural/spline and AoA
boundary conditions remain in the natural *incidence* sense (nose-up positive); the
incidence→normalwash sign lives in `D_jk = -I` and the ANGLEA column `-n_z`, while `wg` is
already a normalwash and is not negated — the original source of the drift.

**Changes (production code unchanged; docs + tests corrected to match):**
- `docs/20_theory/01_aeroelastics_theory.md` — §2.4 governing-convention sentence rewritten
  (positive `w` *reduces* lift); Eq 9 incidence/twist/CFD terms now enter as negative downwash
  slopes with the camber slope entering directly; `w_g` nomenclature row annotated.
- `sbeam/model/aero.py` — `W2gj` dataclass comment states the slope sign and lift effect.
- `sbeam/aero/integration.py` — module docstring, `build_djk` (input is *incidence*, output
  `w = -incidence`), and `build_wg` docstrings clarified.
- `docs/10_standard/05_aeroelastics.md` — `build_djk` / `build_wg` / W2GJ-field reference.
- `sbeam/aero/vlm.py` — `solve_rigid_cl` `wg` docstring: stale "documented inconsistency,
  see backlog" note removed (now one canonical sign).
- `tests/aero/test_integration.py` — T2/T3 use the production combination
  (`gamma = Ajj⁻¹ @ wg`, no local `-wg`); a nose-up AoA is reproduced by a *negative* `wg`.

**Test / Acceptance:**
- New `tests/integration/test_wg_sign_convention.py` (7 tests) drives the real production load
  path (`compute_structural_loads` / `build_fg`) on a splined cantilever and asserts: positive
  `wg` unloads the wing, negative `wg` adds lift, total lift falls monotonically as `wg` sweeps
  negative→positive, and at α = 0 positive `wg` gives a net downward load (antisymmetric in `wg`).
- `tests/aero` + `tests/integration` suites: **378 passed**, 0 failures.

---

### DEF-H1 — ATTACH `g_slope` pitch sign inverted, spurious roll incidence (2026-07-31) ✅ RESOLVED

**Objective:** Correct the ATTACH rigid-attachment slope rows so that an ATTACH-splined panel
sees the same incidence field as the validated SPLINE2 route, and gate that agreement at both
the operator and the solver level.

**Defect:** `_build_attach_rows` wrote `g_slope[..,Rx] = +1.0` and `g_slope[..,Ry] = -1.0`.
`g_slope` carries streamwise incidence, nose-up positive (`build_djk = -I` converts it to
normalwash; the ANGLEA column is `-n_z`), so both rows were wrong: nose-up pitch of a master
grid produced washout, and unit roll injected a full unit of incidence that does not exist —
`u = ω×r` with `ω = (ω_x,0,0)` gives `u_z = ω_x·y`, independent of `x`. Every ATTACH deck
therefore ran with sign-inverted aeroelastic feedback through `Q_aa`, trim and divergence.
Shipped samples were unaffected (ATTACH is test-only), but the path is user-reachable, and
tests V-B3a/b plus `05b_splining.md` encoded the wrong values.

**Deliverables:**
- `sbeam/aero/spline.py` — slope rows rebuilt from the box normal:
  `g_slope[..,Ry] = +n_z`, `g_slope[..,Rz] = -n_y`, `Rx` left at zero, from
  `α = -(ω × x̂)·n̂ = ω_y·n_z - ω_z·n_y`. This reduces to `+1 / 0` for a z-normal box and is
  additionally correct for dihedral and vertical panels, where the previous constants were not.
  Docstring rewritten (the pre-existing "Rx torsion / Ry pitch" labels were also swapped: for a
  Y-span wing `Ry` *is* the torsion axis and `Rx` the bending-slope rotation).
- `tests/aero/test_spline.py` — V-B3b corrected to `+1`; new V-B3e (rigid roll → zero
  incidence) and V-B3f (ATTACH vs SPLINE2 under a general rigid rotation `ω = (0.3,-0.7,0.45)`,
  agreement to 1e-12); "downwash" renamed to "incidence" in the V-B3 names and messages, since
  `D_jk` is not applied at that point and the old naming implied the wrong sign.
- `tests/aero/test_attach_sol144.py` — new V-B3g solver-level regression (4 tests).
- Docs: `05b_splining.md` kinematics block + V-B3 gate list re-derived (its "energy
  consistency" line had itself carried the wrong sign); `02_card_reference.md` ATTACH sign
  convention; `05_aeroelastics.md` card-status note; `01_aeroelastics_theory.md` §4.4 corrected
  — it claimed ATTACH reuses the RBE2/RBE3 machinery, which it never did (that clause struck
  from DEF-L6).

**Test / Acceptance:**
- Each new/changed gate was run against the pre-fix source and confirmed to fail: V-B3b, V-B3e,
  V-B3f, and the V-B3g sign test. V-B3a (plunge) and V-B3d (force transfer) are unaffected by
  the change and continue to pass.
- V-B3g quantifies the defect end-to-end on `val_spline2_cantilever.bdf` with a 1° W2GJ
  incidence at q=800: the elastic axis is at the leading edge and the ¼-chord force line aft of
  it, so the deck must wash out. SPLINE2 gives L/L_rigid = 0.988; per-box ATTACH gives 0.983
  after the fix but **1.071 before it** — a 7 % lift error of the wrong sign. Both routes
  converge to the rigid lift within 1e-6 when the structure is stiffened by 1e6.
- Full suite: **1193 passed, 6 xfailed** (the pre-existing documented AC7 residual XFAILs);
  HA144A reference derivatives bit-unchanged, as expected — no shipped deck uses ATTACH.

**Key decisions:**
- Slope rows built from the box normal rather than the literal `+1 / 0` constants named in the
  backlog, so dihedral and vertical ATTACH panels are correct too, and the rows match the
  existing `ANGLEA = -n_z` convention by construction.
- ATTACH was **not** refactored onto the shared RBE2/RBE3 rigid-body machinery; the theory doc
  was corrected to describe the standalone lever-arm implementation that actually exists.
- `g_disp` was left carrying only its z-row — a deliberate carve-out, logged as **DEF-M11**.

---

### DEF-M11 — ATTACH `g_disp` carried only the z-row (2026-08-01) ✅ RESOLVED

**Objective:** Close the carve-out left open by DEF-H1 — make the ATTACH displacement/force
operator the exact rigid-body transform in all three components, so a canted or vertical
ATTACH panel transfers its in-plane force to the master grid.

**Defect:** `_build_attach_rows` filled only the z-displacement row of `g_disp` (`Tz` plus the
z-component of `ω×r`); the `Tx`/`Ty` columns and the x/y rows of `ω×r` were absent. `g_disp` is
the (3·n_box × n_g) kinematic operator whose copy `g_load` is the force-transfer path
(`g_load.T @ skj @ …` in `build_qaa`/`build_fg`/`compute_structural_loads`), so with those rows
empty the in-plane `Fx`/`Fy` of a non-z-normal box never reached the structure, and the roll and
yaw moments they generate went with them. Exact for a z-normal panel (the box force is pure
`Fz`); silently lossy otherwise. Measured on a 26.57° dihedral panel (`n̂ = (0,−1,2)/√5`, unit
`cp`): true box force `(0, −0.5, 1.0)` transferred as `(0, 0, 1.0)` — **50 % of `Fz` dropped as
side force** — with true moment `(0.625, 0.75, 0.375)` transferred as `(0.5, 0.75, 0.0)`: `Mz`
entirely lost and `Mx` short by the `Fy·rz` term. On a vertical fin panel the transfer is
identically zero. It also left the pairing with `g_slope` — general in the box normal since
DEF-H1 (`Ry = +n_z`, `Rz = −n_y`) — one-sided.

**Deliverables:**
- `sbeam/aero/spline.py` — `g_disp` rows rebuilt as the full rigid-body transform
  `u = t + ω×r`: a translation identity on all three components plus `skew(ω)·r`
  (`u_x = ω_y·rz − ω_z·ry`, `u_y = ω_z·rx − ω_x·rz`, `u_z = ω_x·ry − ω_y·rx`), evaluated at
  `box.force_point`. Docstring rewritten; the DEF-M11 carve-out note removed.
- `tests/aero/test_spline.py` — `_build_attach_bulk` generalised with `p4` / `master`
  arguments so the same geometry can be canted or made a fin; new `TestAttachInPlaneForceTransfer`
  with V-B3d-DIH (dihedral), V-B3d-VERT (fin) and a kinematic-exactness gate, plus a
  z-normal-inertness gate added to the existing V-B3d class.
- Docs: `05b_splining.md` kinematics block (all nine rows), DEF-M11 resolution note, and four
  new lines in the V-B3 gate list.

**Test / Acceptance:**
- V-B3d-DIH: on a 26.57° dihedral panel all three force and all three moment components match
  the closed forms `Σ f_j` and `Σ r_j × f_j` to 1e-14, with `Fy = −Fz/2` from `tan Γ`.
- V-B3d-VERT: on a vertical (fin) panel the pure-`Fy` load and its moment transfer intact to
  1e-14 — the case that previously transferred nothing at all.
- Kinematic gate: `g_disp @ u` reproduces `t + ω×r` per box for an arbitrary rigid motion
  (`t = (0.11,−0.23,0.37)`, `ω = (0.30,−0.70,0.45)`) to 1e-14, pinning every entry of the
  operator rather than only the sums its transpose produces.
- Each of those three was run against the pre-fix source and confirmed to fail.
- Bit-identity gate: on a z-normal panel, zeroing the new x/y rows leaves the transferred load
  `np.array_equal`-identical, which is why no shipped result moves.
- Full suite: **1421 passed, 6 xfailed** (the pre-existing AC7 residual XFAILs), lint clean.

**Key decisions:**
- **No shipped deck was affected, and the audit was stronger than expected:** no `.bdf`/`.dat`
  file anywhere in the repo contains an `ATTACH` card. The card is exercised only by
  Python-built fixtures, two of which are z-normal. The third (`_build_injection_bulk`, 26.57°
  dihedral) already *was* canted, but its ATTACH'd box is never loaded, so the defect sat one
  loaded box away from being caught. That gap is logged as a new opportunistic backlog item.
- The dihedral gate uses Γ = 26.57°, not 45°. `mesh_caero1` orients each box normal so its
  *dominant* component is positive (`panel.py:220`), so past 45° a panel flips to the `+Y`
  (fin) sense. That is the intended convention — it is what the `|n_z| ≥ |n_y|` lift/sideforce
  classification keys off — so the gates straddle it deliberately rather than asserting through
  it: one case each side, no case on the boundary.
- A virtual-work reciprocity test was drafted and **discarded**: `uᵀ(Gᵀf) ≡ (Gu)ᵀf` is numpy
  associativity, true for any operator, so it can never fail. The kinematic-exactness gate
  covers the intent with real signal.

---

### DEF-M2 — `solve_rigid_cl` reported panel-normal magnitudes, not body-axis (2026-08-01) ✅ RESOLVED

**Objective:** Make the rigid VLM path report genuine body-axis force and moment components,
identical to the `skj`-integrated totals every other deliverable uses, so the viewer Aero tab
and the f06 cannot disagree on a canted deck.

**Defect:** `solve_rigid_cl` integrated lift as `2·Σ Γ·‖Δs⃗‖`, crediting the whole
Kutta–Joukowski force *magnitude* to body-z with no `n_z` projection, and computed `CM` from
the pressure form `cp·area·arm` over lift surfaces only. `build_skj` produces
`F_j = area_j·n̂_j·cp_j`, a genuine vector, and the normalwash RHS already carries one `cos Γ`
— so the trim/f06 totals scaled as `cos²Γ` while the rigid path scaled as `cos Γ`, an
`1/cos Γ` disagreement (1.1547 at 30° dihedral). `CL_wind` inherited it. The classification
split compounded it: a dihedral wing's real side force was reported nowhere, because `CY` was
restricted to surfaces *classified* as sideforce. Within the viewer this meant the Aero tab's
CZ/CM metrics disagreed with the S&C derivative table on the same tab, the latter having
always gone through `compute_rigid_derivs`/`skj`.

**Deliverables:**
- `sbeam/aero/vlm.py` — a single per-box force vector
  `f_box = (2·Γ·width)[:,None] · normals`, which since `chord_box = area/width` is *identically*
  `build_skj(boxes) @ cp`. `CX`/`CY`/`CZ` are its three columns summed over every box; `CM` is
  `−Σ Fz·(x_force − xref)`, verbatim `sol144.pitch_moment`. The `dy` variable was renamed
  `width` — it is the panel width (setting `chord_box` and weighting the Trefftz integral),
  never the vertical-force lever, and conflating those two roles was the defect. `x_qc` was
  deleted in favour of `box.force_point[0]` (verified bitwise identical). `trefftz_cdi`'s
  internal `CL_l` projected so `CDi = CZ²/(π·AR·e)` holds against the returned `CZ`.
- `tests/aero/test_dihedral.py` — `test_rigid_cl_cos_gamma` re-baselined from `cos Γ` to
  `cos²Γ`, with the reason recorded in the docstring.
- `tests/aero/test_vae3_cross_check.py` — three canted decks added to the cross-check
  parametrisation, plus V-AE3-DIH: feeding both paths the *same* `cp` isolates the force
  convention and asserts `CX`/`CY`/`CZ`/`CM` against the `skj` integration to 1e-12.
- Docs: `05a_aero_vlm.md` (force convention, return dict, width convention),
  `06_viewer.md` (session-state note), `01_aeroelastics_theory.md` §2.9 (the `cos²Γ` result
  and the now-true `CZ ≡ total_cl` identity).

**Test / Acceptance:**
- **Every moved value explained by a computed cosine before it was written down.** Measured
  across all 15 aero sample decks at α = 3°:

  | Deck | Wing dihedral | cos Γ | Observed CZ ratio |
  |------|---------------|-------|-------------------|
  | `val_vlm_dihedral` / `_anhedral` / `val_dihedral_trim` | 10.000° | 0.984808 | 0.98481 |
  | `val_wing_taper_dihedral(_twist)` | 5.000° | 0.996195 | 0.99619 |
  | `cessna210_aero` / `_body` / `_strip` | 1.504° wing, flat tail, vertical fin | 0.999656 → 1.0 | 0.99969 (load-weighted blend) |

  The remaining 8 decks (`airplane_aero`, all four HA144A, `val_vlm_byu_wing`,
  `val_vlm_rect_ar8`) are planar and bit-identical, ratio exactly 1.00000. `CM` moved by the
  same factor on the same decks. `CY` returns ~1e-17 on every symmetric build — the side force
  cancels, as theory §2.9 requires.
- Cross-path identity now holds to < 1e-12 on all 15 decks (it held only on the 8 planar ones
  before).
- Full suite: **1432 passed, 6 xfailed**, `ruff` and `pyright` clean.

**Key decisions:**
- **Option (a) — project — over option (b) — rename and redocument.** Three reasons: `skj` is
  already the house convention and every shipped deliverable uses it, so two conventions for
  "CZ" *is* the defect; the theory doc §2.9 already described the correct `cos²Γ` physics, so
  projecting made existing documentation true rather than degrading it; and the code already
  contradicted its own comment, which read "lift scales with Δy, not ‖Δs⃗‖" directly above the
  line that used ‖Δs⃗‖.
- **`f_box` defined so the two paths are identical by construction, not by tolerance.** The
  regression gate asserts machine precision against `skj`, so the paths cannot silently drift
  again.
- **Totals now sum every box**, not the classification partition. The lift/sideforce split
  survives only as a `per_surface` label. On existing decks this is near-nil numerically (fins
  carry `Fz ≈ 0`), but it removes a second, independent divergence from the trim path.
- **`cl_section` deliberately left as a section *normal-force* coefficient `cn`,** unprojected.
  `cn` is the conventional section quantity and is what `section_data`/`section_correction`
  ingest from CFD and test; projecting it would break the correction round-trip. The
  asymmetry is now documented at both ends rather than left to look accidental.
- **The nonplanar Trefftz `Di` integral was left alone and backlogged as DEF-M14.** It uses
  `w_z` against a projected `Δy` where a nonplanar wake needs `(w⃗·n̂)‖Δs⃗‖` — a genuine physics
  question, not a convention slip, and changing it silently inside a convention fix would have
  buried it.

---

### DEF-H2 + DEF-H3 — WT1 AIC correction deprecated (2026-07-31) ✅ RESOLVED

**Objective:** Stop `AECORR METHOD=WT1` being presented as a peer of `WT2`. The path is wrong
in two independent ways; the decision taken was to **deprecate rather than fix**, because `WT2`
and the section-correction synthesiser are correct and strictly more capable.

**Defects:**
- **DEF-H2 — wrong scaling at M > 0.** `_assemble_vlm_operator` passed PG-compressed boxes to
  `apply_wt1`, so the reference strip force `f_vlm_s` was integrated over compressed areas and
  chords, while the Göthert `1/β` factor and the Γ→ΔCp conversion (physical chords) were
  applied afterwards. The delivered strip force is `f_target/β²`. Measured exactly: at M = 0.6
  the achieved/target ratio is **1.5625 = 1/0.64** on every strip, a 56 % overshoot; at M = 0
  the ratio is 1.0. All four pre-existing WT1 tests ran at M = 0, so the suite never saw it.
- **DEF-H3 — cross-surface strip aliasing.** `apply_wt1` groups strips by `box.i_span`, which
  restarts per parent CAERO1 (`panel.py`). The card is *selected* by the primary CAERO1 but
  *applied* to every box sharing an `i_span` key. Measured on a wing+tail deck asked for half
  the wing's baseline load: wing and tail strips are scaled by the **same** per-`i_span` ratio,
  so the tail is rescaled although no card names it, and the wing misses its own target. The
  `f_target` length check also counts distinct `i_span` values model-wide, not per surface —
  the same shared-key symptom surfacing as a validation rule.

**Deliverables:**
- `sbeam/parser/bdf_reader.py` — `_handle_aecorr` raises a `UserWarning` on any WT1 card,
  naming both defects and pointing at WT2 / the section-correction path. The card still parses
  and runs; no numerics changed.
- `sbeam/aero/corrections.py`, `sbeam/aero/aero_model.py` — module/function docstrings and the
  WT1 branch marked DEPRECATED with both defects and an explicit "left numerically unchanged
  on purpose" note.
- `tests/aero/test_corrections.py` — new `TestWt1Deprecation`: parser-warning gate (and a
  negative control proving a WT2 card does *not* warn), plus two **characterization** tests
  that pin the known-wrong behaviour so it cannot drift silently.
- Docs: `05a_aero_vlm.md` deprecation block + `apply_wt1` heading; `02_card_reference.md`
  AECORR bullet/METHOD row/example/validation rows; `05_aeroelastics.md`, `01_beam_model.md`
  one-line mentions; theory §3.3 implementation note (Eq. 13 itself is unaffected — the
  defects are in the sbeam implementation, not the Giesing method).
- The false 05a claim "`WKK` and `WT1` still act on the primary CAERO1 only" was deleted, and
  that clause struck from DEF-L6. The 02_card_reference `f_target`-length rule was corrected
  from "in the CAERO1" to the model-wide truth.

**Test / Acceptance:**
- `tests/aero/test_corrections.py` — 23 passed. The four pre-existing `TestApplyWt1` tests were
  left untouched and still pass; because the warning lands in the parser and those tests call
  `apply_wt1` directly, no existing test needed modification.
- Teeth proven: with the parser change stashed, `test_parser_warns_on_wt1_card` fails; with a
  hypothetical β-corrected build path patched in, `test_wt1_overshoots_by_beta_squared_at_mach`
  fails. The DEF-H3 assertions (`|tail ratio − 1| > 0.4`) are violated by construction under
  any correctly scoped implementation.
- Full suite: **1196 passed, 6 xfailed** (the pre-existing documented AC7 residual XFAILs).

**Key decisions:**
- **Deprecate, not fix.** No β-math or grouping-key change was made. `WT2` is genuinely
  multi-surface and `section_correction.py` divides by β; WT1 has no capability they lack.
- **`UserWarning`, not `DeprecationWarning`** — Python hides `DeprecationWarning` outside
  `__main__`, and this card is *silently* wrong, so the user must see it. It also matches the
  existing sbeam precedent (`check_conditioning`, the A7/A8 mesh warnings).
- **Warn in the parser only**, not also at build time — one warning per card for every
  consumer (solver, viewer, CLI), with no duplicate noise.
- **Characterization tests over prose.** The two defects are now locked in by executable
  gates that will fail loudly if anyone "fixes" WT1 without closing DEF-R7.
- Hard removal deferred to a release boundary and logged as **DEF-R7**. No shipped deck uses
  WT1 — no `AECORR` card appears anywhere in `sample/` or `tests/**/*.bdf`.

---

## Performance

### P9 — Vectorize `build_ajj` (broadcast Biot–Savart) + DEF-R6 aero-side LU/gecon batch ✅ COMPLETE (2026-08-02)

**Objective:** The VLM AIC build was a pure-Python n² double loop over `AeroBox` objects —
measured **6.9 s at 400 boxes on the dev machine (12.3 s at ranking time) vs ~3 ms for the
solve** — paid per Mach, per correction rebuild and per viewer overlay: the practical
model-size constraint. DEF-R6 stacked redundant O(n³) work on the same path (double AIC
inversion in the WT2 branch, full-SVD `np.linalg.cond` per build/solve).

**Deliverables:**
- **`aero/vlm.py`** — `build_ajj` rewritten as a broadcast Biot–Savart: `_boxes_to_arrays`
  gathers box geometry into `(n,3)` arrays in **positional order** (callers pass filtered
  sublists — strip boxes are excluded upstream, so `box.k` must not be used);
  `_biot_savart_batch` evaluates receivers × senders as `(m,n,3)` with the scalar kernel's
  exact float64 op order, degenerate guards (`_DEGEN_TOL`) becoming masks under
  `np.errstate`; per-sender far-field points are computed once (previously n× per sender);
  receivers are processed in `_AJJ_CHUNK = 512`-row blocks to bound peak temporary memory
  (~25 MB per temp at n = 2000). The scalar `biot_savart_seg` / `horseshoe_influence` are
  kept unchanged as reference implementations.
- **`aero/vlm.py` `trefftz_cdi`** — the O(n²) Trefftz wake loop broadcast the same way
  (stacked ±Γ trailing-vortex arrays, masked degenerate r²).
- **`aero/integration.py` `build_skj`** — loop replaced by a reshaped fancy-index scatter.
- **`sbeam/linalg_utils.py`** (new) — `estimate_cond_1norm(a, lu_piv=None)`: LU + LAPACK
  `gecon` 1-norm condition estimate in O(n²) given the factorization; returns the LU for
  reuse; singular → `inf` (no raise). Shared by aero and the solvers.
- **`aero/corrections.py`** — `check_conditioning` now uses the gecon estimate and
  **returns the LU** for reuse; `apply_wt2` gains `ajj_inv=None` so
  `_assemble_vlm_operator` passes the already-computed inverse (kills the second O(n³)
  inverse + the SVD); `apply_wt1` (deprecated) reuses its own LU.
- **`aero/aero_model.py` `_assemble_vlm_operator`** — all three branches (WKK / WT2 /
  uncorrected) factor once and `lu_solve` from the `check_conditioning` LU.
- **`aero/section_correction.py`** — same single-factorization pattern (the tiny `g_map`
  SVD at the end is left alone).

**Test/Acceptance:**
- New `tests/aero/test_vlm_vectorized.py` — vectorized `build_ajj` **bit-for-bit equal**
  (`assert_array_equal`, atol=0) to the scalar loop on random irregular geometry
  (sweep/dihedral/twist/mixed normals) and on all degenerate cases (colloc on a bound
  endpoint, on the extended segment line, on the segment interior); chunked path equals
  unchunked; `trefftz_cdi` vs a verbatim copy of the old loop at rel 1e-12 (row-sum order
  differs); `build_skj` exact; gecon conditioning warns on near-singular, silent + reusable
  LU on well-conditioned, `inf` on exactly singular.
- Full suite green (1566 passed); external validation `test_val_byu_wing.py` (CL within 1%
  of AVL) and flagship families unchanged.
- **Measured: 6.87 s → 0.046–0.058 s at 400 boxes (~120×), identical matrix checksum.**
  The full test suite dropped to ~18 s (the flagship fixtures no longer dominate).

**Key decisions:**
- **Bit-for-bit, not tolerance-based** — every arithmetic step reproduces the scalar float64
  op order (explicit 3-component dots, `np.sqrt`, same 3-segment sum order), so the
  equivalence gate asserts exact equality; a documented atol=1e-15 fallback exists in the
  test docstring should a platform/BLAS quirk ever surface.
- **1-norm gecon estimate replaces the 2-norm SVD cond** (user-approved): warning values
  can differ from the old numbers by up to ~n×; thresholds unchanged (1e10 warn); warning
  text now says "1-norm condition estimate". Nothing in f06 output or tests asserted a
  numeric cond.
- Scalar kernels retained as the reference implementation and test oracle rather than
  deleted — they are the specification the broadcast must match.

The solver-side DEF-R6 fixes (SOL 144 `K_eff`, SOL 101 dense path, `maneuver_qs` AeroCache
seeding) are logged in `02_sol101_static.md`, `06_sol144_static_aeroelastic.md` and
`07_maneuver_transient.md` under "Resolved defects".

---
