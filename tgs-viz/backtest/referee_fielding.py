"""
referee_fielding.py - the post-season fielding referee (Phase 2 row 10).

WHAT IT DOES. For each of the seven field positions it regresses the OBSERVED
range runs of the real league on the ENGINE'S range runs for the same players:

    y_i = (made_i / chances_i - league made/chances) * league_chances_per_1200ip * out_value
    x_i = engine range channel = pm_pw(position, range rating, secondary) * T[pos] * out_value
    y_i = a + b * x_i         chance-weighted least squares (weight = chances_i)

b = 1 means the engine's range curve moves runs exactly as fast as the real
league did. The engine channel is the plays-made term of hitters.py compute():
pmaa * H38 (infield) or pmaa * H39 (outfield), with pmaa from the monotone
curves in calib/<LG>/fielding_curves.json (the live path) or, with
linear=True, from the sheet's linear Data Points cells (the pre-D3 path). The
E%, DP and arm terms are NOT in the channel; they are separate regressions.

WHY. The only fielding check the engine has is fielding_curves_fit.py's
sim-vs-engine +/-3 run gate: it compares the curve to the CLONE SIMS it was
fitted on. AUDIT.md 4.1 names the real-outcome loop as missing. This is that
loop for fielding: a real league season, scored against the curves as shipped.

OUT-VALUE INVARIANCE. x and y are both multiplied by the same out value, so the
slope b does not depend on it. This tool cannot test H38/H39 (that is
docs/phase2/out_values.md); it tests the SHAPE and SLOPE of the range curve.

STANDARD ERRORS. The larger of three, per coefficient: HC1 (heteroskedasticity
robust, n/(n-k) scaled), a cluster bootstrap over players (B resamples), and
the binomial floor (independent sampling noise in each player's made/chances).
Never smaller than the binomial floor.

GOVERNANCE (two-sample rule, carried over from the dashboard's C4). A curve is
grounds to move only when the same departure from b = 1 shows up in two
samples (two seasons, or two leagues). One sample = "watch", never "move".
two_sample_verdict() applies it; it proposes no adjustment factor.

SAMPLES (--sample, repeatable):
    live                      calib/<LG>/metadata_inputs (Fielding_Data + Fielding_Ratings,
                              the season the live curves' offsets were transported to)
    actuals:YEAR[:PULL_ID]    backtest/actuals/<LG>/YEAR/fielding.csv (OOTP's per-player
                              season stats; opps_0..5 / opps_made_0..5). Ratings come from
                              ratings_history.db pull PULL_ID (default --pull: pick the pull
                              taken right after that season ended, see pull_game_dates_<LG>.json)
                              and heights from the live Fielding_Ratings (the DB stores none)
    dir:PATH                  a folder with fielding_data_<pos>.csv + fielding_ratings.csv
                              (the dashboard's metadata layout, e.g. SSB 2043)

--basis LG picks the engine calibration (curves + Data Points) that prices the
sample. A league without its own calibration is priced on another's (SSB and RG
are priced on BLM's in this fork): run `--sample dir:<SSB 2043> --basis BLM`.

Usage (python must have pandas and numpy):
    python tgs-viz/backtest/referee_fielding.py --league BLM
    python tgs-viz/backtest/referee_fielding.py --league BLM --sample live --sample actuals:2057:4
    python tgs-viz/backtest/referee_fielding.py --league SSB --basis BLM --sample dir:/path/SSB/metadata/2043

Read-only. Writes nothing except the optional --out JSON. No network.
"""
import argparse
import json
import os
import re
import sys
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))              # tgs-viz/backtest
VIZ = os.path.dirname(HERE)                                      # tgs-viz
REPO = os.path.dirname(VIZ)
ENGINE = os.path.join(VIZ, "engine")

POSITIONS = ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]
IF_POS = {"1B", "2B", "3B", "SS"}
CODE2POS = {3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
FILE_TAG = {p: p.lower() for p in POSITIONS}
BUCKETS = ["R", "L", "E", "U", "Z", "I"]                         # BIZ-I (impossible) is never made
TOT_COLS = [f"BIZ-{b}" for b in BUCKETS]
MADE_COLS = [f"BIZ-{b}m" for b in BUCKETS[:-1]]
STD_IP = 1200.0                                                  # 'Standarized IP per POS' (engine T cells are per 1200 IP)
MIN_CHANCES = 20
ELITE_RATING, ELITE_IP = 68.0, 300.0
N_BOOT, SEED = 4000, 20261003

# position -> (T cell: chances per 1200 IP, out-value cell)
T_CELL = {"1B": "T5", "2B": "T8", "3B": "T12", "SS": "T15", "LF": "T18", "CF": "T22", "RF": "T26"}
OUT_CELL = {p: ("H38" if p in IF_POS else "H39") for p in POSITIONS}
# The sheet's LINEAR pmaa cells (hitters.py compute, the non-curve branch):
#   ((RNG - rng_anchor) * rng_slope + (X2 - x2_anchor) * x2_slope + const) * T
# position -> (rng anchor, rng slope, x2 anchor, x2 slope, const)
LINEAR_CELLS = {
    "1B": ("P9", "L9", "Q9", "M9", "K9"),
    "2B": ("P13", "L13", "Q13", "M13", "K13"),
    "3B": ("P19", "L19", "Q19", "M19", "K19"),
    "SS": ("P23", "L23", "Q23", "M23", "K23"),
    "LF": ("P27", "L27", None, None, "K27"),
    "CF": ("P33", "L33", None, None, "K33"),
    "RF": ("P39", "L39", None, None, "K39"),
}
PRIMARY = {p: ("IFR" if p in IF_POS else "OFR") for p in POSITIONS}
SECONDARY = {"1B": "ht_cm", "2B": "IFA", "3B": "IFA", "SS": "IFA", "LF": None, "CF": None, "RF": None}


# ----------------------------------------------------------------------------
# parsing helpers
# ----------------------------------------------------------------------------

def ip_thirds(series: pd.Series) -> pd.Series:
    """OOTP x.y innings notation (y = outs, 0-2) -> true innings (123.2 -> 123.667)."""
    ip = pd.to_numeric(series, errors="coerce")
    whole = np.floor(ip)
    return whole + ((ip - whole) * 10).round() / 3.0


def height_cm(ht: object) -> float:
    """5' 11\" -> 5*30.48 + 11*2.54, the engine's 'HT Sort' scale. Also accepts the
    dashboard export's 6' 5' spelling. NaN when unparseable."""
    m = re.match(r"\s*(\d+)\s*'\s*(\d+)", str(ht))
    if not m:
        return float("nan")
    return int(m.group(1)) * 30.48 + int(m.group(2)) * 2.54


def _num(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    return out


def observed_from_buckets(df: pd.DataFrame, id_col: str = "ID", ip_col: str = "IP") -> pd.DataFrame:
    """Per-player table (id, ipc, tot, made) from the StatsPlus BIZ-* bucket columns.
    tot = Plays A (all six buckets, impossible included); made = Plays M (the five
    makeable buckets). Same definition as metadata_calibrate.fielding_tables."""
    d = _num(df, TOT_COLS + MADE_COLS)
    out = pd.DataFrame({
        "id": d[id_col].astype(str).str.strip(),
        "ipc": ip_thirds(d[ip_col]),
        "tot": d[TOT_COLS].sum(axis=1),
        "made": d[MADE_COLS].sum(axis=1),
    })
    return out[out["ipc"] > 0].reset_index(drop=True)


# ----------------------------------------------------------------------------
# loaders -> (observed: {pos: DataFrame}, ratings: DataFrame indexed by id)
# ----------------------------------------------------------------------------

def _ratings_frame(df: pd.DataFrame, id_col: str, rng_if: str, arm_if: str, rng_of: str,
                   ht_col: Optional[str]) -> pd.DataFrame:
    r = pd.DataFrame({
        "id": df[id_col].astype(str).str.strip(),
        "IFR": pd.to_numeric(df[rng_if], errors="coerce"),
        "IFA": pd.to_numeric(df[arm_if], errors="coerce"),
        "OFR": pd.to_numeric(df[rng_of], errors="coerce"),
    })
    r["ht_cm"] = df[ht_col].map(height_cm) if ht_col and ht_col in df.columns else np.nan
    return r.drop_duplicates("id").set_index("id")


def load_live_inputs(league: str) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, str]:
    """calib/<LG>/metadata_inputs through the engine's own loaders (metadata_calibrate)."""
    if ENGINE not in sys.path:
        sys.path.insert(0, ENGINE)
    import metadata_calibrate as M  # stdlib only
    d = os.path.join(ENGINE, "calib", league, "metadata_inputs")
    if not os.path.isdir(d):
        raise FileNotFoundError(f"no metadata_inputs for {league}: {d}")
    tabs = M.load_fielding(os.path.join(d, "Fielding_Data.csv"))
    obs = {p: observed_from_buckets(pd.DataFrame(tabs[p])) for p in POSITIONS}
    fr = pd.DataFrame(M.load_single(os.path.join(d, "Fielding_Ratings.csv")))
    ratings = _ratings_frame(fr, "ID", "IF RNG", "IF ARM", "OF RNG", "HT")
    return obs, ratings, M.inputs_label(d, ("Fielding_Data.csv", "Fielding_Ratings.csv"))


def load_actuals_observed(csv_path: str, year: Optional[int] = None) -> Dict[str, pd.DataFrame]:
    """OOTP's per-player-season fielding stats (backtest/actuals/<LG>/<YEAR>/fielding.csv).
    One row per (player, position); a traded player may have two, so they are summed.
    tot = opps_0..5 (impossible bucket included), made = opps_made_0..5, innings =
    ip + ipf/3 (ipf = outs 0-2). MLB rows only when a level column exists."""
    f = pd.read_csv(csv_path)
    if "level_id" in f.columns:
        f = f[f["level_id"] == 1]
    if year is not None and "year" in f.columns:
        f = f[f["year"] == year]
    f = f.assign(
        ipc=f["ip"] + f.get("ipf", 0) / 3.0,
        tot=f[[f"opps_{i}" for i in range(6)]].sum(axis=1),
        made=f[[f"opps_made_{i}" for i in range(6)]].sum(axis=1),
        id=f["player_id"].astype(str),
    )
    out = {}
    for code, pos in CODE2POS.items():
        g = f[f["position"] == code].groupby("id", as_index=False)[["ipc", "tot", "made"]].sum()
        out[pos] = g[g["ipc"] > 0].reset_index(drop=True)
    return out


def load_db_ratings(db_path: str, league: str, pull_id: int, heights: Optional[pd.DataFrame] = None
                    ) -> pd.DataFrame:
    """Range / arm ratings of one ratings_history.db pull (opened read-only). The DB
    stores no height; pass `heights` (a ratings frame with ht_cm) to fill it by id."""
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        df = pd.read_sql(
            "select player_id, c_IF_RNG, c_IF_ARM, c_OF_RNG from ratings r join pulls p "
            "on p.pull_id = r.pull_id where r.pull_id = ? and p.league = ?",
            con, params=(int(pull_id), league))
    finally:
        con.close()
    if df.empty:
        raise ValueError(f"pull {pull_id} of {league} has no ratings rows in {db_path}")
    r = _ratings_frame(df, "player_id", "c_IF_RNG", "c_IF_ARM", "c_OF_RNG", None)
    if heights is not None:
        r["ht_cm"] = heights["ht_cm"].reindex(r.index)
    return r


def load_dashboard_dir(path: str) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    """The dashboard's metadata layout: fielding_data_<pos>.csv per position (one header
    row, StatsPlus columns) + fielding_ratings.csv."""
    obs = {}
    for p in POSITIONS:
        f = os.path.join(path, f"fielding_data_{FILE_TAG[p]}.csv")
        if not os.path.exists(f):
            raise FileNotFoundError(f)
        obs[p] = observed_from_buckets(pd.read_csv(f))
    fr = pd.read_csv(os.path.join(path, "fielding_ratings.csv"))
    return obs, _ratings_frame(fr, "ID", "IF RNG", "IF ARM", "OF RNG", "HT")


# ----------------------------------------------------------------------------
# the engine channel
# ----------------------------------------------------------------------------

def load_calibration(basis: str) -> Tuple[Optional[dict], Dict[str, float]]:
    """(fielding_curves.json or None, Data Points {cell: value}) for a calibration.
    Data Points come from the same place the live path reads them (The Sheet
    Hitters.xlsx via hitters.scan_consts); engine/extracted/<LG>_hitters_datapoints.json
    is the fallback when the workbook is not on disk."""
    cpath = os.path.join(ENGINE, "calib", basis, "fielding_curves.json")
    curves = json.load(open(cpath, encoding="utf-8")) if os.path.exists(cpath) else None
    wb = os.path.join(REPO, f"The Sheets {basis}", "The Sheet Hitters.xlsx")
    if os.path.exists(wb):
        if ENGINE not in sys.path:
            sys.path.insert(0, ENGINE)
        import hitters as H
        dp = {k: float(v) for k, v in H.scan_consts(wb)[0].items() if isinstance(v, (int, float))}
    else:
        dp = {k: float(v) for k, v in json.load(open(
            os.path.join(ENGINE, "extracted", f"{basis}_hitters_datapoints.json"), encoding="utf-8")).items()
            if isinstance(v, (int, float))}
    return curves, dp


def interp_knots(knots: Sequence[Sequence[float]], r: np.ndarray) -> np.ndarray:
    """hitters._interp_knots, vectorised: piecewise-linear through the knots, flat
    beyond both ends. (np.interp has the same semantics; a test pins the equality.)"""
    k = np.asarray(knots, float)
    return np.interp(np.asarray(r, float), k[:, 0], k[:, 1])


def curve_rate(pos: str, ratings: pd.DataFrame, curves: Mapping) -> np.ndarray:
    """hitters.compute pm_pw(): interp(knots, rng) - offset + x2 * m2."""
    c = curves["positions"][pos]
    v = interp_knots(c["knots"], ratings[PRIMARY[pos]].to_numpy(float)) - c["offset"]
    sec = SECONDARY[pos]
    if c.get("m2") is not None and sec is not None:
        v = v + ratings[sec].to_numpy(float) * c["m2"]
    return v


def linear_rate(pos: str, ratings: pd.DataFrame, dp: Mapping[str, float]) -> np.ndarray:
    """The sheet's linear branch of hitters.compute (curves absent)."""
    pr, lr, qr, mr, kr = LINEAR_CELLS[pos]
    v = (ratings[PRIMARY[pos]].to_numpy(float) - dp[pr]) * dp[lr] + dp[kr]
    if qr is not None:
        v = v + (ratings[SECONDARY[pos]].to_numpy(float) - dp[qr]) * dp[mr]
    return v


def model_range_runs(pos: str, ratings: pd.DataFrame, curves: Optional[Mapping],
                     dp: Mapping[str, float], linear: bool = False) -> np.ndarray:
    """Engine range channel in runs per season-slot: rate * T[pos] * out value."""
    use_curve = (curves is not None) and (not linear) and pos in curves.get("positions", {})
    rate = curve_rate(pos, ratings, curves) if use_curve else linear_rate(pos, ratings, dp)
    return rate * dp[T_CELL[pos]] * dp[OUT_CELL[pos]]


# ----------------------------------------------------------------------------
# regression core
# ----------------------------------------------------------------------------

def wls(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> Tuple[float, float]:
    """Weighted simple regression y = a + b x -> (a, b)."""
    sw = w.sum()
    mx, my = (w * x).sum() / sw, (w * y).sum() / sw
    b = (w * (x - mx) * (y - my)).sum() / (w * (x - mx) ** 2).sum()
    return float(my - b * mx), float(b)


def hc1_se(x: np.ndarray, y: np.ndarray, w: np.ndarray, beta: Tuple[float, float]) -> np.ndarray:
    """HC1 sandwich SE for (a, b): (X'WX)^-1 X'W diag(e^2) W X (X'WX)^-1 * n/(n-2)."""
    X = np.column_stack([np.ones_like(x), x])
    n, k = X.shape
    e = y - X @ np.asarray(beta)
    A = np.linalg.inv(X.T @ (X * w[:, None]))
    G = X * (w * e)[:, None]
    return np.sqrt(np.diag(A @ (G.T @ G) @ A * n / max(n - k, 1)))


def binomial_floor_se(x: np.ndarray, w: np.ndarray, var_y: np.ndarray) -> np.ndarray:
    """SE implied by independent binomial sampling noise in each y_i alone."""
    X = np.column_stack([np.ones_like(x), x])
    A = np.linalg.inv(X.T @ (X * w[:, None]))
    meat = (X * (w ** 2 * var_y)[:, None]).T @ X
    return np.sqrt(np.diag(A @ meat @ A))


def cluster_boot_se(x: np.ndarray, y: np.ndarray, w: np.ndarray, clusters: np.ndarray,
                    n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """Bootstrap SE for (a, b), resampling whole clusters (players) with replacement.
    Vectorised: each resample is a (B, n) integer multiplicity matrix on the rows, and
    the weighted simple-regression normal equations are evaluated for all B at once."""
    codes, uniq = pd.factorize(clusters)
    nc = len(uniq)
    rs = np.random.default_rng(seed)
    pick = rs.integers(0, nc, size=(n_boot, nc))
    counts = np.bincount((pick + np.arange(n_boot)[:, None] * nc).ravel(),
                         minlength=n_boot * nc).reshape(n_boot, nc)
    W = counts[:, codes] * w[None, :]                                  # (B, n)
    sw = W.sum(axis=1)
    sx, sy = W @ x, W @ y
    sxx, sxy = W @ (x * x), W @ (x * y)
    den = sw * sxx - sx ** 2
    with np.errstate(divide="ignore", invalid="ignore"):
        b = (sw * sxy - sx * sy) / den
        a = (sy - b * sx) / sw
    ok = np.isfinite(a) & np.isfinite(b) & (den > 1e-12)
    if ok.sum() < 2:
        return np.array([np.nan, np.nan])
    return np.array([np.std(a[ok], ddof=1), np.std(b[ok], ddof=1)])


def fit_position(x: np.ndarray, y: np.ndarray, w: np.ndarray, var_y: np.ndarray,
                 clusters: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Slope/intercept with the max-of-three SE rule, weighted R2, weighted means."""
    a, b = wls(x, y, w)
    se = np.maximum.reduce([hc1_se(x, y, w, (a, b)),
                            np.nan_to_num(cluster_boot_se(x, y, w, clusters, n_boot, seed)),
                            binomial_floor_se(x, w, var_y)])
    ww = w / w.sum()
    ybar = float(ww @ y)
    sst = float(np.sum(w * (y - ybar) ** 2))
    r2 = 1.0 - float(np.sum(w * (y - a - b * x) ** 2)) / sst
    # unfitted skill: how much of the observed spread the channel explains with NO refit
    # (both centred on their chance-weighted means). Negative = worse than no fielding term.
    xbar = float(ww @ x)
    skill = 1.0 - float(np.sum(w * ((y - ybar) - (x - xbar)) ** 2)) / sst
    return dict(intercept=a, se_intercept=float(se[0]), slope=b, se_slope=float(se[1]),
                r2w=r2, skill_unfitted=skill, mean_model=xbar, mean_obs=ybar)


# ----------------------------------------------------------------------------
# one position
# ----------------------------------------------------------------------------

def referee_position(pos: str, obs: pd.DataFrame, ratings: pd.DataFrame, curves: Optional[Mapping],
                     dp: Mapping[str, float], min_chances: int = MIN_CHANCES, linear: bool = False,
                     n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Referee one position. `obs` has id, ipc, tot, made (one row per player)."""
    out_val = dp[OUT_CELL[pos]]
    lg_p = obs["made"].sum() / obs["tot"].sum()
    pa_obs = obs["tot"].sum() / obs["ipc"].sum() * STD_IP              # league chances per 1200 IP this sample
    d = obs.merge(ratings, left_on="id", right_index=True, how="left")
    need = [PRIMARY[pos]] + ([SECONDARY[pos]] if SECONDARY[pos] else [])
    pool = d[d["tot"] >= min_chances]
    d = pool[pool[need].notna().all(axis=1)].copy()
    n_unmatched = int(len(pool) - len(d))

    d["model"] = model_range_runs(pos, d, curves, dp, linear=linear)
    p = d["made"] / d["tot"]
    d["obs"] = (p - lg_p) * pa_obs * out_val
    pt = (d["made"] + 0.5) / (d["tot"] + 1.0)                          # shrunk p for the variance only
    d["var_obs"] = pt * (1 - pt) / d["tot"] * (pa_obs * out_val) ** 2

    x, y, w = d["model"].to_numpy(float), d["obs"].to_numpy(float), d["tot"].to_numpy(float)
    res = fit_position(x, y, w, d["var_obs"].to_numpy(float), d["id"].to_numpy(), n_boot, seed)
    # Pearson dispersion of the fitted line's residuals against the binomial variance: 1.0 means
    # the only scatter is sampling noise; above 1 is real talent the rating does not explain.
    resid = y - res["intercept"] - res["slope"] * x
    phi = float(np.sum(resid ** 2 / d["var_obs"].to_numpy(float)) / max(len(d) - 2, 1))

    # rung table: where on the rating axis the channel departs from the league
    d["rung"] = (d[PRIMARY[pos]] / 5.0).round() * 5.0
    rungs = []
    for r, g in d.groupby("rung"):
        gw = g["tot"].to_numpy(float)
        sw = gw.sum()
        mo, mm = float(gw @ g["obs"].to_numpy() / sw), float(gw @ g["model"].to_numpy() / sw)
        # centred on the fitted line's intercept: residual of the channel at this rung
        se_r = float(np.sqrt(max(phi, 1.0) * np.sum(gw ** 2 * g["var_obs"].to_numpy())) / sw)
        rungs.append(dict(rung=float(r), n=int(len(g)), chances=float(sw), obs=mo, model=mm,
                          resid=mo - (mm - res["mean_model"] + res["mean_obs"]), se=se_r))

    e = d[(d[PRIMARY[pos]] >= ELITE_RATING) & (d["ipc"] >= ELITE_IP)]
    if len(e):
        ew = e["ipc"].to_numpy(float) / e["ipc"].sum()
        elite = dict(n=int(len(e)), model=float(ew @ e["model"].to_numpy()), obs=float(ew @ e["obs"].to_numpy()))
    else:
        elite = dict(n=0, model=None, obs=None)

    return dict(pos=pos, n=int(len(d)), n_unmatched=n_unmatched, chances=float(w.sum()),
                lg_pm=float(lg_p), pa_obs=float(pa_obs), pa_model=float(dp[T_CELL[pos]]),
                out_value=float(out_val), dispersion=phi, rungs=rungs, elite=elite, **res)


def referee(obs: Mapping[str, pd.DataFrame], ratings: pd.DataFrame, curves: Optional[Mapping],
            dp: Mapping[str, float], min_chances: int = MIN_CHANCES, linear: bool = False,
            n_boot: int = N_BOOT, seed: int = SEED) -> List[dict]:
    return [referee_position(p, obs[p], ratings, curves, dp, min_chances, linear, n_boot, seed)
            for p in POSITIONS if p in obs]


# ----------------------------------------------------------------------------
# two-sample governance
# ----------------------------------------------------------------------------

def two_sample_verdict(a: Mapping, b: Mapping, z_bar: float = 2.0) -> dict:
    """Apply the two-sample rule to one position's slope in two samples.
    z_i = (slope_i - 1) / se_i. 'replicated' = both |z| > z_bar with the same sign;
    'watch' = exactly one sample beyond z_bar, or both beyond with opposite signs;
    'consistent-with-1' = neither. pooled = inverse-variance mean of the two slopes.
    No adjustment factor is proposed: that is a decision, not a statistic."""
    z = [(s["slope"] - 1.0) / s["se_slope"] for s in (a, b)]
    w = np.array([1.0 / a["se_slope"] ** 2, 1.0 / b["se_slope"] ** 2])
    pooled = float((w * np.array([a["slope"], b["slope"]])).sum() / w.sum())
    se_pooled = float(1.0 / np.sqrt(w.sum()))
    beyond = [abs(v) > z_bar for v in z]
    if all(beyond) and np.sign(z[0]) == np.sign(z[1]):
        verdict = "replicated"
    elif any(beyond):
        verdict = "watch"
    else:
        verdict = "consistent-with-1"
    return dict(pos=a["pos"], z=[float(v) for v in z], pooled_slope=pooled, se_pooled=se_pooled,
                z_pooled=float((pooled - 1.0) / se_pooled), verdict=verdict)


def flow_check(rows: Sequence[Mapping], tol: float = 0.10) -> List[Tuple[str, float]]:
    """Positions whose observed chances per 1200 IP differ from the engine's T cell by more
    than `tol` (as a ratio observed / engine). A sample like that was played under a
    different chance-flow regime than the one the curves and T cells were calibrated on
    (another game engine, or a rule change): its slopes judge a different game, so it is not
    a clean second sample for these curves. Returns [(pos, ratio), ...]."""
    return [(r["pos"], r["pa_obs"] / r["pa_model"]) for r in rows
            if abs(r["pa_obs"] / r["pa_model"] - 1.0) > tol]


# ----------------------------------------------------------------------------
# printing + CLI
# ----------------------------------------------------------------------------

def format_report(title: str, rows: Sequence[Mapping], min_chances: int = MIN_CHANCES) -> str:
    lines = [f"\nFIELDING REFEREE - {title} - range channel, observed = made/chances vs league, "
             f"sample: >= {min_chances} chances",
             f"{'pos':<4}{'n':>4}{'chances':>9} | {'slope':>7}{'+/-':>7}{'z(vs1)':>7}"
             f"{'intercept':>10}{'+/-':>7}{'R2w':>7}{'skill':>7}{'disp':>6} | {'eliteN':>7}{'mdl':>8}{'obs':>8}"]
    for r in rows:
        e = r["elite"]
        em = f"{e['model']:>+8.1f}" if e["n"] else f"{'-':>8}"
        eo = f"{e['obs']:>+8.1f}" if e["n"] else f"{'-':>8}"
        z = (r["slope"] - 1.0) / r["se_slope"]
        lines.append(f"{r['pos']:<4}{r['n']:>4}{r['chances']:>9.0f} | {r['slope']:>7.3f}{r['se_slope']:>7.3f}"
                     f"{z:>7.1f}{r['intercept']:>+10.2f}{r['se_intercept']:>7.2f}{r['r2w']:>7.3f}"
                     f"{r['skill_unfitted']:>7.2f}{r['dispersion']:>6.1f} | {e['n']:>7}{em}{eo}")
    return "\n".join(lines)


def format_rungs(rows: Sequence[Mapping]) -> str:
    lines = ["\nrung residuals (observed - channel, runs per slot; * = beyond 2 SE of a rung with n >= 3; SE scaled by sqrt(dispersion))"]
    for r in rows:
        cells = []
        for g in r["rungs"]:
            star = "*" if g["n"] >= 3 and g["se"] > 0 and abs(g["resid"]) > 2 * g["se"] else " "
            cells.append(f"{g['rung']:.0f}:{g['resid']:+.1f}{star}(n{g['n']})")
        lines.append(f"  {r['pos']:<3} " + "  ".join(cells))
    return "\n".join(lines)


def run_sample(spec: str, league: str, basis: str, curves: Optional[Mapping], dp: Mapping[str, float],
               pull: int, min_chances: int, linear: bool, n_boot: int, db: Optional[str]
               ) -> Tuple[str, List[dict]]:
    """Load one --sample spec and referee it. Returns (label, per-position rows)."""
    kind, _, rest = spec.partition(":")
    if kind == "live":
        obs, ratings, label = load_live_inputs(league)
        label = f"live {league} ({label})"
    elif kind == "actuals":
        parts = rest.split(":")
        year = int(parts[0])
        pid = int(parts[1]) if len(parts) > 1 else pull
        _, live_ratings, _ = load_live_inputs(league)                  # heights only
        obs = load_actuals_observed(os.path.join(VIZ, "backtest", "actuals", league, str(year), "fielding.csv"),
                                    year)
        ratings = load_db_ratings(db or _default_db(), league, pid, heights=live_ratings)
        label = f"actuals {league} {year}, ratings pull {pid}"
    elif kind == "dir":
        obs, ratings = load_dashboard_dir(rest)
        label = f"dir {rest}"
    else:
        raise SystemExit(f"unknown --sample {spec!r} (live | actuals:YEAR[:PULL] | dir:PATH)")
    rows = referee(obs, ratings, curves, dp, min_chances, linear, n_boot)
    label += f" | priced on {basis} {'LINEAR sheet cells' if linear or curves is None else 'piecewise curves'}"
    return label, rows


def _default_db() -> str:
    try:
        import pull_order as PO
        return PO.DB_PATH
    except ImportError:
        return os.path.join(HERE, "ratings_history.db")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--league", default="BLM", help="league whose samples are read (default BLM)")
    ap.add_argument("--basis", default=None, help="calibration that prices the sample (default: --league)")
    ap.add_argument("--sample", action="append", help="live | actuals:YEAR[:PULL] | dir:PATH (repeatable)")
    ap.add_argument("--pull", type=int, default=4, help="default ratings pull id for actuals samples (BLM 2057: 4 = 2057-10-13)")
    ap.add_argument("--db", default=None, help="ratings_history.db (default: pull_order.DB_PATH)")
    ap.add_argument("--min-chances", type=int, default=MIN_CHANCES)
    ap.add_argument("--linear", action="store_true", help="price with the sheet's linear cells instead of the curves")
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--out", default=None, help="write a JSON report here")
    a = ap.parse_args(argv)

    basis = a.basis or a.league
    curves, dp = load_calibration(basis)
    samples = a.sample or ["live", "actuals:2057"]
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    report = dict(league=a.league, basis=basis, linear=bool(a.linear), samples=[])
    for s in samples:
        label, rows = run_sample(s, a.league, basis, curves, dp, a.pull, a.min_chances, a.linear,
                                 a.n_boot, a.db)
        print(format_report(label, rows, a.min_chances))
        print(format_rungs(rows))
        off = flow_check(rows)
        if off:
            print("\nCHANCE-FLOW REGIME WARNING: observed chances per 1200 IP differ from the engine's T cells by >10% at "
                  + ", ".join(f"{p} x{q:.2f}" for p, q in off)
                  + ".\nThis sample was played under a different flow than the one the curves were calibrated on;"
                  "\nits slopes judge a different game and are not clean evidence about these curves.")
        report["samples"].append(dict(spec=s, label=label, positions=rows, flow_off=off))
    if len(report["samples"]) >= 2:
        s0, s1 = report["samples"][0]["positions"], report["samples"][1]["positions"]
        verdicts = [two_sample_verdict(p, q) for p, q in zip(s0, s1) if p["pos"] == q["pos"]]
        report["governance"] = verdicts
        print(f"\nTWO-SAMPLE GOVERNANCE - {report['samples'][0]['spec']} vs {report['samples'][1]['spec']}")
        for v in verdicts:
            print(f"  {v['pos']:<3} z=({v['z'][0]:+.1f}, {v['z'][1]:+.1f})  pooled slope {v['pooled_slope']:.3f} "
                  f"+/- {v['se_pooled']:.3f} (z {v['z_pooled']:+.1f})  -> {v['verdict']}")
        print("A curve moves only on 'replicated'; 'watch' is a flag, not a change. No factor is proposed here.")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, default=float)
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
