# sbeam — BDF Card Reference

All BDF cards supported in Phase 1 and Phase 2. For each card: field layout, variable names and types, defaults, and a minimal example.

---

## File Structure

A sbeam run file (`.bdf`) has three sections:

```
$ comments begin with $
SOL 101               ← case control section (no header line)
SUBCASE 1
  ...
BEGIN BULK            ← marks start of bulk data section
  ...
ENDDATA               ← marks end of file
```

A bulk-only file (`.dat`) contains only the bulk data cards (no case control, no `BEGIN BULK` / `ENDDATA`).

---

## Format Rules

| Feature | Syntax |
|---------|--------|
| Free-field | Comma-separated fields: `GRID, 1, , 0.0, 0.0, 0.0` |
| Fixed-field | Standard NASTRAN 8-column fields (no commas) |
| Continuation | Next line starts with `+` (or blank first field in fixed format) |
| Comment | `$` anywhere on a line — rest of line is ignored |
| Blank field | Leave empty between commas or use double comma: `GRID, 1, , 0.0` |

Both free-field and fixed-field formats are supported. Continuation lines must immediately follow their parent card.

---

## Case Control Keywords

Case control appears between the `SOL` line and `BEGIN BULK`. Keywords are not order-sensitive except that `SUBCASE` groups the lines that follow it.

| Keyword | Type | Description |
|---------|------|-------------|
| `SOL` | int | Solution type. `101` = static, `103` = normal modes |
| `TITLE` | str | Analysis title — echoed to `.f06` output |
| `SUBCASE` | int | Opens a subcase block; all lines until the next `SUBCASE` belong to it |
| `LOAD` | int | Load set ID (references `FORCE`/`MOMENT`/`LOAD` bulk cards) |
| `SPC` | int | Constraint set ID (references `SPC`/`SPC1` bulk cards) |
| `METHOD` | int | Eigenvalue method SID (references `EIGRL` bulk card; SOL 103 only) |
| `DISPLACEMENT` | — | Request nodal displacement output (`= ALL` or `= PRINT`) |
| `SPCFORCE` | — | Request SPC reaction force output |
| `OLOAD` | — | Request applied load echo output |
| `FORCE` | — | Request CBAR/CBUSH element force output |
| `STRESS` | — | Request CBAR stress output at recovery points |
| `INCLUDE` | str | Path to bulk data file to include: `INCLUDE 'model.dat'` |

**Example case control section:**

```
SOL 101
$
SUBCASE 1
  TITLE = Cantilever tip load
  SPC   = 1
  LOAD  = 10
  DISPLACEMENT = ALL
  SPCFORCE     = ALL
  FORCE        = ALL
  STRESS       = ALL
$
BEGIN BULK
```

---

## Bulk Data Cards

### CORD2R — Rectangular Coordinate System

Defines a right-handed Cartesian coordinate system by three points in a reference system.

**Format:**
```
CORD2R, CID, RID, A1, A2, A3, B1, B2, B3
+,      C1,  C2,  C3
```

The continuation line is **required**.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| CID | `cid` | int | Coordinate system ID (> 0, unique) | required |
| RID | `rid` | int | Reference CID (`0` = global) | `0` |
| A1–A3 | `a` | float×3 | Origin of new system in RID frame | required |
| B1–B3 | `b` | float×3 | Point on local +Z axis in RID frame | required |
| C1–C3 | `c` | float×3 | Point in local XZ-plane in RID frame | required |

Local axes are derived: `z = B − A`, `x_temp = C − A`, `y = z × x_temp`, `x = y × z`.

**Example:**
```
$ CID=1, reference=global, Z-axis along global Z, X-axis along global Y
CORD2R, 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
+,      1.0, 0.0, 0.0
```

---

### GRID — Grid Point (Node)

Defines a node in the model.

**Format:**
```
GRID, GID, CP, X1, X2, X3, CD, PS, SEID
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| GID | `gid` | int | Grid ID (unique) | required |
| CP | `cp` | int | Input coordinate system for X1–X3 (`0` = global) | `0` |
| X1 | `x` | float | X coordinate in CP frame | required |
| X2 | `y` | float | Y coordinate in CP frame | required |
| X3 | `z` | float | Z coordinate in CP frame | required |
| CD | `cd` | int | Output coordinate system for displacement results (`0` = global) | `0` |
| PS | `ps` | str | Permanent SPC DOF string (e.g., `"123456"`) | `""` |
| SEID | — | — | Superelement ID — must be blank | — |

Coordinates are transformed to global CID 0 during parsing; CP and CD are stored for output.

**Example:**
```
$ GID=1 at origin, global input and output frame
GRID, 1, , 0.0, 0.0, 0.0
$ GID=6 at x=10, CD=1 (results in user coordinate system 1)
GRID, 6, , 10.0, 0.0, 0.0, 1
```

---

### MAT1 — Isotropic Material

Defines a linear elastic isotropic material.

**Format:**
```
MAT1, MID, E, G, NU, RHO
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| MID | `mid` | int | Material ID (unique) | required |
| E | `E` | float | Young's modulus | required |
| G | `G` | float | Shear modulus | `0.0` |
| NU | `nu` | float | Poisson's ratio | `0.0` |
| RHO | `rho` | float | Mass density | `0.0` |

If both G and NU are non-zero, G takes precedence. RHO is required for SOL 103 unless CONM2 supplies all mass.

**Example:**
```
$ Steel: E=200 GPa, G=76.9 GPa, nu=0.3, rho=7850 kg/m³
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
```

---

### PBAR — Beam Cross-Section Property

Defines uniform cross-section properties for CBAR elements.

**Format:**
```
PBAR, PID, MID, A, I1, I2, J, NSM
+,    C1, C2, D1, D2, E1, E2, F1, F2
```

The continuation line is optional (stress recovery points default to 0).

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| PID | `pid` | int | Property ID (unique) | required |
| MID | `mid` | int | Material ID (references MAT1) | required |
| A | `A` | float | Cross-sectional area | required |
| I1 | `I1` | float | Moment of inertia about element y-axis (bending in XZ plane) | required |
| I2 | `I2` | float | Moment of inertia about element z-axis (bending in XY plane) | required |
| J | `J` | float | Torsional constant | required |
| NSM | `nsm` | float | Non-structural mass per unit length | `0.0` |
| C1, C2 | `c1`, `c2` | float | y, z of stress recovery point C | `0.0` |
| D1, D2 | `d1`, `d2` | float | y, z of stress recovery point D | `0.0` |
| E1, E2 | `e1`, `e2` | float | y, z of stress recovery point E | `0.0` |
| F1, F2 | `f1`, `f2` | float | y, z of stress recovery point F | `0.0` |

**Example:**
```
$ Solid square cross-section: side=0.316 m → A=0.1, I=8.333e-4, J=1.406e-3
PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
$ Stress recovery at corners (y=±0.158, z=±0.158)
+,    0.15811, 0.15811, -0.15811, 0.15811, -0.15811, -0.15811, 0.15811, -0.15811
```

---

### PBUSH — Spring-Damper Property

Defines stiffness (and optionally damping) for CBUSH elements.

**Format:**
```
PBUSH, PID, K, K1, K2, K3, K4, K5, K6
```

The literal keyword `K` identifies the stiffness group.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| PID | `pid` | int | Property ID (unique) | required |
| `K` | — | str | Literal keyword `K` (stiffness group identifier) | required |
| K1 | `k1` | float | Stiffness for DOF 1 (Tx) | `0.0` |
| K2 | `k2` | float | Stiffness for DOF 2 (Ty) | `0.0` |
| K3 | `k3` | float | Stiffness for DOF 3 (Tz) | `0.0` |
| K4 | `k4` | float | Stiffness for DOF 4 (Rx — torsion) | `0.0` |
| K5 | `k5` | float | Stiffness for DOF 5 (Ry) | `0.0` |
| K6 | `k6` | float | Stiffness for DOF 6 (Rz) | `0.0` |

Only the `K` keyword is supported in Phase 1–2. The `B` (damping) keyword raises `ValueError`.

**Example:**
```
$ Grounded translational spring, 5000 N/m in X only
PBUSH, 10, K, 5000.0
$ Full 6-DOF spring
PBUSH, 20, K, 1.0e6, 1.0e6, 1.0e6, 1.0e3, 1.0e3, 1.0e3
```

---

### CBAR — Beam Element (Euler-Bernoulli)

Defines a two-node beam element with uniform cross-section.

**Format:**
```
CBAR, EID, PID, GA, GB, X1, X2, X3, OFFT
+,    PA, PB
```

The continuation line is optional.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| PID | `pid` | int | Property ID (references PBAR) | required |
| GA | `ga` | int | End A grid ID | required |
| GB | `gb` | int | End B grid ID | required |
| X1 | `x1` | float | Orientation vector component 1 | required |
| X2 | `x2` | float | Orientation vector component 2 | required |
| X3 | `x3` | float | Orientation vector component 3 | required |
| OFFT | `offt` | str | Offset flag | `"GGG"` |
| PA | `pa` | str | Pin releases at end A (DOF digits 1–6) | `""` |
| PB | `pb` | str | Pin releases at end B (DOF digits 1–6) | `""` |

The orientation vector `[X1, X2, X3]` defines the element y-axis and must not be parallel to the element axis (GA→GB).

**Example:**
```
$ Beam along X-axis, orientation vector in +Y (element y = global Y)
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
$ Pin release: Ry and Rz released at both ends (moment-free = truss)
CBAR, 5, 1, 5, 6, 0.0, 1.0, 0.0
+,    56, 56
```

---

### CBUSH — Spring-Damper Element

Defines a two-node (or grounded one-node) spring-damper element.

**Format:**
```
CBUSH, EID, PID, GA, GB, S, CID
+,     X1, X2, X3
```

Both the inline fields after CID and the continuation line are optional.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| PID | `pid` | int | Property ID (references PBUSH) | required |
| GA | `ga` | int | Node A grid ID | required |
| GB | `gb` | int or None | Node B grid ID; blank/omitted = grounded at GA | `None` |
| S | — | — | Spring location ratio — read and ignored | — |
| CID | — | int | Orientation CID — must be `0` or blank | `0` |
| X1–X3 | `x1`–`x3` | float | Orientation vector (continuation) | `0.0` |

For a grounded element (GB blank), stiffness acts only on GA DOFs. For a two-node element, symmetric stiffness couples GA and GB.

**Example:**
```
$ Two-node spring between grids 1 and 2
CBUSH, 1, 10, 1, 2
$ Grounded spring at grid 3 (no GB)
CBUSH, 2, 10, 3
```

---

### PLOTEL — Plot-Only Element

Defines a line segment for visualisation only. Not included in structural matrices.

**Format:**
```
PLOTEL, EID, G1, G2
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| G1 | `g1` | int | Grid point 1 | required |
| G2 | `g2` | int | Grid point 2 | required |

**Example:**
```
$ Visualisation line from node 5 to node 7 (e.g. sensor arm)
PLOTEL, 10, 5, 7
```

---

### RBE2 — Rigid Body Element (Rigid Constraint)

Rigidly couples selected DOFs of dependent grids to an independent grid.

**Format:**
```
RBE2, EID, GN, CM, GM1, GM2, GM3, GM4, GM5, GM6
+,    GM7, GM8, ...
```

Additional dependent grids may span continuation lines.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| GN | `gn` | int | Independent grid ID | required |
| CM | `cm` | str | DOF string coupling GN to all GMs (e.g., `"123456"`) | required |
| GM1–GMn | `gm` | list[int] | Dependent grid IDs | required |

Constraint enforced: `u_GMi[d] = u_GN[d]` for each DOF `d` in CM.

**Example:**
```
$ GID 3 rigidly follows GID 2 in all 6 DOFs
RBE2, 1, 2, 123456, 3
$ Multiple dependents: GIDs 3, 4, 5 all follow GID 1
RBE2, 2, 1, 123456, 3, 4, 5
```

---

### RBE3 — Rigid Body Element (Interpolation Constraint)

Constrains a dependent (reference) grid to the weighted average motion of independent grids.

**Format:**
```
RBE3, EID, (blank), REFGRID, REFC, WT1, C1, G1_1, G1_2, ...
+,    WT2, C2, G2_1, G2_2, ...
```

Each weight group `(WTi, Ci, Gi_1, Gi_2, ...)` may span continuation lines.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| (blank) | — | — | Field 2 must be blank | — |
| REFGRID | `refgrid` | int | Dependent reference grid ID | required |
| REFC | `refc` | str | DOF string for the dependent grid | required |
| WTi | (in `wt_gc`) | float | Weight for independent grid group i | required |
| Ci | (in `wt_gc`) | str | DOF string for group i | required |
| Gi_j | (in `wt_gc`) | list[int] | Independent grid IDs for group i | required |

`wt_gc` is a list of `(weight: float, dofs: str, grids: list[int])` tuples.

Constraint: `u_REFGRID[d] = Σᵢ(wᵢ × u_i[d]) / Σᵢ wᵢ` for each DOF `d` in REFC.

**Example:**
```
$ REFGRID=7 follows the average motion of GID 6, equal weight, all 6 DOFs
RBE3, 20, , 7, 123456, 1.0, 123456, 6
$ Two groups with different weights
RBE3, 30, , 10, 123, 2.0, 123, 1, 2, 1.0, 123, 3
```

---

### CONM2 — Concentrated Mass Element

Adds a point mass (with optional CG offset and inertia tensor) at a grid point.

**Format:**
```
CONM2, EID, GID, CID, M, X1, X2, X3
+,     I11, I21, I22, I31, I32, I33
```

The continuation line is optional (all inertia terms default to 0).

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| EID | `eid` | int | Element ID (unique) | required |
| GID | `gid` | int | Grid point where mass is attached | required |
| CID | `cid` | int | Coordinate system for offset vector and inertia tensor | `0` |
| M | `m` | float | Mass value | `0.0` |
| X1 | `x1` | float | Offset from grid to CG, component 1 in CID | `0.0` |
| X2 | `x2` | float | Offset from grid to CG, component 2 in CID | `0.0` |
| X3 | `x3` | float | Offset from grid to CG, component 3 in CID | `0.0` |
| I11 | `i11` | float | Moment of inertia about CID axis 1 at CG | `0.0` |
| I21 | `i21` | float | Product of inertia, axes 2–1 | `0.0` |
| I22 | `i22` | float | Moment of inertia about CID axis 2 at CG | `0.0` |
| I31 | `i31` | float | Product of inertia, axes 3–1 | `0.0` |
| I32 | `i32` | float | Product of inertia, axes 3–2 | `0.0` |
| I33 | `i33` | float | Moment of inertia about CID axis 3 at CG | `0.0` |

**Examples:**
```
$ 100 kg point mass at GID 7, no offset, no inertia
CONM2, 30, 7, 0, 100.0
$ 0.001 kg mass with torsional inertia I11=2.0 kg·m² (inline continuation)
CONM2, 1, 2, 0, 0.001, 0.0, 0.0, 0.0, 2.0
$ Mass with full inertia tensor on continuation line
CONM2, 2, 5, 0, 50.0, 0.1, 0.0, 0.0
+,     1.5, 0.0, 2.0, 0.0, 0.0, 3.0
```

---

### SPC — Single-Point Constraint (Grid Pairs)

Applies zero (or enforced) displacement to individual grid DOFs.

**Format:**
```
SPC, SID, G1, C1, D1, G2, C2, D2
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Constraint set ID (referenced in case control) | required |
| G1 | `g1` | int | Grid ID 1 | required |
| C1 | `c1` | str | DOF string for G1 (e.g., `"13"`, `"123456"`) | required |
| D1 | `d1` | float | Enforced displacement for G1 — must be `0.0` in Phase 1 | `0.0` |
| G2 | `g2` | int or None | Grid ID 2 (optional) | `None` |
| C2 | `c2` | str or None | DOF string for G2 | `None` |
| D2 | `d2` | float | Enforced displacement for G2 | `0.0` |

DOF digits: `1`=Tx, `2`=Ty, `3`=Tz, `4`=Rx, `5`=Ry, `6`=Rz. Multiple SPC cards with the same SID are merged.

**Example:**
```
$ Fix Tx and Tz at GID 1; fix Ty at GID 2
SPC, 1, 1, 13, 0.0, 2, 2, 0.0
```

---

### SPC1 — Single-Point Constraint (Grid List)

Applies zero displacement to the same DOFs across multiple grids.

**Format:**
```
SPC1, SID, C, G1, G2, G3, G4, G5, G6
+,    G7, G8, ...
```

Grid IDs may span continuation lines.

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Constraint set ID | required |
| C | `c` | str | DOF string applied to all grids | required |
| G1–Gn | `grids` | list[int] | Grid IDs to constrain | required |

**Example:**
```
$ Fix all 6 DOFs at GID 1 (encastre)
SPC1, 1, 123456, 1
$ Pin support: fix translations at GIDs 1 and 10
SPC1, 2, 123, 1, 10
```

---

### FORCE — Concentrated Force

Applies a force vector at a grid point.

**Format:**
```
FORCE, SID, GID, CID, F, N1, N2, N3
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Load set ID | required |
| GID | `gid` | int | Grid point | required |
| CID | `cid` | int | Coordinate system for N1–N3 (`0` = global) | `0` |
| F | `f` | float | Scale factor (force magnitude if N is a unit vector) | `0.0` |
| N1 | `n1` | float | Force direction component 1 | `0.0` |
| N2 | `n2` | float | Force direction component 2 | `0.0` |
| N3 | `n3` | float | Force direction component 3 | `0.0` |

Applied force vector = `F × [N1, N2, N3]`. Multiple FORCE cards with the same SID are summed.

**Example:**
```
$ 1000 N in –Z at GID 6, global frame
FORCE, 10, 6, 0, 1000.0, 0.0, 0.0, -1.0
$ 500 N in +X at GID 3, user coordinate system 2
FORCE, 10, 3, 2, 500.0, 1.0, 0.0, 0.0
```

---

### MOMENT — Concentrated Moment

Applies a moment vector at a grid point. Identical format to FORCE.

**Format:**
```
MOMENT, SID, GID, CID, M, N1, N2, N3
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Load set ID | required |
| GID | `gid` | int | Grid point | required |
| CID | `cid` | int | Coordinate system for N1–N3 (`0` = global) | `0` |
| M | `m` | float | Scale factor (moment magnitude if N is a unit vector) | `0.0` |
| N1 | `n1` | float | Moment axis component 1 | `0.0` |
| N2 | `n2` | float | Moment axis component 2 | `0.0` |
| N3 | `n3` | float | Moment axis component 3 | `0.0` |

Applied moment vector = `M × [N1, N2, N3]`.

**Example:**
```
$ 200 N·m about +Z at GID 6
MOMENT, 10, 6, 0, 200.0, 0.0, 0.0, 1.0
```

---

### LOAD — Load Superposition

Defines a combined load as a linear combination of FORCE/MOMENT load sets.

**Format:**
```
LOAD, SID, S, S1, L1, S2, L2, S3, L3, ...
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Combined load set ID (referenced in case control) | required |
| S | `s` | float | Overall scale factor | required |
| S1, S2, … | (in `components`) | float | Scale factor for component load i | required |
| L1, L2, … | (in `components`) | int | Load set ID for component load i (references FORCE/MOMENT SID) | required |

`components` is a list of `(scale: float, load_sid: int)` pairs. Applied load = `S × Σᵢ(Sᵢ × Loadᵢ)`.

**Example:**
```
$ Combine load sets 10 and 20 with factors 1.0 and 2.0, overall scale 1.0
LOAD, 100, 1.0, 1.0, 10, 2.0, 20
```

---

### EIGRL — Real Eigenvalue Extraction (Lanczos)

Defines parameters for normal modes extraction (SOL 103).

**Format:**
```
EIGRL, SID, V1, V2, ND, MSGLVL, MAXSET, SHFSCL, NORM
```

**Fields:**

| Field | Variable | Type | Description | Default |
|-------|----------|------|-------------|---------|
| SID | `sid` | int | Set ID (referenced by `METHOD` in case control) | required |
| V1 | `v1` | float or None | Lower frequency bound (Hz); blank = no lower limit | `None` |
| V2 | `v2` | float or None | Upper frequency bound (Hz); blank = no upper limit | `None` |
| ND | `nd` | int or None | Number of modes to extract; blank = all in [V1,V2] | `None` |
| MSGLVL | — | — | Message level — ignored | — |
| MAXSET | — | — | Maximum Lanczos set size — ignored | — |
| SHFSCL | — | — | Shift scale — ignored | — |
| NORM | `norm` | str | Mode shape normalisation: `"MASS"` or `"MAX"` | `"MASS"` |

At least one of ND or V2 must be specified to bound the extraction.

**Examples:**
```
$ Extract 10 modes, MASS normalisation, no frequency filter
EIGRL, 20, , , 10, , , , MASS
$ Extract all modes between 1 Hz and 100 Hz, MAX normalisation
EIGRL, 30, 1.0, 100.0, , , , , MAX
```

---

## DOF Reference

| DOF | Label | Physical meaning |
|-----|-------|-----------------|
| 1 | Tx | Translation along global X |
| 2 | Ty | Translation along global Y |
| 3 | Tz | Translation along global Z |
| 4 | Rx | Rotation about global X |
| 5 | Ry | Rotation about global Y |
| 6 | Rz | Rotation about global Z |

DOF strings (used in SPC, SPC1, RBE2, RBE3, CBAR pin releases) are digit sequences, e.g., `"123456"` = all DOFs, `"13"` = Tx and Tz only.

---

## Constraints and Limitations

| Card | Constraint |
|------|-----------|
| CBAR | Maximum 200 elements |
| CBAR | Offsets (W1A/W2A) not supported |
| CBUSH | CID must be `0` or blank |
| CBUSH | Damping (PBUSH `B` keyword) deferred to Phase 3 |
| CONM2 | CID must reference a defined CORD2R or be `0` |
| CORD2R | CID must be > 0; chained RID references supported; cycles raise `ValueError` |
| CORD2R | CORD2C/CORD2S/CORD1R not supported |
| EIGRL | V1/V2 filtering applied in Hz |
| MAT1 | Thermal fields (A, TREF, GE) parsed but ignored in Phase 1–2 |
| SPC | Enforced displacement D must be `0.0` in Phase 1–2 |
