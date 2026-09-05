# Completed Development — SOL 103 Modal Solver

Part of the completed-development record (index: `00_completed_development.md`).
Covers the SOL 103 normal-modes path: consistent mass matrix, eigenvalue solve,
f06 output, and resolved SOL 103 defects.

---

## Phase 4 — Modal Solver (SOL 103)

### Step 14: Consistent Mass Matrix ✅ COMPLETE

**Objective:** Implement the 12×12 consistent mass matrix for a CBAR element and assemble the global mass matrix.

**Deliverables:**
- `assembly/mass_matrix.py` — `local_mass(pbar, mat1, L)`, `element_mass_global(cbar, grids, pbars, mat1s)`, `assemble_global_mass(bulk)`.
- `tests/assembly/test_mass.py`

---

### Step 15: SOL 103 Eigenvalue Solve ✅ COMPLETE

**Objective:** Solve the generalised eigenvalue problem and extract natural frequencies and mode shapes.

**Deliverables:**
- `solver/sol103.py` — `solve_modes(K_free, M_free, eigrl) -> (frequencies_hz, mode_shapes)`.
- `results/results.py` extended — `Sol103Result` dataclass.
- `tests/solver/test_sol103.py`

**Test / Acceptance:**
- Cantilever beam, 10 elements: f₁ = (1.8751²/2π) × √(EI/ρAL⁴) ± 1%.
- Free-free beam (no SPC), 10 elements: first 6 eigenvalues < 1e-4 Hz (rigid body modes).
- Simply supported beam, 10 elements: f₁ = (π²/2πL²) × √(EI/ρA) ± 1%.
- MASS normalisation: `phi^T M phi = I` (identity matrix) within 1e-10.
- MAX normalisation: maximum absolute component of each mode = 1.0.

---

### Step 16: .f06 Output — SOL 103 ✅ COMPLETE

**Objective:** Write SOL 103 results to .f06 format.

**Deliverables:**
- `results/f06_writer.py` extended — `write_f06_sol103(filepath, case_control, bulk, result)`.
- `tests/results/test_f06_sol103.py`

---


## Resolved defects

### DD-3 (P3, release hygiene batch) — `beam_vib` deck headers and the RBE2 doc pointer ✅ COMPLETE (2026-08-03)

**Objective:** The 2026-07-31 sample review filed `beam_vib1.bdf` for deletion ("zero
refs; header says 100 kg, card says 10 000") and `beam_vib.bdf`'s `RHO=0` as a defect to
repair. Establish what the two decks actually are before acting.

**Finding — both premises were wrong.** Git history settles it:
- `a4fc728` — `beam_vib.bdf` originally *was* the "100 kg at node 7 via RBE3, RHO=7850"
  deck its header describes. That commit **deliberately converted it** into a tip-mass
  demonstration: `RHO → 0.0`, mass moved to node 6 at 100 000 kg, `GRID 7`/`RBE3`/`PLOTEL`
  removed. `beam_vib1.bdf` was created in the same commit as a copy of the *original*
  (mass 100 → 10 000). So the two decks are not duplicates — one is a zero-density
  tip-mass case, the other a distributed-mass RBE3-offset case — and both inherited the
  same now-false header.
- `RHO=0.0` is therefore intentional. The deck's fundamental is the closed-form
  single-DOF result `f1 = √(3EI/mL³)/2π = 0.3564 Hz`, and the ~10⁶-Hz modes 4–5 the
  backlog flagged as junk are the expected rank-deficiency artifact of a massless beam
  carrying one lumped mass. "Fixing" `RHO` would have destroyed the deck's purpose.
- `b0d81b5` later added `GRID 7` + `PLOTEL` + `RBE2` + `CONM2` on node 7 to `beam_vib.bdf`,
  and `516016a` removed them again — **without updating
  `docs/10_standard/04_modal_analysis.md`**, which had been written against that
  intermediate state.

**Deliverables:**
- `sample/beam_vib.bdf` — header rewritten to describe the shipped deck (100 000 kg
  directly on node 6, no RBE3, no node 7), with the deliberate `RHO=0`, the closed-form
  `f1`, the expected high-frequency artifacts and the `516016a` history stated explicitly
  so the next reader does not re-file it as broken.
- `sample/beam_vib1.bdf` — header corrected to its own cards (10 000 kg at node 7 via
  RBE3 20), plus the RBE3-offset-inertia caveat and a pointer to
  `val_cantilever_offset_mass_modes.bdf` for genuine offset inertia.
- `docs/10_standard/04_modal_analysis.md` — the RBE2-with-CONM2 example no longer claims
  to be `sample/beam_vib.bdf`. It is now labelled illustrative, with a note recording that
  no shipped deck uses the pattern: the RBE2 gates
  (`tests/integration/bdf/v13_rbe2_rigid_coupling.bdf`, `v18_rbe2_offset.bdf`) carry no
  `CONM2`, and `sample/cessna210_flagship_bulk.bdf` mentions RBE2 only in a comment.

**Test/Acceptance:** both decks parse and solve; measured spectra recorded in the headers
(`beam_vib`: 0.2608 / 0.3514 / 22.51 Hz then artifacts; `beam_vib1`: 1.033 / 1.033 / 11.8
Hz). Full suite green (1741 passed, 6 xfailed).

**Key decisions:**
- **Keep both decks, keep each card value, fix the headers.** The defect was never the
  cards — it was two stale headers and a doc citing deleted cards. No deck content changed,
  so nothing downstream moved.
- **Do not restore the RBE2 to `beam_vib.bdf` to make the doc true.** `516016a` removed
  those cards deliberately enough to be its own decision; the cheaper and more honest fix
  is to stop the doc claiming a file it cannot back up.

### DD-1 (P3, release hygiene batch) — `val_wing_taper_dihedral.bdf` kept, A/B pair anchored ✅ COMPLETE (2026-08-03)

**Objective:** The sample review filed the deck as a zero-ref duplicate of `_twist` minus
its W2GJ block. Verify before deleting.

**Finding:** the "byte-identical minus W2GJ" half was right — `diff` shows only the W2GJ
block and comments differ. "Zero refs" was wrong twice over: it is the `taper_dih` case in
`tests/aero/test_vae3_cross_check.py:62` (the DEF-M2 canted-deck force-convention check),
and it is the *controlled* half of the W2GJ washout A/B pair documented at
`05a_aero_vlm.md:1043` — a claim that needs both decks and is gated by no test.

**Deliverables:** deck kept. Both `val_wing_taper_dihedral.bdf` and `_twist` headers now
record the measured pair (CL = 0.2669 no-twist vs 0.1851 with 0→−2° washout, rigid VLM at
α = 3°) and say why neither may be deleted as a duplicate. The 05a figures were refreshed:
the doc's 0.268/0.186 predated DEF-M2 and were high by exactly the body-axis projection
factor (`0.268·cos 5° = 0.2670`).

**Key decision:** **keep, do not repoint.** Substituting `_twist` into VAE3 was tested and
passes (15 passed) — Path A drives with the ANGLEA column alone and excludes `wg`, which
is why the W2GJ-carrying `ha144a` deck is already in that set. But the deletion would still
have cost the documented A/B baseline, to save one 60-line deck.

### DD-9 (P3, release hygiene batch) — HA144A wing-spline extrapolation documented ✅ COMPLETE (2026-08-03)

**Objective:** The sample review asked to "extend the ha144a canard SET1 span to silence
the SPLINE2 extrapolation warnings emitted on every run".

**Finding — the proposed edit is not performable.** Two premise errors:
- **Wrong spline.** The warnings are on `SPLINE2 1601`/`2601`, the **wing** splines
  (CAERO1 1100/2100, SET1 1100/2100). The canard splines 1501/2501 (SET1 1000/2000 =
  grids 98, 99) emit nothing.
- **Nothing to extend to.** Wing SET1 1100 spans y = 0 → 15 (outermost stringers 121/122);
  the wing CAERO1 runs to y = 20 with NSPAN 8, so exactly one of eight box strips
  (collocation y = 18.75) sits 25 % beyond the range and trips the 10 % band in
  `sbeam/aero/spline.py:171`. The outermost structural grid in the entire model is
  y = ±15. Silencing the warning would require inventing structure MSC did not model or
  shortening the published aero panel.

**Deliverables:** the warning is documented as expected, not suppressed. All five decks
that define SET1 1100 and emit it (`ha144a_fullspan_sbeam`, `ha144a_body_trim`,
`ha144a_fullspan_mloads`, `ha144a_massset_sweep`, `ha144a_mloads_massset`) carry an
`EXPECTED WARNING` block at the spline-set definition explaining the y=15 structure
against the y=20 panel, and why it cannot be fixed without changing the reference case.

**Key decisions:**
- **Do not relax the 10 % threshold.** Widening it to ~30 % would silence this deck at the
  cost of no longer flagging genuinely under-splined surfaces on every other model —
  degrading a true diagnostic for cosmetics.
- **Risk re-assessed from Medium to Low.** With documentation rather than a spline change,
  nothing numerical moves and no ≤ 0.3 % published-value gate needs re-baselining.

### Sample hygiene — `val_cantilever_modes.bdf` f₂ comment and `HA144A.bdf` archive notice ✅ COMPLETE (2026-08-03)

- `sample/val_cantilever_modes.bdf` claimed `f₂ (mode 2 bending in XY) ≈ 2.58 Hz` on the
  strength of the symmetric square section. The deck's own second `SPC1` (`SPC1, 1, 12,
  11, … 2`) constrains DOFs 1 and 2 on every node, suppressing the whole XY family, so f₂
  is the **second XZ bending mode** at 16.16 Hz — which VAL2's `test_second_bending_mode`
  already gates. Header corrected, with the measured 2.5784 / 16.1591 / 45.2561 Hz recorded
  and the β·L values named.
- `sample/HA144A.bdf` gains an archive notice: not runnable by design (verbatim MSC
  listing using cards sbeam does not implement; fails at `CBAR 101: property PID=100 not
  found`), kept for the published Table 7-1 reference values, with a pointer to the
  runnable transcription `sample/ha144a_fullspan_sbeam.bdf`.

### C-1: SOL 103 Generalised Mass Hard-coded to 1.0 ✅ FIXED

**Root cause:** `results/f06_writer.py` wrote `1.0` unconditionally in the GENERALIZED MASS column of the Real Eigenvalue Table. For `norm=MASS` this is correct (M-orthonormal eigenvectors satisfy `phi^T M phi = I`). For `norm=MAX` (peak-component normalisation) the eigenvectors are scaled to unit peak, so `phi^T M phi != 1.0` in general. Any downstream tool reading the column under `norm=MAX` received a fabricated value with no warning.

**Fix:**
- `sbeam/results/results.py` — added `generalized_masses: np.ndarray` field (shape `(n_modes,)`) to `Sol103Result`.
- `sbeam/solver/sol103.py` — after each `solve_modes` call (both the RBE3 and non-RBE3 branches), computes `gen_masses[i] = float((M_free @ phi_free[:, i]) @ phi_free[:, i])` using the original unregularised `M_free`. Works for both sparse (non-RBE3) and dense (RBE3) mass matrices. Result stored in `Sol103Result.generalized_masses`.
- `sbeam/results/f06_writer.py:228` — replaced hard-coded `_fmt(1.0)` with `_fmt(gm)` drawn from `result.generalized_masses`.
- `docs/10_standard/04_modal_analysis.md` — updated Mode Shape Normalisation section to document that GENERALIZED MASS = `phi^T M phi` (1.0 only for `norm=MASS`).

**Tests added (`tests/results/test_f06_sol103.py::TestGeneralizedMass`):**
- `test_norm_mass_all_unity` — all `result.generalized_masses ≈ 1.0 (abs=1e-8)` for `norm=MASS` cantilever.
- `test_norm_max_not_unity` — at least one `generalized_masses[i] != 1.0` for `norm=MAX` cantilever.
- `test_f06_gen_mass_column_norm_mass` — parses GENERALIZED MASS column from f06 text; all values ≈ 1.0.
- `test_f06_gen_mass_column_norm_max` — parses column from `norm=MAX` f06; values match `result.generalized_masses` within 1e-5 relative.

**Acceptance test:** 497 total tests pass, 0 failures.

---

