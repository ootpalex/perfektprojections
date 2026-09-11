"""
r5.py — Rule 5 draft pool export -> public/data/<LG>/r5.json

Same contract as iafa.py: the in-game export supplies ONLY membership (which
players are exposed in the Rule 5 draft). Everything else — projections,
ceilings, FV, dollars — already exists in the main pull and joins on ID, so no
projection is recomputed here and none should be: the same player must not
carry two different WAA depending on which file the app read.

The point of the screen (the model's R5 edge): eligibility is public, but the
rest of the league shops this pool by OVR/POT card. The app joins the pool
against OUR projections, so the sort surfaces exposed players whose engine
line outruns their card — and, on the flip side, whether one of OUR unprotected
guys is somebody a projecting GM would steal.

    python ingest/r5.py [--league TGS] [--csv <path>] [--write]

A missing export is NOT an error — it just means the pool has not been exported
this cycle; the app treats an absent file as an empty pool.
"""
import os
import sys
import csv
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_OOTP26 = r"C:\OOTP 26\data\saved_games"
_OOTP27 = os.path.join(os.path.expanduser("~"), "Documents", "Out of the Park Developments",
                       "OOTP Baseball 27", "saved_games")

FNAME = "major_league_baseball_draft_pool_-_draft_pool_fa_screen.csv"
DEFAULT_CSV = {
    "TGS": os.path.join(_OOTP26, "TheGrandestSalami.lg", "import_export", FNAME),
    "BLM": os.path.join(_OOTP27, "BLM.lg", "import_export", FNAME),
}

# ID is the join key; the rest is display fallback for anyone missing from the pull.
KEEP = ("ID", "Name", "POS", "Age")


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def load_pool(path):
    if not path or not os.path.exists(path):
        return []
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    if age_days > 14:
        print(f"  WARNING: export is {age_days:.0f} days old — re-export if the pool has turned over")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        pid = str(r.get("ID") or "").strip()
        name = str(r.get("Name") or "").strip()
        if not pid or not name:
            continue
        out.append({k: (str(r.get(k) or "").strip() or None) for k in KEEP})
    return out


def main():
    league = _arg("--league", "TGS")
    write = "--write" in sys.argv
    path = _arg("--csv") or DEFAULT_CSV.get(league)
    pool = load_pool(path)

    if not pool:
        print(f"R5 {league}: no export found at {path or '(none configured)'} — nothing to do")
        return 0

    ids = {p["ID"] for p in pool}
    if len(ids) != len(pool):
        print(f"  WARNING: {len(pool) - len(ids)} duplicate IDs in the export")

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
    print(f"R5 {league}: {len(pool)} in the export, {matched} matched in the shipped data")
    if matched < len(pool):
        print(f"  WARNING: {len(pool) - matched} unmatched — re-run a ratings refresh so both "
              f"sides are the same vintage")

    out_path = os.path.join(data_dir, "r5.json")
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
