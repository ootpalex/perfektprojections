"""
eval_history.py - does the player's older record (the history inputs) make the
DEV machine-learning models better? A head-to-head test on the time split.

User, 2026-09-25: "oh yeah it should absolutely use all of the seasons it
already has on file i always assumed it did".

Two model sets per role, same tuned settings (models/peak_settings.json,
models/path_settings.json), same training players, same test players:
  A  CURRENT  the live features (schema_<basis>.json, usable_for_scoring)
              plus 'amateur'; trained on the rows as they are
  B  HISTORY  the live features plus the history inputs
              (schema_<basis>_hist.json); trained with the archive-depth mask
              (common.apply_archive_depth on the row's sim_depth)
Both read the _hist tables (every shared column equals the live tables).

Split: time_split (players first seen after the cutoff are the test side).
Test rows are scored in three views, each built with apply_archive_depth on a
forced depth, for BOTH A and B:
  full   depth -1: the record as DEV has it
  one    depth 1: one recorded season at most (about what TGS holds today)
  none   depth 0: no earlier season at all; the one-year growth inputs of A
         are unknown too (has_prev 0), as for a player with no earlier pull
  two    depth 2 (extra, not in the decision rule): TGS's 1.68 game-years of
         archive read like 2 in the model's bins

Models fit (the headline targets only):
  peak  rows age 16-26, peak_known (in an org and out, as the live fit):
        gain_q50 (clipped at 0), reach_mlb, reach_useful, reach_good,
        regular_future; the app bar rule and chance_order apply
  path  rows age 16-38, present_1 == 1: d1, d3 (the tuned loss)

Scoring (report command): peak rows in an org (the compare.py main rows);
path rows all. Peak MAE = |now + gain_q50 - peak|. Chances: log loss (clip
0.001) and AUC on rows below the bar line (now < bar - 0.05; regular_future
on rows where it is known). Path MAE of d1 and d3 by age band. B minus A with
a 95 percent interval from a bootstrap over players (every row of a drawn
player comes along).

Commands (Python 3.14):
  eval_history.py fit    --basis BLM --role H   fit A and B, predict the views,
                                                permutation importance of B
  eval_history.py report --basis BLM            bootstrap, decision rule,
                                                report.json and report.md
  --quick   about 10 percent of players (smoke test; writes under quick/)

Outputs: .dev_cache/ml/report/history/<basis>/ (preds_<role>.pkl,
fit_<role>.json, importance_<role>.json, report.json, report.md). Nothing
under models/, preds/, vintages/ or public/ is written.
"""
import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C                     # noqa: E402
import peak as PK                      # noqa: E402
import path as PH                      # noqa: E402
from compare import AUC, Boot, logloss_rows   # noqa: E402

VIEWS = {"full": -1, "two": 2, "one": 1, "none": 0}    # "two" is extra: TGS reads as about 2 today
PEAK_T = ["gain_q50", "reach_mlb", "reach_useful", "reach_good", "regular_future"]
PATH_T = ["d1", "d3"]
CH = {"reach_mlb": ("p_mlb", C.PEAK_BARS["mlb"]), "reach_useful": ("p_useful", C.PEAK_BARS["useful"]),
      "reach_good": ("p_good", C.PEAK_BARS["good"]), "regular_future": ("p_regular", None)}
BAR_TOL = 0.05
EPS = 1e-3
PEAK_SUBSETS = ("all", "prospects", "age16_19", "age20_22", "age23_26")
PATH_BANDS = (("all", 16, 38), ("16-22", 16, 22), ("23-27", 23, 27), ("28-32", 28, 32), ("33-38", 33, 38))
TRUTH = ["pid", "dump_year", "age", "pot", "now_waa", "in_org", "peak", "gain", "reach_mlb", "reach_useful",
         "reach_good", "regular_future", "d_1", "d_3", "present_1", "peak_known", "time_split", "fold",
         "lev_raw", "sim_depth"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def out_dir(basis, quick):
    d = os.path.join(C.REPORT_ROOT, "history", basis, "quick" if quick else "")
    os.makedirs(d, exist_ok=True)
    return d


def quick_keep(pids, share=0.10):
    u = np.unique(pids)
    keep = {p for p in u if int(hashlib.md5(f"hq:{p}".encode()).hexdigest()[:8], 16) % 1000 < share * 1000}
    return np.fromiter((p in keep for p in pids), dtype=bool, count=len(pids))


# ---------------------------------------------------------------- features
def feature_sets(role, basis):
    live = C.usable_features(role, schema=json.load(open(os.path.join(
        C.DATA_DIR, f"schema_{basis}.json"), encoding="utf-8")))
    hs = json.load(open(os.path.join(C.DATA_DIR, f"schema_{basis}_hist.json"), encoding="utf-8"))
    hist = C.usable_features(role, schema=hs)
    fam = {c["name"]: c.get("family") for c in hs["roles"][role]["columns"] if c.get("kind") == "feature"}
    A = live + list(C.MODEL_EXTRA_FEATURES)
    B = hist + list(C.MODEL_EXTRA_FEATURES)
    missing = [f for f in A if f not in B]
    if missing:
        raise SystemExit(f"live features missing from the history schema: {missing}")
    return A, B, fam


def hist_subfamily(name):
    """Finer families of the history inputs (for the importance tables)."""
    if name.startswith("h1_"):
        return "hist_1yr"
    if name.startswith("h2_"):
        return "hist_2yr"
    if name.startswith("h3_"):
        return "hist_3yr"
    if name in ("h_grow_int_prev", "h_accel", "h_grow_int_max3"):
        return "hist_accel"
    if name in ("seasons_recorded", "archive_depth"):
        return "hist_depth"
    if name.startswith("rec_g_") or name.startswith("rec_grow"):
        return "rec_growth"
    if name.startswith("rec_d_pot") or name.startswith("rec_pot"):
        return "rec_pot"
    if name in ("rec_d_now_ps", "rec_now_best", "rec_now_below_best", "rec_seasons_since_best"):
        return "rec_value"
    return "rec_level_org"          # rec_age_start, rec_level_start, rec_d_level_ps, rec_seasons_*


def load_rows(role, feats_B, quick):
    t0 = time.time()
    df = C.load_table(C.dev_table(role))
    log(f"[{role}] read {os.path.basename(C.dev_table(role))}: {len(df):,} rows, {df.shape[1]} columns "
        f"({time.time() - t0:.0f}s)")
    age = df["age"]
    peak_g = (age >= 16) & (age <= 26) & (df["peak_known"] == 1)
    path_g = (age >= PH.AGE_LO) & (age <= PH.AGE_HI) & (df["present_1"] == 1)
    keep = peak_g | path_g
    if quick:
        keep &= quick_keep(df["pid"].to_numpy())
    feat_cols = [f for f in feats_B if f not in C.MODEL_EXTRA_FEATURES]
    cols = list(dict.fromkeys(TRUTH + feat_cols + [c for c in C.hist_window_columns(role) if c in df.columns]))
    out = df.loc[keep, cols].reset_index(drop=True)
    del df
    C.add_model_extras(out, C.MODEL_EXTRA_FEATURES)
    out["g_peak"] = ((out["age"] >= 16) & (out["age"] <= 26) & (out["peak_known"] == 1)).to_numpy()
    out["g_path"] = ((out["age"] >= PH.AGE_LO) & (out["age"] <= PH.AGE_HI) & (out["present_1"] == 1)).to_numpy()
    log(f"[{role}] kept {len(out):,} rows (peak group {int(out['g_peak'].sum()):,}, path group "
        f"{int(out['g_path'].sum()):,}), {out.shape[1]} columns")
    return out


# ---------------------------------------------------------------- fitting
def fit_models(role, tr, feats, pk_st, ph_params, ph_loss, tag):
    """Fit the peak and path models on training rows tr. Returns {name: fit}."""
    fits = {}
    P = tr.loc[tr["g_peak"]].reset_index(drop=True)
    val = PK.val_mask(P["pid"].to_numpy(), pk_st["val_share"])
    for t in PEAK_T:
        fits[t] = PK.fit_one(t, P, feats, pk_st, val, log_prefix=f"[{role} {tag}] ")
    del P
    Q = tr.loc[tr["g_path"]].reset_index(drop=True)
    qval = PH.val_flag(Q["pid"].to_numpy())
    for name in PATH_T:
        t0 = time.time()
        y = Q[f"d_{name[1:]}"].to_numpy(dtype=np.float64)
        ok = ~np.isnan(y)
        m = PH.make_reg(ph_params, ph_loss[name])
        m = PH.fit_es(m, Q.loc[ok, feats], y[ok], qval[ok])
        fits[name] = {"model": m, "iso": None, "n_train": int(ok.sum()), "n_iter": int(m.n_iter_)}
        log(f"[{role} {tag}] {name}: n {int(ok.sum()):,} iters {m.n_iter_} ({time.time() - t0:.0f}s)")
    del Q
    return fits


def predict_peak(fits, df, feats):
    X = df[feats]
    out = {"gain_q50": np.maximum(fits["gain_q50"]["model"].predict(X), 0.0)}
    now = df["now_waa"].to_numpy()
    for t in ("reach_mlb", "reach_useful", "reach_good"):
        col, bar = CH[t]
        p = PK.prob(fits[t], X)
        out[col] = np.where(now >= bar - BAR_TOL, 1.0, p)
    out["p_mlb"], out["p_useful"], out["p_good"] = C.chance_order(out["p_mlb"], out["p_useful"], out["p_good"])
    out["p_regular"] = PK.prob(fits["regular_future"], X)
    return {k: np.asarray(v, dtype=np.float32) for k, v in out.items()}


def predict_path(fits, df, feats):
    X = df[feats]
    return {n: fits[n]["model"].predict(X).astype(np.float32) for n in PATH_T}


def view_frame(te, role, depth):
    t = te.copy(deep=False)
    t["sim_depth"] = np.int8(depth)
    return C.apply_archive_depth(t, role)


# ---------------------------------------------------------------- importance
def perm_block(score_fn, X, cols_by_group, rng, repeats):
    base = score_fn(X)
    res = {}
    for g, cols in cols_by_group.items():
        vals = []
        for _ in range(repeats):
            Xp = X.copy()
            perm = rng.permutation(len(X))
            for c in cols:
                if isinstance(X[c].dtype, pd.CategoricalDtype):
                    Xp[c] = pd.Categorical.from_codes(X[c].cat.codes.to_numpy()[perm], dtype=X[c].dtype)
                else:
                    Xp[c] = X[c].to_numpy()[perm]
            vals.append(score_fn(Xp) - base)
        res[g] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals)), "share_of_base": float(np.mean(vals) / base)}
    return base, res


def importance(role, fits, te_full, feats, fam, n_rows, repeats):
    rng = np.random.default_rng(11)
    groups = {}
    for f in feats:
        g = fam.get(f) or "context"
        if g == "history":
            g = hist_subfamily(f)
        groups.setdefault(g, []).append(f)
    hist_all = [f for f in feats if fam.get(f) == "history"]
    fam_groups = dict(groups)
    fam_groups["history (all)"] = hist_all
    single = {f: [f] for f in feats}
    out = {"families": groups, "n_rows": n_rows, "repeats": repeats,
           "rows_note": "time-split test rows, full-history view, sampled"}
    age = te_full["age"].to_numpy()
    jobs = []
    pk = te_full["g_peak"].to_numpy() & (te_full["in_org"] == 1).to_numpy()
    jobs.append(("gain_q50 (peak MAE)", pk & te_full["gain"].notna().to_numpy(), "gain_q50"))
    bar = C.PEAK_BARS["useful"]
    jobs.append(("reach_useful (log loss)", pk & te_full["reach_useful"].notna().to_numpy()
                 & (te_full["now_waa"] < bar - BAR_TOL).to_numpy(), "reach_useful"))
    ph = te_full["g_path"].to_numpy() & te_full["d_1"].notna().to_numpy()
    jobs.append(("d1 ages 16-22 (MAE)", ph & (age <= 22), "d1"))
    jobs.append(("d1 ages 28-38 (MAE)", ph & (age >= 28), "d1"))
    for label, mask, t in jobs:
        sub = te_full.loc[mask]
        if len(sub) > n_rows:
            sub = sub.sample(n_rows, random_state=0)
        X = sub[feats].reset_index(drop=True)
        if t == "gain_q50":
            y = sub["gain"].to_numpy()
            m = fits[t]["model"]
            fn = lambda Z: float(np.mean(np.abs(np.maximum(m.predict(Z), 0.0) - y)))  # noqa: E731
        elif t == "d1":
            y = sub["d_1"].to_numpy()
            m = fits[t]["model"]
            fn = lambda Z: float(np.mean(np.abs(m.predict(Z) - y)))  # noqa: E731
        else:
            y = sub[t].to_numpy().astype(float)
            ft = fits[t]
            fn = lambda Z: float(np.mean(logloss_rows(PK.prob(ft, Z), y, EPS)))  # noqa: E731
        t0 = time.time()
        base, famres = perm_block(fn, X, fam_groups, rng, repeats)
        _b, featres = perm_block(fn, X, single, rng, repeats)
        top = sorted(featres.items(), key=lambda kv: -kv[1]["mean"])
        top_hist = [kv for kv in top if fam.get(kv[0]) == "history"]
        out[label] = {"n_rows": int(len(X)), "base_loss": base,
                      "family": dict(sorted(famres.items(), key=lambda kv: -kv[1]["mean"])),
                      "top10": [{"feature": k, "family": fam.get(k) or "context", **v} for k, v in top[:10]],
                      "top10_history": [{"feature": k, "subfamily": hist_subfamily(k), **v}
                                        for k, v in top_hist[:10]]}
        log(f"[{role} importance] {label}: base {base:.5f}, history (all) "
            f"{famres['history (all)']['mean']:+.5f} ({time.time() - t0:.0f}s)")
    return out


# ---------------------------------------------------------------- fit command
def cmd_fit(args):
    basis, role = args.basis, args.role
    C.use_basis(basis)
    C.use_history(True)
    od = out_dir(basis, args.quick)
    featA, featB, fam = feature_sets(role, basis)
    log(f"[{role}] basis {basis}: A {len(featA)} features, B {len(featB)} features")
    df = load_rows(role, featB, args.quick)
    pk_st = PK.load_settings()[role]
    ph_params, ph_loss = PH.role_settings(PH.load_settings(), role)
    trm = (df["time_split"] == "train").to_numpy()
    tr_raw = df.loc[trm].reset_index(drop=True)
    te = df.loc[~trm].reset_index(drop=True)
    del df
    log(f"[{role}] train {len(tr_raw):,} rows ({tr_raw['pid'].nunique():,} players), test {len(te):,} rows "
        f"({te['pid'].nunique():,} players)")
    info = {"basis": basis, "role": role, "quick": bool(args.quick), "features_A": featA, "features_B": featB,
            "peak_settings": pk_st, "path_params": ph_params, "path_loss": {k: ph_loss[k] for k in PATH_T},
            "sim_depth_train": {str(k): int(v) for k, v in tr_raw["sim_depth"].value_counts().sort_index().items()},
            "n_train_rows": int(len(tr_raw)), "n_test_rows": int(len(te)), "fits": {}}

    # views of the test rows (the same frames serve A and B)
    views = {v: view_frame(te, role, d) for v, d in VIEWS.items()}
    keep_cols = ["pid", "dump_year", "age", "pot", "now_waa", "in_org", "peak", "gain", "reach_mlb",
                 "reach_useful", "reach_good", "regular_future", "d_1", "d_3", "g_peak", "g_path", "sim_depth"]
    PKo = te.loc[te["g_peak"], keep_cols].reset_index(drop=True)
    PKo["seasons_recorded_full"] = views["full"].loc[te["g_peak"].to_numpy(), "seasons_recorded"].to_numpy()
    PHo = te.loc[te["g_path"], keep_cols].reset_index(drop=True)
    PHo["seasons_recorded_full"] = views["full"].loc[te["g_path"].to_numpy(), "seasons_recorded"].to_numpy()
    del te

    t0 = time.time()
    fitsA = fit_models(role, tr_raw, featA, pk_st, ph_params, ph_loss, "A")
    info["fits"]["A"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("model", "iso")} for k, v in fitsA.items()}
    log(f"[{role}] A fit in {time.time() - t0:.0f}s")
    for v, fr in views.items():
        pp = predict_peak(fitsA, fr.loc[fr["g_peak"]], featA)
        for k, a in pp.items():
            PKo[f"A_{v}__{k}"] = a
        qq = predict_path(fitsA, fr.loc[fr["g_path"]], featA)
        for k, a in qq.items():
            PHo[f"A_{v}__{k}"] = a
    del fitsA

    t0 = time.time()
    trB = C.apply_archive_depth(tr_raw, role)
    del tr_raw
    log(f"[{role}] archive-depth mask applied to {len(trB):,} training rows ({time.time() - t0:.0f}s)")
    t0 = time.time()
    fitsB = fit_models(role, trB, featB, pk_st, ph_params, ph_loss, "B")
    info["fits"]["B"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("model", "iso")} for k, v in fitsB.items()}
    log(f"[{role}] B fit in {time.time() - t0:.0f}s")
    del trB
    for v, fr in views.items():
        pp = predict_peak(fitsB, fr.loc[fr["g_peak"]], featB)
        for k, a in pp.items():
            PKo[f"B_{v}__{k}"] = a
        qq = predict_path(fitsB, fr.loc[fr["g_path"]], featB)
        for k, a in qq.items():
            PHo[f"B_{v}__{k}"] = a

    C.save_table(PKo, os.path.join(od, f"preds_peak_{role}.pkl"))
    C.save_table(PHo, os.path.join(od, f"preds_path_{role}.pkl"))
    with open(os.path.join(od, f"fit_{role}.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1, default=str)
    log(f"[{role}] wrote predictions: peak {len(PKo):,} rows, path {len(PHo):,} rows")

    if not args.no_importance:
        imp = importance(role, fitsB, views["full"], featB, fam,
                         n_rows=4000 if args.quick else args.imp_rows, repeats=args.imp_repeats)
        with open(os.path.join(od, f"importance_{role}.json"), "w", encoding="utf-8") as fh:
            json.dump(imp, fh, indent=1)
        log(f"[{role}] wrote importance")


# ---------------------------------------------------------------- report command
def peak_masks(df):
    age = df["age"].to_numpy()
    pot = df["pot"].to_numpy()
    return {"all": np.ones(len(df), bool), "prospects": (pot >= 45) & (age >= 17) & (age <= 22),
            "age16_19": (age >= 16) & (age <= 19), "age20_22": (age >= 20) & (age <= 22),
            "age23_26": (age >= 23) & (age <= 26)}


def ci(boot, pidx, vals):
    return boot.mean_ci(pidx, vals)


def auc_ci(boot, pidx, pa, pb, y):
    """AUC of A and B and the bootstrap interval of B - A (players resampled)."""
    aA, aB = AUC(pa, y), AUC(pb, y)
    n = len(boot.uniq)
    est = aB() - aA()
    diffs = []
    for b in range(boot.B):
        w = boot.W[b][pidx].astype(np.float64)
        diffs.append(aB(w) - aA(w))
    lo, hi = np.nanpercentile(diffs, [2.5, 97.5])
    return aA(), aB(), {"est": float(est), "lo": float(lo), "hi": float(hi)}, n


def score_role(role, PKo, PHo, nboot, seed):
    boot = Boot(np.unique(np.concatenate([PKo["pid"].to_numpy(), PHo["pid"].to_numpy()])), nboot, seed, role)
    R = {"peak": {}, "chances": {}, "path": {}}
    S = PKo.loc[PKo["in_org"] == 1].reset_index(drop=True)
    pidx = boot.idx(S["pid"].to_numpy())
    masks = peak_masks(S)
    now = S["now_waa"].to_numpy(dtype=np.float64)
    peak = S["peak"].to_numpy(dtype=np.float64)
    rec = S["seasons_recorded_full"].to_numpy()
    for v in VIEWS:
        R["peak"][v], R["chances"][v] = {}, {}
        ea = np.abs(now + S[f"A_{v}__gain_q50"].to_numpy(np.float64) - peak)
        eb = np.abs(now + S[f"B_{v}__gain_q50"].to_numpy(np.float64) - peak)
        ok = np.isfinite(peak)
        for sub, mk in masks.items():
            r = ok & mk
            R["peak"][v][sub] = {"n_rows": int(r.sum()), "n_players": int(len(np.unique(pidx[r]))),
                                 "A": float(ea[r].mean()), "B": float(eb[r].mean()),
                                 "B_minus_A": ci(boot, pidx[r], eb[r] - ea[r]),
                                 "seasons_recorded_mean": float(np.nanmean(rec[r]))}
        for t, (col, bar) in CH.items():
            y = S[t].to_numpy(dtype=np.float64)
            scope = np.isfinite(y)
            if bar is not None:
                scope &= now < bar - BAR_TOL
            pa = S[f"A_{v}__{col}"].to_numpy(np.float64)
            pb = S[f"B_{v}__{col}"].to_numpy(np.float64)
            la, lb = logloss_rows(pa, y, EPS), logloss_rows(pb, y, EPS)
            tb = {}
            for sub, mk in masks.items():
                r = scope & mk
                if r.sum() == 0 or np.nansum(y[r]) == 0:
                    continue
                aA, aB, dA, _n = auc_ci(boot, pidx[r], pa[r], pb[r], y[r])
                tb[sub] = {"n_rows": int(r.sum()), "n_pos": int(np.nansum(y[r])),
                           "n_players": int(len(np.unique(pidx[r]))),
                           "logloss": {"A": float(la[r].mean()), "B": float(lb[r].mean()),
                                       "B_minus_A": ci(boot, pidx[r], lb[r] - la[r])},
                           "auc": {"A": aA, "B": aB, "B_minus_A": dA}}
            R["chances"][v][t] = tb
    T = PHo
    pidx = boot.idx(T["pid"].to_numpy())
    age = T["age"].to_numpy()
    for v in VIEWS:
        R["path"][v] = {}
        for name in PATH_T:
            y = T[f"d_{name[1:]}"].to_numpy(dtype=np.float64)
            ea = np.abs(T[f"A_{v}__{name}"].to_numpy(np.float64) - y)
            eb = np.abs(T[f"B_{v}__{name}"].to_numpy(np.float64) - y)
            hb = {}
            for band, lo, hi in PATH_BANDS:
                r = np.isfinite(y) & (age >= lo) & (age <= hi)
                if r.sum() == 0:
                    continue
                hb[band] = {"n_rows": int(r.sum()), "n_players": int(len(np.unique(pidx[r]))),
                            "A": float(ea[r].mean()), "B": float(eb[r].mean()),
                            "B_minus_A": ci(boot, pidx[r], eb[r] - ea[r])}
            R["path"][v][name] = hb
    return R


HEADLINE = [("peak MAE", lambda R, v: R["peak"][v]["all"]["B_minus_A"]),
            ("reach_mlb log loss", lambda R, v: R["chances"][v]["reach_mlb"]["all"]["logloss"]["B_minus_A"]),
            ("reach_useful log loss", lambda R, v: R["chances"][v]["reach_useful"]["all"]["logloss"]["B_minus_A"]),
            ("reach_good log loss", lambda R, v: R["chances"][v]["reach_good"]["all"]["logloss"]["B_minus_A"]),
            ("regular_future log loss",
             lambda R, v: R["chances"][v]["regular_future"]["all"]["logloss"]["B_minus_A"]),
            ("path d1 MAE", lambda R, v: R["path"][v]["d1"]["all"]["B_minus_A"]),
            ("path d3 MAE", lambda R, v: R["path"][v]["d3"]["all"]["B_minus_A"])]
MUST_WIN = ("reach_useful log loss", "reach_mlb log loss", "peak MAE")


def decide(R):
    head = {n: {v: f(R, v) for v in VIEWS} for n, f in HEADLINE}
    wins = {n: head[n]["full"]["hi"] < 0 for n in MUST_WIN}
    worse = {v: [n for n in head if head[n][v]["lo"] > 0] for v in ("one", "none")}
    ok = all(wins.values()) and not worse["one"] and not worse["none"]
    return {"adopt": bool(ok), "full_view_wins": wins, "worse_beyond_noise": worse, "headline": head}


def ci_s(d, nd=4):
    return f"{d['est']:+.{nd}f} [{d['lo']:+.{nd}f}, {d['hi']:+.{nd}f}]"


def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def write_md(basis, RR, DD, IMP, FIT, path, nboot):
    L = []
    adopt = all(DD[r]["adopt"] for r in RR)
    L.append(f"# History inputs: A (current) vs B (history), {basis} basis, time split")
    L.append("")
    L.append("## Decision rule (stated before the numbers)")
    L.append("")
    L.append("Adopt B when, per role (H and P both), (1) on the full-history view B lowers the reach_useful log "
             "loss, the reach_mlb log loss and the peak MAE with the 95% interval of B - A below zero, and (2) on "
             "the 1-season and no-history views B is not worse than A beyond its own bootstrap noise (95% interval "
             "of B - A entirely above zero) on any headline target: peak MAE, the reach_mlb / reach_useful / "
             "reach_good / regular_future log loss, path d1 and d3 MAE (all ages). Otherwise do not adopt.")
    L.append("")
    L.append(f"**Verdict: {'ADOPT B' if adopt else 'DO NOT ADOPT'}** "
             + ", ".join(f"{r}: {'pass' if DD[r]['adopt'] else 'fail'}" for r in RR))
    L.append("")
    for r in RR:
        d = DD[r]
        L.append(f"- {r}: full-view wins " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in d["full_view_wins"].items())
                 + "; worse beyond noise: one-season " + (", ".join(d["worse_beyond_noise"]["one"]) or "none")
                 + "; no-history " + (", ".join(d["worse_beyond_noise"]["none"]) or "none"))
    L.append("")
    L.append(f"Bootstrap: {nboot} resamples over players. Lower is better for every loss; B - A below zero means "
             "history helps. AUC: higher is better.")
    L.append("")
    for r in RR:
        R = RR[r]
        fit = FIT.get(r, {})
        L.append(f"## Role {r}")
        L.append("")
        if fit:
            L.append(f"Features: A {len(fit['features_A'])}, B {len(fit['features_B'])}. Training rows {fit['n_train_rows']:,}, "
                     f"test rows {fit['n_test_rows']:,}. Training sim_depth counts: {fit['sim_depth_train']}.")
            L.append("")
        L.append("### Headline, B - A (95% interval)")
        L.append("")
        rows = []
        for n, f in HEADLINE:
            rows.append([n] + [ci_s(f(R, v)) for v in VIEWS])
        L.append(md_table(["target", "full", "two seasons (extra)", "one season", "no history"], rows))
        L.append("")
        L.append("### Peak MAE (in an org, ages 16-26)")
        L.append("")
        rows = []
        for v in VIEWS:
            for sub, b in R["peak"][v].items():
                rows.append([v, sub, f"{b['n_rows']:,} ({b['n_players']:,} pl)", f"{b['seasons_recorded_mean']:.2f}",
                             f"{b['A']:.4f}", f"{b['B']:.4f}", ci_s(b["B_minus_A"])])
        L.append(md_table(["view", "subset", "n rows (players)", "seasons rec. (full)", "A", "B", "B - A"], rows))
        L.append("")
        L.append("### Chances (below the bar line; regular_future where known)")
        L.append("")
        rows = []
        for v in VIEWS:
            for t, tb in R["chances"][v].items():
                for sub in ("all", "prospects", "age16_19", "age20_22", "age23_26"):
                    if sub not in tb:
                        continue
                    b = tb[sub]
                    rows.append([v, t, sub, f"{b['n_rows']:,} / {b['n_pos']:,}",
                                 f"{b['logloss']['A']:.5f}", f"{b['logloss']['B']:.5f}", ci_s(b["logloss"]["B_minus_A"], 5),
                                 f"{b['auc']['A']:.4f}", f"{b['auc']['B']:.4f}", ci_s(b["auc"]["B_minus_A"], 4)])
        L.append(md_table(["view", "target", "subset", "n rows / pos", "LL A", "LL B", "LL B - A", "AUC A", "AUC B",
                           "AUC B - A"], rows))
        L.append("")
        L.append("### Path MAE by age band (ages 16-38, in the league next year)")
        L.append("")
        rows = []
        for v in VIEWS:
            for name, hb in R["path"][v].items():
                for band, b in hb.items():
                    rows.append([v, name, band, f"{b['n_rows']:,}", f"{b['A']:.4f}", f"{b['B']:.4f}", ci_s(b["B_minus_A"])])
        L.append(md_table(["view", "target", "ages", "n rows", "A", "B", "B - A"], rows))
        L.append("")
        imp = IMP.get(r)
        if imp:
            L.append("### What matters in B (permutation importance, full view, loss increase when shuffled)")
            L.append("")
            for label in [k for k in imp if isinstance(imp[k], dict) and "family" in imp[k]]:
                b = imp[label]
                L.append(f"**{label}** (n={b['n_rows']:,}, base loss {b['base_loss']:.5f})")
                L.append("")
                rows = [[g, f"{x['mean']:+.5f}", f"{100 * x['share_of_base']:+.2f}%"] for g, x in b["family"].items()]
                L.append(md_table(["family", "loss increase", "share of base"], rows))
                L.append("")
                rows = [[x["feature"], x["subfamily"], f"{x['mean']:+.5f}"] for x in b["top10_history"]]
                L.append("Top 10 history inputs:")
                L.append("")
                L.append(md_table(["input", "subfamily", "loss increase"], rows))
                L.append("")
                rows = [[x["feature"], x["family"], f"{x['mean']:+.5f}"] for x in b["top10"]]
                L.append("Top 10 inputs overall:")
                L.append("")
                L.append(md_table(["input", "family", "loss increase"], rows))
                L.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def cmd_report(args):
    C.use_basis(args.basis)
    od = out_dir(args.basis, args.quick)
    RR, DD, IMP, FIT = {}, {}, {}, {}
    for role in args.roles:
        pk = os.path.join(od, f"preds_peak_{role}.pkl")
        if not os.path.exists(pk):
            log(f"[{role}] no predictions in {od}: skipped")
            continue
        t0 = time.time()
        RR[role] = score_role(role, C.load_table(pk), C.load_table(os.path.join(od, f"preds_path_{role}.pkl")),
                              args.boot, args.seed)
        DD[role] = decide(RR[role])
        log(f"[{role}] scored in {time.time() - t0:.0f}s: adopt {DD[role]['adopt']}")
        for name in ("importance", "fit"):
            p = os.path.join(od, f"{name}_{role}.json")
            if os.path.exists(p):
                (IMP if name == "importance" else FIT)[role] = json.load(open(p, encoding="utf-8"))
    adopt = bool(RR) and all(DD[r]["adopt"] for r in RR)
    with open(os.path.join(od, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"basis": args.basis, "split": "time", "boot": args.boot, "seed": args.seed, "adopt": adopt,
                   "decision": DD, "results": RR}, fh, indent=1)
    write_md(args.basis, RR, DD, IMP, FIT, os.path.join(od, "report.md"), args.boot)
    log(f"wrote {os.path.join(od, 'report.md')}: adopt {adopt}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fit")
    p.add_argument("--basis", required=True, choices=list(C.BASES))
    p.add_argument("--role", required=True, choices=list(C.ROLES))
    p.add_argument("--quick", action="store_true")
    p.add_argument("--no-importance", action="store_true")
    p.add_argument("--imp-rows", type=int, default=25000)
    p.add_argument("--imp-repeats", type=int, default=2)
    p = sub.add_parser("report")
    p.add_argument("--basis", required=True, choices=list(C.BASES))
    p.add_argument("--roles", nargs="+", default=list(C.ROLES), choices=list(C.ROLES))
    p.add_argument("--quick", action="store_true")
    p.add_argument("--boot", type=int, default=200)
    p.add_argument("--seed", type=int, default=20260925)
    args = ap.parse_args(argv)
    t0 = time.time()
    {"fit": cmd_fit, "report": cmd_report}[args.cmd](args)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
