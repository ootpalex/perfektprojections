"""
pull_order.py - one rule for the ORDER of the pulls in the ratings archive.

The archive (ratings_history.db) holds two kinds of TGS / BLM pulls:
  live pulls   taken on a real day by refresh.py; real_date = the real day
  asof pulls   past rating snapshots from StatsPlus /ratings/?date=YYYY-MM-DD
               (ingest/statsplus_history.py); real_date = the in-game date
               asked for, the same rule the DEV dump pulls use
So real_date does not sort the archive any more. Every reader sorts by the
IN-GAME date of the pull (pulls.game_date) through ordered() below.

In-game date of a pull, first hit wins:
  1. the pulls.game_date column (refresh.py stores it from /date at pull time;
     statsplus_history.py stores the requested date)
  2. backtest/pull_game_dates_<LG>.json (the birth-date fit of growth_lenses),
     only while its "_real_dates" entry still matches the pull
  3. real_date for an asof or dump pull (their real_date is the in-game date)

Order: (in-game date, real_ts, pull_id). When a live pull has no in-game date:
  - no asof pull in the league: the old order (real_date, pull_id), which is
    the in-game order for live pulls
  - asof pulls in the league: the undated live pull sorts right after the live
    pull before it (real order), and a warning is printed once

"The latest pull" of a league = the newest pull that is NOT an asof pull
(latest_live): the app values always come from the live pull.

RATINGS_ARCHIVE_ROOT (environment, tests only): a folder that holds a copy of
ratings_history.db, vintages/ and pull_game_dates_<LG>.json. Every archive
reader and writer uses it in place of tgs-viz/backtest.
"""
import os
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
ARCHIVE_ROOT = os.environ.get("RATINGS_ARCHIVE_ROOT") or HERE
DB_PATH = os.path.join(ARCHIVE_ROOT, "ratings_history.db")
VINTAGES_DIR = os.path.join(ARCHIVE_ROOT, "vintages")

ASOF = "asof"                     # source of a past-date StatsPlus snapshot
SELF_DATED = ("asof", "dump")     # sources whose real_date IS the in-game date

_warned = set()


def game_dates_path(league):
    return os.path.join(ARCHIVE_ROOT, f"pull_game_dates_{league}.json")


def has_game_date_column(conn):
    return any(r[1] == "game_date" for r in conn.execute("PRAGMA table_info(pulls)"))


def ensure_game_date_column(conn):
    """Add pulls.game_date when it is missing, then fill every blank one the
    archive already knows (the JSON fit, or real_date for asof / dump pulls).
    Needs a writable connection. Returns the number of pulls filled."""
    if not has_game_date_column(conn):
        conn.execute("ALTER TABLE pulls ADD COLUMN game_date TEXT")
    rows = list(conn.execute(
        "SELECT pull_id, league, real_date, source FROM pulls WHERE game_date IS NULL OR game_date=''"))
    if not rows:
        return 0
    by_lg = {}
    for r in rows:
        by_lg.setdefault(r[1], []).append(r)
    n = 0
    for lg, rs in by_lg.items():
        js = json_game_dates(lg, [(r[0], r[2]) for r in rs])
        for pid, _lg, rd, src in rs:
            d = rd if src in SELF_DATED else js.get(pid)
            if d:
                conn.execute("UPDATE pulls SET game_date=? WHERE pull_id=?", (d, pid))
                n += 1
    conn.commit()
    return n


def json_game_dates(league, pulls):
    """{pull_id: 'YYYY-MM-DD'} from pull_game_dates_<LG>.json; pulls = rows whose
    [0] is the pull id and [1] the real date. An entry counts only while its
    stored real date still matches the pull."""
    try:
        with open(game_dates_path(league), encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return {}
    real = stored.get("_real_dates") or {}
    out = {}
    for p in pulls:
        k = str(p[0])
        if k in stored and real.get(k) == p[1] and _iso(stored[k]):
            out[p[0]] = stored[k]
    return out


def _iso(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10]).isoformat()
    except (TypeError, ValueError):
        return None


def game_dates(conn, league, rows):
    """{pull_id: 'YYYY-MM-DD'} for rows (pull_id, real_date, real_ts, source, ...):
    the column, else the JSON fit, else real_date for asof / dump pulls."""
    col = {}
    if has_game_date_column(conn):
        col = {r[0]: _iso(r[1]) for r in conn.execute(
            "SELECT pull_id, game_date FROM pulls WHERE league=? AND game_date IS NOT NULL", (league,))}
    js = json_game_dates(league, [r for r in rows if not col.get(r[0])])
    out = {}
    for r in rows:
        d = col.get(r[0]) or js.get(r[0]) or (_iso(r[1]) if r[3] in SELF_DATED else None)
        if d:
            out[r[0]] = d
    return out


def ordered(conn, league, log=print):
    """(rows, game) for one league. rows = [(pull_id, real_date, real_ts, source,
    n_players)] oldest first by in-game date; game = {pull_id: 'YYYY-MM-DD'}
    (known in-game dates only)."""
    rows = [tuple(r) for r in conn.execute(
        "SELECT pull_id, real_date, real_ts, source, n_players FROM pulls WHERE league=?", (league,))]
    game = game_dates(conn, league, rows)
    return sort_rows(rows, game, league, log), game


def sort_rows(rows, game, league="", log=print):
    """rows sorted by in-game date (see the module notes)."""
    if all(r[0] in game for r in rows):
        return sorted(rows, key=lambda r: (game[r[0]], r[2] or "", r[0]))
    if not any(r[3] == ASOF for r in rows):
        return sorted(rows, key=lambda r: (r[1], r[0]))           # the old order
    # asof pulls present and a live pull has no in-game date: place it right
    # after the live pull before it (real order)
    key, last = {}, "0000-00-00"
    undated = []
    for r in sorted((r for r in rows if r[3] != ASOF), key=lambda r: (r[1], r[0])):
        if r[0] in game:
            last = game[r[0]]
        else:
            undated.append(r[0])
        key[r[0]] = last
    for r in rows:
        if r[3] == ASOF:
            key[r[0]] = game.get(r[0]) or r[1]
    if (league, tuple(undated)) not in _warned:
        _warned.add((league, tuple(undated)))
        log(f"  WARNING {league}: {len(undated)} live pull(s) have no in-game date "
            f"(pull ids {', '.join(str(x) for x in undated)}). Each one is placed right after "
            f"the live pull before it. Run: python tgs-viz/backtest/growth_lenses.py --dates "
            f"--league {league} (it measures and stores the dates).")
    return sorted(rows, key=lambda r: (key[r[0]], r[2] or "", r[0]))


def latest_live(rows):
    """The newest row that is not an asof pull (rows in game order), else the
    newest row, else None."""
    for r in reversed(rows):
        if r[3] != ASOF:
            return r
    return rows[-1] if rows else None
