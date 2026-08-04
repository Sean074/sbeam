# Aeroelastics Phase A — Steady VLM Aerodynamics

Phase A code standard: aerodynamic model definition, the steady VLM operator chain, AIC
corrections, and the viewer aero tab. Part of the aeroelastics guide — see
[`05_aeroelastics.md`](05_aeroelastics.md) for the architecture overview, validation
status, and supported-card table; [`05b_splining.md`](05b_splining.md) for Phase B
splining; [`05c_sol144_maneuver.md`](05c_sol144_maneuver.md) for SOL 144 trim and
maneuver loads.

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

- P1 and P4 are transformed from CP frame to global CID 0 using `get_transform()`
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
- **Cosine chordwise spacing (A7)**: `cosine_chord_fractions(nchord)` returns LE-concentrated
  half-cosine breakpoints `ξ_i = 1 − cos((π/2)·i/n)` for use in an `AEFACT` card referenced
  by `LCHORD` (NCHORD blank). Cosine spacing reaches uniform-spacing accuracy with fewer
  boxes (NASA SP-405 / DeJarnette). It is **opt-in** — uniform NCHORD meshing is unchanged,
  preserving box-for-box NASTRAN fidelity.

**Mesh-quality pre-solve warnings (A7/A8, 2026-07-05):** `build_aero_model` warns once per
VLM CAERO1 when:

- the chordwise box count is **< 4** (A7) — steady-VLM chordwise loading/moment need ≥ 4
  boxes/chord (recommended 8, or cosine spacing); lift alone converges at NCHORD = 1;
- any box aspect ratio (spanwise LE edge / mean streamwise edge) falls **outside
  [0.5, 2.0]** (A8) — high-AR boxes degrade the VLM induced-downwash kernel. The warning
  reports the out-of-band count and the worst AR. A7/A8 couple: raising NCHORD shortens
  the streamwise edge, forcing NSPAN up to hold AR ≈ 1 — size the two together.

Decoupled strip body panels (PID → PSTRIP) carry no horseshoe vortex and are exempt from
both checks.

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

Vectorized broadcast Biot–Savart (P9, 2026-08-02): `_boxes_to_arrays` gathers box
geometry into `(n,3)` arrays in **positional order** (callers pass filtered sublists —
never index by `box.k`), `_biot_savart_batch` evaluates receiver × sender pairs as
`(m,n,3)` blocks with the scalar kernel's exact float64 op order (degenerate guards
become masks), and receivers are processed in `_AJJ_CHUNK = 512`-row chunks to bound
peak temporary memory (~25 MB per temp at n = 2000). Bit-for-bit identical to the
scalar `horseshoe_influence` double loop, which is retained as the reference
implementation and test oracle (`tests/aero/test_vlm_vectorized.py`); ~120× faster at
400 boxes (6.9 s → ~0.05 s). `trefftz_cdi`'s O(n²) wake sum and `build_skj`'s scatter
are vectorized the same way (Trefftz row-sum order differs from the old interleaved
accumulation, so its equivalence gate is rel 1e-12 rather than bit-for-bit).

**`solve_rigid_cl(boxes, alpha, beta=0.0, aeros=None, xref=0.0, mach=0.0, wg=None, cp_operator=None) -> dict`**

Solves the rigid-wing flow-tangency problem at angle of attack `alpha` and sideslip
`beta` (both in radians). When `cp_operator` (the corrected ΔCp operator
`AeroModel.ajj_inv_corr`) is supplied, `ΔCp = cp_operator @ rhs` directly — so any AIC
correction (WKK / WT2) and the baked-in Prandtl–Glauert factor are honoured (and
`mach` is ignored); with no correction this is numerically identical to building and solving
the raw AIC here. Boundary condition per panel (ZAERO Eq. 3.28):

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
normal — `|n_z| ≥ |n_y|` → *lift* surface; `|n_y| > |n_z|` → *sideforce* surface. Since
DEF-M2 this labels the `per_surface` breakdown only; the **global totals are true
body-axis sums over every box**, so a VTP contributes its (near-zero) `Fz` to CZ and a
dihedral wing contributes its real `Fy` to CY, exactly as `skj` integrates them.

**Force convention (DEF-M2, resolved 2026-08-01):** every box force is
`F_j = area_j · n̂_j · cp_j` — the same object `build_skj` produces — so `CX/CY/CZ/CM`
here are *identical* to the skj-integrated totals used by SOL 144, the f06 and the
viewer's S&C derivative table. They are components of the body-axis resultant, not the
panel-normal force magnitude. On a surface with dihedral Γ the boundary condition
reduces the pressure by `cos Γ` and the projection reduces the vertical force by a
further `cos Γ`, so **CZ scales as cos²Γ** (theory §2.9, "dihedral enters twice").
Previously the totals used the force *magnitude* `2Γ‖Δs⃗‖` as if it were vertical,
overstating CZ by `1/cos Γ` (1.1547 at Γ = 30°) and silently disagreeing with every
skj-based deliverable on any canted deck.

**Returns a dict:**
- `cp`: (n,) pressure coefficient per box — `2Γ / (V∞ × box_chord)`, V∞ = 1
- `cl_section`: `{i_span: cn_strip}` — per-strip **normal-force** coefficient via
  Kutta–Joukowski (all surfaces). Deliberately *not* projected on body-z: `cn` is the
  conventional section quantity and is what `section_data` / `section_correction` ingest
  from CFD and test, so projecting it would break the correction round-trip. Only the
  global totals below are body-axis.
- `CL`: **body-axis** vertical-force coefficient (≡ `CZ`) — the box forces summed on
  global/body-z over **every** box, normalised by S_ref. This is the historical key name;
  it is **not** the wind-axis lift. It is linear in α, so the α-linearity /
  AoA-equivalence / parallel-axis-CM identities are stated in terms of it.
- `CZ`: body-axis vertical-force coefficient (explicit alias of `CL`)
- `CX`: body-axis streamwise-force coefficient. ≈ 0 — a surface-normal-pressure VLM carries no
  leading-edge suction, and incidence/camber/controls enter via normalwash (not a geometric
  panel tilt), so the only body-x force comes from genuinely out-of-plane panels.
- `CL_wind`: **wind-axis lift** coefficient (force ⊥ to U∞) — the genuine `CL`.
  `CL_wind = CZ·cosα − CX·sinα`; equals `CZ` only at α ≈ 0 (theory §5.4). Reported in the
  viewer Aero tab and (at the trim α) the SOL 144 f06 "AERODYNAMIC TOTALS".
- `CD_wind`: **wind-axis drag** coefficient (force ∥ to U∞) = the Trefftz `CDi`. Deliberately
  *not* the near-field projection `CX·cosα + CZ·sinα`, which a no-LE-suction flat-panel VLM
  computes incorrectly; the Trefftz far-field induced drag is the meaningful wind-axis drag.
- `CY`: body-axis sideforce coefficient, summed over **every** box, normalised by S_ref —
  so a canted lifting surface's side force is included, not only that of surfaces
  classified *sideforce*. It cancels to ~1e-17 over a symmetric build.
- `CM`: pitching moment about `xref`, nose-up positive — `−Σ Fz·(x_force − xref)` over
  **every** box, normalised by S_ref × c_ref. This is verbatim `sol144.pitch_moment`, the
  single source for the moment-arm convention in the trim chain. Each box load acts at its
  **¼-chord bound vortex** (not the ¾-chord collocation point) — the physically correct
  moment arm. Validated against AVL / VortexLattice.jl (`val_vlm_byu_wing`: CM −0.0209 vs
  −0.02085).

  **Width convention (AE3 resolved; clarified by DEF-M2):** `width = sqrt(Δy² + Δz²)` —
  the cross-flow-projected width of the bound-vortex segment. It sets the box chord
  (`chord_box = area / width`) and weights the Trefftz wake integral. It is **not** the
  vertical-force lever: the body-axis components come from the box normal, via
  `F_j = 2Γ_j·width_j·n̂_j ≡ area_j·n̂_j·cp_j`. Conflating the two was DEF-M2. Verified:
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

### `yaw_rate_force_scale` / `build_fjx_yaw` / `build_fj_rigidrate_yaw` (Step 67a)

The **force-side** companion to the `build_djx` `YAW` normalwash column. Yaw rate has two
effects (theory §7.2 Eq. 28): the fin sidewash `Δβ(x) = r(x−x_ref)/V`, which is a normalwash and
lives in `build_djx`; and the wing's spanwise dynamic-pressure asymmetry `ΔU(y) = −r·y`, which is
an *edgewise* velocity perturbation and therefore **cannot** be a normalwash column. The latter
scales the local load:

| Function | Shape | Meaning |
|----------|-------|---------|
| `yaw_rate_force_scale(boxes, bulk, y_ref=0)` | `(n,)` | `s_j = −(4/b_ref)(y_j − y_ref)` at the box **force point** (¼-chord), the per-unit-`YAW`-label load scaling |
| `build_fjx_yaw(boxes, f_box_ref, bulk, y_ref=0)` | `(3n,)` | `s ⊙ f_box_ref` — the load increment per unit `YAW` trim label, in `build_skj`'s force/q box-major layout |
| `build_fj_rigidrate_yaw(boxes, f_box_ref, bulk, v_inf, y_ref=0)` | `(3n,)` | the same per unit *physical* yaw rate r (rad/s), scaled through `rigid_rate_scales[6]` — the free-flight (Step 61/63) sibling |
| `build_fx_induced_drag(boxes, cp)` | `(3n,)` | Step 67b — the streamwise induced-drag field added into `f_box_ref` so the asymmetry has a drag to act on (`vlm.trefftz_box_drag` reached through `vlm.box_circulation`) |

The whole 3-vector of each box force is scaled, so a canted or vertical panel's in-plane
components come along. `f_box_ref` is the **steady** (normalwash-driven) box-force field at the
trim state; the increment is first order in ΔU/U and must not scale itself. Because the operator
depends on the trim loading, SOL 144 iterates it as a fixed point (`05c_sol144_maneuver.md`
step 3a) and the transient solvers freeze it at the IC trim.

The reference loading is the **steady** box-force field (`skj @ cp`) **plus** the streamwise
induced drag. Both derivatives come out of the same scaling: `C_lr` = `C_L`/4 from the normal
force and `C_nr` = `CDi`/4 from the drag (elliptic limits; a rectangular wing's tip-heavy
downwash pushes drag outboard, giving ~1.45× the latter). Signs differ in structure because
`Mz = x·F_y − y·F_x` carries a minus on the arm that `Mx = y·F_z − z·F_y` does not.

### `box_circulation` / `box_widths` / `trefftz_box_drag` (Step 67b)

`trefftz_box_drag(boxes, gamma)` is the per-box breakdown of the Trefftz integral,
`d_j = Γ_j·w_T,j·Δy_j`, with `Σ d ≡ CDi·S_ref` by construction — `trefftz_cdi` and it are both
thin readers of a shared `_trefftz_wake`, so the induced-drag total and its spanwise distribution
cannot drift apart. Zero on non-lift boxes and on decoupled strip bodies (no wake).
`box_circulation(boxes, cp)` inverts `cp = 2Γ/chord_box` — **`Γ_j = cp_j·area_j/(2·width_j)`** —
so a caller holding a ΔCp field (SOL 144's `gamma` *is* ΔCp) reaches the circulation without a
second solve; `box_widths` is the shared `‖Δs⃗‖`.

**Scope rule.** This drag field feeds the yaw column and nothing else. It is *not* added to the
baseline box forces, `CX`, `CD_wind` or the load export — sbeam reports `CD_wind` as the Trefftz
`CDi` rather than the near-field projection, and the symmetric part of the drag produces no yaw
moment in any case. What the trim *does* carry is the drag's **asymmetry** under a yaw rate: a
real antisymmetric fore-aft wing load whose resultant is precisely the reported wing `C_nr`.
Without a yaw rate the exported per-box forces have no streamwise component at all.

**Known limitation:** no profile drag (sbeam has no viscous model), so the wing `C_nr` is the
induced part only — an under-prediction of a damping derivative, i.e. the non-conservative
direction. A per-surface `CD0` input is backlogged.

### `build_wg(boxes, w2gjs, caero_eid) -> np.ndarray`  — shape (n,)

Baseline normalwash vector from the W2GJ BDF card. Card values follow the **NASTRAN
convention** (MSC Aeroelastic UG Eq. 2-104; HA144A: `W2GJ = +0.001745 rad` is "+0.1 deg
wing incidence"): **positive = leading-edge-up incidence/camber → more lift**, the same
nose-up-positive sense as ANGLEA. `build_wg` **negates** the card data into the internal
washout-positive normalwash — the same negation the ANGLEA column (`−n_z`) and
`build_djk` (`−I`) apply — so internally positive `wg` remains washout/less lift. One
value per box, row-major (span slowest, chord fastest). Returns a zero vector if no
W2GJ card matches `caero_eid`. (Card sign convention corrected 2026-07-05, AE8a root
cause — card data was previously added un-negated, applying deck incidence backwards.)
See `docs/20_theory/01_aeroelastics_theory.md` §2.4–2.5.

### W2GJ Card Format

```
W2GJ  SID  CAERO_EID  D1  D2  D3  D4  D5  D6
+     D7   D8  ...
```

| Field | Description |
|-------|-------------|
| SID | Set ID |
| CAERO_EID | EID of the CAERO1 this normalwash applies to |
| D1–DN | Built-in incidence/camber angles (rad), one per box in row-major order, **NASTRAN convention: positive = leading-edge-up incidence → more lift** (HA144A wing incidence is `+1.745e-3` = +0.1°); a washout twist is **negative** (e.g. linear washout root 0° → tip −2° runs from ~0 at the root to −0.035 rad at the tip — see `sample/val_wing_taper_dihedral_twist.bdf`). `build_wg` negates card data into the internal washout-positive normalwash. |

---

## AIC Corrections (Wkk, WT2)

Phase A provides two correction tiers to match VLM predictions to higher-fidelity
CFD or wind-tunnel data. The correction precedence in `build_aero_model()` is:

```
WKK card present   →  apply_wkk  (caller inverts via np.linalg.solve; per-CAERO1 scatter)
AECORR WT2 present →  apply_wt2  (returns AJJ*⁻¹) — ALL WT2 cards combined (multi-surface)
No correction      →  np.linalg.solve(AJJ, I)
```

### Card binding is validated, not lenient (DEF-M8 / DEF-L1)

A correction card that cannot be applied is an error, never a silent no-op — the builder
reporting "converged" while production never sees the card was the defect class this
closes. All checks are card-labelled (`CARDNAME sid: …`, the CHORDCP house style):

| Card | Rejected |
|------|----------|
| `W2GJ` | two cards on one CAERO1; data length ≠ that surface's box count (either direction); a `caero_eid` with no meshed boxes |
| `WKK` | two cards on one CAERO1; length ≠ that surface's box count; any **zero weight** (it zeroes an AJJ* row, making the corrected AIC singular) |
| `AECORR` (WT2) | target length ≠ that surface's box count |
| `STRIPK` | two cards on one CAERO1; length ≠ that surface's box count (omit the card entirely to take the PSTRIP `SLOPE0` default) |
| section-data CSV | `caero` not in the model (when the caller supplies the model); duplicate `eta` within one `(caero, var, mach, a_lo, a_hi)` curve |
| body TOTAL row | blank/NaN in a **required** column (`cm_a`, `cm0`, `cn_a`, `a0`); only the roll columns `cl_a`/`cl0` default to 0 |

**WKK is per-surface.** Each card applies to its own CAERO1; boxes on unlisted surfaces
take weight 1 (a no-op). Previously the card was selected by the primary (lowest-EID)
CAERO1 and then applied to every box in the operator, so a multi-surface deck raised a
bare numpy shape error and a WKK on a non-primary surface was ignored outright.

> **WT1 was removed at the first SOL 144 loads release (DEF-R7).** A third tier,
> force/moment matching by per-strip lift scaling (`AECORR METHOD=WT1`), was deprecated
> by DEF-H2/H3 (2026-07-31) and is now gone: `AECORR METHOD=WT1` raises a `ValueError`
> at read time. Use `WT2` or the section-correction path. The two defects that
> condemned it, recorded here so a legacy deck's numbers can be understood:
>
> - **DEF-H2 — wrong at Mach > 0.** The correction was handed PG-compressed boxes, so
>   the reference strip force was integrated over compressed areas and chords while the
>   Göthert `1/β` factor and the Γ→ΔCp conversion (physical chords) were applied
>   afterwards. The delivered strip force was `f_target/β²` — a **56 % overshoot at
>   M = 0.6**. Exact at M = 0 only.
> - **DEF-H3 — cross-surface aliasing.** Strips were grouped by `box.i_span`, which
>   restarts per parent CAERO1. On a multi-surface deck the card was *selected* by the
>   primary CAERO1 but *applied* to every box sharing an `i_span` index, so a wing card
>   rescaled tail strips while the wing itself missed its target.
>
> The decision was to **deprecate rather than fix**: `WT2` and the section-correction
> synthesiser (`section_correction.py`, which divides by β) are correct and strictly
> more capable.

**Multi-surface WT2.** When several CAERO1 surfaces each carry a `WT2` `AECORR`, they are
combined into one global Γ-unit target: each card fills its own surface's boxes (row-major),
and boxes on uncorrected surfaces default to the VLM reference circulation (ratio 1). `W2GJ`
baseline normalwash is already accumulated per CAERO1, so the section force+moment correction
(`section_correction.py`) works across the whole model. `WKK` acts per CAERO1.

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
| AECORR METHOD | `WT2` (pressure matching) — the only accepted value; `WT1` raises a `ValueError` (removed, DEF-R7) |
| AECORR CAERO_EID | CAERO1 EID this correction applies to |
| AECORR T1–TN | Target values; see below |

### `apply_wkk(ajj, wkk_data) -> np.ndarray`

Returns `AJJ* = diag(w) @ AJJ`. The caller (`build_aero_model`) inverts it via the
LU factorization returned by `check_conditioning` (`scipy.linalg.lu_solve`).
Simplest correction; can absorb empirical scale factors or stall nonlinearity.
Issues a `UserWarning` if the condition estimate of `AJJ*` exceeds 1e10.

### `apply_wt2(ajj, cp_target, ajj_inv=None) -> np.ndarray`

Pressure-matching correction. Returns corrected `AJJ*⁻¹` by scaling each row of
`AJJ⁻¹` by `cp_target_k / cp_vlm_ref_k`, where the reference normalwash is
`w_ref = -ones(n)` (uniform unit incidence). The fixed reference state is required:
deriving `w_ref` from `cp_target` itself yields a trivial identity correction. Boxes
with near-zero `cp_vlm_ref` (tolerance `_RATIO_TOL = 1e-12`) keep a ratio of 1.0.
`ajj_inv` may be supplied by a caller that already inverted AJJ
(`_assemble_vlm_operator` does, DEF-R6 — one factorization serves the conditioning
check, the target baseline and the correction); when omitted the function factors
AJJ itself and issues a `UserWarning` if the condition estimate exceeds 1e10.

**Conditioning (DEF-R6, 2026-08-02).** `check_conditioning` (and the section-correction
builder's equivalent) no longer runs a full SVD: it computes an LU factorization once
and estimates the **1-norm** condition via LAPACK `gecon`
(`sbeam/linalg_utils.py: estimate_cond_1norm`), returning the LU for reuse by the
solve. Reported values are 1-norm estimates (can differ from the old 2-norm SVD
numbers by up to ~n×); the 1e10 warning threshold is unchanged.

### `apply_wt1(ajj, boxes, f_target) -> np.ndarray` — DEPRECATED (DEF-H2/H3)

**Do not use on new work** — see the deprecation note above; prefer `WT2` or
`section_correction.py`. The description below is of the shipped (unfixed) behaviour.

Per-strip force-matching correction. Groups boxes by `i_span` and finds a per-strip
scalar ratio `f_target_s / f_vlm_s`. All boxes in a strip share the same correction
factor. `f_target` must have one value per distinct `i_span`; a `ValueError` is raised
on length mismatch. Uses same `w_ref = -ones(n)` reference state as WT2.

**Force only — does not move the section a.c.** Because the per-strip factor is uniform
across the chord, the chordwise ΔCp *shape* is preserved (just rescaled), so the section
centre of pressure / aerodynamic centre is unchanged and the section moment scales with
the lift. `f_target` is the surface-normal force/q **per unit reference normalwash** —
i.e. per rad of α (horizontal surface), per rad of β (vertical), per (α·cosΓ) (canted) —
a lift-curve-slope quantity, **not** an absolute force at an operating incidence, and it
produces zero load at α=0 (built-in incidence/camber must come from `W2GJ`). To match a
section *moment* (a.c.) as well, use the section-correction synthesiser below.

## CHORDCP — CFD/WT steady-pressure injection (Step 54)

The corrections above **rescale** the VLM operator toward measured data; `CHORDCP`
goes one step further and **replaces the mean flow entirely**: the per-box physical
steady Cp distribution of every VLM lifting surface, measured (CFD or wind tunnel)
at a stated reference angle of attack `ALPHREF`, becomes the SOL 144 baseline load,
and the trim variables then perturb about that injected operating point.

### How it works — equivalent-normalwash substitution

The mean flow reaches every consumer (trim RHS via `build_fg`, f06 totals,
the SOL 144 trim recovery, `maneuver_qs`, monitor points, viewer) exclusively as
`ΔCp = ajj_inv_corr @ aero.wg`, so `build_aero_model` converts the injected Cp
into an equivalent baseline normalwash and bakes it into `aero.wg`
(`corrections.apply_chordcp`, wired by `_apply_chordcp_injection`):

```
wg_eff = lstsq(ajj_inv_corr_vlm_block, Cp_inj) + n_z·α_ref
```

- The solve runs over the **VLM sub-block only** — PSTRIP strip panels keep their
  W2GJ/Δα wash (their `ajj_inv_corr` block is diagonal with zero coupling, so the
  sub-block solve is exact).
- The `+ n_z·α_ref` term (`= −D_α·α_ref`, the ANGLEA normalwash column) re-references
  the injection to α = 0, so **the solved ANGLEA is absolute**, not relative to ALPHREF.
- A min-norm `lstsq` is used because a WT2 correction can zero operator rows
  (target ratio 0); nonzero injected Cp on such a dead row is unreproducible and
  raises a `ValueError` (residual check), rather than silently losing load.
- WKK/WT2 corrections still govern the **perturbation** aerodynamics — the same
  corrected operator is used for the conversion and the trim, so injecting the
  program's own mean flow reproduces the uninjected trim exactly (the Step 54
  identity gate, `tests/aero/test_chordcp.py`).
- Multi-Mach (AE9) is automatic: injection lives inside `build_aero_model`, which
  `AeroCache` re-runs per TRIM Mach.

### Usage rules (v1)

- **Full coverage:** when any CHORDCP is present, every VLM CAERO1 must carry exactly
  one card and all cards must state the same ALPHREF (degrees on the card, stored in
  radians). Partial per-surface injection is a deferred follow-on (mixed operating
  points have ambiguous interference bookkeeping).
- **W2GJ discarded on injected surfaces** (warned): the injected Cp must already
  contain the camber/incidence — and any body-correction-derived W2GJ offsets — that
  W2GJ would have supplied.
- A nonzero ALPHREF requires an `ANGLEA` AESTAT label (error otherwise).
- `mirror_halfspan` rejects CHORDCP decks (box data is not auto-mirrored).
- Deriving new correction cards (Aero Correction viewer tab) on a CHORDCP deck is
  blocked — the derivation baselines would read the injected wash and change meaning.

### Operating-point bookkeeping & KC7 warnings

The trim result carries a `chordcp_echo` dict and the f06 trim block prints an
`INJECTED OPERATING POINT` table: ALPHREF, the data Mach, and per-surface
`Fz/q`, `My/q` integrals of the supplied Cp next to the VLM flat-plate lift at the
same ALPHREF (a plausibility reference). Warnings (KC7):

- data Mach ≠ TRIM Mach;
- trimmed ANGLEA more than 0.035 rad (≈ 2°) from ALPHREF — the trim is a
  perturbation about the injected point and degrades with distance.

## Section force + moment correction synthesiser (`section_correction.py`)

`sbeam/aero/section_correction.py` generates a **`W2GJ` + `WT2` card pair** that
together reproduce a target section line — slope **and** zero-α offset of both force and
pitching moment — with minimal change to the uncorrected chordwise distribution. It is
the preprocessor implementation of "Option A": no solver or card-schema changes; it emits
two already-supported cards that compose in the normal solve
(`cp = corrected-A⁻¹ · (w_α + w_g)`).

The four section targets split into two pairs, each handled by the mechanism that can do
it without disturbing the other (theory §3.4–3.5):

| Target pair | Meaning | Card |
|-------------|---------|------|
| `dF/dα`, `dM/dα` | force-curve slope **and** aerodynamic centre (α-driven chordwise shape) | **WT2** (per-box ratio) |
| `F₀`, `M₀` | zero-α lift offset **and** camber pitching moment (load at α=0) | **W2GJ** (camber-line normalwash) |

### `build_section_correction_multi(boxes, ajj, targets, *, sid_w2gj_base, sid_aecorr_base, beta=1.0)`

The engine. `targets` is a list of `SurfaceTargets(caero_eid, f_slope, alpha_0, m_slope,
m_0, moment_ref=None)` — one per CAERO1 to correct. Per-strip arrays are ascending
`i_span` within each surface; `f_slope` (dF/dα, force/q per rad), `alpha_0` (α₀ rad,
`F₀ = −f_slope·α₀`), `m_slope` (dM/dα, nose-up + per rad), `m_0` (M at α=0, nose-up +);
moment nose-up positive about `moment_ref` (default strip ¼-chord). Returns a
`MultiSectionCorrectionResult` with `cards[eid] = (W2gj, Aecorr)` (SIDs `base + i`), the
**global** per-box `.r`/`.wg`, and per-surface diagnostics. `boxes`/`ajj` are the **whole
model** (full AIC). `beta = √(1−M²)` carries the solver's Prandtl–Glauert 1/β factor on the
*physical* force while the WT2 card target stays in pure Γ-units (pass the raw `ajj_pg` and
`beta`, **not** `β·ajj_pg`).

### `build_section_correction(boxes, ajj, *, …, moment_ref=None, beta=1.0) -> SectionCorrectionResult`

Single-surface convenience wrapper (requires `boxes` to contain exactly one CAERO1; raises
otherwise). Returns the one surface's cards plus the (global == surface) `.r`/`.wg` and
diagnostics. `cards_to_bdf(result)` formats the pair(s) as bulk-data text — it accepts both
the single- and multi-surface result. All card text is serialized by `card_lines`, a thin
wrapper over `model/card_writers.write_card`: every real routes through
`parser/bdf_field.fmt_real8`, so each free-field token fits the strict 8-character NASTRAN
field (DEF-M12) and NaN/inf raise rather than being written out.

**Algorithm.** The WT2 ratio is calibrated on `w_ref = −ones` and is therefore independent
of `w_g`, so the build is one pass: (1) **per strip across all surfaces**, a uniform scale
`r̄ = f_slope/f_slope_vlm` hits the force with **no shape change**, plus a minimum-norm
per-box perturbation orthogonal to the force (`Σ δ·g0 = 0`) supplies only the moment/a.c.
mismatch — when the target a.c. equals the VLM a.c. (pure slope scaling), `δ = 0` and the
result degenerates exactly to a uniform per-strip scaling. (2) A two-mode camber line per strip
(uniform incidence + chordwise-linear) is sized by **one global linear solve over all
corrected strips** so the WT2-corrected operator reproduces `(F₀, M₀)` per strip exactly
(camber on one surface induces load on the others; the global solve captures it).

**Multi-surface.** The AIC is global, so the build is global: a per-box `r` (1 on
uncorrected boxes) and a global camber solve, emitted as one card pair **per surface**. The
solver combines them — see `build_aero_model` (multiple `WT2` cards → one global Γ-target;
`W2GJ` already accumulated per CAERO1).

**Constraints / guards.** Each corrected strip needs **NCHORD ≥ 2** (a moment needs two
chordwise boxes) — raises otherwise. The emitted WT2 target is in Γ-units (the `apply_wt2`
convention) and mirrors `apply_wt2`'s near-zero-reference guard so the card and the solver
operator are identical. `ajj` is the raw `ajj_pg` at the correction Mach (with `beta`); at
M=0, `beta=1`.

### Spanwise section-data input (`section_data.py`)

The viewer drives `build_section_correction` from a user table of **section coefficients**.
Section aerodynamics are a function of span, **Mach**, and incidence; the nonlinear α
dependence is captured by **linearising into regions** (e.g. a pre-onset and a post-onset
slope), each with its own coefficients and a validity range. The table is therefore a tidy
("long") CSV — one row per surface × span-station × Mach × region:

| column | meaning |
|--------|---------|
| `caero` | CAERO1 EID the row applies to |
| `eta` | span fraction within that CAERO1 (0 root → 1 tip) |
| `mach` | freestream Mach for this block |
| `var` | incidence variable: `ALPHA` (lift surface) or `BETA` (vertical) |
| `a_lo`, `a_hi` | region incidence validity range (deg) |
| `cn_a` | section normal-force slope dC_n/d(var) **per degree** |
| `a0` | zero-normal-force incidence (deg) |
| `cm_a` | section moment slope dC_m/d(var) about `xref`, **per degree** |
| `cm0` | section moment at zero incidence (nose-up +) |
| `xref` | moment reference as a chord fraction (default 0.25) |

Coefficients are **local-chord** normalised (airfoil-polar convention). For a strip of
local chord `c`, area `A = c·dy`, the GUI converts to the builder's per-rad dimensional
targets: `f_slope = cn_a·(180/π)·A`, `alpha_0 = a0·π/180`, `m_slope = cm_a·(180/π)·c·A`,
`m_0 = cm0·c·A`, `moment_ref = LE_x + xref·c`. Spanwise values are interpolated from the
table `eta` stations onto the actual mesh strip mid-spans (`AeroBox.span_frac`), clamped at
the ends with an `extrapolated` flag.

Functions: `validate_section_data(df)` (schema/typing checks); `available_conditions(df)`
→ selectable `(caero, mach, region)` blocks; `template_dataframe(boxes, caero_eid, …)` →
a starter table pre-filled with the strip `eta` stations (for `st.data_editor` / template
download); `build_from_section_data(boxes, ajj, df, *, caero_eid, mach, region, sid_w2gj,
sid_aecorr)` → `SectionDataBuildResult` (single surface); **`build_from_section_data_multi(
boxes, ajj, df, *, mach, incidence_deg, sid_w2gj_base, sid_aecorr_base, caeros=None)`** →
`MultiSectionDataBuildResult` — corrects every surface in the table at one flight point;
`operating_region(df, caero, mach, incidence_deg)` → the region whose range contains a trim
incidence.

**Multi-surface (`build_from_section_data_multi`).** Given a flight Mach **and** an
operating incidence, it picks for each CAERO1 the region whose `[a_lo, a_hi]` contains that
incidence (per-surface), interpolates and converts each, and builds **one global**
correction emitting a card pair per surface. Surfaces with no containing region are skipped
(listed in `.skipped`).

**v1 selection.** Mach is matched **exactly** against the table (no Mach interpolation),
and a **single operating region** per surface is built; the caller warns if the trimmed
incidence falls outside `[a_lo, a_hi]`. Pass `ajj` as the **raw** PG AIC at the chosen Mach
(`build_aero_model(bulk, mach).ajj`); the Prandtl–Glauert 1/β factor is applied internally
from `mach`.

**Worked example.** `sample/cessna210_flagship_bulk.bdf` +
`sample/cessna210_flagship_section_data.csv` are a full-span 5-surface Cessna 210-like model
(wing + HTP + VTP) with per-surface section data — a cambered, washed-out, two-α-region wing,
symmetric HTP, and a `BETA` VTP — exercised end-to-end by
`tests/aero/test_cessna210_example.py`. Unlike the standalone `cessna210_aero.bdf` it replaced
at Step 65, the correction here is **pre-baked into the deck** and **reaches a SOL 144 trim**;
see `docs/20_theory/02_realistic_airplane_sol144.md`.

> **The section table must be 3D-informed, not a raw 2D polar.** A VLM strip already carries
> the finite-wing downwash, so its *installed* normal-force slope is well below the airfoil
> section value — on this wing 0.086/deg at the root falling to 0.047/deg at the tip, and only
> 0.044/deg on the HTP, which additionally sits in the wing's downwash field. Tabulating the
> 2D section slope (≈0.105/deg) and letting WT2 enforce it **double-counts the downwash**: the
> wing alone is driven to 0.105 × 180/π = 6.0/rad, an unphysical finite-wing lift slope. The
> flagship table is anchored to the model's own 3D strip loading and scaled to the Helmbold
> target for AR 7.72 (4.86/rad), so the correction moves the whole-model slope by ~2 %
> (5.21 → 5.33/rad) instead of by a third.

**Aero-tab visualisation.** The viewer Aero tab passes `cp_operator=ajj_inv_corr` to
`solve_rigid_cl`, so the corrected CL / CM / cp / section loads (WKK / WT2 **and** W2GJ)
are shown directly — matching the SOL 144 operator. `viewer/aero_view.build_section_correction_figure`
gives the spanwise preview (`cn_α(η)`, `cm0(η)`; input markers vs achieved-on-strips) for the
section-correction page.

**Aero Correction page (`viewer/aero_correction_view.py`, A-GUI3 / A-GUI4).** The viewer exposes the
above pipeline as a dedicated **Aero Correction** tab (right of **Aero**). The user downloads a
mesh-seeded CSV template (`_template_csv` → `template_dataframe` per surface), fills it with the
section coefficients, and uploads it (`validate_section_data`). Picking a **condition** —
exact-match **Mach** + **operating α and β** — drives `build_from_section_data_multi(..., alpha_deg=,
beta_deg=)` at reserved SID bases (`_W2GJ_BASE = 9001`, `_AECORR_BASE = 9101`). Each surface is
corrected on **one** axis selected by its table `var` (`surface_var`): an ALPHA surface uses α, a
BETA surface uses β (the two angles may differ; `incidence_deg` remains a single-axis fallback).
`operating_region` shows the per-surface region coverage, and `surface_dihedral_deg` flags any
**canted** surface (`20° ≤ |Γ| ≤ 70°`) where a single-axis section correction blends both α and β
responses. **Apply to model** injects the generated `(W2gj, Aecorr)` pairs into
`bulk.w2gjs` / `bulk.aecorrs` (replacing the tool's own previously-injected SIDs, never stacking)
so the existing Aero tab — which keys off `bulk.wkks`/`bulk.aecorrs` — runs the corrected solve. The
Aero tab's **Cp view** toggle then compares corrected / uncorrected / Δcp on both the 3D box
pressure and the span-load curves. **Download cards (.bdf)** emits the pairs via `cards_to_bdf`;
**Full corrected BDF** (`build_corrected_bdf`) splices them into the uploaded model text before
`ENDDATA` with a provenance header (source CSV, date, Mach/α/β), giving a self-contained,
re-parseable model — one per Mach. A separate-file + `INCLUDE` layout is not used: sbeam's parser
honours only a single whole-bulk INCLUDE. Pre-existing **WKK** (which takes precedence over WT2 in
`build_aero_model`) or a non-generated WT2 on a corrected surface are flagged as warnings.

## Cruciform body panels — total-aircraft moment correction (`body_correction.py`, Step A9)

sbeam has **no body/slender-body element**, so a flat-panel airplane built only from wing + tails
gets the **overall pitch (Cm), yaw (Cn) and roll (Cl) moments** wrong (it misses fuselage lift
carry-through, cross-flow, and the body's contribution to static margin / directional & lateral
stability). The classic fix is the **cruciform**: represent the fuselage with two crossing flat VLM
surfaces — a **horizontal body panel** (XY plane, normal ≈ +Z → carries the body's lift / pitch) and
a **vertical body panel** (XZ plane, normal ≈ +Y → side-force / yaw / roll). They are ordinary
`CAERO1`s.

The correction is **two-stage**: the flying surfaces (wing/HTP/VTP) are matched to spanwise section
data (above); then the body panels absorb the **residual** so the **total airplane** matches CFD /
wind tunnel — Cm_α, Cm0 (pitch, horizontal panel) and the sideslip set Cn_β, Cn0, Cl_β, Cl0 (yaw +
roll, vertical panel). The body's lift / side-force is left at the bare VLM value (a minimum-norm
by-product) — the method is **moment-primary**, matching how the airplane total was historically
tuned by correcting the body panels after the flying surfaces.

### `build_body_correction(bulk, *, horiz_eid, vert_eid, targets, mach=None, aero=None, sid_w2gj_base=9301, sid_aecorr_base=9401, tol=1e-4)`

`horiz_eid` / `vert_eid` each accept **an `int` or a list of `int`** — a body plane may be defined by
one CAERO1 or several (e.g. a fuselage side split into a panel by the wing, one to the fin TE, and one
for the lower body). Every listed panel is tuned by **one** joint min-norm solve over all its boxes
(the per-box weights route each box to pitch / yaw / roll by its normal), and each panel emits its own
`(W2gj, Aecorr)` pair at `base + i`. Splitting a plane across more boxes gives the solve more freedom
— it generally **lowers** `ratio_max` and spreads the correction load. (Placement caveat unchanged:
keep every piece clear of the lifting surfaces.)

Returns a `BodyCorrectionResult` (`cards={eid:(W2gj, Aecorr)}`, `target`/`baseline`/`achieved`
`BodyTargets`, `residual`, `converged`, `ratio_max`). `bulk` must already carry the flying-surface
corrections; pass a pre-built flying-corrected `aero` to skip an AIC rebuild. The solve is **direct,
exact and non-iterative**, exploiting two facts (verified to ~1e-13 against `build_aero_model`):

* **Slope — WT2 per-box ratio `r` (decoupled from the flying surfaces; joint across body panels).**
  The corrected operator is `diag(r)·A⁻¹`, so a body-box ratio scales *only that box's* ΔCp — the
  body's slope contribution is linear and **decoupled from the flying surfaces**, with force held at
  the bare VLM value. Pitch (Cm_α, α-driven) is matched by the horizontal panel and yaw (Cn_β,
  β-driven) by the vertical panel; roll (Cl_β, β-driven) is matched by the vertical panel's z-arm but
  **also picks up the horizontal panel** (its small β-load carries a rolling moment via the `w_roll`
  `y·n_z` term). So all slope constraints are solved as **one joint minimum-norm system over both
  panels' boxes** — exact. (Pitch stays horizontal-only because `w_pitch = 0` on the vertical panel
  `n_z = 0`; yaw stays vertical-only because `w_yaw ≈ 0` on the horizontal panel.)
* **Offset — W2GJ baseline normalwash `wg` (coupled, solved jointly).** `wg` enters *before* the
  inverse (`cp = A⁻¹·wg`), so body camber induces load on the wing/tail too — for a long body panel
  under the wing that induced load dominates and reverses sign. Cm0, Cn0 and Cl0 are linear
  functionals of `wg` against the **actual corrected operator**, so a single joint minimum-norm
  least-squares over all body boxes hits every offset target exactly (the wing induction is accounted
  for, not fought). Slope is fixed before the offset is solved and the offset never feeds back into
  the slope, so no iteration is needed.

`ratio_max` (largest body WT2 ratio) is surfaced as a conditioning gauge. It is **not** a
contamination metric: WT2 is a post-inverse diagonal on the **body rows only**, so a large ratio
scales the body-box ΔCp without ever perturbing the lifting-surface operator rows (see *Geometry &
limitations* below). For panels held clear of the tail a ratio of **tens to ~100 is normal and
benign**; it is warned only past `RATIO_WARN = 200`, the point at which the flat-plate cruciform is
being pushed beyond what it can represent and a slender-body element is the proper tool.

### Geometry & limitations — keep the panels clear of the empennage

The body panels must be held **clear of the lifting surfaces**. A VLM box loads any other box that
lies in its neighbourhood **or that its semi-infinite +X trailing legs pass through**, so a body box
overlapping — or trailing its wake into — the HTP/VTP injects a purely numerical interaction onto the
real surfaces (exactly what the cruciform is meant to *stand in for*, not corrupt). Guidance, as
applied in `sample/cessna210_flagship_body_cruciform.bdf`:

* **Terminate ahead of the empennage** (deck: body chord ends at x=5.0, ahead of the VTP LE x=6.6 and
  HTP LE x=6.9) so no body box *and no trailing leg* reaches the tail x-station.
* **Hold the panels off the tail planes:** the horizontal panel sits below the HTP (deck z=0.30 vs HTP
  z=0.70) and the vertical panel **wholly below the VTP root** (deck z<0.45 vs root z=0.80). The
  vertical panel shares the fin's y=0 plane, so any body box at a z in the fin band (0.60–2.30) drives
  a spurious sidewash straight onto the fin — keep it under the root.
* **Keep the panels small/compact** over the forward-mid fuselage, where the body's aero actually
  acts. Smaller panels shed a smaller spurious field on the wing/tail; do **not** enlarge them to chase
  a lower `ratio_max` — bigger/closer panels lower the ratio but *raise* the contamination.

**The flat-plate cruciform can only legitimately supply a SMALL body increment.** A flat plate aft of
the moment reference makes a *stabilising* (nose-down) bare pitch — the wrong sign for a fuselage — so
a large destabilising target is only reachable by immersing the panels in the tail (the spurious
overlap above) or with an extreme, ill-conditioned correction. The cruciform is therefore a tuning
device for a **mild** dCm/dα and dCn/dβ with **~0 roll** (a slender body adds negligible Cl_β); the
`sample/cessna210_flagship_section_data.csv` `TOTAL` row is the flying-surface totals **plus a
realistic fuselage increment** of that size (+0.20 /rad in Cm_α, ~12 % of the flagship's pitch
stiffness). Large body effects — a several-MAC neutral-point shift, genuine wing-body
interference — need a true **slender-body element** (see `docs/30_future/00_backlog.md`, "Body
aerodynamic panels (slender body)"); the `Cl_β` match capability remains in the code but a clean
cruciform is expected to drive it to ≈0.

**SPLINE0 for body panels.** Body panels carry zero structural coupling (`SPLINE0`): body elastic
aero effects are negligible, and a flexible spline would smear the *fictitious* correction load onto
the fuselage beam as spurious bending. The body still drives the **total / trim Cm,Cn and all rigid
+ restrained derivatives**, because those integrate every box directly via `skj·(A⁻¹·w)` —
independent of the spline (`sol144.py` total-trim and restrained-derivative paths). The body load
does not distribute along the fuselage beam, so it produces no local bending there.

**The body load is in the trim balance (Step 64, 2026-07-31).** Until Step 64 the body force was
*only* in those direct integrals — it never entered the trim force balance or the `FORCE`/`MOMENT`
export, so a body-panel trim was silently not closed (the printed totals and the load path disagreed;
31 % lift error measured on `sample/ha144a_body_trim.bdf`). `SPLINE0` field 5 now names a master
`GRID` (default: the SUPORT grid) at which the panel's 6-component resultant is injected as a rigid
load, and every force transfer runs through `g_load` instead of `g_disp`. The f06 `INJECTED AERO
LOADS` block echoes each panel's resultant. See `05b_splining.md` "Load injection".

**CSV `TOTAL` block.** The total-aircraft targets travel in the same section-data CSV as a `TOTAL`
block (`var=TOTAL`, `caero=0`): columns `cm_a`→Cm_α, `cm0`→Cm0, `cn_a`→Cn_β, `a0`→Cn0, one row per
Mach. `split_total_rows` peels it off before `validate_section_data` (which only accepts ALPHA/BETA);
`parse_body_targets(df, mach)` reads it into `BodyTargets`.

**Aero Correction page — Stage 6 (`viewer/aero_correction_view.py`).** After the flying-surface build
the tab shows a **Body panels — total-aircraft moment match** stage (only when a body panel is
present). `_guess_body_panels` pre-selects the largest-chord +Z / +Y surfaces; the six targets
(Cm_α/Cm0, Cn_β/Cn0, Cl_β/Cl0) seed from the CSV `TOTAL` block. **Build body correction** runs
`build_body_correction` (flying cards
merged in) and shows a baseline / target / achieved / residual table plus `ratio_max`. **Apply body
panels to model** injects the flying pairs (idempotent) and the body `(W2gj, Aecorr)` pairs at reserved
SIDs (`_BODY_W2GJ_BASE = 9301`, `_BODY_AECORR_BASE = 9401`); **Download body cards (.bdf)** emits them.
Worked example: `sample/cessna210_flagship_body.bdf` (flagship bulk + cruciform overlay) +
the `TOTAL` row of `sample/cessna210_flagship_section_data.csv`
(`tests/aero/test_cessna210_body_example.py`, `tests/aero/test_cessna210_flagship_body.py`).

## Decoupled strip body panels (`strip.py` + `build_strip_body_correction`)

The cruciform above is bounded by an identity: a flat panel's authority to move the total
moment **is** the coupling that contaminates the lifting surfaces (see §3.6 of the theory
reference). The **decoupled strip body panel** removes that tension by construction.

A CAERO1 whose PID references a **`PSTRIP`** (instead of a `PAERO1`) is a strip body: it has
**no horseshoe vortex, no wake, and no AIC coupling** to or from any other box. Its block of
the ΔCp operator (`AeroModel.ajj_inv_corr`) is **diagonal**,

```
ΔCp_box = slope_box · (α·n_z + β·n_y + Δα_box),   operator diagonal = -slope_box/β
```

so `build_aero_model` excludes strip boxes from the VLM AIC inversion and scatters this
diagonal block into the operator (`sbeam/aero/strip.py`; `_assemble_vlm_operator` builds the
lifting-surface-only inverse). Two consequences, both verified in
`tests/aero/test_strip_body.py`:

* **Zero contamination.** There is no wing↔body coupling block, so adding — or moving, or
  even overlapping — a strip body changes the wing/HTP/VTP loads by *exactly* zero. The
  lifting-surface inverse is bit-identical with or without the strip present. Placement is
  therefore free; in `sample/cessna210_flagship_body_strip.bdf` it is held identical to the
  cruciform overlay only so the two variants differ in one thing (the coupling) and the
  comparison is controlled.
* **No interference either.** A decoupled element is transparent to the wing's flow, so a
  strip carries no fence / no-through-flow effect. It is a pure *load* device. The body's
  *effect on* the lifting surfaces (the fence boundary condition) is a separate, composable
  mechanism — the **image fence** (`docs/30_future/00_backlog.md`), deliberately not in the
  strip element.

**Slope.** The `PSTRIP` default `slope0` ≈ π is the per-box dΔCp/dα_local; with a uniform
per-box slope the sectional lift-curve slope equals that value, so π is "50% of the 2π
flat-plate" body fudge. A `STRIPK` card overrides the slope box-by-box (emitted by the
correction); the Δα offset rides in an ordinary `W2GJ`.

### `build_strip_body_correction(bulk, *, horiz_eid, vert_eid, targets, mach=None, aero=None, sid_w2gj_base=9301, sid_stripk_base=9501, tol=1e-4)`

The strip analogue of `build_body_correction`. Same moment-primary targets (`BodyTargets`:
Cm_α/Cm0 on the horizontal panel(s); Cn_β/Cn0/Cl_β/Cl0 on the vertical panel(s)) and the same
two-knob, slope-then-offset decoupled solve — but the body block is diagonal, so:

* **slope** is a per-box `STRIPK` value (`slope = r·slope0`, joint min-norm ratio `r`), and
* **offset** is a per-box `W2GJ` Δα that, being diagonal, induces load on **no other box** —
  Cm0/Cn0/Cl0 are purely local functionals of `wg`.

There is no WT2 ratio and no `ratio_max` conditioning concern (a large slope scaling is
benign — the panel cannot contaminate). Emits one `(W2gj, Stripk)` pair per panel;
`strip_body_cards_to_bdf` formats them. `build_strip_body_correction` raises if a named panel
is not a strip (PSTRIP-backed) CAERO1. Worked example:
`sample/cessna210_flagship_body_strip_drv.bdf` + the `TOTAL` row of
`sample/cessna210_flagship_section_data.csv`, exercised together by
`tests/aero/test_body_correction.py` and `tests/aero/test_cessna210_flagship_body.py`.
(`tests/aero/test_strip_body.py` gates the builder itself — it constructs `BodyTargets`
programmatically and reads no CSV.)

> **The correction matches moments, not lift.** `BodyTargets` constrains Cm_α/Cm0/Cn_β/Cn0/
> Cl_β/Cl0 and leaves the body's own normal force to fall out of whatever slope the panel has.
> At the `PSTRIP` default `slope0` = π the flagship strip body trims out carrying **11 % of the
> airplane weight** on the fuselage — every total exact, the trim closed, and 11 % of the lift
> taken off the wing. `sample/cessna210_flagship_body_strip.bdf` therefore sets
> `PSTRIP, 20, 0.35`, giving 2.2 % of weight against the cruciform's 2.0 %. Check what your
> body panels *carry*, not only what they correct.

The Aero Correction page Stage 6 auto-detects the panel kind from the deck (PSTRIP → strip,
PAERO1 → cruciform) and routes to the matching builder; strip body cards apply at
`_BODY_W2GJ_BASE = 9301` / `_BODY_STRIPK_BASE = 9501`.

### `build_aero_model(bulk, grid_index=None) -> AeroModel`

Factory function that orchestrates the full Phase A assembly pipeline:

1. Reject half-span models — raise `ValueError` if `AEROS SYMXZ ≠ 0` or `SYMXY ≠ 0`
2. Mesh all CAERO1 elements in ascending EID order → concatenated `AeroBox` list
3. Build raw AIC matrix via `build_ajj(boxes)`
4. Apply correction at highest available tier (WKK → WT2 → identity)
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

## Viewer — Aero Tab (S44)

`sbeam/viewer/aero_view.py` provides Plotly figure builders for the aerodynamic mesh
and pressure-coefficient visualisation. The Streamlit app (`app.py`) shows an "Aero"
tab automatically when `bulk.caero1s` is non-empty.

The Aero tab's **Compute Aero** button solves
`solve_rigid_cl(..., wg=aero_model.wg, cp_operator=aero_model.ajj_inv_corr)`, so the solve runs on
the **corrected** operator: both the **W2GJ baseline incidence** (camber/twist/built-in incidence)
and any **AIC correction (WKK / WT2)** are reflected in CL/CM/cp/section loads, matching the
SOL 144 path. Two decks that differ only by a W2GJ twist produce different loads (e.g. the
`sample/val_wing_taper_dihedral*.bdf` pair: a 0→−2° washout drops CL from 0.2669 to 0.1851
at α = 3°; both decks record the figure in their headers); a section force+moment correction likewise changes the lift-curve slope and a.c. Captions
appear when a non-zero `wg` and/or a correction method are active. The mesh *geometry* is unchanged
by twist/correction (incidence and pressure, not shape), so the visible difference is in the cp
colour map and the section-load strip chart, not the wire-frame.

When a correction card is present the tab also runs the **uncorrected** baseline
(`cp_operator=None, mach=aero_model.mach`) so it can be overlaid for comparison.

**Full-width results below the 3D view (A-GUI2):**
- `build_span_loading_figure(boxes, cp_corr, cp_unc=None, aeros=None)` — per-CAERO1 spanwise
  section normal-force `cn(η)` and section moment `cm(η)` (about each strip's local ¼-chord,
  nose-up +ve, same sign as `solve_rigid_cl`/`sol144.pitch_moment`). Boxes grouped by
  `(caero_eid, i_span)` — one line per surface; corrected solid, uncorrected dashed.
- `rigid_derivative_table(aero_model, bulk, naming, state)` — the full rigid stability & control
  derivative matrix. Reuses `build_djx` (per-label normalwash) + `sol144.compute_rigid_derivs`
  (rigid, `u_a = 0`), so the table matches the SOL 144 f06 rigid derivatives exactly without a
  trim/structure solve. Rows: ANGLEA/SIDES/ROLL/PITCH/YAW + AESURF controls; columns: the six
  force/moment coefficients per radian/label. `naming` toggles conventional aero symbols
  (CZ/CY/Cl/Cm/Cn/CX) ↔ raw SOL 144 names (CZ/CY/CMX/CMY/CMZ/CX). The vertical-force column
  stays **body-axis `CZ`** (summed z-component of the surface-normal box forces) under both
  namings — it is *not* relabelled to wind-axis `CL`. `CL` is the lift component ⊥ to U∞ and
  equals `CZ` only at α≈0 (`CL = CZ·cosα + CX·sinα`); this table carries no reference
  incidence, so a wind-axis `CL` is not formed here.
  `state` (A-GUI5) selects which AIC operator the derivatives are integrated against:
  `"corrected"` (the corrected ΔCp operator with WKK/WT2 applied — what SOL 144 uses),
  `"uncorrected"` (the raw VLM baseline at the same Mach), or `"diff"` (corrected − uncorrected).
  **The `YAW` row is the fin sidewash only.** The wing's yaw-rate contribution (Steps 67a/67b) is
  a *loading-scaled force* term (`build_fjx_yaw`), so it exists only at a trim state and is
  reported by SOL 144, not by this trim-free table — `C_lr` and the wing's `C_nr` read zero on a
  planar wing here.
  The uncorrected operator is rebuilt by `_uncorrected_cp_operator(aero_model)`, which inverts the
  stored raw `aero_model.ajj` and re-applies the Göthert `1/β` factor and the Γ→ΔCp `2/chord`
  conversion — exactly the no-correction branch of `build_aero_model` — then swaps it in via
  `dataclasses.replace` so the same `compute_rigid_derivs` integrates against it. With no
  correction cards the two operators coincide and `"diff"` is identically zero.

`build_section_correction_figure(boxes, df, data_result, caero_eid)` provides the section-correction
page's spanwise preview — `cn_α(η)` and `cm0(η)`, input markers vs achieved-on-strips.

### Public API

```python
build_aero_box_figure(
    bulk: BulkData,
    aero_model: AeroModel,
    cp: np.ndarray | None = None,
    cl_section: dict | None = None,   # i_span → float, from solve_rigid_cl()
    cp_corr: np.ndarray | None = None,
    box_disp: np.ndarray | None = None,
    show_normals: bool = False,
    strip: bool = True,               # False → scene-only (Aero tab)
) -> go.Figure
```

Returns a two-row subplot (or a scene-only figure when `strip=False`):
- **Row 1 (75%)** — Plotly 3D scene with the aerodynamic box mesh (Scatter3d wire-frame)
  and, when `cp` is provided, a triangulated Mesh3d panel coloured by cp (`colorscale="RdBu_r"`).
- **Row 2 (25%)** — *(only when `strip=True`)* 2D bar chart of section CL vs span fraction. When
  `cp_corr` is also provided, two Scatter lines overlay spanwise mean cp for inviscid vs corrected.
  The Aero tab passes `strip=False` (span loading is its own full-width `build_span_loading_figure`);
  the SOL 144 results view keeps the default.

### Internal helpers

| Function | Row | Description |
|----------|-----|-------------|
| `_add_box_mesh(fig, boxes)` | 1 | Single Scatter3d wire-frame; each quad closed as `[0,1,2,3,0,None]` |
| `_add_cp_contour(fig, boxes, cp)` | 1 | Mesh3d triangulated quads; cp→vertex intensity |
| `_add_section_load_strip(fig, boxes, cl_section)` | 2 | Bar chart of `i_span`→CL using `box.span_frac` (legacy strip; `strip=True` only) |
| `_add_corrected_vs_inviscid(fig, boxes, cp_inv, cp_corr)` | 2 | Two Scatter lines: spanwise mean cp per strip (`strip=True` only) |
| `_apply_aero_layout(fig, strip=True)` | — | Orthographic camera, axis labels; strip-axis titles only when `strip` |
| `_strip_cn_cm(boxes, idx, cp)` | — | Per-strip section `cn` (area-weighted) and `cm` about local ¼-chord, for `build_span_loading_figure` |

### Typical usage in the viewer

```python
aero_model = build_aero_model(bulk)
result = solve_rigid_cl(aero_model.boxes, np.radians(3.0),
                        wg=aero_model.wg, cp_operator=aero_model.ajj_inv_corr)
# 3D mesh + corrected cp (scene only — span loading is a separate figure)
fig = build_aero_box_figure(bulk, aero_model, cp=result["cp"], strip=False)
st.plotly_chart(fig, use_container_width=True)
# Per-surface span loading + rigid S&C derivative table
st.plotly_chart(build_span_loading_figure(aero_model.boxes, result["cp"]),
                use_container_width=True)
st.dataframe(rigid_derivative_table(aero_model, bulk, naming="aero"))
```
