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

