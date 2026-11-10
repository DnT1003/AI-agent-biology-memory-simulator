"""Run Aura through simulated days and print a human-likeness report.

    python scripts/simulate_week.py --seed 7 --days 7 [--json out.json] [--messages]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.sim_week import format_report, run_week  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", help="also write the full report as JSON")
    parser.add_argument("--messages", action="store_true", help="list what Aura said")
    args = parser.parse_args(argv)

    report = run_week(seed=args.seed, days=args.days)
    out = sys.stdout
    out.write(format_report(report) + "\n")
    if args.messages:
        out.write("\n")
        for _, stamp, kind, text in report.aura_messages:
            out.write(f"{stamp} [{kind}] {text}\n")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
