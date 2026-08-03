"""SOL 144 trim solve machinery (P13/DEF-R1 split from sol144.py).

The SUPORT Schur partition shared by both trim solves, a-set displacement
recovery from the trimmed free variables, and the determined and
over-determined (TRIMOBJ/TRIMCON null-space weighted-L2) trim solvers.
All names remain importable from ``sbeam.solver.sol144`` (facade).
"""

from typing import Optional

import numpy as np
import scipy.linalg

from sbeam.model.aero import Trimcon, Trimobj, Trimvar
from sbeam.types import FloatArray, LuFactor


def build_trim_schur(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_label_cols: list[int],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int], FloatArray, FloatArray]:
    """Build the trim-equilibrium operator shared by the determined and
    over-determined solves.

    Partitions K_eff = K_aa - q*Q_aa into l-set (non-SUPORT) and r-set (SUPORT).
    With u_r = 0, the r-set equilibrium is the trim equation in the free trim
    variables δ_free:

        schur_A @ delta_free = schur_b
        schur_A = K_rl @ K_ll^{-1} @ C_ax_l - C_ax_r          (n_r, n_free)
        schur_b = f_rhs_r - K_rl @ K_ll^{-1} @ f_rhs_l        (n_r,)

    where C_ax = q*Q_ax_a + M_ax_a is the combined aero + inertial sensitivity.

    Returns:
        (schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l)
    """
    n_a = K_aa.shape[0]
    r_idx = list(suport_local)
    l_idx = [i for i in range(n_a) if i not in set(r_idx)]

    K_eff = K_aa - q * Q_aa
    K_ll = K_eff[np.ix_(l_idx, l_idx)]
    K_rl = K_eff[np.ix_(r_idx, l_idx)]

    # Combined aero + inertial sensitivity for free columns only
    C_ax_l = (q * Q_ax_a[np.ix_(l_idx, free_label_cols)]
              + M_ax_a[np.ix_(l_idx, free_label_cols)])  # (n_l, n_free)
    C_ax_r = (q * Q_ax_a[np.ix_(r_idx, free_label_cols)]
              + M_ax_a[np.ix_(r_idx, free_label_cols)])  # (n_r, n_free)

    f_rhs_l = f_rhs_a[l_idx]
    f_rhs_r = f_rhs_a[r_idx]

    K_ll_lu = scipy.linalg.lu_factor(K_ll)

    Kinv_f = scipy.linalg.lu_solve(K_ll_lu, f_rhs_l)            # (n_l,)
    Kinv_C = scipy.linalg.lu_solve(K_ll_lu, C_ax_l)             # (n_l, n_free)

    schur_A = K_rl @ Kinv_C - C_ax_r                            # (n_r, n_free)
    schur_b = f_rhs_r - K_rl @ Kinv_f                           # (n_r,)

    return schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l


def recover_u_a(
    K_ll_lu: LuFactor,
    C_ax_l: FloatArray,
    f_rhs_l: FloatArray,
    delta_free_arr: FloatArray,
    l_idx: list[int],
    n_a: int,
) -> FloatArray:
    """Recover the a-set displacement from the trimmed free variables (u_r = 0)."""
    u_l = scipy.linalg.lu_solve(K_ll_lu, C_ax_l @ delta_free_arr + f_rhs_l)
    u_a = np.zeros(n_a)
    for li, val in zip(l_idx, u_l):
        u_a[li] = val
    return u_a


def solve_trim_determined(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_label_cols: list[int],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int]]:
    """Schur-complement trim solve for the determined case (n_free == n_suport).

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    n_a = K_aa.shape[0]
    schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l = build_trim_schur(
        K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q, suport_local, free_label_cols)

    delta_free_arr = scipy.linalg.solve(schur_A, schur_b)        # (n_free,)

    u_a = recover_u_a(K_ll_lu, C_ax_l, f_rhs_l, delta_free_arr, l_idx, n_a)
    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


def solve_trim_overdetermined(
    K_aa: FloatArray,
    Q_aa: FloatArray,
    Q_ax_a: FloatArray,
    M_ax_a: FloatArray,
    f_rhs_a: FloatArray,
    q: float,
    suport_local: list[int],
    free_labels: list[str],
    free_label_cols: list[int],
    trimobj: Optional[Trimobj],
    trimcons: list[Trimcon],
    trimvars: dict[int, Trimvar],
) -> tuple[FloatArray, FloatArray, LuFactor, list[int], list[int]]:
    """Over-determined trim solve (n_free > n_suport): redundant controls.

    The trim equilibrium ``schur_A @ δ = schur_b`` is ``n_suport`` equations in
    ``n_free`` unknowns (under-determined as an equality system).  The solution is
    made unique by minimising the weighted-L2 ``TRIMOBJ`` objective

        min_δ  Σ_k  w_k · δ_k²        (k over TRIMOBJ labels; w_k its weight)

    subject to
        * equality:   schur_A @ δ = schur_b          (trim equilibrium),
        * inequality: TRIMCON  (δ_label ≤ rhs  or  δ_label ≥ rhs),
        * bounds:     TRIMVAR  lb ≤ δ_label ≤ ub.

    The equilibrium equality is eliminated by a **null-space reduction** rather
    than handed to the optimiser as a stiff constraint: ``schur_A`` carries
    structural-force magnitudes O(10³) that swamp the O(0.1) trim variables and
    defeat SLSQP's line search.  Writing

        δ = δ_p + N · z          (δ_p = least-norm equilibrium solution,
                                  N = null(schur_A), so schur_A·δ ≡ schur_b)

    turns the problem into a small, well-scaled convex QP in the redundancy
    coordinate ``z`` with only the TRIMCON/TRIMVAR bounds (now linear in ``z``).
    The convex objective makes the optimum initial-guess insensitive (KC6); the
    TRIMVAR ``init`` only seeds the warm start.

    Returns:
        (u_a, delta_free, K_ll_lu, l_idx, r_idx)
    """
    import scipy.optimize

    n_a = K_aa.shape[0]
    n_free = len(free_labels)
    schur_A, schur_b, K_ll_lu, l_idx, r_idx, C_ax_l, f_rhs_l = build_trim_schur(
        K_aa, Q_aa, Q_ax_a, M_ax_a, f_rhs_a, q, suport_local, free_label_cols)

    label_to_idx = {lbl: i for i, lbl in enumerate(free_labels)}

    # Weighted-L2 objective from TRIMOBJ (default weight 1.0 on every free var
    # when no TRIMOBJ label matches, so the solve is always well-posed).
    weights = np.ones(n_free)
    if trimobj is not None and trimobj.labels:
        w_obj = np.zeros(n_free)
        matched = False
        for lbl, w in zip(trimobj.labels, trimobj.weights):
            if lbl in label_to_idx:
                w_obj[label_to_idx[lbl]] = w
                matched = True
        if matched:
            weights = w_obj

    # Particular (least-norm) equilibrium solution and the null-space basis.
    delta_p, *_ = np.linalg.lstsq(schur_A, schur_b, rcond=None)
    _u, sv, vt = np.linalg.svd(schur_A)
    tol = max(schur_A.shape) * np.finfo(float).eps * (sv[0] if sv.size else 0.0)
    rank = int((sv > tol).sum())
    N = vt[rank:].T.conj()                      # (n_free, n_free - rank)
    nz = N.shape[1]

    # TRIMVAR bounds and per-variable initial guess (defaults: unbounded, 0).
    lb = np.full(n_free, -np.inf)
    ub = np.full(n_free, np.inf)
    delta_init = np.zeros(n_free)
    for tv in (trimvars or {}).values():
        if tv.label in label_to_idx:
            i = label_to_idx[tv.label]
            lb[i] = tv.lb
            ub[i] = tv.ub
            delta_init[i] = tv.init

    if nz == 0:
        # No redundancy left after the equilibrium constraint — δ is determined.
        delta_free_arr = delta_p
    else:
        def objective(z: FloatArray) -> float:
            d = delta_p + N @ z
            return float(np.sum(weights * d * d))

        def objective_grad(z: FloatArray) -> FloatArray:
            d = delta_p + N @ z
            return 2.0 * (N.T @ (weights * d))

        constraints = []
        # TRIMCON inequalities (linear in z).
        for tc in (trimcons or []):
            if tc.label not in label_to_idx:
                continue
            i = label_to_idx[tc.label]
            if tc.sense == "LE":      # δ_i ≤ rhs  →  rhs − δ_i ≥ 0
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i, r=tc.rhs: r - (delta_p[i] + N[i] @ z)),
                    'jac': (lambda z, i=i: -N[i]),
                })
            else:                     # GE: δ_i ≥ rhs  →  δ_i − rhs ≥ 0
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i, r=tc.rhs: (delta_p[i] + N[i] @ z) - r),
                    'jac': (lambda z, i=i: N[i]),
                })
        # TRIMVAR bounds → linear inequalities in z.
        for i in range(n_free):
            if np.isfinite(ub[i]):
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i: ub[i] - (delta_p[i] + N[i] @ z)),
                    'jac': (lambda z, i=i: -N[i]),
                })
            if np.isfinite(lb[i]):
                constraints.append({
                    'type': 'ineq',
                    'fun': (lambda z, i=i: (delta_p[i] + N[i] @ z) - lb[i]),
                    'jac': (lambda z, i=i: N[i]),
                })

        # Warm start: project the TRIMVAR init guess onto the redundancy space.
        z0, *_ = np.linalg.lstsq(N, delta_init - delta_p, rcond=None)
        res = scipy.optimize.minimize(
            objective, z0, jac=objective_grad, method='SLSQP',
            constraints=constraints, options={'ftol': 1e-14, 'maxiter': 500},
        )
        if not res.success:
            raise ValueError(
                "Over-determined trim could not satisfy the TRIMCON/TRIMVAR "
                f"bounds: {res.message}")
        delta_free_arr = delta_p + N @ res.x

    u_a = recover_u_a(K_ll_lu, C_ax_l, f_rhs_l, delta_free_arr, l_idx, n_a)
    return u_a, delta_free_arr, K_ll_lu, l_idx, r_idx


