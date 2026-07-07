# Completed Development — Transient Maneuver Loads (Phase G0)

Part of the completed-development record (index: `00_completed_development.md`).
Covers the DLM-free quasi-steady transient maneuver-loads capability (ZAERO MLOADS
card set). Future Phase G0 steps (60-63: MASSSET, modal basis, free-flight) land here.

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
