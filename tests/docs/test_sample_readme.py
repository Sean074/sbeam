"""``sample/README.md`` names every shipped sample file, in the folder that holds it (#108).

The README is the map of ``sample/``.  A deck added without a line there, or a line left
behind after a deck is moved or removed, fails here.
"""
from __future__ import annotations

import re

from tests.samples import SAMPLE_ROOT

README = SAMPLE_ROOT / "README.md"


def _sections() -> dict[str, set[str]]:
    """``{folder: {file names in that folder's tables}}`` as the README states them."""
    out: dict[str, set[str]] = {}
    folder = None
    for line in README.read_text().splitlines():
        heading = re.match(r"## `(\w+)/`", line)
        if heading:
            folder = heading.group(1)
            out[folder] = set()
        elif line.startswith("## "):
            folder = None
        elif folder and (row := re.match(r"\| `([^`]+)` \|", line)):
            out[folder].add(row.group(1))
    return out


def _on_disk() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in SAMPLE_ROOT.rglob("*"):
        if path.is_file() and path.suffix in (".bdf", ".dat", ".csv"):
            out.setdefault(path.parent.relative_to(SAMPLE_ROOT).as_posix(), set()).add(path.name)
    return out


def test_readme_lists_exactly_the_shipped_sample_files():
    disk = _on_disk()
    assert "." not in disk, f"sample files outside a family folder: {sorted(disk['.'])}"
    assert _sections() == disk


def test_every_family_folder_is_in_the_folder_table():
    linked = set(re.findall(r"^\| \[`(\w+)/`\]", README.read_text(), flags=re.M))
    assert linked == set(_on_disk())
