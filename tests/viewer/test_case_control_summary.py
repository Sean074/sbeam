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
