# CBAR pin releases by static condensation — design note for issue #20

**Status:** ✅ **agreed 2026-10-02** (CLAUDE.md rule 1): D3 congruent mass, D5 validation error and G2 in both planes all accepted as recommended; not yet implemented.
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1).
- **Tier M:** behaviour change to an existing capability. No new card and no new physics:
  the release semantics are standard NASTRAN.
- **Issue:** [#20](https://github.com/Sean074/sbeam/issues/20) (DEF-M17, re-scoped
  2026-10-02).
- **Related:**
  - [#37](https://github.com/Sean074/sbeam/issues/37) (DEF-M21, end-B stress sign) and
    [#21](https://github.com/Sean074/sbeam/issues/21) (DEF-M18, plane labels) touch the same
    recovery function, but stay separate commits.
  - [#38](https://github.com/Sean074/sbeam/issues/38) (CROD) builds its element interface on
    the helper introduced here.

---

## 1. The defect

`apply_pin_releases` (`assembly/stiffness.py:126`) **zeroes** the released rows and columns
of the 12×12 local K. That is not a release. The coupling of the released DOF into the
retained DOFs is discarded instead of condensed, so every pin-flagged element is over-stiff.

Separately, recovery (`solver/sol101.py:73` `_element_local_forces`) uses the unreleased
`local_stiffness`. Its forces are therefore inconsistent with the solved displacements, and
released end forces are non-zero. This is the original #20 finding.

Measured on `release/0.3.0` @ `4964788` with the prototype in §6. All cases use
E = 2e11, A = 0.1, I = 8.333e-4, ρ = 7850.

| Case | Closed form | sbeam today | Error |
|---|---|---|---|
| Fixed–pinned single element (`PB=6`, L = 1, Fy = 1000): tip deflection | PL³/3EI = 2.000080e-6 | 5.000200e-7 | 4× too stiff |
| Same: root moment / end-B moment | −1000 / 0 | −500 / −500 | — |
| Clamped–clamped grid ends, last of 20 elements `PB=56`, L = 10: f₁ | clamped–pinned 11.30667 Hz | **16.40710 Hz** (clamped–clamped) | the pin does nothing |
| Truss test (`test_pin_releases.py:184`) with I1 = I2 = 8.333e-4 instead of 0 | −P√2/EA = −1.414214e-10 | −1.285653e-10 | 9.1 % stiff |

**Why nothing caught it:**
- The existing truss gate sets **I1 = I2 = J = 0**. With no bending stiffness there is
  nothing to condense, so it passes.
- `test_pa_pb_456_transverse_shear_survives` (`test_pin_releases.py:135`) asserts the wrong
  behaviour.
- `03_static_analysis.md:150` says a `PA=PB=456` member "transmits axial and transverse
  shear". A pinned truss member transmits axial force only.

**Blast radius:** wrong displacements, modes, trim and load paths on every deck with PA/PB:
SOL 101, 103, 144 and MLOADS. No `sample/` or `tests/` deck uses pin flags (checked
2026-10-02 by parsing every deck), so no shipped result changes.

## 2. Theory

A released DOF *i* carries no force: `f_i = 0`. Write the element equations in partitioned
form, with *r* the retained DOFs and *c* the released ones:

```
[K_rr  K_rc] {u_r}   {f_r}
[K_cr  K_cc] {u_c} = { 0 }   ⇒   u_c = −K_cc⁻¹ K_cr u_r
```

Substituting gives the condensed stiffness `K' = K_rr − K_rc K_cc⁻¹ K_cr`. This is the Schur
complement, i.e. Guyan reduction at element level, which is exact for statics.

Equivalently, with the transformation `T` (identity on *r*, `u_c = −K_cc⁻¹K_cr u_r`):

- **Stiffness:** `K' = Tᵀ K T`.
- **Mass, congruent:** `M' = Tᵀ M T`. The released DOF follows the static deflected shape.
- **Recovery:** `f = K' u`. Released rows of K' are zero, so released end forces are
  **exactly zero by construction**.

**NASTRAN-95 reference** (NOSA 1.3; algorithm reference only, no code reuse):
- `mis/kbar.f:401-438`: stiffness, condensing one released DOF at a time:
  `K ← K − K[:,i]·K[i,:]/K[i,i]`, then zero row/column *i*. If `K[i,i] = 0` it only zeroes.
- `mis/bard.f:690-735`: the **same congruent mass condensation**:
  `M − K_li M_ij/K_ii − K_ij M_li/K_ii + K_li K_ij M_ii/K_ii²`, which is Tᵀ M T one DOF at a
  time.
- `mis/sbar1.f:325-376` and `sbar2.f:92-131`: recovery from the same condensed K.

Sequential single-DOF condensation equals block condensation (successive Schur complements),
so the result does not depend on release order.

**Invariants** (verified by the prototype on 121 release combinations):
- `K'·R = 0` for the six rigid-body modes R. Condensation never adds rigid-body strain energy;
  residual 0 to machine precision.
- `Rᵀ M' R = Rᵀ M R`. The element's rigid-body mass properties (mass, CG, inertia, i.e.
  GPWG) are unchanged, **except** when the same translational or torsional DOF is released at
  both ends (§3, D5).

## 3. Decisions for agreement

**D1. Condense, don't zero.** Use static condensation in element local axes, before the
local→global transform. sbeam has no offsets, so the order question that NASTRAN handles
around WA/WB does not arise. Implement it as successive single-DOF condensation (the
NASTRAN-95 form, simple and order-independent) inside one helper.

**D2. One source for assembly and every recovery path.** Add a single helper, e.g.
`released_local_matrices(pbar, mat1, L, pa, pb) -> (K', M')` in `assembly/`.

- **Assembly** (`element_stiffness_global`, `element_mass_global`) and **recovery**
  (`_element_local_forces`) both call it. `_element_local_forces` serves SOL 101, both SOL 144
  paths and MLOADS.
- `apply_pin_releases` is deleted rather than left as a trap.
- This sweeps the defect class (rule 3). After the change, the only call site of the
  unreleased `local_stiffness` is the helper itself; a test asserts this.

**D3. Condense the mass congruently (`M' = TᵀMT`).** This matches NASTRAN-95 `bard.f`. The
prototype shows why it matters on coarse meshes:

| Clamped–pinned f₁ (closed form 11.30667 Hz) | N = 4 elements | N = 20 elements |
|---|---|---|
| Zeroing (today) | 16.42884 (+45 %) | 16.40710 (+45 %) |
| Condensed K, raw M | 11.47135 (+1.46 %) | 11.30800 (+0.012 %) |
| **Condensed K and M (proposed)** | **11.31450 (+0.07 %)** | **11.30668 (+1e-4 %)** |

With raw M, the released end's rotary and coupling mass is attached to the node rotation the
element no longer drives. Stick models are coarse, so that error is not negligible.

- **Alternative:** leave M unchanged. Simpler, but 1.5 % low-order frequency error at 4
  elements per span.
- **Not decided here:** MSC's treatment of consistent CBAR mass under pin flags is not
  confirmed (no MSC reference in hand).
- **Recommended:** congruent, for NASTRAN-95 parity and the better answer.

**D4. Zero-pivot tolerance.** NASTRAN-95 tests `K[i,i] == 0` exactly. sbeam uses a relative
test, `|K_ii| ≤ 1e-12 · max|diag K|`, under which the DOF is only zeroed. This catches zero
section properties (e.g. I1 = 0 or J = 0) without dividing by round-off.

**D5. Releasing the same DOF at both ends is an error for digits 1–4.**
- **Cases:** releasing axial (1), either shear (2, 3) or torsion (4) at both ends leaves the
  element with an **internal mechanism**. The element cannot carry that load, and its rigid
  mass in that direction is undefined. The prototype shows `RᵀM'R ≠ RᵀMR` for exactly these
  19 of 121 combinations.
- **Proposal:** a validation error at parse/validate time naming the element and digit.
- **Allowed:** rotations 5/6 at both ends, which is a two-force link (well-defined, no
  mechanism).
- **Alternative:** a `UserWarning` plus NASTRAN-95's silent behaviour. Rejected: it hides a
  modelling error behind a later singular-matrix failure.

**D6. Scope fences.**
- No element interface is built here; #38 owns that. D2's helper is the seed #38 generalises.
- Sign and face conventions of the recovered forces are **unchanged** here; #37 and #21 own
  them.
- PLOAD1 and thermal loads do not exist, so there are no fixed-end-load condensation terms.
  When PLOAD1 lands (parked), its equivalent nodal loads must be condensed with the same T
  (`f' = Tᵀ f`). That requirement is recorded in its parked entry.

## 4. Conventions cited

- PA/PB digits are in **element local axes** (1 axial, 2/3 local y/z translation,
  4 torsion, 5/6 local y/z rotation): `02_card_reference.md` (PBAR/CBAR), local DOF order
  `[Tx, Ty, Tz, Rx, Ry, Rz]` per `assembly/stiffness.py:23`.
- Internal-load and face conventions (`09_conventions.md` §9) are not touched. A released end
  now reports exactly zero for the released component, under any face convention.

## 5. Validation (benchmark-first, rule 2)

| Gate | Configuration | Expected | Tolerance |
|---|---|---|---|
| **G1** | Single element, clamped at GA, `PB=6`, grid B R3 SPC'd, Fy = 1000 (L = 1, E = 2e11, I = 8.333e-4) | δ = PL³/3EI = 2.000080e-6; SPC moment at A = −1000; recovered end-B bending = 0 | 1e-10 rel; 0 abs at end B |
| **G2** | 20 elements, L = 10, both grid ends clamped, last element `PB=56` (both planes) | f₁ = (3.92660²/2π)√(EI/mL⁴) = 11.30667 Hz (×2, both planes) | 0.01 % |
| **G2b** | Same at N = 4 | 11.31450 Hz (pins the D3 mass choice; raw-M gives 11.47135) | 1e-6 rel (regression value) |
| **G3** | Existing truss test with **I1 = I2 = 8.333e-4, J = 1.406e-3** (not 0) | apex δy = −P√2/EA = −1.414214e-10 | 1e-9 rel |
| **G4** (invariant) | Every PA/PB combination from {∅, 1…6, 45, 46, 56, 456} at each end, excluding D5 errors | K' symmetric, PSD, `K'R = 0`; `RᵀM'R = RᵀMR`; recovered released end forces = 0 for a random u | machine precision |
| **G5** (single source) | Static analysis of the module | the only caller of `local_stiffness`/`local_mass` for CBARs is the helper | exact |
| **G6** | D5 decks: `PA=PB=1`, `2`, `3`, `4` | validation error naming EID and digit | — |
| **Non-regression** | Full suite | Bit-identical everywhere (no shipped deck uses pin flags). Only `test_pin_releases.py` expectations change: the "zeroes row/col" unit tests become condensation tests, and `transverse_shear_survives` is inverted. | — |

## 6. Prototype

Scratch only, not committed: a ~40-line NumPy check using the production `local_stiffness`
and `local_mass`, with sequential condensation as in D1/D3. It produced every number in §1,
§3 and §5. It is reproduced by the G1–G4 tests in the implementation.

## 7. Affected code and docs (Tier M closure)

**Code:**
- `assembly/stiffness.py`: new helper; delete `apply_pin_releases`.
- `assembly/mass_matrix.py`: mass through the helper.
- `solver/sol101.py`: `_element_local_forces` through the helper.
- Validation: D5 check in the CBAR validator.

**Tests:**
- `tests/assembly/test_pin_releases.py`: rewritten around G1–G4 and G6.
- G2/G2b as integration decks in `tests/integration/bdf/`.

**Docs:**
- `03_static_analysis.md` "Pin Releases": rewrite the implementation and truss text.
- `02_card_reference.md:307-309`.
- `04_modal_analysis.md`: one line on the mass treatment.
- `CHANGELOG.md` (Fixed).
- `docs/40_history/` resolved-defects line (DEF-M17).

## 8. Resolved questions (2026-10-02)

1. **D3:** congruent mass condensation `M' = TᵀMT`, as recommended.
2. **D5:** validation error for the same digit 1–4 at both ends, as recommended.
3. **G2:** runs in both bending planes (`PB=56`), as recommended.
