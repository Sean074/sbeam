"""Unit tests for the structure-to-aero coupling layer (Phase C).

build_qaa / build_fg / build_gaf are pure linear algebra over the AeroModel
matrices and the two beam-spline operators, so they are tested here against
*hand-built* G operators — no real spline required yet.

Covers:
  - build_qaa: shape, exact matrix-chain identity, rigid-translation → zero Q_aa
  - build_fg : shape, exact identity, zero baseline normalwash → zero f_g
  - build_gaf: Phi = I recovers qaa; symmetry preserved; modal reduction shape
  - shape-validation ValueErrors on every operator
  - end-to-end wiring against a real build_aero_model AeroModel
"""

import numpy as np
import pytest

from sbeam.aero.aero_model import AeroModel, build_aero_model
from sbeam.aero.coupling import build_qaa, build_fg, build_gaf
from sbeam.model.aero import Caero1, Paero1
from sbeam.model.bulk_data import BulkData


# ---------------------------------------------------------------------------
# Synthetic AeroModel — only the fields coupling.py reads need to be real.
# (boxes is used solely for len(); the matrices drive the algebra.)
# ---------------------------------------------------------------------------

def _synthetic_aero(n: int, seed: int = 0) -> AeroModel:
    rng = np.random.default_rng(seed)
    ajj = rng.standard_normal((n, n))
    ajj_inv_corr = np.linalg.inv(ajj)
    skj = rng.standard_normal((3 * n, n))
    djk = -np.eye(n)                       # k = 0 deflection→downwash (build_djk)
    wg = rng.standard_normal(n)
    return AeroModel(
        boxes=list(range(n)),              # len() is all coupling.py needs
        ajj=ajj,
        ajj_inv_corr=ajj_inv_corr,
        skj=skj,
        djk=djk,
        wg=wg,
        parity=1,
    )


# ---------------------------------------------------------------------------
# build_qaa
# ---------------------------------------------------------------------------

def test_qaa_shape_and_identity():
    n, n_g = 3, 5
    aero = _synthetic_aero(n)
    rng = np.random.default_rng(1)
    g_slope = rng.standard_normal((n, n_g))
    g_disp = rng.standard_normal((3 * n, n_g))

    qaa = build_qaa(aero, g_disp, g_slope)

    assert qaa.shape == (n_g, n_g)
    expected = g_disp.T @ aero.skj @ aero.ajj_inv_corr @ aero.djk @ g_slope
    assert np.allclose(qaa, expected)


def test_qaa_rigid_translation_gives_zero():
    """A rigid translation produces zero box incidence (g_slope = 0), hence no
    deflection-induced aero stiffness — the rigid-body-exactness expectation."""
    n, n_g = 4, 6
    aero = _synthetic_aero(n)
    g_disp = np.random.default_rng(2).standard_normal((3 * n, n_g))
    g_slope = np.zeros((n, n_g))

    qaa = build_qaa(aero, g_disp, g_slope)
    assert np.allclose(qaa, 0.0)


@pytest.mark.parametrize(
    "g_disp_shape, g_slope_shape",
    [
        ((3 * 3, 5), (3, 4)),      # n_g mismatch between operators
        ((3 * 3, 5), (2, 5)),      # g_slope wrong n_box
        ((2 * 3, 5), (3, 5)),      # g_disp wrong 3*n_box
    ],
)
def test_qaa_shape_validation(g_disp_shape, g_slope_shape):
    aero = _synthetic_aero(3)
    g_disp = np.zeros(g_disp_shape)
    g_slope = np.zeros(g_slope_shape)
    with pytest.raises(ValueError):
        build_qaa(aero, g_disp, g_slope)


# ---------------------------------------------------------------------------
# build_fg
# ---------------------------------------------------------------------------

def test_fg_shape_and_identity():
    n, n_g = 3, 5
    aero = _synthetic_aero(n)
    g_disp = np.random.default_rng(3).standard_normal((3 * n, n_g))

    fg = build_fg(aero, g_disp)

    assert fg.shape == (n_g,)
    expected = g_disp.T @ aero.skj @ (aero.ajj_inv_corr @ aero.wg)
    assert np.allclose(fg, expected)


def test_fg_zero_baseline_normalwash_gives_zero():
    n, n_g = 4, 6
    aero = _synthetic_aero(n)
    aero.wg = np.zeros(n)
    g_disp = np.random.default_rng(4).standard_normal((3 * n, n_g))
    assert np.allclose(build_fg(aero, g_disp), 0.0)


def test_fg_shape_validation():
    aero = _synthetic_aero(3)
    with pytest.raises(ValueError):
        build_fg(aero, np.zeros((2 * 3, 5)))   # wrong 3*n_box


# ---------------------------------------------------------------------------
# build_gaf
# ---------------------------------------------------------------------------

def test_gaf_identity_basis_recovers_qaa():
    n = 4
    qaa = np.random.default_rng(5).standard_normal((n, n))
    phi = np.eye(n)
    assert np.allclose(build_gaf(qaa, phi), qaa)


def test_gaf_preserves_symmetry_and_reduces():
    n, n_m = 6, 2
    a = np.random.default_rng(6).standard_normal((n, n))
    qaa_sym = a + a.T
    phi = np.random.default_rng(7).standard_normal((n, n_m))

    qhh = build_gaf(qaa_sym, phi)

    assert qhh.shape == (n_m, n_m)
    assert np.allclose(qhh, qhh.T)                         # symmetry preserved
    assert np.allclose(qhh, phi.T @ qaa_sym @ phi)         # exact identity


def test_gaf_shape_validation():
    with pytest.raises(ValueError):
        build_gaf(np.zeros((3, 4)), np.zeros((3, 2)))      # qaa not square
    with pytest.raises(ValueError):
        build_gaf(np.zeros((4, 4)), np.zeros((3, 2)))      # phi rows != qaa rows


# ---------------------------------------------------------------------------
# End-to-end wiring against a real AeroModel (guards field-name drift)
# ---------------------------------------------------------------------------

def test_coupling_against_real_aero_model():
    caero = Caero1(
        eid=1, pid=1, cp=0,
        nspan=3, nchord=2, lspan=0, lchord=0, igid=0,
        p1=(0.0, 0.0, 0.0), x12=1.0,
        p4=(0.0, 4.0, 0.0), x43=1.0,
    )
    bulk = BulkData()
    bulk.caero1s = {1: caero}
    bulk.paero1s = {1: Paero1(pid=1)}
    aero = build_aero_model(bulk, parity=1)

    n = len(aero.boxes)
    n_g, n_m = 7, 2
    rng = np.random.default_rng(8)
    g_slope = rng.standard_normal((n, n_g))
    g_disp = rng.standard_normal((3 * n, n_g))
    phi = rng.standard_normal((n_g, n_m))

    qaa = build_qaa(aero, g_disp, g_slope)
    fg = build_fg(aero, g_disp)
    qhh = build_gaf(qaa, phi)

    assert qaa.shape == (n_g, n_g)
    assert fg.shape == (n_g,)
    assert qhh.shape == (n_m, n_m)
    assert np.all(np.isfinite(qaa)) and np.all(np.isfinite(fg)) and np.all(np.isfinite(qhh))
