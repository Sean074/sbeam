"""`docs/20_theory/03_first_analysis_tutorial.md` must keep running as written (#46).

The deck and the plotting script are lifted out of the page, run, and the
numbers the page quotes are asserted against the f06 and the API. Every
relative link on the page must resolve. Round-off cells (the 1e-11 moment at
the free end, negative zeros) are deliberately not asserted (#49).
"""

import math
import re
import sys
from pathlib import Path

import pytest

import sbeam.main as main_mod

REPO = Path(__file__).parent.parent.parent
DOC = REPO / "docs/20_theory/03_first_analysis_tutorial.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _block(first_line_prefix: str) -> str:
    for body in re.findall(r"```\w*\n(.*?)```", _text(), re.S):
        if body.startswith(first_line_prefix):
            return body
    raise AssertionError(f"no fenced block starting {first_line_prefix!r} in the tutorial")


@pytest.fixture(scope="module")
def run(tmp_path_factory, ):
    """Write the tutorial deck exactly as printed and run the CLI on it."""
    folder = tmp_path_factory.mktemp("tutorial")
    deck = folder / "cantilever.bdf"
    deck.write_text(_block("$ cantilever.bdf"), encoding="utf-8")
    argv = sys.argv
    sys.argv = ["sbeam", str(deck)]
    try:
        main_mod.main()
    finally:
        sys.argv = argv
    f06 = deck.with_suffix(".f06").read_text()
    return folder, deck, f06


def test_f06_has_the_four_requested_blocks_in_order(run) -> None:
    _, _, f06 = run
    heads = ["D I S P L A C E M E N T   V E C T O R",
             "F O R C E S   O F   S I N G L E - P O I N T   C O N S T R A I N T",
             "F O R C E S   I N   B A R   E L E M E N T S",
             "S T R E S S E S   I N   B A R   E L E M E N T S"]
    pos = [f06.index(h) for h in heads]
    assert pos == sorted(pos)


def test_quoted_tip_deflection_reaction_and_root_stress(run) -> None:
    """The three §2 hand checks, as the §4 blocks print them."""
    _, _, f06 = run
    grid6 = next(line for line in f06.splitlines() if re.match(r"\s+6\s+G\s", line))
    assert "-2.000080E-03" in grid6 and "3.000120E-04" in grid6          # δ = PL³/3EI, θ = PL²/2EI
    spc = f06.split("S I N G L E - P O I N T")[1].splitlines()[3]
    assert " 1.000000E+03" in spc and "-1.000000E+04" in spc              # reactions
    bar1 = f06.split("( C B A R )")[1].splitlines()[4]
    assert bar1.split()[0] == "1" and "-1.000000E+04" in bar1 and "-1.000000E+03" in bar1
    stress1 = f06.split("( C B A R )")[2].splitlines()[4]
    vals = re.findall(r"-?\d\.\d{6}E[+-]\d\d", stress1)
    assert vals[:4] == ["1.897396E+06", "1.897396E+06", "-1.897396E+06", "-1.897396E+06"]   # C, D tension; E, F compression


def test_hand_values_against_closed_form() -> None:
    """The page's table: δ, M and σ with the page's E, I, c, P, L."""
    P, L, E, I, c = 1000.0, 10.0, 2.0e11, 8.333e-4, 0.15811
    assert P * L**3 / (3 * E * I) == pytest.approx(2.00008e-3, rel=1e-5)
    assert P * L == 1.0e4
    assert P * L * c / I == pytest.approx(1.8974e6, rel=1e-4)


def test_plot_script_runs_without_matplotlib_and_prints_quoted_lines(run, capsys, monkeypatch) -> None:
    folder, _, _ = run
    script = _block("# plot_cantilever.py")
    numeric = script.split("import matplotlib")[0]      # the plot itself needs an optional dep
    assert "parse_bdf" in numeric and "run_sol101" in numeric
    monkeypatch.chdir(folder)
    ns: dict = {}
    exec(compile(numeric, str(DOC), "exec"), ns)
    out = capsys.readouterr().out
    assert "tip deflection  solver -2.000080e-03  theory -2.000080e-03" in out
    assert list(ns["result"].reactions[1]) == pytest.approx([0, 0, 1000, 0, -10000, 0])
    assert ns["w"] == pytest.approx(
        [-P * x**2 * (3 * 10 - x) / (6 * 2e11 * 8.333e-4) for P in [1000.0] for x in ns["x"]])


def test_plot_script_compiles_in_full() -> None:
    compile(_block("# plot_cantilever.py"), str(DOC), "exec")


def test_modal_variant_frequency_quoted_in_where_next(run) -> None:
    """§6: SOL 103 with EIGRL ND=5 — first frequency as quoted, and the closed form."""
    from sbeam.parser.bdf_reader import parse_bdf
    from sbeam.solver.sol103 import run_sol103
    folder, deck, _ = run
    modal = (deck.read_text().replace("SOL 101", "SOL 103")
             .replace("  LOAD  = 10\n", "  METHOD = 1\n")
             .replace("ENDDATA", "EIGRL, 1, , , 5\nENDDATA"))
    mdeck = folder / "cantilever_modes.bdf"
    mdeck.write_text(modal)
    cc, bulk = parse_bdf(str(mdeck))
    res = run_sol103(bulk, cc.subcases[0])
    quoted = float(re.search(r"The first should be ([0-9.]+) Hz", _text()).group(1))
    assert res.frequencies_hz[0] == pytest.approx(quoted, abs=5e-4)
    assert res.frequencies_hz[1] == pytest.approx(res.frequencies_hz[0])     # square section: Y and Z pair
    EI, rho, A, L = 2e11 * 8.333e-4, 7850.0, 0.1, 10.0
    f1 = 1.875104**2 / (2 * math.pi) * math.sqrt(EI / (rho * A * L**4))
    assert res.frequencies_hz[0] == pytest.approx(f1, rel=1e-3)


def test_every_relative_link_resolves() -> None:
    links = re.findall(r"`((?:\.\./)?[0-9A-Za-z_/]+\.md)`", _text())
    assert links
    for link in links:
        assert (DOC.parent / link).exists(), f"dangling link in the tutorial: {link}"


def test_readme_links_the_tutorial_above_the_documentation_section() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/20_theory/03_first_analysis_tutorial.md" in readme
    assert readme.index("03_first_analysis_tutorial.md") < readme.index("## Documentation")
