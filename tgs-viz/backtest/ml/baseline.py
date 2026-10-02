"""
baseline.py - the app's current development method, refit on training rows only.

The ML backtest needs an honest opponent. This script rebuilds the method the
app uses today from the DEV row tables (dataset.py), fits it only on the rows
a split allows, and predicts the held-out rows with the same rules the app
applies to a TGS or BLM player. Nothing in the app changes.

The current method (dev_odds.py builds the cells, dev_signals.py reads them):
  observation  one player-dump at ages 16-26, in an org (raw Lev in ORG_LEV),
               with a Pot grade; a growth cell also needs the previous dump
  cohort       players first seen at age <= 20 who were ever in an org; the
               shipped dev_odds.json also limits the first dump to 2025 through
               the last banked dump minus 23 (the end moves with the dumps)
  cells        role x age x Pot bucket x last-year growth bucket, plus the
               pot-only cells (role x age x Pot bucket, growth unknown)
  peak cell    eventual peak WAA (max now_WAA from that dump on) of the players
               seen at age >= 27 (realized); n, peak p50, the mlb / useful /
               good shares, the gain grid (gain = peak - now, quantiles 5..95,
               2 decimals) and 3 now-tercile sub-cells when the cell has >= 15
               rows
  regular      share of the observations whose player ever had a season with
               >= 300 MLB PA or >= 150 MLB BF (regular_ever), no censoring
  per player   the growth cell; the pot-only cell when growth is unknown or the
               growth cell has n < 15; the now-tercile sub-cell that holds his
               current WAA (the nearest one when outside), the whole cell when
               that sub-cell has n < 15; gain p25 / p50 / p75 from that grid;
               the chance to reach -1 / 0 / +1.5 WAA = the share of the grid's
               gains at or above (bar - now), 1.0 when now >= bar - 0.05; at the
               edge (now outside every sub-cell's range) the lower of that and
               the sub-cell's own share; Make it % = the regular cell, null when
               n < 15 (a thin growth cell gets no pot-only stand-in here)
  path         src/lib/futureValue.js measuredPath: growth to age 27 along the
               curve shape G(a) toward now + max(0, gain p50), or toward now +
               closable(age) x the listed gap when there is no cell; no decline
               before 28; from 28 on, each year adds min(0, curve mean); the
               path stops at age 40 and holds its last value after that

Methods written to .dev_cache/ml/preds/<method>_<group>.pkl:
  current               peak group. Cells fit on cohort_first20 training rows,
                        realized careers only. This is the app's rule without the
                        first-dump window, so it sees the same training players
                        the ML sees.
  current_w40           peak group. The app's exact cohort (cohort_dev_odds:
                        first dump 2025 to the last banked dump minus 23; the
                        name is from the old fixed 2025-2040 window). SELF-CHECK
                        1 fits it on all rows and compares it with the shipped
                        dev_odds.json.
  current_all           peak group. Like current, but the cells count every
                        finished career (realized OR retired), so washouts count.
                        Its regular cells also count finished careers only.
  current_path          path group. measuredPath with a curve refit on the
                        training rows and the gain p50 of the current cells.
  current_path_shipped  path group. The same with public/data/DEV/age_curve.json.
                        LEAKY: that curve saw every DEV player, held-out ones too.
  age_mean              path group. d_k = the sum of the training mean one-year
                        WAA change (role x age) over the k years.

The refit curve against engine/agecurve_fit.py (the shipped DEV curve):
  same    every consecutive dump pair of a player, same engine kind at both
          dumps, in an org at the earlier dump; a pair whose age ticked by one
          is split half to the starting age and half to the next age (every
          DEV pair does, since dumps are one game-year apart and ages are Jan-1
          ages); mean = sum of deltas / sum of exposure years; closure = the
          share of the (ceiling - now) gap closed, gap >= 0.3, clamped to
          [-1, 2]; an age ships with >= 25 contributions; both roles pooled;
          4-decimal rounding
  differs only rows the ML tables hold (ages 16-40, priced now_WAA), only the
          players of the training set, "in an org" = raw Lev in ORG_LEV
          instead of the vintage org field, and no contamination guard (the
          shipped DEV curve flagged 0 pairs)

One model set per league (2026-09-24): --basis TGS | BLM (required) picks the
DEV tables priced with that league's engine calibration (dev_<role>_<basis>.pkl)
and writes to preds/<basis> and report/<basis>. The self-check compares with
the shipped dev_odds.json / dev_signals.json / DEV age_curve.json, which are
priced on the BLM basis, so it runs on --basis BLM only (and --no-self-check
skips it). current_path_shipped reads the shipped DEV curve on either basis.

Out-of-org rows (fix 6, 2026-09-24): the app gives amateurs and free agents
the same cells (fit on in-org rows only). With the ML peak models now also
training on DEV rows outside an org, the baseline predicts those rows too:
<method>_peak_outside.pkl for current, current_w40 and current_all, rows at
ages 16-26, in_org 0, peak_known 1, cells fit exactly as for the main files.

Rows and targets come from the dataset.py tables. The table role is the role
a player held in most dumps; dev_odds files an observation under the role of
that dump. The two differ on 238 hitter rows and 272 pitcher rows of 2.3M;
this script keeps the table role for fitting and predicting.

Prediction files (one per method and group, both splits and both roles):
  keys     pid, dump_year, role, split ('oof' or 'time'), fold (0-4 for oof,
           -1 for time), age
  peak     gain_q10, gain_q25, gain_q50, gain_q75, gain_q90, p_mlb, p_useful,
           p_good, p_regular (NaN where regular_future is unknown),
           p_regular_fut (extra: the same cells with regular_future as the
           outcome), basis, cell
  path     d1..d5, d1_q25, d1_q75, target (cell / listed / none)
  Rows: peak = ages 16-26, in an org, peak_known; path = ages 16-38 with
  present_1 == 1. OOF: each fold predicted by a fit on the other four. TIME:
  a fit on time_split 'train', predicting time_split 'test'. A row without an
  answer stays in the file with NaN.

CLI:
  PY314 baseline.py --basis B          self-check, fit, print summaries, write nothing
  PY314 baseline.py --basis B --write  also write the prediction files and reports
  --self-check-only                 run the self-check and stop
  --no-self-check                   skip the self-check (always skipped on TGS)
  --splits oof,time                 which splits to run (default both)
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import common as C                                              # noqa: E402

sys.path.insert(0, C.BT)
import dev_odds as DO                                           # noqa: E402
import dev_signals as DSIG                                      # noqa: E402

ODDS_PATH = os.path.join(C.APP_DATA, "dev_odds.json")
CURVE_PATH = os.path.join(C.APP_DATA, "DEV", "age_curve.json")

AGES = list(range(16, 27))                  # dev_odds.AGES
POT_BUCKETS = DO.POT_BUCKETS
GROWTH_BUCKETS = DO.GROWTH_BUCKETS
PEAK_BARS = DO.PEAK_BARS
PCTS = list(DO.GAIN_GRID_PCTS)
LVL = np.array(PCTS, dtype=float) / 100.0
MIN_N = DSIG.MIN_N                          # 15
MIN_CELL_NOTE = DO.MIN_CELL_NOTE            # 15
NOW_TERCILES = DO.NOW_TERCILES
BAR_TOL = DSIG.BAR_TOLERANCE                # 0.05
GI = {q: PCTS.index(q) for q in (10, 25, 50, 75, 90)}

GROWTH_START_AGE, GROWTH_END_AGE = 16, 27   # src/lib/ageCurve.js
PATH_END_AGE = 40                           # src/lib/ageCurve.js: the path stops here
CURVE_MIN_N = 25                            # agecurve_fit.MIN_AGE_N
PATH_AGES = (16, 38)
PEAK_AGES = (16, 26)
HORIZONS = (1, 2, 3, 4, 5)

# The cell method reads the UNMASKED one-year growth (grow_steps_r_card /
# has_prev_card): dev_odds builds its cells from every DEV card, and the DEV
# league is exempt from the out-of-an-org rule in dev_signals (hidden-card fix,
# 2026-09-25). The model features grow_steps_r / has_prev carry that mask.
KEEP = ["pid", "dump_year", "age", "in_org", "lev_raw", "now_waa", "ceiling_waa", "pot", "grow_steps_r_card",
        "has_prev_card", "now_kind", "peak", "peak_known", "realized", "regular_ever", "regular_future",
        "cohort_first20", "cohort_dev_odds", "fold", "time_split", "present_1",
        "d_1", "d_2", "d_3", "d_4", "d_5", "gain", "reach_mlb", "reach_useful", "reach_good"]

VARIANTS = {
    # name: (cohort flag, peak rows, regular rows)
    "current": ("cohort_first20", "realized", "all"),
    "current_w40": ("cohort_dev_odds", "realized", "all"),
    "current_all": ("cohort_first20", "peak_known", "peak_known"),
}


# ---------------------------------------------------------------- small helpers
def log(msg=""):
    print(msg, flush=True)


def pot_code(pot):
    """dev_odds.pot_bucket as a code 0..4; -1 when Pot is missing."""
    out = np.full(len(pot), -1, dtype=np.int8)
    ok = np.isfinite(pot)
    p = pot[ok]
    out[ok] = np.select([p < 40, p < 45, p < 50, p < 55], [0, 1, 2, 3], 4)
    return out


def growth_code(role, g, known):
    """dev_odds.growth_bucket as a code; -1 when growth is unknown."""
    out = np.full(len(g), -1, dtype=np.int8)
    ok = known & np.isfinite(g)
    x = g[ok]
    if role == "H":
        out[ok] = np.select([x <= 0, x <= 2, x <= 4, x <= 6], [0, 1, 2, 3], 4)
    else:
        out[ok] = np.select([x <= 0, x <= 1.5, x <= 3], [0, 1, 2], 3)
    return out


def pyround(x, nd):
    """Python's round() on a plain float, as dev_odds does."""
    return round(float(x), nd)


def lookup(tree, *keys):
    return DSIG.lookup(tree, *keys)


# ---------------------------------------------------------------- data
def load_role(role):
    t0 = time.time()
    df = C.load_table(C.dev_table(role))
    df = df[KEEP].copy()
    df["role"] = role
    df["age_i"] = df["age"].astype(np.int16)
    df["pb"] = pot_code(df["pot"].to_numpy(np.float64))
    df["gb"] = growth_code(role, df["grow_steps_r_card"].to_numpy(np.float64),
                           df["has_prev_card"].to_numpy() == 1)
    log(f"  loaded {os.path.basename(C.dev_table(role))}: {len(df):,} rows in {time.time() - t0:.1f}s")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- cells (dev_odds port)
def empty_peak():
    out = {"n": 0, "p50": None, "gain_n": 0, "gain_p25": None, "gain_p50": None, "gain_p75": None}
    for name in PEAK_BARS:
        out[f"{name}_share"] = None
    out["gain_grid"] = None
    out["by_now"] = None
    return out


def gain_grid(sorted_gains):
    if not sorted_gains:
        return None
    return [pyround(DO.percentile(sorted_gains, q), 2) for q in PCTS]


def peak_stats(peaks, nows):
    """dev_odds.PeakCell.stats for the fields dev_signals reads. peaks and
    nows are float64 arrays of the same rows (every table row is priced)."""
    n = len(peaks)
    if n == 0:
        return empty_peak()
    out = {"n": n}
    v = sorted(peaks.tolist())
    out["p50"] = pyround(DO.percentile(v, 50), 2)
    gains = peaks - nows
    g = sorted(gains.tolist())
    out["gain_n"] = len(g)
    for q in (25, 50, 75):
        out[f"gain_p{q}"] = pyround(DO.percentile(g, q), 2)
    for name, bar in PEAK_BARS.items():
        out[f"{name}_share"] = round(int(np.sum(peaks >= bar)) / n, 3)
    out["gain_grid"] = gain_grid(g)
    out["by_now"] = by_now(nows, gains, peaks) if len(g) >= MIN_CELL_NOTE else None
    return out


def by_now(nows, gains, peaks):
    """dev_odds.by_now_terciles."""
    sn = sorted(nows.tolist())
    cuts = np.array([DO.percentile(sn, 100.0 * (i + 1) / NOW_TERCILES) for i in range(NOW_TERCILES - 1)])
    which = (nows[:, None] > cuts[None, :]).sum(axis=1)
    out = []
    for i in range(NOW_TERCILES):
        m = which == i
        if not m.any():
            sub = {"lo": None, "hi": None, "n": 0}
            sub.update({name: None for name in PEAK_BARS})
            sub["gain_grid"] = None
            out.append(sub)
            continue
        ns, gs, ps = nows[m], gains[m], peaks[m]
        sub = {"lo": pyround(ns.min(), 2), "hi": pyround(ns.max(), 2), "n": int(m.sum())}
        for name, bar in PEAK_BARS.items():
            sub[name] = round(int(np.sum(ps >= bar)) / len(ps), 3)
        sub["gain_grid"] = gain_grid(sorted(gs.tolist()))
        out.append(sub)
    return out


def odds_stats(y):
    n = len(y)
    return {"p": round(int(np.sum(y)) / n, 3) if n else None, "n": n}


def _groups(keys):
    """{key: row index array} for an int key array."""
    if len(keys) == 0:
        return {}
    order = np.argsort(keys, kind="stable")
    ks = keys[order]
    cut = np.flatnonzero(np.diff(ks)) + 1
    starts = np.r_[0, cut]
    return {int(ks[s]): order[s:e] for s, e in zip(starts, np.r_[cut, len(ks)])}


def fit_cells(frames, fit_masks, variant, reg_outcome="regular_ever", peaks=True):
    """dev_odds.build_payload's grid / pot_only / peak / peak_pot_only trees,
    fit on the rows fit_masks[role] allows. variant picks the cohort and
    which careers count (VARIANTS). reg_outcome = the regular column the
    grid / pot_only odds count; peaks False skips the peak trees."""
    cohort_col, peak_rule, reg_rule = VARIANTS[variant]
    cells = {"grid": {}, "pot_only": {}, "peak": {}, "peak_pot_only": {}}
    for role, df in frames.items():
        age = df["age_i"].to_numpy()
        base = (fit_masks[role] & (df[cohort_col].to_numpy() == 1) & (df["in_org"].to_numpy() == 1)
                & (age >= AGES[0]) & (age <= AGES[-1]) & (df["pb"].to_numpy() >= 0))
        peak = df["peak"].to_numpy(np.float64)
        now = df["now_waa"].to_numpy(np.float64)
        pk_ok = (df[peak_rule].to_numpy() == 1) & np.isfinite(peak)
        reg_y = df[reg_outcome].to_numpy(np.float64)
        reg_ok = np.isfinite(reg_y)
        if reg_rule == "peak_known":
            reg_ok &= df["peak_known"].to_numpy() == 1
        pb, gb = df["pb"].to_numpy().astype(int), df["gb"].to_numpy().astype(int)
        key_g = age.astype(int) * 100 + pb * 10 + gb
        key_p = age.astype(int) * 100 + pb * 10
        has_g = gb >= 0
        grid = {str(a): {p: {g: {"p": None, "n": 0} for g in GROWTH_BUCKETS[role]} for p in POT_BUCKETS}
                for a in AGES}
        ponly = {str(a): {p: {"p": None, "n": 0} for p in POT_BUCKETS} for a in AGES}
        pk = {str(a): {p: {g: empty_peak() for g in GROWTH_BUCKETS[role]} for p in POT_BUCKETS} for a in AGES}
        pkp = {str(a): {p: empty_peak() for p in POT_BUCKETS} for a in AGES}
        rows = np.flatnonzero(base & has_g & reg_ok)
        for k, idx in _groups(key_g[rows]).items():
            a, p, g = k // 100, (k // 10) % 10, k % 10
            grid[str(a)][POT_BUCKETS[p]][GROWTH_BUCKETS[role][g]] = odds_stats(reg_y[rows[idx]])
        rows = np.flatnonzero(base & reg_ok)
        for k, idx in _groups(key_p[rows]).items():
            a, p = k // 100, (k // 10) % 10
            ponly[str(a)][POT_BUCKETS[p]] = odds_stats(reg_y[rows[idx]])
        rows = np.flatnonzero(base & has_g & pk_ok) if peaks else np.array([], dtype=int)
        for k, idx in _groups(key_g[rows]).items():
            a, p, g = k // 100, (k // 10) % 10, k % 10
            r = rows[idx]
            pk[str(a)][POT_BUCKETS[p]][GROWTH_BUCKETS[role][g]] = peak_stats(peak[r], now[r])
        rows = np.flatnonzero(base & pk_ok) if peaks else np.array([], dtype=int)
        for k, idx in _groups(key_p[rows]).items():
            a, p = k // 100, (k // 10) % 10
            r = rows[idx]
            pkp[str(a)][POT_BUCKETS[p]] = peak_stats(peak[r], now[r])
        cells["grid"][role], cells["pot_only"][role] = grid, ponly
        cells["peak"][role], cells["peak_pot_only"][role] = pk, pkp
    return cells


# ---------------------------------------------------------------- per player (dev_signals port)
def share_at_least_v(grid, d):
    """dev_signals.share_at_least over an array of distances d."""
    g = np.asarray(grid, dtype=float)
    d = np.asarray(d, dtype=float)
    out = np.zeros(len(d))
    q05, q95 = g[0], g[-1]
    m0 = d <= 0
    m1 = ~m0 & (d <= q05)
    m3 = ~m0 & ~m1 & (d > q95)
    m2 = ~m0 & ~m1 & ~m3
    out[m0] = 1.0
    if m1.any():
        out[m1] = 1.0 - LVL[0] * d[m1] / q05
    if m3.any():
        out[m3] = 0.0 if q95 <= 0 else np.maximum(0.0, (1.0 - LVL[-1]) * (1.0 - (d[m3] - q95) / q95))
    if m2.any():
        x = d[m2]
        i = np.clip(np.searchsorted(g, x, side="left") - 1, 0, len(g) - 2)
        lo, hi = g[i], g[i + 1]
        f = LVL[i] + (LVL[i + 1] - LVL[i]) * (x - lo) / (hi - lo)
        out[m2] = 1.0 - f
    return out


def thin(pc):
    return pc is None or DSIG.thin(pc)


def choose_peak_cell(cells, role, age, pb, gb):
    """(cell, pot_only, key) as dev_signals.measure_player picks it; cell None
    when no usable cell."""
    ages, pbs = str(age), POT_BUCKETS[pb]
    if gb >= 0:
        gbs = GROWTH_BUCKETS[role][gb]
        pc = lookup(cells, "peak", role, ages, pbs, gbs)
        key = f"{role}/{age}/{pbs}/{gbs}"
        pot_only = False
        if pc is not None and thin(pc):
            alt = lookup(cells, "peak_pot_only", role, ages, pbs)
            if alt is not None and not thin(alt):
                pc, pot_only, key = alt, True, f"{role}/{age}/{pbs}/any"
    else:
        pc = lookup(cells, "peak_pot_only", role, ages, pbs)
        pot_only, key = True, f"{role}/{age}/{pbs}/any"
    if pc is None or thin(pc):
        return None, pot_only, key
    return pc, pot_only, key


def predict_group(pc, pot_only, now):
    """The dev_signals fields for the rows of one cell. now = current WAA
    (NaN allowed). Returns a dict of arrays and a basis array."""
    n = len(now)
    res = {k: np.full(n, np.nan) for k in ("gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90",
                                           "p_mlb", "p_useful", "p_good")}
    basis = np.empty(n, dtype=object)
    pre = "potonly_" if pot_only else ""
    cell_grid = pc.get("gain_grid")
    cell_share = {name: pc.get(f"{name}_share") for name in PEAK_BARS}
    has_now = np.isfinite(now)
    nr = np.where(has_now, np.round(np.where(has_now, now, 0.0), 2), np.nan)

    # whole-cell defaults (dev_signals: gain_p25 / p50 / p75 from the cell)
    for q in (25, 50, 75):
        v = pc.get(f"gain_p{q}")
        res[f"gain_q{q}"][:] = np.nan if v is None else v
    if cell_grid is not None:
        res["gain_q10"][:] = cell_grid[GI[10]]
        res["gain_q90"][:] = cell_grid[GI[90]]

    # rows without a current WAA (or a cell without a grid): the cell shares
    plain = ~has_now if cell_grid is not None else np.ones(n, bool)
    for name in PEAK_BARS:
        v = cell_share[name]
        res[f"p_{name}"][plain] = np.nan if v is None else v
    basis[plain] = pre + "cell_shares"
    todo = np.flatnonzero(~plain)
    if not len(todo):
        return res, basis

    subs = [s for s in (pc.get("by_now") or []) if isinstance(s, dict)
            and s.get("lo") is not None and s.get("hi") is not None]
    x = nr[todo]
    if subs:
        lo = np.array([s["lo"] for s in subs])
        hi = np.array([s["hi"] for s in subs])
        inside = (x[:, None] >= lo[None, :]) & (x[:, None] <= hi[None, :])
        dist = np.where(inside, 0.0, np.minimum(np.abs(x[:, None] - lo[None, :]),
                                                np.abs(x[:, None] - hi[None, :])))
        pick = np.argmin(dist, axis=1)                      # first minimum, as pick_sub
        edge = (x < lo.min()) | (x > hi.max())
    else:
        pick = np.full(len(x), -1)
        edge = np.zeros(len(x), bool)

    for si in ([-1] + list(range(len(subs)))):
        m = pick == si
        if not m.any():
            continue
        rows = todo[m]
        xs = x[m]
        sub = subs[si] if si >= 0 else None
        use_sub = sub is not None and (sub.get("n") or 0) >= MIN_N and sub.get("gain_grid")
        if use_sub:
            grid = sub["gain_grid"]
            for q in (10, 25, 50, 75, 90):
                res[f"gain_q{q}"][rows] = grid[GI[q]]
            eg = edge[m]
            edge_ok = all(sub.get(name) is not None for name in PEAK_BARS)
            b = np.where(eg & edge_ok, pre + "tercile_edge", pre + "tercile")
        else:
            grid = cell_grid
            eg = np.zeros(len(rows), bool)
            edge_ok = False
            b = np.full(len(rows), pre + "whole")
        basis[rows] = b
        for name, bar in PEAK_BARS.items():
            ch = np.round(share_at_least_v(grid, bar - xs), 3)
            if use_sub and edge_ok:
                ch = np.where(eg, np.minimum(sub[name], ch), ch)
            ch = np.where(xs >= bar - BAR_TOL, 1.0, ch)
            res[f"p_{name}"][rows] = ch
    return res, basis


def predict_rows(df, rows, cells, reg_cells=None):
    """dev_signals per-row fields for df rows (index array), from cells.
    reg_cells: a second tree for p_regular_fut (grid / pot_only), optional."""
    role = df["role"].iat[0]
    n = len(rows)
    out = {k: np.full(n, np.nan) for k in ("gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90",
                                           "p_mlb", "p_useful", "p_good", "p_regular", "p_regular_fut")}
    basis = np.full(n, "no_pot", dtype=object)
    cellk = np.full(n, "", dtype=object)
    age = np.clip(df["age_i"].to_numpy()[rows], AGES[0], AGES[-1]).astype(int)
    pb = df["pb"].to_numpy()[rows].astype(int)
    gb = df["gb"].to_numpy()[rows].astype(int)
    now = df["now_waa"].to_numpy(np.float64)[rows]
    ok = pb >= 0
    key = age * 100 + pb * 10 + (gb + 1)
    for k, idx in _groups(np.where(ok, key, -1)).items():
        if k < 0:
            continue
        a, p, g = k // 100, (k // 10) % 10, k % 10 - 1
        pc, pot_only, ck = choose_peak_cell(cells, role, a, p, g)
        cellk[idx] = ck
        if pc is None:
            basis[idx] = "thin"
        else:
            res, b = predict_group(pc, pot_only, now[idx])
            for f, v in res.items():
                out[f][idx] = v
            basis[idx] = b
        # Make it %: the growth cell, else the pot-only cell; thin gives null
        for tree, col in ((cells, "p_regular"), (reg_cells, "p_regular_fut")):
            if tree is None:
                continue
            if g >= 0:
                c = lookup(tree, "grid", role, str(a), POT_BUCKETS[p], GROWTH_BUCKETS[role][g])
            else:
                c = lookup(tree, "pot_only", role, str(a), POT_BUCKETS[p])
            if c is not None and (c.get("n") or 0) >= MIN_N and c.get("p") is not None:
                out[col][idx] = c["p"]
    # the bar rule needs no cell: a row already at a bar reads 1.0 even when
    # the app has no cell for him (no Pot grade, thin cell); the file contract
    # applies it to every method
    nr = np.round(now, 2)
    for name, bar in PEAK_BARS.items():
        at = np.isfinite(nr) & (nr >= bar - BAR_TOL)
        out[f"p_{name}"][at] = 1.0
    return out, basis, cellk


# ---------------------------------------------------------------- curve (agecurve_fit port) and path (futureValue port)
def build_pairs(frames):
    """Consecutive-dump pairs of every player over both role tables: the
    starting row index per role plus the pair fields agecurve_fit uses."""
    cols = ["pid", "dump_year", "age_i", "now_waa", "ceiling_waa", "now_kind", "in_org", "fold", "time_split"]
    parts = []
    for role, df in frames.items():
        p = df[cols].copy()
        p["role"] = role
        p["row"] = np.arange(len(df))
        parts.append(p)
    allr = pd.concat(parts, ignore_index=True)
    allr["now_kind"] = allr["now_kind"].astype(str)
    nxt = allr[["pid", "dump_year", "age_i", "now_waa", "now_kind"]].copy()
    nxt["dump_year"] = nxt["dump_year"] - 1
    m = allr.merge(nxt, on=["pid", "dump_year"], how="inner", suffixes=("", "_2"))
    d = m["age_i_2"].astype(int) - m["age_i"].astype(int)
    ok = ((m["now_kind"] == m["now_kind_2"]) & (m["in_org"] == 1) & d.isin([0, 1])
          & np.isfinite(m["now_waa"]) & np.isfinite(m["now_waa_2"]))
    m = m[ok].copy()
    m["d"] = d[ok].astype(int)
    m["delta"] = m["now_waa_2"].astype(np.float64) - m["now_waa"].astype(np.float64)
    m["gap"] = m["ceiling_waa"].astype(np.float64) - m["now_waa"].astype(np.float64)
    return m.reset_index(drop=True)


def fit_curve(pairs, mask):
    """agecurve_fit's per-age mean and closure over the pairs mask allows.
    Returns {"curve": {age_str: {n, mean, closure, n_gap}}} like age_curve.json."""
    p = pairs[mask]
    span_by_year = p.groupby("dump_year")["d"].mean()
    span = p["dump_year"].map(span_by_year).to_numpy(np.float64)
    a1 = p["age_i"].to_numpy().astype(int)
    d = p["d"].to_numpy()
    delta = p["delta"].to_numpy()
    gap = p["gap"].to_numpy()
    size = 64
    sums, yrs, cnt = np.zeros(size), np.zeros(size), np.zeros(size)
    cs, cy, cc = np.zeros(size), np.zeros(size), np.zeros(size)
    hasgap = np.isfinite(gap) & (gap >= 0.3)
    cd = np.clip(np.where(hasgap, delta / np.where(hasgap, gap, 1.0), 0.0), -1.0, 2.0)
    for ages, w in ((a1, np.where(d == 0, 1.0, 0.5)), (a1 + 1, np.where(d == 1, 0.5, 0.0))):
        use = w > 0
        sums += np.bincount(ages[use], delta[use] * w[use], size)
        yrs += np.bincount(ages[use], span[use] * w[use], size)
        cnt += np.bincount(ages[use], None, size)
        g = use & hasgap
        cs += np.bincount(ages[g], cd[g] * w[g], size)
        cy += np.bincount(ages[g], span[g] * w[g], size)
        cc += np.bincount(ages[g], None, size)
    curve = {}
    for a in range(size):
        if cnt[a] < CURVE_MIN_N or yrs[a] <= 0:
            continue
        clo = cs[a] / cy[a] if cy[a] > 0 and cc[a] >= CURVE_MIN_N else None
        curve[str(a)] = {"n": int(cnt[a]), "mean": round(sums[a] / yrs[a], 4),
                         "closure": round(clo, 4) if clo is not None else None, "n_gap": int(cc[a])}
    return {"curve": curve}


class Shape:
    """src/lib/ageCurve.js buildShape: mean(age), G(age), closable(age)."""

    def __init__(self, age_curve):
        curve = age_curve["curve"]

        def raw_mean(a):
            c = curve.get(str(a))
            v = c.get("mean") if c else None
            return v if isinstance(v, (int, float)) and math.isfinite(v) else None

        def raw_closure(a):
            c = curve.get(str(a))
            v = c.get("closure") if c else None
            return min(1.0, max(0.0, v)) if isinstance(v, (int, float)) and math.isfinite(v) else None

        ages = sorted(int(a) for a in curve if raw_mean(int(a)) is not None)
        self.first, self.last = ages[0], ages[-1]
        self._raw_mean = raw_mean
        cum, run = {}, 0.0
        for a in range(GROWTH_START_AGE, GROWTH_END_AGE + 1):
            cum[a] = run
            if a < GROWTH_END_AGE:
                run += max(0.0, self.mean(a) or 0.0)
        self.cum, self.total = cum, run
        self.has_closure = any(raw_closure(a) is not None for a in ages)
        self.closable_by_age = {}
        for a in range(GROWTH_START_AGE, GROWTH_END_AGE + 1):
            open_ = 1.0
            for t in range(a, GROWTH_END_AGE):
                open_ *= 1.0 - (raw_closure(t) or 0.0)
            self.closable_by_age[a] = 1.0 - open_

    def mean(self, age):
        a = int(math.floor(age))
        if a <= self.first:
            return self._raw_mean(self.first)
        if a >= self.last:
            return self._raw_mean(self.last)
        for t in range(a, self.first - 1, -1):
            m = self._raw_mean(t)
            if m is not None:
                return m
        return None

    def G(self, age):
        a = int(math.floor(age))
        if a <= GROWTH_START_AGE:
            return 0.0
        if a >= GROWTH_END_AGE:
            return 1.0
        return self.cum[a] / self.total

    def closable(self, age):
        if not self.has_closure:
            return 1.0
        a = int(math.floor(age))
        if a <= GROWTH_START_AGE:
            return self.closable_by_age[GROWTH_START_AGE]
        if a >= GROWTH_END_AGE:
            return 0.0
        return self.closable_by_age[a]

    def coef(self, a0):
        """measuredPath from floor age a0 as d_k = A_k * (target - now) + B_k.
        The app's path ends at max(PATH_END_AGE, a0) and pathAt holds the
        last value after that, so the change stops there."""
        g0 = self.G(a0)
        room = 1.0 - g0
        end = max(PATH_END_AGE, a0)
        A, B = [], []
        a_k, b_k = 0.0, 0.0
        for k in HORIZONS:
            a = a0 + k
            if a > end:
                pass
            elif a <= GROWTH_END_AGE and room > 0:
                a_k, b_k = (self.G(a) - g0) / room, 0.0
            else:
                b_k += min(0.0, self.mean(a - 1) or 0.0)
            A.append(a_k)
            B.append(b_k)
        return A, B


def path_current(df, rows, shape, gain50):
    """measuredPath d1..d5 for df rows; gain50 = the cell gain p50 (NaN when
    no cell). Returns (d array rows x 5, target source)."""
    age = df["age_i"].to_numpy()[rows].astype(int)
    now = df["now_waa"].to_numpy(np.float64)[rows]
    ceil = df["ceiling_waa"].to_numpy(np.float64)[rows]
    listed = np.where(np.isfinite(ceil), ceil, now)
    clos = np.array([shape.closable(a) for a in range(0, 64)])
    has_cell = np.isfinite(gain50)
    target = np.where(has_cell, now + np.maximum(0.0, np.where(has_cell, gain50, 0.0)),
                      now + clos[age] * np.maximum(0.0, listed - now))
    src = np.where(has_cell, "cell", "listed")
    A = np.zeros((64, 5))
    B = np.zeros((64, 5))
    for a in np.unique(age):
        A[a], B[a] = shape.coef(int(a))
    d = A[age] * (target - now)[:, None] + B[age]
    return d, src


def age_tables(frames, fit_masks):
    """Per role x age: mean d_1 and the 25 / 75 quantiles of d_1, over the
    training rows with a next dump. {role: (ages, mean, q25, q75)}."""
    out = {}
    for role, df in frames.items():
        m = fit_masks[role] & (df["present_1"].to_numpy() == 1) & np.isfinite(df["d_1"].to_numpy())
        sub = pd.DataFrame({"a": df["age_i"].to_numpy()[m], "d": df["d_1"].to_numpy(np.float64)[m]})
        g = sub.groupby("a")["d"]
        t = pd.DataFrame({"mean": g.mean(), "q25": g.quantile(0.25), "q75": g.quantile(0.75), "n": g.size()})
        t = t[t["n"] >= CURVE_MIN_N]
        out[role] = t
    return out


def age_lookup(t, ages, col):
    """t[col] at each age; an age below the first uses the first, above the
    last uses the last, a hole uses the nearest lower age (ageCurve.js rule)."""
    idx = t.index.to_numpy()
    vals = t[col].to_numpy()
    pos = np.searchsorted(idx, ages, side="right") - 1
    pos = np.clip(pos, 0, len(idx) - 1)
    return vals[pos]


# ---------------------------------------------------------------- splits
def split_plan(frames, which):
    """[(split, fold, fit_masks, pred_masks)] per split."""
    plan = []
    if "oof" in which:
        for f in range(C.N_FOLDS):
            fit = {r: df["fold"].to_numpy() != f for r, df in frames.items()}
            pred = {r: df["fold"].to_numpy() == f for r, df in frames.items()}
            plan.append(("oof", f, fit, pred))
    if "time" in which:
        fit = {r: df["time_split"].astype(str).to_numpy() == "train" for r, df in frames.items()}
        pred = {r: df["time_split"].astype(str).to_numpy() == "test" for r, df in frames.items()}
        plan.append(("time", -1, fit, pred))
    return plan


def group_masks(df):
    """(peak rows in an org, path rows, peak rows outside an org)."""
    age = df["age_i"].to_numpy()
    young = ((age >= PEAK_AGES[0]) & (age <= PEAK_AGES[1]) & (df["peak_known"].to_numpy() == 1))
    peak = young & (df["in_org"].to_numpy() == 1)
    outside = young & (df["in_org"].to_numpy() == 0)
    path = (age >= PATH_AGES[0]) & (age <= PATH_AGES[1]) & (df["present_1"].to_numpy() == 1)
    return peak, path, outside


def key_frame(df, rows, split, fold):
    return pd.DataFrame({
        "pid": df["pid"].to_numpy()[rows].astype(np.int64),
        "dump_year": df["dump_year"].to_numpy()[rows].astype(np.int16),
        "role": df["role"].iat[0],
        "split": split,
        "fold": np.int8(fold),
        "age": df["age"].to_numpy()[rows].astype(np.float32),
    })


def run_splits(frames, pairs, shipped_shape, which):
    """Fit per training set and predict the held-out rows. Returns
    {method: [DataFrame parts]}."""
    out = {m: [] for m in ("current", "current_w40", "current_all",
                           "current_path", "current_path_shipped", "age_mean")
           + tuple(f"{v}_outside" for v in VARIANTS)}
    gm = {r: group_masks(df) for r, df in frames.items()}
    for split, fold, fit, pred in split_plan(frames, which):
        t0 = time.time()
        tag = f"{split}" + (f" fold {fold}" if split == "oof" else "")
        cells = {v: fit_cells(frames, fit, v) for v in VARIANTS}
        cells_fut = {v: fit_cells(frames, fit, v, reg_outcome="regular_future", peaks=False) for v in VARIANTS}
        pmask = np.zeros(len(pairs), bool)
        for role, df in frames.items():
            fr = fit[role]
            sel = pairs["role"].to_numpy() == role
            pmask[sel] = fr[pairs["row"].to_numpy()[sel]]
        curve = fit_curve(pairs, pmask)
        shape = Shape(curve)
        at = age_tables(frames, fit)
        for role, df in frames.items():
            peak_m, path_m, out_m = gm[role]
            for suffix, gmask in (("", peak_m), ("_outside", out_m)):
                rows = np.flatnonzero(pred[role] & gmask)
                for v in VARIANTS:
                    res, basis, ck = predict_rows(df, rows, cells[v], cells_fut[v])
                    kf = key_frame(df, rows, split, fold)
                    for k, arr in res.items():
                        kf[k] = arr.astype(np.float32)
                    known = np.isfinite(df["regular_future"].to_numpy(np.float64)[rows])
                    kf.loc[~known, "p_regular"] = np.nan
                    kf.loc[~known, "p_regular_fut"] = np.nan
                    kf["basis"] = basis
                    kf["cell"] = ck
                    out[v + suffix].append(kf)
            # path rows
            rows = np.flatnonzero(pred[role] & path_m)
            young = df["age_i"].to_numpy()[rows] <= PEAK_AGES[1]
            g50 = np.full(len(rows), np.nan)
            if young.any():
                res, _b, _c = predict_rows(df, rows[young], cells["current"])
                g50[young] = res["gain_q50"]
            ages = df["age_i"].to_numpy()[rows].astype(int)
            t = at[role]
            q25 = age_lookup(t, ages, "q25")
            q75 = age_lookup(t, ages, "q75")
            for name, shp in (("current_path", shape), ("current_path_shipped", shipped_shape)):
                d, src = path_current(df, rows, shp, g50)
                kf = key_frame(df, rows, split, fold)
                for k in HORIZONS:
                    kf[f"d{k}"] = d[:, k - 1].astype(np.float32)
                kf["d1_q25"] = q25.astype(np.float32)
                kf["d1_q75"] = q75.astype(np.float32)
                kf["target"] = src
                out[name].append(kf)
            kf = key_frame(df, rows, split, fold)
            run = np.zeros(len(rows))
            for k in HORIZONS:
                run = run + age_lookup(t, ages + k - 1, "mean")
                kf[f"d{k}"] = run.astype(np.float32)
            kf["d1_q25"] = q25.astype(np.float32)
            kf["d1_q75"] = q75.astype(np.float32)
            kf["target"] = "none"
            out["age_mean"].append(kf)
        log(f"  {tag}: fit and predicted in {time.time() - t0:.1f}s "
            f"(curve ages {min(map(int, curve['curve']))}-{max(map(int, curve['curve']))})")
    return out


def finish(parts):
    df = pd.concat(parts, ignore_index=True)
    for c in ("role", "split", "basis", "cell", "target"):
        if c in df.columns:
            df[c] = df[c].astype("category")
    return df


# ---------------------------------------------------------------- self-check
def cmp_num(a, b):
    if a is None and b is None:
        return 0.0
    if a is None or b is None:
        return math.inf
    return abs(float(a) - float(b))


def compare_trees(mine, shipped):
    """Field-by-field comparison of two dev_odds cell trees. Returns a report dict."""
    rep = {}
    for tree, fields in (("grid", ("p", "n")), ("pot_only", ("p", "n")),
                         ("peak", ("n", "p50", "gain_n", "gain_p25", "gain_p50", "gain_p75",
                                   "mlb_share", "useful_share", "good_share")),
                         ("peak_pot_only", ("n", "p50", "gain_n", "gain_p25", "gain_p50", "gain_p75",
                                            "mlb_share", "useful_share", "good_share"))):
        cells = 0
        exact = 0
        worst = {f: (0.0, None) for f in fields + (("gain_grid", "by_now") if tree.startswith("peak") else ())}
        for role in ("H", "P"):
            for a in AGES:
                for pb in POT_BUCKETS:
                    keys = GROWTH_BUCKETS[role] if tree in ("grid", "peak") else [None]
                    for gb in keys:
                        path = (tree, role, str(a), pb) + ((gb,) if gb else ())
                        m = lookup(mine, *path)
                        s = lookup(shipped, *path)
                        if s is None:
                            continue
                        cells += 1
                        ok = True
                        for f in fields:
                            dv = cmp_num(m.get(f), s.get(f))
                            if dv > 1e-9:
                                ok = False
                                if dv > worst[f][0]:
                                    worst[f] = (dv, "/".join(path[1:]))
                        if tree.startswith("peak"):
                            mg, sg = m.get("gain_grid"), s.get("gain_grid")
                            dv = (0.0 if mg == sg else
                                  (max(abs(x - y) for x, y in zip(mg, sg)) if mg and sg else math.inf))
                            if dv > 1e-9:
                                ok = False
                                if dv > worst["gain_grid"][0]:
                                    worst["gain_grid"] = (dv, "/".join(path[1:]))
                            mb, sb = m.get("by_now"), s.get("by_now")
                            if mb != sb:
                                dv = math.inf
                                if mb and sb:
                                    dv = 0.0
                                    for x, y in zip(mb, sb):
                                        for f in ("lo", "hi", "n", "mlb", "useful", "good"):
                                            dv = max(dv, cmp_num(x.get(f), y.get(f)))
                                        if x.get("gain_grid") != y.get("gain_grid"):
                                            if x.get("gain_grid") and y.get("gain_grid"):
                                                dv = max(dv, max(abs(p - q) for p, q in
                                                                 zip(x["gain_grid"], y["gain_grid"])))
                                            else:
                                                dv = math.inf
                                if dv > 1e-9:
                                    ok = False
                                    if dv > worst["by_now"][0]:
                                        worst["by_now"] = (dv, "/".join(path[1:]))
                        exact += ok
        rep[tree] = {"cells": cells, "exact": exact,
                     "worst": {f: {"abs_diff": (None if v[0] == math.inf else round(v[0], 4)) if v[1] else 0.0,
                                   "cell": v[1]} for f, v in worst.items()}}
    return rep


def check_signals(odds, league):
    """Recompute the shipped dev_signals.json peak fields from the shipped
    dev_odds.json with this port, per player."""
    path = os.path.join(C.APP_DATA, league, "dev_signals.json")
    with open(path, encoding="utf-8") as fh:
        sig = json.load(fh)
    rows = []
    for pid, e in sig["players"].items():
        if e.get("pot") is None:
            continue
        rows.append({"pid": pid, "role": e["role"], "age_i": min(max(e["age"], 16), 26), "pot": e["pot"],
                     "grow": e["grow"] if e["grow"] is not None else np.nan,
                     "now_waa": e["share_now"] if e["share_now"] is not None else np.nan, "e": e})
    fields = [("gain_q25", "peak_gain_p25"), ("gain_q50", "peak_gain_p50"), ("gain_q75", "peak_gain_p75"),
              ("p_mlb", "peak_mlb"), ("p_useful", "peak_useful"), ("p_good", "peak_good"),
              ("p_regular", "odds")]
    rep = {"players": 0, "fields": {}}
    for role in ("H", "P"):
        rr = [r for r in rows if r["role"] == role]
        if not rr:
            continue
        df = pd.DataFrame({"role": role, "age_i": [r["age_i"] for r in rr],
                           "now_waa": np.array([r["now_waa"] for r in rr], float)})
        df["pb"] = pot_code(np.array([r["pot"] for r in rr], float))
        g = np.array([r["grow"] for r in rr], float)
        df["gb"] = growth_code(role, g, np.isfinite(g))
        res, _b, _c = predict_rows(df, np.arange(len(df)), odds)
        rep["players"] += len(rr)
        for mine, theirs in fields:
            s = np.array([np.nan if r["e"].get(theirs) is None else r["e"][theirs] for r in rr], float)
            m = res[mine]
            both = np.isfinite(s) & np.isfinite(m)
            miss = int(np.sum(np.isfinite(s) != np.isfinite(m)))
            dif = np.abs(s[both] - m[both])
            f = rep["fields"].setdefault(theirs, {"compared": 0, "exact": 0, "within_0.001": 0,
                                                  "max_abs_diff": 0.0, "null_mismatch": 0})
            f["compared"] += int(both.sum())
            f["exact"] += int(np.sum(dif < 1e-9))
            f["within_0.001"] += int(np.sum(dif <= 0.0010001))
            f["max_abs_diff"] = round(max(f["max_abs_diff"], float(dif.max()) if len(dif) else 0.0), 4)
            f["null_mismatch"] += miss
    return rep


def check_share_fn():
    """The vectorized share_at_least against dev_signals.share_at_least."""
    rng = np.random.default_rng(7)
    worst = 0.0
    n = 0
    for _ in range(300):
        g = np.sort(np.round(rng.gamma(1.5, 2.0, 19) * (rng.random(19) > 0.3), 2)).tolist()
        d = rng.uniform(-1, 2.5 * max(g[-1], 0.1), 60)
        v = share_at_least_v(g, d)
        for x, y in zip(d, v):
            worst = max(worst, abs(DSIG.share_at_least(g, float(x), PCTS) - y))
            n += 1
    return {"points": n, "max_abs_diff": worst}


RAW_CORE = {"H": ["BABIP", "Gap", "Pow", "Eye", "Ks"], "P": ["Stf", "HRA", "PBABIP", "Ctrl"]}


def dump_role_frames(frames):
    """The frames with dev_odds' role rule: an observation goes under the role
    of its own dump (SP / RP / CL = P), not the player's majority role. Rows
    whose dump role differs from the table role move to the other frame, with
    the growth recomputed on that role's core skills from the raw dumps (the
    table only carries the majority role's card). Needs the dataset.py raw
    parse cache. Returns (frames, moved row counts), or (None, reason)."""
    import dataset as D
    if not os.path.isfile(D.RAW_CACHE):
        return None, "no raw parse cache (run dataset.py --write)"
    years = D.load_dev_raw(False)
    pid, year, num, strs = D.stack_dev(years)
    key = pid * 10000 + year
    raw_role = np.where(np.isin(strs["Pos"].astype(str), list(C.PITCHER_POS)), "P", "H")
    out = {r: [df] for r, df in frames.items()}
    moved = {}
    for role, df in frames.items():
        k = df["pid"].to_numpy(np.int64) * 10000 + df["dump_year"].to_numpy(np.int64)
        idx = D.lookup(key, k)
        mis = np.flatnonzero((idx >= 0) & (raw_role[np.maximum(idx, 0)] != role))
        other = "P" if role == "H" else "H"
        moved[f"{role}->{other}"] = len(mis)
        sub = df.iloc[mis].copy()
        ci = idx[mis]
        pi = D.lookup(key, k[mis] - 1)
        tot = np.zeros(len(mis))
        for stem in RAW_CORE[other]:
            cur = (np.trunc(num[stem + "_R"][ci]) + np.trunc(num[stem + "_L"][ci])) / 2.0
            prv = np.where(pi >= 0, (np.trunc(num[stem + "_R"][np.maximum(pi, 0)])
                                     + np.trunc(num[stem + "_L"][np.maximum(pi, 0)])) / 2.0, np.nan)
            tot += (cur - prv) / 5.0
        g = np.array([round(float(x) * 2) / 2.0 if np.isfinite(x) else np.nan for x in tot])
        sub["role"] = other
        sub["gb"] = growth_code(other, g, np.isfinite(g))
        out[role][0] = df.drop(df.index[mis])
        out[other].append(sub)
    return {r: pd.concat(v, ignore_index=True) for r, v in out.items()}, moved


def self_check(frames, pairs):
    log("\nSELF-CHECK 1: dev_odds cells refit on all rows (the app's cohort, first dump 2025 to the last "
        "banked dump minus 23) against the shipped public/data/dev_odds.json")
    with open(ODDS_PATH, encoding="utf-8") as fh:
        odds = json.load(fh)
    everything = {r: np.ones(len(df), bool) for r, df in frames.items()}
    mine = fit_cells(frames, everything, "current_w40")
    rep = {"odds_generated": odds.get("generated")}
    rep["cells"] = compare_trees(mine, odds)
    for tree, r in rep["cells"].items():
        log(f"  {tree:14s} cells {r['cells']:4d}, exact on every field {r['exact']:4d}; worst: "
            + ", ".join(f"{f} {w['abs_diff']} ({w['cell']})" for f, w in r["worst"].items() if w["cell"]))
    log("\nSELF-CHECK 1b: the same fit with dev_odds' per-dump role rule (rows whose dump role "
        "differs from the table's majority role move, growth recomputed from the raw dumps)")
    exact_frames, moved = dump_role_frames(frames)
    ex_src, ex_rule = mine, "table role"
    if exact_frames is None:
        log(f"  skipped: {moved}")
        rep["cells_dump_role"] = {"skipped": moved}
    else:
        mine2 = fit_cells(exact_frames, {r: np.ones(len(df), bool) for r, df in exact_frames.items()},
                          "current_w40")
        rep["cells_dump_role"] = {"moved_rows": moved, "trees": compare_trees(mine2, odds)}
        ex_src, ex_rule = mine2, "dump role"
        log(f"  moved rows (all ages, all cohorts): {moved}")
        for tree, r in rep["cells_dump_role"]["trees"].items():
            log(f"  {tree:14s} cells {r['cells']:4d}, exact on every field {r['exact']:4d}; worst: "
                + (", ".join(f"{f} {w['abs_diff']} ({w['cell']})" for f, w in r["worst"].items() if w["cell"])
                   or "none"))
    ex = []
    for role, a, pb, gb in (("H", "19", "55+", "6.5+"), ("P", "19", "50-54", "3.5+"), ("H", "22", "45-49", "2.5-4")):
        s = odds["peak"][role][a][pb][gb]
        m = ex_src["peak"][role][a][pb][gb]
        line = {"cell": f"{role}/{a}/{pb}/{gb}",
                "shipped": {k: s[k] for k in ("n", "gain_p50", "useful_share", "mlb_share", "good_share")},
                "port": {k: m[k] for k in ("n", "gain_p50", "useful_share", "mlb_share", "good_share")},
                "regular_shipped": odds["grid"][role][a][pb][gb], "regular_port": ex_src["grid"][role][a][pb][gb],
                "port_rule": ex_rule}
        ex.append(line)
        log(f"  {line['cell']}: shipped {line['shipped']} reg {line['regular_shipped']}")
        log(f"  {' ' * len(line['cell'])}  port    {line['port']} reg {line['regular_port']} ({ex_rule})")
    rep["examples"] = ex

    log("\nSELF-CHECK 2: vectorized share_at_least against dev_signals.share_at_least")
    rep["share_fn"] = check_share_fn()
    log(f"  {rep['share_fn']}")

    log("\nSELF-CHECK 3: the per-player port on the shipped dev_odds.json against the shipped "
        "dev_signals.json (TGS, BLM)")
    rep["signals"] = {}
    for lg in ("TGS", "BLM"):
        r = check_signals(odds, lg)
        rep["signals"][lg] = r
        log(f"  {lg}: {r['players']} players with a Pot grade")
        for f, v in r["fields"].items():
            log(f"    {f:14s} compared {v['compared']:5d}, exact {v['exact']:5d}, within 0.001 "
                f"{v['within_0.001']:5d}, max diff {v['max_abs_diff']}, null mismatch {v['null_mismatch']}")

    log("\nSELF-CHECK 4: the refit curve on all rows against public/data/DEV/age_curve.json")
    with open(CURVE_PATH, encoding="utf-8") as fh:
        shipped = json.load(fh)
    mc = fit_curve(pairs, np.ones(len(pairs), bool))
    rows = []
    for a in range(16, 41):
        s = shipped["curve"].get(str(a)) or {}
        m = mc["curve"].get(str(a)) or {}
        rows.append({"age": a, "mean_shipped": s.get("mean"), "mean_port": m.get("mean"),
                     "closure_shipped": s.get("closure"), "closure_port": m.get("closure"),
                     "n_shipped": s.get("n"), "n_port": m.get("n")})
    rep["curve"] = rows
    for r in rows:
        log(f"  age {r['age']:2d}: mean shipped {r['mean_shipped']!s:>8} port {r['mean_port']!s:>8}   "
            f"closure shipped {r['closure_shipped']!s:>8} port {r['closure_port']!s:>8}   "
            f"n shipped {r['n_shipped']!s:>7} port {r['n_port']!s:>7}")
    ss, ms = Shape(shipped), Shape(mc)
    rep["shape"] = [{"age": a, "G_shipped": round(ss.G(a), 4), "G_port": round(ms.G(a), 4),
                     "closable_shipped": round(ss.closable(a), 4), "closable_port": round(ms.closable(a), 4)}
                    for a in range(16, 28)]
    log("  G(a) shipped / port: " + ", ".join(f"{r['age']}: {r['G_shipped']:.3f}/{r['G_port']:.3f}"
                                               for r in rep["shape"]))
    log("  closable(a) shipped / port: " + ", ".join(
        f"{r['age']}: {r['closable_shipped']:.3f}/{r['closable_port']:.3f}" for r in rep["shape"]))
    return rep, Shape(shipped)


# ---------------------------------------------------------------- quick self-reported scores
def quick_scores(preds, frames):
    """A few held-out numbers per method, split and role (self-reported; the
    compare step does the real comparison)."""
    tgt = {}
    for role, df in frames.items():
        tgt[role] = df[["pid", "dump_year", "gain", "reach_mlb", "reach_useful", "reach_good",
                        "regular_future", "d_1", "d_2", "d_3", "d_4", "d_5"]]
    out = {}
    for method, df in preds.items():
        for (split, role), part in df.groupby(["split", "role"], observed=True):
            m = part.merge(tgt[role], on=["pid", "dump_year"], how="left")
            r = {"rows": len(m)}
            if "gain_q50" in m:
                ok = np.isfinite(m["gain_q50"])
                r["answered"] = int(ok.sum())
                r["gain_mae_q50"] = round(float(np.abs(m.loc[ok, "gain_q50"] - m.loc[ok, "gain"]).mean()), 3)
                for q in (10, 25, 50, 75, 90):
                    col = f"gain_q{q}"
                    okq = np.isfinite(m[col])
                    if okq.any():
                        r[f"cover_q{q}"] = round(float((m.loc[okq, "gain"] <= m.loc[okq, col]).mean()), 3)
                for name in PEAK_BARS:
                    p, y = m[f"p_{name}"], m[f"reach_{name}"]
                    ok = np.isfinite(p) & np.isfinite(y)
                    r[f"brier_{name}"] = round(float(((p[ok] - y[ok]) ** 2).mean()), 4)
                for col in ("p_regular", "p_regular_fut"):
                    p, y = m[col], m["regular_future"]
                    ok = np.isfinite(p) & np.isfinite(y)
                    r[f"brier_{col}"] = round(float(((p[ok] - y[ok]) ** 2).mean()), 4) if ok.any() else None
                    r[f"n_{col}"] = int(ok.sum())
            else:
                for k in HORIZONS:
                    ok = np.isfinite(m[f"d{k}"]) & np.isfinite(m[f"d_{k}"])
                    r[f"mae_d{k}"] = round(float(np.abs(m.loc[ok, f"d{k}"] - m.loc[ok, f"d_{k}"]).mean()), 3)
                    r[f"n_d{k}"] = int(ok.sum())
                ok = np.isfinite(m["d_1"])
                r["cover_d1_q25"] = round(float((m.loc[ok, "d_1"] <= m.loc[ok, "d1_q25"]).mean()), 3)
                r["cover_d1_q75"] = round(float((m.loc[ok, "d_1"] <= m.loc[ok, "d1_q75"]).mean()), 3)
            out.setdefault(method, {})[f"{split}_{role}"] = r
    return out


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="The app's current development method (dev_odds cells + dev_signals rules + "
                    "measuredPath), refit per training set on the DEV tables; writes the baseline "
                    "prediction files for the ML comparison.")
    ap.add_argument("--write", action="store_true", help="write preds/ and report/ files")
    ap.add_argument("--self-check-only", action="store_true", help="run the self-check and stop")
    ap.add_argument("--no-self-check", action="store_true",
                    help="skip the self-check against the shipped files (it is skipped on TGS anyway)")
    ap.add_argument("--splits", default="oof,time", help="comma list of oof, time (default both)")
    ap.add_argument("--basis", required=True, choices=list(C.BASES),
                    help="engine calibration of the DEV rows (one model set per league)")
    args = ap.parse_args(argv)
    C.use_basis(args.basis)
    which = {s.strip() for s in args.splits.split(",") if s.strip()}
    t0 = time.time()
    log(f"baseline: basis {args.basis}, loading the DEV tables")
    frames = {r: load_role(r) for r in C.ROLES}
    pairs = build_pairs(frames)
    log(f"  curve pairs: {len(pairs):,} consecutive-dump pairs (same kind, in an org at the earlier dump)")
    if args.basis == "BLM" and not args.no_self_check:
        check, shipped_shape = self_check(frames, pairs)
        if args.write:
            os.makedirs(C.REPORT_DIR, exist_ok=True)
            with open(os.path.join(C.REPORT_DIR, "baseline_selfcheck.json"), "w", encoding="utf-8") as fh:
                json.dump(check, fh, indent=1, default=str)
    else:
        log("  self-check skipped: " + ("the shipped files are priced on the BLM basis" if args.basis == "TGS"
                                        else "--no-self-check"))
        with open(CURVE_PATH, encoding="utf-8") as fh:
            shipped_shape = Shape(json.load(fh))
    if args.self_check_only:
        return 0

    log(f"\nFITTING per training set: {sorted(which)}")
    parts = run_splits(frames, pairs, shipped_shape, which)
    preds = {m: finish(p) for m, p in parts.items() if p}
    counts = {}
    for m, df in preds.items():
        grp = "peak" if "gain_q50" in df.columns else "path"
        c = {}
        for (split, role), part in df.groupby(["split", "role"], observed=True):
            key_col = "gain_q50" if grp == "peak" else "d1"
            c[f"{split}_{role}"] = {"rows": int(len(part)), "answered": int(np.isfinite(part[key_col]).sum())}
            if grp == "peak":
                c[f"{split}_{role}"]["basis"] = {str(k): int(v) for k, v in part["basis"].value_counts().items() if v}
            else:
                c[f"{split}_{role}"]["target"] = {str(k): int(v) for k, v in part["target"].value_counts().items() if v}
        counts[m] = {"group": grp, "counts": c}
        log(f"  {m}_{grp}: " + "; ".join(f"{k} rows {v['rows']:,} answered {v['answered']:,}" for k, v in c.items()))
    scores = quick_scores(preds, frames)
    log("\nQUICK HELD-OUT NUMBERS (self-reported)")
    for m, d in scores.items():
        for k, r in d.items():
            log(f"  {m:22s} {k:7s} {r}")
    if args.write:
        os.makedirs(C.PREDS_DIR, exist_ok=True)
        for m, df in preds.items():
            grp = counts[m]["group"]
            name = f"{m[:-len('_outside')]}_{grp}_outside" if m.endswith("_outside") else f"{m}_{grp}"
            p = os.path.join(C.PREDS_DIR, f"{name}.pkl")
            C.save_table(df, p)
            log(f"  wrote {p} ({len(df):,} rows)")
        meta = {"generated": datetime.datetime.now().isoformat(timespec="seconds"), "basis": args.basis,
                "seconds": round(time.time() - t0, 1),
                "methods": {m: counts[m] for m in preds}, "quick_scores": scores,
                "notes": ["p_regular is the app's Make it %: fit on regular_ever (any season of the "
                          "career, no censoring), NaN on rows where regular_future is unknown",
                          "p_regular_fut: the same cells with regular_future as the outcome (extra column)",
                          "gain_q10 / gain_q90: the same gain grid the app reads q25 / q50 / q75 from",
                          "current_path_shipped uses the shipped DEV curve, fit on every DEV player: leaky",
                          "path rows: ages 16-38 with present_1 == 1; peak rows: ages 16-26, in_org, peak_known",
                          "*_outside: peak rows at ages 16-26, in_org 0 (amateurs and free agents), peak_known; "
                          "the same cells (fit on in-org rows), the way the app scores such players"]}
        os.makedirs(C.REPORT_DIR, exist_ok=True)
        with open(os.path.join(C.REPORT_DIR, "baseline_metrics.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1)
        log(f"  wrote {os.path.join(C.REPORT_DIR, 'baseline_metrics.json')}")
    else:
        log("\n(dry run; add --write to write the prediction files)")
    log(f"baseline: done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
