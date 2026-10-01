"""
export_league.py - put an OOTP save that is not on StatsPlus into the app from
its "export database to CSV" folder (<save>.lg/import_export/csv).

User, 2026-09-27: "just made a new league for fun and exported the database csv
can we add it into the app. it should be the same settings as BLM as far as
statistically. Would like to use the app to practice IDing talent and
developing" (OOTP 27 save "Regular Game").

The export is the same OOTP database format as the DEV league's yearly dumps,
so the DEV loader (backtest/dump_vintages.build_rows) turns it into rows in the
StatsPlus ratings schema; from there it is the BLM pull path of refresh.py:
translate_rows -> engine with the calibration league's constants and live
layers (currency, hitter tails, fielding curves, S-curves, role stuff; the
role-stuff table of the calibration league's own players is never applied,
the ids belong to another universe) -> hitters.json / pitchers.json. Contracts,
injury status and service time come from players_contract.csv and
players_roster_status.csv (the same OOTP columns StatsPlus serves).

Levels: MLB / AAA / AA from the league levels; full-season A (level 4) splits
by league name into High-A (A+: Northwest, South Atlantic, Midwest) and Low-A
(A-: California, Carolina, Florida State), or by an "(U27)" / "(U25)" age cap
in the name; complex / rookie leagues (level 6) read R+ as in BLM; foreign
leagues are dropped (as TGS drops NPB / KBO).

Draft board: OOTP's database export marks this year's class with
draft_eligible (Regular Game, 2026 preseason: 1,319 players, 1,211 college,
ages mostly 19-23; not the whole amateur pool the StatsPlus flag marks), so
hitters_draft / pitchers_draft are those players' rows. *_draft_all adds the
players drafted this season, stamped DraftedOverall / DraftedRound /
DraftedTeam (the Mock Draft's full class). NAT comes from nations.csv.
International amateurs: unsigned (no org), not draft-eligible, age 18 or
under, from a nation outside the draft countries (the nations of this year's
draft class) -> iafa.json (ID, Name, POS, Age, NAT). Signing demand and
signability are not in the database export; when the IAFA screen is exported
to <save>.lg/import_export/mlb_transactions_free_agents_-_international_
amateur_fa_fa_screen.csv its DEM / Sign are merged in by ID.

Archive: with --write the export's rows go into the ratings archive
(backtest/ratings_history.db) as one snapshot of this league, dated by the
game date (leagues.csv current_date); loading the same export again replaces
that snapshot, a later export adds one. The raw rows are kept under
ingest/.cache/history/export_<league>_<game date>.json, the vintage mirror is
refreshed and the league's rating_trends.json rebuilt. This is what dev
signals (growth between exports) and the ML scores read: the league's
leagues.json entry carries "basis": <calib>, so backtest/ml scores it with
that basis' models (common.extra_leagues).

Writes public/data/<LEAGUE>/hitters.json, pitchers.json, the draft files,
iafa.json (all with *_park.json copies where the app reads them: an exported
league has no park blend, so both bases are neutral), metadata.json, and
registers the league in public/data/leagues.json.

Usage:
  python tgs-viz/ingest/export_league.py --league RG --name "Regular Game" --save "Regular Game" [--write]
Options: --calib BLM (engine calibration league), --game 27 (OOTP version),
--csv-dir PATH (instead of the save's import_export/csv).
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
sys.path.insert(0, HERE)
sys.path.insert(0, VIZ)
sys.path.insert(0, os.path.join(VIZ, "backtest"))
import ratings as R          # noqa: E402
import statsplus as S        # noqa: E402
import extract_data as X     # noqa: E402
import offline_league as OL  # noqa: E402
import dump_vintages as DV   # noqa: E402
import dump_source as D      # noqa: E402
sys.path.insert(0, os.path.join(VIZ, "tools"))
import settings as ST        # noqa: E402

DATA_DIR = os.path.join(VIZ, "public", "data")
RESERVED = {"TGS", "BLM", "DEV"}
HIGH_A = ("northwest", "south atlantic", "midwest")
LOW_A = ("california", "carolina", "florida state")


def csv_dir_for(save, game):
    """<save>.lg/import_export/csv in the version's saved_games folder: the
    settings folder (ootp.installs.<game>) when set, else Documents."""
    saved = ST.saved_games(game) or os.path.join(os.path.expanduser("~"), "Documents",
                                                 "Out of the Park Developments", f"OOTP Baseball {game}",
                                                 "saved_games")
    return os.path.join(saved, f"{save}.lg", "import_export", "csv")


def read_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def level4_split(leagues):
    """{league_id: 'A+' / 'A-'} for full-season A leagues, by name (real MLB
    High-A / Low-A) or by an age cap; None for a league it cannot place."""
    out = {}
    for r in leagues:
        if str(r.get("league_level")) != "4":
            continue
        name = str(r.get("name") or "").lower()
        m = re.search(r"\(u(\d+)\)", name)
        if any(k in name for k in HIGH_A):
            out[str(r["league_id"])] = "A+"
        elif any(k in name for k in LOW_A):
            out[str(r["league_id"])] = "A-"
        elif m:
            out[str(r["league_id"])] = "A+" if int(m.group(1)) >= 26 else "A-"
    return out


def game_date(leagues):
    """In-game date of the export: the top league's current_date (ISO)."""
    top = [r for r in leagues if str(r.get("parent_league_id") or "0") in ("0", "")]
    for r in top or leagues:
        d = D.parse_date(r.get("current_date"))
        if d:
            return d.isoformat()
    return None


def season_year(leagues):
    top = [r for r in leagues if str(r.get("parent_league_id") or "0") in ("0", "")]
    for r in top or leagues:
        y = str(r.get("season_year") or "").strip()
        if y.isdigit():
            return int(y)
        d = D.parse_date(r.get("current_date"))
        if d:
            return d.year
    return None


IAFA_SCREEN = "mlb_transactions_free_agents_-_international_amateur_fa_fa_screen.csv"


def draft_and_iafa(cdir, year, hrecs, precs):
    """(draft hitters, draft pitchers, draft_all hitters, draft_all pitchers,
    iafa list) from the export's players.csv and the priced records."""
    pl = {r["player_id"]: r for r in read_csv(os.path.join(cdir, "players.csv")) if r.get("retired") == "0"}
    nations = {}
    if os.path.isfile(os.path.join(cdir, "nations.csv")):
        for n in read_csv(os.path.join(cdir, "nations.csv")):
            nations[str(n.get("nation_id"))] = (n.get("abbreviation") or n.get("short_name") or n.get("name") or "").strip()
    teams = {}
    if os.path.isfile(os.path.join(cdir, "teams.csv")):
        for t in read_csv(os.path.join(cdir, "teams.csv")):
            teams[str(t.get("team_id"))] = (str(t.get("name") or "") + " " + str(t.get("nickname") or "")).strip()
    eligible = {pid for pid, r in pl.items() if str(r.get("draft_eligible")) == "1"}
    drafted = {pid: r for pid, r in pl.items()
               if str(r.get("draft_year")) == str(year) and str(r.get("draft_team_id") or "0") not in ("0", "")}
    draft_nations = {str(pl[pid].get("nation_id")) for pid in eligible}

    def stamp(rec, full=False):
        r = dict(rec)
        src = pl.get(str(rec.get("ID")))
        if src:
            r["NAT"] = nations.get(str(src.get("nation_id")), "")
            if full and str(rec.get("ID")) in drafted:
                r["DraftedOverall"] = int(float(src.get("draft_overall_pick") or 0)) or None
                r["DraftedRound"] = int(float(src.get("draft_round") or 0)) or None
                r["DraftedTeam"] = teams.get(str(src.get("draft_team_id")), "")
        return r

    dh = [stamp(r) for r in hrecs if str(r.get("ID")) in eligible]
    dp = [stamp(r) for r in precs if str(r.get("ID")) in eligible]
    ah = [stamp(r, True) for r in hrecs if str(r.get("ID")) in eligible or str(r.get("ID")) in drafted]
    apl = [stamp(r, True) for r in precs if str(r.get("ID")) in eligible or str(r.get("ID")) in drafted]

    screen = {}
    spath = os.path.join(os.path.dirname(cdir), IAFA_SCREEN)
    if os.path.isfile(spath):
        with open(spath, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                pid = str(r.get("ID") or "").strip()
                if pid:
                    screen[pid] = r
    iafa = []
    for rec in hrecs + precs:
        pid = str(rec.get("ID"))
        src = pl.get(pid)
        if not src or pid in eligible:
            continue
        if str(src.get("organization_id") or "0") not in ("0", ""):
            continue
        try:
            age = int(float(src.get("age")))
        except (TypeError, ValueError):
            continue
        in_screen = pid in screen
        if not in_screen and (age > 18 or str(src.get("nation_id")) in draft_nations):
            continue
        sc = screen.get(pid, {})
        iafa.append({"ID": pid, "Name": rec.get("Name"), "POS": rec.get("POS"), "Age": str(age),
                     "NAT": nations.get(str(src.get("nation_id")), ""),
                     "DEM": (sc.get("DEM") or "").strip() or None, "Sign": (sc.get("Sign") or "").strip() or None})
    return dh, dp, ah, apl, iafa, bool(screen)


def write_json(records, path, overwrite):
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    target = path if overwrite else path.replace(".json", "_export.json")
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False)
    ST.replace_retry(tmp, target)          # retried while a reader holds the file
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--league", required=True, help="app league id, e.g. RG")
    ap.add_argument("--name", help="display name in the app's league picker")
    ap.add_argument("--save", help="OOTP save folder name without .lg (e.g. 'Regular Game')")
    ap.add_argument("--game", default="27")
    ap.add_argument("--calib", default="BLM", choices=["BLM", "TGS"])
    ap.add_argument("--csv-dir")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    lg = a.league.strip().upper()
    if lg in RESERVED or not re.fullmatch(r"[A-Z0-9]{2,8}", lg):
        raise SystemExit(f"league id must be 2-8 letters / digits and not one of {sorted(RESERVED)}")
    cdir = a.csv_dir or (csv_dir_for(a.save, a.game) if a.save else None)
    if not cdir or not os.path.isfile(os.path.join(cdir, "players.csv")):
        raise SystemExit(f"no players.csv in {cdir!r}: export the database to CSV in OOTP "
                         "(File > Export > Database to CSV) and pass --save or --csv-dir")
    leagues = read_csv(os.path.join(cdir, "leagues.csv"))
    year = season_year(leagues)
    print(f"{lg}: export {cdir}; season {year}; engine calibration {a.calib}")

    rows, info = DV.build_rows(cdir, year)
    print(f"  {info['players']} active players ({info['pitchers']} pitchers), rating scale {info['scale']}; "
          f"missing files: {info['missing_files'] or 'none'}")
    if info["scale"] != "20-80":
        raise SystemExit("the engine is calibrated on the 20-80 display scale; set the save's ratings "
                         "scale to 20-80 in OOTP and export again")
    split = level4_split(leagues)
    for r in rows:
        if str(r.get("LgLvl")) == "4" and r.get("League") in split:
            r["Lev"] = split[r["League"]]
        elif str(r.get("LgLvl")) == "6":
            r["Lev"] = "R+"
    before = len(rows)
    rows = [r for r in rows if r.get("Foreign") != "1"]
    print(f"  dropped {before - len(rows)} players on foreign-league rosters")
    for r in rows:                       # the app's convention: ORG = name, Org = id
        r["ORG"] = r.get("Org") or ""
        r["Org"] = r.get("OrgId") or "0"
    from collections import Counter
    print("  levels:", dict(Counter(r["Lev"] for r in rows).most_common()))

    trows = S.translate_rows(rows)
    is_pit = lambda r: str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
    hit_rows = [r for r in trows if not is_pit(r)]
    pit_rows = [r for r in trows if is_pit(r)]
    cal = a.calib
    hrecs = R.run_hitters(hit_rows, cal, currency=R.live_currency(cal), tails=R.live_hitter_tails(cal),
                          fielding=R.live_fielding(cal), park_mode="neutral")
    precs = R.run_pitchers(pit_rows, cal, scurves=R.live_scurves(cal), currency=R.live_currency(cal),
                           park_mode="neutral", role_stuff=R.live_role_stuff(cal), observed=False)
    print(f"  priced {len(hrecs)} hitters, {len(precs)} pitchers")

    # contracts + injury / service status (OOTP columns = StatsPlus /contract, /players)
    contracts = read_csv(os.path.join(cdir, "players_contract.csv")) if os.path.isfile(
        os.path.join(cdir, "players_contract.csv")) else []
    status = {r["player_id"]: r for r in read_csv(os.path.join(cdir, "players_roster_status.csv"))} if os.path.isfile(
        os.path.join(cdir, "players_roster_status.csv")) else {}
    pl = {r["player_id"]: r for r in read_csv(os.path.join(cdir, "players.csv"))}
    pmap = {}
    for pid, p in pl.items():
        m = dict(status.get(pid, {}))
        m["ID"] = pid
        m["draft_eligible"] = p.get("draft_eligible")
        pmap[pid] = m
    cmap = {str(c.get("player_id")): c for c in contracts}
    n_priced = S.attach_contract_injury(hrecs, cmap, pmap) + S.attach_contract_injury(precs, cmap, pmap)
    print(f"  contracts: {n_priced} players carry a salary")

    out_dir = os.path.join(DATA_DIR, lg)
    os.makedirs(out_dir, exist_ok=True)
    dh, dp, ah, apl, iafa, have_screen = draft_and_iafa(cdir, year, hrecs, precs)
    print(f"  draft class: {len(dh)} hitters, {len(dp)} pitchers (+ {len(ah) + len(apl) - len(dh) - len(dp)} "
          f"drafted this season in the *_draft_all files); international amateurs: {len(iafa)}"
          f"{' (demand / signability from the IAFA screen export)' if have_screen else ''}")
    for name, recs in (("hitters", hrecs), ("pitchers", precs), ("hitters_draft", dh), ("pitchers_draft", dp),
                       ("hitters_draft_all", ah), ("pitchers_draft_all", apl)):
        t = write_json(recs, os.path.join(out_dir, f"{name}.json"), a.write)
        t2 = write_json(recs, os.path.join(out_dir, f"{name}_park.json"), a.write)
        print(f"  {name}: {len(recs)} -> {os.path.relpath(t, REPO)} (+ {os.path.basename(t2)})")
    t = write_json(iafa, os.path.join(out_dir, "iafa.json"), a.write)
    print(f"  iafa: {len(iafa)} -> {os.path.relpath(t, REPO)}")
    if not a.write:
        print("(dry run: *_export.json side files only; add --write to go live)")
        return
    # ---- archive snapshot (one per game date), vintage mirror, rating trends
    gd = game_date(leagues)
    if gd:
        import ratings_db as RDB
        import vintage_backup as VB
        hist = os.path.join(HERE, ".cache", "history")
        os.makedirs(hist, exist_ok=True)
        raw_path = os.path.join(hist, f"export_{lg.lower()}_{gd}.json")
        with open(raw_path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        os.replace(raw_path + ".tmp", raw_path)
        pull_id = RDB.append_pull(lg, rows, source="live", real_date=gd, real_ts=f"{gd}T00:00:00",
                                  files=[os.path.relpath(raw_path, REPO)], game_date=gd)
        print(f"  archive: snapshot of game date {gd} -> pull {pull_id} (league {lg})")
        # a re-load of the same export replaced the snapshot: drop the mirror
        # file of the replaced pull so the backup never restores it twice
        vdir = os.path.join(VIZ, "backtest", "vintages", lg)
        if os.path.isdir(vdir):
            for fn in os.listdir(vdir):
                if fn.startswith(f"{gd}_p") and fn.endswith(".csv.gz") and fn != f"{gd}_p{pull_id}.csv.gz":
                    os.remove(os.path.join(vdir, fn))
                    print(f"  removed the replaced snapshot's mirror file {fn}")
        try:
            VB.export(leagues=[lg])
        except Exception as e:                      # the mirror is a backup; never fatal
            print(f"  WARNING: vintage mirror not refreshed ({type(e).__name__}: {e})")
        try:
            RDB.export(leagues=[lg])
            print(f"  rating trends: public/data/{lg}/rating_trends.json")
        except Exception as e:
            print(f"  WARNING: rating trends not rebuilt ({type(e).__name__}: {e})")
    else:
        print("  WARNING: no current_date in leagues.csv: the export was not archived (no dev signals)")

    meta = OL.build_metadata(lg, os.path.abspath(cdir), cal, hrecs, precs)
    meta["source"] = {"kind": "OOTP database export", "csv_dir": os.path.abspath(cdir), "season": year,
                      "calibration": cal, "built": time.strftime("%Y-%m-%d %H:%M")}
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    entry = X.build_manifest_entry(lg, name=a.name or lg)
    entry.update({"basis": cal, "source": "OOTP database export", "save": a.save or os.path.abspath(cdir)})
    X.upsert_manifest(os.path.join(DATA_DIR, "leagues.json"), [entry])
    print(f"  registered {lg} ('{entry['name']}') in public/data/leagues.json: "
          f"features {[k for k, v in entry['features'].items() if v]}")


if __name__ == "__main__":
    main()
