# CBAR force and stress output in the NASTRAN layout — design note for issue #21

**Status:** ✅ **agreed 2026-10-02** (CLAUDE.md rule 1): D3 NASTRAN stress layout, D2 field renames and D4 pre-1.0 MINOR breaking change all accepted as recommended. ✅ **Implemented 2026-10-24** (#21, DEF-M18); implementation decisions in §7.
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1).
- **Tier M:** behaviour change to existing outputs. No new card and no new physics.
- **Issue:** [#21](https://github.com/Sean074/sbeam/issues/21) (DEF-M18):
  - f06 plane labels are inconsistent and half-swapped against MSC;
  - the end-A moment face is unstated;
  - plus the stress-layout question deferred to it by the #37 note (D3).
- **Sequencing (agreed):** #20 → #37 → **#21**.
- **Builds on:** the #37 helper `bar_internal_resultants`, which gives positive-face internal
  resultants at both ends ([`cbar_stress_recovery_sign.md`](cbar_stress_recovery_sign.md) D1).

---

## 1. The defect

**Force recovery.** `recover_bar_forces` (`solver/sol101.py:105`) fills `BarForce` with raw
element-frame `K·u` components. `09_conventions.md` §9 flags it ⚠ twice:

- `shear1/shear2/axial/torque` are end-B nodal values, i.e. positive-face internal resultants.
  These are correct and NASTRAN-consistent.
- `bm1_a = My_A`, `bm2_a = Mz_A`, `bm1_b = My_B`, `bm2_b = Mz_B` are **raw nodal moments**.
  - The plane numbering is swapped against the shears and against NASTRAN:
    `BENDING-1` is My, which is NASTRAN plane **2**.
  - The face is never stated: end A is the negated internal moment, end B is the internal
    moment.

**Mapping to the NASTRAN convention.** NASTRAN-95 `mis/sbar2.f:92-131` (NOSA 1.3, convention
reference only; MSC uses the same layout). Plane 1 = element x–y, plane 2 = x–z.

| NASTRAN column | Definition (end-A nodal forces `f`) | sbeam today | Change |
|---|---|---|---|
| BEND-MOMENT END-A PLANE 1 | `M1A = −f[5]` = positive-face `Mz(0)` | `bm2_a = +f[5]` | relabel **and negate** |
| BEND-MOMENT END-A PLANE 2 | `M2A = +f[4]` = −(positive-face `My(0)`) | `bm1_a = +f[4]` | relabel |
| BEND-MOMENT END-B PLANE 1 | `M1B = M1A − V1·L` = `+f[11]` | `bm2_b = +f[11]` | relabel |
| BEND-MOMENT END-B PLANE 2 | `M2B = M2A − V2·L` = `−f[10]` | `bm1_b = +f[10]` | relabel **and negate** |
| SHEAR PLANE 1 / 2 | `V1 = −f[1] = f[7]`, `V2 = −f[2] = f[8]` | `shear1/shear2 = f[7]/f[8]` | none |
| AXIAL FORCE | `−f[0] = f[6]` (tension +) | `axial = f[6]` | none |
| TORQUE | `−f[3] = f[9]` | `torque = f[9]` | none |

The NASTRAN plane-2 moment is the *negated* positive-face `My`. That is the deliberate
symmetry of the convention: rotation about +y bends the x–z plane with the opposite handedness
to rotation about +z in x–y. Defined this way, **M1 and M2 are both positive when they put the
+y / +z fibres in compression**, `σ_bend = −M1·y/I1 − M2·z/I2`.

On a cantilever with +Py, +Pz at the tip: `M1(x) = Py(L−x)` and `M2(x) = Pz(L−x)`, both
positive.

**Stress layout** (deferred here by #37 D3):
- **sbeam:** prints `AXIAL | PT | SA(END-A) | SB(END-B)` with one row per *non-zero*
  recovery point, and `SA/SB` = **total** stress.
- **NASTRAN** (header `demoout/d01101a.out:377`, `mis/ofp1a.f:534`; MSC identical), per
  element:
  - row 1: `SA1 SA2 SA3 SA4 | AXIAL | SA-MAX SA-MIN | M.S.-T`;
  - row 2: `SB1…SB4 | (blank) | SB-MAX SB-MIN | M.S.-C`.
  - `SAi` are **bending-only** at C, D, E, F (all four, zero coordinates printing 0.0).
  - `SA-MAX/MIN = AXIAL + max/min(SA1…4)` (`sbar2.f:214`).

An MSC-trained reader adds AXIAL to sbeam's SA a second time.

## 2. Decisions for agreement

**D1. Adopt the NASTRAN/MSC force convention and layout exactly.**
- **Values:** come from the #37 helper: `M1 = Mz⁺`, `M2 = −My⁺` (⁺ = positive face) at each
  end; `V1 = Vy⁺`, `V2 = Vz⁺`, `AXIAL = P`, `TORQUE = T`.
- **f06 block:** the NASTRAN two-line header and column order: BEND-MOMENT END-A (P1, P2),
  END-B (P1, P2), SHEAR (P1, P2), AXIAL FORCE, TORQUE.
- **The issue's convention checkbox** resolves to the internal moment on the face, MSC-consistent.
  Raw nodal values are no longer reported anywhere.

**D2. Rename the `BarForce` fields, don't redefine them.**
- **New fields:** `m1_a, m2_a, m1_b, m2_b, v1, v2, axial, torque`, with docstrings stating
  face and sign.
- **Why rename:** `bm1_a` today means My. Redefining the same name to mean the plane-1 (Mz)
  moment would leave every existing reader silently wrong. Renaming makes every consumer fail
  loudly and get touched.
- **Consumers swept** (2026-10-02):
  - code: the f06 writer (`:102-121`), the viewer (`results_view.py:116-130`);
  - tests: `test_maneuver_loads.py`, `test_maneuver_reapply.py`, `test_step50_qaa.py`,
    `test_sol101_recovery.py`, `test_maneuver_modal.py`, `test_f06_column_alignment.py`;
  - no CSV and no `sbeam_tools` consumer exists.
- `shear1/shear2` are renamed to `v1/v2` for consistency.

**D3. Adopt the NASTRAN/MSC stress layout** (#37 D3, option a).
- **`BarStress` fields:** `sa[4]`, `sb[4]` bending-only at C, D, E, F; `axial`; `sa_max`,
  `sa_min`, `sb_max`, `sb_min`.
- **f06:** the two-row-per-element NASTRAN block. All four points print, as NASTRAN does
  (a point at (0, 0) prints 0.0 bending).
- **Margins:** `M.S.-T/M.S.-C` are left blank. sbeam has no allowables (MAT1 ST/SC are not
  parsed), so the columns are reserved, not computed.
- **Viewer:** the stress table follows the same columns.
- **Alternative (b):** keep total stress and document it. Rejected: the hand-off reader is
  MSC-trained, and the double-counted axial is exactly the class of silent error this issue
  exists to remove.

**D4. Version policy for an f06 format break.**
- `08_release_process.md` §1 makes a breaking f06 change a **MAJOR** bump, with no pre-1.0
  carve-out. Yet the v1.0.0 milestone is where the "interface-stability promise on
  BDF/case-control/f06" is made.
- **Proposal:** record this under `CHANGELOG.md` **Breaking changes** in 0.3.0, without a
  major bump (SemVer §4: 0.y.z makes no stability promise). Add one clarifying sentence to
  `08_release_process.md` §1: before 1.0.0, breaking f06/BDF changes ship in a MINOR release
  and are listed under Breaking changes.

**D5. Docs and figure.**
- `03_static_analysis.md`: rewrite the force and stress sections and the f06 block
  descriptions.
- `09_conventions.md` §9: replace both ⚠ caveats with the positive-face/NASTRAN-plane
  statement and the cantilever anchor.
- `sign_conventions_internal_loads.svg`: remove the "SWAPPED" caveat line and show M1/M2
  plane signs.
- `04_modal_analysis.md` and `05c_sol144_maneuver.md`: only if they quote column names.

**D6. Scope fences.**
- No CSV export of bar forces is added. #31 owns exported schemas, and there is no consumer.
- No allowables or margins (D3).
- Element-interface work belongs to #38.
- The force block keeps the NASTRAN columns for the maneuver critical-sample f06 too
  (`f06_writer.py:1065`), with the same writer.

## 3. Conventions cited

- `09_conventions.md` §9: section-cut sign = CBAR end-B sign (positive face). The #37 helper
  extends that to end A. This note maps it onto NASTRAN plane numbering.
- Element frame `e_x = GB−GA`, `e_y` from the orientation vector, `e_z = e_x × e_y`
  (`assembly/stiffness.py:99-122`). Plane 1 = x–y (I1), plane 2 = x–z (I2), per the #37 D5
  card-reference fix.

## 4. Validation (benchmark-first, rule 2)

**Reference case:** `val_cantilever_static` geometry (10 × 1 m, A = 0.1, I1 = I2 = 8.333e-4,
C = (+0.15811, +0.15811), D = (−, +), E = (−, −), F = (+, −)), tip loads Py = +1000,
Pz = +2000, Px = +5000. Values come from the prototype run of the production code
(2026-10-02).

| Gate | Check | Expected | Tolerance |
|---|---|---|---|
| **G1** force closed form | el 5 (x = 4 → 5) | M1A = 6000, M2A = 12000, M1B = 5000, M2B = 10000, V1 = 1000, V2 = 2000, AXIAL = 5000, TORQUE = 0. Closed form `M1 = Py(L−x)`, `M2 = Pz(L−x)` | 1e-9 rel |
| **G2** sign anchors | Py only; Pz only | M1 > 0 and M2 = 0; M2 > 0 and M1 = 0. Root plane moment = +PL | exact sign |
| **G3** continuity | every shared node, collinear mesh | M1B(e) = M1A(e+1), M2B(e) = M2A(e+1); V and axial constant | 1e-9 rel |
| **G4** stress closed form | el 6 end A (x = 5) | SA1(C) = −2.846094e6, SA2(D) = −9.48698e5, SA3(E) = +2.846094e6, SA4(F) = +9.48698e5, AXIAL = 5.0e4, SA-MAX = 2.896094e6, SA-MIN = −2.796094e6 | 1e-6 rel |
| **G5** stress/force consistency | every element and end | `SAi = −M1·yᵢ/I1 − M2·zᵢ/I2` from the *printed* force-table values | 1e-12 rel |
| **G6** f06 layout | header lines and column positions | exact NASTRAN header text and order for both blocks; `test_f06_column_alignment.py` updated to the new headers | exact |
| **G7** no-legacy invariant | `BarForce`/`BarStress` field sets | old names (`bm1_a`…, `shear1`, `sa`…`sb_f`) absent; a grep gate in tests | exact |

These are values the fixed recovery must reproduce; the prototype is not committed.

## 5. Affected code and docs (Tier M closure)

**Code:**
- `solver/sol101.py`: `recover_bar_forces` and `recover_bar_stresses` through the #37 helper.
- `results/results.py`: `BarForce`, `BarStress`.
- `results/f06_writer.py`: both blocks and the stress-point table.
- `viewer/results_view.py`: both tables.

**Tests:** the six listed in D2, plus G1–G7.

**Docs:** D5, `CHANGELOG.md` (Breaking changes + Fixed), the `docs/40_history/` resolved
line (DEF-M18), and `08_release_process.md` §1 (D4).

## 6. Resolved questions (2026-10-02)

1. **D3:** adopt the NASTRAN stress layout (bending-only SA1–4 + SA-MAX/MIN), as recommended.
2. **D2:** rename the `BarForce`/`BarStress` fields, as recommended.
3. **D4:** ship as a pre-1.0 MINOR breaking change, with the `08_release_process.md` §1
   clarification landing in the implementation commit, as recommended.

## 7. Implementation decisions (2026-10-24)

1. **`BarStress` uses scalar fields `sa1…sa4`, `sb1…sb4`** (the NASTRAN column names), not
   two 4-tuples as §2 D3 sketched: a flat dataclass keeps the f06 writer, the viewer table and
   the gates one attribute per cell, and the G7 legacy-name check stays a set comparison.
2. **One mapping function.** `_bar_force_from_internal(eid, BarInternal) -> BarForce` applies
   `M1 = +mz`, `M2 = −my` once; `recover_bar_forces` and `recover_bar_stresses` both call it,
   and the stress uses `_bending_stress(m1, m2, y, z, I1, I2) = −M1·y/I1 − M2·z/I2` on the
   `BarForce` values. G5 (stress/force consistency from the printed moments) is therefore
   true by construction, and asserted anyway at 1e-12.
3. **All four points always evaluated**, including (0, 0) ones, so `SA-MAX/MIN` are bounded
   by 0.0 bending exactly as NASTRAN-95 prints them (`demoout/d01101a.out:377`, where SA1 = 0.0
   for an undefined C point and SA-MAX picks it up). The old "omit zero points" f06 rule is
   gone.
4. **f06 headers.** The group labels on force-block line 1 (`BEND-MOMENT END-A`, `- SHEAR -`)
   are centred over two `_FIELD_W` cells by hand because `_hdr` truncates to one cell; every
   per-column label (`PLANE 1`, `FORCE`, `SA1`, …) is on `_hdr`, and the DEF-M13 alignment
   gate's label set was moved to the new names so it keeps checking both blocks.
   `M.S.-T`/`M.S.-C` are header-only.
5. **End-A stress non-regression is now 1e-14 relative, not bit-identical** (`#37` G5 and the
   SOL 144 twin): the total is formed as `axial + bending` instead of accumulating from `P/A`,
   so the last bit can move. The G6 jump gate on HA144A is taken on the totals.
6. **Sign flip in two existing gates.** V21 / `test_pin_releases` asserted the root moment as
   `bm2_a = −P·L` (raw nodal); the +x-face `M1A` is `+P·L`. Reactions are unchanged.
7. **Measured reference values** (production code, 2026-10-24) match §4 to the printed digits:
   el 5 `M1A = 6000`, `M2A = 12000`, `M1B = 5000`, `M2B = 10000`; el 6 end A `SA1 = −2.846094e6`,
   `SA2 = −9.48698e5`, `SA3 = +2.846094e6`, `SA4 = +9.48698e5`, `AXIAL = 5.0e4`,
   `SA-MAX = 2.896094e6`, `SA-MIN = −2.796094e6`.
8. **Not done here (D6):** no CSV export of bar forces (#31), no margins, no element interface
   (#38). The `08_release_process.md` §1 pre-1.0 sentence landed in this commit (D4).
