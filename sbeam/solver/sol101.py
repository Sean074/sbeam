"""SOL 101 static analysis solver."""

from typing import Optional, Union, cast

import numpy as np
import scipy.linalg
import scipy.sparse
import scipy.sparse.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import (
    assemble_global_stiffness,
    get_spc_dofs,
    check_spc_enforced_displacements,
    local_stiffness,
    transform_matrix,
    cbush_stiffness_global,
)
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.assembly.reduction import reduce_to_aset
from sbeam.linalg_utils import estimate_cond_1norm
from sbeam.model.element import Cbar, Cbush
from sbeam.results.results import BarForce, BarStress, Sol101Result
from sbeam.types import FloatArray, SparseMatrix
from sbeam.model.grid import Grid
from sbeam.model.property import Pbar, Pbush
from sbeam.model.material import Mat1


def solve_static(
    K_free: Union[FloatArray, SparseMatrix], f_free: FloatArray,
    free_dofs: list[int], n_dofs: int,
) -> FloatArray:
    """Solve K_free @ u_free = f_free and return full displacement vector.

    K_free may be a sparse CSR matrix (normal path) or a dense ndarray (RBE3
    branch, where T.T @ K_csr @ T produces dense via NumPy's @ operator).
    Raises ValueError if the stiffness matrix is singular or ill-conditioned.
    """
    if not isinstance(K_free, np.ndarray):
        # cast: .tocsc() is typed as csc_matrix | csc_array; spsolve accepts
        # either, but its overloads are not written over that union.
        # spsolve returns a sparse result only for a sparse RHS; f_free is
        # dense, so the result is always a dense vector.
        u_free = cast(FloatArray, scipy.sparse.linalg.spsolve(
            cast(scipy.sparse.csc_matrix, K_free.tocsc()), f_free))
        if not np.all(np.isfinite(u_free)):
            raise ValueError(
                "Singular stiffness matrix: model may have unconstrained DOFs"
            )
    else:
        # Dense path: used when RBE3 transformation collapses K to dense.
        # Factor once (DEF-R6): gecon 1-norm condition estimate replaces the
        # former full-SVD np.linalg.cond, and the same LU serves the solve.
        try:
            cond, k_lu = estimate_cond_1norm(K_free)
        except Exception:
            cond, k_lu = np.inf, None
        if k_lu is None or cond > 1e15:
            raise ValueError(
                "Singular stiffness matrix: model may have unconstrained DOFs"
            )
        u_free = scipy.linalg.lu_solve(k_lu, f_free)

    u = np.zeros(n_dofs)
    for local_idx, global_dof in enumerate(free_dofs):
        u[global_dof] = u_free[local_idx]

    return u


def _element_local_forces(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1], displacements: FloatArray, grid_index: dict[int, int],
) -> FloatArray:
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
    L = float(np.linalg.norm(
        np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z])
    ))

    K_local = local_stiffness(pbar, mat1, L)
    T = transform_matrix(cbar, grids)

    u_local = T @ u_global_elem
    f_local = K_local @ u_local

    return f_local


def recover_bar_forces(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1], displacements: FloatArray, grid_index: dict[int, int],
) -> BarForce:
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


def _stress_at_point(
    fx_a: float, mz_a: float, my_a: float,
    y: float, z: float, A: float, I1: float, I2: float,
) -> float:
    """σ = Fx/A + Mz*y/I1 - My*z/I2"""
    stress = 0.0
    if A > 0:
        stress += fx_a / A
    if I1 > 0:
        stress += mz_a * y / I1
    if I2 > 0:
        stress -= my_a * z / I2
    return stress


def recover_bar_stresses(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1], displacements: FloatArray, grid_index: dict[int, int],
) -> BarStress:
    """Recover CBAR stresses at PBAR recovery points."""
    f_local = _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index)

    pbar = pbars[cbar.pid]
    A = pbar.A
    I1 = pbar.I1
    I2 = pbar.I2

    # f_local[6] = Fx at end B = internal axial force P, tension-positive.
    # f_local[0] = Fx at end A is sign-negated (reaction) — do not use for stress.
    p_axial = f_local[6]
    my_a = f_local[4]
    mz_a = f_local[5]
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
            _stress_at_point(p_axial, mz_a, my_a, y, z, A, I1, I2),
            _stress_at_point(p_axial, mz_b, my_b, y, z, A, I1, I2),
        )
        for pt, (y, z) in recovery_pts.items()
    }

    axial_stress = p_axial / A if A > 0 else 0.0

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
    grids: dict[int, Grid],
    pbushs: dict[int, Pbush],
    displacements: FloatArray,
    grid_index: dict[int, int],
) -> FloatArray:
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
    displacements: FloatArray,
    spc_dofs: list[int],
    K: Union[FloatArray, SparseMatrix],
    grid_index: dict[int, int],
    f_applied: Optional[FloatArray] = None,
) -> dict[int, FloatArray]:
    """Compute SPC reaction forces.

    R_c = K[spc,:] @ u - f_applied[spc].  The f_applied term is zero for
    FORCE/MOMENT loads (all forces at free DOFs) but non-zero for body loads
    such as GRAV where gravity acts on the mass at constrained nodes too.

    Returns {gid: FloatArray(6,)} for grids with constrained DOFs.
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

    if spc_sid is not None:
        check_spc_enforced_displacements(bulk, spc_sid)

    # Load vector (saved before RBE3 transform for reaction correction)
    if load_sid is None:
        f = np.zeros(n_dofs)
    else:
        f = assemble_load_vector(bulk, load_sid)
    f_full = f.copy()

    # RBE3/RBAR reduction + SPC partitioning, through the Step-59 shared
    # ``reduce_to_aset`` (DEF-R5).  SOL 101 used to hand-roll this — including its
    # own copy of the silently-discarded-SPC bug — so the fix now lands once for
    # SOL 101, 103, 144 and the maneuver solvers.
    #
    # ``K`` itself is deliberately NOT rebound: ``recover_reactions`` needs the
    # unreduced, g-set-sized sparse stiffness, the unreduced load vector and the
    # raw SPC DOF list, none of which live on the AsetReduction.
    # ``reduce_matrix`` preserves sparsity exactly when the old code did (no
    # dependent DOFs), so ``solve_static``'s sparse/dense dispatch is unchanged.
    red = reduce_to_aset(bulk, grid_index, spc_sid)
    spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)

    K_aa = red.reduce_matrix(K)
    f_aa = red.reduce_vector(f)
    n_a = len(red.free_local)
    u_a = solve_static(K_aa, f_aa, list(range(n_a)), n_a)
    displacements = red.expand_to_g(u_a)

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
    # K is the unreduced g-set sparse stiffness (never rebound by the port);
    # f_full is the load vector before reduction.
    reactions = recover_reactions(
        bulk, displacements, spc_dofs_full, K, grid_index, f_full)

    return Sol101Result(
        displacements=displacements,
        reactions=reactions,
        bar_forces=bar_forces,
        bar_stresses=bar_stresses,
        cbush_forces=cbush_forces,
    )
