"""Aero Correction tab — CFD/test section data → W2GJ + AECORR(WT2) cards.

Front end (Option A GUI) over ``sbeam.aero.section_data`` / ``section_correction``: the
user downloads a mesh-seeded CSV template, fills it with section lift/moment coefficients,
uploads it, picks a flight **condition** (Mach + operating α and β), and builds one
**W2GJ (camber/zero-α offset) + AECORR/WT2 (slope & a.c.)** card pair per lifting surface.
Each surface is corrected on one axis chosen by its table ``var`` (ALPHA→α, BETA→β). The
cards can be injected into the in-session model — the Aero tab keys off
``bulk.wkks``/``bulk.aecorrs`` so the corrected solve runs with no further wiring — and/or
downloaded as a bulk-data snippet or a full self-contained corrected BDF.

v1 limits (inherited from the engine): exact-Mach match (no Mach interpolation); one
operating region per surface (the region whose [a_lo, a_hi] contains the angle); one axis
per surface.
"""
from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import numpy as np

from sbeam.model.bulk_data import BulkData
from sbeam.aero.aero_model import build_aero_model
from sbeam.aero import section_data as sd
from sbeam.aero import body_correction as bc
from sbeam.aero.section_correction import cards_to_bdf
from sbeam.aero.strip import is_strip_caero
from sbeam.viewer.aero_view import build_section_correction_figure, surface_dihedral_deg
from sbeam.viewer.format_utils import style_numeric

# Reserved SID range for tool-generated cards (kept clear of typical user SIDs so the
# Apply step can find and replace its own cards on a rebuild).
_W2GJ_BASE = 9001
_AECORR_BASE = 9101
# Body-panel cards live in a separate reserved range (Stage 6).
_BODY_W2GJ_BASE = 9301
_BODY_AECORR_BASE = 9401
_BODY_STRIPK_BASE = 9501

# A surface whose mean dihedral magnitude falls in this band is "canted" — neither
# clearly horizontal (α-driven) nor vertical (β-driven) — so a single-axis section
# correction blends both responses and is only approximate.
_CANTED_LO = 20.0
_CANTED_HI = 70.0

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


def _tok(v: float, prec: int) -> str:
    """Filesystem-safe condition token: 0.30 → '0p30', -2.0 → 'm2p0'."""
    return f"{v:.{prec}f}".replace("-", "m").replace(".", "p")


def suggest_corrected_name(stem: str, mach: float, alpha: float, beta: float) -> str:
    """Default output filename encoding the condition, e.g. ``wing_M0p30_A2p0_B0p0.bdf``."""
    return f"{stem}_M{_tok(mach, 2)}_A{_tok(alpha, 1)}_B{_tok(beta, 1)}.bdf"


def _splice_cards(source_text: str, block: str) -> str:
    """Insert *block* before the first ENDDATA line (or append if none)."""
    lines = source_text.splitlines()
    end_idx = None
    for i, ln in enumerate(lines):
        if ln.split("$", 1)[0].strip().upper() == "ENDDATA":
            end_idx = i
            break
    block_lines = block.splitlines()
    if end_idx is None:
        return "\n".join(lines + block_lines) + "\n"
    return "\n".join(lines[:end_idx] + block_lines + lines[end_idx:]) + "\n"


def build_corrected_bdf(source_text: str, cards_text: str, *, source_csv: str,
                        mach: float, alpha: float, beta: float, eids: list,
                        out_name: str, date: str = None) -> str:
    """Splice the W2GJ/AECORR cards into the uploaded model with a provenance header.

    Produces a self-contained corrected BDF (the loaded model + correction cards),
    runnable in sbeam (which honours only one whole-bulk INCLUDE, so a separate
    include file is not used).  The header records the source section-data file,
    generation date, and flight condition for traceability across the per-Mach set.
    """
    date = date or datetime.date.today().isoformat()
    header = "\n".join([
        "$ " + "-" * 68,
        f"$ sbeam aero correction  —  {out_name}",
        f"$ source section data : {source_csv}",
        f"$ generated           : {date}",
        f"$ condition           : Mach {mach:g}  alpha {alpha:g} deg  beta {beta:g} deg",
        f"$ corrected surfaces  : CAERO {list(eids)}",
        "$ " + "-" * 68,
        cards_text.rstrip("\n"),
        "$ " + "-" * 68,
    ])
    return _splice_cards(source_text, header)


def _surface_normal_chord(aero_model) -> dict:
    """Per CAERO1: (mean unit normal, mean box chord) — for body-panel guessing."""
    info: dict = {}
    for eid in sorted({b.caero_eid for b in aero_model.boxes}):
        bx = [b for b in aero_model.boxes if b.caero_eid == eid]
        info[eid] = (np.mean([b.normal for b in bx], axis=0),
                     float(np.mean([b.chord for b in bx])))
    return info


def _guess_body_panels(aero_model):
    """Best-guess (horizontal, vertical) body CAERO1s: the largest-chord +Z / +Y
    surfaces (the fuselage cruciform panels run nose-to-tail, so their box chord is the
    longest).  Returns (eid_or_None, eid_or_None)."""
    info = _surface_normal_chord(aero_model)
    horiz = [(ch, eid) for eid, (n, ch) in info.items() if abs(n[2]) > 0.9]
    vert = [(ch, eid) for eid, (n, ch) in info.items() if abs(n[1]) > 0.9]
    return (max(horiz)[1] if horiz else None,
            max(vert)[1] if vert else None)


def _apply_body_cards(bulk: BulkData, res, bres) -> int:
    """Inject the flying-surface pairs (idempotent) and the body-panel pairs.

    The body card pair is (W2GJ, AECORR-WT2) for a cruciform VLM panel or
    (W2GJ, STRIPK) for a decoupled strip panel; the second card is routed to
    ``bulk.aecorrs`` or ``bulk.stripks`` by type.
    """
    from sbeam.model.aero import Stripk
    _apply_cards(bulk, res)   # flying cards + clears the Aero-tab cache
    for sid in st.session_state.get("aero_body_sids", set()):
        bulk.w2gjs.pop(sid, None)
        bulk.aecorrs.pop(sid, None)
        bulk.stripks.pop(sid, None)
    new_sids: set = set()
    for _eid, (w2, second) in bres.cards.items():
        bulk.w2gjs[w2.sid] = w2
        if isinstance(second, Stripk):
            bulk.stripks[second.sid] = second
        else:
            bulk.aecorrs[second.sid] = second
        new_sids.update((w2.sid, second.sid))
    st.session_state.aero_body_sids = new_sids
    st.session_state.aero_model = None
    st.session_state.aero_result = None
    st.session_state.aero_result_unc = None
    return len(bres.cards)


def _render_body_stage(bulk: BulkData, aero_model, res) -> None:
    """Stage 6 — cruciform body panels absorb the residual so the TOTAL airplane
    pitching/yawing moment match CFD/WT (after the flying surfaces are corrected)."""
    gh, gv = _guess_body_panels(aero_model)
    if gh is None and gv is None:
        return   # no plausible body panel in this model

    st.markdown("#### 6 · Body panels — total-aircraft moment match")
    st.caption(
        "Cruciform body panels absorb the residual so the TOTAL airplane pitching moment "
        "Cm and yawing moment Cn match CFD / wind tunnel, after the flying surfaces are "
        "matched to section data. Moment-primary: the body's lift / side-force is a "
        "minimum-norm by-product."
    )

    eids = sorted({b.caero_eid for b in aero_model.boxes})
    opts = [str(e) for e in eids]
    c1, c2 = st.columns(2)
    # Multiselect: a body plane may be split across several CAERO1s (e.g. a fuselage side
    # as one panel by the wing + one to the fin TE + one for the lower body). They are
    # tuned jointly; the auto-guess pre-selects the largest-chord +Z / +Y surface.
    h_sel = c1.multiselect("Horizontal body panel(s) — match Cm", opts,
                           default=[str(gh)] if gh is not None else [],
                           key="aero_body_horiz")
    v_sel = c2.multiselect("Vertical body panel(s) — match Cn, Cl", opts,
                           default=[str(gv)] if gv is not None else [],
                           key="aero_body_vert")
    horiz = [int(e) for e in h_sel]
    vert = [int(e) for e in v_sel]

    # Panel KIND is set by the deck: a CAERO1 PID → PSTRIP is a decoupled strip body
    # (no AIC coupling — cannot contaminate); PID → PAERO1 is a cruciform VLM body.
    sel = horiz + vert
    n_strip = sum(1 for e in sel if is_strip_caero(bulk, e))
    body_is_strip = bool(sel) and n_strip == len(sel)
    body_mixed = 0 < n_strip < len(sel)
    if body_is_strip:
        st.info("Selected panels are **decoupled strip bodies** (PSTRIP): each box loads "
                "only on its own local α/β — zero coupling to the lifting surfaces, so the "
                "match cannot contaminate the wing/tail and there is no conditioning gauge.")
    elif body_mixed:
        st.error("Mix of strip (PSTRIP) and cruciform (PAERO1) body panels selected — "
                 "build them separately (the two use different correction cards).")

    mach_c, _a, _b = st.session_state.get("aero_corr_cond") or (0.0, 0.0, 0.0)
    raw_df = st.session_state.get("aero_corr_raw_df")
    seed = (bc.parse_body_targets(raw_df, mach_c) if raw_df is not None else None) \
        or bc.BodyTargets()
    # Columns group the targets by plane: pitch (horizontal panel) / yaw + roll (vertical).
    g_pitch, g_yaw, g_roll = st.columns(3)
    t_cma = g_pitch.number_input("Cm_α target", value=float(seed.cm_alpha),
                                 format="%.4f", key="aero_body_cma")
    t_cm0 = g_pitch.number_input("Cm0 target", value=float(seed.cm0),
                                 format="%.4f", key="aero_body_cm0")
    t_cnb = g_yaw.number_input("Cn_β target", value=float(seed.cn_beta),
                               format="%.4f", key="aero_body_cnb")
    t_cn0 = g_yaw.number_input("Cn0 target", value=float(seed.cn0),
                               format="%.5f", key="aero_body_cn0")
    t_clb = g_roll.number_input("Cl_β target", value=float(seed.cl_beta),
                                format="%.4f", key="aero_body_clb")
    t_cl0 = g_roll.number_input("Cl0 target", value=float(seed.cl0),
                                format="%.5f", key="aero_body_cl0")
    st.caption("Targets seed from the CSV `TOTAL` block at this Mach when present; edit "
               "to match your CFD/WT total. Pitch (Cm) → horizontal panel(s); yaw+roll "
               "(Cn, Cl, both sideslip) → vertical panel(s). A plane may be split across "
               "several panels (tuned jointly). Keep panels clear of the wing/tail — an "
               "overlapping panel contaminates them, it does not model interference.")

    if st.button("Build body correction", key="aero_body_build", disabled=body_mixed):
        if not horiz and not vert:
            st.error("Select at least one body panel (horizontal and/or vertical).")
        else:
            try:
                fw2 = {w.sid: w for (w, _a) in res.correction.cards.values()}
                fac = {a.sid: a for (_w, a) in res.correction.cards.values()}
                bulk_f = dataclasses.replace(
                    bulk, w2gjs={**bulk.w2gjs, **fw2}, aecorrs={**bulk.aecorrs, **fac})
                aero_f = build_aero_model(bulk_f, mach=mach_c)
                tgt = bc.BodyTargets(cm_alpha=t_cma, cm0=t_cm0,
                                     cn_beta=t_cnb, cn0=t_cn0,
                                     cl_beta=t_clb, cl0=t_cl0)
                if body_is_strip:
                    st.session_state.aero_body_result = bc.build_strip_body_correction(
                        bulk_f, horiz_eid=horiz or None, vert_eid=vert or None,
                        targets=tgt, mach=mach_c, aero=aero_f,
                        sid_w2gj_base=_BODY_W2GJ_BASE, sid_stripk_base=_BODY_STRIPK_BASE)
                else:
                    st.session_state.aero_body_result = bc.build_body_correction(
                        bulk_f, horiz_eid=horiz or None, vert_eid=vert or None,
                        targets=tgt, mach=mach_c, aero=aero_f,
                        sid_w2gj_base=_BODY_W2GJ_BASE, sid_aecorr_base=_BODY_AECORR_BASE)
                st.session_state.aero_body_is_strip = body_is_strip
                # Remembered so the Aero tab can colour-distinguish the body
                # panels (cruciform boxes carry no per-box flag — AC5).
                st.session_state.aero_body_eids = set(sel)
            except Exception as exc:
                st.session_state.aero_body_result = None
                st.error(f"Body correction failed: {exc}")

    bres = st.session_state.get("aero_body_result")
    if bres is None:
        return

    table = pd.DataFrame([
        {"coef": lbl, "flying baseline": getattr(bres.baseline, k),
         "target": getattr(bres.target, k), "achieved": getattr(bres.achieved, k),
         "residual": bres.residual[k]}
        for k, lbl in (("cm_alpha", "Cm_α"), ("cm0", "Cm0"),
                       ("cn_beta", "Cn_β"), ("cn0", "Cn0"),
                       ("cl_beta", "Cl_β"), ("cl0", "Cl0"))
    ])
    st.dataframe(style_numeric(table), use_container_width=True)
    res_is_strip = st.session_state.get("aero_body_is_strip", False)
    if res_is_strip:
        st.caption(f"Max body slope scaling: {bres.ratio_max:.2f}× the nominal PSTRIP slope "
                   "(informational — a strip body is decoupled, so any value is benign).")
        if not bres.converged:
            st.warning("Strip panels could not reach the targets — they may lack the spatial "
                       "spread (x-arm for pitch/yaw, z-arm for roll). Add boxes or extend the "
                       "panel; geometry is free (a strip cannot contaminate the lifting surfaces).")
    else:
        st.caption(f"Max body WT2 ratio: {bres.ratio_max:.2f} "
                   "(conditioning gauge — not contamination; WT2 scales body boxes only)")
        if not bres.converged:
            st.warning("Body panels could not reach the targets within tolerance — reduce the "
                       "target increment (a flat-plate cruciform only supplies a small body effect; "
                       "large effects need a slender-body element).")
        elif bres.ratio_max > bc._RATIO_WARN:
            st.warning(f"Body WT2 ratio reached {bres.ratio_max:.1f} — beyond what a flat-plate "
                       "cruciform can represent. A ratio of tens-to-~100 is normal/benign for panels "
                       "held clear of the tail (WT2 does not perturb the lifting surfaces); a value "
                       "this large means the targets demand more than a fuselage stand-in should "
                       "supply — reduce the body increment, or use a slender-body element. Do NOT "
                       "enlarge the panels (that lowers the ratio but raises the spurious tail load).")

    cba, cbb = st.columns(2)
    if cba.button("Apply body panels to model", type="primary", key="aero_body_apply"):
        n = _apply_body_cards(bulk, res, bres)
        st.success(f"Injected the flying pairs + {n} body card pair(s). Open the **Aero** "
                   "tab and press Compute Aero to run the fully corrected solve.")
    body_bdf = (bc.strip_body_cards_to_bdf(bres) if res_is_strip
                else bc.body_cards_to_bdf(bres))
    cbb.download_button(
        "Download body cards (.bdf)", data=body_bdf,
        file_name="body_correction.bdf", mime="text/plain", key="aero_body_download")


def render_aero_correction_tab(bulk: BulkData) -> None:
    st.subheader("Aero correction — section force/moment cards from CFD / test data")
    st.caption(
        "Build W2GJ (camber / zero-α offset) + AECORR/WT2 (slope & a.c.) correction cards "
        "from a table of section coefficients for one flight condition (Mach + α/β), "
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
        # st.file_uploader returns the same file on every rerun; only re-parse when the
        # file actually changes, otherwise an unrelated rerun (e.g. changing the preview
        # surface) would reset aero_corr_result and the preview would vanish.
        file_id = (up.name, up.size)
        if file_id != st.session_state.get("aero_corr_upload_id"):
            try:
                raw = pd.read_csv(up)
                # A TOTAL block (body-panel targets) is split off before validation,
                # which only accepts ALPHA/BETA section rows.
                flying_df, _totals = bc.split_total_rows(raw)
                df = sd.validate_section_data(flying_df)
                st.session_state.aero_corr_df = df
                st.session_state.aero_corr_raw_df = raw
                st.session_state.aero_corr_csv_name = up.name
                st.session_state.aero_corr_result = None   # invalidate stale build
                st.session_state.aero_body_result = None
                st.session_state.aero_corr_upload_id = file_id
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
    st.caption(
        "Each surface is corrected on **one** axis: an ALPHA surface uses the operating "
        "α, a BETA surface uses the operating β (the two can differ)."
    )
    machs = sorted({c.mach for c in conds})
    col1, col2, col3 = st.columns(3)
    mach = col1.selectbox("Mach", machs, format_func=lambda m: f"{m:g}", key="aero_corr_mach")
    alpha = col2.number_input("Operating α (°)", value=2.0, step=0.5, key="aero_corr_alpha")
    beta = col3.number_input("Operating β (°)", value=0.0, step=0.5, key="aero_corr_beta")

    table_caeros = sorted({c.caero for c in conds if c.mach == mach})
    status_rows, canted = [], []
    for eid in table_caeros:
        var = sd.surface_var(df, eid, mach)
        if var == "ALPHA":
            ang, axis = alpha, "α"
        elif var == "BETA":
            ang, axis = beta, "β"
        else:  # MIXED or None
            ang, axis = None, "—"
        region = sd.operating_region(df, eid, mach, ang) if ang is not None else None
        gam = surface_dihedral_deg(aero_model.boxes, eid)
        if _CANTED_LO <= gam <= _CANTED_HI:
            canted.append((eid, gam))
        status_rows.append({
            "CAERO": eid,
            "var": "MIXED ⚠" if var == "MIXED" else (var or "—"),
            "axis": axis,
            "operating [°]": float(ang) if ang is not None else float("nan"),
            "region [°]": (f"[{region[0]:g}, {region[1]:g}]" if region else "✗ none"),
            "Γ [°]": gam,
        })
    st.dataframe(style_numeric(pd.DataFrame(status_rows)), use_container_width=True)
    for eid, gam in canted:
        st.warning(
            f"CAERO {eid}: dihedral Γ≈{gam:.0f}° (canted) — a single-axis (α or β) section "
            "correction blends both responses on this surface; interpret with care."
        )

    if st.button("Build correction cards", type="primary", key="aero_corr_build"):
        try:
            ajj = build_aero_model(bulk, mach=mach).ajj
            st.session_state.aero_corr_result = sd.build_from_section_data_multi(
                aero_model.boxes, ajj, df,
                mach=mach, alpha_deg=alpha, beta_deg=beta,
                sid_w2gj_base=_W2GJ_BASE, sid_aecorr_base=_AECORR_BASE,
            )
            st.session_state.aero_corr_cond = (float(mach), float(alpha), float(beta))
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
        use_container_width=True, key="aero_corr_preview_fig",
    )
    diag = res.correction.per_surface[sel]
    st.caption("Achieved per-strip targets (force/q and moment/q per rad; offsets at α=0):")
    st.dataframe(style_numeric(pd.DataFrame({
        "moment_ref_x": diag.moment_ref,
        "f_slope": diag.achieved_f_slope,
        "m_slope": diag.achieved_m_slope,
        "f0": diag.achieved_f0,
        "m0": diag.achieved_m0,
    })), use_container_width=True)

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

    # ---- Full corrected BDF (loaded model + correction cards) ----------------
    st.markdown("##### Full corrected BDF")
    st.caption(
        "Writes a self-contained model = the loaded BDF + these correction cards, with a "
        "provenance header. Build one per Mach (the filename encodes the condition)."
    )
    mach_c, alpha_c, beta_c = st.session_state.get("aero_corr_cond") or (0.0, 0.0, 0.0)
    stem = Path(st.session_state.get("_uploaded_filename") or "model.bdf").stem
    default_name = suggest_corrected_name(stem, mach_c, alpha_c, beta_c)
    out_name = st.text_input("Output filename", value=default_name, key="aero_corr_bdf_name")
    src = st.session_state.get("_uploaded_source_text")
    if src is None:
        st.info(
            "Full-model export needs the originally uploaded file text; only the card "
            "snippet above is available for this session."
        )
    else:
        corrected = build_corrected_bdf(
            src, cards_to_bdf(res.correction),
            source_csv=st.session_state.get("aero_corr_csv_name", "section_data.csv"),
            mach=mach_c, alpha=alpha_c, beta=beta_c, eids=built_eids, out_name=out_name,
        )
        st.download_button(
            "Download corrected BDF",
            data=corrected,
            file_name=out_name,
            mime="text/plain",
            key="aero_corr_bdf_download",
        )

    # ---- 6 · Body panels — total-aircraft moment match -----------------------
    _render_body_stage(bulk, aero_model, res)
