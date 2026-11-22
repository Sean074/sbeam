# v0.4.0 GUI scope — draft for agreement (#11)

**Status:** 📝 **DRAFT 2026-11-18. Nothing here is agreed, and no child issue has been filed.**
It is a proposal for #11, written from a survey of the viewer's code and tests. It is
**not** a hand walk of the running application: a gap listed here means "no code path
found", and a capability listed as present means "code and at least one test exist", not
"it renders correctly". The hand walk in §6 is the check that settles both.

- **Issue:** [#11](https://github.com/Sean074/sbeam/issues/11) — viewer production-ready over the v0.3.0 solver
- **Owner:** Sean O'Meara
- **Target of "production-ready" (from #11):** an engineer can author, run and review every
  v0.3.0 solver capability from the GUI without hand-editing BDFs.

## 1. What needs deciding

| # | Decision | Why it matters | Proposal |
|---|---|---|---|
| D1 | Does "author every capability" include the **model** (grids, CBAR, CONM2, CAERO1, SPLINE2, SET1), or only the **cases** built on a loaded model? | The viewer reads a model and displays it; it has no form for any structural or aero-geometry card. Authoring a model from nothing is a different product from authoring cases. | Cases only. The model arrives as a BDF. State this in #11's definition of done. |
| D2 | Is the viewer a **thin UI over the tools**, as the 2026-09-05 comment on #11 proposes? | Three pieces of case-construction logic live in the viewer today (§4). Building more forms on them deepens the duplication. | Yes. Move the logic first (C1–C3), then add forms. |
| D3 | Are the five items in §3 "Missing" all in scope, or only those a flight-loads user needs first? | They are unequal in size. Monitor placement and MASSCASE authoring are the two that block a loads run without a text editor. | All five, in the order of §5. |
| D4 | What does the journey test have to cover to count? | #11 sets the bar (every example, every step, one no-op interaction per editable block, project unchanged). Today five flows exist (§3). | Adopt #11's bar unchanged. |

## 2. Solver capabilities the viewer has to cover

From `docs/10_standard/02_card_reference.md` and the per-solver guides: SOL 101 static,
SOL 103 modes, SOL 144 trim (determined and over-determined, longitudinal and lateral,
thrust in trim), divergence sweep, MASSCASE mass cases, MANVR transient maneuvers (direct
and modal), GUSTLF static gust cases, monitor points (MONPNT1/3) and section cuts
(MONSECT), aero corrections (W2GJ, WKK/AECORR, CPINJ, STRIPK body panels), and the f06,
CSV and load-BDF outputs.

## 3. Survey: present and missing

**Authoring** (`sol144_authoring_ui.py`, `case_control_ui.py`, `aero_correction_view.py`)

| Capability | State | Evidence |
|---|---|---|
| AESTAT, AESURF (both hinge halves), AELIST, SUPORT | Present | `_family_editor` forms; `test_sol144_authoring.py` |
| TRIM, TRIMVAR, TRIMWGT, TRIMINEQ, DIVERG | Present | forms; DIVERG form updated for #73 |
| MANTRIM, MANTIME, MANCMD, MANPRNT, MANVR, TABLED1 + shape generators, increment builder | Present | forms; generators hold their end value since #70 |
| Case control: SOL, subcases, LOAD/SPC/METHOD/TRIM/TRIMWGT/DIVERG/MANVR/MASSCASE selectors, output requests | Present | `test_case_control_ui.py` |
| Aero corrections from section data; cruciform and strip body corrections | Present | `test_aero_correction_view.py` |
| **MASSCASE card** (label, scale, ADD / REPLACE / DELETE rows) | **Missing** | selector only; no form |
| **MONPNT1, MONPNT3, MONSECT, AECOMP** placement | **Missing** | no form |
| **GUSTLF** card and selector | **Missing, and dropped on export** | filed as #98 |
| **CPINJ** | **Missing** | no form |
| Thrust in trim (a LOAD set on a TRIM subcase) | Present in case control; FORCE/MOMENT cards themselves are model input (D1) | `_apply_sol144_kind` keeps LOAD for trim |

**Running** (`app.py`)

| Capability | State |
|---|---|
| SOL 101, 103, 144 trim, divergence, MANVR from the Run button, all subcases | Present (flows A–E) |
| Parse errors and parser warnings shown; pre-solve checks | Present (`test_pre_solve_validation.py`) |
| Progress within a long run | A spinner per solve; **no per-subcase or per-time-step progress** |
| A list of the bundled examples to open | **Missing**: upload only. #11's journey test needs "every bundled example loaded" |

**Results review** (`results_view.py`, `aero_view.py`)

| Capability | State |
|---|---|
| SOL 101 deformed shape, reactions, bar forces and stresses, rod and CBUSH forces | Present |
| SOL 103 mode shapes, modal mass | Present |
| SOL 144 trim variables, three derivative columns, divergence q, hinge moments (rigid, restrained, trimmed since #82), monitor loads, section cuts, deflected shape | Present |
| MANVR time histories, sample slider, monitor and section envelopes, exports | Present |
| Divergence sweep roots, with a density input for speed (#73) | Present |
| **Gust condition block** (`gust_echo`) | **Missing** (#98) |
| **Injected operating point** (CPINJ echo), **injected aero loads** (LOADINJ), **applied structural load** (#6) | **Missing**: printed in the f06, not shown |
| **The coefficient frame** (basic axes, and MSC's transformation, #82) | **Missing**: the f06 states it, the results page does not |

**Tests**

Five AppTest flows exist (A: SOL 101, B: SOL 103, C: SOL 144 dihedral, D: MANVR, E:
free-flight modal dispatch) plus tab-render tests. None loads every bundled example, none
visits every step, and none asserts the project unchanged after a no-op interaction.

## 4. Boundary debt to clear first (from the 2026-09-05 comment on #11)

| # | Item | Where | Proposal |
|---|---|---|---|
| C1 | `MANEUVER_PRESETS` is a second, executable statement of what a maneuver case is | `sol144_authoring.py` | Move to `sbeam_tools/cases/`; the viewer calls it. Do this before #4 builds `sbeam_tools/cases` families, so there is one generator |
| C2 | `validate_sol144_authoring` re-implements the parser's cross-reference pass, because `apply_card` edits a `BulkData` in memory | `sol144_authoring.py` | Emit the cards and re-parse; delete the duplicate. This also closes a gap opened this month: the parser's new refusals (#65, #67, #68, #75, #77) are not applied to cards the viewer injects in memory |
| C3 | `resolve_increment_tables` reads solved results to author new cards | `sol144_authoring.py` | Move to the tools as a two-pass helper; the viewer keeps the button |

## 5. Proposed child issues, in order

Sizes are rough: S under a day, M a few days, L a week or more.

| Order | Child issue | Size | Depends on |
|---|---|---|---|
| 1 | #98 — carry GUSTLF through case-control export; round-trip gate over every repo driver | S | — |
| 2 | Journey test: every bundled example, every tab, one no-op interaction per editable block, project unchanged (#11's bar) | M | an example picker (3) |
| 3 | Example picker: open any deck in `sample/` without uploading | S | — |
| 4 | C2: re-parse after every authored card; delete `validate_sol144_authoring` | M | — |
| 5 | C1 + C3: move maneuver presets and the two-pass increment builder to `sbeam_tools/cases` | M | agree D2 |
| 6 | MASSCASE authoring form (label, scale, op rows; overlay CONM2 picker) | M | 4 |
| 7 | Monitor placement: MONPNT1 / MONPNT3 / MONSECT / AECOMP forms, with the cut or reference point drawn on the model | L | 4 |
| 8 | GUSTLF form and gust condition block on the results page; a button that calls `sbeam_tools/cases/gust.py` | M | 1, 5 |
| 9 | Results page: coefficient-frame statement, injected operating point, injected aero loads, applied structural load | S | — |
| 10 | CPINJ form (steady-pressure injection from a table) | M | 4 |
| 11 | Per-subcase and per-time-step progress for long runs | S | — |
| 12 | Hand walk and release cut (§6) | S | all |

Not proposed, pending D1: forms for structural and aero-geometry cards.

Open items from the audit that touch the viewer and are tracked elsewhere: the correction
card design (#72, parked: the Aero Correction tab writes whichever card is chosen), the
ZAERO-named card layouts (#87), and MONPNT layouts (#86, which item 7 should follow).

## 6. Definition of done for v0.4.0 (from #11, restated)

1. Every capability in §2 that D1–D3 put in scope can be authored, run and reviewed without
   editing a BDF by hand.
2. The journey test of item 2 passes in CI.
3. One hand walk of the running viewer per release cut, by a person, over the same journey:
   the automated test drives widgets, not a browser, so a page that renders wrongly without
   raising is seen only here.

## 7. What this draft did not do

- No hand walk; no screenshot; nothing was run in a browser.
- No timing of long runs (item 11 is inferred from the code having one spinner per solve).
- No usability judgement: whether the existing forms are *good* was not assessed, only
  whether they exist.
