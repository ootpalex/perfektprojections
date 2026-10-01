"""
iafa.py — international amateur free agent pool -> public/data/<LG>/iafa.json

The ratings pull cannot identify these players. All 129 StatsPlus fields were checked:
there is no nationality, country, birthplace or amateur flag, so an unsigned 16-year-old
international prospect is indistinguishable from any other unsigned 16-year-old. The
in-game export is the only source that names the class.

It is also the only source for the two things that decide whether you sign one:
    DEM   signing demand  ($190k..$350k)
    Sign  signability     (Very Easy / Easy / ...)

Everything else — ratings, projections, FV, dollar values — already exists in the main
pull and joins on ID, so this writes ONLY the membership list plus those two columns. No
projection is recomputed here and none should be: the same player must not be able to
carry two different WAA depending on which file the app read.

    python ingest/iafa.py [--league TGS] [--csv <path>] [--write]

Without --write it reports what it would do. A missing export is NOT an error — it just means that
league's class has not been exported yet, and the app treats an absent file as an empty
pool rather than breaking.
"""
import os
import sys
import csv
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402

FNAME = "mlb_transactions_free_agents_-_international_amateur_fa_fa_screen.csv"
# The export in each online league's OOTP save (settings ootp_version + ootp_save).
# BLM has an international phase too; this is where its export will land.
DEFAULT_CSV = {
    lg: os.path.join(ST.ootp_save_dir(lg), "import_export", FNAME)
    for lg, e in ST.leagues(include_disabled=True).items()
    if e.get("type") == "statsplus" and ST.ootp_save_dir(lg)
}

# Carried through to the app. ID is the join key; the rest is what StatsPlus lacks.
KEEP = ("ID", "Name", "POS", "Age", "DEM", "Sign")


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def load_pool(path):
    """Read the export. Returns [] when the file is absent (class not exported yet)."""
    if not path or not os.path.exists(path):
        return []
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days > 14:
        print(f"  WARNING: export is {age_days:.0f} days old — re-export if the class has turned over")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        pid = str(r.get("ID") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not pid or not name:
            continue          # blank trailing rows
        out.append({k: (str(r.get(k) or "").strip() or None) for k in KEEP})
    return out


def main():
    league = _arg("--league", "TGS")
    write = "--write" in sys.argv
    path = _arg("--csv") or DEFAULT_CSV.get(league)
    pool = load_pool(path)

    if not pool:
        print(f"IAFA {league}: no export found at {path or '(none configured)'} — nothing to do")
        return 0

    ids = {p["ID"] for p in pool}
    if len(ids) != len(pool):
        print(f"  WARNING: {len(pool) - len(ids)} duplicate IDs in the export")

    # Join check against the shipped data — a miss means the export and the ratings pull
    # are from different vintages, which would silently drop players from the board.
    data_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    matched = 0
    for fn in ("hitters.json", "pitchers.json"):
        fp = os.path.join(data_dir, fn)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as fh:
            rows = json.load(fh)
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
        matched += sum(1 for r in rows if str(r.get("ID") or "").strip() in ids)
    print(f"IAFA {league}: {len(pool)} in the export, {matched} matched in the shipped data")
    if matched < len(pool):
        print(f"  WARNING: {len(pool) - matched} unmatched — re-run a ratings refresh so both "
              f"sides are the same vintage")

    out_path = os.path.join(data_dir, "iafa.json")
    if not write:
        print(f"  (dry run) would write {out_path}  — pass --write")
        return 0
    os.makedirs(data_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(pool, fh, ensure_ascii=False)
    print(f"  wrote {os.path.relpath(out_path, REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
