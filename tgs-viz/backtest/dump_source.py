"""
dump_source.py - read OOTP's yearly CSV dump for a dump-sourced league.

A dump-sourced league has no StatsPlus. OOTP writes one CSV dump per season
(League Setup: "Export CSV files after each simulated season"):

    <saved_games>/<league>.lg/dump/dump_<year>_yearly/csv/*.csv

dump_vintages.py turns each dump into one vintage of ratings_history.db, stored
with source "dump", and keeps the full raw rows in
<db dir>/vintages/<LG>/raw_<year>.json.gz. This module reads the dump files and
those raw rows, and gives ratings_db.py and growth_lenses.py the same
structures the StatsPlus path builds:

    for_league(conn, league)   DumpSource, or None for a StatsPlus league
    DumpSource.scale           "20-80" or "1-100" (league_scale_<LG>.json, next to the DB)
    DumpSource.dates(pulls)    {pull_id: in-game date}: the stored real_date IS the in-game date
    DumpSource.now()           in-game date of the newest vintage
    DumpSource.people(pull)    {pid: [lev, club id, leadership, no_team, foreign]}
    DumpSource.personality()   {pid: {WE, INT, LEA, LOY, GRD}} H/N/L from the newest vintage
    DumpSource.season(year)    season table (PA/BF, wOBA vs league) in growth_lenses' cache shape

LEAGUES ARE SEPARATE. A StatsPlus league (TGS, BLM) never reaches this module:
for_league() returns None unless every pull of the league carries source "dump".

Profile: ootp/leagues.json, key = league id, read with defaults:
    {"DEV": {"game": "27", "league": "DEV TESTS", "source": "dump"}}
"game" picks the saved_games folder (Documents layout first, then <install>/data),
"league" is the .lg name (default: the league id), "source" must be "dump".

Rating scale. OOTP shows ratings on the league's display scale. A 20-80 league
steps in 5s; a 1-100 league does not. detect_scale() reads the values.
"""
import os
import re
import csv
import gzip
import json
import glob
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
PROFILES_PATH = os.path.join(REPO, "ootp", "leagues.json")
DUMP_SOURCE = "dump"                                        # pulls.source value
SCALES = ("20-80", "1-100")

# rating keys read for the scale check (raw StatsPlus key names, see dump_vintages)
SCALE_KEYS = ("BABIP_R", "BABIP_L", "Gap_R", "Gap_L", "Pow_R", "Pow_L", "Eye_R", "Eye_L",
              "Ks_R", "Ks_L", "PotBABIP", "PotGap", "PotPow", "PotEye", "PotKs",
              "Speed", "StlRt", "Steal", "Run", "IFR", "IFE", "IFA", "TDP", "OFR", "OFE", "OFA",
              "CBlk", "CArm", "CFrm", "Stf", "HRA", "PBABIP", "Ctrl", "Stf_R", "HRA_R", "PBABIP_R",
              "Ctrl_R", "Stf_L", "HRA_L", "PBABIP_L", "Ctrl_L", "PotStf", "PotHRA", "PotPBABIP",
              "PotCtrl", "Stm", "Hold")
OFF5_SHARE = 0.05         # more than this share of values off the 5-step grid = 1-100
BELOW20_SHARE = 0.02      # more than this share of values in 1..19 = 1-100


# ---------------------------------------------------------------- small io
def read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, obj, **kw):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, **kw)
    os.replace(tmp, path)


def read_csv(path, keep=None):
    """Rows of one dump CSV as dicts. keep(row) -> bool filters while streaming."""
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        rd = csv.DictReader(fh)
        if keep is None:
            return list(rd)
        return [r for r in rd if keep(r)]


def read_raw_rows(path):
    """The raw vintage rows dump_vintages stored (gzipped JSON list)."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def write_raw_rows(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def parse_date(s):
    """OOTP writes dates as 2027-1-1 (no zero padding). None when unreadable."""
    m = re.match(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})", str(s or ""))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------- profile and folders
def _settings():
    """tgs-viz/tools/settings.py, imported on first use (stdlib only)."""
    import sys
    tools = os.path.join(VIZ, "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import settings
    return settings


def profile(league):
    """League profile from ootp/leagues.json plus the profiles New League added
    (settings), with defaults. Raises only settings.SettingsError (a broken
    settings file stops the pipeline)."""
    try:
        profiles = _settings().ootp_profiles()
    except (OSError, ValueError):
        profiles = {}                              # leagues.json not readable: the defaults below
    prof = (profiles or {}).get(league) or {}
    if not isinstance(prof, dict):
        prof = {}
    out = {"game": str(prof.get("game") or "27"),
           "league": str(prof.get("league") or prof.get("folder") or league),   # winsim profiles say "folder"
           "source": str(prof.get("source") or "")}
    out.update({k: v for k, v in prof.items() if k not in out})
    return out


def is_dump_profile(league):
    return profile(league)["source"] == DUMP_SOURCE


def saved_games_dirs(game):
    """Candidate saved_games folders of one OOTP version, existing ones only.
    The settings folder (ootp.installs.<game>.saved_games) comes first."""
    home = os.path.expanduser("~")
    cands = [_settings().saved_games(game),
             os.path.join(home, "Documents", "Out of the Park Developments",
                          f"OOTP Baseball {game}", "saved_games"),
             os.path.join(home, "Library", "Application Support", "Out of the Park Developments",
                          f"OOTP Baseball {game}", "saved_games")]     # macOS
    for root in ("C:\\", "D:\\"):
        cands.append(os.path.join(root, f"OOTP {game}", "data", "saved_games"))
    out = []
    for c in cands:
        if c and os.path.isdir(c) and os.path.normcase(c) not in {os.path.normcase(x) for x in out}:
            out.append(c)
    return out


def league_dir(league, prof=None):
    """<saved_games>/<league name>.lg for the profile, or None. A profile New
    League wrote with a "dump_dir" (the dumps live elsewhere) returns that folder."""
    prof = prof or profile(league)
    if prof.get("dump_dir") and os.path.isdir(str(prof["dump_dir"])):
        return str(prof["dump_dir"])
    for d in saved_games_dirs(prof["game"]):
        p = os.path.join(d, prof["league"] + ".lg")
        if os.path.isdir(p):
            return p
    return None


def dump_dirs(root):
    """{year: csv dir} under a .lg folder, its dump/ folder, or one dump_<year>_yearly folder."""
    if not root:
        return {}
    root = os.path.normpath(root)
    if os.path.isdir(os.path.join(root, "dump")):
        root = os.path.join(root, "dump")
    out = {}
    pats = [root] if re.search(r"dump_\d{4}_yearly$", root) else glob.glob(os.path.join(root, "dump_*_yearly"))
    for d in pats:
        m = re.search(r"dump_(\d{4})_yearly$", d)
        csv_dir = os.path.join(d, "csv")
        if m and os.path.isfile(os.path.join(csv_dir, "players.csv")):
            out[int(m.group(1))] = csv_dir
    return dict(sorted(out.items()))


def year_of_dir(path):
    m = re.search(r"dump_(\d{4})_yearly", str(path or ""))
    return int(m.group(1)) if m else None


def sibling_file(csv_dir, name):
    """(path, borrowed_year) of a dump table: this dump's own copy, else the
    nearest other dump of the same league that has it. OOTP 27 does not write
    the same table set every year (the DEV TESTS 2025 dump had the league
    tables, the 2026 dump the team and stats tables), so STATIC tables such as
    leagues.csv and teams.csv are borrowed across years. Never use this for
    per-season data."""
    p = os.path.join(csv_dir, name)
    if os.path.isfile(p):
        return p, None
    root = os.path.dirname(os.path.dirname(os.path.normpath(csv_dir)))   # .../dump
    y0 = year_of_dir(csv_dir) or 0
    best = None
    for y, d in dump_dirs(root).items():
        q = os.path.join(d, name)
        if os.path.isfile(q) and (best is None or abs(y - y0) < abs(best[0] - y0)):
            best = (y, q)
    return (best[1], best[0]) if best else (None, None)


def _birthday(dob, years):
    try:
        return dob.replace(year=dob.year + years)
    except ValueError:                       # Feb 29
        return dob.replace(year=dob.year + years, day=28)


def date_from_ages(csv_dir, sample=5000):
    """In-game date pinned by the players' ages and birth dates: every player
    has had his age-th birthday and not yet his next one, so the latest
    age-th birthday among them is the earliest possible date and the earliest
    next birthday (minus a day) the latest. Returns (date, spread_days) or None."""
    lo = hi = None
    n = 0
    for r in read_csv(os.path.join(csv_dir, "players.csv"),
                      keep=lambda r: str(r.get("retired") or "0") == "0"):
        dob = parse_date(r.get("date_of_birth"))
        try:
            age = int(float(r.get("age")))
        except (TypeError, ValueError):
            continue
        if dob is None or age < 0 or age > 70:
            continue
        b_lo = _birthday(dob, age)
        b_hi = _birthday(dob, age + 1) - datetime.timedelta(days=1)
        lo = b_lo if lo is None or b_lo > lo else lo
        hi = b_hi if hi is None or b_hi < hi else hi
        n += 1
        if n >= sample:
            break
    if lo is None or hi is None or lo > hi:
        return None
    return lo, (hi - lo).days


GAME_SUM_BAT = ("pa", "ab", "h", "d", "t", "hr", "bb", "ibb", "hp", "sf", "sh", "k", "g")
GAME_SUM_PIT = ("bf", "ab", "ha", "da", "ta", "hra", "bb", "iw", "hp", "sf", "k", "g", "gs", "outs")


def season_from_games(path, year, lids, side):
    """Season totals per (player, league) summed from OOTP's per-game stats
    file (players_game_batting.csv / players_game_pitching_stats.csv), in the
    shape of the career-stats rows the lenses read: year, league_id, level_id,
    split_id 1, and the summed outcome counts. Only the year asked for and
    the leagues in `lids`; the per-game split_id 0 rows are the whole game."""
    keys = GAME_SUM_BAT if side == "bat" else GAME_SUM_PIT
    acc = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r.get("year") != str(year) or str(r.get("league_id")) not in lids:
                continue
            if str(r.get("split_id") or "0") not in ("0", "1"):
                continue
            k = (r.get("player_id"), r.get("league_id"))
            e = acc.get(k)
            if e is None:
                e = acc[k] = {"player_id": r.get("player_id"), "year": str(year),
                              "league_id": r.get("league_id"), "level_id": r.get("level_id"),
                              "split_id": "1", **{c: 0 for c in keys}}
            for c in keys:
                v = r.get(c)
                if v not in (None, ""):
                    try:
                        e[c] += int(float(v))
                    except ValueError:
                        pass
    return list(acc.values())


def dump_date(csv_dir, year):
    """In-game date of one dump: the top league's current_date in leagues.csv.
    Fallbacks: the date the players' ages and birth dates pin, the last played
    game of that year in games.csv, then October 1. Returns (date, how)."""
    try:
        best = None
        for r in read_csv(os.path.join(csv_dir, "leagues.csv")):
            d = parse_date(r.get("current_date"))
            if d is None:
                continue
            lvl = int(float(r.get("league_level") or 99))
            top = str(r.get("parent_league_id") or "0") == "0"
            key = (0 if top else 1, lvl)
            if best is None or key < best[0]:
                best = (key, d)
        if best:
            return best[1], "leagues.csv current_date"
    except (OSError, ValueError):
        pass
    try:
        pinned = date_from_ages(csv_dir)
        if pinned:
            return pinned[0], f"players.csv ages and birth dates (pinned to {pinned[1] + 1} day(s))"
    except (OSError, ValueError):
        pass
    try:
        last = None
        for r in read_csv(os.path.join(csv_dir, "games.csv"),
                          keep=lambda r: str(r.get("played")) == "1"):
            d = parse_date(r.get("date"))
            if d and d.year == year and (last is None or d > last):
                last = d
        if last:
            return last, "games.csv last played game"
    except (OSError, ValueError):
        pass
    return datetime.date(year, 10, 1), "fallback October 1"


# ---------------------------------------------------------------- scale
def scale_path(db_path, league):
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), f"league_scale_{league}.json")


def read_scale(db_path, league):
    """The stored league_scale_<LG>.json, or None."""
    d = read_json(scale_path(db_path, league))
    return d if isinstance(d, dict) and d.get("scale") in SCALES else None


def detect_scale(rows):
    """("20-80" | "1-100", stats) from raw vintage rows. Values 0 are absent
    skills and are not read. A 20-80 league steps in 5s (85+ exists for a few
    players); a 1-100 league has values off the 5-step grid and below 20."""
    n = off5 = below20 = 0
    vmax = 0
    for r in rows:
        for k in SCALE_KEYS:
            v = r.get(k)
            try:
                x = int(float(v))
            except (TypeError, ValueError):
                continue
            if x <= 0:
                continue
            n += 1
            vmax = max(vmax, x)
            if x % 5:
                off5 += 1
            if x < 20:
                below20 += 1
    stats = {"n": n, "max": vmax,
             "off5_share": round(off5 / n, 4) if n else None,
             "below20_share": round(below20 / n, 4) if n else None}
    if not n:
        return "20-80", stats
    scale = "1-100" if (off5 / n > OFF5_SHARE or below20 / n > BELOW20_SHARE) else "20-80"
    return scale, stats


def rated_floor(scale):
    """Smallest value that counts as a rated skill: 20 on 20-80, 1 on 1-100."""
    return 1 if scale == "1-100" else 20


# ---------------------------------------------------------------- the source
def db_path_of(conn):
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2]
    return None


def stored_dump_years(conn, league):
    """{year: (pull_id, real_date, csv_dir, raw_path)} of the league's dump pulls."""
    out = {}
    for pid, date, files in conn.execute(
            "SELECT pull_id, real_date, source_files FROM pulls WHERE league=? AND source=? "
            "ORDER BY real_date", (league, DUMP_SOURCE)):
        try:
            files = json.loads(files or "[]")
        except ValueError:
            files = []
        csv_dir = next((f for f in files if year_of_dir(f)), None)
        raw = next((f for f in files if str(f).endswith(".json.gz")), None)
        y = year_of_dir(csv_dir)
        if y is not None:
            out[y] = (pid, date, csv_dir, raw)
    return out


def for_league(conn, league):
    """DumpSource for a dump-sourced league, else None. A league is dump-sourced
    when it has pulls and every one of them carries source "dump"."""
    srcs = [r[0] for r in conn.execute("SELECT DISTINCT source FROM pulls WHERE league=?", (league,))]
    if not srcs or any(s != DUMP_SOURCE for s in srcs):
        return None
    return DumpSource(conn, league)


def league_scale(conn, league):
    """The league's rating scale for ratings_db: "20-80" unless the league is
    dump-sourced and its scale file says "1-100"."""
    src = for_league(conn, league)
    return src.scale if src is not None else "20-80"


class DumpSource:
    """Lens inputs for one dump-sourced league, read from the DB's own pull
    records, the raw vintage rows and the dump folders."""

    def __init__(self, conn, league):
        self.conn, self.league = conn, league
        self.db_path = db_path_of(conn) or os.path.join(HERE, "ratings_history.db")
        self.db_dir = os.path.dirname(os.path.abspath(self.db_path))
        self.years = stored_dump_years(conn, league)            # year -> (pull_id, date, csv_dir, raw)
        self.by_pull = {v[0]: (y,) + v[1:] for y, v in self.years.items()}
        meta = read_scale(self.db_path, league) or {}
        self.scale = meta.get("scale") if meta.get("scale") in SCALES else "20-80"
        self.meta = meta
        self.cache_dir = os.path.join(self.db_dir, ".lens_cache")
        self._raw = {}                                          # pull_id -> rows (last two)

    # -- dates ---------------------------------------------------------------
    def dates(self, pulls):
        """{pull_id: date}: a dump vintage's real_date is its in-game date."""
        out = {}
        for p in pulls:
            d = parse_date(p[1])
            if d:
                out[p[0]] = d
        return out

    def now(self):
        """In-game date of the newest vintage."""
        ds = [parse_date(v[1]) for v in self.years.values()]
        ds = [d for d in ds if d]
        return max(ds) if ds else None

    # -- raw rows --------------------------------------------------------------
    def raw_rows(self, pull_id):
        if pull_id in self._raw:
            return self._raw[pull_id]
        e = self.by_pull.get(pull_id)
        if not e or not e[3]:
            raise FileNotFoundError(f"pull {pull_id} of {self.league} has no raw vintage file on record")
        path = e[3]
        if not os.path.isabs(path):
            path = os.path.join(REPO, path)
        rows = read_raw_rows(path)
        if len(self._raw) >= 2:
            self._raw.pop(next(iter(self._raw)))
        self._raw[pull_id] = rows
        return rows

    def newest_pull_id(self):
        if not self.years:
            return None
        return self.years[max(self.years)][0]

    def people(self, pull):
        """{pid: [lev, club id, leadership H/N/L, no_team, foreign]} of one pull,
        the shape growth_lenses reads for the population gate, PT and LDR / NEG."""
        out = {}
        for r in self.raw_rows(pull[0]):
            pid = str(r.get("ID") or "").strip()
            if not pid:
                continue
            club = str(r.get("Team") or "").strip()
            lead = r.get("Lead")
            out[pid] = [r.get("Lev") or None, club if club not in ("", "0") else None,
                        lead if lead in ("H", "N", "L") else None,
                        str(r.get("LgLvl") or "").strip() in ("", "0"),
                        str(r.get("Foreign") or "0") == "1"]
        return out

    def personality(self):
        """{pid: {WE, INT, LEA, LOY, GRD}} from the newest vintage (H/N/L)."""
        pid_ = self.newest_pull_id()
        if pid_ is None:
            return {}
        out = {}
        for r in self.raw_rows(pid_):
            out[str(r.get("ID"))] = {"WE": r.get("WrkEthic"), "INT": r.get("Int"),
                                     "LEA": r.get("Lead"), "LOY": r.get("Loy"), "GRD": r.get("Greed")}
        return out

    # -- season stats -------------------------------------------------------
    def season_dir(self, year):
        """csv dir holding season `year`: that year's dump, else the next later one."""
        dirs = {y: v[2] for y, v in self.years.items() if v[2] and os.path.isdir(v[2])}
        root = self.meta.get("dump_root")
        if root:
            for y, d in dump_dirs(root).items():
                dirs.setdefault(y, d)
        later = sorted(y for y in dirs if y >= year)
        return dirs[later[0]] if later else None

    def season(self, year, now, log=print):
        """Season table for growth_lenses: {v, league, year, final, asof, lids,
        lg_woba, coverage, bat, pit}. Rows: players_career_*_stats.csv of the
        season's dump, split 1 (overall), leagues of leagues.csv only (no
        amateur rows). Cached next to the DB under .lens_cache/<LG>_<year>.json,
        keyed to the two CSV files' size and mtime. A missing dump gives a stub
        that growth_lenses leaves out."""
        import growth_lenses as GL
        csv_dir = self.season_dir(year)
        if not csv_dir:
            log(f"  lenses {self.league}: no dump holds season {year}; its pull pairs are left out of PT / PERF")
            return {"v": GL.CACHE_VERSION, "league": self.league, "year": year, "final": False,
                    "asof": None, "stub": True, "bat": {}, "pit": {}}
        bat_csv = os.path.join(csv_dir, "players_career_batting_stats.csv")
        pit_csv = os.path.join(csv_dir, "players_career_pitching_stats.csv")
        from_games = False
        if not (os.path.isfile(bat_csv) and os.path.isfile(pit_csv)):
            # OOTP 27 wrote no season-total files; the per-game files carry the
            # same PA / BF and outcome counts, summed here per player and league.
            bat_csv = os.path.join(csv_dir, "players_game_batting.csv")
            pit_csv = os.path.join(csv_dir, "players_game_pitching_stats.csv")
            from_games = True
            if not (os.path.isfile(bat_csv) and os.path.isfile(pit_csv)):
                log(f"  lenses {self.league}: the {year} dump holds no season or per-game stats files; "
                    f"its pull pairs are left out of PT / PERF")
                return {"v": GL.CACHE_VERSION, "league": self.league, "year": year, "final": False,
                        "asof": None, "stub": True, "bat": {}, "pit": {}}
        stamp = [[os.path.getsize(p), int(os.path.getmtime(p))] for p in (bat_csv, pit_csv)]
        path = os.path.join(self.cache_dir, f"{self.league}_{year}.json")
        cached = read_json(path)
        if (isinstance(cached, dict) and cached.get("v") == GL.CACHE_VERSION
                and cached.get("league") == self.league and cached.get("year") == year
                and cached.get("dump_stamp") == stamp and isinstance(cached.get("bat"), dict)):
            return cached
        lg_path, borrowed = sibling_file(csv_dir, "leagues.csv")
        if not lg_path:
            log(f"  lenses {self.league}: no leagues.csv in any dump; season {year} left out of PT / PERF")
            return {"v": GL.CACHE_VERSION, "league": self.league, "year": year, "final": False,
                    "asof": None, "stub": True, "bat": {}, "pit": {}}
        leagues = read_csv(lg_path)
        lids = [str(l.get("league_id")) for l in leagues if l.get("league_id")]
        if from_games:
            bat = season_from_games(bat_csv, year, lids, "bat")
            pit = season_from_games(pit_csv, year, lids, "pit")
            log(f"  lenses {self.league}: season {year} totals summed from the per-game files "
                f"({len(bat)} batting, {len(pit)} pitching player-league rows)")
        else:
            keep = lambda r: r.get("year") == str(year) and str(r.get("split_id")) == "1" and str(r.get("league_id")) in lids
            bat = read_csv(bat_csv, keep)
            pit = read_csv(pit_csv, keep)
        GL.check_feeds(leagues, bat, pit)
        means, cover = GL.league_means(bat, pit)
        asof, _how = dump_date(csv_dir, year_of_dir(csv_dir) or year)
        table = {"v": GL.CACHE_VERSION, "league": self.league, "year": year,
                 "final": GL.season_is_final(year, now) if now else False,
                 "asof": asof.isoformat(), "source": DUMP_SOURCE, "dump_dir": csv_dir, "dump_stamp": stamp,
                 "fetched": datetime.datetime.now().isoformat(timespec="seconds"),
                 "lids": lids, "lg_woba": {k: round(v, 4) for k, v in means.items()},
                 "coverage": cover,
                 "bat": GL._side_table(bat, "bat", means), "pit": GL._side_table(pit, "pit", means)}
        try:
            write_json(path, table, separators=(",", ":"))
        except OSError as e:
            log(f"  lenses {self.league}: season {year} not cached ({e})")
        return table
