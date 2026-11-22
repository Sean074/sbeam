"""Element and global stiffness matrix assembly for Euler-Bernoulli beam elements."""

from typing import Optional, Union

import numpy as np
import scipy.sparse
from scipy.linalg import block_diag

from sbeam.model.element import Cbar, Cbush
from sbeam.model.property import Pbar, Pbush
from sbeam.model.material import Mat1
from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.model.coordinate_system import Cord2r
from sbeam.assembly.coord_transform import build_transform
from sbeam.types import FloatArray, SparseMatrix


def node_dofs(gid: int, grid_index: dict[int, int]) -> list[int]:
    """Return the 6 global DOF indices for a grid point."""
    i = grid_index[gid]
    return [6 * i + d for d in range(6)]


def local_stiffness(pbar: Pbar, mat1: Mat1, L: float) -> FloatArray:
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


def transform_matrix(cbar: Cbar, grids: dict[int, Grid]) -> FloatArray:
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
    L = float(np.linalg.norm(dx))
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


def release_indices(pa: str, pb: str) -> list[int]:
    """Local 12-DOF indices released by CBAR PA/PB digit strings.

    Digit d (1–6, element local axes) at end A → index d-1; at end B → index d+5.
    """
    idx = [int(c) - 1 for c in (pa or "")] + [int(c) + 5 for c in (pb or "")]
    return sorted(set(idx))


#: Relative pivot threshold below which a released DOF is only zeroed (D4 of
#: ``designs/cbar_pin_release_condensation.md``): catches I1 = 0 / J = 0 sections.
_PIVOT_REL_TOL = 1e-12


def condense_released_dofs(
    K: FloatArray, released: list[int]
) -> tuple[FloatArray, FloatArray]:
    """Static condensation of released DOFs in a local element stiffness matrix.

    Successive single-DOF Schur complements in the NASTRAN-95 ``kbar.f`` form
    (order-independent): ``K ← K − K[:,i]·K[i,:]/K[i,i]`` then zero row/column i.
    If the pivot is numerically zero the row/column is only zeroed.

    Returns ``(K', T)`` where ``K' = Tᵀ K T``.  The same ``T`` condenses the
    consistent mass (``M' = Tᵀ M T``) and any fixed-end load vector (``f' = Tᵀ f``).
    Released rows/columns of ``K'`` are exactly zero, so forces recovered as
    ``K' u`` vanish at released DOFs by construction.
    """
    n = K.shape[0]
    K = K.copy()
    T = np.eye(n)
    scale = float(np.max(np.abs(np.diag(K)))) if n else 0.0
    for i in released:
        k_ii = K[i, i]
        Ti = np.eye(n)
        Ti[i, i] = 0.0
        if abs(k_ii) > _PIVOT_REL_TOL * scale:
            row = K[i, :].copy()
            # u_i = −K[i,r]·u_r / K[i,i]: row i of Tᵢ maps the retained DOFs onto the
            # released one; column i is zero (the released DOF is no longer an input).
            Ti[i, :] = -row / k_ii
            Ti[i, i] = 0.0
            K -= np.outer(row, row) / k_ii
        K[i, :] = 0.0
        K[:, i] = 0.0
        T = T @ Ti
    return K, T


def released_local_stiffness(
    pbar: Pbar, mat1: Mat1, L: float, pa: str, pb: str
) -> tuple[FloatArray, FloatArray]:
    """Local CBAR stiffness with PA/PB releases condensed: ``(K', T)``.

    The single source of the released local stiffness for assembly and every
    force-recovery path (``designs/cbar_pin_release_condensation.md`` D2).
    """
    K = local_stiffness(pbar, mat1, L)
    rel = release_indices(pa, pb)
    if not rel:
        return K, np.eye(K.shape[0])
    return condense_released_dofs(K, rel)


def element_stiffness_global(
    cbar: Cbar,
    grids: dict[int, Grid],
    pbars: dict[int, Pbar],
    mat1s: dict[int, Mat1],
) -> FloatArray:
    """12x12 element stiffness matrix in global coordinates: T.T @ K_local @ T."""
    pbar = pbars[cbar.pid]
    mat1 = mat1s[pbar.mid]

    ga = grids[cbar.ga]
    gb = grids[cbar.gb]
    ga_pos = np.array([ga.x, ga.y, ga.z])
    gb_pos = np.array([gb.x, gb.y, gb.z])
    L = float(np.linalg.norm(gb_pos - ga_pos))

    K_local, _ = released_local_stiffness(pbar, mat1, L, cbar.pa, cbar.pb)
    T = transform_matrix(cbar, grids)

    return T.T @ K_local @ T


def assemble_global_stiffness(bulk: BulkData) -> SparseMatrix:
    """Assemble the (6N x 6N) global stiffness matrix from every line element
    (CBAR, CROD, CONROD through the ``assembly/elements.py`` registry, #38) and
    every CBUSH."""
    # Local import: elements.py builds on this module's CBAR helpers.
    from sbeam.assembly.elements import iter_line_elements, line_element

    grid_index = {gid: i for i, gid in enumerate(sorted(bulk.grids.keys()))}
    n = 6 * len(grid_index)
    rows, cols, data = [], [], []

    for elem in iter_line_elements(bulk):
        le = line_element(elem, bulk)
        K_e = le.global_stiffness()
        dofs = node_dofs(le.ga, grid_index) + node_dofs(le.gb, grid_index)
        ii, jj = np.meshgrid(dofs, dofs, indexing="ij")
        rows.extend(ii.ravel())
        cols.extend(jj.ravel())
        data.extend(K_e.ravel())

    for cbush in bulk.cbushs.values():
        K_e = cbush_stiffness_global(cbush, bulk.grids, bulk.pbushs, bulk.cord2rs)
        dofs_a = node_dofs(cbush.ga, grid_index)
        dofs = dofs_a + node_dofs(cbush.gb, grid_index) if cbush.gb is not None else dofs_a
        ii, jj = np.meshgrid(dofs, dofs, indexing="ij")
        rows.extend(ii.ravel())
        cols.extend(jj.ravel())
        data.extend(K_e.ravel())

    return scipy.sparse.coo_matrix(
        (np.array(data, dtype=float), (np.array(rows), np.array(cols))),
        shape=(n, n),
    ).tocsr()


def cbush_local_stiffness(pbush: Pbush) -> FloatArray:
    """6×6 diagonal local stiffness matrix for a CBUSH element."""
    return np.diag([pbush.k1, pbush.k2, pbush.k3, pbush.k4, pbush.k5, pbush.k6])


def cbush_transform_matrix(
    cbush: Cbush, grids: dict[int, Grid], cord2rs: Optional[dict[int, Cord2r]] = None,
) -> FloatArray:
    """3×3 rotation matrix R for a CBUSH element: rows are the element axes in basic.

    MSC Nastran 2024.1 QRG PDF p.1379:

    * CID ≥ 0 "overrides GO and Xi.  Then the element x-axis is along T1, the element
      y-axis is along T2, and the element z-axis is along T3 of the CID coordinate
      system" (remark 3); CID 0 is basic.
    * CID blank, GA ≠ GB, v given: "the line AB is the element x-axis and the
      orientation vector v lies in the x-y plane" (remark 4).
    * CID blank, GA ≠ GB, no v: the line AB is the element x-axis (remark 5).  The parser
      allows this only for a PBUSH with K1 and K4 alone, so y and z carry no stiffness.

    A grounded or coincident CBUSH needs a CID (remark 6); the parser refuses one without.
    """
    if cbush.cid is not None:
        if cbush.cid == 0:
            return np.eye(3)
        if cord2rs is None:
            raise ValueError(f"CBUSH {cbush.eid}: CID={cbush.cid} needs the CORD2R table")
        return build_transform(cbush.cid, cord2rs).T

    if cbush.gb is None:
        raise ValueError(
            f"CBUSH {cbush.eid}: GB is blank, so CID must be specified (QRG p.1379 remark 6)")
    ga = grids[cbush.ga]
    gb = grids[cbush.gb]
    dx = np.array([gb.x - ga.x, gb.y - ga.y, gb.z - ga.z], dtype=float)
    L = float(np.linalg.norm(dx))
    if L < CBUSH_COINCIDENT:
        raise ValueError(
            f"CBUSH {cbush.eid}: GA and GB are closer than {CBUSH_COINCIDENT:g}, so CID "
            "must be specified (QRG p.1379 remark 6)")
    e_x = dx / L

    v = np.array([cbush.x1, cbush.x2, cbush.x3], dtype=float)
    v_perp = v - np.dot(v, e_x) * e_x
    norm_v = float(np.linalg.norm(v_perp))
    if not v.any():
        # No orientation: any y, z will do because only K1 and K4 are non-zero
        for candidate in ([0.0, 1.0, 0.0], [0.0, 0.0, 1.0]):
            vc = np.array(candidate)
            v_perp = vc - np.dot(vc, e_x) * e_x
            norm_v = float(np.linalg.norm(v_perp))
            if norm_v > 1e-6:
                break
    elif norm_v < 1e-9 * float(np.linalg.norm(v)):
        raise ValueError(
            f"CBUSH {cbush.eid}: the orientation vector is parallel to the line GA-GB")

    e_y = v_perp / norm_v
    e_z = np.cross(e_x, e_y)
    return np.array([e_x, e_y, e_z])


#: "If the distance between GA and GB is less than .0001 ... then CID must be specified"
#: (MSC Nastran 2024.1 QRG PDF p.1379, CBUSH remark 6)
CBUSH_COINCIDENT = 1.0e-4


def cbush_stiffness_global(
    cbush: Cbush, grids: dict[int, Grid], pbushs: dict[int, Pbush],
    cord2rs: Optional[dict[int, Cord2r]] = None,
) -> FloatArray:
    """Global stiffness contribution for a CBUSH element.

    Returns a 12×12 array for two-node elements or a 6×6 array for grounded
    (GB=None) elements. The assembly loop must branch on cbush.gb to scatter
    the correct shape into the global matrix.

    The spring of a two-node element sits at P = GA + S·(GB − GA), joined to each grid
    by a rigid link: "For noncoincident grids, internal rigid links connect the bush
    location to the grid locations" (MSC Nastran 2024.1 QRG PDF p.1381, remark 11).
    The spring sees the relative motion of the two link ends, u_P = u + θ × (P − grid),
    so a rigid-body motion of GA and GB gives no force (#97).
    """
    pbush = pbushs[cbush.pid]
    K6 = cbush_local_stiffness(pbush)
    R = cbush_transform_matrix(cbush, grids, cord2rs)
    T6 = block_diag(R, R)  # 6×6: two blocks for translational + rotational DOFs

    if cbush.gb is not None:
        # Two-node: assemble symmetric 12×12 spring-pair matrix then transform
        K12_local = np.block([[K6, -K6], [-K6, K6]])
        T12 = block_diag(R, R, R, R)
        K12 = T12.T @ K12_local @ T12
        # Rigid links GA→P and GB→P.  A zero arm is an exact identity, so coincident
        # grids are unchanged bit for bit
        E = block_diag(_rigid_link(grids[cbush.ga], cbush, grids),
                       _rigid_link(grids[cbush.gb], cbush, grids))
        return E.T @ K12 @ E
    else:
        # Grounded: only GA contributes — 6×6
        return T6.T @ K6 @ T6


def _cbush_spring_point(cbush: Cbush, grids: dict[int, Grid]) -> FloatArray:
    """Basic position of a two-node CBUSH's spring: GA + S·(GB − GA) (QRG p.1380 Fig. 9-20)."""
    assert cbush.gb is not None, "a grounded CBUSH has no spring arm"
    ga, gb = grids[cbush.ga], grids[cbush.gb]
    xa = np.array([ga.x, ga.y, ga.z], dtype=float)
    xb = np.array([gb.x, gb.y, gb.z], dtype=float)
    return xa + cbush.s * (xb - xa)


def _rigid_link(grid: Grid, cbush: Cbush, grids: dict[int, Grid]) -> FloatArray:
    """6×6 map from a grid's (u, θ) to the motion of the spring point P on a rigid link.

    u_P = u + θ × r = u − [r]× θ with r = P − grid; θ_P = θ.
    """
    r = _cbush_spring_point(cbush, grids) - np.array([grid.x, grid.y, grid.z], dtype=float)
    skew = np.array([[0.0, -r[2], r[1]], [r[2], 0.0, -r[0]], [-r[1], r[0], 0.0]])
    E = np.eye(6)
    E[0:3, 3:6] = -skew
    return E


def get_spc_dofs(
    bulk: BulkData, spc_sid: Optional[int], grid_index: dict[int, int]
) -> list[int]:
    """Return list of constrained global DOF indices for a given SPC SID.

    Also includes permanent SPCs from Grid.ps for all grids.
    Duplicates are handled by the caller (apply_spcs uses a set).
    """
    spc_dofs: list[int] = []

    # --- SPC cards ---
    for spc in (bulk.spcs.get(spc_sid, []) if spc_sid is not None else []):
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
    for spc1 in (bulk.spc1s.get(spc_sid, []) if spc_sid is not None else []):
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


def check_spc_enforced_displacements(bulk: BulkData, spc_sid: int) -> None:
    """Raise ValueError if any SPC in the active set specifies a non-zero enforced displacement.

    Non-zero D fields are parsed and stored but never applied to the RHS (Phase 1 limitation).
    Failing loudly here prevents silent wrong results.
    """
    violations = []
    for spc in bulk.spcs.get(spc_sid, []):
        if spc.d1 != 0.0:
            violations.append(f"SPC SID={spc.sid} GRID={spc.g1} C={spc.c1} D={spc.d1}")
        if spc.g2 is not None and spc.d2 != 0.0:
            violations.append(f"SPC SID={spc.sid} GRID={spc.g2} C={spc.c2} D={spc.d2}")
    if violations:
        detail = "; ".join(violations)
        raise ValueError(
            f"Non-zero enforced displacements are not supported in Phase 1 ({detail}). "
            "Set all SPC D fields to 0 or blank."
        )


def apply_spcs(
    K: Union[FloatArray, SparseMatrix], f: FloatArray, spc_dofs: list[int]
) -> tuple[Union[FloatArray, SparseMatrix], FloatArray, list[int]]:
    """Partition K and f to free DOFs only.

    Returns (K_free, f_free, free_dofs). K may be a dense ndarray or a sparse
    CSR matrix; the returned K_free matches the input type.
    """
    constrained = set(spc_dofs)
    free_dofs = [i for i in range(K.shape[0]) if i not in constrained]
    if scipy.sparse.issparse(K):
        K_free = K[free_dofs, :][:, free_dofs]
    else:
        K_free = K[np.ix_(free_dofs, free_dofs)]
    f_free = f[free_dofs]
    return K_free, f_free, free_dofs
