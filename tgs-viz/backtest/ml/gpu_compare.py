"""
gpu_compare.py - head to head: the peak models on scikit-learn
HistGradientBoosting (CPU; the live models until 2026-10-02, when the gain
quantiles moved to XGBoost) vs XGBoost on the GPU.

User, 2026-09-27: "I would assume the GPU would run far faster and I have no
idea why we wouldn't have done that to begin with" (machine: RTX 4090). The
switch was kept only if XGBoost matched or beat the scikit-learn models on
held-out players.

Same rows, same targets, same grouped early-stopping players, same time split
(train on the players first seen up to the cutoff, test on later debuts) as
peak.py fit-time. Metrics on in-org test rows: pinball loss per gain quantile;
log loss, AUC and calibration error for the reach classifiers (rows below the
bar, the rows they train on); fit seconds per model. Writes
report/<basis>/gpu_compare.json. The process runs at below-normal priority.

  py -3.14 tgs-viz/backtest/ml/gpu_compare.py --basis TGS [--roles H,P]
"""
import argparse
import ctypes
import json
import os
import sys
import time

import numpy as np
from sklearn.metrics import log_loss, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C   # noqa: E402
import peak as PK    # noqa: E402

try:                                       # below-normal priority: the user's game comes first
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
except Exception:
    pass


def xgb_model(kind, st, feats, quantile=None, monotonic=False):
    import xgboost as xgb
    hp = st["quantile" if kind == "quantile" else "classifier"]
    common = dict(tree_method="hist", device="cuda", learning_rate=hp["learning_rate"],
                  max_leaves=hp["max_leaf_nodes"], grow_policy="lossguide", max_depth=0,
                  reg_lambda=hp["l2_regularization"],
                  # quantile loss has a unit hessian, so this is the sklearn
                  # min_samples_leaf; a logistic hessian p(1-p) is tiny on rare
                  # outcomes, so the classifiers keep XGBoost's default
                  min_child_weight=float(hp["min_samples_leaf"]) if kind == "quantile" else 1.0,
                  max_bin=st["max_bins"], n_estimators=st["max_iter"],
                  early_stopping_rounds=st["n_iter_no_change"], enable_categorical=True,
                  max_cat_to_onehot=1, random_state=0)
    if kind == "quantile":
        return xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=quantile, **common)
    mono = {"now_waa": 1} if monotonic and "now_waa" in feats else None
    return xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss",
                             monotone_constraints=mono, **common)


def ece(y, p, nb=10):
    edges = np.unique(np.quantile(p, np.linspace(0, 1, nb + 1)))
    if len(edges) < 2:
        return 0.0
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, len(edges) - 2)
    return float(sum((idx == b).mean() * abs(y[idx == b].mean() - p[idx == b].mean())
                     for b in range(len(edges) - 1) if (idx == b).any()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--basis", default="TGS", choices=C.BASES)
    ap.add_argument("--roles", default="H,P")
    a = ap.parse_args()
    C.use_basis(a.basis)
    settings = PK.load_settings()
    targets = PK.QCOLS + list(PK.REACH)
    report = {"basis": a.basis, "date": time.strftime("%Y-%m-%d %H:%M"), "roles": {}}
    for role in a.roles.split(","):
        st = settings[role]
        g = PK.load_group(role, "all")
        feats, _c, _f = PK.features_of(role)
        tr = g[g["time_split"] == "train"].reset_index(drop=True)
        te = g[g["time_split"] == "test"].reset_index(drop=True)
        del g
        val = PK.val_mask(tr["pid"].to_numpy(), st["val_share"])
        org = (te["in_org"] == 1).to_numpy()
        print(f"{a.basis} {role}: train {len(tr):,} test {len(te):,} ({int(org.sum()):,} in an org)", flush=True)
        rows = {}
        for t in targets:
            rmask = PK.target_rows(tr, t)
            trm, vam = rmask & ~val, rmask & val
            X, Xv = tr.loc[trm, feats], tr.loc[vam, feats]
            if t in PK.QCOLS:
                q = PK.QUANTS[PK.QCOLS.index(t)]
                y, yv = tr.loc[trm, "gain"].to_numpy(), tr.loc[vam, "gain"].to_numpy()
                m_te = te["gain"].notna().to_numpy() & org
                yt = te.loc[m_te, "gain"].to_numpy()
            else:
                y = tr.loc[trm, t].to_numpy().astype(int)
                yv = tr.loc[vam, t].to_numpy().astype(int)
                bar = PK.REACH[t][1]
                m_te = te[t].notna().to_numpy() & (te["now_waa"].to_numpy() < bar - PK.BAR_TOL) & org
                yt = te.loc[m_te, t].to_numpy().astype(int)
            Xt = te.loc[m_te, feats]
            res = {}
            for backend in ("sklearn_cpu", "xgboost_gpu"):
                t0 = time.time()
                if t in PK.QCOLS:
                    if backend == "sklearn_cpu":
                        m = PK.make_model("quantile", st["quantile"], st, feats, quantile=q, sklearn_only=True)
                        m.fit(X, y, X_val=Xv, y_val=yv)
                        it = int(m.n_iter_)
                    else:
                        m = xgb_model("quantile", st, feats, quantile=q)
                        m.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
                        it = int(m.best_iteration) + 1
                    secs = time.time() - t0
                    p = np.maximum(m.predict(Xt), 0.0)
                    res[backend] = {"pinball": round(PK.pinball(yt, p, q), 5), "iters": it, "seconds": round(secs, 1)}
                else:
                    mono = st.get("monotonic_now", False)
                    if backend == "sklearn_cpu":
                        m = PK.make_model("classifier", st["classifier"], st, feats, monotonic=mono)
                        m.fit(X, y, X_val=Xv, y_val=yv)
                        it = int(m.n_iter_)
                    else:
                        m = xgb_model("classifier", st, feats, monotonic=mono)
                        m.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
                        it = int(m.best_iteration) + 1
                    secs = time.time() - t0
                    p = np.clip(m.predict_proba(Xt)[:, 1], 1e-6, 1 - 1e-6)
                    res[backend] = {"logloss": round(float(log_loss(yt, p, labels=[0, 1])), 5),
                                    "auc": round(float(roc_auc_score(yt, p)), 5), "ece": round(ece(yt, p), 5),
                                    "iters": it, "seconds": round(secs, 1)}
                print(f"  {role} {t:13} {backend:12} {res[backend]}", flush=True)
            rows[t] = res
        report["roles"][role] = {"train_rows": int(len(tr)), "test_rows_in_org": int(org.sum()), "targets": rows}
        del tr, te
    out = os.path.join(C.REPORT_DIR, "gpu_compare.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
