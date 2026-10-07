"""
xgb_models.py - XGBoost twins of the scikit-learn HistGradientBoosting models
the ML dev model uses, with the scikit-learn settings mapped across.

Why (user, 2026-10-02 and 2026-10-06): training must not load every CPU core
(i9 degradation worry). scikit-learn's HistGradientBoosting trains on all
cores; XGBoost trains on the GPU (RTX 4090) with one CPU thread for the data
prep. Head to head on held-out TGS players (gpu_compare.py, 2026-09-27): the
gain quantiles were better on XGBoost (the low marks learned at all), the
reach classifiers tied (scikit-learn a hair better on log loss, 0.1 to 1.5%).

Mapping (scikit-learn -> XGBoost): max_iter -> n_estimators; max_leaf_nodes ->
max_leaves with grow_policy lossguide; min_samples_leaf -> min_child_weight
for the losses with a unit hessian (squared, absolute, quantile; a logistic
hessian is tiny on rare outcomes, so classifiers keep 1.0); l2_regularization
-> reg_lambda; max_bins -> max_bin; n_iter_no_change -> early_stopping_rounds.
Saved models are switched to the CPU with one thread, so scoring runs on any
PC that has xgboost.
"""
import numpy as np

_STATE = {}
LOSS_OBJECTIVE = {"squared_error": "reg:squarederror", "absolute_error": "reg:absoluteerror",
                  "quantile": "reg:quantileerror"}


def backend():
    """('xgboost', 'cuda' | 'cpu') when xgboost imports (cuda when a tiny GPU
    fit works), else ('sklearn', None)."""
    if "backend" not in _STATE:
        try:
            import xgboost as xgb
            dev = "cpu"
            try:
                xgb.XGBRegressor(n_estimators=2, device="cuda", tree_method="hist", n_jobs=1).fit(
                    np.zeros((8, 2)), np.arange(8.0))
                dev = "cuda"
            except Exception:
                pass
            _STATE["backend"] = ("xgboost", dev)
            _STATE["version"] = xgb.__version__
        except ImportError:
            _STATE["backend"] = ("sklearn", None)
    return _STATE["backend"]


def version():
    backend()
    return _STATE.get("version")


def _common(p, unit_hessian):
    return dict(tree_method="hist", device=backend()[1], learning_rate=p["learning_rate"],
                max_leaves=p["max_leaf_nodes"], grow_policy="lossguide", max_depth=0,
                reg_lambda=p["l2_regularization"],
                min_child_weight=float(p["min_samples_leaf"]) if unit_hessian else 1.0,
                max_bin=p.get("max_bins", 255), n_estimators=p["max_iter"],
                early_stopping_rounds=p["n_iter_no_change"], enable_categorical=True,
                max_cat_to_onehot=1, random_state=0, n_jobs=1)


def regressor(p, loss, quantile=None):
    """p: scikit-learn style settings (learning_rate, max_iter, max_leaf_nodes,
    min_samples_leaf, l2_regularization, max_bins, n_iter_no_change)."""
    import xgboost as xgb
    kw = _common(p, True)
    if loss == "quantile":
        return xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=quantile, **kw)
    return xgb.XGBRegressor(objective=LOSS_OBJECTIVE[loss], **kw)


def classifier(p, monotone_feature=None, feats=()):
    import xgboost as xgb
    # positional form: a {name: 1} dict does not survive pickling (the reloaded
    # booster rejects it at predict time)
    feats = list(feats)
    mono = ("(" + ",".join("1" if f == monotone_feature else "0" for f in feats) + ")"
            if monotone_feature and monotone_feature in feats else None)
    return xgb.XGBClassifier(objective="binary:logistic", eval_metric="logloss",
                             monotone_constraints=mono, **_common(p, False))


def fit(model, X, y, Xv, yv):
    """Fit with early stopping on the validation rows, then switch the model to
    the CPU with one thread for prediction and saving."""
    model.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
    model.set_params(device="cpu", n_jobs=1)
    return model


def is_xgb(model):
    return type(model).__module__.startswith("xgboost")


def n_iter(model):
    """Boosting rounds kept (scikit-learn n_iter_, XGBoost best round + 1)."""
    if hasattr(model, "n_iter_"):
        return int(model.n_iter_)
    best = getattr(model, "best_iteration", None)
    return int(best) + 1 if best is not None else int(model.get_params().get("n_estimators") or 0)
