from __future__ import annotations

import os
import re
import tempfile
import warnings
from typing import Optional

import pandas as pd
import streamlit as st

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file
from sbeam.model.bulk_data import BulkData
from sbeam.gpwg import compute_gpwg
from sbeam.viewer.geometry import build_model_figure
from sbeam.viewer.case_control_ui import render_case_control_panel
from sbeam.viewer.results_view import render_sol101_results, render_sol103_results


def _init_session_state() -> None:
    defaults: dict = {
        "bulk_data": None,
        "case_control": None,
        "sol101_result": None,
        "sol103_result": None,
        "selected_gid": None,
        "selected_eid": None,
        "cc_subcases": None,
        "selected_subcase_id": None,
        "_parse_warnings": [],
        "_parse_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _has_case_control(content: str) -> bool:
    """Return True if the file content has a SOL statement before BEGIN BULK."""
    for line in content.splitlines():
        idx = line.find("$")
        clean = (line[:idx] if idx >= 0 else line).strip()
        if re.match(r"(?i)^begin\b", clean):
            break
        if re.match(r"(?i)^sol\b", clean):
            return True
    return False


def _handle_upload(uploaded) -> None:
    suffix = os.path.splitext(uploaded.name)[-1] or ".bdf"
    tmp_path: Optional[str] = None
    try:
        content = uploaded.read().decode("utf-8", errors="replace")
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=suffix, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if _has_case_control(content):
                cc, bulk = parse_bdf(tmp_path)
            else:
                bulk = parse_bulk_file(tmp_path)
                cc = None

        st.session_state.bulk_data = bulk
        st.session_state.case_control = cc
        st.session_state.cc_subcases = None   # reset subcase editor
        st.session_state.sol101_result = None
        st.session_state.sol103_result = None
        st.session_state.selected_gid = None
        st.session_state.selected_eid = None
        st.session_state.selected_subcase_id = cc.subcases[0].subcase_id if cc and cc.subcases else None
        st.session_state._parse_warnings = [str(w.message) for w in caught]
        st.session_state._parse_error = None
    except Exception as exc:
        st.session_state.bulk_data = None
        st.session_state.case_control = None
        st.session_state._parse_error = str(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _show_parse_summary(bulk: BulkData) -> None:
    cc = st.session_state.case_control
    load_sets = len(set(list(bulk.forces) + list(bulk.moments) + list(bulk.loads)))
    spc_sets = len(set(list(bulk.spcs) + list(bulk.spc1s)))
    if cc is not None:
        cols = st.columns(6)
        cols[0].metric("SOL", cc.sol)
        cols[1].metric("Subcases", len(cc.subcases))
        cols[2].metric("Grids", len(bulk.grids))
        cols[3].metric("CBARs", len(bulk.cbars))
        cols[4].metric("Load sets", load_sets)
        cols[5].metric("SPC sets", spc_sets)
    else:
        cols = st.columns(5)
        cols[0].metric("Grids", len(bulk.grids))
        cols[1].metric("CBARs", len(bulk.cbars))
        cols[2].metric("Materials", len(bulk.mat1s))
        cols[3].metric("Load sets", load_sets)
        cols[4].metric("SPC sets", spc_sets)
        st.caption("No case control loaded — define analysis via Case Control tab.")


def _show_warnings() -> None:
    msgs = st.session_state._parse_warnings
    if msgs:
        with st.expander(f"Parser warnings ({len(msgs)})"):
            for msg in msgs:
                st.warning(msg)


def _show_gpwg(bulk: BulkData) -> None:
    gpwg = compute_gpwg(bulk)
    st.markdown("**GPWG — Mass & CG**")
    st.metric("Total mass", f"{gpwg.total_mass:.6g}")
    cols = st.columns(3)
    cols[0].metric("CG X", f"{gpwg.cg_x:.4g}")
    cols[1].metric("CG Y", f"{gpwg.cg_y:.4g}")
    cols[2].metric("CG Z", f"{gpwg.cg_z:.4g}")


def _show_item_inspector(bulk: BulkData) -> None:
    st.markdown("**Item inspector**")
    gid_opts: list = [None] + sorted(bulk.grids.keys())
    selected_gid = st.selectbox(
        "Inspect GRID",
        gid_opts,
        format_func=lambda g: "— none —" if g is None else f"GID {g}",
        key="sel_gid_box",
    )
    st.session_state.selected_gid = selected_gid

    if selected_gid is not None:
        g = bulk.grids[selected_gid]
        st.write(f"**X:** {g.x:.6g}  **Y:** {g.y:.6g}  **Z:** {g.z:.6g}")
        st.write(f"**PS:** {g.ps or '—'}")
        spc_info = _grid_spc_info(bulk, selected_gid)
        st.write(f"**SPC:** {spc_info}")

    st.markdown("")
    eid_opts: list = [None] + sorted(bulk.cbars.keys())
    selected_eid = st.selectbox(
        "Inspect CBAR",
        eid_opts,
        format_func=lambda e: "— none —" if e is None else f"EID {e}",
        key="sel_eid_box",
    )
    st.session_state.selected_eid = selected_eid

    if selected_eid is not None and selected_eid in bulk.cbars:
        import math
        cbar = bulk.cbars[selected_eid]
        ga = bulk.grids[cbar.ga]
        gb = bulk.grids[cbar.gb]
        L = math.sqrt((gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2)
        pbar = bulk.pbars.get(cbar.pid)
        mat1 = bulk.mat1s.get(pbar.mid) if pbar else None
        st.write(f"**PID:** {cbar.pid}  **MID:** {mat1.mid if mat1 else '—'}")
        st.write(f"**GA:** {cbar.ga}  **GB:** {cbar.gb}  **L:** {L:.4g}")
        if pbar:
            st.write(f"**A:** {pbar.A:.4g}  **I1:** {pbar.I1:.4g}  **I2:** {pbar.I2:.4g}  **J:** {pbar.J:.4g}")
        st.write(f"**PA:** {cbar.pa or '—'}  **PB:** {cbar.pb or '—'}")


def _grid_spc_info(bulk: BulkData, gid: int) -> str:
    parts = []
    for sid, entries in bulk.spc1s.items():
        for e in entries:
            if gid in e.grids:
                parts.append(f"SPC1 SID={sid} DOFs={e.c}")
    for sid, entries in bulk.spcs.items():
        for e in entries:
            if e.g1 == gid:
                parts.append(f"SPC SID={sid} DOFs={e.c1}")
            if e.g2 == gid and e.c2:
                parts.append(f"SPC SID={sid} DOFs={e.c2}")
    return "; ".join(parts) if parts else "—"


def _show_model_data_tabs(bulk: BulkData) -> None:
    tabs = st.tabs(["Grids", "Elements", "Properties", "Materials", "Loads", "Constraints"])

    with tabs[0]:
        if bulk.grids:
            rows = [{"GID": g.gid, "X": g.x, "Y": g.y, "Z": g.z, "PS": g.ps or ""} for g in bulk.grids.values()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No grids.")

    with tabs[1]:
        rows = []
        for c in bulk.cbars.values():
            ga = bulk.grids.get(c.ga)
            gb = bulk.grids.get(c.gb)
            import math
            L = math.sqrt((gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2) if ga and gb else 0.0
            rows.append({"EID": c.eid, "PID": c.pid, "GA": c.ga, "GB": c.gb, "L": f"{L:.4g}", "PA": c.pa or "", "PB": c.pb or ""})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No CBAR elements.")

    with tabs[2]:
        if bulk.pbars:
            rows = [{"PID": p.pid, "MID": p.mid, "A": p.A, "I1": p.I1, "I2": p.I2, "J": p.J, "NSM": p.nsm} for p in bulk.pbars.values()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No PBAR properties.")

    with tabs[3]:
        if bulk.mat1s:
            rows = [{"MID": m.mid, "E": m.E, "G": m.G, "nu": m.nu, "rho": m.rho} for m in bulk.mat1s.values()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No MAT1 materials.")

    with tabs[4]:
        rows = []
        for sid, forces in bulk.forces.items():
            for f in forces:
                rows.append({"Type": "FORCE", "SID": sid, "GID": f.gid, "Scale": f.f, "N1": f.n1, "N2": f.n2, "N3": f.n3})
        for sid, moments in bulk.moments.items():
            for m in moments:
                rows.append({"Type": "MOMENT", "SID": sid, "GID": m.gid, "Scale": m.m, "N1": m.n1, "N2": m.n2, "N3": m.n3})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No loads.")

    with tabs[5]:
        rows = []
        for sid, entries in bulk.spc1s.items():
            for s in entries:
                rows.append({"Type": "SPC1", "SID": sid, "DOFs": s.c, "Grids": str(s.grids)})
        for sid, entries in bulk.spcs.items():
            for s in entries:
                rows.append({"Type": "SPC", "SID": sid, "DOFs": s.c1, "Grids": str(s.g1)})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No constraints.")


def _active_load_sid() -> Optional[int]:
    cc = st.session_state.case_control
    if cc is None or not cc.subcases:
        return None
    sel_id = st.session_state.selected_subcase_id
    for sc in cc.subcases:
        if sc.subcase_id == sel_id:
            return sc.load_sid
    return cc.subcases[0].load_sid


def _run_analysis(bulk: BulkData) -> None:
    cc = st.session_state.case_control
    if cc is None:
        st.error("Define a case control first (Case Control tab).")
        return

    try:
        if cc.sol == 101:
            from sbeam.solver.sol101 import run_sol101
            with st.spinner("Running SOL 101…"):
                result = run_sol101(bulk, cc)
            st.session_state.sol101_result = result
            st.session_state.sol103_result = None
            st.success("SOL 101 complete.")
        elif cc.sol == 103:
            from sbeam.solver.sol103 import run_sol103
            with st.spinner("Running SOL 103…"):
                result = run_sol103(bulk, cc)
            st.session_state.sol103_result = result
            st.session_state.sol101_result = None
            st.success(f"SOL 103 complete — {len(result.frequencies_hz)} modes extracted.")
        else:
            st.error(f"SOL {cc.sol} is not supported.")
    except Exception as exc:
        st.error(f"Solver error: {exc}")


def main() -> None:
    st.set_page_config(page_title="sbeam", layout="wide")
    st.title("sbeam — Simple Beam FEA")
    _init_session_state()

    # --- Sidebar ---
    with st.sidebar:
        st.header("Model")
        uploaded = st.file_uploader(
            "Upload BDF / DAT file",
            type=["bdf", "dat"],
            key="file_uploader",
        )
        if uploaded is not None:
            _handle_upload(uploaded)

        bulk: Optional[BulkData] = st.session_state.bulk_data
        if bulk is not None:
            cc_sidebar = st.session_state.case_control
            if cc_sidebar is not None and cc_sidebar.subcases:
                st.divider()
                sc_options = {
                    f"Subcase {sc.subcase_id}: {sc.title or '—'}": sc
                    for sc in cc_sidebar.subcases
                }
                sel_label = st.selectbox(
                    "Active subcase",
                    list(sc_options.keys()),
                    key="subcase_selectbox",
                )
                st.session_state.selected_subcase_id = sc_options[sel_label].subcase_id
            st.divider()
            _show_gpwg(bulk)
            st.divider()
            _show_item_inspector(bulk)

    # --- Error / empty state ---
    if st.session_state._parse_error is not None:
        st.error(f"Parse error: {st.session_state._parse_error}")
        return

    bulk = st.session_state.bulk_data
    if bulk is None:
        st.info("Upload a BDF or DAT file to begin.")
        return

    # --- Main tabs ---
    tab_model, tab_cc, tab_results = st.tabs(["Model", "Case Control", "Results"])

    with tab_model:
        _show_parse_summary(bulk)
        _show_warnings()
        fig = build_model_figure(
            bulk,
            selected_gid=st.session_state.selected_gid,
            selected_eid=st.session_state.selected_eid,
            load_sid=_active_load_sid(),
        )
        st.plotly_chart(fig, use_container_width=True)
        _show_model_data_tabs(bulk)

    with tab_cc:
        render_case_control_panel(bulk)

    with tab_results:
        st.subheader("Analysis")
        if st.button("Run Analysis", type="primary"):
            _run_analysis(bulk)

        if st.session_state.sol101_result is not None:
            render_sol101_results(bulk, st.session_state.sol101_result, load_sid=_active_load_sid())

        elif st.session_state.sol103_result is not None:
            render_sol103_results(bulk, st.session_state.sol103_result)

        else:
            cc = st.session_state.case_control
            if cc is not None:
                st.info(f"Press Run Analysis to execute SOL {cc.sol}.")
            else:
                st.info("Define a case control in the Case Control tab, then run the analysis.")


if __name__ == "__main__":
    main()
