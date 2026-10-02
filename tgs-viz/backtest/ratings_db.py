"""
ratings_db.py — permanent per-player ratings-history database + trend analytics.

PURPOSE: keep every recoverable scouting-ratings vintage in one SQLite store so
pull-to-pull rating movement (scout churn, player development/decline) can be
tracked per player, per rating column, across leagues, forever. Prices always
use the current ratings as they are; the archive feeds last year's growth into
the dev numbers (dev_signals.py growth and cells, the ML scoring rows of
ml/dataset.py).

    tgs-viz/backtest/ratings_history.db          (stdlib sqlite3, no deps)

Schema (wide table — one row per player per pull, one NUMERIC column per
rating; the rating set mirrors ingest/ratings.py SMOOTH_COLS + Ovr/Pot):

    pulls(pull_id PK, league, real_date UNIQUE-with-league, real_ts, source,
          source_files, n_players, content_hash, ingested_at, game_date)

    ratings(pull_id, player_id, name, age, pos, org, lev, c_<RATING>..., PK(pull_id, player_id))

game_date = the in-game date of the pull (added 2026-09-25; connect() adds
the column to an older DB and fills it). An "asof" pull (a past-date StatsPlus
snapshot, ingest/statsplus_history.py) stores real_date = game_date, like a DEV
dump pull. Every reader orders the pulls by game date (pull_order.py); the
newest pull that is not "asof" is "the latest pull".

CLI:
    python ratings_db.py --backfill            # ingest every recoverable vintage:
                                               #   ingest/.cache/history/*.json
                                               #   backtest/snapshots/<LG>/*/statsplus_*.json
                                               #   public/data/<LG>/{hitters,pitchers}.json.bak-*  (mtime = vintage date)
                                               # dedupe: one pull per league+date (best source wins);
                                               # bak vintages whose ratings are byte-identical to the
                                               # previous vintage (engine REPROCESSES, not new pulls) are skipped.
    python ratings_db.py --append <cache.json> --league TGS   # ingest one live raw pull (used by refresh.py)
    python ratings_db.py --report  [--league TGS] [--window 3]
    python ratings_db.py --export  [--league TGS]  # -> public/data/<LG>/rating_trends.json (app surface)
                                   [--out DIR]     # -> DIR/<LG>/rating_trends.json instead
    python ratings_db.py --guard   [--league TGS]  # scale-event guard reading of every pull pair

refresh.py calls append_pull() automatically after archiving each live pull.

DUMP-SOURCED LEAGUE (dump_vintages.py + dump_source.py): its pulls carry source
"dump" and its rating scale sits in league_scale_<LG>.json next to the DB. On a
"1-100" league nothing is mapped to the internal scale (units stay "display"),
a skill counts as rated when it is above 0 (not >= 20), and the guard bars stay
in display points. The TGS / BLM path is unchanged.
"""
import os
import sys
import re
import json
import time
import glob
import sqlite3
import hashlib
import datetime
import argparse
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)                                  # tgs-viz
REPO = os.path.dirname(VIZ)
INGEST = os.path.join(VIZ, "ingest")

sys.path.insert(0, INGEST)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import statsplus as S  # stdlib-only; supplies STATSPLUS_TO_SHEET  # noqa: E402
import pull_order as PO  # in-game order of the pulls (live + asof)  # noqa: E402

DB_PATH = PO.DB_PATH                  # tgs-viz/backtest/ratings_history.db (tests: RATINGS_ARCHIVE_ROOT)
ASOF = PO.ASOF                        # source of a past-date StatsPlus snapshot (statsplus_history.py)

_TOOLS = os.path.join(VIZ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402  (stdlib only; works under the ML interpreter too)

LEAGUES = ST.slug_map()               # {id: slug} of the online leagues (TGS, BLM)

# ---- rating columns (sheet-name space; mirrors ingest/ratings.py SMOOTH_COLS) --
_PIT_CORE = ["STU", "HRR", "PBABIP", "CON"]
_PIT_SPLITS = [f"{c} {s}" for c in _PIT_CORE for s in ("vR", "vL", "P")]
_PITCH_CUR = ["FB", "CH", "CB", "SL", "SI", "SP", "CT", "FO", "CC", "SC", "KC", "KN"]
_PITCH_POT = ["KNP", "FBP", "CHP", "CBP", "SLP", "SIP", "SPP", "CTP", "FOP", "CCP", "SCP", "KCP"]
_HIT_SPLITS = [f"{c} {s}" for c in ("BA", "GAP", "POW", "EYE", "K") for s in ("vR", "vL")]
_HIT_POT = ["HT P", "GAP P", "POW P", "EYE P", "K P"]
_RUN_FLD = ["SPE", "SR", "STE", "RUN",
            "IF RNG", "IF ERR", "IF ARM", "TDP", "OF RNG", "OF ERR", "OF ARM",
            "C ABI", "C FRM", "C ARM"]
SMOOTH_COLS = (_PIT_CORE + _PIT_SPLITS + ["STM", "HLD"] + _PITCH_CUR + _PITCH_POT
               + _HIT_SPLITS + _HIT_POT + _RUN_FLD)
EXTRA_COLS = ["Ovr", "Pot"]          # OOTP's own 20-80 summary grades (context only)
ALL_COLS = SMOOTH_COLS + EXTRA_COLS

# Columns the TREND views score (movers, age curves). Everything above is still
# STORED — this only decides what counts as "a player moved".
#   - the 24 individual pitch grades are dropped: they step in whole grades and a
#     pitch appearing/disappearing is a repertoire change, not development. The
#     aggregate STU / CON / HRR / PBABIP already carry the arm's real movement.
#   - the pitcher vR/vL splits are dropped because they DUPLICATE their own core
#     column: one +10 control change was being counted as CON +10, CON vR +10 and
#     CON vL +10, tripling every pitcher's total.
# Hitter ratings exist only as vR/vL, so both are kept; a change that moves both
# sides still counts twice there, which is a known limit of this view.
_TREND_DROP = set(_PITCH_CUR) | set(_PITCH_POT) | {
    f"{c} {s}" for c in _PIT_CORE for s in ("vR", "vL")}
TREND_COLS = [c for c in SMOOTH_COLS if c not in _TREND_DROP]

# Rating scale of a league: "20-80" (TGS, BLM, every StatsPlus league) or
# "1-100" (a dump-sourced league that shows ratings 1-100; dump_source reads it
# from league_scale_<LG>.json next to the DB).
SCALE_DEFAULT = "20-80"


def rated_floor(scale=SCALE_DEFAULT):
    """Smallest value that counts as a rated skill: 20 on 20-80 (OOTP fills an
    absent skill with 0), 1 on a 1-100 league (any value above 0)."""
    return 1 if scale == "1-100" else 20


COL2SQL = {c: "c_" + re.sub(r"[^A-Za-z0-9]", "_", c) for c in ALL_COLS}
SQL2COL = {v: k for k, v in COL2SQL.items()}
assert len(SQL2COL) == len(ALL_COLS), "rating column SQL names collide"

# source precedence when several files claim the same league+date vintage
SOURCE_RANK = {"live": 5, "history": 4, "snapshot": 3, "bak": 2, "recovered": 1, "live-current": 0}
# sources that are engine REPROCESS artifacts (not necessarily new pulls) —
# eligible for the identical-content skip so a re-run of the engine over the
# same ratings never fabricates a fake "vintage" with zero deltas.
REPROCESS_SOURCES = {"bak", "live-current"}


def num(v):
    """Rating value -> float or None. '-' reads as 20 (the engine's convention)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return None
    if s == "-":
        return 20.0
    try:
        return float(s)
    except ValueError:
        return None


def _compact(x):
    """Store integral floats as ints (NUMERIC affinity keeps them small)."""
    if x is None:
        return None
    return int(x) if float(x).is_integer() else float(x)


ARCHIVE_MISSING = ("The ratings archive is missing. Rebuild it first: Control, Setup check, Rebuild ratings "
                   "archive (or python tgs-viz\\backtest\\vintage_backup.py --restore).")


def _archive_missing(db_path):
    """True when db_path does not exist but saved vintages sit next to it
    (vintages/*/_pulls.csv): a fresh clone whose archive was never rebuilt."""
    if os.path.exists(db_path) or os.environ.get("RATINGS_DB_ALLOW_NEW") == "1":
        return False
    root = os.path.dirname(os.path.abspath(db_path))
    return bool(glob.glob(os.path.join(root, "vintages", "*", "_pulls.csv")))


def connect(db_path=DB_PATH):
    # Never create an empty archive next to saved vintages: an export from it
    # would write "players": {} over rating_trends.json, and vintage_backup
    # --restore refuses once a database exists. RATINGS_DB_ALLOW_NEW=1 (worktree
    # tests only) skips this. vintage_backup.restore opens its own connection.
    if _archive_missing(db_path):
        raise SystemExit(ARCHIVE_MISSING)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    rating_defs = ", ".join(f'"{COL2SQL[c]}" NUMERIC' for c in ALL_COLS)
    conn.execute("""CREATE TABLE IF NOT EXISTS pulls(
        pull_id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        real_date TEXT NOT NULL,
        real_ts TEXT,
        source TEXT NOT NULL,
        source_files TEXT,
        n_players INTEGER,
        content_hash TEXT,
        ingested_at TEXT,
        UNIQUE(league, real_date))""")
    PO.ensure_game_date_column(conn)     # older DB: add pulls.game_date and fill it
    conn.execute(f"""CREATE TABLE IF NOT EXISTS ratings(
        pull_id INTEGER NOT NULL,
        player_id TEXT NOT NULL,
        name TEXT, age REAL, pos TEXT, org TEXT, lev TEXT,
        {rating_defs},
        PRIMARY KEY(pull_id, player_id)) WITHOUT ROWID""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_player ON ratings(player_id)")
    return conn


# ---------------------------------------------------------------- level rule
# Level of an archived row. App-JSON rows (bak) carry the app's Lev. A raw
# StatsPlus row carries none, so the level comes from the app's own rule,
# ingest/statsplus._lev_for (TGS: League id, BLM: LgLvl). '-' = a row in a
# foreign league of the TGS world (NPB / KBO): outside every MLB-world org.
# One rule for the archive and its readers (dev_signals, ml/dataset).
FOREIGN_LEV = "-"


def derive_lev(r, league):
    """Level string of one ratings row. Returns the row's own Lev when it has
    one. Else returns statsplus._lev_for for a TGS / BLM raw StatsPlus row
    (a row with a League or LgLvl key). Else returns None."""
    lev = str(r.get("Lev") or "").strip()
    if lev:
        return lev
    if _online(league) and ("League" in r or "LgLvl" in r):
        return S._lev_for(r, league)
    return None


_ONLINE = {}


def _online(league):
    """A StatsPlus league: LEAGUES, or one New League is adding (pending in the
    settings), so its first archived pull gets levels too."""
    if league not in _ONLINE:
        _ONLINE[league] = league in LEAGUES or (ST.league(league) or {}).get("type") == "statsplus"
    return _ONLINE[league]


def raw_pull_levels(conn, pull_id, league):
    """{player_id: level} of one archived pull, rebuilt from the pull's own
    source files (pulls.source_files) with derive_lev. A later row of the same
    ID wins (the rows_to_map order). Returns None when no source file of the
    pull is on disk."""
    row = conn.execute("SELECT source_files FROM pulls WHERE pull_id=?", (pull_id,)).fetchone()
    out, found = {}, False
    for rel in json.loads((row[0] if row else None) or "[]"):
        path = os.path.join(REPO, str(rel).replace("\\", os.sep))
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            continue
        found = True
        for r in rows:
            if not isinstance(r, dict):
                continue
            pid = str(r.get("ID") or "").strip()
            if pid:
                out[pid] = derive_lev(r, league)
    return out if found else None


# ---------------------------------------------------------------- row shaping
def rows_to_map(rows, translate=True, league=None):
    """Rows (raw StatsPlus schema or already sheet-schema) -> {pid: rec} where
    rec = {name, age, pos, org, lev, <sheet rating col>: float, ...}. With a
    TGS / BLM league, a raw row with no Lev gets the app's level rule
    (derive_lev)."""
    if translate:
        rows = S.translate_rows(rows)
    out = {}
    for r in rows:
        pid = str(r.get("ID") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not pid or pid in ("0", "None") or not name or name == "-":
            continue
        rec = {
            "name": name,
            "age": num(r.get("Age")),
            "pos": (str(r.get("POS") or r.get("Pos") or "").strip() or None),
            "org": (str(r.get("ORG") or r.get("Org") or "").strip() or None),
            "lev": derive_lev(r, league),
        }
        for c in ALL_COLS:
            if c in r:
                rec[c] = num(r.get(c))
        out[pid] = rec
    return out


def content_hash(pmap):
    """Hash of the rating CONTENT of a vintage (ids + rating values only)."""
    h = hashlib.sha1()
    for pid in sorted(pmap):
        rec = pmap[pid]
        h.update(pid.encode())
        for c in ALL_COLS:
            v = rec.get(c)
            if v is not None:
                h.update(c.encode())
                h.update(f"{v:.4f}".encode())
    return h.hexdigest()


def _same_ratings(prev_map, cand_map):
    """True when cand looks like a REPROCESS of prev: >=95%% of cand's players
    exist in prev and every shared player's shared rating values are identical."""
    shared = [pid for pid in cand_map if pid in prev_map]
    if not cand_map or len(shared) < 0.95 * len(cand_map):
        return False
    for pid in shared:
        a, b = prev_map[pid], cand_map[pid]
        for c in ALL_COLS:
            va, vb = a.get(c), b.get(c)
            if va is None or vb is None:
                continue
            if abs(va - vb) > 1e-9:
                return False
    return True


# ---------------------------------------------------------------- ingestion
def insert_pull(conn, league, real_date, real_ts, source, files, pmap, game_date=None):
    if game_date is None and source in PO.SELF_DATED:
        game_date = real_date            # an asof / dump pull: real_date is the in-game date
    cur = conn.execute(
        "INSERT INTO pulls(league, real_date, real_ts, source, source_files, n_players, content_hash, "
        "ingested_at, game_date) VALUES(?,?,?,?,?,?,?,?,?)",
        (league, real_date, real_ts, source, json.dumps(files), len(pmap),
         content_hash(pmap), datetime.datetime.now().isoformat(timespec="seconds"), game_date))
    pull_id = cur.lastrowid
    cols = ["pull_id", "player_id", "name", "age", "pos", "org", "lev"] + [COL2SQL[c] for c in ALL_COLS]
    sql = "INSERT INTO ratings({}) VALUES({})".format(
        ", ".join(f'"{c}"' for c in cols), ", ".join("?" * len(cols)))
    conn.executemany(sql, (
        [pull_id, pid, rec["name"], rec["age"], rec["pos"], rec["org"], rec["lev"]]
        + [_compact(rec.get(c)) for c in ALL_COLS]
        for pid, rec in pmap.items()))
    conn.commit()
    return pull_id


def load_pull_map(conn, pull_id):
    cols = ["player_id", "name", "age", "pos", "org", "lev"] + [COL2SQL[c] for c in ALL_COLS]
    q = "SELECT {} FROM ratings WHERE pull_id=?".format(", ".join(f'"{c}"' for c in cols))
    out = {}
    for row in conn.execute(q, (pull_id,)):
        rec = {"name": row[1], "age": row[2], "pos": row[3], "org": row[4], "lev": row[5]}
        for i, c in enumerate(ALL_COLS):
            v = row[6 + i]
            if v is not None:
                rec[c] = float(v)
        out[str(row[0])] = rec
    return out


def league_pulls(conn, league):
    """[(pull_id, real_date, real_ts, source, n_players)] oldest first by
    IN-GAME date (pull_order.ordered), asof snapshots included."""
    return PO.ordered(conn, league)[0]


def live_pulls(conn, league):
    """league_pulls without the asof snapshots: the pulls the app values came
    from. Movers and the trends window read these, so a past snapshot never
    becomes "the latest pull"."""
    return [p for p in league_pulls(conn, league) if p[3] != ASOF]


def append_pull(league, raw_rows, source="live", real_ts=None, real_date=None,
                files=None, db_path=DB_PATH, translate=True, game_date=None):
    """Ingest one pull (raw StatsPlus rows). Same-date pull is REPLACED (one
    vintage per league+date). Used by refresh.py after each live pull; additive
    only: never touches projections. game_date = the pull's in-game date
    (an asof / dump pull defaults to real_date). Returns pull_id or None."""
    real_ts = real_ts or datetime.datetime.now().isoformat(timespec="seconds")
    real_date = real_date or real_ts[:10]
    pmap = rows_to_map(raw_rows, translate=translate, league=league)
    if not pmap:
        return None
    conn = connect(db_path)
    try:
        old = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date=?",
                           (league, real_date)).fetchone()
        if old:
            conn.execute("DELETE FROM ratings WHERE pull_id=?", (old[0],))
            conn.execute("DELETE FROM pulls WHERE pull_id=?", (old[0],))
        return insert_pull(conn, league, real_date, real_ts, source, files or [], pmap, game_date=game_date)
    finally:
        conn.close()


def forget_league(conn, league):
    """Delete every pull of one league (its ratings rows and its pulls rows) in
    one transaction. Returns the number of pulls removed. Only the New League
    rollback calls this, for a league whose first try failed, so its id can be
    used again."""
    ids = [r[0] for r in conn.execute("SELECT pull_id FROM pulls WHERE league=?", (league,))]
    with conn:
        for pid in ids:
            conn.execute("DELETE FROM ratings WHERE pull_id=?", (pid,))
            conn.execute("DELETE FROM pulls WHERE pull_id=?", (pid,))
    return len(ids)


# ---------------------------------------------------------------- backfill
def _slug_to_league(slug):
    for lg, sl in LEAGUES.items():
        if sl == slug:
            return lg
    return slug.upper()


def _candidates_history():
    """ingest/.cache/history/statsplus_<slug>_<stamp>.json — the immutable live
    pull archive (raw schema) + 'recovered-' vintages (sheet schema, translate
    is a no-op on those)."""
    out = []
    hist = os.path.join(INGEST, ".cache", "history")
    for path in sorted(glob.glob(os.path.join(hist, "statsplus_*_*.json"))):
        fn = os.path.basename(path)
        m = re.match(r"statsplus_([a-z0-9]+)_(recovered-)?(\d{8})(?:-(\d{4}))?\.json$", fn)
        if not m:
            continue
        slug, recovered, d, hm = m.group(1), m.group(2), m.group(3), m.group(4) or "0000"
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        ts = f"{date}T{hm[:2]}:{hm[2:]}:00"
        out.append({
            "league": _slug_to_league(slug), "date": date, "ts": ts,
            "source": "recovered" if recovered else "history",
            "files": [os.path.relpath(path, REPO)],
            "load": (lambda p=path, lg=_slug_to_league(slug): rows_to_map(
                json.load(open(p, encoding="utf-8")), league=lg)),
        })
    return out


def _candidates_snapshots():
    """backtest/snapshots/<LG>/<in-game-date>/statsplus_<slug>.json (raw pull
    cache copies; real date from the manifest's snapped_at_real)."""
    out = []
    for lg in LEAGUES:
        for snapdir in sorted(glob.glob(os.path.join(HERE, "snapshots", lg, "*"))):
            raws = glob.glob(os.path.join(snapdir, "statsplus_*.json"))
            if not raws:
                continue
            path = raws[0]
            ts = None
            mpath = os.path.join(snapdir, "manifest.json")
            if os.path.exists(mpath):
                try:
                    ts = json.load(open(mpath, encoding="utf-8")).get("snapped_at_real")
                except Exception:
                    ts = None
            ts = ts or datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds")
            out.append({
                "league": lg, "date": ts[:10], "ts": ts[:19], "source": "snapshot",
                "files": [os.path.relpath(path, REPO)],
                "load": (lambda p=path, lg=lg: rows_to_map(json.load(open(p, encoding="utf-8")), league=lg)),
            })
    return out


def _load_bak_pair(hit_path, pit_path):
    """Merge a hitters/pitchers .bak pair (rows already carry sheet-name rating
    columns alongside computed outputs; extra output columns are ignored)."""
    pmap = {}
    for path in (hit_path, pit_path):
        if not path:
            continue
        rows = json.load(open(path, encoding="utf-8"))
        pmap.update(rows_to_map(rows, translate=False))
    return pmap


def _candidates_baks():
    """public/data/<LG>/{hitters,pitchers}.json.bak-* — each backup's MTIME is
    the date its data went live, i.e. the ratings vintage date. One candidate
    per league+date, pairing that date's newest hitters bak with its newest
    pitchers bak. The live hitters/pitchers.json pair joins as lowest-rank
    'live-current' (it usually duplicates the newest archived pull)."""
    out = []
    for lg in LEAGUES:
        ddir = os.path.join(VIZ, "public", "data", lg)
        by_date = {}   # date -> {"hit": (mtime, path), "pit": (mtime, path)}
        pats = [("hit", "hitters.json.bak-*"), ("pit", "pitchers.json.bak-*"),
                ("hit", "hitters.json"), ("pit", "pitchers.json")]
        for kind, pat in pats:
            for path in glob.glob(os.path.join(ddir, pat)):
                mt = os.path.getmtime(path)
                date = datetime.date.fromtimestamp(mt).isoformat()
                is_live = not os.path.basename(path).count(".bak-")
                slot = by_date.setdefault(date, {"live": False})
                slot["live"] = slot["live"] or is_live
                if kind not in slot or mt > slot[kind][0]:
                    slot[kind] = (mt, path)
        for date, slot in by_date.items():
            hit = slot.get("hit", (0, None))[1]
            pit = slot.get("pit", (0, None))[1]
            mt = max(slot.get("hit", (0,))[0], slot.get("pit", (0,))[0])
            out.append({
                "league": lg, "date": date,
                "ts": datetime.datetime.fromtimestamp(mt).isoformat(timespec="seconds"),
                "source": "live-current" if slot["live"] else "bak",
                "files": [os.path.relpath(p, REPO) for p in (hit, pit) if p],
                "load": (lambda h=hit, p=pit: _load_bak_pair(h, p)),
            })
    return out


def backfill(db_path=DB_PATH, rebuild=False):
    if rebuild and os.path.exists(db_path):
        os.remove(db_path)
        for ext in ("-wal", "-shm"):
            if os.path.exists(db_path + ext):
                os.remove(db_path + ext)
    conn = connect(db_path)

    cands = _candidates_history() + _candidates_snapshots() + _candidates_baks()
    # one candidate per league+date: best source wins; ties -> latest timestamp
    best = {}
    for c in cands:
        key = (c["league"], c["date"])
        rank = (SOURCE_RANK.get(c["source"], 0), c["ts"])
        if key not in best or rank > best[key][0]:
            best[key] = (rank, c)
    chosen = sorted((c for _, c in best.values()), key=lambda c: (c["league"], c["date"]))

    ingested, skipped_dup, skipped_have = [], [], []
    prev_map_by_lg = {}
    for c in chosen:
        lg = c["league"]
        have = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date=?",
                            (lg, c["date"])).fetchone()
        if have:
            skipped_have.append(c)
            prev_map_by_lg[lg] = load_pull_map(conn, have[0])
            continue
        try:
            pmap = c["load"]()
        except Exception as e:
            print(f"  !! {lg} {c['date']} ({c['source']}): load failed — {type(e).__name__}: {e}")
            continue
        if not pmap:
            print(f"  !! {lg} {c['date']} ({c['source']}): no usable rows, skipped")
            continue
        prev = prev_map_by_lg.get(lg)
        if prev is None:
            row = conn.execute("SELECT pull_id FROM pulls WHERE league=? AND real_date<? AND source<>? "
                               "ORDER BY real_date DESC LIMIT 1", (lg, c["date"], ASOF)).fetchone()
            if row:
                prev = load_pull_map(conn, row[0])
        if c["source"] in REPROCESS_SOURCES and prev and _same_ratings(prev, pmap):
            skipped_dup.append(c)
            print(f"  -- {lg} {c['date']} ({c['source']}): ratings identical to previous "
                  f"vintage (engine reprocess, not a new pull) — skipped")
            continue
        insert_pull(conn, lg, c["date"], c["ts"], c["source"], c["files"], pmap)
        prev_map_by_lg[lg] = pmap
        print(f"  ++ {lg} {c['date']} ({c['source']}): {len(pmap)} players "
              f"[{', '.join(os.path.basename(f) for f in c['files'])}]")
        ingested.append(c)
    conn.close()
    print(f"backfill: {len(ingested)} vintages ingested, {len(skipped_dup)} reprocess-duplicates "
          f"skipped, {len(skipped_have)} already in DB")
    return ingested


# ---------------------------------------------------------------- analytics
def player_deltas(conn, league, player_id):
    """Per-pull rating series for one player: [(real_date, {col: value}), ...]."""
    out = []
    for pull_id, date, _ts, _src, _n in league_pulls(conn, league):
        cols = ["name"] + [COL2SQL[c] for c in ALL_COLS]
        row = conn.execute(
            "SELECT {} FROM ratings WHERE pull_id=? AND player_id=?".format(
                ", ".join(f'"{c}"' for c in cols)),
            (pull_id, str(player_id))).fetchone()
        if row is None:
            continue
        vals = {c: float(row[1 + i]) for i, c in enumerate(ALL_COLS) if row[1 + i] is not None}
        out.append((date, vals))
    return out


def _readable(maps_newest_first, pid, field):
    """Best display value for org/lev: raw StatsPlus vintages carry NUMERIC org
    ids; prefer a non-numeric (enriched) value from the newest vintage that has
    one. Falls back to the newest value of any kind."""
    fallback = None
    for m in maps_newest_first:
        rec = m.get(pid)
        if not rec:
            continue
        v = rec.get(field)
        if v:
            if fallback is None:
                fallback = v
            if not str(v).isdigit():
                return v
    # numeric-only org id everywhere: 0 = the free-agent pool
    if field == "org" and str(fallback) == "0":
        return "FA"
    return fallback


def movers(conn, league, window=3, top=15, scale=SCALE_DEFAULT):
    """Biggest total scouting-value change (sum of SMOOTH_COLS deltas, display
    points) between the pull `window` pulls back and the latest pull. Live
    pulls only (live_pulls): an asof snapshot is never an end of the window.
    Returns (risers, fallers, meta); each entry:
    {id, name, pos, age, org, total, ncols, breakdown:{col: delta}}."""
    pulls = live_pulls(conn, league)
    if len(pulls) < 2:
        return [], [], {"pulls": len(pulls)}
    w = min(window, len(pulls) - 1)
    floor = rated_floor(scale)
    old_map = load_pull_map(conn, pulls[-1 - w][0])
    new_map = load_pull_map(conn, pulls[-1][0])
    scored = []
    for pid, nrec in new_map.items():
        orec = old_map.get(pid)
        if not orec:
            continue
        total, breakdown = 0.0, {}
        gained, lost = [], []
        for c in TREND_COLS:
            a, b = orec.get(c), nrec.get(c)
            if a is None or b is None:
                continue
            # OOTP fills an ABSENT skill with 0, below the 20 floor. Crossing that
            # boundary is a pitch appearing or disappearing from the repertoire, not a
            # scouting change: counting it made "gained a slider" read as +35 and put
            # those players at the top of every movers list. Same guard age_curves uses.
            # On a 1-100 league the floor is 1: any value above 0 is rated.
            if a < floor or b < floor:
                if b >= floor > a:
                    gained.append(c)
                elif a >= floor > b:
                    lost.append(c)
                continue
            d = b - a
            if d:
                total += d
                breakdown[c] = d
        if breakdown or gained or lost:
            scored.append({"id": pid, "name": nrec["name"], "pos": nrec["pos"],
                           "age": nrec["age"],
                           "org": _readable((new_map, old_map), pid, "org"),
                           "total": total,
                           "ncols": len(breakdown),
                           "gained": gained, "lost": lost,
                           "breakdown": dict(sorted(breakdown.items(),
                                                    key=lambda kv: -abs(kv[1]))[:6])})
    scored.sort(key=lambda x: -x["total"])
    meta = {"pulls": len(pulls), "window": w,
            "from": pulls[-1 - w][1], "to": pulls[-1][1],
            "players_changed": len(scored)}
    risers = [x for x in scored if x["total"] > 0][:top]
    fallers = [x for x in reversed(scored) if x["total"] < 0][:top]
    return risers, fallers, meta


# Current-rating -> its potential counterpart, for GAP-CONDITIONED growth tracking
# (user 2026-09-04: "a player 45/45 for BABIP — no need to measure that; 45/50 for
# power — track power", and maxed players must never drag down the growth average).
# The gap is re-read at the start of EVERY pull pair, so a re-scouted potential or
# a caught-up current automatically switches what gets tracked for that player.
# Hitters pair BOTH sides with the one published potential (user 2026-09-22:
# "get rid of the vR and vL stuff and just have it be both tied into one
# attribute"); the app pools vR + vL into one attribute row per skill.
# ---- underlying scale ---------------------------------------------------------
# The 20-80 display is a coarse, UNEVEN banding of OOTP's internal rating
# scale: one display step covers 13 to 52 internal points (user, 2026-09-22:
# "growth from 20-25 is not the same as growth from 25-30 ... guys are getting
# to the really tough to break through ratings areas"). Growth is therefore
# counted in INTERNAL points: every displayed rating is mapped to the middle
# of its band before a delta or a gap is taken. Table = the user's OOTP 26
# internal-scale mapping (1-600), labeled APPROXIMATE by its source. Checked
# against this archive (2026-09-22, both leagues): a displayed rating flips
# ~1/width — 60-75 flip 2-4x as often as 45-55 (31+ decliners: rate x width is
# flat from 50 to 75), so the SHAPE holds for batting and pitching ratings;
# the interior edges are only pinned to within ~1.5-2x.
# Two measured exceptions:
#   * the 20 floor: young players leave 20 exactly as fast as they leave 25
#     (TGS 3.51% vs 3.50% per pull), so OOTP creates players near the TOP of
#     the 1-134 band. Reading 20 at the band middle (67.5) would score a 20->25
#     flip as +86 points and carry 25-66% of the growth at 17-19. So 20 is read
#     at 115.5 (as if the effective floor band were 97-134, one 25-band wide).
#   * fielding / running / stamina / hold: the archive shows NO narrowing above
#     55 for them, so they are NOT converted (INTERNAL_COLS below) and stay in
#     display steps; the export says which unit each column carries.
UNDERLYING_BAND = {20: (1, 134), 25: (135, 172), 30: (173, 223), 35: (224, 275),
                   40: (276, 322), 45: (323, 374), 50: (375, 412), 55: (413, 436),
                   60: (437, 449), 65: (450, 464), 70: (465, 478), 75: (479, 492),
                   80: (493, 517), 85: (518, 600)}
UNDERLYING_MID = {v: (lo + hi) / 2.0 for v, (lo, hi) in UNDERLYING_BAND.items()}
UNDERLYING_MID[20] = 115.5          # measured floor (see above), not the band middle


def underlying(v):
    """Displayed 20-80 rating -> its internal value (band middle; 20 = measured floor; 85+ one band)."""
    if v is None:
        return None
    k = int(round(v / 5.0)) * 5
    if k <= 20:
        return UNDERLYING_MID[20]
    if k >= 85:
        return UNDERLYING_MID[85]
    return UNDERLYING_MID[k]


GAP_PAIRS = {
    "STU": "STU P", "HRR": "HRR P", "PBABIP": "PBABIP P", "CON": "CON P",
    "BA vR": "HT P", "GAP vR": "GAP P", "POW vR": "POW P",
    "EYE vR": "EYE P", "K vR": "K P",
    "BA vL": "HT P", "GAP vL": "GAP P", "POW vL": "POW P",
    "EYE vL": "EYE P", "K vL": "K P",
}
# OOTP's own OVERALL grade, tracked toward its POTENTIAL grade the same way
# (user 2026-09-22: "the same stuff but for overall as well"). Kept OUT of
# GAP_PAIRS on purpose: it is a composite with no band table (stays in display
# points: 1-pt steps in TGS, 5-pt in BLM), it must not join the scale-event
# guard columns, and a player's Ovr is a pitcher rating when HE is a pitcher.
OVERALL_PAIRS = {"Ovr": "Pot"}
ALL_GAP_PAIRS = {**GAP_PAIRS, **OVERALL_PAIRS}
AGE_TREND_COLS = TREND_COLS + EXTRA_COLS      # age curves also chart Ovr / Pot
# Columns counted on the internal scale: batting + pitching ratings and their
# potentials (the bands were verified for these). Everything else (fielding,
# running, stamina, hold, pitches, Ovr/Pot) stays in 20-80 display steps.
INTERNAL_COLS = set(GAP_PAIRS) | set(GAP_PAIRS.values())


def col_units(c, scale=SCALE_DEFAULT):
    if scale == "1-100":
        return "display"
    return "internal" if c in INTERNAL_COLS else "display"


def rating_delta(c, a, b, scale=SCALE_DEFAULT):
    """b - a in the column's own unit (internal points for batting / pitching
    ratings of a 20-80 league, display points otherwise)."""
    if scale != "1-100" and c in INTERNAL_COLS:
        return underlying(b) - underlying(a)
    return b - a


def _scale_of(conn, league):
    """The league's rating scale ("20-80" unless dump_source says "1-100")."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import dump_source
        return dump_source.league_scale(conn, league)
    except Exception:
        return SCALE_DEFAULT


# ---- scale-event guard (contaminated pull pairs) ----------------------------
# A re-scout / ratings-scale event between two pulls moves a whole league's
# ratings at once. Its deltas are not development, so the pair must not feed any
# growth curve. engine/agecurve_fit.py skips such a pair when the league-wide
# MEDIAN shift of a potential reaches 2 points. age_curves() applies the same
# measured rule, per league and per SIDE (pitcher ratings / hitter ratings):
#   rule 1 (agecurve_fit's rule): |median shift| >= GUARD_MEDIAN_PTS on any guard
#     column of the side. Guard columns = the gap-tracked CURRENT ratings and
#     their potentials (age_curves measures currents; agecurve_fit reads WAA and
#     guards on potentials only). A median moves only when more than half of the
#     side moved the same way: every clean pair of both leagues reads 0.0.
#   rule 2: share of the side's players who LOST points on one CURRENT rating
#     >= GUARD_DOWN_SHARE. It catches an event that hits under half of a side
#     (median still 0). Measured 2026-09-17 over all 61 pairs of both leagues:
#     clean pairs read 0.000-0.115, the BLM event pair (real 2026-06-23 ->
#     2026-07-09) reads 0.326 for hitters and 0.752 for pitchers. Potentials are
#     NOT read by rule 2: OOTP's pre-season re-rate lowers the potential of
#     11-29 percent of players every spring (both leagues), currents untouched.
# Population of a side = its own players (pitchers for pitcher ratings), with an
# org, shared by both pulls, age step 0 or 1: the same set that dates the pair.
# A contaminated side drops EVERY column of that side for the pair (base cols,
# gaps, traits, lenses). Nothing is hard-coded: run --guard to see every pair.
PIT_POS = ("SP", "RP", "CL")
GUARD_MEDIAN_PTS = 2.0
GUARD_DOWN_SHARE = 0.20
GUARD_MIN_N = 200             # a guard column needs this many rated players
SIDES = ("pit", "hit")
SIDE_LABEL = {"pit": "pitchers", "hit": "hitters"}
SIDE_CUR = {"pit": [c for c in GAP_PAIRS if c in _PIT_CORE],
            "hit": [c for c in GAP_PAIRS if c not in _PIT_CORE]}
SIDE_POT = {s: [GAP_PAIRS[c] for c in cols] for s, cols in SIDE_CUR.items()}
_PIT_SIDE_COLS = set(_PIT_CORE) | set(_PIT_SPLITS) | {"STM", "HLD"} | set(_PITCH_CUR) | set(_PITCH_POT)


def col_side(c):
    """'pit' for a pitcher rating column, 'hit' for everything else."""
    return "pit" if c in _PIT_SIDE_COLS else "hit"


def pair_guard(shared, floor=20):
    """Scale-event reading of one pull pair. shared = [(pid, old rec, new rec,
    age, age step)], the org'd players that date the pair. floor = smallest
    rated value (rated_floor); the bars are display points on every scale.
    Returns {side: {players, median_col, median_shift, down_col, down_share,
    down_mean, reason}}; reason is None for a clean side."""
    out = {}
    for side in SIDES:
        recs = [(o, n) for _pid, o, n, _a, _d in shared
                if ((o.get("pos") or "").upper() in PIT_POS) == (side == "pit")]
        med = down = None
        for c in SIDE_CUR[side] + SIDE_POT[side]:
            ds = []
            for o, n in recs:
                a, b = o.get(c), n.get(c)
                if a is not None and b is not None and a >= floor and b >= floor:
                    ds.append(b - a)
            if len(ds) < GUARD_MIN_N:
                continue
            m = statistics.median(ds)
            if med is None or abs(m) > abs(med[1]):
                med = (c, m)
            if c in SIDE_CUR[side]:
                share = sum(1 for x in ds if x < 0) / len(ds)
                if down is None or share > down[1]:
                    down = (c, share, sum(ds) / len(ds))
        g = {"players": len(recs),
             "median_col": med[0] if med else None, "median_shift": med[1] if med else None,
             "down_col": down[0] if down else None, "down_share": down[1] if down else None,
             "down_mean": down[2] if down else None, "reason": None}
        if med and abs(med[1]) >= GUARD_MEDIAN_PTS:
            g["reason"] = (f"rating scale event: median {med[0]} shift {med[1]:+.1f} points across "
                           f"{len(recs)} {SIDE_LABEL[side]} (bar {GUARD_MEDIAN_PTS:g})")
        elif down and down[1] >= GUARD_DOWN_SHARE:
            g["reason"] = (f"rating scale event: {down[1]:.0%} of {len(recs)} {SIDE_LABEL[side]} lost "
                           f"{down[0]} points in one pair, mean {down[2]:+.2f} "
                           f"(bar {GUARD_DOWN_SHARE:.0%})")
        out[side] = g
    return out


def _guard_measured(g, span=None):
    """One side's pair_guard() reading in payload shape (rounded, None-safe)."""
    out = {"players": g["players"],
           "median": {"col": g["median_col"], "shift": g["median_shift"]},
           "down_share": {"col": g["down_col"],
                          "share": round(g["down_share"], 4) if g["down_share"] is not None else None,
                          "mean_shift": round(g["down_mean"], 3) if g["down_mean"] is not None else None}}
    if span is not None:
        out["span_years"] = round(span, 3)
    return out


def _stored_game_dates(conn, league, pulls):
    """{pull_id: 'YYYY-MM-DD'}: pulls.game_date, else backtest/pull_game_dates_<LG>.json
    (written by growth_lenses; only entries whose stored real date still matches
    the pull), else real_date for an asof / dump pull (pull_order.game_dates)."""
    return PO.game_dates(conn, league, pulls)


PERSONALITY_TRAITS = ("WE", "INT", "LEA", "LOY", "GRD")
_PERSONALITY_LABELS = {"WE": "Work ethic", "INT": "Intelligence", "LEA": "Leadership",
                       "LOY": "Loyalty", "GRD": "Greed"}


def _personality_only(tree):
    """A traits-shaped tree cut down to the five personality lenses, H / N / L order."""
    return {t: {b: tree[t][b] for b in ("H", "N", "L") if b in tree[t]}
            for t in PERSONALITY_TRAITS if t in tree}


def _personality_meta(trait_keys):
    """trait_meta for the personality lenses, built here so it still ships when
    growth_lenses is missing or fails."""
    return {k: {"label": _PERSONALITY_LABELS[k], "buckets": ["H", "N", "L"],
                "bucket_labels": {"H": "High", "N": "Normal", "L": "Low"},
                "basis": "personality",
                "note": (f"{_PERSONALITY_LABELS[k]} from the current pull. Personality is nearly "
                         f"static in OOTP, so the current value stands in for the whole archive.")}
            for k in PERSONALITY_TRAITS if k in trait_keys}


def _personality(league):
    """{pid: {'WE','INT','LEA','LOY','GRD'}} from the CURRENT pull (personality is ~static in
    OOTP; history rows don't store it, so the current value stands in for the
    whole archive — a mid-window personality change mislabels a player's older
    pairs, rare enough to ignore)."""
    out = {}
    for fn in ("hitters.json", "pitchers.json"):
        path = os.path.join(VIZ, "public", "data", league, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                for r in json.load(fh):
                    out[str(r.get("ID"))] = {"WE": r.get("WrkEthic"), "INT": r.get("Int"),
                                             "LEA": r.get("Lead"), "LOY": r.get("Loy"),
                                             "GRD": r.get("Greed")}
        except (OSError, ValueError):
            pass
    return out


def age_curves(conn, league, personality=None, lenses=None, scale=SCALE_DEFAULT):
    """Average rating gain per AGE-YEAR, per column — "how much POW does a
    24-year-old gain before he turns 25" — from ALL consecutive pull pairs.
    scale: "20-80" (default; batting / pitching deltas in internal points,
    rated = >= 20) or "1-100" (every delta in display points, rated = > 0).

    Method (user spec 2026-09-04; the old version averaged per PULL PAIR, which
    is meaningless when pulls are days-to-weeks apart and irregular):
      - a pair's IN-GAME span (years) = share of its org'd shared players whose
        integer age ticked up (every player has exactly one birthday per
        game-year, so the aged fraction IS the elapsed fraction of a year); a
        pair with no in-game time (re-pull, frozen sim date) is SKIPPED — its
        deltas are scout churn, not development
      - a player's delta is attributed to the age he WAS: fully to his starting
        age when he did not age up; split half/half (delta and exposure alike)
        when his birthday crossed the pair; an age jump outside 0..1 is a merge
        glitch and dropped
      - per (col, age): gain/yr = total delta / total player-years observed
        (exposure-weighted ratio of sums — irregular gaps cannot bias it),
        plus the observation count and the player-years
      - MLB/minors only: rows with an org attached (FA pool / draft class out)
      - both values must be rated (>= 20) — same absent-skill guard as movers
      - a pair that holds a rating SCALE EVENT (league-wide re-scout) is skipped
        per side, measured by pair_guard(): see the guard notes above GUARD_*.
        meta["skipped_pairs"] lists every skipped (pair, side) with its reading
      - personality (from the current pull; ~static): per-trait H/N/L growth
        splits for ages 15-25, keyed WE / INT / LEA / LOY / GRD
      - lenses (growth_lenses.Lenses, optional): adds the context lenses
        (playing time, performance, WAA rank, team leaders) to `traits`, same
        value shape. They do not need a personality record. Any exception from
        the lens object drops the context lenses with a printed note; the
        personality lenses still ship (meta["lens_error"] holds the reason)
      - meta["trait_players"] / meta["gap_players"] count DISTINCT players per
        shipped cell; a traits cell without a player count is never returned
    Returns (curves, gaps, traits, meta):
      curves {col: {age: (gain_per_yr, n_obs, years)}}
      traits {trait: {bucket: {col: {age: (gain_per_yr, n_obs, years)}}}}"""
    pulls = league_pulls(conn, league)
    sums, yrs, cnt = {}, {}, {}
    gsums, gyrs, ggapyrs, gcnt, gpids = {}, {}, {}, {}, {}      # gap-conditioned growth
    # personality / lens x gap growth, one flat cell per (trait, bucket, col, age):
    # [delta sum, player-years, gap-weighted years, observations, distinct player ids]
    tcells = {}
    players_by_age = {}
    pairs_used = pairs_skipped = pairs_contaminated = 0
    span_total = 0.0
    skipped_pairs, guard_pairs = [], []
    lens_error = None                 # first exception raised by the lens object
    game_dates = _stored_game_dates(conn, league, pulls)
    if not game_dates and _dump_source(conn, league) is not None:
        game_dates = {p[0]: p[1] for p in pulls}      # a dump vintage's real date IS its in-game date
    floor = rated_floor(scale)

    def _lens_failed(where, e):
        msg = f"{where} raised {type(e).__name__}: {e}"
        print(f"  lenses {league}: {msg}. Context lenses (PT / PERF / WAA / LDR / NEG) dropped; "
              f"the personality lenses still ship")
        return msg

    def _game(pid_):
        d = (getattr(lenses, "dates", None) or {}).get(pid_)
        return d.isoformat() if d is not None else game_dates.get(pid_)

    prev = None
    prev_pull = None
    for pull in pulls:
        pull_id = pull[0]
        cur = load_pull_map(conn, pull_id)
        if prev is not None:
            shared = []
            for pid, nrec in cur.items():
                orec = prev.get(pid)
                if not orec:
                    continue
                if orec.get("org") in (None, "", "0", 0):
                    continue
                try:
                    a1 = int(float(orec["age"]))
                    d = int(float(nrec["age"])) - a1
                except (TypeError, ValueError):
                    continue
                if d in (0, 1):
                    shared.append((pid, orec, nrec, a1, d))
            span = (sum(s[4] for s in shared) / len(shared)) if shared else 0.0
            # scale-event guard, per side (see GUARD_* above): measured on EVERY pair
            guard = pair_guard(shared, floor)
            # A dump league holds TRUE ratings written once a game-year: there is
            # no scout to re-rate anyone, and a whole year of real development
            # legitimately moves the league median a step (DEV 2026: K vR +5
            # across 3,144 hitters). The guard exists for scout re-scale events
            # between StatsPlus pulls days apart; it is measured and reported for
            # dump leagues but never skips their pairs.
            dump_league = _dump_source(conn, league) is not None
            dirty = {s for s in SIDES if guard[s]["reason"]} if (span > 0 and not dump_league) else set()
            if dump_league:
                for s in SIDES:
                    if guard[s]["reason"]:
                        guard[s]["reason"] = ""          # noted below, not acted on
                        guard[s]["note"] = "true-ratings dump league: guard is informational"
            guard_pairs.append({"real_from": prev_pull[1], "real_to": pull[1],
                                "game_from": _game(prev_pull[0]), "game_to": _game(pull[0]),
                                "span_years": span, "skipped": sorted(dirty), "guard": guard})
            for s in SIDES:
                if s in dirty:
                    g = guard[s]
                    skipped_pairs.append({
                        "real_from": prev_pull[1], "real_to": pull[1],
                        "game_from": _game(prev_pull[0]), "game_to": _game(pull[0]),
                        "side": s, "reason": g["reason"],
                        "measured": _guard_measured(g, span)})
            if span <= 0:
                pairs_skipped += 1
            elif len(dirty) == len(SIDES):
                pairs_contaminated += 1
            else:
                pairs_used += 1
                span_total += span
                # Ovr / Pot cover both sides: they need BOTH sides clean
                clean = lambda c: (not dirty) if c in EXTRA_COLS else (col_side(c) not in dirty)
                trend_cols = [c for c in AGE_TREND_COLS if clean(c)]
                gap_cols = [(c, pc) for c, pc in ALL_GAP_PAIRS.items() if clean(c)]
                if lenses is not None and lens_error is None:
                    try:
                        lenses.start_pair(prev_pull, pull, prev)
                    except Exception as e:
                        lens_error = _lens_failed("start_pair", e)
                for pid, orec, nrec, a1, d in shared:
                    parts = ((a1, 1.0),) if d == 0 else ((a1, 0.5), (a1 + 1, 0.5))
                    pers = (personality or {}).get(pid) or {}
                    tb = None      # {is_pitcher_rating: [(trait, bucket), ...]}, built on first use
                    for age, _w in parts:
                        players_by_age.setdefault(age, set()).add(pid)
                    for c in trend_cols:
                        a, b = orec.get(c), nrec.get(c)
                        if a is None or b is None or a < floor or b < floor:
                            continue
                        delta = rating_delta(c, a, b, scale)     # internal points for batting/pitching (20-80), display steps otherwise
                        for age, w in parts:
                            ca = sums.setdefault(c, {})
                            ca[age] = ca.get(age, 0.0) + delta * w
                            ya = yrs.setdefault(c, {})
                            ya[age] = ya.get(age, 0.0) + span * w
                            na = cnt.setdefault(c, {})
                            na[age] = na.get(age, 0) + 1
                    # GAP-CONDITIONED growth (user): only spots where current sits
                    # BELOW potential at the pair's start — a maxed rating (45/45)
                    # contributes nothing, so it can never drag down the growth of
                    # players who actually have room. Gap re-read every pair, so a
                    # re-scout or a caught-up current switches tracking by itself.
                    for c, pc in gap_cols:
                        a, b, p = orec.get(c), nrec.get(c), orec.get(pc)
                        if a is None or b is None or p is None or a < floor or b < floor or p < floor:
                            continue
                        gap = rating_delta(c, a, p, scale)       # internal points (batting/pitching, 20-80) or display
                        if gap <= 0:
                            continue
                        delta = rating_delta(c, a, b, scale)
                        for age, w in parts:
                            g1 = gsums.setdefault(c, {})
                            g1[age] = g1.get(age, 0.0) + delta * w
                            g2 = gyrs.setdefault(c, {})
                            g2[age] = g2.get(age, 0.0) + span * w
                            g3 = ggapyrs.setdefault(c, {})
                            g3[age] = g3.get(age, 0.0) + gap * span * w
                            g4 = gcnt.setdefault(c, {})
                            g4[age] = g4.get(age, 0) + 1
                            gpids.setdefault(c, {}).setdefault(age, set()).add(pid)
                            # the context lenses need no personality record (their own
                            # gate is org + not foreign); the personality lenses do
                            if 15 <= age <= 25 and (pers or (lenses is not None and lens_error is None)):
                                if tb is None:
                                    if lenses is not None and lens_error is None:
                                        try:
                                            tb = lenses.player_buckets(pid, pers, orec)
                                        except Exception as e:
                                            lens_error = _lens_failed("player_buckets", e)
                                    if tb is None:
                                        hnl = [(t, pers.get(t)) for t in PERSONALITY_TRAITS
                                               if pers.get(t) in ("H", "N", "L")]
                                        tb = {True: hnl, False: hnl}
                                # a pitcher rating, or the Ovr of a pitcher, reads the pitcher buckets
                                pit_rating = c in _PIT_CORE or (c in OVERALL_PAIRS and (orec.get("pos") or "").upper() in PIT_POS)
                                for trait, bk in tb[pit_rating]:
                                    cell = tcells.get((trait, bk, c, age))
                                    if cell is None:
                                        cell = tcells[(trait, bk, c, age)] = [0.0, 0.0, 0.0, 0, set()]
                                    cell[0] += delta * w
                                    cell[1] += span * w
                                    cell[2] += gap * span * w
                                    cell[3] += 1
                                    cell[4].add(pid)
        prev = cur
        prev_pull = pull
    curves = {c: {age: (sums[c][age] / yrs[c][age], cnt[c][age], yrs[c][age])
                  for age in sorted(sums[c]) if yrs[c][age] > 0}
              for c in sums}
    # gaps: (points gained per year among gap holders, share of the gap closed per
    # year — the drafting number, exposure-and-gap weighted, n, player-years)
    gaps, gap_players = {}, {}
    for c in gsums:
        for age in gsums[c]:
            y, gy = gyrs[c][age], ggapyrs[c][age]
            if y > 0 and gy > 0:
                gaps.setdefault(c, {})[age] = (gsums[c][age] / y, gsums[c][age] / gy,
                                               gcnt[c][age], y)
                gap_players.setdefault(c, {})[age] = len(gpids[c][age])
    traits, trait_players = {}, {}
    for (trait, bk, c, age), (s, y, gy, n, pids) in sorted(tcells.items()):
        if y > 0 and gy > 0:
            traits.setdefault(trait, {}).setdefault(bk, {}).setdefault(c, {})[age] = (s / y, s / gy, n, y)
            trait_players.setdefault(trait, {}).setdefault(bk, {}).setdefault(c, {})[age] = len(pids)
    if lenses is not None and lens_error is None:
        # drop a lens that failed part-way (its sums cover only some pairs), then
        # put lenses and buckets in display order
        try:
            traits, trait_players = lenses.finish(traits), lenses.finish(trait_players)
        except Exception as e:
            lens_error = _lens_failed("finish", e)
    if lenses is None or lens_error is not None:
        # no lens object, or it failed: its sums may cover only some pairs
        traits, trait_players = _personality_only(traits), _personality_only(trait_players)
    # SAMPLE HONESTY: the UI gates on distinct players, so a traits cell never
    # ships without its player count (1 <= players <= pair observations)
    bad = 0
    for trait, bks in traits.items():
        for bk, cols in bks.items():
            for c, ages in cols.items():
                for age in list(ages):
                    p = trait_players.get(trait, {}).get(bk, {}).get(c, {}).get(age)
                    if not isinstance(p, int) or not 1 <= p <= ages[age][2]:
                        del ages[age]
                        bad += 1
    if bad:
        print(f"  age_curves {league}: {bad} trait cells had no valid distinct-player count; not shipped")
    meta = {"vintages": len(pulls), "pairs_used": pairs_used, "pairs_skipped": pairs_skipped,
            "pairs_contaminated": pairs_contaminated, "skipped_pairs": skipped_pairs,
            "guard_pairs": guard_pairs, "lens_error": lens_error,
            "span_years": span_total, "trait_players": trait_players, "gap_players": gap_players,
            "players": {age: len(s) for age, s in sorted(players_by_age.items())},
            "observations": sum(n for c in cnt for n in cnt[c].values())}
    return curves, gaps, traits, meta


# ---------------------------------------------------------------- report
def report(db_path=DB_PATH, leagues=None, window=3, top=10):
    conn = connect(db_path)
    for lg in (leagues or LEAGUES):
        pulls = league_pulls(conn, lg)
        gdate = PO.game_dates(conn, lg, pulls)
        print(f"\n=== {lg}: {len(pulls)} vintages (in-game order) ===")
        for pid, date, _ts, src, n in pulls:
            print(f"  real {date}  in-game {gdate.get(pid) or '?':<10}  {src:<12} {n:>6} players")
        if len(live_pulls(conn, lg)) < 2:
            print("  (need >= 2 vintages for movers/age curves)")
            continue
        scale = _scale_of(conn, lg)
        risers, fallers, meta = movers(conn, lg, window=window, top=top, scale=scale)
        print(f"\n  Movers {meta['from']} -> {meta['to']} (last {meta['window']} pull(s); "
              f"{meta['players_changed']} players changed):")
        for label, rows in (("RISERS", risers), ("FALLERS", fallers)):
            print(f"    top {label}:")
            for x in rows:
                bd = ", ".join(f"{c} {d:+g}" for c, d in x["breakdown"].items())
                age = f"{int(x['age'])}" if x["age"] is not None else "?"
                print(f"      {x['total']:+7.1f}  {x['name']:<24} {x['pos'] or '?':<3} "
                      f"age {age:<3} {x['org'] or '?':<22} [{bd}]")
        curves, gaps, _traits, cmeta = age_curves(conn, lg, scale=scale)
        print(f"\n  Gain-per-age-year curves: {cmeta['vintages']} vintages -> "
              f"{cmeta['pairs_used']} pairs used ({cmeta['pairs_skipped']} skipped, no in-game "
              f"time; {cmeta['pairs_contaminated']} skipped, rating scale event on both sides), "
              f"{cmeta['span_years']:.2f} game-years total, "
              f"{cmeta['observations']} (player,col) observations.")
        for sp in cmeta["skipped_pairs"]:
            print(f"  SKIPPED {sp['real_from']} -> {sp['real_to']} [{SIDE_LABEL[sp['side']]}]: {sp['reason']}")
        print("  CAVEAT: a short archive still reflects scout re-grade churn; treat as "
              "directional until many more game-years accumulate.")
        for c in ("POW P", "STU", "SPE", "CON"):
            if c not in curves:
                continue
            pts = [f"{age}:{m:+.2f}/yr(n={n})" for age, (m, n, _y) in curves[c].items()
                   if n >= 50 and 17 <= age <= 38]
            if pts:
                print(f"    {c:<7} " + "  ".join(pts[:12]))
        print(f"  Gap-holder growth (current below potential only; "
              f"{'DISPLAY' if scale == '1-100' else 'INTERNAL'} points gained/yr):")
        for c in ("POW vR", "STU", "CON", "BA vR"):
            if c not in gaps:
                continue
            pts = [f"{age}:{m:+.2f}/yr(n={n})" for age, (m, _cl, n, _y) in gaps[c].items()
                   if n >= 50 and 16 <= age <= 26]
            if pts:
                print(f"    {c:<7} " + "  ".join(pts[:11]))
    conn.close()


def guard_report(db_path=DB_PATH, leagues=None):
    """Print what the scale-event guard measures on EVERY pull pair, per side, so
    the two bars (GUARD_MEDIAN_PTS, GUARD_DOWN_SHARE) can be checked by eye.
    Each league reads its own archive only."""
    conn = connect(db_path)
    for lg in (leagues or LEAGUES):
        _c, _g, _t, cmeta = age_curves(conn, lg, scale=_scale_of(conn, lg))
        print(f"\n=== {lg}: scale-event guard, {len(cmeta['guard_pairs'])} pull pairs "
              f"(bars: |median shift| >= {GUARD_MEDIAN_PTS:g} pts, down share >= {GUARD_DOWN_SHARE:.2f}) ===")
        print(f"  {'real pull pair':<24} {'in-game':<24} {'span':>6}  "
              f"{'PIT n':>6} {'max |median|':>14} {'max down share':>20}  "
              f"{'HIT n':>6} {'max |median|':>14} {'max down share':>20}  verdict")
        for gp in cmeta["guard_pairs"]:
            cells = []
            for s in SIDES:
                g = gp["guard"][s]
                med = f"{g['median_col']} {g['median_shift']:+.1f}" if g["median_col"] else "-"
                dn = (f"{g['down_col']} {g['down_share']:.3f} ({g['down_mean']:+.2f})"
                      if g["down_col"] else "-")
                cells.append(f"{g['players']:>6} {med:>14} {dn:>20}")
            verdict = ("zero time" if gp["span_years"] <= 0
                       else "SKIP " + "+".join(gp["skipped"]) if gp["skipped"] else "kept")
            game = f"{gp['game_from'] or '?'}->{gp['game_to'] or '?'}"
            print(f"  {gp['real_from']}->{gp['real_to']:<12} {game:<24} {gp['span_years']:>6.3f}  "
                  f"{cells[0]}  {cells[1]}  {verdict}")
        kept = [gp for gp in cmeta["guard_pairs"] if gp["span_years"] > 0]
        for s in SIDES:
            clean = [gp["guard"][s] for gp in kept if s not in gp["skipped"]]
            hit = [gp["guard"][s] for gp in kept if s in gp["skipped"]]
            print(f"  {SIDE_LABEL[s]}: kept pairs read |median| <= "
                  f"{max((abs(g['median_shift'] or 0) for g in clean), default=0):.1f}, down share <= "
                  f"{max((g['down_share'] or 0 for g in clean), default=0):.3f}; skipped pairs read "
                  + (", ".join(f"|median| {abs(g['median_shift'] or 0):.1f} / down share {g['down_share'] or 0:.3f}"
                               for g in hit) or "none"))
    conn.close()


# ---------------------------------------------------------------- export
def _jsnum(x):
    if x is None:
        return None
    return int(x) if float(x).is_integer() else round(float(x), 2)


def _org_name_map(lg):
    """Numeric StatsPlus team id -> readable org name (e.g. '1064' -> 'Boston
    Red Sox'), derived OFFLINE: the raw cached pull gives player id -> numeric
    org, the shipped enriched app data gives the same player id -> org NAME;
    majority-vote per numeric id. The trends DB stores the raw numeric ids
    (pulls are archived before enrichment), which is why the Trends screens
    showed numbers nobody can place (user, 2026-08-26). Minor-league team ids
    resolve to the PARENT org name, same as the app. Unknown ids stay numeric."""
    slug = ST.slug(lg)
    raw_path = os.path.join(VIZ, "ingest", ".cache", f"statsplus_{slug}.json")
    votes = {}
    try:
        raw = json.load(open(raw_path, encoding="utf-8"))
        id2num = {}
        for r in raw:
            pid = str(r.get("ID") or "").strip()
            org = str(r.get("ORG") or r.get("Org") or "").strip()
            if pid and org.isdigit():
                id2num[pid] = org
        for fn in ("hitters.json", "pitchers.json"):
            p = os.path.join(VIZ, "public", "data", lg, fn)
            if not os.path.exists(p):
                continue
            for r in json.load(open(p, encoding="utf-8")):
                n = id2num.get(str(r.get("ID") or "").strip())
                name = str(r.get("ORG") or "").strip()
                if n and name and not name.isdigit():
                    votes.setdefault(n, {})
                    votes[n][name] = votes[n].get(name, 0) + 1
    except Exception:
        return {}
    out = {k: max(v.items(), key=lambda kv: kv[1])[0] for k, v in votes.items()}
    # Best-effort fallback for team ids with NO players in the shipped app data
    # (NPB clubs are filtered out of the app by design; defunct/renamed clubs
    # only exist in old vintages): the StatsPlus /teams endpoint names them
    # (with this league's saved token; the date-keyed cache reuses the reply
    # refresh.py read while the in-game date is unchanged). Vote-derived names
    # win — they match the app's parent-org naming.
    try:
        sys.path.insert(0, os.path.join(VIZ, "ingest"))
        import statsplus as S
        for tid, name in S.team_name_map(S.fetch_teams(S.normalize_base(slug), cache=True)).items():
            if name:
                out.setdefault(str(tid), name)
    except Exception as e:
        # offline export keeps the numeric ids for those few; a refusal says so
        if isinstance(e, getattr(sys.modules.get("statsplus"), "StatsPlusRefused", ())):
            print(f"  WARNING: {lg} team names: {e.user_message(lg)} The trends file keeps the "
                  f"{len(out)} names it has; other teams show their numeric id.")
    return out


def _dump_source(conn, league):
    """dump_source.DumpSource for a dump-sourced league, else None. Never raises."""
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import dump_source
        return dump_source.for_league(conn, league)
    except Exception:
        return None


def export(db_path=DB_PATH, leagues=None, hist_pulls=6, mover_windows=(1, 3, 5), top=40, out_dir=None):
    """Write public/data/<LG>/rating_trends.json — the app-facing trends file.
    Small by construction: only players with >= 1 changed rating inside the
    last `hist_pulls` vintages, only the columns that changed, values from
    those vintages only. Purely informational — projections never read it.
    out_dir: write DIR/<LG>/rating_trends.json instead (tests, scratch runs).
    A dump-sourced league takes its org names, personality and scale from
    dump_source; the StatsPlus path is unchanged."""
    conn = connect(db_path)
    written = []
    for lg in (leagues or LEAGUES):
        src = _dump_source(conn, lg)
        scale = src.scale if src is not None else SCALE_DEFAULT
        org_names = {} if src is not None else _org_name_map(lg)
        _org = lambda v: org_names.get(str(v), v) if v is not None and str(v).isdigit() else v
        pulls = league_pulls(conn, lg)          # in-game order, asof snapshots included
        gdate = PO.game_dates(conn, lg, pulls)
        live_idx = [i for i, p in enumerate(pulls) if p[3] != ASOF]
        if leagues and not pulls:
            print(f"export: {lg} has no vintages in {db_path}; nothing written")
            raise SystemExit(4)
        if out_dir:
            out_path = os.path.join(out_dir, lg, "rating_trends.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
        else:
            out_path = os.path.join(VIZ, "public", "data", lg, "rating_trends.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)   # a new (dump) league has no folder yet
        payload = {
            "v": 1, "league": lg,
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            # d = real date, s = source, g = in-game date (the list order)
            "pulls": [{"d": p[1], "s": p[3], "g": gdate.get(p[0])} for p in pulls],
            "cols": ALL_COLS,
            "players": {},
            "movers": {},
            "age_curves": {},
        }
        if src is not None:
            payload["source"] = "dump"
            payload["scale"] = scale
        if len(pulls) >= 2 and live_idx:
            # the window = the last hist_pulls LIVE pulls (an asof snapshot is a
            # past card, not a recent pull); indices point into payload["pulls"]
            payload["window"] = live_idx[-hist_pulls:]
            win = [pulls[i] for i in payload["window"]]
            maps = [load_pull_map(conn, p[0]) for p in win]
            latest = maps[-1]
            newest_first = list(reversed(maps))
            ids = set()
            for m in maps:
                ids.update(m)
            for pid in ids:
                series = {}
                for ci, c in enumerate(ALL_COLS):
                    vals = [m.get(pid, {}).get(c) for m in maps]
                    got = [v for v in vals if v is not None]
                    if len(got) >= 2 and max(got) - min(got) > 1e-9:
                        series[str(ci)] = [_jsnum(v) for v in vals]
                if not series:
                    continue
                meta = latest.get(pid) or next(m[pid] for m in newest_first if pid in m)
                payload["players"][pid] = {
                    "n": meta["name"], "p": meta["pos"],
                    "o": _org(_readable(newest_first, pid, "org")),
                    "a": _jsnum(meta["age"]),
                    "l": _readable(newest_first, pid, "lev"), "s": series,
                }
            for w in mover_windows:
                if w > len(live_idx) - 1:
                    continue
                risers, fallers, meta = movers(conn, lg, window=w, top=top, scale=scale)
                payload["movers"][str(w)] = {
                    "from": meta["from"], "to": meta["to"],
                    "changed": meta["players_changed"],
                    "risers": [{"id": x["id"], "n": x["name"], "p": x["pos"],
                                "a": _jsnum(x["age"]), "o": _org(x["org"]),
                                "t": round(x["total"], 1), "c": x["ncols"],
                                "g": x["gained"], "x": x["lost"],
                                "d": {c: _jsnum(d) for c, d in x["breakdown"].items()}}
                               for x in risers],
                    "fallers": [{"id": x["id"], "n": x["name"], "p": x["pos"],
                                 "a": _jsnum(x["age"]), "o": _org(x["org"]),
                                 "t": round(x["total"], 1), "c": x["ncols"],
                                 "g": x["gained"], "x": x["lost"],
                                 "d": {c: _jsnum(d) for c, d in x["breakdown"].items()}}
                                for x in fallers],
                }
            # Development lenses (growth_lenses.py): informational, never fatal. No
            # module or no network only removes lenses; the export still ships.
            if src is not None:
                try:
                    pers = src.personality()
                except Exception as e:
                    pers = {}
                    print(f"  lenses {lg}: personality not read from the vintage file ({type(e).__name__}: {e})")
            else:
                pers = _personality(lg)
            GL = lenses = None
            try:
                if HERE not in sys.path:
                    sys.path.insert(0, HERE)
                import growth_lenses as GL
                lenses = GL.Lenses(conn, lg, pers)
            except Exception as e:
                lenses = None
                print(f"  lenses {lg}: unavailable ({type(e).__name__}: {e}); personality lenses only")
            curves, gaps, traits, cmeta = age_curves(conn, lg, personality=pers, lenses=lenses, scale=scale)
            # NEVER FATAL: info / trait_meta are wrapped like player_buckets / finish.
            # Any exception drops the context lenses; the personality lenses still ship.
            trait_players = cmeta["trait_players"]
            lens_error = cmeta["lens_error"]
            lens_info, trait_meta = {}, None
            if lenses is not None and lens_error is None:
                try:
                    lens_info = lenses.info()
                    trait_meta = GL.trait_meta(traits, lens_info)
                except Exception as e:
                    lens_error = f"{'trait_meta' if lens_info else 'info'} raised {type(e).__name__}: {e}"
                    print(f"  lenses {lg}: {lens_error}. Context lenses (PT / PERF / WAA / LDR / NEG) "
                          f"dropped; the personality lenses still ship")
            if trait_meta is None:
                traits, trait_players = _personality_only(traits), _personality_only(trait_players)
                trait_meta = _personality_meta(traits)
                if lens_error is not None:
                    lens_info = {"pit_cols": list(_PIT_CORE),
                                 "dropped": {k: lens_error for k in ("PT", "PERF", "WAA", "LDR", "NEG")}}
            # rating scale events the guard measured and skipped (pair_guard)
            skipped = cmeta["skipped_pairs"]
            kept = [(gp, s) for gp in cmeta["guard_pairs"] if gp["span_years"] > 0
                    for s in SIDES if s not in gp["skipped"]]
            guard_info = {
                "median_pts": GUARD_MEDIAN_PTS, "down_share": GUARD_DOWN_SHARE,
                "rule": ("A pull pair is skipped for one side (pitcher ratings / hitter ratings) "
                         "when the median shift of a gap-tracked current rating or its potential "
                         f"reaches {GUARD_MEDIAN_PTS:g} points across that side's players, or when "
                         f"{GUARD_DOWN_SHARE:.0%} of them lose points on one current rating."),
                "max_kept": {s: {"median_shift": max((abs(gp["guard"][s]["median_shift"] or 0.0)
                                                      for gp, s2 in kept if s2 == s), default=None),
                                 "down_share": max((round(gp["guard"][s]["down_share"] or 0.0, 4)
                                                    for gp, s2 in kept if s2 == s), default=None)}
                             for s in SIDES}}
            skip_txt = ""
            if skipped:
                by_pair = {}
                for sp in skipped:
                    by_pair.setdefault((sp["real_from"], sp["real_to"], sp["game_from"], sp["game_to"]),
                                       []).append(sp)
                skip_txt = (" Skipped as rating scale events (league-wide re-scout, measured by the "
                            "guard): " + "; ".join(
                                f"{rf} to {rt}" + (f" (in-game {gf} to {gt})" if gf and gt else "")
                                + ", " + " and ".join(SIDE_LABEL[sp["side"]] for sp in sps)
                                + ": " + " / ".join(sp["reason"].replace("rating scale event: ", "")
                                                    for sp in sps)
                                for (rf, rt, gf, gt), sps in by_pair.items()) + ".")
            if scale == "1-100":
                # a 1-100 league: no band table, every gain / gap in display points
                unit_fields = {
                    "units": "display",
                    "units_by_col": {c: "display" for c in list(curves.keys()) + list(ALL_GAP_PAIRS.keys())},
                    "underlying_band": {}, "underlying_mid": {},
                    "underlying_note": ("This league shows ratings on the 1-100 scale. Nothing is mapped to "
                                        "OOTP's internal points: every gain and gap is in 1-100 display points. "
                                        "A skill counts as rated when it is above 0. Guard readings (median "
                                        "shift, down share) are display points."),
                    "note": (f"Average rating GAIN PER YEAR OF AGE in 1-100 display points (true ratings from "
                             f"the yearly dump, no scout noise): how much a player at this age gains before "
                             f"he ages up, MLB/minors only, exposure-weighted across {cmeta['pairs_used']} "
                             f"consecutive yearly vintages ({cmeta['span_years']:.2f} game-years; "
                             f"{cmeta['pairs_skipped']} zero-time pairs skipped). A short archive is still "
                             f"directional. It sharpens as seasons accumulate." + skip_txt)}
            else:
                unit_fields = {
                    # every gain / gap below is in OOTP's INTERNAL points (display
                    # bands mapped to their middles), not 20-80 display steps
                    "units": "internal",
                    "units_by_col": {c: col_units(c) for c in list(curves.keys()) + list(ALL_GAP_PAIRS.keys())},
                    "underlying_band": {str(k): list(v) for k, v in UNDERLYING_BAND.items()},
                    "underlying_mid": {str(k): v for k, v in UNDERLYING_MID.items()},
                    "underlying_note": ("Band table is the user's OOTP 26 mapping (approximate). Measured on this "
                                        "archive: 20 is read at 115.5 (players sit near the top of the floor band); "
                                        "fielding, running, stamina, hold and pitch ratings are NOT converted "
                                        "(no narrowing above 55 for them) and stay in display steps. Guard "
                                        "readings (median shift, down share) are 20-80 display points."),
                    "note": (f"Average rating GAIN PER YEAR OF AGE: batting and pitching ratings in OOTP's "
                             f"internal 1-600 points (the 20-80 display is an uneven banding of them; each "
                             f"rating is read inside its band before the difference is taken; band edges "
                             f"approximate), fielding/running in 20-80 display steps. How much a player at "
                             f"this age gains before he ages up, MLB/minors only, exposure-weighted across "
                             f"{cmeta['pairs_used']} consecutive pull pairs "
                             f"({cmeta['span_years']:.2f} game-years; {cmeta['pairs_skipped']} "
                             f"zero-time pairs skipped as scout churn). A short archive is still "
                             f"directional. It sharpens automatically as game-years accumulate."
                             + skip_txt)}
            payload["age_curves"] = {
                "vintages": cmeta["vintages"], "pairs": cmeta["pairs_used"],
                "pairs_skipped": cmeta["pairs_skipped"],
                "pairs_contaminated": cmeta["pairs_contaminated"],
                "skipped_pairs": skipped,
                "guard": guard_info,
                "span_years": _jsnum(cmeta["span_years"]),
                **unit_fields,
                "cols": {c: {str(age): [round(g, 3), n, round(y, 1)]
                             for age, (g, n, y) in ages.items()}
                         for c, ages in curves.items()},
                # GAP-CONDITIONED growth: only players whose current sat BELOW
                # potential for that rating at the pair start (maxed players never
                # dilute it). Values: [points gained/yr, share of gap closed/yr,
                # n, player-years]. The DISPLAY unit is POINTS/yr (user 2026-09-04:
                # %-of-gap is a ratio of two fuzzy quantities — a "5-point gap" at
                # 45 is not a 5-point gap at 25); closure ships as a secondary
                # field only.
                "gaps": {c: {str(age): [round(g, 3), round(cl, 4), n, round(y, 1)]
                             for age, (g, cl, n, y) in ages.items()}
                         for c, ages in gaps.items()},
                # DISTINCT players behind every gaps cell (n counts pull-pair observations)
                "gap_players": {c: {str(age): n for age, n in ages.items()}
                                for c, ages in cmeta["gap_players"].items()},
                # personality growth splits (gap-conditioned too), ages 15-25
                "traits": {t: {bk: {c: {str(age): [round(g, 3), round(cl, 4), n, round(y, 1)]
                                        for age, (g, cl, n, y) in ages.items()}
                                    for c, ages in cols.items()}
                               for bk, cols in bks.items()}
                           for t, bks in traits.items()},
                # lens display metadata (labels, ordered buckets, notes), DISTINCT
                # players behind every traits cell, and how the lenses were built
                # (in-game dates of the first / last pull, seasons used, drops)
                "trait_meta": trait_meta,
                # one distinct-player count for EVERY shipped traits cell, and no other
                # (age_curves already removed any cell without a valid count)
                "trait_players": {t: {bk: {c: {str(age): trait_players[t][bk][c][age] for age in ages}
                                           for c, ages in cols.items()}
                                      for bk, cols in bks.items()}
                                  for t, bks in traits.items()},
                "lens_info": lens_info,
            }
            if src is not None:
                # the rating scale of a dump-sourced league; TGS / BLM payloads carry no key
                payload["age_curves"]["scale"] = scale
                payload["age_curves"]["source"] = "dump"
            for sp in skipped:
                print(f"  age_curves {lg}: SKIPPED {sp['real_from']} -> {sp['real_to']} "
                      f"[{SIDE_LABEL[sp['side']]}]: {sp['reason']}")
            if lens_info.get("first_pull"):
                fp, lp = lens_info["first_pull"], lens_info["last_pull"]
                print(f"  lenses {lg}: in-game {fp['game']} (pull {fp['real']}) .. {lp['game']} "
                      f"(pull {lp['real']}); seasons "
                      + ", ".join(f"{y} ({'final' if s['final'] else 'as of ' + str(s['asof']) if s.get('asof') else 'no stats'}, "
                                  f"{s['pairs']} pairs"
                                  + (f", {s['pairs_left_out']} left out" if s.get("pairs_left_out") else "")
                                  + ")" for y, s in lens_info["seasons"].items())
                      + f"; lenses shipped: {' '.join(payload['age_curves']['trait_meta'])}")
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        for attempt in range(4):
            # Write to a .tmp file, then swap it in. Windows refuses the swap (Errno
            # 13 / 22) while another process holds the target (dev server, virus
            # scan). The lock is short: wait and retry.
            try:
                os.replace(tmp_path, out_path)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(1.5)
        size = os.path.getsize(out_path)
        print(f"export: {lg} -> {os.path.relpath(out_path, REPO)} "
              f"({size / 1e6:.2f} MB, {len(payload['players'])} players with changes, "
              f"{len(pulls)} vintages)")
        written.append(out_path)
    conn.close()
    return written


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backfill", action="store_true", help="ingest every recoverable vintage")
    ap.add_argument("--rebuild", action="store_true", help="with --backfill: drop the DB first")
    ap.add_argument("--append", metavar="CACHE_JSON", help="ingest one raw pull cache file")
    ap.add_argument("--league", help="league id (TGS/BLM); required with --append")
    ap.add_argument("--date", help="vintage date YYYY-MM-DD for --append (default today)")
    ap.add_argument("--source", default="live", help="source label for --append")
    ap.add_argument("--game-date", help="in-game date YYYY-MM-DD of the pull for --append")
    ap.add_argument("--report", action="store_true", help="print vintages, movers, age curves")
    ap.add_argument("--export", action="store_true", help="write public/data/<LG>/rating_trends.json")
    ap.add_argument("--guard", action="store_true",
                    help="print the scale-event guard reading of EVERY pull pair (both sides)")
    ap.add_argument("--window", type=int, default=3, help="mover window in pulls (report)")
    ap.add_argument("--top", type=int, default=10, help="movers shown per direction (report)")
    ap.add_argument("--db", default=DB_PATH, help="database path")
    ap.add_argument("--out", metavar="DIR", help="with --export: write DIR/<LG>/rating_trends.json instead")
    args = ap.parse_args()

    did = False
    if args.backfill:
        backfill(db_path=args.db, rebuild=args.rebuild)
        did = True
    if args.append:
        if not args.league:
            ap.error("--append requires --league")
        rows = json.load(open(args.append, encoding="utf-8"))
        pid = append_pull(args.league, rows, source=args.source, real_date=args.date,
                          files=[args.append], db_path=args.db, game_date=args.game_date)
        print(f"append: {args.league} {args.date or 'today'} -> pull_id {pid}")
        did = True
    lgs = [args.league] if args.league and not args.append else None
    if args.report:
        report(db_path=args.db, leagues=lgs, window=args.window, top=args.top)
        did = True
    if args.export:
        export(db_path=args.db, leagues=lgs, out_dir=args.out)
        did = True
    if args.guard:
        guard_report(db_path=args.db, leagues=lgs)
        did = True
    if not did:
        ap.print_help()


if __name__ == "__main__":
    main()
