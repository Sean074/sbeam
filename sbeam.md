# sbeam — Program Code Standard, Developer and User Guide

## Purpose

`sbeam` (Simple Beam FEA) is a lightweight Python finite element analysis program for beam structures. It reads NASTRAN-format BDF input, solves SOL 101 (static) and SOL 103 (normal modes) analyses, and provides a Streamlit/Plotly viewer for pre- and post-processing.

---

## Project Structure

```
sbeam/
├── main.py               # CLI entry point
├── parser/
│   ├── bdf_reader.py     # Bulk data section parser → BulkData object
│   └── case_control.py   # Case control section parser → CaseControl object
├── model/
│   ├── grid.py           # Grid dataclass
│   ├── element.py        # Cbar, Plotel, Rbe3, Rbe2 dataclasses
│   ├── property.py       # Pbar dataclass
│   ├── material.py       # Mat1 dataclass
│   ├── load.py           # Force, Moment, Load dataclasses
│   ├── constraint.py     # Spc, Spc1 dataclasses
│   └── mass.py           # Conm2 dataclass
├── assembly/
│   ├── stiffness.py      # Global stiffness matrix assembly
│   ├── mass_matrix.py    # Global consistent mass matrix assembly
│   └── rbe3.py           # RBE3 and RBE2 DOF transformation matrix
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

- Python 3.10+
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
python main.py run.bdf
```

Reads a run file (case control required), determines SOL, runs analysis, writes `run.f06`. Implemented last as a thin wrapper around the solver; the viewer handles all typical interactive workflows.

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

All verification cases use consistent model parameters: E=2.0×10¹¹ Pa, ρ=7850 kg/m³, A=0.05 m², I=8.333×10⁻⁴ m⁴, L=1.0 m, 10 CBAR elements.

---

## Version and Phase

| Phase | SOL | Status |
|-------|-----|--------|
| 1 | 101 Static | Complete |
| 1 | 103 Normal modes | Complete |
| 2 | 108/109/111/112 | Planned |
