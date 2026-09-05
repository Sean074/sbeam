# sbeam — Simple Beam FEA

A Python finite element analysis tool for beam structures using NASTRAN BDF input format. Supports static analysis (SOL 101) and normal modes (SOL 103) via Euler-Bernoulli beam theory, plus static aeroelastics (SOL 144): steady vortex-lattice aerodynamics, flexible trim, stability derivatives, divergence, monitor-point section loads, and DLM-free quasi-steady transient maneuver loads (ZAERO-style `MLOADS`).

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
pip install -e ".[viewer]"
```

`pip install -e .` alone installs the **solver and the loads toolchain** (numpy, scipy,
pandas). The `[viewer]` extra adds Streamlit and Plotly — omit it for a batch or CI
install that never opens the GUI.

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

## Running the Loads Tools

`sbeam` is a solver: it analyses the cases a deck gives it. Deciding *which* cases exist,
and reducing results across them, is the job of the `sbeam_tools` package that ships
alongside it — which, unlike the solver, is allowed to know about physical units,
standard atmospheres and regulatory constants.

Generate the FAR/CS 23.341 quasi-static gust design cases for a deck:

```bash
sbeam-cases sample/cessna210_flagship_trim.bdf --units SI --trim-template 1 --vc 86.0 --vd 105.0 --massset 10,20,30 -o gust_cases.bdf
```

It reads the reference geometry, the weight of each mass case and the rigid lift-curve
slope out of the deck itself, applies the gust schedule and the Pratt formula, and writes
a runnable driver deck plus a summary table. Run the result with `sbeam` like any other
deck.

See `docs/10_standard/00_program_overview.md` (Architecture) for the boundary between the
two packages, and `docs/10_standard/05c_sol144_maneuver.md` for the gust workflow.

## Running Tests

```bash
pytest
```

## Documentation

Full documentation lives in [`docs/`](docs/00_INDEX.md), organised into four sections:
code standard (`10_standard/`), theory & worked examples (`20_theory/`), future development
(`30_future/`), and historic record (`40_history/`). Start at the
[documentation index](docs/00_INDEX.md).

## Workflow

1. Define geometry in a `*.dat` bulk data file (GRID, CBAR, PBAR, MAT1, SPC, FORCE, etc.; for aeroelastic models add the AEROS/CAERO1/SPLINE2/TRIM card set)
2. Open the Streamlit viewer to inspect the model and run GPWG (mass/CG summary)
3. Define case control in the viewer UI and export a `*.bdf` file (SOL 144 trim/divergence/maneuver cases are authored directly in the BDF)
4. Run the solver against the exported `*.bdf`
5. Review results in the `*.f06` output file or load them back into the viewer (SOL 144 adds trimmed flight-load / maneuver-load BDF exports and a monitor-loads CSV)

## Supported BDF Cards

| Category | Cards |
|---|---|
| Geometry | `GRID`, `CORD2R` |
| Elements | `CBAR`, `CBUSH`, `PLOTEL`, `RBE2`, `RBE3`, `RBAR` |
| Properties | `PBAR`, `PBUSH` |
| Material | `MAT1` |
| Mass | `CONM2` |
| Constraints | `SPC`, `SPC1`, `SUPORT` |
| Loads | `FORCE`, `MOMENT`, `LOAD`, `GRAV` |
| Eigenvalue | `EIGRL` |
| Aero geometry | `AEROS`, `CAERO1`, `PAERO1`, `AEFACT`, `PSTRIP`, `STRIPK` |
| Aero corrections | `W2GJ`, `WKK`, `AECORR` |
| Splining | `SET1`, `SPLINE0`, `SPLINE1`*, `SPLINE2`, `ATTACH` |
| Trim / divergence | `AESTAT`, `AESURF`, `AELIST`, `TRIM`, `DIVERG`, `TRIMVAR`, `TRIMOBJ`, `TRIMCON` |
| Monitor points | `MONPNT1`, `MONPNT3`, `AECOMP` |
| Transient maneuver | `MLOADS`, `MLDTRIM`, `MLDTIME`, `MLDCOMD`, `MLDPRNT`, `TABLED1` |

\* `SPLINE1` is parsed but not yet implemented (use `SPLINE2`).

Full field-by-field definitions: [`docs/10_standard/02_card_reference.md`](docs/10_standard/02_card_reference.md).

## Analysis Types

- **SOL 101** — Linear statics: nodal displacements, SPC reactions, CBAR end forces/moments, stress recovery, CBUSH element forces
- **SOL 103** — Normal modes: natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions
- **SOL 144** — Static aeroelastic trim (steady VLM): determined and over-determined trim, rigid + elastic-restrained stability derivatives, hinge-moment derivatives, divergence dynamic pressure (`DIVERG`), balanced maneuver loads with inertia relief, monitor-point integrated section loads, trimmed flight-load export
- **SOL 144 + `MLOADS`** — DLM-free quasi-steady transient maneuver loads (Phase G0, Level 1): open-loop commanded control histories integrated by Newmark-β from a trimmed initial condition, with time-history output and critical-sample load export

## Known Limitations

### Beam theory
- **Euler-Bernoulli only** — Timoshenko shear correction (PBAR K1/K2) is not applied. K1/K2 fields are parsed but silently ignored, which is the correct assumption for slender beams where shear deformation is negligible.
- **Uniform cross-section only** — tapered beams are not supported. `PBARL` (standard shape library) is not supported; cross-section properties must be entered directly via `PBAR`.

### Coordinate systems
- **`CORD2R` only** — `CORD2C`, `CORD2S`, and `CORD1R` are not supported.
- **`GRAV` requires CID=0** — a non-zero CID on a `GRAV` card raises a parse error.

### Elements
- **`RBE3` simplified** — uses same-DOF weighted averaging; rotation-to-translation lever-arm coupling across an offset is not applied. Use `RBAR` for kinematically exact rigid connections when grid offsets are present.
- **`CBUSH` requires CID=0** — element offsets are not supported.

### Loads
- **`PLOAD1` not supported** — distributed beam loads are not implemented. A `PLOAD1` card in the BDF is currently silently dropped with no user-visible warning. Do not use `PLOAD1`; a pre-solve validator warning is planned for a future release.

### Solvers
- **SOL 101, SOL 103, and SOL 144 only** — frequency response (SOL 108 / SOL 111), transient response (SOL 109 / SOL 112), and buckling (SOL 105) are not yet implemented.

### Aeroelastics
- **Steady, subsonic VLM only** — Mach ≥ 1 is rejected; no doublet-lattice (DLM) unsteady aerodynamics or flutter solution yet. Transient maneuver loads are quasi-steady (valid for reduced frequency k ≲ 0.1).
- **Full-span models only** — `AEROS` SYMXZ/SYMXY half-span symmetry is rejected; mirror the model to full span.
- **Unrestrained (mean-axis) stability derivatives not yet computed** — rigid and elastic-restrained columns are output; the trim solution itself is unaffected.

### General
- No hard element count limit; memory and compute time are the practical constraints.
- Results are not certified for safety-critical or regulated structural design — see the Disclaimer below.

## Author

Sean O'Meara — <sean.c.omeara74@gmail.com>

Bug reports and pull requests are welcome via the GitHub issue tracker.

## Disclaimer

`sbeam` implements standard, well-published finite element methods (Euler-Bernoulli beam theory, consistent mass matrix, direct stiffness assembly) using established numerical libraries. It is intended as an educational and exploratory engineering tool.

Results are **not certified** for safety-critical or regulated structural design. The implementation uses simplified assumptions (uniform cross-sections, no shear deformation, global coordinate frame, dense direct solver). Verify any results against an established commercial solver and competent engineering judgement before relying on them for design decisions.

The software is provided "as is", without warranty of any kind. See the [LICENSE](LICENSE) file for the full disclaimer of liability.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Sean O'Meara.
