"""#31 — the exported CSVs and load BDFs are a public interface.

Contract: ``docs/10_standard/10_export_schemas.md``.  These gates hold the exact
header of every CSV ``sbeam/results/load_export.py`` writes, the shared identity
block (``case, [mloads,] massset, mass_case``), the integer ``massset`` sentinel
(``0`` = baseline — one dtype across a baseline run and a MASSSET sweep), and the
fixed-shape ``$ MASSSET=`` comment line of the three load BDFs.
"""

import csv
import re
import types

import numpy as np
import pytest

from sbeam.model.bulk_data import BulkData
from sbeam.model.grid import Grid
from sbeam.results import load_export as le
from sbeam.results.load_export import (
    BASELINE_MASSSET, build_aero_load_cards_text, build_maneuver_load_cards_text,
    build_maneuver_monitor_csv_text, build_maneuver_monitor_envelope_csv_text,
    build_maneuver_section_envelope_csv_text, build_maneuver_section_loads_csv_text,
    massset_comment, write_monitor_csv, write_section_loads_csv,
)
from sbeam.results.maneuver_output import build_maneuver_critical_load_cards_text
from sbeam.results.section_envelope import build_monitor_envelope
from tests.results.test_monitor_output import _sample_monitors
from tests.results.test_monitor_transient_output import _three_sample_result
from tests.results.test_section_cut_output import _maneuver_result, _sample_cut
from tests.results.test_section_envelope import _VALUES, _result as _envelope_result

_IDENTITY_STATIC = ["case", "massset", "mass_case"]
_IDENTITY_MANEUVER = ["case", "mloads", "massset", "mass_case"]
_SECTION_BODY = [
    "name", "label", "comp", "listtype", "cid", "axis", "side", "half_model", "station",
    "x_ref", "y_ref", "z_ref",
    "comp_1", "comp_2", "comp_3", "comp_4", "comp_5", "comp_6",
    "c1", "c2", "c3", "c4", "c5", "c6",
    "Fx", "Fy", "Fz", "Mx", "My", "Mz",
    "c1_aero", "c2_aero", "c3_aero", "c4_aero", "c5_aero", "c6_aero",
    "c1_inertia", "c2_inertia", "c3_inertia", "c4_inertia", "c5_inertia", "c6_inertia",
    "c1_react", "c2_react", "c3_react", "c4_react", "c5_react", "c6_react",
    "n_members", "dc1_ds", "dc2_ds", "dc3_ds", "dc4_ds", "dc5_ds", "dc6_ds",
]
_MONITOR_BODY = [
    "name", "type", "label", "axes", "cid", "x_ref", "y_ref", "z_ref",
    "Fx", "Fy", "Fz", "Mx", "My", "Mz", "Fz_aero", "Fz_inertia", "Fz_react",
    "parity", "whole_airplane",
]
_SPLIT = [f"{s}_{c}" for s in ("aero", "inertia", "elastic", "damping", "react")
          for c in ("Fx", "Fy", "Fz", "Mx", "My", "Mz")]
_ENVELOPE_TAIL = ["comp_index", "comp_name", "max", "max_sample", "max_time",
                  "min", "min_sample", "min_time", "absmax"]

#: The six published headers, spelled out in full.  Editing a writer without
#: editing this table (and the schema guide) is the drift this gate exists for.
EXPECTED_HEADERS = {
    "monitor_loads.csv": _IDENTITY_STATIC + _MONITOR_BODY,
    "section_loads.csv": _IDENTITY_STATIC + _SECTION_BODY,
    "maneuver_section_loads.csv": (
        _IDENTITY_MANEUVER + ["sample", "time", "critical"] + _SECTION_BODY
        + [f"c{i}_elastic" for i in range(1, 7)] + [f"c{i}_damping" for i in range(1, 7)]),
    "maneuver_monitor_loads.csv": (
        _IDENTITY_MANEUVER + ["sample", "time", "critical"] + _MONITOR_BODY
        + ["Fz_elastic", "Fz_damping"] + _SPLIT),
    "maneuver_monitor_envelope.csv": (
        _IDENTITY_MANEUVER + ["name", "type", "label", "axes", "cid", "whole_airplane",
                              "n_samples", "critical_sample"] + _ENVELOPE_TAIL),
    "maneuver_section_envelope.csv": (
        _IDENTITY_MANEUVER + ["name", "label", "comp", "listtype", "cid", "axis", "side",
                              "half_model", "n_samples", "critical_sample", "station"]
        + _ENVELOPE_TAIL),
}
HEADER_CONSTANTS = {
    "monitor_loads.csv": le._MONITOR_CSV_HEADER,
    "section_loads.csv": le._SECTION_LOADS_CSV_HEADER,
    "maneuver_section_loads.csv": le._MANEUVER_SECTION_CSV_HEADER,
    "maneuver_monitor_loads.csv": le._MANEUVER_MONITOR_CSV_HEADER,
    "maneuver_monitor_envelope.csv": le._MANEUVER_MONITOR_ENVELOPE_HEADER,
    "maneuver_section_envelope.csv": le._MANEUVER_SECTION_ENVELOPE_HEADER,
}


def _static_results(massset_sid=None, label="BASELINE"):
    return {7: types.SimpleNamespace(monitor_loads=_sample_monitors(),
                                     section_loads=_sample_cut(),
                                     massset_sid=massset_sid, massset_label=label)}


def _written(tmp_path, name, massset_sid=None, label="BASELINE") -> str:
    """The CSV text each writer produces for a small stub result."""
    if name == "monitor_loads.csv":
        write_monitor_csv(str(tmp_path / name), _static_results(massset_sid, label))
    elif name == "section_loads.csv":
        write_section_loads_csv(str(tmp_path / name), _static_results(massset_sid, label))
    else:
        if name.startswith("maneuver_monitor"):
            res = _three_sample_result()
            res.monitor_envelope = build_monitor_envelope(res)
        elif name == "maneuver_section_loads.csv":
            res = _maneuver_result()
        else:
            res = _envelope_result(_VALUES)
        res.massset_sid, res.massset_label = massset_sid, label
        builder = {
            "maneuver_section_loads.csv": build_maneuver_section_loads_csv_text,
            "maneuver_monitor_loads.csv": build_maneuver_monitor_csv_text,
            "maneuver_monitor_envelope.csv": build_maneuver_monitor_envelope_csv_text,
            "maneuver_section_envelope.csv": build_maneuver_section_envelope_csv_text,
        }[name]
        return builder({res.subcase_id: res})
    return (tmp_path / name).read_text()


@pytest.mark.parametrize("name", sorted(EXPECTED_HEADERS))
class TestHeaders:
    def test_constant_matches_the_published_header(self, name):
        assert HEADER_CONSTANTS[name] == EXPECTED_HEADERS[name]

    def test_written_file_starts_with_it(self, name, tmp_path):
        first = next(csv.reader(_written(tmp_path, name).splitlines()))
        assert first == EXPECTED_HEADERS[name]
        assert len(first) == len(set(first)), "duplicate column names"

    def test_identity_block(self, name):
        hdr = EXPECTED_HEADERS[name]
        assert hdr[0] == "case"
        i = hdr.index("massset")
        assert hdr[i + 1] == "mass_case"
        assert ("mloads" in hdr) == name.startswith("maneuver")

    def test_massset_is_an_integer_in_both_runs(self, name, tmp_path):
        """Baseline writes 0 / BASELINE, a mass case its SID / label; both parse as int."""
        (tmp_path / "s").mkdir()
        base = list(csv.DictReader(_written(tmp_path, name).splitlines()))
        swept = list(csv.DictReader(_written(tmp_path / "s", name, 20, "CRUISE").splitlines()))
        assert base and swept
        assert {r["massset"] for r in base} == {str(BASELINE_MASSSET)}
        assert {r["mass_case"] for r in base} == {"BASELINE"}
        assert {r["massset"] for r in swept} == {"20"}
        assert {r["mass_case"] for r in swept} == {"CRUISE"}
        # Concatenating the two files leaves one integer column — the #5 join key.
        assert all(isinstance(int(r["massset"]), int) for r in base + swept)
        assert "" not in {r["massset"] for r in base + swept}


class TestRowContract:
    def test_reals_are_six_digit_exponent_and_flags_are_ints(self, tmp_path):
        rows = list(csv.DictReader(_written(tmp_path, "section_loads.csv").splitlines()))
        real = re.compile(r"^-?\d\.\d{6}E[+-]\d\d$")
        for r in rows:
            assert real.match(r["Fz"]) and real.match(r["station"])
            assert r["half_model"] in {"0", "1"} and r["case"].isdigit()
        # d*_ds is empty at the first station of a cut, never "nan".
        assert rows[0]["dc1_ds"] == "" and real.match(rows[1]["dc1_ds"])

    def test_samples_are_one_based_and_critical_is_a_flag(self, tmp_path):
        rows = list(csv.DictReader(_written(tmp_path, "maneuver_monitor_loads.csv").splitlines()))
        assert min(int(r["sample"]) for r in rows) == 1
        assert {r["critical"] for r in rows} == {"0", "1"}


class TestLoadBdfComment:
    """The three load BDFs always carry ``$ MASSSET=<int> (<label>)`` (#31)."""

    @staticmethod
    def _bulk():
        b = BulkData()
        b.grids[1] = Grid(gid=1, x=0.0, y=0.0, z=0.0)
        b.grids[2] = Grid(gid=2, x=1.0, y=0.0, z=0.0)
        return b

    def _trim(self, massset_sid=None, label="BASELINE"):
        f = np.zeros(12); f[2] = 100.0; f[8] = -50.0
        return types.SimpleNamespace(
            subcase_id=1, trim_sid=1, q=10.0, mach=0.3, total_cl=0.5,
            grid_loads=f, net_loads=f, massset_sid=massset_sid, massset_label=label,
            massset_mass=250.0)

    def _mloads(self, massset_sid=None, label="BASELINE"):
        step = types.SimpleNamespace(t=0.2, net_loads=np.r_[np.zeros(6), 0, 0, 7.0, 0, 0, 0])
        return types.SimpleNamespace(
            subcase_id=2, mloads_sid=11, trim_sid=1, q=10.0, mach=0.3,
            steps=[step], crit_index=0, massset_sid=massset_sid, massset_label=label)

    def test_massset_comment_shape(self):
        assert massset_comment(None, "BASELINE") == "$ MASSSET=0 (BASELINE)"
        assert massset_comment(20, "CRUISE", 1234.5) == "$ MASSSET=20 (CRUISE)  MASS=1234.5"

    @pytest.mark.parametrize("sid, label, expect", [
        (None, "BASELINE", r"^\$ MASSSET=0 \(BASELINE\)  MASS=250$"),
        (20, "CRUISE", r"^\$ MASSSET=20 \(CRUISE\)  MASS=250$"),
    ])
    def test_trim_bdfs_always_carry_the_line(self, sid, label, expect):
        bulk = self._bulk()
        for builder in (build_aero_load_cards_text, build_maneuver_load_cards_text):
            lines = builder(bulk, self._trim(sid, label), sid=1).splitlines()
            comments = [l for l in lines if l.startswith("$")]
            assert len(comments) == 4 and re.match(expect, comments[3])
            assert lines[4].startswith("FORCE, 1, 1, 0, 1.0,")

    def test_mloads_bdf_carries_the_line(self):
        bulk = self._bulk()
        lines = build_maneuver_critical_load_cards_text(bulk, self._mloads(), sid=2).splitlines()
        assert lines[3] == "$ MASSSET=0 (BASELINE)"
        lines = build_maneuver_critical_load_cards_text(
            bulk, self._mloads(30, "FERRY"), sid=2).splitlines()
        assert lines[3] == "$ MASSSET=30 (FERRY)"
        assert lines[4].startswith("FORCE, 2, 2, 0, 1.0,")


class TestSchemaGuideTracksTheCode:
    def test_every_published_column_is_named_in_the_guide(self):
        from pathlib import Path
        guide = (Path(__file__).resolve().parents[2]
                 / "docs/10_standard/10_export_schemas.md").read_text()
        for name, header in EXPECTED_HEADERS.items():
            assert f"`{name}`" in guide, name
            missing = [c for c in header if f"`{c}`" not in guide]
            assert not missing, f"{name}: columns missing from 10_export_schemas.md: {missing}"
        assert "`$ MASSSET=0 (BASELINE)`" in guide
