# MONSECT — Section-Cut Running Loads Design (Monitor Points Phase 2)

**Status:** ✅ **Implemented 2026-08-02.**  As-built record: this document is kept as the
design rationale; §4.4 and §5.2 were corrected during implementation (see §4.4a) and the
remaining sections describe what shipped.  The user-facing reference is
`docs/10_standard/02_card_reference.md` (`MONSECT`) and
`docs/10_standard/05c_sol144_maneuver.md` §"Section-Cut Running Loads"; the step record is
`docs/40_history/06_sol144_static_aeroelastic.md`.
**Backlog item:** P8 (Tier 1, ~2–3 d) — closed; transient follow-on is P8b.
**Target release:** `0.3.0`.
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-08-02
**Related:** Monitor Points Phase 1 (MON1–MON4) — `sbeam/results/monitor_points.py`,
`docs/10_standard/05c_sol144_maneuver.md` §"Monitor Points — Integrated Section Loads";
Step 53 balanced maneuver loads; Step 60 `MASSSET` mass cases.

This document is the design proposal for a non-standard sbeam BDF card, `MONSECT`, that
produces **per-station section-cut running loads** — the per-station shear / bending /
torque tables
along wing / HTP / VTP that a stress group consumes directly. It is Phase 2 of the monitor
point feature: Phase 1 delivered a *single* integrated resultant per named collection
(`MONPNT1` / `MONPNT3`); Phase 2 sweeps that same integration over a list of cut planes.

---

## 1. Motivation

### 1.1 The engineering problem

A SOL 144 trim currently hands the loads/stress interface two things: a `FORCE`/`MOMENT`
card deck of net (aero + inertial) grid loads (`<stem>.maneuver_loads.bdf`), and a small
number of whole-collection resultants (`<stem>.monitor_loads.csv`). Neither is the
artefact a stress engineer sizes a wing from. That artefact is the **running load table**:
at each of N stations along the span, the shear, bending moment and torque carried across
a cut plane, for every trim condition and every mass case.

Today a user producing that table has to export the net grid loads, load them into a
spreadsheet or a script, decide for each grid which side of each station it falls on, sum
the forces, transfer the moments to a reference on the elastic axis, and repeat the whole
thing per subcase and per `MASSSET`. It is exactly the kind of manual post-processing that
silently goes wrong when a grid is added to the model.

### 1.2 Why this is nearly free inside sbeam

The physics of a section cut is *free-body equilibrium*: the load carried across a cut is
the resultant of everything outboard of it. `MONPNT3` already computes precisely that
resultant over an arbitrary grid collection —

```
F = Σ_g f_g ,   M = Σ_g [ m_g + (r_g − r_ref) × f_g ]
```

— summing the trimmed aero (`grid_loads`), inertial (`inertial_loads`) and recovered
reaction contributions that `Sol144TrimResult` already carries. A section cut is that same
sum with (a) the collection filtered by a plane test and (b) the reference point placed on
the cut plane. No new solve, no new reduction, no new physics: `MONSECT` is a loop over
stations wrapped around the Phase 1 integrand.

### 1.3 Why no standard NASTRAN card fits cleanly

MSC Nastran expresses this with `MONPNT1` **plus** an externally generated family of
`AECOMP`/`SET1` collections — one collection per station, each listing the grids outboard
of that cut, typically emitted by a user's own script or by an OEM loads tool. ZAERO's
`MONPNT` family is the same shape. The station list itself is never declarative; it is
baked into hand-built set cards.

That is the failure mode Phase 1 already documents for `AELIST`
(`docs/10_standard/05c_sol144_maneuver.md`: *"An AELIST does not follow the mesh"*): a
literal ID list goes stale the moment the model gains a grid, silently, and returns a
confident slightly-wrong number. Writing thirty such collections by hand — one per wing
station — multiplies that trap by thirty.

`MONSECT` states the *intent* ("cut this component at these stations along this axis")
instead of enumerating the consequence, so the outboard set is recomputed from the current
model on every run and cannot go stale.

### 1.4 What this card delivers

- A declarative station list along a user-chosen axis of a CORD2R, cut from any existing
  `AECOMP` collection.
- Per station: the six-component resultant in the cut frame, split into aero / inertia /
  reaction contributions, about the **elastic-axis intercept** of the cut plane.
- Automatic coverage of every SOL 144 static trim subcase, including Step 53 balanced
  maneuvers and Step 60 `MASSSET` mass cases — the inertia column already tracks the
  active mass case, so payload sweeps produce their tables for free.
- f06 block, a machine-readable per-station CSV, and a spanwise viewer plot.
- Discretisation-aware behaviour: on-plane grids handled by a stated convention, and a
  warning when a station sits on top of a grid where the table would otherwise step.

---

## 2. Scope

### 2.1 In scope (Phase 2, target `0.3.0`)

- New `MONSECT` bulk-data card; reuses `AECOMP` for the collection.
- `SET1`-type `AECOMP` → aero + inertia + reaction (MON3 semantics).
  `AELIST`-type `AECOMP` → aero only (MON1 semantics, boxes filtered by force point).
- Station axis = any of the three CID axes; default the CID **y**-axis, matching sbeam's
  `Spline2` convention (`sbeam/model/aero.py:147` — the CID y-axis *is* the spline axis),
  so a `MONSECT` can point at the same CORD2R the wing's `SPLINE2` already uses.
- Cut-plane normal defaults to the station axis; optional explicit normal override.
- Reference point per station = intercept of the cut plane with the reference line
  `origin_CID + s·â` (the elastic axis when the CID is the spline CID).
- All SOL 144 static trim subcases, all mass cases.
- Output: f06 `SECTION CUT RUNNING LOADS` block, `<stem>.section_loads.csv`, viewer
  station table + spanwise plot with selectable components and contribution.

### 2.2 Out of scope (follow-ons, to be recorded in the backlog as P8b)

- **Transient (`MLOADS`) section cuts.** The integration is reusable verbatim at each
  output time, but the deliverable becomes a per-time-step table — a third dimension in
  the f06 block, the CSV schema and the viewer plot, plus a critical-station/critical-time
  envelope. That output design is a separate piece of work; P8b should scope the
  critical-sample cut first (one table at the MLDPRNT critical step, reusing this schema
  unchanged).
- **Envelope / max-min tables across subcases.** Once several trim cases and mass cases
  each produce a station table, the natural next artefact is a per-station envelope with
  the driving case ID. Deliberately deferred: it is a pure post-processing pass over the
  CSV and belongs with the envelope-sweep work (P9–P11).
- **HDF5 export.** Already a deferred follow-on for MON4; `MONSECT` inherits that status.
- **`AXES` component masking.** Phase 1 carries `AXES` through for annotation only and
  applies no masking; Phase 2 does not introduce masking either.
- **Stress recovery.** `MONSECT` reports section loads, not stresses; converting
  section loads to skin/spar stresses needs a section-property model sbeam does not have.

---

## 3. Card Definition

### 3.1 `MONSECT`

```
MONSECT, NAME,  LABEL,  COMP,  CID,  AXIS,  SIDE,  TOL
+,       STA1,  STA2,   STA3,  STA4, STA5,  STA6,  STA7,  STA8
+,       STA9,  ...
```

| Field   | Type  | Default | Description |
|---------|-------|---------|-------------|
| `NAME`  | str   | —       | Monitor name (≤ 8 chars). Must be unique across `MONPNT1`, `MONPNT3` **and** `MONSECT`. |
| `LABEL` | str   | blank   | Descriptive label, carried to output. |
| `COMP`  | str   | —       | `AECOMP` name. `SET1`-type ⇒ aero+inertia+reaction; `AELIST`-type ⇒ aero-only. |
| `CID`   | int   | —       | CORD2R (or 0) defining the cut frame. Station coordinates and reported components are in this frame. |
| `AXIS`  | int   | `2`     | Which CID axis is the station axis: 1 = x, 2 = y, 3 = z. Default 2 matches the `SPLINE2` spline-axis convention. |
| `SIDE`  | str   | `POS`   | `POS` integrates the part with station coordinate **greater** than the cut; `NEG` the lesser part. |
| `TOL`   | float | auto    | On-plane tolerance in model length units. Default `1e-6 × (STA_max − STA_min)`, floored at `1e-9`. |
| `STAi`  | float | —       | Station coordinates along `AXIS` in the `CID` frame. **Strictly increasing.** At least one required; continuation lines extend the list. |

### 3.2 Optional normal override

A general cut normal (the backlog's *"general normal as override"*) is declared on a
dedicated continuation, distinguished by the literal keyword in the first field so it
cannot be confused with station values:

```
+,       NORMAL, NX, NY, NZ
```

`(NX, NY, NZ)` is the cut-plane normal in the `CID` frame (normalised internally; need not
be a unit vector). Stations continue to be measured along `AXIS` on the reference line —
the cut plane through station `s` is the plane containing `origin + s·â` with normal `n̂`.
A normal with `|n̂ · â| < 0.1` is rejected: the plane is then near-parallel to the reference
line and either misses it or intercepts it at an ill-conditioned point.

### 3.3 Example — Cessna 210 flagship right wing

```
$ Cut frame: the same CORD2R the wing SPLINE2 uses (y-axis along the elastic axis).
CORD2R,  70,  0,  1.15, 0.0, 0.30,   1.15, 0.0, 1.30,   1.30, 1.0, 0.30
$
$ Grids of the right wing (structure + carry-through), as for a MONPNT3.
SET1,    701, 1001, 1002, 1003, 1004, 1005, 1006, 1007
+,       1008, 1009, 1010
AECOMP,  RWING, SET1, 701
$
$ Six stations from the side-of-body out to the tip.
MONSECT, SECRW, RIGHT WING RUNNING LOADS, RWING, 70, 2, POS
+,       0.30, 1.20, 2.10, 3.00, 3.90, 4.80
```

Reported at each station, in CID 70: `N` (axial, along the EA), `Vy`/`Vz` (in-plane and
vertical shear), `Mt` (torque about the EA), `My`/`Mz` (bending).

---

## 4. Semantics

### 4.1 The cut

Let `(P, R)` = `get_transform(CID, bulk.cord2rs)` (`assembly/coord_transform.py`), `â` = the
`AXIS` column of `R` (basic frame), and `n̂` = `â` unless a `NORMAL` override is present.

For a grid at basic position `r_g`, its **station coordinate** is `s_g = (r_g − P) · n̂`.
A grid is outboard of station `s` when, for `SIDE = POS`:

```
s_g > s + TOL
```

and correspondingly `s_g < s − TOL` for `SIDE = NEG`. For an `AELIST` collection the same
test is applied to `aero.boxes[k].force_point`, i.e. the point the box force is already
applied at for the MON1 integration.

### 4.2 The reference point

```
r_ref(s) = P + t·â ,   with t chosen so that (r_ref − P) · n̂ = s
         = P + (s / (â · n̂)) · â
```

With the default normal (`n̂ = â`) this collapses to `r_ref = P + s·â` — a point on the CID
axis line. When the CID is the wing's spline CID, that line **is** the elastic axis, so the
reported moments are the EA-referenced bending and torque a stress group expects. This also
stays correct on a swept wing, because the stations and the reference line share the same
axis.

### 4.3 The integrand

Identical to Phase 1, with the reference point moved per station:

- **`SET1` collection.** Sum the 6-DOF blocks of `grid_loads` (aero, splined), of
  `inertial_loads` (Step 53 inertia, zero on a plain trim) and of the recovered
  SPC/SUPORT reaction over the outboard grids, each as
  `F += f_g`, `M += m_g + (r_g − r_ref) × f_g`. Reported columns: `aero`, `inertia`,
  `reaction`, `totals = aero + inertia + reaction`.
- **`AELIST` collection.** `F += box_forces[k]`, `M += (force_point[k] − r_ref) × box_forces[k]`
  over the outboard boxes; `inertia` and `reaction` are zero.

The result is rotated into the `CID` frame (`R.T @ v_basic`, as `monitor_points._to_cp`).

### 4.4 Component labelling — **superseded, see §4.4a**

The original proposal named the six components cyclically from the station axis
(`N, Vy, Vz, Mt, My, Mz`, rotating with `AXIS`). **This was rejected during implementation**
and is recorded here only so the change is traceable.

### 4.4a Component labelling (as built)

Only two components need a *role* name: the force along the station axis is the axial load
`N`, and the moment about it is the torque `Mt`.  The other four keep the name of the CID
axis they act along or about.

| `AXIS` | Labelled order | Raw CID components |
|--------|----------------|--------------------|
| 1 (x)  | `N, Vy, Vz, Mt, My, Mz` | `Fx, Fy, Fz, Mx, My, Mz` |
| **2 (y, default)** | `N, Vx, Vz, Mt, Mx, Mz` | `Fy, Fx, Fz, My, Mx, Mz` |
| 3 (z)  | `N, Vx, Vy, Mt, Mx, My` | `Fz, Fx, Fy, Mz, Mx, My` |

**Why the cyclic scheme was wrong.**  At the default `AXIS = 2` it produced
`N=Fy  Vy=Fz  Vz=Fx  Mt=My  My=Mz  Mz=Mx` — that is, it labelled the *vertical* shear `Fz`
as "Vy" and the wing *bending* moment `Mx` as "Mz".  Both are inverted from what a loads
engineer reads, and from the backlog's own `{Vz, My, Mt}` phrasing.  A stress table whose
two most-used numbers are named after the wrong axes is worse than no labels at all.

The axis-named scheme has the property the cyclic one lacked: **every name is tied to an
axis**, so nothing depends on remembering a rotation.  For a spanwise wing cut it gives
`Vz` = vertical shear and `Mx` = wing bending, directly.  This *removes* the mislabelling
risk (§8.2 risk 4) rather than mitigating it; the f06 header still prints the mapping in
use, and the CSV carries both labelled and raw components.

### 4.5 Running-load derivatives

Each station carries the backward difference to its inboard neighbour,
`d_ds = (labelled(s_i) − labelled(s_{i−1})) / (s_i − s_{i−1})`, as a single 6-vector
(`None` at the first station) rather than three named scalars — the labelled component set
depends on `AXIS`, so naming the derivative fields would reintroduce the §4.4 problem.
This is the "running load" in the per-unit-span sense: a presentation convenience computed
from the same table, not an independent quantity.

### 4.6 Decisions that must be deliberate

1. **On-plane grids belong to the *inboard* side** — the test is strictly `s_g > s + TOL`.
   A grid load is a point load; a cut *at* a node should exclude it, so that the outboard
   free body's resultant equals the beam internal force at that node. This is what makes
   the CBAR cross-check (§6, V-SEC2) an exact identity rather than an approximate one.
   Any grid within `TOL` of a cut plane raises a `UserWarning` naming the grid and the
   station, because that is precisely where the table has a step and where a user's
   expectation and the convention can differ.

2. **No symmetry parity, ever.** This is the sharpest divergence from Phase 1 and must not
   be inherited by accident. `monitor_points._apply_symmetry` doubles the symmetric
   components of a half-model (`AEROS SYMXZ ≠ 0`) resultant to report the whole airplane,
   and requires the reference on the symmetry plane. Neither applies to a section cut: a
   wing cut on a half model is *already* the physical per-side load a stress engineer
   wants, its reference is deliberately off-centreline, and the antisymmetric-cancellation
   logic is meaningless there. `MONSECT` therefore fixes `parity = 1.0` unconditionally,
   and annotates the f06 block `HALF-MODEL (LOADS PER SIDE)` when `SYMXZ ≠ 0` so the
   reader knows which airplane they are looking at.

3. **Stations must be strictly increasing.** Duplicates and reversals are a hard parse
   error. Everything downstream — the CSV, the spanwise plot, the running-load differences,
   any future envelope — assumes a monotone table.

4. **An empty outboard set is a zero row, not an error.** A station outboard of every grid
   is a legitimate and useful closure check: it must return exactly zero.

5. **The stale-collection trap still applies.** `MONSECT` recomputes membership from the
   current model, so adding a grid to the wing automatically enters the cuts — *provided
   the grid is in the `SET1`*. The `AECOMP` itself is still a literal list. The
   documentation must repeat the Phase 1 warning in its `SET1` form: a `MONSECT` over a
   stale `SET1` is as wrong as a stale `AELIST`, just harder to notice because the table
   looks plausible.

---

## 5. Implementation Plan

### 5.1 File touches

| File | Change |
|------|--------|
| `sbeam/model/aero.py` | `@dataclass Monsect` (name, label, comp, cid, axis, side, tol, `stations: list[float]`, `normal: Optional[tuple[float,float,float]]`). |
| `sbeam/model/bulk_data.py` | `monsects: dict[str, Monsect]`. |
| `sbeam/parser/bdf_reader.py` | `_parse_monsect` with continuation handling (station list + the `NORMAL` keyword line); keyword registration beside `MONPNT1`/`MONPNT3` (~line 1429); cross-validation in the existing monitor block (~line 1555): `COMP` resolves to an `AECOMP`, `CID` exists as a CORD2R or is 0, `AXIS ∈ {1,2,3}`, `SIDE ∈ {POS,NEG}`, monotone stations, non-degenerate normal, name unique across all three monitor dicts. |
| `sbeam/results/monitor_points.py` | Promote `_monitor_frame` / `_to_cp` / `_grid_resultant` to public helpers (`to_cp`, `grid_resultant`) for reuse. **No behavioural change** — MON1/MON3 output stays byte-identical. |
| **`sbeam/results/section_cuts.py`** (new, ~200 lines) | `compute_section_cuts(bulk, aero, box_forces, grid_loads, inertial_loads, grid_index, reactions, massset_sid) -> dict[str, SectionCutResult]`. Precomputes each collection's member positions and station coordinates once per cut, then sweeps stations with a boolean mask — O(n_grids + n_stations · n_outboard), not a re-scan of the model per station. |
| `sbeam/results/results.py` | `@dataclass SectionCutStation` (station, `ref` basic (3,), `aero`/`inertia`/`reaction`/`totals` (6,) in CID frame, `n_members`, `d_ds` (6,)) and `@dataclass SectionCutResult` (name, label, comp, cid, axis, side, `component_labels`, `stations: list[SectionCutStation]`); `Sol144TrimResult.section_loads: Optional[dict[str, SectionCutResult]] = None`. |
| `sbeam/solver/sol144.py` (~1847–1870) | Widen the monitor guard to `bulk.monpnt1s or bulk.monpnt3s or bulk.monsects`, including the reaction-recovery trigger (a `SET1`-type `MONSECT` needs `reactions` exactly as `MONPNT3` does); call `compute_section_cuts` with the already-computed `grid_loads` / `inertial_loads` / `box_forces` / `reactions`; attach `section_loads=` to `Sol144TrimResult`. |
| `sbeam/results/f06_writer.py` | `_section_cut_block`, called from the same place as `_monitor_block` (~line 535), gated on `result.section_loads`. |
| `sbeam/results/load_export.py` | `write_section_loads_csv`. |
| `sbeam/main.py` (~113) | Write `<stem>.section_loads.csv` when any subcase has `section_loads`, beside the existing `.monitor_loads.csv`. |
| `sbeam/viewer/results_view.py` (~447) | "Section cuts" expander below the monitor table. |
| `sbeam/viewer/case_control_ui.py` (~110) | Add "section loads" to the SOL 144 outputs summary string when `MONSECT` cards are present. |

### 5.2 Output formats

**f06 block** — `SECTION CUT RUNNING LOADS`, one group per cut per subcase:

```
                          S E C T I O N   C U T   R U N N I N G   L O A D S

  MONSECT  SECRW    RIGHT WING RUNNING LOADS      COMP RWING (SET1)   CID 70   AXIS 2 (+Y)   SIDE POS
  COMPONENTS:  N=Fy  Vy=Fz  Vz=Fx  Mt=My  My=Mz  Mz=Mx      HALF-MODEL (LOADS PER SIDE)

    STATION      X-REF      Y-REF      Z-REF          N         VY         VZ         MT         MY         MZ
  ---------- ---------- ---------- ---------- ---------- ---------- ---------- ---------- ---------- ----------
    3.00E-01   1.15E+00   3.00E-01   3.00E-01   ...
```

**CSV** `<stem>.section_loads.csv`, one row per cut per station per subcase (as built):

```
case, massset, mass_case, name, label, comp, listtype, cid, axis, side, half_model,
station, x_ref, y_ref, z_ref,
comp_1..comp_6,            $ the labelled component NAMES for this cut's axis
c1..c6,                    $ labelled totals
Fx, Fy, Fz, Mx, My, Mz,    $ raw cid-frame components
c1_aero..c6_aero, c1_inertia..c6_inertia, c1_react..c6_react,
n_members, dc1_ds..dc6_ds
```

Writing the component *names* into every row (`comp_1..comp_6`) is what makes the file
self-describing: the labelled set depends on `AXIS`, so a consumer must never have to infer
it. The aero/inertia/reaction split is the section-cut analogue of the `Fz_*` breakdown that
Phase 1 documents as "the fastest way to debug a wrong sum", and the `massset` columns make
a payload sweep a single pivot in the consuming tool.

**Viewer** — per cut: a station table via `viewer/format_utils.py` (5 sig figs, consistent
with the rest of the results pane) and a Plotly spanwise figure with `Vz`, `My`, `Mt`
traces, aero / inertia / net selectable, and a subcase + mass-case multiselect so trim
conditions overlay on one axis.

### 5.3 Order of operations in `run_sol144`

Unchanged through the trim solve. After `net_loads` and `maneuver_closure` are formed and
the reactions recovered (the existing MON2/MON3 block), `compute_section_cuts` runs on the
same arrays. No matrix is factored, no spline is re-applied, nothing is re-reduced — the
cost is O(n_grids × n_stations) arithmetic.

### 5.4 Backward compatibility

- No `MONSECT` cards ⇒ `section_loads` is `None` ⇒ the f06 block is not emitted, no CSV is
  written, the viewer panel does not appear. Every existing deck's f06 must remain
  byte-identical; this is an explicit regression assertion, not an assumption.
- The `monitor_points.py` helper promotion is a rename only; MON1/MON3 numerics untouched.

---

## 6. Verification Cases

As built the gates live in four files (the unit-level ones run without a trim solve, so a
failure there is the integrand and nothing else):

| File | Gates |
|------|-------|
| `tests/results/test_section_cuts.py` | V-SEC1, V-SEC4, V-SEC8, V-SEC9, V-SEC10 + reference-point / POS+NEG / derivative checks |
| `tests/aero/test_section_cuts_sol144.py` | V-SEC2, V-SEC3, V-SEC5, V-SEC7 (HA144A) |
| `tests/aero/test_section_cuts_massset.py` | V-SEC6 (flagship, three payload cases) |
| `tests/parser/test_monsect.py` | P-SEC round-trip + rejections |
| `tests/results/test_section_cut_output.py` | f06 block + CSV |


| ID | Case | Gate |
|----|------|------|
| **V-SEC1** | Uniform-load cantilever, no aero, stations along the beam. | `V(s) = w(L−s)`, `M(s) = w(L−s)²/2` to machine precision. Pure summation — proves the plane test, the sign convention and the moment transfer with no trim in the loop. |
| **V-SEC2** | HA144A full-span, stations placed **at** structural nodes. | The outboard free-body resultant equals the CBAR end force/moment at that node (`Sol144TrimResult.bar_forces`, converted from element-local end-B components to the cut frame) to ~1e-8 relative. **The load-bearing gate**: free-body equilibrium ties the cut to an independently computed internal load. |
| **V-SEC3** | Cut inboard of every grid over the whole-aircraft `AECOMP`. | Equals the existing `MONPNT3` totals from `test_monitor_ha144a.py` (shared fixture) — Phase 2 degenerates to Phase 1. |
| **V-SEC4** | Station outboard of every member. | Exactly zero, all six components, `n_members = 0`. |
| **V-SEC5** | Step 53 balanced maneuver, whole-model cut. | Net (aero+inertia+reaction) resultant ≈ 0, reproducing `maneuver_closure` to its own tolerance. |
| **V-SEC6** | Flagship, two `MASSSET` cases (reuse `test_massset_sweep.py` fixture). | Wing-root `My` differs between cases while the `*_aero` columns are identical — the mass case enters only through the inertia column. |
| **V-SEC7** | `AELIST`-type `MONSECT` vs `SET1`-type on a collection with exclusive spline coupling. | Aero columns agree (force to machine precision, moment ~1e-6 relative), mirroring the Phase 1 MON1==MON3 argument. |
| **V-SEC8** | `NORMAL` override at 15° to the axis, vs an equivalent rotated CID with the default normal. | Same resultants to ~1e-10 — the override is a reparametrisation, not new physics. |
| **V-SEC9** | Half-model deck (`SYMXZ ≠ 0`). | Wing cut is **not** doubled; f06 carries the `HALF-MODEL` annotation. Guards decision §4.6.2 against a future refactor re-inheriting `_apply_symmetry`. |
| **V-SEC10** | Grid within `TOL` of a station. | `UserWarning` naming grid and station; the grid is counted inboard. |
| **P-SEC1–7** (`tests/parser/`) | Non-monotone / duplicate stations; unknown `COMP`; unknown `CID`; `AXIS = 4`; `SIDE = UP`; degenerate `NORMAL` (`|n̂·â| < 0.1`); name colliding with a `MONPNT1`. | Each raises `ValueError` with a message naming the card and the offending field. |

### 6.1 Non-regression requirement

The full existing suite passes unchanged, and a deck without `MONSECT` produces a
byte-identical f06 — asserted explicitly against the HA144A and flagship goldens.

### 6.2 Sample deck

`sample/cessna210_flagship_body.bdf` gains a right-wing `MONSECT` with 6 stations on the
existing wing spline CID, so the CI verification deck exercises the card end-to-end and the
shipped sample demonstrates the intended usage (including the CID-shared-with-`SPLINE2`
idiom).

---

## 7. Decisions and Open Questions

### 7.1 Settled (2026-08-02)

1. **Card name — `MONSECT`.** Reads as "monitor section", sorts beside the `MONPNT*`
   family, and collides with no real NASTRAN card.
2. **Default `AXIS` — 2 (CID y).** Chosen for consistency with sbeam's `SPLINE2`
   convention (`sbeam/model/aero.py:147`), so one CORD2R serves both cards and the common
   case needs no `AXIS` field. This supersedes the backlog entry's *"plane normal along the
   spline-axis x̂"* wording, which read as CID x; `AXIS` remains explicit in the card, so
   the choice sets only the default. Because a wrong default would produce a
   plausible-looking table cut the wrong way, the f06 header always prints the axis and the
   component mapping actually in use (§4.4).

### 7.2 Still open

3. **Whether `SIDE` should default by geometry** (integrate whichever side has fewer
   members) rather than to `POS`. Rejected in this draft: an implicit side makes the sign
   of every reported number depend on the mesh. Explicit `POS` default, documented.
4. **Auto-stationing** (`NSTA` = generate N evenly spaced stations between the collection's
   extremes) as a convenience field. Attractive for a first look at a model; deferred until
   the explicit list is proven, to keep Phase 2 at its estimate.

---

## 8. Risks & Effort

### 8.1 Effort (~2.5 d)

| Task | Estimate |
|------|----------|
| `Monsect` dataclass, parser + validation, parser tests, helper extraction | 0.5 d |
| `section_cuts.py`, result types, `sol144.py` wiring; V-SEC1/4 green | 1.0 d |
| f06 block, CSV writer, `main.py`; V-SEC2/3/5/6/7 green; sample deck | 0.5 d |
| Viewer table + spanwise plot | 0.5 d |
| Docs, backlog/history/CHANGELOG, full-suite regression | 0.5 d |

Independent of P9–P11 and of the Phase G0 modal steps — it touches only the
post-processing tail of `run_sol144`.

### 8.2 Top correctness risks

1. **Inheriting the parity logic** (§4.6.2). A copy-paste of the Phase 1 integrator would
   silently double every half-model wing cut. Mitigated by V-SEC9 and by *not* importing
   `_apply_symmetry` into the new module at all.
2. **On-plane ambiguity** (§4.6.1). A station coinciding with a grid changes the answer by
   that grid's whole load. Mitigated by the stated strict-inequality convention, the
   `TOL` warning (V-SEC10), and V-SEC2 which only closes if the convention is right.
3. **Moment reference drift.** Using the CID origin instead of the per-station intercept
   would produce a table that looks smooth and is wrong by `s × V`. Mitigated by V-SEC1,
   where the analytic `M(s)` is only recovered with the correct per-station reference.
4. **Component-label mapping** (§4.4a). Mislabelling a shear or a bending moment is
   invisible on a symmetric case and disastrous on a swept one. **This risk materialised
   during implementation** — the originally proposed cyclic scheme named the vertical shear
   and the wing bending moment after the wrong axes — and was closed by switching to
   axis-named components, so no rotation has to be remembered. The f06 header still prints
   the mapping in use and the CSV carries names, labelled values and raw components.
5. **Stale `SET1`** (§4.6.5). Not fully preventable at this layer; mitigated by
   documentation and by the existing DEF-M10 mass-coverage warning, which continues to fire
   on whole-aircraft `MONPNT3`s.

---

## 9. References

- **NASTRAN / ZAERO equivalents:** MSC.Nastran Aeroelastic Analysis User's Guide —
  `MONPNT1`/`MONPNT2`/`MONPNT3`, `AECOMP`, `AELIST`, `SET1`; ZAERO Theoretical Manual,
  monitor-point load recovery. Neither provides a declarative station sweep; both rely on
  externally generated per-station collections.
- **Mechanics:** Wright & Cooper, *Introduction to Aircraft Aeroelasticity and Loads*, 2nd
  ed., §15 (aircraft loads: shear/moment/torque distributions from a free-body cut);
  Lomax, *Structural Loads Analysis for Commercial Transport Aircraft*, §5 (running loads
  and the elastic-axis reference).
- **In-project precedents:**
  - `sbeam/results/monitor_points.py` — the Phase 1 integrand this design sweeps.
  - `sbeam/solver/sol144.py` — `grid_loads` / `inertial_loads` / `net_loads` /
    `maneuver_closure` / `recover_reactions`, all consumed unchanged.
  - `sbeam/assembly/coord_transform.py` — `get_transform(cid, cord2rs)` supplies `(P, R)`.
  - `docs/10_standard/05c_sol144_maneuver.md` — the Phase 1 documentation section this
    extends, including the "an AELIST does not follow the mesh" warning.

---

## 10. Acceptance Criteria

- V-SEC1–V-SEC10 and P-SEC pass at the stated tolerances. **Met: 31 new tests green.**
- The full existing suite passes unchanged. **Met: 1551 passed / 6 xfailed, no regressions.**
- A `MONSECT` referencing a missing `AECOMP`, `CID`, or a non-monotone station list raises
  `ValueError` at parse time, never produces a silently wrong table.
- Sample decks demonstrate the card and are exercised in CI. **Met:** `sample/ha144a_fullspan_sbeam.bdf` (`SECRW`) and `sample/cessna210_flagship_bulk.bdf` (`SECRW` + `SECRWA`), both reusing the wing's `SPLINE2` CID as the cut frame.
- `pytest --cov` shows ≥ 90 % coverage on `sbeam/results/section_cuts.py`. **Met: 92 %** (the uncovered lines are error branches — unknown SET1 grid, missing aero model, unmeshed AELIST box ID).
- Documentation updated per the project's Step Completion Requirement:
  - `docs/10_standard/05c_sol144_maneuver.md` — new "Section-Cut Running Loads (Phase 2)"
    section (cards, semantics, EA-intercept rule, no-parity decision, on-plane convention,
    outputs, validation).
  - `docs/10_standard/02_card_reference.md` — `MONSECT` field table.
  - `docs/10_standard/05_aeroelastics.md` — card table + validation-status rows.
  - `docs/10_standard/06_viewer.md` — the new results panel.
  - `CLAUDE.md` — `MONSECT` in the supported-cards table and the SOL 144 results bullet.
- `docs/30_future/00_backlog.md` — the P8 row, the P8 summary line and the
  "Monitor points Phase 2 (P8)" section **removed**; a new P8b item added for transient
  section cuts (§2.2).
- `docs/40_history/06_sol144_static_aeroelastic.md` — full step entry (Objective,
  Deliverables, Test/Acceptance, key decisions); contents list in
  `docs/40_history/00_completed_development.md` updated.
- `CHANGELOG.md` `[Unreleased]` lists `MONSECT` under `### Added`.
