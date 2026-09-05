# SPLINE9 — FE-Consistent Hermite Beam Spline (sbeam extension)

**Status:** Design proposal — not yet implemented.
**Target release:** unscheduled (candidate for a post-steady-close-out release).
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-07-05

This document proposes a non-standard sbeam BDF card, `SPLINE9`, that offers a cubic
**Hermite** beam spline as an alternative to the NASTRAN infinite beam spline that
`SPLINE2` implements since the AC7/AE14 close-out (2026-07-05). It is the successor
proposal to the pre-AC7 SPLINE2 implementation, rebuilt on the current conventions and
with its known defect fixed.

---

## 1. Motivation

### 1.1 The engineering argument — FE consistency

For a CBAR (Euler-Bernoulli) model, the element shape functions between grids **are**
cubic Hermite polynomials in the nodal deflections and rotations. A Hermite spline
through the grid deflections *and rotations* therefore reproduces the FE solution's
**exact** displacement field between grids — the transfer is kinematically consistent
with the structure being splined.

The NASTRAN infinite beam spline (current `SPLINE2`) is instead a physical
beam-on-point-supports *fit*: even with rotations rigidly attached (`DTHX = DTHY = 0`)
its interpolant between stations is the natural-beam solution, not the FE field. The
AC7 Phase-2 diagnostics quantified the difference on the swept HA144A wing spline:

| Imposed analytic field | Hermite (pre-AC7) | Infinite beam spline (current) |
|---|---|---|
| Rigid modes (all 6) | exact (1e-12) | exact (1e-12, by construction) |
| Linear bend | exact | exact |
| Parabolic bend w = c·s² | **exact (ratio 1.000 per box)** | interpolated, ~10–25% local slope error between coarse stations |

For sbeam-native stick models — a handful of EA grids, no LE/TE stringer pairs, the
`cessna210`/`val_dihedral_trim` style of deck — the Hermite transfer is the more
accurate option on coarse structural meshes, and it needs no off-axis grids to carry
twist (grid torsion rotations attach directly).

### 1.2 Why this is NOT a revival of the old code

The pre-AC7 SPLINE2 implementation cannot be restored as-is:

1. **Convention mismatch.** It used the retired "spline axis = CID x-axis" frame and
   the old `DTHX`-as-torsion-flag semantics. SPLINE9 must adopt the current MSC frame
   (axis = CID **y**-axis, chord arms along x, deflection along z) and the current
   DTHX/DTHY meanings so the two spline cards read consistently in one deck.
2. **Known defect.** The old implementation omitted the twist-gradient chordwise term
   `θ′(t)·ŷ[0]·χ` in the streamwise-incidence recovery (AC7 finding: LE boxes ×0.67,
   TE boxes ×1.19 under a linear-twist field). SPLINE9 fixes this: with
   z(t, χ) = h(t) − χ·θ(t), the incidence is the full
   −∂z/∂x = −[ŷ[0]·(h′ − χ·θ′) − x̂[0]·θ].
3. **Canard-camber behaviour is opt-in, documented.** A Hermite spline through grid
   rotations acquires chordwise curvature ("camber") from the interpolant where the
   NASTRAN 2-point linear fit gives a rigid plane — that is a *feature* when the
   splined surface genuinely bends, and a *difference from NASTRAN* when it does not.
   The card documentation must state this explicitly (it is why HA144A validation
   decks must stay on SPLINE2).

### 1.3 What SPLINE9 delivers

- An FE-consistent structural-to-aero transfer for beam stick models: exact
  reproduction of the CBAR displacement field, including between-station curvature.
- Direct twist attachment from grid torsion rotations — the natural idiom for EA-only
  collinear SET1s (no stringer-pair modelling required just to carry twist).
- The same g_slope/g_disp operator interface, virtual-work force pairing at the
  ¼-chord force point, and rigid-body exactness gates as SPLINE2.

---

## 2. Card design

```
SPLINE9, EID, CAERO, ID1, ID2, SETG, , DTOR, CID
+,       DTHX, DTHY, , USAGE
```

Fields mirror SPLINE2 with these differences:

| Field | Difference from SPLINE2 |
|-------|-------------------------|
| DZ    | Not supported (blank) — the Hermite interpolant is exact-fit by construction; smoothing springs belong to the fit formulation, i.e. SPLINE2 |
| DTOR  | Retained as EI/GJ only if the implementation adds a smoothing variant; Phase 1 ignores it with a warning when ≠ 1.0 |
| CID   | Same MSC convention as SPLINE2: **y-axis = spline axis**, x = chord, z = deflection |
| DTHX  | Bending-slope attachment: 0 = attached (nodal slope from ω·x̂ enters the Hermite derivative basis), −1 = detached (natural spline segment ends). Spring values (> 0) NOT supported in Phase 1 |
| DTHY  | Torsion attachment, same convention. Torsion interpolation is piecewise cubic Hermite in θ(t) when attached |

**Collinearity requirement (retained by design):** SET1 grids must lie on the spline
axis (chord offset ≤ 5% of the station range → else `ValueError`). Unlike the infinite
beam spline there are no rigid arms — a chord-offset deflection cannot be decomposed
into bend + twist by an exact-fit interpolant (this was AE1 Step B3's finding and it is
inherent to the formulation, not a limitation to remove).

---

## 3. Formulation sketch

Per spline, in the CID frame (ŝ = axis, ĉ = chord, ẑ = deflection):

- Grid data: h_i = u_i·ẑ, slope m_i = (ω_i·ĉ) [DTHX attached], twist θ_i = (ω_i·ŝ)
  [DTHY attached].
- Deflection interpolant h(t): cubic Hermite through (h_i, dh/dt_i) where the nodal
  slope datum is dh/dt_i = m_i (sign per the current frame conventions). If DTHX = −1,
  fall back to a not-a-knot/natural cubic through h_i alone.
- Twist interpolant θ(t): cubic Hermite through θ_i when DTHY = 0 with zero nodal
  θ′ data → use PCHIP or natural cubic through θ_i (decide during implementation;
  document the choice). If DTHY = −1 the spline is singular for planar panels unless
  the panel needs no twist (warn/error as SPLINE2 does).
- Box surface height: z(t, χ) = h(t) − χ·θ(t) with χ the box point's chord offset.
- g_slope row: −∂z/∂x = −[ŷ... **(implementation note: use the same evaluation helper
  as SPLINE2's `_eval_rows` — axis projections ŝ[0], ĉ[0] — so the two cards cannot
  drift apart in frame handling)**.
- g_disp rows: z·ẑ at force_point, virtual-work paired (identical structure to
  SPLINE2's weighting).

---

## 4. Validation / acceptance

1. **Rigid-body exactness** to 1e-12 on the swept/rect/dihedral fixtures (reuse
   `TestGlobalRigidBody`, parametrized over both spline cards).
2. **Analytic-field gates** (reuse/parametrize `TestBeamSplineFlexFields`): linear
   bend and linear twist exact; **parabolic bend exact** (the differentiator vs
   SPLINE2 — this is the card's reason to exist).
3. **Coarse-grid convergence study** (the honest go/no-go gate): a swept flexible
   wing solved with 3, 5, 9 EA stations, SPLINE9 vs SPLINE2-with-attached-rotations,
   restrained CZα/CMα vs the fine-mesh converged answer. **If SPLINE2 matches SPLINE9
   within noise at realistic station counts, close this item as "not worth the second
   code path" without implementing further.** Run this study FIRST, before the card
   plumbing.
4. HA144A stays on SPLINE2 (NASTRAN-matching gates unaffected).

---

## 5. Cost / risks

- Second spline code path: test matrix, documentation, and frame-convention
  synchronization forever after. Mitigate by sharing the evaluation/projection
  helpers with SPLINE2 and parametrizing the existing gates.
- The pre-AC7 history shows exactly how this card class goes wrong (sweep factors,
  torsion terms, force/slope pairing) — the analytic-field tests from AC7 are the
  guard rails and must gate SPLINE9 from the first commit.
- Scope creep risk: smoothing (DZ), spring flexibilities, and DTOR on a Hermite
  interpolant are ill-posed extras; Phase 1 refuses them loudly rather than
  approximating.

## 6. References

- AC7/AE14 close-out — `docs/40_history/00_completed_development.md` Step AC7
  (Hermite-vs-beam-spline diagnostics, the twist-gradient defect, the retired
  implementation's formulation; the old code is in git history pre-2026-07-05).
- MSC Aeroelastic Analysis User's Guide, Eqs. 2-48…2-63 (the SPLINE2 formulation this
  card deliberately deviates from).
- `docs/20_theory/01_aeroelastics_theory.md` §4.2 (current SPLINE2 theory).
