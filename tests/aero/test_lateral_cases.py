"""V-LAT2 — lateral trim cases on `sample/val_lateral_aileron_rudder.bdf` (#10, G10–G12).

Design note ``docs/30_future/designs/lateral_cases_aileron_rudder.md`` §2.3–2.4, §5.
The deck is the AR 8 rectangular wing + a vertical fin on a stiff spine, with an
aileron PAIR (one AESURF, CID1 starboard / CID2 port, both +y outboard) and a rudder
(hinge +y DOWN so positive = TE-port = lift-increasing on the +y fin normal), SUPORT 46,
and two determined trims: steady roll (ROLL prescribed) and steady sideslip (SIDES
prescribed), AIL and RUD free in both.

Every reference number is recomputed from the parsed deck (the VAL2 discipline):
the flap chord ratio from the AELIST geometry, the strip integral from the aileron
span, the moment arm from the box forces, the trim check from the solver's own
restrained derivative table (exact linear algebra, so rtol 1e-8).
"""

import csv
import math
import subprocess
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.integration import aesurf_hinges, build_djx
from sbeam.assembly.coord_transform import get_transform
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Aesurf, require_aeros
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.solver.sol144 import AeroCache, compute_hinge_moments, compute_rigid_derivs, run_sol144_trim

REPO = Path(__file__).parent.parent.parent
DECK = REPO / "sample/val_lateral_aileron_rudder.bdf"
LABELS = ["AIL", "RUD", "ROLL", "SIDES", "YAW", "ANGLEA"]


def _flap_effectiveness(E: float) -> float:
    """Thin-airfoil plain-flap effectiveness τ = ∂α_eff/∂δ for flap chord ratio E."""
    theta = math.acos(2.0 * E - 1.0)
    return 1.0 - (theta - math.sin(theta)) / math.pi


@pytest.fixture(scope="module")
def model():
    cc, bulk = parse_bdf(str(DECK))
    assert cc.sol == 144 and [sc.trim_sid for sc in cc.subcases] == [1, 2]
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
    ref = np.asarray(get_transform(require_aeros(bulk).rcsid, bulk.cord2rs)[0], dtype=float)
    djx = build_djx(aero.boxes, LABELS, bulk, id_to_k=aero.require_box_id_to_k())
    rigid = compute_rigid_derivs(aero, djx, LABELS, bulk, float(ref[0]), ref)
    return cc, bulk, aero, ref, djx, rigid


@pytest.fixture(scope="module")
def trims(model):
    cc, bulk, aero, *_ = model
    cache = AeroCache(bulk, build_grid_index(bulk), seed=aero)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return {sc.subcase_id: run_sol144_trim(bulk, sc, aero, aero_cache=cache) for sc in cc.subcases}


def _fin_boxes(aero):
    return [b.k for b in aero.boxes if abs(b.normal[1]) > 0.9]


# ---------------------------------------------------------------------------
# G10 — rudder
# ---------------------------------------------------------------------------

def test_rudder_signs_and_moment_arm(model):
    """D2: positive RUD = TE-port = +Fy (starboard sideforce at the tail) = +CMZ in
    basic; and CMZ/CY is exactly the sideforce centroid arm over b."""
    cc, bulk, aero, ref, djx, rigid = model
    r = rigid["RUD"]
    assert r["CY"] > 0.1 and r["CMZ"] > 0.05
    assert abs(r["CZ"]) < 1e-12 and abs(r["CMY"]) < 1e-12
    f = (aero.skj @ (aero.ajj_inv_corr @ djx[:, LABELS.index("RUD")])).reshape(-1, 3)
    x_fp = np.array([b.force_point[0] for b in aero.boxes])
    arm = float(((x_fp - ref[0]) * f[:, 1]).sum() / f[:, 1].sum())
    assert r["CMZ"] / r["CY"] == pytest.approx(arm / require_aeros(bulk).bref, rel=1e-10)
    # The rudder hinge +y points DOWN (−z): that is what makes positive = TE-port.
    half, = aesurf_hinges(bulk.aesurfs[602], bulk, aero.require_box_id_to_k())
    np.testing.assert_allclose(half.h_hat, [0, 0, -1], atol=1e-15)
    assert len(half.ks) == 12


def test_rudder_effectiveness_is_the_thin_airfoil_flap_factor(model):
    """CY_δr / CY_β,fin ≈ τ(E): the rudder's sideforce per radian relative to the whole
    fin's per radian of sideslip.  τ is the 2-D thin-airfoil value; the finite-AR fin
    (and its interference with the wing) sits within ±15 % of it on this mesh (1.05 τ)."""
    cc, bulk, aero, ref, djx, rigid = model
    fin = _fin_boxes(aero)
    rudder = aesurf_hinges(bulk.aesurfs[602], bulk, aero.require_box_id_to_k())[0].ks
    n_chord = 8
    assert len(fin) == 6 * n_chord and len(rudder) == 6 * 2
    tau = _flap_effectiveness(2 / n_chord)
    assert tau == pytest.approx(0.609, abs=1e-3)
    fin_only = djx.copy()
    col = LABELS.index("SIDES")
    mask = np.zeros(len(aero.boxes), dtype=bool)
    mask[fin] = True
    fin_only[~mask, col] = 0.0
    cy_beta_fin = compute_rigid_derivs(aero, fin_only, LABELS, bulk, float(ref[0]), ref)["SIDES"]["CY"]
    ratio = rigid["RUD"]["CY"] / cy_beta_fin
    assert 0.85 * tau < ratio < 1.15 * tau, (ratio, tau)


# ---------------------------------------------------------------------------
# G11 — aileron magnitude and hinge moment
# ---------------------------------------------------------------------------

def test_aileron_rolling_power_against_strip_theory(model):
    """|C_lδa| vs 2·CLα·τ·∫c·y dy /(S·b) with the VLM's own CLα: the strip estimate
    is an upper bound (no tip relief, no carry-over loss), so the ratio sits in the
    lifting-line band [0.6, 1.0] — the same discipline as the C_lp gate."""
    cc, bulk, aero, ref, djx, rigid = model
    a = require_aeros(bulk)
    halves = aesurf_hinges(bulk.aesurfs[601], bulk, aero.require_box_id_to_k())
    assert [len(h.ks) for h in halves] == [16, 16]
    stbd = halves[0].ks
    y = np.array([aero.boxes[k].colloc[1] for k in stbd])
    # aileron spans strips whose centres run from y1 to y2 (strip width b/2/20)
    width = (a.bref / 2) / 20
    y1, y2 = y.min() - width / 2, y.max() + width / 2
    assert y1 == pytest.approx(2.4) and y2 == pytest.approx(4.0)
    tau = _flap_effectiveness(2 / 8)
    cla = rigid["ANGLEA"]["CZ"]
    strip = 2.0 * cla * tau * (y2**2 - y1**2) / 2.0 / (a.sref * a.bref)
    ratio = rigid["AIL"]["CMX"] / strip
    assert 0.6 < ratio < 1.0, (rigid["AIL"]["CMX"], strip, ratio)
    assert rigid["AIL"]["CMX"] > 0           # D1: positive AIL rolls toward port (+CMX basic)


def test_pair_hinge_moment_is_twice_one_half(model):
    cc, bulk, aero, ref, djx, rigid = model
    f_unit = aero.skj @ (aero.ajj_inv_corr @ djx[:, LABELS.index("AIL")])
    hm_pair = compute_hinge_moments(aero, djx, LABELS, bulk, f_unit)["AIL"]["total"]
    saved = bulk.aesurfs[601]
    bulk.aesurfs[601] = Aesurf(id=601, label="AIL", cid1=saved.cid1, alid1=saved.alid1)
    try:
        hm_stbd = compute_hinge_moments(aero, djx, LABELS, bulk, f_unit)["AIL"]["total"]
    finally:
        bulk.aesurfs[601] = saved
    assert hm_pair == pytest.approx(2.0 * hm_stbd, rel=1e-12)
    assert hm_pair < 0.0                     # TE-down loading opposes the positive rotation


# ---------------------------------------------------------------------------
# G12 — the two trims, end to end
# ---------------------------------------------------------------------------

def _solve_2x2(restrained, prescribed_label, value):
    """[CMX_δa CMX_δr; CMZ_δa CMZ_δr]·[δa; δr] = −[CMX_p; CMZ_p]·value  (URDD4 = URDD6 = 0)."""
    A = np.array([[restrained["AIL"]["CMX"], restrained["RUD"]["CMX"]],
                  [restrained["AIL"]["CMZ"], restrained["RUD"]["CMZ"]]])
    rhs = -np.array([restrained[prescribed_label]["CMX"], restrained[prescribed_label]["CMZ"]]) * value
    return np.linalg.solve(A, rhs)


def test_steady_roll_trim_is_the_2x2_solve_and_needs_starboard_te_up(trims):
    r = trims[1]
    assert r.trim_mode == "determined" and set(r.trim_vars) == {"AIL", "RUD", "ROLL", "SIDES", "YAW", "URDD4", "URDD6"}
    da, dr = _solve_2x2(r.restrained_derivs, "ROLL", r.trim_vars["ROLL"])
    assert r.trim_vars["AIL"] == pytest.approx(da, rel=1e-8)
    assert r.trim_vars["RUD"] == pytest.approx(dr, rel=1e-8)
    # Right roll (positive ROLL = starboard-down) needs starboard TE-UP: negative AIL (D1).
    assert r.trim_vars["ROLL"] > 0 and r.trim_vars["AIL"] < 0
    # Closure in the SUPORT DOFs (Mx, Mz): the sway force Fy is reacted by the SPC,
    # not trimmed, so only the two free moments must vanish.
    scale = np.abs(r.net_loads).max() * 8.0
    assert abs(r.maneuver_closure[3]) < 1e-9 * scale and abs(r.maneuver_closure[5]) < 1e-9 * scale


def test_steady_sideslip_trim_is_the_2x2_solve_and_rudder_opposes_weathercock(trims):
    r = trims[2]
    da, dr = _solve_2x2(r.restrained_derivs, "SIDES", r.trim_vars["SIDES"])
    assert r.trim_vars["AIL"] == pytest.approx(da, rel=1e-8)
    assert r.trim_vars["RUD"] == pytest.approx(dr, rel=1e-8)
    # Positive SIDES (wind from port) yaws the nose toward port through the fin
    # (CMZ_β > 0); holding YAW = 0 needs the rudder to push the tail the other way,
    # i.e. negative RUD (TE-starboard).  Sign relation, not a magnitude.
    assert r.restrained_derivs["SIDES"]["CMZ"] > 0 and r.trim_vars["RUD"] < 0
    assert np.sign(r.trim_vars["RUD"]) == -np.sign(r.restrained_derivs["SIDES"]["CMZ"] / r.restrained_derivs["RUD"]["CMZ"])
    # Closure in the SUPORT DOFs (Mx, Mz): the sway force Fy is reacted by the SPC,
    # not trimmed, so only the two free moments must vanish.
    scale = np.abs(r.net_loads).max() * 8.0
    assert abs(r.maneuver_closure[3]) < 1e-9 * scale and abs(r.maneuver_closure[5]) < 1e-9 * scale


def test_lateral_monitors_carry_fy_mx_mz(trims):
    for r in trims.values():
        m = r.monitor_loads["MLAT"]
        assert abs(m.totals[1]) > 0 or abs(m.totals[3]) > 0        # Fy or Mx
        assert abs(m.totals[2]) < 1e-9 and abs(m.totals[4]) < 1e-9  # no lift, no pitch
        assert r.section_loads["SECRW"].stations[0].totals[2] != 0  # wing-root Fz from the roll


def test_cli_writes_f06_and_both_csvs(tmp_path):
    deck = tmp_path / DECK.name
    deck.write_text(DECK.read_text())
    out = subprocess.run([sys.executable, "-m", "sbeam.main", str(deck)], capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "val_lateral_aileron_rudder.f06").exists()
    with open(tmp_path / "val_lateral_aileron_rudder.monitor_loads.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["case"] for r in rows} == {"1", "2"} and {r["name"] for r in rows} == {"MLAT", "MLATB"}
    assert (tmp_path / "val_lateral_aileron_rudder.section_loads.csv").exists()
