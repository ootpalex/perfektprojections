"""
growth_lenses.py - development LENSES for the gap-conditioned age curves.

ratings_db.age_curves() measures rating points gained per year of age among
players whose current rating sits below their potential. This module splits
that growth by player context, ages 15-25, in the same value shape as the
personality splits: [gain_per_yr, closure_per_yr, n, years].

Lenses (keys in payload["age_curves"]["traits"]):
  WE INT LEA LOY GRD  personality H / N / L from the CURRENT pull
  PT    playing time that season (PA for hitter ratings, BF for pitcher ratings)
  PERF  performance against his own level (wOBA against the league mean)
  WAA   rank of his projected WAA among players of his age and side
  LDR   teammates with High leadership
  NEG   teammates with Low leadership

Population rules for PT / PERF / WAA / LDR / NEG:
  - the player has a real org in the OLDER pull of the pair
  - that org is not a foreign-league club (NPB / KBO; the app excludes them).
    The older pull's own file says so (its League id). A pull whose file has
    no League id (the sheet-era first pull) falls back to "has a personality
    record in today's player file", which also keeps foreign players out.
  - own side only: hitter ratings from position players, pitcher ratings from
    pitchers. A pitcher's bat has no season PA to read, and his batting ratings
    would fill the "0 PA" bucket with players who are not trying to hit.
No personality record is needed: a player who left the player file since then
still counts. WAA is the exception in practice, because the engine pass needs
bats / throws / height from today's file.
The five personality lenses need the personality record, as before.

LEAGUES ARE SEPARATE. Each league reads its own pulls, its own StatsPlus slug,
its own personality file and its own cache files. Nothing crosses.

DUMP-SOURCED LEAGUE (dump_source.py). A league whose pulls all carry source
"dump" (dump_vintages.py, OOTP's yearly CSV dump) has no StatsPlus. For it the
same lens set reads the dump instead: the in-game date of a pull is its stored
real_date; season stats come from the season dump's players_career_*_stats.csv;
level, club, leadership and the foreign flag come from the raw vintage rows.
WAA is dropped with a note: it needs the projection engine, which has no
calibration for such a league. The StatsPlus path below is untouched.

IN-GAME DATE OF A PULL. The archive column pulls.game_date holds it when it is
known (refresh.py stores /date at pull time; an asof snapshot from
ingest/statsplus_history.py stores the date it asked for) and wins. Else each
pull's in-game date is MEASURED from birth dates: StatsPlus /players gives date_of_birth, the
pull gives every player's integer age, and only one in-game day agrees with all
of them. Checked against the one known point (TGS snapshot manifest, real
2026-08-05 = in-game 2044-10-08): the fit returns 2044-10-08.
Fallbacks when birth dates cannot date a pull:
  1. the newest pull, when it was taken today, reads statsplus.fetch_date()
  2. any other pull walks from the nearest dated pull by the pair spans,
     computed the same way age_curves computes them (share of org players
     whose integer age ticked up). Walked dates are estimates: never stored.
Measured dates persist in pulls.game_date (when the connection can write) and
in backtest/pull_game_dates_<LG>.json as
{pull_id: "YYYY-MM-DD"} and are never overwritten. Two reserved keys ride
along: "_how" ({pull_id: "birth dates" | "today"}) and "_real_dates"
({pull_id: real_date}). The second only detects a renumbered database: an
entry whose real date no longer matches the pull is ignored.

SEASON STATS. One file per (league, year) in backtest/.lens_cache/. A season
is FINAL once the in-game date reaches April 1 of the next year (winter-league
rows keep landing under the old year after October). A final season is cached
for good. A season is USABLE for PT / PERF when it is final or its as-of date
is on or after October 1 of that season (regular schedules complete). Before
October 1 the season is not fetched: its pull pairs are left out of PT / PERF
and counted in lens_info, so an April pair never reads June totals. From
October 1 until final, the season is fetched again on every export.
Cache guards: a feed with 0 rows, or a top-level league with no rows, raises
and caches nothing. A final table smaller than the last cached copy is never
written as final. A cached file must match its league and year.

LEAGUE MEAN. One wOBA mean per league id serves both sides. It comes from the
side with the larger denominator (batting PA against pitching BF of the same
league): StatsPlus drops the rows of deleted players, so the two sides
disagree by up to .020 in some minor leagues. PA and BF totals per league are
stored in the season file ("coverage").

PEOPLE CACHE. Level, club id, leadership, no-team flag and foreign flag per
pull, from the pull's own source file(s). The file stores the pull's real date
and content hash; a copy that does not match the pull is ignored and rebuilt.

FAILURE RULES. No network: PT and PERF drop with a printed note (or run from
the last cached copy, also with a note). StatsPlus refuses (a missing, bad or
expired token, a login page, a reply that is not the data): one WARNING per
league says why, and the rest of the run uses the caches without asking
StatsPlus again (the saved birth dates and season files serve; nothing is
overwritten). agecurve_fit raises: WAA drops with a printed note. ratings_db
wraps start_pair / player_buckets / finish / info / trait_meta: any exception
there drops the context lenses with a printed note and the export still ships
the five personality lenses. The export never fails here.

STATSPLUS READS. Requests carry the league's saved token on their own
(statsplus.py). /players (birth dates), /lgdata and the season stats go
through the date-keyed cache (cache=True): a reply saved under the same
in-game date in the last 6 hours serves again.

CLI:
    python growth_lenses.py --report [--league TGS] [--age 18]
    python growth_lenses.py --dates  [--league TGS]
"""
import os
import sys
import json
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import pull_order as PO     # in-game order of the pulls; archive paths  # noqa: E402
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
INGEST = os.path.join(VIZ, "ingest")
ENGINE = os.path.join(VIZ, "engine")
CACHE_DIR = os.path.join(HERE, ".lens_cache")
CACHE_VERSION = 2             # season files: one league mean for both sides, plus coverage
PEOPLE_VERSION = 2            # people files: carry the pull's real date and content hash

LEAGUE_SLUG = {"TGS": "tgs", "BLM": "blm"}
PIT_POS = ("SP", "RP", "CL")
PIT_COLS = ("STU", "HRR", "PBABIP", "CON")      # GAP_PAIRS keys that are pitcher ratings

HNL = ("H", "N", "L")
HNL_LABELS = {"H": "High", "N": "Normal", "L": "Low"}
PERSONALITY = {"WE": "Work ethic", "INT": "Intelligence", "LEA": "Leadership",
               "LOY": "Loyalty", "GRD": "Greed"}

NO_TEAM = "no team"           # PT bucket: no league team in the older pull, and 0 PA / BF
PT_BUCKETS = [NO_TEAM, "0", "1-25", "26-50", "51-100", "101-250", "251+"]
PERF_BUCKETS = ["too few", "well below", "below", "average", "above", "well above"]
WAA_BUCKETS = ["bottom 25%", "middle 50%", "top 25%"]
COUNT_BUCKETS = ["0", "1-2", "3-4", "5+"]
LENS_ORDER = ["WE", "INT", "LEA", "LOY", "GRD", "PT", "PERF", "WAA", "LDR", "NEG"]
CONTEXT_LENSES = ("PT", "PERF", "WAA", "LDR", "NEG")

# One fixed linear-weight set. It scores the player AND his league mean, so it
# only ranks a player against his own level. It is not a run-value claim.
WOBA_W = {"ubb": 0.69, "hbp": 0.72, "s": 0.89, "d": 1.27, "t": 1.62, "hr": 2.10}
PERF_MIN = 50                 # PA / BF below this = "too few"
WAA_MIN_GROUP = 8             # smallest age-and-side group that gets quartiles
NO_TEAM_LEVS = (None, "", "?", "-", "FA", "AMA", "INT")
DOB_MIN_PLAYERS = 500         # a birth-date fit needs this many players...
DOB_MIN_SHARE = 0.80          # ...this share of them agreeing on the day...
DOB_MAX_WIDTH = 3             # ...and a window no wider than this many days


# ---------------------------------------------------------------- buckets
def pt_bucket(n):
    if n <= 0:
        return "0"
    if n <= 25:
        return "1-25"
    if n <= 50:
        return "26-50"
    if n <= 100:
        return "51-100"
    if n <= 250:
        return "101-250"
    return "251+"


def perf_bucket(n, diff):
    if n < PERF_MIN or diff is None:
        return "too few"
    if diff < -0.040:
        return "well below"
    if diff < -0.015:
        return "below"
    if diff <= 0.015:
        return "average"
    if diff <= 0.040:
        return "above"
    return "well above"


def count_bucket(k):
    if k <= 0:
        return "0"
    if k <= 2:
        return "1-2"
    if k <= 4:
        return "3-4"
    return "5+"


def has_org(v):
    return v not in (None, "", "0", 0, "-")


def pair_season(d_old, d_new):
    """Season of a pull pair = in-game year of its midpoint. A midpoint in
    November-March reads the season that just ended."""
    mid = d_old + (d_new - d_old) / 2
    return mid.year - 1 if mid.month <= 3 else mid.year


def season_is_final(year, now):
    return now >= datetime.date(year + 1, 4, 1)


def season_usable(table, year):
    """True when a season table may bucket PT / PERF: the season is final, or
    its stats are as of October 1 of that season or later (regular schedules
    complete). An earlier copy holds part-season totals: an April pair would be
    bucketed by June playing time."""
    if not isinstance(table, dict) or table.get("stub"):
        return False
    if table.get("final"):
        return True
    try:
        return datetime.date.fromisoformat(str(table.get("asof"))[:10]) >= datetime.date(year, 10, 1)
    except ValueError:
        return False


# ---------------------------------------------------------------- small io
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _write_json(path, obj, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, **kw)
    os.replace(tmp, path)


def _statsplus():
    if INGEST not in sys.path:
        sys.path.insert(0, INGEST)
    import statsplus as S
    return S


_REFUSED = {}                 # league -> the StatsPlus refusal of this run (said once)


def _refusal(e):
    """True when e is statsplus.StatsPlusRefused: StatsPlus refused, or sent
    something that is not the data."""
    S = sys.modules.get("statsplus")
    return S is not None and isinstance(e, getattr(S, "StatsPlusRefused", ()))


def _note_refusal(league, e, log, then):
    """Remember a StatsPlus refusal for the league and print it once. Later
    reads for that league skip StatsPlus and use the caches."""
    if league not in _REFUSED:
        _REFUSED[league] = e
        log(f"  WARNING: lenses {league}: {e.user_message(league)} {then}")


def _dump_source(conn, league):
    """dump_source.DumpSource for a dump-sourced league, else None (a StatsPlus
    league, or the module missing). Never raises."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import dump_source
        return dump_source.for_league(conn, league)
    except Exception:
        return None


def _int(row, key):
    try:
        return int(float(row.get(key) or 0))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- in-game dates
def _add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:                       # Feb 29 in a non-leap year
        return d.replace(year=d.year + n, day=28)


def fit_game_date(ages, dob):
    """The in-game day that agrees with the most (birth date, integer age)
    pairs. ages: iterable of (player_id, age). Returns (date, n, share, width):
    share = players consistent with that day, width = days in the window."""
    events, n = {}, 0
    for pid, age in ages:
        b = dob.get(str(pid))
        if b is None or age is None:
            continue
        try:
            a = int(float(age))
        except (TypeError, ValueError):
            continue
        lo, hi = _add_years(b, a), _add_years(b, a + 1)
        events[lo] = events.get(lo, 0) + 1
        events[hi] = events.get(hi, 0) - 1
        n += 1
    if not n:
        return None, 0, 0.0, 0
    days = sorted(events)
    run, best, best_i = 0, -1, 0
    for i, d in enumerate(days):
        run += events[d]
        if run > best:
            best, best_i = run, i
    lo = days[best_i]
    hi = days[best_i + 1] if best_i + 1 < len(days) else lo + datetime.timedelta(days=1)
    return lo, n, best / n, (hi - lo).days


def pair_span(conn, old_id, new_id):
    """In-game years between two pulls, the age_curves way: share of shared org
    players whose integer age ticked up."""
    old = {str(r[0]): (r[1], r[2]) for r in conn.execute(
        "SELECT player_id, age, org FROM ratings WHERE pull_id=?", (old_id,))}
    n = t = 0
    for pid, age2 in conn.execute("SELECT player_id, age FROM ratings WHERE pull_id=?", (new_id,)):
        o = old.get(str(pid))
        if not o or o[1] in (None, "", "0", 0):
            continue
        try:
            d = int(float(age2)) - int(float(o[0]))
        except (TypeError, ValueError):
            continue
        if d in (0, 1):
            n += 1
            t += d
    return (t / n) if n else 0.0


def _dates_path(league):
    return PO.game_dates_path(league)


def _dob_map(league, online, log):
    """{player_id: date}. Birth dates never change, so the cached copy stays
    valid offline; a live fetch only adds players."""
    path = os.path.join(CACHE_DIR, f"{league}_dob.json")
    raw = _read_json(path) or {}
    if online and league not in _REFUSED:
        try:
            S = _statsplus()
            for r in S.fetch_players(S.normalize_base(LEAGUE_SLUG[league]), cache=True):
                pid, d = str(r.get("ID") or "").strip(), str(r.get("date_of_birth") or "").strip()
                if pid and d:
                    raw[pid] = d
            _write_json(path, raw)
        except Exception as e:
            if _refusal(e):
                _note_refusal(league, e, log, f"Birth dates come from the saved copy ({len(raw)} players)."
                              if raw else "No birth dates are saved, so undated pulls stay undated.")
            else:
                log(f"  lenses {league}: birth dates not fetched ({type(e).__name__}); "
                    f"{'using the cached copy' if raw else 'none cached'}")
    out = {}
    for pid, d in raw.items():
        try:
            out[pid] = datetime.date.fromisoformat(d)
        except ValueError:
            pass
    return out


def pull_game_dates(conn, league, pulls, now=None, log=print):
    """({pull_id: date}, {pull_id: how}) for `pulls` (rows of league_pulls).
    how: 'stored' | 'birth dates' | 'today' | 'walked'. Measured dates are
    stored; walked ones are not. `now` = current in-game date or None (offline)."""
    path = _dates_path(league)
    stored = _read_json(path) or {}
    real = stored.get("_real_dates") or {}
    method = stored.get("_how") or {}
    dates, how = {}, {}
    # stored dates: pulls.game_date, else this JSON (the _real_dates guard),
    # else an asof / dump pull's own real_date (pull_order.game_dates)
    real_of = {p[0]: p[1] for p in pulls}
    for pid, d in PO.game_dates(conn, league, pulls).items():
        try:
            dates[pid] = datetime.date.fromisoformat(d)
        except ValueError:
            continue
        k = str(pid)
        from_json = k in stored and real.get(k) == real_of.get(pid) and stored[k] == d
        how[pid] = method.get(k, "stored") if from_json else "pull record"
    missing = [p for p in pulls if p[0] not in dates]
    fresh = {}
    if missing:
        dob = _dob_map(league, now is not None, log)
        for p in missing:
            if not dob:
                break
            d, n, share, width = fit_game_date(
                conn.execute("SELECT player_id, age FROM ratings WHERE pull_id=?", (p[0],)), dob)
            if d and n >= DOB_MIN_PLAYERS and share >= DOB_MIN_SHARE and width <= DOB_MAX_WIDTH:
                fresh[p[0]] = (d, "birth dates")
            else:
                log(f"  lenses {league}: pull {p[1]} not dated from birth dates "
                    f"(n={n}, agree={share:.2f}, window={width}d)")
        newest = PO.latest_live(pulls)       # an asof snapshot is never "today"
        if (newest[0] not in dates and newest[0] not in fresh and now is not None
                and newest[1] == datetime.date.today().isoformat()):
            fresh[newest[0]] = (now, "today")
    if fresh:
        for p in pulls:
            if p[0] in fresh:
                dates[p[0]], how[p[0]] = fresh[p[0]]
                stored[str(p[0])] = dates[p[0]].isoformat()
                real[str(p[0])] = p[1]
                method[str(p[0])] = how[p[0]]
        stored["_real_dates"], stored["_how"] = real, method
        try:
            _write_json(path, stored, indent=1, sort_keys=True)
        except OSError as e:
            log(f"  lenses {league}: could not store pull dates ({e})")
        try:                                  # the archive column too, where it is still blank
            if PO.has_game_date_column(conn):
                for pid, (d, _h) in fresh.items():
                    conn.execute("UPDATE pulls SET game_date=? WHERE pull_id=? AND "
                                 "(game_date IS NULL OR game_date='')", (d.isoformat(), pid))
                conn.commit()
        except Exception as e:                # a read-only connection keeps the JSON only
            log(f"  lenses {league}: pull dates not written to the archive ({type(e).__name__})")
    # walk the rest from the nearest dated pull (estimate; never stored)
    undated = [i for i, p in enumerate(pulls) if p[0] not in dates]
    if undated and dates:
        spans = {}

        def span(i):                          # pulls[i] -> pulls[i + 1]
            if i not in spans:
                spans[i] = pair_span(conn, pulls[i][0], pulls[i + 1][0])
            return spans[i]
        known = [i for i, p in enumerate(pulls) if p[0] in dates]
        for i in undated:
            j = min(known, key=lambda k: abs(k - i))
            yrs = sum(span(k) for k in range(min(i, j), max(i, j)))
            delta = datetime.timedelta(days=yrs * 365.25)
            dates[pulls[i][0]] = dates[pulls[j][0]] + (delta if i > j else -delta)
            how[pulls[i][0]] = "walked"
    return dates, how


# ---------------------------------------------------------------- season stats
def _woba_parts(row, side):
    """(numerator, denominator) of wOBA for one batting or pitching row."""
    if side == "bat":
        h, d, t, hr = _int(row, "h"), _int(row, "d"), _int(row, "t"), _int(row, "hr")
        ubb = _int(row, "bb") - _int(row, "ibb")
    else:
        h, d, t, hr = _int(row, "ha"), _int(row, "da"), _int(row, "ta"), _int(row, "hra")
        ubb = _int(row, "bb") - _int(row, "iw")
    hbp, sf, ab = _int(row, "hp"), _int(row, "sf"), _int(row, "ab")
    w = WOBA_W
    num = (w["ubb"] * ubb + w["hbp"] * hbp + w["s"] * (h - d - t - hr)
           + w["d"] * d + w["t"] * t + w["hr"] * hr)
    return num, ab + ubb + sf + hbp


def league_means(bat_rows, pit_rows):
    """({league_id: wOBA mean}, {league_id: coverage}). ONE mean per league for
    both sides, read from the side with the larger denominator: batting PA
    against pitching BF of the same league. StatsPlus drops the rows of deleted
    players, so the smaller side is the one that lost more rows.
    coverage = {pa, bf, side, woba_bat, woba_pit}."""
    acc = {}
    for rows, side, vol_key in ((bat_rows, "bat", "pa"), (pit_rows, "pit", "bf")):
        for r in rows:
            num, den = _woba_parts(r, side)
            e = acc.setdefault(str(r.get("league_id")), {"bat": [0.0, 0, 0], "pit": [0.0, 0, 0]})[side]
            e[0] += num
            e[1] += den
            e[2] += _int(r, vol_key)
    means, cover = {}, {}
    for lid, e in acc.items():
        wb = (e["bat"][0] / e["bat"][1]) if e["bat"][1] > 0 else None
        wp = (e["pit"][0] / e["pit"][1]) if e["pit"][1] > 0 else None
        side = "bat" if (wb is not None and (wp is None or e["bat"][2] >= e["pit"][2])) else "pit"
        mean = wb if side == "bat" else wp
        if mean is None:
            continue
        means[lid] = mean
        cover[lid] = {"pa": e["bat"][2], "bf": e["pit"][2], "side": side,
                      "woba_bat": round(wb, 4) if wb is not None else None,
                      "woba_pit": round(wp, 4) if wp is not None else None}
    return means, cover


def _side_table(rows, side, lg_woba):
    """{pid: [playing time, performance]}. Performance = his wOBA minus the
    mean of the league(s) he played in (lg_woba: one mean per league, the same
    for both sides), each league weighted by his own playing time there; sign
    flipped for pitchers, so positive is good on both sides."""
    vol_key = "pa" if side == "bat" else "bf"
    acc = {}
    for r in rows:
        pid = str(r.get("player_id") or "").strip()
        if not pid:
            continue
        num, den = _woba_parts(r, side)
        e = acc.setdefault(pid, [0, 0.0, 0])          # volume, sum(num - lg*den), den
        e[0] += _int(r, vol_key)
        mean = lg_woba.get(str(r.get("league_id")))
        if mean is not None and den > 0:
            e[1] += num - mean * den
            e[2] += den
    sign = 1.0 if side == "bat" else -1.0
    return {pid: [e[0], round(sign * e[1] / e[2], 4) if e[2] > 0 else None]
            for pid, e in acc.items()}


def check_feeds(leagues, bat, pit):
    """Raise when a stats feed is not usable: 0 rows, or a top-level league
    (parent_league_id 0) without rows on either side. A truncated feed must
    never reach the cache."""
    if not bat or not pit:
        raise RuntimeError(f"stats feed came back empty (batting {len(bat)} rows, "
                           f"pitching {len(pit)} rows)")
    top = [str(l.get("league_id")) for l in leagues
           if l.get("league_id") is not None and str(l.get("parent_league_id") or "0") == "0"]
    for name, rows in (("batting", bat), ("pitching", pit)):
        have = {str(r.get("league_id")) for r in rows}
        gone = [lid for lid in top if lid not in have]
        if gone:
            raise RuntimeError(f"{name} feed has no rows for top-level league(s) {', '.join(gone)}")


def fetch_season(league, year, now):
    """Fetch one season for one league from its own StatsPlus: every league id,
    eight per request. Raises on any network or API failure, on an empty feed
    and on a top-level league without rows (check_feeds). Caches nothing."""
    S = _statsplus()
    base = S.normalize_base(LEAGUE_SLUG[league])
    leagues = S.fetch_lgdata(base, cache=True)
    lids = [l.get("league_id") for l in leagues if l.get("league_id") is not None]
    if not lids:
        raise RuntimeError("StatsPlus returned no league ids")
    bat, pit = [], []
    for i in range(0, len(lids), 8):
        bat += S.fetch_batting(base, year=year, lids=lids[i:i + 8], split=1, cache=True)
        pit += S.fetch_pitching(base, year=year, lids=lids[i:i + 8], split=1, cache=True)
    check_feeds(leagues, bat, pit)
    means, cover = league_means(bat, pit)
    return {"v": CACHE_VERSION, "league": league, "year": year,
            "final": season_is_final(year, now), "asof": now.isoformat(),
            "fetched": datetime.datetime.now().isoformat(timespec="seconds"),
            "lids": lids, "lg_woba": {k: round(v, 4) for k, v in means.items()},
            "coverage": cover,
            "bat": _side_table(bat, "bat", means), "pit": _side_table(pit, "pit", means)}


def _table_sizes(table):
    """(batting players, pitching players) of a season file of ANY cache version."""
    if isinstance(table, dict) and isinstance(table.get("bat"), dict) and isinstance(table.get("pit"), dict):
        return len(table["bat"]), len(table["pit"])
    return None


def season_stats(league, year, now, log=print):
    """Season table for one league-year, or None.
      - a final cached copy serves for good
      - before October 1 of the season nothing is fetched: the result is a stub
        that season_usable() refuses, so the pairs of that season are left out
      - otherwise the season is fetched again; when that fails, the last cached
        copy serves with a printed note
      - a fetched final table smaller than the last cached copy is never
        written as final. The cached copy serves when it is usable; if not, the
        fetched table serves and is stored as NOT final (fetched again next run)
      - a cached file must carry this league and this year"""
    path = os.path.join(CACHE_DIR, f"{league}_{year}.json")
    raw = _read_json(path)
    cached = raw
    if not (isinstance(cached, dict) and cached.get("v") == CACHE_VERSION
            and isinstance(cached.get("bat"), dict) and isinstance(cached.get("pit"), dict)):
        cached = None
    wrong = isinstance(raw, dict) and (raw.get("league", league) != league or raw.get("year", year) != year)
    if wrong:
        log(f"  lenses {league}: cache file {os.path.basename(path)} holds league {raw.get('league')} "
            f"year {raw.get('year')}; ignored")
        cached = None
    last_sizes = None if wrong else _table_sizes(raw)      # the size guard reads any version
    if cached and cached.get("final"):
        return cached
    if now is not None and now < datetime.date(year, 10, 1):
        return {"v": CACHE_VERSION, "league": league, "year": year, "final": False,
                "asof": now.isoformat(), "stub": True, "bat": {}, "pit": {}}
    if now is not None and league not in _REFUSED:
        try:
            fresh = fetch_season(league, year, now)
            sizes = _table_sizes(fresh)
            if fresh["final"] and last_sizes and (sizes[0] < last_sizes[0] or sizes[1] < last_sizes[1]):
                log(f"  lenses {league}: season {year} NOT stored as final: the fetched table "
                    f"({sizes[0]} hitters, {sizes[1]} pitchers) is smaller than the last cached copy "
                    f"({last_sizes[0]}, {last_sizes[1]}). Delete {os.path.basename(path)} to accept it")
                if cached and season_usable(cached, year):
                    return cached
                fresh["final"] = False
            _write_json(path, fresh, separators=(",", ":"))
            return fresh
        except Exception as e:
            if _refusal(e):
                _note_refusal(league, e, log, "Season stats come from the saved copies.")
            else:
                log(f"  lenses {league}: season {year} not fetched ({type(e).__name__}: {e})")
    if cached:
        log(f"  lenses {league}: season {year} served from the cache, stats as of "
            f"in-game {cached.get('asof')}")
    return cached


# ---------------------------------------------------------------- the lens set
class Lenses:
    """Per-league lens state. age_curves calls start_pair() once per USED pull
    pair, then player_buckets() once per young player in that pair. A lens that
    fails is dropped for the whole run; finish() removes its partial sums."""

    def __init__(self, conn, league, personality, log=print):
        self.conn, self.league, self.log = conn, league, log
        self.pers = personality or {}
        self.dropped = {}                     # lens key -> reason
        self.pairs = {"PT": 0, "PT_left_out": 0, "WAA": 0, "LDR": 0}
        self.seasons = {}                     # year -> season table or None
        self.season_pairs = {}                # year -> pull pairs bucketed from it
        self.season_left_out = {}             # year -> pull pairs left out (season not usable)
        # per context lens: [player-pairs bucketed, of them without a personality record]
        self.population = {k: [0, 0] for k in CONTEXT_LENSES}
        self.pt_unknown_team = 0              # 0 PA / BF and no level on record: left out of PT
        self.foreign_out = [0, 0]             # player-pairs left out as foreign, of them with a record today
        self._stats = self._waa = self._ldr = None
        self._people = {}
        self._waa_mod = self._waa_fp = self._waa_static = None
        self._people_note = False
        self.now = None
        self.dates, self.how = {}, {}
        self.pulls = PO.ordered(conn, league, log)[0]     # in-game order, asof snapshots included
        self._src, self._hash = {}, {}
        for r in conn.execute("SELECT pull_id, source_files, content_hash FROM pulls WHERE league=?",
                              (league,)):
            self._src[r[0]], self._hash[r[0]] = r[1], r[2]
        self.source = _dump_source(conn, league)
        if self.source is not None:
            # dump-sourced league: dates are stored, stats come from the dump, no engine
            self.now = self.source.now()
            self.dates = self.source.dates(self.pulls)
            self.how = {p[0]: "dump" for p in self.pulls if p[0] in self.dates}
            self._drop("WAA", "dump league: the projection engine has no calibration for it "
                              f"(ratings on the {self.source.scale} scale)")
        else:
            try:
                S = _statsplus()
                raw = S.fetch_date(S.normalize_base(LEAGUE_SLUG[league]))
                self.now = datetime.date.fromisoformat(raw[:10])
            except Exception as e:
                if _refusal(e):
                    _note_refusal(league, e, log, "Working from the caches: no birth dates or season "
                                                  "stats are read from StatsPlus this run.")
                else:
                    log(f"  lenses {league}: StatsPlus not reachable ({type(e).__name__}); "
                        f"working from the caches")
            try:
                self.dates, self.how = pull_game_dates(conn, league, self.pulls, self.now, log)
            except Exception as e:
                log(f"  lenses {league}: pull dates failed ({type(e).__name__}: {e})")
        if not self.dates:
            self._drop("PT", "no in-game date for any pull (StatsPlus unreachable, nothing stored)")

    def _drop(self, key, reason):
        keys = {"PT": ("PT", "PERF"), "LDR": ("LDR", "NEG")}.get(key, (key,))
        for k in keys:
            if k not in self.dropped:
                self.dropped[k] = reason
        self.log(f"  lenses {self.league}: {' / '.join(keys)} dropped - {reason}")

    # -- per pair ---------------------------------------------------------
    def start_pair(self, old_pull, new_pull, old_map):
        self._stats = self._waa = self._ldr = None
        # level / club / leadership / no-team / foreign of the OLDER pull. The
        # population gate, the PT "no team" bucket and LDR / NEG all read it.
        try:
            self._people = self._pull_people(old_pull)
        except Exception as e:
            self._people = {}
            if not self._people_note:
                self._people_note = True
                self.log(f"  lenses {self.league}: source file of pull {old_pull[1]} not readable "
                         f"({type(e).__name__}). Such pulls gate on the personality record and read "
                         f"the level from the archive; LDR / NEG use org + level with the current "
                         f"leadership, or skip the pair when the archive holds no level")
        if "PT" not in self.dropped:
            try:
                self._stats = self._pair_stats(old_pull, new_pull)
            except Exception as e:
                self._drop("PT", f"{type(e).__name__}: {e}")
        if "WAA" not in self.dropped:
            try:
                self._waa = self._pair_waa(old_pull)
            except Exception as e:
                self._drop("WAA", f"agecurve_fit raised {type(e).__name__}: {e}")
        if "LDR" not in self.dropped:
            try:
                self._ldr = self._pair_leaders(old_pull, old_map)
            except Exception as e:
                self._drop("LDR", f"{type(e).__name__}: {e}")

    def _pair_stats(self, old_pull, new_pull):
        d0, d1 = self.dates.get(old_pull[0]), self.dates.get(new_pull[0])
        if d0 is None or d1 is None:
            raise RuntimeError(f"pull {old_pull[1]} or {new_pull[1]} has no in-game date")
        year = pair_season(d0, d1)
        if year not in self.seasons:
            if self.source is not None:
                self.seasons[year] = self.source.season(year, self.now, self.log)
            else:
                self.seasons[year] = season_stats(self.league, year, self.now, self.log)
        table = self.seasons[year]
        if table is None:
            # No table at all. When no as-of date this run could reach is on or after
            # October 1, the season could not be used anyway: leave the pair out.
            latest = max(d for d in (self.now, d1) if d is not None)
            if latest >= datetime.date(year, 10, 1):
                raise RuntimeError(f"season {year} stats not available (network down, nothing cached)")
        if not season_usable(table, year):
            if year not in self.season_left_out:
                asof = (table or {}).get("asof")
                self.log(f"  lenses {self.league}: season {year} is in progress"
                         f"{' (in-game ' + str(asof) + ')' if asof else ''}, before October 1: "
                         f"its pull pairs are left out of PT / PERF")
            self.season_left_out[year] = self.season_left_out.get(year, 0) + 1
            self.pairs["PT_left_out"] += 1
            return None
        self.season_pairs[year] = self.season_pairs.get(year, 0) + 1
        self.pairs["PT"] += 1
        return table

    def _pair_waa(self, old_pull):
        """{pid: bucket} from the engine WAA of the OLDER pull: rank of the
        CURRENT projected WAA inside the same integer age and the same side."""
        path = os.path.join(PO.VINTAGES_DIR, self.league, f"{old_pull[1]}_p{old_pull[0]}.csv.gz")
        if not os.path.exists(path):          # vintage backup not written yet
            self.log(f"  lenses {self.league}: no vintage file for pull {old_pull[1]} "
                     f"(p{old_pull[0]}); WAA skips this pair")
            return None
        if self._waa_mod is None:
            if ENGINE not in sys.path:
                sys.path.insert(0, ENGINE)
            import agecurve_fit
            self._waa_mod = agecurve_fit
            self._waa_fp = agecurve_fit.calib_fingerprint(self.league)
        A = self._waa_mod
        cache = os.path.join(os.path.dirname(path), ".waa_cache",
                             f"{os.path.basename(path)}.{self._waa_fp}.json")
        if not os.path.exists(cache) and self._waa_static is None:
            self.log(f"  lenses {self.league}: engine pass for uncached vintages "
                     f"(one time, about 40 s each)")
            static = {}
            for fn in ("hitters.json", "pitchers.json"):
                with open(os.path.join(VIZ, "public", "data", self.league, fn), encoding="utf-8") as fh:
                    for r in json.load(fh):
                        static[str(r.get("ID"))] = {"B": r.get("B"), "T": r.get("T"), "HT": r.get("HT")}
            self._waa_static = static
        waa = A.vintage_waa(self.league, path, self._waa_static or {}, self._waa_fp)
        groups = {}
        for pid, e in waa.items():
            if e[0] is None or not has_org(e[4]):
                continue
            try:
                age = int(float(e[3]))
            except (TypeError, ValueError):
                continue
            groups.setdefault((age, e[2]), []).append((e[0], pid))
        out = {}
        for members in groups.values():
            n = len(members)
            if n < WAA_MIN_GROUP:
                continue
            members.sort()
            i = 0
            while i < n:                      # tied values share their mid-rank
                j = i
                while j + 1 < n and members[j + 1][0] == members[i][0]:
                    j += 1
                pct = ((i + j) / 2 + 0.5) / n
                b = WAA_BUCKETS[0] if pct < 0.25 else WAA_BUCKETS[2] if pct >= 0.75 else WAA_BUCKETS[1]
                for k in range(i, j + 1):
                    out[members[k][1]] = b
                i = j + 1
        self.pairs["WAA"] += 1
        return out

    def _pull_people(self, pull):
        """{pid: [lev, club id, leadership, no_team, foreign]} as the pull's OWN
        source file(s) recorded them. The archive keeps ratings only: a
        StatsPlus pull stored no level, and no pull stored the club id or the
        personality. Level uses the app's own map (statsplus._lev_for). no_team
        marks a row whose LgLvl is blank or 0: free agent, complex, unassigned
        reserve. foreign = the row's League id is an NPB / KBO league of this
        world (statsplus.FOREIGN_BY_LEAGUE); None when the row has no League id
        (sheet-era pull); False in a world without foreign leagues.
        The file is named by pull id, and a rebuilt database can give the same
        id to a different pull. The file therefore stores the pull's real date
        and content hash: a copy that does not match this pull is ignored and
        rebuilt (pull_game_dates does the same with _real_dates).
        A dump-sourced league reads the pull's raw vintage rows instead."""
        if self.source is not None:
            return self.source.people(pull)
        path = os.path.join(CACHE_DIR, f"{self.league}_people_p{pull[0]}.json")
        want_hash = self._hash.get(pull[0])
        cached = _read_json(path)
        if (isinstance(cached, dict) and cached.get("v") == PEOPLE_VERSION
                and cached.get("league") == self.league and cached.get("pull_id") == pull[0]
                and cached.get("real_date") == pull[1]
                and (not want_hash or cached.get("content_hash") == want_hash)
                and isinstance(cached.get("people"), dict)):
            return cached["people"]
        S = _statsplus()
        foreign_ids = S.FOREIGN_BY_LEAGUE.get(self.league, S.FOREIGN_LEAGUE_IDS)
        out = {}
        for rel in json.loads(self._src.get(pull[0]) or "[]"):
            fp = os.path.join(REPO, rel.replace("\\", os.sep))
            with open(fp, encoding="utf-8") as fh:
                rows = json.load(fh)
            for r in rows:
                pid = str(r.get("ID") or "").strip()
                if not pid:
                    continue
                no_team = "LgLvl" in r and str(r.get("LgLvl") or "").strip() in ("", "0")
                lev = r.get("Lev") or (S._lev_for(r, self.league)
                                       if ("League" in r or "LgLvl" in r) else None)
                club = str(r.get("Team") or "").strip()
                if not foreign_ids:
                    foreign = False
                elif "League" in r:
                    foreign = str(r.get("League")).strip() in foreign_ids
                else:
                    foreign = None
                out[pid] = [lev, club if club not in ("", "0") else None,
                            r.get("Lead") if r.get("Lead") in HNL else None, no_team, foreign]
        _write_json(path, {"v": PEOPLE_VERSION, "league": self.league, "pull_id": pull[0],
                           "real_date": pull[1], "content_hash": want_hash, "people": out},
                    separators=(",", ":"))
        return out

    def _pair_leaders(self, old_pull, old_map):
        """{pid: (LDR bucket, NEG bucket)}: High / Low leadership teammates in
        the OLDER pull, the player himself excluded. Reads the people map that
        start_pair loaded for this pair."""
        people = self._people
        if not people and not any(rec.get("lev") for rec in old_map.values()):
            return None
        team_of, lead_of, counts = {}, {}, {}
        for pid, rec in old_map.items():
            org = rec.get("org")
            if not has_org(org):
                continue
            lev, club, lead, no_team = (people.get(pid) or (None, None, None, False))[:4]
            lev = rec.get("lev") or lev
            if no_team or lev in NO_TEAM_LEVS:
                continue
            key = (str(org), lev, club)
            team_of[pid] = key
            lead_of[pid] = lead = lead or (self.pers.get(pid) or {}).get("LEA")
            c = counts.setdefault(key, [0, 0])
            if lead == "H":
                c[0] += 1
            elif lead == "L":
                c[1] += 1
        out = {}
        for pid, key in team_of.items():
            h, l = counts[key]
            out[pid] = (count_bucket(h - (lead_of[pid] == "H")), count_bucket(l - (lead_of[pid] == "L")))
        self.pairs["LDR"] += 1
        return out

    # -- per player -------------------------------------------------------
    def player_buckets(self, pid, pers, orec):
        """{is_pitcher_rating: [(lens, bucket), ...]} for one player in the
        current pair. Personality lenses apply to both rating sides; the other
        lenses apply to the player's own side only."""
        base = [(t, pers.get(t)) for t in PERSONALITY if pers.get(t) in HNL]
        own = []
        is_pit = (orec.get("pos") or "").upper() in PIT_POS
        person = self._people.get(pid)
        # Population gate: a real org in the older pull, and not a foreign-league
        # club. Foreign status unknown (no people record, or a sheet-era row
        # without a League id): fall back to the personality record, which the
        # app's player file holds for non-foreign players only.
        foreign = person[4] if person is not None and len(person) > 4 else None
        if foreign and has_org(orec.get("org")):
            self.foreign_out[0] += 1                  # left out: foreign-league club in the older pull
            if pers:
                self.foreign_out[1] += 1              # ...although today's player file holds him
        if has_org(orec.get("org")) and (bool(pers) if foreign is None else not foreign):
            if self._stats is not None:
                n, diff = (self._stats["pit"] if is_pit else self._stats["bat"]).get(pid) or (0, None)
                if n > 0:
                    own.append(("PT", pt_bucket(n)))
                elif person is None and not orec.get("lev"):
                    self.pt_unknown_team += 1         # no level on record: left out of PT
                else:
                    # the 0 bucket splits by the level in the older pull: a player with
                    # no league team (complex / unassigned) cannot play league games
                    lev = orec.get("lev") or person[0]
                    no_team = (person is not None and person[3]) or lev in NO_TEAM_LEVS
                    own.append(("PT", NO_TEAM if no_team else "0"))
                own.append(("PERF", perf_bucket(n, diff)))
            if self._waa is not None:
                b = self._waa.get(pid)
                if b:
                    own.append(("WAA", b))
            if self._ldr is not None:
                e = self._ldr.get(pid)
                if e:
                    own.append(("LDR", e[0]))
                    own.append(("NEG", e[1]))
        for k, _b in own:
            self.population[k][0] += 1
            if not pers:
                self.population[k][1] += 1
        full = base + own
        return {True: full if is_pit else base, False: base if is_pit else full}

    # -- after the run ----------------------------------------------------
    def finish(self, tree):
        """{lens: {bucket: ...}} without the lenses that failed part-way (their
        sums cover only some pairs), lenses and buckets in display order."""
        order = {"PT": PT_BUCKETS, "PERF": PERF_BUCKETS, "WAA": WAA_BUCKETS,
                 "LDR": COUNT_BUCKETS, "NEG": COUNT_BUCKETS}
        if self.pairs["PT"] == 0 and self.pairs["PT_left_out"] and "PT" not in self.dropped:
            self._drop("PT", "no pull pair sits in a usable season (final, or stats as of "
                             "October 1 of the season or later)")
        return {k: {b: tree[k][b] for b in order.get(k, HNL) if b in tree[k]}
                for k in LENS_ORDER if k in tree and k not in self.dropped}

    def info(self):
        dated = [p for p in self.pulls if p[0] in self.dates]
        how = {}
        for p in dated:
            how[self.how.get(p[0], "?")] = how.get(self.how.get(p[0], "?"), 0) + 1
        out = {"pit_cols": list(PIT_COLS), "dropped": dict(self.dropped),
               "pairs": dict(self.pairs), "pull_dates_by": how,
               "game_now": self.now.isoformat() if self.now else None}
        if self.source is not None:
            out["source"] = "dump"
            out["scale"] = self.source.scale
        if dated:
            out["first_pull"] = {"real": dated[0][1], "game": self.dates[dated[0][0]].isoformat()}
            out["last_pull"] = {"real": dated[-1][1], "game": self.dates[dated[-1][0]].isoformat()}
        seasons = {}
        for y in sorted(set(self.seasons) | set(self.season_left_out)):
            t = self.seasons.get(y) or {}
            s = {"pairs": self.season_pairs.get(y, 0),
                 "pairs_left_out": self.season_left_out.get(y, 0),
                 "final": bool(t.get("final")), "asof": t.get("asof"),
                 "usable": season_usable(t, y)}
            cover = t.get("coverage") or {}
            if cover:
                side_gaps = [abs(c["woba_bat"] - c["woba_pit"]) for c in cover.values()
                             if c.get("woba_bat") is not None and c.get("woba_pit") is not None]
                s["coverage"] = {"leagues": len(cover),
                                 "pa": sum(c.get("pa") or 0 for c in cover.values()),
                                 "bf": sum(c.get("bf") or 0 for c in cover.values()),
                                 "mean_from_bat": sum(1 for c in cover.values() if c.get("side") == "bat"),
                                 "mean_from_pit": sum(1 for c in cover.values() if c.get("side") == "pit"),
                                 "max_side_gap": round(max(side_gaps), 4) if side_gaps else None}
            seasons[str(y)] = s
        out["seasons"] = seasons
        # player-pair observations per context lens, and how many of them have no
        # personality record in today's player file (the old gate left those out)
        out["population"] = {k: {"player_pairs": v[0], "no_personality_record": v[1]}
                             for k, v in self.population.items() if k not in self.dropped}
        out["foreign_left_out"] = {"player_pairs": self.foreign_out[0],
                                   "with_personality_record": self.foreign_out[1]}
        out["pt_unknown_team"] = self.pt_unknown_team
        return out


# ---------------------------------------------------------------- export text
def trait_meta(trait_keys, info=None):
    """Display metadata for every lens present in the export."""
    info = info or {}
    seasons = info.get("seasons") or {}
    used = {y: s for y, s in seasons.items() if s.get("pairs")}
    left = {y: s for y, s in seasons.items() if s.get("pairs_left_out")}
    season_txt = ", ".join(f"{y} ({'final' if s.get('final') else 'stats as of ' + str(s.get('asof'))}"
                           f", {s.get('pairs')} pull pairs)" for y, s in used.items())
    left_txt = ", ".join(f"{y} ({s.get('pairs_left_out')} pull pairs"
                         + (f", in-game {s.get('asof')}" if s.get("asof") else "") + ")"
                         for y, s in left.items())
    cover = [(y, s["coverage"]) for y, s in used.items() if s.get("coverage")]
    cover_txt = ""
    if cover:
        cover_txt = " Coverage: " + "; ".join(
            f"{y}: {c['leagues']} leagues, {c['pa']:,} PA and {c['bf']:,} BF, mean read from batting "
            f"in {c['mean_from_bat']} and from pitching in {c['mean_from_pit']}"
            + (f", largest gap between the two sides {c['max_side_gap']:.4f}"
               if c.get("max_side_gap") is not None else "")
            for y, c in cover) + "."
    dump = info.get("source") == "dump"
    own = ("Own side only: hitter ratings from position players, pitcher ratings from pitchers. "
           "Players without an org at the start of the pull pair are left out, and so are players "
           + ("of a foreign or independent league club. A personality record is not needed."
              if dump else "of a foreign-league club (NPB / KBO). A personality record is not needed."))
    hnl_note = ("{} from the current pull. Personality is nearly static in OOTP, so the current "
                "value stands in for the whole archive."
                + (" Buckets are terciles of the league's players on OOTP's 1-200 scale "
                   "(dump_vintages.py); the raw values are kept in the vintage file." if dump else ""))
    stats_from = ("in the season's yearly dump (every league in leagues.csv)" if dump
                  else "on this league's StatsPlus (winter ball included)")
    meta = {}
    for k, label in PERSONALITY.items():
        meta[k] = {"label": label, "buckets": list(HNL), "bucket_labels": dict(HNL_LABELS),
                   "note": hnl_note.format(label), "basis": "personality"}
    meta["PT"] = {
        "label": "Playing time that season", "buckets": list(PT_BUCKETS),
        "bucket_labels": {b: ("No league team (complex / unassigned)" if b == NO_TEAM else b)
                          for b in PT_BUCKETS},
        "basis": "PA/BF", "basis_by_side": {"hit": "PA", "pit": "BF"},
        "note": ("Season plate appearances for hitter ratings, batters faced for pitcher ratings, "
                 f"summed over every league and level {stats_from}. Each pull pair reads the in-game season of its midpoint; a midpoint "
                 "from November to March reads the season that just ended. A season counts only "
                 "when it is final or its stats are as of October 1 of that season or later "
                 "(regular schedules complete). The pull pairs of a season still in progress are "
                 "left out, so an April pair is never bucketed by June totals. From October 1 "
                 "until the season is final (April 1), winter-ball rows can still move a bucket. "
                 "The 0 bucket splits by the level in the older pull of the pair. '0' is a player "
                 "on a league team with no PA or BF that season. 'No league team' is a player in "
                 "the international complex or an unassigned reserve, who cannot play league "
                 "games, with no PA or BF that season. " + own
                 + (f" Seasons used: {season_txt}." if season_txt else "")
                 + (f" Left out (season in progress): {left_txt}." if left_txt else ""))}
    meta["PERF"] = {
        "label": "Performance vs his level", "buckets": list(PERF_BUCKETS),
        "bucket_labels": {"too few": f"Too few (under {PERF_MIN})", "well below": "Well below (under -.040)",
                          "below": "Below (-.040 to -.015)", "average": "Average (-.015 to +.015)",
                          "above": "Above (+.015 to +.040)", "well above": "Well above (over +.040)"},
        "basis": "wOBA vs league", "basis_by_side": {"hit": "PA", "pit": "BF"},
        "note": ("Hitters: his season wOBA minus the wOBA of the league he batted in. Pitchers: the "
                 "league's wOBA minus his wOBA allowed. Positive is good on both sides. A player who "
                 "changed level is compared with each league in proportion to his time there. One "
                 "fixed weight set (uBB .69, HBP .72, 1B .89, 2B 1.27, 3B 1.62, HR 2.10) scores the "
                 "player and his league mean alike, so it only ranks him against his own level. "
                 "Each league has ONE mean for both sides, read from the side with more playing "
                 "time on record (batting PA against pitching BF): StatsPlus drops the rows of "
                 "deleted players, so the two sides of a league do not agree exactly. "
                 f"Under {PERF_MIN} PA or BF counts as too few. Same seasons as the playing-time lens."
                 + cover_txt + " " + own)}
    meta["WAA"] = {
        "label": "Projected value among players his age", "buckets": list(WAA_BUCKETS),
        "bucket_labels": {b: b.capitalize() for b in WAA_BUCKETS},
        "basis": "WAA rank",
        "note": ("Rank of his CURRENT projected WAA (engine projection of the ratings in the older "
                 "pull of each pair, neutral park) among org players of the same integer age and the "
                 "same side: hitters with hitters, pitchers with pitchers. Age groups under "
                 f"{WAA_MIN_GROUP} players are left out. " + own)}
    team = ("Team and leadership are read from the older pull of each pair, as that pull's own file "
            "recorded them: same org, same level and same club id. The first pull of each league "
            "(sheet era) has no club id and no personality; it uses org + level and the current "
            "leadership value. Free agents, the amateur pool, the international complex and "
            "unassigned reserves have no team and are left out. " + own)
    meta["LDR"] = {"label": "Leaders on his team", "buckets": list(COUNT_BUCKETS),
                   "bucket_labels": {b: f"{b} leaders" for b in COUNT_BUCKETS},
                   "basis": "teammates",
                   "note": "Teammates with High leadership, himself excluded. " + team}
    meta["NEG"] = {"label": "Low-leadership teammates", "buckets": list(COUNT_BUCKETS),
                   "bucket_labels": {b: f"{b} low-leadership" for b in COUNT_BUCKETS},
                   "basis": "teammates",
                   "note": "Teammates with Low leadership, himself excluded. " + team}
    return {k: meta[k] for k in LENS_ORDER if k in trait_keys and k in meta}


# ---------------------------------------------------------------- CLI
def _report(leagues, age, hit_col, pit_col):
    for lg in leagues:
        path = os.path.join(VIZ, "public", "data", lg, "rating_trends.json")
        ac = (_read_json(path) or {}).get("age_curves") or {}
        traits, meta, players = ac.get("traits") or {}, ac.get("trait_meta") or {}, ac.get("trait_players") or {}
        print(f"\n=== {lg}: {os.path.getsize(path) / 1e6:.2f} MB ===")
        print("  lens_info:", json.dumps(ac.get("lens_info"), indent=1))
        for k, m in meta.items():
            print(f"  {k:<5} {m['label']}  (age {age}; n = pair observations, p = distinct players, "
                  f"y = player-years)")
            for col in (hit_col, pit_col):
                cells = []
                for b in m["buckets"]:
                    e = ((traits.get(k) or {}).get(b) or {}).get(col, {}).get(str(age))
                    p = ((players.get(k) or {}).get(b) or {}).get(col, {}).get(str(age))
                    cells.append(f"{b}: " + (f"{e[0]:+.2f}/yr n={e[2]} p={p} y={e[3]}" if e else "-"))
                print(f"      {col:<7} " + " | ".join(cells))


def _dates(leagues):
    import sqlite3
    conn = sqlite3.connect(PO.DB_PATH)
    for lg in leagues:
        pulls = PO.ordered(conn, lg)[0]       # in-game order, asof snapshots included
        src = _dump_source(conn, lg)
        if src is not None:
            now = src.now()
            dates = src.dates(pulls)
            how = {p[0]: "dump" for p in pulls if p[0] in dates}
        else:
            try:
                S = _statsplus()
                now = datetime.date.fromisoformat(S.fetch_date(S.normalize_base(LEAGUE_SLUG[lg]))[:10])
            except Exception as e:
                now = None
                if _refusal(e):
                    _note_refusal(lg, e, print, "The dates below come from what is stored.")
            dates, how = pull_game_dates(conn, lg, pulls, now)
        print(f"\n=== {lg}: in-game now {now} ===")
        prev = None
        for p in pulls:
            d = dates.get(p[0])
            season = pair_season(prev, d) if prev and d and d > prev else ""
            print(f"  pull {p[0]:>3}  real {p[1]}  in-game {d}  ({how.get(p[0], 'undated')})"
                  f"{'  pair season ' + str(season) if season else ''}")
            prev = d or prev
    conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="bucket sample sizes from the exported file")
    ap.add_argument("--dates", action="store_true", help="in-game date of every archived pull")
    ap.add_argument("--league")
    ap.add_argument("--age", type=int, default=18)
    ap.add_argument("--hit", default="POW vR")
    ap.add_argument("--pit", default="STU")
    a = ap.parse_args()
    lgs = [a.league] if a.league else list(LEAGUE_SLUG)
    if a.dates:
        _dates(lgs)
    if a.report:
        _report(lgs, a.age, a.hit, a.pit)
    if not (a.dates or a.report):
        ap.print_help()
