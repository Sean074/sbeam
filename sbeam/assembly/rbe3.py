"""RBE3 constraint transformation matrix."""

import numpy as np

from sbeam.model.bulk_data import BulkData


def build_rbe3_transformation(bulk: BulkData, grid_index: dict) -> tuple:
    """Build the RBE3 DOF transformation matrix T.

    Returns (T, dep_dofs, red_dofs) where:
      T        : np.ndarray shape (n_dof, n_red) — maps reduced → full DOF space
      dep_dofs : list[int] — global DOF indices eliminated by RBE3
      red_dofs : list[int] — remaining DOF indices in ascending order

    If no RBE3 elements are present, returns (eye(n_dof), [], list(range(n_dof))).
    """
    n_dof = 6 * len(grid_index)

    if not bulk.rbe3s:
        return np.eye(n_dof), [], list(range(n_dof))

    # Start from identity; rows for dependent DOFs will be overwritten.
    T_full = np.eye(n_dof)
    dep_set: set = set()

    for rbe3 in bulk.rbe3s.values():
        if rbe3.refgrid not in grid_index:
            continue
        ref_idx = grid_index[rbe3.refgrid]

        for d_char in str(rbe3.refc):
            d = int(d_char) - 1  # 0-based offset within a grid's 6 DOFs
            p = 6 * ref_idx + d  # global index of the dependent DOF

            # Collect (weight, grid_id) for independent grids that include DOF d.
            pairs: list = []
            for weight, dofs_str, grids in rbe3.wt_gc:
                if d_char in str(dofs_str):
                    for gid in grids:
                        if gid in grid_index:
                            pairs.append((weight, gid))

            if not pairs:
                continue

            W = sum(w for w, _ in pairs)
            if W == 0.0:
                continue

            T_full[p, :] = 0.0
            for weight, gid in pairs:
                q = 6 * grid_index[gid] + d
                T_full[p, q] += weight / W

            dep_set.add(p)

    dep_dofs = sorted(dep_set)
    red_dofs = [i for i in range(n_dof) if i not in dep_set]
    T = T_full[:, red_dofs]
    return T, dep_dofs, red_dofs
