"""Build hook: copy the user documentation into the wheel (#128).

Everything else about the build is in ``pyproject.toml``.  The pages stay under ``docs/``
in the repository; a built wheel carries a copy under ``sbeam_tools/_docs`` so the viewer
can show the documentation of the installed version without a network.  The list of what
is copied is owned by ``sbeam_tools/common/user_docs.py``.

An editable install copies nothing: it runs from the checkout, and ``docs_root`` reads the
pages from there.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


def _user_docs():
    """``sbeam_tools.common.user_docs`` loaded by path: the build environment has none of
    the package's dependencies, so the package itself is not imported."""
    name = "_sbeam_user_docs"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "sbeam_tools" / "common" / "user_docs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # dataclasses looks the module up by name
    spec.loader.exec_module(module)
    return module


class BuildPyWithDocs(build_py):
    def run(self):
        super().run()
        if getattr(self, "editable_mode", False):
            return
        docs = _user_docs()
        target = Path(self.build_lib) / "sbeam_tools" / docs.PACKAGED_FOLDER
        shutil.rmtree(target, ignore_errors=True)      # a page removed since the last build
        for name in docs.shipped_files(ROOT):
            source = ROOT / name
            if not source.is_file():
                raise FileNotFoundError(
                    f"user documentation file {name} is listed in "
                    "sbeam_tools/common/user_docs.py but is not in the source tree")
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target / name)


setup(cmdclass={"build_py": BuildPyWithDocs})
