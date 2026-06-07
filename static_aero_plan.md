# sbeam — Static Aeroelasticity Plan (Phases A, B, C)

Code architecture and step-by-step development plan for adding subsonic aeroelastic
capability to `sbeam`. This document covers **Phase A (steady VLM aerodynamics)**,
**Phase B (structure↔aero splining)**, and **Phase C (SOL 144 static aeroelastics +
divergence)**, with reserved placeholders for **Phase D (Doublet Lattice unsteady AIC)**,
**Phase E (SOL 145 flutter)**, and **Phase F (SOL 146 gust / dynamic aeroelastic)**.

Scope discipline (held across all phases):

- **Flat lifting surfaces only** — `CAERO1` macroelements meshed into trapezoidal boxes.
  No interference/slender bodies (`CAERO2`), no rings.
- **Subsonic** — VLM (Phase A) and DLM (Phase D) only; no supersonic / piston theory.
- **Splines target the CBAR beam elements** — `SPLINE2` (beam spline) is primary;
  `SPLINE1` (surface spline) is optional.
- **Aerodynamic corrections** — `Wkk`-style diagonal weighting of the inviscid AIC.
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
                         └───────────────┬─────────────────────────────┘
                                         │ AJJ  (VLM, Phase A)
                         ┌───────────────┴─────────────────────────────┐
   AERO FORCES (new)     │ q · Skj · AJJ⁻¹ · Djk · w_j  → box forces P_k │
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
User's Guide* (Rodden & Johnson) so future readers can cross-reference.

| Symbol | Meaning | Built in |
|--------|---------|----------|
| `w_j`  | Downwash (normalwash) at aero box `j`, normalised by freestream | VLM / spline |
| `AJJ`  | Aero influence coefficient: `{w_j} = [AJJ]{cp}` (subsonic; real for VLM, complex for DLM) | Phase A / D |
| `cp`   | Pressure coefficient on each box | solve `AJJ⁻¹ w_j` |
| `Skj`  | Integration matrix: box pressures → box resultant forces (area weighting) | Phase A |
| `Djk`  | Differentiation/substantial-derivative matrix: box deflection → downwash | Phase A (k=0) |
| `Wkk`  | Diagonal correction weighting on the inviscid AIC (lift-curve-slope / sweep corrections) | Phase A |
| `G_kg` | Spline matrix: structural g-DOF → aero box deflection & slope | Phase B |
| `Q_aa` | Generalised aero stiffness on structural DOF: `G_kgᵀ Skj AJJ⁻¹ Djk Wkk G_kg` | Phase C |
| `q`    | Dynamic pressure ½ρV² | TRIM / FLFACT |

The single relation that ties it all together for **static aeroelastics**:

```
(K_aa − q · Q_aa) · u_a  =  q · (rigid aero loads from AESTAT/AESURF)  +  f_ext
```

with **divergence** being the eigenvalue problem `det(K_aa − q·Q_aa) = 0` for the smallest
positive `q`.

### 1.2 New module tree

```
sbeam/aero/
├── __init__.py
├── aero_model.py     # AeroModel container: derived numeric model (boxes + matrices),
│                     #   built from BulkData the way grid_index/K are built. Analogous
│                     #   role to assembly/*.
├── panel.py          # CAERO1 → trapezoidal box meshing; collocation (¾c) & vortex (¼c)
│                     #   points, box areas, outward normals, chord/span fractions.
├── vlm.py            # Phase A: steady VLM AIC (AJJ at k=0), horseshoe-vortex normalwash.
├── integration.py    # Phase A: Skj force-integration, Djk downwash-from-deflection.
├── corrections.py    # Phase A: Wkk diagonal correction matrix assembly.
├── spline.py         # Phase B: SPLINE2 beam spline (primary) + SPLINE1 IPS (optional)
│                     #   → G_kg structural↔aero coupling matrix.
├── dlm.py            # ░ PLACEHOLDER Phase D ░ unsteady AIC AJJ(k, M); Albano–Rodden kernel.
└── flutter_aero.py   # ░ PLACEHOLDER Phase E ░ generalised aero Q(k, M) on modal basis.

sbeam/solver/
├── sol101.py         # (exists)
├── sol103.py         # (exists) — provides modal basis reused by Phase E
├── sol144.py         # Phase C: static aeroelastic trim + flexible derivatives + divergence
├── sol145.py         # ░ PLACEHOLDER Phase E ░ flutter (p-k); reuses SOL 103 modes + dlm.py
└── sol146.py         # ░ PLACEHOLDER Phase F ░ gust / random response; reuses SOL 111 + dlm.py
```

### 1.3 Parser & data-model changes

`BulkData` (in `model/bulk_data.py`) gains aero card dicts, following the existing
flat-container pattern (one dict per card type, keyed by ID). Parsed cards stay raw; the
**derived numeric model** (boxes, AIC, splines) is built lazily in `aero/aero_model.py`,
mirroring how `assemble_global_stiffness` derives `K` from `BulkData`.

New dataclasses in `model/aero.py` (new file): `Caero1`, `Paero1`, `Aefact`, `Aeros`,
`Spline1`, `Spline2`, `Set1`, `Trim`, `Aestat`, `Aesurf`, `Aelist`, `Diverg`.

`BulkData` additions (Phase A/B/C only; D/E/F reserved):

```python
# --- Aero geometry (Phase A) ---
caero1s: dict   # {eid: Caero1}
paero1s: dict   # {pid: Paero1}
aefacts: dict   # {sid: Aefact}
aeros:   object # single AEROS reference-geometry card (or None)
# --- Splines (Phase B) ---
spline1s: dict  # {eid: Spline1}
spline2s: dict  # {eid: Spline2}
set1s:    dict  # {sid: Set1}
# --- Static aeroelastic trim (Phase C) ---
trims:    dict  # {sid: Trim}
aestats:  dict  # {id: Aestat}
aesurfs:  dict  # {id: Aesurf}
aelists:  dict  # {sid: Aelist}
divergs:  dict  # {sid: Diverg}
# --- RESERVED Phase D/E/F ---
# mkaero1s, flutters, flfacts, gusts  → add when those phases start
```

New `bdf_reader.py` handlers: `_handle_caero1`, `_handle_paero1`, `_handle_aefact`,
`_handle_aeros`, `_handle_spline1/2`, `_handle_set1`, `_handle_trim`, `_handle_aestat`,
`_handle_aesurf`, `_handle_aelist`, `_handle_diverg`. Each reuses the existing
multi-continuation accumulation pattern already used by `SPC1`/`RBE2`/`RBE3`.

### 1.4 Case control, results, viewer

- **Case control** (`parser/case_control.py`): recognise `SOL 144`, and the subcase
  selectors `TRIM = sid`, `DIVERG = sid`, plus output requests `AEROF` (aero box forces)
  and `APRES` (aero box pressures). `SubcaseControl` gains `trim_sid`, `diverg_sid`.
- **Results** (`results/results.py`): new `Sol144Result` (trim variables, flexible
  stability/control derivatives, divergence q, box pressures/forces, structural
  displacement, recovered CBAR loads).
- **f06** (`results/f06_writer.py`): new blocks — TRIM VARIABLES, STABILITY DERIVATIVES,
  AERODYNAMIC DIVERGENCE (q_div per mode), AERODYNAMIC PRESSURES/FORCES, plus the existing
  displacement & CBAR-force blocks (reused).
- **Viewer** (`viewer/`): aero box mesh overlay on the structural geometry, spline
  connection lines (struct grids ↔ aero boxes), pressure-coefficient contour, trim &
  derivative tables, divergence-q readout. New module `viewer/aero_view.py`.

---

## 2. Phase A — Steady Vortex-Lattice Aerodynamics

**Goal:** Produce the inviscid steady aero matrices (`AJJ` at k=0, `Skj`, `Djk`, `Wkk`)
for flat lifting surfaces, standalone (rigid aero), verifiable against published VLM
lift/moment data **before** any structural coupling exists.

**Method:** Classical horseshoe-vortex lattice (NASA SP-405). Each `CAERO1` macroelement
is meshed into `NCHORD × NSPAN` trapezoidal boxes (uniform, or `AEFACT`-driven non-uniform
spacing). Per box: a bound vortex segment at the box ¼-chord, trailing legs to infinity
downstream, and a collocation point at the box ¾-chord on the surface. The flow-tangency
boundary condition (zero net normal velocity at each collocation point) yields a linear
system for the vortex strengths; `AJJ` is the normalwash influence matrix and its inverse
maps downwash to pressure.

VLM is the **k = 0 limit of the DLM** — the box geometry, `Skj`, and `Djk` built here are
reused unchanged in Phase D, so build them with that reuse in mind.

### Step 39 — Aero reference data & coordinate handling
- **Objective:** Parse `AEROS` (reference chord `CREF`, span `BREF`, area `SREF`,
  symmetry flags `SYMXZ`/`SYMXY`) and resolve the aerodynamic coordinate system.
- **Scope:** `model/aero.py` `Aeros` dataclass; `_handle_aeros`; reuse existing `CORD2R`
  for the aero coord (`ACSID`). Validate exactly one `AEROS`. Symmetry handling: half-model
  with reflection about the x-z plane.
- **Test/Acceptance:** Parser unit test round-trips an `AEROS` card; symmetry flag stored;
   value error if `AEROS` missing when a `CAERO1` is present.
- **Risk:** Aero coord vs structural CID 0 mismatch — all aero geometry resolves to CID 0
  internally (same convention as the structural model). Document the freestream direction
  (aero x-axis = flow) explicitly.

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

### Step 41 — Steady VLM AIC (`vlm.py`)
- **Objective:** Assemble `AJJ` (k=0) via the horseshoe-vortex normalwash influence and
  solve a rigid wing for span loading.
- **Scope:** Biot–Savart influence of each horseshoe vortex on each collocation point;
  assemble influence matrix; impose flow tangency for a rigid angle of attack; recover
  circulation, box `cp`, section `c_ℓ`, and total `C_L`/`C_M`. Handle x-z symmetry by
  adding the mirror-image vortex contributions.
- **Test/Acceptance (validation V-A1):** Rectangular planform, several aspect ratios —
  `C_Lα` converges with mesh refinement toward lifting-line / SP-405 tabulated values
  (within a few %). Mesh-independence demonstrated (e.g. 4×10 vs 8×20 boxes).
- **Risk:** AIC near-singularity at coarse mesh; trailing-leg self-influence sign. Verify
  the isolated-horseshoe self-induced downwash against the closed-form value.

### Step 42 — Integration, downwash, and Wkk corrections
- **Objective:** Build `Skj` (pressure→force), `Djk` (deflection/slope→downwash), and the
  `Wkk` correction matrix; package everything in `AeroModel`.
- **Scope:** `integration.py` (`Skj`, `Djk`); `corrections.py` (`Wkk` as a user-suppliable
  diagonal weighting — default identity — applied as `AJJ_corr = Wkk · AJJ` per the NASTRAN
  W2GJ/WKK convention). `aero_model.py` assembles and caches `AJJ`, `AJJ⁻¹`, `Skj`, `Djk`,
  `Wkk` and exposes the rigid-load columns.
- **Test/Acceptance:** With `Wkk = I`, results match Step 41. A non-unit `Wkk` scales the
  affected box lift by the expected factor. `Skj`-integrated total force equals the direct
  circulation sum (consistency check).
- **Risk:** Convention drift between "downwash" (velocity) and "slope" (geometry) — pick one
  (slope, dimensionless) and document it where `Djk` is defined.

### Step 43 — Viewer: rigid aero visualisation (optional but recommended)
- **Objective:** Render the aero box mesh and rigid `cp` distribution in the Streamlit
  viewer.
- **Scope:** `viewer/aero_view.py` — Plotly mesh overlay on structural geometry; per-box
  `cp` colour map; section-load plot.
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
(ratio set by `DTHX`/`DTHZ`), which is the natural match for `sbeam`'s CBAR DOFs. This is
exactly the "splines to beam elements" requirement.

**Method (optional — SPLINE1 surface spline):** Harder–Desmarais Infinite-Plate Spline
(IPS) for 2-D scatter of grids. Heavier; include only if a beam axis is a poor fit.

### Step 44 — SET1 + SPLINE2 parsing
- **Objective:** Parse `SET1` (grid lists), `SPLINE2` (beam spline: `CAERO1` box range,
  `SET1` ref, spline coord `CID`, `DTHX`/`DTHZ` rotation constraints).
- **Scope:** `Set1`/`Spline2` dataclasses + handlers; multi-continuation `SET1` grid lists.
- **Test/Acceptance:** Round-trip a `SPLINE2` referencing a box range and a `SET1`; resolve
  grid IDs and box IDs; error on dangling references.

### Step 45 — SPLINE2 beam-spline matrix (`spline.py`)
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

### Step 46 — SPLINE1 surface spline (optional)
- **Objective:** Harder–Desmarais IPS for general 2-D grid scatter.
- **Scope:** `Spline1` dataclass + handler; IPS kernel `r²ln r²`; assemble `G_kg`.
- **Test/Acceptance:** Reproduces rigid-body and linear fields exactly; matches a published
  IPS example. **Deferrable** — Phase C can proceed with SPLINE2 only.

### Step 47 — Force transfer & coupled smoke test
- **Objective:** Wire `G_kgᵀ` force transfer and verify the full rigid-aero → structural
  load path end-to-end (no flexibility yet).
- **Scope:** `aero_model.py` exposes `structural_loads = G_kgᵀ · q · P_k(rigid)`. Apply as a
  load vector to the existing SOL 101 path; confirm total lift/moment reacts correctly at
  the SPCs.
- **Test/Acceptance:** Rigid wing at fixed AOA: SPC reactions equal total aero lift and
  pitching moment to within integration tolerance.

---

## 4. Phase C — SOL 144 Static Aeroelastics + Divergence

**Goal:** Couple Phases A+B into the structural stiffness to solve the flexible static
aeroelastic problem: trim, flexible stability/control derivatives, and divergence dynamic
pressure.

**Governing equation (restrained, g-set reduced to a-set after SPC):**

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · (Wkk·AJJ)⁻¹ · Djk · G_kg     (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
```

**Trim:** assemble the rigid + flexible + inertial equilibrium and solve for the unknown
trim variables (`AESTAT` rigid-body states: `ANGLEA`, `PITCH`, `URDD3`, …; `AESURF` control
surface deflections), constrained by the `TRIM` card. **Divergence:** solve the eigenvalue
problem `K_aa φ = q · Q_aa φ` for the smallest positive `q` (and its mode), per `DIVERG`.

### Step 48 — Aero stiffness assembly `Q_aa`
- **Objective:** Assemble the flexible aero stiffness `Q_aa` on the structural a-set.
- **Scope:** `aero_model.py`: `Q_aa = G_kgᵀ Skj (Wkk·AJJ)⁻¹ Djk G_kg`; reduce g-set→a-set
  using the existing SPC partition (`apply_spcs`) and RBE3/RBAR transform (reuse
  `build_rbe3_transformation`). Dense `Q_aa` (aero is fully populated) added to sparse `K`.
- **Test/Acceptance:** `Q_aa` symmetry/structure sanity; dimensions match a-set; for `q→0`
  the system reduces to plain SOL 101.
- **Risk:** Mixing dense `Q_aa` with sparse `K` — follow the existing dense-fallback pattern
  in `solve_static`/`solve_modes` (RBE3 branch already produces dense).

### Step 49 — Trim card set parsing (AESTAT / AESURF / AELIST / TRIM / DIVERG)
- **Objective:** Parse the static aeroelastic trim cards and case-control selectors.
- **Scope:** `Aestat`/`Aesurf`/`Aelist`/`Trim`/`Diverg` dataclasses + handlers; `AESURF`
  references an `AELIST` of aero boxes forming the control surface; `TRIM` fixes Mach, `q`,
  and the constrained trim variables; case control `TRIM=`, `DIVERG=`.
- **Test/Acceptance:** Round-trip each card; resolve control-surface box lists; error when a
  `TRIM` references undefined `AESTAT`/`AESURF` labels.

### Step 50 — SOL 144 trim solve + flexible derivatives (`sol144.py`)
- **Objective:** Solve the flexible trim problem and recover stability/control derivatives.
- **Scope:** Assemble the augmented trim system (structural equilibrium + trim constraints);
  solve for `u_a` and the free trim variables; recover flexible `C_Lα`, `C_Mα`, control
  effectiveness, and structural deflection + CBAR loads (reuse `recover_bar_forces`).
  Compare against the rigid (q→0 aero, or `K`→∞) derivatives.
- **Test/Acceptance (validation V-C1):** Trim a forward-swept / straight wing and reproduce
  the **MSC NASTRAN HA144A-class** flexible-to-rigid derivative ratios (Rodden test-problem
  library). Closed-form check: flexible lift-curve slope of a uniform cantilever wing vs the
  Bisplinghoff analytical correction.
- **Risk:** Trim-system singularity if the count of free trim variables ≠ constraints; emit a
  clear diagnostic. Sign conventions on control-surface incidence.

### Step 51 — Aeroelastic divergence (`DIVERG`)
- **Objective:** Solve `K_aa φ = q · Q_aa φ` for the lowest positive divergence dynamic
  pressure and mode shape.
- **Scope:** Generalised eigenvalue solve (reuse the dense path from `sol103.py`); filter to
  the smallest positive real `q`; report `q_div` and `V_div` (given ρ).
- **Test/Acceptance (validation V-C2):** **Goland wing** and an idealised swept cantilever —
  `q_div` matches the published / closed-form Bisplinghoff value within a few %.
- **Risk:** Spurious negative/complex eigenvalues from the unsymmetric `Q_aa`; document the
  selection rule (smallest positive real).

### Step 52 — SOL 144 f06 output
- **Objective:** Write the static aeroelastic results to `.f06`.
- **Scope:** New f06 blocks — TRIM VARIABLES, STABILITY DERIVATIVES, AERODYNAMIC DIVERGENCE,
  AERODYNAMIC PRES/FORCES; reuse displacement and CBAR-force blocks. Follow the existing
  `f06_writer.py` block style.
- **Test/Acceptance:** Snapshot/regression test of the f06 text for a sample SOL 144 run.

### Step 53 — Viewer: SOL 144 results
- **Objective:** Display trim solution, derivatives, divergence q, deflected shape, and box
  `cp` in the viewer.
- **Scope:** Extend `viewer/aero_view.py` and `viewer/results_view.py`; trim & derivative
  tables; flexible-vs-rigid overlay; `q_div` readout.
- **Test/Acceptance:** AppTest integration test loads a SOL 144 result and renders all panels
  without error.

---

## 5. Placeholders — Phases D, E, F (not in scope for this plan)

These are documented here only to keep the architecture forward-compatible; **no
implementation steps are defined yet.** They are gated on Phase A–C being complete and
validated.

### Phase D — Doublet Lattice unsteady AIC  *(the hard 20%)*
- **Module:** `aero/dlm.py`. Complex `AJJ(k, M)` via the Albano–Rodden subsonic kernel
  function, tabulated over reduced-frequency / Mach pairs (`MKAERO1`). Reuses the Phase A
  box geometry, `Skj`, `Djk` unchanged.
- **Cards:** `MKAERO1`/`MKAERO2`.
- **Risk:** Kernel-function singularity integration is numerically delicate and is the single
  biggest technical risk in the whole aeroelastic effort. Everything in E and F is gated on
  getting it right and validated (AGARD / Rodden DLM benchmarks).

### Phase E — SOL 145 flutter
- **Modules:** `solver/sol145.py`, `aero/flutter_aero.py`. Reduce onto the **SOL 103 modal
  basis (already available)**, form generalised aero `Q_hh(k, M)`, solve the flutter
  eigenvalue problem by the **p-k method** (with k-method cross-check); produce V-g / V-f
  diagrams and flutter speed/frequency.
- **Cards:** `FLUTTER`, `FLFACT`, `MKAERO1`.
- **Validation (future):** Goland wing flutter, AGARD 445.6, BAH wing (Rodden HA145-class).

### Phase F — SOL 146 gust / dynamic aeroelastic
- **Module:** `solver/sol146.py`. Frequency-domain gust response (von Kármán / Dryden
  spectra), gust load columns from the DLM, random-response PSD and RMS loads. Builds on the
  SOL 111 modal frequency-response machinery (Phase 3) + Phase D unsteady aero.
- **Cards:** `GUST`, `TABRND1`, `RANDPS`, frequency-set cards.

---

## 6. Key Risks (Phase A–C)

| ID | Risk | Phase | Severity | Mitigation |
|----|------|-------|----------|------------|
| KA1 | VLM ¼c/¾c box placement off-by-half — classic silent error | A | High | Direct geometric assertions in Step 40 tests |
| KA2 | AIC near-singular at coarse mesh; trailing-leg self-influence sign | A | Med | Closed-form isolated-horseshoe check; mesh-independence study |
| KA3 | Downwash-vs-slope convention drift across `Djk`/`Wkk`/spline | A/B | High | Fix one convention (dimensionless slope), document at definition site |
| KB1 | Spline rigid-body modes not exact → garbage flexible loads | B | High | Rigid-body + linear-field tests must pass to machine precision (gate) |
| KB2 | Spline-system conditioning for off-axis collocation points | B | Med | Regularisation; warn on high condition number |
| KC1 | Dense `Q_aa` mixed with sparse `K` | C | Med | Reuse existing dense-fallback path (RBE3 branch precedent) |
| KC2 | Trim system singular (free vars ≠ constraints) | C | High | Pre-solve count check + explicit diagnostic |
| KC3 | Divergence eigenvalue selection (unsymmetric `Q_aa`) | C | Med | Document "smallest positive real" rule; test against Goland |
| KC4 | Aero vs structural coordinate / freestream-direction mismatch | A/C | High | All aero geometry → CID 0; document flow = aero x-axis |
| KC5 | Units: `q = ½ρV²` consistency with user-defined unit system | C | Med | No internal unit assumptions; validator warns on absent `AEROS` ref dims |
| KX1 | Validation-data availability for non-trivial cases | A/C | Med | Lead with closed-form + SP-405 tables; use Rodden HA-series where licence-free |

---

## 7. References — Analytical Methods

**Vortex-lattice (Phase A)**
- Margason, R. J., Lamar, J. E., *Vortex-Lattice FORTRAN Program for Estimating Subsonic
  Aerodynamic Characteristics of Complex Planforms*, **NASA SP-405**, NASA Langley, 1976.
- Lamar, J. E., Herbert, H. E., *Production Version of the Extended NASA-Langley Vortex
  Lattice FORTRAN Computer Program, Vol. 2: Source Code*, **NASA-TM-83304**, 1982.
  (DTIC ADA256304: https://apps.dtic.mil/sti/tr/pdf/ADA256304.pdf)
- HAW Hamburg / DGLR 2009 panel-method paper (Scholz et al.):
  https://www.fzt.haw-hamburg.de/pers/Scholz/dglr/dlrk2009_ohneReview/Papers/121224.pdf
- Katz, J., Plotkin, A., *Low-Speed Aerodynamics*, 2nd ed., Cambridge, 2001 (Ch. 12 — VLM).

**Splining (Phase B)**
- Harder, R. L., Desmarais, R. N., *Interpolation Using Surface Splines*, J. Aircraft 9(2),
  1972 (SPLINE1 / Infinite-Plate Spline).
- Rodden, W. P., Johnson, E. H., *MSC/NASTRAN Aeroelastic Analysis User's Guide* — Ch. on
  splines (SPLINE1/SPLINE2 formulation, `G_kg`).

**Static aeroelastics / divergence (Phase C)**
- Rodden, W. P., Johnson, E. H., *MSC/NASTRAN Aeroelastic Analysis User's Guide* — SOL 144
  formulation, trim, stability derivatives, the `Q_aa`/`AJJ`/`Skj`/`Djk`/`Wkk` matrix set,
  and the HA144 test-problem library (canonical verification models).
- Bisplinghoff, R. L., Ashley, H., Halfman, R. L., *Aeroelasticity*, Addison-Wesley, 1955
  (divergence closed forms; the **BAH wing** reference model).
- Hodges, D. H., Pierce, G. A., *Introduction to Structural Dynamics and Aeroelasticity*,
  Cambridge — divergence / static aeroelastic derivations.

**Reserved (Phases D/E/F)**
- Albano, E., Rodden, W. P., *A Doublet-Lattice Method for Calculating Lift Distributions on
  Oscillating Surfaces in Subsonic Flows*, AIAA J. 7(2), 1969 (Phase D).
- AGARD Standard Aeroelastic Configurations (445.6 wing) — flutter validation (Phase E).

---

## 8. Standard Validation / Test Cases

| ID | Case | Validates | Reference data |
|----|------|-----------|----------------|
| **V-A1** | Rectangular flat wing, several AR; mesh refinement | VLM `C_Lα`, mesh-independence | SP-405 tables; lifting-line `2πAR/(AR+2)` limit |
| **V-A2** | Swept tapered planform from SP-405 sample | VLM span loading, `C_M` | SP-405 / TM-83304 worked examples |
| **V-B1** | Spline rigid-body + linear-twist recovery | `G_kg` exactness (gate) | Analytical (machine precision) |
| **V-B2** | Uniform pressure → grid loads round-trip | `G_kgᵀ` energy consistency | Analytical total force/moment |
| **V-C1** | Flexible wing trim, derivative ratios | SOL 144 trim, flexible `C_Lα`/control eff. | MSC NASTRAN **HA144A**-class; Bisplinghoff correction |
| **V-C2** | **Goland wing** + idealised swept cantilever | Divergence `q_div` | Published Goland `q_div`; Bisplinghoff closed form |
| **V-C3** | q→0 reduction | SOL 144 → SOL 101 identity | Existing SOL 101 verification suite |

Each validation case ships as a `tests/integration/bdf/*.bdf` model plus an integration
test asserting the reference value within a documented tolerance, exactly like the existing
`test_verification.py` cantilever / simply-supported cases.

---

## 9. Effort & Sequencing Summary

- **Phase A (Steps 39–43)** — well-trodden, closed-form-verifiable; the natural first
  deliverable. Standalone rigid aero with no structural coupling.
- **Phase B (Steps 44–47)** — moderate; the rigid-body spline gate (V-B1) is the make-or-break
  test. SPLINE2 (beam spline) is the primary deliverable; SPLINE1 (Step 46) is deferrable.
- **Phase C (Steps 48–53)** — couples A+B; reuses the SOL 101 solve path and SOL 103 dense
  eigensolver. Yields a genuinely useful tool (trim, flexible derivatives, divergence)
  **without** ever touching the Doublet Lattice.

A→B→C is the real "static aeroelastic phase 1." Phases D/E/F (unsteady aero, flutter, gust)
are reserved and gated on the DLM kernel, which carries the bulk of the remaining technical
risk.
