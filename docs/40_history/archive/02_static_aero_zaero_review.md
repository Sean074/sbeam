# Static Aero Plan — ZAERO Review & Ranked Development Goals

Review of `docs/30_future/01_static_aero_plan.md` (the sbeam SOL 144 / static-aeroelastic plan) against the
ZAERO 9.2 documentation (Theory, User's, Applications Vol. 1, Basic Training), filtered to
the actual application context:

> **Subsonic, conventional airplane configuration, with aerodynamic corrections supplied
> from high-fidelity CFD or wind-tunnel test.**

The plan as written is a faithful, well-scoped clone of the textbook MSC NASTRAN SOL 144
formulation (VLM → spline → `K_aa − q·Q_aa`). That is a sound spine. The gaps below are
the places where the *stated application context* — especially "corrections from CFD or wind
tunnel" — is under-served by the plan, and where ZAERO's design choices point to
higher-value targets.

---

## 1. The central mismatch: correction model is too weak for the stated use case

The plan's entire correction story is one line: **`Wkk`, a diagonal multiplicative weighting
of the inviscid AIC** (Step 42, symbol table, risk KA3). For "tune the local lift-curve
slope per box," a diagonal `Wkk` is fine. For "make the model reproduce a CFD or wind-tunnel
load distribution on a real conventional configuration," it is the weakest of the methods
ZAERO actually ships, and it cannot represent the two effects that dominate a real wing's
baseline loads.

ZAERO (Theory §4, "Review of the AIC Correction Method") implements three correction tiers:

| ZAERO method | What it matches | Form | sbeam plan today |
|---|---|---|---|
| Downwash weighting matrix (Pitt–Goodman) | a **given pressure distribution** `{Cp_given}` | `[AIC*] = [AIC][WT2]`, full matrix | ✗ (only diagonal `Wkk`) |
| Force/moment correction (Giesing) | **given spanwise lift & torque** `{F_given}` | `[AIC*] = [WT1][AIC]`, full matrix | ✗ |
| ZTAW (successive kernel expansion) | in-phase + recovered out-of-phase, unsteady | governing-equation based | N/A (Phase D/E only) |

Two structural points for static work:

- For **static aeroelastics k = 0, only the in-phase (steady) correction matters** — ZTAW's
  whole purpose (recovering correct out-of-phase pressure) is irrelevant until flutter. So
  the *right* target for this plan is the **steady force/moment-matching and
  pressure-matching corrections**, which are exactly the k = 0 limit ZTAW itself starts
  from. This is squarely in Phase A/C scope and needs no DLM.
- ZAERO's trim path additionally lets you **inject the CFD/WT steady pressures directly as
  the mean-flow aerodynamics** (User's §5.8.4, `CHORDCP`/ZTAIC): the trim solution then
  becomes a *perturbation about the CFD/WT operating point* rather than a perturbation about
  inviscid VLM. For a conventional airplane this is the difference between "trims around a
  realistic load" and "trims around a flat-plate guess."

**Implication:** `Wkk`-diagonal-only is the single biggest under-build relative to the
application context, and the fix lives entirely inside subsonic/static scope.

---

## 2. Missing baseline-incidence (camber + twist + control) load — `w_g`/W2GJ

The plan's matrix set carries only `w_j` = downwash from *structural deflection* (`Djk·G_kg·u`).
A conventional wing's rigid load is set mostly by **built-in twist (washout), airfoil camber,
and incidence** — a *permanent* downwash field that exists at zero structural deflection.
NASTRAN calls this `W2GJ` (additional/initial normalwash, the `e_j`/`w_g` column); ZAERO
carries it through airfoil/camber definition and the rigid-load columns.

The plan has no term for it. Without `w_g`, the "rigid aero loads" the trim balances
(`q·Q_ax·δ_x + f_ext`) are missing the camber/twist contribution — i.e. the baseline spanwise
load of the actual aircraft. This is also the natural and *correct* entry point for a CFD/WT
correction expressed as an **additive incidence** (`Δα_j` per box), which is often how CFD-vs-VLM
deltas are most robustly applied (additive `w_g` correction is better-conditioned than
multiplicative `Wkk` near low-load boxes).

**Implication:** add an additive baseline-downwash column `w_g` (camber/twist/incidence + an
additive CFD/WT `Δα` correction) alongside the multiplicative `Wkk`. Small change, large
correctness gain for conventional configs.

---

## 3. Over-determined trim — the plan only handles the square case

The plan's trim solve assumes free trim variables = constraints and flags the mismatch as a
fatal singularity (risk KC2: "emit a clear diagnostic"). ZAERO treats the **over-determined
trim system as a first-class case** (User's §1.10, §5.8.2–5.8.3): more unknowns than
equations, solved by minimizing a user objective (`TRIMOBJ`) subject to constraint functions
(`TRIMCON`), with longitudinal/lateral DOF-count rules (§5.8.1) to keep the square sub-system
non-singular. Real conventional-aircraft trim (multiple control surfaces, redundant
effectors) is routinely over-determined.

**Implication:** design the trim solver around a least-squares / constrained-minimization
core from the start (square solve is the special case), rather than bolting it on later.

---

## 4. Architecture: modal trim vs. the plan's direct g-set assembly

The plan assembles `Q_aa` on the structural a-set and solves `(K_aa − q·Q_aa)u_a = …`
directly, with a dense `Q_aa` glued onto sparse `K` (risk KC1). ZAERO's trim module uses the
**modal approach** explicitly because it "formulates a reduced-order trim system… with much
less computational cost than the direct method" (User's §1.10), reusing the free-vibration
modes.

sbeam already has SOL 103. For a beam idealization the direct method is perfectly adequate
and arguably clearer, so this is **not a required change** — but the modal path (project
loads/flexibility onto a handful of SOL 103 modes) is the same machinery Phase E flutter will
*require*, and it sidesteps the dense-`Q_aa`-into-sparse-`K` friction. Worth at least keeping
the direct solver modal-ready.

---

## 5. Splining — ATTACH and a separate force spline are the practical gaps

The plan ships `SPLINE2` (beam, primary) + optional `SPLINE1` (IPS). ZAERO ships **five**
(User's §1.4): Thin-Plate (`SPLINE3`), Infinite-Plate (`SPLINE1`), Beam (`SPLINE2`),
**Rigid-Body Attachment (`ATTACH`)**, and Zero-Displacement (`SPLINE0`) — plus a *separate*
force-mapping spline (`SPLINEF`). For a conventional configuration the two that earn their
keep beyond beam-spline are:

- **`ATTACH` (rigid-body attachment):** the clean way to hang control surfaces, tips,
  nacelles/pylons, or any panel group with no local FEM grid onto a master node. The plan
  currently has no story for control-surface boxes that aren't sitting on the beam axis.
- **`SPLINE0` (zero-displacement):** pin panels that shouldn't move — useful for fuselage
  carry-through / symmetry-plane boxes.

`SPLINE3` (full 3-D thin-plate) is lower priority for a beam-modeled wing; skip until a
surface-modeled tail/fuselage appears.

---

## 6. Symmetric half-model for *asymmetric* flight

The plan handles x-z symmetry only as VLM mirror-image vortices for the rigid lift case
(Step 41). ZAERO's trim runs a **half model even for asymmetric flight conditions** (User's
§1.10) by carrying symmetric+antisymmetric DOF sets. Lateral-directional trim (roll, yaw,
aileron/rudder) on a conventional airplane needs this. The plan's symmetry handling is
currently lift-only and won't support lateral trim.

**Implication:** decide early whether lateral-directional trim is in scope; if yes, the
half-model must carry antisymmetric loading, not just mirrored lift.

---

## 7. Output: distributed flight loads for downstream stress

The plan's SOL 144 output is f06 displacements + recovered CBAR loads (Steps 50, 52). ZAERO
additionally emits **trim flight loads as FORCE/MOMENT cards at the FEM grid points** for
subsequent detailed stress analysis (User's §1.10). For an actual loads process this is the
deliverable the stress group consumes. Cheap to add given `G_kgᵀ` already produces grid
loads — expose them as a load-card export, not just an f06 block.

---

## Ranked development goals

Ranked by **value to the stated application context (subsonic conventional aircraft, CFD/WT
corrections) per unit of implementation risk.** "Step refs" point into `docs/30_future/01_static_aero_plan.md`.

| Rank | Goal | Why it ranks here | Touches | Effort |
|---|---|---|---|---|
| **1** | **Force/moment-matching + pressure-matching AIC correction** (full `[WT1]`/`[WT2]`, not just diagonal `Wkk`). Match given spanwise lift/torque or `{Cp}` from CFD/WT. | The headline requirement. Diagonal `Wkk` cannot reproduce a real load distribution; force-matching can, and at k = 0 it's fully in subsonic/static scope. | `corrections.py`, `aero_model.py`, new bulk cards | M |
| **2** | **Additive baseline downwash `w_g` (W2GJ):** camber + twist + incidence, plus additive CFD/WT `Δα` correction. | Without it the "rigid aero load" the trim balances omits the wing's built-in load — wrong baseline for any conventional config. Best-conditioned way to apply CFD deltas. | `integration.py`, `aero_model.py`, airfoil/incidence input | S–M |
| **3** | **Over-determined trim solver** (objective + constraints; square case as special case). | Real multi-effector trim is over-determined; the plan currently *fatals* on it. Designing it in is far cheaper than retrofitting. | `sol144.py`, `Trim`/new `TrimObj`/`TrimCon` cards | M |
| **4** | **Inject CFD/WT steady pressures as the trim mean-flow** (ZTAIC/`CHORDCP`-style): trim as a perturbation about the measured operating point. | Highest-fidelity use of CFD/WT data; reuses #1/#2 plumbing. The "right" way to honor the correction requirement end-to-end. | `sol144.py`, `aero_model.py` | M |
| **5** | **`ATTACH` rigid-body spline** (+ `SPLINE0`). | Needed to mount control surfaces / tips / nacelles that have no local beam grid — common on conventional configs. Unblocks proper `AESURF` boxes. | `spline.py`, new cards | S–M |
| **6** | **Half-model antisymmetric loading for lateral-directional trim.** | Required for roll/yaw/aileron/rudder trim; the plan's symmetry is lift-only. Scope decision needed up front. | VLM, spline, `sol144.py` | M–L |
| **7** | **Flight-load export as FORCE/MOMENT cards at grids.** | The deliverable a loads/stress process actually consumes; trivial given `G_kgᵀ`. | `results.py`, `f06_writer.py` / load-card writer | S |
| **8** | **Keep the trim solver modal-ready** (project onto SOL 103 modes). | Not required for beams, but it's the exact basis Phase E needs and avoids dense-`Q_aa`/sparse-`K` friction. Architectural insurance. | `sol144.py`, `aero_model.py` | S (design only) |

**Lower priority / defer:** `SPLINE3` 3-D thin-plate (no surface FEM yet); anything ZTAW /
unsteady (Phase D/E — out of static scope); supersonic methods (out of subsonic scope).

---

## Bottom line

The plan's structural spine and validation ladder (V-A1 → V-C2, Goland divergence,
HA144-class derivatives) are solid and should stay. The reweighting it needs is at the
**aero-correction layer**: the plan treats CFD/WT correction as an afterthought (`Wkk = I` by
default, one diagonal), whereas for this application it is the *point*. Promote
force/moment-and-pressure matching and an additive `w_g` correction from "Step 42 detail" to
**first-class Phase A/C deliverables**, design the trim solver for the over-determined case,
and the tool will actually do what the application demands — all without leaving the subsonic,
static, no-DLM envelope.

---

### Sources

ZAERO 9.2 documentation, `~/Documents/Library/Software_Manuals/`:
- *Theoretical Manual, 3rd Ed.* — §4 "Review of the AIC Correction Method" (downwash
  weighting / force correction / ZTAW), Eqs. 4.55–4.62.
- *User's Manual, 3rd Ed.* — §1.4 (3-D Spline module, four methods), §1.10 (Trim module:
  modal approach, over-determined trim, half-model asymmetric flight, grid-load output),
  §5.8.1–5.8.4 (singular trim, `TRIMOBJ`/`TRIMCON` objective/constraints, ZTAIC/`CHORDCP`
  steady-pressure injection), spline-card map (`SPLINE0/1/2/3`, `ATTACH`, `SPLINEF`).
- *Applications Vol. 1* and *Basic Training* — corroborating worked trim/correction examples.
