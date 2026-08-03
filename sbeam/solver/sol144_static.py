"""Step-50 static aeroelastic solve — reference implementation / test scaffolding.

Solves the flexible static aeroelastic problem at a given dynamic pressure
WITHOUT trim variables (the Step 52 trim solver in ``sol144.py`` is the
production path).  This module has **no production callers** — ``main.py`` and
the viewer dispatch SOL 144 subcases to ``run_sol144_trim`` /
``run_sol144_diverg`` / the maneuver solvers only.  It is retained as the
reference implementation of the direct and modal-ROM aeroelastic solves
(DEF-R3 disposition, P13) and is pinned by ``tests/aero/test_step50_qaa.py``,
``tests/aero/test_attach_sol144.py`` and ``tests/solver/test_modal_basis.py``
(all importing via the ``sol144`` facade).

Governing equation (a-set, Step 50 — no trim variables):
    (K_aa - q * Q_aa) * u_a  =  q * f_g  +  f_struct

Matrix chain (theory docs/20_theory/01_aeroelastics_theory.md Eq. 2, 22a):
    Q_aa  = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope       (n_g, n_g)
    f_g   = G_disp^T  S_kj  (A_jj*)^-1  w_g                  (n_g,)
    Q_hh  = Phi^T  Q_aa  Phi                                  (n_m, n_m)

Public API:
    run_aeroelastic_static(bulk, subcase, aero, q, use_rom, sol103_result)
"""

from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.reduction import reduce_to_aset
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.results.results import Sol144Result, Sol103Result
from sbeam.linalg_utils import estimate_cond_1norm
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses
from sbeam.solver.sol103 import run_sol103
from sbeam.types import FloatArray, LuFactor


def build_qaa_aset(
    bulk: BulkData,
    aero: AeroModel,
    grid_index: dict[int, int],
    spc_sid: Optional[int],
    f_g_full: Optional[FloatArray] = None,
) -> tuple[FloatArray, FloatArray, Optional[FloatArray], list[int]]:
    """Reduce the g-set Q_aa and K_aa to the SPC-free a-set.

    Applies the same RBE3-then-SPC reduction as sol101.py so that the a-set
    indices are identical to those used in the static and modal solvers.

    Args:
        bulk:       Parsed BulkData.
        aero:       AeroModel with g_slope and g_disp populated.
        grid_index: {gid: i} mapping from build_grid_index.
        spc_sid:    SPC set ID (may be None — no SPCs applied when None).
        f_g_full:   Optional full g-set load vector (n_g,) to reduce alongside
                    K and Q.  When supplied the returned f_aa is on the a-set;
                    otherwise None is returned.

    Returns:
        (Q_aa, K_aa, f_aa, free_dofs) where:
          Q_aa      — dense (n_a, n_a) aero stiffness on the free a-set
          K_aa      — dense (n_a, n_a) structural stiffness on the free a-set
          f_aa      — (n_a,) load vector on the a-set, or None if not supplied
          free_dofs — list[int] of g-set DOF indices for the a-set rows/cols

    Raises:
        ValueError if aero.g_slope or aero.g_disp is None.
    """
    if aero.g_slope is None or aero.g_disp is None:
        raise ValueError(
            "build_qaa_aset: aero.g_slope and aero.g_disp must be populated. "
            "Call build_aero_model with a grid_index argument."
        )

    # --- g-set matrices ---
    Q_gg = build_qaa(aero, aero.require_g_load(), aero.require_g_slope())     # (n_g, n_g) dense
    K_gg = assemble_global_stiffness(bulk)                  # (n_g, n_g) sparse CSR

    # --- RBE3/RBAR-then-SPC reduction (shared path, Step 59) ---
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    K_aa = red.reduce_matrix(K_gg, dense=True)      # (n_a, n_a) dense system
    Q_aa = red.reduce_matrix(Q_gg)                  # (n_a, n_a)
    f_aa = red.reduce_vector(f_g_full) if f_g_full is not None else None

    return Q_aa, K_aa, f_aa, red.free_dofs


def solve_direct(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    free_dofs: list[int],
    n_dofs: int,
) -> tuple[FloatArray, FloatArray, LuFactor]:
    """Dense direct solve of (K_aa - q*Q_aa)*u_a = f_aa.

    Returns:
        (displacements, K_eff, k_aa_lu) where:
          displacements — full g-set vector (n_dofs,); SPC DOFs zero
          K_eff         — (n_a, n_a) effective stiffness K_aa - q*Q_aa
          k_aa_lu       — (lu, piv) from lu_factor(K_aa); reused by mode-
                          acceleration recovery and Step 52
    """
    K_eff = K_aa - q * Q_aa
    k_aa_lu = scipy.linalg.lu_factor(K_aa)

    # Factor K_eff once (DEF-R6): gecon 1-norm condition estimate replaces the
    # former full-SVD np.linalg.cond, and the same LU serves the solve below.
    try:
        cond, keff_lu = estimate_cond_1norm(K_eff)
    except Exception:
        cond, keff_lu = np.inf, None
    if keff_lu is None or cond > 1e15:
        raise ValueError(
            "Singular effective aeroelastic stiffness (K_aa - q*Q_aa): "
            "model may be at or beyond divergence dynamic pressure."
        )

    u_free = scipy.linalg.lu_solve(keff_lu, f_aa)

    displacements = np.zeros(n_dofs)
    for local_idx, g_dof in enumerate(free_dofs):
        displacements[g_dof] = u_free[local_idx]

    return displacements, K_eff, k_aa_lu


def solve_rom(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    phi_free: FloatArray,
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Modal-truncation ROM solve of the reduced system.

    Forms the (n_m, n_m) reduced system:
        (K_hh - q * Q_hh) * xi = Phi^T * f_aa
    where K_hh = Phi^T K_aa Phi  and  Q_hh = Phi^T Q_aa Phi (via build_gaf).

    Args:
        phi_free: (n_a, n_modes) mode matrix on the a-set.

    Returns:
        (xi, k_hh, q_hh):
          xi    — (n_modes,) modal amplitudes
          k_hh  — (n_modes, n_modes) modal structural stiffness
          q_hh  — (n_modes, n_modes) modal GAF
    """
    k_hh = phi_free.T @ K_aa @ phi_free         # (n_m, n_m)
    q_hh = build_gaf(Q_aa, phi_free)            # (n_m, n_m) — reuses coupling.py
    K_eff_hh = k_hh - q * q_hh
    f_hh = phi_free.T @ f_aa                    # (n_m,) modal RHS
    xi = scipy.linalg.solve(K_eff_hh, f_hh)
    return xi, k_hh, q_hh


def mode_acceleration_recovery(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    f_aa: FloatArray,
    q: float,
    phi_free: FloatArray,
    xi: FloatArray,
    k_aa_lu: LuFactor,
) -> FloatArray:
    """Mode-acceleration corrected a-set displacement.

    Corrects the mode-displacement estimate u_md = Phi*xi by the static
    flexibility of the residual force:

        u_a = Phi*xi + K_aa^{-1} * (f_aa - (K_aa - q*Q_aa)*Phi*xi)

    The K_aa factorization is already available from solve_direct so no
    additional factorization is required.  When all modes are retained the
    residual is zero and u_corrected == u_md exactly.

    Returns:
        u_free_corrected — (n_a,) corrected a-set displacement
    """
    u_md = phi_free @ xi                            # mode-displacement (n_a,)
    K_eff = K_aa - q * Q_aa
    residual = f_aa - K_eff @ u_md                 # static residual from truncation
    delta_u = scipy.linalg.lu_solve(k_aa_lu, residual)  # K_aa^{-1} * residual
    return u_md + delta_u


def run_aeroelastic_static(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    q: float,
    use_rom: bool = False,
    sol103_result: Optional[Sol103Result] = None,
) -> Sol144Result:
    """Solve the flexible static aeroelastic problem (Step 50 — no trim variables).

    Governing equation (a-set):
        (K_aa - q * Q_aa) * u_a  =  q * f_g  +  f_struct

    where:
      K_aa     — structural stiffness reduced to the SPC-free a-set
      Q_aa     — flexible aero stiffness assembled from coupling.build_qaa
      f_g      — baseline aero load from build_fg (camber/twist/incidence w_g)
      f_struct — structural load from the subcase LOAD set (may be zero)

    Args:
        bulk:           Parsed BulkData.
        subcase:        SubcaseControl — uses spc_sid, load_sid, method_sid.
        aero:           AeroModel with g_slope and g_disp populated (built with
                        grid_index argument to build_aero_model).
        q:              Dynamic pressure in consistent units.
        use_rom:        If True, also solve via modal-truncation ROM with
                        mode-acceleration recovery.  Requires either a
                        sol103_result or a method_sid in the subcase.
        sol103_result:  Pre-computed Sol103Result (optional).  When None and
                        use_rom=True the SOL 103 solve is run internally.

    Returns:
        Sol144Result with direct-solve displacements (and ROM outputs when
        use_rom=True).

    Raises:
        ValueError if aero.g_slope/g_disp are None, or use_rom=True but no
        EIGRL method is available.
    """
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)
    spc_sid = subcase.spc_sid
    load_sid = subcase.load_sid

    # Combine structural load and baseline aero load on the g-set
    f_struct = assemble_load_vector(bulk, load_sid) if load_sid is not None else np.zeros(n_dofs)
    f_aero_g = q * build_fg(aero, aero.require_g_load())    # (n_g,) from coupling.py
    f_g_full = f_struct + f_aero_g

    # Reduce Q_aa, K_aa, and the combined load to the a-set
    Q_aa, K_aa, f_aa, free_dofs = build_qaa_aset(bulk, aero, grid_index, spc_sid, f_g_full)
    if f_aa is None:   # f_g_full was supplied, so build_qaa_aset always reduces it
        raise ValueError("run_aeroelastic_static: a-set load vector was not built")

    # Direct solve
    displacements, _K_eff, k_aa_lu = solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_dofs)

    # --- Modal ROM path (optional) ---
    modal_coords = phi_free = k_hh = q_hh = None
    if use_rom:
        if sol103_result is None:
            if subcase.method_sid is None:
                raise ValueError(
                    "run_aeroelastic_static: use_rom=True requires either a "
                    "pre-computed sol103_result or a METHOD (EIGRL) set ID in the subcase."
                )
            sol103_result = run_sol103(bulk, subcase)

        # Extract a-set mode shapes (free_dofs rows of full-DOF mode matrix)
        phi_full = sol103_result.mode_shapes       # (n_dofs, n_modes)
        phi_free = phi_full[free_dofs, :]          # (n_a, n_modes)

        xi, k_hh, q_hh = solve_rom(K_aa, Q_aa, f_aa, q, phi_free)
        u_free_corrected = mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)

        modal_coords = xi
        # Scatter mode-acceleration corrected a-set back to full DOF vector
        displacements = np.zeros(n_dofs)
        for local_idx, g_dof in enumerate(free_dofs):
            displacements[g_dof] = u_free_corrected[local_idx]

    # CBAR force and stress recovery (reuses sol101 functions unchanged)
    bar_forces = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid] = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )

    return Sol144Result(
        displacements=displacements,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        q_aa=Q_aa,
        q=q,
        free_dofs=free_dofs,
        k_aa_lu=k_aa_lu,
        modal_coords=modal_coords,
        phi_free=phi_free,
        k_hh=k_hh,
        q_hh=q_hh,
    )
