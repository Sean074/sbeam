# Beam methods — the CBAR element, and the code checked against it

This page derives the stiffness and mass matrices of the `CBAR` element from Euler-Bernoulli
beam theory, and shows that the code implements them. Each claim about the code names the
test that fails if the claim stops being true. The matrices are printed with the signs and
the degree-of-freedom order the code uses.

Assembly, the solution and the recovery of forces and stresses are described in the solver
guides ([SOL 101](../10_standard/03_static_analysis.md),
[SOL 103](../10_standard/04_modal_analysis.md)) and are not repeated here.

**References:** NASA-CR-145949; <https://www.sesamx.io/blog/beam_finite_element/>;
<https://mechanicalc.com/reference/finite-element-analysis>.

This page replaced the beam-methods notebook in v0.4.2 (#132). The notebook's own
numpy matrices are gone: the checks below run the solver.

## 1. Theory and assumptions

1. Plane sections remain plane and normal to the neutral axis.
2. No shear deformation. This holds for slender beams, length over depth above about 10.
3. Small displacements and rotations.
4. Linear elastic material; a uniform section along each element.

With no load between the grids, the four motions of a straight uniform bar separate:

$$
EA\,u'' = 0, \qquad GJ\,\theta_x'' = 0, \qquad EI_1\,v'''' = 0, \qquad EI_2\,w'''' = 0
$$

Here $u$ is the axial displacement, $\theta_x$ the twist, and $v$, $w$ the transverse
displacements along local $y$ and $z$. The strain energy and the kinetic energy of one
element of length $L$ are

$$
U = \tfrac12\int_0^L \left( EA\,u'^2 + EI_1\,v''^2 + EI_2\,w''^2 + GJ\,\theta_x'^2 \right) dx
$$

$$
T = \tfrac12\int_0^L \left( m\,(\dot u^2 + \dot v^2 + \dot w^2) + \rho\,(I_1 + I_2)\,\dot\theta_x^2 \right) dx,
\qquad m = \rho A + \mathrm{NSM}
$$

The rotary inertia of the section in bending ($\rho I\,\dot\theta_y^2$, $\rho I\,\dot\theta_z^2$)
is not in $T$. The torsional inertia uses the polar area moment $I_1 + I_2$, not the torsion
constant $J$, and the non-structural mass NSM adds to the translations only.

## 2. Degrees of freedom and local axes

A `CBAR` has 12 degrees of freedom, six at end A then six at end B:

$$
\mathbf{u}_e = [\,u_A,\; v_A,\; w_A,\; \theta_{xA},\; \theta_{yA},\; \theta_{zA},\;
                  u_B,\; v_B,\; w_B,\; \theta_{xB},\; \theta_{yB},\; \theta_{zB}\,]^T
$$

In the code these are indices 0 to 11. The local axes come from the two grids and the
orientation vector $\mathbf{v}$ of the `CBAR` card:

$$
\hat{e}_x = \frac{\mathbf{x}_B - \mathbf{x}_A}{L}, \qquad
\hat{e}_y = \frac{\mathbf{v} - (\mathbf{v}\cdot\hat{e}_x)\,\hat{e}_x}{|\mathbf{v} - (\mathbf{v}\cdot\hat{e}_x)\,\hat{e}_x|}, \qquad
\hat{e}_z = \hat{e}_x \times \hat{e}_y
$$

So the orientation vector lies in the local $x$–$y$ plane, which NASTRAN calls plane 1. An
orientation vector parallel to the element axis is refused.

| Plane | Motion | Rotation | PBAR inertia | Indices |
|---|---|---|---|---|
| Plane 1, local $x$–$y$ | $v$ | $\theta_z = +\,dv/dx$ | `I1` | 1, 5, 7, 11 |
| Plane 2, local $x$–$z$ | $w$ | $\theta_y = -\,dw/dx$ | `I2` | 2, 4, 8, 10 |

The minus sign in plane 2 is the right-hand rule: a positive rotation about $y$ lowers the
beam in $z$ as $x$ increases.

With $[R]$ the 3×3 matrix whose rows are $\hat{e}_x$, $\hat{e}_y$, $\hat{e}_z$ in basic
coordinates, the element transformation is

$$
[T] = \mathrm{blkdiag}([R], [R], [R], [R]), \qquad \mathbf{u}_{local} = [T]\,\mathbf{u}_{global}
$$

$$
[K_e]_{global} = [T]^T [k_e] [T], \qquad [M_e]_{global} = [T]^T [m_e] [T]
$$

## 3. Shape functions

With $\xi = x/L$, the axial displacement and the twist are linear between the grids:

$$
N_1 = 1 - \xi, \qquad N_2 = \xi
$$

The transverse displacements are cubic (Hermite):

$$
H_1 = 1 - 3\xi^2 + 2\xi^3, \qquad H_2 = L\,(\xi - 2\xi^2 + \xi^3)
$$

$$
H_3 = 3\xi^2 - 2\xi^3, \qquad H_4 = L\,(-\xi^2 + \xi^3)
$$

$$
v(x) = H_1 v_A + H_2\,\theta_{zA} + H_3 v_B + H_4\,\theta_{zB}
$$

$$
w(x) = H_1 w_A - H_2\,\theta_{yA} + H_3 w_B - H_4\,\theta_{yB}
$$

A linear $u$ and a cubic $v$ are the exact solutions of the equations of section 1. For a
static problem loaded only at grids the element is therefore exact at any mesh size, and
refining the mesh changes nothing. For a vibration problem the true shape is not a cubic,
and the frequencies converge as the mesh is refined (section 6).

## 4. Stiffness matrix

Putting the shape functions into $U = \tfrac12\,\mathbf{u}_e^T [k_e]\,\mathbf{u}_e$ gives four
blocks that do not couple.

**Axial** ($u_A$, $u_B$) and **torsion** ($\theta_{xA}$, $\theta_{xB}$):

$$
[k_{ax}] = \frac{EA}{L} \begin{bmatrix} 1 & -1 \\ -1 & 1 \end{bmatrix}, \qquad
[k_{tor}] = \frac{GJ}{L} \begin{bmatrix} 1 & -1 \\ -1 & 1 \end{bmatrix}
$$

**Bending in plane 1** ($v_A$, $\theta_{zA}$, $v_B$, $\theta_{zB}$):

$$
[k_{1}] = \frac{EI_1}{L^3}
\begin{bmatrix}
 12 &  6L & -12 &  6L \\
 6L &  4L^2 & -6L &  2L^2 \\
-12 & -6L &  12 & -6L \\
 6L &  2L^2 & -6L &  4L^2
\end{bmatrix}
$$

**Bending in plane 2** ($w_A$, $\theta_{yA}$, $w_B$, $\theta_{yB}$):

$$
[k_{2}] = \frac{EI_2}{L^3}
\begin{bmatrix}
 12 & -6L & -12 & -6L \\
-6L &  4L^2 & 6L &  2L^2 \\
-12 &  6L &  12 &  6L \\
-6L &  2L^2 & 6L &  4L^2
\end{bmatrix}
$$

The code is `local_stiffness` in `sbeam/assembly/stiffness.py`.

## 5. Consistent mass matrix

The same shape functions in $T = \tfrac12\,\dot{\mathbf{u}}_e^T [m_e]\,\dot{\mathbf{u}}_e$ give the
consistent mass matrix, with $m = \rho A + \mathrm{NSM}$.

**Axial** and **torsion**:

$$
[m_{ax}] = \frac{mL}{6} \begin{bmatrix} 2 & 1 \\ 1 & 2 \end{bmatrix}, \qquad
[m_{tor}] = \frac{\rho\,(I_1 + I_2)\,L}{6} \begin{bmatrix} 2 & 1 \\ 1 & 2 \end{bmatrix}
$$

**Bending in plane 1** ($v_A$, $\theta_{zA}$, $v_B$, $\theta_{zB}$):

$$
[m_{1}] = \frac{mL}{420}
\begin{bmatrix}
 156 &  22L &  54 & -13L \\
 22L &  4L^2 &  13L & -3L^2 \\
  54 &  13L & 156 & -22L \\
-13L & -3L^2 & -22L &  4L^2
\end{bmatrix}
$$

**Bending in plane 2** ($w_A$, $\theta_{yA}$, $w_B$, $\theta_{yB}$):

$$
[m_{2}] = \frac{mL}{420}
\begin{bmatrix}
 156 & -22L &  54 &  13L \\
-22L &  4L^2 & -13L & -3L^2 \\
  54 & -13L & 156 &  22L \\
 13L & -3L^2 &  22L &  4L^2
\end{bmatrix}
$$

The code is `local_mass` in `sbeam/assembly/mass_matrix.py`.

## 6. Mesh convergence

The first bending frequency of a cantilever is

$$
f_1 = \frac{(\beta_1 L)^2}{2\pi}\sqrt{\frac{EI}{\rho A L^4}}, \qquad \beta_1 L = 1.87510407
$$

Two things are predicted before any run. The element is a Rayleigh-Ritz method (the shape
functions satisfy continuity and the mass is consistent), so the computed frequency is never
below the exact one. The error of a cubic element in the frequency is of order $h^4$, so
doubling the number of elements divides the error by 16.

The table is the solver's result for a cantilever with the material, section and length of
`val_cantilever_modes.bdf` ($L$ = 10 m, exact $f_1$ = 2.578409 Hz), meshed with $n$ equal
elements. The error is $(f_1 - f_{exact})/f_{exact}$.

| Elements | f1, Hz | Error |
|---|---|---|
| 1 | 2.590667 | 4.754e-03 |
| 2 | 2.579655 | 4.834e-04 |
| 3 | 2.578670 | 1.013e-04 |
| 5 | 2.578443 | 1.352e-05 |
| 10 | 2.578411 | 8.537e-07 |
| 20 | 2.578409 | 5.2e-08 |

Every error is positive. From 5 to 10 elements the error falls by a factor of 15.8, and from
10 to 20 by about 16. One element is already within 0.5 %.

The 20-element error is given to two figures because the third moves with the machine: the
eigenvalue solve gives $f_1$ to a few parts in $10^{10}$, and two machines differed by
2.6e-10 of $f_1$ on this row. The other rows are far above that.

## 7. The code against the closed forms

Two shipped decks, each a 10-element steel cantilever of length 10 m with a square section
($A$ = 0.1 m², $I_1 = I_2$ = 8.333e-4 m⁴):

- [`val_cantilever_static.bdf`](../../sample/validation/val_cantilever_static.bdf): SOL 101,
  a tip load $P$ = 1000 N along −Z.
- [`val_cantilever_modes.bdf`](../../sample/validation/val_cantilever_modes.bdf): SOL 103.
  The deck constrains the X–Y bending family, so mode 2 is the second X–Z bending mode.

| Quantity | Closed form | Closed-form value | sbeam |
|---|---|---|---|
| Tip deflection Tz, m | $-PL^3/3EI$ | −2.0000800e-03 | −2.0000800e-03 |
| Tip rotation Ry, rad | $PL^2/2EI$ | 3.0001200e-04 | 3.0001200e-04 |
| Root reaction Fz, N | $P$ | 1000.0000 | 1000.0000 |
| Root reaction My, N·m | $-PL$ | −10000.000 | −10000.000 |
| f1, Hz | $\beta_1 L$ = 1.87510407 | 2.578409 | 2.578411 |
| f2, Hz | $\beta_2 L$ = 4.69409113 | 16.158611 | 16.159146 |

The static results agree to round-off, as section 3 says they must. The frequencies are above
the closed form by 8.5e-7 and 3.3e-5 of their value.

What gates each claim on this page:

| Claim | Test |
|---|---|
| `local_stiffness` equals the strain-energy integral of the section 3 shape functions, entry by entry | `test_stiffness_is_the_strain_energy_integral_of_the_shape_functions` |
| `local_mass` equals the kinetic-energy integral of the same shape functions, with $I_1 + I_2$ in torsion and NSM in the translations | `test_mass_is_the_kinetic_energy_integral_of_the_same_shape_functions` |
| `I1` acts in plane 1 and `I2` in plane 2, with the rotation signs of section 2 | `test_plane_1_takes_i1_and_plane_2_takes_i2` |
| The local axes follow the orientation vector; $[T]$ is orthogonal | `test_local_axes_follow_the_orientation_vector` |
| The section 6 table | `test_convergence_table_is_what_the_solver_gives` |
| The frequency converges from above at fourth order | `test_frequency_converges_from_above_at_fourth_order` |
| One element gives the exact tip deflection | `test_one_element_gives_the_exact_tip_deflection` |
| The table above | `test_sample_deck_table_is_what_the_solver_gives` |
| The two shipped decks meet their closed forms (and the simply supported and free-free decks theirs) | [`tests/integration/test_sample_verification.py`](../../tests/integration/test_sample_verification.py) |

The first eight are in [`tests/docs/test_beam_methods.py`](../../tests/docs/test_beam_methods.py).
The element-matrix tests integrate the shape functions numerically and use a section with
`I1`, `I2` and `J` all different, so a swapped inertia cannot pass. The tables are read from
this page by the tests: a number changed here, or a change in the solver, fails the suite.

## 8. Where the rest is described

| Topic | Page |
|---|---|
| Global assembly, constraints, the static solve, reactions | [SOL 101 guide](../10_standard/03_static_analysis.md) |
| CBAR forces and stresses, with their signs | [SOL 101 guide](../10_standard/03_static_analysis.md), CBAR End Forces and Moments; CBAR Stress at Recovery Points |
| Pin releases; the rod element | [SOL 101 guide](../10_standard/03_static_analysis.md) |
| CONM2 mass, the eigensolver, normalisation, modal effective mass | [SOL 103 guide](../10_standard/04_modal_analysis.md) |
| RBE2, RBE3 and RBAR | [SOL 101 guide](../10_standard/03_static_analysis.md), RBE3 Constraint Assembly |
| PBAR and CBAR fields | [Card reference](../10_standard/02_card_reference.md) |
| The full verification-case tables | [Program overview](../10_standard/00_program_overview.md) |
