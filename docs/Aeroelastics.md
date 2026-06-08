# Aeroelastics.md — Phase A: Steady Vortex-Lattice Aeroelastics

## Architecture Overview

Phase A adds a steady vortex-lattice aerodynamic layer on top of the existing structural solver.
The data flow is:

```
BDF file
  ↓ parse_bulk_data()
BulkData  (bulk.aeros, bulk.caero1s, bulk.paero1s, bulk.aefacts, ...)
  ↓ build_aero_model()
AeroModel (boxes, ajj, skj, djk, wg, parity)
  ↓ solve_rigid_cl() / coupled aeroelastic solve (Phase B+)
Results   (cp, cl_section, CL, CM, …)
```

### Module map

| Module | Purpose |
|--------|---------|
| `sbeam/model/aero.py` | Dataclasses for aero BDF cards (`Aeros`, `Caero1`, `Paero1`, `Aefact`, `W2gj`, `Wkk`, `Aecorr`) |
| `sbeam/aero/panel.py` | `AeroBox` dataclass + `mesh_caero1()` — trapezoidal box meshing, ¼c/¾c placement |
| `sbeam/aero/vlm.py` | Biot–Savart segments, horseshoe influence, AIC matrix, rigid-AOA solve |
| `sbeam/aero/integration.py` | `Skj` force integration matrix, `Djk` downwash matrix, `wg` baseline normalwash |
| `sbeam/aero/corrections.py` | `Wkk` diagonal correction, `WT1` force-match, `WT2` pressure-match |
| `sbeam/aero/aero_model.py` | `AeroModel` container + `build_aero_model()` factory |
| `sbeam/viewer/aero_view.py` | Plotly box mesh, cp colour map, section-load strip chart |

---

## Supported BDF Cards

| Card | Purpose | Step |
|------|---------|------|
| `AEROS` | Reference geometry (cref, bref, sref) and symmetry flags | S39 |
| `CAERO1` | Aerodynamic panel definition (trapezoidal lifting surface) | S40 |
| `PAERO1` | Aerodynamic panel properties (stub in Phase A) | S40 |
| `AEFACT` | Arbitrary span/chord fraction lists for non-uniform meshing | S40 |
| `W2GJ` | Per-box baseline normalwash slopes | S42 |
| `WKK` | Diagonal AIC correction multipliers | S43 |
| `AECORR` | Force/pressure matching AIC corrections (WT1, WT2) | S43 |

---

## AEROS Card

### Purpose

The AEROS card defines the aerodynamic reference geometry used to non-dimensionalise
lift, drag, and moment coefficients, and to specify the symmetry condition for the
vortex lattice.

### Format

```
AEROS  ACSID  RCSID  CREF  BREF  SREF  SYMXZ  SYMXY
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| ACSID | int | 0 | Aerodynamic coordinate system (0 = basic) |
| RCSID | int | 0 | Reference coordinate system for rigid body motion |
| CREF | float | — | Reference chord length (consistent model units) |
| BREF | float | — | Reference span (full span, even for symmetric models) |
| SREF | float | — | Reference area (full area) |
| SYMXZ | int | 0 | +1 = symmetric about XZ plane, −1 = antisymmetric, 0 = no symmetry |
| SYMXY | int | 0 | +1 = symmetric about XY plane, −1 = antisymmetric, 0 = no symmetry |

### Symmetry conventions

- `SYMXZ = +1`: the model represents one semi-span; a mirror image is added across the
  XZ plane with the same circulation sign (symmetric lift). The VLM AIC matrix adds a
  positive mirror-image horseshoe for each box.
- `SYMXZ = -1`: antisymmetric (rolling) condition; the mirror image has opposite
  circulation sign. Net lift ≈ 0, rolling moment ≠ 0.
- `SYMXZ = 0`: full-span model, no image vortices added.

The parity value derived from `SYMXZ` is passed through the entire Phase A pipeline as
`parity = +1` (sym) or `parity = -1` (antisym).

### Validation rules

- **Duplicate AEROS**: only one AEROS card is permitted per model. A second card raises
  `ValueError("Duplicate AEROS card")`.
- **CAERO1 without AEROS**: if any CAERO1 cards are parsed and no AEROS card is present,
  `parse_bulk_data` raises `ValueError("CAERO1 card(s) present but no AEROS card found")`.
  This guard is implemented in `parse_bulk_data` (post-loop), using the `bulk.caero1s`
  dict populated by S40.

### Storage

```python
bulk.aeros  # Optional[Aeros], None until parsed
```

---

## CAERO1 / PAERO1 / AEFACT

*To be documented in S40.*

---

## VLM AIC Matrix

*To be documented in S41.*

---

## Integration Matrices (Skj, Djk, wg)

*To be documented in S42.*

---

## AIC Corrections (Wkk, WT1, WT2)

*To be documented in S43.*
