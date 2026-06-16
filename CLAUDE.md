# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`sbeam` (Simple Beam FEA) is a Python-based finite element analysis program for beams using standard NASTRAN BDF input format. It is **not** related to RAM SBeam.

## Documentation Requirement

**When ANY code changes are made, the relevant project documentation files MUST be updated.**

`docs/` is organised into four numbered sections by document type. The map is
`docs/00_INDEX.md` — start there. The code-standard guides (section `10_standard/`) are the
ones that must track code changes:

| File | Scope |
|------|-------|
| `docs/10_standard/00_program_overview.md` | Overall program code standard, developer and user guide |
| `docs/10_standard/01_beam_model.md` | Geometry and model definition (BDF cards, data model) |
| `docs/10_standard/02_card_reference.md` | BDF card field reference (all supported cards) |
| `docs/10_standard/03_static_analysis.md` | SOL 101 static analysis solver |
| `docs/10_standard/04_modal_analysis.md` | SOL 103 normal modes solver |
| `docs/10_standard/05_aeroelastics.md` | Phase A VLM aeroelastics developer/user guide |
| `docs/10_standard/06_viewer.md` | Pre/post-processing viewer (Streamlit + Plotly) |
| `docs/10_standard/07_code_review_process.md` | Critical code-review process |
| `docs/10_standard/08_release_process.md` | Versioning and release process |
| `docs/20_theory/00_beam_methods.ipynb` | Analytical methods (Euler-Bernoulli theory, stiffness/mass matrix derivations) |
| `docs/20_theory/01_aeroelastics_theory.md` | Phase A theoretical reference (VLM, AIC corrections, structural coupling) |

## Step Completion Requirement

**HARD REQUIREMENT — When any backlog item, bug, NIT, or future design item is closed/resolved, ALL THREE of the following MUST be done in the same session. No exceptions.**

1. **`docs/30_future/00_backlog.md`** — **REMOVE** the item entirely. Do not leave it marked `✅ RESOLVED`; resolved items do not belong in the backlog.
2. **`docs/40_history/00_completed_development.md`** — **ADD** the item with its full step format (Objective, Deliverables, Test/Acceptance, key decisions). For resolved bugs/NITs, add under "Resolved Defects".
3. **`CHANGELOG.md`** — **ADD** an entry in the `[Unreleased]` section describing what was done.

Never batch these updates or defer them to a later session. The backlog is for **open** items only — anything closed must be moved out immediately.

## Development Phases

- **Phase 1 (complete):** SOL 101 (static) and SOL 103 (normal modes) — see `docs/40_history/00_completed_development.md`
- **Phase 2:** Model enhancements — see `docs/30_future/00_backlog.md`
- **Phase 3:** SOL 108 (frequency response), 109 (transient), 111 (modal freq), 112 (modal transient) — see `docs/30_future/00_backlog.md`
- **Phase A (in progress):** Steady VLM aeroelastics (Steps 39–45 + A9 cruciform body-panel total-moment correction + A10 decoupled strip body panel complete; A7/A8 open) — see `docs/10_standard/05_aeroelastics.md` and `docs/30_future/00_backlog.md`
- **Phase G0 (in progress):** DLM-free quasi-steady transient maneuver loads — increment 1 complete (ZAERO `MLOADS` card set; Level-1 quasi-steady, open-loop; restrained l-set Newmark-β). Follow-ons (free-flight rigid-body coupling, modal ROM, unsteady corrections, closed-loop control) in `docs/30_future/00_backlog.md`
- **Future:** distributed loads, Timoshenko shear, enforced displacements, buckling (SOL 105), results export — see `docs/30_future/00_backlog.md`

## Project Backlog

`docs/30_future/00_backlog.md` is the authoritative backlog. It lists open bugs, Phase 2 and Phase 3 steps, and future development ideas. When a new development step is added, follow the same step format used in `docs/40_history/00_completed_development.md`.

## Tech Stack

Python with: `scipy`, `numpy`, `matplotlib`, `pandas`, `plotly`, `streamlit`, `csv`

## Beam Theory

Phase 1 uses **Euler-Bernoulli beam theory** (shear deformation neglected). Each CBAR element has 12 DOFs (6 per node). Phase 1 uses a **consistent mass matrix**.

## Input File Format

- Model geometry / bulk data: `*.dat` or `*.bdf` (user-defined BDF card format)
- Case control: `*.bdf` (main file, exported from viewer UI — this is what the solver reads; uses `INCLUDE` to pull in the bulk data file)
- Results: `*.f06` (NASTRAN-style output)

### Supported BDF Cards (Phase 1)

| Category | Cards |
|----------|-------|
| Coordinate systems | `CORD2R` (rectangular system; defined by three points A, B, C; supports chained RID references) |
| Geometry | `GRID` (CP = input system; CD = output system for results) |
| Elements | `CBAR`, `PLOTEL`, `RBE3` (constraint interpolation; DOF transformation), `RBE2` (rigid body; DOF transformation), `RBAR` (rigid bar; kinematic coupling with lever-arm), `CBUSH` (two-node and grounded spring-damper; CID=0; offsets not supported) |
| Properties | `PBAR` (uniform cross-section: A, I1, I2, J, recovery points C/D/E/F), `PBUSH` (K1–K6 diagonal stiffness; B1–B6 damping deferred to dynamic solvers) |
| Material | `MAT1` (E, G, nu, rho) |
| Mass | `CONM2` (point mass; offset vector and inertia tensor in CID frame) |
| Constraints | `SPC`, `SPC1` (DOFs 1–6: Tx Ty Tz Rx Ry Rz) |
| Loads | `FORCE`, `MOMENT`, `LOAD` (linear combination), `GRAV` (body acceleration; CID=0 only; f = M×a) |
| Eigenvalue | `EIGRL` (SOL 103: modes, frequency range, normalization) |
| Transient maneuver (Phase G0) | `MLOADS` (driver), `MLDTRIM` (initial-condition TRIM sid), `MLDCOMD` (pilot command label → `TABLED1`), `MLDTIME` (t0/tend/dt/tout), `MLDPRNT` (ASCII output), `TABLED1` (tabular function) |
| Monitor points (SOL 144) | `MONPNT1` (aero-only integrated section load), `MONPNT3` (aero + inertia + reaction, splined to structural grids), `AECOMP` (named AELIST-box / SET1-grid collection) |

### Case Control Cards (Phase 1)

`SOL`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `TRIM`, `MLOADS` (Phase G0 transient maneuver), `DISPLACEMENT`, `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `BEGIN BULK`, `ENDDATA`

## Key Constraints

- No hard CBAR element limit — sparse solver used for all models; memory and compute time are the practical constraint
- **CORD2R rectangular coordinate systems supported** (Step 32); CORD2C/CORD2S/CORD1R not supported
- All internal computations in global CID 0; CORD2R used for input (GRID CP, FORCE/MOMENT/CONM2 CID) and output (GRID CD) transforms only
- Uniform cross-section elements only (no tapered beams in phase 1)
- Euler-Bernoulli only (no Timoshenko shear in phase 1)
- Units are user-defined and must be consistent throughout the model

## Module Structure

```
sbeam/
├── main.py
├── parser/         # bdf_reader.py, case_control.py
├── model/          # grid.py, element.py, property.py, material.py, load.py, constraint.py, mass.py, aero.py, maneuver.py (ZAERO MLOADS cards), maneuver_presets.py
├── assembly/       # stiffness.py, mass_matrix.py, rbe3.py
├── solver/         # sol101.py, sol103.py, sol144.py (static aeroelastic trim), maneuver_qs.py (Phase G0 transient maneuver loads)
├── results/        # results.py, f06_writer.py, load_export.py, monitor_points.py (MONPNT1/MONPNT3 integrated section loads), maneuver_output.py (Phase G0 time histories + critical-step export)
├── gpwg.py         # Mass and CG (GPWG)
├── aero/           # panel.py, vlm.py, integration.py, corrections.py, section_correction.py (W2GJ+WT2 section force/moment synthesis), section_data.py (spanwise section-coefficient ingestion), body_correction.py (cruciform + decoupled-strip body-panel total-aircraft moment match), strip.py (decoupled strip body panels — PSTRIP/STRIPK, zero-coupling diagonal AIC block), aero_model.py
└── viewer/         # app.py, geometry.py, results_view.py, case_control_ui.py, aero_view.py, aero_correction_view.py (CFD/test section data → correction cards + full corrected-BDF export), format_utils.py (5-sig-fig table/metric formatting)
```

## GPWG

Mass and CG computation is called **GPWG** (Grid Point Weight Generator), not "OLOAD". OLOAD is an applied load output request in case control.

## Workflow

1. Define geometry, properties, materials, and loads in BDF card format (`*.dat`)
2. View and interrogate model in the Streamlit viewer
3. Run GPWG (mass and CG summary)
4. Define case control via viewer UI → export `*.bdf`
5. Run analysis (SOL 101 or 103)
6. Review results: deflected shape / nodal forces (SOL 101); mode shapes / frequencies (SOL 103)
7. Output results to `*.f06`-format file

## Results Output

- **SOL 101:** nodal displacements, SPC reactions, applied load echo, CBAR end forces/moments, CBAR stresses at recovery points, CBUSH element forces (global coordinates)
- **SOL 103:** natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions
- **SOL 144** (static aeroelastic trim, Phase C): trim variables, rigid + elastic-restrained stability derivatives, per-AESURF hinge-moment derivatives (about the `cid1` hinge axis), total CL/CMY, critical divergence dynamic pressure, displacements/CBAR loads, and (on `AEROF`/`APRES` request) per-box ΔCp and forces. Exports trimmed aero flight loads as `FORCE`/`MOMENT` cards (`<stem>.aero_loads.bdf`). For balanced maneuvers (Step 53) it also emits the net (aero + inertial) maneuver load (`net_loads`/`inertial_loads`, with per-case force/moment closure) and exports it as `<stem>.maneuver_loads.bdf`. With `MONPNT1`/`MONPNT3` cards present it emits a `MONITOR POINT INTEGRATED LOADS` f06 block and a per-run `<stem>.monitor_loads.csv` (aero-only / aero+inertia+reaction integrated section loads with an `Fz_aero/Fz_inertia/Fz_react` breakdown)
- **SOL 144 transient maneuver loads** (Phase G0, DLM-free): a SOL 144 subcase with an `MLOADS = sid` request runs `solver/maneuver_qs.py` — a Level-1 quasi-steady, open-loop, restrained-l-set Newmark-β time integration seeded from a Step 53 trim (`MLDTRIM`). Per output time it recovers displacements, CBAR loads, instantaneous aero loads, and the net (aero + inertial) maneuver load. Writes an MLDPRNT ASCII time-history (`<stem>.mldprnt.txt`) and the critical-sample net-load `FORCE`/`MOMENT` export (`<stem>.maneuver_qs_loads.bdf`). ZAERO card set: `MLOADS`/`MLDTRIM`/`MLDCOMD`/`MLDTIME`/`MLDPRNT` + `TABLED1`.

## Verification Test Cases

All solvers must pass closed-form verification:
- Cantilever tip load: δ = PL³/3EI (SOL 101)
- Simply supported mid-span load: δ = PL³/48EI (SOL 101)
- Cantilever fundamental frequency: f₁ = (1.875²/2π)√(EI/ρAL⁴) (SOL 103)
- Free-free beam: first 6 modes must be ~0 Hz (SOL 103)

## Reference Material

- NASA-CR-145949
- https://www.sesamx.io/blog/beam_finite_element/
- https://mechanicalc.com/reference/finite-element-analysis
