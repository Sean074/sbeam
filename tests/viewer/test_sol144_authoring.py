"""P12 S3 — SOL 144 authoring logic (pure) + AppTest render smoke."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sbeam.model.aero import Trim, Trimcon
from sbeam.model.constraint import Suport
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.viewer import sol144_authoring as logic

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample"


@pytest.fixture(scope="module")
def mloads_bulk():
    _, bulk = parse_bdf(SAMPLE_DIR / "ha144a_fullspan_mloads.bdf")
    return bulk


class TestSidAllocation:
    def test_next_free_sid(self, mloads_bulk):
        assert logic.next_free_sid(mloads_bulk, "trim") == max(mloads_bulk.trims) + 1
        assert logic.next_free_sid(mloads_bulk, "mloads") == max(mloads_bulk.mloads) + 1

    def test_next_free_sid_empty_family(self, mloads_bulk):
        assert logic.next_free_sid(mloads_bulk, "trimvar") == 1

    def test_suport_ids_use_gid(self, mloads_bulk):
        gids = [s.gid for s in mloads_bulk.supports]
        assert logic.next_free_sid(mloads_bulk, "suport") == max(gids) + 1


class TestConflicts:
    def test_file_sourced_sid_conflicts(self, mloads_bulk):
        sid = next(iter(mloads_bulk.trims))
        msgs = logic.find_sid_conflicts(mloads_bulk, "trim", sid, {})
        assert msgs and "already exists" in msgs[0]

    def test_authored_sid_does_not_conflict(self, mloads_bulk):
        sid = next(iter(mloads_bulk.trims))
        assert logic.find_sid_conflicts(mloads_bulk, "trim", sid, {"trim": {sid}}) == []

    def test_fresh_sid_does_not_conflict(self, mloads_bulk):
        assert logic.find_sid_conflicts(mloads_bulk, "trim", 99999, {}) == []


class TestApplyDelete:
    def test_apply_and_delete_dict_family(self, mloads_bulk):
        authored: dict[str, set[int]] = {}
        card = Trim(sid=9001, mach=0.5, q=10.0, vars={"PITCH": 0.0})
        logic.apply_card(mloads_bulk, "trim", card, authored)
        assert mloads_bulk.trims[9001] is card and 9001 in authored["trim"]
        logic.delete_card(mloads_bulk, "trim", 9001, authored)
        assert 9001 not in mloads_bulk.trims and 9001 not in authored["trim"]

    def test_apply_suport_replaces_by_gid(self, mloads_bulk):
        authored: dict[str, set[int]] = {}
        n0 = len(mloads_bulk.supports)
        logic.apply_card(mloads_bulk, "suport", Suport(gid=9002, dofs="3"), authored)
        logic.apply_card(mloads_bulk, "suport", Suport(gid=9002, dofs="35"), authored)
        added = [s for s in mloads_bulk.supports if s.gid == 9002]
        assert len(added) == 1 and added[0].dofs == "35"
        logic.delete_card(mloads_bulk, "suport", 9002, authored)
        assert len(mloads_bulk.supports) == n0

    def test_apply_trimcon_list(self, mloads_bulk):
        authored: dict[str, set[int]] = {}
        cons = [Trimcon(sid=9003, label="ELEV", sense="LE", rhs=0.4),
                Trimcon(sid=9003, label="ELEV", sense="GE", rhs=-0.4)]
        logic.apply_card(mloads_bulk, "trimcon", cons, authored)
        assert mloads_bulk.trimcons[9003] == cons
        logic.delete_card(mloads_bulk, "trimcon", 9003, authored)
        assert 9003 not in mloads_bulk.trimcons


class TestBoxRangesAndParsing:
    def test_caero_box_ranges(self, mloads_bulk):
        ranges = logic.caero_box_ranges(mloads_bulk)
        assert ranges
        for c in mloads_bulk.caero1s.values():
            if c.nspan * c.nchord:
                assert (c.eid, c.eid + c.nspan * c.nchord - 1) in ranges

    def test_boxes_outside_ranges(self):
        ranges = [(1101, 1112)]
        assert logic.boxes_outside_ranges([1101, 1112], ranges) == []
        assert logic.boxes_outside_ranges([1100, 1113], ranges) == [1100, 1113]
        assert logic.boxes_outside_ranges([5], []) == []

    def test_expand_int_tokens_thru(self):
        assert logic.expand_int_tokens("1101 THRU 1104, 1120") == \
            [1101, 1102, 1103, 1104, 1120]
        with pytest.raises(ValueError):
            logic.expand_int_tokens("1101 nope")

    def test_parse_float_list(self):
        assert logic.parse_float_list("0.0, 0.5 0.9") == [0.0, 0.5, 0.9]


class TestLabelOptions:
    def test_all_labels(self, mloads_bulk):
        labels = logic.label_options(mloads_bulk)
        assert "ELEV" in labels and "ANGLEA" in labels

    def test_modal_only_restricts_to_aesurf(self, mloads_bulk):
        labels = logic.label_options(mloads_bulk, modal_only=True)
        assert labels == ["ELEV"]


# ---------------------------------------------------------------------------
# AppTest smoke — authoring tab renders on a SOL 144 deck without exceptions
# ---------------------------------------------------------------------------

def _sbeam_app():
    from sbeam.viewer.app import main
    main()


def test_authoring_tab_renders(mloads_bulk):
    from streamlit.testing.v1 import AppTest

    cc, bulk = parse_bdf(SAMPLE_DIR / "ha144a_fullspan_mloads.bdf")
    at = AppTest.from_function(_sbeam_app, default_timeout=30)
    at.run()
    at.session_state["bulk_data"] = bulk
    at.session_state["case_control"] = cc
    at.session_state["_loaded_from_file_cc"] = cc
    at.session_state["cc_subcases"] = None
    at.session_state["selected_subcase_id"] = cc.subcases[0].subcase_id
    at.session_state["_uploaded_filename"] = "ha144a_fullspan_mloads.bdf"
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    # Family selectors exist and list the deck's existing cards.
    trim_sel = at.selectbox(key="auth_sel_trim")
    assert trim_sel is not None
    assert 1 in trim_sel.options or "1" in trim_sel.options
    assert at.selectbox(key="auth_sel_mloads") is not None
    assert at.selectbox(key="auth_sel_tabled1") is not None


# ---------------------------------------------------------------------------
# P12 S4 — presets, TABLED1 generators, two-pass increment resolution
# ---------------------------------------------------------------------------


class TestPresets:
    def test_pullup_matches_load_factor_helper(self):
        preset = logic.MANEUVER_PRESETS[0]
        vars_ = preset.prescribed_vars(2.5, g=32.174)
        assert vars_["URDD3"] == load_factor_to_urdd3(2.5, 32.174)
        assert vars_["PITCH"] == 0.0 and vars_["URDD5"] == 0.0

    def test_roll_and_sideslip(self):
        roll = next(p for p in logic.MANEUVER_PRESETS if p.name == "Steady roll")
        assert roll.prescribed_vars(1.5) == {"ROLL": 1.5, "URDD4": 0.0}
        slip = next(p for p in logic.MANEUVER_PRESETS if p.name == "Steady sideslip")
        assert slip.prescribed_vars(0.05) == {"SIDES": 0.05, "YAW": 0.0}

    def test_missing_preset_labels(self, mloads_bulk):
        pullup = logic.MANEUVER_PRESETS[0]
        assert logic.missing_preset_labels(mloads_bulk, pullup) == []
        roll = next(p for p in logic.MANEUVER_PRESETS if p.name == "Steady roll")
        assert logic.missing_preset_labels(mloads_bulk, roll) == ["ROLL", "URDD4"]


class TestGenerators:
    @staticmethod
    def _check_monotone(pts):
        xs = [x for x, _ in pts]
        assert all(xs[i + 1] > xs[i] for i in range(len(xs) - 1))

    def test_step(self):
        pts = logic.gen_step(0.1, 0.0, 0.5)
        self._check_monotone(pts)
        assert pts[0] == (0.0, 0.0) and pts[-1][1] == 0.5

    def test_ramp(self):
        pts = logic.gen_ramp(0.1, 0.3, 0.0, 0.5)
        self._check_monotone(pts)
        assert pts[-1] == (0.3, 0.5)
        with pytest.raises(ValueError):
            logic.gen_ramp(0.3, 0.1, 0.0, 0.5)

    def test_cosine_ramp_smooth_endpoints(self):
        pts = logic.gen_cosine_ramp(0.0, 1.0, 0.0, 1.0, n=21)
        self._check_monotone(pts)
        assert pts[0] == (0.0, 0.0) and pts[-1][1] == pytest.approx(1.0)
        mid = pts[10]
        assert mid[1] == pytest.approx(0.5)
        # Half-cosine: near-zero slope at both ends (smoother than linear).
        assert (pts[1][1] - pts[0][1]) < (mid[1] - pts[9][1])

    def test_doublet(self):
        pts = logic.gen_doublet(0.1, 0.5, 0.2, 1.0, n=41)
        self._check_monotone(pts)
        ys = [y for _, y in pts]
        assert max(ys) == pytest.approx(1.2, abs=1e-3)
        assert min(ys) == pytest.approx(0.8, abs=1e-3)
        assert ys[-1] == pytest.approx(1.0, abs=1e-9)


@pytest.fixture()
def massset_deck():
    cc, bulk = parse_bdf(SAMPLE_DIR / "ha144a_mloads_massset.bdf")
    return cc, bulk


def _fake_maneuver(elev):
    return SimpleNamespace(steps=[SimpleNamespace(trim_vars={"ELEV": elev})])


class TestResolveIncrementTables:
    def test_resolves_from_maneuver_result(self, massset_deck):
        cc, bulk = massset_deck
        spec = logic.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (0.2, 0.1), (2.0, 0.1)])
        cards, report, errors, resolved = logic.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.491711)})
        assert not errors and len(resolved) == 1 and len(report) == 1
        families = [f for f, _ in cards]
        assert families == ["tabled1", "mldcomd"]
        table = cards[0][1]
        assert table.ys == pytest.approx([0.491711, 0.591711, 0.591711])
        comd = cards[1][1]
        assert comd.sid == bulk.mloads[10].mldcomd     # existing MLDCOMD reused
        assert ("ELEV", table.tid) in comd.commands

    def test_resolves_from_trim_result_matching_massset(self, massset_deck):
        cc, bulk = massset_deck
        ic_trim = bulk.mldtrims[bulk.mloads[10].mldtrim].trim_sid
        fake_trim = SimpleNamespace(trim_sid=ic_trim, massset_sid=10,
                                    trim_vars={"ELEV": 0.5})
        spec = logic.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        cards, report, errors, resolved = logic.resolve_increment_tables(
            bulk, cc, [spec], trim_results={99: fake_trim})
        assert not errors and cards[0][1].ys == pytest.approx([0.5, 0.6])

    def test_no_solve_errors(self, massset_deck):
        cc, bulk = massset_deck
        spec = logic.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        cards, report, errors, resolved = logic.resolve_increment_tables(
            bulk, cc, [spec])
        assert not cards and not resolved
        assert errors and "run the trim/maneuver solve first" in errors[0]

    def test_unknown_mloads_errors(self, massset_deck):
        cc, bulk = massset_deck
        spec = logic.IncrementSpec(mloads_sid=999, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        _, _, errors, _ = logic.resolve_increment_tables(bulk, cc, [spec])
        assert errors == ["MLOADS 999 not found."]

    def test_shared_mloads_across_mass_cases_errors(self, massset_deck):
        cc, bulk = massset_deck
        # Point two subcases with different MASSSETs at the same MLOADS.
        cc.subcases[1].mloads_sid = 10
        spec = logic.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        _, _, errors, _ = logic.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)})
        assert errors and "mass-case specific" in errors[0]

    def test_mloads_without_mldcomd_gets_new_one(self, massset_deck):
        cc, bulk = massset_deck
        from sbeam.model.maneuver import Mloads
        bulk.mloads[10] = Mloads(sid=10, mldtrim=1, mldtime=1,
                                 mldcomd=0, mldprnt=1, method=-1, zeta=0.02)
        spec = logic.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        cards, _, errors, _ = logic.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)})
        assert not errors
        families = [f for f, _ in cards]
        assert families == ["tabled1", "mldcomd", "mloads"]
        new_mloads = cards[2][1]
        assert new_mloads.mldcomd == cards[1][1].sid
