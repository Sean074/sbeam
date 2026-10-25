# Lateral cases — rate-column kinematics, the AESURF pair, aileron and rudder conventions — design note for issues #8, #9, #10

**Status:** ✅ **agreed 2026-10-24**, ✅ **implemented 2026-10-24** (#8, #9, #10, #24 all closed
the same day; CLAUDE.md rule 1): D1–D6 below accepted in chat as recommended; D2's authoring
geometry corrected during implementation (§2.3, §9); implementation decisions in §9.
- **Milestone:** [v0.3.0](https://github.com/Sean074/sbeam/milestone/1) — "SOL 144
  engineering-complete **including lateral**".
- **Issues, in closure order:** [#8](https://github.com/Sean074/sbeam/issues/8) DEF-M15
  (Tier M) → [#9](https://github.com/Sean074/sbeam/issues/9) DEF-M16 (Tier M) →
  [#10](https://github.com/Sean074/sbeam/issues/10) lateral capability (Tier L, physics).
  [#24](https://github.com/Sean074/sbeam/issues/24) (four Tier-S wording items) is folded
  in and closed with #10.
- **Related:** charter `09_conventions.md` §5 (rate labels, DEF-M15 warning), §6 (GAP —
  aileron and rudder); backlog map `00_backlog.md` "Required convention decisions".

---

## 1. The defects

### 1.1 #8 — physical-rate → label scales (DEF-M15), and what it generalizes to

`rigid_rate_scales` (`aero/integration.py:143-162`) converts a physical rigid-body rate
about the **basic** axes into the equivalent steady trim label:

```
{1: 0, 2: +1/V, 3: −1/V, 4: +b/2V, 5: +c/2V, 6: +b/2V}       # today
```

DOF 3 carries the relative-wind negation (`α = θ − ḣ/V`); DOFs 2, 4, 6 do not, although
the charter defines SIDES as the freestream's +y velocity fraction (= −β), positive ROLL
as starboard-wing-**down** (rotation about **−x**) and positive YAW as nose-starboard
(rotation about **−z**). A body rate about basic +x therefore maps to a *positive* ROLL
label when it is a *negative* one. The free-flight transient solver forms the aerodynamic
damping `B_hh` from these columns on the input side against the true right-handed `Φ_r`
on the force side (`solver/modal_basis.py:671-683`), so a lateral free-flight rate would
be **anti-damped**. Latent today: no shipped deck frees DOF 2, 4 or 6, and the only test
(`tests/aero/test_integration.py:283-302`) pins the dictionary against its own literals.

**Generalized (D6).** While deriving the independent gate for the scales it became clear
that the three rate columns of `build_djx` are not the kinematic quantity they claim to
be. They are written for a planar horizontal wing:

| Label | Column today (`integration.py:369-387`) | Missing |
|---|---|---|
| PITCH | `−(2/c)(x − x_ref)` | no `n_z` projection: a **vertical fin** receives a pitch-rate normalwash |
| ROLL | `−(2/b)·y` | no `n_z` projection (dihedral), no `z`-offset term (fin above the roll axis sees sidewash), hard-coded `y_ref = 0` |
| YAW | `−(2/b)(x − x_ref)·n_y` | correct form |

Measured 2026-10-24 on `sample/cessna210_flagship_trim.bdf` (rigid derivatives per unit
label, `compute_rigid_derivs`, no structure):

| Label | Coefficient | Today | Kinematic form | Comment |
|---|---|---|---|---|
| PITCH | CY | **+1.881** | 0.000 | spurious fin sideforce: 36 fin boxes carry `−(2/c)(x−x_ref) ≈ −7.6` |
| PITCH | CMZ | **+0.794** | 0.000 | spurious yawing moment from a symmetric rate |
| PITCH | CMY | −17.343 | −17.941 | pitch damping **3.3 % low** today (fin pressure fed back through the AIC) |
| PITCH | CZ | 10.646 | 10.827 | |
| ROLL | CY | −0.032 | −0.074 | fin now sees `p·z` sidewash (physical `C_yp`) |
| ROLL | CMX | 0.5286 | 0.5342 | wing/HTP dihedral `n_z` projection |
| ANGLEA, SIDES, YAW | all | unchanged | unchanged | |

HA144A (no fin, no dihedral) is bit-identical; `val_vlm_rect_ar8` is bit-identical; the
±10° dihedral pair changes `C_lp` 0.5300 → 0.5381 (cos Γ, inside the V-LAT 5 % band) and
`CZ_q` by the same factor. On the flagship the 2.5 g pull-up (`TRIM 2`, PITCH = 0.00284)
is the only shipped case with a non-zero rate label; its trim changes by ≈ 0.0028 × 0.6 in
CMY-per-radian terms (ΔCMY ≈ −0.0017), i.e. a shift of order 0.1 % in trimmed ANGLEA/ELEV,
plus the removal of a fin sideforce `Fy/q ≈ 0.087` from every lateral monitor component.
These deltas are recorded in the CHANGELOG at closure (§5 G4).

### 1.2 #9 — AESURF CID2/ALID2 ignored (DEF-M16)

`Aesurf` stores `cid2`/`alid2`, the parser cross-checks ALID2 (`bdf_reader.py:1855-1860`),
the writer round-trips them, the viewer form **drops them on re-save**
(`sol144_authoring_ui.py:160-188`), and the two consumers read only the first pair:
`build_djx` (`integration.py:401-409`) and `compute_hinge_moments`
(`sol144_derivs.py:131-136`). A one-label antisymmetric aileron pair — NASTRAN's and
ZAERO's standard mechanism — loads nothing on its second half and prints a hinge moment
for one half only, silently. The documented steady-roll preset ("ROLL prescribed, URDD4 =
0, aileron free") therefore cannot run as a determined trim: two single-half labels give
two free variables against one roll equation.

### 1.3 #10 — no lateral case exists

No deck, document or test defines an aileron or a rudder (charter §6 GAP). The steady-roll
and steady-sideslip recipes in `05c_sol144_maneuver.md:519-521` cite V-C5 as their gate,
and V-C5 tests the symmetric pull-up only. Lateral validation is rigid-derivative only
(V-LAT) and asserts magnitude and ± antisymmetry, never an absolute sign.

---

## 2. Theory

### 2.1 One kinematic rule for every rate column

Let `r_j = r_colloc,j − r_ref` with `r_ref` the AEROS RCSID origin (which the trim solver
also uses as `suport_pos` and as the moment reference, `sol144.py:457-474`). A rigid body
rate `ω` about unit axis `ê` gives the box the body velocity `v_j = ω·(ê × r_j)`; the
relative wind is `−v_j`; the `D_jx` sign convention already fixed by ANGLEA (`−n_z` for
`U∞[1, β, α]`) makes the normalwash entry `+n̂_j·v_j / V`. Writing each label as the
reduced rate `ω·L/(2V)`:

```
D_jx[j, label] = (2 / L_ref) · n̂_j · (ê_label × r_j)

  PITCH:  ê = +ŷ,  L = c_ref   →  (2/c)·(n_x·Δz − n_z·Δx)     planar wing: −(2/c)·Δx   (as today)
  ROLL :  ê = −x̂,  L = b_ref   →  (2/b)·(n_y·Δz − n_z·Δy)     planar wing: −(2/b)·Δy   (as today, now about y_ref)
  YAW  :  ê = −ẑ,  L = b_ref   →  (2/b)·(n_x·Δy − n_y·Δx)     fin:         −(2/b)·n_y·Δx (as today)
```

`ê_ROLL = −x̂` and `ê_YAW = −ẑ` are the charter §5 senses (positive ROLL = starboard-down,
positive YAW = nose-starboard); `ê_PITCH = +ŷ` is nose-up in the basic frame (x aft, z up).
The same identity gives the physical-rate scales — the label value that reproduces the
normalwash of a unit body rate about basic **+x, +y, +z** (the `rigid_body.py` axes):

```
rigid_rate_scales = {1: 0, 2: −1/V, 3: −1/V, 4: −b/(2V), 5: +c/(2V), 6: −b/(2V)}
```

DOFs 2, 4, 6 flip relative to today; DOF 5 keeps `+` because `ê_PITCH` is `+ŷ` itself;
DOF 1 (surge) stays 0 — a streamwise speed change is a dynamic-pressure change, not a
normalwash, and has no steady label (documented, not silently assumed). The force-side
yaw-rate wing term inherits `scale[6]`: `build_fj_rigidrate_yaw = (−b/2V)·(−4/b)(y − y_ref)·f
= +2·(y − y_ref)/V · f_ref` — a positive rate about +z advances the starboard wing (higher
q∞, more load), which is the physical sign. Theory Eq. 25 already states the rule
(`(Ω × Δr)·n̂`); Eqs. 26–27 are its planar specializations and will say so, Eq. 27 gaining
`(y − y_ref)`.

**Why this is also the gate.** `build_dj_rigidrate` column k must equal
`(1/V)·n̂_j·v_k(r_j)` with `v_k` built from `assembly/rigid_body.py` (unit translation; unit
rotation `axis × (r − ref)`), independently of any label, scale or sign table. That
identity holds for all five live DOFs on every deck and is exact (rtol 1e-12).

### 2.2 The AESURF pair

A control label deflects the boxes of each half about that half's own hinge. For half
`i ∈ {1, 2}` with hinge axis `ĥ_i` = CID_i +y and origin `o_i` = CID_i origin:

```
D_jx[j, label] = −(ĥ_i × n̂_j)·x̂ · eff        for j ∈ ALID_i          (unchanged formula, now for both halves)
HM_label      = Σ_i Σ_{j∈ALID_i} [(r_fp,j − o_i) × F_j] · ĥ_i          (each half about its own axis)
```

For a mirrored pair with both `+y` outboard the two halves' hinge moments have the same
sign (the geometry is mirrored and so is the axis), so the pair's HM is the sum, and the
f06 reports one number per label as NASTRAN does. One helper owns the geometry:
`aesurf_hinges(aesurf, bulk, id_to_k) -> list[HingeHalf(origin, h_hat, ks)]`
(`aero/integration.py`), consumed by `build_djx` and `compute_hinge_moments` (charter §8
single-source rule; the two consumers currently duplicate the inline derivation).

### 2.3 Signs that follow, with no new rule

Charter §6 already says *positive deflection is lift-increasing: a right-hand rotation
about the CID +y axis*. Applied per half:

- **Aileron (D1).** Author CID1 = starboard half, CID2 = port half, **both +y pointing
  outboard** — NASTRAN's CID1/CID2 practice and ZAERO's `AESURFZ … ANTISYM` semantics.
  Positive AIL = starboard TE-**down**, port TE-**up** → starboard lift up → roll **toward
  port** → **+CMX** in basic (moment about +x, x aft) → in a steady roll the ROLL label
  (positive = starboard-down) comes out **negative**. This is the textbook δa (Etkin,
  Nelson): `C_lδa`, `C_mδe`, `C_nδr` share one sign family.
- **Rudder (D2).** The fin normal is +y, so lift-increasing is +Fy = TE-to-**port**; a
  right-hand rotation that moves the TE to port is about a **downward** axis, so the
  rudder hinge CID is authored with **+y = −z (down)**. *(Corrected 2026-10-24 while
  building the deck: the issue's candidate and the first draft of this note said "+y up",
  which gives TE-starboard. The sign outcome agreed in chat is unchanged; the authoring
  geometry that produces it is the opposite.)* Positive RUD → +Fy at the tail →
  nose-to-port → **+CMZ** in basic → negative YAW label. Textbook δr.
- **Elevator** unchanged (`ELEV` positive = TE-down; nose sense depends on the airframe).

The "lift-increasing per half" statement is what goes into the charter; the physical
outcomes above are the gates (§5 G7, G10, G12).

### 2.4 Steady lateral trims

With `SUPORT 46` (roll and yaw free) and labels `SIDES, ROLL, YAW, URDD4, URDD6, AIL,
RUD` the two recipes are determined trims (`n_free = n_suport = 2`):

| Case | Prescribed | Free | Closed-form check (rigid, linear) |
|---|---|---|---|
| Steady roll | `ROLL = p̂`, `SIDES = YAW = 0`, `URDD4 = URDD6 = 0` | `AIL`, `RUD` | `[CMX_δa CMX_δr; CMZ_δa CMZ_δr]·[δa; δr] = −[CMX_p; CMZ_p]·p̂` |
| Steady sideslip | `SIDES = β̂`, `ROLL = YAW = 0`, `URDD4 = URDD6 = 0` | `AIL`, `RUD` | same matrix, RHS `−[CMX_β; CMZ_β]·β̂` |

The flexible trim equals the rigid solve only for a stiff spine; the deck's spine is stiff
enough that the comparison holds to the stated tolerance, and the restrained-derivative
table is what the solver actually uses (G12 compares against the solver's own
*restrained* derivatives, so the identity is exact linear algebra).

---

## 3. Decisions (agreed 2026-10-24)

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| **D1** | Aileron: lift-increasing rule per half; CID1 starboard, CID2 port, both +y outboard; positive = port roll | "Positive AIL = right-roll command" (issue #9 candidate) | Extends the one rule the charter already has; NASTRAN and ZAERO practice; textbook δa; no second sign rule to teach |
| **D2** | Rudder: lift-increasing = TE-port = nose-port; authored with hinge +y **down** (−z) | — (follows from the same rule) | Textbook δr; the #10 candidate's "+y up" geometry was wrong, its sign outcome is kept |
| **D3** | ROLL about the RCSID origin's y (`suport_pos[1]`) | keep `y = 0` and document | Same point as PITCH and the yaw term; what `Φ_r` rotates about, so the kinematic gate is exact; bit-identical on every shipped deck |
| **D4** | Dedicated `sample/val_lateral_aileron_rudder.bdf`; flagship untouched | add AIL/RUD to the flagship bulk | Eight driver decks and many pinned tests share the bulk; a flagship lateral family arrives with the v0.7.0 case matrix that consumes it (rule 5) |
| **D5** | Fold all four #24 items; close #24 with #10 | leave #24 open | Two of the four live in code this chain edits |
| **D6** | All three rate columns move to the kinematic form (§2.1) under generalize-on-first-find | fix the scales only | The scales' gate *is* the kinematic identity; the PITCH column was loading the flagship fin |

Not decided here (parked, out of scope): an `AELINK`-style card to gang two labels; roll
reference other than the RCSID origin; ZAERO's `TYPE = SYM/ANTISYM` field (sbeam is
full-span only, the CID2 pair is the full-span equivalent).

---

## 4. Conventions cited (`09_conventions.md`)

- §1 Frames — basic x aft, y starboard, z up; CMX/CMZ are the negatives of textbook L, N.
- §2 Aero forces — box force along the panel normal; moment reference = RCSID origin;
  lateral totals about `suport_pos`.
- §5 Trim states — label senses (ANGLEA, SIDES = −β, PITCH, ROLL, YAW); plunge-rate sign;
  **the DEF-M15 warning and the "ROLL has no spanwise reference" sentence are replaced** by
  §2.1 of this note; URDD rotate, aero labels do not.
- §6 Control surfaces — hinge = CID +y; positive = lift-increasing; **GAP replaced** by D1/D2.
- §8 Single-source helpers — `rigid_rate_scales` row updated; new rows `_rate_column`
  (rate kinematics) and `aesurf_hinges` (hinge geometry).
- Theory `01_aeroelastics_theory.md` Eq. 25–28a, §5.4 (AESURF column, hinge moments).

---

## 5. Validation (benchmark-first, rule 2)

| Gate | Issue | What | Tolerance |
|---|---|---|---|
| **G1** | #8 | `build_dj_rigidrate` column k == `(1/V)·n̂·v_k` from `rigid_body` vectors, DOFs 2–6, flagship (wing+HTP+fin, dihedral, off-origin RCSID) and AR8 wing; PITCH column exactly 0 on fin boxes; ROLL on fin boxes == `(2/b)·n_y·Δz` | rtol 1e-12 |
| **G2** | #8 | existing scale/sign pins updated: `test_integration.py` expected scales, `test_yaw_rate_wing.py` force term `+2(y/V)f` | as today |
| **G3** | #8 | free-flight lateral damping sign: on a lateral free-free basis, `−q·B_hh` rigid rate block has damping sign on DOF 4 and DOF 6 diagonals; DOF-2 column opposes sway | sign |
| **G4** | #8 | bit-identity: HA144A SC1/SC2, V-LAT planar, every MLOADS pinned number, flagship TRIM 1; flagship TRIM 2 and dihedral `C_lp`/`CZ_q` deltas recorded in CHANGELOG | 0 / recorded |
| **G5** | #8 | V-LAT `C_lp(dih) = C_lp(anh)`; `≈ planar` | 1e-6 / 5 % |
| **G6** | #9 | one AESURF (CID1/CID2) column == box-for-box sum of two single-half AESURFs with the same CIDs; hinge-moment entry == sum of halves | atol 1e-15 |
| **G7** | #9 | AIL column antisymmetric in y; rigid CZ, CMY, CY, CMZ from AIL vanish on the planar wing; **CMX > 0** (first absolute lateral sign pinned) | abs 1e-9 / sign |
| **G8** | #9 | parse: CID2 ⇔ ALID2, CID1/CID2 must exist, box in both lists → `ValueError` naming the field; writer round-trip | — |
| **G9** | #9 | viewer form keeps CID2/ALID2 on re-save | — |
| **G10** | #10 | rudder: `CY_δr > 0`, `CMZ_δr > 0`; `CMZ_δr/CY_δr` == force-centroid arm from `box_forces`; `CY_δr / CY_β,fin ∈ [0.8, 1.0]·τ(E)` with `τ(E) = 1 − (θ − sin θ)/π`, `θ = acos(2E − 1)` (thin-airfoil flap effectiveness; E = 0.25 → 0.609) | sign / 1e-10 / band |
| **G11** | #10 | aileron: `|C_lδa| / C_lδa,strip ∈ [0.6, 1.0]` with `C_lδa,strip = 2·CLα,VLM·τ·∫_{y1}^{y2} c·y dy /(S·b)` (lifting-line band, same discipline as the C_lp gate); pair HM == 2 × one half | band / 1e-12 |
| **G12** | #10 | end-to-end: TRIM 1 free `AIL, RUD` == 2×2 solve of the solver's restrained-derivative table; `AIL < 0` for `ROLL > 0`; TRIM 2 likewise from `[C_lβ, C_nβ]`, `RUD` sign vs weathercock; `maneuver_closure ≈ 0`; monitor Fy/Mx/Mz ≠ 0; CLI writes f06 + `monitor_loads.csv` + `section_loads.csv` (schema gate) | 1e-8 / sign / 1e-9 |

VAL2 row for the new deck; V-LAT2 added to the aero gate list in `00_program_overview.md`.

---

## 6. Prototype (2026-10-24, `release/0.3.0` @ `8c580de`)

Scratch implementation of §2.1 as a free function (`kin_djx`) run through
`compute_rigid_derivs` against today's `build_djx`, no structure, rigid only — the table
in §1.1 plus:

| Deck | Max |new − old| per column | Derivative changes |
|---|---|---|---|
| `val_vlm_rect_ar8` | 0 for all five labels | none (`C_lp = 0.53850`) |
| `val_vlm_dihedral` / `anhedral` | ROLL 0.0148, PITCH 0.0294 (cos 10° on `n_z`) | `C_lp` 0.52996 → 0.53813; `CZ_q` 6.964 → 6.859; CY_p −0.2995 → −0.3042; anhedral mirrors exactly |
| `ha144a_fullspan_sbeam` | 0 | none |
| `cessna210_flagship_trim` | PITCH 7.60 (fin boxes), ROLL 0.281 (fin `Δz`, dihedral) | §1.1 table |

The §2.1 scales were checked by hand against the five columns: DOF 3 `+n_z/V` (as today),
DOF 5 `−(1/V)·n_z·Δx` on a planar wing (as today), DOFs 2/4/6 the negatives of today.

---

## 7. Affected code and docs (tier closure)

**#8 (Tier M):** `aero/integration.py` (`build_djx` ref point + `_rate_column`,
`rigid_rate_scales`, `build_dj_rigidrate` docstring); tests G1–G5; charter §5/§8; `05c`
Step 52 D_jx bullet + lateral-derivative section; `05a:373-375`; theory Eq. 26–28;
CHANGELOG **Fixed**; `40_history/06` one-liner; #24 item 4 ticked.

**#9 (Tier M):** `aero/integration.py` (`aesurf_hinges`, control branch);
`solver/sol144_derivs.py::compute_hinge_moments`; `parser/bdf_reader.py` cross-checks;
`viewer/sol144_authoring_ui.py::_aesurf_form`; `results/f06_writer.py` + `viewer/results_view.py`
captions; tests G6–G9; `02_card_reference.md` AESURF; `05c:243`; charter §6/§8;
`06_viewer.md`; CHANGELOG **Fixed**; history one-liner.

**#10 (Tier L):** `sample/val_lateral_aileron_rudder.bdf`; `tests/aero/test_lateral_cases.py`
(G10–G12) + VAL2 entry in `tests/integration/test_sample_verification.py`;
`viewer/sol144_authoring.py` preset label (#24-2), `model/maneuver_presets.py` docstring
(#24-3), flagship bulk comments `:404`, `:465` + test echo (#24-1); charter §5 recipes
with SUPORT DOFs, §6 aileron/rudder entries; `05c` recipes + new "Lateral trim cases"
subsection; `00_program_overview.md` VAL2 row, V-LAT2, Known-limitations; `02_card_reference.md`
SUPORT/TRIM examples; `06_viewer.md`; `00_INDEX.md` designs row; `00_backlog.md:56-63`;
CHANGELOG **Added** + **Changed**; `40_history/06` **full step format** +
`00_completed_development.md` index row.

---

## 8. Resolved questions

1. *Is ROLL's missing reference intended?* No — D3; it was the planar-wing shortcut.
2. *Implement the second pair or refuse it?* Implement (D1); refusing would leave the
   steady-roll preset unrunnable and diverge from NASTRAN/ZAERO decks.
3. *Which half is CID1?* Starboard, by authoring rule; the solver cannot enforce it and
   does not need to — the geometry is in the CIDs, the gate is on the sample deck.
4. *Do two single-half AESURF labels stay legal?* Yes (nothing forbids them); the CID2
   pair is the documented form, and G6 proves the two are identical.
5. *Flagship?* Untouched (D4). The flagship's symmetric trims are unchanged by #8 except
   TRIM 2 (recorded); it gains no lateral labels.
6. *Why no AVL run?* No AVL control-surface reference exists in the repo and AVL is not a
   test dependency; the lateral gates are exact identities (G1, G6, G10 arm, G12) plus
   two closed-form bands stated as such (G10 τ, G11 strip theory), the same discipline
   as the existing `C_lp` and `C_nr` gates.

## 9. Implementation decisions

**#8 (closed 2026-10-24):**
1. The three rate columns dispatch through one table `_RATE_LABEL_AXIS = {PITCH: (+ŷ, cref),
   ROLL: (−x̂, bref), YAW: (−ẑ, bref)}` and one function `_rate_column`; no per-label branch
   remains in `build_djx`. `r_ref` is the full RCSID origin (was `x_ref` only).
2. G1 builds the velocity field by placing a one-grid throwaway `BulkData` at each collocation
   point and calling `build_rigid_vectors_g` — the literal `rigid_body.py` primitive, not a
   re-derivation. Parametrized over the flagship (fin, dihedral, off-origin RCSID), the planar
   AR 8 wing and the dihedral wing.
3. G3 frees the flagship MLOADS deck in `SUPORT 23456` in-test (SPC1 reduced to surge) and
   asserts every rigid diagonal of `B_hh` is negative (`C = C_struct − q·B_hh`); the fin makes
   the three lateral entries observable. The pre-#8 scales fail it on DOFs 2, 4, 6.
4. Measured impact (before/after on all twelve SOL 144 samples, single-threaded BLAS): HA144A
   family and `val_dihedral_trim` bit-identical except the HA144A **body** deck, whose strip
   panels lost the same spurious `CY_q = −0.27`; flagship `TRIM 2` ELEV −0.16824 → −0.16910,
   ANGLEA +0.002 %, total CY 5.3e-3 → 9e-7, CMZ 2.3e-3 → −5e-7, whole-aircraft aero monitor
   Fy 202.6 N → 0.03 N; wing-root section loads < 0.01 %. All pinned tests passed unchanged.

**#9 (closed 2026-10-24):**
1. `aesurf_hinges(aesurf, bulk, id_to_k) -> list[HingeHalf(origin, h_hat, ks)]` lives in
   `aero/integration.py` next to `build_djx`; `compute_hinge_moments` imports it and no longer
   calls `get_transform` itself. A half is emitted only when its ALID is non-zero.
2. Parser: `CID1` is now checked against CORD2R too (0 = basic allowed) — it used to fail
   late inside `get_transform` at solve time with no card named.
3. The viewer form offers `CID2`/`ALID2` as selectboxes with 0 = none and refuses a
   half-specified pair; it does not check list overlap (the parser does on the next load).
4. G6 hinge-moment equivalence is asserted on the *trimmed-loading* entry (`'total'` at the
   unit-AIL loading) because the per-label derivative of a single-half surface sees only its
   own half's column; both halves of the pair carry the same-sign hinge moment, negative for
   a positive (TE-down-starboard) deflection.

**#10 (closed 2026-10-24):**
1. **Rudder hinge +y points down.** Laying out CID 13 showed that a right-hand rotation about
   an *upward* axis moves the fin's trailing edge to starboard; the agreed outcome (positive =
   TE-port = +Fy, textbook δr) therefore needs +y = −z. The note, charter §6 and the card
   reference were corrected; G10 asserts the axis `(0, 0, −1)` and `CY_δr > 0`.
2. The deck frees roll and yaw together (`SUPORT 46`) so one deck covers both recipes; each
   trim is determined with `AIL` and `RUD` free. Measured: `C_lp = 0.549`, `C_lδa = 0.302`
   (0.66 × strip), `CY_δr = 0.447`, `CMZ_δr = 0.241`, `CY_δr/CY_β,fin = 1.05 τ`; steady roll
   `AIL = −0.0891`, `RUD = +0.0105` at `ROLL = 0.05`; sideslip `AIL = +0.0011`, `RUD = −0.0721`
   at `SIDES = 0.05`.
3. G10's flap-effectiveness band is ±15 % of the 2-D τ (the finite-AR fin comes out 5 %
   *above* τ on this mesh, not below as the first draft assumed); G11 keeps [0.6, 1.0].
4. `maneuver_closure` is asserted in `Mx` and `Mz` only: sway is SPC-reacted, not trimmed,
   so `Fy` is legitimately non-zero (−0.17 N in the roll case).
5. The two trims are compared against the solver's **restrained** derivative table, which is
   the linearisation the trim actually solves, so rel 1e-8 is exact linear algebra and the
   spine stiffness never enters the tolerance.
6. All four #24 items closed here: flagship comments (1), preset label `pb/2V` (2), pull-up
   `PITCH` guidance (3); item 4 with #8.
