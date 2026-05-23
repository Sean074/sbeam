"""Case Control UI for sbeam viewer."""

from __future__ import annotations

from typing import Optional

import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOL_LABELS: dict[int, str] = {
    101: "101 — Static",
    103: "103 — Normal Modes",
    # Phase 2: 108, 109, 111, 112 added here
}

# Output request fields rendered per SOL.  SOLs absent from this dict show no
# checkboxes (e.g. SOL 103 always outputs all modes automatically).
_SOL_OUTPUT_FIELDS: dict[int, list[str]] = {
    101: ["displacement", "spcforce", "oload", "force", "stress"],
}

_OUTPUT_LABELS: dict[str, str] = {
    "displacement": "DISPLACEMENT",
    "spcforce":     "SPCFORCE",
    "oload":        "OLOAD",
    "force":        "FORCE",
    "stress":       "STRESS",
}


# ---------------------------------------------------------------------------
# BDF export
# ---------------------------------------------------------------------------

def export_bdf_text(cc: CaseControl, include_path: str = "model.dat") -> str:
    """Return a BDF case control file as a string, parseable by parse_bdf."""
    lines: list[str] = []
    lines.append(f"SOL {cc.sol}")
    if cc.title:
        lines.append(f"TITLE = {cc.title}")
    for sc in cc.subcases:
        lines.append(f"SUBCASE {sc.subcase_id}")
        if sc.title:
            lines.append(f"  TITLE = {sc.title}")
        if sc.load_sid is not None:
            lines.append(f"  LOAD = {sc.load_sid}")
        if sc.spc_sid is not None:
            lines.append(f"  SPC = {sc.spc_sid}")
        if sc.method_sid is not None:
            lines.append(f"  METHOD = {sc.method_sid}")
        if sc.displacement:
            lines.append("  DISPLACEMENT = ALL")
        if sc.spcforce:
            lines.append("  SPCFORCE = ALL")
        if sc.oload:
            lines.append("  OLOAD = ALL")
        if sc.force:
            lines.append("  FORCE = ALL")
        if sc.stress:
            lines.append("  STRESS = ALL")
    lines.append(f"INCLUDE '{include_path}'")
    lines.append("BEGIN BULK")
    lines.append("ENDDATA")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

def render_case_control_panel(bulk: Optional[BulkData]) -> None:
    """Render the case control definition form. Updates st.session_state.case_control."""
    st.subheader("Case Control")

    if bulk is None:
        st.info("Upload a model file first.")
        return

    cc: Optional[CaseControl] = st.session_state.get("case_control")
    loaded_cc: Optional[CaseControl] = st.session_state.get("_loaded_from_file_cc")

    # --- Loaded BDF preview (read-only, outside form) ---
    if loaded_cc is not None:
        with st.expander("Loaded BDF — Executive & Case Control", expanded=False):
            st.code(export_bdf_text(loaded_cc, include_path=loaded_cc.include or "model.dat"), language="text")
    else:
        st.info("No case control found in the loaded file — define one below.")

    # Available SIDs from bulk data
    load_sids = sorted(set(list(bulk.forces.keys()) + list(bulk.moments.keys()) + list(bulk.loads.keys())))
    spc_sids  = sorted(set(list(bulk.spcs.keys()) + list(bulk.spc1s.keys())))
    eigrl_sids = sorted(bulk.eigrls.keys())

    # Initialise editable subcase list
    if not st.session_state.get("cc_subcases"):
        if cc and cc.subcases:
            st.session_state.cc_subcases = [
                {
                    "id":           sc.subcase_id,
                    "title":        sc.title,
                    "load_sid":     sc.load_sid,
                    "spc_sid":      sc.spc_sid,
                    "method_sid":   sc.method_sid,
                    "displacement": sc.displacement,
                    "spcforce":     sc.spcforce,
                    "oload":        sc.oload,
                    "force":        sc.force,
                    "stress":       sc.stress,
                }
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
                    "Subcase title", value=sc_data["title"], key=f"sc_title_{idx}"
                )

                col_load, col_spc = st.columns(2)
                load_opts: list = [None] + load_sids
                load_idx = load_opts.index(sc_data["load_sid"]) if sc_data["load_sid"] in load_opts else 0
                sc_data["load_sid"] = col_load.selectbox(
                    "LOAD SID",
                    load_opts,
                    index=load_idx,
                    format_func=lambda v: "— none —" if v is None else str(v),
                    key=f"sc_load_{idx}",
                )
                spc_opts: list = [None] + spc_sids
                spc_idx = spc_opts.index(sc_data["spc_sid"]) if sc_data["spc_sid"] in spc_opts else 0
                sc_data["spc_sid"] = col_spc.selectbox(
                    "SPC SID",
                    spc_opts,
                    index=spc_idx,
                    format_func=lambda v: "— none —" if v is None else str(v),
                    key=f"sc_spc_{idx}",
                )

                if sol == 103:
                    eigrl_opts: list = [None] + eigrl_sids
                    e_idx = eigrl_opts.index(sc_data["method_sid"]) if sc_data["method_sid"] in eigrl_opts else 0
                    sc_data["method_sid"] = st.selectbox(
                        "METHOD (EIGRL) SID",
                        eigrl_opts,
                        index=e_idx,
                        format_func=lambda v: "— none —" if v is None else str(v),
                        key=f"sc_method_{idx}",
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
                            key=f"sc_{field}_{idx}",
                        )
                else:
                    st.info("All modal results (frequencies and mode shapes) are output automatically.")
                    for field in _OUTPUT_LABELS:
                        sc_data[field] = False

        # Advanced (INCLUDE path) — collapsed
        with st.expander("Advanced", expanded=False):
            include_path = st.text_input(
                "INCLUDE path (bulk data file)",
                value=cc.include if (cc and cc.include) else "model.dat",
            )

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
        subcases = [
            SubcaseControl(
                subcase_id=s["id"],
                title=st.session_state.get(f"sc_title_{idx}", s["title"]),
                load_sid=st.session_state.get(f"sc_load_{idx}", s["load_sid"]),
                spc_sid=st.session_state.get(f"sc_spc_{idx}", s["spc_sid"]),
                method_sid=st.session_state.get(f"sc_method_{idx}") if sol == 103 else None,
                displacement=st.session_state.get(f"sc_displacement_{idx}", s["displacement"]),
                spcforce=st.session_state.get(f"sc_spcforce_{idx}", s["spcforce"]),
                oload=st.session_state.get(f"sc_oload_{idx}", s["oload"]),
                force=st.session_state.get(f"sc_force_{idx}", s["force"]),
                stress=st.session_state.get(f"sc_stress_{idx}", s["stress"]),
            )
            for idx, s in enumerate(st.session_state.cc_subcases)
        ]
        st.session_state.case_control = CaseControl(
            sol=sol,
            title=title,
            subcases=subcases,
            include=include_path.strip() or None,
        )
        st.success("Case control updated.")

    # ------------------------------------------------------------------ export
    cc_current: Optional[CaseControl] = st.session_state.get("case_control")
    if cc_current is not None:
        bdf_text = export_bdf_text(cc_current, include_path=include_path)
        st.download_button(
            label="Download BDF",
            data=bdf_text,
            file_name="run.bdf",
            mime="text/plain",
        )
        with st.expander("Preview BDF", expanded=False):
            st.code(bdf_text, language="text")


def _default_subcase(subcase_id: int) -> dict:
    return {
        "id":           subcase_id,
        "title":        "",
        "load_sid":     None,
        "spc_sid":      None,
        "method_sid":   None,
        "displacement": True,
        "spcforce":     True,
        "oload":        False,
        "force":        True,
        "stress":       True,
    }
