"""End-of-pull truth report.

Runs as the LAST step of "Get StatsPlus Ratings.bat". Ignores what the
legs above claimed and looks at the files on disk: for each league, when
was the app data actually written?

Each league pulls with its own StatsPlus token (StatsPlus Tokens.txt
saves one per league), else with the browser cookie. A browser login is
PER-LEAGUE (measured 2026-08-26): it updates only the league the browser is
signed into. So a league with no token and no login this run is NORMAL: it
is reported calmly with its data date and the one-line way to update it. A
league that has a saved token but did not update is flagged: the reason is
printed above the report. Alarm language is reserved for the case where
NOTHING updated (token expired or unknown, bad cookie, network, StatsPlus
down).

Each league also shows whether a StatsPlus token is saved and when, with a
warning when it is more than 80 days old (tokens expire after 90 days). The
token itself is never shown.

Exit code: 0 when at least one league's ratings are fresh, 1 when none are.

--leagues A,B reports only those leagues (the Control page's per-league update
task passes its own league). With no flag it reports TGS and BLM, the ones of
those two that are enabled online leagues in the settings.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(REPO, "tgs-viz", "public", "data")
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402

SLUGS = ST.slug_map()
LEAGUES = [lg for lg in ("TGS", "BLM") if lg in SLUGS]
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


def _game_date(league_dir):
    """The in-game date the pull wrote into metadata.json (Phase 3), or None."""
    try:
        with open(os.path.join(league_dir, "metadata.json"), encoding="utf-8") as fh:
            gd = json.load(fh).get("game_date")
        return str(gd)[:10] if gd else None
    except (OSError, ValueError, AttributeError):
        return None


def _token_lines(lg):
    """(True when a StatsPlus token is saved for lg, report lines about it).
    The lines give the save date and the age warning, never the token."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import statsplus_token as T
        slug = ST.slug(lg)
        info, warn = T.saved_info(slug), T.age_warning(slug)
    except Exception as e:
        return False, [f"       StatsPlus token: could not be read ({type(e).__name__})"]
    if not info:
        return False, ["       StatsPlus token: none saved (paste one into StatsPlus Tokens.txt)"]
    days = info.get("days")
    ago = {None: "", 0: " (today)", 1: " (1 day ago)"}.get(days, f" ({days} days ago)")
    when = f"saved {info.get('saved')}{ago}"
    lines = [f"       StatsPlus token: {when}"]
    if warn:
        lines.append(f"       WARNING: {warn}")
    return True, lines


def _leagues_arg():
    """The --leagues list (A,B), else LEAGUES."""
    if "--leagues" not in sys.argv:
        return list(LEAGUES)
    i = sys.argv.index("--leagues") + 1
    raw = sys.argv[i] if i < len(sys.argv) else ""
    names = [x.strip().upper() for x in raw.split(",") if x.strip()]
    if not names:
        print("  --leagues needs league ids, for example --leagues TGS,BLM")
        sys.exit(2)
    return names


def main():
    max_age_min = 30.0
    if "--max-age-min" in sys.argv:
        max_age_min = float(sys.argv[sys.argv.index("--max-age-min") + 1])
    leagues = _leagues_arg()
    now = time.time()
    fresh_lgs, stale_lgs = [], []
    has_token = {}
    print()
    print("  ================= DATA DATE REPORT =================")
    for lg in leagues:
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
        has_token[lg], token_lines = _token_lines(lg)
        if oldest is None:
            print(f"  {lg}: no ratings files at all in public/data/{lg}")
            for ln in token_lines:
                print(ln)
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
        gd = _game_date(d)
        if gd:
            print(f"       in-game date: {gd}")
        for ln in token_lines:
            print(ln)
        if missing:
            print(f"       missing files: {', '.join(missing)}")
        # board dates are informational - they only move when their source does
        for fn in BOARD_FILES:
            p = os.path.join(d, fn)
            if fn == "metadata.json" and gd:
                continue        # every pull now writes its game_date, so its file time is the pull's
            if os.path.exists(p):
                m = os.path.getmtime(p)
                print(f"       {fn}: {time.strftime('%Y-%m-%d %H:%M', time.localtime(m))} ({_age_str(m, now)})")
    print("  ====================================================")
    print()
    if fresh_lgs and stale_lgs:
        for lg in stale_lgs:
            if has_token.get(lg):
                print(f"  !!!! {lg} did NOT update although its token is saved. Scroll up for the reason,")
                print("  !!!! then run this bat again. Until then it keeps the data shown above.")
            else:
                print(f"  To update {lg} too: paste its token into StatsPlus Tokens.txt (or open")
                print(f"  statsplus.net/{ST.slug(lg)} in your browser, logged in), then run this bat again.")
                print("  Until then it keeps the data shown above.")
        print("  Reload the web app to see the fresh data.")
        sys.exit(0)
    if fresh_lgs:
        what = {1: "Updated.", 2: "Both leagues updated."}.get(len(fresh_lgs), "All leagues updated.")
        print(f"  {what} Reload the web app to see the new data.")
        sys.exit(0)
    if len(leagues) == 1:
        print(f"  !!!! {leagues[0]} not pulled this run - that is a real failure (token expired or unknown,")
    else:
        print("  !!!! NOTHING updated this run - that is a real failure (token expired or unknown,")
    print("  !!!! bad cookie, network, or StatsPlus down). Scroll up for the reason and try again.")
    sys.exit(1)


if __name__ == "__main__":
    main()
