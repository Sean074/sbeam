from __future__ import annotations

import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

import numpy as np

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file
from sbeam.model.bulk_data import BulkData
from sbeam.gpwg import compute_gpwg
from sbeam.viewer.geometry import build_model_figure
from sbeam.viewer.case_control_ui import render_case_control_panel
from sbeam.viewer.results_view import (
    render_sol101_results, render_sol103_results, render_sol144_results,
)
from sbeam.viewer.aero_view import (
    build_aero_box_figure, build_span_loading_figure, rigid_derivative_table,
)
from sbeam.viewer.aero_correction_view import render_aero_correction_tab
from sbeam.viewer.format_utils import fmt, fmt_mass, style_numeric
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero.vlm import solve_rigid_cl


def _init_session_state() -> None:
    defaults: dict = {
        "bulk_data": None,
        "case_control": None,
        "_loaded_from_file_cc": None,
        "sol101_result": None,
        "sol103_result": None,
        "sol144_result": None,
        "sol144_diverg_result": None,
        "maneuver_result": None,
        "aero_model_144": None,
        "aero_model": None,
        "aero_result": None,
        "aero_result_unc": None,
        "aero_corr_model": None,
        "aero_corr_df": None,
        "aero_corr_result": None,
        "aero_corr_sids": set(),
        "aero_corr_upload_id": None,
        "aero_corr_csv_name": None,
        "aero_corr_cond": None,
        "selected_gid": None,
        "selected_eid": None,
        "cc_subcases": None,
        "selected_subcase_id": None,
        "_parse_warnings": [],
        "_parse_error": None,
        "_uploaded_file_id": None,
        "_uploaded_filename": None,
        "_uploaded_source_text": None,
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
        st.session_state._loaded_from_file_cc = cc
        st.session_state._uploaded_filename = uploaded.name
        st.session_state._uploaded_source_text = content
        st.session_state.cc_subcases = None   # reset subcase editor
        st.session_state.sol101_result = None
        st.session_state.sol103_result = None
        st.session_state.sol144_result = None
        st.session_state.sol144_diverg_result = None
        st.session_state.maneuver_result = None
        st.session_state.aero_model_144 = None
        st.session_state.aero_model = None
        st.session_state.aero_result = None
        st.session_state.aero_result_unc = None
        st.session_state.aero_corr_model = None
        st.session_state.aero_corr_df = None
        st.session_state.aero_corr_result = None
        st.session_state.aero_corr_sids = set()
        st.session_state.aero_corr_upload_id = None
        st.session_state.aero_corr_csv_name = None
        st.session_state.aero_corr_cond = None
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
        cols = st.columns(10)
        cols[0].metric("SOL", cc.sol)
        cols[1].metric("Subcases", len(cc.subcases))
        cols[2].metric("Grids", len(bulk.grids))
        cols[3].metric("CBARs", len(bulk.cbars))
        cols[4].metric("CBUSHs", len(bulk.cbushs))
        cols[5].metric("RBE3s", len(bulk.rbe3s))
        cols[6].metric("RBE2s", len(bulk.rbe2s))
        cols[7].metric("CONM2s", len(bulk.conm2s))
        cols[8].metric("Load sets", load_sets)
        cols[9].metric("SPC sets", spc_sets)
    else:
        cols = st.columns(9)
        cols[0].metric("Grids", len(bulk.grids))
        cols[1].metric("CBARs", len(bulk.cbars))
        cols[2].metric("CBUSHs", len(bulk.cbushs))
        cols[3].metric("RBE3s", len(bulk.rbe3s))
        cols[4].metric("RBE2s", len(bulk.rbe2s))
        cols[5].metric("CONM2s", len(bulk.conm2s))
        cols[6].metric("Materials", len(bulk.mat1s))
        cols[7].metric("Load sets", load_sets)
        cols[8].metric("SPC sets", spc_sets)
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
    st.metric("Total mass", fmt_mass(gpwg.total_mass))
    cols = st.columns(3)
    cols[0].metric("CG X", fmt(gpwg.cg_x))
    cols[1].metric("CG Y", fmt(gpwg.cg_y))
    cols[2].metric("CG Z", fmt(gpwg.cg_z))


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
        st.write(f"**X:** {fmt(g.x)}  **Y:** {fmt(g.y)}  **Z:** {fmt(g.z)}")
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
        st.write(f"**GA:** {cbar.ga}  **GB:** {cbar.gb}  **L:** {fmt(L)}")
        if pbar:
            st.write(f"**A:** {fmt(pbar.A)}  **I1:** {fmt(pbar.I1)}  **I2:** {fmt(pbar.I2)}  **J:** {fmt(pbar.J)}")
        st.write(f"**PA:** {cbar.pa or '—'}  **PB:** {cbar.pb or '—'}")

    if bulk.rbe3s:
        st.markdown("")
        rbe3_opts: list = [None] + sorted(bulk.rbe3s.keys())
        selected_rbe3_eid = st.selectbox(
            "Inspect RBE3",
            rbe3_opts,
            format_func=lambda e: "— none —" if e is None else f"EID {e}",
            key="sel_rbe3_eid_box",
        )
        if selected_rbe3_eid is not None and selected_rbe3_eid in bulk.rbe3s:
            rbe3 = bulk.rbe3s[selected_rbe3_eid]
            st.write(f"**RefGrid:** {rbe3.refgrid}  **RefDOFs:** {rbe3.refc}")
            for i, (weight, dofs, grids) in enumerate(rbe3.wt_gc):
                st.write(f"**Group {i + 1}:** WT={weight}  DOFs={dofs}  Grids={grids}")

    if bulk.rbe2s:
        st.markdown("")
        rbe2_opts: list = [None] + sorted(bulk.rbe2s.keys())
        selected_rbe2_eid = st.selectbox(
            "Inspect RBE2",
            rbe2_opts,
            format_func=lambda e: "— none —" if e is None else f"EID {e}",
            key="sel_rbe2_eid_box",
        )
        if selected_rbe2_eid is not None and selected_rbe2_eid in bulk.rbe2s:
            rbe2 = bulk.rbe2s[selected_rbe2_eid]
            st.write(f"**IndepGrid (GN):** {rbe2.gn}  **CoupledDOFs (CM):** {rbe2.cm}")
            st.write(f"**Dependent Grids (GM):** {rbe2.gm}")


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
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No grids.")

    with tabs[1]:
        import math
        cbar_rows = []
        for c in bulk.cbars.values():
            ga = bulk.grids.get(c.ga)
            gb = bulk.grids.get(c.gb)
            L = math.sqrt((gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2) if ga and gb else 0.0
            cbar_rows.append({"EID": c.eid, "PID": c.pid, "GA": c.ga, "GB": c.gb, "L": L, "PA": c.pa or "", "PB": c.pb or ""})
        if cbar_rows:
            st.markdown("**CBAR elements**")
            st.dataframe(style_numeric(pd.DataFrame(cbar_rows)), width="stretch")
        else:
            st.info("No CBAR elements.")
        if bulk.rbe3s:
            st.markdown("**RBE3 elements**")
            rbe3_rows = []
            for r in bulk.rbe3s.values():
                n_indep = sum(len(grids) for _, _, grids in r.wt_gc)
                rbe3_rows.append({"EID": r.eid, "RefGrid": r.refgrid, "RefDOFs": r.refc, "Num Indep. Grids": n_indep})
            st.dataframe(pd.DataFrame(rbe3_rows), width="stretch")
        if bulk.rbe2s:
            st.markdown("**RBE2 elements**")
            rbe2_rows = [
                {"EID": r.eid, "GN (indep)": r.gn, "CM (DOFs)": r.cm, "Num Dep. Grids": len(r.gm)}
                for r in bulk.rbe2s.values()
            ]
            st.dataframe(pd.DataFrame(rbe2_rows), width="stretch")
        if bulk.cbushs:
            st.markdown("**CBUSH elements**")
            cbush_rows = [
                {"EID": c.eid, "PID": c.pid, "GA": c.ga, "GB": c.gb if c.gb is not None else "GND"}
                for c in bulk.cbushs.values()
            ]
            st.dataframe(pd.DataFrame(cbush_rows), width="stretch")
        if bulk.conm2s:
            st.markdown("**CONM2 masses**")
            conm2_rows = [
                {"EID": c.eid, "GID": c.gid, "Mass": c.m, "X1": c.x1, "X2": c.x2, "X3": c.x3}
                for c in bulk.conm2s.values()
            ]
            st.dataframe(style_numeric(pd.DataFrame(conm2_rows), mass_cols=["Mass"]),
                         width="stretch")

    with tabs[2]:
        if bulk.pbars:
            rows = [{"PID": p.pid, "MID": p.mid, "A": p.A, "I1": p.I1, "I2": p.I2, "J": p.J, "NSM": p.nsm} for p in bulk.pbars.values()]
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No PBAR properties.")
        if bulk.pbushs:
            st.markdown("**PBUSH properties**")
            pbush_rows = [
                {"PID": p.pid, "K1": p.k1, "K2": p.k2, "K3": p.k3, "K4": p.k4, "K5": p.k5, "K6": p.k6}
                for p in bulk.pbushs.values()
            ]
            st.dataframe(style_numeric(pd.DataFrame(pbush_rows)), width="stretch")

    with tabs[3]:
        if bulk.mat1s:
            rows = [{"MID": m.mid, "E": m.E, "G": m.G, "nu": m.nu, "rho": m.rho} for m in bulk.mat1s.values()]
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
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
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
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
            st.dataframe(pd.DataFrame(rows), width="stretch")
        else:
            st.info("No constraints.")


def _get_pre_solve_warnings(
    bulk: BulkData, cc, parse_warnings: list
) -> list:
    """Return pre-solve validation warning strings.

    Checks performed:
    - Zero-length CBAR elements (singular stiffness matrix).
    - No SPC/SPC1 constraints (unconstrained model; bad for SOL 101).
    - SPC SID referenced in case control but absent from bulk.
    - Unsupported load cards present (e.g. PLOAD1), silently dropped by parser.
    - MAT1 rho=0 for SOL 103 (mass matrix will be zero → unreliable frequencies).
    - E-value range >1000x across materials (possible unit inconsistency).
    """
    import math

    msgs: list = []

    # 1. Zero-length CBAR elements
    zero_eids = []
    for eid, cbar in bulk.cbars.items():
        ga = bulk.grids.get(cbar.ga)
        gb = bulk.grids.get(cbar.gb)
        if ga and gb:
            L = math.sqrt(
                (gb.x - ga.x) ** 2 + (gb.y - ga.y) ** 2 + (gb.z - ga.z) ** 2
            )
            if L == 0.0:
                zero_eids.append(eid)
    if zero_eids:
        msgs.append(
            f"Zero-length CBAR element(s) detected: EID {zero_eids}. "
            "These produce a singular stiffness matrix and will cause the solver to fail."
        )

    # 2. SPC coverage
    has_any_spc = bool(bulk.spcs) or bool(bulk.spc1s)
    if not has_any_spc:
        if cc is not None and cc.sol == 144:
            # SOL 144 trim is restrained via SUPORT (free-flight r-set), not SPC;
            # an unconstrained-SPC model is valid here, so no warning.
            pass
        elif cc is None or cc.sol == 101:
            msgs.append(
                "No SPC or SPC1 constraints are defined. "
                "An unconstrained model has a singular stiffness matrix; SOL 101 will fail."
            )
        else:
            msgs.append(
                "No SPC or SPC1 constraints are defined. "
                "For SOL 103 this is valid (free-free analysis); "
                "the first 6 modes will be near-zero rigid-body modes."
            )
    elif cc is not None:
        for sc in cc.subcases:
            if sc.spc_sid is not None:
                if sc.spc_sid not in bulk.spcs and sc.spc_sid not in bulk.spc1s:
                    msgs.append(
                        f"Subcase {sc.subcase_id}: SPC SID {sc.spc_sid} is referenced "
                        "in case control but not found in bulk data."
                    )

    # 3. Unsupported load cards present (captured as parser warnings)
    _UNSUPPORTED_LOAD_CARDS = frozenset({
        "PLOAD", "PLOAD1", "PLOAD2", "PLOAD4",
        "RFORCE", "DLOAD", "TLOAD1", "TLOAD2",
        "RLOAD1", "RLOAD2", "ACCEL", "ACCEL1", "SLOAD",
    })
    found_unsupported: set = set()
    for msg in parse_warnings:
        for card in _UNSUPPORTED_LOAD_CARDS:
            if card in msg:
                found_unsupported.add(card)
    if found_unsupported:
        card_list = ", ".join(sorted(found_unsupported))
        msgs.append(
            f"Unsupported load card(s) present: {card_list}. "
            "These were ignored during parsing and do not contribute to the load vector."
        )

    # 4. Zero density for SOL 103
    if cc is not None and cc.sol == 103:
        zero_rho_mids = [m.mid for m in bulk.mat1s.values() if m.rho == 0.0]
        if zero_rho_mids:
            msgs.append(
                f"SOL 103: MAT1 MID={zero_rho_mids} have zero density (rho=0). "
                "The mass matrix will be zero for those elements, producing unreliable frequencies."
            )

    # 5. Units consistency heuristic
    e_vals = [m.E for m in bulk.mat1s.values() if m.E > 0.0]
    if len(e_vals) >= 2:
        ratio = max(e_vals) / min(e_vals)
        if ratio > 1000.0:
            msgs.append(
                f"Possible unit inconsistency: MAT1 Young's modulus (E) values span a "
                f"{ratio:.0f}× range across materials. "
                "Verify all inputs use the same consistent unit system."
            )

    return msgs


def _show_pre_solve_warnings(bulk: BulkData, cc) -> None:
    for msg in _get_pre_solve_warnings(bulk, cc, st.session_state._parse_warnings):
        st.warning(msg)


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
            results: dict = {}
            with st.spinner("Running SOL 101…"):
                for sc in cc.subcases:
                    results[sc.subcase_id] = run_sol101(bulk, sc)
            st.session_state.sol101_result = results
            st.session_state.sol103_result = None
            st.success(f"SOL 101 complete — {len(results)} subcase(s).")
        elif cc.sol == 103:
            from sbeam.solver.sol103 import run_sol103
            results = {}
            with st.spinner("Running SOL 103…"):
                for sc in cc.subcases:
                    results[sc.subcase_id] = run_sol103(bulk, sc)
            st.session_state.sol103_result = results
            st.session_state.sol101_result = None
            n = next(iter(results.values())).frequencies_hz.shape[0]
            st.success(f"SOL 103 complete — {n} modes, {len(results)} subcase(s).")
        elif cc.sol == 144:
            _run_sol144(bulk, cc)
        else:
            st.error(f"SOL {cc.sol} is not supported.")
    except Exception as exc:
        st.error(f"Solver error: {exc}")


def _run_sol144(bulk: BulkData, cc) -> None:
    """Run a SOL 144 deck, routing each subcase to trim / divergence / maneuver.

    Mirrors the solver routing in ``sbeam.main`` — build one AeroModel + AeroCache
    (shared across subcases / multi-Mach AICs) and dispatch per subcase.
    """
    from sbeam.aero.aero_model import build_aero_model
    from sbeam.assembly.load_vector import build_grid_index
    from sbeam.solver.sol144 import run_sol144_trim, run_sol144_diverg, AeroCache
    from sbeam.solver.maneuver_qs import run_maneuver_qs

    trim_results: dict = {}
    diverg_results: dict = {}
    maneuver_results: dict = {}
    with st.spinner("Running SOL 144…"):
        grid_index = build_grid_index(bulk)
        aero = build_aero_model(bulk, grid_index=grid_index)
        cache = AeroCache(bulk, grid_index, seed=aero)
        for sc in cc.subcases:
            if sc.mloads_sid is not None:
                maneuver_results[sc.subcase_id] = run_maneuver_qs(
                    bulk, sc, aero, aero_cache=cache)
            elif sc.diverg_sid is not None and sc.trim_sid is None:
                diverg_results[sc.subcase_id] = run_sol144_diverg(
                    bulk, sc, aero, aero_cache=cache)
            else:
                trim_results[sc.subcase_id] = run_sol144_trim(
                    bulk, sc, aero, aero_cache=cache)
                if sc.diverg_sid is not None:
                    diverg_results[sc.subcase_id] = run_sol144_diverg(
                        bulk, sc, aero, aero_cache=cache)

    st.session_state.aero_model_144 = aero
    st.session_state.sol144_result = trim_results or None
    st.session_state.sol144_diverg_result = diverg_results or None
    st.session_state.maneuver_result = maneuver_results or None
    st.session_state.sol101_result = None
    st.session_state.sol103_result = None
    n = len(trim_results) + len(diverg_results) + len(maneuver_results)
    st.success(f"SOL 144 complete — {n} subcase(s).")


def _render_f06_export(bulk: BulkData) -> None:
    """Show f06 export controls after a successful analysis."""
    from sbeam.results.f06_writer import (
        build_f06_sol101_text, build_f06_sol103_text,
        build_f06_sol144_text, build_f06_sol144_diverg_text,
    )

    cc = st.session_state.case_control
    sol101 = st.session_state.sol101_result
    sol103 = st.session_state.sol103_result
    sol144 = st.session_state.sol144_result
    sol144_div = st.session_state.sol144_diverg_result
    if cc is None or (sol101 is None and sol103 is None
                      and sol144 is None and sol144_div is None):
        return

    uploaded_name = st.session_state._uploaded_filename or "results.bdf"
    default_path = str(Path(os.getcwd()) / Path(uploaded_name).with_suffix(".f06").name)

    st.divider()
    st.subheader("Export F06")

    # Build combined f06 text for all subcases
    parts = []
    if sol101 is not None:
        for sc_id, result in sorted(sol101.items()):
            parts.append(build_f06_sol101_text(cc, bulk, result, sc_id))
    elif sol103 is not None:
        for sc_id, result in sorted(sol103.items()):
            parts.append(build_f06_sol103_text(cc, bulk, result, sc_id))
    else:
        for sc_id, result in sorted((sol144 or {}).items()):
            parts.append(build_f06_sol144_text(cc, bulk, result, sc_id))
        for sc_id, result in sorted((sol144_div or {}).items()):
            parts.append(build_f06_sol144_diverg_text(cc, bulk, result, sc_id))
    f06_text = "".join(parts)

    col1, col2 = st.columns([3, 1])
    with col1:
        out_path = st.text_input("Output path", value=default_path, key="f06_out_path")
    with col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Write F06", key="write_f06_btn"):
            try:
                Path(out_path).write_text(f06_text, encoding="utf-8")
                st.success(f"Written: {out_path}")
            except Exception as exc:
                st.error(f"Write failed: {exc}")

    stem = Path(uploaded_name).with_suffix(".f06").name
    st.download_button(
        label="Download F06",
        data=f06_text,
        file_name=stem,
        mime="text/plain",
        key="download_f06_btn",
    )


def _render_aero_tab(bulk: BulkData) -> None:
    col_ctrl, col_fig = st.columns([1, 3])

    with col_ctrl:
        alpha_deg = st.number_input("AoA α (°)", value=3.0, step=0.5, key="aero_alpha")
        beta_deg  = st.number_input("Sideslip β (°)", value=0.0, step=0.5, key="aero_beta")
        compute_btn = st.button("Compute Aero", type="primary", key="aero_compute")

    if compute_btn:
        with st.spinner("Building AIC and solving…"):
            aero_model = build_aero_model(bulk)
            alpha_rad = np.radians(alpha_deg)
            beta_rad  = np.radians(beta_deg)
            # Corrected solve on aero_model.ajj_inv_corr — any AIC correction
            # (WKK / WT1 / WT2) and Prandtl–Glauert are honoured, matching the
            # SOL 144 path; the W2GJ baseline normalwash (camber/twist/built-in
            # incidence) is folded into the RHS with the SOL 144 sign.
            result = solve_rigid_cl(
                aero_model.boxes, alpha_rad,
                beta=beta_rad,
                aeros=aero_model.aeros,
                wg=aero_model.wg,
                cp_operator=aero_model.ajj_inv_corr,
            )
            # Uncorrected baseline (raw VLM + Prandtl–Glauert at the same Mach and
            # the same W2GJ wg) — only when a correction card is present, so there
            # is something to overlay; otherwise the two solves coincide.
            if bulk.wkks or bulk.aecorrs:
                result_unc = solve_rigid_cl(
                    aero_model.boxes, alpha_rad,
                    beta=beta_rad,
                    aeros=aero_model.aeros,
                    wg=aero_model.wg,
                    cp_operator=None,
                    mach=aero_model.mach,
                )
            else:
                result_unc = None
        st.session_state["aero_model"] = aero_model
        st.session_state["aero_result"] = result
        st.session_state["aero_result_unc"] = result_unc

    aero_model = st.session_state["aero_model"]
    aero_result = st.session_state["aero_result"]
    aero_result_unc = st.session_state["aero_result_unc"]

    with col_ctrl:
        show_normals = st.checkbox(
            "Show surface normals", value=False, key="aero_show_normals"
        )
        # Cp view toggle — only meaningful when an uncorrected baseline exists.
        cp_view = "Corrected"
        if aero_result is not None and aero_result_unc is not None:
            cp_view = st.radio(
                "Cp view", ["Corrected", "Uncorrected", "Δ (corr − uncorr)"],
                key="aero_cp_view",
                help="Switch the 3D box pressure and the span-load curves between the "
                     "corrected solve, the uncorrected baseline, and their difference.",
            )
        if aero_result is not None:
            st.metric("CL (wind)", fmt(aero_result.get('CL_wind', aero_result['CL'])))
            st.metric("CD (induced)",
                      fmt(aero_result.get('CD_wind', aero_result.get('CDi', 0.0))))
            st.metric("CZ (body)", fmt(aero_result.get('CZ', aero_result['CL'])))
            st.metric("CY", fmt(aero_result.get('CY', 0.0)))
            st.metric("CM", fmt(aero_result['CM']))
            st.metric("Boxes", len(aero_model.boxes))
            st.caption(
                "CL/CD are **wind-axis** (⊥ / ∥ to U∞); CZ is the **body-axis** "
                "vertical-force coefficient. CL = CZ·cosα − CX·sinα (equal only at "
                "α ≈ 0). CD is the Trefftz induced drag."
            )
            if aero_model.wg is not None and np.any(aero_model.wg):
                st.caption(
                    "ℹ️ W2GJ baseline incidence (camber/twist) folded into the "
                    "solve — CL/cp include the built-in twist."
                )
            if bulk.wkks or bulk.aecorrs:
                methods = (["WKK"] if bulk.wkks else []) + \
                    sorted({c.method for c in bulk.aecorrs.values()})
                st.caption(
                    f"ℹ️ AIC correction ({', '.join(methods)}) applied — CL/CM/cp "
                    "reflect the corrected operator."
                )

    # Resolve the displayed cp field and span-plot mode from the Cp-view toggle.
    cp_corr = aero_result["cp"] if aero_result is not None else None
    cp_unc = aero_result_unc["cp"] if aero_result_unc is not None else None
    disp_cp, cp_cmid, cp_title, span_mode = cp_corr, None, "Cp", "corrected"
    if cp_unc is not None and aero_result is not None:
        if cp_view == "Uncorrected":
            disp_cp, span_mode = cp_unc, "uncorrected"
        elif cp_view.startswith("Δ"):
            disp_cp, cp_cmid, cp_title, span_mode = cp_corr - cp_unc, 0.0, "ΔCp", "diff"

    with col_fig:
        if aero_model is not None:
            fig = build_aero_box_figure(
                bulk, aero_model, cp=disp_cp, show_normals=show_normals, strip=False,
                cp_cmid=cp_cmid, cp_title=cp_title,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Set parameters and press Compute Aero to visualise the panel mesh.")

    # ---- Full-width results below the 3D view -------------------------------
    if aero_result is not None and aero_model is not None:
        st.markdown("#### Spanwise loading")
        if cp_unc is not None:
            if span_mode == "diff":
                st.caption("Δ = corrected − uncorrected (per strip).")
            elif span_mode == "uncorrected":
                st.caption("Uncorrected VLM (raw AIC + Prandtl–Glauert).")
            else:
                st.caption(
                    "Solid = corrected · dashed = uncorrected VLM "
                    "(raw AIC + Prandtl–Glauert)."
                )
        # Per-surface show/hide — thins a busy multi-surface plot. Stale stored
        # selections (from a previous model) are filtered to the current surfaces.
        surf_eids = sorted({b.caero_eid for b in aero_model.boxes})
        selected = surf_eids
        if len(surf_eids) > 1:
            picked = st.multiselect(
                "Show surfaces", surf_eids, default=surf_eids,
                format_func=lambda e: f"CAERO {e}", key="aero_span_surfaces",
            )
            selected = [e for e in surf_eids if e in picked]
        if not selected:
            st.info("Select at least one surface to plot.")
        else:
            st.plotly_chart(
                build_span_loading_figure(
                    aero_model.boxes, cp_corr, cp_unc=cp_unc,
                    aeros=aero_model.aeros, mode=span_mode, surfaces=selected,
                ),
                use_container_width=True,
            )

        # Rigid stability & control derivatives — all airplane rigid derivatives.
        if bulk.aeros is not None:
            st.markdown("#### Rigid stability & control derivatives")
            naming_label = st.radio(
                "Naming", ["Aero (α, Cm…)", "Raw (ANGLEA, CMY…)"],
                horizontal=True, key="aero_deriv_naming",
            )
            naming = "aero" if naming_label.startswith("Aero") else "raw"
            deriv_df = rigid_derivative_table(aero_model, bulk, naming=naming)
            if deriv_df is not None:
                st.caption(
                    "Per radian / per unit label, rigid (u_a = 0). Rows: "
                    "α, β, roll p, pitch q, yaw r + AESURF controls."
                )
                st.dataframe(style_numeric(deriv_df), use_container_width=True)

        # Per-surface coefficient breakdown (multi-surface decks).  Per-surface
        # contributions are body-axis (CZ vertical / CY side), so they sum to the
        # body-axis totals; the wind-axis CL above is the whole-aircraft rotation.
        per_surf = aero_result.get("per_surface", {})
        if len(per_surf) > 1:
            st.markdown("#### Per-surface coefficients (body axis)")
            rows = []
            for eid, info in sorted(per_surf.items()):
                if info["surface_type"] == "lift":
                    rows.append({"EID": eid, "Type": "lift",
                                 "CZ": fmt(info['CL']), "CY": "—",
                                 "CM": fmt(info['CM'])})
                else:
                    rows.append({"EID": eid, "Type": "sideforce",
                                 "CZ": "—", "CY": fmt(info['CY']),
                                 "CM": "—"})
            st.table(rows)


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
            file_id = (uploaded.name, uploaded.size)
            if file_id != st.session_state._uploaded_file_id:
                _handle_upload(uploaded)
                st.session_state._uploaded_file_id = file_id

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
    _has_aero = bool(bulk.caero1s)
    if _has_aero:
        tab_model, tab_cc, tab_results, tab_aero, tab_aero_corr = st.tabs(
            ["Model", "Case Control", "Results", "Aero", "Aero Correction"]
        )
    else:
        tab_model, tab_cc, tab_results = st.tabs(["Model", "Case Control", "Results"])
        tab_aero = None
        tab_aero_corr = None

    with tab_model:
        _show_parse_summary(bulk)
        _show_warnings()
        show_forces = st.checkbox("Show applied forces", value=True, key="model_show_forces")
        fig = build_model_figure(
            bulk,
            selected_gid=st.session_state.selected_gid,
            selected_eid=st.session_state.selected_eid,
            load_sid=_active_load_sid() if show_forces else None,
        )
        st.plotly_chart(fig, use_container_width=True)
        _show_model_data_tabs(bulk)

    with tab_cc:
        render_case_control_panel(bulk, on_launch=lambda: _run_analysis(bulk))

    with tab_results:
        st.subheader("Analysis")
        cc_for_val = st.session_state.case_control
        _show_pre_solve_warnings(bulk, cc_for_val)
        if st.button("Run Analysis", type="primary"):
            _run_analysis(bulk)

        if st.session_state.sol101_result is not None:
            render_sol101_results(bulk, st.session_state.sol101_result)
            _render_f06_export(bulk)

        elif st.session_state.sol103_result is not None:
            render_sol103_results(bulk, st.session_state.sol103_result)
            _render_f06_export(bulk)

        elif (st.session_state.sol144_result is not None
              or st.session_state.sol144_diverg_result is not None
              or st.session_state.maneuver_result is not None):
            render_sol144_results(
                bulk,
                st.session_state.sol144_result,
                st.session_state.sol144_diverg_result,
                st.session_state.maneuver_result,
            )
            _render_f06_export(bulk)

        else:
            cc = st.session_state.case_control
            if cc is not None:
                st.info(f"Press Run Analysis to execute SOL {cc.sol}.")
            else:
                st.info("Define a case control in the Case Control tab, then run the analysis.")

    if tab_aero is not None:
        with tab_aero:
            _render_aero_tab(bulk)

    if tab_aero_corr is not None:
        with tab_aero_corr:
            render_aero_correction_tab(bulk)


if __name__ == "__main__":
    main()
