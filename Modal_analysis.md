# Modal_analysis.md — SOL 103 Normal Modes Analysis

## Overview

SOL 103 computes the natural frequencies and mode shapes of the undamped structural system. The generalised eigenvalue problem is:

```
[K]{phi} = omega^2 [M]{phi}
```

Where:
- `[K]` is the global stiffness matrix
- `[M]` is the global mass matrix
- `omega` is the natural circular frequency (rad/s)
- `{phi}` is the mode shape (eigenvector)

Natural frequency in Hz: `f = omega / (2 * pi)`

---

## Beam Theory

Same Euler-Bernoulli assumptions as SOL 101 (see `Static_analysis.md`).

---

## Mass Matrix

Phase 1 uses a **consistent mass matrix**. The consistent formulation distributes the element mass using the same shape functions as the stiffness matrix. This gives more accurate natural frequencies than the lumped mass approach, particularly for bending modes.

Each CBAR element contributes a 12×12 local consistent mass matrix `[m_e]` based on element length L, cross-sectional area A, and material density rho from the referenced MAT1:

- Translational inertia: `rho * A * L` terms distributed via cubic Hermite shape functions
- Rotational inertia: second-order terms (can be optionally included or excluded)

CONM2 concentrated masses contribute a full 6×6 symmetric block to the global mass matrix at the referenced grid's DOFs: translational mass `m·I₃`, offset-induced translation-rotation coupling `−m·skew(r)`, and rotational inertia from the parallel axis theorem plus the CM inertia tensor (I11–I33). For zero offset and no inertia tensor, only the translational diagonal is affected.

---

## Global Mass Assembly

1. Initialise `M_global` as a `(6N × 6N)` zero matrix.
2. For each CBAR element: compute local consistent mass matrix `[m_e]` and transform to global coordinates using the same `[T]` as used for the stiffness matrix.
3. Scatter into `M_global` at DOF positions of GA and GB.
4. For each CONM2: assemble the full 6×6 symmetric mass block into `M_global` at the referenced grid's DOF base. Block includes: `m·I₃` (translational), `−m·skew(r)` / `m·skew(r)ᵀ` (coupling, non-zero only when offset r ≠ 0), and `I_cm + m·(|r|²·I₃ − r·rᵀ)` (rotational, parallel axis + CM inertia).

---

## RBE3 Constraint Assembly

RBE3 elements are applied as a DOF transformation (same approach as SOL 101 — see `Static_analysis.md`).

**Insertion point in `run_sol103`** — after full assembly, before SPC partitioning:

```
K_red = Tᵀ K T
M_red = Tᵀ M T
spc_dofs mapped from full-space → reduced-space indices
K_free, M_free partitioned from K_red, M_red
phi_free solved (reduced space)
phi_full = T @ phi_red   (phi_red is phi_free expanded to n_red DOFs)
```

Mode shapes in `full_phi` thus include the interpolated displacement at the dependent (REFGRID) grids.

---

## Eigenvalue Solution

### Boundary Condition Application

SPC constraints are applied by elimination (same as SOL 101):

1. Identify constrained DOF indices from the active SPC set (mapped to reduced-space indices when RBE3 is present).
2. Remove constrained rows/columns from both `K_red` (or `K_global`) and `M_red` (or `M_global`) to obtain `K_free` and `M_free`.

### Solver

```python
eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, M_free)
```

`scipy.linalg.eigh` is used (symmetric positive semi-definite matrices). Returns eigenvalues sorted in ascending order.

Natural circular frequencies: `omega = sqrt(max(eigenvalue, 0))`  
Natural frequencies: `f = omega / (2 * pi)`

The number of modes returned is the lesser of:
- `ND` from the EIGRL card
- Number of free DOFs

Frequency filtering: if V1/V2 are specified on EIGRL, only return modes with `V1 <= f <= V2`.

---

## Free-Free Models

If no SPC constraints are applied, the model is free-free. The first 6 eigenvalues should be zero (or near-zero within numerical tolerance, typically < 1e-6 Hz). These are rigid body modes. They are retained in the output but flagged as rigid body modes.

Tolerance for identifying a zero frequency: `|f| < 1e-4 Hz`.

---

## Mode Shape Normalisation

Controlled by the `NORM` field of EIGRL:

**MASS normalisation (default):**
```
phi_norm = phi / sqrt(phi^T M_free phi)
```
Modal mass = 1.0 for each mode.

**MAX normalisation:**
```
phi_norm = phi / max(abs(phi))
```
Maximum component of each mode shape = 1.0.

---

## Modal Effective Mass

For each mode `i` and each global DOF direction `d` (X, Y, Z translation):

```
L_id = {phi_i}^T {M} {T_d}
effective_mass_id = L_id^2 / (phi_i^T M phi_i)
```

Where `{T_d}` is the unit rigid body vector for direction `d`. Sum of effective mass fractions across all modes in each direction should approach 1.0 for a well-constrained model with sufficient modes extracted.

Effective mass output is optional in phase 1.

---

## .f06 Output (SOL 103)

Output sections written to `results.f06`:

1. **NASTRAN Executive and Case Control echo** (abbreviated)
2. **Real Eigenvalue Table** — mode number, eigenvalue (rad²/s²), frequency (Hz), generalised mass, generalised stiffness
3. **Mode Shape Table** — for each mode: GID, T1, T2, T3, R1, R2, R3 (normalised per NORM setting)
4. **Effective Mass Fractions** (optional) — per mode and per direction

---

## Verification Cases

### Case 1 — Cantilever Beam, Fundamental Frequency

- Configuration: fully fixed at x=0, free at x=L; uniform CBAR elements along x-axis.
- Analytical first bending frequency:
  ```
  f_1 = (beta_1^2 / 2*pi) * sqrt(EI / rho*A*L^4)
  ```
  where `beta_1 * L = 1.8751` (first root of the cantilever characteristic equation).
- Tolerance: < 1% relative error (consistent mass matrix converges well).

### Case 2 — Free-Free Beam, Rigid Body Modes

- Configuration: no SPC constraints.
- Expected: first 6 eigenvalues ≈ 0 (rigid body modes).
- Tolerance: |f| < 1e-4 Hz for all rigid body modes.

### Case 3 — Simply Supported Beam, First Bending Mode

- Analytical first frequency:
  ```
  f_1 = (pi^2 / 2*pi*L^2) * sqrt(EI / rho*A)
  ```
- Tolerance: < 1% relative error.

---

## Solver Module: `solver/sol103.py`

Key functions:

```python
def run_sol103(bulk: BulkData, case: SubcaseControl) -> Sol103Result:
    ...

def assemble_mass(bulk: BulkData) -> np.ndarray:
    ...

def solve_eigenproblem(
    K_free: np.ndarray,
    M_free: np.ndarray,
    eigrl: Eigrl
) -> tuple[np.ndarray, np.ndarray]:
    ...

def normalise_modes(
    eigenvectors: np.ndarray,
    M_free: np.ndarray,
    norm: str
) -> np.ndarray:
    ...
```
