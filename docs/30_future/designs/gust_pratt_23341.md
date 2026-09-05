# Quasi-Static Gust Load Cases — Pratt Formula (FAR/CS 23.341)

**Status:** ✅ **AGREED — no code.** Decisions D1–D7 settled in chat 2026-09-05 (§8).
Implementation may begin against this note.
**Issue:** [#1](https://github.com/Sean074/sbeam/issues/1) (`mission:E`, `physics`)
**Milestone / target release:** v0.3.0
**Owner:** Sean O'Meara
**Last updated:** 2026-09-05
**Related:** #23 (DEF-M20 URDD3/RCSID guard — **closed inside this change**, D6);
#4 (V-n / design-case matrix — extends the generator and owns the case-index table);
#5 (loads envelope & critical-case report — consumes the f06 provenance);
23.423 tail gust loads — **filed separately** (D2)

This document is the design for the mandatory FAR/CS-23 vertical-gust load cases. It needs no
DLM and no unsteady aerodynamics — it is the cheapest certification-gust path, identified as
missing in the 2026-08-04 process review (F7/R2).

**The load-bearing architectural decision (D3):** the regulation is *dimensional* — `U_de` is
50 ft/s, `ρ₀` is a sea-level density, the gust schedule is keyed to altitude in feet — while
conventions charter §7 forbids unit-converting fields anywhere in sbeam and the solver has no
atmosphere model. Rather than breach the charter, **the entire dimensional calculation moves
out of the solver into a preprocessing script.** The solver receives only a dimensionless load
factor. Charter §7 governs the solver; a tool that writes decks *for* the solver is free to
know what a foot is.

---

## 1. Motivation

### 1.1 The engineering problem

The mission is a FAR/CS-23 loads process. sbeam generates **maneuver** design cases today
(balanced pull-up/push-over at a commanded `n_z`) but **no gust cases at all** — and
23.333(c)/23.341 gust cases are mandatory, frequently critical, and on a low-wing-loading
airplane routinely exceed the maneuver envelope. The v-n diagram sbeam can populate today is
therefore only half a v-n diagram.

### 1.2 Why this is nearly free

23.341 poses the gust as a **load factor**, not a distributed gust field: the response to a
1-cosine gust is collapsed into a closed-form alleviation factor and applied as an incremental
`n`. That is exactly the input the Step-53 balanced-maneuver path already takes
(`URDD3 = −n_z·g`). Trim, inertia relief, monitor points, section cuts, envelopes and load
export are all unchanged and already validated.

### 1.3 What this delivers — two artefacts

1. **`scripts/gust_load_factor.py`** — a preprocessing tool, *outside* the `sbeam/` solver
   package. Reads a deck, extracts the airplane's own geometry/mass/slope, applies 23.333(c)
   and 23.341 in a declared unit system, and emits ready-to-run gust subcases.
2. **`GUSTLF` — a provenance card.** Carries the resulting load factor (which the solver uses)
   plus the derivation that produced it (which the solver only *echoes*). The f06 then states
   why a case exists, in the regulation's own terms, without the solver knowing a unit.

---

## 2. Scope

### 2.1 In scope

- Symmetric **vertical** gust load factors per 23.341, at V_C and V_D, positive and negative.
- Per mass case (MASSSET), altitude and design speed, reusing the existing sweep machinery.
- Full 23.333(c) `U_de` altitude schedule and an ISA atmosphere **in the script**.
- f06 provenance block; `n` flows into monitor/section loads like any maneuver case.
- **DEF-M20 (#23)** — the RCSID z-up/absent guard on `URDD3` (D6).
- A flagship gust deck at genuine V_C/V_D, and a convention-free closed-form validation deck.

### 2.2 Out of scope (declared, not overlooked)

- **Horizontal-tail gust loads (23.423)** — own formula, own trim posing (controls-fixed,
  increment reacted by airframe angular inertia). **Filed as its own v0.3.0 issue** (D2).
- **The case-index CSV** — deferred to #4 (V-n matrix), which already promises one. For #1 the
  f06 provenance block is the traceability artefact (D-extra).
- **V_B rough-air gust (66 fps, commuter only)** — the script implements the schedule so a
  V_B point costs one CLI flag, but no in-repo deck exercises it.
- **Flap-extended gust (23.345)**, **dynamic/tuned gust and turbulence** (Phase D, #16),
  **lateral gusts (23.443)** — the last blocked on DEF-M15/M16 (#8/#9).

---

## 3. The preprocessing script

### 3.1 `scripts/gust_load_factor.py`

```
.venv/bin/python scripts/gust_load_factor.py DECK.bdf \
    --units SI|IMPERIAL \
    --vc 85.0 [--vd 106.0] [--vb 70.0] \
    --altitude 0 [--altitude 6096 ...] \
    --massset 10,20,30 \
    --trim-template 1 \
    -o gust_cases.bdf
```

**Reads from the deck** (never retyped by the user — this is why the script parses the BDF):
`S`, `c̄` from `AEROS` (`sref`/`cref`); `W = m·g` from `compute_gpwg(bulk, massset)` per mass
case; `a` from a **rigid** derivative run (`compute_rigid_derivs` — no structure, no mass, no
`q`, so no trim is needed); the non-`URDD3` prescribed labels from `--trim-template`.

**Supplies from `--units`:** `ρ₀`, `g`, the ISA atmosphere `ρ(h)`, and the 23.333(c) `U_de`
schedule constants. Declaring the unit system is mandatory — there is no way to infer it from
a deck, and the script echoes its assumption in the output header (§7).

**Emits:** a BDF fragment of `TRIM` + `GUSTLF` pairs, one per
`(design speed × altitude × mass case × sense)`, plus a printed summary table.

`q = ½·ρ₀·V_EAS²` (identically `½·ρ·V_TAS²`), and `RHOREF = ρ(h)` so the solver's
`Trim.velocity()` returns true airspeed while Pratt uses EAS — the two densities stay
distinct by construction (§7).

### 3.2 Why the script may know units, and the solver may not

Charter §7 binds sbeam's card fields and solver arithmetic. `scripts/` is a preprocessing
tool that produces decks; it is versioned, linted, type-checked and CI-gated with sbeam
(§5.1) but is not part of the solver. Nothing dimensional crosses into `sbeam/`: the only
values the solver consumes from this feature are `N` (dimensionless) and `G` (a consistent-
units scalar the deck already supplies today for every maneuver case).

---

## 4. Card definition

### 4.1 GUSTLF — Gust Load Factor Case (sbeam extension)

Applies a precomputed gust load factor to a referenced TRIM, and records the derivation.
Selected by case control `GUSTLF = sid`.

**Format:**
```
GUSTLF, SID, TRIMID, N, G, UDE, VEAS, KG, MU
+,      A, ASRC, ALT
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Set ID (unique; referenced by case control `GUSTLF =`) | required |
| TRIMID | `trimid` | int | TRIM SID supplying Q, MACH and every prescribed label **except URDD3** | required |
| N | `n` | float | Gust load factor. **Used:** `URDD3 = −N·G`. May be negative (down-gust) | required |
| G | `g` | float | Gravitational acceleration, model units. **Used** | required |
| UDE | `ude` | float | Derived gust velocity `U_de` (EAS) — **recorded only** | `0.0` (not recorded) |
| VEAS | `veas` | float | Equivalent airspeed — **recorded only** | `0.0` |
| KG | `kg` | float | Gust alleviation factor `K_g` — **recorded only** | `0.0` |
| MU | `mu` | float | Mass ratio `μ` — **recorded only** | `0.0` |
| A | `a` | float | Lift-curve slope used, per radian — **recorded only** | `0.0` |
| ASRC | `asrc` | str | Slope source: `RIGID` or `RESTRAINED` — **recorded only** | `RIGID` |
| ALT | `alt` | float | Altitude — **recorded only** | `0.0` |

**Only `TRIMID`, `N` and `G` affect the solution.** Every other field is echoed to the f06 and
never enters an equation — which is precisely what keeps the regulation's dimensional content
out of the solver.

**Semantics.** `GUSTLF` supplies `URDD3` via the existing single-source helper
`load_factor_to_urdd3(N, G)` (`model/maneuver_presets.py:24`), never re-derived inline
(charter rule 2). The referenced TRIM must **not** prescribe `URDD3` — two sources for one
quantity is the DEF-M4 antipattern. `PITCH` is authored on the referenced TRIM (normally
`0.0`): a gust is an instantaneous plunge with no steady pitch rate, unlike a pull-up, which
carries `PITCH = (n−1)·g·c̄/(2V²)`. That asymmetry is stated in the card reference.

**Cross-reference validation (post-parse):** TRIMID must name an existing TRIM that does not
prescribe `URDD3`; `G > 0`; `N` finite; `ASRC ∈ {RIGID, RESTRAINED}`; recorded `UDE`, `VEAS`,
`MU`, `A` ≥ 0; **`KG`, when recorded, must satisfy `0 < KG < 0.88`** — the formula's strict
range, so an impossible recorded value is caught rather than printed — else `ValueError`.

**Example:**
```
$ +50 fps gust at V_C, sea level, MTOW — generated by scripts/gust_load_factor.py
GUSTLF, 700, 1, 3.996, 9.81, 15.24, 61.73, 0.6365, 13.855
+,      5.3335, RIGID, 0.0
$ ... and its down-gust partner
GUSTLF, 701, 1, -1.996, 9.81, 15.24, 61.73, 0.6365, 13.855
+,      5.3335, RIGID, 0.0
```

### 4.2 Case control

```
SUBCASE 10
  TITLE   = +50 fps gust at V_C, sea level, MTOW
  GUSTLF  = 700
  MASSSET = 30
  SPC     = 1
```

---

## 5. Mathematical formulation (implemented **in the script**)

### 5.1 The regulation, in consistent units

```
n   = 1 ± Δn ,      Δn = K_g · ρ₀ · U_de · V · a · S / (2·W)
K_g = 0.88·μ / (5.3 + μ)
μ   = 2·(W/S) / (ρ · c̄ · a · g)
```

- `ρ₀` sea-level density, pairing with `V` and `U_de` as **equivalent** airspeeds;
  `ρ` density **at altitude**, appearing only in `μ`. Transposing them is the classic error in
  this formula, so they arrive from different places by construction (§7).
- `a` — the **airplane normal-force curve slope** per radian. The regulation works in airplane
  normal force coefficient `C_NA` (FAR-23 guide §7.2.1), which is sbeam's **body-axis `CZ_α`**
  (charter §2, up-positive), *not* wind-axis `CL_α`. ANGLEA is in radians (charter §5), so
  `derivs['ANGLEA']['CZ']` is directly per-radian. **Rigid** — see D1.
- `W = m·g` from GPWG for the subcase's mass case.

### 5.2 `U_de` schedule (23.333(c)) and atmosphere — script-owned

| Design speed | Sea level → 20,000 ft | 20,000 → 50,000 ft |
|---|---|---|
| V_C | 50 fps (15.24 m/s) | linear to 25 fps (7.62 m/s) |
| V_D | 25 fps (7.62 m/s) | linear to 12.5 fps (3.81 m/s) |
| V_B (commuter) | 66 fps (20.12 m/s) | linear to 38 fps (11.58 m/s) |

`ρ(h)` from the ISA standard atmosphere (troposphere + lower stratosphere covers the whole
23.333(c) range).

### 5.3 The Imperial cross-check — the external validation anchor

The regulation's Imperial form is `Δn = K_g·U_de·V_kt·a / (498·(W/S))`. The constant 498 is
`2/(ρ₀·1.6878)` packaged with the knots→ft/s conversion:

```
2 / (0.0023769 slug/ft³ × 1.6878099 ft·s⁻¹/kt) = 498.53
```

A correct consistent-units implementation fed Imperial inputs must therefore reproduce the
regulation's own constant to **0.107 %**. This is an *external, non-circular* gate on the
formula's packaging, and it replaces the acceptance criterion originally written on issue #1
(D7).

### 5.4 Conventions relied on (charter citations, CLAUDE.md rule 1)

| § | What is relied on |
|---|---|
| §1 | Basic frame; URDD values given in RCSID and rotated to basic |
| §2 | `CZ` up-positive, nondimensionalised by `S_ref`; `CZ_α` is the normal-force slope |
| §5 | `URDD3 = −n_z·g`, RCSID z-down presumption (**and its guard — D6**), ANGLEA in radians, PITCH is a *rate* |
| §7 | User-defined consistent units; sbeam never converts — **the reason for the script/solver split** |
| §8 | `load_factor_to_urdd3` reused; the script's `μ`/`K_g`/`Δn` helpers are added to the §8 table |
| §9 | Section-cut/output signs — gust cases flow through MONSECT/MONPNT unchanged |

**Not relied on:** `rigid_rate_scales` DOF-2/4/6 (DEF-M15, #8) — this item is symmetric-only
and touches no lateral rate column, stated explicitly per the charter's DEF-M15 caveat.

---

## 6. Implementation plan

### 6.1 File touches

| File | Change |
|---|---|
| `scripts/gust_load_factor.py` *(new)* | The tool: ISA atmosphere, `U_de` schedule, `mass_ratio`, `alleviation_factor`, `gust_load_factor`, deck reader, BDF emitter, CLI |
| `pyrightconfig.json` | `include: ["sbeam", "scripts"]` — **otherwise the script ships untyped** |
| `.github/workflows/ci.yml` | `ruff check sbeam/ tests/ scripts/` |
| `sbeam/model/gust.py` *(new)* | `Gustlf` dataclass |
| `sbeam/model/bulk_data.py` | `gustlfs: dict[int, Gustlf]` |
| `sbeam/parser/bdf_reader.py` | `_handle_gustlf`, dispatch branch, post-parse cross-reference block |
| `sbeam/parser/case_control.py` | `gustlf_sid` on `SubcaseControl` + keyword |
| `sbeam/model/card_writers.py` | `write_gustlf` + `FAMILIES` entry (viewer round-trip for free) |
| `sbeam/solver/sol144.py` | Stage resolving the gust case: inject `URDD3` before `_stage_build_labels`; stash `gust_echo` |
| `sbeam/solver/sol144_util.py` *(or the URDD path)* | **DEF-M20 guard** (#23): warn when a negative `URDD3` is prescribed against an absent or z-up RCSID |
| `sbeam/results/results.py` | `gust_echo: Optional[dict[str, Any]] = None` on `Sol144TrimResult` |
| `sbeam/results/f06_writer.py` | Conditional provenance block (CHORDCP block is the template) |
| `sbeam/main.py` | Dispatch a `GUSTLF` subcase |

### 6.2 Order of operations

Single-pass by construction: the script computes `n` before the deck exists, and the solver
reads `n` off a card. The two-pass problem that an in-solver `RESTRAINED` slope would have
created does not arise (D1).

### 6.3 Backward compatibility

A deck with no `GUSTLF` parses, solves and writes a **byte-identical** f06 — asserted, as the
MONSECT and MASSSET blocks are.

---

## 7. Verification cases

### 7.1 Script gates — `tests/scripts/test_gust_load_factor.py` *(new dir)*

| ID | Case | Gate |
|----|------|------|
| **S-GUST1** | Imperial identity | consistent-units `Δn` reproduces the regulation's `498` form within **0.2 %** (§5.3) |
| **S-GUST2** | ISA atmosphere | `ρ` at 0 / 20,000 / 50,000 ft against published ISA table values, 0.5 % |
| **S-GUST3** | `U_de` schedule | 50/25/66 fps below 20,000 ft; 25/12.5/38 fps at 50,000 ft; linear between; both unit systems |
| **S-GUST4** | `K_g` bounds & monotonicity | `0 < K_g < 0.88`; `Δn` increases with `V`, decreases with `W/S` |
| **S-GUST5** | Flagship end-to-end | reproduces the §7.3 table from the **parsed deck** (GPWG mass, AEROS `sref`/`cref`, solved `CZ_α`), never module constants — the VAL2 discipline |
| **S-GUST6** | Emitted deck round-trips | the generated fragment parses, and its `GUSTLF` cards re-emit byte-identically through `card_writers` |

### 7.2 Solver gates — `tests/aero/test_gust_cases.py`

| ID | Case | Gate |
|----|------|------|
| **V-GUST1** | Trim closes on the gust load factor | `lift == n·W` within `rel=1e-6` (mirrors `test_lift_equals_nz_weight`) |
| **V-GUST2** | ± pair | up-gust trims to greater incidence than 1g, down-gust to less — signs **relative to the 1g case**, never absolute (charter §6) |
| **V-GUST3** | Negative-`n` case | the down-gust case (`n = −2.0` on the flagship) trims; `maneuver_closure ≈ 0` |
| **V-GUST4** | Monitor/section flow-through | gust subcase produces monitor and section-cut loads indistinguishable in form from a maneuver subcase |
| **V-GUST5** | f06 provenance block | present, correct, and column-aligned (add labels to `_NUMERIC_LABELS`) |
| **V-GUST6** | Non-regression | a deck without `GUSTLF` produces a byte-identical f06 |
| **V-GUST7** | **DEF-M20 guard (#23)** | negative `URDD3` against an absent or z-up RCSID warns; `sample/val_dihedral_trim.bdf` (which does this deliberately) stays green with the warning expected |
| **P-GUST1–6** | Parse rejections | unknown TRIMID; TRIM prescribing `URDD3`; `G ≤ 0`; bad `ASRC`; `KG` outside `(0, 0.88)`; negative recorded `UDE`/`MU`/`A` |

### 7.3 Expected numbers (flagship, computed 2026-09-05)

Cessna 210 flagship, `sample/cessna210_flagship_trim.bdf` SUBCASE 1 (`q = 2334 Pa`,
`ρ = 1.225`, `V = 61.730 m/s`), GPWG mass `1081.03 kg` → `W = 10 604.9 N`,
`S = 16.240 m²`, `c̄ = 1.4707 m`, `g = 9.81`, `ρ₀ = 1.225`, `U_de = 15.24 m/s` (50 fps),
rigid `CZ_α = 5.3335`:

| Quantity | Value |
|---|---|
| `μ` | 13.855 |
| `K_g` | 0.6365 |
| `Δn` | 2.9956 |
| `n` (up / down) | **+3.996 / −1.996** |

Two observations that matter:

1. The gust case at this condition is **far more critical than the 2.5 g maneuver case** the
   deck carries today (`n = 4.0` vs `2.5`) — precisely why the omission mattered.
2. This is the deck's **cruise** condition, not a design speed. The shipped gust deck defines
   genuine V_C/V_D (D5), so these numbers are the *unit-test* anchor, not the shipped case.

For reference, the elastic slopes on the same deck are `CZ_α` = 5.5188 (restrained) and
5.5704 (unrestrained), which would give `n = +4.070 / −2.070` — a 1.9 % difference, recorded
here so the D1 decision is auditable rather than invisible.

### 7.4 Sample decks

- `sample/cessna210_flagship_gust.bdf` — a fourth thin driver over the shared flagship bulk:
  ±U_de at **V_C and V_D**, across the three MASSSET payload cases, generated by the script and
  committed as generated output (with the generating command in the header).
- `sample/val_pratt_gust.bdf` — a minimal deck for the closed-form gate, with an
  `$ ACCEPTANCE (S-GUST5):` header paragraph in the `val_dihedral_trim.bdf` style.

---

## 8. Decisions (settled 2026-09-05)

| # | Decision | Rationale |
|---|---|---|
| **D1** | `a` = **rigid** `CZ_α`. No solver-side selector; `ASRC` records what the script used. | Pratt is a rigid-airplane derivation in plunge — feeding it an elastic slope mixes a flexible quantity into a rigid-body formula whose empirical constants were calibrated on the rigid basis. *Note:* `K_g` is an alleviation factor for rigid-body plunge during gust penetration plus unsteady lift growth — it is **not** a structural-flexibility correction; the justification for rigid is derivational consistency, not double-counting. Also single-pass (§6.2). |
| **D2** | **Balanced** posing (free ANGLEA + ELEV). 23.423 tail gust loads filed as their own v0.3.0 issue. | Balanced is what 23.341 asks for and what #1 specifies. 23.423 is a different formula, a different posing (controls fixed, increment reacted by angular inertia) and a different deliverable — scheduling it explicitly beats leaving a mandatory requirement unplanned. |
| **D3** | **All dimensional calculation moves to `scripts/gust_load_factor.py`;** the solver receives a dimensionless `N`. | The regulation is dimensional; charter §7 forbids unit-converting solver fields and there is no atmosphere model. The split honours both, and lets the script own the full 23.333(c) schedule and ISA atmosphere in either unit system. |
| **D4** | One `GUSTLF` per case; no `SENSE` field. | The script generates each ± case explicitly, so a multi-case card has no purpose. |
| **D5** | Flagship gust deck defines genuine **V_C/V_D**. | The current deck's `q` is a 120 kt cruise point; a shipped gust example must be a real certification case. |
| **D6** | **DEF-M20 (#23) closes inside this change.** | Gust cases generate the negative-`n` cases where the unguarded RCSID z-up/absent trap silently trims inverted lift. Generalize-on-first-find. |
| **D7** | Acceptance criterion on #1 **corrected**: the Imperial `498` identity replaces the non-existent "worked example". | `FAR23_UserGuide.pdf` carries the regulation text and the 23.423 formula but **no numeric worked example** — every "example" in it is a plot. Verified 2026-09-05. |
| **extra** | Case-index CSV **deferred to #4**; f06 provenance is #1's traceability artefact. | #4 already promises a case-index table; duplicating it here would create two records. |

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| `ρ` (altitude) and `ρ₀` (sea level) transposed — the classic error | They arrive from different places by construction: `ρ₀` from the script's unit system, `ρ(h)` from its ISA model. S-GUST1 catches a swap because the Imperial identity holds only with the correct pairing |
| Deck units disagree with `--units` | Unverifiable in principle (sbeam decks are unit-free). Mitigated by making `--units` mandatory, echoing it in the emitted deck header, and recording `UDE`/`VEAS` on the card where the f06 shows them next to the model's own `q` |
| Hand-edited `GUSTLF` with inconsistent provenance | The solver cannot check arithmetic it deliberately does not own. Bounded by the `0 < KG < 0.88` range gate and by the script writing the card in the first place |
| A new AESTAT-like label added naively | Avoided by design — `GUSTLF` injects a value for the *existing* `URDD3` label and adds no `D_jx` column. (`build_djx`'s `else` branch silently yields a zero column for an unknown label.) |

**Effort:** M — 2–3 days for the script (atmosphere, schedule, deck reader, emitter, 6 gates),
1–2 days for the card, solver stage, f06 block and DEF-M20 guard, plus decks and docs.

---

## 10. References

**Standards / regulation**
- FAR/CS 23.333(c) — gust envelope, `U_de` values and altitude schedule.
- FAR/CS 23.341 — gust load factors; the Pratt alleviation formula.
- FAR/CS 23.423 — horizontal tail gust loads (separate issue, D2).
- *FAR 23 Loads User Guide* (`~/Documents/Library/software_manuals/FAR23_UserGuide.pdf`)
  §11.2.1.3 (gust envelope, verbatim `U_de` schedule), §7.2.1 (`C_NA`), §12.2.4 (angular
  inertia reaction of gust tail increments).

**In-project precedents**
- `sbeam/model/maneuver_presets.py:24` — `load_factor_to_urdd3`, the `n → URDD3` helper.
- `sbeam/solver/sol144_derivs.py:42` — `compute_rigid_derivs` (structure-free, single-pass).
- `sbeam/gpwg.py:22` — `compute_gpwg`, mass per MASSSET case.
- `docs/10_standard/02_card_reference.md` MLOADS/MLDTRIM — the driver-references-TRIM pattern.
- `sbeam/results/f06_writer.py:540` — the CHORDCP echo block, template for the provenance block.
- `tests/aero/test_cessna210_flagship.py` T3 — the trim-closure gate this suite mirrors.
- `tests/integration/test_sample_verification.py` — the VAL2 recompute-from-the-deck discipline.

---

## 11. Acceptance criteria

- [ ] S-GUST1–6, V-GUST1–7 and P-GUST1–6 green in CI; full suite green.
- [ ] `scripts/` is linted (`ruff`) and type-checked (`pyright` strict) in CI.
- [ ] A deck without `GUSTLF` produces a byte-identical f06.
- [ ] `docs/10_standard/02_card_reference.md` — GUSTLF entry (six-column table; the FAR `U_de`
      values documented in fps **and** m/s; the used-vs-recorded field split stated).
- [ ] `docs/10_standard/05c_sol144_maneuver.md` — gust-case section incl. the script workflow.
- [ ] `docs/10_standard/09_conventions.md` — §8 rows for the script's gust helpers; the D1
      decision recorded in §5 with its gate; the DEF-M20 guard noted against the §5 bullet.
- [ ] `docs/10_standard/00_program_overview.md` — S-GUST/V-GUST rows in the verification tables.
- [ ] `CLAUDE.md` supported-cards list; `CHANGELOG.md` entry.
- [ ] Full step-format entry in `docs/40_history/06_sol144_static_aeroelastic.md` + its index;
      DEF-M20 recorded as a resolved defect.
- [ ] One commit with `(#1)` in the subject; `gh issue close 1` and `gh issue close 23`, each
      with the merge SHA.
