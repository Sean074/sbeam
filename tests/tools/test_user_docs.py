"""The user documentation's page list, its links and the wheel that carries it (#128).

``sbeam_tools/common/user_docs.py`` is the one owner of the page list.  These gates hold
the repository, the links and a built wheel to it:

- every page of the documented folders is listed, or listed as not shipped;
- every link of every shipped page goes somewhere (a renamed page or heading fails here,
  not in front of a user);
- a wheel built from the tree and installed outside the checkout carries exactly the
  listed pages and figures, and reads them from its own copy.
"""

import ast
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from sbeam_tools.common import user_docs

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The page list
# ---------------------------------------------------------------------------

def test_every_page_of_the_documented_folders_is_listed_or_excluded() -> None:
    on_disk = {p.relative_to(REPO).as_posix()
               for folder in user_docs.DOCUMENTED_FOLDERS
               for p in (REPO / folder).rglob("*.md")}
    listed = set(user_docs.pages(REPO)) | set(user_docs.NOT_SHIPPED)
    assert on_disk - listed == set(), "add the page to SECTIONS or to NOT_SHIPPED"
    assert set(user_docs.NOT_SHIPPED) <= on_disk, "NOT_SHIPPED names a page that is gone"


def test_listed_pages_exist_once_and_figures_are_found() -> None:
    pages = user_docs.pages(REPO)
    assert len(pages) == len(set(pages))
    assert not set(pages) & set(user_docs.NOT_SHIPPED)
    assert all((REPO / page).is_file() for page in pages)
    assert "CHANGELOG.md" in pages
    assert len(user_docs.figures(REPO)) >= 9


def test_verification_records_are_listed_newest_first() -> None:
    records = dict(user_docs.sections(REPO))["Verification records"]
    assert records == sorted(records, reverse=True) and len(records) >= 4


def test_a_checkout_reads_the_pages_from_the_repository() -> None:
    assert user_docs.docs_root() == REPO
    text = user_docs.read_page("docs/10_standard/02_card_reference.md")
    assert user_docs.page_title(text, "x.md").startswith("sbeam")
    with pytest.raises(KeyError, match="not a page"):
        user_docs.read_page("docs/10_standard/08_release_process.md")


def test_the_module_imports_the_standard_library_only() -> None:
    """``setup.py`` loads it by path in a build environment with nothing installed."""
    tree = ast.parse(Path(user_docs.__file__).read_text(encoding="utf-8"))
    imported = {node.module if isinstance(node, ast.ImportFrom) else alias.name
                for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    assert imported <= {"__future__", "posixpath", "re", "dataclasses", "pathlib", "typing"}


# ---------------------------------------------------------------------------
# Headings and links
# ---------------------------------------------------------------------------

def test_anchors_follow_githubs_rule() -> None:
    text = ("# Title\n\n## Mass cases — MASSCASE payload (Step 60)\n\n```\n# not a heading\n```\n"
            "## `TRIM` card\n## `TRIM` card\n")
    assert [a for _, _, a in user_docs.headings(text)] == [
        "title", "mass-cases--masscase-payload-step-60", "trim-card", "trim-card-1"]


def test_link_targets_skip_code() -> None:
    text = ("See [a](one.md) and ![fig](../figures/f.svg \"t\").\n"
            "`[not](code.md)` and [b](two.md#h).\n```\n[not](fenced.md)\n```\n")
    assert user_docs.link_targets(text) == ["one.md", "../figures/f.svg", "two.md#h"]


@pytest.mark.parametrize("target, expected", [
    ("02_card_reference.md#trim",
     user_docs.Link("page", target="docs/10_standard/02_card_reference.md", anchor="trim")),
    ("../20_theory/00_beam_methods.md",
     user_docs.Link("page", target="docs/20_theory/00_beam_methods.md")),
    ("#frames", user_docs.Link("anchor", target="docs/10_standard/09_conventions.md", anchor="frames")),
    ("../figures/section_cut.svg", user_docs.Link("figure", target="docs/figures/section_cut.svg")),
    ("../30_future/00_backlog.md", user_docs.Link(
        "repository", target="docs/30_future/00_backlog.md",
        url="https://github.com/Sean074/sbeam/blob/v1.2.3/docs/30_future/00_backlog.md")),
    ("08_release_process.md#tag", user_docs.Link(
        "repository", target="docs/10_standard/08_release_process.md", anchor="tag",
        url="https://github.com/Sean074/sbeam/blob/v1.2.3/docs/10_standard/08_release_process.md#tag")),
    ("../../sample/", user_docs.Link(
        "repository", target="sample", url="https://github.com/Sean074/sbeam/tree/v1.2.3/sample")),
    ("https://semver.org/", user_docs.Link("external", url="https://semver.org/")),
    ("mailto:someone@example.com", user_docs.Link("external", url="mailto:someone@example.com")),
])
def test_a_link_is_classified_by_where_it_goes(target, expected) -> None:
    link = user_docs.resolve_link("docs/10_standard/09_conventions.md", target, REPO, "1.2.3")
    assert link == expected


def test_every_link_of_every_shipped_page_goes_somewhere() -> None:
    assert user_docs.check_links(REPO) == []


def test_a_dead_link_and_a_dead_heading_are_reported(tmp_path, monkeypatch) -> None:
    (tmp_path / "docs" / "figures").mkdir(parents=True)
    (tmp_path / "docs" / "a.md").write_text(
        "# A\n[ok](b.md#real) [gone](c.md) [bad](b.md#missing) [here](#nowhere) [up](../../x.md)\n",
        encoding="utf-8")
    (tmp_path / "docs" / "b.md").write_text("# B\n## Real\n", encoding="utf-8")
    monkeypatch.setattr(user_docs, "SECTIONS", (("S", ("docs/a.md", "docs/b.md")),))
    problems = user_docs.check_links(tmp_path)
    assert len(problems) == 4
    assert "docs/a.md: link (c.md) names docs/c.md, which does not exist" in problems[0]
    assert "#missing, which docs/b.md does not have" in problems[1]
    assert "#nowhere, which docs/a.md does not have" in problems[2]
    assert "(../../x.md)" in problems[3]


# ---------------------------------------------------------------------------
# The wheel
# ---------------------------------------------------------------------------

_BUILD_INPUTS = ("pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "CHANGELOG.md",
                 "LICENSE", "sbeam", "sbeam_tools", "docs")

_INSTALLED_CHECK = """
import sys
sys.path.insert(0, sys.argv[1])
from sbeam_tools.common import user_docs
root = user_docs.docs_root()
print(root)
for name in user_docs.shipped_files(root):
    print(name)
user_docs.read_page("CHANGELOG.md")
"""


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    """A wheel built from a copy of the tree (the build writes ``build/`` beside its
    input).  pip builds in an isolated environment and fetches setuptools for it."""
    work = tmp_path_factory.mktemp("wheel")
    source = work / "src"
    source.mkdir()
    for name in _BUILD_INPUTS:
        if (REPO / name).is_dir():
            shutil.copytree(REPO / name, source / name,
                            ignore=shutil.ignore_patterns("__pycache__", "_docs"))
        else:
            shutil.copy2(REPO / name, source / name)
    done = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(source), "--no-deps", "-w", str(work / "dist")],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    (built,) = (work / "dist").glob("sbeam-*.whl")
    return built


def test_the_wheel_carries_exactly_the_listed_pages_and_figures(wheel: Path) -> None:
    prefix = f"sbeam_tools/{user_docs.PACKAGED_FOLDER}/"
    with zipfile.ZipFile(wheel) as archive:
        carried = {n[len(prefix):] for n in archive.namelist() if n.startswith(prefix)}
    assert carried == set(user_docs.shipped_files(REPO))


def test_an_installed_wheel_reads_its_own_copy(wheel: Path, tmp_path: Path) -> None:
    """Installed outside the checkout, the package finds the pages inside itself."""
    site = tmp_path / "site"
    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", str(wheel), "--no-deps", "--target", str(site)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    # -I: neither the working directory nor PYTHONPATH can supply the checkout's package
    done = subprocess.run([sys.executable, "-I", "-c", _INSTALLED_CHECK, str(site)],
                          capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    root, *names = done.stdout.split()
    assert Path(root) == (site / "sbeam_tools" / user_docs.PACKAGED_FOLDER).resolve()
    assert names == user_docs.shipped_files(REPO)
