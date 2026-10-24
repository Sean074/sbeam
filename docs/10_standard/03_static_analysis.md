# SOL 101 — Static Analysis

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
4. Solve: `K_free @ u_free = f_free`. The sparse path uses `spsolve`; the dense path
   (RBE3 transformation collapses K to dense) factors `K_free` **once** (DEF-R6,
   2026-08-02): the singularity check is an LU + LAPACK `gecon` 1-norm condition
   estimate (`sbeam/linalg_utils.py: estimate_cond_1norm`, threshold 1e15 as before —
   replacing a full-SVD `np.linalg.cond`) and the same LU serves the solve via
   `lu_solve`.
5. Reconstruct full `u_global` by inserting zeros at constrained DOF positions, then applying `u_full = T @ u_red`.

Since DEF-R5 all of steps 1–3 and 5 go through the **shared** reduction,
`assembly/reduction.py:reduce_to_aset` — the same object SOL 103, SOL 144 and the
maneuver solvers use (`red.reduce_matrix` / `reduce_vector` / `expand_to_g`). SOL 101
previously hand-rolled it, which meant a second copy of every fix. `run_sol101` keeps the
*unreduced* sparse `K`, the unreduced load vector and the raw SPC DOF list, because
`recover_reactions` works in g-set space.

**An SPC on an RBE2/RBAR/RBE3-dependent DOF raises** (DEF-M9) — that DOF has already been
eliminated, so there is no equation left to constrain. It used to be dropped silently, and
the model solved with the DOF free to follow its master and no reaction reported.

---

## Pin Releases (PA, PB)

Pin releases on a CBAR element free specified DOFs at end A (PA) or end B (PB). A released
DOF carries **no force**: it is removed from the element by **static condensation** (the
Schur complement, i.e. Guyan reduction at element level, exact for statics), not by zeroing.
Zeroing discards the coupling of the released DOF into the retained ones and leaves the
element over-stiff (DEF-M17: a fixed–pinned element came out 4× too stiff). Design note:
`docs/30_future/designs/cbar_pin_release_condensation.md`.

**Implementation** (`released_local_stiffness(pbar, mat1, L, pa, pb)` → `(K', T)` and
`condense_released_dofs(K, released)` in `assembly/stiffness.py`):
- Released local indices: digit `d` in PA → `d-1`, in PB → `d+5` (`release_indices`).
- One released DOF *i* at a time, in element local axes before the coordinate
  transformation (the NASTRAN-95 `kbar.f` form, order-independent):
  `K ← K − K[:,i]·K[i,:] / K[i,i]`, then zero row and column *i*. If
  `|K[i,i]| ≤ 1e-12·max|diag K|` (e.g. I1 = 0 or J = 0) the row/column is only zeroed.
- `T` is the transformation with `u_released = −K[i,r]·u_r / K[i,i]`, so `K' = TᵀKT`.
  The consistent mass is condensed congruently with the same `T` (`M' = TᵀMT`,
  `assembly/mass_matrix.py`; see `04_modal_analysis.md`), and any future fixed-end load
  vector must be condensed as `f' = Tᵀf`.
- The **same `K'`** is used for assembly and for every force-recovery path
  (`_element_local_forces` in `solver/sol101.py`, serving SOL 101, SOL 144 and MLOADS).
  Released rows of `K'` are zero, so the recovered force at a released DOF is **exactly
  zero** by construction. A test asserts that nothing else in `sbeam/` builds the
  unreleased CBAR matrices.

**DOF code mapping (1-based):**

| Code | Local DOF | Meaning |
|------|-----------|---------|
| 1 | 0 (A), 6 (B) | Axial force (Tx) |
| 2 | 1, 7 | Shear (Ty) |
| 3 | 2, 8 | Shear (Tz) |
| 4 | 3, 9 | Torsion (Rx) |
| 5 | 4, 10 | Bending moment (Ry) |
| 6 | 5, 11 | Bending moment (Rz) |

**Typical use:** `PA=PB="56"` releases both bending rotations at both ends, making the
element a **two-force member**: it transmits axial force (and torsion) only — once both end
moments are released, no transverse shear can survive. Releasing a single bending rotation
at one end (`PB=6`) gives a fixed–pinned member.

**Validation:** releasing the same translation or torsion digit (1–4) at **both** ends
leaves an internal mechanism (the element cannot carry that load and its rigid mass in that
direction is undefined), so the parser refuses it with a `ValueError` naming the element and
digit. `PA=PB="456"` is therefore an error; use `"56"`. Rotations 5/6 at both ends are
allowed.

**Note:** a released grid DOF that no other element or SPC stiffens is a singular row of
the global K. Constrain rotational DOFs at free joints of `PA=PB="56"` truss members.

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

**Output frame.** Reactions are recovered — and stored in `Sol101Result.reactions` — in
basic CID 0, which is the frame the SPC itself acts in (SPC DOF digits are always basic;
see the Known Limitations index in `00_program_overview.md`). They are rotated into the
grid's `CD` frame at f06 **write** time only, exactly like the displacement block, because
NASTRAN's "global" output system is the assembly of the per-grid `CD` frames rather than
basic CID 0. Downstream consumers of the stored vectors — `results/section_cuts.py` and
the MONPNT3 integrators — depend on them staying in basic.

### CBAR End Forces and Moments

For each element:
1. Extract nodal displacements at GA and GB from `u_global`.
2. Transform to local element coordinates: `u_local = [T] @ u_element`.
3. Compute local end forces: `f_local = [k_e] @ u_local` (the forces the nodes exert on the
   element).
4. Convert to **+x-face internal resultants** with `bar_internal_resultants` (below).
5. Report in the **NASTRAN/MSC layout** (`BarForce`, DEF-M18 #21): plane-1 and plane-2 bending
   moments at ends A and B, plane-1 and plane-2 shears, axial force, torque.

Plane 1 is the element x–y plane (bending about local z, PBAR `I1`); plane 2 is the x–z plane
(bending about local y, PBAR `I2`). The plane moments carry the NASTRAN sign:

```
M1 = +Mz⁺      M2 = −My⁺      V1 = Vy⁺      V2 = Vz⁺      AXIAL = P (tension +)      TORQUE = T
```

(⁺ = +x-face internal resultant). Both plane moments are therefore **positive when they put
the +y / +z fibres in compression**. Closed-form anchor: a cantilever with tip loads +Py, +Pz
gives `M1(x) = Py·(L−x)` and `M2(x) = Pz·(L−x)`, both positive and decaying to zero at the tip;
at a shared node `M1B(e) = M1A(e+1)`. The mapping is NASTRAN-95 `mis/sbar2.f`
(`M1A = −FA(6)`, `M2A = +FA(5)`, `V1 = −FA(2)`, `FX = −FA(1)`, `M1B = M1A − V1·L`,
`M2B = M2A − V2·L`), which MSC prints in the same layout. Gates G1–G3 and G5 are in
`tests/solver/test_cbar_force_layout.py`.

### CBAR Stress at Recovery Points

The nodal 12-vector `f_local = [k_e] @ u_local` is first converted to **internal resultants on
the positive (+x) face** of the section by `bar_internal_resultants` (`solver/sol101.py`), the
single place where the nodal-to-internal sign conversion happens (DEF-M21, #37), and from there
to the plane moments above:

```
end A (x = 0):  P = -f[0]   Vy = -f[1]   Vz = -f[2]   T = -f[3]   My_A = -f[4]   Mz_A = -f[5]
end B (x = L):  P = +f[6]   Vy = +f[7]   Vz = +f[8]   T = +f[9]   My_B = +f[10]  Mz_B = +f[11]
```

This is the section-cut / CBAR end-B sign of `09_conventions.md` §9 applied to both ends: at
end B the nodal value already is the +x-face resultant; at end A it is the negated one. The
stress output is the **NASTRAN/MSC layout** (`BarStress`, DEF-M18 #21). For each recovery point
C, D, E, F on the PBAR, with (y, z) the point coordinates in the element frame, the
**bending-only** stress is evaluated at both ends from the same plane moments the force table
prints:

```
SAi = -M1A * y_i / I1  -  M2A * z_i / I2        SBi = -M1B * y_i / I1  -  M2B * z_i / I2
AXIAL = P / A
SA-MAX / SA-MIN = AXIAL + max / min (SA1..SA4)   (likewise SB-MAX / SB-MIN)
```

Tension is positive; I12 = 0. With `M1 = Mz⁺`, `M2 = −My⁺` this is `σ_b = −Mz·y/I1 + My·z/I2` on
the +x-face resultants, so a +y tip load on a cantilever puts the +y fibres in compression at
every station, and the same fibre at a shared node reads the same total stress from end B of one
element and end A of the next (gate G3). This is NASTRAN-95 `sbar2.f` term by term
(`K1 = −M1/I1`, `K2 = −M2/I2`, `SIG = K1·C1 + K2·C2`, `SIGAMX = SIGAX + AMAX1(SIG1A..SIG4A)`).
All four points are always evaluated; a point left at (0, 0) contributes 0.0 bending and
therefore bounds MAX/MIN, exactly as in NASTRAN. `M.S.-T`/`M.S.-C` are not computed (MAT1
`ST`/`SC` are not parsed). Torsional shear stress is not computed.

**Reading the table:** `SA1–4`/`SB1–4` are bending only — add `AXIAL` to get a fibre total, or
read `SA-MAX`/`SA-MIN` directly. Before #21 sbeam's `SA/SB` columns were total stresses; an
MSC-trained reader would have added the axial term twice.

---

## .f06 Output (SOL 101)

Output sections written to `results.f06`:

1. **NASTRAN Executive and Case Control echo** (abbreviated)
2. **Applied Load Vector (OLOAD)** — echo of assembled load vector
3. **Nodal Displacements** — GID, T1, T2, T3, R1, R2, R3 per subcase
4. **SPC Reaction Forces** — GID, DOF, value per constrained DOF
5. **CBAR Forces** — the NASTRAN/MSC `FORCES IN BAR ELEMENTS (CBAR)` block, one row per
   element (DEF-M18 #21; values per "CBAR End Forces and Moments" above):

   ```
          ELEMENT      BEND-MOMENT END-A         BEND-MOMENT END-B             - SHEAR -                 AXIAL
              ID.        PLANE 1      PLANE 2      PLANE 1      PLANE 2      PLANE 1      PLANE 2        FORCE       TORQUE
                1   1.000000E+04 2.000000E+04 9.000000E+03 1.800000E+04 1.000000E+03 2.000000E+03 5.000000E+03 0.000000E+00
   ```

6. **CBAR Stresses** — the NASTRAN/MSC `STRESSES IN BAR ELEMENTS (CBAR)` block, **two rows per
   element**: row 1 = EID, bending-only `SA1–SA4` at C, D, E, F, `AXIAL`, `SA-MAX`, `SA-MIN`;
   row 2 = `SB1–SB4`, (blank), `SB-MAX`, `SB-MIN`. All four points print; a point left at
   (0, 0) prints `0.000000E+00`. The `M.S.-T`/`M.S.-C` columns are reserved and blank.

   ```
          ELEMENT            SA1          SA2          SA3          SA4        AXIAL       SA-MAX       SA-MIN    M.S.-T
              ID.            SB1          SB2          SB3          SB4       STRESS       SB-MAX       SB-MIN    M.S.-C
                1  -5.692188E+06-1.897396E+06 5.692188E+06 1.897396E+06 5.000000E+04 5.742188E+06-5.642188E+06
                   -5.122969E+06-1.707656E+06 5.122969E+06 1.707656E+06              5.172969E+06-5.072969E+06
   ```

   Both blocks are shared verbatim by SOL 144 (trim) and the MLOADS critical-sample f06.

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

### Case 5 — Cantilever + Zero-Offset RBAR (V14)

- Configuration: cantilever with a zero-offset RBAR connecting GID2 (free tip) to GID3; GID3 carries the tip load.
- Expected GID2 tip deflection: `δ = PL³ / 3EI` (RBAR with d=0 must be transparent).
- Expected GID3 displacement = GID2 displacement exactly (rigid coupling, no lever arm).
- BDF: `tests/integration/bdf/v14_rbar_zero_offset.bdf`
- Tolerance: < 0.1% relative error; GID3 == GID2 to machine precision.

### Case 5b — RBAR Non-Zero Offset / Lever-Arm (V19)

- Configuration: same cantilever; GA (GID 2) is the free CBAR tip, GB (GID 3) is offset a = 0.5 m in X. Force P in +Y at GB transfers to GA as F_y + M_z = a·P.
- Expected GA tip deflection: `u_y(GA) = PL³/(3EI) + a·PL²/(2EI) = 3.5×10⁻⁶ m`
- Expected GB deflection (lever-arm): `u_y(GB) = u_y(GA) + a·θ_z(GA) = 6.5×10⁻⁶ m`
- Rigid-body consistency: `u_GB = R @ u_GA` to 1×10⁻¹⁴ (exercises the full R-matrix).
- BDF: `tests/integration/bdf/v19_rbar_offset.bdf`
- Tolerance: < 0.1% relative error on deflections.

### Case 6 — Gravity Load, Simply Supported Beam (V15)

- Configuration: simply supported CBAR beam under uniform body acceleration (GRAV −Y); mass derived from CBAR distributed density.
- Expected reaction sum: `ΣR = total_mass × g` (392.5 kg × 9.81 = 3850.425 N).
- BDF: `tests/integration/bdf/v15_grav_simply_supported.bdf`
- Tolerance: < 0.01% relative error; reactions symmetric to 0.01%.

### Case 7 — Gravity Load with CONM2 (V16)

- Configuration: same beam as V15 with an additional 50 kg CONM2 at mid-span.
- Expected reaction sum: 442.5 kg × 9.81 = 4340.925 N (CBAR mass + CONM2 contribution).
- BDF: `tests/integration/bdf/v16_grav_with_conm2.bdf`
- Tolerance: < 0.01% relative error.

### Case 8 — Gravity Combined with Nodal Force via LOAD (V17)

- Configuration: GRAV −Y combined with an upward nodal FORCE via a LOAD card (superposition).
- Expected reaction sum: 2849.225 N (net of gravity weight and upward force).
- BDF: `tests/integration/bdf/v17_grav_plus_force.bdf`
- Tolerance: < 0.01% relative error.

### Case 9 — RBE2 with Eccentric Offset / Lever-Arm (V18)

- Configuration: cantilever with a non-coincident RBE2; dependent node GM is offset 0.5 m in X from independent node GN.
- Expected `u_y(GM)` matches analytical lever-arm formula to 0.1%; `u_GM = R × u_GN` to 1e-14 (rigid-body consistency).
- BDF: `tests/integration/bdf/v18_rbe2_offset.bdf`
- Tolerance: < 0.1% relative error on deflection; rigid-body consistency to 1e-14.

### CBUSH — Unit-Level Stiffness Coverage

CBUSH stiffness and force recovery are verified at unit level in `tests/assembly/test_cbush.py` (axial, torsional, grounded-spring, 45° orientation, and mixed-DOF cases). An end-to-end BDF + SOL 101 integration test (`v20_cbush_grounded_spring.bdf`) asserting `F = K × u` is tracked as R20.

---

## Key Modules

Key functions across the solver and assembly layers:

```python
# solver/sol101.py
def run_sol101(bulk: BulkData, subcase: SubcaseControl) -> Sol101Result:
    ...

# assembly/stiffness.py
def assemble_global_stiffness(bulk: BulkData) -> scipy.sparse.csr_matrix:
    ...

def apply_spcs(K, f, spc_dofs: list[int]) -> tuple:
    ...

# assembly/load_vector.py
def assemble_load_vector(bulk: BulkData, load_sid: int) -> np.ndarray:
    ...

# solver/sol101.py — called per element in the recovery loop
def recover_bar_forces(cbar, grids, pbars, mat1s,
                       displacements, grid_index) -> BarForce:
    ...
```

`run_sol101` accepts `subcase.load_sid = None` as a valid zero-load subcase;
all displacements and reactions will be zero.
