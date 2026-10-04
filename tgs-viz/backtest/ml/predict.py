"""
predict.py - the one shared scoring helper for the DEV machine-learning models.

User, 2026-09-24: "is there any way you can make a machine learning model to
help with figuring out this dev stuff".

Every caller that turns a table of players into ML numbers goes through
predict() here, so the rules live in one place:
  basis         one model set per league. load_bundle('TGS') reads
                models/TGS/peak_manifest.json and path_manifest.json and the
                model files they list; a TGS player is scored with the TGS
                models only, a BLM player with the BLM models only
  features      the manifest's feature order; level, pos, bats and throws are
                rebuilt as pandas categories with the manifest's category lists
                (so the codes match the training codes); 'amateur' comes from
                common.amateur_flag (DEV lev_raw AMA, app Lev AMA or INT)
  gain          gain_q10 .. gain_q90: the five quantile models, clipped at 0 and
                sorted per row (they never cross, never go below 0)
  chances       p_mlb / p_useful / p_good: the average of the reach
                classifier and the chance the gain quantiles give for the bar
                (common.blend_chance, 2026-09-26); 1.0 when now_waa >= bar -
                0.05 (the app rule); then the order rule (fix 2): p_useful =
                min(p_useful, p_mlb), p_good = min(p_good, p_useful)
                (common.chance_order)
  regular       p_regular: some later MLB season with >= 300 PA or >= 150 BF
  path          d1..d5 medians, d1_mean..d5_mean expected changes (fix 5, for
                money), d1_q25 / d1_q75 (sorted pair), p_present1 (ages 27+
                only; NaN below 27)
  range flags   peak_in_range: age 16-26 (the peak training ages); path_in_range:
                age 16-38; ml_source: "ML", or "ML, outside training range"
                when the age is outside the peak ages or the player is an
                unsigned international amateur (app Lev INT: DEV has no such
                players; he reads as an amateur)

Commands (Python 3.14):
  check --basis B [--n 1000]   unit checks on n DEV rows of the basis table:
                               predict() equals calling every model directly,
                               and p_good <= p_useful <= p_mlb on every row;
                               then the same order check on the basis league's
                               scoring rows (score_<B>_H / _P)
"""
import argparse
import json
import os
import pickle
import re
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

QCOLS = ["gain_q10", "gain_q25", "gain_q50", "gain_q75", "gain_q90"]
REACH = {"reach_mlb": ("p_mlb", C.PEAK_BARS["mlb"]),
         "reach_useful": ("p_useful", C.PEAK_BARS["useful"]),
         "reach_good": ("p_good", C.PEAK_BARS["good"])}
BAR_TOL = 0.05                      # dev_signals.BAR_TOLERANCE
KS = (1, 2, 3, 4, 5)
OUTSIDE_NOTE = "ML, outside training range"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- loading
def models_dir(basis):
    return os.path.join(C.MODELS_ROOT, C.check_basis(basis))


def not_installed_hint(basis):
    """One line for a missing schema / manifest: the models are the author's files, not trained here."""
    return (f"models for basis {basis} are not installed on this machine; install the author's files with "
            f"`python tgs-viz/backtest/ml/install_models.py --from <dir>` (training is not run on the Mac)")


# ---------------------------------------------------------------- library versions
def recorded_versions(pm, am):
    """{'sklearn', 'python', 'xgboost'} the models were trained with, read from the peak manifest `pm`
    and the path manifest `am` (peak.py fit-final / path.py fit-final record them). A value is None when
    the manifest does not say. xgboost comes from peak's "quantile_backend" text ("xgboost 3.4.1 (trained
    on cpu)"); None also when the quantile models are scikit-learn."""
    meta = am.get("_meta") or {}
    hit = re.match(r"\s*xgboost\s+(\S+)", str(pm.get("quantile_backend") or ""))
    return {"sklearn": pm.get("sklearn") or meta.get("sklearn"),
            "python": pm.get("python") or meta.get("python"),
            "xgboost": hit.group(1) if hit else None}


def installed_versions():
    """{'sklearn', 'python', 'xgboost'} of this interpreter (None for a package that is not installed)."""
    from importlib import metadata

    def ver(dist):
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return None
    return {"sklearn": ver("scikit-learn"), "python": sys.version.split()[0], "xgboost": ver("xgboost")}


def version_mismatches(rec, now=None):
    """[(library, trained, installed)] for scikit-learn and xgboost (the libraries a pickle depends on)
    whose recorded version differs from the installed one. A library the manifest does not record is not
    checked. Python is not compared here: a minor-version gap alone does not break a pickle."""
    now = now or installed_versions()
    return [(lib, rec[lib], now.get(lib)) for lib in ("sklearn", "xgboost")
            if rec.get(lib) and rec[lib] != now.get(lib)]


def warn_versions(basis, pm, am, now=None):
    """Warn (stderr) when the models were trained with other scikit-learn / xgboost versions than the
    installed ones. Never stops scoring: sklearn itself raises when a pickle cannot be read. Returns the
    mismatch list."""
    bad = version_mismatches(recorded_versions(pm, am), now)
    for lib, trained, have in bad:
        name = {"sklearn": "scikit-learn"}.get(lib, lib)
        print(f"WARNING: the {basis} models were trained with {name} {trained} but this Python has "
              f"{have or 'no ' + name}; pickles are not portable across versions, so scores may be wrong or "
              f"loading may fail. Run `python tgs-viz/backtest/ml/install_models.py --basis {basis} --check` "
              "for the steps to build a matching environment (python.ml in settings.local.json).",
              file=sys.stderr, flush=True)
    return bad


def load_bundle(basis):
    """{basis, peak: manifest, path: manifest, models: {role: {'peak': {target:
    fit dict}, 'path': {name: model}}}} for one basis. Stops with a message
    when a manifest is missing (run peak.py / path.py fit-final first)."""
    d = models_dir(basis)
    out = {"basis": basis, "models": {}}
    for grp in ("peak", "path"):
        p = os.path.join(d, f"{grp}_manifest.json")
        if not os.path.exists(p):
            raise SystemExit(f"no {grp} models for basis {basis} ({p}); run: py -3.14 tgs-viz/backtest/ml/"
                             f"{grp}.py fit-final --basis {basis}\n{not_installed_hint(basis)}")
        with open(p, encoding="utf-8") as fh:
            out[grp] = json.load(fh)
    pm, am = out["peak"], out["path"]
    if pm.get("basis") not in (None, basis) or am.get("_meta", {}).get("basis") not in (None, basis):
        raise SystemExit(f"manifest basis does not match {basis}")
    warn_versions(basis, pm, am)
    for role in C.ROLES:
        r = {"peak": {}, "path": {}}
        for t, info in pm["roles"][role]["models"].items():
            with open(os.path.join(d, info["file"]), "rb") as fh:
                r["peak"][t] = pickle.load(fh)
        for name, info in am[role]["models"].items():
            with open(os.path.join(d, info["file"]), "rb") as fh:
                r["path"][name] = pickle.load(fh)
        out["models"][role] = r
    return out


def calib_check(bundle, basis):
    """(trained fingerprint or None, current fingerprint, message or None). The models
    learned from DEV priced with one engine calibration; after the basis' calibration
    changes they score prices they never saw. A mismatch is a message (score.py warns);
    models written before the fingerprint was recorded give an info message."""
    cur = C.calib_fingerprint(basis)
    pm, am = bundle["peak"], bundle["path"].get("_meta") or {}

    def recorded(m):
        # the field, else the "DEV engine price tag <fp>-<basis>" text older manifests carry
        if m.get("calib_fingerprint"):
            return m["calib_fingerprint"]
        hit = re.search(r"price tag ([0-9a-f]{10})-", str(m.get("basis_rule") or ""))
        return hit.group(1) if hit else None

    fps = {recorded(pm), recorded(am)}
    fps.discard(None)
    if not fps:
        return None, cur, (f"the {basis} models do not record their calibration fingerprint (trained before "
                           f"the check); current calibration {cur}")
    if fps != {cur}:
        return ",".join(sorted(fps)), cur, (f"the {basis} models were trained on calibration "
                                            f"{', '.join(sorted(fps))} but the current one is {cur}; retrain "
                                            f"(peak.py and path.py fit-final) before trusting these scores")
    return cur, cur, None


# ---------------------------------------------------------------- features
def feature_frame(df, feats, cats):
    """X for the models: df's columns in the manifest order; categorical
    columns rebuilt with the manifest's category lists; model-only extras
    (amateur) made when missing."""
    missing = [f for f in feats if f not in df.columns and f not in C.MODEL_EXTRA_FEATURES]
    if missing:
        raise KeyError(f"table lacks features {missing[:8]}")
    extra = [f for f in feats if f in C.MODEL_EXTRA_FEATURES and f not in df.columns]
    src = C.add_model_extras(df.copy(), extra) if extra else df
    cols = {}
    for f in feats:
        v = src[f]
        if f in cats:
            vals = v.astype(object).where(v.notna(), None).to_numpy()
            cols[f] = pd.Categorical(vals, categories=cats[f])
        else:
            cols[f] = v.to_numpy(dtype=np.float32)
    return pd.DataFrame(cols, index=df.index)


def _cats(manifest_role):
    c = manifest_role.get("categorical") or {}
    if isinstance(c, list):                         # older manifests: names only
        c = {k: C.CATEGORICAL[k] for k in c}
    return c


# ---------------------------------------------------------------- predict
def _prob(fit, X):
    p = fit["model"].predict_proba(X)[:, 1]
    if fit.get("iso") is not None:
        p = fit["iso"].predict(p)
    return np.clip(p, 0.0, 1.0)


def predict(bundle, df, role):
    """ML numbers for the rows of df (one role). Returns a DataFrame on df's
    index. df needs the manifest features (or lev_raw / lev_app for the
    'amateur' extra), age and now_waa."""
    if len(df) == 0:
        return pd.DataFrame(index=df.index)
    pm_role = bundle["peak"]["roles"][role]
    am_role = bundle["path"][role]
    mods = bundle["models"][role]
    out = {}
    # peak
    Xp = feature_frame(df, pm_role["features"], _cats(pm_role))
    q = np.column_stack([mods["peak"][c]["model"].predict(Xp) for c in QCOLS])
    q = np.sort(np.maximum(q, 0.0), axis=1)
    for j, c in enumerate(QCOLS):
        out[c] = q[:, j].astype(np.float32)
    now = df["now_waa"].to_numpy(dtype=np.float64)
    for t, (col, bar) in REACH.items():
        p = C.blend_chance(_prob(mods["peak"][t], Xp), bar - now, q)
        with np.errstate(invalid="ignore"):
            at_bar = now >= bar - BAR_TOL          # the app rule; a missing now_waa reads the model
        out[col] = np.where(at_bar, 1.0, p).astype(np.float32)
    out["p_mlb"], out["p_useful"], out["p_good"] = C.chance_order(out["p_mlb"], out["p_useful"], out["p_good"])
    out["p_regular"] = _prob(mods["peak"]["regular_future"], Xp).astype(np.float32)
    # path
    Xa = feature_frame(df, am_role["features"], _cats(am_role))
    for name, m in mods["path"].items():
        if name == "present1":
            continue
        out[name] = m.predict(Xa).astype(np.float32)
    lo = np.minimum(out["d1_q25"], out["d1_q75"])
    hi = np.maximum(out["d1_q25"], out["d1_q75"])
    out["d1_q25"], out["d1_q75"] = lo, hi
    age = df["age"].to_numpy(dtype=np.float64)
    pp = np.full(len(df), np.nan, dtype=np.float32)
    old = age >= 27
    if old.any():
        pp[old] = mods["path"]["present1"].predict_proba(Xa[old])[:, 1]
    out["p_present1"] = pp
    # range flags
    plo, phi = bundle["peak"].get("age_range", [16, 26])
    alo, ahi = am_role.get("age_range", [16, 38])
    out["peak_in_range"] = (age >= plo) & (age <= phi)
    out["path_in_range"] = (age >= alo) & (age <= ahi)
    intl = np.zeros(len(df), bool)
    if "lev_app" in df.columns:
        intl = df["lev_app"].astype(object).where(df["lev_app"].notna(), "").astype(str).str.strip().eq("INT").to_numpy()
    ok = out["peak_in_range"] & ~intl
    out["ml_source"] = np.where(ok, "ML", OUTSIDE_NOTE)
    order = QCOLS + ["p_mlb", "p_useful", "p_good", "p_regular"] + [f"d{k}" for k in KS] \
        + [f"d{k}_mean" for k in KS if f"d{k}_mean" in out] + ["d1_q25", "d1_q75", "p_present1",
                                                                "peak_in_range", "path_in_range", "ml_source"]
    return pd.DataFrame({k: out[k] for k in order}, index=df.index)


# ---------------------------------------------------------------- checks
def direct(bundle, df, role):
    """The same numbers by calling every model by hand on the table's own
    columns (DEV tables already hold the categories), for the unit check.
    Returns (final dict, raw chance dict before the order rule)."""
    pm_role = bundle["peak"]["roles"][role]
    am_role = bundle["path"][role]
    mods = bundle["models"][role]
    d = df.copy()
    d["amateur"] = C.amateur_flag(d)
    Xp = d[pm_role["features"]]
    Xa = d[am_role["features"]]
    res = {}
    for c in QCOLS:
        res[c] = mods["peak"][c]["model"].predict(Xp)
    q = np.sort(np.maximum(np.column_stack([res[c] for c in QCOLS]), 0.0), axis=1)
    for j, c in enumerate(QCOLS):
        res[c] = q[:, j]
    now = d["now_waa"].to_numpy(dtype=np.float64)
    raw = {}
    for t, (col, bar) in REACH.items():
        fit = mods["peak"][t]
        p = fit["model"].predict_proba(Xp)[:, 1]
        if fit.get("iso") is not None:
            p = fit["iso"].predict(p)
        raw[col] = np.where(now >= bar - BAR_TOL, 1.0, C.blend_chance(np.clip(p, 0, 1), bar - now, q))
    res["p_mlb"] = raw["p_mlb"]
    res["p_useful"] = np.minimum(raw["p_useful"], res["p_mlb"])
    res["p_good"] = np.minimum(raw["p_good"], res["p_useful"])
    fit = mods["peak"]["regular_future"]
    res["p_regular"] = fit["model"].predict_proba(Xp)[:, 1]
    for name, m in mods["path"].items():
        if name != "present1":
            res[name] = m.predict(Xa)
    lo, hi = np.minimum(res["d1_q25"], res["d1_q75"]), np.maximum(res["d1_q25"], res["d1_q75"])
    res["d1_q25"], res["d1_q75"] = lo, hi
    pp = np.full(len(d), np.nan)
    old = d["age"].to_numpy() >= 27
    if old.any():
        pp[old] = mods["path"]["present1"].predict_proba(Xa[old])[:, 1]
    res["p_present1"] = pp
    return res, raw


def order_ok(P):
    pm, pu, pg = (P[c].to_numpy(dtype=np.float64) for c in ("p_mlb", "p_useful", "p_good"))
    return (pg <= pu) & (pu <= pm)


def cmd_check(args):
    t0 = time.time()
    bundle = load_bundle(args.basis)
    log(f"loaded {args.basis} models in {time.time() - t0:.1f}s")
    rep = {"basis": args.basis, "dev": {}, "score": {}}
    for role in C.ROLES:
        df = C.load_table(C.dev_table(role, args.basis))
        df = df[(df["age"] >= 16) & (df["age"] <= 38)]
        s = df.sample(args.n, random_state=args.seed).copy()
        del df
        t1 = time.time()
        P = predict(bundle, s, role)
        secs = time.time() - t1
        D, raw = direct(bundle, s, role)
        worst = {}
        for c, v in D.items():
            a = P[c].to_numpy(dtype=np.float64)
            b = np.asarray(v, dtype=np.float64)
            same_nan = np.array_equal(np.isnan(a), np.isnan(b))
            dif = np.nanmax(np.abs(a - b)) if np.isfinite(a).any() else 0.0
            worst[c] = {"max_abs_diff": float(dif), "nan_pattern_same": bool(same_nan)}
        bad = [c for c, w in worst.items() if w["max_abs_diff"] > 1e-6 or not w["nan_pattern_same"]]
        crossed = int(np.sum((raw["p_good"] > raw["p_useful"]) | (raw["p_useful"] > raw["p_mlb"])))
        ok = order_ok(P)
        rep["dev"][role] = {"rows": int(len(s)), "columns_checked": len(worst), "columns_off": bad,
                            "max_abs_diff": max(w["max_abs_diff"] for w in worst.values()),
                            "raw_rows_out_of_order": crossed, "rows_in_order_after": int(ok.sum()),
                            "predict_seconds": round(secs, 2)}
        log(f"[{role} DEV] {len(s):,} rows: {len(worst)} columns vs direct model calls, max abs diff "
            f"{rep['dev'][role]['max_abs_diff']:.2e}, off {bad or 'none'}; raw chances out of order on {crossed} "
            f"rows, in order after the rule {int(ok.sum())} of {len(s)}; predict {secs:.2f}s")
        if bad or not ok.all():
            raise SystemExit(f"CHECK FAILED ({role}): {bad}, order {int((~ok).sum())} rows")
        # league scoring rows of this basis
        sp = C.table_path(f"score_{args.basis}_{role}")
        if os.path.exists(sp):
            sc = C.load_table(sp)
            t1 = time.time()
            Q = predict(bundle, sc, role)
            secs = time.time() - t1
            ok = order_ok(Q)
            num = Q.select_dtypes(include=[np.number])
            nan_cols = {c: int(num[c].isna().sum()) for c in num.columns if num[c].isna().any()}
            young = (sc["age"] >= 16) & (sc["age"] <= 26)
            org = young & (sc["in_org"] == 1)
            rep["score"][role] = {
                "rows": int(len(sc)), "in_order": int(ok.sum()), "nan_columns": nan_cols,
                "ml_source": {k: int(v) for k, v in Q["ml_source"].value_counts().items()},
                "mean_p_useful_16_26_in_org": round(float(Q.loc[org, "p_useful"].mean()), 4),
                "n_16_26_in_org": int(org.sum()),
                "mean_p_useful_16_26_amateur": round(float(Q.loc[young & (sc["lev_app"] == "AMA"), "p_useful"].mean()), 4),
                "n_16_26_amateur": int((young & (sc["lev_app"] == "AMA")).sum()),
                "mean_p_useful_16_26_free_agent": round(float(Q.loc[young & (sc["lev_app"] == "FA"), "p_useful"].mean()), 4),
                "n_16_26_free_agent": int((young & (sc["lev_app"] == "FA")).sum()),
                "predict_seconds": round(secs, 2)}
            log(f"[{role} {args.basis} scoring rows] {rep['score'][role]}")
            if not ok.all():
                raise SystemExit(f"CHECK FAILED ({role} scoring rows): order broken on {int((~ok).sum())} rows")
    os.makedirs(os.path.join(C.REPORT_ROOT, args.basis), exist_ok=True)
    out = os.path.join(C.REPORT_ROOT, args.basis, "predict_check.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=1)
    log(f"PASS; wrote {out} ({time.time() - t0:.0f}s)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="unit checks of predict() on DEV rows and the league's scoring rows")
    p.add_argument("--basis", required=True, choices=list(C.BASES))
    p.add_argument("--n", type=int, default=1000, help="DEV rows per role (default 1000)")
    p.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    {"check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    main()
