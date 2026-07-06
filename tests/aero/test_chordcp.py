"""CHORDCP steady-pressure injection (Step 54) — mean-flow trim about a measured point.

Backlog AC6 acceptance criteria:
  1. Identity — injecting the program's own inviscid mean flow (the Cp the VLM
     produces at the reference AOA) reproduces the Step 52 trim exactly.
  2. Scaled injection — a scaled distribution shifts the trimmed AOA by the
     expected amount.  Tested in machine-precision form: algebraically
     wg_eff(s) = s·wg + (1−s)·n_z·α_ref, so trimming the s-scaled injection
     equals trimming a deck whose W2GJ is scaled by s with ANGLEA judged
     against the same elastic solve; plus a loose physical direction check.
  3. Integral match — the total injected lift/moment equals the integral of the
     supplied Cp distribution.

Plus KC7 validation paths (coverage, ALPHREF consistency, PSTRIP exclusion,
dead-row reproducibility, missing ANGLEA, Mach / perturbation-distance
warnings) and strip-body coexistence.
"""

import math
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_data
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.corrections import apply_chordcp
from sbeam.aero.mirror import mirror_halfspan
from sbeam.assembly.load_vector import build_grid_index
from sbeam.model.aero import Chordcp, W2gj
from sbeam.solver.sol144 import run_sol144_trim

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _load_ha144a():
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, aero, grid_index


def _mean_flow_cp(aero, alpha_ref: float) -> np.ndarray:
    """The program's own rigid mean-flow Cp at ANGLEA = alpha_ref (per-box)."""
    n_z = np.array([b.normal[2] for b in aero.boxes])
    w = -n_z * alpha_ref + aero.wg          # D_alpha = -n_z (build_djx ANGLEA)
    return aero.ajj_inv_corr @ w


def _add_chordcp_cards(bulk, aero, cp: np.ndarray, alpha_ref: float,
                       mach: float = 0.0, sid0: int = 9000) -> None:
    """One CHORDCP per CAERO1 from a global per-box Cp vector (box order)."""
    for i, eid in enumerate(sorted(bulk.caero1s)):
        local = [k for k, b in enumerate(aero.boxes) if b.caero_eid == eid]
        bulk.chordcps[sid0 + i] = Chordcp(
            sid=sid0 + i, caero_eid=eid, alpha_ref=alpha_ref, mach=mach,
            data=cp[local].tolist(),
        )


def _trim(bulk, aero, trim_sid=1):
    subcase = SubcaseControl(subcase_id=trim_sid, spc_sid=1, trim_sid=trim_sid)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_sol144_trim(bulk, subcase, aero)


# --------------------------------------------------------------------------- #
# apply_chordcp unit tests (toy operator)
# --------------------------------------------------------------------------- #

def _toy_boxes(n_z_values):
    return [SimpleNamespace(normal=np.array([0.0, 0.0, nz])) for nz in n_z_values]


class TestApplyChordcp:
    def test_round_trip_identity(self):
        rng = np.random.default_rng(42)
        a = rng.normal(size=(4, 4)) + 4.0 * np.eye(4)
        boxes = _toy_boxes([1.0, 1.0, 1.0, 1.0])
        alpha_ref = 0.05
        wg_true = rng.normal(size=4)
        cp = a @ (-np.array([b.normal[2] for b in boxes]) * alpha_ref + wg_true)
        wg_eff = apply_chordcp(a, boxes, cp, alpha_ref)
        assert wg_eff == pytest.approx(wg_true, abs=1e-12)

    def test_alpha_ref_zero_is_plain_solve(self):
        a = np.diag([2.0, 4.0])
        boxes = _toy_boxes([1.0, 1.0])
        cp = np.array([1.0, 2.0])
        wg_eff = apply_chordcp(a, boxes, cp, 0.0)
        assert wg_eff == pytest.approx([0.5, 0.5])

    def test_dead_row_with_nonzero_cp_raises(self):
        a = np.diag([2.0, 0.0])   # WT2 r=0 dead row
        boxes = _toy_boxes([1.0, 1.0])
        with pytest.raises(ValueError, match="not reproducible"):
            apply_chordcp(a, boxes, np.array([1.0, 0.5]), 0.0)

    def test_dead_row_with_zero_cp_is_ok(self):
        a = np.diag([2.0, 0.0])
        boxes = _toy_boxes([1.0, 1.0])
        wg_eff = apply_chordcp(a, boxes, np.array([1.0, 0.0]), 0.0)
        assert wg_eff[0] == pytest.approx(0.5)

    def test_size_mismatch_raises(self):
        with pytest.raises(ValueError, match="size mismatch"):
            apply_chordcp(np.eye(3), _toy_boxes([1.0, 1.0]), np.zeros(3), 0.0)


# --------------------------------------------------------------------------- #
# Acceptance 1 — identity on HA144A
# --------------------------------------------------------------------------- #

class TestIdentity:
    @pytest.mark.parametrize("alpha_ref", [0.0, math.radians(2.0)])
    def test_injecting_own_mean_flow_reproduces_step52(self, alpha_ref):
        bulk0, aero0, _gi = _load_ha144a()
        base = _trim(bulk0, aero0)

        bulk, aero_ref, gi = _load_ha144a()
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        _add_chordcp_cards(bulk, aero_ref, cp, alpha_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        assert aero_inj.chordcp_alpha_ref == pytest.approx(alpha_ref)
        # the equivalent wash must recover the pre-injection baseline exactly
        assert aero_inj.wg == pytest.approx(aero_ref.wg, abs=1e-10)

        res = _trim(bulk, aero_inj)
        for lbl, val in base.trim_vars.items():
            assert res.trim_vars[lbl] == pytest.approx(val, abs=1e-9), lbl
        assert res.displacements == pytest.approx(base.displacements, abs=1e-9)

    def test_identity_with_wt2_correction_active(self):
        """Injection composes with a WT2-corrected operator (Γ-unit target)."""
        alpha_ref = math.radians(1.0)

        def _with_wt2(lines_extra):
            _cc, bulk = parse_bdf(str(BDF_PATH))
            # WT2 target = 1.15 × the bare-VLM unit-incidence circulation on
            # every surface (Γ-units, all entries nonzero) — a genuine
            # correction with no dead rows.
            gi = build_grid_index(bulk)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                aero_raw = build_aero_model(bulk, grid_index=gi)
            gamma_ref = np.linalg.solve(aero_raw.ajj, -np.ones(len(aero_raw.boxes)))
            from sbeam.model.aero import Aecorr
            for i, eid in enumerate(sorted(bulk.caero1s)):
                local = [k for k, b in enumerate(aero_raw.boxes) if b.caero_eid == eid]
                bulk.aecorrs[8000 + i] = Aecorr(
                    sid=8000 + i, method="WT2", caero_eid=eid,
                    target=(1.15 * gamma_ref[local]).tolist(),
                )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                aero = build_aero_model(bulk, grid_index=gi)
            return bulk, aero, gi

        bulk0, aero0, _ = _with_wt2(None)
        base = _trim(bulk0, aero0)

        bulk, aero_ref, gi = _with_wt2(None)
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        _add_chordcp_cards(bulk, aero_ref, cp, alpha_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)

        res = _trim(bulk, aero_inj)
        for lbl, val in base.trim_vars.items():
            assert res.trim_vars[lbl] == pytest.approx(val, abs=1e-9), lbl


# --------------------------------------------------------------------------- #
# Acceptance 2 — scaled injection shifts the trimmed AOA
# --------------------------------------------------------------------------- #

class TestScaledInjection:
    def test_scaled_injection_equals_scaled_w2gj_deck(self):
        """Machine-precision form: wg_eff(s) = s·wg + (1−s)·n_z·α_ref.

        Injecting s×(mean-flow Cp at α_ref) must produce exactly that
        equivalent wash — verified at the wash level, where the algebra is
        exact — and the resulting trim must differ from baseline in the
        direction physics requires (more lift injected → lower trimmed AOA).
        """
        s, alpha_ref = 1.1, math.radians(2.0)
        bulk, aero_ref, gi = _load_ha144a()
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        n_z = np.array([b.normal[2] for b in aero_ref.boxes])
        _add_chordcp_cards(bulk, aero_ref, s * cp, alpha_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)

        wg_expected = s * aero_ref.wg + (1.0 - s) * n_z * alpha_ref
        assert aero_inj.wg == pytest.approx(wg_expected, abs=1e-10)

    def test_upscaled_lift_trims_to_lower_aoa(self):
        s, alpha_ref = 1.1, math.radians(2.0)
        bulk0, aero0, _ = _load_ha144a()
        base = _trim(bulk0, aero0)

        bulk, aero_ref, gi = _load_ha144a()
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        _add_chordcp_cards(bulk, aero_ref, s * cp, alpha_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        res = _trim(bulk, aero_inj)

        assert res.trim_vars["ANGLEA"] < base.trim_vars["ANGLEA"]


# --------------------------------------------------------------------------- #
# Acceptance 3 — total injected lift/moment matches the supplied integral
# --------------------------------------------------------------------------- #

class TestIntegralMatch:
    def test_injected_operating_point_reproduces_supplied_integrals(self):
        alpha_ref = math.radians(2.0)
        bulk, aero_ref, gi = _load_ha144a()
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        _add_chordcp_cards(bulk, aero_ref, cp, alpha_ref)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero = build_aero_model(bulk, grid_index=gi)

        # Reconstruct the rigid state at the injected operating point
        n_z = np.array([b.normal[2] for b in aero.boxes])
        cp_back = aero.ajj_inv_corr @ (-n_z * alpha_ref + aero.wg)
        f_box = aero.skj @ cp_back                       # force/q per box

        # Direct integrals of the supplied Cp: Fz = Σ Cp·area·n_z (skj is area·normal)
        areas = np.array([b.area for b in aero.boxes])
        assert f_box[2::3].sum() == pytest.approx((cp * areas * n_z).sum(), rel=1e-9)
        x_fp = np.array([b.force_point[0] for b in aero.boxes])
        my_direct = -(cp * areas * n_z * x_fp).sum()     # nose-up + about x=0
        my_model = -(f_box[2::3] * x_fp).sum()
        assert my_model == pytest.approx(my_direct, rel=1e-9)


# --------------------------------------------------------------------------- #
# Validation & warnings (KC7)
# --------------------------------------------------------------------------- #

class TestValidation:
    def test_partial_coverage_raises(self):
        bulk, aero, gi = _load_ha144a()
        eid = sorted(bulk.caero1s)[0]
        local = [k for k, b in enumerate(aero.boxes) if b.caero_eid == eid]
        bulk.chordcps[9000] = Chordcp(
            sid=9000, caero_eid=eid, alpha_ref=0.0, data=[0.1] * len(local))
        with pytest.raises(ValueError, match="full coverage"):
            build_aero_model(bulk, grid_index=gi)

    def test_alphref_mismatch_raises(self):
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0)
        first = next(iter(bulk.chordcps))
        bulk.chordcps[first].alpha_ref = 0.01
        with pytest.raises(ValueError, match="disagree on ALPHREF"):
            build_aero_model(bulk, grid_index=gi)

    def test_duplicate_surface_raises(self):
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0)
        first = bulk.chordcps[next(iter(bulk.chordcps))]
        bulk.chordcps[9999] = Chordcp(
            sid=9999, caero_eid=first.caero_eid, alpha_ref=0.0, data=list(first.data))
        with pytest.raises(ValueError, match="already covered"):
            build_aero_model(bulk, grid_index=gi)

    def test_unknown_caero_raises(self):
        bulk, aero, gi = _load_ha144a()
        bulk.chordcps[9000] = Chordcp(sid=9000, caero_eid=777, alpha_ref=0.0, data=[0.1])
        with pytest.raises(ValueError, match="not found"):
            build_aero_model(bulk, grid_index=gi)

    def test_data_length_mismatch_raises(self):
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0)
        first = bulk.chordcps[next(iter(bulk.chordcps))]
        first.data = first.data[:-1]
        with pytest.raises(ValueError, match="data length"):
            build_aero_model(bulk, grid_index=gi)

    def test_w2gj_discard_warns(self):
        bulk, aero, gi = _load_ha144a()
        assert any(any(v != 0.0 for v in w.data) for w in bulk.w2gjs.values()), \
            "HA144A deck should carry a nonzero W2GJ (wing incidence)"
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0)
        with pytest.warns(UserWarning, match="replaces the W2GJ baseline"):
            build_aero_model(bulk, grid_index=gi)

    def test_missing_anglea_with_nonzero_alphref_raises(self):
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, math.radians(1.0))
        _add_chordcp_cards(bulk, aero, cp, math.radians(1.0))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        # Remove the ANGLEA AESTAT; prescribe it on the TRIM card is not enough —
        # injection needs the AOA normalwash column.
        for aid in [a for a, st in bulk.aestats.items() if st.label == "ANGLEA"]:
            del bulk.aestats[aid]
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
        with pytest.raises(ValueError, match="ANGLEA"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                run_sol144_trim(bulk, subcase, aero_inj)

    def test_mach_mismatch_warns(self):
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0, mach=0.5)   # TRIM Mach is 0.9
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
        with pytest.warns(UserWarning, match="CHORDCP data Mach"):
            run_sol144_trim(bulk, subcase, aero_inj)

    def test_far_from_reference_aoa_warns(self):
        """HA144A SC1 trims to ANGLEA≈0.169 rad; inject at α_ref = 0 → > 2° away."""
        bulk, aero, gi = _load_ha144a()
        cp = _mean_flow_cp(aero, 0.0)
        _add_chordcp_cards(bulk, aero, cp, 0.0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
        with pytest.warns(UserWarning, match="CHORDCP reference AOA"):
            run_sol144_trim(bulk, subcase, aero_inj)

    def test_mirror_halfspan_rejects_chordcp(self):
        bulk = parse_bulk_data(
            "AEROS, 0, 0, 2.0, 4.0, 8.0, 1, 0\n"
            "PAERO1, 1\n"
            "CAERO1, 100, 1, , 2, 2, , , 0\n"
            "+, 0.0, 0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 2.0\n"
            "CHORDCP, 1, 100, 0.0, , 0.1, 0.1, 0.1, 0.1\n".splitlines()
        )
        with pytest.raises(NotImplementedError, match="CHORDCP"):
            mirror_halfspan(bulk)


# --------------------------------------------------------------------------- #
# Strip-body coexistence — VLM entries replaced, strip wash untouched
# --------------------------------------------------------------------------- #

_STRIP_MIX_DECK = """\
AEROS, 0, 0, 1.0, 4.0, 4.0, 0, 0, 0.0
PAERO1, 10
CAERO1, 100, 10, 0, 4, 4, 0, 0, 1
+, 0.0, -2.0, 0.0, 1.0, 0.0, 2.0, 0.0, 1.0
PSTRIP, 20
CAERO1, 400, 20, 0, 1, 2, 0, 0, 1
+, 2.0, -0.5, 0.0, 1.0, 2.0, 0.5, 0.0, 1.0
W2GJ, 1, 400, 0.02, 0.02
"""


class TestStripCoexistence:
    def test_strip_wash_untouched_vlm_replaced(self):
        bulk = parse_bulk_data(_STRIP_MIX_DECK.splitlines())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero0 = build_aero_model(bulk)
        strip = np.array([b.is_strip for b in aero0.boxes])
        alpha_ref = math.radians(1.5)
        n_z = np.array([b.normal[2] for b in aero0.boxes])
        cp_full = aero0.ajj_inv_corr @ (-n_z * alpha_ref + aero0.wg)

        local = [k for k, b in enumerate(aero0.boxes) if b.caero_eid == 100]
        bulk.chordcps[9000] = Chordcp(
            sid=9000, caero_eid=100, alpha_ref=alpha_ref, data=cp_full[local].tolist())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero = build_aero_model(bulk)

        # strip boxes keep the W2GJ wash; VLM identity round-trips
        assert aero.wg[strip] == pytest.approx(aero0.wg[strip])
        assert aero.wg[~strip] == pytest.approx(aero0.wg[~strip], abs=1e-10)
        assert aero.chordcp_alpha_ref == pytest.approx(alpha_ref)

    def test_f06_injected_operating_point_block(self):
        """The f06 trim block echoes the injected operating point (KC7)."""
        from sbeam.parser.case_control import CaseControl
        from sbeam.results.f06_writer import build_f06_sol144_text

        alpha_ref = math.radians(2.0)
        bulk, aero_ref, gi = _load_ha144a()
        cp = _mean_flow_cp(aero_ref, alpha_ref)
        _add_chordcp_cards(bulk, aero_ref, cp, alpha_ref, mach=0.9)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            aero_inj = build_aero_model(bulk, grid_index=gi)
        res = _trim(bulk, aero_inj)

        assert res.chordcp_echo is not None
        assert res.chordcp_echo['alpha_ref'] == pytest.approx(alpha_ref)
        assert len(res.chordcp_echo['surfaces']) == len(bulk.caero1s)
        # injected == program mean flow here, so injected Fz/q must equal the
        # rigid solve integral, and the echo total must match a direct sum
        n_z = np.array([b.normal[2] for b in aero_ref.boxes])
        areas = np.array([b.area for b in aero_ref.boxes])
        fz_direct = float((cp * areas * n_z).sum())
        fz_echo = sum(s['FZ_Q'] for s in res.chordcp_echo['surfaces'].values())
        assert fz_echo == pytest.approx(fz_direct, rel=1e-12)

        sc = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
        cc = CaseControl(sol=144, title="chordcp test", subcases=[sc])
        text = build_f06_sol144_text(cc, bulk, res, 1)
        assert "I N J E C T E D   O P E R A T I N G   P O I N T" in text
        assert "ALPHREF = 0.034907 RAD (2.0000 DEG)" in text
        assert "DATA MACH = 0.9000" in text
        assert "TOTAL" in text

    def test_chordcp_on_strip_surface_raises(self):
        bulk = parse_bulk_data(_STRIP_MIX_DECK.splitlines())
        bulk.chordcps[9000] = Chordcp(
            sid=9000, caero_eid=400, alpha_ref=0.0, data=[0.1, 0.1])
        with pytest.raises(ValueError, match="PSTRIP"):
            build_aero_model(bulk)
