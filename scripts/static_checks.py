#!/usr/bin/env python3
"""Run the Harbor task's static checks over every registered bowl into checks.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harbor/ramen/tests"))
from check import check

OUTPUT = ROOT / "checks.json"


def build() -> str:
    registry = json.loads((ROOT / "runs/registry.json").read_text())
    results = {}
    for manifest in registry["runs"]:
        run_dir = (ROOT / "runs" / manifest).parent
        run = json.loads((run_dir / "run.json").read_text())
        failures = check(run_dir / run["artifacts"]["result"]).values()
        violations = list(dict.fromkeys(item for items in failures for item in items))
        results[run["id"]] = {"reward": int(not violations), "violations": violations}
    document = {
        "schemaVersion": 1,
        "checker": "harbor/ramen/tests/check.py",
        "results": results,
    }
    return json.dumps(document, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update checks.json")
    args = parser.parse_args(argv)
    expected = build()
    if args.write:
        OUTPUT.write_text(expected)
        return 0
    if not OUTPUT.is_file() or OUTPUT.read_text() != expected:
        print("checks.json is stale; run scripts/static_checks.py --write")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
