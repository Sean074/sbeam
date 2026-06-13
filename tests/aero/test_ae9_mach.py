"""AE9 — Mach is a flight condition (per-TRIM), not a model property.

The VLM AIC depends on Mach (Prandtl–Glauert / Göthert β scaling).  Before AE9
the AIC was built once from ``AEROS.mach`` and ``TRIM.mach`` was silently
ignored, so multiple subsonic subcases at different Mach were impossible and a
supersonic Mach was silently clamped to 0.99.  These tests lock the fix:

  1. an AEROS-vs-TRIM Mach disagreement warns (and the TRIM Mach is used);
  2. two subsonic subcases at different Mach give different β-scaled AICs and
     therefore different trim;
  3. a supersonic Mach is rejected (no silent clamp);
  4. the Mach-keyed AeroCache memoizes, preserving the build-once pattern.
"""

import warnings
from pathlib import Path

import numpy as np
import pytest

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.parser.case_control import SubcaseControl
from sbeam.aero.aero_model import build_aero_model
from sbeam.assembly.load_vector import build_grid_index
from sbeam.solver.sol144 import run_sol144_trim, AeroCache

BDF_PATH = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_sbeam.bdf"


def _load():
    """Fresh parse + grid_index + AeroModel (AEROS Mach) for a single test."""
    _cc, bulk = parse_bdf(str(BDF_PATH))
    grid_index = build_grid_index(bulk)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        aero = build_aero_model(bulk, grid_index=grid_index)
    return bulk, grid_index, aero


def test_aeros_mach_is_subsonic():
    """Sanity: the deck's AEROS Mach is the subsonic value the tests assume."""
    bulk, _gi, aero = _load()
    assert bulk.aeros.mach == pytest.approx(0.9)
    assert aero.mach == pytest.approx(0.9)


def test_trim_mach_mismatch_warns():
    """A TRIM Mach differing from AEROS Mach warns and uses the TRIM Mach."""
    bulk, _gi, aero = _load()
    bulk.trims[1].mach = 0.5  # AEROS is 0.9 — genuine disagreement
    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    with pytest.warns(UserWarning, match="disagrees with AEROS"):
        result = run_sol144_trim(bulk, subcase, aero)
    # The result records the Mach actually used for the AIC (the TRIM Mach).
    assert result.mach == pytest.approx(0.5)


def test_distinct_subsonic_mach_gives_distinct_trim():
    """Two subsonic subcases at different Mach trim to different ANGLEA."""
    bulk, grid_index, aero = _load()
    # Same flight condition except Mach: q held equal so only β scaling differs.
    bulk.trims[1].mach = 0.5
    bulk.trims[2].mach = 0.9
    bulk.trims[2].q = bulk.trims[1].q
    cache = AeroCache(bulk, grid_index, seed=aero)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        r_lo = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1), aero, cache
        )
        r_hi = run_sol144_trim(
            bulk, SubcaseControl(subcase_id=2, spc_sid=1, trim_sid=2), aero, cache
        )

    a_lo = r_lo.trim_vars["ANGLEA"]
    a_hi = r_hi.trim_vars["ANGLEA"]
    assert a_lo != pytest.approx(a_hi, rel=1e-3), (
        f"Mach had no effect on trim: M=0.5 ANGLEA={a_lo:.6f}, M=0.9 ANGLEA={a_hi:.6f}"
    )


def test_supersonic_trim_rejected():
    """A supersonic TRIM Mach raises rather than silently clamping to 0.99.

    M=1.3 is the HA144A third flight condition in ADA370433 Table 3.1.2
    (q=1151 psf, ZONA7) — out of scope for sbeam's steady subsonic VLM, so the
    end-to-end trim path must reject it at the AE9 guard rather than solve it.
    """
    bulk, _gi, aero = _load()
    bulk.trims[1].mach = 1.3
    subcase = SubcaseControl(subcase_id=1, spc_sid=1, trim_sid=1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with pytest.raises(ValueError, match="1.0"):
            run_sol144_trim(bulk, subcase, aero)


def test_supersonic_build_aero_model_rejected():
    """build_aero_model rejects an explicit supersonic Mach override."""
    bulk, grid_index, _aero = _load()
    with pytest.raises(ValueError, match=r"≥ 1.0|>= 1.0"):
        build_aero_model(bulk, grid_index=grid_index, mach=1.3)


def test_cache_memoizes_same_mach():
    """AeroCache returns the same AeroModel object for the same Mach."""
    bulk, grid_index, aero = _load()
    cache = AeroCache(bulk, grid_index, seed=aero)
    # Seeded Mach reuses the prebuilt model (no rebuild).
    assert cache.get(0.9) is aero
    # A new Mach builds once, then is reused.
    m1 = cache.get(0.5)
    m2 = cache.get(0.5)
    assert m1 is m2
    assert m1 is not aero
    assert m1.mach == pytest.approx(0.5)


def test_cache_distinct_mach_distinct_aic():
    """Different Mach keys yield AeroModels with different β-scaled AIC inverses."""
    bulk, grid_index, aero = _load()
    cache = AeroCache(bulk, grid_index, seed=aero)
    a05 = cache.get(0.5)
    a09 = cache.get(0.9)
    assert not np.allclose(a05.ajj_inv_corr, a09.ajj_inv_corr)
