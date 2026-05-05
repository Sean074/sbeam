"""Consistent mass matrix assembly for Euler-Bernoulli beam elements."""

import numpy as np

from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import transform_matrix


def local_mass(pbar: Pbar, mat1: Mat1, L: float) -> np.ndarray:
    """12x12 consistent mass matrix for a CBAR element in local coordinates.

    Local DOF order per node: [Tx, Ty, Tz, Rx, Ry, Rz]
    Node A = indices 0-5, Node B = indices 6-11.
    """
    m_lin = mat1.rho * pbar.A + pbar.nsm  # mass per unit length
    c = m_lin * L / 420.0

    M = np.zeros((12, 12))

    # Axial [0, 6]
    M[0, 0] = 140 * c;  M[6, 6] = 140 * c
    M[0, 6] = 70 * c;   M[6, 0] = 70 * c

    # Bending xy-plane [v=1, θz=5, v=7, θz=11] — uses θz = dv/dx convention
    idx1 = [1, 5, 7, 11]
    M_b1 = c * np.array([
        [ 156,    22*L,    54,   -13*L],
        [ 22*L,  4*L**2,  13*L,  -3*L**2],
        [ 54,    13*L,   156,   -22*L],
        [-13*L,  -3*L**2, -22*L,  4*L**2],
    ])
    for ii, ri in enumerate(idx1):
        for jj, ci in enumerate(idx1):
            M[ri, ci] += M_b1[ii, jj]

    # Bending xz-plane [w=2, θy=4, w=8, θy=10] — uses θy = -dw/dx convention
    idx2 = [2, 4, 8, 10]
    M_b2 = c * np.array([
        [ 156,   -22*L,   54,    13*L],
        [-22*L,  4*L**2, -13*L,  -3*L**2],
        [ 54,   -13*L,  156,    22*L],
        [ 13*L,  -3*L**2, 22*L,  4*L**2],
    ])
    for ii, ri in enumerate(idx2):
        for jj, ci in enumerate(idx2):
            M[ri, ci] += M_b2[ii, jj]

    # Torsion [θx=3, θx=9] — rotational inertia from polar area moment
    I_polar = pbar.I1 + pbar.I2
    if I_polar > 0:
        c_rot = mat1.rho * I_polar * L / 6.0
        M[3, 3] = 2 * c_rot;  M[9, 9] = 2 * c_rot
        M[3, 9] = c_rot;      M[9, 3] = c_rot

    return M


def element_mass_global(
    cbar: Cbar,
    grids: dict,
    pbars: dict,
    mat1s: dict,
) -> np.ndarray:
    """12x12 element mass matrix in global coordinates: T.T @ M_local @ T."""
    pbar = pbars[cbar.pid]
    mat1 = mat1s[pbar.mid]

    ga = grids[cbar.ga]
    gb = grids[cbar.gb]
    dx = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z])
    L = np.linalg.norm(dx)

    M_local = local_mass(pbar, mat1, L)
    T = transform_matrix(cbar, grids)

    return T.T @ M_local @ T


def assemble_global_mass(bulk: BulkData) -> np.ndarray:
    """Assemble the (6N x 6N) global consistent mass matrix.

    Includes CBAR element contributions and CONM2 point masses.
    CONM2 contributes the full 6x6 symmetric block: translational mass,
    offset-induced translation-rotation coupling, parallel-axis rotational
    inertia, and CM inertia tensor (I11-I33).
    """
    grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}
    n = 6 * len(grid_index)
    M_global = np.zeros((n, n))

    for cbar in bulk.cbars.values():
        M_e = element_mass_global(cbar, bulk.grids, bulk.pbars, bulk.mat1s)

        ia = grid_index[cbar.ga]
        ib = grid_index[cbar.gb]

        dofs_a = [6 * ia + d for d in range(6)]
        dofs_b = [6 * ib + d for d in range(6)]
        dofs = dofs_a + dofs_b

        for i_local, i_global in enumerate(dofs):
            for j_local, j_global in enumerate(dofs):
                M_global[i_global, j_global] += M_e[i_local, j_local]

    for conm2 in bulk.conm2s.values():
        if conm2.gid not in grid_index:
            continue
        idx = grid_index[conm2.gid]
        base = 6 * idx
        m = conm2.m
        r = np.array([conm2.x1, conm2.x2, conm2.x3])

        # Translational 3x3: m*I3
        M_global[base, base] += m
        M_global[base + 1, base + 1] += m
        M_global[base + 2, base + 2] += m

        # Off-diagonal coupling and parallel-axis rotational inertia (offset terms)
        if conm2.x1 != 0.0 or conm2.x2 != 0.0 or conm2.x3 != 0.0:
            # M_tr = -m * tilde(r), placed at rows [Tx,Ty,Tz], cols [Rx,Ry,Rz]
            # tilde(r) = [[0,-r2,r1],[r2,0,-r0],[-r1,r0,0]]
            M_tr = -m * np.array([
                [0.0,   -r[2],  r[1]],
                [r[2],   0.0,  -r[0]],
                [-r[1],  r[0],  0.0],
            ])
            M_global[base:base+3, base+3:base+6] += M_tr
            M_global[base+3:base+6, base:base+3] += M_tr.T

            # M_rr (parallel axis) = m * (|r|^2 * I3 - r*r^T)
            M_global[base+3:base+6, base+3:base+6] += (
                m * (np.dot(r, r) * np.eye(3) - np.outer(r, r))
            )

        # CM inertia tensor (zero by default; symmetric by construction)
        M_global[base+3, base+3] += conm2.i11
        M_global[base+3, base+4] += conm2.i21
        M_global[base+4, base+3] += conm2.i21
        M_global[base+4, base+4] += conm2.i22
        M_global[base+3, base+5] += conm2.i31
        M_global[base+5, base+3] += conm2.i31
        M_global[base+4, base+5] += conm2.i32
        M_global[base+5, base+4] += conm2.i32
        M_global[base+5, base+5] += conm2.i33

    return M_global
