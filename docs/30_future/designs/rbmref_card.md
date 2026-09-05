# RBMREF — Rigid-Body-Mode Reference Basis Design

**Status:** Design proposal — not yet implemented.
**Target release:** `0.3.0` (alongside `AMODE` Phase 1).
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-06-10
**Related:** [`amode_card.md`](amode_card.md) — composes cleanly with this feature.

This document is the design proposal for a non-standard sbeam BDF card, `RBMREF`, that rebases the 6 rigid-body modes produced by a free-free SOL 103 into a user-declared mechanical basis (surge / sway / heave / roll / pitch / yaw) at a CORD2R-defined reference point. The motivating use case is vehicle-level free-free modal analysis where the rigid-body modes must be expressed at a known aero reference (typically 25% MAC) in known body axes for downstream aero correction, flight-dynamics coupling, and loads-tool ingestion.

---

## 1. Motivation

### 1.1 The engineering problem

In a free-free SOL 103, the global stiffness matrix `K` has a 6-dimensional null space corresponding to the 6 rigid-body motions of the unconstrained structure. The generalised eigenvalue problem `K φ = λ M φ` returns 6 eigenvectors at `λ ≈ 0` whose columns span that null space — but the *specific basis vectors within the null space* are not uniquely determined. They depend on the numerical decomposition used by the eigensolver, and any orthonormal-in-M basis for the null space is a mathematically valid output.

For aero correction, flight-dynamics coupling, gust/manoeuvre loads tools, and any workflow that needs to identify "which mode is pitch" or "what is the effective inertia for the heave mode," the user must currently:

1. Inspect each of the 6 returned eigenvectors,
2. Project the displacements onto unit translations and rotations at a chosen reference point,
3. Identify each mode by the dominant projection,
4. Compute the effective generalised mass for each motion separately.

This is fragile and must be repeated on every run. A declarative basis at a user-specified reference point removes the inspection step entirely.

### 1.2 Why standard NASTRAN does not solve this declaratively

NASTRAN's free-free SOL 103 returns rigid-body modes in whatever basis the Lanczos (or equivalent) eigensolver produces. The "CG / principal-axes" interpretation that users often *expect* comes from a separate post-modal diagnostic — `PARAM, GRDPNT` (Grid Point Weight Generator) — which computes the inertia tensor at a reference point but does *not* rebase the modes themselves. `SUPORT` cards designate specific DOFs as rigid-body directions for Craig-Bampton dynamic reduction in substructure analysis, but they are not wired into the normal-modes solution sequence.

The result is that NASTRAN users routinely scaffold their own rigid-body identification logic externally — typically as a MATLAB / Python post-processing step that consumes the f06 — and the rebase is informal.

**RBMREF gives this capability declaratively, inside the solver, with the result written into the f06 in a labelled, machine-readable form. This is a meaningful improvement over stock NASTRAN behaviour for vehicle-level workflows.**

### 1.3 What this card delivers

- A single CORD2R-defined reference point and axis system as the rigid-body basis.
- Six labelled rigid-body modes in the output: SURGE, SWAY, HEAVE, ROLL, PITCH, YAW.
- A reported generalised mass per RBM that equals the effective rigid-body inertia at the reference point — i.e. the GPWG output but expressed per mode, useful directly for aero coupling.
- An inertia-tensor table at the reference point as a side effect.
- f06 and viewer integration: the rigid-body block appears before the elastic eigenvalue table; the elastic mode numbering starts at mode 7.
- Friendly validation: declaring RBMREF on a constrained (non-free-free) model produces a clear error, not a silent mis-identification.

---

## 2. Scope

### 2.1 In scope (Phase 1, target `0.3.0`)

- Single RBMREF card per model (singleton).
- Reference point defined via the origin of a CORD2R; rebase axes defined by the CORD2R local x/y/z.
- Mechanical normalisation (`NORM=MECH`): each RBM column is a unit translation or unit rotation at the reference point — columns are NOT mutually M-orthonormal but are M-orthogonal to all elastic modes.
- Optional M-orthonormalisation (`NORM=MASS`): Gram–Schmidt of the mechanical basis against M, producing columns that satisfy `Φᵀ M Φ = I` while remaining labelled SURGE…YAW.
- Frequency tolerance `TOL` to identify which returned modes are RBMs.
- Sanity-check field `NRBM` for the expected number of RBMs (default 6); raises `ValueError` if the count differs.
- Free-free only — rejects with `ValueError` on a constrained model.
- f06 output: labelled rigid-body section + inertia tensor at the reference point.
- Viewer output: RBM modes shown as labelled selectable entries.

### 2.2 Out of scope

- **Multiple RBMREF cards per model** — no current use case; would require a basis-selection mechanism per subcase.
- **Subcase-scoped rebase** — RBMREF applies to all SOL 103 subcases identically.
- **Stability-axis vs body-axis distinction** — the user supplies the CORD2R; sbeam does not interpret it as stability vs body axes. The label "ROLL" means "rotation about the CORD2R local x-axis" regardless of physical interpretation.
- **Automatic reference-point computation** (e.g. "use the CG") — Phase 1 requires the user to declare the reference point explicitly. Auto-CG could be added in Phase 2 as `RBMREF, CG, MECH, 0.1, 6` if desired.
- **Constrained-RBM rebase** for partially-constrained models with `< 6` RBMs (e.g. a model on jacks with 3 SPCs leaving 3 rotational RBMs) — out of scope; the validation explicitly rejects this case.

---

## 3. Card Definition

### 3.1 `RBMREF`

| Field | 1 | 2 | 3 | 4 | 5 | 6–10 |
|---|---|---|---|---|---|---|
| Name | `RBMREF` | CID | NORM | TOL | NRBM | — |
| Type | str | int | str | float | int | — |
| Default | — | — | `MECH` | `0.1` | `6` | — |

| Field | Description |
|---|---|
| `CID` | Identifier of a `CORD2R` coordinate system. The CORD2R origin point is the reference point; its local x, y, z axes define the surge / sway / heave (translation) and roll / pitch / yaw (rotation) directions respectively. |
| `NORM` | Rigid-body-mode normalisation: `MECH` (default) returns the columns as unit translation / unit rotation about the reference point — generalised mass equals the effective rigid-body inertia at that point. `MASS` returns the Gram–Schmidt-M-orthonormalised columns (satisfying `Φᵀ M Φ = I`) while retaining the SURGE…YAW labels. |
| `TOL` | Frequency tolerance in Hz. Any returned mode with `f < TOL` is classified as a rigid-body mode and rebased. Default 0.1 Hz. |
| `NRBM` | Expected number of rigid-body modes (sanity check). Default 6. Raises `ValueError` if sbeam finds a different count below TOL. |

### 3.2 Validation rules

- At most one `RBMREF` card per model. A second occurrence raises `ValueError("Duplicate RBMREF; only one per model")`.
- `CID` must refer to a defined `CORD2R` card.
- `NORM` must be `MECH` or `MASS`. Any other value raises `ValueError`.
- `TOL > 0` and `NRBM > 0`. Zero or negative values raise `ValueError`.
- At solve time: if the number of modes with `f < TOL` is not `NRBM`, raise `ValueError("RBMREF expects {NRBM} rigid-body modes; found {N}. RBMREF requires a free-free model; check for spurious constraints, mechanisms, or an inconsistent TOL.")`.
- At solve time: if `Bᵀ K B` is not close to zero (norm > 1e-6 × ‖K‖), emit a `UserWarning` — indicates that the mechanical basis is leaking into the elastic stiffness, which is unusual for a well-formed free-free model.

### 3.3 Example — aircraft body axes at 25% MAC

```
$ Reference point: 4.20 m aft of fuselage station 0, on the symmetry plane,
$ aircraft body axes (+x aft, +y right, +z down).
$ CORD2R 500: origin at MAC/25, +z down, +x aft.
CORD2R, 500,  0,    4.20, 0.0, 0.0,    4.20, 0.0,-1.0
+,                    5.20, 0.0, 0.0

$ Rebase RBMs to body axes at MAC/25, mechanical normalisation,
$ classify modes below 0.1 Hz as rigid-body, expect 6 of them.
RBMREF, 500, MECH, 0.1, 6
```

After SOL 103 runs, the f06 reports:

```
                R I G I D   B O D Y   M O D E S
                (rebased to CID 500, NORM=MECH, REF=(4.200, 0.000, 0.000))

   MODE  LABEL    GEN. MASS       UNITS
      1  SURGE    7.450E+04       kg
      2  SWAY     7.450E+04       kg
      3  HEAVE    7.450E+04       kg
      4  ROLL     1.230E+05       kg·m²        (about CID 500 local x)
      5  PITCH    8.940E+05       kg·m²        (about CID 500 local y)
      6  YAW      9.870E+05       kg·m²        (about CID 500 local z)

                I N E R T I A   T E N S O R   A T   R E F E R E N C E
                CG offset from reference: (1.234E-01, 0.000E+00, 5.678E-02) m
                m·I3 + J at ref:
                [  1.230E+05    0.000E+00    -4.230E+03 ]
                [  0.000E+00    8.940E+05     0.000E+00 ]
                [ -4.230E+03    0.000E+00     9.870E+05 ]

                          R E A L   E I G E N V A L U E S
                          (elastic modes — RBMs reported above)
   MODE NO.   EIGENVALUE      RADIANS       CYCLES        GENERALIZED MASS
        7    ...
```

---

## 4. Mathematical Formulation

### 4.1 Mechanical basis construction

Let `R` be the 3×3 CORD2R-to-global rotation matrix (column 1 is the local x-axis expressed in global) and `P` be the CORD2R origin in global coordinates. For each grid `i` at global position `r_i`, define the lever arm in CORD2R-local coordinates:

```
ρ_i = Rᵀ · (r_i − P)     ≡ (ρ_x, ρ_y, ρ_z)
```

The six rigid-body basis columns of `B_target ∈ ℝ⁶ᴺ ˣ ⁶` are constructed grid-by-grid as 6-vectors `B_i^k` for grid `i` and basis index `k`:

| `k` | Label | Translation block `B_i^k[0:3]` | Rotation block `B_i^k[3:6]` |
|---|---|---|---|
| 1 | SURGE | `R · (1, 0, 0)ᵀ` | `(0, 0, 0)` |
| 2 | SWAY  | `R · (0, 1, 0)ᵀ` | `(0, 0, 0)` |
| 3 | HEAVE | `R · (0, 0, 1)ᵀ` | `(0, 0, 0)` |
| 4 | ROLL  | `R · ((1, 0, 0) × (ρ_x, ρ_y, ρ_z))ᵀ` = `R · (0, −ρ_z, +ρ_y)ᵀ` | `R · (1, 0, 0)ᵀ` |
| 5 | PITCH | `R · (0, 1, 0) × (ρ_x, ρ_y, ρ_z))ᵀ` = `R · (+ρ_z, 0, −ρ_x)ᵀ` | `R · (0, 1, 0)ᵀ` |
| 6 | YAW   | `R · ((0, 0, 1) × (ρ_x, ρ_y, ρ_z))ᵀ` = `R · (−ρ_y, +ρ_x, 0)ᵀ` | `R · (0, 0, 1)ᵀ` |

The full `B_target` is the column-wise stack of these vectors over all grids, in the same DOF ordering used by `assemble_global_mass` and `assemble_global_stiffness` (sorted GID order, 6 DOFs per grid).

### 4.2 Why `B_target` and `Φ_rbm` span the same subspace

`B_target` is the analytical basis for rigid-body motion of the structure: pure translation of the entire structure, and pure rotation of the entire structure about the reference point. Any rigid-body motion of a free-free structure must lie in the column space of `B_target`. Equivalently, `K · B_target = 0` exactly (a rigid-body motion produces zero strain in every element).

The eigensolver-returned `Φ_rbm ∈ ℝ⁶ᴺ ˣ ⁶` also spans the K-null space. Therefore both span the same 6-D subspace, and there exists an invertible 6×6 `C` such that `B_target = Φ_rbm · C`. The eigensolver's choice of basis within the subspace is what `C` records.

### 4.3 Mechanical normalisation (`NORM=MECH`)

Output:
```
Φ_rbm_aligned = B_target            (one column per labelled basis vector)
```

The columns are NOT M-orthonormal in general. Each column is a *mechanical* unit displacement — 1 m of surge, 1 rad of pitch about the reference point. Two useful properties result:

1. **Per-column generalised mass = effective inertia at the reference point.** The six values `(B_target^k)ᵀ M (B_target^k)` are, respectively:
   - SURGE, SWAY, HEAVE: total structural mass `m` (identical for all three).
   - ROLL, PITCH, YAW: rotational inertia about the corresponding CORD2R-local axis at the reference point, by the parallel-axis theorem.

2. **6×6 cross-coupling matrix** `B_targetᵀ M B_target` is the full rigid-body inertia tensor at the reference point — i.e. the GPWG output. Off-diagonal entries reveal CG offset from the reference point (the `m·skew(r_CG − P)` coupling block).

Both quantities are reported in the f06 header block.

Elastic modes are M-orthonormalised by `eigh` as usual and remain M-orthogonal to `B_target` (verified by the unchanged `Φᵀ_elastic M B_target ≈ 0`).

### 4.4 M-orthonormalisation (`NORM=MASS`)

Output:
```
Φ_rbm_aligned = B̃     where B̃ = B_target · L⁻ᵀ
```

with `L L^T = B_targetᵀ M B_target` the Cholesky factorisation of the 6×6 rigid-body inertia tensor.

Properties:
- `B̃ᵀ M B̃ = I` (M-orthonormal).
- Each column is still labelled SURGE…YAW.
- Each column has unit generalised mass — but the *displacement amplitude* of each column is no longer "1 m of surge" or "1 rad of pitch."

Use case: workflows that consume `Φᵀ M Φ = I` as a precondition (some modal-superposition codes assume this).

---

## 5. Implementation Plan

### 5.1 File touches

| File | Change |
|---|---|
| `sbeam/model/rbmref.py` | **New.** `@dataclass RbmRef(cid, norm="MECH", tol=0.1, nrbm=6)`. |
| `sbeam/model/bulk_data.py` | Add `rbmref: Optional[RbmRef] = None`. |
| `sbeam/parser/bdf_reader.py` | Add `_handle_rbmref`. Wire into the keyword dispatch. Reject duplicates. |
| `sbeam/solver/rbm_rebase.py` | **New.** `build_rbm_basis(bulk, grid_index, rbmref) → B_target`; `apply_rbm_rebase(freqs_hz, phi, eigenvalues, bulk, grid_index, rbmref, M_global) → (freqs_hz, phi, eigenvalues, rbm_metadata)`. |
| `sbeam/solver/sol103.py` | After eigensolve + full-DOF reconstruction, if `bulk.rbmref is not None`, call `apply_rbm_rebase`. The M_global the rebase needs is the full pre-reduction global mass; pass through. |
| `sbeam/results/results.py` | Extend `Sol103Result` with `rbm_metadata: Optional[RbmMetadata] = None`. New `@dataclass RbmMetadata(cid, norm, labels, gen_masses, inertia_tensor, cg_offset, ref_point_global)`. |
| `sbeam/results/f06_writer.py` | Insert the "R I G I D   B O D Y   M O D E S" block before the eigenvalue table when `result.rbm_metadata is not None`. |
| `sbeam/viewer/results_view.py` | Mode-selector labels for the first `NRBM` modes use SURGE/SWAY/HEAVE/ROLL/PITCH/YAW instead of "Mode 1, Mode 2, …" when `rbm_metadata` is present. |
| `docs/10_standard/01_beam_model.md` | Add RBMREF under bulk cards. |
| `docs/10_standard/02_card_reference.md` | Add the RBMREF field table. |
| `docs/10_standard/04_modal_analysis.md` | Add a "Rigid-body mode rebase" section describing the math and `NORM` options. |
| `README.md` | Add RBMREF to the "Supported BDF Cards" table. |
| `tests/parser/test_rbmref.py` | **New.** Card parse tests; defaults; duplicate rejection; invalid NORM. |
| `tests/solver/test_rbm_rebase.py` | **New.** Unit tests on `build_rbm_basis` — column shapes, label ordering, CORD2R rotation correctness. |
| `tests/integration/test_verification.py` | **Extend** with V27–V32 (see Section 6). |
| `tests/integration/bdf/v27_rbmref_identity.bdf` etc. | **New** BDF files for V27–V32. |
| `CHANGELOG.md` | `[Unreleased]` → `Added: RBMREF card (rigid-body mode rebase for free-free SOL 103)`. |
| `docs/30_future/00_backlog.md` | Mark the RBMREF step as complete; document the V27–V32 acceptance gates. |

### 5.2 Order of operations in `run_sol103`

```
1–6.  (existing assembly, RBE reduction, AMODE reduction, SPC partitioning)
7.    freqs_hz, phi_red = solve_modes(K_free, M_free, eigrl, force_dense=force_dense)
8.    full_phi = T @ phi_red  (existing — full-DOF reconstruction)

9.    NEW: if bulk.rbmref is not None:
         freqs_hz, full_phi, eigenvalues, rbm_metadata = apply_rbm_rebase(
             freqs_hz, full_phi, eigenvalues, bulk, grid_index, bulk.rbmref, M_global
         )
      else:
         rbm_metadata = None

10.   return Sol103Result(
          frequencies_hz=freqs_hz,
          mode_shapes=full_phi,
          eigenvalues=eigenvalues,
          amode_participations=amode_participations,  # from AMODE Phase 1
          rbm_metadata=rbm_metadata,                   # this card
      )
```

### 5.3 `apply_rbm_rebase` algorithm

```python
def apply_rbm_rebase(freqs_hz, phi, eigenvalues, bulk, grid_index, rbmref, M_global):
    # 1. Identify RBMs
    rbm_mask = freqs_hz < rbmref.tol
    n_found = int(rbm_mask.sum())
    if n_found != rbmref.nrbm:
        raise ValueError(
            f"RBMREF expects {rbmref.nrbm} rigid-body modes; found {n_found}. "
            "RBMREF requires a free-free model; check for spurious constraints, "
            "mechanisms, or an inconsistent TOL."
        )

    # 2. Build the target mechanical basis
    B_target = build_rbm_basis(bulk, grid_index, rbmref)   # (6N, NRBM)

    # 3. Sanity-check: K B_target ≈ 0 (warn, don't reject)
    # (skip in the hot path; available as a separate diagnostic)

    # 4. Apply NORM
    if rbmref.norm == "MECH":
        B_out = B_target
    elif rbmref.norm == "MASS":
        G = B_target.T @ M_global @ B_target               # (6, 6)
        L = scipy.linalg.cholesky(G, lower=True)
        B_out = B_target @ scipy.linalg.solve_triangular(L.T, np.eye(rbmref.nrbm), lower=False)

    # 5. Compute generalised masses
    gen_masses = np.diag(B_out.T @ M_global @ B_out)

    # 6. Compute inertia tensor and CG offset at reference point
    ref_point_global, R = get_transform(rbmref.cid, bulk.cord2rs)
    inertia_tensor = B_target.T @ M_global @ B_target      # 6x6, mechanical basis

    # 7. CG offset extraction (top-right 3x3 block ≡ m·skew(r_CG − P))
    cg_offset = _extract_cg_offset_from_inertia(inertia_tensor)

    # 8. Replace the first NRBM columns of phi (already sorted ascending by f) with B_out
    rbm_indices = np.where(rbm_mask)[0]
    phi_new = phi.copy()
    phi_new[:, rbm_indices] = B_out

    # 9. Zero the eigenvalues / frequencies for the rebased columns
    freqs_new = freqs_hz.copy()
    freqs_new[rbm_indices] = 0.0
    eigenvalues_new = eigenvalues.copy()
    eigenvalues_new[rbm_indices] = 0.0

    # 10. Build metadata
    metadata = RbmMetadata(
        cid=rbmref.cid,
        norm=rbmref.norm,
        labels=["SURGE", "SWAY", "HEAVE", "ROLL", "PITCH", "YAW"][:rbmref.nrbm],
        gen_masses=gen_masses,
        inertia_tensor=inertia_tensor,
        cg_offset=cg_offset,
        ref_point_global=ref_point_global,
    )

    return freqs_new, phi_new, eigenvalues_new, metadata
```

### 5.4 Backward compatibility

A model with no `RBMREF` card must behave bit-identically to the current solver. `bulk.rbmref is None` skips the entire rebase branch. The V1–V18 regression suite must continue to pass without modification.

### 5.5 Composition with AMODE

The two features compose cleanly:

- AMODE adds finite-frequency modes (control-surface rotation around `k > 0` stiffness). These are typically tens of Hz — far above the default `TOL = 0.1` Hz.
- RBMREF only touches modes below `TOL`. The rebase therefore does not touch any AMODE-generated mode.
- The augmented-DOF rows in `full_phi` (the `q` rows for each AMODE) are not part of `B_target` — `B_target` has zero in those rows by construction, because the SETID grid DOFs already capture the rotating-set kinematics. The AMODE q-rows pass through the rebase unchanged.
- f06 output: RBMs (labelled, mode 1–6) → AMODE participation table → elastic eigenvalue table starting at mode 7.

V32 (Section 6) is the cross-feature regression test.

---

## 6. Verification Cases

| ID | Model | Analytic target | Tolerance |
|---|---|---|---|
| **V27** | Free-free 5-element CBAR with CONM2s at each grid; `RBMREF` CID = identity at origin; `NORM=MECH`, `NRBM=6` | `gen_masses[0:3] == total_mass` exactly; `gen_masses[4]` (PITCH) equals the parallel-axis sum `Σ m_i · (x_i² + z_i²)` over all CONM2s, computed by hand in the test | < 1e-6 relative |
| **V28** | V27 model with `RBMREF` CID at offset `(1.0, 0.5, 0.0)` | PITCH and ROLL generalised masses match the parallel-axis-shifted inertia at the offset reference point | < 1e-6 relative |
| **V29** | V27 model with `RBMREF` CID rotated 30° about global Z | RBM labels still SURGE/SWAY/HEAVE/ROLL/PITCH/YAW; the columns lie along the CID-local axes, not global; `inertia_tensor` matches the rotated frame to floating-point precision | < 1e-10 absolute |
| **V30** | Constrained cantilever (1 SPC at root, no other modifications) with RBMREF declared | `parse_bdf` succeeds; `run_sol103` raises `ValueError` with the message "RBMREF expects 6 rigid-body modes; found 0" | exact-match assertion |
| **V31** | V27 model but `NORM=MASS` | `Φᵀ_rbm M Φ_rbm == I` for the first 6 columns to 1e-10; labels still SURGE/SWAY/…/YAW | < 1e-10 absolute on the 6×6 identity |
| **V32** | V27 model + AMODE control-surface (one rotation mode at ~5 Hz, k tuned to put it above `TOL`) | Modes 1–6 are the rebased RBMs unchanged from V27; mode 7 is the AMODE rotation mode with finite frequency; mode 8+ are elastic modes | mode-wise comparison against V27 + a standalone AMODE solve |

V27 is the load-bearing analytical test — the parallel-axis sum is unambiguous and computed in the test from the CONM2 distribution.

V29 catches every error class in the CORD2R-to-global rotation, which is the dominant correctness risk.

V32 confirms composition with the AMODE feature.

### 6.1 Non-regression requirement

V1–V18 must pass identically after RBMREF is merged. A CI step running `pytest tests/integration/test_verification.py::TestV1*` through `TestV18*` independently on every PR is the gate.

---

## 7. Open Decisions

| # | Decision | Recommendation | Owner |
|---|---|---|---|
| 1 | Card name: `RBMREF` vs `PARAM, RBMREF` (3-line PARAM form) vs `RBMSET` | **`RBMREF` dedicated card** — cleaner validation surface than three parallel PARAM lines | Author |
| 2 | Default `NORM`: `MECH` vs `MASS` | **`MECH`** — mechanical interpretation of generalized mass is genuinely more useful for aero work; `MASS` is opt-in | Author |
| 3 | Default `TOL`: 0.1 Hz vs 1.0 Hz vs scaled by `nu = √(k/m)` of the lightest mode | **0.1 Hz** — well below the elastic-mode floor of typical aircraft models (lowest elastic typically > 1 Hz); user can override | Author |
| 4 | Behaviour when CORD2R `CID` is not pure-rotation (i.e., shifted origin with non-identity rotation) | Both shift and rotation are honoured. Translation columns SURGE/SWAY/HEAVE align with CID-local x/y/z; rotation columns ROLL/PITCH/YAW are rotations about the CID-local axes through the CID origin. | Author |
| 5 | Output of CG offset: in CORD2R-local frame vs global frame | **CORD2R-local frame** — consistent with the rest of the rebased output | Author |
| 6 | Validation on constrained models | **Reject with `ValueError`** at solve time, not parse time — the parser does not know whether the model will solve constrained or free-free without inspecting the case-control SPC selection | Author |
| 7 | Should `RBMREF` zero the eigenvalues of the rebased modes (force them to exactly 0)? | **Yes** — the numerical eigenvalue is typically `O(1e-6)` rad²/s² from numerical noise; zeroing makes the f06 output cleaner and prevents downstream tools from interpreting noise as a low-frequency elastic mode | Author |
| 8 | Reference point at the CG via a sentinel value | **Defer.** Phase 1 requires explicit CID. A future `RBMREF, CG, …` shorthand can be added once the CG-from-bulk computation is available as a solver utility | Author |

---

## 8. Risks & Effort

### 8.1 Effort

| Task | Effort | Risk |
|---|---|---|
| Card + parser + validation | 0.5 day | Trivial |
| `build_rbm_basis` (geometry → B_target) | 0.5 day | Low — pure geometry |
| `apply_rbm_rebase` (MECH and MASS variants) | 1 day | Low |
| f06 output formatting + viewer label hookup | 0.5 day | Trivial |
| V27–V32 verification BDFs and tests | 1 day | Low — analytic targets are unambiguous |
| Docs (Beam_model.md, card_definition.md, Modal_analysis.md, README) | 0.5 day | Trivial |
| **Total** | **~4 days** | **Low overall** |

### 8.2 Top correctness risks

1. **CORD2R origin vs rotation mix-up** — the lever-arm calculation uses both `Rᵀ (r − P)` (the position in CID-local coordinates) and `R · v_local` (axis vectors expressed in global). Easy to swap the transpose. V29 (rotated CID) is the targeted catch — pure shift (V28) won't detect a rotation transpose bug.
2. **DOF ordering mismatch** — `B_target` must use the same `grid_index` (sorted-GID-order, 6 DOFs per grid) as the mass-matrix assembly. Take the sorted GID order from `build_grid_index` directly; do not regenerate.
3. **Mode-ordering after rebase** — `freqs_hz` is sorted ascending by `eigh`. The rebased columns are the first NRBM by construction. Verify in V32 that adding an AMODE doesn't disturb the rebase column indices.
4. **Cholesky on a singular `Bᵀ M B`** — happens if the user declares NRBM > 6 (mathematically impossible in 3D), or if two CONM2-only grids coincide in mass. Default NRBM=6 with the explicit check at step 1 of the algorithm prevents this in practice.
5. **AMODE q-row handling** — `B_target` has zero at the AMODE q-rows (because q is not a grid DOF). The rebase replaces only the SETID grid rows' rigid-body content; the q-rows of the rigid-body modes remain at whatever value `eigh` produced. For modes at f < TOL this should be zero (q does not participate in pure RBM); a unit test in V32 asserts this.

---

## 9. References

- **NASTRAN equivalent forms:**
  - MSC.Nastran Quick Reference Guide — `PARAM, GRDPNT` (Grid Point Weight Generator), `SUPORT` (rigid-body DOF for dynamic reduction), `SUPORT1` (subcase-scoped variant).
  - MSC.Nastran User's Guide, "Real Eigenvalue Analysis" — discusses the basis-ambiguity of rigid-body eigenvectors.
- **Mechanics:**
  - Hodges, Pierce, *Introduction to Structural Dynamics and Aeroelasticity*, 2nd ed., §4.2 (rigid-body modes and the inertia tensor at an arbitrary reference point).
  - Thomson, *Theory of Vibration with Applications*, 5th ed., §6.3 (free-free systems and the rigid-body subspace).
- **Aero coupling:**
  - Rodden, Johnson, *MSC.Nastran Aeroelastic Analysis User's Guide*, §3 (mode-shape requirements for the doublet-lattice method; the rigid-body basis at the aero reference point).
  - Wright, Cooper, *Introduction to Aircraft Aeroelasticity and Loads*, 2nd ed., §13.4 (control-surface and rigid-body modes in flutter coupling).
- **In-project precedents:**
  - `sbeam/gpwg.py` — the existing GPWG implementation; the inertia-tensor computation in RBMREF reuses the same parallel-axis logic over the full mass distribution.
  - `assembly/coord_transform.py` — `get_transform(cid, cord2rs)` provides the `(P, R)` pair RBMREF needs to construct `B_target`.
  - `docs/10_standard/04_modal_analysis.md` — the SOL 103 documentation pattern this design follows.

---

## 10. Acceptance Criteria

- All V27–V32 pass with the stated tolerances.
- All V1–V18 pass unchanged (free-free V6 included — RBMREF is optional and does not alter behaviour when absent).
- A constrained model with RBMREF declared raises `ValueError` cleanly at solve time, never silently produces a wrong rebase.
- `pytest --cov` shows ≥ 90% coverage on `sbeam/solver/rbm_rebase.py` and ≥ 85% on the RBMREF branches of `sbeam/solver/sol103.py`.
- A `sample/sample_rbmref_aircraft.bdf` model exists demonstrating the card on a representative free-free vehicle stick model with documented generalised masses for SURGE/SWAY/HEAVE/ROLL/PITCH/YAW.
- `docs/10_standard/01_beam_model.md`, `docs/10_standard/02_card_reference.md`, `docs/10_standard/04_modal_analysis.md`, `README.md` ("Supported BDF Cards" table) all updated.
- `CHANGELOG.md` `[Unreleased]` lists `RBMREF` under `### Added`.
- A combined sample (`sample_rbmref_aircraft.bdf` extended with one AMODE control surface) demonstrates the V32 composition path end-to-end.
