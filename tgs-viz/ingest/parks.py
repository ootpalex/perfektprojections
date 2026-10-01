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

REPO = os.path.dirname(VIZ)
sys.path.insert(0, os.path.join(VIZ, "tools"))
import settings as ST  # noqa: E402


def _home(lg):
    """The league's home club for My Park (settings leagues.<LG>.my_team)."""
    return (ST.league(lg) or {}).get("my_team")


LEAGUES = {
    # "workbook": the league's park sheet the user keeps (gitignored folder). Sheet
    # "Current": cols A-B = Team / MLB Park (assignments; blank rows = folded clubs),
    # col D = Park (the park list). Its factor columns are NOT used (user: they are
    # not accurate) - factors always come from the StatsPlus export, per club. When
    # the workbook exists, park_list.csv + park_assignments.csv in calib/<LG>/ are
    # refreshed from it, so the tracked copies stay current.
    "TGS": {"home": _home("TGS"), "exclude": NPB,
            "workbook": os.path.join(REPO, "perfekt filters and views", "TGS Park Factors.xlsx")},
    "BLM": {"home": _home("BLM"), "exclude": set()},
}


def refresh_park_csvs(league, cfg):
    """Regenerate calib/<LG>/park_list.csv + park_assignments.csv from the league
    workbook (sheet 'Current'). Silent no-op without a workbook or openpyxl."""
    wbp = cfg.get("workbook")
    if not wbp or not os.path.exists(wbp):
        return
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("  (openpyxl missing - park CSVs not refreshed from the workbook)")
        return
    wb = load_workbook(wbp, read_only=True, data_only=True)
    ws = wb["Current"] if "Current" in wb.sheetnames else wb.worksheets[0]
    assignments, parks = [], []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue
        team, park = (row[0] or ""), (row[1] or "")
        if str(team).strip() and str(park).strip():
            assignments.append((str(team).strip(), str(park).strip()))
        if len(row) > 3 and row[3] and str(row[3]).strip():
            parks.append([str(row[3]).strip()])
    cal = os.path.join(VIZ, "engine", "calib", league)
    os.makedirs(cal, exist_ok=True)
    with open(os.path.join(cal, "park_list.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Park"])
        w.writerows(parks)
    with open(os.path.join(cal, "park_assignments.csv"), "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Team", "MLB Park"])
        w.writerows(assignments)
    print(f"  refreshed park_list.csv ({len(parks)} parks) + park_assignments.csv "
          f"({len(assignments)} clubs) from {os.path.basename(wbp)}")

# CSV column -> output key. Handedness is the BATTER's side.
COLS = {
    "Avg RHB": "avg_rhb", "Avg LHB": "avg_lhb", "Average": "avg",
    "Doubles": "doubles", "Triples": "triples",
    "HR RHB": "hr_rhb", "HR LHB": "hr_lhb", "Home Runs": "hr",
}


def build(league, write=False):
    cfg = LEAGUES[league]
    refresh_park_csvs(league, cfg)
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

    # Parks page datasets (user 2026-09-12). Two sources the user keeps in
    # calib/<LG>/ (pasted from the league):
    #   park_list.csv         Park   (the park names; the league sheet's Copies and
    #                         factor columns are NOT used - occupancy is recounted and
    #                         factors come from the StatsPlus export per club)
    #   park_assignments.csv  Team, MLB Park   (which park each club plays in)
    # Occupancy = assigned clubs still in the league (an org with players in the
    # current pull) - folded clubs drop out on their own. League rule: a park can be
    # used by at most MAX_TEAMS_PER_PARK clubs; `open` = slots left to switch into.
    # Without those files (BLM) a stadium is the set of clubs with identical factor
    # rows, as before. Each club also ships its OWN factors: a club can run its own
    # version of a park.
    MAX_TEAMS_PER_PARK = 3
    cal = os.path.join(VIZ, "engine", "calib", league)
    lst_path = os.path.join(cal, "park_list.csv")
    asg_path = os.path.join(cal, "park_assignments.csv")
    park_list = []
    assignment = {}
    if os.path.exists(lst_path) and os.path.exists(asg_path):
        with open(lst_path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if not (r.get("Park") or "").strip():
                    continue
                park_list.append({"Name": r["Park"].strip()})
        with open(asg_path, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("Team") or "").strip():
                    assignment[r["Team"].strip()] = (r.get("MLB Park") or "").strip()
        active = set()
        for fn in ("hitters.json", "pitchers.json"):
            fp = os.path.join(VIZ, "public", "data", league, fn)
            if os.path.exists(fp):
                with open(fp, encoding="utf-8") as fh:
                    for rec in json.load(fh):
                        o = str(rec.get("ORG") or "").strip()
                        # skip the FA pool, bare numeric ids, and folded "(PWBL)" orgs
                        if o and o != "0" and not o.isdigit() and "(PWBL)" not in o:
                            active.add(o)
        park_names = {p["Name"] for p in park_list}
        bad = sorted(v for v in set(assignment.values()) if v not in park_names)
        if bad:
            print(f"  WARNING park_assignments.csv names parks not in park_list.csv: {bad}")
        gone = sorted(t for t in assignment if t not in active)
        if gone:
            print(f"  park_assignments.csv clubs no longer in the league (ignored): {gone}")
        occupants = {}
        for team, park in assignment.items():
            if team in active:
                occupants.setdefault(park, []).append(team)
        for p in park_list:
            occ = sorted(occupants.get(p["Name"], []))
            p["occupants"] = occ
            p["copies"] = len(occ)
            p["open"] = max(0, MAX_TEAMS_PER_PARK - len(occ))
            p["is_home"] = cfg["home"] in occ
        unassigned = sorted(t for t in active if t not in assignment)
        if unassigned:
            print(f"  WARNING active clubs with no park assignment: {unassigned}")
    else:
        print("  (no park_list.csv / park_assignments.csv - grouping clubs by identical factor rows)")

    # per-club rows: own factors + park
    if assignment:
        counted = {t for p in park_list for t in p["occupants"]}
        park_of = {t: pk for t, pk in assignment.items() if t in counted}
        rows_src = [r for r in mlb if r["Team"].strip() in park_of]
    else:
        park_of = {}
        auto = {}
        for r in mlb:
            sig = tuple((r.get(c) or "").strip() for c in list(COLS) + ["Capacity", "Stadium Type", "Surface"])
            auto.setdefault(sig, []).append(r["Team"].strip())
        for teams in auto.values():
            label = " / ".join(sorted(teams)) + " park"
            for t in teams:
                park_of[t] = label
        rows_src = mlb
    occ_by_park = {}
    for t, pk in park_of.items():
        occ_by_park[pk] = occ_by_park.get(pk, 0) + 1
    parks = []
    for r in rows_src:
        team = r["Team"].strip()
        pk = park_of[team]
        n = occ_by_park.get(pk, 0)
        row = {"Name": team, "park": pk, "stadium": pk,
               "n_teams": n, "open": max(0, MAX_TEAMS_PER_PARK - n),
               "is_home": team == cfg["home"],
               "capacity": (r.get("Capacity") or "").strip(),
               "type": (r.get("Stadium Type") or "").strip(),
               "surface": (r.get("Surface") or "").strip()}
        for col, key in COLS.items():
            row[key] = float(r[col])
        parks.append(row)
    parks.sort(key=lambda p: (p["park"], p["Name"]))
    if write:
        ddir = os.path.join(VIZ, "public", "data", league)
        os.makedirs(ddir, exist_ok=True)
        with open(os.path.join(ddir, "parks.json"), "w", encoding="utf-8") as fh:
            json.dump(parks, fh, ensure_ascii=False)
        with open(os.path.join(ddir, "park_list.json"), "w", encoding="utf-8") as fh:
            json.dump(park_list, fh, ensure_ascii=False)
        n_open = sum(1 for p in park_list if p["open"] > 0)
        print(f"  wrote public/data/{league}/parks.json ({len(parks)} clubs) + park_list.json "
              f"({len(park_list)} parks, {n_open} with an open slot)")
    return out


if __name__ == "__main__":
    write = "--write" in sys.argv
    picked = [a for a in sys.argv[1:] if a in LEAGUES] or list(LEAGUES)
    for lg in picked:
        build(lg, write=write)
