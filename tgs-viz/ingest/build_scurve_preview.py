"""
build_scurve_preview.py — D1 rebuild PREVIEW build. Runs the full pitcher
projection from the cached StatsPlus pull through the OPT-IN fitted-logistic
path (calib/<LG>/scurves-preview.json) and writes a NEW side file:

    public/data/<LG>/pitchers_scurve_preview.json

NOTHING live is touched: pitchers.json, the workbooks, constants-latest.json
and the cached pull are all read-only here. The live pipeline (refresh.py)
keeps producing today's two-segment numbers until the user approves the switch.

  python tgs-viz/ingest/build_scurve_preview.py --league TGS
  python tgs-viz/ingest/build_scurve_preview.py --league BLM
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
import ratings as R    # noqa: E402
import statsplus as S  # noqa: E402
import pitchers as P   # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tgs-viz", "tools"))
import settings as ST  # noqa: E402

# fields joined onto the live records by refresh.py that the engine run lacks
# (ORG names need network; contracts need the public endpoints) — carried over
# from the CURRENT live pitchers.json by ID so the preview is app-comparable.
CARRY = ["ORG", "Lev", "Price", "SalarySchedule", "ContractYrs", "ContractYr",
         "NoTrade", "IsMajorDeal", "OnDL", "OnDL60", "DLDays", "MLBSvcYrs"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True, choices=["TGS", "BLM"])
    a = ap.parse_args()
    lg = a.league
    slug = ST.slug(lg)
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", lg)
    out_path = os.path.join(out_dir, "pitchers_scurve_preview.json")

    scurve_path = os.path.join(REPO, "tgs-viz", "engine", "calib", lg, "scurves-preview.json")
    scurves = P.load_scurves(scurve_path)
    print(f"scurves: {scurve_path}")

    raw_path = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
    rows = json.load(open(raw_path, encoding="utf-8"))
    print(f"cached pull: {len(rows)} rows ({raw_path})")
    rows = S.drop_foreign(rows, league=lg)
    trows = S.translate_rows(rows)

    def is_pit(r):
        return str(r.get("POS", "")).upper() in ("SP", "RP", "CL")

    precs = R.run_pitchers([r for r in trows if is_pit(r)], lg, scurves=scurves)
    print(f"engine (S-CURVE path): {len(precs)} pitchers computed")

    # carry over the join-only fields from the live JSON (read-only)
    live_path = os.path.join(out_dir, "pitchers.json")
    live = {str(x.get("ID")): x for x in json.load(open(live_path, encoding="utf-8"))}
    carried = 0
    for r in precs:
        j = live.get(str(r.get("ID")))
        if not j:
            continue
        for k in CARRY:
            if k in j and (r.get(k) in (None, "") or k in ("ORG", "Lev")):
                r[k] = j[k]
        carried += 1
    print(f"carried ORG/Lev/contract/injury fields for {carried} pitchers from live JSON")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(precs, f, ensure_ascii=False)
    print(f"wrote {out_path}  (preview side file — live pitchers.json untouched)")


if __name__ == "__main__":
    main()
