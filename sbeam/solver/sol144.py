"""SOL 144 static aeroelastic solver — Step 50.

Assembles the flexible aerodynamic stiffness Q_aa on the structural a-set and
solves (K_aa - q*Q_aa)*u_a = q*f_g for a given dynamic pressure, without trim
variables (Step 52 adds those).

Matrix chain (theory docs/20_theory/01_aeroelastics_theory.md Eq. 2, 22a):
    Q_aa  = G_disp^T  S_kj  (A_jj*)^-1  D_jk  G_slope       (n_g, n_g)
    f_g   = G_disp^T  S_kj  (A_jj*)^-1  w_g                  (n_g,)
    Q_hh  = Phi^T  Q_aa  Phi                                  (n_m, n_m)

Governing equation (a-set, Step 50 — no trim variables):
    (K_aa - q * Q_aa) * u_a  =  q * f_g  +  f_struct

Public API:
    run_aeroelastic_static(bulk, subcase, aero, q, use_rom, sol103_result)
"""

from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.aero.aero_model import AeroModel
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.results.results import BarForce, BarStress, Sol144Result
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses
from sbeam.solver.sol103 import run_sol103


def _build_qaa_aset(
    bulk: BulkData,
    aero: AeroModel,
    grid_index: dict,
    spc_sid,
    f_g_full: Optional[np.ndarray] = None,
) -> tuple:
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
            "_build_qaa_aset: aero.g_slope and aero.g_disp must be populated. "
            "Call build_aero_model with a grid_index argument."
        )

    n_g = 6 * len(grid_index)

    # --- g-set matrices ---
    Q_gg = build_qaa(aero, aero.g_disp, aero.g_slope)     # (n_g, n_g) dense
    K_gg = assemble_global_stiffness(bulk)                  # (n_g, n_g) sparse CSR

    # --- RBE3 / RBAR transform (same as sol101) ---
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        # T.T @ K_sparse @ T → dense ndarray (NumPy @ semantics, same as sol101 precedent)
        K_red = (T.T @ K_gg @ T)
        if hasattr(K_red, "toarray"):
            K_red = K_red.toarray()
        Q_red = T.T @ Q_gg @ T
        f_red = T.T @ f_g_full if f_g_full is not None else None
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = [red_map[d] for d in spc_dofs_full if d not in dep_set]
    else:
        K_red = K_gg.toarray()      # convert sparse → dense once; Q_aa is dense so system is dense
        Q_red = Q_gg
        f_red = f_g_full.copy() if f_g_full is not None else None
        red_dofs = list(range(n_g))
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = spc_dofs_full

    # --- SPC partition to a-set ---
    constrained = set(spc_dofs_local)
    free_local = [i for i in range(len(red_dofs)) if i not in constrained]

    K_aa = K_red[np.ix_(free_local, free_local)]    # (n_a, n_a)
    Q_aa = Q_red[np.ix_(free_local, free_local)]    # (n_a, n_a)
    f_aa = f_red[free_local] if f_red is not None else None

    # Map local a-set indices → g-set DOF indices for displacement scatter
    free_dofs = [red_dofs[i] for i in free_local]

    return Q_aa, K_aa, f_aa, free_dofs


def _solve_direct(
    K_aa: np.ndarray,
    Q_aa: np.ndarray,
    f_aa: np.ndarray,
    q: float,
    free_dofs: list,
    n_dofs: int,
) -> tuple:
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

    try:
        cond = np.linalg.cond(K_eff)
    except Exception:
        cond = np.inf
    if cond > 1e15:
        raise ValueError(
            "Singular effective aeroelastic stiffness (K_aa - q*Q_aa): "
            "model may be at or beyond divergence dynamic pressure."
        )

    u_free = scipy.linalg.solve(K_eff, f_aa)

    displacements = np.zeros(n_dofs)
    for local_idx, g_dof in enumerate(free_dofs):
        displacements[g_dof] = u_free[local_idx]

    return displacements, K_eff, k_aa_lu


def _solve_rom(
    K_aa: np.ndarray,
    Q_aa: np.ndarray,
    f_aa: np.ndarray,
    q: float,
    phi_free: np.ndarray,
) -> tuple:
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


def _mode_acceleration_recovery(
    K_aa: np.ndarray,
    Q_aa: np.ndarray,
    f_aa: np.ndarray,
    q: float,
    phi_free: np.ndarray,
    xi: np.ndarray,
    k_aa_lu: tuple,
) -> np.ndarray:
    """Mode-acceleration corrected a-set displacement.

    Corrects the mode-displacement estimate u_md = Phi*xi by the static
    flexibility of the residual force:

        u_a = Phi*xi + K_aa^{-1} * (f_aa - (K_aa - q*Q_aa)*Phi*xi)

    The K_aa factorization is already available from _solve_direct so no
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
    sol103_result: Optional[object] = None,
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
    f_aero_g = q * build_fg(aero, aero.g_disp)    # (n_g,) from coupling.py
    f_g_full = f_struct + f_aero_g

    # Reduce Q_aa, K_aa, and the combined load to the a-set
    Q_aa, K_aa, f_aa, free_dofs = _build_qaa_aset(bulk, aero, grid_index, spc_sid, f_g_full)

    # Direct solve
    displacements, _K_eff, k_aa_lu = _solve_direct(K_aa, Q_aa, f_aa, q, free_dofs, n_dofs)

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

        xi, k_hh, q_hh = _solve_rom(K_aa, Q_aa, f_aa, q, phi_free)
        u_free_corrected = _mode_acceleration_recovery(K_aa, Q_aa, f_aa, q, phi_free, xi, k_aa_lu)

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
