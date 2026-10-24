"""CBAR pin releases (PA/PB) by static condensation — DEF-M17 / issue #20.

Gates G1, G3, G4, G5 and G6 of ``docs/30_future/designs/cbar_pin_release_condensation.md``.
G2/G2b (clamped–pinned modal decks) live in ``tests/integration/test_verification.py``
as V22/V23.
"""

import ast
import itertools
from pathlib import Path

import numpy as np
import pytest

import sbeam
from sbeam.model.grid import Grid
from sbeam.model.element import Cbar
from sbeam.model.property import Pbar
from sbeam.model.material import Mat1
from sbeam.model.load import Force
from sbeam.model.constraint import Spc1
from sbeam.model.bulk_data import BulkData
from sbeam.assembly.stiffness import (
    local_stiffness,
    release_indices,
    condense_released_dofs,
    released_local_stiffness,
    element_stiffness_global,
    transform_matrix,
)
from sbeam.assembly.mass_matrix import local_mass, element_mass_global
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol101 import run_sol101, recover_bar_forces, _element_local_forces
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import CaseControl, SubcaseControl


# ---------------------------------------------------------------------------
# Shared fixtures — design-note §1 section (E = 2e11, A = 0.1, I = 8.333e-4, ρ = 7850)
# ---------------------------------------------------------------------------

E = 2.0e11
G = 7.692e10
A = 0.1
I = 8.333e-4
J = 1.406e-3
RHO = 7850.0
L = 1.0

_pbar_full = Pbar(pid=10, mid=100, A=A, I1=I, I2=I, J=J)
_mat1 = Mat1(mid=100, E=E, G=G, nu=0.3, rho=RHO)


def _rigid_body_modes(L: float) -> np.ndarray:
    """12×6 rigid-body modes of a local element from A=(0,0,0) to B=(L,0,0).

    A rotation θ about the origin displaces a point r by θ × r: Ry gives w = −x·θy,
    Rz gives v = +x·θz (consistent with θy = −dw/dx, θz = dv/dx in ``local_mass``).
    """
    R = np.zeros((12, 6))
    for node, x in ((0, 0.0), (1, L)):
        o = 6 * node
        for d in range(6):
            R[o + d, d] = 1.0
        R[o + 2, 4] = -x    # w from Ry
        R[o + 1, 5] = x     # v from Rz
    return R


def _release_combos():
    opts = ["", "1", "2", "3", "4", "5", "6", "45", "46", "56", "456"]
    for pa, pb in itertools.product(opts, opts):
        if any(d in pa and d in pb for d in "1234"):   # D5 cases are refused upstream
            continue
        yield pa, pb


# ---------------------------------------------------------------------------
# release_indices / condense_released_dofs — unit behaviour
# ---------------------------------------------------------------------------

class TestReleaseIndices:
    def test_mapping(self):
        assert release_indices("", "") == []
        assert release_indices("1", "") == [0]
        assert release_indices("", "1") == [6]
        assert release_indices("56", "456") == [4, 5, 9, 10, 11]

    def test_none_tolerated(self):
        assert release_indices(None, None) == []  # type: ignore[arg-type]


class TestCondensation:
    def test_no_release_is_identity(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        Kc, T = released_local_stiffness(_pbar_full, _mat1, L, "", "")
        assert np.array_equal(Kc, K)
        assert np.array_equal(T, np.eye(12))

    def test_does_not_modify_input(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        K_copy = K.copy()
        condense_released_dofs(K, [5, 11])
        assert np.array_equal(K, K_copy)

    def test_k_prime_is_congruent_transform(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        Kc, T = condense_released_dofs(K, release_indices("", "56"))
        assert np.allclose(Kc, T.T @ K @ T, atol=1e-6 * np.abs(K).max())
        assert np.all(T[:, [10, 11]] == 0.0)        # released DOFs are no longer inputs

    def test_single_release_is_schur_complement(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        i = 11
        r = [k for k in range(12) if k != i]
        Kc, _ = condense_released_dofs(K, [i])
        schur = K[np.ix_(r, r)] - np.outer(K[r, i], K[i, r]) / K[i, i]
        assert np.allclose(Kc[np.ix_(r, r)], schur)
        assert np.all(Kc[i, :] == 0.0) and np.all(Kc[:, i] == 0.0)

    def test_block_release_equals_sequential_any_order(self):
        K = local_stiffness(_pbar_full, _mat1, L)
        rel = [4, 5, 10, 11]
        r = [k for k in range(12) if k not in rel]
        Kc, _ = condense_released_dofs(K, rel)
        Kc_rev, _ = condense_released_dofs(K, rel[::-1])
        block = K[np.ix_(r, r)] - K[np.ix_(r, rel)] @ np.linalg.solve(K[np.ix_(rel, rel)], K[np.ix_(rel, r)])
        assert np.allclose(Kc[np.ix_(r, r)], block)
        assert np.allclose(Kc, Kc_rev)

    def test_fixed_pinned_bending_stiffness(self):
        """PB=6 on a unit element: retained K[1,1] = 3EI/L³ (fixed–pinned), not 12EI/L³."""
        Kc, _ = released_local_stiffness(_pbar_full, _mat1, L, "", "6")
        assert Kc[1, 1] == pytest.approx(3 * E * I / L**3, rel=1e-12)
        assert Kc[11, :].tolist() == [0.0] * 12

    def test_zero_pivot_only_zeroes(self):
        """I1 = 0 (D4): releasing Rz has nothing to condense; row/col is just zeroed."""
        pbar0 = Pbar(pid=11, mid=100, A=A, I1=0.0, I2=I, J=J)
        K = local_stiffness(pbar0, _mat1, L)
        Kc, T = condense_released_dofs(K, [5, 11])
        assert np.all(np.isfinite(Kc)) and np.all(np.isfinite(T))
        keep = [k for k in range(12) if k not in (5, 11)]
        assert np.allclose(Kc[np.ix_(keep, keep)], K[np.ix_(keep, keep)])

    def test_pa_pb_56_is_a_two_force_member(self):
        """Design-note correction: PA=PB=56 transmits axial force and torsion only —
        no transverse shear survives once both bending rotations are released."""
        K = local_stiffness(_pbar_full, _mat1, L)
        Kc, _ = released_local_stiffness(_pbar_full, _mat1, L, "56", "56")
        assert Kc[0, 0] == pytest.approx(K[0, 0]) and Kc[0, 6] == pytest.approx(K[0, 6])
        assert Kc[3, 9] == pytest.approx(K[3, 9])
        for idx in (1, 2, 7, 8, 4, 5, 10, 11):
            assert np.all(np.abs(Kc[idx, :]) <= 1e-9 * np.abs(K).max()), f"row {idx} not zero"


# ---------------------------------------------------------------------------
# G4 — invariants over every allowed PA/PB combination
# ---------------------------------------------------------------------------

class TestG4Invariants:
    @pytest.mark.parametrize("pa,pb", list(_release_combos()))
    def test_invariants(self, pa, pb):
        K = local_stiffness(_pbar_full, _mat1, L)
        M = local_mass(_pbar_full, _mat1, L)
        Kc, T = released_local_stiffness(_pbar_full, _mat1, L, pa, pb)
        Mc = T.T @ M @ T
        R = _rigid_body_modes(L)
        kscale = np.abs(K).max()
        rel = release_indices(pa, pb)

        assert np.allclose(Kc, Kc.T, atol=1e-9 * kscale)
        assert np.linalg.eigvalsh(Kc).min() >= -1e-9 * kscale          # PSD
        assert np.allclose(Kc @ R, 0.0, atol=1e-7 * kscale)             # no rigid strain energy
        assert np.allclose(R.T @ Mc @ R, R.T @ M @ R, rtol=1e-10, atol=1e-12)  # GPWG preserved

        rng = np.random.default_rng(0)
        u = rng.standard_normal(12)
        f = Kc @ u
        assert np.all(f[rel] == 0.0)                                    # released forces exactly 0

    def test_d5_combo_breaks_rigid_mass(self):
        """Why D5 refuses digits 1–4 at both ends: the rigid mass is no longer preserved."""
        K = local_stiffness(_pbar_full, _mat1, L)
        M = local_mass(_pbar_full, _mat1, L)
        _, T = condense_released_dofs(K, release_indices("2", "2"))
        R = _rigid_body_modes(L)
        assert not np.allclose(R.T @ (T.T @ M @ T) @ R, R.T @ M @ R, rtol=1e-6)


# ---------------------------------------------------------------------------
# Assembly / recovery wiring
# ---------------------------------------------------------------------------

def _grids_horizontal(length=1.0):
    return {1: Grid(gid=1, x=0.0, y=0.0, z=0.0), 2: Grid(gid=2, x=length, y=0.0, z=0.0)}


class TestAssemblyUsesCondensedMatrices:
    def test_element_stiffness_global_condensed(self):
        grids = _grids_horizontal()
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="", pb="6")
        Kg = element_stiffness_global(cbar, grids, {10: _pbar_full}, {100: _mat1})
        Kc, _ = released_local_stiffness(_pbar_full, _mat1, L, "", "6")
        T = transform_matrix(cbar, grids)
        assert np.allclose(Kg, T.T @ Kc @ T)
        assert np.allclose(Kg, Kg.T, atol=1e-10)

    def test_element_mass_global_condensed(self):
        grids = _grids_horizontal()
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="", pb="6")
        Mg = element_mass_global(cbar, grids, {10: _pbar_full}, {100: _mat1})
        _, T_rel = released_local_stiffness(_pbar_full, _mat1, L, "", "6")
        M = local_mass(_pbar_full, _mat1, L)
        T = transform_matrix(cbar, grids)
        assert np.allclose(Mg, T.T @ (T_rel.T @ M @ T_rel) @ T)
        assert not np.allclose(Mg, T.T @ M @ T)      # congruent condensation changed it (D3)

    def test_no_pins_unchanged(self):
        grids = _grids_horizontal()
        cbar = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0)
        T = transform_matrix(cbar, grids)
        assert np.array_equal(element_stiffness_global(cbar, grids, {10: _pbar_full}, {100: _mat1}),
                              T.T @ local_stiffness(_pbar_full, _mat1, L) @ T)
        assert np.array_equal(element_mass_global(cbar, grids, {10: _pbar_full}, {100: _mat1}),
                              T.T @ local_mass(_pbar_full, _mat1, L) @ T)


# ---------------------------------------------------------------------------
# G1 — fixed–pinned single element, tip load
# ---------------------------------------------------------------------------

class TestG1FixedPinned:
    P = 1000.0

    def _bulk(self):
        bulk = BulkData()
        bulk.grids.update(_grids_horizontal())
        bulk.pbars[10] = _pbar_full
        bulk.mat1s[100] = _mat1
        bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=2, x1=0.0, x2=1.0, x3=0.0, pa="", pb="6")
        bulk.spc1s[1] = [Spc1(sid=1, c="123456", grids=[1]), Spc1(sid=1, c="6", grids=[2])]
        bulk.forces[2] = [Force(sid=2, gid=2, cid=0, f=self.P, n1=0.0, n2=1.0, n3=0.0)]
        return bulk

    @pytest.fixture(scope="class")
    def solved(self):
        bulk = self._bulk()
        result = run_sol101(bulk, SubcaseControl(subcase_id=1, spc_sid=1, load_sid=2))
        return bulk, result, build_grid_index(bulk)

    def test_tip_deflection(self, solved):
        bulk, result, gi = solved
        assert result.displacements[6 * gi[2] + 1] == pytest.approx(self.P * L**3 / (3 * E * I), rel=1e-10)

    def test_root_moment(self, solved):
        bulk, result, gi = solved
        assert result.reactions[1][5] == pytest.approx(-self.P * L, rel=1e-10)
        assert result.reactions[1][1] == pytest.approx(-self.P, rel=1e-10)

    def test_released_end_moment_exactly_zero(self, solved):
        bulk, result, gi = solved
        f_local = _element_local_forces(bulk.cbars[1], bulk.grids, bulk.pbars, bulk.mat1s,
                                        result.displacements, gi)
        assert f_local[11] == 0.0
        bf = recover_bar_forces(bulk.cbars[1], bulk.grids, bulk.pbars, bulk.mat1s,
                                result.displacements, gi)
        assert bf.bm2_b == 0.0
        assert bf.bm2_a == pytest.approx(-self.P * L, rel=1e-10)
        assert bf.shear1 == pytest.approx(self.P, rel=1e-10)


# ---------------------------------------------------------------------------
# G3 — truss with real bending stiffness (the old gate used I = J = 0)
# ---------------------------------------------------------------------------

class TestG3TrussAnalytical:
    """
    2-bar A-frame truss (XY plane): supports at (−1,0,0) and (1,0,0), apex (0,1,0),
    Fy = −P at the apex.  Bars have full I1/I2/J and PA=PB='56' (two-force members).
    Analytical: δy = −P√2/EA.
    """

    def _make_bulk(self, pa="56", pb="56"):
        bulk = BulkData()
        bulk.grids[1] = Grid(gid=1, x=-1.0, y=0.0, z=0.0)
        bulk.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        bulk.grids[3] = Grid(gid=3, x=0.0, y=1.0, z=0.0)
        bulk.pbars[10] = _pbar_full
        bulk.mat1s[100] = _mat1
        bulk.cbars[1] = Cbar(eid=1, pid=10, ga=1, gb=3, x1=0.0, x2=0.0, x3=1.0, pa=pa, pb=pb)
        bulk.cbars[2] = Cbar(eid=2, pid=10, ga=2, gb=3, x1=0.0, x2=0.0, x3=1.0, pa=pa, pb=pb)
        bulk.spc1s[10] = [Spc1(sid=10, c="123456", grids=[1, 2]), Spc1(sid=10, c="3456", grids=[3])]
        bulk.forces[20] = [Force(sid=20, gid=3, cid=0, f=1.0, n1=0.0, n2=-1.0, n3=0.0)]
        return bulk

    def _solve(self, bulk):
        cc = CaseControl(sol=101, subcases=[SubcaseControl(subcase_id=1, spc_sid=10, load_sid=20)])
        return run_sol101(bulk, cc.subcases[0])

    def test_apex_deflection_matches_truss(self):
        result = self._solve(self._make_bulk())
        assert result.displacements[6 * 2 + 1] == pytest.approx(-np.sqrt(2) / (E * A), rel=1e-9)

    def test_horizontal_displacement_zero_by_symmetry(self):
        result = self._solve(self._make_bulk())
        assert result.displacements[6 * 2 + 0] == pytest.approx(0.0, abs=1e-15)

    def test_rigid_frame_differs(self):
        result = self._solve(self._make_bulk(pa="", pb=""))
        assert result.displacements[6 * 2 + 1] != pytest.approx(-np.sqrt(2) / (E * A), rel=0.01)


# ---------------------------------------------------------------------------
# G6 — D5 validation at parse time
# ---------------------------------------------------------------------------

_DECK = """\
SOL 101
SUBCASE 1
  SPC = 1
  LOAD = 2
BEGIN BULK
GRID, 1, , 0.0, 0.0, 0.0
GRID, 2, , 1.0, 0.0, 0.0
MAT1, 100, 2.0e11, 7.692e10, 0.3, 7850.0
PBAR, 10, 100, 0.1, 8.333e-4, 8.333e-4, 1.406e-3
CBAR, 1, 10, 1, 2, 0.0, 1.0, 0.0
+, {pa}, {pb}
SPC1, 1, 123456, 1
FORCE, 2, 2, 0, 1000.0, 0.0, 1.0, 0.0
ENDDATA
"""


def _parse(tmp_path, pa, pb):
    deck = tmp_path / "pins.bdf"
    deck.write_text(_DECK.format(pa=pa, pb=pb))
    return parse_bdf(deck)


class TestG6SameDofBothEnds:
    @pytest.mark.parametrize("d", ["1", "2", "3", "4"])
    def test_translation_or_torsion_both_ends_refused(self, tmp_path, d):
        with pytest.raises(ValueError, match=rf"CBAR 1: DOF {d} released at both ends"):
            _parse(tmp_path, d, d)

    def test_456_both_ends_refused_naming_digit_4(self, tmp_path):
        with pytest.raises(ValueError, match=r"CBAR 1: DOF 4 released at both ends"):
            _parse(tmp_path, "456", "456")

    def test_56_both_ends_allowed(self, tmp_path):
        _, bulk = _parse(tmp_path, "56", "56")
        assert bulk.cbars[1].pa == "56" and bulk.cbars[1].pb == "56"

    def test_invalid_digit_refused(self, tmp_path):
        with pytest.raises(ValueError, match=r"CBAR 1 PB: invalid DOF string"):
            _parse(tmp_path, "", "7")


# ---------------------------------------------------------------------------
# G5 — single source: only the helper builds the unreleased CBAR matrices
# ---------------------------------------------------------------------------

class TestG5SingleSource:
    def test_only_helper_calls_unreleased_cbar_matrices(self):
        pkg = Path(sbeam.__file__).parent
        allowed = {
            ("assembly/stiffness.py", "local_stiffness"),   # released_local_stiffness
            ("assembly/mass_matrix.py", "local_mass"),       # element_mass_global (condenses with T)
        }
        offenders = []
        for py in pkg.rglob("*.py"):
            rel = py.relative_to(pkg).as_posix()
            tree = ast.parse(py.read_text(), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                    if name in ("local_stiffness", "local_mass") and (rel, name) not in allowed:
                        offenders.append(f"{rel}:{node.lineno} {name}")
        assert offenders == [], offenders
