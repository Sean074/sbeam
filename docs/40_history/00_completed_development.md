# sbeam — Completed Development (index)

Authoritative record of completed steps, key decisions, and resolved defects. **Split by
development area (2026-07-05)** — this file is the index; the full step entries live in the
per-area files below. Every entry keeps the step format (Objective, Deliverables,
Test/Acceptance, key decisions). When a backlog item is closed, its entry is **added to the
matching area file** (and this index's list is updated), per the step-completion rule in
`CLAUDE.md`.

## File map

| File | Area | Contents |
|------|------|----------|
| [`01_program_foundation.md`](01_program_foundation.md) | Foundation, parser & infrastructure | Phase 1 setup; Phase 2 BDF parser; Phase 6 integration & verification; Phase 2 model enhancements — Steps 32 (CORD2R), 36 (RBE2), 37 (CBUSH), 38 (RBAR); dependency map; code & documentation reviews (2026-05-09, 2026-07-05 design review + H1/H2); card-reference documentation — Steps 31 (GRAV), 35 (CONM2); infrastructure — SPARSE, CI1, TEST1, CI2, Step 34, VAL1, R-defects R1–R15/R20; doc/model defects R16–R22, Q5, DOC2 |
| [`02_sol101_static.md`](02_sol101_static.md) | SOL 101 static solver | Steps 7–13 (stiffness, assembly, loads/SPC, solve, recovery, f06, GPWG); Step 23 pin releases; defect B3 (multi-subcase) |
| [`03_sol103_modal.md`](03_sol103_modal.md) | SOL 103 modal solver | Steps 14–16 (consistent mass, eigenvalue solve, f06); defect C-1 (generalised mass) |
| [`04_viewer_gui.md`](04_viewer_gui.md) | Viewer / GUI | Steps 17–22 (model display, interrogation, case-control UI, in-process run, SOL 101/103 results); Step 39 (case-control UI redesign); viewer defects B1, B2, B4; Phase A GUI — Step 44 (aero view), A-GUI–A-GUI5 + A-GUI2a/b (aero + aero-correction tabs); Step 57 (SOL 144 results + case-control rework); Step AC5 (viewer gaps close-out) |
| [`05_aero_vlm_spline.md`](05_aero_vlm_spline.md) | Aerodynamics — VLM & splining (Phases A + B) | Phase A Steps 39–43 (AEROS, meshing, VLM AIC, Skj/Djk/w_g, corrections + AeroModel); S45 (VTP/beta), Step 46 (LU); defects A1, A9 (¼-chord arm), A2+A3, A4 (Prandtl–Glauert), A6 (Trefftz); section corrections A-SC/A-SD/A-SM; body panels A9 (cruciform), A9a/A9b, A10 (PSTRIP strips); Phase B Steps 45–47, 49 (SET1/SPLINE2, spline operators, ATTACH/SPLINE0, force transfer); W2GJ sign convention |
| [`06_sol144_static_aeroelastic.md`](06_sol144_static_aeroelastic.md) | SOL 144 static aeroelastics (Phase C) | Steps 50–56, 58 (Q_aa + ROM, trim cards, trim solve + derivatives, balanced maneuver loads, CHORDCP, divergence, f06/export, dihedral); AE-defect closures (AE1 Steps A/B/C/E/F/G, AE2–AE7, AE9–AE11, AE13, V-AE3, half-span deprecation, A5); monitor points MON1–MON4; 2026-07-03 backlog-closure review; steady close-out Steps AC1–AC4, AC6–AC8 (AE8a/AE8b, warnings, AE14, AE15, CHORDCP) |
| [`07_maneuver_transient.md`](07_maneuver_transient.md) | Transient maneuver loads (Phase G0) | Increment 1 — ZAERO MLOADS card set, Level-1 quasi-steady, open-loop, restrained l-set Newmark-β; Step 59 — shared `reduce_to_aset` a-set reduction (`assembly/reduction.py`) + `Sol103Result` a-set eigendata retention. Future Steps 60–63 (MASSSET, modal basis, free-flight) land here |

Defect-ID legend: **A** (A1–A10) Phase A VLM; **AE** (AE1–AE15) aeroelastic review findings
spanning Phases A/B/C; **R** (R1–R22) 2026-05 review NITs; **B** (B1–B4) Phase 1 viewer bugs;
**C-1** SOL 103 generalised-mass bug; **AC** (AC1–AC8) the 2026-07 steady close-out steps.

## Principles

- Each step produces working, testable code before the next step begins.
- Steps are small enough to complete and verify in a single session.
- Every step that adds solver logic must have an analytical verification case.
- The viewer is developed in parallel with the solver — each solver step has a corresponding display step.
- Documentation is updated as part of each step, not after.
- **The Streamlit viewer (`viewer/app.py`) is the primary entry point for all interactive use.** The CLI (`main.py`) is a secondary, batch-mode interface for automation and headless runs.
