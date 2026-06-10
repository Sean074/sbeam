# AMODE — Assumed-Mode Card Design

**Status:** Design proposal — not yet implemented.
**Target release:** Phase 1 (rigid rotating set) in `0.3.0`; Phase 2 (elastic rotating set) in `0.4.0`, **required prior to `1.0.0` production release**.
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-06-10

This document is the design proposal for a non-standard sbeam BDF card, `AMODE`, that lets the user introduce a generalized coordinate representing a rigid (Phase 1) or elastic (Phase 2) rotation of a set of grids about a CORD2R-defined hinge axis, against a user-supplied rotational stiffness `k`. The motivating use case is control-surface (aileron, elevator, rudder, flap, tab) modal behaviour for vehicle-level SOL 103 analysis feeding downstream loads / flutter tools.

---

## 1. Motivation

### 1.1 The engineering problem

In vehicle-level modal analysis, control surfaces participate in flutter and dynamic-loads behaviour through two distinct mechanisms:

1. **Hinge rotation of the rigid surface about its hinge line**, restrained by actuator stiffness and hinge-line bearing compliance. The natural frequency of this mode (the "control-surface rotation mode") is typically 5–25 Hz on transport-category aircraft and is the dominant degree of freedom in standard binary flutter analyses (bending–rotation, torsion–rotation).
2. **Elastic deformation of the control surface itself** — bending and torsion of the surface skin/spar structure — coupled to the hinge rotation. These modes start at ~20–80 Hz on typical metallic control surfaces and lower on composite ones; they matter for higher-frequency flutter mechanisms and for transient response under buffet / gust loads.

For Phase 1 of a vehicle-level workflow, item (1) is the load-bearing addition: it captures the dominant rotational mode without requiring the user to discretise the actuator-spring-mass-bearing kinematics by hand. Item (2) is addressed in Phase 2 (see Section 7).

### 1.2 Why no standard NASTRAN card fits cleanly

NASTRAN gives the user three approximate paths to the rigid-rotation-on-spring case:

| NASTRAN form | Why it fails as a UX |
|---|---|
| `DMIG` (direct matrix input — generalised) | User computes `Φᵀ·M·Φ` and `Φᵀ·K·Φ` by hand and emits matrix entries. Not a usable workflow for repeated trade studies. |
| `RBE2` to a hinge grid + `CELAS1`/`CBUSH` torsion spring | Closest standard option, but requires a separate "hinge grid" that doesn't lie on the structure, plus careful coordination of the RBE2 dependent-DOF list and the spring DOF. Cycle detection across RBE2 + the spring DOF gets confusing. The "hinge axis" is implicit, not declared. |
| Superelement (SE) with attachment + constraint modes | Overkill; requires defining a substructure boundary and a CMS reduction. |

A single bespoke card that *names* the hinge axis (via CORD2R), the rotating set (via SET1), and the stiffness `k` is meaningfully cleaner than any of these. The cost is one new bulk card and one new transformation in the assembly path.

### 1.3 What this card delivers

- A single generalized coordinate `q` per AMODE card, representing rotation about the hinge x-axis.
- Automatic effective-inertia computation: `I_q = Φᵀ M Φ` falls out of the existing mass-assembly pass — including CONM2 inertia tensors at the rotating grids — without the user computing anything by hand.
- Direct integration with the existing RBE2 / RBE3 / RBAR DOF-reduction path. Cycle detection extends naturally.
- A new f06 section, "ASSUMED MODE PARTICIPATION", labelling each mode's `q` content so the user can see at a glance which modes are control-surface dominated.
- Viewer animation of the rotating set following the assumed-mode shape.

---

## 2. Scope

### 2.1 Phase 1 — Rigid rotating set (target `0.3.0`)

All grids listed in the AMODE SETID move as a **rigid body** rotating about the hinge x-axis. Their 6 DOFs are kinematically dependent on the single generalized coordinate `q`. The mass and inertia of these grids (including any CONM2 contributions) are folded into the effective rotational inertia `I_q`. The user-supplied `k` is the only stiffness contribution to the q DOF.

### 2.2 Phase 2 — Elastic rotating set (target `0.4.0`, required prior to `1.0.0`)

All grids in the AMODE SETID retain their structural DOFs *and* participate in the rotation. The assumed mode adds a generalized coordinate `q` that augments rather than replaces the grid DOFs. Internal control-surface bending/torsion modes appear at their structural frequencies, coupled through the hinge to `q`. See Section 7 for the design sketch and why this is a 1.0.0 blocker for the vehicle-level tool.

### 2.3 Out of scope (Phase 3+)

- **Damping** about the hinge axis — out of scope for SOL 103 (undamped modes). The card field order leaves room for a `C` field for future SOL 109 / SOL 111 / SOL 112 use.
- **Non-hinge assumed modes** — e.g. assumed bending Ritz vectors for fuel-slosh or antenna-flap. The `TYPE` field on AMODE leaves room for `TYPE=BEND`, `TYPE=TRANS` in a future release. Phase 1 implements `TYPE=HINGE` only.
- **Coupled multi-axis hinge** (gimbal-mount style) — out of scope. A two-axis hinge would require two AMODE cards sharing a common rotating set, which the cycle-detection logic must reject in Phase 1.
- **Free-play / hinge backlash** non-linearities — out of scope. `k` is linear.

---

## 3. Card Definition

### 3.1 `AMODE`

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Name | `AMODE` | ID | CID | K | SETID | TYPE | C | — | — | — |
| Type | str | int | int | float | int | str | float | — | — | — |
| Default | — | — | — | — | — | `HINGE` | `0.0` | — | — | — |
| Phase | 1 | 1 | 1 | 1 | 1 | 1 | 3 | — | — | — |

| Field | Description |
|---|---|
| `ID` | Unique AMODE identifier. Used as the q-DOF label in f06 and viewer output. |
| `CID` | Identifier of a `CORD2R` coordinate system whose local x-axis is the hinge axis. The CORD2R origin point (field `A`) defines the location of the hinge axis in space. |
| `K` | Rotational stiffness about the hinge x-axis [moment / radian]. Must be `> 0`. |
| `SETID` | Identifier of a `SET1` card listing the grid IDs that rotate with the hinge. |
| `TYPE` | Assumed-mode type. Phase 1 supports `HINGE` only. Reserved values for future phases: `HINGE_ELASTIC` (Phase 2), `BEND` (Phase 3+), `TRANS` (Phase 3+). |
| `C` | Rotational damping about the hinge x-axis. Parsed but unused in SOL 103. Reserved for SOL 109 / 111 / 112. |

**Validation rules:**

- `ID` must be unique across all AMODE cards.
- `CID` must refer to a defined `CORD2R` card.
- `SETID` must refer to a defined `SET1` card.
- Every grid in the SET must exist in `bulk.grids`.
- No grid may simultaneously be (a) a dependent DOF of an RBE2/RBE3/RBAR *and* (b) a member of an AMODE SET. The cycle-check at assembly time raises `ValueError` with the offending GID.
- No grid may be a member of more than one AMODE SET. (A grid attached to two hinges is geometrically over-constrained.)
- `K > 0`. Zero stiffness produces a singular K and a spurious zero-frequency mode; if the user genuinely wants this, they can set `K = 1e-12` and accept the warning.

### 3.2 `SET1` (re-used from NASTRAN)

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Name | `SET1` | SID | G1 | G2 | G3 | G4 | G5 | G6 | G7 |
| Type | str | int | int | int | int | int | int | int | int |

Continuations supported using the same multi-line continuation pattern as `SPC1`. SET1 is a standard NASTRAN card; sbeam will parse it identically.

### 3.3 Example: aileron at wing tip

```
$ Aileron hinge: CORD2R 100, hinge x-axis from (5.0, 0.5, 0.0) along +X
CORD2R, 100,  0,   5.0, 0.5, 0.0,   5.0, 0.5, 1.0
+,                  6.0, 0.5, 0.0

$ Aileron mass grids (4 CONM2-bearing grids on the control surface)
SET1, 200,  101, 102, 103, 104

$ Assumed-mode card: aileron rotation about CID 100 local-x,
$ stiffness 250 N·m/rad about the hinge, applies to grids in SET1 200
AMODE,  1, 100, 250.0, 200, HINGE
```

The user reads this as "AMODE #1, hinge axis = CID 100, k = 250 N·m/rad, rotating set is SET1 200, type is rigid hinge."

---

## 4. Mathematical Formulation (Phase 1)

### 4.1 Hinge-axis kinematics

Let `R` be the 3×3 CID→global rotation matrix (column 1 of `R` is the hinge x-axis expressed in the global frame). Let `p_hinge` be the CORD2R origin in the global frame.

For a grid at global position `r_i`, its position in **hinge-local** coordinates is:

```
r_i_hinge = Rᵀ · (r_i − p_hinge)        ≡ (x_h, y_h, z_h)
```

For a small rotation `q` (radians) about the hinge x-axis, the rigid-body displacement of grid `i` in hinge-local coordinates is:

```
Δu_hinge = (    0   ,  −z_h · q ,  +y_h · q )
Δθ_hinge = (  +q    ,     0     ,     0     )
```

Transformed back to global coordinates, the grid's 6-vector displacement is `Φ_i · q`, where:

```
Φ_i[0:3] = R · (    0,  −z_h,  +y_h )ᵀ     translational, per radian
Φ_i[3:6] = R · ( +1, 0, 0 )ᵀ  =  R[:, 0]   rotational, per radian (= hinge axis in global)
```

The full assumed-mode shape vector `Φ ∈ ℝ⁶ᴺ` is the concatenation: `Φ_i` at the 6 rows of each grid `i ∈ SETID`, zero elsewhere.

### 4.2 Augmented system

The augmented displacement vector is:

```
u_aug = [ u_full (6N) ,  q (n_amode) ]
```

For each AMODE, the rotating-set grids' 6 DOFs become **dependent** on the corresponding `q`. The reduction is implemented as a transformation matrix `T_amode` of shape `(6N + n_amode) × n_red` such that the dependent rows scatter `q` to the rotating-grid DOFs via `Φ_i`. After RBE2/RBE3/RBAR have produced their own `T_rbe`, the composed reduction is:

```
T = T_rbe @ T_amode_in_reduced_space
```

The augmented stiffness has the user-supplied `k` on the q-block diagonal:

```
K_aug = [ K_global ,    0    ]
        [    0     ,  diag(k) ]
```

The augmented mass has zero in the q-block (the effective inertia is recovered by reduction, not declared):

```
M_aug = [ M_global ,  0  ]
        [    0     ,  0  ]
```

After reduction `K_red = Tᵀ K_aug T`, `M_red = Tᵀ M_aug T`, the standard `scipy.linalg.eigh(K_red, M_red)` solve proceeds unchanged. The generalised effective inertia `I_q = Φᵀ M_global Φ` falls out automatically of `Tᵀ M_aug T` — including any CONM2 inertia tensor contributions at the rotating grids — without the user computing anything.

### 4.3 Why the q DOF for `M` is zero

The assumed-mode coordinate `q` has no *direct* inertia of its own; all inertia is contributed by the structural mass (CBAR + CONM2) at the rotating-set grids, which the reduction `Tᵀ M_aug T` correctly folds into the q row/column. Adding a non-zero entry on the q diagonal of `M_aug` would double-count.

---

## 5. Implementation Plan

### 5.1 File touches

| File | Change |
|---|---|
| `sbeam/model/amode.py` | **New.** `@dataclass Amode(id, cid, k, set_sid, type, c=0.0)`. |
| `sbeam/model/bulk_data.py` | Add `amodes: dict = field(default_factory=dict)`, `sets: dict[int, list[int]] = field(default_factory=dict)`. |
| `sbeam/parser/bdf_reader.py` | Add `_handle_amode`, `_handle_set1`. Wire into the keyword dispatch. SET1 multi-continuation loop mirrors SPC1. |
| `sbeam/assembly/amode.py` | **New.** `build_amode_transformation(bulk, grid_index) → (T_amode, dep_dofs, red_dofs, q_dof_indices, K_q_diag)`. |
| `sbeam/assembly/stiffness.py` | Add `assemble_augmented_stiffness(bulk, K_global)` returning the `(6N + n_amode) × (6N + n_amode)` augmented stiffness with `K_q_diag` on the q block. |
| `sbeam/assembly/mass_matrix.py` | Add `assemble_augmented_mass(bulk, M_global)` returning the augmented mass with a zero q block. |
| `sbeam/solver/sol103.py` | Compose `build_rbe3_transformation` (existing) with `build_amode_transformation` (new). Order: RBE2/3/RBAR reduce *first*, then AMODE. Cycle detection: any grid in an AMODE SET that is already a `dep_dof` from RBE2/3/RBAR raises `ValueError`. |
| `sbeam/results/results.py` | Extend `Sol103Result` with `amode_participations: dict[int, np.ndarray]` — per AMODE ID, the q-component of every mode shape, shape `(n_modes,)`. |
| `sbeam/results/f06_writer.py` | Add "A S S U M E D   M O D E   P A R T I C I P A T I O N" table after the eigenvalue table. Columns: MODE NO., AMODE ID, q AMPLITUDE, % OF MODE NORM. |
| `sbeam/viewer/geometry.py` | `_amode_grid_coords(...)` to compute the rotating-set displacements from `Φ_i · q` for visualisation. |
| `sbeam/viewer/results_view.py` | Add an "AMODE Participation" panel under SOL 103 results showing the `Sol103Result.amode_participations` table. |
| `docs/10_standard/01_beam_model.md` | Add AMODE and SET1 to the bulk-data card reference. |
| `docs/10_standard/02_card_reference.md` | Add full field-layout tables for AMODE and SET1. |
| `docs/10_standard/04_modal_analysis.md` | Add a section explaining the augmented-system formulation and where AMODE inserts in `run_sol103`. |
| `tests/parser/test_amode.py` | **New.** Card parse tests; validation rules; cycle detection. |
| `tests/assembly/test_amode_transform.py` | **New.** Unit tests on `build_amode_transformation` — shape, dep/red split, Φ_i values. |
| `tests/integration/test_verification.py` | **Extend** with V19–V23 (see Section 6). |
| `tests/integration/bdf/v19_amode_rigid_hinge.bdf` etc. | **New** BDF files for V19–V23. |
| `CHANGELOG.md` | `[Unreleased]` → `Added: AMODE card (Phase 1 — rigid hinge)`. |
| `docs/30_future/00_backlog.md` | Move the Phase 1 step to completed; add Phase 2 (Section 7) as a new step. |

### 5.2 Order of operations in `run_sol103`

```
1. K_global = assemble_global_stiffness(bulk)               # 6N × 6N
2. M_global = assemble_global_mass(bulk)                    # 6N × 6N
3. K_aug = assemble_augmented_stiffness(bulk, K_global)     # (6N+n_a) × (6N+n_a)
4. M_aug = assemble_augmented_mass(bulk, M_global)          # (6N+n_a) × (6N+n_a)
5. T_rbe, dep_rbe, red_rbe = build_rbe3_transformation(bulk, grid_index)
6. T_amode, dep_a, red_a, q_idx, K_q = build_amode_transformation(bulk, grid_index, red_rbe)
   - cycle check: dep_a ∩ dep_rbe must be empty
   - K_aug[q_idx, q_idx] += K_q  (user-supplied k values)
7. T = T_rbe @ T_amode  (composed, augmented)
8. K_red = Tᵀ K_aug T,  M_red = Tᵀ M_aug T
9. Apply SPCs (q DOFs are never constrained by SPC — they live above the 6N range)
10. eigh(K_free, M_free) — unchanged
11. Reconstruct full mode shapes: full_phi = T @ phi_red    # includes both grid-DOF and q-DOF rows
12. Extract per-AMODE q amplitudes: amode_participations[id] = full_phi[q_idx_of_amode_id, :]
```

### 5.3 Sparse-path implications

The augmented system inherits the sparse / dense decision of `solve_modes`. Two considerations:

1. **`K_aug` density:** Adding `n_amode` rows/cols of mostly-zero with `k` on the q diagonal preserves sparsity. Use `scipy.sparse.bmat` to compose.
2. **Reduction densifies:** `Tᵀ K_aug T` produces a dense ndarray when `T` is dense (the AMODE `T_amode` has the `Φ_i` blocks — dense by row but sparse by column count). The existing sparse-vs-dense gate in `solve_modes` will fall back to dense for AMODE-bearing models below `n_red = _DENSE_THRESHOLD`. For very large vehicle models with AMODEs, explicitly construct `T` as a sparse CSR — this is straightforward but worth a benchmark before claiming sparse compatibility.

### 5.4 Backward compatibility

A model with no AMODE cards must behave **bit-identically** to the current solver. The augmentation steps (#3, #4) become no-ops when `bulk.amodes` is empty; `T_amode = I(n_red)` and `K_q = ∅`. The V1–V18 regression suite must continue to pass without modification.

---

## 6. Verification Cases

| ID | Model | Analytic target | Tolerance |
|---|---|---|---|
| **V19** | Rigid one-element wing (very stiff CBAR, EI = 10¹²); single CONM2 mass `m=1.0` at offset `d=0.5` from a hinge axis at the origin, aligned with global X; CORD2R 1 = identity; AMODE k = 10.0 | `f = (1/2π)·√(k / m·d²) = (1/2π)·√40 ≈ 1.0066 Hz` | < 0.1 % |
| **V20** | V19 model with CORD2R rotated 30° about global Z (hinge axis no longer aligned with global X) | Frequency invariant under hinge-axis rotation — same 1.0066 Hz | < 0.1 % |
| **V21** | Cantilever beam (3 CBAR elements, standard `E·I·ρ·A`), CONM2 aileron mass at tip with offset, AMODE hinging the tip mass | Hand-derived 2-DOF reduced eigenvalue problem (q_wing_bending Ritz + q_aileron) solved separately in the test | < 5 % on both frequencies |
| **V22** | Symmetric model with two independent AMODEs (aileron-left, aileron-right) | Symmetric and antisymmetric modes appear at the close-but-not-equal expected frequencies | < 1 % on each |
| **V23** | Negative cases: (a) grid in both RBE2 GM list and AMODE SET; (b) grid in two AMODE SETs; (c) AMODE references undefined CORD2R; (d) AMODE references undefined SET1; (e) `K ≤ 0` | All raise `ValueError` with the offending ID in the message | exact-match assertion |

V19 is the load-bearing correctness test: a single-DOF analytic problem with no discretisation error means sbeam must match to floating-point precision. V20 catches every error class in the CID-to-global rotation. V21 is the coupling correctness test — if the reduction is done in the wrong order or `Tᵀ M_aug T` is mis-composed, V21 fails by 10s of percent.

### 6.1 Non-regression requirement

V1–V18 must pass identically after AMODE is merged. A CI step `pytest tests/integration/test_verification.py::TestV1*` through `TestV18*` running independently on every PR is the gate.

---

## 7. Phase 2 — Elastic Rotating Set (target `0.4.0`, required prior to `1.0.0`)

### 7.1 Why elastic modes in control surfaces matter

The Phase 1 rigid-rotating-set assumption is a useful first approximation but is **insufficient for production vehicle-level flutter and dynamic-loads analysis** for three reasons:

1. **Internal control-surface bending modes** (first bending of the aileron about its own neutral axis) typically lie in the 30–80 Hz band on metallic transport-category control surfaces, lower on composites and on large all-moving surfaces. These modes participate measurably in flutter mechanisms and in transient response under buffet and gust loads. Treating them as infinitely-stiff (Phase 1) shifts predicted flutter speeds non-conservatively.
2. **Control-surface torsion modes** couple to the hinge rotation mode and produce the binary "rotation–torsion" mechanism. Without the torsion DOF, the user cannot model this without a separate substructure analysis.
3. **Mass-balance / inertia effects** of mass items physically mounted on a deforming control-surface skin (e.g. balance weights, hinge fittings) are not captured by a rigid kinematic constraint.

For these reasons Phase 2 is **required before sbeam can be promoted to `1.0.0` as a vehicle-level modal/loads tool**. Phase 1 is adequate for the slender-beam educational `0.3.0` release; the vehicle-level claim depends on Phase 2.

### 7.2 Phase 2 design sketch

The Phase 2 implementation replaces the rigid kinematic constraint with an **augmenting** generalized coordinate:

| Aspect | Phase 1 (rigid) | Phase 2 (elastic) |
|---|---|---|
| Rotating-set grid DOFs | Eliminated from the reduced system; slaved to `q` via `Φ_i` | **Retained**; grid DOFs remain free |
| Number of reduced DOFs | `6N − 6·n_set + n_amode` | `6N + n_amode` |
| Stiffness q–q | `k` | `k` |
| Stiffness u–q coupling | (none — reduced out) | `K_uq` derived from the structural connection between rotating grids and the rest of the model |
| Mass q–q | Recovered by `Φᵀ M Φ` reduction | Recovered by `Φᵀ M Φ` over the rotating grids (same scalar) |
| Mass u–q coupling | (none — reduced out) | `M_uq = M @ Φ_set` — Coriolis-like coupling between grid translations and `q` |
| Internal modes of the rotating set | Removed (rigid) | Retained — appear at their structural frequencies in the eigensolution |
| Card change | — | `TYPE = HINGE_ELASTIC` |

Concretely, in Phase 2 the assumed mode `Φ` adds a *Ritz vector* to the basis rather than replacing the structural DOFs. The augmented system becomes:

```
K_aug = [ K_global ,   K_uq   ]
        [   K_quᵀ  ,    k    ]

M_aug = [ M_global ,   M_uq   ]
        [   M_quᵀ  , Φᵀ M Φ  ]
```

where `M_uq = M_global @ Φ_set_vector` and `K_uq = K_global @ Φ_set_vector` are computed once at assembly time. The eigensolve and reduction logic is otherwise unchanged.

### 7.3 Additional verification cases for Phase 2

| ID | Model | Analytic target |
|---|---|---|
| **V24** | Cantilever "aileron" (5-element beam) with CONM2 at root, AMODE TYPE=HINGE_ELASTIC at the root binding the *root grid only* to a hinge. The aileron is therefore a flexible beam vibrating about a sprung hinge. | First two frequencies: hinge-rotation mode (sprung-pendulum, low) and aileron-first-bending (cantilever, higher) — both have closed-form solutions |
| **V25** | V24 model with `k → ∞` (very large k) | The hinge-rotation mode frequency → ∞ (drops out); remaining modes match a fixed-root cantilever |
| **V26** | V24 model with `k → 0` | The hinge-rotation mode frequency → 0; the structure becomes a free-pinned beam |

### 7.4 Why this is required for `1.0.0` not `0.3.0`

The Phase 2 implementation is **non-trivial** — it requires `K_uq` and `M_uq` coupling terms, a careful examination of whether `Φᵀ M Φ` and the explicit q-block on `M` are correctly composed (no double-counting), and verification that the existing V1–V18 still pass when an AMODE is added to a flexible structure. Phase 1's clean separation (`T_amode` reduces independently of `T_rbe`) does not extend directly. Realistic effort estimate: **2 weeks**, split roughly into 1 week of math/code and 1 week of V24–V26 verification + regression hardening.

Shipping Phase 1 first lets the user community exercise the card UX and provides real-world feedback on the SET1-as-rotating-set choice, the CORD2R-as-hinge-axis choice, and the f06/viewer output formats — *before* Phase 2 locks in those API decisions.

---

## 8. Open Decisions

| # | Decision | Recommendation | Owner |
|---|---|---|---|
| 1 | Card name: `AMODE` vs `HMODE` / `CSURF` / `RHGNGE` | `AMODE` — leaves room for non-hinge Ritz modes in future | Author |
| 2 | Rigid (Phase 1) vs elastic-first | **Rigid first**, elastic as Phase 2 required pre-1.0.0 | Author |
| 3 | User-supplied k exclusive vs additive to CBUSH/CELAS spanning rotating-set grids | Exclusive: sbeam warns at assembly if a CBUSH spans two grids both in the AMODE SET (the spring is slaved out anyway by the rigid reduction; the warning prevents silent double-stiffening expectations) | Author |
| 4 | Hinge-axis location: CORD2R origin vs centroid of SETID grids vs explicit field | CORD2R origin (field A) — already unambiguous and matches how a hinge-line is physically defined on the airframe | Author |
| 5 | `q` in f06 displacement table: synthetic "GID 0, AMODE 1" row vs separate table | **Separate "AMODE Participation" table** (Section 5.1) — keeps the conventional displacement table NASTRAN-clean | Author |
| 6 | Free-free interaction: extra zero-freq modes when k=0 in a free-free model | Validate V6 still passes after AMODE is added; document that AMODE with `k > 0` does NOT add zero-frequency modes to a free-free model | Author |
| 7 | Generalised damping `C` field on the card | Reserve the field; parse it; document as deferred to Phase 3+ | Author |
| 8 | Multiple AMODEs sharing a SETID | Reject in Phase 1 (geometric over-constraint). Allow in Phase 2 only if axes are orthogonal (gimbal-mount; not in current scope) | Author |

---

## 9. Risks & Effort

### 9.1 Phase 1 effort

| Task | Effort | Risk |
|---|---|---|
| Card definition + parser + cycle check | 1 day | Trivial |
| `build_amode_transformation` + augmented K/M | 2 days | Low — same shape as `build_rbe3_transformation` |
| SOL 103 integration + sparse path verification | 1 day | Medium — augmented matrix sparse-vs-dense gating; may force dense for AMODE-bearing models below threshold, like free-free does |
| V19–V23 verification BDFs and tests | 1.5 days | Low — analytic targets are unambiguous |
| f06 participation table | 0.5 day | Trivial |
| Viewer animation of AMODE motion | 1 day | Low |
| Docs (Beam_model.md, card_definition.md, Modal_analysis.md) | 0.5 day | Trivial |
| **Total Phase 1** | **~7.5 days** | **Low overall** |

### 9.2 Phase 2 effort

| Task | Effort | Risk |
|---|---|---|
| Augmented K_uq, M_uq derivation and unit tests | 3 days | Medium — careful book-keeping required to avoid double-counting |
| Composition with RBE2/RBE3/RBAR reduction in the elastic case | 2 days | Medium |
| V24–V26 verification BDFs and tests | 2 days | Low |
| Regression hardening — V1–V23 must still pass | 1 day | Low |
| Sparse-path benchmark for vehicle-scale models | 1 day | Medium — verify shift-invert factorisation still well-conditioned with augmenting Ritz vectors |
| Docs update | 0.5 day | Trivial |
| **Total Phase 2** | **~10 days (~2 weeks)** | **Medium** |

### 9.3 Top correctness risks (Phase 1)

1. **CID→global rotation in `Φ_i`** — easy to get the transpose wrong. V20 (hinge rotated 30°) is the targeted catch.
2. **Reduction composition order** — RBE2/RBE3/RBAR must reduce *before* AMODE, because AMODE rows would otherwise reference DOFs that get eliminated by RBE. The cycle-check at step 6 of Section 5.2 must be explicit, not implicit.
3. **Cycle detection for nested constraints** — a grid that is the GA of an RBAR *and* in an AMODE SET would be silently overridden by whichever reduction runs last; the explicit `dep_a ∩ dep_rbe` check prevents that.
4. **SET1 multi-continuation parsing** — the existing SPC1 multi-continuation loop (`_handle_spc1`) is the template; lift it.

---

## 10. References

- **NASTRAN equivalent forms:**
  - MSC.Nastran Quick Reference Guide — `DMIG`, `RBE2`, `CELAS1`, `CBUSH`, `SE`/`SEBSET`/`SECSET`, `SET1`.
  - Felippa, *Introduction to Finite Element Methods*, Ch. 12 (constraint elimination and reduction).
- **Aeroelastic context:**
  - Bisplinghoff, Ashley, Halfman, *Aeroelasticity*, Dover edition, Ch. 9 (control-surface flutter).
  - Hodges, Pierce, *Introduction to Structural Dynamics and Aeroelasticity*, 2nd ed., §4.5 (assumed-modes / Rayleigh-Ritz).
- **Component-mode synthesis:**
  - Craig, Bampton, "Coupling of substructures for dynamic analysis", AIAA Journal Vol. 6 No. 7 (1968).
- **In-project precedents:**
  - `assembly/rbe3.py` — the existing RBE2/RBE3/RBAR transformation builder is the structural template for `build_amode_transformation`.
  - `docs/10_standard/04_modal_analysis.md` § "RBE3 Constraint Assembly" — the reduction-in-`run_sol103` insertion-point pattern.
  - `tests/integration/test_verification.py::TestV13Rbe2RigidCoupling` and `TestV18Rbe2LeverArm` — the test-anchor pattern that V19–V23 will follow.

---

## 11. Acceptance Criteria

### 11.1 Phase 1 (target `0.3.0`)

- All V19–V23 pass with the stated tolerances.
- All V1–V18 pass unchanged.
- `pytest --cov` shows ≥ 90% coverage on `sbeam/assembly/amode.py` and ≥ 85% on the AMODE branches of `sbeam/solver/sol103.py`.
- A `sample/sample_amode_aileron.bdf` model exists demonstrating the card and producing a documented first-mode frequency.
- `docs/10_standard/01_beam_model.md`, `docs/10_standard/02_card_reference.md`, `docs/10_standard/04_modal_analysis.md`, `README.md` ("Supported BDF Cards" table) all updated.
- `CHANGELOG.md` `[Unreleased]` lists `AMODE (TYPE=HINGE)` under `### Added`.

### 11.2 Phase 2 (target `0.4.0`, blocker for `1.0.0`)

- All V24–V26 pass with the stated tolerances.
- All V1–V23 pass unchanged.
- The Phase 1 `TYPE=HINGE` continues to behave bit-identically (rigid-rotating-set path preserved).
- A `sample/sample_amode_aileron_elastic.bdf` demonstrates the elastic case with an internal aileron-bending mode visible in the output.
- `docs/30_future/designs/amode_card.md` (this document) updated to reflect any Phase 2 design changes from this proposal.
