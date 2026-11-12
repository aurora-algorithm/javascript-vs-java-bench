#!/usr/bin/env python3
"""Runs a command pinned to a set of logical CPUs; on Windows the command and its own children inherit the mask.

usage: python pin.py CPUS COMMAND...        CPUS like 0-7 or 8,9,10,11
"""
import subprocess
import sys

import psutil


def parse_cpus(spec: str) -> list[int]:
    cpus: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        cpus += range(int(lo), int(hi or lo) + 1)
    return cpus


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    if hasattr(psutil.Process, "cpu_affinity"):
        psutil.Process().cpu_affinity(parse_cpus(sys.argv[1]))
    else:
        print("pin.py: no CPU affinity on this OS (smoke test only)", file=sys.stderr)
    return subprocess.call(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
