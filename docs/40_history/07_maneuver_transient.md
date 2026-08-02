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

---

### Step 61 (P4) — Free-free maneuver modal basis + one-time h-set operator set ✅ COMPLETE (2026-07-30)

**Objective:** Build the ZAERO-style free-free basis `Φ = [Φ_r | Φ_e]` and precompute every
geometry/Mach-only h-set operator exactly once, validated **standalone** before any time
integration touches it (the consumer is Step 62).

**Deliverables:**
- **`sbeam/solver/modal_basis.py` (new):**
  - `build_rigid_modes(bulk, grid_index, red, rigid_dofs, ref_pos) → Φ_r` — **the single
    rigid-basis builder** (`designs/rbmref_card.md` reuses it; its `B_target` is the same
    object). One column per SUPORT DOF, geometric vectors about `suport_pos`: unit axis for
    translations, `â × (x_i − p)` / `â` for rotations. The a-set restriction is a **row
    selection on the independent DOFs**, not the force-type `Tᵀ·` reduction (rigid vectors are
    displacements); the builder asserts the round trip back through the RBE3/RBAR `T`.
  - `build_maneuver_basis(bulk, ops, eigrl=None, nmodes=0) → ManeuverBasis` — one `solve_modes`
    call per job (basis-consistency rule, `designs/matrix_gaf_export.md` §4.3), mean-axis
    orthogonalization `φ_e ← φ_e − Φ_r M_rr⁻¹ Φ_rᵀ M_aa φ_e` (twice, then M-normalized) against
    the **unregularized** `M_aa`, generalized-mass filter, NMODES truncation of the elastic
    partition only. Returns `phi`, `n_r`/`n_e`, `rigid_dofs`, `rigid_label_map`, `suport_pos`,
    `elastic_freqs_hz`, `M_hh`, `K_hh`, `M_rr`, `orthogonality_residual`, `n_filtered`,
    `filtered_freqs_hz`, `n_available_elastic`, `n_massless`.
  - `build_hset_gafs(bulk, ops, basis, aero, v_inf, zeta=0.0) → HsetGafs` — `Q_hh` via
    `coupling.build_gaf` (reused verbatim), `Q_hx` for **all** trim labels with `Q_hc` as the
    AESURF subset view (so Steps 62 and 63 each take the columns they need without re-deriving
    anything), the rigid-rate `B_hh`, `f_h0`, and `C_hh = diag(2ζω)` on the elastic partition.
    All aerodynamic operators are **dynamic-pressure free**.
  - `assemble_aset_operators(bulk, subcase, aero) → AsetOperators` — the shared a-set assembly
    (K_aa/M_aa/Q_aa/Q_ax/M_ax/baseline aero/RCSID transform/SUPORT data) on top of Step 59's
    `reduce_to_aset`. `maneuver_qs._assemble_operators` now calls it and adds only the l-set
    partition and the `q` scaling — behaviour bit-identical (full suite green before and after).
- **`aero/integration.py::build_dj_rigidrate(boxes, rigid_dofs, bulk, v_inf)`** — normalwash per
  unit *physical* rigid-body rate. Every column is the corresponding `build_djx` column rescaled
  (plunge `−1/V·ANGLEA`, lateral `+1/V·SIDES`, pitch `c_ref/2V·PITCH`, roll/yaw `b_ref/2V`),
  so the `Ω×r` geometry keeps exactly one owner. DOF 1 (streamwise) is zero at k = 0.
  Elastic-rate columns are an explicit zero block — the documented G0-d hook.
- **MLOADS card extension:** `MLOADS SID MLDTRIM MLDTIME MLDCOMD MLDPRNT NMODES METHOD ZETA`
  (still one small-field line). `METHOD` = EIGRL sid for the basis solve (0 ⇒ internal all-modes
  default), `ZETA` = uniform elastic modal damping ratio. **NMODES semantics fixed: count of
  retained ELASTIC modes; rigid modes always all included** (0 ⇒ all elastic). Validation:
  METHOD must name an EIGRL, NMODES ≥ 0, ZETA ≥ 0. `run_maneuver_qs` warns that it ignores all
  three (extends the increment-1 NMODES warning) — no behaviour change to the legacy solver.
- **TRIM `RHOREF` (sbeam extension):** a reserved pseudo-label in the LABEL/VALUE pair list
  (`TRIM, 1, 0.9, 40.0, RHOREF, 2.3769-3, PITCH, 0.0`) carrying the freestream density, so
  `Trim.velocity() = √(2q/ρ)`. This is the only source of a true airspeed in the deck and the
  rate columns cannot be formed without it. Back-compatible (no field-layout change); an
  AESTAT/AESURF label named `RHOREF` is rejected. `sample/ha144a_fullspan_mloads.bdf` updated.

**Test/Acceptance (`tests/solver/test_modal_basis.py`, 18 tests; plus `TestBuildDjRigidRate` in
`tests/aero/test_integration.py` and 8 card tests in `tests/aero/test_maneuver_cards.py`):**
- `Φᵀ M_aa Φ` block diagonal (rigid↔elastic coupling < 1e−10 relative — the mean-axis
  condition), elastic block = I; measured `orthogonality_residual` ≈ 6e−16 on HA144A.
- `M_rr` = GPWG rigid mass about `suport_pos`: `M_rr[0,0]` = total mass, `M_rr[0,1]` =
  `−m(x_cg − x_sup)` from the GPWG CG, `M_rr[1,1]` against an independent `Σ m_i r_i²` sum.
- **`M_ax` identity** — the a-set-reduced `_build_inertial_cols` URDD columns equal `−M_aa Φ_r`
  column for column via `rigid_label_map`, to machine precision on the CONM2-only fixture.
- `Q_hh` **and** `K_hh` equal to `sol144._solve_rom`'s projections for the same basis (1e−12).
- `K_hh` rigid rows/columns ≤ 1e−8·‖K_hh‖ (measured 1.3e−14).
- `B_hh` rigid-rate columns against their exact rescaling of `Q_hx`; elastic columns exactly 0.
- Rigid-vector round trip; NMODES truncation + over-request warning; METHOD/EIGRL bounding;
  no-SUPORT error; C_hh damping; `v_inf ≤ 0` error; TRIM/MLOADS card round-trips and negatives.

**Key decisions:**
- **Geometric rigid vectors over eigensolver zero modes** — deterministic across mass cases and
  LAPACK builds, exact GPWG/`M_ax` identities, and an exact algebraic map to the URDD/ANGLEA/
  PITCH trim labels (rigid trim labels become *outputs* of the later transient solve). Recorded
  in theory §7.8.
- **Massless DOFs are statically (Guyan) condensed, not regularised and filtered** — a deviation
  from the plan's sketch, forced by measurement. With Tikhonov regularisation the eigenvectors
  carry `O(1/√ε)` amplitudes on the massless DOFs and are M-orthogonal only against the
  *regularised* mass; the mean-axis projection against the true `M_aa` then left the HA144A basis
  **0.99 non-orthogonal** while every mode still reported unit generalized mass — invisible to any
  frequency or mass filter. Condensation is exact (those equations carry no mass at any
  frequency) and the condensed subspace contains the rigid vectors exactly, since `K u_r = 0`.
  After it, HA144A gives 2 rigid + 30 elastic modes from a 50-DOF a-set (18 condensed), the
  filter drops only the rigid zero modes, and the previously-reported contaminated frequencies
  (5.59/6.20/9.84…) resolve to the correct 5.53/6.20/9.89… Hz.
- **`Q_hx` is kept for all labels**, `Q_hc` being a view of its AESURF columns — costs nothing and
  keeps Steps 62 (prescribed rigid) and 63 (free rigid) from re-deriving the projection.
- Basis always from the **baseline** mass configuration; `Φ` fixed across MASSSET cases (Step 62).
- All aerodynamic h-set operators are q-free, matching the `Q_aa` convention, so the solver
  applies `q` uniformly in `M_hh Δξ̈ + [C_hh − q·B_hh]Δξ̇ + [K_hh − q·Q_hh]Δξ = q·Q_hc·Δδ_c(t)`.

**Found, not fixed (backlog Q4):** `_build_inertial_cols` is a *lumped* inertia model while
`M_aa` is *consistent*, so the `M_ax = −M_aa Φ_r` identity is exact on translational rows always
and on all rows for CONM2-only decks, but the rotational rows differ once CBARs carry `rho > 0`
(no lumped counterpart to the consistent-mass translation↔rotation coupling; measured O(10%) of
the peak column value). Pre-existing in the Step 53 and increment-1 inertia-relief RHS, pinned by
`test_m_ax_identity_limits_with_consistent_cbar_mass`.

> **Closed 2026-07-31** (Q4 + DEF-M3) — `build_inertial_cols` is now `−M_gg·Φ_r` off the same
> consistent mass matrix, so the identity is exact on all rows and the pin became
> `test_m_ax_identity_exact_with_consistent_cbar_mass`. See
> `docs/40_history/06_sol144_static_aeroelastic.md`.

---

### Step 62 (P10) — Modal transient solver, prescribed rigid states + fixed-Φ mass-case gates ✅ COMPLETE (2026-08-02)

**Objective:** De-risk basis + integration + mode-acceleration recovery with the rigid partition
still *prescribed* (open-loop, exactly increment-1 physics) before Step 63 frees it — isolating
truncation behavior from free-flight dynamics — and land the fixed-Φ mass-case transient
capability on top of Step 60's MASSSET.

**Design decisions (resolved with the user, 2026-08-02):**

| # | Decision | Outcome |
|---|----------|---------|
| D1 | Solver selection | Trio-nonzero (any of NMODES/METHOD/ZETA) + `METHOD=-1` all-defaults-modal sentinel; all-zeros keeps the direct solver bit-identical. `Mloads.selects_modal` is the single dispatch predicate. |
| D2 | Displacement convention | Outputs in the direct solver's `u_r = 0` frame — realized by re-basing the *basis* (below), so the full-basis gate is a plain match on all quantities. |
| D3 | Φ sharing scope | Job-level `ManeuverBasisCache` (keyed `spc_sid` + EIGRL sid), shared by `main.py` across all modal MLOADS subcases; basis always from the baseline mass. |
| D4 | CG-shift warning | Warn when a MASSSET overlay moves the GPWG CG by more than 5 % of `c_ref`. |

**Key implementation finding — restrained-frame re-basing (Eq. 41, theory §7.9).** A Galerkin
projection onto the mean-axis `Φ_e` directly cannot reproduce the direct solver: under an
unbalancing command the implicit SUPORT reaction leaks into the mean-axis test space
(`Φ_e,rᵀλ ≠ 0`) and the restrained solution's rigid content carries aero load
(`q·Φ_eᵀQ·Φ_r c`) the elastic-only system never sees. Re-basing each mode to be zero at the
SUPORT DOFs (`ψ_e = φ_e − Φ_r(Φ_r[r])⁻¹φ_e[r]` — strain-identical; the D2 convention applied to
the basis) kills both terms, making the reduced system `M_ψψξ̈ + C_ψψξ̇ + K_ψψξ = VᵀF_l(t)`
(V = `ψ_e[l]`) an **exact change of coordinates** of the increment-1 l-set ODE at full basis.
`B_hh` deliberately not engaged (rates prescribed via δ(t) labels — would double-count; Step 63).
Second finding: on CONM2-only decks the Guyan condensation removes massless DOFs from the basis,
so even the full basis cannot span the l-set — mode-acceleration recovers their static content
through `K_eff⁻¹` and the identity degrades to a measured ~1e−5 (net loads) near-identity.
Third finding (risk item 3 realized): clamped-linear TABLED1 ramps ring the highest retained
modes and put an ω-independent floor under truncated solutions — NMODES convergence is only
visible on smooth (cosine-sampled) commands; documented as deck-authoring practice.

**Deliverables:**
- `sbeam/solver/maneuver_modal.py` — `run_maneuver_modal(bulk, subcase, aero, aero_cache=None,
  basis_cache=None, recovery="acceleration")`: IC trim (mass case threaded), restrained-frame
  re-basing, dense n_e Newmark-β (¼, ½), equilibrium start (`K_ψψξ0 = VᵀF(t0)` ⇒ recovered t0
  sample = the direct static start independently of truncation), mode-acceleration recovery with
  inertia relief reusing the direct solver's `K_eff_ll` (damping force `M_ll V·2ζω_iξ̇_i`
  consistent with `C_ψψ = M_ψψ·diag(2ζω_i)`); `ManeuverBasisCache` (D3) + D4 CG warning;
  `recovery="displacement"` as the test/reference mode.
- Dispatch: `main.py` routes `Mloads.selects_modal` subcases to the modal solver with one shared
  basis cache; parser accepts `METHOD=-1` (validates ≥ −1); the increment-1
  NMODES-ignored warning retired (CHANGELOG behavior change).
- Shared recovery: `maneuver_qs`'s `Operators`/`assemble_operators`/`delta_of_t`/`force_l`/
  `recover_step` made the sanctioned shared names (were `_`-private), `Operators` gains
  `suport_local`; `recover_step` gains `modal_coords` passthrough. `modal_basis.truncate_basis`
  (per-subcase NMODES as a column slice — one eigensolve per job, risk item 9 enforced
  structurally). `ManeuverStep.modal_coords`; `ManeuverResult.massset_sid` / `n_modes_used` /
  `basis_info`; f06 `MODAL SOLVER` basis-summary block (modal runs only — direct output
  byte-identical).
- Docs: theory §7.9 (records the reversal of the increment-1 restrained-basis decision *and* why
  the restrained frame reappears as a representation in Step 62), `05c_sol144_maneuver.md`
  Step 62 user section, `02_card_reference.md` MLOADS fields, `05_aeroelastics.md` module table,
  CLAUDE.md.

**Test/Acceptance (`tests/solver/test_maneuver_modal.py`, 15 gates):** full-basis identity to
`run_maneuver_qs` ≤ 1e−6 (measured ~1e−14) on the rho-variant HA144A deck (`n_massless = 0`);
documented CONM2-only near-identity (≤1e−4 net loads); monotone NMODES ∈ {2, 4, 8, all}
peak-CBAR-force decay on a smooth command; mode-acceleration ≥ 10× over mode-displacement
(measured ~400×); hold-at-trim = Step 53 to 1e−8; ζ > 0 halves the late-time oscillation;
fixed-Φ exactness (MASSSET + all modes ≤ 1e−6 vs the direct solver on the same case) and
approximation (+10 % fuel, NMODES=8: peak CBAR force within 2 % of a re-solved-modes reference);
basis cache builds Φ exactly once across five runs; truncated equilibrium start exact (≤1e−9);
D4 warning fires above 5 % `c_ref` and not below; `selects_modal` truth table, `METHOD=-1`
parser sentinel, no-warning-on-all-zeros; f06 summary present for modal, absent for direct.
Full suite: 1581 passed.

---

## Resolved defects

### DEF-R6 (maneuver share) — `run_maneuver_qs` rebuilt the Mach-correct AIC twice ✅ COMPLETE (2026-08-02)

**Objective:** When called without an `AeroCache`, `run_maneuver_qs` let the IC trim build
and discard its own internal cache, then seeded a fresh `AeroCache` with the *original*
(wrong-Mach) model, so the subsequent `aero_cache.get(ic.mach)` rebuilt the full AIC a
second time.

**Deliverables:** `solver/maneuver_qs.py` — the `if aero_cache is None` seeding is hoisted
**above** the `run_sol144_trim` call and the cache is passed in; the trim populates it at
the flight Mach, so `.get(ic.mach)` is a cache hit. The hoisted `build_grid_index` result
is reused for the later `grid_index` (was computed twice).

**Test/Acceptance:** maneuver/MLOADS integration tests unchanged and green. Part of the P9
batch — see `05_aero_vlm_spline.md` "Performance".

---

### DEF-M5 — critical maneuver sample: selector, f06 label and printed column were three different metrics ✅ COMPLETE (2026-08-01)

**Objective:** The Phase G0 "critical sample" — the one whose net load is exported for stress
sizing — was named by four disagreeing things:

| Role | Quantity it actually used |
|------|---------------------------|
| Selector (`maneuver_qs.py:342`) | `argmax ‖closure[:3]‖` |
| f06 label (`f06_writer.py:708`) | printed `PEAK \|NET FORCE\|` |
| f06 column (`:719,722`) | `max\|net_loads\|` over **all six DOFs** — forces and moments mixed |
| MLDPRNT (`maneuver_output.py:38`) | printed the **0-based** index; the f06 printed 1-based |

`closure` is the resultant of `net_loads` about the reference point — i.e. the aero/inertia
**balance residual**, which is ~0 on a converged balanced maneuver. Selecting on it ranked samples
by numerical noise. Verified divergent on the shipped deck (selector 7, column peak 11), so the
exported critical-sample BDF was taken at a sample the printed table disowned.

**Deliverables:**
- **`results.peak_grid_force(step)`** — the max over grids of the net (aero + inertial)
  translational force magnitude. Placed beside `ManeuverStep` in `results.py`, not in an output
  module, so the solver does not have to import `results/maneuver_output` to select.
- One metric everywhere: `maneuver_qs` selects with it, the f06 column prints it under
  `PEAK GRID F`, the f06 header names it `PEAK |NET GRID FORCE|`, and MLDPRNT prints it under
  `PEAK_GRID_F`.
- Sample numbering unified to **1-based** (NASTRAN convention): MLDPRNT now prints
  `critical sample=k of n`, matching the f06 `SAMPLE` column and `CRITICAL SAMPLE = k`. The
  exported critical-sample BDF header states the same `k of n`.
- `CLOSURE_F`/`CLOSURE_M` are **kept** in the MLDPRNT table and relabelled in the docstring as
  what they are — a solution-quality diagnostic, useful but not a severity metric.

**Key decision — peak per-grid net force, not peak bar load.** Bar load is closer to what a loads
team sizes to, but combining axial/shear/torque/bending into one scalar needs section properties
and would have silently ignored whichever component was left out. Per-grid net force is
unit-consistent, needs no arbitrary combination, and is the quantity the export actually contains.

**Test/Acceptance:** five new gates in `tests/aero/test_maneuver_qs.py`, all run on a maneuver with
a real transient (a held-at-trim run is a fixed point and cannot distinguish a correct selector
from a broken one — the new fixture asserts the run has a transient to rank): `crit_index` equals
the `peak_grid_force` argmax; the f06 header number, the `<-- CRITICAL` row and the printed column
argmax agree and the column equals `peak_grid_force` per row; MLDPRNT numbering matches the f06;
the MLDPRNT column matches the selector metric; and the exported card set is the sample the f06
names — with a companion assertion that some *other* sample would have produced different cards,
so that check has teeth.

---

### DEF-M7 — f06 maneuver time-history header misaligned 2 characters per column ✅ COMPLETE (2026-08-01)

**Objective:** `f06_writer.py:716-719` built header cells as `f"  {label:>13}"` (15 characters) and
the three fixed trailing headers at 15, over data cells of `_fmt` = `f"{val:13.6E}"` (13). The `T`
header was 12 over a 13-wide datum. With the 5 trim variables of the HA144A deck the
`FZ-AERO`/`MY-AERO` headers sat a full column off their data.

**Deliverable:** one module-level `_FIELD_W = 13` that `_fmt` itself formats against, with the
header row and the data rows both laid out on it, so the two cannot drift apart again. Header text
is kept under `_FIELD_W` so adjacent cells never abut (the first attempt used a 13-character
`PEAK |GRID F|`, which was correctly aligned but ran straight into `MY-AERO`; shortened to
`PEAK GRID F`).

**Test/Acceptance:** `test_f06_time_history_columns_align_with_their_headers` — the header line and
a data row are the same length, and the 13 characters ending where each of `FZ-AERO`/`MY-AERO`
ends parse as a float. Verified visually on the shipped `ha144a_fullspan_mloads` run.
