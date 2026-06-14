"""Aero Correction tab — CFD/test section data → W2GJ + AECORR(WT2) cards.

Front end (Option A GUI) over ``sbeam.aero.section_data`` / ``section_correction``: the
user downloads a mesh-seeded CSV template, fills it with section lift/moment coefficients,
uploads it, picks a flight **condition** (Mach + operating incidence), and builds one
**W2GJ (camber/zero-α offset) + AECORR/WT2 (slope & a.c.)** card pair per lifting surface.
The cards can be injected into the in-session model — the Aero tab keys off
``bulk.wkks``/``bulk.aecorrs`` so the corrected solve runs with no further wiring — and/or
downloaded as a bulk-data snippet.

v1 limits (inherited from the engine): exact-Mach match (no Mach interpolation); one
operating region per surface (the region whose [a_lo, a_hi] contains the incidence).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from sbeam.model.bulk_data import BulkData
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd
from sbeam.aero.section_correction import cards_to_bdf
from sbeam.viewer.aero_view import build_section_correction_figure

# Reserved SID range for tool-generated cards (kept clear of typical user SIDs so the
# Apply step can find and replace its own cards on a rebuild).
_W2GJ_BASE = 9001
_AECORR_BASE = 9101

_SCHEMA_HELP = """\
One row per **surface × span-station × Mach × region** (tidy / long format):

| column | meaning |
|--------|---------|
| `caero` | CAERO1 EID the row applies to |
| `eta`   | span fraction within that CAERO1, 0 (root) … 1 (tip) |
| `mach`  | freestream Mach for this block (exact match — no interpolation) |
| `var`   | incidence variable: `ALPHA` (lift surface) or `BETA` (vertical) |
| `a_lo` / `a_hi` | region incidence bounds (deg) — validity range |
| `cn_a`  | section normal-force-curve slope dCn/d(var) **[per degree]** |
| `a0`    | zero-normal-force incidence (deg) |
| `cm_a`  | section pitch-moment slope dCm/d(var) about `xref` [per degree] |
| `cm0`   | section pitch moment at zero incidence (nose-up +) |
| `xref`  | moment reference as a chord fraction (0.25 = ¼-chord) |

Coefficients are **local-chord** normalised (airfoil-polar convention). Pitching moment is
**nose-up positive**.
"""


def _template_csv(aero_model) -> str:
    """Mesh-seeded starter table covering every CAERO1 surface, as CSV text."""
    eids = sorted({b.caero_eid for b in aero_model.boxes})
    frames = [sd.template_dataframe(aero_model.boxes, eid) for eid in eids]
    df = (pd.concat(frames, ignore_index=True) if frames
          else pd.DataFrame(columns=sd.COLUMNS))
    return df.to_csv(index=False)


def _warn_conflicts(bulk: BulkData, eids: list) -> None:
    """Surface correction-card clashes that ``build_aero_model`` would resolve silently."""
    own = st.session_state.get("aero_corr_sids", set())
    for eid in eids:
        if any(c.caero_eid == eid for c in bulk.wkks.values()):
            st.warning(
                f"CAERO {eid}: a WKK card is already in the model — build_aero_model applies "
                "WKK before WT2, so the generated WT2 would be ignored. Remove the WKK to use "
                "this correction."
            )
        clashing = [c.sid for c in bulk.aecorrs.values()
                    if c.caero_eid == eid and c.method == "WT2" and c.sid not in own]
        if clashing:
            st.warning(
                f"CAERO {eid}: a non-generated WT2 AECORR (sid {clashing}) is already present; "
                "applying adds another WT2 on the same surface."
            )


def _apply_cards(bulk: BulkData, res) -> int:
    """Inject the generated W2GJ/AECORR pairs into the in-session model.

    Removes any cards this tool injected on a previous build (tracked SIDs), adds the new
    pairs, and clears the Aero-tab results so the corrected solve recomputes.
    """
    for sid in st.session_state.get("aero_corr_sids", set()):
        bulk.w2gjs.pop(sid, None)
        bulk.aecorrs.pop(sid, None)
    new_sids: set = set()
    for _eid, (w2, ac) in res.correction.cards.items():
        bulk.w2gjs[w2.sid] = w2
        bulk.aecorrs[ac.sid] = ac
        new_sids.update((w2.sid, ac.sid))
    st.session_state.aero_corr_sids = new_sids
    # Force the Aero tab to rebuild the operator with the new cards.
    st.session_state.aero_model = None
    st.session_state.aero_result = None
    st.session_state.aero_result_unc = None
    return len(res.correction.cards)


def render_aero_correction_tab(bulk: BulkData) -> None:
    st.subheader("Aero correction — section force/moment cards from CFD / test data")
    st.caption(
        "Build W2GJ (camber / zero-α offset) + AECORR/WT2 (slope & a.c.) correction cards "
        "from a table of section coefficients for one flight condition (Mach + incidence), "
        "then add them to the model so the **Aero** tab runs the corrected solve."
    )

    if not bulk.caero1s:
        st.info("No CAERO1 surfaces in this model.")
        return

    if st.session_state.get("aero_corr_model") is None:
        st.session_state.aero_corr_model = build_aero_model(bulk)
    aero_model = st.session_state.aero_corr_model

    # ---- 1 · Section-data table ----------------------------------------------
    st.markdown("#### 1 · Section-data table")
    st.download_button(
        "Download section-data template (CSV)",
        data=_template_csv(aero_model),
        file_name="section_data_template.csv",
        mime="text/csv",
        key="aero_corr_template",
    )
    with st.expander("CSV column reference", expanded=False):
        st.markdown(_SCHEMA_HELP)

    up = st.file_uploader("Upload section-data CSV", type=["csv"], key="aero_corr_upload")
    if up is not None:
        try:
            df = sd.validate_section_data(pd.read_csv(up))
            st.session_state.aero_corr_df = df
            st.session_state.aero_corr_result = None   # invalidate stale build
        except Exception as exc:
            st.error(f"Could not load section data: {exc}")

    df = st.session_state.get("aero_corr_df")
    if df is None:
        st.info("Upload a section-data CSV (start from the template) to continue.")
        return

    st.dataframe(df, use_container_width=True)

    # ---- 2 · Available blocks ------------------------------------------------
    conds = sd.available_conditions(df)
    st.markdown("#### 2 · Blocks in the table")
    st.table([
        {"CAERO": c.caero, "Mach": f"{c.mach:g}", "var": c.var,
         "region [°]": f"[{c.a_lo:g}, {c.a_hi:g}]", "stations": c.n_stations}
        for c in conds
    ])

    # ---- 3 · Build condition -------------------------------------------------
    st.markdown("#### 3 · Build condition")
    machs = sorted({c.mach for c in conds})
    col1, col2 = st.columns(2)
    mach = col1.selectbox("Mach", machs, format_func=lambda m: f"{m:g}", key="aero_corr_mach")
    incidence = col2.number_input(
        "Operating incidence α/β (°)", value=2.0, step=0.5, key="aero_corr_incidence"
    )

    table_caeros = sorted({c.caero for c in conds if c.mach == mach})
    st.table([
        {"CAERO": eid,
         "status": (f"✓ region [{r[0]:g}, {r[1]:g}]°"
                    if (r := sd.operating_region(df, eid, mach, incidence)) else
                    "✗ no region covers this incidence")}
        for eid in table_caeros
    ])

    if st.button("Build correction cards", type="primary", key="aero_corr_build"):
        try:
            ajj = build_aero_model(bulk, mach=mach).ajj
            st.session_state.aero_corr_result = sd.build_from_section_data_multi(
                aero_model.boxes, ajj, df,
                mach=mach, incidence_deg=incidence,
                sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
            )
        except Exception as exc:
            st.session_state.aero_corr_result = None
            st.error(f"Build failed: {exc}")

    res = st.session_state.get("aero_corr_result")
    if res is None:
        return

    # ---- 4 · Generated cards -------------------------------------------------
    st.markdown("#### 4 · Generated cards")
    if res.skipped:
        st.warning(
            "Surfaces skipped (no region covering the incidence): "
            + "; ".join(f"CAERO {eid} — {why}" for eid, why in res.skipped)
        )
    extrap = [eid for eid, ex in res.extrapolated.items() if ex]
    if extrap:
        st.warning(
            f"Span extrapolation (clamped) on CAERO {extrap}: mesh η extends beyond the "
            "table's η range."
        )

    built_eids = sorted(res.correction.cards)
    if not built_eids:
        st.error("No surfaces were buildable at this condition.")
        return
    st.success(f"Built {len(built_eids)} surface card pair(s): CAERO {built_eids}")

    sel = st.selectbox("Preview surface", built_eids, key="aero_corr_preview")
    st.plotly_chart(
        build_section_correction_figure(aero_model.boxes, df, res, sel),
        use_container_width=True,
    )
    diag = res.correction.per_surface[sel]
    st.caption("Achieved per-strip targets (force/q and moment/q per rad; offsets at α=0):")
    st.dataframe(pd.DataFrame({
        "moment_ref_x": diag.moment_ref,
        "f_slope": diag.achieved_f_slope,
        "m_slope": diag.achieved_m_slope,
        "f0": diag.achieved_f0,
        "m0": diag.achieved_m0,
    }), use_container_width=True)

    # ---- 5 · Apply / export --------------------------------------------------
    st.markdown("#### 5 · Apply / export")
    _warn_conflicts(bulk, built_eids)
    cda, cdb = st.columns(2)
    if cda.button("Apply to model", type="primary", key="aero_corr_apply"):
        n = _apply_cards(bulk, res)
        st.success(
            f"Injected {n} card pair(s) into the model. Open the **Aero** tab and press "
            "Compute Aero to run the corrected solve."
        )
    cdb.download_button(
        "Download cards (.bdf)",
        data=cards_to_bdf(res.correction),
        file_name="section_correction.bdf",
        mime="text/plain",
        key="aero_corr_download",
    )
