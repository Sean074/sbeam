# CBAR stress recovery from face-consistent internal moments — design note for issue #37

**Status:** ✅ **agreed 2026-10-02** (CLAUDE.md rule 1): D3 defer SA layout to #21, D1 direct end-B moments with G4 gate and sequencing #20 → #37 → #21 all accepted as recommended; not yet implemented.
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1).
- **Tier M:** behaviour change to an existing output. No new card and no new physics.
- **Issue:** [#37](https://github.com/Sean074/sbeam/issues/37) (DEF-M21): the end-B bending
  stress sign is flipped, and the PBAR I1/I2 plane is mislabelled in the card reference.
- **Neighbours:**
  - [#20](https://github.com/Sean074/sbeam/issues/20) (pin-release condensation, agreed note
    [`cbar_pin_release_condensation.md`](cbar_pin_release_condensation.md)) rewrites the same
    `_element_local_forces` input. Land #20 first.
  - [#21](https://github.com/Sean074/sbeam/issues/21) (DEF-M18, `BarForce`/f06 plane labels
    and the end-A face) reuses the helper introduced here. #21 lands after #37, as a separate
    commit.

---

## 1. The defect

`recover_bar_stresses` (`solver/sol101.py:143`) applies one formula,
`σ = P/A + Mz·y/I1 − My·z/I2` (`_stress_at_point`, `sol101.py:128`), to the **raw nodal**
end moments of `f_local = K·u` at *both* ends:
- at end A it uses `f[5]`, `f[4]`;
- at end B it uses `f[11]`, `f[10]`.

At end A the nodal moment is the negative of the internal moment on the positive face, so the
formula is right there. At end B the nodal moment *is* the positive-face internal moment, so
the bending term has the wrong sign.

The single function serves SOL 101, both SOL 144 paths (`sol144.py:753`,
`sol144_static.py:283`) and therefore every CBAR stress in f06 and the viewer. MLOADS does not
recover stresses (`maneuver_qs.py` calls only `recover_bar_forces`).

**Reproduction** (`release/0.3.0` @ `4964788`):
- **Deck:** `sample/val_cantilever_static.bdf` (10 × 1 m, A = 0.1, I1 = I2 = 8.333e-4,
  C = (+0.158, +0.158), E = (−0.158, −0.158)).
- **Tip loads:** Py = +1000, Pz = +2000, Px = +5000 (tension).
- **Closed form:** `σ(x) = Px/A − Py(L−x)·y/I1 − Pz(L−x)·z/I2`.

| Location | Point | sbeam today | Closed form |
|---|---|---|---|
| el 1 end A, x = 0 | C / E | −5.642188e6 / +5.742188e6 | −5.642188e6 / +5.742188e6 ✓ |
| el 5 end B, x = 5 | C / E | **+2.896094e6 / −2.796094e6** | −2.796094e6 / +2.896094e6 |
| el 6 end A, x = 5 | C / E | −2.796094e6 / +2.896094e6 | −2.796094e6 / +2.896094e6 ✓ |
| el 9 end B, x = 9 | C / E | **+6.192188e5 / −5.192188e5** | −5.192188e5 / +6.192188e5 |

End A matches in both planes and with axial load. End B has the bending term negated and the
axial term correct, so its values are not simply sign-flipped: `P/A − σ_bend` instead of
`P/A + σ_bend`. The same fibre at the same section (el 5 end B against el 6 end A) disagrees.

**Why nothing caught it:**
- `test_sol101_recovery.py:113-126` checks |σ_A| and |σ_B| < |σ_A| (magnitudes only).
- The cantilever gates have zero moment at the free end B.
- The combined-loading test (`:162`) checks end B where M = 0.

**The doc defect:** `02_card_reference.md:221-222` says I1 is "about element y-axis
(bending in XZ plane)" and I2 "about element z-axis (bending in XY plane)". The code
(`assembly/stiffness.py:31-33`) correctly uses **I1 for bending in the element x–y plane**
(v, θz; about local z). NASTRAN agrees: plane 1 is x–y, containing the orientation vector. The
docs are wrong and the code is right.

## 2. Theory and the NASTRAN-95 reference

Let `f = K·u` be the element-frame nodal force 12-vector (on the element, at the nodes). Take
the internal resultants on the **positive (+x) face** at station x: the force that the part
beyond x exerts. That is the outboard-resultant sign sbeam's section cuts already use
(`09_conventions.md` §9: "MONSECT/section-cut sign = the CBAR end-B sign"):

```
end A (x = 0):  P = −f[0]   Vy = −f[1]   Vz = −f[2]   T = −f[3]   My = −f[4]    Mz = −f[5]
end B (x = L):  P = +f[6]   Vy = +f[7]   Vz = +f[8]   T = +f[9]   My = +f[10]   Mz = +f[11]
```

With no element loads, equilibrium gives `Mz(L) = Mz(0) − Vy·L` and `My(L) = My(0) + Vz·L`.

The Euler–Bernoulli fibre stress (no I12; sbeam has none) is:

```
σ(y, z) = P/A − Mz·y/I1 + My·z/I2
```

**NASTRAN-95** (`mis/sbar2.f:92-175`; NOSA 1.3, convention reference only), with end-A forces
`FA`:
- `M1A = −FA(6)`, `M2A = +FA(5)`, `V1 = −FA(2)`, `M1B = M1A − V1·L`.
- `σ = −M1·y/I1 − M2·z/I2` at both ends.
- Its plane-1 moment is the positive-face `Mz` above. Its plane-2 moment is the *negated*
  positive-face `My` (the NASTRAN plane-2 sign). Both give exactly the σ formula above.
- `SA1…SA4` are **bending only**. `AXIAL` is printed separately, and `SA-MAX/SA-MIN = AXIAL
  + max/min(SA1…4)` (`sbar2.f:214`; header `demoout/d01101a.out:377`).

## 3. Decisions for agreement

**D1. One internal-resultant helper.** Add `bar_internal_resultants(f_local, L) ->
BarInternal`:
- positive-face P, Vy, Vz, T, and My/Mz at both ends, per §2;
- it lives next to `_element_local_forces` and is the only place nodal-to-internal sign
  conversion happens;
- `recover_bar_stresses` consumes it;
- #21 will make `recover_bar_forces` consume it too, which is how that issue's end-A face
  decision lands.

End-B moments are taken **directly** from `f[10]`, `f[11]`, not by equilibrium from end A.
They are identical without element loads, and taking them directly needs no L-dependent
reconstruction. A gate (G4) asserts the equilibrium identity, so the day PLOAD1 adds element
loads, the helper is visibly incomplete instead of silently wrong.

**D2. One stress formula at both ends:** `σ = P/A − Mz·y/I1 + My·z/I2` on the D1 resultants.
- **End A:** bit-identical to today.
- **End B:** the bending term changes sign.
- `_stress_at_point` takes internal moments and its docstring states the face.

**D3. SA/SB semantics stay "total stress" (axial + bending) in #37; NASTRAN layout alignment
is deferred to #21.**
- sbeam's `SA/SB` include P/A. NASTRAN's `SA1–4` are bending-only, with `SA-MAX/MIN` carrying
  the total.
- Changing that is an output-schema change: f06 columns, `BarStress` fields, viewer table. It
  belongs with #21's f06 plane and label work, not in a sign fix.
- #37 documents the current semantics explicitly in `03_static_analysis.md` and §9, and adds
  the layout question to #21's body.
- **Alternative:** switch now. Rejected because it mixes a correctness fix with a schema
  change and doubles the diff.

**D4. `BarForce` is not touched in #37.** `bm1_a/bm2_a/bm1_b/bm2_b` stay raw nodal values
with their current (wrong-plane) labels until #21. The interim state is documented in
`09_conventions.md` §9:
- stress is face-consistent;
- the force-table moments are still raw.

That is the existing ⚠ caveat narrowed, not a new inconsistency. #21 is sequenced directly
after.

**D5. Doc corrections in the same commit.**
- `02_card_reference.md` PBAR: I1 is "area moment of inertia for bending in the element x–y
  plane (plane 1; about local z)"; I2 is "bending in the x–z plane (plane 2; about local y)".
- `03_static_analysis.md` "CBAR Stress at Recovery Points": the new formula, the face
  statement, and the SA/SB = total-stress statement.
- `09_conventions.md` §9: a new bullet on internal-resultant faces and the stress sign.
- The `sign_conventions_internal_loads.svg` caveat text if it mentions stress.

**D6. Sweep (rule 3).** Every nodal-to-internal conversion in the codebase was checked
(2026-10-02 grep of `bm*_a/b`, `f_local[4|5|10|11]`):
- **Stress:** only `recover_bar_stresses`, which is fixed here.
- **Force table:** `recover_bar_forces`, f06 `:119` and viewer `:126-129` consume raw
  `BarForce`. That is #21 (D4).
- **Section cuts and monitor points:** free-body sums of grid loads, not affected.
- **Viewer diagrams:** plot section-cut values, not affected.

No other occurrence exists. The invariant gate G3 prevents regression.

## 4. Conventions cited

- `09_conventions.md` §9: section-cut sign = the CBAR end-B sign (the positive-face,
  outboard-resultant convention). D1 extends exactly that convention to end A.
- Element local frame `e_x = GB−GA`, `e_y` from the orientation vector, `e_z = e_x × e_y`
  (`assembly/stiffness.py:99-122`). Recovery points (C…F) are (y, z) in that frame
  (`02_card_reference.md` PBAR).
- I1 ↔ x–y plane (about z) and I2 ↔ x–z plane (about y): code `assembly/stiffness.py:31-33`,
  NASTRAN plane 1/2.

## 5. Validation (benchmark-first, rule 2)

| Gate | Configuration | Expected | Tolerance |
|---|---|---|---|
| **G1** two-plane closed form | `val_cantilever_static` geometry, tip Py = +1000, Pz = +2000, Px = +5000; points C and E | `σ = Px/A − Py(L−x)y/I1 − Pz(L−x)z/I2` at both ends of el 1, 5, 6, 9 (the §1 table "closed form" column, e.g. el 5 end B C = −2.796094e6) | 1e-9 rel |
| **G2** sign anchors | single-plane loads (Py only; Pz only) | +Py → compression at +y fibres; +Pz → compression at +z fibres; signs asserted, not abs | exact sign |
| **G3** continuity invariant | collinear same-section mesh, both planes, axial + bending | σ(end B of e) = σ(end A of e+1) at every shared node and every recovery point | 1e-9 rel |
| **G4** equilibrium identity | any element, no element loads | helper end-B Mz/My equal `Mz(0) − Vy·L` / `My(0) + Vz·L` | 1e-12 rel |
| **G5** end-A non-regression | all existing decks | end-A stresses bit-identical; only end-B values change | exact |
| **G6** SOL 144 path | HA144A trim | stress continuity (G3) holds on the trimmed wing; end-A unchanged | 1e-9 rel |

Existing tests: `test_sol101_recovery.py:113-126` gets signed assertions (G2). Nothing else
pins an end-B stress value, so no expectation inverts.

## 6. Prototype

A scratch run of the production code with the G1 loads (not committed) produced the §1 table.
The closed-form column is the G1 expectation.

## 7. Affected code and docs (Tier M closure)

**Code:**
- `solver/sol101.py`: `bar_internal_resultants` helper, `_stress_at_point` on internal
  moments, `recover_bar_stresses` through the helper.

**Tests:**
- `tests/solver/test_sol101_recovery.py`: G1–G4.
- An HA144A G6 check in `tests/aero/`.

**Docs:** per D5, plus `CHANGELOG.md` (Fixed) and the `docs/40_history/` resolved-defects line
(DEF-M21). #21's body gains the D3 layout question.

## 8. Resolved questions (2026-10-02)

1. **D3:** SA/SB stay total stress in #37. NASTRAN's bending-only SA1–4 + SA-MAX/MIN layout is
   deferred to #21, as recommended. The question was added to #21 the same day.
2. **D1:** end-B moments are taken directly from `f[10]`, `f[11]`, with the G4 equilibrium
   gate, as recommended.
3. **Sequencing:** #20 → #37 → #21, as recommended.
