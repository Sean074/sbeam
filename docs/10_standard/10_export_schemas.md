# Export Schemas — the CSV and load-BDF contract

**Authoritative single source for every file the solver writes besides the f06** (#31,
2026-10-24). The architecture boundary (`00_program_overview.md`, Architecture) makes these
files the seam between `sbeam/` and the post-processing toolchain, so their shape is a
public interface: a column rename, a dtype change or a reordering is a **breaking change**
under `08_release_process.md` §1, exactly like the f06 layout. The headers below are held
by `tests/results/test_export_schema.py`, which asserts the module constants in
`sbeam/results/load_export.py`, the first line of every written file, and that every
column named here is named in this guide.

Solver guides describe *what* each file contains (`05c_sol144_maneuver.md`); this guide
owns the *contract*: names, order, types, sentinels and ordering.

---

## 1. Files and when they are written

All files are written next to the input by `sbeam/main.py`, as `<stem>.<name>`.

| File | Writer (`sbeam/results/`) | Written when |
|------|---------------------------|--------------|
| `aero_loads.bdf` | `load_export.write_aero_load_cards` | any SOL 144 `TRIM` subcase |
| `maneuver_loads.bdf` | `load_export.write_maneuver_load_cards` | any `TRIM` subcase |
| `monitor_loads.csv` | `load_export.write_monitor_csv` | a `TRIM` subcase has `MONPNT1`/`MONPNT3` |
| `section_loads.csv` | `load_export.write_section_loads_csv` | a `TRIM` subcase has `MONSECT` |
| `mldprnt.txt` | `maneuver_output.write_maneuver_outputs` | any `MLOADS` subcase (fixed-width text, not a CSV; columns in `05c` §MLDPRNT) |
| `maneuver_qs_loads.bdf` | `maneuver_output.write_maneuver_outputs` | any `MLOADS` subcase |
| `maneuver_monitor_loads.csv`, `maneuver_monitor_envelope.csv` | `load_export.write_maneuver_monitor_csv`, `..._envelope_csv` | an `MLOADS` subcase has monitor points |
| `maneuver_section_loads.csv`, `maneuver_section_envelope.csv` | `load_export.write_maneuver_section_loads_csv`, `..._envelope_csv` | an `MLOADS` subcase has `MONSECT` |

The viewer's download buttons call the `build_*_text` twin of each maneuver writer, so a
downloaded file is byte-identical to the CLI's. SOL 101/103 write the f06 only.

---

## 2. Common CSV conventions

| Rule | Contract |
|------|----------|
| Encoding / dialect | `csv.writer` defaults: comma, `\n` line ends, no quoting unless a label needs it, UTF-8 |
| Header | Exactly one header row, the lists in §3; no comment lines, no units row |
| **Identity block** | Every file starts `case, massset, mass_case` (static) or `case, mloads, massset, mass_case` (transient). `case` is the subcase id, `mloads` the `MLOADS` SID |
| **`massset`** | **Always an integer.** `0` = the subcase selects no `MASSSET` (baseline); otherwise the `MASSSET` SID. Never empty, so the column keeps one dtype whether or not a run (or a concatenation of runs) contains a baseline case. Constant `BASELINE_MASSSET` in `load_export.py` |
| `mass_case` | The mass-case label: `BASELINE` for `massset = 0`, else the `MASSSET` label |
| Reals | `%.6E` (e.g. `-1.234567E+03`); the `parity` column is `%g` |
| Integers | ids, `cid`, `axes`, `sample`, `n_members`, `n_samples`, `comp_index`, `*_sample` |
| Flags | `whole_airplane`, `half_model`, `critical` are `0` / `1` |
| Empty cell | Only `dc*_ds` at the first station of a cut (no backward difference exists). Never `nan` |
| Row order | Cases in **case-control order** (not sorted, not necessarily contiguous); within a case monitors / cuts sorted by name; stations in `MONSECT` order; samples ascending (`sample` is **1-based**, matching the f06 `SAMPLE` column); envelope rows per name then per component. Consumers must key on the identity columns, never on row position |
| Empty cases | A subcase with nothing to report contributes no rows (the file may hold only the header) |

---

## 3. CSV headers

### 3.1 `monitor_loads.csv` — `_MONITOR_CSV_HEADER`

`case`, `massset`, `mass_case`, `name`, `type`, `label`, `axes`, `cid`, `x_ref`, `y_ref`,
`z_ref`, `Fx`, `Fy`, `Fz`, `Mx`, `My`, `Mz`, `Fz_aero`, `Fz_inertia`, `Fz_react`,
`Fz_applied`, `parity`, `whole_airplane`

One row per monitor per `TRIM` subcase. `type` is `MONPNT1` / `MONPNT3`; `Fx..Mz` are the
six totals in the monitor's `cid` frame about (`x_ref`, `y_ref`, `z_ref`); `Fz_*` is the
diagnostic split (`MONPNT1` reports `0.0` for inertia, reaction and applied; `Fz_applied`
is the subcase's applied `LOAD` set, `0.0` when the subcase selected none — #6,
2026-10-24); `parity` is the half-model factor applied and `whole_airplane` whether it was
applied. Physics:
`05c_sol144_maneuver.md` "Output (MON4)".

### 3.2 `section_loads.csv` — `_SECTION_LOADS_CSV_HEADER`

`case`, `massset`, `mass_case`, then the shared **section-cut block**
`_SECTION_CUT_COLUMNS`:

`name`, `label`, `comp`, `listtype`, `cid`, `axis`, `side`, `half_model`, `station`,
`x_ref`, `y_ref`, `z_ref`,
`comp_1`, `comp_2`, `comp_3`, `comp_4`, `comp_5`, `comp_6`,
`c1`, `c2`, `c3`, `c4`, `c5`, `c6`,
`Fx`, `Fy`, `Fz`, `Mx`, `My`, `Mz`,
`c1_aero`, `c2_aero`, `c3_aero`, `c4_aero`, `c5_aero`, `c6_aero`,
`c1_inertia`, `c2_inertia`, `c3_inertia`, `c4_inertia`, `c5_inertia`, `c6_inertia`,
`c1_react`, `c2_react`, `c3_react`, `c4_react`, `c5_react`, `c6_react`,
`c1_applied`, `c2_applied`, `c3_applied`, `c4_applied`, `c5_applied`, `c6_applied`,
`n_members`, `dc1_ds`, `dc2_ds`, `dc3_ds`, `dc4_ds`, `dc5_ds`, `dc6_ds`

One row per cut per station per subcase. `comp_1..comp_6` name the labelled components
(`N`, `Vy`, `Mt`, … depending on `axis`) that `c1..c6` carry; `Fx..Mz` are the same loads
in the raw `cid` frame; the `_aero/_inertia/_react/_applied` blocks split `c1..c6`
(`_applied` is the subcase's applied `LOAD` set, `0.0` when none was selected and on every
`AELIST` cut — #6, 2026-10-24); `dc*_ds` is the backward running-load difference per unit
station. Physics: `05c` "Output" (MONSECT).

### 3.3 `maneuver_section_loads.csv` — `_MANEUVER_SECTION_CSV_HEADER`

`case`, `mloads`, `massset`, `mass_case`, `sample`, `time`, `critical`, then
`_SECTION_CUT_COLUMNS` verbatim, then `c1_elastic`, `c2_elastic`, `c3_elastic`,
`c4_elastic`, `c5_elastic`, `c6_elastic`, `c1_damping`, `c2_damping`, `c3_damping`,
`c4_damping`, `c5_damping`, `c6_damping`

One row per cut per station per output sample. A reader of `section_loads.csv` reads this
file: same names, same order, with the sample identity in front and the two transient
contributions behind (the `_applied` block is carried and is always `0.0`: an `MLOADS`
subcase cannot select a `LOAD`, #6). `critical = 1` marks the run's critical sample (DEF-M5).

### 3.4 `maneuver_monitor_loads.csv` — `_MANEUVER_MONITOR_CSV_HEADER`

`case`, `mloads`, `massset`, `mass_case`, `sample`, `time`, `critical`, then the static
monitor block (`name` … `whole_airplane`, §3.1 without its identity), then `Fz_elastic`,
`Fz_damping`, then the full six-component split of all five sources:
`aero_Fx`, `aero_Fy`, `aero_Fz`, `aero_Mx`, `aero_My`, `aero_Mz`,
`inertia_Fx`, `inertia_Fy`, `inertia_Fz`, `inertia_Mx`, `inertia_My`, `inertia_Mz`,
`elastic_Fx`, `elastic_Fy`, `elastic_Fz`, `elastic_Mx`, `elastic_My`, `elastic_Mz`,
`damping_Fx`, `damping_Fy`, `damping_Fz`, `damping_Mx`, `damping_My`, `damping_Mz`,
`react_Fx`, `react_Fy`, `react_Fz`, `react_Mx`, `react_My`, `react_Mz`

Source-first names (`aero_Fx`) cannot collide with the static diagnostics (`Fz_aero`).

### 3.5 `maneuver_monitor_envelope.csv` — `_MANEUVER_MONITOR_ENVELOPE_HEADER`

`case`, `mloads`, `massset`, `mass_case`, `name`, `type`, `label`, `axes`, `cid`,
`whole_airplane`, `n_samples`, `critical_sample`, `comp_index`, `comp_name`, `max`,
`max_sample`, `max_time`, `min`, `min_sample`, `min_time`, `absmax`

One row per monitor per component (`comp_index` 1–6, `comp_name` `Fx` … `Mz`). `max_sample`
/ `min_sample` are the **driving** samples; `critical_sample` is carried beside them so a
consumer sees when they differ.

### 3.6 `maneuver_section_envelope.csv` — `_MANEUVER_SECTION_ENVELOPE_HEADER`

`case`, `mloads`, `massset`, `mass_case`, `name`, `label`, `comp`, `listtype`, `cid`,
`axis`, `side`, `half_model`, `n_samples`, `critical_sample`, `station`, `comp_index`,
`comp_name`, `max`, `max_sample`, `max_time`, `min`, `min_sample`, `min_time`, `absmax`

One row per cut per station per labelled component (`comp_name` is the station-axis
label, e.g. `Mt`).

---

## 4. Load BDFs

All three files are comma free-field bulk-data fragments: one block per subcase, blocks
separated by a blank line, each block a fixed comment header followed by
`emit_force_moment_cards` output.

| Rule | Contract |
|------|----------|
| Cards | `FORCE, SID, GID, 0, 1.0, Fx, Fy, Fz` and `MOMENT, SID, GID, 0, 1.0, Mx, My, Mz`; `SID` = subcase id (the `sid=` argument); CID `0`; unit scale factor so the components carry the load |
| Grid order | Ascending GID; a card is omitted when all three components are below `1e-9` |
| Reals | `parser/bdf_field.fmt_real8` — fits the NASTRAN 8-character field (DEF-M6; precision note in `05c` "Field format") |
| Comment header | Exactly four `$` lines for the trim exports, four for the MLOADS export (below). Line 4 is **always** `$ MASSSET=<int> (<label>)` — `$ MASSSET=0 (BASELINE)` for a baseline subcase — so a reader can key the block to the CSV identity without special-casing the baseline |

```
$ SOL 144 trimmed aerodynamic flight loads — subcase <case>, SID <sid>          (aero_loads.bdf)
$ TRIM=<trim_sid>  Q=<q>  MACH=<mach>  CZ=<total_cl:.6f>
$ FORCE/MOMENT set sums to the total trimmed lift/moment (plain trim).
$ MASSSET=<massset> (<mass_case>)  MASS=<total mass>

$ SOL 144 balanced maneuver loads (aero + inertia relief) — subcase <case>, SID <sid>   (maneuver_loads.bdf)
$ TRIM=<trim_sid>  Q=<q>  MACH=<mach>  CZ=<total_cl:.6f>
$ FORCE/MOMENT set is the net (aero + inertial) maneuver load for stress (Step 53).
$ MASSSET=<massset> (<mass_case>)  MASS=<total mass>

$ Phase G0 critical maneuver loads (aero + inertia + elastic inertia + damping) — subcase <case>, SID <sid>   (maneuver_qs_loads.bdf)
$ MLOADS=<mloads>  IC TRIM=<trim_sid>  Q=<q>  MACH=<mach>  t=<time>
$ Full applied load at the peak |net grid force| sample (<critical_sample> of <n_samples>).
$ MASSSET=<massset> (<mass_case>)
```

`massset_comment()` in `load_export.py` is the single source of line 4.

---

## 5. Reserved: element-force CSV (not yet written)

No element-force export exists (CBAR or rod); forces and stresses are in the f06 and the
viewer only. The schema is fixed here so the first consumer (#36, the per-case applied-loads
delivery to stress) does not have to invent it, and so the rod deferral from #38 has a home.
It is **not built** until that consumer exists (CLAUDE.md rule 5).

`<stem>.element_forces.csv`, one row per element per `TRIM` subcase (and per SOL 101
subcase when the static path adopts it):

`case`, `massset`, `mass_case`, `eid`, `type`, `m1_a`, `m2_a`, `m1_b`, `m2_b`, `v1`, `v2`,
`axial`, `torque`, `axial_stress`, `torsional_stress`

- `type` is `CBAR`, `CROD` or `CONROD`. `m1_a` … `v2` come from `BarForce` (MSC plane
  signs, +x-face internal resultants, `09_conventions.md` §9) and are **empty** for rods;
  `axial_stress` = `P/A` and `torsional_stress` = `T·C/J` come from `RodStress` and are
  empty for CBARs (whose stresses stay in the f06 `STRESSES IN BAR ELEMENTS` block).
- Source: `sbeam/solver/element_recovery.py::recover_line_elements`, element order as
  `iter_line_elements` (CBARs, then CRODs, then CONRODs, deck order).

---

## 6. Changing a schema

1. Edit the header constant in `load_export.py` and the matching table here in the same
   commit; `tests/results/test_export_schema.py` fails until both agree.
2. Record the change under **Breaking changes** in `CHANGELOG.md` (pre-1.0: ships in the
   next MINOR; from 1.0.0: MAJOR — `08_release_process.md` §1).
3. Adding a column at the **end** of a file is still a schema change (consumers that
   assert the exact header break) and is recorded the same way.
