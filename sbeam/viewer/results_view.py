"""Results display for sbeam viewer — Steps 21 and 22."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import Sol103Result
from sbeam.assembly.load_vector import build_grid_index
from sbeam.viewer.geometry import build_deformed_figure, build_mode_figure
from sbeam.viewer.aero_view import build_aero_box_figure
from sbeam.viewer.format_utils import fmt, style_numeric


# ---------------------------------------------------------------------------
# SOL 101 results display (Step 21)
# ---------------------------------------------------------------------------

def render_sol101_results(bulk: BulkData, results: dict) -> None:
    """Display deformed shape, scale slider, and results tables for SOL 101."""
    subcase_ids = sorted(results.keys())
    if len(subcase_ids) > 1:
        sel_id = st.selectbox("Subcase", subcase_ids, key="results_sc_sel")
    else:
        sel_id = subcase_ids[0]
    result = results[sel_id]

    cc = st.session_state.get("case_control")
    load_sid: Optional[int] = None
    if cc is not None:
        for sc in cc.subcases:
            if sc.subcase_id == sel_id:
                load_sid = sc.load_sid
                break

    grid_index = build_grid_index(bulk)
    gids_sorted = sorted(bulk.grids.keys())

    st.subheader("Deformed shape")

    max_disp = float(np.max(np.abs(result.displacements))) if result.displacements.size else 1.0
    if max_disp == 0.0:
        max_disp = 1.0

    # Suggest a scale so the deformation is ~10% of model span
    if bulk.grids:
        coords = [(g.x, g.y, g.z) for g in bulk.grids.values()]
        span = max(
            max(c[i] for c in coords) - min(c[i] for c in coords)
            for i in range(3)
        )
        span = span if span > 0 else 1.0
    else:
        span = 1.0
    suggested = span * 0.1 / max_disp
    scale = st.slider(
        "Deformation scale",
        min_value=0.0,
        max_value=float(suggested * 10),
        value=float(suggested),
        format="%.2g",
        key="sol101_deform_scale",
    )

    show_forces = st.checkbox("Show applied forces", value=True, key="sol101_show_forces")
    fig = build_deformed_figure(bulk, result.displacements, grid_index, scale, load_sid=load_sid if show_forces else None)
    st.plotly_chart(fig, use_container_width=True)

    # Results tables
    tab_disp, tab_rxn, tab_force, tab_stress, tab_cbush = st.tabs(
        ["Displacements", "Reactions", "Bar Forces", "Bar Stresses", "CBUSH Forces"]
    )

    with tab_disp:
        rows = []
        for gid in gids_sorted:
            i = grid_index[gid]
            base = 6 * i
            d = result.displacements
            rows.append({
                "GID": gid,
                "Tx": d[base],
                "Ty": d[base + 1],
                "Tz": d[base + 2],
                "Rx": d[base + 3],
                "Ry": d[base + 4],
                "Rz": d[base + 5],
            })
        st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")

    with tab_rxn:
        if result.reactions:
            rows = []
            for gid in sorted(result.reactions.keys()):
                r = result.reactions[gid]
                rows.append({
                    "GID": gid,
                    "Fx": r[0], "Fy": r[1], "Fz": r[2],
                    "Mx": r[3], "My": r[4], "Mz": r[5],
                })
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No SPC reactions.")

    with tab_force:
        if result.bar_forces:
            rows = []
            for eid in sorted(result.bar_forces.keys()):
                bf = result.bar_forces[eid]
                rows.append({
                    "EID": eid,
                    "Axial": bf.axial,
                    "Shear1": bf.shear1,
                    "Shear2": bf.shear2,
                    "Torque": bf.torque,
                    "BM1_A": bf.bm1_a,
                    "BM2_A": bf.bm2_a,
                    "BM1_B": bf.bm1_b,
                    "BM2_B": bf.bm2_b,
                })
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No bar forces.")

    with tab_stress:
        if result.bar_stresses:
            rows = []
            for eid in sorted(result.bar_stresses.keys()):
                bs = result.bar_stresses[eid]
                rows.append({
                    "EID": eid,
                    "Axial": bs.axial,
                    "SA_C": bs.sa,
                    "SB_C": bs.sb,
                    "SA_D": bs.sa_d,
                    "SB_D": bs.sb_d,
                    "SA_E": bs.sa_e,
                    "SB_E": bs.sb_e,
                    "SA_F": bs.sa_f,
                    "SB_F": bs.sb_f,
                })
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No bar stresses.")

    with tab_cbush:
        if result.cbush_forces:
            rows = []
            for eid in sorted(result.cbush_forces.keys()):
                f = result.cbush_forces[eid]
                rows.append({
                    "EID": eid,
                    "F1 (global)": f[0],
                    "F2 (global)": f[1],
                    "F3 (global)": f[2],
                    "M1 (global)": f[3],
                    "M2 (global)": f[4],
                    "M3 (global)": f[5],
                })
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")
        else:
            st.info("No CBUSH forces.")


# ---------------------------------------------------------------------------
# SOL 103 results display (Step 22)
# ---------------------------------------------------------------------------

def render_sol103_results(bulk: BulkData, results: dict) -> None:
    """Display mode shapes and frequency table for SOL 103."""
    subcase_ids = sorted(results.keys())
    if len(subcase_ids) > 1:
        sel_id = st.selectbox("Subcase", subcase_ids, key="results_sc_sel")
    else:
        sel_id = subcase_ids[0]
    result = results[sel_id]

    grid_index = build_grid_index(bulk)
    n_modes = len(result.frequencies_hz)

    _CAMERA_PRESETS = {
        "Isometric": dict(eye=dict(x=1.5, y=1.5, z=1.5)),
        "+X view": dict(eye=dict(x=2.5, y=0.0, z=0.2)),
        "-X view": dict(eye=dict(x=-2.5, y=0.0, z=0.2)),
        "+Y view": dict(eye=dict(x=0.0, y=2.5, z=0.2)),
        "-Y view": dict(eye=dict(x=0.0, y=-2.5, z=0.2)),
        "+Z view (top)": dict(eye=dict(x=0.0, y=0.0, z=2.5)),
        "-Z view (bottom)": dict(eye=dict(x=0.0, y=0.0, z=-2.5)),
        "XZ plane": dict(eye=dict(x=0.0, y=2.5, z=0.5)),
        "YZ plane": dict(eye=dict(x=2.5, y=0.0, z=0.5)),
    }

    ctrl_col, plot_col = st.columns([3, 7])

    with ctrl_col:
        st.subheader("Mode shape")

        mode_labels = [f"Mode {i + 1}  —  {result.frequencies_hz[i]:.4g} Hz" for i in range(n_modes)]
        mode_sel = st.selectbox("Select mode", range(n_modes), format_func=lambda i: mode_labels[i], key="mode_sel")

        freq = result.frequencies_hz[mode_sel]
        phi = result.mode_shapes[:, mode_sel]
        max_comp = float(np.max(np.abs(phi))) if phi.size else 1.0
        if max_comp == 0.0:
            max_comp = 1.0

        if bulk.grids:
            coords = [(g.x, g.y, g.z) for g in bulk.grids.values()]
            span = max(
                max(c[i] for c in coords) - min(c[i] for c in coords)
                for i in range(3)
            )
            span = span if span > 0 else 1.0
        else:
            span = 1.0
        suggested = span * 0.2 / max_comp

        scale = st.slider(
            "Scale",
            min_value=0.0,
            max_value=float(suggested * 10),
            value=float(suggested),
            format="%.2g",
            key="mode_scale",
        )
        phase_pct = st.slider(
            "Phase (°)  (90°=+max, 270°=−max)",
            min_value=0,
            max_value=360,
            value=90,
            key="mode_phase",
        )
        view_sel = st.selectbox(
            "Camera",
            list(_CAMERA_PRESETS.keys()),
            key="mode_camera_preset",
        )
        chart_height = st.slider(
            "Height (px)",
            min_value=400,
            max_value=1400,
            value=580,
            step=50,
            key="mode_chart_height",
        )

        # Frequency table in collapsible section
        freq_rows = []
        for i, (f, lam) in enumerate(zip(result.frequencies_hz, result.eigenvalues), start=1):
            omega = 2.0 * np.pi * f
            freq_rows.append({"Mode": i, "Freq (Hz)": f, "ω (rad/s)": omega, "λ (ω²)": lam})
        with st.expander("Natural frequencies", expanded=False):
            st.dataframe(style_numeric(pd.DataFrame(freq_rows)), width="stretch")

        with st.expander("Modal participation", expanded=False):
            _render_modal_mass_chart(bulk, result, grid_index)

    camera = _CAMERA_PRESETS[view_sel]
    fig = build_mode_figure(
        bulk, phi, grid_index,
        scale=scale, freq_hz=freq,
        camera=camera, height=chart_height,
        phase=phase_pct / 360.0,
    )

    with plot_col:
        st.plotly_chart(fig, use_container_width=True)


def _render_modal_mass_chart(
    bulk: BulkData,
    result: Sol103Result,
    grid_index: dict,
) -> None:
    """Bar chart of modal mass fractions for translational DOFs."""
    try:
        from sbeam.assembly.mass_matrix import assemble_global_mass
        M = assemble_global_mass(bulk)
        n_modes = result.mode_shapes.shape[1]
        fracs = []
        for i in range(n_modes):
            phi = result.mode_shapes[:, i]
            # Effective mass = (phi^T M e)^2 / total_mass where e is unit excitation
            # Use Tx DOFs sum as a scalar proxy
            tx_dofs = [6 * grid_index[gid] for gid in bulk.grids]
            e_tx = np.zeros(len(phi))
            for d in tx_dofs:
                e_tx[d] = 1.0
            total_mass_tx = float(e_tx @ M @ e_tx)
            if total_mass_tx > 0:
                eff = float((phi @ M @ e_tx) ** 2) / total_mass_tx
            else:
                eff = 0.0
            fracs.append(eff)

        import plotly.graph_objects as go
        labels = [f"Mode {i + 1}" for i in range(n_modes)]
        fig = go.Figure(go.Bar(x=labels, y=fracs))
        fig.update_layout(
            xaxis_title="Mode",
            yaxis_title="Effective mass fraction (Tx)",
            height=300,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        st.caption("Modal mass fractions unavailable.")


# ---------------------------------------------------------------------------
# SOL 144 results display (Step 57)
# ---------------------------------------------------------------------------

def _model_span(bulk: BulkData) -> float:
    """Largest model extent across X/Y/Z (used to scale deflection sliders)."""
    if not bulk.grids:
        return 1.0
    coords = [(g.x, g.y, g.z) for g in bulk.grids.values()]
    span = max(
        max(c[i] for c in coords) - min(c[i] for c in coords)
        for i in range(3)
    )
    return span if span > 0 else 1.0


def render_sol144_results(
    bulk: BulkData,
    trim_results: Optional[dict] = None,
    diverg_results: Optional[dict] = None,
    maneuver_results: Optional[dict] = None,
) -> None:
    """Display SOL 144 trim / divergence / maneuver results (Step 57)."""
    trim_results = trim_results or {}
    diverg_results = diverg_results or {}
    maneuver_results = maneuver_results or {}

    sc_ids = sorted(set(trim_results) | set(diverg_results) | set(maneuver_results))
    if not sc_ids:
        st.info("No SOL 144 results to display.")
        return

    if len(sc_ids) > 1:
        sel_id = st.selectbox("Subcase", sc_ids, key="sol144_sc_sel")
    else:
        sel_id = sc_ids[0]

    if sel_id in trim_results:
        _render_sol144_trim(bulk, trim_results[sel_id])
    if sel_id in diverg_results:
        _render_sol144_diverg(diverg_results[sel_id])
    if sel_id in maneuver_results:
        _render_sol144_maneuver(bulk, maneuver_results[sel_id])


def _render_sol144_trim(bulk: BulkData, result) -> None:
    """Trim variables, stability derivatives, q_div, hinge/monitor loads, deflected shape."""
    # ---- Trim summary metrics ----
    st.subheader("Trim solution")
    cols = st.columns(6)
    cols[0].metric("Dynamic pressure q", fmt(result.q))
    cols[1].metric("Mach", fmt(result.mach))
    cols[2].metric("CZ (body)", fmt(result.total_cl))
    cols[3].metric("CL (wind)",
                   fmt(getattr(result, 'total_cl_wind', result.total_cl)))
    cols[4].metric("Total CMy", fmt(result.total_cm))
    cols[5].metric("Trim mode", result.trim_mode)

    # ---- Trim variables ----
    trim_card = bulk.trims.get(result.trim_sid)
    prescribed = {k.upper() for k in trim_card.vars.keys()} if trim_card else set()
    tv_rows = [
        {
            "Label": label,
            "Type": "PRESCRIBED" if label.upper() in prescribed else "FREE",
            "Value": result.trim_vars[label],
        }
        for label in sorted(result.trim_vars.keys())
    ]
    st.markdown("**Trim variables**")
    st.dataframe(style_numeric(pd.DataFrame(tv_rows)), width="stretch")

    # ---- Stability & control derivatives (rigid + restrained + unrestrained) ----
    unrest_all = getattr(result, "unrestrained_derivs", None) or {}
    deriv_rows = []
    for label in sorted(result.trim_vars.keys()):
        rg = result.rigid_derivs.get(label, {})
        el = result.restrained_derivs.get(label, {})
        un = unrest_all.get(label)
        deriv_rows.append({
            "Label": label,
            "CZ (rigid)":  rg.get("CZ", 0.0),
            "CMY (rigid)": rg.get("CMY", 0.0),
            "CX (rigid)":  rg.get("CX", 0.0),
            "CY (rigid)":  rg.get("CY", 0.0),
            "CMX (rigid)": rg.get("CMX", 0.0),
            "CMZ (rigid)": rg.get("CMZ", 0.0),
            "CZ (restrained)":  el.get("CZ", 0.0),
            "CMY (restrained)": el.get("CMY", 0.0),
            "CMX (restrained)": el.get("CMX", 0.0),
            "CMZ (restrained)": el.get("CMZ", 0.0),
            # URDD acceleration columns have no unrestrained entry (they are
            # the mean-axis ü_r unknowns) — shown as None/blank.
            "CZ (unrestrained)":  un.get("CZ") if un else None,
            "CMY (unrestrained)": un.get("CMY") if un else None,
        })
    st.markdown("**Stability & control derivatives** (rigid vs elastic-restrained "
                "vs elastic-unrestrained/mean-axis)")
    st.dataframe(style_numeric(pd.DataFrame(deriv_rows)), width="stretch")

    # ---- Divergence readout ----
    st.markdown("**Aerodynamic divergence**")
    if result.q_div is None:
        st.info("No divergence found (q-div → ∞).")
    else:
        ratio = result.q / result.q_div if result.q_div else 0.0
        dc = st.columns(2)
        dc[0].metric("Critical q-div", fmt(result.q_div))
        dc[1].metric("q / q-div", fmt(ratio))

    # ---- Hinge moments ----
    if result.hinge_moments:
        st.markdown("**Hinge-moment derivatives** (about each AESURF cid1 hinge axis)")
        for surf in sorted(result.hinge_moments):
            entry = result.hinge_moments[surf]
            rows = [
                {"Trim variable": k, "d(HM)/d(var)": result.q * entry[k]}
                for k in sorted(k for k in entry if k != "total")
            ]
            rows.append({"Trim variable": "TOTAL (trim)", "d(HM)/d(var)": result.q * entry["total"]})
            st.caption(f"Surface: {surf}")
            st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")

    # ---- Monitor-point integrated loads ----
    if result.monitor_loads:
        st.markdown("**Monitor-point integrated loads**")
        rows = []
        for name in sorted(result.monitor_loads):
            ml = result.monitor_loads[name]
            t = ml.totals
            rows.append({
                "Monitor": name, "Label": ml.label, "Type": ml.mtype,
                "Fx": t[0], "Fy": t[1], "Fz": t[2],
                "Mx": t[3], "My": t[4], "Mz": t[5],
            })
        st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")

    # ---- Maneuver closure (balanced-maneuver net load resultant) ----
    if result.maneuver_closure is not None:
        st.markdown("**Maneuver load closure** (net aero+inertia resultant; ≈0 when balanced)")
        c = result.maneuver_closure
        cc = st.columns(6)
        for i, lab in enumerate(["Fx", "Fy", "Fz", "Mx", "My", "Mz"]):
            cc[i].metric(lab, fmt(c[i]))

    # ---- Deflected shape + canted box cp ----
    _render_sol144_deflected(bulk, result)


def _render_sol144_deflected(bulk: BulkData, result) -> None:
    """Deformed structure overlay + spline-deflected, canted aero box cp mesh."""
    st.subheader("Deflected shape & aerodynamic boxes")
    grid_index = build_grid_index(bulk)

    max_disp = float(np.max(np.abs(result.displacements))) if result.displacements.size else 1.0
    if max_disp == 0.0:
        max_disp = 1.0
    suggested = _model_span(bulk) * 0.1 / max_disp
    scale = st.slider(
        "Deflection scale",
        min_value=0.0,
        max_value=float(suggested * 10),
        value=float(suggested),
        format="%.2g",
        key="sol144_deform_scale",
    )

    # Deformed structure
    fig_struct = build_deformed_figure(bulk, result.displacements, grid_index, scale)
    st.plotly_chart(fig_struct, use_container_width=True)

    # Spline-deflected aero box mesh + cp (canted geometry — corners are z-bearing)
    aero_model = st.session_state.get("aero_model_144")
    if aero_model is None:
        st.caption("Aero box mesh unavailable (no aero model cached).")
        return

    box_disp = None
    if aero_model.g_disp is not None:
        box_disp = scale * (aero_model.g_disp @ result.displacements)
    elif result.displacements.size:
        st.caption("No spline cards — aero boxes shown at jig (undeflected) position.")

    cp = result.box_cp  # None unless AEROF/APRES requested
    if cp is None:
        st.caption("Per-box ΔCp shown only when AEROF/APRES is requested in case control.")
    fig_aero = build_aero_box_figure(bulk, aero_model, cp=cp, box_disp=box_disp)
    st.plotly_chart(fig_aero, use_container_width=True)


def _render_sol144_diverg(result) -> None:
    """Per-Mach divergence roots table (Step 55 DIVERG sweep)."""
    st.subheader("Aerodynamic divergence sweep")
    has_v = result.rhoref > 0.0
    for mr in result.mach_results:
        st.markdown(f"**Mach {mr.mach:.4g}**")
        if not mr.roots:
            st.info("No divergence found (no positive real root).")
            continue
        rows = []
        for i, root in enumerate(mr.roots, start=1):
            row = {"Root": i, "q-div": root.q_div}
            if has_v and root.v_div is not None:
                row["V-div"] = root.v_div
            rows.append(row)
        st.dataframe(style_numeric(pd.DataFrame(rows)), width="stretch")


def _render_sol144_maneuver(bulk: BulkData, result) -> None:
    """Phase G0 transient maneuver time histories + deflected shape at a sample."""
    import plotly.graph_objects as go

    st.subheader("Transient maneuver loads")
    cols = st.columns(4)
    cols[0].metric("Dynamic pressure q", fmt(result.q))
    cols[1].metric("Mach", fmt(result.mach))
    cols[2].metric("Output samples", len(result.steps))
    cols[3].metric("Critical sample", result.crit_index)

    times = result.times
    fz = [s.Fz_aero for s in result.steps]
    my = [s.My_aero for s in result.steps]
    net = [float(np.max(np.abs(s.net_loads))) if s.net_loads.size else 0.0 for s in result.steps]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=times, y=fz, mode="lines", name="Fz aero"))
    fig.add_trace(go.Scatter(x=times, y=my, mode="lines", name="My aero"))
    fig.add_trace(go.Scatter(x=times, y=net, mode="lines", name="max |net load|"))
    if 0 <= result.crit_index < len(times):
        fig.add_vline(x=float(times[result.crit_index]), line=dict(color="#cc2222", dash="dash"))
    fig.update_layout(
        xaxis_title="Time", yaxis_title="Load",
        height=350, margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig, use_container_width=True)

    n = len(result.steps)
    idx = st.slider(
        "Sample", min_value=0, max_value=max(n - 1, 0),
        value=int(result.crit_index) if n else 0, key="sol144_man_step",
    )
    step = result.steps[idx]
    grid_index = build_grid_index(bulk)
    max_disp = float(np.max(np.abs(step.displacements))) if step.displacements.size else 1.0
    if max_disp == 0.0:
        max_disp = 1.0
    suggested = _model_span(bulk) * 0.1 / max_disp
    scale = st.slider(
        "Deflection scale", min_value=0.0, max_value=float(suggested * 10),
        value=float(suggested), format="%.2g", key="sol144_man_scale",
    )
    fig_struct = build_deformed_figure(bulk, step.displacements, grid_index, scale)
    st.plotly_chart(fig_struct, use_container_width=True)
