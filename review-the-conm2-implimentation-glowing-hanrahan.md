# Plan: Review CONM2 Implementation and Fix SOL103 Error

## Context

The user reported an error when running SOL 103 (normal modes) with a CONM2 point mass. The goal is to find the root cause, fix it, and write a verification test case — a cantilever beam with aluminium properties, zero beam density, and a CONM2 at the tip — to confirm the fix is correct.

---

## Root Cause

**File**: `sbeam/solver/sol103.py:30`

```python
eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, b=M_free)
```

`scipy.linalg.eigh` requires the `b` matrix to be **positive definite**. When `rho = 0.0`:

- The CBAR consistent mass contribution is zero everywhere (`m_lin = rho * A + nsm = 0`).
- CONM2 only adds mass to the **three translational DOFs** (Tx, Ty, Tz) at the tip node (`mass_matrix.py:106–112`).
- All rotational DOFs, and all translational DOFs at non-CONM2 nodes, have **zero diagonal entries** in `M_free`.
- `M_free` is therefore **positive semi-definite (singular)**, not positive definite.
- `scipy.linalg.eigh` raises `LinAlgError: n-th leading minor of the array is not positive definite`.

The CONM2 mass assembly itself is **correct** — translational-only mass is the right formulation for a scalar point mass without rotational inertia.

---

## Fix

**File**: `sbeam/solver/sol103.py` — inside `solve_modes()`, before calling `eigh`.

Detect zero-mass free DOFs and add a tiny Tikhonov regularisation to those diagonal entries only. The regularisation value is `max_nonzero_mass × 1e-12`, so artificial modes from these DOFs appear at frequencies orders of magnitude above any real mode and never contaminate the first `nd` results.

Replace (line 30):
```python
eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, b=M_free)
```

With:
```python
diag_M = np.diag(M_free)
zero_mass = diag_M == 0.0
if zero_mass.any():
    nonzero_vals = diag_M[~zero_mass]
    eps_m = (nonzero_vals.max() if nonzero_vals.size else 1.0) * 1e-12
    M_solve = M_free.copy()
    M_solve[np.diag_indices_from(M_solve)] = np.where(zero_mass, eps_m, diag_M)
    eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, b=M_solve)
else:
    eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, b=M_free)
```

No other changes to `solve_modes()` or `run_sol103()` are needed.

---

## Test BDF

**File to create**: `sample/cantilever_al_conm2.bdf`

### Model parameters

| Property | Value |
|----------|-------|
| Length | 1.0 m, 10 elements @ 0.1 m, nodes 1–11 |
| Cross-section | 20 mm × 20 mm solid square |
| A | 4.0 × 10⁻⁴ m² |
| I₁ = I₂ | (0.02)⁴ / 12 = 1.333 × 10⁻⁸ m⁴ |
| J | 0.1406 × (0.02)⁴ = 2.250 × 10⁻⁹ m⁴ |
| E | 70.0 × 10⁹ Pa (aluminium) |
| G | 26.3 × 10⁹ Pa |
| ν | 0.33 |
| **ρ** | **0.0 kg/m³ (zero density — all mass from CONM2)** |
| CONM2 mass | 1.0 kg at node 11 (tip) |
| SPC | All 6 DOFs fixed at node 1 |
| EIGRL | ND = 5, NORM = MASS |

### Analytical verification

For a massless cantilever with tip mass `m`, the fundamental bending frequency is:

```
f₁ = (1 / 2π) × √(3EI / mL³)
   = (1 / 2π) × √(3 × 70e9 × 1.333e-8 / (1.0 × 1.0³))
   = (1 / 2π) × √2799.3
   = (1 / 2π) × 52.91
   ≈ 8.42 Hz
```

The square cross-section has equal I₁ = I₂, so modes 1 and 2 are degenerate bending modes (Y-plane and Z-plane) at ~8.42 Hz. Mode 3 is the axial mode at ~842 Hz. Modes 4–5 will be high-frequency artificial modes from the regularised zero-mass DOFs (>> 10⁶ Hz).

---

## Critical Files

| File | Change |
|------|--------|
| `sbeam/solver/sol103.py` | Replace `eigh` call with regularised version (lines 28–30) |
| `sample/cantilever_al_conm2.bdf` | **Create** new test BDF |
| `Modal_analysis.md` | Add note: CONM2 with zero-density beam requires mass regularisation; zero-mass DOFs produce artificial high-frequency modes |
| `Beam_model.md` | Add note: CONM2 contributes translational mass only; rotational inertia not supported in Phase 1 |

---

## Verification

1. Run the new BDF through the solver:
   ```
   python -m sbeam sample/cantilever_al_conm2.bdf
   ```
2. Confirm no `LinAlgError` is raised.
3. Check that modes 1 and 2 are both ≈ **8.42 Hz** (within ~1% of analytical).
4. Check that mode 3 is ≈ **842 Hz** (axial).
5. Re-run `beam_vib.bdf` (steel, rho ≠ 0) to confirm no regression.
6. Run the test suite: `pytest tests/` — all existing tests must still pass.
