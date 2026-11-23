#!/usr/bin/env python3
"""Builds every level of levels/ : checks it, solves it, and writes puzzles/<name>.json and
puzzles/<name>.solution.json for the levels that pass.

    python tools/build.py                    all levels
    python tools/build.py --only 02          the levels whose file name contains "02"
    python tools/build.py --solve-seconds 15 give the search more time (default 8)
    python tools/build.py --no-write         only check

Exit code 1 when a level fails. A level file defines build() -> Puzzle (see levels/_template.py)."""
import glob
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import gear_kit as K  # noqa: E402


def main(argv):
    only = argv[argv.index("--only") + 1] if "--only" in argv else ""
    seconds = float(argv[argv.index("--solve-seconds") + 1]) if "--solve-seconds" in argv else 8.0
    write = "--no-write" not in argv
    files = sorted(f for f in glob.glob(os.path.join(ROOT, "levels", "level_*.py")) if only in os.path.basename(f))
    if not files:
        print("no level files found")
        return 1
    results = []
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            res = K.report(module.build(), solve_seconds=seconds, write_dir=os.path.join(ROOT, "puzzles") if write else None, name=name)
            results.append((name, res["ok"], len(res["warnings"])))
        except Exception:
            traceback.print_exc()
            results.append((name, False, 0))
        print()
    print("=" * 60)
    for name, ok, warnings in results:
        print("%-40s %s%s" % (name, "PASS" if ok else "FAIL", "  (%d warning(s))" % warnings if warnings else ""))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
