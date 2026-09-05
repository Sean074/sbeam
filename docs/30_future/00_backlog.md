# sbeam — Mission & Milestone Map

**The working backlog lives in GitHub issues** (migrated 2026-09-05): every open item is
an issue at <https://github.com/Sean074/sbeam/issues>, carrying its full body (objective,
deliverables, acceptance, effort, convention-decision checklists). Milestones are planned
releases; the process is `docs/10_standard/08_release_process.md` §2a. **This file holds
no item bodies** — the pre-migration backlog with all bodies is preserved in git history
(`git log -- docs/30_future/00_backlog.md`). Items not on the mission path live in
[`02_parked.md`](02_parked.md) as before — real but unscheduled, and deliberately **not**
issues; activating one means opening an issue for it and deleting the parked entry.

**Numbering:** issue numbers (`#N`) replace step numbers for new work; `docs/40_history/`
entries reference `#N` going forward. Existing Step 1–68 references stand; no new step
numbers are assigned.

---

## Mission (2026-08-04)

**A FAR/CS-23-style loads process on a beam-stick aeroelastic model:** generate the
maneuver + gust design cases from the flight envelope, trim/integrate each one, and
deliver monitor/section loads with a traceable critical-case report for downstream stress
work. Delivered so far: SOL 144 trim + derivatives, balanced maneuvers, MASSSET payload
sweeps, quasi-steady + free-flight modal transient maneuvers (MLOADS), monitor points and
section-cut running loads with per-maneuver envelopes, and correction-matched aerodynamics
validated on HA144A and an ATR42-class flagship. **SOL 145 flutter + DLM (Phase D) is the
declared phase after loads sufficiency.**

Issues carry the mission tag as labels: `mission:E` essential to the mission path,
`mission:V` valuable (fidelity/usability, not blocking). The 2026-08-02 release-scope
decisions stand (see `docs/40_history/06_sol144_static_aeroelastic.md`).

---

## Milestone map (2026-09-05)

| Milestone | Definition of done | Key issues |
|---|---|---|
| [v0.3.0](https://github.com/Sean074/sbeam/milestone/1) — SOL 144 + MLOADS engineering-complete | Full FAR/CS-23 loads process **including lateral**: gust cases, case-matrix generation, cross-case envelope + critical-case report, transient monitors, thrust-in-trim, DEF-M14/M15/M16 closed, aileron/rudder capability with conventions decided | #1–#10 |
| [v0.4.0](https://github.com/Sean074/sbeam/milestone/2) — GUI production-ready | A loads engineer can author, run and review every v0.3.0 capability from the viewer without hand-editing BDFs; scripted GUI journey test in CI | #11 (scoping) |
| [v0.5.0](https://github.com/Sean074/sbeam/milestone/3) — DLM + SOL 145 flutter | GAF export, AMODE Phase 1, DLM D0–D3 anchored to the VLM at k=0, PK flutter, matrix reuse store | #12–#15 |
| [v0.6.0](https://github.com/Sean074/sbeam/milestone/4) — Dynamic gust loads | RFA state-space, SOL 146 discrete gust + continuous turbulence, Monitor Phase 3 — completes the dynamic loads process | #16 |
| [v1.0.0](https://github.com/Sean074/sbeam/milestone/5) — Full flutter, dynamic flight & gust loads | AMODE Phase 2 + hardening scope from #18; interface-stability promise on BDF/case-control/f06 | #17, #18 |

Unscheduled small items carry the `opportunistic` label and no milestone (#19–#28) — do
them when adjacent, and close them like any other issue.

**Required convention decisions** (aileron/rudder signs, end-A moment face, prop
handedness, bank-angle scope, ROLL reference) are checklist blocks inside their consuming
issues (#4, #6, #8, #9, #10, #21) — each is made in the design note of the first step that
consumes it, never invented ad hoc, and lands in `09_conventions.md` with a gate.
