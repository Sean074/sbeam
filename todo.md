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
