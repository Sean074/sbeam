# byu_wing_sweep.jl — A1 convergence sweep in VortexLattice.jl (peer-VLM check)
#
# Reproduces the BYU FLOW Lab "Steady-State Analysis of a Wing" example
# (https://flow.byu.edu/VortexLattice.jl/dev/examples/) and sweeps the spanwise
# panel count ns = 6, 12, 24, 48 (nc = 6, uniform spacing) — the same sequence
# run in sbeam (studies/a1_spanwise_spacing_study.py). This answers the one open
# A1 question: does an independent, AVL-validated VLM drift the same way under
# spanwise refinement?
#
# ---------------------------------------------------------------------------
# INSTALL & RUN (macOS, no Fortran/X11 needed):
#   brew install --cask julia          # or: curl -fsSL https://install.julialang.org | sh
#   julia                              # then, once:
#     julia> ]add VortexLattice        # press ]  for pkg mode, then backspace
#   julia studies/byu_wing_sweep.jl
#
# API NOTE: this matches the *dev* docs (wing_to_grid / System / steady_analysis!).
# If `]add VortexLattice` gives you an older registered release that errors with a
# MethodError on wing_to_grid, install the docs version:  ]add VortexLattice#master
# (older API used wing_to_surface_panels(...) -> (grid, surface) and
#  steady_analysis(surfaces, ref, fs; symmetric=...)).
# ---------------------------------------------------------------------------

using VortexLattice
using Printf

# --- BYU wing geometry (right half; symmetric analysis mirrors it) ----------
xle   = [0.0, 0.4]
yle   = [0.0, 7.5]
zle   = [0.0, 0.0]
chord = [2.2, 1.8]
theta = [2.0*pi/180, 2.0*pi/180]   # 2 deg uniform twist (Ainc-equivalent BC)
phi   = [0.0, 0.0]
fc    = fill((xc) -> 0, 2)         # flat camber line

# --- reference + freestream (alpha 1 deg + 2 deg twist = 3 deg incidence) ---
Sref = 30.0; cref = 2.0; bref = 15.0; rref = [0.50, 0.0, 0.0]; Vinf = 1.0
ref = Reference(Sref, cref, bref, rref, Vinf)

alpha = 1.0*pi/180
beta  = 0.0
Omega = [0.0; 0.0; 0.0]
fs = Freestream(Vinf, alpha, beta, Omega)

symmetric = true
alpha_eff = 3.0*pi/180             # CL_alpha = CL / alpha_eff (matches sbeam table)

# --- sbeam (uniform spanwise) CL_alpha for side-by-side comparison ----------
sbeam = Dict(6 => 4.7697, 12 => 4.6746, 24 => 4.6216, 48 => 4.5938)

nc = 6
spacing_s = Uniform()
spacing_c = Uniform()

println("\nBYU wing — spanwise convergence (nc=$nc, uniform spacing, alpha_eff=3 deg)")
println("AVL published value (ns=12): CL = 0.24454,  Cm = -0.02091,  CDi = 0.00248\n")
@printf("%5s %12s %12s %12s %12s %14s %10s\n",
        "ns", "CL", "CL_a /rad", "Cm", "CDi(far)", "sbeam CL_a", "Δ(VLM-sb)")
println("-"^82)

for ns in (6, 12, 24, 48)
    grid, ratio = wing_to_grid(xle, yle, zle, chord, theta, phi, ns, nc;
        fc = fc, spacing_s = spacing_s, spacing_c = spacing_c)
    system = System([grid]; ratios = [ratio])

    steady_analysis!(system, ref, fs; symmetric = symmetric)

    CF, CM = body_forces(system; frame = Wind())
    CD, CY, CL = CF
    Cl, Cm, Cn = CM
    CDiff = far_field_drag(system)

    cla = CL / alpha_eff
    sb  = get(sbeam, ns, NaN)
    @printf("%5d %12.5f %12.4f %12.5f %12.6f %14.4f %10.4f\n",
            ns, CL, cla, Cm, CDiff, sb, cla - sb)
end

println("""
\nINTERPRETATION
  If the VLM.jl 'CL_a /rad' column drifts down with ns the same way sbeam does
  (Δ(VLM-sb) stays small, both -> ~4.57), then A1 is BENIGN — the deficit is the
  lifting-surface-vs-lifting-line gap plus normal mesh convergence; close A1.
  If VLM.jl instead plateaus near 4.667 while sbeam falls to ~4.57, a genuine
  spanwise-count kernel bias remains in sbeam (isolated from spacing/nchord/box-AR).
""")
