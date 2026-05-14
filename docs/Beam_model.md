# Beam_model.md — Geometry and Model Definition

## Overview

The `sbeam` data model represents a NASTRAN-format beam structure. All data originates from BDF card input. The model is assembled into Python dataclass objects by the parser and held in a central `BulkData` object used by the assembler and solver.

---

## BDF Card Definitions

### CORD2R

Defines a rectangular (Cartesian) coordinate system by three points.

```
CORD2R, CID, RID, A1, A2, A3, B1, B2, B3
+,      C1, C2, C3
```

| Field | Description |
|-------|-------------|
| CID | Coordinate system ID (integer > 0, unique) |
| RID | Reference coordinate system ID (0 = global; or another CORD2R CID) |
| A1–A3 | Origin of the new system, expressed in RID frame |
| B1–B3 | Point on the local Z-axis, expressed in RID frame |
| C1–C3 | Point in the local XZ-plane, expressed in RID frame |

The three orthonormal axes are derived as:
- **Local Z** = normalise(B − A)
- **Local X** = normalise((C − A) − ((C−A)·Ẑ)Ẑ) (Gram-Schmidt)
- **Local Y** = Ẑ × X̂ (right-handed)

The continuation line carrying C1–C3 is required. A, B, C must be non-collinear; CID must be unique and > 0.

Chained systems (`RID > 0`) are supported; cycles raise a `ValueError`.

Only rectangular systems (CORD2R) are supported. CORD2C, CORD2S, CORD1R are not implemented.

---

### GRID

Defines a grid point (node).

```
GRID, GID, CP, X1, X2, X3, CD, PS, SEID
```

| Field | Description |
|-------|-------------|
| GID | Grid ID (integer, unique) |
| CP | Input coordinate system: coordinates X1/X2/X3 are given in this system (0 = global) |
| X1, X2, X3 | Coordinates in the CP system |
| CD | Output coordinate system: nodal results (displacements, reactions) are reported in this system |
| PS | Permanent SPC DOFs (optional) |
| SEID | Superelement ID (not used; must be blank) |

After parsing, `resolve_grid_positions()` transforms all grid positions from their CP system into global CID 0 in-place. The `cd` field is preserved for output transformation.

---

### CBAR

Uniform cross-section beam element using Euler-Bernoulli theory.

```
CBAR, EID, PID, GA, GB, X1, X2, X3, OFFT
+,    PA, PB
```

| Field | Description |
|-------|-------------|
| EID | Element ID (integer, unique) |
| PID | Property ID → references PBAR |
| GA, GB | End node A and B grid IDs |
| X1, X2, X3 | Orientation vector components (or GRID ID if G0 form) |
| OFFT | Offset flag (default GGG — offsets measured at grid points) |
| PA, PB | Pin releases at end A and B (string of released DOFs 1–6, e.g. "456") |

Pin release DOFs: 1=Tx, 2=Ty, 3=Tz, 4=Rx, 5=Ry, 6=Rz (in element local axes).

**Phase 1 constraint:** Offsets (W1A, W2A, etc.) not supported. X1/X2/X3 orientation vector required.

---

### PBAR

Uniform beam cross-section properties. Referenced by CBAR.

```
PBAR, PID, MID, A, I1, I2, J, NSM
+,    C1, C2, D1, D2, E1, E2, F1, F2
```

| Field | Description |
|-------|-------------|
| PID | Property ID (integer, unique) |
| MID | Material ID → references MAT1 |
| A | Cross-sectional area |
| I1 | Area moment of inertia about local 1-axis (bending in plane 1-3) |
| I2 | Area moment of inertia about local 2-axis (bending in plane 1-2) |
| J | Torsional constant |
| NSM | Non-structural mass per unit length (optional) |
| C1,C2 | Y,Z coordinates of stress recovery point C |
| D1,D2 | Y,Z coordinates of stress recovery point D |
| E1,E2 | Y,Z coordinates of stress recovery point E |
| F1,F2 | Y,Z coordinates of stress recovery point F |

---

### MAT1

Isotropic material properties. Referenced by PBAR.

```
MAT1, MID, E, G, NU, RHO, A, TREF, GE
```

| Field | Description |
|-------|-------------|
| MID | Material ID (integer, unique) |
| E | Young's modulus |
| G | Shear modulus (if blank, computed from E and NU) |
| NU | Poisson's ratio |
| RHO | Mass density |
| A | Thermal expansion coefficient (phase 2) |
| TREF | Reference temperature (phase 2) |
| GE | Structural damping coefficient (phase 2) |

**Phase 1:** E, G (or NU), and RHO are required. If both G and NU are provided, G takes precedence.

---

### CONM2

Concentrated mass element. Supports translational mass, offset vector, and inertia tensor.

```
CONM2, EID, GID, CID, M, X1, X2, X3
+,     I11, I21, I22, I31, I32, I33
```

| Field | Description |
|-------|-------------|
| EID | Element ID |
| GID | Grid point ID where mass is applied |
| CID | Coordinate system ID for offset vector and inertia tensor (references CORD2R; 0 = global) |
| M | Mass value |
| X1, X2, X3 | Offset vector from grid to centre of mass (optional; default 0) |
| I11, I21, I22, I31, I32, I33 | Inertia tensor at CM in CID frame (optional, second line; default 0) |

**Mass matrix contribution:** Full 6×6 symmetric block at the grid's DOFs:

- Translational 3×3: `m·I₃`
- Coupling 3×3 (non-zero when offset ≠ 0): `−m·skew(r)` / `m·skew(r)ᵀ`
- Rotational 3×3: `I_cm + m·(|r|²·I₃ − r·rᵀ)` (parallel axis theorem + CM inertia)

**Zero offset / zero inertia tensor:** When X1=X2=X3=0 and I11–I33 are omitted or zero, CONM2 contributes only the translational 3×3 block (`m·I₃`). Rotational DOFs at the mass node receive no mass contribution. Combined with `rho=0` on MAT1, this makes the global mass matrix singular — see `Modal_analysis.md` for how SOL 103 handles this via regularisation.

**CID support:** When CID references a CORD2R system, the offset vector `r` and inertia tensor are rotated from the CID frame into global CID 0 before assembly (`R @ r`, `R @ I @ Rᵀ`). CID=0 is a no-op.

**Card format:** Inertia fields may appear on a continuation line (fixed-field) or as fields 8–13 on the same line (free-field).

---

### SPC / SPC1

Single-point constraint. Fixes specified DOFs of specified grids to zero.

```
SPC,  SID, G1, C1, D1, G2, C2, D2
SPC1, SID, C,  G1, G2, G3, ...
```

| Field | Description |
|-------|-------------|
| SID | Set ID (referenced by `SPC` in case control) |
| G1, G2 | Grid IDs |
| C1, C2 | DOF string (e.g. "123456") |
| D1, D2 | Enforced displacement value (SPC only; must be 0.0 in phase 1) |

DOF key: 1=Tx, 2=Ty, 3=Tz, 4=Rx, 5=Ry, 6=Rz.

**Phase 1:** Enforced non-zero displacements are not supported (D must be 0 or blank).

---

### FORCE

Concentrated force at a grid point.

```
FORCE, SID, GID, CID, F, N1, N2, N3
```

| Field | Description |
|-------|-------------|
| SID | Load set ID |
| GID | Grid point ID |
| CID | Coordinate system for direction vector (references CORD2R; 0 = global) |
| F | Scale factor |
| N1,N2,N3 | Direction cosines (force vector = F × [N1, N2, N3]) |

---

### MOMENT

Concentrated moment at a grid point.

```
MOMENT, SID, GID, CID, M, N1, N2, N3
```

Same field structure as FORCE; M is the scale factor, N1–N3 are the moment direction cosines, and CID references a CORD2R system (0 = global).

---

### LOAD

Linear combination of load sets. Allows superposition of FORCE/MOMENT sets.

```
LOAD, SID, S, S1, L1, S2, L2, ...
```

| Field | Description |
|-------|-------------|
| SID | Combined load set ID (referenced by `LOAD` in case control) |
| S | Overall scale factor |
| S1, S2 | Scale factor for each component set |
| L1, L2 | Component load set IDs |

Applied load = S × (S1×L1 + S2×L2 + ...)

Component SIDs (`L1`, `L2`, …) may reference FORCE, MOMENT, or GRAV sets.

---

### GRAV

Body acceleration load. Applies a uniform inertial load to all mass-bearing DOFs using the assembled consistent mass matrix.

```
GRAV, SID, CID, G, N1, N2, N3
```

| Field | Description |
|-------|-------------|
| SID | Load set ID |
| CID | Coordinate system for the direction vector (Phase 1: CID=0 only) |
| G | Acceleration magnitude (units/s²) |
| N1, N2, N3 | Unit direction vector of the acceleration in CID frame |

**Method:** The gravity load vector is computed as:

```
f_grav = [M_global] × {a_field}
```

where `{a_field}` has `G × [N1, N2, N3]` at every translational DOF and zero at rotational DOFs. This uses the assembled consistent mass matrix, so both CBAR distributed mass and CONM2 point masses are naturally included.

**Reaction recovery:** Reaction forces are computed as `R = K[spc,:] @ u - f_applied[spc]`. The `f_applied[spc]` term corrects for gravity forces that act at constrained (SPC'd) DOFs and would otherwise cause reactions to undercount the total weight.

**LOAD combination:** GRAV SIDs can appear as components in a LOAD card, mixed freely with FORCE and MOMENT SIDs.

**Phase 1 constraint:** CID must be 0 (global). CID ≠ 0 raises a parse error.

---

### PLOTEL

Plot-only element connecting two grid points. Used for visualising intermediate beam geometry and deformed shape. Not included in structural stiffness or mass matrices.

```
PLOTEL, EID, G1, G2
```

---

### RBE3

Rigid Body Element (interpolation type). Defines a dependent (reference) grid whose DOFs are constrained to be a weighted average of independent grid DOFs.

```
RBE3, EID, (blank), REFGRID, REFC, WT1, C1, G1,1, G1,2, ..., +
+,   WT2, C2, G2,1, G2,2, ...
```

| Field | Description |
|-------|-------------|
| EID | Element ID |
| (blank) | Field 2 is always blank on RBE3 cards |
| REFGRID | Dependent (reference) grid ID |
| REFC | DOF string for the dependent grid (e.g. `"123456"`) |
| WT_i | Weight for independent grid group i |
| C_i | DOF string for independent grid group i |
| G_i,j | Independent grid IDs in group i (one or more per continuation line) |

**Constraint equation** — for each DOF `d` in `REFC`:

```
u_refgrid[d] = Σᵢ (wᵢ · u_i[d]) / Σᵢ wᵢ
```

where the sum is over independent grids in groups whose DOF string includes `d`.

**Phase 1 assembly:** implemented as a DOF transformation matrix **T** (shape `n_dof × n_red`) built in `assembly/rbe3.py`. T is applied to K and M before SPC partitioning: `K_red = Tᵀ K T`, `M_red = Tᵀ M T`. After solving, full displacements and mode shapes are recovered via `u_full = T @ u_red`. Phase 2 may add Lagrange multiplier support.

**`Rbe3` dataclass:**

| Field | Type | Description |
|-------|------|-------------|
| `eid` | `int` | Element ID |
| `refgrid` | `int` | Dependent (reference) grid ID |
| `refc` | `str` | DOF string for the dependent grid |
| `wt_gc` | `list` | List of `(weight: float, dofs: str, grids: list[int])` tuples |

---

### RBE2

Rigid Body Element (rigid type). Constrains a set of dependent grids to move identically to a single independent grid for a specified set of DOFs.

```
RBE2, EID, GN, CM, GM1, GM2, GM3, GM4, GM5, GM6
+,   GM7, GM8, ...
```

| Field | Description |
|-------|-------------|
| EID | Element ID |
| GN | Independent grid ID |
| CM | Coupled DOF string (e.g. `"123456"`) |
| GM1… | Dependent grid IDs (first line and continuation lines) |

**Constraint equation** — for each dependent grid GMi and each DOF `d` in `CM`:

```
u_GMi[d] = u_GN[d]
```

**Phase 1 scope:** no rigid arm eccentricity. All DOFs are coupled directly without offset vector computation.

**Phase 1 assembly:** implemented in `assembly/rbe3.py` within `build_rbe3_transformation`, using the same T-matrix approach as RBE3. For each dependent DOF, the corresponding row of `T_full` is set to `[0, …, 1, …, 0]` with the `1` at the column of the independent DOF. After applying all RBE2 and RBE3 constraints, the transformation matrix `T` (shape `n_dof × n_red`) is applied before SPC partitioning.

**Viewer:** rendered as solid red lines (`#cc2222`, width=2) from GN to each GM — distinguishable from RBE3 dashed lines.

**Attaching CONM2 via RBE2 (Lesson-16 pattern):** The standard approach is to place the CONM2 on the **independent (GN) node**. The RBE2 kinematically couples all dependent nodes to GN, so the concentrated mass inertia is carried into the reduced system when the congruence transformation `M_red = Tᵀ M T` is applied. This is the correct model for discrete equipment masses (motors, payloads, fuel) attached to the structure.

Example (`sample/beam_vib.bdf`):
```
RBE2,  20, 7, 123456, 6     $ GN=7 (independent), GM=[6] (dependent)
CONM2, 30, 7, 0, 100000.0   $ mass on node 7 = independent node ✓
```

Placing a CONM2 on an RBE2 **dependent (GM) node** is implicitly handled by the same congruence transformation and is mathematically valid, but this configuration is untested in sbeam — verify results against a closed-form or independent model if used.

**`Rbe2` dataclass:**

| Field | Type | Description |
|-------|------|-------------|
| `eid` | `int` | Element ID |
| `gn` | `int` | Independent grid ID |
| `cm` | `str` | Coupled DOF string |
| `gm` | `list[int]` | Dependent grid IDs |

---

### RBAR

Rigid Bar element. Connects two independent grids (GA, GB) with full rigid body kinematics — translations and rotations are coupled with the lever-arm effect of the offset vector between the two grids.

```
RBAR, EID, GA, GB, CNA, CNB, CMA, CMB
```

| Field | Description |
|-------|-------------|
| EID | Element ID (integer, unique) |
| GA | End A grid ID (independent by default) |
| GB | End B grid ID (dependent by default) |
| CNA | Independent DOF components at GA (default `"123456"`) |
| CNB | Independent DOF components at GB (default blank — none) |
| CMA | Dependent DOF components at GA (auto-computed; field may be blank) |
| CMB | Dependent DOF components at GB (auto-computed; field may be blank) |

**Phase 1 scope:** Only the default case is supported — `CNA="123456"` (all 6 DOFs at GA independent) and `CNB=""` (blank, all 6 DOFs at GB dependent). Non-default combinations raise `ValueError`. CMA and CMB are parsed but not stored; they are always the complement of CNA/CNB.

**Constraint equations** — all 6 DOFs at GB are determined by the rigid body kinematics matrix R:

```
[u_Bx]   [1  0  0   0   dz  -dy] [u_Ax]
[u_By] = [0  1  0  -dz   0   dx] [u_Ay]
[u_Bz]   [0  0  1   dy  -dx   0] [u_Az]
[θ_Bx]   [0  0  0   1    0   0] [θ_Ax]
[θ_By]   [0  0  0   0    1   0] [θ_Ay]
[θ_Bz]   [0  0  0   0    0   1] [θ_Az]
```

where **d** = (dx, dy, dz) = r_GB − r_GA in global coordinates (CID 0).

**Distinction from RBE2:** RBE2 copies each DOF directly (`u_dep[d] = u_indep[d]`). RBAR computes translations at GB from both translations and rotations at GA, capturing the lever-arm effect. When `d = (0,0,0)` (coincident grids), R reduces to the identity and RBAR is equivalent to a full-DOF RBE2.

**Assembly:** implemented in `assembly/rbe3.py` within `build_rbe3_transformation()`. For each RBAR, 6 rows of `T_full` (corresponding to GB's DOFs) are filled with the R matrix evaluated at the grid offset. The resulting T matrix is applied identically in SOL 101 and SOL 103.

**Viewer:** rendered as solid purple lines (`#9467bd`, width=3) from GA to GB.

**`Rbar` dataclass:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `eid` | `int` | — | Element ID |
| `ga` | `int` | — | End A grid (independent) |
| `gb` | `int` | — | End B grid (dependent) |
| `cna` | `str` | `"123456"` | Independent DOFs at GA |
| `cnb` | `str` | `""` | Independent DOFs at GB |

---

### PBUSH

Generalised spring-damper property. Referenced by CBUSH.

```
PBUSH, PID, K, K1, K2, K3, K4, K5, K6
```

| Field | Description |
|-------|-------------|
| PID | Property ID (integer, unique) |
| K | Literal keyword "K" (identifies the stiffness field group) |
| K1–K6 | Stiffness values for DOFs 1–6 (Tx, Ty, Tz, Rx, Ry, Rz); blank or 0 = no stiffness in that DOF |

**Phase 2 scope:** Viscous damping (B1–B6) is not supported; a card with the "B" keyword raises `ValueError`. K1–K6 provide diagonal stiffness; off-diagonal coupling is not supported.

---

### CBUSH

Two-node generalised spring-damper element. Adds diagonal stiffness in up to 6 DOFs.

```
CBUSH, EID, PID, GA, GB, (S), (CID)
+,     X1, X2, X3
```

| Field | Description |
|-------|-------------|
| EID | Element ID (integer, unique) |
| PID | Property ID → references PBUSH |
| GA | Node A grid ID |
| GB | Node B grid ID (blank = grounded element; stiffness applied to GA DOFs only) |
| S | Spring location ratio (not used; field is read and ignored) |
| CID | Orientation coordinate system (must be 0 or blank — user CID deferred to Phase 3) |
| X1, X2, X3 | Orientation vector (continuation line); defines the XZ-plane, same convention as CBAR. Required when nodes are coincident. |

**Element stiffness:** Diagonal 6×6 local matrix `diag(K1…K6)`. For a two-node element, assembled into a 12×12 matrix:
```
K_e = [ K_local  -K_local ]
      [-K_local   K_local ]
```
For a grounded element (GB blank), only the 6×6 block at GA is assembled. The local matrix is transformed to global via `Tᵀ K_e T` using the same rotation-matrix approach as CBAR.

**CBUSH is massless.** Use CONM2 to add mass at connection points.

**Viewer:** rendered as a zigzag (spring-coil) polyline between GA and GB, distinct from CBAR and PLOTEL traces.

---

### EIGRL

Real eigenvalue extraction parameters for SOL 103.

```
EIGRL, SID, V1, V2, ND, MSGLVL, MAXSET, SHFSCL, NORM
```

| Field | Description |
|-------|-------------|
| SID | Set ID (referenced by `METHOD` in case control) |
| V1, V2 | Lower and upper frequency bounds (Hz); blank = no limit |
| ND | Number of modes to extract |
| NORM | Normalisation: MASS (modal mass = 1) or MAX (max component = 1) |

---

## BulkData Object

The parser produces a `BulkData` dataclass containing:

```python
@dataclass
class BulkData:
    grids: dict[int, Grid]
    cbars: dict[int, Cbar]
    cbushs: dict[int, Cbush]
    plotels: dict[int, Plotel]
    rbe3s: dict[int, Rbe3]
    rbe2s: dict[int, Rbe2]
    pbars: dict[int, Pbar]
    pbushs: dict[int, Pbush]
    mat1s: dict[int, Mat1]
    conm2s: dict[int, Conm2]
    spcs: dict[int, list[Spc]]
    spc1s: dict[int, list[Spc1]]
    forces: dict[int, list[Force]]
    moments: dict[int, list[Moment]]
    loads: dict[int, Load]
    eigrls: dict[int, Eigrl]
    cord2rs: dict[int, Cord2r]
```

All dictionaries are keyed by the card's primary ID (GID, EID, PID, SID, CID, etc.).

---

## Model Limits

| Quantity | Limit | Reason |
|----------|-------|--------|
| CBAR elements | 200 | Direct matrix inversion (no sparse solver) |
| Coordinate systems | CORD2R only (rectangular) | CORD2C, CORD2S, CORD1R not implemented |
| Tapered sections | Not supported | PBAR is uniform cross-section only |
| CBAR offsets | Not supported | W1A/W2A/etc. offset fields are ignored |
| CBUSH CID | 0 only | User-defined CID deferred to Phase 3 |

---

## Parser

Two top-level entry points exist in `parser/bdf_reader.py`:

| Function | Use case | Requires case control |
|----------|----------|-----------------------|
| `parse_bdf(filepath)` | Full run file (SOL + SUBCASE + bulk data) | Yes — raises `ValueError` if no `SOL` found |
| `parse_bulk_file(filepath)` | Bulk-data-only file (geometry, loads, constraints) | No |

The viewer calls `parse_bulk_file()` when uploading a model file before case control has been defined. The solver always receives data from `parse_bdf()`.

### `parse_bulk_file(filepath) -> BulkData`

Reads a bulk-data-only file. Behaviour:

1. Reads all lines from the file.
2. If a `BEGIN BULK` line is present, discards everything before it.
3. Passes remaining lines to `parse_bulk_data`.
4. Returns `BulkData`. Does not call `parse_case_control`.

### `parse_bdf(filepath) -> (CaseControl, BulkData)` — run file entry point

`parse_bdf` reads a complete run file. It:

1. Reads the file and splits on the `BEGIN BULK` line.
2. Passes the case control section (before `BEGIN BULK`) to `parse_case_control`.
3. If the `CaseControl` has an `include` path, loads the referenced file as bulk data; otherwise uses the lines after `BEGIN BULK`.
4. Passes the bulk data lines to `parse_bulk_data`.
5. Returns `(CaseControl, BulkData)`.

Raises `FileNotFoundError` if the INCLUDE file does not exist.

### `parse_case_control(lines) -> CaseControl` — `parser/case_control.py`

Parses the case control section (lines above `BEGIN BULK`). Uses space/equals keyword syntax — not the comma/fixed-field bulk format. Recognises: `SOL`, `TITLE`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `DISPLACEMENT`, `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `INCLUDE`.

Raises `ValueError` if `SOL` is absent or not 101/103.

### `parse_bulk_data(lines) -> BulkData` — `parser/bdf_reader.py`

Accepts a list of BDF text lines (bulk data section only). Supports:

- **Free-field format** — comma-separated fields (e.g. `GRID, 1, , 0.0, 0.0, 0.0`)
- **Fixed-field format** — 8-character columns (standard NASTRAN small-field)
- **Inline `$` comments** — everything from `$` to end of line is ignored
- **Continuation lines** — lines whose first field starts with `+`; consumed by the preceding card handler (e.g. PBAR recovery points)

Cards recognised: `CORD2R`, `GRID`, `PBAR`, `PBUSH`, `MAT1`, `CBAR`, `CBUSH`, `PLOTEL`, `CONM2`, `RBE3`, `RBE2`, `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `EIGRL`.
Structural markers `BEGIN BULK` / `ENDDATA` are silently skipped.
All other keywords issue `warnings.warn(…, UserWarning)` and are skipped.
Duplicate GID raises `ValueError`.

**Ordering constraints:** PBAR and MAT1 must appear before the CBAR elements that reference them. PBUSH must appear before the CBUSH elements that reference it. CORD2R cards may appear in any order relative to each other; cycles in `RID` references raise `ValueError`.

**CBAR cross-reference validation** (at parse time):
- `GA` or `GB` not in `bulk.grids` → `ValueError`
- `PID` not in `bulk.pbars` → `ValueError`
- More than 200 CBAR elements → `ValueError`

**DOF string validation** (SPC and SPC1 cards):
- Any character outside `1–6` (including `"0"`) → `ValueError`

**LOAD component validation** (post-parse, after all cards are read):
- Component SID not found in `bulk.forces` or `bulk.moments` → `ValueError`

---

## Verification

A valid model must satisfy:
- Every CBAR references an existing PBAR (by PID) and two existing GRIDs.
- Every PBAR references an existing MAT1 (by MID).
- No duplicate GIDs, EIDs, PIDs, MIDs.
- No zero-length CBAR elements.
- At least one SPC set defined (SOL 101).
- Total CBAR count ≤ 200.
