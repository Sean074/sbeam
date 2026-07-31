# Aeroelastics — Index (Phases A–C, G0)

> **Split by area (2026-07-05).** The aeroelastics code standard is split into three
> area guides; this file keeps the cross-phase material (architecture, validation
> status, supported-card table) and the file map. **New documentation goes in the
> matching area file below**, not here.

| File | Scope |
|------|-------|
| [`05a_aero_vlm.md`](05a_aero_vlm.md) | **Phase A — aerodynamics**: AEROS/CAERO1 cards, VLM AIC, integration matrices, AIC corrections (WKK/WT1/WT2), CHORDCP, section force/moment synthesiser, body panels (cruciform + decoupled strip), compressibility, viewer aero tab |
| [`05b_splining.md`](05b_splining.md) | **Phase B — structure ↔ aero splining**: SPLINE2 (NASTRAN infinite beam), ATTACH, SPLINE0, `build_g_spline` API, `compute_structural_loads` |
| [`05c_sol144_maneuver.md`](05c_sol144_maneuver.md) | **Phases C + G0 — SOL 144 & maneuver loads**: governing equation, coupling, trim card set, trim solver + derivatives, running & output (f06, load export, balanced maneuvers, transient MLOADS), monitor points |

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
| `sbeam/aero/corrections.py` | `Wkk` diagonal correction, `WT2` pressure-match, `WT1` per-strip force-match (**deprecated** — DEF-H2/H3) |
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
| `sbeam/model/mass_overlay.py` | **Step 60** — `resolve_mass_case` / `effective_conm2s`: MASSSET payload-case resolution (baseline scaling + ADD/REPLACE/DELETE overlay) |
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
| `AECORR` | Force/pressure matching AIC corrections (WT2; WT1 deprecated by DEF-H2/H3 2026-07-31) | S43 |
| `CHORDCP` | Injected CFD/WT steady-Cp mean flow at a reference AOA (sbeam extension) | S54 |
| `SET1` | List of structural grid IDs for spline input | S45 |
| `SPLINE2` | NASTRAN infinite beam spline: links CAERO1 box range to SET1 grids (rigid chord arms, DTOR/DTHX/DTHY flexibilities) | S45–46, AC7 |
| `ATTACH` | Rigid attachment of box group to single master grid (Step 47, complete; slope-row signs corrected by DEF-H1 2026-07-31) | S45–47 |
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
| `MASSSET` | Payload / mass case (ADD/REPLACE/DELETE CONM2 ops + SCALE) | S60 |

