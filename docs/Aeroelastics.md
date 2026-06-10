# Aeroelastics.md — Phase A: Steady Vortex-Lattice Aeroelastics

## Architecture Overview

Phase A adds a steady vortex-lattice aerodynamic layer on top of the existing structural solver.
The data flow is:

```
BDF file
  ↓ parse_bulk_data()
BulkData  (bulk.aeros, bulk.caero1s, bulk.paero1s, bulk.aefacts, ...)
  ↓ build_aero_model()
AeroModel (boxes, ajj, skj, djk, wg, parity, aeros)
  ↓ solve_rigid_cl() / coupled aeroelastic solve (Phase B+)
Results   (cp, cl_section, CL, CY, CM, per_surface, …)
```

### Module map

| Module | Purpose |
|--------|---------|
| `sbeam/model/aero.py` | Dataclasses for aero BDF cards (`Aeros`, `Caero1`, `Paero1`, `Aefact`, `W2gj`, `Wkk`, `Aecorr`) |
| `sbeam/aero/panel.py` | `AeroBox` dataclass + `mesh_caero1()` — trapezoidal box meshing, ¼c/¾c placement |
| `sbeam/aero/vlm.py` | Biot–Savart segments, horseshoe influence, AIC matrix, rigid-AOA solve |
| `sbeam/aero/integration.py` | `Skj` force integration matrix, `Djk` downwash matrix, `wg` baseline normalwash |
| `sbeam/aero/corrections.py` | `Wkk` diagonal correction, `WT1` force-match, `WT2` pressure-match |
| `sbeam/aero/aero_model.py` | `AeroModel` container + `build_aero_model()` factory |
| `sbeam/aero/coupling.py` | `build_qaa` flexible aero stiffness `Q_aa = G_dispᵀ S_kj (A_jj*)⁻¹ D_jk G_slope`; `build_fg` baseline aero load; `build_gaf` modal GAF `Q_hh = Φᵀ Q_aa Φ` |
| `sbeam/viewer/aero_view.py` | Plotly box mesh, cp colour map, section-load strip chart |

---

## Supported BDF Cards

| Card | Purpose | Step |
|------|---------|------|
| `AEROS` | Reference geometry (cref, bref, sref) and symmetry flags | S39 |
| `CAERO1` | Aerodynamic panel definition (trapezoidal lifting surface) | S40 |
| `PAERO1` | Aerodynamic panel properties (stub in Phase A) | S40 |
| `AEFACT` | Arbitrary span/chord fraction lists for non-uniform meshing | S40 |
| `W2GJ` | Per-box baseline normalwash slopes | S42 |
| `WKK` | Diagonal AIC correction multipliers | S43 |
| `AECORR` | Force/pressure matching AIC corrections (WT1, WT2) | S43 |

---

## AEROS Card

### Purpose

The AEROS card defines the aerodynamic reference geometry used to non-dimensionalise
lift, drag, and moment coefficients, and to specify the symmetry condition for the
vortex lattice.

### Format

```
AEROS  ACSID  RCSID  CREF  BREF  SREF  SYMXZ  SYMXY
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| ACSID | int | 0 | Aerodynamic coordinate system (0 = basic) |
| RCSID | int | 0 | Reference coordinate system for rigid body motion |
| CREF | float | — | Reference chord length (consistent model units) |
| BREF | float | — | Reference span (full span, even for symmetric models) |
| SREF | float | — | Reference area (full area) |
| SYMXZ | int | 0 | +1 = symmetric about XZ plane, −1 = antisymmetric, 0 = no symmetry |
| SYMXY | int | 0 | +1 = symmetric about XY plane, −1 = antisymmetric, 0 = no symmetry |

### Symmetry conventions

- `SYMXZ = +1`: the model represents one semi-span; a mirror image is added across the
  XZ plane with the same circulation sign (symmetric lift). The VLM AIC matrix adds a
  positive mirror-image horseshoe for each box.
- `SYMXZ = -1`: antisymmetric (rolling) condition; the mirror image has opposite
  circulation sign. Net lift ≈ 0, rolling moment ≠ 0.
- `SYMXZ = 0`: full-span model, no image vortices added.

The parity value derived from `SYMXZ` is passed through the entire Phase A pipeline as
`parity = +1` (sym) or `parity = -1` (antisym).

### Validation rules

- **Duplicate AEROS**: only one AEROS card is permitted per model. A second card raises
  `ValueError("Duplicate AEROS card")`.
- **CAERO1 without AEROS**: if any CAERO1 cards are parsed and no AEROS card is present,
  `parse_bulk_data` raises `ValueError("CAERO1 card(s) present but no AEROS card found")`.
  This guard is implemented in `parse_bulk_data` (post-loop), using the `bulk.caero1s`
  dict populated by S40.

### Storage

```python
bulk.aeros  # Optional[Aeros], None until parsed
```

---

## CAERO1 / PAERO1 / AEFACT

### Card Formats

```
AEFACT  SID  D1  D2  D3  D4  D5  D6  D7
+       D8   D9  ...
```

```
PAERO1  PID
```

```
CAERO1  EID  PID  CP  NSPAN  NCHORD  LSPAN  LCHORD  IGID
+       X1   Y1   Z1  X12    X4      Y4     Z4      X43
```

| Field | Description |
|-------|-------------|
| AEFACT SID | Set ID referenced by CAERO1 LSPAN or LCHORD |
| AEFACT D1–DN | Decimal fractions 0.0–1.0; must start at 0.0 and end at 1.0 |
| PAERO1 PID | Property ID referenced by CAERO1; Phase A stub (no body support) |
| CAERO1 EID | Element ID (unique integer) |
| CAERO1 PID | References PAERO1 |
| CAERO1 CP | Coordinate system for P1/P4 (0 = global; or CORD2R CID) |
| CAERO1 NSPAN | Number of equal spanwise boxes (0 if LSPAN used) |
| CAERO1 NCHORD | Number of equal chordwise boxes (0 if LCHORD used) |
| CAERO1 LSPAN | AEFACT SID for non-uniform span breakpoints (0 if NSPAN used) |
| CAERO1 LCHORD | AEFACT SID for non-uniform chord breakpoints (0 if NCHORD used) |
| CAERO1 IGID | Interference group ID (ignored in Phase A) |
| X1, Y1, Z1 | Root leading-edge point P1, in CP coordinate system |
| X12 | Root chord length in freestream +X direction |
| X4, Y4, Z4 | Tip leading-edge point P4, in CP coordinate system |
| X43 | Tip chord length in freestream +X direction |

Exactly one of NSPAN/LSPAN must be non-zero; exactly one of NCHORD/LCHORD must be
non-zero. An AEROS card must be present whenever CAERO1 cards appear.

### AeroBox Dataclass

`mesh_caero1()` produces a list of `AeroBox` objects — one per VLM panel — in
row-major order (span slowest, chord fastest):

```python
@dataclass
class AeroBox:
    k: int              # Global sequential index
    caero_eid: int      # Parent CAERO1 EID
    i_span: int         # Spanwise strip index (0-based)
    j_chord: int        # Chordwise column index (0-based)
    corners: np.ndarray # (4, 3) corner coordinates in global CID 0
    colloc: np.ndarray  # (3,) collocation point at 3/4-chord, midspan
    bound_a: np.ndarray # (3,) bound vortex root endpoint at 1/4-chord
    bound_b: np.ndarray # (3,) bound vortex tip endpoint at 1/4-chord
    area: float         # Panel area (cross-product of diagonals)
    normal: np.ndarray  # (3,) outward unit normal (dominant-axis oriented: +Z or +Y)
    chord: float        # CAERO1 macroelement chord (not the individual box chord)
    span_frac: float    # Spanwise centroid position, 0.0 (root) to 1.0 (tip)
```

### `mesh_caero1()` Function

```python
def mesh_caero1(
    caero: Caero1,
    paero: Paero1,
    aefacts: dict[int, Aefact],
    cord2rs: dict[int, Cord2r],
    start_k: int = 0,
) -> list[AeroBox]
```

Converts one CAERO1 macroelement into an ordered list of `AeroBox` objects. Key
implementation details:

- P1 and P4 are transformed from CP frame to global CID 0 using `_get_transform()`
  (full origin + R @ v_local, not rotation-only).
- Bound vortex and collocation points are placed at ¼ and ¾ of each **box** chord
  individually. For NCHORD > 1 each chordwise row has independent horseshoe positions.
- **Normal orientation**: the cross-product of box diagonals gives a raw normal; it is
  flipped so the component with the largest absolute value is positive (+Z for horizontal
  surfaces, +Y for vertical fins in the XZ plane).
- **Bound vortex orientation**: the bound segment direction is chosen so that the AIC
  self-influence (diagonal entry) is always negative — i.e., `(bound_b − bound_a) × x̂ · n̂ < 0`.
  For VTP panels (span in +Z), this means the bound vortex runs top-to-bottom (high Z to
  low Z). This is required for consistent sign conventions across horizontal and vertical
  surfaces.
- Non-uniform meshing: AEFACT fraction list defines NSPAN+1 or NCHORD+1 breakpoints;
  panels are sized proportionally to the fraction differences.

---

## VLM AIC Matrix

### Horseshoe Vortex Convention

Each VLM box carries a horseshoe vortex of unit circulation strength:
- **Bound segment**: runs from `bound_a` to `bound_b` at the box ¼-chord line.
- **Trailing legs**: extend from `bound_a` and `bound_b` in the +X (freestream)
  direction to a far-field cutoff at `max(bound_a.x, bound_b.x) + 1000 × chord`.
- Flow tangency is enforced at each box's **collocation point** (3/4-chord, midspan).

### Functions

**`biot_savart_seg(p, a, b) -> np.ndarray`**

Induced velocity (3-vector) at point `p` from a unit-strength finite vortex segment
`a → b`, using the NASA SP-405 closed-form formula. Returns the zero vector for
degenerate inputs (p on segment, or a ≈ b).

Guards: `_DEGEN_TOL = 1e-14` for collinearity; `_FAR_FIELD_FACTOR = 1000.0` for the
trailing-leg cutoff ratio.

**`horseshoe_influence(colloc, colloc_normal, box, parity=1) -> float`**

Returns the normalwash (induced velocity dotted with `colloc_normal`) at `colloc` from
a unit horseshoe at `box` (ZAERO Eq. 3.49a: `NIC = n_x·UIC + n_y·VIC + n_z·WIC`).
This general dot-product formulation supports arbitrary surface orientations — horizontal
wings (n̂ ≈ +Z) and vertical fins (n̂ ≈ +Y) are treated consistently.
For half-span models a mirror image across the XZ plane is added:

| `parity` | Image direction | Effect |
|----------|-----------------|--------|
| `+1` (symmetric) | bound reversed: b_img → a_img | Root trailing legs cancel; left-wing produces same-sign lift |
| `-1` (antisymmetric) | bound unreversed: a_img → b_img | Root trailing legs reinforce; full-span CL = 0 |
| `0` | No image | Full-span model, no symmetry |

**`build_ajj(boxes, parity=1) -> np.ndarray`**

Assembles the n×n aerodynamic influence coefficient (AIC) matrix. `A[i, j]` is the
normalwash at collocation point `i` per unit circulation strength at horseshoe `j`.
O(n²) loop over all panel pairs.

**`solve_rigid_cl(boxes, alpha, beta=0.0, parity=1, aeros=None, xref=0.0) -> dict`**

Solves the rigid-wing flow-tangency problem at angle of attack `alpha` and sideslip
`beta` (both in radians). Boundary condition per panel (ZAERO Eq. 3.28):

```
rhs[i] = -(V⃗ · n̂_i)  ≈ -(α·n_z[i] + β·n_y[i])   for small angles
A @ Γ = rhs
```

- Horizontal surfaces (n̂ ≈ +Z): loaded by `alpha`, negligible response to `beta`.
- Vertical surfaces (n̂ ≈ +Y): loaded by `beta`, negligible response to `alpha`.

**Parameters:**
- `aeros` — optional `Aeros` card; if provided `aeros.sref` is used as S_ref and
  `aeros.cref` as the reference chord. Without it a heuristic S_ref = Σ(box areas)
  and c_ref = S_ref/span_ref is used. Always pass `aero_model.aeros` in production.
- `xref` — x-coordinate of the moment reference point in CID 0 (default 0.0, the
  coordinate origin). Set to the quarter-MAC x-coordinate for a standard stability-axis
  CM. The NASTRAN convention (AEROS RCSID = 0) corresponds to xref = 0.

**Surface classification:** each CAERO1 surface is classified from its mean outward
normal — `|n_z| ≥ |n_y|` → *lift* surface (contributes to CL and CM); `|n_y| > |n_z|`
→ *sideforce* surface (contributes to CY). This ensures VTP sideforce is not added to
wing CL on multi-surface models.

**Returns a dict:**
- `cp`: (n,) pressure coefficient per box — `2Γ / (V∞ × box_chord)`, V∞ = 1
- `cl_section`: `{i_span: CL_strip}` — per-strip coefficient via Kutta–Joukowski (all surfaces)
- `CL`: total lift coefficient — lift surfaces only, normalised by S_ref
- `CY`: total sideforce coefficient — sideforce surfaces only, normalised by S_ref
- `CM`: pitching moment about `xref`, nose-up positive; lift surfaces only;
  normalised by S_ref × c_ref. Each box load acts at its **¼-chord bound vortex**
  (not the ¾-chord collocation point) — the physically correct moment arm.
  Validated against AVL / VortexLattice.jl (`val_vlm_byu_wing`: CM −0.0209 vs −0.02085).
- `per_surface`: `{caero_eid: {surface_type, CL, CY, CM}}` — per-CAERO1 coefficients

Note: with `parity=0` (full-span single surface, no image vortex), the VLM solution
converges to a limit ~5–10% below the Prandtl finite-span formula `2πAR/(AR+2)`. This
is an intrinsic property of single-surface parity=0 VLM, not a bug. The convergence is
non-monotone relative to the Prandtl target (overshoots at coarse meshes, then decreases
as panels are added), but is internally consistent and converges to a stable VLM limit.

---

## Integration Matrices (Skj, Djk, wg)

### `build_skj(boxes) -> np.ndarray`  — shape (3n, n)

Force integration matrix mapping pressure coefficient per box to resultant force vector.
Column `j`: `F_j = area_j × normal_j × cp_j` (three consecutive rows for Fx, Fy, Fz).

Usage: `F_vec = Skj @ cp_vec` → `[Fx_0, Fy_0, Fz_0, Fx_1, …]`

### `build_djk(boxes) -> np.ndarray`  — shape (n, n)

Deflection-to-downwash matrix for steady (k = 0) analysis. Returns `−I` (negative
identity): unit positive slope Δz/Δx at collocation point j produces normalwash `−1`
at box j. Phase D DLM will replace this matrix with the full unsteady kernel without
changing the caller interface.

### `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray`  — shape (n,)

Baseline normalwash vector from the W2GJ BDF card. Values are dimensionless slope
Δz/Δx, one per box, in row-major order (span slowest, chord fastest). Returns a zero
vector if no W2GJ card matches `caero_eid`.

### W2GJ Card Format

```
W2GJ  SID  CAERO_EID  D1  D2  D3  D4  D5  D6
+     D7   D8  ...
```

| Field | Description |
|-------|-------------|
| SID | Set ID |
| CAERO_EID | EID of the CAERO1 this normalwash applies to |
| D1–DN | Dimensionless normalwash slopes Δz/Δx, one per box in row-major order |

---

## AIC Corrections (Wkk, WT1, WT2)

Phase A provides three correction tiers to match VLM predictions to higher-fidelity
CFD or wind-tunnel data. The correction precedence in `build_aero_model()` is:

```
WKK card present  →  apply_wkk  (caller inverts via np.linalg.solve)
AECORR WT2 present →  apply_wt2  (returns AJJ*⁻¹)
AECORR WT1 present →  apply_wt1  (returns AJJ*⁻¹)
No correction      →  np.linalg.solve(AJJ, I)
```

### Card Formats

```
WKK     SID  CAERO_EID  W1  W2  W3  W4  W5  W6
+       W7   W8  ...

AECORR  SID  METHOD  CAERO_EID  T1  T2  T3  T4  T5
+       T6   T7  ...
```

| Field | Description |
|-------|-------------|
| WKK SID | Set ID |
| WKK CAERO_EID | CAERO1 EID this correction applies to |
| WKK W1–WN | Diagonal weight per box; one value per box in row-major order |
| AECORR SID | Set ID |
| AECORR METHOD | `WT1` (force/moment matching) or `WT2` (pressure matching) |
| AECORR CAERO_EID | CAERO1 EID this correction applies to |
| AECORR T1–TN | Target values; see below |

### `apply_wkk(ajj, wkk_data) -> np.ndarray`

Returns `AJJ* = diag(w) @ AJJ`. The caller (`build_aero_model`) inverts via
`np.linalg.solve`. Simplest correction; can absorb empirical scale factors or
stall nonlinearity. Issues a `UserWarning` if `cond(AJJ*) > 1e10`.

### `apply_wt2(ajj, cp_target) -> np.ndarray`

Pressure-matching correction. Returns corrected `AJJ*⁻¹` by scaling each row of
`AJJ⁻¹` by `cp_target_k / cp_vlm_ref_k`, where the reference normalwash is
`w_ref = -ones(n)` (uniform unit incidence). The fixed reference state is required:
deriving `w_ref` from `cp_target` itself yields a trivial identity correction. Boxes
with near-zero `cp_vlm_ref` (tolerance `_RATIO_TOL = 1e-12`) keep a ratio of 1.0.
Issues a `UserWarning` if `cond(AJJ) > 1e10`.

### `apply_wt1(ajj, boxes, f_target) -> np.ndarray`

Force/moment-matching correction. Groups boxes by `i_span` and finds a per-strip
scalar ratio `f_target_s / f_vlm_s`. All boxes in a strip share the same correction
factor. `f_target` must have one value per distinct `i_span`; a `ValueError` is raised
on length mismatch. Uses same `w_ref = -ones(n)` reference state as WT2.

### `build_aero_model(bulk, parity=1) -> AeroModel`

Factory function that orchestrates the full Phase A assembly pipeline:

1. Mesh all CAERO1 elements in ascending EID order → concatenated `AeroBox` list
2. Build raw AIC matrix via `build_ajj(boxes, parity)`
3. Apply correction at highest available tier (WKK → WT2 → WT1 → identity)
4. Build `Skj`, `Djk`, and `wg` integration quantities
5. Package into `AeroModel` and return

```python
@dataclass
class AeroModel:
    boxes: list[AeroBox]       # All AeroBox objects (concatenated across CAERO1s)
    ajj: np.ndarray            # Raw VLM AIC, shape (n, n)
    ajj_inv_corr: np.ndarray   # Corrected inverse (factored), shape (n, n)
    skj: np.ndarray            # Force integration, shape (3n, n)
    djk: np.ndarray            # Deflection-to-downwash, shape (n, n)
    wg: np.ndarray             # Baseline normalwash, shape (n,)
    parity: int                # +1 symmetric, -1 antisymmetric, 0 full-span
```

---

## Viewer — Aero Tab (S44)

`sbeam/viewer/aero_view.py` provides Plotly figure builders for the aerodynamic mesh
and pressure-coefficient visualisation. The Streamlit app (`app.py`) shows an "Aero"
tab automatically when `bulk.caero1s` is non-empty.

### Public API

```python
build_aero_box_figure(
    bulk: BulkData,
    aero_model: AeroModel,
    cp: np.ndarray | None = None,
    cl_section: dict | None = None,   # i_span → float, from solve_rigid_cl()
    cp_corr: np.ndarray | None = None,
) -> go.Figure
```

Returns a two-row subplot:
- **Row 1 (75%)** — Plotly 3D scene with the aerodynamic box mesh (Scatter3d wire-frame)
  and, when `cp` is provided, a triangulated Mesh3d panel coloured by cp (`colorscale="RdBu_r"`).
- **Row 2 (25%)** — 2D bar chart of section CL vs span fraction. When `cp_corr` is also
  provided, two Scatter lines are overlaid showing spanwise mean cp for inviscid vs corrected solutions.

### Internal helpers

| Function | Row | Description |
|----------|-----|-------------|
| `_add_box_mesh(fig, boxes)` | 1 | Single Scatter3d wire-frame; each quad closed as `[0,1,2,3,0,None]` |
| `_add_cp_contour(fig, boxes, cp)` | 1 | Mesh3d triangulated quads; cp→vertex intensity |
| `_add_section_load_strip(fig, boxes, cl_section)` | 2 | Bar chart of `i_span`→CL using `box.span_frac` |
| `_add_corrected_vs_inviscid(fig, boxes, cp_inv, cp_corr)` | 2 | Two Scatter lines: spanwise mean cp per strip |
| `_apply_aero_layout(fig)` | — | Orthographic camera, axis labels, subplot axis titles |

### Typical usage in the viewer

```python
aero_model = build_aero_model(bulk, parity=1)
result = solve_rigid_cl(aero_model.boxes, np.radians(3.0))
fig = build_aero_box_figure(
    bulk, aero_model,
    cp=result["cp"],
    cl_section=result["cl_section"],
)
st.plotly_chart(fig, use_container_width=True)
```
