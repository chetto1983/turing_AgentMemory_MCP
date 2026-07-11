#!/usr/bin/env bash
# run-fast-tests.sh — pre-push fast pytest subset (L-03).
#
# The `-m "not slow and not integration and not gpu"` marker expression contains
# spaces, and lefthook's Windows command execution does not reliably preserve quoted
# multi-word arguments passed inline in a `run:` value (verified: quotes/words get
# mangled, producing a pytest marker-expression parse error). Keeping the quoted
# expression inside this script instead of lefthook.yml sidesteps that entirely.
set -euo pipefail

exec bash scripts/run-python.sh -m pytest -q -m "not slow and not integration and not gpu"
