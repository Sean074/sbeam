# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`sbeam` (Simple Beam FEA) is a Python-based finite element analysis program for beams using standard NASTRAN BDF input format. It is **not** related to RAM SBeam.

## Documentation Requirement

**When ANY code changes are made, the relevant project documentation files MUST be updated.** Each subsystem has a dedicated guide:

## Step Completion Requirement

**When a development step from `inital_project_guide.md` is completed, mark it complete immediately.** Add `✅ COMPLETE` to the step heading, for example:

```
### Step 7: Element Stiffness Matrix ✅ COMPLETE
```

Do this as part of the same session that implements the step — never batch completions or defer them.

| File | Scope |
|------|-------|
| `sbeam.md` | Overall program code standard, developer and user guide |
| `viewer.md` | Pre/post-processing viewer (Streamlit + Plotly) |
| `Beam_model.md` | Geometry and model definition (BDF cards, data model) |
| `Static_analysis.md` | SOL 101 static analysis solver |
| `Modal_analysis.md` | SOL 103 normal modes solver |
| `Methods.ipynb` | Summary of analytical methods (Euler-Bernoulli theory, stiffness and mass matrix derivations) |

## Development Phases

- **Phase 1 (complete):** SOL 101 (static) and SOL 103 (normal modes)
- **Phase 2:** SOL 108 (frequency response), 109 (transient), 111 (modal freq), 112 (modal transient)
- **Future (see `inital_project_guide.md` Phase 7):** distributed loads, local coordinate systems, Timoshenko shear, enforced displacements, buckling (SOL 105), results export

## Project Backlog

`inital_project_guide.md` is the authoritative backlog. It lists known bugs, Phase 2 steps, and future development ideas. **Do not delete it.** When a new development step is added, follow the same step format used for Phase 1–6.

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
| Elements | `CBAR`, `PLOTEL`, `RBE3` (constraint interpolation; DOF transformation), `RBE2` (rigid body; DOF transformation), `CBUSH` (two-node and grounded spring-damper; CID=0; offsets not supported) |
| Properties | `PBAR` (uniform cross-section: A, I1, I2, J, recovery points C/D/E/F), `PBUSH` (K1–K6 diagonal stiffness; B1–B6 damping deferred to dynamic solvers) |
| Material | `MAT1` (E, G, nu, rho) |
| Mass | `CONM2` (point mass; offset vector and inertia tensor in CID frame) |
| Constraints | `SPC`, `SPC1` (DOFs 1–6: Tx Ty Tz Rx Ry Rz) |
| Loads | `FORCE`, `MOMENT`, `LOAD` (linear combination) |
| Eigenvalue | `EIGRL` (SOL 103: modes, frequency range, normalization) |

### Case Control Cards (Phase 1)

`SOL`, `SUBCASE`, `LOAD`, `SPC`, `METHOD`, `DISPLACEMENT`, `SPCFORCE`, `OLOAD`, `FORCE`, `STRESS`, `BEGIN BULK`, `ENDDATA`

## Key Constraints

- Maximum **200 CBAR elements** (keeps matrices small enough for direct inversion — no sparse solvers)
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
├── model/          # grid.py, element.py, property.py, material.py, load.py, constraint.py, mass.py
├── assembly/       # stiffness.py, mass_matrix.py, rbe3.py
├── solver/         # sol101.py, sol103.py
├── results/        # results.py, f06_writer.py
├── gpwg.py         # Mass and CG (GPWG)
└── viewer/         # app.py, geometry.py, results_view.py, case_control_ui.py
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
