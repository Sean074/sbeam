# sbeam — Beta Readiness Todo

sbeam has stronger error handling andtest coverage than smodal at equivalent stage; the primary gaps are Phase 2 capability and infrastructure.


## Rules
- Remove each item from this file **immediately** when it is complete.
- **Before closing any step**, update the relevant file(s) in `docs/` (or `CLAUDE.md` / `README.md`
  if the step touches root-level docs). Never defer documentation.

---

## USER IDENTIFIED CRITICAL - Must fix

No silent-failure bugs equivalent to smodal C-1/C-2/C-3 found. Error handling in `main.py`,
`sol101.py`, and `bdf_reader.py` is clean — no silent `pass` in exception handlers, no fabricated
fallback results.

---

## USER IDENTIFIED NICE TO HAVE MINOR - Potential future addition

- **[DEPLOY] Deploy to Streamlit Community Cloud** — smodal has a live public deploy; provides
  shareability and a live demo for contributors.

---

## MAJOR — Must fix or document before beta

Phase 2 — Dynamic Solvers (full scope in `development_plan_bugs_todo.md`):

- **[S26] Step 26: SOL 108 — Direct Frequency Response** — `([K] - ω²[M]){U} = {F(ω)}`; DLOAD /
  RLOAD1 / RLOAD2; FREQ / FREQ1; structural damping (MAT1 GE); FRF plot in viewer.

- **[S27] Step 27: SOL 109 — Direct Transient Response** — Newmark-β integration; TLOAD1 /
  TLOAD2; TSTEP; time-history plot in viewer.

- **[S28] Step 28: SOL 111 — Modal Frequency Response** — modal superposition on SOL 103 basis;
  TABDMP1 modal damping; more efficient than SOL 108 for many-DOF models.

- **[S29] Step 29: SOL 112 — Modal Transient Response** — modal superposition transient;
  Newmark-β in modal coordinates; same output requests as SOL 109.

---

## MINOR — Fix in this or next PR

Phase 2 Model Enhancements (full scope in `development_plan_bugs_todo.md`):

- **[S30] Step 30: PLOAD1 — Distributed Loads** — linearly-varying / uniform loads along CBAR;
  equivalent nodal load vector; viewer distributed-load visualisation.

- **[S33] Step 33: Timoshenko Shear Correction (PBAR K1/K2)** — shear parameter
  `φ = 12EI/(κAGL²)`; falls back to Euler-Bernoulli when K1=K2=0.

- **[S34] Step 34: Non-Zero Enforced Displacements** — SPC D1/D2 fields; move non-zero terms to
  RHS before partitioning.

Documentation and robustness (concurrent with Phase 2):

- **[DOC1] README "Known Limitations" section** — max 200 CBAR elements, no Timoshenko (Phase 1),
  no sparse solver, no buckling, CORD2R only. Makes constraints visible to first-time users.

- **[DOC2] Tutorial worked example in `docs/Methods.ipynb`** — run a model end-to-end against the
  bundled sample BDF and verify identified results against analytical truth. Currently the notebook
  is reference theory only; a tutorial path is missing (same gap flagged in smodal review).

- **[VAL1] Viewer pre-solve input validation** — before running SOL 101/103, warn if: zero-length
  elements detected, no SPC defined, unsupported cards present, inconsistent units flag. Show
  inline `st.warning` rather than crashing in the solver. Analogous to smodal M-3.

---

## NIT — Optional / next cleanup PR

Future Phase 3+ items (full descriptions in `development_plan_bugs_todo.md`):

- Sparse solver (remove 200-element ceiling)
- Results export CSV/Excel
- SOL 105 Buckling
- PBARL (standard cross-section shapes)
- NASTRAN f06 import
- Model pre-solve validator panel
- Sample model library
- Parametric sweep
- f06 results comparison (two-file diff)
