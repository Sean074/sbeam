# Aeroelastics Phase B — Structure ↔ Aero Splining

Phase B code standard: the spline operators coupling the structural DOFs to the aero
boxes. Part of the aeroelastics guide — see [`05_aeroelastics.md`](05_aeroelastics.md)
for the architecture overview; [`05a_aero_vlm.md`](05a_aero_vlm.md) for the Phase A
aerodynamics these operators feed; [`05c_sol144_maneuver.md`](05c_sol144_maneuver.md)
for the SOL 144 solve that consumes them.

---

## Phase B — Structure ↔ Aero Splining

### Overview

Phase B implements the structural-to-aerodynamic spline operators required for the SOL 144
static-aeroelastic trim solve (Phase C). Three operators are built:

| Operator | Shape | Role |
|----------|-------|------|
| `g_slope` | `(n_box, 6·n_grid)` | Maps structural DOFs → per-box streamwise incidence (feeds `Djk` in VLM solve) |
| `g_disp`  | `(3·n_box, 6·n_grid)` | Maps structural DOFs → 3-D box displacement (kinematics: deformed-shape recovery, viewer overlay) |
| `g_load`  | `(3·n_box, 6·n_grid)` | **Force transfer**: `g_disp` plus rigid-load rows for boxes with no structural coupling (Step 64) |

These are the `G_slope` and `G_load` operators in the coupling equation
`Q_aa = G_loadᵀ Skj A_jj*⁻¹ Djk G_slope` (see `coupling.py`). Every `gᵀ·f` transfer —
`Q_aa`, `f_g`, `Q_ax`, `grid_loads`, the modal GAFs, the maneuver solvers — uses
`g_load`; `g_disp` is reserved for displacement recovery, so a box the deck never
attached to anything is never shown moving.

#### Load injection (Step 64 / DEF-M1, 2026-07-31)

Boxes with no structural coupling — `SPLINE0`-declared body panels and boxes no spline
card covers — still generate aerodynamic force. Before Step 64 that force was multiplied
by zero `g_disp` rows: it appeared in the printed totals, the rigid derivatives and
MONPNT1, but never in the trim force balance or the load export, so a body-panel trim was
silently *not closed* (measured 31 % lift error on `sample/ha144a_body_trim.bdf`).

`g_load` adds, for each such box `k` with master grid `m` at `p` and lever
`r_k = force_point_k − p`:

```
g_load[3k:3k+3, Tx:Tz] = I₃
g_load[3k:3k+3, Rx:Rz] = −skew(r_k)
⇒  g_loadᵀ f  delivers  Σ F_k  and  Σ r_k × F_k  at the master grid
```

All three force components are carried (a fin or vertical body panel's `Fy` matters as
much as a wing panel's `Fz`). Read forward the same rows are the rigid-body displacement
interpolation `u_k = u_m + θ_m × r_k`, so injection and transfer are a virtual-work pair.

`g_slope` deliberately stays zero on injected boxes: they load the structure but take no
downwash from it — the `SPLINE0` contract ("body elasticity negligible"). `Q_aa` therefore
gains rows at the master grid but no columns, making an already unsymmetric matrix more so;
nothing downstream assumes symmetry (the trim Schur solve and the divergence eigensolve are
both general).

Master-grid resolution: `SPLINE0` field 5 (`GRID`) if given, else the first SUPORT grid.
With neither, a `UserWarning` reports the dropped load and the rows stay zero — SOL 101
body-panel decks (`sample/cessna210_body.bdf`, `cessna210_strip.bdf`) rely on this.

### SPLINE2 — NASTRAN Infinite Beam (Linear) Spline

**Rewritten at the AC7/AE14 close-out (2026-07-05).** SPLINE2 now implements the MSC
NASTRAN infinite-beam-spline formulation exactly (MSC Aeroelastic Analysis User's Guide,
"Theory of Infinite Beam Splines" + "Summary of Matrices for Infinite Surface and Beam
Spline Interpolation", Eqs. 2-48…2-63), replacing the previous cubic-Hermite
implementation.

**Card format:**
```
SPLINE2  EID  CAERO  ID1  ID2  SETG  DZ  DTOR  CID
+        DTHX DTHY        USAGE
```

| Field | Default | Description |
|-------|---------|-------------|
| EID   | —       | Element ID |
| CAERO | —       | CAERO1 EID of the panel being splined |
| ID1   | —       | First NASTRAN box ID in the range |
| ID2   | —       | Last NASTRAN box ID in the range |
| SETG  | —       | SET1 SID listing the structural grids |
| DZ    | 0.0     | Linear (deflection) attachment flexibility: 0 = rigid, > 0 = spring; negative warns and is treated as rigid |
| DTOR  | 1.0     | Torsional flexibility ratio **EI/GJ** — now USED (only the ratio matters); ≤ 0 warns and falls back to 1.0 |
| CID   | 0       | CORD2R SID; **the CID *y*-axis is the spline axis** (MSC convention; QRG SPLINE2 remark 2). The CID x-axis is the chord / rigid-arm direction, the z-axis the deflection direction |
| DTHX  | 0.0     | Bending-slope (rotation about CID x) attachment flexibility: 0 = rigid, > 0 = spring, negative = not attached |
| DTHY  | 0.0     | Torsion (rotation about CID y = spline axis) attachment flexibility (same convention) |
| USAGE | BOTH    | FORCE / DISP / BOTH (informational; not filtered in Phase B) |

**Formulation.** Each SET1 grid attaches its *deflection* `w_g = u·ẑ` to an infinite beam
at axis station `t = (r−origin)·ŷ_cid` with rigid chord arm `χ = (r−origin)·x̂_cid`.
Off-axis grids are legal — the rigid arm converts their deflection into twist information
(the pre-AC7 EA-collinearity restriction is **gone**). The interpolant superimposes
point-load fundamental solutions on the rigid part `a₀ + a₁·t − a₂·χ`:

| Kernel | Bending (EI) | Torsion (GJ = EI/DTOR) |
|--------|--------------|------------------------|
| force P | `\|Δt\|³/12EI` | arm-coupled: `−χᵢχⱼ\|Δt\|/2GJ` |
| moment M | `−Δt·\|Δt\|/4EI` | — |
| torque T | — | `−\|Δt\|/2GJ` |

closed by the equilibrium rows `Rᵀq = 0` with `Rᵢ = [1, tᵢ, −χᵢ; 0,1,0; 0,0,1]`.
Attachment flexibilities (DZ/DTHX/DTHY) add to the flexibility-matrix diagonal
(springs in series). A grid rotation about x̂ attaches as a bending-slope DOF (load:
moment), about ŷ as a torsion DOF (load: torque) — only when the corresponding DTHX/DTHY
is ≥ 0.

Deformed surface height at a box point: `z(t, χ) = w(t) − χ·φ(t)`. The g_slope row is the
streamwise incidence `−∂z/∂x = −[ŷ_cid[0]·(w′ − χ·φ′) − x̂_cid[0]·φ]` at the ¾-chord
collocation point; g_disp rows carry `z·ẑ_cid` at the ¼-chord force point (AE6), so force
transfer is virtual-work paired. With wing rotations detached (DTHX=DTHY=−1, the MSC
HA144A configuration) grid loads are **pure forces** — twist information travels through
LE/TE stringer deflection *pairs* and their rigid arms, exactly as in NASTRAN.

**HA144A configuration (MSC deck values, restored at AC7):** wing SPLINE2 with
SET1 = {99, 100, 111, 112, 121, 122} (root fuselage grid + root EA + LE/TE stringers) and
DTHX=DTHY=−1; canard SPLINE2 with SET1 = {98, 99} (both at axis station 0, distinguished
by their chord arms → pitch from the deflection pair) and DTHX=1.0 (the guide's roll
smoothing spring; DTHX=0 would be overdetermined, DTHX=−1 singular).

**Warnings/errors:** DTOR ≤ 0 and DZ < 0 warn (fall back to 1.0 / 0.0). A singular spline
system (e.g. an EA-only collinear SET1 with torsion detached — no twist information)
raises a `ValueError` naming the likely cause. Box-range/extrapolation warnings unchanged.

**History:** the AE4/AE6 fixes and the AE12 DTOR/DTHZ warnings applied to the retired
Hermite implementation; the DTOR warning is gone (DTOR is used now) and the old "DTHZ"
field is DTHY per the MSC card. See `docs/40_history/00_completed_development.md`
(Steps AC4, AC7).

**NASTRAN box ID convention** (must match `panel.py` row-major ordering):
```
box_id = CAERO1.EID + i_span × n_chord_boxes + j_chord
```

Single owner: `panel.nchord_per_caero` / `nastran_box_id` / `build_box_id_map`. The last
builds the `{box ID: k}` map every consumer uses (spline coverage, `build_djx` AESURF
columns, hinge moments, `MONPNT1`) and **raises on any ID collision** — a CAERO1 spans
`NSPAN × NCHORD` consecutive IDs from its EID, so surfaces numbered closer than that
overlap and one box's load is attributed to another. `build_aero_model` validates it
immediately after meshing; `AeroModel.require_box_id_to_k()` hands out the validated map.

### CID-aware DOF projection

All structural DOFs are in global CID 0. The spline CID provides the projections:

```
origin, R_cid = get_transform(spline2.cid, cord2rs)
c_hat = R_cid[:, 0]   # chord / rigid-arm direction (CID x)
s_hat = R_cid[:, 1]   # spline axis (CID y) — MSC convention
z_hat = R_cid[:, 2]   # deflection direction (CID z)
```

Per grid: deflection DOF value = `u·ẑ` (translation columns weighted by `z_hat[d]`);
bending-slope DOF = `ω·ĉ` (rotation columns via `c_hat[d−3]`, if DTHX ≥ 0); torsion DOF =
`ω·ŝ` (via `s_hat[d−3]`, if DTHY ≥ 0).

### Rigid-body exactness (V-AE2 / V-AE1b gates)

Any rigid motion gives grid data `w = c₀ + c₁t + c₂χ` with matching attached rotations,
which the beam spline's rigid part (a₀, a₁, a₂) fits with zero point loads — all six
global basic-frame rigid-body modes are reproduced to machine precision **by
construction**. Verified to 1e-12 by `TestSweptSplineRigidBody` (V-AE2) and
`TestGlobalRigidBody` (V-AE1b) on swept, rectangular, and 30°-dihedral fixtures, plus the
non-rigid analytic-field gates (`TestBeamSplineFlexFields`: linear bend exact, linear
twist pinned at the stringer stations, parabolic bend interpolated).

### `build_spline_operators` API

```python
from sbeam.aero.spline import build_spline_operators

ops = build_spline_operators(bulk, boxes, grid_index)   # None if no spline cards
# ops.g_slope    : np.ndarray (n_box, 6*n_grid)
# ops.g_disp     : np.ndarray (3*n_box, 6*n_grid)   kinematics
# ops.g_load     : np.ndarray (3*n_box, 6*n_grid)   force transfer (g_disp + injection)
# ops.covered    : list[bool] per box
# ops.injections : list[LoadInjection] — (master_grid, boxes, source)

# Kinematics-only convenience wrapper (no injection rows):
from sbeam.aero.spline import build_g_spline
g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
```

Raises `ValueError` if a box is covered by more than one spline, a SET1 has < 2 grids,
or a spline system is singular (e.g. EA-only collinear SET1 with DTHY < 0 — no twist
information). Issues `UserWarning` for un-splined boxes, >10% extrapolation, empty box
ranges, DTOR ≤ 0, or DZ < 0.

`AeroModel` stores the operators as `aero_model.g_slope`, `aero_model.g_disp`,
`aero_model.g_load` and `aero_model.load_injections` when
`build_aero_model` is called with a `grid_index` dict.

### ATTACH — Rigid Attachment (Step 47)

`ATTACH` rigidly couples a group of aero boxes to a single master structural GRID.
It is an sbeam extension (ZAERO-inspired). All boxes in the covered ID range move
as a rigid body with the master grid.

**Card format:**
```
ATTACH  EID  CAERO  ID1  ID2  GRID  CID
```

| Field | Description |
|-------|-------------|
| EID | Element ID (unique) |
| CAERO | CAERO1 EID of the panel |
| ID1, ID2 | NASTRAN box ID range (inclusive) |
| GRID | Master structural GRID ID |
| CID | Coordinate system (must be 0; CID ≠ 0 raises `NotImplementedError`) |

**Lever-arm kinematics (global CID 0):**

For each covered box j with lever `r = box.force_point − master_pos = (rx, ry, rz)`:

**AE6 — resolved 2026-06-11:** the lever and the SPLINE2 `g_disp` evaluation point both
use `box.force_point` (¼-chord bound-vortex midpoint), not `box.colloc` (¾-chord).
The g_slope operator remains at the ¾-chord collocation point (flow tangency).

`g_slope` carries **streamwise incidence, nose-up positive** — the same sense as SPLINE2
and the ANGLEA column (`build_djk = -I` converts it to normalwash). For a rigid rotation
ω the surface displacement is `u = ω×r`, so

```
∂u/∂x = ω × x̂ = (0, ω_z, -ω_y)
α     = -(∂u/∂x)·n̂ = ω_y·n_z - ω_z·n_y
```

giving, per box unit normal `n̂`:

```
g_slope[j, col_Tx/Ty/Tz] = 0.0     # uniform translation → zero slope
g_slope[j, col_Rx] = 0.0           # roll about the streamwise axis → no slope
g_slope[j, col_Ry] = +n_z          # pitch  (+1 for a z-normal box)
g_slope[j, col_Rz] = -n_y          # yaw    (drives incidence on fins)

g_disp[3j+0, col_Tx] = 1.0  # translation identity, all three components
g_disp[3j+1, col_Ty] = 1.0
g_disp[3j+2, col_Tz] = 1.0
g_disp[3j+0, col_Ry] =  rz  # (ω×r)_x = +Ry·rz - Rz·ry
g_disp[3j+0, col_Rz] = -ry
g_disp[3j+1, col_Rx] = -rz  # (ω×r)_y = -Rx·rz + Rz·rx
g_disp[3j+1, col_Rz] =  rx
g_disp[3j+2, col_Rx] =  ry  # (ω×r)_z = +Rx·ry - Ry·rx
g_disp[3j+2, col_Ry] = -rx
```

**DEF-H1 — resolved 2026-07-31:** the `Ry` row previously read `-1.0` and `Rx` a spurious
`+1.0`. Nose-up pitch of a master grid therefore produced washout, and unit roll injected
a full unit of false incidence, sign-inverting the aeroelastic feedback in `Q_aa`, trim and
divergence for every ATTACH deck. The `Ry`/`Rz` rows are now built from the box normal, so
dihedral and vertical panels are handled as well as flat ones.

Energy consistency: `α = -∂u_z/∂x = -∂(-rx·θ_y)/∂x = +θ_y = g_slope[j, col_Ry]` for a
z-normal box (virtual work ✓ — `g_disp` supplies `u_z = -rx·θ_y`).

**DEF-M11 — resolved 2026-08-01:** `g_disp` previously filled only the z-row (`Tz`, and the
z-component of `ω×r`), so the in-plane `Fx`/`Fy` of a canted or vertical ATTACH panel never
reached the master grid and the roll/yaw moments they generate were lost with them — a
26.57° dihedral panel dropped 50% of `Fz` as side force and all of `Mz`; a fin panel
transferred nothing at all. All three rows now carry the full rigid-body transform
`u = t + ω×r`, so `g_dispᵀ f` is the exact transfer `F = Σ f_j`, `M = Σ r_j × f_j`, and the
pairing with `g_slope` (general in the box normal since DEF-H1) is complete. For a z-normal
panel the box force is pure `Fz`, so the added rows multiply by zero and every existing
result is bit-identical.

**V-B3 rigid-body gate (machine precision):**
- V-B3a Tz translation → zero incidence (< 1e-14)
- V-B3b Ry pitch → uniform incidence +1.0 (< 1e-14)
- V-B3e Rx roll → zero incidence (< 1e-14)
- V-B3f rigid rotation matches the SPLINE2 route on the same panel (< 1e-12)
- V-B3d Force transfer: `g_disp.T @ (skj @ cp)` gives correct Fz, Mx, My at master (< 1e-12),
  and the in-plane rows are inert on a z-normal panel (bit-identical)
- V-B3d-DIH Force transfer on a 26.57° dihedral panel: all three force and all three moment
  components match `ΣF` / `Σ r×F` (< 1e-14), with `Fy = −Fz/2` from `tan Γ` (DEF-M11)
- V-B3d-VERT Force transfer on a vertical (fin) panel: the load is pure `Fy` and survives
  transfer intact (< 1e-14) (DEF-M11)
- V-B3d kinematics: `g_disp @ u` reproduces `t + ω×r` per box for arbitrary rigid motion
  (< 1e-14) — pins the operator itself, not only its transpose (DEF-M11)
- V-B3g (`tests/aero/test_attach_sol144.py`) ATTACH and SPLINE2 give the same flexible
  lift within 3% through the SOL 144 static aeroelastic solve, and both converge to the
  rigid lift (1e-6) in the stiff limit

### SPLINE0 — Zero-Displacement Constraint (Step 47)

`SPLINE0` registers a box range as "covered" without adding any structural coupling.
All `g_slope` and `g_disp` rows for the covered boxes remain zero — but their aerodynamic
force is injected at the master grid through `g_load` (see *Load injection* above). Used to suppress
un-splined warnings for boxes that are intentionally uncoupled (e.g. control surfaces
or far-field boxes that do not deflect structurally).

**Card format:**
```
SPLINE0  EID  CAERO  ID1  ID2  GRID
```

`g_disp.T @ (any pressure force)` = 0 for all structural DOFs (V-B3c verified), while
`g_load.T @ (that force)` is its exact 6-component resultant at the master grid (V-M1a).

---

### `compute_structural_loads` API (Step 49)

```python
from sbeam.aero.aero_model import compute_structural_loads

f_g = compute_structural_loads(aero_model, q, alpha)
# f_g: np.ndarray, shape (6 * n_structural_grids,)
```

Computes the rigid-configuration structural g-set load vector for a given dynamic
pressure and angle of attack.

**Algorithm:**

```
w_total[j] = -(alpha * normal_z[j]) + wg[j]   # flow-tangency + baseline normalwash
gamma       = ajj_inv_corr @ w_total            # VLM solve (returns circulation Γ)
f_box       = skj @ gamma                       # per-box aerodynamic forces (3·n_box,)
f_g         = q * g_load.T @ f_box             # virtual-work force transfer to g-set
```

**Sign convention:** matches `solve_rigid_cl` — for a horizontal flat plate with
`normal = [0, 0, 1]`, angle of attack `alpha` gives `w[j] = -alpha` at each box.

**AE2 — Gamma/cp unit defect — RESOLVED (2026-06-11):** `ajj_inv_corr` is now
row-scaled by `2/chord_box_j` in `build_aero_model` immediately after the Prandtl–Glauert
step, so `ajj_inv_corr @ w` returns ΔCp (not Γ) and `skj`'s `F = area·n̂·Cp` is
unit-consistent.  `total_cl/cm` in `run_sol144_trim` and `_compute_restrained_derivs` no
longer divide by `q`.  Verification: CZα = 5.071 via skj path (target: `solve_rigid_cl`
CLα = 5.0709 ✓); `total_cl` at SC1 trim = −1.001 ✓.  See `docs/40_history/00_completed_development.md`.

**Requirements:**
- `aero_model.g_load` must not be `None` — call `build_aero_model` with a `grid_index`
  argument to populate the spline operators. Raises `ValueError` otherwise.
- `alpha` in radians; `q` in consistent pressure units (Pa, psf, …).

**V-B2 verification (Step 49, machine precision):**
- V-B2a: `sum(f_g[Tz_dofs]) == q * sum(f_box_z)` to < 1e-10 — exact by virtual work ✓
- V-B2b: `f_tz` within 2% of `q*CL*sref` (or `/2` for Γ-based AIC) ✓
- V-B2c: `compute_structural_loads(alpha=0) == q * build_fg(aero, g_load)` to < 1e-12 ✓
- V-B2d: `ValueError` when `g_load is None` ✓
