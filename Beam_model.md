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
| CID | Coordinate system ID (must be 0 in phase 1) |
| M | Mass value |
| X1, X2, X3 | Offset vector from grid to centre of mass (optional; default 0) |
| I11, I21, I22, I31, I32, I33 | Inertia tensor at CM in CID frame (optional, second line; default 0) |

**Mass matrix contribution:** Full 6×6 symmetric block at the grid's DOFs:

- Translational 3×3: `m·I₃`
- Coupling 3×3 (non-zero when offset ≠ 0): `−m·skew(r)` / `m·skew(r)ᵀ`
- Rotational 3×3: `I_cm + m·(|r|²·I₃ − r·rᵀ)` (parallel axis theorem + CM inertia)

**Zero offset / zero inertia tensor:** When X1=X2=X3=0 and I11–I33 are omitted or zero, CONM2 contributes only the translational 3×3 block (`m·I₃`). Rotational DOFs at the mass node receive no mass contribution. Combined with `rho=0` on MAT1, this makes the global mass matrix singular — see `Modal_analysis.md` for how SOL 103 handles this via regularisation.

**CID constraint:** CID must be 0. Non-zero CID triggers a `UserWarning` and is treated as 0.

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
| CID | Coordinate system (0 in phase 1) |
| F | Scale factor |
| N1,N2,N3 | Direction cosines (force vector = F × [N1, N2, N3]) |

---

### MOMENT

Concentrated moment at a grid point.

```
MOMENT, SID, GID, CID, M, N1, N2, N3
```

Same field structure as FORCE; M is the scale factor and N1–N3 are the moment direction cosines.

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

**`Rbe2` dataclass:**

| Field | Type | Description |
|-------|------|-------------|
| `eid` | `int` | Element ID |
| `gn` | `int` | Independent grid ID |
| `cm` | `str` | Coupled DOF string |
| `gm` | `list[int]` | Dependent grid IDs |

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
    plotels: dict[int, Plotel]
    rbe3s: dict[int, Rbe3]
    pbars: dict[int, Pbar]
    mat1s: dict[int, Mat1]
    conm2s: dict[int, Conm2]
    spcs: dict[int, list[Spc]]
    spc1s: dict[int, list[Spc1]]
    forces: dict[int, list[Force]]
    moments: dict[int, list[Moment]]
    loads: dict[int, Load]
    eigrls: dict[int, Eigrl]
```

All dictionaries are keyed by the card's primary ID (GID, EID, SID, etc.).

---

## Model Limits

| Quantity | Limit | Reason |
|----------|-------|--------|
| CBAR elements | 200 | Direct matrix inversion (no sparse solver) |
| Coordinate systems | CID 0 only (phase 1) | Simplify coordinate transforms |
| Tapered sections | Not supported (phase 1) | PBAR is uniform only |

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

Cards recognised: `GRID`, `PBAR`, `MAT1`, `CBAR`, `PLOTEL`, `CONM2`, `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `EIGRL`.
Structural markers `BEGIN BULK` / `ENDDATA` are silently skipped.
All other keywords issue `warnings.warn(…, UserWarning)` and are skipped.
Duplicate GID raises `ValueError`.

**Ordering constraint:** PBAR and MAT1 must appear before the CBAR elements that reference them.

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
