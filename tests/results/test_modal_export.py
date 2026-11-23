"""Reduced modal model export, MODEXP (#100): MHH, KHH, PHIA, PHIX as OP4 + Universal file.

Gates agreed in the #100 design note (2026-11-22):
  G1  Goland, cg = 0, tributary lumping: flap and torsion 49.48 / 87.10 rad/s within 0.5 %
      (closed form, Goland 1945 / Bisplinghoff et al. 1955 §9.3).
  G2  Goland as Flaps builds it (sample/goland_wing_modes.bdf): 7.370 / 14.119 Hz within
      0.5 % (Flaps 2.3.4, flaps_env/docs/demo_results.md).
  G3  Free-free: MHH = I, KHH = diag(ω²) to 1e-8, six rigid modes that are geometric rigid
      motions, PHIX = the g-set rows of the SET grids.
  G4  The OP4 reads back in pyNastran (tests/compat/test_op4_roundtrip.py).
"""
import math
import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.assembly.load_vector import build_grid_index
from sbeam.assembly.rigid_body import build_rigid_vectors_g
from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import CaseControl, SubcaseControl, parse_case_control
from sbeam.results.modal_export import build_modal_model, export_modal_model
from sbeam.solver.sol103 import run_sol103

SAMPLE = Path(__file__).resolve().parents[2] / "sample"


def _quiet(fn, *a, **k):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*a, **k)


def _mode_by_shape(result, component):
    """Index of the first mode whose largest share of Σφ² is in the given DOF component."""
    for j in range(len(result.frequencies_hz)):
        phi = result.mode_shapes[:, j]
        if int(np.argmax([np.sum(phi[c::6] ** 2) for c in range(6)])) == component:
            return j
    raise AssertionError(f"no mode dominated by component {component + 1}")


def _goland_tributary(n=13, length=6.096, mass=217.74, i_tors=52.68):
    """cg = 0, end grids carrying half a bay each — the closed form's distributed beam."""
    w = np.ones(n)
    w[0] = w[-1] = 0.5
    w /= w.sum()
    lines = ["MAT1, 1, 1.0, 1.0, , 0.0", "PBAR, 1, 1, 2.0e5, 3.0e7, 9.773e6, 9.876e5",
             "EIGRL, 1, , , 10", "SPC1, 1, 123456, 1"]
    for k in range(n):
        lines += [f"GRID, {k + 1}, , 0.0, {length * k / (n - 1)!r}, 0.0",
                  f"CONM2, {100 + k}, {k + 1}, , {float(mass * w[k])!r}",
                  f"+, {float(w[k])!r}, 0.0, {float(i_tors * w[k])!r}, 0.0, 0.0, {float(w[k])!r}"]
    lines += [f"CBAR, {k + 1}, 1, {k + 1}, {k + 2}, 1.0, 0.0, 0.0" for k in range(n - 1)]
    return parse_bulk_data(lines)


class TestGoland:
    def test_g1_uncoupled_closed_form(self):
        bulk = _quiet(_goland_tributary)
        r = run_sol103(bulk, SubcaseControl(subcase_id=1, spc_sid=1, method_sid=1))
        m, ei, gj, i_a, length = 217.74 / 6.096, 9.773e6, 9.876e5, 52.68 / 6.096, 6.096
        flap = 1.875104 ** 2 * math.sqrt(ei / (m * length ** 4))           # 49.48 rad/s
        tors = (math.pi / 2) * math.sqrt(gj / (i_a * length ** 2))         # 87.10 rad/s
        w = 2 * math.pi * r.frequencies_hz
        assert w[_mode_by_shape(r, 2)] == pytest.approx(flap, rel=5e-3)
        assert w[_mode_by_shape(r, 4)] == pytest.approx(tors, rel=5e-3)

    def test_g2_flaps_coupled_modes(self):
        cc, bulk = _quiet(parse_bdf, SAMPLE / "goland_wing_modes.bdf")
        r = run_sol103(bulk, cc.subcases[0])
        f = r.frequencies_hz
        assert f[_mode_by_shape(r, 2)] == pytest.approx(7.370, rel=5e-3)
        assert f[_mode_by_shape(r, 4)] == pytest.approx(14.119, rel=5e-3)

    def test_export_writes_three_files(self, tmp_path):
        cc, bulk = _quiet(parse_bdf, SAMPLE / "goland_wing_modes.bdf")
        sc = cc.subcases[0]
        paths = export_modal_model(str(tmp_path / "g"), cc, bulk, sc, run_sol103(bulk, sc))
        assert [Path(p).name for p in paths] == ["g.op4", "g_dofmap.csv", "g.uf"]
        op4 = (tmp_path / "g.op4").read_text().splitlines()
        assert [ln[32:40].strip() for ln in op4 if ln[32:40].strip()
                in ("MHH", "KHH", "PHIA", "PHIX")] == ["MHH", "KHH", "PHIA", "PHIX"]
        uf = (tmp_path / "g.uf").read_text().splitlines()
        assert uf.count("    15") == 1 and uf.count("    82") == 1
        assert uf.count("    55") == len(run_sol103(bulk, sc).frequencies_hz)


class TestFreeFree:
    @pytest.fixture(scope="class")
    def model(self):
        cc, bulk = _quiet(parse_bdf, SAMPLE / "val_free_free_modes.bdf")
        sc = cc.subcases[0]
        sc.modexp_set, sc.sets = 1, {1: [1, 6, 11]}
        r = run_sol103(bulk, sc)
        return cc, bulk, sc, r, _quiet(build_modal_model, cc, bulk, sc, r)

    def test_g3_generalized_matrices(self, model):
        *_, r, mm = model
        assert mm.rigid_replaced
        assert mm.mhh == pytest.approx(np.eye(len(mm.mhh)), abs=1e-8)
        scale = float(np.max(np.abs(mm.khh)))
        assert np.max(np.abs(mm.khh - np.diag(np.diag(mm.khh)))) <= 1e-8 * scale
        elastic = (2 * np.pi * r.frequencies_hz[6:]) ** 2
        assert np.diag(mm.khh)[6:] == pytest.approx(elastic, rel=1e-8)
        assert np.all(np.abs(np.diag(mm.khh)[:6]) <= 1e-8 * scale)   # rigid: no strain

    def test_g3_rigid_modes_are_geometric(self, model):
        _cc, bulk, _sc, _r, mm = model
        r_g = build_rigid_vectors_g(bulk, build_grid_index(bulk), [1, 2, 3, 4, 5, 6],
                                    np.zeros(3))
        # every exported rigid column lies in the span of the six geometric motions
        coef, *_ = np.linalg.lstsq(r_g, mm.phi_g[:, :6], rcond=None)
        assert np.allclose(r_g @ coef, mm.phi_g[:, :6], atol=1e-10)

    def test_g3_phix_is_the_set_rows(self, model):
        _cc, bulk, _sc, _r, mm = model
        gi = build_grid_index(bulk)
        rows = [6 * gi[g] + c for g in (1, 6, 11) for c in range(6)]
        assert np.array_equal(mm.phix, mm.phi_g[rows, :])
        assert mm.x_rows[:2] == [(1, "T1"), (1, "T2")] and len(mm.x_rows) == 18


class TestCaseControl:
    def test_msc_set_example(self):
        """QRG p.625: SET 88 = 5 … 10 THRU 55 EXCEPT 15, 16, 77, 78, 79, 100 THRU 300."""
        cc = parse_case_control(["SOL 103", "SET 88=5, 6, 7, 8, 9, 10 THRU 55 EXCEPT 15, 16, "
                                 "77, 78, 79, 100 THRU 300", "SUBCASE 1", "  METHOD = 1"])
        s = cc.sets[88]
        assert 15 not in s and 16 not in s and {5, 14, 17, 55, 77, 300} <= set(s)
        assert len(s) == 49 + 3 + 201

    def test_modexp_needs_sol_103(self):
        with pytest.raises(ValueError, match="MODEXP needs SOL 103"):
            parse_case_control(["SOL 144", "SET 1 = ALL", "SUBCASE 1", "  TRIM = 1",
                                "  MODEXP = 1"])

    def test_unknown_describer_is_refused(self):
        with pytest.raises(ValueError, match="unknown describer"):
            parse_case_control(["SOL 103", "SET 1 = ALL", "SUBCASE 1", "  MODEXP(OP2) = 1"])

    def test_norm_max_is_refused(self):
        cc, bulk = _quiet(parse_bdf, SAMPLE / "goland_wing_modes.bdf")
        sc = cc.subcases[0]
        bulk.eigrls[1].norm = "MAX"
        r = run_sol103(bulk, sc)
        with pytest.raises(ValueError, match="NORM = MAX"):
            build_modal_model(cc, bulk, sc, r)

    def test_missing_set_is_refused(self):
        cc = CaseControl(sol=103, subcases=[SubcaseControl(subcase_id=1, modexp_set=9)])
        _cc, bulk = _quiet(parse_bdf, SAMPLE / "goland_wing_modes.bdf")
        r = run_sol103(bulk, _cc.subcases[0])
        with pytest.raises(ValueError, match="names no SET 9"):
            build_modal_model(cc, bulk, cc.subcases[0], r)
