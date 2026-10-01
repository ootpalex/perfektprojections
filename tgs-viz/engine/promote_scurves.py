"""
promote_scurves.py — gate-checked, zero-touch S-curve promotion (grind-loop step).

scurve_fit.py refits the preview every recalibrate; this writes the live
calib/<LG>/scurves.json from it and, for the leagues in PER_BLOCK_LEAGUES
(BLM), chooses the curve PER BLOCK (role x SO/uBB/HR/HHR). Other leagues (TGS)
keep the earlier all-or-nothing rule (legacy_promote). Always exits 0 so an
automation loop never dies here.

Rule per block, on the REAL season (the preview's live_gate: every pitcher
in the role's Data tab, both curves level-matched, bucket RMSE vs his actual
season rate):
  * S-curve when it is monotone AND its live RMSE beats the two-line's by
    more than 5%;
  * else the two-segment line, with the preview's twoline_offset so its
    league level matches the live season.

scurves.json keeps both role keys. "blocks" holds only the S-curve blocks
(pitchers.compute runs the two-segment line for a block missing there),
"twoline_offsets" holds the level offset of every block, "curve" names the
choice. A preview made before the live gate existed (no live_gate) leaves
the current scurves.json as it is.

    python tgs-viz/engine/promote_scurves.py --league TGS
    python tgs-viz/engine/promote_scurves.py --league BLM --calib-dir <copy of calib/BLM>
"""
import os
import sys
import copy
import json
import time
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCKS = ("SO", "uBB", "HR", "HHR")
MARGIN = 0.05   # the S-curve must beat the two-line's live RMSE by more than this
# Leagues that use the per-block rule (user, 2026-10-01, for BLM). Any other
# league keeps the all-or-nothing archive-frame rule it had (legacy_promote)
# until the user decides otherwise: TGS and BLM are separate leagues.
PER_BLOCK_LEAGUES = {"BLM"}


def legacy_promote(league, prev, prev_p, live_p):
    """The earlier rule: promote the whole preview when every block is monotone
    and its archive bucket RMSE is not more than 5% worse than the two-line's,
    else keep the current live curves."""
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


def choose(b):
    """('S-curve' | 'two-line', reason) for one preview block."""
    if b.get("monotone_ok") is not True:
        return "two-line", "S-curve not monotone"
    g = b.get("live_gate")
    if not g:
        return "two-line", "no live-season points"
    s, t = g["rmse_sigmoid"], g["rmse_twoline"]
    gain = 1.0 - s / t if t > 0 else 0.0
    if s < (1.0 - MARGIN) * t:
        return "S-curve", f"live RMSE {s:.5f} vs two-line {t:.5f} (S-curve {gain:+.1%})"
    return "two-line", (f"live RMSE {s:.5f} vs two-line {t:.5f} (S-curve {gain:+.1%}, "
                        f"needs more than {MARGIN:.0%})")


def main():
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else "TGS"
    cal = (sys.argv[sys.argv.index("--calib-dir") + 1] if "--calib-dir" in sys.argv
           else os.path.join(HERE, "calib", league))
    prev_p, live_p = os.path.join(cal, "scurves-preview.json"), os.path.join(cal, "scurves.json")
    if not os.path.exists(prev_p):
        print(f"[scurve-promote {league}] no preview - nothing to do")
        return 0
    prev = json.load(open(prev_p, encoding="utf-8"))
    if league not in PER_BLOCK_LEAGUES:
        return legacy_promote(league, prev, prev_p, live_p)
    roles = prev.get("roles") or {}
    old = [f"{role}/{blk}" for role in ("SP", "RP")
           for blk, b in ((roles.get(role) or {}).get("blocks") or {}).items()
           if "live_gate" not in b or "twoline_offset" not in b]
    if old or any(role not in roles for role in ("SP", "RP")):
        print(f"[scurve-promote {league}] KEPT the current live curves - the preview has no "
              f"live-season gate (an older scurve_fit.py made it). Rerun scurve_fit.py --league {league}.")
        return 0

    live = copy.deepcopy(prev)
    picked = []
    print(f"[scurve-promote {league}] per-block choice on the live season "
          f"({prev.get('live_source', 'source not recorded')}):")
    for role in ("SP", "RP"):
        rd = live["roles"][role]
        blocks = rd.get("blocks") or {}
        rd["twoline_offsets"] = {blk: b["twoline_offset"] for blk, b in blocks.items()}
        rd["curve"] = {}
        keep = {}
        for blk in BLOCKS:
            b = blocks.get(blk)
            if b is None:
                continue
            curve, why = choose(b)
            rd["curve"][blk] = curve
            if curve == "S-curve":
                keep[blk] = b
                picked.append(f"{role} {blk}")
            print(f"    {role} {blk:4} -> {curve:8}  {why}")
        rd["blocks"] = keep
        if "SO" not in keep:
            # the live K%-by-STU ladder plots the S-curve's SO block, which is not live here
            rd.pop("live_k_by_stu", None)
            rd.pop("k_gap_45_50", None)
    live["promoted_at"] = time.strftime("%Y-%m-%d %H:%M")
    live["gate"] = (f"per block on the live season: level-matched bucket RMSE, "
                    f"S-curve only when more than {MARGIN:.0%} better")

    if os.path.exists(live_p):
        shutil.copy2(live_p, live_p + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(live_p, "w", encoding="utf-8") as fh:
        json.dump(live, fh, indent=1)
    print(f"[scurve-promote {league}] wrote scurves.json: S-curve for "
          f"{', '.join(picked) or 'no block'}; two-line (level-matched) for the rest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
