"""
dev_rating_odds.py - odds of becoming an MLB regular by age and one rating, DEV league.

The user asked (2026-09-24) for tables like "a player age 18 with 25 BABIP has
X% chance to be an MLB regular", for different ages, ratings and attributes.
This script builds those tables from the DEV league (all-AI OOTP 27, true
ratings, one dump per game-year) and writes them for the web app.

It reuses dev_odds.py for everything that decides who counts: the cohort
(players first seen at age <= 20 from the 2025 dump to the last banked dump
minus 23, ever in an org), the observations (one player-dump at ages 16-26, in
an org, all core skills and a Pot grade present; the same rows as dev_odds
pot_only), the "regular" outcome (>= 300 MLB PA or >= 150 MLB BF in some
season, judged through the last dump) and the eventual peak WAA (max engine
now_WAA over the player's dumps from the observation on; realized only when
some priced dump shows him at age >= 27). The app's /odds page (Make-it odds)
therefore counts the same players and outcomes as the dev_odds cells behind
the dev signals.

One table per role (H, P), basis and attribute. A cell is (5-point band of
the attribute, Jan-1 age) and carries:
  n          observations in the cell
  regular    share of n whose player ever had a regular season
  useful_n   observations whose player's peak is realized
  mlb        share of useful_n whose eventual peak WAA reached -1.0 (an
             MLB-level player, a 5th starter or bench bat; user, 2026-09-24:
             "if they will ever be anything in the mlb")
  useful     share of useful_n whose eventual peak WAA reached 0 (an average
             MLB player)
  good       share of useful_n whose eventual peak WAA reached +1.5 (a star)
Bars are dev_odds.PEAK_BARS.

Bases:
  current    the skill as it stands at that dump: mean of the vR and vL
             ratings, rounded to the nearest 5 (a half rounds up), clamped to
             20-80; Ovr and Pot are OOTP's 1-point grades, same rounding
  potential  the skill's potential rating of that dump (raw Pot<skill>), same
             rounding and clamp; Ovr and Pot have no potential basis

Attributes (output name -> raw dump key stem; raw has <stem>_R, <stem>_L and
Pot<stem>):
  hitters   BABIP BABIP, GAP Gap, POW Pow, EYE Eye, AvK Ks
  pitchers  STU Stf, HRR HRA, CON Ctrl, PBABIP PBABIP
  both      Ovr, Pot (current basis only)
HRR is the app's HRR column, the raw HRA rating, the same stem dev_odds uses.
Raw Mov (OOTP's Movement composite) is a different number and is not used.
Contact (raw Cntct) is not tabled: the user asked to remove it (2026-09-24,
"please remove contact from the list").

Output: tgs-viz/public/data/dev_rating_odds.json (layout in build_payload).
Cells with n = 0 are dropped. Every other cell ships with its n, including
thin ones (n < 30), so the page can grey them.

CLI:
  python tgs-viz/backtest/dev_rating_odds.py            print, write nothing
  python tgs-viz/backtest/dev_rating_odds.py --write    also write the JSON
  --rebuild                                             ignore the playing-time cache
  --dump-root PATH                                      the DEV .lg folder or its dump/ folder
  --obs-cache PATH                                      pickle of the tallied rows, for reruns
"""
import argparse
import datetime
import gzip
import json
import math
import os
import pickle
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dev_odds as D                                         # noqa: E402

OUT_PATH = os.path.join(VIZ, "public", "data", "dev_rating_odds.json")
AGES = D.AGES                                                # 16-26
BANDS = list(range(20, 85, 5))                               # 20, 25, ..., 80
BASES = ["current", "potential"]
THIN_N = 30                                                  # the page greys cells below this n

# attribute name -> raw stem; raw has <stem>_R, <stem>_L and Pot<stem>.
# Contact (raw Cntct) is left out: user, 2026-09-24, "please remove contact from the list".
ATTRS = {
    "H": [("BABIP", "BABIP"), ("GAP", "Gap"), ("POW", "Pow"), ("EYE", "Eye"), ("AvK", "Ks")],
    "P": [("STU", "Stf"), ("HRR", "HRA"), ("CON", "Ctrl"), ("PBABIP", "PBABIP")],
}
GRADES = ["Ovr", "Pot"]                                      # OOTP 1-point grades, current basis only
# mlb = an MLB-level player (user, 2026-09-24: "if they will ever be anything in the mlb")
MLB_BAR = D.PEAK_BARS["mlb"]
USEFUL_BAR = D.PEAK_BARS["useful"]
GOOD_BAR = D.PEAK_BARS["good"]


# ---------------------------------------------------------------- bands
def band(v):
    """5-point display band of one rating: nearest 5, a half rounds up, clamped
    to 20-80 (user, 2026-09-24: tables in 5-point steps 20..80)."""
    if v is None:
        return None
    b = int(math.floor(float(v) / 5.0 + 0.5)) * 5
    return max(BANDS[0], min(BANDS[-1], b))


def rating_bands(rec, role):
    """(current bands, potential bands, Ovr band, Pot band) of one raw dump row."""
    cur = tuple(band(D.display(rec, stem)) for _name, stem in ATTRS[role])
    pot = tuple(band(D.to_int(rec.get("Pot" + stem))) for _name, stem in ATTRS[role])
    return (cur, pot, band(D.to_int(rec.get("Ovr"))), band(D.to_int(rec.get("Pot"))))


def slim(rec):
    """dev_odds' slim row plus the banded ratings at ages 16-26 (None elsewhere)."""
    out = D.slim(rec)
    a = out["age"]
    if a is not None and AGES[0] <= a <= AGES[-1]:
        out["rat"] = rating_bands(rec, D.role_of(out["pos"]))
    else:
        out["rat"] = None
    return out


def load_players(log=print):
    """{pid: {year: slim row}} over every raw DEV vintage, like dev_odds.load_players."""
    players = defaultdict(dict)
    years = D.raw_years()
    if not years:
        raise SystemExit(f"no raw vintages under {D.VINT_DIR}")
    for y, path in years.items():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        for r in rows:
            pid = str(r.get("ID") or "")
            if pid:
                players[pid][y] = slim(r)
    log(f"  raw vintages: {len(years)} dumps {min(years)}-{max(years)}, {len(players)} players")
    return dict(players), (min(years), max(years))


# ---------------------------------------------------------------- rows and tally
def tally_rows(players, obs_all):
    """One compact row per observation: (role, age, reg, peak, cur, pot, ovr, pot_grade)."""
    rows = []
    for o in obs_all:
        rat = players[o["pid"]][o["year"]]["rat"]
        if rat is None:
            continue
        cur, pot, ovr_b, pot_b = rat
        rows.append((o["role"], o["age"], bool(o["reg"]), o.get("peak"), cur, pot, ovr_b, pot_b))
    return rows


def new_cell():
    # n, regular hits, realized n, mlb hits, useful hits, good hits
    return [0, 0, 0, 0, 0, 0]


def tally(rows):
    """{role: {basis: {attr: {band: {age: [n, k_reg, useful_n, k_mlb, k_useful, k_good]}}}}}"""
    cells = {role: {b: {} for b in BASES} for role in ATTRS}

    def bump(role, basis, name, b, age, reg, peak):
        if b is None:
            return
        c = cells[role][basis].setdefault(name, {}).setdefault(b, {}).setdefault(age, new_cell())
        c[0] += 1
        c[1] += 1 if reg else 0
        if peak is not None:
            c[2] += 1
            # the three bars over the same realized players (user, 2026-09-24:
            # mlb = anything in MLB, useful = average, good = a star)
            c[3] += 1 if peak >= MLB_BAR else 0
            c[4] += 1 if peak >= USEFUL_BAR else 0
            c[5] += 1 if peak >= GOOD_BAR else 0

    for role, age, reg, peak, cur, pot, ovr_b, pot_b in rows:
        names = [name for name, _stem in ATTRS[role]]
        for name, b in zip(names, cur):
            bump(role, "current", name, b, age, reg, peak)
        for name, b in zip(names, pot):
            bump(role, "potential", name, b, age, reg, peak)
        bump(role, "current", "Ovr", ovr_b, age, reg, peak)
        bump(role, "current", "Pot", pot_b, age, reg, peak)
    return cells


def share(k, n):
    return round(k / n, 3) if n else None


def cell_out(c):
    n, k, un, km, ku, kg = c
    return {"n": n, "regular": share(k, n), "useful_n": un,
            "mlb": share(km, un), "useful": share(ku, un), "good": share(kg, un)}


def build_payload(cells, meta):
    tables = {}
    for role in ATTRS:
        tables[role] = {}
        for basis in BASES:
            tables[role][basis] = {}
            for name, by_band in cells[role][basis].items():
                t = {}
                for b in BANDS:
                    by_age = by_band.get(b)
                    if not by_age:
                        continue
                    t[str(b)] = {str(a): cell_out(by_age[a]) for a in AGES if a in by_age}
                tables[role][basis][name] = t
    attrs = {role: [name for name, _stem in ATTRS[role]] + GRADES for role in ATTRS}
    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "league": D.LEAGUE,
        "seasons": list(meta["seasons"]),
        "cohort": meta["cohort"],
        "peak_basis": meta["peak_basis"],
        "definitions": {
            "cell": "one (attribute band, age) pair: n observations, regular = share of n, "
                    "useful_n = observations whose player's peak is realized, mlb, useful and "
                    "good = shares of useful_n",
            "regular": f"a season with >= {D.REGULAR_PA} MLB PA (hitter) or >= {D.REGULAR_BF} MLB BF "
                       "(pitcher), MLB = level_id 1 of the dump's per-game files; the outcome is "
                       "whether the player ever had one through the last dump, the dev_odds "
                       "definition; every observation counts, so players still young at the last "
                       "dumps count as not yet regular, the same as dev_odds pot_only",
            "mlb": f"share of useful_n whose eventual peak WAA reached {MLB_BAR:g} (an MLB-level "
                   "player, a 5th starter or bench bat); user, 2026-09-24: 'if they will ever be "
                   "anything in the mlb'",
            "useful": f"share of useful_n whose eventual peak WAA reached {USEFUL_BAR:g} (an average "
                      "MLB player)",
            "good": f"share of useful_n whose eventual peak WAA reached +{GOOD_BAR:g} (a star)",
            "peak": "eventual peak WAA = max of the player's engine now_WAA over his dumps from the "
                    "observation's dump on (BLM engine, neutral park, vintages/DEV/.waa_cache); "
                    f"realized, and counted in useful_n, only when some priced dump shows him at "
                    f"age >= {D.PEAK_MIN_AGE}",
            "cohort": f"players first seen at age <= {D.COHORT_MAX_AGE} in dumps "
                      f"{D.COHORT_YEARS[0]}-{D.COHORT_YEARS[1]} who were ever in an org (level R, A, "
                      "AA, AAA or MLB); dev_odds' cohort",
            "observation": "one player-dump at ages 16-26, in an org at that dump, with every core "
                           "skill and the Pot grade present (dev_odds obs_all, the rows behind "
                           "pot_only); the same player counts once per age; the 2025 dump has no "
                           "Pot grade and is skipped",
            "age": "the dump's Age field: the Jan-1 age, dump_<year> being dated Jan 1 of year+1",
            "role": "P when the dump position is SP, RP or CL, else H",
            "band": "5-point display band 20..80: the value rounded to the nearest 5, a half rounds "
                    "up (42.5 -> 45), values below 20 or above 80 clamped",
            "current": "split skills: mean of the vR and vL ratings of that dump, then banded; Ovr "
                       "and Pot: OOTP's 1-point grade of that dump, banded",
            "potential": "the skill's potential rating of that dump (raw Pot<skill>), banded; no "
                         "potential basis for Ovr and Pot",
            "attributes": "H: BABIP GAP POW EYE AvK (raw BABIP Gap Pow Eye Ks); P: STU HRR CON "
                          "PBABIP (raw Stf HRA Ctrl PBABIP); HRR = the app's HRR column = raw HRA, "
                          "as in dev_odds; raw Mov is not used; Contact (raw Cntct) is left out "
                          "(user, 2026-09-24: 'please remove contact from the list')",
            "thin": f"cells with n < {THIN_N} (or useful_n < {THIN_N}) are thin; they ship with "
                    "their n so the page can grey them; cells with n = 0 are dropped",
        },
        "notes": [
            "Cohort, observations, regular outcome and eventual peak come from dev_odds.py, so the "
            "/odds page counts the same players and outcomes as the dev_odds cells (pot_only) behind "
            "the dev signals' MLB / useful / good shares.",
            "mlb, useful and good share one denominator (useful_n) and nest: good <= useful <= mlb.",
            "A share is over one attribute alone. Players in the same band differ in every other "
            "rating, so read a cell as 'players who looked like this in this one skill'.",
            "useful_n is smaller than n: only players seen at age >= 27 in a priced dump have a "
            "realized peak.",
            "User, 2026-09-24: tables per age, rating band and attribute.",
        ],
        "ages": AGES,
        "bands": BANDS,
        "bases": BASES,
        "attributes": attrs,
        "thin_n": THIN_N,
        "tables": tables,
    }


# ---------------------------------------------------------------- report
def get_cell(payload, role, basis, name, b, age):
    return (payload["tables"].get(role, {}).get(basis, {}).get(name, {})
            .get(str(b), {}).get(str(age)))


def fmt(c):
    if not c:
        return "n=0"
    pct = lambda v: "   -  " if v is None else f"{100 * v:5.1f}%"       # noqa: E731
    return (f"regular {pct(c['regular'])} (n {c['n']})  mlb {pct(c['mlb'])}  "
            f"useful {pct(c['useful'])}  good {pct(c['good'])} (n {c['useful_n']})")


def print_report(payload, log=print):
    log("\nReport cells (current basis)")
    for b in (25, 40, 55):
        log(f"  H age 18 BABIP {b}:  {fmt(get_cell(payload, 'H', 'current', 'BABIP', b, 18))}")
    log(f"  H age 18 Pot 50:    {fmt(get_cell(payload, 'H', 'current', 'Pot', 50, 18))}")
    log(f"  P age 18 Pot 50:    {fmt(get_cell(payload, 'P', 'current', 'Pot', 50, 18))}")
    log(f"  P age 21 CON 50:    {fmt(get_cell(payload, 'P', 'current', 'CON', 50, 21))}")
    for role, name in (("H", "BABIP"), ("P", "STU")):
        log(f"\n{role} {name} current: regular% (n) by band x age")
        log("  band  " + "  ".join(f"{a:>12d}" for a in AGES))
        for b in BANDS:
            row = []
            for a in AGES:
                c = get_cell(payload, role, "current", name, b, a)
                row.append(f"{100 * c['regular']:5.1f}% ({c['n']:4d})" if c else "      -      ")
            log(f"  {b:4d}  " + "  ".join(row))


def check_payload(payload):
    """Every share in [0, 1], good <= useful <= mlb, n > 0 in every shipped cell."""
    bad = []
    for role, bases in payload["tables"].items():
        if "Contact" in bases.get("current", {}) or "Contact" in bases.get("potential", {}):
            bad.append(f"{role}: Contact table shipped (user, 2026-09-24: removed from the list)")
        for basis, attrs in bases.items():
            for name, bands in attrs.items():
                for b, ages in bands.items():
                    for a, c in ages.items():
                        where = f"{role}/{basis}/{name}/{b}/{a}"
                        if c["n"] <= 0:
                            bad.append(where + ": n = 0 shipped")
                        for k in ("regular", "mlb", "useful", "good"):
                            v = c[k]
                            if v is not None and not (0.0 <= v <= 1.0):
                                bad.append(f"{where}: {k} = {v}")
                        if c["useful"] is not None and c["good"] is not None and c["useful"] < c["good"]:
                            bad.append(f"{where}: useful {c['useful']} < good {c['good']}")
                        if c["mlb"] is not None and c["useful"] is not None and c["mlb"] < c["useful"]:
                            bad.append(f"{where}: mlb {c['mlb']} < useful {c['useful']}")
                        if (c["useful"] is None) != (c["useful_n"] == 0):
                            bad.append(f"{where}: useful null does not match useful_n")
                        if (c["mlb"] is None) != (c["useful_n"] == 0):
                            bad.append(f"{where}: mlb null does not match useful_n")
    return bad


# ---------------------------------------------------------------- main
def compute(args, log=print):
    root = D.find_dump_root(args.dump_root)
    log(f"dev_rating_odds: dump root {root}")
    pt = D.load_mlb_pt(root, rebuild=args.rebuild, log=log)
    players, seasons = load_players(log=log)
    cohort, obs, obs_all = D.measure(players, pt, log=log)
    waa = D.load_waa(log=log)
    realized, stamped = D.stamp_peaks(players, cohort, obs, obs_all, waa, log=log)
    rows = tally_rows(players, obs_all)
    roles = {"H": 0, "P": 0}
    for role, _reg in cohort.values():
        roles[role] += 1
    meta = {
        "seasons": seasons,
        "cohort": {"players": len(cohort), "hitters": roles["H"], "pitchers": roles["P"],
                   "observations": len(rows)},
        "peak_basis": {"waa_vintages": len(waa), "waa_years": [min(waa), max(waa)] if waa else None,
                       "min_age": D.PEAK_MIN_AGE, "players_realized": len(realized),
                       "rows_stamped": stamped},
    }
    return rows, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="DEV league odds by age and one rating band")
    ap.add_argument("--write", action="store_true", help="write public/data/dev_rating_odds.json")
    ap.add_argument("--rebuild", action="store_true", help="ignore the playing-time cache")
    ap.add_argument("--dump-root", default=None, help="DEV .lg folder or its dump/ folder")
    ap.add_argument("--obs-cache", default=None,
                    help="pickle of the tallied rows; read when present, written otherwise")
    args = ap.parse_args(argv)
    log = print
    rows = meta = None
    if args.obs_cache and os.path.isfile(args.obs_cache):
        with open(args.obs_cache, "rb") as fh:
            rows, meta = pickle.load(fh)
        log(f"dev_rating_odds: {len(rows)} rows from {args.obs_cache}")
    else:
        rows, meta = compute(args, log=log)
        if args.obs_cache:
            os.makedirs(os.path.dirname(os.path.abspath(args.obs_cache)), exist_ok=True)
            with open(args.obs_cache, "wb") as fh:
                pickle.dump((rows, meta), fh)
            log(f"  rows cached: {args.obs_cache}")
    payload = build_payload(tally(rows), meta)
    c = meta["cohort"]
    log(f"  cohort {c['players']} players ({c['hitters']} H, {c['pitchers']} P); "
        f"{c['observations']} observations; {meta['peak_basis']['players_realized']} realized peaks")
    bad = check_payload(payload)
    if bad:
        for line in bad[:20]:
            log("  CHECK FAILED " + line)
        raise SystemExit(f"{len(bad)} cell check(s) failed")
    log("  checks: every share in [0, 1], mlb >= useful >= good, no Contact table, no empty cell shipped")
    print_report(payload, log=log)
    if args.write:
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        log(f"\nwrote {OUT_PATH} ({os.path.getsize(OUT_PATH)} bytes)")
    else:
        log("\n(dry run; add --write to write public/data/dev_rating_odds.json)")
    return payload


if __name__ == "__main__":
    main()
