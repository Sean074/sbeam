# MATRIX REUSE STORE — Precompute / Save / Reload of K, M and Aerodynamic Matrices for Dual-Mode SOL 144

**Status:** Design proposal — not yet implemented.
**Target release:** Phase 0 (SOL 144 production dispatch + results writer — prerequisite) and Phases 1–3 (store, generation, dual-mode reload) as a sequence; Phase 4 (export-bundle convergence) deferrable.
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-06-13
**Related:** `docs/30_future/designs/matrix_gaf_export.md` (the OUTPUT4/export complement — **read it first**; this design is its INPUTT4/reload counterpart and shares its bundle, manifest, `MKAERO1` card, and `reduce_to_aset` refactor), `docs/10_standard/05_aeroelastics.md` (Phase A architecture), `docs/20_theory/01_aeroelastics_theory.md` (Q_aa / GAF derivation), backlog defect AE9 (multi-Mach `AeroCache` contract), AE4 (SPLINE2 kinematics — baked into the cached splines).

This document is the design proposal for an **internal matrix-reuse store**: the ability to run the aerodynamic AIC + corrections as an *independent* generation step that saves a reusable per-Mach aero kernel (the corrected influence inverse, integration and downwash operators, and spline operators); to likewise generate, save and reload the unconstrained structural stiffness `K_gg` and mass `M_gg`; and to make **SOL 144 dual-mode** — it still computes everything fresh the "standard NASTRAN way," but can optionally reload already-computed K, M and aerodynamic matrices from a store instead of rebuilding them. The motivating use case is the Part 25 trim/envelope sweep: a fixed structure and geometry trimmed across many dynamic pressures, Machs, and load cases, where the expensive `O(n_box²)` AIC build and the structural assembly are recomputed every run today and thrown away.

This is the **reload (INPUTT4 / RESTART) complement** of `matrix_gaf_export.md`, which designed the one-way **export (OUTPUT4)** of the same matrices to external flutter solvers (FLAPS/ZAERO). The two share one on-disk bundle: `matrix_gaf_export` writes `.mm`/OP4 for downstream tools; this design adds a numpy-native fast path (`.npz`) that round-trips back *into* sbeam, plus the dual-mode SOL 144 that consumes it.

---

## 1. Motivation

### 1.1 The engineering problem

sbeam recomputes, on every run, two expensive things that depend only on inputs that rarely change between runs in a sweep:

| Build | Cost | Depends on | Today |
|---|---|---|---|
| AIC assembly `build_ajj` (Biot–Savart horseshoe loop) | `O(n_box²)` | geometry + Mach | rebuilt every run, per Mach |
| Corrected inverse `ajj_inv_corr` (`np.linalg.solve` + correction + β + Cp scaling) | `O(n_box³)` solve | geometry + Mach + correction cards | rebuilt every run, per Mach |
| Structural assembly `assemble_global_stiffness` / `assemble_global_mass` | element loop, sparse | geometry + properties + materials | rebuilt every run |
| Spline operators `g_slope` / `g_disp` | spline blocks | geometry + structure (grid_index, spline cards) | rebuilt every run, **per Mach** (see §4.3 — a current `AeroCache` inefficiency) |

For a determined-trim envelope sweep — one structure, a handful of Machs, dozens of `(q, load-case)` points — none of these inputs change across the sweep, yet all are rebuilt for each point. A persistent store turns the second and subsequent runs into matrix *loads* plus the cheap live recombination.

### 1.2 What already exists (this is incremental, not greenfield)

- **`AeroCache`** (`sol144.py:38`) — a Mach-keyed *in-memory* memo of `AeroModel`s, keyed at `round(mach, 6)` (`_MACH_DP = 6`, `sol144.py:50`), seeded with a prebuilt model (`sol144.py:847`). The AE9 multi-Mach work made each AIC build once *per process*. This design makes that cache **persistent** across processes — its `get()` miss-handler is the single seam.
- **`build_aero_model(..., mach=M)`** (`aero_model.py:43`) — the per-Mach override already exists (AE9). Generation needs no new aero physics.
- **`matrix_gaf_export.md`** — the export/serialization machinery (bundle directory, `manifest.json`, fixed-width Mach filenames, the `MKAERO1` card, the `reduce_to_aset` refactor) is fully designed. This design **reuses** all of it and adds only the reload direction. It explicitly defers matrix *import* (its §2.4: "Matrix import (DMIG-style) — export only") — that deferred half is precisely this document.
- **A clean solve seam** — `_solve_trim_determined` (`sol144.py:512`) already takes `K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a` as explicit arguments, so the trim solver needs **no change** for dual-mode; only the two build seams above it do.

### 1.3 What this feature delivers

- A `MatrixStore` abstraction (`sbeam/io/matrix_store.py`) persisting the *exact* clean cache boundary (§4) to numpy-native `.npz` bundles with a content-hash provenance manifest.
- Two generation entry points: a **structural generator** (`KGG`/`MGG` + DOF/grid map) and an **aero generator** (per-Mach `AeroModel` members + the structure-keyed splines), both wrapping the existing builders unchanged.
- A **dual-mode SOL 144**: standard fresh-compute path unchanged and bit-identical; an opt-in reload path (`--reuse-matrices DIR` / `ASSIGN MATRIX=DIR`) that loads K, M and the aero kernel from the store, validates them against the live deck, and runs the identical reduction + trim solve.
- One on-disk bundle shared with `matrix_gaf_export`: `.npz` for internal reload, `.mm`/OP4 for external handoff.

### 1.4 The prerequisite, stated up front (Phase 0)

`main.py` dispatches **only SOL 101 and SOL 103** (`main.py:31–40`; `SOL {cc.sol} is not supported` for 144), and **no `Sol144TrimResult` `.f06`/text writer exists**. Today SOL 144 runs *only* through test harnesses calling `run_sol144_trim` directly; the "one shared `AeroCache` across the subcase loop" multi-Mach contract lives only in `test_ae9_mach.py`. Therefore **"dual-mode SOL 144" depends on first building the SOL 144 production path** — CLI/viewer dispatch with a shared cache across subcases, plus a results writer. This is Phase 0 and is the bulk of the integration effort; the caching seam itself is small. Phases 1–2 ship test-gated value independently of Phase 0.

---

## 2. Scope

### 2.1 Phase 0 — SOL 144 production path (prerequisite, not caching)

- `cc.sol == 144` dispatch branch in `main.py` and `viewer/app.py`, looping subcases with **one shared `AeroCache`** (the AE9 contract, currently test-only).
- A `Sol144TrimResult` `.f06`/text writer in `sbeam/results/f06_writer.py` (none exists today).
- No reuse yet — fresh path only, behaviourally identical to the test path.

### 2.2 Phase 1 — `MatrixStore` + structural generation

- `sbeam/io/matrix_store.py`: `MatrixStore` with `save_struct`/`load_struct`, the content-hash helpers, `manifest.json` read/write, `StaleMatrixError`.
- Structural generator: `assemble_global_stiffness` / `assemble_global_mass` once → `KGG.npz`/`MGG.npz` (sparse, **unconstrained**) + `gridmap.json` + `dofmap.csv`.
- Default-off; `store=None` path bit-identical to today.

### 2.3 Phase 2 — Per-Mach aero generation

- `MKAERO1` card + parser (shared with `matrix_gaf_export` §3.2; Phase A restriction `k = 0.0`).
- Aero generator: loop the Mach list calling `build_aero_model(mach=M)`; persist each `AeroModel`'s **members** (`ajj_inv_corr, skj, djk, wg, boxes`) under `aero_M{mach}.npz`, and the **structure-keyed** `g_slope`/`g_disp` in a *separate* `splines.npz`.
- The `reduce_to_aset` refactor (extracted from `sol144._build_qaa_aset`), shared with `matrix_gaf_export`.

### 2.4 Phase 3 — Dual-mode SOL 144 reload

- `DiskAeroCache(AeroCache)` overriding only the miss-handler (deserialize-or-build-then-save).
- `--reuse-matrices DIR` CLI flag (and/or `ASSIGN MATRIX=DIR` executive directive); `--save-matrices DIR` write-through.
- Full reload validation (§6); cached-vs-fresh trim **bit-identical** on a clean store; q-sweep reuses one stored set.

### 2.5 Phase 4 — Export-bundle convergence (deferrable)

- Converge the reuse bundle layout with `matrix_gaf_export`'s `<job>_export` bundle: shared manifest schema, shared fixed-width Mach filenames, `.mm`/OP4 emitted as interchange siblings of the `.npz` artifacts, so one store serves both internal reload and external FLAPS/ZAERO handoff.

### 2.6 Out of scope

- **Caching reduced or fused products** — `K_aa`/`M_aa`/`Q_aa`/`Q_hh` (SPC/RBE-reduced), `K_eff`/`C_ax`/Schur products (q-fused), and any LU factorization. See §4; these are always recomputed live.
- **Unsteady GAFs (k ≠ 0)** — Phase D. The `(Mach, k)` key slot is reserved (§5) but nothing is implemented.
- **Cross-version matrix portability** — a stored bundle is valid for the recording scipy/numpy/sbeam versions; a version bump invalidates it (regenerate). The manifest detects, not bridges, the mismatch.
- **Pickle / HDF5 / OP2** — `.npz` + JSON manifest only for reuse; `.mm`/OP4 only via the `matrix_gaf_export` export path.

---

## 3. Input Definition

### 3.1 Generation: CLI subcommands

```
sbeam generate-matrices <deck.bdf> [--dir DIR] [--mach M1,M2,...]
```

Parses the deck, runs the structural and aero generators, writes the bundle. The Mach list defaults to `AEROS.mach` plus any `MKAERO1` Machs; `--mach` overrides. SOL number stays implicit/144 — this is an I/O step, the NASTRAN "generate-and-store cold run."

A write-through alternative generates the store **as a side effect** of a normal SOL 144 run:

```
sbeam <deck.bdf> --save-matrices DIR
```

### 3.2 Reuse: CLI flag and/or executive directive

```
sbeam <deck.bdf> --reuse-matrices DIR
```

When set, SOL 144 reloads from `DIR` instead of rebuilding (subject to the validation in §6). Absent the flag, SOL 144 computes everything fresh — the standard NASTRAN way, byte-identical to today.

**Optional deck-portable form** (Phase 4): an executive `ASSIGN MATRIX=DIR` directive parsed in `case_control.py`, mirroring NASTRAN `ASSIGN` + `DBLOCATE`/`RESTART`, so the reuse intent travels with the deck rather than the command line. Recommendation in §10.

### 3.3 `MKAERO1` card (shared with `matrix_gaf_export` §3.2)

No new card is invented here. The per-Mach generation loop reads the same NASTRAN-compatible `MKAERO1` card the export design defines (Phase A restriction: every reduced frequency `Kᵢ` must be `0.0`). Mach values are stored and keyed at `round(M, 6)` to match `AeroCache._MACH_DP`.

---

## 4. Architecture — the cache boundary

The load-bearing design decision. There are **two independent dependency axes**, and the store must key each artifact on the right one. Caching across the wrong axis either over-invalidates (needless rebuilds) or — far worse — silently serves a wrong matrix.

### 4.1 What to cache, and on which key

| Artifact | Where built | Depends on Mach? | Depends on structure? | Cache key |
|---|---|---|---|---|
| `ajj_inv_corr` (corrected AIC⁻¹, ΔCp-units) | `aero_model.py:124–147` | **yes** (β baked at `:136–137`) | no | (geometry, Mach@6dp, **correction**) |
| `skj` (force integration) | `integration.py:13` | no (geometry) | no | (geometry, Mach group) |
| `djk` (downwash, = −I at k=0) | `integration.py:28` | no (count) | no | (geometry, Mach group) — reserved `(Mach,k)` slot |
| `wg` (W2GJ camber/twist baseline) | `integration.py:41` | no (geometry + W2GJ data) | no | (geometry, Mach group) |
| `boxes` (AeroBox geometry, **physical**) | `aero_model.py` mesh | no | no | (geometry, Mach group) |
| `g_slope`, `g_disp` (spline operators) | `spline.py` (`build_g_spline`) | **NO** | **yes** (grid_index + spline cards) | (geometry, **structure**) — *separate file* |
| `KGG`, `MGG` (unconstrained sparse) | `stiffness.py:165`, `mass_matrix.py:84` | no | yes | (structure) |

### 4.2 What to NEVER cache

Everything below the dynamic-pressure fusion and the subcase-dependent reduction stays **live** at solve time:

- `Q_aa = g_dispᵀ · skj · ajj_inv_corr · djk · g_slope` (`build_qaa`, `coupling.py:54`), `Q_ax`, `Q_hh` (`build_gaf`, `coupling.py:105`) — recombination of cached members; caching them **re-entangles** the Mach and structural axes and duplicates q-independent data.
- `f_g` (`build_fg`, `coupling.py:78`) and `D_jx` (`build_djx`, `integration.py:65`) — cheap; recompute live.
- `K_eff = K_aa − q·Q_aa` (`sol144.py:164/240/541`) and `C_ax = q·Q_ax_a + M_ax_a` (`sol144.py:546–549`) — **q-fused**; caching them freezes one dynamic pressure and breaks the entire q-sweep, which is the primary use case.
- `K_aa`/`M_aa`/`Q_aa` (SPC/RBE3-reduced) — **subcase-dependent**; the RBE3 transformation, SPC partition and SUPORT partition (`get_spc_dofs`/`apply_spcs`) run per subcase and must stay live.
- LU factorizations (`k_aa_lu` on the Step-50 path, `K_ll_lu` in `sol144_trim_solve.py`; the per-trim `Sol144TrimResult.k_aa_lu` was deleted as dead by P13/DEF-R2) — cross-scipy-version landmine; store raw matrices, re-factor on load.

**The rule:** *cache only the pre-q, pre-reduction operands.* One stored set then serves an arbitrary q-sweep **and** any SPC/AESTAT/AESURF label set with zero rebuild.

### 4.3 The two-axis split (why splines get their own file)

`g_slope`/`g_disp` are **Mach-independent but structure-dependent** — the opposite axis from the AIC. The current in-memory `AeroModel`/`AeroCache` stores them *inside* the Mach-keyed model, which means a multi-Mach sweep rebuilds the splines on every Mach miss (wasteful) and carries no structural key (unsafe if reused naïvely). The store **must** put `g_slope`/`g_disp` in a separate `splines.npz` keyed on `(geometry, structure)`, referenced by every Mach group. A Mach sweep then reuses the splines once; a structural edit invalidates the splines (and `KGG`/`MGG`) while the AICs remain valid.

### 4.4 Mapping to the requested NASTRAN concepts

| Request | sbeam realization | NASTRAN analog |
|---|---|---|
| AIC + **Mach** correction, run independently | `build_aero_model(mach=M)` → PG/Göthert β baked into `ajj_inv_corr` (`aero_model.py:108,136`) | per-Mach AIC generation (MKAERO1) |
| + **pressure / WKK** correction | `apply_wkk` / WT2 folded into `ajj_inv_corr` (`aero_model.py:122–127`) | WKK / WTFACT |
| + **section** correction | **W2GJ → `wg`** — note this is an *additive RHS* in `build_fg`, **not** a factor of the GAF; persisted as a first-class vector or it silently drops camber/twist | W2GJ DMI |
| "save GAFs that could be reloaded" | persist the per-Mach `AeroModel` members + shared splines | OUTPUT4 of aero matrices / EXTSEOUT |
| generate & save **K, M** | save unconstrained sparse `KGG`/`MGG` + grid map | OUTPUT4 `KGG`/`MGG` |
| reload K, M, aero into SOL 144 | `DiskAeroCache` + `KGG` load-or-build switch | INPUTT4 / DBLOCATE |
| standard SOL 144 **and** reuse | same SOL number; reuse is executive I/O, chosen by flag/`ASSIGN` | cold start vs **RESTART / ASSIGN** |

The "generate vs reuse is an I/O concern expressed at the executive level, not a different SOL number" mapping is deliberate and matches NASTRAN's restart model.

---

## 5. Store Format and Bundle Layout

Numpy-native, **zero new dependency** (`scipy 1.13.1` + numpy already in-stack):

- `scipy.sparse.save_npz` / `load_npz` for the sparse unconstrained `KGG`/`MGG` (CSR, lossless).
- `np.savez` for the dense `AeroModel` members and the spline operators; the `AeroBox` list is serialized as **parallel ndarrays** (`colloc, bound_a, bound_b, normal, force_point, area, chord, i_span`) and rehydrated on load — no pickle (cross-version fragility; opaque for Part 25 provenance).
- `manifest.json` always written — the provenance contract (§6).

```
<job>_matstore/                  # default next to the .bdf; --dir overrides
  manifest.json                  # versions, source-BDF path+hash, fingerprints,
                                 #   Mach list, per-Mach correction record, full_span=true,
                                 #   unit-convention tag, format-version int
  KGG.npz   MGG.npz              # scipy CSR, UNCONSTRAINED g-set  (structure-keyed)
  gridmap.json                   # sorted-GID list + {gid:i}; MUST travel with K/M
  dofmap.csv                     # g_row,grid_id,component,x,y,z,cd  (shared w/ matrix_gaf_export)
  splines.npz                    # g_slope, g_disp                 (structure-keyed)  ← separate, §4.3
  aero_M0.000000.npz             # ajj_inv_corr, skj, djk, wg, boxes  (Mach+correction-keyed)
  aero_M0.600000.npz             #   fixed-width Mach @ 6dp == AeroCache._MACH_DP
```

Filenames use the **fixed-width Mach** convention (`M0.600000`) from `matrix_gaf_export` Decision #6 so the two stores interoperate. The `(Mach, k)` key reserves a slot for the Phase D unsteady DLM (`aero_M0.600000_K0.100000.npz`), `k` defaulting to `0.0` in Phase A.

**Unit convention (recorded, never re-applied):** `ajj_inv_corr` is stored *fully corrected* — post-correction, post-`1/β` (`aero_model.py:137`), post-`Γ→ΔCp` `2/chord` scaling (`aero_model.py:147`), Mach-baked. `boxes` are stored **physical** (un-PG-compressed; the β compression lives only inside the already-built inverse). A consumer that re-applies any scaling or re-compresses the boxes **double-corrects**. The manifest tags the convention; the loader applies nothing further.

---

## 6. Reload and Validation (provenance / staleness)

A stale cached matrix silently producing a wrong trim is the worst failure mode. Validation runs **before any matrix is trusted**; the default is **hard-fail naming the offending field**, with an opt-in degrade-to-fresh mode (§10).

`MatrixStore(dir, validate_against=bulk)` performs, in order:

1. **Version gate.** Read `manifest.json`; reject (or loudly warn) if the `format-version` int or recorded scipy/numpy version is incompatible — `save_npz`'s on-disk format is version-coupled.
2. **Structural fingerprint.** Recompute a SHA-256 over the cache-relevant bulk subset from the **live** deck and compare to the manifest. The hash is over **post-`resolve_grid_positions`** coordinates (`coord_transform.py:77` mutates `Grid.x/y/z` in place and zeroes `cp`, so a raw-CP-frame hash would mismatch the matrix actually built) plus the enumerated field set: `Grid x/y/z/cd/ps`, `CBAR` connectivity + orientation + pin-releases (`pa`/`pb`), `CBUSH` `gb` + orientation, `PBAR` `A/I1/I2/J/nsm`, `PBUSH` `k1..k6`, `MAT1` `E/G/rho`, `CONM2` mass/offset/inertia/cid, `CORD2R` chains. **Single-sourced** in one `_structural_key` helper with a unit test asserting *every* field perturbs the key.
3. **Geometry/mesh fingerprint.** `CAERO1` + `PAERO1` + `AEFACT` breakpoints + `CORD2R` — guards the AIC and splines.
4. **Grid-map equality.** `scipy.sparse.load_npz` `KGG`/`MGG`, then assert the saved `gridmap.json` sorted-GID list equals the current `build_grid_index` (`load_vector.py:12`) ordering **element-wise, not by length** — a single added/removed/renumbered grid shifts every higher `6·i+d` block silently. This is the load-bearing remap guard.
5. **Aero key match.** For each needed Mach, round to 6dp (matching `AeroCache._MACH_DP`), load `aero_M{mach}.npz`, and validate `(geometry, Mach, correction)`. The **correction fingerprint** is the *resolved* correction actually applied: method by first-match (`WKK > WT2 > WT1 > none`) on the **primary CAERO1 EID** (`aero_model.py:114`), the correction card **data** hash, and the fixed `w_ref = −ones(n)` convention for WT1/WT2 — because correction + β + Cp-scaling are *irreversibly baked* into `ajj_inv_corr` with no separate record of which was applied. Same-Mach + different-correction must invalidate.
6. **Spline key match.** Load `splines.npz` only if the `(geometry, structure: grid_index + spline cards)` fingerprint matches; else rebuild `g_slope`/`g_disp` live (Mach-independent, cheap relative to the AIC).
7. **Re-fire input guards against the live deck.** A deserialized `AeroModel` bypasses `build_aero_model`'s validators and may predate them — so re-run the **Mach ≥ 1 reject** (`aero_model.py:102`) and the **half-span SYMXZ/SYMXY reject** (`aero_model.py:77–84`) against the live `bulk`. Never trust the blob's validity.
8. **Hand off to the live solve.** Only validated `KGG`/`MGG` + `AeroModel` proceed; RBE3 `T`, SPC/SUPORT partition, `reduce_to_aset`, `K_eff = K_aa − q·Q_aa` all run live.

A `full_span = true` provenance flag is recorded. Post the 2026-06-12 half-span deprecation (full-span only) there is no sym/parity key to carry — a clean state — but the flag ensures a full-span-built matrix cannot be silently reused under a future half-span deck (step 7 enforces it).

---

## 7. Dual-Mode SOL 144

The solver core is already decoupled from the builds, so dual-mode is **two build-seam switches** plus the Phase 0 plumbing — nothing below the assembly changes.

**Fresh-compute path (default — standard NASTRAN way, byte-identical to today):**
```
aero_cache = AeroCache(bulk, grid_index, seed=aero)        # sol144.py:847
K_gg       = assemble_global_stiffness(bulk)               # sol144.py:110
... build D_jx, Q_aa, Q_ax, f_g live; reduce; trim solve
```

**Reload path (opt-in `--reuse-matrices` / `ASSIGN`):**
```
aero_cache = DiskAeroCache(bulk, grid_index, store, seed=aero)   # miss → store.load_aero(mach), else build+save
K_gg       = store.load_struct_kgg()                             # instead of assemble_global_stiffness
... build D_jx, Q_aa, Q_ax, f_g live; reduce; trim solve   (UNCHANGED)
```

The **single seam** is `AeroCache.get`'s miss-handler: point it at `build_aero_model` (fresh) or the deserializer (reload). `DiskAeroCache(AeroCache)` overrides **only** that handler and self-heals a partial store (build-and-save on a store miss). The structural switch is the one-line `K_gg = store.load(...) if store else assemble_global_stiffness(bulk)`.

**Critical invariant, both modes:** the q-fusions (`K_eff`, `C_ax`), the RBE3/SPC/SUPORT reduction, and the `K_ll` LU factorization always run live from the loaded operands. This is what lets one stored set serve an entire q-sweep and any label set.

**Blast-radius decision:** the `store=` object is passed at the **SOL 144 / CLI layer**, *not* threaded into `assemble_global_stiffness`/`assemble_global_mass`/`load_vector`. Threading it into the pure assembly functions widens the caching concern into SOL 101/103 and `load_vector` (which re-assembles `M` independently), and the memo would not deduplicate unless the *same* store object reached every call site. Persisting at the SOL 144 layer keeps the change local.

---

## 8. Implementation Plan

### 8.1 File touches

| File | Change |
|---|---|
| `sbeam/io/matrix_store.py` | **New.** `MatrixStore` (`save_struct`/`load_struct`, `save_aero`/`load_aero`, `has_aero(mach)`); `_structural_key`/`_geometry_key`/`_correction_key` hashers (single-sourced); `save_npz`/`np.savez` wrappers + `AeroBox` (de)serialization; `manifest.json` read/write; `StaleMatrixError`. |
| `sbeam/solver/genmatrices.py` | **New.** `run_genmatrices_struct(bulk, out_dir)` and `run_genaero(bulk, out_dir, machs)` drivers — wrap the existing builders unchanged. |
| `sbeam/solver/sol144.py` | **New** `DiskAeroCache(AeroCache)` overriding only the miss-handler. `store: Optional[MatrixStore]=None` on `run_sol144_trim` (`:753`) and `run_aeroelastic_static`; the `K_gg` load-or-build interception (`:110`); the `AeroCache`-vs-`DiskAeroCache` choice at `:847`. |
| `sbeam/assembly/reduction.py` | **DONE — landed with Step 59 (2026-07-06).** `reduce_to_aset(...)` extracted from `sol144._build_qaa_aset` / `_compute_aset_data`; behaviour-preserving, verified bit-identical against the SOL 144 + SOL 103 suites. Both this design and the exporter now simply consume it. |
| `sbeam/main.py` | **Phase 0:** `cc.sol == 144` dispatch branch looping subcases with one shared `AeroCache`. Add the `generate-matrices` subcommand and `--reuse-matrices`/`--save-matrices` flags. |
| `sbeam/viewer/app.py` | **Phase 0:** SOL 144 run path with the shared cache (mirror `main.py`). |
| `sbeam/results/f06_writer.py` | **Phase 0:** `Sol144TrimResult` `.f06`/text writer (none exists today). |
| `sbeam/model/aero.py`, `sbeam/parser/bdf_reader.py`, `sbeam/model/bulk_data.py` | `MKAERO1` card (shared with `matrix_gaf_export` §3.2; `k = 0.0` enforced). |
| `sbeam/parser/case_control.py` | **Phase 4 (optional):** parse `ASSIGN MATRIX=DIR` executive directive. |
| `docs/10_standard/05_aeroelastics.md` | Reuse-store section: pipeline, cache boundary, dual-mode SOL 144, the don't-cache-below-q rule. |
| `docs/10_standard/02_card_reference.md` | `MKAERO1` (cross-ref `matrix_gaf_export`); `--reuse-matrices`/`generate-matrices`/`ASSIGN MATRIX`. |
| `docs/10_standard/00_program_overview.md` | CLI subcommands + reuse workflow. |
| `tests/io/test_matrix_store.py` | **New.** R1–R6 (round-trip, staleness, grid-map). |
| `tests/solver/test_sol144_reuse.py` | **New.** R7–R10 (cached-vs-fresh, q-sweep, multi-Mach, guard re-fire). |
| `sample/sample_matrix_reuse.bdf` | **New.** Full-span wing + CAERO1 + SPLINE2 + multi-Mach `MKAERO1` + multi-`q` TRIM subcases. |
| `CHANGELOG.md` | On promotion: `[Unreleased] → Added: matrix reuse store, generate-matrices / --reuse-matrices, dual-mode SOL 144`. |
| `docs/30_future/00_backlog.md` | On promotion: add as formal steps (next free numbers) per the step format; remove on delivery per the step-completion rule. |

### 8.2 Order of operations (generation)

```
1. parse BDF; resolve_grid_positions(bulk)            # mutates coords in place — hash AFTER
2. KGG = assemble_global_stiffness(bulk);  MGG = assemble_global_mass(bulk)   # unconstrained
3. gridmap = sorted-GID list + {gid:i};  dofmap rows
4. save_struct(KGG, MGG, gridmap, dofmap, _structural_key, _geometry_key)
5. grid_index = build_grid_index(bulk)
6. g_slope, g_disp = build_g_spline(bulk, boxes, grid_index)    # once, structure-keyed
7. save_splines(g_slope, g_disp, _structural_key + spline-card hash)
8. for M in sorted(set(machs)):
      aero = build_aero_model(bulk, grid_index=grid_index, mach=M)   # PG + correction baked
      save_aero(M, aero.ajj_inv_corr, aero.skj, aero.djk, aero.wg, aero.boxes,
                _geometry_key, mach@6dp, _correction_key(M))
9. write manifest.json (versions, fingerprints, Mach list, correction-per-Mach, full_span=true, unit tag)
```

### 8.3 Backward compatibility

A deck with no reuse flag and no store is **bit-identical** to today: `store=None` is the default everywhere; the new card field and directive are additive; the `DiskAeroCache` is only constructed on the reuse path. The single existing-path touch is the `reduce_to_aset` refactor, gated by the SOL 144 + SOL 103 suites passing unchanged (and shared with `matrix_gaf_export` so it is extracted only once).

---

## 9. Verification Cases

| ID | Case | Target | Tolerance |
|---|---|---|---|
| **R1** | Round-trip `KGG`/`MGG`: assemble → `save_npz` → `load_npz` → compare to fresh assemble | exact | ≤ 1e−15 |
| **R2** | Round-trip `AeroModel` members: `build_aero_model` → `save_aero` → `load_aero` → compare `ajj_inv_corr`/`skj`/`djk`/`wg`/`boxes` member-by-member | exact | ≤ 1e−15 |
| **R3** | Grid-map guard: a deck with one GRID renumbered/added/removed raises `StaleMatrixError` naming the GID mismatch (not a length check) | raises | exact-match assertion |
| **R4** | Structural-fingerprint completeness: a unit test perturbs **each** contributing field (Grid ps, CBAR pa/pb, CBUSH gb, PBAR/PBUSH/MAT1, CONM2 cid/inertia, CORD2R) and asserts the key changes | every field perturbs | exact |
| **R5** | Correction guard: same Mach, WKK data edited → `load_aero` raises; blank-vs-present correction distinguished | raises | exact |
| **R6** | Version guard: manifest with an incompatible scipy/format-version → load refuses (or warns per mode) | raises/warns | message match |
| **R7** | **Cached-vs-fresh trim (load-bearing):** generate store → trim with `--reuse-matrices` vs fresh trim, same deck, SC1 + SC2 | **bit-identical** trim vars | ≤ 1e−12 relative |
| **R8** | q-sweep reuse: one stored set trims a sweep of dynamic pressures; assert one `load_aero` per Mach, no rebuild, and each `q` matches the fresh solve | reuse + match | ≤ 1e−12 |
| **R9** | Multi-Mach reuse: SC at distinct Machs uses one `DiskAeroCache`, one file per Mach, no wrong-Mach reuse (the AE9 regression) | per-Mach correct | ≤ 1e−12 |
| **R10** | Guard re-fire on load: a stored model loaded against a deck that is now Mach ≥ 1 or SYMXZ ≠ 0 raises the same error `build_aero_model` would | raises | message match |
| **R11** | Non-regression: full existing suite (V-AE1f full-span trim, SOL 101/103, all aero/integration) passes unchanged with `store=None` | all pass | exact |

R7 is the load-bearing test — it proves the reload path and the fresh path produce the *same physics* through one shared reduction. R8 is the proof that the q-fusion stayed live (the cache boundary is correct).

---

## 10. Open Decisions

| # | Decision | Recommendation | Owner |
|---|---|---|---|
| 1 | Reuse trigger: CLI flag vs `ASSIGN MATRIX` directive | **CLI flag in Phase 3**; add the directive in Phase 4 if deck portability is wanted (it is more NASTRAN-faithful and travels with the deck) | Author |
| 2 | Store format | **`.npz` (numpy-native)** for internal reload — lossless, zero-dependency, fast; `.mm`/OP4 only via the `matrix_gaf_export` export bridge | Author |
| 3 | Stale-match behaviour | **Strict-abort by default** (names the offending field); opt-in `--reuse-matrices auto` warns and degrades to fresh so one stale Mach doesn't kill a sweep | Author |
| 4 | Splines location | **Separate `splines.npz`**, structure-keyed, shared across Mach groups (§4.3) — not embedded per-Mach | Author |
| 5 | What is cached | **Pre-q, pre-reduction operands only** (`KGG`/`MGG` unconstrained, `AeroModel` members, splines); never `Q_aa`/`K_eff`/`K_aa`/LU | Author |
| 6 | Bundle convergence with `matrix_gaf_export` | **Converge** — shared manifest schema + fixed-width Mach filenames + shared `reduce_to_aset`; one store serves reload (`.npz`) and export (`.mm`) | Author |
| 7 | `wg` (W2GJ) persistence | **First-class store member** — it is an additive RHS, not inside the GAF; omitting it drops camber/twist | Author |
| 8 | `djk` rebuild divergence | Refactor `sol144.py:617/720` to read `aero.djk` **before** a non-trivial DLM `djk(M,k)` is ever stored (harmless at −I today); reserve the `(Mach,k)` key now | Author |

---

## 11. Risks and Effort

### 11.1 Effort

| Phase | Task | Effort | Risk |
|---|---|---|---|
| 0 | SOL 144 CLI/viewer dispatch + shared cache + `.f06` writer (prerequisite) | ~2.5 days | **Medium — first SOL 144 production surface; integration, not algorithm** |
| 1 | `MatrixStore` + struct generation + hashers + R1/R3/R4/R6 | ~1.5 days | Low — pure new code over Mach/q-free pure functions |
| 2 | `MKAERO1` + aero generation + `AeroModel`↔npz + two-key fingerprints + `reduce_to_aset` refactor + R2/R5 | ~2 days | Low–medium — the refactor is the only existing-path touch, gated by tests |
| 3 | `DiskAeroCache` + reload validation + flags + R7–R10 | ~2.5 days | Medium — correctness-critical (a wrong key silently corrupts), heavy on validation tests |
| 4 | Export-bundle convergence (`.mm`/OP4 siblings) | ~1 day | Low — composes `matrix_gaf_export` writers onto the store |
| | **Total Phases 0–3** | **~8.5 days** | **Low–medium overall** |

The payoff scales with the sweep: the `O(n_box²)` Biot–Savart AIC build and the `O(n_box³)` inverse are computed once per Mach and then loaded — largest win for the multi-`q`, multi-load-case envelope sweeps that dominate Part 25 trim work. Benchmark on a representative deck before claiming a speedup (`np.savez_compressed` trades disk for load-time decompression; dense `ajj_inv_corr` is `n_box²`, `g_disp` is `3·n_box·n_g`).

### 11.2 Top correctness risks

1. **Stale-key silent corruption (dominant).** Omit any contributing field from the structural/geometry/correction fingerprint and a wrong-but-non-crashing matrix is served. Mitigation: single-sourced hashers + R4 (every field perturbs the key) + hard-fail naming the field + strict-abort default.
2. **Grid-map remap corruption.** A reloaded `KGG`/`MGG` is valid only against the exact sorted-GID ordering; one added/removed/renumbered grid shifts `6·i+d` for all higher indices silently. Mitigation: element-wise sorted-GID assertion (R3), not a count check.
3. **Caching below the q-fusion.** Freezing `K_eff`/`C_ax`/`K_ll` at one `q` breaks q-sweeps — the single biggest design trap. Mitigation: store only pre-q operands; R8 regression-guards the boundary; document it prominently in `matrix_store.py`.
4. **Bypassing `build_aero_model` guards on load.** A deserialized model skips the Mach ≥ 1 / SYMXZ rejects and may predate them. Mitigation: re-fire the guards against the live deck (R10); never trust the blob.
5. **Double-correcting on reload.** `ajj_inv_corr` is already corrected/β-scaled/Cp-scaled/Mach-baked, and `boxes` are physical. Re-applying any scaling or re-PG-compressing corrupts results. Mitigation: manifest unit-convention tag; loader applies nothing.
6. **W2GJ dropped.** `wg` is the additive RHS, not inside `Q_aa`/`Q_hh`. Mitigation: persist `wg` as a first-class member.
7. **scipy/numpy version coupling.** `save_npz` on-disk format can shift across versions. Mitigation: record versions + format-int (R6); regenerate after a bump.
8. **Inherited Phase A defects.** A reused aero kernel inherits any open `g_slope`/`g_disp` defect (AE4, SPLINE2 kinematics on swept/offset configs) baked into the splines. Mitigation: manifest known-issue flag for swept configs; straight-wing reuse is sound today.
9. **`reduce_to_aset` fork.** Shared with `matrix_gaf_export`; if both land independently they fork it. Mitigation: extract once, both consume the single helper, gated by both suites.
10. **`djk` latent divergence.** `build_djk` is rebuilt locally at `sol144.py:617/720` instead of reading `aero.djk`. Harmless at −I; once a non-trivial DLM `djk(M,k)` is stored, the local rebuilds diverge. Mitigation: refactor those call sites before storing a non-trivial `djk`; reserve the `(Mach,k)` slot now.

---

## 12. References

- **`docs/30_future/designs/matrix_gaf_export.md`** — the export/OUTPUT4 complement; source of the bundle, manifest, fixed-width Mach filename convention, `MKAERO1` card, and the `reduce_to_aset` refactor this design shares.
- **In-project precedents:** `solver/sol144.py::AeroCache` (the in-memory cache made persistent here, `:38`/`:50`/`:847`); `aero/aero_model.py::build_aero_model` (per-Mach generation, `:43`; correction + β + Cp baking, `:114–147`; input guards `:77–84`/`:102`); `aero/coupling.py::build_qaa`/`build_fg`/`build_gaf` (the live recombination, `:54`/`:78`/`:105`); `aero/integration.py::build_skj`/`build_djk`/`build_wg`/`build_djx` (`:13`/`:28`/`:41`/`:65`); `assembly/stiffness.py::assemble_global_stiffness` (`:165`), `assembly/mass_matrix.py::assemble_global_mass` (`:84`); `assembly/load_vector.py::build_grid_index` (`:12`); `assembly/coord_transform.py::resolve_grid_positions` (`:77`, mutates coords — hash after).
- **NASTRAN:** MSC Nastran Quick Reference Guide — `OUTPUT4`/`INPUTT4`, `ASSIGN`, `DBLOCATE`, `RESTART`, `MKAERO1`; MSC Nastran Aeroelastic Analysis User's Guide — AIC/GAF and the static-trim governing equation `(K_aa − q·Q_aa)·u = q·f_g + f_struct`.
- **AE9** (multi-Mach `AeroCache` contract) and **AE4** (SPLINE2 kinematics, baked into the cached splines) — `docs/30_future/00_backlog.md`.

---

## 13. Acceptance Criteria

- R1–R11 pass with the stated tolerances; **R7 (cached-vs-fresh bit-identical trim) and R8 (q-sweep reuse) are load-bearing.**
- A deck with no reuse flag and no store is **bit-identical** to pre-feature output; the full existing suite (V-AE1f full-span trim, SOL 101/103, aero/integration) passes unchanged.
- `sample/sample_matrix_reuse.bdf` generates a complete bundle whose `manifest.json` validates and whose reuse run reproduces the fresh trim across a documented multi-`q`, multi-Mach sweep walkthrough in `05_aeroelastics.md`.
- The reuse bundle and the `matrix_gaf_export` export bundle share one manifest schema and Mach filename convention; one store serves both internal reload (`.npz`) and external handoff (`.mm`).
- `docs/10_standard/05_aeroelastics.md`, `02_card_reference.md`, `00_program_overview.md`, `CHANGELOG.md` updated; on promotion to active work, formal steps added to (and on completion removed from) `docs/30_future/00_backlog.md` per the step-completion rule.
