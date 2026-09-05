"""S-GUST gates — sbeam_tools.cases.gust (FAR/CS 23.341 quasi-static gust).

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` §7.1 (issue #1).

Gate map:

===========  =============================================================
S-GUST1      Consistent-units ``dn`` reproduces the regulation's own
             Imperial ``498`` form to within 0.2 %.  This is the *external*
             anchor: 498 is nothing but ``2/(rho_0 * 1.6878)`` packaged with
             the knots conversion, so agreeing with it validates the
             formula's packaging against the regulation rather than against
             our own arithmetic.
S-GUST2      ISA density at 0 / 20,000 / 50,000 ft vs published tables.
S-GUST3      23.333(c) U_de schedule, both unit systems.
S-GUST4      K_g strictly in (0, 0.88); dn monotone in V and in W/S.
S-GUST5      Flagship end-to-end, every expected value recomputed from the
             parsed deck (the VAL2 discipline) — never module constants.
S-GUST6a     The generated deck parses; its TRIM cards carry the expected
             q / RHOREF / labels and leave URDD3 unprescribed for GUSTLF.
===========  =============================================================

S-GUST6b (GUSTLF cards re-emit byte-identically through ``card_writers``)
is deferred until the ``GUSTLF`` card itself lands — the script writes the
card through ``write_card`` today so the two agree by construction.
"""

import math
import shutil
import warnings
from pathlib import Path

import pytest

from sbeam_tools.cases.gust import (
    alleviation_factor,
    derived_gust_velocity,
    emit_deck,
    generate_cases,
    gust_increment,
    mass_ratio,
)
from sbeam_tools.common import UNIT_SYSTEMS, isa_density, read_airplane

SAMPLE = Path(__file__).parent.parent.parent / "sample"
FLAGSHIP = SAMPLE / "cessna210_flagship_trim.bdf"

SI = UNIT_SYSTEMS["SI"]
IMPERIAL = UNIT_SYSTEMS["IMPERIAL"]

_KT_TO_FPS = 1.6878099
_FT = 0.3048

# The flagship's own cruise point, so the gate reproduces the design note's
# worked numbers.  g = 9.81 matches the deck's TRIM cards (URDD3 = -9.81 at 1g).
_V_CRUISE = 61.7302
_G_DECK = 9.81


# --------------------------------------------------------------------------- #
# S-GUST1 — the Imperial 498 identity (external anchor)
# --------------------------------------------------------------------------- #

class TestSGust1ImperialIdentity:
    @pytest.mark.parametrize(
        "w_over_s,cbar,a,v_kt,ude_fps",
        [
            (17.8, 4.9, 4.5, 122.0, 50.0),   # light single, V_C
            (17.8, 4.9, 4.5, 165.0, 25.0),   # same airplane, V_D
            (35.0, 6.5, 5.2, 200.0, 50.0),   # heavier twin
            (12.0, 4.0, 4.0, 90.0, 66.0),    # low wing loading, V_B
        ],
    )
    def test_matches_the_regulation_constant(self, w_over_s, cbar, a, v_kt, ude_fps):
        """dn from consistent units equals the 498 form to within 0.2 %."""
        rho0 = IMPERIAL.rho0
        g = IMPERIAL.g
        v_fps = v_kt * _KT_TO_FPS

        mu = mass_ratio(w_over_s, rho0, cbar, a, g)
        kg = alleviation_factor(mu)
        # S = 1 and W = W/S, so the ratio S/W is exactly 1/(W/S).
        ours = gust_increment(kg, rho0, ude_fps, v_fps, a, 1.0, w_over_s)

        regulation = kg * ude_fps * v_kt * a / (498.0 * w_over_s)
        assert ours == pytest.approx(regulation, rel=2e-3)

    def test_the_constant_is_where_we_think_it_is(self):
        """498 is 2/(rho_0 * kt->fps) — the identity the gate above rests on."""
        implied = 2.0 / (IMPERIAL.rho0 * _KT_TO_FPS)
        assert implied == pytest.approx(498.0, rel=2e-3)


# --------------------------------------------------------------------------- #
# S-GUST2 — ISA standard atmosphere
# --------------------------------------------------------------------------- #

class TestSGust2Atmosphere:
    @pytest.mark.parametrize(
        "alt_ft,published_kgm3",
        [(0.0, 1.225), (20000.0, 0.652694), (50000.0, 0.186479)],
    )
    def test_density_matches_published_isa(self, alt_ft, published_kgm3):
        got = isa_density(alt_ft * _FT, SI)
        assert got == pytest.approx(published_kgm3, rel=5e-3)

    def test_imperial_and_si_describe_the_same_air(self):
        """The two unit systems' densities differ only by the slug/ft^3 factor."""
        for alt_ft in (0.0, 10000.0, 40000.0):
            si = isa_density(alt_ft * _FT, SI)
            imp = isa_density(alt_ft, IMPERIAL)
            assert imp * 515.378818 == pytest.approx(si, rel=1e-12)

    def test_density_falls_monotonically(self):
        alts = [0.0, 5000.0, 20000.0, 36000.0, 50000.0]
        rhos = [isa_density(a, IMPERIAL) for a in alts]
        assert all(b < a for a, b in zip(rhos, rhos[1:]))

    def test_below_sea_level_raises(self):
        with pytest.raises(ValueError, match="below sea level"):
            isa_density(-100.0, SI)


# --------------------------------------------------------------------------- #
# S-GUST3 — the 23.333(c) U_de schedule
# --------------------------------------------------------------------------- #

class TestSGust3GustSchedule:
    @pytest.mark.parametrize(
        "speed,low_fps,high_fps",
        [("VC", 50.0, 25.0), ("VD", 25.0, 12.5), ("VB", 66.0, 38.0)],
    )
    def test_schedule_endpoints_and_taper(self, speed, low_fps, high_fps):
        """Constant to 20,000 ft, then linear to the 50,000 ft value."""
        assert derived_gust_velocity(speed, 0.0, IMPERIAL) == pytest.approx(low_fps)
        assert derived_gust_velocity(speed, 20000.0, IMPERIAL) == pytest.approx(low_fps)
        assert derived_gust_velocity(speed, 50000.0, IMPERIAL) == pytest.approx(high_fps)
        midpoint = derived_gust_velocity(speed, 35000.0, IMPERIAL)
        assert midpoint == pytest.approx(0.5 * (low_fps + high_fps))

    def test_si_is_the_same_schedule_in_metres(self):
        for speed in ("VC", "VD", "VB"):
            for alt_ft in (0.0, 20000.0, 35000.0, 50000.0):
                imp = derived_gust_velocity(speed, alt_ft, IMPERIAL)
                si = derived_gust_velocity(speed, alt_ft * _FT, SI)
                assert si == pytest.approx(imp * _FT, rel=1e-12)

    def test_the_familiar_values(self):
        """The numbers an engineer expects to see, stated once."""
        assert derived_gust_velocity("VC", 0.0, IMPERIAL) == pytest.approx(50.0)
        assert derived_gust_velocity("VC", 0.0, SI) == pytest.approx(15.24)
        assert derived_gust_velocity("VD", 0.0, SI) == pytest.approx(7.62)

    def test_above_the_schedule_raises_rather_than_extrapolating(self):
        with pytest.raises(ValueError, match="50,000 ft"):
            derived_gust_velocity("VC", 55000.0, IMPERIAL)

    def test_unknown_design_speed_raises(self):
        with pytest.raises(ValueError, match="unknown design speed"):
            derived_gust_velocity("VA", 0.0, IMPERIAL)


# --------------------------------------------------------------------------- #
# S-GUST4 — alleviation-factor bounds and monotonicity
# --------------------------------------------------------------------------- #

class TestSGust4BoundsAndTrends:
    def test_kg_is_strictly_inside_its_range(self):
        """0 < K_g < 0.88 for every physical mass ratio — the card's parse gate."""
        for mu in (0.01, 0.5, 5.0, 13.855, 50.0, 500.0, 1e6):
            kg = alleviation_factor(mu)
            assert 0.0 < kg < 0.88

    def test_kg_rises_with_mass_ratio(self):
        mus = [1.0, 5.0, 10.0, 20.0, 100.0]
        kgs = [alleviation_factor(m) for m in mus]
        assert all(b > a for a, b in zip(kgs, kgs[1:]))

    def test_kg_approaches_but_never_reaches_the_asymptote(self):
        assert alleviation_factor(1e9) == pytest.approx(0.88, rel=1e-6)
        assert alleviation_factor(1e9) < 0.88

    def test_increment_rises_with_speed(self):
        base = dict(kg=0.64, rho0=1.225, ude=15.24, a=5.33, sref=16.24, weight=10605.0)
        dns = [gust_increment(v_eas=v, **base) for v in (40.0, 60.0, 80.0, 100.0)]
        assert all(b > a for a, b in zip(dns, dns[1:]))

    def test_increment_falls_with_wing_loading(self):
        """Heavier at the same area is less gust-sensitive — the physical trend."""
        sref, a, cbar, rho, rho0, g, ude, v = 16.24, 5.33, 1.4707, 1.225, 1.225, 9.81, 15.24, 61.73
        dns = []
        for weight in (8000.0, 10605.0, 14000.0, 18000.0):
            mu = mass_ratio(weight / sref, rho, cbar, a, g)
            kg = alleviation_factor(mu)
            dns.append(gust_increment(kg, rho0, ude, v, a, sref, weight))
        assert all(b < a for a, b in zip(dns, dns[1:]))

    def test_nonphysical_inputs_raise(self):
        with pytest.raises(ValueError):
            mass_ratio(650.0, 0.0, 1.47, 5.33, 9.81)
        with pytest.raises(ValueError):
            alleviation_factor(0.0)
        with pytest.raises(ValueError):
            gust_increment(0.64, 1.225, 15.24, 61.73, 5.33, 16.24, 0.0)


# --------------------------------------------------------------------------- #
# S-GUST5 — flagship end-to-end, recomputed from the parsed deck
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def flagship():
    """Read the flagship once — the rigid derivative needs no trim solve."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return read_airplane(FLAGSHIP, trim_template=1, massets=[None])


@pytest.fixture(scope="module")
def flagship_cases(flagship):
    return generate_cases(
        flagship, SI, {"VC": _V_CRUISE}, [0.0], _G_DECK, sid_base=9000
    )


class TestSGust5Flagship:
    def test_reads_reference_geometry_from_the_deck(self, flagship):
        """S, cbar and the rigid slope come from the model, not from constants."""
        assert flagship.sref == pytest.approx(16.24)
        assert flagship.cref == pytest.approx(1.4707)
        assert flagship.cz_alpha == pytest.approx(5.3335, abs=5e-4)
        assert flagship.includes == ["cessna210_flagship_bulk.bdf"]

    def test_the_template_contributes_everything_but_urdd3(self, flagship):
        assert "URDD3" not in flagship.template_vars
        assert flagship.template_vars == {"PITCH": 0.0, "URDD5": 0.0}
        assert flagship.template_spc == 1

    def test_generates_the_plus_minus_pair(self, flagship_cases):
        assert [c.sense for c in flagship_cases] == ["UP", "DOWN"]
        assert [c.sid for c in flagship_cases] == [9000, 9001]

    def test_derivation_recomputed_from_the_deck(self, flagship, flagship_cases):
        """Every quantity re-derived here from deck-read properties (VAL2 rule)."""
        up = flagship_cases[0]
        weight = flagship.mass_cases[0].mass * _G_DECK
        a = flagship.cz_alpha
        rho = rho0 = 1.225  # ISA sea level, both densities coincide at h = 0

        mu = 2.0 * (weight / flagship.sref) / (rho * flagship.cref * a * _G_DECK)
        kg = 0.88 * mu / (5.3 + mu)
        dn = kg * rho0 * 15.24 * _V_CRUISE * a * flagship.sref / (2.0 * weight)

        assert up.weight == pytest.approx(weight, rel=1e-12)
        assert up.mu == pytest.approx(mu, rel=1e-12)
        assert up.kg == pytest.approx(kg, rel=1e-12)
        assert up.dn == pytest.approx(dn, rel=1e-12)
        assert up.n == pytest.approx(1.0 + dn, rel=1e-12)
        assert flagship_cases[1].n == pytest.approx(1.0 - dn, rel=1e-12)

    def test_design_note_numbers(self, flagship_cases):
        """Regression anchor: the worked table in the design note §7.3."""
        up, down = flagship_cases
        assert up.mu == pytest.approx(13.855, abs=5e-3)
        assert up.kg == pytest.approx(0.6365, abs=5e-4)
        assert up.dn == pytest.approx(2.9956, abs=5e-4)
        assert up.n == pytest.approx(3.996, abs=1e-3)
        assert down.n == pytest.approx(-1.996, abs=1e-3)

    def test_gust_case_is_more_critical_than_the_deck_manoeuvre(self, flagship_cases):
        """The reason the omission mattered: n = 4.0 beats the deck's 2.5 g case."""
        assert flagship_cases[0].n > 2.5

    def test_urdd3_follows_the_charter_sign(self, flagship_cases):
        """URDD3 = -n*g (charter §5); the down-gust case is positive."""
        up, down = flagship_cases
        assert up.urdd3 == pytest.approx(-up.n * _G_DECK, rel=1e-12)
        assert up.urdd3 < 0.0
        assert down.urdd3 > 0.0

    def test_dynamic_pressure_matches_the_deck(self, flagship_cases):
        """q = 0.5 rho_0 V_EAS^2 reproduces the flagship's own 2334 Pa."""
        assert flagship_cases[0].q == pytest.approx(2334.0, rel=1e-4)


# --------------------------------------------------------------------------- #
# S-GUST6a — the generated deck parses
# --------------------------------------------------------------------------- #

class TestSGust6GeneratedDeck:
    @pytest.fixture(scope="class")
    def generated(self, tmp_path_factory, flagship, flagship_cases):
        out = tmp_path_factory.mktemp("gust")
        shutil.copy(SAMPLE / "cessna210_flagship_bulk.bdf", out)
        lines = emit_deck(flagship_cases, flagship, SI, "test", "S-GUST6a")
        deck = out / "gust_cases.bdf"
        deck.write_text("\n".join(lines) + "\n")
        return deck

    def test_deck_parses(self, generated):
        from sbeam.parser.bdf_reader import parse_bdf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cc, bulk = parse_bdf(str(generated))
        assert cc.sol == 144
        assert [sc.subcase_id for sc in cc.subcases] == [9000, 9001]
        assert all(sc.spc_sid == 1 for sc in cc.subcases)
        assert set(bulk.trims) >= {9000, 9001}

    def test_generated_trims_carry_the_flight_condition(self, generated, flagship_cases):
        from sbeam.parser.bdf_reader import parse_bdf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _cc, bulk = parse_bdf(str(generated))
        for case in flagship_cases:
            trim = bulk.trims[case.sid]
            assert trim.q == pytest.approx(case.q, rel=1e-6)
            assert trim.rhoref == pytest.approx(case.rho, rel=1e-6)
            # URDD3 is GUSTLF's to supply — never authored on the TRIM (DEF-M4).
            assert "URDD3" not in trim.vars
            assert trim.vars == {"PITCH": 0.0, "URDD5": 0.0}

    def test_header_records_how_it_was_made(self, generated):
        text = generated.read_text()
        assert "GENERATED by sbeam-cases" in text
        assert "Units: SI" in text
        assert "Rigid CZ_alpha" in text

    def test_gustlf_cards_are_emitted_for_every_case(self, generated, flagship_cases):
        """Card is not implemented yet, so assert on the emitted text (S-GUST6b)."""
        lines = generated.read_text().splitlines()
        gustlf = [ln for ln in lines if ln.startswith("GUSTLF,")]
        assert len(gustlf) == len(flagship_cases)
        for line, case in zip(gustlf, flagship_cases):
            fields = [f.strip() for f in line.split(",")]
            assert int(fields[1]) == case.sid
            assert int(fields[2]) == case.sid  # TRIMID
            assert float(fields[3]) == pytest.approx(case.n, rel=1e-5)
            assert float(fields[4]) == pytest.approx(case.g, rel=1e-6)

    def test_no_nonfinite_values_reach_the_deck(self, generated):
        for line in generated.read_text().splitlines():
            if line.startswith("$") or not line:
                continue
            for field in line.split(","):
                token = field.strip()
                try:
                    value = float(token)
                except ValueError:
                    continue
                assert math.isfinite(value)
