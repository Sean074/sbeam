# Applied structural load in the SOL 144 trim RHS — design note for issue #6

**Status:** ✅ **agreed 2026-10-24**, ✅ **implemented 2026-10-24** (CLAUDE.md rule 1): D1
trim-only scope with the MLOADS / DIVERG silent-drop closed by refusal, D6 propeller
handedness decided through a torque case, D7 dedicated validation deck — all accepted as
recommended. Implementation decisions in §9 (including the correction of the §6 "10 %
elastic" reading).
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1) ("thrust-in-trim" is
  named in its definition of done).
- **Tier L:** new capability and new physics in the trim balance (an applied-load term), a
  schema change on two CSVs, and a new charter convention.
- **Issue:** [#6](https://github.com/Sean074/sbeam/issues/6) (DEF-M4 follow-on).
- **Related:** DEF-M4 (`40_history/06`, 2026-08-01) promised this term; theory
  `02_realistic_airplane_sol144.md` §7.2 documents the gap; [#22](https://github.com/Sean074/sbeam/issues/22)
  (DEF-M19, no OLOAD applied-load block) is adjacent and stays open; the lateral note
  `lateral_cases_aileron_rudder.md` fixed the aileron sign this note's torque case consumes.

---

## 1. The gap

`run_sol144_trim` builds its right-hand side from three terms only
(`solver/sol144.py::_stage_build_downwash_and_reduce`):

```
f_rhs = q·f_g  +  q·Q_ax·δ_prescribed  +  M_ax·a_prescribed
```

so a `LOAD` request in a trim subcase has nowhere to go. DEF-M4 made the combination
*refuse* instead of silently dropping the load, which is the right stop-gap and the wrong
end state: the one airplane the repository calls its flagship is a tractor-prop, and the
thrust-line moment of a powered trim has no honest home (theory §7.2 lists a `cm0` fudge
that scales with `q` instead of with thrust, and the restrained static path that gives up
free-flight trim). The issue asked two physics questions before any code:

1. does an applied load participate in inertia relief, and
2. what does `maneuver_closure` mean once it enters the balance?

**Found in review (same defect class, swept here).** An `MLOADS` subcase carrying `LOAD`
is silently dropped today: `maneuver_qs.py:415` and `maneuver_modal.py:302` rebuild the
initial-condition subcase without `load_sid`, so the DEF-M4 guard never sees it. A
`DIVERG`-only subcase with `LOAD` is likewise ignored.

## 2. Theory

### 2.1 One more right-hand-side vector

Theory `01_aeroelastics_theory.md` Eq. 18 already writes the trim RHS as `q f_g + f_ext`;
the code simply never had an `f_ext`. With the applied g-set load `f_struct` from the
subcase `LOAD` set (`assembly/load_vector.py::assemble_load_vector` — `FORCE`, `MOMENT`,
`LOAD` combinations with their scale factors), the flexible trim equation is

```
(K_aa − q·Q_aa)·u_a = q·f_g + q·Q_ax·δ + M_ax·a + f_struct ,     u_r = 0,  reaction_r = 0
```

`build_trim_schur` (`solver/sol144_trim_solve.py:18-69`) partitions the a-set into the
elastic l-set and the SUPORT r-set and reduces **the whole RHS** onto the r-set:

```
schur_b = f_rhs_r − K_rl·K_ll⁻¹·f_rhs_l ,     K = K_aa − q·Q_aa
```

Nothing in that reduction knows which term is aerodynamic. Adding `f_struct` to `f_rhs`
therefore gives, for free:

- the **rigid moment** of the applied load about the reference point (the `f_rhs_r` part),
- its **elastic aero coupling** (the structure deflects under the load, the deflection
  changes the normalwash, the aero changes the balance — all inside `K_ll⁻¹` because `K_ll`
  carries `−q·Q_ll`),
- and the **over-determined** and **GUSTLF** trims, which consume the same `schur_b`.

This is the MSC SOL 144 formulation: the `P_l` / `P_r` applied-load terms in MSC's
unrestrained-derivative chain (Aeroelastic Analysis UG Eqs. 2-110 ff.), already named in
`compute_unrestrained_derivs`' docstring, are exactly this vector.

### 2.2 The two questions, answered by the linear algebra

**Inertia relief needs no separate rule.** The r-set equations say *the resultant of
every load on the free aircraft, about the reference, is zero in the SUPORT directions*.
Which unknown absorbs the applied load is decided by the labels, not by a new switch:

| Label state | What balances the applied load |
|---|---|
| a free aero label (ANGLEA, ELEV, AIL, …) | the aerodynamic increment of that label |
| a free URDD label | the rigid-body acceleration — `m·URDD1 = T + Fx_aero` for a free surge |
| a prescribed URDD / no label in that direction | nothing in the trim: the component is reacted at the SPC that restrains that rigid DOF (every rigid DOF is either SUPORT or SPC, else `K_ll` is singular) |

So on the ordinary `SUPORT 35` / `SPC 1246` recipe the thrust x-component is reacted at
the SPC grid and **only its moment about the reference enters the pitch trim**, which is
the textbook statement of the thrust-line effect. On `SUPORT 135` with URDD1 free the
surge equation is trimmed and the aircraft accelerates at `(T + Fx_aero)/m`.

**Closure keeps its meaning.** `net_loads = aero + inertial + applied` and
`maneuver_closure = resultant(net_loads)` about the reference is zero in the SUPORT
directions by construction, exactly as before; in an SPC'd direction it equals minus the
reaction, exactly as before (the existing "warn only when the model has no SPC" rule
already covers it). What changes is the *name* of the quantity: "aero vs inertia" becomes
"the full applied load", the same definition the transient already uses (#3).

### 2.3 Rigid closed form (the design number)

Thrust `T` along −x (forward) at `z_T` below the reference, basic axes x aft / z up:

```
r × F = (0, 0, −d) × (−T, 0, 0) = (0, +T·d, 0)        d = z_ref − z_T
ΔCm   = T·d / (q·S·c)        nose-UP (+My basic): a low thrust line pitches up
[CZ_α  CZ_δe ] [Δα ]   [  0  ]
[CM_α  CM_δe ] [Δδe] = [−ΔCm ]       ⇒ Δδe > 0 (TE-down, nose-down) for d > 0
```

Engine torque reaction `+Mx = Q` (§3 D6) on the lateral deck:

```
[CMX_δa  CMX_δr] [δa]     [Q/(q·S·b)]
[CMZ_δa  CMZ_δr] [δr] = − [    0    ]       ⇒ δa < 0 (starboard TE-up) for a clockwise prop
```

### 2.4 Not a follower force

`FORCE`/`MOMENT` are basic-frame loads and the basic frame **is** the body frame: ANGLEA is
a flow angle (charter §5, theory Eq. 10a), the body never rotates in the solve. A thrust
line authored along body −x stays along body −x at every trimmed α. No follower-force
term exists or is needed.

## 3. Decisions

- **D1 Scope — TRIM subcases only.** Plain, over-determined and GUSTLF trims take the
  `LOAD`. An `MLOADS` subcase with `LOAD` **raises** (DEF-M4 wording: the load would enter
  the initial-condition trim and then be dropped from the time history); carry-through as
  a constant load is filed as a follow-on with a body, for the v0.7.0 case matrix if a
  powered time history ever needs it. A `DIVERG`-only subcase with `LOAD` raises
  (homogeneous eigenproblem; nothing to apply it to).
- **D2 GRAV refused** in a trim `LOAD` set, directly or through a `LOAD` combination.
  Gravity enters through `URDD3` only (theory §7.3: "gravity is folded into the load
  factor"); a `GRAV` card beside it is the two-sources-for-one-quantity defect DEF-M4
  closed, and the gravity double-count the closure warning (KC9) exists to catch.
- **D3 Body-fixed loads, used exactly as authored** (charter §9 bullet) — §2.4.
- **D4 Derivatives and unrestrained intercepts stay aero-only.** Rigid, restrained and
  unrestrained derivatives are sensitivities and a constant load has none; `CZ0`/`CMY0`
  remain the `w_g` baseline (dimensionless by `q·S·c`, which a thrust is not). The applied
  load is reported as its own six-component resultant about the reference in the f06
  trim block (`APPLIED STRUCTURAL LOAD (LOAD=<sid>)`), which is also the honest partial
  answer to DEF-M19 for trim subcases.
- **D5 Monitor and section outputs gain an `applied` column** beside aero / inertia /
  reaction (`MonitorLoad.applied`, `SectionCutStation.applied`; `Fz_applied` in
  `monitor_loads.csv`, `c1_applied … c6_applied` in `section_loads.csv`). Schema change
  per `10_export_schemas.md` §6, recorded under **Breaking changes**; it ships in the same
  unreleased 0.3.0 as the #31 stabilisation, so no released consumer breaks. The f06
  monitor source line says `+ APPLIED` only when the subcase carries a `LOAD`, so every
  shipped f06 stays byte-identical.
- **D6 Propeller handedness — decided here, consumed by the torque case** (charter §10
  GAP → rule). Basic axes x aft, y starboard, z up.
  - A propeller is **clockwise** when it turns clockwise as seen **from behind** (the
    pilot's view; Lycoming, Continental, PT6). Its rotation vector is along **−x**
    (forward), because a right-hand rotation about an axis pointing away from the viewer
    appears clockwise.
  - **Torque reaction on the airframe:** the engine drives the propeller about −x, so the
    airframe feels **+Mx basic** of magnitude `Q = P/Ω` at the mount — starboard wing up,
    i.e. the textbook roll toward **port**. Authored as `MOMENT sid gid 0 Q 1. 0. 0.`.
    Counter-clockwise is −Mx. Holding wings level needs roll toward starboard = starboard
    TE-up = **negative AIL** (lateral note D1).
  - **Swirl** (documented rule, no gate until a powered correction deck exists): the
    slipstream rotates with the propeller, so a clockwise propeller puts **downwash
    (Δα < 0) on the starboard side** of the nacelle and upwash on the port side; a fin
    above the slipstream sees a +y crossflow, i.e. +Fy at the tail, i.e. nose-to-port =
    +CMZ basic (lateral note D2) — the familiar left-turning tendency. Counter-clockwise
    flips every sign. The per-strip `a0`/`W2GJ` signs of a powered correction follow from
    this and the W2GJ sign rule of charter §3.
- **D7 Validation deck:** new `sample/val_thrust_trim.bdf` (§5); the flagship bulk and
  drivers are untouched. Theory §7.2 is rewritten to point at the capability.
- **D8 Tier L** — full step format in `40_history/06`.

## 4. Conventions cited (`09_conventions.md`)

| § | Used for |
|---|---|
| §1 Frames | basic x aft / y starboard / z up; +My nose-up; +Mx starboard-wing-up |
| §5 Trim and maneuver states | ANGLEA is a flow angle (D3); URDD3 = −n·g carries gravity (D2) |
| §6 Control surfaces | ELEV lift-increasing = TE-down = nose-down; AIL positive rolls toward port (torque sign) |
| §9 Internal loads | "applied loads are used exactly as authored" now includes the trim (D3); section-cut sign for the pylon cut |
| §10 Engines | GAP → the handedness rule (D6); thrust-in-trim sentence replaced |
| §8 helpers | `load_resultant` is the single resultant for closure and the f06 applied-load line |

## 5. Validation (benchmark-first) — gates G1–G10

**Deck `sample/val_thrust_trim.bdf`** (V-THR). AR 8 rectangular wing (b = 8, c = 1, S = 8,
20 × 8 boxes per half) + horizontal tail (span ±1.5, chord 1, z = 0.5, 6 × 8 per half)
with an elevator on the aft two rows; stiff CBAR spine; nose grid 10 at x = −1.5; **engine
grid 70 at (−1.5, 0, −0.5) on `RBAR 70`**; reference grid 90 at (0.25, 0, 0) = RCSID origin
(z-down stability axes) = SUPORT point; total mass 10 at CG (0.30, 0, −0.05). `SUPORT 90 135`,
`SPC1 1 246 90`; labels ANGLEA, PITCH, URDD1, URDD3, URDD5; one `TRIM 1` (q = 51, PITCH 0,
URDD3 −9.81, URDD5 0) shared by three subcases: 1 no load; 2 `LOAD 710 = 1.0 × FORCE 701`;
3 `LOAD 701` directly. `FORCE 701`: T = 40 along −x at grid 70. Monitors: `MONPNT1 MAERO`,
every-grid `MONPNT3 MALL`, nose free-body `MONSECT SECNOSE` (axis x, SIDE NEG, members
grids 10 + 70), wing `MONSECT SECRW`.

**Lateral deck `sample/val_lateral_aileron_rudder.bdf`** gains `MOMENT 701 90 0 35 1 0 0`
(clockwise-propeller torque reaction) and `TRIM 3` / `SUBCASE 3` (ROLL = SIDES = YAW = 0,
URDD4 = URDD6 = 0, `LOAD 701`; AIL and RUD free).

| Gate | Statement | Tolerance |
|---|---|---|
| **G1** Schur identity | `δ(SC2) − δ(SC1)` equals `solve(schur_A, f_r − K_rl K_ll⁻¹ f_l)` built by `build_trim_schur` from the solver's own `K_aa, Q_aa, Q_ax_a, M_ax_a` with `f_rhs = reduce(f_struct)` alone; `u_a` likewise through `recover_u_a` | rel 1e-10 |
| **G2** rigid closed form | on a stiffened copy (E, G × 1e6) Δα, Δδe equal the rigid 2 × 2 solve of §2.3 — surge free with `ΔCm = T·(z_cg − z_T)/(qSc) = 0.044118` (about the **CG**, §9), `SUPORT 35` variant with `ΔCm = T·(z_ref − z_T)/(qSc) = 0.049020`; Δδe > 0 | rel 1e-6 |
| **G3** linearity | SC3 ≡ SC2 bit for bit; T × 2 (in-test) doubles every shift | 1e-10 / exact |
| **G4** closure / surge | `maneuver_closure` ≈ 0 in all six components; `m·URDD1 = T + Fx_aero`; in-test `SUPORT 35` + `SPC 1246` variant: MONPNT3 reaction `Fx = +T`, closure `Fx = −T` (reacted, not trimmed), Schur identity holds, and the ELEV shift is 20/18 of the free-surge one (moment about the reference vs about the CG, §9) | 1e-9·‖aero‖ / rel 1e-12 / 1e-3 |
| **G5** load path | `SECNOSE` carries `c1_applied = −T`, `c5_applied = +0.5·T` at both stations; every-grid `MONPNT3`: aero + inertia + applied + reaction = 0; both CSV headers match the constants (schema gate extended) | 1e-12·T / 1e-9 |
| **G6** derivatives untouched | rigid, restrained, unrestrained derivatives and intercepts identical across SC1–SC3 | exact |
| **G7** refusals | `GRAV` direct and via `LOAD` → `ValueError` naming URDD3; `MLOADS` + `LOAD` → `ValueError` (direct and modal); `DIVERG`-only + `LOAD` → `ValueError`; the no-LOAD trim is unaffected | — |
| **G8** torque / handedness | lateral SC3: AIL, RUD equal the 2 × 2 solve of the restrained derivatives against `−[Q/(qSb), 0]`; **AIL < 0**; closure in Mx, Mz ≈ 0 | rel 1e-8 |
| **G9** bit-identity | every shipped SOL 144 f06 / `aero_loads.bdf` / `maneuver_loads.bdf` byte-identical to the pre-change run; flagship pins unchanged; only the two CSV headers differ (zero-filled new columns) | diff |
| **G10** CLI | `python -m sbeam.main sample/val_thrust_trim.bdf` writes the f06 with the APPLIED block, both CSVs and `maneuver_loads.bdf`; import-boundary gate green | — |

## 6. Prototype (2026-10-24, `release/0.3.0` @ `1287ff7`, RHS stage wrapped in a scratch script)

Deck as in §5; q = 51, W = 98.1, `W/(qS) = 0.240441`.

| Quantity | SC1 (no load) | SC2 = SC3 (T = 40) | Shift |
|---|---|---|---|
| ANGLEA (rad) | 5.01709053e-2 | 4.79009927e-2 | −2.2699e-3 |
| ELEV (rad) | −4.93313504e-2 | −3.35497731e-2 | **+1.5782e-2** (TE-down, nose-down) |
| URDD1 (RCSID, forward +) | 0 | **4.000000** = T/m | +4.0 |
| CZ | 0.240441 | 0.240441 | 0 |
| CMY | −0.012022 | −0.056140 | −0.049118 |
| applied resultant about ref | — | (−40, 0, 0, 0, +20, 0) | ΔCm = 20/408 = 0.049020 |
| closure (aero + inertia + applied) | 1e-13 | 1e-13 | — |

Rigid 2 × 2 with `CZ_α = 5.5819, CM_α = −3.4807, CZ_δe = 0.80291, CM_δe = −3.2963` and
`ΔCm = 0.049020` (about the reference): Δα = −2.522e-3, Δδe = +1.7534e-2 — 10 % from the
deck. *Read at prototype time as elasticity; corrected while gating (§9): the 10 % is the
surge-inertia relief, and with `ΔCm = T·(z_cg − z_T)/(qSc) = 0.044118` (about the CG) the
rigid solve reproduces the deck to 1e-3; the stiffened copy to 1e-6.* SC1's CMY = −0.012022
is the CG 0.05 aft of the reference (98.1 × 0.05 / 408), and SC2 adds exactly −0.044118:
the aero balances the thrust moment about the CG, as it must in free flight.

Torque on the lateral deck, Q = 35 (`CMX_applied = 0.010723`): restrained
`C_lδa = 0.301626, C_nδa = 0.015358, C_lδr = −0.055411, C_nδr = 0.240912` →
**AIL = −0.035139 rad (−2.013°)**, RUD = +0.002240 rad; the solver's trim reproduces the
2 × 2 solve to 1e-8 and total CMX = −0.010723 cancels the applied moment.

## 7. Affected code and docs

**Code.** `solver/sol144.py` (`_TrimState.load_sid/applied_loads`; `_stage_validate_inputs`
resolves the LOAD and refuses GRAV; `_stage_build_downwash_and_reduce` adds `f_struct`;
`_stage_flight_and_net_loads` net = aero + inertial + applied; `_stage_monitor_outputs`
and `_pack_trim_result` pass it on); `results/results.py` (`Sol144TrimResult.applied_loads`,
`.load_sid`; `MonitorLoad.applied`; `SectionCutStation.applied`);
`results/monitor_points.py`, `results/section_cuts.py` (`applied_loads` gathered like
`inertial_loads`); `results/f06_writer.py` (APPLIED block, `+ APPLIED` source text);
`results/load_export.py` (`Fz_applied`, `c*_applied`, maneuver-loads header text);
`solver/maneuver_qs.py`, `solver/maneuver_modal.py`, `main.py` (D1 refusals);
`viewer/results_view.py` (applied column in the split tables).

**Docs.** `05c_sol144_maneuver.md` (governing-equation box, Step 53 net-load/closure text,
new V-THR subsection, monitor/section columns), `09_conventions.md` §9/§10, `02_card_reference.md`
(`LOAD`/`FORCE`/`MOMENT`/`GRAV`/`SUPORT`/`MONPNT3`/`MONSECT`), `10_export_schemas.md`,
`00_program_overview.md` (Known limitations, VAL2 rows, project structure), theory `01` §5.3/§7.3
and `02` §7.1/§7.2/§8, `11_python_api.md`, `06_viewer.md`, README, CHANGELOG, `40_history/06`
+ `00_completed_development.md`, `00_backlog.md` decision map, `00_INDEX.md`.

## 8. Resolved questions

| Question | Resolution |
|---|---|
| Does the applied load participate in inertia relief? | Through the labels only (§2.2); no new rule, no new card |
| What does `maneuver_closure` mean? | Resultant of the full net load (aero + inertial + applied); ≈ 0 in SUPORT directions, −reaction elsewhere |
| GRAV in a trim LOAD set? | Refused (D2) |
| Follower thrust? | No — body-fixed basic frame (D3) |
| Do derivatives / intercepts change? | No (D4); the load gets its own f06 resultant |
| Transient carry-through? | Out of scope; the silent drop becomes a refusal; follow-on issue filed (D1) |
| Propeller handedness | Decided (D6); torque gate G8 pins the sign; swirl rule documented, ungated |
| Flagship powered driver? | Not shipped; the flagship bulk is unchanged. The recipe (FORCE + MOMENT at the engine-mount grid, or a thrust-line grid on an RBAR) is in `05c` |
| `URDD1` as a free label | Already supported by `build_inertial_cols`; first exercised here (`SUPORT 135`) |

## 9. Implementation decisions (2026-10-24, at close)

1. **Thrust moment about the CG, not the reference, when surge is free.** The prototype's
   "10 % elastic" gap (§6) was the surge-inertia relief: with `URDD1` free the thrust
   accelerates the aircraft at `T/m`, the inertia relief `−M·a` acts at the CG (0.05 below the
   reference on the deck), and its pitching moment `T·(z_ref − z_cg) = 2` opposes the thrust
   moment about the reference (20). The trim therefore balances `T·(z_cg − z_T) = 18` — the
   thrust moment **about the CG**, the textbook statement. With `SUPORT 35` / `SPC 1246` the
   x-component is reacted at the SPC grid and the trim balances the moment about that point
   (20). G2 gates both on stiffened copies (1e-6); the shipped flexible deck is within 1e-3 of
   the rigid number, so the spine's flexibility is a 1e-3 effect, not 10 %. The two recipes are
   documented in `05c` as different problems with different answers, not as a discrepancy.
2. **G4's "identical ANGLEA/ELEV on the 35 variant" was wrong** for the same reason and is
   replaced by the 20/18 ratio and the Schur identity on that variant.
3. **GRAV detection** walks one level: the direct SID and the components of a `LOAD` card
   (nested `LOAD` cards are not a thing in `assemble_load_vector`).
4. **f06 reference point** for the applied-load resultant is the RCSID origin (basic origin
   when `RCSID = 0`) through `grid_resultant`, the same point the moment coefficients and
   `maneuver_closure` use; `results/` imports it locally to avoid a `results ↔ solver` cycle.
5. **Schema:** `Fz_applied` after `Fz_react`; `c*_applied` after the `_react` block; the
   transient CSVs carry them as zeros through the shared column blocks (a transient cannot
   select a `LOAD`). `maneuver_loads.bdf` names the `LOAD` set in its header only when one was
   applied, so every other deck's header is byte-identical.
6. **Bit-identity verified** on all 13 shipped SOL 144 driver decks (single-threaded BLAS,
   before/after): only time stamps, the new zero columns, and the #49 round-off noise
   (max |Δ| 7e-10 on O(1e4) values; noise-driven envelope sample indices) differ.
7. **Deck geometry:** the horizontal tail sits at z = 0.5 so its collocation points are
   clear of the wing's wake filaments (an in-plane tail 0.025 from a trailing leg is a
   near-singular VLM configuration, not a physics point).
8. **Follow-on filed as [#50](https://github.com/Sean074/sbeam/issues/50):** constant applied load carried through the MLOADS transient (the IC
   trim takes it, the time history keeps it, transient monitors gain the column).
