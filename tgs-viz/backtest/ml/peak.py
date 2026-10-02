"""
peak.py - machine-learning model of a young DEV player's eventual peak.

For each role (H hitters, P pitchers) this script fits gradient-boosted tree
models on DEV player-dumps at ages 16-26 with a known outcome (peak_known:
seen at 27+ or retired). Washouts stay in. The five gain quantiles use XGBoost
(on the GPU when CUDA works, else the CPU; scikit-learn HistGradientBoosting
only when xgboost is not installed). The classifiers stay scikit-learn
HistGradientBoosting.

User, 2026-09-24: "is there any way you can make a machine learning model to
help with figuring out this dev stuff".

One model set per league (--basis TGS | BLM, required): the rows come from
dev_<role>_<basis>.pkl (DEV priced with that league's engine calibration) and
every model, prediction and report goes to models/<basis>, preds/<basis>,
report/<basis>. The tuned settings of the first run (models/peak_settings.json)
are read as they are; no re-tuning per basis.

Rows (--rows, default all): 'all' = in an org AND outside an org (amateurs and
free agents, level 'none'); 'org' = in an org only (the first run). Fix 6,
2026-09-24: the app also shows amateurs (draft boards) and free agents 16-26,
and DEV has plenty of such rows (H 291,430, P 281,619), so they join the
training. Held-out predictions keep the in-org rows in the main parts (the
rows the cell method is compared on) and the out-of-org rows in *_outside
parts. The extra feature 'amateur' (common.amateur_flag) tells an amateur from
a free agent; both read level 'none'.

Models per role:
  gain_q10 .. gain_q90   quantile regressors of gain = eventual peak WAA minus
                         now WAA (quantile loss at 0.10 0.25 0.50 0.75 0.90);
                         the five are sorted per row so they never cross, and
                         clipped at 0 (gain is never below 0)
  reach_mlb / reach_useful / reach_good
                         classifiers of "peak reaches -1.0 / 0.0 / +1.5 WAA";
                         trained only on rows with now < bar - 0.05; a row at or
                         above bar - 0.05 reads 1.0 (the app rule)
  regular_future         classifier of "some later MLB season with >= 300 PA or
                         >= 150 BF" (rows where it is known)

Features: every schema_<basis>.json feature with usable_for_scoring true (the
same columns exist in the TGS / BLM scoring rows), plus 'amateur'. level, pos,
bats and throws are categorical. No target or flag is a feature.

Chances: p_useful and p_good are capped by the chance of the lower bar
(common.chance_order, fix 2), the same rule predict.py applies when scoring.

Early stopping uses a grouped validation set: about 10% of the training
PLAYERS (every dump of a player on the same side). Settings come from `tune`
(first OOF training set only) and stay fixed for every later fit.

Commands (run with Python 3.14; every command takes --basis TGS | BLM):
  tune        pick settings on the fold-0 training set (folds 1-4), test the
              now_WAA monotonic constraint and the isotonic calibration step on
              an inner check set of players; writes models/peak_settings.json
  fit-oof     5-fold grouped out-of-fold predictions -> preds (split 'oof')
  fit-time    fit on time_split 'train', predict time_split 'test' -> preds
              (split 'time')
  fit-final   fit on every training row, save models/peak_<role>_<target>.pkl
              and models/peak_manifest.json
  importance  permutation importance (feature family and top 15 features) of
              the gain median and reach_useful models on held-out fold-0 rows
Outputs (<B> = the basis):
  .dev_cache/ml/preds/<B>/ml_peak.pkl          in-org rows, both roles, both splits
  .dev_cache/ml/preds/<B>/ml_peak_outside.pkl  out-of-org rows, the same
  .dev_cache/ml/preds/<B>/parts/ml_peak_<role>_<split>[_outside].pkl
  .dev_cache/ml/models/<B>/peak_<role>_<target>.pkl, peak_manifest.json
  .dev_cache/ml/report/<B>/peak_<role>_<split>[_outside].json   self-check metrics
  .dev_cache/ml/report/<B>/peak_importance_<role>.json
"""
import argparse
import datetime as _dt
import hashlib
import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

import sklearn  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import log_loss, roc_auc_score  # noqa: E402

METHOD = "ml"
GROUP = "peak"
QUANTS = (0.10, 0.25, 0.50, 0.75, 0.90)
QCOLS = ["gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90"]
REACH = {"reach_mlb": ("p_mlb", C.PEAK_BARS["mlb"]),
         "reach_useful": ("p_useful", C.PEAK_BARS["useful"]),
         "reach_good": ("p_good", C.PEAK_BARS["good"])}
BAR_TOL = 0.05                       # dev_signals.BAR_TOLERANCE
TARGETS = QCOLS + list(REACH) + ["regular_future"]
SETTINGS_PATH = os.path.join(C.MODELS_ROOT, "peak_settings.json")   # first-run settings, shared
ROW_RULES = {
    "all": "DEV player-dumps at ages 16-26, peak_known 1 (washouts kept), in an org or not (amateurs and "
           "free agents read level 'none'; the 'amateur' feature tells them apart)",
    "org": "DEV player-dumps at ages 16-26, in_org 1, peak_known 1 (washouts kept)",
}


def part_dir():
    """preds/<basis>/parts (read at call time: use_basis moves PREDS_DIR)."""
    return os.path.join(C.PREDS_DIR, "parts")
VAL_SALT = "peakval:"
CHECK_SALT = "peakcheck:"

DEFAULT_SETTINGS = {
    "quantile": {"learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 200,
                 "l2_regularization": 0.5},
    "classifier": {"learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 200,
                   "l2_regularization": 0.5},
    "max_iter": 2000,
    "n_iter_no_change": 30,
    "max_bins": 255,
    "val_share": 0.10,
    "monotonic_now": True,
    "calibrate": {"reach_mlb": False, "reach_useful": False, "reach_good": False,
                  "regular_future": False},
    "source": "defaults (tune not run)",
}

TUNE_GRID = [
    {"learning_rate": 0.10, "max_leaf_nodes": 31, "min_samples_leaf": 200, "l2_regularization": 0.0},
    {"learning_rate": 0.05, "max_leaf_nodes": 31, "min_samples_leaf": 200, "l2_regularization": 0.5},
    {"learning_rate": 0.05, "max_leaf_nodes": 63, "min_samples_leaf": 100, "l2_regularization": 1.0},
    {"learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 400, "l2_regularization": 0.0},
    {"learning_rate": 0.10, "max_leaf_nodes": 63, "min_samples_leaf": 400, "l2_regularization": 1.0},
    {"learning_rate": 0.03, "max_leaf_nodes": 63, "min_samples_leaf": 200, "l2_regularization": 0.5},
]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- rows
def hash_bucket(pids, salt, mod):
    """Stable bucket 0..mod-1 per player id, independent of the fold hash."""
    out = np.empty(len(pids), dtype=np.int64)
    cache = {}
    for i, p in enumerate(pids):
        v = cache.get(p)
        if v is None:
            v = int(hashlib.md5((salt + str(p)).encode("utf-8")).hexdigest()[:8], 16) % mod
            cache[p] = v
        out[i] = v
    return out


def load_group(role, rows="all"):
    """Peak-group rows of one role: age 16-26, peak_known; in an org only when
    rows == 'org'. Adds the model-only 'amateur' column."""
    df = C.load_table(C.dev_table(role))
    m = (df["age"] >= 16) & (df["age"] <= 26) & (df["peak_known"] == 1)
    if rows == "org":
        m &= df["in_org"] == 1
    g = df.loc[m].reset_index(drop=True)
    del df
    C.add_model_extras(g, C.MODEL_EXTRA_FEATURES)
    return g


def features_of(role):
    schema = C.load_schema()
    feats = C.usable_features(role, schema) + list(C.MODEL_EXTRA_FEATURES)
    fam = {c["name"]: c.get("family") for c in schema["roles"][role]["columns"] if c.get("kind") == "feature"}
    fam.update({f: "context" for f in C.MODEL_EXTRA_FEATURES})
    cats = [f for f in feats if f in C.CATEGORICAL]
    return feats, cats, fam


def in_org_mask(df):
    return (df["in_org"] == 1).to_numpy()


def val_mask(pids, share):
    """True for about `share` of the players (grouped), used for early stopping
    and for the calibration step."""
    k = int(round(1.0 / share))
    return hash_bucket(pids, VAL_SALT, k) == 0


# ---------------------------------------------------------------- models
# The gain quantiles run on XGBoost (the GPU when CUDA works). Head to head on
# held-out TGS players (gpu_compare.py, 2026-09-27): scikit-learn's quantile
# models for the low marks never left their start value, because ~28% of
# pitcher gains are exactly 0 (P q10 / q25 and H q10 were a constant 0 for
# every player); XGBoost learned them (P q25 pinball 0.131 -> 0.095), was ~3%
# better on the medians and tied on q75 / q90. The reach classifiers stay on
# scikit-learn (they tied, scikit-learn a hair better). The user's go: 2026-10-02.
_XGB = {}


def quantile_backend():
    """('xgboost', device) when xgboost imports, device 'cuda' when a tiny GPU
    fit works, else 'cpu'; ('sklearn', None) without xgboost."""
    if "backend" not in _XGB:
        try:
            import xgboost as xgb
            dev = "cpu"
            try:
                xgb.XGBRegressor(n_estimators=2, device="cuda", tree_method="hist").fit(
                    np.zeros((8, 2)), np.arange(8.0))
                dev = "cuda"
            except Exception:
                pass
            _XGB["backend"] = ("xgboost", dev)
            _XGB["version"] = xgb.__version__
        except ImportError:
            _XGB["backend"] = ("sklearn", None)
    return _XGB["backend"]


def _xgb_quantile(hp, st, quantile):
    """XGBoost quantile regressor with the settings tested in gpu_compare.py
    (the scikit-learn settings mapped across)."""
    import xgboost as xgb
    _lib, dev = quantile_backend()
    return xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=quantile, tree_method="hist",
                            device=dev, learning_rate=hp["learning_rate"], max_leaves=hp["max_leaf_nodes"],
                            grow_policy="lossguide", max_depth=0, reg_lambda=hp["l2_regularization"],
                            min_child_weight=float(hp["min_samples_leaf"]), max_bin=st["max_bins"],
                            n_estimators=st["max_iter"], early_stopping_rounds=st["n_iter_no_change"],
                            enable_categorical=True, max_cat_to_onehot=1, random_state=0,
                            n_jobs=1)   # one CPU thread for the data prep: the user keeps CPU load light


def n_iter(m):
    """Boosting rounds kept (scikit-learn n_iter_, XGBoost best round + 1)."""
    if hasattr(m, "n_iter_"):
        return int(m.n_iter_)
    best = getattr(m, "best_iteration", None)
    return int(best) + 1 if best is not None else int(m.get_params().get("n_estimators") or 0)


def make_model(kind, hp, st, feats, quantile=None, monotonic=False, sklearn_only=False):
    """sklearn_only: the scikit-learn model even for a quantile (gpu_compare.py
    compares the two libraries)."""
    if kind == "quantile" and not sklearn_only and quantile_backend()[0] == "xgboost":
        return _xgb_quantile(hp, st, quantile)
    common = dict(learning_rate=hp["learning_rate"], max_leaf_nodes=hp["max_leaf_nodes"],
                  min_samples_leaf=hp["min_samples_leaf"], l2_regularization=hp["l2_regularization"],
                  max_iter=st["max_iter"], max_bins=st["max_bins"], early_stopping=True,
                  n_iter_no_change=st["n_iter_no_change"], scoring="loss",
                  categorical_features="from_dtype", random_state=0)
    if kind == "quantile":
        return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **common)
    mono = {"now_waa": 1} if monotonic and "now_waa" in feats else None
    return HistGradientBoostingClassifier(loss="log_loss", monotonic_cst=mono, **common)


def target_rows(df, target):
    """Boolean mask of the rows a target's model trains on."""
    if target in QCOLS:
        return df["gain"].notna().to_numpy()
    if target in REACH:
        bar = REACH[target][1]
        return (df[target].notna() & (df["now_waa"] < bar - BAR_TOL)).to_numpy()
    return df[target].notna().to_numpy()


def fit_one(target, df, feats, st, val, log_prefix=""):
    """Fit one target's model on df rows (val = grouped early-stopping rows).
    Returns a dict {model, iso, n_train, n_val, n_iter, val_loss}."""
    rows = target_rows(df, target)
    tr, va = rows & ~val, rows & val
    X, Xv = df.loc[tr, feats], df.loc[va, feats]
    t0 = time.time()
    if target in QCOLS:
        q = QUANTS[QCOLS.index(target)]
        m = make_model("quantile", st["quantile"], st, feats, quantile=q)
        y, yv = df.loc[tr, "gain"].to_numpy(), df.loc[va, "gain"].to_numpy()
        if hasattr(m, "n_iter_no_change"):
            m.fit(X, y, X_val=Xv, y_val=yv)
        else:
            m.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
        pv = m.predict(Xv)
        if not hasattr(m, "n_iter_no_change"):
            # saved models score on the CPU anywhere, one thread (the user's PC
            # keeps CPU load light; scoring is ~100k rows)
            m.set_params(device="cpu", n_jobs=1)
        r = yv - pv
        vloss = float(np.mean(np.maximum(q * r, (q - 1) * r)))
        iso = None
    else:
        mono = st.get("monotonic_now", False) and target in REACH
        m = make_model("classifier", st["classifier"], st, feats, monotonic=mono)
        y, yv = df.loc[tr, target].to_numpy().astype(int), df.loc[va, target].to_numpy().astype(int)
        m.fit(X, y, X_val=Xv, y_val=yv)
        pv = m.predict_proba(Xv)[:, 1]
        vloss = float(log_loss(yv, np.clip(pv, 1e-7, 1 - 1e-7), labels=[0, 1]))
        iso = None
        if st.get("calibrate", {}).get(target):
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pv, yv)
    log(f"{log_prefix}{target}: train {int(tr.sum()):,} val {int(va.sum()):,} iters {n_iter(m)} "
        f"val loss {vloss:.5f} ({time.time() - t0:.0f}s)")
    return {"model": m, "iso": iso, "n_train": int(tr.sum()), "n_val": int(va.sum()),
            "n_iter": n_iter(m), "val_loss": vloss}


def fit_set(df, feats, st, targets=TARGETS, log_prefix=""):
    val = val_mask(df["pid"].to_numpy(), st["val_share"])
    return {t: fit_one(t, df, feats, st, val, log_prefix) for t in targets}


def prob(fit, X):
    p = fit["model"].predict_proba(X)[:, 1]
    if fit.get("iso") is not None:
        p = fit["iso"].predict(p)
    return np.clip(p, 0.0, 1.0)


def predict_set(models, df, feats):
    """Prediction columns for df rows (every row gets an answer; NaN features
    are handled by the boosted trees)."""
    X = df[feats]
    out = {}
    q = np.column_stack([models[c]["model"].predict(X) for c in QCOLS])
    q = np.sort(np.maximum(q, 0.0), axis=1)          # never cross, never below 0
    for j, c in enumerate(QCOLS):
        out[c] = q[:, j].astype(np.float32)
    now = df["now_waa"].to_numpy()
    for t, (col, bar) in REACH.items():
        p = prob(models[t], X)
        p = np.where(now >= bar - BAR_TOL, 1.0, p)   # app rule
        out[col] = p.astype(np.float32)
    # fix 2: nested bars, nested chances (the rule predict.py applies too)
    out["p_mlb"], out["p_useful"], out["p_good"] = C.chance_order(out["p_mlb"], out["p_useful"], out["p_good"])
    pr = prob(models["regular_future"], X)
    out["p_regular"] = np.where(df["regular_future"].notna().to_numpy(), pr, np.nan).astype(np.float32)
    return pd.DataFrame(out, index=df.index)


def pred_frame(df, pred, role, split, fold):
    base = pd.DataFrame({"pid": df["pid"].to_numpy(), "dump_year": df["dump_year"].to_numpy(),
                         "role": role, "split": split,
                         "fold": np.asarray(fold, dtype=np.int8)}, index=df.index)
    return pd.concat([base, pred], axis=1).reset_index(drop=True)


# ---------------------------------------------------------------- settings
def load_settings():
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    log("no peak_settings.json: using the defaults (run `tune` first)")
    return {"H": DEFAULT_SETTINGS, "P": DEFAULT_SETTINGS}


# ---------------------------------------------------------------- metrics
def pinball(y, p, q):
    r = y - p
    return float(np.mean(np.maximum(q * r, (q - 1) * r)))


def calib_table(y, p, nbins=10):
    """Reliability by predicted-probability bins (quantile bins of p)."""
    if len(y) == 0:
        return []
    edges = np.unique(np.quantile(p, np.linspace(0, 1, nbins + 1)))
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2) if len(edges) > 1 else np.zeros(len(p), int)
    rows = []
    for b in range(max(len(edges) - 1, 1)):
        s = idx == b
        if s.sum() == 0:
            continue
        rows.append({"n": int(s.sum()), "mean_pred": round(float(p[s].mean()), 5),
                     "observed": round(float(y[s].mean()), 5)})
    return rows


def ece(tab):
    n = sum(r["n"] for r in tab)
    return float(sum(r["n"] * abs(r["mean_pred"] - r["observed"]) for r in tab) / max(n, 1))


def self_check(df, pred):
    """Held-out metrics of one split (df = truth rows, pred = prediction rows)."""
    rep = {"rows": int(len(df))}
    y = df["gain"].to_numpy()
    rep["gain"] = {c: {"pinball": round(pinball(y, pred[c].to_numpy(), q), 5)}
                   for c, q in zip(QCOLS, QUANTS)}
    rep["gain"]["q50_mae"] = round(float(np.mean(np.abs(y - pred["gain_q50"].to_numpy()))), 5)
    rep["gain"]["cover_q25_q75"] = round(float(np.mean((y >= pred["gain_q25"]) & (y <= pred["gain_q75"]))), 4)
    rep["gain"]["cover_q10_q90"] = round(float(np.mean((y >= pred["gain_q10"]) & (y <= pred["gain_q90"]))), 4)
    peak = df["peak"].to_numpy()
    now = df["now_waa"].to_numpy()
    rep["peak_mae_from_q50"] = round(float(np.mean(np.abs(peak - (now + pred["gain_q50"].to_numpy())))), 5)
    for t, (col, bar) in REACH.items():
        yt = df[t].to_numpy().astype(int)
        p = pred[col].to_numpy().astype(float)
        below = now < bar - BAR_TOL
        r = {"n_all": int(len(yt)), "n_below_bar": int(below.sum()), "pos_below_bar": int(yt[below].sum())}
        pc = np.clip(p, 1e-6, 1 - 1e-6)
        r["logloss_all"] = round(float(log_loss(yt, pc, labels=[0, 1])), 5)
        if below.sum() and 0 < yt[below].sum() < below.sum():
            r["logloss_below"] = round(float(log_loss(yt[below], pc[below], labels=[0, 1])), 5)
            r["auc_below"] = round(float(roc_auc_score(yt[below], p[below])), 5)
            r["brier_below"] = round(float(np.mean((p[below] - yt[below]) ** 2)), 6)
            tab = calib_table(yt[below], p[below])
            r["calibration_below"] = tab
            r["ece_below"] = round(ece(tab), 5)
        if 0 < yt.sum() < len(yt):
            r["auc_all"] = round(float(roc_auc_score(yt, p)), 5)
        rep[t] = r
    k = df["regular_future"].notna().to_numpy()
    yt = df.loc[k, "regular_future"].to_numpy().astype(int)
    p = pred.loc[k, "p_regular"].to_numpy().astype(float)
    r = {"n": int(k.sum()), "pos": int(yt.sum())}
    if 0 < yt.sum() < len(yt):
        r["logloss"] = round(float(log_loss(yt, np.clip(p, 1e-6, 1 - 1e-6), labels=[0, 1])), 5)
        r["auc"] = round(float(roc_auc_score(yt, p)), 5)
        tab = calib_table(yt, p)
        r["calibration"] = tab
        r["ece"] = round(ece(tab), 5)
    rep["regular_future"] = r
    # by age band, the two headline numbers
    bands = {}
    for lo, hi in ((16, 18), (19, 22), (23, 26)):
        s = ((df["age"] >= lo) & (df["age"] <= hi)).to_numpy()
        below = s & (now < C.PEAK_BARS["useful"] - BAR_TOL)
        yt = df["reach_useful"].to_numpy().astype(int)
        d = {"n": int(s.sum()),
             "gain_q50_mae": round(float(np.mean(np.abs(y[s] - pred["gain_q50"].to_numpy()[s]))), 5)}
        if below.sum() and 0 < yt[below].sum() < below.sum():
            pu = np.clip(pred["p_useful"].to_numpy()[below], 1e-6, 1 - 1e-6)
            d["useful_n_below"] = int(below.sum())
            d["useful_logloss_below"] = round(float(log_loss(yt[below], pu, labels=[0, 1])), 5)
            d["useful_auc_below"] = round(float(roc_auc_score(yt[below], pu)), 5)
        bands[f"{lo}-{hi}"] = d
    rep["by_age"] = bands
    return rep


def headline(role, split, rep):
    u = rep["reach_useful"]
    log(f"[{role} {split}] rows {rep['rows']:,}: gain_q50 MAE {rep['gain']['q50_mae']:.4f}, "
        f"cover 25-75 {rep['gain']['cover_q25_q75']:.3f}, 10-90 {rep['gain']['cover_q10_q90']:.3f}; "
        f"useful logloss below bar {u.get('logloss_below')} AUC {u.get('auc_below')} "
        f"(n {u['n_below_bar']:,}, pos {u['pos_below_bar']:,}) ECE {u.get('ece_below')}")


def write_report(name, obj):
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    path = os.path.join(C.REPORT_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1)
    log("wrote", path)


def assemble_preds():
    """Glue the per-role / per-split parts into preds/<basis>/ml_peak.pkl
    (in-org rows) and ml_peak_outside.pkl (out-of-org rows)."""
    for suffix in ("", "_outside"):
        parts = []
        for role in C.ROLES:
            for split in ("oof", "time"):
                p = os.path.join(part_dir(), f"{METHOD}_{GROUP}_{role}_{split}{suffix}.pkl")
                if os.path.exists(p):
                    parts.append(pd.read_pickle(p))
        if not parts:
            continue
        allp = pd.concat(parts, ignore_index=True)
        for c in ("role", "split"):
            allp[c] = allp[c].astype("category")
        out = os.path.join(C.PREDS_DIR, f"{METHOD}_{GROUP}{suffix}.pkl")
        C.save_table(allp, out)
        log(f"wrote {out}: {len(allp):,} rows",
            allp.groupby(["role", "split"], observed=True).size().to_dict())


def write_held_out(te, pr, role, split, fold_of_rows, folds_note=None):
    """Save one split's held-out predictions: in-org rows to the main part,
    out-of-org rows to the _outside part, with a self-check report each."""
    org = in_org_mask(te)
    os.makedirs(part_dir(), exist_ok=True)
    for suffix, m in (("", org), ("_outside", ~org)):
        if not m.any():
            continue
        t = te[m].reset_index(drop=True)
        P = pred_frame(t, pr[m].reset_index(drop=True), role, split, np.asarray(fold_of_rows)[m])
        C.save_table(P, os.path.join(part_dir(), f"{METHOD}_{GROUP}_{role}_{split}{suffix}.pkl"))
        rep = self_check(t, P)
        rep["basis"] = C.BASIS
        if folds_note is not None:
            rep["folds"] = folds_note
        if suffix:
            rep["by_kind"] = {}
            ama = t["amateur"].to_numpy() == 1
            for kind, km in (("amateur", ama), ("free_agent", ~ama)):
                if km.sum():
                    rep["by_kind"][kind] = self_check(t[km].reset_index(drop=True), P[km].reset_index(drop=True))
        headline(role, split + suffix, rep)
        write_report(f"peak_{role}_{split}{suffix}.json", rep)


# ---------------------------------------------------------------- commands
def cmd_tune(args):
    """Settings search on the fold-0 training set (folds 1-4) only. Inside it:
    10% of players for early stopping (val), another 10% to score configs and
    to test the monotonic constraint and the isotonic step (check)."""
    out = {"source": f"tune on the fold-0 training set (folds 1-4), run {args.date}",
           "sklearn": sklearn.__version__}
    report = {}
    for role in args.roles:
        g = load_group(role)
        feats, _cats, _fam = features_of(role)
        tr = g[g["fold"] != 0].reset_index(drop=True)
        del g
        if args.sample < 1.0:
            keep = hash_bucket(tr["pid"].to_numpy(), "peaksample:", 1000) < int(args.sample * 1000)
            tr = tr[keep].reset_index(drop=True)
        b = hash_bucket(tr["pid"].to_numpy(), CHECK_SALT, 10)
        check = b == 0
        fitdf = tr[~check].reset_index(drop=True)
        chk = tr[check].reset_index(drop=True)
        log(f"[{role}] tune rows: fit {len(fitdf):,} (players {fitdf.pid.nunique():,}), "
            f"check {len(chk):,} (players {chk.pid.nunique():,})")
        st = json.loads(json.dumps(DEFAULT_SETTINGS))
        val = val_mask(fitdf["pid"].to_numpy(), st["val_share"])
        res = {"quantile": [], "classifier": []}
        yq = chk["gain"].to_numpy()
        cu = target_rows(chk, "reach_useful")
        for hp in TUNE_GRID:
            st["quantile"] = hp
            st["classifier"] = hp
            st["monotonic_now"] = False
            f = fit_one("gain_q50", fitdf, feats, st, val, f"[{role} tune {hp}] ")
            pq = f["model"].predict(chk[feats])
            res["quantile"].append({"hp": hp, "check_pinball": pinball(yq, pq, 0.5), "iters": f["n_iter"]})
            f = fit_one("reach_useful", fitdf, feats, st, val, f"[{role} tune {hp}] ")
            pu = f["model"].predict_proba(chk.loc[cu, feats])[:, 1]
            ll = float(log_loss(chk.loc[cu, "reach_useful"].astype(int), np.clip(pu, 1e-7, 1 - 1e-7)))
            res["classifier"].append({"hp": hp, "check_logloss": ll, "iters": f["n_iter"]})
            log(f"[{role}] {hp}: check pinball50 {res['quantile'][-1]['check_pinball']:.5f}, "
                f"useful logloss {ll:.5f}")
        bq = min(res["quantile"], key=lambda r: r["check_pinball"])["hp"]
        bc = min(res["classifier"], key=lambda r: r["check_logloss"])["hp"]
        st["quantile"], st["classifier"] = bq, bc
        # monotonic constraint on now_waa and the isotonic step, per classifier
        mono_res, cal_res = {}, {}
        for t in list(REACH) + ["regular_future"]:
            rows = target_rows(chk, t)
            yc = chk.loc[rows, t].to_numpy().astype(int)
            Xc = chk.loc[rows, feats]
            lls = {}
            fits = {}
            for mono in ((False, True) if t in REACH else (False,)):
                st["monotonic_now"] = mono
                st["calibrate"] = {t: True}
                f = fit_one(t, fitdf, feats, st, val, f"[{role} mono={mono}] ")
                fits[mono] = f
                p_raw = f["model"].predict_proba(Xc)[:, 1]
                p_iso = f["iso"].predict(p_raw)
                lls[mono] = {"raw": float(log_loss(yc, np.clip(p_raw, 1e-7, 1 - 1e-7), labels=[0, 1])),
                             "iso": float(log_loss(yc, np.clip(p_iso, 1e-7, 1 - 1e-7), labels=[0, 1])),
                             "ece_raw": ece(calib_table(yc, p_raw)), "ece_iso": ece(calib_table(yc, p_iso)),
                             "n_check": int(len(yc)), "pos_check": int(yc.sum())}
            mono_res[t] = {str(k): v for k, v in lls.items()}
            log(f"[{role}] {t}: {mono_res[t]}")
        # keep the monotonic constraint when it does not raise check log loss
        # (summed over the three reach classifiers, raw probabilities)
        base = sum(mono_res[t]["False"]["raw"] for t in REACH)
        cons = sum(mono_res[t]["True"]["raw"] for t in REACH)
        keep_mono = cons <= base * 1.001
        cal = {}
        for t in list(REACH) + ["regular_future"]:
            key = "True" if (keep_mono and t in REACH) else "False"
            r = mono_res[t][key]
            # isotonic only when it clearly helps: >= 0.5% lower check log loss
            cal[t] = bool(r["iso"] < r["raw"] * 0.995)
            cal_res[t] = {"raw": r["raw"], "iso": r["iso"], "ece_raw": r["ece_raw"], "ece_iso": r["ece_iso"],
                          "use_iso": cal[t]}
        st["monotonic_now"] = bool(keep_mono)
        st["calibrate"] = cal
        st["source"] = out["source"]
        out[role] = st
        report[role] = {"grid": res, "monotonic": mono_res, "monotonic_sum_raw": {"free": base, "constrained": cons},
                        "calibration": cal_res, "chosen": st,
                        "rows": {"fit": int(len(fitdf)), "check": int(len(chk))}}
        log(f"[{role}] chosen: quantile {bq}, classifier {bc}, monotonic {keep_mono}, calibrate {cal}")
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    old = load_settings() if os.path.exists(SETTINGS_PATH) else {}
    old.update(out)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(old, fh, indent=1)
    log("wrote", SETTINGS_PATH)
    write_report("peak_tune.json" if len(args.roles) == 2 else f"peak_tune_{''.join(args.roles)}.json", report)


def cmd_fit_oof(args):
    settings = load_settings()
    for role in args.roles:
        st = settings[role]
        g = load_group(role, args.rows)
        feats, _c, _f = features_of(role)
        preds, truths, fold_ids = [], [], []
        folds = args.folds if args.folds is not None else list(range(C.N_FOLDS))
        for f in folds:
            tr = g[g["fold"] != f].reset_index(drop=True)
            te = g[g["fold"] == f]
            log(f"[{role} oof fold {f}] train {len(tr):,} rows, predict {len(te):,}")
            models = fit_set(tr, feats, st, log_prefix=f"[{role} f{f}] ")
            preds.append(predict_set(models, te, feats).reset_index(drop=True))
            truths.append(te.reset_index(drop=True))
            fold_ids.append(np.full(len(te), f, dtype=np.int8))
            if f == 0:
                os.makedirs(os.path.join(C.MODELS_DIR, "oof"), exist_ok=True)
                with open(os.path.join(C.MODELS_DIR, "oof", f"peak_{role}_fold0.pkl"), "wb") as fh:
                    pickle.dump({"models": models, "features": feats}, fh)
            del tr, models
        write_held_out(pd.concat(truths, ignore_index=True), pd.concat(preds, ignore_index=True), role, "oof",
                       np.concatenate(fold_ids), folds_note=folds)
    assemble_preds()


def cmd_fit_time(args):
    settings = load_settings()
    for role in args.roles:
        st = settings[role]
        t0 = time.time()
        g = load_group(role, args.rows)
        feats, _c, _f = features_of(role)
        tr = g[g["time_split"] == "train"].reset_index(drop=True)
        te = g[g["time_split"] == "test"].reset_index(drop=True)
        log(f"[{role} time] rows '{args.rows}': train {len(tr):,} (out of an org {int((tr['in_org'] == 0).sum()):,}),"
            f" predict {len(te):,} (out of an org {int((te['in_org'] == 0).sum()):,})")
        models = fit_set(tr, feats, st, log_prefix=f"[{role} time] ")
        pr = predict_set(models, te, feats)
        write_held_out(te, pr, role, "time", np.full(len(te), -1, dtype=np.int8))
        log(f"[{role} time] fit and predicted in {time.time() - t0:.0f}s")
    assemble_preds()


def cmd_fit_final(args):
    settings = load_settings()
    man_path = os.path.join(C.MODELS_DIR, "peak_manifest.json")
    manifest = {}
    if os.path.exists(man_path):
        with open(man_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    manifest.update({"method": METHOD, "group": GROUP, "date": args.date, "sklearn": sklearn.__version__,
                     "python": sys.version.split()[0],
                     "basis": C.BASIS,
                     "basis_rule": "one model set per league: DEV priced with this league's engine calibration "
                                   f"(DEV engine price tag {C.waa_tag(C.BASIS)}); score only this league",
                     "rows": args.rows,
                     "row_rule": ROW_RULES[args.rows],
                     "age_range": [16, 26],
                     "app_rule": f"p_* = 1.0 when now_waa >= bar - {BAR_TOL}; reach models train on rows "
                                 f"below that line only",
                     "order_rule": "p_useful = min(p_useful, p_mlb), p_good = min(p_good, p_useful) "
                                   "(common.chance_order, fix 2)",
                     "extra_features": {"amateur": "1 = amateur: DEV lev_raw AMA; TGS / BLM app Lev AMA or INT "
                                                   "(common.amateur_flag); 0 = in an org or a free agent"},
                     "settings_file": os.path.relpath(SETTINGS_PATH, C.ML_ROOT),
                     "quantiles": dict(zip(QCOLS, QUANTS)),
                     "bars": {v[0]: v[1] for v in REACH.values()},
                     "post": "gain quantiles clipped at 0 and sorted per row; isotonic step applied when "
                             "settings.calibrate says so (fit on the grouped validation players)"})
    lib, dev = quantile_backend()
    manifest["quantile_backend"] = (f"xgboost {_XGB.get('version')} (trained on {dev})" if lib == "xgboost"
                                    else f"scikit-learn {sklearn.__version__}")
    targets = TARGETS
    if getattr(args, "targets", None):
        targets = [t for t in TARGETS if t in args.targets or ("gain" in args.targets and t in QCOLS)]
    manifest.setdefault("roles", {})
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    for role in args.roles:
        st = settings[role]
        t0 = time.time()
        g = load_group(role, args.rows)
        feats, cats, _f = features_of(role)
        log(f"[{role} final] train {len(g):,} rows (out of an org {int((g['in_org'] == 0).sum()):,}), "
            f"players {g.pid.nunique():,}; targets {', '.join(targets)}")
        old = ((manifest["roles"].get(role) or {}).get("models") or {}) if targets != TARGETS else {}
        old_loss = {t: v.get("val_loss") for t, v in old.items()}
        models = fit_set(g, feats, st, targets=targets, log_prefix=f"[{role} final] ")
        for t, fit in models.items():
            if old_loss.get(t) is not None:
                log(f"[{role} final] {t}: validation loss {old_loss[t]:.5f} before -> {fit['val_loss']:.5f} now")
        files = dict(old)
        for t, fit in models.items():
            path = os.path.join(C.MODELS_DIR, f"peak_{role}_{t}.pkl")
            with open(path, "wb") as fh:
                pickle.dump({"target": t, "role": role, "features": feats, "categorical": cats,
                             "model": fit["model"], "iso": fit["iso"]}, fh)
            files[t] = {"file": os.path.basename(path), "train_rows": fit["n_train"], "val_rows": fit["n_val"],
                        "iterations": fit["n_iter"], "val_loss": round(fit["val_loss"], 6),
                        "isotonic": fit["iso"] is not None}
        manifest["roles"][role] = {"features": feats, "categorical": {c: C.CATEGORICAL[c] for c in cats},
                                   "settings": st,
                                   "train_rows": int(len(g)), "train_players": int(g.pid.nunique()),
                                   "train_rows_outside_org": int((g["in_org"] == 0).sum()),
                                   "train_rows_amateur": int((g["amateur"] == 1).sum()),
                                   "fit_seconds": round(time.time() - t0, 1),
                                   "models": files}
    os.makedirs(C.MODELS_DIR, exist_ok=True)
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    log("wrote", man_path)


def _score(model_fit, target, X, y):
    if target in QCOLS:
        q = QUANTS[QCOLS.index(target)]
        return pinball(y, model_fit["model"].predict(X), q)
    p = prob(model_fit, X)
    return float(log_loss(y, np.clip(p, 1e-7, 1 - 1e-7), labels=[0, 1]))


def cmd_importance(args):
    """Permutation importance on held-out fold-0 rows with the fold-0 OOF
    models (trained on folds 1-4): loss increase when a feature family (all
    its columns shuffled together, same row order) or one feature is shuffled."""
    rng = np.random.default_rng(0)
    for role in args.roles:
        path = os.path.join(C.MODELS_DIR, "oof", f"peak_{role}_fold0.pkl")
        with open(path, "rb") as fh:
            saved = pickle.load(fh)
        models, feats = saved["models"], saved["features"]
        _f, _c, fam = features_of(role)
        g = load_group(role, args.rows)
        te = g[g["fold"] == 0].reset_index(drop=True)
        del g
        fams = {}
        for f in feats:
            fams.setdefault(fam.get(f) or "other", []).append(f)
        out = {"rows_note": "held-out fold 0, sampled", "families": {k: v for k, v in fams.items()}}
        for t in ("gain_q50", "reach_useful"):
            rows = target_rows(te, t)
            sub = te.loc[rows]
            if len(sub) > args.n_rows:
                sub = sub.sample(args.n_rows, random_state=0)
            X = sub[feats].reset_index(drop=True)
            y = (sub["gain"] if t in QCOLS else sub[t]).to_numpy()
            if t not in QCOLS:
                y = y.astype(int)
            base = _score(models[t], t, X, y)
            res = {"n_rows": int(len(X)), "base_loss": base, "loss": "pinball 0.5 (= MAE / 2)" if t in QCOLS
                   else "log loss", "family": {}, "feature": {}}
            for fname, cols in fams.items():
                vals = []
                for _r in range(args.repeats):
                    Xp = X.copy()
                    perm = rng.permutation(len(X))
                    for c in cols:
                        Xp[c] = X[c].to_numpy()[perm] if not isinstance(X[c].dtype, pd.CategoricalDtype) \
                            else pd.Categorical.from_codes(X[c].cat.codes.to_numpy()[perm], dtype=X[c].dtype)
                    vals.append(_score(models[t], t, Xp, y) - base)
                res["family"][fname] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals)),
                                        "share_of_base": float(np.mean(vals) / base)}
            log(f"[{role} {t}] families:", {k: round(v["mean"], 5) for k, v in
                                           sorted(res["family"].items(), key=lambda kv: -kv[1]["mean"])})
            for c in feats:
                vals = []
                for _r in range(args.repeats):
                    Xp = X.copy()
                    perm = rng.permutation(len(X))
                    Xp[c] = X[c].to_numpy()[perm] if not isinstance(X[c].dtype, pd.CategoricalDtype) \
                        else pd.Categorical.from_codes(X[c].cat.codes.to_numpy()[perm], dtype=X[c].dtype)
                    vals.append(_score(models[t], t, Xp, y) - base)
                res["feature"][c] = {"mean": float(np.mean(vals)), "sd": float(np.std(vals)),
                                     "family": fam.get(c)}
            top = sorted(res["feature"].items(), key=lambda kv: -kv[1]["mean"])[:15]
            res["top15"] = [{"feature": k, **v} for k, v in top]
            log(f"[{role} {t}] top 15:", [(k, round(v["mean"], 5)) for k, v in top])
            out[t] = res
        write_report(f"peak_importance_{role}.json", out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def roles_arg(p):
        p.add_argument("--roles", nargs="+", default=list(C.ROLES), choices=list(C.ROLES),
                       help="roles to run (default H P)")
        p.add_argument("--basis", required=True, choices=list(C.BASES),
                       help="engine calibration of the DEV rows = the league the models serve")
        p.add_argument("--rows", default="all", choices=list(ROW_RULES),
                       help="all = in an org and outside (default, fix 6); org = in an org only")

    p = sub.add_parser("tune", help="pick settings on the fold-0 training set")
    roles_arg(p)
    p.add_argument("--sample", type=float, default=1.0, help="share of players to use (default 1.0)")
    p.add_argument("--date", default=_dt.date.today().isoformat(), help="date string for the settings note")
    p = sub.add_parser("fit-oof", help="5-fold grouped out-of-fold predictions")
    roles_arg(p)
    p.add_argument("--folds", type=int, nargs="+", default=None, help="only these folds (default all)")
    p = sub.add_parser("fit-time", help="fit on time_split train, predict time_split test")
    roles_arg(p)
    p = sub.add_parser("fit-final", help="fit on every training row and save the models")
    roles_arg(p)
    p.add_argument("--date", default=_dt.date.today().isoformat(), help="date string for the manifest")
    p.add_argument("--targets", nargs="+", choices=TARGETS + ["gain"], default=None,
                   help="refit only these targets ('gain' = the five gain quantiles); the other saved "
                        "models and their manifest rows stay as they are (default: all)")
    p = sub.add_parser("importance", help="permutation importance on held-out fold-0 rows")
    roles_arg(p)
    p.add_argument("--n-rows", type=int, default=40000, help="held-out rows to sample (default 40000)")
    p.add_argument("--repeats", type=int, default=3, help="shuffles per feature (default 3)")
    args = ap.parse_args(argv)
    C.use_basis(args.basis)
    log(f"basis {args.basis}: tables {os.path.basename(C.dev_table('H'))} / {os.path.basename(C.dev_table('P'))}, "
        f"models {C.MODELS_DIR}")
    t0 = time.time()
    {"tune": cmd_tune, "fit-oof": cmd_fit_oof, "fit-time": cmd_fit_time, "fit-final": cmd_fit_final,
     "importance": cmd_importance}[args.cmd](args)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
