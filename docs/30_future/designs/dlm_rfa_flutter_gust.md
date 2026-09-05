# PHASE D — DLM + RFA UNSTEADY AERODYNAMICS FOR FLUTTER (SOL 145) AND GUST LOADS (SOL 146)

**Status:** Design proposal — not yet implemented.
**Target release:** six sub-phases D1–D6 (see §2); D1–D3 deliver NASTRAN-style flutter, D4–D5 deliver RFA and gust loads, D6 is enhancements.
**Owner:** Sean O'Meara
**Reviewer:** —
**Last updated:** 2026-07-05
**Related:** `docs/30_future/designs/matrix_gaf_export.md` (MKAERO1 card, per-Mach GAF loop, export bundle — this design extends it to k ≠ 0), `docs/10_standard/05_aeroelastics.md` (Phase A–C architecture), `docs/20_theory/01_aeroelastics_theory.md` (steady AIC/GAF derivation), backlog defects AE4/AE6 (spline correctness — hard prerequisites).

This document is the design proposal for sbeam Phase D: a Doublet Lattice Method (DLM) unsteady aerodynamic module, generation of complex generalized aerodynamic force (GAF) matrices `Q_hh(M, k)` on a fixed SOL 103 modal basis with Mach-matched AIC corrections, a NASTRAN-style SOL 145 flutter solution (PK primary, KE secondary), Rational Function Approximation (RFA, Roger form) with aeroelastic state-space assembly, and a SOL 146 dynamic aeroelastic response solution for discrete (1-cosine) gusts and continuous turbulence (Von Kármán PSD, Ā/N₀ outputs).

Sources behind every formula in this document (page references inline):

- **[BLAIR]** Blair, *A Compilation of the Mathematics Leading to the Doublet Lattice Method*, WL-TR-92-3028, 1992 (incl. reference C implementation and 3×3 benchmark).
- **[AAUG]** MSC Nastran 2021.3 Aeroelastic Analysis User's Guide (printed-page refs).
- **[QRG]** MSC Nastran 2024.1 Quick Reference Guide (card field layouts).
- **[Z]** ZAERO 9.2 Theoretical Manual, 3rd ed. (RFA §8, g-method §7, gust §10–11, AIC correction §4.3).
- **[P&G]** Pitt & Goodman, AIAA 87-0882 (AIC correction-factor practice).
- **[CR]** NASA CR-172232, Chao & Lan 1983 (gust downwash convention, Sears benchmark tables, Padé/Küssner fits).
- **[PA]** DLR PanelAero `DLM.py` (BSD-3-Clause, copy in `.refs/PanelAero_DLM.py`) — executable reference implementation of the full nonplanar kernel with per-equation citations to Rodden 1971/1972/1998; see §15.

---

## 1. Motivation

### 1.1 The engineering problem

sbeam Phases A–C deliver a validated structural model (SOL 103), a corrected steady VLM (k = 0) aero model, and static aeroelastic coupling (SOL 144). The two production analyses an aeroelastic beam tool exists for — **flutter clearance** and **dynamic gust loads** — both need the same missing ingredient: the *unsteady* aerodynamic transfer matrix `Q_hh(M, k)` over a grid of reduced frequencies, and a solver that uses it.

The architecture was designed for this from the start (`05_aeroelastics.md` "Phase D" notes; `matrix_gaf_export.md` §1.5): the chain

```
Q_hh(M, k) = Φᵀ · G_dispᵀ · S_kj · A_jj(M, k)⁻¹ · D_jk(k) · G_slope · Φ
```

is already implemented end-to-end for real k = 0 matrices. Phase D replaces exactly two links — the AIC `A_jj` becomes complex and frequency-dependent (DLM kernel), and the downwash operator `D_jk` becomes `D¹ + ik·D²` (substantial derivative) — and adds the consumers: flutter eigensolvers, an RFA fitter, and a frequency-response gust solver. Spline operators, integration matrix, correction tiers, modal basis, and the export bundle are reused unchanged.

### 1.2 What this delivers (user-visible)

- **NASTRAN-compatible decks**: `AERO`, `MKAERO1` (k ≠ 0), `FLUTTER`, `FLFACT`, `TABDMP1`, `GUST`, `TLOAD1/2`, `RLOAD1/2`, `DAREA`, `DLOAD`, `FREQ/FREQ1`, `TSTEP`, `TABLED1`, `TABRND1`, `TABRNDG`, `RANDPS`, plus `PARAM Q/MACH/GUSTAERO/LMODES/VREF/KDAMP/G`. A NASTRAN HA145B-style flutter deck runs in sbeam with cosmetic edits only.
- **SOL 145**: V-g / V-f flutter solution by the PK method (KE secondary), NASTRAN-format `FLUTTER SUMMARY` in the f06, flutter crossings identified.
- **GAF generation at specific Mach with corrections, against a modal basis**: one SOL 103 basis, a Mach × k loop over the `MKAERO1` table, Mach-matched `WKK`/`AECORR` correction selection (corrections derived at k = 0 applied to all k at that Mach — the standard industry practice [P&G p.511; AAUG p.26–27]), complex `QHH_M{mach}_K{k}.mm` files dropping into the existing export bundle slot reserved by `matrix_gaf_export.md` §1.5, plus gust columns `QHJ`.
- **RFA**: Roger-form rational fit of `Q_hh(ik)` with constraint options, aeroelastic state-space `A_ae` assembly, eigenvalue-vs-velocity flutter cross-check, state-space matrix export (controls/ASE-ready).
- **SOL 146**: modal frequency response with gust excitation; discrete gusts (1-cosine et al.) by the Fourier method; continuous turbulence with Von Kármán/Dryden PSDs, response PSDs, Ā (RMS per unit gust RMS) and N₀ outputs.

### 1.3 Why DLM (not ZONA6-style panels, not strip theory)

- DLM is the **k = 0-consistent extension of the VLM sbeam already has**: a constant-pressure doublet line at the box ¼-chord is identical to a horseshoe vortex at k = 0 [AAUG p.17, 19], so the production decomposition `D(k) = D_VLM + ΔD_osc(k)` (§5.4) anchors the unsteady method to the existing validated, corrected steady solution to machine precision.
- It is the method NASTRAN SOL 145/146 uses subsonically, so card semantics, box-sizing rules, and benchmark decks (HA145B, HA146A) carry over directly.
- The complete kernel mathematics, including the Laschka coefficients and closed-form spanwise integrals, is in [BLAIR] with a reference implementation and a numeric benchmark; the full nonplanar kernel (T1/T2, I2, regularization branches) is additionally available as an executable, NASTRAN-validated open-source reference [PA] — implementation risk is bounded.

---

## 2. Scope and Phasing

| Sub-phase | Content | Depends on |
|---|---|---|
| **D0** | Prerequisites: AE4 + AE6 spline fixes; `matrix_gaf_export` Phases 1–2 (MKAERO1 card, per-Mach driver, bundle writers); collocation-point displacement operator `g_disp_colloc` (§5.6) | — |
| **D1** | DLM kernel and unsteady AIC `A_jj(M, k)`: planar kernel + nonplanar T1/T2 dihedral terms, Laschka I1, parabolic spanwise quadrature, symmetry images, `D_VLM + ΔD_osc` anchoring | D0 |
| **D2** | Unsteady GAF generation: `D¹ + ik D²` downwash, `Q_kk(M,k)`, `Q_hh(M,k)` on fixed Φ over the Mach × k table, Mach-matched corrections at all k, gust columns `Q_hj(M,k)`, complex export bundle | D1 |
| **D3** | SOL 145 flutter: AERO/FLUTTER/FLFACT/TABDMP1/PARAMs, PK method with NASTRAN "special linear" GAF interpolation, KE method, V-g/V-f, f06 FLUTTER SUMMARY, viewer plots | D2 |
| **D4** | RFA: Roger least-squares fit with constraints, lag-root defaults, aeroelastic state-space assembly, eigenvalue V-sweep flutter cross-check, state-space export | D2 |
| **D5** | SOL 146 gust: frequency response solver, GUST + dynamic-load card set, Fourier discrete gust, random turbulence (PSD/Ā/N₀), f06 output | D2 (D3 deck infrastructure) |
| **D6** | Enhancements (each independently deferrable): time-domain gust via RFA state-space (hybrid IFFT forcing), g-method flutter, minimum-state RFA, quartic spanwise quadrature, viewer flutter-mode animation | D4/D5 |

### Out of scope (all phases)

- **Bodies / slender-body interference** (CAERO2, PAERO1 body fields parse-and-ignore with warning). Lifting surfaces only.
- **Supersonic Mach** (ZONA51-class). `M < 1` enforced; MKAERO1 validation per `matrix_gaf_export.md` §3.2 relaxed to `0 ≤ M < 1` with any `k ≥ 0`.
- **K-method flutter** (needs user-selected complex eigensolver, adds nothing over KE for sbeam's purposes [AAUG p.75–78]).
- **SPLINE1 surface splines** — beam structures spline naturally with SPLINE2/ATTACH; SPLINE1 remains `NotImplementedError`.
- **Control-surface unsteady aero / AESURF in flutter** (Q_hc columns) — design leaves the column slot (§8.3) but Phase D fits and flies only Q_hh and Q_hg.
- **Aeroservoelastic closed-loop analysis** — the D4 state-space export is the enabler; control-law coupling is downstream-tool territory (FLAPS et al.).
- **Mission-analysis / phased-loads gust criteria** (design-ellipse correlation, exceedance curves) — Ā and N₀ outputs give the user the inputs; the criteria arithmetic stays outside sbeam.

---

## 3. Conventions (load-bearing — fix once, never revisit)

RFA and flutter implementations live or die on these. All recorded in code as module-level docstrings and asserted in tests where possible.

1. **Reduced frequency:** `k = ω·c̄/(2·V)` with `c̄ = REFC` from the new `AERO` card (NASTRAN convention [QRG FLUTTER remark; AAUG p.75]). The semichord `b = c̄/2`. ZAERO formulas quoted with `L` map via `L = b = c̄/2`.
2. **Time/Fourier convention:** harmonic factor `e^{+iωt}`; forward transform `F(iω) = ∫ f(t) e^{−iωt} dt` [Z 10.2–10.4]. Downwash substantial derivative is then `w = ∂h/∂x + (iω/V)·h`.
3. **Pressure normalization:** complex `ΔCp` on `q = ½ρV²`; box force = `q·ΔCp·area` (the existing post-AE2 convention). `A_jj(M,k)` maps `ΔCp → w` (so `w = A_jj·ΔCp`); the *corrected inverse* `A_jj*⁻¹` maps `w → ΔCp`, exactly as the steady `ajj_inv_corr` does today.
4. **Downwash sign:** positive `w` = leading-edge-up incidence (increases lift) — unchanged from Phase A.
5. **Density:** flutter density = `DENS(FLFACT) × RHOREF(AERO)`; consistent-units philosophy unchanged (no WTMASS analogue).
6. **Damping bookkeeping:** `g` printed in the flutter summary is `2γ` (twice the critical-ratio-equivalent transient decay) [AAUG eq. 2-172ff]; TABDMP1 `TYPE=G` means `g = 2·C/C₀`.
7. **Complex dtype:** `numpy.complex128` for `A_jj(M,k)`, `Q_kk`, `Q_hh`, `Q_hj`, frequency-response vectors. Spline operators, Φ, K, M stay real `float64`. No sparse complex matrices (aero matrices are dense).
8. **Basis-consistency rule** (inherited from `matrix_gaf_export.md` §4.3, now load-bearing for flutter): SOL 103 solved exactly once; the identical `Φ` projects `K_hh`, `M_hh`, every `Q_hh(M,k)` and `Q_hj(M,k)`. Nothing inside the Mach × k loop may touch the eigensolver.

---

## 4. New Bulk Data and Case Control (NASTRAN-compatible)

Field layouts verified against [QRG]; only fields sbeam will honour are listed — unsupported fields parse-and-warn (existing house pattern).

### 4.1 `AERO` — unsteady aerodynamic physical data [QRG p.1118]

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Name | `AERO` | ACSID | VELOCITY | REFC | RHOREF | SYMXZ | SYMXY |

- `ACSID`: aero coordinate system (Phase D restriction: 0/blank — flow along basic +x, matching Phase A).
- `VELOCITY`: used only by SOL 146 data recovery; must equal `V` on GUST.
- `REFC`: reference chord `c̄` for `k = ωc̄/2V` (required, > 0).
- `RHOREF`: reference density.
- `SYMXZ`: +1 symmetric, 0 none, −1 antisymmetric → maps to the existing VLM/DLM `parity` (closes AE10's manual-parity gap for the dynamic solvers). `SYMXY` parsed, must be 0 (ground effect unsupported).
- Coexists with `AEROS` (static). Rule: SOL 144 requires AEROS; SOL 145/146 require AERO; decks may carry both (NASTRAN behaviour). One AERO max.

### 4.2 `MKAERO1` — Mach × k table

Exactly as designed in `matrix_gaf_export.md` §3.2, with the Phase A restriction lifted: `Ki ≥ 0.0` allowed (k = 0 permitted and recommended as the steady anchor; NASTRAN itself disallows k = 0 and extrapolates — sbeam computes k = 0 exactly via the VLM identity, a deliberate, documented improvement). All (Mi, Kj) combinations are computed. Multiple cards accumulate and de-duplicate. Validation: `0 ≤ M < 1`; max k warning per box-sizing rule §5.7.

### 4.3 `FLUTTER` [QRG p.1832]

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| Name | `FLUTTER` | SID | METHOD | DENS | MACH | RFREQ/VEL | IMETH | NVALUE | EPS |

- `METHOD`: `PK`, `PKNL`, `KE` (Phase D set; `K`/`PKS`/`PKNLS` rejected with message).
- `DENS`/`MACH`/`VEL`: FLFACT ids — density ratios, Machs, velocities (PK) or reduced frequencies (KE).
- `IMETH`: `L` (default). PK always uses the special-linear scheme (§7.3); for KE, `L` = 1-D linear spline in k. `S`/`TCUB` rejected.
- `NVALUE`: number of modes carried in the flutter solve output (default: all retained modes).
- `EPS`: PK k-convergence tolerance (default 1e-3).
- Loop order (NASTRAN Table 3-3): k/V innermost, Mach, then density. `PKNL`: matched triplets (equal-length lists), no cross product.
- Negative velocity in the VEL FLFACT ⇒ flutter eigenvector output at |V| (NASTRAN convention).

### 4.4 `FLFACT` [QRG p.1817]

`FLFACT, SID, F1, F2, …` with continuations, plus the `F1 THRU FNF NF FMID` alternate form:

```
Fi = [ F1(FNF−FMID)(NF−i) + FNF(FMID−F1)(i−1) ] / [ (FNF−FMID)(NF−i) + (FMID−F1)(i−1) ]
```

(FMID default `(F1+FNF)/2`; `FMID = 2·F1·FNF/(F1+FNF)` gives equal 1/k spacing — documented in the card reference for KE users.)

### 4.5 `TABDMP1` [QRG p.2855]

`TABDMP1, TID, TYPE` + `(f1, g1, f2, g2, …, ENDT)`. `TYPE` = `G` (default) / `CRIT` / `Q`. Linear interpolation, linear extrapolation from the end pair. Selected by case control `SDAMPING`. Per-mode damping `b_i = (g(f_i)/ω_i)·K_i` into `B_hh`; `PARAM,KDAMP,-1` routes it as complex stiffness `(1+ig)K` instead (for KE).

### 4.6 `GUST` [QRG p.1917]

| Field | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Name | `GUST` | SID | DLOAD | WG | X0 | V |

Gust angle = `WG · T(t − (x − X0)/V)`; `WG` = w_gust/V scale; `DLOAD` points at the TLOADi/RLOADi giving `T`; `V` must equal AERO VELOCITY. Selected by case control `GUST = SID`. For random analysis set `WG = 1/V` and carry the RMS on TABRNDG (NASTRAN practice).

### 4.7 Dynamic load set [QRG pp.1554–2965]

- `RLOAD1, SID, EXCITEID, DELAY, DPHASE, TC, TD, TYPE` → `{P(f)} = {A}[C(f)+iD(f)]e^{i(θ−2πfτ)}`
- `RLOAD2, SID, EXCITEID, DELAY, DPHASE, TB, TP, TYPE` → `{P(f)} = {A}·B(f)e^{i(φ+θ−2πfτ)}`
- `TLOAD1, SID, EXCITEID, DELAY, TYPE, TID` → `{P(t)} = {A}·F(t−τ)`; in SOL 146 Fourier-transformed, solved in frequency domain, inverse-transformed [QRG TLOAD1 remark 7].
- `TLOAD2`: analytic pulse form (parse; low priority — TLOAD1+TABLED1 covers gust profiles).
- `DAREA, SID, P1, C1, A1, …` — for pure gust runs a dummy DAREA is still required by the TLOAD/RLOAD but its value is unused (`WG` governs) [AAUG p.647].
- `DLOAD, SID, S, S1, L1, …` — combination; SOL 146 case control requires `DLOAD =` even for gust-only loading (HA146A pattern).
- `FREQ, SID, F1, F2, …` and `FREQ1, SID, F1, DF, NDF` (equal Δf — required for the Fourier method; FREQ2/3 out of scope).
- `TSTEP, SID, N1, DT1, NO1` — in SOL 146 defines **output times for the inverse FT only**.
- `TABLED1, TID, XAXIS, YAXIS` + `(x1, y1, …, ENDT)` — zero outside table range under Fourier processing (no extrapolation) [QRG remark 7].
- `TABRND1, TID` + table — tabulated gust PSD.
- `TABRNDG, TID, TYPE, L/U, WG` — analytic gust PSD: `TYPE` 1 = Von Kármán (p = 1/3, κ = 1.339), 2 = Dryden (p = 1/2, κ = 1.0):

  ```
  S_q(ω) = 2·WG²·(L/U)·[1 + 2(p+1)·κ²(L/U)²ω²] / [1 + κ²(L/U)²ω²]^(p+3/2),  ω = 2πf
  ```

- `RANDPS, SID, J, K, X, Y, TID` — source PSD `S_jk(F) = (X+iY)·G(F)`; Phase D restriction: `J = K` (auto-PSD) only.

### 4.8 PARAMs

| PARAM | Default | sbeam Phase D meaning |
|---|---|---|
| `Q` | — | dynamic pressure, **required** in SOL 146 (fatal if absent) |
| `MACH` | lowest in MKAERO1 | selects the Mach used by SOL 146 (closest match) |
| `GUSTAERO` | +1 | −1 ⇒ compute gust columns `Q_hj` (required for SOL 146 gust) |
| `LMODES` | 0 (= all) | number of lowest modes retained in the modal basis |
| `VREF` | 1.0 | flutter-summary velocities printed as V/VREF |
| `KDAMP` | +1 | −1 ⇒ TABDMP1 as complex stiffness (KE path) |
| `G` | 0.0 | uniform structural damping |

### 4.9 Case control

`FMETHOD = n` (FLUTTER select, SOL 145 required), `METHOD = n` (EIGRL, existing), `SDAMPING = n`, `GUST = n`, `DLOAD = n`, `FREQUENCY = n`, `TSTEP = n`, `RANDOM = n`, plus existing output requests extended: `DISPLACEMENT`/`VELOCITY`/`ACCELERATION` (SOL 146, SORT2 over frequency/time), `SDISP` (modal). `SOL 145` and `SOL 146` join the SOL whitelist and dispatch table in `main.py`.

### 4.10 `RFA` — sbeam-specific card (non-standard, AMODE precedent)

NASTRAN has no RFA card (RFA lives in ZAERO/ASE tools); sbeam needs a deck-resident request:

| Field | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Name | `RFA` | ID | NLAG | KMAX | CONSTR | MACH | EXPORT |
| Default | — | — | 4 | (max MKAERO1 k) | `K0` | (PARAM,MACH rule) | blank |

- `NLAG`: number of Roger lag terms (1–8).
- `KMAX`: overrides the lag-root spacing anchor (§8.1).
- `CONSTR`: `NONE` / `K0` (enforce A0 = Q(0), default) / `K0K1` (also match damping slope at smallest k > 0).
- `MACH`: which MKAERO1 Mach to fit (one RFA card per Mach of interest).
- `EXPORT`: blank / `SS` — write state-space `A_ae, B_w, C` matrices and fit-quality report into the export bundle.

---

## 5. Phase D1 — DLM Unsteady AIC

New module `sbeam/aero/dlm.py`, mirroring `vlm.py`'s structure (`AeroBox` consumed unchanged).

### 5.1 Integral equation and discretization

Normalwash–pressure relation per box pair (planar form) [BLAIR eq. 276, p.91; lattice pp.91–99]:

```
w̄_r = Σ_s  D_rs · ΔCp_s ,    D_rs = −(Δξ_s / 8π) · ∫_line K̄(x0, y0, z0; M, ω) dl
```

- Sending box s: constant-ΔCp **doublet line along the box ¼-chord** (endpoints inboard/outboard, midpoint — all already on `AeroBox` as `bound_a`, `bound_b`, `force_point`).
- Receiving box r: collocation at **¾-chord mid-span** (`AeroBox.colloc`), downwash normal to the receiving surface.
- `Δξ_s` = average box chord (`AeroBox.chord`).

### 5.2 Kernel function (Landahl form) [BLAIR §XIII pp.79–92]

```
K̄(x0,y0,z0) = exp(−iω x0/U) · [K1·T1 + K2·T2] / r1²

x0 = x_r − ξ_s,  y0 = y_r − η_s,  z0 = z_r − ζ_s
r1 = √(y0² + z0²),    k1 = ω r1/U,    β² = 1 − M²
R̄  = √(x0² + β² r1²),  u1 = (M R̄ − x0)/(r1 β²)

T1 = cos(γr − γs)
T2 = (z0 cosγs − y0 sinγs)(z0 cosγr − y0 sinγr)/r1²

K1 = −I1 − (M r1/R̄)·e^{−ik1u1}/(1+u1²)^{1/2}
K2 = 3I2 + (ik1 M² r1²/R̄²)·e^{−ik1u1}/(1+u1²)^{1/2}
     + (M r1/R̄)·[(1+u1²)(β²r1²/R̄²) + 2 + M r1 u1/R̄]·e^{−ik1u1}/(1+u1²)^{3/2}
```

`γs, γr` = sending/receiving dihedral angles (general T1/T2 are the standard Landahl/Rodden forms — Blair prints only the planar specialization). **Research gap closed (2026-07-05):** the nonplanar factors are verified against [PA], which implements K1/K2 in the identical Landahl form (Rodden 1971 eqs 7+8), T1 = cos(γ_sr) (eq 5), and T2 in the r1²-scaled form of Rodden 1971 eq 21a, with the r1 = 0 on-axis limits (K1 = −2, K2 = +4 for x0 ≥ 0; both 0 for x0 < 0) and the analytic k = 0 kernels K10/K20 (eqs 15+16) used for the §5.4 steady subtraction. [PA] also documents Rodden's typographic traps (missing denominators/brackets in eqs 7, 8, 11) — consult its comments during implementation. Planar surfaces need only K1 (T2 → 0 in the z0 → 0 limit) [BLAIR p.87] — D1 implements K1 first, K2/T2 in the same sub-phase behind the dihedral test gate (V-D1-6/V-D1-7).

### 5.3 Kernel integrals I1, I2 — Laschka approximation [BLAIR pp.87–90]

```
I1(u1,k1) = ∫_{u1}^{∞} e^{−ik1u}/(1+u²)^{3/2} du
          = e^{−ik1u1}·[1 − u1/(1+u1²)^{1/2} − ik1·J1]            (u1 ≥ 0)

1 − u/(1+u²)^{1/2} ≈ Σ_{n=1}^{11} a_n e^{−ncu},  c = 0.372
J1 ≈ Σ_{n=1}^{11} a_n e^{−ncu1} (nc − ik1)/(n²c² + k1²)
```

Laschka coefficients (printed values [BLAIR p.89], hard-coded with this citation):

```
a1=+0.24186198   a2=−2.7918027   a3=+24.991079   a4=−111.59196
a5=+271.43549    a6=−305.75288   a7=−41.183630   a8=+545.98537
a9=−644.78155    a10=+328.72755  a11=−64.279511
```

For `u1 < 0` use the reflection identity [BLAIR eq. 275]:

```
I1(u1,k1) = 2·Re[I1(0,k1)] − Re[I1(−u1,k1)] + i·Im[I1(−u1,k1)]
```

`I2` (nonplanar only) by the analogous parts-reduction — the closed form is not printed in [BLAIR] but is implemented in [PA] (`laschka_approximation`, Rodden 1971 eq A.6, with the same I0/J0 exponential sums):

```
3·I2 = [(2 + ik1·u1)·(1 − u1/(1+u1²)^{1/2}) − u1/(1+u1²)^{3/2} − ik1·I0 + k1²·J0]·e^{−ik1u1}
```

and the u1 < 0 reflection identity for I2 mirrors the I1 form (Rodden 1971 eq A.9, [PA] `get_integrals12`):

```
I2(u1,k1) = 2·Re[I2(0,k1)] − Re[I2(−u1,k1)] + i·Im[I2(−u1,k1)]
```

The Desmarais 12-term refinement of the exponential fit is a deferred nicety (D6); its coefficient table is also in [PA] (`desmarais_approximation`).

### 5.4 Steady anchoring — `D(k) = D_VLM + ΔD_osc(k)` [BLAIR p.102]

Production decomposition (Giesing-Kalman-Rodden practice):

```
D(M, k) = D_VLM(M)  +  [ D_dlm(M, k) − D_dlm(M, 0) ]
```

- `D_VLM(M)`: the existing exact steady AIC — horseshoe-vortex `build_ajj` on PG-compressed boxes with Göthert scaling, converted to ΔCp units (the post-AE2 `2/chord` row scaling), i.e. precisely the matrix `aero_model.py` produces today.
- `D_dlm(M, k)` and `D_dlm(M, 0)`: the parabolic-quadrature kernel integral of §5.5 at k and at k = 0, same lattice, same code path.

Consequences, both load-bearing: (a) `D(M, 0) ≡ D_VLM(M)` to machine precision, so SOL 145/146 at k → 0 is exactly consistent with SOL 144 and with every k = 0 correction; (b) the quadrature error of the parabolic fit cancels to first order between the two `D_dlm` evaluations, dramatically improving low-k accuracy on coarse lattices. This is the design's single most important structural decision.

### 5.5 Spanwise quadrature — parabolic (Rodden 1971/Blair) closed forms [BLAIR pp.95–99]

Evaluate the kernel numerator `K̄` at the doublet line's inboard end, midpoint, and outboard end; fit a parabola in the line coordinate `l ∈ [−L, +L]` (L = half line length, `sinΛ = (y_out − y_mid)/L`):

```
A0 = K̄_mid,   A1 = (K̄_out − K̄_in)/(2L),   A2 = (K̄_in − 2K̄_mid + K̄_out)/(2L²)
D_rs ∝ B0·A0 + B1·A1 + B2·A2
```

with the principal-value closed forms (planar denominators; `y` = receiving-point lateral offset from the sending-line midpoint):

```
F     = 2L/(y² − L² sin²Λ)
logT  = log[(sin²Λ·L² − 2y sinΛ·L + y²)/(sin²Λ·L² + 2y sinΛ·L + y²)]
B0 = F
B1 = logT/(2 sin²Λ) + (y/sinΛ)·F
B2 = 2L/sin²Λ + (y/sin³Λ)·logT + (y²/sin²Λ)·F
```

(verified against Blair's C source, p.113; the `−Δξ/8π` factor and `A_n` folding per §5.1). Singular-case branches, all mandatory:

- **Λ → 0 (unswept line):** Blair's forms divide by sinΛ — implement the analytic limit `B0 = 2L/y²`, `B1 = 0`, `B2 = 2L³/(3y²)·3 → (2/3)L³/y²·…` (derive and unit-test the limit explicitly; switch at `|sinΛ| < 1e-6` with a continuity test across the switch).
- **`y² = L²sin²Λ`** (receiving point laterally aligned with a sending-line endpoint): principal-value pole. With the standard lattice (collocation at strip mid-span) this occurs only across equal-width strips, where the pole term cancels pairwise between adjacent sending boxes sharing the endpoint — the assembler must compute strip-pair contributions together or regularize consistently (Rodden 1971 App. B treatment). Acceptance gate: V-D1-3.
- **Nonplanar denominators** (`r1²`-form, dihedral): closed forms per Rodden 1971 eqs 40/41, implemented in [PA] `calc_Ajj` (parabolic branch) in local (ȳ, z̄, e) semiwidth coordinates, including the three-condition regularization NASTRAN uses — planar `|z̄|/e ≤ 0.001`, co-planar series expansion (eq 32/33, `|ratio| ≤ 0.3`), far-field arctan form (eq 31b) — with thresholds cross-checked against NASTRAN `idf1.f`/`idf2.f`. Verified reference available; same gate V-D1-6/V-D1-7.

The quartic (Rodden 1998) numerator fit — five evaluation points, better for low-aspect boxes and high k — is a structured drop-in: the quadrature is isolated behind `_integrate_doublet_line(K̄_samples, geom) → complex`, parabolic in D1, quartic as D6 enhancement. The complete quartic closed forms (Rodden 1998 eqs 15–34) are implemented in [PA] (`method='quartic'`), including a resolved discrepancy between Rodden 1998 eq 23 and Rodden 1972 eq 30b (the d1/d2 selector values — [PA]'s comment records the correct set).

### 5.6 Downwash operator — `D_jk = D¹ + ik·D²` [AAUG eq. 2-2]

```
w_j = D¹_jk·u_k + ik·D²_jk·u_k,   ik·D² ≡ (iω/V)·h_normal
```

- `D¹` = streamwise slope at the collocation point = the existing `g_slope` chain (unchanged).
- `D²` = `(2/c̄)·h_n`, the **normal displacement at the ¾-chord collocation point**. The existing `g_disp` evaluates at the ¼-chord `force_point` (AE6, virtual-work-correct for forces) — D2 of the substantial derivative needs a *second* displacement evaluation at `colloc`. **New spline output `g_disp_colloc`** (same SPLINE2/ATTACH/SPLINE0 machinery, evaluation abscissa moved) listed as a D0 prerequisite. Force transfer continues to use `g_disp` at the ¼-chord (unchanged virtual-work pairing).
- Gust baseline `w_g` (W2GJ) participates at k = 0 only (static incidence — not part of the oscillatory problem).

### 5.7 Box-sizing rules (documented + warned, not enforced) [AAUG pp.106–107; RTM]

- Box chord `Δx < 0.08·V/f` for the highest frequency of interest (≈ 12 boxes per minimum wavelength); ≥ 4 chordwise boxes minimum. **Note:** Rodden/Taylor/McIntosh [RTM] revise this to **50 boxes per minimum wavelength (`Δx < 0.02·V/f`)** based on N5KA/N5KQ convergence studies — the validator warns at the [AAUG] 12-box rule and *recommends* the [RTM] 50-box rule in the warning text for high-k work.
- Box aspect ratio < 3 (≈ 1 desirable).
- `mesh_caero1` gains a validator that, given the MKAERO1 k-list and AERO REFC, prints the implied max usable frequency per CAERO1 and warns when `k_max > c̄/(4·Δx_max)` (the [QRG MKAERO1] limit).

### 5.8 API

```python
def build_ajj_dlm(boxes, mach, k, parity) -> np.ndarray[complex]:
    """Unsteady AIC, w = A_jj @ dCp. k = omega*cref/(2V). Anchored: returns
    exactly the steady VLM AIC when k == 0.0 (D_VLM + zero increment)."""
```

Performance note: each (M, k) pair is an O(n²) kernel-evaluation pass (3 kernel evaluations per box pair + image). The kernel evaluation vectorizes over receiving points per sending line (numpy broadcasting); no caching across k beyond the shared `D_dlm(M, 0)` term per Mach. Target: 2,000 boxes × 20 (M,k) pairs in minutes, not hours.

---

## 6. Phase D2 — Unsteady GAF Generation with Corrections

Extends the `matrix_gaf_export.md` Phase 2 driver from a Mach loop at k = 0 to a Mach × k loop. The driver is the deliverable behind the user requirement "*generate the GAF using a modal basis, where GAF are at a specific Mach with appropriate corrections*".

### 6.1 Pipeline (per Mach M, per reduced frequency k)

```
 1. ω_n, Φ = solve_modes(...)                 once, before any loop (§3 rule 8)
 2. for M in MKAERO1 machs:
 3.    select correction cards Mach-matched per matrix_gaf_export §3.3
 4.    A_vlm(M) = existing steady corrected chain (PG + WKK/WT2 + units)
 5.    D_dlm0(M) = build_ajj_dlm(boxes, M, k=0, parity)        # raw, uncorrected
 6.    for k in MKAERO1 ks:
 7.        A_jj(M,k)   = A_vlm_raw(M) + [build_ajj_dlm(M,k) − D_dlm0(M)]
 8.        A_jj*(M,k)  = apply correction to A_jj(M,k)          # §6.2
 9.        Q_kk(M,k)   = S_kj · A_jj*⁻¹(M,k) · (D¹ + ik D²)
10.        Q_hh(M,k)   = Φᵀ·G_dispᵀ·Q_kk-chain·G_slope-chain·Φ  # complex build_qaa/build_gaf
11.        Q_hj(M,k)   = Φᵀ·G_dispᵀ·S_kj·A_jj*⁻¹(M,k)           # gust columns, if PARAM,GUSTAERO,-1
12.        write QHH_M{M:.3f}_K{k:.4f}.mm (complex) and QHJ_... on EXPORT request
```

### 6.2 Corrections at a specific Mach, applied at all k

Standard industry practice, three independent citations:

- [P&G p.511]: correction factors derived from steady (k = 0) CFD at a Mach are "applied to all the unsteady AICs **for each value of k**".
- [AAUG pp.26–27, eq. 2-20]: `W_kk` is a multiplicative diagonal on box forces, the *flutter-appropriate* correction (the additive experimental-pressure term is static-aero-only and excluded here).
- [Z §4.3]: DWM (post-multiply, downwash side) and FCM (pre-multiply, force side) weighting matrices from steady Cp/force targets — sbeam's existing WT2 (the force-side WT1 was removed by DEF-R7).

sbeam rule: the **same correction operator the steady path builds at this Mach** (Mach-matched per the `WKK`/`AECORR` `MACH` field, `matrix_gaf_export.md` §3.3) is applied unchanged to the complex `A_jj(M,k)` at every k of that Mach. Known limitation, documented in the theory manual: steady-derived multiplicative corrections have no rational basis for the out-of-phase (imaginary) parts [Z p.4-42, LANN-wing failure case]; transonic-grade corrections (ZTAW successive kernel expansion) are out of scope. The correction record per (M, k) goes into the export manifest exactly as the steady design specifies.

### 6.3 Gust columns `Q_hj`

`Q_kj = S_kj·A_jj*⁻¹` (no D matrices — the gust drives downwash directly) [AAUG p.82–83]; modal `Q_hj = Φᵀ G_dispᵀ Q_kj`. Computed when `PARAM,GUSTAERO,-1` and stored alongside `Q_hh` per (M, k). The per-box gust downwash phase vector (§9.2) is applied at solve time, not baked into `Q_hj` — `Q_hj` stays gust-profile-independent, exactly like NASTRAN's QHJL.

### 6.4 Export bundle extension

The bundle layout of `matrix_gaf_export.md` §4.5 gains complex matrices in its reserved slot: `QHH_M{mach}_K{k}.mm`, `QHJ_M{mach}_K{k}.mm` (`scipy.io.mmwrite` handles complex natively); the manifest gains the k-list, the §3 convention block (k definition, e^{+iωt}, ΔCp normalization), and per-(M,k) correction records. `KHH`/`MHH`/`PHIA`/`PHIG`/dofmap unchanged. A FLAPS/external-solver consumer thereby receives a complete flutter-ready set without running sbeam's own SOL 145.

---

## 7. Phase D3 — SOL 145 Flutter

New module `sbeam/solver/sol145.py`.

### 7.1 Modal flutter equation

```
[ −Mhh ω² + iω Bhh + (1+ig) Khh − ½ρV² Qhh(M,k) ] {uh} = 0
```

`Mhh = ΦᵀMΦ`, `Khh = ΦᵀKΦ` by explicit triple product (matrix_gaf_export §4.2 rationale); `Bhh` from TABDMP1 (KDAMP=+1) per-mode; `g` from PARAM,G (+KDAMP=−1 TABDMP1 route).

### 7.2 PK method (primary) [AAUG eq. 2-172–2-182, pp.78–81]

Per (ρ, M, V) loop point, real nonsymmetric eigenproblem in `p = ω(γ ± i)`:

```
[ Mhh p² + (Bhh − ¼ ρ c̄ V Qhh^I/k) p + (Khh − ½ ρ V² Qhh^R) ] {uh} = 0

A = [        0                                  I
     −Mhh⁻¹(Khh − ½ρV²Qhh^R)    −Mhh⁻¹(Bhh − ¼ρc̄V·Qhh^I/k) ]
```

- `Qhh^R` enters as aerodynamic stiffness; `Qhh^I/k` as aerodynamic damping. All-real matrices; `scipy.linalg.eig` on `A` (2n_m × 2n_m).
- **Per-mode k iteration:** for mode s start from the previous mode's converged frequency (`k_s⁰ = ω·c̄/2V`; mode 1 from the no-aero frequency); after each eigensolution take the s-th sorted oscillatory root, set `k^{(j)} = Im(p)·c̄/(2V)`, re-interpolate Qhh, repeat until `|k^{(j)} − k^{(j−1)}| < EPS` (absolute for k < 1, relative for k ≥ 1) [AAUG eq. 2-179/2-182]. Failure to converge in N_iter ⇒ warning naming mode/V (NASTRAN's FA1PKE 4581 analogue).
- Real roots (aperiodic: divergence, roll subsidence) reported with `g = 2p·c̄/((ln2)·V)` (decay-per-chord form) [AAUG eq. 2-176] — this is how static divergence appears in the PK output.
- Damping output `g = 2γ = 2·Re(p)/Im(p)`; frequency `f = Im(p)/2π`.
- `PKNL`: same solve, matched (ρ, M, V) triplets without the cross product.

### 7.3 GAF interpolation in k — NASTRAN "special linear" scheme [AAUG eq. 2-158–2-161]

PK requires Qhh at arbitrary k between MKAERO1 points. Fit `Qhh^R` and `Qhh^I/k` (the smooth-in-k quantities, symmetric about k = 0):

```
Qhh(k_est) = Σ_j C_j(k_est) · [ Qhh^R(k_j) + (i/k_j)·Qhh^I(k_j) ]
A_ij = |k_i − k_j|³ + |k_i + k_j|³ ,   B_i = |k_est − k_i|³ + |k_est + k_i|³   (+ constant row)
```

Linear-spline system solved once per Mach (factorized), evaluated per k-iteration — cheap. Mach interpolation: Phase D evaluates at the FLFACT Mach nearest an MKAERO1 Mach (warn if no exact match), matching `PARAM,MACH` semantics; 2-D (M,k) surface interpolation is deliberately out of scope (run one flutter point per MKAERO1 Mach — standard matched-point practice).

With k = 0 computed exactly (§4.2), the k → 0 limit of `Qhh^I/k` needs the slope of Im Qhh at 0; the scheme's even-symmetric basis handles this naturally — test V-D3-1 verifies a divergence speed recovered through the k→0 PK path against the SOL 144-side eigensolve.

### 7.4 KE method (secondary) [AAUG pp.77–78]

K-equation with `Bhh` deleted, eigenvalues only, per (M, k, ρ):

```
[ (2k/c̄)²·Mhh·(−V²/(1+ig)) + ... ] → eig of  ( (2k/c̄)² Mhh + ½ρ Qhh(M,k),  (1+ig)-scaled Khh )
p² = −V²/(1+ig) = a + ib  ⇒  g = −b/a,  V = √(−(a²+b²)/a),  f = kV/(πc̄)
```

Branch sorting by eigenvalue extrapolation continuity [AAUG eq. 2-170/171]: predicted `p_e(i,n)` from the previous two k-points, roots paired by min |p_e − p|². Cheap V-g scans on the raw MKAERO1 k-set; complements PK.

### 7.5 Output

f06 `FLUTTER SUMMARY`, NASTRAN format [AAUG p.171–173]:

```
                          FLUTTER  SUMMARY
POINT =    1     MACH NUMBER =  0.5000     DENSITY RATIO =  1.0000E+00     METHOD = PK
   KFREQ      1./KFREQ      VELOCITY       DAMPING       FREQUENCY     COMPLEX   EIGENVALUE
```

PK: one POINT per mode, rows by increasing V (velocities printed as V/VREF). KE: one POINT per (k,M,ρ), branch-sorted. `Sol145Result` dataclass: per-mode arrays of (V, k, g, f, p), flutter crossings (linear-interpolated g = 0 with V, f at crossing), flutter eigenvectors at negative-V request points. Viewer: V-g/V-f plot panel (plotly, existing results_view pattern). Crossing summary table printed after the per-point blocks (sbeam extension, clearly marked non-NASTRAN).

---

## 8. Phase D4 — RFA (Roger) and Aeroelastic State Space

New module `sbeam/aero/rfa.py`. ZAERO formulas with `L = b = c̄/2` per §3.

### 8.1 Roger fit [Z §8.1, eqs. 8.3–8.15]

```
Q(ik) ≈ A0 + A1(ik) + A2(ik)² + Σ_{n=1}^{Nlag} A_{2+n} · (ik)/(ik + b_n),   b_n > 0
```

- Lag roots default [Z eq. 8.6]: `b_n = 1.7·k_max·(n/(Nlag+1))²`, k_max from the MKAERO1 k-list (RFA card KMAX override).
- With roots fixed, the fit is **linear least squares, independent per matrix element**, on the real/imag split:

  ```
  Re Q(k_l) ≈ A0 − k_l²A2 + Σ_n A_{2+n}·k_l²/(k_l² + b_n²)
  Im Q(k_l) ≈ k_l·A1     + Σ_n A_{2+n}·k_l·b_n/(k_l² + b_n²)
  ```

- Constraints (RFA card CONSTR): `K0` ⇒ eliminate A0 = Q(0) exactly (sbeam has the exact k = 0 matrix — use it); `K0K1` ⇒ also match `Im Q(k₁)/k₁` damping slope. Over-constraining degrades the global fit [Z p.8-8] — documented.
- Fit-quality report (always): per-element and Frobenius relative residual at each k, worst-element ranking — printed and manifest-recorded. The validation strategy is ZAERO's [Z §9.6]: the frequency-domain solution (PK, no RFA) is the truth; tune Nlag until state-space eigenvalues match it (gate V-D4-3).

### 8.2 State-space assembly [Z eqs. 8.16–8.23]

Aero states `x_a` (dim `n_m·Nlag`), `ẋ_a = (V/b)·R·x_a + E·ξ̇` with `R = diag(−b_n)⊗I`, and:

```
M̄ = Mhh − q∞ (b/V)² A2

A_ae = [        0                          I                     0
        −M̄⁻¹(Khh − q∞A0)    −M̄⁻¹(Bhh − q∞(b/V)A1)     q∞·M̄⁻¹·D
                0                         E                  (V/b)·R   ]
```

(Roger structure: `D = [I I … I]`, `E` stacks the `A_{2+n}` action on ξ̇.) Total states `2n_m + n_m·Nlag`. Flutter path: eigenvalues of `A_ae` swept over V (and ρ pairs); damping `g = 2·Re(s)/|Im(s)|`; mode tracking by the predictor-corrector pairing of §7.4 transplanted to the V-sweep [Z eqs. 7.33–7.35]. This is a *cross-check and a product* (exported state space for controls work), not a replacement for PK.

### 8.3 Forward slots

Column structure reserves `Q_hc` (control-surface) and `Q_hg` (gust) partitions [Z 8.22, 10.16–10.25]: the fitter accepts an optional extra-columns block fitted with frozen R (modified-minimum-state pattern) so D6's time-domain gust and any future ASE work append columns without re-fitting `Q_hh`. Minimum-state (Karpel D-E iteration) itself is D6 — Roger's per-element linear fit is the right first implementation (simpler, no bilinear iteration, no cross-column contamination [Z pp.8-6/8-7]).

### 8.4 Export

`EXPORT` token `SS` (RFA card): `A_AE_V{vel}.mm` per sweep velocity or the velocity-independent pieces (`A0..A2, A_lag, R, E` + recipe in manifest) — decision Open #5.

---

## 9. Phase D5 — SOL 146 Gust Response

New module `sbeam/solver/sol146.py`.

### 9.1 Frequency response core [AAUG eq. 2-183]

```
[ −ω²Mhh + iωBhh + (1+ig)Khh − q̄·Qhh(M, k(ω)) ] {uh(ω)} = {P(ω)}
```

per frequency of the FREQ/FREQ1 set; `k(ω) = ωc̄/2V`; `Qhh` and `Qhj` interpolated to each ω by the §7.3 scheme; `q̄` = PARAM,Q; M = PARAM,MACH-selected MKAERO1 Mach. Dense complex solve per ω (n_m × n_m — trivial). Non-gust dynamic loads (RLOADi via DAREA → modal projection) supported as the base case; this is, deliberately, most of a SOL 111 modal-frequency-response solver — Phase 3 gets it nearly free (Open #6).

### 9.2 Gust excitation [AAUG eq. 2-184–2-186; Z 10.12–10.13; CR eq. 19]

Per aero box j at frequency ω, the sinusoidal-gust penetration downwash:

```
w_j(ω) = cos(γ_j) · exp( −iω (x_j − X0)/V )
{P_gust(ω)} = q̄ · WG · PP(ω) · [Q_hj(ω)] {w_j(ω)}
```

- `γ_j` = box dihedral (normal-projection of a vertical gust), `x_j` = box collocation x, `X0`/`WG` from the GUST card, `PP(ω)` = the RLOADi spectrum or the FFT of the TLOADi profile.
- Phase convention pinned by §3(2); identical in [AAUG 2-184], [Z 10.10] and [CR eq. 19].

### 9.3 Discrete gust — Fourier method [AAUG pp.84–85; HA146A pp.646–657]

1. `TLOAD1` + `TABLED1` define the gust time profile (1-cosine, square-edge, arbitrary).
2. FFT of the profile → `PP(ω)` at the FREQ1 frequencies (equal Δf required; period `T = 1/Δf` must exceed event + decay — validated, error if TSTEP output window exceeds T).
3. Solve §9.1 per ω → `{uh(ω)}`; data recovery in frequency domain.
4. Inverse FFT → time histories at TSTEP output times.

House rules from the HA146A reference deck, encoded as validations/docs: dummy DAREA required-but-unused; `DLOAD` case control mandatory; trailing negative-copy profile technique documented for driving responses back to zero; delay via `X0 = −delay·V`.

Load recovery: mode-displacement (`F = K_gh·ξ(ω)`, default) and **mode-acceleration** (sum-of-forces, reusing the SOL 144 residual-correction machinery) — MA is the documented-accurate option for concentrated loads [Z 10.65–10.71]. CBAR force/stress recovery through the existing element pipelines at each output time.

### 9.4 Continuous turbulence [AAUG pp.85–89; Z Ch.11]

Unit-gust frequency response `H_y(ω)` (run §9.1–9.2 with `WG = 1/V`, `PP = 1`), then per requested response y:

```
S_y(ω) = |H_y(ω)|²·S_q(ω)            S_q from TABRNDG (Von Kármán/Dryden, §4.7) or TABRND1
ū_y    = sqrt( (1/4π)·Σ [S(ω_{i+1})+S(ω_i)]·Δω )         (RMS — "Ā" per unit-RMS input)   [AAUG 2-199]
N0_y   = (1/2π)·sqrt( ∫ω²S dω / ∫S dω )                   (characteristic frequency)       [AAUG 2-200]
```

Trapezoidal quadrature over the FREQ set (frequency-range adequacy warning if the PSD tail at ω_max exceeds a threshold of the integral). Output: PSDF tables per requested response + Ā/N₀ summary block in the f06. `RANDPS` with `J = K` selects the source; cross-PSD/phased-loads out of scope (§2).

### 9.5 f06 output

SORT2 frequency-response tables (DISP/VELO/ACCE, complex as real/imag), transient tables at TSTEP times, PSDF blocks, Ā/N₀ summary. No default output (NASTRAN SOL 146 behaviour — everything requested explicitly).

---

## 10. Phase D6 — Enhancements (independently deferrable)

1. **Time-domain gust via RFA state space — hybrid method** [Z §10.5, eqs. 10.55–10.56]: RFA only `Q_hh`; generalized gust force computed exactly as `φᵀF_G(t) = (q̄/V)·IFFT[Q_hj(ik)·w_G(iω)]` and fed as exogenous forcing to the §8.2 state space. Avoids RFA-fitting the spiral-phased gust column entirely (the dominant error source [Z Fig. 10.3]); gust-lag RFA [Z 10.16–10.25] only if true state-space gust inputs are later needed for ASE.
2. **g-method flutter** [Z §7.3, eqs. 7.15–7.32]: damping-perturbation `[ (V/b)²M p² + K − ½ρV²Q′(ik)·g − ½ρV²Q(ik) ]q = 0` with `Q′ = dQ/d(ik)` by central differencing of the tabulated GAFs; k-sweep, Im(g) = 0 crossings. Finds aerodynamic-lag roots PK misses (BAH divergence-as-lag-root case [Z p.7-14]).
3. **Minimum-state RFA** (Karpel D→E→D iteration, modified for extra columns) — when state count matters.
4. **Quartic spanwise quadrature** (Rodden 1998) behind the §5.5 integrator interface — closed forms in [PA] `method='quartic'` (eqs 15–34 incl. the eq-23 erratum); per [RTM], the payoff is box AR ≳ 3 and damping accuracy.
5. **Desmarais 12-term kernel-integral fit** — coefficient table in [PA] `desmarais_approximation`.
6. **Viewer**: flutter-mode animation at crossings, gust time-history animation, PSD panel.

---

## 11. Implementation Plan — File Touches

| File | Phase | Change |
|---|---|---|
| `sbeam/aero/dlm.py` | D1 | **New.** Kernel (K1/T1 planar; K2/T2 dihedral), Laschka I1 (+u1<0 branch), I2, parabolic line integrator with Λ→0/pole branches, `build_ajj_dlm`, symmetry images |
| `sbeam/aero/integration.py` | D2 | `build_djk2(boxes)` (D² = 2/c̄ × normal displacement at colloc); existing `build_djk` renamed conceptually to D¹ path (no behaviour change) |
| `sbeam/aero/spline.py` | D0 | `g_disp_colloc` evaluation (¾-chord abscissa) alongside existing `g_disp`; **after AE4 fixes** |
| `sbeam/aero/aero_model.py` | D2 | `build_unsteady_aero(bulk, mach, k, parity, grid_index)` → complex AeroModel variant; correction application to complex A_jj; reuses Mach-matched card selection from matrix_gaf_export work |
| `sbeam/aero/coupling.py` | D2 | `build_qaa`/`build_gaf` accept complex (dtype-generic — likely zero-change + tests); `build_qhj` gust columns |
| `sbeam/aero/gaf.py` | D2 | **New.** The Mach × k GAF driver (§6.1), single-Φ enforcement, bundle writing (complex MM), manifest records |
| `sbeam/aero/rfa.py` | D4 | **New.** Roger fit (constrained LS per element), lag-root defaults, fit report, state-space assembly, V-sweep eigensolution with predictor-corrector tracking |
| `sbeam/solver/sol145.py` | D3 | **New.** PK loop (k-iteration per mode, special-linear interp), KE loop (branch sorting), PKNL, crossing detection, `Sol145Result` |
| `sbeam/solver/sol146.py` | D5 | **New.** Frequency response, gust excitation, Fourier discrete gust, random turbulence, MA load recovery, `Sol146Result` |
| `sbeam/model/aero.py` | D3/D5 | **New dataclasses:** Aero, Flutter, Flfact, Gust, Rfa; (MKAERO1 from matrix_gaf_export) |
| `sbeam/model/dynamics.py` | D5 | **New.** Tabdmp1, Rload1/2, Tload1/2, Darea, Dload, Freq/Freq1, Tstep, Tabled1, Tabrnd1, Tabrndg, Randps |
| `sbeam/parser/bdf_reader.py` | D3/D5 | Handlers for every §4 card (SPC1-style continuation patterns); cross-validation (FLUTTER→FLFACT ids, GUST→DLOAD chain, AERO uniqueness, MKAERO1 k-limit warning) |
| `sbeam/parser/case_control.py` | D3/D5 | FMETHOD, SDAMPING, GUST, DLOAD, FREQUENCY, TSTEP, RANDOM; SOL 145/146 whitelist |
| `sbeam/main.py` | D3/D5 | Dispatch SOL 145 → sol145, SOL 146 → sol146; parity wired from AERO.SYMXZ (AE10 closure for dynamics) |
| `sbeam/results/results.py` | D3/D5 | `Sol145Result`, `Sol146Result` |
| `sbeam/results/f06_writer.py` | D3/D5 | FLUTTER SUMMARY block (NASTRAN format), crossing table, SORT2 freq/time tables, PSDF + Ā/N₀ block |
| `sbeam/viewer/results_view.py` | D3/D6 | V-g/V-f plots; PSD plots (D6) |
| `docs/10_standard/02_card_reference.md` | all | every §4 card field table |
| `docs/10_standard/05_aeroelastics.md` | all | Phase D sections per sub-phase |
| `docs/20_theory/01_aeroelastics_theory.md` | all | DLM kernel + quadrature, PK/KE math, Roger RFA + state space, gust/PSD theory (the §5–§9 content in full) |
| `docs/10_standard/00_program_overview.md` | D3 | SOL 145/146 in the solution map |
| `tests/aero/test_dlm.py`, `test_gaf_unsteady.py`, `test_rfa.py` | D1/D2/D4 | per verification matrix |
| `tests/solver/test_sol145.py`, `test_sol146.py` | D3/D5 | per verification matrix |
| `sample/sample_flutter_ha145b_style.bdf`, `sample_gust_1mc.bdf` | D3/D5 | reference decks |
| `CHANGELOG.md` + backlog | all | per the step-completion rule, one backlog step per sub-phase on promotion |

---

## 12. Verification Matrix

Closed-form-first house style. **Bold** gates are load-bearing.

| ID | Phase | Case | Target | Tol |
|---|---|---|---|---|
| **V-D1-1** | D1 | k = 0 identity: `build_ajj_dlm(M, 0)` vs existing VLM AIC, several lattices/sweeps/Mach | identical by construction (§5.4) — asserts the increment is exactly zero | 0 / 1e-14 |
| **V-D1-2** | D1 | **Blair 3×3 benchmark** [BLAIR App. B/C]: rectangular half-wing AR 2, M = 0.5, k = 1.0 (b = 6), uniform w/U = −i, symmetric | C_L = −2.5038 + 2.8433i (|C_L| = 3.7901, ∠131.347°); per-box Cp table (9 values, printed in [BLAIR p.140]) | 0.1 % |
| V-D1-3 | D1 | Pole/limit branches: unswept line (Λ = 0), equal-width-strip endpoint alignment, continuity across the sinΛ switch | finite, continuous, converged vs refined lattice | 1e-6 cont. |
| V-D1-4 | D1 | Theodorsen 2-D limit: AR ≥ 20 rectangular wing, M ≈ 0, plunge & pitch at k = 0.1/0.3/0.5/1.0; mid-span section lift vs `C(k)` (scipy Hankel functions) | magnitude + phase of L(k) | 3 % |
| V-D1-5 | D1 | Lattice convergence: V-D1-4 case, error vs NCHORD at fixed k; box-sizing warning fires when Δx rule violated | monotone convergence; warning text | — |
| V-D1-6 | D1 | Nonplanar gate: two parallel planar surfaces vs single surface (interference sanity); dihedral wing symmetric/antisymmetric image consistency; T1/T2 and I2 verified against the [PA] closed forms (Rodden 1971 eqs 21a, 40/41, A.6/A.9) | documented check + regression snapshot | snapshot |
| **V-D1-7** | D1 | **PanelAero oracle**: full-matrix `build_ajj_dlm(M, k)` vs [PA] `calc_Ajj` (pip-installable, BSD-3) on (a) the Blair 3×3 lattice and (b) a dihedral/nonplanar case, several (M, k) pairs. Convention conversion required: [PA] uses k = ω/V (not ω·c̄/2V) and adds the steady VLM part separately — compare total `D_VLM + ΔD_osc` matrices, not intermediate terms | element-wise complex AIC match | 1e-6 rel |
| **V-D2-1** | D2 | GAF k = 0 cross-check: `Q_hh(M, 0)` from the unsteady driver ≡ steady `Q_hh(M)` from the matrix_gaf_export driver (corrections on) | identical path ⇒ | 1e-12 rel |
| V-D2-2 | D2 | Correction invariance: WKK-corrected `Q_hh(M, k)` at k = 0 reproduces corrected steady derivatives; corrected/uncorrected ratio at k > 0 equals the k = 0 ratio (multiplicative rule §6.2) | exact-by-construction checks | 1e-12 |
| V-D2-3 | D2 | Basis-consistency trap: driver called with per-k re-solved modes must be impossible by API (Φ is an argument); test asserts single `solve_modes` call (mock counter) | structural | exact |
| **V-D2-4** | D2 | **Sears gust column** [CR Table I]: high-AR wing, M = 0, sinusoidal gust; section C_l/C_l0 vs k ∈ {0.1: (0.821, −0.164), 0.4: (0.568, −0.085), 1.0: (0.369, +0.126), 2.0: (0.082, +0.268)} | in/out-of-phase pairs | 5 % |
| V-D2-5 | D2 | Complex export round-trip: QHH/QHJ written, `mmread` back, compare; manifest k-list/conventions block | exact | 1e-15 |
| **V-D3-1** | D3 | 2-DOF typical section (CG 37 % chord, [Z pp.7-15/7-16] model): PK divergence 210 ft/s, flutter 250 ft/s; CG 45 %: flutter 170 ft/s | both speeds | 2 % |
| **V-D3-2** | D3 | Theodorsen typical-section flutter: closed-form V_f from classical 2-DOF solution (independent python implementation in the test, exact C(k)) vs sbeam PK on a high-AR wing matching the section | V_f, f_f | 3 % |
| V-D3-3 | D3 | HA145B-style BAH wing PK deck (translated from [AAUG p.431–433]): flutter speed vs published ≈ 1056 ft/s class result; f06 FLUTTER SUMMARY format snapshot vs Listing 8-7 layout | V_f 5 %; format exact |
| V-D3-4 | D3 | PK/KE consistency: same model, KE crossings vs PK crossings | V_f | 1 % |
| V-D3-5 | D3 | PK k-iteration: convergence in < 10 iters on V-D3-1; EPS honoured; non-convergence warning fires on a contrived case | behavioural | exact |
| V-D3-6 | D3 | k→0 PK divergence vs direct eigensolve `K_hh v = q Q_hh(M,0) v` | q_div | 0.5 % |
| **V-D4-1** | D4 | Roger fit on analytic Theodorsen `C(k)`: residual decreases with Nlag; constraint K0 exact at k = 0 | fit residual < 1 % at Nlag = 4 over k ≤ 1 | 1 % |
| V-D4-2 | D4 | State-space dimension/structure: eigenvalues of A_ae at q̄ = 0 reproduce structural ω_n exactly; lag eigenvalues at −b_n V/b | exact | 1e-10 |
| **V-D4-3** | D4 | RFA-flutter cross-check: A_ae eigenvalue V-sweep flutter point vs PK (V-D3-1 and V-D3-3 models) | V_f, f_f | 2 % |
| **V-D5-1** | D5 | Sears frequency response: unit-gust H(ω) on the V-D2-4 model vs Sears function modal response (independent analytic implementation) | mag/phase over k ≤ 1 | 5 % |
| V-D5-2 | D5 | Fourier round-trip: zero-aero (q̄ = 0) 1-cosine "gust" on a 1-DOF oscillator vs scipy `odeint` time integration; period/Δf validation errors fire | peak response | 0.5 % |
| V-D5-3 | D5 | HA146A-style deck translation: discrete gust on the BAH-class model; response time-history snapshot; deck-rule validations (dummy DAREA, DLOAD required, period check) | snapshot + error texts | snapshot |
| **V-D5-4** | D5 | Von Kármán analytic check: SDOF system with known |H|², Ā computed by sbeam quadrature vs `scipy.integrate.quad` closed evaluation; N₀ likewise | Ā, N₀ | 0.5 % |
| V-D5-5 | D5 | TABRNDG vs TABRND1 parity: tabulated Von Kármán PSD reproduces TYPE=1 results | Ā | 0.1 % |
| V-D6-1 | D6 | Hybrid time-domain gust vs D5 frequency-domain IFFT response (same model) | time histories | 1 % |

**Non-regression:** entire existing suite unchanged; decks without Phase D cards bit-identical. **External-benchmark caveat:** AGARD 445.6 flutter numbers are *not* printed in the in-repo references (research finding) — treat 445.6 as a documented manual-validation exercise with externally sourced data (NASA TM-100492/Yates), not a CI gate.

---

## 13. Dependencies, Risks, Effort

### 13.1 Hard prerequisites (D0)

1. **AE4 (SPLINE2 swept-axis kinematics) must close first.** Every `Q_hh(M,k)` is built through `g_slope`/`g_disp`; flutter answers on swept wings are invalid until the spline rigid-body gates (V-AE2) pass. Straight-wing development of D1–D2 can proceed in parallel, but D3 sign-off requires AE4 closed.
2. **AE6 (¼-chord force point)** — already fixed per the current branch; the `g_disp_colloc` work (§5.6) builds directly on it.
3. **`matrix_gaf_export.md` Phases 1–2** — MKAERO1 card, Mach-loop driver, bundle writers, Mach-tagged corrections. D2 extends rather than duplicates this machinery. (AE1/AE5/AE7/AE8 are trim-side defects and do **not** block Phase D.)

### 13.2 Top correctness risks

1. **Kernel/quadrature sign and branch errors** — the classic DLM failure mode. Mitigations: Blair benchmark with per-box Cp comparison (V-D1-2) catches global errors; Theodorsen limit (V-D1-4) catches phase-convention errors; the k = 0 anchoring (§5.4) eliminates the entire steady part as an error source; the [PA] oracle (V-D1-7) provides an independent, NASTRAN-validated full-matrix comparison at arbitrary (M, k) — including the known sign trap that Rodden 1971 switched the signs of K1/K2 relative to Rodden 1968 ([PA] stays with the 1968 convention to keep the VLM steady part consistent; sbeam must make the same choice for §5.4 to hold).
2. **Nonplanar T1/T2 + I2 closed forms** — ~~not printed in available references~~ **closed 2026-07-05**: [PA] implements all of them with per-equation Rodden citations and NASTRAN `idf1.f`/`idf2.f`/`incro.f` cross-check comments (§5.2, §5.3, §5.5); AFFDL-TR-71-5 no longer on the critical path. Planar-only remains a shippable D1 milestone; dihedral enablement gated by V-D1-6/V-D1-7.
3. **`Qhh^I/k` at small k** in PK and in the special-linear interpolation — division hazard; the interpolation basis (§7.3) is built for it, and k = 0-exact data improves on NASTRAN's extrapolation, but unit tests must cover k_est below the smallest MKAERO1 k.
4. **Mode tracking** (PK ordering, KE branch sorting, state-space V-sweep) — wrong pairing produces plausible-looking nonsense V-g plots. Three independent paths (PK, KE, RFA eigen) on the same models (V-D3-4, V-D4-3) are the cross-trap.
5. **Fourier-method bookkeeping** (Δf/period/output-window, zero-outside-table, e^{±iωt} consistency) — V-D5-2's zero-aero round-trip isolates it from the aerodynamics.
6. **Correction-at-all-k limitation** — out-of-phase parts uncorrected by construction [Z p.4-42]; not a bug, but must be documented prominently or users will over-trust transonic-corrected flutter points.

### 13.3 Effort

| Sub-phase | Content | Effort |
|---|---|---|
| D0 | g_disp_colloc + (AE4 separately scoped on backlog) | 2 d |
| D1 | dlm.py kernel/quadrature/branches + V-D1-1…6 | 8–10 d |
| D2 | unsteady GAF driver, complex coupling/corrections/export, gust columns + V-D2 | 4–5 d |
| D3 | cards/parser/case control, PK + KE, interpolation, f06, viewer V-g + V-D3 | 8–10 d |
| D4 | rfa.py fit + state space + sweep + export + V-D4 | 5–6 d |
| D5 | sol146 freq response, Fourier gust, turbulence, recovery, f06 + V-D5 | 8–10 d |
| Docs | theory manual + standards + card reference (continuous, per sub-phase) | 4 d |
| **Total D0–D5** | | **~40–47 days** |
| D6 | each enhancement 2–4 d, independently schedulable | — |

---

## 14. Open Decisions

| # | Decision | Recommendation | Owner |
|---|---|---|---|
| 1 | k = 0 in MKAERO1 (NASTRAN forbids; sbeam can compute exactly) | **Allow and recommend** — exact steady anchor for interpolation, RFA constraint, and divergence; document the deliberate NASTRAN deviation | Author |
| 2 | Flutter methods in scope | **PK + PKNL + KE**; K never; PKS/g-method/state-space-primary later (D6) | Author |
| 3 | Mach interpolation of GAFs | **Nearest-MKAERO1-Mach with warning** (matched-point practice); no (M,k) surface interpolation | Author |
| 4 | RFA trigger: bulk card vs case control vs export token | **Bulk `RFA` card** (§4.10) — deck-resident like AMODE; case control stays NASTRAN-clean | Author |
| 5 | State-space export form | **Velocity-independent pieces** (A0–A2, lag blocks, R, E + assembly recipe in manifest) — consumer assembles at any (ρ, V); avoid per-V file explosion | Author |
| 6 | SOL 146 ↔ SOL 111 sharing | Build the frequency-response core as a standalone function so Phase 3's SOL 111 wraps it with q̄ = 0; don't advertise SOL 111 until Phase 3 | Author |
| 7 | TLOAD2 analytic pulse | Parse-and-store, implement evaluation only if a verification deck needs it (TLOAD1+TABLED1 covers gusts) | Author |
| 8 | Where Bhh lives | Per-mode diagonal from TABDMP1 (KDAMP=+1 default); KDAMP=−1 complex-stiffness path implemented for KE parity | Author |
| 9 | DLM image treatment for parity | Reuse VLM parity convention (+1/−1/0) sourced from AERO.SYMXZ; case-control AESYM overrides deferred | Author |
| 10 | Viewer scope in D3 | V-g/V-f static plots only; animation D6 | Author |

---

## 15. References

- **[BLAIR]** Blair, M., *A Compilation of the Mathematics Leading to the Doublet Lattice Method*, WL-TR-92-3028, 1992 — kernel (eqs. 257–281), Laschka coefficients (p.89), parabolic quadrature closed forms (eqs. 286–300 + C source pp.107–135), 3×3 benchmark (App. B/C, pp.137–140).
- **[AAUG]** *MSC Nastran 2021.3 Aeroelastic Analysis User's Guide* — AIC/GAF chain (eqs. 2-1…2-4), splines (Ch.2 pp.27–41), K/KE/PK methods (eqs. 2-162…2-182), GAF interpolation (eqs. 2-151…2-161), SOL 146 + gust (eqs. 2-183…2-204), box sizing (pp.106–107), HA145B deck (pp.431–433), HA146A deck (pp.646–657), flutter summary format (pp.171–173, Listing 8-7).
- **[QRG]** *MSC Nastran 2024.1 Quick Reference Guide* — card field layouts cited per card in §4.
- **[Z]** *ZAERO 9.2 Theoretical Manual*, 3rd ed. — flutter methods incl. g-method (Ch.7), Roger/min-state RFA + state space (Ch.8, eqs. 8.3–8.23), frequency-domain ASE validation strategy (§9.6), gust (Ch.10, eqs. 10.12–10.56), continuous turbulence (Ch.11, eqs. 11.3–11.20), AIC correction (§4.3).
- **[P&G]** Pitt, D. M., Goodman, C. E., AIAA 87-0882 — k = 0-derived correction factors applied at all k (pp.510–511).
- **[CR]** NASA CR-172232 — gust downwash convention (eqs. 2–19), Sears benchmark tables (Tables I/II, pp.27–28), Padé/Küssner indicial fits (§2.3–2.5).
- **[PA]** Voß, A. (DLR-AE), *PanelAero* `DLM.py`, github.com/DLR-AE/PanelAero, BSD-3-Clause — executable reference implementation, copy in `.refs/PanelAero_DLM.py` (retrieved 2026-07-05). Contains: Landahl K1/K2 (Rodden 1971 eqs 7+8) with analytic k = 0 kernels K10/K20 (eqs 15+16) and r1 = 0 limits; T1/T2 (eqs 5, 21a); Laschka I1/I2 closed forms incl. u1 < 0 reflection for both (eqs A.1–A.9); planar/co-planar/far-field regularization branches with NASTRAN-matched thresholds (`idf1.f`/`idf2.f`/`incro.f` cross-check comments); parabolic (Rodden 1971 eqs 28–41) **and** quartic (Rodden 1998 eqs 15–34) quadrature; Desmarais and Watkins coefficient tables; Rodden-paper errata notes. Convention caveats: k = ω/V (not NASTRAN ω·c̄/2V); Rodden local (ȳ, z̄, e) semiwidth parameterization rather than Blair's B0/B1/B2 line-coordinate form — mathematically equivalent, so cross-check assembled AIC matrices, not intermediate terms.
- **[RTM]** Rodden, W. P., Taylor, P. F., McIntosh, S. C., *Improvements to the Doublet-Lattice Method in MSC/NASTRAN* — N5KA/N5KQ convergence studies; revises chordwise box-sizing to 50 boxes per minimum wavelength (`Δx < 0.02·V/f`); quartic-vs-parabolic guidance (quartic matters for box AR ≳ 3 and damping estimates). Modeling-guidelines companion to the 1998 quartic paper — contains no kernel math. Local copy: `~/Documents/Library/Software_Manuals/IMPROVEMENTS-TO-DLM.pdf`.
- To source externally during D3/D6 validation: NASA TM-100492/Yates (AGARD 445.6 data); optionally Rodden, Taylor, McIntosh, *Further Refinement of the Subsonic Doublet-Lattice Method*, J. Aircraft 35(5), 1998 (quartic derivation — the closed forms themselves are already in [PA]). AFFDL-TR-71-5 retired from the critical path (superseded by [PA], 2026-07-05). Local library copies: `~/Documents/Library/Flutter/` and `~/Documents/Library/Software_Manuals/` (working copies in `.refs/`, gitignored).
- **In-project precedents:** `aero/vlm.py` (AIC assembly pattern + steady anchor), `aero/coupling.py` (GAF chain), `aero/corrections.py` (correction tiers), `solver/sol103.py` (modal basis), `docs/30_future/designs/matrix_gaf_export.md` (MKAERO1, Mach-tagged corrections, export bundle, basis-consistency rule).

---

## 16. Acceptance Criteria

Per sub-phase, in addition to the per-gate tolerances of §12:

- **D1:** V-D1-1…5 pass plus V-D1-7(a) (PanelAero oracle, planar lattice); V-D1-6/V-D1-7(b) may gate dihedral support separately; `build_ajj_dlm` documented in the theory manual with the §3 conventions block.
- **D2:** V-D2-1…5 pass; export bundle from a sample deck contains complex QHH/QHJ per (M,k) with a manifest a consumer can act on without the BDF; corrections recorded per (M,k).
- **D3:** V-D3-1…6 pass; the HA145B-style sample deck produces a NASTRAN-format FLUTTER SUMMARY and a documented flutter crossing in `05_aeroelastics.md`; SOL 145 dispatched from `main.py` with parity from AERO.SYMXZ.
- **D4:** V-D4-1…3 pass; fit-quality report and state-space export documented; RFA flutter point agrees with PK within gate tolerance on both reference models.
- **D5:** V-D5-1…5 pass; 1-cosine sample deck and turbulence sample deck documented end-to-end (deck → f06 → viewer) in `05_aeroelastics.md`; Ā/N₀ block format documented.
- **All:** full pre-existing suite passes unchanged; decks without Phase D cards behave bit-identically; every sub-phase lands with its card-reference/theory/standard-doc updates and CHANGELOG entry per the step-completion rule; on promotion, backlog steps created (next free step numbers) and removed on completion.
