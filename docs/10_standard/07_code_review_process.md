# Code Review Process — sbeam FEA Application

Authoritative process guide for critical code review in this repository.  
All reviews **must** be critical: identify potential defects, non-conformance to documentation,
and deviations from FEA engineering best practice — not just style.

---

## 0. Review Tiers, Scoping, and Cadence (2026-08-04 process review)

The review depth scales with the change, matching the S/M/L closure tiers in CLAUDE.md:

| Change tier | Review required |
|---|---|
| **S** (small fix, hygiene, docs, sample decks — no behavior change) | **Light checklist only:** CI green (ruff/pyright/pytest); closed-form + VAL2 suite green; conventions charter (`09_conventions.md`) consulted if signs/axes/frames are touched; same-class defect sweep done (see rule 3 below); closure tier done. No numbered review steps. |
| **M** (behavior change, existing capability) | Steps 1, 11, plus **only the domain steps (2–10) whose areas the diff touches**. |
| **L** (new capability / new physics / new solver) | The full ordered process below. Physics steps additionally require the **design-note-before-code** review (theory reference, conventions citations, validation target with expected numbers) *before* implementation — the cheapest defect ever found in this project was caught at design review, before any code existed. |

**Scoping rule (all tiers):** domain steps 2–10 apply only to areas the diff touches. Do
not walk the parser checklist for a viewer change.

**Cadence:** hold a scheduled light review every ~2 weeks or every ~5 closed steps,
whichever comes first — small, recent findings are cheap to fix. Do not let findings
accumulate into multi-week review waves (the 2026-07-31 wave surfaced ~24 defect IDs at
once because seven weeks had passed).

**Review hygiene (lessons from the defect history):**

1. **File findings with bodies in the same session they are raised.** A severity-tagged
   name list is not a finding — the DEF-L2–L7 write-ups were lost this way and had to be
   scheduled for re-derivation.
2. **Verify premises with evidence before acting on a finding.** Three of the 2026-07-31
   sample-review deletion proposals had false premises (DD-1/3/9) and were correctly
   declined only because git history was checked first.
3. **Generalize on first find:** when a review confirms a defect, sweep the same defect
   class across the codebase in the same fix and add an invariant gate where feasible
   (DEF-M6→M12 and DEF-M7→M13 each cost a second full discovery cycle).
4. **Integration benchmarks outrank unit tests.** 207 unit tests were green while the
   HA144A trim was grossly wrong (AE13). A physics review must check that an end-to-end
   benchmark gate ships **with** the change.

---

## 1. Objectives

A code review in this project must verify:

| Objective | Why it matters |
|---|---|
| **Correctness** | FEA errors produce silently wrong displacements, forces, frequencies, and stresses |
| **Documentation conformance** | CLAUDE.md mandates docs stay in sync with every code change |
| **BDF card contract** | The parser must never silently drop a supported card or silently accept an unsupported one without a warning |
| **Matrix assembly integrity** | Global stiffness and mass matrices must be symmetric, positive semi-definite, and assembled with correct DOF indexing |
| **Coordinate system consistency** | All internal computations are in global CID 0; input/output transforms must be applied exactly once |
| **Numerical validity** | Sparse solvers, eigenvalue extraction, and matrix conditioning failures surface only for certain model configurations |
| **Maintainability** | Structural analysts will modify this codebase; debt compounds |

---

## 2. Pre-Review Checklist

Complete before reading a single line of diff:

- [ ] Read the PR description / commit message — understand the *intent*, not just the change.
- [ ] Read the relevant `docs/` file for every module touched (see table in CLAUDE.md).
- [ ] Confirm the diff includes documentation updates (`docs/`) if code changed. Flag immediately if absent.
- [ ] Check `docs/30_future/00_backlog.md` — does this PR close a known bug, or introduce a pattern already flagged there?
- [ ] Confirm `docs/40_history/00_completed_development.md` was updated if a step is marked complete.
- [ ] Confirm tests exist for new or changed functions in `assembly/`, `solver/`, or `parser/`.
- [ ] Identify any function whose signature or return shape changed in `assembly/` or `solver/` — these are high-blast-radius changes.

---

## 3. Review Process (Ordered Steps)

### Step 1 — Documentation Compliance Audit

**Non-negotiable per CLAUDE.md**: every code change must update `docs/` in the same session.

Check:

- `docs/10_standard/00_program_overview.md` — any structural change to the module layout, workflow, or supported card set must be reflected.
- `docs/10_standard/01_beam_model.md` — any new or removed BDF card, dataclass field, or data model change must appear here.
- `docs/10_standard/03_static_analysis.md` — any change to SOL 101 assembly, load application, SPC enforcement, or results output must be reflected.
- `docs/10_standard/04_modal_analysis.md` — any change to SOL 103 mass assembly, eigensolver call, or mode normalisation must be reflected.
- `docs/10_standard/06_viewer.md` — any UI control added, removed, or renamed must be reflected.
- `docs/20_theory/00_beam_methods.ipynb` — algorithm derivations must stay consistent with implemented formulations.
- `docs/40_history/00_completed_development.md` — updated if a development step is completed.
- `docs/30_future/00_backlog.md` — updated if a bug is resolved or a step is closed.

The required documentation depth follows the S/M/L closure tier in CLAUDE.md — a Tier-S
change needs only the changelog + backlog + one-line history entry, not a full doc sweep.
**Raise as MAJOR** (blocking) if the closure tier was not completed. Documentation drift
blocks approval but is not the same severity class as wrong results.

---

### Step 2 — BDF Parser and Data Model Review

The parser (`parser/bdf_reader.py`) is the model gateway. Errors here corrupt every downstream result.

- [ ] Every supported card in CLAUDE.md has a corresponding parser branch. Any card not in the supported list must either raise a clear warning or be silently skipped — never silently accepted with wrong field counts.
- [ ] Field indices are zero-based free-format or fixed 8-column NASTRAN format — verify the field-slicing logic matches the card definition in `docs/10_standard/01_beam_model.md`.
- [ ] Integer IDs (GID, EID, PID, MID, SID) are stored as `int`, not `str`. Mixed types break dictionary lookups silently.
- [ ] `BulkData` container stores each card type in its dedicated dict/list — verify no card is appended to the wrong collection.
- [ ] INCLUDE file resolution: confirm the parser resolves the path relative to the main BDF file, not the current working directory.
- [ ] Duplicate IDs: does the parser warn on duplicate GRID/CBAR/PBAR/MAT1 IDs, or silently overwrite?
- [ ] `CORD2R` chained RID: verify the coordinate system is resolved recursively before any GRID using that CID is transformed.

---

### Step 3 — Matrix Assembly Correctness

Assembly errors in `assembly/stiffness.py` and `assembly/mass_matrix.py` are the highest-risk category — they produce wrong results with no visible error.

**Global DOF Mapping**

- [ ] The DOF index for node `i` must be `6*(node_index) + dof_offset` (0-based) — verify against `assembly/stiffness.py`. An off-by-one here misplaces rows/columns across the entire matrix.
- [ ] Sparse COO triplets `(row, col, val)` must be accumulated with `+=` semantics, not `=`. `scipy.sparse.coo_matrix` sums duplicates at construction; verify no pre-summation elsewhere introduces silent overwrites.
- [ ] The assembled global matrix must be symmetric: `K[i,j] == K[j,i]`. Any element transformation error breaks symmetry. Assert this in tests for non-trivial models.

**Element Stiffness (CBAR / `assembly/stiffness.py`)**

- [ ] The 12×12 local stiffness matrix follows Euler-Bernoulli beam theory (no shear terms). Verify against `docs/20_theory/00_beam_methods.ipynb` for A, I1, I2, J coupling.
- [ ] The transformation matrix T is 12×12 (block-diagonal of two 6×6 rotation matrices). Verify `K_global = T.T @ K_local @ T`.
- [ ] Element length `L` is computed from grid coordinates **after** CORD2R transformation to CID 0 — not from raw BDF coordinates when `CP != 0`.

**Consistent Mass Matrix (`assembly/mass_matrix.py`)**

- [ ] Consistent mass uses the same shape functions as the stiffness. Verify the 12×12 element mass entries against the analytical form in `docs/20_theory/00_beam_methods.ipynb`.
- [ ] CONM2 offset vector must be expressed in CID 0 before adding the 6×6 offset inertia contribution. Verify the parallel-axis theorem application.
- [ ] RBE3 does not add mass — it only distributes loads/DOFs. Confirm `mass_matrix.py` makes no mass contribution for RBE3 elements.

**Constraint Enforcement (SPC / `solver/sol101.py`)**

- [ ] SPC enforcement by row/column deletion must remove both the row and the column for each constrained DOF. Removing only the row leaves a non-square system.
- [ ] SPC reaction recovery: reactions are computed as `f_spc = K_full @ u_full - f_applied`. Verify the full (pre-reduction) stiffness matrix is used, not the reduced one.

---

### Step 4 — Coordinate System and Transformation Review

Coordinate system errors are silent and affect every result.

- [ ] **Input transform (GRID CP):** GRID coordinates in a non-zero CP must be transformed to CID 0 before assembly. Verify `model/grid.py` and `assembly/coord_transform.py` do this at model-build time, not at solve time.
- [ ] **Load transform (FORCE/MOMENT CID):** Force/moment vectors in a non-zero CID must be transformed to CID 0 before assembly into the load vector.
- [ ] **CONM2 CID transform:** Offset vector and inertia tensor in a non-zero CID must be transformed to CID 0 before the parallel-axis contribution is added.
- [ ] **Output transform (GRID CD):** Displacements and SPC reactions are stored internally in CID 0. The f06 writer must transform to the CD system for output.
- [ ] **CORD2R construction:** The three defining points (A, B, C) are used to build orthonormal axes. Verify the cross-product convention matches NASTRAN (e → A→B, f is in A-B-C plane, g = e×f normalised).
- [ ] **No double-transform:** Verify no vector is transformed twice. Common pattern: a load assembled in CID 0 should not be re-transformed when extracted for SPC reaction computation.

---

### Step 5 — Solver Correctness

**SOL 101 (`solver/sol101.py`)**

- [ ] Load combination: `LOAD` card scale factors and load SID references must be applied before assembly. Verify `f_combined = Σ(S_i × f_i)` with the correct SID-to-vector lookup.
- [ ] Sparse solve: uses `scipy.sparse.linalg.spsolve` or equivalent — never `np.linalg.inv(K) @ f`, which is numerically unstable and prohibitively expensive for large models.
- [ ] Gravity load (`GRAV`): body force vector is `f = M × a` where M is the consistent mass matrix assembled over all mass-contributing elements. Verify the GRAV acceleration vector is transformed to CID 0 before multiplication.
- [ ] CBAR end-force recovery: element end forces are `f_e = k_local @ T @ u_e` where `u_e` is the 12-DOF element displacement vector extracted from the global solution. Verify sign convention (positive = tension/compression at node A).
- [ ] Stress recovery: PBAR recovery points C, D, E, F are defined in the element cross-section plane. Verify axial + bending stress combination: `σ = P/A ± M1×y/I1 ± M2×z/I2`.

**SOL 103 (`solver/sol103.py`)**

- [ ] Eigensolver call: `scipy.sparse.linalg.eigsh(K_red, M_red, k=n_modes, sigma=0)` with shift-invert for smallest eigenvalues. Verify `sigma=0` is used (or a small positive shift) — without sigma, `eigsh` may fail or return wrong modes.
- [ ] Free-free check: the first 6 eigenvalues of an unconstrained model must be ~0 (rigid body modes). A non-zero rigid body frequency indicates a mass or stiffness assembly error.
- [ ] Mode normalisation: EIGRL `NORM` field selects mass-normalisation (`MAX` or `MASS`). Verify that mass-normalised shapes satisfy `phi^T M phi = I`.
- [ ] Frequency conversion: `f_Hz = sqrt(λ) / (2π)`. Verify no factor-of-2π error between rad/s and Hz in the f06 output.
- [ ] Negative eigenvalues: a negative λ produces an imaginary frequency. Flag this as a model error (non-positive-definite reduced stiffness, typically an unconstrained mechanism) — do not silently take `abs(λ)`.

---

### Step 6 — Constraint Element Review (RBE2, RBE3, RBAR, CBUSH)

- [ ] **RBE3 (`assembly/rbe3.py`):** The constraint matrix distributes the dependent DOF motion as a weighted average of independent DOF motions. Verify the weighting uses the `WT` field, not equal weights. The dependent DOF must be eliminated from the global system (Lagrange multiplier or direct substitution).
- [ ] **RBE2:** All dependent DOFs move rigidly with the independent DOF. Verify the transformation accounts for the lever arm (offset distance × rotation = translation) — missing lever arm gives wrong displacement transfer.
- [ ] **RBAR:** Both nodes are constrained relative to each other. Verify the kinematic coupling includes the full 6-DOF rigid body relationship between the two nodes.
- [ ] **CBUSH (grounded):** A single-node CBUSH grounds the stiffness to the global frame. Verify the K1–K6 diagonal terms are added to the correct 6 DOFs of the single node. CID=0 only — flag any non-zero CID as unsupported.

---

### Step 7 — Error Handling and Robustness

- [ ] The parser must never raise an unhandled `IndexError` or `ValueError` on a malformed card line. Wrap field access in try/except and emit a descriptive warning with the card line number.
- [ ] Missing references: CBAR referencing a non-existent GRID, PBAR, or MAT1 must raise a clear error before assembly — not a `KeyError` at solve time.
- [ ] Zero-length elements: CBAR with coincident nodes must be caught before stiffness assembly. Division by L would produce `inf` stiffness entries.
- [ ] Singular stiffness: if the reduced stiffness matrix is singular (under-constrained model), `spsolve` will return `nan` or raise. Detect this and report "model is not fully constrained" — do not return a garbage displacement vector.
- [ ] Empty results: if a SUBCASE requests output for a SID that produced no results (e.g., wrong LOAD SID), report the mismatch rather than writing a blank f06 section.

---

### Step 8 — Viewer (Streamlit) Review

- [ ] `st.session_state` — any model or results data passed between viewer pages must be stored in `st.session_state`. A local variable does not persist across Streamlit reruns.
- [ ] Cache guards — model parsing and solver execution are expensive. Verify that file-upload and run triggers use re-load guards (compare filename + mtime) to avoid re-solving on every widget interaction.
- [ ] Widget keys — every `st.selectbox`, `st.slider`, and `st.radio` that persists state must have a unique, stable `key=` argument.
- [ ] `st.stop()` after guards — any page section that depends on upstream state (parsed model, solved results) must call `st.stop()` after displaying a "run solver first" warning, not fall through to broken computation.
- [ ] Plotly figure construction — deformed shape and mode shape plots must scale displacements by a user-visible scale factor. Verify the scale factor widget is wired to the plot, not just displayed.
- [ ] f06 file path — verify the viewer writes the f06 to the same directory as the input BDF, or to a user-selected path. Writing to the current working directory silently puts the file in an unexpected location.

---

### Step 9 — Numerical and Scientific Code Standards

- [ ] **Units are explicit:** variable names must convey units where ambiguity exists (`length_m`, `freq_hz`, `stress_pa`, not bare `l`, `f`, `s`). This is especially important in solvers that handle multiple physical quantities.
- [ ] **Array shapes are documented:** functions returning multi-dimensional arrays must state axis conventions (e.g., global stiffness `shape (n_dof, n_dof)`, mode shape matrix `shape (n_dof, n_modes)`).
- [ ] **No silent broadcasting:** numpy broadcasting between `(n,)` and `(n,1)` arrays can produce `(n,n)` results. Verify shapes are explicit where stiffness or mass sub-matrices are accumulated.
- [ ] **Use `np.linalg.solve` / `spsolve` not `inv`:** `np.linalg.inv(K) @ f` is numerically unstable and allocates a dense n×n matrix — always use a solver.
- [ ] **Positive semi-definiteness:** the assembled global K and M must be PSD. A quick check is that all diagonal entries are non-negative. Assert this in tests for any new matrix assembly path.
- [ ] **No magic numbers:** stiffness penalty values, default tolerances, and DOF counts (6 DOFs per node) must be named constants — not bare literals.

---

### Step 10 — Code Quality and Maintainability

- [ ] **Type hints:** all public functions in `assembly/`, `solver/`, `parser/`, and `model/` must have complete type annotations.
- [ ] **Docstrings:** public functions must have a one-line summary plus args/returns description with shape annotations for array parameters.
- [ ] **Function length:** functions longer than ~60 lines should be decomposed. A single function doing parsing + assembly + solving + output is a design defect.
- [ ] **No magic numbers:** DOF counts, stiffness scale factors, default eigenvalue tolerances must be named constants.
- [ ] **No mutable default arguments:** `def f(x, results=[])` is a Python antipattern; flag any occurrence.
- [ ] **Import hygiene:** `solver/` must not import from `viewer/`; `assembly/` must not import from `solver/`. The dependency graph is: `viewer → solver → assembly → model → parser`, with `model` as a pure data layer.

---

### Step 11 — Test Coverage

- [ ] New `assembly/` or `solver/` functions must have a corresponding test in `tests/`.
- [ ] Tests must cover the happy path **and** at least one invalid-input case (wrong shape, empty model, missing reference).
- [ ] Solver tests must compare against analytically known results:
  - Cantilever tip load: `δ = PL³/3EI`
  - Simply supported mid-span load: `δ = PL³/48EI`
  - Cantilever fundamental frequency: `f₁ = (1.875²/2π)√(EI/ρAL⁴)`
  - Free-free beam: first 6 modes must be ~0 Hz
- [ ] Parser tests must cover malformed cards (truncated line, wrong field type, duplicate ID) and confirm graceful error messages.
- [ ] Coordinate transform tests must verify round-trip accuracy: transform to CID 0 and back must recover the original vector to machine precision.
- [ ] Run `pytest tests/ -v` and include pass/fail status in the review.

---

## 4. Issue Severity Classification

| Severity | Label | Criteria | Required action |
|---|---|---|---|
| **Critical** | `[CRITICAL]` | Produces wrong results, data loss, silent card drop, wrong matrix assembly | Block merge — must fix |
| **Major** | `[MAJOR]` | Unhandled exception path, missing coordinate transform, wrong DOF index, missing test for new solver logic, closure tier (docs) not completed | Block merge — must fix or explicitly justify |
| **Minor** | `[MINOR]` | Type hint missing, magic number, suboptimal but correct algorithm | Non-blocking — fix in this PR or open follow-up |
| **Nit** | `[NIT]` | Style, naming, comment wording | Optional |

---

## 5. Common Defect Patterns in This Codebase

| Pattern | Where to look | Risk |
|---|---|---|
| Off-by-one in DOF index (`6*i` vs `6*(i-1)`) | `assembly/stiffness.py`, `assembly/mass_matrix.py` | All matrix entries misplaced; wrong results |
| Element transform `K = T.T @ K_local @ T` inverted to `T @ K_local @ T.T` | `assembly/stiffness.py` | Wrong element contribution |
| CORD2R not applied to GRID before assembly | `model/grid.py`, `assembly/coord_transform.py` | All positions wrong for non-zero CP models |
| CORD2R not applied to FORCE/MOMENT vectors | `assembly/load_vector.py` | Wrong load direction |
| Output displacement not transformed from CID 0 to GRID CD | `results/f06_writer.py` | Wrong output for non-default CD |
| `np.linalg.inv(K)` used for solve | `solver/sol101.py` | Numerically unstable; prohibitively slow |
| `eigsh` called without `sigma=0` | `solver/sol103.py` | Wrong or missing low-frequency modes |
| RBE3 lever arm omitted | `assembly/rbe3.py` | Wrong displacement transfer at offset |
| CONM2 inertia in local CID not transformed | `assembly/mass_matrix.py` | Wrong rotational inertia contribution |
| `spsolve` result not checked for NaN | `solver/sol101.py` | Singular model returns garbage displacements silently |
| Parser silently ignores unknown card | `parser/bdf_reader.py` | Supported cards dropped without warning |
| Zero-length CBAR not caught before assembly | `assembly/stiffness.py` | `inf` stiffness entries corrupt global matrix |
| Docs not updated after step completion | Any module | Documentation drift |

---

## 6. Review Output Format

Every review finding must be written as:

```
[SEVERITY] file.py:line_number — Short description of the issue.
WHY: Explain the defect or risk in one sentence.
FIX: Concrete suggestion (code snippet if helpful).
```

Example:

```
[CRITICAL] assembly/stiffness.py:143 — DOF index computed as 6*gid instead of 6*node_index.
WHY: Grid IDs are not required to be contiguous starting from zero; using gid directly misplaces
     rows/columns in the sparse matrix for any model where GIDs don't start at 0 or have gaps.
FIX: Build a node_index_map = {gid: i for i, gid in enumerate(sorted(bulk.grids))} at assembly
     start and use node_index_map[gid] * 6 as the DOF offset.
```

---

## 7. Final Approval Gate

A PR may be approved **only** when:

- [ ] All `[CRITICAL]` and `[MAJOR]` items are resolved or explicitly accepted with documented justification.
- [ ] `pytest tests/ -v` passes with no failures.
- [ ] All four closed-form verification cases pass (cantilever static, simply-supported static, cantilever frequency, free-free modes).
- [ ] The closure tier (CLAUDE.md S/M/L table) is complete for every item the change closes.
- [ ] `docs/30_future/00_backlog.md` and `docs/40_history/` are consistent with the step status.

---

## 8. References

| Resource | Purpose |
|---|---|
| `docs/10_standard/00_program_overview.md` | Overall program standard, developer and user guide |
| `docs/10_standard/01_beam_model.md` | BDF card definitions and data model |
| `docs/10_standard/03_static_analysis.md` | SOL 101 assembly, load application, and results |
| `docs/10_standard/04_modal_analysis.md` | SOL 103 eigensolver and mode shape output |
| `docs/10_standard/06_viewer.md` | Streamlit viewer architecture |
| `docs/20_theory/00_beam_methods.ipynb` | Euler-Bernoulli stiffness and mass matrix derivations |
| `docs/40_history/00_completed_development.md` | Record of completed steps and key decisions |
| `docs/30_future/00_backlog.md` | Open bugs and backlog |
| `CLAUDE.md` | Project conventions and documentation requirement |
| NASA-CR-145949 | Beam element formulation reference |
| https://www.sesamx.io/blog/beam_finite_element/ | Beam FE theory reference |
| https://mechanicalc.com/reference/finite-element-analysis | FEA reference |
