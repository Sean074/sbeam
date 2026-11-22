"""Run-to-run reproducibility of the flagship SOL 144 outputs (#49).

The same code run twice on the same deck must write the same f06 and CSV, byte for
byte apart from the run date and time, so a regression diff of the shipped decks shows
only real changes.  #49 saw ~1e-10 noise in the zero-level antisymmetric monitor
components of the gust deck; it does not reproduce on Accelerate or OpenBLAS
(threaded or single-threaded) or across PYTHONHASHSEED values at the closing commit.
This gate runs each deck in two separate processes with different hash seeds, so
thread scheduling and set/dict iteration order both get a chance to differ.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SAMPLE_DIR = Path(__file__).parent.parent.parent / "sample"
DECKS = ["cessna210_flagship_gust.bdf", "cessna210_flagship_mloads.bdf"]
# Run stamps: the f06 DATE line and the date-time on the transient subcase headers
_STAMP = re.compile(r"DATE.*|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def _run(deck: str, workdir: Path, hashseed: str) -> dict[str, list[str]]:
    shutil.copytree(SAMPLE_DIR, workdir)
    env = dict(os.environ, PYTHONHASHSEED=hashseed)
    subprocess.run([sys.executable, "-m", "sbeam.main", deck], cwd=workdir, env=env,
                   check=True, capture_output=True)
    stem = Path(deck).stem
    out = {}
    for path in sorted(workdir.glob(f"{stem}.*")):
        if path.name == deck:
            continue
        lines = path.read_text().splitlines()
        out[path.name] = [_STAMP.sub("", ln) for ln in lines]
    return out


@pytest.mark.parametrize("deck", DECKS)
def test_two_runs_write_identical_outputs(deck, tmp_path):
    first = _run(deck, tmp_path / "a", "1")
    second = _run(deck, tmp_path / "b", "2")
    assert first.keys() == second.keys()
    assert any(name.endswith(".f06") for name in first)
    for name in first:
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(first[name], second[name]))
                if a != b]
        assert len(first[name]) == len(second[name]), name
        assert not diff, f"{name}: {len(diff)} lines differ, first {diff[0]}"
