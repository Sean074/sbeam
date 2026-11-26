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

## Mission (2026-08-04; re-sequenced 2026-09-05; re-stated 2026-11-21, #99)

**sbeam is a NASTRAN/ZAERO-format beam aeroelastic solver for aircraft loads.** It reads a
standard beam-stick deck — structure, mass cases, steady and unsteady (doublet-lattice)
aero, monitor points — with MSC NASTRAN and ZAERO as the reference for every card it
accepts and pyNastran as the parse gate, and writes NASTRAN-style results **and two reduced
models**: a **modal model of the airplane** (generalized M/K, mode shapes at a named
interface set; OP4 + Universal 55) for downstream dynamics — sgear's flexible-airframe
landing analysis is the first consumer — and **generalized aerodynamic forces Q(k, M)**
(OP4) for flutter. On that solver, `sbeam_tools` builds the **FAR/CS-23 and -25 loads
process**: design-case generation, trim and integration, monitor and section loads, and a
traceable critical-case report for stress. The solver never decides which cases exist.

**The flutter solve is external.** [Flaps 2.3.4](https://github.com/Sean074/flaps_env)
(E. E. Meyer, GPL-3.0; tarball and manual in the Library) solves the flutter equations on
the matrices sbeam exports — the Apex→Flaps split. sbeam ships no SOL 145; the 2-DOF p-k
tool (`30_2dflutter`) is the section-level cross-check. **Where MSC has the card, MSC's
layout; where only ZAERO has it, ZAERO's** (#87); sbeam-only extensions go in the deviation
register (#95).

**The route is still solver first, process second** — each rung now has a named consumer.
sloads (its #435) delivers the *early* FAR 23/25 loads with a documented report and a
standard NASTRAN deck that sbeam reads; sbeam's v0.7.0 is the *near-final* loads layer. The
two are not the same deliverable. Process definition: [`loads_process.md`](loads_process.md).

Delivered so far: SOL 101/103; SOL 144 trim + derivatives, balanced maneuvers, MASSCASE
payload sweeps, quasi-steady + free-flight modal transient maneuvers (MANVR), monitor
points and section-cut running loads with per-maneuver envelopes, correction-matched
aerodynamics validated on HA144A and an ATR42-class flagship, the first design-case family
(Pratt gust, #1); and, 16–18 Nov 2026, faithful NASTRAN input (MSC field layouts,
refuse-instead-of-skip, order-independent bulk data, pyNastran cross-parse in CI).

Issues carry the mission tag as labels: `mission:E` essential to the mission path,
`mission:V` valuable (fidelity/usability, not blocking). The 2026-08-02 release-scope
decisions stand (see `docs/40_history/06_sol144_static_aeroelastic.md`). Decision record
for the 2026-11-21 re-cut: [#99](https://github.com/Sean074/sbeam/issues/99).

---

## Milestone map (2026-11-21, #99)

| Milestone | Definition of done | Key issues |
|---|---|---|
| [v0.3.0](https://github.com/Sean074/sbeam/milestone/1) — **Solver capability mature** — ✅ **released `v0.3.0` 2026-10-25** | SOL 144 + MANVR engineering-complete **including lateral**: transient monitors, net_loads decision, thrust-in-trim, DEF-M15/M16 closed, aileron/rudder capability with conventions decided, stable documented output schemas, CBAR pin-release/stress/plane defects closed (DEF-M17/M18/M21), rod element for engine pylon struts, viewer moved out of the solver (#34). | #2, #3, #6, #8–#10, #20, #21, #30, #31, #34, #37, #38, #52–#54 |
| [v0.4.0](https://github.com/Sean074/sbeam/milestone/2) — **Faithful NASTRAN input** — ✅ **released `v0.4.0` 2026-11-22** | What shipped 16–18 Nov (the [compatibility audit](../50_reviews/2026-11-16_nastran_zaero_audit.md): #48, #51, #55, #57–#83, #98) plus the WT2/WKK/CBUSH defects (#72, #96, #97), panel-normal sign convention (#84), MONPNT layouts (#86), round-off noise (#49) and the mass-case construction decided once with sloads (#102 ↔ sloads #436). Tag, then merge `release/0.4.0` to `main`; first colleague install from the tag on the Air. | — (all closed; tagged `v0.4.0`) |
| [v0.4.1](https://github.com/Sean074/sbeam/milestone/7) — **Viewer authoring + reduced-model export** | An engineer authors, runs and reviews every solver capability from the viewer (#11); SOL 103 free-free modal model written as OP4 + Universal 55 at a named interface set, read by pyNastran and by Flaps (#100); ZAERO-layout decision applied (#87); f06 compatibility (#90); docs (#91, #95). | #11 (closed: #95, #87, #90, #91, #100, #104, #106, #107) |
| [v0.5.0](https://github.com/Sean074/sbeam/milestone/3) — **DLM + GAF export** | Complex unsteady AIC anchored to the validated VLM at k = 0 (D0–D3); Q(k, M) over the MKAERO1 Mach×k table as OP4; AMODE Phase 1; matrix store. **Gate:** [`flaps_env/docs/sbeam_handoff.md`](https://github.com/Sean074/flaps_env/blob/main/docs/sbeam_handoff.md) — Goland wing through Flaps at 175.7 m/s / 10.5 Hz; HA145B and NASTRAN-95 D10-02 parity. No flutter solver in sbeam. | #14, #12, #13, #15, #7, #28, #88, #94 |
| [v0.6.0](https://github.com/Sean074/sbeam/milestone/4) — **Dynamic gust loads + sgear load recovery** | RFA state-space, SOL 146 discrete gust + continuous turbulence, Monitor Phase 3 (#16) — gust *loads*; airframe loads recovered from sgear's landing time histories by mode acceleration (#101, `sbeam_tools`). | #16, #101 |
| [v0.7.0](https://github.com/Sean074/sbeam/milestone/6) — **The loads process** | Design-case matrix → run → envelope/critical-case report → downselect → LRA delivery package for stress. Built once on the complete set of case families. Definition: [`loads_process.md`](loads_process.md) | #4, #5, #29, #35, #36, #41–#44 |
| [v1.0.0](https://github.com/Sean074/sbeam/milestone/5) — Hardening | AMODE Phase 2 + hardening scope from #18; interface-stability promise on BDF/case-control/f06/OP4 | #17, #18 |

Unscheduled small items carry the `opportunistic` label and no milestone (#19, #22, #26,
#27, #50, #85, #89, #92, #93) — do them when adjacent, and close them like any other issue.
#25 (G0-d unsteady corrections) stays superseded by the DLM.

**Required convention decisions** (aileron/rudder signs, end-A moment face, prop
handedness, ROLL reference) are checklist blocks inside their consuming issues (#6, #8,
#9, #10, #21) — each is made in the design note of the first step that consumes it, never
invented ad hoc, and lands in `09_conventions.md` with a gate. *Decided 2026-10-24:* ROLL
reference (#8), aileron and rudder signs (#9/#10) — design note
[`designs/lateral_cases_aileron_rudder.md`](designs/lateral_cases_aileron_rudder.md); end-A
face (#21, 2026-10-24); propeller handedness (#6, 2026-10-24) — design note
[`designs/thrust_in_trim_applied_load.md`](designs/thrust_in_trim_applied_load.md) D6, charter
§10. None open. **Bank-angle scope** was
decided 2026-09-05 ([`designs/vn_matrix_23337.md`](designs/vn_matrix_23337.md) O2): out of
scope as a case family, since a steady coordinated turn at load factor n is
aerodynamically identical to a symmetric pull-up at n on this model, and the part that is
not — roll/yaw rate and sideslip — belongs with the lateral work (#10). *Open decisions
2026-11-21:* panel normals (#84), MONPNT layouts (#86), ZAERO layouts (#87), mass-case
construction (#102) — each lands in `09_conventions.md` or the card reference with a gate.
