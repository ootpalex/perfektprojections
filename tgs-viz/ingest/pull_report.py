"""End-of-pull truth report.

Runs as the LAST step of "Get StatsPlus Ratings.bat". Ignores what the
legs above claimed and looks at the files on disk: for each league, when
was the app data actually written?

StatsPlus logins are PER-LEAGUE (measured 2026-08-26): one run updates the
league the browser is signed into; the other league keeps its last data.
That is NORMAL, so a not-pulled league is reported calmly with its data
date and the one-line way to update it. Alarm language is reserved for the
case where NOTHING updated (bad cookie, network, StatsPlus down).

Exit code: 0 when at least one league's ratings are fresh, 1 when none are.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(REPO, "tgs-viz", "public", "data")

LEAGUES = ["TGS", "BLM"]
SLUGS = {"TGS": "tgs", "BLM": "blm"}
# The files the pull rewrites for a league it updates.
RATINGS_FILES = ["hitters.json", "pitchers.json", "hitters_park.json", "pitchers_park.json"]
# Informational boards: shown with their dates, but they never fail the run
# (they refresh only when their OOTP export / API source is available).
# hitters_fa.json is NOT listed: the app no longer reads it (FA pages derive
# free agents live from the pull since 2026-08-21).
BOARD_FILES = ["hitters_draft.json", "r5.json", "iafa.json", "metadata.json"]


def _age_str(mtime, now):
    mins = (now - mtime) / 60.0
    if mins < 90:
        return f"{mins:.0f} min ago"
    hours = mins / 60.0
    if hours < 36:
        return f"{hours:.0f} hours ago"
    return f"{hours / 24.0:.1f} days ago"


def main():
    max_age_min = 30.0
    if "--max-age-min" in sys.argv:
        max_age_min = float(sys.argv[sys.argv.index("--max-age-min") + 1])
    now = time.time()
    fresh_lgs, stale_lgs = [], []
    print()
    print("  ================= DATA DATE REPORT =================")
    for lg in LEAGUES:
        d = os.path.join(DATA, lg)
        oldest = None      # the stalest ratings file decides the league verdict
        missing = []
        for fn in RATINGS_FILES:
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                missing.append(fn)
                continue
            m = os.path.getmtime(p)
            if oldest is None or m < oldest:
                oldest = m
        if oldest is None:
            print(f"  {lg}: no ratings files at all in public/data/{lg}")
            stale_lgs.append(lg)
            continue
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(oldest))
        fresh = (now - oldest) <= max_age_min * 60
        if fresh:
            print(f"  {lg}: OK - updated this run")
            fresh_lgs.append(lg)
        else:
            print(f"  {lg}: not pulled this run - app is serving data from {stamp} ({_age_str(oldest, now)})")
            stale_lgs.append(lg)
        if missing:
            print(f"       missing files: {', '.join(missing)}")
        # board dates are informational - they only move when their source does
        for fn in BOARD_FILES:
            p = os.path.join(d, fn)
            if os.path.exists(p):
                m = os.path.getmtime(p)
                print(f"       {fn}: {time.strftime('%Y-%m-%d %H:%M', time.localtime(m))} ({_age_str(m, now)})")
    print("  ====================================================")
    print()
    if fresh_lgs and stale_lgs:
        for lg in stale_lgs:
            print(f"  To update {lg} too: open statsplus.net/{SLUGS.get(lg, lg.lower())} in your browser")
            print("  (logged in), then run this bat again. Until then it keeps the data shown above.")
        print("  Reload the web app to see the fresh data.")
        sys.exit(0)
    if fresh_lgs:
        print("  Both leagues updated. Reload the web app to see the new data.")
        sys.exit(0)
    print("  !!!! NOTHING updated this run - that is a real failure (bad/expired cookie,")
    print("  !!!! network, or StatsPlus down). Scroll up for the reason and try again.")
    sys.exit(1)


if __name__ == "__main__":
    main()
