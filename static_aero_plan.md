# sbeam — Static Aeroelasticity Plan (Phases A, B, C)

Code architecture and step-by-step development plan for adding subsonic aeroelastic
capability to `sbeam`. This document covers **Phase A (steady VLM aerodynamics, baseline
incidence & corrections)**, **Phase B (structure↔aero splining)**, and **Phase C (SOL 144
static aeroelastics + trim + divergence, incl. balanced maneuver loads)**, with reserved
placeholders for **Phase D (Doublet Lattice unsteady AIC)**, **Phase E (SOL 145 flutter)**,
**Phase F (SOL 146 gust / dynamic aeroelastic)**, **Phase G0 (quasi-steady transient maneuver
loads — DLM-free)**, and **Phase G (MLOADS — transient maneuver loads)**.

**Application context driving the priorities below:** subsonic, **conventional airplane
configuration**, with **aerodynamic corrections supplied from high-fidelity CFD or
wind-tunnel test**. This context is reflected in the plan: the aerodynamic *correction layer*
(force/moment and pressure matching, plus a baseline camber/twist/incidence downwash) is
treated as a **first-class Phase A/C deliverable**, not an afterthought — see the
`static_aero_plan_zaero_review.md` companion review for the rationale and the ZAERO
cross-reference.

Scope discipline (held across all phases):

- **Flat lifting surfaces only** — `CAERO1` macroelements meshed into trapezoidal boxes.
  No interference/slender bodies (`CAERO2`), no rings.
- **Subsonic** — VLM (Phase A) and DLM (Phase D) only; no supersonic / piston theory.
- **Splines target the CBAR beam elements** — `SPLINE2` (beam spline) is primary;
  `SPLINE1` (surface spline) is optional. Rigid-body attachment (`ATTACH`) and
  zero-displacement (`SPLINE0`) reuse the existing `RBE2`/`RBE3` machinery.
- **Aerodynamic corrections (steady, k = 0)** — three tiers, all in subsonic/static scope and
  needing no DLM: (1) diagonal multiplicative `Wkk`; (2) additive baseline/correction
  downwash `w_g` (`W2GJ`: camber, twist, incidence, plus an additive CFD/WT `Δα`); (3)
  full-matrix **force/moment matching** (`WT1`) and **pressure matching** (`WT2`) to reproduce
  a CFD or wind-tunnel load distribution. This correction layer is the primary application
  driver.
- Same non-certification disclaimer as the rest of `sbeam`: educational/exploratory,
  validated against published cases, **not** a means of compliance.

Step numbering continues from the backlog (next free number is **Step 39**), and every
step follows the project step format (Objective · Scope/Deliverables · Test/Acceptance ·
Key decisions/risks). On completion each step updates `docs/completed_development.md` and
removes itself from this plan, per the project documentation rule in `CLAUDE.md`.

---

## 1. Architecture Overview

Aeroelasticity is **three new layers bolted onto the existing structural spine** — it does
not modify the Euler-Bernoulli core (`assembly/stiffness.py`, `assembly/mass_matrix.py`):

```
                         ┌─────────────────────────────────────────────┐
   STRUCTURAL (exists)   │ BulkData → assemble_global_stiffness  → K     │
                         │           assemble_global_mass        → M     │
                         │           build_grid_index            → g-DOF │
                         └───────────────┬─────────────────────────────┘
                                         │ G_kg  (spline, Phase B)
                         ┌───────────────┴─────────────────────────────┐
   AERO GEOMETRY (new)   │ AeroModel: CAERO1 → boxes (k,j)               │
                         │            collocation pts, normals, areas    │
                         │            baseline downwash w_g (camber/twist)│
                         └───────────────┬─────────────────────────────┘
                                         │ AJJ*, w_g  (VLM + corrections, Phase A)
                         ┌───────────────┴─────────────────────────────┐
   AERO FORCES (new)     │ q · Skj · AJJ*⁻¹ · (Djk·G_kg·u + w_g) → P_k   │
                         └───────────────┬─────────────────────────────┘
                                         │ G_kgᵀ  (force transfer)
                         ┌───────────────┴─────────────────────────────┐
   COUPLED SOLVERS (new) │ SOL 144 trim / divergence (Phase C)          │
                         │ SOL 145 flutter (Phase E)  ← needs Phase D    │
                         │ SOL 146 gust (Phase F)     ← needs Phase D    │
                         └─────────────────────────────────────────────┘
```

### 1.1 Matrix nomenclature (NASTRAN aeroelastic convention)

These symbols are used throughout; they map directly onto the MSC/NX *Aeroelastic Analysis
User's Guide* (Rodden & Johnson) and the ZAERO correction theory so future readers can
cross-reference.

| Symbol | Meaning | Built in |
|--------|---------|----------|
| `w_j`  | Downwash (normalwash) at aero box `j` from structural deflection, normalised by freestream | VLM / spline |
| `w_g`  | **Baseline/additional normalwash** `W2GJ`: camber + twist + incidence, plus additive CFD/WT `Δα` correction. Present at zero structural deflection. | Phase A |
| `AJJ`  | Inviscid aero influence coefficient: `{w_j} = [AJJ]{cp}` (subsonic; real for VLM, complex for DLM) | Phase A / D |
| `AJJ*` | **Corrected** AIC after applying the chosen correction (`Wkk`, `WT1`, or `WT2`) | Phase A |
| `cp`   | Pressure coefficient on each box | solve `AJJ*⁻¹ (w_j + w_g)` |
| `Skj`  | Integration matrix: box pressures → box resultant forces (area weighting) | Phase A |
| `Djk`  | Differentiation/substantial-derivative matrix: box deflection → downwash | Phase A (k=0) |
| `Wkk`  | Diagonal multiplicative correction on the inviscid AIC (lift-curve-slope / sweep tuning) | Phase A |
| `WT1`  | **Force/moment correction matrix**: `[AIC*] = [WT1][AIC]`, matches given spanwise lift/torque | Phase A |
| `WT2`  | **Pressure (downwash) weighting matrix**: `[AIC*] = [AIC][WT2]`, matches given `{cp}` | Phase A |
| `G_kg` | Spline matrix: structural g-DOF → aero box deflection & slope | Phase B |
| `Q_aa` | Generalised aero stiffness on structural DOF: `G_kgᵀ Skj AJJ*⁻¹ Djk G_kg` | Phase C |
| `q`    | Dynamic pressure ½ρV² | TRIM / FLFACT |

The single relation that ties it all together for **static aeroelastics** (now including the
baseline-incidence load):

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg          (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g                 (camber/twist/incidence + CFD/WT)
```

with **divergence** being the eigenvalue problem `det(K_aa − q·Q_aa) = 0` for the smallest
positive `q` (the `w_g`/`Q_ax` right-hand side does not affect the divergence eigenvalue).

### 1.2 New module tree

```
sbeam/aero/
├── __init__.py
├── aero_model.py     # AeroModel container: derived numeric model (boxes + matrices),
│                     #   built from BulkData the way grid_index/K are built. Caches AJJ,
│                     #   AJJ*, Skj, Djk, Wkk/WT1/WT2, w_g, rigid-load columns. Analogous
│                     #   role to assembly/*.
├── panel.py          # CAERO1 → trapezoidal box meshing; collocation (¾c) & vortex (¼c)
│                     #   points, box areas, outward normals, chord/span fractions.
├── vlm.py            # Phase A: steady VLM AIC (AJJ at k=0), horseshoe-vortex normalwash;
│                     #   symmetric AND antisymmetric image-vortex assembly.
├── integration.py    # Phase A: Skj force-integration, Djk downwash-from-deflection,
│                     #   w_g baseline-incidence column (camber/twist/incidence).
├── corrections.py    # Phase A: Wkk diagonal + additive Δα + WT1 (force/moment matching)
│                     #   + WT2 (pressure matching) correction-matrix assembly.
├── spline.py         # Phase B: SPLINE2 beam spline (primary) + SPLINE1 IPS (optional)
│                     #   + ATTACH rigid-body / SPLINE0 zero-displacement → G_kg.
├── dlm.py            # ░ PLACEHOLDER Phase D ░ unsteady AIC AJJ(k, M); Albano–Rodden kernel.
└── flutter_aero.py   # ░ PLACEHOLDER Phase E ░ generalised aero Q(k, M) on modal basis.

sbeam/solver/
├── sol101.py         # (exists)
├── sol103.py         # (exists) — provides modal basis reused by Phase C (modal-ready trim)
│                     #            and Phase E
├── sol144.py         # Phase C: static aeroelastic trim (determined + over-determined),
│                     #   CFD/WT steady-pressure injection, flexible derivatives, divergence
├── sol145.py         # ░ PLACEHOLDER Phase E ░ flutter (p-k); reuses SOL 103 modes + dlm.py
├── sol146.py         # ░ PLACEHOLDER Phase F ░ gust / random response; reuses SOL 111 + dlm.py
├── maneuver_qs.py    # ░ PLACEHOLDER Phase G0 ░ quasi-steady transient maneuver loads — NO DLM:
│                     #   Ω×r incidence + 2-D apparent mass + Wagner strip-lag; steady VLM + time integ.
└── mloads.py         # ░ PLACEHOLDER Phase G ░ transient maneuver loads (state-space + control);
                      #   reuses SOL 103 modes + dlm.py (RFA) + the mode-acceleration recovery
```

### 1.3 Parser & data-model changes

`BulkData` (in `model/bulk_data.py`) gains aero card dicts, following the existing
flat-container pattern (one dict per card type, keyed by ID). Parsed cards stay raw; the
**derived numeric model** (boxes, AIC, corrections, splines) is built lazily in
`aero/aero_model.py`, mirroring how `assemble_global_stiffness` derives `K` from `BulkData`.

New dataclasses in `model/aero.py` (new file): `Caero1`, `Paero1`, `Aefact`, `Aeros`,
`W2gj`, `Wkk`, `Aecorr`, `Spline1`, `Spline2`, `Attach`, `Spline0`, `Set1`, `Trim`, `Trimvar`,
`Trimobj`, `Trimcon`, `Aestat`, `Aesurf`, `Aelist`, `Diverg`, `Chordcp`.

`BulkData` additions (Phase A/B/C only; D/E/F reserved):

```python
# --- Aero geometry (Phase A) ---
caero1s: dict   # {eid: Caero1}
paero1s: dict   # {pid: Paero1}
aefacts: dict   # {sid: Aefact}
aeros:   object # single AEROS reference-geometry card (or None)
# --- Aero corrections (Phase A) ---
w2gjs:   dict   # {sid: W2gj}    baseline/additive normalwash columns (camber/twist/incidence/Δα)
wkks:    dict   # {sid: Wkk}     diagonal multiplicative correction
aecorrs: dict   # {sid: Aecorr}  force/moment (WT1) or pressure (WT2) matching spec + target data
# --- Splines (Phase B) ---
spline1s: dict  # {eid: Spline1}
spline2s: dict  # {eid: Spline2}
attaches: dict  # {eid: Attach}  rigid-body attachment (reuses RBE2/RBE3 transform)
spline0s: dict  # {eid: Spline0} zero-displacement boxes
set1s:    dict  # {sid: Set1}
# --- Static aeroelastic trim (Phase C) ---
trims:    dict  # {sid: Trim}
trimvars: dict  # {id: Trimvar}  per-variable bounds/initial guess (over-determined trim)
trimobjs: dict  # {sid: Trimobj} objective function (over-determined trim)
trimcons: dict  # {sid: Trimcon} constraint functions (over-determined trim)
aestats:  dict  # {id: Aestat}
aesurfs:  dict  # {id: Aesurf}
aelists:  dict  # {sid: Aelist}
divergs:  dict  # {sid: Diverg}
chordcps: dict  # {sid: Chordcp} input steady Cp distribution (CFD/WT) for trim mean-flow
# --- RESERVED Phase D/E/F ---
# mkaero1s, flutters, flfacts, gusts  → add when those phases start
```

New `bdf_reader.py` handlers mirror the dict list above; each reuses the existing
multi-continuation accumulation pattern already used by `SPC1`/`RBE2`/`RBE3`.

**Card provenance note.** `CAERO1`, `PAERO1`, `AEFACT`, `AEROS`, `W2GJ`, `WKK`, `SPLINE1/2`,
`SET1`, `AESTAT`, `AESURF`, `AELIST`, `TRIM`, `DIVERG`, `CHORDCP` follow MSC/NX NASTRAN
conventions. The over-determined-trim cards (`TRIMVAR`, `TRIMOBJ`, `TRIMCON`), the
force/moment & pressure matching card (`AECORR`), and the spline `ATTACH`/`SPLINE0` are
**ZAERO-inspired, sbeam-defined** (no direct NASTRAN SOL 144 equivalent); their semantics
are documented at the step where they are introduced.

### 1.4 Case control, results, viewer

- **Case control** (`parser/case_control.py`): recognise `SOL 144`, and the subcase
  selectors `TRIM = sid`, `DIVERG = sid`, plus output requests `AEROF` (aero box forces)
  and `APRES` (aero box pressures). `SubcaseControl` gains `trim_sid`, `diverg_sid`.
- **Results** (`results/results.py`): new `Sol144Result` (trim variables, flexible
  stability/control derivatives, divergence q, box pressures/forces, structural
  displacement, recovered CBAR loads, **grid flight-load vectors**).
- **f06** (`results/f06_writer.py`): new blocks — TRIM VARIABLES, STABILITY DERIVATIVES,
  AERODYNAMIC DIVERGENCE (q_div per mode), AERODYNAMIC PRESSURES/FORCES, plus the existing
  displacement & CBAR-force blocks (reused). A separate **flight-load export** writes the
  trimmed grid loads as `FORCE`/`MOMENT` bulk-data cards for downstream stress runs.
- **Viewer** (`viewer/`): aero box mesh overlay on the structural geometry, spline
  connection lines (struct grids ↔ aero boxes), pressure-coefficient contour, trim &
  derivative tables, divergence-q readout. New module `viewer/aero_view.py`.

---

## 2. Phase A — Steady Vortex-Lattice Aerodynamics, Baseline Incidence & Corrections

**Goal:** Produce the inviscid steady aero matrices (`AJJ` at k=0, `Skj`, `Djk`), the
**baseline-incidence downwash `w_g`** (camber/twist/incidence), and the **correction layer**
(`Wkk`, `WT1`, `WT2`) for flat lifting surfaces, standalone (rigid aero), verifiable against
published VLM lift/moment data and against the ability to reproduce a supplied CFD/wind-tunnel
load — **before** any structural coupling exists.

**Method:** Classical horseshoe-vortex lattice (NASA SP-405). Each `CAERO1` macroelement
is meshed into `NCHORD × NSPAN` trapezoidal boxes (uniform, or `AEFACT`-driven non-uniform
spacing). Per box: a bound vortex segment at the box ¼-chord, trailing legs to infinity
downstream, and a collocation point at the box ¾-chord on the surface. The flow-tangency
boundary condition (zero net normal velocity at each collocation point) yields a linear
system for the vortex strengths; `AJJ` is the normalwash influence matrix and its inverse
maps downwash to pressure.

VLM is the **k = 0 limit of the DLM** — the box geometry, `Skj`, and `Djk` built here are
reused unchanged in Phase D, so build them with that reuse in mind.

### Step 39 — Aero reference data, coordinate & symmetry handling
- **Objective:** Parse `AEROS` (reference chord `CREF`, span `BREF`, area `SREF`,
  symmetry flags `SYMXZ`/`SYMXY`) and resolve the aerodynamic coordinate system; establish
  the symmetric / antisymmetric loading convention.
- **Scope:** `model/aero.py` `Aeros` dataclass; `_handle_aeros`; reuse existing `CORD2R`
  for the aero coord (`ACSID`). Validate exactly one `AEROS`. **Symmetry handling: half-model
  with both symmetric and antisymmetric reflection about the x-z plane** — carry a loading
  parity flag through the model so that lateral-directional (antisymmetric) trim is possible
  later, not just symmetric lift. Document the freestream direction (aero x-axis = flow).
- **Test/Acceptance:** Parser unit test round-trips an `AEROS` card; symmetry flag stored;
  value error if `AEROS` missing when a `CAERO1` is present; parity flag selectable.
- **Risk:** Aero coord vs structural CID 0 mismatch — all aero geometry resolves to CID 0
  internally (same convention as the structural model).

### Step 40 — CAERO1 box meshing (`panel.py`)
- **Objective:** Mesh each `CAERO1` into trapezoidal boxes with collocation points, bound
  vortex endpoints, areas, and outward normals.
- **Scope:** `Caero1`/`Paero1`/`Aefact` dataclasses + handlers. `CAERO1` geometry: root
  leading-edge point `P1`, root chord `X12`, tip leading-edge `P4`, tip chord `X43`,
  `NSPAN`/`NCHORD` (or `LSPAN`/`LCHORD` → `AEFACT` fraction lists). Output: a flat,
  globally-indexed list of boxes (the aero `k`-set), each with corner coords, ¼c bound
  vortex segment, ¾c collocation point, area, normal. `PAERO1` is a no-op stub (no bodies).
- **Test/Acceptance:** A 1×1 box and an N×M mesh on a known rectangular planform reproduce
  expected box corner coordinates, total area = planform area, collocation points at ¾c.
- **Risk:** Off-by-half-box errors in ¼c/¾c placement are the classic VLM bug — assert
  geometric placement directly in tests.

### Step 41 — Steady VLM AIC with symmetric/antisymmetric images (`vlm.py`)
- **Objective:** Assemble `AJJ` (k=0) via the horseshoe-vortex normalwash influence and
  solve a rigid wing for span loading, with both symmetric and antisymmetric image options.
- **Scope:** Biot–Savart influence of each horseshoe vortex on each collocation point;
  assemble influence matrix; impose flow tangency for a rigid angle of attack; recover
  circulation, box `cp`, section `c_ℓ`, and total `C_L`/`C_M`. **Handle x-z symmetry by
  adding mirror-image vortex contributions with the correct sign for the symmetric
  (mirror lift) and antisymmetric (opposed lift, for roll/yaw) cases**, selected by the
  Step 39 parity flag.
- **Test/Acceptance (validation V-A1):** Rectangular planform, several aspect ratios —
  `C_Lα` converges with mesh refinement toward lifting-line / SP-405 tabulated values
  (within a few %). Mesh-independence demonstrated (e.g. 4×10 vs 8×20 boxes). Antisymmetric
  case produces zero net lift and a pure rolling moment for an antisymmetric incidence.
- **Risk:** AIC near-singularity at coarse mesh; trailing-leg self-influence sign; image
  sign error in the antisymmetric case. Verify the isolated-horseshoe self-induced downwash
  against the closed-form value.

### Step 42 — Integration, deflection-downwash, and baseline incidence `w_g`
- **Objective:** Build `Skj` (pressure→force), `Djk` (deflection/slope→downwash), and the
  **baseline-incidence downwash column `w_g`** (`W2GJ`).
- **Scope:** `integration.py`: `Skj`, `Djk`, and a `w_g` builder. `w_g` is the per-box
  normalwash present at zero structural deflection, assembled from (a) airfoil **camber**,
  (b) built-in **twist/washout**, (c) root **incidence**, and (d) an optional additive CFD/WT
  `Δα` per box. Input via the `W2GJ` card (per-box list, `AEFACT`-driven), reusing the
  meshing fraction lists from Step 40. Fix the convention: `w_g` is a **dimensionless slope**
  (normalwash / freestream), consistent with `Djk`.
- **Test/Acceptance:** A rigid flat plate has `w_g = 0`. A uniform geometric incidence in
  `w_g` reproduces the Step 41 rigid-AOA span loading exactly. A linear twist distribution
  produces the expected linearly-varying section load. `Skj`-integrated total force equals
  the direct circulation sum (consistency check).
- **Risk (KA3):** Downwash-vs-slope convention drift across `Djk`/`w_g`/`Wkk`/spline — pick
  one (dimensionless slope) and document it at every definition site. For a conventional wing
  the camber/twist part of `w_g` carries most of the rigid load; an error here silently biases
  every trim solution.

### Step 43 — AIC corrections: `Wkk`, force/moment matching, pressure matching
- **Objective:** Build the steady (k = 0) correction layer so the model can reproduce a
  CFD or wind-tunnel load, and assemble/cache the full `AeroModel`.
- **Scope:** `corrections.py` provides three tiers, selected per run:
  1. **`Wkk`** — diagonal multiplicative weighting, `AJJ* = Wkk·AJJ` (default identity; the
     existing W2GJ/WKK convention). Cheapest; local lift-curve-slope/sweep tuning.
  2. **`WT2` pressure matching** (Pitt–Goodman downwash weighting) — solve for `WT2` such
     that `{cp_given} = [AJJ⁻¹][WT2]{w}` reproduces a supplied per-box pressure
     distribution; `AJJ* = AJJ·WT2`-equivalent corrected inverse.
  3. **`WT1` force/moment matching** (Giesing) — solve for `WT1` such that integrated
     spanwise lift & torque match a supplied `{F_given}`; `AJJ* = WT1·AJJ`-equivalent.

  Targets (`{cp_given}` or `{F_given}`) are supplied on the `AECORR` card (method flag +
  `AEFACT`/`CHORDCP` target lists). `aero_model.py` assembles and caches `AJJ`, the corrected
  `AJJ*⁻¹`, `Skj`, `Djk`, `Wkk`/`WT1`/`WT2`, `w_g`, and the rigid-load columns.
- **Test/Acceptance (validation V-A3):** With no correction, results match Step 41. **A
  force/moment-matching correction reproduces a supplied spanwise lift/torque distribution to
  tolerance** (round-trip: feed the inviscid load back as the target → recover identity). A
  pressure-matching correction reproduces a supplied `{cp}` per box. A non-unit diagonal `Wkk`
  scales the affected box lift by the expected factor.
- **Risk:** `WT1`/`WT2` conditioning when target data is sparse or noisy — regularise and warn
  on high condition number; document that only the **in-phase (steady)** correction is valid
  at k = 0 (out-of-phase / ZTAW recovery is deferred to Phase D).

### Step 44 — Viewer: rigid aero visualisation (optional but recommended)
- **Objective:** Render the aero box mesh, rigid `cp`, and the baseline-incidence load in
  the Streamlit viewer.
- **Scope:** `viewer/aero_view.py` — Plotly mesh overlay on structural geometry; per-box
  `cp` colour map; section-load plot; overlay of corrected vs inviscid load when an `AECORR`
  is active.
- **Test/Acceptance:** AppTest integration test renders without error for a sample wing;
  visual smoke test.

---

## 3. Phase B — Structure ↔ Aero Splining

**Goal:** Build the `G_kg` matrix mapping structural displacements/rotations (g-set, 6 DOF
per `GRID`) to aero box deflection and slope, with the transpose `G_kgᵀ` transferring aero
box forces back to structural nodes. Energy-consistent (virtual-work) coupling.

**Method (primary — SPLINE2 beam spline):** Fit a 1-D beam spline along a reference axis
(the `CORD2R` x-axis supplied on the `SPLINE2` card) through the structural grids in a
`SET1`. The beam spline carries **bending deflection + slope** and **torsional rotation**
(ratio set by `DTHX`/`DTHZ`), the natural match for `sbeam`'s CBAR DOFs.

**Method (rigid attachment — ATTACH / SPLINE0):** Box groups with no local FEM grid (control
surfaces, tips, nacelles/pylons) are tied rigidly to a master grid; pinned boxes are held
fixed. These reuse `sbeam`'s existing `RBE2`/`RBE3` rigid transforms.

**Method (optional — SPLINE1 surface spline):** Harder–Desmarais Infinite-Plate Spline
(IPS) for 2-D scatter of grids. Heavier; include only if a beam axis is a poor fit.

### Step 45 — SET1 + SPLINE2 parsing
- **Objective:** Parse `SET1` (grid lists), `SPLINE2` (beam spline: `CAERO1` box range,
  `SET1` ref, spline coord `CID`, `DTHX`/`DTHZ` rotation constraints).
- **Scope:** `Set1`/`Spline2` dataclasses + handlers; multi-continuation `SET1` grid lists.
- **Test/Acceptance:** Round-trip a `SPLINE2` referencing a box range and a `SET1`; resolve
  grid IDs and box IDs; error on dangling references.

### Step 46 — SPLINE2 beam-spline matrix (`spline.py`)
- **Objective:** Construct the `G_kg` block for each `SPLINE2`: aero box deflection/slope as
  a function of the spline-axis grids' translation + rotation DOFs.
- **Scope:** Beam-spline (one-dimensional smoothing-spline) interpolation along the axis;
  project structural grids and aero collocation points onto the axis; solve the small spline
  coefficient system; assemble the dense `G_kg` rows for the spanned boxes. Torsion couples
  to box incidence (downwash) via `DTHX`.
- **Test/Acceptance (validation V-B1):** **Rigid-body check** — a rigid structural
  translation produces uniform box deflection and zero induced downwash; a rigid pitch
  produces uniform box slope. **Linear check** — a linear twist distribution along the axis
  reproduces exactly at the boxes (beam spline is exact for linear fields). Round-trip
  energy check: `G_kgᵀ` applied to a uniform pressure yields the correct total force/moment
  at the grids.
- **Risk:** Spline-system conditioning (collocation points far off-axis); torsion/bending
  DOF mapping sign. The rigid-body test is the gate — it must pass to machine precision for
  the trim solution to be trustworthy.

### Step 47 — ATTACH rigid-body spline + SPLINE0 zero-displacement
- **Objective:** Tie box groups with no local FEM grid to a master grid (`ATTACH`), and pin
  selected boxes (`SPLINE0`), so control surfaces, tips, and carry-through panels can be
  modelled.
- **Scope:** `Attach`/`Spline0` dataclasses + handlers; assemble the corresponding `G_kg`
  rows by **reusing the existing `RBE2`/`RBE3` rigid-body transforms** (`build_rbe3_transformation`)
  rather than a new kinematic implementation — the master-grid lever-arm mapping is identical.
  `SPLINE0` rows are zero (box deflection forced to zero).
- **Test/Acceptance (validation V-B3):** A rigid translation/rotation of the master grid
  produces the exact rigid-body box motion (machine precision); a `SPLINE0` box shows zero
  deflection under any structural motion; `G_kgᵀ` returns the resultant force/moment to the
  master grid correctly.
- **Risk:** Double-splining a box (caught by the existing "box splined more than once" check);
  master-grid DOF set mismatch — reuse the RBE2/RBE3 DOF bookkeeping already validated.

### Step 48 — SPLINE1 surface spline (optional)
- **Objective:** Harder–Desmarais IPS for general 2-D grid scatter.
- **Scope:** `Spline1` dataclass + handler; IPS kernel `r²ln r²`; assemble `G_kg`.
- **Test/Acceptance:** Reproduces rigid-body and linear fields exactly; matches a published
  IPS example. **Deferrable** — Phase C can proceed with SPLINE2 + ATTACH only.

### Step 49 — Force transfer & coupled smoke test
- **Objective:** Wire `G_kgᵀ` force transfer and verify the full rigid-aero → structural
  load path end-to-end (no flexibility yet), including the baseline-incidence load.
- **Scope:** `aero_model.py` exposes `structural_loads = G_kgᵀ · q · P_k(rigid + w_g)`. Apply
  as a load vector to the existing SOL 101 path; confirm total lift/moment reacts correctly
  at the SPCs.
- **Test/Acceptance (validation V-B2):** Rigid wing at fixed AOA (and with a camber/twist
  `w_g`): SPC reactions equal total aero lift and pitching moment to within integration
  tolerance.

---

## 4. Phase C — SOL 144 Static Aeroelastics, Trim & Divergence

**Goal:** Couple Phases A+B into the structural stiffness to solve the flexible static
aeroelastic problem: trim (determined **and over-determined**), flexible stability/control
derivatives, optional CFD/WT mean-flow injection, and divergence dynamic pressure.

**Governing equation (restrained, g-set reduced to a-set after SPC):**

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg     (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g            (baseline camber/twist/incidence + CFD/WT)
```

**Trim:** assemble the rigid + flexible + inertial equilibrium and solve for the unknown
trim variables (`AESTAT` rigid-body states: angle of attack/sideslip `ANGLEA`/`SIDES`, rates
`ROLL`/`PITCH`/`YAW` = p/q/r, and accelerations `URDD2`–`URDD6` = lateral/vertical/roll/pitch/
yaw; `AESURF` control surface deflections), constrained by the `TRIM` card. **Balanced
maneuver loads** are the trim solution at a prescribed load factor / angular acceleration: the
aerodynamic loads are balanced by the **inertia-relief load** `f_inertial = −M_aa · a` (the
mass matrix times the rigid-body acceleration field, reusing the existing `M_aa`, `CONM2`, and
GPWG machinery — `GRAV` already builds `f = M·a`). The solver supports both the **determined**
square system and the **over-determined** system (more trim variables than equilibrium
equations) via constrained minimization. **Divergence:** solve the eigenvalue problem
`K_aa φ = q · Q_aa φ` for the smallest positive `q` (and its mode), per `DIVERG`.

### Step 50 — Aero stiffness assembly `Q_aa` + modal-truncation ROM
- **Objective:** Assemble the flexible aero stiffness `Q_aa` on the structural a-set, and
  provide an optional **modal-truncation reduced-order model** built on the SOL 103 basis.
- **Scope:** `aero_model.py`: `Q_aa = G_kgᵀ Skj AJJ*⁻¹ Djk G_kg`; reduce g-set→a-set using
  the existing SPC partition (`apply_spcs`) and RBE3/RBAR transform (reuse
  `build_rbe3_transformation`). Dense `Q_aa` (aero is fully populated) added to sparse `K`
  via the existing dense-fallback path. Direct (a-set) solve is the **default** for beam
  models (exact and cheap).

  **Modal-truncation ROM (chosen reduction method):** project onto the SOL 103 free-vibration
  mode set `Φ` (the truncated basis), forming the generalised system
  `Φᵀ(K_aa − q·Q_aa)Φ · ξ = Φᵀ(q·Q_ax·δ_x + q·f_g + f_ext)`. For a free aircraft the basis is
  the **6 rigid-body modes + the retained elastic modes** (inertia relief handled by the
  rigid-body partition, consistent with the `AESTAT` trim states). This mirrors ZAERO's modal
  trim approach and is the basis Phase E flutter will reuse.

  **Static-load recovery — mode-acceleration method (required, not optional):** pure
  mode-displacement recovery (`u_a = Φξ`) underconverges static loads because truncated
  high-frequency modes carry real static flexibility. Recover instead by the **mode-acceleration
  method** — add the static flexibility correction `u_a = Φξ + K_aa⁻¹(f − (K_aa−q·Q_aa)Φξ)` — or
  equivalently augment `Φ` with **residual (attachment) vectors** for the aero, `f_g`, and
  external load patterns. CBAR loads are then recovered from the corrected `u_a` via
  `recover_bar_forces` unchanged. `K_aa⁻¹` reuses the existing factorisation from the direct
  solve path, so the correction is cheap.
- **Test/Acceptance (validation V-C3):** `Q_aa` symmetry/structure sanity; dimensions match
  a-set; for `q→0` the system reduces to plain SOL 101 (identity against the existing SOL 101
  suite). **Modal ROM vs direct:** trim *displacements and recovered CBAR loads* agree to a
  documented tolerance, and a **mode-count convergence study** shows the mode-acceleration
  recovery converging far faster than mode-displacement (which is the demonstration that the
  residual correction is doing its job).
- **Risk (KC1):** Mixing dense `Q_aa` with sparse `K` — follow the existing dense-fallback
  pattern in `solve_static`/`solve_modes` (RBE3 branch already produces dense).
- **Risk (KC8):** Modal truncation error on static trim loads — mitigated by the
  mode-acceleration / residual-vector recovery above (a gate: mode-displacement-only recovery
  is not acceptable for loads). Document the retained-mode count and modal-mass-fraction
  guidance; include rigid-body modes for free-aircraft trim.

### Step 51 — Trim card set parsing (AESTAT / AESURF / AELIST / TRIM / DIVERG / over-determined)
- **Objective:** Parse the static aeroelastic trim cards, including the over-determined-trim
  set, and the case-control selectors.
- **Scope:** `Aestat`/`Aesurf`/`Aelist`/`Trim`/`Diverg` dataclasses + handlers; `AESURF`
  references an `AELIST` of aero boxes forming the control surface; `TRIM` fixes Mach, `q`,
  and the constrained trim variables. **Over-determined set (ZAERO-inspired, sbeam-defined):**
  `TRIMVAR` (per-variable bounds + initial guess), `TRIMOBJ` (weighted objective function
  over trim functions), `TRIMCON` (inequality constraint functions). **Maneuver states:**
  recognise the full `AESTAT` rigid-body set — rates `ROLL`/`PITCH`/`YAW` and accelerations
  `URDD2`–`URDD6` — so a balanced maneuver (load factor, angular acceleration) can be
  prescribed. Case control `TRIM=`, `DIVERG=`. Encode the longitudinal/lateral DOF-count rule
  (NX/NZ/QDOT vs NY/PDOT/RDOT) as a pre-solve validator.
- **Test/Acceptance:** Round-trip each card; resolve control-surface box lists; error when a
  `TRIM` references undefined `AESTAT`/`AESURF` labels; the longitudinal/lateral count
  validator flags an under-specified square sub-system before the solve.

### Step 52 — SOL 144 trim solve + flexible derivatives (`sol144.py`)
- **Objective:** Solve the flexible trim problem (determined and over-determined) and recover
  stability/control derivatives.
- **Scope:** Assemble the augmented trim system (structural equilibrium + trim constraints +
  baseline `f_g` + **inertia-relief load** `f_inertial = −M_aa · a` from the prescribed
  maneuver accelerations). For the **determined** case, solve the square system directly. For
  the **over-determined** case (more trim variables than equations), solve by **constrained
  minimization** of the `TRIMOBJ` objective subject to `TRIMCON` constraints and `TRIMVAR`
  bounds (least-squares core; the square solve is the special case). Recover `u_a`, the free
  trim variables, flexible `C_Lα`, `C_Mα`, control effectiveness, and structural deflection +
  CBAR loads (reuse `recover_bar_forces`). Compare against the rigid (q→0) derivatives. The
  detailed balanced-maneuver load *cases* and the net (aero + inertial) load output are
  developed in Step 53.

  **Rate (damping) aero — quasi-steady `Ω×r` incidence (no DLM).** The `ROLL`/`PITCH`/`YAW`
  rate trim variables get their aero load columns from the local incidence a rigid-body rate
  induces, computed with the *steady* VLM — the standard k→0 way SOL 144 / ZAERO TRIM produce
  damping derivatives. For rate vector `Ω = [p,q,r]` about the reference, each box sees a local
  velocity `Ω × Δr` (`Δr` = box − reference); projected on the box normal and divided by `V∞`
  it is an extra normalwash column, i.e. an additional `Q_ax` column built through the same
  `Skj·AJJ*⁻¹` path as `w_g`:
  - **pitch rate:** `Δα(x) = q·(x − x_ref)/V∞` (streamwise-linear; loads the tail → `C_mq`);
  - **roll rate:** `Δα(y) = p·y/V∞` (antisymmetric in span → `C_lp`; uses the Step 41
    antisymmetric VLM);
  - **yaw rate:** spanwise `ΔU(y) = −r·y` on the wing and `Δβ(x) = r·(x − x_ref)/V∞` on vertical
    surfaces → `C_nr`.
  This is rigorous to first order in reduced frequency and needs no unsteady aero; the genuinely
  unsteady terms (apparent mass, wake lag) are deferred to Phase G0 / Phase G.
- **Test/Acceptance (validation V-C1):** Trim a forward-swept / straight wing and reproduce
  the **MSC NASTRAN HA144A-class** flexible-to-rigid derivative ratios (Rodden test-problem
  library). Closed-form check: flexible lift-curve slope of a uniform cantilever wing vs the
  Bisplinghoff analytical correction. **(V-C4)** An over-determined case (two control
  effectors, one equation) returns the objective-minimizing solution and satisfies the
  constraints.
- **Risk (KC2):** Determined system singular when longitudinal/lateral trim-variable counts
  don't match the DOF split — caught by the Step 51 validator with a clear diagnostic.
  Over-determined solution may be a local optimum; document the initial-guess sensitivity
  (`TRIMVAR INITIAL`). Sign conventions on control-surface incidence.

### Step 53 — Balanced maneuver loads & inertia relief
- **Objective:** Compute balanced *static* maneuver loads — symmetric pull-up / push-over at a
  load factor, steady roll, steady yaw/sideslip — and output the **net (aero + inertial)** load
  for downstream stress. This is the static "maneuver loads" analogue of ZAERO's TRIM-based
  flight loads (as distinct from the transient MLOADS of Phase G).
- **Scope:** Each maneuver point is a `TRIM` subcase with prescribed `AESTAT` accelerations /
  rates and load factor. Assemble the **inertia-relief load** `f_inertial = −M_aa · a` by
  distributing the rigid-body acceleration field over the structural mass (`M_aa`, `CONM2`,
  GPWG; `GRAV` for the gravity component), solve the trim (Step 52) so that aero + inertial +
  gravity is in equilibrium in the body frame, and recover deflection + CBAR loads
  (mode-acceleration recovery when the modal ROM is active). Steady **rotary** maneuvers
  (roll/yaw rate) draw their damping aero from the antisymmetric VLM (Step 41 antisymmetric
  images). Provide standard maneuver-case presets (symmetric pull-up/push-over, steady roll,
  steady sideslip).
- **Test/Acceptance (validation V-C5):** Symmetric pull-up at load factor `n_z` — the net
  (aero + inertial) resultant equals `n_z · W` with zero residual force/moment in the body
  frame; recovered CBAR loads scale linearly with `n_z`. A free-aircraft (SUPORT-referenced)
  case balances to ≈0 net force/moment.
- **Risk (KC9):** Inertia-relief load inconsistent with the prescribed accelerations
  (gravity double-counted; lumped vs consistent mass) → net imbalance. Gate: assert
  force/moment closure per maneuver case. Free-aircraft maneuvers need a rigid-body reference
  (SUPORT-like) consistent with the Step 50 modal basis.

### Step 54 — CFD / wind-tunnel steady-pressure injection (mean-flow trim)
- **Objective:** Allow the trim mean-flow aerodynamics to be supplied directly from CFD or
  wind-tunnel steady pressures, so the trim solution is a perturbation about the measured
  operating point.
- **Scope:** `CHORDCP` card supplies a per-box steady `{cp}` (or per-strip load) at a stated
  reference angle of attack; `sol144.py` replaces the program-computed mean-flow rigid load
  with the injected distribution (reusing the Step 43 pressure-/force-matching machinery to
  build the consistent `AJJ*` and `w_g`). The trim variables then perturb about the injected
  state. Documents the operating-point bookkeeping (e.g. `{cp}` given at 10° ⇒ results are
  perturbations about 10°).
- **Test/Acceptance:** Injecting the program's own inviscid mean-flow reproduces the Step 52
  result (identity). Injecting a scaled distribution shifts the trimmed AOA by the expected
  amount. Total injected lift/moment matches the supplied integral.
- **Risk:** Operating-point/reference-AOA mismatch between the injected data and the trim
  linearization — validate and warn; require the reference AOA on the `CHORDCP` card.

### Step 55 — Aeroelastic divergence (`DIVERG`)
- **Objective:** Solve `K_aa φ = q · Q_aa φ` for the lowest positive divergence dynamic
  pressure and mode shape.
- **Scope:** Generalised eigenvalue solve (reuse the dense path from `sol103.py`); filter to
  the smallest positive real `q`; report `q_div` and `V_div` (given ρ). Divergence depends
  only on `K_aa` and `Q_aa` (the `w_g`/`Q_ax` right-hand side does not enter the eigenvalue).
- **Test/Acceptance (validation V-C2):** **Goland wing** and an idealised swept cantilever —
  `q_div` matches the published / closed-form Bisplinghoff value within a few %.
- **Risk (KC3):** Spurious negative/complex eigenvalues from the unsymmetric `Q_aa`; document
  the selection rule (smallest positive real).

### Step 56 — SOL 144 f06 output + flight/maneuver-load export
- **Objective:** Write the static aeroelastic results to `.f06`, and export the trimmed loads
  as `FORCE`/`MOMENT` cards for downstream stress analysis.
- **Scope:** New f06 blocks — TRIM VARIABLES, STABILITY DERIVATIVES, AERODYNAMIC DIVERGENCE,
  AERODYNAMIC PRES/FORCES; reuse displacement and CBAR-force blocks. Follow the existing
  `f06_writer.py` block style. **Load export:** write grid loads as NASTRAN `FORCE`/`MOMENT`
  bulk-data cards, one set per subcase. For a plain trim this is the aero load `G_kgᵀ·q·P_k`;
  for a **maneuver case (Step 53) the exported set is the net (aero + inertial) balanced
  load**, which is what the stress process consumes.
- **Test/Acceptance:** Snapshot/regression test of the f06 text for a sample SOL 144 run; the
  exported `FORCE`/`MOMENT` set sums to the total trimmed lift and pitching moment (plain
  trim), and to `n_z · W` with zero residual (maneuver case).

### Step 57 — Viewer: SOL 144 results
- **Objective:** Display trim solution, derivatives, divergence q, deflected shape, and box
  `cp` in the viewer.
- **Scope:** Extend `viewer/aero_view.py` and `viewer/results_view.py`; trim & derivative
  tables; flexible-vs-rigid overlay; `q_div` readout; injected-vs-computed mean-flow overlay
  when `CHORDCP` is active.
- **Test/Acceptance:** AppTest integration test loads a SOL 144 result and renders all panels
  without error.

---

## 5. Placeholders — Phases D, E, F, G0, G (not in scope for this plan)

These are documented here only to keep the architecture forward-compatible; **no
implementation steps are defined yet.** With one exception they are gated on Phase A–C being
complete and validated. The exception is **Phase G0** (quasi-steady transient maneuver loads),
which needs **no DLM** and is the natural near-term increment after Phase C — it could be
promoted to numbered steps without waiting on Phases D–G.

### Phase D — Doublet Lattice unsteady AIC  *(the hard 20%)*
- **Module:** `aero/dlm.py`. Complex `AJJ(k, M)` via the Albano–Rodden subsonic kernel
  function, tabulated over reduced-frequency / Mach pairs (`MKAERO1`). Reuses the Phase A
  box geometry, `Skj`, `Djk` unchanged.
- **Unsteady correction (ZTAW):** the steady force/moment and pressure matching built in
  Step 43 is the **k = 0 input** to ZAERO's successive-kernel-expansion (ZTAW) recovery of
  the correct out-of-phase pressure. That recovery is *only* needed for unsteady (flutter)
  work and therefore lives here, not in Phase A/C.
- **Cards:** `MKAERO1`/`MKAERO2`.
- **Risk:** Kernel-function singularity integration is numerically delicate and is the single
  biggest technical risk in the whole aeroelastic effort. Everything in E, F and G is gated on
  getting it right and validated (AGARD / Rodden DLM benchmarks).

### Phase E — SOL 145 flutter
- **Modules:** `solver/sol145.py`, `aero/flutter_aero.py`. Reduce onto the **SOL 103 modal
  basis (already available; modal-ready trim built in Step 50)**, form generalised aero
  `Q_hh(k, M)`, solve the flutter eigenvalue problem by the **p-k method** (with k-method
  cross-check); produce V-g / V-f diagrams and flutter speed/frequency.
- **Cards:** `FLUTTER`, `FLFACT`, `MKAERO1`.
- **Validation (future):** Goland wing flutter, AGARD 445.6, BAH wing (Rodden HA145-class).

### Phase F — SOL 146 gust / dynamic aeroelastic
- **Module:** `solver/sol146.py`. Frequency-domain gust response (von Kármán / Dryden
  spectra), gust load columns from the DLM, random-response PSD and RMS loads. Builds on the
  SOL 111 modal frequency-response machinery (Phase 3) + Phase D unsteady aero.
- **Cards:** `GUST`, `TABRND1`, `RANDPS`, frequency-set cards.

### Phase G0 — Quasi-steady transient maneuver loads  *(DLM-free; near-term, ahead of Phase G)*
- **Module:** `solver/maneuver_qs.py`. Time-integrate a pilot/control-command maneuver using
  **quasi-steady aerodynamics only** — no DLM, no RFA. The bridge between Step 53 (a single
  balanced instant) and the full unsteady MLOADS of Phase G: it produces transient load time
  histories with the steady VLM plus cheap analytic unsteady corrections.
- **Method (graded, each optional on top of the previous):**
  1. **Quasi-steady `Ω×r` incidence** — the rate-induced local incidence/sideslip of Step 52,
     re-evaluated at each time step from the instantaneous rates/attitude; circulatory loads
     from the *steady* VLM (`Skj·AJJ*⁻¹`). Captures the rate-damping physics and the frozen
     aero stiffness.
  2. **2-D apparent (added) mass** — per-strip non-circulatory `πρb²`-type loads ∝ acceleration
     (`α̇`, `ḣ`), added analytically. Captures the acceleration-dependent part.
  3. **Downwash-lag delay** — a single convective lag `τ = l_t/V` for the tail (the `C_mα̇`
     effect), without unsteady aero.
  4. **Strip-theory unsteady (Wagner / Theodorsen)** — per-strip 2-D lift-deficiency (frequency
     domain `C(k)`, or time-domain Wagner indicial convolution) applied to the VLM spanwise
     loading. Time-domain Wagner slots straight into the maneuver integration for
     arbitrary-motion loads.
- **Recovery & output:** per-time-step grid/component loads by the **mode-acceleration method
  (Step 50)**, exported as `FORCE`/`MOMENT` sets for critical-case identification (same
  deliverable as Phase G).
- **Cards:** pilot/control-command time-history; reuses the Phase C trim/`AESTAT`/`AESURF` and
  the `M_aa`/`CONM2`/GPWG inertial machinery.
- **Validity & gating:** good for low reduced frequency `k = ωc/2V ≲ 0.05–0.1` (slow maneuvers
  relative to chord/airspeed); breaks down for high-rate inputs, buzz, and gust, where Phase D
  unsteady aero is required. **Gated only on Phase C** — not on the DLM. Serves as the
  validation benchmark for the eventual full Phase G.

### Phase G — MLOADS: transient maneuver loads  *(distinct from the static maneuver loads of Step 53)*
- **Module:** `solver/mloads.py`. Time-domain maneuver-load time histories from a pilot input
  command, for the flexible airframe with its control system in the loop — ZAERO's MLOADS
  module. This is the *dynamic* counterpart to the Phase C static balanced-maneuver loads
  (which already cover steady/quasi-steady maneuvers via TRIM + inertia relief, Step 53).
- **Method:** reduce onto the **SOL 103 modal basis**; form generalised unsteady aero
  `Q_hh(k, M)` from the **Phase D DLM**; build a time-domain **state-space** model — modal
  states + aero **lag states** from a **rational function approximation** (Roger / minimum-state)
  of `Q_hh`, plus rigid-body/airframe states in flight-dynamics form (with zero-eigenvalue
  enforcement for the rigid-body modes). A **frequency-domain** path (no RFA) serves as the
  benchmark, mirroring ZAERO. Integrate the pilot-command maneuver in time and recover
  per-time-step grid/component loads by the **mode-acceleration method (already in Step 50)**,
  exported as `FORCE`/`MOMENT` sets for critical-case identification.
- **Control layer (ASE):** actuator, sensor, and control-law models for the closed-loop
  system; open-loop runs use prescribed control-surface time histories.
- **Cards:** pilot-input time-history, actuator/sensor, RFA-parameter, `MKAERO1` (shared with
  D/E).
- **Gating & risk:** gated on **Phase D (DLM)** and the Phase E generalised-aero machinery;
  carries the same unsteady-aero risk as flutter, plus RFA accuracy (rigid-body-mode
  eigenvalue preservation) and control-model fidelity. Reuses the existing `M_aa`/`CONM2`/GPWG
  inertial machinery and the Step 50 mode-acceleration recovery.

---

## 6. Key Risks (Phase A–C)

| ID | Risk | Phase | Severity | Mitigation |
|----|------|-------|----------|------------|
| KA1 | VLM ¼c/¾c box placement off-by-half — classic silent error | A | High | Direct geometric assertions in Step 40 tests |
| KA2 | AIC near-singular at coarse mesh; trailing-leg / image-vortex self-influence sign | A | Med | Closed-form isolated-horseshoe check; mesh-independence study |
| KA3 | Downwash-vs-slope convention drift across `Djk`/`w_g`/`Wkk`/spline | A/B | High | Fix one convention (dimensionless slope), document at every definition site |
| KA4 | `w_g` camber/twist baseline wrong → every rigid/trim load biased | A | High | V-A/V-B2 baseline-load checks; rigid-AOA identity against Step 41 |
| KA5 | `WT1`/`WT2` correction-matrix conditioning with sparse/noisy CFD/WT targets | A | Med | Regularise; warn on high condition number; round-trip identity test (V-A3) |
| KB1 | Spline rigid-body modes not exact → garbage flexible loads | B | High | Rigid-body + linear-field tests must pass to machine precision (gate) |
| KB2 | Spline-system conditioning for off-axis collocation points | B | Med | Regularisation; warn on high condition number |
| KB3 | ATTACH/SPLINE0 DOF bookkeeping vs existing RBE2/RBE3 | B | Low | Reuse validated `build_rbe3_transformation`; "splined more than once" check |
| KC1 | Dense `Q_aa` mixed with sparse `K` | C | Med | Reuse existing dense-fallback path (RBE3 branch precedent) |
| KC2 | Determined trim singular (long./lat. var counts ≠ DOF split) | C | High | Pre-solve count validator (Step 51) + explicit diagnostic |
| KC3 | Divergence eigenvalue selection (unsymmetric `Q_aa`) | C | Med | Document "smallest positive real" rule; test against Goland |
| KC4 | Aero vs structural coordinate / freestream-direction mismatch | A/C | High | All aero geometry → CID 0; document flow = aero x-axis |
| KC5 | Units: `q = ½ρV²` consistency with user-defined unit system | C | Med | No internal unit assumptions; validator warns on absent `AEROS` ref dims |
| KC6 | Over-determined trim returns local (not global) optimum | C | Med | Document initial-guess sensitivity; trial-and-error on `TRIMVAR INITIAL` |
| KC7 | CFD/WT mean-flow injection reference-AOA mismatch | C | Med | Require reference AOA on `CHORDCP`; identity test against computed mean-flow |
| KC8 | Modal-truncation error on static trim loads (mode-displacement underconverges) | C | High | Mode-acceleration / residual-vector recovery (gate); mode-count convergence study (V-C3); include rigid-body modes for free-aircraft trim |
| KC9 | Maneuver inertia-relief inconsistent with prescribed accelerations (gravity double-count; lumped vs consistent mass) → net imbalance | C | Med | Force/moment closure assertion per maneuver case (V-C5); SUPORT reference consistent with modal basis |
| KX1 | Validation-data availability for non-trivial cases | A/C | Med | Lead with closed-form + SP-405 tables; use Rodden HA-series where licence-free |

---

## 7. References — Analytical Methods

**Vortex-lattice (Phase A)**
- Margason, R. J., Lamar, J. E., *Vortex-Lattice FORTRAN Program for Estimating Subsonic
  Aerodynamic Characteristics of Complex Planforms*, **NASA SP-405**, NASA Langley, 1976.
- Lamar, J. E., Herbert, H. E., *Production Version of the Extended NASA-Langley Vortex
  Lattice FORTRAN Computer Program, Vol. 2: Source Code*, **NASA-TM-83304**, 1982.
  (DTIC ADA256304: https://apps.dtic.mil/sti/tr/pdf/ADA256304.pdf)
- Katz, J., Plotkin, A., *Low-Speed Aerodynamics*, 2nd ed., Cambridge, 2001 (Ch. 12 — VLM).

**AIC corrections — CFD / wind-tunnel matching (Phase A)**
- Pitt, D. M., Goodman, C. E., *FASTOP-3 / downwash weighting matrix method* (pressure
  matching) — and ZAERO *Theoretical Manual* §4, "Review of the AIC Correction Method",
  Eqs. 4.55–4.58 (`WT1`/`WT2` formulation).
- Giesing, J. P., Kálmán, T. P., Rodden, W. P., *force/moment correction matrix method*
  (subsonic AIC correction to match measured spanwise loads).
- ZONA Technology, *ZAERO User's Manual* §5.8.4 / `CHORDCP` (steady-pressure injection for
  trim mean-flow).

**Splining (Phase B)**
- Harder, R. L., Desmarais, R. N., *Interpolation Using Surface Splines*, J. Aircraft 9(2),
  1972 (SPLINE1 / Infinite-Plate Spline).
- Rodden, W. P., Johnson, E. H., *MSC/NASTRAN Aeroelastic Analysis User's Guide* — Ch. on
  splines (SPLINE1/SPLINE2 formulation, `G_kg`).
- ZONA Technology, *ZAERO User's Manual* §1.4 (3-D Spline module: thin-plate, infinite-plate,
  beam, rigid-body attachment).

**Static aeroelastics / trim / divergence (Phase C)**
- Rodden, W. P., Johnson, E. H., *MSC/NASTRAN Aeroelastic Analysis User's Guide* — SOL 144
  formulation, trim, stability derivatives, the `Q_aa`/`AJJ`/`Skj`/`Djk`/`Wkk` matrix set,
  and the HA144 test-problem library (canonical verification models).
- ZONA Technology, *ZAERO User's Manual* §1.10, §5.8 (modal trim; over-determined trim via
  `TRIMOBJ`/`TRIMCON`/`TRIMVAR`; longitudinal/lateral DOF rules; half-model asymmetric flight).
- Bisplinghoff, R. L., Ashley, H., Halfman, R. L., *Aeroelasticity*, Addison-Wesley, 1955
  (divergence closed forms; the **BAH wing** reference model).
- Hodges, D. H., Pierce, G. A., *Introduction to Structural Dynamics and Aeroelasticity*,
  Cambridge — divergence / static aeroelastic derivations.

**Reserved (Phases D/E/F)**
- Albano, E., Rodden, W. P., *A Doublet-Lattice Method for Calculating Lift Distributions on
  Oscillating Surfaces in Subsonic Flows*, AIAA J. 7(2), 1969 (Phase D).
- ZONA Technology, *ZAERO Theoretical Manual* §4 — ZTAW successive-kernel-expansion unsteady
  correction (Phase D/E, gated on the DLM).
- AGARD Standard Aeroelastic Configurations (445.6 wing) — flutter validation (Phase E).

---

## 8. Standard Validation / Test Cases

| ID | Case | Validates | Reference data |
|----|------|-----------|----------------|
| **V-A1** | Rectangular flat wing, several AR; mesh refinement; sym + antisym | VLM `C_Lα`, mesh-independence, image signs | SP-405 tables; lifting-line `2πAR/(AR+2)` limit |
| **V-A2** | Swept tapered planform from SP-405 sample | VLM span loading, `C_M` | SP-405 / TM-83304 worked examples |
| **V-A3** | Force/moment & pressure matching round-trip | `WT1`/`WT2` reproduce a supplied load/`cp` | Analytical identity; supplied target distribution |
| **V-A4** | Camber/twist/incidence baseline (`w_g`) | `w_g` rigid-load contribution | Rigid-AOA identity vs Step 41; linear-twist load |
| **V-B1** | Spline rigid-body + linear-twist recovery | `G_kg` exactness (gate) | Analytical (machine precision) |
| **V-B2** | Uniform pressure / `w_g` → grid loads round-trip | `G_kgᵀ` energy consistency | Analytical total force/moment |
| **V-B3** | ATTACH/SPLINE0 rigid-body recovery | rigid-attachment exactness | Analytical (machine precision) |
| **V-C1** | Flexible wing trim, derivative ratios | SOL 144 trim, flexible `C_Lα`/control eff. | MSC NASTRAN **HA144A**-class; Bisplinghoff correction |
| **V-C2** | **Goland wing** + idealised swept cantilever | Divergence `q_div` | Published Goland `q_div`; Bisplinghoff closed form |
| **V-C3** | q→0 reduction; modal ROM vs direct (loads); mode-count convergence | SOL 144 → SOL 101 identity; mode-acceleration recovery | Existing SOL 101 verification suite |
| **V-C4** | Over-determined trim (redundant effectors) | `TRIMOBJ`/`TRIMCON` minimization | Objective-minimizing solution + constraint satisfaction |
| **V-C5** | Balanced maneuver (symmetric pull-up at `n_z`) | inertia-relief load balance, net-load export | Net (aero+inertial) = `n_z·W`; load closure ≈ 0 |
| **V-C6** | Rate (damping) derivatives from `Ω×r` incidence | quasi-steady `C_mq`/`C_lp`/`C_nr` | Strip/lifting-line estimates; sign & trend checks |

Each validation case ships as a `tests/integration/bdf/*.bdf` model plus an integration
test asserting the reference value within a documented tolerance, exactly like the existing
`test_verification.py` cantilever / simply-supported cases.

---

## 9. Effort & Sequencing Summary

- **Phase A (Steps 39–44)** — well-trodden, closed-form-verifiable; the natural first
  deliverable. Standalone rigid aero with no structural coupling. **The correction layer
  (Steps 42–43: `w_g`, `WT1`/`WT2`) is the primary application driver** — it is what lets the
  tool reproduce CFD/wind-tunnel loads on a conventional configuration, and it is fully
  inside the subsonic/static/no-DLM envelope.
- **Phase B (Steps 45–49)** — moderate; the rigid-body spline gate (V-B1) is the make-or-break
  test. SPLINE2 (beam spline) + ATTACH/SPLINE0 (Step 47, reusing RBE2/RBE3) are the primary
  deliverables; SPLINE1 (Step 48) is deferrable.
- **Phase C (Steps 50–57)** — couples A+B; reuses the SOL 101 solve path and SOL 103 dense
  eigensolver. Yields a genuinely useful tool (trim incl. over-determined, flexible
  derivatives, **balanced maneuver loads with inertia relief**, CFD/WT mean-flow injection,
  divergence) **without** ever touching the Doublet Lattice. The static maneuver-loads case
  (Step 53) covers steady/quasi-steady maneuvers; transient maneuver loads are Phase G.

A→B→C is the real "static aeroelastic phase 1." Phases D/E/F/G (unsteady aero, flutter, gust,
transient maneuver loads) are reserved and gated on the DLM kernel — and on the ZTAW unsteady
correction that builds on the Step 43 steady-correction layer — which carry the bulk of the
remaining technical risk. **Phase G0 (quasi-steady transient maneuver loads) is the exception:
it needs no DLM and is the natural near-term increment after Phase C**, reusing the steady VLM,
the Step 52 `Ω×r` rate aero, and the Step 50 mode-acceleration recovery, with cheap analytic
apparent-mass / Wagner-lag add-ons.

---

## Appendix — Mapping of the ZAERO review goals to steps

The eight ranked goals from `static_aero_plan_zaero_review.md`, folded in:

| Review goal | Folded into |
|---|---|
| 1. Force/moment + pressure-matching AIC correction (`WT1`/`WT2`) | **Step 43** (was the diagonal-only `Wkk` step) |
| 2. Additive baseline downwash `w_g` (W2GJ: camber/twist/incidence + Δα) | **Step 42** (new `w_g` builder) |
| 3. Over-determined trim solver (`TRIMOBJ`/`TRIMCON`/`TRIMVAR`) | **Steps 51–52** |
| 4. CFD/WT steady-pressure injection as trim mean-flow (`CHORDCP`) | **Step 54** (new) |
| 5. `ATTACH` rigid-body spline + `SPLINE0` (reuse RBE2/RBE3) | **Step 47** (new) |
| 6. Half-model antisymmetric loading for lateral-directional trim | **Steps 39, 41** (parity flag + antisymmetric images) |
| 7. Flight/maneuver-load export as `FORCE`/`MOMENT` cards | **Step 56** |
| 8. Reduced-order trim — **modal-truncation ROM** on the SOL 103 basis, with mode-acceleration (residual-vector) static-load recovery | **Step 50** |
