"""Element and global stiffness matrix assembly for Euler-Bernoulli beam elements."""

import numpy as np
from scipy.linalg import block_diag

from sbeam.model.element import Cbar, Cbush
from sbeam.model.property import Pbar, Pbush
from sbeam.model.material import Mat1
from sbeam.model.bulk_data import BulkData


def _node_dofs(gid: int, grid_index: dict) -> list:
    """Return the 6 global DOF indices for a grid point."""
    i = grid_index[gid]
    return [6 * i + d for d in range(6)]


def local_stiffness(pbar: Pbar, mat1: Mat1, L: float) -> np.ndarray:
    """12x12 Euler-Bernoulli local element stiffness matrix.

    Local DOF order per node: [Tx, Ty, Tz, Rx, Ry, Rz]
    Node A = indices 0-5, Node B = indices 6-11.
    """
    E = mat1.E
    G = mat1.G
    A = pbar.A
    I1 = pbar.I1   # Bending about local 1-axis (in xy-plane) → uses v, θz
    I2 = pbar.I2   # Bending about local 2-axis (in xz-plane) → uses w, θy
    J = pbar.J

    K = np.zeros((12, 12))

    # Axial (u): DOFs 0, 6
    a = E * A / L
    K[0, 0] = a;  K[6, 6] = a
    K[0, 6] = -a; K[6, 0] = -a

    # Torsion (θx): DOFs 3, 9
    t = G * J / L
    K[3, 3] = t;  K[9, 9] = t
    K[3, 9] = -t; K[9, 3] = -t

    # Bending in xy-plane (v, θz): DOFs 1, 5, 7, 11
    # Uses I1 (moment of inertia about local 1-axis)
    b1 = E * I1 / (L ** 3)
    idx1 = [1, 5, 7, 11]
    K_b1 = b1 * np.array([
        [ 12,    6*L,  -12,   6*L],
        [6*L,  4*L**2, -6*L, 2*L**2],
        [-12,   -6*L,   12,  -6*L],
        [6*L,  2*L**2, -6*L, 4*L**2],
    ])
    for ii, ri in enumerate(idx1):
        for jj, ci in enumerate(idx1):
            K[ri, ci] += K_b1[ii, jj]

    # Bending in xz-plane (w, θy): DOFs 2, 4, 8, 10
    # Uses I2 (moment of inertia about local 2-axis)
    # Sign convention: θy = -dw/dx
    b2 = E * I2 / (L ** 3)
    idx2 = [2, 4, 8, 10]
    K_b2 = b2 * np.array([
        [ 12,  -6*L, -12,  -6*L],
        [-6*L, 4*L**2, 6*L, 2*L**2],
        [-12,   6*L,  12,   6*L],
        [-6*L, 2*L**2, 6*L, 4*L**2],
    ])
    for ii, ri in enumerate(idx2):
        for jj, ci in enumerate(idx2):
            K[ri, ci] += K_b2[ii, jj]

    return K


def transform_matrix(cbar: Cbar, grids: dict) -> np.ndarray:
    """12x12 transformation matrix T such that u_local = T @ u_global.

    Local axes:
      e_x = (GB - GA) / |GB - GA|
      e_y = normalised component of orientation vector perpendicular to e_x
      e_z = e_x x e_y
    R = [e_x; e_y; e_z] (rows are local axes in global frame)
    T = block_diag(R, R, R, R)
    """
    ga = grids[cbar.ga]
    gb = grids[cbar.gb]

    ga_pos = np.array([ga.x, ga.y, ga.z], dtype=float)
    gb_pos = np.array([gb.x, gb.y, gb.z], dtype=float)

    # Local x-axis
    dx = gb_pos - ga_pos
    L = np.linalg.norm(dx)
    if L < 1e-12:
        raise ValueError(f"CBAR {cbar.eid}: nodes GA={cbar.ga} and GB={cbar.gb} are coincident")
    e_x = dx / L

    # Orientation vector v (nominally in local y direction)
    v = np.array([cbar.x1, cbar.x2, cbar.x3], dtype=float)

    # Remove component along e_x to get local y
    v_perp = v - np.dot(v, e_x) * e_x
    norm_v = np.linalg.norm(v_perp)
    if norm_v < 1e-12:
        raise ValueError(
            f"Orientation vector for CBAR {cbar.eid} is parallel to the element axis."
        )
    e_y = v_perp / norm_v

    # Local z-axis
    e_z = np.cross(e_x, e_y)

    # Rotation matrix: rows are local axes expressed in global frame
    R = np.array([e_x, e_y, e_z])  # shape (3, 3)

    # Block diagonal for 4 nodes (12 DOFs)
    T = block_diag(R, R, R, R)
    return T


def apply_pin_releases(K: np.ndarray, pa: str, pb: str) -> np.ndarray:
    """Return a copy of local 12×12 K with released DOF rows/columns zeroed.

    PA/PB are strings of DOF codes 1–6 to release at end A / end B.
    Code d at end A → local DOF index d-1 (0-based, indices 0–5).
    Code d at end B → local DOF index d-1+6 (indices 6–11).
    """
    K = K.copy()
    for c in (pa or ""):
        d = int(c) - 1          # end-A local DOF index (0-based)
        K[d, :] = 0.0
        K[:, d] = 0.0
    for c in (pb or ""):
        d = int(c) - 1 + 6      # end-B local DOF index (0-based)
        K[d, :] = 0.0
        K[:, d] = 0.0
    return K


def element_stiffness_global(
    cbar: Cbar,
    grids: dict,
    pbars: dict,
    mat1s: dict,
) -> np.ndarray:
    """12x12 element stiffness matrix in global coordinates: T.T @ K_local @ T."""
    pbar = pbars[cbar.pid]
    mat1 = mat1s[pbar.mid]

    ga = grids[cbar.ga]
    gb = grids[cbar.gb]
    ga_pos = np.array([ga.x, ga.y, ga.z])
    gb_pos = np.array([gb.x, gb.y, gb.z])
    L = np.linalg.norm(gb_pos - ga_pos)

    K_local = local_stiffness(pbar, mat1, L)
    if cbar.pa or cbar.pb:
        K_local = apply_pin_releases(K_local, cbar.pa or "", cbar.pb or "")
    T = transform_matrix(cbar, grids)

    return T.T @ K_local @ T


def assemble_global_stiffness(bulk: BulkData) -> np.ndarray:
    """Assemble the (6N x 6N) global stiffness matrix from all CBAR and CBUSH elements."""
    grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}
    n = 6 * len(grid_index)
    K_global = np.zeros((n, n))

    for cbar in bulk.cbars.values():
        K_e = element_stiffness_global(cbar, bulk.grids, bulk.pbars, bulk.mat1s)

        dofs = _node_dofs(cbar.ga, grid_index) + _node_dofs(cbar.gb, grid_index)

        for i_local, i_global in enumerate(dofs):
            for j_local, j_global in enumerate(dofs):
                K_global[i_global, j_global] += K_e[i_local, j_local]

    for cbush in bulk.cbushs.values():
        K_e = cbush_stiffness_global(cbush, bulk.grids, bulk.pbushs)
        dofs_a = _node_dofs(cbush.ga, grid_index)
        dofs = dofs_a + _node_dofs(cbush.gb, grid_index) if cbush.gb is not None else dofs_a

        for i_local, i_global in enumerate(dofs):
            for j_local, j_global in enumerate(dofs):
                K_global[i_global, j_global] += K_e[i_local, j_local]

    return K_global


def cbush_local_stiffness(pbush: Pbush) -> np.ndarray:
    """6×6 diagonal local stiffness matrix for a CBUSH element."""
    return np.diag([pbush.k1, pbush.k2, pbush.k3, pbush.k4, pbush.k5, pbush.k6])


def cbush_transform_matrix(cbush: Cbush, grids: dict) -> np.ndarray:
    """3×3 rotation matrix R for a CBUSH element.

    Rows are local axes expressed in the global frame.
    When gb is None (grounded), the orientation vector (x1/x2/x3) defines the
    local x-axis direction directly. When gb is set, e_x = GA→GB unit vector.
    """
    if cbush.gb is not None:
        ga = grids[cbush.ga]
        gb = grids[cbush.gb]
        dx = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z], dtype=float)
        L = np.linalg.norm(dx)
        if L < 1e-12:
            raise ValueError(
                f"CBUSH {cbush.eid}: nodes GA and GB are coincident; X1/X2/X3 orientation is required"
            )
        e_x = dx / L
    else:
        # Grounded: use the orientation vector as the local x-axis
        e_x_raw = np.array([cbush.x1, cbush.x2, cbush.x3], dtype=float)
        norm_ex = np.linalg.norm(e_x_raw)
        if norm_ex < 1e-12:
            e_x = np.array([1.0, 0.0, 0.0])
        else:
            e_x = e_x_raw / norm_ex

    # Orientation vector defines the XZ-plane (same role as CBAR v-vector)
    v = np.array([cbush.x1, cbush.x2, cbush.x3], dtype=float)
    v_perp = v - np.dot(v, e_x) * e_x
    norm_v = np.linalg.norm(v_perp)

    if norm_v < 1e-12:
        # Default: try global Y; fall back to global Z if parallel to e_x
        for candidate in ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
            vc = np.array(candidate)
            vp = vc - np.dot(vc, e_x) * e_x
            if np.linalg.norm(vp) > 1e-12:
                v_perp = vp
                norm_v = np.linalg.norm(v_perp)
                break
        else:
            raise ValueError(
                f"CBUSH {cbush.eid}: cannot determine local y-axis — element axis is degenerate"
            )

    e_y = v_perp / norm_v
    e_z = np.cross(e_x, e_y)
    return np.array([e_x, e_y, e_z])


def cbush_stiffness_global(cbush: Cbush, grids: dict, pbushs: dict) -> np.ndarray:
    """Global stiffness contribution for a CBUSH element.

    Returns a 12×12 array for two-node elements or a 6×6 array for grounded
    (GB=None) elements. The assembly loop must branch on cbush.gb to scatter
    the correct shape into the global matrix.
    """
    pbush = pbushs[cbush.pid]
    K6 = cbush_local_stiffness(pbush)
    R = cbush_transform_matrix(cbush, grids)
    T6 = block_diag(R, R)  # 6×6: two blocks for translational + rotational DOFs

    if cbush.gb is not None:
        # Two-node: assemble symmetric 12×12 spring-pair matrix then transform
        K12_local = np.block([[K6, -K6], [-K6, K6]])
        T12 = block_diag(R, R, R, R)
        return T12.T @ K12_local @ T12
    else:
        # Grounded: only GA contributes — 6×6
        return T6.T @ K6 @ T6


def get_spc_dofs(bulk: BulkData, spc_sid: int, grid_index: dict) -> list:
    """Return list of constrained global DOF indices for a given SPC SID.

    Also includes permanent SPCs from Grid.ps for all grids.
    Duplicates are handled by the caller (apply_spcs uses a set).
    """
    spc_dofs = []

    # --- SPC cards ---
    for spc in bulk.spcs.get(spc_sid, []):
        for c in str(spc.c1):
            d = int(c)  # 1-6
            if spc.g1 in grid_index:
                spc_dofs.append(6 * grid_index[spc.g1] + (d - 1))
        if spc.g2 is not None and spc.c2 is not None:
            for c in str(spc.c2):
                d = int(c)
                if spc.g2 in grid_index:
                    spc_dofs.append(6 * grid_index[spc.g2] + (d - 1))

    # --- SPC1 cards ---
    for spc1 in bulk.spc1s.get(spc_sid, []):
        for gid in spc1.grids:
            if gid in grid_index:
                for c in str(spc1.c):
                    d = int(c)
                    spc_dofs.append(6 * grid_index[gid] + (d - 1))

    # --- Permanent SPCs from Grid.ps ---
    for gid, grid in bulk.grids.items():
        if grid.ps and gid in grid_index:
            for c in str(grid.ps):
                d = int(c)
                spc_dofs.append(6 * grid_index[gid] + (d - 1))

    return spc_dofs


def apply_spcs(
    K: np.ndarray,
    f: np.ndarray,
    spc_dofs: list,
) -> tuple:
    """Partition K and f to free DOFs only.

    Returns (K_free, f_free, free_dofs).
    """
    constrained = set(spc_dofs)
    free_dofs = [i for i in range(K.shape[0]) if i not in constrained]
    K_free = K[np.ix_(free_dofs, free_dofs)]
    f_free = f[free_dofs]
    return K_free, f_free, free_dofs
