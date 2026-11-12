#!/usr/bin/env bash
# Builds and runs a pilot: one recorded round plus the plain round at a quarter of the durations, with no quiet-machine
# gate. Run on Windows (Git Bash) from the repo root. PY is a Python 3.12 with psutil and pywinpty.
# usage: tools/pilot.sh RESULTS_NAME
set -uo pipefail
cd "$(dirname "$0")/.."
NAME=${1:?usage: tools/pilot.sh RESULTS_NAME}
PY=${PY:-python}
export PATH="/c/Program Files/nodejs:$PATH"
tools/build.sh || exit 1
BENCH_NO_GATE=1 BENCH_SECONDS_SCALE=${SCALE:-0.25} "$PY" tools/session.py "results/$NAME" 1
echo "pilot exit $? $(date +%T)"
