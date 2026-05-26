"""Smoke tests for the sbeam CLI entry point (R11).

main.main() is the only code path with 0% coverage before this file.
Three tests cover the full dispatch table: SOL 101, SOL 103, and the
missing-file early exit.
"""

import shutil
import sys
from pathlib import Path

import pytest

import sbeam.main as main_mod

BDF_DIR = Path(__file__).parent / "integration" / "bdf"


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

    def test_missing_bdf_exits(self, tmp_path, monkeypatch):
        """Non-existent BDF path causes sys.exit with 'file not found' in the message."""
        monkeypatch.setattr(sys, "argv", ["sbeam", str(tmp_path / "nope.bdf")])

        with pytest.raises(SystemExit) as exc_info:
            main_mod.main()

        assert "file not found" in str(exc_info.value).lower()
