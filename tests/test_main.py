"""Smoke tests for the sbeam CLI entry point (R11, AE10).

main.main() is the only code path with 0% coverage before this file.
Tests cover the full dispatch table: SOL 101, SOL 103, SOL 144 (AE10
end-to-end trim), and the missing-file early exit.
"""

import shutil
import sys
import warnings
from pathlib import Path

import pytest

import sbeam.main as main_mod

BDF_DIR = Path(__file__).parent / "integration" / "bdf"
SAMPLE_DIR = Path(__file__).parent.parent / "sample"


class TestMainCLI:
    def test_sol101_produces_f06(self, tmp_path, monkeypatch):
        """SOL 101 end-to-end: .f06 file is written and non-empty."""
        bdf = tmp_path / "cantilever.bdf"
        shutil.copy(BDF_DIR / "v1_v2_cantilever.bdf", bdf)

        monkeypatch.setattr(sys, "argv", ["sbeam", str(bdf)])
        main_mod.main()

        f06 = bdf.with_suffix(".f06")
        assert f06.exists()
        assert f06.stat().st_size > 0

    def test_sol103_produces_f06(self, tmp_path, monkeypatch):
        """SOL 103 end-to-end: .f06 file is written and non-empty."""
        bdf = tmp_path / "modal.bdf"
        shutil.copy(BDF_DIR / "v5_cantilever_modal.bdf", bdf)

        monkeypatch.setattr(sys, "argv", ["sbeam", str(bdf)])
        main_mod.main()

        f06 = bdf.with_suffix(".f06")
        assert f06.exists()
        assert f06.stat().st_size > 0

    def test_sol144_produces_f06_and_loads(self, tmp_path, monkeypatch):
        """SOL 144 end-to-end (AE10): the HA144A trim deck runs through main.main()
        and writes both a non-empty .f06 and an .aero_loads.bdf FORCE/MOMENT export."""
        bdf = tmp_path / "ha144a.bdf"
        shutil.copy(SAMPLE_DIR / "ha144a_fullspan_sbeam.bdf", bdf)

        monkeypatch.setattr(sys, "argv", ["sbeam", str(bdf)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            main_mod.main()

        f06 = bdf.with_suffix(".f06")
        loads = bdf.with_suffix(".aero_loads.bdf")
        assert f06.exists() and f06.stat().st_size > 0
        assert loads.exists() and loads.stat().st_size > 0

        f06_text = f06.read_text()
        # Both trim subcases written, with the SOL 144-specific blocks.
        assert "SOL 144 STATIC AEROELASTIC RESPONSE" in f06_text
        assert "T R I M   V A R I A B L E S" in f06_text
        assert "S T A B I L I T Y   D E R I V A T I V E S" in f06_text
        assert "A E R O D Y N A M I C   D I V E R G E N C E" in f06_text
        assert f06_text.count("SUBCASE 1") == 1 and "SUBCASE 2" in f06_text

        # Exported loads carry FORCE cards for both subcase SIDs.
        loads_text = loads.read_text()
        assert "FORCE, 1," in loads_text and "FORCE, 2," in loads_text

    def test_missing_bdf_exits(self, tmp_path, monkeypatch):
        """Non-existent BDF path causes sys.exit with 'file not found' in the message."""
        monkeypatch.setattr(sys, "argv", ["sbeam", str(tmp_path / "nope.bdf")])

        with pytest.raises(SystemExit) as exc_info:
            main_mod.main()

        assert "file not found" in str(exc_info.value).lower()
