"""Maneuver case construction: trim recipes, command shapes, the two-pass builder (#114).

These tests moved here from ``tests/viewer`` with the code: the module is a tool a script
can call, and nothing in this file starts the viewer.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.card_writers import write_authored_block
from sbeam.model.maneuver_presets import load_factor_to_urdd3
from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.solver.sol144 import run_sol144_trim
from sbeam_tools.cases import maneuver
from tests.samples import sample_path


@pytest.fixture()
def mloads_bulk():
    _, bulk = parse_bdf(sample_path("ha144a_fullspan_mloads.bdf"))
    return bulk


# ---------------------------------------------------------------------------
# Trim recipes, command shapes, the two-pass builder
# ---------------------------------------------------------------------------


class TestPresets:
    def test_pullup_matches_load_factor_helper(self):
        preset = maneuver.MANEUVER_PRESETS[0]
        vars_ = preset.prescribed_vars(2.5, g=32.174)
        assert vars_["URDD3"] == load_factor_to_urdd3(2.5, 32.174)
        assert vars_["PITCH"] == 0.0 and vars_["URDD5"] == 0.0

    def test_no_regulatory_number_is_a_default(self):
        """The load factor of a case is the caller's input; 1.0 is level flight (#114)."""
        assert maneuver.MANEUVER_PRESETS[0].param_default == 1.0

    def test_roll_and_sideslip(self):
        roll = next(p for p in maneuver.MANEUVER_PRESETS if p.name == "Steady roll")
        assert roll.prescribed_vars(1.5) == {"ROLL": 1.5, "URDD4": 0.0}
        slip = next(p for p in maneuver.MANEUVER_PRESETS if p.name == "Steady sideslip")
        assert slip.prescribed_vars(0.05) == {"SIDES": 0.05, "YAW": 0.0}

    def test_missing_preset_labels(self, mloads_bulk):
        pullup = maneuver.MANEUVER_PRESETS[0]
        assert maneuver.missing_preset_labels(mloads_bulk, pullup) == []
        roll = next(p for p in maneuver.MANEUVER_PRESETS if p.name == "Steady roll")
        assert maneuver.missing_preset_labels(mloads_bulk, roll) == ["ROLL", "URDD4"]


class TestGenerators:
    @staticmethod
    def _check_monotone(pts):
        xs = [x for x, _ in pts]
        assert all(xs[i + 1] > xs[i] for i in range(len(xs) - 1))

    def test_step(self):
        pts = maneuver.gen_step(0.1, 0.0, 0.5)
        self._check_monotone(pts)
        assert pts[0] == (0.0, 0.0) and pts[-1][1] == 0.5

    def test_ramp(self):
        pts = maneuver.gen_ramp(0.1, 0.3, 0.0, 0.5)
        self._check_monotone(pts)
        # the ramp ends at (0.3, 0.5) and a hold point keeps it there (#70)
        assert pts[-2] == (0.3, 0.5) and pts[-1] == (0.6, 0.5)
        with pytest.raises(ValueError):
            maneuver.gen_ramp(0.3, 0.1, 0.0, 0.5)

    def test_cosine_ramp_smooth_endpoints(self):
        pts = maneuver.gen_cosine_ramp(0.0, 1.0, 0.0, 1.0, n=21)
        self._check_monotone(pts)
        assert pts[0] == (0.0, 0.0) and pts[-1][1] == pytest.approx(1.0)
        mid = pts[10]
        assert mid[1] == pytest.approx(0.5)
        # Half-cosine: near-zero slope at both ends (smoother than linear).
        assert (pts[1][1] - pts[0][1]) < (mid[1] - pts[9][1])

    def test_doublet(self):
        pts = maneuver.gen_doublet(0.1, 0.5, 0.2, 1.0, n=41)
        self._check_monotone(pts)
        ys = [y for _, y in pts]
        assert max(ys) == pytest.approx(1.2, abs=1e-3)
        assert min(ys) == pytest.approx(0.8, abs=1e-3)
        assert ys[-1] == pytest.approx(1.0, abs=1e-9)


@pytest.fixture()
def massset_deck():
    cc, bulk = parse_bdf(sample_path("ha144a_mloads_massset.bdf"))
    return cc, bulk


def _fake_maneuver(elev):
    return SimpleNamespace(steps=[SimpleNamespace(trim_vars={"ELEV": elev})])


class TestResolveIncrementTables:
    def test_resolves_from_maneuver_result(self, massset_deck):
        cc, bulk = massset_deck
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (0.2, 0.1), (2.0, 0.1)])
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.491711)})
        assert not res.errors and len(res.resolved) == 1 and len(res.report) == 1
        families = [f for f, _ in res.cards]
        assert families == ["tabled1", "mldcomd"]
        table = res.cards[0][1]
        assert table.ys == pytest.approx([0.491711, 0.591711, 0.591711])
        comd = res.cards[1][1]
        assert comd.sid == bulk.mloads[10].mldcomd     # existing MANCMD reused
        assert ("ELEV", table.tid) in comd.commands

    def test_resolves_from_trim_result_matching_massset(self, massset_deck):
        cc, bulk = massset_deck
        ic_trim = bulk.mldtrims[bulk.mloads[10].mldtrim].trim_sid
        fake_trim = SimpleNamespace(trim_sid=ic_trim, massset_sid=10,
                                    trim_vars={"ELEV": 0.5})
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], trim_results={99: fake_trim})
        assert not res.errors and res.cards[0][1].ys == pytest.approx([0.5, 0.6])

    def test_no_solve_errors(self, massset_deck):
        cc, bulk = massset_deck
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec])
        assert not res.cards and not res.resolved
        assert res.errors and "run the trim/maneuver solve first" in res.errors[0]

    def test_unknown_mloads_errors(self, massset_deck):
        cc, bulk = massset_deck
        spec = maneuver.IncrementSpec(mloads_sid=999, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        res = maneuver.resolve_increment_tables(bulk, cc, [spec])
        assert res.errors == ["MANVR 999 not found."]

    def test_shared_mloads_across_mass_cases_errors(self, massset_deck):
        cc, bulk = massset_deck
        # Point two subcases with different MASSCASEs at the same MANVR.
        cc.subcases[1].mloads_sid = 10
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)})
        assert res.errors and "mass-case specific" in res.errors[0]

    def test_mloads_without_mldcomd_gets_new_one(self, massset_deck):
        cc, bulk = massset_deck
        from sbeam.model.maneuver import Mloads
        bulk.mloads[10] = Mloads(sid=10, mldtrim=1, mldtime=1,
                                 mldcomd=0, mldprnt=1, method=-1, zeta=0.02)
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV",
                                   points=[(0.0, 0.0), (1.0, 0.1)])
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)})
        assert not res.errors
        families = [f for f, _ in res.cards]
        assert families == ["tabled1", "mldcomd", "mloads"]
        new_mloads = res.cards[2][1]
        assert new_mloads.mldcomd == res.cards[1][1].sid


# ---------------------------------------------------------------------------
# Loaded cards are replaced by new ones, not rewritten (#113, #114)
# ---------------------------------------------------------------------------

def _loaded(bulk):
    return {"mldcomd": set(bulk.mldcomds), "mloads": set(bulk.mloads),
            "tabled1": set(bulk.tabled1s)}


class TestLoadedCardsAreNotRewritten:
    SPEC_POINTS = [(0.0, 0.0), (0.2, 0.1), (2.0, 0.1)]

    def test_new_mancmd_and_manvr_and_a_selector(self, massset_deck):
        cc, bulk = massset_deck
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV", points=self.SPEC_POINTS)
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)},
            loaded=_loaded(bulk))
        assert not res.errors
        by_family = {family: card for family, card in res.cards}
        assert list(by_family) == ["tabled1", "mldcomd", "mloads"]
        table, comd, manvr = by_family["tabled1"], by_family["mldcomd"], by_family["mloads"]
        # every card has an ID the loaded deck does not use
        assert table.tid not in bulk.tabled1s
        assert comd.sid not in bulk.mldcomds and manvr.sid not in bulk.mloads
        # the copy is MANVR 10 with the new MANCMD, and nothing else changed
        old = bulk.mloads[10]
        assert manvr.mldcomd == comd.sid and comd.commands == [("ELEV", table.tid)]
        assert (manvr.mldtrim, manvr.mldtime, manvr.mldprnt, manvr.method, manvr.zeta) == (
            old.mldtrim, old.mldtime, old.mldprnt, old.method, old.zeta)
        # the subcase that selected MANVR 10 now selects the copy; the others do not move
        assert res.selectors == {1: manvr.sid}
        assert any("replaces it in subcase(s) [1]" in line for line in res.report)

    def test_a_loaded_mancmd_keeps_its_other_commands(self, massset_deck):
        """The new MANCMD starts from the loaded one's commands, then sets the resolved one."""
        cc, bulk = massset_deck
        bulk.mldcomds[11].commands.append(("ANGLEA", 310))
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV", points=self.SPEC_POINTS)
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)},
            loaded=_loaded(bulk))
        comd = next(card for family, card in res.cards if family == "mldcomd")
        assert dict(comd.commands)["ANGLEA"] == 310
        assert dict(comd.commands)["ELEV"] not in bulk.tabled1s

    def test_without_loaded_the_cards_are_rewritten_in_place(self, massset_deck):
        """Cards authored in the same session keep their IDs, and no selector moves."""
        cc, bulk = massset_deck
        spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV", points=self.SPEC_POINTS)
        res = maneuver.resolve_increment_tables(
            bulk, cc, [spec], maneuver_results={1: _fake_maneuver(0.49)})
        assert [family for family, _ in res.cards] == ["tabled1", "mldcomd"]
        assert res.cards[1][1].sid == bulk.mloads[10].mldcomd and res.selectors == {}


# ---------------------------------------------------------------------------
# The two passes from a script, with no viewer
# ---------------------------------------------------------------------------

def test_two_pass_from_a_script_reproduces_the_hand_written_table():
    """``ha144a_mloads_massset.bdf`` was written by hand in two passes: its TABLED1 310
    starts at the EMPTY mass case's trim elevator and adds a 0.1 rad ramp.  Solving the
    trim and running the builder on the same increments must give that table.  The
    target is the deck's own number, not the builder's output.
    """
    path = sample_path("ha144a_mloads_massset.bdf")
    cc, bulk = parse_bdf(path)
    by_hand = bulk.tabled1s[310]
    increments = [(x, y - by_hand.ys[0]) for x, y in zip(by_hand.xs, by_hand.ys)]
    assert increments[0] == (0.0, 0.0)

    # pass 1: the trim that the maneuver starts from, at the EMPTY mass case
    manvr = bulk.mloads[10]
    ic_trim = bulk.mldtrims[manvr.mldtrim].trim_sid
    trim_case = SubcaseControl(subcase_id=101, trim_sid=ic_trim, massset_sid=10)
    grid_index = build_grid_index(bulk)
    aero = build_aero_model(bulk, grid_index=grid_index)
    trim = run_sol144_trim(bulk, trim_case, aero)
    assert trim.trim_vars["ELEV"] == pytest.approx(by_hand.ys[0], abs=1e-6)

    # pass 2: the builder
    spec = maneuver.IncrementSpec(mloads_sid=10, label="ELEV", points=increments)
    res = maneuver.resolve_increment_tables(
        bulk, cc, [spec], trim_results={101: trim}, loaded=_loaded(bulk))
    assert not res.errors
    table = next(card for family, card in res.cards if family == "tabled1")
    assert table.xs == by_hand.xs
    assert table.ys == pytest.approx(by_hand.ys, abs=1e-6)

    # the result is a deck: the new cards after the loaded ones, the subcase repointed
    new_manvr = res.selectors[1]
    authored: dict[str, set[int]] = {}
    for family, card in res.cards:
        store = {"tabled1": bulk.tabled1s, "mldcomd": bulk.mldcomds, "mloads": bulk.mloads}[family]
        key = card.tid if family == "tabled1" else card.sid
        store[key] = card
        authored.setdefault(family, set()).add(key)
    text = path.read_text().replace("MANVR  = 10", f"MANVR  = {new_manvr}", 1)
    text = text.replace("ENDDATA", write_authored_block(bulk, authored) + "ENDDATA")
    cc2, bulk2 = parse_bdf(path, text=text)
    assert cc2.subcases[0].mloads_sid == new_manvr
    assert [sc.mloads_sid for sc in cc2.subcases[1:]] == [sc.mloads_sid for sc in cc.subcases[1:]]
    commands = dict(bulk2.mldcomds[bulk2.mloads[new_manvr].mldcomd].commands)
    assert bulk2.tabled1s[commands["ELEV"]].ys == pytest.approx(by_hand.ys, abs=1e-6)
    assert 10 in bulk2.mloads and 310 in bulk2.tabled1s      # the loaded cards are untouched


# ---------------------------------------------------------------------------
# Where the code lives (#114)
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(("." * node.level) + node.module)
    return names


def test_case_construction_does_not_import_the_viewer_or_streamlit():
    for path in sorted((REPO / "sbeam_tools" / "cases").glob("*.py")):
        bad = {name for name in _imports(path)
               if name.split(".")[0] in ("streamlit", "plotly")
               or "viewer" in name.split(".")}
        assert not bad, f"{path.name} imports {sorted(bad)}"


def test_the_viewer_does_not_define_what_a_maneuver_case_is():
    """Presets, command shapes and the builder are defined once, in the tools."""
    moved = {"ManeuverPreset", "MANEUVER_PRESETS", "missing_preset_labels", "gen_step",
             "gen_ramp", "gen_cosine_ramp", "gen_doublet", "IncrementSpec",
             "resolve_increment_tables"}
    for name in ("sol144_authoring.py", "sol144_authoring_ui.py"):
        tree = ast.parse((REPO / "sbeam_tools" / "viewer" / name).read_text())
        defined = {node.name for node in tree.body
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        defined |= {target.id for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
                    for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                    if isinstance(target, ast.Name)}
        assert not (defined & moved), f"{name} defines {sorted(defined & moved)}"
    assert moved <= set(dir(maneuver))
