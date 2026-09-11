"""
parks.py — league park-factor CSV -> calib/<LG>/park_blend.json

The park spec (final, 2026-08-14):
  DEFAULT  all parks equal. Every player is projected into the league-average
           park — no one gets credit or blame for where they happen to play.
           Contracts and cross-team comparisons read this state.
  MY PARK  one button push: 50% the user's home park + 50% the average of the
           OTHER MLB parks (the home team plays half its games at home and the
           other half spread across the rest of the league). Per outcome
           (hits / doubles / triples / HR) and per batter handedness.
           NPB parks are excluded everywhere — Japan is a different finance and
           park environment and never enters an MLB comparison.

This module only produces the FACTORS. Converting a multiplicative factor into
the sheet's additive rate-delta units needs the league baseline rates, which
live in the workbook the engine already scans — so that conversion happens in
the engine layer, not here.

    python ingest/parks.py            # both leagues, report
    python ingest/parks.py --write    # write calib/<LG>/park_blend.json

Source CSVs are checked into calib/<LG>/park_factors.csv (copied from the
StatsPlus "Ballparks" export). Re-export + re-copy + re-run when parks change.
"""
import os
import sys
import csv
import json
from statistics import mean

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)

# NPB clubs in the TGS file — excluded from both the road average and the count.
NPB = {"Fukuoka Vipers", "Hiroshima Phoenix", "Kansai Cubs", "Kyoto Aces",
       "Nagoya Dolphins", "Osaka Bulls", "Saitama Panthers", "Sapporo Bruisers",
       "Sendai Woodpeckers", "Tokyo Golden Kites", "Tokyo Jaguars", "Yokohama Astrals"}

LEAGUES = {
    "TGS": {"home": "Chicago Cubs", "exclude": NPB},
    "BLM": {"home": "Tampa Bay Rays", "exclude": set()},
}

# CSV column -> output key. Handedness is the BATTER's side.
COLS = {
    "Avg RHB": "avg_rhb", "Avg LHB": "avg_lhb", "Average": "avg",
    "Doubles": "doubles", "Triples": "triples",
    "HR RHB": "hr_rhb", "HR LHB": "hr_lhb", "Home Runs": "hr",
}


def build(league, write=False):
    cfg = LEAGUES[league]
    src = os.path.join(VIZ, "engine", "calib", league, "park_factors.csv")
    with open(src, encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if (r.get("Team") or "").strip()]
    mlb = [r for r in rows if r["Team"].strip() not in cfg["exclude"]]
    home = [r for r in mlb if r["Team"].strip() == cfg["home"]]
    if len(home) != 1:
        raise SystemExit(f"{league}: expected exactly one '{cfg['home']}' row in "
                         f"{os.path.basename(src)}, found {len(home)} "
                         f"(teams: {sorted(r['Team'] for r in mlb)[:5]}...)")
    home = home[0]
    road = [r for r in mlb if r["Team"].strip() != cfg["home"]]

    blend = {}
    for col, key in COLS.items():
        h = float(home[col])
        r = mean(float(x[col]) for x in road)
        blend[key] = round(0.5 * h + 0.5 * r, 6)

    out = {
        "league": league,
        "home_team": cfg["home"],
        "n_parks": len(mlb),
        "n_road": len(road),
        "n_excluded": len(rows) - len(mlb),
        # MY PARK state: 50% home + 50% mean(other MLB parks), per outcome/hand.
        "blend": blend,
        # DEFAULT state is all parks equal: factor 1.0 everywhere, by definition.
        # It is not listed because it is not data — the engine hard-codes it.
    }
    print(f"{league}: home={cfg['home']}  parks={len(mlb)} MLB "
          f"({out['n_excluded']} excluded)  road avg over {len(road)}")
    for key in COLS.values():
        print(f"    {key:<9} {blend[key]:.4f}")
    dst = os.path.join(VIZ, "engine", "calib", league, "park_blend.json")
    if write:
        with open(dst, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"  wrote {os.path.relpath(dst, VIZ)}")
    else:
        print(f"  (dry run) would write {os.path.relpath(dst, VIZ)} — pass --write")
    return out


if __name__ == "__main__":
    write = "--write" in sys.argv
    picked = [a for a in sys.argv[1:] if a in LEAGUES] or list(LEAGUES)
    for lg in picked:
        build(lg, write=write)
