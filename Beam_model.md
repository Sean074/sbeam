# Beam_model.md — Geometry and Model Definition

## Overview

The `sbeam` data model represents a NASTRAN-format beam structure. All data originates from BDF card input. The model is assembled into Python dataclass objects by the parser and held in a central `BulkData` object used by the assembler and solver.

---

## BDF Card Definitions (Phase 1)

### GRID

Defines a grid point (node) in the global Cartesian coordinate system.

```
GRID, GID, CP, X1, X2, X3, CD, PS, SEID
```

| Field | Description |
|-------|-------------|
| GID | Grid ID (integer, unique) |
| CP | Input coordinate system (must be 0 in phase 1) |
| X1, X2, X3 | X, Y, Z coordinates |
| CD | Output coordinate system (must be 0 in phase 1) |
| PS | Permanent SPC DOFs (optional) |
| SEID | Superelement ID (not used; must be blank) |

**Phase 1 constraint:** CP and CD must be 0 or blank.

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

Concentrated mass element. Phase 1 supports scalar point mass only.

```
CONM2, EID, GID, CID, M
```

| Field | Description |
|-------|-------------|
| EID | Element ID |
| GID | Grid point ID where mass is applied |
| CID | Coordinate system ID (must be 0 in phase 1) |
| M | Mass value |

**Phase 2:** offset vector (X1, X2, X3) and inertia tensor (I11, I21, I22, I31, I32, I33).

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

In phase 1, RBE3 is used only for interpolation of PLOTEL grid displacements for visualisation. It is **not** assembled into the structural stiffness matrix in phase 1.

Full structural RBE3 support (as a constraint equation / Lagrange multiplier) is planned for phase 2.

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
