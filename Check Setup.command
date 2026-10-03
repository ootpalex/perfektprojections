#!/bin/bash
# Check Setup: the macOS twin of "Check Setup.bat". DASH_PY overrides the interpreter.
cd "$(dirname "$0")" || exit 1
PY="${DASH_PY:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi
"$PY" tgs-viz/tools/run_task.py doctor "$@"
rc=$?
read -rp "Press Enter to close. "
exit $rc
