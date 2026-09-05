# Development Process Review — 2026-08-04

**Scope:** critical assessment of sbeam development progress (2026-05-03 → 2026-08-03) with
recommendations on scope control, code standards, documentation, and the user ↔ AI-agent working
process, toward the goal of a FAR/CS-23-style loads capability.

**Evidence base:** full read of `CHANGELOG.md` (~112 unreleased entries), all 8 `docs/40_history/`
files (~6,900 lines), `docs/30_future/00_backlog.md` (57 open items), the process docs
(`CLAUDE.md`, review + release process), and git history (215 commits).

---

## 1. Executive summary

Development velocity is **high** and quality control **works** — but roughly **a third of all
effort is being spent on rework and bookkeeping** rather than forward progress, and the backlog
is not pointed at the stated goal.

- ~95–100 work items completed in 13 weeks (≈7–8/week, solo + AI agent). Core FEA took 5½ weeks;
  aeroelastics has consumed the 8 weeks since.
- **~40% of changelog entries are rework** (fixes to previously-shipped work), concentrated in
  aero coupling: signs, axes, reference points, and splines were each re-fixed 4–8 times.
- **Documentation is as large as the source code** (22.5k doc lines vs 23.6k source lines) and the
  three most-churned files in the entire repository are bookkeeping files (backlog 93 touches,
  CHANGELOG 91, history index 77). 60 of 215 commits (28%) touch no code at all.
- **Only 7 of the 57 open backlog items are essential** to a FAR-23 loads process — and the
  cheapest certification-gust path (Pratt-formula quasi-static gust) is not in the plan at all,
  while a ~50-day DLM/RFA chain is.
- **Nothing has shipped since 0.1.0** — there is not even a git tag for 0.1.0. ~2,500 changelog
  lines sit in `[Unreleased]` because the release gate is milestone-scale and unbounded.

The pain ("development has been long, backlog says lots to go") is therefore partly real and
partly an artifact: 8 weeks to NASTRAN-parity static aeroelastic trim + transient maneuver loads
is objectively fast; what makes it *feel* long is the rework tax, the bookkeeping tax, and a
backlog whose 57 items are mostly not on the critical path. Re-scoping shrinks "to go" from 57
items to roughly a dozen.

---

## 2. Where the time went

| Metric | Value | Source |
|---|---|---|
| Duration / commits | 93 days, 215 commits (May 73, Jun 85, Jul 27, Aug 30) | git |
| Source / test / doc lines | 23.6k / 26.4k (1,518 tests) / 22.5k + 2.6k changelog | wc |
| Phase 1 (SOL 101/103 + viewer) | ~5.5 weeks, ~35 items, ~1 real physics defect per solver | history 01–04 |
| Aeroelastics (A/B/C/G0) | ~8 weeks, ~60 items, ~24 defect IDs in SOL 144 alone (~3/step) | history 05–06 |
| Rework : feature ratio | ~40 : 60 by changelog entry count | CHANGELOG audit |
| Defects found by scheduled reviews | ~75% (four review waves); review precision ~90% | history audit |
| Docs-only commits | 60 / 215 (28%) | git |
| Top-3 churn files | backlog (93), CHANGELOG (91), history index (77) — all bookkeeping | git |
| Viewer share of source | 6.5k / 23.6k lines (27%) | wc |
| Releases shipped | 1 (0.1.0, changelog-only — no git tag exists) | git tag |

**The five biggest rework sinks** (repeat-touch chains from the history/changelog audit):

1. **HA144A trim validation** — ~10 entries; AE1 alone took six sequential fix steps (A, B, C, E,
   F, G) including two root-cause re-diagnoses.
2. **Sign/axis/reference-point conventions** — touched 7 times (A3, A9, AE1-A, AE1-E, A-GUI2a,
   A-GUI2b, DEF-M2). Same class of error, different places.
3. **Splining** — 8 entries culminating in a full SPLINE2 rewrite (AC7) plus a sign inversion
   (DEF-H1) and a missing-loads defect worth 31.5% of lift (DEF-M1).
4. **Body panels** — four iterations in 48 hours (A9 → A9a → A9b → A10), then two more passes six
   weeks later.
5. **W2GJ/AIC corrections** — 8 entries; the wg sign was "unified" twice on the same day; WT1 was
   built (Step 43), deprecated (DEF-H2/H3), and deleted (DEF-R7) — a complete waste cycle.

**The single most important process datum** is recorded in AE13: *"207 aero tests passed while
the HA144A trim was grossly wrong."* Unit gates were green while integration physics was broken;
the NASTRAN/AVL benchmark gates that actually catch this were retrofitted after the failure.

A second recurring pattern: **defects fixed narrowly, then re-found in adjacent code** — DEF-M6
(export field width) recurred as DEF-M12; DEF-M7 (f06 column drift) recurred as DEF-M13 across
five more output blocks before an invariant gate was added.

---

## 3. What is working — keep it

These earn their cost and should survive any process diet:

- **Closed-form verification gates** (V-suite + VAL2 shipped decks with CI-gated tolerances).
  Cheap, objective, and they target the dominant FEA risk: silently wrong results.
- **The critical-review process itself** — 75% of all defects were caught by the four scheduled
  reviews, at ~90% finding precision, with verify-before-acting discipline (the DD-1/3/9 deck
  deletions were correctly declined when their premises failed). The "Common Defect Patterns"
  table is distilled domain knowledge.
- **The backlog open-items-only invariant** — one file to read for current state; excellent
  cross-session context recovery for an AI agent.
- **History files with "key decisions"** — the only durable record of *why* (e.g. mean-axis
  correction rationale); repeatedly used to re-establish context.
- **CI triple gate** (ruff/pyright/pytest) with the 85% coverage floor scoped to solver/assembly/
  parser and the viewer exempted — a good tiering precedent that the rest of the process ignores.
- **Adversarial design review before code** — used once (CHORDCP Γ-unit operator) and it caught a
  wrong plan before implementation. This is the cheapest defect ever found in this project.

---

## 4. Critical findings

**F1 — Convention errors are the #1 rework driver, and there is no conventions authority.**
Signs, axes, reference points, and frames account for the largest defect chains (§2 items 1–5).
Each fix was local; no single document states the project's sign/axis/frame/reference-point
conventions that new code must cite. The one structural fix that was made (AE1-E single-source
sign helper) worked — and was never generalized into a rule.

**F2 — Unit tests systematically pass while integration physics is wrong (AE13).**
Benchmark gates (HA144A, BYU/AVL) were retrofitted after failures rather than written with the
feature. Nothing in the definition of done requires an end-to-end validation number before a
physics step closes.

**F3 — Documentation overhead is 3–10× code effort for small changes.**
A one-line fix requires 4–6 documentation edits across the hard 3-part closure plus the standard
docs. The same information is maintained in up to 5 places in sync: the supported-card list
(CLAUDE.md → 02_card_reference → 01_beam_model → 00_program_overview → 05_aeroelastics), the
module tree (3 places), results-output prose, verification-case list (4 places), and phase
status. "Documentation not updated" carries the same CRITICAL severity as "wrong matrix
assembly."

**F4 — The process is size-invariant.**
A typo fix and a new solver get the identical 11-step review, full test-suite run, full doc
closure, and full step-format history entry. There are no severity/size tiers for *work*, only
for *defects*.

**F5 — The release process is unusable, so nothing ships.**
Release triggers are milestone-scale, the pre-release gate demands an unbounded consistency audit
over ~7,200 doc lines, and 0.2.0 is tied to Phase 3 solvers that are themselves obsolete for the
goal (see F7). Consequence: no tags, no baselines, ~2,500 unreleased changelog lines, and no
stable reference points to measure regressions against.

**F6 — ~35 of ~100 completed items were unplanned insertions**, visible as three parallel
numbering systems (Steps, A/AC/AE letters, P-priorities), four backlog renumberings, a/b step
splits, and step-number collisions (39, 45, 46 each used twice). Planning happens, but the plan
is re-laid mid-flight roughly monthly.

**F7 — The backlog is not pointed at the goal.**
Of 57 open items, ~7 are essential to a FAR-23 loads capability, ~10 valuable, ~40 deferrable
(general-FEA completeness, viewer polish, NASTRAN-compat niceties). Phase 3 (SOL 108/109/111/112)
is superseded by the G0/SOL 146 route for this mission. Meanwhile the plan is **missing**:
- **Pratt-formula quasi-static gust (23.341)** — the mandatory FAR-23 gust cases, achievable with
  the *existing* balanced-maneuver machinery in days, no DLM needed. The only gust path currently
  in the backlog is the ~40–50-day DLM → RFA → SOL 146 chain.
- **V-n envelope / design-case generation** (23.333/.335) — cases are hand-authored decks; no
  item generates the maneuver+gust case matrix from V_A/V_C/V_D, W, altitude.
- **Loads bookkeeping/reporting** — no critical-case selection across the envelope, no
  certification-style loads report.
- Ground/landing loads, engine torque/gyro cases, asymmetric cases — absent, not even marked
  out-of-scope.

**F8 — Backlog hygiene has drifted.** ~40% of the backlog file is closed content (delivery
records, CLOSED post-mortems, empty tables) violating its own open-only rule; DEF-L2–L7 exist
only as a name list with no bodies; `01_static_aero_plan.md` cites a twice-superseded numbering.

---

## 5. Recommendations

Ordered by expected time saved. Items marked **[doc]** are concrete edits for the follow-up
documentation session.

### A. Scope control (biggest lever on "work to go")

**R1. Declare the mission and gate the backlog on it. [doc]**
State the FAR-23 loads objective in CLAUDE.md and the program overview. Re-tag every backlog item
Essential / Valuable / Deferred *against that mission* (the classification exists in this
review's evidence base). New backlog intake must carry the tag. Deferred items move to a separate
"parked" file so the working backlog shows the true distance to goal (~a dozen items, not 57).

**R2. Re-plan gust around the Pratt path. [doc]**
Add a near-term step: quasi-static gust cases via the Pratt gust-alleviation formula on the
existing Step-53 balanced-maneuver machinery. Demote the DLM → SOL 145 → RFA → SOL 146 chain to
an explicit later phase (it remains the right long-term answer for flutter and dynamic gust).
Retire Phase 3 SOL 108/109/111/112 from the plan or mark them superseded.

**R3. Add the missing loads-process spine. [doc]**
V-n/case-matrix generation, load-case bookkeeping + critical-case reporting, engine/asymmetric
cases — as backlog items, or as explicit out-of-scope declarations. A loads program is cases ×
bookkeeping, not only solvers.

**R4. No speculative features.**
Nothing gets built without a named validation target or a named load case that consumes it. WT1
(built → deprecated → deleted) and the removed half-span symmetry support are the cautionary
precedents.

### B. Standards that attack the rework tax

**R5. Write the conventions charter — one page, authoritative. [doc]**
Signs, axes (body/wind/basic), frames, reference points (¼-chord vs ¾-chord, moment reference),
units for Γ/ΔCp, spline slope conventions. Every physics step must cite it in its design note;
every reviewer checks against it. This targets the single largest defect class (F1). Extend
`docs/20_theory/01_aeroelastics_theory.md` or add `docs/10_standard/09_conventions.md`.

**R6. Benchmark-first definition of done for physics steps. [doc]**
A physics step is not done until an end-to-end benchmark number (closed-form, NASTRAN, or AVL)
passes in CI — written *with* the feature, not retrofitted. Unit tests alone are demonstrated
insufficient (F2/AE13). The VAL2 pattern (expected values recomputed from the parsed deck) is
the template.

**R7. Generalize-on-first-find. [doc]**
When a defect is found, the fix must sweep the same defect class across the codebase and, where
feasible, add an invariant gate — in the same change. M6→M12 and M7→M13 each cost a second
discovery-diagnosis-fix cycle that a 20-minute sweep would have avoided.

**R8. Keep the review process; tier it. [doc]**
Full 11-step review only for new solvers/physics and L-size changes. S-size changes (fixes, doc
edits, sample decks) get a 5-line checklist: CI green, closed-form suite green, conventions
charter consulted, defect-class sweep done, closure done. The review's value is proven (75%
catch rate); its uniform weight is not.

### C. Documentation diet (biggest lever on overhead)

**R9. Single source of truth per fact. [doc]**
- Card tables: `02_card_reference.md` is authoritative; CLAUDE.md keeps a bare card-name list
  with a pointer. Delete the duplicated tables in 01/00/05.
- Module tree: one location (overview); CLAUDE.md points to it.
- Results-output prose: lives in the per-solver docs; CLAUDE.md's ~40-line SOL 144/MLOADS
  narrative shrinks to two lines + pointer.
- Verification cases: one list (overview), pointed to by review/release docs.
This collapses the 5-way sync chains that drive the 28% docs-only commit rate.

**R10. Tiered definition of done. [doc]**
- **S (no behavior change / small fix):** CHANGELOG line + backlog move. History gets a one-line
  entry under "Resolved defects", not full step format.
- **M (behavior change, existing capability):** + the affected standard doc section.
- **L (new capability):** the current full 3-part closure, unchanged.
The hard 3-part rule stays — only the *depth* per tier changes.

**R11. CLAUDE.md budget: rules and pointers only (~150 lines).**
Status narrative, phase prose, and feature descriptions migrate to the overview. CLAUDE.md is
loaded every session; every line costs every future session context. **[doc]**

**R12. Backlog cleanup. [doc]**
Purge closed content (~40% of the file), write bodies for DEF-L2–L7 or delete them, fix the
stale P-numbering reference in `01_static_aero_plan.md`, and adopt a single numbering scheme
going forward (plain sequential steps; retire the parallel P-/letter systems).

**R13. Ship monthly, tag always.**
A release is: CI green + closed-form/VAL2 suite green + changelog cut + git tag. Drop the
unbounded doc-consistency audit from the gate (docs consistency is now enforced per-change by
R9/R10 instead). Version numbers decouple from phase completion. First action: tag current
main as 0.2.0 and empty `[Unreleased]`. Baselines make regressions measurable. **[doc]**

### D. User ↔ AI-agent working process

**R14. Design-note-before-code for physics steps.**
The one adversarial design review held (CHORDCP) caught a wrong plan before any code existed —
the cheapest possible defect. Make it standard for physics/L steps: a half-page note stating the
theory reference, conventions-charter citations, the validation target with expected numbers,
and acceptance tolerances — agreed in chat before implementation starts.

**R15. One step per session; acceptance criteria first.**
Sessions that state the acceptance test up front (deck + expected values) converge fastest in
this project's history; sessions that discover the target mid-flight produce the a/b step splits
and next-day defect fixes (A9→A9a). The agent should write the acceptance criteria as the first
artifact of the session and get a yes/no before coding.

**R16. Continuous small reviews over review waves.**
The 2026-07-31 wave found ~24 defect IDs at once because seven weeks had accumulated since the
last review. A short scheduled review every ~2 weeks (or every 5 steps) keeps findings small,
recent, and cheap to fix — and avoids the multi-session "release hygiene batch" cleanups.

**R17. End-of-session closure check.**
The agent verifies the tiered closure (R10) before reporting done — this already mostly happens;
codifying it prevents the "promised follow-on never filed" class (the DEF-M4 dropped follow-up).

---

## 6. Expected impact

Rough, but grounded in the measured ratios:

- Rework is ~40% of entries; the conventions charter (R5), benchmark-first DoD (R6), and
  defect-class sweeps (R7) attack the majority of that class → plausibly **15–20% of total
  effort recovered**.
- Documentation overhead: single-sourcing (R9) + tiered DoD (R10) should roughly halve the
  28% docs-only commit share and the 4–6-file small-fix burden → **~10% recovered**.
- Scope re-pointing (R1–R3) doesn't speed anything up directly — it shortens the *remaining
  path*: the essential set is ~7 existing items + Pratt gust + case-matrix/reporting, i.e. a
  goal-relevant backlog of roughly a dozen items instead of 57.

Combined, a ~25–30% cycle-time improvement is a defensible expectation, with the larger
psychological win being a backlog that visibly converges on the FAR-23 loads goal.

---

## 7. Suggested order for the documentation session

1. R12 backlog cleanup + R1 mission tags (unblocks everything else's bookkeeping)
2. R9 single-source consolidation + R11 CLAUDE.md diet
3. R10 tiered DoD + R8 tiered review — amend CLAUDE.md "Step Completion Requirement" and
   `07_code_review_process.md`
4. R13 release-gate slim-down — amend `08_release_process.md`; tag 0.2.0
5. R5 conventions charter (new doc, seeded from the AE/DEF defect history)
6. R2/R3 backlog additions (Pratt gust, case matrix, reporting)
