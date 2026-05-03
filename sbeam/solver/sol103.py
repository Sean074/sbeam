"""SOL 103 normal modes solver."""

import numpy as np
import scipy.linalg

from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import assemble_global_stiffness, get_spc_dofs, apply_spcs
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import build_grid_index
from sbeam.results.results import Sol103Result


def solve_modes(
    K_free: np.ndarray,
    M_free: np.ndarray,
    eigrl,
) -> tuple:
    """Solve generalised eigenvalue problem K phi = lambda M phi.

    Returns (frequencies_hz, eigenvectors) where eigenvectors has shape
    (n_free_dofs, n_modes) normalised according to eigrl.norm.
    """
    n = K_free.shape[0]
    nd = eigrl.nd if eigrl.nd is not None else n
    nd = min(nd, n)

    # scipy.linalg.eigh solves K x = lambda M x, returning eigenvalues in ascending order.
    # With b=M_free the returned eigenvectors are M-normalised: phi^T M phi = I.
    eigenvalues, eigenvectors = scipy.linalg.eigh(K_free, b=M_free)

    eigenvalues = eigenvalues[:nd]
    eigenvectors = eigenvectors[:, :nd]

    # Convert to Hz — clamp negative eigenvalues (numerical noise near zero)
    freqs_hz = np.sqrt(np.maximum(eigenvalues, 0.0)) / (2.0 * np.pi)

    if eigrl.norm == "MAX":
        for i in range(nd):
            max_val = np.max(np.abs(eigenvectors[:, i]))
            if max_val > 0.0:
                eigenvectors[:, i] /= max_val

    return freqs_hz, eigenvectors


def run_sol103(bulk: BulkData, case_control) -> Sol103Result:
    """Run SOL 103 normal modes analysis (first subcase).

    Returns a Sol103Result with frequencies, full-DOF mode shapes, and eigenvalues.
    """
    grid_index = build_grid_index(bulk)
    n_dofs = 6 * len(grid_index)

    K = assemble_global_stiffness(bulk)
    M = assemble_global_mass(bulk)

    subcase = case_control.subcases[0]
    spc_sid = subcase.spc_sid
    method_sid = subcase.method_sid

    if method_sid is None:
        raise ValueError("SOL 103 subcase requires a METHOD (EIGRL) card")

    eigrl = bulk.eigrls[method_sid]

    spc_dofs = get_spc_dofs(bulk, spc_sid, grid_index)
    K_free, _, free_dofs = apply_spcs(K, np.zeros(n_dofs), spc_dofs)
    M_free = M[np.ix_(free_dofs, free_dofs)]

    freqs_hz, phi_free = solve_modes(K_free, M_free, eigrl)

    n_modes = len(freqs_hz)
    full_phi = np.zeros((n_dofs, n_modes))
    for mode in range(n_modes):
        for local_idx, global_dof in enumerate(free_dofs):
            full_phi[global_dof, mode] = phi_free[local_idx, mode]

    eigenvalues = (2.0 * np.pi * freqs_hz) ** 2

    return Sol103Result(
        frequencies_hz=freqs_hz,
        mode_shapes=full_phi,
        eigenvalues=eigenvalues,
    )
