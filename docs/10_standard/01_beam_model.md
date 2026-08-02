# Beam Model — Geometry and Model Definition

## Overview

The `sbeam` data model represents a NASTRAN-format beam structure. All data originates from BDF card input. The model is assembled into Python dataclass objects by the parser and held in a central `BulkData` object used by the assembler and solver.

This document covers the **data model**: the `BulkData` container, the card → dataclass mapping, the parser API, and coordinate-system/model limits. Per-card field layouts, defaults, validation rules, and examples live in the card reference: [`02_card_reference.md`](02_card_reference.md).

---

## Supported Cards

One dataclass per card type; parsed instances are stored in `BulkData` (see below). Field-by-field definitions for every card are in [`02_card_reference.md`](02_card_reference.md).

### Geometry and structure

| Card | Purpose |
|------|---------|
| `CORD2R` | Rectangular coordinate system defined by three points A/B/C; chained `RID` references supported |
| `GRID` | Grid point (node); `CP` = input frame for coordinates, `CD` = output frame for results |
| `CBAR` | Two-node Euler-Bernoulli beam element (orientation vector, OFFT, pin releases) |
| `PBAR` | Uniform beam cross-section property (A, I1, I2, J, NSM, stress recovery points C/D/E/F) |
| `MAT1` | Isotropic material (E, G, NU, RHO; G auto-derived from E and NU when blank) |
| `PLOTEL` | Plot-only line element — visualisation, no stiffness or mass |
| `CBUSH` / `PBUSH` | Two-node or grounded diagonal spring element and its K1–K6 stiffness property |

### Rigid / interpolation elements

| Card | Purpose |
|------|---------|
| `RBE2` | Rigid coupling: dependent grids follow one independent grid for the CM DOFs |
| `RBE3` | Interpolation constraint: reference grid = weighted average of independent grids |
| `RBAR` | Rigid bar: all 6 DOFs at GB slaved to GA with full lever-arm kinematics |

All three are assembled as a DOF transformation matrix **T** (`n_dof × n_red`) in `assembly/rbe3.py` (`build_rbe3_transformation()`). T is applied to K and M before SPC partitioning (`K_red = Tᵀ K T`, `M_red = Tᵀ M T`); full displacements/mode shapes are recovered via `u_full = T @ u_red`.

### Mass, constraints, and loads

| Card | Purpose |
|------|---------|
| `CONM2` | Concentrated mass with optional CG offset vector and inertia tensor (in a CID frame) |
| `SPC` / `SPC1` | Single-point constraints (grid/DOF pairs or a DOF string across a grid list) |
| `FORCE` / `MOMENT` | Concentrated force/moment at a grid (direction in a CID frame) |
| `LOAD` | Linear combination of FORCE/MOMENT/GRAV load sets |
| `GRAV` | Body acceleration load via the assembled consistent mass matrix (`f = M·a`) |
| `EIGRL` | Real eigenvalue extraction parameters for SOL 103 (bounds, mode count, normalisation) |

### Aerodynamics (Phase A)

| Card | Purpose |
|------|---------|
| `AEROS` | Aerodynamic reference geometry (CREF/BREF/SREF); one per model, full-span only |
| `CAERO1` | Flat trapezoidal lifting-surface macroelement, meshed NSPAN × NCHORD |
| `PAERO1` | Aerodynamic panel property (Phase A stub) |
| `AEFACT` | Fraction list for non-uniform span/chord panel spacing |
| `W2GJ` | Per-box baseline normalwash slopes (geometric incidence) |
| `WKK` | Diagonal AIC correction weights |
| `AECORR` | WT2 pressure-matching AIC correction (WT1 force-matching is deprecated — DEF-H2/H3) |

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
    rbars: dict[int, Rbar]
    pbars: dict[int, Pbar]
    pbushs: dict[int, Pbush]
    mat1s: dict[int, Mat1]
    conm2s: dict[int, Conm2]
    spcs: dict[int, list[Spc]]
    spc1s: dict[int, list[Spc1]]
    forces: dict[int, list[Force]]
    moments: dict[int, list[Moment]]
    loads: dict[int, Load]
    gravs: dict[int, Grav]
    eigrls: dict[int, Eigrl]
    cord2rs: dict[int, Cord2r]
    aeros: Optional[Aeros]               # single AEROS card (or None)
    caero1s: dict[int, Caero1]
    paero1s: dict[int, Paero1]
    aefacts: dict[int, Aefact]
    w2gjs: dict[int, W2gj]
    wkks: dict[int, Wkk]
    aecorrs: dict[int, Aecorr]
```

All dictionaries are keyed by the card's primary ID (GID, EID, PID, SID, CID, etc.).

### Notable dataclass shapes

| Dataclass | Structure |
|-----------|-----------|
| `Rbe3` | `eid: int`, `refgrid: int`, `refc: str`, `wt_gc: list` of `(weight: float, dofs: str, grids: list[int])` tuples |
| `Rbe2` | `eid: int`, `gn: int`, `cm: str`, `gm: list[int]` |
| `Rbar` | `eid: int`, `ga: int`, `gb: int`, `cna: str = "123456"`, `cnb: str = ""` |

### Coordinate-system handling

All internal computation is in global CID 0. After parsing, `resolve_grid_positions()` transforms every grid position from its `CP` system into CID 0 in-place; the `cd` field is preserved for output transformation of nodal results. `CORD2R` frames are also used to rotate FORCE/MOMENT direction vectors and CONM2 offset vectors / inertia tensors into CID 0 before assembly.

---

## Model Limits

| Quantity | Limit | Reason |
|----------|-------|--------|
| CBAR elements | No hard limit | Sparse solver used; memory and compute time are the practical constraint |
| AEROS ACSID/RCSID | 0 only (Phase A) | Non-zero aerodynamic coordinate systems deferred |
| AEROS | One per model | Duplicate raises `ValueError` |
| CAERO1 NSPAN/LSPAN | Exactly one non-zero | Both zero or both non-zero raises `ValueError` |
| CAERO1 NCHORD/LCHORD | Exactly one non-zero | Both zero or both non-zero raises `ValueError` |
| CAERO1 IGID | Ignored in Phase A | Interference group support deferred |
| PAERO1 | Phase A stub | Body element support deferred |
| W2GJ/WKK/AECORR | One correction tier active | WKK overrides WT2/WT1 if all present; WT1 deprecated |
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
3. Loads every path in `CaseControl.includes`, in the order the `INCLUDE` lines appear, and concatenates them; the lines after `BEGIN BULK` are appended to that.
4. Passes the bulk data lines to `parse_bulk_data`.
5. Returns `(CaseControl, BulkData)`.

**Several `INCLUDE`s are allowed** (Step 66), which is how a driver deck composes a shared bulk with an overlay without duplicating the shared part — see `sample/cessna210_flagship_body.bdf`. `ENDDATA` is an ignored keyword rather than a terminator, so an included file ending in one does not truncate the files behind it. `CaseControl.include` remains as the first entry for callers that expect a single path.

Raises `FileNotFoundError` if any INCLUDE file does not exist.

### `parse_case_control(lines) -> CaseControl` — `parser/case_control.py`

Parses the case control section (lines above `BEGIN BULK`). Uses space/equals keyword syntax — not the comma/fixed-field bulk format. Recognises: `SOL`, `TITLE`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `TRIM`, `DIVERG`, `MLOADS`, `MASSSET`, `AEROF`, `APRES`, `DISPLACEMENT`, `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `INCLUDE`.

Raises `ValueError` if `SOL` is absent or not one of 101/103/144.

### `parse_bulk_data(lines) -> BulkData` — `parser/bdf_reader.py`

Accepts a list of BDF text lines (bulk data section only). Supports:

- **Free-field format** — comma-separated fields (e.g. `GRID, 1, , 0.0, 0.0, 0.0`)
- **Fixed-field format** — 8-character columns (standard NASTRAN small-field)
- **Inline `$` comments** — everything from `$` to end of line is ignored
- **Continuation lines** — lines whose first field starts with `+`; consumed by the preceding card handler (e.g. PBAR recovery points, SPC1 with >6 grids)

Cards recognised: `CORD2R`, `GRID`, `PBAR`, `PBUSH`, `MAT1`, `CBAR`, `CBUSH`, `PLOTEL`, `CONM2`, `MASSSET`, `RBE3`, `RBE2`, `RBAR`, `SPC`, `SPC1`, `FORCE`, `MOMENT`, `LOAD`, `GRAV`, `EIGRL`, `SUPORT`, plus the aero/trim/monitor/maneuver families: `AEROS`, `AEFACT`, `PAERO1`, `PSTRIP`, `STRIPK`, `CAERO1`, `W2GJ`, `WKK`, `AECORR`, `SET1`, `SPLINE0`, `SPLINE1`, `SPLINE2`, `ATTACH`, `AESTAT`, `AESURF`, `AELIST`, `TRIM`, `DIVERG`, `TRIMVAR`, `TRIMOBJ`, `TRIMCON`, `AECOMP`, `MONPNT1`, `MONPNT3`, `MLOADS`, `MLDTRIM`, `MLDTIME`, `MLDCOMD`, `MLDPRNT`, `TABLED1` (full list with fields in `02_card_reference.md`).
Structural markers `BEGIN BULK` / `ENDDATA` are silently skipped.
All other keywords issue `warnings.warn(…, UserWarning)` and are skipped.
Duplicate GID, PID (PBAR), MID (MAT1), or LOAD SID raises `ValueError`.

**Ordering constraints:** PBAR and MAT1 must appear before the CBAR elements that reference them. PBUSH must appear before the CBUSH elements that reference it. CORD2R cards may appear in any order relative to each other; cycles in `RID` references raise `ValueError`.

**CBAR cross-reference validation** (at parse time):
- `GA` or `GB` not in `bulk.grids` → `ValueError`
- `PID` not in `bulk.pbars` → `ValueError`
**DOF string validation** (SPC and SPC1 cards):
- Any character outside `1–6` (including `"0"`) → `ValueError`

**LOAD component validation** (post-parse, after all cards are read):
- Component SID not found in `bulk.forces` or `bulk.moments` → `ValueError`

**CAERO1 cross-reference validation** (post-parse, after all cards are read):
- CAERO1 present but no AEROS → `ValueError`
- PID not in `bulk.paero1s` → `ValueError`
- LSPAN or LCHORD references a missing AEFACT SID → `ValueError`

---

## Verification

A valid model must satisfy:
- Every CBAR references an existing PBAR (by PID) and two existing GRIDs.
- Every PBAR references an existing MAT1 (by MID).
- No duplicate GIDs, EIDs, PIDs, MIDs, or LOAD SIDs.
- No zero-length CBAR elements.
- At least one SPC set defined (SOL 101).
- No hard CBAR element limit (sparse solver); memory and runtime are the practical constraint.
