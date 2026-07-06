# Aeroelastics — Steady VLM, Splining, SOL 144 Trim & Quasi-Steady Maneuver Loads (Phases A–C, G0)

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
Results   (cp, cl_section, CL≡CZ, CX, CL_wind, CD_wind, CY, CM, CDi, e, per_surface, …)
```

### Module map

| Module | Purpose |
|--------|---------|
| `sbeam/model/aero.py` | Dataclasses: `Aeros`, `Caero1`, `Paero1`, `Aefact`, `W2gj`, `Wkk`, `Aecorr`, `Set1`, `Spline2`, `Attach`, `Spline0`, `Spline1`; trim set: `Aestat`, `Aesurf`, `Aelist`, `Trim`, `Diverg`, `Trimvar`, `Trimobj`, `Trimcon` |
| `sbeam/aero/panel.py` | `AeroBox` dataclass + `mesh_caero1()` — trapezoidal box meshing, ¼c/¾c placement |
| `sbeam/aero/vlm.py` | Biot–Savart segments, horseshoe influence, AIC matrix, rigid-AOA solve |
| `sbeam/aero/integration.py` | `Skj` force integration matrix, `Djk` downwash matrix, `wg` baseline normalwash |
| `sbeam/aero/corrections.py` | `Wkk` diagonal correction, `WT1` per-strip force-match, `WT2` pressure-match |
| `sbeam/aero/section_correction.py` | Synthesise a per-surface `W2GJ`+`WT2` card pair matching section force **and** moment (slope + α=0 offset): `build_section_correction_multi` (engine, all surfaces at once), `build_section_correction` (single-surface wrapper), `cards_to_bdf()` |
| `sbeam/aero/section_data.py` | Spanwise section-coefficient table ingestion (tidy CSV) → strip targets → builder: `validate_section_data`, `available_conditions`, `template_dataframe`, `build_from_section_data` (single), `build_from_section_data_multi` (per-surface at one flight point), `operating_region` |
| `sbeam/aero/body_correction.py` | **Step A9** — cruciform body-panel total-aircraft moment match: `build_body_correction` (direct linear solve: joint WT2 slope + joint W2GJ offset on the body panels so the TOTAL Cm_α/Cm0, Cn_β/Cn0, Cl_β/Cl0 hit targets), `BodyTargets`, `split_total_rows` / `parse_body_targets` (CSV `TOTAL` block), `body_cards_to_bdf`; **Step A10** — `build_strip_body_correction` / `strip_body_cards_to_bdf` (decoupled strip body: STRIPK slope + W2GJ Δα) |
| `sbeam/aero/strip.py` | **Step A10** — decoupled strip body panels (PSTRIP/STRIPK): `is_strip_caero`, `strip_box_mask`, `strip_box_slopes` (diagonal, zero-coupling ΔCp operator block — cannot contaminate the lifting surfaces) |
| `sbeam/aero/aero_model.py` | `AeroModel` container + `build_aero_model()` factory (block-diagonal strip body block via `_assemble_vlm_operator`) |
| `sbeam/aero/mirror.py` | Half-span → full-span model mirroring (symmetry deprecation; raises on unsupported cards) |
| `sbeam/aero/spline.py` | **Phase B** — `build_g_spline()`: builds `g_slope` (n_box×n_g) and `g_disp` (3n_box×n_g) from `SPLINE2` + `ATTACH` + `SPLINE0` cards |
| `sbeam/aero/coupling.py` | `build_qaa` flexible aero stiffness `Q_aa = G_dispᵀ S_kj (A_jj*)⁻¹ D_jk G_slope`; `build_fg` baseline aero load; `build_gaf` modal GAF `Q_hh = Φᵀ Q_aa Φ` |
| `sbeam/solver/sol144.py` | `run_sol144_trim` (Schur trim solve, derivatives), `run_sol144_diverg` (DIVERG-card divergence sweep + mode shape + V_div), `run_aeroelastic_static`, `AeroCache`, `_divergence_dynamic_pressure`, `_divergence_roots` |
| `sbeam/solver/maneuver_qs.py` | **Phase G0** — `run_maneuver_qs`: Level-1 quasi-steady, open-loop, restrained l-set Newmark-β transient maneuver integration |
| `sbeam/model/maneuver.py` | Dataclasses for the ZAERO `MLOADS`/`MLDTRIM`/`MLDTIME`/`MLDCOMD`/`MLDPRNT` + `TABLED1` card set |
| `sbeam/model/maneuver_presets.py` | Canned pilot-command history presets |
| `sbeam/results/f06_writer.py` | `build_f06_sol144_text` / `write_f06_sol144` — SOL 144 trim f06 blocks (shares displacement/CBAR helpers with SOL 101) |
| `sbeam/results/load_export.py` | `write_aero_load_cards` — trimmed flight loads as `FORCE`/`MOMENT` bulk cards |
| `sbeam/results/monitor_points.py` | `integrate_monpnt1` / `integrate_monpnt3` — monitor-point integrated section loads |
| `sbeam/results/maneuver_output.py` | MLDPRNT ASCII time-history + critical-sample `FORCE`/`MOMENT` export |
| `sbeam/viewer/aero_view.py` | Plotly box mesh, cp colour map, section-load strip chart |

---

## Validation status & known limitations

The SOL 144 trim solver is **validated and usable**. The 2026-06-11 HA144A design review
(MSC Nastran Aeroelastic Analysis User's Guide, Listing 7-2) found critical defects in the
integration, spline, and trim layers — all of which (AE1–AE7, AE9, AE10, AE11) are now
**resolved and closed** (see `docs/40_history/00_completed_development.md` and CHANGELOG).
The VLM core matches the NASTRAN rigid result to 4 significant figures (CLα = 5.0709 vs
5.07097); the **AE1 trim acceptance gate is CLOSED (2026-06-13)** — both HA144A subcases
trim within the ≤1%-full-scale gate (measured ≤0.4% FS), and the rigid derivative column is
gated within 0.5% of the independent ADA370433 Table 3.1.1 values (V-AE1g). Permanent
regression gates: V-AE1 (trim), V-AE2 (swept-spline rigid body), V-AE3 (coupling-path
cross-check), V-C-DIH (dihedral ±Γ), V-C4/V-LAT (over-determined trim, lateral derivatives),
V-C5 (maneuver-load closure).

One documented, accepted residual remains (Study A2,
`docs/20_theory/studies/a2_wing_root_interference.md` — Step AC8 close-out 2026-07-05):

| ID | Limitation | Severity | Impact |
|----|-----------|----------|--------|
| AE15 | **Wing-root interference residual (investigated and ACCEPTED, Step AC8 2026-07-05)**: the HA144A q=1200 pitching-moment/ELEV columns carry a 2.9–5.3% residual vs Table 7-1 (restrained CMα +4.3%, CZδe −2.9%, CMδe +5.2%; unrestrained inherits it; CZα/CZq/CMq gated live at ≤2/2.5%; all q=40 columns ≤0.2%). Study A2 attribution: sbeam's VLM is implementation-correct (independent DLR PanelAero agrees to 1.6e-8 at operator level and to 4+ decimals through the flexible chain); the residual is a canard-wake/wing-root interference **discretization** difference — MSC's steady AIC is near-mesh-converged on the coarse 8×4 mesh where a horseshoe VLM is not (sbeam at NCHORD=8–12 lands within ~0.5–2.3% of NASTRAN's coarse-mesh values). Kept as six `xfail` gates citing the study. Modeling guidance: align upstream/downstream spanwise breakpoints; use NCHORD ≥ 8 on wake-washed surfaces. | MINOR (accepted residual) | Moment/ELEV flexible columns 3–5% off at q=1200 on the NASTRAN-comparison mesh |

**AE14 closed (2026-07-05, Step AC7):** two root causes found and fixed. (1) The full-span
HA144A deck had NOT doubled the centreline fuselage PBAR when mirroring (masses were
doubled, stiffness was not) — the fuselage flexed ×2, driving 5–28% derivative errors at
q=1200 and the entire AE8a "accepted trim bias" (with the fix the q=40 trim matches
NASTRAN Listing 7-2 to 5 digits, superseding the AE8a residual note). (2) SPLINE2 was
rewritten as the NASTRAN infinite beam spline (see the SPLINE2 section), eliminating the
canard chordwise-camber contamination and the missing twist-gradient term.

**AE8b closed (2026-07-05):** the unrestrained (mean-axis / inertia-relief) derivative column is
now computed by `sol144._compute_unrestrained_derivs` — the MSC SOL 144 algorithm (MSC Aeroelastic
Analysis UG Eqs. 2-111…2-134), validated at q=40 against Table 7-1 (all six longitudinal
derivatives ≤1%, W2GJ intercepts ≤1%) and proven operator-correct at both q by an independent
ZAERO Ch. 12 modal mean-axis cross-check (agreement to 4+ decimals). See
`docs/40_history/00_completed_development.md` Step AC2.

Reproduction script for the original review: `studies/_review_ha144a_check.py`.

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
| `SPLINE2` | NASTRAN infinite beam spline: links CAERO1 box range to SET1 grids (rigid chord arms, DTOR/DTHX/DTHY flexibilities) | S45–46, AC7 |
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
| `SUPORT` | Rigid-body support DOFs (r-set) for the trim Schur partition | S52 |
| `PSTRIP` | Decoupled strip body panel property (nominal per-box slope, default π) | A10 |
| `STRIPK` | Per-box slope override for strip body panels | A10 |
| `AECOMP` | Named collection of AELIST boxes or SET1 grids for monitor points | MON1 |
| `MONPNT1` | Aero-only integrated section load at a reference point | MON1 |
| `MONPNT3` | Aero + inertia + reaction integrated section load (splined to grids) | MON1 |
| `MLOADS` | Transient maneuver driver (Phase G0; ZAERO card set) | G0 |
| `MLDTRIM` | Initial-condition TRIM sid for the maneuver | G0 |
| `MLDCOMD` | Pilot command label → `TABLED1` history | G0 |
| `MLDTIME` | Integration window t0/tend/dt/tout | G0 |
| `MLDPRNT` | ASCII time-history output request | G0 |
| `TABLED1` | Tabular function of time (command histories) | G0 |

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
O(n²) loop over all panel pairs.

**`solve_rigid_cl(boxes, alpha, beta=0.0, aeros=None, xref=0.0, mach=0.0, wg=None, cp_operator=None) -> dict`**

Solves the rigid-wing flow-tangency problem at angle of attack `alpha` and sideslip
`beta` (both in radians). When `cp_operator` (the corrected ΔCp operator
`AeroModel.ajj_inv_corr`) is supplied, `ΔCp = cp_operator @ rhs` directly — so any AIC
correction (WKK / WT1 / WT2) and the baked-in Prandtl–Glauert factor are honoured (and
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
normal — `|n_z| ≥ |n_y|` → *lift* surface (contributes to CL and CM); `|n_y| > |n_z|`
→ *sideforce* surface (contributes to CY). This ensures VTP sideforce is not added to
wing CL on multi-surface models.

**Returns a dict:**
- `cp`: (n,) pressure coefficient per box — `2Γ / (V∞ × box_chord)`, V∞ = 1
- `cl_section`: `{i_span: CL_strip}` — per-strip coefficient via Kutta–Joukowski (all surfaces)
- `CL`: **body-axis** vertical-force coefficient (≡ `CZ`) — lift surfaces only, normalised
  by S_ref. This is the historical key name; it is the force summed on global/body-z, **not**
  the wind-axis lift. It is linear in α, so the α-linearity / AoA-equivalence / parallel-axis-CM
  identities are stated in terms of it.
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

## AIC Corrections (Wkk, WT1, WT2)

Phase A provides three correction tiers to match VLM predictions to higher-fidelity
CFD or wind-tunnel data. The correction precedence in `build_aero_model()` is:

```
WKK card present   →  apply_wkk  (caller inverts via np.linalg.solve; primary CAERO1)
AECORR WT2 present →  apply_wt2  (returns AJJ*⁻¹) — ALL WT2 cards combined (multi-surface)
AECORR WT1 present →  apply_wt1  (returns AJJ*⁻¹; primary CAERO1)
No correction      →  np.linalg.solve(AJJ, I)
```

**Multi-surface WT2.** When several CAERO1 surfaces each carry a `WT2` `AECORR`, they are
combined into one global Γ-unit target: each card fills its own surface's boxes (row-major),
and boxes on uncorrected surfaces default to the VLM reference circulation (ratio 1). `W2GJ`
baseline normalwash is already accumulated per CAERO1, so the section force+moment correction
(`section_correction.py`) works across the whole model. `WKK` and `WT1` still act on the
primary CAERO1 only.

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
the single- and multi-surface result.

**Algorithm.** The WT2 ratio is calibrated on `w_ref = −ones` and is therefore independent
of `w_g`, so the build is one pass: (1) **per strip across all surfaces**, a uniform scale
`r̄ = f_slope/f_slope_vlm` hits the force with **no shape change**, plus a minimum-norm
per-box perturbation orthogonal to the force (`Σ δ·g0 = 0`) supplies only the moment/a.c.
mismatch — when the target a.c. equals the VLM a.c. (pure slope scaling), `δ = 0` and the
result degenerates exactly to the uniform WT1 scaling. (2) A two-mode camber line per strip
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

**Worked example.** `sample/cessna210_aero.bdf` + `sample/cessna210_section_data.csv` are a
full-span 5-surface Cessna 210-like model (wing + HTP + VTP) with per-surface section data —
a cambered, two-α-region wing, symmetric HTP, and a `BETA` VTP — exercised end-to-end by
`tests/aero/test_cessna210_example.py`.

**Aero-tab visualisation.** The viewer Aero tab passes `cp_operator=ajj_inv_corr` to
`solve_rigid_cl`, so the corrected CL / CM / cp / section loads (WKK / WT1 / WT2 **and** W2GJ)
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
benign**; it is warned only past `_RATIO_WARN = 200`, the point at which the flat-plate cruciform is
being pushed beyond what it can represent and a slender-body element is the proper tool.

### Geometry & limitations — keep the panels clear of the empennage

The body panels must be held **clear of the lifting surfaces**. A VLM box loads any other box that
lies in its neighbourhood **or that its semi-infinite +X trailing legs pass through**, so a body box
overlapping — or trailing its wake into — the HTP/VTP injects a purely numerical interaction onto the
real surfaces (exactly what the cruciform is meant to *stand in for*, not corrupt). Guidance, as
applied in `sample/cessna210_body.bdf`:

* **Terminate ahead of the empennage** (deck: body chord ends at x=5.0, ahead of the VTP LE x=6.6 and
  HTP LE x=6.9) so no body box *and no trailing leg* reaches the tail x-station.
* **Hold the panels off the tail planes:** the horizontal panel sits below the HTP (deck z=0.30 vs HTP
  z=0.70) and the vertical panel **wholly below the VTP root** (deck z<0.45 vs root z=0.60). The
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
`sample/cessna210_body.bdf` `TOTAL` targets are the flying-surface totals **plus a realistic fuselage
increment** of that size. Large body effects — a several-MAC neutral-point shift, genuine wing-body
interference — need a true **slender-body element** (see `docs/30_future/00_backlog.md`, "Body
aerodynamic panels (slender body)"); the `Cl_β` match capability remains in the code but a clean
cruciform is expected to drive it to ≈0.

**SPLINE0 for body panels.** Body panels carry zero structural coupling (`SPLINE0`): body elastic
aero effects are negligible, and a flexible spline would smear the *fictitious* correction load onto
the fuselage beam as spurious bending. The body still drives the **total / trim Cm,Cn and all rigid
+ restrained derivatives**, because those integrate every box directly via `skj·(A⁻¹·w)` —
independent of the spline (`sol144.py` total-trim and restrained-derivative paths). Consequence: the
body correction load does **not** appear in fuselage CBAR internal loads (correct — it is a tuning
load, not a real airload).

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
Worked example: `sample/cessna210_body.bdf` + `sample/cessna210_body_section_data.csv`
(`tests/aero/test_cessna210_body_example.py`).

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
  therefore free; in `sample/cessna210_strip.bdf` it is chosen only for physical moment-arm
  realism, not to dodge the tail.
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
is not a strip (PSTRIP-backed) CAERO1. Worked example: `sample/cessna210_strip.bdf` +
`sample/cessna210_body_section_data.csv` (`tests/aero/test_strip_body.py`).

The Aero Correction page Stage 6 auto-detects the panel kind from the deck (PSTRIP → strip,
PAERO1 → cruciform) and routes to the matching builder; strip body cards apply at
`_BODY_W2GJ_BASE = 9301` / `_BODY_STRIPK_BASE = 9501`.

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
  The f06 gains a transient-maneuver block per MLOADS subcase
  (`f06_writer.py::build_f06_sol144_maneuver_text`, AC5: run summary, time-history table with
  critical-sample marker, critical-sample closure/displacement/CBAR detail); the viewer offers
  the two ASCII/BDF exports as download buttons on the maneuver results view. Sample deck:
  `sample/ha144a_fullspan_mloads.bdf` (ELEV ramp pitch-up on the HA144A full-span model).
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

The Aero tab's **Compute Aero** button solves
`solve_rigid_cl(..., wg=aero_model.wg, cp_operator=aero_model.ajj_inv_corr)`, so the solve runs on
the **corrected** operator: both the **W2GJ baseline incidence** (camber/twist/built-in incidence)
and any **AIC correction (WKK / WT1 / WT2)** are reflected in CL/CM/cp/section loads, matching the
SOL 144 path. Two decks that differ only by a W2GJ twist produce different loads (e.g. the
`sample/val_wing_taper_dihedral*.bdf` pair: a 0→−2° washout drops CL from 0.268 to 0.186 at
α = 3°); a section force+moment correction likewise changes the lift-curve slope and a.c. Captions
appear when a non-zero `wg` and/or a correction method are active. The mesh *geometry* is unchanged
by twist/correction (incidence and pressure, not shape), so the visible difference is in the cp
colour map and the section-load strip chart, not the wire-frame.

When a correction card is present the tab also runs the **uncorrected** baseline
(`cp_operator=None, mach=aero_model.mach`) so it can be overlaid for comparison.

**Full-width results below the 3D view (A-GUI2):**
- `build_span_loading_figure(boxes, cp_corr, cp_unc=None, aeros=None)` — per-CAERO1 spanwise
  section normal-force `cn(η)` and section moment `cm(η)` (about each strip's local ¼-chord,
  nose-up +ve, same sign as `solve_rigid_cl`/`sol144._pitch_moment`). Boxes grouped by
  `(caero_eid, i_span)` — one line per surface; corrected solid, uncorrected dashed.
- `rigid_derivative_table(aero_model, bulk, naming, state)` — the full rigid stability & control
  derivative matrix. Reuses `build_djx` (per-label normalwash) + `sol144._compute_rigid_derivs`
  (rigid, `u_a = 0`), so the table matches the SOL 144 f06 rigid derivatives exactly without a
  trim/structure solve. Rows: ANGLEA/SIDES/ROLL/PITCH/YAW + AESURF controls; columns: the six
  force/moment coefficients per radian/label. `naming` toggles conventional aero symbols
  (CZ/CY/Cl/Cm/Cn/CX) ↔ raw SOL 144 names (CZ/CY/CMX/CMY/CMZ/CX). The vertical-force column
  stays **body-axis `CZ`** (summed z-component of the surface-normal box forces) under both
  namings — it is *not* relabelled to wind-axis `CL`. `CL` is the lift component ⊥ to U∞ and
  equals `CZ` only at α≈0 (`CL = CZ·cosα + CX·sinα`); this table carries no reference
  incidence, so a wind-axis `CL` is not formed here.
  `state` (A-GUI5) selects which AIC operator the derivatives are integrated against:
  `"corrected"` (the corrected ΔCp operator with WKK/WT1/WT2 applied — what SOL 144 uses),
  `"uncorrected"` (the raw VLM baseline at the same Mach), or `"diff"` (corrected − uncorrected).
  The uncorrected operator is rebuilt by `_uncorrected_cp_operator(aero_model)`, which inverts the
  stored raw `aero_model.ajj` and re-applies the Göthert `1/β` factor and the Γ→ΔCp `2/chord`
  conversion — exactly the no-correction branch of `build_aero_model` — then swaps it in via
  `dataclasses.replace` so the same `_compute_rigid_derivs` integrates against it. With no
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

### CID-aware DOF projection

All structural DOFs are in global CID 0. The spline CID provides the projections:

```
origin, R_cid = _get_transform(spline2.cid, cord2rs)
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

### `build_g_spline` API

```python
from sbeam.aero.spline import build_g_spline

g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)
# g_slope: np.ndarray (n_box, 6*n_grid)   or None if no spline cards
# g_disp:  np.ndarray (3*n_box, 6*n_grid) or None if no spline cards
```

Raises `ValueError` if a box is covered by more than one spline, a SET1 has < 2 grids,
or a spline system is singular (e.g. EA-only collinear SET1 with DTHY < 0 — no twist
information). Issues `UserWarning` for un-splined boxes, >10% extrapolation, empty box
ranges, DTOR ≤ 0, or DZ < 0.

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
set and the remaining Table 7-1 restrained columns are still open on **AE8b** (backlog Step AC2).

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
