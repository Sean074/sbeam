"""MSC multiple mass combination (#102): BEGIN MASSID sections, MASSSET bulk and case control.

MSC Nastran 2024.1 QRG: ``BEGIN MASSID = massid [LABEL = masslabel]`` opens an incremental
mass case Bulk Data Section (PDF p.286-287); the bulk ``MASSSET ID S0 S1 ID1 S2 ID2 ...``
defines ``M_ID = S0 · Σ Si·M_IDi`` with ``IDi = 0`` the base (p.2018); the case-control
``MASSSET = n`` selects it per subcase, and a subcase without one runs at the base mass
(p.482).

Gates on ``sample/ha144a_mass_combination_sweep.bdf``, the MSC twin of the MASSCASE sweep:

  * **twin** — MASSSET 10/20/30 reproduce MASSCASE 10/20/30 of
    ``ha144a_massset_sweep.bdf``: the same CONM2 set in the same order, so GPWG, M_gg and
    the trim are identical;
  * **hand check** — MASSSET 40 (S0 = 2.0, 0.5 · base + 0.25 · HALFFUEL) is the base plus
    half the half-fuel load, 16000 + 1000 lb, with the CG worked from the grid positions.
"""
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.mass_matrix import assemble_global_mass
from sbeam.gpwg import compute_gpwg
from sbeam.model.mass_overlay import resolve_mass_case
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import parse_case_control
from sbeam.solver.sol144 import AeroCache, run_sol144_trim

SAMPLE = Path(__file__).parent.parent.parent / "sample"
G = 32.174


def _run(deck):
    cc, bulk = parse_bdf(str(SAMPLE / deck))
    gi = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        aero = build_aero_model(bulk, grid_index=gi)
        cache = AeroCache(bulk, gi, seed=aero)
        results = {sc.massset_sid: run_sol144_trim(bulk, sc, aero, aero_cache=cache)
                   for sc in cc.subcases}
    return bulk, results


@pytest.fixture(scope="module")
def decks():
    return _run("ha144a_massset_sweep.bdf"), _run("ha144a_mass_combination_sweep.bdf")


@pytest.mark.parametrize("sid", [10, 20, 30])
def test_twin_reproduces_the_masscase_sweep(decks, sid):
    (b_case, r_case), (b_msc, r_msc) = decks
    c_case, c_msc = resolve_mass_case(b_case, sid), resolve_mass_case(b_msc, sid)
    assert list(c_case.conm2s) == list(c_msc.conm2s)
    assert c_case.conm2s == c_msc.conm2s and c_case.scale == c_msc.scale
    g1, g2 = compute_gpwg(b_case, sid), compute_gpwg(b_msc, sid)
    assert (g1.total_mass, g1.cg_x, g1.cg_y, g1.cg_z) == (
        g2.total_mass, g2.cg_x, g2.cg_y, g2.cg_z)
    assert np.array_equal(assemble_global_mass(b_case, sid).toarray(),
                          assemble_global_mass(b_msc, sid).toarray())
    assert r_case[sid].trim_vars == r_msc[sid].trim_vars
    assert np.array_equal(r_case[sid].displacements, r_msc[sid].displacements)


def test_s0_scales_the_whole_combination_by_hand(decks):
    """MASSSET 40, 2.0 · (0.5 · base + 0.25 · HALFFUEL) = base + 0.5 · HALFFUEL."""
    (_b, _r), (bulk, results) = decks
    base = compute_gpwg(bulk, 10)                   # MASSSET 10 = 1.0 · base
    fuel_eids = bulk.mass_increments[102]
    m_fuel = 0.5 * sum(bulk.conm2s[e].m for e in fuel_eids)
    x_fuel = sum(bulk.conm2s[e].m * bulk.grids[bulk.conm2s[e].gid].x
                 for e in fuel_eids) / sum(bulk.conm2s[e].m for e in fuel_eids)
    g = compute_gpwg(bulk, 40)
    assert g.total_mass * G == pytest.approx(17000.0, rel=1e-4)
    assert g.total_mass == pytest.approx(base.total_mass + m_fuel, rel=1e-12)
    assert g.cg_x == pytest.approx((base.total_mass * base.cg_x + m_fuel * x_fuel)
                                   / (base.total_mass + m_fuel), rel=1e-12)
    assert results[40].trim_vars["ANGLEA"] > results[10].trim_vars["ANGLEA"]


def test_increment_masses_stay_out_of_the_base(decks):
    """A subcase with no MASSSET runs at the base mass (QRG p.482 remark 1)."""
    (_b, _r), (bulk, _results) = decks
    base = resolve_mass_case(bulk, None)
    assert not set(base.conm2s) & {e for eids in bulk.mass_increments.values() for e in eids}
    assert compute_gpwg(bulk).total_mass == compute_gpwg(bulk, 10).total_mass


def test_section_labels_and_ids_are_read(decks):
    (_b, _r), (bulk, _results) = decks
    assert bulk.mass_increment_labels == {101: "BAGGAGE", 102: "HALFFUEL",
                                          103: "FULLFUEL", 104: "HEAVYBAG"}
    assert bulk.mass_combinations[40].s0 == 2.0
    assert bulk.mass_combinations[40].terms == [(0.5, 0), (0.25, 102)]


# --------------------------------------------------------------------------------------
# Refusals: nothing in an MMC deck is dropped
# --------------------------------------------------------------------------------------

_BASE = ["GRID, 1, , 0., 0., 0.", "GRID, 2, , 1., 0., 0.", "CONM2, 1, 1, , 10.0"]


@pytest.mark.parametrize("cards, match", [
    (["MASSSET, 11, 1.0, 1.0, 0, 1.0, 101"],
     "MASSSET 11: mass increment 101 is not defined"),
    (["MASSSET, 11, 1.0, 1.0, 0", "BEGIN MASSID=101", "GRID, 9, , 0., 0., 0."],
     "BEGIN MASSID=101: GRID in an incremental mass section"),
    (["MASSSET, 11, 1.0, 1.0, 0", "BEGIN MASSID=101", "CONM2, 1, 2, , 1.0"],
     "BEGIN MASSID=101: CONM2 1 is already defined"),
    (["BEGIN MASSID=101", "CONM2, 5, 2, , 1.0", "BEGIN MASSID=101", "CONM2, 6, 2, , 1.0"],
     "BEGIN MASSID=101: a second section"),
    (["MASSSET, 101, 1.0, 1.0, 0", "BEGIN MASSID=101", "CONM2, 5, 2, , 1.0"],
     "MASSSET 101: the ID is also a BEGIN MASSID section"),
    (["MASSSET, 10, 1.0, 1.0, 0", "MASSCASE, 10, EMPTY, 1.0"],
     "MASSSET 10: the ID is also a MASSCASE SID"),
    (["MASSSET, 11, 1.0, -1.0, 0"], "MASSSET 11: scale factors must be >= 0.0"),
    (["MASSSET, 11, 1.0, 1.0"], "MASSSET 11: S1=1.0 has no ID"),
    (["MASSCASE, 10, X, 1.0", "+, ADD, 5", "BEGIN MASSID=101", "CONM2, 5, 2, , 1.0"],
     "MASSCASE 10: names CONM2 \\[5\\], which is in a BEGIN MASSID section"),
    (["BEGIN SUPER=2 MASSID=101", "CONM2, 5, 2, , 1.0"], "partitioned Bulk Data Sections"),
])
def test_refused(cards, match):
    with pytest.raises(ValueError, match=match):
        parse_bulk_data(_BASE + cards)


def test_a_repeated_increment_adds():
    """M = S0 · Σ Si·Mi: naming increment 101 twice counts it twice."""
    bulk = parse_bulk_data(_BASE + ["MASSSET, 11, 1.0, 1.0, 0, 0.5, 101, 0.5, 101",
                                    "BEGIN MASSID=101 LABEL='X'", "CONM2, 5, 2, , 4.0"])
    case = resolve_mass_case(bulk, 11)
    assert case.conm2s[5].m == pytest.approx(4.0)


def test_base_left_out_of_a_combination_is_absent():
    """No (Si, 0) term: the base takes no part in M_ID (p.2018 formula)."""
    bulk = parse_bulk_data(_BASE + ["MASSSET, 11, 1.0, 1.0, 101",
                                    "BEGIN MASSID=101", "CONM2, 5, 2, , 4.0"])
    case = resolve_mass_case(bulk, 11)
    assert case.scale == 0.0 and case.conm2s[1].m == 0.0 and case.conm2s[5].m == 4.0


def test_case_control_masscase_and_massset_in_one_subcase_are_refused():
    with pytest.raises(ValueError, match="MASSCASE and MASSSET in one subcase"):
        parse_case_control(["SOL 144", "SUBCASE 1", "  MASSCASE = 10", "  MASSSET = 11"])


def test_a_selector_must_name_its_own_kind(tmp_path):
    deck = tmp_path / "d.bdf"
    deck.write_text("\n".join(["SOL 101", "SUBCASE 1", "  MASSCASE = 11", "BEGIN BULK",
                               *_BASE, "MASSSET, 11, 1.0, 1.0, 0", "ENDDATA"]) + "\n")
    with pytest.raises(ValueError, match="MASSCASE = 11 selects an MSC MASSSET; select it "
                                         "with MASSSET = 11"):
        parse_bdf(str(deck))
