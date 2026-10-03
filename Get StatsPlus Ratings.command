#!/bin/bash
# Get StatsPlus Ratings for one league: runs the league's "Update <league>" task (update.<id>:
# ratings, draft board, trends, dev signals, ML scores, data-date report). The Windows
# "Get StatsPlus Ratings.bat" runs get_ratings, which needs TGS and BLM both turned on.
# DASH_LEAGUE picks the league (default SSB); DASH_PY overrides the interpreter.
cd "$(dirname "$0")" || exit 1
PY="${DASH_PY:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi
"$PY" tgs-viz/tools/run_task.py "update.${DASH_LEAGUE:-SSB}" "$@"
rc=$?
read -rp "Press Enter to close. "
exit $rc
