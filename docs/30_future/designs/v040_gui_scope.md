# Viewer scope for v0.4.1 — agreed (#11)

**Status:** ✅ **AGREED 2026-11-26.** The four decisions in §1 were made by the owner, the
child issues of §5 are filed on milestone v0.4.1, and #11 is closed. (Drafted 2026-11-18 as
the "v0.4.0 GUI scope"; the work moved to v0.4.1 and the file name was kept so links hold.)

The survey in §3 was written from the viewer's code and tests and re-checked against the
code on 2026-11-26. It is **not** a hand walk of the running application: a gap listed here
means "no code path found", and a capability listed as present means "code and at least one
test exist", not "it renders correctly". The hand walk (#121) is the check that settles both.

- **Issue:** [#11](https://github.com/Sean074/sbeam/issues/11) — viewer production-ready over the solver
- **Owner:** Sean O'Meara
- **Target of "production-ready" (from #11):** an engineer can author, run and review every
  solver capability from the GUI without hand-editing BDFs.

## 1. Decisions (2026-11-26)

| # | Decision | Answer | Consequence |
|---|---|---|---|
| D1 | Does "author every capability" include the **model** (grids, CBAR, CONM2, CAERO1, SPLINE2, SET1), or only the **cases** built on a loaded model? | **Cases only.** The model arrives as a BDF. | No form for a structural or aero-geometry card is in scope. |
| D2 | Is the viewer a **thin UI over the tools**, as the 2026-09-05 comment on #11 proposes? | **Yes.** Move the logic first, then add forms. | #113 and #114 come before the new forms. |
| D3 | Are all the missing items of §3 in scope for v0.4.1? | **All eleven child issues** are on v0.4.1. | v0.4.1 stays open until each is closed or parked. |
| D4 | What does the journey test have to cover to count? | **#11's bar, unchanged:** every example, every step, one no-op interaction per editable block, project unchanged. | #112. |
| — | When does #11 close? | When the scope is agreed and the children are filed. | The definition of done (§6) is carried by #121. |

## 2. Solver capabilities the viewer has to cover

From `docs/10_standard/02_card_reference.md` and the per-solver guides: SOL 101 static,
SOL 103 modes, SOL 144 trim (determined and over-determined, longitudinal and lateral,
thrust in trim), divergence sweep, MASSCASE mass cases, MANVR transient maneuvers (direct
and modal), GUSTLF static gust cases, monitor points (MONPNT1) and section cuts
(MONSECT), aero corrections (W2GJ, WKK/AECORR, CPINJ, STRIPK body panels), and the f06,
CSV and load-BDF outputs.

## 3. Survey: present and missing (re-checked 2026-11-26)

**Authoring** (`sol144_authoring_ui.py`, `case_control_ui.py`, `aero_correction_view.py`)

| Capability | State | Evidence / issue |
|---|---|---|
| AESTAT, AESURF (both hinge halves), AELIST, SUPORT | Present | `_family_editor` forms; `test_sol144_authoring.py` |
| TRIM, TRIMVAR, TRIMWGT, TRIMINEQ, DIVERG | Present | forms; DIVERG form updated for #73 |
| MANTRIM, MANTIME, MANCMD, MANPRNT, MANVR, TABLED1 + shape generators, increment builder | Present | forms; generators hold their end value since #70 |
| Case control: SOL, subcases, LOAD/SPC/METHOD/TRIM/TRIMWGT/DIVERG/MANVR/MASSCASE/GUSTLF selectors, output requests | Present | `test_case_control_ui.py`; GUSTLF selector since #98 |
| Aero corrections from section data; cruciform and strip body corrections | Present | `test_aero_correction_view.py` |
| **MASSCASE card** (label, scale, ADD / REPLACE / DELETE rows) | **Missing** | selector only; no form, no writer → #115 |
| **AECOMP, MONPNT1, MONSECT** placement | **Missing** | no form, no writer → #116. MONPNT3 is refused by the parser (#86) |
| **GUSTLF card** | **Missing** | a writer exists (`write_gustlf`) but no form → #117 |
| **CPINJ** | **Missing** | no form, no writer, and no sample deck uses it → #119 names a consumer first |
| Thrust in trim (a LOAD set on a TRIM subcase) | Present in case control; FORCE/MOMENT cards themselves are model input (D1) | `_apply_sol144_kind` keeps LOAD for trim |

**Running** (`app.py`)

| Capability | State |
|---|---|
| SOL 101, 103, 144 trim, divergence, MANVR from the Run button, all subcases | Present (flows A–E) |
| Parse errors and parser warnings shown; pre-solve checks | Present (`test_pre_solve_validation.py`) |
| Progress within a long run | A spinner per solve; **no per-subcase or per-time-step progress** → #120 |
| Opening a deck | **Upload only.** The upload is parsed from a temporary file, so a deck with `INCLUDE` cannot load: all six flagship drivers fail (checked 2026-11-26). No list of bundled examples → #111 |

**Results review** (`results_view.py`, `aero_view.py`)

| Capability | State |
|---|---|
| SOL 101 deformed shape, reactions, bar forces and stresses, rod and CBUSH forces | Present |
| SOL 103 mode shapes, modal mass | Present |
| SOL 144 trim variables, three derivative columns, divergence q, hinge moments (rigid, restrained, trimmed since #82), monitor loads, section cuts, deflected shape | Present |
| MANVR time histories, sample slider, monitor and section envelopes, exports | Present |
| Divergence sweep roots, with a density input for speed (#73) | Present |
| Gust condition block (`gust_echo`) | Present since #98 |
| **Injected operating point** (CPINJ echo), **injected aero loads** (LOADINJ) | **Missing**: printed in the f06, not shown → #118 |
| **Applied structural load** (#6) | **Partly**: a column in the monitor table and the section cuts; the resultant block is not shown → #118 |
| **The coefficient frame** (basic axes, and MSC's transformation, #82) | **Missing**: the f06 states it, the results page does not → #118 |

**Tests**

Five AppTest flows exist (A: SOL 101, B: SOL 103, C: SOL 144 dihedral, D: MANVR, E:
free-flight modal dispatch) plus tab-render tests. None loads every bundled example, none
visits every step, and none asserts the project unchanged after a no-op interaction → #112.

## 4. Boundary debt to clear first (from the 2026-09-05 comment on #11)

| # | Item | Where | Issue |
|---|---|---|---|
| C1 | `MANEUVER_PRESETS` is a second, executable statement of what a maneuver case is | `sol144_authoring.py` | #114: move to `sbeam_tools/cases`, before #4 builds the case families there |
| C2 | `validate_sol144_authoring` re-implements the parser's cross-reference pass, because `apply_card` edits a `BulkData` in memory | `sol144_authoring.py` | #113: emit the cards and re-parse; delete the duplicate. Which of the parser's November refusals reached the viewer copy was not checked rule by rule; that list is #113's first task |
| C3 | `resolve_increment_tables` reads solved results to author new cards | `sol144_authoring.py` | #114: a two-pass helper in the tools; the viewer keeps the button |

## 5. Child issues, in order

All are on milestone v0.4.1. The sizes were estimates made before the work.

| Order | Issue | Size | State (2026-11-26) |
|---|---|---|---|
| 1 | #111 — open a deck from a path or the bundled samples, so INCLUDE drivers load | S | Closed |
| 2 | #112 — journey test: every sample deck, every tab, one no-op interaction per editable block, project unchanged | M | Closed. It found #122 and #123 |
| 3 | #113 — re-parse after every authored card; delete `validate_sol144_authoring` (C2) | M | Closed. Loaded cards are not edited in place: Save as new SID |
| 4 | #114 — move maneuver presets and the two-pass increment builder to `sbeam_tools/cases` (C1, C3) | M | Closed |
| 5 | #115 — MASSCASE authoring form | M | Closed |
| 6 | #116 — monitor placement: AECOMP / MONPNT1 / MONSECT forms, drawn on the model | L | Closed |
| 7 | #117 — GUSTLF card form and a gust-case panel over `sbeam_tools/cases/gust.py` | M | Closed |
| 8 | #118 — results page: coefficient frame, injected operating point, injected loads, applied-load block | S | Closed |
| 9 | #119 — CPINJ form, after a consumer is named; parked if there is none (CLAUDE.md rule 5) | M | Parked by the owner 2026-11-26 (`02_parked.md`, Viewer) |
| 10 | #120 — per-subcase and per-time-step progress | S | Closed without code: the longest sample run is 1.4 s |
| 11 | #121 — hand walk and v0.4.1 release cut | S | **Open: needs a person at the running viewer** |

Found while working these, all filed with bodies:

| Issue | What | State |
|---|---|---|
| #122 | The viewer refused to run a GUSTLF subcase | Closed |
| #123 | A no-op in the viewer changed the deck (case-control Apply, export, card forms, second deck) | Closed |
| #124 | Case control was not checked against the model before a run; the viewer kept its own copy of the solver's rules | Closed |
| #125 | Two SUPORT cards on one grid are accepted without a message | Open, opportunistic |
| #126 | `test_run_reproducibility` fails intermittently on round-off in near-zero outputs | Open |
| #127 | The pull-up trim recipe prescribed PITCH = 0 at every load factor | Closed |

Already done from the draft's list: #98 (GUSTLF carried through case-control export, with
the gust condition block on the results page), closed 2026-11-18.

Out of scope by D1: forms for structural and aero-geometry cards.

Related, tracked elsewhere: the correction card design (#72, parked: the Aero Correction
tab writes whichever card is chosen). The ZAERO-named card layouts (#87) and the MONPNT
layouts (#86) are closed; #116 follows #86.

## 6. Definition of done for the viewer in v0.4.1 (carried by #121)

1. Every case capability in §2 can be authored, run and reviewed without editing a BDF by
   hand. "Case" is as D1 fixed it: the model arrives as a BDF.
2. The journey test (#112) passes in CI.
3. One hand walk of the running viewer per release cut, by a person, over the same journey:
   the automated test drives widgets, not a browser, so a page that renders wrongly without
   raising is seen only here.

## 7. What this scope did not do

- No hand walk; no screenshot; nothing was run in a browser.
- No timing of long runs (#120 is inferred from the code having one spinner per solve, and
  starts by timing one).
- No usability judgement: whether the existing forms are *good* was not assessed, only
  whether they exist.
