# Changelog

All notable changes to sbeam are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Post-Phase-1 additions built on top of v0.1.0. Will be released as v0.2.0 on Phase 2 completion.

### Added

**Step 65 — flagship realistic-airplane SOL 144 sample family + theory doc (2026-08-01)**

The first deck anywhere in the repo where a **corrected AIC drives a trim**, and the first
that pairs `MLOADS` with `MASSSET`. One bulk model, three thin case-control drivers over it
by whole-bulk `INCLUDE`:

- `sample/cessna210_flagship_bulk.bdf` — Cessna 210-like full-span airframe: 324-box
  5-surface mesh (1000-spaced CAERO1 EIDs; 6000/7000 reserved for Step 66 body panels),
  quarter-MAC reference grid spliced into the fuselage load path with a z-down stability
  `CORD2R`, `SUPORT,900,35`, 1081.0 kg at 22.0 % MAC, four `SPLINE2` (DTHY = 0.0) plus an
  `ATTACH` on the fin, a part-chord 32-box elevator on the straight ⅔-chord line, two
  `MONPNT1` + two `MONPNT3`, three `MASSSET` cases (996.0/1201.0/1560.0 kg exercising
  DELETE/ADD/REPLACE and an offset CONM2), and the full `MLOADS` chain.
- `..._trim.bdf` (1g cruise + 2.5g pull-up), `..._massset.bdf` (payload sweep),
  `..._mloads.bdf` (elevator-ramp transient), `..._section_data.csv`.
- `docs/20_theory/02_realistic_airplane_sol144.md` — tutorial: the deck layer by layer with
  a "what breaks if you get this wrong" note per layer, then the f06 read block by block
  against hand-check anchors.

Results: CL closes on n·W at both load factors (rel 1e-6), rigid CZ_α = 5.33 /rad with the
elastic-restrained column +3.5 % on it, divergence at 23× the cruise q, elevator −3.91 °/g,
whole-aircraft `MONPNT1` = n·W with `MONPNT3` ≈ 0 (1.5e-11 N).

**The correction is pre-baked from 3D-informed section data**, and that is the family's
central lesson. A VLM strip already carries the finite-wing downwash, so its installed slope
(0.086 → 0.047 /deg on this wing, 0.044 /deg on the HTP) is far below the 2D section value;
tabulating the 2D slope and letting WT2 enforce it double-counts the downwash and drives the
wing alone to an unphysical 6.0 /rad. The committed table is anchored to the model's own 3D
strip loading and scaled to the Helmbold AR-7.72 target, so the correction adds camber,
washout and section moment (CL₀ 0 → 0.099) while moving the lift slope only 5.21 → 5.33 /rad.

Also in this step:
- **Wing stiffness calibrated** rather than inherited — the previous PBAR values left the
  wing effectively rigid (+0.44 % elastic, divergence 175× q). Established empirically that
  `I2`, not `I1`, resists flapwise bending for a wing CBAR along global Y with orientation
  vector (1,0,0); the inherited comment had them swapped. Cross-section area re-sized as the
  mass property it also is (the old `A = 0.020` fuselage was 564 kg of structure at
  CG x = 4.06, which put the design CG out of reach).
- **First `ATTACH` card in any `.bdf`/`.dat` in the repo** (the fin), closing the coverage
  gap found during DEF-M11 — the card had only ever been exercised by Python fixtures.
- **`MLDCOMD` tables are absolute, hence mass-case specific.** First coverage of MLOADS ×
  MASSSET: a table authored for the baseline trim does not start at another mass case's
  trimmed elevator, so the run begins with a step input. Deck-authoring property, not a
  solver defect — re-authored for the case, the initial condition reproduces to 3e-16.
  Documented in `05c_sol144_maneuver.md`.
- **Docs fix:** `02_card_reference.md` described the `AESURF` `CID1` hinge as that system's
  **x**-axis; the code uses the **y**-axis (`integration.build_djx` → `R[:, 1]`). Following
  the documented convention yields an identically-zero elevator column and an unexplained
  singular-matrix failure in the trim solve.

Gated by `tests/aero/test_cessna210_flagship.py` (24 checks, ~28 s), including a wing-root
inertia-relief gate (bending per unit weight falls 0.760 → 0.635 → 0.586 as fuel enters the
wing) that no other test covered.

### Removed

- `sample/airplane_aero.bdf` (its NCHORD/NSPAN box-aspect-ratio sizing rationale moved into
  the flagship bulk header), `sample/cessna210_aero.bdf` and
  `sample/cessna210_section_data.csv` — superseded by the flagship family.
  `tests/aero/test_cessna210_example.py` is re-pointed at the flagship with its numeric
  assertions **re-derived** for the 3D-informed table (they were tied to the old flat 2D CSV).

**Offset-tip-mass coupled bending-torsion sample deck (2026-08-01)**

`sample/val_cantilever_offset_mass_modes.bdf` — a SOL 103 cantilever with a tip CONM2 whose
CG sits 1.5 m off the elastic axis (m = 5000 kg, I11 = 5000 kg·m²). The offset mass block
(the `m·[r]×` translation-rotation coupling plus the `m·d²` parallel-axis term) produces two
genuinely coupled bending-torsion modes: f₁ ≈ 0.1489 Hz (bending-dominant, ~10 % twist
participation) and f₂ ≈ 0.7466 Hz (torsion-dominant). The deck header carries the tip-dominant
2-DOF closed form with Rayleigh beam-mass corrections; the FE result matches it to 1.4e-5 /
9.6e-4 relative. Unlike V12 (which SPCs everything but Rx), both partitions stay free — this
is the shipped demonstration that a mass off the elastic center couples the mode families.

Gated in CI alongside the VAL2 decks: `tests/integration/test_sample_verification.py` gains
`TestValCantileverOffsetMassModes` (3 tests — coupled-pair frequencies vs the closed form at
rel 2e-3, twist-participation ratios of both mode shapes, and a decoupling check that zeroing
the CONM2 offset separates the families). Docs: `04_modal_analysis.md` verification Case 6,
`00_program_overview.md` VAL2 table row.

Alongside it, the 2026-08-01 torsion-capability review recorded the three known torsion gaps
as backlog items (`docs/30_future/00_backlog.md`, Phase 2+ table): CBAR end offsets (WA/WB),
shear-center offset / PBAR I12 bend-twist coupling, and restrained warping of open
thin-walled sections.

**VAL2 — closed-form CI gates for the four sample verification decks (2026-08-01)**

The four `CLAUDE.md` "Verification Test Cases" are now enforced by CI against the decks that
ship them. Previously they were exercised only by `docs/20_theory/00_beam_methods.ipynb`,
which CI never runs — the V1–V20 suite gates its own private decks under
`tests/integration/bdf/`, not `sample/` — so a regression in the decks users copy could reach
a release unnoticed.

`tests/integration/test_sample_verification.py` (11 tests, 4 solves, 0.6 s) parses each
shipped deck, solves it through `run_sol101`/`run_sol103` and asserts the analytical result:

| Deck | Gates |
|------|-------|
| `sample/val_cantilever_static.bdf` | tip Tz = PL³/3EI, tip Ry = PL²/2EI, root Fz = P and My = −P·L |
| `sample/val_ss_static.bdf` | mid-span Tz = PL³/48EI, P/2 at each support |
| `sample/val_cantilever_modes.bdf` | f₁ (β₁ = 1.875104) and f₂ (β₂ = 4.694091), ascending-order guard |
| `sample/val_free_free_modes.bdf` | six rigid-body modes < 1e-3 Hz, mode 7 elastic (>1e3 separation), f₇ against the free-free closed form (β = 4.730041) |

Beam properties are read back out of the parsed deck rather than declared as module constants,
so a deck edit cannot silently drift away from the values a test compares against. Static
gates run at `rel = 1e-9` — the consistent Euler-Bernoulli formulation is exact at the nodes
for point loads, so the measured error is round-off (~1e-13 relative); modal gates run at
`rel = 1e-5` (f₁) and `2e-4` (f₂, f₇), 6–11× the measured discretisation error. Signs are
gated, not just magnitudes.

Note for anyone reading `val_cantilever_modes.bdf`: its header's "f₂ ≈ 2.58 Hz (XY)" comment
is stale — the deck's own `SPC1, 1, 12, …` suppresses the XY bending family, so f₂ is the
second XZ bending mode at 16.16 Hz (mode 4, 71.95 Hz, is first torsion). No production code
and no CI-config change.

### Fixed

**`parse_bdf` / `parse_bulk_file` accept a `Path`, not just a `str` (2026-08-01)**

Both readers were annotated `filepath: str` while only ever calling `open(filepath)` and
`os.path.dirname(os.path.abspath(filepath))` — all of which take any `os.PathLike[str]`. The
annotation understated what the functions accept, so every `parse_bdf(BDF_DIR / "model.bdf")`
call site was a type error (21 in `tests/integration/test_verification.py`, 6 in the viewer
tests) and the other 68 call sites carried a redundant `str(...)` wrapper to work around it.

Both signatures now take `StrPath = Union[str, os.PathLike[str]]`, a new alias in
`sbeam/types.py` (the first non-array alias there; documented in the
`docs/10_standard/00_program_overview.md` alias table). Runtime behaviour is unchanged — this
is an annotation widening only, and no call site needed editing.

While fixing this, both integration verification modules were brought up to the project's
"every function signature is annotated" standard: fixture return types and the test-method
parameters that consume them are now typed (`Sol101Fixture`/`Sol101BulkFixture` in
`test_verification.py`, `StaticFixture`/`ModalFixture` in `test_sample_verification.py`),
clearing 67 and 22 strict-mode errors respectively. These were invisible to CI — `pyrightconfig.json`
sets `"include": ["sbeam"]` — but Pylance applies strict mode to any open file, so the editor
disagreed with CI. Annotating `TestB3MultiSubcase._make_model` also pinned down that it returns
a `CaseControl`, not the `SubcaseControl` its sibling `TestR12NoLoadSid._make_model` returns.
`test_verification.py`'s docstring said "V1–V19" while the file has run V20 since the CBUSH
step; corrected.

**DEF-M2 — `solve_rigid_cl` now reports body-axis force/moment components (2026-08-01)**

⚠️ **Behaviour change on canted decks.** The rigid VLM path integrated lift as
`2·Σ Γ·‖Δs⃗‖`, crediting the whole Kutta–Joukowski force *magnitude* to body-z with no `n_z`
projection, and computed `CM` from the pressure form over lift surfaces only. `build_skj`
produces a genuine vector `F_j = area_j·n̂_j·cp_j`, and the normalwash RHS already carries one
`cos Γ` — so the trim/f06 totals scaled as `cos²Γ` while the rigid path scaled as `cos Γ`, an
`1/cos Γ` disagreement (1.1547 at 30° dihedral). Inside the viewer, the Aero tab's CZ/CM
metrics disagreed with the S&C derivative table *on the same tab*.

`CX`/`CY`/`CZ` are now the three columns of a single per-box force vector
`f_box = 2·Γ·width·n̂ ≡ skj @ cp`, summed over every box; `CM` is `−Σ Fz·(x_force − xref)`,
verbatim `sol144.pitch_moment`. The two paths are now identical **by construction**, gated at
1e-12 by the new V-AE3-DIH test on three canted decks. The `dy` variable was renamed `width`:
it is the panel width (setting `chord_box`, weighting the Trefftz integral), never the
vertical-force lever, and conflating the two roles was the defect.

Values that move, all explained by the deck's dihedral — measured at α = 3°:

| Deck | Wing dihedral | CZ and CM ratio (new/old) |
|------|---------------|---------------------------|
| `val_vlm_dihedral`, `val_vlm_anhedral`, `val_dihedral_trim` | 10.000° | 0.98481 = cos 10° |
| `val_wing_taper_dihedral`, `..._twist` | 5.000° | 0.99619 = cos 5° |
| `cessna210_aero`, `_body`, `_strip` | 1.504° | 0.99969 (load-weighted blend with the flat tail) |

The other 8 aero sample decks are planar and bit-identical. `CY` is now summed over every box,
so a canted wing's real side force is reported (it cancels to ~1e-17 on symmetric builds)
rather than being dropped because the surface was classified "lift". `cl_section` is
deliberately unchanged — it is a section *normal-force* coefficient `cn`, which is what the
section-correction path ingests from CFD; that asymmetry is now documented at both ends.
`trefftz_cdi`'s internal `CL_l` was projected so `CDi = CZ²/(π·AR·e)` holds against the
returned `CZ`; the nonplanar-wake `Di` kernel itself is a separate physics question, raised as
backlog **DEF-M14** rather than changed silently here.

**DEF-M11 — ATTACH force transfer completed for canted and vertical panels (2026-08-01)**

`_build_attach_rows` (`sbeam/aero/spline.py`) filled only the z-displacement row of `g_disp`
— `Tz` plus the z-component of `ω×r`. Since `g_disp` is copied into `g_load`, the operator
whose transpose transfers box forces to the structure, the in-plane `Fx`/`Fy` of any
non-z-normal ATTACH box never reached the master grid, taking the roll and yaw moments with
them. On a 26.57° dihedral panel a true box force of `(0, −0.5, 1.0)` transferred as
`(0, 0, 1.0)` — half the lift dropped as side force — with `Mz` entirely lost and `Mx` short
by the `Fy·rz` term; a vertical fin panel transferred nothing at all. All three rows now
carry the full rigid-body transform `u = t + ω×r` (translation identity plus `skew(ω)·r`),
so `g_dispᵀ f` is the exact `F = Σ f_j`, `M = Σ r_j × f_j`, completing the pairing with the
box-normal-general `g_slope` from DEF-H1.

**No shipped result changes.** For a z-normal panel the box force is pure `Fz`, so the added
rows multiply by zero — gated by a bit-identity test. The audit also found that no `.bdf` or
`.dat` file in the repo contains an `ATTACH` card at all; the card is exercised only by
Python-built test fixtures, which is now logged as a sample-coverage gap in the backlog.

New gates in `tests/aero/test_spline.py` (`TestAttachInPlaneForceTransfer`): V-B3d-DIH
(dihedral, all six components to 1e-14), V-B3d-VERT (fin), and a kinematic-exactness check
that `g_disp @ u` reproduces `t + ω×r` per box. All three were confirmed to fail against the
pre-fix source.

### Changed

**DEF-M deliverable-integrity batch — M5, M6, M7, M10 (2026-08-01)**

Four defects in what *leaves* the program — the f06 tables, the exported bulk-data cards and
the shipped sample decks. No solver math changed; every fix is at the handoff boundary.

- **DEF-M6 — exported `FORCE`/`MOMENT` cards now fit the NASTRAN 8-character field.** The
  exporter wrote 12-13 character reals into a comma free-field card; free field does not
  exempt a card from the 8-character width, so a strict reader truncated `4.715932E+03` to
  `4.715932`. New `sbeam/parser/bdf_field.py` provides `fmt_real8`, which picks whichever of a
  fixed-point or NASTRAN implicit-exponent spelling reproduces the value more closely, and
  `parse_real`, which `bdf_reader._to_float` now delegates to so the read and write formats
  are one definition. Non-finite values raise instead of writing `NAN` into a card.
  **0 oversized fields across 1456** exported over the four HA144A decks, from 66 in one
  export. Two per-grid export round-trip tolerances moved `1e-6` -> `1e-5`: that is the
  8-character field floor (a sign costs a significant figure), not exporter slop.
- **DEF-M5 — the critical maneuver sample is one metric on one numbering.** The selector
  (`argmax ‖closure‖`, the aero/inertia *balance residual*, ~0 on a balanced maneuver), the
  f06 label, the printed column (`max|net_loads|` over all six DOFs, mixing forces and
  moments) and the MLDPRNT index (0-based vs the f06's 1-based) were four different things,
  and the exported critical-sample BDF was taken at a sample the table disowned. All now use
  `results.peak_grid_force` — the peak per-grid net translational force — on 1-based
  numbering. `CLOSURE_F`/`CLOSURE_M` stay in the MLDPRNT table as the balance diagnostic
  they are.
- **DEF-M7 — f06 maneuver time-history columns align with their headers.** 15-character
  header cells over 13-character data drifted a full column with 5 trim variables; header
  and rows now share one `_FIELD_W`.
- **DEF-M10 — the HA144A whole-aircraft `MONPNT3` accounts for all of the inertia.**
  `SET1 1310` omitted grid 97 (93.236 slug, exactly 18.75 % of the model), so the
  `WHOLE AIRCRAFT` monitor reported ~+3000 lb of phantom lift on a balanced trim; it now
  closes to 0. The same defect was found and fixed in `ha144a_fullspan_mloads.bdf` and
  `ha144a_massset_sweep.bdf` (which also omitted the four fuel-overlay stations). New solver
  warning when a monitor integrates the *whole* aero load but only part of the mass — scoped
  that way so it cannot fire on deliberate section cuts, and measured against the active
  MASSSET case rather than every `CONM2` card.

Two follow-ons filed while verifying, both the same defect classes in adjacent code and
neither in this batch's scope:
- **DEF-M12** — `aero/section_correction.card_lines` writes the same oversized fields into
  `W2GJ`/`AECORR`/`STRIPK` correction cards and should route through `fmt_real8`.
- **DEF-M13** — four more f06 blocks (monitor totals, displacement vector, bar forces, bar
  stresses) carry the same header/data column drift DEF-M7 fixed in the maneuver table.
  Numbers are correct; the listing layout is not.

**Project-wide type annotations + pyright CI gate (2026-07-30)**

- New `sbeam/types.py` with the shared aliases every physical quantity now uses:
  `FloatArray`, `ComplexArray`, `IntArray`, `BoolArray`, `SparseMatrix`, `LuFactor`.
  All 275 bare `np.ndarray` annotations and 488 bare `dict`/`list`/`tuple`/`set`
  annotations across 41 modules are now parameterised; the type information moved out of
  trailing comments and into the signatures (`BulkData` alone gained 54 field types).
- New `pyrightconfig.json` (strict, Python 3.9) and a `pyright` step in CI after `ruff`;
  `pyright` added to the `dev` extra. The three unknown-type rules and
  `reportConstantRedefinition` are disabled with the rationale documented in
  `docs/10_standard/00_program_overview.md` §Coding Standards.
- `Optional` dereferences that could raise a bare `AttributeError` now go through explicit
  guards: `require_aeros(bulk)` (`BulkData.aeros`) and `AeroModel.require_g_disp()` /
  `require_g_slope()`, each raising a descriptive `ValueError`.
- Cross-module helpers promoted from private to public names, matching what they already
  are in practice: `_get_transform` → `get_transform`, `_node_dofs` → `node_dofs`,
  `_build_inertial_cols` → `build_inertial_cols`, `_get_suport_local` → `get_suport_local`,
  `_compute_rigid_derivs` → `compute_rigid_derivs`, `_pitch_moment` → `pitch_moment`,
  `_urdd_rcsid_to_basic` → `urdd_rcsid_to_basic`, `_load_resultant` → `load_resultant`,
  `_check_conditioning` → `check_conditioning`, `_pair_to_bdf` → `pair_to_bdf`,
  `_card_lines` → `card_lines`, `_build_id_to_k` → `build_id_to_k`,
  `_nchord_per_caero` → `nchord_per_caero`, `_emit_force_moment_cards` →
  `emit_force_moment_cards`, `_RATIO_WARN` → `RATIO_WARN`.
- `AsetReduction.reduce_matrix` gained `@overload`s so a dense input (or `dense=True`) is
  typed as returning `FloatArray` rather than the dense-or-sparse union.
- Behaviour is unchanged throughout: the full suite is identical before and after
  (1187 passed, 6 xfailed).

### Deprecated

**DEF-H2 + DEF-H3 — `AECORR METHOD=WT1` deprecated (2026-07-31)**

- The WT1 per-strip force-matching AIC correction is deprecated. It still parses and runs
  unchanged — no numerics were altered — but the parser now raises a `UserWarning` naming
  both defects and pointing at `WT2` / the section-correction path.
- **DEF-H2:** `build_aero_model` hands `apply_wt1` the Prandtl–Glauert-compressed boxes, so
  the reference strip force is integrated over compressed areas and chords while the Göthert
  `1/β` factor and the Γ→ΔCp conversion (physical chords) are applied afterwards. The
  delivered strip force is `f_target/β²` — measured at exactly **1.5625 (= 1/0.64) at
  M = 0.6**, a 56 % overshoot. Exact at M = 0 only, which is where all four pre-existing WT1
  tests ran.
- **DEF-H3:** `apply_wt1` groups strips by `box.i_span`, which restarts per parent CAERO1, so
  a card selected for one surface rescales every surface sharing an `i_span` index. Measured
  on a wing+tail deck: wing and tail are scaled by the *same* per-`i_span` ratio, so the tail
  is corrupted although no card names it and the wing misses its own target.
- **Deprecated rather than fixed** — `WT2` is genuinely multi-surface and
  `section_correction.py` divides by β, so both are correct and strictly more capable; WT1
  offers no capability they lack. Both defects are pinned by new characterization tests in
  `tests/aero/test_corrections.py` so they cannot drift silently. Hard removal is deferred to
  a release boundary and tracked as backlog **DEF-R7**.
- Docs: `05a_aero_vlm.md`, `02_card_reference.md`, `05_aeroelastics.md`, `01_beam_model.md`
  and theory §3.3 mark WT1 deprecated. Two false claims were corrected in the process — 05a's
  "`WKK` and `WT1` still act on the primary CAERO1 only" (deleted; also struck from DEF-L6),
  and the card-reference rule that WT1's `f_target` length matches "the number of distinct
  span strips in the CAERO1" (it is counted model-wide).
- No shipped deck is affected: no `AECORR` card appears anywhere in `sample/` or
  `tests/**/*.bdf`.

### Fixed

**DEF-M silent-input batch — M4, M8, M9 + DEF-R5, DEF-L1, F1 (2026-08-01)**

Six defects, one theme: the deck said something, the program read it, discarded it, and
reported a converged answer anyway. **Several previously-accepted decks now fail loudly** —
that is the point of the batch, but it is a breaking change for any deck relying on the
silent behaviour.

- **F1 — colliding NASTRAN box IDs are now fatal.** A CAERO1 owns the `NSPAN*NCHORD`
  consecutive box IDs from its EID, so two CAERO1s numbered closer together overlap. The
  ID formula was reimplemented three times, each last-wins: on a 2×(30×2) case **10 of 120
  boxes were silently unreachable**, and `MONPNT1` resolves AELIST box IDs through that map
  with a direct lookup, so a collision dropped a box's load from the monitor total. New
  `panel.build_box_id_map` is the single derivation and validates once in
  `build_aero_model`; `AeroModel.require_box_id_to_k()` serves all four consumers.
  `mirror.py` now clears the box-ID *span*, not just the EIDs, when offsetting a mirrored
  half-model.
- **Sample decks renumbered.** Eight decks collided (`airplane_aero`,
  `cessna210_aero`/`_body`/`_strip`, `val_vlm_dihedral`/`_anhedral`/`_rect_ar8`/`_byu_wing`)
  and are renumbered to **`EID = 1000 × k`**, with the `SPLINE0` box ranges and the
  section-data CSV `caero` columns updated in lockstep. Results are **bit-identical** —
  `caero.eid` is a label that never enters an arithmetic expression, and meshing is in
  sorted-EID order.
- **DEF-M8a — W2GJ.** Duplicate cards per CAERO1 (silently shadowed by a bare `break`),
  short data (silently zero-padded) and long data (silently truncated) are all fatal. A
  W2GJ naming a CAERO1 not in the model — previously dead data no loop ever visited — is
  reported by the new `build_wg_all`.
- **DEF-M8b — WKK.** Was selected by the primary (lowest-EID) CAERO1 and applied to every
  box: a multi-surface deck hit a raw numpy shape error and a WKK on a non-primary surface
  was ignored. Now a per-surface scatter with length, duplicate and zero-weight checks (a
  zero weight makes the corrected AIC singular).
- **DEF-L1 — STRIPK, body targets, section data.** Duplicate STRIPK per CAERO1 and short
  STRIPK data (was a silent fall-back to PSTRIP `SLOPE0`) are fatal; `parse_body_targets`
  NaN-checks the four required TOTAL columns; `build_body_correction` rejects a PSTRIP
  panel; `validate_section_data` gains an optional `caero_eids` binding and a duplicate-eta
  check grouped by `(caero, var, mach, a_lo, a_hi)`.
- **DEF-M9 — an SPC on an RBE2/RBAR/RBE3-dependent DOF is now fatal.** It used to be
  filtered out of `reduce_to_aset` silently: the constraint never applied, the DOF stayed
  free to follow its master, and no reaction was reported. The error names every offending
  grid/DOF and the owning element. Verified safe first — no deck in `sample/` or `tests/`,
  and no inline fixture, trips it.
- **DEF-R5 — `sol101` ported onto the shared `reduce_to_aset`.** It hand-rolled the same
  reduction including its own copy of M9's bug, so the fix now lands once for SOL 101, 103,
  144 and the maneuver solvers. Verified numerically inert: displacements, reactions and
  CBAR end forces bit-identical across 31 decks.
- **DEF-M4 — `LOAD` in a TRIM subcase now raises.** `run_sol144_trim` never read
  `subcase.load_sid`; the trim RHS has no `f_struct` term, so the request vanished. The
  error points at `run_aeroelastic_static`, which does support it. Adding `f_struct` to the
  trim RHS is backlogged separately — it is a capability change with unresolved physics.
- `AsetReduction.expand_to_g` gains a no-rigid-elements fast path, so the SOL 101 port does
  not turn a cheap scatter into an O(n²) identity matvec on every static solve.
- Two stale "inverts via lstsq" docstrings corrected to `np.linalg.solve`.
- **Retired:** `test_partial_w2gj_data_fills_remaining_zeros`, which pinned the silent
  zero-pad as intended behaviour.

**Q4 + DEF-M3 — one mass model for `M_ax` (2026-07-31)**

- **`build_inertial_cols` is now `M_ax = −M_gg·Φ_r`**, formed from the same consistent
  `assemble_global_mass` the elastic equations use, instead of a separate hand-rolled
  *lumped* inertia model. The `M_ax = −M_aa·Φ_r` identity is now definitional rather than
  incidental (`reduce_rect` is `Tᵀ·` and `T Φ_r_a = Φ_r_g`).
- **Fixes DEF-M3** — the inertia-relief columns silently ignored CONM2 offset transport
  (the *grid* position was used as the moment arm, so an offset mass lost its parallel-axis
  `m·d²` inertia entirely), products of inertia (`i21/i31/i32` were never read, so yaw
  acceleration produced no roll reaction), CONM2 `CID` rotation, and PBAR `nsm`.
- **Fixes Q4** — lumped CBAR half-masses had no counterpart to the consistent-mass
  translation↔rotation coupling, so the identity broke on rotational rows whenever
  `rho > 0` (O(10 %) of the peak column value).
- **Behaviour change on decks with distributed CBAR mass or non-trivial CONM2s.** `M_ax`
  enters the trim equilibrium as `C_ax = q·Q_ax + M_ax` and is what `inertial_loads`,
  `net_loads` and the exported `FORCE`/`MOMENT` stress handoff are recovered from, so trim
  variables and maneuver loads move. Every shipped deck is **bit-identical** (all are
  CONM2-only with `rho = 0`); with `rho = 2700` forced onto `ha144a_fullspan_mloads`,
  ANGLEA goes 166.6637 → 166.7048 and peak displacement 33.193 → 33.447.
- **New `sbeam/assembly/rigid_body.py`** — `build_rigid_vectors_g`, the single derivation of
  the g-set rigid-body geometry, shared by `sol144.build_inertial_cols` and
  `modal_basis.build_rigid_modes` (which keeps ownership of the a-set restriction and its
  RBE3/RBAR round-trip check). It lives in `assembly/` because `modal_basis` imports
  `sol144`, so `sol144` cannot import back.
- **`build_inertial_cols` gained an optional `M_gg=` parameter** so callers that already
  hold the mass matrix do not assemble it twice; `assemble_aset_operators` and
  `run_sol144_trim` both pass theirs, removing a duplicate assembly from the trim path.
- New gates in `tests/aero/test_trim_urdd.py::TestInertialColsFullMassModel` check the
  closed-form rigid-body resultant (`F = −m a`, `M = −I_ref α`) rather than re-deriving
  through the same code path; the Q4 pin becomes
  `test_m_ax_identity_exact_with_consistent_cbar_mass` (exact to 1e-12 on all rows).

**Step 64 / DEF-M1 — SPLINE0 / un-splined box loads now enter the trim equilibrium (2026-07-31)**

- **Behaviour change — trim results on body-panel decks change by design.** Aero boxes with
  no structural spline (`SPLINE0`-declared body panels, or boxes no spline card covers)
  generate real force that reached the printed totals, the stability derivatives and MONPNT1,
  but never the trim force balance, `grid_loads`, MONPNT3 or the `FORCE`/`MOMENT` export.
  Since the A9 cruciform / A10 strip body workflows exist to carry residual Cm/Cn on exactly
  such panels, the printed aircraft and the balanced aircraft were different aircraft.
  Measured on the new `sample/ha144a_body_trim.bdf`: trimmed all-box lift missed the weight
  by **31.5 %** before the fix (21032 lb vs 15999 lb), and by **9.4e-15** after.
- Root cause: force transfer used the transpose of the displacement spline (the NASTRAN
  virtual-work convention), under which `u_box = 0 ⇒ f_g = 0` is a theorem — zero
  displacement necessarily meant zero load path. ZAERO avoids this with a separate
  force-mapping spline (`SPLINEF`); sbeam had adopted `SPLINE0`/`ATTACH` without it.
- **New third operator `g_load` = `g_disp` + rigid-load rows** (`aero/spline.py`), delivering
  each uncoupled group's exact 6-component resultant (all three force components) at a master
  grid. Read forward those rows are the rigid-body interpolation `u_k = u_m + θ_m × r_k`, so
  the virtual-work pairing is restored rather than broken: `SPLINE0` now means "`ATTACH` for
  loads, zero for incidence". `g_slope` stays zero — injected boxes load the structure but
  take no downwash from it — so `Q_aa` gains rows at the master grid but no columns.
- **`SPLINE0` gains field 5 `GRID`** naming the master structural grid; blank defaults to the
  SUPORT grid. `ValueError` on an unknown grid; `UserWarning` (never a raise) when a deck has
  neither, so SOL 101 body-panel decks such as `sample/cessna210_body.bdf` still build.
- New `build_spline_operators()` returning `SplineOperators(g_slope, g_disp, g_load, covered,
  injections)`; `build_g_spline()` kept as a kinematics-only wrapper. `AeroModel` gains
  `g_load`, `load_injections` and `require_g_load()`. All 13 force-transfer sites — `build_qaa`,
  `build_fg`, `Q_ax`, `grid_loads`, `compute_structural_loads`, `maneuver_qs`, the Step 61 modal
  GAFs — now use `g_load`; the viewer's displacement overlay deliberately stays on `g_disp`.
- New f06 `INJECTED AERO LOADS` block (source card, master grid, box count, resultant), emitted
  only when injection is active, so decks without uncoupled boxes are byte-identical.
- New sample `sample/ha144a_body_trim.bdf` (full-span HA144A + `PSTRIP` cruciform body panels)
  exercising both master-resolution paths; new gates in `tests/aero/test_spline.py` (V-M1a–f),
  `tests/integration/test_sol144_body_injection.py` and `tests/parser/test_aero.py`.
  Fully-splined decks are bit-identical (`load_injections == []` asserted).
- Follow-on backlogged: `SPLINEF`, the general distributed force-mapping spline (one master
  grid is exact for the global balance, approximate for local internal loads).

**DEF-H1 — ATTACH `g_slope` pitch sign inverted, spurious roll incidence (2026-07-31)**

- `aero/spline.py` wrote `g_slope[..,Ry] = -1.0` and `g_slope[..,Rx] = +1.0` for ATTACH-
  splined boxes. Since `g_slope` carries nose-up-positive incidence (`build_djk = -I`),
  nose-up pitch of a master grid produced washout and unit roll injected incidence that
  does not physically exist — so every ATTACH deck ran with sign-inverted aeroelastic
  feedback through `Q_aa`, trim and divergence. Measured end-to-end on a splined
  cantilever at q=800: the ATTACH route reported a 7 % lift *gain* where the validated
  SPLINE2 route gives a 1.2 % loss. No shipped sample deck uses ATTACH.
- The slope rows are now derived from the box normal —
  `g_slope[..,Ry] = +n_z`, `g_slope[..,Rz] = -n_y`, `Rx` zero, from
  `α = -(ω × x̂)·n̂` — which reduces to the correct `+1 / 0` for a flat panel and also
  handles dihedral and vertical ATTACH panels, unlike the previous constants.
- Tests: V-B3b corrected to `+1`; new V-B3e (roll → zero incidence), V-B3f (ATTACH matches
  SPLINE2 under a general rigid rotation) and a new `tests/aero/test_attach_sol144.py`
  V-B3g solver-level regression. Each was confirmed to fail against the pre-fix source.
- Docs: `05b_splining.md` kinematics and gate list re-derived (its "energy consistency"
  line had carried the wrong sign too), `02_card_reference.md` sign convention added,
  theory §4.4 corrected — it claimed ATTACH reuses the RBE2/RBE3 machinery, which it never
  did. The remaining `g_disp` z-row-only limitation is logged as backlog DEF-M11.

**Dead code and red CI lint (2026-07-30)**

- `ruff check sbeam/` had been failing (44 findings; 29 of them present 30 commits back).
  All unused imports and dead locals removed across `sbeam/` and `tests/`; the CI lint step
  now covers `tests/` as well. Three of the findings were introduced by Step 61
  (`maneuver_qs.py` kept importing `build_inertial_cols`/`get_suport_local` after they moved
  to `modal_basis`, plus a dead `grid_index` local).
- Removed two private SOL 144 helpers left dead by the Step 59/61 refactors:
  `_compute_aset_data` (superseded by `reduce_to_aset`) and `_compute_aero_forces`.
- `Sol144DivergResult` f06 output guarded `root.v_div` (`Optional[float]`) before formatting;
  `write_monitor_csv` guarded the MONPNT1 `aero`/`inertia`/`reaction` columns, which are
  `None` for aero-only monitors.
- `BodyCorrectionResult.cards` is typed `dict[int, tuple[W2gj, Union[Aecorr, Stripk]]]` —
  the strip-body builder stores `Stripk`, not `Aecorr`, so the two `*_cards_to_bdf`
  formatters now select by type instead of assuming one variant.
- `get_spc_dofs`, `assemble_global_mass`, `compute_gpwg` and `reduce_to_aset` declare their
  `Optional[int]` SID parameters (they were already called with `None`).

### Added

**Step 61 — Free-free maneuver modal basis + h-set operator set (2026-07-30)**

- New `sbeam/solver/modal_basis.py` — the basis layer of the Phase G0 modal architecture
  (Steps 61–63), built and validated **standalone**; the modal transient solver that consumes
  it lands with Step 62, so no analysis behaviour changes in this step.
  - `build_rigid_modes` — the single owner of the geometric rigid-body basis `Φ_r` (one column
    per SUPORT DOF, about `suport_pos`); `designs/rbmref_card.md` reuses it rather than
    deriving its own `B_target`.
  - `build_maneuver_basis` → `ManeuverBasis` (`Φ = [Φ_r | Φ_e]`, `M_hh`, `K_hh`, `M_rr`,
    elastic frequencies, rigid→trim-label map, diagnostics): one `solve_modes` call per job,
    mean-axis mass-orthogonalization of the elastic modes against `Φ_r`, NMODES truncation of
    the elastic partition only.
  - `build_hset_gafs` → `HsetGafs` (`Q_hh` via the reused `coupling.build_gaf`, `Q_hx`/`Q_hc`,
    the rigid-rate `B_hh`, `f_h0`, `C_hh = diag(2ζω)`); all operators dynamic-pressure free.
  - `assemble_aset_operators` — the shared a-set assembly for both maneuver paths, on top of
    Step 59's `reduce_to_aset`. `maneuver_qs` now calls it; its behaviour is unchanged.
- New `aero/integration.py::build_dj_rigidrate` — normalwash per unit *physical* rigid-body
  rate; each column is the corresponding `build_djx` column rescaled (plunge `−1/V`, pitch
  `c_ref/2V`, roll/yaw `b_ref/2V`), keeping the `Ω×r` geometry in one place.
- `MLOADS` gains fields 7–9: `NMODES` (retained **elastic** modes — rigid modes are always all
  retained), `METHOD` (EIGRL sid for the basis eigensolve, `0` = internal all-modes default)
  and `ZETA` (uniform elastic modal damping ratio). The shipped quasi-steady solver parses and
  warns that it ignores all three until Step 62.
- `TRIM` gains the sbeam `RHOREF` pseudo-label (`TRIM, 1, 0.9, 40.0, RHOREF, 2.3769-3, ...`):
  the freestream density, used only for `V = √(2q/ρ)`, which the transient rate terms require.
  Back-compatible — decks without it are unaffected; `Trim.velocity()` raises when it is absent.
  `sample/ha144a_fullspan_mloads.bdf` updated to carry it.
- 30 new tests: `tests/solver/test_modal_basis.py` (the five Step 61 gates — basis
  orthogonality, `M_rr` vs GPWG, the `M_ax = −M_aa Φ_r` identity, `Q_hh`/`K_hh` vs the static
  ROM, `K_hh` rigid block — plus condensation, truncation and error paths), plus
  `TestBuildDjRigidRate` and the new TRIM/MLOADS card cases.

**Step 60 — `MASSSET` payload / mass cases for static SOL 144 (2026-07-30)**

- New `MASSSET` bulk card (`Massset` in `model/mass.py`, `bulk.masssets`): a named mass
  configuration built from the baseline model mass — `SCALE` multiplies the baseline, then
  `ADD` / `REPLACE` / `DELETE` continuation rows overlay, swap, or drop CONM2 cards.
  `REPLACE` takes (baseline EID, overlay EID) **pairs**. EIDs named by `ADD` or by a
  `REPLACE` overlay slot are marked overlay-only (`bulk.overlay_conm2_eids`) and excluded
  from the baseline mass; an EID may not be both overlay and baseline.
- Case-control `MASSSET = sid` per subcase (`SubcaseControl.massset_sid`), MSC-style.
- New `model/mass_overlay.py`: `resolve_mass_case` / `effective_conm2s`.
  `assemble_global_mass`, `compute_gpwg`, `sol144._build_inertial_cols`, `run_sol144_trim`
  and `run_maneuver_qs` all take an optional `massset_sid` (`None` = baseline, unchanged).
  Only mass-derived quantities are rebuilt per case — stiffness, splines, the VLM AIC and
  the whole `AeroCache` are geometry/Mach-only and shared untouched across a sweep.
- Output: `Sol144TrimResult` gains `massset_sid` / `massset_label` / `massset_mass` /
  `massset_cg`; the f06 subcase header gains `MASSSET`/`LABEL`/`MASS` and `CG` lines when a
  case is selected (baseline f06 output is byte-identical to before); load-card exports stamp
  the case in their comment block; the viewer GPWG panel gains a mass-case selector and the
  analysis-plan summary names the case per subcase.
- New sample deck `sample/ha144a_massset_sweep.bdf` — full-span HA144A, one TRIM card, three
  payload conditions (EMPTY 16000 lb / HALFFUEL 18500 lb / FULLFUEL 21000 lb) exercising all
  three ops.
- 42 new tests (`tests/parser/test_massset.py`, `tests/aero/test_massset_sweep.py`): card
  round-trip and every negative case; the equivalence gate (a MASSSET case is identical to a
  hand-edited deck with the same final CONM2 set — same `M_gg`, GPWG and trim); baseline
  unchanged; per-case Step 53 closure ≈ 0 and lift = case weight; three subcases sharing one
  `AeroModel` (object identity); heavier case ⇒ larger trimmed ANGLEA and further-aft CG.
- `mirror_halfspan` now rejects decks containing MASSSET cards — whether a payload item
  mirrors is model intent, not geometry.

### Changed

- **`*.monitor_loads.csv` gains two columns** (`massset`, `mass_case`) after `case`, naming
  the mass configuration each row was integrated at (`BASELINE` when no MASSSET is selected).
  Consumers that index the CSV by column position rather than header name need updating.

**Step 59 — shared `reduce_to_aset` a-set reduction (behavior-identical refactor, 2026-07-06)**

- New `sbeam/assembly/reduction.py`: `reduce_to_aset(bulk, grid_index, spc_sid)` returns an
  `AsetReduction` dataclass (`T`, `dep_dofs`, `red_dofs`, `free_local`, `free_dofs`) with
  `reduce_matrix` / `reduce_rect` / `reduce_vector` / `expand_to_g` methods — the single owner
  of the RBE3/RBAR-then-SPC g-set → a-set reduction previously duplicated across
  `sol144._build_qaa_aset`, `sol144._compute_aset_data`, `sol103.run_sol103`, and
  `maneuver_qs._assemble_operators`. All four consumers re-pointed;
  `sol144._compute_aset_data` and `sol144._expand_to_g` retained as thin wrappers/aliases.
- `Sol103Result` gains optional a-set eigendata fields `phi_free`, `free_dofs`, `K_free`,
  `M_free` (default `None`), populated by `run_sol103` — the retention consumed by the
  Step 61 modal basis and the `matrix_gaf_export` GAF loop.
- Behavior-identical: full suite unchanged, SOL 103/144 f06 and all
  `ha144a_fullspan_mloads.bdf` maneuver/monitor/load exports verified bit-identical pre/post
  (modulo embedded run timestamps). New `tests/assembly/test_reduction.py` (11 tests) proves
  equivalence against the pre-refactor reduction logic on an RBE3+SPC model.

### Documentation

**`docs/10_standard/05_aeroelastics.md` split by area (2026-07-05)**

- The 1,842-line aeroelastics code-standard guide is split into three area guides:
  `05a_aero_vlm.md` (Phase A — VLM, AIC corrections, CHORDCP, section synthesiser, body
  panels, viewer aero tab), `05b_splining.md` (Phase B — SPLINE2/ATTACH/SPLINE0,
  `build_g_spline`, load transfer), and `05c_sol144_maneuver.md` (Phases C + G0 — SOL 144
  trim/derivatives/divergence, running & output, transient maneuver loads, monitor points).
- `05_aeroelastics.md` retained as the index: architecture overview, validation status,
  supported-card table, and the file map. All section content carried over verbatim
  (heading-diff verified against the pre-split file).
- Phase-specific cross-references re-pointed (`02_card_reference.md`,
  `01_aeroelastics_theory.md`, backlog, CLAUDE.md, `docs/00_INDEX.md`); generic references
  continue to resolve via the index.

**Critical design review of `docs/30_future` + backlog restructure (2026-07-05)**

- `docs/30_future/00_backlog.md` rewritten as a priority-ordered plan (P1–P12 across four
  tiers) toward a production aeroelastic process: SOL 144 early-design sufficiency first
  (Steps 59–63 Phase G0 plan with `MASSSET` payload sweeps pulled forward to Step 60,
  monitor section cuts, viewer authoring), then SOL 145 + DLM (Phase D). All six
  `designs/*` proposals reviewed with recorded verdicts; stale prerequisites flagged
  (AE4 closed by AC7; `matrix_reuse_store` Phase 0 already delivered by Step 56/AC5);
  single owners assigned for shared infrastructure (`reduce_to_aset` → Step 59,
  rigid-basis builder → Step 61 with RBMREF folded in, MKAERO1/export bundle →
  `matrix_gaf_export`).
- Closed-item summaries (AC1–AC8, Phase G0 increment 1, monitor Phase 1, Steps 50–58)
  removed from the backlog — all were already fully recorded in
  `docs/40_history/00_completed_development.md`.
- `docs/30_future/02_static_aero_zaero_review.md` archived to `docs/40_history/archive/`
  (all 8 goals actioned via now-closed steps); `docs/00_INDEX.md` updated.
- **Completed-development record split by area (2026-07-05):**
  `docs/40_history/00_completed_development.md` (4500+ lines) split into seven area files —
  `01_program_foundation.md`, `02_sol101_static.md`, `03_sol103_modal.md`,
  `04_viewer_gui.md`, `05_aero_vlm_spline.md`, `06_sol144_static_aeroelastic.md`,
  `07_maneuver_transient.md` — with `00_completed_development.md` retained as the index
  (file map, defect-ID legend, principles). All 130+ step/defect entries carried over
  verbatim (verified by heading diff). `CLAUDE.md` step-completion rule, `docs/00_INDEX.md`,
  and the release-process doc updated to point at the area files.
- **H1 (2026-07-05):** `docs/30_future/01_static_aero_plan.md` pruned per its own
  self-removal rule — the closed Step 39–58 bodies (duplicated in `40_history`) replaced by
  a one-line delivered-step map, and the Phase D/E/F/G0/G placeholders retired in favour of
  `designs/dlm_rfa_flutter_gust.md` + the backlog. Retained as a compact architecture
  reference (layer diagram, matrix nomenclature, as-built module map, references,
  validation-case index).

### Fixed

**High-q flexible-coupling fidelity (AE14) — Step AC7 (2026-07-05)**

- **HA144A full-span deck: fuselage PBAR doubled** — the mirror of the MSC half-span deck
  had doubled the centreline masses but not the centreline fuselage stiffness, so the
  full-span fuselage (carrying both wings) flexed ×2. This drove most of the 5–28% q=1200
  restrained-derivative errors, the wrong-signed rate-column increments, **and the entire
  AE8a "accepted trim bias"** (superseded: q=40 trim now matches NASTRAN Listing 7-2 to 5
  digits, ANGLEA 0.16918 vs 1.6919E-1).
- **SPLINE2 rewritten as the NASTRAN infinite beam spline** (MSC Aeroelastic UG
  Eqs. 2-48…2-63), replacing the cubic Hermite: spline axis = CID **y-axis** (MSC
  convention), rigid chord arms (off-axis SET1 grids legal; the EA-collinearity
  restriction is gone), `DTOR = EI/GJ` now used, `DZ`/`DTHX`/`DTHY` as attachment
  flexibilities (0 = rigid, > 0 = spring, negative = detached; field `dthz` renamed
  `dthy` per the MSC card). Fixes the canard chordwise-camber contamination and the
  missing twist-gradient term; rigid-body modes exact by construction. The HA144A deck's
  MSC SPLINE2/SET1/CORD2R card values are restored verbatim; `val_dihedral_trim.bdf` and
  the cantilever test deck converted to the new convention.
- **Result:** q=40 restrained columns all ≤0.20%; q=1200 CZα/CZq/CMq gated live (≤2/2.5%,
  restrained and unrestrained). The remaining moment/ELEV residual (3–5%, wing-root TE
  boxes behind the canard — steady-VLM vs k→0-DLM interference) is documented and
  re-scoped as backlog Step AC8/AE15. q_div sentinel re-pinned 4034 → 3809.8.

### Added

**CFD/wind-tunnel steady-pressure injection (CHORDCP) — Step 54 / AC6 (2026-07-05)**

- **New `CHORDCP` card** (sbeam extension): per-box physical steady Cp of a CAERO1 at a
  required reference AOA (ALPHREF, degrees; optional data MACH). When present, the SOL 144
  mean flow is the injected CFD/test distribution instead of the program-computed W2GJ
  baseline, and the trim perturbs about the measured operating point with an **absolute**
  solved ANGLEA.
- **Equivalent-normalwash substitution** at assembly (`corrections.apply_chordcp` +
  `aero_model._apply_chordcp_injection`): min-norm solve of the corrected wash→ΔCp
  operator over the VLM sub-block with `+ n_z·α_ref` re-referencing; composes with
  WKK/WT1/WT2 corrections and PSTRIP strip panels (strips keep their wash); dead-row
  (unreproducible) injected Cp raises. No solver load-path changes — all consumers
  (trim, maneuver, monitor points, viewer) pick the injection up through `aero.wg`.
- **v1 coverage rule:** every VLM CAERO1 needs exactly one card, one shared ALPHREF;
  KC7 validation and warnings (Mach mismatch, trimmed AOA > 2° from ALPHREF, W2GJ
  discard); `mirror_halfspan` rejects the card; f06 gains an `INJECTED OPERATING POINT`
  echo block; viewer flags active injection and blocks correction derivation on
  CHORDCP decks. Identity/scaling/integral acceptance gates in
  `tests/aero/test_chordcp.py`; docs: card reference, `05_aeroelastics.md`, theory §3.4
  (Eq. 13′). Partial coverage + viewer authoring recorded as backlog follow-ons.

**GUI — small viewer gaps closed — Step AC5 (2026-07-05)**

- **Maneuver exports in the viewer** — the transient-maneuver results view gained download
  buttons for the MLDPRNT ASCII time-history (`<stem>.mldprnt.txt`) and the critical-sample
  net-load BDF (`<stem>.maneuver_qs_loads.bdf`), built in-memory from the same
  `results/maneuver_output.py` builders the CLI uses (byte-identical content per subcase).
- **F06 transient-maneuver block** — new `build_f06_sol144_maneuver_text` (run summary,
  per-output-time MANEUVER TIME HISTORY table with the critical sample marked,
  critical-sample closure/displacement/CBAR detail), wired into **both** the viewer f06
  export and the CLI `.f06` (no maneuver f06 block existed anywhere before).
- **All six aerodynamic trim totals** — `sol144.py` now computes and stores total CY, CMx
  (roll), and CMz (yaw) (full 3-component `aero_moment_resultant` about the RCSID origin)
  alongside CZ/CX/CMy/CL_wind; shown as a second metrics row in the viewer trim view and
  added to the f06 AERODYNAMIC TOTALS block. (The backlog's "already computed" claim was
  wrong — these were new solver outputs.)
- **Body panels visually distinct** — `build_aero_box_figure(..., body_eids=)` draws body
  boxes as a separate purple "Body panels" legend trace: PSTRIP strip bodies automatically
  (`AeroBox.is_strip`), cruciform bodies via the EIDs remembered in
  `st.session_state.aero_body_eids` when the Aero Correction tab builds a body correction.
- **Bulk-aware SOL 144 run summary** — the pre-solve Planned-Analysis line now advertises
  hinge moments (AESURF), monitor loads (MONPNT1/3), aero totals, and the maneuver exports.
- **MLOADS sample deck** — `sample/ha144a_fullspan_mloads.bdf` (static trim subcase + an
  ELEV-ramp quasi-steady pitch-up MLOADS subcase); none existed before.
- **Docs** — `06_viewer.md` executive-control/SOL 144 run-path reconcile + all new UI
  documented; `05_aeroelastics.md`/`CLAUDE.md` output lists updated.
- **Tests** — f06 maneuver-block unit tests, trim-totals gates (lateral totals vanish on
  the symmetric HA144A; CY cross-checked per-box), body-panel trace-split tests, summary
  tests, and AppTest Flow D (MLOADS deck end-to-end in the viewer). Suite: 1075 passed.

**Wing-root interference residual investigated and accepted (AE15) — Step AC8 (2026-07-05)**

- Study A2 (`docs/20_theory/studies/a2_wing_root_interference.md`) closes the residual
  re-scoped from AC7: sbeam's VLM implementation is **exonerated** by an independent
  cross-check (DLR PanelAero substituted through the full SOL 144 chain agrees to 1.6e-8
  at operator level and to 4+ decimals on every derivative column); the q=1200
  moment/ELEV residual (2.9–5.3%) is attributed to a canard-wake/wing-root interference
  **discretization** difference — MSC's steady AIC is near-mesh-converged on the coarse
  8×4 mesh where a horseshoe VLM is not (sbeam at NCHORD=8–12 matches NASTRAN's
  coarse-mesh values to ~0.5–2.3%; strip-level confirmation at the pinned Listing 7-2
  trim state). Residual ACCEPTED; the six q=1200 gates stay xfail citing the study.
  No product code changed. Modeling guidance: align upstream/downstream spanwise
  breakpoints (misaligned canard staggers corrupt even rigid derivatives ±135–295%);
  use NCHORD ≥ 8 on wake-washed surfaces.

**SPLINE9 design proposal (2026-07-05)**

- **`docs/30_future/designs/spline9_hermite_beam_spline.md`** — design proposal for an
  sbeam-extension FE-consistent cubic-Hermite beam spline as an opt-in alternative to the
  NASTRAN infinite beam spline (SPLINE2 since AC7), rebuilt on the current conventions
  with the AC7-found twist-gradient defect fixed. Includes a convergence-study go/no-go
  gate to be run before any implementation. Indexed in `docs/00_INDEX.md`; summarized
  under "Future development" in the backlog.

**Minor solver warnings + cosine chordwise spacing — AE12/A7/A8 / Step AC4 (2026-07-05)**

- **SPLINE2 DTOR/DTHZ warnings (AE12)** — `build_g_spline` now warns when a SPLINE2 card carries
  a value the beam spline ignores: `DTOR ≠ 1.0`, or `DTHZ` outside {0.0, −1.0} (−1.0 is NASTRAN's
  "Rz detached", which matches sbeam's behaviour and stays silent — the HA144A decks run
  warning-free). The misidentified PG-normal half is closed with a guard-test pair
  (`TestPrandtlGlauertNormalCopy`) locking in that the normal copy is exact for all `mesh_caero1`
  output. Side finding: the HA144A cards carry only the benign detached values, exonerating AE12
  as the prime suspect for the AE14 high-q coupling gap (backlog AC7 suspect list updated).
- **`panel.cosine_chord_fractions(n)` (A7)** — LE-concentrated half-cosine chordwise breakpoints
  for AEFACT/LCHORD use (opt-in; uniform NCHORD meshing unchanged for NASTRAN fidelity), plus a
  pre-solve `build_aero_model` warning when a VLM CAERO1 has fewer than 4 chordwise boxes.
- **Box aspect-ratio warning (A8)** — pre-solve warning (one per CAERO1) when any box AR
  (spanwise/streamwise edge) falls outside [0.5, 2.0], reporting count and worst AR. PSTRIP strip
  body panels are exempt from both A7/A8 checks. 16 new tests; suite 1053 passed / 6 xfailed.

**Theory tutorial: aeroelastic stability derivatives (2026-07-05)**

- **`docs/20_theory/aeroelastic_derivatives.md`** — new-engineer-level tutorial on the three SOL 144
  derivative columns (rigid / elastic-restrained / elastic-unrestrained mean-axis) as implemented in
  sbeam (MSC Nastran algorithms), plus the equivalent ZAERO Ch. 12 modal formulation, the HA144A
  worked numbers, and the two documented wrong turns. Indexed in `docs/00_INDEX.md`; cross-linked
  from `01_aeroelastics_theory.md` §5.4.

**Unrestrained (mean-axis) stability derivatives — AE8b / Step AC2 (2026-07-05)**

- **`sol144._compute_unrestrained_derivs`** — the missing UNRESTRAINED derivative column, a literal
  implementation of the MSC SOL 144 mean-axis / inertia-relief algorithm (MSC Aeroelastic Analysis
  User's Guide Eqs. 2-111…2-134, sourced into `.refs/`; DMAP names kept in comments). Validated at
  q=40 against Table 7-1 (all six longitudinal derivatives within 1%, W2GJ intercepts within 1%)
  and proven operator-correct at both q by an independent ZAERO Ch. 12 modal mean-axis cross-check
  (agreement to 4+ decimals). New `Sol144TrimResult.unrestrained_derivs` / `.unrestrained_intercepts`;
  f06 gains the ELASTIC UNRESTRAINED column block + intercepts line; the viewer derivative table
  gains the unrestrained columns. V-AE1e restrained columns completed against Table 7-1 q=40.
  The q=1200 gates are XFAILed pending the NEW backlog item AC7/AE14 (high-q flexible-coupling
  fidelity: restrained q=1200 columns are independently 5–28% off — the coupling, not the operator).

### Fixed

**W2GJ sign convention inverted vs NASTRAN — AE8a root cause / Step AC3 (2026-07-05)**

- **`integration.build_wg`** now negates W2GJ card data into the internal washout-positive
  normalwash: card values follow the NASTRAN convention (positive = nose-up incidence, like ANGLEA
  — MSC Eq. 2-104 / HA144A "+0.001745 rad = +0.1 deg wing incidence"); sbeam previously applied
  deck incidence backwards. W2GJ **writers** (`section_correction`, both `body_correction`
  emitters) flipped to match, so generated cards stay NASTRAN-convention and round-trip. With the
  fix, sbeam's rigid intercepts match Table 7-1 to 4 sig figs (CZ0 +0.008419 vs +0.008421,
  CM0 −0.006007 vs −0.006008). The HA144A trim offset becomes −0.093° ANGLEA / +0.104° ELEV
  (≤0.31% FS, q-invariant) and is documented as the accepted residual bias.

**Decoupled strip body panels (Step A10, 2026-06-15)**

- **New panel type — `PSTRIP` + `STRIPK` cards** (`model/aero.py`, `parser/bdf_reader.py`): a CAERO1
  whose PID references a `PSTRIP` (instead of a `PAERO1`) is a **decoupled strip body panel** — no
  horseshoe vortex, no wake, and **no AIC coupling** to or from any other box. Its block of the ΔCp
  operator is **diagonal** (`ΔCp = slope·(α·n_z + β·n_y + Δα)`, operator diagonal `-slope/β`), so it
  **cannot contaminate** the lifting surfaces (their inverse is bit-identical with or without the
  strip, even overlapping it) and carries no interference/fence effect — a pure load device. `PSTRIP`
  sets the nominal per-box slope (default π — half the 2π flat plate, "50% normal surface"); `STRIPK`
  overrides it per box. This is the clean resolution of the cruciform's authority-equals-contamination
  limit (theory §3.7).
- **`sbeam/aero/strip.py`** — `is_strip_caero`, `strip_box_mask`, `strip_box_slopes`; `build_aero_model`
  excludes strip boxes from the VLM AIC inversion and scatters the diagonal strip block into
  `ajj_inv_corr` (refactored the operator assembly into `_assemble_vlm_operator`). `AeroBox` gains an
  `is_strip` flag; `solve_rigid_cl`'s raw (no-operator) path rejects strip decks.
- **`build_strip_body_correction`** (`body_correction.py`) — strip analogue of `build_body_correction`:
  sets per-box slope (`STRIPK`) and Δα (`W2GJ`) so the total airplane Cm_α/Cm0, Cn_β/Cn0, Cl_β/Cl0 hit
  targets, contamination-free with no WT2-ratio conditioning concern. `strip_body_cards_to_bdf`
  formatter. Aero Correction Stage 6 auto-detects panel kind (PSTRIP → strip / PAERO1 → cruciform) and
  routes to the matching builder (`viewer/aero_correction_view.py`).
- **Sample** `sample/cessna210_strip.bdf` (strip variant of the cruciform deck) and **tests**
  `tests/aero/test_strip_body.py` (parser round-trip; diagonal/zero-coupling operator; exact
  decoupling and overlap-harmless; π-slope ⇒ sectional cl_α=π; correction hits all six targets to
  machine precision on a full rebuild).

**Multi-surface body planes (2026-06-15)**

- **`sbeam/aero/body_correction.py`** — `build_body_correction` now accepts a **list of EIDs** (as well
  as a single `int`, backward compatible) for `horiz_eid` / `vert_eid`, so a body plane can be defined
  by several CAERO1s — e.g. a fuselage side split into a panel by the wing, one running to the fin TE,
  and one for the lower body. All listed panels are tuned by **one** joint min-norm solve over every
  body box (the per-box weights already route each box to pitch / yaw / roll by its normal), and each
  panel emits its own `(W2gj, Aecorr)` pair. Distributing a plane across more boxes gives the solve
  more freedom and generally **lowers** `ratio_max` (e.g. the Cessna body dropped ~93→~32 split across
  4 panels). New `_as_eid_list` helper; verified to machine precision on a 1-horizontal + 3-vertical
  body.
- **Aero Correction tab** — the horizontal / vertical body-panel pickers are now `st.multiselect`
  (`viewer/aero_correction_view.py`), so a plane can be built from several panels in the UI; defaults
  to the auto-guessed surfaces.
- **Tests** — `test_eid_int_and_singleton_list_equivalent` (int ≡ one-element list) and
  `test_multi_surface_body_plane` (a 2-panel vertical body hits all targets, one card pair per panel)
  in `tests/aero/test_body_correction.py`; the viewer test asserts the pickers are multiselects.

**Cruciform body panels — total-aircraft moment correction (Step A9, 2026-06-14)**

- **`sbeam/aero/body_correction.py`** — represent the fuselage (sbeam has no body element) with a
  cruciform of two flat VLM `CAERO1` surfaces (horizontal +Z, vertical +Y) and tune them so the
  **total airplane** matches CFD / wind tunnel after the flying surfaces are matched to section data:
  Cm_α, Cm0 (pitch, horizontal panel) and the full sideslip set Cn_β, Cn0, Cl_β, Cl0 (yaw + roll,
  vertical panel). `build_body_correction` is a **direct, exact, non-iterative** linear solve: a
  joint minimum-norm WT2 per-box-ratio solve over the body boxes sets the slopes (decoupled from the
  flying surfaces — `diag(r)·A⁻¹`; the roll metric `Cl_β` couples to both panels via the `y·n_z`
  arm, so all slope constraints are solved together), then a joint minimum-norm W2GJ solve against
  the actual corrected operator sets the offsets (accounting for the body camber's induced load on
  the wing). Moment-primary — the body's lift/side-force is a minimum-norm by-product. Exposes
  `BodyTargets`, `split_total_rows` / `parse_body_targets` (CSV `TOTAL` block: `cm_a`→Cm_α,
  `cm0`→Cm0, `cn_a`→Cn_β, `a0`→Cn0, optional `cl_a`→Cl_β, `cl0`→Cl0), and `body_cards_to_bdf`.
- **Aero Correction tab — Stage 6 "Body panels — total-aircraft moment match"**
  (`viewer/aero_correction_view.py`): auto-guesses the horizontal/vertical body panels, seeds the
  six targets (Cm_α/Cm0, Cn_β/Cn0, Cl_β/Cl0) from the CSV `TOTAL` block, builds + shows a
  baseline/target/achieved/residual table with the max body WT2 ratio, and applies the flying + body
  card pairs (body SIDs 9301/9401) or downloads them. `build_body_correction` gains an `aero=`
  argument so the page reuses one AIC build.
- **Refined Cessna 210 sample** — `sample/cessna210_body.bdf` adds the cruciform body panels
  (`CAERO1` 400 horizontal 2×8, 500 vertical 4×8 — the spanwise z-resolution gives the roll
  authority — `SPLINE0` zero structural coupling) and **fixes the empennage so the vertical tail
  intersects the horizontal tail** (VTP root extended from z=0.80 down to z=0.60, crossing the HTP
  plane at z=0.70). Companion `cessna210_body_section_data.csv` carries the flying-surface section
  rows plus a `TOTAL` block (with the optional `cl_a`/`cl0` roll columns).
- Tests: `tests/aero/test_body_correction.py`, `tests/aero/test_cessna210_body_example.py`, and
  Stage-6 coverage in `tests/viewer/test_aero_correction_view.py`.

**Aero tab — corrected / uncorrected / Δ rigid-derivative table (A-GUI5, 2026-06-14)**

- The Aero-tab **Rigid stability & control derivatives** table gains a **Values** radio
  (Corrected / Uncorrected / **Δ (corr − uncorr)**), replacing the former Aero/Raw **Naming**
  toggle (the raw SOL 144 names stay available via `rigid_derivative_table(..., naming="raw")`
  for f06 cross-checks, just not as a UI control). The radio appears only when a correction card
  is present (an uncorrected baseline exists); otherwise the corrected table shows alone.
- `rigid_derivative_table` gains a `state` argument; the uncorrected operator is rebuilt by the new
  `aero_view._uncorrected_cp_operator` (inverts the stored raw `aero_model.ajj`, re-applies the
  Göthert `1/β` and Γ→ΔCp `2/chord` scaling — the no-correction branch of `build_aero_model` — and
  swaps it in via `dataclasses.replace`), so the same `_compute_rigid_derivs` machinery produces the
  uncorrected and difference matrices.

**Aero Correction page — α/β split, cp comparison, 5-sig-fig formatting, full corrected-BDF export (A-GUI4, 2026-06-14)**

- **Separate α and β operating points.** The Aero Correction build condition now takes two angles
  (Operating α / β); each surface is corrected on the one axis given by its table `var`
  (`section_data.surface_var`; ALPHA→α, BETA→β; `incidence_deg` kept as a single-axis fallback).
  A surface carrying both axes (`MIXED`) is skipped. `build_from_section_data_multi` gains
  `alpha_deg`/`beta_deg`.
- **Canted-surface warning.** `aero_view.surface_dihedral_deg` computes each surface's |Γ|; the build
  status table shows it and warns when `20° ≤ Γ ≤ 70°` (a single-axis section correction blends α/β).
- **Preview no longer vanishes** when switching the Preview surface — the CSV upload is re-parsed only
  when the file actually changes (upload-id guard), instead of resetting the build on every rerun;
  the preview chart also carries a stable key.
- **Aero tab Cp view toggle** — Corrected / Uncorrected / **Δ (corr − uncorr)** drives both the 3D
  box-pressure mesh (Δ uses a zero-centred diverging scale, **ΔCp** colour bar) and the span-load
  curves (`build_span_loading_figure(..., mode=)`; `build_aero_box_figure(..., cp_cmid=, cp_title=)`).
- **Span-load per-surface show/hide** — a **Show surfaces** multiselect (default all, multi-select)
  thins a busy multi-surface span-loading plot via `build_span_loading_figure(..., surfaces=)`; each
  surface keeps a fixed colour so hiding one does not recolour the others.
- **Full corrected BDF export.** `build_corrected_bdf` splices the W2GJ/AECORR cards into the uploaded
  model text (before `ENDDATA`) with a provenance header (source CSV, date, Mach/α/β, corrected
  CAEROs) — a self-contained, re-parseable model. Editable filename defaults to
  `suggest_corrected_name` (`<stem>_M0p30_A2p0_B0p0.bdf`); build one per Mach. (A separate
  correction file + `INCLUDE` is not used: sbeam's parser honours only a single whole-bulk INCLUDE.)
- **5-significant-figure formatting across all viewer tables/metrics** via new
  `viewer/format_utils.py` (`fmt` — decimal down to exp −4, uppercase `E` below; `fmt_mass` — 0.1-unit
  masses; `style_numeric` — Styler for float columns). Applied to the model-data tabs, GPWG, item
  inspector, SOL 101/103/144 result tables and metrics, the rigid-derivative and per-surface tables,
  and the Aero/Aero-Correction Plotly hovers/ticks (`.5~g`).

**Aero — genuine wind-axis CL/CD reported alongside body-axis CZ (2026-06-14)**

- `solve_rigid_cl` (`sbeam/aero/vlm.py`) now returns, in addition to the existing body-axis force
  coefficient (`CL` ≡ new explicit `CZ`): `CX` (body streamwise), `CL_wind` (wind-axis lift
  `CZ·cosα − CX·sinα`), and `CD_wind` (wind-axis drag = Trefftz `CDi`). The wind-axis lift is the
  force ⊥ to U∞ and equals `CZ` only at α≈0; the existing `CL` key keeps its body-axis meaning so
  the α-linearity / AoA-equivalence / parallel-axis-CM identities (and all existing tests) are
  unchanged. Because a surface-normal-pressure VLM has no leading-edge suction, `CX≈0` and the
  near-field drag is unreliable — so `CD_wind` is the far-field Trefftz value, not the near-field
  projection.
- SOL 144 trim (`sbeam/solver/sol144.py`, `Sol144TrimResult`): new `total_cx` and `total_cl_wind`
  (`CZ·cosα − CX·sinα` at the trimmed α). `total_cl` is unchanged (body-axis CZ; balances weight).
- Viewer: the Aero tab shows **CL (wind)**, **CD (induced)**, **CZ (body)**, CY, CM with an
  axis-convention caption; the per-surface table is labelled body-axis (CZ). The SOL 144 trim
  summary shows **CZ (body)** and **CL (wind)**. f06 "AERODYNAMIC TOTALS" prints
  `TOTAL CZ (BODY)` and `TOTAL CL (WIND)`; the trimmed-loads BDF export comment says `CZ=`.
- Tests: `tests/aero/test_vlm.py` — new wind-axis cases (CZ alias, CX≈0 on a planar wing,
  `CL_wind = CZ·cosα − CX·sinα < CZ`, `CD_wind == CDi`). Docs: theory §5.4, 05_aeroelastics.md,
  06_viewer.md.

**Viewer — Aero Correction tab: build correction cards from CFD/test section data (2026-06-14)**

- New `sbeam/viewer/aero_correction_view.py` (`render_aero_correction_tab`) + a new **Aero
  Correction** tab (right of **Aero**, shown when the deck has CAERO1s). Front end over the
  existing `section_data` / `section_correction` engine — no solver/engine changes.
- Workflow: download a mesh-seeded CSV template → fill with section coefficients → upload
  (validated inline) → pick a **condition** (exact-match Mach + operating incidence) → **Build
  correction cards** (`build_from_section_data_multi`, reserved SIDs 9001/9101) with per-surface
  region coverage (`operating_region`) and extrapolation/skip warnings → preview input-vs-achieved
  (`build_section_correction_figure`) + per-strip diagnostics → **Apply to model** or **Download
  cards (.bdf)**.
- **Apply to model** injects the `(W2gj, Aecorr)` pairs into `bulk.w2gjs` / `bulk.aecorrs` and
  nulls the Aero-tab results so the existing Aero tab runs the corrected solve; re-applies replace
  the tool's own previously-injected SIDs (tracked in `aero_corr_sids`) rather than stacking.
  Warns on a pre-existing WKK (WKK precedence shadows WT2) or a non-generated WT2 on a corrected
  surface. **Download cards (.bdf)** emits the same pairs via `cards_to_bdf`.
- New session keys (reset on upload): `aero_corr_model`, `aero_corr_df`, `aero_corr_result`,
  `aero_corr_sids`.
- Tests: new `tests/viewer/test_aero_correction_view.py` (5) — template CSV schema round-trip;
  build→inject→rebuild corrected-CL hits the prescribed section slope; AppTest renders, Build
  button appears with a table, Apply injects cards and a re-apply does not stack.
- Docs: `06_viewer.md` new "Aero Correction Tab" section + module-map row + test table;
  `05_aeroelastics.md` "Aero Correction page" paragraph.

**Aero — section force + moment correction synthesiser (2026-06-14)**

- New `sbeam/aero/section_correction.py`: `build_section_correction(...)` generates a
  **W2GJ + WT2 (AECORR) card pair** that reproduces a target *section line* per span strip —
  force slope, moment slope (i.e. aerodynamic centre), zero-α lift offset (α₀/camber), and
  zero-α pitching moment (Cm0) — with **minimal change** to the uncorrected chordwise load.
  `cards_to_bdf()` formats the pair as bulk data. This fills the gap that `apply_wt1` (per-strip
  force only, cannot move the a.c. or produce load at α=0) cannot.
- Decomposition: the slope pair (dF/dα, dM/dα) → per-box **WT2** (reshapes the α-driven chordwise
  load to set force slope + a.c.); the offset pair (F₀, M₀) → **W2GJ** camber line (the load at
  α=0). The WT2 ratio is calibrated on the unit-incidence reference and is independent of `wg`, so
  the build is one decoupled pass (WT2 first, then W2GJ through the corrected operator). WT2 is a
  uniform per-strip scale (no shape change) plus a minimum-norm perturbation orthogonal to the
  force for the a.c. mismatch — it degenerates exactly to the uniform WT1 scaling when the target
  a.c. equals the VLM a.c.
- Guards: single CAERO1 only (matches the existing full-length WT2 target path); NCHORD ≥ 2 per
  strip (a moment needs two chordwise boxes). Emitted WT2 target is in Γ-units and mirrors
  `apply_wt2`'s near-zero-reference guard, so the card and the solver operator are identical.
- Tests: new `tests/aero/test_section_correction.py` (8 tests) — no-op identity; uniform-r pure
  slope scaling; full (slope/a.c./α₀/Cm0) match verified both in the diagnostics and end-to-end
  through `build_aero_model`; NCHORD<2 / multi-surface / length-mismatch guards; BDF round-trip.
- Docs: theory §3.5 (synthesis method) + §3.3 WT1 clarification; standard-doc section, module-map
  row, and clarified `apply_wt1` entry.

**Viewer — Aero tab honours AIC corrections; section-correction preview plots (2026-06-14)**

- `solve_rigid_cl` (`aero/vlm.py`) gains an optional `cp_operator` argument (the corrected
  ΔCp operator `AeroModel.ajj_inv_corr`). When supplied, `ΔCp = cp_operator @ rhs` directly,
  so any AIC correction (WKK / WT1 / WT2) **and** the baked-in Prandtl–Glauert factor are
  honoured — the same operator SOL 144 uses. With no correction the result is numerically
  identical to the prior build-and-solve path (verified). `mach` is then ignored (β baked in).
- The viewer **Aero tab** (`viewer/app.py`) now passes `cp_operator=aero_model.ajj_inv_corr`, so
  a deck with WKK/WT1/WT2 (e.g. the section force+moment correction) shows the corrected CL / CM /
  cp / section loads — previously only the W2GJ camber was reflected. A caption flags which
  correction method is active.
- New `viewer/aero_view.build_section_correction_figure(boxes, df, data_result, caero_eid)`:
  spanwise preview for the section-correction page — section force-slope `cn_α(η)` and zero-α
  moment `cm0(η)`, overlaying the user input (markers at the table η-stations) with the achieved
  correction recovered on the mesh strips (line), so interpolation/end-clamping is visible.
- Tests: `test_corrections.py` `TestSolveRigidClCorrectedOperator` (identity with no correction;
  WKK=1.5 scales CL by 1/1.5; shape guard); `test_cessna210_example.py` preview-figure trace +
  achieved-vs-input check. Pre-existing lint debt in `test_corrections.py` cleaned up.

**Viewer — Aero tab: rigid S&C derivative table, uncorrected-vs-corrected span loading (2026-06-14)**

- The Aero tab's coefficient output is now a **full-width** panel below the 3D view instead of
  being crammed into the narrow control column.
- New `viewer/aero_view.rigid_derivative_table(aero_model, bulk, naming)`: the **full rigid
  stability & control derivative matrix** (rows ANGLEA/SIDES/ROLL/PITCH/YAW + AESURF controls;
  columns the six force/moment coefficients per radian/label). Reuses the SOL 144 machinery
  (`build_djx` + `_compute_rigid_derivs`, rigid `u_a = 0`) so it matches the f06 rigid derivatives
  with no trim/structure solve. A **Naming** toggle switches conventional aero symbols
  (CL/CY/Cl/Cm/Cn/CX) ↔ raw SOL 144 names (CZ/CY/CMX/CMY/CMZ/CX).
- New `viewer/aero_view.build_span_loading_figure(boxes, cp_corr, cp_unc, aeros)`: per-CAERO1
  spanwise **section normal force `cn(η)` and moment `cm(η)`** (about each strip's local ¼-chord),
  as **line** plots — one line per surface, grouped by `(caero_eid, i_span)`. This fixes the old
  single-bar strip that merged strips sharing an `i_span` across surfaces and showed force only.
  When a correction card is present the **uncorrected** baseline is overlaid dashed.
- `viewer/app.py` `_render_aero_tab`: also solves the uncorrected baseline
  (`cp_operator=None, mach=aero_model.mach`) when a correction card exists (new `aero_result_unc`
  session key); renders the span figure + derivative table + per-surface table full-width.
- `build_aero_box_figure` gains `strip: bool = True`; the Aero tab passes `strip=False`
  (scene-only). SOL 144 results view and existing crash tests use the default — unchanged.
- Tests: `test_aero_view.py` (+6 — derivative-table shape/naming/cross-check/AESURF rows/None,
  span figure single & multi-surface, scene-only figure); `test_cessna210_example.py` (+1 — rigid
  CLα ≈ 5.2/rad and 5-surface span figure). Suite 429 → 437.

**Sample — Cessna 210-like VLM aero model + section-correction example (2026-06-14)**

- `sample/cessna210_aero.bdf`: a full-span, 5-surface VLM model (wing + HTP + VTP, both
  halves explicit; SI units) of a Cessna 210-like GA aircraft (span 11.2 m, MAC 1.47 m, area
  16.24 m², 1.5° dihedral high wing), with a light coherent stick structure so it is a complete,
  viewable SOL 101 deck. 324 boxes (NCHORD=6).
- `sample/cessna210_section_data.csv`: per-surface section coefficients driving the multi-surface
  W2GJ+WT2 correction — wing (NACA 64-415-like) with **two α-regions** (pre/post-onset), symmetric
  HTP, and a `BETA` VTP. Demonstrates `section_data.build_from_section_data_multi`.
- `tests/aero/test_cessna210_example.py` (3 tests): the deck meshes to 5 surfaces / 324 boxes; the
  multi build corrects all surfaces (wing per-strip slope reproduces cn_a, wing carries a camber
  moment, HTP does not); and through the corrected operator the WT2 slope (~0.091→>0.11 /deg) and
  the W2GJ camber (CL(0)>0.2) both take effect.
- Note: with the Aero-tab corrected-operator wiring (above), the viewer now reflects the **full**
  correction (W2GJ camber + WT2 slope/a.c.); load the deck plus the generated correction cards and
  press Compute Aero to see the corrected CLα and span loading.

**Aero — section force+moment correction extended to multi-surface (2026-06-14)**

- `section_correction.py` gains `build_section_correction_multi(boxes, ajj, targets, *,
  sid_w2gj_base, sid_aecorr_base, beta=1.0)` — corrects any number of CAERO1 surfaces in one
  global build, emitting a `W2GJ`+`WT2` card pair **per surface**. The AIC is global, so the WT2
  ratio is a per-box vector (1 on uncorrected boxes) and the W2GJ camber offset is **one global
  linear solve** over all corrected strips (camber on one surface induces load on the others).
  `build_section_correction` is now a thin single-surface wrapper; `cards_to_bdf` accepts either
  result. New `SurfaceTargets` / `MultiSectionCorrectionResult` / `SurfaceDiagnostics`.
- `aero_model.build_aero_model`: the WT2 branch now **combines all `WT2` `AECORR` cards** into one
  global Γ-unit target (each card fills its own surface's boxes; uncorrected surfaces default to
  ratio 1) instead of using only the primary CAERO1's card. `W2GJ` was already accumulated per
  surface; `WKK`/`WT1` still act on the primary CAERO1. Backward compatible: a single WT2 card on a
  single-surface deck is unchanged.
- **Prandtl–Glauert fix:** the builder now takes the raw `ajj_pg` plus an explicit `beta=√(1−M²)`
  and applies 1/β only to the *physical* force, keeping the emitted WT2 target in pure Γ-units.
  (The earlier "pass β·ajj_pg" convention double-counted β in the card at M>0; M=0 was unaffected.)
- `section_data.py`: `build_from_section_data_multi(boxes, ajj, df, *, mach, incidence_deg, …)`
  corrects every surface in the table at one flight point — per-surface region selection (the
  region containing `incidence_deg`), surfaces with no containing region skipped (`.skipped`).
  Strip geometry is now per-surface; β is derived internally from `mach` (pass the raw `ajj_pg`).
- Tests: +5 (multi-surface engine end-to-end through `build_aero_model`; partial correction leaves
  the other surface at r=1/wg=0; multi-card BDF round-trip; section-data multi build + per-surface
  region selection/skip). Full aero suite 351 passing; ruff clean.

**Aero — spanwise section-data ingestion for the correction GUI (2026-06-14)**

- New `sbeam/aero/section_data.py`: turns a user table of **section coefficients** (a function
  of span, Mach, and a linearised α/β region) into the per-strip dimensional targets and drives
  `build_section_correction`. Tidy/long CSV schema (`caero, eta, mach, var, a_lo, a_hi, cn_a, a0,
  cm_a, cm0, xref`); coefficients are local-chord normalised, per degree, moment about a chord
  fraction `xref` (default ¼c). Functions: `validate_section_data`, `available_conditions`,
  `template_dataframe` (seeds the `st.data_editor` / template download with the strip η stations),
  `build_from_section_data`, `operating_region`.
- Conversion: `f_slope = cn_a·(180/π)·A`, `alpha_0 = a0·π/180`, `m_slope = cm_a·(180/π)·c·A`,
  `m_0 = cm0·c·A`, `moment_ref = LE_x + xref·c` (local chord `c`, strip area `A`). Spanwise values
  are interpolated from the table η-stations onto the mesh strip mid-spans (`AeroBox.span_frac`),
  clamped with an `extrapolated` flag.
- v1 selection: Mach matched exactly (no Mach interpolation); a single operating region built per
  call (the caller warns if the trim incidence leaves `[a_lo, a_hi]`). `ajj` must be the
  PG-consistent AIC at the chosen Mach (`β·ajj_pg`).
- Tests: new `tests/aero/test_section_data.py` (20 total with section_correction) — validation
  guards, condition listing, force/moment coefficient-conversion correctness, end-to-end CL-slope
  match through `build_aero_model`, extrapolation flag, Mach/region selection, operating-region
  helper. Docs: standard-doc "Spanwise section-data input" section + module-map row.

**Viewer — W2GJ baseline incidence folded into the Aero-tab rigid solve (2026-06-14)**

- `solve_rigid_cl` (`aero/vlm.py`) gains an optional `wg` argument (the per-box baseline
  normalwash from W2GJ — camber/twist/built-in incidence). It is added to the flow-tangency
  RHS with the **SOL 144 sign convention** (`rhs = -(α·n_z + β·n_y) + wg`), so a positive
  `wg` (downwash slope) reduces lift, matching the trim solver. `wg=None` (default) is a zero
  vector — identical to the prior rigid-AoA behaviour, so all existing callers are unchanged.
- The viewer Aero tab (`viewer/app.py`) now passes `aero_model.wg`, so decks that differ only
  by a W2GJ twist produce visibly different CL/CM/cp/section loads. A caption flags when a
  non-zero baseline incidence is active. Example: the new `sample/val_wing_taper_dihedral.bdf`
  vs `sample/val_wing_taper_dihedral_twist.bdf` decks (5° dihedral, taper 0.8; the second adds a
  linear 0→−2° washout) now read CL 0.268 → 0.186 at α = 3° in the Aero tab.
- New verification `TestBaselineNormalwashWg` (`tests/aero/test_vlm.py`): `wg=None` ≡ zero
  vector; the AoA-equivalence identity `solve_rigid_cl(α, wg=0) ≡ solve_rigid_cl(0, wg=-α·n_z)`
  that pins the sign; positive `wg` reduces CL; linear washout unloads the tip monotonically;
  shape-mismatch raises.
- Sample decks added: `sample/val_wing_taper_dihedral.bdf` and
  `sample/val_wing_taper_dihedral_twist.bdf`.

**Viewer — Aero tab surface-normal toggle (2026-06-14)**

- New **Show surface normals** checkbox on the Aero tab (`viewer/app.py`,
  `key="aero_show_normals"`). When enabled, `build_aero_box_figure` draws each aero box's
  outward unit normal (`AeroBox.normal`) as a green `go.Cone` arrow rooted at its
  collocation point, scaled to the median box chord, via the new `_add_normal_vectors`
  helper in `viewer/aero_view.py`. Arrows track the deflected mesh when `box_disp` is
  supplied, and toggling re-renders the cached `aero_model` without recomputing the AIC.

**Viewer — SOL 144 results & Case Control rework (Step 57, 2026-06-13)**

The viewer now runs and renders SOL 144 (static aeroelastic trim, divergence sweep, and
Phase G0 transient maneuver loads) — the closing item that surfaces the full SOL 144 chain
in the UI.

- **Run wiring (`viewer/app.py`):** new `_run_sol144` mirrors the `main.py` routing — one
  `AeroModel` + `AeroCache` shared across subcases, dispatching each subcase to
  `run_sol144_trim` / `run_sol144_diverg` / `run_maneuver_qs`. New session keys
  `sol144_result` / `sol144_diverg_result` / `maneuver_result` / `aero_model_144`; the
  Results tab dispatches to the new renderer and the f06 export covers SOL 144 trim + diverg.
  The pre-solve "no SPC" warning no longer misfires on SOL 144 (trim is SUPORT-restrained).
- **Results view (`viewer/results_view.py`):** `render_sol144_results` — trim summary
  metrics (q, Mach, CL, CMy, trim mode), trim-variable table (free/prescribed),
  rigid-vs-elastic stability-derivative table, `q_div` readout, hinge-moment and
  monitor-point integrated-load tables, maneuver-closure resultant, the DIVERG per-Mach
  roots table, and the transient-maneuver time histories with a per-sample deflected shape.
- **Canted, spline-deflected aero mesh (`viewer/aero_view.py`):** `build_aero_box_figure`
  gains an optional `box_disp` arg that rigidly translates each box's corners by the
  spline-interpolated structural displacement (`g_disp @ u_g`). The mesh is drawn from the
  z-bearing box corners, so ±Γ dihedral geometry renders canted in 3-D, never flattened to
  an xy-projection.
- **Case Control page rework (`viewer/case_control_ui.py`):** the tab now leads with a
  SOL-aware, read-only **Planned Analysis** summary (`summarize_case_control` +
  `_SOL_SUMMARY` registry covering SOL 101/103/144 with a generic fallback) and a **Launch
  Analysis** button (via an `on_launch` callback); the subcase editor is demoted behind an
  "Edit case control" toggle. SOL 144 case control is read-only in the editor (launch-only).
- **Tests:** `tests/viewer/test_apptest_integration.py::test_flow_c_sol144_render_and_run`
  loads the ±Γ dihedral deck (`sample/val_dihedral_trim.bdf`), runs the trim, asserts all
  panels render and the cached aero mesh is canted (box-corner z range > 0 — the
  flattening-regression guard); `tests/viewer/test_case_control_summary.py` covers the
  summary registry for SOL 101/103/144.

**SOL 144 — `DIVERG`-card divergence sweep, mode shape & V_div (Step 55, 2026-06-13)**

A `DIVERG` case-control request now drives a full aeroelastic-divergence sweep, generalising
the single critical `q_div` shipped with Step 56.

- **Card (`sbeam/model/aero.py`, `sbeam/parser/bdf_reader.py`):** `DIVERG  SID  NROOTS  RHOREF
  M1 M2 …` — `RHOREF` (sbeam extension, field 4) is the reference density for `V_div`
  (default 0.0 ⇒ omitted); the Mach list moves to field 5+. The `DIVERG=` case-control hook
  already existed.
- **Solver (`sbeam/solver/sol144.py`):** new `run_sol144_diverg` solves the restrained-l-set
  eigenproblem `K_ll φ = q·Q_ll φ` (`_divergence_roots`, dense generalised eig) for the lowest
  `NROOTS` real-positive divergence pressures, sorted ascending, at each card Mach; returns the
  g-set divergence **mode shapes** (max-abs normalised) and `V_div = √(2·q_div/ρ)`. Reuses the
  trim a-set reduction and the multi-Mach `AeroCache`.
- **Results / f06 (`results/results.py`, `results/f06_writer.py`):** `Sol144DivergResult`
  (`DivergMachResult`/`DivergRoot`) and `build_f06_sol144_diverg_text` — per-Mach `AERODYNAMIC
  DIVERGENCE` table (`Q-DIV`, `V-DIV`) plus a mode-shape block per root.
- **CLI (`main.py`):** a SOL 144 subcase with `DIVERG=sid` runs the sweep (with trim when a
  TRIM is also present, standalone otherwise) and appends its f06 block. No TRIM card required.
- **Tests:** `tests/aero/test_step55_diverg.py` — closed-form eigen-core, machine-precision
  agreement of the lowest sweep root with the validated single `q_div` on HA144A, `V_div`
  mapping, mode-shape sizing/normalisation, multi-Mach compressibility, parser, and f06 block.

**Monitor points — `MONPNT1` / `MONPNT3` integrated section loads (2026-06-13)**

Static integrated section loads for the structures/loads handoff from each SOL 144 trim subcase,
replicating NASTRAN `MONPNT1` (aero-only) and `MONPNT3` (aero + inertia + reaction, splined to
structural grids) with sbeam-native RBE3/RBAR pass-through.

- **BDF parsing** (`sbeam/model/aero.py`, `sbeam/parser/bdf_reader.py`): `MONPNT1`, `MONPNT3`,
  `AECOMP` cards (`AELIST` box-collection and `SET1` grid-collection lookup paths) with full
  cross-reference validation. Card layout `MONPNT1/3, NAME, LABEL, AXES, COMP, CP, X, Y, Z`.
- **Integration** (`sbeam/results/monitor_points.py`, new): `integrate_monpnt1` sums the trimmed
  `box_forces` over the AELIST collection; `integrate_monpnt3` sums the g-set `grid_loads` (aero),
  `inertial_loads` (inertia), and recovered SPC/SUPORT reaction over the SET1 grids. Both transform
  to the monitor `cp` frame and apply the AEROS-`SYMXZ` parity factor (single-sourced; 1.0 full-span,
  2.0 + `*WHOLE-AIRPLANE*` annotation for a direct half-model). Reuses vectors already on
  `Sol144TrimResult` and `sol101.recover_reactions` (no `G_kg` re-derivation). Wired into
  `run_sol144_trim`; carried as `Sol144TrimResult.monitor_loads`.
- **Output** (`sbeam/results/f06_writer.py`, `sbeam/results/load_export.py`, `sbeam/main.py`): a
  `MONITOR POINT INTEGRATED LOADS` f06 block and a per-run CSV (`<stem>.monitor_loads.csv`) with the
  six totals plus the diagnostic `Fz_aero/Fz_inertia/Fz_react` breakdown. HDF5 export deferred.
- **Tests:** `tests/parser/test_monitor.py` (7), `tests/results/test_monitor_points.py` (7),
  `tests/results/test_monitor_output.py` (3), `tests/aero/test_monitor_ha144a.py` (V-MON1, 6 —
  whole-aircraft `MONPNT1`==`MONPNT3` spline conservation, `MONPNT3` lift = 1g weight within 1%).
  `sample/ha144a_fullspan_sbeam.bdf` carries the four monitor cards.

**Phase G0 increment 1 — DLM-free quasi-steady transient maneuver loads (2026-06-13)**

A ZAERO `MLOADS`-style **transient** maneuver-loads capability without the DLM: time-integrate the
elastic airframe response to a prescribed (open-loop) pilot-command history from a Step 53
balanced-trim initial condition, recovering the net (aero + inertial) maneuver loads per output time.

- **ZAERO `MLOADS` card set** (`sbeam/model/maneuver.py`, `sbeam/parser/bdf_reader.py`,
  `sbeam/parser/case_control.py`): `MLOADS` (driver), `MLDTRIM` (initial-condition TRIM sid),
  `MLDCOMD` (command label → time history), `MLDTIME` (t0/tend/dt/tout), `MLDPRNT` (ASCII output),
  and the general `TABLED1` tabular function (linear interp, held extrapolation). Selected by an
  `MLOADS = sid` subcase entry under SOL 144; full cross-reference validation.
- **Solver** (`sbeam/solver/maneuver_qs.py`): `run_maneuver_qs` — Level-1 quasi-steady (`Ω×r`),
  open-loop, restrained l-set Newmark-β (β=¼, γ=½) integration of
  `M_ll ü + C_ll u̇ + (K_ll − q·Q_ll) u = f_aero_l + q·Q_ax_l·δ(t) + M_ax_l·a(t)`. The steady VLM is
  re-evaluated at the instantaneous deformation and trim-variable state each step; per-step recovery
  of displacements, CBAR loads, aero box forces, net (aero + inertial) grid loads, and closure.
  Directly integrates the l-set so the steady state equals the Step 53 static load exactly.
- **Output** (`sbeam/results/maneuver_output.py`, `sbeam/main.py`): MLDPRNT ASCII time-history table
  (`<stem>.mldprnt.txt`) and the critical-sample net-load FORCE/MOMENT export
  (`<stem>.maneuver_qs_loads.bdf`).
- **Tests:** `tests/aero/test_maneuver_cards.py` (13 — card round-trip + validation) and
  `tests/aero/test_maneuver_qs.py` (7 — G0→Step 53 machine-precision identity, quasi-static settling
  to the new balanced trim, per-step closure, MLDPRNT + critical-load export round-trips). Full suite
  870 pass.
- **Scope:** increment 1 is open-loop prescribed-kinematics; free-flight rigid-body re-balancing,
  modal reduction (`NMODES`), unsteady corrections (apparent mass / downwash lag / Wagner), and the
  closed-loop control layer are documented Phase G0 follow-ons (`docs/30_future/00_backlog.md`).

**Step 53 — balanced maneuver loads & inertia relief (2026-06-14)**

SOL 144 now emits the net (aero + inertial) grid load for each balanced static maneuver — the
load-generating deliverable for downstream stress and the non-zero inertia column that monitor
points (MON3) will consume.

- **`Sol144TrimResult.net_loads` / `inertial_loads`** (`sbeam/results/results.py`,
  `sbeam/solver/sol144.py`): `inertial_loads = M_ax · a_all` uses the final trim accelerations
  (prescribed AND solved-free URDD), via the new shared helper `_urdd_rcsid_to_basic` (extracted
  from the previously-inline prescribed RCSID→basic transform); `net_loads = grid_loads +
  inertial_loads`. Both reduce to the aero-only / zero case for a 1g determined trim, so existing
  results are unchanged.
- **Closure gate (V-C5 / KC9):** `Sol144TrimResult.maneuver_closure` stores the body-frame
  6-resultant of the net load (`_load_resultant`); a pure free aircraft (SUPORT, no SPC) with a
  non-zero residual raises a `UserWarning` (gravity double-count / mass-model guard).
- **Export:** `build_maneuver_load_cards_text` / `write_maneuver_load_cards`
  (`sbeam/results/load_export.py`) write the net load as FORCE/MOMENT cards to
  `<stem>.maneuver_loads.bdf` (CLI: `sbeam/main.py`). Per-grid emission factored into
  `_emit_force_moment_cards`, shared with the aero-only export.
- **Presets:** `sbeam/model/maneuver_presets.py` — `load_factor_to_urdd3(n_z, g) = −n_z·g` plus
  documented TRIM recipes for pull-up/push-over, steady roll, steady sideslip. Gravity is folded
  into the URDD load factor (NASTRAN convention); no separate `GRAV` term in SOL 144.
- **Tests:** `tests/aero/test_maneuver_loads.py` (V-C5) — full-span HA144A symmetric pull-up:
  net symmetric resultant ≈ 0, lift = `n_z·W`, exact `n_z`-linear `net_loads` + CBAR loads,
  per-grid export round-trip. 850 tests pass.

### Changed

**Step AC1 closed — documentation scrub widened to a full project-documentation review (2026-07-03)**

- **`docs/10_standard/05_aeroelastics.md`** — stale "⚠ Known Defects" table replaced with
  "Validation status & known limitations" (AE1 and AE2–AE10 rows removed as resolved; AE8 split
  into AE8a/AE8b; the blanket "do not use SOL 144 trim results" warning replaced — trim is
  validated and gated at ≤0.4% FS). Stale "Step 52 WIP" section rewritten as CLOSED. Title and
  scope broadened to Phases A–C + G0; supported-cards table and module map completed.
- **R23 closed** — `docs/10_standard/03_static_analysis.md` `recover_bar_forces` signature
  corrected to the per-element 6-arg form.
- **`sbeam/solver/sol144.py`** — `run_sol144_trim` docstring no longer claims over-determined
  trim raises `NotImplementedError` (it is implemented; docstring-only change).
- **README.md** — brought up to current capability: SOL 144 (trim/divergence/monitor points) and
  Phase G0 `MLOADS` in the tagline and Analysis Types; supported-cards table extended to all 51
  parsed cards; new Aeroelastics limitations section; solvers limitation corrected.
- **`docs/10_standard/02_card_reference.md`** — completed against the parser dispatch (51/51
  cards): new Splining (SET1/SPLINE2/ATTACH/SPLINE0/SPLINE1), SUPORT, and Phase G0
  (MLOADS/MLDTRIM/MLDTIME/MLDCOMD/MLDPRNT/TABLED1) sections; case-control table gained
  MLOADS/AEROF/APRES/TRIMOBJ. **RBE2 constraint equation corrected** (full 6×6 lever-arm
  rigid-body matrix, not a direct DOF copy). Ten details ported from the old beam-model card
  tables (CONM2 assembly + singular-mass warning, MAT1 G-derivation, CBAR local-axis pin
  releases, CBUSH rules, CORD2R non-collinearity, GRAV reaction correction, WKK inversion,
  RBE3 limitation, RBE2+CONM2 pattern).
- **`docs/10_standard/01_beam_model.md`** — de-duplicated against the card reference: ~645 lines
  of duplicate per-card field tables removed; now the data-model & parser guide with a compact
  card summary; stale SOL-101/103-only parser claims fixed.
- **`docs/10_standard/00_program_overview.md`** — SOL 144 + MLOADS in purpose/CLI sections
  (incl. the five auxiliary output files); module tree regenerated (17 missing modules);
  version/phase table rewritten to current phase status.
- **`docs/10_standard/06_viewer.md`** — Run-Analysis and F06-Export sections reconciled with the
  SOL 144 viewer code paths; CLI-only exports noted (backlog Step AC5).
- **`docs/00_INDEX.md`** / **CLAUDE.md** — scope descriptions and assembly module list updated.
- Audit outcome: no doc deletions warranted (no orphans, no dangling links); the only merge was
  the 01→02 card-table consolidation. Card fields now live in `02_card_reference.md` only.

**Backlog restructured into the steady-aeroelastic close-out plan; AE13 and A5 closed (2026-07-03)**

- **`docs/30_future/00_backlog.md`** rewritten as the ordered aeroelastic completion plan
  (Steps AC1–AC6): AC1 documentation scrub (stale `05_aeroelastics.md` defect table, R23,
  stale `run_sol144_trim` docstring), AC2 AE8b unrestrained derivatives, AC3 AE8a trim offset,
  AC4 AE12/A7/A8 warnings, AC5 viewer gap close-out (maneuver exports, f06 maneuver block,
  trim CX/CY + roll/yaw totals, body-panel visualization, run-summary string, viewer-doc
  reconcile), AC6 Step 54 CHORDCP (optional). Scope decision recorded: steady-complete only;
  Phase G0 follow-ons and DLM/flutter stay under "Future development"; SOL 144/MLOADS case
  *authoring* UI recorded as a deferred future item (viewer runs/displays SOL 144 but cases
  are authored in the BDF).
- **AE13 (validation gap) CLOSED** — its three planned permanent gates (V-AE1 HA144A acceptance,
  V-AE2 swept-spline rigid-body, V-AE3 coupling-path/rigid-solver cross-check) plus the V-AE1g
  ADA370433 rigid-derivative benchmark are all implemented and green; residual flexible
  unrestrained-derivative coverage rides with AE8b. Moved to
  `docs/40_history/00_completed_development.md`.
- **A5 (aero model viewer-only) CLOSED** — expected-state verdict: SOL 144 CLI dispatch landed
  with AE10/Step 56; SOL 101/103 correctly do not consume the aero model. Moved to
  `docs/40_history`.
- **AE1 validated-trim reference-baseline table** moved from the backlog to `docs/40_history`
  (AE1 itself closed 2026-06-13); closed-narrative blocks (Step 52/53/58 closure summaries,
  "closed in this branch" lists, Phase A/B status paragraphs) removed from the backlog — the
  backlog now carries open items only.

**Cruciform body panels moved clear of the empennage (2026-06-15)**

- **`sample/cessna210_body.bdf`** — the body panels overlapped the empennage: the horizontal panel
  (z=0.60, chord to x=8.00) sat just under the HTP (z=0.70) and the vertical panel (y=0, z=0.10–1.30,
  chord to x=8.00) was **coplanar with the VTP** (also y=0), so body boxes — and their semi-infinite
  +X trailing legs — interpenetrated the tail and dumped a spurious load onto the real surfaces. Both
  panels are now **compact and clear of the tail**: they terminate at x=5.00 (ahead of the VTP LE 6.60
  / HTP LE 6.90), the horizontal panel drops to z=0.30 (below the HTP) and the vertical panel sits
  **wholly below the VTP root** (z=0.05–0.45). Half-spans/heights shrunk to ~0.40 to minimise the
  field they shed on the wing/tail. Box counts (372) and SPLINE0 ranges are unchanged. Measured
  ‖ΔCp‖ contamination of the lifting-surface boxes drops markedly vs the overlapping deck.
- **`sample/cessna210_body_section_data.csv`** — `TOTAL` targets revised from the original
  (Cm_α=−6.9, Cn_β=0.52, Cl_β=−0.24) to a **realistic fuselage increment** over the flying baseline
  (Cm_α=−19.92, Cn_β=0.368, Cl_β=−0.051, ~0 roll). The original targets demanded the fuselage shift
  the neutral point ~3.8 m (≈2.5 MAC) forward — only reachable via the empennage overlap that has now
  been removed; such large body effects belong to a slender-body element (new backlog item).
- **`sbeam/aero/body_correction.py`** — `ratio_max` is documented as a **conditioning gauge, not a
  contamination metric**: WT2 is a post-inverse diagonal on the body rows only, so a large ratio for
  clear-of-tail (weakly-coupled) panels is benign for the lifting surfaces. `_RATIO_WARN` raised
  5 → 200 and its message reworded (the old "add body-panel area/arm" advice is counterproductive —
  bigger/closer panels lower the ratio but raise the contamination; large ratios now point to a
  slender-body element). Module docstring gains a "Geometry, the WT2 ratio, and the cruciform's
  limits" section.
- **Docs** — `docs/10_standard/05_aeroelastics.md` gains a "Geometry & limitations — keep the panels
  clear of the empennage" subsection; `docs/20_theory/01_aeroelastics_theory.md` §3.6 documents the
  key finding (a body panel's *authority to move the total moment* and its *contamination of the real
  surfaces* are the same coupling mechanism, so a clean cruciform can only supply a small increment).
  `docs/30_future/00_backlog.md` adds a **"Body aerodynamic panels (slender body)"** item (Tier 1
  NASTRAN-style slender + interference body recommended) and refines A9-c.
- **Tests** — `tests/aero/test_cessna210_body_example.py` adds `test_body_panels_clear_of_empennage`
  (the panels and their +X wakes must not reach the tail); the `ratio_max < 5` assertions in the body
  tests are replaced by `< _RATIO_WARN` with a note that the ratio is decoupled from contamination;
  the parse/roll-delta assertions track the realistic targets.

**Theory — force/moment conventions consolidated (2026-06-14)**

- New §2.9 "Force and moment conventions (summary)" in
  `docs/20_theory/01_aeroelastics_theory.md`, gathering the previously scattered conventions
  (§2.4 force integration, §2.7 rigid coefficients, §5.4 moment derivatives) into one
  reference. Pins down the three points that are easily conflated: the per-box force is along
  the **panel surface normal** (`S_kj`), **not** the global/body-z axis and **not** the
  wind-axis lift (`C_L`); each force acts at the **local box ¼-chord** (`box.force_point`),
  which is what makes sweep/taper/dihedral arms correct; and moments are taken about a
  **single aircraft reference** (`AEROS RCSID` origin ≈ CG / quarter-MAC), not each strip's
  local ¼-chord — with the hinge-axis and `MONPNT1`/`MONPNT3` exceptions noted. Documents the
  "dihedral enters twice" effect (cosΓ incidence projection plus the tilted force vector /
  side force). Documentation only; no code change. Pointer added from the top "Conventions"
  note.

**W2GJ baseline-normalwash (wg) sign convention unified (2026-06-14)**

The wg sign is now a single canonical convention across docs, tests, and code, closing a
latent inconsistency where a deck authored to the theory doc would have flown flipped aero
loads under SOL 144. Canonical sign (theory §2.4–2.5, `model/aero.py` `W2gj`): wg is a
dimensionless downwash slope Δz/Δx added directly to the assembled normalwash, so **positive
wg = washout = less lift** and a leading-edge-up built-in incidence is **negative**.

- Theory `docs/20_theory/01_aeroelastics_theory.md` §2.4/§2.5 and Eq 9 rewritten (incidence
  and twist terms now carry a minus sign); `W2gj` dataclass and `aero/integration.py`
  (`build_djk`, `build_wg`) docstrings document the sign and why it is opposite to the
  D_jk-mapped incidence sense.
- `tests/aero/test_integration.py` T2/T3 now drive the **production combination**
  (`gamma = solve(Ajj, wg)`, no local `-wg`) with nose-up incidence as a negative wg.
- New end-to-end regression `tests/integration/test_wg_sign_convention.py` pins the sign
  through the real `compute_structural_loads` / `coupling.build_fg` load path on a splined
  cantilever (positive wg → downward Tz; antisymmetric in wg; monotone in a wg sweep).

**AE1 Step F closed — V-AE1d trim acceptance re-framed to %-full-scale (2026-06-13)**

The V-AE1d SC2 acceptance gate now measures each TRIM variable against its full-scale physical
range instead of relative to its NASTRAN target, and runs live (the `xfail` is gone). A relative
tolerance was meaningless for SC2 (q=1200): its trim AoA passes through ~0 as dynamic pressure
rises, so a fixed absolute error read as an exploding percentage (the old gate saw ANGLEA "+136%"
for a 0.107° miss).

- **`tests/aero/test_ae1_fullspan.py::TestVAE1dSC2`** dropped the `@pytest.mark.xfail` and now
  asserts ANGLEA within `np.deg2rad(0.3)` (1% of the 30° AoA stall band) and ELEV within
  `np.deg2rad(0.4)` (1% of the 40° elevator throw). SC2 actual: ANGLEA 0.357% FS, ELEV 0.229% FS —
  both pass. `TestVAE1dSC1` keeps its existing live relative gate.
- The residual ~0.1° miss is a q-INVARIANT common-mode offset (same absolute error already
  accepted at SC1), not a high-q flexible defect; its optional root-cause stays tracked as MINOR
  AE8a. No HA144A bulk parameters were re-tuned.
- Suite: 801 passed, 0 xfailed (was 799 passed / 2 xfailed — the 2 SC2 relative xfails cleared).

### Added

**Step 52 (remainder) — over-determined trim + lateral rate derivatives (2026-06-14)**

Closes the two remaining Step 52 deliverables on top of the existing determined Schur trim solver.

- **Lateral / directional derivatives:** `_compute_rigid_derivs` / `_compute_restrained_derivs`
  (`sbeam/solver/sol144.py`) now emit roll/yaw moment coefficients `CMX = Mx/(S_ref·b_ref)` and
  `CMZ = Mz/(S_ref·b_ref)` (full 3-component cross-product resultant via `aero_moment_resultant`),
  yielding the damping derivatives `C_lp` (ROLL), `C_nr` (YAW) and the dihedral effect `C_lβ`
  (SIDES). The rate normalwash columns already existed in `build_djx`; this adds the moment
  recovery. Gate: `tests/aero/test_lateral_derivs.py` (V-LAT) — `|C_lp| ≈ 0.54` for the AR=8 rect
  wing, clean planar decoupling, and the ±Γ `C_lβ` sign-flip (zero on the planar deck).
- **Over-determined (redundant-control) trim:** `run_sol144_trim` dispatches to
  `_solve_trim_overdetermined` when `n_free > n_suport`. The equilibrium equality is eliminated by a
  null-space reduction `δ = δ_p + N·z`; the redundancy coordinate minimises the convex weighted-L2
  TRIMOBJ objective subject to TRIMCON inequalities and TRIMVAR bounds (SLSQP). The Schur build is
  refactored into `_build_trim_schur` + `_recover_u_a`, shared with the determined path. Gate:
  `tests/aero/test_trim_overdetermined.py` (V-C4) — `min(PITCH²)` reproduces the determined trim, a
  TRIMCON forces its bound active, and the result is initial-guess insensitive.
- **Plumbing:** `SubcaseControl.trimobj_sid` + `TRIMOBJ = sid` case-control parsing;
  `Sol144TrimResult.trim_mode`; f06 LATERAL/DIRECTIONAL DERIVATIVES block + TRIM SOLUTION mode line.
- Suite: 362 passed across `tests/aero/` + `tests/results/` + case-control parser (no regression to
  the validated longitudinal derivative column).

**Step 58 — dihedral / anhedral (±Γ) correctness gate (2026-06-14)**

The SOL 144 chain (VLM → spline → force integration → trim) is now permanently validated OUT of
the xy-plane, for both positive dihedral (Γ=+10°) and anhedral (Γ=−10°). Key finding: the
force/normal architecture was already 3-component and geometry-driven (`mesh_caero1` derives the
box normal from the z-bearing corners; `build_skj` emits `area·normal·cp`), so no production
rewrite was needed — only validation decks, a permanent gate, and a reusable moment helper.

- **`sample/val_vlm_dihedral.bdf`, `sample/val_vlm_anhedral.bdf`** — rigid-VLM rect wings canted at
  Γ=±10°; **`sample/val_dihedral_trim.bdf`** — a minimal structured symmetric dihedral wing (spar +
  SPLINE2 on a canted CID + mass + SUPORT) for a determined plunge trim out of plane.
- **`sbeam/solver/sol144.py::aero_moment_resultant`** — full 3-component aerodynamic moment
  `Σ (r_j − ref) × F_j` (roll/pitch/yaw), reusable by future monitor-point integration.
- **`tests/aero/test_dihedral.py`** (V-C-DIH, 6 tests) — geometric box normal `(0, ∓sinΓ, cosΓ)`;
  per-box `Fy/Fz = n_y/n_z` and symmetric `Fy` cancellation; rigid `CL ≈ CL_planar·cosΓ` (0.27% at
  AR=8) with dihedral≡anhedral CL; and a structured trim that closes the inertia-relief balance
  with residual `Fy`/roll/yaw ≈ 0. Guards permanently against the `(0,0,1)`-normal /
  Fz-only-resultant blind spot.

**AE11 — hinge-moment derivatives in SOL 144 (2026-06-13)**

SOL 144 now recovers, per AESURF control surface, the hinge moment about its `cid1` hinge axis —
both the trimmed value and the per-trim-variable derivatives `dHM/dδ`.

- **`sbeam/solver/sol144.py::_compute_hinge_moments`** computes
  `HM = Σ_{j∈AELIST} [(r_j − o) × F_j]·ĥ` from the box forces (rigid columns mirror
  `_compute_rigid_derivs`); results carried on the new `Sol144TrimResult.hinge_moments` field and
  printed in a **HINGE-MOMENT DERIVATIVES** block in the `.f06`.
- Validated by an independent closed-form resultant (uniform-Cp flat surface) rather than external
  NASTRAN data — `tests/aero/test_ae11_hinge.py`.

**AE1 Step C — `Q_aa` rigid-body null-space regression gate (2026-06-13)**

A permanent guard that the rigid-body modes which do not load the aero lie in the null space of
the flexible aero stiffness `Q_aa` (`Q_aa·u_rb ≈ 0`), so a future spline regression cannot
silently re-contaminate `Q_aa`. Test-only; no production code changed.

- **`tests/aero/test_spline.py::TestGlobalRigidBody`** extended with composed `Q_aa·u_rb`
  null-space assertions (built via the real `build_aero_model` → `build_qaa` chain) on three
  fixtures, each with a geometry-dependent null set: HA144A swept-planar (`{Tx,Ty,Tz,Rz}` < 1e-10,
  `Rx` bounded < 1e-3 due to BDF coordinate rounding), a math-exact planar rect (`{Tx,Ty,Tz,Rx,Rz}`
  < 1e-10), and a **new 30° dihedral fixture** with z≠0 grids and a tilted surface normal
  (`{Tx,Ty,Tz,Rx}` < 1e-10).
- Rigid pitch (and yaw on the dihedral wing, where it loads ∝ sin Γ) are asserted to LOAD as
  positive discriminators, so the gate cannot pass on a degenerate all-zero `Q_aa`.
- 18 new cases; verified to trip when a `g_slope` row is perturbed.

**V-AE3 — independent unit-Cp force/moment cross-check (2026-06-13)**

A discriminating validation gate that confirms the aerodynamic force/moment coupling path is
independently correct, closing the AE13 blind spot where every aero gate was only self-consistent
(a common scale error or factor-of-2 parity bug would pass).

- **`tests/aero/test_vae3_cross_check.py` (new)** builds the box force/moment two ways on the same
  model and asserts the totals agree to ≤1%: Path A is the SOL 144 coupling chain
  `skj @ (ajj_inv_corr @ w)` (totals via `_pitch_moment`); Path B is `solve_rigid_cl`, which
  rebuilds its own AIC and Kutta–Joukowski resultants in a separate module (`Fz = CL·S`,
  `My = CM·S·c`). Parametrised over `ha144a_fullspan_sbeam.bdf` (M=0.9) and `val_vlm_rect_ar8.bdf`
  (M=0).
- Both paths are driven with the SAME alpha-only normalwash (W2GJ baseline excluded) and the SAME
  effective Mach, so the comparison is apples-to-apples. The totals match to machine precision; a
  parity proxy (halving `f_box`) fails the gate by ~2×, confirming it discriminates.
- No new production code — reuses `_pitch_moment`, `build_djx`, and `solve_rigid_cl`.

**SOL 144 runs end-to-end from the CLI — f06 output + trimmed flight-load export (AE10 + Step 56, 2026-06-13)**

`sbeam deck.bdf` now solves a SOL 144 static aeroelastic trim deck end-to-end. Previously
`run_sol144_trim` had no production caller and the deck exited with "SOL 144 is not supported".

- **CLI dispatch (AE10).** `main.py` gained a SOL 144 branch that builds the `AeroModel` +
  `grid_index`, seeds an `AeroCache` shared across subcases (multi-Mach decks build each AIC
  once), runs `run_sol144_trim` per TRIM subcase, and writes `<stem>.f06` plus
  `<stem>.aero_loads.bdf`. `build_aero_model` rejects half-span (`SYMXZ≠0`) decks.
- **SOL 144 f06 writer (Step 56).** New `build_f06_sol144_text` / `write_f06_sol144` with
  TRIM VARIABLES, STABILITY DERIVATIVES (rigid + elastic restrained), AERODYNAMIC TOTALS
  (CL/CMY), AERODYNAMIC DIVERGENCE, and an AERODYNAMIC BOX PRESSURES AND FORCES block gated on
  the new `AEROF`/`APRES` case-control requests. The DISPLACEMENT / BAR FORCE / BAR STRESS
  blocks were extracted into shared helpers reused by SOL 101 (its output is byte-identical).
- **Trimmed flight-load export.** New `results/load_export.py` writes comma free-field
  `FORCE`/`MOMENT` bulk cards per subcase from `Sol144TrimResult.grid_loads` (`g_disp^T·q·f_box`);
  the set sums to the trimmed lift/moment (verified to 3.5e-9 on HA144A).
- **Result enrichment + divergence.** `Sol144TrimResult` gained `box_cp`, `box_forces`,
  `grid_loads`, and `q_div`. `sol144._divergence_dynamic_pressure` computes the single critical
  divergence dynamic pressure on the restrained l-set.
- **Case control.** `AEROF` / `APRES` output requests parsed onto `SubcaseControl`; stale
  `parse_case_control` docstring corrected.
- **Deferred (Step 56's own carve-outs):** maneuver-balanced (aero + inertial) load export →
  Step 53; the `DIVERG`-card q-sweep + divergence mode shape → Step 55.
- **Tests.** Full suite 792 passed, 2 xfailed: end-to-end CLI run, f06 block coverage with
  AEROF/APRES gating, FORCE/MOMENT sum-to-lift + re-parse round-trip, SOL 144 case-control.

**HA144A stability-derivative validation against ADA370433 (2026-06-13)**

Cross-checked the HA144A trim case against an independent source — the ASTROS*/ZAERO
Applications Manual (DTIC ADA370433, §3.1, Table 3.1.1) — which reproduces the MSC/NASTRAN
longitudinal derivatives.

- **New gate `tests/aero/test_ha144a_rigid_derivs.py`:** the full rigid longitudinal column
  (C_Zα, C_Mα, C_Zq, C_Mq, C_Zδe, C_Mδe) is now regression-guarded against the document's
  NASTRAN rigid values. sbeam already computed all six to 4 sig figs; only C_Zα/C_Mα had been
  gated. Suite now 799 passed, 2 xfailed.
- **AE8 targets sourced:** the document's UNRESTRAINED (mean-axis) column is recorded as
  `NASTRAN_UNRESTRAINED` in `test_ae1_restrained_derivs.py` for the open AE8 acceptance —
  previously "needs the MSC manual". Clarified that this is distinct from the MSC Table 7-1
  RESTRAINED column (5.103) that V-AE1e gates; the two must not be conflated.
- **Scope-boundary link:** `test_supersonic_trim_rejected` annotated to cite the document's
  M=1.3 / q=1151 third flight condition (out of scope for the steady subsonic VLM).

### Removed

**Half-span / symmetry (AEROS SYMXZ/SYMXY) support removed — sbeam is full-span only (2026-06-12)**

The half-span symmetry-image capability — a 1970s computational economy no longer needed —
was removed. Every lifting surface is now meshed in full.

- **VLM kernel simplified.** Removed the `parity` parameter and the XZ-mirror image logic from
  `horseshoe_influence`, `build_ajj`, `trefftz_cdi`, and `solve_rigid_cl` (vlm.py), including the
  symmetric/antisymmetric image-bound branches, the mirror trailing-vortex loop, the
  `parity == -1` CL/CY/CDi special cases, and the half-vs-full-span reference-AR doubling
  heuristic. `AeroModel.parity` and the `parity` argument of `build_aero_model` are gone.
- **AE1 Step D fixed by construction.** Removing the `sym = 2` half-span force-doubling factor
  from `run_sol144_trim` eliminates the aero/inertia parity double-count that halved the HA144A
  trim. SC1 now trims to NASTRAN Listing 7-2 within ~2% on the full-span deck.
- **SYMXZ guard + migration aid.** `build_aero_model` now raises if `AEROS SYMXZ`/`SYMXY` ≠ 0,
  pointing at the new `sbeam.aero.mirror.mirror_halfspan()` utility, which unfolds a legacy
  half-span deck (GRID/CBAR/CONM2/RBAR/RBE2/CAERO1) to full-span about the XZ plane. The AEROS
  card still *parses* SYMXZ/SYMXY (the field layout is unchanged); only solving a non-zero model
  is rejected.
- **Viewer.** Removed the Symmetric/Antisymmetric/Full-span radio from the aero tab.
- **Decks & tests.** Half-span `sample/ha144a_sbeam.bdf` and its gate `test_ae1_keff_trim.py`
  removed; `sample/ha144a_fullspan_sbeam.bdf` + `test_ae1_fullspan.py` are now the sole HA144A
  trim gate (SC1 value + SC2 sign/flexible-increment coverage folded in). All VLM tests rebuilt
  on genuine full-span geometry; the antisymmetric and parity-image unit tests and the concluded
  A1 convergence diagnostics were removed.

### Fixed

**Aero tab — rigid S&C derivative table no longer mislabels body-axis `CZ` as wind-axis `CL` (2026-06-14)**

- The viewer's "Rigid stability & control derivatives" table relabelled the vertical-force
  coefficient `CZ` → `CL` under the **Aero** naming toggle (`sbeam/viewer/aero_view.py`,
  `_DERIV_AERO_COLS`). `CZ` is the body/global-z force (summed z-component of the surface-normal
  box forces); `CL` is the wind-axis lift (⊥ to U∞), related by `CL = CZ·cosα + CX·sinα` and equal
  to `CZ` only at α≈0. The toggle applies no body→wind rotation (it only relabels — the RAW and
  Aero columns are numerically identical), and the table carries no reference incidence, so the
  `CL` label was incorrect. The Aero naming now keeps the body-axis symbol `CZ`; moments stay the
  conventional body-axis `Cl/Cm/Cn`. (The `naming="raw"` view already showed `CZ` and was correct.)
- `sbeam/viewer/app.py`: the Naming radio illustration updated to symbols that actually differ
  between modes (`Aero (α, Cm…)` ↔ `Raw (ANGLEA, CMY…)`).
- Tests: `tests/viewer/test_aero_view.py` updated to expect the `CZ` column header and cross-check
  `df.loc["α", "CZ"]`. Docs: 05_aeroelastics.md / 06_viewer.md note the body-axis `CZ` (not `CL`).

**W2GJ baseline-normalwash (`wg`) sign convention unified across all layers (2026-06-14)**

The `wg` sign was documented one way (theory doc / test T2: positive `wg` = +incidence =
*more* lift) and computed the other way in every production solver (positive `wg` = downwash
slope = *less* lift). A deck authored to the theory/test convention would have run with
silently flipped aerodynamic loads under SOL 144. The production "downwash-slope" convention
is now the single canonical one everywhere, validated end-to-end:

- **Canonical convention:** `wg` (W2GJ) is a dimensionless downwash slope Δz/Δx added directly
  to the assembled normalwash (NASTRAN W2GJ convention, *not* passed through `D_jk`). **Positive
  `wg` = local nose-down / washout → less lift; negative `wg` = leading-edge-up built-in
  incidence → more lift.** Production code (`sol144._compute_aero_forces`,
  `aero_model.compute_structural_loads`, `coupling.build_fg`, `vlm.solve_rigid_cl`,
  `maneuver_qs`) and `sample/val_wing_taper_dihedral_twist.bdf` already used this sign and are
  unchanged.
- **Docs corrected to match:** theory `01_aeroelastics_theory.md` §2.4 governing-convention
  sentence (positive `w` *reduces* lift) and Eq 9 (incidence/twist terms now enter as negative
  downwash slopes); the `w_g` nomenclature row; the `W2gj` dataclass comment
  (`sbeam/model/aero.py`); `integration.py` module/`build_djk`/`build_wg` docstrings; and the
  `05_aeroelastics.md` `build_djk` / `build_wg` / W2GJ-field reference.
- **Tests aligned to the production chain:** `test_integration.py` T2 and T3 no longer apply a
  local `-wg` negation — they solve `gamma = Ajj⁻¹ @ wg` exactly as the solvers do, with `wg`
  carrying the canonical sign (a nose-up AoA reproduced by a *negative* `wg`).
- **New end-to-end regression** (`tests/integration/test_wg_sign_convention.py`): drives the
  real production load path (`compute_structural_loads` / `build_fg`) on a splined cantilever
  and asserts positive `wg` unloads the wing, negative `wg` adds lift, total lift falls
  monotonically as `wg` sweeps negative→positive, and at α = 0 a positive `wg` produces a net
  downward load.

**Code-review follow-ups — monitor parity, divergence robustness, cleanups (2026-06-13)**

Findings from the critical design review of the SOL 144 divergence / maneuver / monitor work:

- **MONPNT1/MONPNT3 SYMXZ parity reconstruction corrected** (`results/monitor_points.py`).
  A half-span (`SYMXZ ≠ 0`) build previously doubled *all six* `[F, M]` components. Under
  symmetric loading only the symmetric components (Fx, Fz, My) double across the xz mirror;
  the antisymmetric ones (Fy, Mx, Mz) cancel. New `_apply_symmetry` applies this in the basic
  frame before the cp-frame rotation, and rejects off-centerline monitors (`|y_ref| > 1e-6`)
  on half-span models with a clear error (a full-span model is required there). The default
  full-span path (`parity = 1`) is unchanged.
- **DIVERG `NROOTS` validated at parse time** (`parser/bdf_reader.py`): `NROOTS < 1` now raises
  a descriptive error instead of being silently coerced to 1 inside `_divergence_roots`
  (`solver/sol144.py`, which now slices `roots[:nroots]` directly).
- **Cleanups:** removed the unused `n_dofs` parameter from `maneuver_qs._recover_step`, and
  corrected the `_divergence_roots` docstring (it calls `scipy.linalg.eig` directly, not
  `sol103._solve_modes_dense`).

**AE11 — D_jx YAW column + AESURF hinge geometry (2026-06-13)**

`build_djx` (`sbeam/aero/integration.py`) had two latent control/lateral-column defects, both
fixed without changing any existing trim (HA144A uses only ANGLEA/PITCH/URDD3/ELEV, and its ELEV
hinge is spanwise):

- **YAW no longer duplicates ROLL.** The YAW column is now the vertical-surface sidewash
  `−(2/bref)·(x_ctrl − x_ref)·n_y` (matching the `SIDES = −n_y` convention), which loads vertical
  fins and vanishes on horizontal/z-normal panels, instead of the copied `−(2/bref)·y_ctrl`.
- **AESURF control column uses the actual hinge axis.** The column is now `−(ĥ × n)·x̂·eff` about
  the `cid1` hinge axis `ĥ` (its y-axis), resolved via `_get_transform`. For a spanwise hinge this
  reduces *exactly* to the previous `−n_z·eff` (verified bit-identical on HA144A ELEV); only
  swept/non-spanwise hinges change. Also dropped the `eff if eff != 0.0 else 1.0` guard so an
  explicit `AESURF` `eff = 0.0` is honoured rather than silently promoted to 1.0.

**Backlog validation review — AE1 re-diagnosis corrected; R16–R22 closed (2026-06-12)**

Full validation pass over `docs/30_future/00_backlog.md` against the MSC HA144A reference
(Table 7-1 / Listing 7-2). No solver behaviour changed except the two NIT fixes below.

- **AE1 root cause re-diagnosed (CRITICAL).** The SC1/SC2 ANGLEA/ELEV trim gap is a `sym=2`
  aero/inertia parity double-count in `run_sol144_trim` (aero terms ×2 at
  sol144.py:795/822/833; inertial `M_ax` at :873–874 not doubled), **not** the flexible
  `q·Q_aa` increment. Forcing `sym=1` yields the correct trim (0.1727/0.4893 vs NASTRAN
  0.169191/0.492457) and 8000 lb lift; flexibility at q=40 is a 0.6% effect (Table 7-1),
  incapable of a 50% error. Rewrote the backlog Diagnosis, step sequence (lead = Step D
  parity fix, not Step C), Steps C/D/F/G, AE8, AE13 (V-AE1/V-AE3), and the V-AE1 acceptance.
  The actual `sym` code fix is left for a dedicated change (confirm the HA144A REFS
  convention first).
- **Full-span cross-check added (`sample/ha144a_fullspan_sbeam.bdf`).** Explicit 2× mirror of
  HA144A (both wings/canards, SYMXZ=0, fuselage mass doubled → 16000 lb, CG_x=17.18 matched).
  Ground truth with no symmetry assumption: uses a single-point ground (`SPC1 1246` at GRID 90
  + `SUPORT 35`) rather than the half-model's centreline symmetry SPCs, so symmetry EMERGES
  (antisymmetric centreline DOF = 1e-18, L/R wing tips identical). Passes the rigid-pitch
  spline check and trims to **SC1 0.1711/0.4908 (101%/100% of NASTRAN), lift 16000 lb**,
  independently confirming the parity diagnosis. It also REFINED the fix: `parity` is overloaded (it also selects the AIC
  symmetry image vortices, which are required), so the fix decouples the force-scale (`sym=1`)
  from the AIC parity — NOT simply `parity=0` (which removes the images and gives 0.302).
  Surfaced a SEPARATE, still-open flexible residual at SC2 (q=1200): corrected half (0.0049)
  and full-span (0.0032) both miss NASTRAN (0.0014) — Step G / AE8 territory, not parity.
- **Test-gate weaknesses documented:** `test_trim_lift` is non-discriminating (lift=8000 lb
  for both sym=1 and sym=2); SC2 ANGLEA passes at 140% of target under the shared
  `ATOL_ANGLEA=1e-3`. Flagged for per-target relative tolerances.
- **R21** fixed: `if spc_sid is not None:` guard before `check_spc_enforced_displacements`
  (`sbeam/solver/sol101.py:255`).
- **R22** fixed: public `build_f06_sol101_text` / `build_f06_sol103_text` aliases in
  `sbeam/results/f06_writer.py`; `sbeam/main.py` and `sbeam/viewer/app.py` import the public
  names instead of the private `_build_f06_*`.
- **R16, R17, R18, R19 removed** from the backlog (R16/R18 fixed by the prior doc
  restructure; R17/R19 misidentified — already present). New NIT **R23** logged for a
  residual `recover_bar_forces` doc-signature mismatch (`03_static_analysis.md:307`).
- **Backlog reframes** (still open, corrected): AE9 (subsonic multi-Mach; HA144A SC3 is
  supersonic/out-of-scope; add a supersonic guard, not a one-line fix), AE10 (dispatch needs
  a prebuilt AeroModel; case-control already whitelists SOL 144), AE11 (non-blocking for AE1;
  YAW latent), AE12 (PG-normal half re-diagnosed as **not a bug** — exact for n_x=0 incl.
  dihedral; DTOR/DTHZ-warning half kept), A5 (stale "case_control rejects SOL 144" claim),
  A7 (CM-convergence numbers retracted — ~50%/34% do not reproduce; ≤~1.9% measured).

**AE1 Step E — Moment-sign single-source helper + virtual-work consistency gate (2026-06-12)**

Closed the AE1 Step E increment and corrected its diagnosis. The gross pitching-moment
sign was already fixed in Step A; investigation showed the moment that drives the Schur
trim (the `g_disp` virtual-work path onto the SUPORT Ry DOF) was already sign- and
magnitude-correct, so Step E became a DRY refactor plus a permanent regression gate.

- `sbeam/solver/sol144.py`: new `_pitch_moment(f_box_vec, boxes, x_ref)` — single source
  for the nose-up-positive moment-arm convention `My = −ΣFz·(x_force − x_ref)` (¼-chord
  force point). Replaced the three hand-inlined copies in `_compute_aero_forces`,
  `_compute_rigid_derivs`, and the `run_sol144_trim` total-CM loop (latter keeps its
  `sym` parity factor at the call site). Behaviour-preserving — HA144A trim numbers are
  byte-identical (SC1 ANGLEA=0.085951, ELEV=0.244584).
- `sbeam/aero/vlm.py`: comment on `solve_rigid_cl.CM` cross-referencing the shared
  `−Σ(...)·(x−xref)` convention with `sol144._pitch_moment` (pressure form vs force form).
- `tests/aero/test_ae1_step_e_moment.py` (new): `TestStepEMomentConsistency` — for unit
  ANGLEA/ELEV on HA144A, asserts g_disp virtual-work Fz == direct Fz (1e-9), virtual-work
  moment about the SUPORT == `_pitch_moment` (1e-6 rel), and ANGLEA moment is nose-down.
  3 tests pass.
- **Re-diagnosis:** the residual SC1/SC2 ANGLEA/ELEV gap (e.g. ELEV 0.245 vs NASTRAN
  0.492) is the flexible `q·Q_aa` increment, **not** a moment-sign error (a direct rigid
  2×2 trim gives ELEV ≈ 0.795; the Schur flexible solve gives 0.245). The
  `test_ae1_keff_trim.py` value tests remain failing pending Steps C/D/G. Backlog updated:
  Step E removed, AE8 sign half marked resolved, action-plan/sequence/measured-state and
  "What not to do" notes corrected to point the ANGLEA/ELEV gap at Steps C/D/G.

**AE1 Step B — Spline kinematic correctness on swept SPLINE2 (B1–B4, 2026-06-12)**

Resolved three independent defects that together prevented `g_slope`/`g_disp` from
reproducing global basic-frame rigid-body modes on a swept SPLINE2. The HA144A wing,
under a global θ=1e-3 pitch about y, now returns uniform incidence +1.000e-3 (was
[−9.45e-02, +4.53e-02]). All 18 `TestGlobalRigidBody` (V-AE1b) tests pass; the full
non-V-AE1 suite holds at 238 passed.

- **B1 — RBAR-expanded recovery in the trim path.** Added `_expand_to_g(u_a, T,
  free_local, n_red)` to `sbeam/solver/sol144.py` and replaced the three
  direct-index scatters in `run_sol144_trim` and `_compute_restrained_derivs`
  (nominal + perturbed) with `displacements = T @ u_red`. RBAR slave DOFs now move
  with their masters before `g_slope @ displacements` is evaluated. The
  `_compute_restrained_derivs` signature changed from `(free_dofs, …, n_dofs)` to
  `(T, free_local, n_red, …)`.
- **B2 — Sample HA144A SET1 fixed to the elastic axis.**
  `sample/ha144a_sbeam.bdf` SPLINE2 1601 SET1 changed from `{99, 100, 111, 112,
  121, 122}` (fuselage centreline + RBAR-slave LE/TE stringers) to the EA-only
  `{100, 110, 120}` (wing-CBAR endpoints); SPLINE2 DTHX flipped −1 → +1 (attached)
  so torsion rides through the master Rx DOF with the corrected formula.
- **B3 — SPLINE2 SET1 collinearity validator.** `sbeam/aero/spline.py
  ::_build_spline2_block` now computes each SET1 grid's chord offset
  `Δ_i = (r_i − origin)·ŷ_spline` and raises `ValueError` when
  `max |Δ| > 5%` of the span range, naming the offending grids and their (x, y,
  s, Δ). Prevents silent Q_aa contamination from future off-EA SET1 layouts.
- **B3+ — Spline-math fix (multiplication-bending + corrected torsion).**
  `_build_spline2_block` now uses `w = −x̂[0]·(dh/ds)` for the bending /
  translation contribution (was `−(dh/ds)/x̂[0]`, self-consistent only on the
  V-AE2b along-spline-axis kinematic). Torsion uses
  `w_torsion = −ŷ[0]·x_comp·f_vals_slope` (was `x_comp·f_vals_slope`, correct
  only for unswept splines). Added matching torsion contribution to `g_disp`:
  `g_disp[3k+c] += x_comp·ζ_k·ẑ[c]·f_vals_force`. The `sweep_ok`
  gate is removed (multiplication is well-defined at `x̂[0]=0`). With the new
  formulas the attached (`DTHX=+1`) path reproduces all six basic-frame rigid-body
  modes exactly on planar wings.
- **B4 — V-AE1b gate added (`tests/aero/test_spline.py::TestGlobalRigidBody`).**
  For each of `{Tx, Ty, Tz, Rx, Ry, Rz}` applied to *every* grid (with lever-arm
  fill for rotations), asserts `g_slope·u_rb` and `g_disp·u_rb` (z-component at
  every box force_point) against analytic expectations. Tolerances: 1e-5 on
  HA144A (limited by 5-decimal coordinate input), 1e-12 on the math-exact
  rectangular fixture.
- The legacy V-AE2 swept-spline fixture was updated to the EA-only SET1 and
  `DTHX=+1` to align with the corrected spline; V-AE2a/b/c remain green as unit
  checks on the Hermite slope projection.

### Added

- **AE9 — per-TRIM Mach (multi-Mach SOL 144)** — the VLM AIC is now built at the flight
  Mach of each TRIM subcase instead of once from `AEROS.mach`. `build_aero_model` gained a
  `mach` override; a new Mach-keyed `AeroCache` (`sbeam/solver/sol144.py`) memoizes the AIC
  per Mach so the build-once pattern still holds, and `run_sol144_trim` gained an optional
  `aero_cache` argument (existing 3-arg callers are unchanged — the prebuilt model seeds the
  cache). `AEROS.mach` is the fallback when the TRIM field is unset; a genuine TRIM-vs-AEROS
  disagreement now warns. The previous *silent* M≤0.99 clamp is replaced by a **supersonic
  guard**: an effective Mach ≥ 1 raises `ValueError` (steady subsonic VLM cannot solve it) in
  `build_aero_model`, `prandtl_glauert_boxes`, and `solve_rigid_cl`. Tests:
  `tests/aero/test_ae9_mach.py` (mismatch warns, distinct-Mach distinct trim, supersonic
  rejected, cache memoization). Closes AE9.

- **AE1 Step G — analytic restrained stability derivatives (closes AE8 derivative half)** —
  `_compute_restrained_derivs` (`sbeam/solver/sol144.py`) now returns the exact analytic
  derivative from the Schur factorisation (`∂u_l/∂δ = K_ll⁻¹·C_ax_l`, then the linear
  normalwash → circulation → force chain), replacing the prior one-pass finite-difference
  hybrid (AE8). The trim is linear in each label, so the analytic columns equal the old FD
  columns to round-off; the FD machinery (`delta_perturbation`, nominal re-evaluation,
  per-column perturbed solve) is deleted. Gate `tests/aero/test_ae1_restrained_derivs.py`
  (V-AE1e, partial): rigid columns unchanged (CZα 5.071, CMα −2.871), restrained CZα 5.112
  vs NASTRAN Table 7-1 5.103 (q=40) within 1%, analytic == captured FD baseline. AE8 stays
  open for the remaining unrestrained (mean-axis) derivative set.

- **V-AE1d trim acceptance gate (AE1 Step F)** — added per-target relative-tolerance
  trim assertions to `tests/aero/test_ae1_fullspan.py`, replacing the shared absolute
  tolerance that masked SC2's high result. SC1 is gated live (ANGLEA ≤1.5%, ELEV ≤1%,
  lift ≤1% of 16000 lb); SC2 was initially gated at 1% per target and marked `xfail`.
  *(Superseded 2026-06-13 — see "AE1 Step F closed" above: the SC2 gate was re-framed to
  %-full-scale and the `xfail` dropped; AE1 Step F is now closed.)*

**Critical design review — aeroelastics, HA144A benchmark (2026-06-11)**
- Reviewed the full aeroelastic chain (`aero/`, `solver/sol144.py`) against MSC Nastran
  HA144A (Aeroelastic Analysis User's Guide Listing 7-2 / Table 7-1) and the ZAERO 9.2
  Theoretical Manual (trim Ch. 12, splines Ch. 6). Verified the VLM core (Biot–Savart
  kernel, symmetry image, Göthert PG) matches the NASTRAN rigid CZα to 4 significant
  figures once the swept lift-width defect is corrected; found 5 CRITICAL and 5 MAJOR
  defects in the integration/spline/trim layers (trim currently fails HA144A on both
  subcases and trims to −1g).
- `docs/30_future/00_backlog.md`: new "Code Review — 2026-06-11" section with findings
  AE1–AE13, measured-vs-reference table, and a 6-step correction plan with per-step
  verification targets; Phase A/B and Step 52 entries annotated with their open AE items.
- `docs/10_standard/05_aeroelastics.md`: "Known Defects" banner; corrected the false
  "skj calibrated to consume Γ" claim (AE2); documented MSC vs sbeam SPLINE2 DTHX
  semantics divergence (AE4c); swept-axis projection and Hermite slope-sign defects
  (AE4a/b); ¼-vs-¾-chord force application caveat (AE6); swept K-J lift-width caveat on
  the validated CL/CM claims (AE3); new Step 52 WIP status section for `run_sol144_trim`.
- `studies/_review_ha144a_check.py`: reproduction script — HA144A trim both subcases,
  rigid-body spline kinematics checks, force-transfer-point check, rigid-derivative
  cross-check against `solve_rigid_cl`.

**AE2 — Fixed j-set pressure unit: `ajj_inv_corr` now returns ΔCp, not Γ**
- `sbeam/aero/aero_model.py`: `build_aero_model` scales `ajj_inv_corr` rows by
  `2/chord_box` (physical boxes) immediately after the Prandtl–Glauert step, so that
  `ajj_inv_corr @ w` returns dimensionless ΔCp throughout. All downstream consumers
  (`build_fg`, `build_qaa`, `Q_ax`, `_compute_rigid_derivs`, `_compute_aero_forces`)
  are now unit-consistent with no caller changes.
- `sbeam/aero/corrections.py`: `apply_wt1` reference strip force changed from
  `Σ area·Γ` to `Σ area·2Γ/chord` (physical strip lift/q), so the WT1 correction ratio
  is computed against the correct physical reference. `apply_wt2` unchanged (WT2 target
  convention stays as VLM Γ — ratio cancellation makes it transparent).
- `sbeam/solver/sol144.py`: `run_sol144_trim` `total_cl`/`total_cm` now divide by
  `sref` (not `q·sref`) because `skj @ Cp` is force/q; `_compute_restrained_derivs`
  CZ/CMY denominators likewise drop the spurious `q`.
- `tests/aero/test_corrections.py`: 5 tests updated to assert against physical Cp
  quantities (skj-path CL round-trip, WKK force ratio, WT2 Cp output, WT1 physical
  strip-force round-trip and scaled variant).
- Verified: HA144A rigid CZα (ANGLEA) via `_compute_rigid_derivs` = 5.071, matching
  `solve_rigid_cl` CLα = 5.0709. Previously 6.339 (≈25% error). `total_cl` at SC1
  trim = −1.001; lift = −8011 lb ≈ −W (sign fixed by AE5, still open).

**AE5 + AE7 — Fixed RCSID-frame URDD transform and inertial trim columns**
- `sbeam/solver/sol144.py`: replaced `_build_urdd_load` with `_build_inertial_cols(bulk,
  all_labels, grid_index, suport_pos)` returning a full (n_g, n_labels) inertial sensitivity
  matrix M_ax (non-zero only for URDD columns). Translational URDD: `M[Tz_dof, col] = −m`
  per CONM2 and lumped CBAR half-mass. Rotational URDD: spin term `M[Ry_dof] = −I_diag`
  plus transport cross-product `F = −m·(α̂×r)` about `suport_pos`. M_ax_a (a-set) is now
  passed to both `_solve_trim_determined` and `_compute_restrained_derivs`, replacing bare
  `q·Q_ax` with `q·Q_ax + M_ax` throughout the Schur assembly.
- RCSID transform block in `run_sol144_trim` now handles partial URDD sets (e.g. only URDD3
  present without URDD1/2): assembles the full 3-vector with zeros for absent components,
  applies R_rcsid, writes back only present components. Previously required all three of
  URDD1/2/3 before applying the transform, causing the sign inversion to persist when only
  URDD3 was in `all_labels`.
- `tests/aero/test_trim_urdd.py` (new file): 10 tests — `TestUrddRcsidTransform` (2 unit),
  `TestInertialCols` (5 unit), `TestTrimSignAe5` (3 integration). V-AE3a gate:
  `total_cl > 0` for RCSID z-down 1g trim. All 10 pass; full suite 721 tests pass.

**AE4 + AE6 — Fixed SPLINE2 swept-axis kinematics and ¼-chord force point**
- `sbeam/aero/panel.py`: added `force_point` field to `AeroBox` — midpoint of the ¼-chord
  bound-vortex segment `(bound_a + bound_b) / 2`.
- `sbeam/aero/spline.py` (full rewrite of `_build_spline2_block`):
  - AE4(a): slope projection now divides by `x_hat[0]` (ZAERO §6.3: `w = −(dh/ds)/x̂₀`).
  - AE4(b): nodal-slope sign corrected: `(dh/ds)_i = −(ω·ŷ)_i`; bending g_slope gains
    `+(y_comp/x0)·dψ/ds`, bending g_disp changes to `−y_comp·ẑ·ψ(t_force)`.
  - AE4(c): `DTHX = −1.0` now correctly means "detach rotation DOF" (skip torsion
    coupling); `DTHX = 1.0` attaches; other values warn and treat as detached.
  - AE6: g_disp evaluated at `t_force = (force_point − origin)·x_hat` (¼-chord), not
    `t_slope = (colloc − origin)·x_hat` (¾-chord); g_slope unchanged at colloc.
  - `_build_attach_rows` lever arm changed from `box.colloc` to `box.force_point`.
- `sbeam/solver/sol144.py`: three `colloc[0]` → `force_point[0]` in moment arms
  (`_compute_aero_forces`, `_compute_rigid_derivs`, total CM loop).
- `tests/aero/test_spline.py`: new `TestSweptSplineRigidBody` class (V-AE2a/b/c) passing
  to 1e-12; `TestAttachRigidBodyGate.test_v_b3d_force_transfer_lever_arm` expected moment
  arm updated to use `force_point` (¼-chord at 0.25 ft, not colloc at 0.75 ft).
- All 711 tests pass.

**AE3 — Fixed Kutta-Joukowski lift-width projection for swept wings**
- `sbeam/aero/vlm.py`: `solve_rigid_cl` and `trefftz_cdi` now use the cross-flow projected
  width `sqrt(Δy² + Δz²)` as the spanwise width `dy` of each bound-vortex segment, instead
  of the 3-D Euclidean length `‖bound_b − bound_a‖`. This is required by the K-J theorem
  (F = ρ V∞ × Γ Δs; lift scales with Δy, not ‖Δs‖). The fix also corrects `chord_box`,
  `cl_section`, `CM`, `CDi`, and per-surface breakdowns, all of which derived from `dy`.
- `tests/aero/test_integration.py`: aligned inline `dy` formula to match production code.
- Verified: HA144A (Λ = 30°) rigid CLα = 5.07098 vs NASTRAN −CZα = 5.07097; CMα = −2.87093
  vs NASTRAN −2.871. Previously CLα = 5.757 (×1/cos30° = 1.155 overprediction).
  Unswept validation cases (BYU wing, AR=8 rectangle) are numerically unchanged.

**Step 51 — Trim card set parsing (AESTAT / AESURF / AELIST / TRIM / DIVERG / over-determined)**
- `sbeam/model/aero.py`: 8 new dataclasses — `Aestat`, `Aesurf`, `Aelist`, `Trim`, `Diverg`,
  `Trimvar`, `Trimobj`, `Trimcon`.
- `sbeam/model/bulk_data.py`: 8 new dict fields (`aestats`, `aesurfs`, `aelists`, `trims`,
  `divergs`, `trimvars`, `trimobjs`, `trimcons`).
- `sbeam/parser/bdf_reader.py`: 8 new handlers; dispatch branches for all new keywords;
  post-parse cross-reference validation (AESURF→AELIST, AELIST→CAERO1 box ranges, TRIM label
  refs); DOF-count diagnostic warns on fully-prescribed or over-determined-without-objective TRIM.
- `sbeam/parser/case_control.py`: `SubcaseControl` gains `trim_sid` and `diverg_sid`; parser
  handles `TRIM=` and `DIVERG=` case-control keywords; error message updated to include SOL 144.
- `docs/10_standard/02_card_reference.md`: field tables for AESTAT, AESURF, AELIST, TRIM,
  DIVERG, TRIMVAR, TRIMOBJ, TRIMCON; `TRIM=`/`DIVERG=` added to case-control keyword table.
- `docs/10_standard/05_aeroelastics.md`: updated supported-cards table; Step 51 section
  (data model, cross-reference rules, DOF-count diagnostic, over-determined trim design).

**Phase C — Aero stiffness assembly Q_aa + modal-truncation ROM (Step 50)**
- `sbeam/solver/sol144.py` new module: `run_aeroelastic_static(bulk, subcase, aero, q,
  use_rom, sol103_result)` solves `(K_aa − q·Q_aa)·u_a = q·f_g + f_struct`; recovers
  CBAR forces/stresses. Private helpers: `_build_qaa_aset` (g-set → a-set reduction via
  RBE3 + SPC, always-dense), `_solve_direct`, `_solve_rom` (modal-truncation ROM via
  `coupling.build_gaf`), `_mode_acceleration_recovery` (corrects mode-displacement with
  static flexibility residual using stored `k_aa_lu`).
- `sbeam/results/results.py`: `Sol144Result` dataclass (displacements, bar_forces,
  bar_stresses, q_aa, q, free_dofs, k_aa_lu, modal_coords, phi_free, k_hh, q_hh).
- `sbeam/parser/case_control.py`: SOL 144 added to `_SUPPORTED_SOLS`.
- `tests/aero/test_step50_qaa.py`: 13 V-C3 acceptance tests (all pass).
- `docs/10_standard/05_aeroelastics.md`: Phase C section (governing equation, coupling.py
  API, sol144.py API, Sol144Result fields, V-C3 acceptance criteria).

**Phase B — Force transfer & coupled smoke test (Step 49)**
- `compute_structural_loads(aero_model, q, alpha)` added to `sbeam/aero/aero_model.py`:
  wires the full rigid-aero → structural load path via
  `w_total = -(alpha·normal_z) + wg`, `gamma = ajj_inv_corr @ w_total`,
  `f_box = skj @ gamma`, `f_g = q * g_disp.T @ f_box`.
  Raises `ValueError` if `g_disp is None` (caller must supply `grid_index` to `build_aero_model`).
- BDF integration fixture `tests/integration/bdf/val_spline2_cantilever.bdf`:
  4-CBAR cantilever, 4-box CAERO1, SPLINE2 via CORD2R CID=1, full-span AEROS.
- `tests/integration/test_phase_b.py` (V-B2a–d): virtual-work force balance (< 1e-10),
  CL magnitude plausibility (< 2%), alpha=0 agreement with `build_fg` (< 1e-12),
  and `ValueError` guard. 194 total tests pass.

**Phase B — ATTACH rigid-body spline (Step 47)**
- `_build_attach_rows()` implemented in `sbeam/aero/spline.py`: rigid lever-arm coupling
  of a box group to a single master GRID via `ATTACH` card. Fills `g_slope`
  (`col_Rx = +1.0` torsion, `col_Ry = -1.0` pitch) and `g_disp` normal z-rows with
  lever-arm cross-product `(ω×r)_z = Rx·ry − Ry·rx`.
- ATTACH loop in `build_g_spline()` replaces Step 46 placeholder warning.
- `NotImplementedError` raised for `CID ≠ 0`; `ValueError` for unknown master GRID.
- V-B3 test class (4 tests) in `tests/aero/test_spline.py`: machine-precision rigid-body
  gate (Tz→0, Ry→-1) and force-transfer lever-arm check (Fz/Mx/My vs analytical).
  SPLINE0 zero-force and zero-slope verified alongside ATTACH. 20 total tests pass.

**Phase B — Structure ↔ Aero Splining (Steps 45–46)**
- `SET1` card parsed (Pattern B multi-continuation, same template as `SPC1`/`RBE2`);
  `Set1` dataclass added to `model/aero.py` and `BulkData`.
- `SPLINE2` card parsed (Pattern A with optional DTHX/DTHZ/USAGE continuation);
  `Spline2` dataclass with full field set including defaults (DZ=0.0, DTOR=1.0,
  DTHX=1.0, DTHZ=0.0, USAGE="BOTH"); cross-reference validation at end of
  `parse_bulk_data` (SETG → SET1, CAERO → CAERO1, SET1 grids → GRID).
- `Attach`, `Spline0`, `Spline1` stub dataclasses added; `SPLINE1` parser handler raises
  `NotImplementedError`; `ATTACH` and `SPLINE0` parse to their dataclasses (builders in Step 47).
- `BulkData` gains: `set1s`, `spline2s`, `attaches`, `spline0s`, `spline1s`.
- New module `sbeam/aero/spline.py` — `build_g_spline(bulk, boxes, grid_index)`:
  - Builds two CID-aware spline operators from SPLINE2 cards using `CubicHermiteSpline`
  - `g_slope` (n_box × 6·n_grid): maps structural g-set DOFs → per-box streamwise incidence
    for the VLM solve (consumed by `coupling.build_qaa`)
  - `g_disp` (3·n_box × 6·n_grid): maps structural g-set DOFs → per-box 3-D displacement
    for virtual-work force transfer back to structure (consumed by `coupling.build_fg`)
  - CID-aware projections via x_hat/y_hat/z_hat from CORD2R: correct for any spline axis
    orientation (standard NASTRAN SPLINE2 convention)
  - Unit-impulse Hermite approach: column-by-column fill using scipy phi_f / phi_d basis
    functions; exact for the cubic Hermite space
  - Coverage tracking: error on doubly-splined box; UserWarning on un-splined box and
    on >10% extrapolation beyond SET1 span range
- `AeroModel` gains `g_slope` and `g_disp` optional fields; `build_aero_model` accepts
  optional `grid_index` parameter and populates both operators when spline cards are present.
- 15 new tests in `tests/aero/test_spline.py`:
  - Parser round-trips and error cases for SET1 and SPLINE2
  - Operator shape validation
  - V-B1 rigid-body gate: uniform Tz → zero downwash (< 1e-12); uniform Ry → uniform
    downwash = 1.0 (< 1e-12); both verify partition-of-unity property of Hermite bases
  - Energy round-trip: `g_disp.T @ (Skj @ cp_unit)` Z-component equals total panel area

**Phase A — Prandtl–Glauert compressibility correction (A4)**
- `AEROS` card now accepts optional field 8 `MACH` (sbeam extension; default 0.0). Specifying
  a Mach number triggers the Göthert similarity correction: panel y,z coordinates are
  compressed by β = √(1−M²) before AIC assembly, and the inverted AIC is scaled by 1/β,
  giving the correct subsonic compressible pressure distribution (§2.8 of theory doc, Eq. 14).
  M = 0.0 gives bit-identical results to the incompressible solver; Mach is capped at 0.99.
- `solve_rigid_cl` and `build_aero_model` both accept `mach=` and apply the correction.
- 4 new tests in `TestPrandtlGlauert` verify identity at M=0, y-compression, CL increase
  bounded by 1/β, and the M=0.99 cap.

**Phase A — Steady VLM Aeroelastics (Steps 39–46)**
- `AEROS` card — reference geometry (`cref`, `bref`, `sref`) and symmetry flags (`symxz`,
  `symxy`); enforces CAERO1-without-AEROS validation at parse time.
- `CAERO1`, `PAERO1`, `AEFACT`, `W2GJ` cards — aerodynamic panel definition, box meshing
  (quarter-chord bound vortex / three-quarter-chord collocation), and geometric incidence input.
- `sbeam/aero/vlm.py` — steady horseshoe VLM: Biot-Savart kernel, AIC matrix assembly,
  symmetric (+1) and antisymmetric (-1) XZ-plane image vortices, `solve_rigid_cl` for
  rigid-wing CL/CM/CDi/e at a given alpha/beta; `trefftz_cdi` for Trefftz-plane induced drag
  coefficient (CDi) and Oswald span efficiency (e).
- `sbeam/aero/integration.py` — integration matrices `Skj` (force recovery), `Djk`
  (normalwash mapping), and baseline normalwash vector `w_g`.
- `sbeam/aero/corrections.py` — AIC correction tiers: diagonal box weight (Wkk), pressure
  correction (WT2), and strip force correction (WT1). LU-factored AIC inverse
  (`np.linalg.solve`) replaces prior SVD (`np.linalg.lstsq`), reducing build time approx. 25x on
  large panel models.
- `sbeam/aero/aero_model.py` — `AeroModel` container; `build_aero_model` factory.
- Sideslip angle beta: VTP/fin surfaces produce sideforce (CY) at non-zero beta; lift (CL/CM) and
  sideforce (CY) separated by surface normal in `solve_rigid_cl` result dict.
- Viewer Aero tab: 3D aerodynamic box mesh, per-panel Cp colour overlay, spanwise section-CL
  strip chart, optional corrected vs inviscid Cp overlay.
- `sample/val_vlm_rect_ar8.bdf` — rectangular AR=8 validation case.
- `sample/val_vlm_byu_wing.bdf` — AVL-validated AR-7.5 tapered/swept benchmark; CL within
  0.16%, CM within 0.25% of AVL.

**BDF cards**
- `CORD2R` — user-defined rectangular coordinate systems for grid input positions (CP),
  result output frames (CD), load directions, and CONM2 offset/inertia. Chained RID
  references supported. All internal computation remains in global CID 0.
- `GRAV` — uniform body acceleration applied to all mass-bearing DOFs; works with CBAR
  distributed mass and CONM2 point masses; combinable via LOAD card; echoed in f06 OLOAD
  output.
- `RBE2` — rigid element: all dependent DOFs (CM string) at each GM grid are set equal to
  the corresponding DOF at the independent grid GN. Displayed as solid red lines in the viewer.
- `CBUSH` — generalised spring-damper element with up to 6 independent stiffness values
  (K1–K6 via PBUSH). Grounded elements (GB blank) supported. Displayed as a spring-coil
  polyline in the viewer. CBUSH element forces recovered and written to f06 under SOL 101.
- `RBAR` — rigid bar element with full lever-arm kinematics: translations at the dependent
  end (GB) include the cross-product contribution `θ_GA × d` where `d = r_GB − r_GA`.
  Displayed as solid purple lines in the viewer.
- `CONM2` offset and inertia tensor fully verified: 3×3 inertia tensor (I11–I33), CID-frame
  offset vector (X1/X2/X3) rotated to global via `R @ r_cid`, and parallel-axis theorem
  applied in the mass matrix. GPWG and viewer geometry corrected to apply the same CID→global
  transform when computing CG position and offset line.

**Viewer**
- Case Control UI redesign: separate Executive Control and Subcases sections; SOL-dependent
  output request checkboxes (only fields relevant to the active SOL are shown); collapsed
  Advanced expander for INCLUDE path; Download BDF button with inline BDF preview; immutable
  "Loaded BDF" snapshot shown in a read-only expander when a run file is uploaded.
- GRAV load direction visualised as a scaled arrow cone at the model centroid.
- CBUSH rendered as spring-coil polyline; RBE2 as solid red lines; RBAR as solid purple lines.

**Infrastructure**
- GitHub Actions CI pipeline: `pytest` + `ruff` lint on every push and PR to `main`;
  matrix covers Python 3.9, 3.11, 3.12.
- `pytest-cov` coverage measurement with branch coverage; explicit 85% floor gate command
  for `solver/`, `assembly/`, and `parser/` modules.
- AppTest end-to-end viewer tests covering the full SOL 101 and SOL 103 render+run flows.
- `docs/10_standard/02_card_reference.md` — field-level BDF card reference for all 17 implemented bulk
  data cards and all case control keywords.

### Changed
- **Documentation reorganised** into four numbered sections under `docs/` by document type:
  `10_standard/` (code standard), `20_theory/` (theory & worked examples), `30_future/`
  (backlog, plans, design proposals), and `40_history/` (completed-development record and
  archive). Added `docs/00_INDEX.md` as the navigation entry point. The root planning files
  (`development_plan_bugs_todo.md`, `static_aero_plan.md`, `static_aero_plan_zaero_review.md`)
  moved into `docs/30_future/`; the redundant root `todo.md` was merged into the backlog and
  removed. All internal cross-references updated.

### Fixed

**Phase A fixes**
- **A2/A3 — AEROS reference geometry and moment reference point:** `solve_rigid_cl` now
  uses AEROS `sref`/`cref` for CL/CM normalisation; per-surface classification separates
  lift surfaces (contribute to CL/CM) from sideforce surfaces (contribute to CY); moment
  reference `xref` parameter added (default 0.0).
- **A9 — CM moment arm corrected from three-quarter-chord to quarter-chord:** pitching-moment
  arm changed from the three-quarter-chord collocation point to the quarter-chord bound-vortex
  location where the Kutta-Joukowski force acts. Error was mesh-dependent (bias = CL * half-box-chord /
  c_ref, vanishing as NCHORD tends to infinity). CM now matches AVL to 0.25% on the BYU AR-7.5 benchmark.
- **A1 confirmed non-defect:** VLM lift-slope deficit (A1) validated against BYU
  VortexLattice.jl (AVL-validated); sbeam tracks the peer code to a constant 0.16% offset at
  every spanwise resolution. Deficit was an artefact of comparing to lifting-line upper bounds.

**Code review fixes**
- **C-1 — SOL 103 generalised mass hard-coded:** f06 GENERALIZED MASS column was always
  written as `1.0`. Now computed as `phi^T M phi` per mode. Correct (1.0) for `norm=MASS`;
  non-trivial for `norm=MAX`. `Sol103Result.generalized_masses` field added.
- **R13 — EIGRL V1/V2 frequency bounds:** V1/V2 were parsed and stored but silently ignored.
  `solve_modes` now emits a `UserWarning`; `docs/10_standard/04_modal_analysis.md` corrected to state
  that V1/V2 filtering is not implemented; use the `ND` field to limit mode count.
- **R14 — MAT1 G derived from isotropic relationship:** G was silently stored as 0.0 when
  the G field was blank, zeroing torsional stiffness. Now derived as `G = E / (2(1+nu))` when
  G is blank and both E and nu are non-zero. Supplied G always takes precedence.
- **R15 — SPC1 multi-continuation grids:** only the first continuation line was consumed;
  grids on subsequent lines were silently dropped. Now accumulates all continuation lines using
  the same loop pattern as RBE2/RBE3.
- **R10 — RBE3 lever-arm limitation documented:** block comment added in `assembly/rbe3.py`;
  "Known limitation" paragraph added to `docs/10_standard/01_beam_model.md` directing users to RBAR for
  kinematically exact rigid connections with offset.

**Existing fixes (Phase 1 bugs)**
- **Case control UI subcase export (B1):** Per-subcase field values (LOAD, SPC, output
  flags) now read from `st.session_state` after form submission, not from the pre-submission
  dict. Eliminates stale-value export when multiple subcases are defined.
- **Multi-subcase solver (B3):** `run_sol101` and `run_sol103` previously silently used only
  the first subcase. Solvers now accept a single `SubcaseControl` argument; the viewer loops
  over all subcases and stores results as `dict[subcase_id, result]`; the results panel shows
  a Subcase selector when more than one result is present.
- **Deformed shape hover (B2):** Hover tooltip on deformed nodes now shows raw physical
  displacements (Tx, Ty, Tz) instead of scaled plot coordinates.
- **CONM2 CG in GPWG and viewer:** CG marker and offset line for CONM2 with CID not equal to 0 now
  correctly apply the CID-to-global rotation before adding the offset to the grid position.
- **CBAR zero-length guard:** `transform_matrix` raises `ValueError` when GA and GB are
  coincident, matching the existing guard for CBUSH.
- **SPC reaction recovery with body loads (GRAV):** Reactions now computed as
  `R = K[spc,:] @ u - f[spc]` so that forces applied at constrained DOFs (which contribute
  to equilibrium but produce zero displacement) are correctly included in the reaction sum.

---

## [0.1.0] — Phase 1 Complete

Initial release: SOL 101 static analysis and SOL 103 normal modes for Euler-Bernoulli beam
models in NASTRAN BDF input format.

### Added

**BDF parser**
- Free-field and fixed-field BDF line parsing.
- Bulk data cards: `GRID`, `CBAR` (with orientation vector and pin releases PA/PB), `PLOTEL`,
  `CONM2` (point mass), `PBAR`, `MAT1`, `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `EIGRL`.
- Case control section: `SOL`, `TITLE`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `DISPLACEMENT`,
  `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `BEGIN BULK`, `ENDDATA`.
- `INCLUDE` statement for separating bulk data from case control.
- `parse_bdf(filepath)` — reads a full run file (case control + bulk data via INCLUDE).
- `parse_bulk_file(filepath)` — reads a bulk-data-only `.dat` or `.bdf` file.
- Validation: duplicate GIDs, missing PIDs/GIDs, invalid DOF strings all raise `ValueError`;
  unknown cards issue a warning and are skipped.

**SOL 101 — Static Analysis**
- 12×12 Euler-Bernoulli local element stiffness matrix with coordinate transformation.
- Global stiffness assembly from all CBAR elements.
- Load vector assembly from `FORCE`, `MOMENT`, and `LOAD` combination cards.
- SPC constraint application by DOF elimination.
- Direct solve via `scipy.linalg.solve`; singular matrix raises `ValueError` identifying
  unconstrained DOFs.
- CBAR end forces/moments and stresses at PBAR recovery points C/D/E/F recovered in element
  local frame.
- SPC reaction forces recovered.
- Verified: cantilever tip deflection `PL³/3EI` < 0.1%; simply-supported mid-span deflection
  `PL³/48EI` < 0.1%; fixed-end moment `PL` < 0.1%; reactions sum to applied load < 0.1%;
  cantilever tip torque `θ_x = TL/GJ` < 0.1%.

**SOL 103 — Normal Modes**
- 12×12 consistent mass matrix per CBAR element; CONM2 point mass assembled into global
  mass matrix.
- Generalised eigenvalue solve via `scipy.linalg.eigh`; EIGRL frequency range and mode
  count limits applied.
- MASS and MAX normalisation modes.
- Verified: cantilever f₁ = `(1.875²/2π)√(EI/ρAL⁴)` < 1%; free-free first 6 modes
  < 1×10⁻⁴ Hz; simply-supported f₁ = `(π²/2πL²)√(EI/ρA)` < 1%.

**CBAR pin releases**
- PA/PB DOF release flags zero the released rows/columns in the local stiffness matrix
  before transformation, enabling pinned-end connections and simply-supported models.

**GPWG — Mass and CG**
- Total structural mass and centre of gravity computed from CBAR distributed mass (via
  consistent mass matrix diagonal) and CONM2 point masses.

**f06 output**
- SOL 101: applied load echo, nodal displacements, SPC reactions, CBAR end forces/moments,
  CBAR stresses at recovery points — NASTRAN-compatible column format.
- SOL 103: natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions.
- Displacement and mode-shape output rotated into each grid's CD output frame.

**Streamlit viewer**
- 3D Plotly model display: GRID nodes, CBAR beam lines, PLOTEL dashed lines, RBE3 dashed
  cyan, CONM2 markers.
- Click-to-select grid/element with details panel.
- Tabbed properties tables: Grids, Elements, Properties, Materials, Loads, Constraints.
- GPWG summary panel.
- Case control form: SOL selection, TITLE, subcase LOAD/SPC assignment, METHOD (EIGRL),
  output request checkboxes; BDF export with INCLUDE.
- Run Analysis button: calls solver in-process; errors shown as banners.
- SOL 101 results: deformed shape overlay with scale factor slider; displacement, reaction,
  bar force, and stress tables.
- SOL 103 results: mode selector; animated mode shape cycling ±maximum; frequency display;
  modal mass fraction bar chart.
- Handles both bulk-data-only files and full run files on upload.

**Sample model**
- `sample/simple_beam.dat` — 10 m steel cantilever, 5 CBAR elements, SI units.

**Documentation**
- `docs/10_standard/00_program_overview.md` — developer and user guide; module structure; coding standards; testing.
- `docs/10_standard/01_beam_model.md` — BDF card reference; data model.
- `docs/10_standard/03_static_analysis.md` — SOL 101 algorithm; stiffness matrix derivation; load assembly.
- `docs/10_standard/04_modal_analysis.md` — SOL 103 algorithm; mass matrix derivation; eigenvalue solution.
- `docs/10_standard/06_viewer.md` — viewer architecture; session state; Plotly figure structure.
- `docs/20_theory/00_beam_methods.ipynb` — Euler-Bernoulli theory; stiffness and mass matrix derivations;
  coordinate transformation; eigenvalue solution.
