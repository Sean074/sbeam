"""sbeam command-line solver entry point."""

import argparse
import sys
from pathlib import Path

from sbeam.parser.bdf_reader import parse_bdf
from sbeam.results.f06_writer import _build_f06_sol101_text, _build_f06_sol103_text


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sbeam",
        description="sbeam — Simple Beam FEA solver",
    )
    parser.add_argument("bdf", help="Input BDF file (must contain a SOL case control statement)")
    args = parser.parse_args()

    bdf_path = Path(args.bdf).resolve()
    if not bdf_path.exists():
        sys.exit(f"Error: file not found: {bdf_path}")

    f06_path = bdf_path.with_suffix(".f06")

    try:
        cc, bulk = parse_bdf(str(bdf_path))
    except Exception as exc:
        sys.exit(f"Parse error: {exc}")

    try:
        if cc.sol == 101:
            from sbeam.solver.sol101 import run_sol101
            results = {sc.subcase_id: run_sol101(bulk, sc) for sc in cc.subcases}
            build_text = _build_f06_sol101_text
        elif cc.sol == 103:
            from sbeam.solver.sol103 import run_sol103
            results = {sc.subcase_id: run_sol103(bulk, sc) for sc in cc.subcases}
            build_text = _build_f06_sol103_text
        else:
            sys.exit(f"Error: SOL {cc.sol} is not supported")
    except Exception as exc:
        sys.exit(f"Solver error: {exc}")

    with open(f06_path, "w") as fh:
        for sc_id, result in results.items():
            fh.write(build_text(cc, bulk, result, sc_id))

    print(f"Written: {f06_path}")
