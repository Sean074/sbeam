"""SOL 144 static aeroelastic solver — Steps 50 and 52.

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
from sbeam.aero.integration import build_djx
from sbeam.results.results import BarForce, BarStress, Sol144Result, Sol144TrimResult
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


# ---------------------------------------------------------------------------
# Step 52 — SOL 144 Trim Solver
# ---------------------------------------------------------------------------

def _compute_aset_data(bulk: BulkData, grid_index: dict, spc_sid) -> tuple:
    """Compute a-set partition data (T, dep_dofs, red_dofs, free_local, free_dofs).

    Identical reduction logic to _build_qaa_aset; factored out so run_sol144_trim
    can reuse the partition for Q_ax and the inertial load vector without
    duplicating the RBE3+SPC reduction.
    """
    n_g = 6 * len(grid_index)
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = [red_map[d] for d in spc_dofs_full if d not in dep_set]
    else:
        red_dofs = list(range(n_g))
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = spc_dofs_full

    constrained = set(spc_dofs_local)
    free_local = [i for i in range(len(red_dofs)) if i not in constrained]
    free_dofs = [red_dofs[i] for i in free_local]
    return T, dep_dofs, red_dofs, free_local, free_dofs


def _build_urdd_load(bulk: BulkData, urdd_values: dict, grid_index: dict) -> np.ndarray:
    """Inertial load vector f_inertial on the full g-set.

    Convention: f_inertial[Ti_dof] = -m * URDD_i  (physical acceleration).
    For URDD3 = -32.174 ft/s² (1g upward), f[Tz] = +m*g (upward load).

    Only CONM2 point masses and CBAR distributed mass (if rho > 0) contribute.
    """
    n_g = 6 * len(grid_index)
    f = np.zeros(n_g)

    urdd_to_dof = {'URDD1': 0, 'URDD2': 1, 'URDD3': 2,
                   'URDD4': 3, 'URDD5': 4, 'URDD6': 5}

    for label, accel in urdd_values.items():
        if accel == 0.0:
            continue
        ul = label.upper()
        if ul not in urdd_to_dof:
            continue
        dof_off = urdd_to_dof[ul]

        if dof_off < 3:  # translational
            for conm2 in bulk.conm2s.values():
                if conm2.gid not in grid_index:
                    continue
                base = grid_index[conm2.gid] * 6
                f[base + dof_off] -= conm2.m * accel

            for cbar in bulk.cbars.values():
                pbar = bulk.pbars.get(cbar.pid)
                mat = bulk.mat1s.get(pbar.mid) if pbar else None
                if mat is None or mat.rho == 0.0:
                    continue
                ga = bulk.grids[cbar.ga]
                gb = bulk.grids[cbar.gb]
                dx, dy, dz = gb.x - ga.x, gb.y - ga.y, gb.z - ga.z
                L = (dx**2 + dy**2 + dz**2) ** 0.5
                m_half = 0.5 * mat.rho * pbar.A * L
                f[grid_index[cbar.ga] * 6 + dof_off] -= m_half * accel
                f[grid_index[cbar.gb] * 6 + dof_off] -= m_half * accel
        else:
            # Rotational URDD — CONM2 inertia contribution only
            rot = dof_off - 3
            for conm2 in bulk.conm2s.values():
                if conm2.gid not in grid_index:
                    continue
                I_val = (conm2.i11, conm2.i22, conm2.i33)[rot]
                if I_val == 0.0:
                    continue
                base = grid_index[conm2.gid] * 6
                f[base + dof_off] -= I_val * accel

    return f


def _get_suport_local(bulk: BulkData, free_dofs: list, grid_index: dict) -> list:
    """Return local a-set indices corresponding to SUPORT DOFs.

    Uses bulk.supports (list[Suport]).  DOF string "35" means Tz (3) and Ry (5).
    """
    g_to_local = {g_dof: loc for loc, g_dof in enumerate(free_dofs)}
    suport_local = []
    for sup in bulk.supports:
        if sup.gid not in grid_index:
            continue
        base = grid_index[sup.gid] * 6
        for ch in sup.dofs:
            g_dof = base + (int(ch) - 1)
            if g_dof in g_to_local:
                suport_local.append(g_to_local[g_dof])
    return suport_local


def _solve_trim_determined(
    K_aa: np.ndarray,
    Q_ax_a: np.ndarray,
    f_rhs_a: np.ndarray,
    q: float,
    suport_local: list,
    free_label_cols: list,
) -> tuple:
    """Schur-complement trim solve for the determined case (n_free == n_suport).

    Partitions the a-set into l-set (non-SUPORT) and r-set (SUPORT).
    With u_r = 0, the r-set equilibrium provides the trim equations:

        K_rl @ u_l = q * Q_ax_r @ delta_free + f_rhs_r
        K_ll @ u_l = q * Q_ax_l @ delta_free + f_rhs_l

    Substituting the l-set solution:
        Schur rhs  = K_rl @ K_ll^{-1} @ f_rhs_l - f_rhs_r
        Schur lhs  = q*(K_rl @ K_ll^{-1} @ Q_ax_l - Q_ax_r)[:,free_label_cols]
        Schur lhs @ delta_free = -Schur rhs

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    n_a = K_aa.shape[0]
    r_idx = list(suport_local)
    l_idx = [i for i in range(n_a) if i not in set(r_idx)]

    K_ll = K_aa[np.ix_(l_idx, l_idx)]
    K_rl = K_aa[np.ix_(r_idx, l_idx)]

    Q_ax_l = Q_ax_a[np.ix_(l_idx, free_label_cols)]  # (n_l, n_free)
    Q_ax_r = Q_ax_a[np.ix_(r_idx, free_label_cols)]  # (n_r, n_free)

    f_rhs_l = f_rhs_a[l_idx]
    f_rhs_r = f_rhs_a[r_idx]

    K_ll_lu = scipy.linalg.lu_factor(K_ll)

    # K_ll^{-1} @ f_rhs_l and K_ll^{-1} @ Q_ax_l
    Kinv_f = scipy.linalg.lu_solve(K_ll_lu, f_rhs_l)            # (n_l,)
    Kinv_Q = scipy.linalg.lu_solve(K_ll_lu, Q_ax_l)             # (n_l, n_free)

    # Trim equation: schur_A @ delta_free = schur_b
    schur_A = q * (K_rl @ Kinv_Q - Q_ax_r)                      # (n_r, n_free)
    schur_b = f_rhs_r - K_rl @ Kinv_f                           # (n_r,)

    delta_free_arr = scipy.linalg.solve(schur_A, schur_b)        # (n_free,)

    # Recover l-set displacements
    u_l = scipy.linalg.lu_solve(K_ll_lu, q * Q_ax_l @ delta_free_arr + f_rhs_l)

    # Assemble a-set displacement (u_r = 0)
    u_a = np.zeros(n_a)
    for li, val in zip(l_idx, u_l):
        u_a[li] = val

    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


def _compute_aero_forces(
    u_a_full: np.ndarray,
    delta_all: np.ndarray,
    all_labels: list,
    aero: AeroModel,
    D_jx: np.ndarray,
    bulk,
    x_ref: float,
) -> tuple:
    """Compute total Fz and My at given trim state.

    Returns (Fz, My) where My is the aerodynamic pitching moment about x_ref
    in the basic CID 0 frame.
    """
    from sbeam.aero.integration import build_djk

    djk = build_djk(aero.boxes)
    w_struct = djk @ (aero.g_slope @ u_a_full)     # structural normalwash
    w_trim   = D_jx @ delta_all                    # trim-variable normalwash
    w_total  = w_struct + w_trim + aero.wg         # total normalwash

    gamma = aero.ajj_inv_corr @ w_total            # (n_box,)

    skj = aero.skj                                 # (3*n_box, n_box)
    f_box_vec = skj @ gamma                        # (3*n_box,) forces per box

    Fz = f_box_vec[2::3].sum()                     # sum of z-components
    My = 0.0
    for j, box in enumerate(aero.boxes):
        x_ctrl = box.colloc[0]
        My += f_box_vec[3 * j + 2] * (x_ctrl - x_ref)

    return Fz, My


def _compute_rigid_derivs(
    aero: AeroModel,
    D_jx: np.ndarray,
    all_labels: list,
    bulk,
    x_ref: float,
) -> dict:
    """Rigid aerodynamic stability and control derivatives.

    For each label, computes the change in total Fz and My per unit label
    value without any structural deformation (u_a = 0).

    CZ = Fz / (q * sref),  dCZ/d(label) = dFz/(q * sref * d_label)
    At unit q:  dCZ/d(label) = Fz_sensitivity / sref
    """
    sref = bulk.aeros.sref
    cref = bulk.aeros.cref

    n_box = len(aero.boxes)
    rigid_derivs: dict = {}

    for col, label in enumerate(all_labels):
        # Normalwash from unit perturbation of this label alone
        w_pert = D_jx[:, col]
        gamma = aero.ajj_inv_corr @ w_pert          # (n_box,)
        f_box_vec = aero.skj @ gamma                 # (3*n_box,)

        Fz_sens = f_box_vec[2::3].sum()
        My_sens = sum(
            f_box_vec[3 * j + 2] * (aero.boxes[j].colloc[0] - x_ref)
            for j in range(n_box)
        )
        Fz_x = f_box_vec[0::3].sum()
        Fz_y = f_box_vec[1::3].sum()

        rigid_derivs[label] = {
            'CZ':  Fz_sens / sref,
            'CMY': My_sens / (sref * cref),
            'CX':  Fz_x / sref,
            'CY':  Fz_y / sref,
        }

    return rigid_derivs


def _compute_restrained_derivs(
    K_ll_lu: tuple,
    l_idx: list,
    Q_ax_a: np.ndarray,
    all_labels: list,
    u_a_trim: np.ndarray,
    delta_all_trim: np.ndarray,
    aero: AeroModel,
    D_jx: np.ndarray,
    free_dofs: list,
    bulk,
    x_ref: float,
    q: float,
    n_dofs: int,
    delta_perturbation: float = 1e-4,
) -> dict:
    """Elastic restrained stability derivatives via finite difference.

    For each label, perturbs by delta_perturbation, holds SUPORT DOFs at zero,
    re-solves the l-set, and computes ΔFz and ΔMy.
    """
    from sbeam.aero.integration import build_djk

    sref = bulk.aeros.sref
    cref = bulk.aeros.cref
    djk  = build_djk(aero.boxes)
    n_a  = Q_ax_a.shape[0]
    Q_ax_l = Q_ax_a[np.ix_(l_idx, list(range(len(all_labels))))]

    # Nominal structural load on l-set used in l-set equation (without trim aero):
    # u_l = K_ll^{-1} @ (q*Q_ax_l @ delta_full + f_rhs_l_base)
    # Here we use the trim-point displacements as baseline.

    # Scatter trim displacement to full g-set
    u_full_trim = np.zeros(n_dofs)
    for loc_i, g_dof in enumerate(free_dofs):
        u_full_trim[g_dof] = u_a_trim[loc_i]

    # Compute nominal Fz, My at trim point
    Fz0, My0 = _compute_aero_forces(
        u_full_trim,
        delta_all_trim, all_labels, aero, D_jx, bulk, x_ref,
    )

    rest_derivs: dict = {}
    DELTA = delta_perturbation

    for col, label in enumerate(all_labels):
        # Perturb the normalwash RHS by adding unit delta in this column
        dw = q * Q_ax_l[:, col] * DELTA            # (n_l,)
        u_l_pert_delta = scipy.linalg.lu_solve(K_ll_lu, dw)   # (n_l,)

        # Build perturbed a-set displacement
        u_a_pert = u_a_trim.copy()
        for li_idx, li in enumerate(l_idx):
            u_a_pert[li] += u_l_pert_delta[li_idx]

        u_full_pert = np.zeros(n_dofs)
        for loc_i, g_dof in enumerate(free_dofs):
            u_full_pert[g_dof] = u_a_pert[loc_i]

        # Perturbed trim variables
        delta_all_pert = delta_all_trim.copy()
        delta_all_pert[col] += DELTA

        Fz_p, My_p = _compute_aero_forces(
            u_full_pert,
            delta_all_pert, all_labels, aero, D_jx, bulk, x_ref,
        )

        rest_derivs[label] = {
            'CZ':  (Fz_p - Fz0) / (q * sref * DELTA),
            'CMY': (My_p - My0) / (q * sref * cref * DELTA),
        }

    return rest_derivs


def run_sol144_trim(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
) -> Sol144TrimResult:
    """SOL 144 static aeroelastic trim solve (Step 52).

    Solves the coupled structural/aerodynamic trim problem using the Schur
    complement method.  Only the determined case (n_free == n_suport) is
    supported; an over-determined case raises NotImplementedError.

    Args:
        bulk:     Parsed BulkData — must include SUPORT and TRIM cards.
        subcase:  SubcaseControl — uses spc_sid and trim_sid.
        aero:     AeroModel with g_slope, g_disp, ajj_inv_corr, skj, wg populated.

    Returns:
        Sol144TrimResult with trim variables, displacements, stability derivatives.

    Raises:
        ValueError  if no SUPORT card, TRIM card, or trim is over-determined
                    without TRIMOBJ/TRIMCON.
        NotImplementedError for over-determined trim.
    """
    if not bulk.supports:
        raise ValueError("run_sol144_trim: no SUPORT card found in model")

    trim_sid = subcase.trim_sid
    if trim_sid is None or trim_sid not in bulk.trims:
        raise ValueError(f"run_sol144_trim: TRIM SID {trim_sid} not found")

    trim_card = bulk.trims[trim_sid]
    q_dyn  = trim_card.q
    mach   = trim_card.mach

    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)
    spc_sid = subcase.spc_sid

    # ------------------------------------------------------------------ #
    # All labels (AESTAT + AESURF), sorted consistently
    # ------------------------------------------------------------------ #
    all_labels = sorted(
        [a.label for a in bulk.aestats.values()]
        + [s.label for s in bulk.aesurfs.values()]
    )

    # Separate free (to solve for) vs prescribed (given in TRIM card)
    prescribed_dict = {k.upper(): v for k, v in trim_card.vars.items()}
    free_labels   = [l for l in all_labels if l not in prescribed_dict]
    pres_labels   = [l for l in all_labels if l in prescribed_dict]

    # ------------------------------------------------------------------ #
    # Reference geometry
    # ------------------------------------------------------------------ #
    aeros = bulk.aeros
    if aeros.rcsid:
        from sbeam.assembly.coord_transform import _get_transform
        x_ref_pt, _ = _get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref = float(x_ref_pt[0])
    else:
        x_ref = 0.0

    # ------------------------------------------------------------------ #
    # Build D_jx and Q_ax on the g-set
    # ------------------------------------------------------------------ #
    D_jx = build_djx(aero.boxes, all_labels, bulk)       # (n_box, n_labels)
    Q_ax_g = aero.g_disp.T @ aero.skj @ aero.ajj_inv_corr @ D_jx  # (n_g, n_labels)

    # ------------------------------------------------------------------ #
    # A-set partition (SPC + RBE3 reduction)
    # ------------------------------------------------------------------ #
    T, dep_dofs, red_dofs, free_local, free_dofs = _compute_aset_data(
        bulk, grid_index, spc_sid
    )

    # Reduce Q_ax and structural stiffness to a-set
    if dep_dofs:
        Q_ax_red = T.T @ Q_ax_g
    else:
        Q_ax_red = Q_ax_g
    Q_ax_a = Q_ax_red[np.ix_(free_local, list(range(len(all_labels))))]  # (n_a, n_labels)

    K_gg = assemble_global_stiffness(bulk)
    if dep_dofs:
        K_red = T.T @ K_gg @ T
        if hasattr(K_red, "toarray"):
            K_red = K_red.toarray()
    else:
        K_red = K_gg.toarray()
    K_aa = K_red[np.ix_(free_local, free_local)]   # (n_a, n_a)

    # Also compute Q_aa for storage in result (reuse existing helper)
    from sbeam.aero.coupling import build_qaa
    Q_gg = build_qaa(aero, aero.g_disp, aero.g_slope)
    if dep_dofs:
        Q_red_full = T.T @ Q_gg @ T
    else:
        Q_red_full = Q_gg
    Q_aa = Q_red_full[np.ix_(free_local, free_local)]

    # ------------------------------------------------------------------ #
    # Build combined RHS: q*f_g (baseline aero) + inertial load
    # ------------------------------------------------------------------ #
    from sbeam.aero.coupling import build_fg
    f_aero_g = q_dyn * build_fg(aero, aero.g_disp)   # (n_g,) baseline aero

    # Contribution of prescribed trim variables to normalwash
    pres_values = np.array([prescribed_dict.get(l, 0.0) for l in all_labels])
    pres_aero_g = q_dyn * Q_ax_g @ pres_values       # (n_g,)

    # Inertial load from prescribed URDD accelerations
    urdd_dict = {l: prescribed_dict[l] for l in pres_labels if l.upper().startswith('URDD')}
    # Also include URDD values from free labels (they could be free trim variables)
    for l in free_labels:
        if l.upper().startswith('URDD'):
            urdd_dict[l] = 0.0  # initially zero; will be updated at trim
    f_inertial_g = _build_urdd_load(bulk, urdd_dict, grid_index)  # (n_g,)

    f_rhs_g = f_aero_g + pres_aero_g + f_inertial_g  # (n_g,)

    # Reduce f_rhs to a-set
    if dep_dofs:
        f_rhs_red = T.T @ f_rhs_g
    else:
        f_rhs_red = f_rhs_g.copy()
    f_rhs_a = f_rhs_red[free_local]   # (n_a,)

    # ------------------------------------------------------------------ #
    # SUPORT DOF indices in a-set
    # ------------------------------------------------------------------ #
    suport_local = _get_suport_local(bulk, free_dofs, grid_index)
    n_suport = len(suport_local)
    n_free   = len(free_labels)

    if n_free > n_suport:
        raise NotImplementedError(
            f"Over-determined trim (n_free={n_free} > n_suport={n_suport}) "
            "not yet implemented — add TRIMOBJ/TRIMCON or prescribe more variables."
        )
    if n_free < n_suport:
        raise ValueError(
            f"Under-determined trim (n_free={n_free} < n_suport={n_suport}): "
            "more SUPORT DOFs than free variables."
        )
    if n_free == 0:
        raise ValueError("run_sol144_trim: no free trim variables — all labels prescribed.")

    # ------------------------------------------------------------------ #
    # Map free labels to column indices in Q_ax_a
    # ------------------------------------------------------------------ #
    label_to_col = {l: i for i, l in enumerate(all_labels)}
    free_label_cols = [label_to_col[l] for l in free_labels]

    # ------------------------------------------------------------------ #
    # Schur-complement trim solve
    # ------------------------------------------------------------------ #
    u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = _solve_trim_determined(
        K_aa, Q_ax_a, f_rhs_a, q_dyn, suport_local, free_label_cols
    )

    # ------------------------------------------------------------------ #
    # Assemble full trim variable dict
    # ------------------------------------------------------------------ #
    trim_vars: dict = dict(prescribed_dict)
    for i, lbl in enumerate(free_labels):
        trim_vars[lbl] = float(delta_free_arr[i])

    # Full delta_all vector (ordered by all_labels)
    delta_all = np.array([trim_vars.get(l, 0.0) for l in all_labels])

    # ------------------------------------------------------------------ #
    # Scatter a-set displacement to full g-set
    # ------------------------------------------------------------------ #
    displacements = np.zeros(n_dofs)
    for loc_i, g_dof in enumerate(free_dofs):
        displacements[g_dof] = u_a[loc_i]

    # ------------------------------------------------------------------ #
    # CBAR force / stress recovery
    # ------------------------------------------------------------------ #
    bar_forces   = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid]   = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index)

    # ------------------------------------------------------------------ #
    # Rigid derivatives (no structural deformation)
    # ------------------------------------------------------------------ #
    rigid_derivs = _compute_rigid_derivs(aero, D_jx, all_labels, bulk, x_ref)

    # ------------------------------------------------------------------ #
    # Elastic restrained derivatives (finite difference, u_r = 0)
    # ------------------------------------------------------------------ #
    rest_derivs = _compute_restrained_derivs(
        K_ll_lu, l_idx, Q_ax_a, all_labels,
        u_a, delta_all, aero, D_jx,
        free_dofs, bulk, x_ref, q_dyn, n_dofs,
    )

    # ------------------------------------------------------------------ #
    # Total CL and CM at trim
    # ------------------------------------------------------------------ #
    from sbeam.aero.integration import build_djk
    djk = build_djk(aero.boxes)
    w_struct = djk @ (aero.g_slope @ displacements)
    w_total  = w_struct + D_jx @ delta_all + aero.wg
    gamma    = aero.ajj_inv_corr @ w_total
    f_box_vec = aero.skj @ gamma
    Fz_total = float(f_box_vec[2::3].sum())
    My_total = float(sum(
        f_box_vec[3 * j + 2] * (aero.boxes[j].colloc[0] - x_ref)
        for j in range(len(aero.boxes))
    ))
    sref = aeros.sref
    cref = aeros.cref
    total_cl = Fz_total / (q_dyn * sref) if q_dyn > 0 else 0.0
    total_cm = My_total / (q_dyn * sref * cref) if q_dyn > 0 else 0.0

    k_aa_lu_trim = scipy.linalg.lu_factor(K_aa)

    return Sol144TrimResult(
        subcase_id=subcase.subcase_id,
        trim_sid=trim_sid,
        q=q_dyn,
        mach=mach,
        trim_vars=trim_vars,
        displacements=displacements,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        q_aa=Q_aa,
        free_dofs=free_dofs,
        k_aa_lu=k_aa_lu_trim,
        rigid_derivs=rigid_derivs,
        restrained_derivs=rest_derivs,
        box_gamma=gamma,
        total_cl=total_cl,
        total_cm=total_cm,
    )
