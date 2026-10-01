"""
compare.py - score the machine-learning models against the app's current
method on the same held-out DEV rows, and write the verdict.

One model set per league (2026-09-24): --basis TGS | BLM (required) reads the
DEV tables priced with that league's engine calibration and the predictions of
that basis, and writes report/<basis>/report.json and report.md. --splits
picks the splits (default oof,time); the decision rule then needs every split
that ran. User, 2026-09-24: "is there any way you can make a machine learning
model to help with figuring out this dev stuff".

Inputs (all under .dev_cache/ml, <B> = the basis):
  data/dev_H_<B>.pkl, data/dev_P_<B>.pkl  truth: peak, gain, reach_*, regular_future,
                                       d_1..d_5, plus age, Pot, now_WAA
  preds/<B>/ml_peak.pkl                ML peak model (peak.py)
  preds/<B>/current_peak.pkl           the app's cells, first-20 cohort, realized only
  preds/<B>/current_all_peak.pkl       the same cells on every finished career
  preds/<B>/current_w40_peak.pkl       the app's exact 2025-2040 cohort (extra)
  preds/<B>/ml_path.pkl                ML year-by-year model (path.py)
  preds/<B>/current_path_path.pkl      the app's measuredPath, curve refit per split
  preds/<B>/age_mean_path.pkl          plain role x age mean change
  preds/<B>/*_peak_outside.pkl         optional: the same peak methods on rows
                                       outside an org (amateurs, free agents;
                                       fix 6), scored in their own section
  report/<B>/peak_importance_<role>.json, report/<B>/path_importance.json

Every method is scored on exactly the same rows. The main view keeps the rows
every method answers (a NaN is that method's coverage gap, counted). The
"filled" view fills a method's NaN with its own fallback: the mean of that
method's answers for the same split, fold, role and age.

Metrics, per split (oof, time), role (H, P), and subset (all, prospects =
Pot >= 45 at ages 17-22, ages 16-19, 20-22, 23-26):
  peak     MAE of now + gain_q50 against the peak, pinball loss at q25 / q50 /
           q75, share of true gains inside q25-q75 (and q10-q90)
  chances  p_mlb / p_useful / p_good on rows below the bar line (now < bar -
           0.05; rows at or above it read 1.0 for every method), p_regular on
           rows where regular_future is known: log loss (probabilities clipped
           to [eps, 1 - eps]), Brier, AUC, 10-bin calibration, and the "top 10
           percent" view at ages 18, 19 and 20
  path     MAE of d1, d3, d5 by age band 16-22, 23-27, 28-32, 33-38; d1 q25-q75
           coverage
Uncertainty: a bootstrap over PLAYERS (every row of a drawn player comes along)
gives a 95% interval for every method difference.

Decision rule (applied mechanically, overall subset, main view):
  ML wins a target when its main metric (peak: MAE of the median; chances: log
  loss; path: MAE of d1 and of d3) is lower than BOTH current and current_all
  (for the path: current_path and age_mean) with the 95% interval of each
  difference below zero, on BOTH the oof and the time split.
  "current wins" when ML is worse than current with the interval above zero on
  both splits. Otherwise "no clear win".

Outputs:
  .dev_cache/ml/report/report.json
  .dev_cache/ml/report/report.md

Run with Python 3.14:
  python compare.py                 full run (about 10 minutes)
  python compare.py --quick         20% of players, 60 resamples (smoke test)
"""
import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

KEY = ["pid", "dump_year", "split"]
SPLITS = ("oof", "time")            # main() narrows this to --splits

PEAK_METHODS = {            # method -> prediction file stem
    "ml": "ml_peak",
    "current": "current_peak",
    "current_all": "current_all_peak",
    "current_w40": "current_w40_peak",
}
PATH_METHODS = {
    "ml": "ml_path",
    "current_path": "current_path_path",
    "age_mean": "age_mean_path",
}
CHANCES = ("p_mlb", "p_useful", "p_good", "p_regular")
CHANCE_TRUTH = {"p_mlb": "reach_mlb", "p_useful": "reach_useful", "p_good": "reach_good",
                "p_regular": "regular_future"}
CHANCE_BAR = {"p_mlb": C.PEAK_BARS["mlb"], "p_useful": C.PEAK_BARS["useful"],
              "p_good": C.PEAK_BARS["good"], "p_regular": None}
BAR_TOL = 0.05

# The baseline file carries two regular-season columns. p_regular is the app's
# Make it % (fit on regular_ever: any season, no censoring). p_regular_fut is the
# same cells fit on regular_future, the target every method is scored on. The
# decision uses p_regular_fut (like for like); the app's own column is scored
# as the extra method "current_makeit".
def chance_col(method, target):
    if target == "p_regular" and method in ("current", "current_all", "current_w40"):
        return "p_regular_fut"
    return target


PEAK_SUBSETS = ("all", "prospects", "age16_19", "age20_22", "age23_26")
OUTSIDE_SUBSETS = ("all", "amateur", "free_agent", "age16_19", "age20_22", "age23_26")
PATH_BANDS = (("all", 16, 38), ("16-22", 16, 22), ("23-27", 23, 27), ("28-32", 28, 32), ("33-38", 33, 38))
PATH_H = (1, 3, 5)

MAIN_BASE = {"peak": ("current", "current_all"), "path": ("current_path", "age_mean")}
DIFFS_PEAK = [("ml", "current"), ("ml", "current_all"), ("current_all", "current"), ("ml", "current_w40")]
DIFFS_PATH = [("ml", "current_path"), ("ml", "age_mean"), ("age_mean", "current_path")]


def log(msg=""):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------- loading
TRUTH_COLS = ["pid", "dump_year", "age", "pot", "now_waa", "peak", "gain", "reach_mlb", "reach_useful",
              "reach_good", "regular_future", "d_1", "d_3", "d_5", "present_1", "in_org"]


def load_truth(role):
    df = pd.read_pickle(C.dev_table(role))
    out = df[TRUTH_COLS].copy()
    out["amateur"] = C.amateur_flag(df)
    del df
    for c in out.columns:
        if c not in ("pid", "dump_year"):
            out[c] = out[c].astype("float64")
    return out


def load_pred(stem, role):
    df = pd.read_pickle(os.path.join(C.PREDS_DIR, stem + ".pkl"))
    df = df[df["role"].astype(str) == role].copy()
    df["split"] = df["split"].astype(str)
    return df


def rng_for(seed, *parts):
    """Seeded generator that does not depend on Python's per-run string hash."""
    h = int(hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)
    return np.random.default_rng([seed, h])


# ----------------------------------------------------------------- stats helpers
def clip_p(p, eps):
    return np.clip(p, eps, 1.0 - eps)


def logloss_rows(p, y, eps):
    q = clip_p(p, eps)
    return -(y * np.log(q) + (1.0 - y) * np.log(1.0 - q))


def pinball_rows(q, y, tau):
    e = y - q
    return np.maximum(tau * e, (tau - 1.0) * e)


class AUC:
    """Weighted AUC that reuses one sort per score vector (fast for bootstraps)."""

    def __init__(self, score, y):
        self.order = np.argsort(score, kind="mergesort")
        s = score[self.order]
        self.y = y[self.order].astype(np.float64)
        self.starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])

    def __call__(self, w=None):
        ws = np.ones(len(self.y)) if w is None else w[self.order]
        pos = np.add.reduceat(ws * self.y, self.starts)
        neg = np.add.reduceat(ws * (1.0 - self.y), self.starts)
        below = np.cumsum(neg) - neg
        P, N = pos.sum(), neg.sum()
        if P <= 0 or N <= 0:
            return float("nan")
        return float((pos * (below + 0.5 * neg)).sum() / (P * N))


def calibration(p, y, bins=10):
    order = np.argsort(p, kind="mergesort")
    rows = []
    for chunk in np.array_split(order, bins):
        if len(chunk) == 0:
            continue
        rows.append({"n": int(len(chunk)), "pred": float(p[chunk].mean()), "obs": float(y[chunk].mean())})
    gaps = [abs(r["pred"] - r["obs"]) for r in rows]
    ece = sum(abs(r["pred"] - r["obs"]) * r["n"] for r in rows) / max(1, sum(r["n"] for r in rows))
    return {"bins": rows, "max_gap": float(max(gaps)) if gaps else float("nan"), "ece": float(ece)}


class Boot:
    """Bootstrap over players. W[b, j] = how many times player j was drawn in
    resample b. A mean of per-row values over a row set is then
    (W @ player_sums) / (W @ player_counts)."""

    def __init__(self, pids, B, seed, tag):
        self.uniq, self.inv = np.unique(pids, return_inverse=True)
        n = len(self.uniq)
        rng = rng_for(seed, tag)
        W = np.zeros((B, n), dtype=np.float32)
        for b in range(B):
            W[b] = np.bincount(rng.integers(0, n, size=n), minlength=n)
        self.W = W
        self.B = B

    def idx(self, pids):
        j = np.searchsorted(self.uniq, pids)
        assert np.all(self.uniq[j] == pids)
        return j

    def mean_ci(self, pidx, vals):
        n = len(self.uniq)
        S = np.bincount(pidx, weights=vals, minlength=n)
        K = np.bincount(pidx, minlength=n).astype(np.float64)
        est = S.sum() / K.sum()
        boots = (self.W @ S) / (self.W @ K)
        lo, hi = np.nanpercentile(boots, [2.5, 97.5])
        return {"est": float(est), "lo": float(lo), "hi": float(hi)}


def ci_label(d, nd=4):
    return f"{d['est']:+.{nd}f} [{d['lo']:+.{nd}f}, {d['hi']:+.{nd}f}]"


def excl_below(d):
    return d is not None and d["hi"] < 0


def excl_above(d):
    return d is not None and d["lo"] > 0


# ----------------------------------------------------------------- frames
def fill_fallback(J, col, method_cols):
    """Fill NaN in col with the mean of the same column over rows of the same
    split, fold and age (that method's own answers)."""
    miss = J[col].isna()
    if not miss.any():
        return J[col].to_numpy(dtype=np.float64), 0
    means = J.groupby(["split", "fold", "age"], observed=True)[col].transform("mean")
    filled = J[col].fillna(means)
    still = filled.isna()
    if still.any():  # age with no answers at all: role mean for the split
        filled = filled.fillna(J.groupby("split", observed=True)[col].transform("mean"))
    return filled.to_numpy(dtype=np.float64), int(miss.sum())


def build_peak_frame(role, truth, suffix=""):
    J = None
    keysets = {}
    for m, stem in PEAK_METHODS.items():
        df = load_pred(stem + suffix, role)
        cols = ["gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90", "p_mlb", "p_useful", "p_good"]
        cols += ["p_regular_fut", "p_regular"] if m != "ml" else ["p_regular"]
        keep = KEY + (["fold"] if J is None else []) + cols
        df = df[keep].rename(columns={c: f"{m}__{c}" for c in cols})
        keysets[m] = len(df)
        J = df if J is None else J.merge(df, on=KEY, how="outer", indicator=f"_m_{m}")
        if f"_m_{m}" in J:
            bad = (J[f"_m_{m}"] != "both").sum()
            if bad:
                log(f"  WARNING {role} {m}: {bad} rows on one side only")
            J = J.drop(columns=[f"_m_{m}"])
    J = J.merge(truth, on=["pid", "dump_year"], how="left")
    J["fold"] = J["fold"].astype(np.int16)
    # the app's own Make it % as an extra method
    J["current_makeit__p_regular"] = J["current__p_regular"]
    return J, keysets


def build_path_frame(role, truth):
    J = None
    for m, stem in PATH_METHODS.items():
        df = load_pred(stem, role)
        cols = ["d1", "d3", "d5", "d1_q25", "d1_q75"] + ([f"d{h}_mean" for h in PATH_H] if m == "ml" else [])
        keep = KEY + (["fold"] if J is None else []) + cols
        df = df[keep].rename(columns={c: f"{m}__{c}" for c in cols})
        J = df if J is None else J.merge(df, on=KEY, how="outer", indicator=f"_m_{m}")
        if f"_m_{m}" in J:
            bad = (J[f"_m_{m}"] != "both").sum()
            if bad:
                log(f"  WARNING path {role} {m}: {bad} rows on one side only")
            J = J.drop(columns=[f"_m_{m}"])
    J = J.merge(truth[["pid", "dump_year", "age", "now_waa", "d_1", "d_3", "d_5"]], on=["pid", "dump_year"],
                how="left")
    J["fold"] = J["fold"].astype(np.int16)
    return J


def peak_subset_masks(df):
    age = df["age"].to_numpy()
    pot = df["pot"].to_numpy()
    return {
        "all": np.ones(len(df), bool),
        "prospects": (pot >= 45) & (age >= 17) & (age <= 22),
        "age16_19": (age >= 16) & (age <= 19),
        "age20_22": (age >= 20) & (age <= 22),
        "age23_26": (age >= 23) & (age <= 26),
    }


def outside_subset_masks(df):
    """Subsets of the out-of-org rows: amateurs, free agents, age bands."""
    age = df["age"].to_numpy()
    ama = df["amateur"].to_numpy() == 1
    return {
        "all": np.ones(len(df), bool),
        "amateur": ama,
        "free_agent": ~ama,
        "age16_19": (age >= 16) & (age <= 19),
        "age20_22": (age >= 20) & (age <= 22),
        "age23_26": (age >= 23) & (age <= 26),
    }


# ----------------------------------------------------------------- scoring
def score_peak(S, boot, views, masks_fn=peak_subset_masks):
    """S: frame for one split and role. Returns the peak-gain block."""
    out = {}
    methods = list(PEAK_METHODS)
    now = S["now_waa"].to_numpy()
    peak = S["peak"].to_numpy()
    gain = S["gain"].to_numpy()
    pidx = boot.idx(S["pid"].to_numpy())
    masks = masks_fn(S)
    qcols = ["gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90"]
    for view in views:
        Q = {}
        filled_n = {}
        for m in methods:
            Q[m] = {}
            filled_n[m] = 0
            for qc in qcols:
                col = f"{m}__{qc}"
                if view == "filled":
                    Q[m][qc], k = fill_fallback(S, col, None)
                    filled_n[m] = max(filled_n[m], k)
                else:
                    Q[m][qc] = S[col].to_numpy(dtype=np.float64)
        ok = np.isfinite(gain)
        for m in methods:
            ok &= np.isfinite(Q[m]["gain_q50"]) & np.isfinite(Q[m]["gain_q25"]) & np.isfinite(Q[m]["gain_q75"])
        vblock = {"filled_rows": filled_n}
        for sub, mk in masks.items():
            r = ok & mk
            if r.sum() == 0:
                continue
            per = {}
            rows = {}
            for m in methods:
                q = Q[m]
                est = now[r] + q["gain_q50"][r]
                rows[m] = {
                    "mae": np.abs(est - peak[r]),
                    "pin25": pinball_rows(q["gain_q25"][r], gain[r], 0.25),
                    "pin50": pinball_rows(q["gain_q50"][r], gain[r], 0.50),
                    "pin75": pinball_rows(q["gain_q75"][r], gain[r], 0.75),
                }
                c50 = (gain[r] >= q["gain_q25"][r]) & (gain[r] <= q["gain_q75"][r])
                c80 = (gain[r] >= q["gain_q10"][r]) & (gain[r] <= q["gain_q90"][r])
                per[m] = {k: float(v.mean()) for k, v in rows[m].items()}
                per[m]["bias"] = float((est - peak[r]).mean())
                per[m]["cover_q25_q75"] = float(c50.mean())
                per[m]["cover_q10_q90"] = float(c80[np.isfinite(q["gain_q10"][r])].mean()) \
                    if np.isfinite(q["gain_q10"][r]).any() else float("nan")
                per[m]["share_below_q50"] = float((gain[r] <= q["gain_q50"][r]).mean())
            diffs = {}
            for a, b in DIFFS_PEAK:
                diffs[f"{a}-{b}"] = {k: boot.mean_ci(pidx[r], rows[a][k] - rows[b][k])
                                    for k in ("mae", "pin25", "pin50", "pin75")}
            vblock[sub] = {"n_rows": int(r.sum()), "n_players": int(len(np.unique(pidx[r]))),
                           "methods": per, "diffs": diffs}
        out[view] = vblock
    return out


def score_chances(S, boot, views, eps, auc_ci, masks_fn=peak_subset_masks):
    out = {}
    now = S["now_waa"].to_numpy()
    pidx = boot.idx(S["pid"].to_numpy())
    masks = masks_fn(S)
    for tgt in CHANCES:
        y_all = S[CHANCE_TRUTH[tgt]].to_numpy(dtype=np.float64)
        methods = list(PEAK_METHODS) + (["current_makeit"] if tgt == "p_regular" else [])
        bar = CHANCE_BAR[tgt]
        scope = np.isfinite(y_all)
        above = np.zeros(len(S), bool)
        if bar is not None:
            above = now >= bar - BAR_TOL
            scope &= ~above
        tblock = {"rows_above_bar_line": int((np.isfinite(y_all) & above).sum()),
                  "above_bar_reached": float(np.nanmean(y_all[above])) if above.any() else None}
        for view in views:
            P = {}
            filled_n = {}
            for m in methods:
                col = f"{m}__{chance_col(m, tgt)}"
                if view == "filled":
                    P[m], filled_n[m] = fill_fallback(S, col, None)
                else:
                    P[m], filled_n[m] = S[col].to_numpy(dtype=np.float64), 0
            ok = scope.copy()
            for m in methods:
                ok &= np.isfinite(P[m])
            vblock = {"filled_rows": filled_n}
            for sub, mk in masks.items():
                r = ok & mk
                if r.sum() == 0:
                    continue
                y = y_all[r]
                per, rows = {}, {}
                aucs = {}
                for m in methods:
                    p = P[m][r]
                    rows[m] = {"logloss": logloss_rows(p, y, eps), "brier": (p - y) ** 2}
                    aucs[m] = AUC(p, y)
                    per[m] = {"logloss": float(rows[m]["logloss"].mean()), "brier": float(rows[m]["brier"].mean()),
                              "auc": aucs[m](), "mean_pred": float(p.mean()),
                              "share_exact_0": float((p <= 0).mean()), "share_exact_1": float((p >= 1).mean())}
                    if sub == "all":
                        per[m]["calibration"] = calibration(p, y)
                    else:
                        cal = calibration(p, y)
                        per[m]["calibration_max_gap"] = cal["max_gap"]
                        per[m]["calibration_ece"] = cal["ece"]
                diffs = {}
                pairs = list(DIFFS_PEAK) + ([("ml", "current_makeit")] if tgt == "p_regular" else [])
                for a, b in pairs:
                    d = {k: boot.mean_ci(pidx[r], rows[a][k] - rows[b][k]) for k in ("logloss", "brier")}
                    if auc_ci and sub == "all":
                        pr = pidx[r]
                        bs = []
                        for bb in range(boot.B):
                            w = boot.W[bb][pr].astype(np.float64)
                            bs.append(aucs[a](w) - aucs[b](w))
                        lo, hi = np.nanpercentile(bs, [2.5, 97.5])
                        d["auc"] = {"est": aucs[a]() - aucs[b](), "lo": float(lo), "hi": float(hi)}
                    diffs[f"{a}-{b}"] = d
                vblock[sub] = {"n_rows": int(r.sum()), "n_players": int(len(np.unique(pidx[r]))),
                               "base_rate": float(y.mean()), "methods": per, "diffs": diffs}
            tblock[view] = vblock
        out[tgt] = tblock
    return out


def top10(S, seed, tag):
    """Of the players each method ranks in its top 10% at one age, the share who
    reached useful and the share who became regulars. Ranks on p_useful and on
    p_regular. Rows every method answers."""
    out = {}
    methods = list(PEAK_METHODS) + ["current_makeit"]
    useful = S["reach_useful"].to_numpy(dtype=np.float64)
    regular = S["regular_future"].to_numpy(dtype=np.float64)
    age = S["age"].to_numpy()
    for rank_on in ("p_useful", "p_regular"):
        ok = np.isfinite(useful)
        ms = methods if rank_on == "p_regular" else list(PEAK_METHODS)
        P = {m: S[f"{m}__{chance_col(m, rank_on)}"].to_numpy(dtype=np.float64) for m in ms}
        for m in ms:
            ok &= np.isfinite(P[m])
        blk = {}
        for label, lo, hi in (("18", 18, 18), ("19", 19, 19), ("20", 20, 20), ("18-20", 18, 20)):
            r = np.flatnonzero(ok & (age >= lo) & (age <= hi))
            if len(r) == 0:
                continue
            k = int(math.ceil(0.10 * len(r)))
            tie = rng_for(seed, tag, rank_on, label).random(len(r))
            ab = {"n_rows": int(len(r)), "top_n": k, "base_useful": float(useful[r].mean()),
                  "base_regular": float(np.nanmean(regular[r])), "methods": {}}
            for m in ms:
                order = np.lexsort((tie, -P[m][r]))
                top = r[order[:k]]
                ab["methods"][m] = {"useful": float(useful[top].mean()),
                                    "regular": float(np.nanmean(regular[top])),
                                    "n_useful": int(useful[top].sum()),
                                    "n_regular": int(np.nansum(regular[top])),
                                    "n_regular_known": int(np.isfinite(regular[top]).sum()),
                                    "min_score_in_top": float(P[m][top].min())}
            blk[label] = ab
        out[rank_on] = blk
    return out


def score_path(S, boot):
    out = {}
    methods = list(PATH_METHODS) + ["ml_mean"]
    age = S["age"].to_numpy()
    pidx = boot.idx(S["pid"].to_numpy())
    pred = {m: {h: S[f"{m}__d{h}"].to_numpy(dtype=np.float64) for h in PATH_H} for m in PATH_METHODS}
    # fix 5: the squared-loss mean models of every scored horizon (d1_mean, d3_mean, d5_mean)
    pred["ml_mean"] = {h: S[f"ml__d{h}_mean"].to_numpy(dtype=np.float64) for h in PATH_H
                       if f"ml__d{h}_mean" in S.columns}
    for h in PATH_H:
        y = S[f"d_{h}"].to_numpy(dtype=np.float64)
        hb = {}
        for band, lo, hi in PATH_BANDS:
            r = np.isfinite(y) & (age >= lo) & (age <= hi)
            ms = [m for m in methods if h in pred[m]]
            for m in ms:
                r &= np.isfinite(pred[m][h])
            if r.sum() == 0:
                continue
            rows = {m: np.abs(pred[m][h][r] - y[r]) for m in ms}
            per = {m: {"mae": float(rows[m].mean()), "bias": float((pred[m][h][r] - y[r]).mean())} for m in ms}
            diffs = {f"{a}-{b}": {"mae": boot.mean_ci(pidx[r], rows[a] - rows[b])} for a, b in DIFFS_PATH}
            if "ml_mean" in rows:
                diffs["ml_mean-current_path"] = {"mae": boot.mean_ci(pidx[r], rows["ml_mean"] - rows["current_path"])}
                # squared-loss models aim at the mean: RMSE and bias are their fair check
                for m in ("ml", "ml_mean", "current_path"):
                    per[m]["rmse"] = float(np.sqrt(np.mean((pred[m][h][r] - y[r]) ** 2)))
            hb[band] = {"n_rows": int(r.sum()), "n_players": int(len(np.unique(pidx[r]))), "methods": per,
                        "diffs": diffs}
        out[f"d{h}"] = hb
    # d1 middle-half coverage (current_path and age_mean share one unconditional band)
    y = S["d_1"].to_numpy(dtype=np.float64)
    cov = {}
    for band, lo, hi in PATH_BANDS:
        r = np.isfinite(y) & (age >= lo) & (age <= hi)
        c = {}
        for m in PATH_METHODS:
            q25 = S[f"{m}__d1_q25"].to_numpy(dtype=np.float64)[r]
            q75 = S[f"{m}__d1_q75"].to_numpy(dtype=np.float64)[r]
            c[m] = float(((y[r] >= q25) & (y[r] <= q75)).mean())
            c[m + "_strict"] = float(((y[r] > q25) & (y[r] < q75)).mean())
        cov[band] = {"n_rows": int(r.sum()), "cover": c}
    out["d1_cover_q25_q75"] = cov
    return out


# ----------------------------------------------------------------- verdicts
def verdict_rule(diff_by_split, base_a, base_b, lower_better=True):
    """diff_by_split[split][base] = {est, lo, hi} of ML minus base."""
    wins = all(excl_below(diff_by_split[s].get(base_a)) and excl_below(diff_by_split[s].get(base_b))
               for s in SPLITS)
    if wins:
        return "ML wins"
    if all(excl_above(diff_by_split[s].get(base_a)) for s in SPLITS):
        return "current wins"
    return "no clear win"


def verdicts(R):
    out = []
    surv = []
    for role in C.ROLES:
        # peak median
        spec = [("peak gain median", "peak", "mae", "MAE of now + gain_q50 vs peak (WAA)")]
        spec += [(t, "chance", "logloss", "log loss, rows below the bar line") if t != "p_regular"
                 else (t, "chance", "logloss", "log loss vs regular_future") for t in CHANCES]
        for name, kind, metric, label in spec:
            by = {}
            vals = {}
            for s in SPLITS:
                if kind == "peak":
                    blk = R[s][role]["peak"]["main"]["all"]
                else:
                    blk = R[s][role]["chances"][name]["main"]["all"]
                by[s] = {"current": blk["diffs"]["ml-current"][metric],
                         "current_all": blk["diffs"]["ml-current_all"][metric],
                         "surv": blk["diffs"]["current_all-current"][metric]}
                vals[s] = {m: blk["methods"][m][metric] for m in ("ml", "current", "current_all")}
                vals[s]["n"] = blk["n_rows"]
            v = verdict_rule(by, "current", "current_all")
            nd = 3 if kind == "peak" else 4
            out.append({
                "target": f"{name} ({role})", "role": role, "winner": v, "metric": label,
                "ml": " / ".join(f"{s} {vals[s]['ml']:.{nd}f}" for s in SPLITS),
                "current": " / ".join(f"{s} {vals[s]['current']:.{nd}f}" for s in SPLITS),
                "current_all": " / ".join(f"{s} {vals[s]['current_all']:.{nd}f}" for s in SPLITS),
                "diff_ci": "; ".join(f"{s} ML-current {ci_label(by[s]['current'], nd)}, ML-current_all "
                                     f"{ci_label(by[s]['current_all'], nd)}" for s in SPLITS),
                "n": {s: vals[s]["n"] for s in SPLITS},
            })
            sv = ("current_all beats current" if all(excl_below(by[s]["surv"]) for s in SPLITS)
                  else "current beats current_all" if all(excl_above(by[s]["surv"]) for s in SPLITS)
                  else "no clear difference")
            surv.append({"target": f"{name} ({role})", "verdict": sv,
                         "diff_ci": "; ".join(f"{s} {ci_label(by[s]['surv'], nd)}" for s in SPLITS)})
        # path d1, d3
        for h in (1, 3):
            by, vals = {}, {}
            for s in SPLITS:
                blk = R[s][role]["path"][f"d{h}"]["all"]
                by[s] = {"current": blk["diffs"]["ml-current_path"]["mae"],
                         "current_all": blk["diffs"]["ml-age_mean"]["mae"],
                         "surv": blk["diffs"]["age_mean-current_path"]["mae"]}
                vals[s] = {"ml": blk["methods"]["ml"]["mae"], "current": blk["methods"]["current_path"]["mae"],
                           "current_all": blk["methods"]["age_mean"]["mae"], "n": blk["n_rows"]}
            v = verdict_rule(by, "current", "current_all")
            out.append({
                "target": f"path d{h} ({role})", "role": role, "winner": v,
                "metric": f"MAE of the WAA change {h} year(s) ahead, ages 16-38",
                "ml": " / ".join(f"{s} {vals[s]['ml']:.3f}" for s in SPLITS),
                "current": " / ".join(f"{s} {vals[s]['current']:.3f}" for s in SPLITS),
                "current_all": "age_mean " + " / ".join(f"{s} {vals[s]['current_all']:.3f}" for s in SPLITS),
                "diff_ci": "; ".join(f"{s} ML-current_path {ci_label(by[s]['current'], 3)}, ML-age_mean "
                                     f"{ci_label(by[s]['current_all'], 3)}" for s in SPLITS),
                "n": {s: vals[s]["n"] for s in SPLITS},
            })
            sv = ("age_mean beats current_path" if all(excl_below(by[s]["surv"]) for s in SPLITS)
                  else "current_path beats age_mean" if all(excl_above(by[s]["surv"]) for s in SPLITS)
                  else "no clear difference")
            surv.append({"target": f"path d{h} ({role})", "verdict": sv,
                         "diff_ci": "; ".join(f"{s} age_mean-current_path {ci_label(by[s]['surv'], 3)}"
                                              for s in SPLITS)})
    return out, surv


def subset_verdicts(R):
    """The same rule per subset (secondary; the headline uses 'all')."""
    rows = []
    for role in C.ROLES:
        for sub in PEAK_SUBSETS:
            for name, path_ in [("peak gain median", ("peak", None, "mae"))] + \
                               [(t, ("chances", t, "logloss")) for t in CHANCES]:
                by = {}
                okk = True
                for s in SPLITS:
                    blk = R[s][role][path_[0]]
                    blk = blk["main"] if path_[1] is None else blk[path_[1]]["main"]
                    if sub not in blk:
                        okk = False
                        break
                    b = blk[sub]
                    by[s] = {"current": b["diffs"]["ml-current"][path_[2]],
                             "current_all": b["diffs"]["ml-current_all"][path_[2]]}
                if okk:
                    rows.append({"role": role, "subset": sub, "target": name,
                                 "verdict": verdict_rule(by, "current", "current_all"),
                                 "ml_minus_current": {s: by[s]["current"] for s in SPLITS}})
        for band, _, _ in PATH_BANDS:
            for h in PATH_H:
                by = {}
                for s in SPLITS:
                    b = R[s][role]["path"][f"d{h}"].get(band)
                    if b is None:
                        break
                    by[s] = {"current": b["diffs"]["ml-current_path"]["mae"],
                             "current_all": b["diffs"]["ml-age_mean"]["mae"]}
                if len(by) == 2:
                    rows.append({"role": role, "subset": band, "target": f"path d{h}",
                                 "verdict": verdict_rule(by, "current", "current_all"),
                                 "ml_minus_current": {s: by[s]["current"] for s in SPLITS}})
    return rows


# ----------------------------------------------------------------- importance
def importance_summary():
    out = {}
    rep = C.REPORT_DIR
    for role in C.ROLES:
        f = os.path.join(rep, f"peak_importance_{role}.json")
        if not os.path.exists(f):
            continue
        d = json.load(open(f))
        blk = {}
        for model in ("gain_q50", "reach_useful"):
            m = d.get(model)
            if not m:
                continue
            fam = sorted(((k, v["mean"]) for k, v in m["family"].items()), key=lambda t: -t[1])
            blk[model] = {"n_rows": m["n_rows"], "base_loss": m["base_loss"], "loss": m["loss"],
                          "families": fam, "top": [(t["feature"], t["mean"]) for t in m["top15"]]}
        out[f"peak_{role}"] = blk
    f = os.path.join(rep, "path_importance.json")
    if os.path.exists(f):
        d = json.load(open(f))
        for role, rb in d.get("roles", {}).items():
            blk = {}
            for band, b in rb.get("bands", {}).items():
                fam = sorted(((k, v["mae_rise"]) for k, v in b["families"].items()), key=lambda t: -t[1])
                blk[band] = {"n_rows": b["n"], "base_mae": b["base_mae"], "families": fam,
                             "top": [(t["feature"], t["mae_rise"]) for t in b["top_features"]]}
            vet = rb.get("veterans_30_34", {}).get("tables", {})
            blk["veterans_30_34"] = vet
            out[f"path_{role}"] = blk
    return out


# ----------------------------------------------------------------- markdown
def fmt(x, nd=3):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def md_table(head, rows):
    s = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    s += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(s)


RULE_TEXT = (
    "ML wins a target when its main metric (peak: MAE of now + gain_q50 against the peak; chances: log loss; "
    "path: MAE of d1 and of d3) is lower than BOTH current and current_all (for the path: current_path and "
    "age_mean), with the 95% player-bootstrap interval of each difference below zero, on EVERY split run "
    "(the full run: the oof and the time split). \"current wins\" when ML is worse than current with the "
    "interval above zero on every split run. Anything else is \"no clear win\". The rule reads the overall "
    "subset, main view (rows every method answers)."
)


def write_md(R, V, SURV, SUBV, IMP, meta, path, OUT=None, OUTV=None):
    L = []
    L.append(f"# ML vs the current method: DEV held-out comparison, {meta['basis']} basis")
    L.append("")
    L.append(f"Generated {meta['generated']} by backtest/ml/compare.py --basis {meta['basis']}. Basis: the DEV "
             f"rows are priced with the {meta['basis']} engine calibration (one model set per league). Splits: "
             f"{', '.join(SPLITS)}. Bootstrap: {meta['boot']} resamples over "
             f"players. Log loss clips probabilities to [{meta['eps']}, 1 - {meta['eps']}].")
    L.append("")
    L.append("## Decision rule")
    L.append("")
    L.append(RULE_TEXT)
    L.append("")
    L.append("## Verdicts")
    L.append("")
    L.append(md_table(["Target", "Winner", "Metric", "ML", "current", "current_all / age_mean",
                       f"n rows ({' / '.join(SPLITS)})"],
                      [[v["target"], v["winner"], v["metric"], v["ml"], v["current"], v["current_all"],
                        " / ".join(f"{v['n'][s]:,}" for s in SPLITS)] for v in V]))
    L.append("")
    L.append("Differences with 95% intervals (negative = ML better):")
    L.append("")
    for v in V:
        L.append(f"- {v['target']}: {v['diff_ci']}")
    L.append("")
    if OUT:
        L.extend(outside_md(OUT, OUTV))
    L.append("## Survivorship fix on its own (current_all vs current), and age_mean vs current_path")
    L.append("")
    L.append(md_table(["Target", "Verdict", "Difference (negative = first method better)"],
                      [[s["target"], s["verdict"], s["diff_ci"]] for s in SURV]))
    L.append("")
    L.append("## Plain words")
    L.append("")
    L.append(meta.get("plain", ""))
    L.append("")
    # top 10
    L.append("## Top 10 percent at ages 18-20")
    L.append("")
    L.append("Each method ranks the players at one age by its own chance. The table shows, for its top 10%, the "
             "share whose peak reached useful (0 WAA) and the share who later had a regular MLB season.")
    L.append("")
    for s in SPLITS:
        for role in C.ROLES:
            T = R[s][role]["top10"]
            rows = []
            for rank_on in ("p_useful", "p_regular"):
                for age_l, ab in T[rank_on].items():
                    for m, mv in ab["methods"].items():
                        rows.append([rank_on, age_l, m, f"{ab['top_n']:,} of {ab['n_rows']:,}",
                                     f"{mv['useful']:.3f} ({mv['n_useful']:,})",
                                     f"{mv['regular']:.3f} ({mv['n_regular']:,})",
                                     f"{ab['base_useful']:.3f} / {ab['base_regular']:.3f}"])
            L.append(f"### {s} split, {role}")
            L.append("")
            L.append(md_table(["Ranked on", "Age", "Method", "Top n of n", "Useful share (n)",
                               "Regular share (n)", "All players useful / regular"], rows))
            L.append("")
    # peak detail
    L.append("## Peak detail")
    L.append("")
    L.append("MAE = mean |now + gain_q50 - peak| in WAA. pin25/50/75 = pinball loss on the gain. cover = share of "
             "true gains inside q25-q75 (target 0.50) and q10-q90 (target 0.80); a gain of exactly 0 counts as "
             "inside when the lower quantile is 0.")
    L.append("")
    for s in SPLITS:
        for role in C.ROLES:
            blk = R[s][role]["peak"]
            for view in blk:
                vb = blk[view]
                rows = []
                for sub in PEAK_SUBSETS:
                    if sub not in vb:
                        continue
                    b = vb[sub]
                    for m, mv in b["methods"].items():
                        rows.append([sub, f"{b['n_rows']:,}", m, fmt(mv["mae"]), fmt(mv["bias"]), fmt(mv["pin25"], 4),
                                     fmt(mv["pin50"], 4), fmt(mv["pin75"], 4), fmt(mv["cover_q25_q75"]),
                                     fmt(mv["cover_q10_q90"]), fmt(mv["share_below_q50"])])
                L.append(f"### {s} split, {role}, {view} view (filled rows: {vb['filled_rows']})")
                L.append("")
                L.append(md_table(["Subset", "n rows", "Method", "MAE", "Bias", "pin25", "pin50", "pin75",
                                   "cover 25-75", "cover 10-90", "share <= q50"], rows))
                L.append("")
                rows = []
                for sub in PEAK_SUBSETS:
                    if sub not in vb:
                        continue
                    for pair, d in vb[sub]["diffs"].items():
                        rows.append([sub, pair, ci_label(d["mae"], 3), ci_label(d["pin50"], 4)])
                L.append(md_table(["Subset", "Pair", "MAE diff [95%]", "pin50 diff [95%]"], rows))
                L.append("")
    # chances detail
    L.append("## Chances detail")
    L.append("")
    L.append("p_mlb / p_useful / p_good are scored on rows below the bar line (now < bar - 0.05); every method "
             "reads 1.0 above it. p_regular is scored against regular_future (a later season with >= 300 PA or "
             ">= 150 BF). current_makeit is the app's own Make it % column (fit on regular_ever); current, "
             "current_all and current_w40 use the same cells refit on regular_future.")
    L.append("")
    for s in SPLITS:
        for role in C.ROLES:
            for tgt in CHANCES:
                tb = R[s][role]["chances"][tgt]
                vb = tb["main"]
                rows = []
                for sub in PEAK_SUBSETS:
                    if sub not in vb:
                        continue
                    b = vb[sub]
                    for m, mv in b["methods"].items():
                        cg = mv.get("calibration", {}).get("max_gap", mv.get("calibration_max_gap"))
                        rows.append([sub, f"{b['n_rows']:,}", fmt(b["base_rate"], 4), m, fmt(mv["logloss"], 4),
                                     fmt(mv["brier"], 4), fmt(mv["auc"], 3), fmt(cg, 4),
                                     fmt(mv["share_exact_0"], 3)])
                L.append(f"### {s} split, {role}, {tgt} (rows at or above the bar line, not scored: "
                         f"{tb['rows_above_bar_line']:,})")
                L.append("")
                L.append(md_table(["Subset", "n rows", "Base rate", "Method", "Log loss", "Brier", "AUC",
                                   "Calib max gap", "Share at exactly 0"], rows))
                L.append("")
                rows = []
                for sub in PEAK_SUBSETS:
                    if sub not in vb:
                        continue
                    for pair, d in vb[sub]["diffs"].items():
                        rows.append([sub, pair, ci_label(d["logloss"], 4), ci_label(d["brier"], 5),
                                     ci_label(d["auc"], 4) if "auc" in d else ""])
                L.append(md_table(["Subset", "Pair", "Log loss diff [95%]", "Brier diff [95%]", "AUC diff [95%]"],
                                  rows))
                L.append("")
                if "filled" in tb:
                    fb = tb["filled"]["all"]
                    L.append(f"Filled view, all rows (n {fb['n_rows']:,}, filled {tb['filled']['filled_rows']}): " +
                             ", ".join(f"{m} {fmt(mv['logloss'], 4)}" for m, mv in fb["methods"].items()) +
                             "; ML-current " + ci_label(fb["diffs"]["ml-current"]["logloss"], 4))
                    L.append("")
                cal = vb["all"]["methods"]
                L.append("Calibration, all rows (10 equal-count bins, predicted / observed):")
                L.append("")
                for m, mv in cal.items():
                    bins = mv["calibration"]["bins"]
                    L.append(f"- {m}: " + ", ".join(f"{b['pred']:.4f}/{b['obs']:.4f}" for b in bins) +
                             f" (max gap {mv['calibration']['max_gap']:.4f}, ECE {mv['calibration']['ece']:.4f})")
                L.append("")
    # path detail
    L.append("## Path detail")
    L.append("")
    L.append("MAE of the predicted WAA change against the real one, on rows where the real change is known. "
             "ml = the median models; ml_mean = the squared-loss models d1_mean..d5_mean (fix 5, for money: "
             "the expected change). A mean model loses on MAE by design; its check is the bias and the RMSE.")
    L.append("")
    for s in SPLITS:
        for role in C.ROLES:
            P = R[s][role]["path"]
            rows = []
            for h in PATH_H:
                for band, _, _ in PATH_BANDS:
                    b = P[f"d{h}"].get(band)
                    if b is None:
                        continue
                    ms = b["methods"]
                    mm = ms.get("ml_mean", {})
                    rows.append([f"d{h}", band, f"{b['n_rows']:,}", fmt(ms["ml"]["mae"]),
                                 fmt(mm.get("mae")), fmt(ms["current_path"]["mae"]),
                                 fmt(ms["age_mean"]["mae"]), ci_label(b["diffs"]["ml-current_path"]["mae"], 3),
                                 ci_label(b["diffs"]["ml-age_mean"]["mae"], 3),
                                 f"{fmt(ms['ml']['bias'])} / {fmt(ms['current_path']['bias'])} / "
                                 f"{fmt(ms['age_mean']['bias'])}",
                                 f"{fmt(mm.get('bias'))} / {fmt(mm.get('rmse'))} / {fmt(ms['ml'].get('rmse'))}"])
            L.append(f"### {s} split, {role}")
            L.append("")
            L.append(md_table(["Horizon", "Ages", "n rows", "ML", "ml_mean", "current_path", "age_mean",
                               "ML - current_path [95%]", "ML - age_mean [95%]", "Bias ML / cur / age",
                               "ml_mean bias / RMSE / ML RMSE"], rows))
            L.append("")
            cov = P["d1_cover_q25_q75"]
            L.append("d1 q25-q75 coverage (target 0.50; ties at the edges count as inside; current_path and "
                     "age_mean share one unconditional role x age band): " +
                     "; ".join(f"{band} n {c['n_rows']:,}: ML {fmt(c['cover']['ml'])}, "
                               f"age band {fmt(c['cover']['current_path'])}" for band, c in cov.items()))
            L.append("")
    # subset verdicts
    L.append("## The same rule per subset (secondary)")
    L.append("")
    L.append(md_table(["Role", "Subset", "Target", "Verdict"] + [f"ML - current, {s}" for s in SPLITS],
                      [[r["role"], r["subset"], r["target"], r["verdict"]]
                       + [ci_label(r["ml_minus_current"][s], 4) for s in SPLITS]
                       for r in SUBV]))
    L.append("")
    # coverage
    L.append("## Coverage (rows each method answers)")
    L.append("")
    rows = []
    for s in SPLITS:
        for role in C.ROLES:
            for grp, cv in meta["coverage"][s][role].items():
                for m, c in cv.items():
                    rows.append([s, role, grp, m, f"{c['rows']:,}", f"{c['answered']:,}"])
    L.append(md_table(["Split", "Role", "Group", "Method", "Rows", "Answered"], rows))
    L.append("")
    # importance
    L.append("## What drives development in this model")
    L.append("")
    L.append(meta.get("importance_text", ""))
    L.append("")
    for key, blk in IMP.items():
        if key.startswith("peak_"):
            role = key[-1]
            for model, b in blk.items():
                L.append(f"- Peak model {role}, {model} (n {b['n_rows']:,} fold-0 rows, loss rise when shuffled): "
                         "families " + ", ".join(f"{f} {v:.3f}" for f, v in b["families"]) +
                         "; top features " + ", ".join(f for f, _ in b["top"][:10]) + ".")
        else:
            role = key[-1]
            for band, b in blk.items():
                if band == "veterans_30_34":
                    continue
                L.append(f"- Path model {role}, ages {band} (n {b['n_rows']:,}, base MAE {b['base_mae']:.3f}): "
                         "families " + ", ".join(f"{f} +{v:.3f}" for f, v in b["families"]) +
                         "; top features " + ", ".join(f for f, _ in b["top"][:10]) + ".")
    L.append("")
    L.append("## Notes")
    L.append("")
    for n in meta.get("notes", []):
        L.append(f"- {n}")
    L.append("")
    text = "\n".join(L).replace("—", ", ")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def outside_md(OUT, OUTV):
    """Markdown lines for the out-of-org rows (fix 6)."""
    L = ["## Out-of-org rows: amateurs and free agents (fix 6)", "",
         "DEV rows at ages 16-26 outside an org (raw Lev AMA or FA, level 'none'), peak known. ML: the peak "
         "models trained with these rows added (feature 'amateur' = raw Lev AMA). The cell methods use the same "
         "cells as above (fit on in-org rows only), which is how the app scores an amateur or a free agent today. "
         "Main metric per target as in the verdicts; negative difference = ML better.", ""]
    if OUTV:
        L.append(md_table(["Target", "Winner (same rule)", "ML", "current", "current_all", "n rows"],
                          [[v["target"], v["winner"], v["ml"], v["current"], v["current_all"],
                            " / ".join(f"{v['n'][s]:,}" for s in SPLITS)] for v in OUTV]))
        L.append("")
        for v in OUTV:
            L.append(f"- {v['target']}: {v['diff_ci']}")
        L.append("")
    for s in SPLITS:
        for role in C.ROLES:
            blk = OUT.get(s, {}).get(role)
            if not blk:
                continue
            rows = []
            pb = blk["peak"]["main"]
            for sub in OUTSIDE_SUBSETS:
                if sub not in pb:
                    continue
                b = pb[sub]
                ms = b["methods"]
                rows.append([sub, "peak MAE", f"{b['n_rows']:,}", "", fmt(ms["ml"]["mae"]), fmt(ms["current"]["mae"]),
                             fmt(ms["current_all"]["mae"]), ci_label(b["diffs"]["ml-current"]["mae"], 3)])
            for tgt in CHANCES:
                cb = blk["chances"][tgt]["main"]
                for sub in OUTSIDE_SUBSETS:
                    if sub not in cb:
                        continue
                    b = cb[sub]
                    ms = b["methods"]
                    rows.append([sub, f"{tgt} log loss", f"{b['n_rows']:,}", fmt(b["base_rate"], 4),
                                 fmt(ms["ml"]["logloss"], 4), fmt(ms["current"]["logloss"], 4),
                                 fmt(ms["current_all"]["logloss"], 4), ci_label(b["diffs"]["ml-current"]["logloss"], 4)])
            L.append(f"### {s} split, {role}, out-of-org rows")
            L.append("")
            L.append(md_table(["Subset", "Metric", "n rows", "Base rate", "ML", "current", "current_all",
                               "ML - current [95%]"], rows))
            L.append("")
    return L


def outside_verdicts(OUT):
    """The decision rule on the out-of-org rows (overall subset, main view)."""
    out = []
    for role in C.ROLES:
        if not all(role in OUT.get(s, {}) for s in SPLITS):
            continue
        spec = [("peak gain median", "peak", "mae")] + [(t, "chance", "logloss") for t in CHANCES]
        for name, kind, metric in spec:
            by, vals = {}, {}
            for s in SPLITS:
                blk = (OUT[s][role]["peak"] if kind == "peak" else OUT[s][role]["chances"][name])["main"]["all"]
                by[s] = {"current": blk["diffs"]["ml-current"][metric],
                         "current_all": blk["diffs"]["ml-current_all"][metric]}
                vals[s] = {m: blk["methods"][m][metric] for m in ("ml", "current", "current_all")}
                vals[s]["n"] = blk["n_rows"]
            nd = 3 if kind == "peak" else 4
            out.append({"target": f"{name} ({role}, out of an org)", "role": role,
                        "winner": verdict_rule(by, "current", "current_all"),
                        "ml": " / ".join(f"{s} {vals[s]['ml']:.{nd}f}" for s in SPLITS),
                        "current": " / ".join(f"{s} {vals[s]['current']:.{nd}f}" for s in SPLITS),
                        "current_all": " / ".join(f"{s} {vals[s]['current_all']:.{nd}f}" for s in SPLITS),
                        "diff_ci": "; ".join(f"{s} ML-current {ci_label(by[s]['current'], nd)}, ML-current_all "
                                             f"{ci_label(by[s]['current_all'], nd)}" for s in SPLITS),
                        "n": {s: vals[s]["n"] for s in SPLITS}})
    return out


IMPORTANCE_TEXT = (
    "From the FIRST run (BLM basis, in-org rows only); a basis without its own importance run shows only this "
    "text. "
    "Pulled from the peak.py and path.py importance runs (permutation importance on held-out fold-0 rows). "
    "Correlated features share credit, so single-feature ranks understate a feature whose partner stays in.\n\n"
    "- Peak (how far a young player climbs): the model mostly asks how old he is, what OOTP's Pot grade says, and "
    "what he is worth today. After that it reads his total batting or pitching points and how much he grew last "
    "year. I think Pot leads partly because OOTP re-rolls Pot up for the players who make it.\n"
    "- Hitters: the TOTAL batting points and last year's total growth move the chances; single skills barely do "
    "(peak.py direction check, ages 18-21, n 20,000: core_int p25 to p75 moves p_useful 0.011 to 0.022, "
    "grow_steps 0 to 2.5 moves it 0.008 to 0.022; babip, eye or pow alone move it 0.0006 or less). Glove is the "
    "smallest family, and a better glove at the same value means slightly less gain (bat over glove).\n"
    "- Pitchers: control is the one single skill that matters (con_mean moves p_useful 0.0122 to 0.0147, n 20,000). "
    "At the same WAA today, value built on PBABIP, groundballs or velocity means less room left, because those "
    "traits do not grow. Last-year growth matters less for pitchers than for hitters.\n"
    "- Year by year (path model): for players 16-26, age, last year's growth, contact and BABIP (hitters) or Ovr "
    "and movement (pitchers), Pot and org level set the speed. Two players the same age do not grow at the same "
    "rate: at 16-22 the model cuts the age-only error by about a third.\n"
    "- Veterans (28-38): age and how good he is now decide most of it. In path.py's 30-34 tables, the top third "
    "of hitters by WAA lose about 0.43 WAA a year against 0.23 for the bottom third (n 9,643 / 9,642), CF lose "
    "0.45 (n 2,121) and C 0.23 (n 3,272), SP lose 0.084 against RP 0.047 (n 13,494 / 28,084). Speed does "
    "nothing (model -0.339 / -0.342 / -0.326 at speed 40 / 50 / 60, n 5,735)."
)


# ----------------------------------------------------------------- main
def have_outside():
    return all(os.path.exists(os.path.join(C.PREDS_DIR, stem + "_outside.pkl")) for stem in PEAK_METHODS.values())


def run(args):
    t0 = time.time()
    R = {s: {} for s in SPLITS}
    OUT = {s: {} for s in SPLITS}
    coverage = {s: {} for s in SPLITS}
    do_out = have_outside()
    log(f"basis {C.BASIS}, splits {', '.join(SPLITS)}, out-of-org section {'on' if do_out else 'off (no files)'}")
    for role in C.ROLES:
        log(f"loading truth {role}")
        truth = load_truth(role)
        log(f"building peak frame {role}")
        PF, _ = build_peak_frame(role, truth)
        PF = PF[PF["split"].isin(SPLITS)]
        log(f"building path frame {role}")
        TF = build_path_frame(role, truth)
        TF = TF[TF["split"].isin(SPLITS)]
        OF = None
        if do_out:
            log(f"building out-of-org peak frame {role}")
            OF, _ = build_peak_frame(role, truth, "_outside")
            OF = OF[OF["split"].isin(SPLITS)]
        del truth
        if args.quick:
            keep = np.unique(np.r_[PF["pid"].to_numpy(), TF["pid"].to_numpy()])
            keep = keep[rng_for(args.seed, "quick", role).random(len(keep)) < 0.2]
            PF = PF[PF["pid"].isin(keep)]
            TF = TF[TF["pid"].isin(keep)]
        for s in SPLITS:
            ps = PF[PF["split"] == s].reset_index(drop=True)
            ts = TF[TF["split"] == s].reset_index(drop=True)
            log(f"{s} {role}: peak rows {len(ps):,}, path rows {len(ts):,}")
            cov = {"peak": {}, "path": {}}
            for m in PEAK_METHODS:
                cov["peak"][m] = {"rows": int(len(ps)), "answered": int(ps[f"{m}__gain_q50"].notna().sum())}
            for m in PATH_METHODS:
                cov["path"][m] = {"rows": int(len(ts)), "answered": int(ts[f"{m}__d1"].notna().sum())}
            coverage[s][role] = cov
            pids = np.unique(np.r_[ps["pid"].to_numpy(), ts["pid"].to_numpy()])
            boot = Boot(pids, args.boot, args.seed, f"{s}{role}")
            views = ["main"]
            needs_fill = any(ps[c].isna().any() for c in ps.columns if "__" in c)
            if needs_fill:
                views.append("filled")
            blk = {}
            log("  peak")
            blk["peak"] = score_peak(ps, boot, views)
            log("  chances")
            blk["chances"] = score_chances(ps, boot, views, args.eps, not args.no_auc_ci)
            log("  top 10 percent")
            blk["top10"] = top10(ps, args.seed, f"{s}{role}")
            log("  path")
            blk["path"] = score_path(ts, boot)
            R[s][role] = blk
            del boot
            if OF is not None:
                os_ = OF[OF["split"] == s].reset_index(drop=True)
                if len(os_):
                    log(f"  out-of-org rows {len(os_):,}")
                    ob = Boot(np.unique(os_["pid"].to_numpy()), args.boot, args.seed, f"{s}{role}out")
                    ov = ["main"] + (["filled"] if any(os_[c].isna().any() for c in os_.columns if "__" in c)
                                     else [])
                    OUT[s][role] = {"peak": score_peak(os_, ob, ov, outside_subset_masks),
                                    "chances": score_chances(os_, ob, ov, args.eps, False, outside_subset_masks),
                                    "coverage": {m: {"rows": int(len(os_)),
                                                     "answered": int(os_[f"{m}__gain_q50"].notna().sum())}
                                                 for m in PEAK_METHODS}}
                    del ob
        del PF, TF, OF
    V, SURV = verdicts(R)
    SUBV = subset_verdicts(R)
    OUTV = outside_verdicts(OUT) if do_out else []
    IMP = importance_summary()
    meta = {"generated": _dt.datetime.now().isoformat(timespec="seconds"), "basis": C.BASIS,
            "splits": list(SPLITS), "boot": args.boot, "eps": args.eps,
            "seed": args.seed, "quick": bool(args.quick), "coverage": coverage,
            "importance_text": IMPORTANCE_TEXT, "plain": plain_words(R, V, SURV), "notes": notes(R)}
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    suffix = "_quick" if args.quick else ""
    jpath = os.path.join(C.REPORT_DIR, f"report{suffix}.json")
    mpath = os.path.join(C.REPORT_DIR, f"report{suffix}.md")
    rep = {"meta": meta, "decision_rule": RULE_TEXT, "verdicts": V, "survivorship": SURV,
           "subset_verdicts": SUBV, "results": R, "outside_verdicts": OUTV, "outside": OUT, "importance": IMP}
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    write_md(R, V, SURV, SUBV, IMP, meta, mpath, OUT if do_out else None, OUTV)
    log(f"wrote {jpath}")
    log(f"wrote {mpath}")
    log(f"done in {time.time() - t0:.0f} s")
    for v in V + OUTV:
        log(f"  {v['target']}: {v['winner']} | ML {v['ml']} | current {v['current']} | current_all {v['current_all']}")


def plain_words(R, V, SURV):
    """Short generated summary from the numbers (the report's own words)."""
    wins = [v["target"] for v in V if v["winner"] == "ML wins"]
    lose = [v["target"] for v in V if v["winner"] == "current wins"]
    none = [v["target"] for v in V if v["winner"] == "no clear win"]
    lines = [f"ML wins {len(wins)} of {len(V)} targets under the rule: {', '.join(wins) if wins else 'none'}."]
    if lose:
        lines.append(f"The current method wins: {', '.join(lose)}.")
    if none:
        lines.append(f"No clear win: {', '.join(none)}.")
    for role in C.ROLES:
        try:
            ab = R["time"][role]["top10"]["p_useful"]["19"]
            m = ab["methods"]
            lines.append(
                f"{'Hitters' if role == 'H' else 'Pitchers'} at 19, time split: of the top 10% by each method "
                f"(n {ab['top_n']:,} of {ab['n_rows']:,}), ML's picks reached useful {m['ml']['useful']:.1%} of the "
                f"time ({m['ml']['n_useful']:,}), current's {m['current']['useful']:.1%} "
                f"({m['current']['n_useful']:,}), current_all's {m['current_all']['useful']:.1%} "
                f"({m['current_all']['n_useful']:,}); all 19-year-olds {ab['base_useful']:.1%}.")
        except KeyError:
            pass
    return " ".join(lines)


def notes(R):
    return [
        "Rows: peak group = DEV rows at ages 16-26, in an org, with a known outcome (seen at 27+ or retired). "
        "Path group = rows at ages 16-38 present the next year. oof = 5 grouped folds by player; time = fit on "
        "players first seen by 2144, tested on later ones.",
        "The bootstrap resamples players (every row of a drawn player comes along), so the intervals account for "
        "one player appearing at several ages.",
        "Log loss clips every probability to [eps, 1 - eps]. The cell methods give exactly 0 on many rows below "
        "the bar (see 'Share at exactly 0'), so an unclipped log loss would be infinite for them. The clip helps "
        "the cell methods more than ML; Brier needs no clip and is reported next to it.",
        "p_regular: ML and the refit cells are scored on regular_future. The app's own column (current_makeit) "
        "was fit on regular_ever, which also counts seasons already played.",
        "current = the app's cells on the first-20 cohort without the 2025-2040 window; current_w40 = the app's "
        "exact cohort; current_all = the same cells on every finished career (realized or retired).",
        "Path: the decision compares ML with current_path (the app's measuredPath) and age_mean (role x age mean "
        "change), because the path has no current_all. ML's d1..d5 are medians; ml_mean is the squared-loss "
        "model of the same horizon (d1_mean..d5_mean, fix 5).",
        f"Basis {C.BASIS}: the DEV rows are priced with the {C.BASIS} engine calibration; the cell methods are refit "
        "on the same rows, so every method sees the same WAA scale.",
        "d3 and d5 are scored only where the player is still in the league and priced k years later (survivors).",
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score the ML models against the current method on the same held-out DEV rows and write "
                    ".dev_cache/ml/report/report.json and report.md.")
    ap.add_argument("--boot", type=int, default=300, help="bootstrap resamples over players (default 300)")
    ap.add_argument("--eps", type=float, default=1e-3, help="probability clip for log loss (default 0.001)")
    ap.add_argument("--seed", type=int, default=20260924, help="random seed")
    ap.add_argument("--no-auc-ci", action="store_true", help="skip the bootstrap interval of AUC differences")
    ap.add_argument("--quick", action="store_true",
                    help="smoke test: 20%% of players, 60 resamples, writes report_quick.*")
    ap.add_argument("--basis", required=True, choices=list(C.BASES),
                    help="engine calibration of the DEV rows = the league the models serve")
    ap.add_argument("--splits", default="oof,time", help="comma list of oof, time (default both)")
    args = ap.parse_args(argv)
    if args.quick:
        args.boot = min(args.boot, 60)
    C.use_basis(args.basis)
    global SPLITS
    SPLITS = tuple(s for s in ("oof", "time") if s in {x.strip() for x in args.splits.split(",")})
    if not SPLITS:
        raise SystemExit("--splits needs oof and / or time")
    run(args)


if __name__ == "__main__":
    main()
