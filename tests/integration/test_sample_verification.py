"""P5: Closed-form CI gates for the four CLAUDE.md verification decks.

CLAUDE.md ("Verification Test Cases") declares four closed-form results that every
solver must reproduce, and ``sample/`` ships the four decks that embody them:

    sample/val_cantilever_static.bdf   SOL 101   delta_tip = P*L^3 / (3*E*I)
    sample/val_ss_static.bdf           SOL 101   delta_mid = P*L^3 / (48*E*I)
    sample/val_cantilever_modes.bdf    SOL 103   f1 = (beta1^2 / 2*pi) * sqrt(E*I / rho*A*L^4)
    sample/val_free_free_modes.bdf     SOL 103   first 6 modes ~ 0 Hz

A fifth shipped deck added 2026-08-01 is gated here in the same style:

    sample/val_cantilever_offset_mass_modes.bdf   SOL 103   coupled bending-torsion
        pair from a transverse-offset tip CONM2 (2-DOF closed form, see class)

Until this module existed the shipped decks were exercised only by
``docs/20_theory/00_beam_methods.ipynb``, which CI never runs — the V1-V20 suite in
``test_verification.py`` gates its own private decks in ``tests/integration/bdf/``
(L = 1 m, A = 0.05), not these. Any regression in the decks users actually copy
reached a release silently.

Every expected value is recomputed from properties read back out of the parsed deck
(see ``_beam_props``), never from module constants — so editing a deck either keeps
these gates honest or fails them for a real reason.

Note: ``val_cantilever_modes.bdf``'s header carries a stale "f2 ~ 2.58 Hz (XY)"
comment. The deck's own ``SPC1, 1, 12, ...`` suppresses the XY bending family, so f2
is the *second XZ* bending mode at 16.16 Hz — gated below. Correcting the comment
belongs to the sample-hygiene batch in docs/30_future/00_backlog.md.
"""

import math
from pathlib import Path
from typing import NamedTuple

import pytest

from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.bulk_data import BulkData
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.results import Sol101Result, Sol103Result
from sbeam.solver.sol101 import run_sol101
from sbeam.solver.sol103 import run_sol103
from sbeam.types import FloatArray

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"

#: (result, grid_index, bulk) — the bulk is carried so gates can read the deck's
#: own properties back out rather than trust a module constant.
StaticFixture = tuple[Sol101Result, dict[int, int], BulkData]

#: (result, bulk) — modal gates need no grid index.
ModalFixture = tuple[Sol103Result, BulkData]

# Euler-Bernoulli mode-shape eigenvalues (roots of the characteristic equation)
BETA_CANTILEVER = (1.875104, 4.694091)  # clamped-free, modes 1 and 2
BETA_FREE_FREE = 4.730041               # free-free, first elastic mode

# The consistent Euler-Bernoulli formulation is exact at the nodes for point loads,
# so the static gates run at round-off + 3 decades, not at an engineering tolerance.
STATIC_REL = 1.0e-9


class BeamProps(NamedTuple):
    """Beam properties read back from the parsed deck."""

    E: float
    I: float
    A: float
    rho: float
    L: float

    def flexural_hz(self, beta: float) -> float:
        """Closed-form bending frequency (Hz) for mode-shape eigenvalue ``beta``."""
        return (beta**2 / (2.0 * math.pi)) * math.sqrt(self.E * self.I / (self.rho * self.A * self.L**4))


def _beam_props(bulk: BulkData) -> BeamProps:
    """Read E, I, A, rho and the beam length back out of the deck.

    All four decks share one MAT1, one PBAR (I1 == I2) and a straight beam along X.
    """
    mat = next(iter(bulk.mat1s.values()))
    pbar = next(iter(bulk.pbars.values()))
    assert pbar.I1 == pytest.approx(pbar.I2), "decks assume a symmetric section (I1 == I2)"
    xs = [g.x for g in bulk.grids.values()]
    return BeamProps(E=mat.E, I=pbar.I1, A=pbar.A, rho=mat.rho, L=max(xs) - min(xs))


def _point_load_z(bulk: BulkData, sid: int) -> float:
    """Signed Z-component of the single FORCE card in load set ``sid``."""
    forces = bulk.forces[sid]
    assert len(forces) == 1, f"expected one FORCE card in set {sid}, found {len(forces)}"
    force = forces[0]
    return force.f * force.n3


def _run_static(name: str) -> StaticFixture:
    cc, bulk = parse_bdf(str(SAMPLE_DIR / name))
    assert cc.sol == 101
    return run_sol101(bulk, cc.subcases[0]), build_grid_index(bulk), bulk


def _run_modal(name: str) -> ModalFixture:
    cc, bulk = parse_bdf(str(SAMPLE_DIR / name))
    assert cc.sol == 103
    return run_sol103(bulk, cc.subcases[0]), bulk


@pytest.fixture(scope="module")
def cantilever_static() -> StaticFixture:
    return _run_static("val_cantilever_static.bdf")


@pytest.fixture(scope="module")
def ss_static() -> StaticFixture:
    return _run_static("val_ss_static.bdf")


@pytest.fixture(scope="module")
def cantilever_modes() -> ModalFixture:
    return _run_modal("val_cantilever_modes.bdf")


@pytest.fixture(scope="module")
def free_free_modes() -> ModalFixture:
    return _run_modal("val_free_free_modes.bdf")


@pytest.fixture(scope="module")
def offset_mass_modes() -> ModalFixture:
    return _run_modal("val_cantilever_offset_mass_modes.bdf")


class TestValCantileverStatic:
    """sample/val_cantilever_static.bdf — delta_tip = P*L^3 / (3*E*I)."""

    def test_tip_deflection(self, cantilever_static: StaticFixture) -> None:
        result, grid_index, bulk = cantilever_static
        p = _beam_props(bulk)
        fz = _point_load_z(bulk, 10)          # -1000 N (acts in -Z)
        expected = fz * p.L**3 / (3.0 * p.E * p.I)
        assert expected < 0.0                 # guards the deck's load direction
        tip_tz = result.displacements[6 * grid_index[11] + 2]
        assert tip_tz == pytest.approx(expected, rel=STATIC_REL)

    def test_tip_rotation(self, cantilever_static: StaticFixture) -> None:
        """theta_tip = P*L^2 / (2*E*I); a -Z tip load gives a positive Ry rotation."""
        result, grid_index, bulk = cantilever_static
        p = _beam_props(bulk)
        fz = _point_load_z(bulk, 10)
        expected = -fz * p.L**2 / (2.0 * p.E * p.I)
        tip_ry = result.displacements[6 * grid_index[11] + 4]
        assert tip_ry > 0.0
        assert tip_ry == pytest.approx(expected, rel=STATIC_REL)

    def test_root_reactions(self, cantilever_static: StaticFixture) -> None:
        """Global equilibrium at the clamped root: Fz = P, My = -P*L."""
        result, _grid_index, bulk = cantilever_static
        p = _beam_props(bulk)
        fz = _point_load_z(bulk, 10)
        root = result.reactions[1]
        assert root[2] == pytest.approx(-fz, rel=STATIC_REL)
        assert root[4] == pytest.approx(fz * p.L, rel=STATIC_REL)


class TestValSsStatic:
    """sample/val_ss_static.bdf — delta_mid = P*L^3 / (48*E*I)."""

    def test_midspan_deflection(self, ss_static: StaticFixture) -> None:
        result, grid_index, bulk = ss_static
        p = _beam_props(bulk)
        fz = _point_load_z(bulk, 10)
        expected = fz * p.L**3 / (48.0 * p.E * p.I)
        assert expected < 0.0
        mid_tz = result.displacements[6 * grid_index[6] + 2]
        assert mid_tz == pytest.approx(expected, rel=STATIC_REL)

    def test_support_reactions(self, ss_static: StaticFixture) -> None:
        """A mid-span load splits evenly: P/2 at the pin and P/2 at the roller."""
        result, _grid_index, bulk = ss_static
        fz = _point_load_z(bulk, 10)
        pin_fz = result.reactions[1][2]
        roller_fz = result.reactions[11][2]
        assert pin_fz == pytest.approx(-fz / 2.0, rel=STATIC_REL)
        assert roller_fz == pytest.approx(-fz / 2.0, rel=STATIC_REL)
        assert pin_fz + roller_fz == pytest.approx(-fz, rel=STATIC_REL)


class TestValCantileverModes:
    """sample/val_cantilever_modes.bdf — f_n = (beta_n^2 / 2*pi) * sqrt(E*I / rho*A*L^4)."""

    def test_frequencies_ascending(self, cantilever_modes: ModalFixture) -> None:
        result, _bulk = cantilever_modes
        freqs = result.frequencies_hz
        assert len(freqs) >= 2
        assert all(freqs[i] <= freqs[i + 1] for i in range(len(freqs) - 1))

    def test_first_bending_mode(self, cantilever_modes: ModalFixture) -> None:
        """f1 ~ 2.5784 Hz — the CLAUDE.md cantilever fundamental."""
        result, bulk = cantilever_modes
        expected = _beam_props(bulk).flexural_hz(BETA_CANTILEVER[0])
        assert result.frequencies_hz[0] == pytest.approx(expected, rel=1.0e-5)

    def test_second_bending_mode(self, cantilever_modes: ModalFixture) -> None:
        """f2 ~ 16.159 Hz — the second XZ bending mode, not the XY family the deck's
        SPC1 suppresses (the deck header comment is stale; see the module docstring)."""
        result, bulk = cantilever_modes
        expected = _beam_props(bulk).flexural_hz(BETA_CANTILEVER[1])
        assert result.frequencies_hz[1] == pytest.approx(expected, rel=2.0e-4)


class TestValFreeFreeModes:
    """sample/val_free_free_modes.bdf — exactly six rigid-body modes, then elastic."""

    def test_six_rigid_body_modes(self, free_free_modes: ModalFixture) -> None:
        """3 translations + 3 rotations at ~0 Hz; measured max is ~4.6e-5 Hz."""
        result, _bulk = free_free_modes
        assert len(result.frequencies_hz) >= 7
        assert all(f < 1.0e-3 for f in result.frequencies_hz[:6])

    def test_no_seventh_zero_mode(self, free_free_modes: ModalFixture) -> None:
        """Mode 7 must be genuinely elastic — no spurious extra mechanism."""
        result, _bulk = free_free_modes
        freqs = result.frequencies_hz
        assert freqs[6] > 1.0
        assert freqs[6] / max(freqs[5], 1.0e-12) > 1.0e3

    def test_first_elastic_mode(self, free_free_modes: ModalFixture) -> None:
        """f7 ~ 16.407 Hz — free-free first bending, beta = 4.730041."""
        result, bulk = free_free_modes
        expected = _beam_props(bulk).flexural_hz(BETA_FREE_FREE)
        assert result.frequencies_hz[6] == pytest.approx(expected, rel=2.0e-4)


class TestValCantileverOffsetMassModes:
    """sample/val_cantilever_offset_mass_modes.bdf — coupled bending-torsion pair.

    A tip CONM2 whose CG sits d off the elastic axis couples Z-bending with
    torsion through the offset mass block. Tip-dominant 2-DOF closed form with
    Rayleigh corrections for the distributed beam mass:

        M = [[m + (33/140)*rho*A*L,  m*d              ],
             [m*d,                   m*d^2 + I11 + rho*Ip*L/3]]
        K = diag(3*E*I/L^3, G*J/L)          (Ip = I1 + I2)

    Like the other gates, every constant is read back out of the parsed deck.
    """

    @staticmethod
    def _closed_form_hz(bulk: BulkData) -> FloatArray:
        import numpy as np
        from scipy.linalg import eigh as sp_eigh

        p = _beam_props(bulk)
        mat = next(iter(bulk.mat1s.values()))
        pbar = next(iter(bulk.pbars.values()))
        conm2 = next(iter(bulk.conm2s.values()))
        assert conm2.x1 == 0.0 and conm2.x3 == 0.0, "deck assumes a pure +Y offset"
        m, d, i11 = conm2.m, conm2.x2, conm2.i11

        k_w = 3.0 * p.E * p.I / p.L**3
        k_t = mat.G * pbar.J / p.L
        m_eff = m + (33.0 / 140.0) * p.rho * p.A * p.L
        i_eff = m * d**2 + i11 + p.rho * (pbar.I1 + pbar.I2) * p.L / 3.0
        M = np.array([[m_eff, m * d], [m * d, i_eff]])
        K = np.diag([k_w, k_t])
        vals = sp_eigh(K, M, eigvals_only=True)
        return np.sqrt(vals) / (2.0 * math.pi)

    def test_coupled_pair_frequencies(self, offset_mass_modes: ModalFixture) -> None:
        """f1 ~ 0.1489 Hz, f2 ~ 0.7466 Hz — measured FE error 1.4e-5 / 9.6e-4."""
        result, bulk = offset_mass_modes
        expected = self._closed_form_hz(bulk)
        assert result.frequencies_hz[0] == pytest.approx(expected[0], rel=2.0e-3)
        assert result.frequencies_hz[1] == pytest.approx(expected[1], rel=2.0e-3)

    def test_modes_are_coupled(self, offset_mass_modes: ModalFixture) -> None:
        """Both modes carry twist AND deflection: tip Rx*d/Tz ~ +0.10 and ~ -0.99."""
        result, bulk = offset_mass_modes
        grid_index = build_grid_index(bulk)
        conm2 = next(iter(bulk.conm2s.values()))
        tip = 6 * grid_index[conm2.gid]
        for mode, lo, hi in ((0, 0.05, 0.5), (1, -1.5, -0.5)):
            shape = result.mode_shapes[:, mode]
            ratio = shape[tip + 3] * conm2.x2 / shape[tip + 2]
            assert lo < ratio < hi, f"mode {mode + 1} twist participation {ratio}"

    def test_offset_removal_decouples(self) -> None:
        """With the CONM2 offset zeroed the families separate: mode 1 is pure
        bending at sqrt(k_w/m_eff)/2pi and the torsion mode is Rx-only."""
        cc, bulk = parse_bdf(str(SAMPLE_DIR / "val_cantilever_offset_mass_modes.bdf"))
        conm2 = next(iter(bulk.conm2s.values()))
        conm2.x2 = 0.0
        result = run_sol103(bulk, cc.subcases[0])

        expected = self._closed_form_hz(bulk)   # m*d terms vanish with x2 = 0
        assert result.frequencies_hz[0] == pytest.approx(expected[0], rel=2.0e-3)
        assert result.frequencies_hz[1] == pytest.approx(expected[1], rel=2.0e-3)

        grid_index = build_grid_index(bulk)
        tip = 6 * grid_index[conm2.gid]
        bending = result.mode_shapes[:, 0]
        torsion = result.mode_shapes[:, 1]
        assert abs(bending[tip + 3]) < 1.0e-8 * abs(bending[tip + 2])
        assert abs(torsion[tip + 2]) < 1.0e-8 * abs(torsion[tip + 3])
