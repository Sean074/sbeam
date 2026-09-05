"""Shared dense linear-algebra helpers.

``estimate_cond_1norm`` replaces the former full-SVD ``np.linalg.cond`` calls
(DEF-R6): given (or computing once) an LU factorization, LAPACK ``gecon``
estimates the reciprocal 1-norm condition in O(n²), and the factorization is
returned so callers solve with it instead of refactorizing.
"""

import warnings
from typing import Optional

import numpy as np
from scipy.linalg import LinAlgWarning, lapack, lu_factor

from sbeam.types import FloatArray, LuFactor


def estimate_cond_1norm(
    a: FloatArray, lu_piv: Optional[LuFactor] = None
) -> tuple[float, LuFactor]:
    """1-norm condition estimate of a square matrix via LU + LAPACK ``gecon``.

    The estimate is within a small factor of the true 1-norm condition number
    (and differs from the 2-norm SVD value by at most a factor n).  Returns
    ``(cond, lu_piv)``; a singular matrix yields ``cond = inf`` rather than
    raising, so callers keep their own threshold/raise behaviour.
    """
    if lu_piv is None:
        with warnings.catch_warnings():
            # lu_factor warns (LinAlgWarning) on an exactly singular matrix;
            # gecon then reports rcond = 0 → cond = inf, which is the signal
            # callers act on — the warning is redundant noise here.
            warnings.simplefilter("ignore", LinAlgWarning)
            lu_piv = lu_factor(a)
    anorm = float(np.linalg.norm(a, 1))
    # LAPACK wrappers are generated at runtime; getattr keeps pyright quiet.
    dgecon = getattr(lapack, "dgecon")
    rcond, info = dgecon(lu_piv[0], anorm, norm="1")
    cond = float("inf") if (info != 0 or rcond == 0.0) else 1.0 / float(rcond)
    return cond, lu_piv
