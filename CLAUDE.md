# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository. It holds **rules and pointers only** — status, feature descriptions, and field
tables live in `docs/` (budget: keep this file under ~150 lines; move prose out, not in).

## Project Overview

`sbeam` (Simple Beam FEA) is a Python-based finite element analysis program for beams using
standard NASTRAN BDF input format. It is **not** related to RAM SBeam.

**Mission (2026-08-04):** a FAR/CS-23-style **loads process** on a beam-stick aeroelastic
model — generate maneuver + gust design cases, trim/integrate them, and deliver
monitor/section loads with a traceable critical-case report for stress. SOL 145 flutter +
DLM is the declared phase after loads sufficiency. New work must serve this mission or be
parked (`docs/30_future/02_parked.md`); the working backlog is **GitHub issues**
(milestones = planned releases; mission + milestone map: `docs/30_future/00_backlog.md`;
workflow: `docs/10_standard/08_release_process.md` §2a).

## Architecture boundary (2026-09-05)

**The solver reads a deck and writes results for the cases it is given. It never decides
which cases exist, and it never reduces across runs.** `sbeam/` is the NASTRAN-style
solver core (unit-neutral card fields, per-case physics, within-run envelopes);
`scripts/loads/` is the loads toolchain (case construction, cross-run reduction,
reporting) and *may* know units, atmospheres and regulatory constants. Both ship in every
release — the mission above is the repository's, not the solver package's. Rationale and
the consequences that follow: `docs/10_standard/00_program_overview.md` (Architecture).

## Documentation Map

`docs/00_INDEX.md` is the map. Sections: `10_standard/` (code-standard guides — these must
track code changes), `20_theory/` (analytical references), `30_future/` (backlog + parked +
designs), `40_history/` (completed steps + resolved defects), `50_reviews/` (process
reviews). Authoritative single sources — never duplicate their content elsewhere, link to
them instead:

- **Card fields/defaults/validation:** `docs/10_standard/02_card_reference.md`
- **Module/file structure:** `docs/10_standard/00_program_overview.md` (Project Structure)
- **Verification-case tables (V-suite, VAL2):** `docs/10_standard/00_program_overview.md`
- **Sign/axis/frame/reference-point conventions:** `docs/10_standard/09_conventions.md`
- **Solver behavior and outputs:** the per-solver guides `03`/`04`/`05a`–`05c`
- **Known limitations:** index in `00_program_overview.md`

## Step Completion Requirement (tiered)

**HARD REQUIREMENT — when any backlog item, bug, NIT, or step is closed, its closure tier
must be completed in the same session, and its GitHub issue explicitly closed
(`gh issue close N --comment "Closed by <sha>"` — never rely on `Closes #N` auto-close;
it does not fire on release branches). One commit per closed item, `(#N)` in the subject.
Never batch or defer closure to a later session.**

| Tier | Applies to | Required closure |
|------|-----------|------------------|
| **S** | Small fix, hygiene, docs, sample decks — no behavior change | `CHANGELOG.md` entry + backlog removal + a **one-line** entry under "Resolved defects" in the matching `docs/40_history/` area file |
| **M** | Behavior change to an existing capability | Tier S + update the affected `docs/10_standard/` section(s) |
| **L** | New capability, new card, new physics | Tier S + affected standard docs + **full step format** (Objective, Deliverables, Test/Acceptance, key decisions) in the matching `docs/40_history/` area file + its index `00_completed_development.md` |

Additional rules (from the 2026-08-04 process review — rationale in
`docs/50_reviews/2026-08-04_development_process_review.md`):

1. **Design note before code (physics/L steps):** a short note — theory reference,
   conventions-charter citations (`09_conventions.md`), validation target with expected
   numbers, acceptance tolerances — agreed in chat **before** implementation starts.
2. **Benchmark-first definition of done:** a physics step is not done until an end-to-end
   benchmark number (closed-form, NASTRAN, or AVL) passes in CI, written **with** the
   feature. Green unit tests alone are demonstrated insufficient (AE13).
3. **Generalize on first find:** a defect fix must sweep the same defect class across the
   codebase in the same change, and add an invariant gate where feasible.
4. **Review findings are filed with bodies** in the same session they are raised — a name
   list is not a finding (DEF-L lesson).
5. **No speculative features:** nothing is built without a named validation target or a
   named load case that consumes it (WT1 lesson).

## Development Status

Phase 1 (SOL 101/103) complete; SOL 144 static aeroelastic trim + Phase G0 transient
maneuver loads delivered and release-scoped. Current state: `docs/40_history/` (done),
GitHub issues/milestones (open; map in `docs/30_future/00_backlog.md`). Work happens on
the current `release/X.Y.0` branch, merged to `main` at milestone completion — release
process and branch model: `docs/10_standard/08_release_process.md`.

## Tech Stack

Python with: `scipy`, `numpy`, `matplotlib`, `pandas`, `plotly`, `streamlit`, `csv`.
Run everything with the repo venv: `.venv/bin/python` (plain `python` is not on PATH).

## Structural Theory

Euler-Bernoulli beam theory (no shear deformation); 12 DOFs per CBAR; consistent mass
matrix; uniform torsion GJ/L. Derivations: `docs/20_theory/00_beam_methods.ipynb`.

## Input / Output

- Bulk data: `*.dat`/`*.bdf` (BDF cards); case control: main `*.bdf` (uses `INCLUDE`)
- Results: `*.f06` NASTRAN-style output + per-run CSV/BDF exports
- Per-solver output details: `03_static_analysis.md`, `04_modal_analysis.md`,
  `05c_sol144_maneuver.md` (SOL 144 trim, MLOADS transient, monitor/section loads)

## Supported Cards

Field-level reference (authoritative): `docs/10_standard/02_card_reference.md`.

- **Structure:** CORD2R, GRID, CBAR, PLOTEL, RBE3, RBE2, RBAR, CBUSH, PBAR, PBUSH, MAT1
- **Mass:** CONM2, MASSSET
- **Constraints/loads:** SPC, SPC1, FORCE, MOMENT, LOAD, GRAV
- **Eigenvalue:** EIGRL
- **Aero (Phase A/C):** AEROS, CAERO1, PAERO1, AEFACT, W2GJ, WKK, AECORR, CHORDCP,
  PSTRIP, STRIPK, SPLINE0/2 (+ ATTACH), SET1, AELIST, AESTAT, AESURF, TRIM, TRIMVAR,
  TRIMCON, TRIMOBJ, SUPORT, DIVERG, MONPNT1, MONPNT3, MONSECT, AECOMP, GUSTLF
- **Transient maneuver (G0):** MLOADS, MLDTRIM, MLDCOMD, MLDTIME, MLDPRNT, TABLED1
- **Case control:** SOL, SUBCASE, LOAD, SPC, METHOD, TRIM, MLOADS, MASSSET, GUSTLF,
  DISPLACEMENT, SPCFORCE, OLOAD, FORCE, STRESS, BEGIN BULK, ENDDATA

## Key Constraints

- Sparse solvers throughout — no hard element limit; memory/time are the practical bounds
- CORD2R only (no CORD2C/CORD2S/CORD1R); all internal computation in basic CID 0
- Uniform cross-sections; Euler-Bernoulli only; units are user-defined and must be
  consistent
- GPWG = mass/CG summary (Grid Point Weight Generator). OLOAD = applied-load output
  request. Do not confuse them.

## Module Structure

Packages: `parser/`, `model/`, `assembly/`, `solver/`, `results/`, `aero/`, `viewer/`,
plus `gpwg.py`, `types.py`, `linalg_utils.py`. Import direction:
viewer → solver → assembly → model → parser. The annotated file-level tree is in
`docs/10_standard/00_program_overview.md` (Project Structure) — keep it there only.

## Verification

All solvers must pass closed-form verification (authoritative case tables incl. VAL2
sample-deck gates: `00_program_overview.md`):

- Cantilever tip load: δ = PL³/3EI (SOL 101)
- Simply supported mid-span load: δ = PL³/48EI (SOL 101)
- Cantilever fundamental frequency: f₁ = (1.875²/2π)√(EI/ρAL⁴) (SOL 103)
- Free-free beam: first 6 modes ~0 Hz (SOL 103)

## Reference Material

- NASA-CR-145949
- https://www.sesamx.io/blog/beam_finite_element/
- https://mechanicalc.com/reference/finite-element-analysis
