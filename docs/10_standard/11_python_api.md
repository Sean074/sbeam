# Calling sbeam from Python — the public entry points

The guides `01`–`10` describe the deck format, the solvers and the CLI. This one is for
code that imports sbeam: a script, a notebook, a test harness, or a tool such as the
sloads round-trip gate, which already depends on `parse_bdf`, `run_sol101` and
`compute_gpwg`. It names the functions and classes that are **public**, states what
everything else is, and shows the two calling patterns the CLI itself uses.

**Gate:** `tests/docs/test_python_api_guide.py` imports every symbol named in §3 and runs
the examples in §2 and §4, so this page cannot name something that does not exist.

---

## 1. What "public" means here

- **Public** is exactly the set in §3. These names, their signatures as written there and
  the fields of the result dataclasses are the contract. Changing one is a breaking change:
  pre-1.0 it is shipped as a MINOR bump under **Breaking changes** in `CHANGELOG.md`
  (`08_release_process.md` §1), after 1.0 as a MAJOR.
- **Internal** is everything else under `sbeam/`: the assembly layer, the solver stage
  functions, the parser card handlers, the `sol144.py` facade beyond the three names
  listed below, and the whole of `sbeam/viewer/`. `sbeam_tools/` reaches into internals
  by design (`00_program_overview.md`, Architecture); it ships in the same distribution and
  is fixed in the same commit. External code that imports an internal name gets no
  stability promise and no CHANGELOG line when it moves.
- **The CLI is the reference consumer.** `sbeam/main.py` uses only public names, in the
  order shown in §2 and §4. When in doubt about how to drive a solver, read it.

There is no `sbeam.api` facade and no `__all__` curation beyond `sbeam/types.py` and the
`sol144.py` facade: the import paths below are the real module paths, and they are stable.

---

## 2. The pattern: parse, run, read, write

Every solution is three calls. For SOL 101 and SOL 103 the solver takes the bulk data
and one subcase:

```python
# example_sol101 — tests/docs/test_python_api_guide.py runs this verbatim
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import build_f06_sol101_text
from sbeam.solver.sol101 import run_sol101

case_control, bulk = parse_bdf("sample/simple_beam.bdf")      # 1. parse
subcase = case_control.subcases[0]
result = run_sol101(bulk, subcase)                            # 2. run

index = build_grid_index(bulk)                                # 3. read
tip_t3 = result.displacements[6 * index[6] + 2]               #    grid 6, T3
root = result.bar_forces[1]                                   #    element 1
print(f"tip T3 = {tip_t3:.6e}   root M2 = {root.m2_a:.3e}   reactions = {result.reactions[1]}")

f06_text = build_f06_sol101_text(case_control, bulk, result, subcase.subcase_id)   # 4. write
```

Run from the repository root it prints the tutorial cantilever's answers
(`../20_theory/03_first_analysis_tutorial.md`):

```
tip T3 = -2.000080e-03   root M2 = -1.000e+04   reactions = [     0.      0.   1000.      0. -10000.      0.]
```

Three rules that apply to every result:

- **Displacement vectors are flat, six entries per grid, grids in ascending GID order.**
  Entry `6*i + d` is DOF `d` (0–5 = T1 T2 T3 R1 R2 R3) of the grid at position `i`, and
  `build_grid_index(bulk)` is the `{gid: i}` map. Mode shapes are `(n_dofs, n_modes)` with
  the same row layout. Vectors are in the basic frame (CID 0); the f06 writer applies each
  grid's `CD` frame on output, the result objects do not (`09_conventions.md`).
- **Element and grid tables are dictionaries keyed by ID**: `bar_forces[eid]`,
  `reactions[gid]`, `monitor_loads[name]`. Missing key means the deck had no such item or
  the subcase did not produce it.
- **Errors are `ValueError`** (bad deck, singular stiffness, unsupported card, trim that
  cannot be posed) **or `FileNotFoundError`** (deck or `INCLUDE`). The parser also issues
  `UserWarning` for unknown cards and advisories; collect them as the CLI does with
  `warnings.catch_warnings(record=True)` if they matter to you.

---

## 3. The public surface

### 3.1 Parse

| Name | Import | Signature | Notes |
|---|---|---|---|
| `parse_bdf` | `from sbeam.parser.bdf_reader import parse_bdf` | `(filepath) -> (CaseControl, BulkData)` | Run file: case control + bulk, inline or via one or more `INCLUDE`s. Rejects unsupported cards (#45). |
| `parse_bulk_file` | `from sbeam.parser.bdf_reader import parse_bulk_file` | `(filepath) -> BulkData` | Bulk-data-only file, no case control required (the viewer's upload path). |
| `parse_bulk_data` | `from sbeam.parser.bdf_reader import parse_bulk_data` | `(lines: list[str]) -> BulkData` | Bulk lines already in memory. |
| `parse_case_control` | `from sbeam.parser.case_control import parse_case_control` | `(lines: list[str]) -> CaseControl` | Case-control lines already in memory. |

Parser behaviour (formats, ordering rules, cross-reference validation): `01_beam_model.md`.

### 3.2 Model and model-level queries

| Name | Import | Role |
|---|---|---|
| `BulkData` | `from sbeam.model.bulk_data import BulkData` | The parsed deck: one `dict[int, Card]` per card family (`grids`, `cbars`, `pbars`, `mat1s`, `forces`, `trims`, …) plus `aeros` and `supports`. Dataclass map: `01_beam_model.md`. |
| `CaseControl`, `SubcaseControl` | `from sbeam.parser.case_control import CaseControl, SubcaseControl` | `sol`, `subcases`; per subcase the selected set IDs (`load_sid`, `spc_sid`, `method_sid`, `trim_sid`, `diverg_sid`, `mloads_sid`, `massset_sid`, …) and output flags. Build one by hand to run a subcase the deck does not contain. |
| `build_grid_index` | `from sbeam.assembly.load_vector import build_grid_index` | `(bulk) -> dict[int, int]`, the DOF layout key above. |
| `compute_gpwg`, `GpwgResult` | `from sbeam.gpwg import compute_gpwg, GpwgResult` | `(bulk, massset_sid=None) -> GpwgResult(total_mass, cg_x, cg_y, cg_z, massset_sid, massset_label)`. Mass and CG of the baseline or a `MASSSET` case. |
| `resolve_mass_case`, `MassCase` | `from sbeam.model.mass_overlay import resolve_mass_case, MassCase` | `(bulk, massset_sid=None) -> MassCase(sid, label, scale, conm2s)`. Which CONM2s a mass case contains and its label. |

### 3.3 Run

| Name | Import | Signature | Returns |
|---|---|---|---|
| `run_sol101` | `from sbeam.solver.sol101 import run_sol101` | `(bulk, subcase)` | `Sol101Result` |
| `run_sol103` | `from sbeam.solver.sol103 import run_sol103` | `(bulk, subcase)` | `Sol103Result` |
| `build_aero_model` | `from sbeam.aero.aero_model import build_aero_model` | `(bulk, grid_index=None, mach=None)` | `AeroModel` — the VLM mesh, AIC and splines; built once per deck. |
| `AeroCache` | `from sbeam.solver.sol144 import AeroCache` | `(bulk, grid_index, seed=aero)`; `.get(mach)` | Mach-keyed store of `AeroModel`s so a multi-Mach deck builds each AIC once. Pass the same instance to every SOL 144 call. |
| `run_sol144_trim` | `from sbeam.solver.sol144 import run_sol144_trim` | `(bulk, subcase, aero, aero_cache=None)` | `Sol144TrimResult` |
| `run_sol144_diverg` | `from sbeam.solver.sol144 import run_sol144_diverg` | `(bulk, subcase, aero, aero_cache=None)` | `Sol144DivergResult` |
| `run_maneuver_qs` | `from sbeam.solver.maneuver_qs import run_maneuver_qs` | `(bulk, subcase, aero, aero_cache=None)` | `ManeuverResult` — direct l-set transient solver. |
| `run_maneuver_modal` | `from sbeam.solver.maneuver_modal import run_maneuver_modal` | `(bulk, subcase, aero, aero_cache=None, basis_cache=None)` | `ManeuverResult` — modal transient solver. |
| `ManeuverBasisCache` | `from sbeam.solver.maneuver_modal import ManeuverBasisCache` | `(bulk, aero)` | One free-free modal basis per job, shared across modal `MLOADS` subcases. |

A SOL 144 subcase is routed by its case-control requests, exactly as the CLI does it:
`mloads_sid` set → a maneuver solver (`bulk.mloads[sid].selects_modal` picks modal over
direct); else `diverg_sid` set without `trim_sid` → `run_sol144_diverg`; else
`run_sol144_trim`, followed by `run_sol144_diverg` if `diverg_sid` is also set. §4 shows
the loop. Solver guides: `03_static_analysis.md`, `04_modal_analysis.md`,
`05c_sol144_maneuver.md`.

### 3.4 Results

All in `sbeam.results.results` unless stated. They are plain dataclasses; every field is
commented at its definition, and the ones below are the ones consumers read.

| Class | Key fields |
|---|---|
| `Sol101Result` | `displacements` (n_dofs,), `reactions {gid: (6,)}`, `bar_forces {eid: BarForce}`, `bar_stresses {eid: BarStress}`, `rod_forces`, `rod_stresses`, `cbush_forces {eid: (6,)}` |
| `Sol103Result` | `frequencies_hz` (n_modes,), `mode_shapes` (n_dofs, n_modes), `eigenvalues`, `generalized_masses` |
| `Sol144TrimResult` | `trim_vars {label: value}`, `q`, `mach`, `displacements`, `bar_forces`, `bar_stresses`, `rigid_derivs` / `restrained_derivs` / `unrestrained_derivs {label: {coef: value}}`, `total_cl`, `total_cm`, `grid_loads`, `inertial_loads`, `applied_loads` (n_dofs, or None without a subcase `LOAD`; #6), `load_sid`, `net_loads` (n_dofs,), `monitor_loads {name: MonitorLoad}`, `section_loads {name: SectionCutResult}`, `massset_sid`, `massset_label`, `hinge_moments`, `q_div` |
| `Sol144DivergResult` | `mach_results: list[DivergMachResult(mach, roots: list[DivergRoot(q_div, v_div, mode_shape)])]` |
| `ManeuverResult` | `times` (n_out,), `steps: list[ManeuverStep]`, `crit_index`, `labels`, `massset_sid`, `massset_label`, `monitor_envelope`, `section_envelope` |
| `ManeuverStep` | `t`, `trim_vars`, `displacements`, `bar_forces`, `grid_loads`, `inertial_loads`, `net_loads`, `closure` (6,), `monitor_loads`, `section_loads` |
| `BarForce` | `m1_a, m2_a, m1_b, m2_b, v1, v2, axial, torque` — +x-face internal resultants, NASTRAN plane signs (`09_conventions.md` §9) |
| `BarStress` | `sa1–sa4, sb1–sb4, axial, sa_max, sa_min, sb_max, sb_min` |
| `RodForce`, `RodStress` | `axial, torque` / `axial, torsional` |
| `MonitorLoad` | `name, label, mtype, cid, ref` (3,), `totals` (6,), `aero`, `inertia`, `reaction` |
| `SectionCutResult`, `SectionCutStation` | per-`MONSECT` running loads: `name, comp, cid, axis, side`, `stations: list[SectionCutStation]`, each with `station`, `totals` (6,), `aero`, `inertia`, `reaction` |

### 3.5 Write

| Name | Import | Signature |
|---|---|---|
| `build_f06_sol101_text`, `build_f06_sol103_text`, `build_f06_sol144_text`, `build_f06_sol144_diverg_text`, `build_f06_sol144_maneuver_text` | `from sbeam.results.f06_writer import …` | `(case_control, bulk, result, subcase_id) -> str`, one f06 block per subcase; concatenate for a multi-subcase file as the CLI does. |
| `write_f06_sol101`, `write_f06_sol103`, `write_f06_sol144` | `from sbeam.results.f06_writer import …` | `(filepath, case_control, bulk, result, subcase_id=1) -> None`, single-subcase convenience wrappers. |
| `write_aero_load_cards`, `write_maneuver_load_cards` | `from sbeam.results.load_export import …` | `(filepath, bulk, results: dict[int, Sol144TrimResult]) -> None` |
| `write_monitor_csv`, `write_section_loads_csv` | `from sbeam.results.load_export import …` | `(filepath, results: dict[int, Sol144TrimResult]) -> None` |
| `write_maneuver_monitor_csv`, `write_maneuver_monitor_envelope_csv`, `write_maneuver_section_loads_csv`, `write_maneuver_section_envelope_csv` | `from sbeam.results.load_export import …` | `(filepath, results: dict[int, ManeuverResult]) -> None` |
| `write_maneuver_outputs` | `from sbeam.results.maneuver_output import write_maneuver_outputs` | `(stem, bulk, results: dict[int, ManeuverResult]) -> (mldprnt_path, qs_loads_path)` |

Every CSV and load-BDF column is specified in `10_export_schemas.md`; the f06 blocks in the
solver guides.

---

## 4. SOL 144: build once, run every subcase

The aero model is the expensive object, so it is built once and shared. This is
`sbeam/main.py`'s SOL 144 branch with the file writing removed:

```python
# example_sol144 — tests/docs/test_python_api_guide.py runs this on the flagship trim deck
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.maneuver_modal import ManeuverBasisCache, run_maneuver_modal
from sbeam.solver.maneuver_qs import run_maneuver_qs
from sbeam.solver.sol144 import AeroCache, run_sol144_diverg, run_sol144_trim

case_control, bulk = parse_bdf(deck_path)
grid_index = build_grid_index(bulk)
aero = build_aero_model(bulk, grid_index=grid_index)
cache = AeroCache(bulk, grid_index, seed=aero)
basis_cache = ManeuverBasisCache(bulk, aero)

trim, diverg, maneuver = {}, {}, {}
for sc in case_control.subcases:
    if sc.mloads_sid is not None:
        modal = bulk.mloads[sc.mloads_sid].selects_modal
        run = run_maneuver_modal if modal else run_maneuver_qs
        kwargs = {"basis_cache": basis_cache} if modal else {}
        maneuver[sc.subcase_id] = run(bulk, sc, aero, aero_cache=cache, **kwargs)
    elif sc.diverg_sid is not None and sc.trim_sid is None:
        diverg[sc.subcase_id] = run_sol144_diverg(bulk, sc, aero, aero_cache=cache)
    else:
        trim[sc.subcase_id] = run_sol144_trim(bulk, sc, aero, aero_cache=cache)
        if sc.diverg_sid is not None:
            diverg[sc.subcase_id] = run_sol144_diverg(bulk, sc, aero, aero_cache=cache)

for sid, r in trim.items():
    print(sid, r.massset_label, {k: round(v, 4) for k, v in r.trim_vars.items()})
```

`trim`, `diverg` and `maneuver` are the `{subcase_id: result}` dictionaries every writer in
§3.5 takes. A `MASSSET = sid` on a subcase changes only the mass-derived operators; the
stiffness, splines and `AeroCache` entries are reused across the sweep.

---

## 5. Running a subcase the deck does not contain

`SubcaseControl` is a dataclass, so a script can pose its own case against a parsed bulk:

```python
from sbeam.parser.case_control import SubcaseControl

sc = SubcaseControl(subcase_id=99, spc_sid=1, load_sid=10, displacement=True)
result = run_sol101(bulk, sc)
```

This is how the viewer runs a model uploaded without case control, and how a test harness
sweeps load sets. The IDs must exist in the bulk; a missing set raises `ValueError`
(`load_sid=None` is a valid zero-load case).

---

## 6. Changing this surface

Adding a public name: add its row here, and the gate will import it. Renaming or removing
one, or changing a listed signature or result field: `CHANGELOG.md` **Breaking changes**,
the version rule in `08_release_process.md` §1, and the gate updated in the same commit.
Internal reorganisation that leaves §3 true needs none of that, which is the point of
drawing the line.
