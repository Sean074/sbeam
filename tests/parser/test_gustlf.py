"""P-GUST gates — GUSTLF card parsing and cross-reference validation (issue #1).

Design note: ``docs/30_future/designs/gust_pratt_23341.md`` §7.2.

GUSTLF is a provenance card: only TRIMID, N and G affect the solution, and the
solver deliberately does not own the gust arithmetic.  The parser therefore
validates what it *can* falsify — references, required fields, and the one
range the regulation's own formula fixes (0 < K_g < 0.88) — and records the
rest.
"""

import warnings

import pytest

from sbeam.model.card_writers import write_gustlf
from sbeam.parser.bdf_reader import parse_bdf

_PREAMBLE = """SOL 144
TITLE = GUSTLF parse gates
BEGIN BULK
AEROS, 0, 0, 1.0, 8.0, 8.0, 0, 0
AESTAT, 501, ANGLEA
AESTAT, 503, URDD3
SUPORT, 1, 3
GRID, 1, 0, 0.0, 0.0, 0.0
"""


def _deck(tmp_path, *cards, trim="TRIM, 1, 0.0, 100.0, ANGLEA, 0.1"):
    text = _PREAMBLE + trim + "\n" + "\n".join(cards) + "\nENDDATA\n"
    path = tmp_path / "gustlf.bdf"
    path.write_text(text)
    return path


def _parse(path):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_bdf(str(path))


class TestGustlfParsing:
    def test_full_card_round_trips(self, tmp_path):
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 3.996, 9.81, 15.24, 61.73, 0.6365, 13.855",
            "+, 5.3335, RIGID, 0.0",
        )
        _cc, bulk = _parse(deck)
        gust = bulk.gustlfs[700]
        assert (gust.sid, gust.trimid) == (700, 1)
        assert gust.n == pytest.approx(3.996)
        assert gust.g == pytest.approx(9.81)
        assert gust.ude == pytest.approx(15.24)
        assert gust.veas == pytest.approx(61.73)
        assert gust.kg == pytest.approx(0.6365)
        assert gust.mu == pytest.approx(13.855)
        assert gust.a == pytest.approx(5.3335)
        assert gust.asrc == "RIGID"
        assert gust.alt == pytest.approx(0.0)

    def test_minimal_card_defaults_the_provenance(self, tmp_path):
        """A hand-authored card may record nothing but the load factor."""
        deck = _deck(tmp_path, "GUSTLF, 700, 1, 2.5, 9.81")
        _cc, bulk = _parse(deck)
        gust = bulk.gustlfs[700]
        assert (gust.ude, gust.veas, gust.kg, gust.mu, gust.a) == (0.0,) * 5
        assert gust.asrc == "RIGID"
        assert gust.alt is None, "sea level is a real altitude; absent must stay None"

    def test_urdd3_and_sense_derive_from_n(self, tmp_path):
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 3.996, 9.81",
            "GUSTLF, 701, 1, -1.996, 9.81",
            trim="TRIM, 1, 0.0, 100.0, ANGLEA, 0.1\nTRIM, 2, 0.0, 100.0, ANGLEA, 0.1",
        )
        # Two GUSTLFs on one TRIM is refused, so point the second at TRIM 2.
        deck.write_text(deck.read_text().replace("GUSTLF, 701, 1,", "GUSTLF, 701, 2,"))
        _cc, bulk = _parse(deck)
        up, down = bulk.gustlfs[700], bulk.gustlfs[701]
        assert up.urdd3 == pytest.approx(-3.996 * 9.81)
        assert down.urdd3 == pytest.approx(1.996 * 9.81)
        assert up.sense == "UP-GUST"
        assert down.sense == "DOWN-GUST"

    def test_writer_round_trips_through_the_parser(self, tmp_path):
        """S-GUST6b — the script's cards and write_gustlf agree by construction."""
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 3.996, 9.81, 15.24, 61.73, 0.6365, 13.855",
            "+, 5.3335, RIGID, 1234.5",
        )
        _cc, bulk = _parse(deck)
        original = bulk.gustlfs[700]

        rewritten = _deck(tmp_path, *write_gustlf(original))
        _cc2, bulk2 = _parse(rewritten)
        assert bulk2.gustlfs[700] == original

    def test_absent_altitude_survives_a_write_read_cycle(self, tmp_path):
        deck = _deck(tmp_path, "GUSTLF, 700, 1, 2.5, 9.81")
        _cc, bulk = _parse(deck)
        rewritten = _deck(tmp_path, *write_gustlf(bulk.gustlfs[700]))
        _cc2, bulk2 = _parse(rewritten)
        assert bulk2.gustlfs[700].alt is None


class TestPGustRejections:
    def test_p_gust1_unknown_trimid(self, tmp_path):
        deck = _deck(tmp_path, "GUSTLF, 700, 99, 2.5, 9.81")
        with pytest.raises(ValueError, match="TRIMID 99 not found"):
            _parse(deck)

    def test_p_gust2_trim_also_prescribes_urdd3(self, tmp_path):
        """Two sources for one quantity — the DEF-M4 antipattern."""
        deck = _deck(
            tmp_path, "GUSTLF, 700, 1, 2.5, 9.81",
            trim="TRIM, 1, 0.0, 100.0, ANGLEA, 0.1, URDD3, -9.81",
        )
        with pytest.raises(ValueError, match="also prescribes URDD3"):
            _parse(deck)

    def test_p_gust3_nonpositive_gravity(self, tmp_path):
        deck = _deck(tmp_path, "GUSTLF, 700, 1, 2.5, 0.0")
        with pytest.raises(ValueError, match="G must be > 0"):
            _parse(deck)

    def test_p_gust4_bad_asrc(self, tmp_path):
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 2.5, 9.81, 15.24, 61.73, 0.6365, 13.855",
            "+, 5.3335, ELASTIC, 0.0",
        )
        with pytest.raises(ValueError, match="ASRC must be RIGID or RESTRAINED"):
            _parse(deck)

    @pytest.mark.parametrize("kg", ["0.88", "0.95", "-0.1"])
    def test_p_gust5_alleviation_factor_out_of_range(self, tmp_path, kg):
        """K_g = 0.88 mu/(5.3+mu) is strictly inside (0, 0.88) for every mu."""
        deck = _deck(
            tmp_path,
            f"GUSTLF, 700, 1, 2.5, 9.81, 15.24, 61.73, {kg}, 13.855",
        )
        with pytest.raises(ValueError, match="KG must lie in"):
            _parse(deck)

    @pytest.mark.parametrize(
        "card,field",
        [
            ("GUSTLF, 700, 1, 2.5, 9.81, -15.24", "UDE"),
            ("GUSTLF, 700, 1, 2.5, 9.81, 15.24, -61.73", "VEAS"),
            ("GUSTLF, 700, 1, 2.5, 9.81, 15.24, 61.73, 0.6, -13.9", "MU"),
        ],
    )
    def test_p_gust6_negative_recorded_provenance(self, tmp_path, card, field):
        deck = _deck(tmp_path, card)
        with pytest.raises(ValueError, match=f"{field} must be >= 0"):
            _parse(deck)

    def test_missing_required_fields(self, tmp_path):
        deck = _deck(tmp_path, "GUSTLF, 700, 1")
        with pytest.raises(ValueError, match="SID, TRIMID, N and G are required"):
            _parse(deck)

    def test_duplicate_sid(self, tmp_path):
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 2.5, 9.81",
            "GUSTLF, 700, 1, 3.5, 9.81",
        )
        with pytest.raises(ValueError, match="Duplicate GUSTLF SID 700"):
            _parse(deck)

    def test_two_gust_cards_on_one_trim(self, tmp_path):
        """One gust case per TRIM — otherwise URDD3 has two values."""
        deck = _deck(
            tmp_path,
            "GUSTLF, 700, 1, 2.5, 9.81",
            "GUSTLF, 701, 1, -0.5, 9.81",
        )
        with pytest.raises(ValueError, match="already driven by GUSTLF 700"):
            _parse(deck)

    def test_no_urdd3_aestat(self, tmp_path):
        text = _PREAMBLE.replace("AESTAT, 503, URDD3\n", "")
        text += "TRIM, 1, 0.0, 100.0, ANGLEA, 0.1\nGUSTLF, 700, 1, 2.5, 9.81\nENDDATA\n"
        path = tmp_path / "no_urdd3.bdf"
        path.write_text(text)
        with pytest.raises(ValueError, match="no AESTAT defines URDD3"):
            _parse(path)


class TestGustlfDofAccounting:
    def test_gust_trim_is_not_reported_over_determined(self, tmp_path):
        """§6.1a — URDD3 counts as prescribed once a GUSTLF supplies it.

        Without this the generated gust decks warn 'over-determined' on every
        case, which is exactly the noise that trains users to ignore warnings.
        """
        deck = _deck(
            tmp_path, "GUSTLF, 700, 1, 2.5, 9.81",
            trim="TRIM, 1, 0.0, 100.0, ANGLEA, 0.1",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            parse_bdf(str(deck))
        assert not [w for w in caught if "over-determined" in str(w.message)]
