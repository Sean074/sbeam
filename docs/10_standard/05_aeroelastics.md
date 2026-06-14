# Aeroelastics — Phase A: Steady Vortex-Lattice Aeroelastics

## Architecture Overview

Phase A adds a steady vortex-lattice aerodynamic layer on top of the existing structural solver.
The data flow is:

```
BDF file
  ↓ parse_bulk_data()
BulkData  (bulk.aeros, bulk.caero1s, bulk.paero1s, bulk.aefacts, ...)
  ↓ build_aero_model()
AeroModel (boxes, ajj, skj, djk, wg, aeros)
  ↓ solve_rigid_cl() / coupled aeroelastic solve (Phase B+)
Results   (cp, cl_section, CL, CY, CM, CDi, e, per_surface, …)
```

### Module map

| Module | Purpose |
|--------|---------|
| `sbeam/model/aero.py` | Dataclasses: `Aeros`, `Caero1`, `Paero1`, `Aefact`, `W2gj`, `Wkk`, `Aecorr`, `Set1`, `Spline2`, `Attach`, `Spline0`, `Spline1`; trim set: `Aestat`, `Aesurf`, `Aelist`, `Trim`, `Diverg`, `Trimvar`, `Trimobj`, `Trimcon` |
| `sbeam/aero/panel.py` | `AeroBox` dataclass + `mesh_caero1()` — trapezoidal box meshing, ¼c/¾c placement |
| `sbeam/aero/vlm.py` | Biot–Savart segments, horseshoe influence, AIC matrix, rigid-AOA solve |
| `sbeam/aero/integration.py` | `Skj` force integration matrix, `Djk` downwash matrix, `wg` baseline normalwash |
| `sbeam/aero/corrections.py` | `Wkk` diagonal correction, `WT1` force-match, `WT2` pressure-match |
| `sbeam/aero/aero_model.py` | `AeroModel` container + `build_aero_model()` factory |
| `sbeam/aero/spline.py` | **Phase B** — `build_g_spline()`: builds `g_slope` (n_box×n_g) and `g_disp` (3n_box×n_g) from `SPLINE2` + `ATTACH` + `SPLINE0` cards |
| `sbeam/aero/coupling.py` | `build_qaa` flexible aero stiffness `Q_aa = G_dispᵀ S_kj (A_jj*)⁻¹ D_jk G_slope`; `build_fg` baseline aero load; `build_gaf` modal GAF `Q_hh = Φᵀ Q_aa Φ` |
| `sbeam/solver/sol144.py` | `run_sol144_trim` (Schur trim solve, derivatives), `run_sol144_diverg` (DIVERG-card divergence sweep + mode shape + V_div), `run_aeroelastic_static`, `AeroCache`, `_divergence_dynamic_pressure`, `_divergence_roots` |
| `sbeam/results/f06_writer.py` | `build_f06_sol144_text` / `write_f06_sol144` — SOL 144 trim f06 blocks (shares displacement/CBAR helpers with SOL 101) |
| `sbeam/results/load_export.py` | `write_aero_load_cards` — trimmed flight loads as `FORCE`/`MOMENT` bulk cards |
| `sbeam/viewer/aero_view.py` | Plotly box mesh, cp colour map, section-load strip chart |

---

## ⚠ Known Defects — Critical Design Review 2026-06-11 (HA144A benchmark)

A design review against the MSC Nastran HA144A benchmark (Aeroelastic Analysis User's Guide
Listing 7-2) found that while the VLM core (Biot–Savart kernel, symmetry image, Göthert PG)
matches the NASTRAN rigid result to 4 significant figures (CLα = 5.0709 vs 5.07097, AE3
resolved), but the **integration, spline, and trim layers carry critical defects**. Until
the remaining AE items in `docs/30_future/00_backlog.md` (Code Review 2026-06-11) are closed:

| ID | Defect | Affected results |
|----|--------|------------------|
| AE1 | Trim solve omits the `q·Q_aa` aeroelastic feedback term | All `run_sol144_trim` output |
| ~~AE2~~ | ~~`skj`/coupling path consumes circulation Γ as if it were ΔCp (×chord_box/2 per box)~~ | **RESOLVED** — `ajj_inv_corr` row-scaled by `2/chord_box` in `build_aero_model`; CZα = 5.071 via skj path ✓ |
| ~~AE3~~ | ~~K-J lift width uses bound-segment length, not cross-flow projection~~ | **RESOLVED** — `dy = sqrt(Δy²+Δz²)`; CLα = 5.0709 ✓ |
| ~~AE4~~ | ~~SPLINE2 fails rigid-body kinematics on swept axes / offset grids (sweep projection, Hermite slope sign, DTHX semantics)~~ | **RESOLVED** — `spline.py` rewritten: slope divides by `x_hat[0]` (ZAERO §6.3), nodal-slope sign fixed, `DTHX=−1` correctly detaches; V-AE2a/b/c pass to 1e-12 ✓ |
| ~~AE5~~ | ~~URDD interpreted in basic frame (RCSID ignored) — HA144A trims to **−1g**~~ | **RESOLVED** — prescribed URDD values transformed through R_rcsid (partial-set support); `pres_values_basic` path in `run_sol144_trim`; V-AE3a gate passes ✓ |
| ~~AE6~~ | ~~Forces applied at ¾-chord collocation point, not ¼-chord bound vortex~~ | **RESOLVED** — `AeroBox.force_point = (bound_a+bound_b)/2`; `g_disp` and ATTACH lever evaluated at force_point; sol144 moment arms use `force_point[0]` ✓ |
| ~~AE7~~ | ~~No inertial trim columns; transport terms missing~~ | **RESOLVED** — `_build_inertial_cols` returns (n_g, n_labels) M_ax; translational + spin + transport terms; M_ax_a passed to Schur and derivs; 10/10 tests pass ✓ |
| ~~AE9~~ | ~~Mach fixed per model (AEROS), TRIM Mach ignored; supersonic silently clamped~~ | **RESOLVED** — per-TRIM Mach via Mach-keyed `AeroCache`; AEROS fallback + mismatch warning; supersonic guard raises; `test_ae9_mach.py` ✓ |
| AE8 | Unrestrained (mean-axis) derivative set still missing (restrained half closed analytically — Step G ✓) | SC2 high-q flexible trim |
| ~~AE10~~ | ~~SOL 144 unreachable from `main.py` — no CLI dispatch~~ | **RESOLVED** — `main.py` SOL 144 branch builds the AeroModel/AeroCache and runs `run_sol144_trim` per subcase; f06 + flight-load export written (Step 56). End-to-end `sbeam ha144a.bdf` runs ✓ |

**Do not use SOL 144 trim results for anything until AE1 and AE8 are resolved.** Rigid
`solve_rigid_cl` results on **unswept** surfaces are unaffected. AE2–AE7 are resolved;
the sections below describe the *intended* design; passages known to diverge from the
implementation carry an `⚠ AE#` marker. Reproduction script: `studies/_review_ha144a_check.py`.

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
| `SET1` | List of structural grid IDs for spline input | S45 |
| `SPLINE2` | Beam spline: links CAERO1 box range to SET1 grids via CubicHermite interpolation | S45–46 |
| `ATTACH` | Rigid attachment of box group to single master grid (Step 47, complete) | S45–47 |
| `SPLINE0` | Zero-displacement constraint — box rows in g_slope/g_disp remain zero | S45–47 |
| `SPLINE1` | Harder–Desmarais IPS surface spline (parse raises NotImplementedError; Step 48) | S45 |
| `AESTAT` | Rigid-body trim DOF label (ANGLEA, PITCH, ROLL, YAW, URDD2–URDD6) | S51 |
| `AESURF` | Aerodynamic control surface — hinge line + AELIST of active boxes | S51 |
| `AELIST` | Ordered list of CAERO1 box IDs forming a control surface | S51 |
| `TRIM` | Trim condition — Mach, q, and prescribed label/value pairs | S51 |
| `DIVERG` | Divergence analysis — NROOTS, RHOREF (V_div), and Mach sweep | S51 / S55 |
| `TRIMVAR` | Per-variable bounds + initial guess (sbeam-defined; over-determined trim) | S51 |
| `TRIMOBJ` | Weighted objective function (sbeam-defined; over-determined trim) | S51 |
| `TRIMCON` | Inequality constraint (sbeam-defined; over-determined trim) | S51 |

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
| SYMXZ | int | 0 | Parsed for NASTRAN compatibility; **must be 0** — non-zero (half-span) is rejected |
| SYMXY | int | 0 | Parsed for NASTRAN compatibility; **must be 0** — non-zero (half-span) is rejected |

### Full-span only — no symmetry models

sbeam is **full-span only**. Every lifting surface must be meshed in full (both sides of the
XZ plane); there is no symmetry-image / parity option. The `SYMXZ`/`SYMXY` fields are still
*parsed* so legacy NASTRAN decks load, but `build_aero_model` rejects any model with
`SYMXZ ≠ 0` or `SYMXY ≠ 0`:

```
ValueError: build_aero_model: half-span / symmetry models are not supported
            (AEROS SYMXZ=1, SYMXY=0). sbeam runs full-span only. Convert the deck
            with sbeam.aero.mirror.mirror_halfspan(), or rebuild it full-span, so
            that SYMXZ=SYMXY=0.
```

`mirror_halfspan(bulk)` (`sbeam/aero/mirror.py`) is a migration aid: it unfolds a half-span
deck about the XZ plane (mirrors GRID/CBAR/CONM2/RBAR/RBE2/CAERO1, clears the symmetry flags)
and raises `NotImplementedError` listing any cards — splines, control surfaces, W2GJ,
constraints — whose correct full-span form needs manual rebuilding.

### Validation rules

- **Half-span model**: `build_aero_model` raises `ValueError` if `AEROS SYMXZ ≠ 0` or
  `SYMXY ≠ 0` (see above).
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

**`horseshoe_influence(colloc, colloc_normal, box) -> float`**

Returns the normalwash (induced velocity dotted with `colloc_normal`) at `colloc` from
a unit horseshoe at `box` (ZAERO Eq. 3.49a: `NIC = n_x·UIC + n_y·VIC + n_z·WIC`).
This general dot-product formulation supports arbitrary surface orientations — horizontal
wings (n̂ ≈ +Z) and vertical fins (n̂ ≈ +Y) are treated consistently. Full-span only —
no symmetry-image vortex (both sides of the XZ plane are meshed explicitly).

**`build_ajj(boxes) -> np.ndarray`**

Assembles the n×n aerodynamic influence coefficient (AIC) matrix. `A[i, j]` is the
normalwash at collocation point `i` per unit circulation strength at horseshoe `j`.
O(n²) loop over all panel pairs.

**`solve_rigid_cl(boxes, alpha, beta=0.0, aeros=None, xref=0.0, mach=0.0, wg=None) -> dict`**

Solves the rigid-wing flow-tangency problem at angle of attack `alpha` and sideslip
`beta` (both in radians). Boundary condition per panel (ZAERO Eq. 3.28):

```
rhs[i] = -(V⃗ · n̂_i) + wg[i]  ≈ -(α·n_z[i] + β·n_y[i]) + wg[i]   for small angles
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
- `wg` — optional `(n,)` baseline normalwash (W2GJ camber/twist/built-in incidence),
  one value per box; pass `aero_model.wg`. `None` (default) is a zero vector, identical
  to the prior rigid-AoA behaviour. It is added to the RHS with the **canonical normalwash
  sign** (`+wg`; theory §2.4–2.5): wg is the downwash slope dz/dx, so a *positive* entry
  **reduces** lift (leading-edge-down / washout) and a built-in leading-edge-up incidence is
  *negative* — the same single sign the trim solver uses (`sol144.py` `w_total = w_trim +
  wg`) and the end-to-end `tests/integration/test_wg_sign_convention.py` pins. The viewer
  Aero tab passes `aero_model.wg`, so a W2GJ twist deck (e.g.
  `sample/val_wing_taper_dihedral_twist.bdf`) reads a lower CL than its un-twisted twin. The
  AoA-equivalence identity `solve_rigid_cl(α, wg=0) ≡ solve_rigid_cl(0, wg=−α·n_z)` pins the
  rigid-path sign (`TestBaselineNormalwashWg`).

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

  **dy convention (AE3 resolved):** `dy = sqrt(Δy² + Δz²)` — the projected cross-flow
  width of the bound-vortex segment. The K-J force is `F⃗ = ρV⃗∞ × ΓΔs⃗`; for
  `V⃗∞ = (1,0,0)` the lift component scales with the **y-projection** of the segment, not
  its 3-D length. The projection handles sweep and dihedral automatically. Verified:
  HA144A (Λ = 30°) CLα = 5.0709 vs NASTRAN 5.07097; CMα = −2.871 vs NASTRAN −2.871.
- `CDi`: Trefftz-plane induced drag coefficient — lift surfaces only, normalised by
  S_ref. Computed by `trefftz_cdi()` via the 2-D Biot-Savart far-field integral
  (Katz & Plotkin Eq 12.17). Relation to CL: `CDi = CL² / (π · AR · e)`.
- `e`: Oswald span efficiency — `CL² / (π · AR · CDi)`. For an elliptically loaded
  wing e = 1; a rectangular wing gives e ≈ 0.90–0.98 depending on AR and mesh.
  `nan` when CDi ≈ 0 (zero-incidence or no lift surfaces).
- `per_surface`: `{caero_eid: {surface_type, CL, CY, CM}}` — per-CAERO1 coefficients

Note: the full-span VLM solution converges to a limit ~5–10% below the Prandtl finite-span
formula `2πAR/(AR+2)`. This is an intrinsic property of the horseshoe VLM, not a bug. The
convergence is non-monotone relative to the Prandtl target (overshoots at coarse meshes, then
decreases as panels are added), but is internally consistent and converges to a stable limit.

---

## Integration Matrices (Skj, Djk, wg)

### `build_skj(boxes) -> np.ndarray`  — shape (3n, n)

Force integration matrix mapping pressure coefficient per box to resultant force vector.
Column `j`: `F_j = area_j × normal_j × cp_j` (three consecutive rows for Fx, Fy, Fz).

Usage: `F_vec = Skj @ cp_vec` → `[Fx_0, Fy_0, Fz_0, Fx_1, …]`

**Non-planar (±Γ dihedral/anhedral) surfaces** are handled with no special case: the box normal
comes straight from the z-bearing corner geometry in `mesh_caero1` (canted `(0, ∓sinΓ, cosΓ)`, not
`(0,0,1)`), so a tilted panel's force carries a side component `Fy = Fz · n_y/n_z = ∓Fz·tanΓ`. Over
a symmetric full-span build the `Fy` cancels. The whole VLM → spline → force → trim chain is gated
out of the xy-plane for Γ = ±10° by **V-C-DIH** (`tests/aero/test_dihedral.py`): geometric normal,
rigid `CL ≈ CL_planar·cosΓ`, symmetric `Fy`/roll/yaw cancellation, and a structured determined trim
(`sample/val_dihedral_trim.bdf`). The full 3-component aerodynamic moment (roll/pitch/yaw) is
available via `sol144.aero_moment_resultant`.

### `build_djk(boxes) -> np.ndarray`  — shape (n, n)

Deflection-to-downwash matrix for steady (k = 0) analysis. Returns `−I` (negative
identity): the input is the per-box **incidence** (nose-up positive) delivered by the
spline, and `w = −incidence`, so a nose-up incidence (lift-increasing) becomes a
negative normalwash. This is the *opposite* sign sense to a baseline `wg` slope (see
`build_wg`). Phase D DLM will replace this matrix with the full unsteady kernel without
changing the caller interface.

### `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray`  — shape (n,)

Baseline normalwash vector from the W2GJ BDF card. Values are dimensionless downwash
slopes Δz/Δx, one per box, in row-major order (span slowest, chord fastest). They are
added **directly** to the assembled normalwash (NASTRAN W2GJ convention — *not* passed
through `Djk`), so **positive `wg` = local nose-down / washout → less lift**, and a
leading-edge-up built-in incidence is a **negative** `wg`. Returns a zero vector if no
W2GJ card matches `caero_eid`. See `docs/20_theory/01_aeroelastics_theory.md` §2.4–2.5.

### W2GJ Card Format

```
W2GJ  SID  CAERO_EID  D1  D2  D3  D4  D5  D6
+     D7   D8  ...
```

| Field | Description |
|-------|-------------|
| SID | Set ID |
| CAERO_EID | EID of the CAERO1 this normalwash applies to |
| D1–DN | Dimensionless downwash slopes Δz/Δx, one per box in row-major order. **Positive = local nose-down / washout → less lift**; a leading-edge-up incidence is negative. (e.g. linear washout root 0° → tip −2° grows from ~0 at the root to +0.035 rad at the tip — see `sample/val_wing_taper_dihedral_twist.bdf`.) |

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

### `build_aero_model(bulk, grid_index=None) -> AeroModel`

Factory function that orchestrates the full Phase A assembly pipeline:

1. Reject half-span models — raise `ValueError` if `AEROS SYMXZ ≠ 0` or `SYMXY ≠ 0`
2. Mesh all CAERO1 elements in ascending EID order → concatenated `AeroBox` list
3. Build raw AIC matrix via `build_ajj(boxes)`
4. Apply correction at highest available tier (WKK → WT2 → WT1 → identity)
5. Build `Skj`, `Djk`, and `wg` integration quantities
6. Package into `AeroModel` and return

```python
@dataclass
class AeroModel:
    boxes: list[AeroBox]       # All AeroBox objects (concatenated across CAERO1s)
    ajj: np.ndarray            # Raw VLM AIC, shape (n, n)
    ajj_inv_corr: np.ndarray   # Corrected inverse (factored), shape (n, n)
    skj: np.ndarray            # Force integration, shape (3n, n)
    djk: np.ndarray            # Deflection-to-downwash, shape (n, n)
    wg: np.ndarray             # Baseline normalwash, shape (n,)
```

---

## Implementation Notes

### Prandtl–Glauert / Göthert Compressibility Correction

Subsonic compressibility is corrected via the **Göthert similarity rule** (see
`docs/20_theory/01_aeroelastics_theory.md` §2.8). The implementation compresses
the aerodynamic panel geometry in the spanwise and vertical directions by
β = √(1 − M²) before building the AIC, then scales the inverted AIC by 1/β:

```
Ajj_pg⁻¹ = (1/β) · Ajj(β · geometry)⁻¹
```

**Input:** the flight Mach is a property of the **flight condition** — the `TRIM`
card (AE9). `AEROS` field 8 still carries a Mach, used as the **default/fallback**
when a TRIM card omits it; a genuine TRIM-vs-AEROS disagreement is warned about.

```
AEROS, 0, 0, 2.0, 10.0, 20.0, 1, 0, 0.6   $ AEROS Mach 0.6 (fallback)
TRIM,  1, 0.9, 40.0, ...                    $ this subcase flies at Mach 0.9
```

**Per-TRIM Mach + AeroCache (AE9):** because the AIC depends on Mach, each TRIM
subcase at a distinct Mach needs its own AIC. `build_aero_model(bulk, grid_index,
mach=…)` takes a Mach override, and `sbeam.solver.sol144.AeroCache` memoizes one
AeroModel per Mach so the build-once pattern still holds across subcases.
`run_sol144_trim(bulk, subcase, aero, aero_cache=None)` resolves the TRIM Mach,
seeds the cache with the prebuilt `aero`, and fetches/builds the AIC for that Mach
(existing 3-arg callers are unchanged — their TRIM Mach matches AEROS, so no
rebuild). Multiple subsonic subcases at different Mach therefore trim correctly.

**Key design decisions:**
- `skj`, `djk`, and `wg` are built from the **physical** (unscaled) boxes — only
  the AIC computation uses the PG-compressed geometry.
- **Supersonic guard (AE9):** an effective Mach ≥ 1 raises `ValueError` in
  `build_aero_model`, `prandtl_glauert_boxes`, and `solve_rigid_cl` — the steady
  subsonic VLM cannot solve the transonic/supersonic regime (it needs ZONA51 /
  piston theory). This replaces the previous silent `min(mach, 0.99)` clamp, which
  would have returned a physically wrong answer.
- M = 0.0 (default) gives bit-identical results to the pre-correction solver.
- For M < 0.3 the correction is < 5% (within typical VLM modelling error); it can
  be omitted for low-speed work.

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
| AERODYNAMIC TOTALS (CL / CMY) | `result.total_cl`, `result.total_cm` |
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
direction components carry the physical load) from `result.grid_loads` (`g_disp^T·q·f_box`),
one card block per subcase with `SID = subcase_id`. By spline force/moment conservation the
set sums to the trimmed lift/moment.

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
  force. Re-solving the free rigid-body variables each step (free-flight self-balancing), modal
  reduction (`NMODES`), unsteady corrections, and a closed-loop control layer are Phase G0 follow-ons.
- **Output (`results/maneuver_output.py`):** an MLDPRNT ASCII time-history table
  (`<stem>.mldprnt.txt`: time, commands, aero `Fz`/`My`, closure norms, peak net load) and the
  critical-sample (peak |net force|) net-load `FORCE`/`MOMENT` export (`<stem>.maneuver_qs_loads.bdf`).
- **Gates (`tests/aero/test_maneuver_cards.py`, `tests/aero/test_maneuver_qs.py`):** card round-trip +
  validation; G0→Step 53 machine-precision identity; quasi-static settling to the new balanced trim
  (closure → 0, lift = `n_z·W`); per-step closure bounded; MLDPRNT + critical-load export round-trips.
- **Validity:** low reduced frequency `k = ω·c_ref/2V ≲ 0.05–0.1` (slow maneuvers); higher-rate inputs
  need the Phase G0 unsteady corrections or the Phase D DLM.

---

## Viewer — Aero Tab (S44)

`sbeam/viewer/aero_view.py` provides Plotly figure builders for the aerodynamic mesh
and pressure-coefficient visualisation. The Streamlit app (`app.py`) shows an "Aero"
tab automatically when `bulk.caero1s` is non-empty.

The Aero tab's **Compute Aero** button solves `solve_rigid_cl(..., wg=aero_model.wg)`, so the
**W2GJ baseline incidence (camber/twist/built-in incidence) is folded into the rigid solve**.
Two decks that differ only by a W2GJ twist therefore produce different CL/CM/cp/section loads
(e.g. the `sample/val_wing_taper_dihedral*.bdf` pair: a 0→−2° washout drops CL from 0.268 to
0.186 at α = 3°). A caption appears when a non-zero `wg` is active. The mesh *geometry* is
unchanged by twist (incidence, not shape), so the visible difference is in the cp colour map and
the section-load strip chart, not the wire-frame.

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
aero_model = build_aero_model(bulk)
result = solve_rigid_cl(aero_model.boxes, np.radians(3.0), wg=aero_model.wg)
fig = build_aero_box_figure(
    bulk, aero_model,
    cp=result["cp"],
    cl_section=result["cl_section"],
)
st.plotly_chart(fig, use_container_width=True)
```

---

## Phase B — Structure ↔ Aero Splining

### Overview

Phase B implements the structural-to-aerodynamic spline operators required for the SOL 144
static-aeroelastic trim solve (Phase C). Two separate operators are built:

| Operator | Shape | Role |
|----------|-------|------|
| `g_slope` | `(n_box, 6·n_grid)` | Maps structural DOFs → per-box streamwise incidence (feeds `Djk` in VLM solve) |
| `g_disp`  | `(3·n_box, 6·n_grid)` | Maps structural DOFs → 3-D box displacement (for virtual-work force transfer `Skjᵀ`) |

These are the `G_slope` and `G_disp` operators in the coupling equation
`Q_aa = G_dispᵀ Skj A_jj*⁻¹ Djk G_slope` (see `coupling.py`).

### SPLINE2 — Beam Spline

SPLINE2 uses a 1-D cubic Hermite spline along the spline axis (CID x-axis = span direction)
to interpolate structural grid displacements to aero box collocation points.

**Card format:**
```
SPLINE2  EID  CAERO  ID1  ID2  SETG  DZ  DTOR  CID
+        DTHX DTHZ        USAGE
```

| Field | Default | Description |
|-------|---------|-------------|
| EID   | —       | Element ID |
| CAERO | —       | CAERO1 EID of the panel being splined |
| ID1   | —       | First NASTRAN box ID in the range |
| ID2   | —       | Last NASTRAN box ID in the range |
| SETG  | —       | SET1 SID listing the structural grids |
| DZ    | 0.0     | Smoothing parameter (0.0 = interpolating Hermite) |
| DTOR  | 1.0     | Torsional/bending ratio (not used in Phase B matrix) |
| CID   | 0       | CORD2R SID defining the spline axis |
| DTHX  | 1.0     | Torsion (CID x-axis rotation) attachment switch: `1.0` = attached, `−1.0` = detached (do not couple), other values warn and treat as detached |
| DTHZ  | 0.0     | CID z-axis rotation contribution (not used in Phase B) |
| USAGE | BOTH    | FORCE / DISP / BOTH (informational; not filtered in Phase B) |

**DTHX semantics (AE4c — resolved 2026-06-11):** in MSC Nastran, SPLINE2 DTHX is a
rotational *attachment flag*, where **−1.0 means "do not attach the rotational DOF to the
spline"**. sbeam now implements this correctly: `DTHX = 1.0` couples torsion; `DTHX = −1.0`
detaches it (torsion arrives through fore/aft offset grids, as in HA144A's wing spline);
other values emit a `UserWarning` and are treated as detached.

**NASTRAN box ID convention** (must match `panel.py` row-major ordering):
```
box_id = CAERO1.EID + i_span × n_chord_boxes + j_chord
```

### CID-aware DOF projection

The SPLINE2 CID defines the spline coordinate frame. All structural DOFs are in global CID 0.
The CID rotation matrix columns provide the projection vectors:

```
origin, R_cid = _get_transform(spline2.cid, cord2rs)
x_hat = R_cid[:, 0]   # span / spline axis
y_hat = R_cid[:, 1]   # bending-slope axis (d(normal)/ds)
z_hat = R_cid[:, 2]   # surface normal / deflection direction
```

For each structural node i and global DOF d, the contributions are:

| DOF type | g_slope contribution | g_disp contribution |
|----------|---------------------|---------------------|
| Translation d < 3 | `-z_hat[d] × d(phi_f[i])/ds` | `z_hat[d] × phi_f[i](t_j) × z_hat` |
| Rotation (bending) d ≥ 3 | `-y_hat[d-3] × d(phi_d[i])/ds` | `y_hat[d-3] × phi_d[i](t_j) × z_hat` |
| Rotation (torsion) d ≥ 3 | `+dthx × x_hat[d-3] × phi_f[i](t_j)` | zero |

where `phi_f[i]` = Hermite function-value basis at node i and `phi_d[i]` = Hermite
derivative-value basis at node i (both built with `scipy.interpolate.CubicHermiteSpline`).

**For CID = 0 (basic):** z_hat = [0,0,1], y_hat = [0,1,0], x_hat = [1,0,0], so only
Tz (d=2), Ry (d=4), and Rx (d=3) contribute — the classic NASTRAN convention.

**AE4(a)/(b) — projection (resolved 2026-06-11):** the streamwise slope for a swept axis is
`w = −(dh/ds) / x_hat[0]` (ZAERO §6.3), not `−(dh/ds)`. The 1D beam spline captures the
slope along the swept axis; dividing by `x_hat[0]` (= cos Λ) recovers the physical
streamwise slope. The nodal-slope datum is `(dh/ds)_i = −(ω·ŷ)_i` (sign-corrected from
prior `+ω·ŷ`). Both are now implemented in `_build_spline2_block`.

### Rigid-body exactness (V-B1 gate)

Two properties hold analytically and are verified numerically to < 1e-12:

1. **Partition of unity:** `Σ_i phi_f[i](s) = 1` for all s. Consequence: uniform "torsion"
   displacement at all grids → uniform incidence at all boxes.

2. **Zero derivative of constant:** `Σ_i d(phi_f[i])/ds = 0` for all s. Consequence:
   uniform translational displacement (no slope) → zero downwash at all boxes.

These are the make-or-break tests for Phase C trim: a spline that fails these produces
non-physical trim solutions.

**V-B1 → V-AE2 (resolved 2026-06-11):** V-B1 (plunge and twist) was necessary but not
sufficient — rigid pitch on swept-axis and offset-grid configurations previously failed.
After the AE4 fix, the full V-AE2 gate (`TestSweptSplineRigidBody`) passes to 1e-12:
rigid plunge → zero downwash; rigid beam pitch → uniform incidence θ; g_disp evaluated at
¼-chord force_point (AE6). V-AE2 replaces V-B1 as the make-or-break spline gate.

### `build_g_spline` API

```python
from sbeam.aero.spline import build_g_spline

g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
# g_slope: np.ndarray (n_box, 6*n_grid)   or None if no spline cards
# g_disp:  np.ndarray (3*n_box, 6*n_grid) or None if no spline cards
```

Raises `ValueError` if a box is covered by more than one spline or if a SET1 has < 2 grids.
Issues `UserWarning` for un-splined boxes, >10% extrapolation, or empty box ranges.

`AeroModel` stores the operators as `aero_model.g_slope` and `aero_model.g_disp` when
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

```
g_slope[j, col_Tz] = 0.0    # plunge → zero slope
g_slope[j, col_Rx] = +1.0   # torsion coupling
g_slope[j, col_Ry] = -1.0   # pitch → uniform downwash -1

g_disp[3j+2, col_Tz] = 1.0  # normal displacement from plunge
g_disp[3j+2, col_Rx] = ry   # (ω×r)_z = Rx·ry
g_disp[3j+2, col_Ry] = -rx  # (ω×r)_z = -Ry·rx
```

Energy consistency: `∂(-rx)/∂x = -1 = g_slope[j, col_Ry]` (virtual work ✓).

**V-B3 rigid-body gate (machine precision):**
- Tz translation → zero downwash (< 1e-14)
- Ry pitch → uniform downwash -1.0 (< 1e-14)
- Force transfer: `g_disp.T @ (skj @ cp)` gives correct Fz, Mx, My at master (< 1e-12)

### SPLINE0 — Zero-Displacement Constraint (Step 47)

`SPLINE0` registers a box range as "covered" without adding any structural coupling.
All `g_slope` and `g_disp` rows for the covered boxes remain zero. Used to suppress
un-splined warnings for boxes that are intentionally uncoupled (e.g. control surfaces
or far-field boxes that do not deflect structurally).

**Card format:**
```
SPLINE0  EID  CAERO  ID1  ID2
```

`g_disp.T @ (any pressure force)` = 0 for all structural DOFs (V-B3c verified).

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
f_g         = q * g_disp.T @ f_box             # virtual-work force transfer to g-set
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
- `aero_model.g_disp` must not be `None` — call `build_aero_model` with a `grid_index`
  argument to populate the spline operators. Raises `ValueError` otherwise.
- `alpha` in radians; `q` in consistent pressure units (Pa, psf, …).

**V-B2 verification (Step 49, machine precision):**
- V-B2a: `sum(f_g[Tz_dofs]) == q * sum(f_box_z)` to < 1e-10 — exact by virtual work ✓
- V-B2b: `f_tz` within 2% of `q*CL*sref` (or `/2` for Γ-based AIC) ✓
- V-B2c: `compute_structural_loads(alpha=0) == q * build_fg(aero, g_disp)` to < 1e-12 ✓
- V-B2d: `ValueError` when `g_disp is None` ✓

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

---

### `coupling.py` — Phase C Coupling Functions

Three pure linear-algebra functions in `sbeam/aero/coupling.py` implement the
Phase C matrix chains. They operate on already-built AeroModel quantities.

#### `build_qaa(aero, g_disp, g_slope) → np.ndarray`

```
Q_aa = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope    shape (n_g, n_g)
```

| Arg | Shape | Description |
|-----|-------|-------------|
| `aero` | — | AeroModel (provides `skj`, `ajj_inv_corr`, `djk`) |
| `g_disp` | (3n_box, n_g) | Displacement spline from `build_g_spline` |
| `g_slope` | (n_box, n_g) | Slope spline from `build_g_spline` |

Returns the **g-set** Q_aa (dense, unsymmetric in general). Reduction to the
a-set is done downstream in `sol144._build_qaa_aset`.

#### `build_fg(aero, g_disp) → np.ndarray`

```
f_g = G_disp^T  S_kj  (A_jj*)^-1  w_g               shape (n_g,)
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
    aero,           # AeroModel — must have g_slope and g_disp populated
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

Mirrors the RBE3 + SPC reduction in `sol101.py`, applied to the (K, Q, f) triple:

```
1. Q_gg = build_qaa(aero, aero.g_disp, aero.g_slope)    # (n_g, n_g) dense
2. K_gg = assemble_global_stiffness(bulk)                  # (n_g, n_g) sparse CSR
3. T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
4. If RBE3 present:
     K_red = (T.T @ K_gg @ T).toarray()   # dense after NumPy @ semantics
     Q_red = T.T @ Q_gg @ T
5. Else:
     K_red = K_gg.toarray()               # dense (Q_aa is dense; system is dense anyway)
     Q_red = Q_gg
6. Partition to free a-set (SPC) → K_aa, Q_aa of shape (n_a, n_a)
7. free_dofs = g-set DOF indices for the a-set rows/cols
```

Rationale for always-dense K_aa: adding dense Q_aa to sparse K would require a
mixed-format code path; converting K to dense at this point is consistent with
the RBE3 dense-fallback precedent in `sol101.py` (Risk KC1 from the backlog).

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
  TRIM   = 10
  DIVERG = 20
```

`SubcaseControl` gains `trim_sid` and `diverg_sid` fields (both `Optional[int]`, default `None`).

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

## Step 52 — SOL 144 Trim Solver (WIP — ⚠ carries open critical defects)

`solver/sol144.py:run_sol144_trim(bulk, subcase, aero)` implements the **determined** trim
case (`n_free_labels == n_SUPORT_DOFs`) on the `aeroelastics` branch:

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

The Schur partition structure is sound (equivalent to the MSC r-set/l-set method), but the
implementation **fails the HA144A benchmark on both subcases** (measured 2026-06-11:
SC1 ANGLEA −0.098 vs +0.169191, ELEV −1.197 vs +0.492457; trim lift −8 012 lb vs +8 000 lb).
Open defects, in fix order (full detail in `docs/30_future/00_backlog.md`, Code Review
2026-06-11):

| Order | ID | Defect |
|-------|----|--------|
| ~~1~~ | ~~AE3~~ | ~~K-J lift width not projected to cross-flow~~ — **RESOLVED** ✓ |
| ~~2~~ | ~~AE2~~ | ~~Γ consumed as ΔCp throughout the coupled force path; `total_cl` divides by q twice~~ — **RESOLVED** ✓ |
| ~~3~~ | ~~AE4/AE6~~ | ~~SPLINE2 swept-axis kinematics; forces applied at ¾-chord~~ — **RESOLVED** ✓ (V-AE2 gate passes, 711 tests ✓) |
| ~~4~~ | ~~AE5/AE7~~ | ~~URDD in basic frame (trims to −1g); no inertial trim columns `M·φr`~~ — **RESOLVED** ✓ (V-AE3a gate passes, 721 tests ✓) |
| 5 | AE1 | Solve uses bare `K_aa` — the `q·Q_aa` aeroelastic feedback never enters the trim system |
| 6 | AE8 | Unrestrained (mean-axis) derivative set still missing (restrained half closed by Step G; ~~per-TRIM Mach AE9~~ and ~~derivative FD AE8/Step G~~ resolved 2026-06-12; AE10 CLI wiring open) |

Acceptance for closing Step 52 is the V-AE1 gate (backlog AE13): HA144A SC1/SC2 trim
variables vs MSC Listing 7-2 and the Table 7-1 derivative columns.

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
  `D_jx` ANGLEA column (`= −n_z`); totals via `_pitch_moment`.
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
`CZ = Σ∂Fz/∂δ / S_ref` and `CMY = _pitch_moment(∂f_box)/(S_ref·c_ref)`. This replaced the
prior finite-difference hybrid (AE8); because the trim is linear in δ the two agree to
round-off. Gate V-AE1e (partial): rigid columns unchanged (CZα 5.071, CMα −2.871), restrained
CZα 5.112 vs NASTRAN Table 7-1 5.103 (q=40) within 1%. The unrestrained (mean-axis) derivative
set and the remaining Table 7-1 restrained columns are still open on **AE8**.

### Lateral / directional rate derivatives — `C_lp`, `C_nr`, `C_lβ` (Step 52)

`_compute_rigid_derivs` and `_compute_restrained_derivs` emit the roll/yaw **moment**
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
  over the AELIST boxes (NASTRAN box ID → global box index via the spline `_build_id_to_k` map).
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
