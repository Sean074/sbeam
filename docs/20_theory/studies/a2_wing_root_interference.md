# Study A2 — HA144A Wing-Root Interference Residual (AE15 / Step AC8)

**Date:** 2026-07-05
**Status:** Closed — residual quantitatively attributed and accepted (documented-accept).
**Scope:** the six xfailed HA144A q=1200 moment/ELEV derivative gates in
`tests/aero/test_ae1_restrained_derivs.py` (`TestRestrainedDerivsQ1200` /
`TestUnrestrainedDerivsQ1200` residual halves).

---

## 1. The residual

After the AC7/AE14 close-out (fuselage-PBAR doubling + NASTRAN infinite-beam-spline
rewrite), the HA144A q=1200, M=0.9 derivative columns vs MSC Table 7-1:

| Column | restrained | unrestrained | gate |
|--------|-----------:|-------------:|------|
| CZα    | −1.53 %    | −1.90 %      | live (2 / 2.5 %) — pass |
| CZq    | −0.95 %    | −1.25 %      | live — pass |
| CMq    | +2.02 %    | −2.28 %      | live — pass |
| CMα    | **+4.30 %** | **−4.33 %** | xfail (this study) |
| CZδe   | **−2.90 %** | **−3.62 %** | xfail (this study) |
| CMδe   | **+5.23 %** | **+5.28 %** | xfail (this study) |

q=40 columns are all ≤0.2 %. The AC7 pinned-trim-state per-box comparison against
the guide's Listing 7-2 box forces (NASTRAN's exact trim state forced:
q=1200 ANGLEA=1.373015E−3, ELEV=1.932495E−2) localized the q=1200 mismatch to the
**wing-root TE boxes directly behind the canard** (canard boxes ≤0.2 % each;
outboard wing LE ≈1.008; root TE box ratios 1.9–4.1 with a sign flip on box 1110).
Geometry: canard x∈[10,20], y∈[0,±5]; wing root LE x=25 — the canard wake convects
straight into the wing root, and the canard span breakpoints (y=0, 2.5, 5) coincide
with wing span breakpoints (its trailing legs ride wing box edges).

**Constraint framing the study:** NASTRAN's Table 7-1 was computed on the SAME
8×4 wing / 2×4 canard mesh, so mesh refinement moves sbeam toward the *continuum*
answer, not toward NASTRAN's fixed-mesh answer — refinement is diagnostic only.

## 2. Experiment 1 — independent VLM implementation cross-check (DLR PanelAero)

DLR **PanelAero** (github.com/DLR-AE/PanelAero, the VLM/DLM used by DLR's Loads
Kernel) was run on the exact HA144A box geometry (sbeam's meshed corner points,
collocation, and bound-vortex endpoints) at M=0.9, and its steady-VLM ΔCp operator
`Qjj` substituted for sbeam's `ajj_inv_corr` through the full SOL 144 chain
(rigid derivatives, Q_aa coupling, trim, restrained/unrestrained derivatives).

- Operator-level: ‖Qjj − (−ajj_inv_corr)‖/‖ajj_inv_corr‖ = **1.6×10⁻⁸**
  (sign convention aside, entrywise identical).
- All rigid AND all q=1200 flexible derivative columns identical to ≥4 decimals.

The two implementations differ in exactly the details one might suspect —
compressibility (sbeam: Göthert y,z·β scaling; PanelAero: Hedman x/β stretch),
trailing-leg extent (1000-chord cutoff vs true semi-infinite), kernel algebra
(Biot–Savart segments vs Katz & Plotkin D1+D2+D3) — and the results are
numerically indistinguishable. **sbeam's VLM implementation is exonerated**: the
residual is not reproducible or removable by any textbook-VLM implementation
choice.

A consequence for the planned arbiter experiment: PanelAero's DLM at k=0
degenerates *by construction* to its VLM (`DLM.calc_Qjj`: the steady part IS the
VLM; the oscillatory increment is zero at k=0). The pre-registered acceptance bar
for this study — "a substituted k→0 DLM AIC recovers ≥70 % of each column gap" —
is therefore **unmeetable with an open-source arbiter**, not merely unmet: no
available implementation reproduces MSC's proprietary steady-AIC quadrature. The
attribution below rests on convergence evidence instead.

## 3. Experiment 2 — discretization sensitivity (scratch remesh, shipped deck untouched)

q=1200 restrained columns vs Table 7-1 under chordwise refinement of canard+wing
(box-ID-dependent cards — elevator AELIST, SPLINE2 ranges, monitor AELIST, per-box
W2GJ — renumbered programmatically):

| Mesh | CZα | CMα | CZq | CMq | CZδe | CMδe |
|------|----:|----:|----:|----:|-----:|-----:|
| NCHORD=4 (shipped / NASTRAN mesh) | −1.53 | **+4.30** | −0.95 | +2.02 | **−2.90** | **+5.23** |
| NCHORD=8  | +0.59 | −0.49 | −0.17 | −0.63 | +2.27 | +0.76 |
| NCHORD=12 | +0.25 | +0.35 | −0.47 | −0.25 | +1.89 | +1.81 |
| NCHORD=4, cosine chord spacing | −1.83 | +4.37 | −1.06 | +2.28 | −2.61 | +5.76 |

Refining sbeam chordwise moves its answer to within ~0.5–2.3 % of **NASTRAN's
coarse-mesh** values on every column. Since refined sbeam ≈ the mesh-converged
VLM limit, this means **MSC's NCHORD=4 steady AIC is already near-mesh-converged
in the interference region, where a coarse horseshoe VLM is 3–5 % off its own
converged limit** — precisely in the moment/ELEV columns whose flexible increment
weights the canard-wake-washed root. (Cosine chordwise spacing at the same box
count does not help: the defect is interference resolution, not LE loading.)

Strip-level confirmation at the pinned q=1200 state — wing-right per-strip Fz (lb):

| Strip (y-band, ft) | sbeam N4 | sbeam N12 | NASTRAN N4 | N4−N12 | NAS−N12 |
|---|---:|---:|---:|---:|---:|
| 0 (0–2.5)   | −343.2 | −324.7 | −317.3 | −18.5 | **+7.3** |
| 1 (2.5–5)   | −28.7  | −6.6   | +3.1   | −22.1 | **+9.7** |
| 2 (5–7.5)   | +1113.4 | +1188.1 | +1172.7 | −74.8 | **−15.4** |
| 3 (7.5–10)  | +1137.2 | +1156.7 | +1155.6 | −19.5 | **−1.1** |
| 4–7 (outboard) | — | — | — | ≤12 | ≤9 |

In the four root strips NASTRAN-coarse sits within 1–15 lb of sbeam's refined
answer while sbeam-coarse is 19–75 lb off. This is the box-level form of the
attribution.

## 4. Experiment 3 — wake-geometry sensitivity (mechanism corroboration)

**Spanwise alignment (rigid-level).** Re-meshing the canard so its trailing legs
no longer coincide with wing box edges corrupts even the RIGID derivatives
(canard 3-span: rigid CZδe +0.246→+0.591; 5-span: sign flip to −0.502; derivative
columns ±135–295 %): the discrete-wake singularity sweeps across wing collocation
points. Two conclusions: (a) upstream/downstream **span breakpoints must be
aligned** in multi-surface VLM models (the MSC HA144A deck does exactly this);
(b) the wing root sits in the canard wake's singular near field — the least
numerically benign region of the model.

**Wake displacement (flexible-level).** Kinking the canard wake out of the wing
plane by dz (legs slant over one chord aft of the canard, then run straight):

| dz (ft) | CMα | CMq | CZδe | CMδe |
|--------:|----:|----:|-----:|-----:|
| 0.0  | +4.30 | +2.02 | −2.90 | +5.23 |
| ±0.25 | +3.77 | +1.76 | −1.93 | +1.72 |
| ±0.5 | +2.84 | +1.24 | −0.68 | −4.02 |
| ±1.0 | +1.51 | +0.41 | −0.51 | −11.46 |

Half a foot of wake displacement moves CMδe by nine points: the residual columns
are governed by sub-foot details of how the discrete canard wake threads the wing
root — details a flat rigid wake at NCHORD=4 cannot resolve, and which MSC's
steady AIC evidently treats differently (and closer to the converged limit).

## 5. Conclusion

The q=1200 moment/ELEV residual (2.9–5.3 %) is a **canard-wake / wing-root
interference discretization difference between sbeam's horseshoe VLM and MSC
NASTRAN's proprietary steady AIC on the fixed 8×4/2×4 mesh**:

1. sbeam's VLM is implementation-correct (independent DLR implementation agrees
   to 1.6×10⁻⁸ at operator level and to 4+ decimals through the flexible chain).
2. The mismatch is confined to the wing-root strips behind the canard, where
   NASTRAN's coarse-mesh loading is near the mesh-converged limit and a coarse
   horseshoe VLM is not (strip table, §3).
3. The flexible increment of exactly the moment/ELEV columns weights that region,
   which is also hypersensitive to wake geometry (§4).

The residual is **accepted as a documented kernel/method difference**; the six
q=1200 gates remain `xfail(strict=False)` citing this study. Resolution paths,
if ever needed: the Phase D DLM implementation
(`docs/30_future/designs/dlm_rfa_flutter_gust.md`) with its steady kernel-function
quadrature, or refined chordwise meshing for sbeam-native (non-NASTRAN-comparison)
models.

**Modeling guidance for sbeam users** (from §3–§4):

- In multi-surface models, **align spanwise breakpoints** of upstream and
  downstream surfaces (canard/wing, wing/tail) — misalignment puts discrete
  trailing legs near downstream collocation points and can corrupt results at the
  rigid level.
- Downstream surfaces washed by an upstream wake need **chordwise refinement**
  (NCHORD ≥ 8) for converged moment/control derivatives; cosine spacing does not
  substitute for box count in interference regions.

## 6. Reproduction

Scratch scripts (session scratchpad, deleted at close-out): `ac8_boxcmp.py`
(pinned-state per-box comparison; Listing 7-2 extraction self-validated against
the 8000 lb totals), `ac8_meshstudy.py` (in-memory remesh study),
`ac8_panelaero.py` (PanelAero substitution, rungs 1–3), `ac8_strip_wake.py`
(strip aggregation + kinked-wake sweep). PanelAero 2023-vintage pip release in a
scratch venv; `pip install panelaero`.

## 7. References

- MSC Aeroelastic Analysis User's Guide 2021.3 — Table 7-1 (p. 230), Listing 7-2
  (per-box forces, trim states).
- Step AC7 close-out — `docs/40_history/00_completed_development.md` (residual
  provenance, per-box method).
- DLR PanelAero: Voß, A., *An Implementation of the Vortex Lattice and the
  Doublet Lattice Method*, DLR-IB-AE-GO-2020-137.
- Backlog Step AC8 / known-limitation AE15 (closed by this study).
