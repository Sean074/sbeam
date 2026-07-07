# sbeam — Program Code Standard, Developer and User Guide

## Purpose

`sbeam` (Simple Beam FEA) is a lightweight Python finite element analysis program for beam structures. It reads NASTRAN-format BDF input, solves SOL 101 (static), SOL 103 (normal modes), and SOL 144 (static aeroelastic trim + divergence) analyses — a SOL 144 subcase with an `MLOADS` request additionally runs the Phase G0 quasi-steady transient maneuver-loads solver — and provides a Streamlit/Plotly viewer for pre- and post-processing.

**See also:** [card reference](02_card_reference.md) — BDF card reference (field definitions, variable names, examples for all supported cards).

---

## Project Structure

```
sbeam/
├── main.py               # CLI entry point (SOL routing, f06 + load/monitor/maneuver exports)
├── parser/
│   ├── bdf_reader.py     # Bulk data section parser → BulkData object
│   └── case_control.py   # Case control section parser → CaseControl object
├── model/
│   ├── bulk_data.py          # BulkData container dataclass
│   ├── grid.py               # Grid dataclass (includes cp, cd fields)
│   ├── element.py            # Cbar, Plotel, Rbe3, Rbe2, Rbar dataclasses
│   ├── property.py           # Pbar, Pbush dataclasses
│   ├── material.py           # Mat1 dataclass
│   ├── load.py               # Force, Moment, Load, Grav dataclasses
│   ├── constraint.py         # Spc, Spc1 dataclasses
│   ├── mass.py               # Conm2 dataclass
│   ├── coordinate_system.py  # Cord2r dataclass
│   ├── aero.py               # Aero/trim card dataclasses (Aeros, Caero1, Paero1, Pstrip, Stripk, Aefact, W2gj, Wkk, Aecorr, Set1, Spline0/1/2, Attach, Aestat, Aesurf, Aelist, Trim, Diverg, …)
│   ├── maneuver.py           # ZAERO MLOADS card set (Mloads, Mldtrim, Mldcomd, Mldtime, Mldprnt, Tabled1) for Phase G0
│   └── maneuver_presets.py   # Balanced-maneuver TRIM authoring presets (load factor / steady rate → AESTAT values, Step 53)
├── assembly/
│   ├── stiffness.py          # Global stiffness matrix assembly
│   ├── mass_matrix.py        # Global consistent mass matrix assembly
│   ├── load_vector.py        # Load vector assembly (FORCE, MOMENT, GRAV)
│   ├── rbe3.py               # RBE3, RBE2, and RBAR DOF transformation matrix
│   ├── reduction.py          # Shared RBE3+SPC g-set → a-set reduction (reduce_to_aset / AsetReduction, Step 59)
│   └── coord_transform.py    # CORD2R rotation matrices; input/output transforms
├── solver/
│   ├── sol101.py         # Static analysis
│   ├── sol103.py         # Normal modes
│   ├── sol144.py         # Static aeroelastic trim (Schur solve, derivatives), divergence sweep, AeroCache
│   └── maneuver_qs.py    # Phase G0 quasi-steady transient maneuver loads (restrained l-set Newmark-β)
├── results/
│   ├── results.py        # Results dataclass (displacements, forces, modes)
│   ├── f06_writer.py     # .f06-format text output (SOL 101/103/144 trim + divergence blocks)
│   ├── load_export.py    # Trimmed aero + net maneuver FORCE/MOMENT card export; monitor-point CSV
│   ├── monitor_points.py # MONPNT1/MONPNT3 integrated section loads (aero-only / aero+inertia+reaction)
│   └── maneuver_output.py # Phase G0 MLDPRNT ASCII time histories + critical-step net-load export
├── gpwg.py               # Mass and centre-of-gravity calculation
├── aero/
│   ├── __init__.py
│   ├── panel.py          # AeroBox dataclass + mesh_caero1() trapezoidal box meshing
│   ├── vlm.py            # Biot–Savart, horseshoe influence, build_ajj, solve_rigid_cl
│   ├── integration.py    # build_skj, build_djk, build_wg integration matrices
│   ├── corrections.py    # apply_wkk, apply_wt2, apply_wt1 AIC corrections
│   ├── section_correction.py # W2GJ+WT2 card-pair synthesis matching section force and moment
│   ├── section_data.py   # Spanwise section-coefficient table (CSV) ingestion → strip targets
│   ├── body_correction.py # Cruciform (A9) + decoupled-strip (A10) body-panel total-aircraft moment match
│   ├── strip.py          # Decoupled strip body panels (PSTRIP/STRIPK; zero-coupling diagonal AIC block)
│   ├── mirror.py         # mirror_halfspan(): half-span (SYMXZ) deck → full-span unfold migration aid
│   ├── spline.py         # build_g_spline(): g_slope / g_disp from SPLINE2 + ATTACH + SPLINE0 cards
│   ├── coupling.py       # build_qaa (flexible aero stiffness), build_fg, build_gaf (modal GAF Qhh)
│   └── aero_model.py     # AeroModel dataclass + build_aero_model() factory
└── viewer/
    ├── app.py            # Streamlit app entry point
    ├── geometry.py       # 3D Plotly model display
    ├── results_view.py   # Post-processing display
    ├── case_control_ui.py # Case control form → BDF export
    ├── aero_view.py      # Aero box mesh + cp colour maps, span loading, S&C derivative tables
    ├── aero_correction_view.py # Aero Correction tab: CFD/test section data → correction cards + corrected-BDF export
    └── format_utils.py   # Shared 5-sig-fig table/metric formatting (fmt / fmt_mass / style_numeric)
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
| Bulk data file (`.dat` or `.bdf`) | GRID, CBAR, PBAR, MAT1, SPC, FORCE, etc., plus the aero/trim card families (AEROS/CAERO1/SPLINE2/AESTAT/AESURF/TRIM/MONPNT/MLOADS, …) — no case control. Full list in [card reference](02_card_reference.md) | Parsed via `parse_bulk_file()`; model displayed immediately; user defines case control in the UI |
| Run file (`.bdf`) | Case control (`SOL`, `SUBCASE`, …) + bulk data (inline or via `INCLUDE`) | Parsed via `parse_bdf()`; both `CaseControl` and `BulkData` loaded |

Detection is automatic: the viewer scans uploaded file content for a `SOL` statement before `BEGIN BULK`.

### CLI (secondary — batch/automation)

```
python -m sbeam run.bdf
# or, after pip install:
sbeam run.bdf
```

Reads a run file (case control required), determines SOL, runs analysis, and writes `run.f06` **to the same directory as the input file**. Supports SOL 101, SOL 103, and SOL 144; multiple subcases are written sequentially to a single `.f06` file.

For SOL 144 each subcase is routed by its case-control requests: `TRIM` → static aeroelastic trim, `DIVERG` (without `TRIM`) → divergence sweep, `MLOADS` → Phase G0 quasi-steady transient maneuver loads. Besides the `.f06` (trim + divergence blocks), the CLI writes additional files next to the input:

| File | Content | Written when |
|------|---------|--------------|
| `<stem>.aero_loads.bdf` | Trimmed aero flight loads as `FORCE`/`MOMENT` cards (SID = subcase id) | Any trim subcase |
| `<stem>.maneuver_loads.bdf` | Net (aero + inertial) balanced-maneuver loads (Step 53) | Any trim subcase |
| `<stem>.monitor_loads.csv` | MONPNT1/MONPNT3 integrated section loads across subcases | Trim subcases with monitor points |
| `<stem>.mldprnt.txt` | MLDPRNT ASCII maneuver time histories | Any `MLOADS` subcase |
| `<stem>.maneuver_qs_loads.bdf` | Critical-sample net-load `FORCE`/`MOMENT` export | Any `MLOADS` subcase |

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
| V15 | `v15_grav_simply_supported.bdf` | 101 | Reactions sum to ρALg (CBAR mass only under GRAV) | < 0.01% |
| V16 | `v16_grav_with_conm2.bdf` | 101 | Reactions sum to (ρAL + m_conm2)·g (CBAR mass + CONM2 under GRAV) | < 0.01% |
| V17 | `v17_grav_plus_force.bdf` | 101 | Reactions sum to net load (GRAV + upward FORCE combined via LOAD card) | < 0.01% |
| V18 | `v18_rbe2_offset.bdf` | 101 | u_y at GN/GM satisfy cantilever formula with eccentric load; u_GM = R·u_GN (RBE2 lever-arm) | < 0.1% |

V1–V7 use: E=2.0×10¹¹ Pa, ρ=7850 kg/m³, A=0.05 m², I=8.333×10⁻⁴ m⁴, L=1.0 m, 10 CBAR elements. V8–V18 use parameters defined in their BDF files; see `tests/integration/test_verification.py` for exact values.

### Coverage

Every `pytest` run automatically emits a per-file branch-coverage table (configured via `addopts` in `pyproject.toml`). No extra flags needed:

```
pytest
```

To enforce the ≥85% floor on the three gated modules (`solver/`, `assembly/`, `parser/`) explicitly — use this command for CI gates or pre-merge checks:

```
pytest --cov=sbeam/solver --cov=sbeam/assembly --cov=sbeam/parser --cov-fail-under=85
```

`viewer/` coverage is included in the default report for visibility but is **not** subject to the 85% floor — it requires Streamlit `AppTest` integration tests (TEST1) to reach a meaningful level.

---

## Version and Phase

| Phase | Capability | Status |
|-------|------------|--------|
| 1 | SOL 101 Static analysis | Complete |
| 1 | SOL 103 Normal modes | Complete |
| 1 | BDF cards: CORD2R, GRID, CBAR, PBAR, MAT1, SPC/SPC1, FORCE, MOMENT, LOAD, PLOTEL, CONM2, EIGRL | Complete |
| 2 | BDF cards: RBE2, RBE3, CBUSH, PBUSH, RBAR | Complete |
| 2 | BDF card: GRAV (gravity body load; CID=0; f = M×a via consistent mass matrix) | Complete |
| A | Steady VLM aeroelastics: card parsing, panel meshing, AIC + integration matrices, AIC corrections (Wkk, WT1, WT2), section force/moment correction synthesis, body-panel total-moment corrections | Steps 39–45 + A9 (cruciform) + A10 (decoupled strip) complete; A7/A8 warnings open |
| B | Structural coupling splines: SPLINE2/ATTACH/SPLINE0 → g_slope/g_disp; flexible aero stiffness Q_aa | Complete (Step 48 SPLINE1 surface spline deferred) |
| C | SOL 144 static aeroelastic trim: Schur trim solve, rigid + elastic-restrained derivatives, hinge moments, divergence sweep, balanced-maneuver loads (Step 53), monitor points, load exports | Essentially complete (AE8b unrestrained mean-axis derivatives + optional Step 54 CHORDCP open) |
| G0 | DLM-free quasi-steady transient maneuver loads (ZAERO MLOADS card set; restrained l-set Newmark-β) | Increment 1 complete (free-flight rigid-body coupling, modal ROM, unsteady corrections, closed-loop control open) |
| 3 | SOL 108 Direct frequency response | Planned |
| 3 | SOL 109 Direct transient response | Planned |
| 3 | SOL 111 Modal frequency response | Planned |
| 3 | SOL 112 Modal transient response | Planned |

The authoritative open-items list is `docs/30_future/00_backlog.md` — see its "Aeroelastic
completion plan" (Steps AC1–AC6) for the remaining Phase A/C close-out work.

**Version strategy:** `pyproject.toml` version is `0.1.0` and classifier is `3 - Alpha` for Phase 1.
On Phase 2 completion (SOL 108/109/111/112 all passing), bump to `0.2.0` and change the classifier
to `4 - Beta`.
