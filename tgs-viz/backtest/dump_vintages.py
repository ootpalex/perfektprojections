"""
dump_vintages.py - turn OOTP's yearly CSV dumps into ratings-history vintages.

A dump-sourced league (ootp/leagues.json: "source": "dump") is a plain OOTP
league, every team AI-run, simmed year after year with "Export CSV files after
each simulated season" ON. Each dump holds TRUE ratings (no scout noise),
personality on OOTP's 1-200 scale, level, org, birth date, draft data and the
career stats. One dump = one vintage of ratings_history.db, stored with source
"dump". The pull's real_date IS the in-game date of the dump (see dump_date):
the top league's current_date in leagues.csv, else the last played game of
that year in games.csv, else October 1 of the dump year.

    python tgs-viz/backtest/dump_vintages.py --league DEV            # dry run: counts per year
    python tgs-viz/backtest/dump_vintages.py --league DEV --write    # store new years
        [--db PATH] [--dump-dir PATH] [--years 2027,2028] [--scale 20-80|1-100] [--no-mirror]

Idempotent: a year already in the DB for that league is skipped. --write stores,
for every new year:
    ratings_history.db          one pull (source "dump") + one ratings row per player
    <db dir>/vintages/<LG>/raw_<year>.json.gz     the full raw rows (lens inputs)
    <db dir>/vintages/<LG>/<date>_p<id>.csv.gz    the usual vintage mirror (vintage_backup)
    <db dir>/league_scale_<LG>.json               rating scale + personality cutoffs
With the default --db those land in tgs-viz/backtest/. A --db copy keeps every
side file next to that copy: nothing real is touched.

Rows are built in the StatsPlus RAW schema (the keys ingest/statsplus.py
STATSPLUS_TO_SHEET translates), so ratings_db.append_pull() stores them like a
live pull. Extra keys (raw personality numbers, DOB, draft fields, Lev, Org,
Foreign) ride along in the raw file for the lenses.

Personality H / N / L: terciles of the active players of that dump, per trait:
value below the lower tercile = L, above the upper = H, else N. The cutoffs are
printed and stored in league_scale_<LG>.json; the raw 1-200 values stay in
<Trait>Raw keys.

Rating scale: read from the values (dump_source.detect_scale) and stored as
league_scale_<LG>.json {"scale": "20-80" | "1-100", ...}. ratings_db reads it.

LEAGUES ARE SEPARATE: this tool writes one league and never reads another.
"""
import os
import re
import sys
import json
import argparse
import datetime
import statistics
import collections

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
sys.path.insert(0, HERE)
import dump_source as D                                     # noqa: E402

DB_PATH = os.path.join(HERE, "ratings_history.db")

POS = {"1": "P", "2": "C", "3": "1B", "4": "2B", "5": "3B", "6": "SS", "7": "LF", "8": "CF",
       "9": "RF", "10": "DH"}
ROLE = {"11": "SP", "12": "RP", "13": "CL"}
BATS = {"1": "R", "2": "L", "3": "S"}
THROWS = {"1": "R", "2": "L"}
LEVEL_LEV = {1: "MLB", 2: "AAA", 3: "AA", 5: "A-", 6: "R", 7: "FOR", 8: "FOR"}
FOREIGN_LEVELS = (7, 8)

# personality_<col> -> (H/N/L key, raw key), StatsPlus names
PERSONALITY = {"work_ethic": ("WrkEthic", "WrkEthicRaw"), "intelligence": ("Int", "IntRaw"),
               "leader": ("Lead", "LeadRaw"), "loyalty": ("Loy", "LoyRaw"),
               "greed": ("Greed", "GreedRaw"), "play_for_winner": ("PlayForWinner", "PlayForWinnerRaw")}

# players_batting.csv: batting_ratings_<split>_<skill> -> raw key stem
BAT_SKILL = {"contact": "Cntct", "gap": "Gap", "power": "Pow", "eye": "Eye", "strikeouts": "Ks",
             "babip": "BABIP"}
BAT_SPLIT = {"overall": "{}", "vsr": "{}_R", "vsl": "{}_L", "talent": "Pot{}"}
RUN = {"running_ratings_speed": "Speed", "running_ratings_stealing_rate": "StlRt",
       "running_ratings_stealing": "Steal", "running_ratings_baserunning": "Run",
       "batting_ratings_misc_bunt": "SacBunt", "batting_ratings_misc_bunt_for_hit": "BuntHit",
       "batting_ratings_misc_gb_hitter_type": "GBType", "batting_ratings_misc_fb_hitter_type": "FBType"}
# players_pitching.csv
PIT_SKILL = {"stuff": "Stf", "movement": "Mov", "hra": "HRA", "pbabip": "PBABIP", "control": "Ctrl"}
PIT_SPLIT = {"overall": "{}", "vsr": "{}_R", "vsl": "{}_L", "talent": "Pot{}"}
PITCHES = {"fastball": "Fst", "slider": "Sld", "curveball": "Crv", "screwball": "Scr",
           "forkball": "Frk", "changeup": "Chg", "sinker": "Snk", "splitter": "Splt",
           "knuckleball": "Knbl", "cutter": "Cutt", "circlechange": "CirChg", "knucklecurve": "Kncrv"}
PIT_MISC = {"pitching_ratings_misc_velocity": "VelCode", "pitching_ratings_misc_arm_slot": "ArmSlotCode",
            "pitching_ratings_misc_stamina": "Stm", "pitching_ratings_misc_ground_fly": "GB",
            "pitching_ratings_misc_hold": "Hold"}
# players_fielding.csv
FLD = {"fielding_ratings_infield_range": "IFR", "fielding_ratings_infield_arm": "IFA",
       "fielding_ratings_turn_doubleplay": "TDP", "fielding_ratings_outfield_range": "OFR",
       "fielding_ratings_outfield_arm": "OFA", "fielding_ratings_catcher_arm": "CArm",
       "fielding_ratings_catcher_ability": "CBlk", "fielding_ratings_catcher_framing": "CFrm",
       "fielding_ratings_infield_error": "IFE", "fielding_ratings_outfield_error": "OFE"}
FLD_POS = ["P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
# players.csv extras carried in the raw file
PLAYER_EXTRA = {"height": "Height", "weight": "Weight", "free_agent": "FreeAgent",
                "experience": "Experience", "draft_eligible": "DraftEligible", "draft_year": "DraftYear",
                "draft_round": "DraftRound", "draft_pick": "DraftPick", "draft_overall_pick": "DraftOverall",
                "draft_team_id": "DraftTeam", "draft_league_id": "DraftLeague",
                "picked_in_draft": "PickedInDraft", "injury_is_injured": "Injured",
                "injury_career_ending": "CareerEnding", "prone_overall": "ProneRaw",
                "prone_leg": "ProneLegRaw", "prone_back": "ProneBackRaw", "prone_arm": "ProneArmRaw"}


def _int(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- league / team maps
def lev_map(leagues):
    """{league_id: (Lev, foreign)} from leagues.csv. Level 4 (full-season A)
    splits by the age cap in the name: "(U27)" above "(U25)" = A+ over A-;
    two A leagues without caps both read A; one A league reads A+ when a
    level-5 league exists, else A. foreign = the top league of the chain is
    level 7 (indy) or 8 (foreign top)."""
    level, parent, name = {}, {}, {}
    for r in leagues:
        lid = str(r.get("league_id") or "").strip()
        if not lid:
            continue
        level[lid] = _int(r.get("league_level"), -1)
        parent[lid] = str(r.get("parent_league_id") or "0").strip()
        name[lid] = str(r.get("name") or "")

    def top(lid):
        seen = set()
        while parent.get(lid, "0") not in ("0", "") and lid not in seen:
            seen.add(lid)
            lid = parent[lid]
        return lid

    a4 = []
    for lid, lv in level.items():
        if lv == 4:
            m = re.search(r"\(U(\d+)\)", name[lid])
            a4.append((int(m.group(1)) if m else None, lid))
    has5 = any(lv == 5 for lv in level.values())
    lev4 = {}
    if len(a4) >= 2 and all(c is not None for c, _ in a4):
        a4.sort(key=lambda x: -x[0])
        for i, (_c, lid) in enumerate(a4):
            lev4[lid] = "A+" if i == 0 else "A-" if i == len(a4) - 1 else "A"
    elif len(a4) == 1:
        lev4[a4[0][1]] = "A+" if has5 else "A"
    else:
        lev4 = {lid: "A" for _c, lid in a4}
    out = {}
    for lid, lv in level.items():
        lev = lev4.get(lid) if lv == 4 else LEVEL_LEV.get(lv, "-")
        out[lid] = (lev, level.get(top(lid), -1) in FOREIGN_LEVELS)
    return out


def team_maps(teams):
    """({team_id: 'City Nickname'}, {team_id: league_id})."""
    names, lg = {}, {}
    for r in teams:
        tid = str(r.get("team_id") or "").strip()
        if not tid:
            continue
        names[tid] = (str(r.get("name") or "").strip() + " " + str(r.get("nickname") or "").strip()).strip()
        lg[tid] = str(r.get("league_id") or "").strip()
    return names, lg


def terciles(values):
    """[lower, upper] tercile cutoffs of a list of numbers (None when too few)."""
    vals = sorted(v for v in values if v is not None)
    if len(vals) < 3:
        return None
    q = statistics.quantiles(vals, n=3, method="inclusive")
    return [q[0], q[1]]


def hnl(v, cut):
    if cut is None or v is None:
        return None
    return "L" if v < cut[0] else "H" if v > cut[1] else "N"


# ---------------------------------------------------------------- one dump -> raw rows
def build_rows(csv_dir, year):
    """(rows, info) for one dump. rows = raw StatsPlus-schema rows of every
    non-retired player; info = counts, personality cutoffs, scale reading."""
    lg_path, borrowed = D.sibling_file(csv_dir, "leagues.csv")
    if not lg_path:
        raise SystemExit(f"no leagues.csv in any dump under {os.path.dirname(os.path.dirname(csv_dir))}; "
                         f"cannot tell the players' levels")
    leagues = D.read_csv(lg_path)
    # OOTP's yearly export can be PARTIAL (its settings pick the tables): the
    # OOTP 27 "DEV TESTS" first dump had players + ratings + leagues but no
    # teams.csv, players_fielding.csv, players_value.csv or career stats.
    # Everything but players.csv / leagues.csv / the two ratings files is optional;
    # what is missing is reported so the export settings can be fixed.
    have = lambda fn: os.path.isfile(os.path.join(csv_dir, fn))
    missing = [fn for fn in ("teams.csv", "players_fielding.csv", "players_value.csv",
                             "players_career_batting_stats.csv", "players_career_pitching_stats.csv")
               if not have(fn)]
    tm_path, tm_borrowed = D.sibling_file(csv_dir, "teams.csv")
    teams = D.read_csv(tm_path) if tm_path else []
    borrowed_note = [f"leagues.csv from the {borrowed} dump" if borrowed else None,
                     f"teams.csv from the {tm_borrowed} dump" if tm_borrowed else None]
    borrowed_note = [x for x in borrowed_note if x]
    levs = lev_map(leagues)
    lg_level = {str(r.get("league_id")): _int(r.get("league_level"), 0) for r in leagues}
    tname, tleague = team_maps(teams)
    if not tleague and have("team_relations.csv"):          # team -> league without teams.csv
        for tr in D.read_csv(os.path.join(csv_dir, "team_relations.csv")):
            tid, lid = str(tr.get("team_id") or "").strip(), str(tr.get("league_id") or "").strip()
            if tid and lid and tid not in tleague:
                tleague[tid] = lid

    active = lambda r: str(r.get("retired") or "0") == "0"
    players = D.read_csv(os.path.join(csv_dir, "players.csv"), active)
    ids = {r["player_id"] for r in players}
    by_id = lambda fn: {r["player_id"]: r for r in D.read_csv(os.path.join(csv_dir, fn),
                                                                lambda r: r.get("player_id") in ids)}
    bat, pit = by_id("players_batting.csv"), by_id("players_pitching.csv")
    fld = by_id("players_fielding.csv") if have("players_fielding.csv") else {}
    val = by_id("players_value.csv") if have("players_value.csv") else {}

    cuts = {}
    for col, (key, _raw) in PERSONALITY.items():
        cuts[key] = terciles([_int(r.get(f"personality_{col}"), None) for r in players])

    rows = []
    for p in players:
        pid = p["player_id"]
        lid = str(p.get("league_id") or "0").strip()
        tid = str(p.get("team_id") or "0").strip()
        if lid not in levs and tid in tleague:
            lid = tleague[tid]                              # all-star squads carry a negative league id
        org_id = str(p.get("organization_id") or "0").strip()
        de = str(p.get("draft_eligible")) == "1"
        if lid in levs:
            lev, foreign = levs[lid]
        elif org_id in ("", "0"):
            lev, foreign = ("AMA" if de else "FA"), False
        else:
            lev, foreign = "-", False
        pos = POS.get(str(p.get("position")), "-")
        if pos == "P":
            pos = ROLE.get(str(p.get("role")), "SP")
        dob = D.parse_date(p.get("date_of_birth"))
        r = {"ID": pid, "Name": f"{p.get('first_name', '').strip()} {p.get('last_name', '').strip()}".strip(),
             "Pos": pos, "League": lid, "Team": tid,
             "Org": (tname.get(org_id) or f"Org {org_id}") if org_id not in ("", "0") else "",
             "OrgId": org_id, "LgLvl": str(lg_level.get(lid, 0)), "Lev": lev,
             "Foreign": "1" if foreign else "0",
             "Age": p.get("age"), "Bats": BATS.get(str(p.get("bats")), "-"),
             "Throws": THROWS.get(str(p.get("throws")), "-"),
             "DOB": dob.isoformat() if dob else "", "DumpYear": str(year)}
        for col, key in PLAYER_EXTRA.items():
            r[key] = p.get(col, "")
        for col, (key, raw_key) in PERSONALITY.items():
            v = _int(p.get(f"personality_{col}"), None)
            r[raw_key] = v
            r[key] = hnl(v, cuts[key])
        b = bat.get(pid)
        if b:
            for split, fmt in BAT_SPLIT.items():
                for skill, stem in BAT_SKILL.items():
                    r[fmt.format(stem)] = b.get(f"batting_ratings_{split}_{skill}")
            for col, key in RUN.items():
                r[key] = b.get(col)
        q = pit.get(pid)
        if q:
            for split, fmt in PIT_SPLIT.items():
                for skill, stem in PIT_SKILL.items():
                    r[fmt.format(stem)] = q.get(f"pitching_ratings_{split}_{skill}")
            for pitch, stem in PITCHES.items():
                r[stem] = q.get(f"pitching_ratings_pitches_{pitch}")
                r["Pot" + stem] = q.get(f"pitching_ratings_pitches_talent_{pitch}")
            for col, key in PIT_MISC.items():
                r[key] = q.get(col)
        f = fld.get(pid)
        if f:
            for col, key in FLD.items():
                r[key] = f.get(col)
            for i, key in enumerate(FLD_POS, start=1):
                r[key] = f.get(f"fielding_rating_pos{i}")
                r["Pot" + key] = f.get(f"fielding_rating_pos{i}_pot")
        v = val.get(pid)
        if v:
            r["Ovr"] = v.get("oa_rating")
            r["Pot"] = v.get("pot_rating")
        rows.append(r)

    scale, sstats = D.detect_scale(rows)
    info = {"players": len(rows),
            "pitchers": sum(1 for r in rows if r["Pos"] in ("SP", "RP", "CL")),
            "with_org": sum(1 for r in rows if r["Org"]),
            "foreign": sum(1 for r in rows if r["Foreign"] == "1"),
            "lev": dict(collections.Counter(r["Lev"] for r in rows).most_common()),
            "personality_cutoffs": cuts,
            "personality_split": {key: dict(collections.Counter(r[key] for r in rows))
                                  for _c, (key, _r) in PERSONALITY.items()},
            "scale": scale, "scale_stats": sstats,
            "missing_files": missing, "borrowed": borrowed_note,
            "leagues": {lid: {"lev": lv[0], "foreign": lv[1]} for lid, lv in levs.items()}}
    return rows, info


# ---------------------------------------------------------------- main
# A dump folder written to in the last SETTLE_MINUTES is skipped (2026-09-25):
# OOTP may still be writing it while the user sims, and banking it then would
# store a half-written season. The next run picks it up once it has settled.
SETTLE_MINUTES = 10


def newest_write(csv_dir):
    """Newest file modification time (epoch seconds) in one dump folder."""
    folder = os.path.dirname(csv_dir)
    newest = 0.0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return newest


def ingest(league, db_path=DB_PATH, dump_root=None, years=None, write=False,
           force_scale=None, mirror=True, log=print):
    prof = D.profile(league)
    if dump_root is None:
        if prof["source"] != D.DUMP_SOURCE:
            log(f"{league}: profile in ootp/leagues.json has no \"source\": \"dump\" and no --dump-dir given")
            raise SystemExit(2)
        dump_root = D.league_dir(league, prof)
        if not dump_root:
            log(f"{league}: league folder '{prof['league']}.lg' not found for OOTP {prof['game']}")
            raise SystemExit(2)
    dirs = D.dump_dirs(dump_root)
    if not dirs:
        log(f"{league}: no dump_<year>_yearly/csv/players.csv under {dump_root}")
        log("  (in OOTP: Game Settings -> Export CSV files after each simulated season must be ON, then sim a season)")
        raise SystemExit(3)
    if years:
        dirs = {y: d for y, d in dirs.items() if y in years}
    import time as _time
    cutoff = _time.time() - SETTLE_MINUTES * 60
    fresh = [y for y, d in dirs.items() if newest_write(d) > cutoff]
    if fresh:
        log(f"{league}: skipping dump {', '.join(str(y) for y in fresh)}: written in the last "
            f"{SETTLE_MINUTES} minutes, OOTP may still be writing it (the next run banks it)")
        dirs = {y: d for y, d in dirs.items() if y not in fresh}

    import ratings_db as R
    conn = R.connect(db_path)
    try:
        have = D.stored_dump_years(conn, league)
        used_dates = {v[1]: y for y, v in have.items()}
        other = [r[0] for r in conn.execute(
            "SELECT DISTINCT source FROM pulls WHERE league=? AND source<>?", (league, D.DUMP_SOURCE))]
    finally:
        conn.close()
    if other:
        log(f"{league}: this league already has pulls of source {other} in {db_path}; "
            f"a dump league must hold dump pulls only. Nothing done.")
        raise SystemExit(2)
    db_dir = os.path.dirname(os.path.abspath(db_path))
    vint_dir = os.path.join(db_dir, "vintages")
    raw_dir = os.path.join(vint_dir, league)
    meta = D.read_scale(db_path, league) or {}
    log(f"{league}: dumps {', '.join(str(y) for y in dirs)} under {dump_root}")
    log(f"  db {db_path}  ({len(have)} dump vintages stored"
        + (": " + ", ".join(str(y) for y in sorted(have)) if have else "") + ")")

    done = []
    scale_by_year = dict(meta.get("scale_by_year") or {})
    detected = dict(meta.get("detected") or {})
    cutoffs = dict(meta.get("personality_cutoffs") or {})
    dump_dates = dict(meta.get("dump_dates") or {})
    for year, csv_dir in dirs.items():
        if year in have:
            log(f"  {year}: already stored (pull {have[year][0]}, {have[year][1]}); skipped")
            continue
        date, how = D.dump_date(csv_dir, year)
        real_date = date.isoformat()
        if real_date in used_dates:
            log(f"  {year}: its in-game date {real_date} is already used by the {used_dates[real_date]} "
                f"vintage; skipped")
            continue
        rows, info = build_rows(csv_dir, year)
        levtxt = ", ".join(f"{k} {n}" for k, n in info["lev"].items())
        log(f"  {year}: in-game {real_date} ({how}); {info['players']} active players "
            f"({info['pitchers']} pitchers), {info['with_org']} with an org, {info['foreign']} foreign/indy")
        log(f"        levels: {levtxt}")
        if info.get("borrowed"):
            log(f"        borrowed: {'; '.join(info['borrowed'])} (OOTP 27 writes a different table set each year)")
        if info.get("missing_files"):
            log(f"        not in this dump: {', '.join(info['missing_files'])}"
                + (" (season totals come from the per-game files)" if "players_career_batting_stats.csv" in info["missing_files"] else ""))
        st = info["scale_stats"]
        log(f"        scale: {info['scale']} (max {st['max']}, off-5-grid share {st['off5_share']}, "
            f"below-20 share {st['below20_share']}, {st['n']} values)"
            + (f"  [forced to {force_scale}]" if force_scale else ""))
        cut_txt = ", ".join(f"{k} L<{c[0]:g} H>{c[1]:g}" if c else f"{k} -"
                            for k, c in info["personality_cutoffs"].items())
        log(f"        personality terciles: {cut_txt}")
        scale_by_year[str(year)] = force_scale or info["scale"]
        detected[str(year)] = st
        cutoffs[str(year)] = info["personality_cutoffs"]
        dump_dates[str(year)] = {"date": real_date, "how": how}
        if not write:
            continue
        raw_path = os.path.join(raw_dir, f"raw_{year}.json.gz")
        D.write_raw_rows(raw_path, rows)
        pull_id = R.append_pull(league, rows, source=D.DUMP_SOURCE, real_ts=f"{real_date}T00:00:00",
                                real_date=real_date, files=[csv_dir, raw_path], db_path=db_path)
        used_dates[real_date] = year
        log(f"        stored: pull {pull_id}, raw rows -> {os.path.relpath(raw_path, db_dir)}")
        done.append((year, pull_id))

    if not write:
        log(f"  dry run: {len(scale_by_year) - len(have)} new year(s) would be stored; re-run with --write")
        return []
    if scale_by_year:
        newest = max(scale_by_year, key=int)
        scale = scale_by_year[newest]
        if len(set(scale_by_year.values())) > 1:
            log(f"  WARNING: the dumps do not agree on the scale {scale_by_year}; using the newest ({scale})")
        D.write_json(D.scale_path(db_path, league), {
            "league": league, "source": D.DUMP_SOURCE, "scale": scale,
            "forced": bool(force_scale), "scale_by_year": scale_by_year, "detected": detected,
            "scale_rule": (f"1-100 when more than {D.OFF5_SHARE:.0%} of the rated values sit off the "
                           f"5-step grid or more than {D.BELOW20_SHARE:.0%} sit below 20; else 20-80"),
            "personality_cutoffs": cutoffs,
            "personality_rule": ("terciles of the dump's active players per trait: below the lower "
                                 "tercile = L, above the upper = H, else N; raw 1-200 values in "
                                 "<Trait>Raw"),
            "dump_root": dump_root, "dump_dates": dump_dates,
            "date_rule": ("real_date = in-game date of the dump: the top league's current_date in "
                          "leagues.csv, else the last played game of the year in games.csv, else "
                          "October 1"),
            "updated": datetime.datetime.now().isoformat(timespec="seconds")}, indent=1, sort_keys=True)
        log(f"  scale file: {D.scale_path(db_path, league)} -> {scale}")
    if done and mirror:
        import vintage_backup as VB
        VB.export(db_path=db_path, out_dir=vint_dir)
    log(f"  stored {len(done)} new vintage(s) for {league}")
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True, help="league id, e.g. DEV (profile key in ootp/leagues.json)")
    ap.add_argument("--write", action="store_true", help="store the new years (default: dry run)")
    ap.add_argument("--db", default=DB_PATH, help="ratings_history.db path (side files land next to it)")
    ap.add_argument("--dump-dir", help="a .lg folder, its dump/ folder, or one dump_<year>_yearly folder")
    ap.add_argument("--years", help="comma list of dump years to consider, e.g. 2025,2026")
    ap.add_argument("--scale", choices=list(D.SCALES), help="override the detected rating scale")
    ap.add_argument("--no-mirror", action="store_true", help="skip the vintage_backup csv.gz mirror")
    a = ap.parse_args()
    years = None
    if a.years:
        years = {int(y) for y in re.split(r"[,\s]+", a.years.strip()) if y}
    ingest(a.league, db_path=a.db, dump_root=a.dump_dir, years=years, write=a.write,
           force_scale=a.scale, mirror=not a.no_mirror)


if __name__ == "__main__":
    main()
