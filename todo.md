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

S40–S45 and A2+A3 are complete. Remaining items below.

---

### [A1] VLM lift-slope systematic under-prediction — root-cause + fix

**Files:** `sbeam/aero/vlm.py` (`horseshoe_influence` lines 56–101, `solve_rigid_cl`)

CL_α is 3–8% below analytical references (Polhamus, lifting-line) and the deficit
**grows** with mesh refinement on an elliptic planform — this rules out pure
discretisation error and points to a systematic bias in the induced-downwash kernel
(trailing system over-predicts downwash at ¾c).

**Fix:**
- Validate against Katz & Plotkin Table 12-x (rectangular wings, several AR) and the
  Warren-12 planform (CL_α = 2.743, CM_α = −3.10).
- Diagnose: compare single-strip limit (strip theory), check trailing-leg semi-infinite
  start-point (should begin at ¼c, not at the leading edge), verify Biot-Savart trailing
  kernel against closed-form.
- Add an elliptic-planform convergence regression test asserting
  `CL_α → 2π/(1+2/AR) ± 2%` for AR ∈ {6, 8, 10} — this test currently fails and is
  the acceptance gate.

---

### [A7] Cosine chordwise spacing helper + NCHORD < 4 warning

**Files:** `sbeam/aero/panel.py:67–71` (`mesh_caero1` chord-fraction block);
`sbeam/aero/aero_model.py` (`build_aero_model` pre-solve checks)

`mesh_caero1` only supports uniform chordwise spacing (linspace); cosine
LE-concentrated spacing requires a hand-built LCHORD/AEFACT. No warning fires for low
NCHORD, which produces unconverged pitching moments.

**Fix:**
- Add `cosine_chord_fractions(n: int) -> list[float]` helper in `panel.py` that returns
  LE-concentrated cosine breakpoints (NASA SP-405 / DeJarnette), usable as an AEFACT list.
- Emit `UserWarning` in `build_aero_model` when any CAERO1 has NCHORD < 4.

**Test/Acceptance:** Warning fires for NCHORD = 2; cosine fractions sum to 1.0 and
values are monotonically LE-concentrated vs uniform; CM convergence with NCHORD
demonstrated in at least one integration test.

---

### [A8] Box aspect-ratio pre-solve warning

**Files:** `sbeam/aero/aero_model.py` (`build_aero_model`) or `sbeam/aero/panel.py`

After the A8 sample-model fix, box ARs are correct in the shipped BDFs, but no runtime
warning exists to catch future user models with degenerate box sizing.

**Fix:**
- After meshing all CAERO1s, compute per-box AR = spanwise edge / chordwise edge.
- Emit `UserWarning` listing the CAERO1 EID and box count where AR < 0.5 or AR > 2.0.

**Test/Acceptance:** A test model with NSPAN=2/NCHORD=8 (high AR) triggers the warning;
`airplane_aero.bdf` (mean AR ≈ 0.99) does not.

---

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
