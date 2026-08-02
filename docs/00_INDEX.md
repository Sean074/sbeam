# sbeam Documentation — Index

This directory is organised into four numbered sections by **document type**. Lower numbers
are the day-to-day references; higher numbers are planning and historical record.

| Section | Type | Contents |
|---------|------|----------|
| `10_standard/` | **Code standard** | Program, subsystem, and process guides — the authoritative description of how sbeam works *today*. Update these whenever code changes. |
| `20_theory/` | **Theory, test cases & worked examples** | Analytical derivations and the validation/diagnostic studies behind them. |
| `30_future/` | **Future development** | The backlog, plans, capability reviews, and design proposals for not-yet-implemented cards. |
| `40_history/` | **Historic data & fixes** | The completed-step record, resolved defects, and archived one-off plans. |

---

## 10_standard — Code standard

| File | Scope |
|------|-------|
| [`00_program_overview.md`](10_standard/00_program_overview.md) | Program code standard, developer and user guide |
| [`01_beam_model.md`](10_standard/01_beam_model.md) | Data model and parser (BulkData container, dataclass mapping, parser API, model limits; card summary — field tables in `02_card_reference.md`) |
| [`02_card_reference.md`](10_standard/02_card_reference.md) | BDF card field reference (all supported cards) |
| [`03_static_analysis.md`](10_standard/03_static_analysis.md) | SOL 101 static analysis solver |
| [`04_modal_analysis.md`](10_standard/04_modal_analysis.md) | SOL 103 normal modes solver |
| [`05_aeroelastics.md`](10_standard/05_aeroelastics.md) | **Aeroelastics index** (split by area 2026-07-05): architecture overview, validation status, supported-card table, file map |
| [`05a_aero_vlm.md`](10_standard/05a_aero_vlm.md) | Phase A — VLM aerodynamics: CAERO1 meshing, AIC, corrections (WKK/WT1/WT2/CHORDCP), section synthesiser, body panels, viewer aero tab |
| [`05b_splining.md`](10_standard/05b_splining.md) | Phase B — structure ↔ aero splining (SPLINE2/ATTACH/SPLINE0, `build_g_spline`, load transfer) |
| [`05c_sol144_maneuver.md`](10_standard/05c_sol144_maneuver.md) | Phases C + G0 — SOL 144 trim/derivatives/divergence, running & output, transient maneuver loads (MLOADS), monitor points |
| [`06_viewer.md`](10_standard/06_viewer.md) | Streamlit/Plotly pre/post-processing viewer |
| [`07_code_review_process.md`](10_standard/07_code_review_process.md) | Critical code-review process |
| [`08_release_process.md`](10_standard/08_release_process.md) | Versioning and release process |

## 20_theory — Theory, test cases & worked examples

| File | Scope |
|------|-------|
| [`00_beam_methods.ipynb`](20_theory/00_beam_methods.ipynb) | Euler-Bernoulli theory; stiffness/mass matrix derivations; worked example |
| [`01_aeroelastics_theory.md`](20_theory/01_aeroelastics_theory.md) | VLM, AIC corrections, splining, SOL 144 theory |
| [`02_realistic_airplane_sol144.md`](20_theory/02_realistic_airplane_sol144.md) | Tutorial: the Cessna 210 flagship SOL 144 sample family — the deck layer by layer (structure, mass, mesh, splines, corrections, trim, monitors, mass cases, transient, body panels), then the f06 read block by block against hand-check anchors |
| [`aeroelastic_derivatives.md`](20_theory/aeroelastic_derivatives.md) | Tutorial: rigid vs elastic-restrained vs elastic-unrestrained (mean-axis) stability derivatives + the ZAERO modal form — new-engineer level |
| [`studies/a1_spanwise_spacing.md`](20_theory/studies/a1_spanwise_spacing.md) | VLM lift-slope spanwise-spacing convergence diagnostic |
| [`studies/a2_wing_root_interference.md`](20_theory/studies/a2_wing_root_interference.md) | HA144A wing-root interference residual (AE15/AC8) — attribution study, accepted residual |

## 30_future — Future development

| File | Scope |
|------|-------|
| [`00_backlog.md`](30_future/00_backlog.md) | **Authoritative backlog** — priority-ordered open work: strategic aim, design-review verdicts, Tier 1 (SOL 144 production process incl. the Phase G0 plan), Tier 2 (infrastructure), Tier 3 (SOL 145 + DLM), Tier 4 (lower priority) |
| [`01_static_aero_plan.md`](30_future/01_static_aero_plan.md) | Static-aero architecture reference (Phases A–C complete): layer diagram, matrix nomenclature, delivered-step map, references, validation-case index |
| [`designs/amode_card.md`](30_future/designs/amode_card.md) | AMODE assumed-mode card — design proposal |
| [`designs/rbmref_card.md`](30_future/designs/rbmref_card.md) | RBMREF rigid-body-mode reference card — design proposal |
| [`designs/spline9_hermite_beam_spline.md`](30_future/designs/spline9_hermite_beam_spline.md) | SPLINE9 FE-consistent Hermite beam spline (sbeam extension) — design proposal |
| [`designs/dlm_rfa_flutter_gust.md`](30_future/designs/dlm_rfa_flutter_gust.md) | DLM / RFA flutter & gust (Phase D) — design proposal |
| [`designs/matrix_gaf_export.md`](30_future/designs/matrix_gaf_export.md) | Matrix / GAF **export** (OUTPUT4 → FLAPS/ZAERO) — design proposal |
| [`designs/matrix_reuse_store.md`](30_future/designs/matrix_reuse_store.md) | Matrix **reuse store** (precompute/save/reload K, M, aero; dual-mode SOL 144) — design proposal |

## 40_history — Historic data & fixes

| File | Scope |
|------|-------|
| [`00_completed_development.md`](40_history/00_completed_development.md) | **Index** of the completed-development record (split by area 2026-07-05): file map, defect-ID legend, principles |
| [`01_program_foundation.md`](40_history/01_program_foundation.md) | Foundation: setup, BDF parser, model enhancements, integration/verification, infrastructure, reviews |
| [`02_sol101_static.md`](40_history/02_sol101_static.md) | SOL 101 static solver development + defects |
| [`03_sol103_modal.md`](40_history/03_sol103_modal.md) | SOL 103 modal solver development + defects |
| [`04_viewer_gui.md`](40_history/04_viewer_gui.md) | Viewer / GUI development (Phase 1 viewer, aero tabs, SOL 144 display) + defects |
| [`05_aero_vlm_spline.md`](40_history/05_aero_vlm_spline.md) | Aerodynamics: VLM, corrections, body panels, splining (Phases A + B) + defects |
| [`06_sol144_static_aeroelastic.md`](40_history/06_sol144_static_aeroelastic.md) | SOL 144 static aeroelastics (Phase C): trim, derivatives, maneuver loads, monitor points, AC close-out |
| [`07_maneuver_transient.md`](40_history/07_maneuver_transient.md) | Transient maneuver loads (Phase G0) |
| [`archive/`](40_history/archive/) | Superseded one-off plans and fully-actioned reviews (e.g. the CONM2/SOL103 fix plan; the ZAERO capability review, all goals folded into closed Steps 39–58) |

---

> Root-level docs live outside `docs/`: [`../README.md`](../README.md) (user front page),
> [`../CHANGELOG.md`](../CHANGELOG.md) (release notes), and [`../CLAUDE.md`](../CLAUDE.md)
> (guidance for Claude Code). The `figures/` directory holds SVGs referenced by the theory docs.
