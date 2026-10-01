"""
role_stuff_fit.py - how much a pitcher's STUFF changes between the starter and
reliever roles, measured from the league's own ratings archive.

User, 2026-09-26 (Ramon Ragel, RP, stuff 45): "as a starter ragel doesnt drop
to 40 though he stays 45". The sheet (and the engine port) move every
pitcher's stuff a flat 5 points for the other role (-5 for a reliever priced
as a starter, +5 for a starter priced as a reliever). The archive says OOTP
does not: when a pitcher's listed role changes between SP and RP/CL with every
pitch grade, HRR, PBABIP and CON unchanged, his displayed stuff as a reliever
is the same as a starter about half the time and one notch (5) higher the
rest (TGS 2,211 switches: 51% same, 49% +5, 0.5% more; average +2.5. BLM
1,433: 60% / 37% / 2.5%, average +2.1). The gain is larger for a pitcher
whose best pitches stand out from the rest of his arsenal, and it depends on
the stuff level (display bands narrow higher up the internal scale).

Model (per league, per view): expected gain as a reliever, in 20-80 display
points, = a linear function of the arsenal (pitch count, best grade, second
grade, mean grade, top-two gap, best-vs-rest gap) plus one offset per
displayed stuff level of the listed role (25 or less, 30, ..., 55, 60 or
more), clipped to [0, 15]:
  sp_view      listed SP: gain from his starter stuff (prices his RP line)
  rp_view      listed RP/CL: gain from his reliever stuff (prices his SP line)
  pot_sp_view  / pot_rp_view: the same for potential stuff (STU P) from the
               potential pitch grades
Fitted by least squares on every switch in the league's archive; grouped
5-fold cross-validation by player reports the error against a constant and
against the first form (one linear stuff term), which the level offsets
replaced after review (2026-09-26: the linear term under-predicted 50+ stuff
arms and kept rising past 75).

Observed switches: a pitcher whose own switch is on record with the same pitch
grades and the same listed-role stuff gets what OOTP actually did (the
"observed" table, keyed by player id with his name as a check); the model is
for everyone else. Ragel's own switch: 45 -> 45.

Writes engine/calib/<LEAGUE>/role_stuff.json, read by ingest/ratings.
live_role_stuff() and passed to engine/pitchers.compute(role_stuff=...). The
file is part of the calibration fingerprint, so a new fit re-prices the
archives (agecurve_fit / reprice caches).

Usage:  python tgs-viz/engine/role_stuff_fit.py --league TGS [--write]
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backtest"))
import pitchers as P  # noqa: E402

PITCH = P.PITCH_TYPES
SAME = (PITCH + [k + "P" for k in PITCH]
        + ["HRR", "PBABIP", "CON", "HRR P", "PBABIP P", "CON P",
           "HRR vR", "HRR vL", "PBABIP vR", "PBABIP vL", "CON vR", "CON vL"])
LINEAR = [f for f in P.ROLE_STUFF_FEATURES]            # arsenal terms (no stuff term)
BINS = list(P.ROLE_STUFF_LEVELS)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def role(pos):
    return "SP" if pos == "SP" else ("RP" if pos in ("RP", "CL") else None)


def collect(league):
    """Role switches between consecutive live pulls (same player, same name,
    listed role SP <-> RP/CL, every pitch grade and HRR / PBABIP / CON
    unchanged). Rows: dicts with the arsenal, the stuff of both roles and the
    potential stuff of both roles."""
    import pull_order as PO
    import ratings_db as RDB
    conn = sqlite3.connect(PO.DB_PATH)
    rows, _game = PO.ordered(conn, league, lambda *a: None)
    live = [r for r in rows if r[3] == "live"]
    out, prev = [], None
    for r in live:
        m = RDB.load_pull_map(conn, r[0])
        if prev:
            for pid, a in prev.items():
                b = m.get(pid)
                if not b or a.get("name") != b.get("name"):
                    continue
                ra, rb = role(a.get("pos")), role(b.get("pos"))
                if not ra or not rb or ra == rb:
                    continue
                if any(a.get(k) != b.get(k) for k in SAME):
                    continue
                sa, sb = num(a.get("STU")), num(b.get("STU"))
                if sa is None or sb is None:
                    continue
                sp, rp = (a, b) if ra == "SP" else (b, a)
                out.append({"pid": str(pid), "name": a.get("name"), "pull": r[0],
                            "sp_stu": num(sp.get("STU")), "rp_stu": num(rp.get("STU")),
                            "sp_stu_p": num(sp.get("STU P")), "rp_stu_p": num(rp.get("STU P")),
                            "grades": {k: num(a.get(k)) for k in PITCH if (num(a.get(k)) or 0) > 0},
                            "pot_grades": {k: num(a.get(k + "P")) for k in PITCH if (num(a.get(k + "P")) or 0) > 0}})
        prev = m
    conn.close()
    return out


def design(rows, grade_key, stu_key, gain_of, linear_stu=False):
    X, y, grp = [], [], []
    for r in rows:
        f = P.arsenal_features(r[grade_key], r[stu_key])
        g = gain_of(r)
        if f is None or g is None:
            continue
        lin = [f[k] for k in LINEAR]
        if linear_stu:
            X.append(lin + [f["stu"], 1.0])
        else:
            b = P.role_stuff_level(f["stu"])
            X.append(lin + [1.0 if b == lv else 0.0 for lv in BINS])
        y.append(g)
        grp.append(zlib.crc32(str(r["pid"]).encode()) % 5)
    return np.array(X, float), np.array(y, float), np.array(grp)


def cv_mse(X, y, grp):
    se_m, se_c = [], []
    for k in range(5):
        tr, te = grp != k, grp == k
        if not te.any() or not tr.any():
            continue
        beta = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        se_m.append(np.mean((y[te] - np.clip(X[te] @ beta, 0.0, 15.0)) ** 2))
        se_c.append(np.mean((y[te] - y[tr].mean()) ** 2))
    return float(np.mean(se_m)), float(np.mean(se_c))


def fit_view(rows, grade_key, stu_key, gain_of):
    X, y, grp = design(rows, grade_key, stu_key, gain_of)
    mse, mse_c = cv_mse(X, y, grp)
    Xl, yl, gl = design(rows, grade_key, stu_key, gain_of, linear_stu=True)
    mse_lin, _ = cv_mse(Xl, yl, gl)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    nl = len(LINEAR)
    counts = X[:, nl:].sum(axis=0)
    model = {"features": LINEAR, "coef": [round(float(c), 6) for c in beta[:nl]],
             "level_coef": {str(lv): round(float(c), 6) for lv, c in zip(BINS, beta[nl:]) if counts[BINS.index(lv)] > 0},
             "intercept": 0.0, "clip": [0.0, 15.0], "mean_gain": round(float(y.mean()), 4)}
    pred = np.clip(X @ beta, 0.0, 15.0)
    report = {"n": int(len(y)), "mean_gain": round(float(y.mean()), 3),
              "share_gaining": round(float(np.mean(y > 0)), 3),
              "cv_mse_constant": round(mse_c, 3), "cv_mse_linear_stu_form": round(mse_lin, 3),
              "cv_mse_model": round(mse, 3),
              "rows_per_level": {str(lv): int(c) for lv, c in zip(BINS, counts)},
              "fitted_range": [round(float(pred.min()), 2), round(float(pred.max()), 2)]}
    return model, report


def observed_table(rows):
    """{pid: [switch, ...]}: each switch with the name, both arsenals and the
    stuff of both roles (current and potential), for exact-match lookups."""
    out = {}
    for r in rows:
        out.setdefault(r["pid"], []).append(
            {k: r[k] for k in ("name", "grades", "pot_grades", "sp_stu", "rp_stu", "sp_stu_p", "rp_stu_p")})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--league", required=True, choices=["TGS", "BLM"])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    rows = collect(a.league)
    print(f"{a.league}: {len(rows)} role switches ({len({r['pid'] for r in rows})} pitchers)")
    cur = lambda r: r["rp_stu"] - r["sp_stu"]
    pot = lambda r: (r["rp_stu_p"] - r["sp_stu_p"]) if r["rp_stu_p"] is not None and r["sp_stu_p"] is not None else None
    out = {"league": a.league, "date": datetime.date.today().isoformat(), "version": 2,
           "method": "least squares of the reliever-minus-starter stuff (display points) on the arsenal features "
                     "plus one offset per displayed listed-role stuff level; switches = consecutive live pulls, "
                     "role SP <-> RP/CL, pitch grades / HRR / PBABIP / CON unchanged; clipped 0-15. Priced as a "
                     "blend of the two whole notches around the expected gain (OOTP moves 0 or 5, never 2.5)",
           "sheet_rule": "flat 5 (-5 reliever priced as a starter, +5 starter priced as a reliever)",
           "models": {}, "report": {}, "observed": observed_table(rows)}
    for name, gk, sk, gain in (("sp_view", "grades", "sp_stu", cur), ("rp_view", "grades", "rp_stu", cur),
                               ("pot_sp_view", "pot_grades", "sp_stu_p", pot),
                               ("pot_rp_view", "pot_grades", "rp_stu_p", pot)):
        m, rep = fit_view(rows, gk, sk, gain)
        out["models"][name], out["report"][name] = m, rep
        print(f"  {name:12} n {rep['n']:5}  mean gain {rep['mean_gain']:.2f}  CV MSE {rep['cv_mse_model']:.3f} "
              f"(first form {rep['cv_mse_linear_stu_form']:.3f}, constant {rep['cv_mse_constant']:.3f})  "
              f"fitted {rep['fitted_range'][0]}..{rep['fitted_range'][1]}")
    path = os.path.join(HERE, "calib", a.league, "role_stuff.json")
    if a.write:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"wrote {os.path.relpath(path, os.path.dirname(os.path.dirname(HERE)))}")
    else:
        print("(dry run; add --write)")


if __name__ == "__main__":
    main()
