"""The user documentation: which pages it holds, where they are, where their links go (#128).

This module is the one owner of the page list.  The build (``setup.py``) copies the listed
pages and figures into the wheel, the viewer shows them, and the tests hold both to the
list.  Nothing under ``docs/`` is moved or duplicated in the repository: the copy exists
only in a built wheel, under ``sbeam_tools/_docs``, at the same relative paths, so the
relative links between pages and figures hold unchanged.

A page is named by its path from the repository root with forward slashes, for example
``docs/10_standard/02_card_reference.md`` or ``CHANGELOG.md``.

Standard library only, and no import of the rest of the package: ``setup.py`` loads this
file by path in a build environment that has nothing else installed.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: The project's repository; a link to a file that is not shipped goes here, at the tag
#: of the installed version.
REPOSITORY_URL = "https://github.com/Sean074/sbeam"

#: Sections in reading order: (title, pages).  A trailing ``*`` names every ``.md`` file
#: of a folder (sorted, newest release first for the verification records), so a new
#: release record needs no edit here.
SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Getting started", (
        "docs/20_theory/03_first_analysis_tutorial.md",
        "docs/20_theory/02_realistic_airplane_sol144.md",
    )),
    ("Guides", (
        "docs/10_standard/00_program_overview.md",
        "docs/10_standard/01_beam_model.md",
        "docs/10_standard/02_card_reference.md",
        "docs/10_standard/03_static_analysis.md",
        "docs/10_standard/04_modal_analysis.md",
        "docs/10_standard/05_aeroelastics.md",
        "docs/10_standard/05a_aero_vlm.md",
        "docs/10_standard/05b_splining.md",
        "docs/10_standard/05c_sol144_maneuver.md",
        "docs/10_standard/06_viewer.md",
        "docs/10_standard/09_conventions.md",
        "docs/10_standard/10_export_schemas.md",
        "docs/10_standard/11_python_api.md",
        "docs/10_standard/12_deviation_register.md",
    )),
    ("Theory", (
        "docs/20_theory/00_beam_methods.md",
        "docs/20_theory/01_aeroelastics_theory.md",
        "docs/20_theory/aeroelastic_derivatives.md",
        "docs/20_theory/studies/a1_spanwise_spacing.md",
        "docs/20_theory/studies/a2_wing_root_interference.md",
    )),
    ("Verification records", ("docs/verification/*",)),
    ("Changes", ("CHANGELOG.md",)),
)

#: Pages of the documented folders that are deliberately not shipped: the two process
#: guides are for people changing the code, not for people using it (decision
#: 2026-11-27, #128).  The backlog, history and review folders are not shipped at all.
NOT_SHIPPED: tuple[str, ...] = (
    "docs/10_standard/07_code_review_process.md",
    "docs/10_standard/08_release_process.md",
)

#: Folders whose every ``.md`` file must be in SECTIONS or in NOT_SHIPPED (a gate).
DOCUMENTED_FOLDERS: tuple[str, ...] = ("docs/10_standard", "docs/20_theory", "docs/verification")

#: Folder of the figures the pages show; every file in it is shipped.
FIGURES_FOLDER = "docs/figures"

#: Folder inside the installed package that holds the copy.
PACKAGED_FOLDER = "_docs"


def _expand(entry: str, root: Path) -> list[str]:
    if not entry.endswith("/*"):
        return [entry]
    folder = entry[:-2]
    names = sorted((p.name for p in (root / folder).glob("*.md")), reverse=True)
    return [f"{folder}/{name}" for name in names]


def sections(root: Path) -> list[tuple[str, list[str]]]:
    """The sections with every folder entry expanded against the files under ``root``."""
    return [(title, [page for entry in entries for page in _expand(entry, root)])
            for title, entries in SECTIONS]


def pages(root: Path) -> list[str]:
    """Every shipped page, in reading order."""
    return [page for _, group in sections(root) for page in group]


def figures(root: Path) -> list[str]:
    """Every shipped figure."""
    return sorted(f"{FIGURES_FOLDER}/{p.name}" for p in (root / FIGURES_FOLDER).iterdir()
                  if p.is_file())


def shipped_files(root: Path) -> list[str]:
    """Every file the wheel carries under ``sbeam_tools/_docs``: pages, then figures."""
    return pages(root) + figures(root)


def docs_root() -> Path:
    """The folder the pages are read from.

    An installed wheel carries them under ``sbeam_tools/_docs``.  A source checkout (and
    an editable install, which runs from one) has no such copy: there the pages are read
    from the repository itself, two levels above the package.
    """
    package = Path(__file__).resolve().parent.parent
    packaged = package / PACKAGED_FOLDER
    if packaged.is_dir():
        return packaged
    checkout = package.parent
    if (checkout / "docs" / "10_standard").is_dir():
        return checkout
    raise FileNotFoundError(
        "The sbeam documentation was not found: this installation has neither "
        f"{packaged} nor a source checkout beside the package. Read it at "
        f"{REPOSITORY_URL}/blob/main/docs/00_INDEX.md")


def read_page(page: str, root: Optional[Path] = None) -> str:
    """The Markdown text of a shipped page."""
    root = docs_root() if root is None else root
    if page not in pages(root):
        raise KeyError(f"{page!r} is not a page of the user documentation")
    return (root / page).read_text(encoding="utf-8")


def page_title(text: str, page: str) -> str:
    """The page's first level-1 heading, or its file name if it has none."""
    for line in _prose_lines(text):
        if line.startswith("# "):
            return line[2:].strip()
    return posixpath.basename(page)


# ---------------------------------------------------------------------------
# Headings and anchors
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _prose_lines(text: str) -> list[str]:
    """The lines of ``text`` outside fenced code blocks (a ``#`` or a link inside a
    code block is not a heading or a link)."""
    out, fence = [], None
    for line in text.splitlines():
        mark = _FENCE.match(line)
        if mark and fence is None:
            fence = mark.group(1)
        elif mark and mark.group(1) == fence:
            fence = None
        elif fence is None:
            out.append(line)
    return out


def anchor_of(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to
    hyphens.  Inline code and emphasis marks are punctuation and drop out."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)       # a link keeps its text
    text = re.sub(r"[^\w\- ]", "", text.lower(), flags=re.UNICODE)
    return text.replace(" ", "-")


def headings(text: str) -> list[tuple[int, str, str]]:
    """Every heading of a page as (level, title, anchor), in order.  A repeated anchor
    takes the suffix ``-1``, ``-2``, … as on GitHub."""
    seen: dict[str, int] = {}
    out = []
    for line in _prose_lines(text):
        found = _HEADING.match(line)
        if not found:
            continue
        base = anchor_of(found.group(2))
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append((len(found.group(1)), found.group(2), base if count == 0 else f"{base}-{count}"))
    return out


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Link:
    """Where a link on a page goes.

    ``kind`` is one of:

    - ``"page"``: another shipped page (``target``), at ``anchor`` if given;
    - ``"anchor"``: a heading of the same page (``target`` is that page);
    - ``"figure"``: a shipped figure (``target``);
    - ``"repository"``: a file or folder of the repository that is not shipped;
      ``url`` is its address on GitHub at the installed version's tag;
    - ``"external"``: any other address, in ``url``.
    """
    kind: str
    target: str = ""
    anchor: str = ""
    url: str = ""


_LINK = re.compile(r"(!?)\[(?:[^\]\[]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")


def link_targets(text: str) -> list[str]:
    """The target of every Markdown link and image on a page, outside code."""
    out = []
    for line in _prose_lines(text):
        out += [m.group(2) for m in _LINK.finditer(_INLINE_CODE.sub("", line))]
    return out


def repository_url(path: str, version: str, is_folder: bool = False) -> str:
    """The GitHub address of a repository path at the tag of ``version``."""
    return f"{REPOSITORY_URL}/{'tree' if is_folder else 'blob'}/v{version}/{path}"


def resolve_link(page: str, target: str, root: Path, version: str) -> Link:
    """Classify one link ``target`` found on ``page``.

    A relative target is read against the page's own folder, as GitHub reads it.  What
    is not shipped is taken to be a file of the repository; whether it exists there is
    checked by ``check_links`` in a source checkout, not at run time.
    """
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", target):
        return Link("external", url=target)
    path, _, anchor = target.partition("#")
    if not path:
        return Link("anchor", target=page, anchor=anchor)
    repo_path = posixpath.normpath(posixpath.join(posixpath.dirname(page), path))
    if repo_path in pages(root):
        return Link("page", target=repo_path, anchor=anchor)
    if repo_path in figures(root):
        return Link("figure", target=repo_path)
    is_folder = path.endswith("/") or "." not in posixpath.basename(repo_path)
    url = repository_url(repo_path, version, is_folder)
    return Link("repository", target=repo_path, anchor=anchor,
                url=url + (f"#{anchor}" if anchor else ""))


def check_links(checkout: Path, version: str = "0.0.0") -> list[str]:
    """Every link of every shipped page that goes nowhere, as messages naming the page
    and the link.  Run against a source checkout: a ``"repository"`` link is checked
    against the files there, and an anchor against the headings of its page."""
    problems = []
    anchors: dict[str, set[str]] = {}

    def anchors_of(page: str) -> set[str]:
        if page not in anchors:
            anchors[page] = {a for _, _, a in headings((checkout / page).read_text(encoding="utf-8"))}
        return anchors[page]

    for page in pages(checkout):
        for target in link_targets((checkout / page).read_text(encoding="utf-8")):
            link = resolve_link(page, target, checkout, version)
            if link.kind == "repository":
                if link.target.startswith("..") or not (checkout / link.target).exists():
                    problems.append(f"{page}: link ({target}) names {link.target}, "
                                    "which does not exist in the repository")
            elif link.kind in ("page", "anchor") and link.anchor:
                if link.anchor not in anchors_of(link.target):
                    problems.append(f"{page}: link ({target}) names the heading "
                                    f"#{link.anchor}, which {link.target} does not have")
    return problems
