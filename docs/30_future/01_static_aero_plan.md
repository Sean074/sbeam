# sbeam — Static Aeroelasticity Plan (Phases A, B, C) — COMPLETE; retained as architecture reference

**Status (2026-07-05): Phases A, B, and C are complete.** Every step of this plan
(Steps 39–58, plus the AC1–AC8 close-out) is delivered and recorded in
`docs/40_history/00_completed_development.md`; the as-built system is documented in
`docs/10_standard/05_aeroelastics.md` (developer/user guide) and
`docs/20_theory/01_aeroelastics_theory.md` (theory). Per the plan's self-removal rule the
closed step bodies have been pruned (backlog housekeeping H1, 2026-07-05).

This document is retained for what stays useful after completion:

- **§1 Architecture overview** — the layer diagram and matrix nomenclature that the code,
  theory doc, and design proposals all cross-reference.
- **§2 Delivered steps** — a one-line map from each step to its deliverable and history entry.
- **§3 Follow-on phases** — pointers only; the forward plan now lives in
  `docs/30_future/00_backlog.md` (priority-ordered) and `docs/30_future/designs/`.
- **§4 References** and **§5 validation-case index** — the literature and V-case IDs cited
  throughout the tests and docs.

**Application context that drove the priorities:** subsonic, conventional airplane
configuration, with aerodynamic corrections supplied from high-fidelity CFD or wind-tunnel
test — the correction layer (`Wkk`/`WT1`/`WT2`/`W2GJ`/`CHORDCP`) was a first-class
deliverable, not an afterthought. Scope discipline held throughout: flat lifting surfaces
(`CAERO1`), subsonic only, SPLINE2 beam spline primary, steady (k = 0) corrections,
educational/exploratory (not a means of compliance).

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
   AERO GEOMETRY         │ AeroModel: CAERO1 → boxes (k,j)               │
                         │            collocation pts, normals, areas    │
                         │            baseline downwash w_g (camber/twist)│
                         └───────────────┬─────────────────────────────┘
                                         │ AJJ*, w_g  (VLM + corrections, Phase A)
                         ┌───────────────┴─────────────────────────────┐
   AERO FORCES           │ q · Skj · AJJ*⁻¹ · (Djk·G_kg·u + w_g) → P_k   │
                         └───────────────┬─────────────────────────────┘
                                         │ G_kgᵀ  (force transfer)
                         ┌───────────────┴─────────────────────────────┐
   COUPLED SOLVERS       │ SOL 144 trim / divergence (Phase C) ✅        │
                         │ SOL 145 flutter (Phase E)  ← needs Phase D    │
                         │ SOL 146 gust (Phase F)     ← needs Phase D    │
                         └─────────────────────────────────────────────┘
```

### 1.1 Matrix nomenclature (NASTRAN aeroelastic convention)

These symbols are used throughout the code, theory doc, and design proposals; they map
directly onto the MSC/NX *Aeroelastic Analysis User's Guide* (Rodden & Johnson) and the
ZAERO correction theory.

| Symbol | Meaning | Built in |
|--------|---------|----------|
| `w_j`  | Downwash (normalwash) at aero box `j` from structural deflection, normalised by freestream | VLM / spline |
| `w_g`  | **Baseline/additional normalwash** `W2GJ`: camber + twist + incidence, plus additive CFD/WT `Δα` correction. Present at zero structural deflection. | `aero/integration.py` |
| `AJJ`  | Inviscid aero influence coefficient: `{w_j} = [AJJ]{cp}` (real for VLM, complex for the future DLM) | `aero/vlm.py` |
| `AJJ*` | **Corrected** AIC after applying the chosen correction (`Wkk`, `WT1`, or `WT2`) | `aero/corrections.py` |
| `cp`   | Pressure coefficient on each box | solve `AJJ*⁻¹ (w_j + w_g)` |
| `Skj`  | Integration matrix: box pressures → box resultant forces (area weighting) | `aero/integration.py` |
| `Djk`  | Differentiation/substantial-derivative matrix: box deflection → downwash (`−I` at k = 0; the documented Phase D swap point) | `aero/integration.py` |
| `Wkk`  | Diagonal multiplicative correction on the inviscid AIC | `aero/corrections.py` |
| `WT1`  | **Force/moment correction matrix**: matches given spanwise lift/torque | `aero/corrections.py` |
| `WT2`  | **Pressure (downwash) weighting matrix**: matches given `{cp}` | `aero/corrections.py` |
| `G_kg` | Spline matrix: structural g-DOF → aero box deflection & slope (`g_slope`/`g_disp`) | `aero/spline.py` |
| `Q_aa` | Generalised aero stiffness on structural DOF: `G_kgᵀ Skj AJJ*⁻¹ Djk G_kg` | `aero/coupling.py` |
| `Q_hh` | Modal (h-set) GAF: `Φᵀ Q_aa Φ` | `aero/coupling.py::build_gaf` |
| `q`    | Dynamic pressure ½ρV² | TRIM / FLFACT |

The single relation that ties it all together for **static aeroelastics**:

```
(K_aa − q · Q_aa) · u_a  =  q · Q_ax · δ_x  +  q · f_g  +  f_ext
   where   Q_aa = G_kgᵀ · Skj · AJJ*⁻¹ · Djk · G_kg          (flexible increment)
           Q_ax = rigid aero load sensitivity to trim variables δ_x
           f_g  = G_kgᵀ · Skj · AJJ*⁻¹ · w_g                 (camber/twist/incidence + CFD/WT)
```

with **divergence** the eigenvalue problem `det(K_aa − q·Q_aa) = 0` for the smallest
positive `q`, and the **balanced maneuver** adding the inertia-relief load
`f_inertial = M_ax · a` (Step 53).

### 1.2 As-built module map

```
sbeam/aero/       aero_model.py, panel.py, vlm.py, integration.py, corrections.py,
                  section_correction.py, section_data.py, body_correction.py, strip.py,
                  spline.py, coupling.py
sbeam/solver/     sol144.py (trim/derivatives/divergence/maneuver), maneuver_qs.py
                  (Phase G0 increment 1), sol103.py (modal basis), sol101.py
sbeam/results/    f06_writer.py, load_export.py, monitor_points.py, maneuver_output.py
sbeam/viewer/     aero_view.py, aero_correction_view.py, case_control_ui.py
```

The parser/data-model surface (cards, `BulkData` dicts, case control) is documented in
`docs/10_standard/01_beam_model.md` and `docs/10_standard/02_card_reference.md`; the
solver/output surface in `docs/10_standard/05_aeroelastics.md`.

---

## 2. Delivered steps (bodies pruned — full records in `docs/40_history/00_completed_development.md`)

| Step | Deliverable |
|------|-------------|
| 39 | `AEROS` reference data, aero coordinate & symmetry handling |
| 40 | `CAERO1` box meshing (`panel.py`) |
| 41 | Steady VLM AIC with symmetric/antisymmetric images (`vlm.py`) |
| 42 | `Skj`/`Djk` integration + baseline incidence `w_g` (`W2GJ`) |
| 43 | AIC corrections: `Wkk` diagonal, `WT1` force/moment matching, `WT2` pressure matching |
| 44 | Viewer rigid-aero visualisation |
| 45 | `SET1` + `SPLINE2` parsing |
| 46 | SPLINE2 beam-spline matrix (`spline.py`; rewritten as the NASTRAN infinite beam spline at AC7) |
| 47 | `ATTACH` rigid-body spline + `SPLINE0` zero-displacement |
| 48 | `SPLINE1` surface spline — **deferred** (stub raises; see backlog Tier 4) |
| 49 | Force transfer & coupled smoke test |
| 50 | Aero stiffness `Q_aa` + modal-truncation ROM with mode-acceleration recovery |
| 51 | Trim card set parsing (AESTAT/AESURF/AELIST/TRIM/DIVERG + TRIMVAR/TRIMOBJ/TRIMCON) |
| 52 | SOL 144 trim solve (determined + over-determined) + flexible derivatives + `Ω×r` rate aero |
| 53 | Balanced maneuver loads & inertia relief (net aero + inertial load export) |
| 54 | `CHORDCP` CFD/WT steady-pressure injection (closed as AC6) |
| 55 | Aeroelastic divergence (`DIVERG` sweep, `q_div`/`V_div`) |
| 56 | SOL 144 f06 output + flight/maneuver-load export (with AE10 CLI dispatch) |
| 57 | Viewer SOL 144 results + case-control rework |
| 58 | Dihedral / anhedral (±Γ) correctness |
| AC1–AC8 | Steady close-out: doc scrub, AE8a/AE8b unrestrained derivatives, warnings, viewer gaps, CHORDCP, AE14 fidelity (fuselage PBAR + SPLINE2 rewrite), AE15 accepted residual (Study A2) |
| G0 inc. 1 | DLM-free quasi-steady transient maneuver loads (`MLOADS` card set, `maneuver_qs.py`) |

---

## 3. Follow-on phases — pointers only (the plan lives elsewhere)

The forward plan is priority-ordered in **`docs/30_future/00_backlog.md`** (mission
statement + mission-tagged priority list, 2026-08-04 structure; parked items in
`02_parked.md`). Per-phase design detail:

- **Loads-process completion (gust cases, case matrix, envelope/report)** — backlog
  near-term items; Steps 59–63 (free-free modal basis, `MASSSET` mass cases, free-flight
  coupling) are closed, see `docs/40_history/07_maneuver_transient.md`.
- **Phase D (DLM) + SOL 145 flutter + SOL 146 gust** — backlog Phase D chain;
  full design in `designs/dlm_rfa_flutter_gust.md` (kernel, GAFs, PK/KE, RFA, gust). The
  ZTAW out-of-phase correction recovery belongs here, building on the Step 43 steady
  correction layer.
- **Matrix/GAF export and reuse** — backlog Phase D chain; `designs/matrix_gaf_export.md`
  and `designs/matrix_reuse_store.md`.
- **Phase G (full unsteady MLOADS + ASE)** — gated on Phase D; outline parked
  (`02_parked.md` G0-e) and the Phase G notes inside `designs/dlm_rfa_flutter_gust.md`.

---

## 4. References — Analytical Methods

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
  splines (SPLINE1/SPLINE2 formulation, `G_kg`; the infinite beam spline Eqs. 2-48…2-63
  implemented at AC7).
- ZONA Technology, *ZAERO User's Manual* §1.4 (3-D Spline module: thin-plate, infinite-plate,
  beam, rigid-body attachment).

**Static aeroelastics / trim / divergence (Phase C)**
- Rodden, W. P., Johnson, E. H., *MSC/NASTRAN Aeroelastic Analysis User's Guide* — SOL 144
  formulation, trim, stability derivatives, the `Q_aa`/`AJJ`/`Skj`/`Djk`/`Wkk` matrix set,
  the unrestrained (mean-axis) algorithm Eqs. 2-111…2-134, and the HA144 test-problem
  library (canonical verification models).
- ZONA Technology, *ZAERO User's Manual* §1.10, §5.8 (modal trim; over-determined trim via
  `TRIMOBJ`/`TRIMCON`/`TRIMVAR`; longitudinal/lateral DOF rules) and *Theoretical Manual*
  Ch. 12 (modal mean-axis derivatives — the sbeam cross-check).
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

## 5. Validation-case index (all delivered; IDs cited across tests and docs)

| ID | Case | Validates |
|----|------|-----------|
| **V-A1** | Rectangular flat wing, several AR; mesh refinement; sym + antisym | VLM `C_Lα`, mesh-independence, image signs |
| **V-A2** | Swept tapered planform from SP-405 sample | VLM span loading, `C_M` |
| **V-A3** | Force/moment & pressure matching round-trip | `WT1`/`WT2` reproduce a supplied load/`cp` |
| **V-A4** | Camber/twist/incidence baseline (`w_g`) | `w_g` rigid-load contribution |
| **V-B1** | Spline rigid-body + linear-twist recovery | `G_kg` exactness (machine-precision gate) |
| **V-B2** | Uniform pressure / `w_g` → grid loads round-trip | `G_kgᵀ` energy consistency |
| **V-B3** | ATTACH/SPLINE0 rigid-body recovery | rigid-attachment exactness |
| **V-C1** | Flexible wing trim, derivative ratios | SOL 144 trim vs MSC **HA144A** |
| **V-C2** | Goland wing + idealised swept cantilever | Divergence `q_div` |
| **V-C3** | q→0 reduction; modal ROM vs direct; mode-count convergence | SOL 144 → SOL 101 identity; mode-acceleration recovery |
| **V-C4** | Over-determined trim (redundant effectors) | `TRIMOBJ`/`TRIMCON` minimization |
| **V-C5** | Balanced maneuver (symmetric pull-up at `n_z`) | inertia-relief balance, net-load export |
| **V-C6** | Rate (damping) derivatives from `Ω×r` incidence | quasi-steady `C_mq`/`C_lp`/`C_nr` |

Each ships as a `tests/` model plus an integration test asserting the reference value within
a documented tolerance, exactly like the existing `test_verification.py` cantilever /
simply-supported cases. The one accepted residual is AE15 (q=1200 moment/ELEV columns,
2.9–5.3%, six xfail gates — Study A2).
