"""Step 67a — the quasi-steady yaw-rate WING term (loading-scaled force column).

Theory §7.2 Eq. 28 gives yaw rate two effects: the fin sidewash Δβ(x) = r(x−x_ref)/V
(the `build_djx` YAW normalwash column, in since AE11) and the wing's spanwise
dynamic-pressure asymmetry ΔU(y) = −r·y.  The second is an edgewise-velocity
perturbation, not a normalwash, so it cannot be a `D_jx` column; it enters as a
loading-scaled force term

    Δf_box = 2(ΔU/U)·f_box,steady = −(4/b_ref)·(y−y_ref)·YAW · f_box,steady

(`aero.integration.build_fjx_yaw`), evaluated at the trim loading.

The sharp gate here is the closed-form roll-rate cross-derivative.  In force/q
units the identity is exact:

    C_lr = ∂C_l/∂(rb/2V) = −(4/(S_ref·b_ref²))·Σ_j (y_j−y_ref)²·F_z,j

and for a near-elliptic spanwise load Σ y²F_z = (b²/16)·CL·S, i.e. |C_lr| = CL/4 —
the strip-theory result.  That C_lr tracks the trim CL *exactly* (test
`test_c_lr_scales_linearly_with_trim_cl`) is the property that motivated choosing
the loading-scaled form over the rejected lift-slope proxy, so it is asserted
directly rather than inferred.

Sign convention: as in `test_lateral_derivs.py`, moments are the full
3-component resultant in sbeam's z-up / y-starboard frame.  The assertions below
are written against that frame's handedness; the convention-independent content
is the magnitude, the antisymmetry, and the CL proportionality.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_file, parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import (
    build_djx, build_fjx_yaw, build_fj_rigidrate_yaw, rigid_rate_scales,
    yaw_rate_force_scale,
)
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aestat, require_aeros
from sbeam.solver.sol144 import compute_rigid_derivs, run_sol144_trim

SAMPLE = Path(__file__).parent.parent.parent / "sample"
LABELS = ["ANGLEA", "ROLL", "YAW", "SIDES"]


# ---------------------------------------------------------------------------
# Rigid aero-only fixtures (val_vlm_rect_ar8: full-span AR=8, S=b=8, c=1)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rect():
    """(bulk, aero) for the full-span rectangular AR=8 validation wing."""
    bulk = parse_bulk_file(str(SAMPLE / "val_vlm_rect_ar8.bdf"))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero


def _rigid_loading(bulk, aero, alpha):
    """Steady box-force field (force/q) of the rigid wing at incidence alpha."""
    djx = build_djx(aero.boxes, ["ANGLEA"], bulk)
    return aero.skj @ (aero.ajj_inv_corr @ (alpha * djx[:, 0]))


def _derivs(bulk, aero, f_box_yaw=None):
    djx = build_djx(aero.boxes, LABELS, bulk)
    return compute_rigid_derivs(
        aero, djx, LABELS, bulk, 0.0, np.zeros(3), f_box_yaw=f_box_yaw)


# ---------------------------------------------------------------------------
# 1. The scale vector itself
# ---------------------------------------------------------------------------

def test_scale_is_the_derived_geometric_factor(rect):
    """s_j == −(4/b_ref)·(y_j − y_ref) at the box FORCE point, exactly."""
    bulk, aero = rect
    b_ref = require_aeros(bulk).bref
    for y_ref in (0.0, 1.5):
        s = yaw_rate_force_scale(aero.boxes, bulk, y_ref)
        expected = np.array(
            [-(4.0 / b_ref) * (b.force_point[1] - y_ref) for b in aero.boxes])
        assert np.allclose(s, expected, rtol=0, atol=0)


def test_scale_is_antisymmetric_and_zero_at_the_reference(rect):
    """A full-span mesh is mirror-symmetric in y, so s is antisymmetric about
    y_ref and vanishes there."""
    bulk, aero = rect
    s = yaw_rate_force_scale(aero.boxes, bulk)
    y = np.array([b.force_point[1] for b in aero.boxes])
    order = np.argsort(y)
    mirror = np.argsort(-y)
    assert np.allclose(s[order], -s[mirror], rtol=1e-12, atol=1e-14)
    assert np.allclose(yaw_rate_force_scale(aero.boxes, bulk, float(y.max())),
                       -(4.0 / require_aeros(bulk).bref) * (y - y.max()))


def test_force_column_is_the_scaled_reference_load(rect):
    """build_fjx_yaw scales the FULL 3-vector of each box force, box-major."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(4.0))
    col = build_fjx_yaw(aero.boxes, f_ref, bulk)
    s = yaw_rate_force_scale(aero.boxes, bulk)
    for j in range(len(aero.boxes)):
        assert np.allclose(col[3 * j:3 * j + 3], s[j] * f_ref[3 * j:3 * j + 3])


def test_zero_reference_loading_gives_a_zero_column(rect):
    """No load ⇒ no yaw-rate increment.  Exactly zero, not just small."""
    bulk, aero = rect
    col = build_fjx_yaw(aero.boxes, np.zeros(3 * len(aero.boxes)), bulk)
    assert np.array_equal(col, np.zeros_like(col))


def test_physical_rate_column_matches_the_label_column(rect):
    """The physical-r column is the label column through the single owner of the
    rate nondimensionalization (rigid_rate_scales), so the trim-label and
    free-flight paths cannot drift apart."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(4.0))
    v_inf = 250.0
    phys = build_fj_rigidrate_yaw(aero.boxes, f_ref, bulk, v_inf)
    label = build_fjx_yaw(aero.boxes, f_ref, bulk)
    assert np.allclose(phys, rigid_rate_scales(bulk, v_inf)[6] * label,
                       rtol=0, atol=0)
    # ... and equals the raw physical form −2·(y/V)·f_ref.
    y = np.repeat([b.force_point[1] for b in aero.boxes], 3)
    assert np.allclose(phys, -2.0 * (y / v_inf) * f_ref, rtol=1e-12)


# ---------------------------------------------------------------------------
# 2. C_lr — the closed-form gate
# ---------------------------------------------------------------------------

def _c_lr_closed_form(bulk, aero, f_ref, y_ref=0.0):
    aeros = require_aeros(bulk)
    y = np.array([b.force_point[1] for b in aero.boxes]) - y_ref
    fz = f_ref[2::3]
    return -(4.0 / (aeros.sref * aeros.bref ** 2)) * float((y ** 2 * fz).sum())


def test_c_lr_matches_the_closed_form(rect):
    """The CMX entry of the YAW column reproduces
    −(4/(S·b²))·Σ y²F_z to machine precision (it IS that sum, integrated)."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(5.0))
    col = build_fjx_yaw(aero.boxes, f_ref, bulk)
    c_lr = _derivs(bulk, aero, f_box_yaw=col)["YAW"]["CMX"]
    assert c_lr == pytest.approx(_c_lr_closed_form(bulk, aero, f_ref), rel=1e-12)


def test_c_lr_is_a_quarter_of_the_trim_cl(rect):
    """Strip theory: |C_lr| = CL/4 for near-elliptic loading.  A rectangular
    AR=8 wing is not elliptic, so allow ~15 %."""
    bulk, aero = rect
    alpha = np.radians(5.0)
    f_ref = _rigid_loading(bulk, aero, alpha)
    cl = float(f_ref[2::3].sum()) / require_aeros(bulk).sref
    col = build_fjx_yaw(aero.boxes, f_ref, bulk)
    c_lr = _derivs(bulk, aero, f_box_yaw=col)["YAW"]["CMX"]
    assert abs(c_lr) == pytest.approx(cl / 4.0, rel=0.15)


def test_c_lr_scales_linearly_with_trim_cl(rect):
    """The property the loading-scaled form was chosen FOR: C_lr tracks the trim
    CL exactly.  Double the loading, double C_lr — the rejected lift-slope proxy
    would have given a CL-independent constant."""
    bulk, aero = rect
    f1 = _rigid_loading(bulk, aero, np.radians(3.0))
    f2 = _rigid_loading(bulk, aero, np.radians(6.0))
    c1 = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, f1, bulk))["YAW"]["CMX"]
    c2 = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, f2, bulk))["YAW"]["CMX"]
    assert c2 == pytest.approx(2.0 * c1, rel=1e-10)
    assert abs(c1) > 1e-4, "C_lr collapsed to zero — the term is not being applied"


def test_c_lr_flips_with_the_loading_sign(rect):
    """A negative-lift trim reverses the asymmetry, hence C_lr."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(4.0))
    up = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, f_ref, bulk))
    dn = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, -f_ref, bulk))
    assert dn["YAW"]["CMX"] == pytest.approx(-up["YAW"]["CMX"], rel=1e-12)


def test_planar_wing_yaw_moment_stays_zero(rect):
    """KNOWN LIMITATION, asserted so it cannot regress silently: box forces are
    strictly panel-normal (no leading-edge suction), so a planar wing has
    F_x = F_y = 0 and the scaled load produces NO yaw moment.  The wing's C_nr is
    an induced-drag asymmetry and needs the Step 67b streamwise-force term; until
    then C_nr is carried by the fin sidewash column alone."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(5.0))
    d = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, f_ref, bulk))
    assert d["YAW"]["CMZ"] == pytest.approx(0.0, abs=1e-12)
    assert abs(d["YAW"]["CMX"]) > 1e-4     # ... while C_lr is live


def test_other_columns_are_untouched(rect):
    """The force column rides on YAW only: ANGLEA/ROLL/SIDES are bit-identical
    with and without it."""
    bulk, aero = rect
    f_ref = _rigid_loading(bulk, aero, np.radians(5.0))
    base = _derivs(bulk, aero)
    with_yaw = _derivs(bulk, aero, f_box_yaw=build_fjx_yaw(aero.boxes, f_ref, bulk))
    for lbl in ("ANGLEA", "ROLL", "SIDES"):
        for comp, val in base[lbl].items():
            assert with_yaw[lbl][comp] == val, f"{lbl} {comp} moved"


def test_none_reference_reproduces_the_pre_step67_derivatives(rect):
    """f_box_yaw=None is the old code path, exactly — this is what keeps every
    deck without a yaw-rate case bit-identical."""
    bulk, aero = rect
    base = _derivs(bulk, aero)
    for lbl in LABELS:
        for comp, val in base[lbl].items():
            # The pre-Step-67 planar-wing result: YAW loads nothing at all.
            if lbl == "YAW":
                assert val == pytest.approx(0.0, abs=1e-9), comp


# ---------------------------------------------------------------------------
# 3. End-to-end trim: gating, the fixed point, and load participation
# ---------------------------------------------------------------------------

def _ha144a():
    """Case control + bulk for the full-span HA144A trim deck."""
    return parse_bdf(str(SAMPLE / "ha144a_fullspan_sbeam.bdf"))


def _trim(bulk, subcase):
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        return run_sol144_trim(bulk, subcase, aero)


def _add_prescribed_yaw(bulk, trim_sid, value):
    """Add YAW as a PRESCRIBED trim label (leaves n_free/n_suport untouched)."""
    new_id = max(bulk.aestats) + 1 if bulk.aestats else 900
    bulk.aestats[new_id] = Aestat(id=new_id, label="YAW")
    bulk.trims[trim_sid].vars["YAW"] = value
    return bulk


def test_deck_without_yaw_label_is_untouched():
    """No YAW label ⇒ the stage returns immediately, iters == 0."""
    cc, bulk = _ha144a()
    res = _trim(bulk, cc.subcases[0])
    assert res.yaw_rate_iters == 0


def test_zero_yaw_rate_is_bit_identical():
    """YAW present but prescribed 0.0: the increment is identically zero, so the
    trim must reproduce the no-YAW result BIT-for-bit (not just closely) —
    the guard that yaw-rate support costs existing decks nothing."""
    cc, bulk = _ha144a()
    base = _trim(bulk, cc.subcases[0])

    cc2, bulk2 = _ha144a()
    _add_prescribed_yaw(bulk2, trim_sid=1, value=0.0)
    zero = _trim(bulk2, cc2.subcases[0])

    assert zero.yaw_rate_iters == 0
    assert np.array_equal(zero.displacements, base.displacements)
    assert zero.total_cl == base.total_cl
    assert zero.total_cmx == base.total_cmx
    for lbl, comp in base.trim_vars.items():
        assert zero.trim_vars[lbl] == comp


def test_nonzero_yaw_rate_converges_and_loads_the_wing():
    """A prescribed yaw rate activates the fixed point, which converges in a
    handful of iterations and puts a genuine rolling moment on the airplane."""
    cc, bulk = _ha144a()
    base = _trim(bulk, cc.subcases[0])

    cc2, bulk2 = _ha144a()
    _add_prescribed_yaw(bulk2, trim_sid=1, value=0.05)
    yawed = _trim(bulk2, cc2.subcases[0])

    assert 1 <= yawed.yaw_rate_iters <= 4
    # The asymmetry is a roll moment; the symmetric longitudinal trim barely moves.
    assert abs(yawed.total_cmx) > 1e-4
    assert abs(base.total_cmx) < 1e-9
    assert yawed.total_cl == pytest.approx(base.total_cl, rel=1e-6)


def test_trim_loading_carries_the_increment():
    """The increment is part of the trimmed load, not a derivative-only bolt-on:
    it shows up in the exported per-box forces as a spanwise-antisymmetric
    perturbation of the baseline."""
    cc, bulk = _ha144a()
    base = _trim(bulk, cc.subcases[0])

    cc2, bulk2 = _ha144a()
    _add_prescribed_yaw(bulk2, trim_sid=1, value=0.05)
    yawed = _trim(bulk2, cc2.subcases[0])

    dfz = yawed.box_forces[:, 2] - base.box_forces[:, 2]
    assert np.max(np.abs(dfz)) > 0.0
    # Antisymmetric perturbation ⇒ small net lift change, large roll change.
    assert abs(dfz.sum()) < 0.05 * np.abs(dfz).sum()


def test_transient_operators_gate_on_the_yaw_label():
    """The Phase G0 a-set operators take the same term through the same helper.
    On a deck with no YAW label, passing a reference loading must change
    NOTHING — the transient path inherits the trim path's gating."""
    from sbeam.solver.modal_basis import (
        assemble_aset_operators, yaw_reference_loading)

    cc, bulk = _ha144a()
    subcase = cc.subcases[0]
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        trim = run_sol144_trim(bulk, subcase, aero)
        base = assemble_aset_operators(bulk, subcase, aero)
        f_box_ref = yaw_reference_loading(aero, trim)
        with_ref = assemble_aset_operators(bulk, subcase, aero, f_box_ref=f_box_ref)

    assert f_box_ref is not None
    assert np.array_equal(with_ref.Q_ax_a, base.Q_ax_a)


def test_yaw_reference_loading_is_the_steady_load():
    """The reference loading is the STEADY (normalwash-driven) box-force field —
    scaling the already-incremented load would double-count at second order."""
    from sbeam.solver.modal_basis import yaw_reference_loading

    cc, bulk = _ha144a()
    subcase = cc.subcases[0]
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        trim = run_sol144_trim(bulk, subcase, aero)
    assert np.allclose(yaw_reference_loading(aero, trim),
                       aero.skj @ trim.box_gamma, rtol=0, atol=0)


def test_yaw_rate_sign_reverses_the_rolling_moment():
    """±r give equal and opposite rolling moments (to the linearity of the
    fixed point)."""
    out = {}
    for value in (0.05, -0.05):
        cc, bulk = _ha144a()
        _add_prescribed_yaw(bulk, trim_sid=1, value=value)
        out[value] = _trim(bulk, cc.subcases[0]).total_cmx
    assert out[0.05] == pytest.approx(-out[-0.05], rel=1e-3)
