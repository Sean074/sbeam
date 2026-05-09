# sbeam — Program Code Standard, Developer and User Guide

## Purpose

`sbeam` (Simple Beam FEA) is a lightweight Python finite element analysis program for beam structures. It reads NASTRAN-format BDF input, solves SOL 101 (static) and SOL 103 (normal modes) analyses, and provides a Streamlit/Plotly viewer for pre- and post-processing.

**See also:** [`docs/card_definition.md`](card_definition.md) — BDF card reference (field definitions, variable names, examples for all supported cards).

---

## Project Structure

```
sbeam/
├── main.py               # CLI entry point
├── parser/
│   ├── bdf_reader.py     # Bulk data section parser → BulkData object
│   └── case_control.py   # Case control section parser → CaseControl object
├── model/
│   ├── grid.py               # Grid dataclass (includes cp, cd fields)
│   ├── element.py            # Cbar, Plotel, Rbe3, Rbe2, Rbar dataclasses
│   ├── property.py           # Pbar dataclass
│   ├── material.py           # Mat1 dataclass
│   ├── load.py               # Force, Moment, Load dataclasses
│   ├── constraint.py         # Spc, Spc1 dataclasses
│   ├── mass.py               # Conm2 dataclass
│   └── coordinate_system.py  # Cord2r dataclass
├── assembly/
│   ├── stiffness.py          # Global stiffness matrix assembly
│   ├── mass_matrix.py        # Global consistent mass matrix assembly
│   ├── rbe3.py               # RBE3, RBE2, and RBAR DOF transformation matrix
│   └── coord_transform.py    # CORD2R rotation matrices; input/output transforms
├── solver/
│   ├── sol101.py         # Static analysis
│   └── sol103.py         # Normal modes
├── results/
│   ├── results.py        # Results dataclass (displacements, forces, modes)
│   └── f06_writer.py     # .f06-format text output
├── gpwg.py               # Mass and centre-of-gravity calculation
└── viewer/
    ├── app.py            # Streamlit app entry point
    ├── geometry.py       # 3D Plotly model display
    ├── results_view.py   # Post-processing display
    └── case_control_ui.py # Case control form → BDF export
```

---

## Coding Standards

- Python 3.9+
- Type hints on all function signatures.
- Dataclasses (`@dataclass`) for all BDF card data objects.
- All physical arrays are `numpy.ndarray`. Matrix indices follow DOF ordering: [Tx, Ty, Tz, Rx, Ry, Rz] per node.
- No global mutable state. Pass model and results objects explicitly.
- Raise `ValueError` with a descriptive message for invalid input. Do not silently ignore errors.
- Unrecognised BDF cards: issue a `warnings.warn` and continue; log skipped card text.
- Tests live in `tests/` and mirror the `sbeam/` directory structure.

---

## DOF Numbering Convention

Each grid point has 6 DOFs numbered locally 1–6:

| Local | Physical |
|-------|----------|
| 1 | Translation X (Tx) |
| 2 | Translation Y (Ty) |
| 3 | Translation Z (Tz) |
| 4 | Rotation X (Rx) |
| 5 | Rotation Y (Ry) |
| 6 | Rotation Z (Rz) |

Global DOF index for grid `i`, local DOF `d` (0-based): `6 * i + d`.

---

## Units

BDF format is unit-agnostic. The user is responsible for a consistent unit system throughout the model. Recommended:

| Quantity | SI | Imperial |
|----------|----|----------|
| Length | m | in |
| Force | N | lbf |
| Mass | kg | lb·s²/in (slinch) |
| Stress | Pa | psi |

Results are output in the same units as input. The `.f06` header should echo any unit note provided in the model comments.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| Singular stiffness matrix | `ValueError`: "Singular stiffness matrix — check for unconstrained DOFs" |
| Unrecognised BDF card | `warnings.warn` + skip; list skipped cards in output |
| Missing referenced ID (GRID, PID, MID) | `ValueError` with card type and offending ID |
| Zero-length element | `ValueError` with element ID |
| More than 200 CBAR elements | `ValueError` with count |
| No SPC constraints (SOL 101) | `ValueError`: "Model has no SPC constraints" |

---

## Entry Points

### Viewer (primary)

```
streamlit run viewer/app.py
```

The Streamlit viewer is the **primary entry point** for all interactive use. It handles both file types:

| File type | Content | Viewer behaviour |
|-----------|---------|-----------------|
| Bulk data file (`.dat` or `.bdf`) | GRID, CBAR, PBAR, MAT1, SPC, FORCE, etc. — no case control | Parsed via `parse_bulk_file()`; model displayed immediately; user defines case control in the UI |
| Run file (`.bdf`) | Case control (`SOL`, `SUBCASE`, …) + bulk data (inline or via `INCLUDE`) | Parsed via `parse_bdf()`; both `CaseControl` and `BulkData` loaded |

Detection is automatic: the viewer scans uploaded file content for a `SOL` statement before `BEGIN BULK`.

### CLI (secondary — batch/automation)

```
python -m sbeam run.bdf
# or, after pip install:
sbeam run.bdf
```

Reads a run file (case control required), determines SOL, runs analysis, and writes `run.f06` **to the same directory as the input file**. Supports SOL 101 and SOL 103; multiple subcases are written sequentially to a single `.f06` file.

Exit codes: 0 on success; 1 on parse or solver error (message printed to stderr). Omitting the argument prints usage and exits with code 2.

---

## Dependency Requirements

```
numpy>=1.24
scipy>=1.10
pandas>=2.0
plotly>=5.18
streamlit>=1.30
```

---

## Testing

```
pytest tests/
```

### Unit tests

Tests mirror the `sbeam/` module structure under `tests/`. Each assembly, solver, parser, results, and viewer sub-package has a corresponding test module.

### Integration tests — verification suite

`tests/integration/test_verification.py` exercises the full pipeline (`parse_bdf → run_sol101/103 → results`) against closed-form analytical values. BDF input files live in `tests/integration/bdf/`.

| ID | BDF file | SOL | Check | Tolerance |
|----|----------|-----|-------|-----------|
| V1 | `v1_v2_cantilever.bdf` | 101 | Tip deflection = PL³/3EI | < 0.1% |
| V2 | `v1_v2_cantilever.bdf` | 101 | Fixed-end moment = PL | < 0.1% |
| V3 | `v3_simply_supported.bdf` | 101 | Mid-span deflection = PL³/48EI | < 0.1% |
| V4 | `v4_fixed_fixed_udl.bdf` | 101 | Reactions sum to total load | < 0.1% |
| V5 | `v5_cantilever_modal.bdf` | 103 | f₁ = (1.8751²/2π)√(EI/ρAL⁴) | < 1% |
| V6 | `v6_free_free_modal.bdf` | 103 | First 6 modes < 0.1 Hz (rigid body) | — |
| V7 | `v7_simply_supported_modal.bdf` | 103 | f₁ = (π²/2πL²)√(EI/ρA) | < 1% |
| V8 | `v8_conm2_torsional_inertia.bdf` | 103 | f = √(GJ/L·I₁₁)/(2π) | < 1% |
| V9 | `v9_conm2_offset_bending.bdf` | 103 | Coupled 2-DOF f₁, f₂ (CONM2 axial offset) | < 1% |
| V10 | `v10_conm2_zero_density.bdf` | 103 | f = √(3EI/mL³)/(2π) (tip mass, zero density) | < 1% |
| V11 | `v11_cantilever_torsion_sol101.bdf` | 101 | θ_x = T·L/(G·J) | < 0.1% |
| V12 | `v12_conm2_offset_torsion_sol103.bdf` | 103 | f = √(GJ/L·m·d²)/(2π) (transverse offset) | < 1% |
| V13 | `v13_rbe2_rigid_coupling.bdf` | 101 | Tip deflection = PL³/3EI via RBE2 coupling | < 0.1% |
| V14 | `v14_rbar_zero_offset.bdf` | 101 | Tip deflection = PL³/3EI via RBAR (zero-offset, R=identity) | < 0.1% |

V1–V7 use: E=2.0×10¹¹ Pa, ρ=7850 kg/m³, A=0.05 m², I=8.333×10⁻⁴ m⁴, L=1.0 m, 10 CBAR elements. V8–V14 use unit stiffness values defined in their BDF files; see `tests/integration/test_verification.py` for exact parameters.

---

## Version and Phase

| Phase | Capability | Status |
|-------|------------|--------|
| 1 | SOL 101 Static analysis | Complete |
| 1 | SOL 103 Normal modes | Complete |
| 1 | BDF cards: CORD2R, GRID, CBAR, PBAR, MAT1, SPC/SPC1, FORCE, MOMENT, LOAD, PLOTEL, CONM2, EIGRL | Complete |
| 2 | BDF cards: RBE2, RBE3, CBUSH, PBUSH, RBAR | Complete |
| 2 | SOL 108 Direct frequency response | Planned |
| 2 | SOL 109 Direct transient response | Planned |
| 2 | SOL 111 Modal frequency response | Planned |
| 2 | SOL 112 Modal transient response | Planned |
