# sbeam — Simple Beam FEA

A Python finite element analysis tool for beam structures. It reads a documented subset of the NASTRAN BDF input format (MSC NASTRAN and ZAERO card layouts) and refuses the rest; the known differences are listed in [`docs/10_standard/12_deviation_register.md`](docs/10_standard/12_deviation_register.md). Supports static analysis (SOL 101) and normal modes (SOL 103) via Euler-Bernoulli beam theory, plus static aeroelastics (SOL 144): steady vortex-lattice aerodynamics, flexible trim, stability derivatives, divergence, monitor-point section loads, quasi-static gust cases, and DLM-free quasi-steady transient maneuver loads (sbeam's `MANVR` card set). A SOL 103 run can also write a reduced modal model (OP4 and Universal file) for use in other programs.

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
install that never opens the GUI. The `[dev]` extra adds pytest, ruff and pyright, which
the test suite needs: `pip install -e ".[viewer,dev]"`.

The editable install registers `sbeam` into the active environment so it is importable from anywhere — including inside Streamlit.

## Running the Viewer

```bash
sbeam-view
```

(`sbeam-view` is `streamlit run sbeam_tools/viewer/app.py`; extra arguments go to `streamlit run`.)

The viewer opens in your browser. Open a deck in the sidebar in one of two ways:

- **Open from disk** — pick a bundled sample deck or type a path. Use this for a run file that has an `INCLUDE`, so the included file is found beside it.
- **Upload** a `*.bdf` or `*.dat` file. An uploaded file cannot `INCLUDE` another file.

With a deck open you can inspect the model, see the mass and C.G. summary, define case control, author SOL 144 cases (trim, divergence, mass cases, gust, maneuver, monitors), run the analysis and review the results. Guide: [`docs/10_standard/06_viewer.md`](docs/10_standard/06_viewer.md).

A sample model is provided at `sample/beam/simple_beam.dat` — a 10 m steel cantilever beam (5 CBAR elements, SI units). The sample decks are grouped by model family; [`sample/README.md`](sample/README.md) says what each one is for.

## Running the Solver

```bash
sbeam path/to/model.bdf
```

(`sbeam` is `python -m sbeam.main`.)

The solver reads the run file (`.bdf`): case control, then `BEGIN BULK`, where an `INCLUDE` may bring in the bulk data file (`.dat`). Results are written to a `.f06` file in NASTRAN format. A SOL 144 run file is checked against its model before the first subcase is solved; a fault stops the run with every fault listed.

## Running the Loads Tools

`sbeam` is a solver: it analyses the cases a deck gives it. Deciding *which* cases exist,
and reducing results across them, is the job of the `sbeam_tools` package that ships
alongside it — which, unlike the solver, is allowed to know about physical units,
standard atmospheres and regulatory constants.

Generate the FAR/CS 23.341 quasi-static gust design cases for a deck:

```bash
sbeam-cases sample/cessna210_flagship/cessna210_flagship_trim.bdf --units SI --trim-template 1 --vc 86.0 --vd 105.0 --massset 10,20,30 -o gust_cases.bdf
```

It reads the reference geometry, the weight of each mass case and the rigid lift-curve
slope out of the deck itself, applies the gust schedule and the Pratt formula, and writes
a runnable driver deck plus a summary table. Run the result with `sbeam` like any other
deck.

See `docs/10_standard/00_program_overview.md` (Architecture) for the boundary between the
two packages, and `docs/10_standard/05c_sol144_maneuver.md` for the gust workflow.

## Running Tests

```bash
pip install -e ".[viewer,dev]"
pytest
```

## First analysis in ten minutes

New here? [`docs/20_theory/03_first_analysis_tutorial.md`](docs/20_theory/03_first_analysis_tutorial.md)
takes you from an empty folder to a plotted SOL 101 result: a six-grid cantilever typed
in by hand, one CLI run, the f06 read block by block against the closed-form deflection
and stress, then the deflected shape in the viewer and from a ten-line Python script.
Calling the solver from your own code: [`docs/10_standard/11_python_api.md`](docs/10_standard/11_python_api.md).

## Documentation

Full documentation lives in [`docs/`](docs/00_INDEX.md), organised into four sections:
code standard (`10_standard/`), theory & worked examples (`20_theory/`), future development
(`30_future/`), and historic record (`40_history/`). Start at the
[documentation index](docs/00_INDEX.md).

## Workflow

1. Define geometry in a `*.dat` bulk data file (GRID, CBAR, PBAR, MAT1, SPC, FORCE, etc.; for aeroelastic models add the AEROS/CAERO1/SPLINE2/TRIM card set)
2. Open the model in the viewer to inspect it and see the GPWG mass/CG summary
3. Define case control in the viewer and, for SOL 144, author the trim, divergence, mass, gust, maneuver and monitor cards there. Cards of the loaded deck are not changed in place; an edit is saved under a new ID. Export a `*.bdf` run file
4. Run the analysis from the viewer, or run the solver on the exported `*.bdf`
5. Review results in the viewer or in the `*.f06` output file (SOL 144 adds trimmed flight-load / maneuver-load BDF exports and a monitor-loads CSV). The viewer shows the results of a run it made; it does not read an `.f06`

## Supported BDF Cards

| Category | Cards |
|---|---|
| Geometry | `GRID`, `CORD2R` |
| Elements | `CBAR`, `CROD`, `CONROD`, `CBUSH`, `PLOTEL`, `RBE2`, `RBE3`, `RBAR` |
| Properties | `PBAR`, `PROD`, `PBUSH` |
| Material | `MAT1` |
| Mass | `CONM2`, `MASSCASE`, `MASSSET` |
| Constraints | `SPC`, `SPC1`, `SUPORT` |
| Loads | `FORCE`, `MOMENT`, `LOAD`, `GRAV` |
| Eigenvalue | `EIGRL` |
| Aero geometry | `AEROS`, `CAERO1`, `PAERO1`, `AEFACT`, `PSTRIP`, `STRIPK` |
| Aero corrections | `W2GJ`, `WKK`, `DMIJ` (W2GJ), `DMIK` (WKK), `AECORR`, `CPINJ` |
| Splining | `SET1`, `LOADINJ`, `SPLINE1`*, `SPLINE2`, `BODYATT` |
| Trim / divergence / gust | `AESTAT`, `AESURF`, `AELIST`, `TRIM`, `DIVERG`, `TRIMVAR`, `TRIMWGT`, `TRIMINEQ`, `GUSTLF` |
| Monitor points / section cuts | `MONPNT1`, `MONSECT`, `AECOMP` |
| Transient maneuver | `MANVR`, `MANTRIM`, `MANTIME`, `MANCMD`, `MANPRNT`, `TABLED1` |

\* `SPLINE1` is not implemented: a deck that has one is refused (use `SPLINE2`).

`MONPNT3` is refused; a structural sum is written as a `MONPNT1` that names a `SET1`.

Full field-by-field definitions, case control keywords and `PARAM` rules: [`docs/10_standard/02_card_reference.md`](docs/10_standard/02_card_reference.md).

## Analysis Types

- **SOL 101** — Linear statics: nodal displacements, SPC reactions, CBAR end forces/moments, stress recovery, CBUSH element forces
- **SOL 103** — Normal modes: natural frequencies (Hz and rad/s), normalised mode shapes, modal mass fractions; reduced modal model export (`MODEXP`: OP4 and Universal file)
- **SOL 144** — Static aeroelastic trim (steady VLM): determined and over-determined trim, rigid, elastic-restrained and elastic-unrestrained stability derivatives, hinge-moment derivatives, divergence dynamic pressure (`DIVERG`), balanced maneuver loads with inertia relief, applied structural loads in the trim (thrust, engine torque via `LOAD`), mass cases (`MASSCASE`), FAR/CS 23.341 quasi-static gust cases (`GUSTLF`), monitor-point integrated section loads, trimmed flight-load export
- **SOL 144 + `MANVR`** — DLM-free quasi-steady transient maneuver loads (Phase G0, Level 1): open-loop commanded control histories integrated by Newmark-β from a trimmed initial condition, with time-history output and critical-sample load export

## Known Limitations

### Beam theory
- **Euler-Bernoulli only** — Timoshenko shear correction (PBAR K1/K2) is not applied. A `PBAR` with non-blank K1/K2 is refused.
- **Uniform cross-section only** — tapered beams are not supported. `PBARL` (standard shape library) is not supported; cross-section properties must be entered directly via `PBAR`.

### Coordinate systems
- **`CORD2R` only** — `CORD2C`, `CORD2S`, and `CORD1R` are not supported.
- **`GRAV` requires CID=0** — a non-zero CID on a `GRAV` card raises a parse error.

### Elements
- **`RBE3` simplified** — uses same-DOF weighted averaging; rotation-to-translation lever-arm coupling across an offset is not applied. Use `RBAR` for kinematically exact rigid connections when grid offsets are present. An offset RBE3 warns, and a REFC DOF in no Ci (e.g. `REFC=123456` with `Ci=123`) is refused.
- **`CBUSH`** — `CID` is basic or a `CORD2R`; a grounded or coincident-grid spring needs a `CID`. The `GO` orientation grid and the `OCID` spring offset are refused.

### Loads
- **`PLOAD1` not supported** — distributed beam loads are not implemented. A deck carrying `PLOAD1` (or any other known-but-unsupported NASTRAN card) is refused at parse with a counted list; replace it with equivalent `FORCE`/`MOMENT` cards. Table of refused cards and alternatives: `docs/10_standard/02_card_reference.md`, "Unsupported cards".

### Solvers
- **SOL 101, SOL 103, and SOL 144 only** — frequency response (SOL 108 / SOL 111), transient response (SOL 109 / SOL 112), and buckling (SOL 105) are not yet implemented.

### Aeroelastics
- **Steady, subsonic VLM only** — Mach ≥ 1 is rejected; no doublet-lattice (DLM) unsteady aerodynamics or flutter solution yet. Transient maneuver loads are quasi-steady (valid for reduced frequency k ≲ 0.1).
- **Full-span models only** — `AEROS` SYMXZ/SYMXY half-span symmetry is rejected; mirror the model to full span.

### General
- No hard element count limit; memory and compute time are the practical constraints.
- Results are not certified for safety-critical or regulated structural design — see the Disclaimer below.

## Author

Sean O'Meara — <sean.c.omeara74@gmail.com>

Bug reports and pull requests are welcome via the GitHub issue tracker.

## Disclaimer

`sbeam` implements standard, well-published finite element methods (Euler-Bernoulli beam theory, consistent mass matrix, direct stiffness assembly) using established numerical libraries. It is intended as an educational and exploratory engineering tool.

Results are **not certified** for safety-critical or regulated structural design. The implementation uses simplified assumptions (uniform cross-sections, no shear deformation, global coordinate frame, sparse direct solver for the structure and dense influence-coefficient matrices for the aerodynamics). Verify any results against an established commercial solver and competent engineering judgement before relying on them for design decisions.

The software is provided "as is", without warranty of any kind. See the [LICENSE](LICENSE) file for the full disclaimer of liability.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Sean O'Meara.
