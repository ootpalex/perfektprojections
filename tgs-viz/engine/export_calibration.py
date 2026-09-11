"""
export_calibration.py — ship the fits' own accuracy tables to the app.

Every fitted layer already measures itself against the archive: for each rating
rung it records how often the outcome ACTUALLY happened in the sims (emp) next
to what the model says (fitted) and what the sheet's straight-line fit says.
Those tables only ever printed to a console that scrolls away. This writes them
to public/data/<LG>/calibration.json so the app can show them.

Nothing is computed here — it is a pure extract of:
    calib/<LG>/hitter_tails.json   blocks[*].report   (rung -> n, pa, emp, line, fitted)
    calib/<LG>/scurves.json        roles[*].blocks[*].buckets (rung -> n, bf, emp, sig, two)
                                   roles[*].live_k_by_stu     (live-season K% ladder)

    python tgs-viz/engine/export_calibration.py --league TGS [--write]
"""
import os, sys, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)

HIT_LABEL = {
    "SO":  ("Strikeouts",        "K rating",     "per PA (after HBP/BB)"),
    "HR":  ("Home runs",         "POWER",        "per PA (after HBP/BB)"),
    "HHR": ("Hits (not HR)",     "BABIP rating", "per ball in play"),
    "XBH": ("Extra-base hits",   "GAP",          "per hit (not HR)"),
    "T3B": ("Triples",           "SPEED",        "per extra-base hit"),
}
PIT_LABEL = {
    "SO":  ("Strikeouts",     "STUFF"),
    "uBB": ("Walks",          "CONTROL"),
    "HR":  ("Home runs",      "HR RATE"),
    "HHR": ("Hits (not HR)",  "pBABIP"),
}


def _load(p):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else "TGS"
    write = "--write" in sys.argv
    cal = os.path.join(HERE, "calib", league)
    out = {"league": league, "built_at": time.strftime("%Y-%m-%d %H:%M"),
           "hitters": [], "pitchers": [], "ladder": []}

    tails = _load(os.path.join(cal, "hitter_tails.json"))
    if tails:
        for blk, b in (tails.get("blocks") or {}).items():
            lab, rating, unit = HIT_LABEL.get(blk, (blk, b.get("x", "?"), ""))
            rows = []
            for rung, v in sorted((b.get("report") or {}).items(), key=lambda kv: float(kv[0])):
                rows.append({"r": float(rung), "n": v.get("n"), "w": v.get("pa"),
                             "emp": v.get("emp"), "model": v.get("fitted"),
                             "sheet": v.get("line")})
            if rows:
                out["hitters"].append({"block": blk, "label": lab, "rating": rating,
                                       "unit": unit, "rows": rows})

    sc = _load(os.path.join(cal, "scurves.json"))
    if sc:
        for role, rd in (sc.get("roles") or {}).items():
            for blk, b in (rd.get("blocks") or {}).items():
                lab, rating = PIT_LABEL.get(blk, (blk, b.get("x_vR", "?")))
                rows = []
                for rung, v in sorted((b.get("buckets") or {}).items(), key=lambda kv: float(kv[0])):
                    rows.append({"r": float(rung), "n": v.get("n"), "w": v.get("bf"),
                                 "emp": v.get("emp"), "model": v.get("sig"),
                                 "sheet": v.get("two")})
                if rows:
                    out["pitchers"].append({
                        "role": role, "block": blk, "label": lab, "rating": rating,
                        "unit": "per batter faced", "rows": rows,
                        "rmse_model": b.get("bucket_rmse_sigmoid"),
                        "rmse_sheet": b.get("bucket_rmse_twoline")})
            lad = rd.get("live_k_by_stu") or {}
            rows = [{"r": float(k), "n": v.get("n"), "emp": v.get("live"),
                     "model": v.get("proj_eng", v.get("proj"))}
                    for k, v in sorted(lad.items(), key=lambda kv: float(kv[0]))]
            if rows:
                out["ladder"].append({"role": role, "label": "Strikeouts, live season",
                                      "rating": "STUFF", "unit": "per batter faced",
                                      "rows": rows})

    nh, np_ = len(out["hitters"]), len(out["pitchers"])
    print(f"calibration {league}: {nh} hitter blocks, {np_} pitcher blocks, "
          f"{len(out['ladder'])} live ladders")
    if not (nh or np_):
        print("  nothing to export (no fitted layers yet)")
        return 0
    dst = os.path.join(VIZ, "public", "data", league, "calibration.json")
    if not write:
        print(f"  (dry run) would write {dst} — pass --write")
        return 0
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    json.dump(out, open(dst, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"  wrote public/data/{league}/calibration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
