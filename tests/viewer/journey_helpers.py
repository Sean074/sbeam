"""Shared steps for the viewer AppTests that open a sample deck and interact with it."""
from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
from streamlit.testing.v1 import AppTest


def _sbeam_app():
    from sbeam_tools.viewer.app import main
    main()


def _open(name: str) -> AppTest:
    at = AppTest.from_function(_sbeam_app, default_timeout=600)
    at.run()
    at.selectbox(key="sample_pick").set_value(name)
    at.button(key="open_deck").click()
    at.run()
    _assert_clean(at, "open")
    return at


def _assert_clean(at: AppTest, step: str) -> None:
    assert not at.exception, (step, [str(e.value) for e in at.exception])
    assert not at.error, (step, [e.value for e in at.error])


def _submit(at: AppTest, form_id: str) -> None:
    buttons = [b for b in at.button if b.label == "Apply" and b.form_id == form_id]
    assert len(buttons) == 1, (form_id, len(buttons))
    buttons[0].click()
    at.run()


def differences(a: Any, b: Any, where: str = "") -> list[str]:
    """Every place two parsed objects differ, as ``path: a != b`` lines."""
    if dataclasses.is_dataclass(a) and dataclasses.is_dataclass(b) and type(a) is type(b):
        out: list[str] = []
        for f in dataclasses.fields(a):
            out += differences(getattr(a, f.name), getattr(b, f.name), f"{where}.{f.name}")
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{where}[{k!r}]: only in one" for k in set(a) ^ set(b)]
        for k in set(a) & set(b):
            out += differences(a[k], b[k], f"{where}[{k!r}]")
        return out
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return [f"{where}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += differences(x, y, f"{where}[{i}]")
        return out
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        same = np.shape(a) == np.shape(b) and bool(np.array_equal(a, b, equal_nan=True))
        return [] if same else [f"{where}: arrays differ"]
    if isinstance(a, float) and isinstance(b, float) and a != a and b != b:
        return []                                    # NaN on both sides
    return [] if a == b else [f"{where}: {a!r} != {b!r}"]
