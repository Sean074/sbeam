"""Step 67b — the yaw-rate wing DRAG asymmetry (the wing's C_nr).

Step 67a scales the trim loading by `s_j = −(4/b_ref)(y_j − y_ref)` per unit YAW.
On a planar wing that produces a rolling moment and *exactly zero* yaw moment,
because every VLM box force is strictly panel-normal (no leading-edge suction) so
F_x = F_y = 0.  The wing's yaw damping is an induced-**drag** asymmetry, so 67b
gives each box a streamwise force — the per-box Trefftz induced drag — for the
same scaling to act on:

    C_nr = −(4/(S_ref·b_ref²))·Σ_j (y_j − y_ref)²·F_x,drag,j     →  −CDi/4 (elliptic)

and since CDi ∝ CL², the wing C_nr ∝ CL² — the physically right trend and the
sharp test here (`test_c_nr_scales_with_cl_squared`).

**Confinement.** The drag field is used ONLY inside the yaw column.  It is not
added to the baseline box forces, CX, CD_wind or the load export: sbeam
deliberately reports `CD_wind` as the Trefftz CDi rather than the near-field
projection, and only the *asymmetric* part of the drag makes a yaw moment (the
symmetric part is already in CDi and contributes no Mz).  `test_baseline_totals_*`
are the guards.

Sign convention: as in `test_lateral_derivs.py`, moments are the full 3-component
resultant in sbeam's z-up / y-starboard aero frame.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bulk_file, parse_bdf
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import build_djx, build_fjx_yaw, build_fx_induced_drag
from sbeam.aero.vlm import (
    box_circulation, box_widths, solve_rigid_cl, trefftz_box_drag, trefftz_cdi,
)
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aestat, require_aeros
from sbeam.solver.sol144 import compute_rigid_derivs, run_sol144_trim

SAMPLE = Path(__file__).parent.parent.parent / "sample"
LABELS = ["ANGLEA", "ROLL", "YAW", "SIDES"]


@pytest.fixture(scope="module")
def rect():
    bulk = parse_bulk_file(str(SAMPLE / "val_vlm_rect_ar8.bdf"))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero


def _rigid_cp(bulk, aero, alpha):
    """Trim ΔCp field of the rigid wing at incidence alpha (the SOL 144 `gamma`)."""
    djx = build_djx(aero.boxes, ["ANGLEA"], bulk)
    return aero.ajj_inv_corr @ (alpha * djx[:, 0])


def _yaw_derivs(bulk, aero, cp):
    """Rigid derivatives with the full 67a+67b yaw column at this loading."""
    f_ref = aero.skj @ cp + build_fx_induced_drag(aero.boxes, cp)
    col = build_fjx_yaw(aero.boxes, f_ref, bulk)
    djx = build_djx(aero.boxes, LABELS, bulk)
    return compute_rigid_derivs(
        aero, djx, LABELS, bulk, 0.0, np.zeros(3), f_box_yaw=col)


# ---------------------------------------------------------------------------
# 1. The refactor: CDi unchanged, and the per-box breakdown sums to it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("deck", [
    "val_vlm_rect_ar8", "val_vlm_dihedral", "val_vlm_anhedral",
])
def test_box_drag_sums_to_cdi(deck):
    """Σ F_x,drag ≡ CDi·S_ref — the per-box field IS the Trefftz integrand, so
    the total and its distribution cannot drift apart."""
    bulk = parse_bulk_file(str(SAMPLE / f"{deck}.bdf"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    aeros = require_aeros(bulk)
    cp = _rigid_cp(bulk, aero, np.radians(5.0))
    gamma = box_circulation(aero.boxes, cp)

    cdi = trefftz_cdi(aero.boxes, gamma, aeros.sref,
                      aeros.bref ** 2 / aeros.sref)["CDi"]
    assert float(trefftz_box_drag(aero.boxes, gamma).sum()) == pytest.approx(
        cdi * aeros.sref, rel=1e-12)
    assert cdi > 0.0, "no induced drag to distribute — test is vacuous"


def test_circulation_identity_matches_the_rigid_solver(rect):
    """box_circulation reproduces solve_rigid_cl's Γ from its ΔCp — the guard on
    the Γ = cp·area/(2·width) factor, which 67b relies on to avoid a second solve."""
    bulk, aero = rect
    alpha = np.radians(4.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = solve_rigid_cl(aero.boxes, alpha, aeros=require_aeros(bulk),
                             wg=aero.wg, cp_operator=aero.ajj_inv_corr)
    cp = _rigid_cp(bulk, aero, alpha)
    assert np.allclose(cp, res["cp"], rtol=1e-12)
    # Γ = cp·area/(2·width): reproduce the solver's own reconstruction.
    chord_box = np.array([b.area for b in aero.boxes]) / box_widths(aero.boxes)
    assert np.allclose(box_circulation(aero.boxes, cp), cp * chord_box / 2.0,
                       rtol=1e-14, atol=0)


def test_drag_field_populates_only_the_streamwise_rows(rect):
    """build_fx_induced_drag is a pure streamwise field — it must not perturb the
    normal force in the reference loading it is added to."""
    bulk, aero = rect
    field = build_fx_induced_drag(aero.boxes, _rigid_cp(bulk, aero, np.radians(5.0)))
    assert np.array_equal(field[1::3], np.zeros(len(aero.boxes)))
    assert np.array_equal(field[2::3], np.zeros(len(aero.boxes)))
    assert np.abs(field[0::3]).sum() > 0.0


# ---------------------------------------------------------------------------
# 2. C_nr — the closed form, the CL² trend, the damping sign
# ---------------------------------------------------------------------------

def _c_nr_closed_form(bulk, aero, cp):
    """C_nr = +(4/(S·b²))·Σ y²F_x,drag.

    Note the sign relative to C_lr's −(4/(S·b²))Σ y²F_z: the yaw moment is
    `Mz = x·F_y − y·F_x`, so the arm carries a minus the roll moment
    (`Mx = y·F_z − z·F_y`) does not, and the two derivatives come out with
    opposite sign structure for the same scaling.
    """
    aeros = require_aeros(bulk)
    y = np.array([b.force_point[1] for b in aero.boxes])
    fx = build_fx_induced_drag(aero.boxes, cp)[0::3]
    return (4.0 / (aeros.sref * aeros.bref ** 2)) * float((y ** 2 * fx).sum())


def test_c_nr_matches_the_closed_form(rect):
    """CMZ of the YAW column equals −(4/(S·b²))·Σ y²F_x,drag."""
    bulk, aero = rect
    cp = _rigid_cp(bulk, aero, np.radians(5.0))
    c_nr = _yaw_derivs(bulk, aero, cp)["YAW"]["CMZ"]
    assert c_nr == pytest.approx(_c_nr_closed_form(bulk, aero, cp), rel=1e-10)


def test_c_nr_is_now_nonzero_on_a_planar_wing(rect):
    """The whole point of 67b: before it, a planar wing's yaw column produced no
    yaw moment at all."""
    bulk, aero = rect
    cp = _rigid_cp(bulk, aero, np.radians(5.0))
    d = _yaw_derivs(bulk, aero, cp)
    assert abs(d["YAW"]["CMZ"]) > 1e-6
    # ... and the 67a rolling moment is still there and still much larger
    # (C_lr ~ CL/4 vs C_nr ~ CDi/4, and CDi << CL).
    assert abs(d["YAW"]["CMX"]) > abs(d["YAW"]["CMZ"])


def test_c_nr_magnitude_is_of_order_cdi_over_four(rect):
    """Strip theory gives |C_nr| = CDi/4 for an *elliptic* drag distribution
    (where w_T is constant, so d(y) ∝ Γ(y) and Σy²d = (b²/16)·Di).

    A rectangular AR=8 wing is not elliptic and, more to the point, its Trefftz
    downwash rises sharply toward the tips — pushing the drag outboard, where the
    y² arm is largest.  The measured ratio is ~1.45·CDi/4, which is the physics,
    not an error; the band below records it rather than pretending to 15 %."""
    bulk, aero = rect
    aeros = require_aeros(bulk)
    cp = _rigid_cp(bulk, aero, np.radians(5.0))
    cdi = trefftz_cdi(aero.boxes, box_circulation(aero.boxes, cp), aeros.sref,
                      aeros.bref ** 2 / aeros.sref)["CDi"]
    c_nr = _yaw_derivs(bulk, aero, cp)["YAW"]["CMZ"]
    assert 1.0 <= abs(c_nr) / (cdi / 4.0) <= 1.8


def test_c_nr_scales_with_cl_squared(rect):
    """CDi ∝ CL², so the wing C_nr must too — the trend that distinguishes a
    genuine drag-asymmetry term from a lift-scaled fudge.  (C_lr, by contrast,
    scales linearly — asserted in test_yaw_rate_wing.py.)"""
    bulk, aero = rect
    cp1 = _rigid_cp(bulk, aero, np.radians(3.0))
    cp2 = _rigid_cp(bulk, aero, np.radians(6.0))
    c1 = _yaw_derivs(bulk, aero, cp1)["YAW"]["CMZ"]
    c2 = _yaw_derivs(bulk, aero, cp2)["YAW"]["CMZ"]
    assert c2 == pytest.approx(4.0 * c1, rel=1e-8)


def test_wing_drag_c_nr_has_the_same_sign_as_the_fin():
    """The wing drag asymmetry must *reinforce* the fin's yaw damping, not fight
    it — the advancing wing carries more drag, which is a damping moment.

    Asserted against the fin's own C_nr on the same deck rather than against an
    absolute sign: sbeam's z-up / y-starboard frame is not the textbook z-down
    body axis (the fin's C_nr comes out POSITIVE here), so a bare sign assertion
    would be testing the frame convention instead of the physics."""
    bulk = parse_bulk_file(str(SAMPLE / "cessna210_flagship_bulk.bdf"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=build_grid_index(bulk))
    n_vert = sum(1 for b in aero.boxes if abs(b.normal[1]) > 0.9)
    assert n_vert > 0, "deck has no fin — the comparison would be vacuous"

    cp = _rigid_cp(bulk, aero, np.radians(4.0))
    djx = build_djx(aero.boxes, LABELS, bulk)
    fin_only = compute_rigid_derivs(
        aero, djx, LABELS, bulk, 0.0, np.zeros(3))["YAW"]["CMZ"]
    total = _yaw_derivs(bulk, aero, cp)["YAW"]["CMZ"]
    wing_drag = total - fin_only

    assert abs(fin_only) > 1e-3, "fin sidewash C_nr vanished"
    assert abs(wing_drag) > 1e-6, "wing drag C_nr vanished"
    assert np.sign(wing_drag) == np.sign(fin_only)
    assert abs(total) > abs(fin_only)          # damping strictly increased


def test_c_nr_survives_a_negative_lift_trim(rect):
    """CDi is quadratic in loading, so a negative-lift trim gives the SAME
    (damping) C_nr sign — unlike C_lr, which flips."""
    bulk, aero = rect
    cp = _rigid_cp(bulk, aero, np.radians(4.0))
    up = _yaw_derivs(bulk, aero, cp)["YAW"]
    dn = _yaw_derivs(bulk, aero, -cp)["YAW"]
    assert dn["CMZ"] == pytest.approx(up["CMZ"], rel=1e-8)
    assert dn["CMX"] == pytest.approx(-up["CMX"], rel=1e-8)


# ---------------------------------------------------------------------------
# 3. Confinement — the baseline load path must not see the drag field
# ---------------------------------------------------------------------------

def _ha144a():
    return parse_bdf(str(SAMPLE / "ha144a_fullspan_sbeam.bdf"))


def _trim(bulk, subcase):
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=grid_index)
        return run_sol144_trim(bulk, subcase, aero)


def _add_prescribed_yaw(bulk, trim_sid, value):
    new_id = max(bulk.aestats) + 1 if bulk.aestats else 900
    bulk.aestats[new_id] = Aestat(id=new_id, label="YAW")
    bulk.trims[trim_sid].vars["YAW"] = value
    return bulk


def test_strip_body_boxes_carry_no_induced_drag(flagship_strip_uncorrected):
    """Decoupled strip body panels shed no trailing vorticity, so they have no
    Trefftz wake and no induced drag — and therefore contribute nothing to the
    wing C_nr, however much load they carry."""
    _cc, bulk, aero, _gi, _w = flagship_strip_uncorrected
    cp = _rigid_cp(bulk, aero, np.radians(4.0))
    fx = build_fx_induced_drag(aero.boxes, cp)[0::3]

    strip_idx = [j for j, b in enumerate(aero.boxes) if b.is_strip]
    assert strip_idx, "fixture has no strip boxes — test would be vacuous"
    assert np.array_equal(fx[strip_idx], np.zeros(len(strip_idx)))
    assert np.abs(fx).sum() > 0.0        # the lifting surfaces still do


def test_symmetric_drag_never_enters_the_load_path():
    """The confinement rule, stated precisely.

    The SYMMETRIC induced drag stays out of the baseline entirely — sbeam
    reports CD_wind as the Trefftz CDi, not the near-field projection, and the
    baseline box forces are strictly panel-normal (CX ≈ 0).  What the yaw-rate
    case DOES put into the load path is the drag's *asymmetry*, which is a real
    fore-aft load on the wing and is exactly the resultant reported as the wing
    C_nr; excluding it would make the printed CMZ disagree with the exported
    loads.  So: no drag at all without a yaw rate, an antisymmetric (≈ zero-net)
    streamwise load with one."""
    cc, bulk = _ha144a()
    base = _trim(bulk, cc.subcases[0])

    cc2, bulk2 = _ha144a()
    _add_prescribed_yaw(bulk2, trim_sid=1, value=0.05)
    yawed = _trim(bulk2, cc2.subcases[0])

    # No yaw rate ⇒ the baseline carries no streamwise force whatsoever.
    assert np.array_equal(base.box_forces[:, 0], np.zeros(len(base.box_forces)))
    # With a yaw rate: a real streamwise load, but antisymmetric — the net
    # (and hence the reported body-axis CX / drag bookkeeping) is unchanged.
    fx = yawed.box_forces[:, 0]
    assert np.abs(fx).sum() > 0.0
    assert abs(fx.sum()) < 1e-3 * np.abs(fx).sum()
    assert yawed.total_cx == pytest.approx(base.total_cx, abs=1e-9)


def test_trim_yaw_moment_is_live_end_to_end():
    """A prescribed yaw rate produces a yawing moment on the trimmed airplane —
    zero before 67b, since HA144A's fin is the only yaw contributor and it sees
    no sidewash asymmetry from the wing."""
    cc, bulk = _ha144a()
    base = _trim(bulk, cc.subcases[0])

    cc2, bulk2 = _ha144a()
    _add_prescribed_yaw(bulk2, trim_sid=1, value=0.05)
    yawed = _trim(bulk2, cc2.subcases[0])

    assert abs(base.total_cmz) < 1e-9
    assert abs(yawed.total_cmz) > 1e-9
