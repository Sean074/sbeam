"""Shared RBE3/RBAR-then-SPC a-set reduction (Step 59).

Single owner of the g-set → a-set reduction previously duplicated across
``sol144._build_qaa_aset`` / ``sol144._compute_aset_data``, ``sol103.run_sol103``,
and ``maneuver_qs._assemble_operators``.  The reduction is two stages:

1. RBE3/RBE2/RBAR transformation ``T`` (n_g × n_red) eliminates dependent DOFs
   (``build_rbe3_transformation``); when no rigid elements exist T is identity.
2. SPC partition removes constrained DOFs from the reduced set, leaving the
   free a-set.

All downstream solvers (SOL 103 modes, SOL 144 trim/divergence, Phase G0
transient maneuver) must share this path so their a-set indices are identical.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Union, overload

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import get_spc_dofs
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.types import FloatArray, SparseMatrix


@dataclass
class AsetReduction:
    """A-set partition data for one (bulk, spc_sid) combination.

    Attributes:
        T:          (n_g, n_red) RBE3/RBAR transformation, reduced → full DOF
                    space.  Identity when no rigid elements are present.
        dep_dofs:   g-set DOF indices eliminated by T ([] when none).
        red_dofs:   g-set DOF index for each reduced-set row (range(n_g) when
                    no dependent DOFs).
        free_local: a-set indices into the reduced set (SPC DOFs removed).
        free_dofs:  a-set indices into the g-set.
    """
    T: FloatArray
    dep_dofs: list[int]
    red_dofs: list[int]
    free_local: list[int]
    free_dofs: list[int]

    @property
    def n_red(self) -> int:
        """Number of reduced-set DOFs (T's column count)."""
        return len(self.red_dofs)

    @overload
    def reduce_matrix(self, A: FloatArray, dense: bool = ...) -> FloatArray: ...
    @overload
    def reduce_matrix(self, A: SparseMatrix, dense: Literal[True]) -> FloatArray: ...
    @overload
    def reduce_matrix(
        self, A: SparseMatrix, dense: bool = ...
    ) -> Union[FloatArray, SparseMatrix]: ...

    def reduce_matrix(
        self, A: Union[FloatArray, SparseMatrix], dense: bool = False
    ) -> Union[FloatArray, SparseMatrix]:
        """Reduce a square (n_g, n_g) matrix to the a-set.

        Without dependent DOFs the input's sparsity is preserved (matching
        apply_spcs, so SOL 103's sparse eigsh path is unchanged); pass
        ``dense=True`` to force a dense result (SOL 144 solves dense systems).
        With dependent DOFs ``T.T @ A @ T`` densifies regardless (NumPy @
        semantics, same as the sol101 precedent).
        """
        if self.dep_dofs:
            A_red: Union[FloatArray, SparseMatrix] = self.T.T @ A @ self.T
            if not isinstance(A_red, np.ndarray):
                A_red = A_red.toarray()
            return A_red[np.ix_(self.free_local, self.free_local)]
        if not isinstance(A, np.ndarray):
            if dense:
                return A.toarray()[np.ix_(self.free_local, self.free_local)]
            return A[self.free_local, :][:, self.free_local]
        return A[np.ix_(self.free_local, self.free_local)]

    def reduce_rect(self, A: FloatArray) -> FloatArray:
        """Reduce a rectangular (n_g, k) column block to a-set rows (e.g. Q_ax, M_ax)."""
        A_red = (self.T.T @ A) if self.dep_dofs else A
        return A_red[self.free_local, :]

    def reduce_vector(self, f: FloatArray) -> FloatArray:
        """Reduce a (n_g,) load vector to the a-set."""
        f_red = (self.T.T @ f) if self.dep_dofs else f
        return f_red[self.free_local]

    def expand_to_g(self, u_a: FloatArray) -> FloatArray:
        """Expand an a-set displacement vector to the full g-set (see expand_to_g)."""
        return expand_to_g(u_a, self.T, self.free_local, self.n_red)


def reduce_to_aset(
    bulk: BulkData, grid_index: dict[int, int], spc_sid: Optional[int]
) -> AsetReduction:
    """Compute the RBE3+SPC a-set partition for a model.

    Args:
        bulk:       Parsed BulkData.
        grid_index: {gid: i} mapping from build_grid_index.
        spc_sid:    SPC set ID (may be None — no SPCs applied when None).

    Returns:
        AsetReduction with the transformation and index sets; use its
        reduce_matrix / reduce_rect / reduce_vector / expand_to_g methods to
        move quantities between the g-set and the a-set.
    """
    n_g = 6 * len(grid_index)
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = [red_map[d] for d in spc_dofs_full if d not in dep_set]
    else:
        red_dofs = list(range(n_g))
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs_local = spc_dofs_full

    constrained = set(spc_dofs_local)
    free_local = [i for i in range(len(red_dofs)) if i not in constrained]
    free_dofs = [red_dofs[i] for i in free_local]
    return AsetReduction(
        T=T, dep_dofs=dep_dofs, red_dofs=red_dofs,
        free_local=free_local, free_dofs=free_dofs,
    )


def expand_to_g(
    u_a: FloatArray,
    T: FloatArray,
    free_local: list[int],
    n_red: int,
) -> FloatArray:
    """Expand an a-set displacement vector to the full g-set via the RBE3/RBAR T matrix.

    The aeroelastic solvers work on the a-set (post-SPC, post-RBAR). When the
    result is fed back into `aero.g_slope @ u` or `_compute_aero_forces`, the
    RBAR slave DOFs must move with their masters; a bare index scatter leaves
    the slaves at zero and corrupts the structural normalwash on every
    RBAR-attached grid.

    Args:
        u_a:        (n_a,) a-set displacement.
        T:          (n_g, n_red) RBE3/RBAR transformation from build_rbe3_transformation.
        free_local: list[int] of a-set indices in the reduced set (length n_a).
        n_red:      number of reduced-set DOFs (T's column count).

    Returns:
        (n_g,) full g-set displacement with RBAR slaves driven by their masters.
    """
    u_red = np.zeros(n_red)
    for local_i, red_i in enumerate(free_local):
        u_red[red_i] = u_a[local_i]
    return T @ u_red
