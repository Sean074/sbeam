# Transient `net_loads` carries the elastic inertia — design note for issue #3

**Status:** ✅ implemented 2026-09-05 (option B; measured G1 figures in §5). Milestone
[v0.3.0](https://github.com/Sean074/sbeam/milestone/1). Tier **M** — behaviour change to
an existing capability, no new card, no new physics. Closes the question deferred as O1 in
[`monsect_transient_section_cuts.md`](monsect_transient_section_cuts.md) §9 and the Step 68
follow-on in `docs/40_history/07_maneuver_transient.md`.

---

## 1. The defect this settles

`ManeuverStep.net_loads` is `aero + rigid inertia` (`grid_loads + M_ax_g·δ_basic`). It feeds
three things: the exported `<stem>.maneuver_qs_loads.bdf` `FORCE`/`MOMENT` cards, the
`closure` diagnostic, and the DEF-M5 `peak_grid_force` critical-sample metric. Step 68
recovered the elastic d'Alembert load `−M_gg·ü_e` and the damping force `−M_gg·w` on the same
dataclass but deliberately left them out of `net_loads`, because folding them in moves all
three consumers at once.

The transient equilibrium at a sample is

```
K·u  =  F_aero  −  M·ü_rigid  −  M·ü_elastic  −  C·u̇
        └──── net_loads today ────┘  └── elastic_inertial_loads + damping_loads ──┘
```

so the exported cards carry two of the four terms while the section cuts (`totals`) carry
all four — V-TSEC3 is the proof that a cut is wrong without them (1.21 % on the HA144A
wing cut, 3.7e-11 with them). **The cut and the exported cards for the same sample
therefore disagree by construction.** #36 makes these cards the LRA deliverable and #31
freezes the file as a public interface; both assume this is settled.

The exported load has one contract that matters: **applied statically to the same model,
it reproduces the run's internal loads.** Two of four terms cannot satisfy it.

## 2. Decision (B)

**`net_loads` becomes the full applied load at the sample:**

```
net_loads = grid_loads + inertial_loads + elastic_inertial_loads + damping_loads
```

with `elastic_inertial_loads`/`damping_loads` retained as separate fields (the section-cut
columns still need them individually). Nothing else is renamed. Consequences, each
deliberate:

| Consumer | Change | Why it is right |
|---|---|---|
| exported `FORCE`/`MOMENT` cards | carry all four terms | the contract above |
| `closure` | includes the elastic + damping resultant | the closure is "what the SUPORT reacts"; under the free-flight modal solver the elastic resultant is **exactly zero** (mean-axis orthogonality) so it is unchanged; under the direct solver the restrained l-set does react it, so it must move |
| `peak_grid_force` / `crit_index` | computed on the full load | DEF-M5's one-metric-one-numbering ruling is untouched — the *definition* of the metric does not change, only its input |
| `recover_reactions` in `recover_step` | `f_applied = net_loads` (drops the hand-summed form) | already the full load; now single-source |
| `evaluate_section_cut` | **unchanged** — receives the four columns separately | static tables keep their verified three-column split |
| static `SOL144Result.net_loads` | **unchanged** | on a static trim the rigid inertia *is* the whole inertia; the definition is identical |

Options rejected: **A** status quo (ships an incomplete stress load into an interface about
to be hardened); **C** a parallel `applied_loads` vector (two near-identical vectors where
`net` no longer means the stress deliverable; nothing downstream wants aero + rigid-only —
#2's transient monitors take the columns separately); **D** elastic inertia without damping
(modal ζ is a model of dissipation the static stress model does not have; drop it and
`K·u ≠ F` by the damping force — the cut's `totals` already includes it).

## 3. Quantification (2026-09-05, both sample decks, both solvers)

| Deck / solver | max\|F_el\| / max\|F_net\| per grid | root-cut bending, elastic share | resultant of elastic term | critical sample net → full |
|---|---|---|---|---|
| C210 elevator ramp, direct | 0.06 % | 0.07 % | 15 N (closure 805 N) | 21 → 9 (peaks differ by 1e-5) |
| C210 ramp, modal ζ = 0 | 0.56 % | 1.52 % | 4 N | 1 → 1 |
| C210 ramp, modal ζ = 0.03 | 0.57 % (damping 0.15 %) | 1.46 % | — | 1 → 1 |
| HA144A elevator step, direct | 0.50 % | 0.25 % | 21 N (closure 409 N) | 11 → 3 (peaks differ by 0.5 %) |
| HA144A step, modal ζ = 0 | 0.54 % | 0.23 % | 8e-15 (exactly 0) | 11 → 11 |

Reading: the term is small on these decks **because both maneuvers are gentle ramps** — it
scales with the frequency content of the excited response, and a 23.423 checked maneuver
(#29) or a tuned gust will excite the first wing mode where a 0.3 s ramp does not. The
critical-sample flips are near-ties (two samples within 1e-5), not physics. The closure is
unaffected wherever mean-axis orthogonality holds, exactly as the theory says.

## 4. Conventions cited

- `09_conventions.md` §5 (trim and maneuver states): the d'Alembert sign — `M_ax_g` **is**
  `−M_gg·Φ_r`, so the rigid load is `−M·ü_rigid` and the elastic one is `−M·ü_elastic`
  (already the Step 68 form; nothing new).
- `09_conventions.md` §9 (internal loads, section cuts, output signs): the section-cut
  `totals` definition the export must now agree with.
- `09_conventions.md` §8 (single-source helpers): the full applied load is assembled once,
  in `recover_step`, and every consumer reads `net_loads` — no consumer re-sums the columns.

## 5. Gates

**G1 — static re-apply (load-bearing, the rule-2 benchmark).** Take the critical sample of an
MLOADS run; apply its load as a SOL 101 case on the same deck with the SPC plus the SUPORT
DOFs fixed; recover CBAR forces; compare with `step.bar_forces`.

- G1a: the g-set `net_loads` vector applied directly → **1e-8 rel** on the direct solver and
  on the modal solver with all elastic modes retained (the basis spans the l-set, so the
  modal residual is zero).
- G1b: the same through the exported `FORCE`/`MOMENT` **cards** (parse → SOL 101) → **1e-5
  rel**, the NASTRAN 8-character field floor (DEF-M6), which is the number the stress
  office actually receives.
- G1c: **truncated** modal basis (`NMODES` < all). The modal residual `r = F − Mü − Cu̇ − Ku`
  is orthogonal to the retained modes but not zero, so the static re-apply differs from
  the modal recovery by `K⁻¹r`. This is the truncation error and it is *measured*, not
  bounded a priori. **Measured** on the HA144A elevator step: 1.49 % at `NMODES=2`, 0.77 %
  at 4, 1.4e-14 with all modes. Under the default mode-*acceleration* recovery the
  displacement is the static l-set solve of the full load, so G1a is exact regardless of
  `NMODES` — the truncation is only visible under `displacement` recovery.
- Companion (V-TSEC3 pattern): G1a asserted to **fail** with the elastic + damping terms
  removed, so the gate is demonstrably load-bearing. Measured: 1.6e-14 with, 1.55 % without;
  G1b 4.6e-7 (direct), 2.5e-7 (modal), 3.2e-7 (shipped C210 deck).

**G2 — closure.** Modal free-flight: `‖resultant(elastic + damping)‖ < 1e-12·lift` and the
closure bit-unchanged against the pre-change value. Direct: the closure shifts by exactly
that resultant.

**G3 — static anchor.** Commands held at trim (V-TSEC1 fixture): every sample's `net_loads`
equals the static Step 53 `net_loads` to 1e-8 (elastic and damping terms zero).

**G4 — existing round-trips.** `test_critical_load_card_export_roundtrip`,
`test_maneuver_export_roundtrip` and the V-TSEC suite pass unchanged — the cards equal
`net_loads` by construction, and the cut columns are untouched.

## 6. Deliverables

- `sbeam/solver/maneuver_qs.py::recover_step` — form the full `net_loads`; `closure` from
  it; `f_applied = net_loads`.
- `sbeam/results/results.py` — `ManeuverStep.net_loads` comment and the Step 68 comment
  rewritten (the "deliberately NOT folded in" paragraph is deleted, not softened).
- Labels that say "aero + inertial": `f06_writer.py` (`NET (AERO + INERTIAL) LOAD CLOSURE`
  and the critical-sample detail header), `maneuver_output.py` (card-block comments and
  docstrings), `load_export.py` module docstring, the viewer download caption. They say
  `AERO + INERTIA + ELASTIC INERTIA + DAMPING` on transient output, matching the Step 68
  `SOURCE:` line of the section-cut block. Static labels unchanged.
- Tests: G1a/G1b/G1c + companion in `tests/aero/test_maneuver_reapply.py`; G2/G3 in
  `tests/aero/test_maneuver_qs.py` / `test_section_cuts_transient.py`.
- Docs (Tier M): `05c_sol144_maneuver.md` — DEF-M5 paragraph ("net (aero + inertial)" →
  full applied load), the Step 68 "extra load column" subsection, the "Not covered" bullet
  removed, G1 added to the validation table; `monsect_transient_section_cuts.md` §9 O1
  marked resolved with a pointer here; `CHANGELOG.md`; one-line resolved entry plus the
  G1c figure in `docs/40_history/07_maneuver_transient.md`; #3 closed with the sha.

## 7. Acceptance

1. G1a/G1b pass on both sample decks under both solvers; the companion fails without the
   terms.
2. G1c's truncation figure is recorded.
3. G2, G3, G4 pass; full suite green.
4. The critical-sample section-cut `totals` and the exported cards for the same sample are
   now the same load — checked by G1b, which is the only place the two meet.
