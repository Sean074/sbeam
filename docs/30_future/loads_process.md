# The Loads Process — End to End

**Status:** 🟡 process definition, agreed in chat 2026-09-05. **Target: milestone
[v0.7.0](https://github.com/Sean074/sbeam/milestone/6).** Stages 0 and 3 are implemented
today; stages 1–2 ([#4](https://github.com/Sean074/sbeam/issues/4)), 4a
([#5](https://github.com/Sean074/sbeam/issues/5)), 4b
([#35](https://github.com/Sean074/sbeam/issues/35)) and 5
([#36](https://github.com/Sean074/sbeam/issues/36)) are not.
**Last updated:** 2026-09-05

**Why this lives in `30_future/`:** `10_standard/` is the authoritative description of how
sbeam works *today*, and four of this document's five stages do not exist yet. It moves to
`10_standard/` when v0.7.0 delivers them. **Why v0.7.0 and not v0.3.0:** v0.3.0's aim is a
mature *solver*; this process is the toolchain built on one, and placing it after the
dynamic-gust work ([#16](https://github.com/Sean074/sbeam/issues/16), v0.6.0) means it is
built once against the complete set of case families rather than retrofitted twice.

This document describes what an **external loads engineer** does with sbeam from a finished
structural model to a package handed to the **stress office**, and it is the yardstick the
tooling is measured against. It exists because #4 and #5 were each specified against their
neighbour rather than against the person using both, and that hid three gaps (§7).

It is a *process* document. Card fields live in
[`02_card_reference.md`](../10_standard/02_card_reference.md), solver behaviour in
[`05c_sol144_maneuver.md`](../10_standard/05c_sol144_maneuver.md), signs and frames in
[`09_conventions.md`](../10_standard/09_conventions.md). Nothing is duplicated from those here.

---

## 1. The architecture this implements

From [`00_program_overview.md`](../10_standard/00_program_overview.md):

> The solver reads a deck and writes results for the cases it is given. It never decides
> which cases exist, and it never reduces across runs.

Every stage below is therefore either **solver** (stage 3, and the model in stage 0) or
**toolchain** (`sbeam_tools/`, everything else). The toolchain may know units, atmospheres
and regulatory constants; the solver may not.

---

## 2. The five stages

```
0  MODEL      bulk deck: structure, mass (MASSSET per weight/cg), aero,
   [done]     MONPNT3 at the LRA, MONSECT stations, one template TRIM

1  DECLARE    certification basis, category, gust method, design speeds,
   [#4]       altitudes, mass cases, design max takeoff weight

2  GENERATE   sbeam-cases  →  matrix.bdf   one subcase per design case
   [#4]                       cases.json   why each subcase exists

3  RUN        sbeam matrix.bdf
   [done]                 →  .f06, monitor_loads.csv, section_loads.csv,
                             *.maneuver_loads.bdf

4a REPORT     sbeam-report →  envelope CSV, driving-case attribution,
   [#5]                       critical-case tables, TeX/PDF + convention appendix
                              DESCRIPTIVE — "case 9012 drives WS 3400"

4b CRITIC     sbeam-critic →  downselected case set
   [new]                      cases_selected.json (same schema)
                              DECISIVE — "these 14 cases go to stress"

5  DELIVER    LRA package  →  one BDF per selected case, loads at the LRA
   [new]                      monitor points, plus the case definitions
```

Stages 4a and 4b are deliberately separate tools. **Enveloping is descriptive and
deterministic; downselecting is policy.** The envelope of a run is a fact that will not
change; the selection criteria vary by programme and will be revised. Splitting them keeps a
criteria change out of the report generator and its LaTeX. The cost — two tools reading the
same join — is paid once by putting the join itself in `sbeam_tools/common/`.

---

## 3. Stage 1 — declaring the design cases

### 3.1 What the deck already supplies

Read back from the model rather than retyped, so a case can never disagree with the deck it
will be solved on (`sbeam_tools/common/deck.py`):

| Quantity | Source |
|---|---|
| S, c̄, Mach | `AEROS`, the template `TRIM` |
| W per mass case | `compute_gpwg(bulk, massset).total_mass × g` |
| rigid C_Nα (`CZ_α`) | `compute_rigid_derivs` — no trim solve |
| prescribed labels to inherit | the template `TRIM`, minus `URDD3` |
| SPC, INCLUDEs | the driver's case control |

**cg is not a separate input axis.** A forward-cg and an aft-cg condition are two `MASSSET`s,
so cg variation rides on the mass-case list exactly as weight does.

### 3.2 What the user declares

| Input | Notes |
|---|---|
| certification basis | `FAR23` / `CS23` / `FAR25` / `CS25` — recorded **as given**, not normalised |
| category | Part 23 only; an error under Part 25, which has no categories |
| gust method | Part 25 only, **required, no default** — `pratt` or `dynamic` |
| V_A | not derivable — a linear VLM has no C_Nmax (§3.4) |
| V_B, V_C, V_D | V_B required under Part 25 (25.335(d)); commuter-only under Part 23 |
| altitudes | swept; the `U_de` schedule and ISA density follow |
| mass cases | `MASSSET` SIDs |
| design max takeoff weight | the W in the 23.337/25.337 formula — *not* the weight of each case |

### 3.3 The two rulesets

They draw the same diagram and disagree about two numbers:

| | FAR/CS-23 | FAR/CS-25 |
|---|---|---|
| `n_max` | `2.1 + 24000/(W+10000)`, cap 3.8; utility 4.4, acrobatic 6.0 | same formula, cap 3.8, **floor 2.5** |
| `n_min` | −0.4·`n_max` (−0.5 acrobatic) | **−1.0** |
| envelope shape | `n_min` held to V_C, then linear to zero at V_D | *same* |
| gust | 23.341 Pratt | 25.341 tuned discrete + continuous turbulence (**not implemented** — #16), or pre-Amdt-25-86 Pratt |

`W` is in **pounds** in both formulas — a dimensional constant, and therefore toolchain
territory (charter §7). The active constraint differs at each end of the weight range: the
3.8 cap binds below ~4,117 lb, Part 25's 2.5 floor only above 50,000 lb. Part 23's own weight
ceiling (12,500 lb; 19,000 lb commuter) sits well below that crossover, which is why the 2.5
floor never appears there — the formula alone is always above it.

**Applicability is guarded, not assumed.** Part 23 above its weight ceiling refuses rather
than producing a number, the same way the 23.333(c) `U_de` schedule refuses above 50,000 ft
instead of extrapolating a certification quantity.

**`--gust dynamic` refuses today**, naming #16 as what would make it work. A flag that states
its own completion condition is better than Part 25 users silently receiving Pratt.

### 3.4 V_A is the one input that is neither

23.335(c) gives V_A ≥ V_S1·√n_max, and V_S1 needs C_Nmax — which a linear VLM does not have
and never will. The user states V_A directly; `--cnmax` optionally derives and cross-checks
it. V_A is a number the loads engineer already has from performance work, whereas C_Nmax
invites an argument about what stall means on a stick model.

---

## 4. Stage 2 — the case index

`cases.json` is the load-bearing artefact of the whole process: it is the join key that lets
stages 4a/4b post-process with no solver changes, and it is **the only carrier of the
certification basis**.

```jsonc
{
  "schema_version": 1,
  "meta": {"deck": "...", "deck_sha256": "...", "includes": [{"file": "...", "sha256": "..."}],
           "basis": "FAR25", "gust_method": "pratt", "category": null,
           "units": "SI", "g": 9.80665, "generator": "sbeam <version>", "generated": "..."},
  "cases": [
    {"subcase": 9000, "trim": 9000, "family": "GUST", "speed": "VC",
     "v_eas": 86.0, "altitude": 0.0, "massset": 10, "mass_case": "FERRY",
     "n": 5.42506, "ude": 15.24, "kg": 0.621831, "mu": 12.76566, "a": 5.333485}
  ]
}
```

Hashes cover the emitted driver **and its INCLUDEs** — editing the bulk model where the
structure actually lives must invalidate the index too. Downstream tools warn on mismatch.

**The basis never reaches the solver.** It is an attribute of why a case was generated, not
of how it is solved, and the solver has no use for it. The consequence is that an index-less
run is a run whose regulatory basis is unrecoverable — so the index travels with the results,
always.

> **Corollary (fix owed by #4):** `f06_writer.py` currently hardcodes the block header
> `G U S T   L O A D   C O N D I T I O N   (GUSTLF, FAR/CS 23.341)`. The solver cannot know
> that citation is true — for a Part-25 Pratt case it is false. The header loses the
> citation; the `U_de`/`K_g`/`μ`/`a` values stay. **The solver echoes numbers; the index
> names the basis.**

---

## 5. Stage 3 — running, and the artefacts that become interfaces

One `sbeam` run over `matrix.bdf` produces the per-case outputs described in
[`05c_sol144_maneuver.md`](../10_standard/05c_sol144_maneuver.md). Three of them are consumed by tools and
are therefore **public interfaces**, not human output:

| Artefact | Consumed by | Hardening |
|---|---|---|
| `monitor_loads.csv` | 4a, 4b, **5 (the delivered loads themselves)** | #31 |
| `section_loads.csv` | 4a, 4b | #31 |
| `*.maneuver_loads.bdf` | 5 | #31 (scope extension) |

A column rename in any of these is a breaking change. #31 adds the header gates, fixes the
unstable `massset` dtype and documents the ordering/dtype contract.

---

## 6. Stages 4b and 5 — the stress hand-off

### 6.1 The LRA is the monitor points

The Loads Reference Axis is **defined in the structural model as `MONPNT3` monitor points**.
This is the decision that makes stage 5 a formatter rather than a capability:

- `MONPNT3` integrates **aero + inertia + reaction** over a `SET1` of structural grids — the
  net load stress applies. `MONPNT1` is aero-only and is *not* the LRA card.
- `monitor_loads.csv` already carries F/M at each monitor's reference point, per case and per
  mass case, with its `cid` and `x_ref/y_ref/z_ref`.
- No load transfer, lumping or static-equivalence machinery is needed. The loads arrive at
  the LRA because the model was asked for them there.

**Closure gate.** For a delivered set to be complete and non-double-counting, the `MONPNT3`
`SET1`s must partition the load-bearing grids. The delivered monitor loads, summed about a
common reference, must reproduce the case's whole-airplane net load. Note that the
`whole_airplane` column does **not** provide this — it is a parity annotation (`parity ≠ 1`),
not a coverage flag. DEF-M10's `MONPNT3` mass-coverage warning is the precedent for the
check.

### 6.2 The delivery package

| Item | Produced by | Notes |
|---|---|---|
| one `.bdf` per selected case | stage 5 | `FORCE`/`MOMENT` at the LRA monitor reference points |
| `cases_selected.json` | stage 4b | same schema as `cases.json`, `meta.derived_from` + the selection criterion |
| envelope CSV + critical-case PDF | stage 4a | includes the sign-convention appendix (§11 figures) |
| the deck and its hashes | stage 2 | so the package is re-runnable |

Re-runnability is the part that matters: a stress office that cannot regenerate a number
cannot defend it.

**Units reach stress only by convention.** The numbers are in model units by charter §7 and
only the index knows which system. Every delivered table and every generated deck header
states it.

### 6.3 Sequencing consequences

- **#2 (`MONPNT1`/`MONPNT3` on transient maneuvers) blocks every transient delivery.** If the
  LRA is monitor points and monitors do not exist on transient maneuvers, no MLOADS case can
  be handed over at all. Filed as a ~0.5 d output-surface gap; it is on the critical path.
- **#3 (transient `net_loads` elastic-inertia decision) blocks the package contents.** What is
  *in* a delivered transient case is undecided until it lands.

---

## 7. What writing this down found

Recorded because the value of the exercise was in the gaps, not the prose:

1. **The delivery package was unspecified** — the mission's last mile owned by no issue.
2. **Downselect ≠ envelope**, and #5 owned only the envelope. Now stage 4b, its own tool.
3. **Units had no route to stress** beyond convention.
4. **The f06 named a regulation it cannot know** (§4 corollary).
5. **#2 and #31 were mis-prioritised** — both sit under the stress hand-off, not beside it.

---

## 8. Open items

Marked here rather than silently assumed. Both are one-line changes if read differently.

| # | Item | Working assumption |
|---|---|---|
| O1 | Negative envelope shape | `n_min` held to V_C, then linear to zero at V_D, for **both** rulesets. Corner points (V_A, n_max), (V_D, n_max), (V_C, n_min), (V_D, 0). Confirm against the 23.333(b) / 25.333(b) figures. |
| O2 | Bank angle | **Out of scope for #4.** A steady coordinated turn at load factor n is aerodynamically identical to a symmetric pull-up at n on this model; the part that is not — roll/yaw rate and sideslip — is blocked behind DEF-M15/M16 (#8/#9) and lands with the lateral work (#10). |

---

## 9. Issue map

| Stage | Issue | Milestone |
|---|---|---|
| 1–2 generate | [#4](https://github.com/Sean074/sbeam/issues/4) V-n / design-case matrix | **v0.7.0** |
| 3 run | done (SOL 144 + G0) | v0.2.0 |
| 4a report | [#5](https://github.com/Sean074/sbeam/issues/5) envelope & critical-case report | **v0.7.0** |
| 4b critic | [#35](https://github.com/Sean074/sbeam/issues/35) `sbeam-critic` downselect | **v0.7.0** |
| 5 deliver | [#36](https://github.com/Sean074/sbeam/issues/36) LRA delivery package | **v0.7.0** |
| interfaces | [#31](https://github.com/Sean074/sbeam/issues/31) harden the CSVs and loads BDF | v0.3.0 |
| transient | [#2](https://github.com/Sean074/sbeam/issues/2), [#3](https://github.com/Sean074/sbeam/issues/3) | v0.3.0 |
| Part 25 dynamic gust | [#16](https://github.com/Sean074/sbeam/issues/16) | v0.6.0 |
| viewer over these tools | [#11](https://github.com/Sean074/sbeam/issues/11) | v0.4.0 |
