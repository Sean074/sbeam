# A Realistic Airplane Through SOL 144 — the Cessna 210 Flagship

*A tutorial for engineers who have a working SOL 144 solver and now have to point it at a
real airplane. It walks the flagship sample family layer by layer — structure, mass,
aero mesh, splines, corrections, trim, monitors, mass cases, transient — and then reads
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
| `sample/cessna210_flagship_section_data.csv` | spanwise section coefficients |

The drivers are thin: a `SOL 144` line, a `TITLE`, a case-control `INCLUDE` of the shared
bulk file, and their subcases. Everything physical lives in one place.

Gated by `tests/aero/test_cessna210_flagship.py` (24 checks) and
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
Free-flight rigid-body coupling — where ANGLEA, PITCH and URDD3 evolve — is Step 63.

The same restraint explains why the aero/inertia closure residual, machine-small at t = 0,
grows as the elevator deflects: away from the initial condition the extra lift is balanced
by the restraint rather than by an inertial response.

---

## 6. Limitations and roadmap

| Limitation | Where it lifts |
|---|---|
| No body/fuselage aero panels — the fuselage carries no lift or moment | Step 66 (flagship stage 2); EIDs 6000/7000 reserved |
| Steady aerodynamics only (VLM at k = 0); no unsteady, no flutter | Phase D — DLM, SOL 145 |
| Transient is restrained and open-loop; ANGLEA/PITCH/URDD frozen | Step 62 (modal basis), Step 63 (free flight) |
| One correction operating region per surface, no warning on exit | `section_data` v2; T3b gates it meanwhile |
| Mach matched exactly, no interpolation | as above |
| Euler–Bernoulli beams, no shear flexibility | Phase 2 (Timoshenko) |
| Correction cards written at 7 significant digits | DEF-M12 |

---

## 7. If you are building your own deck

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

The recurring theme in every failure above is that the wrong answer looks like an answer.
A zeroed control column gives a singular matrix with no explanation; a missing monitor grid
gives a small number instead of zero; 2D section data gives a beautifully converged trim at
the wrong incidence. The hand checks in §1 and the balance check in §3.4 are cheap, and
they are what stands between you and a plausible wrong airplane.
