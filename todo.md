# sbeam — Beta Readiness Todo

sbeam has stronger error handling and test coverage than smodal at equivalent stage. All 441
tests pass. The primary gaps identified in the 2026-05-24 code review are listed below by severity.
Full review findings are in `development_plan_bugs_todo.md` (items R1–R11).

## Rules
- Remove each item from this file **immediately** when it is complete.
- **Before closing any step**, update the relevant file(s) in `docs/` (or `CLAUDE.md` / `README.md`
  if the step touches root-level docs). Never defer documentation.

---

## USER IDENTIFIED CRITICAL - Must fix

No silent-failure bugs equivalent to smodal C-1/C-2/C-3 found. The review confirms no
CRITICAL items. Error handling in `main.py`, `sol101.py`, and `bdf_reader.py` is clean —
no silent `pass` in exception handlers, no fabricated fallback results.

---

## USER IDENTIFIED NICE TO HAVE MINOR - Potential future addition

- **[DEPLOY] Deploy to Streamlit Community Cloud** — smodal has a live public deploy; provides
  shareability and a live demo for contributors.

---

## MAJOR — Must fix or document before beta

Items from the 2026-05-24 code review. Full detail in `development_plan_bugs_todo.md`.

---

## MINOR — Fix in this or next PR

From the 2026-05-24 code review:

Pre-existing MINOR items:

- **[DOC1] README "Known Limitations" section** — no Timoshenko (Phase 1), no buckling, CORD2R
  only, RBE2 lever-arm limitation (pending R1 resolution). Makes constraints visible to first-time
  users.

- **[DOC2] Tutorial worked example in `docs/Methods.ipynb`** — run a model end-to-end against the
  bundled sample BDF and verify identified results against analytical truth. Currently the notebook
  is reference theory only.

- **[VAL1] Viewer pre-solve input validation** — before running SOL 101/103, warn if: zero-length
  elements detected, no SPC defined, **unsupported cards present (e.g. PLOAD1)**, inconsistent
  units flag. Show inline `st.warning` rather than crashing in the solver. **Required before S30
  can be safely deferred — without this, PLOAD1 loads are silently dropped with no user-visible
  error.**

---

## NIT — Optional / next cleanup PR

From the 2026-05-24 code review:

- **[R9] `_DENSE_THRESHOLD` magic number** (`solver/sol103.py:24`) — add a comment or rename to
  make the `200 elements × 6 DOFs` basis explicit.

- **[R10] RBE3 lever-arm simplification undocumented** (`assembly/rbe3.py:27`) — add a docstring
  note and `docs/Beam_model.md` entry: "same-DOF weighted averaging; rotation-to-translation
  coupling across an offset is not applied; use RBAR for kinematically exact rigid connections."

- **[R11] `main.py` CLI at 0% coverage** — add a smoke test that calls `main.main()` with a known
  BDF and checks that an f06 is produced.

Phase 3 — Dynamic Solvers (full scope in `development_plan_bugs_todo.md`):

- **[S26] Step 26: SOL 108 — Direct Frequency Response** — `([K] - ω²[M]){U} = {F(ω)}`; DLOAD /
  RLOAD1 / RLOAD2; FREQ / FREQ1; structural damping (MAT1 GE); FRF plot in viewer.

- **[S27] Step 27: SOL 109 — Direct Transient Response** — Newmark-β integration; TLOAD1 /
  TLOAD2; TSTEP; time-history plot in viewer.

- **[S28] Step 28: SOL 111 — Modal Frequency Response** — modal superposition on SOL 103 basis;
  TABDMP1 modal damping; more efficient than SOL 108 for many-DOF models.

- **[S29] Step 29: SOL 112 — Modal Transient Response** — modal superposition transient;
  Newmark-β in modal coordinates; same output requests as SOL 109.

Future Phase 3+ items (full descriptions in `development_plan_bugs_todo.md`):

- Results export CSV/Excel
- SOL 105 Buckling
- PBARL (standard cross-section shapes)
- NASTRAN f06 import
- Model pre-solve validator panel
- Sample model library
- Parametric sweep
- f06 results comparison (two-file diff)
- **[S30] PLOAD1 Distributed Loads** — *(Deferred: VAL1 must warn on PLOAD1 before this is safe.)*
- **[S33] Timoshenko Shear Correction (PBAR K1/K2)** — *(Deferred: Euler-Bernoulli is the Phase 1
  assumption; K1/K2 silently ignored, correct for slender beams.)*
- **[S34-full] Non-Zero Enforced Displacement Enforcement** — *(Deferred: full enforcement; beta
  only requires the VAL1 validation guard above.)*
