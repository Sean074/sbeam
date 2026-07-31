"""Shared type aliases for sbeam.

All physical quantities in sbeam are dense ``numpy`` arrays of 64-bit floats —
displacement vectors, stiffness/mass matrices, aerodynamic influence
coefficients, mode shapes.  ``FloatArray`` is the single alias used for every
one of them, so a bare (and therefore unparameterised) ``np.ndarray`` never
appears in a signature.

The aliases deliberately do NOT encode shape or rank: a 1-D load vector and a
2-D AIC matrix are both ``FloatArray``.  ``numpy`` shape typing is not mature
enough to express the FEA index conventions usefully, and the DOF ordering that
actually matters ([Tx, Ty, Tz, Rx, Ry, Rz] per grid) is documented in each
function's docstring and shape comment instead.

Usage::

    from sbeam.types import FloatArray

    def build_skj(boxes: list[AeroBox]) -> FloatArray:
        ...
"""

from typing import Tuple, Union

import numpy as np
import numpy.typing as npt
import scipy.sparse

#: Dense float64 array — the type of every physical vector/matrix in sbeam.
FloatArray = npt.NDArray[np.float64]

#: Dense complex128 array — eigenvalues/eigenvectors of a non-symmetric system
#: (divergence roots), before the real part is taken.
ComplexArray = npt.NDArray[np.complex128]

#: Dense integer array — DOF index maps, connectivity, box-ID lists.
IntArray = npt.NDArray[np.int_]

#: Dense boolean array — DOF masks (free/fixed, a-set/o-set partitions).
BoolArray = npt.NDArray[np.bool_]

#: Assembled sparse global matrix (K_gg, M_gg).
#:
#: scipy is mid-migration from the ``spmatrix`` family to the ``sparray``
#: family: ``coo_matrix(...).tocsr()`` is annotated as returning ``csr_array``
#: even though the runtime object is a ``csr_matrix``.  The union keeps the
#: annotation honest for callers under either scipy behaviour — every consumer
#: in sbeam only ever does ``@``, ``.toarray()``, or slicing, which both
#: families support identically.
SparseMatrix = Union[scipy.sparse.csr_matrix, scipy.sparse.csr_array]

#: The ``(lu, piv)`` pair returned by ``scipy.linalg.lu_factor`` and consumed by
#: ``scipy.linalg.lu_solve``.  Passed around whenever one factorisation is reused
#: for many right-hand sides (trim Schur complement, stability derivatives).
LuFactor = Tuple[FloatArray, IntArray]

__all__ = ["FloatArray", "ComplexArray", "IntArray", "BoolArray",
           "SparseMatrix", "LuFactor"]
