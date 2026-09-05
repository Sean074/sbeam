# MATRIX / GAF EXPORT — Reduced-Model Export for External Flutter Solvers

**Status:** Design proposal — not yet implemented.
**Target release:** Phase 1 (K/M/DOF-map + modal export) and Phase 2 (per-Mach GAF) together as one release; Phase 3 (OP4 + Universal Files) deferrable.
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-06-11
**Related:** `docs/10_standard/05_aeroelastics.md` (Phase A architecture), `docs/20_theory/01_aeroelastics_theory.md` (Q_aa / GAF derivation), backlog defects AE1/AE4/AE5 (correctness of the exported aero).

This document is the design proposal for a matrix-export capability: the full global stiffness `K_gg` and mass `M_gg` with an explicit DOF map, the SOL 103 modal-reduced `K_hh`, `M_hh` and mode-shape matrix `Φ`, and a steady (k = 0) generalized aerodynamic force matrix `Q_hh(M)` per Mach number including the Prandtl–Glauert and WKK/WT2 corrections. The motivating use case is handing a reduced flutter-ready model (`M_hh`, `K_hh`, `Q_hh` per Mach) to external solvers — primarily **FLAPS** (Flutter Analysis Programs, Meyer), and secondarily ZAERO/NASTRAN-adjacent tools via OUTPUT4.

---

## 1. Motivation

### 1.1 The engineering problem

sbeam's Phase A produces a validated structural model (SOL 103) and a corrected steady VLM aero model (SOL 144). Downstream work — flutter, parameter studies, controls coupling — lives in dedicated tools. The natural exchange currency between such tools is the **modal-reduced matrix set**: a small (n_m × n_m) mass, stiffness, and aerodynamic matrix triple on a common mode basis. Today sbeam computes every one of these matrices internally and throws them away:

| Matrix | Where it already exists | Fate today |
|---|---|---|
| `K_gg`, `M_gg` (g-set, sparse CSR) | `assembly/stiffness.py::assemble_global_stiffness`, `assembly/mass_matrix.py::assemble_global_mass` | consumed internally, never written |
| `K_aa`, `M_aa` (a-set) | built inside `run_sol103` / `sol144._build_qaa_aset` via `build_rbe3_transformation` + `apply_spcs` | discarded after the solve |
| `Φ` (a-set eigenvectors) | `sol103.solve_modes` → `phi_free` | expanded to g-set for the f06, a-set version discarded |
| `Q_aa` (aero stiffness, g/a-set) | `aero/coupling.py::build_qaa`, reduced in `sol144._build_qaa_aset` | held in `Sol144Result.q_aa`, never written |
| `Q_hh = Φᵀ Q_aa Φ` | `aero/coupling.py::build_gaf` (Step 50 ROM path) | held in `Sol144Result.q_hh`, never written |

The missing piece is not computation — it is (a) a way to *request* these matrices, (b) a **per-Mach loop** so `Q_hh` comes out at each Mach of interest on a *fixed* mode basis, and (c) **file writers** in formats the target solver imports natively.

### 1.2 The FLAPS target (Flaps Users' Manual v2.3.4)

FLAPS solves the frequency-domain flutter equation in generalized coordinates (manual Eq. 2.2.5):

```
[ s²M + sΩG + sV + (1 + i d)K − q·A(s̄, M) + T ] y = 0      ∈ ℂⁿᵉ
```

Three facts from the manual drive this design:

1. **Import formats (§8.8 `import`):** NASTRAN OUTPUT4 ASCII (`.op4`), uncompressed MATLAB MAT-file (`.mat`), Matrix Market ASCII (`.mm`), and SDRC Universal Files (`.uf`, datasets 15/55/82 — visualization only). Matrix Market is the lowest-friction target: `scipy.io.mmwrite`/`mmread` are already in sbeam's stack, the format is human-readable, and FLAPS uses it natively for its own matrix display.
2. **Mach handling (§6.4 Matrix Parameterizations, `pz` command §8.12):** FLAPS does not want one Mach-baked matrix — it wants a *set* of `A` matrices computed at several values of reduced frequency / Mach, which `pz` interpolates in 1–3 independent variables during continuation. The deliverable is therefore **one `Q_hh` file per Mach** plus the Mach list, not a single matrix.
3. **Sign and units (Eq. 2.2.5, §4.4, Table 4.2):** aero enters as `−q·A`, exactly matching sbeam's SOL 144 governing equation `(K_aa − q·Q_aa)·u = f`, so **`A ≡ Q_hh` with no sign or scale fix-up**. FLAPS equation units are SI and *consistency is the user's responsibility* — identical to sbeam's units philosophy. The export manifest must record the unit system so the downstream user can apply FLAPS's `units` conversion if needed.

The modal-reduction workflow is explicitly the intended FLAPS use pattern: manual §9.2.3 (`reduction.fp`) reduces the 144-DOF Goland wing to 10 modes via `Φᵀ M Φ` / `Φᵀ K Φ` triple products and shows near-identical flutter answers; §6.4 recommends forming FE matrices externally, reducing them with `Φ`, and importing.

### 1.3 ZAERO / NASTRAN context

The per-Mach GAF generation loop is ZAERO's MKAEROZ pattern and NASTRAN's MKAERO1 pattern, restricted to k = 0 (steady). sbeam's correction chain (WKK diagonal, WT2 pressure-matching — `aero/corrections.py`; WT1 force-matching was removed by DEF-R7) is already ZAERO-style; what is missing for multi-Mach use is that correction data is physically **Mach-specific** (wind-tunnel or CFD targets are measured at a Mach), while sbeam's WKK/AECORR cards currently carry no Mach tag. OUTPUT4 is the lingua franca of that ecosystem, which motivates the Phase 3 `.op4` writer.

### 1.4 What this feature delivers

- `EXPORT` case-control request → a self-contained **export bundle** directory: matrices + DOF map + JSON manifest.
- Full g-set `K_gg`/`M_gg` (sparse) and reduced a-set `K_aa`/`M_aa` (dense) with a row-by-row **DOF map** (grid, component, coordinates, set membership).
- SOL 103: `Φ` on both the a-set and g-set, `K_hh = ΦᵀKΦ`, `M_hh = ΦᵀMΦ` computed by explicit triple product (valid for any EIGRL normalization).
- Per-Mach steady GAF: `Q_hh(M) = Φᵀ Q_aa(M) Φ` for every Mach on a new `MKAERO1` card, with Prandtl–Glauert/Göthert at each Mach and Mach-matched correction-card selection — **one fixed Φ basis across all Machs**.
- A documented, copy-paste FLAPS input fragment (`import` + `pz` Mach interpolation + `flut`) making the bundle turnkey.

### 1.5 Steady-only caveat (stated up front)

sbeam Phase A aero is **steady (k = 0) and real**. A k = 0-only `Q_hh` set supports divergence and static-aeroelastic / quasi-steady studies in FLAPS directly, and is the zero-frequency anchor of a future unsteady set — but production flutter answers need unsteady aerodynamics (sbeam Phase D / doublet-lattice). The `MKAERO1` card and the bundle layout are deliberately designed so that unsteady matrices (`QHH_M{mach}_K{k}.mm`, complex) slot in later without changing the export architecture: the Mach loop simply becomes a Mach × k loop and `mmwrite` already handles complex matrices.

---

## 2. Scope

### 2.1 Phase 1 — Full-matrix and modal export

- `EXPORT` case-control request parsed and dispatched from `main.py`.
- Writers for Matrix Market (primary) and uncompressed `.mat` (secondary; one `scipy.io.savemat` call).
- `K_gg`, `M_gg` (sparse), `K_aa`, `M_aa` (dense), `dofmap.csv`, `manifest.json`.
- SOL 103 retains `phi_free` / `free_dofs` / a-set matrices; exports `PHIA`, `PHIG`, `KHH`, `MHH` and the frequency list.

### 2.2 Phase 2 — Per-Mach GAF export

- New bulk card `MKAERO1` (NASTRAN-compatible field layout; Phase A restriction: reduced-frequency list must be `0.0` only).
- `build_aero_model(..., mach=...)` Mach override.
- Optional `MACH` field on `WKK` and `AECORR` cards; Mach-matched correction selection with documented fallback.
- GAF driver: one SOL 103 basis, loop Machs, write `QHH_M{mach}.mm` per Mach (and `QAA` on request).
- Shared a-set reduction helper refactored out of `sol144._build_qaa_aset` so the solver and the exporter use one code path.

### 2.3 Phase 3 — Interop extras (deferrable)

- ASCII OUTPUT4 (`.op4`) writer (~150 lines, no new dependency) for ZAERO/NASTRAN-adjacent tools.
- SDRC Universal File writer: dataset 15 (grids), 55 (per-mode displacement data), 82 (tracelines from CBAR connectivity) — enables FLAPS animated-mode visualization (`amviz`).

### 2.4 Out of scope

- **Unsteady GAFs (k ≠ 0)** — Phase D. The design leaves the slot (see §1.5) but implements nothing.
- **Matrix import** (DMIG-style) — export only.
- **Binary OP4** — ASCII OP4 only; every consumer of OP4 reads the ASCII form.
- **Per-subcase export variation** — `EXPORT` is a global (above-subcase) request; the model has one stiffness, one mass, one mode basis.
- **Damping matrices** (`G`, `V` in FLAPS Eq. 2.2.5) — sbeam SOL 103 is undamped; PBUSH B-fields are deferred to the dynamic solvers. The manifest records their absence.

---

## 3. Input Definition

### 3.1 Case control: `EXPORT`

A global case-control command (above subcase level, like `SOL`):

```
EXPORT(MM, DIR=export_out) = KGG, MGG, KAA, MAA, PHIA, PHIG, KHH, MHH, QHH, DOFMAP
```

| Token | Meaning |
|---|---|
| `MM` / `MAT` / `OP4` | Output format (Matrix Market default; OP4 is Phase 3). |
| `DIR=name` | Bundle directory, created next to the f06 (default `<jobname>_export/`). |
| `KGG, MGG` | g-set sparse stiffness / mass. |
| `KAA, MAA` | a-set dense stiffness / mass (after RBE reduction + SPC partition). |
| `PHIA, PHIG` | mode shapes on the a-set (n_a × n_m) / g-set (6N × n_m). Requires SOL 103 (or SOL 144 with a METHOD). |
| `KHH, MHH` | `ΦᵀKΦ`, `ΦᵀMΦ` (n_m × n_m). Requires SOL 103. |
| `QHH` | per-Mach GAF set (Phase 2). Requires CAERO1/SPLINE cards, a METHOD, and an `MKAERO1` card. |
| `QAA` | per-Mach a-set aero stiffness (optional, large; for users doing their own reduction). |
| `DOFMAP` | the DOF-map CSV (always written when any matrix is requested; the token exists for an explicit ask). |
| `ALL` | everything applicable to the current SOL. |

**Validation rules:**

- `PHIA/PHIG/KHH/MHH/QHH` without an EIGRL/METHOD in the deck → error naming the missing card.
- `QHH` without `MKAERO1` → error; without CAERO1/spline cards → error.
- Unknown token → error listing valid tokens (consistent with existing case-control parser behaviour).

### 3.2 Bulk card: `MKAERO1` (NASTRAN-compatible)

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Name | `MKAERO1` | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 |
| Cont. | `+` | K1 | K2 | K3 | K4 | K5 | K6 | K7 | K8 |

`M1–M8`: Mach numbers (blank fields skipped). `K1–K8`: reduced frequencies. **Phase A restriction: every Kᵢ must be `0.0`** (or the continuation omitted, defaulting to `[0.0]`); any non-zero k is an error citing Phase D. Multiple `MKAERO1` cards accumulate, duplicates de-duplicated, Mach values must satisfy `0.0 ≤ M < 1.0` (consistent with the existing PG clamp in `aero_model.py`).

Adopting the standard NASTRAN card rather than inventing one (e.g. `MACHLIST`) costs nothing now and means decks are portable and Phase D needs no new card.

### 3.3 Mach-tagged corrections: `MACH` field on `WKK` / `AECORR`

Correction targets (wind-tunnel Cp distributions, strip forces) are valid at the Mach they were measured. Add one trailing field:

- `WKK, ID, CAERO_EID, MACH, ...data...` — `MACH` optional, default blank.
- `AECORR, ID, CAERO_EID, METHOD, MACH, ...target...` — same.

**Selection rule per loop Mach M** (replacing the current first-match-by-`caero_eid` in `build_aero_model`):

1. A correction card whose `MACH` matches M within `±0.001` → use it.
2. Else a card with blank `MACH` → use it at every Mach (current behaviour, preserved).
3. Else → no correction at this Mach; the manifest records `correction: none` for that Mach and a warning is printed (silently mixing corrected and uncorrected Machs in one interpolated set is exactly the kind of thing a downstream flutter engineer must be told about).

Backward compatible: existing decks have blank `MACH` and behave identically.

---

## 4. Mathematical Formulation

### 4.1 Matrix sets and the DOF map

sbeam's sets (terminology per `05_aeroelastics.md`):

| Set | Definition | Size | Where built |
|---|---|---|---|
| **g-set** | all grids × 6, grids in ascending sorted-ID order, DOFs `[6i … 6i+5]` = `[Tx Ty Tz Rx Ry Rz]` | 6N | `node_dofs` / `grid_index` |
| **red-set** | g-set after RBE2/RBE3/RBAR elimination `T` | n_red | `build_rbe3_transformation` |
| **a-set** | red-set after SPC partition (free DOFs) | n_a | `get_spc_dofs` + `apply_spcs` |
| **h-set** | modal coordinates | n_m | `solve_modes` |

This ordering is currently *implicit*. The export materialises it as `dofmap.csv`, one row per g-set DOF:

```
g_row, grid_id, component, x, y, z, cd, is_spc, is_rbe_dep, a_row
```

`component` ∈ 1–6 (NASTRAN convention), `cd` the grid's output CID, `is_spc` true if the DOF is in the SPC set (including GRID PS), `is_rbe_dep` true if eliminated by RBE2/RBE3/RBAR, `a_row` the row index in `K_aa`/`M_aa`/`PHIA` (−1 if not in the a-set). This single file makes every exported matrix self-describing.

### 4.2 Modal matrices

With `Φ_a` the (n_a × n_m) a-set eigenvector matrix from `solve_modes`:

```
K_hh = Φ_aᵀ K_aa Φ_a          M_hh = Φ_aᵀ M_aa Φ_a
```

computed by **explicit triple product**, not assumed equal to `diag(ω²)` / `I`. Reasons: (a) `EIGRL NORM=MAX` rescaling breaks the identity-mass assumption; (b) the off-diagonal residual of the computed `M_hh` is a free numerical health check (asserted < 1e−8 relative in tests, recorded in the manifest); (c) the same code path is reused for any future non-eigen basis (AMODE Ritz vectors, residual vectors). With `NORM=MASS` (recommended and recorded in the manifest), `M_hh ≈ I` and `K_hh ≈ diag(ω_i²)` to round-off.

`PHIG` is the existing g-set expansion from `run_sol103` (`full_phi = T @ phi_red`, SPC'd DOFs zero) — already computed for the f06, exported as-is.

### 4.3 Per-Mach GAF

For each Mach M in the `MKAERO1` list:

```
1. aero(M)   = build_aero_model(bulk, parity, grid_index, mach=M)
                 # PG box compression + 1/β Göthert scaling at M,
                 # Mach-matched correction card per §3.3
2. Q_aa(M)   = g_dispᵀ · Skj · AJJ*⁻¹(M) · Djk · g_slope        (existing build_qaa)
3. Q̃_aa(M)  = a-set reduction of Q_aa(M)                        (shared helper, §6.2)
4. Q_hh(M)   = Φ_aᵀ · Q̃_aa(M) · Φ_a                             (existing build_gaf)
```

**Basis-consistency rule (load-bearing):** SOL 103 is solved exactly **once**; the identical `Φ_a` projects `K_hh`, `M_hh`, and every `Q_hh(M)`. The Mach loop must never re-solve or re-normalise the modes — a per-Mach re-solve could reorder or re-sign eigenvectors and silently corrupt the interpolated set.

### 4.4 Conventions for the consumer (recorded in the manifest)

- **Sign:** sbeam solves `(K_aa − q·Q_aa)u = q·f_g + f_struct`; FLAPS Eq. 2.2.5 carries `−q·A(s̄,M)`. Hence `A ≡ Q_hh` exported as-is, premultiplied by dynamic pressure `q = ρV²/2` by the consumer. `Q_hh` is real and in general **non-symmetric** (aero stiffness is non-self-adjoint) — writers must not assume symmetry.
- **Units:** every matrix is in the deck's consistent unit system. The dimensional bookkeeping is automatic: `K_hh` and `q·Q_hh` are projected by the same `Φ` from g-set quantities that already satisfy `[K·u] = [q·Q_aa·u] = force`, so the pair lands in FLAPS Table 4.2's convention by construction. The manifest carries a free-text `units` field (e.g. `"SI (N, m, kg, s)"`) supplied by a `UNITS=` token on the EXPORT command or defaulted to `"unspecified — consistent set assumed"`.
- **Rigid-body modes:** a free-free basis makes `K_hh` singular (ω ≈ 0 rows). This is legitimate input for FLAPS; the export must **not** filter modes silently — mode selection is the EIGRL card's job. The manifest lists every modal frequency so the consumer sees the RBM content at a glance.
- **Parity:** half-models (`parity = ±1`) produce symmetric- or antisymmetric-only GAFs; recorded in the manifest, since a downstream flutter analysis needs both sets run separately.

### 4.5 Bundle layout

```
<jobname>_export/
├── manifest.json          # units, sets sizes, machs, frequencies, normalization,
│                          #   correction per Mach, parity, sign convention note,
│                          #   M_hh off-diagonal residual, sbeam version, source BDF
├── dofmap.csv
├── KGG.mm  MGG.mm         # sparse coordinate MM
├── KAA.mm  MAA.mm         # dense array MM
├── PHIA.mm PHIG.mm
├── KHH.mm  MHH.mm
├── QHH_M0.000.mm          # one per MKAERO1 Mach, fixed-width Mach in name
├── QHH_M0.600.mm
└── flaps_example.fp       # generated, ready-to-edit FLAPS input fragment (§8)
```

---

## 5. File Formats

| Format | Writer | Notes |
|---|---|---|
| Matrix Market `.mm` (primary) | `scipy.io.mmwrite` | sparse `coordinate` for KGG/MGG, dense `array` for the rest; `comment=` field carries matrix name, set, shape, units string. Zero new dependencies. |
| MATLAB `.mat` (secondary) | `scipy.io.savemat(..., do_compression=False)` | single `bundle.mat` holding every requested matrix under its export name — FLAPS §8.8 requires *uncompressed* MAT, which is scipy's default. One call, near-zero cost. |
| OUTPUT4 `.op4` (Phase 3) | new ~150-line ASCII writer in `matrix_export.py` | dense and BIGMAT-free sparse ASCII per the NASTRAN OUTPUT4 spec; covers FLAPS, ZAERO and NASTRAN ingestion. |
| Universal `.uf` (Phase 3) | new writer | datasets 15/55/82 only (the subset FLAPS reads, manual §10.11.2); mode-shape data from `PHIG`, tracelines from CBAR/PLOTEL connectivity. Visualization only — carries no analysis data. |

`manifest.json` is always written. It is the contract document: a consumer must be able to reconstruct the meaning of every file from the manifest plus `dofmap.csv` alone, with no access to the BDF.

---

## 6. Implementation Plan

### 6.1 File touches

| File | Change |
|---|---|
| `sbeam/results/matrix_export.py` | **New.** `ExportRequest` dataclass (tokens, format, dir, units); `write_bundle(...)`; MM/MAT writers; `build_dofmap(bulk, grid_index, spc_dofs, dep_dofs, free_dofs)`; manifest assembly; (Phase 3) OP4 + UF writers. |
| `sbeam/parser/case_control.py` | Parse `EXPORT(...) = ...` into `CaseControl.export: Optional[ExportRequest]`. Global command, not per-subcase. |
| `sbeam/model/aero.py` | **New dataclass** `Mkaero1(machs, ks)`. Add optional `mach` field to `Wkk` and `Aecorr`. |
| `sbeam/parser/bdf_reader.py` | `_handle_mkaero1` (continuation pattern as SPC1); extend WKK/AECORR handlers by one optional field. |
| `sbeam/model/bulk_data.py` | Add `mkaero1s` accumulator. |
| `sbeam/aero/aero_model.py` | `build_aero_model(..., mach: Optional[float] = None)` — override of the current hardwired `bulk.aeros.mach` (line 77); correction-card selection per §3.3 (currently first-match-by-EID at lines 87–89). |
| `sbeam/assembly/reduction.py` | **DONE — landed with Step 59 (2026-07-06).** `reduce_to_aset(bulk, grid_index, spc_sid) → AsetReduction` (dataclass with `reduce_matrix`/`reduce_rect`/`reduce_vector`/`expand_to_g`) extracted from `sol144._build_qaa_aset`; SOL 103/144 and `maneuver_qs` all re-pointed, bit-identical-verified. This design **reuses** it — no extraction work remains. |
| `sbeam/solver/sol103.py` | **DONE — landed with Step 59 (2026-07-06).** `Sol103Result` carries `phi_free`, `free_dofs`, `K_free`, `M_free` (optional fields, default `None`), always populated by `run_sol103` from values already in hand. |
| `sbeam/results/results.py` | Extend `Sol103Result` per above. |
| `sbeam/solver/gaf_export.py` (or a function in `matrix_export.py`) | **New.** The Phase 2 driver: run SOL 103 once → loop `MKAERO1` Machs → `build_aero_model(mach=M)` → `build_qaa` → `reduce_to_aset` → `build_gaf` → write. |
| `sbeam/main.py` | After the SOL dispatch, if `cc.export` is set, call `write_bundle` with whatever the solution produced; the QHH token routes through the GAF driver. |
| `docs/10_standard/02_card_reference.md` | MKAERO1 field table; MACH field on WKK/AECORR; EXPORT case-control entry. |
| `docs/10_standard/04_modal_analysis.md` | K_hh/M_hh export section (triple product, normalization). |
| `docs/10_standard/05_aeroelastics.md` | GAF export section: pipeline, basis-consistency rule, FLAPS handoff. |
| `docs/20_theory/01_aeroelastics_theory.md` | Short section mapping sbeam Q_hh to the FLAPS flutter equation (sign/units, §4.4 above). |
| `tests/results/test_matrix_export.py` | **New.** X1–X4 (round-trip, dofmap, formats, manifest). |
| `tests/solver/test_modal_export.py` | **New.** X5–X6. |
| `tests/aero/test_gaf_export.py` | **New.** X7–X10. |
| `sample/sample_gaf_export.bdf` | **New.** Cantilever wing + CAERO1 + SPLINE2 + EIGRL + MKAERO1 (3 Machs) + EXPORT ALL. |
| `CHANGELOG.md` | `[Unreleased]` → `Added: EXPORT case-control request, MKAERO1 card, K/M/Φ/GAF matrix export bundle`. |
| `docs/30_future/00_backlog.md` | On promotion: add as formal steps (next free numbers, currently 58+) per the backlog's step format; remove once delivered per the step-completion rule. |

### 6.2 Order of operations (Phase 2 driver)

```
 1. parse BDF; validate EXPORT tokens against SOL and deck content (§3.1 rules)
 2. K_gg = assemble_global_stiffness(bulk);  M_gg = assemble_global_mass(bulk)
 3. T, dep_dofs, red_dofs = build_rbe3_transformation(...)
 4. spc_dofs / free_dofs;  K_aa, M_aa via reduce_to_aset
 5. dofmap = build_dofmap(...)                                   ← Phase 1 stops here for KGG/MGG/KAA/MAA
 6. ω, Φ_a = solve_modes(K_aa, M_aa, eigrl)        (once, never repeated)
 7. K_hh = Φ_aᵀ K_aa Φ_a;  M_hh = Φ_aᵀ M_aa Φ_a;  assert ‖offdiag(M_hh)‖ small → manifest
 8. for M in sorted(set(mkaero1 machs)):
       aero = build_aero_model(bulk, parity, grid_index, mach=M)   # PG + Mach-matched correction
       Q_aa = build_qaa(aero, aero.g_disp, aero.g_slope)
       Q̃_aa = reduce_to_aset(Q_aa, ...)                            # same T/free_dofs as step 4
       Q_hh = build_gaf(Q̃_aa, Φ_a)
       write QHH_M{M:.3f}.mm  (and QAA_M{M:.3f}.mm if requested)
 9. write manifest.json, flaps_example.fp
```

Steps 2–4 reuse the matrices the solution already assembled when possible (SOL 103 path) rather than re-assembling; re-assembly is the fallback when EXPORT is requested with SOL 101.

### 6.3 Backward compatibility

A deck with no `EXPORT` command must behave **bit-identically** to today: every change is additive (`mach=None` keeps the `bulk.aeros.mach` path; new optional card fields default to blank; `Sol103Result` extensions default `None`). The `_build_qaa_aset` → `reduce_to_aset` refactor is the only touch to an existing code path and is gated by the existing SOL 144 test suite passing unchanged.

---

## 7. Verification Cases

| ID | Case | Target | Tolerance |
|---|---|---|---|
| **X1** | Round-trip: cantilever BDF → export `KGG/MGG` → `scipy.io.mmread` → compare to freshly assembled matrices | exact (same floats through MM's 16-digit output) | ≤ 1e−15 relative |
| **X2** | DOF map: 6N rows; `is_spc` rows ≡ `get_spc_dofs` output; `a_row` permutation consistent with `apply_spcs` free-DOF indexing; RBE2 model marks dependent DOFs | exact set equality | exact |
| **X3** | Format parity: same model exported as `.mm` and `.mat`; reload both; matrices identical | ≤ 1e−15 | exact-ish |
| **X4** | Manifest: machs, frequencies, normalization, units string, correction-per-Mach record all present and correct for the sample deck | schema + value assertions | exact |
| **X5** | Modal identities (cantilever, `NORM=MASS`): `M_hh = I`, `K_hh = diag(ω²)` from the exported files; eigenvalues of `(K_hh, M_hh)` reproduce the f06 frequencies | ≤ 1e−8 relative |
| **X6** | `NORM=MAX` variant: `M_hh ≠ I`, but `eig(K_hh, M_hh)` still reproduces the same frequencies (normalization-invariance of the exported pair) | ≤ 1e−8 relative |
| **X7** | GAF cross-check vs Step 50 ROM: `Q_hh(M = bulk.aeros.mach)` from the export driver equals `Sol144Result.q_hh` from `run_aeroelastic_static(use_rom=True)` on the same deck | ≤ 1e−12 relative |
| **X8** | Prandtl–Glauert trend (planar unswept wing, no correction cards): `Q_hh(M) ≈ Q_hh(0)/β`, β = √(1−M²), at M = 0.3/0.6/0.8 | ≤ 1 % (PG is exact for the planar kernel scaling; tolerance covers the collocation-geometry compression) |
| **X9** | Closed-loop divergence: solve the eigenproblem `K_hh·v = q·Q_hh·v` from the *exported files only*; lowest real positive q vs sbeam's internal a-set divergence solve (Step 55 when available, else a direct `eig(K_aa, Q_aa)` reference computed in the test) | ≤ 0.5 % |
| **X10** | Negative cases: (a) `QHH` without MKAERO1; (b) MKAERO1 with k ≠ 0; (c) M ≥ 1.0; (d) `PHIA` without EIGRL; (e) Mach-tagged correction exists but no card matches a loop Mach → warning emitted + manifest records `none`; (f) unknown EXPORT token | `ValueError` with offending item named (a–d, f); warning text match (e) | exact-match assertion |

X7 is the load-bearing test — it proves the export path and the solver path produce the *same physics* through one shared reduction. X9 is the end-to-end proof that an external solver consuming only the bundle reproduces an sbeam answer. A manual (non-CI) companion check: run `flaps_example.fp` in an actual FLAPS installation against the sample deck and confirm the divergence q matches X9.

**Non-regression:** the full existing suite — V1–V18 integration, all 207 aero/integration tests, SOL 144 tests — must pass unchanged (only the `reduce_to_aset` refactor touches existing code).

---

## 8. FLAPS Handoff Example (generated `flaps_example.fp`)

```
# generated by sbeam — <jobname>, <date>, units: SI
# n_modes = 6, machs = (0.0, 0.3, 0.6)
import{i=KHH.mm}
import{i=MHH.mm}
import{i=QHH_M0.000.mm, o=QHH0}
import{i=QHH_M0.300.mm, o=QHH3}
import{i=QHH_M0.600.mm, o=QHH6}
# steady GAF: parameterize in mach (k=0 anchor; see manifest 'steady_only' note)
pz{i=(QHH0, QHH3, QHH6), o=QHH, mach=(0.0, 0.3, 0.6)}
# flutter / divergence run per Flaps manual §8.6 'flut' — user supplies
# vtas/alt ranges; gaf=QHH, mass=MHH, stif=KHH
```

(Exact `pz`/`flut` spec syntax to be finalised against the user's FLAPS version during implementation; the fragment is a starting point, flagged as such in its header comment.)

---

## 9. Open Decisions

| # | Decision | Recommendation | Owner |
|---|---|---|---|
| 1 | Trigger: case-control `EXPORT` vs CLI flag vs `PARAM` card | **Case control** — it travels with the deck, matches how every other output request works, and the viewer UI can expose it like DISPLACEMENT | Author |
| 2 | Primary format | **Matrix Market** — native to scipy and FLAPS, human-readable, complex-capable for Phase D | Author |
| 3 | One file per matrix vs single bundle file | **One `.mm` per matrix** + optional all-in-one `.mat`; per-matrix files match FLAPS's one-`import`-per-matrix model | Author |
| 4 | Φ export set | **Both** PHIA (analysis-consistent) and PHIG (visualization/spline-consistent); dofmap disambiguates rows | Author |
| 5 | New `MKAERO1` vs reusing `DIVERG.machs` | **MKAERO1** — DIVERG conflates a solution request with a Mach list; MKAERO1 is the standard NASTRAN separation and is Phase-D-ready | Author |
| 6 | Mach in filenames: `M0.600` fixed-width vs index `QHH_01` | **Fixed-width Mach value** — self-describing without the manifest; manifest still carries the authoritative list | Author |
| 7 | Default modal normalization for export | Recommend `NORM=MASS` in docs; export works under any EIGRL norm (X6) — never silently re-normalise | Author |
| 8 | `QAA` export (n_a × n_a per Mach, potentially large) | Opt-in token only, never part of `ALL` | Author |
| 9 | Units declaration | `UNITS="..."` free-text token on EXPORT → manifest; no conversion logic in sbeam (consistent-units philosophy) | Author |
| 10 | Where the GAF driver lives: inside SOL 144 vs standalone | **Standalone driver invoked from main.py** — GAF generation needs no TRIM/load case; requiring a SOL 144 subcase to export matrices would be artificial | Author |

---

## 10. Risks & Effort

### 10.1 Effort

| Task | Effort | Risk |
|---|---|---|
| Phase 1: export module, MM/MAT writers, dofmap, manifest | 1.5 days | Low — pure new code over existing data |
| Phase 1: case-control EXPORT parse + main.py dispatch | 0.5 day | Low |
| Phase 1: SOL 103 retention + K_hh/M_hh + X1–X6 | 1 day | Low |
| Phase 2: MKAERO1 card + parser + validation | 0.5 day | Trivial |
| Phase 2: `build_aero_model` mach override + Mach-tagged corrections | 1 day | Low–medium (correction-selection logic; X10e) |
| Phase 2: `reduce_to_aset` refactor + SOL 144 re-point | 1 day | **Medium — the only existing-path touch; gated by SOL 144 suite** |
| Phase 2: GAF driver + X7–X9 | 1.5 days | Low — composes existing functions |
| Docs (4 standard docs + theory + sample deck) | 1 day | Trivial |
| **Total Phases 1–2** | **~8 days** | **Low–medium overall** |
| Phase 3: OP4 writer + tests | 1.5 days | Medium — format fiddliness; validate by round-trip through pyNastran in a dev-only test |
| Phase 3: UF 15/55/82 writer | 1 day | Low |

### 10.2 Top correctness risks

1. **Exported GAFs inherit open Phase A defects.** **AE4** (SPLINE2 kinematics wrong on swept/offset configurations) sits inside `g_slope`/`g_disp`, which every `Q_hh` is built from. For straight-wing models the export is sound today; for swept configurations **AE4 should land first**, or the manifest must carry a prominent known-issue flag. (AE1 — missing trim feedback — does *not* affect this path: `Q_hh` is formed upstream of trim. AE5 is trim-only likewise.)
2. **Basis drift across the Mach loop.** Re-solving modes per Mach would silently reorder/re-sign eigenvectors and corrupt the interpolated set. The design rule (§4.3, one `solve_modes` call) must be enforced structurally — the driver takes `Φ_a` as an argument, and nothing inside the loop can reach the eigensolver.
3. **Set mismatch between Φ and Q_aa reduction.** `Q_hh` is only meaningful if `Q̃_aa` and `Φ_a` use the identical free-DOF ordering. Sharing `reduce_to_aset` (one `T`, one `free_dofs`, computed once in step 4) makes this true by construction; X7 is the regression trap.
4. **Units miscommunication downstream.** sbeam cannot detect inconsistent units; FLAPS will produce confidently wrong flutter speeds from a mixed-unit deck. Mitigation is documentation: the mandatory manifest `units` field plus a warning section in `05_aeroelastics.md`.
5. **MM dense-array column-major order.** Matrix Market `array` format is column-major; `scipy.io.mmwrite` handles it, but any hand-rolled writer (OP4, Phase 3) must be round-trip tested (X3-style) before trust.

---

## 11. References

- **FLAPS:** *Flaps Users' Manual* v2.3.4, E. E. Meyer — Eq. 2.2.5 (flutter equation), §4.4/Table 4.1–4.2 (units), §6.4 (matrix parameterizations), §8.3/§8.8 (`export`/`import` formats), §8.12 (`pz`), §9.2.3 (modal reduction example), §10.11.2 (Universal File datasets 15/55/82). Local copy: `~/Documents/Library/Software_Manuals/FLAPS_manual.pdf`.
- **ZAERO:** ZAERO 9.2 Theoretical Manual (AIC correction, GAF formation conventions); ZAERO 9.2 User's Manual (MKAEROZ per-Mach AIC generation pattern). sbeam's WKK/WT2 chain already follows these — see `docs/20_theory/01_aeroelastics_theory.md`.
- **NASTRAN:** MSC Nastran Quick Reference Guide — `MKAERO1` field layout, OUTPUT4 ASCII format; MSC Nastran Aeroelastic Analysis User's Guide — GAF / modal-reduction conventions.
- **Matrix Market format:** NIST, https://math.nist.gov/MatrixMarket/formats.html (`scipy.io.mmwrite`/`mmread`).
- **In-project precedents:** `aero/coupling.py::build_qaa/build_gaf` (the physics, already implemented); `solver/sol144.py::_build_qaa_aset` (the reduction to refactor); `assembly/rbe3.py` + `assembly/stiffness.py::apply_spcs` (set machinery); `tests/aero/test_step50_qaa.py` (ROM test anchor for X7).

---

## 12. Acceptance Criteria

### 12.1 Phases 1–2 (shipped together)

- X1–X10 pass with the stated tolerances.
- Full existing suite (V1–V18, aero/integration, SOL 144) passes unchanged; a deck without `EXPORT` is bit-identical to pre-feature output.
- `sample/sample_gaf_export.bdf` produces a complete bundle whose `manifest.json` validates and whose X9-style closed-loop divergence check is reproduced in a documented walkthrough in `05_aeroelastics.md`.
- `pytest --cov` ≥ 90 % on `sbeam/results/matrix_export.py` and the GAF driver.
- `docs/10_standard/02_card_reference.md`, `04_modal_analysis.md`, `05_aeroelastics.md`, `docs/20_theory/01_aeroelastics_theory.md`, `CHANGELOG.md` all updated; on promotion to active work, formal steps added to (and on completion removed from) `docs/30_future/00_backlog.md` per the step-completion rule.

### 12.2 Phase 3

- OP4 round-trip test (write → independent reader → compare) passes for dense and sparse cases.
- A UF bundle loads in FLAPS `viz`/`amviz` and animates a mode shape (manual verification, documented with a screenshot in `05_aeroelastics.md`).
