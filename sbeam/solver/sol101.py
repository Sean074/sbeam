"""SOL 101 static analysis solver."""

from dataclasses import dataclass
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
    """Compute 12-vector of local end forces for a CBAR element.

    Kept on the explicit dict signature (section-cut tests call it directly);
    the matrices come from the line-element registry (#38) and the product is
    the shared ``local_end_forces``.
    """
    from sbeam.assembly.elements import cbar_line_element
    from sbeam.solver.element_recovery import local_end_forces
    le = cbar_line_element(cbar, grids, pbars, mat1s)
    return local_end_forces(le, displacements, grid_index)


@dataclass(frozen=True)
class BarInternal:
    """CBAR internal resultants on the positive (+x) face of the section.

    The face convention is the section-cut / CBAR end-B sign of
    ``09_conventions.md`` §9: each value is the force or moment that the part
    of the element beyond the station exerts on the station, in the element
    local frame. Axial ``p`` is tension-positive; ``vy``/``vz`` act along local
    +y/+z; ``t``, ``my_*``, ``mz_*`` are right-handed about local +x/+y/+z.
    Without element loads ``p``, ``vy``, ``vz`` and ``t`` are constant along the
    element, so one value each is kept; the bending moments differ between
    the ends and are kept per end.
    """
    p: float
    vy: float
    vz: float
    t: float
    my_a: float
    mz_a: float
    my_b: float
    mz_b: float


def bar_internal_resultants(f_local: FloatArray) -> BarInternal:
    """Convert the element-frame nodal 12-vector ``f_local = K·u`` to +x-face
    internal resultants (DEF-M21, #37).

    ``f_local`` holds the forces the nodes exert on the element:
    ``[Fx_A, Fy_A, Fz_A, Mx_A, My_A, Mz_A, Fx_B, Fy_B, Fz_B, Mx_B, My_B, Mz_B]``.
    At end B the nodal value *is* the +x-face internal resultant; at end A the
    +x-face resultant is the negated nodal value. This is the only place in
    the solver where that nodal-to-internal sign conversion happens; stress
    recovery and force recovery both consume it (#37, #21).

    End-B moments are read directly from ``f_local[10]``/``f_local[11]``, not
    rebuilt from end A by equilibrium. Without element loads the two agree
    (``Mz_B = Mz_A − Vy·L``, ``My_B = My_A + Vz·L``; gate G4 of
    ``docs/30_future/designs/cbar_stress_recovery_sign.md``). A future PLOAD1
    implementation must revisit this function.
    """
    return BarInternal(
        p=float(f_local[6]),
        vy=float(f_local[7]),
        vz=float(f_local[8]),
        t=float(f_local[9]),
        my_a=-float(f_local[4]),
        mz_a=-float(f_local[5]),
        my_b=float(f_local[10]),
        mz_b=float(f_local[11]),
    )


def _bar_force_from_internal(eid: int, r: BarInternal) -> BarForce:
    """Map +x-face internal resultants onto the NASTRAN force layout.

    ``M1 = +Mz⁺`` (plane 1, x–y) and ``M2 = −My⁺`` (plane 2, x–z): NASTRAN-95
    ``sbar2.f`` forms ``M1A = −FA(6)``, ``M2A = +FA(5)`` from the end-A nodal
    forces, which is exactly ``mz_a = −f[5]`` and ``−my_a = +f[4]``. Defined
    this way both plane moments are positive when they compress the +y / +z
    fibres.
    """
    return BarForce(
        eid=eid,
        m1_a=r.mz_a, m2_a=-r.my_a,
        m1_b=r.mz_b, m2_b=-r.my_b,
        v1=r.vy, v2=r.vz,
        axial=r.p, torque=r.t,
    )


def recover_bar_forces(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1], displacements: FloatArray, grid_index: dict[int, int],
) -> BarForce:
    """Recover CBAR end forces as +x-face internal resultants in the NASTRAN
    plane layout (DEF-M18, #21). See :class:`BarForce` for signs."""
    f_local = _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index)
    return _bar_force_from_internal(cbar.eid, bar_internal_resultants(f_local))


def _bending_stress(m1: float, m2: float, y: float, z: float, I1: float, I2: float) -> float:
    """Bending-only fibre stress ``σ_b = −M1·y/I1 − M2·z/I2`` (NASTRAN-95
    ``sbar2.f``; I12 = 0) on the :class:`BarForce` plane moments. With
    ``M1 = Mz⁺`` and ``M2 = −My⁺`` this is ``−Mz·y/I1 + My·z/I2`` on the
    +x-face resultants (DEF-M21). Tension positive."""
    stress = 0.0
    if I1 > 0:
        stress -= m1 * y / I1
    if I2 > 0:
        stress -= m2 * z / I2
    return stress


def recover_bar_stresses(
    cbar: Cbar, grids: dict[int, Grid], pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1], displacements: FloatArray, grid_index: dict[int, int],
) -> BarStress:
    """Recover CBAR stresses at the PBAR recovery points in the NASTRAN layout:
    bending-only ``SA1–4``/``SB1–4`` at C, D, E, F, ``AXIAL = P/A``, and
    ``SA/SB-MAX/MIN = AXIAL + max/min(bending)`` (DEF-M18, #21). The bending
    values come from the same plane moments the force table prints, so the two
    tables are consistent by construction."""
    f_local = _element_local_forces(cbar, grids, pbars, mat1s, displacements, grid_index)
    bf = _bar_force_from_internal(cbar.eid, bar_internal_resultants(f_local))

    pbar = pbars[cbar.pid]
    A, I1, I2 = pbar.A, pbar.I1, pbar.I2
    pts = ((pbar.c1, pbar.c2), (pbar.d1, pbar.d2), (pbar.e1, pbar.e2), (pbar.f1, pbar.f2))
    sa = [_bending_stress(bf.m1_a, bf.m2_a, y, z, I1, I2) for y, z in pts]
    sb = [_bending_stress(bf.m1_b, bf.m2_b, y, z, I1, I2) for y, z in pts]
    axial = bf.axial / A if A > 0 else 0.0

    return BarStress(
        eid=cbar.eid,
        sa1=sa[0], sa2=sa[1], sa3=sa[2], sa4=sa[3],
        sb1=sb[0], sb2=sb[1], sb3=sb[2], sb4=sb[3],
        axial=axial,
        sa_max=axial + max(sa), sa_min=axial + min(sa),
        sb_max=axial + max(sb), sb_min=axial + min(sb),
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

    # Recover line-element forces and stresses (CBAR + CROD/CONROD, #38)
    from sbeam.solver.element_recovery import recover_line_elements
    elems = recover_line_elements(bulk, displacements, grid_index)

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
        bar_forces=elems.bar_forces,
        bar_stresses=elems.bar_stresses,
        cbush_forces=cbush_forces,
        rod_forces=elems.rod_forces,
        rod_stresses=elems.rod_stresses,
    )
