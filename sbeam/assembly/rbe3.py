"""RBE3/RBE2/RBAR constraint transformation matrix."""

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.types import FloatArray


def _build_rigid_transform(
    bulk: BulkData, grid_index: dict[int, int]
) -> tuple[FloatArray, dict[int, str]]:
    """Full (n_dof, n_dof) transform plus {dependent g-DOF: owning-element label}.

    The single derivation behind both ``build_rbe3_transformation`` (which drops
    the owner map) and ``dep_dof_owners`` (which keeps only the owner map), so the
    two can never disagree about which DOFs a rigid element eliminates.  The
    labels exist so an SPC landing on a dependent DOF can name the element that
    owns it (DEF-M9) instead of being silently discarded.
    """
    n_dof = 6 * len(grid_index)

    if not bulk.rbe3s and not bulk.rbe2s and not bulk.rbars:
        return np.eye(n_dof), {}

    # Start from identity; rows for dependent DOFs will be overwritten.
    T_full = np.eye(n_dof)
    dep_owner: dict[int, str] = {}

    class _DepSet:
        """``dep_set`` shim: ``add`` records the owner, membership tests unchanged."""
        owner_label = ""

        def add(self, dof: int) -> None:
            dep_owner[dof] = self.owner_label

        def __contains__(self, dof: object) -> bool:
            return dof in dep_owner

    dep_set = _DepSet()

    # RBE3 formulation: each dependent DOF is a weighted average of the *same-numbered* DOF
    # at the independent grids.  Rotation-to-translation coupling across an offset (lever-arm
    # kinematics) is NOT applied.  This is the common simplified formulation and is exact when
    # the independent grids are collocated or the reference point moves rigidly with the
    # independent set.  Use RBAR for kinematically exact rigid connections with an offset.
    for rbe3 in bulk.rbe3s.values():
        if rbe3.refgrid not in grid_index:
            continue
        ref_idx = grid_index[rbe3.refgrid]

        for d_char in str(rbe3.refc):
            d = int(d_char) - 1  # 0-based offset within a grid's 6 DOFs
            p = 6 * ref_idx + d  # global index of the dependent DOF

            # Collect (weight, grid_id) for independent grids that include DOF d.
            pairs: list[tuple[float, int]] = []
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

            dep_set.owner_label = f"RBE3 {rbe3.eid} (REFGRID {rbe3.refgrid}, C{d + 1})"
            dep_set.add(p)

    # RBE2: dependent grid DOFs follow GN via rigid-body kinematics (lever-arm).
    # u_GM[d] = R[d, :] @ u_GN  where R encodes the offset r_GM - r_GN.
    # When the offset is zero R reduces to identity, recovering the direct-copy case.
    for rbe2 in bulk.rbe2s.values():
        if rbe2.gn not in grid_index:
            continue
        indep_idx = grid_index[rbe2.gn]
        gn_g = bulk.grids[rbe2.gn]
        for gm_id in rbe2.gm:
            if gm_id not in grid_index:
                continue
            dep_idx = grid_index[gm_id]
            gm_g = bulk.grids[gm_id]
            dx = gm_g.x - gn_g.x
            dy = gm_g.y - gn_g.y
            dz = gm_g.z - gn_g.z
            R = np.array([
                [1, 0, 0,   0,  dz, -dy],
                [0, 1, 0, -dz,   0,  dx],
                [0, 0, 1,  dy, -dx,   0],
                [0, 0, 0,   1,   0,   0],
                [0, 0, 0,   0,   1,   0],
                [0, 0, 0,   0,   0,   1],
            ], dtype=float)
            for d_char in str(rbe2.cm):
                d = int(d_char) - 1
                dep_dof = 6 * dep_idx + d
                T_full[dep_dof, :] = 0.0
                for k in range(6):
                    T_full[dep_dof, 6 * indep_idx + k] = R[d, k]
                dep_set.owner_label = f"RBE2 {rbe2.eid} (GM {gm_id}, C{d + 1})"
                dep_set.add(dep_dof)

    # GN of an RBE2 must not itself be a dependent DOF of another constraint element.
    for rbe2 in bulk.rbe2s.values():
        if rbe2.gn not in grid_index:
            continue
        indep_idx = grid_index[rbe2.gn]
        for d_char in str(rbe2.cm):
            d = int(d_char) - 1
            if (6 * indep_idx + d) in dep_set:
                raise ValueError(
                    f"RBE2 {rbe2.eid}: GN={rbe2.gn} DOF {d_char} is a dependent DOF "
                    f"of another constraint element"
                )

    # RBAR: all 6 DOFs at GB depend on GA via rigid body kinematics.
    # u_B = R @ u_A where R encodes the lever-arm effect of the offset d = r_GB - r_GA.
    for rbar in bulk.rbars.values():
        if rbar.ga not in grid_index or rbar.gb not in grid_index:
            continue
        ga_idx = grid_index[rbar.ga]
        gb_idx = grid_index[rbar.gb]
        ga_g = bulk.grids[rbar.ga]
        gb_g = bulk.grids[rbar.gb]
        dx = gb_g.x - ga_g.x
        dy = gb_g.y - ga_g.y
        dz = gb_g.z - ga_g.z
        R = np.array([
            [1, 0, 0,   0,  dz, -dy],
            [0, 1, 0, -dz,   0,  dx],
            [0, 0, 1,  dy, -dx,   0],
            [0, 0, 0,   1,   0,   0],
            [0, 0, 0,   0,   1,   0],
            [0, 0, 0,   0,   0,   1],
        ], dtype=float)
        for d in range(6):
            dep_dof = 6 * gb_idx + d
            T_full[dep_dof, :] = 0.0
            for k in range(6):
                T_full[dep_dof, 6 * ga_idx + k] = R[d, k]
            dep_set.owner_label = f"RBAR {rbar.eid} (GB {rbar.gb}, C{d + 1})"
            dep_set.add(dep_dof)

    # GA of an RBAR must not be a dependent DOF of another constraint element.
    for rbar in bulk.rbars.values():
        if rbar.ga not in grid_index:
            continue
        ga_idx = grid_index[rbar.ga]
        for d in range(6):
            if (6 * ga_idx + d) in dep_set:
                raise ValueError(
                    f"RBAR {rbar.eid}: GA={rbar.ga} DOF {d+1} is a dependent DOF "
                    f"of another constraint element"
                )

    return T_full, dep_owner


def build_rbe3_transformation(
    bulk: BulkData, grid_index: dict[int, int]
) -> tuple[FloatArray, list[int], list[int]]:
    """Build the RBE3/RBE2/RBAR DOF transformation matrix T.

    Returns (T, dep_dofs, red_dofs) where:
      T        : FloatArray shape (n_dof, n_red) — maps reduced → full DOF space
      dep_dofs : list[int] — global DOF indices eliminated by RBE3, RBE2, or RBAR
      red_dofs : list[int] — remaining DOF indices in ascending order

    If no RBE3, RBE2, or RBAR elements are present, returns (eye(n_dof), [], list(range(n_dof))).
    """
    n_dof = 6 * len(grid_index)
    T_full, dep_owner = _build_rigid_transform(bulk, grid_index)
    dep_dofs = sorted(dep_owner)
    red_dofs = [i for i in range(n_dof) if i not in dep_owner]
    return T_full[:, red_dofs], dep_dofs, red_dofs


def dep_dof_owners(bulk: BulkData, grid_index: dict[int, int]) -> dict[int, str]:
    """{dependent g-set DOF: label of the rigid element that eliminates it}.

    Same derivation as ``build_rbe3_transformation``'s ``dep_dofs`` — that
    function's list is literally ``sorted()`` of this dict's keys — so the two
    cannot drift.  Used only on the error path of ``reduce_to_aset``, where an
    SPC has been found on a dependent DOF and the message needs to name the
    owning element.
    """
    return _build_rigid_transform(bulk, grid_index)[1]
