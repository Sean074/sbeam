"""SOL 103 normal modes solver."""

import warnings

import numpy as np
import scipy.linalg
import scipy.sparse
import scipy.sparse.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import SubcaseControl
from sbeam.assembly.stiffness import (
    assemble_global_stiffness,
    get_spc_dofs,
    apply_spcs,
    check_spc_enforced_displacements,
)
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.rbe3 import build_rbe3_transformation
from sbeam.results.results import Sol103Result


_DENSE_THRESHOLD = 1200  # n_free <= this → use dense eigh (200 elements × 6 DOFs)


def solve_modes(K_free, M_free, eigrl, force_dense: bool = False) -> tuple:
    """Solve generalised eigenvalue problem K phi = lambda M phi.

    Returns (frequencies_hz, eigenvectors) where eigenvectors has shape
    (n_free_dofs, n_modes) normalised according to eigrl.norm.

    K_free and M_free may be sparse CSR matrices or dense ndarrays.
    force_dense=True bypasses eigsh (required for free-free models where K is
    singular and the shift-invert factorisation would fail).
    """
    n = K_free.shape[0]
    nd = eigrl.nd if eigrl.nd is not None else n
    nd = min(nd, n)

    # Use sparse eigsh only when the model is large enough to benefit and K is
    # well-conditioned (SPCs applied). Models at or below the old 200-element
    # limit always use the dense path for zero regression risk.
    use_dense = (
        force_dense
        or not scipy.sparse.issparse(K_free)
        or n <= _DENSE_THRESHOLD
        or nd >= n  # eigsh requires k < n; fall back to eigh for all modes
    )

    if use_dense:
        K_arr = K_free.toarray() if scipy.sparse.issparse(K_free) else K_free
        M_arr = M_free.toarray() if scipy.sparse.issparse(M_free) else M_free
        return _solve_modes_dense(K_arr, M_arr, nd, eigrl.norm)
    else:
        return _solve_modes_sparse(K_free, M_free, nd, n, eigrl.norm)


def _solve_modes_dense(K_arr: np.ndarray, M_arr: np.ndarray, nd: int, norm: str) -> tuple:
    """Dense generalised eigensolver (scipy.linalg.eigh).

    scipy.linalg.eigh solves K x = lambda M x, returning eigenvalues in ascending order.
    With b=M_arr the returned eigenvectors are M-normalised: phi^T M phi = I.
    When rho=0 and CONM2 has no rotational inertia, zero-mass DOFs make M singular.
    Tikhonov regularisation adds a tiny mass to those DOFs only; artificial modes
    appear at >> 1e6 Hz and never contaminate the first nd physical results.
    """
    diag_M = np.diag(M_arr)
    zero_mass = diag_M == 0.0
    if zero_mass.any():
        nonzero_vals = diag_M[~zero_mass]
        eps_m = (nonzero_vals.max() if nonzero_vals.size else 1.0) * 1e-12
        M_solve = M_arr.copy()
        M_solve[np.diag_indices_from(M_solve)] = np.where(zero_mass, eps_m, diag_M)
        eigenvalues, eigenvectors = scipy.linalg.eigh(K_arr, b=M_solve)
    else:
        eigenvalues, eigenvectors = scipy.linalg.eigh(K_arr, b=M_arr)

    eigenvalues = eigenvalues[:nd]
    eigenvectors = eigenvectors[:, :nd]
    return _postprocess_modes(eigenvalues, eigenvectors, norm)


def _solve_modes_sparse(K_csr, M_csr, nd: int, n: int, norm: str) -> tuple:
    """Sparse generalised eigensolver (scipy.sparse.linalg.eigsh, shift-invert σ=0).

    Falls back to dense eigh on ArpackNoConvergence.
    """
    # Tikhonov regularisation for zero-mass DOFs on sparse M
    diag_M = M_csr.diagonal()
    zero_mass = diag_M == 0.0
    if zero_mass.any():
        nonzero_vals = diag_M[~zero_mass]
        eps_m = (nonzero_vals.max() if nonzero_vals.size else 1.0) * 1e-12
        M_solve = M_csr.copy()
        M_solve.setdiag(np.where(zero_mass, eps_m, diag_M))
    else:
        M_solve = M_csr

    k = min(nd, n - 1)  # eigsh requires k < n
    try:
        eigenvalues, eigenvectors = scipy.sparse.linalg.eigsh(
            K_csr, k=k, M=M_solve, sigma=0.0, which="LM"
        )
        sort_idx = np.argsort(eigenvalues)
        eigenvalues = eigenvalues[sort_idx]
        eigenvectors = eigenvectors[:, sort_idx]
    except scipy.sparse.linalg.ArpackNoConvergence:
        warnings.warn("eigsh failed to converge; falling back to dense eigh for this model")
        return _solve_modes_dense(K_csr.toarray(), M_solve.toarray(), nd, norm)

    return _postprocess_modes(eigenvalues, eigenvectors, norm)


def _postprocess_modes(eigenvalues: np.ndarray, eigenvectors: np.ndarray, norm: str) -> tuple:
    """Convert eigenvalues to Hz and apply MAX normalisation if requested."""
    freqs_hz = np.sqrt(np.maximum(eigenvalues, 0.0)) / (2.0 * np.pi)
    if norm == "MAX":
        for i in range(eigenvectors.shape[1]):
            max_val = np.max(np.abs(eigenvectors[:, i]))
            if max_val > 0.0:
                eigenvectors[:, i] /= max_val
    return freqs_hz, eigenvectors


def run_sol103(bulk: BulkData, subcase: SubcaseControl) -> Sol103Result:
    """Run SOL 103 normal modes analysis for a single subcase.

    Returns a Sol103Result with frequencies, full-DOF mode shapes, and eigenvalues.
    """
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)

    K = assemble_global_stiffness(bulk)
    M = assemble_global_mass(bulk)

    spc_sid = subcase.spc_sid
    method_sid = subcase.method_sid

    if spc_sid is not None:
        check_spc_enforced_displacements(bulk, spc_sid)

    if method_sid is None:
        raise ValueError("SOL 103 subcase requires a METHOD (EIGRL) card")

    eigrl = bulk.eigrls[method_sid]

    # Free-free models (no SPC) have a singular K; eigsh shift-invert would fail
    # trying to factorise it. Force the dense path in that case.
    force_dense = spc_sid is None

    # RBE3 DOF transformation — eliminates dependent DOFs before SPC partitioning.
    # Note: T is dense; T.T @ K_csr @ T produces a dense ndarray (NumPy @ semantics).
    # solve_modes dispatches to the dense path for the resulting K.
    T, dep_dofs, red_dofs = build_rbe3_transformation(bulk, grid_index)
    if dep_dofs:
        K = T.T @ K @ T
        M = T.T @ M @ T
        dep_set = set(dep_dofs)
        red_map = {g: i for i, g in enumerate(red_dofs)}
        spc_dofs_full = get_spc_dofs(bulk, spc_sid, grid_index)
        spc_dofs = [red_map[d] for d in spc_dofs_full if d not in dep_set]
        n_red = len(red_dofs)
        K_free, _, free_dofs = apply_spcs(K, np.zeros(n_red), spc_dofs)
        M_free = M[free_dofs, :][:, free_dofs]
        freqs_hz, phi_free = solve_modes(K_free, M_free, eigrl, force_dense=force_dense)
        n_modes = len(freqs_hz)
        phi_red = np.zeros((n_red, n_modes))
        phi_red[free_dofs, :] = phi_free
        full_phi = T @ phi_red
    else:
        spc_dofs = get_spc_dofs(bulk, spc_sid, grid_index)
        K_free, _, free_dofs = apply_spcs(K, np.zeros(n_dofs), spc_dofs)
        M_free = M[free_dofs, :][:, free_dofs]
        freqs_hz, phi_free = solve_modes(K_free, M_free, eigrl, force_dense=force_dense)
        n_modes = len(freqs_hz)
        full_phi = np.zeros((n_dofs, n_modes))
        full_phi[free_dofs, :] = phi_free

    eigenvalues = (2.0 * np.pi * freqs_hz) ** 2

    return Sol103Result(
        frequencies_hz=freqs_hz,
        mode_shapes=full_phi,
        eigenvalues=eigenvalues,
    )
