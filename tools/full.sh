#!/usr/bin/env bash
# The full session: builds, then runs ROUNDS recorded rounds + the plain round. Run on Windows (Git Bash) from the
# repo root. PY is a Python 3.12 with psutil and pywinpty.
# usage: tools/full.sh RESULTS_NAME [ROUNDS=5]
set -uo pipefail
cd "$(dirname "$0")/.."
NAME=${1:?usage: tools/full.sh RESULTS_NAME [ROUNDS]}
PY=${PY:-python}
export PATH="/c/Program Files/nodejs:$PATH"
tools/build.sh || exit 1
"$PY" tools/session.py "results/$NAME" "${2:-5}"
echo "session exit $? $(date +%T)"
