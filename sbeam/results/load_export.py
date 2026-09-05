"""Export trimmed SOL 144 grid loads as NASTRAN FORCE/MOMENT bulk-data cards.

For a determined (plain) trim the exported set is the g-set aerodynamic flight
load ``G_disp^T·(q·P_k)`` recovered by ``run_sol144_trim`` (``result.grid_loads``);
by spline force/moment conservation it sums to the total trimmed lift/moment.
The cards are emitted in comma free-field form with a unit scale factor so the
direction components carry the physical load:

    FORCE,  SID, GID, 0, 1.0, Fx, Fy, Fz
    MOMENT, SID, GID, 0, 1.0, Mx, My, Mz

Maneuver-balanced (aero + inertial) net loads (Step 53) are emitted by
``build_maneuver_load_cards_text`` from ``result.net_loads`` — the same card
form, but the set sums to the trimmed lift minus the inertia-relief reaction
(i.e. the constraint reaction for the balanced maneuver).
"""

import csv
import io
from typing import Optional, TextIO, Union

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import (
    ManeuverResult, SectionCutResult, SectionCutStation, Sol144TrimResult,
)
from sbeam.results.section_cuts import component_names, labelled
from sbeam.assembly.load_vector import build_grid_index
from sbeam.parser.bdf_field import fmt_real8
from sbeam.types import FloatArray

# Loads below this magnitude are treated as zero and not emitted.
_TOL = 1e-9


def _fmt(val: float) -> str:
    """Format a load component into an 8-character NASTRAN field.

    Free-field does not exempt a card from the 8-character field width: a
    strict reader truncates ``4.715932E+03`` to ``4.715932``.  These cards are
    the handoff to an external stress code, so they must survive that.
    """
    return fmt_real8(val)


def emit_force_moment_cards(
    loads_g: FloatArray, bulk: BulkData, grid_index: dict[int, int], sid: int
) -> list[str]:
    """Return FORCE/MOMENT card lines for a g-set load vector (one per grid)."""
    lines = []
    for gid in sorted(bulk.grids.keys()):
        base = 6 * grid_index[gid]
        f = loads_g[base:base + 3]
        m = loads_g[base + 3:base + 6]
        if np.any(np.abs(f) > _TOL):
            lines.append(
                f"FORCE, {sid}, {gid}, 0, 1.0, {_fmt(f[0])}, {_fmt(f[1])}, {_fmt(f[2])}"
            )
        if np.any(np.abs(m) > _TOL):
            lines.append(
                f"MOMENT, {sid}, {gid}, 0, 1.0, {_fmt(m[0])}, {_fmt(m[1])}, {_fmt(m[2])}"
            )
    return lines


def build_aero_load_cards_text(
    bulk: BulkData,
    result: Sol144TrimResult,
    sid: Optional[int] = None,
) -> str:
    """Return FORCE/MOMENT bulk-data card text for one trimmed subcase.

    Args:
        bulk:   Parsed BulkData (for the grid ordering / grid_index).
        result: Sol144TrimResult with ``grid_loads`` populated.
        sid:    Load set ID to stamp on the cards; defaults to the subcase id.

    Returns:
        Comma free-field NASTRAN card text (with a leading comment block).

    Raises:
        ValueError if result.grid_loads is None.
    """
    if result.grid_loads is None:
        raise ValueError(
            "build_aero_load_cards_text: result.grid_loads is None — "
            "the trim result carries no exportable flight loads."
        )

    sid = sid if sid is not None else result.subcase_id
    grid_index = build_grid_index(bulk)

    lines = [
        f"$ SOL 144 trimmed aerodynamic flight loads — subcase {result.subcase_id}, SID {sid}",
        f"$ TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  CZ={result.total_cl:.6f}",
        "$ FORCE/MOMENT set sums to the total trimmed lift/moment (plain trim).",
    ]
    if result.massset_sid is not None:
        lines.append(
            f"$ MASSSET={result.massset_sid} ({result.massset_label})  "
            f"MASS={result.massset_mass:g}"
        )
    lines += emit_force_moment_cards(result.grid_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def build_maneuver_load_cards_text(
    bulk: BulkData,
    result: Sol144TrimResult,
    sid: Optional[int] = None,
) -> str:
    """Return FORCE/MOMENT card text for one trimmed subcase's net maneuver load.

    Emits ``result.net_loads`` (aero + inertia-relief, Step 53) — the stress
    deliverable for a balanced maneuver.  Card form is identical to the aero-only
    export; only the load content differs.

    Raises:
        ValueError if result.net_loads is None.
    """
    if result.net_loads is None:
        raise ValueError(
            "build_maneuver_load_cards_text: result.net_loads is None — "
            "the trim result carries no maneuver-balanced loads."
        )

    sid = sid if sid is not None else result.subcase_id
    grid_index = build_grid_index(bulk)

    lines = [
        f"$ SOL 144 balanced maneuver loads (aero + inertia relief) — subcase {result.subcase_id}, SID {sid}",
        f"$ TRIM={result.trim_sid}  Q={result.q:g}  MACH={result.mach:g}  CZ={result.total_cl:.6f}",
        "$ FORCE/MOMENT set is the net (aero + inertial) maneuver load for stress (Step 53).",
    ]
    if result.massset_sid is not None:
        lines.append(
            f"$ MASSSET={result.massset_sid} ({result.massset_label})  "
            f"MASS={result.massset_mass:g}"
        )
    lines += emit_force_moment_cards(result.net_loads, bulk, grid_index, sid)
    return "\n".join(lines) + "\n"


def write_aero_load_cards(
    filepath: str, bulk: BulkData, results: dict[int, Sol144TrimResult]
) -> None:
    """Write FORCE/MOMENT cards for all trimmed subcases to one bulk-data file.

    Args:
        filepath: Output path (a ``*.bdf``-style bulk-data fragment).
        bulk:     Parsed BulkData.
        results:  {subcase_id: Sol144TrimResult}.  One card block per subcase,
                  each stamped with SID = subcase_id.
    """
    blocks = [
        build_aero_load_cards_text(bulk, result, sid=sc_id)
        for sc_id, result in results.items()
    ]
    with open(filepath, "w") as fh:
        fh.write("\n".join(blocks))


_MONITOR_CSV_HEADER = [
    "case", "massset", "mass_case", "name", "type", "label", "axes", "cid",
    "x_ref", "y_ref", "z_ref",
    "Fx", "Fy", "Fz", "Mx", "My", "Mz",
    "Fz_aero", "Fz_inertia", "Fz_react",
    "parity", "whole_airplane",
]


def write_monitor_csv(filepath: str, results: dict[int, Sol144TrimResult]) -> None:
    """Write monitor-point integrated loads for all trim subcases to one CSV (MON4).

    One row per monitor per subcase: metadata, the six totals (cp frame), and the
    diagnostic Fz aero/inertia/reaction breakdown.  Values mirror the f06
    MONITOR POINT INTEGRATED LOADS block exactly.

    Args:
        filepath: Output ``*.monitor_loads.csv`` path.
        results:  {subcase_id: Sol144TrimResult}.
    """
    with open(filepath, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_MONITOR_CSV_HEADER)
        for sc_id, result in results.items():
            if not result.monitor_loads:
                continue
            for name in sorted(result.monitor_loads.keys()):
                ml = result.monitor_loads[name]
                # Mass case (Step 60); getattr keeps the writer usable with the
                # lightweight result stubs the monitor tests build.
                ms_sid = getattr(result, "massset_sid", None)
                writer.writerow([
                    sc_id,
                    ms_sid if ms_sid is not None else "",
                    getattr(result, "massset_label", "BASELINE"),
                    ml.name, ml.mtype, ml.label, ml.axes, ml.cid,
                    f"{ml.ref[0]:.6E}", f"{ml.ref[1]:.6E}", f"{ml.ref[2]:.6E}",
                    *(f"{v:.6E}" for v in ml.totals),
                    # MONPNT1 has no inertia/reaction split — report 0.0 there.
                    f"{(ml.aero[2] if ml.aero is not None else 0.0):.6E}",
                    f"{(ml.inertia[2] if ml.inertia is not None else 0.0):.6E}",
                    f"{(ml.reaction[2] if ml.reaction is not None else 0.0):.6E}",
                    f"{ml.parity:g}", int(ml.whole_airplane),
                ])


# Column block shared by the static and transient section-load CSVs, so the two
# files stay readable by one consumer (Step 68).  The transient writer inserts
# its sample/time identity columns before these and appends the elastic-inertia
# and damping contributions after them.
_SECTION_CUT_COLUMNS = [
    "name", "label", "comp", "listtype",
    "cid", "axis", "side", "half_model", "station",
    "x_ref", "y_ref", "z_ref",
    "comp_1", "comp_2", "comp_3", "comp_4", "comp_5", "comp_6",
    "c1", "c2", "c3", "c4", "c5", "c6",
    "Fx", "Fy", "Fz", "Mx", "My", "Mz",
    "c1_aero", "c2_aero", "c3_aero", "c4_aero", "c5_aero", "c6_aero",
    "c1_inertia", "c2_inertia", "c3_inertia", "c4_inertia", "c5_inertia",
    "c6_inertia",
    "c1_react", "c2_react", "c3_react", "c4_react", "c5_react", "c6_react",
    "n_members",
    "dc1_ds", "dc2_ds", "dc3_ds", "dc4_ds", "dc5_ds", "dc6_ds",
]


def _section_cut_row(sc: "SectionCutResult", st: "SectionCutStation") -> list[Union[str, int]]:
    """The shared per-station cells of a section-cut CSV row."""
    d = st.d_ds
    return [
        sc.name, sc.label, sc.comp, sc.listtype,
        sc.cid, sc.axis, sc.side, int(sc.half_model),
        f"{st.station:.6E}",
        *(f"{v:.6E}" for v in st.ref),
        *component_names(sc.axis),
        *(f"{v:.6E}" for v in labelled(st.totals, sc.comp_map)),
        *(f"{v:.6E}" for v in st.totals),
        *(f"{v:.6E}" for v in labelled(st.aero, sc.comp_map)),
        *(f"{v:.6E}" for v in labelled(st.inertia, sc.comp_map)),
        *(f"{v:.6E}" for v in labelled(st.reaction, sc.comp_map)),
        st.n_members,
        *(("" if d is None else f"{v:.6E}")
          for v in (d if d is not None else range(6))),
    ]


def write_section_loads_csv(filepath: str, results: dict[int, Sol144TrimResult]) -> None:
    """Write MONSECT section-cut running loads for all trim subcases to one CSV.

    One row per cut per station per subcase.  Both the labelled stress
    components (``N``/``V*``/``Mt``/``M*``, whose meaning depends on the station
    axis) and the raw cid-frame ``Fx..Mz`` are written, so a consuming tool never
    has to reconstruct the mapping; ``comp_1..comp_6`` name it explicitly.  The
    per-contribution aero / inertia / reaction split is the section-cut analogue
    of the monitor CSV's ``Fz_*`` diagnostic — the fastest way to find a wrong
    sum.  ``massset`` columns make a payload sweep a single pivot.

    Args:
        filepath: Output ``*.section_loads.csv`` path.
        results:  {subcase_id: Sol144TrimResult}.
    """
    header = ["case", "massset", "mass_case"] + _SECTION_CUT_COLUMNS
    with open(filepath, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for sc_id, result in results.items():
            section_loads = result.section_loads
            if not section_loads:
                continue
            ms_sid = getattr(result, "massset_sid", None)
            for name in sorted(section_loads.keys()):
                sc = section_loads[name]
                for st in sc.stations:
                    writer.writerow([
                        sc_id,
                        ms_sid if ms_sid is not None else "",
                        getattr(result, "massset_label", "BASELINE"),
                        *_section_cut_row(sc, st),
                    ])


def write_maneuver_section_loads_csv(
    filepath: str, results: dict[int, "ManeuverResult"]
) -> None:
    """Write MONSECT running loads for every sample of every maneuver subcase.

    One row per cut per station per **sample**.  The static
    ``section_loads.csv`` schema is carried verbatim (same column names, same
    order) with four identity columns inserted up front — ``mloads``, ``sample``
    (1-based, matching the f06 SAMPLE column, DEF-M5), ``time`` and ``critical``
    — and the two Step 68 contributions appended.  A tool that reads the static
    file reads this one; a pivot on ``station`` × ``time`` is the running-load
    time history, and a groupby on ``case``/``massset`` is the sweep envelope.

    Written as its own file rather than merged into ``section_loads.csv``: the
    row cardinality differs by orders of magnitude, and a static table sitting
    in a mostly-empty ``time`` column serves neither consumer.

    Args:
        filepath: Output ``*.maneuver_section_loads.csv`` path.
        results:  {subcase_id: ManeuverResult}.
    """
    with open(filepath, "w", newline="") as fh:
        _write_maneuver_section_loads(fh, results)


def build_maneuver_section_loads_csv_text(
    results: dict[int, "ManeuverResult"]
) -> str:
    """The same CSV as :func:`write_maneuver_section_loads_csv`, as a string.

    The viewer offers this as a download button; sharing the writer keeps the
    downloaded file byte-identical to the one the CLI run produces.
    """
    buf = io.StringIO()
    _write_maneuver_section_loads(buf, results)
    return buf.getvalue()


def _write_maneuver_section_loads(fh: TextIO, results: dict[int, "ManeuverResult"]) -> None:
    header = (["case", "mloads", "massset", "sample", "time", "critical"]
              + _SECTION_CUT_COLUMNS
              + [f"c{i}_elastic" for i in range(1, 7)]
              + [f"c{i}_damping" for i in range(1, 7)])
    writer = csv.writer(fh)
    writer.writerow(header)
    for sc_id, result in results.items():
        ms_sid = result.massset_sid
        for i, step in enumerate(result.steps):
            if not step.section_loads:
                continue
            for name in sorted(step.section_loads.keys()):
                sc = step.section_loads[name]
                for st in sc.stations:
                    el = (st.elastic_inertia if st.elastic_inertia is not None
                          else np.zeros(6))
                    da = st.damping if st.damping is not None else np.zeros(6)
                    writer.writerow([
                        sc_id, result.mloads_sid,
                        ms_sid if ms_sid is not None else "",
                        i + 1, f"{step.t:.6E}",
                        int(i == result.crit_index),
                        *_section_cut_row(sc, st),
                        *(f"{v:.6E}" for v in labelled(el, sc.comp_map)),
                        *(f"{v:.6E}" for v in labelled(da, sc.comp_map)),
                    ])


def write_maneuver_section_envelope_csv(
    filepath: str, results: dict[int, "ManeuverResult"]
) -> None:
    """Write the per-station section-cut envelope for all maneuver subcases.

    One row per cut per station per labelled component: the max and min over the
    run's samples with the sample and time that drove each, plus ``absmax`` (the
    sizing number).  ``max_sample``/``min_sample`` are the **driving** samples,
    which need not be the run's ``critical`` sample — the latter is carried as
    its own column so a consumer can see when they differ.

    Args:
        filepath: Output ``*.maneuver_section_envelope.csv`` path.
        results:  {subcase_id: ManeuverResult}.
    """
    with open(filepath, "w", newline="") as fh:
        _write_maneuver_section_envelope(fh, results)


def build_maneuver_section_envelope_csv_text(
    results: dict[int, "ManeuverResult"]
) -> str:
    """The envelope CSV as a string, for the viewer download button."""
    buf = io.StringIO()
    _write_maneuver_section_envelope(buf, results)
    return buf.getvalue()


def _write_maneuver_section_envelope(fh: TextIO, results: dict[int, "ManeuverResult"]) -> None:
    header = [
        "case", "mloads", "massset", "name", "label", "comp", "listtype",
        "cid", "axis", "side", "half_model", "n_samples", "critical_sample",
        "station", "comp_index", "comp_name",
        "max", "max_sample", "max_time",
        "min", "min_sample", "min_time", "absmax",
    ]
    writer = csv.writer(fh)
    writer.writerow(header)
    for sc_id, result in results.items():
        if not result.section_envelope:
            continue
        ms_sid = result.massset_sid
        for name in sorted(result.section_envelope.keys()):
            env = result.section_envelope[name]
            names = component_names(env.axis)
            for e in env.entries:
                writer.writerow([
                    sc_id, result.mloads_sid,
                    ms_sid if ms_sid is not None else "",
                    env.name, env.label, env.comp, env.listtype,
                    env.cid, env.axis, env.side, int(env.half_model),
                    env.n_samples, result.crit_index + 1,
                    f"{e.station:.6E}", e.comp + 1, names[e.comp],
                    f"{e.max_value:.6E}", e.max_sample, f"{e.max_time:.6E}",
                    f"{e.min_value:.6E}", e.min_sample, f"{e.min_time:.6E}",
                    f"{e.absmax:.6E}",
                ])


def write_maneuver_load_cards(
    filepath: str, bulk: BulkData, results: dict[int, Sol144TrimResult]
) -> None:
    """Write net maneuver-balanced FORCE/MOMENT cards for all subcases (Step 53).

    Args:
        filepath: Output path (a ``*.maneuver_loads.bdf`` bulk-data fragment).
        bulk:     Parsed BulkData.
        results:  {subcase_id: Sol144TrimResult}.  One block per subcase, SID =
                  subcase_id.
    """
    blocks = [
        build_maneuver_load_cards_text(bulk, result, sid=sc_id)
        for sc_id, result in results.items()
    ]
    with open(filepath, "w") as fh:
        fh.write("\n".join(blocks))
