# A Realistic Airplane Through SOL 144 — the Cessna 210 Flagship

*A tutorial for engineers who have a working SOL 144 solver and now have to point it at a
real airplane. It walks the flagship sample family layer by layer — structure, mass,
aero mesh, splines, corrections, trim, monitors, mass cases, transient, body panels — and
then reads
the resulting `.f06` block by block against numbers you can check by hand. The solver
theory lives in [`01_aeroelastics_theory.md`](01_aeroelastics_theory.md); the three
stability-derivative columns are explained in
[`aeroelastic_derivatives.md`](aeroelastic_derivatives.md). This document is about
building and reading a **model**.*

**The deck family**

| File | What it is |
|------|-----------|
| `sample/cessna210_flagship_bulk.bdf` | the whole bulk model — no case control |
| `sample/cessna210_flagship_trim.bdf` | SC1 1g cruise, SC2 2.5g pull-up |
| `sample/cessna210_flagship_massset.bdf` | one TRIM × three payload cases |
| `sample/cessna210_flagship_mloads.bdf` | trim + elevator-ramp transient |
| `sample/cessna210_flagship_section_data.csv` | spanwise section coefficients + the body `TOTAL` block |
| `sample/cessna210_flagship_body.bdf` | §6 — trim with cruciform body panels |
| `sample/cessna210_flagship_body_strip_drv.bdf` | §6 — the decoupled-strip contrast |
| `sample/cessna210_flagship_body_cruciform.bdf` | body-panel overlay (not standalone) |
| `sample/cessna210_flagship_body_strip.bdf` | body-panel overlay (not standalone) |

The drivers are thin: a `SOL 144` line, a `TITLE`, one or more case-control `INCLUDE`s of
the shared bulk (plus, in §6, a body overlay), and their subcases. Everything physical
lives in one place — and layers are added by `INCLUDE`, never by editing the bulk.

Gated by `tests/aero/test_cessna210_flagship.py` (24 checks),
`tests/aero/test_cessna210_flagship_body.py` (34 checks) and
`tests/aero/test_cessna210_example.py`.

---

## 1. The airplane

A Cessna 210-like cantilever high-wing single, in SI units, modelled full span. sbeam has
no half-span/symmetry support, so both wing halves and both tailplane halves are explicit
and `AEROS` carries `SYMXZ = SYMXY = 0`.

| Quantity | Value | Where it comes from |
|---|---|---|
| Wing span / area / AR | 11.20 m / 16.24 m² / 7.723 | `AEROS` BREF, SREF |
| MAC | 1.4707 m | `AEROS` CREF |
| **Quarter-MAC** | **x = 2.4375 m** | the ¼-chord line is *straight* (root 2.00 + 0.4375, tip 2.15 + 0.2875) |
| LE of the MAC | x = 2.0698 m | y_MAC = 2.607 m |
| Tail area / arm / V_H | 3.114 m² / 4.784 m / **0.6237** | HTP ¼-MAC at x = 7.2216 |
| Elevator hinge | **x = 7.60 m**, straight | the ⅔-chord line (root 6.90 + 0.70, tip 7.10 + 0.50) |
| Baseline mass / CG | **1081.0 kg / 22.0 % MAC** | GPWG |
| Cruise q / V | 2334 Pa / 61.7 m s⁻¹ (120 kt) | `TRIM`, ρ = 1.225 |

Two pieces of geometric luck are worth naming, because they are what make the deck
tractable: **both the wing ¼-chord line and the tailplane ⅔-chord line are straight.**
The first means the quarter-MAC — the natural moment reference — is a single x value
rather than a swept locus. The second means the elevator hinge is a single x value, so
the control surface is exactly the aft chordwise box rows with no ragged edge.

> **A correction to earlier revisions of this model.** The pre-flagship
> `cessna210_aero.bdf` header stated "Quarter-MAC is near x = 2.55 m". It is 2.4375 m.
> The 0.11 m error propagates into the tail arm, the tail volume and every moment
> reference, so it is called out here rather than quietly fixed.

**Sanity check before running anything.** Lift at 1g must be
CL = W/(qS) = 1081.0 × 9.81 / (2334 × 16.24) = **0.280**. Helmbold for AR 7.72 predicts a
wing lift-curve slope 2πA/(2 + √(A²+4)) = **4.86 /rad**; with the tail the whole airplane
should land near 5.2–5.3. If the deck disagrees with these, the deck is wrong.

---

## 2. The deck, layer by layer

Each subsection ends with **what breaks if you get this wrong** — in every case a failure
mode that actually occurred while this deck was being built.

### 2.1 Structure

A stick model: a fuselage spine of five CBARs, wing and tail elastic axes, and struts
joining them. Two things about it are deliberate.

**The reference point is a structural node.** `GRID 900` sits at the quarter-MAC
(x = 2.4375) *in the fuselage chain*, between GRID 1 and GRID 2 — the spine's first
element was split to put it there. It carries `SPC1,1,1246,900` and `SUPORT,900,35`.

**The support is free flight, not a ground mount.** The four non-trim rigid-body DOFs
(Tx, Ty, Rx, Rz) are pinned at that one point and `SUPORT` carries the two symmetric trim
DOFs (Tz, Ry). Under symmetric loads the antisymmetric DOFs come out ≈ 0 with no SPC
needed, so both wings react through the fuselage rather than against a rigid centreline.

> **What breaks.** Hang the reference grid off an RBE2 spider instead of putting it in
> the load path and the SUPORT reaction has no route into the structure. Carry a
> half-model's centreline symmetry SPCs into a full-span deck and you ground the fuselage
> in torsion, giving the wing roots a rigid wall instead of the real wing→fuselage→wing
> path.

### 2.2 Mass

19 `CONM2` cards carry powerplant, systems, furnishing and payload; the `MAT1` density is
live, so the CBARs carry ≈ 349 kg of distributed structural mass as well. Together:
1081.0 kg with the CG at 22.0 % MAC, ≈ 31 points of static margin against a neutral point
near 53 % MAC.

The single most important number in the mass model is the **cross-section area**, and it
is easy to forget that `A` is a mass property as well as a stiffness property. The
pre-flagship deck used `A = 0.020 m²` on the fuselage: at ρ = 2700 that is a 54 kg/m
spine, 564 kg of structure at CG x = 4.06 m. No arrangement of point masses can pull an
airplane's CG to 22 % MAC when its *structure* alone weighs half the airplane and sits
that far aft. The areas here are sized so that ρAL over each group lands on a believable
structural weight first, and the stiffness is then set independently through I and J.

> **What breaks.** If GPWG does not print the mass and CG you designed for, stop. Every
> downstream number — trim incidence, load factor, monitor balance, inertia relief — is
> conditioned on it.

### 2.3 Aero mesh

Five `CAERO1` panels: wing starboard/port (16 × 6 boxes each), HTP starboard/port
(8 × 6), and the fin (6 × 6). **324 boxes.**

`NCHORD = 6` everywhere. Two or more chordwise boxes are *required* for the section-moment
correction to exist at all, four or more before the pitching moment converges; six leaves
margin at the 2.5g point. `NSPAN` is then chosen per surface to keep the box aspect ratio
near 1, which is where the horseshoe-vortex kernel is best conditioned.

The `CAERO1` EIDs are **1000-spaced**: 1000, 2000, 3000, 4000, 5000. A NASTRAN box ID is
`EID + i_span·NCHORD + j_chord`, so this keeps each surface's boxes inside its own decade
(1000–1095, 2000–2095, 3000–3047, 4000–4047, 5000–5035) and makes collisions impossible
by construction. 6000 and 7000 are reserved for the Step 66 body panels.

> **What breaks.** Space the EIDs too closely and two surfaces' box IDs overlap.
> `build_box_id_map` is fatal on collision — which is the good outcome; the bad one is a
> deck where an `AELIST` silently addresses the wrong surface's boxes.

### 2.4 Splining — and why the fin is different

Four `SPLINE2` beam splines (wing L/R, HTP L/R) and one `ATTACH` (the fin).

Each `SPLINE2` needs a spline-axis `CORD2R`. **The spline axis is the CID *y*-axis** (MSC
convention): x is the chord/rigid-arm direction, z the deflection direction. The four here
are built from the elastic axis they serve — y = unit(root EA → tip EA), z = global +Z
made orthogonal to y so the 1.5° dihedral is carried exactly, x = y × z.

**`DTHY` must be 0.0 on every one of them.** Each `SET1` lists elastic-axis grids only,
and those are collinear along the spline axis, so the beam spline has no twist information
of its own. Detaching torsion (`DTHY = -1`, the HA144A setting) leaves the spline system
singular. HA144A gets away with it because its `SET1`s carry leading/trailing-edge
stringer *pairs*, which supply twist through their deflection difference. A pure stick
model has no such pairs, so torsion must attach rigidly to the beam's own rotation —
which is exactly right, because the beam's Rx/Ry *is* the only twist DOF that exists.

The fin gets `ATTACH, 1005, 5000, 5000, 5035, 30, 0` — all 36 boxes rigidly slaved to the
fin-root grid. Two reasons: a `SPLINE2` would need a spline-axis CORD2R whose y-axis runs
along global **Z**, the awkward case; and the fin's own bending is negligible next to the
tailcone bending that carries it, so rigid slaving is the honest idealisation. `ATTACH`
requires `CID = 0`.

> **What breaks.** A singular spline raises at operator build, which is survivable. The
> nastier failure is a box that no spline covers: it neither deflects with the structure
> nor feeds load back into it, and nothing says so. Check that every box has a non-zero
> `g_slope` row.

### 2.5 Control surface

```
AESURF, 505, ELEV, 995, 3100
```

`CID1 = 995` defines the hinge. **The hinge line is that CORD2R's *y*-axis** — the same
convention as the spline axis. The card is built as z = +Z, x = +X, so y = z × x = +Y runs
spanwise along x = 7.60.

The `AELIST` names the aft two of the six chordwise rows on each tailplane —
`3000 + 6s + {4,5}` and `4000 + 6s + {4,5}` for s = 0…7, **32 boxes** — i.e. the aft third
of the chord, hinged on the straight ⅔-chord line.

> **What breaks, silently.** Build the hinge CORD2R with its *x*-axis spanwise and the
> elevator column of `D_jx` comes out **identically zero**. The trim then has two free
> variables whose aerodynamic responses are linearly dependent, and the only symptom is
> `LinAlgError: Matrix is singular` from a 2×2 Schur solve with nothing pointing at the
> cause. This cost a debugging cycle during the build of this very deck.

### 2.6 Corrections — the central lesson

The `W2GJ` + `AECORR` pairs are **pre-baked into the bulk file**, generated once from
`cessna210_flagship_section_data.csv` and committed with the viewer's provenance header
recording the source CSV, the date and the flight condition.

The section table is **3D-informed**, and this is the part most worth internalising.

A VLM strip is not an airfoil section. By the time you read a strip's normal force out of
the AIC solution, the finite-wing downwash is *already in there*. On this wing the
installed slope runs **0.086 /deg at the root to 0.047 /deg at the tip**; on the tailplane
it is only **0.044 /deg**, because the HTP additionally sits in the wing's downwash field.
The 2D section values are ≈ 0.105 and ≈ 0.095 /deg.

WT2's job is to make each strip reproduce the force slope you tabulate. Tabulate the *2D*
value and it dutifully does so — and you have now counted the downwash twice. The wing
alone is driven to 0.105 × 180/π = **6.0 /rad**, which is not a lift slope any AR-7.7 wing
has ever had.

So the committed table is anchored to the model's own 3D strip loading and scaled by a
single factor (1.0223) to the Helmbold target of 4.86 /rad. On top of that anchoring it
carries the things a real airfoil has and a flat plate does not:

- **camber**: `a0 = -2.5°` at the root (a NACA 2412-like zero-lift angle);
- **washout**: `a0` sweeps linearly to `+0.5°` at the tip — 3° of geometric washout;
- **section moment**: `cm0` from −0.055 at the root to −0.045 at the tip;
- **a second operating region**, 8–14°, at 70 % of the low-α slope with `a0` shifted for
  continuity at 8° — stall onset.

The effect on the model is exactly what it should be: the corrected operator carries
**CL = 0.099 at α = 0** where the bare VLM carries none, while the lift *slope* moves only
from 5.21 to 5.33 /rad — about 2 %. A correction that barely changes the slope but adds
the camber, washout and section moment is a correction that has been given honest data.

> **What breaks.** Feed it raw 2D polars and everything downstream is wrong in a way that
> looks plausible: the trim incidence is too low, the elevator angle is too small, and the
> spanwise loading is too flat. Nothing errors.

**One region at a time.** `section_data` v1 bakes a *single* operating region per surface,
and nothing warns when a trim wanders outside it. Both trims here land inside the −4…8°
block (2.39° and 7.08°) and a test gates that they continue to. The 8–14° rows ship in the
CSV as the selectable second region, but neither trim uses them.

### 2.7 Trim

```
TRIM, 1, 0.0, 2334.0, RHOREF, 1.225, PITCH, 0.0
+, URDD3, -9.81, URDD5, 0.0
```

Four `AESTAT` labels (ANGLEA, PITCH, URDD3, URDD5) plus the `AESURF` ELEV. TRIM prescribes
PITCH, URDD3 and URDD5, leaving ANGLEA and ELEV free against the two SUPORT equations —
a determined trim.

`RCSID = 990` is a **z-down** stability axis at the quarter-MAC. That is what makes
`URDD3 = -9.81` a 1g level pull rather than a 1g bunt.

The 2.5g card prescribes `URDD3 = -24.525` **and** `PITCH = 2.8402e-3`. A steady pull-up is
a constant pitch *rate* as well as a load factor:
PITCH = q̇·c/(2V) = (n−1)g·c/(2V²) = 1.5 × 9.81 × 1.4707 / (2 × 3810.2). Leave PITCH at 0
and you have trimmed a 2.5g pull with no rotation — a different and unphysical manoeuvre
that also drops the tail damping term setting the real elevator-per-g gradient.

`RHOREF` takes no part in the static trim. It exists so that V = √(2q/ρ) is available to
the transient solver's rate terms.

### 2.8 Monitor points

Two kinds, and the contrast between them is the point:

- **`MONPNT1`** — **aero only**, summed over an `AELIST` box collection.
- **`MONPNT3`** — **aero + inertia + reaction**, summed over `SET1` structural grids.

`MALLAR`/`MALLEA` are the whole airplane; `MRWAER`/`MWROOT` are the starboard wing.
`MWROOT` deliberately *excludes* the shared root grid 10, so taken about the root station
its resultant is the starboard wing-root shear and bending.

> **What breaks — the DEF-M10 rule.** A whole-aircraft `MONPNT3` `SET1` must list **every
> spline-load grid AND every CONM2-bearing grid.** Grids 1, 900, 3, 5, 31 and 32 here carry
> mass but take no spline load. Omit one and you silently drop that share of the inertia,
> and the balance check below stops meaning anything while still looking like a small
> number.

### 2.9 Mass cases

```
MASSSET, 10, FERRY,  1.0   +, DELETE, 7
MASSSET, 20, CRUISE, 1.0   +, ADD, 6001, 6002, 6003, 6004
MASSSET, 30, MTOW,   1.0   +, ADD, 6011, 6012, 6013, 6014
                           +, REPLACE, 7, 6020
```

996.0 / 1201.0 / 1560.0 kg over one airframe, exercising all three ops. Overlay `CONM2`s
(the 6000-series) are excluded from the baseline and enter only the cases that name them;
`6020` carries an offset so the deck exercises the offset path — translation–rotation
coupling and the parallel-axis transfer — inside a mass case.

Stiffness, splines and the whole VLM `AeroCache` are geometry/Mach-only and are built once
and shared; only `M_gg`, `M_ax`, GPWG and the trim solve are rebuilt per case.

### 2.10 Transient

The `MLOADS` chain seeds a Level-1 quasi-steady, open-loop, restrained-l-set Newmark-β
integration from the 1g trim and ramps the elevator +2° over 0.3 s, then holds.

> **What breaks — `MLDCOMD` tables are ABSOLUTE.** The `TABLED1` does not carry a
> perturbation; it carries the commanded angle itself. It must therefore **start at the
> trimmed elevator angle**, which makes the deck a two-pass authoring job: run the trim
> driver, read the trimmed ELEV out of the f06, write it into the table. Start the table
> at 0.0 instead and the airplane takes a 3.8° step input at t = 0.
>
> The same property makes the table **mass-case specific**. Pair `MLOADS` with a `MASSSET`
> and the trimmed elevator moves, so a table authored for the baseline no longer starts at
> equilibrium for that case. Re-run the trim for the mass case and re-bake the first point;
> do that and the initial condition is reproduced to machine precision.

---

## 3. Reading the `.f06`

Run `sbeam sample/cessna210_flagship_trim.bdf`.

### 3.1 Trim variables

```
SUBCASE 1     TRIM = 1     MACH = 0.0000     Q = 2.334000E+03
      ANGLEA          FREE           4.171998E-02      (=  2.3904 deg)
      ELEV            FREE          -6.599247E-02      (= -3.7811 deg)
```

α = 2.39° at 1g. Check it: CL must be 0.280, the airplane's slope is ≈ 5.33 /rad, and the
camber already supplies CL₀ ≈ 0.09, so α ≈ (0.280 − 0.090)/5.33 = 0.036 rad = 2.0° before
the tail download is accounted for. The solver's 2.39° is the same number with the tail
carried properly.

SUBCASE 2 gives α = 7.08°, ELEV = −9.64°. Both trims sit inside the baked −4…8° block.

**Elevator per g** = (−9.639 − (−3.781))/1.5 = **−3.91 °/g**. Trailing edge up with
increasing load factor, as it must be for a statically stable airplane.

### 3.2 Stability derivatives

```
                  --------- RIGID ---------   -- ELASTIC RESTRAINED --   - ELASTIC UNRESTRAINED -
      LABEL          CZ          CMY             CZ          CMY            CZ          CMY
      ANGLEA     5.333485E+00 -1.692080E+00   5.518806E+00 -1.688459E+00  5.570403E+00 -1.708297E+00
      ELEV       6.103003E-01 -1.965806E+00   6.084772E-01 -1.958088E+00  6.103798E-01 -1.959628E+00
```

- **CZ_α = 5.33 /rad rigid.** Helmbold gives 4.86 for the wing; the tail adds the rest.
- **Cm_α = −1.69 /rad**, i.e. statically stable. The tail contributes roughly
  −V_H·CL_α,t·(1−dε/dα)·η ≈ −1.3 and the CG-ahead-of-ac term the balance.
- **Elastic restrained is +3.5 % on rigid.** The wing washes *in* under load here rather
  than out, so flexibility increases the lift slope.
- **Unrestrained differs from restrained** — it is the free-flight number a flight-test
  extraction would see, and unlike the restrained column it does not depend on where you
  put the SUPORT. See [`aeroelastic_derivatives.md`](aeroelastic_derivatives.md).
- **`UNRESTRAINED INTERCEPTS (W2GJ BASELINE): CZ0 = 9.02e-2`** — this is the camber
  talking. A flat-plate deck prints zero here.

### 3.3 Aerodynamic totals and divergence

```
      TOTAL CZ (BODY) =  2.797810E-01        TOTAL CL (WIND) =  2.795375E-01
      CRITICAL DIVERGENCE DYNAMIC PRESSURE  Q-DIV =  5.373038E+04   Q / Q-DIV = 4.343911E-02
```

CZ = 0.27978 against the hand value W/(qS) = 0.27978. At 2.5g it is 0.69945 — exactly
2.5×. Divergence sits at **23× the cruise q**: the wing is flexible enough to show
aeroelastic feedback (§3.2) and nowhere near losing it.

### 3.4 Monitor points — the balance check

```
      MONITOR MALLAR   (MONPNT1, aero only)      FZ =  1.060486E+04
      MONITOR MALLEA   (MONPNT3, aero+inertia+reaction)  FZ =  1.455192E-11
```

The whole-airplane **aero-only** vertical force is 10 604.9 N. The weight is
1081.0 × 9.81 = 10 604.9 N. The whole-airplane **balanced** force is 1.5 × 10⁻¹¹ N.

That pair is the cheapest end-to-end statement that the trim really closed: lift equals
weight, and once inertia and the support reaction are added back the airplane is in
equilibrium. If `MALLEA` is not ~0, either the trim did not converge or the `SET1` is
missing mass grids (§2.8).

`MWROOT` gives the starboard wing-root bending, Mx = 8352 N·m at 1g.

### 3.5 Deflections

| | wing-tip Uz | % semispan | tip rotation |
|---|---|---|---|
| 1g | 85.1 mm | 1.52 % | +1.10° |
| 2.5g | 250.2 mm | 4.47 % | +3.28° |

Believable for a GA wing, and the nose-up tip rotation under load is the wash-in that
raises the elastic lift slope in §3.2.

---

## 4. The mass sweep, and inertia relief

Run `sbeam sample/cessna210_flagship_massset.bdf`.

| Case | Mass (kg) | ANGLEA | MONPNT1 Fz (N) | n·W (N) | Root Mx / W |
|---|---|---|---|---|---|
| FERRY | 996.0 | 2.152° | 9 771.0 | 9 771.0 | 0.760 |
| CRUISE | 1201.0 | 2.736° | 11 782.1 | 11 782.1 | 0.635 |
| MTOW | 1560.0 | 3.680° | 15 303.9 | 15 303.9 | 0.586 |

Two readings.

**ANGLEA rises monotonically with weight.** Same q, more lift needed, more incidence.

**Wing-root bending *per unit aircraft weight* falls as fuel goes into the wing:** 0.760 →
0.635 → 0.586. This is **inertia relief**. Wing fuel is carried outboard of the root cut,
so its weight acts downward on the same span the lift acts upward on, and the two partly
cancel *before* reaching the root. The heaviest airplane is not the most critical one for
the wing root — which is why a loads engineer certifies the zero-fuel case.

Note the elevator does *not* move monotonically (−3.69°, −3.95°, −3.74°): the MTOW case
also moves the CG, via the offset cabin mass, and CG position competes with weight in
setting the trim elevator.

---

## 5. The transient

Run `sbeam sample/cessna210_flagship_mloads.bdf`. Outputs: the f06 transient block, a
`.mldprnt.txt` time history, and `.maneuver_qs_loads.bdf` FORCE/MOMENT cards for the
critical sample.

```
     TIME        ANGLEA         ELEV          FZ_AERO
  0.00000e+00  4.17200e-02  -6.59925e-02   1.06049e+04
  1.50000e-01  4.17200e-02  -4.85390e-02   1.10074e+04
  3.00000e-01  4.17200e-02  -3.10859e-02   1.14100e+04
  1.00000e+00  4.17200e-02  -3.10859e-02   1.14100e+04
```

At t = 0 every recovered quantity equals the SUBCASE 1 trim — the initial condition *is*
that trim. The elevator tracks the absolute table linearly to the held value and the
response settles. `FZ_AERO` rises from 10 605 N (= W) to 11 410 N.

**ANGLEA does not change, and that is the model, not a bug.** This is Level-1: open-loop,
with the rigid-body DOFs *restrained*. The airplane does not fly away in response to the
elevator; the extra load is reacted by the support. What the run gives you is the
structural load path responding to a time-varying control input at a frozen flight state.
Free-flight rigid-body coupling — where ANGLEA, PITCH and URDD3 evolve — is the Step 63
modal solver (select it with MLOADS METHOD=-1; this flagship deck deliberately runs the
prescribed-rigid direct solver).

The same restraint explains why the aero/inertia closure residual, machine-small at t = 0,
grows as the elevator deflects: away from the initial condition the extra lift is balanced
by the restraint rather than by an inertial response.

---

## 6. The body layer

Everything above is a bare airframe: five lifting surfaces and no fuselage. The fuselage
of a real airplane is not aerodynamically silent — it is mildly destabilising in pitch and
in yaw, and it carries a small share of the lift. sbeam has no slender-body element, so the
fuselage is represented by flat VLM panels: a **cruciform** of two crossing surfaces, one
horizontal (body lift and pitching moment) and one vertical (side force and yaw).

```
sbeam sample/cessna210_flagship_body.bdf            # cruciform  (PAERO1)
sbeam sample/cessna210_flagship_body_strip_drv.bdf  # strip      (PSTRIP)
```

Both drivers are three lines of aerodynamics on top of the deck you already have:

```
INCLUDE 'cessna210_flagship_bulk.bdf'
INCLUDE 'cessna210_flagship_body_cruciform.bdf'
```

The bulk is **byte-identical** to the one §2 describes. That is deliberate, and it is worth
copying: the flagship's numbers took a long calibration to land, and a layered deck lets you
add aerodynamics without putting any of them back in play. Every number in §3 is still the
number that deck produces.

### 6.1 What the correction actually constrains

The body panels are tuned by `build_body_correction` against a `TOTAL` row in the same
section-data CSV the flying surfaces use:

```
caero,eta,mach,var,a_lo,a_hi,cn_a,a0,cm_a,cm0,xref,cl_a,cl0
0,0.00,0.0,TOTAL,-4.0,8.0,0.0772,0.000,-1.4921,-0.0404,0.25,-0.0364,0.0
```

The column names are re-used, not renamed: on a `TOTAL` row `cm_a` is Cm_α, `cn_a` is
Cn_β, `a0` is Cn0, `cl_a` is Cl_β. The targets are **total-airplane** coefficients about
the `AEROS` RCSID origin — here the ¼-MAC at (2.4375, 0, 0.60), *not* the basic origin. A
`TOTAL` row copied from a deck with a different reference point is meaningless; moment
coefficients are only defined with respect to a point.

Cm_α = −1.4921 against the bare airplane's −1.6921 is the whole fuselage story: a
**+0.20 /rad destabilising increment**, about 12 % of the airplane's pitch stiffness. The
static margin shrinks and the airplane stays comfortably stable, which is what a fuselage
does.

Note what the correction does **not** constrain: **lift**. It matches four moment
coefficients and leaves the body's own normal force to fall out of whatever slope the panel
happens to have. That is not academic. At the `PSTRIP` default slope of π the strip body
trims out carrying **1168 N — 11 % of the airplane's weight — on the fuselage**. The trim
still closes, every total is still exact, and the answer is still wrong for loads work:
11 % of the weight has been taken off the wing and put somewhere it does not belong. The
committed deck sets `PSTRIP, 20, 0.35`, which brings the strip body to 237 N (2.2 %),
matching the cruciform's 216 N (2.0 %).

If you take one thing from this section: **check what your body panels carry, not just what
they correct.**

### 6.2 Reading the body in the `.f06`

Body boxes have no structural spline — they carry `SPLINE0`, which means "no elastic
coupling", and their force reaches the structure as a rigid load at a named master grid:

```
                    I N J E C T E D   A E R O   L O A D S   (SPLINE0 / UN-SPLINED)

      SOURCE          MASTER GRID   BOXES        FX        FY        FZ        MX        MY
      SPLINE0 9400            900      16       0.0       0.0   2.156E+02  -1.417E+01  1.054E+03
      SPLINE0 9500            900      32       0.0  -3.943E+01       0.0  -1.298E+01       0.0
```

Before Step 64 this force appeared in the printed totals but not in the force balance, and
a body-panel trim silently did not close. The gate that it does now is the same one as
always — all-box lift equals n·W — and it is worth re-checking whenever you add panels.

`SPLINE0` field 5 names the master grid; left blank it falls back to the `SUPORT` grid, and
with neither you get a warning and the body force is **dropped**. The deck names GRID 900
explicitly. Two things have to be true of that grid: it must be in the structural load path
(GRID 900 is spliced into the fuselage CBAR chain), and it must be inside your
whole-airplane `MONPNT3` `SET1`, or the balance check in §3.4 stops meaning anything.

### 6.3 Your monitors do not follow your mesh

The bulk's `AELIST 1400` covers the 324 flying boxes. It was correct in §3.4 and it is
quietly wrong now:

```
      MONITOR MALLAR    (324 flying boxes)      FZ = 1.038922E+04
      MONITOR MALLARB   (all 372 boxes)         FZ = 1.060486E+04     <- = n*W
```

The shortfall is 215.6 N — exactly the injected body force above. Nothing warns you. An
`AELIST` is a list of box IDs, so boxes added later are simply not in it, and the monitor
goes on returning a confident, slightly wrong number. The overlay adds `AELIST 1401` over
all 372 boxes and keeps both, so the difference is visible rather than hypothetical.

### 6.4 Cruciform or strip: the same airplane, twice

The two overlays differ in exactly one field — the `CAERO1` property ID — and therefore in
exactly one physical property:

| | Cruciform (`PAERO1`) | Strip (`PSTRIP`) |
|---|---|---|
| Horseshoe vortex, wake | yes | no |
| Influence-operator block | fully coupled | **diagonal** |
| Effect on wing/HTP/VTP | real | **exactly zero** |
| Placement constraints | must stay clear of the tail | none — overlap is harmless |
| Interference / fence effect | represented (crudely) | not represented |

They were tuned to the same targets and matched on body-lift share, so they trim within
0.003° of α of one another and produce identical rigid Cm_α. And yet:

```
max change in flying-surface DCp response vs the bare airplane
  strip      1.8e-15      (machine precision)
  cruciform  4.5e-01      (tens of percent of a typical box DCp)
```

The horizontal panel sits 0.95 m under the wing. For the cruciform that is a genuine VLM
surface loading its neighbour; for the strip it is invisible. **Both airplanes have exactly
the right total moments.** One of them has substantially redistributed the spanwise wing
loading to get there.

That is the trap this pair exists to show. Matching total coefficients is not the same as
getting the load distribution right, and a correction that is tuned on totals cannot tell
you which one you have. If you are computing stability derivatives, the cruciform's
interference is a feature. If you are computing wing-root bending for a structural sizing
loop, prefer the strip — it is a pure load device that cannot perturb what you are
measuring — and understand that in exchange it models no interference at all.

The measurement above is taken at a **fixed** aerodynamic state, not at the trim point. At
their own trims both variants change the flying loads, simply because both add lift and so
both trim at a lower α. Contamination is a property of the influence operator, so that is
where it has to be measured.

### 6.5 Where a flat plate runs out

The correction reports a `ratio_max` — the largest WT2 pressure scaling it had to apply to
the body boxes — and warns past 200. On this deck it is 27.7 (cruciform) and 10.1 (strip),
comfortably inside. Push the targets harder and it climbs: the panels are weakly coupled,
so large authority has to come from large per-box scaling.

A high ratio is not contamination — WT2 is a post-inverse diagonal on the body rows only —
it is the builder telling you that a flat plate is being asked to be something it is not.
Large body effects (a several-MAC neutral-point shift, say) are only reachable by immersing
the panels in the tail, which buys the authority with a spurious interference the deck
deliberately avoids. That is where a real slender-body element is the right tool, and it is
on the backlog.

---

## 7. Powered effects — the corrections position

The flagship is a single-engine tractor-prop airplane, and everything above models it
**unpowered**. That is deliberate, and it is worth being explicit about why, because the
release this document supports claims maneuver loads on a twin-turboprop.

**sbeam has no propeller.** No actuator disc, no slipstream tube, no thrust. The VLM sees
one freestream, one dynamic pressure, one Mach, over the whole model. Powered effects enter
by exactly one route: **the same correction cards you have already met — `W2GJ`, `WT2`,
`CHORDCP` — built from powered data instead of unpowered data.** There is no third option
and no partial one. If your correction table came from an unpowered source, your airplane
is unpowered no matter what the thrust line in your drawing says.

This is a position, not an oversight. A correction built from powered CFD or powered flight
test carries the real installed effect, including the interference a simple momentum-theory
slipstream would miss. What it cannot do is *vary* — and §7.3 is about that.

### 7.1 What a propeller does, and which card carries it

Five distinct effects. They are separate physics and they land on different cards; treating
them as one lump is the most common way to get a powered deck subtly wrong.

| # | Effect | Physics | Card it belongs on |
|---|--------|---------|--------------------|
| 1 | **Slipstream dynamic pressure** | Axial induction raises local q on the washed strips — `q_s/q∞ ≈ (1+a)²`. More load, same shape. | Force **slope** on the washed strips: `cn_a` in the section table → `WT2` |
| 2 | **Swirl** | The disc imparts rotation: upwash on the up-going-blade side, downwash on the other. A local Δα, **antisymmetric about the nacelle**. | Zero-lift incidence per strip: `a0` in the section table → `W2GJ` |
| 3 | **Propeller normal force** | A disc at incidence carries a side/normal force in its own plane. Ahead of the CG it is **destabilising** — a real `Cm_α` increment. | Body/nacelle correction `TOTAL` row: `cn_a`, `cm_a` |
| 4 | **Thrust-line offset moment** | `T × z_offset`. Not aerodynamic at all. | **Nothing clean — see §7.2** |
| 5 | **Slipstream on the tail** | A conventional tail sits in the washed flow; a T-tail (ATR42) largely does not. Changes tail q *and* the downwash reaching it. | The tail surface's own section-table rows |

Effects 1 and 2 are the ones people remember, and they behave very differently. The q
increment is roughly symmetric about the nacelle and adds lift. The swirl increment is
**antisymmetric** and, over one nacelle, largely cancels in lift — but it does *not* cancel
in rolling or yawing moment, and it does not cancel across the airplane unless the
propellers are handed. On a co-rotating twin, swirl is a net rolling and yawing moment at
every power setting, which is precisely the trim asymmetry a powered deck exists to capture.
Tabulate it per strip with the correct sign on each side of each nacelle, or you have built
a symmetric airplane with extra steps.

### 7.2 The thrust moment has no clean home — read this before you fake it

Effect 4 is the awkward one, and the deck will not let you do the obvious thing.

**You cannot apply thrust as a `FORCE`/`MOMENT` in a SOL 144 trim subcase.** A subcase
carrying both `TRIM` and `LOAD` is *refused* with an error naming both SIDs (DEF-M4). The
trim RHS is aerodynamic + inertial only — there is no applied-structural-load term — and
rather than read a `LOAD` request and silently discard it, the solver stops. That refusal is
protecting you: a deck that "trimmed with thrust" while ignoring the thrust card is exactly
the failure mode that looks plausible and is wrong.

That leaves two honest routes and one temptation:

1. **Fold the thrust moment into the aerodynamic correction** — add `T·z_offset`, expressed
   as a `cm0` increment, to the body correction's `TOTAL` row. The airplane then trims
   against an *aerodynamic* moment standing in for a *propulsive* one.
   > **The catch, and it is not small.** A correction moment scales with `q·S·c̄`. Thrust
   > moment does not — it scales with thrust, which at fixed power roughly *falls* with
   > speed. Build the fudge at one condition and it is exact there and wrong everywhere
   > else, in the direction that flatters you at low speed. If you take this route, build
   > one correction set **per flight condition** and never sweep speed inside one.
2. **Use the restrained static path** (`run_aeroelastic_static`), which *does* combine a
   `LOAD` set with the aero load, and apply thrust as ordinary `FORCE`/`MOMENT` cards. You
   give up free-flight trim and inertia relief to get it — a fair trade for a stress case at
   a known attitude, not for a maneuver.
3. **Do not** put the thrust moment into a wing section's `cm0` to "make the trim come out".
   It lands as a distributed aerodynamic moment on the wing strips, so your wing torsion —
   the thing the section loads exist to report — is wrong by the amount you fudged.

The real fix is an applied-load term in the trim RHS, which is a capability change with
undecided physics (does an applied load participate in inertia relief, and what does
`maneuver_closure` mean once it does?), not a defect. It is on the backlog.

### 7.3 What a frozen correction cannot do

Everything in §2.6 about honest data applies here, and powered corrections add failure modes
of their own. **A correction is a fixed matrix.** It is built once, at one condition, and the
solver applies it unchanged no matter where the trim lands.

- **One power setting.** The correction encodes a single advance ratio `J` and disc loading.
  Climb power and cruise power are different airplanes; so are the same airplane at the same
  power at two altitudes. Build a correction set per condition and say so in the provenance
  header.
- **It does not move with α.** The slipstream Δα of §7.1 is applied as a fixed `W2GJ`. In
  reality the slipstream tube deflects with the airplane and the washed strip set changes.
  Trim to an α far from the build α and the wash is being applied to the wrong strips.
- **It does not move with the trim solution, or with the structure.** The correction is
  calibrated on the *rigid* mesh at the build condition. Elastic twist changes the real
  loading; the powered increment does not re-evaluate. This is the ordinary correction
  caveat, but powered increments are large, so the error is larger too.
- **No thrust lapse.** Nothing in the model knows what thrust *is*, so nothing varies it
  with speed, altitude or temperature.
- **One operating region per surface** (`section_data` v1), and nothing warns on exit —
  the §2.6 limitation, now with a powered table that is even more strongly nonlinear in α.
- **Asymmetric cases need their own correction set.** One engine out is not a scaled version
  of both-engines-running: the washed strips on one wing revert to freestream while the
  other stays washed, and the swirl on that side disappears. That is a different `W2GJ` and
  a different `WT2`, built from a different CFD run. Do not scale a symmetric powered
  correction and call it OEI.

> **The one-line summary.** sbeam will let you model a powered airplane accurately at *the
> condition you built the correction for*, and will not warn you when you leave it.

### 7.4 The workflow, concretely

The correction machinery does not care that your data is powered — it takes section
coefficients per strip. So the work is entirely in producing the table:

1. Run (or obtain) the aerodynamics **twice** at the same geometry, Mach and α: **powered**
   and **unpowered**.
2. Reduce both to the section quantities the table wants — `cn_a`, `a0`, `cm_a`, `cm0` per
   strip, per surface (§2.6 for the column meanings, and for the 2D-vs-3D trap, which does
   not go away just because the data is powered).
3. Build the table from the **powered** numbers, anchored to the model's own 3D strip loading
   exactly as §2.6 describes. The unpowered run is your check: the powered-minus-unpowered
   delta should be concentrated in the washed strips and should be antisymmetric in `a0`
   about each nacelle. If it is not, something upstream is wrong.
4. Synthesise the `W2GJ` + `WT2` pairs through the viewer's correction tab (or
   `build_section_correction_multi` directly), and commit them with a provenance header
   stating the **power setting and advance ratio** alongside the Mach and date.
5. Correct the **tail as well as the wing** (effect 5). A powered wing with an unpowered tail
   trims to the wrong elevator angle and therefore the wrong tail load — and tail load is a
   structural deliverable.
6. Gate the trim's α against the table's region, the way `test_cessna210_flagship` does.

Nothing above needs a card sbeam does not have. It needs data sbeam cannot generate.

---

## 8. Limitations and roadmap

| Limitation | Where it lifts |
|---|---|
| Body panels are flat plates, not a slender body — only a small increment is legitimate (§6.5) | slender-body / CAERO2 element (backlog) |
| The body correction matches moments only; body lift is unconstrained (§6.1) | constrained-CZ body solve (backlog) |
| A cruciform body redistributes the wing loading it corrects (§6.4) | use the strip variant for loads; image-fence method for interference |
| No propeller model — powered effects only via corrections, frozen at one power setting (§7) | no native slipstream model planned; a correction set per condition is the method |
| Thrust cannot be applied in a trim subcase (`TRIM` + `LOAD` is refused, DEF-M4) (§7.2) | applied-load term in the trim RHS (backlog) |
| Steady aerodynamics only (VLM at k = 0); no unsteady, no flutter | Phase D — DLM, SOL 145 |
| Direct-solver transient is restrained and open-loop; ANGLEA/PITCH/URDD frozen | Delivered: the Step 63 free-flight modal solver (MLOADS NMODES/METHOD/ZETA) integrates them |
| One correction operating region per surface, no warning on exit | `section_data` v2; T3b gates it meanwhile |
| Mach matched exactly, no interpolation | as above |
| Euler–Bernoulli beams, no shear flexibility | Phase 2 (Timoshenko) |
| Correction cards written at 7 significant digits | DEF-M12 |

---

## 9. If you are building your own deck

The order that worked, each step gated before starting the next:

1. **Structure + mass first.** Do not proceed until GPWG prints the mass and CG you
   designed for. Size `A` as a mass property; set stiffness with I and J afterwards.
2. **Mesh and splines.** Check 100 % box coverage and zero warnings before any trim.
3. **One trim, uncorrected.** Confirm CL = W/(qS) and that α is physically sensible.
   Calibrate stiffness here — you want a visible elastic effect (a few percent) with
   divergence an order of magnitude away, and wing-tip deflections of a couple of percent
   of semispan.
4. **Then corrections**, from 3D-informed data, iterating the reference incidence until it
   equals the α it produces.
5. **Then the second trim, monitors, mass cases**, and only last the transient, whose
   command table depends on a converged trim.
6. **Body panels last of all, as a separate layer.** Add them over a frozen bulk so the
   calibration above is not back in play, check what they *carry* as well as what they
   correct (§6.1), and extend every `AELIST` that is supposed to mean "the whole
   airplane" (§6.3).

The recurring theme in every failure above is that the wrong answer looks like an answer.
A zeroed control column gives a singular matrix with no explanation; a missing monitor grid
gives a small number instead of zero; 2D section data gives a beautifully converged trim at
the wrong incidence. The hand checks in §1 and the balance check in §3.4 are cheap, and
they are what stands between you and a plausible wrong airplane.
