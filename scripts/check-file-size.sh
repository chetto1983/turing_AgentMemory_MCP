#!/usr/bin/env bash
# check-file-size.sh — enforce the 600-LOC cap (CLAUDE.md / D-08). Scans ALL tracked
# *.py files (src, tests, scripts) with NO allowlist/exemption.
#
# Usage: bash scripts/check-file-size.sh [cap]   (default cap: 600)
set -euo pipefail

CAP="${1:-600}"
if ! [[ "$CAP" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 [cap]" >&2
  exit 2
fi

TARGETS=$(git ls-files '*.py' || true)
if [ -z "$TARGETS" ]; then
  echo "check-file-size: no *.py files matched; nothing to check."
  exit 0
fi

# Process-substitution (not a `<<<` here-string): on Windows Git Bash (MSYS/busybox)
# a here-string mangles the final list entry, which `wc` then can't open and `set -e`
# turns into a false commit-blocking failure. Process substitution keeps the loop in
# the current shell so the violations counter + exit code still propagate correctly.
violations=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue   # tracked-but-deleted-in-worktree (e.g. mid-split) is not an error
  lines=$(wc -l < "$f" | tr -d '[:space:]')
  if [ "$lines" -gt "$CAP" ]; then
    printf "OVER CAP: %s (%d LOC > %d)\n" "$f" "$lines" "$CAP"
    violations=$((violations + 1))
  fi
done < <(printf '%s\n' "$TARGETS")

if [ "$violations" -gt 0 ]; then
  echo ""
  echo "check-file-size: $violations file(s) exceed the ${CAP}-LOC cap." >&2
  echo "No allowlist. Refactor on touch: split <name>_<concern>.py." >&2
  exit 1
fi
echo "check-file-size: all tracked *.py files within the ${CAP}-LOC cap."
