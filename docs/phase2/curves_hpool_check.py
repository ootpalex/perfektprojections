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
Only the pitching blocks are checked (hitting has no logistic path in his engine, and the
two-line hitting fit needs the batter archive).
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
            curves = {"hp_two": f_two, "hp_logi": f_logi, "hp_pw": f_pw,
                      "hp_pw_rel": (lambda r, c=c_rel: PW.pw_value(c, r)),
                      "his_two": PW.twoline_pitch_fn(dp, role, blk, b["twoline_offset"]),
                      "his_sigmoid": PW.scurve_fn(b)}
            g = PW.live_gate_n(mrole, blk, xc, xl, curves)
            r = g["rmse"]
            row["seasons"][label] = {k: v_ for k, v_ in r.items()}
            print(f"{label:9}{role:>3} {blk:4} {bres['two']:8.2f} /{bres['logi']:7.2f} /{bres['pw']:7.2f}"
                  f"  | {r['hp_two']*1e3:7.2f} /{r['hp_logi']*1e3:7.2f} /{r['hp_pw']*1e3:7.2f} /{r['hp_pw_rel']*1e3:7.2f}   ||"
                  f" {r['his_two']*1e3:7.2f} /{r['his_sigmoid']*1e3:7.2f}")
        res.append(row)
    if a.json:
        json.dump(res, open(a.json, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
