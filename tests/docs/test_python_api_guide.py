"""`docs/10_standard/11_python_api.md` must stay true (issue #47).

The guide is the only place the public programmatic surface is named, so it is
checked against the code four ways: every ``from sbeam.x import y`` it prints
resolves; every name the CLI (the reference consumer) imports from ``sbeam`` is
named in the guide; every result field it lists exists on the dataclass; and the
two worked examples run.
"""

import ast
import importlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GUIDE = REPO / "docs/10_standard/11_python_api.md"
MAIN = REPO / "sbeam/main.py"

_IMPORT_RE = re.compile(r"from (sbeam[\w.]*) import ([\w, ]+|…)")


def _guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _guide_imports() -> list[tuple[str, str]]:
    """Every (module, name) spelled out as ``from m import n`` in the guide.

    A table row that imports several names writes ``from m import …`` and lists
    the names in its first cell.
    """
    out: set[tuple[str, str]] = set()
    for line in _guide_text().splitlines():
        for mod, names in _IMPORT_RE.findall(line):
            if names == "…":
                names = ", ".join(re.findall(r"`(\w+)`", _cells(line)[0]))
            out.update((mod, n.strip()) for n in names.split(",") if n.strip())
    assert out, "no imports found in the guide"
    return sorted(out)


@pytest.mark.parametrize("mod,name", _guide_imports(), ids=lambda v: v)
def test_every_import_in_the_guide_resolves(mod: str, name: str) -> None:
    module = importlib.import_module(mod)
    assert hasattr(module, name), f"{mod} has no attribute {name!r}; the guide is stale"


def _cli_sbeam_imports() -> set[str]:
    """Names ``sbeam/main.py`` imports from the ``sbeam`` package (top level or local)."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sbeam"):
            names.update(alias.name for alias in node.names)
    assert names
    return names


def test_guide_names_everything_the_cli_uses() -> None:
    """The CLI is the reference consumer: anything it needs is public, so the
    guide must list it."""
    text = _guide_text()
    missing = sorted(n for n in _cli_sbeam_imports() if f"`{n}`" not in text)
    assert not missing, f"CLI imports not named in the guide: {missing}"


def test_result_fields_named_in_the_guide_exist() -> None:
    """§3.4: every lower-case identifier in a 'Key fields' cell is a field of one
    of the result classes named on that row."""
    from sbeam.results import results as R
    table = _guide_text().split("### 3.4 Results")[1].split("### 3.5")[0]
    stop = {"n", "list", "dict", "gid", "eid", "coef", "value", "per", "each", "with",
            "running", "loads", "running", "internal", "resultants", "face", "signs",
            "plane", "key", "fields", "x"}
    checked = 0
    for row in table.splitlines():
        if not row.startswith("| `"):
            continue
        first, second = _cells(row)[:2]
        classes = [c for c in re.findall(r"\b([A-Z]\w+)\b", first + " " + second)
                   if hasattr(R, c) and hasattr(getattr(R, c), "__dataclass_fields__")]
        assert classes, row
        have = set().union(*(set(getattr(R, c).__dataclass_fields__) for c in classes))
        named = set()
        for tok in re.findall(r"`([^`]+)`", second):
            named.update(re.findall(r"(?<![\w.])([a-z][a-z0-9_]*)(?![\w.])", tok))
        unknown = sorted(named - have - stop)
        assert not unknown, f"{classes}: named in the guide but not on the class: {unknown}"
        checked += 1
    assert checked >= 8


def _example(tag: str) -> str:
    for b in re.findall(r"```python\n(.*?)```", _guide_text(), re.S):
        if b.startswith(f"# {tag}"):
            return b
    raise AssertionError(f"no ```python block starting '# {tag}' in the guide")


def test_sol101_example_runs_and_prints_the_quoted_line(capsys, monkeypatch) -> None:
    monkeypatch.chdir(REPO)
    ns: dict = {}
    exec(compile(_example("example_sol101"), str(GUIDE), "exec"), ns)
    out = capsys.readouterr().out
    quoted = re.search(r"```\n(tip T3 = .*?)\n```", _guide_text(), re.S).group(1)
    # Scalars must match the guide to the digit; the numpy vector is compared by
    # value so numpy's print spacing cannot fail the gate.
    assert out.split("reactions")[0].strip() == quoted.split("reactions")[0].strip()
    assert list(ns["result"].reactions[1]) == pytest.approx([0, 0, 1000, 0, -10000, 0])
    assert ns["f06_text"].lstrip().startswith("1")


def test_sol144_example_runs_on_the_flagship_trim_deck(capsys) -> None:
    ns: dict = {"deck_path": str(REPO / "sample/cessna210_flagship_trim.bdf")}
    exec(compile(_example("example_sol144"), str(GUIDE), "exec"), ns)
    assert ns["trim"], "the flagship trim deck should produce at least one trim result"
    assert all(hasattr(r, "trim_vars") for r in ns["trim"].values())
    assert "BASELINE" in capsys.readouterr().out


def test_subcase_by_hand_example_runs() -> None:
    """§5: a SubcaseControl built in code runs against a parsed bulk."""
    from sbeam.parser.bdf_reader import parse_bdf
    from sbeam.parser.case_control import SubcaseControl
    from sbeam.solver.sol101 import run_sol101
    _, bulk = parse_bdf(str(REPO / "sample/simple_beam.bdf"))
    sc = SubcaseControl(subcase_id=99, spc_sid=1, load_sid=10, displacement=True)
    result = run_sol101(bulk, sc)
    assert result.displacements.shape[0] == 6 * len(bulk.grids)
