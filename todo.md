# sbeam — Beta Readiness Todo

sbeam has stronger error handling and test coverage than smodal at equivalent stage; the primary gaps are Phase 2 model enhancements, Phase 3 dynamic solvers, and supporting infrastructure.


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

No open MAJOR items.

---

## MINOR — Fix in this or next PR

Phase 2 Model Enhancements (full scope in `development_plan_bugs_todo.md`):


Documentation and robustness (concurrent with Phase 2):

- **[DOC1] README "Known Limitations" section** — no Timoshenko (Phase 1),
  no buckling, CORD2R only. Makes constraints visible to first-time users.

- **[DOC2] Tutorial worked example in `docs/Methods.ipynb`** — run a model end-to-end against the
  bundled sample BDF and verify identified results against analytical truth. Currently the notebook
  is reference theory only; a tutorial path is missing (same gap flagged in smodal review).

- **[VAL1] Viewer pre-solve input validation** — before running SOL 101/103, warn if: zero-length
  elements detected, no SPC defined, **unsupported cards present (e.g. PLOAD1)**, inconsistent
  units flag. Show inline `st.warning` rather than crashing in the solver. Analogous to smodal
  M-3. **Required before S30 can be safely deferred — without this, PLOAD1 loads are silently
  dropped with no user-visible error.**

---

## NIT — Optional / next cleanup PR

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
- **[S30] PLOAD1 Distributed Loads** — equivalent nodal load vector for linearly-varying /
  uniform distributed loads along CBAR; viewer distributed-load visualisation. *(Deferred:
  unsupported cards are a documented limitation; VAL1 must warn on PLOAD1 before this is safe.)*
- **[S33] Timoshenko Shear Correction (PBAR K1/K2)** — shear parameter `φ = 12EI/(κAGL²)`;
  falls back to Euler-Bernoulli when K1=K2=0. *(Deferred: Euler-Bernoulli is documented as
  the Phase 1 assumption; K1/K2 fields are silently ignored, which is correct behaviour for
  the slender-beam target use case.)*
- **[S34-full] Non-Zero Enforced Displacement Enforcement** — move non-zero SPC D1/D2 terms to
  RHS before partitioning. *(Deferred: full enforcement; beta only requires the validation
  guard above.)*
