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

import warnings
from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.aero.integration import build_djx
from sbeam.results.results import BarForce, BarStress, Sol144Result, Sol144TrimResult
from sbeam.solver.sol101 import recover_bar_forces, recover_bar_stresses
from sbeam.solver.sol103 import run_sol103


class AeroCache:
    """Mach-keyed cache of AeroModels for multi-Mach SOL 144 (AE9).

    The VLM AIC depends on Mach (Prandtl–Glauert / Göthert β scaling), so each
    TRIM subcase at a distinct Mach needs its own AeroModel.  Building the AIC is
    the expensive step, so models are memoized by Mach (rounded to 6 dp) and the
    build-once fixture pattern still holds across subcases at the same Mach.

    The cache is seeded with a prebuilt AeroModel so existing callers that pass a
    model built at ``AEROS.mach`` incur no rebuild when ``TRIM.mach`` matches.
    """

    _MACH_DP = 6

    def __init__(self, bulk: BulkData, grid_index: dict, seed: Optional[AeroModel] = None):
        self.bulk = bulk
        self.grid_index = grid_index
        self._cache: dict = {}
        if seed is not None:
            self._cache[round(float(seed.mach), self._MACH_DP)] = seed

    def get(self, mach: float) -> AeroModel:
        """Return the AeroModel for ``mach``, building and memoizing on a miss."""
        key = round(float(mach), self._MACH_DP)
        model = self._cache.get(key)
        if model is None:
            model = build_aero_model(self.bulk, grid_index=self.grid_index, mach=mach)
            self._cache[key] = model
        return model


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


def _build_inertial_cols(
    bulk: BulkData,
    all_labels: list,
    grid_index: dict,
    suport_pos: np.ndarray,
) -> np.ndarray:
    """Inertial sensitivity matrix M_ax on the full g-set — basic frame.

    Returns (n_g, n_labels) where column k is dF/dURDD_k (force per unit
    acceleration for URDD labels; zero for aerodynamic labels).  All values
    are expressed in the basic CID 0 frame; RCSID-frame URDD values must be
    transformed to basic before multiplying.

    Translational URDD (1-3): M[Tx/Ty/Tz dof, col] = -mass_i (CONM2 + CBAR).
    Rotational URDD (4-6): M[Ry dof, col] = -I_diag (CONM2 spin term)
        plus transport coupling: M[Tx/Ty/Tz dof, col] += -m_i * (α_hat × r_i)
        where r_i = grid_pos_i - suport_pos and α_hat is the unit rotation axis.

    Only CONM2 point masses and CBAR distributed mass (rho > 0) contribute.
    """
    n_g = 6 * len(grid_index)
    n_labels = len(all_labels)
    M = np.zeros((n_g, n_labels))

    _urdd_trans = {'URDD1': 0, 'URDD2': 1, 'URDD3': 2}
    _urdd_rot   = {'URDD4': 0, 'URDD5': 1, 'URDD6': 2}

    # Unit rotation axes in basic frame for URDD4/5/6
    _rot_axis = {0: np.array([1.0, 0.0, 0.0]),
                 1: np.array([0.0, 1.0, 0.0]),
                 2: np.array([0.0, 0.0, 1.0])}

    for col, label in enumerate(all_labels):
        ul = label.upper()

        if ul in _urdd_trans:
            ax = _urdd_trans[ul]
            for conm2 in bulk.conm2s.values():
                if conm2.gid not in grid_index:
                    continue
                M[grid_index[conm2.gid] * 6 + ax, col] -= conm2.m
            for cbar in bulk.cbars.values():
                pbar = bulk.pbars.get(cbar.pid)
                mat = bulk.mat1s.get(pbar.mid) if pbar else None
                if mat is None or mat.rho == 0.0:
                    continue
                ga = bulk.grids[cbar.ga]
                gb = bulk.grids[cbar.gb]
                L = ((gb.x - ga.x)**2 + (gb.y - ga.y)**2 + (gb.z - ga.z)**2) ** 0.5
                m_half = 0.5 * mat.rho * pbar.A * L
                M[grid_index[cbar.ga] * 6 + ax, col] -= m_half
                M[grid_index[cbar.gb] * 6 + ax, col] -= m_half

        elif ul in _urdd_rot:
            rot = _urdd_rot[ul]
            alpha_hat = _rot_axis[rot]
            for conm2 in bulk.conm2s.values():
                if conm2.gid not in grid_index:
                    continue
                gi = grid_index[conm2.gid]
                base = gi * 6
                # Spin inertia (diagonal only)
                I_val = (conm2.i11, conm2.i22, conm2.i33)[rot]
                M[base + 3 + rot, col] -= I_val
                # Transport term: F_trans = -m * (alpha_hat × r)
                g = bulk.grids[conm2.gid]
                r = np.array([g.x, g.y, g.z]) - suport_pos
                f_transport = -conm2.m * np.cross(alpha_hat, r)
                M[base:base + 3, col] += f_transport
            for cbar in bulk.cbars.values():
                pbar = bulk.pbars.get(cbar.pid)
                mat = bulk.mat1s.get(pbar.mid) if pbar else None
                if mat is None or mat.rho == 0.0:
                    continue
                ga = bulk.grids[cbar.ga]
                gb = bulk.grids[cbar.gb]
                L = ((gb.x - ga.x)**2 + (gb.y - ga.y)**2 + (gb.z - ga.z)**2) ** 0.5
                m_half = 0.5 * mat.rho * pbar.A * L
                for gobj, gi in ((ga, grid_index[cbar.ga]), (gb, grid_index[cbar.gb])):
                    r = np.array([gobj.x, gobj.y, gobj.z]) - suport_pos
                    f_transport = -m_half * np.cross(alpha_hat, r)
                    M[gi * 6: gi * 6 + 3, col] += f_transport

    return M


def _expand_to_g(
    u_a: np.ndarray,
    T: np.ndarray,
    free_local: list,
    n_red: int,
) -> np.ndarray:
    """Expand an a-set displacement vector to the full g-set via the RBE3/RBAR T matrix.

    The trim solver works on the a-set (post-SPC, post-RBAR). When the result is
    fed back into `aero.g_slope @ u` or `_compute_aero_forces`, the RBAR slave
    DOFs must move with their masters; a bare index scatter leaves the slaves at
    zero and corrupts the structural normalwash on every RBAR-attached grid.

    Args:
        u_a:        (n_a,) a-set displacement.
        T:          (n_g, n_red) RBE3/RBAR transformation from build_rbe3_transformation.
        free_local: list of a-set indices in the reduced set (length n_a).
        n_red:     number of reduced-set DOFs (T's column count).

    Returns:
        (n_g,) full g-set displacement with RBAR slaves driven by their masters.
    """
    u_red = np.zeros(n_red)
    for local_i, red_i in enumerate(free_local):
        u_red[red_i] = u_a[local_i]
    return T @ u_red


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
    Q_aa: np.ndarray,
    Q_ax_a: np.ndarray,
    M_ax_a: np.ndarray,
    f_rhs_a: np.ndarray,
    q: float,
    suport_local: list,
    free_label_cols: list,
) -> tuple:
    """Schur-complement trim solve for the determined case (n_free == n_suport).

    Partitions K_eff = K_aa - q*Q_aa into l-set (non-SUPORT) and r-set (SUPORT).
    With u_r = 0, the r-set equilibrium provides the trim equations.

    C_ax = q * Q_ax_a + M_ax_a   (combined aero + inertial sensitivity)

    Substituting the l-set solution:
        Schur rhs  = K_rl @ K_ll^{-1} @ f_rhs_l - f_rhs_r
        Schur lhs  = K_rl @ K_ll^{-1} @ C_ax_l - C_ax_r
        Schur lhs @ delta_free = -Schur rhs

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    n_a = K_aa.shape[0]
    r_idx = list(suport_local)
    l_idx = [i for i in range(n_a) if i not in set(r_idx)]

    K_eff = K_aa - q * Q_aa
    K_ll = K_eff[np.ix_(l_idx, l_idx)]
    K_rl = K_eff[np.ix_(r_idx, l_idx)]

    # Combined aero + inertial sensitivity for free columns only
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, free_label_cols)]
              + M_ax_a[np.ix_(l_idx, free_label_cols)])  # (n_l, n_free)
    C_ax_r = (q * Q_ax_a[np.ix_(r_idx, free_label_cols)]
              + M_ax_a[np.ix_(r_idx, free_label_cols)])  # (n_r, n_free)

    f_rhs_l = f_rhs_a[l_idx]
    f_rhs_r = f_rhs_a[r_idx]

    K_ll_lu = scipy.linalg.lu_factor(K_ll)

    Kinv_f = scipy.linalg.lu_solve(K_ll_lu, f_rhs_l)            # (n_l,)
    Kinv_C = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)             # (n_l, n_free)

    # Trim equation: schur_A @ delta_free = schur_b
    schur_A = K_rl @ Kinv_C - C_ax_r                            # (n_r, n_free)
    schur_b = f_rhs_r - K_rl @ Kinv_f                           # (n_r,)

    delta_free_arr = scipy.linalg.solve(schur_A, schur_b)        # (n_free,)

    # Recover l-set displacements
    u_l = scipy.linalg.lu_solve(K_ll_lu, C_ax_l @ delta_free_arr + f_rhs_l)

    # Assemble a-set displacement (u_r = 0)
    u_a = np.zeros(n_a)
    for li, val in zip(l_idx, u_l):
        u_a[li] = val

    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


def _pitch_moment(f_box_vec: np.ndarray, boxes: list, x_ref: float) -> float:
    """Nose-up-positive aerodynamic pitching moment about ``x_ref`` (AE1 Step E).

    Single source for the moment-arm convention `My = −ΣFz·(x_force − x_ref)`
    used throughout the trim chain.  The sign is nose-up positive, matching
    `solve_rigid_cl.CM` (`vlm.py`) and NASTRAN's Cm convention.  Each box load
    acts at its ¼-chord bound-vortex midpoint `box.force_point` (AE6), not the
    ¾-chord collocation point.

    Args:
        f_box_vec: (3·n_box,) per-box force vector [Fx0, Fy0, Fz0, Fx1, …] in
                   force/q units (skj @ Cp).
        boxes:     AeroBox list (provides force_point[0] moment arms).
        x_ref:     moment reference x-coordinate in basic CID 0 (RCSID origin).

    Returns:
        Pitching moment about x_ref (force/q · length units).  Full-span model,
        so this is already the whole-airplane moment (no symmetry factor).
    """
    return -sum(
        f_box_vec[3 * j + 2] * (boxes[j].force_point[0] - x_ref)
        for j in range(len(boxes))
    )


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

    Fz = f_box_vec[2::3].sum()
    My = _pitch_moment(f_box_vec, aero.boxes, x_ref)   # nose-up-positive

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
        My_sens = _pitch_moment(f_box_vec, aero.boxes, x_ref)   # nose-up-positive
        Fz_x = f_box_vec[0::3].sum()
        Fz_y = f_box_vec[1::3].sum()

        rigid_derivs[label] = {
            'CZ':  Fz_sens / sref,
            'CMY': My_sens / (sref * cref),
            'CX':  Fz_x / sref,
            'CY':  Fz_y / sref,
        }

    return rigid_derivs


def _compute_hinge_moments(
    aero: AeroModel,
    D_jx: np.ndarray,
    all_labels: list,
    bulk,
    f_box_trim: np.ndarray,
) -> dict:
    """Hinge-moment derivatives and trimmed hinge moment per AESURF control.

    The hinge moment is the moment of the aero box forces on a surface's AELIST
    boxes about its hinge axis ĥ (the cid1 y-axis) through the hinge origin o:

        HM = Σ_{j∈AELIST} [(r_j − o) × F_j] · ĥ          (r_j = box force point)

    Returns ``{label: {'total': HM_trim, <trim_label>: dHM/dδ, ...}}`` where each
    ``dHM/dδ`` uses the rigid box forces from that label's normalwash column
    alone (u_a = 0, force/q units), mirroring ``_compute_rigid_derivs``.  The
    ``'total'`` entry uses the full trimmed box-force field ``f_box_trim``
    (force/q units; multiply by q for the physical hinge moment).
    """
    from sbeam.assembly.coord_transform import _get_transform

    # NASTRAN-box-ID → global-k index (same convention as build_djx)
    id_to_k: dict = {}
    for box in aero.boxes:
        caero = bulk.caero1s[box.caero_eid]
        nch = (caero.nchord if caero.nchord > 0
               else len(bulk.aefacts[caero.lchord].data) - 1)
        id_to_k[box.caero_eid + box.i_span * nch + box.j_chord] = box.k

    hinge_moments: dict = {}
    for aesurf in bulk.aesurfs.values():
        aelist = bulk.aelists.get(aesurf.alid1)
        if aelist is None:
            continue
        o, R = _get_transform(aesurf.cid1, bulk.cord2rs)
        h_hat = R[:, 1]                                   # hinge axis = cid1 y-axis
        ks = [id_to_k[bid] for bid in aelist.elements if bid in id_to_k]

        def _hm(f_box, _ks=ks, _o=o, _h=h_hat):
            total = 0.0
            for k in _ks:
                F = f_box[3 * k:3 * k + 3]
                r = aero.boxes[k].force_point - _o
                total += float(np.dot(np.cross(r, F), _h))
            return total

        entry = {'total': _hm(f_box_trim)}
        for col, lbl in enumerate(all_labels):
            f_box_col = aero.skj @ (aero.ajj_inv_corr @ D_jx[:, col])
            entry[lbl] = _hm(f_box_col)
        hinge_moments[aesurf.label.upper()] = entry

    return hinge_moments


def _compute_restrained_derivs(
    K_ll_lu: tuple,
    l_idx: list,
    Q_ax_a: np.ndarray,
    M_ax_a: np.ndarray,
    all_labels: list,
    u_a_trim: np.ndarray,
    delta_all_trim: np.ndarray,
    aero: AeroModel,
    D_jx: np.ndarray,
    T: np.ndarray,
    free_local: list,
    n_red: int,
    bulk,
    x_ref: float,
    q: float,
) -> dict:
    """Elastic restrained stability derivatives — exact analytic form (AE1 Step G).

    Restrained means the SUPORT (r-set) DOFs are held at zero; the l-set responds
    elastically.  The trim problem is linear in each label δ, so the derivative is
    obtained directly from the Schur factorisation instead of by finite difference
    (which the prior one-pass hybrid approximated and which converged to neither
    NASTRAN's restrained nor unrestrained column — see AE8).

    For label column ``col`` with combined aero + inertial sensitivity
    ``C_ax_l = q·Q_ax_a + M_ax_a`` on the l-set:

        ∂u_l/∂δ = K_ll⁻¹ · C_ax_l[:, col]        (K_ll already carries q·Q_aa,
                                                   so this is the restrained,
                                                   aero-coupled sensitivity)
        ∂w/∂δ   = D_jx[:, col] + D_jk·G_slope·∂u/∂δ
        ∂γ/∂δ   = A_jj*⁻¹ · ∂w/∂δ
        ∂f_box/∂δ = S_kj · ∂γ/∂δ
        CZ = Σ∂Fz/∂δ / S_ref,   CMY = ∂My/∂δ / (S_ref·c_ref)

    My uses the nose-up-positive ``_pitch_moment`` convention (AE1 Step E).  Each
    g-set displacement derivative is expanded through the RBE3/RBAR T matrix so
    slave DOFs move with their masters (AE1 Step B1).  The result is exact (no FD
    truncation) and the URDD/inertial columns are carried by M_ax_a.
    """
    from sbeam.aero.integration import build_djk

    sref = bulk.aeros.sref
    cref = bulk.aeros.cref
    djk  = build_djk(aero.boxes)
    n_a  = Q_ax_a.shape[0]
    boxes = aero.boxes

    # Combined aero + inertial sensitivity on the l-set (one column per label).
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, list(range(len(all_labels))))]
              + M_ax_a[np.ix_(l_idx, list(range(len(all_labels))))])

    # ∂u_l/∂δ for every label at once: K_ll⁻¹ · C_ax_l  (n_l, n_labels)
    du_l_all = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)

    rest_derivs: dict = {}
    for col, label in enumerate(all_labels):
        # Scatter the l-set sensitivity into a full a-set vector, then expand to
        # the g-set so RBAR/RBE3 slaves follow their masters.
        u_a_d = np.zeros(n_a)
        for li_idx, li in enumerate(l_idx):
            u_a_d[li] = du_l_all[li_idx, col]
        u_full_d = _expand_to_g(u_a_d, T, free_local, n_red)

        # Linear normalwash sensitivity: direct trim term + elastic feedback.
        dw = D_jx[:, col] + djk @ (aero.g_slope @ u_full_d)
        dgamma = aero.ajj_inv_corr @ dw
        df_box = aero.skj @ dgamma                              # (3·n_box,) force/q

        rest_derivs[label] = {
            'CZ':  df_box[2::3].sum() / sref,
            'CMY': _pitch_moment(df_box, boxes, x_ref) / (sref * cref),
        }

    return rest_derivs


def _divergence_dynamic_pressure(K_ll: np.ndarray, Q_ll: np.ndarray) -> Optional[float]:
    """Critical static-aeroelastic divergence dynamic pressure (restrained l-set).

    Divergence occurs when the effective stiffness ``K_ll - q*Q_ll`` first becomes
    singular, i.e. ``K_ll x = q*Q_ll x``.  Rewriting as the standard eigenproblem
    ``(K_ll^{-1} Q_ll) x = (1/q) x``, the eigenvalues are ``1/q``; the lowest
    positive divergence pressure is the reciprocal of the largest positive real
    eigenvalue.  The restrained l-set (SUPORT DOFs removed) is used because the
    full a-set ``K_aa`` is singular for the free-flight SUPORT model.

    This is the single critical divergence pressure derived from the trim
    matrices.  A user-driven DIVERG-card q-sweep is a separate item (Step 55).

    Returns:
        Lowest positive divergence dynamic pressure, or None if the model does
        not diverge (no positive real eigenvalue — e.g. a stiffening surface).
    """
    if K_ll.size == 0:
        return None
    try:
        M = scipy.linalg.solve(K_ll, Q_ll)        # K_ll^{-1} Q_ll
        eigvals = scipy.linalg.eigvals(M)
    except Exception:
        return None
    # Keep eigenvalues that are real and positive (1/q must be a positive real).
    real_pos = [ev.real for ev in eigvals
                if abs(ev.imag) < 1e-8 * max(1.0, abs(ev.real)) and ev.real > 1e-12]
    if not real_pos:
        return None
    return float(1.0 / max(real_pos))


def run_sol144_trim(
    bulk: BulkData,
    subcase: SubcaseControl,
    aero: AeroModel,
    aero_cache: Optional["AeroCache"] = None,
) -> Sol144TrimResult:
    """SOL 144 static aeroelastic trim solve (Step 52).

    Solves the coupled structural/aerodynamic trim problem using the Schur
    complement method.  Only the determined case (n_free == n_suport) is
    supported; an over-determined case raises NotImplementedError.

    Args:
        bulk:       Parsed BulkData — must include SUPORT and TRIM cards.
        subcase:    SubcaseControl — uses spc_sid and trim_sid.
        aero:       AeroModel with g_slope, g_disp, ajj_inv_corr, skj, wg
                    populated.  Used directly when its Mach matches the TRIM
                    Mach; otherwise it seeds the AeroCache and the AIC is rebuilt
                    at the TRIM Mach (AE9).
        aero_cache: Optional AeroCache shared across subcases so multi-Mach runs
                    build each AIC once.  When None, a local cache seeded with
                    ``aero`` is created.

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

    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)
    spc_sid = subcase.spc_sid

    # ------------------------------------------------------------------ #
    # Resolve the flight Mach for this subcase (AE9)
    # ------------------------------------------------------------------ #
    # The AIC is Mach-dependent (Prandtl–Glauert β scaling), so the flight Mach
    # comes from the TRIM card.  AEROS.mach is the fallback when the TRIM field is
    # unset (0.0); a genuine disagreement is warned about.  A supersonic Mach is
    # rejected by build_aero_model / AeroCache (steady subsonic VLM only).
    aeros_mach = bulk.aeros.mach if bulk.aeros else 0.0
    mach = trim_card.mach if trim_card.mach else aeros_mach
    if trim_card.mach and aeros_mach and abs(trim_card.mach - aeros_mach) > 1e-9:
        warnings.warn(
            f"run_sol144_trim: TRIM Mach {trim_card.mach} disagrees with AEROS "
            f"Mach {aeros_mach}; using the TRIM Mach {trim_card.mach} for the AIC.",
            UserWarning,
        )

    if aero_cache is None:
        aero_cache = AeroCache(bulk, grid_index, seed=aero)
    aero = aero_cache.get(mach)

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
    # Reference geometry + RCSID rotation matrix for URDD transform
    # ------------------------------------------------------------------ #
    aeros = bulk.aeros
    from sbeam.assembly.coord_transform import _get_transform
    if aeros.rcsid:
        x_ref_pt, R_rcsid = _get_transform(aeros.rcsid, bulk.cord2rs)
        x_ref    = float(x_ref_pt[0])
        suport_pos = x_ref_pt          # RCSID origin = moment reference
    else:
        x_ref    = 0.0
        R_rcsid  = np.eye(3)
        suport_pos = np.zeros(3)

    # ------------------------------------------------------------------ #
    # Build D_jx and Q_ax on the g-set
    # ------------------------------------------------------------------ #
    # Full-span model: aero and inertia are both whole-airplane, so there is no
    # symmetry force-doubling factor (the AE1 Step D `sym=2` double-count that
    # halved the trim solution is gone with half-span support).
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
    f_aero_g = q_dyn * build_fg(aero, aero.g_disp)   # (n_g,) baseline aero (whole-airplane)

    # Aerodynamic contribution of prescribed trim variables (URDD cols = 0)
    label_to_col = {l: i for i, l in enumerate(all_labels)}
    pres_values = np.array([prescribed_dict.get(l, 0.0) for l in all_labels])
    pres_aero_g = q_dyn * Q_ax_g @ pres_values       # (n_g,)

    # Transform prescribed URDD values from RCSID frame to basic frame (AE5).
    # pres_values_basic is used only for the inertial path; prescribed_dict
    # is preserved in RCSID-frame form so trim_vars output matches the input card.
    # Transform prescribed URDD values from RCSID frame to basic frame (AE5).
    # Build the full 3-vector with zeros for absent components, rotate, then write
    # back only the components that are actually present in all_labels.
    pres_values_basic = pres_values.copy()
    if aeros.rcsid:
        _trans_lbls = ['URDD1', 'URDD2', 'URDD3']
        _rot_lbls   = ['URDD4', 'URDD5', 'URDD6']
        t_map = {l: label_to_col[l] for l in _trans_lbls if l in label_to_col}
        r_map = {l: label_to_col[l] for l in _rot_lbls   if l in label_to_col}
        if t_map:
            u_trans = np.array([
                pres_values_basic[label_to_col[l]] if l in label_to_col else 0.0
                for l in _trans_lbls
            ])
            u_trans_basic = R_rcsid @ u_trans
            for i, lbl in enumerate(_trans_lbls):
                if lbl in t_map:
                    pres_values_basic[t_map[lbl]] = u_trans_basic[i]
        if r_map:
            u_rot = np.array([
                pres_values_basic[label_to_col[l]] if l in label_to_col else 0.0
                for l in _rot_lbls
            ])
            u_rot_basic = R_rcsid @ u_rot
            for i, lbl in enumerate(_rot_lbls):
                if lbl in r_map:
                    pres_values_basic[r_map[lbl]] = u_rot_basic[i]

    # Inertial sensitivity matrix (basic frame); prescribed inertial RHS (AE7).
    # M_ax_g[:, col] = dF/dURDD_col; zero for non-URDD labels.
    M_ax_g = _build_inertial_cols(bulk, all_labels, grid_index, suport_pos)
    pres_inertial_g = M_ax_g @ pres_values_basic     # (n_g,) — free URDD entry = 0

    f_rhs_g = f_aero_g + pres_aero_g + pres_inertial_g  # (n_g,)

    # Reduce f_rhs to a-set
    if dep_dofs:
        f_rhs_red = T.T @ f_rhs_g
    else:
        f_rhs_red = f_rhs_g.copy()
    f_rhs_a = f_rhs_red[free_local]   # (n_a,)

    # Reduce M_ax to a-set (same RBE3+SPC path as Q_ax)
    if dep_dofs:
        M_ax_red = T.T @ M_ax_g
    else:
        M_ax_red = M_ax_g
    M_ax_a = M_ax_red[np.ix_(free_local, list(range(len(all_labels))))]  # (n_a, n_labels)

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
    free_label_cols = [label_to_col[l] for l in free_labels]

    # ------------------------------------------------------------------ #
    # Schur-complement trim solve
    # ------------------------------------------------------------------ #
    u_a, delta_free_arr, K_ll_lu, l_idx, r_idx = _solve_trim_determined(
        K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q_dyn, suport_local, free_label_cols
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
    # Expand a-set displacement to full g-set via RBAR/RBE3 T matrix.
    # AE1 Step B1: RBAR slave DOFs must move with their masters before any
    # downstream `g_slope @ u` or `_compute_aero_forces` call; a bare index
    # scatter leaves them at zero and corrupts the structural normalwash.
    # ------------------------------------------------------------------ #
    displacements = _expand_to_g(u_a, T, free_local, len(red_dofs))

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
        K_ll_lu, l_idx, Q_ax_a, M_ax_a, all_labels,
        u_a, delta_all, aero, D_jx,
        T, free_local, len(red_dofs),
        bulk, x_ref, q_dyn,
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
    # nose-up-positive (single-source helper, AE1 Step E); whole-airplane (full-span)
    My_total = float(_pitch_moment(f_box_vec, aero.boxes, x_ref))
    sref = aeros.sref
    cref = aeros.cref
    # Fz_total and My_total are force/q (skj @ Cp); divide by area only, not q.
    total_cl = Fz_total / sref if sref > 0 else 0.0
    total_cm = My_total / (sref * cref) if sref * cref > 0 else 0.0

    # ------------------------------------------------------------------ #
    # Hinge-moment derivatives + trimmed hinge moment per AESURF control
    # ------------------------------------------------------------------ #
    hinge_moments = _compute_hinge_moments(aero, D_jx, all_labels, bulk, f_box_vec)

    # ------------------------------------------------------------------ #
    # Step 56 — per-box pressures/forces, g-set flight loads, divergence q
    # ------------------------------------------------------------------ #
    # f_box_vec is in force/q units; the physical box force is q * f_box_vec.
    # ΔCp is the normal-projected force per unit area in force/q units (so the
    # box's z-normal flat-plate limit reduces to f_box_vec[3j+2] / area).
    n_box = len(aero.boxes)
    box_forces = np.empty((n_box, 3))
    box_cp = np.empty(n_box)
    for j, b in enumerate(aero.boxes):
        f_j = f_box_vec[3 * j:3 * j + 3]
        box_forces[j] = q_dyn * f_j
        box_cp[j] = float(np.dot(f_j, b.normal) / b.area) if b.area > 0 else 0.0

    # g-set aero flight-load vector for FORCE/MOMENT export (plain trim:
    # G_disp^T · q · P_k).  Preserves net force/moment through the spline.
    grid_loads = aero.g_disp.T @ (q_dyn * f_box_vec)

    # Critical divergence dynamic pressure on the restrained l-set.
    K_ll_div = K_aa[np.ix_(l_idx, l_idx)]
    Q_ll_div = Q_aa[np.ix_(l_idx, l_idx)]
    q_div = _divergence_dynamic_pressure(K_ll_div, Q_ll_div)

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
        box_cp=box_cp,
        box_forces=box_forces,
        grid_loads=grid_loads,
        q_div=q_div,
        hinge_moments=hinge_moments,
    )
