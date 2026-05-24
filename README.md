# sbeam — Simple Beam FEA

A Python finite element analysis tool for beam structures using NASTRAN BDF input format. Supports static analysis (SOL 101) and normal modes (SOL 103) via Euler-Bernoulli beam theory.

**License:** MIT (see [LICENSE](LICENSE)) — free to use, modify, and redistribute, including commercially.

## Requirements

- Python 3.9+
- pip

## Installation

Clone the repository and create a virtual environment:

```bash
git clone <repo-url>
cd sbeam
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

Install the package and its dependencies in editable mode:

```bash
pip install -e .
```

The editable install registers `sbeam` into the active environment so it is importable from anywhere — including inside Streamlit.

## Running the Viewer

```bash
streamlit run sbeam/viewer/app.py
```

The viewer opens in your browser. Upload a `*.dat` bulk data file to inspect model geometry, define case control, and launch analyses.

A sample model is provided at `sample/simple_beam.dat` — a 10 m steel cantilever beam (5 CBAR elements, SI units).

## Running the Solver

```bash
python -m sbeam.main path/to/model.bdf
```

The solver reads the case control file (`.bdf`), which uses `INCLUDE` to reference the bulk data file (`.dat`). Results are written to a `.f06` file in NASTRAN format.

## Running Tests

```bash
pytest
```

## Workflow

1. Define geometry in a `*.dat` bulk data file (GRID, CBAR, PBAR, MAT1, SPC, FORCE, etc.)
2. Open the Streamlit viewer to inspect the model and run GPWG (mass/CG summary)
3. Define case control in the viewer UI and export a `*.bdf` file
4. Run the solver against the exported `*.bdf`
5. Review results in the `*.f06` output file or load them back into the viewer

## Supported BDF Cards

| Category | Cards |
|---|---|
| Geometry | `GRID`, `CORD2R`|
| Elements | `CBAR`, `CBUSH`, `PLOTEL`, `RBE2`, `RBE3`, `RBAR` |
| Properties | `PBAR`, `PBUSH` |
| Material | `MAT1` |
| Mass | `CONM2` |
| Constraints | `SPC`, `SPC1` |
| Loads | `FORCE`, `MOMENT`, `LOAD` |
| Eigenvalue | `EIGRL` |

## Analysis Types

- **SOL 101** — Linear statics: nodal displacements, SPC reactions, CBAR end forces/moments, stress recovery
- **SOL 103** — Normal modes: natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions

## Limitations (Phase 1)

- Global coordinate system (CID 0) only
- Uniform cross-section elements (no tapered beams)
- Euler-Bernoulli beam theory (shear deformation neglected)

## Author

Sean O'Meara — <sean.c.omeara74@gmail.com>

Bug reports and pull requests are welcome via the GitHub issue tracker.

## Disclaimer

`sbeam` implements standard, well-published finite element methods (Euler-Bernoulli beam theory, consistent mass matrix, direct stiffness assembly) using established numerical libraries. It is intended as an educational and exploratory engineering tool.

Results are **not certified** for safety-critical or regulated structural design. The implementation uses simplified assumptions (uniform cross-sections, no shear deformation, global coordinate frame, dense direct solver). Verify any results against an established commercial solver and competent engineering judgement before relying on them for design decisions.

The software is provided "as is", without warranty of any kind. See the [LICENSE](LICENSE) file for the full disclaimer of liability.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Sean O'Meara.
