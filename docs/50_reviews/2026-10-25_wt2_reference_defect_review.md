# Defect Review — #52, the WT2 reference that sideslipped the fin (2026-10-25)

**Status:** ✅ **agreed 2026-10-25.** P1 filed as #53; P2–P6 adopted as CLAUDE.md rules 1–3 (†) and new rule 6.

**Scope:** how #52 entered the code, why it survived 4.4 months and three gate-heavy steps,
what was built on it, and what to change so this defect class can't survive like that again.

**Evidence base:** git history (`a7e73d1`, `f62cffd`, `e2f5ca7`, `3c5992c`), the Step 65/66
records in `40_history/06_sol144_static_aeroelastic.md`, the theory walk-through
`20_theory/02_realistic_airplane_sol144.md`, and the pre- and post-fix trees run side by side
on the flagship (2026-10-25).

---

## 1. The defect

WT2 pressure matching sets each box's ratio as `r_k = cp_target_k / cp_ref_k`, where `cp_ref`
is the VLM loading at a reference normalwash. That reference was **−1 on every box**. On a
horizontal surface −1 is unit α. On a vertical surface it is unit **sideslip**. With a fin in
the model, the reference loaded the fin sideways, the fin's vortex system induced an
antisymmetric normalwash on the tailplane, and the tailplane ratios came out port/starboard
asymmetric. Fixed by a per-axis reference (`corrections.wt2_reference_cp`) shared by the
solver and both correction builders.

## 2. Timeline

| Date | Commit | Event |
|---|---|---|
| 2026-06-08 | `a7e73d1` | `apply_wt2` written for one planar wing. `w_ref = −1` is **correct** there. |
| 2026-06-14 | `f62cffd` | Multi-surface correction and the first Cessna example in the **same commit**. The example corrects a BETA fin (CAERO 300) in the same AIC as the HTP. **The defect is live from here.** |
| 2026-08-01 | `e2f5ca7` | Step 65 flagship inherits it; every later flagship-based step builds on it. |
| 2026-08-02 | Step 66 | Body overlays: the symptoms appear in print and are explained as physics (§3.3). |
| 2026-10-24 | `b4e224b` | DEF-M15 (#8) fixes the same defect *class* (a horizontal-surface formula loading the fin) but sweeps only the rate columns (§3.5). |
| 2026-10-25 | `3c5992c` | Found by eye in the viewer's corrected-vs-uncorrected HTP plot; fixed as #52. |

## 3. Why it survived

### 3.1 Every gate checked consistency, which a consistent error passes

| Gate | What it proves | Why it passed |
|---|---|---|
| T2 / B2 (cards regenerate from the CSV) | the committed cards are reproducible | the builder reproduces the bug bit-for-bit |
| Builder "achieved vs target" diagnostics; B5 (targets met to 1e-9) | the solve hit its targets | scored in the builder's own (wrong) reference |
| T3 / B3 (lift = n·W) | the trim closed | true for any loading the trim settles on |
| T3 band (`CZ_α ≈ 5.2 ± 0.5`) | plausibility | the error was 0.5 % |

None of them compared the corrected operator, at the condition the airplane actually flies, with
anything outside itself.

### 3.2 The error landed where nobody looked, and a constraint absorbed it

The flagship balances only Tz and Ry (`SUPORT 900,35`). The other four rigid DOFs are pinned by
`SPC1 1 1246 900`, and the deck comment says the antisymmetric DOFs "come out ~0 with no SPC
needed". That was never asserted. The pins silently reacted +116 N·m (1g) and +171 N·m (2.5g)
of spurious aero roll, which also put a spurious torque into the fuselage CBARs.

### 3.3 Visible symptoms were explained as physics

- Step 66 recorded "the cruciform changes the flying-surface ΔCp response by 4.5e-1" as the
  point of the cruciform/strip pair, and **gated it as a lower bound** (B4, `> 0.1`). That gate
  required the bug to be present. In the fixed code the α response is pinned (2.2e-4); real
  contamination remains in β (0.22) and in the camber baseline (0.027).
- The theory walk-through printed `SPLINE0 9500 … FY = −3.943E+01` at β = 0 — side force on a
  symmetric airplane in level flight — without comment.

### 3.4 The assumption was documented, so it read as a decision

`w_ref = −ones(n)` appeared as a stated convention in the card reference, `05a`, the theory doc
and two docstrings. Generalising from one planar surface to many surfaces on two axes was the
moment to re-test it, and nothing prompted that.

### 3.5 The rule-3 sweep was scoped to the function, not the assumption

DEF-M15 (#8, one day earlier) was the same class: "a formula derived for a horizontal wing,
applied to a vertical fin". Its sweep covered the rate columns. A sweep for the *assumption*
(`normal = +z`, "−1 on every box", "planar") would have found `w_ref` the same day.

### 3.6 The wing was almost untouched

The wing sits far from the fin (about 1 N port/starboard difference at 1g), so the
lift-dominated numbers everyone watches moved by 0.5 %. The damage was concentrated in the
tailplane and the lateral resultants.

## 4. What it affected

**Caused directly** (pre-fix vs post-fix, flagship, measured 2026-10-25):

| Quantity | Pre-fix | Correct |
|---|---|---|
| HTP balance load, 1g, starboard / port | −253.2 / −410.2 N | −332.5 / −332.5 N |
| HTP balance load, 2.5g, starboard / port | −311.6 / −522.9 N | −420.4 / −420.4 N |
| Aero rolling moment, 1g / 2.5g | +115.9 / +171.2 N·m | 0 |
| `CMX` per rad ANGLEA / ELEV | −0.0064 / −0.0082 | 0 |
| Vertical body panel side force at β = 0 | −39.4 N | 0 |
| Rigid `CZ_α` / `Cm_α` / `Cm_δe` | 5.3335 / −1.692 / −1.966 | 5.3079 / −1.609 / −1.859 |
| 1g trim elevator | −3.781° | −3.892° |

The tailplane loads are the ones that matter for stress: each side was about 24 % off, in
opposite directions.

**Built on it, all corrected in `3c5992c`:** Step 66 `TOTAL` body targets (derived from the
wrong bare `Cm_α`), the B4 gate and its narrative, the #1 gust anchors, the MLOADS `TABLED1 300`
initial elevator, the gust case deck, the theory walk-through numbers, and the #29 draft note
prototype numbers (caught before any #29 code was written).

**Same class, separate defect:** DEF-M15 (#8).

**Searched for and not found:** an earlier fix that patched a #52 symptom while attributing it
to something else. The commit log and the history/review docs show no asymmetry, roll or
side-force investigation. The only traces are the two Step 66 items in §3.3.

## 5. Proposed process changes

| # | Change | Addresses | Where it goes |
|---|---|---|---|
| **P1** | **Invariant gates for symmetry.** Symmetric decks at β = 0 must produce zero lateral load, equal mirror-pair loads, and zero reactions on pinned rigid DOFs. | §3.2, §3.6 | Issue **#53** |
| **P2** | **Closure gates are not benchmarks.** A regeneration, target-achieved or balance gate proves consistency only. Every calibration or correction feature also needs one gate at the actual operating condition, scored outside the builder. | §3.1 | CLAUDE.md rule 2 |
| **P3** | **No gate on an unexplained effect.** A gate that asserts a non-zero effect needs an independent prediction of its size. "Surprising but plausible" becomes an investigation item, not a lower-bound gate. | §3.3 | CLAUDE.md new rule 6 |
| **P4** | **Sweep the assumption, not the function.** A rule-3 sweep names the broken assumption in a searchable form (for example "normal = +z", "−1 on every box") and searches the whole codebase for it. | §3.5 | CLAUDE.md rule 3 |
| **P5** | **Re-test stated assumptions when a capability is generalised.** The design note lists the assumptions of the code being extended and says which stop holding (single → multi-surface, α → α+β, planar → canted, rigid → elastic). | §3.4 | CLAUDE.md rule 1 |
| **P6** | **Check printed output against invariants.** f06 blocks quoted in docs are read against the invariants of the case (β = 0 ⇒ no side force; symmetric ⇒ equal halves) before they are committed. | §3.3 | CLAUDE.md new rule 6 |

P1 is mechanical and catches the class. P2–P6 change how gates and notes are written; they cost
minutes per step and would each have caught #52 independently, P5 on 2026-06-14.

### 5.1 What not to change

- **No blanket tightening of tolerances.** The #52 numbers moved by 0.5–5 %, inside every
  sensible plausibility band. Tighter bands would only have produced noise.
- **Keep the regeneration gates.** T2 and B2 still do their job, which is proving the
  committed cards are reproducible. P2 adds a gate beside them rather than replacing them.
