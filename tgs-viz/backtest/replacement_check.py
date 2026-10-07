"""
replacement_check.py - check a league's replacement credits (engine/calib/replacement.json)
against what an engine-0 player actually delivered in OOTP's own WAR.

WAR = engine WAA + credit(role) is right only when the credit equals the WAR of a player the
engine rates at exactly 0 WAA. The budget identity (average WAR per slot) equals that only when
the average MLB player is 0 WAA in the engine. This script measures it directly:

  1. for each banked season (backtest/actuals/<LG>/<year>), take the archived ratings snapshot
     nearest July 1 of that season (an asof or live pull dated <year>-04-01 .. <year>-09-30)
  2. price every player with the engine on that snapshot (--calib: the calibration the app
     prices the league with; neutral park)
  3. regress each MLB player's actual WAR rate on his engine WAA, weighted by playing time:
       SP  war / (BF / 800) on "WAA wtd"      (SP = GS >= G/2)
       RP  war / (BF / 300) on "WAA wtd RP"
       H   war / (PA / 600) on the engine WAA at the positions he played (fielding innings
           weighted; C WAA x 600/500 to the 600-PA basis; DH when he did not field)
     The intercept is the WAR of an engine-0 player per slot: the credit to compare.
Pitchers are fitted on OOTP's war (FIP-based) and ra9war (runs allowed, the engine's basis).
Seasons are reported one by one and pooled. A player missing from the current pull has no
bats / throws / height, so he is skipped; the coverage line says how much playing time that is.

Read-only: prints, writes nothing. Python 3.13+, numpy, pandas.

  python tgs-viz/backtest/replacement_check.py --league SSB --calib BLM [--seasons 2043,2044]
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(VIZ, "engine"))
sys.path.insert(0, os.path.join(VIZ, "ingest"))
import agecurve_fit as A  # noqa: E402
import ratings as R  # noqa: E402

POS_NUM = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
BOOT = 1000


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def pull_game_dates(league):
    """{pull_id: in-game date} from vintages/<LG>/_pulls.csv (game_date, else real_date: a live
    pull's file name carries the real-world date, an asof pull's the game date)."""
    p = os.path.join(VIZ, "backtest", "vintages", league, "_pulls.csv")
    if not os.path.exists(p):
        return {}
    d = pd.read_csv(p, dtype=str)
    gd = d["game_date"] if "game_date" in d else d["real_date"]
    return {int(i): str(g if isinstance(g, str) and g else r)
            for i, g, r in zip(d["pull_id"], gd, d["real_date"])}


def snapshot_for(league, year):
    """The archived vintage whose IN-GAME date is nearest <year>-07-01 inside <year>-04-01 ..
    <year>-09-30, or None."""
    best, gap = None, None
    target = datetime.date(year, 7, 1)
    games = pull_game_dates(league)
    for p in glob.glob(os.path.join(VIZ, "backtest", "vintages", league, "*_p*.csv.gz")):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})_p(\d+)\.csv\.gz$", os.path.basename(p))
        if not m:
            continue
        g = games.get(int(m.group(4)))
        try:
            d = datetime.date.fromisoformat(g[:10]) if g else None
        except ValueError:
            d = None
        if d is None:
            continue
        if not (datetime.date(year, 4, 1) <= d <= datetime.date(year, 9, 30)):
            continue
        g = abs((d - target).days)
        if gap is None or g < gap:
            best, gap = p, g
    return best


def static_traits(league):
    out = {}
    for fn in ("hitters.json", "pitchers.json"):
        p = os.path.join(VIZ, "public", "data", league, fn)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                for r in json.load(fh):
                    out[str(r.get("ID"))] = {"B": r.get("B"), "T": r.get("T"), "HT": r.get("HT")}
    return out


def price(path, static, calib):
    """(pitchers frame: player_id, sp, rp), (hitters frame: player_id, C..DH WAA wtd)."""
    hit, pit = A.to_records(A.load_vintage(path), static)
    cur = R.live_currency(calib)
    precs = R.run_pitchers(pit, calib, scurves=R.live_scurves(calib), currency=cur, park_mode="neutral",
                           role_stuff=R.live_role_stuff(calib), observed=False)
    pit_df = pd.DataFrame([{"player_id": int(r["ID"]), "sp": _f(r.get("WAA wtd")),
                            "rp": _f(r.get("WAA wtd RP"))} for r in precs])
    hrecs = R.run_hitters(hit, calib, currency=cur, tails=R.live_hitter_tails(calib),
                          fielding=R.live_fielding(calib), park_mode="neutral")
    cols = list(POS_NUM.values()) + ["DH"]
    hit_df = pd.DataFrame([dict({"player_id": int(r["ID"])},
                                **{c: _f(r.get(f"{c} WAA wtd")) for c in cols}) for r in hrecs])
    if "C" in hit_df:
        hit_df["C"] = hit_df["C"] * 600.0 / 500.0           # C WAA is on 500 PA
    return pit_df, hit_df


def season_rows(league, year, calib, static, log):
    adir = os.path.join(HERE, "actuals", league, str(year))
    snap = snapshot_for(league, year)
    if not os.path.isdir(adir):
        log(f"{year}: no banked actuals ({os.path.relpath(adir, VIZ)}); skipped")
        return None
    if not snap:
        log(f"{year}: no ratings snapshot between {year}-04-01 and {year}-09-30; skipped "
            f"(pull one: ingest/statsplus_history.py --league {league} --dates {year}-07-01 --write)")
        return None
    pit_df, hit_df = price(snap, static, calib)
    p = pd.read_csv(os.path.join(adir, "pitching.csv"))
    b = pd.read_csv(os.path.join(adir, "batting.csv"))
    fl = pd.read_csv(os.path.join(adir, "fielding.csv"))
    lid = p[p.level_id == 1].league_id.mode()[0]
    keep = lambda d: d[(d.level_id == 1) & (d.split_id == 1) & (d.league_id == lid) & (d.stint == 0)]
    p, b = keep(p), keep(b)
    fl = fl[(fl.level_id == 1) & (fl.league_id == lid) & (fl.position.isin(POS_NUM))]
    p = p.merge(pit_df, on="player_id", how="left")
    p["year"] = year
    p["role"] = np.where(p.gs >= p.g / 2.0, "SP", "RP")
    p["waa"] = np.where(p.role == "SP", p.sp, p.rp)
    # hitters: engine WAA at the positions played, by fielding innings
    ip = fl.groupby(["player_id", "position"]).ip.sum().reset_index()
    ip["pos"] = ip.position.map(POS_NUM)
    hl = hit_df.melt(id_vars="player_id", var_name="pos", value_name="pw")
    ip = ip.merge(hl, on=["player_id", "pos"], how="left").dropna(subset=["pw"])
    ip = ip[ip.ip > 0]
    pw = ip.groupby("player_id").apply(lambda d: np.average(d.pw, weights=d.ip), include_groups=False)
    b = b.merge(pw.rename("waa_pos").reset_index(), on="player_id", how="left")
    b = b.merge(hit_df[["player_id", "DH"]], on="player_id", how="left")
    b["waa"] = b.waa_pos.fillna(b.DH)
    b["year"] = year
    clubs = p.team_id.nunique()
    log(f"{year}: snapshot {os.path.basename(snap)}, {clubs} clubs; priced coverage "
        f"pitchers {p.loc[p.waa.notna(), 'bf'].sum() / p.bf.sum():.0%} of BF, "
        f"hitters {b.loc[b.waa.notna(), 'pa'].sum() / b.pa.sum():.0%} of PA")
    return p, b, clubs


def fit(x, rate, w, seed=0):
    X = np.c_[np.ones_like(x), x]
    beta = np.linalg.solve((X.T * w) @ X, (X.T * w) @ rate)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(BOOT):
        i = rng.integers(0, len(x), len(x))
        Xi, yi, wi = X[i], rate[i], w[i]
        bs.append(np.linalg.solve((Xi.T * wi) @ Xi, (Xi.T * wi) @ yi)[0])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return beta[0], beta[1], lo, hi


def report(label, p, b, clubs, shipped, log):
    log(f"--- {label}")
    for role, base in (("SP", 800.0), ("RP", 300.0)):
        d = p[p.role == role]
        ident = d.war.sum() / (d.bf.sum() / base)
        dd = d.dropna(subset=["waa"])
        dd = dd[dd.bf >= 50]
        mean_waa = np.average(dd.waa, weights=dd.bf)
        parts = [f"{role}: shipped {shipped.get(role.lower(), float('nan')):.3f}, budget identity {ident:.3f}, "
                 f"mean engine WAA {mean_waa:+.2f}"]
        for col in ("war", "ra9war"):
            a, s, lo, hi = fit(dd.waa.values, dd[col].values / (dd.bf.values / base), dd.bf.values.astype(float))
            parts.append(f"engine-0 {col} {a:.3f} [{lo:.2f}, {hi:.2f}] (slope {s:.2f})")
        log("  " + "; ".join(parts) + f"; n={len(dd)}")
    d = b.dropna(subset=["waa"])
    d = d[d.pa >= 50]
    ident = b.war.sum() / (b.pa.sum() / 600.0)
    a, s, lo, hi = fit(d.waa.values, d.war.values / (d.pa.values / 600.0), d.pa.values.astype(float))
    log(f"  H: shipped {shipped.get('hitter', float('nan')):.3f}, budget identity {ident:.3f}, "
        f"mean engine WAA {np.average(d.waa, weights=d.pa):+.2f}; engine-0 war {a:.3f} [{lo:.2f}, {hi:.2f}] "
        f"(slope {s:.2f}); n={len(d)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True)
    ap.add_argument("--calib", help="engine calibration the app prices the league with (default: the league)")
    ap.add_argument("--seasons", help="comma list (default: every banked season)")
    args = ap.parse_args(argv)
    calib = args.calib or args.league
    log = print
    if args.seasons:
        years = [int(y) for y in args.seasons.split(",")]
    else:
        years = sorted(int(os.path.basename(d)) for d in glob.glob(os.path.join(HERE, "actuals", args.league, "*"))
                       if os.path.basename(d).isdigit())
    with open(os.path.join(VIZ, "engine", "calib", "replacement.json"), encoding="utf-8") as fh:
        ent = json.load(fh).get(args.league) or {}
    shipped = {k: float(ent[k]) for k in ("hitter", "sp", "rp") if k in ent}
    static = static_traits(args.league)
    got = []
    for y in years:
        r = season_rows(args.league, y, calib, static, log)
        if r:
            got.append(r)
            report(str(y), *r, shipped, log)
    if len(got) > 1:
        report("pooled " + ",".join(str(int(r[0].year.iloc[0])) for r in got),
               pd.concat([r[0] for r in got]), pd.concat([r[1] for r in got]), sum(r[2] for r in got), shipped, log)
    if not got:
        log("nothing to check")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
