"""
Bank a season's ACTUAL stats from the public StatsPlus per-player stats APIs.

Pulls batting + pitching + fielding for one season and writes them as CSVs with
the exact server headers, preserving the raw split/stint rows (split_id 1=overall,
2=vsL, 3=vsR, 21=playoffs; stint rows have stint>0) — downstream aggregates.

Run this at each season end, before the new season starts. No OOTP needed —
these endpoints are public (no auth).

Usage:
  python tgs-viz/backtest/fetch_actuals.py --league TGS [--slug tgs] [--year 2044] [--levels mlb|all] --write

  --league   folder name under backtest/actuals/ (TGS, BLM)
  --slug     StatsPlus slug (default: lowercased league)
  --year     season to bank (default: current in-game year via /date)
  --levels   mlb = top-level MLB only (level 1 in /lgdata; excludes NPB/foreign);
             all = every league id in /lgdata  (default: mlb)
  --write    actually write (otherwise dry run: fetch + print counts only)

Output: tgs-viz/backtest/actuals/<LEAGUE>/<year>/{batting,pitching,fielding}.csv
Idempotent: re-running overwrites, after saving a timestamped .bak of the old file.
All three feeds are downloaded and checked before any file is moved or written.

StatsPlus requests carry the league's saved token on their own (statsplus.py).

Exit codes:
  0  banked, or skipped because the season is still in progress
  3  StatsPlus refused a request, or sent something that is not the data (or no
     rows in one or more feeds). Nothing was moved or written.
  4  StatsPlus could not be reached (or sent an address on another site).
     Nothing was moved or written.
"""
import argparse, csv, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ingest"))
import statsplus as sp  # noqa: E402

EXIT_REFUSED = 3      # StatsPlus refused, or its reply was not the data
EXIT_NETWORK = 4      # StatsPlus could not be reached


def season_complete(game_date, year):
    """Is `year`'s REGULAR SEASON complete as of the in-game date?
    MLB-style calendar heuristic: a later year, or Oct 1+ of the same year
    (playoffs may still be running — regular-season stats are final)."""
    gy, gm = int(game_date[:4]), int(game_date[5:7])
    return gy > year or (gy == year and gm >= 10)


def discover_lids(base, levels):
    """League ids to pull, from /lgdata. 'mlb' = level 1 (the true top-level MLB;
    excludes foreign primaries like TGS's JPBO which sits at level 8)."""
    leagues = sp.fetch_lgdata(base)
    if levels == "all":
        lids = [lg["league_id"] for lg in leagues]
    else:
        lids = [lg["league_id"] for lg in leagues if lg.get("level") == 1]
    if not lids:
        raise SystemExit(f"no league ids found in {base}/lgdata/ for levels={levels}")
    names = {lg["league_id"]: lg.get("abbr") or lg.get("name") for lg in leagues}
    print(f"  leagues ({levels}): " + ", ".join(f"{i}={names.get(i, '?')}" for i in lids))
    return lids


def write_rows(path, rows):
    """Write dict rows back out with the exact server header (key order of row 1)."""
    if os.path.exists(path):
        bak = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        os.replace(path, bak)
        print(f"  (old file saved as {os.path.basename(bak)})")
    with open(path, "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def stop(league, why, code):
    """Print why nothing was banked, then exit with code."""
    print(f"[{league}] {why}")
    print("  Nothing was banked: no file was moved or written.")
    sys.exit(code)


def main():
    ap = argparse.ArgumentParser(description="Bank a season's actual stats from StatsPlus")
    ap.add_argument("--league", required=True, help="TGS or BLM (folder name)")
    ap.add_argument("--slug", default=None, help="StatsPlus slug (default: lowercased --league)")
    ap.add_argument("--year", type=int, default=None, help="season year (default: current in-game year)")
    ap.add_argument("--levels", choices=("mlb", "all"), default="mlb")
    ap.add_argument("--allow-partial", action="store_true",
                    help="override the completed-seasons-only rule (analysis previews only)")
    ap.add_argument("--write", action="store_true", help="write CSVs (otherwise dry run)")
    a = ap.parse_args()

    league = a.league.upper()
    base = sp.normalize_base(a.slug or league.lower())
    try:
        game_date = sp.fetch_date(base)
    except sp.StatsPlusRefused as e:
        stop(league, e.user_message(league), EXIT_REFUSED)
    except sp.OffSiteError as e:
        stop(league, f"StatsPlus sent an address on another site ({e}).", EXIT_NETWORK)
    except OSError as e:
        stop(league, f"StatsPlus could not be reached ({type(e).__name__}: {e}). Try again in a minute.",
             EXIT_NETWORK)
    year = a.year or int(game_date[:4])
    complete = season_complete(game_date, year)
    print(f"[{league}] {base}  in-game date {game_date}  banking season {year}")
    if not complete and not a.allow_partial:
        # HARD RULE (user-set): the actuals folders hold COMPLETED seasons only.
        # Mid-season data never lands here — metadata and backtest scoring both
        # require full seasons, and a partial on disk is a trap waiting to be read.
        print(f"  SKIPPED: {year} is still in progress as of {game_date}.")
        print(f"  Re-run at season end (the stats stay fetchable — nothing is lost by waiting).")
        return

    out_dir = os.path.join(HERE, "actuals", league, str(year))
    pulls = [("batting", sp.fetch_batting), ("pitching", sp.fetch_pitching), ("fielding", sp.fetch_fielding)]
    # Every feed is downloaded and checked BEFORE any file is touched: a refusal
    # half way must not leave a good season file moved to .bak.
    got = []
    try:
        lids = discover_lids(base, a.levels)
        for name, fn in pulls:
            rows = fn(base, year=year, lids=lids)  # no split filter: keep ALL split/stint rows
            players = {r.get("player_id") for r in rows}
            print(f"  {name:<9}: {len(rows):>6} rows   {len(players):>5} distinct players")
            if not rows:
                print(f"  WARNING: {name} came back empty (HTTP 204?) — nothing to write")
            got.append((name, rows))
    except sp.StatsPlusRefused as e:
        stop(league, e.user_message(league), EXIT_REFUSED)
    except sp.OffSiteError as e:
        stop(league, f"StatsPlus sent an address on another site ({e}).", EXIT_NETWORK)
    except OSError as e:
        stop(league, f"StatsPlus could not be reached ({type(e).__name__}: {e}). Try again in a minute.",
             EXIT_NETWORK)
    if not any(rows for _name, rows in got):
        stop(league, f"StatsPlus sent no {year} stats at all (every feed was empty).", EXIT_REFUSED)
    empty = [name for name, rows in got if not rows]
    if empty:
        # A season bank needs all three feeds: banking two would move the good
        # copies of those to .bak and leave the third file from an older bank.
        stop(league, f"StatsPlus sent no {year} {' or '.join(empty)} rows, but the other feeds have rows. "
                     f"A season is banked only with all three feeds; try again later.", EXIT_REFUSED)
    for name, rows in got:
        if rows and a.write:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{name}.csv")
            write_rows(path, rows)
            print(f"  wrote {path}")
    if a.write:
        # Completeness marker: anything scoring/recalibrating from this folder MUST
        # check this first — a mid-season bank is a preview, not the season.
        meta = {
            "league": league, "year": year, "in_game_date": game_date,
            "season_complete": complete,
            "banked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        print(f"  meta.json: season_complete={complete}")
    else:
        print("  (dry run — pass --write to save)")


if __name__ == "__main__":
    main()
