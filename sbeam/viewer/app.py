from __future__ import annotations

import os
import re
import tempfile
import warnings

import streamlit as st

from sbeam.parser.bdf_reader import parse_bdf, parse_bulk_file
from sbeam.viewer.geometry import build_model_figure


def _init_session_state() -> None:
    defaults: dict = {
        "bulk_data": None,
        "case_control": None,
        "case_controls": [],
        "sol101_results": None,
        "sol103_results": None,
        "selected_gid": None,
        "selected_eid": None,
        "deform_scale": 1.0,
        "active_mode": 1,
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
    tmp_path: str | None = None
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


def _show_parse_summary() -> None:
    bulk = st.session_state.bulk_data
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


def main() -> None:
    st.set_page_config(page_title="sbeam", layout="wide")
    st.title("sbeam — Simple Beam FEA")
    _init_session_state()

    with st.sidebar:
        st.header("Model")
        uploaded = st.file_uploader(
            "Upload BDF / DAT file",
            type=["bdf", "dat"],
            key="file_uploader",
        )

    if uploaded is not None:
        _handle_upload(uploaded)

    if st.session_state._parse_error is not None:
        st.error(f"Parse error: {st.session_state._parse_error}")
        return

    if st.session_state.bulk_data is None:
        st.info("Upload a BDF or DAT file to begin.")
        return

    _show_parse_summary()
    _show_warnings()
    st.plotly_chart(
        build_model_figure(st.session_state.bulk_data),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
