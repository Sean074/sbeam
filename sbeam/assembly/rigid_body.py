"""Geometric rigid-body displacement vectors on the g-set.

THE single derivation of the rigid-body geometry in sbeam.  Two consumers build
on it and neither re-derives it:

  * ``solver.modal_basis.build_rigid_modes`` — restricts to the a-set (with the
    RBE3/RBAR rigid-body-exactness round-trip check) to give ``Phi_r``, the
    rigid partition of the free-free maneuver basis (Step 61);
  * ``solver.sol144.build_inertial_cols`` — forms the inertia-relief columns
    ``M_ax = -M_gg Phi_r_g`` (Q4 / DEF-M3).

Keeping the primitive here rather than in ``modal_basis`` is what lets both use
it: ``modal_basis`` imports ``sol144``, so ``sol144`` cannot import back.

A rigid-body vector about a reference point ``ref`` is, per grid ``i`` with
``r_i = pos_i - ref``:

    translation along unit axis ``a``:   u_i = a          theta_i = 0
    rotation    about  unit axis ``a``:  u_i = a x r_i    theta_i = a

All positions are basic (CID 0), matching every other internal operator.
"""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.types import FloatArray


def build_rigid_vectors_g(
    bulk: BulkData,
    grid_index: dict[int, int],
    rigid_dofs: list[int],
    ref_pos: FloatArray,
) -> FloatArray:
    """Unit rigid-body displacement vectors on the full g-set.

    Args:
        bulk:       parsed model (grid positions, basic CID 0).
        grid_index: {gid: i} — the same ordering every g-set operator uses.
        rigid_dofs: rigid DOF components 1-6; column k corresponds to
                    ``rigid_dofs[k]``.  1-3 are translations along x/y/z,
                    4-6 rotations about x/y/z.
        ref_pos:    reference point in basic coordinates (rotation columns only;
                    translation columns are independent of it).

    Returns:
        (6 * n_grid, len(rigid_dofs)) rigid-body basis on the g-set.

    Raises:
        ValueError: if a requested DOF component is outside 1-6.
    """
    n_g = 6 * len(grid_index)
    ref = np.asarray(ref_pos, dtype=float)
    phi = np.zeros((n_g, len(rigid_dofs)))

    for col, dof in enumerate(rigid_dofs):
        if not 1 <= dof <= 6:
            raise ValueError(
                f"build_rigid_vectors_g: rigid DOF must be 1-6; got {dof}")
        if dof <= 3:
            for i in grid_index.values():
                phi[6 * i + (dof - 1), col] = 1.0
        else:
            axis = np.zeros(3)
            axis[dof - 4] = 1.0
            for gid, i in grid_index.items():
                g = bulk.grids[gid]
                r = np.array([g.x, g.y, g.z]) - ref
                phi[6 * i: 6 * i + 3, col] = np.cross(axis, r)
                phi[6 * i + 3: 6 * i + 6, col] = axis

    return phi
