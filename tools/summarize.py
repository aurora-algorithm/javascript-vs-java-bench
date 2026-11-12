#!/usr/bin/env python3
"""Medians of one session: each cell's figures over its recorded rounds, and the plain round next to them.

usage: python3 tools/summarize.py results/<session>   -> results/<session>/summary.json
"""

import json
import statistics
import sys
from pathlib import Path

KEYS = ["rps", "cores_busy", "p50_ms", "p99_ms", "mem_mb_median", "health_p50_ms", "ready_s", "threads"]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    session = Path(sys.argv[1])
    lines = (session / "runs.jsonl").read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if not rows:
        sys.exit(f"{session}: no runs")
    cells = {}
    for name in dict.fromkeys(r["cell"] for r in rows):
        recorded = [r for r in rows if r["cell"] == name and r["round"] != "plain"]
        plain = next((r for r in rows if r["cell"] == name and r["round"] == "plain"), None)
        median = {k: round(statistics.median(r[k] for r in recorded), 3) for k in KEYS}
        cells[name] = {
            "rounds": len(recorded),
            "median": median,
            "rps_by_round": [round(r["rps"], 2) for r in recorded],
            "plain_rps": round(plain["rps"], 2) if plain else None,
            "plain_vs_recorded": round(plain["rps"] / median["rps"] - 1, 4) if plain else None,
        }
    summary = {"session": session.name, "cells": cells}
    (session / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    for name, c in cells.items():
        m = c["median"]
        print(f"{name:14s} {m['rps']:7.1f}/s  cores {m['cores_busy']:.2f}  plain {c['plain_vs_recorded']:+.1%}")


if __name__ == "__main__":
    main()
