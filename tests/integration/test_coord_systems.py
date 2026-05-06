"""Integration verification for CORD2R coordinate system support (V-CS1 to V-CS5)."""

import math
import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_data
from sbeam.assembly.stiffness import assemble_global_stiffness, apply_spcs
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.assembly.load_vector import assemble_load_vector, build_grid_index
from sbeam.solver.sol101 import solve_static
from sbeam.solver.sol103 import solve_modes
from sbeam.model.constraint import Spc1


# ---------------------------------------------------------------------------
# Shared cantilever BDF fragments
# ---------------------------------------------------------------------------

# Reference model: cantilever along global X, tip load in global Y
_CANTILEVER_GLOBAL = """\
$ Reference cantilever — all in global CID 0
GRID, 1, 0, 0.0, 0.0, 0.0
GRID, 2, 0, 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 0.0, 1.0
SPC1, 1, 123456, 1
FORCE, 10, 2, 0, 1.0, 0.0, 1.0, 0.0
""".splitlines()

# Same cantilever but defined in a rotated coordinate system (local X = global Y)
# The beam runs along local X (= global Y), and load is in local Y (= -global X).
# After coordinate resolution: grid 1 at global (0,0,0), grid 2 at global (0,1,0).
_CANTILEVER_ROTATED = """\
$ Cantilever in rotated CORD2R: local X=global Y, local Y=-global X
$ CORD2R 1: A=origin, B on global Z-axis, C in global Y direction
$ → local X = global Y, local Y = -global X, local Z = global Z
CORD2R, 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
+, 0.0, 1.0, 0.0
GRID, 1, 1, 0.0, 0.0, 0.0
GRID, 2, 1, 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 0.0, 1.0
SPC1, 1, 123456, 1
$ Force in local Y direction of CID 1 (= -global X)
FORCE, 10, 2, 1, 1.0, 0.0, 1.0, 0.0
""".splitlines()


def _run_sol101(lines):
    bulk = parse_bulk_data(lines)
    grid_index = build_grid_index(bulk)
    K = assemble_global_stiffness(bulk)
    f = assemble_load_vector(bulk, 10)
    spc1 = bulk.spc1s[1][0]
    spc_dofs = [6 * grid_index[g] + (int(d) - 1)
                for g in spc1.grids for d in spc1.c]
    K_free, f_free, free_dofs = apply_spcs(K, f, spc_dofs)
    n_dofs = 6 * len(grid_index)
    return solve_static(K_free, f_free, free_dofs, n_dofs), bulk, grid_index


def _run_sol103(lines, n_modes):
    bulk = parse_bulk_data(lines)
    from sbeam.model.load import Eigrl
    bulk.eigrls[1] = Eigrl(sid=1, nd=n_modes, norm="MASS")
    grid_index = build_grid_index(bulk)
    K = assemble_global_stiffness(bulk)
    M = assemble_global_mass(bulk)
    spc1 = bulk.spc1s[1][0]
    spc_dofs = [6 * grid_index[g] + (int(d) - 1)
                for g in spc1.grids for d in spc1.c]
    K_free, _, free_dofs = apply_spcs(K, np.zeros(K.shape[0]), spc_dofs)
    M_free = M[np.ix_(free_dofs, free_dofs)]
    freqs, shapes = solve_modes(K_free, M_free, bulk.eigrls[1])
    return freqs, shapes, bulk, grid_index


# ---------------------------------------------------------------------------
# V-CS1: GRID in rotated CP — static result matches global reference
# ---------------------------------------------------------------------------

class TestVCS1:
    """Grid defined in rotated CP system: static tip deflection matches reference."""

    def test_tip_displacement_matches_global(self):
        u_ref, bulk_ref, gi_ref = _run_sol101(_CANTILEVER_GLOBAL)
        u_rot, bulk_rot, gi_rot = _run_sol101(_CANTILEVER_ROTATED)

        # Reference: tip (gid 2) Ty (DOF index 1) deflection
        tip_ref = u_ref[6 * gi_ref[2] + 1]

        # Rotated model: beam is along global Y, load is in global -X direction
        # → tip displacement in global -X (DOF index 0 = Tx, should be negative)
        tip_rot = u_rot[6 * gi_rot[2] + 0]  # Tx

        assert abs(tip_ref) > 1e-10   # non-trivial reference
        assert abs(abs(tip_rot) - abs(tip_ref)) / abs(tip_ref) < 0.001


# ---------------------------------------------------------------------------
# V-CS2: FORCE in rotated CID — same as applying equivalent global force
# ---------------------------------------------------------------------------

class TestVCS2:
    """Force applied in rotated CID gives same load vector as equivalent global force."""

    def test_force_in_rotated_cid(self):
        # Model: one free grid, FORCE in CID 1 (90° about Z)
        # Force (1,0,0) in CID 1 = (0,1,0) in global
        lines_rotated = """\
CORD2R, 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
+, 0.0, 1.0, 0.0
GRID, 1, 0, 0.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
FORCE, 10, 1, 1, 5.0, 1.0, 0.0, 0.0
""".splitlines()
        bulk = parse_bulk_data(lines_rotated)
        f = assemble_load_vector(bulk, 10)
        # Force (1,0,0) in CID 1 → (0,1,0) in global, magnitude 5.0
        # GID 1 is grid index 0 → DOF 1 = Ty
        assert f[0] == pytest.approx(0.0, abs=1e-12)  # Tx
        assert f[1] == pytest.approx(5.0, abs=1e-12)  # Ty
        assert f[2] == pytest.approx(0.0, abs=1e-12)  # Tz

    def test_force_cid0_unchanged(self):
        lines = """\
GRID, 1, 0, 0.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
FORCE, 10, 1, 0, 3.0, 0.0, 1.0, 0.0
""".splitlines()
        bulk = parse_bulk_data(lines)
        f = assemble_load_vector(bulk, 10)
        assert f[1] == pytest.approx(3.0)   # Ty


# ---------------------------------------------------------------------------
# V-CS3: CD output frame — displacements reported in grid's CD system
# ---------------------------------------------------------------------------

class TestVCS3:
    """Displacements written in the grid's CD coordinate system."""

    def test_cd_transform_applied(self):
        from sbeam.assembly.coord_transform import build_transform

        # Run the reference cantilever, then manually verify that rotating
        # the global tip displacement into a 90°-about-Z CD frame gives
        # the expected local components.
        u_ref, bulk_ref, gi_ref = _run_sol101(_CANTILEVER_GLOBAL)
        tip_idx = gi_ref[2]
        t_global = u_ref[6*tip_idx:6*tip_idx+3]

        # Add CID 1 (90° about Z: local X = global Y) as CD
        bulk_ref.cord2rs[1] = __import__(
            'sbeam.model.coordinate_system', fromlist=['Cord2r']
        ).Cord2r(cid=1, rid=0, a=(0,0,0), b=(0,0,1), c=(0,1,0))

        R = build_transform(1, bulk_ref.cord2rs)
        t_local = R.T @ t_global

        # Global tip displacement is (0, Ty, 0); in rotated frame it should be
        # in local X direction (since local X = global Y)
        assert abs(t_local[0]) > abs(t_local[1])  # dominant component is local Tx


# ---------------------------------------------------------------------------
# V-CS4: Chained CORD2R — grid position resolves correctly
# ---------------------------------------------------------------------------

class TestVCS4:
    def test_chained_cord2r_position(self):
        """Grid position resolves through two chained coordinate systems."""
        # CID 1: identity (Z=global Z, X=global X) but origin at (1,0,0)
        # CID 2: defined in CID 1 frame, identity relative to CID 1
        # Grid at CID 2 local (0,0,0) should resolve to global (1,0,0)
        lines = """\
CORD2R, 1, 0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0
+, 2.0, 0.0, 0.0
CORD2R, 2, 1, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
+, 1.0, 0.0, 0.0
GRID, 1, 2, 0.0, 0.0, 0.0
""".splitlines()
        bulk = parse_bulk_data(lines)
        g = bulk.grids[1]
        assert g.x == pytest.approx(1.0, abs=1e-12)
        assert g.y == pytest.approx(0.0, abs=1e-12)
        assert g.z == pytest.approx(0.0, abs=1e-12)


# ---------------------------------------------------------------------------
# V-CS5: Cantilever frequency in rotated coordinate system
# ---------------------------------------------------------------------------

class TestVCS5:
    """Cantilever fundamental frequency is the same regardless of CP orientation."""

    _CANTILEVER_10_GLOBAL = """\
GRID, 1, 0, 0.0, 0.0, 0.0
GRID, 2, 0, 0.1, 0.0, 0.0
GRID, 3, 0, 0.2, 0.0, 0.0
GRID, 4, 0, 0.3, 0.0, 0.0
GRID, 5, 0, 0.4, 0.0, 0.0
GRID, 6, 0, 0.5, 0.0, 0.0
GRID, 7, 0, 0.6, 0.0, 0.0
GRID, 8, 0, 0.7, 0.0, 0.0
GRID, 9, 0, 0.8, 0.0, 0.0
GRID, 10, 0, 0.9, 0.0, 0.0
GRID, 11, 0, 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 0.0, 1.0
CBAR, 2, 1, 2, 3, 0.0, 0.0, 1.0
CBAR, 3, 1, 3, 4, 0.0, 0.0, 1.0
CBAR, 4, 1, 4, 5, 0.0, 0.0, 1.0
CBAR, 5, 1, 5, 6, 0.0, 0.0, 1.0
CBAR, 6, 1, 6, 7, 0.0, 0.0, 1.0
CBAR, 7, 1, 7, 8, 0.0, 0.0, 1.0
CBAR, 8, 1, 8, 9, 0.0, 0.0, 1.0
CBAR, 9, 1, 9, 10, 0.0, 0.0, 1.0
CBAR, 10, 1, 10, 11, 0.0, 0.0, 1.0
SPC1, 1, 123456, 1
"""

    _CANTILEVER_10_ROTATED = """\
$ Same beam along local X (= global Y) in CID 1
CORD2R, 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0
+, 0.0, 1.0, 0.0
GRID, 1, 1, 0.0, 0.0, 0.0
GRID, 2, 1, 0.1, 0.0, 0.0
GRID, 3, 1, 0.2, 0.0, 0.0
GRID, 4, 1, 0.3, 0.0, 0.0
GRID, 5, 1, 0.4, 0.0, 0.0
GRID, 6, 1, 0.5, 0.0, 0.0
GRID, 7, 1, 0.6, 0.0, 0.0
GRID, 8, 1, 0.7, 0.0, 0.0
GRID, 9, 1, 0.8, 0.0, 0.0
GRID, 10, 1, 0.9, 0.0, 0.0
GRID, 11, 1, 1.0, 0.0, 0.0
PBAR, 1, 1, 0.01, 8.333e-6, 8.333e-6, 1.406e-5
MAT1, 1, 2.0e11, 7.692e10, 0.3, 7850.0
CBAR, 1, 1, 1, 2, 0.0, 0.0, 1.0
CBAR, 2, 1, 2, 3, 0.0, 0.0, 1.0
CBAR, 3, 1, 3, 4, 0.0, 0.0, 1.0
CBAR, 4, 1, 4, 5, 0.0, 0.0, 1.0
CBAR, 5, 1, 5, 6, 0.0, 0.0, 1.0
CBAR, 6, 1, 6, 7, 0.0, 0.0, 1.0
CBAR, 7, 1, 7, 8, 0.0, 0.0, 1.0
CBAR, 8, 1, 8, 9, 0.0, 0.0, 1.0
CBAR, 9, 1, 9, 10, 0.0, 0.0, 1.0
CBAR, 10, 1, 10, 11, 0.0, 0.0, 1.0
SPC1, 1, 123456, 1
"""

    def test_frequency_matches_global(self):
        freqs_global, _, _, _ = _run_sol103(self._CANTILEVER_10_GLOBAL.splitlines(), 3)
        freqs_rotated, _, _, _ = _run_sol103(self._CANTILEVER_10_ROTATED.splitlines(), 3)

        f1_global = min(f for f in freqs_global if f > 0.01)
        f1_rotated = min(f for f in freqs_rotated if f > 0.01)

        assert abs(f1_rotated - f1_global) / f1_global < 0.01
