"""
promote_scurves.py — gate-checked, zero-touch S-curve promotion (grind-loop step).

scurve_fit.py refits the preview every recalibrate; this ships it to the live
curves IF its own stored gates pass, else keeps the current curves and says so
loudly. Always exits 0 so an automation loop never dies here.

Gates (all per role/block, read from the preview itself):
  * monotone_ok            — more rating never moves the rate the wrong way
  * bucket RMSE            — the sigmoid must not be WORSE than the two-line
                             fit it replaces (tolerance 5% for tie-noise)

    python tgs-viz/engine/promote_scurves.py --league TGS
"""
import os
import sys
import json
import time
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else "TGS"
    cal = os.path.join(HERE, "calib", league)
    prev_p, live_p = os.path.join(cal, "scurves-preview.json"), os.path.join(cal, "scurves.json")
    if not os.path.exists(prev_p):
        print(f"[scurve-promote {league}] no preview - nothing to do")
        return 0
    prev = json.load(open(prev_p, encoding="utf-8"))

    fails = []
    for role, rd in (prev.get("roles") or {}).items():
        for blk, b in (rd.get("blocks") or {}).items():
            if b.get("monotone_ok") is not True:
                fails.append(f"{role}/{blk}: monotonicity")
            sig, two = b.get("bucket_rmse_sigmoid"), b.get("bucket_rmse_twoline")
            if sig is not None and two is not None and sig > two * 1.05:
                fails.append(f"{role}/{blk}: sigmoid RMSE {sig:.4f} worse than two-line {two:.4f}")

    if fails:
        print(f"[scurve-promote {league}] KEPT the current live curves - preview failed gates:")
        for f in fails:
            print(f"    !! {f}")
        print("    (projections keep the last good fit; nothing is broken. The next cycle refits.)")
        return 0

    if os.path.exists(live_p):
        shutil.copy2(live_p, live_p + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(prev_p, live_p)
    print(f"[scurve-promote {league}] gates passed - preview PROMOTED to live scurves.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
