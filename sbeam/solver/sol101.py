"""SOL 101 static analysis solver."""

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import (
    assemble_global_stiffness,
    get_spc_dofs,
    apply_spcs,
    local_stiffness,
    transform_matrix,
    element_stiffness_global,
)
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
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

    # Recovery point C
    sa_c = _stress_at_point(fx_a, mz_a, my_a, pbar.c1, pbar.c2, A, I1, I2)
    sb_c = _stress_at_point(fx_b, mz_b, my_b, pbar.c1, pbar.c2, A, I1, I2)

    # Recovery point D
    sa_d = _stress_at_point(fx_a, mz_a, my_a, pbar.d1, pbar.d2, A, I1, I2)
    sb_d = _stress_at_point(fx_b, mz_b, my_b, pbar.d1, pbar.d2, A, I1, I2)

    # Recovery point E
    sa_e = _stress_at_point(fx_a, mz_a, my_a, pbar.e1, pbar.e2, A, I1, I2)
    sb_e = _stress_at_point(fx_b, mz_b, my_b, pbar.e1, pbar.e2, A, I1, I2)

    # Recovery point F
    sa_f = _stress_at_point(fx_a, mz_a, my_a, pbar.f1, pbar.f2, A, I1, I2)
    sb_f = _stress_at_point(fx_b, mz_b, my_b, pbar.f1, pbar.f2, A, I1, I2)

    # Axial stress (pure axial, no bending contribution)
    axial_stress = fx_b / A if A > 0 else 0.0

    return BarStress(
        eid=cbar.eid,
        axial=axial_stress,
        sa=sa_c,
        sb=sb_c,
        sa_d=sa_d,
        sb_d=sb_d,
        sa_e=sa_e,
        sb_e=sb_e,
        sa_f=sa_f,
        sb_f=sb_f,
    )


def recover_reactions(bulk: BulkData, displacements: np.ndarray, spc_dofs: list, K: np.ndarray, grid_index: dict) -> dict:
    """Compute SPC reaction forces.

    Returns {gid: np.ndarray(6,)} for grids with constrained DOFs.
    """
    if not spc_dofs:
        return {}

    spc_dofs_unique = list(set(spc_dofs))

    # Reaction = K[constrained_dofs, :] @ u
    reactions_vec = K[spc_dofs_unique, :] @ displacements

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


def run_sol101(bulk: BulkData, case_control) -> Sol101Result:
    """Run SOL 101 static analysis and return results.

    Assumes single subcase (first subcase in case_control.subcases).
    """
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)

    # Assemble global stiffness
    K = assemble_global_stiffness(bulk)

    # Use first subcase
    subcase = case_control.subcases[0]
    load_sid = subcase.load_sid
    spc_sid = subcase.spc_sid

    # Load vector
    f = assemble_load_vector(bulk, load_sid)

    # SPC enforcement
    spc_dofs = get_spc_dofs(bulk, spc_sid, grid_index)
    K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)

    # Solve
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

    # Recover reactions
    reactions = recover_reactions(bulk, displacements, spc_dofs, K, grid_index)

    return Sol101Result(
        displacements=displacements,
        reactions=reactions,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
    )
