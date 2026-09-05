# Conventions Charter — Signs, Axes, Frames, Reference Points, Units

**Authoritative single source** for every sign/axis/frame/reference-point/unit convention
in sbeam (2026-08-04 process review, R5). Sign/axis/reference-point errors were the #1
rework driver of 2026 — seven separate defect cycles (A3, A9, AE1-A, AE1-E, A-GUI2a/2b,
DEF-M2). The rules:

1. **Every physics step's design note must cite the sections of this charter it relies
   on, before code is written** (CLAUDE.md rule 1).
2. **New sign logic must go through the named single-source helpers (§8)** — never
   re-derive an arm, a rate scale, or a box-ID map inline.
3. **A change to any convention here is a breaking change** — it requires an L-tier step,
   an update to this file, and a sweep of every consumer.

Facts below are verified against code/theory with citations (extraction 2026-08-04).
Deeper derivations: `docs/20_theory/01_aeroelastics_theory.md` §2.9.

---

## 1. Frames

- **Basic frame (CID 0):** all internal computation. Freestream along **+x** (x points
  aft/downstream), **z up**, y completes the right-handed triad — so **+y = starboard**
  (`aero/panel.py:134`, theory §1).
- **Textbook comparison (figure `../figures/sign_conventions_state.svg`):** relative to
  standard flight-mechanics body axes (x forward, y right, z down), the basic frame is a
  **180° rotation about y**: y is shared, x and z are both negated. Consequences:
  pitch-plane quantities (α, θ, q, CMY) carry textbook signs; **moments about basic
  +x/+z are the negatives of textbook L (roll) and N (yaw)**. sbeam's `C_lp` and `C_nr`
  therefore come out **positive** for a damped airplane; tests gate magnitude and
  antisymmetry only, never an absolute lateral sign
  (`tests/aero/test_lateral_derivs.py:9-14`, `tests/aero/test_yaw_rate_drag.py:193-196`).
- **Body axis = basic frame** for aero totals (CZ along +z up, CX along +x). **Wind axis
  is reporting-only:** `CL_wind = CZ·cosα − CX·sinα` rotated through trimmed α
  (`solver/sol144.py:869-883`). Reported CD is the far-field Trefftz C_Di, positive
  downstream.
- **URDD card values are given in the RCSID frame** and rotated to basic before use;
  URDD1–6 are rigid accelerations of the whole airframe about the SUPORT point
  (`solver/sol144_util.py:54-121, 161-171`).

## 2. Aerodynamic forces and moments

- **Box force acts along the geometric panel normal** (not body-z, not wind axis):
  `F_j = q·A_j·ΔCp_j·n̂_j`; no leading-edge suction, no in-plane force (DEF-M2;
  `aero/integration.py:27-42`). Panel normals are oriented so the dominant component is
  positive: horizontal panels → +z, vertical panels → +y (`aero/panel.py:220-225`).
- **The SOL 144 `gamma` variable is ΔCp, not circulation.** True circulation
  Γ = cp·area/(2·width) (`aero/vlm.py:219-231`).
- **¼-chord = force point** (bound vortex / Kutta–Joukowski); **¾-chord mid-span =
  collocation point** (flow tangency) (`aero/panel.py:199-207`).
- **Moment reference = the AEROS RCSID origin** for aircraft totals — one point, never
  per-strip ¼-chords. Exceptions: hinge moments (about the cid1 hinge axis) and
  MONPNT/MONSECT reference points. Lateral totals CMx/CMz reference `suport_pos`
  (`solver/sol144.py:889-891`).
- **Signs:** CZ up-positive; **CMY nose-up-positive** via the single-source arm
  `My = −Σ Fz·(x_fp − x_ref)` (`pitch_moment`, §8). Nondimensionalization: CZ/CX/CY by
  S_ref; CMY by S_ref·c_ref; CMX/CMZ by S_ref·b_ref.
- **The trim chain carries force/q units; ×q happens only at export.** Exported
  FORCE/MOMENT cards are physical CID-0 loads.

## 3. Normalwash and correction cards

- **Internal normalwash `w` is a dimensionless downwash slope Δz/Δx with POSITIVE =
  WASHOUT = less lift** (nose-up incidence = negative w). The −1 lives in `build_djk`
  (= −I) and the ANGLEA column (−n_z) (`aero/integration.py:4-12, 45-58`).
- **The W2GJ card uses the NASTRAN sign: positive = leading-edge-up = MORE lift** (like
  ANGLEA). `build_wg` negates on assembly; the card writers negate on emission so decks
  round-trip (AE8a, fixed 2026-07-05; `aero/integration.py:61-68,104`,
  `model/aero.py:88-93`). **Never hand-add a sign between card and assembly.**
- CHORDCP: `data` = signed per-box dΔCp/dα_local; `alpha_ref` is **degrees on the card,
  radians in storage** (`model/aero.py:119`).

## 4. Splining

- **SPLINE2 axis = the CID y-axis** (MSC convention) (`aero/spline.py:13`).
- `g_slope` delivers **streamwise incidence, nose-up positive**; internally
  incidence = −dz/dx (`aero/spline.py:312, 382`).
- Displacement transfer: structure → aero at collocation (slope) and force point
  (displacement); **loads return by the virtual-work transpose** — any force map must be
  the transpose of a physically meaningful displacement interpolation.
- Rigid-attach rotation rows are generalized to the box normal: Ry: +n_z, Rz: −n_y,
  Rx: 0 (DEF-H1; `aero/spline.py:389-392`).

## 5. Trim and maneuver states

- **ANGLEA/SIDES in radians.** PITCH/ROLL/YAW are reduced rates qc/2V, pb/2V, rb/2V —
  the scales are owned by `rigid_rate_scales` (§8).
- **ANGLEA = α, nose-up positive** (freestream taken as `U∞·[1, β, α]`, theory Eq. 10a) —
  matches the textbook. **SIDES is the freestream's +y (starboard-pointing) velocity
  fraction: positive SIDES = wind from the PORT side = `−β` in the textbook convention**
  (`aero/integration.py:365-367`, theory §2 Eq. 10a). Nothing else in the code or decks
  flips this back — read `C_yβ`/`C_nβ`/`C_lβ` from `sol144_derivs.py` with both this and
  the §1 axis reversal in mind.
- **Rate-label senses** (figure `../figures/maneuver_rates.svg`): positive PITCH =
  nose-up q (textbook); positive ROLL = starboard-wing-down (right roll); positive YAW =
  nose-starboard (right yaw) (`aero/integration.py:369-387`). ROLL and YAW are thus
  right-handed about the **nose (−x)** and **down (−z)** directions — the opposite
  handedness of CMX/CMZ (§1). The ROLL column has **no spanwise reference**: it is always
  about the deck's y = 0 plane, unlike PITCH (RCSID-origin `x_ref`) and the yaw-drag
  force term (`y_ref = suport_pos[1]`).
- Plunge-rate sign: α = θ − ḣ/V, so the DOF-3 rate column is −ANGLEA/V
  (`aero/integration.py:185-194`). **⚠ Known defect (DEF-M15):** the same
  relative-wind negation is *missing* from the DOF-2/4/6 entries of
  `rigid_rate_scales` (`aero/integration.py:160-162`) — latent while free-flight scope
  is symmetric-only; do not cite those scales as a convention until it is resolved.
- **Load factor: `URDD3 = −n_z·g` authored in the RCSID frame** (1g level flight = −g;
  2.5g pull-up = −2.5g); gravity is folded into the load factor
  (`model/maneuver_presets.py:24-38`). **This presumes a z-DOWN (stability-axes) RCSID**,
  which every shipped aircraft deck uses (`sample/HA144A.bdf:187-188`,
  `sample/cessna210_flagship_bulk.bdf:80-82`) — the URDD rotation to basic z-up turns −g
  into an upward +g reaction and positive trimmed lift. With RCSID absent or z-up, the
  same value is a genuinely downward acceleration and trims **inverted lift**
  (`sample/val_dihedral_trim.bdf` does exactly this, deliberately — see its
  header). *A 2026-08-04 charter note claiming the `maneuver_presets.py:25` "(RCSID
  z-down)" docstring was misleading was itself wrong and is retracted (2026-08-09); the
  docstring is correct.* **DEF-M20 closed 2026-09-05 (issue #23, with #1):**
  `_stage_resolve_ref_geometry` (`solver/sol144.py`) now warns when a prescribed
  negative `URDD3` meets an absent or z-up RCSID, so the case is loud rather than
  silent; `val_dihedral_trim.bdf` is expected to warn. Gate: `V-GUST7`
  (`tests/aero/test_gust_cases.py`).
- **Gust load factors (FAR/CS 23.341) enter through the same helper.** A `GUSTLF`
  card carries a dimensionless load factor `N` and prescribes `URDD3 = −N·G` via
  `load_factor_to_urdd3`; a down-gust with `N < 0` therefore prescribes a **positive**
  `URDD3`, which is correct and is not what DEF-M20 guards. **Decision (2026-09-05,
  issue #1):** the lift-curve slope in the Pratt formula is the **rigid** `CZ_α` —
  the body-axis normal-force slope, which is the regulation's `C_NA` (§2), not
  wind-axis `CL_α`. Pratt is a rigid-airplane derivation in plunge, so an elastic
  slope would mix a flexible quantity into a rigid-body formula whose empirical
  constants were calibrated on the rigid basis; `K_g` alleviates rigid-body plunge
  during gust penetration plus unsteady lift growth, and is **not** a
  structural-flexibility correction. The whole dimensional calculation lives outside
  the solver in `scripts/gust_load_factor.py` (§7).
- **URDD labels are the only trim labels rotated RCSID→basic** (`sol144_util.py:54-121`);
  the aero labels (ANGLEA/SIDES/rates) never rotate. Under the standard z-down RCSID,
  authored URDD4/5/6 are therefore textbook stability-axis angular accelerations
  (roll-right, nose-up, nose-right positive) while the rate *labels* follow the bullet
  above — an easy place to mix frames; do not equate URDD4 with ROLL's axis.
- Inertial columns: `M_ax[:,k] = −M_gg·φ_r[:,dof(k)]` about the SUPORT point — **one
  mass model** (Q4/DEF-M3; `solver/sol144_util.py:166-177`).
- `NZ_REL = URDD3_basic(t)/URDD3_basic(t0)` (equals n_z in g for a 1g initial
  condition).

## 6. Control surfaces

- **Hinge axis = the cid1 CORD2R y-axis** (`aero/integration.py:402`) — not x. (The
  x-axis mis-documentation once produced an identically-zero elevator column.)
- Positive deflection is **lift-increasing** — a right-handed rotation about the cid1 +y
  axis, i.e. trailing-edge-down for a spanwise (+y) hinge. Deflections in radians
  (flat-plate column, same units as ANGLEA) (`aero/integration.py:334-336, 393-409`).
- Hinge moment: `HM = Σ_{j∈AELIST} [(r_j−o)×F_j]·ĥ`, in force/q units, about the same
  cid1 +y axis as positive deflection (`solver/sol144_derivs.py:114-125`).
- **Elevator (the only surface any deck defines, always labelled `ELEV`):** positive =
  TE-down. On the Cessna aft tail that is **nose-down** (the 2.5g gate trims more
  TE-up, `tests/aero/test_cessna210_flagship.py:259-266`); on the HA144A canard
  (surface forward of the CG) positive is nose-up. "Positive elevator" has no
  airframe-independent pitch sense — only the lift-increasing rule is universal.
- **GAP — aileron and rudder:** no deck, doc, or test defines either. The sign a rudder
  or aileron gets is entirely set by how the deck author orients cid1 +y; nothing
  validates the intent. An antisymmetric aileron pair currently requires two AESURF
  labels: **`CID2`/`ALID2` are parsed and validated but silently ignored by
  `build_djx` and the hinge-moment sum** (DEF-M16; `aero/integration.py:403`,
  `solver/sol144_derivs.py:133-136`), so the NASTRAN second-half mechanism loads
  nothing.

## 7. Units

- **Preprocessing tools may know units; the solver may not (2026-09-05, issue #1).**
  This rule binds `sbeam/` — card fields and solver arithmetic. Tools under
  `scripts/` that *generate* decks are outside it, and are where dimensional
  regulatory content belongs: `scripts/gust_load_factor.py` owns the ISA atmosphere,
  the FAR/CS 23.333(c) `U_de` schedule in feet, and `ρ₀`, then hands the solver a
  dimensionless load factor on a `GUSTLF` card. Nothing dimensional crosses the
  boundary. Prefer this split to adding a unit-aware field.
- **User-defined consistent units throughout** — sbeam never converts. The two deliberate
  exceptions (card-field degrees → stored radians): CHORDCP `alpha_ref`
  (`model/aero.py:119`) and its tolerance constant `_CHORDCP_ALPHA_TOL = 0.035 rad`
  (`solver/sol144.py:174-175`). Do not add new unit-converting fields without recording
  them here.

## 8. Single-source helpers (use these; never re-derive)

| Helper | Owns | Where |
|---|---|---|
| `pitch_moment` | The nose-up-positive pitch arm (AE1 Step E) | `solver/sol144_util.py:255` |
| `aero_moment_resultant` | Full 3-component moment about a reference (Step 58) | `solver/sol144_util.py:280` |
| `rigid_rate_scales` | PITCH/ROLL/YAW rate nondimensionalization | `aero/integration.py:143` |
| `load_factor_to_urdd3` | The load-factor → `URDD3` sign (`−n_z·g`), for maneuvers and gusts alike | `model/maneuver_presets.py:24` |
| `mass_ratio` / `alleviation_factor` / `gust_increment` | The Pratt gust formula (μ, `K_g`, Δn). Deliberately **outside** the solver — dimensional, see §7 | `scripts/gust_load_factor.py` |
| `build_box_id_map` | The NASTRAN box-ID derivation (F1) | `aero/panel.py:43` |
| `build_wg` / card writers | W2GJ sign flip (assembly negates; writers negate back) | `aero/integration.py:61`, `model/aero.py:88` |

When a new sign-sensitive quantity appears, create its single-source helper first and add
it to this table.

## 9. Internal loads, section cuts and output signs (extraction 2026-08-09)

Figure: `../figures/sign_conventions_internal_loads.svg`; cut geometry:
`../figures/section_cut.svg`.

- **CBAR force recovery is the raw element-frame `K·u` 12-vector**
  (`solver/sol101.py:73-125`; same routine feeds SOL 144 and the transient). Reported
  components: axial/shear1/shear2/torque are the **end-B** nodal values — axial
  tension-positive, shears along local +y/+z, torque right-handed about local +x. The
  end-A `Fx` is the negated reaction and is deliberately not used
  (`sol101.py:155-156`). Element local frame: `e_x = GB−GA`, `e_y` from the orientation
  vector, `e_z = e_x × e_y` (`assembly/stiffness.py:99-122`).
- **⚠ End-A bending moments `bm1_a`/`bm2_a` are reported raw** — no statement anywhere
  fixes which face they are on (the end-B trap called out for axial is not applied to
  them). **⚠ f06 plane labels are internally inconsistent and half-swapped vs MSC:**
  `SHEAR-1 = Fy` matches MSC plane 1, but `BENDING-1 = My` is MSC's plane **2**
  (DEF-M18; `sol101.py:117-124`). Do not map an MSC-trained f06 parser onto sbeam
  columns without checking.
- **MONSECT/section-cut sign = the CBAR end-B sign, with no flip:** the cut reports the
  resultant of all applied loads (aero + inertia + reaction, each column signed alike)
  on the **outboard** side, about the cut plane's axis intercept, rotated into the cut
  CID frame; on-plane grids count inboard so a cut at a node equals the CBAR internal
  force there (`results/section_cuts.py:184-263`, gate
  `tests/aero/test_section_cuts_sol144.py:68-93`). Closed-form anchor: tip load +P in
  +z gives `Vz = +P`, `Mx = +P(L−s)` (`tests/results/test_section_cuts.py:51-72`) — so
  on an up-loaded right wing, **Vz and Mx are positive at the root and decay to the
  tip**. **Never** apply symmetry parity to a cut; a half-model cut is already the
  per-side load. MONPNT1/MONPNT3 *do* carry parity (Fx/Fz/My doubled, Fy/Mx/Mz zeroed
  when SYMXZ; `results/monitor_points.py:29-65`).
- **Shear/moment/torsion diagrams plot the raw signed values** — station on the x-axis,
  no engineering-diagram inversion, no sagging/hogging re-orientation
  (`viewer/results_view.py:515-538`). The sign you read off the plot is the section-cut
  sign above.
- **SPCFORCE = the force the constraint applies to the structure**
  (`R = K·u − f_applied` at the SPC DOFs, `solver/sol101.py:221-264`). Stored in basic;
  **printed in the grid CD frame** (Q1) — so the f06 SPCFORCE block and the monitor
  reaction column (which consumes the stored basic vectors) can differ in frame on a
  CD≠0 model. **⚠ OLOAD prints only a GRAV echo today** — no applied-load block exists
  (DEF-M19).
- **Applied loads are used exactly as authored** (FORCE/MOMENT/GRAV: no hidden sign,
  right-hand rule about the given axis, GRAV direction vector must itself point down;
  `assembly/load_vector.py:20-81`). Exported FORCE/MOMENT trim loads are physical CID-0
  loads, verbatim (`results/load_export.py:45-63`).
- **⚠ CONM2 products of inertia are the direct tensor entries, POSITIVE off-diagonals**
  — `I_cid = [[i11,i21,i31],[i21,i22,i32],[i31,i32,i33]]`
  (`assembly/mass_matrix.py:130-134`, gated `tests/aero/test_trim_urdd.py:265-279`).
  **This is the opposite of MSC NASTRAN**, whose CONM2 fields are the *negated*
  products; a NASTRAN deck with nonzero I21/I31/I32 imports with flipped inertia
  coupling. Single source for the field meanings: `02_card_reference.md` (CONM2).

## 10. Engines and powered effects

- **There is no propulsion model of any kind** — no thrust, engine-torque, gyroscopic,
  or slipstream term exists in code (Known Limitations,
  `00_program_overview.md`). Powered aero enters **only** through the ordinary
  correction cards (W2GJ/WT2/CHORDCP + body TOTAL rows) built from powered data —
  the "corrections position", theory `02_realistic_airplane_sol144.md` §7.
- **Thrust cannot enter a SOL 144 trim:** a subcase with both `TRIM` and `LOAD` raises
  (DEF-M4 guard, `solver/sol144.py:314-325`); the restrained static path is the
  workaround. Follow-on backlog item: applied structural load in the trim RHS.
- **GAP — propeller handedness:** no convention anywhere fixes which sign of swirl
  correction corresponds to which rotation direction; the user tabulates per-strip
  signs by hand (theory §7). Engine torque / gyroscopic case sets (23.361/.363) are
  declared out of scope (`30_future/02_parked.md`).

## 11. Convention figures

| Figure | Depicts |
|---|---|
| `../figures/sign_conventions_state.svg` | Basic frame vs textbook axes; α, SIDES(−β), rate-label senses, control deflection |
| `../figures/sign_conventions_internal_loads.svg` | CBAR end-B recovery signs; section-cut face and SMT-diagram signs |
| `../figures/maneuver_rates.svg` | Rate downwash mechanisms (q, p, r) |
| `../figures/section_cut.svg` | MONSECT cut plane, reference point, component labelling |

These four figures are the required sign-convention appendix of the future TeX/PDF
critical-case loads report (backlog item "Loads envelope & critical-case report").
