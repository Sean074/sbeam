"""Case Control UI for sbeam viewer — Step 19."""

from __future__ import annotations

from typing import Optional

import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.parser.case_control import CaseControl, SubcaseControl


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

    # Available SIDs
    load_sids = sorted(set(list(bulk.forces.keys()) + list(bulk.moments.keys()) + list(bulk.loads.keys())))
    spc_sids = sorted(set(list(bulk.spcs.keys()) + list(bulk.spc1s.keys())))
    eigrl_sids = sorted(bulk.eigrls.keys())

    with st.form("cc_form"):
        sol = st.selectbox("SOL", [101, 103], index=(0 if cc is None or cc.sol == 101 else 1))
        title = st.text_input("Title", value=cc.title if cc else "")
        include_path = st.text_input(
            "INCLUDE path (bulk data file)",
            value=cc.include if (cc and cc.include) else "model.dat",
        )

        st.markdown("---")
        st.markdown("**Subcases**")

        # Initialise editable subcase list from session state or existing cc
        if not st.session_state.get("cc_subcases"):
            if cc and cc.subcases:
                st.session_state.cc_subcases = [
                    {
                        "id": sc.subcase_id,
                        "title": sc.title,
                        "load_sid": sc.load_sid,
                        "spc_sid": sc.spc_sid,
                        "method_sid": sc.method_sid,
                        "displacement": sc.displacement,
                        "spcforce": sc.spcforce,
                        "oload": sc.oload,
                        "force": sc.force,
                        "stress": sc.stress,
                    }
                    for sc in cc.subcases
                ]
            else:
                st.session_state.cc_subcases = [_default_subcase(1)]

        for idx, sc_data in enumerate(st.session_state.cc_subcases):
            with st.expander(f"Subcase {sc_data['id']}", expanded=True):
                sc_data["title"] = st.text_input(
                    "Subcase title", value=sc_data["title"], key=f"sc_title_{idx}"
                )
                load_opts: list = [None] + load_sids
                load_idx = load_opts.index(sc_data["load_sid"]) if sc_data["load_sid"] in load_opts else 0
                sc_data["load_sid"] = st.selectbox(
                    "LOAD SID",
                    load_opts,
                    index=load_idx,
                    format_func=lambda v: "— none —" if v is None else str(v),
                    key=f"sc_load_{idx}",
                )
                spc_opts: list = [None] + spc_sids
                spc_idx = spc_opts.index(sc_data["spc_sid"]) if sc_data["spc_sid"] in spc_opts else 0
                sc_data["spc_sid"] = st.selectbox(
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

                cols = st.columns(5)
                sc_data["displacement"] = cols[0].checkbox("DISPLACEMENT", value=sc_data["displacement"], key=f"sc_disp_{idx}")
                sc_data["spcforce"] = cols[1].checkbox("SPCFORCE", value=sc_data["spcforce"], key=f"sc_spcf_{idx}")
                sc_data["oload"] = cols[2].checkbox("OLOAD", value=sc_data["oload"], key=f"sc_oload_{idx}")
                sc_data["force"] = cols[3].checkbox("FORCE", value=sc_data["force"], key=f"sc_force_{idx}")
                sc_data["stress"] = cols[4].checkbox("STRESS", value=sc_data["stress"], key=f"sc_stress_{idx}")

        col_add, col_remove = st.columns(2)
        add_clicked = col_add.form_submit_button("+ Add subcase")
        remove_clicked = col_remove.form_submit_button("- Remove last subcase")
        submitted = st.form_submit_button("Apply case control", type="primary")

    if add_clicked:
        next_id = max(s["id"] for s in st.session_state.cc_subcases) + 1
        st.session_state.cc_subcases.append(_default_subcase(next_id))
        st.rerun()

    if remove_clicked and len(st.session_state.cc_subcases) > 1:
        st.session_state.cc_subcases.pop()
        st.rerun()

    if submitted:
        subcases = [
            SubcaseControl(
                subcase_id=s["id"],
                title=s["title"],
                load_sid=s["load_sid"],
                spc_sid=s["spc_sid"],
                method_sid=s["method_sid"],
                displacement=s["displacement"],
                spcforce=s["spcforce"],
                oload=s["oload"],
                force=s["force"],
                stress=s["stress"],
            )
            for s in st.session_state.cc_subcases
        ]
        st.session_state.case_control = CaseControl(
            sol=sol,
            title=title,
            subcases=subcases,
            include=include_path if include_path.strip() else None,
        )
        st.success("Case control updated.")

    cc_current: Optional[CaseControl] = st.session_state.get("case_control")
    if cc_current is not None:
        st.markdown("---")
        st.markdown("**Export**")
        bdf_text = export_bdf_text(cc_current, include_path=include_path if include_path.strip() else "model.dat")
        st.download_button(
            label="Download case control BDF",
            data=bdf_text,
            file_name="run.bdf",
            mime="text/plain",
        )
        with st.expander("Preview BDF"):
            st.code(bdf_text, language="text")


def _default_subcase(subcase_id: int) -> dict:
    return {
        "id": subcase_id,
        "title": "",
        "load_sid": None,
        "spc_sid": None,
        "method_sid": None,
        "displacement": True,
        "spcforce": True,
        "oload": False,
        "force": True,
        "stress": True,
    }
