# Static_analysis.md — SOL 101 Static Analysis

## Overview

SOL 101 performs a linear static analysis. The global system of equations is:

```
[K]{u} = {f}
```

Where:
- `[K]` is the global stiffness matrix (assembled from CBAR element stiffness matrices)
- `{u}` is the vector of nodal displacements (6 DOFs per grid: Tx, Ty, Tz, Rx, Ry, Rz)
- `{f}` is the global load vector (assembled from FORCE and MOMENT cards, via LOAD combinations)

---

## Beam Theory

**Euler-Bernoulli beam theory** is used. Key assumptions:
- Plane sections remain plane and perpendicular to the neutral axis after deformation.
- Shear deformation is neglected (valid for slender beams with length/depth > ~10).
- Small displacements and linear elastic material.

---

## Element Stiffness Matrix

Each CBAR element contributes a 12×12 local stiffness matrix `[k_e]` in element local coordinates (axes 1, 2, 3), where:
- Axis 1: element axial direction (GA → GB)
- Axis 2, 3: principal bending axes (defined by orientation vector)

The local stiffness matrix captures:
- Axial stiffness: EA/L
- Bending stiffness about axes 2 and 3: EI/L terms
- Torsional stiffness: GJ/L
- Coupled bending/shear terms from Euler-Bernoulli formulation

The local matrix is transformed to global coordinates via:

```
[K_e_global] = [T]^T [k_e] [T]
```

Where `[T]` is the 12×12 transformation matrix built from the element direction cosines.

---

## Global Assembly

Global DOF index for grid `i` (0-based), local DOF `d` (0–5): `idx = 6*i + d`

1. Initialise `K_global` as a `(6N × 6N)` zero matrix where N = number of grids.
2. For each CBAR element: compute `[K_e_global]` and scatter into `K_global` at the DOF rows/columns corresponding to GA and GB.
3. For each CONM2 mass (SOL 101 only relevant if inertia relief is needed — not in phase 1): no stiffness contribution.

---

## Load Vector Assembly

1. Initialise `f_global` as a `(6N,)` zero vector.
2. For each FORCE card in the active load set: rotate the direction vector `[N1, N2, N3]` from the card's CID into global CID 0 (no-op if CID=0), then apply `F × n_global` to DOFs 0–2 of the referenced grid.
3. For each MOMENT card: rotate the direction vector from CID into global, then apply `M × n_global` to DOFs 3–5 of the referenced grid.
4. If a LOAD combination card is active, scale each component set and superpose.

---

## RBE3 Constraint Assembly

RBE3 elements are applied as a **DOF transformation** before SPC partitioning. Implemented in `assembly/rbe3.py`.

`build_rbe3_transformation(bulk, grid_index)` returns `(T, dep_dofs, red_dofs)`:
- **T**: `np.ndarray` shape `(n_dof, n_red)` — maps reduced DOF space → full DOF space
- **dep_dofs**: global DOF indices eliminated (one per constrained DOF of each REFGRID)
- **red_dofs**: remaining DOF indices in ascending order

For each dependent DOF `p` (REFGRID × DOF in REFC), row `p` of T is set to the weighted average of the corresponding independent grid DOFs:

```
T[p, q_i] = w_i / W    where W = Σ w_i
```

All other rows of T are identity. Dependent DOF columns are then removed: `T = T_full[:, red_dofs]`.

**Insertion point in `run_sol101`** — between full assembly and SPC partitioning:

```
K_red = Tᵀ K T
f_red = Tᵀ f
spc_dofs mapped from full-space → reduced-space indices
K_free, f_free partitioned from K_red, f_red
u_red solved
u_full = T @ u_red
```

Reactions are recovered using the **original** K and the recovered full-space `u_full`.

If no RBE3 elements are present, T = I (identity), and the solver path is unchanged.

---

## Boundary Condition Application

SPC constraints are applied by the **penalty / elimination method** (elimination preferred):

1. Identify all constrained DOF indices from the active SPC set (mapped to reduced-space indices when RBE3 is present).
2. Remove the corresponding rows and columns from `K_red` (or `K_global` if no RBE3) to obtain `K_free`.
3. Remove the corresponding entries from `f_red` to obtain `f_free`.
4. Solve: `K_free @ u_free = f_free`
5. Reconstruct full `u_global` by inserting zeros at constrained DOF positions, then applying `u_full = T @ u_red`.

---

## Pin Releases (PA, PB)

Pin releases on a CBAR element free specified DOFs at end A (PA) or end B (PB) before the element stiffness contributes to global assembly.

**Implementation** (`apply_pin_releases(K_local, pa, pb)` in `assembly/stiffness.py`):
- For each DOF code `d` in PA: zero row and column `d-1` (0-based) of the 12×12 local K.
- For each DOF code `d` in PB: zero row and column `d-1+6` (0-based) of the 12×12 local K.
- Pin releases are applied after `local_stiffness()` and before the coordinate transformation.

**DOF code mapping (1-based):**

| Code | Local DOF | Meaning |
|------|-----------|---------|
| 1 | 0 (A), 6 (B) | Axial force (Tx) |
| 2 | 1, 7 | Shear (Ty) |
| 3 | 2, 8 | Shear (Tz) |
| 4 | 3, 9 | Torsion (Rx) |
| 5 | 4, 10 | Bending moment (Ry) |
| 6 | 5, 11 | Bending moment (Rz) |

**Typical use:** PA=PB="456" releases torsion and both bending moments at both ends, making the element behave as a pure truss member (only transmits axial and transverse shear). When combined with SPC constraints that fix rotational DOFs at all free joints, the element provides exactly the truss stiffness matrix.

**Note:** Released DOFs that are not otherwise constrained (by SPC or connected elements) will produce zero-stiffness rows in the global K, causing a singular matrix. Always SPC rotational DOFs at all free joints when using PA=PB="456" truss members.

---

## Solve

```python
u_free = numpy.linalg.solve(K_free, f_free)
```

If `K_free` is singular (`numpy.linalg.LinAlgError`), raise `ValueError`: "Singular stiffness matrix — check for unconstrained DOFs".

---

## Post-Processing

### SPC Reaction Forces

```
f_spc = K_global @ u_global - f_global
```

Extract values at constrained DOF indices.

### CBAR End Forces and Moments

For each element:
1. Extract nodal displacements at GA and GB from `u_global`.
2. Transform to local element coordinates: `u_local = [T] @ u_element`.
3. Compute local end forces: `f_local = [k_e] @ u_local`.
4. Report as: Axial (F1), Shear Y (F2), Shear Z (F3), Torque (M1), Bending Y (M2), Bending Z (M3) at ends A and B.

### CBAR Stress at Recovery Points

For each recovery point (C, D, E, F) on the PBAR:

```
sigma = F1/A  ±  M2 * z / I1  ±  M3 * y / I2
```

Where y and z are the recovery point coordinates from the PBAR card. Torsional shear stress is not computed in phase 1.

---

## .f06 Output (SOL 101)

Output sections written to `results.f06`:

1. **NASTRAN Executive and Case Control echo** (abbreviated)
2. **Applied Load Vector (OLOAD)** — echo of assembled load vector
3. **Nodal Displacements** — GID, T1, T2, T3, R1, R2, R3 per subcase
4. **SPC Reaction Forces** — GID, DOF, value per constrained DOF
5. **CBAR Forces** — EID, end A forces/moments, end B forces/moments
6. **CBAR Stresses** — EID, point C/D/E/F axial + bending stress

---

## Verification Cases

### Case 1 — Cantilever, Tip Point Load

- Configuration: fixed end at x=0, free end at x=L, point load P in Y at free end.
- Expected tip deflection: `δ = PL³ / 3EI`
- Expected tip rotation: `θ = PL² / 2EI`
- Tolerance: < 0.1% relative error.

### Case 2 — Simply Supported Beam, Mid-Span Load

- Configuration: pin at x=0 (Ty, Tz constrained), roller at x=L (Ty, Tz constrained), point load P in Y at x=L/2.
- Expected mid-span deflection: `δ = PL³ / 48EI`
- Tolerance: < 0.1% relative error.

### Case 3 — Fixed-Fixed Beam, Uniform Load (modelled as nodal loads)

- Verifies reaction forces sum to total applied load.

### Case 4 — Cantilever, Tip Torque (V11)

- Configuration: fixed end at x=0, free end at x=L, tip torque T about global x-axis (MOMENT N1=1).
- Expected tip torsional rotation: `θ_x = T·L / (G·J)`
- BDF: `tests/integration/bdf/v11_cantilever_torsion_sol101.bdf`
- Parameters: G=1.0, J=2.0, L=1.0, T=4.0 → expected θ_x = 2.0 rad
- Tolerance: < 0.1% relative error.

---

## Solver Module: `solver/sol101.py`

Key functions:

```python
def run_sol101(bulk: BulkData, case: SubcaseControl) -> Sol101Result:
    ...

def assemble_stiffness(bulk: BulkData) -> np.ndarray:
    ...

def assemble_load_vector(bulk: BulkData, load_sid: int) -> np.ndarray:
    ...

def apply_spcs(K: np.ndarray, f: np.ndarray, spc_dofs: list[int]) -> tuple[np.ndarray, np.ndarray, list[int]]:
    ...

def recover_bar_forces(bulk: BulkData, u: np.ndarray) -> dict[int, BarForces]:
    ...
```
