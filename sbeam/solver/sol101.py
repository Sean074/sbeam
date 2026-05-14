"""SOL 101 static analysis solver."""

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import (
    assemble_global_stiffness,
    get_spc_dofs,
    apply_spcs,
    local_stiffness,
    transform_matrix,
    cbush_stiffness_global,
)
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.model.element import Cbush
from sbeam.results.results import BarForce, BarStress, Sol101Result


def solve_static(
    K_free: np.ndarray,
    f_free: np.ndarray,
    free_dofs: list,
    n_dofs: int,
) -> np.ndarray:
    """Solve K_free @ u_free = f_free and return full displacement vector.

    Raises ValueError if the stiffness matrix is singular or ill-conditioned.
    """
    # Check condition number to detect singular/near-singular systems
    try:
        cond = np.linalg.cond(K_free)
    except Exception:
        cond = np.inf

    if cond > 1e15:
        raise ValueError(
            "Singular stiffness matrix: model may have unconstrained DOFs"
        )

    try:
        u_free = scipy.linalg.solve(K_free, f_free)
    except scipy.linalg.LinAlgError:
        raise ValueError(
            "Singular stiffness matrix: model may have unconstrained DOFs"
        )

    u = np.zeros(n_dofs)
    for local_idx, global_dof in enumerate(free_dofs):
        u[global_dof] = u_free[local_idx]

    return u


def _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index):
    """Compute 12-vector of local end forces for a CBAR element."""
    pbar = pbars[cbar.pid]
    mat1 = mat1s[pbar.mid]

    ia = grid_index[cbar.ga]
    ib = grid_index[cbar.gb]

    dofs_a = [6 * ia + d for d in range(6)]
    dofs_b = [6 * ib + d for d in range(6)]
    dofs = dofs_a + dofs_b

    u_global_elem = displacements[dofs]

    ga = grids[cbar.ga]
    gb = grids[cbar.gb]
    L = np.linalg.norm(
        np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z])
    )

    K_local = local_stiffness(pbar, mat1, L)
    T = transform_matrix(cbar, grids)

    u_local = T @ u_global_elem
    f_local = K_local @ u_local

    return f_local


def recover_bar_forces(cbar, grids, pbars, mat1s, displacements, grid_index) -> BarForce:
    """Recover CBAR end forces in local coordinates."""
    f_local = _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index)

    # f_local indices:
    # 0: Fx_A, 1: Fy_A, 2: Fz_A, 3: Mx_A, 4: My_A, 5: Mz_A
    # 6: Fx_B, 7: Fy_B, 8: Fz_B, 9: Mx_B, 10: My_B, 11: Mz_B
    return BarForce(
        eid=cbar.eid,
        axial=f_local[6],        # Fx at end B (tension positive)
        shear1=f_local[7],       # Fy at end B (local y)
        shear2=f_local[8],       # Fz at end B (local z)
        torque=f_local[9],       # Mx (torsion)
        bm1_a=f_local[4],        # My at end A
        bm2_a=f_local[5],        # Mz at end A
        bm1_b=f_local[10],       # My at end B
        bm2_b=f_local[11],       # Mz at end B
    )


def _stress_at_point(fx_a, mz_a, my_a, y, z, A, I1, I2):
    """σ = Fx/A + Mz*y/I1 - My*z/I2"""
    stress = 0.0
    if A > 0:
        stress += fx_a / A
    if I1 > 0:
        stress += mz_a * y / I1
    if I2 > 0:
        stress -= my_a * z / I2
    return stress


def recover_bar_stresses(cbar, grids, pbars, mat1s, displacements, grid_index) -> BarStress:
    """Recover CBAR stresses at PBAR recovery points."""
    f_local = _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index)

    pbar = pbars[cbar.pid]
    A = pbar.A
    I1 = pbar.I1
    I2 = pbar.I2

    # End A: f_local[0]=Fx_A, f_local[4]=My_A, f_local[5]=Mz_A
    # End B: f_local[6]=Fx_B, f_local[10]=My_B, f_local[11]=Mz_B
    fx_a = f_local[0]
    my_a = f_local[4]
    mz_a = f_local[5]

    fx_b = f_local[6]
    my_b = f_local[10]
    mz_b = f_local[11]

    recovery_pts = {
        "C": (pbar.c1, pbar.c2),
        "D": (pbar.d1, pbar.d2),
        "E": (pbar.e1, pbar.e2),
        "F": (pbar.f1, pbar.f2),
    }
    stresses = {
        pt: (
            _stress_at_point(fx_a, mz_a, my_a, y, z, A, I1, I2),
            _stress_at_point(fx_b, mz_b, my_b, y, z, A, I1, I2),
        )
        for pt, (y, z) in recovery_pts.items()
    }

    axial_stress = fx_b / A if A > 0 else 0.0

    return BarStress(
        eid=cbar.eid,
        axial=axial_stress,
        sa=stresses["C"][0],
        sb=stresses["C"][1],
        sa_d=stresses["D"][0],
        sb_d=stresses["D"][1],
        sa_e=stresses["E"][0],
        sb_e=stresses["E"][1],
        sa_f=stresses["F"][0],
        sb_f=stresses["F"][1],
    )


def recover_cbush_forces(
    cbush: Cbush,
    grids: dict,
    pbushs: dict,
    displacements: np.ndarray,
    grid_index: dict,
) -> np.ndarray:
    """Return 6-vector of spring forces in global coordinates for a CBUSH element.

    Returns forces at GB for two-node elements, or forces at GA for grounded elements.
    Note: forces are in global coordinates, unlike CBAR bar_forces which are in local coords.
    """
    ia = grid_index[cbush.ga]
    dofs_a = [6 * ia + d for d in range(6)]

    if cbush.gb is not None:
        ib = grid_index[cbush.gb]
        dofs_b = [6 * ib + d for d in range(6)]
        dofs = dofs_a + dofs_b
        u_e = displacements[dofs]
        K_e = cbush_stiffness_global(cbush, grids, pbushs)  # 12×12
        f_e = K_e @ u_e
        return f_e[6:12]  # forces at GB end
    else:
        u_a = displacements[dofs_a]
        K_e = cbush_stiffness_global(cbush, grids, pbushs)  # 6×6
        return K_e @ u_a


def recover_reactions(
    bulk: BulkData,
    displacements: np.ndarray,
    spc_dofs: list,
    K: np.ndarray,
    grid_index: dict,
    f_applied: np.ndarray = None,
) -> dict:
    """Compute SPC reaction forces.

    R_c = K[spc,:] @ u - f_applied[spc].  The f_applied term is zero for
    FORCE/MOMENT loads (all forces at free DOFs) but non-zero for body loads
    such as GRAV where gravity acts on the mass at constrained nodes too.

    Returns {gid: np.ndarray(6,)} for grids with constrained DOFs.
    """
    if not spc_dofs:
        return {}

    spc_dofs_unique = list(set(spc_dofs))

    reactions_vec = K[spc_dofs_unique, :] @ displacements
    if f_applied is not None:
        reactions_vec = reactions_vec - f_applied[spc_dofs_unique]

    # Build reverse map: global_dof -> gid
    dof_to_gid = {}
    for gid, idx in grid_index.items():
        for d in range(6):
            dof_to_gid[6 * idx + d] = gid

    # Accumulate reactions by GID
    reactions = {}
    for local_idx, global_dof in enumerate(spc_dofs_unique):
        gid = dof_to_gid.get(global_dof)
        if gid is None:
            continue
        if gid not in reactions:
            reactions[gid] = np.zeros(6)
        local_dof = global_dof % 6
        reactions[gid][local_dof] += reactions_vec[local_idx]

    return reactions


def run_sol101(bulk: BulkData, subcase: SubcaseControl) -> Sol101Result:
    """Run SOL 101 static analysis for a single subcase and return results."""
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)

    # Assemble global stiffness
    K = assemble_global_stiffness(bulk)

    load_sid = subcase.load_sid
    spc_sid = subcase.spc_sid

    # Load vector (saved before RBE3 transform for reaction correction)
    f = assemble_load_vector(bulk, load_sid)
    f_full = f.copy()

    # RBE3 DOF transformation — eliminates dependent DOFs before SPC partitioning.
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        K_orig = K.copy()
        K = T.T @ K @ T
        f = T.T @ f
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs = [red_map[d] for d in spc_dofs_full if d not in dep_set]
        K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
        u_red = solve_static(K_free, f_free, free_dofs, len(red_dofs))
        displacements = T @ u_red
    else:
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs = spc_dofs_full
        K_orig = K
        K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
        displacements = solve_static(K_free, f_free, free_dofs, n_dofs)

    # Recover bar forces and stresses
    bar_forces = {}
    bar_stresses = {}
    for cbar in bulk.cbars.values():
        bar_forces[cbar.eid] = recover_bar_forces(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )
        bar_stresses[cbar.eid] = recover_bar_stresses(
            cbar, bulk.grids, bulk.pbars, bulk.mat1s, displacements, grid_index
        )

    # Recover CBUSH forces
    cbush_forces = {}
    for cbush in bulk.cbushs.values():
        cbush_forces[cbush.eid] = recover_cbush_forces(
            cbush, bulk.grids, bulk.pbushs, displacements, grid_index
        )

    # Recover reactions: R = K[spc,:] @ u - f[spc].
    # The f_full subtraction handles body loads (GRAV) that act at constrained DOFs.
    reactions = recover_reactions(bulk, displacements, spc_dofs_full, K_orig, grid_index, f_full)

    return Sol101Result(
        displacements=displacements,
        reactions=reactions,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        cbush_forces=cbush_forces,
    )
