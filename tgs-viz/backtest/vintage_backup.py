"""
vintage_backup.py — git-safe backup of the ratings-history vintages.

WHY: ratings_history.db holds scouting vintages that CANNOT be re-fetched.
StatsPlus serves only current ratings — there is no history endpoint — so a
lost pull is lost permanently, and with it every fit that needs pull-to-pull
rating movement (development / decline curves). The .db itself is a poor git
citizen: ~92 MB of binary that git must re-store in full on every change.

WHAT: one gzipped CSV per pull, written once and never rewritten:

    tgs-viz/backtest/vintages/<LEAGUE>/<real_date>_p<pull_id>.csv.gz
    tgs-viz/backtest/vintages/<LEAGUE>/_pulls.csv        (pull metadata)
    tgs-viz/backtest/vintages/_schema.sql                (original DDL)

The DDL is stored alongside the data because CSV carries no types: restoring
into a typeless table turns NULL into "" and 38.0 into "38.0". Recreating the
real schema first lets SQLite's column affinity coerce every value back.

Because a pull is immutable, each refresh adds one small file and touches
nothing else, so the repo grows by roughly the size of one vintage.

CLI:
    python vintage_backup.py --export             # DB  -> vintages/  (skips existing)
    python vintage_backup.py --restore            # vintages/ -> DB   (rebuilds if lost)
    python vintage_backup.py --verify             # row-count check, both directions
"""
import os
import csv
import gzip
import sqlite3
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
# tgs-viz/backtest by default; RATINGS_ARCHIVE_ROOT (tests only) moves both
_ROOT = os.environ.get("RATINGS_ARCHIVE_ROOT") or HERE
DB_PATH = os.path.join(_ROOT, "ratings_history.db")
OUT_DIR = os.path.join(_ROOT, "vintages")

# game_date = the pull's in-game date (pull_order.py sorts by it). An older DB
# without the column exports it blank; --restore reads blank as NULL.
PULL_COLS = ["pull_id", "league", "real_date", "real_ts", "source",
             "source_files", "n_players", "content_hash", "ingested_at", "game_date"]


def _cols(con, table):
    return [r[1] for r in con.execute(f"pragma table_info({table})")]


def _slug(real_date, pull_id):
    return f"{real_date}_p{pull_id}.csv.gz"


def export(db_path=DB_PATH, out_dir=OUT_DIR, leagues=None):
    """leagues: only these leagues' folders (None = every league)."""
    if not os.path.exists(db_path):
        raise SystemExit(f"no database at {db_path} — nothing to export")
    con = sqlite3.connect(db_path)
    rcols = _cols(con, "ratings")
    have = set(_cols(con, "pulls"))
    sel = ",".join(c if c in have else f"NULL AS {c}" for c in PULL_COLS)

    os.makedirs(out_dir, exist_ok=True)
    ddl = [s for (s,) in con.execute(
        "select sql from sqlite_master where type='table' and name in ('pulls','ratings')") if s]
    with open(os.path.join(out_dir, "_schema.sql"), "w", encoding="utf-8") as fh:
        fh.write(";\n\n".join(ddl) + ";\n")

    pulls = list(con.execute(f"select {sel} from pulls order by pull_id"))
    by_league = {}
    for p in pulls:
        if leagues and p[1] not in leagues:
            continue
        by_league.setdefault(p[1], []).append(p)

    written = skipped = 0
    for league, rows in sorted(by_league.items()):
        d = os.path.join(out_dir, league)
        os.makedirs(d, exist_ok=True)

        with open(os.path.join(d, "_pulls.csv"), "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(PULL_COLS)
            w.writerows(rows)

        for p in rows:
            pull_id, real_date = p[0], p[2]
            path = os.path.join(d, _slug(real_date, pull_id))
            if os.path.exists(path):
                skipped += 1
                continue
            data = list(con.execute(
                f"select {','.join(rcols)} from ratings where pull_id=? order by player_id",
                (pull_id,)))
            with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(rcols)
                w.writerows(data)
            written += 1
            print(f"  {league} {real_date}  pull {pull_id:>3}  "
                  f"{len(data):>6,} rows  {os.path.getsize(path)/1024:>7,.0f} KB")

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(out_dir) for f in fs)
    print(f"export: {written} new, {skipped} already present, "
          f"{total/1048576:.1f} MB total in {os.path.relpath(out_dir, HERE)}/")


def restore(db_path=DB_PATH, out_dir=OUT_DIR):
    """Rebuild the DB from the exported vintages. Refuses to clobber an
    existing database — move it aside first if you really mean it."""
    if os.path.exists(db_path):
        raise SystemExit(f"{db_path} already exists — move it aside to rebuild from scratch")
    if not os.path.isdir(out_dir):
        raise SystemExit(f"no vintages at {out_dir}")

    schema = os.path.join(out_dir, "_schema.sql")
    if not os.path.exists(schema):
        raise SystemExit(f"missing {schema} — re-run --export against a live DB first")

    con = sqlite3.connect(db_path)
    with open(schema, encoding="utf-8") as fh:
        con.executescript(fh.read())
    if "game_date" not in _cols(con, "pulls"):     # a schema saved before the column existed
        con.execute("ALTER TABLE pulls ADD COLUMN game_date TEXT")

    # CSV has no NULL: an empty field is a missing rating, not the string "".
    def _row(vals):
        return [None if v == "" else v for v in vals]

    n_pulls = n_rows = 0
    for league in sorted(os.listdir(out_dir)):
        d = os.path.join(out_dir, league)
        pulls_csv = os.path.join(d, "_pulls.csv")
        if not os.path.isdir(d) or not os.path.exists(pulls_csv):
            continue

        with open(pulls_csv, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        head, body = rows[0], rows[1:]
        con.executemany(
            f"insert or replace into pulls ({','.join(head)}) "
            f"values ({','.join('?' * len(head))})", [_row(r) for r in body])
        n_pulls += len(body)

        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".csv.gz"):
                continue
            with gzip.open(os.path.join(d, fn), "rt", newline="", encoding="utf-8") as fh:
                rr = csv.reader(fh)
                rcols = next(rr)
                batch = [_row(r) for r in rr]
            con.executemany(
                f"insert or replace into ratings ({','.join(rcols)}) "
                f"values ({','.join('?' * len(rcols))})", batch)
            n_rows += len(batch)
            print(f"  restored {league} {fn}  {len(batch):,} rows")

    con.commit()
    print(f"restore: {n_pulls} pulls, {n_rows:,} rating rows -> {os.path.relpath(db_path, HERE)}")


def verify(db_path=DB_PATH, out_dir=OUT_DIR):
    con = sqlite3.connect(db_path)
    db_pulls = {(r[0], r[1], r[2]): r[3] for r in con.execute(
        "select pull_id, league, real_date, count(*) from ratings "
        "join pulls using(pull_id) group by pull_id")}

    missing, mismatch, ok = [], [], 0
    for (pull_id, league, real_date), n in sorted(db_pulls.items()):
        path = os.path.join(out_dir, league, _slug(real_date, pull_id))
        if not os.path.exists(path):
            missing.append(f"{league} {real_date} (pull {pull_id})")
            continue
        with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
            n_file = sum(1 for _ in fh) - 1
        if n_file != n:
            mismatch.append(f"{league} {real_date}: db {n} vs file {n_file}")
        else:
            ok += 1

    print(f"verify: {ok} vintages match")
    for m in missing:
        print(f"  MISSING backup: {m}")
    for m in mismatch:
        print(f"  ROW MISMATCH: {m}")
    if missing or mismatch:
        raise SystemExit(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--out", default=OUT_DIR)
    a = ap.parse_args()
    if a.restore:
        restore(a.db, a.out)
    elif a.verify:
        verify(a.db, a.out)
    else:
        export(a.db, a.out)
