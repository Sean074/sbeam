"""`docs/20_theory/00_beam_methods.md` states what the code does, with numbers (#132).

The page replaced a notebook whose cells built their own matrices and whose results
table was typed by hand. Three things are gated here:

1. The element matrices the page derives, integrated numerically from the page's shape
   functions, equal ``local_stiffness`` and ``local_mass`` entry by entry.
2. The mesh-convergence table: each row is recomputed with the solver, and the order of
   convergence the page predicts (error in f1 ∝ 1/n⁴) is asserted.
3. Every number in the page's sample-deck table is recomputed with the solver.

The closed-form gates of the sample decks themselves are in
``tests/integration/test_sample_verification.py``; this module ties the page to them.
"""

import math
import re
from pathlib import Path

import numpy as np
import pytest

from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.mass_matrix import local_mass
from sbeam.assembly.stiffness import local_stiffness, transform_matrix
from sbeam.model.element import Cbar
from sbeam.model.grid import Grid
from sbeam.model.material import Mat1
from sbeam.model.property import Pbar
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol101 import run_sol101
from sbeam.solver.sol103 import run_sol103
from tests.samples import sample_path

REPO = Path(__file__).parent.parent.parent
DOC = REPO / "docs/20_theory/00_beam_methods.md"

BETA1 = 1.87510407      # first root of 1 + cos(βL)·cosh(βL) = 0
BETA2 = 4.69409113      # second root


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _table_after(heading: str) -> list[list[str]]:
    """Body rows of the first table after ``heading``, as lists of cell strings."""
    section = _text().split(heading, 1)[1]
    rows = []
    for line in section.splitlines():
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return rows[2:]          # drop the header and the rule


# ---------------------------------------------------------------------------
# 1. Element matrices from the shape functions
# ---------------------------------------------------------------------------

# Distinct values everywhere, so a swapped I1/I2 or a J used for the torsional
# inertia cannot pass by coincidence.
E, G, RHO = 2.0e11, 7.7e10, 7850.0
A, I1, I2, J, NSM = 0.05, 3.0e-4, 8.0e-4, 5.0e-4, 12.0
LENGTH = 1.7


def _shape_rows(x: float, L: float):
    """Rows of the interpolation matrix at ``x``, and the derivatives the strain
    energy needs, for the local DOF order [Tx Ty Tz Rx Ry Rz] at A then B.

    Returns (u, v, w, θx, u', v'', w'', θx').  v uses θz = +dv/dx; w uses θy = −dw/dx.
    """
    xi = x / L
    lin = np.array([1 - xi, xi])
    dlin = np.array([-1 / L, 1 / L])
    herm = np.array([1 - 3 * xi**2 + 2 * xi**3, L * (xi - 2 * xi**2 + xi**3),
                     3 * xi**2 - 2 * xi**3, L * (-xi**2 + xi**3)])
    d2herm = np.array([-6 + 12 * xi, L * (-4 + 6 * xi),
                       6 - 12 * xi, L * (-2 + 6 * xi)]) / L**2
    sign_w = np.array([1.0, -1.0, 1.0, -1.0])          # θy = −dw/dx

    def row(idx, vals):
        r = np.zeros(12)
        r[idx] = vals
        return r

    return (row([0, 6], lin), row([1, 5, 7, 11], herm), row([2, 4, 8, 10], sign_w * herm),
            row([3, 9], lin), row([0, 6], dlin), row([1, 5, 7, 11], d2herm),
            row([2, 4, 8, 10], sign_w * d2herm), row([3, 9], dlin))


def _integrated_matrices(L: float):
    """K and M by 4-point Gauss–Legendre quadrature (exact to degree 7; the mass
    integrand is degree 6)."""
    pts, wts = np.polynomial.legendre.leggauss(4)
    K = np.zeros((12, 12))
    M = np.zeros((12, 12))
    m_lin = RHO * A + NSM
    for p, wt in zip(pts, wts):
        x, w_x = 0.5 * L * (p + 1.0), 0.5 * L * wt
        u, v, w, th, du, d2v, d2w, dth = _shape_rows(x, L)
        K += w_x * (E * A * np.outer(du, du) + E * I1 * np.outer(d2v, d2v)
                    + E * I2 * np.outer(d2w, d2w) + G * J * np.outer(dth, dth))
        M += w_x * (m_lin * (np.outer(u, u) + np.outer(v, v) + np.outer(w, w))
                    + RHO * (I1 + I2) * np.outer(th, th))
    return K, M


@pytest.fixture(scope="module")
def section():
    return (Pbar(pid=1, mid=1, A=A, I1=I1, I2=I2, J=J, nsm=NSM),
            Mat1(mid=1, E=E, G=G, nu=0.3, rho=RHO))


def test_stiffness_is_the_strain_energy_integral_of_the_shape_functions(section) -> None:
    pbar, mat1 = section
    K_int, _ = _integrated_matrices(LENGTH)
    K = local_stiffness(pbar, mat1, LENGTH)
    assert np.allclose(K, K_int, rtol=1e-12, atol=1e-12 * np.abs(K).max())


def test_mass_is_the_kinetic_energy_integral_of_the_same_shape_functions(section) -> None:
    pbar, mat1 = section
    _, M_int = _integrated_matrices(LENGTH)
    M = local_mass(pbar, mat1, LENGTH)
    assert np.allclose(M, M_int, rtol=1e-12, atol=1e-12 * np.abs(M).max())


def test_plane_1_takes_i1_and_plane_2_takes_i2(section) -> None:
    """The page's table of blocks: I1 on (Ty, Rz), I2 on (Tz, Ry)."""
    pbar, mat1 = section
    K = local_stiffness(pbar, mat1, LENGTH)
    assert K[1, 1] == pytest.approx(12 * E * I1 / LENGTH**3)
    assert K[2, 2] == pytest.approx(12 * E * I2 / LENGTH**3)
    assert K[1, 5] > 0 > K[2, 4]                       # θz = +dv/dx, θy = −dw/dx


def test_local_axes_follow_the_orientation_vector() -> None:
    """e_x along GA→GB; e_y the part of v normal to e_x; e_z = e_x × e_y."""
    grids = {1: Grid(gid=1, x=1.0, y=2.0, z=3.0), 2: Grid(gid=2, x=4.0, y=6.0, z=3.0)}
    v = np.array([0.3, -0.2, 1.0])
    cbar = Cbar(eid=1, pid=1, ga=1, gb=2, x1=v[0], x2=v[1], x3=v[2])
    T = transform_matrix(cbar, grids)
    R = T[:3, :3]
    e_x = np.array([3.0, 4.0, 0.0]) / 5.0
    assert np.allclose(R[0], e_x)
    assert R[1] @ e_x == pytest.approx(0.0, abs=1e-15)
    assert R[1] @ v > 0.0
    assert np.linalg.det(np.array([e_x, v, R[1]])) == pytest.approx(0.0, abs=1e-12)
    assert np.allclose(R[2], np.cross(R[0], R[1]))
    assert np.allclose(T.T @ T, np.eye(12))
    assert all(np.allclose(T[3 * i:3 * i + 3, 3 * i:3 * i + 3], R) for i in range(4))


# ---------------------------------------------------------------------------
# 2. Mesh convergence, on the properties of the shipped cantilever deck
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def deck_props():
    _, bulk = parse_bdf(str(sample_path("val_cantilever_modes.bdf")))
    mat = next(iter(bulk.mat1s.values()))
    pbar = next(iter(bulk.pbars.values()))
    length = max(g.x for g in bulk.grids.values())
    return mat, pbar, length


def _cantilever(tmp_path: Path, n: int, mat: Mat1, pbar: Pbar, length: float,
                sol: int) -> Path:
    """An n-element cantilever along X with the sample deck's material and section."""
    lines = [f"SOL {sol}", "SUBCASE 1", "  SPC = 1",
             "  METHOD = 20" if sol == 103 else "  LOAD = 10", "BEGIN BULK"]
    lines += [f"GRID, {i + 1}, , {length * i / n!r}, 0.0, 0.0" for i in range(n + 1)]
    lines += [f"CBAR, {i + 1}, 1, {i + 1}, {i + 2}, 0.0, 1.0, 0.0" for i in range(n)]
    lines += [f"MAT1, 1, {mat.E!r}, {mat.G!r}, 0.3, {mat.rho!r}",
              f"PBAR, 1, 1, {pbar.A!r}, {pbar.I1!r}, {pbar.I2!r}, {pbar.J!r}",
              "SPC1, 1, 123456, 1",
              "EIGRL, 20, , , 1" if sol == 103 else f"FORCE, 10, {n + 1}, 0, 1000.0, 0.0, 0.0, -1.0",
              "ENDDATA"]
    path = tmp_path / f"cantilever_{sol}_{n}.bdf"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _f1(tmp_path: Path, n: int, props) -> float:
    cc, bulk = parse_bdf(str(_cantilever(tmp_path, n, *props, sol=103)))
    return float(run_sol103(bulk, cc.subcases[0]).frequencies_hz[0])


def _closed_form_hz(props, beta: float) -> float:
    mat, pbar, length = props
    return (beta**2 / (2 * math.pi)) * math.sqrt(mat.E * pbar.I1 / (mat.rho * pbar.A * length**4))


#: Round-off of the eigenvalue solve in f1, as a fraction of f1.  Two runs of one commit
#: on different CI runners gave 5.2004e-8 and 5.2263e-8 for the 20-element error, a
#: scatter of 2.6e-10 of f1 (#134).  The floor is about eight times that, and still 400
#: times below the 10-element error, so only the 20-element row is loosened (to 4 %).
F1_ROUNDOFF = 2e-9


def test_convergence_table_is_what_the_solver_gives(tmp_path, deck_props) -> None:
    exact = _closed_form_hz(deck_props, BETA1)
    rows = _table_after("## 6. Mesh convergence")
    assert [int(r[0]) for r in rows] == [1, 2, 3, 5, 10, 20]
    for n_text, f_text, err_text in rows:
        f1 = _f1(tmp_path, int(n_text), deck_props)
        assert f1 == pytest.approx(float(f_text), abs=6e-7), f"n = {n_text}"
        assert (f1 - exact) / exact == pytest.approx(
            float(err_text), rel=5e-3, abs=F1_ROUNDOFF), f"n = {n_text}"


def test_frequency_converges_from_above_at_fourth_order(tmp_path, deck_props) -> None:
    """Predicted outside the code: a conforming element with consistent mass is a
    Rayleigh–Ritz method, so f1 is an upper bound; the cubic element's eigenvalue error
    is O(h⁴), so doubling the element count divides the error by 16."""
    exact = _closed_form_hz(deck_props, BETA1)
    err = {n: (_f1(tmp_path, n, deck_props) - exact) / exact for n in (5, 10, 20)}
    assert all(e > 0.0 for e in err.values())
    assert err[5] / err[10] == pytest.approx(16.0, rel=0.05)
    assert err[10] / err[20] == pytest.approx(16.0, rel=0.05)


def test_one_element_gives_the_exact_tip_deflection(tmp_path, deck_props) -> None:
    """The cubic is the exact solution of EI·w'''' = 0 between point loads."""
    mat, pbar, length = deck_props
    cc, bulk = parse_bdf(str(_cantilever(tmp_path, 1, *deck_props, sol=101)))
    result = run_sol101(bulk, cc.subcases[0])
    tip = 6 * build_grid_index(bulk)[2]
    assert result.displacements[tip + 2] == pytest.approx(
        -1000.0 * length**3 / (3 * mat.E * pbar.I2), rel=1e-12)


# ---------------------------------------------------------------------------
# 3. The sample-deck table
# ---------------------------------------------------------------------------

def _number(cell: str) -> float:
    return float(re.search(r"-?\d+\.\d+(?:[eE][+-]?\d+)?", cell.replace("−", "-")).group())


def test_sample_deck_table_is_what_the_solver_gives() -> None:
    rows = {r[0]: r for r in _table_after("## 7. The code against the closed forms")}

    cc, bulk = parse_bdf(str(sample_path("val_cantilever_static.bdf")))
    static = run_sol101(bulk, cc.subcases[0])
    tip = 6 * build_grid_index(bulk)[11]
    mat = next(iter(bulk.mat1s.values()))
    pbar = next(iter(bulk.pbars.values()))
    P, L = 1000.0, 10.0
    solved = {
        "Tip deflection Tz, m": (-P * L**3 / (3 * mat.E * pbar.I2), static.displacements[tip + 2]),
        "Tip rotation Ry, rad": (P * L**2 / (2 * mat.E * pbar.I2), static.displacements[tip + 4]),
        "Root reaction Fz, N": (P, static.reactions[1][2]),
        "Root reaction My, N·m": (-P * L, static.reactions[1][4]),
    }
    cc, bulk = parse_bdf(str(sample_path("val_cantilever_modes.bdf")))
    modal = run_sol103(bulk, cc.subcases[0])
    props = (mat, pbar, L)
    solved["f1, Hz"] = (_closed_form_hz(props, BETA1), modal.frequencies_hz[0])
    solved["f2, Hz"] = (_closed_form_hz(props, BETA2), modal.frequencies_hz[1])

    assert set(rows) == set(solved)
    for label, (closed, computed) in solved.items():
        row = rows[label]
        assert _number(row[2]) == pytest.approx(closed, rel=5e-7), f"{label}: closed form"
        assert _number(row[3]) == pytest.approx(computed, rel=5e-7), f"{label}: sbeam"


def test_every_relative_link_on_the_page_resolves() -> None:
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", _text()):
        if not target.startswith("http"):
            assert (DOC.parent / target).exists(), target
