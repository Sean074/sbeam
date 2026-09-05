# SOL 103 — Normal Modes Analysis

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

Same Euler-Bernoulli assumptions as SOL 101 (see `docs/10_standard/03_static_analysis.md`).

---

## Mass Matrix

Phase 1 uses a **consistent mass matrix**. The consistent formulation distributes the element mass using the same shape functions as the stiffness matrix. This gives more accurate natural frequencies than the lumped mass approach, particularly for bending modes.

Each CBAR element contributes a 12×12 local consistent mass matrix `[m_e]` based on element length L, cross-sectional area A, and material density rho from the referenced MAT1:

- Translational inertia: `rho * A * L` terms distributed via cubic Hermite shape functions
- Rotational inertia: second-order terms (can be optionally included or excluded)

CONM2 concentrated masses contribute a full 6×6 symmetric block to the global mass matrix at the referenced grid's DOFs: translational mass `m·I₃`, offset-induced translation-rotation coupling `−m·skew(r)`, and rotational inertia from the parallel axis theorem plus the CM inertia tensor (I11–I33). When the CONM2 CID field is non-zero, the offset vector `r` and inertia tensor `I` are rotated from the CID frame into global CID 0 before assembly (`R @ r` and `R @ I @ Rᵀ`). For zero offset and no inertia tensor, only the translational diagonal is affected.

---

## Global Mass Assembly

1. Initialise `M_global` as a `(6N × 6N)` zero matrix.
2. For each CBAR element: compute local consistent mass matrix `[m_e]` and transform to global coordinates using the same `[T]` as used for the stiffness matrix.
3. Scatter into `M_global` at DOF positions of GA and GB.
4. For each CONM2: assemble the full 6×6 symmetric mass block into `M_global` at the referenced grid's DOF base. Block includes: `m·I₃` (translational), `−m·skew(r)` / `m·skew(r)ᵀ` (coupling, non-zero only when offset r ≠ 0), and `I_cm + m·(|r|²·I₃ − r·rᵀ)` (rotational, parallel axis + CM inertia).

---

## RBE3 Constraint Assembly

RBE3 elements are applied as a DOF transformation (same approach as SOL 101 — see `docs/10_standard/03_static_analysis.md`).

Since Step 59 the RBE3-then-SPC reduction is the **shared a-set path**
`sbeam/assembly/reduction.py:reduce_to_aset(bulk, grid_index, spc_sid)`, used
identically by SOL 103, SOL 144, and the Phase G0 maneuver solver. In
`run_sol103` — after full assembly:

```
red    = reduce_to_aset(bulk, grid_index, spc_sid)   # T + a-set partition
K_free = red.reduce_matrix(K)    # Tᵀ K T then SPC partition (RBE3 present)
M_free = red.reduce_matrix(M)    # sparse K/M stay sparse when no RBE3
phi_free solved (a-set)
phi_full = T @ phi_red   (phi_red is phi_free scattered to n_red DOFs)
```

`reduce_matrix` preserves input sparsity when no dependent DOFs exist, so the
sparse `eigsh` shift-invert path for large SPC'd models is unchanged.

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

**Negative-eigenvalue diagnostic:** if any eigenvalue is below `−1.0 rad²/s²` after solving, a `UserWarning` is emitted listing the count and suggesting the model may have a mechanism or missing constraint. Values between `−1.0` and `0` (typical numerical noise for near-zero rigid-body modes) are clipped silently.

The number of modes returned is the lesser of:
- `ND` from the EIGRL card
- Number of free DOFs

**V1/V2 frequency filtering is not implemented in sbeam Phase 1.** If V1 or V2 are present on the EIGRL card, sbeam emits a `UserWarning` and returns all ND modes regardless of the bounds. Use the ND field to limit the number of extracted modes.

---

## Zero-Density Beams with CONM2

When `rho = 0` and a CONM2 provides point mass without rotational inertia (I11–I33 all zero), only the three translational DOFs at the mass node receive non-zero diagonal entries in `M`. All rotational DOFs at the mass node, and all DOFs at non-CONM2 nodes, are zero — making `M` singular. `scipy.linalg.eigh` requires a positive-definite `b` matrix and raises `LinAlgError` without correction.

**Fix (applied in `solve_modes`):** Tikhonov regularisation adds `max_mass × 1e-12` to the diagonal of any zero-mass DOF before calling `eigh`. Artificial modes introduced by these DOFs appear at frequencies far above 10⁶ Hz and never contaminate the first `nd` physical results.

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
The returned eigenvectors are M-orthonormal: `phi_i^T M phi_j = delta_ij`. Generalised mass = 1.0 for every mode.

**MAX normalisation:**
```
phi_norm = phi / max(abs(phi))
```
Maximum component of each mode shape = 1.0. Generalised mass (`phi^T M phi`) is **not** 1.0 in general; its value depends on the mass distribution and mode shape.

**Generalised mass in the f06:** The GENERALIZED MASS column of the Real Eigenvalue Table is computed as `phi_free_i^T M_free phi_free_i` using the unregularised `M_free`. For `norm=MASS` this evaluates to ≈ 1.0 (within numerical tolerance); for `norm=MAX` the actual physical value is written.

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

### Case 4 — CONM2 Torsional Inertia (V8)

- Configuration: massless cantilever, only Rx DOF free at tip. CONM2 with `i11` specified directly.
- Analytical: `f = sqrt(G·J / (L·i11)) / (2π)`
- BDF: `tests/integration/bdf/v8_conm2_torsional_inertia.bdf`
- Tolerance: < 1% relative error.

### Case 5 — CONM2 Transverse-Offset Torsional Mode (V12)

- Configuration: massless cantilever, only Rx DOF free at tip. CONM2 at tip with `x2=d` (transverse offset). No `i11`.
- Torsional inertia comes from the parallel-axis theorem: `I_eff = m·d²`.
- Analytical: `f = sqrt(G·J / (L·m·d²)) / (2π)`
- BDF: `tests/integration/bdf/v12_conm2_offset_torsion_sol103.bdf`
- Parameters: G=1.0, J=2.0, L=1.0, m=2.0, d=1.0 → I_eff=2.0, f≈0.15915 Hz
- Tolerance: < 1% relative error.
- **Cross-check:** same analytical frequency as V8 (I_eff=2.0 via offset equals i11=2.0 directly).

### Case 6 — Coupled Bending-Torsion Pair from an Offset Tip Mass (shipped sample, 2026-08-01)

- Configuration: steel cantilever (L = 10 m, 10 CBARs, 0.1 m solid square), tip CONM2
  (m = 5000 kg, `x2` = 1.5 m transverse offset, `i11` = 5000 kg·m²). SPC1 suppresses the
  axial and XY-bending families so the deck isolates the coupled Tz/Rx/Ry family. Unlike
  V12, both partitions stay free — the offset mass block (`m·[r]×` coupling + `m·d²`
  parallel-axis) produces two genuinely **coupled** bending-torsion modes.
- Analytical: tip-dominant 2-DOF eigenproblem with Rayleigh beam-mass corrections —
  `M = [[m + (33/140)·ρAL, m·d], [m·d, m·d² + i11 + ρ·Ip·L/3]]`, `K = diag(3EI/L³, GJ/L)`
  → f₁ ≈ 0.1489 Hz (bending-dominant, tip Rx·d/Tz ≈ +0.10), f₂ ≈ 0.7466 Hz
  (torsion-dominant, Rx·d/Tz ≈ −0.99). Measured FE error 1.4e-5 / 9.6e-4 relative.
- BDF: `sample/val_cantilever_offset_mass_modes.bdf` (user-facing; header carries the full
  derivation). CI gate: `tests/integration/test_sample_verification.py`
  (`TestValCantileverOffsetMassModes`), including a decoupling check with the offset zeroed.

### Note — RBE2 and CONM2

Unlike RBE3 (which uses weighted DOF-by-DOF interpolation), RBE2 enforces true rigid-body kinematic coupling. The correct place for a CONM2 representing tip equipment or payload mass is on the **independent (GN) node** of the RBE2. The assembly pipeline applies `M_red = Tᵀ M T` after full-space assembly, which correctly projects the concentrated mass and any offset inertia into the reduced system.

Example (illustrative — see the note below):
```
RBE2,  20, 7, 123456, 6     $ GN=7 (independent), GM=[6] (dependent)
CONM2, 30, 7, 0, 100000.0   $ mass on node 7 = independent node ✓
```

> **No shipped deck currently uses this pattern.** This snippet cited
> `sample/beam_vib.bdf` until 2026-08-03; that deck carried the two cards above only
> between commits `b0d81b5` and `516016a`, and `516016a` removed its `GRID 7`, `PLOTEL`
> and `RBE2` without updating the doc. `beam_vib.bdf` today places its `CONM2` directly
> on the tip node with no rigid element at all. The RBE2 kinematics themselves are gated
> by `tests/integration/bdf/v13_rbe2_rigid_coupling.bdf` and `v18_rbe2_offset.bdf`
> (neither carries a `CONM2`), so the mass-through-RBE2 path above is documented but not
> demonstrated by a sample deck — treat the snippet as the recommended pattern, not as a
> file you can run.

Placing a CONM2 on an RBE2 **dependent (GM) node** is implicitly handled by the same congruence transformation and is mathematically valid, but this configuration is untested. Contrast this with the RBE3 limitation below: for RBE2, the kinematic constraint is exact, so mass at GN is always correctly transferred.

### Note — RBE3 and Offset Mass

Placing a CONM2 at an RBE3-dependent node does **not** correctly transfer torsional inertia from an offset mass. The RBE3 transformation in sbeam uses DOF-by-DOF interpolation (`u_dep = u_indep` for each DOF independently) and does not include rigid-body offset kinematics. As a result, the translational mass at the dependent node maps only to the same translational DOFs on the independent node, with no torsional coupling.

**Correct approach for offset mass:** specify the CG offset directly in the CONM2 `X1/X2/X3` fields at the beam-tip node. The CONM2 assembly applies the parallel-axis theorem automatically, giving `M[Rx,Rx] += m·(X2²+X3²)` torsional inertia.

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

### `Sol103Result` a-set retention (Step 59)

Besides the primary outputs (`frequencies_hz`, `mode_shapes`, `eigenvalues`,
`generalized_masses`), `run_sol103` populates four optional a-set fields
(default `None`, so hand-built results stay valid):

| Field | Contents |
|-------|----------|
| `phi_free` | (n_a, n_modes) a-set mode shapes (pre-expansion) |
| `free_dofs` | a-set indices into the g-set |
| `K_free` / `M_free` | (n_a, n_a) a-set stiffness / mass (dense, or sparse CSR when no rigid elements) |

These are consumed downstream by the Phase G0 modal basis (Step 61) and the
`matrix_gaf_export` GAF loop without re-running the reduction.
