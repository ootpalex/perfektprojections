"""
path.py - year-ahead WAA change models for DEV players (the "path" group).

For every DEV player-dump at ages 16-38 whose player is still in the league a
year later, the models predict how much his now_WAA moves over the next 1 to 5
game-years:

  d1 .. d5        one gradient-boosted regressor per horizon k; target
                  d_k = now_WAA at dump_year + k minus now_WAA today, trained
                  on the rows where d_k is known (the player is still in the
                  league and priced k years later)
  d1_mean .. d5_mean
                  squared-loss twins of d1..d5 (fix 5, 2026-09-24): d1..d5
                  are medians (absolute loss); money (FA pricing) needs the
                  EXPECTED change, which is the mean. Same settings as d1_mean.
  d1_q25, d1_q75  quantile regressors for the one-year change (the middle
                  half of outcomes)
  p_present1      a classifier for "still in the league next year", trained on
                  ages 27-38 (veterans), written as an extra column

Every model uses scikit-learn HistGradientBoosting on the features that
schema_<basis>.json marks usable_for_scoring (the same columns exist in the
TGS / BLM scoring rows). Targets and flags are never features. Early stopping
uses a held-back 10 percent of the training PLAYERS (every dump of a player on
one side).

User, 2026-09-24: "is there any way you can make a machine learning model to
help with figuring out this dev stuff". One model set per league (--basis TGS
| BLM, required): rows from dev_<role>_<basis>.pkl, outputs in models/<basis>,
preds/<basis>, report/<basis>. The tuned settings of the first run
(models/path_settings.json) are read as they are; no re-tuning per basis.

Rows (the contract's "path" group): age 16-38 and present_1 == 1.

Commands (run with the Python 3.14 install, PY314; every command takes --basis):
  PY314 path.py tune         light tuning on fold 0's training set (folds 1-4);
                             writes models/path_settings.json
  PY314 path.py fit-oof      5-fold out-of-fold predictions (fit on four folds,
                             predict the fifth); runs tune first when no
                             settings file exists
  PY314 path.py fit-time     fit on time_split 'train', predict 'test'
  PY314 path.py fit-final    fit on all rows; save models/path_<role>_*.pkl
                             and models/path_manifest.json
  PY314 path.py importance   what drives the one-year change, by feature
                             family and top features, for ages 16-26 and
                             28-38, plus veteran tables (ages 30-34)
  PY314 path.py score        apply the final models to the scoring rows of the
                             basis league (preds/<basis>/ml_path_score_<LG>.pkl)
  PY314 path.py all          tune (if needed), fit-oof, fit-time, fit-final,
                             importance, score
  --role H|P|both            which role (default both)

Outputs (.dev_cache/ml/, <B> = the basis):
  preds/<B>/ml_path.pkl      pid, dump_year, role, split ('oof' / 'time'),
                             fold, d1..d5, d1_mean..d5_mean, d1_q25, d1_q75,
                             p_present1
  preds/<B>/ml_present.pkl   the present-next-year classifier on its own rows
                             (ages 27-38 with present_1 known, both outcomes)
  preds/<B>/parts/           one file per role and split; ml_path.pkl is
                             rebuilt from these after every fit
  models/<B>/                fitted models, path_manifest.json (the settings
                             file stays in models/)
  report/<B>/                path_metrics_<split>_<role>.json,
                             path_importance.json
"""
import argparse
import datetime
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import common as C                                         # noqa: E402
import xgb_models as XM  # noqa: E402

import sklearn                                             # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor  # noqa: E402

AGE_LO, AGE_HI = 16, 38            # path rows
PRES_LO = 27                        # present-next-year classifier rows: ages 27-38
KS = (1, 2, 3, 4, 5)
VAL_SHARE = 10                      # 1 in 10 training players held back for early stopping
BANDS = [(16, 18), (19, 22), (23, 26), (27, 30), (31, 34), (35, 38)]
SETTINGS_PATH = os.path.join(C.MODELS_ROOT, "path_settings.json")   # first-run settings, shared
MEAN_TWINS = True                   # fix 5: a squared-loss dk_mean next to every median dk


def parts_dir():
    """preds/<basis>/parts (read at call time: use_basis moves PREDS_DIR)."""
    return os.path.join(C.PREDS_DIR, "parts")


def manifest_path():
    return os.path.join(C.MODELS_DIR, "path_manifest.json")

# fixed settings used when no tuning has run; tune() overwrites the tree shape
DEFAULT_PARAMS = {"learning_rate": 0.1, "max_iter": 2000, "max_leaf_nodes": 63,
                  "min_samples_leaf": 200, "l2_regularization": 1.0, "max_bins": 255,
                  "n_iter_no_change": 30}
DEFAULT_LOSS = {f"d{k}": "squared_error" for k in KS}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- data
def val_flag(pids):
    """1 for the players held back for early stopping (a salted md5, so the
    choice is independent of the fold rule)."""
    u = np.unique(pids)
    held = {p: int(hashlib.md5(f"val:{p}".encode()).hexdigest()[:8], 16) % VAL_SHARE == 0 for p in u}
    return np.fromiter((held[p] for p in pids), dtype=bool, count=len(pids))


def load_role(role):
    """(features, path rows, present rows) for one role.

    path rows    age 16-38 and present_1 == 1 (the contract's path group)
    present rows age 27-38 and present_1 known (0 or 1)"""
    feats = C.usable_features(role)
    keep = (["pid", "dump_year", "fold", "time_split", "present_1"]
            + [f"d_{k}" for k in KS] + feats)
    df = C.load_table(C.dev_table(role))
    df = df[keep]
    age = df["age"]
    path = df[(age >= AGE_LO) & (age <= AGE_HI) & (df["present_1"] == 1)].reset_index(drop=True)
    pres = df[(age >= PRES_LO) & (age <= AGE_HI) & df["present_1"].notna()].reset_index(drop=True)
    del df
    path["val"] = val_flag(path["pid"].to_numpy())
    pres["val"] = val_flag(pres["pid"].to_numpy())
    return feats, path, pres


# ---------------------------------------------------------------- models
def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def role_settings(settings, role):
    if settings and role in settings:
        s = settings[role]
        return dict(DEFAULT_PARAMS, **s["params"]), dict(DEFAULT_LOSS, **s["loss"])
    return dict(DEFAULT_PARAMS), dict(DEFAULT_LOSS)


def make_reg(params, loss, quantile=None, seed=0):
    kw = dict(params)
    return HistGradientBoostingRegressor(loss=loss, quantile=quantile, early_stopping=True,
                                         scoring="loss", random_state=seed, **kw)


def make_cls(params, seed=0):
    return HistGradientBoostingClassifier(early_stopping=True, scoring="loss", random_state=seed, **params)


def fit_es(model, X, y, val):
    """Fit with early stopping on the held-back players (val == True)."""
    tr = ~val
    model.fit(X[tr], y[tr], X_val=X[val], y_val=y[val])
    return model


def model_specs(loss):
    """(name, target column, kind, loss, quantile) for every model of a role."""
    specs = [(f"d{k}", f"d_{k}", "reg", loss[f"d{k}"], None) for k in KS]
    for k in KS:
        if loss[f"d{k}"] != "squared_error" and (k == 1 or MEAN_TWINS):
            # the chosen dk is a median; a squared-loss twin gives the mean
            # change (what an expected-value price needs). Fix 5, 2026-09-24:
            # every horizon, not only d1; same settings as d1_mean.
            specs.append((f"d{k}_mean", f"d_{k}", "reg", "squared_error", None))
    specs += [("d1_q25", "d_1", "reg", "quantile", 0.25), ("d1_q75", "d_1", "reg", "quantile", 0.75),
              ("present1", "present_1", "cls", None, None)]
    return specs


def fit_one(spec, params, feats, path, pres, rows_path, rows_pres):
    """Fit one model on the given training row masks. Returns the model and n rows used.
    XGBoost on the GPU when it is installed (xgb_models.py: the user keeps CPU
    load light), else scikit-learn as before."""
    name, tcol, kind, loss, q = spec
    use_xgb = XM.backend()[0] == "xgboost"
    if kind == "cls":
        d = pres[rows_pres]
        X, y, val = d[feats], d[tcol].to_numpy().astype(int), d["val"].to_numpy().astype(bool)
        if use_xgb:
            m = XM.fit(XM.classifier(params, feats=feats), X[~val], y[~val], X[val], y[val])
        else:
            m = fit_es(make_cls(params), X, y, val)
        return m, len(d)
    d = path[rows_path]
    y = d[tcol].to_numpy(dtype=np.float64)
    ok = ~np.isnan(y)
    d = d[ok]
    if use_xgb:
        val = d["val"].to_numpy().astype(bool)
        X, yy = d[feats], y[ok]
        m = XM.fit(XM.regressor(params, loss, q), X[~val], yy[~val], X[val], yy[val])
    else:
        m = fit_es(make_reg(params, loss, q), d[feats], y[ok], d["val"].to_numpy())
    return m, len(d)


def predict_into(out, name, model, X, kind):
    if kind == "cls":
        out[name] = model.predict_proba(X)[:, 1].astype(np.float32)
    else:
        out[name] = model.predict(X).astype(np.float32)


def run_split(role, feats, path, pres, params, loss, train_path, train_pres, test_path, test_pres,
              keep_models=False, tag=""):
    """Fit every model on the training masks and predict the test masks.

    Returns (pred frame for the path test rows, pred frame for the present
    test rows, {name: model} when keep_models, {name: info})."""
    outp = path.loc[test_path, ["pid", "dump_year"]].copy()
    outq = pres.loc[test_pres, ["pid", "dump_year"]].copy()
    Xp = path.loc[test_path, feats]
    Xq = pres.loc[test_pres, feats]
    models, info = {}, {}
    for spec in model_specs(loss):
        name, _t, kind, lo, _q = spec
        t0 = time.time()
        m, n = fit_one(spec, params, feats, path, pres, train_path, train_pres)
        if kind == "cls":
            predict_into(outq, "p_present1", m, Xq, kind)
            p = np.full(len(outp), np.nan, dtype=np.float32)
            old = (Xp["age"] >= PRES_LO).to_numpy()
            if old.any():
                p[old] = m.predict_proba(Xp[old])[:, 1]
            outp["p_present1"] = p
        else:
            predict_into(outp, name, m, Xp, kind)
        info[name] = {"n_train": int(n), "n_iter": XM.n_iter(m), "loss": lo or "log_loss",
                      "seconds": round(time.time() - t0, 1)}
        log(f"  {role}{tag} {name}: n {n:,} iters {XM.n_iter(m)} {time.time() - t0:.0f}s")
        if keep_models:
            models[name] = m
    lo, hi = np.minimum(outp["d1_q25"], outp["d1_q75"]), np.maximum(outp["d1_q25"], outp["d1_q75"])
    outp["d1_q25"], outp["d1_q75"] = lo, hi
    return outp, outq, models, info


# ---------------------------------------------------------------- tuning
def tune(role, feats, path):
    """Light tuning on fold 0's training set (folds 1-4), scored on its
    held-back players: tree shape on d1 and d3 with squared loss, then the loss
    (squared vs absolute) per horizon by held-out MAE."""
    tr = (path["fold"] != 0).to_numpy()
    d = path[tr]
    val = d["val"].to_numpy()
    grid = [(31, 100), (63, 200), (127, 200), (127, 800), (255, 400)]
    res = []
    for leaves, msl in grid:
        p = dict(DEFAULT_PARAMS, max_leaf_nodes=leaves, min_samples_leaf=msl)
        row = {"max_leaf_nodes": leaves, "min_samples_leaf": msl}
        for k in (1, 3):
            y = d[f"d_{k}"].to_numpy(dtype=np.float64)
            ok = ~np.isnan(y)
            t0 = time.time()
            m = make_reg(p, "squared_error")
            m.fit(d.loc[ok & ~val, feats], y[ok & ~val], X_val=d.loc[ok & val, feats], y_val=y[ok & val])
            pr = m.predict(d.loc[ok & val, feats])
            row[f"d{k}_mae"] = float(np.mean(np.abs(pr - y[ok & val])))
            row[f"d{k}_iters"] = int(m.n_iter_)
            log(f"  tune {role} leaves {leaves} msl {msl} d{k}: MAE {row[f'd{k}_mae']:.4f} "
                f"iters {m.n_iter_} {time.time() - t0:.0f}s")
        res.append(row)
    best = min(res, key=lambda r: r["d1_mae"] + r["d3_mae"])
    params = {"max_leaf_nodes": best["max_leaf_nodes"], "min_samples_leaf": best["min_samples_leaf"]}
    p = dict(DEFAULT_PARAMS, **params)
    loss, loss_res = {}, {}
    for k in KS:
        y = d[f"d_{k}"].to_numpy(dtype=np.float64)
        ok = ~np.isnan(y)
        r = {}
        for lo in ("squared_error", "absolute_error"):
            t0 = time.time()
            m = make_reg(p, lo)
            m.fit(d.loc[ok & ~val, feats], y[ok & ~val], X_val=d.loc[ok & val, feats], y_val=y[ok & val])
            pr = m.predict(d.loc[ok & val, feats])
            err = pr - y[ok & val]
            r[lo] = {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err ** 2))),
                     "mean_bias": float(np.mean(err)), "iters": int(m.n_iter_), "n_val": int((ok & val).sum())}
            log(f"  tune {role} d{k} {lo}: MAE {r[lo]['mae']:.4f} RMSE {r[lo]['rmse']:.4f} "
                f"bias {r[lo]['mean_bias']:+.4f} {time.time() - t0:.0f}s")
        loss[f"d{k}"] = min(r, key=lambda lo: r[lo]["mae"])
        loss_res[f"d{k}"] = r
    return {"params": params, "loss": loss, "grid": res, "loss_check": loss_res,
            "rule": "tree shape by d1 + d3 held-out MAE (squared loss); loss per horizon by held-out MAE",
            "data": "fold 0 training set (folds 1-4), scored on its held-back 10% of players"}


# ---------------------------------------------------------------- metrics
def band_of(age):
    out = np.full(len(age), "", dtype=object)
    for lo, hi in BANDS:
        out[(age >= lo) & (age <= hi)] = f"{lo}-{hi}"
    return out


def age_table(ages, y):
    """Per-age mean and median of y (NaN dropped)."""
    s = pd.DataFrame({"age": ages, "y": y}).dropna()
    g = s.groupby("age")["y"]
    return g.mean(), g.median()


def self_check(path, preds, train_masks, test_masks):
    """MAE of d1 and d3 by age band: the model against the per-age mean and
    per-age median of the training rows (the age-only baseline), plus the
    d1 middle-half coverage. train_masks / test_masks are parallel lists (one
    pair per fold for OOF, one pair for the time split)."""
    rows = []
    base = {}
    for k in (1, 3):
        bm = np.full(len(path), np.nan)
        bd = np.full(len(path), np.nan)
        for trm, tem in zip(train_masks, test_masks):
            mean, med = age_table(path.loc[trm, "age"].to_numpy(), path.loc[trm, f"d_{k}"].to_numpy())
            a = path.loc[tem, "age"]
            bm[tem] = a.map(mean).to_numpy()
            bd[tem] = a.map(med).to_numpy()
        base[k] = (bm, bd)
    test_any = np.zeros(len(path), dtype=bool)
    for tem in test_masks:
        test_any |= tem
    sub = path.loc[test_any, ["pid", "dump_year", "age", "d_1", "d_3"]].copy()
    sub = sub.merge(preds[["pid", "dump_year", "d1", "d3", "d1_q25", "d1_q75"]], on=["pid", "dump_year"], how="left")
    for k in (1, 3):
        sub[f"b{k}_mean"] = base[k][0][test_any]
        sub[f"b{k}_med"] = base[k][1][test_any]
    sub["band"] = band_of(sub["age"].to_numpy())
    for band in [f"{lo}-{hi}" for lo, hi in BANDS] + ["all"]:
        s = sub if band == "all" else sub[sub["band"] == band]
        r = {"band": band}
        for k in (1, 3):
            y = s[f"d_{k}"].to_numpy()
            ok = ~np.isnan(y)
            r[f"n_d{k}"] = int(ok.sum())
            for col, nm in ((f"d{k}", "ml"), (f"b{k}_mean", "age_mean"), (f"b{k}_med", "age_median")):
                r[f"d{k}_mae_{nm}"] = float(np.nanmean(np.abs(s[col].to_numpy()[ok] - y[ok]))) if ok.any() else None
            r[f"d{k}_bias_ml"] = float(np.nanmean(s[f"d{k}"].to_numpy()[ok] - y[ok])) if ok.any() else None
        y = s["d_1"].to_numpy()
        cov = (y >= s["d1_q25"].to_numpy()) & (y <= s["d1_q75"].to_numpy())
        r["d1_mid_half_cover"] = float(cov.mean()) if len(y) else None
        rows.append(r)
    return rows


def present_check(pres, predq):
    s = pres[["pid", "dump_year", "age", "present_1"]].merge(predq, on=["pid", "dump_year"], how="inner")
    y, p = s["present_1"].to_numpy(), s["p_present1"].to_numpy()
    base = s.groupby("age")["present_1"].transform("mean").to_numpy()   # in-sample age-only rate, a loose bar
    out = {"n": int(len(s)), "rate": float(y.mean()),
           "brier_ml": float(np.mean((p - y) ** 2)), "brier_age_rate_insample": float(np.mean((base - y) ** 2))}
    try:
        from sklearn.metrics import roc_auc_score
        out["auc_ml"] = float(roc_auc_score(y, p))
        out["auc_age_only"] = float(roc_auc_score(y, base))
    except ValueError:
        pass
    return out


def print_check(role, split, rows, pc):
    log(f"self-check {role} {split} (MAE; age mean / age median from the training rows; self-reported)")
    print(f"  {'band':6} {'n d1':>8} {'ml':>7} {'mean':>7} {'median':>7} | {'n d3':>8} {'ml':>7} {'mean':>7} {'median':>7} | cover")
    for r in rows:
        print(f"  {r['band']:6} {r['n_d1']:>8,} {r['d1_mae_ml']:>7.4f} {r['d1_mae_age_mean']:>7.4f} {r['d1_mae_age_median']:>7.4f} |"
              f" {r['n_d3']:>8,} {(r['d3_mae_ml'] or float('nan')):>7.4f} {(r['d3_mae_age_mean'] or float('nan')):>7.4f}"
              f" {(r['d3_mae_age_median'] or float('nan')):>7.4f} | {r['d1_mid_half_cover']:.3f}")
    print(f"  present next year (27-38): {json.dumps({k: (round(v, 4) if isinstance(v, float) else v) for k, v in pc.items()})}")


# ---------------------------------------------------------------- writing
def write_part(df, role, split, kind):
    os.makedirs(parts_dir(), exist_ok=True)
    C.save_table(df, os.path.join(parts_dir(), f"ml_{kind}_{split}_{role}.pkl"))


def assemble():
    """Rebuild preds/<basis>/ml_path.pkl and ml_present.pkl from the parts."""
    for kind, cols in (("path", ["d1", "d2", "d3", "d4", "d5", "d1_q25", "d1_q75", "p_present1"]
                        + [f"d{k}_mean" for k in KS]),
                       ("present", ["p_present1"])):
        frames = []
        for split in ("oof", "time"):
            for role in C.ROLES:
                p = os.path.join(parts_dir(), f"ml_{kind}_{split}_{role}.pkl")
                if os.path.exists(p):
                    frames.append(C.load_table(p))
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        cols = [c for c in cols if c in df.columns]
        df["role"] = df["role"].astype("category")
        df["split"] = df["split"].astype("category")
        df = df[["pid", "dump_year", "role", "split", "fold"] + cols]
        C.save_table(df, os.path.join(C.PREDS_DIR, f"ml_{kind}.pkl"))
        log(f"wrote preds/ml_{kind}.pkl: {len(df):,} rows "
            f"{df.groupby(['split', 'role'], observed=True).size().to_dict()}")


def write_report(name, obj):
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    with open(os.path.join(C.REPORT_DIR, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)


def finish_frame(out, role, split, fold):
    out = out.copy()
    out.insert(2, "role", role)
    out.insert(3, "split", split)
    out.insert(4, "fold", fold)
    return out


# ---------------------------------------------------------------- commands
def cmd_tune(roles, force=False):
    settings = load_settings() or {}
    for role in roles:
        if role in settings and not force:
            log(f"tune {role}: settings exist, skipped (use tune to redo)")
            continue
        feats, path, _pres = load_role(role)
        log(f"tune {role}: {len(path):,} path rows, {len(feats)} features")
        settings[role] = tune(role, feats, path)
        settings["_meta"] = {"written": datetime.datetime.now().isoformat(timespec="seconds"),
                             "sklearn": sklearn.__version__, "fixed": DEFAULT_PARAMS}
        os.makedirs(C.MODELS_DIR, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=1)
        log(f"tune {role}: params {settings[role]['params']} loss {settings[role]['loss']}")


def cmd_fit_oof(roles):
    settings = load_settings()
    if not settings or any(r not in settings for r in roles):
        cmd_tune(roles)
        settings = load_settings()
    for role in roles:
        params, loss = role_settings(settings, role)
        feats, path, pres = load_role(role)
        log(f"fit-oof {role}: {len(path):,} path rows, {len(pres):,} present rows")
        fp, fq = path["fold"].to_numpy(), pres["fold"].to_numpy()
        outs_p, outs_q, infos = [], [], {}
        trm, tem = [], []
        for f in range(C.N_FOLDS):
            keep = f == 0
            op, oq, models, info = run_split(role, feats, path, pres, params, loss,
                                             fp != f, fq != f, fp == f, fq == f, keep_models=keep, tag=f" fold{f}")
            outs_p.append(finish_frame(op, role, "oof", f))
            outs_q.append(finish_frame(oq, role, "oof", f))
            infos[f] = info
            trm.append(fp != f)
            tem.append(fp == f)
            if keep:
                os.makedirs(C.MODELS_DIR, exist_ok=True)
                with open(os.path.join(C.MODELS_DIR, f"path_{role}_fold0.pkl"), "wb") as fh:
                    pickle.dump({"models": models, "features": feats, "note": "fit on folds 1-4; for importance"}, fh)
        P = pd.concat(outs_p, ignore_index=True)
        Q = pd.concat(outs_q, ignore_index=True)
        write_part(P, role, "oof", "path")
        write_part(Q, role, "oof", "present")
        rows = self_check(path, P, trm, tem)
        pc = present_check(pres, Q)
        print_check(role, "oof", rows, pc)
        write_report(f"path_metrics_oof_{role}.json", {"role": role, "split": "oof", "bands": rows,
                                                       "present": pc, "fits": infos, "params": params, "loss": loss})
    assemble()


def cmd_fit_time(roles):
    settings = load_settings()
    if not settings or any(r not in settings for r in roles):
        cmd_tune(roles)
        settings = load_settings()
    for role in roles:
        params, loss = role_settings(settings, role)
        feats, path, pres = load_role(role)
        tp = (path["time_split"] == "train").to_numpy()
        tq = (pres["time_split"] == "train").to_numpy()
        log(f"fit-time {role}: train {tp.sum():,} test {(~tp).sum():,} path rows")
        op, oq, _m, info = run_split(role, feats, path, pres, params, loss, tp, tq, ~tp, ~tq, tag=" time")
        P = finish_frame(op, role, "time", -1)
        Q = finish_frame(oq, role, "time", -1)
        P["fold"] = path.loc[~tp, "fold"].to_numpy()
        Q["fold"] = pres.loc[~tq, "fold"].to_numpy()
        write_part(P, role, "time", "path")
        write_part(Q, role, "time", "present")
        rows = self_check(path, P, [tp], [~tp])
        pc = present_check(pres, Q)
        print_check(role, "time", rows, pc)
        write_report(f"path_metrics_time_{role}.json", {"role": role, "split": "time", "bands": rows,
                                                        "present": pc, "fits": info, "params": params, "loss": loss})
    assemble()


def cmd_fit_final(roles):
    settings = load_settings()
    if not settings or any(r not in settings for r in roles):
        cmd_tune(roles)
        settings = load_settings()
    manifest = {}
    if os.path.exists(manifest_path()):
        with open(manifest_path(), encoding="utf-8") as fh:
            manifest = json.load(fh)
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    for role in roles:
        params, loss = role_settings(settings, role)
        t_role = time.time()
        feats, path, pres = load_role(role)
        allp = np.ones(len(path), dtype=bool)
        allq = np.ones(len(pres), dtype=bool)
        entry = {"features": feats, "categorical": {k: v for k, v in C.CATEGORICAL.items() if k in feats},
                 "params": params, "rows": f"path rows age {AGE_LO}-{AGE_HI} with present_1 == 1; "
                 f"present1 rows age {PRES_LO}-{AGE_HI} with present_1 known",
                 "age_range": [AGE_LO, AGE_HI], "present_age_range": [PRES_LO, AGE_HI], "models": {}}
        for spec in model_specs(loss):
            name, tcol, kind, lo, q = spec
            t0 = time.time()
            m, n = fit_one(spec, params, feats, path, pres, allp, allq)
            fn = f"path_{role}_{name}.pkl"
            with open(os.path.join(C.MODELS_DIR, fn), "wb") as fh:
                pickle.dump(m, fh)
            entry["models"][name] = {"file": fn, "target": tcol, "kind": kind, "loss": lo or "log_loss",
                                     "quantile": q, "n_train": int(n), "n_iter": XM.n_iter(m),
                                     "library": "xgboost" if XM.is_xgb(m) else "scikit-learn"}
            log(f"  final {role} {name}: n {n:,} iters {XM.n_iter(m)} {time.time() - t0:.0f}s -> {fn}")
        entry["fit_seconds"] = round(time.time() - t_role, 1)
        manifest[role] = entry
    manifest["_meta"] = {"written": datetime.datetime.now().isoformat(timespec="seconds"),
                         "sklearn": sklearn.__version__, "python": sys.version.split()[0],
                         "basis": C.BASIS,
                         "calib_fingerprint": C.calib_fingerprint(C.BASIS),
                         "basis_rule": "one model set per league: DEV priced with this league's engine calibration "
                                       f"(DEV engine price tag {C.waa_tag(C.BASIS)}); score only this league",
                         "settings_file": os.path.relpath(SETTINGS_PATH, C.ML_ROOT),
                         "d_k_mean": "squared-loss twin of d_k: the expected change (for money); d_k itself is "
                                     "the median when its loss is absolute_error (fix 5)",
                         "load": "pickle.load(open(path, 'rb')); X = rows[features] with the categorical columns "
                                 "as pandas categories using common.CATEGORICAL lists",
                         "d_k": "predicted change in now_WAA over k game-years, for a player still in the league",
                         "present1": "chance he is still in the league next year (trained on ages 27-38)"}
    with open(manifest_path(), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    log(f"wrote {manifest_path()}")


def cmd_score(roles):
    """Apply the final models to the scoring rows of the basis league (ages
    16-38). Leagues are separate: a basis scores only its own league."""
    with open(manifest_path(), encoding="utf-8") as fh:
        manifest = json.load(fh)
    for lg in (C.BASIS,):
        frames = []
        for role in roles:
            p = C.table_path(f"score_{lg}_{role}")
            if not os.path.exists(p) or role not in manifest:
                continue
            df = C.load_table(p)
            df = df[(df["age"] >= AGE_LO) & (df["age"] <= AGE_HI)].reset_index(drop=True)
            ent = manifest[role]
            X = df[ent["features"]]
            out = df[["pid", "name", "age", "pos", "now_waa"]].copy()
            out["role"] = role
            for name, m in ent["models"].items():
                with open(os.path.join(C.MODELS_DIR, m["file"]), "rb") as fh:
                    model = pickle.load(fh)
                if m["kind"] == "cls":
                    out["p_present1"] = model.predict_proba(X)[:, 1].astype(np.float32)
                else:
                    out[name] = model.predict(X).astype(np.float32)
            frames.append(out)
        if frames:
            df = pd.concat(frames, ignore_index=True)
            C.save_table(df, os.path.join(C.PREDS_DIR, f"ml_path_score_{lg}.pkl"))
            log(f"wrote preds/ml_path_score_{lg}.pkl: {len(df):,} rows")


# ---------------------------------------------------------------- importance
def perm_mae(model, X, y, cols, rng, repeats=3):
    """Mean rise in MAE when the columns are shuffled together (one row
    order for the whole group, so a family moves as one block)."""
    base = np.mean(np.abs(model.predict(X) - y))
    rises = []
    for _ in range(repeats):
        Xp = X.copy()
        idx = rng.permutation(len(X))
        for c in cols:
            Xp[c] = X[c].to_numpy()[idx] if not isinstance(X[c].dtype, pd.CategoricalDtype) else \
                pd.Categorical(X[c].to_numpy()[idx], categories=X[c].cat.categories)
        rises.append(np.mean(np.abs(model.predict(Xp) - y)) - base)
    return float(np.mean(rises)), float(base)


def pos_group(pos):
    m = {"C": "C", "1B": "1B/DH", "DH": "1B/DH", "2B": "2B/SS", "SS": "2B/SS", "3B": "3B",
         "LF": "LF/RF", "RF": "LF/RF", "CF": "CF", "SP": "SP", "RP": "RP/CL", "CL": "RP/CL"}
    return pd.Series(pos).astype(object).map(m).fillna("other").to_numpy()


def cmd_importance(roles, n_sample=40000, seed=7):
    schema = C.load_schema()
    rep = {"what": "permutation importance of the fold-0 d1 model (fit on folds 1-4) on fold-0 path rows; "
                   "MAE rise in WAA when a feature (or a whole family) is shuffled", "roles": {}}
    oof = C.load_table(os.path.join(C.PREDS_DIR, "ml_path.pkl"))
    oof = oof[oof["split"] == "oof"]
    rng = np.random.default_rng(seed)
    for role in roles:
        fam = {c["name"]: c["family"] for c in schema["roles"][role]["columns"] if c.get("kind") == "feature"}
        feats, path, _pres = load_role(role)
        with open(os.path.join(C.MODELS_DIR, f"path_{role}_fold0.pkl"), "rb") as fh:
            fm = pickle.load(fh)["models"]
        m = fm["d1"]
        m_mean = fm.get("d1_mean", m)      # partial dependence on the mean-change model when there is one
        f0 = path[path["fold"] == 0]
        R = {"bands": {}}
        for lo, hi, label in ((16, 26, "16-26 growth"), (28, 38, "28-38 decline")):
            s = f0[(f0["age"] >= lo) & (f0["age"] <= hi)]
            if len(s) > n_sample:
                s = s.sample(n_sample, random_state=seed)
            X, y = s[feats], s["d_1"].to_numpy(dtype=np.float64)
            fams = {}
            for fname in sorted(set(fam[c] for c in feats)):
                cols = [c for c in feats if fam[c] == fname]
                rise, base = perm_mae(m, X, y, cols, rng)
                fams[fname] = {"mae_rise": round(rise, 5), "n_features": len(cols)}
            single = {}
            for c in feats:
                rise, base = perm_mae(m, X, y, [c], rng, repeats=2)
                single[c] = round(rise, 5)
            top = sorted(single.items(), key=lambda kv: -kv[1])[:15]
            R["bands"][label] = {"n": int(len(s)), "base_mae": round(base, 4),
                                 "families": dict(sorted(fams.items(), key=lambda kv: -kv[1]["mae_rise"])),
                                 "top_features": [{"feature": k, "family": fam[k], "mae_rise": v} for k, v in top]}
            log(f"importance {role} {label}: n {len(s):,} base MAE {base:.4f}")
            for k, v in R["bands"][label]["families"].items():
                print(f"    family {k:10} {v['mae_rise']:+.4f} ({v['n_features']} features)")
            for t in R["bands"][label]["top_features"]:
                print(f"    {t['feature']:16} {t['family']:10} {t['mae_rise']:+.4f}")
        # veteran tables, ages 30-34, OOF predictions against the age-only mean
        v = path[(path["age"] >= 30) & (path["age"] <= 34)][["pid", "dump_year", "age", "pos", "d_1", "now_waa"]
                                                              + (["speed"] if role == "H" else ["vel", "stm"])]
        mcol = "d1_mean" if "d1_mean" in oof.columns and oof.loc[oof["role"] == role, "d1_mean"].notna().any() else "d1"
        v = v.merge(oof[oof["role"] == role][["pid", "dump_year", "d1", mcol]].rename(columns={mcol: "d1_m"})
                    if mcol != "d1" else oof[oof["role"] == role][["pid", "dump_year", "d1"]].assign(d1_m=lambda x: x["d1"]),
                    on=["pid", "dump_year"], how="inner")
        agemean = path.groupby("age")["d_1"].mean()
        agemed = path.groupby("age")["d_1"].median()
        v["age_mean"] = v["age"].map(agemean)
        v["age_median"] = v["age"].map(agemed)
        v["pos_group"] = pos_group(v["pos"])
        key = "speed" if role == "H" else "vel"
        v[f"{key}_tercile"] = pd.qcut(v[key].rank(method="first"), 3, labels=["low", "mid", "high"])
        v["now_tercile"] = pd.qcut(v["now_waa"].rank(method="first"), 3, labels=["low", "mid", "high"])

        def table(col):
            g = v.groupby(col, observed=True)
            t = pd.DataFrame({"n": g.size(), "actual_mean": g["d_1"].mean(), "actual_median": g["d_1"].median(),
                              "model_mean": g["d1_m"].mean(), "model_d1": g["d1"].mean(), "age_only_mean": g["age_mean"].mean(),
                              "age_only_median": g["age_median"].mean()})
            if col == f"{key}_tercile":
                t.insert(1, f"{key}_range", g[key].agg(lambda s: f"{s.min():.0f}-{s.max():.0f}"))
            if col == "now_tercile":
                t.insert(1, "now_range", g["now_waa"].agg(lambda s: f"{s.min():+.1f} to {s.max():+.1f}"))
            return t.round(3)
        tabs = {}
        for col in (f"{key}_tercile", "pos_group", "now_tercile"):
            t = table(col)
            tabs[col] = t.reset_index().to_dict(orient="records")
            print(f"  {role} ages 30-34 by {col} (one-year now_WAA change; model = OOF)")
            print(t.to_string())
        # partial dependence: same rows, only the one feature moved
        f0v = f0[(f0["age"] >= 30) & (f0["age"] <= 34)]
        pdp = {}
        Xv = f0v[feats]
        basep = float(np.mean(m_mean.predict(Xv)))
        for q in (0.17, 0.5, 0.83):
            Xq = Xv.copy()
            Xq[key] = np.float32(np.nanquantile(Xv[key], q))
            pdp[f"{key}_at_q{int(q * 100)}"] = {"value": float(Xq[key].iloc[0]),
                                                "mean_pred": round(float(np.mean(m_mean.predict(Xq))), 4)}
        pdp["base_mean_pred"] = round(basep, 4)
        pdp["n"] = int(len(Xv))
        print(f"  {role} partial dependence on {key} (fold-0 rows 30-34, everything else as is): {pdp}")
        R["veterans_30_34"] = {"tables": tabs, "partial_dependence": pdp, "n": int(len(v))}
        rep["roles"][role] = R
    write_report("path_importance.json", rep)
    log("wrote report/path_importance.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Year-ahead WAA change models (d1..d5, d1 quartiles, present next year) "
                                             "for DEV players 16-38; HistGradientBoosting per role.")
    ap.add_argument("command", choices=["tune", "fit-oof", "fit-time", "fit-final", "importance", "score", "all"])
    ap.add_argument("--role", default="both", choices=["H", "P", "both"], help="role to run (default both)")
    ap.add_argument("--basis", required=True, choices=list(C.BASES),
                    help="engine calibration of the DEV rows = the league the models serve")
    a = ap.parse_args(argv)
    C.use_basis(a.basis)
    log(f"basis {a.basis}: tables {os.path.basename(C.dev_table('H'))} / {os.path.basename(C.dev_table('P'))}, "
        f"models {C.MODELS_DIR}")
    roles = list(C.ROLES) if a.role == "both" else [a.role]
    for d in (C.PREDS_DIR, C.MODELS_DIR, C.REPORT_DIR):
        os.makedirs(d, exist_ok=True)
    t0 = time.time()
    if a.command == "tune":
        cmd_tune(roles, force=True)
    elif a.command == "fit-oof":
        cmd_fit_oof(roles)
    elif a.command == "fit-time":
        cmd_fit_time(roles)
    elif a.command == "fit-final":
        cmd_fit_final(roles)
    elif a.command == "importance":
        cmd_importance(roles)
    elif a.command == "score":
        cmd_score(roles)
    else:
        cmd_tune(roles)
        cmd_fit_oof(roles)
        cmd_fit_time(roles)
        cmd_fit_final(roles)
        cmd_importance(roles)
        cmd_score(roles)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
