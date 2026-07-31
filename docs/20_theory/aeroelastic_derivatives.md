# Aeroelastic Stability Derivatives — Rigid, Restrained, and Unrestrained

*A tutorial for engineers new to static aeroelasticity. It explains the three
stability-derivative columns sbeam prints for a SOL 144 trim — **rigid**, **elastic
restrained**, and **elastic unrestrained (mean-axis)** — the algorithms behind them (the
same ones MSC Nastran uses), and the equivalent ZAERO modal formulation used as an
independent cross-check. The full solver theory lives in
[`01_aeroelastics_theory.md`](01_aeroelastics_theory.md); this document zooms in on the
derivatives only.*

---

## 1. What is a stability derivative, and why does flexibility change it?

A **stability derivative** answers a simple question: *if I change one flight variable by
one unit, how much does the total force or moment on the airplane change?* For example
$C_{Z_\alpha}$ = change in vertical-force coefficient per radian of angle of attack, and
$C_{m_\alpha}$ = change in pitching-moment coefficient per radian. Flight-mechanics,
handling-qualities, and control-law work all start from these numbers.

For a **rigid** airplane the answer comes straight from aerodynamics. A **flexible**
airplane is more interesting: increase α and the extra lift *bends and twists the
structure*, which changes the local incidence of every panel, which changes the lift
again. The measured derivative therefore includes an **aeroelastic feedback loop**:

```
        Δα  →  extra aero load  →  structure deforms  →  panel incidences change
                     ↑                                            │
                     └────────────── more/less load ←─────────────┘
```

At low dynamic pressure $\bar q$ the loop gain is tiny and the flexible derivative is
almost the rigid one. As $\bar q$ grows the loop gain grows (for a conventional aft-swept
or coupled wing it can either *increase* or *decrease* the derivative), and at the
**divergence** dynamic pressure the loop gain reaches 1 and the response is unbounded.

There is one more subtlety, and it is the reason there are *two* flexible columns rather
than one. To solve the structural problem you must hold the airplane somehow — a
free-flying structure has a singular stiffness matrix. **How you imagine holding it
changes the answer**:

| Column | Physical picture | What is held |
|--------|-----------------|--------------|
| **Rigid** | wind-tunnel model machined from solid steel | nothing deforms |
| **Elastic restrained** | flexible model **bolted to a sting** at one reference point | the SUPORT point is clamped; the structure deforms *relative to it* |
| **Elastic unrestrained** | the **free-flying** airplane | nothing — the airplane is free to accelerate; deformation is measured about the *mean axis* |

The restrained number depends on where you put the sting. The unrestrained number does
not — it is the one a flight-test derivative extraction would see. NASTRAN's HA144A
example prints both, and so does sbeam.

> **Terminology warning — "restrained" is about SUPORT, not SPC.** The r-set that gets
> held in the restrained method comes from the **`SUPORT`** card (the free-flight
> rigid-body DOFs — for HA144A, `SUPORT,90,35` = Tz and Ry at the fuselage reference
> grid). Ordinary `SPC` constraints (symmetry planes, unused DOFs) are removed from the
> problem *before any of this* and are identical in all three columns. If you hear
> "the SPC'd derivative", the speaker almost always means the SUPORT-restrained one.

### The running example — HA144A

Everything below is illustrated with NASTRAN's classic **HA144A** forward-swept-wing
airplane (`sample/ha144a_fullspan_sbeam.bdf`), at Mach 0.9 and two dynamic pressures:
q = 40 psf (barely flexible) and q = 1200 psf (30 % of the divergence q). The reference
values are MSC Aeroelastic Analysis User's Guide **Table 7-1**
(`.refs/MSC_Nastran_2021.3_Aeroelastic_Analysis_User_Guide.pdf`, PDF p. 230):

| $C_{Z_\alpha}$ (1/rad, sbeam sign: +up) | q = 40 | q = 1200 |
|---|---|---|
| Rigid | 5.071 | 5.071 |
| Elastic restrained | 5.103 | 6.463 |
| Elastic unrestrained | 5.127 | 7.772 |

Note the ordering **unrestrained > restrained > rigid** for this airplane (the
forward-swept wing washes *in* under load — flexibility adds lift), and how the spread
explodes with q: at q = 40 the three values differ by ~1 %, at q = 1200 by ~50 %.

---

## 2. The machinery all three methods share

sbeam assembles the static aeroelastic problem on the structural **a-set** (all DOFs
surviving the RBE2/RBE3/RBAR reduction and the SPC removal):

$$
\big(K_{aa} - \bar q\,Q_{aa}\big)\,u_a \;=\; \bar q\,Q_{ax}\,u_x \;+\; P_a .
$$

Read each piece as:

- $K_{aa}$ — ordinary structural stiffness.
- $Q_{aa}$ — the **aerodynamic feedback matrix**: aero force produced *per unit
  structural deflection* (spline → downwash → AIC → pressures → spline back). The term
  $-\bar q\,Q_{aa}$ acts like a (generally unsymmetric) *negative* spring: the
  "aeroelastic stiffness" $K^a = K_{aa}-\bar q\,Q_{aa}$ softens as $\bar q$ rises.
- $Q_{ax}$ — aero force per unit **trim variable** $u_x$ (α, pitch rate q̂, elevator
  δe, …); one column per variable.
- $P_a$ — everything prescribed: the $w_g$ (W2GJ) built-in-incidence load, inertial
  loads from prescribed accelerations, etc.

The `SUPORT` card splits the a-set into the **r-set** (the supported rigid-body DOFs,
size $n_r$ — 2 for HA144A) and the **l-set** ("leftover", everything else). All three
derivative methods are different answers to *what to do with the r-set*.

A derivative in any column is finally non-dimensionalised the same way:

$$
C_Z = \frac{F_z}{\bar q\,S_\text{ref}}, \qquad
C_{MY} = \frac{M_y}{\bar q\,S_\text{ref}\,c_\text{ref}} \quad(\text{nose-up positive}),
$$

with forces/moments summed about the aero reference point (the `AEROS` RCSID origin).

---

## 3. Method 1 — Rigid derivatives

*(code: `sol144.compute_rigid_derivs`)*

Hold the structure perfectly rigid: $u_a = 0$, no feedback at all. For each trim
variable, take its downwash column, push it through the (corrected) AIC to get pressures,
integrate to forces:

$$
\frac{\partial F}{\partial u_x}\bigg|_\text{rigid}
   = \bar q\, S_{kj}\,\big(A_{jj}^*\big)^{-1} D_{jx} .
$$

In words: *unit α → downwash on every box → AIC inversion → box pressures → sum forces
and moments.* No structural matrix appears anywhere; the result is independent of $\bar
q$ (as a coefficient) and of the SUPORT location (for forces; moments use the fixed aero
reference).

This is the cheapest and most robust column — for HA144A sbeam matches NASTRAN's rigid
$C_{Z_\alpha}=5.071$, $C_{m_\alpha}=-2.871$ to four significant figures — and it is the
baseline against which the flexible increments below are judged.

---

## 4. Method 2 — Elastic restrained derivatives (SUPORT held)

*(code: `sol144._compute_restrained_derivs`; MSC UG Eqs. 2-116 … 2-122)*

Now let the structure flex, but **clamp the SUPORT point**: set $u_r = 0$ and let only
the l-set deform. Think of the flexible wind-tunnel model bolted to its sting.

Because the trim problem is *linear* in every variable, the derivative does not need
finite differencing; it falls straight out of the factorised system. Per trim variable
(one column of the combined aero + inertial sensitivity $C_{ax}$):

1. **Elastic response per unit variable** — solve with the *aeroelastic* stiffness, so
   the feedback loop is fully converged:

   $$
   \frac{\partial u_l}{\partial u_x}
      = \big(K_{ll} - \bar q\,Q_{ll}\big)^{-1} C_{ax,l} .
   $$

   The $(K-\bar qQ)^{-1}$ is where the loop lives: expanding it as a geometric series
   $K^{-1} + K^{-1}(\bar qQ)K^{-1} + \dots$ shows the load→deflection→load→… cycles being
   summed to convergence. It blows up exactly at divergence.

2. **Total force per unit variable** — the direct aero column plus the aero force from
   that elastic response:

   $$
   \frac{\partial w}{\partial u_x} = D_{jx} + D_{jk}\,G_{kg}\,\frac{\partial u}{\partial u_x},
   \qquad
   \frac{\partial F}{\partial u_x} = \bar q\,S_{kj}\big(A_{jj}^*\big)^{-1}\frac{\partial w}{\partial u_x} .
   $$

3. Non-dimensionalise as in §2.

At q = 40 the flexible increment is tiny (5.071 → 5.103, +0.6 %); at q = 1200 it is huge
(→ 6.46, +27 %). **The catch:** hold the model somewhere else and you get a different
number, because "the structure deforms relative to the support" means the deformation
field itself depends on the support. That is physically fine for a sting-mounted test —
and physically wrong for a free airplane. Hence method 3.

---

## 5. Method 3 — Elastic unrestrained derivatives (mean axis / inertia relief)

*(code: `sol144._compute_unrestrained_derivs`; MSC UG Eqs. 2-111 … 2-134 — implemented
verbatim, DMAP matrix names kept in the code comments)*

### 5.1 The two ideas

**Idea 1 — the airplane accelerates instead of reacting.** A free airplane has no
ground to push against. Apply a load and the *whole vehicle accelerates*; the load that
deforms the structure is only the part left over after the rigid-body inertia "absorbs"
its share (distributed over the mass). This is called **inertia relief**. The derivative
we want is the *net force on the accelerating vehicle* per unit trim variable — i.e.
$m_r\,\ddot u_r$, the rigid mass times the rigid acceleration the variable produces.

**Idea 2 — deformation needs a support-independent reference: the mean axis.** With
nothing clamped, "how much did it deform?" needs a frame. The **mean axes** are defined
so that elastic deformation, weighted by the mass distribution, produces **no net motion
of the CG and no net rotation** — formally, the deformation is *mass-orthogonal to the
rigid-body modes*:

$$
\begin{bmatrix} D \\ I \end{bmatrix}^{\mathsf T}
\begin{bmatrix} M_{ll} & M_{lr} \\ M_{rl} & M_{rr} \end{bmatrix}
\begin{bmatrix} u_l \\ u_r \end{bmatrix} = 0 ,
$$

where $D = -K_{ll}^{-1}K_{lr}$ is the **rigid-body mode matrix** — the shape the l-set
takes when you move the SUPORT DOFs rigidly (built from the *structural* stiffness only;
it is pure geometry). This constraint is what makes the final answer independent of where
the SUPORT was placed.

### 5.2 The algorithm

Collect three block-rows in the three unknowns $(u_l,\,u_r,\,\ddot u_r)$, with
$K^a \equiv K - \bar q\,Q$ and $m_r = M_{rr}+M_{rl}D+D^{\mathsf T}M_{lr}+D^{\mathsf T}M_{ll}D$
(the vehicle's total rigid mass/inertia about the SUPORT):

| Row | Equation | Meaning |
|-----|----------|---------|
| 1 | $K^a_{ll}u_l + K^a_{lr}u_r + (M_{ll}D{+}M_{lr})\ddot u_r = -K^a_{lx}u_x$ | l-set force balance (with inertia loading from the rigid acceleration) |
| 2 | $(D^{\mathsf T}M_{ll}{+}M_{rl})u_l + (D^{\mathsf T}M_{lr}{+}M_{rr})u_r = 0$ | mean-axis constraint |
| 3 | $D^{\mathsf T}(\text{row 1}) + (\text{r-set row})$ | whole-vehicle (rigid-projected) equilibrium: ends in $m_r\ddot u_r$ |

Then eliminate, in this order (MSC's DMAP names in parentheses):

1. Solve row 1 for $u_l$ through the **aeroelastic** $K^a_{ll}$ — same converged
   feedback loop as the restrained method (ARLR, AMLR, ALX).
2. Put that into row 2 and solve for $u_r$ — note $u_r$ is eliminated **through the
   mass matrix**, not the stiffness: this is the mean-axis bookkeeping (M2RR → M4RR,
   K4LX).
3. Put both into row 3. What remains is one small ($n_r \times n_r$) relation
   $\mathrm{MIRR}\,\ddot u_r + \mathrm{KR1ZX}\,u_x = 0$ (per-variable part), so

   $$
   \boxed{\;Z1ZX \;=\; m_r\,\ddot u_r \text{ per unit } u_x \;=\; -\,m_r\,\mathrm{MIRR}^{-1}\,\mathrm{KR1ZX}\;}
   $$

   is the **dimensional unrestrained derivative** — transfer it from the SUPORT point to
   the aero reference and non-dimensionalise as in §2. The same chain applied to the
   $w_g$ baseline load gives the unrestrained **intercepts** ($C_{Z_o}$, $C_{m_o}$).

### 5.3 What it is *not* (two tempting wrong turns)

Both of these were implemented in sbeam's history, produced plausible-looking numbers,
and were wrong — they are preserved as warnings (`docs/40_history`, Step AC2):

- **Not** "project the loads with an inertia-relief projector, then do a restrained
  solve". Filtering the load through $I - M\Phi m_r^{-1}\Phi^{\mathsf T}$ and solving as
  in §4 gave $C_{Z_\alpha}$ ≈ 1.5× too high at q = 1200.
- **Not** "the aero force integrated over the converged *free-free* aeroelastic
  response" $\big(K - P\bar qQ\big)^{-1}$. That is a legitimate physical object, but it
  is not the printed NASTRAN quantity, and it lets airload feed back through the
  rigid-body DOFs in a way the derivative definition excludes.

The correct operator sits *between* the restrained and free-free answers, which is
exactly where NASTRAN's Table 7-1 values lie (6.46 < **7.77** < 11.7 at q = 1200).

### 5.4 Sanity anchors

- As $\bar q\to 0$ every aeroelastic term vanishes and the chain collapses to the
  rigid-projected rigid derivative — the rigid column, recovered exactly.
- As vehicle mass $\to\infty$ the airplane cannot accelerate, inertia relief vanishes,
  and the chain reduces to the restrained column.
- Validation status in sbeam (post AC7 close-out, 2026-07-05): at q = 40 all
  restrained and unrestrained longitudinal columns match Table 7-1 within 0.2 %/1 %.
  At q = 1200 the α and rate columns (CZα, CZq, CMq) are gated live at ≤2/2.5 %
  (restrained and unrestrained); the pitching-moment/ELEV columns carry a documented
  3–5 % residual attributed to canard-wake/wing-root interference (steady VLM vs
  NASTRAN's k→0 DLM) — tracked as backlog item **AC8/AE15**. The operator itself is
  proven correct (§6).

---

## 6. The ZAERO formulation — same physics in mode coordinates

*(ZAERO Theoretical Manual Ch. 12, Eqs. 12.9–12.16, `.refs/ZAERO_9.2_Theo_3rd_Ed.pdf`;
this is also the ASTROS lineage behind the ADA370433 reference values)*

ZAERO reaches the same unrestrained derivative by a completely different route, and the
route makes the *physics* easier to see. Work in mode coordinates: let $\phi_r$ be the
rigid-body modes and $\phi_e$ the **free-free elastic modes**, which are automatically
mass-orthogonal to the rigid ones ($\phi_e^{\mathsf T}M\phi_r=0$ — the mean-axis
condition, satisfied by construction). Then:

$$
C_\text{unrest} \;=\; \frac{1}{\bar q S}\,
\phi_r^{\mathsf T}\!\underbrace{\Big[\,\frac{\partial f}{\partial a}}_{\text{rigid part } S_R}
\;+\;
\underbrace{\bar q\,Q\,\phi_e\big(K_{ee}-\bar q\,Q_{ee}\big)^{-1}\phi_e^{\mathsf T}\,\frac{\partial f}{\partial a}}_{\text{elastic increment } S_e}\Big] .
$$

Read it right to left: *unit trim variable → aero force → project onto the elastic modes
→ converged aeroelastic solve in **elastic-mode space only** → resulting extra airload →
project the total onto the rigid modes to get net force and moment.*

Two things drop out of the algebra and explain §5.3:

- The inertia-relief load **never appears** in the derivative operator — the
  mass-orthogonality $\phi_e^{\mathsf T}M\phi_r=0$ kills it identically. (In the MSC
  chain the same cancellation happens implicitly through the mass-weighted elimination.)
- The rigid modes only **project** force; the airload never feeds back through the
  rigid-body DOFs inside the solve. That is precisely the ingredient the "converged
  free-free" wrong turn adds, and why it overshoots.

**Practical differences.** The modal form needs the free-free elastic modes (a SOL 103
by-product) and is exact only as the retained-mode count grows — ZAERO's guidance is
~50 modes for a real airframe. The MSC chain works directly in physical DOFs with no
truncation. In sbeam the MSC chain is the shipped implementation; the ZAERO form (with a
complete mass-orthogonal complement basis instead of truncated modes, which makes it
exact) was implemented as a throwaway verification script during development — **the two
formulations agreed to four-plus decimals at both q = 40 and q = 1200**, which is the
proof that sbeam's operator is correct independent of the reference values.

---

## 7. Side-by-side summary

| | Rigid | Elastic restrained | Elastic unrestrained |
|---|---|---|---|
| Physical picture | solid-steel model | flexible model on a sting | free-flying airplane |
| Structure solve | none | $(K_{ll}-\bar qQ_{ll})^{-1}$, $u_r=0$ | same l-set solve **+** mean-axis elimination of $u_r$ through the mass matrix |
| Depends on SUPORT location? | no | **yes** | no (mean axis restores invariance) |
| Uses the mass matrix? | no | only for URDD columns | yes — $D$, $m_r$, and the constraint are mass-weighted |
| Derivative is… | integrated aero force | integrated aero force incl. elastic increment | net force on the accelerating vehicle, $m_r\ddot u_r$ |
| HA144A $C_{Z_\alpha}$, q=1200 | 5.071 | 6.463 | 7.772 |
| sbeam code | `compute_rigid_derivs` | `_compute_restrained_derivs` | `_compute_unrestrained_derivs` |
| f06 column | RIGID | ELASTIC RESTRAINED | ELASTIC UNRESTRAINED |

Notes for the practitioner:

- **Which one do I use?** For loads about a test-rig condition: restrained. For flight
  mechanics, handling qualities, and control design of the real vehicle: unrestrained.
  Always sanity-check both against the rigid column — the flexible/rigid ratio (the
  *aeroelastic efficiency*) should trend smoothly with $\bar q$.
- The URDD (acceleration) trim variables have **no unrestrained column** — in the
  mean-axis formulation the rigid accelerations *are* the unknowns $\ddot u_r$, not
  inputs. sbeam prints `N/A` there (NASTRAN handles them via its TRX selection matrix).
- All three columns share the same corrected AIC $\big(A_{jj}^*\big)^{-1}$, splines, and
  $w_g$ baseline — so correction cards (WKK/WT2/W2GJ) affect all three consistently.

## References

- MSC Nastran Aeroelastic Analysis User's Guide, Ch. 2 "Static Aeroelasticity",
  Eqs. (2-104)–(2-142) — the restrained/unrestrained algorithms implemented here
  (`.refs/MSC_Nastran_2021.3_Aeroelastic_Analysis_User_Guide.pdf`, PDF pp. 70–82;
  Table 7-1 reference values PDF p. 230).
- ZAERO 9.2 Theoretical Manual, Ch. 12 "Formulation of the Static Aeroelastic/Trim
  Analysis", Eqs. (12.4)–(12.16) (`.refs/ZAERO_9.2_Theo_3rd_Ed.pdf`, PDF pp. 270–276).
- Zeiler, T. A., *Including Aeroelastic Effects in the Calculation of X-33 Loads and
  Control Characteristics*, NASA/ASEE 1997 (`.refs/19990010052.pdf`) — a compact,
  readable mean-axis / inertia-relief derivation.
- Riso, C. et al., *Nonlinear Aeroelastic Trim of Very Flexible Aircraft Described by
  Detailed Models*, J. Aircraft 55(6), 2018 (`.refs/`) — Sec. II.A restates the linear
  restrained trim; the paper generalises inertia relief to large deflections.
- Rodden, W. P. and Love, J. R., "Equations of Motion of a Quasisteady Flight Vehicle
  Utilizing Restrained Static Aeroelastic Characteristics", J. Aircraft 22(9), 1985 —
  why mean-axis rotations matter when *restrained* coefficients are used in flight EOM.
- sbeam internals: `docs/20_theory/01_aeroelastics_theory.md` §5.4 (derivation summary),
  `docs/40_history/00_completed_development.md` Step AC2 (implementation history and the
  two documented wrong turns), `tests/aero/test_ae1_restrained_derivs.py` (gates).
