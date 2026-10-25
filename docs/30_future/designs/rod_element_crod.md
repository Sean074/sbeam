# CROD / PROD / CONROD rod element behind a line-element registry — design note for issue #38

**Status:** ✅ **agreed 2026-10-24**, ✅ **implemented 2026-10-24** (CLAUDE.md rule 1): D1 registry,
D3 consistent translational mass without torsional inertia, D4 native CONROD and D8 CSV
deferral all accepted as recommended. Implementation decisions in §9.
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1).
- **Tier L:** new cards, new element physics, and the first per-element interface.
- **Issue:** [#38](https://github.com/Sean074/sbeam/issues/38) (activated from the
  Structural-fidelity route of `02_parked.md`, 2026-10-02).
- **Related:**
  - [#20](https://github.com/Sean074/sbeam/issues/20) (DEF-M17): the released-stiffness helper
    this note's CBAR registry entry wraps.
  - [#37](https://github.com/Sean074/sbeam/issues/37) / [#21](https://github.com/Sean074/sbeam/issues/21):
    the +x-face sign helper and NASTRAN output layout the rod reuses.
  - [#31](https://github.com/Sean074/sbeam/issues/31): owns the element-force CSV schema (D8).
  - [#45](https://github.com/Sean074/sbeam/issues/45): PLOAD1 is out of scope here (D8).

---

## 1. Objective and consumer

Engine pylon struts are pin-ended, triangulated two-force members carrying nacelle mass and
thrust into the wing. Today they are CBARs with `PA=PB=56`, which is a bending element with
its moments condensed away, not a rod: it still needs an orientation vector, still carries
`ρ(I1+I2)` rotary inertia, and prints eight bending columns of zeros. This step adds the
NASTRAN rod (`CROD` + `PROD`, `CONROD` with inline properties): axial `EA/L` and torsion
`GJ/L` only.

The enabler is a **minimal per-element interface**. Assembly (`assemble_global_stiffness`,
`assemble_global_mass`), GPWG, the four recovery loops (SOL 101, SOL 144 trim, SOL 144
static, MLOADS) and both f06 element blocks all iterate `bulk.cbars` directly; CBUSH is a
second hard-coded path. Nothing in `sbeam/` abstracts an element. The rod is the second
line element, so this is the first time the abstraction earns its keep (rule 5: no element
types beyond CBAR and CROD/CONROD are added).

## 2. Theory and the NASTRAN-95 reference

Element axis `n = (GB − GA)/L`. In the element frame with `e_x = n` the rod stiffness is

```
K_local: EA/L on DOFs (0, 6)   [u_A, u_B]
         GJ/L on DOFs (3, 9)   [θx_A, θx_B]
         zero elsewhere
```

so `K_global = Tᵀ K_local T = (EA/L)·n nᵀ` on the translations and `(GJ/L)·n nᵀ` on the
rotations, independent of how `e_y`, `e_z` are chosen in the plane normal to `n`.

Recovery: `f_local = K_local·T·u`; the +x-face resultants are `P = +f[6]` (tension +) and
`T = +f[9]` (right-handed about +x), exactly the CBAR `AXIAL`/`TORQUE` entries. Stresses:
`σ = P/A`, `τ = T·C/J` where `C` is the PROD/CONROD torsional stress coefficient.

**NASTRAN-95 reference** (NOSA 1.3; algorithm reference only, no code copied; sources
`mis/krod.f`, `mis/srod1.f`, `mis/srod2.f` read 2026-10-24):
- `krod.f`: `DSCL = A·E/L`, `DSCR = J·G/L`, `KE = DSCL·N` on translations and `DSCR·N` on
  rotations with `N = n nᵀ`; the off-diagonal partition takes the negative sign.
- `srod1.f`: `SAT = +n·E/L` on `u_A`, `SBT = −n·E/L` on `u_B` with `n` taken **A − B**, so
  `σ = (E/L)·(GB−GA)/L·(u_B − u_A)` is tension-positive; `FJOVRC = C/J`, set to 0 when
  `J = 0`.
- `srod2.f`: `P = AREA·σ`, `TORQUE = (GJ/L)·n·(θ_B − θ_A)`, `TAU = FJOVRC·TORQUE`. Margins
  of safety are printed from MAT1 allowables sbeam does not parse.
- Mass: NASTRAN-95 lumps `(ρA + NSM)·L/2` at each end by default; MSC `COUPMASS` gives the
  consistent translational matrix. Neither carries rod torsional inertia.

**Consistent translational rod mass** (3D truss, Przemieniecki):
`m·L/6·[2 1; 1 2]` on each translation pair (0,6), (1,7), (2,8), `m = ρA + NSM`. Rigid-body
mass is `m·L` exactly; the rotational rows are zero.

## 3. Decisions for agreement

**D1. Element interface = a registry of per-type functions.** New
`sbeam/assembly/elements.py`:
- `LineElement` frozen record: `eid, kind, ga, gb, L, K_local, T` with `K_local` the 12×12
  **released/condensed** local stiffness and `T` the 12×12 local←global transform.
  `global_stiffness()` returns `Tᵀ K_local T`.
- `line_element(elem, bulk) -> LineElement`, dispatching on `type(elem)` through a dict
  `{Cbar, Crod, Conrod}`. `line_element_mass_global(elem, bulk)` and
  `line_element_mass_per_length(elem, bulk)` are the mass side, kept separate so recovery
  (called per MLOADS time step) never builds a mass matrix.
- `iter_line_elements(bulk)` yields CBARs, then CRODs, then CONRODs, each in deck order.
- The CBAR entry calls `released_local_stiffness`, `transform_matrix` and
  `element_mass_global` exactly as today, so a rodless deck is **bit-identical** and the #20
  G5 single-source gate is untouched.
- Model dataclasses stay plain data (no Protocol methods on `Cbar`): the physics stays in
  `assembly/`, and the model→assembly import direction is preserved.
- *Alternative rejected:* a `typing.Protocol` with `local_stiffness()`/`local_mass()` methods on
  the element classes. It moves physics into `sbeam/model/` and churns more for two types.

**D2. Rod frame and stiffness.** `e_x = (GB − GA)/L` (`09_conventions.md` §9 CBAR wording).
`e_y` is a deterministic unit vector ⊥ `e_x`, built from the basic axis least aligned with
`e_x`; `e_z = e_x × e_y`. Because `K_local` is non-zero only on the axial and torsional DOFs,
the global matrix is independent of that choice (gate G5b). Keeping the full 12-DOF frame
lets the rod reuse the scatter, `K·T·u` recovery and `bar_internal_resultants` unchanged.

**D3. Rod mass: consistent translational, no torsional inertia.** `m·L/6·[2 1; 1 2]` on the
three translation pairs; zero on every rotation. This matches MSC `COUPMASS` for CROD and
sbeam's always-consistent CBAR convention (there is no COUPMASS switch). No torsional or
rotary inertia term, as in MSC and NASTRAN-95: a rod has no `I1`/`I2` for the CBAR
`ρ(I1+I2)` term, and `J` is a stiffness constant, not a mass moment. GPWG: `m·L` at the
midpoint. MASSSET scale applies as for CBAR.
- *Alternative rejected:* lumped `m·L/2` per end (NASTRAN-95 default). A strut and its CBAR
  spine would then use two mass formulations in one model.

**D4. CONROD natively.** `Crod(eid, pid, ga, gb)` in `bulk.crods`; `Prod(pid, mid, A, J, c,
nsm)` in `bulk.prods`; `Conrod(eid, ga, gb, mid, A, J, c, nsm)` in `bulk.conrods`.
`rod_section(elem, bulk) -> RodSection(mid, A, J, c, nsm)` is the only place that knows the
difference; no synthetic PIDs leak into the viewer or the mirror tool.

**D5. Recovery and sign.** `RodForce(eid, axial, torque)`, `RodStress(eid, axial, torsional)`
with `axial = P/A`, `torsional = T·C/J` (0 when `J = 0` or `C = 0`, per `srod1.f`). `P` and
`T` come from `bar_internal_resultants(f_local)` (`p = f[6]`, `t = f[9]`), the §8
single-source helper, so rod and CBAR signs cannot diverge. Rods never populate
`bar_forces`/`bar_stresses`; new `rod_forces`/`rod_stresses` dicts sit beside them on
`Sol101Result`, `Sol144Result`, `Sol144TrimResult`, and `rod_forces` on `ManeuverStep`. The
four recovery loops collapse into one `recover_line_elements` (rule 3).

**D6. f06 layout.** New blocks, emitted only when the deck has rods, after the CBAR blocks,
under the same FORCE/STRESS requests, in SOL 101, both SOL 144 paths and the MLOADS
critical-sample f06:

```
                                     F O R C E S   I N   R O D   E L E M E N T S      ( C R O D )
       ELEMENT          AXIAL
         ID.            FORCE       TORQUE

                                   S T R E S S E S   I N   R O D   E L E M E N T S      ( C R O D )
       ELEMENT          AXIAL       SAFETY    TORSIONAL       SAFETY
         ID.           STRESS       MARGIN       STRESS       MARGIN
```

CONROD prints the same blocks under `( C O N R O D )`. One element per row on
`_hdr`/`_FIELD_W` (sbeam convention; NASTRAN's two-elements-per-line is not reproduced).
`SAFETY MARGIN` cells are header-only blank, like the CBAR `M.S.-T/-C` columns.

**D7. Validation.** CROD/CONROD: GA, GB exist, GA ≠ GB, PID → PROD exists, PROD/CONROD MID →
MAT1 exists, `A > 0`, `J ≥ 0`; coincident grids raise at assembly as for CBAR. **EID
uniqueness across CBAR/CROD/CONROD/CBUSH** is enforced in one helper (rule 3:
`01_beam_model.md` already claims duplicate-EID detection for CBAR; the code lacked it).
Rod-only grids have rotational stiffness only about each rod's axis; sbeam has no AUTOSPC,
so the deck must SPC them. Stated in the card reference, Known limitations and a pre-solve
viewer warning beside the zero-length check.

**D8. Scope fences.** No PLOAD1/thermal/element deformation (#45). No CTUBE, no PBARL. Rod
CSV deferred to #31 (no CBAR element-force CSV exists either; #31 owns the schema). Viewer:
model-view traces, a rod table and a "Rod Forces" results tab, nothing more. The mirror tool
gains CROD/CONROD so half-model pylons mirror instead of being silently dropped.

## 4. Conventions cited

- `09_conventions.md` §1: basic frame, right-handed.
- §7: unit-neutral card fields; `A`, `J`, `C`, `NSM` in the deck's units.
- §8: single-source helper table — a rod row is added, pointing at
  `bar_internal_resultants` for `P` and `T`.
- §9: element local axis `e_x = GB − GA`; +x-face internal resultants; `AXIAL = P` tension
  positive; `TORQUE = T` right-handed about +x; NASTRAN output layout column-for-column.

## 5. Validation (benchmark-first, rule 2)

| Gate | Configuration | Expected | Tolerance |
|---|---|---|---|
| **G1** closed form (V24) | Single CROD, GA clamped, GB loaded Px = 1000, Mx = 10. E = 2e11, G = 8e10, A = 1e-4, J = 2e-8, C = 2e-3, L = 2 | δ = PL/EA = 1.0e-4; θ = TL/GJ = 1.25e-2; AXIAL 1000, TORQUE 10; σ = P/A = 1.0e7; τ = TC/J = 1.0e6 | 1e-10 rel |
| **G2** statics (V25) | Planar V: fixed grids (−1,0,0), (+1,0,0), apex (0,0,−1); CROD 1 + CONROD 2; apex SPC 2456; Px = 500, Pz = −1000 | N1 = 1060.660172 (tension), N2 = 353.553391; ΣSPC = −P | 1e-9 rel |
| **G3** modal (V26) | CONM2 m = 100 at the apex of two massless struts (ρ = 0) at ±30° from vertical, L = 2, EA = 2e7, apex SPC 2456 | k = EA/L = 1e7; f_z = √(1.5k/m)/2π = 61.640444 Hz; f_x = √(0.5k/m)/2π = 35.588127 Hz | 1e-8 rel; with ρ = 7850 the pair drops by < 1 % |
| **G4** equivalence (V27) | CROD vs CBAR `PA=PB=56` with the same A, J, E, G, L, under axial + torque and under a transverse tip force, side by side on separate grids | identical δ, θ, AXIAL, TORQUE; CBAR 56 bending/shear fields 0; rod has no bending fields | 1e-12 rel |
| **G5** invariants | Unit level on `rod_local_stiffness`, `rod_local_mass`, `line_element` | K rows/cols 1,2,4,5,7,8,10,11 exactly 0; M has no rotational terms; `K_global·R = 0` for the six rigid modes; global K identical for any admissible `e_y` (G5b); `Rᵀ M R` = `m·L`·I₃ on translations | 0 abs / 1e-14 |
| **G6** NASTRAN-95 mapping | Synthetic 12-vector through `line_element` + recovery | `P = A·(E/L)·n·(u_B−u_A)`, `T = (GJ/L)·n·(θ_B−θ_A)`, `τ = T·C/J`, `C/J = 0` at `J = 0` (`srod1.f`/`srod2.f` term by term) | 1e-14 |
| **G7** registry coverage | Deck with one CBAR, one CROD, one CONROD | every EID present in K and M, GPWG total = sum of three, both results dicts filled, all f06 blocks present with the D6 labels, column-alignment gate green, viewer tables build | exact |
| **G8** parser | Field tables and errors | CROD/PROD/CONROD fields and defaults; `ValueError` for missing GA/GB/PID/MID, GA = GB, duplicate EID across element types, A ≤ 0 | — |
| **Non-regression** | Full suite + the shipped sample decks | rodless decks bit-identical f06 against `0108f76`; `tests/tools/test_import_boundary.py` and `TestG5SingleSource` green | bit-identical |

## 6. Prototype

Reference numbers computed 2026-10-24 (planar V statics by joint equilibrium; modal from the
2-DOF spring pair): see §5. No solver prototype was needed; the closed forms are exact for
single rods.

## 7. Affected code and docs (Tier L closure)

**Code:**
- `model/element.py` (`Crod`, `Conrod`), `model/property.py` (`Prod`), `model/bulk_data.py`.
- `parser/bdf_reader.py`: three handlers, dispatch, shared duplicate-EID check.
- `assembly/elements.py` (new): registry, rod frame, rod matrices, `rod_section`.
- `assembly/stiffness.py`, `assembly/mass_matrix.py`, `gpwg.py`: loops through the registry.
- `solver/element_recovery.py` (new): rod recovery + `recover_line_elements`; the four
  solver loops replaced.
- `results/results.py` (`RodForce`, `RodStress`, result fields), `results/f06_writer.py`.
- `viewer/geometry.py`, `viewer/app.py`, `viewer/results_view.py`.
- `sbeam_tools/common/mirror.py`.

**Tests:** `tests/assembly/test_rod_element.py`, `tests/solver/test_rod_recovery.py`,
`tests/parser/test_rod_cards.py`, `tests/results/test_f06_rod_blocks.py`; V24–V27 in
`tests/integration/test_verification.py`; `TestValPylon` in `test_sample_verification.py`.

**Docs:** `02_card_reference.md` (CROD/PROD/CONROD + limitation), `03_static_analysis.md`,
`04_modal_analysis.md`, `01_beam_model.md`, `00_program_overview.md` (tree, V-suite, Known
limitations, phase table), `09_conventions.md` §8/§9, `CLAUDE.md` Supported Cards,
`00_INDEX.md`, `02_parked.md`, `CHANGELOG.md` (Added), `40_history/02_sol101_static.md`
(full L-tier step) + `00_completed_development.md`.

## 8. Resolved questions (2026-10-24)

1. **D1:** registry of per-type functions, as recommended.
2. **D3:** consistent translational mass, no torsional inertia, as recommended.
3. **D4:** own `Conrod` dataclass behind `rod_section`, as recommended.
4. **D8:** rod CSV deferred to #31, as recommended.

## 9. Implementation decisions (2026-10-24)

1. **Record split:** `LineElement` carries geometry, released `K_local` and `T` only; the
   mass side is `line_element_mass_global` / `line_element_mass_per_length`. Recovery runs
   per MLOADS sample and must never build a mass matrix, so D1's "M_local in the record" was
   dropped.
2. **CBAR entry = the old arithmetic verbatim**, including the `np.array` position
   subtraction for `L`, so the seven shipped sample outputs are byte-identical to `0108f76`
   (f06, loads BDF and CSV; checked with `cmp`). `iter_line_elements` keeps CBAR insertion
   order for the same reason (COO duplicate summation order).
3. **Import direction:** `elements.py` imports `stiffness.py` and `mass_matrix.py`; their
   two assemblers import the registry inside the function (precedent: `resolve_mass_case`).
   `gpwg.py` imports it at module level and keeps its lenient skip of elements with missing
   property/material/grids (`KeyError` → skip), because the viewer calls it on partial decks.
4. **Sign helper reuse:** `rod_force_from_local` calls `bar_internal_resultants` (`p = f[6]`,
   `t = f[9]`); `09_conventions.md` §8 gained the row. `RodStress.torsional = 0` when
   `J = 0` or `C = 0`.
5. **Validation sweep (rule 3):** the shared `_check_unique_eid` now also runs on CBAR (the
   docs promised it, the code did not do it) and PBAR/PROD share one PID space. Rod MID is
   checked at the element, not the PROD, so card order stays "GRID/PROD/MAT1 before the
   element" as for CBAR.
6. **G4 configuration changed:** a transverse tip force on a both-ends-pinned member is a
   mechanism for the CBAR 56 as much as for the rod, so V27 applies Px + Mx with GB held in
   2356 and adds a transverse force that goes straight into the SPC; both elements must
   ignore it. The CBAR 56 bending/shear columns read 0 to 1e-9 abs.
7. **Rod-only grids:** no solver-side AUTOSPC was added (would be a convention change). The
   card reference, `01_beam_model.md`, the Known-limitations index and a viewer pre-solve
   warning (`_rod_only_grids_without_rotation_spc`) carry the rule; the sample deck avoids
   it by making the engine grid the spine's end B.
8. **f06:** one element per row on `_hdr` (not NASTRAN's two per line); the blocks are
   omitted entirely on rodless decks. The DEF-M13 alignment gate gained the `STRESS` label.
9. **Gates landed as:** G1 → V24 `TestV24RodAxialTorsion`; G2 → V25; G3 → V26 (massless
   exact at 1e-8, ρ = 7850 gives 35.403 / 61.320 Hz, −0.5 %); G4 → V27; G5/G5b/G7(assembly)
   → `tests/assembly/test_rod_element.py`; G6/G7(recovery) →
   `tests/solver/test_rod_recovery.py`; G7(f06) → `tests/results/test_f06_rod_blocks.py`;
   G8 → `tests/parser/test_rod_cards.py`; sample deck → `TestValPylonStrutEngine`.
   Measured: V24 δ = 9.999999999999999e-05, θ = 0.0125, σ = 1.0e7, τ = 1.0e6; V25
   N1 = 1060.6601717798214, N2 = 353.5533905932738; V26 35.58812717 / 61.64044441 Hz; all
   as predicted in §5.
