# Sample decks

One folder per model family. Each deck's header comment carries the detail (geometry, units,
expected numbers); this page says what each one is for. The numbers the test suite holds these
decks to are in [`docs/10_standard/00_program_overview.md`](../docs/10_standard/00_program_overview.md)
(verification-case tables).

| Folder | What it is | Solutions |
|---|---|---|
| [`beam/`](#beam) | Small structural models to start from | 101, 103 |
| [`validation/`](#validation) | Decks checked against a closed form or a published number | 101, 103, 144 |
| [`goland_wing/`](#goland_wing) | The Goland wing, exported as a reduced modal model | 103 |
| [`ha144a/`](#ha144a) | MSC's HA144A forward-swept-wing airplane and its variants | 144 |
| [`cessna210_flagship/`](#cessna210_flagship) | A realistic light airplane: one bulk file, several thin drivers | 144 |

## Running a deck

```bash
python -m sbeam.main sample/beam/simple_beam.bdf
```

Results (`.f06` and the per-run CSV/BDF exports) are written beside the deck and are ignored by
git. An `INCLUDE` is resolved relative to the deck that names it, so a family folder has to be
copied or moved as a whole.

## Which decks MSC NASTRAN could read

The first line of every deck is one of two tags:

- `$ COMPAT: MSC-runnable` — every bulk card and case-control command in the deck, and in the
  files it `INCLUDE`s, is one MSC NASTRAN defines.
- `$ COMPAT: sbeam-extension` — the deck uses at least one
  [sbeam-only card or command](../docs/10_standard/02_card_reference.md#sbeam-only-cards)
  (`W2GJ`, `MONSECT`, `MANVR`, `MODEXP` …). MSC will not run it.

The tag is about card names and layouts. **No deck here has been run in MSC NASTRAN**, and
"MSC-runnable" does not say MSC would give sbeam's numbers: the known differences are in the
[deviation register](../docs/10_standard/12_deviation_register.md). 17 files carry the first
tag and 20 the second. Of the SOL 144 decks only `val_dihedral_trim.bdf` and the MSC archive
listing `HA144A.bdf` are MSC-runnable; sbeam refuses the archive listing. Two tests hold the tags: one against sbeam's own
list of sbeam-only names, one against the cards pyNastran does not know (#83, #95).

Four kinds of file here are **not** decks to run on their own; the tables mark them:

- **bulk only**: no case control; a driver deck `INCLUDE`s it.
- **overlay**: extra bulk data `INCLUDE`d after the bulk file by a driver.
- **archive**: a verbatim vendor listing kept as a reference record; sbeam refuses it by design.
- **generated**: written by a tool; regenerate it, do not edit it.

## `beam/`

| File | SOL | Purpose |
|---|---|---|
| `simple_beam.bdf` | 101 | 10 m steel cantilever, 5 CBARs, tip load. The first deck to run. |
| `simple_beam.dat` | — | **Bulk only.** The same beam with no case control, for loading into the viewer to inspect geometry and author the cases there. |
| `beam_vib.bdf` | 103 | The cantilever with a point mass on the tip grid and zero beam density: a tip-mass-dominated mode. |
| `beam_vib1.bdf` | 103 | Companion to `beam_vib.bdf`: the mass sits off the tip, carried through an RBAR, with beam density on. |
| `pylon_strut_engine.bdf` | 101 | Strut-braced engine pylon on a wing stick: CBAR pylon, a CROD and a CONROD strut, CONM2 engine (#38). |

## `validation/`

Structural closed forms:

| File | SOL | Purpose |
|---|---|---|
| `val_cantilever_static.bdf` | 101 | Cantilever tip load, δ = PL³/3EI. |
| `val_ss_static.bdf` | 101 | Simply supported beam, mid-span load, δ = PL³/48EI. |
| `val_cantilever_modes.bdf` | 103 | Cantilever fundamental bending frequency against the Euler-Bernoulli closed form. |
| `val_free_free_modes.bdf` | 103 | Unconstrained beam: six rigid-body modes at ~0 Hz. |
| `val_cantilever_offset_mass_modes.bdf` | 103 | Tip mass offset from the elastic axis: CONM2 offset couples bending and torsion. |

Rigid vortex-lattice aerodynamics (aero cards only; SOL 101 is just the carrier):

| File | SOL | Purpose |
|---|---|---|
| `val_vlm_rect_ar8.bdf` | 101 | Rectangular wing, AR = 8: the standard lift-curve-slope case. |
| `val_vlm_dihedral.bdf` | 101 | The same wing with +10° dihedral: an out-of-plane lifting surface. |
| `val_vlm_anhedral.bdf` | 101 | Its mirror, −10° anhedral. |
| `val_vlm_byu_wing.bdf` | 101 | The BYU VortexLattice.jl "steady-state analysis of a wing" example, itself validated against AVL. |
| `val_wing_taper_dihedral.bdf` | 101 | Tapered wing with 5° dihedral, no twist. Half of an A/B pair. |
| `val_wing_taper_dihedral_twist.bdf` | 101 | The same wing with a 0 → −2° `W2GJ` washout: shows what twist does to the load. |

Static aeroelastic trim:

| File | SOL | Purpose |
|---|---|---|
| `val_dihedral_trim.bdf` | 144 | Minimal flexible wing with 10° dihedral in a plunge trim: splines and trim on canted panels (Step 58). |
| `val_thrust_trim.bdf` | 144 | Wing, tail and an engine hung below the nose: an applied `FORCE` (thrust) in the trim balance (#6). |
| `val_lateral_aileron_rudder.bdf` | 144 | Wing, fin, aileron pair and rudder: steady-roll and steady-sideslip trims (#10). |

## `goland_wing/`

| File | SOL | Purpose |
|---|---|---|
| `goland_wing_modes.bdf` | 103 | The Goland wing as the Flaps demo builds it, with `MODEXP` writing the reduced modal model (OP4 + Universal file) that sgear and Flaps read (#100, #107). |

## `ha144a/`

The forward-swept-wing airplane of MSC Nastran Aeroelastic Analysis User's Guide, Listing 7-1.
Every runnable deck here is self-contained and carries its own copy of the model; they all derive
from `ha144a_fullspan_sbeam.bdf`.

| File | SOL | Purpose |
|---|---|---|
| `HA144A.bdf` | 144 | **Archive.** The verbatim MSC listing and its published values. Does not run; its header says why. |
| `ha144a_fullspan_sbeam.bdf` | 144 | The runnable full-span transcription: level-flight trim against the MSC numbers. The base model for the rest. |
| `ha144a_fullspan_dmij.bdf` | 144 | The same trim with the aero corrections entered MSC's way, as `DMIJ W2GJ` and `DMIK WKK` matrices (#104). |
| `ha144a_body_trim.bdf` | 144 | Adds decoupled strip body panels whose load reaches the structure through `LOADINJ` (Step 64). |
| `ha144a_massset_sweep.bdf` | 144 | One trim, three payload conditions selected per subcase with `MASSCASE` (Step 60). |
| `ha144a_mass_combination_sweep.bdf` | 144 | The same sweep in MSC's construction: `BEGIN MASSID` sections combined by `MASSSET` (#102). |
| `ha144a_fullspan_mloads.bdf` | 144 | Transient maneuver: an elevator ramp from the 1g trim, `MANVR` card set (Phase G0). |
| `ha144a_mloads_massset.bdf` | 144 | Free-flight maneuver run over three payload conditions (Step 63). |

## `cessna210_flagship/`

One realistic airplane held in a single bulk file, with a thin case-control driver per analysis.
The worked tutorial is
[`docs/20_theory/02_realistic_airplane_sol144.md`](../docs/20_theory/02_realistic_airplane_sol144.md).

| File | SOL | Purpose |
|---|---|---|
| `cessna210_flagship_bulk.bdf` | — | **Bulk only.** The shared airplane model every driver below includes. |
| `cessna210_flagship_trim.bdf` | 144 | Driver: 1g cruise and 2.5g pull-up trims. |
| `cessna210_flagship_massset.bdf` | 144 | Driver: one trim over three payload cases (ferry, cruise, MTOW). |
| `cessna210_flagship_mloads.bdf` | 144 | Driver: 1g trim, then an elevator-ramp transient maneuver. |
| `cessna210_flagship_gust.bdf` | 144 | **Generated** by `sbeam-cases` from the trim driver: FAR/CS 23.341 gust cases at V_C and V_D. |
| `cessna210_flagship_body.bdf` | 144 | Driver: the two trims with cruciform fuselage panels coupled into the aerodynamics (Step 66). |
| `cessna210_flagship_body_strip_drv.bdf` | 144 | Driver: the same with decoupled strip body panels, as the controlled contrast. |
| `cessna210_flagship_body_cruciform.bdf` | — | **Overlay.** The cruciform body panels, included by `cessna210_flagship_body.bdf`. |
| `cessna210_flagship_body_strip.bdf` | — | **Overlay.** The strip body panels, included by `cessna210_flagship_body_strip_drv.bdf`. |
| `cessna210_flagship_section_data.csv` | — | Section aerodynamic coefficients that `sbeam_tools` turns into the aero-correction cards. Read by the tools, not by the solver. |
