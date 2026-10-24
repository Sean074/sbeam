"""#38 rod element — unit gates on the line-element registry and the rod matrices.

Design note ``docs/30_future/designs/rod_element_crod.md``: G5 (invariants), G5b
(frame independence), G7 (registry coverage, assembly part) and the CBAR
bit-identity promise of D1.
"""

from pathlib import Path

import numpy as np
import pytest

from sbeam.assembly.elements import (
    ROD_ZERO_DOFS, LineElement, RodSection, cbar_line_element, iter_line_elements,
    line_element, line_element_mass_global, line_element_mass_per_length,
    rod_frame, rod_local_mass, rod_local_stiffness, rod_section,
)
from sbeam.assembly.mass_matrix import assemble_global_mass, element_mass_global
from sbeam.assembly.stiffness import assemble_global_stiffness, element_stiffness_global
from sbeam.gpwg import compute_gpwg
from sbeam.model.element import Cbush
from sbeam.model.grid import Grid
from sbeam.parser.bdf_reader import parse_bdf

E, G, A, J, C, RHO, NSM = 2.0e11, 8.0e10, 1.0e-4, 2.0e-8, 2.0e-3, 7850.0, 0.3

#: One CBAR, one CROD and one CONROD meeting at grid 2; grid 4 is rod-only (held
#: by CONROD 3 along x, every other DOF SPC'd: a single rod stiffens one translation).
MIXED_DECK = """\
SOL 101
SUBCASE 1
  SPC = 1
  LOAD = 10
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
GRID, 3, , 1.0, 1.0, 0.0
GRID, 4, , 2.0, 0.0, 0.0
MAT1, 1, 2.0e11, 8.0e10, 0.25, 7850.0
PBAR, 1, 1, 1.0e-4, 1.0e-8, 1.0e-8, 2.0e-8, 0.3
PROD, 2, 1, 1.0e-4, 2.0e-8, 2.0e-3, 0.3
CBAR, 1, 1, 1, 2, 0.0, 1.0, 0.0
CROD, 2, 2, 2, 3
CONROD, 3, 2, 4, 1, 1.0e-4, 2.0e-8, 2.0e-3, 0.3
SPC1, 1, 123456, 1, 3
SPC1, 1, 23456, 4
FORCE, 10, 4, 0, 100.0, 1.0, 0.0, 0.0
ENDDATA
"""


def _mixed(tmp_path: Path):
    f = tmp_path / "mixed.bdf"
    f.write_text(MIXED_DECK)
    return parse_bdf(str(f))


def _rigid_modes(ga: Grid, gb: Grid) -> np.ndarray:
    """Six rigid-body modes of a two-node element as columns of a 12×6 matrix."""
    R = np.zeros((12, 6))
    for k, g in enumerate((ga, gb)):
        r = np.array([g.x, g.y, g.z])
        R[6 * k: 6 * k + 3, 0:3] = np.eye(3)
        R[6 * k + 3: 6 * k + 6, 3:6] = np.eye(3)
        # translation from a unit rotation about the origin: u = θ × r
        R[6 * k: 6 * k + 3, 3:6] = -np.array([[0, -r[2], r[1]], [r[2], 0, -r[0]], [-r[1], r[0], 0]])
    return R


# ---------------------------------------------------------------------------
# G5 — rod matrix invariants
# ---------------------------------------------------------------------------

class TestG5RodMatrices:
    def test_stiffness_only_axial_and_torsion(self):
        K = rod_local_stiffness(E, G, A, J, 2.0)
        for i in ROD_ZERO_DOFS:
            assert not K[i, :].any() and not K[:, i].any()
        a, t = E * A / 2.0, G * J / 2.0
        assert K[0, 0] == a and K[6, 6] == a and K[0, 6] == -a
        assert K[3, 3] == t and K[9, 9] == t and K[3, 9] == -t
        assert np.array_equal(K, K.T)

    def test_mass_translational_only_sums_to_mL(self):
        L = 2.0
        m = RHO * A + NSM
        M = rod_local_mass(m, L)
        for i in (3, 4, 5, 9, 10, 11):
            assert not M[i, :].any() and not M[:, i].any()
        for i in (0, 1, 2):
            assert M[i, i] == pytest.approx(2 * m * L / 6) and M[i, i + 6] == pytest.approx(m * L / 6)
        # Rigid translation sees the full mass in each direction.
        for d in range(3):
            u = np.zeros(12); u[d] = 1.0; u[d + 6] = 1.0
            assert u @ M @ u == pytest.approx(m * L, rel=1e-14)
        assert np.array_equal(M, M.T)

    @pytest.mark.parametrize("gb_xyz", [(2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 1.5),
                                        (1.0, 2.0, 3.0), (-0.3, 0.4, -1.2)])
    def test_global_stiffness_is_n_nT_and_frame_independent(self, gb_xyz):
        """G5b: Tᵀ K T = (EA/L) n nᵀ ⊕ (GJ/L) n nᵀ whatever e_y the frame picked."""
        ga, gb = Grid(gid=1, x=0.0, y=0.0, z=0.0), Grid(gid=2, x=gb_xyz[0], y=gb_xyz[1], z=gb_xyz[2])
        R = rod_frame(1, "CROD", ga, gb)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-15)
        assert np.linalg.det(R) == pytest.approx(1.0, rel=1e-14)
        n = np.array(gb_xyz) / np.linalg.norm(gb_xyz)
        assert np.allclose(R[0], n, atol=1e-15)
        L = float(np.linalg.norm(gb_xyz))
        from scipy.linalg import block_diag
        T = block_diag(R, R, R, R)
        K = T.T @ rod_local_stiffness(E, G, A, J, L) @ T
        N = np.outer(n, n)
        expected = np.zeros((12, 12))
        for (i, j, sgn) in ((0, 0, 1), (6, 6, 1), (0, 6, -1), (6, 0, -1)):
            expected[i:i + 3, j:j + 3] = sgn * E * A / L * N
            expected[i + 3:i + 6, j + 3:j + 6] = sgn * G * J / L * N
        assert np.allclose(K, expected, rtol=1e-13, atol=1e-13 * E * A / L)
        # Rigid modes carry no strain energy.
        assert np.allclose(K @ _rigid_modes(ga, gb), 0.0, atol=1e-13 * E * A / L)

    def test_coincident_grids_refused(self):
        g = Grid(gid=1, x=1.0, y=1.0, z=1.0)
        with pytest.raises(ValueError, match=r"CONROD 7: nodes GA=1 and GB=1 are coincident"):
            rod_frame(7, "CONROD", g, g)


# ---------------------------------------------------------------------------
# D1/D4 — registry behaviour
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_iteration_order_and_types(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        elems = list(iter_line_elements(bulk))
        assert [type(e).__name__ for e in elems] == ["Cbar", "Crod", "Conrod"]
        assert [line_element(e, bulk).kind for e in elems] == ["CBAR", "CROD", "CONROD"]

    def test_unregistered_type_is_a_type_error(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        with pytest.raises(TypeError, match="Cbush is not a registered line element"):
            line_element(Cbush(eid=9, pid=1, ga=1, gb=2), bulk)

    def test_cbar_entry_is_bit_identical_to_the_legacy_helpers(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        cbar = bulk.cbars[1]
        le = line_element(cbar, bulk)
        assert isinstance(le, LineElement)
        assert np.array_equal(le.global_stiffness(),
                              element_stiffness_global(cbar, bulk.grids, bulk.pbars, bulk.mat1s))
        assert np.array_equal(line_element_mass_global(cbar, bulk),
                              element_mass_global(cbar, bulk.grids, bulk.pbars, bulk.mat1s))
        assert np.array_equal(cbar_line_element(cbar, bulk.grids, bulk.pbars, bulk.mat1s).K_local,
                              le.K_local)

    def test_rod_section_hides_the_crod_conrod_difference(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        assert rod_section(bulk.crods[2], bulk) == RodSection(mid=1, A=A, J=J, c=C, nsm=NSM)
        assert rod_section(bulk.conrods[3], bulk) == RodSection(mid=1, A=A, J=J, c=C, nsm=NSM)
        assert line_element_mass_per_length(bulk.crods[2], bulk) == RHO * A + NSM
        assert line_element_mass_per_length(bulk.conrods[3], bulk) == RHO * A + NSM
        assert line_element_mass_per_length(bulk.cbars[1], bulk) == RHO * A + NSM

    def test_rod_entries_use_the_rod_matrices(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        for elem in (bulk.crods[2], bulk.conrods[3]):
            le = line_element(elem, bulk)
            assert np.array_equal(le.K_local, rod_local_stiffness(E, G, A, J, le.L))
            M = line_element_mass_global(elem, bulk)
            u = np.zeros(12); u[2] = 1.0; u[8] = 1.0
            assert u @ M @ u == pytest.approx((RHO * A + NSM) * le.L, rel=1e-14)


# ---------------------------------------------------------------------------
# G7 (assembly part) — every registered element reaches K, M and GPWG
# ---------------------------------------------------------------------------

class TestG7AssemblyCoverage:
    def test_every_element_reaches_k_and_m(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        gi = {gid: i for i, gid in enumerate(sorted(bulk.grids))}
        K = assemble_global_stiffness(bulk).toarray()
        M = assemble_global_mass(bulk).toarray()
        for gid in (1, 2, 3, 4):
            rows = slice(6 * gi[gid], 6 * gi[gid] + 3)
            assert np.abs(K[rows, :]).sum() > 0.0
            assert np.abs(M[rows, :]).sum() > 0.0
        # Grid 4 is rod-only: no bending/shear coupling, so its rotation rows see only GJ/L.
        rot = slice(6 * gi[4] + 3, 6 * gi[4] + 6)
        le = line_element(bulk.conrods[3], bulk)
        assert np.abs(K[rot, :]).sum() == pytest.approx(
            np.abs(le.global_stiffness()[9:12, :]).sum(), rel=1e-14)
        assert np.abs(M[rot, :]).sum() == 0.0

    def test_gpwg_sums_all_three_elements(self, tmp_path):
        _, bulk = _mixed(tmp_path)
        total = 0.0
        for elem in iter_line_elements(bulk):
            total += line_element_mass_per_length(elem, bulk) * line_element(elem, bulk).L
        assert compute_gpwg(bulk).total_mass == pytest.approx(total, rel=1e-14)

    def test_single_source_gate_still_names_the_only_callers(self):
        """The #20 G5 allow-list is untouched: elements.py never calls local_* itself."""
        import ast
        src = (Path(__file__).resolve().parents[2] / "sbeam/assembly/elements.py").read_text()
        names = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                 for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
        assert "local_stiffness" not in names and "local_mass" not in names
