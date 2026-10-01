"""
dev_odds.py - odds of becoming an MLB regular, measured in the DEV league.

The DEV league (all-AI OOTP 27, true ratings, one dump per game-year) is the
only place where a young player's full career is known. This script reads its
raw vintages (vintages/DEV/raw_<year>.json.gz) and its per-game MLB stats,
follows every player first seen at age 20 or younger, and counts how many
became a regular. The counts are grouped by age, OOTP Pot grade and the
growth of the core skills over the previous game-year.

Output: tgs-viz/public/data/dev_odds.json (schema in build_payload). TGS and
BLM never enter this file. They only read the grid, through dev_signals.

Definitions:
  regular    a season with >= 300 MLB PA (hitter) or >= 150 MLB BF (pitcher)
  outcome    the player ever had a regular season through the last dump
  cohort     players first seen at age <= 20 in dumps 2025-2040, ever in an org
  age        the Age field of the dump (Jan-1 age; dump_<year> is dated Jan 1 of year+1)
  Pot        the OOTP Pot grade of that dump (raw "Pot"; absent in 2025)
  growth     sum over the core skills of (display now - display last dump) / 5,
             display = mean of the vR and vL ratings; half steps occur
  core sum   sum over the core skills of underlying(display), band middles below
  pot_dir    Pot grade rose / held / fell over the previous dump

Core skills, identical on the TGS / BLM side:
  hitters   BABIP, GAP, POW, EYE, K        (raw BABIP, Gap, Pow, Eye, Ks)
  pitchers  STU, HRR, PBABIP, CON          (raw Stf, HRA, PBABIP, Ctrl)

MLB playing time comes from the dump's per-game files, summed per player at
level_id 1, and is cached under .dev_cache/ keyed to each file's size and
mtime. A re-dumped year rebuilds only itself.

Eventual peak ("Exp peak"):
  The app's listed peak (MAX WAA P / WAP) prices the potential ratings OOTP
  shows today. OOTP raises those ratings later for the players who make it,
  so a negative listed peak often sits next to a high Make-it %. The peak
  tables answer "what did DEV players in this cell become". They read the
  engine WAA per DEV vintage from vintages/DEV/.waa_cache/ (one file per
  vintage, {pid: [now_WAA, ceiling_WAA, kind, age, ...]}, BLM engine, neutral
  park; the file tagged '<BLM fingerprint>-BLM' per vintage, never the newest
  file (WAA_CALIB); a file dated Jan 1 of year+1 belongs to dump_<year>).
  eventual peak  max of now_WAA over the player's dumps at ages >= the cell
                 age; counted only for players seen at age >= 27, so the
                 peak is realized
  ceiling        ceiling_WAA at the observation's dump: the listed peak of
                 that day
  listed_gap     mean of (eventual peak - ceiling) over the cell
  reach_share    share of the cell whose eventual peak >= that day's ceiling
  gain           eventual peak minus the player's now_WAA at the observation's
                 dump (element 0 of the cache row); the cell ships gain_p25,
                 gain_p50, gain_p75, gain_mean and gain_n. The peak includes
                 the observation's own dump, so a gain is never below 0. A
                 dump the cache did not price gives no gain (gain_n < n).
                 The app adds gain_p50 to a player's current WAA to set his
                 growth target: a cell's peak level would jump a player far
                 below his cell's usual current, the gain does not.
  mlb_share      share of the cell whose eventual peak reached -1.0 WAA (an
                 MLB-level player, a 5th starter or bench bat). User,
                 2026-09-24: "if they will ever be anything in the mlb"; the
                 org builder orders minors playing time by this chance first.
  useful_share   share of the cell whose eventual peak reached 0 WAA (an
                 average MLB player); good_share = the share that reached
                 +1.5 (a clear regular). The bars are PEAK_BARS. User,
                 2026-09-24: Make it % is playing time, not quality; these
                 two say whether the lookalikes turned out good enough.
  gain_grid      the cell's gains at quantiles 5, 10, ..., 95 (19 values,
                 GAIN_GRID_PCTS) over every row with a priced now_WAA. It
                 lets dev_signals turn the shares into a chance FROM WHERE
                 THE PLAYER IS NOW: the share of gains at or above (bar -
                 his current WAA). User, 2026-09-24: "there are a ton of
                 guys who are already at 0+ WAA that are getting like
                 tagged as less than 100% to reach it", so the shares above
                 (the cell's peak distribution, blind to his current) are
                 kept for reference and the app's chance is the conditional
                 one.
  by_now         3 sub-cells by now_WAA tercile (cut points from the cell's
                 own nows): lo / hi = the sub-cell's now range, n, its own
                 gain_grid, and mlb / useful / good = the share of the
                 sub-cell's eventual peaks at or above each PEAK_BARS bar.
                 Lookalikes at a similar current gain differently from the
                 whole cell (a player near the top of the cell has less
                 room). The peak-level shares serve a player whose current
                 sits outside every sub-cell's range (above the top hi or
                 below the bottom lo): the gain rule would lend him gains
                 measured on players who were never where he is, so
                 dev_signals reads the nearest sub-cell's own outcome share
                 instead (2026-09-24: a P 20 at -1.44 WAA read 98% MLB in a
                 cell where 7% ever reached the bar). Left out when fewer
                 than MIN_CELL_NOTE rows have a priced now.
  observations   the same rows as grid (peak) and pot_only (peak_pot_only)

CLI:
  python tgs-viz/backtest/dev_odds.py            print the tables, write nothing
  python tgs-viz/backtest/dev_odds.py --write    also write public/data/dev_odds.json
  --rebuild                                      ignore the playing-time cache
  --dump-root PATH                               the DEV .lg folder or its dump/ folder
"""
import argparse
import csv
import datetime
import glob
import gzip
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dump_source as DS                                     # noqa: E402

LEAGUE = "DEV"
VINT_DIR = os.path.join(HERE, "vintages", LEAGUE)
CACHE_DIR = os.path.join(HERE, ".dev_cache")
PT_CACHE = os.path.join(CACHE_DIR, "dev_mlb_pt.json.gz")
OUT_PATH = os.path.join(VIZ, "public", "data", "dev_odds.json")
DB_PATH = os.path.join(HERE, "ratings_history.db")
CACHE_VERSION = 1

REGULAR_PA = 300
REGULAR_BF = 150
# Cohort window (2026-09-25, user: "i plan on getting about 1000 seasons of
# data to train on ... is there a way to train the model on the new data"):
# players first seen from COHORT_START to the last banked dump year minus
# COHORT_MARGIN, so every cohort player has had 23 seasons to finish his
# career (first seen at 20 or younger, 43 or older at the last dump). It was
# fixed at 2025-2040, which kept every season after 2063 out of the odds,
# the Make-it odds tables and the dev signals. measure() sets it from the
# banked seasons; the value below is only the start-up default.
COHORT_START = 2025
COHORT_MARGIN = 23
COHORT_YEARS = (2025, 2040)
COHORT_MAX_AGE = 20
AGES = list(range(16, 27))          # 16-26: the grid covers every age that still develops (user, 2026-09-24)
MIN_CELL_NOTE = 15

ORG_LEV = {"R", "A", "A-", "A+", "AA", "AAA", "MLB"}
PITCHER_POS = {"SP", "RP", "CL"}

# core skills: output name -> raw key stem (raw has <stem>_R and <stem>_L)
CORE = {
    "H": [("BABIP", "BABIP"), ("GAP", "Gap"), ("POW", "Pow"), ("EYE", "Eye"), ("K", "Ks")],
    "P": [("STU", "Stf"), ("HRR", "HRA"), ("PBABIP", "PBABIP"), ("CON", "Ctrl")],
}
# the previous analysis summed OOTP's composite ratings, 6 for hitters, 5 for pitchers
LEGACY = {"H": ["Cntct", "Gap", "Pow", "Eye", "Ks", "BABIP"],
          "P": ["Stf", "Mov", "Ctrl", "HRA", "PBABIP"]}

# internal scale: band middles of the 20-80 display bands
INTERNAL = {20: 115.5, 25: 153.5, 30: 198.0, 35: 249.5, 40: 299.0, 45: 348.5, 50: 393.5,
            55: 424.5, 60: 443.0, 65: 457.0, 70: 471.5, 75: 485.5, 80: 505.0, 85: 559.0}
INTERNAL_TEXT = ("band middles " + " ".join(f"{k}:{v:g}" for k, v in INTERNAL.items())
                 + "; 85 and above = 559; below 20 = 115.5; a display value between two "
                   "bands interpolates linearly (a vR/vL mean can end in 2.5)")

GROWTH_BUCKETS = {"H": ["<=0", "0.5-2", "2.5-4", "4.5-6", "6.5+"],
                  "P": ["<=0", "0.5-1.5", "2-3", "3.5+"]}
POT_BUCKETS = ["<40", "40-44", "45-49", "50-54", "55+"]
POT_DIRS = ["up", "flat", "down"]
POT_DIR_MIN = 45

WAA_CACHE_DIR = os.path.join(VINT_DIR, ".waa_cache")
# The cell method's basis is DEV priced with the BLM engine calibration: the
# files agecurve_fit --league DEV --calib BLM writes, tagged
# '<BLM fingerprint>-BLM' (197c3f18ed-BLM on 2026-09-25). load_waa picks that
# file per vintage by its tag, never "the newest file": a DEV file priced with
# any other calibration (the TGS one, or DEV's own) must never switch the cell
# method's basis just because it was written later (fix of 2026-09-25). A
# vintage not yet re-priced after a BLM recalibration reads its newest file
# from an earlier BLM fingerprint (still the BLM basis; the log counts them).
WAA_CALIB = "BLM"
CALIB_DIR = os.path.join(VIZ, "engine", "calib")
PEAK_MIN_AGE = 27               # a player counts once a dump shows him at this age or older
PEAK_PCTS = (10, 25, 50, 75, 90)
# "mlb" = the eventual peak WAA reached -1.0 (an MLB-level player, a 5th starter
# or bench bat; user, 2026-09-24: "if they will ever be anything in the mlb"),
# "useful" = it reached 0 (an average MLB player), "good" = it reached +1.5 (a
# clear regular). User, 2026-09-24: Make it % is playing time, not quality;
# these say whether the lookalikes turned out good enough.
PEAK_BARS = {"mlb": -1.0, "useful": 0.0, "good": 1.5}
# gain_grid quantile levels: 5, 10, ..., 95 (19 values). grid[i] is the gain
# at level (i + 1) * 5 percent, so the share of gains at or above grid[i] is
# 1 - that level. dev_signals reads the share at (bar - the player's current
# WAA) off this grid (user, 2026-09-24: a player already at the bar reads 100%).
GAIN_GRID_PCTS = tuple(range(5, 100, 5))
NOW_TERCILES = 3                # by_now sub-cells per cell, cut at the cell's own now terciles


# ---------------------------------------------------------------- scale helpers
def underlying(display):
    """Internal points of one display value. Linear between band middles."""
    if display is None:
        return None
    v = float(display)
    if v <= 20:
        return INTERNAL[20]
    if v >= 85:
        return INTERNAL[85]
    lo = int(v // 5) * 5
    hi = lo + 5
    if hi > 85:
        return INTERNAL[85]
    a, b = INTERNAL[lo], INTERNAL[hi]
    return a + (b - a) * (v - lo) / 5.0


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def display(rec, stem):
    """Display value of one skill: the mean of its vR and vL ratings."""
    r, l = to_int(rec.get(stem + "_R")), to_int(rec.get(stem + "_L"))
    if r is None or l is None:
        return None
    return (r + l) / 2.0


def role_of(pos):
    return "P" if pos in PITCHER_POS else "H"


def growth_bucket(role, g):
    if g <= 0:
        return "<=0"
    if role == "H":
        if g <= 2:
            return "0.5-2"
        if g <= 4:
            return "2.5-4"
        if g <= 6:
            return "4.5-6"
        return "6.5+"
    if g <= 1.5:
        return "0.5-1.5"
    if g <= 3:
        return "2-3"
    return "3.5+"


def pot_bucket(p):
    if p < 40:
        return "<40"
    if p < 45:
        return "40-44"
    if p < 50:
        return "45-49"
    if p < 55:
        return "50-54"
    return "55+"


# ---------------------------------------------------------------- dump files
def find_dump_root(override=None):
    """The DEV dump folder: --dump-root, else league_scale_DEV.json, else the profile."""
    if override:
        return override
    scale = DS.read_scale(DB_PATH, LEAGUE)
    if scale and scale.get("dump_root") and os.path.isdir(scale["dump_root"]):
        return scale["dump_root"]
    return DS.league_dir(LEAGUE)


def sum_mlb_pt(path, pt_col):
    """{player_id: sum of pt_col} over the rows of one per-game file at level_id 1."""
    out = Counter()
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        r = csv.reader(fh)
        hdr = next(r)
        ix = {h: i for i, h in enumerate(hdr)}
        ipid, ilev, ipt = ix["player_id"], ix["level_id"], ix[pt_col]
        for row in r:
            if row[ilev] != "1":
                continue
            try:
                out[row[ipid]] += int(float(row[ipt]))
            except (ValueError, IndexError):
                pass
    return dict(out)


def load_mlb_pt(dump_root, rebuild=False, log=print):
    """{year: {"pa": {pid: PA}, "bf": {pid: BF}}} at MLB, from the cache or the dump.
    Each year is keyed to the size and mtime of its two per-game files."""
    dirs = DS.dump_dirs(dump_root) if dump_root else {}
    cached = {}
    if not rebuild and os.path.isfile(PT_CACHE):
        try:
            with gzip.open(PT_CACHE, "rt", encoding="utf-8") as fh:
                c = json.load(fh)
            if isinstance(c, dict) and c.get("v") == CACHE_VERSION:
                cached = c.get("years") or {}
        except (OSError, ValueError):
            cached = {}
    years = {}
    rebuilt = 0
    for y, csv_dir in dirs.items():
        bat = os.path.join(csv_dir, "players_game_batting.csv")
        pit = os.path.join(csv_dir, "players_game_pitching_stats.csv")
        if not (os.path.isfile(bat) and os.path.isfile(pit)):
            continue
        stamp = [[os.path.getsize(p), int(os.path.getmtime(p))] for p in (bat, pit)]
        c = cached.get(str(y))
        if c and c.get("stamp") == stamp and isinstance(c.get("pa"), dict) and isinstance(c.get("bf"), dict):
            years[y] = c
            continue
        years[y] = {"stamp": stamp, "pa": sum_mlb_pt(bat, "pa"), "bf": sum_mlb_pt(pit, "bf")}
        rebuilt += 1
        log(f"  playing time {y}: summed from the per-game files "
            f"({len(years[y]['pa'])} MLB batters, {len(years[y]['bf'])} MLB pitchers)")
    if not years:
        raise SystemExit(f"no per-game stats files under {dump_root!r}; cannot measure outcomes")
    if rebuilt or not os.path.isfile(PT_CACHE):
        os.makedirs(CACHE_DIR, exist_ok=True)
        with gzip.open(PT_CACHE, "wt", encoding="utf-8") as fh:
            json.dump({"v": CACHE_VERSION, "league": LEAGUE,
                       "years": {str(y): v for y, v in years.items()}}, fh)
        log(f"  playing-time cache written: {PT_CACHE} ({rebuilt} year(s) rebuilt)")
    return years


# ---------------------------------------------------------------- raw vintages
def raw_years():
    out = {}
    for p in glob.glob(os.path.join(VINT_DIR, "raw_*.json.gz")):
        m = re.search(r"raw_(\d{4})\.json\.gz$", p)
        if m:
            out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def slim(rec):
    """The fields one player-dump needs, as numbers."""
    out = {"age": to_int(rec.get("Age")), "pos": rec.get("Pos") or "",
           "lev": rec.get("Lev") or "", "pot": to_int(rec.get("Pot"))}
    for role, skills in CORE.items():
        out[role] = [display(rec, stem) for _name, stem in skills]
        out["L" + role] = [to_int(rec.get(k)) for k in LEGACY[role]]
    return out


def load_players(log=print):
    """{pid: {year: slim record}} over every raw DEV vintage."""
    players = defaultdict(dict)
    years = raw_years()
    if not years:
        raise SystemExit(f"no raw vintages under {VINT_DIR}")
    for y, path in years.items():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        for r in rows:
            pid = str(r.get("ID") or "")
            if pid:
                players[pid][y] = slim(r)
    log(f"  raw vintages: {len(years)} dumps {min(years)}-{max(years)}, {len(players)} players")
    return dict(players), (min(years), max(years))


# ---------------------------------------------------------------- engine WAA cache
def calib_fingerprint(league):
    """engine/agecurve_fit.calib_fingerprint, copied so this script needs no
    engine import: md5 of the calib files the engine reads, first 10 hex."""
    h = hashlib.md5()
    for fn in ("constants-latest.json", "scurves.json", "fielding_curves.json", "hitter_tails.json",
               "role_stuff.json", "currency.json"):
        p = os.path.join(CALIB_DIR, league, fn)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:10]


def waa_tag():
    """File tag of the cell method's DEV prices: '<BLM fingerprint>-BLM'."""
    return f"{calib_fingerprint(WAA_CALIB)}-{WAA_CALIB}"


def load_waa(log=print):
    """{dump year: {pid: (now_WAA, ceiling_WAA, age)}} from the engine WAA cache.

    One file per vintage, picked by its calibration tag (WAA_CALIB): the file
    tagged waa_tag() (DEV priced with the current BLM calibration). A vintage
    with no such file (the BLM calibration changed and DEV is not re-priced
    yet) falls back to its newest file tagged with an earlier BLM fingerprint,
    and the log counts those. A file priced with any other calibration is
    never read. The file's leading date is Jan 1 after the season, so year =
    date year - 1. Rows without two finite numbers are skipped."""
    tag = waa_tag()
    suffix = f"-{WAA_CALIB}.json"
    picked, older = {}, {}
    other = 0
    for p in glob.glob(os.path.join(WAA_CACHE_DIR, "*.json")):
        name = os.path.basename(p)
        m = re.match(r"(\d{4})-\d{2}-\d{2}_", name)
        if not m:
            continue
        year = int(m.group(1)) - 1
        if name.endswith(f".{tag}.json"):
            picked[year] = p
        elif name.endswith(suffix):
            mt = os.path.getmtime(p)
            if year not in older or mt > older[year][0]:
                older[year] = (mt, p)
        else:
            other += 1
    stale = sorted(y for y in older if y not in picked)
    for y in stale:
        picked[y] = older[y][1]
    log(f"  waa cache: {len(picked) - len(stale)} vintages tagged {tag} ({WAA_CALIB} calibration); "
        f"{len(stale)} on an earlier {WAA_CALIB} fingerprint (re-price DEV: python tgs-viz/engine/"
        f"agecurve_fit.py --league DEV --calib {WAA_CALIB} --no-guard); {other} files of other "
        f"calibrations ignored")
    out = {}
    for year, p in sorted(picked.items()):
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            log(f"  waa cache {os.path.basename(p)}: unreadable ({e}); skipped")
            continue
        rows = {}
        for pid, v in d.items():
            try:
                now, ceil = float(v[0]), float(v[1])
                age = to_int(v[3]) if len(v) > 3 else None
            except (TypeError, ValueError, IndexError):
                continue
            if math.isfinite(now) and math.isfinite(ceil):
                rows[str(pid)] = (now, ceil, age)
        out[year] = rows
    if out:
        log(f"  waa cache: {len(out)} vintages {min(out)}-{max(out)}, "
            f"{sum(len(v) for v in out.values())} player-dumps priced")
    else:
        log(f"  waa cache: none under {WAA_CACHE_DIR}; peak tables stay empty")
    return out


def stamp_peaks(players, cohort, obs, obs_all, waa, log=print):
    """Add peak, ceil and now to every observation whose player's peak is realized.

    peak = max now_WAA over the player's cache dumps at years >= the
    observation year (his ages >= the cell age). ceil = ceiling_WAA and
    now = now_WAA at the observation's dump, None when that dump did not
    price him. A player counts when some cache dump shows him at age >=
    PEAK_MIN_AGE; the other observations keep peak None. Returns (realized
    players, stamped rows)."""
    series = defaultdict(list)                   # pid -> [(year, now, ceil, age)]
    for year, rows in waa.items():
        for pid, (now, ceil, age) in rows.items():
            if pid in cohort:
                series[pid].append((year, now, ceil, age))
    suffix = {}                                  # pid -> ([years asc], [max now from that year on])
    realized = set()
    for pid, rows in series.items():
        rows.sort()
        ages = [a if a is not None else (players[pid].get(y) or {}).get("age") for y, _n, _c, a in rows]
        if not any(a is not None and a >= PEAK_MIN_AGE for a in ages):
            continue
        realized.add(pid)
        years = [y for y, _n, _c, _a in rows]
        best = [0.0] * len(rows)
        run = None
        for i in range(len(rows) - 1, -1, -1):
            now = rows[i][1]
            run = now if run is None or now > run else run
            best[i] = run
        suffix[pid] = (years, best, {y: c for y, _n, c, _a in rows}, {y: n for y, n, _c, _a in rows})
    stamped = 0
    for o in obs_all + obs:
        o["peak"] = o["ceil"] = o["now"] = None
        s = suffix.get(o["pid"])
        if s is None:
            continue
        years, best, ceils, nows = s
        i = 0
        while i < len(years) and years[i] < o["year"]:
            i += 1
        if i >= len(years):
            continue
        o["peak"] = best[i]
        o["ceil"] = ceils.get(o["year"])
        o["now"] = nows.get(o["year"])
        stamped += 1
    log(f"  peaks: {len(realized)} cohort players seen at age >= {PEAK_MIN_AGE} in the cache; "
        f"{stamped} of {len(obs) + len(obs_all)} observation rows stamped")
    return realized, stamped


# ---------------------------------------------------------------- measure
class Cell:
    __slots__ = ("n", "k", "s", "s2")

    def __init__(self):
        self.n = 0
        self.k = 0
        self.s = 0.0
        self.s2 = 0.0

    def add(self, reg, x=None):
        self.n += 1
        self.k += 1 if reg else 0
        if x is not None:
            self.s += x
            self.s2 += x * x

    def odds(self):
        return {"p": round(self.k / self.n, 3) if self.n else None, "n": self.n}

    def typical(self):
        if not self.n:
            return {"core_sum_mean": None, "core_sum_sd": None, "n": 0}
        m = self.s / self.n
        var = max(self.s2 / self.n - m * m, 0.0)
        return {"core_sum_mean": round(m, 1), "core_sum_sd": round(math.sqrt(var), 1), "n": self.n}


def percentile(sorted_vals, q):
    """Percentile q (0-100) of an ascending list, linear between neighbours."""
    n = len(sorted_vals)
    if not n:
        return None
    pos = (n - 1) * q / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def gain_grid(gains):
    """The gains at quantiles GAIN_GRID_PCTS (19 values, 2 decimals), or None
    when the list is empty. gains must be sorted ascending."""
    if not gains:
        return None
    return [round(percentile(gains, q), 2) for q in GAIN_GRID_PCTS]


def by_now_terciles(rows_np):
    """Split (now, gain, peak) rows into NOW_TERCILES sub-cells at the
    terciles of the nows. Each sub-cell ships lo / hi (its now range), n,
    mlb / useful / good (the share of its eventual peaks at or above each
    PEAK_BARS bar: the sub-cell's own outcome, for a player whose current
    sits outside every sub-cell's range) and gain_grid. An empty sub-cell
    (heavy ties) ships n 0 and nulls. Key order matters: dumps_compact
    keeps a sub-cell on one line only while gain_grid is its last key."""
    nows = sorted(n for n, _g, _p in rows_np)
    cuts = [percentile(nows, 100.0 * (i + 1) / NOW_TERCILES) for i in range(NOW_TERCILES - 1)]
    subs = [[] for _ in range(NOW_TERCILES)]
    for now, gain, peak in rows_np:
        i = 0
        while i < len(cuts) and now > cuts[i]:
            i += 1
        subs[i].append((now, gain, peak))
    out = []
    for rows in subs:
        if not rows:
            sub = {"lo": None, "hi": None, "n": 0}
            sub.update({name: None for name in PEAK_BARS})
            sub["gain_grid"] = None
            out.append(sub)
            continue
        ns = [n for n, _g, _p in rows]
        sub = {"lo": round(min(ns), 2), "hi": round(max(ns), 2), "n": len(rows)}
        # the sub-cell's own outcome: the share whose eventual peak reached
        # each bar, read by dev_signals for a player above or below every
        # lookalike's current (the gain rule would borrow gains measured on
        # players who were never where he is)
        for name, bar in PEAK_BARS.items():
            sub[name] = round(sum(1 for _n, _g, p in rows if p >= bar) / len(rows), 3)
        sub["gain_grid"] = gain_grid(sorted(g for _n, g, _p in rows))
        out.append(sub)
    return out


class PeakCell:
    """Eventual peak WAA of one cell, how it compares to the listed ceiling,
    and the gain from the observation's now_WAA to that peak. Keeps the
    (now, gain, peak) rows so the gain and the outcome can be read
    conditional on the now."""
    __slots__ = ("vals", "gaps", "reach", "gains", "pairs")

    def __init__(self):
        self.vals = []
        self.gaps = []
        self.reach = 0
        self.gains = []
        self.pairs = []

    def add(self, peak, ceil, now=None):
        self.vals.append(peak)
        if ceil is not None:
            self.gaps.append(peak - ceil)
            self.reach += 1 if peak >= ceil else 0
        if now is not None:
            self.gains.append(peak - now)
            self.pairs.append((now, peak - now, peak))

    def stats(self):
        n = len(self.vals)
        out = {"n": n}
        v = sorted(self.vals)
        for q in PEAK_PCTS:
            out[f"p{q}"] = round(percentile(v, q), 2) if n else None
        out["mean"] = round(sum(v) / n, 2) if n else None
        m = len(self.gaps)
        out["listed_gap"] = round(sum(self.gaps) / m, 2) if m else None
        out["reach_share"] = round(self.reach / m, 3) if m else None
        g = sorted(self.gains)
        k = len(g)
        out["gain_n"] = k
        for q in (25, 50, 75):
            out[f"gain_p{q}"] = round(percentile(g, q), 2) if k else None
        out["gain_mean"] = round(sum(g) / k, 2) if k else None
        # share of the cell whose eventual peak reached each PEAK_BARS bar:
        # mlb_share, useful_share, good_share (user, 2026-09-24: the chance to
        # be anything in MLB, then quality, next to the playing-time Make it %)
        for name, bar in PEAK_BARS.items():
            out[f"{name}_share"] = round(sum(1 for x in v if x >= bar) / n, 3) if n else None
        # the gain distribution itself, so the consumer can read the chance
        # from where a player is now (user, 2026-09-24: a player already at
        # 0+ WAA must not read under 100% to reach 0): gain_grid over every
        # priced row, by_now the same per now-WAA tercile, only when the cell
        # has MIN_CELL_NOTE priced rows (keeps the file small)
        out["gain_grid"] = gain_grid(g)
        out["by_now"] = by_now_terciles(self.pairs) if k >= MIN_CELL_NOTE else None
        return out


def measure(players, pt, log=print):
    """Cohort, outcomes and every player-dump observation at ages 16-26."""
    global COHORT_YEARS
    last = max((max(yrs) for yrs in players.values() if yrs), default=COHORT_START)
    COHORT_YEARS = (COHORT_START, max(COHORT_START, last - COHORT_MARGIN))
    log(f"  cohort: first seen {COHORT_YEARS[0]}-{COHORT_YEARS[1]} "
        f"(last dump {last}, {COHORT_MARGIN} seasons to finish a career)")
    max_pa, max_bf = Counter(), Counter()
    for y, t in pt.items():
        for pid, v in t["pa"].items():
            if v > max_pa[pid]:
                max_pa[pid] = v
        for pid, v in t["bf"].items():
            if v > max_bf[pid]:
                max_bf[pid] = v

    def regular(pid):
        return max_pa[pid] >= REGULAR_PA or max_bf[pid] >= REGULAR_BF

    cohort = {}
    for pid, yrs in players.items():
        y0 = min(yrs)
        a0 = yrs[y0]["age"]
        if a0 is None or a0 > COHORT_MAX_AGE or not (COHORT_YEARS[0] <= y0 <= COHORT_YEARS[1]):
            continue
        if not any(r["lev"] in ORG_LEV for r in yrs.values()):
            continue
        role = Counter(role_of(r["pos"]) for r in yrs.values()).most_common(1)[0][0]
        cohort[pid] = (role, regular(pid))

    obs = []            # observations with a previous dump
    obs_all = []        # every in-org observation at 16-26, previous dump or not
    for pid, (_role, reg) in cohort.items():
        yrs = players[pid]
        for y, r in yrs.items():
            a = r["age"]
            if a is None or a < AGES[0] or a > AGES[-1] or r["lev"] not in ORG_LEV:
                continue
            role = role_of(r["pos"])
            cur = r[role]
            if any(v is None for v in cur) or r["pot"] is None:
                continue
            core_sum = sum(underlying(v) for v in cur)
            o = {"pid": pid, "year": y, "age": a, "role": role, "pot": r["pot"],
                 "core_sum": core_sum, "reg": reg, "lev": r["lev"]}
            obs_all.append(o)
            prev = yrs.get(y - 1)
            if prev is None:
                continue
            pcur = prev[role]
            if any(v is None for v in pcur):
                continue
            grow = round(sum((c - p) / 5.0 for c, p in zip(cur, pcur)) * 2) / 2.0
            o = dict(o, grow=grow)
            o["pot_delta"] = (r["pot"] - prev["pot"]) if prev["pot"] is not None else None
            lc, lp = r["L" + role], prev["L" + role]
            o["legacy"] = (sum((c - p) / 5.0 for c, p in zip(lc, lp))
                           if not any(v is None for v in lc + lp) else None)
            obs.append(o)
    log(f"  cohort: {len(cohort)} players, {len(obs)} observations with a previous dump, "
        f"{len(obs_all)} in total")
    return cohort, obs, obs_all


def build_payload(cohort, obs, obs_all, seasons, peak_basis=None):
    grid = {role: {str(a): {pb: {gb: Cell() for gb in GROWTH_BUCKETS[role]} for pb in POT_BUCKETS}
                   for a in AGES} for role in ("H", "P")}
    pdir = {role: {str(a): {d: Cell() for d in POT_DIRS} for a in AGES} for role in ("H", "P")}
    typ = {role: {str(a): {pb: Cell() for pb in POT_BUCKETS} for a in AGES} for role in ("H", "P")}
    ponly = {role: {str(a): {pb: Cell() for pb in POT_BUCKETS} for a in AGES} for role in ("H", "P")}
    peak = {role: {str(a): {pb: {gb: PeakCell() for gb in GROWTH_BUCKETS[role]} for pb in POT_BUCKETS}
                   for a in AGES} for role in ("H", "P")}
    peak_ponly = {role: {str(a): {pb: PeakCell() for pb in POT_BUCKETS} for a in AGES}
                  for role in ("H", "P")}
    for o in obs:
        a, role, pb = str(o["age"]), o["role"], pot_bucket(o["pot"])
        gb = growth_bucket(role, o["grow"])
        grid[role][a][pb][gb].add(o["reg"])
        typ[role][a][pb].add(o["reg"], o["core_sum"])
        if o["pot_delta"] is not None and o["pot"] >= POT_DIR_MIN:
            d = "up" if o["pot_delta"] > 0 else "down" if o["pot_delta"] < 0 else "flat"
            pdir[role][a][d].add(o["reg"])
        if o.get("peak") is not None:
            peak[role][a][pb][gb].add(o["peak"], o.get("ceil"), o.get("now"))
    for o in obs_all:
        a, role, pb = str(o["age"]), o["role"], pot_bucket(o["pot"])
        ponly[role][a][pb].add(o["reg"])
        if o.get("peak") is not None:
            peak_ponly[role][a][pb].add(o["peak"], o.get("ceil"), o.get("now"))

    roles = Counter(role for role, _reg in cohort.values())
    reg_rate = {}
    for role in ("H", "P"):
        n = roles[role]
        k = sum(1 for r, reg in cohort.values() if r == role and reg)
        reg_rate[role] = round(k / n, 3) if n else None

    def walk(tree, fn):
        return {k: (walk(v, fn) if isinstance(v, dict) else fn(v)) for k, v in tree.items()}

    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": LEAGUE,
        "seasons": [seasons[0], seasons[1]],
        "cohort": {"players": len(cohort), "hitters": roles["H"], "pitchers": roles["P"],
                   "regular_rate": reg_rate},
        "definitions": {
            "regular": f"a season with >= {REGULAR_PA} MLB PA (hitter) or >= {REGULAR_BF} MLB BF (pitcher); "
                       "MLB = level_id 1 of the dump's per-game files, summed per player and season",
            "outcome": "the player ever had a regular season, either way, through the last dump",
            "cohort": f"players first seen at age <= {COHORT_MAX_AGE} in dumps {COHORT_YEARS[0]}-{COHORT_YEARS[1]} "
                      "who were ever in an org (level R, A, AA, AAA or MLB); hitters / pitchers by the "
                      "role they held in most dumps",
            "observation": "one player-dump at ages 16-26, in an org at that dump, with the previous "
                           "game-year's dump present; the same player counts once per age",
            "age": "the dump's Age field: the Jan-1 age, dump_<year> being dated Jan 1 of year+1",
            "pot": "the OOTP Pot grade of that dump (1-point steps, 20-80)",
            "role": "P when the dump position is SP, RP or CL, else H",
            "core_skills": "H: BABIP GAP POW EYE K (raw BABIP Gap Pow Eye Ks); P: STU HRR PBABIP CON "
                           "(raw Stf HRA PBABIP Ctrl); a skill's display value is the mean of its vR and vL ratings",
            "growth": "sum over the core skills of (display now - display at the previous dump) / 5, "
                      "over one game-year, rounded to 0.5; half steps occur because a display value "
                      "is a vR/vL mean",
            "pot_dir": f"up / flat / down by the Pot grade change over the previous dump, Pot >= {POT_DIR_MIN} only",
            "core_sum": "sum over the core skills of underlying(display value)",
            "internal_scale": INTERNAL_TEXT,
            "typical": "mean and population sd of core_sum per age and Pot bucket, all outcomes pooled, "
                       "same observations as grid",
            "pot_only": "odds by age and Pot bucket alone, over every in-org observation at 16-26 with "
                        "or without a previous dump; for a player whose growth is unknown",
            "cells": f"every cell ships with its n; cells with n < {MIN_CELL_NOTE} are thin and the "
                     "consumer decides",
        },
        "growth_buckets": GROWTH_BUCKETS,
        "pot_buckets": POT_BUCKETS,
        "ages": AGES,
        "grid": walk(grid, Cell.odds),
        "pot_dir": walk(pdir, Cell.odds),
        "typical": walk(typ, Cell.typical),
        "pot_only": walk(ponly, Cell.odds),
        "peak_definition": (
            "eventual peak WAA of the DEV players in a cell: per observation, the max of the "
            "player's engine now_WAA over his dumps at ages >= the cell age (BLM engine "
            "calibration, neutral park, from vintages/DEV/.waa_cache); only players seen at "
            f"age >= {PEAK_MIN_AGE} count, so the peak is realized; ceiling = the engine's "
            "ceiling_WAA at the observation's dump, the same number the app lists as MAX WAA P "
            "/ WAP; p10-p90 and mean describe the eventual peak; listed_gap = mean of (eventual "
            "peak - ceiling); reach_share = share whose eventual peak >= that dump's ceiling; "
            "gain_p25 / gain_p50 / gain_p75 / gain_mean describe (eventual peak - the player's "
            "now_WAA at the observation's dump), never below 0 because the peak includes that "
            "dump; gain_n = rows with a priced now_WAA (at most n); the app's growth target is "
            "current WAA + gain_p50; mlb_share = share of the cell whose eventual peak "
            f"reached {PEAK_BARS['mlb']:g} WAA (an MLB-level player, a 5th starter or bench "
            "bat; user, 2026-09-24: 'if they will ever be anything in the mlb'), useful_share "
            f"= share that reached {PEAK_BARS['useful']:g} WAA (an average MLB player), "
            f"good_share = share that reached +{PEAK_BARS['good']:g} (a clear regular), bars "
            "in peak_bars (user, 2026-09-24: Make it % is playing time, these say whether the "
            "lookalikes turned out good enough); those three shares are the cell's peak "
            "distribution and ignore the player's own current WAA, so a player already at "
            "the bar could read under 100% (user, 2026-09-24: 'there are a ton of guys who "
            "are already at 0+ WAA that are getting like tagged as less than 100% to reach "
            "it'); the conditional rule fixes that: gain_grid = the cell's gains at "
            f"quantiles {GAIN_GRID_PCTS[0]}, {GAIN_GRID_PCTS[1]}, ..., {GAIN_GRID_PCTS[-1]} "
            f"({len(GAIN_GRID_PCTS)} values, 2 decimals) over every priced row, grid[i] "
            "being the gain at level (i + 1) * 5 percent; by_now = the same grid per "
            f"now-WAA tercile ({NOW_TERCILES} sub-cells cut at the cell's own now terciles, "
            "each with lo / hi = its now range, n, mlb / useful / good = the share of the "
            "sub-cell's eventual peaks at or above each bar, and gain_grid), only when the "
            f"cell has >= {MIN_CELL_NOTE} priced rows, else null; dev_signals picks the "
            "sub-cell holding the player's current WAA (nearest when outside, whole cell "
            f"when the sub-cell has n < {MIN_CELL_NOTE}) and reads each bar's chance as the "
            "share of that grid at or above (bar - his current WAA): 1.0 when he is already "
            "at the bar, else linear between the grid levels; a player whose current sits "
            "outside every sub-cell's range (above the top hi or below the bottom lo) reads "
            "the nearest sub-cell's own mlb / useful / good instead, because the gain rule "
            "would lend him gains measured on players who were never where he is; peak "
            f"uses the grid's observations, peak_pot_only the pot_only ones; cells with n < "
            f"{MIN_CELL_NOTE} are thin"),
        "peak_bars": PEAK_BARS,
        "gain_grid_pcts": list(GAIN_GRID_PCTS),
        "peak_basis": peak_basis or {},
        "peak": walk(peak, PeakCell.stats),
        "peak_pot_only": walk(peak_ponly, PeakCell.stats),
    }


_NUM_LIST = re.compile(r"\[\s+(-?\d[^\[\]{}\"]*?)\s+\]", re.S)
_SUB_CELL = re.compile(r"\{\s+(\"lo\":[^{}]*?\"gain_grid\": (?:null|\[[^\]]*\]))\s+\}", re.S)


def dumps_compact(payload):
    """json.dumps with indent 1, but a list of plain numbers and a by_now
    sub-cell object each stay on one line. The gain grids (19 numbers each,
    thousands of them) would otherwise take one line per number and triple
    the file."""
    text = json.dumps(payload, indent=1)
    text = _NUM_LIST.sub(lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)
    return _SUB_CELL.sub(lambda m: "{" + re.sub(r"\s+", " ", m.group(1)) + "}", text)


# ---------------------------------------------------------------- report
def fmt_cell(c):
    return f"{100 * c['p']:5.1f}% ({c['n']:4d})" if c["n"] else "      -      "


def print_tables(payload, obs, log=print):
    for role, name in (("H", "HITTERS"), ("P", "PITCHERS")):
        gbs = GROWTH_BUCKETS[role]
        log(f"\n{name} age 19: regular% (n) by Pot grade x core-skill steps gained over the last game-year")
        log("   Pot \\ steps " + "  ".join(f"{g:>13s}" for g in gbs))
        for pb in POT_BUCKETS:
            row = payload["grid"][role]["19"][pb]
            log(f"   {pb:8s}    " + "  ".join(fmt_cell(row[g]) for g in gbs))
        pd = payload["pot_dir"][role]["19"]
        log(f"   Pot >= {POT_DIR_MIN}, by Pot grade direction: "
            + "  ".join(f"{d} {fmt_cell(pd[d])}" for d in POT_DIRS))

    def rate(rows):
        return (f"{100 * sum(1 for r in rows if r['reg']) / len(rows):.1f}% (n={len(rows)})"
                if rows else "n=0")

    a19 = [o for o in obs if o["age"] == 19 and o["pot"] >= 50]
    h = [o for o in a19 if o["role"] == "H"]
    p = [o for o in a19 if o["role"] == "P"]
    log("\nRule-of-thumb checks at age 19, Pot 50+ (finding: hitters 60% / 6%, pitchers 58% / 19%)")
    log(f"  hitters, core growth >= 4.5 steps:  {rate([o for o in h if o['grow'] >= 4.5])}")
    log(f"  hitters, core growth <= 2 steps:    {rate([o for o in h if o['grow'] <= 2])}")
    log(f"  pitchers, core growth >= 3 steps:   {rate([o for o in p if o['grow'] >= 3])}")
    log(f"  pitchers, core growth <= 0 steps:   {rate([o for o in p if o['grow'] <= 0])}")
    hl = [o for o in h if o["legacy"] is not None]
    pl = [o for o in p if o["legacy"] is not None]
    log("  same rules on the analysis' own measure (OOTP composite ratings, 6 hitting / 5 pitching):")
    log(f"  hitters, composite steps >= 5:      {rate([o for o in hl if o['legacy'] >= 5])}")
    log(f"  hitters, composite steps <= 2:      {rate([o for o in hl if o['legacy'] <= 2])}")
    log(f"  pitchers, composite steps >= 3:     {rate([o for o in pl if o['legacy'] >= 3])}")
    log(f"  pitchers, composite steps <= 0:     {rate([o for o in pl if o['legacy'] <= 0])}")
    log("  The finding summed 6 composite hitting ratings (with Contact) and 5 pitching ratings "
        "(with Movement) in whole steps. The grid sums 5 hitting and 4 pitching skills as vR/vL "
        "means in half steps, so a given cut lands on a different set of players.")
    print_peak_tables(obs, log=log)


def print_peak_tables(obs, log=print):
    """Age 19, Pot 50+: eventual peak WAA by growth bucket, against the listed ceiling."""
    log(f"\nEventual peak WAA at age 19, Pot 50+ (players seen at age >= {PEAK_MIN_AGE}; "
        "ceiling = the listed peak of that day; gain = peak - now_WAA of that day; "
        f"mlb = share whose peak reached {PEAK_BARS['mlb']:g}, useful = reached "
        f"{PEAK_BARS['useful']:g}, good = reached +{PEAK_BARS['good']:g})")
    log("   role  steps        n   ceil p50   peak p50  peak p25/p75  listed_gap  reach   "
        "gain p50  gain p25/p75    mlb  useful   good")
    for role, name in (("H", "H"), ("P", "P")):
        gbs = GROWTH_BUCKETS[role]
        rows = [o for o in obs if o["age"] == 19 and o["pot"] >= 50 and o["role"] == role
                and o.get("peak") is not None]
        by_gb = {}
        for o in rows:
            c = by_gb.setdefault(growth_bucket(role, o["grow"]), PeakCell())
            c.add(o["peak"], o.get("ceil"), o.get("now"))
        for gb in gbs:
            c = by_gb.get(gb)
            if c is None or not c.vals:
                log(f"   {name}     {gb:9s}    0")
                continue
            s = c.stats()
            ceils = sorted(o["ceil"] for o in rows if growth_bucket(role, o["grow"]) == gb
                           and o.get("ceil") is not None)
            cm = percentile(ceils, 50) if ceils else None
            gain = (f"{s['gain_p50']:8.2f}  {s['gain_p25']:5.2f}/{s['gain_p75']:5.2f}"
                    if s["gain_n"] else "       -      -/-")
            log(f"   {name}     {gb:9s} {s['n']:4d}   {cm if cm is None else round(cm, 2)!s:>8}   "
                f"{s['p50']:8.2f}  {s['p25']:5.2f}/{s['p75']:5.2f}   {s['listed_gap']!s:>9}  "
                f"{s['reach_share']!s:>5}   {gain}  {s['mlb_share']:6.3f} {s['useful_share']:6.3f} "
                f"{s['good_share']:6.3f}")
        top, bot = by_gb.get(gbs[-1]), by_gb.get(gbs[0])
        if top and top.vals and bot and bot.vals:
            ts, bs = top.stats(), bot.stats()
            log(f"   {name}: top growth ({gbs[-1]}) p50 eventual peak {ts['p50']:+.2f} vs bottom "
                f"({gbs[0]}) {bs['p50']:+.2f}; listed_gap {ts['listed_gap']:+.2f} vs "
                f"{bs['listed_gap']:+.2f}")
            if ts["gain_n"] and bs["gain_n"]:
                log(f"   {name}: top growth ({gbs[-1]}) p50 gain {ts['gain_p50']:+.2f} (n {ts['gain_n']}) "
                    f"vs bottom ({gbs[0]}) {bs['gain_p50']:+.2f} (n {bs['gain_n']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description="DEV league odds of becoming an MLB regular")
    ap.add_argument("--write", action="store_true", help="write public/data/dev_odds.json")
    ap.add_argument("--rebuild", action="store_true", help="ignore the playing-time cache")
    ap.add_argument("--dump-root", default=None, help="DEV .lg folder or its dump/ folder")
    args = ap.parse_args(argv)
    log = print
    root = find_dump_root(args.dump_root)
    log(f"dev_odds: dump root {root}")
    pt = load_mlb_pt(root, rebuild=args.rebuild, log=log)
    players, seasons = load_players(log=log)
    cohort, obs, obs_all = measure(players, pt, log=log)
    waa = load_waa(log=log)
    realized, stamped = stamp_peaks(players, cohort, obs, obs_all, waa, log=log)
    peak_basis = {"waa_vintages": len(waa), "waa_years": [min(waa), max(waa)] if waa else None,
                  "min_age": PEAK_MIN_AGE, "players_realized": len(realized),
                  "rows_stamped": stamped, "cache_dir": os.path.relpath(WAA_CACHE_DIR, VIZ)}
    payload = build_payload(cohort, obs, obs_all, seasons, peak_basis)
    c = payload["cohort"]
    log(f"  seasons {seasons[0]}-{seasons[1]}; cohort {c['players']} players "
        f"({c['hitters']} H, {c['pitchers']} P); regular rate H {c['regular_rate']['H']} P {c['regular_rate']['P']}")
    print_tables(payload, obs, log=log)
    if args.write:
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            fh.write(dumps_compact(payload))
        log(f"\nwrote {OUT_PATH}")
    else:
        log("\n(dry run; add --write to write public/data/dev_odds.json)")
    return payload


if __name__ == "__main__":
    main()
