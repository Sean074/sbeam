# V-n Design Case Matrix — Maneuver Corner Points (23.337 / 25.337)

**Status:** 🟡 **PROPOSED** — awaiting agreement (CLAUDE.md rule 1: design note before code).

**Issue:** [#4](https://github.com/Sean074/sbeam/issues/4) (`mission:E`, `decision`)
**Milestone / target release:** [v0.7.0](https://github.com/Sean074/sbeam/milestone/6) (moved from v0.3.0, 2026-09-05 — v0.3.0's aim is a mature solver)
**Owner:** Sean O'Meara
**Last updated:** 2026-09-05
**Process context:** [`../loads_process.md`](../loads_process.md) — stages 1–2
**Related:** [#1](https://github.com/Sean074/sbeam/issues/1) gust family (done — this note extends its generator);
[#5](https://github.com/Sean074/sbeam/issues/5) envelope/report; [#35](https://github.com/Sean074/sbeam/issues/35) critic;
[#36](https://github.com/Sean074/sbeam/issues/36) LRA delivery; [#16](https://github.com/Sean074/sbeam/issues/16) Part 25 dynamic gust

**No solver changes** except one correction this note obliges (§7).

---

## 1. Objective

Stop hand-authoring the case set. From a certification basis, design speeds, design weights
and altitudes, generate the maneuver corner points of the V-n envelope beside the Pratt gust
points already delivered by #1, as one runnable deck plus a machine-readable case index.

The index is the load-bearing artefact: it is the join key that lets #5/#35/#36 post-process
with no solver changes, and after D3 below it is the **only** carrier of the certification
basis.

---

## 2. Theory and regulatory basis

### 2.1 Limit maneuvering load factors

| | FAR/CS-23 (pre-Amdt 23-64) | FAR/CS-25 |
|---|---|---|
| `n_max` | `2.1 + 24000/(W+10000)`, cap 3.8; utility 4.4, acrobatic 6.0 | same formula, cap 3.8, **floor 2.5** |
| `n_min` | `−0.4·n_max` (`−0.5·n_max` acrobatic) | **−1.0** |
| shape | `n_min` held to V_C, linear to zero at V_D | *same* |

`W` is the **design maximum takeoff weight in pounds** — one value for the airplane, not the
weight of each mass case. The regulation says so explicitly, and it matches the placard.

The two rulesets are consistent rather than arbitrary. The 3.8 cap binds below **4,117 lb**
(`24000/(W+10000) = 1.7`); Part 25's 2.5 floor binds only above **50,000 lb**
(`= 0.4`). Part 23's own weight ceiling — 12,500 lb normal/utility/acrobatic, 19,000 lb
commuter — sits far below that crossover, which is why the floor never appears there: inside
Part 23's weight range the formula alone always exceeds 2.5.

### 2.2 Design speeds

- **V_A** — 23.335(c)/25.335(c): `V_A ≥ V_S1·√n_max`, need not exceed V_C. **Not derivable**
  (§4.3).
- **V_B** — required under Part 25 (25.335(d)); commuter-only under Part 23.
- **V_C, V_D** — user-declared.

### 2.3 Steady pull-up kinematics

A corner point is a load factor **and** a steady pitch rate. In charter §2 nondimensional
form:

```
PITCH = q̄ c̄ / (2 V)   with   q̄ = (n − 1) g / V      ⇒    PITCH = (n − 1) g c̄ / (2 V²)
```

**`V` here is TRUE airspeed**, because the pitch rate is a real angular rate.
`V_TAS = V_EAS/√(ρ/ρ₀)`. Dynamic pressure remains `q = ½ρ₀V_EAS²`. At sea level the two
coincide, which is why the hand-authored flagship deck cannot distinguish them — see §6.2.
This is the same class of trap as ρ₀-vs-ρ in Pratt, and is handled the same way: the two
speeds arrive from different places by construction.

### 2.4 Charter citations

- **§2** — `a` is the body-axis normal-force slope `CZ_α`, taken **rigid**; `PITCH` is the
  reduced rate `qc̄/2V`.
- **§5** — `URDD3 = −n_z·g`, presuming a z-down RCSID. The DEF-M20 guard added by #1 already
  covers maneuver TRIMs, since it triggers on any prescribed negative `URDD3`.
- **§7** — sbeam never converts units. Every dimensional constant here (pounds, feet,
  ft/s) lives in `sbeam_tools/`, per the boundary rule established by #1.
- **§8** — single-source helpers: `load_factor_to_urdd3` and `card_writers.write_trim` are
  reused, not reimplemented.

---

## 3. Scope

### 3.1 In scope

- Maneuver corner points under FAR/CS-23 and FAR/CS-25, per design speed, altitude and mass
  case.
- Certification-basis selection, with Part 25 gust method as an explicit choice.
- Applicability guards (weight ceiling; the existing 50,000 ft gust-schedule limit).
- The case index, shared by the gust family.
- A generated flagship case-matrix deck and its gates.
- The f06 citation correction (§7).

### 3.2 Out of scope (declared, not overlooked)

- **Part 25 dynamic gust** — 25.341 tuned discrete gust and continuous turbulence. `--gust
  dynamic` refuses, naming #16.
- **The negative stall corner** (`V_A_neg = V_S1·√|n_min|`) — needs C_Nmax, same reason as
  §4.3. The flat negative edge is generated at V_A and V_C instead.
- **Bank angle / steady turns** — O2 below.
- **Flap-extended (23.345), rolling (23.349), yawing (23.441)** — lateral work, #10 behind
  DEF-M15/M16 (#8/#9).
- **Downselect and delivery** — #35 and #36.

---

## 4. Design

### 4.1 Module layout

```
sbeam_tools/
    common/
        units.py          + force_per_lbf          (new field — the pound in 23.337)
        case_index.py     NEW  write + read cases.json
    cases/
        regulations.py    NEW  the ruleset objects
        maneuver.py       NEW  corner points
        gust.py                unchanged but for the U_de table split (§4.5)
        cli.py                 extended
```

`regulations.py` holds one object per basis exposing `n_max(design_weight_lb, category)` and
`n_min(n_max)` plus its applicability guard. Two concrete implementations, ~20 lines each,
because §2.1 shows the rulesets share their shape.

### 4.2 CLI

```
sbeam-cases deck.bdf --units SI --trim-template 1 \
    --basis FAR23 --category normal \
    --family maneuver,gust \
    --va 60.0 --vc 86.0 --vd 105.0 \
    --altitude 0 --altitude 3000 \
    --massset 10,20,30 \
    --index cases.json -o matrix.bdf
```

| Flag | Rule |
|---|---|
| `--basis` | required; `FAR23`/`CS23`/`FAR25`/`CS25`, recorded **as given**, not normalised |
| `--category` | Part 23 only; an error under Part 25, which has no categories |
| `--gust` | Part 25 only, **required, no default** — `pratt` or `dynamic` (D5) |
| `--va` | required for `--family maneuver` |
| `--vb` | required under Part 25; optional (commuter) under Part 23 |
| `--cnmax` | optional — derives V_A and cross-checks a declared one |
| `--nmax`, `--nmin` | optional overrides; 23.337 sets a floor, not a ceiling |
| `--design-weight` | optional; defaults to the heaviest declared mass case |
| `--index` | output path for `cases.json` |

### 4.3 V_A is a user input, not a derived one

`V_A ≥ V_S1·√n_max` needs `V_S1`, which needs C_Nmax — which a linear VLM does not have and
never will. So V_A is declared. `--cnmax` is offered as an alternative that derives V_A and
prints V_S1, but the primary input is the speed itself: V_A is a number the loads engineer
already holds from performance work, whereas C_Nmax invites an argument about what stall
means on a stick model.

### 4.4 The corner points generated

Per (altitude × mass case), with `n_max`/`n_min` fixed for the airplane:

| Point | Speed | n | Note |
|---|---|---|---|
| A | V_A | `n_max` | max α; wing torsion, inboard loading |
| C⁺ | V_C | `n_max` | on the top edge, but at cruise q |
| D⁺ | V_D | `n_max` | max q at limit n |
| A⁻ | V_A | `n_min` | flat negative edge |
| G | V_C | `n_min` | corner of the negative edge |
| E | V_D | `0` | negative edge's linear run to zero |

Six maneuver cases per (altitude, mass case), beside #1's two gust cases per (speed,
altitude, mass case, sense).

Each emits a `TRIM` with `URDD3 = −n·g`, `PITCH` per §2.3, `URDD5 = 0`, `RHOREF = ρ(h)`,
`Q = ½ρ₀V_EAS²`, and the template's remaining prescribed labels. No new card: the `TRIM`
already states `URDD3` explicitly, so a maneuver case needs no `GUSTLF` analogue (D4).

### 4.5 The `U_de` schedules

`_UDE_FPS` (23.333(c)) is joined by a separately named pre-Amdt-25-86 25.341 table, **not an
alias**, even though the values are believed identical (66/50/25 fps at V_B/V_C/V_D, constant
to 20,000 ft, linear to 38/25/12.5 at 50,000 ft). Aliasing would let a future divergence
inherit silently.

### 4.6 The case index

Schema in [`loads_process.md` §4](../loads_process.md). `meta` carries
`basis`, `gust_method`, `category`, `units`, `g`, the generator version, and SHA-256 of the
emitted driver **and each INCLUDE** — editing the bulk model where the structure lives must
invalidate the index too.

---

## 5. Decisions

| | Decision | Rationale |
|---|---|---|
| **D1** | Certification basis is a user input, both Parts implemented | The rulesets share their shape; ~20 lines each. Named by the user as in scope, so CLAUDE.md rule 5 is satisfied. |
| **D2** | `W` in the `n_max` formula is design max takeoff weight, applied to all mass cases | The regulation defines it so; it is one placarded number, not a per-case quantity. |
| **D3** | **The basis never reaches the solver** | It is an attribute of why a case was generated, not of how it is solved. Consequence: the index is its only carrier, and §7 follows. |
| **D4** | No maneuver provenance card | The `TRIM` already states `URDD3`. The asymmetry with `GUSTLF` is accepted: the index carries the provenance, and #4 promises no solver changes. |
| **D5** | `--gust` required under Part 25, no default | Choosing Pratt for a transport is a deliberate preliminary-design decision. A decision that defaults is a decision nobody remembers making. |
| **D6** | `--gust dynamic` refuses, naming #16 | A flag that states its own completion condition beats Part 25 users silently receiving Pratt. |
| **D7** | Applicability guarded, not assumed | Same principle as the existing 50,000 ft refusal: a certification quantity outside its stated domain stops rather than extrapolates. |
| **D8** | `PITCH` uses **V_TAS** | It is a real angular rate. §2.3. |
| **D9** | Separate `U_de` tables per basis | §4.5. |

---

## 6. Validation and acceptance

### 6.1 Arithmetic gates (exact, rel. tol 1e-12)

The limit-factor rules are closed-form, so the anchors are exact crossovers rather than
tolerances:

| Gate | Expected |
|---|---|
| M-VN1 | `n_max` cap crossover: W = 4,117.647 lb gives exactly 3.8 |
| M-VN2 | Part 25 floor crossover: W = 50,000 lb gives exactly 2.5 |
| M-VN3 | FAR23 normal, flagship MTOW 1560 kg → 3,440.9 lb → formula 3.8856 → **capped 3.8**; `n_min = −1.52` |
| M-VN4 | FAR25, same weight → `n_max = 3.8` (cap), `n_min = −1.0` — the −52% difference on the negative envelope |
| M-VN5 | FAR23 utility 4.4 / acrobatic 6.0, `n_min` −1.76 / −3.0 |
| M-VN6 | Part 23 above 12,500 lb (19,000 commuter) raises; Part 25 has no lower guard |
| M-VN7 | `--gust dynamic` raises, naming #16 |

### 6.2 The in-repo end-to-end anchor

`sample/cessna210_flagship_bulk.bdf:438` carries a **hand-authored** 2.5 g pull-up:

```
TRIM, 2, 0.0, 2334.0, RHOREF, 1.225, PITCH, 2.8402-3
```

With `n = 2.5`, `g = 9.81`, `c̄ = 1.4707`, `q = 2334`, `ρ = 1.225` ⇒ `V² = 2q/ρ = 3810.20`:

```
PITCH = 1.5 × 9.81 × 1.4707 / (2 × 3810.20) = 2.84017e-3
```

**M-VN8:** the generator, given the same inputs, reproduces `2.8402e-3` to the deck's five
significant figures (rel. tol 1e-5). This is the issue's "reproduces a hand-built reference
set" criterion made concrete, against a number written before this tool existed.

**Its limitation, stated:** the anchor is at sea level, where V_TAS = V_EAS, so it does *not*
validate D8. **M-VN9** covers that separately — at altitude, `PITCH(V_TAS)/PITCH(V_EAS)` must
equal `ρ/ρ₀` — since using EAS there would be wrong by exactly that ratio and no sea-level
test can see it.

### 6.3 Integration gates

- **M-VN10** — every generated case runs end to end on the flagship; the achieved `URDD3`
  echoes `−n·g`.
- **M-VN11** — the case index round-trips, and its subcase ids match the emitted deck exactly.
- **M-VN12** — a hand-edited deck makes the index's hash check warn.
- **M-VN13** — the Part 25 code path runs on the flagship. A Cessna 210 would never be
  certified under Part 25; this exercises the path and the sample says so in a comment. It is
  a code-path exercise, **not a certification claim**.
- **S-GUST1–6a** stay green unchanged — the safety net for touching the gust module.

### 6.4 Sample deck

`sample/cessna210_flagship_vn.bdf`, FAR23 normal, V_A 60 / V_C 86 / V_D 105 m/s, three
MASSSETs, sea level. V_A is illustrative for a sample — it follows from a stated
`V_S1 ≈ 30.9 m/s` as `30.9·√3.8 = 60.2`, and is not a measured certification number.

---

## 7. The correction this note obliges

`sbeam/results/f06_writer.py:541` hardcodes:

```
G U S T   L O A D   C O N D I T I O N   (GUSTLF, FAR/CS 23.341)
```

Under D3 the solver cannot know that citation is true, and for a Part-25 Pratt case it is
false. **The header loses the citation; the `U_de`/`K_g`/`μ`/`a` values stay exactly as they
are.** Same treatment for the docstrings at `bdf_reader.py:1143`, `model/gust.py:1` and
`case_control.py:16`, which describe `GUSTLF` as a 23.341 card when it is really a
Pratt-formula card that two rulesets use.

**Tier M** — behaviour change to an existing output; `05c_sol144_maneuver.md` and the f06
gate update with it.

---

## 8. Open items

| | Item | Working assumption |
|---|---|---|
| **O1** | Negative envelope shape | `n_min` held to V_C, then linear to zero at V_D, for both rulesets — §4.4's A⁻/G/E points. Confirm against the 23.333(b) / 25.333(b) figures. |
| **O2** | Bank angle | Out of scope. A steady coordinated turn at load factor n is aerodynamically identical to a symmetric pull-up at n on this model; the part that is not — roll/yaw rate and sideslip — is blocked behind DEF-M15/M16 (#8/#9) and lands with #10. Resolves the issue's `decision` label. |

Both are one-line changes if read differently, and neither blocks the rest of the note.
