"""
curves_hpool_check.py - Phase 2 row 5, supplementary: separate the FAMILY from the SUBSTRATE.

The bake-off in curve_bakeoff.py compares curves fit on different sim substrates (his: BLM clone
sims; ours: designed "H-pool" sims). A loss for ours could be the family (continuous multi-knot
line) or the substrate (designed rosters). Our H-pool bins are on this machine (they are ours, not
his archives), so his two FAMILIES can be fit to OUR substrate with his own code (scurve_fit
fit_logistic, calibrate.wls) and scored on the same real seasons with the same gate:

    H-pool two-line   his family, our substrate
    H-pool logistic   his family, our substrate (bare logistic: no live drift, no elite hinge)
    H-pool piecewise  our family, our substrate (the wired knots, pw_curves.py)

If the two H-pool curves lose to his BLM-fit curves as badly as the piecewise does, the substrate
is the cause; if they score like his, the family is.

This is analysis, not engine: nothing it computes is read by the pipeline. Run from the repo root:

    python docs/phase2/curves_hpool_check.py \
        --bins <ootp27-conversion>/test-league-design/outputs/viz/hpool_hitpit_bins.json \
        --ssb-dir <ootp-dashboard>/leagues/SSB/metadata/2043 [--json out.json]

Bins: fitbins rows are [internal rating, display rating, rate, weight]; the display column is used.
Pitching: his two families on our bins, and our family on his bucket means. Hitting: only our family
on his bucket means (hitter_tails.json `report`, 5 of 6 blocks); his engine has no hitting S-curve.
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "tgs-viz", "engine")
sys.path.insert(0, ENGINE)
import calibrate as C  # noqa: E402
import curve_bakeoff as CB  # noqa: E402  (_CALIB_AVG: the pool averages the wired knots are offsets from)
import pw_curves as PW  # noqa: E402
import scurve_fit as SF  # noqa: E402
import pitchers as P  # noqa: E402
import hitters as H  # noqa: E402

KEY = {("SP", "SO"): "PIT[SP] Stuff→K%", ("SP", "uBB"): "PIT[SP] Control→uBB%",
       ("SP", "HR"): "PIT[SP] Move→HR%", ("SP", "HHR"): "PIT[SP] pbabip→BABIP",
       ("RP", "SO"): "PIT[RP] Stuff→K%", ("RP", "uBB"): "PIT[RP] Control→uBB%",
       ("RP", "HR"): "PIT[RP] Move→HR%", ("RP", "HHR"): "PIT[RP] pbabip→BABIP"}


def fit_two_line(pts, xbar, gt):
    """His two-segment WLS (calibrate.wls on rating-xbar, rate-gt), seam at 50, intercepts free."""
    out = {}
    for name, filt in (("hi", lambda x: x >= 50), ("lo", lambda x: x < 50)):
        dev = [(r - xbar, y - gt, w) for r, y, w in pts if filt(r)]
        out[name] = C.wls(dev)
    return lambda r: gt + (out["hi"][0] + out["hi"][1] * (r - xbar) if r >= 50
                           else out["lo"][0] + out["lo"][1] * (r - xbar))


def fit_pw_on_buckets(buckets, abs_knots):
    """Our family on HIS substrate, approximately: the wired knots (absolute display) with the slopes
    refit by weighted least squares in the ReLU basis on the 5-point archive bucket means that
    scurves-preview.json carries (rung -> {bf, emp}; up to 13 points per block). NOT the archive pool
    fit (that needs calib/BLM/{Batting,Pitching,Pitchers}.csv): 13 bucket means identify a 3-5 slope curve
    only loosely. Returns (curve, slopes)."""
    import numpy as np
    xs = np.array([float(r) for r in buckets])
    ys = np.array([b["emp"] for b in buckets.values()])
    ws = np.array([b["bf"] for b in buckets.values()])
    X = np.column_stack([np.ones_like(xs), xs] + [np.maximum(xs - k, 0.0) for k in abs_knots])
    sw = np.sqrt(ws)
    beta = np.linalg.lstsq(X * sw[:, None], ys * sw, rcond=None)[0]
    slopes = [beta[1]]
    for d in beta[2:]:
        slopes.append(slopes[-1] + d)
    c = PW.pw_params(dict(knots=tuple(abs_knots), slopes=tuple(slopes), relative=False), 50.0, 0.0)
    return (lambda r, c=c: PW.pw_value(c, r)), slopes


def bin_rmse(pts, f):
    sw = sum(w for _, _, w in pts)
    return (sum(w * (y - f(r)) ** 2 for r, y, w in pts) / sw) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bins", required=True)
    ap.add_argument("--ssb-dir", required=True)
    ap.add_argument("--json")
    a = ap.parse_args()
    bins = json.load(open(a.bins, encoding="utf-8"))

    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        blm = SF.read_metadata("BLM")
    ssb = PW.read_pitching_flat(a.ssb_dir)
    prev = json.load(open(os.path.join(ENGINE, "calib", "BLM", "scurves-preview.json"), encoding="utf-8"))
    dp = P.scan_consts(os.path.join(REPO, "The Sheets BLM", "The Sheet Pitchers.xlsx"))[0]

    res = []
    print(f"{'season':9}{'role':>3} {'blk':4} {'bins RMSE (x1e-3): two / logi / pw':>40} | "
          f"{'real-season gate RMSE (x1e-3): hpool two / logi / pw(abs) / pw(as wired) || his BLM two / sigmoid':>100}")
    for (role, blk), key in KEY.items():
        v = bins[key]
        pts = [(b[1], b[2], b[3]) for b in v["fitbins"]]
        xbar = v["leagueAvg"]["display"]
        gt = sum(y * w for _, y, w in pts) / sum(w for _, _, w in pts)
        direction = SF.BLOCKS[blk][2]
        f_two = fit_two_line(pts, xbar, gt)
        lg = SF.fit_logistic(pts, direction, SF.bucket_table(pts))
        f_logi = lambda r, g=lg: SF.logistic(min(max(r, 20.0), 80.0), g["A"], g["B"], g["k"], g["m"])
        spec = PW.PIT_PW[role][blk]
        # the wired knots at their CALIBRATION positions (absolute display values, as fit on the sims)
        c_pw = PW.pw_params(spec, CB._CALIB_AVG[(role, blk)], 0.0)
        f_pw = lambda r, c=c_pw: PW.pw_value(c, r)
        # bins are fit-frame points: compare shapes after removing each curve's level on the bins
        bres = {n: bin_rmse(pts, (lambda r, f=f, m=sum(w * (f(r) - y) for r, y, w in pts) / sum(w for _, _, w in pts):
                                  f(r) - m)) * 1e3 for n, f in (("two", f_two), ("logi", f_logi), ("pw", f_pw))}
        xc, xl, _ = SF.BLOCKS[blk]
        b = prev["roles"][role]["blocks"][blk]
        row = {"role": role, "block": blk, "bins_rmse_x1e3": bres, "seasons": {}}
        for label, mrole in (("BLM-2058", blm[role]), ("SSB-2043", ssb[role])):
            c_rel = PW.build_pw(mrole, spec, xc, xl, mrole["rates"][blk])    # as wired: knots slide with the live average
            f_pwh, slopes_h = fit_pw_on_buckets(b["buckets"], [k + CB._CALIB_AVG[(role, blk)] for k in spec["knots"]]
                                                if spec["relative"] else list(spec["knots"]))
            curves = {"hp_two": f_two, "hp_logi": f_logi, "hp_pw": f_pw, "pw_his_buckets": f_pwh,
                      "hp_pw_rel": (lambda r, c=c_rel: PW.pw_value(c, r)),
                      "his_two": PW.twoline_pitch_fn(dp, role, blk, b["twoline_offset"]),
                      "his_sigmoid": PW.scurve_fn(b)}
            g = PW.live_gate_n(mrole, blk, xc, xl, curves)
            r = g["rmse"]
            row["seasons"][label] = {k: v_ for k, v_ in r.items()}
            row["pw_his_bucket_slopes"] = [float(x) for x in slopes_h]
            print(f"{label:9}{role:>3} {blk:4} {bres['two']:8.2f} /{bres['logi']:7.2f} /{bres['pw']:7.2f}"
                  f"  | {r['hp_two']*1e3:7.2f} /{r['hp_logi']*1e3:7.2f} /{r['hp_pw']*1e3:7.2f} /{r['hp_pw_rel']*1e3:7.2f}   ||"
                  f" {r['his_two']*1e3:7.2f} /{r['his_sigmoid']*1e3:7.2f}  ||  pw on his buckets {r['pw_his_buckets']*1e3:7.2f}")
        res.append(row)

    # ---- hitting: our family refit on HIS archive bucket means (hitter_tails.json `report`), 5 of 6 blocks
    # (the Eye -> uBB block has no tails entry). Same approximation as above: 13 rung means, slopes only.
    tails = json.load(open(os.path.join(ENGINE, "calib", "BLM", "hitter_tails.json"), encoding="utf-8"))
    dpH = H.scan_consts(os.path.join(REPO, "The Sheets BLM", "The Sheet Hitters.xlsx"))[0]
    hit_sets = (("BLM-2058", PW.read_hitting_blm(os.path.join(ENGINE, "calib", "BLM", "metadata_inputs"))),
                ("SSB-2043", PW.read_hitting_flat(a.ssb_dir)))
    hres = []
    print("\nHITTING: gate RMSE (x1e-3): his two-line + tails || our piecewise as wired | our piecewise, slopes refit on his bucket means")
    for blk, tb in tails["blocks"].items():
        spec, xc, xl = PW.HIT_PW[blk]
        buckets = {r: {"emp": v["emp"], "bf": v["pa"]} for r, v in tb["report"].items() if v["pa"] > 0}
        absk = [k + CB._CALIB_AVG[blk] for k in spec["knots"]] if spec["relative"] else list(spec["knots"])
        f_pwh, slopes_h = fit_pw_on_buckets(buckets, absk)
        for label, mh in hit_sets:
            c_rel = PW.build_pw(mh, spec, xc, xl, mh["rates"][blk])
            curves = {"his_two_tails": PW.twoline_hit_fn(dpH, blk, tails), "pw_wired": (lambda r, c=c_rel: PW.pw_value(c, r)),
                      "pw_his_buckets": f_pwh}
            g = PW.live_gate_n(mh, blk, xc, xl, curves, rate_fn=PW.hit_rate)
            r = g["rmse"]
            hres.append({"season": label, "block": blk, "rmse": r, "slopes_his_buckets": [float(x) for x in slopes_h]})
            print(f"{label:9} {blk:4} {r['his_two_tails']*1e3:6.2f} || {r['pw_wired']*1e3:6.2f} | {r['pw_his_buckets']*1e3:6.2f}")
    res = {"pitching": res, "hitting": hres}
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
