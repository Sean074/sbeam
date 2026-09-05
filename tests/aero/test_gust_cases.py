"""V-GUST gates — quasi-static gust load cases end-to-end (issue #1).

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` §7.2.

Gate map:

=========  ================================================================
V-GUST1    The trim closes on the gust load factor: lift = n*W.
V-GUST2    The +/- pair straddles 1 g, with incidence ordered by n —
           signs relative to each other, never absolute (charter §6).
V-GUST3    The negative-n (down-gust) case solves and its URDD3 is positive.
V-GUST4    Monitor and section-cut loads flow through unchanged.
V-GUST5    The f06 provenance block, and URDD3 reported as PRESCRIBED.
V-GUST6    A deck without GUSTLF emits no gust block.
V-GUST7    DEF-M20 (#23): a negative URDD3 against an absent or z-up RCSID
           warns rather than silently trimming inverted lift.
=========  ================================================================

Runs the shipped ``sample/cessna210_flagship_gust.bdf``, which the generator
script produced — so these gates also prove the script's output is solvable.
"""

import warnings
from pathlib import Path

import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.gpwg import compute_gpwg
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import build_f06_sol144_text
from sbeam.solver.sol144 import AeroCache, run_sol144_trim

SAMPLE = Path(__file__).parent.parent.parent / "sample"
GUST_DECK = SAMPLE / "cessna210_flagship_gust.bdf"
TRIM_DECK = SAMPLE / "cessna210_flagship_trim.bdf"

# SUBCASE 9000/9001 are the +/- pair at V_C for the FERRY mass case.
_UP, _DOWN = 0, 1


@pytest.fixture(scope="module")
def model():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(str(GUST_DECK))
        gi = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=gi)
        cache = AeroCache(bulk, gi, seed=aero)
    return cc, bulk, aero, cache


@pytest.fixture(scope="module")
def pair(model):
    """The up/down gust pair at V_C, FERRY — solved once."""
    cc, bulk, aero, cache = model
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for idx in (_UP, _DOWN):
            out.append(run_sol144_trim(bulk, cc.subcases[idx], aero, aero_cache=cache))
    return out


class TestVGust1TrimClosesOnLoadFactor:
    def test_lift_equals_n_times_weight(self, model, pair):
        """The whole point: the trim carries exactly the gust load factor."""
        _cc, bulk, _aero, _cache = model
        for result, subcase in zip(pair, (_UP, _DOWN)):
            gust = bulk.gustlfs[_cc_subcase(model, subcase).gustlf_sid]
            weight = compute_gpwg(bulk, _cc_subcase(model, subcase).massset_sid
                                  ).total_mass * gust.g
            lift = result.total_cl * result.q * bulk.aeros.sref
            assert lift == pytest.approx(gust.n * weight, rel=1e-6)

    def test_urdd3_is_the_cards_value(self, model, pair):
        _cc, bulk, _aero, _cache = model
        for result, idx in zip(pair, (_UP, _DOWN)):
            gust = bulk.gustlfs[_cc_subcase(model, idx).gustlf_sid]
            assert result.trim_vars["URDD3"] == pytest.approx(gust.urdd3, rel=1e-12)
            assert result.trim_vars["URDD3"] == pytest.approx(-gust.n * gust.g, rel=1e-12)

    def test_trim_stays_determined(self, pair):
        """URDD3 arriving from GUSTLF keeps the DOF count square."""
        assert all(r.trim_mode == "determined" for r in pair)


class TestVGust2ThePair:
    def test_pair_straddles_one_g(self, model):
        _cc, bulk, _aero, _cache = model
        up = bulk.gustlfs[_cc_subcase(model, _UP).gustlf_sid]
        down = bulk.gustlfs[_cc_subcase(model, _DOWN).gustlf_sid]
        assert up.n > 1.0 > down.n
        assert up.n - 1.0 == pytest.approx(1.0 - down.n, rel=1e-9)

    def test_incidence_is_ordered_by_load_factor(self, pair):
        """Relative gate: more load factor, more incidence.  Never an absolute sign."""
        up, down = pair
        assert up.trim_vars["ANGLEA"] > down.trim_vars["ANGLEA"]

    def test_elevator_moves_opposite_ways(self, pair):
        """Also relative — 'positive elevator' has no airframe-independent sense."""
        up, down = pair
        assert up.trim_vars["ELEV"] < down.trim_vars["ELEV"]


class TestVGust3DownGust:
    def test_negative_load_factor_solves(self, model, pair):
        _cc, bulk, _aero, _cache = model
        gust = bulk.gustlfs[_cc_subcase(model, _DOWN).gustlf_sid]
        assert gust.n < 0.0, "the flagship down-gust should overcome 1 g"
        assert pair[_DOWN].trim_mode == "determined"

    def test_down_gust_urdd3_is_positive(self, pair):
        """The DEF-M20 danger zone — and the case that makes the guard reachable."""
        assert pair[_DOWN].trim_vars["URDD3"] > 0.0

    def test_down_gust_needs_negative_incidence(self, pair):
        assert pair[_DOWN].trim_vars["ANGLEA"] < 0.0


class TestVGust4LoadsFlowThrough:
    def test_monitor_loads_present(self, pair):
        for result in pair:
            assert result.monitor_loads, "gust cases must produce monitor loads"

    def test_section_loads_present(self, pair):
        for result in pair:
            assert result.section_loads, "gust cases must produce section-cut loads"

    def test_net_loads_scale_with_the_load_factor(self, model, pair):
        """A 5.4 g case carries more net load than a -3.4 g one, in magnitude."""
        import numpy as np

        up, down = pair
        assert np.abs(up.net_loads).sum() > np.abs(down.net_loads).sum()


class TestVGust5F06Block:
    @pytest.fixture(scope="class")
    def f06(self, model, pair):
        cc, bulk, _aero, _cache = model
        return build_f06_sol144_text(cc, bulk, pair[_UP], cc.subcases[_UP].subcase_id)

    def test_block_is_present_with_its_values(self, model, f06):
        _cc, bulk, _aero, _cache = model
        gust = bulk.gustlfs[_cc_subcase(model, _UP).gustlf_sid]
        assert "G U S T   L O A D   C O N D I T I O N" in f06
        assert f"GUSTLF = {gust.sid}" in f06
        assert "SENSE = UP-GUST" in f06
        assert "RECORDED PROVENANCE ONLY" in f06

    def test_recorded_altitude_is_not_mistaken_for_absent(self, f06):
        """Sea level is a real altitude — 0.0 must print as a value."""
        assert "ALTITUDE = 0.000000E+00" in f06
        assert "ALTITUDE = NOT RECORDED" not in f06

    def test_urdd3_is_reported_prescribed(self, f06):
        """It comes from GUSTLF, not the TRIM card — but it is not a solved unknown."""
        urdd3_rows = [ln for ln in f06.splitlines() if ln.strip().startswith("URDD3 ")]
        assert urdd3_rows, "no URDD3 row in the trim-variable table"
        assert "PRESCRIBED" in urdd3_rows[0], urdd3_rows[0]

    def test_delta_n_is_n_minus_one(self, model, f06):
        _cc, bulk, _aero, _cache = model
        gust = bulk.gustlfs[_cc_subcase(model, _UP).gustlf_sid]
        expected = f"{gust.n - 1.0:13.6E}".strip()
        assert f"DELTA-N (N-1) = {expected}" in f06


class TestVGust6NonRegression:
    def test_a_deck_without_gustlf_has_no_gust_block(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cc, bulk = parse_bdf(str(TRIM_DECK))
            gi = build_grid_index(bulk)
            aero = build_aero_model(bulk, grid_index=gi)
            result = run_sol144_trim(bulk, cc.subcases[0], aero)
        f06 = build_f06_sol144_text(cc, bulk, result, cc.subcases[0].subcase_id)
        assert "G U S T   L O A D   C O N D I T I O N" not in f06
        assert result.gust_echo is None


class TestVGust7DefM20Guard:
    """DEF-M20 (#23) — the RCSID orientation guard for the load-factor sign."""

    def test_absent_rcsid_with_negative_urdd3_warns(self):
        """sample/val_dihedral_trim.bdf has RCSID 0 and URDD3 = -9.81, deliberately."""
        deck = SAMPLE / "val_dihedral_trim.bdf"
        cc, bulk = parse_bdf(str(deck))
        gi = build_grid_index(bulk)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            aero = build_aero_model(bulk, grid_index=gi)
            run_sol144_trim(bulk, cc.subcases[0], aero)
        messages = [str(w.message) for w in caught]
        assert any("DEF-M20" in m for m in messages), messages
        assert any("inverted lift" in m.lower() for m in messages), messages
        assert any("no RCSID" in m for m in messages), messages

    def test_the_flagship_z_down_rcsid_does_not_warn(self, model, pair):
        """The standard convention must stay silent, or the guard is just noise."""
        cc, bulk, aero, cache = model
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            run_sol144_trim(bulk, cc.subcases[_UP], aero, aero_cache=cache)
        assert not [w for w in caught if "DEF-M20" in str(w.message)]

    def test_positive_urdd3_never_warns(self, model):
        """A down-gust prescribes URDD3 > 0, which the convention does not govern."""
        cc, bulk, aero, cache = model
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            run_sol144_trim(bulk, cc.subcases[_DOWN], aero, aero_cache=cache)
        assert not [w for w in caught if "DEF-M20" in str(w.message)]


def _cc_subcase(model, idx):
    """The SubcaseControl at ``idx`` of the gust deck."""
    cc, _bulk, _aero, _cache = model
    return cc.subcases[idx]
