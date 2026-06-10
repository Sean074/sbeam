"""A1 diagnostic — spanwise-spacing convergence of the VLM lift-curve slope.

Purpose
-------
Discriminate the two surviving hypotheses for finding A1 (VLM CL_alpha runs a
few percent below analytical references and the deficit GROWS with spanwise
refinement):

  H2 (spacing artifact): UNIFORM spanwise spacing under-resolves the tip-region
     loading (which has a square-root edge behaviour). CL_alpha then drifts with
     refinement, while COSINE spanwise spacing (clustered at root & tip,
     Hough 1973 / Lan 1974, NASA SP-405) converges fast to a stable plateau.

  H3 (kernel bug): both spacings drift together and the converged value is still
     low vs an independent peer VLM (AVL) — i.e. the trailing-vortex induced
     downwash is genuinely biased.

Method
------
For fixed planforms, sweep nspan with uniform vs cosine spanwise breakpoints
(via AEFACT — no mesher change), nchord fixed. Full-span model (two CAERO1
half-surfaces, parity=0) so CL is the true wing CL. Compare CL_alpha to:
  * AVL (BYU VortexLattice.jl tapered wing): CL_alpha = 4.667 /rad  (a real
    peer-VLM number, not an upper bound).
  * Lifting-line upper bounds (rectangular AR=8): elliptic 2*pi/(1+2/AR)=5.027,
    rectangular ~4.78, Polhamus ~4.91 /rad.

A true elliptic *planform* needs curved-LE meshing (tip chord -> 0 degenerates
the trapezoidal mesher), so the AVL-anchored tapered wing is used as the primary
reference — it is a stronger anchor than a lifting-line upper bound anyway.

Run:  python studies/a1_spanwise_spacing_study.py
"""

from math import radians, cos, pi

import numpy as np

from sbeam.model.aero import Caero1, Paero1, Aefact, Aeros
from sbeam.aero.panel import mesh_caero1
from sbeam.aero.vlm import solve_rigid_cl


def cosine_breaks(n: int) -> list:
    """n+1 breakpoints in [0,1] clustered at both ends (full cosine)."""
    return [0.5 * (1.0 - cos(pi * i / n)) for i in range(n + 1)]


def _half(eid, root_c, tip_c, sweep, half_span, sign, nspan, nchord, spacing, start_k):
    """Boxes for one wing half (sign=+1 starboard, -1 port)."""
    p1 = (0.0, 0.0, 0.0)
    p4 = (sweep, sign * half_span, 0.0)
    if spacing == "uniform":
        caero = Caero1(eid, 1, 0, nspan, nchord, 0, 0, 1, p1, root_c, p4, tip_c)
        return mesh_caero1(caero, Paero1(1), {}, {}, start_k=start_k)
    sid = eid  # unique AEFACT sid per half
    eta = cosine_breaks(nspan)
    caero = Caero1(eid, 1, 0, 0, nchord, sid, 0, 1, p1, root_c, p4, tip_c)
    return mesh_caero1(caero, Paero1(1), {sid: Aefact(sid, eta)}, {}, start_k=start_k)


def full_wing(root_c, tip_c, sweep, half_span, nspan, nchord, spacing):
    """Full-span boxes (two halves), parity=0."""
    sb = _half(100, root_c, tip_c, sweep, half_span, +1, nspan, nchord, spacing, 0)
    pt = _half(200, root_c, tip_c, sweep, half_span, -1, nspan, nchord, spacing, len(sb))
    return sb + pt


def cl_alpha(boxes, aeros, alpha_deg):
    a = radians(alpha_deg)
    r = solve_rigid_cl(boxes, a, parity=0, aeros=aeros, xref=0.0)
    return r["CL"] / a


def run_case(name, root_c, tip_c, sweep, half_span, nchord, aeros, nspans,
             alpha_deg, references):
    print(f"\n{'='*72}\n{name}\n{'='*72}")
    AR = aeros.bref ** 2 / aeros.sref
    print(f"AR = bref^2/Sref = {AR:.3f},  nchord = {nchord},  alpha = {alpha_deg} deg")
    print("references: " + ", ".join(f"{k}={v:.3f}" for k, v in references.items()))
    print(f"\n{'nspan':>6} | {'uniform CLa':>12} {'cosine CLa':>12} | "
          f"{'uni %dev':>9} {'cos %dev':>9}   (dev vs primary ref)")
    print("-" * 72)
    ref = list(references.values())[0]
    rows = []
    for ns in nspans:
        bu = full_wing(root_c, tip_c, sweep, half_span, ns, nchord, "uniform")
        bc = full_wing(root_c, tip_c, sweep, half_span, ns, nchord, "cosine")
        cu = cl_alpha(bu, aeros, alpha_deg)
        cc = cl_alpha(bc, aeros, alpha_deg)
        rows.append((ns, cu, cc))
        print(f"{ns:>6} | {cu:>12.4f} {cc:>12.4f} | "
              f"{100*(cu-ref)/ref:>8.2f}% {100*(cc-ref)/ref:>8.2f}%")
    # Drift between coarsest and finest
    du = rows[-1][1] - rows[0][1]
    dc = rows[-1][2] - rows[0][2]
    print(f"\n  drift coarsest->finest:  uniform {du:+.4f}   cosine {dc:+.4f}")
    return rows


def main():
    np.set_printoptions(suppress=True)

    # --- BYU tapered wing (AVL-anchored): CL_alpha = 4.667 /rad ---------------
    byu_aeros = Aeros(acsid=0, rcsid=0, cref=2.0, bref=15.0, sref=30.0, symxz=0, symxy=0)
    run_case(
        "BYU VortexLattice.jl / AVL wing  (root 2.2, tip 1.8, sweep 0.4, b/2=7.5)",
        root_c=2.2, tip_c=1.8, sweep=0.4, half_span=7.5, nchord=6,
        aeros=byu_aeros, nspans=[6, 12, 24, 48], alpha_deg=3.0,
        references={"AVL": 0.24454 / radians(3.0)},
    )

    # --- Rectangular AR=8 (the A1-flagged case) ------------------------------
    rect_aeros = Aeros(acsid=0, rcsid=0, cref=1.0, bref=8.0, sref=8.0, symxz=0, symxy=0)
    run_case(
        "Rectangular AR=8 wing  (chord 1.0, b/2=4.0, unswept)",
        root_c=1.0, tip_c=1.0, sweep=0.0, half_span=4.0, nchord=8,
        aeros=rect_aeros, nspans=[10, 20, 40, 80], alpha_deg=1.0,
        references={"ellipticLL": 2*pi/(1+2/8), "rectLL": 4.78, "Polhamus": 4.91},
    )

    # --- Control probe 1: chordwise (nchord) sensitivity at fixed nspan -------
    # If lift is nchord-insensitive, the refinement drift is purely SPANWISE.
    print(f"\n{'='*72}\nControl probe 1 — BYU wing, nchord sensitivity at fixed nspan=24\n{'='*72}")
    print(f"{'nchord':>6} | {'uniform CLa':>12}   (AVL 4.670)")
    print("-" * 40)
    for ncd in [2, 4, 6, 8, 12]:
        b = full_wing(2.2, 1.8, 0.4, 7.5, 24, ncd, "uniform")
        print(f"{ncd:>6} | {cl_alpha(b, byu_aeros, 3.0):>12.4f}")

    # --- Control probe 2: joint refinement holding box aspect ratio ~ 1 -------
    # Rules out a box-AR confound (refining nspan alone elongates boxes).
    print(f"\n{'='*72}\nControl probe 2 — BYU wing, joint refinement at box AR ~ 1\n{'='*72}")
    print(f"{'(nspan,nchord)':>16} | {'uniform CLa':>12}   (AVL 4.670)")
    print("-" * 46)
    for ns, ncd in [(8, 2), (15, 4), (22, 6), (30, 8)]:
        b = full_wing(2.2, 1.8, 0.4, 7.5, ns, ncd, "uniform")
        print(f"{('('+str(ns)+','+str(ncd)+')'):>16} | {cl_alpha(b, byu_aeros, 3.0):>12.4f}")


if __name__ == "__main__":
    main()
