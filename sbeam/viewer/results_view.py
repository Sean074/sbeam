"""Results display for sbeam viewer — Steps 21 and 22."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.results.results import Sol101Result, Sol103Result
from sbeam.assembly.load_vector import build_grid_index
from sbeam.viewer.geometry import build_deformed_figure, build_mode_figure


# ---------------------------------------------------------------------------
# SOL 101 results display (Step 21)
# ---------------------------------------------------------------------------

def render_sol101_results(bulk: BulkData, result: Sol101Result, load_sid: Optional[int] = None) -> None:
    """Display deformed shape, scale slider, and results tables for SOL 101."""
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
        st.dataframe(pd.DataFrame(rows), width="stretch")

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
            st.dataframe(pd.DataFrame(rows), width="stretch")
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
            st.dataframe(pd.DataFrame(rows), width="stretch")
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
            st.dataframe(pd.DataFrame(rows), width="stretch")
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
            st.dataframe(pd.DataFrame(rows), width="stretch")
        else:
            st.info("No CBUSH forces.")


# ---------------------------------------------------------------------------
# SOL 103 results display (Step 22)
# ---------------------------------------------------------------------------

def render_sol103_results(bulk: BulkData, result: Sol103Result) -> None:
    """Display mode shapes and frequency table for SOL 103."""
    grid_index = build_grid_index(bulk)
    n_modes = len(result.frequencies_hz)

    st.subheader("Natural frequencies")

    # Frequency summary table
    freq_rows = []
    for i, (freq, lam) in enumerate(zip(result.frequencies_hz, result.eigenvalues), start=1):
        omega = 2.0 * np.pi * freq
        freq_rows.append({"Mode": i, "Freq (Hz)": freq, "ω (rad/s)": omega, "λ (ω²)": lam})
    st.dataframe(pd.DataFrame(freq_rows), width="stretch")

    st.subheader("Mode shape")

    mode_labels = [f"Mode {i + 1}  —  {result.frequencies_hz[i]:.4g} Hz" for i in range(n_modes)]
    mode_sel = st.selectbox("Select mode", range(n_modes), format_func=lambda i: mode_labels[i])

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
        "Mode shape scale",
        min_value=0.0,
        max_value=float(suggested * 10),
        value=float(suggested),
        format="%.2g",
        key="mode_scale",
    )

    fig = build_mode_figure(bulk, phi, grid_index, scale=scale, freq_hz=freq)
    st.plotly_chart(fig, use_container_width=True)

    # Modal mass fractions (translational DOFs)
    st.subheader("Modal participation")
    _render_modal_mass_chart(bulk, result, grid_index)


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
