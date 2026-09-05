"""Unit tests for the SOL-aware case-control summary (Step 57)."""
from __future__ import annotations

from sbeam.viewer.case_control_ui import summarize_case_control


def test_summary_sol101(cantilever_sol101_parsed):
    cc, bulk = cantilever_sol101_parsed
    lines = summarize_case_control(cc, bulk)
    assert len(lines) == len(cc.subcases)
    assert any("Static" in ln for ln in lines)


def test_summary_sol103(cantilever_sol103_parsed):
    cc, bulk = cantilever_sol103_parsed
    lines = summarize_case_control(cc, bulk)
    assert any("Modal" in ln for ln in lines)


def test_summary_sol144_trim(dihedral_sol144_parsed):
    cc, bulk = dihedral_sol144_parsed
    lines = summarize_case_control(cc, bulk)
    assert any("Aeroelastic" in ln and "TRIM" in ln for ln in lines)
    # dynamic pressure pulled from the TRIM card
    trim = bulk.trims[cc.subcases[0].trim_sid]
    assert any(f"q={trim.q:g}" in ln for ln in lines)


def test_summary_sol144_advertises_hinge_and_monitor_outputs():
    """AC5: trim summary lists hinge moments (AESURF) and monitor loads (MONPNT)."""
    import warnings
    from pathlib import Path
    from sbeam.parser.bdf_reader import parse_bdf

    sample = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_mloads.bdf"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(sample)
    lines = summarize_case_control(cc, bulk)
    trim_line = next(ln for ln in lines if "TRIM" in ln)
    assert "hinge moments" in trim_line
    assert "monitor loads" in trim_line
    assert "aero totals" in trim_line


def test_summary_sol144_maneuver_advertises_exports():
    """AC5: MLOADS summary lists the time-history and critical-load exports."""
    import warnings
    from pathlib import Path
    from sbeam.parser.bdf_reader import parse_bdf

    sample = Path(__file__).parent.parent.parent / "sample" / "ha144a_fullspan_mloads.bdf"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cc, bulk = parse_bdf(sample)
    lines = summarize_case_control(cc, bulk)
    man_line = next(ln for ln in lines if "MLOADS" in ln)
    assert "MLDPRNT" in man_line
    assert "critical-sample loads" in man_line
