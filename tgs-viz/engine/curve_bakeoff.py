"""
curve_bakeoff.py - Phase 2 row 5: score his two-line, his S-curve and our piecewise on a real
season, per block, with FIXED (not refit) curves. A report: it writes nothing unless --json is
given, and nothing it writes is read by the engine.

What it needs, and has on disk:
  * his fitted S-curves   calib/BLM/scurves-preview.json   (all eight pitching blocks)
  * his two-line          The Sheets BLM/The Sheet {Pitchers,Hitters}.xlsx  (+ hitter_tails.json)
  * our piecewise         pw_curves.py (literals from ootp-dashboard data_points.py)
  * real season           calib/BLM/metadata_inputs (BLM 2058)
                          ootp-dashboard leagues/SSB/metadata/2043 (--ssb-dir)

Metric (the gate's): live_gate bucket RMSE - every player of the role, each curve at his raw vR and
vL rating share-blended, each curve's own weighted mean miss removed, 5-point vR buckets inside
[20, 80], weighted by the rate's denominator. Reported with:
  n      players scored          W      summed denominator (BF for pitchers, PA for hitters)
  floor  binomial sampling noise of the bucket means (a rough lower bound)
  CI     95% player-bootstrap interval (resample players, redo level-matching and buckets)

    python tgs-viz/engine/curve_bakeoff.py --league BLM [--ssb-dir <metadata/2043>] [--boot 2000]
                                           [--json out.json]
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import pw_curves as PW  # noqa: E402
import scurve_fit as SF  # noqa: E402
import pitchers as P  # noqa: E402
import hitters as H  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
MARGIN = 0.05
HIT_RATING = {b: (PW.HIT_PW[b][1], PW.HIT_PW[b][2]) for b in PW.HIT_BLOCKS}


# ---------------------------------------------------------------- bootstrap on the gate
def _arrays(pts, names):
    rv = np.array([p[0] for p in pts])
    y = np.array([p[1] for p in pts])
    w = np.array([p[2] for p in pts])
    pr = np.array([[p[3][n] for n in names] for p in pts])
    rung = np.round(rv / 5.0) * 5.0
    keep = (rung >= SF.SUPPORT[0]) & (rung <= SF.SUPPORT[1])
    return rv, y, w, pr, ((rung - 20.0) / 5.0).astype(int), keep


def _rmse(y, w, pr, bucket, keep, nb):
    """live_gate arithmetic on arrays: per-curve RMSE (rows of pr are players, columns curves)."""
    bias = (w[:, None] * (pr - y[:, None])).sum(0) / w.sum()
    wk = w * keep
    bw = np.bincount(bucket, weights=wk, minlength=nb)
    by = np.bincount(bucket, weights=wk * y, minlength=nb)
    ok = bw > 0
    out = []
    for j in range(pr.shape[1]):
        bp = np.bincount(bucket, weights=wk * (pr[:, j] - bias[j]), minlength=nb)
        out.append(math.sqrt((bw[ok] * (by[ok] / bw[ok] - bp[ok] / bw[ok]) ** 2).sum() / bw[ok].sum()))
    return np.array(out)


def bootstrap(pts, names, nboot, seed=20261003):
    """Player-bootstrap of the gate. Returns (point RMSEs, draws array nboot x ncurves)."""
    rv, y, w, pr, bucket, keep = _arrays(pts, names)
    nb = 13
    point = _rmse(y, w, pr, bucket, keep, nb)
    rng = np.random.default_rng(seed)
    n = len(y)
    draws = np.empty((nboot, len(names)))
    for i in range(nboot):
        idx = rng.integers(0, n, n)
        draws[i] = _rmse(y[idx], w[idx], pr[idx], bucket[idx], keep[idx], nb)
    return point, draws


def ci(x):
    return float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))


# ---------------------------------------------------------------- curve sets
def _abs_variant(spec, calib_avg_shift_anchor):
    """DIAGNOSTIC: the same knots placed at their CALIBRATION positions (not slid with the league
    average). `calib_avg_shift_anchor` = the calibration average the offsets were taken from."""
    s = dict(spec)
    s["knots"] = tuple(k + calib_avg_shift_anchor for k in spec["knots"])
    s["relative"] = False
    return s


_CALIB_AVG = {("SP", "SO"): 56.605, ("SP", "uBB"): 57.313, ("SP", "HR"): 54.157, ("SP", "HHR"): 52.629,
              ("RP", "SO"): 57.217, ("RP", "uBB"): 56.308, ("RP", "HR"): 53.866, ("RP", "HHR"): 52.064,
              "uBB": 56.038, "HR": 57.686, "SO": 56.316, "HHR": 57.407, "XBH": 57.508}


def pitching_cells(meta, prev, dp, label):
    cells = []
    for role in ("SP", "RP"):
        m = meta[role]
        for blk, (xc, xl, d) in SF.BLOCKS.items():
            b = prev["roles"][role]["blocks"][blk]
            spec = PW.PIT_PW[role][blk]
            c = PW.build_pw(m, spec, xc, xl, m["rates"][blk])
            f_pw = lambda r, c=c: PW.pw_value(c, r)
            ca = _CALIB_AVG[(role, blk)]
            c_abs = PW.build_pw(m, _abs_variant(spec, ca), xc, xl, m["rates"][blk], anchor=c["anchor"])
            f_abs = lambda r, c=c_abs: PW.pw_value(c, r)
            lpts = SF.live_points(m, blk, xc, xl)
            f_drift, a, cc = PW.with_drift(f_pw, lpts)
            curves = {"sigmoid": PW.scurve_fn(b),
                      "twoline": PW.twoline_pitch_fn(dp, role, blk, b["twoline_offset"]),
                      "piecewise": f_pw, "pw_abs": f_abs, "pw_drift": f_drift}
            cells.append(dict(season=label, kind="pitching", role=role, block=blk, mrole=m, xc=xc, xl=xl,
                              rate_fn=PW.pit_rate, curves=curves, anchor=c["anchor"],
                              drift=(a, cc), monotone=PW.monotone_scan(f_pw, d)[0]))
    return cells


def hitting_cells(mh, dpH, tails, label):
    cells = []
    for blk in PW.HIT_BLOCKS:
        spec, xc, xl = PW.HIT_PW[blk]
        c = PW.build_pw(mh, spec, xc, xl, mh["rates"][blk])
        f_pw = lambda r, c=c: PW.pw_value(c, r)
        c_abs = PW.build_pw(mh, _abs_variant(spec, _CALIB_AVG[blk]) if spec["relative"] else spec,
                            xc, xl, mh["rates"][blk], anchor=c["anchor"])
        f_abs = lambda r, c=c_abs: PW.pw_value(c, r)
        pts = _hit_live_points(mh, blk, xc, xl)
        f_drift, a, cc = PW.with_drift(f_pw, pts)
        curves = {"twoline": PW.twoline_hit_fn(dpH, blk, None),
                  "twoline_tails": PW.twoline_hit_fn(dpH, blk, tails),
                  "piecewise": f_pw, "pw_abs": f_abs, "pw_drift": f_drift}
        cells.append(dict(season=label, kind="hitting", role="BAT", block=blk, mrole=mh, xc=xc, xl=xl,
                          rate_fn=PW.hit_rate, curves=curves, anchor=c["anchor"], drift=(a, cc),
                          monotone=None))
    return cells


def _hit_live_points(mh, blk, xc, xl):
    """scurve_fit.live_points for hitters (blended rating, rate, weight) - the drift fit's input."""
    s = mh["share"]
    rv = {x["ID"]: x.get(xc) for x in mh["vr"]}
    rl = {x["ID"]: x.get(xl) for x in mh["vl"]}
    pts = []
    for pid, st in mh["per_id"].items():
        a, b = rv.get(pid), rl.get(pid)
        if a is None and b is None:
            continue
        r = (s * a + (1 - s) * b) if (a is not None and b is not None) else (a if a is not None else b)
        y, den = PW.hit_rate(st, blk)
        if den > 0:
            pts.append((float(r), y, den))
    return pts


def score(cell, nboot):
    names = list(cell["curves"])
    pts = PW.gate_points(cell["mrole"], cell["block"], cell["xc"], cell["xl"], cell["rate_fn"], cell["curves"])
    g = PW.gate_from_points(pts, names)
    point, draws = bootstrap(pts, names, nboot) if nboot else (np.array([g["rmse"][n] for n in names]), None)
    # the arrays path must equal the gate path (guards the bootstrap code)
    assert max(abs(point[i] - g["rmse"][n]) for i, n in enumerate(names)) < 1e-12
    res = {"n": g["n"], "W": g["w"], "floor": PW.noise_floor(g), "rmse": {n: g["rmse"][n] for n in names},
           "buckets": g["buckets"]}
    if draws is not None:
        res["rmse_ci"] = {n: ci(draws[:, i]) for i, n in enumerate(names)}
        res["ratio_ci"] = {}
        for a in names:
            for b in names:
                if a < b:
                    ia, ib = names.index(a), names.index(b)
                    gain = 1.0 - draws[:, ia] / draws[:, ib]     # a better than b by `gain`
                    res["ratio_ci"][f"{a}_vs_{b}"] = {
                        "gain": 1.0 - g["rmse"][a] / g["rmse"][b], "ci": ci(gain),
                        "p_gain_gt_margin": float((gain > MARGIN).mean()),
                        "p_gain_gt_0": float((gain > 0).mean())}
    return res


def winner(res, order):
    """Gate rule over `order` (first = incumbent): a challenger replaces the incumbent only when its
    RMSE is more than MARGIN below it; among qualifiers the lowest RMSE wins."""
    inc = order[0]
    q = [n for n in order[1:] if res["rmse"][n] < (1 - MARGIN) * res["rmse"][inc]]
    return min(q, key=lambda n: res["rmse"][n]) if q else inc


def fmt(cells_res, family_order, extra):
    lines = []
    for cell, res in cells_res:
        names = list(cell["curves"])
        r = res["rmse"]
        lines.append(f"{cell['season']:9} {cell['role']:3} {cell['block']:4} n={res['n']:4d} W={res['W']:8.0f} "
                     f"floor={res['floor']:.5f} " + " ".join(f"{n}={r[n]:.5f}" for n in names)
                     + f"  -> {winner(res, family_order)}")
    return "\n".join(lines)


def pw_preview(prev, meta, dp):
    """A copy of the committed scurves-preview.json with the piecewise block added to every pitching
    block - what `scurve_fit.py --pw` would write, rebuilt from the committed S-curve params and the
    on-disk live season (no archives needed)."""
    out = json.loads(json.dumps(prev))
    for role in ("SP", "RP"):
        for blk, (xc, xl, d) in SF.BLOCKS.items():
            b = out["roles"][role]["blocks"][blk]
            b["piecewise"] = PW.preview_block(
                meta[role], role, blk, xc, xl, PW.scurve_fn(b),
                PW.twoline_pitch_fn(dp, role, blk, b["twoline_offset"]), b["live_gate"])
    out["pw_note"] = ("piecewise blocks added by curve_bakeoff.py --write-preview from the committed "
                      "S-curve params and the metadata_inputs season; NOT read by the engine")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="BLM", choices=["BLM"])
    ap.add_argument("--ssb-dir", help="ootp-dashboard leagues/SSB/metadata/2043 (flat CSV layout)")
    ap.add_argument("--boot", type=int, default=0, help="bootstrap draws (0 = point estimates only)")
    ap.add_argument("--json", help="write the full results here")
    ap.add_argument("--write-preview", help="write the committed preview + piecewise blocks here "
                                            "(a NEW file; promote_scurves.py --three-way can read a copy)")
    a = ap.parse_args()
    lg = a.league
    calib = os.path.join(HERE, "calib", lg)
    prev = json.load(open(os.path.join(calib, "scurves-preview.json"), encoding="utf-8"))
    dp = P.scan_consts(os.path.join(REPO, f"The Sheets {lg}", "The Sheet Pitchers.xlsx"))[0]
    dpH = H.scan_consts(os.path.join(REPO, f"The Sheets {lg}", "The Sheet Hitters.xlsx"))[0]
    tails = json.load(open(os.path.join(calib, "hitter_tails.json"), encoding="utf-8"))

    sets = []
    d = os.path.join(calib, "metadata_inputs")
    man = json.load(open(os.path.join(d, "manifest.json"), encoding="utf-8"))
    sets.append((f"{lg}-{man['season']}", SF.read_metadata(lg), PW.read_hitting_blm(d)))
    if a.ssb_dir:
        sets.append(("SSB-2043", PW.read_pitching_flat(a.ssb_dir), PW.read_hitting_flat(a.ssb_dir)))

    if a.write_preview:
        with open(a.write_preview, "w", encoding="utf-8") as fh:
            json.dump(pw_preview(prev, sets[0][1], dp), fh, indent=1)
        print(f"wrote {a.write_preview}")
    out = {"margin": MARGIN, "cells": []}
    for label, mp, mh in sets:
        cells = pitching_cells(mp, prev, dp, label) + hitting_cells(mh, dpH, tails, label)
        scored = [(c, score(c, a.boot)) for c in cells]
        pit = [(c, r) for c, r in scored if c["kind"] == "pitching"]
        hit = [(c, r) for c, r in scored if c["kind"] == "hitting"]
        print(f"\n== {label} pitching (incumbent = two-line) ==")
        print(fmt(pit, ["twoline", "sigmoid", "piecewise"], None))
        print(f"\n== {label} hitting (incumbent = two-line + tails) ==")
        print(fmt(hit, ["twoline_tails", "piecewise"], None))
        for c, r in scored:
            out["cells"].append({"season": c["season"], "kind": c["kind"], "role": c["role"], "block": c["block"],
                                 "anchor": c["anchor"], "drift_a_c": c["drift"], **r})
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
