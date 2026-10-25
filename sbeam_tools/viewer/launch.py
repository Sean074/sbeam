"""``sbeam-view`` — start the Streamlit viewer (issue #34).

Equivalent to ``streamlit run <path to sbeam_tools/viewer/app.py>``, so the GUI
starts without the user knowing where the package is installed.  Extra arguments
are passed through to ``streamlit run`` (e.g. ``sbeam-view --server.port 8502``).
Needs the ``viewer`` extra: ``pip install sbeam[viewer]``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    from streamlit.web import cli as stcli

    app = Path(__file__).with_name("app.py")
    sys.argv = ["streamlit", "run", str(app), *sys.argv[1:]]
    sys.exit(stcli.main())
