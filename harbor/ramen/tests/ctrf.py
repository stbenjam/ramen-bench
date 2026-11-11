"""Write Reward Kit's per-criterion results as a CTRF test report."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def report(details: dict, start: int, stop: int) -> dict:
    tests = []
    for criterion in details["reward"]["criteria"]:
        test = {
            "name": criterion["name"],
            "status": "passed" if criterion["value"] == 1 else "failed",
            "duration": 0,
        }
        if criterion.get("reasoning"):
            test["message"] = criterion["reasoning"]
        if criterion.get("error"):
            test["trace"] = criterion["error"]
        tests.append(test)
    passed = sum(test["status"] == "passed" for test in tests)
    return {
        "results": {
            "tool": {"name": "rewardkit"},
            "summary": {
                "tests": len(tests),
                "passed": passed,
                "failed": len(tests) - passed,
                "skipped": 0,
                "pending": 0,
                "other": 0,
                "start": start,
                "stop": stop,
            },
            "tests": tests,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True, help="epoch milliseconds")
    parser.add_argument("--logs", type=Path, default=Path("/logs/verifier"))
    args = parser.parse_args()
    details = json.loads((args.logs / "reward-details.json").read_text())
    ctrf = report(details, args.start, round(time.time() * 1000))
    (args.logs / "ctrf.json").write_text(json.dumps(ctrf, indent=2) + "\n")


if __name__ == "__main__":
    main()
