"""Aeroelastic Authoring tab — SOL 144 / MLOADS bulk-card editors (P12).

Each card family gets a top-level expander holding a selectbox ("— new —" or
an existing ID, outside the form so switching reruns and pre-fills) and one
``st.form`` with the family's fields.  Applying builds the dataclass, checks
SID clashes (clone-as-new policy for INCLUDE-sourced cards), injects it into
the in-session ``BulkData`` and invalidates solver results.  All widget keys
are ``auth_``-prefixed; ``st.session_state.authored_cards`` tracks what this
session created, which is exactly the card set the driver export inlines.
"""

from typing import Any, Callable, Optional

import pandas as pd
import streamlit as st

from sbeam.model.aero import (
    Aestat, Aesurf, Aelist, Trim, Diverg, Trimvar, Trimobj, Trimcon,
)
from sbeam.model.bulk_data import BulkData
from sbeam.model.constraint import Suport
from sbeam.model.maneuver import (
    Tabled1, Mldtime, Mldcomd, Mldprnt, Mldtrim, Mloads,
)
from sbeam.model.card_writers import write_authored_block
from sbeam.viewer import sol144_authoring as logic
from sbeam.viewer.case_control_ui import export_bdf_text


def export_sol144_bdf(cc, bulk: BulkData, authored: dict[str, set[int]],
                      include_paths: Optional[list] = None,
                      title_comment: str = "") -> str:
    """Full driver deck: provenance header + case control + authored cards
    inline + every INCLUDE.  Pure — reused by the export tests."""
    header = "Authored in the sbeam viewer (SOL 144 / MLOADS authoring tab)"
    if title_comment:
        header += f"\n{title_comment}"
    block = write_authored_block(bulk, authored, header)
    return export_bdf_text(cc, include_paths=include_paths,
                           authored_block=block)


# ---------------------------------------------------------------------------
# Shared plumbing
# ---------------------------------------------------------------------------

_NEW = "— new —"


def _invalidate_results() -> None:
    """Authored cards changed — solved results and the aero cache are stale."""
    for key in ("sol144_result", "sol144_diverg_result", "maneuver_result",
                "aero_model_144"):
        st.session_state[key] = None


def _authored() -> dict[str, set[int]]:
    return st.session_state.setdefault("authored_cards", {})


def _family_ids(bulk: BulkData, family: str) -> list[int]:
    store = logic.family_store(bulk, family)
    if family == "suport":
        return sorted(s.gid for s in store)
    return sorted(store.keys())


def _family_editor(
    bulk: BulkData,
    family: str,
    title: str,
    render_form: Callable[[BulkData, Optional[Any], int], Optional[Any]],
) -> None:
    """Selector + form + apply/delete skeleton shared by every card family.

    ``render_form(bulk, existing_card, default_id)`` renders the family's
    widgets (inside the form) and returns the built card — or None when the
    inputs are incomplete (it should st.warning the reason).
    """
    with st.expander(title, expanded=False):
        ids = _family_ids(bulk, family)
        sel = st.selectbox(
            "Edit existing or create new", [_NEW] + ids,
            key=f"auth_sel_{family}",
        )
        editing = sel != _NEW
        existing = None
        if editing:
            store = logic.family_store(bulk, family)
            if family == "suport":
                existing = next(s for s in store if s.gid == sel)
            else:
                existing = store[sel]
        default_id = sel if editing else logic.next_free_sid(bulk, family)

        with st.form(f"auth_form_{family}"):
            card = render_form(bulk, existing, default_id)
            col_apply, col_new = st.columns([1, 2])
            applied = col_apply.form_submit_button("Apply", type="primary")
            save_new = False
            if editing and sel not in _authored().get(family, set()):
                save_new = col_new.form_submit_button(
                    "Save as new SID",
                    help="This card came from the loaded file; re-exporting "
                         "it inline would duplicate its SID against the "
                         "INCLUDE.  Saving as a new SID keeps the deck "
                         "parseable.",
                )

        if (applied or save_new) and card is not None:
            if save_new:
                key_attr = "gid" if family == "suport" else (
                    "sid" if hasattr(card, "sid") else "id")
                setattr(card, key_attr, logic.next_free_sid(bulk, family))
            key = logic.card_key(family, card[0] if isinstance(card, list) else card)
            conflicts = logic.find_sid_conflicts(bulk, family, key, _authored())
            for msg in conflicts:
                st.warning(msg)
            logic.apply_card(bulk, family, card, _authored())
            _invalidate_results()
            st.success(f"{family.upper()} {logic.card_key(family, card[0] if isinstance(card, list) else card)} applied to the session model.")

        if editing and sel in _authored().get(family, set()):
            if st.button("Delete", key=f"auth_del_{family}"):
                logic.delete_card(bulk, family, sel, _authored())
                _invalidate_results()
                st.rerun()


def _pairs_editor(key: str, columns: dict[str, Any],
                  rows: list[dict[str, Any]]) -> pd.DataFrame:
    """A dynamic-row data editor (allowed inside forms; commits on submit)."""
    df = pd.DataFrame(rows, columns=list(columns))
    return st.data_editor(
        df, key=key, num_rows="dynamic", column_config=columns,
        use_container_width=True, hide_index=True,
    )


# ---------------------------------------------------------------------------
# Panel 1 — Control surfaces & states
# ---------------------------------------------------------------------------

def _aestat_form(bulk: BulkData, card: Optional[Aestat], default_id: int):
    aid = st.number_input("ID", min_value=1, value=(card.id if card else default_id),
                          key="auth_aestat_id")
    label = st.selectbox(
        "Label", logic.AESTAT_LABELS,
        index=(logic.AESTAT_LABELS.index(card.label)
               if card and card.label in logic.AESTAT_LABELS else 0),
        key="auth_aestat_label",
        help="Canonical rigid-body trim-variable labels.",
    )
    return Aestat(id=int(aid), label=label)


def _aesurf_form(bulk: BulkData, card: Optional[Aesurf], default_id: int):
    aid = st.number_input("ID", min_value=1, value=(card.id if card else default_id),
                          key="auth_aesurf_id")
    label = st.text_input("Label", value=(card.label if card else ""),
                          key="auth_aesurf_label").strip().upper()
    cids = [0] + sorted(bulk.cord2rs.keys())
    alids = sorted(bulk.aelists.keys())
    col1, col2 = st.columns(2)
    cid1 = col1.selectbox(
        "Hinge CID (CID1)", cids,
        index=cids.index(card.cid1) if card and card.cid1 in cids else 0,
        key="auth_aesurf_cid1",
        help="The CID's y-axis is the hinge line.",
    )
    alid1 = col2.selectbox(
        "Box list (ALID1, an AELIST SID)", alids,
        index=alids.index(card.alid1) if card and card.alid1 in alids else 0,
        key="auth_aesurf_alid1",
    ) if alids else None
    eff = st.number_input("Effectiveness (EFF)", value=(card.eff if card else 1.0),
                          key="auth_aesurf_eff")
    if not label:
        st.warning("AESURF needs a label.")
        return None
    if alid1 is None:
        st.warning("Define an AELIST first — AESURF needs a box list.")
        return None
    return Aesurf(id=int(aid), label=label, cid1=int(cid1), alid1=int(alid1),
                  eff=float(eff))


def _aelist_form(bulk: BulkData, card: Optional[Aelist], default_id: int):
    sid = st.number_input("SID", min_value=1, value=(card.sid if card else default_id),
                          key="auth_aelist_sid")
    ranges = logic.caero_box_ranges(bulk)
    if ranges:
        st.caption("Valid box IDs: " +
                   ", ".join(f"{lo}–{hi}" for lo, hi in ranges))
    default_text = " ".join(str(e) for e in card.elements) if card else ""
    text = st.text_input("Box IDs (THRU allowed, e.g. '1101 THRU 1112')",
                         value=default_text, key="auth_aelist_boxes")
    try:
        elements = logic.expand_int_tokens(text)
    except ValueError:
        st.warning("Box list is not a valid integer/THRU list.")
        return None
    if not elements:
        st.warning("AELIST needs at least one box ID.")
        return None
    outside = logic.boxes_outside_ranges(elements, ranges)
    if outside:
        st.warning(f"Boxes outside every CAERO1 range: {outside}")
        return None
    return Aelist(sid=int(sid), elements=elements)


def _suport_form(bulk: BulkData, card: Optional[Suport], default_id: int):
    gids = sorted(bulk.grids.keys())
    gid = st.selectbox(
        "Grid (GID)", gids,
        index=gids.index(card.gid) if card and card.gid in gids else 0,
        key="auth_suport_gid",
    ) if gids else None
    dofs = st.text_input("DOF components (e.g. '35' = Tz + Ry)",
                         value=(card.dofs if card else "35"),
                         key="auth_suport_dofs").strip()
    if gid is None or not dofs or not dofs.isdigit():
        st.warning("SUPORT needs a grid and a digit-string DOF list.")
        return None
    return Suport(gid=int(gid), dofs=dofs)


# ---------------------------------------------------------------------------
# Panel 2 — Trim conditions
# ---------------------------------------------------------------------------

def _trim_form(bulk: BulkData, card: Optional[Trim], default_id: int):
    col1, col2, col3, col4 = st.columns(4)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key="auth_trim_sid")
    mach = col2.number_input("Mach", value=(card.mach if card else 0.0),
                             key="auth_trim_mach", format="%.4f")
    q = col3.number_input("Dynamic pressure Q", value=(card.q if card else 0.0),
                          key="auth_trim_q", format="%.6g")
    rhoref = col4.number_input(
        "RHOREF (0 = unset)", value=(card.rhoref if card else 0.0),
        key="auth_trim_rhoref", format="%.6g", min_value=0.0,
        help="Freestream density; required for the modal MLOADS initial "
             "condition (V = sqrt(2q/rho)).",
    )
    labels = logic.label_options(bulk)
    prefill: Optional[dict[str, float]] = st.session_state.get("auth_trim_prefill")
    if card is not None:
        rows = [{"label": k, "value": v} for k, v in card.vars.items()]
    elif prefill:
        rows = [{"label": k, "value": v} for k, v in prefill.items()]
    else:
        rows = [{"label": labels[0] if labels else "", "value": 0.0}]
    # The editor key is versioned so a preset pre-fill replaces the persisted
    # editor state instead of being ignored by it.
    ver = st.session_state.get("auth_trim_vars_ver", 0)
    df = _pairs_editor(
        f"auth_trim_vars_{ver}",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "value": st.column_config.NumberColumn("Prescribed value", format="%.6g")},
        rows,
    )
    vars_: dict[str, float] = {}
    for _, row in df.iterrows():
        if isinstance(row["label"], str) and row["label"].strip():
            vars_[row["label"].strip().upper()] = float(row["value"] or 0.0)
    if not labels:
        st.warning("Define AESTAT/AESURF labels first.")
        return None
    return Trim(sid=int(sid), mach=float(mach), q=float(q), vars=vars_,
                rhoref=float(rhoref))


def _trimvar_form(bulk: BulkData, card: Optional[Trimvar], default_id: int):
    labels = logic.label_options(bulk)
    col1, col2 = st.columns(2)
    vid = col1.number_input("ID", min_value=1,
                            value=(card.id if card else default_id),
                            key="auth_trimvar_id")
    label = col2.selectbox(
        "Label", labels,
        index=labels.index(card.label) if card and card.label in labels else 0,
        key="auth_trimvar_label",
    ) if labels else None
    col3, col4, col5 = st.columns(3)
    init = col3.number_input("Initial", value=(card.init if card else 0.0),
                             key="auth_trimvar_init", format="%.6g")
    lb = col4.number_input("Lower bound", value=(card.lb if card else -1.0),
                           key="auth_trimvar_lb", format="%.6g")
    ub = col5.number_input("Upper bound", value=(card.ub if card else 1.0),
                           key="auth_trimvar_ub", format="%.6g")
    if label is None:
        st.warning("Define AESTAT/AESURF labels first.")
        return None
    return Trimvar(id=int(vid), label=label, init=float(init),
                   lb=float(lb), ub=float(ub))


def _trimobj_form(bulk: BulkData, card: Optional[Trimobj], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key="auth_trimobj_sid")
    labels = logic.label_options(bulk)
    rows = ([{"label": l, "weight": w} for l, w in zip(card.labels, card.weights)]
            if card else [{"label": labels[0] if labels else "", "weight": 1.0}])
    df = _pairs_editor(
        "auth_trimobj_pairs",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "weight": st.column_config.NumberColumn("Weight", format="%.6g")},
        rows,
    )
    out_labels, weights = [], []
    for _, row in df.iterrows():
        if isinstance(row["label"], str) and row["label"].strip():
            out_labels.append(row["label"].strip().upper())
            weights.append(float(row["weight"] or 0.0))
    if not out_labels:
        st.warning("TRIMOBJ needs at least one label/weight pair.")
        return None
    return Trimobj(sid=int(sid), labels=out_labels, weights=weights)


def _trimcon_form(bulk: BulkData, cards: Optional[list[Trimcon]], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(cards[0].sid if cards else default_id),
                          key="auth_trimcon_sid")
    labels = logic.label_options(bulk)
    rows = ([{"label": c.label, "sense": c.sense, "rhs": c.rhs} for c in cards]
            if cards else
            [{"label": labels[0] if labels else "", "sense": "LE", "rhs": 0.0}])
    df = _pairs_editor(
        "auth_trimcon_rows",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "sense": st.column_config.SelectboxColumn("Sense", options=["LE", "GE"]),
         "rhs": st.column_config.NumberColumn("RHS", format="%.6g")},
        rows,
    )
    cons = []
    for _, row in df.iterrows():
        if isinstance(row["label"], str) and row["label"].strip():
            cons.append(Trimcon(sid=int(sid), label=row["label"].strip().upper(),
                                sense=str(row["sense"]), rhs=float(row["rhs"] or 0.0)))
    if not cons:
        st.warning("TRIMCON needs at least one constraint row.")
        return None
    return cons


def _diverg_form(bulk: BulkData, card: Optional[Diverg], default_id: int):
    col1, col2, col3 = st.columns(3)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key="auth_diverg_sid")
    nroots = col2.number_input("Roots (NROOTS)", min_value=1,
                               value=(card.nroots if card else 1),
                               key="auth_diverg_nroots")
    rhoref = col3.number_input("RHOREF (0 = omit V_div)", min_value=0.0,
                               value=(card.rhoref if card else 0.0),
                               key="auth_diverg_rhoref", format="%.6g")
    machs_text = st.text_input(
        "Mach list", value=(" ".join(f"{m:g}" for m in card.machs) if card else "0.0"),
        key="auth_diverg_machs",
    )
    try:
        machs = logic.parse_float_list(machs_text)
    except ValueError:
        st.warning("Mach list is not a valid float list.")
        return None
    if not machs:
        st.warning("DIVERG needs at least one Mach number.")
        return None
    return Diverg(sid=int(sid), nroots=int(nroots), rhoref=float(rhoref),
                  machs=machs)


# ---------------------------------------------------------------------------
# Panel 3 — Maneuver (MLOADS family)
# ---------------------------------------------------------------------------

def _mloads_form(bulk: BulkData, card: Optional[Mloads], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key="auth_mloads_sid")
    trims = sorted(bulk.mldtrims.keys())
    times = sorted(bulk.mldtimes.keys())
    comds = [0] + sorted(bulk.mldcomds.keys())
    prnts = [0] + sorted(bulk.mldprnts.keys())
    col1, col2 = st.columns(2)
    mldtrim = col1.selectbox(
        "MLDTRIM (initial condition)", trims,
        index=trims.index(card.mldtrim) if card and card.mldtrim in trims else 0,
        key="auth_mloads_mldtrim") if trims else None
    mldtime = col2.selectbox(
        "MLDTIME (integration window)", times,
        index=times.index(card.mldtime) if card and card.mldtime in times else 0,
        key="auth_mloads_mldtime") if times else None
    col3, col4 = st.columns(2)
    mldcomd = col3.selectbox(
        "MLDCOMD (0 = hold trim)", comds,
        index=comds.index(card.mldcomd) if card and card.mldcomd in comds else 0,
        format_func=lambda v: "— none (hold trim) —" if v == 0 else str(v),
        key="auth_mloads_mldcomd")
    mldprnt = col4.selectbox(
        "MLDPRNT (0 = no ASCII print)", prnts,
        index=prnts.index(card.mldprnt) if card and card.mldprnt in prnts else 0,
        format_func=lambda v: "— none —" if v == 0 else str(v),
        key="auth_mloads_mldprnt")
    st.caption(
        "Solver selection: any of NMODES/METHOD/ZETA nonzero runs the "
        "free-flight modal solver (METHOD = −1 is the all-defaults-modal "
        "sentinel); all zeros runs the direct restrained l-set solver.  The "
        "modal solver only accepts AESURF labels in MLDCOMD and needs RHOREF "
        "on the IC TRIM."
    )
    col5, col6, col7 = st.columns(3)
    nmodes = col5.number_input("NMODES (0 = all elastic)", min_value=0,
                               value=(card.nmodes if card else 0),
                               key="auth_mloads_nmodes")
    methods = [-1, 0] + sorted(bulk.eigrls.keys())
    method = col6.selectbox(
        "METHOD", methods,
        index=methods.index(card.method) if card and card.method in methods else 1,
        format_func=lambda v: {-1: "−1 — all-defaults modal", 0: "0 — default"}.get(v, f"EIGRL {v}"),
        key="auth_mloads_method")
    zeta = col7.number_input("ZETA (elastic damping)", min_value=0.0,
                             value=(card.zeta if card else 0.0),
                             key="auth_mloads_zeta", format="%.4f")
    if mldtrim is None or mldtime is None:
        st.warning("Define an MLDTRIM and an MLDTIME first.")
        return None
    return Mloads(sid=int(sid), mldtrim=int(mldtrim), mldtime=int(mldtime),
                  mldcomd=int(mldcomd), mldprnt=int(mldprnt),
                  nmodes=int(nmodes), method=int(method), zeta=float(zeta))


def _mldtrim_form(bulk: BulkData, card: Optional[Mldtrim], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key="auth_mldtrim_sid")
    trims = sorted(bulk.trims.keys())
    trim_sid = st.selectbox(
        "TRIM SID (steady initial condition)", trims,
        index=trims.index(card.trim_sid) if card and card.trim_sid in trims else 0,
        format_func=lambda v: (
            f"{v} (q={bulk.trims[v].q:g}, M={bulk.trims[v].mach:g}"
            + ("" if bulk.trims[v].rhoref else ", no RHOREF") + ")"),
        key="auth_mldtrim_trim") if trims else None
    if trim_sid is None:
        st.warning("Define a TRIM condition first.")
        return None
    return Mldtrim(sid=int(sid), trim_sid=int(trim_sid))


def _mldtime_form(bulk: BulkData, card: Optional[Mldtime], default_id: int):
    col1, col2, col3, col4, col5 = st.columns(5)
    sid = col1.number_input("SID", min_value=1,
                            value=(card.sid if card else default_id),
                            key="auth_mldtime_sid")
    t0 = col2.number_input("T0", value=(card.t0 if card else 0.0),
                           key="auth_mldtime_t0", format="%.4g")
    tend = col3.number_input("TEND", value=(card.tend if card else 1.0),
                             key="auth_mldtime_tend", format="%.4g")
    dt = col4.number_input("DT", value=(card.dt if card else 0.01),
                           key="auth_mldtime_dt", format="%.4g")
    tout = col5.number_input("TOUT (0 = every step)", min_value=0.0,
                             value=(card.tout if card else 0.0),
                             key="auth_mldtime_tout", format="%.4g")
    if dt <= 0.0 or tend <= t0:
        st.warning("MLDTIME needs DT > 0 and TEND > T0.")
        return None
    return Mldtime(sid=int(sid), t0=float(t0), tend=float(tend),
                   dt=float(dt), tout=float(tout))


def _mldcomd_form(bulk: BulkData, card: Optional[Mldcomd], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key="auth_mldcomd_sid")
    # Restrict to AESURF labels when any modal MLOADS references this card —
    # rigid-state commands under the modal solver are a hard parse error.
    modal_owner = any(m.mldcomd == (card.sid if card else 0) and m.selects_modal
                      for m in bulk.mloads.values())
    labels = logic.label_options(bulk, modal_only=modal_owner)
    if modal_owner:
        st.caption("A modal MLOADS references this card — AESURF labels only.")
    tabids = sorted(bulk.tabled1s.keys())
    rows = ([{"label": l, "tabid": t} for l, t in card.commands]
            if card else
            [{"label": labels[0] if labels else "", "tabid": tabids[0] if tabids else 0}])
    df = _pairs_editor(
        "auth_mldcomd_rows",
        {"label": st.column_config.SelectboxColumn("Label", options=labels),
         "tabid": st.column_config.SelectboxColumn("TABLED1", options=tabids)},
        rows,
    )
    commands = []
    for _, row in df.iterrows():
        if isinstance(row["label"], str) and row["label"].strip():
            commands.append((row["label"].strip().upper(), int(row["tabid"] or 0)))
    if not labels or not tabids:
        st.warning("Define AESURF/AESTAT labels and at least one TABLED1 first.")
        return None
    if not commands:
        st.warning("MLDCOMD needs at least one label/table pair.")
        return None
    return Mldcomd(sid=int(sid), commands=commands)


def _mldprnt_form(bulk: BulkData, card: Optional[Mldprnt], default_id: int):
    sid = st.number_input("SID", min_value=1,
                          value=(card.sid if card else default_id),
                          key="auth_mldprnt_sid")
    st.caption("Item keywords are recorded on the card but do not filter the "
               "ASCII output — the full column set is always printed.")
    return Mldprnt(sid=int(sid), items=list(card.items) if card else [])


# ---------------------------------------------------------------------------
# Panel 4 — Tables (TABLED1)
# ---------------------------------------------------------------------------

def _tabled1_form(bulk: BulkData, card: Optional[Tabled1], default_id: int):
    tid = st.number_input("TID", min_value=1,
                          value=(card.tid if card else default_id),
                          key="auth_tabled1_tid")
    rows = ([{"x": x, "y": y} for x, y in zip(card.xs, card.ys)]
            if card else [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}])
    df = _pairs_editor(
        "auth_tabled1_points",
        {"x": st.column_config.NumberColumn("x (time)", format="%.6g"),
         "y": st.column_config.NumberColumn("y (value)", format="%.6g")},
        rows,
    )
    xs, ys = [], []
    for _, row in df.iterrows():
        if row["x"] is not None and row["y"] is not None:
            xs.append(float(row["x"]))
            ys.append(float(row["y"]))
    if len(xs) < 2:
        st.warning("TABLED1 needs at least two points.")
        return None
    if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
        st.warning("Abscissae must be strictly increasing.")
        return None
    return Tabled1(tid=int(tid), xs=xs, ys=ys)


# ---------------------------------------------------------------------------
# S4 — presets, table generators, two-pass increment builder
# ---------------------------------------------------------------------------

def _render_preset_panel(bulk: BulkData) -> None:
    with st.expander("Preset maneuvers — pre-fill the TRIM form", expanded=False):
        names = [p.name for p in logic.MANEUVER_PRESETS]
        sel = st.selectbox("Maneuver", names, key="auth_preset_sel")
        preset = next(p for p in logic.MANEUVER_PRESETS if p.name == sel)
        st.caption(preset.description)
        col1, col2 = st.columns(2)
        param = col1.number_input(preset.param_label, value=preset.param_default,
                                  key="auth_preset_param", format="%.4g")
        g = col2.number_input(
            "Gravity g (model units)", value=32.174, key="auth_preset_g",
            format="%.6g",
        ) if preset.uses_g else 0.0
        missing = logic.missing_preset_labels(bulk, preset)
        if missing:
            st.warning(f"Missing AESTAT labels: {', '.join(missing)}")
            if st.button("Create missing AESTATs", key="auth_preset_mkstat"):
                for label in missing:
                    aid = logic.next_free_sid(bulk, "aestat")
                    logic.apply_card(bulk, "aestat", Aestat(id=aid, label=label),
                                     _authored())
                _invalidate_results()
                st.rerun()
        if not any(s for s in bulk.aesurfs.values()):
            st.warning(f"The {preset.surface_role} (an AESURF) must exist and "
                       "stay un-prescribed so it can trim free.")
        if st.button("Pre-fill TRIM form", key="auth_preset_fill"):
            st.session_state["auth_trim_prefill"] = preset.prescribed_vars(param, g)
            st.session_state["auth_trim_vars_ver"] = \
                st.session_state.get("auth_trim_vars_ver", 0) + 1
            st.session_state["auth_sel_trim"] = _NEW
            st.rerun()


_GENERATORS = ["Cosine ramp (recommended)", "Linear ramp", "Step", "Doublet"]


def _generator_points(shape: str, key_prefix: str,
                      y0_label: str = "Start value y0",
                      y1_label: str = "End value y1") -> Optional[list]:
    """Shared generator parameter widgets; returns (x, y) points or None."""
    col1, col2 = st.columns(2)
    t1 = col1.number_input("t1 (shape start)", min_value=0.0, value=0.0,
                           key=f"{key_prefix}_t1", format="%.4g")
    t2 = col2.number_input("t2 (shape end)", min_value=0.0, value=0.2,
                           key=f"{key_prefix}_t2", format="%.4g")
    col3, col4 = st.columns(2)
    if shape == "Doublet":
        y0 = col3.number_input("Baseline y0", value=0.0,
                               key=f"{key_prefix}_y0", format="%.6g")
        amp = col4.number_input("Amplitude", value=0.1,
                                key=f"{key_prefix}_amp", format="%.6g")
    else:
        y0 = col3.number_input(y0_label, value=0.0,
                               key=f"{key_prefix}_y0", format="%.6g")
        y1 = col4.number_input(y1_label, value=0.1,
                               key=f"{key_prefix}_y1", format="%.6g")
    try:
        if shape == "Step":
            return logic.gen_step(t1, y0, y1)
        if shape == "Linear ramp":
            return logic.gen_ramp(t1, t2, y0, y1)
        if shape == "Doublet":
            return logic.gen_doublet(t1, t2, amp, y0)
        return logic.gen_cosine_ramp(t1, t2, y0, y1)
    except ValueError as exc:
        st.warning(str(exc))
        return None


def _render_table_generator(bulk: BulkData) -> None:
    with st.expander("Generate a TABLED1 from a shape", expanded=False):
        st.caption(
            "Cosine ramps are the recommended default — clamped-linear slope "
            "jumps ring the highest retained mode under the modal solver."
        )
        shape = st.selectbox("Shape", _GENERATORS, key="auth_gen_shape")
        tid = st.number_input("TID", min_value=1,
                              value=logic.next_free_sid(bulk, "tabled1"),
                              key="auth_gen_tid")
        points = _generator_points(shape, "auth_gen")
        if points is not None and st.button("Create TABLED1", key="auth_gen_apply"):
            table = Tabled1(tid=int(tid),
                            xs=[p[0] for p in points], ys=[p[1] for p in points])
            for msg in logic.find_sid_conflicts(bulk, "tabled1", table.tid, _authored()):
                st.warning(msg)
            logic.apply_card(bulk, "tabled1", table, _authored())
            _invalidate_results()
            st.success(f"TABLED1 {table.tid} applied to the session model.")


def _render_increment_builder(bulk: BulkData) -> None:
    """Two-pass MLDCOMD authoring: increments now, absolute tables post-solve."""
    with st.expander("Two-pass command builder (increments from trim)",
                     expanded=False):
        st.caption(
            "Command tables are absolute and mass-case specific: the table "
            "value at t0 must equal the solved trim control value, which is "
            "only known after a solve.  Author the command as an increment "
            "here; after running the analysis, one click offsets it by the "
            "solved trim value per mass case and writes the absolute TABLED1."
        )
        specs: dict = st.session_state.setdefault("mldcomd_increments", {})
        mloads_sids = sorted(bulk.mloads.keys())
        surf_labels = logic.label_options(bulk, modal_only=True)
        if not mloads_sids or not surf_labels:
            st.info("Define an MLOADS driver and at least one AESURF first.")
            return
        col1, col2 = st.columns(2)
        msid = col1.selectbox("MLOADS", mloads_sids, key="auth_inc_mloads")
        label = col2.selectbox("Control (AESURF label)", surf_labels,
                               key="auth_inc_label")
        shape = st.selectbox("Increment shape (Δ from trim)", _GENERATORS,
                             key="auth_inc_shape")
        points = _generator_points(shape, "auth_inc",
                                   y0_label="Start Δ", y1_label="End Δ")
        if points is not None and st.button("Add increment command",
                                            key="auth_inc_add"):
            specs[(msid, label)] = logic.IncrementSpec(
                mloads_sid=msid, label=label, points=points)
            st.rerun()

        if specs:
            st.markdown("**Pending increment commands**")
            for (m, l), spec in list(specs.items()):
                col_a, col_b = st.columns([4, 1])
                dys = [dy for _, dy in spec.points]
                col_a.markdown(
                    f"- MLOADS {m} · {l}: {len(spec.points)} points, "
                    f"Δ ∈ [{min(dys):g}, {max(dys):g}]")
                if col_b.button("Remove", key=f"auth_inc_rm_{m}_{l}"):
                    del specs[(m, l)]
                    st.rerun()

            trim_results = st.session_state.get("sol144_result")
            maneuver_results = st.session_state.get("maneuver_result")
            have_solve = bool(trim_results or maneuver_results)
            if not have_solve:
                st.button("Resolve → absolute TABLED1s", disabled=True,
                          key="auth_inc_resolve",
                          help="Run the trim/maneuver solve first (or author "
                               "the table as absolute values).")
            elif st.button("Resolve → absolute TABLED1s", type="primary",
                           key="auth_inc_resolve"):
                cc = st.session_state.get("case_control")
                cards, report, errors, resolved = logic.resolve_increment_tables(
                    bulk, cc, list(specs.values()),
                    trim_results=trim_results,
                    maneuver_results=maneuver_results,
                )
                for family, card in cards:
                    logic.apply_card(bulk, family, card, _authored())
                if cards:
                    _invalidate_results()
                for line in report:
                    st.success(line)
                for err in errors:
                    st.error(err)
                for spec in resolved:
                    specs.pop((spec.mloads_sid, spec.label), None)


# ---------------------------------------------------------------------------
# Tab entry point
# ---------------------------------------------------------------------------

def render_sol144_authoring(bulk: BulkData) -> None:
    st.subheader("Aeroelastic Authoring")
    st.caption(
        "Author the SOL 144 / MLOADS condition cards, apply them to the "
        "in-session model, then reference them from the Case Control tab.  "
        "Applied cards are exported inline in the driver BDF."
    )
    tab_surf, tab_trim, tab_mloads, tab_tables = st.tabs(
        ["Surfaces & States", "Trim Conditions", "Maneuver (MLOADS)", "Tables"]
    )
    with tab_surf:
        _family_editor(bulk, "aestat", "AESTAT — rigid-body trim variable", _aestat_form)
        _family_editor(bulk, "aesurf", "AESURF — control surface", _aesurf_form)
        _family_editor(bulk, "aelist", "AELIST — control-surface box list", _aelist_form)
        _family_editor(bulk, "suport", "SUPORT — free-body support DOFs", _suport_form)
    with tab_trim:
        _render_preset_panel(bulk)
        _family_editor(bulk, "trim", "TRIM — static trim condition", _trim_form)
        _family_editor(bulk, "trimvar", "TRIMVAR — variable bounds (over-determined)", _trimvar_form)
        _family_editor(bulk, "trimobj", "TRIMOBJ — weighted objective (over-determined)", _trimobj_form)
        _family_editor(bulk, "trimcon", "TRIMCON — inequality constraints (over-determined)", _trimcon_form)
        _family_editor(bulk, "diverg", "DIVERG — divergence sweep", _diverg_form)
    with tab_mloads:
        _render_increment_builder(bulk)
        _family_editor(bulk, "mldtrim", "MLDTRIM — initial-condition trim", _mldtrim_form)
        _family_editor(bulk, "mldtime", "MLDTIME — integration window", _mldtime_form)
        _family_editor(bulk, "mldcomd", "MLDCOMD — pilot command histories", _mldcomd_form)
        _family_editor(bulk, "mldprnt", "MLDPRNT — ASCII time-history output", _mldprnt_form)
        _family_editor(bulk, "mloads", "MLOADS — transient maneuver driver", _mloads_form)
    with tab_tables:
        _render_table_generator(bulk)
        _family_editor(bulk, "tabled1", "TABLED1 — tabular time function", _tabled1_form)

    _render_authoring_export(bulk)


def _render_authoring_export(bulk: BulkData) -> None:
    """Download buttons for the authored driver deck and the cards snippet."""
    authored = _authored()
    if not any(authored.values()):
        return
    st.divider()
    st.markdown("**Export authored cards**")
    cc = st.session_state.get("case_control")
    errors: list[str] = []
    if cc is not None and cc.sol == 144:
        errors, _ = logic.validate_sol144_authoring(
            bulk, cc,
            unresolved_increments=list(
                st.session_state.get("mldcomd_increments", {}).values()),
            file_sids=st.session_state.get("file_card_sids"),
            authored=authored,
        )
        for err in errors:
            st.error(err)
    stem = (st.session_state.get("_uploaded_filename") or "model").rsplit(".", 1)[0]
    col1, col2 = st.columns(2)
    if cc is not None:
        col1.download_button(
            "Download run BDF (driver + INCLUDEs)",
            data=export_sol144_bdf(cc, bulk, authored),
            file_name=logic.suggest_run_name(stem, cc),
            mime="text/plain",
            disabled=bool(errors),
            key="auth_export_driver",
        )
    else:
        col1.caption("Define a case control to export a run deck.")
    col2.download_button(
        "Download authored cards only (.bdf snippet)",
        data=write_authored_block(
            bulk, authored,
            "Authored in the sbeam viewer (SOL 144 / MLOADS authoring tab)"),
        file_name=f"{stem}_authored_cards.bdf",
        mime="text/plain",
        key="auth_export_cards",
    )
