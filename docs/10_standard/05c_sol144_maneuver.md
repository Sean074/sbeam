# Aeroelastics Phases C + G0 — SOL 144 Static Aeroelastics & Maneuver Loads

Phase C + G0 code standard: the SOL 144 trim solve, stability derivatives, divergence,
output/exports, transient maneuver loads (MLOADS), and monitor points. Part of the
aeroelastics guide — see [`05_aeroelastics.md`](05_aeroelastics.md) for the architecture
overview, validation status, and supported-card table; [`05a_aero_vlm.md`](05a_aero_vlm.md)
for the Phase A aerodynamics; [`05b_splining.md`](05b_splining.md) for the Phase B splines.

---

## Phase C — SOL 144 Static Aeroelastics

### Governing Equation

The flexible static aeroelastic equilibrium on the SPC-free a-set:

```
(K_aa − q · Q_aa) · u_a  =  q · f_g  +  f_struct
```

where:
- `K_aa` — structural stiffness reduced to the a-set (SPC + RBE3 applied)
- `Q_aa` — flexible aerodynamic stiffness `G_dispᵀ S_kj (A_jj*)⁻¹ D_jk G_slope`
- `f_g` — baseline aero load from camber/twist/incidence normalwash (from `build_fg`)
- `f_struct` — structural load from the BDF `LOAD` set

Step 50 solves this equation without trim variables (Steps 51–52 add trim card
parsing and the full SOL 144 solve with `Q_ax·δ_x`).

> **`LOAD` applies to the restrained static path only.** `run_aeroelastic_static`
> combines a `LOAD` set with the aero load as above. The **trim** RHS
> (`run_sol144_trim`) is aero + inertia only — there is no `f_struct` term — so a
> subcase carrying both `TRIM` and `LOAD` now **raises** rather than silently
> ignoring the load request (DEF-M4). Adding `f_struct` to the trim RHS is a
> capability change, not a defect fix: on a free-flight SUPORT trim it enters the
> force balance and changes what `maneuver_closure` means. Backlogged separately.

---

### `coupling.py` — Phase C Coupling Functions

Three pure linear-algebra functions in `sbeam/aero/coupling.py` implement the
Phase C matrix chains. They operate on already-built AeroModel quantities.

#### `build_qaa(aero, g_load, g_slope) → np.ndarray`

```
Q_aa = G_load^T  S_kj  (A_jj*)^-1  D_jk  G_slope    shape (n_g, n_g)
```

| Arg | Shape | Description |
|-----|-------|-------------|
| `aero` | — | AeroModel (provides `skj`, `ajj_inv_corr`, `djk`) |
| `g_load` | (3n_box, n_g) | Force-transfer spline from `build_spline_operators` (`g_disp` + Step 64 load injection) |
| `g_slope` | (n_box, n_g) | Slope spline from `build_spline_operators` |

Every `gᵀ·f` transfer in the SOL 144 / maneuver chain — `Q_aa`, `f_g`, `Q_ax`,
`grid_loads`, the modal GAFs — uses `g_load`, so `SPLINE0` body-panel and
un-splined-box forces reach the force balance and the exports (Step 64 / DEF-M1).
`g_disp` remains the kinematic operator used for displacement recovery only.

Returns the **g-set** Q_aa (dense, unsymmetric in general). Reduction to the
a-set is done downstream via the shared `assembly.reduction.reduce_to_aset`
path (wrapped by `sol144._build_qaa_aset`).

#### `build_fg(aero, g_load) → np.ndarray`

```
f_g = G_load^T  S_kj  (A_jj*)^-1  w_g               shape (n_g,)
```

Baseline aero load from the `W2GJ` normalwash at zero elastic deflection.
The trim/static RHS contribution is `q · f_g`.

#### `build_gaf(qaa, phi) → np.ndarray`

```
Q_hh = Phi^T  Q_aa  Phi                              shape (n_modes, n_modes)
```

Modal generalized aerodynamic force (GAF) matrix. `phi` and `qaa` must be on
the same DOF set. Used by the modal-truncation ROM in `sol144._solve_rom`.

---

### `sol144.py` — Step 50 Aeroelastic Static Solver

**Module:** `sbeam/solver/sol144.py`

#### Public entry point

```python
from sbeam.solver.sol144 import run_aeroelastic_static

result = run_aeroelastic_static(
    bulk,           # BulkData
    subcase,        # SubcaseControl (uses spc_sid, load_sid, method_sid)
    aero,           # AeroModel — must have g_slope, g_disp and g_load populated
    q,              # float — dynamic pressure in consistent units
    use_rom=False,  # bool — enable modal-truncation ROM with mode-acceleration
    sol103_result=None,  # Optional[Sol103Result] — pre-computed modes for ROM
)
# result: Sol144Result
```

`aero` must be built with `build_aero_model(bulk, grid_index=grid_index)`
to populate the spline operators; raises `ValueError` otherwise.

When `use_rom=True` and `sol103_result is None`, SOL 103 is run internally using
`subcase.method_sid` (raises if `method_sid` is None).

#### Private helpers

| Function | Purpose |
|----------|---------|
| `_build_qaa_aset(bulk, aero, grid_index, spc_sid, f_g_full)` | Reduce g-set Q_aa and K_aa to the a-set via RBE3 + SPC partition |
| `_solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_dofs)` | Dense direct solve of `(K_aa − q·Q_aa)·u_a = f_aa` |
| `_solve_rom(K_aa, Q_aa, f_aa, q, phi_free)` | Modal-truncation ROM solve |
| `_mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)` | Mode-acceleration correction |

#### `_build_qaa_aset` algorithm

Since Step 59 the RBE3 + SPC reduction itself lives in
`sbeam/assembly/reduction.py` (`reduce_to_aset(bulk, grid_index, spc_sid) →
AsetReduction`), shared by SOL 103, SOL 144, and `maneuver_qs`.
`_build_qaa_aset` composes it for the (K, Q, f) triple:

```
1. Q_gg = build_qaa(aero, aero.g_load, aero.g_slope)    # (n_g, n_g) dense
2. K_gg = assemble_global_stiffness(bulk)                  # (n_g, n_g) sparse CSR
3. red  = reduce_to_aset(bulk, grid_index, spc_sid)        # T + a-set partition
4. K_aa = red.reduce_matrix(K_gg, dense=True)              # (n_a, n_a) dense
5. Q_aa = red.reduce_matrix(Q_gg)                          # (n_a, n_a)
6. f_aa = red.reduce_vector(f_g_full)                      # if supplied
7. free_dofs = red.free_dofs   # g-set DOF indices for the a-set rows/cols
```

`AsetReduction` also provides `reduce_rect` (rectangular column blocks: Q_ax,
M_ax), and `expand_to_g` (a-set → g-set scatter through the RBE3/RBAR `T`
matrix so slave DOFs follow their masters). `reduce_matrix` preserves input
sparsity when no dependent DOFs exist (SOL 103's sparse path); `dense=True`
forces the dense result the SOL 144 solves need.

Rationale for always-dense K_aa in SOL 144: adding dense Q_aa to sparse K would
require a mixed-format code path; converting K to dense at this point is
consistent with the RBE3 dense-fallback precedent in `sol101.py` (Risk KC1 from
the backlog).

`sol144._compute_aset_data` (a tuple-returning wrapper around `reduce_to_aset`) was
removed once its last caller went through `reduce_to_aset` directly; call
`reduction.reduce_to_aset` / `reduction.expand_to_g` from new code.

**SPC on a rigid-dependent DOF is fatal (DEF-M9).** A DOF eliminated by an
RBE2/RBAR/RBE3 has no equation left to constrain, so `reduce_to_aset` raises naming the
grid, the DOF and the owning element. It used to filter such DOFs out silently: the
constraint never applied, the DOF stayed free to follow its master, and no reaction was
reported. NASTRAN fatals on the same m-set/s-set overlap. Since DEF-R5, **SOL 101 also
goes through `reduce_to_aset`** (it previously hand-rolled the reduction, bug included),
so all four solvers inherit the one check.

#### Mode-acceleration recovery

For a truncated modal basis `Φ` (first `n_m` columns), the mode-displacement
estimate `u_md = Φξ` leaves a static residual. The mode-acceleration correction
applies the pure structural flexibility to that residual:

```
residual = f_aa - (K_aa - q·Q_aa) · Φξ
u_a      = Φξ  +  K_aa⁻¹ · residual
```

`K_aa⁻¹ · residual` is computed cheaply via `lu_solve(k_aa_lu, residual)` where
`k_aa_lu` is the LU factorization stored in `Sol144Result.k_aa_lu`. When all modes
are retained the residual is zero and the correction vanishes identically.

---

### `Sol144Result` — Step 50 Result Dataclass

```python
@dataclass
class Sol144Result:
    displacements: np.ndarray          # (n_dofs,) full g-set; SPC DOFs zeroed
    bar_forces: dict                   # {eid: BarForce}
    bar_stresses: dict                 # {eid: BarStress}
    q_aa: np.ndarray                   # (n_a, n_a) flexible aero stiffness on a-set
    q: float                           # dynamic pressure used in this solve
    free_dofs: list                    # a-set DOF indices into the g-set (len = n_a)
    k_aa_lu: tuple                     # (lu, piv) from lu_factor(K_aa); reused by Step 52
    modal_coords: Optional[np.ndarray] # (n_modes,) ξ; None when use_rom=False
    phi_free: Optional[np.ndarray]     # (n_a, n_modes); None when use_rom=False
    k_hh: Optional[np.ndarray]         # (n_modes, n_modes) Φᵀ K_aa Φ
    q_hh: Optional[np.ndarray]         # (n_modes, n_modes) Φᵀ Q_aa Φ (modal GAF)
```

`k_aa_lu` is stored for Step 52 reuse: the pure structural stiffness factorization
is needed for the mode-acceleration correction in each trim subcase without
re-factorizing K_aa.

---

### V-C3 Acceptance Criteria (Step 50)

All tests in `tests/aero/test_step50_qaa.py`:

| ID | Test | Tolerance |
|----|------|-----------|
| V-C3-1 | `Q_aa.shape == (n_a, n_a)` and `K_aa.shape == (n_a, n_a)` | exact |
| V-C3-2 | `run_aeroelastic_static(q=0)` displacements ≡ `run_sol101` | 1e-10 |
| V-C3-3 | ROM (all modes) + mode-acceleration ≡ direct solve | 1e-6 |
| V-C3-4 | At n_modes/4: MA CBAR root-moment error < MD error | MA < MD always |
| V-C3-5 | `lu_solve(k_aa_lu, K_aa @ e1) ≈ e1` | 1e-10 |

---

## Step 51 — Trim Card Set Parsing

Step 51 adds BDF-parsing support for the static aeroelastic trim card set. No solver is
added; these cards are parsed, stored in `BulkData`, and cross-referenced so that the
Step 52+ trim solver can consume them directly.

### Data model

All trim objects live in `sbeam/model/aero.py` and are stored in `BulkData` as:

| `BulkData` field | Type | Key |
|-----------------|------|-----|
| `aestats` | `dict` | `{id: Aestat}` |
| `aesurfs` | `dict` | `{id: Aesurf}` |
| `aelists` | `dict` | `{sid: Aelist}` |
| `trims` | `dict` | `{sid: Trim}` |
| `divergs` | `dict` | `{sid: Diverg}` |
| `trimvars` | `dict` | `{id: Trimvar}` |
| `trimobjs` | `dict` | `{sid: Trimobj}` |
| `trimcons` | `dict` | `{sid: list[Trimcon]}` |

### Cross-reference validation (in `parse_bulk_data()`)

1. **AESURF → AELIST**: `alid1` (and `alid2` if non-zero) must exist in `bulk.aelists`.
2. **AELIST → CAERO1 box range**: every element ID must fall within
   `[caero.eid, caero.eid + nspan×nchord − 1]` for at least one CAERO1.
3. **TRIM label**: every key in `trim.vars` must be defined by an AESTAT or AESURF card.

### DOF-count diagnostic

After cross-reference validation, `parse_bulk_data()` emits `UserWarning` for degenerate
trim conditions:

- **Fully prescribed** (`len(free) == 0`): all trim variables have prescribed values — no
  DOFs remain for the solver.
- **Over-determined without objective** (`len(free) > len(prescribed)` and no TRIMOBJ
  present): the system cannot be solved as a square system; a TRIMOBJ card is required to
  specify the weighted least-squares objective.

### Case control

SOL 144 subcases may declare:

```
SOL 144
SUBCASE 1
  TRIM    = 10
  DIVERG  = 20
  MASSSET = 30
```

`SubcaseControl` gains `trim_sid` and `diverg_sid` fields (both `Optional[int]`, default `None`),
plus `massset_sid` for the Step 60 payload / mass case (see
[Mass cases](#mass-cases--masset-payload-conditions-step-60)).

### Over-determined trim (sbeam-defined cards)

When the number of free trim variables exceeds the number of equilibrium equations,
the problem is over-determined. sbeam uses three sbeam-defined cards to handle this:

| Card | Role |
|------|------|
| `TRIMVAR` | Per-variable initial guess and bounds (`lb`, `ub`) |
| `TRIMOBJ` | Weighted-L2 objective `J = Σ wᵢ·δᵢ²` over the listed labels |
| `TRIMCON` | Scalar inequality constraints (`LE` or `GE`) |

These cards are consumed by `run_sol144_trim` when `n_free > n_suport` — see
**Over-determined trim solve** below. The case-control `TRIMOBJ = sid` selects the objective
for a subcase (`SubcaseControl.trimobj_sid`); a single defined `TRIMOBJ` is used by default.

---

## Step 52 — SOL 144 Trim Solver (CLOSED 2026-06-14)

`solver/sol144.py:run_sol144_trim(bulk, subcase, aero)` implements the **determined** trim
case (`n_free_labels == n_SUPORT_DOFs`) and the **over-determined** (redundant-control) case
(null-space reduction + weighted-L2 `TRIMOBJ`/`TRIMCON`/`TRIMVAR`, gate V-C4):

1. Build `D_jx` (per-box normalwash per unit trim label: ANGLEA `−n_z`, SIDES `−n_y`, PITCH
   `−(2/cref)(x−x_ref)`, ROLL `−(2/bref)·y`, YAW `−(2/bref)(x−x_ref)·n_y` (vertical-surface
   sidewash), URDD1–6 `0`, AESURF `−(ĥ × n)·x̂·eff` about the `cid1` hinge axis ĥ — reducing to
   `−n_z·eff` for a spanwise hinge) and `Q_ax = G_dispᵀ S_kj A_jj*⁻¹ D_jx` on the g-set.
2. Reduce `Q_ax`, `K`, and the RHS (baseline `q·f_g` + prescribed-variable aero + URDD
   inertial load) to the a-set via the same RBE3 + SPC partition as SOL 101.
3. Partition the a-set into l-set / r-set (SUPORT DOFs), set `u_r = 0`, and solve the
   Schur-complement system for the free trim variables and `u_l`.
4. Recover CBAR forces/stresses, rigid and (analytic) restrained derivatives, total CL/CM,
   per-AESURF hinge-moment derivatives (`_compute_hinge_moments`, moment of the box forces about
   each control's `cid1` hinge axis), and return a `Sol144TrimResult`.

The Schur partition structure is equivalent to the MSC r-set/l-set method. The review-era
defects (AE1–AE7, AE9, AE10) are all resolved; the HA144A benchmark passes on both subcases
within the ≤1%-full-scale gate (measured ≤0.4% FS — see "Validation status & known
limitations" at the top of this document). Step 52 closed 2026-06-14 with the
over-determined trim and the lateral rate derivatives (`C_lp`/`C_nr`/`C_lβ`); the only open
derivative work is the unrestrained (mean-axis) column, tracked as **AE8b** in the backlog.

### Trim acceptance gates — V-AE1f and V-AE1d (`tests/aero/test_ae1_fullspan.py`)

The HA144A trim is gated on the full-span deck (`sample/ha144a_fullspan_sbeam.bdf`,
SYMXZ=0, whole-airplane = 16000 lb) — the parity ground truth since half-span support
was removed (AE1 Step D).

- **V-AE1f** — SC1 ANGLEA/ELEV within a shared ~2% relative tolerance, lift = 16000 lb,
  mirrored-spline rigid-pitch reproduction, and emergent symmetry (antisymmetric DOF ≈ 0,
  L/R wing tips match). SC2 is sign/increment-gated only.
- **V-AE1d** (AE1 Step F, closed 2026-06-13) — the same SC1/SC2 trim, but each TRIM variable
  is gated against its **full-scale physical range**, not relative to its NASTRAN target:
  - SC1 **live, relative**: ANGLEA within 1.5% (actual +1.1%; not chased — no bulk re-tuning),
    ELEV within 1%, lift within 1% of 16000 lb. (SC1 is rigid-dominated with a trim point well
    away from zero, so a relative tolerance is meaningful there.)
  - SC2 **live, %-full-scale**: ANGLEA within 0.3° (1% of the 30° AoA stall band), ELEV within
    0.4° (1% of the 40° elevator throw). A relative tolerance is meaningless for SC2 — its trim
    AoA passes through ~0 as q rises, so a fixed absolute error reads as an exploding percentage
    (the old gate saw "+136%" for a 0.107° miss). SC2 actual: ANGLEA 0.36% FS, ELEV 0.23% FS,
    both inside the gate. The residual ~0.1° is a **q-invariant common-mode offset** — the same
    absolute error already accepted at SC1, not a high-q flexible defect; its optional root-cause
    is tracked as MINOR AE8a. (AE1 Step G — the analytic restrained derivatives — is closed and
    did **not** move SC2: the derivatives are an output, not the trim driver.)

### Coupling-path cross-check — V-AE3 (`tests/aero/test_vae3_cross_check.py`)

An INDEPENDENT confirmation that the force/moment coupling path is correct, closing the AE13
blind spot where every aero gate was only self-consistent (a common scale error or factor-of-2
parity bug would pass). The box force/moment is built two ways on the same model:

- **Path A (coupling)** — the SOL 144 chain: `f_box = skj @ (ajj_inv_corr @ w)` with `w` the
  `D_jx` ANGLEA column (`= −n_z`); totals via `pitch_moment`.
- **Path B (independent)** — `solve_rigid_cl` (`sbeam/aero/vlm.py`), which rebuilds its own AIC
  and Kutta–Joukowski resultants in a separate module; at unit q `Fz = CL·S_ref`,
  `My = CM·S_ref·c_ref`.

Both paths are driven with the SAME alpha-only normalwash (W2GJ baseline `wg` excluded so the
excitations match) and the SAME effective Mach (`bulk.aeros.mach`). On HA144A (full-span, M=0.9)
and `val_vlm_rect_ar8` (planar, M=0) the Path-A totals match the `solve_rigid_cl` resultants to
machine precision; a parity proxy (halving `f_box`) fails the 1% gate by ~2×, confirming the gate
discriminates — unlike `test_phase_b.py::test_tz_sum_vs_cl_magnitude`'s
`min(err_full, err_half) < 0.02`, which accepts both the correct lift and exactly half of it.

### Restrained derivatives — analytic Schur form (`tests/aero/test_ae1_restrained_derivs.py`)

`_compute_restrained_derivs` returns the **exact analytic** restrained stability derivatives
from the Schur factorisation (AE1 Step G): per label δ, `∂u_l/∂δ = K_ll⁻¹·C_ax_l` (K_ll
already carries the `q·Q_aa` aero feedback), then the linear `∂w → ∂γ → ∂f_box` chain gives
`CZ = Σ∂Fz/∂δ / S_ref` and `CMY = pitch_moment(∂f_box)/(S_ref·c_ref)`. This replaced the
prior finite-difference hybrid (AE8); because the trim is linear in δ the two agree to
round-off. Gate V-AE1e (partial): rigid columns unchanged (CZα 5.071, CMα −2.871), restrained
CZα 5.112 vs NASTRAN Table 7-1 5.103 (q=40) within 1%. The unrestrained (mean-axis) derivative
set and the remaining Table 7-1 restrained columns are still open on **AE8b** (backlog Step AC2).

### Lateral / directional rate derivatives — `C_lp`, `C_nr`, `C_lβ` (Step 52)

`compute_rigid_derivs` and `_compute_restrained_derivs` emit the roll/yaw **moment**
coefficients alongside the longitudinal `CZ`/`CMY`:

```
CMX = Mx / (S_ref · b_ref)    rolling moment   → C_lp = ∂CMX/∂ROLL,  C_lβ = ∂CMX/∂SIDES
CMZ = Mz / (S_ref · b_ref)    yawing moment    → C_nr = ∂CMZ/∂YAW
```

`Mx`, `Mz` are the full 3-component cross-product resultant `Σ(r_box − ref) × F_box`
(`aero_moment_resultant`), about the AERO reference (`AEROS.RCSID` origin), so they carry the
side force `Fy` of any canted (±Γ dihedral) panel — the dihedral effect `C_lβ` falls out of the
Step 58 box normals automatically. The quasi-steady rate normalwash columns (ROLL, YAW) are
built in `build_djx` (no DLM): roll rate `Δα(y) = p·y/V∞` and yaw-rate sidewash act through the
local box geometry/normal. **Sign convention:** moments are in sbeam's z-up / y-starboard aero
frame (the V-C-DIH frame), so the damping derivatives carry that frame's handedness rather than
a textbook z-down body-axis sign; the magnitudes and the ±Γ `C_lβ` symmetry are the
convention-independent content. Gate: `tests/aero/test_lateral_derivs.py` (V-LAT) — roll-rate
damping magnitude in the lifting-line band, clean ROLL↔Fz/My/Mz decoupling on a planar wing,
and the `C_lβ` sign-flip between `val_vlm_dihedral`/`val_vlm_anhedral` (zero on the planar deck).

### Over-determined trim solve — redundant controls (Step 52)

When `n_free > n_suport` (more free trim variables than equilibrium equations, e.g. redundant
control effectors), `run_sol144_trim` dispatches to `_solve_trim_overdetermined`. The trim
equilibrium `schur_A·δ = schur_b` (n_suport equations) is satisfied **by construction** through a
null-space reduction `δ = δ_p + N·z` (δ_p = least-norm equilibrium solution, `N = null(schur_A)`);
the redundancy coordinate `z` is then chosen by minimising the convex weighted-L2 TRIMOBJ
objective `Σ wᵢ·δᵢ²` subject to the TRIMCON inequalities and TRIMVAR bounds (SLSQP on the small,
well-scaled reduced problem). The null-space form avoids handing the optimiser the stiff
equilibrium equality (whose rows carry structural-force magnitudes O(10³) that swamp the O(0.1)
trim variables). Because the objective is convex the optimum is initial-guess insensitive (KC6);
TRIMVAR `init` only seeds the warm start. `Sol144TrimResult.trim_mode` reports `"determined"` or
`"over-determined"` and is echoed in the f06 TRIM VARIABLES block. Gate: V-C4
(`tests/aero/test_trim_overdetermined.py`) — `min(PITCH²)` reproduces the determined ANGLEA/ELEV,
a TRIMCON forces its bound active, and the result is start-point independent.


---

## Running SOL 144 & Output (AE10 + Step 56)

A SOL 144 deck runs end-to-end from the CLI:

```
sbeam ha144a.bdf
# → Written: ha144a.f06
# → Written: ha144a.aero_loads.bdf
```

**Dispatch (`main.py`, AE10).** Unlike the two-arg SOL 101/103 path, the SOL 144 branch
builds `grid_index` and an `AeroModel` (`build_aero_model`, which rejects `SYMXZ≠0`
half-span decks), seeds an `AeroCache` shared across subcases, and calls
`run_sol144_trim(bulk, subcase, aero, aero_cache=cache)` per TRIM subcase.

**f06 output (`build_f06_sol144_text` / `write_f06_sol144`).** Per subcase:

| Block | Source |
|-------|--------|
| TRIM VARIABLES (free vs prescribed) | `result.trim_vars` + the TRIM card |
| STABILITY DERIVATIVES (rigid + elastic restrained) | `result.rigid_derivs`, `result.restrained_derivs` |
| AERODYNAMIC TOTALS (CZ body / CL wind / CMY) | `result.total_cl` (body CZ), `result.total_cl_wind` (wind CL = CZ·cosα − CX·sinα at trim α), `result.total_cm` |
| AERODYNAMIC DIVERGENCE (`q_div`, `q/q_div`) | `result.q_div` (restrained l-set; see below) |
| DISPLACEMENT / BAR FORCES / BAR STRESSES | shared helpers, reused from the SOL 101 writer |
| AERODYNAMIC BOX PRESSURES AND FORCES | `result.box_cp`, `result.box_forces` — **only when the subcase requests `AEROF` or `APRES`** |

**Divergence diagnostic.** `sol144._divergence_dynamic_pressure(K_ll, Q_ll)` returns the
single critical divergence dynamic pressure — the reciprocal of the largest positive-real
eigenvalue of `K_ll⁻¹ Q_ll` on the **restrained l-set** (the free-flight SUPORT `K_aa` is
singular, so the full a-set is not used). `None` when the model does not diverge. It is
emitted in every trim subcase's `AERODYNAMIC DIVERGENCE` block.

**Divergence sweep (`DIVERG` card, Step 55).** A SOL 144 subcase with `DIVERG = sid`
runs `sol144.run_sol144_diverg`, which solves the same restrained-l-set eigenproblem
`K_ll φ = q·Q_ll φ` but returns the lowest `NROOTS` positive divergence pressures and
their **mode shapes** at each Mach on the card:

- `_divergence_roots(K_ll, Q_ll, nroots)` solves `(K_ll⁻¹ Q_ll) x = (1/q) x` (dense
  generalised solve, mirroring `sol103._solve_modes_dense`), keeps only **real, strictly
  positive** `1/q` (selection rule for the unsymmetric `Q_ll`; spurious negative/complex
  roots are discarded), and sorts ascending in `q`. Its lowest root reproduces
  `_divergence_dynamic_pressure` exactly.
- Each l-set eigenvector is scattered to the a-set (SUPORT DOFs zero) and expanded to the
  g-set via the RBE3/RBAR `T` matrix (`_expand_to_g`), then max-abs normalised for output.
- With the `RHOREF` sbeam-extension density on the card, each root reports
  `V_div = √(2·q_div/ρ)`.
- The sweep depends only on `K_aa`/`Q_aa`, so a DIVERG subcase needs no TRIM card; a
  subcase carrying both runs the trim and the sweep. Output: `Sol144DivergResult`
  (`mach_results → DivergMachResult → DivergRoot`), rendered by
  `f06_writer.build_f06_sol144_diverg_text` as a per-Mach `AERODYNAMIC DIVERGENCE` table
  (root no., `Q-DIV`, `V-DIV`) plus a divergence mode-shape block per root.

**Flight-load export (`results/load_export.py`).** `write_aero_load_cards` writes
`<stem>.aero_loads.bdf` — comma free-field `FORCE`/`MOMENT` cards (unit scale factor;
direction components carry the physical load) from `result.grid_loads` (`g_load^T·q·f_box`),
one card block per subcase with `SID = subcase_id`. By spline force/moment conservation the
set sums to the trimmed lift/moment.

**Field format (DEF-M6).** Every real in an exported card is written by
`parser/bdf_field.fmt_real8`, which fits it into the NASTRAN **8-character** data field.
Free field does not exempt a card from that width — a strict reader truncates each
comma-delimited field to its first 8 characters, which would turn `4.715932E+03` into
`4.715932`. `fmt_real8` builds both a fixed-point spelling (`4715.932`) and a NASTRAN
implicit-exponent spelling (`4.716+3`) and keeps whichever reproduces the value more
closely; `bdf_field.parse_real` is the matching read side, which `bdf_reader._to_float`
delegates to so the two cannot drift. Non-finite values raise rather than being written.
Precision is therefore bounded by the field width: 6-7 significant figures across the
physical load range, fewer for very large or very small magnitudes, and one fewer for a
negative value (the sign costs a character). This applies to every load-card export below,
since they share `emit_force_moment_cards`.

**Balanced maneuver loads & inertia relief (Step 53).** Each balanced maneuver is a `TRIM`
subcase with prescribed `AESTAT` accelerations/rates — a load factor maps to `URDD3 = −n_z·g`
(`sbeam/model/maneuver_presets.load_factor_to_urdd3`; gravity folded into the load factor,
NASTRAN convention). After the trim solve the inertial g-set load `M_ax·a` (final trim URDD,
prescribed + solved-free) is recovered as `result.inertial_loads` and added to the aero load to
give `result.net_loads` — the net deliverable for stress and the non-zero inertia column for
MONPNT3. `write_maneuver_load_cards` writes these as `<stem>.maneuver_loads.bdf`.
`result.maneuver_closure` is the body-frame 6-resultant of the net load; for a free aircraft
(SUPORT, no SPC) it must balance to ≈ 0 (a non-zero residual warns — gravity/mass-model guard,
KC9). Recipes: symmetric pull-up/push-over (prescribe `URDD3`, `PITCH=0`), steady roll
(prescribe `ROLL` rate, `URDD4=0`; aileron free), steady sideslip (prescribe `SIDES`, `YAW=0`;
rudder free). Gated by **V-C5** (`tests/aero/test_maneuver_loads.py`).

**Transient maneuver loads — Phase G0 increment 1 (DLM-free quasi-steady).** A SOL 144 subcase that
carries an `MLOADS = sid` request runs `solver/maneuver_qs.py` instead of the static trim. It
time-integrates the elastic response to a prescribed (open-loop) pilot-command history, starting
from a Step 53 balanced trim as the initial condition, and recovers the net (aero + inertial)
maneuver load at each output time.

- **Cards (ZAERO `MLOADS` family, `sbeam/model/maneuver.py`):** `MLOADS` is the driver and
  references `MLDTRIM` (the initial-condition `TRIM` sid), `MLDTIME` (`t0/tend/dt/tout`), `MLDCOMD`
  (one or more `(label, TABLED1)` command pairs — any AESTAT/AESURF label; uncommanded labels hold
  their trim value), and `MLDPRNT` (ASCII output request). `TABLED1` is the general tabular
  time→value function (linear interpolation; held/constant extrapolation beyond the table, so a
  command ramps to a deflection and then holds).
- **Method:** like the trim, the SUPORT r-set is held at the mean axis (`u_r = 0`) and the elastic
  l-set is integrated with Newmark-β (β=¼, γ=½):
  `M_ll ü + C_ll u̇ + (K_ll − q·Q_ll) u = f_aero_l + q·Q_ax_l·δ(t) + M_ax_l·a(t)`. The steady VLM is
  re-evaluated at the instantaneous deformation and trim-variable state each step (Level-1
  quasi-steady, `Ω×r` rate columns); no DLM, no apparent mass, no lag. Holding the command at the
  trim value reproduces the Step 53 balanced load to machine precision (the l-set is integrated
  directly, so this identity is exact). The initial acceleration is taken as zero (the run starts at
  static equilibrium), so a singular lumped `M_ll` is tolerated.
- **Convention (increment 1):** open-loop *prescribed-kinematics* — every trim variable is prescribed
  (commanded or held). The net load closes to ≈ 0 when the commanded histories form a consistent
  (trimmed) set; the per-step closure residual otherwise equals the instantaneous rigid-body net
  force. Re-solving the free rigid-body variables each step (free-flight self-balancing), the modal
  transient solver (Step 62), unsteady corrections, and a closed-loop control layer are Phase G0
  follow-ons. This solver parses `NMODES`/`METHOD`/`ZETA` and warns that it ignores them.
- **Critical sample (DEF-M5):** one severity metric, `results.peak_grid_force` — the maximum over
  grids of the net (aero + inertial) **translational force magnitude** at that grid. It selects the
  critical sample, fills the f06 `PEAK GRID F` and MLDPRNT `PEAK_GRID_F` columns, and labels the f06
  header (`PEAK |NET GRID FORCE|`); sample numbering is **1-based** everywhere, including MLDPRNT.
  It is deliberately neither the load-closure resultant (`closure`, the aero/inertia balance
  residual — ~0 on a balanced maneuver, so ranking by it ranks numerical noise) nor
  `max|net_loads|` over all six DOFs (which mixes force and moment units). `CLOSURE_F`/`CLOSURE_M`
  remain in the MLDPRNT table as the balance diagnostic they are.
- **Output (`results/maneuver_output.py`):** an MLDPRNT ASCII time-history table
  (`<stem>.mldprnt.txt`: time, commands, aero `Fz`/`My`, closure norms, peak grid force) and the
  critical-sample net-load `FORCE`/`MOMENT` export (`<stem>.maneuver_qs_loads.bdf`).
  The f06 gains a transient-maneuver block per MLOADS subcase
  (`f06_writer.py::build_f06_sol144_maneuver_text`, AC5: run summary, time-history table with
  critical-sample marker, critical-sample closure/displacement/CBAR detail). Header and data cells
  of the time-history table share one column width (`f06_writer._FIELD_W`, DEF-M7). The viewer offers
  the two ASCII/BDF exports as download buttons on the maneuver results view. Sample decks:
  `sample/ha144a_fullspan_mloads.bdf` (ELEV ramp pitch-up on the HA144A full-span model) and
  `sample/cessna210_flagship_mloads.bdf` (Step 65 — the same maneuver on the corrected,
  splined, monitored realistic-airplane flagship).
- **Gates (`tests/aero/test_maneuver_cards.py`, `tests/aero/test_maneuver_qs.py`):** card round-trip +
  validation; G0→Step 53 machine-precision identity; quasi-static settling to the new balanced trim
  (closure → 0, lift = `n_z·W`); per-step closure bounded; MLDPRNT + critical-load export round-trips.
- **Validity:** low reduced frequency `k = ω·c_ref/2V ≲ 0.05–0.1` (slow maneuvers); higher-rate inputs
  need the Phase G0 unsteady corrections or the Phase D DLM.

### Free-free maneuver modal basis (Step 61)

The basis layer of the Steps 61–63 modal architecture (`sbeam/solver/modal_basis.py`). It builds,
once per job, the free-free basis `Φ = [Φ_r | Φ_e]` and every h-set operator that depends only on
geometry, Mach and the baseline mass case. **Nothing time-integrates it yet** — the modal transient
solver that consumes it lands with Step 62; today the objects are exercised by their gates only.

- **Deck input:** `MLOADS ... NMODES METHOD ZETA` (fields 7–9) selects the retained *elastic* mode
  count (rigid modes are always all retained), the EIGRL for the basis eigensolve (`0` = internal
  all-modes default), and a uniform elastic modal damping ratio. The `TRIM` card that seeds the run
  must carry the `RHOREF` pseudo-label — it is the only source of the true airspeed `V = √(2q/ρ)`
  the rate terms need. Example:
  `TRIM, 1, 0.9, 40.0, RHOREF, 2.3769-3, PITCH, 0.0` and `MLOADS, 1, 1, 1, 1, 1, 12, 900, 0.02`.
- **What is built:** `build_rigid_modes` (the single owner of the geometric rigid-body basis —
  `designs/rbmref_card.md` reuses it), `build_maneuver_basis → ManeuverBasis` (`Φ`, `M_hh`, `K_hh`,
  `M_rr`, elastic frequencies, the rigid→trim-label map, diagnostics), and
  `build_hset_gafs → HsetGafs` (`Q_hh` via `coupling.build_gaf`, `Q_hx`/`Q_hc`, the rigid-rate
  `B_hh`, `f_h0`, `C_hh`). All aerodynamic operators are dynamic-pressure free.
- **Shared assembly:** `assemble_aset_operators` is now the single a-set assembly for both maneuver
  paths (it is what `maneuver_qs._assemble_operators` calls), on top of the Step 59
  `assembly/reduction.reduce_to_aset`.
- **Massless DOFs:** a CONM2-only model's rotational DOFs are statically (Guyan) condensed out
  before the eigensolve — exact, since those equations carry no mass. Do **not** substitute a
  regularise-and-filter approach: the regularised eigenvectors carry huge amplitudes on the massless
  DOFs and leave the basis non-orthogonal against the true `M_aa` while still reporting unit
  generalized mass. See theory §7.8.
- **Gates (`tests/solver/test_modal_basis.py`):** `ΦᵀM_aaΦ` block diagonal with an identity elastic
  block; `M_rr` = GPWG rigid mass about the SUPORT point; the `M_ax = −M_aa Φ_r` identity;
  `Q_hh`/`K_hh` equal to the shipped static-ROM projections for the same basis; `K_hh` rigid
  rows/columns ≈ 0; the rigid-vector round trip through the RBE3/RBAR transformation; NMODES/METHOD
  truncation; and the `B_hh` rigid-rate columns against their exact rescaling of `Q_hx`
  (plunge `−1/V·ANGLEA`, pitch `c_ref/2V·PITCH`). `build_dj_rigidrate` has its own column-rescale
  gate in `tests/aero/test_integration.py`.
- **One mass model (Q4 / DEF-M3, 2026-07-31):** `M_ax` is *defined* as `−M_gg Φ_r` — the same
  consistent `assemble_global_mass` the elastic equations use, times the geometric rigid vectors
  from `assembly/rigid_body.py`. The `M_ax = −M_aa Φ_r` identity is therefore definitional rather
  than incidental (`red.reduce_rect` is `Tᵀ·` and `T Φ_r_a = Φ_r_g`), and everything
  `assemble_global_mass` knows — CONM2 offset transport, products of inertia, CONM2 `CID`
  rotation, PBAR `nsm`, consistent CBAR mass — reaches the inertia-relief columns. The previous
  hand-rolled lumped model silently dropped all five.

---

## Mass cases — MASSSET payload conditions (Step 60)

ZAERO-style payload sweeps for the static capability: **one deck, N subcases**, each
pairing a `MASSSET` with its `TRIM` (or Step 53 balanced-maneuver) case. This is the
early-design payload deliverable — different payload conditions analysed without
duplicating the model.

### Card and selection

The `MASSSET` bulk card (fields and ops in
[`02_card_reference.md`](02_card_reference.md#massset--payload--mass-case-step-60)) names
a mass configuration built from the baseline model mass: `SCALE` multiplies the baseline,
then `ADD` / `REPLACE` / `DELETE` overlay, swap, or drop CONM2 cards. A subcase selects it
MSC-style with a case-control `MASSSET = sid` request (like `SPC`/`METHOD`) — deliberately
*not* a TRIM or MLDTRIM field, so the static and transient solvers share one mechanism.

### Resolution — `model/mass_overlay.py`

`resolve_mass_case(bulk, massset_sid)` returns a `MassCase`
(`sid`, `label`, `scale`, `conm2s`); `effective_conm2s(...)` is the CONM2-only shorthand.
Baseline members come back already scaled, overlay members at their card values. The
effective set is built by iterating `bulk.conm2s`, so it keeps **deck (card) order** and a
mass case sums its contributions in the same order a hand-edited deck would.

`massset_sid=None` is the baseline configuration: every CONM2 that is not overlay-only,
unscaled. With no MASSSET cards in the deck that is exactly `bulk.conm2s`, and every
operator below is unchanged from pre-Step-60 behaviour.

### What is rebuilt, and what is not

| Rebuilt per mass case | Shared across the sweep |
|---|---|
| `M_gg` (`assemble_global_mass(bulk, massset_sid)`) | `K_gg` / `K_aa` (stiffness) |
| `M_ax` (`build_inertial_cols(..., M_gg=M_gg)` — `−M_gg Φ_r`, the row above reused) | VLM AIC — `ajj`, `ajj_inv_corr` |
| GPWG mass / CG (`compute_gpwg(bulk, massset_sid)`) | `skj` / `djk` / `wg`, splines `g_disp`/`g_load`/`g_slope` |
| The trim solve and its recovered loads | the whole `AeroCache` |

> **Invariant — no AeroCache invalidation.** The AIC is a function of geometry and Mach
> only. A MASSSET sweep must never rebuild or invalidate it; `test_sweep_shares_one_aero_model`
> asserts object identity across the three subcases of the sample deck.

`SCALE` applies to the whole baseline mass — CBAR distributed mass (`rho·A + nsm`) and
baseline CONM2 mass *and* inertia tensor — because the 6×6 CONM2 block is linear in
`(m, I)`, so scaling both scales the whole block including offset coupling and
parallel-axis terms. MAT1 `rho` overlays are out of scope for v1.

### Output

`Sol144TrimResult` gains `massset_sid`, `massset_label`, `massset_mass` and `massset_cg`.
When a MASSSET is selected the f06 subcase header gains a `MASSSET = / LABEL = / MASS =`
line plus a `CG =` line (omitted entirely for baseline runs, so pre-Step-60 decks produce
byte-identical f06 output). The `*.monitor_loads.csv` gains `massset` and `mass_case`
columns, and both load-card exports stamp the mass case in their comment block. The viewer's
GPWG panel offers a mass-case selector when the deck defines MASSSET cards, and the
analysis-plan summary names the case per subcase.

### Transient maneuvers

`run_maneuver_qs` threads `subcase.massset_sid` into its own `M_gg`/`M_ax` build **and**
into the initial-condition trim, so an `MLOADS` subcase carrying a `MASSSET` runs the whole
maneuver at that payload condition. The fixed-Φ modal interaction (recompute `M_hh,i` only,
reuse the basis) lands with Step 62.

> **The command table is mass-case-specific.** `MLDCOMD` tables are **absolute**, not
> incremental, so a `TABLED1` authored to start at one case's trimmed control angle is not
> that angle in another case: the trim shifts with the payload, and the run then begins with
> a step input instead of at equilibrium. This is a deck-authoring property, not a solver
> defect — pairing `MASSSET` with `MLOADS` means re-running the trim for that mass case and
> re-baking the table's first point. First covered at Step 65 by
> `tests/aero/test_cessna210_flagship.py::test_t6_mloads_with_massset_is_exact_when_the_table_matches_the_case`,
> which pins down both halves: stale table ⇒ the initial condition is not the trim;
> re-authored table ⇒ the initial condition is reproduced to machine precision.

### Sample deck and gates

`sample/ha144a_massset_sweep.bdf` — the full-span HA144A with one TRIM card and three
payload conditions (EMPTY 16000 lb / HALFFUEL 18500 lb / FULLFUEL 21000 lb), exercising all
three ops. Gated by `tests/parser/test_massset.py` (card round-trip, overlay marking, SCALE,
negative cases) and `tests/aero/test_massset_sweep.py`:

- **equivalence** — each MASSSET case matches a hand-edited deck carrying the same final
  CONM2 set: identical `M_gg`, identical GPWG, identical trim (machine precision);
- **baseline unchanged** — no MASSSET selected reproduces the pre-Step-60 operators, and the
  EMPTY case reproduces the untouched `ha144a_fullspan_sbeam.bdf` trim exactly;
- **closure** — per-case Step 53 balanced-maneuver closure ≈ 0, and trimmed lift equals the
  case weight;
- **physics** — heavier case ⇒ larger trimmed ANGLEA and a further-aft CG;
- **shared aero** — three subcases, one `AeroModel` (object-identity assert).

---

## Monitor Points — Integrated Section Loads (MON1–MON4)

Static `MONPNT1` / `MONPNT3` integrated section loads are emitted per SOL 144 trim subcase for the
structures/loads handoff. They sum the trimmed aerodynamic and inertial loads over a named
collection of aero boxes (`MONPNT1`) or structural grids (`MONPNT3`) and report the six-component
resultant `[Fx, Fy, Fz, Mx, My, Mz]` about a reference point, in a chosen coordinate frame.

### Cards

```
$ Named collection: AELIST (box IDs) for MONPNT1, or SET1 (grid IDs) for MONPNT3
AECOMP,  NAME, LISTTYPE, LISTID1, LISTID2, ...        $ LISTTYPE = AELIST | SET1
$ Monitor point definition (single line):
MONPNT1, NAME, LABEL, AXES, COMP, CP, X, Y, Z          $ aero-only
MONPNT3, NAME, LABEL, AXES, COMP, CP, X, Y, Z          $ aero + inertia + reaction
```

- `COMP` is an `AECOMP` name. `MONPNT1` requires an `AELIST`-type AECOMP; `MONPNT3` a `SET1`-type.
- `CP` is the CORD2R (or 0/basic) frame the loads are reported in; `X,Y,Z` is the reference point in
  that frame. The reference is resolved to basic CID 0 for the moment summation, then the resultant
  is rotated into `CP`.
- `AXES` is carried through to the output for annotation (no component masking is applied in Phase 1).

### Integration semantics (`sbeam/results/monitor_points.py`)

- **`MONPNT1` (aero-only):** `F = Σ_k box_forces[k]`, `M = Σ_k (force_point[k] − ref) × box_forces[k]`
  over the AELIST boxes (NASTRAN box ID → global box index via the shared,
  collision-checked `panel.build_box_id_map`, reached as `aero.require_box_id_to_k()`).
  `box_forces` is the trimmed per-box physical force already on `Sol144TrimResult`.
- **`MONPNT3` (aero + inertia + reaction):** per SET1 grid, sum the 6-DOF block from
  `grid_loads` (aero, splined to grids — inherits RBE3/RBAR pass-through), `inertial_loads`
  (inertia; zero for a plain trim, non-zero for a balanced maneuver / 1g gravity trim), and the
  recovered SPC/SUPORT reaction (only for constrained grids inside the collection; balances the net
  aero + inertial load via `sol101.recover_reactions`, R = K·u − f). Forces add directly; moments add
  `m_grid + (r_grid − ref) × f_grid`.
- **Parity:** a single `SYMXZ` factor (from the post-mirror `AEROS`) scales every component — 1.0 for
  the normal full-span pipeline (mirror zeros SYMXZ), 2.0 with a `*WHOLE-AIRPLANE*` annotation if a
  half model is fed directly. The full 3-component force is carried (no Fz-only projection), so
  dihedral `Fy`/`Fz` splits survive.

- **Mass-coverage warning (DEF-M10).** A `MONPNT3` whose SET1 misses a mass-bearing grid reports a
  spurious force imbalance on a balanced trim — the shipped HA144A deck omitted one 93.236-slug
  grid (18.75 % of the model) and showed ~+3000 lb of phantom lift. A section cut legitimately
  covers only part of the model, so the check qualifies on **aero** scope first: only a monitor
  whose z-force matches the model total (within 1 %) is treated as whole-aircraft, and only then is
  its grid set compared against the CONM2-bearing grids. Wing-root and per-wing cuts therefore never
  trigger it. Masses come from the **active MASSSET case** (`mass_overlay.effective_conm2s`), not
  from every `CONM2` card, so mutually exclusive overlays are not double-counted. The warning names
  the omitted grids, their mass and the omitted fraction.

  A whole-aircraft `MONPNT3` should list every grid that carries mass, not only the grids a spline
  transfers force to — these differ whenever a mass sits on a structural grid outside the spline
  target set.

The results are attached as `Sol144TrimResult.monitor_loads = {name: MonitorLoad}`, where
`MonitorLoad` carries `totals` plus the per-contribution `aero` / `inertia` / `reaction` 6-vectors.

### Output (MON4)

- **f06 block** `MONITOR POINT INTEGRATED LOADS` (`results/f06_writer.py`): one metadata row
  (name, label, type, axes, cid, reference) + the six totals per monitor per subcase, annotated
  `*WHOLE-AIRPLANE*` when parity ≠ 1.
- **CSV** `<stem>.monitor_loads.csv` (`results/load_export.py`, written by `main.py`): one row per
  monitor per subcase. Columns:
  `case, name, type, label, axes, cid, x_ref, y_ref, z_ref, Fx, Fy, Fz, Mx, My, Mz,
  Fz_aero, Fz_inertia, Fz_react, parity, whole_airplane`. The `Fz_*` diagnostic breakdown is the
  fastest way to debug a wrong sum.
- **HDF5** hierarchical export is a deferred follow-on (f06 + CSV shipped).

### Validation

`tests/aero/test_monitor_ha144a.py` (V-MON1) gates the chain on the full-span HA144A deck: the
whole-aircraft `MONPNT1` aero resultant equals the whole-aircraft `MONPNT3` aero resultant by spline
conservation (force to machine precision, moment to ~1e-6 relative — the spline rotational-row
numerics), and the whole-aircraft `MONPNT3` aero Fz equals the trimmed 1g weight (~16000 lb) within
1%. **Note:** the exact `MONPNT1`==`MONPNT3` equality holds only over a collection whose grids
receive load *exclusively* from those boxes; a shared centreline root grid (right/left wing + canard)
makes per-surface equality approximate, hence the whole-aircraft gate.

> **An `AELIST` does not follow the mesh.** A `MONPNT1` collection is a literal list of box
> IDs, so boxes added to the model later are simply not in it and the monitor goes on
> returning a confident, slightly wrong number — no warning. The flagship shows this
> deliberately: with body panels active, the bulk's 324-box `AELIST 1400` returns
> 1.0389e4 N where the weight is 1.0605e4 N, short by exactly the 215.6 N injected body
> resultant, while the overlay's 372-box `AELIST 1401` returns n·W. Whenever a deck gains
> `CAERO1`s, every `AELIST` that is meant to say "the whole airplane" has to be extended.
> The `SET1` side of this is the same trap in `MONPNT3` form (DEF-M10). Gated by
> `tests/aero/test_cessna210_flagship_body.py` (B7).

---

## Section-Cut Running Loads (Monitor Phase 2 — `MONSECT`)

Phase 1 gives **one** resultant per named collection. The artefact a stress group
actually sizes a surface from is the **running-load table**: at each of N stations along
the span, the shear, bending moment and torque carried across a cut plane, for every
trim condition and every mass case. `MONSECT` produces it.

The physics is free-body equilibrium — the load carried across a cut is the resultant of
everything on one side of it — which is exactly the `MONPNT3` integrand with the
collection filtered by a plane test and the moment reference moved onto the plane. So
`sbeam/results/section_cuts.py` is a station sweep around the Phase 1 sum: no new solve,
no re-splining, no re-reduction. It consumes the `box_forces` / `grid_loads` /
`inertial_loads` / recovered-reaction arrays `run_sol144_trim` has already built.

![Section-cut geometry and component labelling](../figures/section_cut.svg)

### Card

```
$ Collection: SET1 grids (aero+inertia+reaction) or AELIST boxes (aero only)
AECOMP,  RWINGEA, SET1, 1300
$ Cut definition; continuations carry the stations
MONSECT, SECRW, RIGHT WING LOADS, RWINGEA, 991, 2, POS
+, 0.30, 1.50, 4.20, 6.50
+, NORMAL, 0.26, 1.0, 0.0            $ optional: tilt the cut plane
```

Full field table in `docs/10_standard/02_card_reference.md`. The essentials:

- `CID` + `AXIS` define the station axis. **`AXIS` defaults to 2 (CID y)** — sbeam's
  `SPLINE2` convention — so a cut can reuse the surface's spline CORD2R verbatim, as
  both shipped samples do (HA144A CID 2, flagship CID 991).
- `SIDE` (`POS` default) picks which side of each plane is integrated.
- Stations must be **strictly increasing**; every downstream consumer assumes a monotone
  table.

### Integration semantics (`sbeam/results/section_cuts.py`)

With `(P, R) = get_transform(CID)`, `â` the `AXIS` column of `R` and `n̂` the cut normal
(`â` unless overridden), a member at basic position `r` has **station coordinate**
`s_m = (r − P)·n̂`. For `SIDE = POS` it enters station `s` when `s_m > s + TOL`.

The **reference point** is the plane's intercept with the reference line:

```
r_ref(s) = P + (s / (â·n̂))·â          →   P + s·â  with the default normal
```

When `CID` is the surface's spline CID that line *is* the elastic axis, so the reported
moments are EA-referenced — and it stays correct on a swept surface, because the
stations and the reference line share the axis.

The sum is then Phase 1's, per station:

- **`SET1` collection** — over the outboard grids, `F += f_g`,
  `M += m_g + (r_g − r_ref) × f_g`, applied separately to `grid_loads` (aero),
  `inertial_loads` (inertia) and the recovered SPC/SUPORT reaction. All three are
  reported, plus `totals = aero + inertia + reaction`.
- **`AELIST` collection** — over the outboard boxes, `F += box_forces[k]`,
  `M += (force_point[k] − r_ref) × box_forces[k]`. Inertia and reaction are zero.

Results are rotated into the `CID` frame and attached as
`Sol144TrimResult.section_loads = {name: SectionCutResult}`, each carrying a
`stations: list[SectionCutStation]` with the contribution split and the per-unit-span
differences `d_ds` to the previous station.

### Component labelling

Only two of the six components carry a **role** name: the force along the station axis
(`N`) and the moment about it (`Mt`). The other four keep the name of the CID axis they
act along or about, so nothing is silently renamed by the choice of axis:

| `AXIS` | Labelled order | Raw CID components |
|--------|----------------|--------------------|
| 1 (x)  | `N, Vy, Vz, Mt, My, Mz` | `Fx, Fy, Fz, Mx, My, Mz` |
| **2 (y, default)** | `N, Vx, Vz, Mt, Mx, Mz` | `Fy, Fx, Fz, My, Mx, Mz` |
| 3 (z)  | `N, Vx, Vy, Mt, Mx, My` | `Fz, Fx, Fy, Mz, Mx, My` |

For a spanwise wing cut (`AXIS = 2`) that makes `Vz` the vertical shear and `Mx` the
wing bending moment — the quantities a loads engineer means by those names. The f06
header prints the mapping actually in use, and the CSV writes both the labelled and the
raw components, so no consumer has to reconstruct it.

### Conventions that must be deliberate

1. **On-plane members count as inboard** — the test is strictly `s_m > s + TOL`. A grid
   load is a point load, so a cut *at* a node must exclude it for the outboard free
   body's resultant to equal the beam internal force there; that identity is what
   V-SEC2 gates. Any member within `TOL` of a plane raises a `UserWarning` naming it and
   the station, because that is exactly where the table steps and where the convention
   and a user's expectation can differ.
2. **No symmetry parity, ever.** `monitor_points._apply_symmetry` doubles the symmetric
   components of an `AEROS SYMXZ ≠ 0` half model to report the whole airplane. None of
   that applies to a section cut: a wing cut is *already* the physical per-side load, its
   reference is deliberately off-centreline, and the antisymmetric cancellation is
   meaningless there. `parity` is fixed at 1.0 and the output is annotated
   `HALF-MODEL (LOADS PER SIDE)` instead. The new module deliberately does not import the
   Phase 1 parity helper.
3. **An empty outboard set is a zero row, not an error.** A station outboard of every
   member is a legitimate closure check — it must return exactly zero.
4. **Mass cases come for free.** The inertia column is built from `inertial_loads`, which
   already reflects the active `MASSSET` (Step 60), so a payload sweep produces a table
   per mass case with no extra cards.

> **A `SET1` does not follow the mesh either.** `MONSECT` recomputes *membership* from
> the current model, so a station table can never go stale the way a hand-built
> per-station collection would — but the `AECOMP` it cuts is still a literal list. A
> `MONSECT` over a `SET1` that has not kept up with the model is as wrong as a stale
> `AELIST`, and harder to notice because the table still looks plausible. Same trap as
> the `MONPNT1` box-list note above, in `MONPNT3` form (DEF-M10).

### Output

- **f06 block** `SECTION CUT RUNNING LOADS` (`results/f06_writer.py:_section_cut_block`):
  per cut, a header with the collection, frame, axis, side and source
  (`AERO ONLY` / `AERO + INERTIA + REACTION`), the explicit component legend, then one
  row per station with the reference point and the six labelled components.
- **CSV** `<stem>.section_loads.csv` (`results/load_export.py:write_section_loads_csv`,
  written by `main.py`): one row per cut per station per subcase. Carries the mass-case
  columns, the labelled components *and* their names (`comp_1..comp_6`), the raw
  `Fx..Mz`, the aero / inertia / reaction split, `n_members`, and the `d*_ds` running-load
  differences. The contribution split is the section-cut analogue of the monitor CSV's
  `Fz_*` diagnostic — the fastest way to find a wrong sum.
- **Viewer**: a "Section-cut running loads" panel per cut — the station table plus a
  spanwise chart with selectable components and contribution (total / aero / inertia /
  reaction).

### Validation

| ID | Gate | Where |
|----|------|-------|
| V-SEC1 | Tip point load: `Vz = P`, `Mx = P(L−s)` in closed form, machine precision | `tests/results/test_section_cuts.py` |
| V-SEC2 | **Free-body equilibrium** — outboard resultant == CBAR internal force from `K·u`, ~1e-8 rel | `tests/aero/test_section_cuts_sol144.py` |
| V-SEC3 | Cut inboard of everything == whole-aircraft `MONPNT3` (transferred to the cut reference) | `tests/aero/test_section_cuts_sol144.py` |
| V-SEC4 | Station outboard of every member returns exact zero | both |
| V-SEC5 | Whole-model net (aero+inertia+reaction) ≈ 0, reproducing the maneuver closure | `tests/aero/test_section_cuts_sol144.py` |
| V-SEC6 | **Wing-fuel bending relief** across three `MASSSET` cases | `tests/aero/test_section_cuts_massset.py` |
| V-SEC7 | `AELIST` cut == `SET1` cut aero over a whole collection (spline conservation) | `tests/aero/test_section_cuts_sol144.py` |
| V-SEC8 | `NORMAL` override reassigns members by geometry; reference stays on the EA and on the plane | `tests/results/test_section_cuts.py` |
| V-SEC9 | Half model is annotated, never doubled | `tests/results/test_section_cuts.py` |
| V-SEC10 | On-plane grid warns and counts inboard | `tests/results/test_section_cuts.py` |
| P-SEC1–11 | Parser rejections (non-monotone stations, bad AXIS/SIDE, unknown COMP/CID, degenerate NORMAL, name collision) | `tests/parser/test_monsect.py` |

**V-SEC2 is the load-bearing gate.** It ties the cut to a quantity computed by an
entirely different route — element stiffness times displacement — so it pins the plane
test, the reference point, the moment transfer and the on-plane convention at once. On
the HA144A deck, stations 8 and 10 (CID 2, along the swept EA) cross only `CBAR 120`,
and the outboard resultant matches its end-B internal force to machine precision.

**V-SEC6 is the one a loads engineer will recognise.** On the flagship's three payload
cases the aero root bending rises steeply with weight (9.0 → 11.1 → 14.5 kN·m), the
wing-fuel inertia relief grows against it (−2.4 → −4.4 → −6.4 kN·m), and the *net* root
bending therefore rises far more slowly (6.7 → 6.7 → 8.0 kN·m). A cut that ignored the
mass case, or got the inertia sign wrong, could not reproduce that.

> **A station-by-station `AELIST` cut is not a `SET1` cut's aero column.** The two agree
> over a whole collection (V-SEC7, spline conservation) but not per station: near a cut
> plane, a box and the grids its load splines to can fall on opposite sides. Use the
> `SET1` cut's `*_aero` split for the airload carried across a *structural* station, and
> an `AELIST` cut for the airload distribution in its own right.

### Not covered (follow-on P8b)

Transient (`MLOADS`) section cuts. The integration is reusable verbatim at each output
time, but the deliverable becomes a per-time-step table — a third dimension in the f06
block, the CSV schema and the viewer plot, plus a critical-station/critical-time
envelope. Scope the critical-sample cut first, reusing this schema unchanged.
