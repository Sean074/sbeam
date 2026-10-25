# Your first analysis in ten minutes

A new user, an empty folder, one small deck, one SOL 101 run, and a plot you can read.
Everything below is checked by `tests/docs/test_first_analysis_tutorial.py`: the deck is
lifted out of this page, run, and the numbers quoted here are asserted against the f06.

What you will have at the end:

1. A 10 m steel cantilever with a 1 kN tip load, written as a NASTRAN-format deck.
2. Its `.f06` result, read block by block against two hand calculations.
3. The deflected shape plotted, once in the viewer and once from a Python script.

You need Python 3.9+ and about ten minutes. No NASTRAN experience is assumed, but the
deck format is NASTRAN's, so anything you learn here transfers.

---

## 1. Install (two minutes)

From a clone of the repository:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[viewer]"
```

`pip install -e .` alone installs the solver; the `[viewer]` extra adds the Streamlit GUI
used in §5. Check the install with `sbeam --help` (or `python -m sbeam.main --help`).

---

## 2. The model

A straight steel beam, 10 m long, clamped at one end, with a 1 kN load pushing the free end
down (−Z). Solid square section, side 0.31623 m, so the area is 0.1 m².

```
      Z
      ^
      |   grid 1    2    3    4    5    6
  ====|===o----o----o----o----o----o   --> X
  clamp   0    2    4    6    8   10 m
                                   |
                                   v  F = 1000 N  (−Z)
```

Six grids, five CBAR elements of 2 m each. Units are SI throughout: metres, newtons,
kilograms, pascals. **sbeam never converts units** — it solves whatever consistent set the
deck is written in, so the choice is yours but it must be consistent
(`../10_standard/09_conventions.md` §7).

Two numbers to hold on to, from Euler–Bernoulli beam theory with
E = 2.0×10¹¹ Pa and I = 8.333×10⁻⁴ m⁴ (so EI = 1.6666×10⁸ N·m²):

| Quantity | Formula | Value |
|---|---|---|
| Tip deflection | δ = PL³ / 3EI | 1000 × 10³ / (3 × 1.6666×10⁸) = **2.00008×10⁻³ m** |
| Root bending moment | M = PL | 1000 × 10 = **1.0×10⁴ N·m** |
| Root bending stress | σ = M·c / I, c = 0.15811 m | 1.0×10⁴ × 0.15811 / 8.333×10⁻⁴ = **1.8974×10⁶ Pa** |

The solver should reproduce all three exactly, because a tip-loaded prismatic cantilever is
a case the cubic beam element represents without approximation.

---

## 3. Write the deck

Create an empty folder and save this as `cantilever.bdf`. Lines starting with `$` are
comments; fields are comma-separated ("free field"). Leave a field empty to take its default.

```text
$ cantilever.bdf — sbeam first-analysis tutorial
$ 10 m steel cantilever, 5 CBAR elements, 1 kN tip load in -Z. Units: m, N, kg, Pa.
SOL 101
SUBCASE 1
  TITLE = Tutorial cantilever
  SPC   = 1
  LOAD  = 10
  DISPLACEMENT = ALL
  SPCFORCE     = ALL
  FORCE        = ALL
  STRESS       = ALL
BEGIN BULK
$ GRID, ID, CP, X, Y, Z
GRID, 1, , 0.0,  0.0, 0.0
GRID, 2, , 2.0,  0.0, 0.0
GRID, 3, , 4.0,  0.0, 0.0
GRID, 4, , 6.0,  0.0, 0.0
GRID, 5, , 8.0,  0.0, 0.0
GRID, 6, , 10.0, 0.0, 0.0
$ MAT1, MID, E, G, NU, RHO      (steel)
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
$ PBAR, PID, MID, A, I1, I2, J   (solid square, side 0.31623 m)
PBAR, 1, 1, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
$ continuation: stress recovery points C, D, E, F as (y, z) pairs = the four corners
+, 0.15811, 0.15811, -0.15811, 0.15811, -0.15811, -0.15811, 0.15811, -0.15811
$ CBAR, EID, PID, GA, GB, X1, X2, X3   (orientation vector = +Y)
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
CBAR, 2, 1, 2, 3, 0.0, 1.0, 0.0
CBAR, 3, 1, 3, 4, 0.0, 1.0, 0.0
CBAR, 4, 1, 4, 5, 0.0, 1.0, 0.0
CBAR, 5, 1, 5, 6, 0.0, 1.0, 0.0
$ SPC1, SID, DOFs, grid           (clamp all six DOFs at grid 1)
SPC1, 1, 123456, 1
$ FORCE, SID, grid, CID, magnitude, direction vector
FORCE, 10, 6, 0, 1000.0, 0.0, 0.0, -1.0
ENDDATA
```

Reading it top to bottom:

- **Case control** (everything before `BEGIN BULK`). `SOL 101` asks for linear statics.
  The subcase selects constraint set 1 and load set 10 and requests the four output blocks
  you will read in §4.
- **GRID** places the six nodes on the X axis.
- **MAT1** is steel: E, G, Poisson's ratio, density. Density is unused in a static run but
  costs nothing to carry.
- **PBAR** is the section: area, the two bending inertias `I1`/`I2`, torsion constant `J`.
  The continuation line gives four stress-recovery points in the section plane; the
  solver reports bending stress at each. Without them the stress block prints zeros.
- **CBAR** connects the grids. Fields 6–8 are the orientation vector, which fixes where the
  element's local y axis points: here +Y, so local z is global Z and "plane 2" bending is
  the bending this load produces.
- **SPC1** clamps grid 1 in all six degrees of freedom (`123456` = Tx Ty Tz Rx Ry Rz).
- **FORCE** applies 1000 N at grid 6 along the unit vector (0, 0, −1).

Full field tables for every card: `../10_standard/02_card_reference.md`.

---

## 4. Run it and read the f06

```bash
sbeam cantilever.bdf
```

```
Written: /your/folder/cantilever.f06
```

The `.f06` is a plain-text report in NASTRAN's layout, written next to the input. Open it
in any editor. Four blocks follow the header, in the order the subcase requested them.

### 4.1 Displacement vector

```
      POINT ID.   TYPE           T1           T2           T3           R1           R2           R3
             1     G   0.000000E+00 0.000000E+00 0.000000E+00 0.000000E+00 0.000000E+00 0.000000E+00
             2     G   0.000000E+00 0.000000E+00-1.120045E-04 0.000000E+00 1.080043E-04 0.000000E+00
             ...
             6     G   0.000000E+00-0.000000E+00-2.000080E-03 0.000000E+00 3.000120E-04 0.000000E+00
```

One row per grid: three translations `T1 T2 T3` (X Y Z) and three rotations `R1 R2 R3`,
in that grid's output coordinate system (global here). Grid 1 is all zeros because it is
clamped. Grid 6 moves **−2.000080×10⁻³ m** in Z, which is the PL³/3EI value from §2 to
every printed digit. `R2` at the tip, 3.0×10⁻⁴ rad, is the slope PL²/2EI; it is positive
because a rotation about +Y tips +X toward −Z, the way the beam droops.

### 4.2 Forces of single-point constraint

```
      POINT ID.   TYPE           T1           T2           T3           R1           R2           R3
             1     G   0.000000E+00 0.000000E+00 1.000000E+03 0.000000E+00-1.000000E+04 0.000000E+00
```

The reactions the clamp supplies: +1000 N up in Z to balance the load, and a moment of
−1.0×10⁴ N·m about Y to balance the load's lever arm of 10 m. These are the `M = PL` check
from §2, with the sign that opposes the applied load. If a model is under-constrained the
run fails before this block with a "singular stiffness matrix" message, which is the first
thing to look for when a new deck will not solve.

### 4.3 Forces in bar elements

```
       ELEMENT      BEND-MOMENT END-A         BEND-MOMENT END-B             - SHEAR -                 AXIAL
           ID.        PLANE 1      PLANE 2      PLANE 1      PLANE 2      PLANE 1      PLANE 2        FORCE       TORQUE
             1  -0.000000E+00-1.000000E+04 0.000000E+00-8.000000E+03 0.000000E+00-1.000000E+03 0.000000E+00 0.000000E+00
             ...
             5  -0.000000E+00-2.000000E+03 0.000000E+00-4.365575E-11 0.000000E+00-1.000000E+03 0.000000E+00 0.000000E+00
```

This is the internal-load table, in the element's local axes and in the MSC NASTRAN layout.
Everything the load produces is in **plane 2**, the element x–z plane, because the load is
in Z and the orientation vector put local y along global Y. The plane-2 moment runs from
−1.0×10⁴ N·m at the root (end A of element 1) linearly to zero at the tip (end B of
element 5; the 10⁻¹¹ is round-off and its digits may differ on your machine), and the
plane-2 shear is a constant −1000 N. Plane 1, axial force and torque are zero.

The sign needs one sentence: a positive plane moment puts the element's +y / +z fibre in
compression. A downward tip load stretches the top (+z) fibre, so the moment is negative.
The next block confirms it. Convention and derivation: `../10_standard/09_conventions.md`
§9 and `../10_standard/03_static_analysis.md`.

### 4.4 Stresses in bar elements

```
       ELEMENT            SA1          SA2          SA3          SA4        AXIAL       SA-MAX       SA-MIN    M.S.-T
           ID.            SB1          SB2          SB3          SB4       STRESS       SB-MAX       SB-MIN    M.S.-C
             1   1.897396E+06 1.897396E+06-1.897396E+06-1.897396E+06 0.000000E+00 1.897396E+06-1.897396E+06
                 1.517917E+06 1.517917E+06-1.517917E+06-1.517917E+06              1.517917E+06-1.517917E+06
```

Two rows per element: end A on the first line, end B on the second. `SA1`–`SA4` are the
bending stresses at the four PBAR recovery points C, D, E, F; `AXIAL` is P/A; `SA-MAX` and
`SA-MIN` are the extreme totals. At the root, points C and D (both at z = +0.15811, the
top corners) carry **+1.897×10⁶ Pa**, tension, and E and F (bottom corners) the same in
compression. That is the σ = Mc/I check from §2. Margins of safety are blank because no
allowables are given.

So far you have three hand numbers and three matches, which is the whole point of a first
run: before trusting a solver on a model you cannot check, make it reproduce one you can.

---

## 5. Plot it

### 5.1 In the viewer

```bash
sbeam-view
```

A browser tab opens. Upload `cantilever.bdf` in the sidebar; because it carries case
control, the model and the subcase load together. The **Model** tab shows the six grids,
five elements and the load arrow at the tip. Open the **Results** tab, press **Run
Analysis**, and the deformed shape appears over a grey ghost of the undeformed beam. The
scale slider starts at a magnification that makes the tip move about a tenth of the span,
so a 2 mm deflection on a 10 m beam is visible; the true shape is the cubic you expect, not
a straight tilt. Below the figure are the same four tables as the f06. The viewer is
described in full in `../10_standard/06_viewer.md`.

### 5.2 From Python

The CLI is a thin wrapper around three calls: parse, solve, read the result. This script
does the same and plots the Z deflection against the closed-form curve
w(x) = Px²(3L − x) / 6EI. It needs `matplotlib` (`pip install matplotlib`; it is not an
sbeam dependency).

```python
# plot_cantilever.py — sbeam first-analysis tutorial
import numpy as np

from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol101 import run_sol101

case_control, bulk = parse_bdf("cantilever.bdf")
result = run_sol101(bulk, case_control.subcases[0])

# Displacements are one flat vector, six entries per grid in sorted-GID order;
# build_grid_index gives the grid -> position map, and T3 is the third entry.
index = build_grid_index(bulk)
x = np.array([bulk.grids[gid].x for gid in sorted(bulk.grids)])
w = np.array([result.displacements[6 * index[gid] + 2] for gid in sorted(bulk.grids)])

P, L, EI = 1000.0, 10.0, 2.0e11 * 8.333e-4
xs = np.linspace(0.0, L, 101)
w_exact = -P * xs**2 * (3 * L - xs) / (6 * EI)

print(f"tip deflection  solver {w[-1]:.6e}  theory {w_exact[-1]:.6e}")
print(f"root reaction   {result.reactions[1]}")

import matplotlib.pyplot as plt
plt.plot(xs, w_exact, label="PL³/3EI theory")
plt.plot(x, w, "o", label="sbeam SOL 101")
plt.xlabel("x [m]"); plt.ylabel("w [m]"); plt.legend(); plt.grid(True)
plt.title("Tutorial cantilever: tip deflection")
plt.show()
```

```
tip deflection  solver -2.000080e-03  theory -2.000080e-03
root reaction   [    0.     0.  1000.     0. -10000.     0.]
```

The five solver points sit on the theory curve. `result` is a `Sol101Result` whose other
fields (`bar_forces`, `bar_stresses`, `reactions`) hold the tables from §4 as plain
dataclasses keyed by element or grid ID; the full programmatic surface, and which parts of
it are public, is in `../10_standard/11_python_api.md`.

---

## 6. Where next

- **Change something and re-run.** Halve `I1`/`I2` and the tip deflection doubles; move
  the FORCE to grid 4 and the moment diagram breaks at element 3. Ten-second experiments
  like these are how the sign conventions become second nature.
- **Normal modes.** Replace `SOL 101` with `SOL 103`, swap the `LOAD` line for
  `METHOD = 1`, add `EIGRL, 1, , , 5` to the bulk, and the f06 lists the first five natural
  frequencies. The first should be 2.578 Hz for this beam, against
  f₁ = (1.875²/2π)·√(EI/ρAL⁴) = 2.578 Hz; it appears twice, because a square section bends
  identically in Y and Z: `../10_standard/04_modal_analysis.md`.
- **A real aeroplane.** The Cessna 210 flagship deck family takes the same format through
  static aeroelastic trim, monitor loads and transient maneuvers:
  `02_realistic_airplane_sol144.md`.
- **Every card, every field:** `../10_standard/02_card_reference.md`.
- **Signs, axes and frames,** the reference you will want open beside any result:
  `../10_standard/09_conventions.md`.
