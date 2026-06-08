# sbeam — Beta Readiness Todo

sbeam has stronger error handling and test coverage than smodal at equivalent stage.
493 tests pass (as of 2026-05-26). The primary gaps identified across the code reviews
are listed below by severity. Full review findings are in `development_plan_bugs_todo.md`.

## Rules
- Remove each item from this file **immediately** when it is complete.
- **Before closing any step**, update the relevant file(s) in `docs/` (or `CLAUDE.md` / `README.md`
  if the step touches root-level docs). Never defer documentation.

---

## NIT — Optional / next cleanup PR

### [R21] `check_spc_enforced_displacements` unconditional (`solver/sol101.py:255`)

Called even when `spc_sid` is `None`; works safely by accident (`dict.get(None, [])`
returns `[]`). Intent is unclear.

**Fix:** Add `if spc_sid is not None:` guard.

### [R22] Private function imports in `main.py` (`main.py:8`)

`_build_f06_sol101_text` and `_build_f06_sol103_text` are imported by leading-underscore
private names. A rename in `f06_writer.py` silently breaks the entry point.

**Fix:** Drop underscores in `f06_writer.py` (promote to public), or add public aliases.

---

## DEPLOY — Nice to have

- **[DEPLOY] Deploy to Streamlit Community Cloud** — provides a live demo URL for the README.

---

## Phase A — Static Aeroelastics (VLM)

Steps 39–44 implement the steady vortex-lattice aerodynamic layer. Full design
rationale in `static_aero_plan.md`. Sequence: 39 → 40 → 41 → 42 → 43 → 44(optional).
Each completed step must update `docs/completed_development.md` and
`development_plan_bugs_todo.md` in the same session (per `CLAUDE.md`).

---

### [S40] ✅ CAERO1/PAERO1/AEFACT parsing + `panel.py` box meshing — COMPLETE

**Files:**
- `sbeam/model/aero.py` — add `Caero1` (eid, pid, cp, nspan, nchord, lspan, lchord,
  igid, p1: tuple, x12, p4: tuple, x43), `Paero1` (eid, pid stub), `Aefact` (sid,
  data: list)
- `sbeam/model/bulk_data.py` — add `caero1s`, `paero1s`, `aefacts` dicts
- `sbeam/parser/bdf_reader.py` — `_handle_caero1()` (single continuation: P1/X12 on
  main, P4/X43 on cont); `_handle_paero1()`; `_handle_aefact()` (multi-continuation
  fraction list, same accumulation pattern as SPC1/RBE2)
- `sbeam/aero/__init__.py` *(new)*
- `sbeam/aero/panel.py` *(new)* — `AeroBox` dataclass (k, caero\_eid, corners 4×3,
  colloc 3, bound\_a 3, bound\_b 3, area, normal 3, chord, span\_frac) +
  `mesh_caero1(caero, paero, aefacts, cord2rs) -> list[AeroBox]`.
  Resolve P1/P4 via `to_global()` from `assembly/coord_transform.py`; interpolate
  trapezoidal corners; bound vortex at ¼c, collocation at ¾c; area from cross-product;
  outward normal upward (+z for flat wings).
- `tests/parser/test_aero.py` — add CAERO1/PAERO1/AEFACT round-trip tests
- `tests/aero/__init__.py` *(new)*
- `tests/aero/test_panel.py` *(new)* — geometric assertions per KA1

**Acceptance (KA1):** 1×1 box: total area == X12 × span; colloc at exactly 3/4 of
chord; bound vortex at exactly 1/4 chord. N×M rectangular mesh: total area == planform
area; all corner coords match analytic trapezoidal interpolation. Assert placement
directly — off-by-half-box is a silent, fatal error.

---

### [S41] ✅ Steady VLM AIC `vlm.py` — symmetric + antisymmetric images — COMPLETE

**Files:**
- `sbeam/aero/vlm.py` *(new)*
  - `biot_savart_seg(p, a, b) -> np.ndarray` — normalwash at p from finite vortex
    segment a→b of unit strength (Biot–Savart)
  - `horseshoe_influence(colloc, box, parity=1) -> float` — single AIC entry;
    `parity=+1` adds mirror image (symmetric lift), `parity=-1` adds opposed image
    (antisymmetric/roll)
  - `build_ajj(boxes, parity=1) -> np.ndarray` — n_box × n_box AIC matrix at k=0
  - `solve_rigid_cl(boxes, alpha, parity=1) -> dict` — solve flow-tangency for rigid
    wing at AOA `alpha`; return `{cp, cl_section, CL, CM}`
  - Trailing legs: extend to x = +1000 × max_chord (large-but-finite cutoff)
- `tests/aero/test_vlm.py` *(new)*

**Acceptance (V-A1, V-A2):**
- Rectangular wing AR=5, 4×10 mesh: `C_Lα` within 5 % of `2πAR/(AR+2)` (lifting-line limit)
- Mesh refinement 4×10 → 8×20: `C_Lα` monotonically converges
- `parity=-1` uniform incidence: net lift ≈ 0, rolling moment ≠ 0
- Isolated horseshoe self-induced downwash matches closed-form Biot–Savart value
- SP-405 swept/tapered sample planform (V-A2): `C_Lα` and `C_M` within 5 %

---

### [S42] Integration matrices `Skj`, `Djk`, and baseline normalwash `w_g`

**Files:**
- `sbeam/model/aero.py` — add `W2gj` dataclass: `sid`, `caero_eid`, `data: list`
  (per-box dimensionless normalwash slopes, length = nspan × nchord)
- `sbeam/model/bulk_data.py` — add `w2gjs: dict`
- `sbeam/parser/bdf_reader.py` — `_handle_w2gj()` (multi-continuation list; same
  pattern as AEFACT)
- `sbeam/aero/integration.py` *(new)*
  - `build_skj(boxes) -> np.ndarray` — (3·n\_box × n\_box) area-weighted force
    integration matrix: box `cp` → box resultant forces
  - `build_djk(boxes) -> np.ndarray` — (n\_box × n\_box) deflection/slope → downwash
    (for rigid k=0; reused unchanged by Phase D DLM)
  - `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray` — (n\_box,) baseline normalwash
    from W2GJ card; zero if no W2GJ present
  - **Convention:** all downwash / normalwash quantities are **dimensionless slope**
    (Δz/Δx); document this at every definition site (risk KA3)
- `tests/aero/test_integration.py` *(new)*

**Acceptance (V-A4):**
- Flat plate (no W2GJ): `w_g == 0` vector
- Uniform incidence via `w_g`: reproduces Step 41 rigid-AOA span loading to tolerance
- Linear twist distribution: section load varies linearly in span
- `Skj`-integrated total force == direct circulation sum (consistency round-trip)

---

### [S43] AIC corrections (`corrections.py`) + `AeroModel` container

**Files:**
- `sbeam/model/aero.py` — add `Wkk` (sid, caero\_eid, data: list) and `Aecorr`
  (sid, method: `'WT1'`|`'WT2'`, caero\_eid, target: list) dataclasses
- `sbeam/model/bulk_data.py` — add `wkks`, `aecorrs` dicts
- `sbeam/parser/bdf_reader.py` — `_handle_wkk()`, `_handle_aecorr()` (multi-cont list)
- `sbeam/aero/corrections.py` *(new)*
  - `apply_wkk(ajj, wkk_data) -> np.ndarray` — diagonal multiplicative: `AJJ* = Wkk·AJJ`
  - `apply_wt2(ajj, cp_target) -> np.ndarray` — pressure matching; returns corrected
    `AJJ*⁻¹`; uses `np.linalg.lstsq`; warns if `cond(AJJ) > 1e10`
  - `apply_wt1(ajj, skj, f_target) -> np.ndarray` — force/moment matching; returns
    corrected `AJJ*⁻¹`; same conditioning guard
- `sbeam/aero/aero_model.py` *(new)* — `AeroModel` dataclass (boxes, ajj,
  ajj\_inv\_corr, skj, djk, wg, parity) + `build_aero_model(bulk, parity=1) -> AeroModel`
- `tests/aero/test_corrections.py` *(new)*

**Acceptance (V-A3):**
- No correction: rigid `CL` matches Step 41 directly (identity)
- `WT1` round-trip: feed inviscid spanwise load as target → load reproduced to tol
- `WT2` round-trip: feed inviscid cp as target → cp reproduced to tol
- Non-unit `Wkk` (1.5 on first box): that box's lift scales by 1.5, others unchanged
- High-condition-number input triggers a `warnings.warn` (tested with `pytest.warns`)

---

### [S44] Viewer — rigid aero box mesh + `cp` overlay *(optional, recommended)*

**Files:**
- `sbeam/viewer/aero_view.py` *(new)*
  - `build_aero_box_figure(bulk, aero_model) -> go.Figure` — box mesh overlay on
    structural geometry + per-box `cp` colour map + section-load strip chart
  - `_add_box_mesh(fig, boxes)` — Plotly `Scatter3d` quads (4 corners + close)
  - `_add_cp_contour(fig, boxes, cp)` — colour each box by its cp value
  - `_add_corrected_vs_inviscid(fig, boxes, cp_inv, cp_corr)` — overlay when AECORR active
- `sbeam/viewer/app.py` — add "Aero" tab / panel when `bulk.caero1s` is non-empty
- `tests/viewer/test_aero_view.py` *(new)* — AppTest smoke test (no crash, no exception)

**Acceptance:** `AppTest` renders without `at.exception` for a sample 4×10 rectangular-wing
BDF; visual smoke-test only (no numerical values asserted).

---

## Phase 3 — Dynamic Solvers (full scope in `development_plan_bugs_todo.md`)

- **[S26] SOL 108 — Direct Frequency Response**
- **[S27] SOL 109 — Direct Transient Response**
- **[S28] SOL 111 — Modal Frequency Response**
- **[S29] SOL 112 — Modal Transient Response**

Future Phase 3+ items (full descriptions in `development_plan_bugs_todo.md`):

- Results export CSV/Excel
- SOL 105 Buckling
- PBARL (standard cross-section shapes)
- NASTRAN f06 import
- Model pre-solve validator panel
- Sample model library
- Parametric sweep
- f06 results comparison (two-file diff)
- **[S30] PLOAD1 Distributed Loads** — *(VAL1 complete: viewer warns on PLOAD1 cards. S30 can be implemented.)*
- **[S33] Timoshenko Shear Correction (PBAR K1/K2)** — *(Deferred: K1/K2 ignored for slender beams.)*
- **[S34-full] Non-Zero Enforced Displacement Enforcement** — *(Deferred: full enforcement post-beta.)*
