# A1 Diagnostic — Spanwise-Spacing Convergence of the VLM Lift-Curve Slope

**Date:** 2026-06-09
**Script:** [`studies/a1_spanwise_spacing_study.py`](../../../studies/a1_spanwise_spacing_study.py)
**Bug:** A1 — "VLM under-predicts CL_α (3–8%) and the deficit grows with spanwise refinement."

## Question

Discriminate the surviving A1 hypotheses:

- **H2 (spacing artifact):** uniform spanwise spacing under-resolves the tip-region
  loading; **cosine** spanwise spacing (Hough 1973 / Lan 1974, NASA SP-405) would
  converge fast and remove the refinement drift.
- **H3 (kernel bias):** the trailing-vortex induced downwash is genuinely biased; the
  converged value stays low vs an independent peer VLM (AVL).
- **H1 (benign):** there is no defect — the "deficit" is the legitimate gap between
  lifting-*surface* VLM and the lifting-*line* upper bounds A1 was compared against, plus
  ordinary mesh convergence.

## Method

Full-span model (two CAERO1 half-surfaces, parity = 0), spanwise breakpoints supplied
via AEFACT (no mesher change). Two planforms; sweep nspan with **uniform vs cosine**
spanwise spacing at fixed nchord, plus two control probes.

## Results

### BYU / AVL tapered wing (AVL CL_α = 4.667 /rad — a real peer-VLM number)

| nspan | uniform CL_α | cosine CL_α | uniform %dev vs AVL | cosine %dev |
|------:|-------------:|------------:|--------------------:|------------:|
| 6  | 4.7697 | 4.7670 | +2.13% | +2.07% |
| 12 | 4.6746 | 4.6751 | **+0.09%** | **+0.10%** |
| 24 | 4.6216 | 4.6223 | −1.04% | −1.03% |
| 48 | 4.5938 | 4.5943 | −1.64% | −1.63% |

Drift coarsest→finest: uniform −0.176, **cosine −0.173 (identical)**.

### Rectangular AR = 8 wing (refs: elliptic-LL 5.027, rect-LL 4.78, Polhamus 4.91)

| nspan | uniform CL_α | cosine CL_α |
|------:|-------------:|------------:|
| 10 | 4.7204 | 4.7218 |
| 20 | 4.6556 | 4.6568 |
| 40 | 4.6213 | 4.6219 |
| 80 | 4.6036 | 4.6040 |

Drift coarsest→finest: uniform −0.117, **cosine −0.118 (identical)**.

### Control probe 1 — chordwise (nchord) sensitivity, BYU, fixed nspan = 24

| nchord | 2 | 4 | 6 | 8 | 12 |
|--------|---|---|---|---|----|
| CL_α | 4.6154 | 4.6207 | 4.6216 | 4.6220 | 4.6222 |

Lift is **chordwise-insensitive** (0.15% over nchord 2→12) — the drift is purely spanwise.

### Control probe 2 — joint refinement holding box aspect ratio ≈ 1, BYU

| (nspan, nchord) | (8,2) | (15,4) | (22,6) | (30,8) |
|-----------------|-------|--------|--------|--------|
| CL_α | 4.7195 | 4.6531 | 4.6266 | 4.6109 |

The drift **persists at box AR ≈ 1** — it is not a box-elongation (AR) artifact.

## Conclusions

1. **H2 (spanwise spacing) is REFUTED — decisively.** Uniform and cosine spacing agree
   to < 0.01 /rad (< 0.2%) at every resolution on both planforms. Cosine spanwise spacing
   does **not** reduce the refinement drift. The Hough/Lan spacing remedy does not apply here.

2. **The refinement drift is real, convergent, and purely a function of spanwise panel
   count.** It is independent of spacing distribution, of nchord (probe 1), and of box
   aspect ratio (probe 2). The decrements halve as nspan doubles (BYU uniform: −0.095,
   −0.053, −0.028), i.e. geometric convergence; Richardson extrapolation gives a limit of
   **≈ 4.56 /rad** for the BYU wing.

3. **At AVL's own discretisation (12 × 6) sbeam matches AVL to 0.09%.** The apparent
   "drift below AVL" compares sbeam-refined against AVL-at-12×6 — not a like-for-like
   comparison. sbeam and AVL agree at the matched mesh.

4. **The rectangular converged value (~4.60 /rad) sits below the lifting-*line* references
   (4.78–5.03) by the expected amount.** Lifting-*surface* VLM legitimately gives a lower
   slope than lifting-line for finite AR, so most of A1's "deficit" is the wrong baseline
   (LL upper bounds), not a defect.

**Net:** A1 is most consistent with **H1 (benign) — not a kernel bug**. The spacing
hypothesis is eliminated; the residual refinement drift is ordinary, convergent VLM
mesh behaviour, and sbeam agrees with the AVL peer VLM at matched resolution.

## Peer-VLM convergence comparison — VortexLattice.jl (RESOLVES A1)

The like-for-like check was run with **VortexLattice.jl** (BYU FLOW Lab; validated
against AVL to < 0.1%) at the same nspan sequence, nc=6, uniform spacing, via
[`studies/byu_wing_sweep.jl`](../../../studies/byu_wing_sweep.jl). Results (2026-06-09):

| nspan | VLM.jl CL | VLM.jl CL_α /rad | sbeam CL_α /rad | Δ (VLM−sbeam) | VLM.jl Cm | VLM.jl CDi |
|------:|----------:|-----------------:|----------------:|--------------:|----------:|-----------:|
| 6  | 0.24935 | 4.7621 | 4.7697 | −0.0076 | −0.02174 | 0.002475 |
| 12 | 0.24437 | 4.6671 | 4.6746 | −0.0075 | −0.02085 | 0.002476 |
| 24 | 0.24160 | 4.6142 | 4.6216 | −0.0074 | −0.02039 | 0.002470 |
| 48 | 0.24014 | 4.5864 | 4.5864… → ~4.59 | −0.0074 | −0.02016 | 0.002466 |

**VortexLattice.jl drifts down with spanwise refinement EXACTLY like sbeam** (4.76 → 4.67
→ 4.61 → 4.59), and the sbeam−peer offset is **constant at ≈ −0.0075 /rad (~0.16%) at
every resolution** — a fixed, tiny inter-code difference, not a growing divergence. The CM
(after the A9 ¼-chord fix) and the far-field CDi also track VLM.jl across the whole sweep.

## Resolution — A1 CLOSED, benign

A1 is **not a defect.** The "deficit grows with refinement" signature is ordinary,
convergent lifting-surface VLM mesh behaviour, reproduced identically by an
AVL-validated peer code. The original 3–8% "deficit" was an artifact of comparing
against lifting-*line* upper bounds (`2π/(1+2/AR)` = 5.027, etc.), which finite-AR
lifting-*surface* VLM correctly sits below. sbeam agrees with VortexLattice.jl/AVL to
~0.16% at every spanwise resolution.

The constant ~0.16% sbeam-vs-VLM.jl offset is well within expected inter-code scatter
(trailing-leg far-field cutoff, single-horseshoe vs ring formulation) and is not pursued.
