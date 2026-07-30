# Completed Development — Transient Maneuver Loads (Phase G0)

Part of the completed-development record (index: `00_completed_development.md`).
Covers the DLM-free quasi-steady transient maneuver-loads capability (ZAERO MLOADS
card set). Future Phase G0 steps (61-63: modal basis, modal transient solver, free-flight) land here.

---

## Phase G0 — Quasi-Steady Transient Maneuver Loads (DLM-free)

### Phase G0 — Increment 1: DLM-free quasi-steady transient maneuver loads ✅ COMPLETE (2026-06-13)

**Objective:** Add a ZAERO `MLOADS`-style **transient** maneuver-loads capability without the DLM —
time-integrate the elastic response of the airframe to a prescribed (open-loop) pilot-command
history, starting from a Step 53 static balanced-trim initial condition, and recover the net
(aero + inertial) maneuver loads at each output time. This is increment 1 (Level-1 quasi-steady,
open-loop) of the DLM-free Phase G0 path; full unsteady MLOADS (state-space / RFA / control law) is
Phase G, gated on the DLM (Phase D).

**Method (restrained l-set, Level-1 quasi-steady `Ω×r`):** exactly like the Step 53 trim, the SUPORT
(r-set) rigid-body DOFs are held at the mean axis (`u_r = 0`) and the elastic l-set responds. The
governing l-set equation, integrated with the unconditionally stable Newmark-β average-acceleration
scheme (β=¼, γ=½), is

    M_ll ü_l + C_ll u̇_l + (K_ll − q·Q_ll) u_l = f_aero_l + q·Q_ax_l·δ(t) + M_ax_l·a_basic(t)

The right-hand side is the **steady** VLM evaluated at the instantaneous deformation and trim-variable
state `δ(t)` (control deflections + attitude + rigid-body rates via the `build_djx` rate columns) plus
the inertia-relief forcing `M_ax·a(t)`. There is no DLM, no aerodynamic lag, and no apparent mass.
The RHS is **identical to the Step 53 trim RHS when `δ(t) = δ_trim`**, so holding the commanded state at
the trim value reproduces the Step 53 balanced load to machine precision. The l-set is integrated
**directly** (not modally) so this static identity is exact rather than mode-truncation-limited;
modal reduction with the SOL 103 eigenbasis is the documented Level-1b follow-on. The initial
acceleration is taken as exactly zero (the run starts at static equilibrium), so a singular lumped
`M_ll` is tolerated (no `M⁻¹`).

**Deliverables:**
- **ZAERO `MLOADS` card set (`sbeam/model/maneuver.py`, `parser/bdf_reader.py`,
  `parser/case_control.py`):** `MLOADS` (driver), `MLDTRIM` (initial-condition TRIM sid),
  `MLDCOMD` (pilot command label → time history), `MLDTIME` (t0/tend/dt/tout), `MLDPRNT` (ASCII
  output request), and the general `TABLED1` tabular function (linear interpolation, held
  extrapolation). Full cross-reference validation; `MLOADS` is selected in case control by an
  `MLOADS = sid` subcase entry under SOL 144.
- **Solver (`sbeam/solver/maneuver_qs.py`):** `run_maneuver_qs` — runs the Step 53 trim for the
  `MLDTRIM` IC, re-assembles the a-set/l-set operators (mirroring `run_sol144_trim` so the working
  trim path is untouched), reduces the structural mass to the l-set, and Newmark-integrates. Each
  output sample recovers g-set displacements, CBAR end loads, instantaneous aero box forces, the net
  (aero + inertial) grid load, and the 6-component closure resultant.
- **Output (`sbeam/results/maneuver_output.py`, `main.py`):** an MLDPRNT ASCII time-history table
  (`<stem>.mldprnt.txt`) and the critical-sample (peak |net force|) net-load FORCE/MOMENT export
  (`<stem>.maneuver_qs_loads.bdf`, reusing `_emit_force_moment_cards`).

**Test/Acceptance (`tests/aero/test_maneuver_cards.py`, `tests/aero/test_maneuver_qs.py`):**
- Card round-trip echo + cross-reference validation (13 tests).
- **G0 → Step 53 identity (strongest gate):** holding the state at trim, every sample reproduces the
  Step 53 net load to ~1e-12 (machine precision).
- **Quasi-static settling:** a slow full-state ramp 1g→2g asymptotes (with mass-proportional damping)
  to the Step 53 2g balanced load (≈3e-10 relative), with the net force/moment closing to ≈0; settled
  aero lift = `n_z·W`.
- **Per-step closure:** for a consistent (trimmed) command history the closure transient stays bounded
  and decays. Plus MLDPRNT and critical-load export round-trips. 7 tests; full suite 870 green.

**Key decisions:**
- **Open-loop prescribed-kinematics convention (increment 1):** every trim variable is prescribed
  (commanded or held at trim). Closure ≈ 0 holds when the commanded histories form a consistent
  (trimmed) set; the per-step closure residual otherwise equals the instantaneous rigid-body net
  force. Re-solving the free rigid-body variables each step so the load self-balances (free-flight
  rigid-body coupling) is a Level-1b follow-on, as is closed-loop control.
- **Direct l-set integration over modal reduction** for increment 1, because free-free SOL 103 modes
  differ from the SUPORT-restrained mean-axis modes and would make the Step 53 identity
  truncation-approximate rather than exact.
- Gravity stays folded into the URDD load factor (consistent with Step 53); the `MLDTRIM` Step 53
  trim is the steady-state initial condition.


### Step 59 (P1) — Prerequisite refactor: shared a-set reduction + SOL 103 retention (behavior-identical) ✅ COMPLETE (2026-07-06)

**Objective:** Eliminate the 4×-duplicated RBE3+SPC a-set reduction and retain a-set eigendata so
every later Phase G0 step composes one code path. This is the `reduce_to_aset` refactor specified
in `designs/matrix_gaf_export.md` §6.1 (and `matrix_reuse_store.md` §8.1) — landed here under the
single-owner rule so all three features reuse it, never re-extract.

**Deliverables:**
- **`sbeam/assembly/reduction.py` (new):** `reduce_to_aset(bulk, grid_index, spc_sid) →
  AsetReduction` dataclass `{T, dep_dofs, red_dofs, free_local, free_dofs}` with methods
  `reduce_matrix` (square g-set → a-set; `dense=True` for the dense SOL 144 systems),
  `reduce_rect` (rectangular column blocks: Q_ax, M_ax), `reduce_vector`, and `expand_to_g`
  (absorbing `sol144._expand_to_g`, which now aliases the moved module-level function).
  Extracted verbatim from `sol144._compute_aset_data` / `_build_qaa_aset`.
- **Re-pointed consumers:** `sol103.run_sol103` (its two RBE3/no-RBE3 branches collapsed onto
  the shared path), `sol144` (`_build_qaa_aset`, `run_sol144_trim`, `run_sol144_diverg`), and
  `maneuver_qs._assemble_operators` (six hand-rolled reduce-then-index blocks replaced by the
  dataclass methods). `sol144._compute_aset_data` kept as a thin tuple-returning wrapper for
  existing importers.
- **`Sol103Result`** gains optional `phi_free` (a-set mode shapes), `free_dofs` (g-set indices),
  `K_free`, `M_free` (all default `None`), populated by `run_sol103` from values already in hand —
  the retention consumed by Step 61's modal basis and the `matrix_gaf_export` GAF loop.

**Test/Acceptance:**
- Full suite passes unchanged (1104 → 1115 with the 11 new reduction tests).
- Bit-identical pre/post refactor (modulo embedded run timestamps): SOL 103 f06
  (`val_cantilever_modes`, `val_free_free_modes`, `beam_vib`), SOL 144 trim f06 + aero/maneuver/
  monitor exports (`ha144a_fullspan_sbeam`), and the full `sample/ha144a_fullspan_mloads.bdf`
  maneuver output set (f06, `.mldprnt.txt`, `.maneuver_qs_loads.bdf`, all load/monitor exports).
- **`tests/assembly/test_reduction.py` (new, 11 tests):** `reduce_to_aset` products equal the old
  `_compute_aset_data` logic (reproduced verbatim as the reference) on an RBE3+SPC model;
  `reduce_matrix`/`reduce_vector`/`reduce_rect` match the old `_build_qaa_aset` reductions
  exactly; identity-T path, `spc_sid=None` free-free path, and expand/scatter round-trip.

**Key decisions:**
- **`reduce_matrix` preserves input sparsity when no dependent DOFs exist** (matching the old
  `apply_spcs` semantics) so SOL 103's sparse `eigsh` shift-invert path is untouched; SOL 144
  callers pass `dense=True` to reproduce the old explicit `.toarray()` densification. This is the
  one place the four duplicated code paths genuinely differed, and the reason a naive extraction
  would not have been behavior-identical.
- Operation order inside the reduction moved verbatim (no "cleanup" reordering of
  `T.T @ A @ T` vs slicing) to keep float results bit-identical.
- `sol101.py` also performs an RBE3+SPC reduction but was deliberately left out of scope
  (not in the Step 59 re-point list; behavior-identical risk minimisation).

---

### Step 60 (P2) — MASSSET payload / mass-case capability for static SOL 144 ✅ COMPLETE (2026-07-30)

**Objective:** ZAERO-style payload-condition sweeps for the **existing static capability**: one
deck, N subcases, each pairing a `MASSSET` with its TRIM (or Step 53 balanced-maneuver) case —
AIC/splines/stiffness shared, only mass-derived quantities rebuilt per case. This is the
early-design payload deliverable; the modal fixed-Φ interaction lands with Step 62.

**Deliverables:**
- **New `MASSSET` card** (`Massset` dataclass in `model/mass.py`, `bulk.masssets`,
  `_handle_massset` + dispatch branch, post-parse cross-reference validation):
  ```
  MASSSET, SID, LABEL, SCALE
  +, ADD,     e1, e2, ...
  +, REPLACE, old1, new1, old2, new2, ...
  +, DELETE,  e1, e2, ...
  ```
  `LABEL` = case name for output headers; `SCALE` (default 1.0, must be ≥ 0) multiplies the
  baseline mass before the ops. Continuation rows are an op keyword + CONM2 EIDs; any number
  of rows of any op, in any order. Overlay CONM2s are ordinary `CONM2` bulk cards; a post-parse
  pass marks every `ADD` EID and every `REPLACE` overlay-slot EID as **overlay-only** in
  `bulk.overlay_conm2_eids` so baseline assembly excludes them.
- **Case-control `MASSSET = n`** per subcase (`SubcaseControl.massset_sid`) — MSC-style selection
  like SPC/METHOD.
- **`model/mass_overlay.py` (new):** `resolve_mass_case(bulk, massset_sid) → MassCase`
  (`sid`, `label`, `scale`, `conm2s` with baseline members already scaled) and the
  `effective_conm2s(...)` shorthand. `assemble_global_mass(..., massset_sid=None)`,
  `_build_inertial_cols(..., massset_sid=None)`, `compute_gpwg(..., massset_sid=None)`,
  `run_sol144_trim` and `run_maneuver_qs` all threaded. Explicit invariant (module docstring,
  code comment, doc, and an object-identity test): **no AeroCache invalidation — the AIC is
  geometry/Mach-only.**
- **Output:** `Sol144TrimResult` gains `massset_sid` / `massset_label` / `massset_mass` /
  `massset_cg`; the f06 subcase header gains `MASSSET =`/`LABEL =`/`MASS =` and `CG =` lines
  (emitted only when a MASSSET is selected, so baseline decks stay byte-identical); the
  monitor-loads CSV gains `massset` + `mass_case` columns; both load-card exports stamp the case
  in their comment block; the viewer GPWG panel gains a mass-case selector and the analysis-plan
  summary names the case per subcase.
- **New sample deck `sample/ha144a_massset_sweep.bdf`** — full-span HA144A, one TRIM card, three
  payload conditions exercising all three ops: EMPTY 16000 lb (`DELETE` baggage), HALFFUEL
  18500 lb (`ADD` 2000 lb wing fuel), FULLFUEL 21000 lb (`ADD` 4000 lb wing fuel +
  `REPLACE` 500 lb baggage with 1000 lb).

**Test/Acceptance (`tests/parser/test_massset.py` 26 tests, `tests/aero/test_massset_sweep.py`
16 tests):**
- Parser round-trip (free- and fixed-field), all three ops, multi-row ops, SCALE (including
  the inertia tensor and SCALE = 0), overlay marking, deck-order preservation, and every
  negative case: dangling EID, duplicate reference within one MASSSET, EID used as both
  overlay and baseline, odd `REPLACE` count, unknown op, empty op row, negative SCALE,
  duplicate SID, case control selecting an undefined SID.
- **Equivalence gate:** each of the three cases matches a hand-edited deck carrying the same
  final CONM2 set — `np.array_equal` on `M_gg`, exact-equality GPWG mass/CG, and trim
  variables + displacements to 1e-12.
- **Baseline unchanged:** a deck with no MASSSET has `resolve_mass_case(bulk, None).conm2s is
  bulk.conm2s`-equal and `assemble_global_mass(bulk) == assemble_global_mass(bulk, None)`; the
  EMPTY case reproduces the untouched `ha144a_fullspan_sbeam.bdf` subcase-1 trim exactly
  (ANGLEA 1.693721E-01 both ways).
- **Per-case Step 53 closure ≈ 0** (Fz and My), and trimmed lift = case weight to 1e-6.
- **Sweep test:** three subcases / three MASSSETs share one `AeroModel` — `len(cache._cache) == 1`
  plus `is` identity on the model and on `ajj_inv_corr`.
- **Physics:** heavier case ⇒ monotonically larger trimmed ANGLEA (0.16937 → 0.20079 → 0.23220)
  and a further-aft CG (17.18 → 17.75 → 18.18 ft).

**Key decisions:**
- **`REPLACE` takes (baseline EID, overlay EID) pairs**, not a flat list. The plan's flat-list
  sketch was self-contradictory against its own overlay-marking rule (a referenced EID cannot be
  both baseline and overlay); pairs make "supersedes a baseline EID" literal and make every
  promised error case — dangling REPLACE, an EID used as both overlay and baseline — fall out of
  the same check. Cost: 3 pairs per fixed-field row instead of 7 EIDs.
- **Case-control selection** (not a TRIM/MLDTRIM field) so static and transient share the
  mechanism — `run_maneuver_qs` threads `massset_sid` into its own operators *and* into the
  initial-condition trim, so an `MLOADS` subcase carrying a `MASSSET` runs at that payload
  condition rather than silently ignoring it.
- **`SCALE` applies to the whole baseline mass** — CBAR distributed mass and baseline CONM2 mass
  *and* inertia tensor (the 6×6 CONM2 block is linear in `(m, I)`, so scaling both scales the
  whole block including offset coupling and parallel-axis terms). Overlay cards enter unscaled.
- The effective CONM2 set is built by iterating `bulk.conm2s`, so it keeps **deck order** and a
  mass case sums contributions in the same order a hand-edited deck would — the reason the
  equivalence gate can assert exact `np.array_equal` on `M_gg` rather than a tolerance.
- **`mirror_halfspan` rejects MASSSET decks** (added to `_UNSUPPORTED`): whether a payload item
  mirrors (wing fuel) or does not (a centreline store) is model intent, not geometry.
- MAT1-`rho` overlays out of scope (v1) — use `SCALE`, or author a separate deck.
