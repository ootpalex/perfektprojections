"""
dataset.py - build the DEV training rows and the TGS / BLM scoring rows.

The DEV league (all-AI OOTP 27, true ratings, one raw dump per game-year) is
the only place where a young player's whole career is known. This script turns
every DEV player-dump with an engine-priced now_WAA (ages 16-40) into one row:
his full card at that dump (features), and what he became after it (targets).
The same feature code then builds rows for the current players of TGS and BLM,
so a model trained on DEV can score them, and a parity check says which
features exist with the same meaning in those leagues.

ONE MODEL SET PER LEAGUE (2026-09-24). TGS and BLM are separate leagues. The
DEV value columns (now / ceiling WAA and every target built from WAA) come
from the engine, so --basis picks the calibration that priced them, and the
scoring rows are built for that same league only:
  --basis BLM   DEV prices = vintages/DEV/.waa_cache files tagged
                '<BLM fingerprint>-BLM'; scoring rows = BLM
  --basis TGS   DEV prices = .dev_cache/ml/waa_TGS files tagged
                '<TGS fingerprint>-TGS' (ml/reprice.py); scoring rows = TGS
Files are chosen by that tag, never as "the newest file per vintage".
User, 2026-09-24: "is there any way you can make a machine learning model to
help with figuring out this dev stuff".

Inputs (read only):
  vintages/DEV/raw_<year>.json.gz     raw dump rows (StatsPlus key names, DOB)
  DEV engine prices (see --basis)     engine now / ceiling WAA per dump
                                      (neutral park)
  .dev_cache/dev_mlb_pt.json.gz       MLB PA / BF per player-season
  ratings_history.db                  pull list + game dates (dev_signals pick)
  ingest/.cache/history/*.json        raw StatsPlus pull of the latest TGS / BLM vintage
  vintages/<LG>/*.csv.gz              the earlier pull (archive columns)
  vintages/<LG>/.waa_cache/*.json     engine WAA of both pulls (growth of WAA),
                                      the league's own current calibration tag
  public/data/<LG>/hitters.json, pitchers.json   now / ceiling / level (dev_signals.app_rows)

Outputs (.dev_cache/ml/data/, pandas pickle; pyarrow is not installed):
  dev_H_<basis>.pkl, dev_P_<basis>.pkl
                                one row per DEV player-dump, per role
  score_<basis>_H.pkl, score_<basis>_P.pkl
                                one row per current player of the basis league
  schema_<basis>.json           every column, targets, folds, counts, parity
  parity_<basis>.json           per-feature coverage and scale, DEV vs the league
  (dev_H.pkl, dev_P.pkl, schema.json, parity.json of the first build, BLM
  priced with both leagues scored, are left as they were)
  _raw_compact.pkl              parse cache of every banked raw dump (rebuilt
                                per dump when the file's size or mtime changes)

Row key: pid + dump_year. dump_year = the season just played; the dump is
dated Jan 1 of dump_year + 1. Role = the role the player held in most of his
dumps (dev_odds rule: P when the dump position is SP, RP or CL).

Targets (NaN where not defined):
  peak            max now_WAA over this dump and every later priced dump
  peak_known      the player is seen at age >= 27 at some dump (realized, the
                  app's rule) or he retired (absent from every later dump
                  while later dumps exist)
  gain            peak - now_WAA
  reach_mlb / reach_useful / reach_good
                  peak >= -1.0 / 0.0 / +1.5, only where peak_known
  regular_future  some MLB season AFTER this dump (season > dump_year) with
                  >= 300 PA or >= 150 BF; 1 as soon as one exists, 0 only
                  where peak_known, else NaN. dev_odds' own outcome (any season
                  of the career, before or after) is kept as regular_ever.
  waa_k, d_k, present_k (k = 1..5)
                  now_WAA at dump_year + k, its change from now, and whether
                  the player is in that dump (NaN beyond the last dump)

Scoring rows: the league's own app values (public/data/<LG>, the league's own
calibration), the earlier pull from dev_signals.choose_clean_pulls (the pull
nearest one game-year back whose pair with the latest pull ratings_db
pair_guard does not flag; growth scaled to one game-year by the span), and a
winter-league player (app Lev WL) reads level R (common.score_level).

Out-of-an-org rule (hidden-card fix, 2026-09-25; common.mask_earlier_card):
when a player was out of an org at the earlier card, every feature built from
that card (per-skill and total growth, d_pot, d_ovr, d_ceiling, d_now) is
unknown and has_prev is 0. Out of an org = DEV: raw Lev at dump_year-1 not in
ORG_LEV (AMA or FA); TGS / BLM: the earlier pull's lev is AMA, FA, INT or
blank. prev_in_org = 1 in an org there, 0 out of one, NaN no earlier card
(DEV: not in the dump a year back; TGS / BLM: missing from the earlier pull,
or no earlier pull). DEV cards are never hidden, but DEV rows get the same
mask so training matches what the leagues can show. The DEV tables keep the
unmasked one-year growth as info columns grow_steps_r_card / has_prev_card:
dev_odds builds its cells from every DEV card (DEV is exempt from the rule
there), and baseline.py rebuilds those cells from these two columns.

CLI:
  PY314 dataset.py --basis BLM             build and print the checks, write nothing
  PY314 dataset.py --basis BLM --write     also write the files above
  PY314 dataset.py --basis TGS --score-only --write
                                           rebuild only score_TGS_H / _P from the
                                           latest pulls (fast; for the pull bat)
  --rebuild                                ignore the raw parse cache
"""
import argparse
import datetime
import glob
import json
import os
import sqlite3
import sys
import time
from collections import Counter

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C                                         # noqa: E402

sys.path.insert(0, C.BT)
import dev_signals as DSIG                                 # noqa: E402  (stdlib only)
import dev_odds as DO                                      # noqa: E402  (stdlib only)
sys.path.insert(0, os.path.join(C.VIZ, "ingest"))
import statsplus as SP                                     # noqa: E402  (stdlib only)
import ratings_db as RDB                                   # noqa: E402  (stdlib only)

REPO = os.path.dirname(C.VIZ)
RAW_CACHE = os.path.join(C.DATA_DIR, "_raw_compact.pkl")
RAW_CACHE_VERSION = 1
PARKED_MAX_AGE = 22            # DEV "MLB" with no MLB PA/BF this season at <= this age reads R
TEST_MIN_CAREERS = 4000        # realized careers per role at ages 17-22 the time-split test side needs
LEAGUES = ("TGS", "BLM")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- DEV raw dumps
def raw_files():
    out = {}
    for p in sorted(os.listdir(C.DEV_VINT)):
        if p.startswith("raw_") and p.endswith(".json.gz"):
            try:
                out[int(p[4:8])] = os.path.join(C.DEV_VINT, p)
            except ValueError:
                pass
    return dict(sorted(out.items()))


def load_dev_raw(rebuild=False, write_cache=True):
    """{year: (ids, num, strs)} for every raw DEV dump, from the parse cache
    when the file's size and mtime still match. write_cache=False never
    rewrites the parse cache (the --history build leaves it as it is)."""
    files = raw_files()
    cache = {}
    if not rebuild and os.path.isfile(RAW_CACHE):
        try:
            c = pd.read_pickle(RAW_CACHE)
            if c.get("v") == RAW_CACHE_VERSION and c.get("raw_num") == C.RAW_NUM:
                cache = c["years"]
        except Exception:                      # noqa: BLE001  a bad cache is rebuilt
            cache = {}
    years, rebuilt = {}, 0
    t0 = time.time()
    for y, p in files.items():
        stamp = (os.path.getsize(p), int(os.path.getmtime(p)))
        c = cache.get(y)
        if c is not None and c["stamp"] == stamp:
            years[y] = c
            continue
        ids, num, strs = C.parse_cards(C.gz_json(p))
        years[y] = {"stamp": stamp, "ids": ids, "num": num, "strs": strs}
        rebuilt += 1
        if rebuilt % 20 == 0:
            log(f"  parsed {rebuilt} dumps [{time.time() - t0:.0f}s]")
    if rebuilt and write_cache:
        os.makedirs(C.DATA_DIR, exist_ok=True)
        pd.to_pickle({"v": RAW_CACHE_VERSION, "raw_num": C.RAW_NUM, "years": years}, RAW_CACHE + ".tmp")
        os.replace(RAW_CACHE + ".tmp", RAW_CACHE)
    log(f"  raw dumps: {len(years)} ({min(years)}-{max(years)}), {rebuilt} parsed, "
        f"{len(years) - rebuilt} from the cache [{time.time() - t0:.0f}s]")
    return years


def stack_dev(years):
    """Concatenate every dump into one long table sorted by (pid, year)."""
    pid = np.concatenate([np.array([int(i) for i in d["ids"]], dtype=np.int64) for d in years.values()])
    year = np.concatenate([np.full(len(d["ids"]), y, dtype=np.int32) for y, d in years.items()])
    num = {k: np.concatenate([d["num"][k] for d in years.values()]) for k in C.RAW_NUM}
    strs = {k: np.concatenate([d["strs"][k] for d in years.values()]) for k in C.RAW_STR if k != "ID"}
    order = np.lexsort((year, pid))
    pid, year = pid[order], year[order]
    num = {k: v[order] for k, v in num.items()}
    strs = {k: v[order] for k, v in strs.items()}
    return pid, year, num, strs


def lookup(keys_sorted, want):
    """Index of each wanted key in the sorted key array, -1 when absent."""
    j = np.searchsorted(keys_sorted, want)
    j = np.clip(j, 0, len(keys_sorted) - 1)
    return np.where(keys_sorted[j] == want, j, -1)


def load_dev_waa(key_sorted, basis):
    """now, ceil, kind arrays aligned to the long table (NaN / None when the
    dump's prices on this basis do not cover the player)."""
    n = len(key_sorted)
    now = np.full(n, np.nan, dtype=np.float32)
    ceil = np.full(n, np.nan, dtype=np.float32)
    kind = np.full(n, None, dtype=object)
    files = C.basis_waa_files(basis)
    for y, p in files.items():
        d = C.read_waa_file(p)
        if not d:
            continue
        pids = np.array([int(k) for k in d], dtype=np.int64)
        vals = list(d.values())
        idx = lookup(key_sorted, pids * 10000 + y)
        ok = idx >= 0
        now[idx[ok]] = np.array([v[0] for v in vals], dtype=np.float32)[ok]
        ceil[idx[ok]] = np.array([v[1] for v in vals], dtype=np.float32)[ok]
        kind[idx[ok]] = np.array([v[2] for v in vals], dtype=object)[ok]
    log(f"  waa {basis} basis ({C.waa_tag(basis)} in {os.path.relpath(C.WAA_BASIS_DIR[basis], C.BT)}): "
        f"{len(files)} dumps ({min(files)}-{max(files)}); {int((~np.isnan(now)).sum())} of {n} player-dumps priced")
    return now, ceil, kind, files


def load_pt():
    """(pa, bf) dicts keyed (pid, season) and the set of seasons covered."""
    c = C.gz_json(C.PT_CACHE)
    pa, bf = {}, {}
    for y, t in c["years"].items():
        yi = int(y)
        for p, v in t["pa"].items():
            pa[(int(p), yi)] = v
        for p, v in t["bf"].items():
            bf[(int(p), yi)] = v
    seasons = sorted(int(y) for y in c["years"])
    log(f"  playing time: seasons {seasons[0]}-{seasons[-1]} ({len(seasons)}), "
        f"{len(pa)} batter-seasons, {len(bf)} pitcher-seasons at MLB")
    return pa, bf, set(seasons)


# ---------------------------------------------------------------- DEV table
def dev_history(role, rows, key, year, num, in_org, level, age, now, ceil, first_year_row, dev_first_year):
    """History inputs of the DEV rows `rows` (indexes into the long table) as
    {column: array}: the full-record inputs, their __w<d> window variants
    (d = 0..3) and sim_depth. Slot j = the dump j seasons back (common
    history block)."""
    t0 = time.time()
    stems = {name: stem for name, stem, _p in C.SPLIT_SKILLS[role]}
    long = {"age": age.astype(np.float32),
            "rank": np.array([C.LEVEL_RANK.get(x, np.nan) if x is not None else np.nan for x in level],
                             dtype=np.float32),
            "in_org": in_org.astype(np.float32),
            "pot": num["Pot"], "ovr": num["Ovr"], "now": now, "ceil": ceil}
    core = None
    for s in C.CORE[role]:
        v = C.split_internal(num[stems[s] + "_R"], num[stems[s] + "_L"]).astype(np.float32)
        long[f"i_{s}"] = v
        core = v.astype(np.float64) if core is None else core + v
    long["core"] = core.astype(np.float32)
    kr = key[rows]

    def slot(j):
        idx = lookup(key, kr - j)
        ok = idx >= 0
        ii = np.maximum(idx, 0)
        s = {k: np.where(ok, v[ii], np.nan).astype(np.float32) for k, v in long.items()}
        s["span"] = float(j)
        s["present"] = ok
        s["usable"] = ok & (s["in_org"] == 1)
        return s

    cur = {k: v[rows] for k, v in long.items()}
    J = int((year[rows] - first_year_row[rows]).max())
    path = [(lambda j=j: slot(j)) for j in range(1, J + 1)]
    kslots = {k: (lambda k=k: slot(k)) for k in C.HIST_K}
    ad = np.minimum(year[rows].astype(np.float64) - dev_first_year, C.ARCHIVE_DEPTH_CAP)
    out = dict(C.history_inputs(role, cur, path, kslots, None, ad, True))
    for w in C.HIST_WINDOWS:
        wv = C.history_inputs(role, cur, path[:w], kslots, w, ad, False)
        for k, v in wv.items():
            out[f"{k}__w{w}"] = v
    out["sim_depth"] = C.sim_depths(key[rows] // 10000, year[rows])
    log(f"  {role} history inputs: {len(C.hist_feature_names(role))} inputs + "
        f"{len(C.hist_window_columns(role))} window columns, record reaches back up to {J} dumps "
        f"[{time.time() - t0:.0f}s]")
    return out


def build_dev(basis, rebuild=False, history=False):
    t0 = time.time()
    years = load_dev_raw(rebuild, write_cache=not history)
    final_year = max(years)
    # dev_odds' cohort window (dev_odds.measure): first seen from COHORT_START to
    # the last banked dump minus COHORT_MARGIN, so its end moves with the dumps
    cohort_years = (DO.COHORT_START, max(DO.COHORT_START, int(final_year) - DO.COHORT_MARGIN))
    pid, year, num, strs = stack_dev(years)
    n = len(pid)
    key = pid * 10000 + year
    log(f"  long table: {n} player-dumps, {len(np.unique(pid))} players [{time.time() - t0:.0f}s]")

    now, ceil, kind, waa_files = load_dev_waa(key, basis)
    pa_d, bf_d, pt_seasons = load_pt()

    # player groups
    starts = np.flatnonzero(np.r_[True, pid[1:] != pid[:-1]])
    ends = np.r_[starts[1:], n]
    gsize = ends - starts
    gid = np.repeat(np.arange(len(starts)), gsize)
    age = num["Age"].astype(np.float32)
    pos = strs["Pos"]
    lev = strs["Lev"]
    is_p = np.isin(pos.astype(str), list(C.PITCHER_POS))
    in_org = np.isin(lev.astype(str), list(C.ORG_LEV))
    first_year = year[starts]
    first_age = age[starts]
    last_year = year[ends - 1]
    max_age = np.maximum.reduceat(np.nan_to_num(age, nan=-1), starts)
    n_p = np.add.reduceat(is_p.astype(np.int32), starts)
    ever_org = np.add.reduceat(in_org.astype(np.int32), starts) > 0
    # dev_odds: Counter(role).most_common(1); a tie goes to the role seen first
    first_is_p = is_p[starts]
    role_p = (n_p * 2 > gsize) | ((n_p * 2 == gsize) & first_is_p)
    role_row = np.where(role_p[gid], "P", "H")

    # playing time per row (season = dump_year) and per player
    upid = pid[starts]
    pa_row = np.array([pa_d.get((int(p), int(y)), 0) for p, y in zip(pid, year)], dtype=np.float32)
    bf_row = np.array([bf_d.get((int(p), int(y)), 0) for p, y in zip(pid, year)], dtype=np.float32)
    pt_known_row = np.isin(year, list(pt_seasons))
    last_reg = {}
    any_reg = set()
    for (p, y), v in pa_d.items():
        if v >= C.REGULAR_PA:
            any_reg.add(p)
            last_reg[p] = max(last_reg.get(p, -1), y)
    for (p, y), v in bf_d.items():
        if v >= C.REGULAR_BF:
            any_reg.add(p)
            last_reg[p] = max(last_reg.get(p, -1), y)
    last_reg_row = np.array([last_reg.get(int(p), -1) for p in upid], dtype=np.int32)[gid]
    reg_ever_row = np.isin(pid, np.fromiter(any_reg, dtype=np.int64))

    # level: collapsed Lev; parked international kids (MLB label, no MLB PA/BF
    # in the season just played, age <= PARKED_MAX_AGE) read R
    level = np.array([C.collapse_level(x) for x in lev], dtype=object)
    parked = ((lev == "MLB") & pt_known_row & (pa_row == 0) & (bf_row == 0)
              & (age <= PARKED_MAX_AGE))
    level[parked] = "R"
    mlb_lab = lev == "MLB"
    log(f"  level: {int(mlb_lab.sum())} rows labelled MLB; {int(parked.sum())} read R (no MLB PA/BF that "
        f"season, age <= {PARKED_MAX_AGE}); MLB-labelled rows with no MLB time by age: "
        + ", ".join(f"{a}: {int((mlb_lab & (age == a) & pt_known_row & (pa_row == 0) & (bf_row == 0)).sum())}"
                    f"/{int((mlb_lab & (age == a) & pt_known_row).sum())}" for a in (17, 19, 21, 23, 25, 28, 32)))

    # age from the birth date. Day-resolution numpy dates, not pandas
    # timestamps: pandas stores dates in nanoseconds and cannot hold a date
    # after 2262-04-11, and the DEV save has simmed past that (2026-09-25).
    # DOB is 'YYYY-MM-DD' in the dumps; anything else reads NaN.
    def _day(s):
        s = "" if s is None else str(s).strip()[:10]
        try:
            return np.datetime64(s, "D") if len(s) == 10 else np.datetime64("NaT")
        except ValueError:
            return np.datetime64("NaT")
    dob = np.array([_day(s) for s in strs["DOB"]], dtype="datetime64[D]")
    ref = (np.asarray(year, dtype=np.int64) + 1 - 1970).astype("datetime64[Y]").astype("datetime64[D]")
    days = (ref - dob).astype("timedelta64[D]").astype(np.float64)
    days[np.isnat(dob)] = np.nan
    age_frac = (days / 365.25).astype(np.float32)

    # previous dumps
    i_prev = lookup(key, key - 1)
    i_prev2 = lookup(key, key - 2)
    prev_now = np.where(i_prev >= 0, now[np.maximum(i_prev, 0)], np.nan).astype(np.float32)
    prev_ceil = np.where(i_prev >= 0, ceil[np.maximum(i_prev, 0)], np.nan).astype(np.float32)
    # in an org at the dump one / two years back: 1 / 0, NaN when not in that
    # dump (the out-of-an-org rule, common.mask_earlier_card)
    prev_in_org = np.where(i_prev >= 0, in_org[np.maximum(i_prev, 0)], np.nan).astype(np.float32)
    prev2_in_org = np.where(i_prev2 >= 0, in_org[np.maximum(i_prev2, 0)], np.nan).astype(np.float32)
    prev_lev = np.where(i_prev >= 0, lev[np.maximum(i_prev, 0)], None)

    # ---- targets
    priced = ~np.isnan(now)
    rev = np.arange(n)[::-1]
    s = pd.Series(np.where(priced, now, -np.inf)[rev])
    peak = s.groupby(gid[rev]).cummax().to_numpy()[::-1].astype(np.float64)
    peak = np.where(np.isfinite(peak), peak, np.nan).astype(np.float32)
    realized = (max_age >= C.PEAK_MIN_AGE)[gid]
    retired = (last_year < final_year)[gid]
    peak_known = realized | retired
    censored = ~peak_known
    peak_t = np.where(priced & peak_known, peak, np.nan).astype(np.float32)
    gain_t = (peak_t - now).astype(np.float32)
    reach = {}
    for name, bar in C.PEAK_BARS.items():
        reach[name] = np.where(np.isnan(peak_t), np.nan, (peak_t >= bar).astype(np.float32)).astype(np.float32)
    reg_future = np.where(last_reg_row > year, 1.0, np.where(peak_known, 0.0, np.nan)).astype(np.float32)
    waa_k, pres_k = {}, {}
    for k in C.HORIZONS:
        j = lookup(key, key + k)
        w = np.where(j >= 0, now[np.maximum(j, 0)], np.nan).astype(np.float32)
        waa_k[k] = w
        pres_k[k] = np.where(year + k > final_year, np.nan, (j >= 0).astype(np.float32)).astype(np.float32)

    # ---- features per role, rows kept: priced now, age 16-40
    keep = priced & (age >= C.AGE_MIN) & (age <= C.AGE_MAX)
    tables = {}
    for role in C.ROLES:
        rows = np.flatnonzero(keep & (role_row == role))
        cur = {k: v[rows] for k, v in num.items()}
        prev = C.take(num, i_prev[rows])
        prev2 = C.take(num, i_prev2[rows])
        ctx = {"age": age[rows], "age_frac": age_frac[rows], "level": level[rows],
               "in_org": in_org[rows].astype(np.float32), "pos": pos[rows], "bats": strs["Bats"][rows],
               "throws": strs["Throws"][rows], "now": now[rows], "ceil": ceil[rows],
               "prev_now": prev_now[rows], "prev_ceil": prev_ceil[rows],
               "pot_scale": C.dev_pot_scale(year[rows]),
               "prev_pot_scale": np.where(i_prev[rows] >= 0, C.dev_pot_scale(year[rows] - 1), np.nan).astype(np.float32)}
        # built once without the out-of-an-org mask, so the real earlier-card
        # growth can be kept for the cell method; then the mask is applied
        feats = C.build_features(role, cur, prev, prev2, 1.0, 2.0, ctx)
        card_grow_r = feats["grow_steps_r"].copy()
        card_has_prev = feats["has_prev"].copy()
        feats["prev_in_org"] = prev_in_org[rows]
        C.mask_earlier_card(feats, role, prev_in_org[rows], prev2_in_org[rows])
        a = age[rows]
        young = (a >= 16) & (a <= 26)
        out = prev_in_org[rows] == 0
        known_lost = out & (card_has_prev == 1)
        log(f"  {role} out-of-an-org rule, ages 16-26: {int(young.sum())} rows; masked (out of an org a year "
            f"back) {int((young & out).sum())}, of which growth was known {int((young & known_lost).sum())}; "
            f"no earlier dump {int((young & np.isnan(prev_in_org[rows])).sum())}; level a year back of the "
            f"masked rows: {dict(Counter(prev_lev[rows][young & out].astype(str).tolist()).most_common())}; "
            f"masked rows in an org now {int((young & out & (in_org[rows] == 1)).sum())}")
        df = pd.DataFrame({"pid": pid[rows], "dump_year": year[rows].astype(np.int16)})
        df = pd.concat([df, C.to_frame(feats)], axis=1)
        g = gid[rows]
        extra = {
            "grow_steps_r_card": card_grow_r, "has_prev_card": card_has_prev,
            "now_kind": pd.Categorical(kind[rows], categories=["H", "P"]),
            "lev_raw": pd.Categorical(lev[rows].astype(str)),
            "mlb_pa": pa_row[rows], "mlb_bf": bf_row[rows],
            "peak": peak_t[rows], "peak_known": peak_known[rows].astype(np.int8),
            "gain": gain_t[rows],
            "reach_mlb": reach["mlb"][rows], "reach_useful": reach["useful"][rows],
            "reach_good": reach["good"][rows],
            "regular_future": reg_future[rows],
            "regular_ever": reg_ever_row[rows].astype(np.int8),
        }
        for k in C.HORIZONS:
            extra[f"waa_{k}"] = waa_k[k][rows]
            extra[f"d_{k}"] = (waa_k[k][rows] - now[rows]).astype(np.float32)
            extra[f"present_{k}"] = pres_k[k][rows]
        extra.update({
            "realized": realized[rows].astype(np.int8), "retired": retired[rows].astype(np.int8),
            "censored": censored[rows].astype(np.int8),
            "cohort_first20": ((first_age[g] <= 20) & ever_org[g]).astype(np.int8),
            "cohort_dev_odds": ((first_age[g] <= 20) & ever_org[g] & (first_year[g] >= cohort_years[0])
                                & (first_year[g] <= cohort_years[1])).astype(np.int8),
            "left_censored": (first_year[g] == min(years)).astype(np.int8),
            "first_seen_year": first_year[g].astype(np.int16),
            "first_seen_age": first_age[g].astype(np.float32),
            "last_seen_year": last_year[g].astype(np.int16),
            "max_age_seen": max_age[g].astype(np.float32),
            "fold": np.array([C.fold_of(p) for p in pid[rows]], dtype=np.int8),
        })
        df = pd.concat([df, pd.DataFrame(extra)], axis=1)
        if history:
            first_year_row = first_year[gid]
            hist = dev_history(role, rows, key, year, num, in_org, level, age, now, ceil,
                               first_year_row, int(min(years)))
            df = pd.concat([df, pd.DataFrame(hist)], axis=1)
        tables[role] = df
        log(f"  {role}: {len(df)} rows, {df['pid'].nunique()} players [{time.time() - t0:.0f}s]")
    meta = {"final_year": int(final_year), "first_year": int(min(years)), "dumps": len(years),
            "waa_dumps": len(waa_files), "basis": basis, "waa_tag": C.waa_tag(basis),
            "waa_dir": os.path.relpath(C.WAA_BASIS_DIR[basis], C.VIZ).replace(os.sep, "/"),
            "pt_seasons": [min(pt_seasons), max(pt_seasons)],
            "parked_rows": int(parked.sum()), "history": bool(history)}
    return tables, meta


def pick_time_split(tables):
    """Largest first-seen-year cutoff whose test side (players first seen after
    it) still has TEST_MIN_CAREERS REALIZED careers per role (seen at 27+,
    with a row at ages 17-22, not left-censored).

    Why realized and not just finished: the most recent debut years can only
    finish by retiring young, so a cutoff that only counts finished careers
    (2158 on the current dumps) leaves a test side of about 78 percent early
    washouts with a lower useful rate than the train side. Returns (cutoff,
    {role: {finished, realized, useful share test / train}})."""
    per_role = {}
    for role, df in tables.items():
        m = (df["age"] >= 17) & (df["age"] <= 22) & (df["left_censored"] == 0)
        per_role[role] = df.loc[m].groupby("pid").agg(
            fy=("first_seen_year", "first"), known=("peak_known", "first"),
            real=("realized", "first"), useful=("reach_useful", "max"))
    lo = int(min(d["first_seen_year"].min() for d in tables.values()))
    hi = int(max(d["first_seen_year"].max() for d in tables.values()))
    best = None
    for c in range(lo, hi + 1):
        real = {r: int(((pl["fy"] > c) & (pl["real"] == 1)).sum()) for r, pl in per_role.items()}
        if all(v >= TEST_MIN_CAREERS for v in real.values()):
            best = c
    if best is None:
        raise SystemExit("no time-split cutoff leaves enough realized careers on the test side")
    counts = {}
    for r, pl in per_role.items():
        te, tr = pl[(pl["fy"] > best) & (pl["known"] == 1)], pl[(pl["fy"] <= best) & (pl["known"] == 1)]
        counts[r] = {"test_finished": int(len(te)), "test_realized": int((te["real"] == 1).sum()),
                     "test_censored": int(((pl["fy"] > best) & (pl["known"] == 0)).sum()),
                     "train_finished": int(len(tr)),
                     "useful_share_test": round(float(te["useful"].mean()), 4),
                     "useful_share_train": round(float(tr["useful"].mean()), 4)}
    for role, df in tables.items():
        df["time_split"] = pd.Categorical(np.where(df["first_seen_year"] <= best, "train", "test"),
                                          categories=["train", "test"])
    return best, counts


# ---------------------------------------------------------------- TGS / BLM scoring rows
def repo_path(p):
    return os.path.join(REPO, p.replace("\\", "/"))


def app_rows_full(league):
    """{pid: app row} from public/data/<LG>/hitters.json and pitchers.json."""
    out = {}
    for fn in ("hitters.json", "pitchers.json"):
        path = os.path.join(C.APP_DATA, league, fn)
        with open(path, encoding="utf-8") as fh:
            for r in json.load(fh):
                if isinstance(r, dict) and r.get("ID") is not None:
                    out[str(r["ID"])] = r
    return out


def untranslate(row):
    """App row (sheet names) -> raw StatsPlus key names, for the fallback when
    the latest pull's raw file is gone."""
    out = dict(row)
    for raw, sheet in SP.STATSPLUS_TO_SHEET.items():
        if sheet in row:
            out[raw] = row[sheet]
    return out


def archive_cards(league, pull_id):
    """(ids, card dict, file name, lev) of an archive vintage: the core splits,
    Pot, Ovr (raw key names) and each player's lev string. A blank lev is
    rebuilt from the pull's raw file (dev_signals.fill_blank_levs); '' when
    neither source knows it."""
    import glob as _g
    hits = _g.glob(os.path.join(C.LEAGUE_VINT, league, f"*_p{pull_id}.csv.gz"))
    if not hits:
        return None, None, None, None
    df = pd.read_csv(hits[0], dtype={"player_id": str, "lev": str})
    ids = df["player_id"].astype(str).tolist()
    num = {k: np.full(len(df), np.nan, dtype=np.float32) for k in C.RAW_NUM}
    for col, raw in C.ARCHIVE_TO_RAW.items():
        if col in df.columns:
            num[raw] = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float32)
    lev = (df["lev"].fillna("").astype(str).str.strip().to_numpy(dtype=object) if "lev" in df.columns
           else np.full(len(df), "", dtype=object))
    if (lev == "").any():
        conn = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
        try:
            filled, _n = DSIG.fill_blank_levs(conn, pull_id, league, ids, list(lev))
        finally:
            conn.close()
        lev = np.array(filled, dtype=object)
    return ids, num, os.path.basename(hits[0]), lev


def archive_identity(league, pull_id):
    """{player_id: {"name", "age"}} of an archive vintage, for the reused-ID
    test (dev_signals.same_person). Empty when the vintage is missing."""
    import glob as _g
    hits = _g.glob(os.path.join(C.LEAGUE_VINT, league, f"*_p{pull_id}.csv.gz"))
    if not hits:
        return {}
    df = pd.read_csv(hits[0], dtype={"player_id": str, "name": str}, usecols=["player_id", "name", "age"])
    return {str(p): {"name": n, "age": a} for p, n, a in zip(df["player_id"], df["name"], df["age"])}


def prev_org_flag(lev):
    """Out-of-an-org rule for a TGS / BLM earlier pull: 0.0 when the lev is
    AMA, FA, INT, '-' (a foreign-league row) or blank (out of an org, the card
    may be hidden), else 1.0. Rule: dev_signals.lev_out_of_org."""
    return 0.0 if DSIG.lev_out_of_org(lev) else 1.0


def league_waa(league, pull_id, fp):
    """({pid: (now, ceil, kind)}, fingerprint, file) of one pull's .waa_cache
    file with exactly this calibration fingerprint (the league's own current
    one; picked by tag, not by age). Empty when that pull has no such file."""
    import glob as _g
    d = os.path.join(C.LEAGUE_VINT, league, ".waa_cache")
    files = _g.glob(os.path.join(d, f"*_p{pull_id}.csv.gz.{fp}.json"))
    if not files:
        return {}, None, None
    return C.read_waa_file(files[0]), fp, os.path.basename(files[0])


def pull_levels(league, conn, pull_id, ids, lev, org):
    """Level strings of one archived pull. A blank vintage lev (TGS pull 29 /
    BLM pull 9 on, before the 2026-09-25 backfill) is rebuilt from the raw
    StatsPlus pull (source_files) with the shared rule
    (dev_signals.fill_blank_levs -> ratings_db.derive_lev, the app's own
    statsplus._lev_for). Returns (lev strings, how) with None where neither
    source knows."""
    lev = np.array([str(x).strip() if x is not None and x == x else "" for x in lev], dtype=object)
    blank = lev == ""
    if not blank.any():
        return lev, "vintage lev"
    filled, n = DSIG.fill_blank_levs(conn, pull_id, league, ids, list(lev))
    out = np.array(filled, dtype=object)
    if n:
        for i in np.flatnonzero(out == ""):
            out[i] = None                   # not in the raw pull: unknown
        return out, "raw pull League / LgLvl (statsplus._lev_for)"
    out = lev.copy()
    # no raw pull: org '0' (or blank) = out of an org; any other org = in an
    # org at an unknown level
    for i in np.flatnonzero(blank):
        o = "" if org[i] is None else str(org[i]).strip()
        out[i] = "FA" if o in ("", "0", "-", "nan") else None
    return out, "org column only (level unknown)"


def level_codes(levs, org_known_in):
    """(rank, in_org) float32 arrays of level strings: rank 1..5 in an org, 0
    out of one (FA, AMA, INT), NaN unknown; a None level with org_known_in
    counts as in an org at an unknown level."""
    rank = np.full(len(levs), np.nan, dtype=np.float32)
    ino = np.zeros(len(levs), dtype=np.float32)
    for i, x in enumerate(levs):
        lv = C.score_level(x) if x is not None else None
        if lv is None:
            if x is None and org_known_in[i]:
                ino[i] = 1.0
            continue
        rank[i] = C.LEVEL_RANK[lv]
        ino[i] = 0.0 if lv == "none" else 1.0
    return rank, ino


def league_archive(league, conn, pulls, gdates, choice, fp):
    """Every archived pull of the league that the history inputs may read.

    Pulls kept: dated like the choice (in-game dates when the latest pull has
    one), before the latest pull, clean against it (ratings_db.pair_guard via
    dev_signals.pair_reading), and at least HIST_MIN_SPAN game-years back (E
    candidates), plus the k = 1 pick whatever its span. Returns (records
    oldest-last by span, k picks {k: record}, archive_depth, note)."""
    import ratings_db as _RDB
    to_id, to_date = choice["to_id"], choice["to_date"]
    if choice["dates"] == "in-game":
        dated = [(p, gdates[p]) for p, _rd, _ts in pulls if p in gdates and p != to_id]
    else:
        # an asof pull's real_date is an in-game date: never mix it with real dates
        dated = [(p, DSIG.parse_date(rd)) for p, rd, _ts in pulls if p != to_id and not DSIG.is_asof(pulls, p)]
    dated = [(p, d, (to_date - d).days / DSIG.YEAR_DAYS) for p, d in dated if d is not None and d < to_date]
    floor = _RDB.rated_floor(_RDB._scale_of(conn, league))
    to_map = _RDB.load_pull_map(conn, to_id)
    clean, flagged = [], []
    for p, d, span in dated:
        if span < C.HIST_MIN_SPAN and p != choice["from_id"]:
            continue
        reasons = DSIG.pair_reading(conn, league, p, to_map, floor)
        (flagged if reasons else clean).append((p, d, span))
    # archive depth: the oldest clean pull of any span (short ones are all clean
    # when a longer one is, the guard reads each pair against the latest pull)
    depth = max([s for _p, _d, s in clean], default=0.0)
    recs = []
    for p, d, span in sorted(clean, key=lambda x: (x[2], x[0])):
        hits = glob.glob(os.path.join(C.LEAGUE_VINT, league, f"*_p{p}.csv.gz"))
        if not hits:
            continue
        cols = ["player_id", "name", "age", "org", "lev"] + list(C.ARCHIVE_TO_RAW)
        df = pd.read_csv(hits[0], dtype={"player_id": str, "name": str, "lev": str, "org": str},
                         usecols=lambda c: c in cols)
        ids = df["player_id"].astype(str).tolist()
        card = {}
        for col, raw in C.ARCHIVE_TO_RAW.items():
            card[raw] = (pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float32) if col in df.columns
                         else np.full(len(df), np.nan, dtype=np.float32))
        org = df["org"].to_numpy(dtype=object) if "org" in df.columns else np.full(len(df), None, dtype=object)
        levs, how = pull_levels(league, conn, p, ids, df["lev"].to_numpy(dtype=object) if "lev" in df.columns
                                else np.full(len(df), "", dtype=object), org)
        org_in = np.array([o is not None and str(o).strip() not in ("", "0", "-", "nan") for o in org])
        rank, ino = level_codes(levs, org_in)
        w, _fp, wfile = league_waa(league, p, fp)
        recs.append({"pull": p, "date": str(d), "span": float(span), "idx": {x: i for i, x in enumerate(ids)},
                     "ident": {x: {"name": nm, "age": a} for x, nm, a in zip(ids, df["name"], df["age"])},
                     "age": pd.to_numeric(df["age"], errors="coerce").to_numpy(dtype=np.float32),
                     "card": card, "rank": rank, "in_org": ino, "lev_how": how,
                     "waa": w, "waa_file": wfile})
    by_id = {r["pull"]: r for r in recs}
    picks = {}
    if choice["from_id"] is not None and choice["from_id"] in by_id:
        picks[1] = by_id[choice["from_id"]]
    for k in C.HIST_K[1:]:
        if (k - 1) not in picks:
            break
        lo = max(k - 0.5, picks[k - 1]["span"] + C.HIST_MIN_SPAN)
        cands = [r for r in recs if lo <= r["span"] <= k + 0.5]
        if not cands:
            break
        picks[k] = min(cands, key=lambda r: (abs(r["span"] - k), r["pull"]))
    note = {"pulls_read": [{"pull": r["pull"], "date": r["date"], "span": round(r["span"], 3),
                            "lev": r["lev_how"], "waa": r["waa_file"]} for r in recs],
            "pulls_flagged": [{"pull": p, "date": str(d), "span": round(s, 3)} for p, d, s in flagged],
            "k_picks": {str(k): {"pull": r["pull"], "date": r["date"], "span": round(r["span"], 3)}
                        for k, r in picks.items()},
            "archive_depth": round(float(depth), 3),
            "rule": "E = his earliest pull 0.5+ game-years back that is clean against the latest pull, with "
                    "him in an org there and the same person under the ID; k picks: k = 1 the "
                    "choose_clean_pulls pick, k = 2, 3 the clean pull nearest k game-years back within "
                    "k +- 0.5 and 0.5+ past the k-1 pick"}
    return recs, picks, float(depth), note


def league_slot(rec, rid, to_ident, role):
    """One archived pull as a history slot for the players rid of one role."""
    n = len(rid)
    j = np.array([rec["idx"].get(p, -1) for p in rid])
    same = np.array([jj >= 0 and DSIG.same_person(to_ident.get(p), rec["ident"].get(p), rec["span"])
                     for p, jj in zip(rid, j)], dtype=bool)
    ok = (j >= 0) & same
    jj = np.maximum(j, 0)

    def pick(a):
        return np.where(ok, a[jj], np.nan).astype(np.float32)

    card = rec["card"]
    s = {"span": rec["span"], "present": ok, "age": pick(rec["age"]), "rank": pick(rec["rank"]),
         "in_org": pick(rec["in_org"]), "pot": pick(card["Pot"]), "ovr": pick(card["Ovr"])}
    stems = {name: stem for name, stem, _p in C.SPLIT_SKILLS[role]}
    core = np.zeros(n)
    for sk in C.CORE[role]:
        v = pick(C.split_internal(card[stems[sk] + "_R"], card[stems[sk] + "_L"]).astype(np.float32))
        s[f"i_{sk}"] = v
        core = core + v
    s["core"] = core.astype(np.float32)
    w = rec["waa"]
    s["now"] = np.where(ok, np.array([w.get(p, (np.nan,) * 3)[0] for p in rid], dtype=np.float32), np.nan)
    s["ceil"] = np.where(ok, np.array([w.get(p, (np.nan,) * 3)[1] for p in rid], dtype=np.float32), np.nan)
    s["usable"] = ok & (s["in_org"] == 1)
    s["reused"] = (j >= 0) & ~same
    return s


def league_history(role, rid, cur, recs, picks, depth, to_ident):
    """History inputs of the TGS / BLM players rid of one role, and the pull
    id of each one's E (-1 = none)."""
    n = len(rid)
    slots = [(r, league_slot(r, rid, to_ident, role)) for r in recs]
    # E slot: his oldest usable pull at least HIST_MIN_SPAN back
    keys = ["age", "rank", "in_org", "pot", "ovr", "now", "ceil", "core"] + [f"i_{s}" for s in C.CORE[role]]
    e = {k: np.full(n, np.nan, dtype=np.float32) for k in keys}
    e_span = np.full(n, np.nan)
    e_pull = np.full(n, -1, dtype=np.int32)
    for r, s in slots:
        cand = s["usable"] & (r["span"] >= C.HIST_MIN_SPAN)
        for k in keys:
            e[k] = np.where(cand, s[k], e[k])
        e_span = np.where(cand, r["span"], e_span)
        e_pull = np.where(cand, r["pull"], e_pull)
    has = e_pull >= 0
    eslot = dict(e, span=e_span, present=has, usable=has)
    by_pull = {r["pull"]: s for r, s in slots}
    kslots = {k: by_pull[r["pull"]] for k, r in picks.items()}
    path = [kslots[k] for k in sorted(kslots)] + [eslot]
    out = C.history_inputs(role, cur, path, kslots, None, min(depth, C.ARCHIVE_DEPTH_CAP), True)
    reused = {r["pull"]: int(s["reused"].sum()) for r, s in slots if s["reused"].any()}
    return out, e_pull, reused


def records_report(df, league, role):
    """Players 16-26 in an org by seasons recorded (0, 1, 2, 3+; rounded
    game-years) and by recent inputs known (h1 / h2 / h3)."""
    m = (df["age"] >= 16) & (df["age"] <= 26) & (df["in_org"] == 1)
    sr = df.loc[m, "seasons_recorded"].to_numpy(dtype=np.float64)
    b = np.where(sr < C.HIST_MIN_SPAN, 0, C.whole_seasons(np.where(sr < C.HIST_MIN_SPAN, 1, sr)))
    rep = {"n_16_26_in_org": int(m.sum()),
           "seasons_recorded": {"0": int((b == 0).sum()), "1": int((b == 1).sum()),
                                "2": int((b == 2).sum()), "3+": int((b >= 3).sum())},
           "recent_known": {f"h{k}": int(df.loc[m, f"h{k}_grow_int"].notna().sum()) for k in C.HIST_K},
           "seasons_recorded_mean": round(float(np.mean(sr)), 3) if len(sr) else None}
    log(f"  {league} {role} history, players 16-26 in an org (n {rep['n_16_26_in_org']}): seasons recorded "
        f"{rep['seasons_recorded']}; recent inputs known {rep['recent_known']}")
    return rep


def build_league(league, history=False):
    """Scoring rows of one league (per role) and a note dict.

    Value columns are the league's own app values (its own calibration), the
    basis its own model trains on. Earlier pull: dev_signals.choose_clean_pulls
    (nearest one game-year back, pair with the latest pull not flagged by
    ratings_db.pair_guard), the same pull for hitters and pitchers.
    history=True adds the history inputs from every archived pull
    (league_archive / league_history) and the info column rec_start_pull."""
    conn = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
    try:
        pulls = DSIG.league_pulls(conn, league)
        gdates = DSIG.game_dates(league, pulls)
        plain = DSIG.choose_pulls(pulls, gdates)
        choice = DSIG.choose_clean_pulls(conn, league, pulls, gdates)
        src = conn.execute("SELECT source, source_files FROM pulls WHERE pull_id=?",
                           (choice["to_id"],)).fetchone()
    finally:
        conn.close()
    note = {"to_pull": choice["to_id"], "to_date": str(choice["to_date"]),
            "from_pull": choice["from_id"],
            "from_date": str(choice["from_date"]) if choice["from_date"] else None,
            "span_game_years": round(choice["span"], 3) if choice["span"] else None,
            "pull_rule": "dev_signals.choose_clean_pulls: the pull nearest one game-year back whose pair with "
                         "the latest pull ratings_db.pair_guard does not flag; growth / span",
            "unguarded_from_pull": plain["from_id"],
            "dates": choice["dates"], "choose_notes": choice["notes"]}
    sides = {s: (choice["from_id"], choice["from_date"], choice["span"]) for s in RDB.SIDES}
    note["from_by_role"] = {("P" if s == "pit" else "H"): {"pull": v[0], "date": str(v[1]) if v[1] else None,
                                                           "span_game_years": round(v[2], 3) if v[2] else None}
                            for s, v in sides.items()}
    app = app_rows_full(league)
    levels, peaks, currents = DSIG.app_rows(league)
    fp = C.calib_fingerprint(league)

    raw_rows = None
    for p in json.loads(src[1] or "[]"):
        rp = repo_path(p)
        if rp.endswith(".json") and os.path.isfile(rp):
            with open(rp, encoding="utf-8") as fh:
                raw_rows = json.load(fh)
            note["to_source"] = os.path.relpath(rp, REPO)
            break
    if raw_rows is None:
        raw_rows = [untranslate(r) for r in app.values()]
        note["to_source"] = "app hitters.json / pitchers.json, translated back to raw names"
    raw_rows = [r for r in raw_rows if str(r.get("ID")) in app]
    ids, num, strs = C.parse_cards(raw_rows)

    # rating agreement between the raw pull and the app rows the engine priced
    agree = mism = 0
    for i, pid in enumerate(ids):
        a = app[pid]
        for rk, sk in (("BABIP_R", "BA vR"), ("Stf_R", "STU vR"), ("Pot", "Pot")):
            va, vr = C.to_num(a.get(sk)), num[rk][i]
            if np.isnan(va) or np.isnan(vr):
                continue
            agree += int(va == vr)
            mism += int(va != vr)
    note["raw_vs_app_ratings"] = {"agree": agree, "differ": mism}

    # engine WAA of the latest pull from the league's own .waa_cache, current fingerprint
    w_to, _fp, f_to = league_waa(league, choice["to_id"], fp)
    note["waa_cache"] = {"fingerprint": fp, "to": f_to}
    if f_to is None:
        note["waa_cache"]["missing"] = (f"no .waa_cache file of pull {choice['to_id']} with fingerprint {fp}: "
                                        "d_now / d_ceiling are NaN")

    n = len(ids)
    pos = np.array([str(app[p].get("POS") or strs["Pos"][i] or "") for i, p in enumerate(ids)], dtype=object)
    role = np.array([C.role_of(x) for x in pos], dtype=object)
    lev_app = np.array([levels.get(p) for p in ids], dtype=object)
    level = np.array([C.score_level(x) for x in lev_app], dtype=object)
    note["wl_read_as_R"] = int(sum(1 for x in lev_app if x is not None and str(x).strip() == "WL"))
    in_org = np.array([1.0 if (x is not None and x not in C.NO_ORG_LEVELS) else 0.0 for x in lev_app],
                      dtype=np.float32)
    age = np.array([C.to_num(app[p].get("Age")) for p in ids], dtype=np.float32)
    now = np.array([currents[r].get(p, np.nan) for p, r in zip(ids, role)], dtype=np.float32)
    ceil = np.array([peaks[r].get(p, np.nan) for p, r in zip(ids, role)], dtype=np.float32)
    c_now_to = np.array([w_to.get(p, (np.nan,) * 3)[0] for p in ids], dtype=np.float32)
    c_ceil_to = np.array([w_to.get(p, (np.nan,) * 3)[1] for p in ids], dtype=np.float32)
    ok = ~np.isnan(now) & ~np.isnan(c_now_to)
    note["app_now_vs_cache_now"] = {
        "n": int(ok.sum()),
        "mean_app_minus_cache": round(float(np.mean(now[ok] - c_now_to[ok])), 3) if ok.any() else None,
        "corr": round(float(np.corrcoef(now[ok], c_now_to[ok])[0, 1]), 4) if ok.sum() > 2 else None,
        "why": "the app's now must match the neutral-park engine the DEV cache used; a gap here would mean "
               "a park or calibration layer in the app numbers"}

    out = {}
    note["from_source"] = {}
    if history:
        th = time.time()
        hconn = sqlite3.connect(f"file:{C.DB_PATH}?mode=ro", uri=True)
        try:
            h_recs, h_picks, h_depth, note["history"] = league_archive(league, hconn, pulls, gdates, choice, fp)
        finally:
            hconn.close()
        log(f"  {league} history archive: {len(h_recs)} pulls read, k picks "
            f"{ {k: (r['pull'], round(r['span'], 2)) for k, r in h_picks.items()} }, archive depth "
            f"{h_depth:.2f} game-years [{time.time() - th:.0f}s]")
    # reused player IDs (2026-09-25): TGS gives an old ID to a new player, so
    # the earlier card under this ID can be someone else's; such a player
    # counts as not in the earlier pull (dev_signals.same_person)
    to_ident = archive_identity(league, choice["to_id"])
    from_ident = archive_identity(league, choice["from_id"]) if choice["from_id"] is not None else {}
    note["reused_id"] = {}
    for r in C.ROLES:
        side = "pit" if r == "P" else "hit"
        from_id, _fd, span = sides[side]
        rows = np.flatnonzero(role == r)
        rid = [ids[i] for i in rows]
        pv, c_now_fr, c_ceil_fr = None, np.full(len(rows), np.nan, np.float32), np.full(len(rows), np.nan, np.float32)
        # out-of-an-org rule: 1 in an org at the earlier pull, 0 out of one
        # (AMA, FA, INT, blank), NaN missing from it or no earlier pull
        prev_in_org = np.full(len(rows), np.nan, np.float32)
        if from_id is not None:
            prev_ids, prev_num, prev_file, prev_lev = archive_cards(league, from_id)
            if prev_ids is not None:
                pmap = {p: i for i, p in enumerate(prev_ids)}
                pidx = np.array([pmap.get(p, -1) for p in rid])
                reused = np.array([j >= 0 and not DSIG.same_person(to_ident.get(p), from_ident.get(p), span)
                                   for p, j in zip(rid, pidx)], dtype=bool)
                pidx = np.where(reused, -1, pidx)
                note["reused_id"][r] = int(reused.sum())
                pv = C.take(prev_num, pidx)
                prev_in_org = np.array([prev_org_flag(prev_lev[j]) if j >= 0 else np.nan for j in pidx],
                                       dtype=np.float32)
                note["from_source"][r] = f"vintages/{league}/{prev_file}"
            w_from, _fp, f_from = league_waa(league, from_id, fp)
            note["waa_cache"]["from_" + r] = f_from
            c_now_fr = np.array([w_from.get(p, (np.nan,) * 3)[0] for p in rid], dtype=np.float32)
            c_ceil_fr = np.array([w_from.get(p, (np.nan,) * 3)[1] for p in rid], dtype=np.float32)
            if prev_ids is not None and reused.any():
                c_now_fr[reused] = np.nan              # someone else's value a year ago
                c_ceil_fr[reused] = np.nan
        cur = {k: v[rows] for k, v in num.items()}
        ctx = {"age": age[rows], "level": level[rows], "in_org": in_org[rows], "pos": pos[rows],
               "bats": strs["Bats"][rows], "throws": strs["Throws"][rows], "now": now[rows], "ceil": ceil[rows],
               "prev_in_org": prev_in_org,
               "pot_scale": np.full(len(rows), C.LEAGUE_OVR_POT_SCALE.get(league, 0.0), dtype=np.float32)}
        feats = C.build_features(r, cur, pv, None, span if span else np.nan, 2.0, ctx)
        # WAA growth: both ends from the league cache (one engine, neutral park), like DEV
        feats["d_ceiling"] = (c_ceil_to[rows] - c_ceil_fr).astype(np.float32)
        feats["d_now"] = (c_now_to[rows] - c_now_fr).astype(np.float32)
        # the out-of-an-org rule again, now that d_ceiling / d_now are set
        C.mask_earlier_card(feats, r, prev_in_org)
        e_pull = None
        if history:
            stems = {nm: st for nm, st, _p in C.SPLIT_SKILLS[r]}
            hcur = {"age": age[rows], "in_org": in_org[rows],
                    "rank": np.array([C.LEVEL_RANK.get(x, np.nan) if x is not None else np.nan
                                      for x in level[rows]], dtype=np.float32),
                    "pot": cur["Pot"], "ovr": cur["Ovr"], "now": c_now_to[rows], "ceil": c_ceil_to[rows]}
            hcore = np.zeros(len(rows))
            for sk in C.CORE[r]:
                hcur[f"i_{sk}"] = C.split_internal(cur[stems[sk] + "_R"], cur[stems[sk] + "_L"]).astype(np.float32)
                hcore = hcore + hcur[f"i_{sk}"]
            hcur["core"] = hcore.astype(np.float32)
            hfe, e_pull, h_reused = league_history(r, rid, hcur, h_recs, h_picks, h_depth, to_ident)
            feats.update(hfe)
            note["history"].setdefault("reused_id_by_pull", {})[r] = h_reused
        young = (age[rows] >= 16) & (age[rows] <= 26)
        note.setdefault("prev_org_rule", {})[r] = {
            "ages_16_26": int(young.sum()),
            "masked_out_of_org_a_year_back": int((young & (prev_in_org == 0)).sum()),
            "in_org_a_year_back": int((young & (prev_in_org == 1)).sum()),
            "no_earlier_card": int((young & np.isnan(prev_in_org)).sum())}
        df = pd.DataFrame({"pid": np.array([int(x) for x in rid], dtype=np.int64),
                           "name": [str(app[x].get("Name") or "") for x in rid]})
        df = pd.concat([df, C.to_frame(feats)], axis=1)
        df["lev_app"] = lev_app[rows]
        df["cache_now_waa"] = c_now_to[rows]
        df["cache_ceiling_waa"] = c_ceil_to[rows]
        df["from_pull"] = -1 if from_id is None else int(from_id)
        df["span_game_years"] = np.float32(span) if span else np.float32(np.nan)
        df["league"] = league
        if history:
            df["rec_start_pull"] = e_pull
            note["history"].setdefault("records", {})[r] = records_report(df, league, r)
        out[r] = df
    note["players"] = {r: int(len(d)) for r, d in out.items()}
    return out, note


# ---------------------------------------------------------------- parity
MANUAL_DROP = {
    "age_frac": "TGS / BLM data carry no birth date, so the fractional age cannot be built there",
    "grow2_steps": "the TGS / BLM archives span under two game-years (TGS 2043-11 to 2045-07, "
                   "BLM 2057-07 to 2058-10, and BLM's usable span starts after its 2057-12-31 scale "
                   "event), so two-year growth is never known there",
    "grow2_int": "same as grow2_steps",
}
COVER_MIN = 0.5        # a league share non-null below this, where DEV is at >= 0.9, drops the feature
SMD_FLAG = 1.0         # |league mean - DEV mean| / DEV sd above this is printed for review


HIST_PARITY_NOTE = ("history input: kept usable whatever its league coverage today. The TGS / BLM archives are "
                    "short, so the deeper inputs fill in as the archive grows; the DEV side is read AFTER the "
                    "archive-depth mask (common.apply_archive_depth), the rows the models train on")


def parity(dev, score, history=False):
    """Per role and feature: share non-null and mean / sd in DEV rows 16-26 in
    an org vs TGS and BLM players 16-26 in an org; decides usable_for_scoring.
    history=True adds the history inputs: their DEV side is read after the
    archive-depth mask, and the coverage rule does not drop them."""
    out = {}
    for role in C.ROLES:
        d = dev[role]
        dm = d[(d["age"] >= 16) & (d["age"] <= 26) & (d["in_org"] == 1)]
        hist_names = set(C.hist_feature_names(role)) if history else set()
        dmm = C.apply_archive_depth(dm, role) if history else dm
        lg = {L: s[role][(s[role]["age"] >= 16) & (s[role]["age"] <= 26) & (s[role]["in_org"] == 1)]
              for L, s in score.items()}
        rows = {}
        for spec in C.feature_spec(role, history=history):
            name = spec["name"]
            is_hist = name in hist_names
            e = {"dev_n": int(len(dm))}

            def stats(frame):
                col = frame[name]
                if isinstance(col.dtype, pd.CategoricalDtype):
                    nn = col.notna()
                    vc = col[nn].value_counts(normalize=True)
                    return float(nn.mean()) if len(col) else None, None, None, \
                        {str(k): round(float(v), 3) for k, v in vc.items() if v > 0}
                v = col.to_numpy(dtype=np.float64)
                nn = ~np.isnan(v)
                if not nn.any():
                    return float(nn.mean()) if len(v) else None, None, None, None
                return float(nn.mean()), float(np.mean(v[nn])), float(np.std(v[nn])), None

            e["dev_share"], e["dev_mean"], e["dev_sd"], e["dev_cats"] = stats(dmm if is_hist else dm)
            reasons = []
            for L, f in lg.items():
                sh, mu, sd, cats = stats(f)
                e[f"{L}_n"] = int(len(f))
                e[f"{L}_share"], e[f"{L}_mean"], e[f"{L}_sd"], e[f"{L}_cats"] = sh, mu, sd, cats
                if e["dev_share"] is not None and e["dev_share"] >= 0.9 and (sh is None or sh < COVER_MIN):
                    reasons.append(f"{L} non-null share {0 if sh is None else sh:.2f} vs DEV {e['dev_share']:.2f}")
                if mu is not None and e["dev_mean"] is not None and e["dev_sd"]:
                    smd = (mu - e["dev_mean"]) / e["dev_sd"]
                    e[f"{L}_smd"] = round(float(smd), 3)
            if name in MANUAL_DROP:
                reasons = [MANUAL_DROP[name]]
            if is_hist:
                reasons = []
                e["note"] = HIST_PARITY_NOTE
            e["usable_for_scoring"] = not reasons
            e["drop_reason"] = "; ".join(reasons) if reasons else None
            for k, v in list(e.items()):
                if isinstance(v, float):
                    e[k] = round(v, 4)
            rows[name] = e
        out[role] = rows
    return out


def print_parity(par, only=None):
    for role, rows in par.items():
        if only is not None:
            rows = {k: v for k, v in rows.items() if k in only[role]}
            if not rows:
                continue
        log(f"\nPARITY {role}: share non-null (mean) in DEV 16-26 in org vs the league 16-26 in org")
        any_row = next(iter(rows.values()))
        lgs = [L for L in LEAGUES if f"{L}_n" in any_row]
        log(f"  n: DEV {any_row['dev_n']}, " + ", ".join(f"{L} {any_row.get(L + '_n')}" for L in lgs))
        for name, e in rows.items():
            def fm(sh, mu):
                if sh is None:
                    return "      -       "
                return f"{sh:5.2f} ({mu:7.2f})" if mu is not None else f"{sh:5.2f} (   cat )"
            flag = "" if e["usable_for_scoring"] else f"  DROP: {e['drop_reason']}"
            smd = [f"{L} smd {e[f'{L}_smd']:+.2f}" for L in lgs
                   if e.get(f"{L}_smd") is not None and abs(e[f"{L}_smd"]) > SMD_FLAG]
            log(f"  {name:16s} DEV {fm(e['dev_share'], e['dev_mean'])}  "
                + "  ".join(f"{L} {fm(e[L + '_share'], e[L + '_mean'])}" for L in lgs)
                + f"{'  ' + ', '.join(smd) if smd else ''}{flag}")


# ---------------------------------------------------------------- sanity
def sanity(tables, meta, cutoff, counts):
    log("\nROW COUNTS")
    for role, df in tables.items():
        log(f"  {role}: {len(df)} rows, {df['pid'].nunique()} players; peak_known rows {int(df['peak_known'].sum())}; "
            f"finished players {df.loc[df['peak_known'] == 1, 'pid'].nunique()}; "
            f"time split train {int((df['time_split'] == 'train').sum())} / test {int((df['time_split'] == 'test').sum())} rows")
        a = df[(df["age"] >= 16) & (df["age"] <= 26)]
        log(f"    ages 16-26: {len(a)} rows; in org {int((a['in_org'] == 1).sum())}; "
            f"cohort_first20 {int((a['cohort_first20'] == 1).sum())}")
    log(f"  time split: cutoff first_seen_year <= {cutoff} is train; careers with a 17-22 row: {counts}")
    for role, df in tables.items():
        log(f"\n{role}: by age (n rows, peak_known share, mean peak / gain, reach mlb/useful/good, "
            "regular_future, mean d_1, present_1)")
        g = df.groupby("age")
        for a, x in g:
            if a < 16 or a > 32:
                continue
            k = x["peak_known"] == 1
            log(f"  {int(a):2d}  n {len(x):7d}  known {k.mean():.3f}  peak {x['peak'].mean():+.2f}  "
                f"gain {x['gain'].mean():+.2f}  reach {x['reach_mlb'].mean():.3f}/{x['reach_useful'].mean():.3f}/"
                f"{x['reach_good'].mean():.3f}  regF {x['regular_future'].mean():.3f}  "
                f"d1 {x['d_1'].mean():+.3f}  pres1 {x['present_1'].mean():.3f}")


def hand_check(tables, basis):
    """Print three DEV players' raw rows across dumps next to their table rows:
    a star, a washout, and one still active at the last dump."""
    df = tables["H"]
    young = df[(df["age"] == 19) & (df["in_org"] == 1)]
    star = young[(young["peak_known"] == 1)].sort_values("peak", ascending=False)["pid"].iloc[0]
    wash = young[(young["retired"] == 1) & (young["peak"] < -1.5) & (young["pot"] >= 50)]
    wash = wash["pid"].iloc[0] if len(wash) else young[young["retired"] == 1]["pid"].iloc[0]
    act = df[(df["censored"] == 1) & (df["age"] == 22)]["pid"].iloc[0]
    years = raw_files()
    wanted = {int(star): "star", int(wash): "washout", int(act): "still active"}
    raw = {p: {} for p in wanted}
    for y, p in years.items():
        for r in C.gz_json(p):
            i = int(r["ID"])
            if i in raw:
                raw[i][y] = r
    waa = {}
    for y, p in C.basis_waa_files(basis).items():
        d = C.read_waa_file(p)
        for i in raw:
            if str(i) in d:
                waa[(i, y)] = d[str(i)]
    for pid, label in wanted.items():
        rows = df[df["pid"] == pid].set_index("dump_year")
        log(f"\nHAND CHECK {label}: pid {pid}")
        log("  year age lev  | raw BABIP_R/L Gap_R/L Pot | cache now ceil | table age level babip_mean "
            "g_babip_steps pot now peak gain reach_u regF waa_1 present_1")
        for y in sorted(raw[pid]):
            r = raw[pid][y]
            w = waa.get((pid, y))
            t = rows.loc[y] if y in rows.index else None
            tt = (f"{t['age']:.0f} {t['level']} {t['babip_mean']:.1f} {t['g_babip_steps']:+.1f} {t['pot']:.0f} "
                  f"{t['now_waa']:+.2f} {t['peak']:+.2f} {t['gain']:+.2f} {t['reach_useful']:.0f} "
                  f"{t['regular_future']:.0f} {t['waa_1']:+.2f} {t['present_1']:.0f}") if t is not None else "(no row)"
            log(f"  {y} {r.get('Age'):>3} {r.get('Lev'):4s} | {r.get('BABIP_R')}/{r.get('BABIP_L')} "
                f"{r.get('Gap_R')}/{r.get('Gap_L')} {r.get('Pot')} | "
                f"{(w[0] if w else float('nan')):+.2f} {(w[1] if w else float('nan')):+.2f} | {tt}")
    return wanted


# ---------------------------------------------------------------- schema
TARGET_DEFS = {
    "peak": "max now_WAA over this dump and every later dump the engine priced; NaN unless peak_known",
    "peak_known": "1 when the player is seen at age >= 27 at some dump (realized, the app's rule) or retired "
                  "(absent from every later dump while later dumps exist); constant per player",
    "gain": "peak - now_WAA (never below 0); NaN unless peak_known",
    "reach_mlb": "peak >= -1.0 (dev_odds PEAK_BARS mlb); NaN unless peak_known",
    "reach_useful": "peak >= 0.0; NaN unless peak_known",
    "reach_good": "peak >= +1.5; NaN unless peak_known",
    "regular_future": "1 when some MLB season s > dump_year (a season played after this Jan-1 dump) has >= 300 PA "
                      "or >= 150 BF (dev_mlb_pt, level_id 1); 0 when none and peak_known; else NaN. Differs from "
                      "dev_odds' outcome, which counts any season of the career, including seasons already played "
                      "(kept as regular_ever). Seasons start at 2026: the cache has no 2025 season.",
    "regular_ever": "dev_odds' outcome: some season of the career (2026 on) with >= 300 PA or >= 150 BF; not "
                    "censoring-aware, reference only",
    "waa_k": "now_WAA at dump_year + k (k = 1..5); NaN when retired, not priced, or beyond the last dump",
    "d_k": "waa_k - now_WAA",
    "present_k": "1 when the player is in the raw dump dump_year + k, 0 when absent (retired), NaN beyond the last dump",
}
FLAG_DEFS = {
    "realized": "seen at age >= 27 at some dump (dev_odds / app definition)",
    "retired": "absent from every dump after his last one while later dumps exist (players never come back)",
    "censored": "still active at the last dump and never seen at 27+: peak and outcomes unknown",
    "cohort_first20": "first seen at age <= 20 and ever in an org (dev_odds cohort without its year window)",
    "cohort_dev_odds": "cohort_first20 and first seen from 2025 to the last banked dump minus 23 (dev_odds "
                       "COHORT_YEARS exactly; the end moves with the last banked year)",
    "left_censored": "first seen in the first dump (2025): his earlier years are unknown",
    "first_seen_year": "dump_year of his first dump",
    "first_seen_age": "age at his first dump",
    "last_seen_year": "dump_year of his last dump",
    "max_age_seen": "highest age in any dump",
}
INFO_DEFS = {
    "pid": "player id (int64); key with dump_year",
    "dump_year": "season just played; the dump is dated Jan 1 of dump_year + 1",
    "now_kind": "engine record the cache priced at this dump (H or P); differs from the role for a few position changers",
    "lev_raw": "raw dump Lev before the collapse / parked fix",
    "mlb_pa": "MLB PA in season dump_year (0 when none or unknown)",
    "mlb_bf": "MLB BF in season dump_year",
    "fold": "0..4, md5 of the pid string mod 5; every dump of a player in one fold",
    "grow_steps_r_card": "grow_steps_r BEFORE the out-of-an-org mask (the real DEV card a year back). Only the cell "
                         "method reads it (baseline.py, as dev_odds builds its cells from every DEV card); never a "
                         "model feature",
    "has_prev_card": "has_prev BEFORE the out-of-an-org mask; read with grow_steps_r_card by baseline.py only",
    "time_split": "train when first_seen_year <= the cutoff, else test",
    "sim_depth": "simulated archive depth of the row (history tables only): -1 = full record (about half the "
                 "rows), else 0, 1, 2 or 3 seasons of archive (one eighth each); md5 of 'pid/dump_year' "
                 "(common.sim_depth). common.apply_archive_depth() applies it; never a model feature",
    "rec_start_pull": "scoring rows (history tables only): pull id of E, the start of his record; -1 = none",
}
WINDOW_DESC = ("window variant of a record input: the same input recomputed over an archive that starts d seasons "
               "back (d = the __w<d> suffix). Read only by common.apply_archive_depth for rows with sim_depth d; "
               "never a model feature")


def dtype_name(s):
    if isinstance(s.dtype, pd.CategoricalDtype):
        return "category[" + ",".join(str(c) for c in s.cat.categories) + "]"
    return str(s.dtype)


def build_schema(tables, meta, cutoff, counts, par, notes, wanted, history=False):
    basis = meta["basis"]
    sfx = C.HIST_SUFFIX if history else ""
    roles = {}
    for role, df in tables.items():
        spec = {s["name"]: s for s in C.feature_spec(role, basis, history=history)}
        wcols = set(C.hist_window_columns(role)) if history else set()
        cols = []
        for c in df.columns:
            e = {"name": c, "dtype": dtype_name(df[c])}
            if c in wcols:
                e.update({"kind": "window", "desc": WINDOW_DESC})
            elif c in spec:
                p = par[role].get(c, {})
                e.update({"kind": "feature", "family": spec[c]["family"], "desc": spec[c]["desc"],
                          "dev_source": spec[c]["dev_source"], "lg_source": spec[c]["lg_source"],
                          "usable_for_scoring": bool(p.get("usable_for_scoring", False)),
                          "drop_reason": p.get("drop_reason")})
            elif c in TARGET_DEFS or c.rstrip("12345").rstrip("_") in ("waa", "d", "present"):
                base = c if c in TARGET_DEFS else c.rstrip("12345").rstrip("_") + "_k"
                e.update({"kind": "target", "desc": TARGET_DEFS.get(base)})
            elif c in FLAG_DEFS:
                e.update({"kind": "flag", "desc": FLAG_DEFS[c]})
            else:
                e.update({"kind": "key" if c in ("pid", "dump_year") else "info", "desc": INFO_DEFS.get(c)})
            cols.append(e)
        age = df["age"]
        roles[role] = {
            "file": f"{C.basis_name('dev_' + role, basis)}{sfx}.pkl",
            "rows": int(len(df)), "players": int(df["pid"].nunique()),
            "rows_by_age": {str(int(a)): int(n) for a, n in age.value_counts().sort_index().items()},
            "finished_rows": int(df["peak_known"].sum()),
            "finished_players": int(df.loc[df["peak_known"] == 1, "pid"].nunique()),
            "time_split_rows": {"train": int((df["time_split"] == "train").sum()),
                                "test": int((df["time_split"] == "test").sum())},
            "usable_features": [e["name"] for e in cols if e.get("kind") == "feature" and e["usable_for_scoring"]],
            "dropped_features": {e["name"]: e["drop_reason"] for e in cols
                                 if e.get("kind") == "feature" and not e["usable_for_scoring"]},
            "columns": cols,
        }
    hist_block = None
    if history:
        hist_block = {
            "switch": "dataset.py --history wrote these tables; common.use_history(True) makes dev_table, "
                      "score_table and load_schema read them",
            "inputs": {r: C.hist_feature_names(r) for r in C.ROLES},
            "record_inputs_windowed": {r: C.hist_record_names(r) for r in C.ROLES},
            "window_columns": "<record input>__w<d>, d = 0..3 (DEV tables only)",
            "mask": "common.apply_archive_depth(df, role) on DEV training rows BEFORE fitting: rows with "
                    "sim_depth d take the __w<d> record values, lose the recent inputs deeper than d "
                    "(h<k>_* for k > d; h_grow_int_prev / h_accel need d >= 2) and, at d = 0, the one-year "
                    "growth features (prev_in_org unknown, has_prev 0); grow2_* unknown for d < 2. Scoring rows "
                    "are never masked: their record is what the league archive holds",
            "min_span_game_years": C.HIST_MIN_SPAN, "archive_depth_cap": C.ARCHIVE_DEPTH_CAP,
            "sim_depth_rule": "md5('pid/dump_year'): u < 0.5 full record, else d = min(3, int((u - 0.5) * 8))",
        }
    schema = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "format": "pandas pickle (.pkl), one DataFrame per file; load with pandas.read_pickle or "
                  "common.load_table. pyarrow is not installed under Python 3.14, so no parquet. Features are "
                  "float32, categorical features are pandas categories with fixed category lists "
                  "(common.CATEGORICAL), flags int8, targets float32 with NaN where undefined.",
        "key": ["pid", "dump_year"],
        "basis": basis,
        "basis_rule": "one model set per league: DEV priced with this league's engine calibration, scored on "
                      "this league's own app values (TGS and BLM never mixed)",
        "files": {"dev": [f"{C.basis_name('dev_' + r, basis)}{sfx}.pkl" for r in C.ROLES],
                  "score": [f"score_{basis}_{r}{sfx}.pkl" for r in C.ROLES],
                  "parity": f"parity_{basis}{sfx}.json"},
        "source": {"league": "DEV", "dumps": meta["dumps"], "years": [meta["first_year"], meta["final_year"]],
                   "waa": f"{meta['waa_dir']}/*.csv.gz.{meta['waa_tag']}.json ({basis} engine calibration, "
                          "neutral park), picked by that tag",
                   "playing_time_seasons": meta["pt_seasons"]},
        "row_rule": f"one row per DEV player-dump with a priced now_WAA at ages {C.AGE_MIN}-{C.AGE_MAX}; "
                    "role = the role held in most of the player's dumps (dev_odds; a tie goes to the role of "
                    "his first dump); features use only that dump and earlier dumps",
        "families": ["bat", "bat_pot", "growth", "glove", "pitch", "pitch_pot", "value", "context"],
        "targets": TARGET_DEFS,
        "flags": FLAG_DEFS,
        "info": INFO_DEFS,
        "folds": {"rule": "fold = int(md5(str(pid)).hexdigest()[:8], 16) % 5 (common.fold_of); every dump of a "
                          "player lands in one fold",
                  "time_split": f"train = players first seen in dump years <= {cutoff}, test = first seen after "
                                f"{cutoff}; the cutoff is the latest year that leaves >= {TEST_MIN_CAREERS} "
                                f"realized careers (seen at 27+, a row at ages 17-22, not left-censored) per role "
                                f"on the test side. A cutoff counting only finished careers would sit at 2158, "
                                f"where the test side is mostly early washouts (the recent debuts can finish "
                                f"only by retiring young) and its useful share falls below the train side's",
                  "time_cutoff": cutoff, "test_careers_17_22": counts},
        "level_rule": f"DEV Lev collapsed to none/R/A/AA/AAA/MLB; an MLB label with no MLB PA and no MLB BF in "
                      f"the season just played at age <= {PARKED_MAX_AGE} reads R (parked international kids; "
                      f"{meta['parked_rows']} rows); in_org uses the raw Lev (dev_odds ORG_LEV). The 2025 dump has "
                      "no playing time, so its MLB labels are kept.",
        "left_out": {
            "personality": "not included. The DEV letters (WrkEthic, Int, Lead, Loy, Greed) are terciles that "
                           "dump_vintages cut from the raw 1-200 values; the TGS / BLM letters are OOTP's own "
                           "labels with other cut points (TGS work ethic N 68%, H 24%, L 8% vs DEV one third "
                           "each), so the scales do not map",
            "prone": "DEV carries raw injury numbers, StatsPlus a text label; no known mapping",
            "arm_slot, bunt, GB/FB hitter type, draft fields": "not asked for; left out",
        },
        "scoring": notes,
        "hand_check_pids": {str(k): v for k, v in wanted.items()},
        "roles": roles,
    }
    if hist_block is not None:
        schema["history"] = hist_block
    return schema


# ---------------------------------------------------------------- main
def history_sanity(tables):
    """Print the DEV history inputs by age (full record) and the share of
    rows per sim_depth, so a wrong join shows up at once."""
    for role, df in tables.items():
        log(f"\n{role} history (full record, DEV rows): by age n, seasons_recorded mean, rec_grow_int_ps mean, "
            f"h1/h2/h3 known share, rec_now_below_best mean, rec_seasons_at_level mean")
        for a, x in df.groupby("age"):
            if a < 16 or a > 34 or a % 2:
                continue
            log(f"  {int(a):2d}  n {len(x):7d}  sr {x['seasons_recorded'].mean():5.2f}  "
                f"gps {x['rec_grow_int_ps'].mean():+7.2f}  h1 {x['h1_grow_int'].notna().mean():.3f}  "
                f"h2 {x['h2_grow_int'].notna().mean():.3f}  h3 {x['h3_grow_int'].notna().mean():.3f}  "
                f"below_best {x['rec_now_below_best'].mean():+.2f}  at_level {x['rec_seasons_at_level'].mean():.2f}")
        vc = df["sim_depth"].value_counts(normalize=True).sort_index()
        log(f"  sim_depth shares: " + ", ".join(f"{int(k)}: {v:.3f}" for k, v in vc.items()))


def out_names(basis, history):
    sfx = C.HIST_SUFFIX if history else ""
    return {"dev": {r: C.table_path(C.basis_name(f"dev_{r}", basis) + sfx) for r in C.ROLES},
            "score": {r: C.table_path(f"score_{basis}_{r}{sfx}") for r in C.ROLES},
            "parity": os.path.join(C.DATA_DIR, f"parity_{basis}{sfx}.json"),
            "schema": os.path.join(C.DATA_DIR, f"schema_{basis}{sfx}.json")}


def score_only(basis, write, history=False):
    """Rebuild only score_<basis>_H / _P (with --history: the _hist tables)
    from the latest pulls. The schema's "scoring" note of this basis is
    updated when the schema exists. basis may also be an exported league
    (common.extra_leagues): its rows are score_<league>_H / _P and its note
    goes to score_note_<league>.json (its basis' schema is not touched)."""
    t0 = time.time()
    if basis not in C.BASES:
        return score_extra(basis, write)
    names = out_names(basis, history)
    log(f"dataset: {basis} scoring rows only{' (history inputs)' if history else ''}")
    d, note = build_league(basis, history)
    log(f"  {basis}: {note}")
    if not write:
        log(f"\n(dry run; add --write to write {C.DATA_DIR}) [{time.time() - t0:.0f}s]")
        return
    for role, df in d.items():
        C.save_table(df, names["score"][role])
    sp = names["schema"]
    if os.path.isfile(sp):
        with open(sp, encoding="utf-8") as fh:
            schema = json.load(fh)
        schema["scoring"] = {basis: note}
        schema["scoring_rebuilt"] = datetime.datetime.now().isoformat(timespec="seconds")
        with open(sp + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(schema, fh, indent=1, default=str)
        os.replace(sp + ".tmp", sp)
    log(f"\nwrote {', '.join(os.path.basename(p) for p in names['score'].values())} in {C.DATA_DIR} "
        f"[{time.time() - t0:.0f}s]")


def score_extra(league, write):
    """Scoring rows of an exported league (common.extra_leagues), scored with
    its basis' models: score_<league>_H / _P and score_note_<league>.json."""
    t0 = time.time()
    basis = C.league_basis(league)
    log(f"dataset: {league} scoring rows only (exported league, {basis} models)")
    d, note = build_league(league, False)
    note["basis"] = basis
    log(f"  {league}: {note}")
    if not write:
        log(f"\n(dry run; add --write to write {C.DATA_DIR}) [{time.time() - t0:.0f}s]")
        return
    for role, df in d.items():
        C.save_table(df, C.table_path(f"score_{league}_{role}"))
    p = os.path.join(C.DATA_DIR, f"score_note_{league}.json")
    with open(p + ".tmp", "w", encoding="utf-8") as fh:
        json.dump({"scoring": {league: note}, "basis": basis,
                   "scoring_rebuilt": datetime.datetime.now().isoformat(timespec="seconds")}, fh, indent=1, default=str)
    os.replace(p + ".tmp", p)
    log(f"\nwrote score_{league}_H / _P and {os.path.basename(p)} in {C.DATA_DIR} [{time.time() - t0:.0f}s]")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the DEV ML row tables and the scoring rows of one league basis.")
    ap.add_argument("--basis", required=True, choices=C.scoring_leagues(),
                    help="engine calibration of the DEV prices, and the league scored (one model set per league)")
    ap.add_argument("--write", action="store_true", help="write the tables and schema_<basis>.json")
    ap.add_argument("--score-only", action="store_true",
                    help="rebuild only score_<basis>_H / _P from the latest pulls (fast)")
    ap.add_argument("--history", action="store_true",
                    help="add the history inputs (the player's own earlier seasons) and write the tables under "
                         "_hist names (dev_H_<basis>_hist.pkl, score_<basis>_H_hist.pkl, schema_<basis>_hist.json); "
                         "the live tables are not touched")
    ap.add_argument("--rebuild", action="store_true", help="ignore the raw parse cache")
    ap.add_argument("--no-hand-check", action="store_true", help="skip the three-player hand check")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    basis = args.basis
    history = args.history
    if basis not in C.BASES and not args.score_only:
        raise SystemExit(f"{basis} is an exported league: only --score-only applies (it has no DEV tables of its own)")
    if args.score_only:
        score_only(basis, args.write, history)
        return
    names = out_names(basis, history)
    t0 = time.time()
    log(f"dataset: DEV rows, {basis} basis{' (history inputs)' if history else ''}")
    tables, meta = build_dev(basis, args.rebuild, history)
    cutoff, counts = pick_time_split(tables)
    log(f"dataset: {basis} scoring rows")
    score, notes = {}, {}
    score[basis], notes[basis] = build_league(basis, history)
    log(f"  {basis}: {notes[basis]}")
    par = parity(tables, score, history)
    print_parity(par)
    sanity(tables, meta, cutoff, counts)
    if history:
        history_sanity(tables)
    wanted = {} if args.no_hand_check else hand_check(tables, basis)
    schema = build_schema(tables, meta, cutoff, counts, par, notes, wanted, history)
    if args.write:
        os.makedirs(C.DATA_DIR, exist_ok=True)
        for role, df in tables.items():
            C.save_table(df, names["dev"][role])
        for L, d in score.items():
            for role, df in d.items():
                C.save_table(df, names["score"][role])
        with open(names["parity"], "w", encoding="utf-8") as fh:
            json.dump(par, fh, indent=1)
        with open(names["schema"], "w", encoding="utf-8") as fh:
            json.dump(schema, fh, indent=1, default=str)
        log(f"\nwrote {C.DATA_DIR} [{time.time() - t0:.0f}s]")
    else:
        log(f"\n(dry run; add --write to write {C.DATA_DIR}) [{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
