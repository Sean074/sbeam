"""Case Control UI for sbeam viewer."""

from __future__ import annotations

import dataclasses
import re

from typing import Any, Callable, Dict, Optional, cast

import streamlit as st
from sbeam_tools.viewer.widget_keys import wk
from streamlit.delta_generator import DeltaGenerator

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl
from sbeam_tools.viewer.sol144_authoring import cards_text, check_case_control


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOL_LABELS: dict[int, str] = {
    101: "101 — Static",
    103: "103 — Normal Modes",
    144: "144 — Static Aeroelastic / Maneuver",
    # Phase 2: 108, 109, 111, 112 added here
}

# Output request fields rendered per SOL.  SOLs absent from this dict show no
# checkboxes (e.g. SOL 103 always outputs all modes automatically).
_SOL_OUTPUT_FIELDS: dict[int, list[str]] = {
    101: ["displacement", "spcforce", "oload", "force", "stress"],
    144: ["displacement", "spcforce", "oload", "force", "stress", "aerof", "apres"],
}

_OUTPUT_LABELS: dict[str, str] = {
    "displacement": "DISPLACEMENT",
    "spcforce":     "SPCFORCE",
    "oload":        "OLOAD",
    "force":        "FORCE",
    "stress":       "STRESS",
    "aerof":        "AEROF",
    "apres":        "APRES",
}

# SOL 144 subcase driver kinds — each subcase selects exactly one, matching the
# solver routing (MANVR wins; DIVERG without TRIM = divergence-only; else TRIM,
# with DIVERG as an optional add-on sweep).
_SC_KIND_TRIM   = "Trim"
_SC_KIND_DIVERG = "Divergence only"
_SC_KIND_MLOADS = "Maneuver (MANVR)"
_SC_KINDS = [_SC_KIND_TRIM, _SC_KIND_DIVERG, _SC_KIND_MLOADS]


def _subcase_kind(sc_data: dict[str, Any]) -> str:
    """Infer the SOL 144 driver kind from a subcase's populated SID fields."""
    if sc_data.get("mloads_sid") is not None:
        return _SC_KIND_MLOADS
    if sc_data.get("diverg_sid") is not None and sc_data.get("trim_sid") is None:
        return _SC_KIND_DIVERG
    return _SC_KIND_TRIM


# ---------------------------------------------------------------------------
# BDF export
# ---------------------------------------------------------------------------


def _set_line(n: int, members: Optional[list[int]]) -> str:
    """A case-control SET (QRG p.625), wrapped so no line grows past 72 characters."""
    if members is None:
        return f"SET {n} = ALL"
    items = [str(m) for m in members]
    rows, row = [], f"SET {n} ="
    for k, item in enumerate(items):
        piece = f" {item}" + ("," if k < len(items) - 1 else "")
        if len(row) + len(piece) > 72:
            rows.append(row)
            row = "   "
        row += piece
    rows.append(row)
    return "\n".join(rows)

def deck_bulk_section(source_text: Optional[str]) -> Optional[str]:
    """The loaded deck's own bulk section: the lines between BEGIN BULK and ENDDATA.

    ``None`` when the text has no BEGIN BULK (a bulk-data-only file, or no file).  The
    section is returned as written, INCLUDE lines and comments included, so an export
    that carries it loses no card of the loaded deck (#123).
    """
    if not source_text:
        return None
    lines = source_text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        clean = line.split("$", 1)[0].strip().upper()
        if start is None:
            if re.match(r"BEGIN\b", clean):
                start = i + 1
        elif clean.startswith("ENDDATA"):
            end = i
            break
    if start is None:
        return None
    return "\n".join(lines[start:end])


def export_bdf_text(
    cc: CaseControl,
    include_paths: Optional[list[str]] = None,
    authored_block: str = "",
    bulk_section: Optional[str] = None,
) -> str:
    """Return a BDF driver file as a string, parseable by parse_bdf.

    Layout: executive/case control, BEGIN BULK, one INCLUDE per bulk file (an
    INCLUDE inserts its file where it stands, so bulk INCLUDEs sit below BEGIN
    BULK, #81), then any authored bulk cards, then ENDDATA.

    Args:
        cc:             Case control to serialize (all SOL 144 keywords included).
        include_paths:  Bulk-data file paths; defaults to ``cc.includes`` (or
                        ``['model.dat']`` when the deck names none).
        authored_block: Optional bulk-card text emitted inline after BEGIN BULK
                        (the viewer-authored TRIM/MANVR/… card block).
        bulk_section:   The loaded deck's own bulk section (``deck_bulk_section``).
                        When given it is written unchanged in place of the generated
                        INCLUDE lines, so inline cards and the deck's own INCLUDEs
                        survive; ``include_paths`` is then not used.
    """
    if bulk_section is not None:
        include_paths = []
    elif include_paths is None:
        if cc.includes:
            include_paths = list(cc.includes)
        elif cc.include:
            include_paths = [cc.include]
        else:
            include_paths = ["model.dat"]
    lines: list[str] = []
    lines.append(f"SOL {cc.sol}")
    for command in ("TITLE", "SUBTITLE", "LABEL"):          # page headings (#90)
        if getattr(cc, command.lower()):
            lines.append(f"{command} = {getattr(cc, command.lower())}")
    lines += [_set_line(n, members) for n, members in getattr(cc, "sets", {}).items()]
    for sc in cc.subcases:
        lines.append(f"SUBCASE {sc.subcase_id}")
        for command in ("TITLE", "SUBTITLE", "LABEL"):
            if getattr(sc, command.lower()):
                lines.append(f"  {command} = {getattr(sc, command.lower())}")
        lines += [f"  {_set_line(n, members)}" for n, members in sc.sets.items()]
        if sc.modexp_set is not None:                       # #100
            lines.append(f"  MODEXP({','.join(sc.modexp_formats)}) = {sc.modexp_set}")
        for sid, keyword in [
            (sc.load_sid, "LOAD"), (sc.spc_sid, "SPC"), (sc.method_sid, "METHOD"),
            (sc.trim_sid, "TRIM"), (sc.trimobj_sid, "TRIMWGT"),
            (sc.diverg_sid, "DIVERG"), (sc.mloads_sid, "MANVR"),
            (sc.gustlf_sid, "GUSTLF"), (sc.massset_sid, sc.mass_card),
        ]:
            if sid is not None:
                lines.append(f"  {keyword} = {sid}")
        for flag, keyword in [
            (sc.displacement, "DISPLACEMENT"), (sc.spcforce, "SPCFORCE"),
            (sc.oload, "OLOAD"), (sc.force, "FORCE"), (sc.stress, "STRESS"),
            (sc.aerof, "AEROF"), (sc.apres, "APRES"),
        ]:
            if flag:
                lines.append(f"  {keyword} = ALL")
    lines.append("BEGIN BULK")
    for path in include_paths:
        lines.append(f"INCLUDE '{path}'")
    if bulk_section is not None:
        lines.extend(bulk_section.splitlines())
    if authored_block:
        lines.extend(authored_block.rstrip("\n").splitlines())
    lines.append("ENDDATA")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Analysis-plan summary (SOL-aware, read-only)
# ---------------------------------------------------------------------------

_SOL_TITLES: dict[int, str] = {
    101: "Static",
    103: "Normal Modes",
    144: "Static Aeroelastic Trim",
}


def _describe_outputs(sc: SubcaseControl) -> str:
    reqs = [
        name for flag, name in [
            (sc.displacement, "DISP"), (sc.spcforce, "SPCFORCE"),
            (sc.oload, "OLOAD"), (sc.force, "FORCE"), (sc.stress, "STRESS"),
            (sc.aerof, "AEROF"), (sc.apres, "APRES"),
        ] if flag
    ]
    return ", ".join(reqs) if reqs else "default"


def _summarize_sol101(sc: SubcaseControl, bulk: BulkData) -> str:
    load = f"LOAD {sc.load_sid}" if sc.load_sid is not None else "no load"
    spc = f"SPC {sc.spc_sid}" if sc.spc_sid is not None else "no SPC"
    return f"Static: {load}, {spc}; outputs {_describe_outputs(sc)}"


def _summarize_sol103(sc: SubcaseControl, bulk: BulkData) -> str:
    method = f"EIGRL {sc.method_sid}" if sc.method_sid is not None else "no METHOD"
    return f"Modal: modes via {method} (all frequencies & mode shapes output)"


def _summarize_sol144(sc: SubcaseControl, bulk: BulkData) -> str:
    # Pre-solve summary: advertise what the run WILL output based on the
    # case-control requests and the bulk cards present (AC5).
    has_monitors = bool(bulk.monpnt1s or bulk.monpnt3s)
    # Step 60: the payload / mass case this subcase runs at (baseline if unset).
    mass_case = ""
    if sc.massset_sid is not None:
        ms = bulk.masssets.get(sc.massset_sid)
        label = f" {ms.label}" if ms is not None else ""
        mass_case = f" [mass case {sc.mass_card} {sc.massset_sid}{label}]"
    if sc.mloads_sid is not None:
        outputs = "time histories, MANPRNT export, critical-sample loads"
        if has_monitors:
            outputs += ", monitor loads"
        return (f"Transient maneuver loads (MANVR {sc.mloads_sid}){mass_case}; "
                f"outputs {outputs}")
    parts: list[str] = []
    if sc.trim_sid is not None:
        trim = bulk.trims.get(sc.trim_sid)
        if trim is not None:
            parts.append(f"trim @ q={trim.q:g}, M={trim.mach:g} (TRIM {sc.trim_sid})")
        else:
            parts.append(f"trim (TRIM {sc.trim_sid})")
        if sc.trimobj_sid is not None:
            parts.append(f"over-determined (TRIMWGT {sc.trimobj_sid})")
    if sc.gustlf_sid is not None:
        gust = bulk.gustlfs.get(sc.gustlf_sid)
        detail = f", n = {gust.n:g} on TRIM {gust.trimid}" if gust is not None else ""
        parts.append(f"static gust case (GUSTLF {sc.gustlf_sid}{detail})")
    if sc.diverg_sid is not None:
        parts.append(f"divergence sweep (DIVERG {sc.diverg_sid})")
    head = "; ".join(parts) if parts else "aeroelastic"
    outputs = "trim vars, stability derivatives, aero totals, q_div, displacements"
    if bulk.aesurfs:
        outputs += ", hinge moments"
    if has_monitors:
        outputs += ", monitor loads"
    if bulk.monsects:
        outputs += ", section-cut running loads"
    if sc.aerof or sc.apres:
        outputs += ", box ΔCp/forces"
    return f"Aeroelastic {head}{mass_case}; outputs {outputs}"


_SOL_SUMMARY = {
    101: _summarize_sol101,
    103: _summarize_sol103,
    144: _summarize_sol144,
}


def summarize_case_control(cc: CaseControl, bulk: BulkData) -> list[str]:
    """Return human-readable per-subcase summary lines for the planned analysis.

    SOL-aware via the ``_SOL_SUMMARY`` registry so new solutions slot in without
    touching call sites; an unknown SOL falls back to a generic field dump.
    """
    fn = _SOL_SUMMARY.get(cc.sol)
    lines: list[str] = []
    for sc in cc.subcases:
        label = f"Subcase {sc.subcase_id}"
        if sc.title:
            label += f" ({sc.title})"
        if fn is not None:
            lines.append(f"{label} — {fn(sc, bulk)}")
        else:
            lines.append(
                f"{label} — LOAD {sc.load_sid}, SPC {sc.spc_sid}; "
                f"outputs {_describe_outputs(sc)}"
            )
    return lines


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def render_case_control_panel(
    bulk: Optional[BulkData], on_launch: Optional[Callable[[], None]] = None
) -> None:
    """Render the analysis-plan summary, a Launch button, and the case-control editor.

    When a case control is present, leads with a SOL-aware read-only summary and a
    ``Launch Analysis`` button (delegating to ``on_launch``); the subcase editor is
    demoted to a collapsed expander.  Updates ``st.session_state.case_control``.
    """
    st.subheader("Case Control")

    if bulk is None:
        st.info("Upload a model file first.")
        return

    cc: Optional[CaseControl] = st.session_state.get("case_control")
    loaded_cc: Optional[CaseControl] = st.session_state.get("_loaded_from_file_cc")

    # --- Planned-analysis summary + Launch (read-only) ---
    if cc is not None and cc.subcases:
        st.markdown("### Planned Analysis")
        st.markdown(f"**SOL {cc.sol} — {_SOL_TITLES.get(cc.sol, 'Analysis')}**")
        if cc.title:
            st.caption(cc.title)
        for line in summarize_case_control(cc, bulk):
            st.markdown(f"- {line}")
        errors, _ = check_case_control(bulk, cc)
        for err in errors:
            st.error(err)
        if on_launch is not None and st.button(
            "▶ Launch Analysis", type="primary", key=wk("cc_launch"),
            disabled=bool(errors),
            help="Fix the errors above first." if errors else None,
        ):
            on_launch()
            st.caption("Results are shown on the Results tab.")
        st.divider()

    # A checkbox (not an expander) demotes the editor — the editor itself nests
    # expanders, and Streamlit forbids expander-in-expander.
    show_editor = st.checkbox(
        "Edit case control", value=(cc is None), key=wk("cc_show_editor")
    )
    if show_editor:
        _render_case_control_editor(bulk, cc, loaded_cc)


def _render_case_control_editor(
    bulk: BulkData,
    cc: Optional[CaseControl],
    loaded_cc: Optional[CaseControl],
) -> None:
    """The original subcase editor + BDF export (now nested in an expander)."""
    # --- Loaded BDF preview (read-only, outside form) ---
    if loaded_cc is not None:
        with st.expander("Loaded BDF — Executive & Case Control", expanded=False):
            st.code(export_bdf_text(loaded_cc), language="text")
    else:
        st.info("No case control found in the loaded file — define one below.")

    if cc is not None and cc.sol not in _SOL_LABELS:
        st.info(
            f"SOL {cc.sol} case control is read-only in the editor — "
            "launch it from the summary above."
        )

    # Available SIDs from bulk data
    # Every set a LOAD selector may name: a GRAV-only set is one of them (#123).
    load_sids = sorted(set(bulk.forces) | set(bulk.moments) | set(bulk.loads) | set(bulk.gravs))
    spc_sids  = sorted(set(list(bulk.spcs.keys()) + list(bulk.spc1s.keys())))
    eigrl_sids = sorted(bulk.eigrls.keys())
    trim_sids    = sorted(bulk.trims.keys())
    trimobj_sids = sorted(bulk.trimobjs.keys())
    diverg_sids  = sorted(bulk.divergs.keys())
    mloads_sids  = sorted(bulk.mloads.keys())
    massset_sids = sorted(bulk.masssets.keys())
    gustlf_sids  = sorted(bulk.gustlfs.keys())

    # Initialise editable subcase list
    if not st.session_state.get("cc_subcases"):
        if cc and cc.subcases:
            st.session_state.cc_subcases = [
                cast(Dict[str, Any], {
                    "id":           sc.subcase_id,
                    "title":        sc.title,
                    "load_sid":     sc.load_sid,
                    "spc_sid":      sc.spc_sid,
                    "method_sid":   sc.method_sid,
                    "trim_sid":     sc.trim_sid,
                    "trimobj_sid":  sc.trimobj_sid,
                    "diverg_sid":   sc.diverg_sid,
                    "mloads_sid":   sc.mloads_sid,
                    "gustlf_sid":   sc.gustlf_sid,
                    "massset_sid":  sc.massset_sid,
                    "displacement": sc.displacement,
                    "spcforce":     sc.spcforce,
                    "oload":        sc.oload,
                    "force":        sc.force,
                    "stress":       sc.stress,
                    "aerof":        sc.aerof,
                    "apres":        sc.apres,
                })
                for sc in cc.subcases
            ]
        else:
            default = _default_subcase(1)
            default["load_sid"] = load_sids[0] if load_sids else None
            default["spc_sid"]  = spc_sids[0]  if spc_sids  else None
            st.session_state.cc_subcases = [default]

    # ------------------------------------------------------------------ form
    with st.form("cc_form"):

        # Executive Control
        st.markdown("**Executive Control**")
        col_sol, col_title = st.columns([1, 3])
        sol_keys = list(_SOL_LABELS.keys())
        current_sol = cc.sol if cc else 101
        sol_idx = sol_keys.index(current_sol) if current_sol in sol_keys else 0
        sol = col_sol.selectbox(
            "SOL",
            sol_keys,
            index=sol_idx,
            format_func=lambda v: _SOL_LABELS.get(v, str(v)),
        )
        title = col_title.text_input("Title", value=cc.title if cc else "")

        st.markdown("---")
        st.markdown("**Subcases**")

        for idx, sc_data in enumerate(st.session_state.cc_subcases):
            expander_label = f"Subcase {sc_data['id']}"
            if sc_data["title"]:
                expander_label += f" — {sc_data['title']}"
            with st.expander(expander_label, expanded=True):
                sc_data["title"] = st.text_input(
                    "Subcase title", value=sc_data["title"], key=wk(f"sc_title_{idx}")
                )

                col_load, col_spc = st.columns(2)
                load_opts: list[Optional[int]] = [None] + load_sids
                load_idx = load_opts.index(sc_data["load_sid"]) if sc_data["load_sid"] in load_opts else 0
                sc_data["load_sid"] = col_load.selectbox(
                    "LOAD SID",
                    load_opts,
                    index=load_idx,
                    format_func=lambda v: "— none —" if v is None else str(v),
                    key=wk(f"sc_load_{idx}"),
                    # #6: in SOL 144 the LOAD set is an applied structural load
                    # (thrust, engine torque) in the TRIM balance; the Trim kind
                    # keeps it, MANVR / Divergence-only drop it (_apply_sol144_kind).
                    help=("SOL 144: applied structural load (FORCE/MOMENT) added to the "
                          "TRIM balance — thrust, engine torque; GRAV is refused. Not "
                          "available for MANVR or divergence-only subcases.")
                    if sol == 144 else None,
                )
                spc_opts: list[Optional[int]] = [None] + spc_sids
                spc_idx = spc_opts.index(sc_data["spc_sid"]) if sc_data["spc_sid"] in spc_opts else 0
                sc_data["spc_sid"] = col_spc.selectbox(
                    "SPC SID",
                    spc_opts,
                    index=spc_idx,
                    format_func=lambda v: "— none —" if v is None else str(v),
                    key=wk(f"sc_spc_{idx}"),
                )

                if sol == 144:
                    _render_sol144_subcase_fields(
                        sc_data, idx, trim_sids, trimobj_sids, diverg_sids,
                        mloads_sids, massset_sids, gustlf_sids,
                    )

                if sol == 103:
                    eigrl_opts: list[Optional[int]] = [None] + eigrl_sids
                    e_idx = eigrl_opts.index(sc_data["method_sid"]) if sc_data["method_sid"] in eigrl_opts else 0
                    sc_data["method_sid"] = st.selectbox(
                        "METHOD (EIGRL) SID",
                        eigrl_opts,
                        index=e_idx,
                        format_func=lambda v: "— none —" if v is None else str(v),
                        key=wk(f"sc_method_{idx}"),
                    )
                else:
                    sc_data["method_sid"] = None

                output_fields = _SOL_OUTPUT_FIELDS.get(sol, [])
                if output_fields:
                    st.caption("Output requests")
                    out_cols = st.columns(len(output_fields))
                    for i, field in enumerate(output_fields):
                        sc_data[field] = out_cols[i].checkbox(
                            _OUTPUT_LABELS[field],
                            value=sc_data[field],
                            key=wk(f"sc_{field}_{idx}"),
                        )
                else:
                    st.info("All modal results (frequencies and mode shapes) are output automatically.")
                    for field in _OUTPUT_LABELS:
                        sc_data[field] = False

        # Advanced (INCLUDE paths) — collapsed.  One path per line; a deck may
        # compose several bulk files (multi-INCLUDE, Step 66).
        bulk_section = deck_bulk_section(st.session_state.get("_uploaded_source_text"))
        with st.expander("Advanced", expanded=False):
            if bulk_section is not None:
                st.caption(
                    "The loaded deck's bulk section, with its INCLUDE lines, is written "
                    "to the export unchanged."
                )
                include_paths = list(cc.includes) if cc else []
            else:
                # A bulk-data-only file: the export is a driver that INCLUDEs it.
                default_include = (st.session_state.get("_uploaded_filename")
                                   or "model.dat")
                include_text = st.text_area(
                    "INCLUDE paths (bulk data files, one per line)",
                    value="\n".join(cc.includes) if (cc and cc.includes) else default_include,
                    key=wk("cc_includes"),
                )
                include_paths = [p.strip() for p in include_text.splitlines() if p.strip()]

        # Action row
        col_add, col_rem, _, col_apply = st.columns([1, 1, 2, 2])
        add_clicked    = col_add.form_submit_button("+ Add subcase")
        remove_clicked = col_rem.form_submit_button("− Remove last")
        submitted      = col_apply.form_submit_button("Apply", type="primary")

    # ------------------------------------------------------------------ handlers
    if add_clicked:
        next_id = max(s["id"] for s in st.session_state.cc_subcases) + 1
        st.session_state.cc_subcases.append(_default_subcase(next_id))
        st.rerun()

    if remove_clicked and len(st.session_state.cc_subcases) > 1:
        st.session_state.cc_subcases.pop()
        st.rerun()

    if submitted:
        # Read committed values from widget session state keys
        # Each subcase is the loaded one with the edited fields replaced, so what the
        # editor has no widget for (SUBTITLE, LABEL, SET, MODEXP) is carried, not
        # dropped (#123).  The same holds for the deck-level fields below.
        loaded = {sc.subcase_id: sc for sc in cc.subcases} if cc else {}
        subcases = []
        for idx, s in enumerate(st.session_state.cc_subcases):
            fields = dict(s)
            fields["load_sid"] = st.session_state.get(wk(f"sc_load_{idx}"), s["load_sid"])
            if sol == 144:
                for key in ("trim_sid", "trimobj_sid", "diverg_sid",
                            "mloads_sid", "gustlf_sid", "massset_sid"):
                    fields[key] = st.session_state.get(wk(f"sc_{key}_{idx}"), s.get(key))
                kind = st.session_state.get(wk(f"sc_kind_{idx}"), _subcase_kind(fields))
                fields = _apply_sol144_kind(fields, kind)
            else:
                for key in ("trim_sid", "trimobj_sid", "diverg_sid",
                            "mloads_sid", "gustlf_sid", "massset_sid"):
                    fields[key] = None
            subcases.append(dataclasses.replace(
                loaded.get(s["id"]) or SubcaseControl(subcase_id=s["id"]),
                title=st.session_state.get(wk(f"sc_title_{idx}"), s["title"]),
                # SOL 144: kept for a Trim subcase (applied load in the trim balance,
                # #6), dropped for MANVR / divergence-only by _apply_sol144_kind.
                load_sid=fields["load_sid"],
                spc_sid=st.session_state.get(wk(f"sc_spc_{idx}"), s["spc_sid"]),
                method_sid=st.session_state.get(wk(f"sc_method_{idx}")) if sol == 103 else None,
                trim_sid=fields["trim_sid"],
                trimobj_sid=fields["trimobj_sid"],
                diverg_sid=fields["diverg_sid"],
                mloads_sid=fields["mloads_sid"],
                gustlf_sid=fields.get("gustlf_sid"),
                massset_sid=fields["massset_sid"],
                # #102: an MSC mass combination is selected with MASSSET
                mass_card=("MASSSET" if fields["massset_sid"] in bulk.masssets
                           and bulk.masssets[fields["massset_sid"]].msc else "MASSCASE"),
                displacement=st.session_state.get(wk(f"sc_displacement_{idx}"), s["displacement"]),
                spcforce=st.session_state.get(wk(f"sc_spcforce_{idx}"), s["spcforce"]),
                oload=st.session_state.get(wk(f"sc_oload_{idx}"), s["oload"]),
                force=st.session_state.get(wk(f"sc_force_{idx}"), s["force"]),
                stress=st.session_state.get(wk(f"sc_stress_{idx}"), s["stress"]),
                aerof=st.session_state.get(wk(f"sc_aerof_{idx}"), s.get("aerof", False)) if sol == 144 else False,
                apres=st.session_state.get(wk(f"sc_apres_{idx}"), s.get("apres", False)) if sol == 144 else False,
            ))
        st.session_state.case_control = dataclasses.replace(
            cc if cc is not None else CaseControl(sol=sol),
            sol=sol,
            title=title,
            subcases=subcases,
            include=include_paths[0] if include_paths else None,
            includes=include_paths,
        )
        st.success("Case control updated.")

    # ------------------------------------------------------------------ export
    cc_current: Optional[CaseControl] = st.session_state.get("case_control")
    if cc_current is not None:
        # Export gate: the case control must make runnable cases, and no command may
        # still be an unresolved increment.  Card rules need no gate here: every
        # authored card has already been through the parser (#113).
        export_errors, _ = check_case_control(
            bulk, cc_current,
            unresolved_increments=list(
                st.session_state.get("mldcomd_increments", {}).values()),
        )
        authored_block = cards_text(
            bulk, st.session_state.get("authored_cards") or {},
            st.session_state.get("deck_blocks") or {})
        bdf_text = export_bdf_text(cc_current, include_paths=include_paths,
                                   authored_block=authored_block,
                                   bulk_section=bulk_section)
        for err in export_errors:
            st.error(err)
        st.download_button(
            label="Download BDF",
            data=bdf_text,
            file_name="run.bdf",
            mime="text/plain",
            disabled=bool(export_errors),
        )
        with st.expander("Preview BDF", expanded=False):
            st.code(bdf_text, language="text")


def _render_sol144_subcase_fields(
    sc_data: dict[str, Any],
    idx: int,
    trim_sids: list[int],
    trimobj_sids: list[int],
    diverg_sids: list[int],
    mloads_sids: list[int],
    massset_sids: list[int],
    gustlf_sids: list[int],
) -> None:
    """SOL 144 driver selection widgets for one subcase (inside the cc form).

    All pickers stay visible regardless of the chosen driver kind — widgets
    inside a form do not rerun the script on interaction, so hiding them on
    the radio value would leave stale UI.  The Apply handler keeps only the
    fields consistent with the selected kind.
    """
    kind = _subcase_kind(sc_data)
    st.radio(
        "Analysis kind",
        _SC_KINDS,
        index=_SC_KINDS.index(kind),
        horizontal=True,
        key=wk(f"sc_kind_{idx}"),
        help="Only the SIDs matching the selected kind are kept on Apply "
             "(DIVERG also combines with Trim as an add-on sweep).",
    )

    def _sid_box(col: DeltaGenerator, label: str, field: str, sids: list[int],
                 help_: str = "") -> None:
        opts: list[Optional[int]] = [None] + sids
        cur = sc_data.get(field)
        sc_data[field] = col.selectbox(
            label, opts,
            index=opts.index(cur) if cur in opts else 0,
            format_func=lambda v: "— none —" if v is None else str(v),
            key=wk(f"sc_{field}_{idx}"),
            help=help_ or None,
        )

    col1, col2, col3 = st.columns(3)
    _sid_box(col1, "TRIM SID", "trim_sid", trim_sids)
    _sid_box(col2, "TRIMWGT SID", "trimobj_sid", trimobj_sids,
             "Over-determined trim objective (optional).")
    _sid_box(col3, "DIVERG SID", "diverg_sid", diverg_sids,
             "Sole driver for a divergence-only subcase, or an add-on sweep "
             "after a trim.")
    col4, col5, col6 = st.columns(3)
    _sid_box(col4, "MANVR SID", "mloads_sid", mloads_sids,
             "Transient maneuver driver (Phase G0).")
    _sid_box(col5, "MASSCASE SID", "massset_sid", massset_sids,
             "Payload / mass case (baseline when none).")
    _sid_box(col6, "GUSTLF SID", "gustlf_sid", gustlf_sids,
             "Static gust load case (#1); it names its own TRIM, so TRIM SID may stay "
             "empty. Kept for a Trim subcase only.")


def _apply_sol144_kind(sc_data: dict[str, Any], kind: str) -> dict[str, Any]:
    """Return subcase fields filtered to the selected SOL 144 driver kind."""
    out = dict(sc_data)
    out["method_sid"] = None
    if kind == _SC_KIND_MLOADS:
        out["trim_sid"] = out["trimobj_sid"] = out["diverg_sid"] = out["gustlf_sid"] = None
        out["load_sid"] = None   # #6 D1: not carried through the transient
    elif kind == _SC_KIND_DIVERG:
        out["trim_sid"] = out["trimobj_sid"] = out["mloads_sid"] = out["gustlf_sid"] = None
        out["load_sid"] = None   # homogeneous eigenproblem — nothing to apply
    else:                        # Trim (DIVERG allowed as add-on sweep); LOAD kept (#6)
        out["mloads_sid"] = None
    return out


def _default_subcase(subcase_id: int) -> dict[str, Any]:
    return {
        "id":           subcase_id,
        "title":        "",
        "load_sid":     None,
        "spc_sid":      None,
        "method_sid":   None,
        "trim_sid":     None,
        "trimobj_sid":  None,
        "diverg_sid":   None,
        "mloads_sid":   None,
        "gustlf_sid":   None,
        "massset_sid":  None,
        "displacement": True,
        "spcforce":     True,
        "oload":        False,
        "force":        True,
        "stress":       True,
        "aerof":        False,
        "apres":        False,
    }
