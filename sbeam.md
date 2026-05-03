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
│   ├── element.py        # Cbar, Plotel, Rbe3 dataclasses
│   ├── property.py       # Pbar dataclass
│   ├── material.py       # Mat1 dataclass
│   ├── load.py           # Force, Moment, Load dataclasses
│   ├── constraint.py     # Spc, Spc1 dataclasses
│   └── mass.py           # Conm2 dataclass
├── assembly/
│   ├── stiffness.py      # Global stiffness matrix assembly
│   └── mass_matrix.py    # Global consistent mass matrix assembly
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

Run verification test cases from `tests/verification/`:

```
pytest tests/
```

All solvers must pass analytical verification before release. See `Beam_model.md` and `Static_analysis.md` / `Modal_analysis.md` for case details.

---

## Version and Phase

| Phase | SOL | Status |
|-------|-----|--------|
| 1 | 101 Static | In development |
| 1 | 103 Normal modes | In development |
| 2 | 108/109/111/112 | Planned |
