# sbeam — Development Backlog

Authoritative backlog of **open** work only, in priority order. Updated as part of every
session that completes a step — never deferred. Completed steps live in
`docs/40_history/`; nothing closed is summarised here. Items not on the mission path live
in `02_parked.md` — real but unscheduled; move them back here (with a mission tag) before
working them.

**Numbering rule (2026-08-04):** items are identified by name while open; a plain
sequential step number is assigned only at promotion to a formal step (next free number is
**Step 69**). No parallel numbering systems — the historical P-ranks and A/AC/AE letters
are retired; dated references to them resolve via `docs/40_history/`.

---

## Mission (2026-08-04)

**A FAR/CS-23-style loads process on a beam-stick aeroelastic model:** generate the
maneuver + gust design cases from the flight envelope, trim/integrate each one, and
deliver monitor/section loads with a traceable critical-case report for downstream stress
work. Delivered so far: SOL 144 trim + derivatives, balanced maneuvers, MASSSET payload
sweeps, quasi-steady + free-flight modal transient maneuvers (MLOADS), monitor points and
section-cut running loads with per-maneuver envelopes, and correction-matched aerodynamics
validated on HA144A and an ATR42-class flagship. **SOL 145 flutter + DLM (Phase D)
remains the declared phase after loads sufficiency.**

Every item below carries a mission tag: **[E]** essential to the mission path,
**[V]** valuable (fidelity/usability, not blocking). The 2026-08-02 release-scope
decisions stand (see `docs/40_history/06_sol144_static_aeroelastic.md`): quasi-steady
maneuvers in scope, lateral cases in scope, powered effects via correction cards,
corrected body panels adequate, dynamic (DLM) gust out of scope until Phase D.

---

## Priority order

**Near term — completes the loads process (each item small/medium):**

1. **[E] Quasi-static gust cases (Pratt, 23.341)** — the missing mandatory load cases;
   fits the existing balanced-maneuver machinery. See body below.
2. **[E] `MONPNT1`/`MONPNT3` on transient maneuvers** (~0.5 d) — Step 68 follow-on;
   enabling work done, only the output surface is missing. See body below.
3. **[E] Transient `net_loads` elastic-inertia decision** (~0.5–1 d) — quantify, then
   decide with gates. See body below.
4. **[E] V-n / design-case matrix generation** — generate the maneuver+gust case set from
   the envelope instead of hand-authoring decks. See body below.
5. **[E] Loads envelope & critical-case report** — cross-case envelope + traceability
   table; the deliverable a stress office consumes — now including the TeX/PDF report
   with its sign-convention appendix. See body below.
6. **[E] Applied structural load in the SOL 144 trim RHS (DEF-M4 follow-on)** — thrust
   cannot enter a trim today; undecided physics. See body below.
7. **[V] DEF-M14 — nonplanar Trefftz `CDi` kernel** (~1–2 d) — last open correctness
   defect; reporting-only outputs. See body below.
8. **[E] DEF-M15 + DEF-M16 — lateral sign chain** — `rigid_rate_scales` DOF-2/4/6 signs
   and the ignored `AESURF CID2/ALID2`; both must close before any aileron/rudder
   (lateral) case is trusted. See bodies below (filed 2026-08-09, sign-convention
   review).

**Phase D — flutter + dynamic gust (the declared next phase, in dependency order):**

9. **[E] `matrix_gaf_export` Phases 1–2** (~8 d) — external flutter handoff and the
   declared prerequisite of the DLM (MKAERO1, Mach loop, bundle writers).
10. **[V] `AMODE` Phase 1 — control-surface hinge modes** (~7.5 d) — before
    control-surface flutter; Phase 2 is a declared pre-1.0.0 blocker.
11. **[E] Phase D core — DLM (D0–D3) + SOL 145 PK flutter** (~25–30 d).
12. **[E] Phase D cont. — RFA state-space + SOL 146 dynamic gust + Monitor Phase 3**
    (~15–20 d) — CS-25.341-style discrete gust / continuous turbulence; completes the
    dynamic loads process.
13. **[E] `matrix_reuse_store` Phases 1–3** (~6 d) — worthwhile once envelope sweeps grow
    (the Mach dimension arrives with the DLM).

**Opportunistic (small, independent, do when adjacent):** DEF-L re-triage; G0-d unsteady
corrections (conditional — superseded by the DLM); `CD0` profile drag; body-lift
constraint (`BodyTargets` CZ); `SPLINEF` distributed force-mapping spline; DEF-M17–M20
+ the sign-wording hygiene batch (2026-08-09 sign-convention review, bodies below).

**Required convention decisions** (aileron/rudder signs, end-A moment face, prop
handedness, bank-angle scope, ROLL reference) are indexed in their own section below —
each is made in the design note of the first step that consumes it, never invented
ad hoc.

---

## Open defects

### DEF-M14 — `trefftz_cdi` uses a planar-wake formulation on nonplanar wakes [V] [E-evidence]

`sbeam/aero/vlm.py` `trefftz_cdi`. The far-field integral is
`Di = ρ/2 · Σ Γ_i · w_z,i · Δy_i` — the **z-component** of the induced velocity against a
cross-flow-projected width. For a genuinely nonplanar wake (dihedral, winglets, a
cruciform tail) the correct kernel is the wake-normal component, `Σ Γ_i (w⃗_i·n̂_i) ‖Δs⃗_i‖`,
and the induced velocity has a `v_y` component the current form ignores entirely.
Raised (not fixed) during DEF-M2, 2026-08-01: DEF-M2 corrected the force *convention*,
and `CL_l` inside `trefftz_cdi` was projected with it so the documented identity
`CDi = CZ²/(π·AR·e)` holds — but the `Di` integral itself is a separate physics question,
not a convention slip, so it was deliberately left alone rather than changed silently.
Affects `CDi` and `e` on canted decks only; both are reporting-only outputs (no solver
or trim path consumes them). *Fix (complexity medium):* rebuild the Trefftz kernel on
`(w⃗·n̂)‖Δs⃗‖`; gate against a closed-form elliptic-wing case with and without dihedral,
and against a winglet case where the planar form is known to be wrong.

### DEF-M4 follow-on — applied structural load in the SOL 144 trim RHS [E]

DEF-M4 (closed 2026-08-01) made a subcase carrying both `TRIM` and `LOAD`
raise rather than silently ignore the load, and its close-out recorded that adding an
`f_struct` term to the trim RHS "is now its own backlog item" — it was never filed;
logged here 2026-08-03 while writing the propeller-effects docs, which is where the gap
bites. Today the trim RHS is aerodynamic + inertial only, so **thrust cannot be applied
in a trim** at all: a powered deck must either fold the thrust-line moment into a
correction `cm0` (where it wrongly scales with `q` instead of thrust) or drop to the
restrained static path and give up free-flight trim. *Undecided physics, which is why it
is a capability change and not a defect:* on a free-flight SUPORT trim an applied load
enters the force balance, so `maneuver_closure` stops meaning "aero vs inertia", and
whether the applied load participates in inertia relief is an open question. Complexity
medium. See `docs/20_theory/02_realistic_airplane_sol144.md` §7.2.

### DEF-L2–L7 — low-severity batch, **bodies never recorded — re-triage required** [V]

The 2026-07-31 review closed out with these six findings named but their write-ups were
never captured in any document (confirmed 2026-08-04): L2 extrapolation advisory,
L3 SUPORT-drop diagnosis, L4 viewer Cp/span-load, L5 f06 presentation, L6 docs-mismatch
batch (partially struck during later doc work), L7 SYMXZ parity decision. Before any are
worked, re-derive each finding from the code (~1–1.5 d total for the batch as originally
estimated). Lesson recorded in `07_code_review_process.md`: review findings must be filed
with bodies in the same session they are raised.

### DEF-M15 — `rigid_rate_scales` DOF-2/4/6 signs inconsistent with the basic-frame rigid vectors [E]

`aero/integration.py:160-162` maps physical rigid-DOF rates to trim-label values as
`{2:+1/V, 4:+b/2V, 6:+b/2V}`, but the rigid DOFs are right-handed about **basic** x/y/z
(`assembly/rigid_body.py:57-71`) while the labels' positive senses are wind-relative:
sway +y (aircraft toward starboard) is *negative* SIDES, rate about basic +x
(starboard-wing-up) is *negative* ROLL, rate about basic +z (nose-port) is *negative*
YAW — exactly the relative-wind negation DOF 3 already carries (`−1/V`, α = θ − ḣ/V) and
DOF 5 doesn't need (pitch senses coincide). Verified analytically 2026-08-09
(sign-convention review). Because `B_hh` uses these columns on the input side against
the true `Φ` on the force side (`solver/modal_basis.py:672-681`), a free-flight lateral
rate would receive **anti-damping**. Latent today: free-flight scope is symmetric-only
(the deliberate `disp=None` lateral caveat, `modal_basis.py:113-117`), and the closure
test gates the scales only against themselves (`tests/aero/test_integration.py:292-303`).
*Fix:* negate DOFs 2/4/6, gate each lateral scale against an independent relative-wind
derivation, and per the generalize-on-first-find rule sweep every consumer of
`rigid_rate_scales`. Must close before lateral free-flight or aileron/rudder cases.

### DEF-M16 — `AESURF CID2`/`ALID2` parsed, validated, then silently ignored [E]

The second hinge/AELIST pair — NASTRAN's mechanism for the opposite half of an
antisymmetric aileron pair — is stored (`model/aero.py:213-214`), cross-checked
(`parser/bdf_reader.py:1644-1645`) and written back out (`model/card_writers.py:63-64`),
but `build_djx` uses only `alid1`/`cid1` (`aero/integration.py:403`) and so does
`compute_hinge_moments` (`solver/sol144_derivs.py:133-136`): the second surface half
loads nothing and produces no hinge moment, with no warning. *Fix:* either implement the
second pair in both consumers or refuse the fields loudly at parse; add a deck-level
aileron sample + sign gate when implemented (no aileron convention exists anywhere —
see `09_conventions.md` §6 GAP). Blocks the steady-roll preset ever running.

### DEF-M17 — pin releases (`PA`/`PB`) ignored in CBAR force recovery [V]

`_element_local_forces` (`solver/sol101.py:92-100`) calls `local_stiffness` directly,
while assembly applies `apply_pin_releases` (`assembly/stiffness.py:161-163`). On a deck
with pin flags, recovered end forces are non-zero at released DOFs and inconsistent with
the solved displacements; feeds SOL 101 f06/stress, SOL 144 and the transient recovery.
No test covers `bar_forces` with pins (`tests/assembly/test_pin_releases.py`). *Fix:*
recover with the released local stiffness; gate a pinned cantilever against the
closed-form released end force.

### DEF-M18 — CBAR f06 plane labels internally inconsistent and half-swapped vs MSC [V]

`SHEAR-1 = Fy` matches MSC plane 1, but `BENDING-1 = My` is MSC's plane **2**
(`solver/sol101.py:117-124`): shear and bending use opposite plane numbering in the same
output row, and an MSC-trained f06 parser mis-maps two columns. Additionally the end-A
moments `bm1_a`/`bm2_a` are the raw nodal `K·u` values with the face never stated
(contrast the explicit end-B rule for axial, `sol101.py:155-156`). *Fix:* decide the
labelling (MSC-consistent preferred), state the end-A face convention in
`09_conventions.md` §9 and `03_static_analysis.md`, and gate against a hand-checked
cantilever in both planes. Documented as a ⚠ caveat in `09_conventions.md` §9 and
`sign_conventions_internal_loads.svg` until fixed.

### DEF-M19 — OLOAD prints only a GRAV echo; the promised applied-load block is missing [V]

`OLOAD` is parsed (`parser/case_control.py:19,138`) and offered in the viewer, and
`03_static_analysis.md:213` documents an "Applied Load Vector (OLOAD)" f06 section — but
`results/f06_writer.py:321-340` emits only a GRAV card echo; no applied-load vector or
resultant exists. *Fix:* either write the block (echo of the assembled load vector in
basic, plus a resultant) or strike the doc claim; align the doc either way.

### DEF-M20 — `URDD3 = −n_z·g` has no RCSID-orientation guard [V]

The load-factor sign presumes a z-DOWN (stability-axes) RCSID, which every shipped
aircraft deck uses; with RCSID absent or z-up the same TRIM value is a genuinely
downward acceleration and silently trims **inverted lift**
(`sample/val_dihedral_trim.bdf` does it deliberately). *Fix:* warn when a TRIM subcase
prescribes negative URDD3 while the AEROS RCSID basic-frame z-axis points up (or RCSID
is absent), with a pointer to `09_conventions.md` §5. Filed from the 2026-08-09
sign-convention review, which also retracted the erroneous 2026-08-04 charter note that
called the `maneuver_presets.py:25` "(RCSID z-down)" docstring misleading — the
docstring is correct.

### Sign-wording hygiene batch (2026-08-09 review) [V]

Four Tier-S items, each a wording/labelling fix with no behavior change; close together:

1. **Flagship "Nose-up pull" comment is backwards** — `sample/cessna210_flagship_bulk.bdf:465`
   (and its echo `tests/aero/test_cessna210_flagship.py:393`) calls a **+2 deg** ELEV
   ramp a nose-up pull; the deck's own trim gate proves +ELEV is nose-down on this aft
   tail (`test_cessna210_flagship.py:259-266`). The transient Fz rises only because the
   quasi-steady run is l-set restrained. Reword to "elevator TE-down step (restrained:
   tail-lift increase)".
2. **GUI labels the steady-roll preset "rad/s"** (`viewer/sol144_authoring.py:194`) but
   ROLL is the nondimensional `pb/2V`.
3. **Preset `PITCH = 0` pull-up guidance contradicts the flagship reference deck** —
   a steady pull-up carries `PITCH = (n−1)·g·c/(2V²)` (`cessna210_flagship_bulk.bdf:436-441`);
   align `model/maneuver_presets.py` docs/GUI guidance (and note push-over needs the
   negative rate).
4. **ROLL column has no spanwise reference** — always about y = 0
   (`aero/integration.py:374-377`), unlike PITCH (`x_ref`) and the yaw force term
   (`y_ref = suport_pos[1]`); decide whether that is intended (document) or should use
   `suport_pos[1]` (behavior change → M-tier).

---

## Required convention decisions (2026-08-09 sign-convention review)

Gaps where **no convention exists and one must be deliberately chosen** — nothing was
invented during the review (`09_conventions.md` flags each as GAP). Per charter rule 1
each decision is made in the design note of the first step that consumes it, and per
charter rule 3 it then lands in `09_conventions.md` with a gate that pins it. Decisions
are listed with the item that forces them:

1. **Aileron sign convention** — decide with **DEF-M16 / the first aileron deck**.
   What "positive aileron" means for an antisymmetric pair (which half is TE-down) and
   which roll direction it commands, plus how the pair is authored (one AESURF with
   CID2/ALID2 vs two labels). The generic lift-increasing rule cannot answer this — it
   gives each half its own sign. Candidate: NASTRAN's CID2 mechanism with positive
   deflection = right-roll command (starboard TE-up / port TE-down); decide against the
   validation target (a C_lδa closed form or AVL run). Charter §6 entry + sign gate
   required at closure.
2. **Rudder sign convention** — decide with **the first rudder deck** (steady-sideslip /
   lateral trim cases). The hinge rule fixes the sign only once the cid1 +y orientation
   is chosen (up vs down flips it). Candidate: cid1 +y UP so positive rudder = TE-port =
   nose-left force couple; must be stated against the textbook δr sign in the same
   charter entry because SIDES already carries the −β flip (§5).
3. **CBAR end-A bending-moment face** — decide inside **DEF-M18**. Whether
   `bm1_a`/`bm2_a` report the internal moment on the A-face (MSC-consistent, negated
   `K·u`) or stay raw nodal values with the face documented. MSC-consistent preferred;
   either way charter §9 and `03_static_analysis.md` state it and a two-plane cantilever
   gate pins it.
4. **Propeller handedness / swirl tabulation** — decide with **the first powered
   correction deck** (corrections position, theory §7). A charter rule mapping rotation
   direction (viewed from behind) → the sign of the per-strip `a0`/W2GJ swirl increments
   on each side of the nacelle, so co-rotating vs handed twins are authored consistently.
   Blocks nothing today; required before any powered validation case.
5. **Bank-angle / turn-coordination scope** — decide with **the V-n / design-case matrix
   item** (which enumerates the lateral certification cases). Today no attitude angle
   exists (DOF-4/6 `disp` slots deliberately `None`, `modal_basis.py:113-117`) and
   gravity never tilts: a coordinated-turn or steady-heading-sideslip case cannot be
   posed. Decide whether the CS/FAR-23 lateral case set needs a gravity-tilt/bank term
   in trim (new physics, L-tier + design note) or is served by the existing
   ROLL/YAW/SIDES labels; record the decision either way (build it, or move the case
   family to `02_parked.md` with the reason).
6. **ROLL spanwise reference point** — hygiene batch item 4 above; decide document-vs-fix
   before DEF-M15 closes (the two touch the same column and should be swept together).

---

## Item bodies — near term

### Quasi-static gust cases (Pratt formula, FAR/CS 23.341) [E]

**Objective:** the certification vertical-gust load factors as balanced-maneuver load
cases, with no DLM dependency. `n = 1 ± k_g·ρ₀·U_de·V·a·S / (2W)` with gust alleviation
factor `k_g = 0.88μ/(5.3+μ)`, mass ratio `μ = 2(W/S)/(ρ·c̄·a·g)`; lift-curve slope `a`
taken from the model's own trimmed `CZ_α` (rigid or elastic-restrained — decide and
document which, per 23.341's intent this is the airplane slope). Gust speeds `U_de` per
23.333(c) at V_C and V_D, with altitude schedule.
**Deliverables:** a gust-case generator producing the ±U_de pairs at each (V, W, altitude)
point as standard Step-53 balanced-maneuver subcases (`TRIM` with the computed Nz); f06
echo of μ, k_g, U_de and the resulting n per case; sample deck on the flagship.
**Test/acceptance:** hand-checked μ/k_g/n against the worked example in the FAR-23
guidance material for a known W/S; gust cases flow through monitor/section loads and the
envelope like any maneuver case. **Effort:** S–M (days). Design note + conventions-charter
citations required before code (physics step).

### MONPNT1/MONPNT3 on transient maneuvers [E]

Step 68 follow-on (~0.5 d). The per-sample integrand inputs (`box_forces`, `grid_loads`,
`inertial_loads`, reactions, and the elastic/damping columns) all exist inside
`recover_step`. Missing is only the monitor output surface: a per-sample `MonitorLoad`
dict, an f06 block at the critical sample and a maneuver monitor CSV.

### Transient `net_loads` elastic-inertia decision [E]

(~0.5–1 d, decision + gates.) `ManeuverStep.net_loads` is aero + **rigid** inertia. The
elastic d'Alembert load `−M·ü_e` is recovered alongside it (Step 68) but kept separate,
because folding it in would simultaneously move the exported `maneuver_qs_loads.bdf`
cards, the closure diagnostic and the DEF-M5 critical-sample selection. Physically it
belongs in the export — a stress model consuming those cards should see the whole applied
load. Quantify the difference on the flagship deck first, then decide with gates. Note
the interaction: changing `net_loads` also changes which sample is "critical".

### V-n / design-case matrix generation [E]

**Objective:** stop hand-authoring the case set. From design speeds (V_A/V_C/V_D), design
weights (`MASSSET` list), cg positions and altitudes, generate the maneuver corner points
(n_max/n_min per 23.337 category limits) and the Pratt gust points (item above) as an
exported case-control BDF — one subcase per case with systematic SID/labeling, ready for
the existing multi-subcase run and monitor/section machinery.
**Deliverables:** case-matrix generator (input: a small envelope-definition card or CSV;
output: driver BDF + a case-index table); viewer authoring surface can follow later.
**Test/acceptance:** generated matrix for the flagship reproduces a hand-built reference
set; every case runs end-to-end. **Effort:** M. Depends on the gust item for the gust rows
(maneuver rows do not need to wait).

### Loads envelope & critical-case report [E]

**Objective:** the cross-case deliverable a stress office consumes. Step 68 already
envelopes per-station loads *within* one maneuver; extend across **all subcases and mass
cases of a run**: per-station / per-monitor max/min with the driving case identified
(case label, mass case, time sample where transient), plus a critical-case summary table.
**Deliverables:** cross-case envelope CSV + f06 block; case-traceability columns on the
existing section/monitor CSVs; **a TeX → PDF critical-case report** (requirement added
2026-08-09) whose front matter **must include a sign-convention appendix embedding the
four convention figures** (`docs/figures/sign_conventions_state.svg`,
`sign_conventions_internal_loads.svg`, `maneuver_rates.svg`, `section_cut.svg` — see
`09_conventions.md` §11) so every table in the report is readable without the code. The
parked "load-case envelope viewer" idea is this item's viewer face and stays parked until
the data product exists.
**Test/acceptance:** on a generated case matrix, the envelope reproduces the by-hand
max/min of the per-case CSVs, with correct driving-case attribution; the PDF builds in CI
and carries the appendix. **Effort:** S–M for the envelope data product
(builds on `results/section_envelope.py`); the TeX report is its own L-tier design note
(report generator = new capability) before code.

---

## Item bodies — Phase D chain

### matrix_gaf_export — matrix / GAF export bundle [E]

Per `designs/matrix_gaf_export.md` (viable): `EXPORT` case-control command
writing sparse `K_gg`/`M_gg`, dense a-set `K_aa`/`M_aa`, `PHIA`/`PHIG`, modal `K_hh`/`M_hh`,
and per-Mach steady GAFs `Q_hh(M)` on one fixed Φ (Matrix Market + `.mat`, manifest +
dofmap); new `MKAERO1` card; Mach-tagged corrections. Phases 1–2 (~8 d). Unblocked —
Step 59 closed (reuses `assembly/reduction.py:reduce_to_aset`); schedule before the DLM
(which extends its MKAERO1/Mach-loop machinery). Its stated AE4 prerequisite is stale —
closed by AC7. Phase 3 (OP3/UF writers) deferrable.

### AMODE Phase 1 — control-surface hinge modes [V]

Per `designs/amode_card.md`: `AMODE` card adding a generalized rotation DOF `q` for a SET1
grid group about a CORD2R hinge axis against stiffness `k`, via a transformation composed
after the RBE reduction (mirrors the proven `rbe3.py` path); f06 participation table.
Schedule before control-surface flutter work in the DLM step (~7.5 d). Phase 2 (elastic
rotating set) is a declared pre-1.0.0 blocker, target after Phase D core. Open interaction
to resolve at implementation: the augmented `q` DOF vs the Step 61 free-free basis solve.

### Phase D core — DLM (D0–D3) + SOL 145 PK flutter [E]

Per `designs/dlm_rfa_flutter_gust.md` (viable): complex unsteady AIC
`A_jj(M,k)` (Landahl kernel, Laschka approximation, parabolic spanwise quadrature),
**anchored so `D(M,0) ≡ D_VLM(M)` to machine precision** (the load-bearing de-risking
decision — the entire steady content reuses the validated VLM); complex GAFs `Q_hh(M,k)`
over a Mach×k table (extending `matrix_gaf_export`'s MKAERO1/Mach loop); `sol145.py` PK
(primary) / PKNL / KE flutter with V-g/V-f output. Gates: Blair 3×3 kernel benchmark
(0.1%), k=0 GAF cross-check, typical-section flutter closed-form. **Prerequisites:**
`matrix_gaf_export`; `g_disp_colloc` (¾-chord displacement spline) added at D0; the doc's
AE4 gate is stale (closed by AC7). Planar-only ships first — the nonplanar kernel terms
(T1/T2, I2) are a genuine research gap correctly walled behind their own gate. ~25–30 d.

### Phase D cont. — RFA state-space + SOL 146 gust + Monitor Phase 3 [E]

Roger-form RFA + aeroelastic state-space (`rfa.py`); `sol146.py` discrete 1-cosine gust
(Fourier method) and continuous Von Kármán/Dryden turbulence (Ā/N₀). **Monitor points
Phase 3** lands here: discrete-gust gradient sweep and continuous turbulence at each
monitor, with correlated companion-load extraction — built on the Phase 1 monitor data
model. Together these complete the dynamic loads process. ~15–20 d.

### matrix_reuse_store — matrix persistence / dual-mode SOL 144 [E]

Per `designs/matrix_reuse_store.md` (viable, subordinated): persist `ajj_inv_corr`,
`skj/djk/wg`, box geometry, spline operators, sparse `KGG`/`MGG` to `.npz` bundles with
content-hash provenance; `DiskAeroCache(AeroCache)` reload path, default fresh-compute
bit-identical. Phase 0 deleted (already shipped with Step 56/AE10 + AC5). Phases 1–3
(~6 d) become worthwhile once envelope sweeps grow large (Machs × MASSSETs × maneuvers —
the maneuver × mass sweep exists since Step 63; the Mach dimension arrives with the DLM);
the cache-boundary rules (§4: cache pre-q, pre-reduction operands only, never
`Q_aa`/`K_eff`/LU) stand as written.

---

## Item bodies — opportunistic

### G0-d — unsteady corrections (Levels 2–4) [V, conditional]

Layer the analytic unsteady terms onto the steady VLM forcing as an ordered list of
optional `AeroIncrement` objects each contributing `(ΔM_hh, ΔB_hh, ΔK_hh)` and optional
appended states: (2) 2-D apparent (added) mass per strip (`πρb²` projected to `A_hh`,
plus the elastic-rate `B_hh` columns — the slot left in Step 61); (3) tail downwash-lag
delay `τ = l_t/V` (`C_mα̇`; ring buffer of delayed `D_jx`/`D_jξ̇` arguments); (4) strip
Wagner/Theodorsen lift-deficiency (per-strip 2-state R.T. Jones approximation appended to
the state vector). Selected by a new `MLDAERO` card (designed at promotion). Each
optional; extends validity beyond `k ≲ 0.05–0.1`. Acceptance sketch: Level 2 reproduces
2-D `πρb²` exactly on a single strip; Level 4 reproduces Wagner indicial lift to
Jones-approximation accuracy. **Conditional:** once the DLM is underway it supersedes
Levels 2–4 — implement only if transient-load fidelity beyond `k ≈ 0.1` is needed first.
(Residual G0 validity notes — TABLED1 rate discontinuities, linear inertial-frame
kinematics, absent control-surface inertia, SUPORT dependence — are documented in
`docs/10_standard/05c_sol144_maneuver.md`; the closed plan record is in
`docs/40_history/07_maneuver_transient.md`.)

### Profile drag input (`CD0`) — the other half of the wing C_nr [V]

Step 67b gives the wing an *induced*-drag yaw-damping term (`build_fx_induced_drag`); a
real airplane's profile drag contributes comparably, and sbeam has no viscous model. A
per-CAERO1 (or per-strip) `CD0` input would let the user supply it from drag polars /
CFD, added into the same streamwise field the yaw column already scales — small and
self-contained now that the field exists. Until then the omission is a documented Known
Limitation (theory §7.2, `05a_aero_vlm.md`) and biases C_nr low — the non-conservative
direction.

### Body correction matches moments but leaves body lift unconstrained [V]

Found during Step 66. `build_body_correction` / `build_strip_body_correction` solve for
Cm_α, Cm0, Cn_β, Cn0, Cl_β, Cl0 and say nothing about the body's own normal force, which
falls out of whatever slope the panels happen to carry. On the flagship at the `PSTRIP`
default `slope0` = π the strip body trims out carrying **11 % of the airplane weight** —
every total exact, the trim closed, and 11 % of the lift lifted off the wing. The deck
works around it by choosing `PSTRIP, 20, 0.35` by hand (2.2 % of weight, matching the
cruciform's 2.0 %), which is a deck-authoring fix for what is really an API gap.
**Proposal:** add an optional CZ0/CZ_α pair to `BodyTargets`. The horizontal-panel solve
already has two knobs (slope ratio and Δα offset) against two pitch targets; adding a
lift target makes it three constraints, so it needs either a third knob (per-box slope
distribution rather than a single joint ratio) or a documented least-squares trade. Until
then the guidance in `05a_aero_vlm.md` — *check what your body panels carry, not only
what they correct* — is the mitigation. Complexity low-medium; no new physics.

### SPLINEF — distributed force-mapping spline (ZAERO parity) [V]

Step 64 gave structurally-uncoupled boxes (`SPLINE0`, un-splined) a load path: their
6-component resultant is injected rigidly at **one** master grid (`SPLINE0` field 5,
default the SUPORT grid), via the `g_load` operator in `sbeam/aero/spline.py`.
**Gap:** a single application point is exact for the *global* balance but wrong *locally*
when the panel is long relative to the structure carrying it — correct trim, misleading
internal loads. Mitigation today is guidance plus the f06 `INJECTED AERO LOADS` echo.
**Scope:** a `SPLINEF` card naming a box range and a `SET1` of grids, distributing each
box force over the set by RBE3-style weights (`sbeam/assembly/rbe3.py` already computes
exactly those weights — reuse, don't re-derive). `SPLINE0` field 5 stays as the
single-grid shorthand. Keep the adjoint property: whatever maps force must be the
transpose of a physically meaningful displacement interpolation. **Caveat:** confirm the
intended semantics against the ZAERO manual before matching the name. **Effort:** small;
do when a deck appears whose body/nacelle panel is long enough for the local error to
matter.
