"""Structure-to-aero coupling: flexible aerodynamic stiffness Q_aa, baseline
aero load f_g, and the modal generalized aerodynamic force (GAF) matrix Q_hh.

This is the Phase C assembly layer that sits *downstream* of the corrected AIC.
It consumes an already-built ``AeroModel`` (raw AIC + correction + integration
matrices) together with the two beam-spline transfer operators and produces the
matrices the SOL 144 static-aeroelastic solve needs.

Matrix chain (steady, k = 0), theory ``docs/20_theory/01_aeroelastics_theory.md`` Eq. (2), (22a):

    Q_aa = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope                         (n_g, n_g)
    f_g  = G_disp^T  S_kj  (A_jj*)^-1  w_g                                   (n_g,)
    Q_hh = Phi^T  Q_aa  Phi                                                  (n_m, n_m)

The two spline operators are deliberately distinct (see the module sketch / theory
§6.1): ``G_slope`` (n_box × n_g) maps structural g-DOF to the per-box streamwise
*incidence* that drives the downwash through ``D_jk``; ``G_disp`` (3·n_box × n_g)
maps g-DOF to the per-box translation at the load point, and its transpose carries
the box force vectors (``S_kj`` output, [Fx, Fy, Fz] per box) back to the structure.
Collapsing them into a single operator is the classic spline bug — keep them separate
so the virtual-work pairing (theory §4.1) and rigid-body exactness (§4.5) both hold.

The corrected inverse ``A_jj*^-1`` is read directly from ``AeroModel.ajj_inv_corr``;
this layer never refactors or re-inverts the AIC. All correction (Wkk/WT1/WT2) is
already baked into that stored inverse upstream — there is no correction applied here.
"""

import numpy as np

from sbeam.aero.aero_model import AeroModel


def _check_spline_shapes(aero: AeroModel, g_disp: np.ndarray, g_slope: np.ndarray) -> int:
    """Validate spline-operator shapes against the AeroModel and return n_g."""
    n = len(aero.boxes)
    if g_slope.ndim != 2 or g_slope.shape[0] != n:
        raise ValueError(
            f"build_qaa: g_slope must have shape (n_box, n_g) = ({n}, n_g); "
            f"got {g_slope.shape}"
        )
    if g_disp.ndim != 2 or g_disp.shape[0] != 3 * n:
        raise ValueError(
            f"build_qaa: g_disp must have shape (3*n_box, n_g) = ({3 * n}, n_g); "
            f"got {g_disp.shape}"
        )
    if g_disp.shape[1] != g_slope.shape[1]:
        raise ValueError(
            f"build_qaa: g_disp and g_slope must share the structural DOF count n_g; "
            f"got {g_disp.shape[1]} vs {g_slope.shape[1]}"
        )
    return g_slope.shape[1]


def build_qaa(aero: AeroModel, g_disp: np.ndarray, g_slope: np.ndarray) -> np.ndarray:
    """Flexible aerodynamic stiffness Q_aa on the structural g-set.

    Q_aa = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope.

    The aerodynamic load produced by the structure's own deflection is
    ``f_aero = q * Q_aa @ u_g`` (theory Eq. 17). Q_aa is dense and, in general,
    unsymmetric. It is built on the g-set; reduction to the analysis a-set uses
    the existing SPC/RBE transforms in ``assembly/`` and is the caller's concern.

    Args:
        aero:    Assembled AeroModel (provides skj, ajj_inv_corr, djk).
        g_disp:  Displacement spline, shape (3*n_box, n_g): g-DOF → box translation.
        g_slope: Slope spline, shape (n_box, n_g): g-DOF → box streamwise incidence.

    Returns:
        Q_aa, shape (n_g, n_g).
    """
    _check_spline_shapes(aero, g_disp, g_slope)
    return np.linalg.multi_dot(
        [g_disp.T, aero.skj, aero.ajj_inv_corr, aero.djk, g_slope]
    )


def build_fg(aero: AeroModel, g_disp: np.ndarray) -> np.ndarray:
    """Baseline aerodynamic load f_g on the structural g-set.

    f_g = G_disp^T  S_kj  (A_jj*)^-1  w_g.

    This is the structural load from the camber/twist/incidence (and additive
    CFD/WT) baseline normalwash ``w_g`` at zero elastic deflection (theory Eq. 2,
    §2.5). The trim/static solve forcing is ``q * f_g`` (theory Eq. 1).

    Args:
        aero:   Assembled AeroModel (provides skj, ajj_inv_corr, wg).
        g_disp: Displacement spline, shape (3*n_box, n_g): g-DOF → box translation.

    Returns:
        f_g, shape (n_g,).
    """
    n = len(aero.boxes)
    if g_disp.ndim != 2 or g_disp.shape[0] != 3 * n:
        raise ValueError(
            f"build_fg: g_disp must have shape (3*n_box, n_g) = ({3 * n}, n_g); "
            f"got {g_disp.shape}"
        )
    cp = aero.ajj_inv_corr @ aero.wg          # (n,)   box lifting pressures from w_g
    p = aero.skj @ cp                          # (3n,)  box force vectors [Fx,Fy,Fz]...
    return g_disp.T @ p                        # (n_g,) structural grid loads


def build_gaf(qaa: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Modal generalized aerodynamic force (GAF) matrix Q_hh = Phi^T Q_aa Phi.

    The steady (k = 0) generalized aerodynamic force matrix, the aerodynamics
    expressed on the modal basis (theory Eq. 22a). Size is (n_modes, n_modes),
    independent of the aero mesh. This is the object the flutter phase reuses:
    when the real A_jj becomes the complex Doublet-Lattice A_jj(M, k) the same
    expression returns Q_hh(M, k) with no change to the spline or modal matrices.

    The CFD/WT correction is inherited from the corrected AIC already baked into
    ``qaa``; no correction is applied at the modal level.

    Args:
        qaa: Flexible aerodynamic stiffness on the a-set (or g-set), shape (n, n).
             ``phi`` must be expressed on the same set as ``qaa``.
        phi: Retained free-vibration mode matrix, shape (n, n_modes).

    Returns:
        Q_hh, shape (n_modes, n_modes).
    """
    if qaa.ndim != 2 or qaa.shape[0] != qaa.shape[1]:
        raise ValueError(f"build_gaf: qaa must be square (n, n); got {qaa.shape}")
    if phi.ndim != 2 or phi.shape[0] != qaa.shape[0]:
        raise ValueError(
            f"build_gaf: phi must have shape (n, n_modes) with n = qaa rows "
            f"({qaa.shape[0]}); got {phi.shape}"
        )
    return np.linalg.multi_dot([phi.T, qaa, phi])
