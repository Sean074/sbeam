# Horizontal-Tail Gust Loads — Controls-Fixed Gust Posing (FAR/CS 23.425) — design note for issue #29

**Status:** 📝 **DRAFT 2026-10-25 — decisions D1–D8 (§9) pending agreement** (CLAUDE.md rule 1).
No code until they are agreed in chat.

- **Issue:** [#29](https://github.com/Sean074/sbeam/issues/29) (`mission:E`, `physics`)
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1)
- **Tier L:** new card, new trim posing, new single-source helper, new charter bullet.
- **Owner:** Sean O'Meara
- **Related:** #1 (`GUSTLF`, the Pratt helpers in `sbeam_tools/cases/gust.py`, design note
  `gust_pratt_23341.md` D2, which split this item out); #4 / v0.7.0 (systematic case-family
  generation); MLOADS `NZ_REL` (charter §5 — same defect class as finding F1, D5).

---

## 1. The gap

#1 applies the 23.341 Pratt load factor as a **balanced** maneuver: `URDD3 = −n·g` with
`ANGLEA` and `ELEV` free. That is what 23.341 asks for and it gives the correct airplane load
factor — but it re-trims the elevator for the gust, so the horizontal tail ends up carrying
only the balance load for `n`. On the flagship at V_C / MTOW the tail carries **+248 N**.

The horizontal-surface gust requirement is a different problem: the gust strikes an airplane
whose controls are **fixed** at the 1g trim, the incremental tail load is "reacted by the
angular inertia of the airplane in a rational or conservative manner" (FAR-23 Loads User
Guide §12.2.4b), and the total is the **1g balancing tail load plus the gust increment**. On
the same flagship condition that gives **+3435 N** (up-gust) and **−4937 N** (down-gust) —
about 14× the balanced figure. The tail sizing case is missing today.

## 2. Scope

**In scope**
- Symmetric vertical gust at V_C and V_D, positive and negative, per mass case (MASSSET),
  aft horizontal tail.
- The 1g balancing state and the gust state in one subcase; total = 1g + increment.
- Tail-load recovery (a named MONPNT1), and the airplane-`n` cross-check against Pratt.
- Tool support to emit the cases; a flagship sample deck.

**Out of scope (declared)**
- 23.425(a)(2) — flaps-extended ±25 fps at V_F (no deck defines a flap surface; 23.345 was
  likewise out of #1).
- Unsymmetrical tail loads (23.427); lateral/fin gust (23.443).
- Part 25 horizontal-tail gust (dynamic gust, #16).
- The systematic sweep over speed × altitude × mass case — v0.7.0, per the 2026-09-05
  comment on #29. This item delivers the posing plus a deck-level demonstration.
- Canard configurations (the posing works, but the formula's `1 − dε/dα` is aft-tail only).

## 3. Physics

### 3.1 The effective gust angle

The Pratt formula and the tail formula share one quasi-static gust angle,

```
Δα = K_g · U_de / V_EAS
```

applied to the whole airplane at fixed controls. With `q = ½ρ₀V²`:

```
airplane:  Δn    = q·S·CZ_α·Δα / W               = K_g·ρ₀·U_de·V·a·S / (2W)        (23.341)
tail:      ΔL_ht = q·Δα·a_ht(1 − dε/dα)·S_ht      = K_g·U_de·V·a_ht·S_ht(1 − dε/dα)/498  (Imperial, 23.425)
```

The `498` is the same `2/(ρ₀·1.6878)` packaging as #1 §5.3. The VLM supplies the downwash
factor itself: a uniform Δα changes the wing's downwash at the tail, so the solved tail
increment already contains `(1 − dε/dα)`. Nothing in the solver needs to know `a_ht` or
`dε/dα` separately.

### 3.2 The posing

| State | Prescribed | Free |
|---|---|---|
| 1g reference | `URDD3 = −g`, `PITCH = 0`, `URDD5 = 0` | `ANGLEA`, `ELEV` |
| Gust | `ANGLEA = α₁g + Δα`, `ELEV = δ₁g`, `PITCH = 0` | `URDD3`, `URDD5` |

Both are **determined** against the flagship's `SUPORT 900,35`. Free URDDs are already
supported (the Step 63 fix in `_stage_solve_trim` rebuilds free URDD labels in the RCSID
frame). `PITCH = 0` in the gust state: the gust is instantaneous, so there is no pitch rate
yet — only a pitch acceleration.

### 3.3 Finding F1 — URDD3 is the reference-point acceleration

`URDD3` is the acceleration of the **RCSID origin** (the SUPORT point), not the CG. With
`URDD5` prescribed zero (every existing trim, every GUSTLF) the two coincide, which is why
this has never mattered. With `URDD5` free they don't:

```
a_cg = a_ref + θ̈ × r_(cg/ref)      →     n_cg = n_ref + (x_cg − x_ref)·θ̈ / g   (flagship geometry)
```

Prototype (rigid limit, §8): `n_ref = 4.100019`, `θ̈ = URDD5 = 4.18807`,
`x_cg − x_ref = 2.55100 − 2.4375` → **`n_cg = 4.148473`**, Pratt's `4.148473` to seven
digits. The cross-check #29 promises holds — **at the CG only**. The implementation uses the
rigid-body kinematics in `assembly/rigid_body.py` through a new helper (§5), never a
hand-written sign.

### 3.4 Finding F2 — the regulation is §23.425, not 23.423

In the pre-Amdt-64 Part 23 numbering, 23.421 is balancing loads, **23.423 is maneuvering
loads** (sudden deflection / checked maneuver — the sense in which
`transient_net_loads_elastic_inertia.md:75` already uses it), and **23.425 is gust loads on
horizontal surfaces**, carrying the `498` formula and the "add the increment to the initial
balancing load" rule. **To verify** against `FAR23_UserGuide.pdf` (not available when this
note was drafted) — D1.

### 3.5 Finding F3 — the elastic airplane exceeds Pratt

On the elastic flagship the same Δα gives `n_cg = 4.356` — Δn 6.6 % above Pratt — because
the elastic slope is larger (`CZ_α`: rigid 5.308, restrained 5.684, unrestrained 5.728).
Pratt and `K_g` are rigid-airplane constructions (#1 D1). D4 proposes reporting the
difference, not correcting it.

## 4. Card definition

### 4.1 GUSTHT — Horizontal-Tail Gust Case (sbeam extension)

```
GUSTHT, SID, TRIMID, DALPHA, G, UDE, VEAS, KG, NPRATT
+,      DLHT, AHTE, SHT, ALT, HTMON
```

| Field | Type | Role | Description | Default |
|---|---|---|---|---|
| SID | int | — | Set ID; case control `GUSTHT = sid` | required |
| TRIMID | int | **used** | TRIM supplying Q, MACH and the reference labels (rules below) | required |
| DALPHA | float | **used** | Effective gust angle Δα, rad, signed (negative = down-gust) | required |
| G | float | **used** | Gravity in model units — 1g reference `URDD3 = −G`, and `n` recovery | required |
| UDE | float | recorded | Derived gust velocity (EAS) | `0.0` |
| VEAS | float | recorded | Equivalent airspeed | `0.0` |
| KG | float | recorded | Alleviation factor `K_g` | `0.0` |
| NPRATT | float | recorded | Pratt load factor for the same gust (#1) — printed beside the solved `n_cg` | `0.0` |
| DLHT | float | recorded | Regulation-formula tail increment ΔL_ht | `0.0` |
| AHTE | float | recorded | `a_ht(1 − dε/dα)`, per radian | `0.0` |
| SHT | float | recorded | Horizontal-tail area | `0.0` |
| ALT | float | recorded | Altitude; `Optional`, blank = not recorded (as GUSTLF) | blank |
| HTMON | str | output | Name of a MONPNT1 whose 1g / gust / increment is echoed | blank |

**Only `TRIMID`, `DALPHA` and `G` affect the solution.** `HTMON` only selects what the f06
block prints.

**Cross-reference validation (post-parse, `ValueError`):** TRIMID exists; the TRIM does not
prescribe `URDD3` (the card supplies it, DEF-M4 single-source rule); the TRIM prescribes
`PITCH = 0` and `URDD5 = 0` (steady unaccelerated reference); the reference free set is
`{ANGLEA} ∪ {≥ 1 AESURF label}` and nothing else; SUPORT is exactly the symmetric pair
(3, 5); `G > 0`; `DALPHA` finite and nonzero (**warn** when `|DALPHA| > 0.35 rad`, the
linear-VLM range); `KG`, when recorded, in `(0, 0.88)`; `HTMON`, when given, names an
existing MONPNT1. The parse-time "over-determined but no TRIMOBJ" diagnostic is taught about
GUSTHT exactly as it was about GUSTLF (#1 §6.1a), and a gate asserts the generated deck parses
clean.

### 4.2 Case control

```
SUBCASE 9100
  TITLE   = +15.24 m/s tail gust at VC, alt 0 m, MTOW
  GUSTHT  = 9100
  MASSSET = 30
  SPC     = 1
```

`GUSTHT` and `GUSTLF` are mutually exclusive in one subcase.

## 5. Solver

In `sbeam/solver/sol144.py`:

1. `_stage_validate_inputs` resolves the GUSTHT (as it does GUSTLF).
2. **Reference pass** — the referenced TRIM solved balanced with
   `URDD3 = load_factor_to_urdd3(1.0, G)`, the same injection path GUSTLF uses, reusing the
   subcase's `aero_cache`. Keeps `α₁g`, every free surface's `δ₁g`, and the HTMON loads.
3. **Gust pass** — a `label_overrides` field on `_TrimState`, consumed in
   `_stage_build_labels`, replaces the prescribed set with `ANGLEA = α₁g + DALPHA`, each
   reference-free surface at its 1g value, `PITCH = 0`, and frees `URDD3`, `URDD5`. Every
   downstream stage (recovery, monitors, sections, exports) runs unchanged on this state, so
   all loads are **totals** (1g + increment), as 23.425 requires.
4. The result carries `gust_ht_echo` (reference values, `n_ref`, `n_cg`, `URDD5`, recorded
   provenance, HTMON 1g / gust / increment).

**New single-source helper** (charter §8): `urdd_to_cg_load_factor(urdd_basic, r_cg, r_ref, g)`
in `sbeam/model/maneuver_presets.py`, beside `load_factor_to_urdd3`, using the rigid-body
transfer from `assembly/rigid_body.py`.

**f06 block**, after the subcase/MASSSET header and before `T R I M   V A R I A B L E S`,
prose-formatted like the GUSTLF block (out of the column-alignment gate's scope by
construction):

```
             H O R I Z O N T A L   T A I L   G U S T   (GUSTHT, FAR/CS 23.425)

      GUSTHT = 9100     TRIM = 9100     SENSE = UP-GUST     CONTROLS FIXED AT 1G
      1G REFERENCE:  ANGLEA = 2.689E-02     ELEV = -4.196E-02
      DALPHA = 1.234E-01     ANGLEA = 1.503E-01
      URDD3 (REF PT) = ...     URDD5 = ...     N (REF PT) = ...     N (CG) = ...
      PRATT N (RECORDED) = 4.148E+00     N(CG)/PRATT = ...
      MHTAERO  CZ FORCE:  1G = ...   GUST = ...   INCREMENT = ...   FORMULA DLHT (RECORDED) = ...

      RECORDED PROVENANCE ONLY — DALPHA AND G ENTER THE SOLUTION; SBEAM DOES NOT COMPUTE THE GUST.
```

Cost: two trim solves per GUSTHT subcase; the aero cache is shared.

## 6. Tool

`sbeam_tools/cases/gust.py` gains `--tail --ht-aelist SID`:

- `DALPHA = K_g·U_de/V_EAS` and `NPRATT` from the existing helpers (`mass_ratio`,
  `alleviation_factor`, `gust_load_factor`), rigid slope per #1 D1.
- `AHTE·SHT` from the **rigid** ANGLEA column's tail-box forces at fixed controls;
  `SHT` from the CAERO1 geometry of the named AELIST; `DLHT = q·DALPHA·AHTE·SHT`.
- Emits `TRIM` + `GUSTHT` pairs, one per (speed × altitude × mass case × sense).

**Sample:** `sample/cessna210_flagship_tailgust.bdf` — V_C/V_D × ± × three MASSSET cases, sea
level, generated output with the generating command in its header. An HT `AECOMP`/`MONPNT1`
(`MHTAERO`, boxes 3000–3047 and 4000–4047) is added to the shared flagship bulk (D7).

## 7. Conventions relied on (charter citations)

| § | What is relied on |
|---|---|
| §1 | Basic frame; URDDs authored in RCSID, rotated to basic |
| §2 | `CZ` up-positive; `CZ_α` is the regulation's normal-force slope |
| §5 | `URDD3 = −n·g` at the RCSID origin, z-down RCSID, DEF-M20 guard. **New bullet:** URDD3 is the RCSID-origin acceleration; `n` at the CG needs the URDD5 transfer (F1); `NZ_REL` labelled as reference-point |
| §6 | Elevator sign is airframe-dependent — every gate is relative to the 1g case, never absolute |
| §7 | Units stay in the tool; the solver sees a radian and a `G` |
| §8 | `load_factor_to_urdd3` reused; `urdd_to_cg_load_factor` added |
| §9 | Monitor-point signs — HTMON flows through MONPNT1 unchanged |

**Not relied on:** lateral rate columns (symmetric-only item).

## 8. Verification

### 8.1 Expected numbers (prototype, 2026-10-25)

In-memory runs of the current solver on `sample/cessna210_flagship_gust.bdf` SUBCASE 9004
(V_C = 86.0 m/s EAS, sea level, MTOW): `q = 4530.05`, `m = 1560.03 kg`, `g = 9.81`,
`U_de = 15.24`, `K_g = 0.69631`, Pratt `n = 4.148473`.
*Recomputed 2026-10-25 after the #52 WT2 correction fix (the first draft's numbers were
taken on the asymmetric correction).*

| Quantity | Rigid limit (E, G ×1e6) | Elastic flagship |
|---|---|---|
| `Δα` | 0.123393 rad (7.070°) | same |
| `α₁g` / `δ₁g` (rad) | — | 0.026893 / −0.041956 |
| `n_ref` (−URDD3/g) | 4.100019 | 4.308920 |
| `URDD5` | 4.18807 | 4.09006 |
| `n_cg` | **4.148473** | 4.356 |
| 1g tail load (N) | −754.6 | −751.0 |
| tail increment ΔL_ht (N) | **4207.54** | ±4185.81 |
| `a_ht(1−dε/dα)·S_ht` (m²/rad) | 7.52725 | 7.48837 |
| tail total, up / down (N) | — | **+3434.8 / −4936.8** |
| balanced 23.341 case tail (N), for contrast | — | +247.9 |

With `S_ht = 3.114 m²` the implied `a_ht(1 − dε/dα) = 2.417 /rad`; against a Helmbold
isolated-tail slope of ≈ 3.81 /rad that is `dε/dα ≈ 0.37` — physically plausible for this
layout.

### 8.2 Gates

| ID | Gate | Tolerance |
|---|---|---|
| **S-HTG1** | Consistent-units ΔL_ht reproduces the regulation's `498` form | 0.2 % |
| **S-HTG2** | `DALPHA = K_g·U_de/V`; the emitted deck parses **clean** | exact / no warning |
| **V-HTG1** | Rigid limit: `n_cg` = Pratt `n` (4.148473 vs 4.148473) — the non-circular cross-check | rel 1e-5 |
| **V-HTG2** | Rigid limit: tail increment = tool's DLHT (4207.54 N) | rel 1e-5 |
| **V-HTG3** | `n_cg − n_ref = (x_cg − x_ref)·URDD5/g` (guards F1) | rel 1e-9 |
| **V-HTG4** | Controls held: `ELEV = δ₁g` exactly, `ANGLEA = α₁g + Δα`; Fz/My closure ≈ 0 | abs 1e-6 |
| **V-HTG5** | Linearity: ± increments equal and opposite | rel 1e-9 |
| **V-HTG6** | Signs relative to 1g: up-gust tail increment > 0, down-gust < 0 | — |
| **V-HTG7** | Elastic flagship regression anchor (§8.1 right column) | rel 1e-4 |
| **V-HTG8** | f06 block content and conditional emission; decks without GUSTHT byte-identical | exact |
| **P-HTG1–9** | Parse rejections of §4.1 | `ValueError` |

## 9. Decisions (proposed — agree before code)

| # | Proposal | Rationale |
|---|---|---|
| **D1** | Cite **§23.425**; retitle #29 once verified. Part 25 out of scope. | F2 — 23.423 is maneuvering loads in this numbering |
| **D2** | The 1g reference is solved **inside the subcase by the solver**, not by the tool writing absolute ANGLEA/ELEV. | Exact (no float round-trip), single source, one f06 shows both states. It is per-case physics, so within the architecture boundary — the deck still decides which cases exist |
| **D3** | **Companion card `GUSTHT`**, not a mode on GUSTLF. | In GUSTLF `N` is an input; here `n` is an output. One field with two meanings by mode is the thing to avoid |
| **D4** | Δα applied **as-is to the elastic airplane**; μ and `K_g` from the rigid slope (#1 D1). The elastic `n` exceeding Pratt (+6.6 % Δn, F3) is reported, not corrected. | The gust angle is the regulation's input; the elastic response to it is the rational analysis. The 23.341 GUSTLF case stays the airplane-`n` case of record |
| **D5** | Report `n` **at the CG** via the new helper; label URDD3 as the reference-point acceleration. Rule-3 sweep in this change: charter §5 bullet and `NZ_REL` labelling; a CG-corrected `NZ_REL`, if wanted, filed as its own issue with a body. | F1. No code inverts URDD3→n today, so the sweep is documentary plus `NZ_REL` |
| **D6** | Symmetric only: SUPORT exactly the symmetric pair; reference `PITCH = URDD5 = 0`. | 23.425(c) "steady unaccelerated flight"; keeps the posing determined |
| **D7** | Tail recovery through optional `HTMON`; the HT MONPNT1 goes in the **shared** flagship bulk. | A tail monitor point is useful to every flagship case. Cost: flagship monitor CSVs gain one row — regenerate any golden files |
| **D8** | v0.3.0 ships the posing and the deck demonstration; the systematic sweep is v0.7.0. | The #29 scoping comment (2026-09-05) |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Linear VLM at Δα ≈ 7° (≈ 0.21 rad at V_D lower) | Fine for loads at these angles; warn above 0.35 rad |
| Reference-point vs CG load factor confused | F1/D5; V-HTG3 gate; the f06 prints both, labelled |
| Hand-edited provenance inconsistent | Unverifiable by design (as #1); `KG` range gate; the tool writes the card |
| Twice the trim cost per subcase | Aero cache shared; acceptable at stick-model scale |

**Effort:** M — about 1 day for the tool, 2 days for card, solver passes, helper and f06
block, plus the deck and docs.

## 11. References

**Regulation**
- FAR/CS 23.333(c) (`U_de` schedule), 23.341 (Pratt), 23.421 (balancing loads),
  23.425 (horizontal-surface gust loads — to verify, F2).
- *FAR 23 Loads User Guide* §12.2.4 (angular-inertia reaction of the tail increment).

**In project**
- `docs/30_future/designs/gust_pratt_23341.md` — #1, D1 (rigid slope), D2 (this split), §5.3
  (the `498` identity).
- `sbeam/model/gust.py` — `Gustlf`, the provenance-card pattern.
- `sbeam/model/maneuver_presets.py` — `load_factor_to_urdd3`.
- `sbeam/solver/sol144.py` — `_stage_build_labels` (GUSTLF injection), `_stage_solve_trim`
  (free-URDD frame handling).
- `sbeam/solver/sol144_derivs.py` — `compute_rigid_derivs`.
- `sbeam_tools/cases/gust.py` — Pratt helpers and deck emitter.
- `docs/10_standard/09_conventions.md` §5, §6, §8.
