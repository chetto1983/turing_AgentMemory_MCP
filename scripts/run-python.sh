#!/usr/bin/env bash
# run-python.sh — resolve the project's Python interpreter and exec the given args.
#
# Bare `python` on this Windows-primary repo can resolve to the broken Windows Store
# app-execution alias instead of the project venv (see CLAUDE.md). Lefthook commands
# invoke this wrapper instead of `python` directly so pre-commit/pre-push checks work
# whether or not the venv is activated in the invoking shell, and stay portable to a
# Linux/macOS CI venv layout. No embedded shell quoting lives in lefthook.yml itself —
# lefthook's Windows command execution does not reliably preserve nested single/double
# quotes, so all quoting-sensitive logic is kept here instead.
set -euo pipefail

PY=".venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  PY=".venv/bin/python"
fi
if [ ! -x "$PY" ]; then
  PY="python"
fi

exec "$PY" "$@"
