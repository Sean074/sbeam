# sbeam — Development Plan, Bugs & To-Do

Authoritative backlog of **open** work only — bugs, planned development, and design proposals,
in priority order. Updated as part of every session that completes a step — never deferred.
Completed steps live in `docs/40_history/00_completed_development.md`; nothing closed is
summarised here. When an item is promoted to a formal step, give it a step number (next free
number is **Step 67**; Steps 62–66 are assigned below) and apply the step format
(Objective, Deliverables, Test/Acceptance).

---

## Strategic aim & priority order (critical design review, 2026-07-05)

**Aim:** a production-like aeroelastic process able to analyse **different maneuvers and
payload conditions**. The SOL 144 phase must be sufficiently developed that **early design
analysis** can be completed with it (trim, balanced/transient maneuver loads, mass-case
sweeps, section loads, usable authoring/output surface). The phase after that is
**SOL 145 flutter + the DLM** (Phase D).

### Priority order

**Revised 2026-07-31 (this update):** the DEF-H items that held P1/P2 are closed, and the
open findings of the 2026-07-31 critical review had never been ranked. The table below is
renumbered contiguously and now carries the open DEF-M defects. Ordering principle:
**silently wrong numbers on reachable inputs before new capability** — an early-design
process is only useful if its trim, inertial loads and exported deliverables are right —
then the Tier 1 capability sequence, then refactor-before-Phase-D, then Tiers 2–3.
Amended later the same day: the **2026-07-31 sample-problem review** items slot in at
P6–P8 — cheap CI insurance and the flagship sample after the correctness batches (whose
P3 deliverable-integrity fixes the flagship's exports inherit), before new capability.

| P | Item | Where | Effort (est.) | Rationale |
|---|------|-------|--------------|-----------|
| P1 | Step 64 / DEF-M1 — inject SPLINE0/unsplined box forces into the trim equilibrium | Defects | ~2–3 d | Decision already taken (2026-07-31). The body-panel workflow (A9/A10) is the advertised way to carry residual Cm/Cn, yet those forces are invisible to the force balance and the load export while appearing in printed totals — the trim is not closed on any body-panel deck. |
| P2 | Q4 + DEF-M3 — one mass model for `M_ax` (`build_inertial_cols` → `−M_aa·Φ_r`) | Defects / Q&R | ~1–2 d | Same root cause, resolve together. Today inertial-relief columns ignore CONM2 offsets, products of inertia and CID rotation, and mix lumped with consistent mass — silently wrong balanced-maneuver and transient inertial loads on any realistic mass model. Fix before Step 62 builds on `Φ_r`. |
| P3 | DEF-M deliverable-integrity batch — M5, M6, M7, M10 | Defects | ~1–1.5 d | All cheap, all corrupt what leaves the program: the critical-sample selector/label/column disagree, exported FORCE/MOMENT fields overflow 8-char free field (the advertised stress handoff), the f06 time-history header is misaligned, and the shipped HA144A monitor omits 18.75 % of the inertia. |
| P4 | DEF-M silent-input batch — M4, M8, M9 (+ DEF-R5, DEF-L1, sample-review F1) | Defects | ~2 d | Three "user asked, program ignored" paths: `LOAD` in a TRIM subcase, correction cards dropped/mis-bound, SPC on a rigid-dependent DOF discarded. M9's fix lands once only after R5 ports `sol101` onto `reduce_to_aset`; L1 is the same validation sweep. The 2026-07-31 sample review adds two of the same class: **F1** — CAERO1s with overlapping NASTRAN box-ID ranges silently overwrite in `build_id_to_k` (`spline.py:69-77`; the pre-flagship cessna210 EIDs 100/150/200/250 collide) — and SOL 101 with zero GRIDs running to an empty f06 without warning. |
| P5 | DEF-M2 + DEF-M11 — force/moment convention and ATTACH transfer completeness | Defects | ~1 d | `solve_rigid_cl` reports panel-normal rather than body-axis totals (viewer and f06 disagree on canted decks) and ATTACH `g_disp` carries only the z-row. Both are carve-outs that become wrong answers as soon as dihedral/fin panels are used. |
| P6 | Closed-form CI gates for the four CLAUDE.md verification decks | Samples review | ~0.5 d | `val_cantilever_static`, `val_ss_static`, `val_cantilever_modes`, `val_free_free_modes` reproduce their closed forms today (verified by run, 2026-07-31: 0.004 % / 0.004 % / 0.02 % / RBMs ≤ 4.6e-5 Hz) but are gated only by the theory notebook, which CI never runs. Independent of everything; can land any time. |
| P7 | Step 65 — flagship realistic-airplane SOL 144 sample family + theory doc | Samples review | ~3–5 d | Closes the biggest sample coverage gap: nothing anywhere combines corrected aero + trim + maneuver + mass cases on a realistic airplane, and corrections never reach a trim. Clean of all open defects (SPLINE2 only, no body panels); after P3 so its exports/critical-sample story is clean. |
| P8 | Step 66 — flagship stage 2: body panels into the flagship family | Samples review | ~2 d | Blocked on **P1/Step 64** (unsplined-box forces into the trim balance) and on **P7/Step 65** (the family it extends). Folds `cessna210_body`/`_strip` + their 14+ tests into the flagship. |
| P9 | Monitor Phase 2 — section-cut running loads | Tier 1 | ~2–3 d | The production stress deliverable (per-station Vz/My/Mt); unblocked, independent — can run in parallel with P10–P12. |
| P10 | Vectorize `build_ajj` (broadcast Biot–Savart) (+ DEF-R6) | Tier 1 | ~1–2 d | Measured 12.3 s at 400 boxes vs 3 ms for the solve — the quadratic pure-Python AIC loop is the actual model-size constraint named in CLAUDE.md; ~100× available; paid per Mach, per correction rebuild, per viewer overlay. DEF-R6's redundant O(n³) work is the same hot path. |
| P11 | Step 62 — modal transient solver (prescribed rigid) + fixed-Φ mass gates | Tier 1 (G0 plan) | ~4–5 d | De-risks basis/truncation/recovery before free flight; lands the fixed-Φ mass-case transient capability. Consumes P2's unified mass model. |
| P12 | Step 63 — free-flight rigid-body coupling | Tier 1 (G0 plan) | ~4–5 d | The "different maneuvers" half of the aim: self-balancing transient maneuvers from arbitrary control input. |
| P13 | Viewer — SOL 144 / MLOADS case authoring UI | Tier 1 | ~5–8 d | Early-design usability: today SOL 144 cases must be hand-authored in the BDF; a production process needs the authoring loop closed. Sequenced after Steps 62–63 so it authors the final card surface once. |
| P14 | DEF-R1 refactor batch — decompose `sol144.py` (+ R2, R3, R4; R7 at a release boundary) | Defects | ~2–3 d | `run_sol144_trim` is a ~500-line god function in an 1838-line module that P15/P17 both extend. Do it after Tier 1 stops churning it and **before** Phase D piles on. |
| P15 | `matrix_gaf_export` Phases 1–2 | Tier 2 | ~8 d | External flutter handoff (FLAPS) **and** the declared prerequisite of Phase D (MKAERO1, Mach loop, bundle writers). |
| P16 | `AMODE` Phase 1 (control-surface hinge modes) | Tier 3 | ~7.5 d | Needed before control-surface flutter in SOL 145; Phase 2 is a declared pre-1.0.0 blocker. |
| P17 | Phase D core — DLM (D0–D3) + SOL 145 PK flutter | Tier 3 | ~25–30 d | The declared next phase after SOL 144 sufficiency. Gated on P15. |
| P18 | Phase D cont. — RFA state-space + SOL 146 gust + Monitor Phase 3 | Tier 3 | ~15–20 d | Completes the dynamic loads process (CS-25.341 gust/turbulence monitors). |
| P19 | `matrix_reuse_store` Phases 1–3 | Tier 2 | ~6 d | Real payoff only once envelope sweeps (many Machs × masses × maneuvers) exist — i.e. after P10–P12/P17. Its Phase 0 is stale (see verdicts). |

**Opportunistic / unranked** (small, independent, do when adjacent): SPLINE9 go/no-go
convergence study (~1 d, study only); G0-d unsteady corrections; body fence image method;
load-case envelope viewer; CHORDCP follow-ons; A9 follow-ons; the remaining DEF-L items
(L2–L7 — extrapolation advisory, SUPORT-drop diagnosis, viewer Cp/span-load, f06
presentation, docs-mismatch batch, SYMXZ parity decision; ~1–1.5 d total, independent);
the samples hygiene batch and doc-pointer sweep from the 2026-07-31 sample review
(~1 d total, zero-risk — details in the sample-review section below).
**Deferred:** G0-e (with Phase G ASE), slender-body element (after Phase D), non-aero
Phase 2/3 items.

### Design-review verdicts on the `30_future` documents (2026-07-05)

All six design proposals share the house style (bit-identical-when-absent guarantees,
closed-form gates, resolved decision tables) and none had been reviewed before this pass.
Verdicts:

| Document | Verdict | Notes |
|----------|---------|-------|
| `01_static_aero_plan.md` | **Pruned** (H1, done 2026-07-05) | Phases A–C (Steps 39–58) were all closed but never removed per its own self-removal rule. Now a compact architecture/reference doc: layer diagram, matrix nomenclature, delivered-step map, references, V-case index; the Phase D/E/F/G placeholders retired in favour of `designs/dlm_rfa_flutter_gust.md` and this backlog. |
| `02_static_aero_zaero_review.md` | **Archived** (done, this review) | All 8 ranked goals were folded into Steps 39–58, all closed. Moved to `docs/40_history/archive/`. |
| `designs/matrix_gaf_export.md` | **Viable — schedule (P15)** | Highest-viability aero design: new code over data already computed; no new physics. Its AE4 prerequisite is **stale** — AE4/spline kinematics closed with AC7 (2026-07-05, NASTRAN infinite-beam SPLINE2, rigid-body-exact). Its `reduce_to_aset` §6.1 **landed with Step 59** (2026-07-06, `sbeam/assembly/reduction.py`) — reuse, don't re-extract. |
| `designs/matrix_reuse_store.md` | **Viable — subordinate (P19); Phase 0 deleted** | Rigorous cache-boundary analysis, but its Phase 0 ("build the SOL 144 production dispatch + f06 writer") is **stale** — that surface shipped with Step 56/AE10 and AC5. Re-scope to Phases 1–3 only; schedule when envelope sweeps make caching pay. |
| `designs/dlm_rfa_flutter_gust.md` | **Viable — the Tier 3 core (P17/P18)** | Technically honest, well-gated (Blair 3×3, Sears, typical-section). The k=0 VLM anchoring is the right de-risking move. Its AE4 gate is stale (closed by AC7); the nonplanar kernel terms (T1/T2, I2) remain a genuine research gap, correctly walled behind V-D1-6 (planar-only ships). Needs `g_disp_colloc` (¾-chord displacement spline) at D0. |
| `designs/rbmref_card.md` | **Fold, don't build standalone** | Its `B_target` geometric rigid-basis construction is mathematically the same object as Step 61's `Φ_r`. Step 61 owns the single `build_rigid_modes`; the RBMREF *card* (user-selectable reference point + f06 rigid-mode block) becomes a thin optional wrapper afterwards, if still wanted. |
| `designs/spline9_hermite_beam_spline.md` | **Run the kill-switch study only** | Correctly self-gated: run the coarse-grid convergence study (SPLINE9 vs SPLINE2-with-attached-rotations at 3/5/9 EA stations) FIRST; if SPLINE2 matches within noise, close without implementing. Do not start the card plumbing before the study. |
| `designs/amode_card.md` | **Viable — schedule Phase 1 before flutter (P16)** | Mirrors the proven RBE3 transformation path; V19 analytic gate is unforgeable. Phase 2 (elastic rotating set) honestly rated harder and is a declared 1.0.0 blocker. Open interaction to resolve at implementation: AMODE's augmented `q` DOF vs the Step 61 free-free basis solve (neither doc addresses it). |

### Shared-infrastructure ownership (single-owner rule)

Three designs and the Phase G0 plan each assumed they would build the same infrastructure.
Assigned owners — later features **reuse, never re-extract**:

- **`reduce_to_aset` a-set reduction** → **Step 59, delivered 2026-07-06**
  (`sbeam/assembly/reduction.py`; serves `matrix_gaf_export` §6.1, `matrix_reuse_store`
  §8.1, and the G0 solvers — see `docs/40_history/07_maneuver_transient.md`).
- **Geometric rigid-body basis builder (`build_rigid_modes`)** → **Step 61, delivered
  2026-07-30** (`sbeam/solver/modal_basis.py`; RBMREF reuses it, never re-derives it).
- **A-set operator assembly for the maneuver solvers (`assemble_aset_operators`)** →
  **Step 61, delivered 2026-07-30** (`sbeam/solver/modal_basis.py`, on top of Step 59's
  `reduce_to_aset`; both `maneuver_qs` and the Step 62 modal solver call it).
- **`MKAERO1` card, per-Mach GAF loop, export bundle/manifest** → **`matrix_gaf_export`**
  (Phase D "extends rather than duplicates"; `matrix_reuse_store` shares the bundle).
- **SOL 144 production dispatch + f06 surface** → **already exists** (Step 56/AE10 + AC5);
  no design may re-propose it.

### Housekeeping (doc hygiene)

- **H3 — stale-prerequisite annotations:** when P15/P17 start, update
  `matrix_gaf_export.md`/`dlm_rfa_flutter_gust.md` AE4 gates (closed by AC7) and
  `matrix_reuse_store.md` Phase 0 (delivered by Step 56/AC5).

(H1 — prune `01_static_aero_plan.md` — and H2 — archive the ZAERO review — closed
2026-07-05; see `docs/40_history/00_completed_development.md` and CHANGELOG.)

---

## Open questions / risks

| ID | Question / Risk | Severity | Status |
|----|-----------------|----------|--------|
| Q1 | SPC reaction f06 output: NASTRAN outputs SPCFORCE in the global (CID 0) frame, not the CD displacement frame. Current code matches this convention (no CD transform on reactions). Verify intentional. | Low | Open |
| Q3 | GRAV CID restriction (only CID=0 supported, parser raises): acceptable for Phase 1 but not documented in "Known Limitations". | Low | Open |
| Q4 | Lumped vs consistent inertia in `M_ax` (found during Step 61, 2026-07-30): `sol144.build_inertial_cols` builds the inertia-relief columns from **lumped** CONM2 masses / diagonal inertia and CBAR half-masses, while `M_aa` comes from `assemble_global_mass` (**consistent** mass). The `M_ax = −M_aa Φ_r` identity is therefore exact on translational rows always, and on all rows for CONM2-only decks; with `rho > 0` CBARs the rotational rows differ (the consistent-mass translation↔rotation coupling has no lumped counterpart — measured O(10%) of the peak column value on a dihedral test model). Affects the inertia-relief RHS of the Step 53 balanced maneuver and the increment-1 transient solver equally — pre-existing, not introduced by Step 61. Decide whether `build_inertial_cols` should be replaced by `−M_aa Φ_r` outright (one mass model, and the identity becomes definitional) or the discrepancy documented as intended. Pinned by `tests/solver/test_modal_basis.py::test_m_ax_identity_limits_with_consistent_cbar_mass`. **Ranked P2, batched with DEF-M3** (same root cause). | Medium | Open |

---

## Open defects — 2026-07-31 SOL 144 critical review

Findings of the 2026-07-31 multi-agent critical review (4 area reviewers + 8 numerical
probes + inline trim/dead-code sweep), all independently verified in a second pass —
**every finding confirmed, none refuted**. Evidence tags: **[E]** reproduced by an
executed numerical check; **[D]** directly verified in code. Positive baseline for
context: HA144A rigid longitudinal derivatives match the ADA370433 NASTRAN reference to
0.02 %; maneuver closure is machine-zero; lateral symmetry at β=0 is exact; PG scaling
follows the 3-D Göthert prediction (ratio 1.173 vs 1.177 Helmbold at M=0.6); stiff-limit
elastic derivatives converge to rigid at 3e-8; strip correction round-trips through card
text to 1.3e-8; divergence q cross-checks an independent QZ eigensolve to 1e-15.

Decisions taken 2026-07-31: SPLINE0 body loads → **inject as rigid loads at the reference
point** (DEF-M1 = **Step 64**).

**Ranking (2026-07-31 priority update).** These findings now hold the top of the priority
order — see the table above:

| Rank | Batch | Items |
|------|-------|-------|
| P1 | Step 64 — SPLINE0 body loads into the trim equilibrium | DEF-M1 |
| P2 | One mass model for `M_ax` | DEF-M3 + **Q4** (same root cause; resolve together) |
| P3 | Deliverable integrity (what leaves the program) | DEF-M5, M6, M7, M10 |
| P4 | Silent-input handling (user asked, program ignored) | DEF-M4, M8, M9 + DEF-R5, DEF-L1 + sample-review F1 (duplicate box IDs) |
| P5 | Convention / transfer completeness | DEF-M2, M11 |
| P10 | Aero hot path (with the `build_ajj` vectorization) | DEF-R6 |
| P14 | Refactor before Phase D | DEF-R1, R2, R3, R4 (+ DEF-R7 at a release boundary) |
| — | Opportunistic, do when adjacent | DEF-L2–L7 |

### DEF-M — Medium (silent wrong output on specific configurations, or misleading deliverables) — P1–P5

- **DEF-M1 / Step 64 — Inject SPLINE0/unsplined box forces into the trim equilibrium as
  rigid loads** (decision taken 2026-07-31) [D]
  Today those forces enter reported totals/derivatives but never the trim force balance
  or the load export: `sbeam/solver/sol144.py:1674-1707` (all-box sums) vs `:1730`
  (`g_disp.T` transfer). The cruciform/strip body-panel workflow tunes SPLINE0-covered
  panels to carry residual Cm/Cn — in a trim those forces are invisible to the force
  balance and the load export, while printed totals/derivative tables include them.
  *Objective:* body-panel trims physically closed, ZAERO-style.
  *Deliverables:* per label column and for the baseline w_g, sum the unsplined boxes'
  `skj`-forces to a 6-component resultant at the RCSID origin and add it to the r-set
  rows of the trim equations (Q_ax, f_rhs) and to `grid_loads`/exports via a
  reference-grid FORCE/MOMENT pair.
  *Test/Acceptance:* on `cessna210_body`/`_strip`, trimmed ANGLEA shifts by the body
  ΔCm/CZ_α prediction; closure stays machine-zero; `total_cz` at trim equals the
  balanced load factor. Complexity medium; trim results on body-panel decks change by
  design.

- **DEF-M2 — `solve_rigid_cl` CZ/CM are panel-normal magnitudes, not body-z** [E]
  `sbeam/aero/vlm.py:320-324, 442-445, 469-472`. Off by 1/cos(dihedral) vs the skj-based
  SOL 144 totals (verified 1.1547 at 30° dihedral); viewer Aero tab and f06 silently
  disagree on any canted deck; CL_wind inherits it; theory doc §2.9/`:435` claims they are
  equal; `test_dihedral.py:110` enshrines the wrong convention (cos Γ vs cos² Γ).
  *Options:* (a) project through n_z/n_y and update the dihedral test + theory doc
  (medium); (b) keep as normal-force convention and rename/redocument (low).

- **DEF-M3 — `build_inertial_cols` ignores CONM2 offsets, products of inertia, and CID
  rotation** [D] `sbeam/solver/sol144.py:400-476`. M_ax uses grid-point m and diagonal
  I11/I22/I33 in the basic frame only, while `assemble_global_mass`/GPWG handle offset
  transport, parallel-axis, and CID. Trim inertial loads and URDD columns are silently
  wrong for decks with offset/rotated/product-inertia CONM2s (HA144A has none, so gates
  pass). **Same root cause as Q4** (lumped vs consistent `M_ax`, found during Step 61) —
  resolve together: Q4's option of replacing `build_inertial_cols` by `−M_aa·Φ_r`
  (one mass model, identity becomes definitional) fixes both. Complexity medium.

- **DEF-M4 — `LOAD` in a TRIM subcase silently ignored** [D] `run_sol144_trim` never reads
  `subcase.load_sid` (only the test-only Step-50 path does). A payload/thrust FORCE in a
  SOL 144 trim subcase vanishes without warning.
  *Options:* (a) raise/warn "LOAD not supported with TRIM" (low); (b) add f_struct to the
  trim RHS as the Step-50 path does (medium; NASTRAN-consistent).

- **DEF-M5 — Critical maneuver sample: selector, f06 label, and printed column are three
  different metrics** [D] `maneuver_qs.py:343` (argmax ‖closure force‖) vs f06 "PEAK |NET
  FORCE|" label and `MAX |NET F|` column (= per-DOF max incl. moment DOFs, mixed units);
  0-based MLDPRNT vs 1-based f06 numbering. Verified divergent on the shipped MLOADS
  sample (crit=2, column peak=10, actual bar-load peak=4); the exported critical-sample
  BDF is taken at yet another sample than the column suggests. (MLDPRNT's ASCII already
  prints CLOSURE_F/CLOSURE_M — the inconsistency is the f06 table + the selection metric.)
  *Fix (complexity medium):* pick one severity metric (translational-force max or peak bar
  load), use it for selection + column + label, unify numbering.

- **DEF-M6 — Exported FORCE/MOMENT cards use 12–13-char fields on 8-char free-field
  format** [E] `load_export.py:32-53`. sbeam round-trips them, but a strict NASTRAN
  free-field reader truncates `4.715932E+03` catastrophically — and external stress
  handoff is the advertised purpose (05c:439). 66 oversized fields in one sample export.
  *Fix (complexity low):* NASTRAN 8-char reals (`4.7159+3`) or large-field `FORCE*`.

- **DEF-M7 — f06 maneuver time-history header misaligned 2 chars/column** [E]
  `f06_writer.py:696-699` (15-char header cells vs 13-char data cells): with 5 trim
  variables the FZ-AERO/MY-AERO headers sit a full column off their data. *Fix low:* one
  column-spec for header + rows.

- **DEF-M8 — Correction cards silently dropped on real decks** [E] Three variants, one
  theme (builder reports converged, production never sees the card):
  (a) `build_wg` first-W2GJ-wins — a generated correction W2GJ is ignored when the deck
  already carries one for that surface (`integration.py:70-81`), and short/long data
  silently pads/truncates; (b) WKK on non-primary CAERO1 ignored, on multi-surface primary
  crashes with a raw numpy shape error (`aero_model.py:93`, `corrections.py:113`);
  (c) WT2/AECORR on strip or nonexistent EIDs dropped, and the cruciform builder accepts
  strip panels whose WT2 half then never applies (`aero_model.py:94`,
  `body_correction.py:250`). *Fix (complexity low):* validate card↔surface binding and
  lengths at build time with card-labelled errors, mirroring the CHORDCP standard.

- **DEF-M9 — SPC on an RBE2/RBAR/RBE3-dependent DOF silently discarded** [E]
  `assembly/reduction.py:117-118` (+ duplicate `sol101.py:299-302`). Reproduced: a
  2-CBAR cantilever with grid 3 RBE2-slaved to grid 2 and `SPC1, 5, 123456, 3` solves
  with u_z(3) = −8.33e-3 (following its master) and zero warnings — the constraint is
  never enforced and the reaction is omitted. NASTRAN fatals on m-set/s-set overlap.
  *Fix low:* raise naming the grid/DOF and owning rigid element (fix once in
  `reduce_to_aset` after DEF-R5 ports sol101 onto it).

- **DEF-M10 — Sample-deck defect: HA144A "whole aircraft" MONPNT3 misses 18.75 % of the
  inertia** [E] `sample/ha144a_fullspan_sbeam.bdf:204-205` — SET1 1310 omits grid 97
  (CONM2 93.24 slug), so the WHOLE-AIRCRAFT monitor reports +3000 lb apparent imbalance
  on a balanced trim. Solver summation itself verified exact. *Fix low:* add 97 to SET1
  1310; consider a solver warning when an AECOMP grid set misses CONM2-bearing grids.

- **DEF-M11 — ATTACH `g_disp` carries only the z-row** [D]
  `sbeam/aero/spline.py:449-453` fills `g_disp` for the z-component of `ω×r` only: the
  `Tx`/`Ty` columns are absent and the x/y components of the rigid motion are dropped. For
  a z-normal panel this is exact, but on a dihedral or vertical (fin) ATTACH panel the
  in-plane `Fx`/`Fy` force transfer to the master grid is lost, and the virtual-work pairing
  with `g_slope` — now general in the box normal after DEF-H1 (`Ry = +n_z`, `Rz = -n_y`) —
  is incomplete. Deliberate carve-out when DEF-H1 was fixed (2026-07-31); no shipped deck
  uses a non-z-normal ATTACH panel. *Fix (complexity low-medium):* fill all three rows with
  the full rigid-body transform (translation identity + `skew(ω)·r`); extend V-B3d force
  transfer to a dihedral panel.

### DEF-L — Low (robustness, hygiene, docs; batch opportunistically) — L1 with P4, L2–L7 unranked

- **DEF-L1** Silent lenient card handling: STRIPK length/duplicates (`strip.py:68-81`);
  W2GJ duplicates (also DEF-M8a); box-ID range collisions mis-bind AELIST boxes
  (`integration.py:202`, duplicated in `sol144._compute_hinge_moments`); WKK zero weight
  → bare LinAlgError, docstrings say lstsq while code uses solve (`aero_model.py:102/306`);
  `parse_body_targets` passes NaN through required TOTAL columns
  (`body_correction.py:194`); section-data `caero` column bypasses friendly validation,
  duplicate eta rows silently interp (`section_data.py:110`). [E/D]
- **DEF-L2** SPLINE2 extrapolation advisory skipped for single-station SET1; probes colloc
  only (`spline.py:179-189`). (The pre-existing HA144A warnings are legitimate: 3 wing-tip
  boxes extrapolate ≤25 % past the EA tip — physically reasonable.) [E]
- **DEF-L3** `get_suport_local` silently drops SUPORT DOFs eliminated by SPC/RBE3 —
  changes determined/over-determined classification without diagnosis
  (`sol144.py:490-500`). [D]
- **DEF-L4** Viewer: uncorrected-Cp operator inverts the strip identity placeholder as a
  real AIC on PSTRIP decks (`aero_view.py:423`); `cl_section` merges strips across
  surfaces so multi-surface span-load plots are meaningless (`vlm.py:424-434`). [D]
- **DEF-L5** f06 presentation: AEROF/APRES "BOX ID" is the internal index, not the NASTRAN
  box ID every other card uses (`f06_writer.py:520-530`); hinge-moment block omits that
  per-variable derivatives are rigid while TOTAL is elastic (`f06_writer.py:462`,
  `sol144.py:870-872`); export SID = subcase_id invites silent superposition with deck
  load sets (`load_export.py:81`; parser merges duplicate FORCE SIDs,
  `bdf_reader.py:413-414`); `build_maneuver_time_history_text` IndexError on
  empty-steps results the sibling writers guard (`maneuver_output.py:38`). [D]
- **DEF-L6** Docs-mismatch batch: theory doc claims M ≤ 0.99 cap (code accepts any M<1,
  `aero_model.py:363`); 05c monitor CSV column list missing
  massset/mass_case (`:667-669` vs `load_export.py:154-160`); 05c parity paragraph
  (`:653-656`) describes behaviour the code doesn't have; `build_g_spline` docstring lists
  retired DTHZ/DTOR warnings (`spline.py:470-474`); `AeroBox.chord` comment says box chord
  but stores strip chord (`panel.py:33/168`); stale "(finite difference)" comment at
  `sol144.py:1644` (implementation is exact analytic); CLAUDE.md module map omits
  `aero/spline.py`, `aero/coupling.py`, `aero/mirror.py`. [D]
- **DEF-L7** Monitor SYMXZ parity path (par=2, *WHOLE-AIRPLANE* tag, CSV parity columns)
  unreachable in the shipped pipeline — build_aero_model rejects SYMXZ≠0 and
  mirror_halfspan (which zeroes it) has no production caller (`monitor_points.py:35-64`).
  Decide: remove (full-span-only), or wire mirror_halfspan into parse/main. Related:
  mirror_halfspan silently drops STRIPK/PSTRIP for mirrored strip panels
  (`mirror.py:35-48`). [D]

### DEF-R — Refactor / dead code (no behaviour change) — P14 (R5 with P4, R6 with P10)

- **DEF-R1 — Decompose `sol144.py` (1838 lines)** — `run_sol144_trim` is a ~500-line god
  function. Natural seams: derivatives module (rigid/restrained/unrestrained/hinge),
  divergence module, trim assembly, Step-50 static path. Includes hygiene: duplicate local
  imports of top-level names (`build_qaa`/`build_fg` at 1511/1518, `build_djk` twice,
  `get_transform` twice), unused `_compute_restrained_derivs` params
  `u_a_trim`/`delta_all_trim` (:919-920), misnamed `Fz_x`/`Fz_y`. Complexity medium-high;
  best done before Phase D piles more on. [D]
- **DEF-R2 — Dead per-trim `lu_factor(K_aa)`** — `sol144.py:1775` factorizes the singular
  free-flight K_aa (O(n³)) into `Sol144TrimResult.k_aa_lu`, which no production or test
  code ever consumes. Delete the field or populate lazily. [D]
- **DEF-R3 — Step-50 path is test-only** — `run_aeroelastic_static`/`_solve_rom`/
  `_mode_acceleration_recovery` (~250 lines) have no production caller. Decide: route SOL
  144-without-TRIM subcases to it in main/viewer, or mark it reference/test scaffolding
  and move next to the tests. [D]
- **DEF-R4 — Body-builder duplication** — ~110 lines copy-pasted between
  `build_body_correction` and `build_strip_body_correction`
  (`body_correction.py:289-444` vs `497-629`; diff-measured ~190 line-identical of 289);
  extract the shared weight-row/solve/achieved core, parameterized by unit response +
  card emitter. Dead `_NORM_TOL` constant (:115). [D]
- **DEF-R5 — `sol101` inline duplicate of `reduce_to_aset`** — `sol101.py:294-311`
  hand-rolls the Step-59 shared reduction (including its own copy of DEF-M9's silent SPC
  drop); port onto `reduce_to_aset` so the fix lands once. [D]
- **DEF-R6 — Redundant O(n³) work per aero build** — WT2 branch inverts the same AIC twice
  plus a full-SVD `np.linalg.cond` (3× the dominant cost; `aero_model.py:104`,
  `corrections.py:131-133`, `section_correction.py:184-192`); `np.linalg.cond(K_eff)` full
  SVD per static solve (`sol144.py:148`); `run_maneuver_qs` rebuilds the Mach-correct AIC
  twice when no AeroCache is passed (`maneuver_qs.py:267-274`). Factor once (LU), estimate
  condition via gecon. [E/D]
- **DEF-R7 — Remove the deprecated WT1 correction path** — DEF-H2/H3 (closed 2026-07-31)
  deprecated `AECORR METHOD=WT1` with a parser `UserWarning` but left it working. Complete
  the retirement at a release boundary: delete `apply_wt1` (`corrections.py`), the WT1
  branch in `_assemble_vlm_operator` (`aero_model.py:116-118`), the parser's acceptance of
  `METHOD='WT1'` (`bdf_reader.py` — `AECORR` becomes WT2-only, and the deprecation warning
  becomes a `ValueError`), and the `TestApplyWt1`/`TestWt1Deprecation` classes in
  `tests/aero/test_corrections.py`. Also strip the WT1 rows/notes from `05a_aero_vlm.md`,
  `02_card_reference.md`, `05_aeroelastics.md`, `01_beam_model.md` and theory §3.3. No
  shipped deck uses WT1 (no `AECORR` card appears anywhere in `sample/` or `tests/**/*.bdf`),
  so the only breakage is a hand-written legacy deck — which is producing wrong numbers
  today. Complexity low. [D]

---

## Open items — 2026-07-31 sample-problem review (P6–P8 + opportunistic)

Full review + proposal delivered 2026-07-31. Evidence basis: all 22 `sample/` decks run
headless through `main.main()` — 20 run end-to-end, 2 fail by design (`HA144A.bdf` MSC
archive; `simple_beam.dat` viewer onboarding file), and every checkable anchor reproduced
(PL³/3EI to 0.004 %, PL³/48EI to 0.004 %, cantilever f₁ to 0.02 %, free-free RBMs
≤ 4.6e-5 Hz, HA144A fullspan trim/derivatives to ≤ 0.3 % of the published MSC/ADA370433
values). The gaps are **coverage and redundancy, not correctness**.

### Step 65 (P7) — Flagship realistic-airplane SOL 144 sample family + theory doc

**Objective.** One realistic-airplane worked example combining corrected aerodynamics,
multi-subcase static trim, a transient maneuver, mass cases and monitor points — the
combination no HA144A or cessna deck covers (the cessna correction ladder never reaches a
SOL 144 solve).

**Deliverables.**
- `sample/cessna210_flagship_bulk.bdf` + three thin case-control drivers
  (`_trim`: SC1 1g cruise + SC2 2.5g pull-up; `_mloads`: trim + elevator-ramp transient;
  `_massset`: one TRIM × MASSSET 10/20/30) via whole-bulk `INCLUDE`, plus
  `cessna210_flagship_section_data.csv`.
- Bulk = the cessna210 stick + 324-box mesh with CAERO1 EIDs renumbered
  1100/1300/2100/2200/3100 (kills the F1 box-ID collisions; 4100/4200 reserved for
  stage 2), plus: GRID 900 at ¼-MAC + z-down stability CORD2R 990 (`AEROS RCSID`, HA144A
  URDD3 = −g convention); `SPC1,1,1246,900` + `SUPORT,900,35`; ~19 CONM2s (≈ 1081 kg
  baseline, CG ≈ 22 % MAC, GPWG-checked, C210 envelope); 5× SPLINE2+SET1+spline-axis
  CORD2R (EA-only SET1 ⇒ **DTHY = 0.0** or the spline system is singular); part-chord
  elevator (hinge CORD2R at the straight ⅔-chord line x ≈ 7.60, AESURF + explicit 32-box
  AELIST); AESTAT ANGLEA/PITCH/URDD3/URDD5; TRIM 1 (q = 2334 Pa, M = 0.0, 1g) and TRIM 2
  (2.5g, PITCH = (n−1)g·c/2V²), both with RHOREF; MASSSET FERRY/CRUISE/MTOW
  (≈ 996/1201/1560 kg — exercises DELETE, ADD, REPLACE and an offset CONM2); MONPNT3
  wing-root + whole-aircraft, MONPNT1 all-aero + right-wing (+ AECOMPs); MLOADS chain
  with the trimmed ELEV baked into TABLED1 (+2° over 0.3 s, hold — MLDCOMD tables are
  absolute, two-pass workflow).
- Corrections **pre-baked and committed** (generated once via
  `build_from_section_data_multi`, viewer-export provenance header) from a
  **3D-informed** CSV: spanwise-tapered cn_a integrating to wing CLα ≈ 4.9/rad, washout
  in a0, per-polar cm data, reduced-slope 8–14° region adjacent to the 2.5g trim point.
  Raw 2D polars (the old cessna CSV) would give an unphysical corrected CLα ≈ 7/rad —
  the theory doc's central lesson.
- `docs/20_theory/02_realistic_airplane_sol144.md` (tutorial register of
  `aeroelastic_derivatives.md`): the deck layer-by-layer, then the f06 block-by-block
  with hand-check anchors (CL₁g ≈ 0.28, CLα ≈ 5.0–5.2/rad Helmbold AR 7.72,
  Cmα ≈ −0.7…−0.9/rad from tail volume 0.63, ≈ 2°/g elevator; MONPNT1 ≈ n·W aero-only vs
  MONPNT3 ≈ 0 balanced), mass sweep, transient, limitations/roadmap. Plus one
  `docs/00_INDEX.md` row.
- Staged deletions: `airplane_aero.bdf` (its NCHORD/NSPAN box-AR sizing rationale moves
  into the flagship bulk header) and `cessna210_aero.bdf` + `cessna210_section_data.csv`
  (`tests/aero/test_cessna210_example.py`'s 5 tests re-pointed at the flagship bulk;
  `docs/10_standard/05a_aero_vlm.md` §"worked example" updated).

**Test/Acceptance.** `tests/aero/test_cessna210_flagship.py` (module-scoped, ≈ 3 solves):
T1 all three drivers parse via INCLUDE, 324 boxes, **no duplicate box IDs**, zero
spline-coverage warnings; T2 regenerating W2GJ/AECORR from the CSV reproduces the
committed cards (atol 1e-8); T3 both trims close, lift = n·W from GPWG mass (rel 1e-6),
corrected whole-model CLα = 5.2 ± 0.5/rad; T4 MASSSET sweep — ANGLEA strictly increasing
FERRY→CRUISE→MTOW and wing-root bending per unit weight **decreases** with wing fuel
(inertia relief; no existing test covers that physics); T5 MLOADS t=0 sample == SC1 trim
and final held sample == a static trim with ELEV prescribed at the ramped value; T6
MLOADS × MASSSET=30 combined smoke (first coverage of the pairing anywhere).

### Step 66 (P8) — Flagship stage 2: body panels (blocked on Step 64 + Step 65)

**Objective.** Total-aircraft moment match on the flagship, once Step 64 injects
unsplined-box forces into the trim balance (until then a body-panel trim is internally
inconsistent: totals include the body increment, closure/monitors/exports do not).

**Deliverables.** CAERO1 4100/4200 + SPLINE0 (or PSTRIP) + CSV `TOTAL` row +
body-correction cards into the flagship bulk; tighten T3's lift gate to include the body
increment; fold `cessna210_body.bdf`/`cessna210_strip.bdf` +
`cessna210_body_section_data.csv` into the family and re-point
`test_cessna210_body_example.py` / `test_body_correction.py` / `test_strip_body.py`;
theory-doc limitations section updated.

**Test/Acceptance.** Existing body/strip gates pass against the flagship decks; trimmed
ANGLEA shifts by the body increment (the acceptance already recorded under DEF-M1/Step 64).

### Sample hygiene + doc pointers (opportunistic, ~1 d total, zero risk)

- **Hygiene batch (~0.5 d):** delete `beam_vib1.bdf` (zero refs; header says 100 kg, card
  says 10 000) and `val_wing_taper_dihedral.bdf` (byte-identical to `_twist` minus W2GJ,
  zero refs — record the no-twist CL 0.268 as a comment in `_twist` and reword the 05a
  washout-table rows); delete the two stale untracked f06s (`beam_vib.f06` is actually
  `beam_vib1`'s output); fix `beam_vib.bdf`'s copied header and its RHO=0 config (f06
  prints ~10⁶-Hz junk modes 4–5); fix `val_cantilever_modes.bdf`'s stale "f₂ ≈ 2.58 (XY)"
  comment (actual f₂ = 16.16 Hz — the deck's own SPC1 suppresses the XY family); 2-line
  archive notice in `HA144A.bdf` (not runnable by design; holds the published Table 7-1
  reference values); extend the ha144a canard SET1 span to silence the SPLINE2
  extrapolation warnings emitted on every run of all three ha144a decks.
- **Doc-pointer sweep (fold into the DEF-L docs-mismatch batch):** `sample/ha144a_sbeam.bdf`
  cited 5× but deleted long ago (incl. `40_history/06`); `05a_aero_vlm.md` overstates
  `test_strip_body.py`'s coupling to `cessna210_body_section_data.csv` (targets are
  programmatic); de-line-number DEF-M10's `ha144a_fullspan_sbeam.bdf:204-205` pointer.
- **Deferred verdicts (re-examine at flagship stage 2):** `val_vlm_anhedral.bdf` is a
  2-coordinate sign flip of `_dihedral` that 2 test files could mirror in memory —
  consolidate opportunistically or keep; ha144a_fullspan ×3 INCLUDE consolidation
  (superset bulk + 3 drivers, ~280 duplicated lines each, already drifting) only **after**
  the flagship proves the driver pattern — ripple is ~24 test files + 6 docs.

---

## Tier 1 — SOL 144 production process (P9–P13)

The goal state: SOL 144 supports early design analysis end-to-end — static trim and balanced
maneuvers (done), **payload-condition sweeps** (Step 60, closed 2026-07-30), **transient maneuvers with a modal
basis** (Steps 61–63), **section loads for stress** (Monitor Phase 2), and a **closed
authoring loop** (viewer UI).

### Phase G0 — transient maneuver loads (DLM-free): detailed plan (2026-07-05, re-prioritised in this review)

**Increment 1 is CLOSED (2026-06-13)** — Level-1 quasi-steady (`Ω×r`), open-loop, restrained l-set
Newmark-β integration of the ZAERO `MLOADS` card set (`MLOADS`/`MLDTRIM`/`MLDCOMD`/`MLDTIME`/
`MLDPRNT` + `TABLED1`). See `docs/40_history/00_completed_development.md` (Phase G0 increment 1) and
`solver/maneuver_qs.py`. The steps below build on it; all are **DLM-free** and gated only on
Phase C. Full unsteady MLOADS (state-space / RFA / control law) remains Phase G (gated on the DLM).

**Re-ordering note (this review):** `MASSSET` was pulled forward to Step 60 because its static
half (payload sweeps for SOL 144 trim / Step 53 maneuvers) needs none of the modal work and
directly serves the early-design aim; its fixed-Φ transient gates land with Step 62.
Sequencing: **59 (refactor, closed 2026-07-06) → 60 (MASSSET static, closed 2026-07-30) →
61 (basis + GAFs, closed 2026-07-30) → 62 (modal solver + mass gates) → 63 (free-flight)**,
then G0-d/G0-e.

#### Architecture decisions (confirmed 2026-07-05)

1. **Free-free ZAERO-style basis** `Φ = [Φ_r | Φ_e]` (n_a × n_h) built once from the **baseline**
   mass case:
   - **Φ_r — geometric rigid-body vectors about the SUPORT point** (one column per SUPORT DOF),
     NOT eigensolver zero-modes: free-free `eigh` returns the zero-frequency subspace in arbitrary
     linear combinations, whereas geometric vectors are deterministic, give an **exact algebraic
     map between rigid modal coordinates and the URDD/ANGLEA/PITCH trim labels** (unit-plunge ⇒
     `ξ̈ = URDD3`; unit-pitch ⇒ `ξ̈ = URDD5`, `ξ̇·c_ref/2V = PITCH`), and make
     `M_rr = Φ_rᵀ M_aa Φ_r` exactly the GPWG rigid mass about the SUPORT point. Same reference
     point as `build_inertial_cols` (`suport_pos`), so `M_ax ≡ −M_aa Φ_r` column-for-column —
     a tested identity. (This is the same mathematical object as `designs/rbmref_card.md`
     `B_target`; Step 61 owns the single builder.)
   - **Φ_e — free-free elastic modes** from `solve_modes(K_aa, M_aa, force_dense=True)`
     (unconstrained a-set), zero modes dropped, then **explicitly mass-orthogonalized against Φ_r**
     (`φ_e ← φ_e − Φ_r M_rr⁻¹ Φ_rᵀ M_aa φ_e`, re-M-orthonormalized). `Φ_eᵀ M_aa Φ_r = 0` holds by
     construction — this **is** the mean-axis condition (ZAERO Ch. 12 Eqs 12.9–12.16; same physics
     as `_compute_unrestrained_derivs`). `M_hh` is block-diagonal `[M_rr, 0; 0, I]` at baseline.
   - SUPORT's role changes: it supplies the rigid-mode reference point / DOF selection, the l-set
     constraint for mode-acceleration recovery, and the trim-label map — it no longer constrains
     the dynamics (`u_r = 0` dropped in the modal solver). SUPORT remains required.
2. **Modal EOM (Level-1 quasi-steady, perturbation about the Step 53 trim IC):**
   `M_hh Δξ̈ + [C_hh − q·B_hh] Δξ̇ + [K_hh − q·Q_hh] Δξ = q·Q_hc·Δδ_c(t)` where
   `K_hh = Φᵀ K_aa Φ`, `Q_hh = build_gaf(Q_aa, Φ)` (reused verbatim), `B_hh` = quasi-steady
   rate-damping GAF (plunge-rate column `−1/V` + the existing `Ω×r` PITCH/ROLL/YAW machinery from
   `build_djx`, rescaled from nondimensional rate; elastic-rate columns zero at Level 1 = the
   G0-d hook), `Q_hc` = control-surface columns of the existing `Q_ax` projected once, and
   `C_hh = diag(2ζωᵢ)` on the elastic partition. Rigid-state trim labels (ANGLEA/PITCH/URDD*)
   become **outputs** recovered from `ξ_r` — not inputs. Newmark-β (¼, ½) on the dense n_h system:
   `K̂` is nonsingular (M_rr ≻ 0) — **free flight = don't constrain the rigid partition; no Schur,
   no per-step re-trim**. Perturbation form keeps gravity implicit and guarantees an exact
   equilibrium start.
3. **Multi-mass-case: fixed Φ, swap M only (ZAERO-style).** Per MASSSET case *i* recompute only
   `M_aa,i` → `M_hh,i = Φᵀ M_aa,i Φ` (full, coupled off-baseline), `M_ax,i`, GPWG/trim mass
   properties, and the Step 53 IC trim. `Φ`, AIC (`ajj/ajj_inv_corr` — geometry+Mach only),
   `skj/djk/wg`, splines, `Q_hh/Q_hc/B_hh`, `K_hh`, `AeroCache` all reused untouched — explicitly
   **no aero-cache invalidation**. Exactness property used in the gates: with all n_a modes
   retained, Φ spans the a-set, so fixed-Φ off-baseline solutions are exact — truncation is the
   only approximation.
4. **Mode-acceleration recovery with inertia relief** (theory Eq. 23, required for load quality),
   per output step: `u_md = Φξ`; residual `r_a = f_ext(t) − M_aa Φξ̈ − C_a Φξ̇ − (K_aa − q·Q_aa)Φξ`;
   `Δu_l = K_eff_ll⁻¹ r_l` (SUPORT r-set held, reusing the increment-1 `K_eff_ll` LU); downstream
   recovery via the existing `_recover_step` with URDD entries of `δ_basic` filled from `ξ̈_r`.

#### Step 62 (P11) — Modal transient solver, prescribed rigid states + fixed-Φ mass-case gates

**Objective:** De-risk basis + integration + mode-acceleration recovery with the rigid partition
still *prescribed* (open-loop, exactly increment-1 physics) before freeing it in Step 63 —
isolates truncation behavior from free-flight dynamics — and land the fixed-Φ mass-case
transient capability on top of Step 60's MASSSET.

**Deliverables:**
- `sbeam/solver/maneuver_modal.py` (new): `run_maneuver_modal(bulk, subcase, aero, aero_cache=None)
  → ManeuverResult`, selected in `main.py` when the MLOADS card has METHOD/NMODES set; otherwise
  the legacy `run_maneuver_qs` runs unchanged (kept permanently as the regression anchor; the
  increment-1 NMODES ignored-warning retired). Trim IC via `run_sol144_trim` (unchanged pattern);
  IC projection `ξ_e0 = Φ_eᵀ M_aa u_a,trim`; prescribed ξ_r(t) from the δ(t) URDD/rate histories
  via the rigid map; elastic Newmark with `−M_er,i ξ̈_r` (zero at baseline) + `q·Q_ec·Δδ_c` RHS.
- Per-mass-case pipeline: `M_aa,i` → `M_hh,i = Φᵀ M_aa,i Φ` (full, coupled), `M_ax,i`, IC trim
  with overlay, new Newmark LU (n_h-sized, cheap). Both maneuver solvers thread
  `subcase.massset_sid`.
- Recovery per architecture decision 4 (`_recover_step` refactored into a shared helper);
  `ManeuverStep`/`ManeuverResult` gain optional `modal_coords`, `n_modes_used`, `massset_sid`.
- Docs: theory §7.x (free-free basis, mean-axis orthogonalization, mode-acceleration with inertia
  relief; records the reversal of the increment-1 restrained-basis decision), `05c_sol144_maneuver.md`
  user section, `02_card_reference.md` MLOADS fields.

**Test/Acceptance:** **modal-convergence gate** — all elastic modes retained ⇒ CBAR forces, net
loads, closure, Fz/My histories match `run_maneuver_qs` ≤1e−6 relative (displacements compared
after rigid-projection removal: mean-axis vs `u_r = 0` rigid content differs); convergence table
NMODES ∈ {2, 4, 8, all} with monotone peak-bar-force error decay (documented); mode-acceleration
beats mode-displacement by ≥10× on truncated bar forces; hold-at-trim steady output = Step 53
loads; ζ>0 decays energy, ζ=0 reproduces the gate. **Fixed-Φ exactness gate** (off-baseline
MASSSET, all modes ⇒ matches `run_maneuver_qs` on the equivalent hand-edited deck ≤1e−6 — mass-case
error is pure truncation). **Fixed-Φ approximation gate** (+10% fuel overlay, truncated basis:
peak-CBAR-force error vs a re-solved-modes reference reported, ≤~2% asserted for the sample,
guidance recorded in `05c_sol144_maneuver.md` — "re-solve the basis when case frequencies shift >~5%").

#### Step 63 (P12) — G0-b free-flight rigid-body coupling (free the rigid partition)

**Objective:** The self-balancing maneuver: integrate `ξ_r` as states of the coupled h-set Newmark
system so closure ≈ 0 for an arbitrary commanded *control* history — no per-step trim solve.

**Deliverables:**
- Full coupled system (architecture decision 2): rigid rows active, `B_hh` rate damping engaged,
  controls-only `Q_hc`; single `K̂ (n_h×n_h)` LU with `K̂_rr = a0·M_rr − q·(Q_rr + a1·B_rr)`.
- δ bookkeeping: commanded AESURF labels = inputs (MLDCOMD/`_delta_of_t` reused);
  ANGLEA/URDD/PITCH labels = **outputs** from `ξ_r, ξ̇_r, ξ̈_r`; a rigid-state label in MLDCOMD
  under the modal solver ⇒ hard `ValueError` naming the label (the legacy solver remains available
  for prescribed-rigid studies).
- Recovery: `δ_basic` URDD entries from `ξ̈_r` (`urdd_rcsid_to_basic` reused); MLDPRNT gains
  rigid-state histories (α, pitch rate, Nz).
- New sample deck `sample/ha144a_mloads_massset.bdf` (free-flight elevator maneuver × 3-mass
  sweep — the full "maneuvers × payload conditions" demonstration).

**Test/Acceptance:** **G0-b gate (unchanged intent):** ELEV ramp-and-hold on the HA144A deck ⇒
closure ≤ tol throughout with O(dt²) decay under dt-halving, and the settled steady state
reproduces the Step 53 trim with ELEV prescribed and ANGLEA/URDD free (trim vars + net loads
≤1e−6 relative, full basis); zero-command free response stays at equilibrium to round-off;
short-period eigenpair of the assembled system matches a rigid 2-DOF hand calculation from the
Step 53 derivatives to ~5%; mass-case physics sanity (heavier MASSSET ⇒ lower steady load factor
for equal elevator). Determined command sets only (over-determined transient allocation deferred
to G0-e).

**Key decisions:** perturbation-about-trim (gravity implicit, exact equilibrium start); linear
inertial-frame rigid coordinates at fixed V (steady pull-up reachable since `α = θ − ḣ/V`
settles; phugoid/speed DOF out of scope, documented).

#### G0-d — Unsteady corrections (Levels 2–4) — follow-on (outline; hooks land in Steps 61–63)

**Objective:** Layer the analytic unsteady terms onto the steady VLM forcing as an ordered list of
optional `AeroIncrement` objects each contributing `(ΔM_hh, ΔB_hh, ΔK_hh)` and optional appended
states: (2) 2-D apparent (added) mass per strip (`πρb²` projected to `A_hh`, plus the elastic-rate
`B_hh` columns — the slot left in Step 61); (3) tail downwash-lag delay `τ = l_t/V` (`C_mα̇`; ring
buffer of delayed `D_jx`/`D_jξ̇` arguments); (4) strip Wagner/Theodorsen lift-deficiency (per-strip
2-state R.T. Jones approximation appended to the state vector). Selected by a new `MLDAERO` card
(designed at promotion). Each optional; extends validity beyond `k ≲ 0.05–0.1`. Acceptance sketch:
Level 2 reproduces 2-D `πρb²` exactly on a single strip; Level 4 reproduces Wagner indicial lift to
Jones-approximation accuracy. **Priority note (this review):** opportunistic — once Phase D (P17)
is underway the DLM supersedes Levels 2–4; only implement if transient-load fidelity beyond
`k ≈ 0.1` is needed *before* the DLM lands.

#### G0-e — Closed-loop control layer (ASE bridge) — deferred (outline)

**Objective:** Discrete control-law update `δ_c[n+1] = f(sensor(ξ, ξ̇, ξ̈))` inside the time loop;
actuator lag as a first-order appended state; sensors at grids via the existing spline/recovery
operators. Enables commanded-Nz and the over-determined transient control allocation (reusing the
`TRIMOBJ` null-space QP pattern). ZAERO-ASE-flavoured cards designed at promotion. Bridges to the
full Phase G ASE system. Acceptance sketch: proportional pitch-rate damper reduces short-period
overshoot vs open loop; zero-gain identity to Step 63. **Deferred with Phase G.**

#### Phase G0 plan — risks & open questions

1. **Singular/lumped `M_aa` in the free-free eigensolve** — CLOSED by Step 61, but *not* the way
   this risk was originally written. Regularise-and-filter does not work: the Tikhonov
   eigenvectors carry `O(1/√ε)` amplitudes on the massless DOFs, are M-orthogonal only against
   the *regularised* mass, and still report unit generalized mass — so no frequency or mass
   filter can see them, while the mean-axis projection against the true `M_aa` leaves the basis
   0.99 non-orthogonal (measured on HA144A). Step 61 instead condenses the massless DOFs out
   statically (exact — those equations carry no mass) before the eigensolve. Downstream steps
   must keep that path; do not reintroduce a filter-based mitigation.
2. **Fixed-Φ mass-case error** — quantified by the Step 62 approximation gate; the exactness gate
   proves it is pure truncation. Residual risk: large CG shifts change the mean axis materially —
   warn when an overlay moves the CG by more than a documented fraction of c_ref.
3. **TABLED1 rate discontinuities** — clamped-linear command tables have slope jumps; with `B_hh`
   rate terms the forcing is discontinuous and can ring the highest retained mode. Document
   ramp-smoothing practice; optional cosine-smoothed table evaluation as a future add.
4. **Damping model** — uniform ζ only at Step 61; per-mode TABDMP1 and the `B_hh` asymmetry
   (K̂ unsymmetric — LU already handles it) noted; Rayleigh `damping_alpha` stays legacy-solver-only.
5. **Linear inertial-frame rigid kinematics** — short-period-scale maneuvers at fixed V; no
   phugoid/speed DOF, no large-attitude kinematics. Documented validity envelope alongside the
   existing `k ≲ 0.05–0.1` aero limit.
6. **Control-surface inertia / hinge moments absent** — commanded δ_c produces aero only; surface
   mass reaction / hinge DOFs out of scope (theory-doc note). `AMODE` (P16) is the eventual home
   of a physical hinge DOF.
7. **SUPORT dependence stands** — the modal solver still requires SUPORT (reference point +
   recovery constraint + rigid DOF selection); a SUPORT-free variant (rigid modes about the GPWG
   CG) is a possible future relaxation, not planned.
8. **NMODES behavior change** — parsed-and-ignored with a warning through Step 61 (which added
   METHOD/ZETA alongside it); Step 62 makes the trio activate the modal solver. Call out in
   CHANGELOG as a behavior change when it lands.
9. **Basis drift** — one `solve_modes` call per job, enforced structurally (the basis object is
   passed into the GAF/mass-case loops; nothing inside can reach the eigensolver).
10. **Open question:** should `Q_hc` accept AESTAT rigid-state labels a user commands open-loop
    (e.g. prescribed-α studies)? Current answer: hard error under the modal solver; the legacy
    solver covers prescribed-rigid studies. Revisit if a use case appears.

### Monitor points Phase 2 (P9) — Section-cut running loads

The actual stress-team deliverable: per-station `{Vz, My, Mt}` tables along the wing,
HTP, VTP. Cut convention: plane normal along the spline-axis `x̂` at user-specified
stations (general normal as override). Builds directly on MON3's per-grid tally — a
section cut is "sum the per-grid loads outboard of the cut plane, project to EA
intercept". Unblocked (Phase 1 + Step 53 both done); independent of the G0 steps — can
land in parallel. With Step 60, section-cut tables per MASSSET complete the early-design
loads picture.

### Viewer (P13) — SOL 144 / MLOADS case authoring UI

The viewer runs and displays SOL 144 trim/DIVERG/MLOADS subcases but cannot *author* them —
the case-control editor's SOL selector offers 101/103 only and SOL 144 case control is
read-only. A full authoring UI (TRIM condition builder, AESTAT/AESURF/TRIMVAR editors,
DIVERG setup, MLOADS/MLDTIME/MLDCOMD/TABLED1 command-history editor, MASSSET selector after
Step 60, BDF export) closes the production authoring loop; until it lands, cases are
authored in the bulk-data BDF. Promoted from "deferred" to P13 by the 2026-07-05 review: a
production-like process needs authoring, not just display.

---

## Tier 2 — Supporting infrastructure (P15, P19, studies)

### matrix_gaf_export (P15) — matrix / GAF export bundle

Per `designs/matrix_gaf_export.md` (viable, see verdicts): `EXPORT` case-control command
writing sparse `K_gg`/`M_gg`, dense a-set `K_aa`/`M_aa`, `PHIA`/`PHIG`, modal `K_hh`/`M_hh`,
and per-Mach steady GAFs `Q_hh(M)` on one fixed Φ (Matrix Market + `.mat`, manifest +
dofmap); new `MKAERO1` card; Mach-tagged corrections. Phases 1–2 (~8 d). **Sequencing:**
unblocked — Step 59 closed 2026-07-06 (reuses `assembly/reduction.py:reduce_to_aset`);
before Phase D (which extends its MKAERO1/Mach-loop machinery). Its stated AE4 prerequisite is stale — closed by AC7. Phase 3 (OP4/UF writers)
deferrable.

### matrix_reuse_store (P19) — matrix persistence / dual-mode SOL 144

Per `designs/matrix_reuse_store.md` (viable, subordinated): persist `ajj_inv_corr`,
`skj/djk/wg`, box geometry, spline operators, sparse `KGG`/`MGG` to `.npz` bundles with
content-hash provenance; `DiskAeroCache(AeroCache)` reload path, default fresh-compute
bit-identical. **Re-scoped by this review: Phase 0 deleted** (the SOL 144 production
dispatch + f06 writer it wanted to build already shipped with Step 56/AE10 + AC5). Phases
1–3 (~6 d) become worthwhile once envelope sweeps exist (Machs × MASSSETs × maneuvers —
i.e. after P10–P12/P17); the cache-boundary rules (§4: cache pre-q, pre-reduction operands
only, never `Q_aa`/`K_eff`/LU) stand as written.

### SPLINE9 — FE-consistent Hermite beam spline (go/no-go study only)

Per `designs/spline9_hermite_beam_spline.md`: run the coarse-grid convergence study FIRST
(SPLINE9 vs SPLINE2-with-attached-rotations at 3/5/9 EA stations, ~1 d); if SPLINE2 matches
within noise at realistic station counts, **close as "not worth the second code path"
without implementing**. No card plumbing before the study. HA144A validation decks stay on
SPLINE2 either way.

---

## Tier 3 — SOL 145 flutter + DLM (Phase D/E/F) — the declared next phase (P16–P18)

### Phase D core (P17) — DLM (D0–D3) + SOL 145 PK flutter

Per `designs/dlm_rfa_flutter_gust.md` (viable, see verdicts): complex unsteady AIC
`A_jj(M,k)` (Landahl kernel, Laschka approximation, parabolic spanwise quadrature),
**anchored so `D(M,0) ≡ D_VLM(M)` to machine precision** (the load-bearing de-risking
decision — the entire steady content reuses the validated VLM); complex GAFs `Q_hh(M,k)`
over a Mach×k table (extending `matrix_gaf_export`'s MKAERO1/Mach loop); `sol145.py` PK
(primary) / PKNL / KE flutter with V-g/V-f output. Gates: Blair 3×3 kernel benchmark
(0.1%), k=0 GAF cross-check, typical-section flutter closed-form. **Prerequisites:** P15
landed; `g_disp_colloc` (¾-chord displacement spline) added at D0; the doc's AE4 gate is
stale (closed by AC7). Planar-only ships first — the nonplanar kernel terms (T1/T2, I2)
are a genuine research gap correctly walled behind their own gate. ~25–30 d.

### AMODE Phase 1 (P16) — control-surface hinge modes

Per `designs/amode_card.md`: `AMODE` card adding a generalized rotation DOF `q` for a SET1
grid group about a CORD2R hinge axis against stiffness `k`, via a transformation composed
after the RBE reduction (mirrors the proven `rbe3.py` path); f06 participation table.
**Schedule before control-surface flutter work in P17** (~7.5 d). Phase 2 (elastic rotating
set) is a declared pre-1.0.0 blocker, target after Phase D core. Open interaction to
resolve at implementation: the augmented `q` DOF vs the Step 61 free-free basis solve.

### RBMREF — folded into Step 61

`designs/rbmref_card.md`'s `B_target` construction is owned by Step 61's
`build_rigid_modes`. The RBMREF *card* (user CORD2R reference point, MECH/MASS
normalization, f06 rigid-body block) remains available as a thin optional wrapper
afterwards if the reporting feature is still wanted — do not build a second rigid-basis
path.

### Phase D cont. (P18) — RFA state-space + SOL 146 gust + Monitor Phase 3

Roger-form RFA + aeroelastic state-space (`rfa.py`); `sol146.py` discrete 1-cosine gust
(Fourier method) and continuous Von Kármán/Dryden turbulence (Ā/N₀). **Monitor points
Phase 3** lands here: CS-25.341(a) discrete gust (H = 30–350 ft sweep) and CS-25.341(b)
continuous turbulence at each monitor, with correlated companion-load extraction — built on
the Phase 1 monitor data model. Together these complete the dynamic loads process. ~15–20 d.

---

## Tier 4 — Lower priority / opportunistic

### Quasi-steady rate aerodynamics — yaw-rate wing term (small)

**Strategic note:** the quasi-steady rate-aero path (`build_djx` rate columns) is to remain a
**fully functional, supported option** even after the DLM (Phase D) lands — it is the cheap
maneuver-loads method and must be complete in its own right, not a stopgap.

**Gap:** the theory (`docs/20_theory/01_aeroelastics_theory.md` §7.2, Eq. 28) gives yaw rate *two*
effects: the fin sidewash Δβ(x) = r(x−x_ref)/V∞ **and** the spanwise dynamic-pressure asymmetry
ΔU(y) = −r·y on the wing (the advancing wing sees higher q∞). `build_djx`
(`sbeam/aero/integration.py`, `YAW` column) implements only the fin sidewash — the column vanishes
on horizontal panels, so the wing contribution to C_nr and the cross-derivative C_lr are missing.

- **Scope:** add the wing ΔU term to the `YAW` column. Note it is a *dynamic-pressure* (edgewise
  velocity) perturbation, not a normalwash — for the linear VLM it enters as an equivalent
  incidence increment Δw = −(2/bref)·y·(local lift-slope proxy) or, more rigorously, as a per-box
  freestream scaling of the steady loading; pick and document one formulation. Feeds SOL 144 trim
  (C_nr, C_lr) and the Phase G0 transient solver (which consumes the same column) unchanged.
- **Related known gap (same completeness aim):** the Phase G0 transient RHS has no elastic-velocity
  downwash ẇ/V term (`maneuver_qs.py` `w_struct` is displacement-slope only) — aerodynamic damping
  of the flexible modes is absent; covered by the G0-d Level 2–4 follow-ons.
- **Docs:** update §7.2/Eq. 28 note and `05a_aero_vlm.md` card/column table when implemented.
- **Test/acceptance:** full-span wing-only model — yaw-rate column currently produces zero load;
  after the change, a nonzero C_nr (drag-asymmetry sign) and C_lr consistent with strip-theory
  estimates; fin-only C_nr unchanged.

### Body fence / no-through-flow boundary condition via image vortices (small, opportunistic)

The complement to the decoupled strip (A10). A strip body carries the body's *load* but is
transparent to the wing's flow — it does **not** enforce that a wing box cannot blow through the
fuselage (the fence / carryover effect). By the §3.7 identity, a fence is *necessarily* coupling
(it reacts to the wing's induced velocity), so it cannot live in the decoupled strip element. The
cheap, **unknown-free** way to add it is the **method of images**: reflect each wing horseshoe
across the body surface (mirrored geometry, reversed circulation, as in ground effect) and add the
image's Biot–Savart contribution into the wing-wing block of `build_ajj`.

- **Scope:** an image variant of `horseshoe_influence` (mirror `bound_a`/`bound_b` + the +X trailing
  legs across a plane, reverse sense); fence planes derived from the body geometry (flanks y≈±w/2,
  waterline z) with **footprint gating** (reflect only behind the body extent); wire into `build_ajj`
  via an optional `fence_planes` argument; tests (a wall in isolation reproduces the textbook image
  result; fence raises wing-root loading; strip + fence compose).
- **Caveats to document:** a plane is not a body (planar image exact only for an infinite flat wall;
  finite/curved fuselage ⇒ first-order; gate to the footprint); sbeam is **full-span** so the y=0
  centreline is already present — fence planes go on the body's *outer* surface, not the centreline; a
  perpendicular corner (flank + waterline) needs the 3-image corner construction to stay exact.
- **Effort:** small (AIC augmentation only, no new unknowns / no body solve).

### Body aerodynamic panels (slender body) — proper fuselage element (after Phase D)

The cruciform (A9) is a **flat-plate tuning device**, not a fuselage model, and its limits are
documented (`docs/10_standard/05a_aero_vlm.md` "Geometry & limitations";
`docs/20_theory/01_aeroelastics_theory.md` §3.6). The **decoupled strip body panel** (Step A10,
`PSTRIP`/`STRIPK`, done) is the recommended *load-only* body stand-in. Large, *predictive* body
effects — the destabilising Munk couple, wing-body interference/carryover, a several-MAC
neutral-point shift, real fuselage airloads into the structure — still need a genuine body element:

- **Tier 1 (recommended) — slender body + interference body (NASTRAN `CAERO2`/`PAERO2` style).** A line
  of acceleration-potential doublets (Munk slender-body theory) for the body's own load, plus a
  cylindrical interference body whose image system modifies the wing boxes' boundary condition. New
  cards + a 3-D line/point-doublet kernel + a block `build_ajj` + a real fuselage spline. The
  interference-tube image method is the research risk / long pole. **Large effort.**
- **Tier 2 — closed vortex-ring/doublet body (sbeam-native).** Wrap the cross-sections in closed
  vortex-ring panels folded into the existing Biot-Savart `build_ajj`; no thickness/volume, needs a
  Kutta/wake treatment. **Medium-large effort.**
- **Tier 3 — full source+doublet 3-D panel body (ZAERO `BODY7` style).** Highest fidelity, effectively
  a second solver. **Very large.**

Until then, keep the cruciform compact and clear of the empennage (A9 guidance) and use it only for
a mild increment — or use the decoupled strip body (A10), which is placement-free.
**Priority note (this review):** below Phase D — the aim's early-design trim/loads accuracy is
served first by corrections (done) and the DLM; a predictive fuselage element is a
fidelity-completion item.

### Body cruciform (A9) — follow-ons (low)

- **A9-a — match body force as well as moment (optional).** Add an optional force target (Cz_α/Cy_β
  and offsets) so the body's CL/CY contribution can be matched to body-isolated CFD too.
- **A9-b — canted body panels.** Support a canted body panel (blended pitch/yaw) via a 2×2 slope
  solve over both moment metrics.
- **A9-c — automatic body-panel sizing / mesh guidance.** Size the cruciform from the fuselage
  planform/profile and report the genuine adverse metric — the body's induced ΔCp on the
  lifting-surface boxes.
- **A9-d — multi-Mach body targets.** Extend the CSV `TOTAL` block to a per-Mach sweep consistent
  with the flying-surface per-Mach corrected-BDF export.

### CHORDCP (Step 54) — follow-ons (low)

- **S54-a — partial per-surface coverage.** v1 requires every VLM CAERO1 to carry a CHORDCP card
  (one shared ALPHREF). CFD-wing-only injection with the tail on its W2GJ baseline mixes two
  operating points — needs a documented approximation + warning before it can ship.
- **S54-b — viewer CHORDCP authoring.** A path from a per-box Cp table (CSV) to CHORDCP cards +
  corrected-BDF export, parallel to the existing W2GJ+WT2 synthesis in
  `aero_correction_view.py`. Includes the deferred injected-vs-computed mean-flow overlay.

### Monitor points — MON-SYM (low)

Off-centerline monitors on `SYMXZ ≠ 0` half-span models are rejected (the mirror
reconstruction is only valid on the symmetry plane); lifting this needs the mirror half
integrated about its own reflected reference point. Low priority now that full-span is the
default build.

### SPLINE1 surface spline (Step 48 — deferred)

Harder–Desmarais Infinite-Plate Spline for general 2-D grid scatter. `Spline1` dataclass
stub exists; `_handle_spline1` raises `NotImplementedError`. Implement when a 2-D scatter
case arises. Acceptance: reproduces rigid-body and linear fields exactly; matches a
published IPS example (Harder & Desmarais 1972).

### Load-case envelope (viewer)

Max/min results across all subcases in a single table — becomes genuinely useful once
Step 60 mass sweeps and Step 63 maneuver sweeps multiply the case count. Small,
viewer-side; pair with a sweep-capable release.

### Phase 3 — structural dynamic response solvers (SOL 108/109/111/112)

Frequency- and time-domain structural response (no aero). **Priority note (this review):**
for the aeroelastic aim these are largely superseded — the G0 solvers cover transient
maneuver response and Phase D's SOL 146 covers gust — but they remain the right home for
structural-only dynamics (ground shake, hammer tests) and SOL 111/112 share the modal
machinery Steps 61–62 build. Implement opportunistically after Tier 1.

| Step | Solver | Objective |
|------|--------|-----------|
| 26 | SOL 108 — Direct frequency response | Solve `([K] − ω²[M]){U} = {F(ω)}` over a frequency range. Cards: `DLOAD`, `RLOAD1/2`, `FREQ`/`FREQ1`; damping via MAT1 GE. |
| 27 | SOL 109 — Direct transient response | Newmark-β (β=0.25, γ=0.5). Cards: `TLOAD1/2`, `TSTEP`. |
| 28 | SOL 111 — Modal frequency response | Modal superposition on the SOL 103 basis; TABDMP1 modal damping. |
| 29 | SOL 112 — Modal transient response | Modal superposition transient; Newmark-β in modal coordinates. |

### Future development (Phase 2+, non-aero)

Lower priority or significant new infrastructure; independent of the aeroelastic track.

| Item | Description | Prerequisite |
|------|-------------|--------------|
| PLOAD1 — Distributed Loads | Equivalent nodal load vector for linearly-varying / uniform loads along CBAR; viewer load visualisation. VAL1 complete — viewer warns when PLOAD1 cards are present. S30 can be implemented. | — |
| Timoshenko Shear (PBAR K1/K2) | Modified stiffness with shear parameter φ = 12EI/(κAGL²); falls back to Euler-Bernoulli when K1=K2=0. K1/K2 currently ignored silently — correct for slender beams. | Parser update |
| SOL 105 — Buckling | Solve `([K] + λ[K_G]){φ} = 0`; requires geometric stiffness from SOL 101 axial forces. | SOL 101 complete |
| Results export (CSV/Excel) | Download displacement, force, stress tables from the viewer as spreadsheets. | Viewer complete |
| OP2 results export (pyNastran) | Write an OP2 alongside the f06 (displacements, eigenvectors, CBAR forces/stresses; later SOL 144 box pressures/forces). Unlocks pyNastranGUI as an external post-processor. pyNastran (BSD-3) optional dependency; prototype from its test suite first. Acceptance: pyNastran round-trips the OP2; pyNastranGUI renders SOL 101/103 results. | SOL 101/103 complete |
| PBARL | Define PBAR cross-section by standard shape (ROD, BAR, BOX, I, L, T, …) with auto-computed A, I, J. | Parser |
| Parametric sweep | Vary a geometry/material parameter and plot the response curve. | SOL 103 complete |
| MAT1 thermal fields | GE (structural damping) parsed but unused; A and TREF for thermal expansion. | SOL 108 for GE |
| CBEND | Curved beam element. | New element formulation |
| NASTRAN f06 import | Read an existing NASTRAN f06 into the viewer for display and comparison. | Results parser |
| Model pre-solve validator | Pre-run checks: zero-length elements, missing SPC, unsupported cards, inconsistent units, unreferenced SIDs — viewer warning panel. | Viewer complete |
| Sample model library | Curated BDF examples (cantilever, portal frame, truss, airplane stick, …) for tutorials and regression. | Verification suite |
| f06 results comparison | Two f06 files side-by-side; difference tables and overlaid deformed shapes. | NASTRAN f06 import |
| Deploy to Streamlit Community Cloud | Live demo URL for the README (nice-to-have). | Viewer complete |
