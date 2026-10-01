"""
agecurve_fit.py — MEASURED per-age development rates from the ratings archive.

The FV machinery models development as a logistic gap-closure curve with ASSUMED
constants (16 -> 25, ~50% at 20.5, 95% closed at maturity). This measures the
real thing, per league, from the archived ratings vintages.

METHOD (user spec 2026-09-04 — "expected growth per year of age", never per pull):
  - EVERY consecutive vintage pair is used (not first-vs-last: a 1.3-year window
    bucketed by starting age credits age-24 with development that happened at 25)
  - a pair's IN-GAME span (years) = share of its org'd shared players whose
    integer age ticked up (each player has exactly one birthday per game-year,
    so the aged fraction IS the elapsed fraction of a year); a pair with no
    in-game time is SKIPPED — its deltas are scout churn, not development
  - a player's change is attributed to the age he WAS: fully to his starting age
    when he did not age up, split half/half (delta and exposure alike) when his
    birthday crossed the pair
  - per age: dWAA/yr = total delta / total player-years (exposure-weighted), and
    gap-closure/yr the same way over players with a real remaining gap
  - the per-pair CONTAMINATION GUARD skips only the poisoned pair (a re-scout /
    adjusted-ratings toggle between two pulls), instead of damning the archive —
    clean pairs keep accumulating around scale events
  - MLB/minors only (org attached); trimmed/median stats are gone on purpose —
    week-scale deltas are mostly zero, so only the ratio of sums means anything

Engine WAA per vintage is CACHED (backtest/vintages/<LG>/.waa_cache/) keyed by a
calib fingerprint: the first run pays ~40s per vintage, every later run computes
only vintages it has never seen; a recalibration changes the fingerprint and
triggers one full rebuild.

LEAGUES ARE SEPARATE. Each league is measured only on its own archive; a league
whose usable pairs span less than MIN_SPAN game-years is refused, never borrowed.

Per the ratings-history rule, nothing here feeds back into any player's own
projection: the output is a LEAGUE-WIDE curve, shipped for display (the
profile's development chart) and for the user to compare against the FV
assumptions before deciding to swap them (the measured FV path stays dormant).

    python tgs-viz/engine/agecurve_fit.py --league TGS [--write]
    python tgs-viz/engine/agecurve_fit.py --league DEV --calib BLM [--write]

--calib <LG>: run the engine with THAT league's calibration (a dump league such
as DEV has true OOTP 27 ratings but no calibration of its own; BLM's is the
OOTP 27 one). Bats / throws / height then come from the league's raw vintage
rows (backtest/vintages/<LG>/raw_<year>.json.gz) instead of a shipped pull.
--write ->  calib/<LG>/age_curve.json  +  public/data/<LG>/age_curve.json
"""
import os
import sys
import csv
import glob
import gzip
import json
import hashlib
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
sys.path.insert(0, os.path.join(VIZ, "ingest"))
import ratings as R  # noqa: E402
sys.path.insert(0, os.path.join(VIZ, "backtest"))
import pull_order as PO  # in-game order of the archived pulls  # noqa: E402


def ordered_vintages(league, log=print):
    """Vintage files (vintages/<LG>/<real_date>_p<id>.csv.gz) oldest first by
    IN-GAME date (pull_order.py). An asof snapshot (real_date = its in-game
    date) sorts among the live pulls by its game date, never by file time.
    Order source: the archive DB; without it, vintages/<LG>/_pulls.csv.
    A file whose pull is not in the archive (a same-day re-pull replaced it)
    is left out. Neither source: file modification time (the old rule)."""
    import re
    import sqlite3
    vdir = os.path.join(PO.VINTAGES_DIR, league)
    files = {}
    for f in glob.glob(os.path.join(vdir, "*.csv.gz")):
        m = re.search(r"_p(\d+)\.csv\.gz$", os.path.basename(f))
        if m:
            files[int(m.group(1))] = f
    rows = None
    if os.path.exists(PO.DB_PATH):
        conn = sqlite3.connect(f"file:{PO.DB_PATH}?mode=ro", uri=True)
        try:
            rows = PO.ordered(conn, league, log)[0]
        finally:
            conn.close()
    elif os.path.exists(os.path.join(vdir, "_pulls.csv")):
        with open(os.path.join(vdir, "_pulls.csv"), newline="", encoding="utf-8") as fh:
            recs = list(csv.DictReader(fh))
        rows = [(int(r["pull_id"]), r["real_date"], r.get("real_ts") or "", r["source"], r.get("n_players"))
                for r in recs]
        game = {int(r["pull_id"]): (r.get("game_date") or (r["real_date"] if r["source"] in PO.SELF_DATED
                                                             else None)) for r in recs}
        rows = PO.sort_rows(rows, {k: v for k, v in game.items() if v}, league, log)
    if rows is None:
        return sorted(files.values(), key=os.path.getmtime)
    out = [files[r[0]] for r in rows if r[0] in files]
    left = sorted(set(files) - {r[0] for r in rows})
    if left:
        log(f"{league}: {len(left)} vintage file(s) not in the archive, left out "
            f"(pull ids {', '.join(str(x) for x in left)}; a same-day re-pull replaced them)")
    return out

MIN_SPAN = 0.5      # game-years across USABLE pairs; refuse to fit less
MIN_AGE_N = 25      # min observations for an age to ship
PIT_POS = ("SP", "RP", "CL")
GUARD_COLS = ("c_STU_P", "c_HT_P", "c_POW_P")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_vintage(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return {r["player_id"]: r for r in csv.DictReader(fh)}


def to_records(vint, static):
    """Vintage rows -> engine-shaped records (c_BA_vR -> 'BA vR', + static traits)."""
    hit, pit = [], []
    for pid, r in vint.items():
        stc = static.get(pid)
        if not stc:
            continue          # not in the current pull -> no B/T/HT; skip
        rec = {"ID": pid, "Name": r.get("name"), "POS": (r.get("pos") or "").upper(),
               "Age": r.get("age"), "B": stc["B"], "T": stc["T"], "HT": stc["HT"]}
        for k, v in r.items():
            if k.startswith("c_"):
                rec[k[2:].replace("_", " ") if k[2:] not in (
                    "FB", "CH", "CB", "SL", "SI", "SP", "CT", "FO", "CC", "SC", "KC", "KN",
                    "KNP", "FBP", "CHP", "CBP", "SLP", "SIP", "SPP", "CTP", "FOP", "CCP",
                    "SCP", "KCP", "STM", "HLD", "SPE", "SR", "STE", "RUN", "TDP", "Ovr", "Pot",
                ) else k[2:]] = v
        (pit if rec["POS"] in PIT_POS else hit).append(rec)
    return hit, pit


def calib_fingerprint(league):
    """Hash of the calib inputs the engine reads — cache key component. A
    recalibration (or hand edit) changes it and invalidates every cached pass."""
    h = hashlib.md5()
    for fn in ("constants-latest.json", "scurves.json", "fielding_curves.json",
               "hitter_tails.json", "role_stuff.json", "currency.json"):
        p = os.path.join(HERE, "calib", league, fn)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:10]


def vintage_waa(league, path, static, fp, calib=None):
    """{pid: [now, ceil, kind, age, org, stu_p, ht_p, pow_p]} for one vintage,
    from the .waa_cache when the calib fingerprint matches, else computed and
    cached. The guard cols ride along so the pair loop never re-reads the gz.
    calib = the league whose engine calibration prices the ratings (default:
    the league itself)."""
    calib = calib or league
    own = calib == league          # the league's own players: its observed role switches apply
    cache_dir = os.path.join(os.path.dirname(path), ".waa_cache")
    cache = os.path.join(cache_dir, f"{os.path.basename(path)}.{fp}.json")
    if os.path.exists(cache):
        with open(cache, encoding="utf-8") as fh:
            return json.load(fh)
    vint = load_vintage(path)
    hit, pit = to_records(vint, static)
    league = calib
    cur = R.live_currency(league)
    out = {}
    hrecs = R.run_hitters(hit, league, currency=cur, tails=R.live_hitter_tails(league),
                          fielding=R.live_fielding(league), park_mode="neutral")
    for r in hrecs:
        out[str(r["ID"])] = [_num(r.get("Max WAA wtd")), _num(r.get("MAX WAA P")), "H"]
    precs = R.run_pitchers(pit, league, scurves=R.live_scurves(league), currency=cur,
                           park_mode="neutral", role_stuff=R.live_role_stuff(league), observed=own)
    for r in precs:
        now = max([x for x in (_num(r.get("WAA wtd")), _num(r.get("WAA wtd RP")))
                   if x is not None], default=None)
        ceil = max([x for x in (_num(r.get("WAP")), _num(r.get("WAP RP")))
                    if x is not None], default=None)
        out[str(r["ID"])] = [now, ceil, "P"]
    for pid, entry in out.items():
        v = vint.get(pid, {})
        entry.extend([v.get("age"), v.get("org"),
                      _num(v.get("c_STU_P")), _num(v.get("c_HT_P")), _num(v.get("c_POW_P"))])
    os.makedirs(cache_dir, exist_ok=True)
    tmp = cache + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    os.replace(tmp, cache)
    return out


def main():
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else "TGS"
    calib = sys.argv[sys.argv.index("--calib") + 1] if "--calib" in sys.argv else league
    write = "--write" in sys.argv
    # --no-guard: a true-ratings dump league has no scout and no re-scale events;
    # a whole game-year of real development moves league medians, which the
    # guard would read as contamination. Off by default for scouted archives.
    no_guard = "--no-guard" in sys.argv

    files = ordered_vintages(league)       # in-game order (was: file modification time)
    if len(files) < 2:
        print(f"{league}: fewer than 2 vintages archived — nothing to measure")
        return 1

    # static traits (bats / throws / height): from the current shipped pull, or,
    # for a league with no shipped pull (a dump league), from its raw vintage rows
    static = {}
    shipped = os.path.join(VIZ, "public", "data", league, "hitters.json")
    if os.path.exists(shipped):
        for fn in ("hitters.json", "pitchers.json"):
            with open(os.path.join(VIZ, "public", "data", league, fn), encoding="utf-8") as fh:
                for r in json.load(fh):
                    static[str(r.get("ID"))] = {"B": r.get("B"), "T": r.get("T"), "HT": r.get("HT")}
    else:
        for rp in sorted(glob.glob(os.path.join(PO.VINTAGES_DIR, league, "raw_*.json.gz"))):
            with gzip.open(rp, "rt", encoding="utf-8") as fh:
                for r in json.load(fh):
                    ht = r.get("Height") or r.get("HT")
                    try:
                        ht = float(ht) if ht not in (None, "") else None
                    except ValueError:
                        ht = None
                    static[str(r.get("ID"))] = {"B": r.get("Bats") or r.get("B"),
                                                "T": r.get("Throws") or r.get("T"), "HT": ht}
        print(f"{league}: bats / throws / height read from {len(static)} raw vintage rows")
    if not static:
        print(f"{league}: no bats / throws / height source (no shipped pull, no raw vintage rows)")
        return 1

    fp = calib_fingerprint(calib) + ("" if calib == league else f"-{calib}")
    print(f"{league}: {len(files)} vintages, engine calibration {calib}, fingerprint {fp} "
          f"(uncached vintages get one engine pass each; later runs reuse the cache)")

    sums, yrs, cnt = {}, {}, {}
    csums, cyrs, ccnt = {}, {}, {}
    players_by_age = {}
    pairs_used = pairs_zero = pairs_dirty = 0
    span_total = 0.0
    prev = None
    prev_name = None
    for path in files:
        cached = os.path.exists(os.path.join(os.path.dirname(path), ".waa_cache",
                                             f"{os.path.basename(path)}.{fp}.json"))
        if not cached:
            print(f"  engine pass: {os.path.basename(path)} ...")
        cur = vintage_waa(league, path, static, fp, calib=calib)
        if prev is not None:
            shared = []
            for pid, e2 in cur.items():
                e1 = prev.get(pid)
                if not e1 or e1[2] != e2[2]:
                    continue
                if e1[4] in (None, "", "0", 0):        # MLB/minors only
                    continue
                a1, a2 = _num(e1[3]), _num(e2[3])
                if a1 is None or a2 is None:
                    continue
                d = int(a2) - int(a1)
                if d in (0, 1):
                    shared.append((pid, e1, e2, int(a1), d))
            span = (sum(s[4] for s in shared) / len(shared)) if shared else 0.0
            if span <= 0:
                pairs_zero += 1
            else:
                # per-pair contamination guard: a league-wide median potential
                # shift means a re-scout / adjusted-ratings toggle sits inside
                # THIS pair — skip it alone, keep every clean pair around it
                dirty = False
                for gi in (() if no_guard else (5, 6, 7)):
                    ds = [e2[gi] - e1[gi] for _pid, e1, e2, _a, _d in shared
                          if e1[gi] is not None and e2[gi] is not None]
                    if ds and abs(st.median(ds)) >= 2:
                        print(f"  SKIP pair {prev_name} -> {os.path.basename(path)}: "
                              f"median {GUARD_COLS[gi - 5]} shift {st.median(ds):+.1f} "
                              f"(re-scout/scale event inside the pair)")
                        dirty = True
                        break
                if dirty:
                    pairs_dirty += 1
                else:
                    pairs_used += 1
                    span_total += span
                    for pid, e1, e2, a1, d in shared:
                        n1, c1 = e1[0], e1[1]
                        n2 = e2[0]
                        if n1 is None or n2 is None:
                            continue
                        parts = ((a1, 1.0),) if d == 0 else ((a1, 0.5), (a1 + 1, 0.5))
                        delta = n2 - n1
                        gap = (c1 - n1) if c1 is not None else None
                        for age, w in parts:
                            players_by_age.setdefault(age, set()).add(pid)
                            sums[age] = sums.get(age, 0.0) + delta * w
                            yrs[age] = yrs.get(age, 0.0) + span * w
                            cnt[age] = cnt.get(age, 0) + 1
                            if gap is not None and gap >= 0.3:
                                # clamp per-pair closure so one glitch row can't
                                # dominate a week's tiny denominator
                                cd = max(-1.0, min(2.0, delta / gap))
                                csums[age] = csums.get(age, 0.0) + cd * w
                                cyrs[age] = cyrs.get(age, 0.0) + span * w
                                ccnt[age] = ccnt.get(age, 0) + 1
        prev = cur
        prev_name = os.path.basename(path)

    print(f"  pairs: {pairs_used} used, {pairs_zero} zero-time, {pairs_dirty} contaminated "
          f"-> {span_total:.2f} usable game-years")
    if span_total < MIN_SPAN:
        print(f"  usable pairs span < {MIN_SPAN} game-years — refusing to fit "
              f"(leagues are never borrowed from)")
        return 1

    print(f"\n  {'age':>4} {'n':>7} {'players':>8} {'yrs':>7} {'dWAA/yr':>9}"
          f" {'closure/yr':>11} {'n(gap)':>7}")
    curve = {}
    for age in sorted(sums):
        if cnt[age] < MIN_AGE_N or yrs[age] <= 0:
            continue
        closure = (csums[age] / cyrs[age]) if cyrs.get(age, 0) > 0 and ccnt.get(age, 0) >= MIN_AGE_N else None
        curve[age] = {
            "n": cnt[age],
            "players": len(players_by_age.get(age, ())),
            "years": round(yrs[age], 1),
            "mean": round(sums[age] / yrs[age], 4),
            "closure": round(closure, 4) if closure is not None else None,
            "n_gap": ccnt.get(age, 0),
        }
        c = curve[age]
        print(f"  {age:>4} {c['n']:>7} {c['players']:>8} {c['years']:>7.1f} {c['mean']:>9.3f}"
              f" {(f'{c[chr(99)+chr(108)+chr(111)+chr(115)+chr(117)+chr(114)+chr(101)]:.3f}' if c['closure'] is not None else '     -'):>11} {c['n_gap']:>7}")

    out = {
        "league": league,
        "calibration": calib,
        "window": [os.path.basename(files[0]), os.path.basename(files[-1])],
        "span_years": round(span_total, 3),
        "pairs": {"used": pairs_used, "zero_time": pairs_zero, "contaminated": pairs_dirty},
        "players": len(set().union(*players_by_age.values())) if players_by_age else 0,
        "curve": curve,
        "notes": ["gain per AGE-YEAR: adjacent-pair deltas attributed to the age the player "
                  "was (split on birthday crossings), exposure-weighted ratio of sums",
                  "dWAA/yr on the neutral-park basis; MLB/minors only",
                  "closure = share of the (ceiling - current) gap closed per game-year",
                  "contaminated pairs (re-scout/adjusted-ratings inside the pair) are "
                  "skipped individually; clean pairs keep accumulating"]
                 + ([f"ratings priced with the {calib} engine calibration (the league has none of its own)"]
                    if calib != league else []),
    }
    if write:
        for d in (os.path.join(HERE, "calib", league),
                  os.path.join(VIZ, "public", "data", league)):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "age_curve.json"), "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=1)
        print(f"\n  wrote calib/{league}/age_curve.json + public/data/{league}/age_curve.json")
    else:
        print("\n  (dry run — pass --write to ship the curve)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
