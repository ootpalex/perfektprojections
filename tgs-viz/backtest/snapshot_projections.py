"""
Snapshot the CURRENT projections so they can be scored against actuals later.

Copies public/data/<LEAGUE>/hitters.json + pitchers.json + metadata.json and the
raw ratings-pull cache (ingest/.cache/statsplus_<slug>.json) into a dated folder:

  tgs-viz/backtest/snapshots/<LEAGUE>/<in-game-date>/

The folder is named for the IN-GAME date (via the public /date endpoint), so a
snapshot taken at the end of 2044 lands under e.g. 2044-10-08/. An existing
snapshot dir is never silently overwritten — a -2 / -3 suffix is appended.
Each snapshot carries a manifest.json (what was snapped, real-world timestamp,
in-game date).

Usage:
  python tgs-viz/backtest/snapshot_projections.py --league TGS [--slug tgs] --write

StatsPlus requests carry the league's saved token on their own (statsplus.py).
Exit codes: 3 = StatsPlus refused /date or sent something that is not a date;
4 = StatsPlus could not be reached. In both cases nothing is snapped (the folder
name needs the in-game date).
"""
import argparse, datetime, json, os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "ingest"))
import statsplus as sp  # noqa: E402

VIZ = os.path.dirname(HERE)  # tgs-viz/
EXIT_REFUSED = 3      # StatsPlus refused /date, or the reply was not a date
EXIT_NETWORK = 4      # StatsPlus could not be reached


def snapshot_dir(league, game_date):
    """Dated dir under snapshots/<LEAGUE>/; refuse to reuse an existing one."""
    safe = re.sub(r"[^0-9A-Za-z_-]+", "-", game_date.strip()) or "unknown-date"
    root = os.path.join(HERE, "snapshots", league)
    dest = os.path.join(root, safe)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(root, f"{safe}-{n}")
        n += 1
    return dest


def main():
    ap = argparse.ArgumentParser(description="Snapshot current projections for backtesting")
    ap.add_argument("--league", required=True, help="TGS or BLM (public/data folder name)")
    ap.add_argument("--slug", default=None, help="StatsPlus slug (default: lowercased --league)")
    ap.add_argument("--write", action="store_true", help="copy files (otherwise dry run)")
    a = ap.parse_args()

    league = a.league.upper()
    slug = (a.slug or league.lower()).strip("/")
    base = sp.normalize_base(slug)
    try:
        game_date = sp.fetch_date(base)
    except (sp.StatsPlusRefused, OSError) as e:
        refused = isinstance(e, sp.StatsPlusRefused)
        why = (e.user_message(league) if refused else
               f"StatsPlus could not be reached ({type(e).__name__}: {e}). Try again in a minute.")
        print(f"[{league}] {why}")
        print("  Nothing was snapped: the snapshot folder is named for the in-game date.")
        sys.exit(EXIT_REFUSED if refused else EXIT_NETWORK)

    ratings_cache = os.path.join(VIZ, "ingest", ".cache", f"statsplus_{slug}.json")
    sources = [
        os.path.join(VIZ, "public", "data", league, "hitters.json"),
        os.path.join(VIZ, "public", "data", league, "pitchers.json"),
        os.path.join(VIZ, "public", "data", league, "metadata.json"),
        ratings_cache,
    ]
    dest = snapshot_dir(league, game_date)
    print(f"[{league}] in-game date {game_date}  ->  {dest}")

    # THE IMPORTANT PART: stats are retrievable forever (year-addressable API), but the
    # ratings AS THEY WERE during those stats exist only in the current pull — one refresh
    # later they're gone. This snapshot is the only thing that preserves the pairing the
    # whole system regresses on. A stale cache here = season-end ratings lost permanently.
    cache_age_h = None
    if os.path.exists(ratings_cache):
        cache_age_h = (datetime.datetime.now().timestamp() - os.path.getmtime(ratings_cache)) / 3600
        if cache_age_h > 48:
            print("!" * 72)
            print(f"  WARNING: the ratings cache is {cache_age_h/24:.1f} DAYS old.")
            print("  This snapshot will preserve STALE ratings next to today's stats.")
            print("  For a season-end snapshot, run 'Get StatsPlus Ratings.bat' FIRST")
            print("  (fresh ratings pull), then re-run this. Ratings not captured now")
            print("  cannot be recovered later — stats can, ratings can't.")
            print("!" * 72)

    snapped, missing = [], []
    for src in sources:
        if not os.path.exists(src):
            print(f"  MISSING (skipped): {src}")
            missing.append(os.path.basename(src))
            continue
        if a.write:
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
        rel = os.path.relpath(src, VIZ)
        print(f"  snapped: {rel}  ({os.path.getsize(src):,} bytes)")
        snapped.append({"file": os.path.basename(src), "source": rel.replace(os.sep, "/"),
                        "bytes": os.path.getsize(src)})

    if a.write:
        manifest = {
            "league": league,
            "slug": slug,
            "in_game_date": game_date,
            "snapped_at_real": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "ratings_cache_age_hours": round(cache_age_h, 1) if cache_age_h is not None else None,
            "ratings_fresh": (cache_age_h is not None and cache_age_h <= 48),
            "files": snapped,
            "missing": missing,
        }
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"  wrote manifest.json  ({len(snapped)} files snapped, {len(missing)} missing)")
    else:
        print("  (dry run — pass --write to snapshot)")


if __name__ == "__main__":
    main()
