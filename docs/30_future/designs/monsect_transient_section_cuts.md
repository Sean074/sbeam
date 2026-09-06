# MONSECT on Transient Maneuvers — Design (P8b / Step 68)

> **STATUS: BUILT 2026-08-02.** The step record with as-built detail and measured results
> is `docs/40_history/07_maneuver_transient.md` (Step 68); the user-facing reference is
> `docs/10_standard/05c_sol144_maneuver.md`. This document is kept as the design rationale.
> **Deviations from the design as written**, recorded rather than edited away:
>
> * `evaluate_section_cut` takes explicit `elastic_inertial_loads=` / `damping_loads=`
>   keywords rather than the generic `extra=[(name, vector)]` list of §4.1. Two typed
>   fields on `SectionCutStation` beat a name-keyed dict for two known contributions.
> * A defect surfaced during V-TSEC5 that the design had not anticipated: the reaction must
>   be recovered against the **full** applied load (`net_loads + elastic + damping`), not
>   `net_loads`, since `R = K·u − f_applied`. Fixed — but **no sample deck exercises it**
>   (it only differs when a constrained grid carries mass, and HA144A's SPC/SUPORT grid is
>   massless), so it is written correct-by-construction rather than gated. Logged in the
>   backlog.
> * V-TSEC5 as designed ("cut equals `step.closure` ≈ 0") was wrong for the direct solver:
>   under prescribed-rigid integration the closure is *legitimately* non-zero during a
>   maneuver and the imbalance is reacted at the SUPORT. The gate became "a cut over the
>   entire model, reaction included, closes" — stronger, and it also required building a
>   collection the deck does not have, since `AECOMP ALLGRID` omits the SUPORT grid.
> * Effort ran ~3 d as re-estimated in §8, against the backlog's ~2 d.

**Backlog item:** P8b (Tier 1) — the transient (`MLOADS`) follow-on to Monitor Phase 2.
**Predecessor design:** `designs/monsect_section_cuts.md` (P8, closed 2026-08-02, static only)
— §2.2 of that document records this work as its declared out-of-scope follow-on.
**Step number:** **68** (64–66 used; 67 is reserved by the backlog for the Tier 4 yaw-rate
wing term).
**Revised effort:** **~2.5–3 d**, not the backlog's ~2 d. See §8 — the backlog estimate
assumed "the integrand is reusable verbatim", which is true of the *integrand* but not of
its *inputs*: a transient section cut needs an elastic-inertia load column that no sbeam
result object carries today (§4.3). That term is the technical core of this step, not the
output plumbing.

---

## 1. Motivation

### 1.1 What is missing

A stress group sizing a wing from a maneuver does not size it from the trimmed 1g
condition — it sizes it from the worst instant of the maneuver, and it needs the running
loads (shear / bending / torque versus span station) *at that instant*, plus the envelope
over the whole time history so it knows no other instant is worse at any other station.

Today sbeam delivers:

| | static SOL 144 trim | transient `MLOADS` maneuver |
|---|---|---|
| Integrated monitor loads (`MONPNT1/3`) | ✅ | ❌ |
| Section-cut running loads (`MONSECT`) | ✅ f06 block + CSV + viewer | ❌ |
| Net grid loads for stress | ✅ `maneuver_loads.bdf` | ✅ critical sample only |
| CBAR end forces | ✅ | ✅ critical sample (f06), all samples (in memory) |

So the transient solver already computes the worst instant and exports its grid loads, but
the loads engineer must re-derive running loads from those cards by hand. Closing that
gap is the entire content of P8b.

### 1.2 Why the static integrand carries over — and where it does not

`results/section_cuts.py` is a free-body sum over members outboard of a plane. Nothing in
it is trim-specific: it consumes `box_forces`, `grid_loads`, `inertial_loads` and
`reactions` and returns a per-station table. Every one of those exists per output sample
inside `recover_step` (`solver/maneuver_qs.py:177`) — three of them are already stored on
`ManeuverStep`.

The one that does **not** carry over is the inertia column. `ManeuverStep.inertial_loads`
is `M_ax_g @ delta_basic` — the **rigid-body** d'Alembert load only. On a static balanced
trim that is the whole inertia, because the structure is not accelerating in the elastic
sense. On a dynamic sample it is not: the elastic acceleration field `ü_e` produces a real
distributed inertia load `M·ü_e`, and a free body of the outboard wing must include it.

This is not caught by any existing gate, because the existing gates are *global*:

- The Step 63 free-flight closure is ≈ 0 *despite* the missing term — mean-axis
  orthogonality makes the rigid-row resultant of `M·Φ_e ξ̈_e` exactly zero. A global
  resultant cannot see a term whose global resultant is zero by construction.
- A section cut is a **local** resultant. It sees it directly.

Hence §4.3: the step gains an elastic-inertia (and modal-damping) load column, and the
gate that proves it is right is the free-body/CBAR equilibrium check (V-TSEC3), which
fails today on any sample with meaningful elastic acceleration and passes after.

---

## 2. Scope

### 2.1 In scope

**Increment 1 — the critical sample (§5.1, ~1.5 d incl. the elastic-inertia term)**

- Elastic-inertia + modal-damping load recovery per output sample, for **both** transient
  solvers (`maneuver_qs` direct l-set, `maneuver_modal` free-flight).
- `MONSECT` tables evaluated at every output sample; the critical sample surfaced in the
  f06 using the static block format unchanged.
- `<stem>.maneuver_section_loads.csv` written with the **final** schema (sample/time
  columns present from day one — increment 1 writes only the critical row-set).
- Viewer: section-cut station table at the sample the existing sample-slider selects.

**Increment 2 — full history + envelope (§5.2, ~1–1.5 d)**

- Full per-sample rows in `maneuver_section_loads.csv`.
- Per-station / per-component **envelope** (max, min, driving sample + time) within a
  subcase → new f06 `SECTION CUT ENVELOPE` block, `<stem>.maneuver_section_envelope.csv`,
  and a viewer envelope table + band overlay on the station plot.
- Viewer time-history plot: pick cut × station × component → load versus time, with the
  critical-sample marker.

### 2.2 Out of scope (record as follow-ons if wanted)

- **Cross-subcase / cross-mass-case envelopes.** The envelope here is over *samples within
  one subcase*. Enveloping across subcases and `MASSSET` cases is a pure pivot over the
  CSV (the schema carries `case` and `massset` columns precisely so it is one groupby) and
  belongs with the sweep post-processing, alongside the identical static gap.
- **`MONPNT1`/`MONPNT3` on transient.** Same enabling work (the per-sample integrand
  inputs) but a separate output surface. Cheap once this lands (~0.5 d); deliberately not
  bundled so this step has one output design to get right. Log as **P8c**.
- **Changing `net_loads` / `closure` / the critical-sample metric.** The elastic-inertia
  term is added as a *separate* contribution and is **not** folded into `net_loads`.
  Folding it in would change the exported `maneuver_qs_loads.bdf` cards, the closure
  diagnostic and the DEF-M5 severity metric all at once — a much larger and separately
  arguable change. See §7.2 (open question O1). **Superseded 2026-09-05:** issue #3 made
  exactly that change — `net_loads` is now the full applied load
  ([`transient_net_loads_elastic_inertia.md`](transient_net_loads_elastic_inertia.md)).
- **HDF5 export, `AXES` masking, stress recovery.** Inherited exclusions from the P8
  design; unchanged.
- **New card fields.** No `MLOADS`/`MLDPRNT` field is added; the presence of `MONSECT`
  cards in a deck with an `MLOADS` subcase is the request, exactly as for static trim.

---

## 3. Semantics

Everything in `designs/monsect_section_cuts.md` §4 stands unchanged and is not restated:
the strictly-`s > station` inboard convention, the reference point on the cut plane, the
`N/V*/Mt/M*` component labelling from the station axis, and — emphatically — **no
symmetry parity, ever**. A transient cut is the same free body at a different instant.

Three semantics are new to this step.

### 3.1 The transient integrand

Per output sample, the cut's total is

```
totals(t) = aero(t) + inertia_rigid(t) + inertia_elastic(t) + damping(t) + reaction(t)
```

where the first, second and last are the existing static columns evaluated at `t`, and

```
inertia_elastic(t) = M_gg · ü_g,elastic(t)          (§4.3)
damping(t)         = M_gg · (2ζω · u̇_g,elastic(t))  (modal damping, ζ ≠ 0 only)
```

The damping term is included because when `MLOADS ZETA ≠ 0` the modal solver applies
`C = M Φ (2ζω) Φᵀ M`-equivalent damping in the h-set, and that force is genuinely carried
across a cut plane. It is separated from the inertia column in the CSV so a user can see
it is small (or switch it off by running ζ = 0) rather than wondering where the residual
went.

Sign convention: the two new columns follow whatever sign makes the **all-members cut
equal `step.closure`** (V-TSEC5) — i.e. the same d'Alembert sense as the existing
`inertial_loads = M_ax_g @ delta_basic`. This is fixed by a gate, not by inspection;
`build_inertial_cols` returns `−M_gg·Φ_r`, so the expected form is `−M_gg·ü` and the gate
confirms it.

### 3.2 Critical sample vs critical station

Two different "criticals" coexist and must be labelled as such:

- **Critical sample** — `result.crit_index`, selected by `peak_grid_force` (DEF-M5). One
  per subcase, unchanged by this step. It selects the f06 detail table and the exported
  load cards.
- **Driving sample** — per station, per component, from the envelope. Generally *not* the
  critical sample: outboard bending can peak at a different instant than the peak grid
  force.

The f06 envelope block prints the driving sample for each entry precisely so nobody
assumes the two are the same. The critical-sample metric is **not** redefined to be
section-cut-based — DEF-M5's "one metric, one numbering" ruling stands.

### 3.3 Reactions in a transient run

Identical treatment to `run_sol144_trim` (`solver/sol144.py:1922-1936`): the constrained
set is the subcase `SPC` DOFs plus every `SUPORT` DOF, and `recover_reactions(bulk, u_g,
constrained, K_gg, grid_index, net_loads)` supplies the reaction column. Both transient
solvers hold the r-set at the mean axis during recovery (`u_r = 0`), so a `SUPORT` grid
carries a reaction in exactly the sense the static path already reports; for the Step 63
free-flight solver it is the discrete mean-axis residual and is ≈ 0, which V-TSEC5 asserts.

---

## 4. Implementation

### 4.1 Two-phase section-cut API (the enabling refactor)

`compute_section_cut` currently re-resolves the AECOMP collection, the CID transform, the
station coordinates, the tolerance and the on-plane warning **on every call**. Calling it
once per output sample would re-do all of that thousands of times and would emit the
on-plane `UserWarning` once per sample — unusable.

Split it, in `results/section_cuts.py`:

```python
@dataclass(frozen=True)
class SectionCutPlan:
    """Everything about a MONSECT cut that does not depend on the load state."""
    cut: Monsect
    listtype: str                 # 'SET1' | 'AELIST'
    member_ids: list[int]         # grid IDs or global box indices k
    rows: FloatArray              # (n,) 6*grid_index rows — SET1 only
    pos: FloatArray               # (n, 3) member positions, basic
    R: FloatArray                 # (3, 3) cid rotation
    masks: list[FloatArray]       # per station, (n,) bool — outboard members
    refs:  FloatArray             # (n_station, 3) reference points, basic
    comp_map: tuple[int, ...]
    half_model: bool
    normal: Optional[FloatArray]

def prepare_section_cuts(bulk, aero, grid_index) -> dict[str, SectionCutPlan]:
    """Resolve geometry + masks once; emit the on-plane warnings once."""

def evaluate_section_cut(plan, box_forces, grid_loads, inertial_loads,
                         grid_index, reactions=None, extra=None) -> SectionCutResult:
    """Masked sums only — no geometry, no warnings.  `extra` is an ordered
    list of (name, g-set vector) contributions folded into `totals` and
    reported separately (the elastic-inertia and damping columns)."""

def compute_section_cuts(...) -> dict[str, SectionCutResult]:
    """Unchanged public signature = prepare + evaluate.  Static path keeps calling this."""
```

Non-negotiable: the static path's numbers must be **bit-identical** after the split
(V-TSEC9). Keep `compute_section_cuts` as the static entry point rather than rewriting
`run_sol144_trim`'s call site, so the refactor is provably neutral.

Per-sample cost after the split is `n_cuts × n_stations` masked sums over the member
arrays — for the flagship deck (4 cuts × 4 stations) it is negligible against the aero
evaluation already in `recover_step`.

### 4.2 Result model additions (`results/results.py`)

```python
@dataclass
class SectionCutStation:
    ...                                     # existing fields unchanged
    elastic_inertia: Optional[FloatArray] = None   # (6,) M·ü_e contribution
    damping: Optional[FloatArray] = None           # (6,) modal-damping contribution

@dataclass
class ManeuverStep:
    ...
    elastic_inertial_loads: Optional[FloatArray] = None  # (n_dofs,) g-set, M·ü_e
    damping_loads: Optional[FloatArray] = None           # (n_dofs,) g-set, ζ ≠ 0 only
    section_loads: Optional[dict[str, SectionCutResult]] = None

@dataclass
class SectionCutEnvelopeEntry:
    station: float
    comp: int                       # 0..5, labelled-component index
    max_value: float; max_sample: int; max_time: float
    min_value: float; min_sample: int; min_time: float

@dataclass
class SectionCutEnvelope:
    name: str; label: str; cid: int; axis: int; side: str
    comp_map: tuple[int, ...]; half_model: bool
    entries: list[SectionCutEnvelopeEntry]

@dataclass
class ManeuverResult:
    ...
    section_envelope: Optional[dict[str, SectionCutEnvelope]] = None
```

New fields are all `Optional` with `None` defaults — decks without `MONSECT`, and the
existing tests that construct `ManeuverStep` positionally, are untouched.

Memory: a 2000-sample run with 4 cuts × 10 stations × 6 contributions × 6 components is
~2.9 M floats ≈ 23 MB. Acceptable, documented in the module docstring, and bounded by
stations rather than by boxes or grids (which is why the plan stores the *result*, not the
per-sample `box_forces`).

### 4.3 Elastic-inertia recovery — per solver

The two solvers reach `ü_g,elastic` differently. Both must build it in the **g-set**
directly (`M_gg @ ü_g`), not in the a-set: mapping a reduced force back to g is not
well-defined through RBE3, whereas `u_g = T u_a` maps displacements/accelerations forward
cleanly. `M_gg` is already assembled in `modal_basis` (it is passed to
`build_inertial_cols` as `M_gg=M_gg`); retain a handle on `AsetOperators` rather than
re-assembling.

**Modal solver (`maneuver_modal._emit`)** — the pieces are already computed for the
mode-acceleration recovery at `solver/maneuver_modal.py:487-491`:

```python
f_inert = ops_a.M_aa @ (phi_e @ daxi_e)      # today: a-set, used only for u_l recovery
f_damp  = ops_a.M_aa @ (phi_e @ (c_rate * dvxi_e))
```

Replace with the g-set equivalents `M_gg @ expand_to_g(phi_e @ daxi_e)` and likewise for
the damping, then take the l-rows for the existing recovery **and** hand the full g-set
vectors to `recover_step`. One expression, two consumers — no second definition of the
same force (the DEF-M3 "one mass model" principle).

Note the mode-acceleration path (`recovery == "displacement"`) does not form these; under
that mode the elastic inertia must still be built from `phi_e @ daxi_e`, which is
available either way. Do not let the recovery-mode switch silently change the load.

**Direct solver (`maneuver_qs`)** — Newmark keeps `a_l` in the integrator loop but
`recover_step` is only handed `u_l`. Thread `a_l` (and `v_l` when α-damping is active)
through the same `_emit` path, scatter to the a-set with `r`-rows zero, `expand_to_g`,
multiply by `M_gg`. Same code path in `recover_step`; the solvers differ only in how the
acceleration field is produced.

`recover_step` gains parameters `accel_g=None, damp_g=None, cut_plans=None,
reactions_fn=None` — all optional, so the direct solver's existing behaviour with no
`MONSECT` cards is byte-identical.

### 4.4 Order of operations in each solver

1. Before the time loop: `cut_plans = prepare_section_cuts(bulk, aero, grid_index)` if
   `bulk.monsects` — geometry and warnings once, per subcase.
2. Also before the loop: resolve the constrained DOF list (SPC + SUPORT) once and keep
   `K_gg` for `recover_reactions`; skip entirely when no `SET1`-backed cut and no
   reaction consumer exists (mirrors `needs_reactions` at `sol144.py:1922`).
3. Inside `_emit`, after the existing `net_loads`: build `elastic_inertial_loads`,
   `damping_loads`, `reactions`, then
   `evaluate_section_cut(plan, box_forces_t, grid_loads, inertial_loads, grid_index,
   reactions, extra=[("elastic_inertia", ...), ("damping", ...)])` per cut.
   `box_forces_t` = `(ops.q * f_box_vec).reshape(n_box, 3)` — already computed at
   `maneuver_qs.py:212`, currently discarded.
4. After the loop (increment 2): `build_section_envelope(result)` reducing over samples.

### 4.5 File touches

| File | Change | Increment |
|---|---|---|
| `sbeam/results/section_cuts.py` | `SectionCutPlan`, `prepare_section_cuts`, `evaluate_section_cut`, `extra` contributions; `compute_section_cuts` becomes prepare+evaluate | 1 |
| `sbeam/results/results.py` | `ManeuverStep.{elastic_inertial_loads,damping_loads,section_loads}`; `SectionCutStation.{elastic_inertia,damping}`; `SectionCutEnvelope*`; `ManeuverResult.section_envelope` | 1 / 2 |
| `sbeam/solver/maneuver_qs.py` | thread `a_l`/`v_l` into `_emit`; g-set elastic inertia; cut plans; reactions; `recover_step` signature | 1 |
| `sbeam/solver/maneuver_modal.py` | g-set `f_inert`/`f_damp`; pass through `_emit`; cut plans; reactions | 1 |
| `sbeam/solver/modal_basis.py` | retain `M_gg` on `AsetOperators` (or return it) | 1 |
| `sbeam/results/section_envelope.py` **(new)** | `build_section_envelope`, `write_maneuver_section_envelope_csv` | 2 |
| `sbeam/results/f06_writer.py` | `_section_cut_block(..., title=...)`; critical-sample block in `_build_f06_sol144_maneuver_text`; envelope block | 1 / 2 |
| `sbeam/results/load_export.py` | `write_maneuver_section_loads_csv` (shares the static row builder) | 1 / 2 |
| `sbeam/main.py` | write the two new CSVs when any maneuver result carries section loads | 1 / 2 |
| `sbeam/viewer/results_view.py` | `_render_section_cuts(section_loads, key_prefix)` signature change; wire into `_render_sol144_maneuver`; time-history plot; envelope table; download buttons | 1 / 2 |
| `sample/cessna210_flagship_mloads.bdf` | no card change needed — it already `INCLUDE`s the bulk file carrying `SECRW`/`SECRWA`; add a header comment noting the transient cuts now come out | 1 |
| `sample/ha144a_fullspan_mloads.bdf` | add one `MONSECT` + `AECOMP`/`SET1` so the direct-solver path has cut coverage too | 1 |

### 4.6 Output formats

**f06 (increment 1)** — appended to `_build_f06_sol144_maneuver_text` after the existing
critical-sample displacement/bar-force blocks, reusing `_section_cut_block` with a title
suffix:

```
        S E C T I O N   C U T   R U N N I N G   L O A D S   ( S A M P L E  47,  T = 2.35000E-01 )
```

The per-cut header gains one line when the new columns are non-zero:

```
        SOURCE: AERO + INERTIA + REACTION + ELASTIC INERTIA (+ DAMPING)
```

**f06 (increment 2)** — one `S E C T I O N   C U T   E N V E L O P E` block per cut:

```
         STATION     COMPONENT            MAX     SAMPLE       T-MAX            MIN     SAMPLE       T-MIN
```

The **full** per-sample table is deliberately not written to the f06 — samples × stations
× cuts would swamp the file. f06 carries critical + envelope; CSV carries everything.

**`<stem>.maneuver_section_loads.csv`** — the static `section_loads.csv` schema with four
leading columns inserted after `case`: `mloads`, `sample` (1-based, DEF-M5), `time`,
`critical` (0/1); and two contribution groups appended: `c1_elastic..c6_elastic`,
`c1_damping..c6_damping`. Same column names otherwise, so a tool that reads the static CSV
reads this one. Written as a **separate file** from the static `section_loads.csv`
(different row cardinality and different case semantics — one file with a mostly-empty
`time` column would be worse for both consumers).

**`<stem>.maneuver_section_envelope.csv`** — `case, mloads, massset, mass_case, name,
label, cid, axis, side, half_model, station, comp_index, comp_name, max, max_sample,
max_time, min, min_sample, min_time, absmax`.

**MLDPRNT (`.mldprnt.txt`)** — left alone. Its column set is the DEF-M5/DEF-M7 stabilised
state history; section cuts are a table per sample, not a column.

**Viewer** — `_render_section_cuts` is generalised to take `(section_loads, key_prefix)`
so the static and transient panels share one renderer (the widget `key=` collisions are
why the prefix is a parameter). In `_render_sol144_maneuver`, below the existing sample
slider: the station table/plot for the selected sample; a cut × station × component
time-history chart with the critical-sample vline; and (increment 2) the envelope table
plus min/max band on the station plot. Two more download buttons alongside the existing
MLDPRNT/BDF pair.

---

## 5. Sequencing

### 5.1 Increment 1 — critical sample (~1.5 d)

1. `prepare_section_cuts`/`evaluate_section_cut` split + static bit-identity gate
   (V-TSEC9). **Land and commit this alone** — it is a pure refactor with a strong gate.
2. `M_gg` retention + g-set elastic-inertia/damping recovery in both solvers, with V-TSEC3
   (CBAR equilibrium) as the acceptance gate. This is the risky part; it is second so the
   refactor is not in flight at the same time.
3. Per-sample cut evaluation stored on `ManeuverStep`; reactions wired.
4. f06 critical-sample block, CSV writer (final schema), `main.py`, viewer station table.
5. Sample decks + docs + backlog/history/CHANGELOG (§7).

### 5.2 Increment 2 — history + envelope (~1–1.5 d)

6. `results/section_envelope.py` + envelope on `ManeuverResult`.
7. f06 envelope block; envelope CSV; full per-sample CSV rows.
8. Viewer time-history plot + envelope table/band + downloads.
9. Docs update; V-TSEC6/V-TSEC10.

Increment 1 is independently shippable and useful (it answers "give me the running loads
at the worst instant"). Increment 2 is what makes it defensible ("and no other instant is
worse").

---

## 6. Verification

| ID | Case | Assertion |
|---|---|---|
| **V-TSEC1** | **Quasi-static identity.** Flagship deck, commands held at the trim value, run to steady state. | The last sample's `SECRW` table equals the static Step 53 `MONSECT` table to ~1e-8 relative, station by station, component by component. Elastic-inertia and damping columns → 0. This is the anchor gate: it ties the new path to the already-verified static path. |
| **V-TSEC2** | Critical-sample table structure. | `result.steps[crit_index].section_loads` has the same cuts, stations, `comp_map`, `half_model` and `listtype` as the static run of the same model. |
| **V-TSEC3** | **Free-body / CBAR equilibrium on a dynamic sample.** Pick a sample with non-negligible `ξ̈_e`; take a `SET1` cut at a station between two wing grids. | The cut's `N/V/Mt/M` equals the CBAR internal end force at that station (transformed to the cut CID) to ~1e-6 relative. **Must fail before step 5.1.2 and pass after** — assert this explicitly in the step record; it is the only gate that proves the elastic-inertia term is both needed and correctly signed. |
| **V-TSEC4** | Trivial cuts. | Station outboard of every member → all six components exactly 0, `n_members == 0`. Station inboard of every member on a whole-airplane cut → total equals the sample's net resultant about that reference. |
| **V-TSEC5** | **Free-flight closure consistency.** Step 63 solver, whole-airplane cut, every sample. | Cut total (incl. elastic inertia + damping) ≈ `step.closure` ≈ 0 to the same tolerance the Step 63 closure gate uses. Simultaneously pins the sign convention (§3.1). |
| **V-TSEC6** | Envelope correctness. | `build_section_envelope` max/min/driving-sample match a brute-force numpy reduction over `[s.section_loads for s in steps]`; driving sample is 1-based and consistent with the f06 and CSV. |
| **V-TSEC7** | Half model. | `SYMXZ ≠ 0` deck: transient cut is **not** doubled; `half_model` flag propagates to the f06 and both CSVs. Inherits V-SEC9's intent into the transient path. |
| **V-TSEC8** | `MASSSET` sweep. | Two mass cases over the same maneuver produce different inertia columns and different envelopes; the CSV `massset`/`mass_case` columns identify them. Extends `tests/aero/test_section_cuts_massset.py` to the transient path. |
| **V-TSEC9** | **Static non-regression.** | Every existing static `MONSECT` test (`tests/results/test_section_cuts.py`, `tests/aero/test_section_cuts_sol144.py`, `..._massset.py`, `tests/results/test_section_cut_output.py`) passes unchanged, and the on-plane `UserWarning` still fires exactly once per cut per run (`pytest.warns` count), not once per sample. |
| **V-TSEC10** | Cost. | Flagship `MLOADS` deck with 4 cuts: wall-clock increase < 10 % versus the same deck with the `MONSECT` cards removed. Guards against an accidental per-sample geometry rebuild. |
| **V-TSEC11** | Both solvers. | Direct (`maneuver_qs`) and modal free-flight (`maneuver_modal`) paths both produce cuts; V-TSEC1 runs on both. Prevents the feature landing on one solver only. |

Test files: extend `tests/aero/test_maneuver_qs.py` and add
`tests/aero/test_section_cuts_transient.py` (V-TSEC1–5, 7, 8, 11),
`tests/results/test_section_envelope.py` (V-TSEC6), and the output-format assertions in
`tests/results/test_f06_maneuver.py` / a `test_section_cut_output.py` extension.

---

## 7. Documentation and closure obligations

Per `CLAUDE.md`, all three of these happen in the same session as the code:

1. **`docs/30_future/00_backlog.md`** — **remove** the P8b row from the ranked table and
   **remove** the "Section cuts on transient maneuvers (P8b)" section. Add the P8c row
   (`MONPNT1/3` on transient) if it is wanted as a follow-on.
2. **`docs/40_history/07_maneuver_transient.md`** — add **Step 68** in the full step format
   (Objective / Deliverables / Test & Acceptance / key decisions), including the V-TSEC3
   before-and-after result. Update the contents cell for `07_maneuver_transient.md` in
   `docs/40_history/00_completed_development.md`.
3. **`CHANGELOG.md`** — `[Unreleased]` entry.

Standard-guide updates (also mandatory):

- `docs/10_standard/05c_sol144_maneuver.md` — a transient-`MONSECT` section: semantics, the
  elastic-inertia column, the two CSVs, the envelope, critical-sample vs driving-sample.
- `docs/10_standard/05_aeroelastics.md` — card table / validation status: `MONSECT` moves
  from "static only" to "static + transient".
- `docs/10_standard/06_viewer.md` — the transient section-cut panel.
- `docs/20_theory/01_aeroelastics_theory.md` §7.3a — extend the section-cut derivation with
  the transient free body (the `M·ü_e` term and why the global closure cannot see it).
- `designs/monsect_section_cuts.md` §2.2 — mark the transient bullet delivered, pointing here.
- `CLAUDE.md` — the "SOL 144 transient maneuver loads" bullet gains the two new exports.

---

## 8. Risks and effort

### 8.1 Effort

| Task | Est. |
|---|---|
| Two-phase section-cut API + static bit-identity gate | 0.4 d |
| `M_gg` retention + g-set elastic-inertia/damping in both solvers | 0.6 d |
| Per-sample evaluation, reactions, `ManeuverStep` plumbing | 0.3 d |
| f06 critical block + CSV writer + `main.py` + viewer table | 0.3 d |
| V-TSEC1–5, 7–9, 11 + sample decks | 0.4 d |
| **Increment 1 subtotal** | **~2.0 d** |
| Envelope module + f06 block + envelope CSV | 0.4 d |
| Full-history CSV rows + viewer time-history/envelope UI | 0.4 d |
| V-TSEC6, V-TSEC10 + docs/history/changelog | 0.3 d |
| **Increment 2 subtotal** | **~1.1 d** |
| **Total** | **~3 d** |

Against the backlog's ~2 d. The delta is the elastic-inertia term (§1.2), which the
backlog estimate did not account for because the *integrand* really is reusable verbatim —
it is the integrand's *inputs* that are incomplete on a transient sample.

### 8.2 Top correctness risks

1. **Wrong sign or frame on the elastic-inertia term.** It would look plausible (right
   order of magnitude, smooth in time) and quietly corrupt every dynamic cut. Mitigated by
   V-TSEC5 (pins the sign against a known-zero closure) and V-TSEC3 (pins the magnitude
   against the independently computed CBAR internal force). Neither alone is sufficient.
2. **a-set → g-set force mapping.** Forming the elastic inertia in the a-set and pushing
   it back to g through a transpose is wrong across RBE3. The design mandates
   `M_gg @ expand_to_g(ü_a)`; a review checkpoint should confirm no `T.T @ f_a` appears.
3. **Recovery-mode divergence.** The modal solver has two recovery modes; if only the
   mode-acceleration branch builds `f_inert`, the `"displacement"` branch silently reports
   cuts without elastic inertia. Build the term once, outside the branch.
4. **Silent per-sample warning storm or geometry rebuild.** Caught by V-TSEC9's warning
   count and V-TSEC10's timing.
5. **Static regression through the refactor.** The static path is released behaviour;
   V-TSEC9 requires bit-identity, and the refactor lands as its own commit so a bisect is
   one step.
6. **Memory on long runs.** Bounded and documented (§4.2); if a deck ever exceeds comfort,
   the escape hatch is a `MLDPRNT` item keyword to store only the critical sample — noted,
   not built.

---

## 9. Open questions

- **O1 — should `net_loads` include the elastic inertia?** *Resolved 2026-09-05 by #3:
  yes, with the damping term too —
  [`transient_net_loads_elastic_inertia.md`](transient_net_loads_elastic_inertia.md).*
  Original text: Physically the exported
  critical-sample `FORCE`/`MOMENT` cards are the load a stress model should see, and that
  load *does* include `M·ü_e`. This design deliberately does **not** change `net_loads`,
  because doing so simultaneously moves the exported cards, the closure diagnostic and the
  DEF-M5 critical-sample selection. Recommendation: land Step 68 as designed, then raise a
  separate item ("transient net load should carry elastic inertia") with its own gates —
  the data will be sitting on `ManeuverStep` to quantify the difference first.
- **O2 — envelope over rate-of-change (`d_ds`)?** The static table carries a `d_ds` running
  load. Enveloping a derivative is rarely what a stress group wants. Proposal: carry
  `d_ds` per sample in the CSV (free) but envelope only the loads themselves.
- **O3 — `AELIST` cuts on transient.** Aero-only cuts work per sample with no new physics
  (`box_forces_t` is already computed). Included; flagged only because their inertia,
  damping and reaction columns are structurally zero, which the `SOURCE:` line should say
  rather than printing zeros without comment.

---

## 10. Acceptance criteria

1. A deck with `MONSECT` cards and an `MLOADS` subcase produces section-cut running loads
   at every output sample, under **both** transient solvers.
2. V-TSEC1 passes: holding commands at trim reproduces the static `MONSECT` table to ~1e-8.
3. V-TSEC3 passes: on a dynamic sample the cut equals the CBAR internal force — documented
   as failing before the elastic-inertia term and passing after.
4. V-TSEC5 passes: the whole-airplane transient cut equals the step closure (≈ 0 free-flight).
5. f06 carries the critical-sample table and the envelope block; the full history is in
   `<stem>.maneuver_section_loads.csv` and the envelope in
   `<stem>.maneuver_section_envelope.csv`.
6. Viewer shows the station table at the selected sample, a cut/station/component time
   history, the envelope, and offers both CSVs as downloads.
7. V-TSEC9 passes: every existing static `MONSECT` result is bit-identical and the
   on-plane warning still fires once per run.
8. V-TSEC10 passes: < 10 % wall-clock overhead on the flagship deck.
9. Backlog row removed, Step 68 recorded in `40_history/07_maneuver_transient.md`,
   `CHANGELOG.md` updated, and the six standard/theory docs in §7 updated.
