"""
roster_export.py - merge the OOTP org screen export (org.csv) into a pull's
player records by player ID, for the roster-management fields StatsPlus does not
serve.

Why. The StatsPlus pull has ratings, contracts and service days, but no option
years, no Rule 5 flag, no 40-man flag and no rookie status (see
src/lib/serviceTime.js). OOTP's own org export carries them. Where a field has
no verified StatsPlus source, this module takes OOTP's value as exported; it
never computes one from a rule (standing rule: OOTP's rules are not re-derived).
A player the export does not list simply gets no keys: the field is unknown,
not "No".

Off by default. A league opts in with the optional setting leagues.<id>.roster_export
(tools/settings.py). With no setting, no file, or a file that fails its checks,
the pull is unchanged and (for the last two) says why in one WARNING line.

What it adds (NEW keys only; a key the record already has is never overwritten):

  export column  record key             value
  ON40           On40Man                bool   on the 40-man roster
  ACT            ActiveRoster           bool   on the active (26-man) roster
  OPT            OptionsUsed            int    option years used (0-3)
  OY             OptionYearUsed         int    the export's option-year column (0-3;
                                               the app reads > 0 as "burning one")
  R5             Rule5Eligible          bool   currently Rule 5 eligible
  ROOK           RookieStatus           bool
  IC             IntlComplex            bool
  YL             ContractStatus         text   OOTP's own "2 (arbitr.)" string
  FAT            FAType                 text   free-agent type (A / B)
  Sign           SignDifficulty         text
  DEM            ContractDemand         text   as exported, "$860k"
  TXN            LastTransaction        text
  TXNDT          LastTransactionDate    ISO date
  (derived)      RosterExportDate       ISO date of the export (see below)
  (derived)      RosterExportGapDays    int, pull game date minus export date

The export carries no date. RosterExportDate is the newest TXNDT in the file,
the latest in-game transaction: a LOWER bound on the export's game date. The pull
log also prints the file's modification time.

Safety. Player IDs are per league. Every joined row is also checked by name
(case-folded); a row whose name differs is skipped. When at least 200 rows join
and fewer than half agree on name, the whole export is refused as another
league's file (the same test as the wrong-league guard in refresh.py).

Stdlib only.

    python tgs-viz/ingest/roster_export.py --league SSB [--csv <path>] [--data-dir <dir>] [--pull-date YYYY-MM-DD]
    (report only; merges into copies loaded from disk and writes nothing)
"""
import csv
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")

# (export column, record key, kind). Order is the order keys are added.
FIELDS = (
    ("ON40", "On40Man", "bool"),
    ("ACT", "ActiveRoster", "bool"),
    ("OPT", "OptionsUsed", "int"),
    ("OY", "OptionYearUsed", "int"),
    ("R5", "Rule5Eligible", "bool"),
    ("ROOK", "RookieStatus", "bool"),
    ("IC", "IntlComplex", "bool"),
    ("YL", "ContractStatus", "text"),
    ("FAT", "FAType", "text"),
    ("Sign", "SignDifficulty", "text"),
    ("DEM", "ContractDemand", "text"),
    ("TXN", "LastTransaction", "text"),
    ("TXNDT", "LastTransactionDate", "date"),
)
KEYS = tuple(k for _, k, _ in FIELDS) + ("RosterExportDate", "RosterExportGapDays")

# borrowed (🟡): the identity test of refresh.py's wrong-league guard.
MIN_JOIN = 200
MIN_SAME = 0.5
# borrowed (🟡): the 14-day re-export convention of ingest/r5.py, applied to game days.
STALE_GAP_DAYS = 14

_MONTHS = {m: i + 1 for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))}


class RosterExportError(Exception):
    """The export cannot be read or is not usable. The message is plain words."""


def parse_txn_date(text):
    """'Dec. 28th   2043' -> datetime.date(2043, 12, 28); None when it is not a date."""
    parts = str(text or "").replace(".", " ").split()
    if len(parts) != 3:
        return None
    mon = _MONTHS.get(parts[0][:3].lower())
    day = "".join(ch for ch in parts[1] if ch.isdigit())
    if not mon or not day or not parts[2].isdigit():
        return None
    try:
        return datetime.date(int(parts[2]), mon, int(day))
    except ValueError:
        return None


def _value(raw, kind):
    """One export cell -> a typed value, or None when the cell says nothing."""
    s = str(raw if raw is not None else "").strip()
    if kind == "bool":
        low = s.lower()
        if low == "yes":
            return True
        if low in ("no", "-"):
            return False
        return None
    if s in ("", "-"):
        return None
    if kind == "int":
        try:
            return int(float(s))
        except ValueError:
            return None
    if kind == "date":
        d = parse_txn_date(s)
        return d.isoformat() if d else None
    return s


def load_export(path):
    """Read an org export. Returns
    {"path", "rows": {id: {"name": str, "fields": {key: value}}}, "rows_read",
     "duplicates", "missing_columns", "as_of": ISO date or None, "file_date": ISO date}.
    Raises RosterExportError when the file cannot be read or has no ID/Name column.
    The FIRST column of a given name wins (OOTP repeats some headers, e.g. DEM)."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if not header:
                raise RosterExportError(f"{os.path.basename(path)} is empty")
            col = {}
            for i, h in enumerate(header):
                col.setdefault(h.strip(), i)
            if "ID" not in col or "Name" not in col:
                raise RosterExportError(
                    f"{os.path.basename(path)} has no ID and Name columns (is it the org export?)")
            present = [(c, k, kind, col[c]) for c, k, kind in FIELDS if c in col]
            missing = [c for c, _, _ in FIELDS if c not in col]
            rows, dup, n, newest = {}, 0, 0, None
            iid, inm = col["ID"], col["Name"]
            for rec in reader:
                n += 1
                if len(rec) <= max(iid, inm):
                    continue
                pid = rec[iid].strip()
                if not pid:
                    continue
                if pid in rows:
                    dup += 1
                    continue
                fields = {}
                for _c, key, kind, i in present:
                    v = _value(rec[i] if i < len(rec) else "", kind)
                    if v is not None:
                        fields[key] = v
                d = fields.get("LastTransactionDate")
                if d and (newest is None or d > newest):
                    newest = d
                rows[pid] = {"name": rec[inm].strip(), "fields": fields}
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise RosterExportError(f"could not read {os.path.basename(path)} ({type(e).__name__})") from None
    file_date = datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    return {"path": path, "rows": rows, "rows_read": n, "duplicates": dup,
            "missing_columns": missing, "as_of": newest, "file_date": file_date}


def _same_name(a, b):
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


def gap_days(pull_game_date, as_of):
    """Whole days from the export date to the pull's game date (positive = the
    export is older), or None when either date is unknown or unreadable."""
    try:
        return (datetime.date.fromisoformat(str(pull_game_date)[:10])
                - datetime.date.fromisoformat(str(as_of)[:10])).days
    except ValueError:
        return None


def merge(primary, export, mirrors=(), pull_game_date=None):
    """Merge a loaded export into player records by ID, in place.

    primary  - lists of record dicts that are counted (hitters, pitchers).
    mirrors  - lists of record dicts that get the same keys but are not counted
               (the My-Park copies of the same players).
    pull_game_date - the pull's in-game date, 'YYYY-MM-DD', or None.

    Raises RosterExportError when the export looks like another league's.
    Returns a report dict (counts per list, per key, dates, gap, stale flag)."""
    rows = export["rows"]
    joined = same = 0
    for recs in primary:
        for r in recs:
            e = rows.get(str(r.get("ID")).strip())
            if e is None:
                continue
            joined += 1
            same += _same_name(e["name"], r.get("Name"))
    if joined >= MIN_JOIN and same < MIN_SAME * joined:
        raise RosterExportError(
            f"it does not look like this league's file (only {same} of {joined} players "
            "match the pull by ID and name)")

    as_of = export["as_of"]
    gap = gap_days(pull_game_date, as_of) if as_of else None
    key_counts = {k: 0 for k in KEYS}
    kept = {}

    def attach(r, e, counts):
        for key, v in e["fields"].items():
            if key in r:
                kept[key] = kept.get(key, 0) + 1
            else:
                r[key] = v
                counts[key] += 1
        if as_of and "RosterExportDate" not in r:
            r["RosterExportDate"] = as_of
            counts["RosterExportDate"] += 1
        if gap is not None and "RosterExportGapDays" not in r:
            r["RosterExportGapDays"] = gap
            counts["RosterExportGapDays"] += 1

    per_list, name_mismatch, matched_ids = [], 0, set()
    for recs in primary:
        n = 0
        for r in recs:
            pid = str(r.get("ID")).strip()
            e = rows.get(pid)
            if e is None:
                continue
            if not _same_name(e["name"], r.get("Name")):
                name_mismatch += 1
                continue
            attach(r, e, key_counts)
            matched_ids.add(pid)
            n += 1
        per_list.append({"records": len(recs), "matched": n})
    for recs in mirrors:        # the same players again; their counts are not reported
        for r in recs:
            e = rows.get(str(r.get("ID")).strip())
            if e is not None and _same_name(e["name"], r.get("Name")):
                attach(r, e, {k: 0 for k in KEYS})
    mirror_n = sum(len(m) for m in mirrors)
    return {
        "path": export["path"], "rows_in_export": len(rows), "duplicates": export["duplicates"],
        "missing_columns": export["missing_columns"],
        "lists": per_list, "matched": len(matched_ids), "name_mismatch": name_mismatch,
        "export_only": len(set(rows) - matched_ids),
        "keys_added": {k: v for k, v in key_counts.items() if v}, "kept_existing": kept,
        "mirror_records": mirror_n,
        "as_of": as_of, "file_date": export["file_date"], "pull_game_date": pull_game_date,
        "gap_days": gap, "stale": gap is not None and gap > STALE_GAP_DAYS,
    }


def configured_path(league):
    """The league's roster export path from settings, or None when not set."""
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)
    import settings as ST
    return ST.roster_export_path(league)


def apply(league, primary, mirrors=(), pull_game_date=None, path=None, log=print):
    """The refresh.py hook. Merges the league's roster export into the records.

    Returns the merge report, or None when nothing was merged (not configured,
    file missing, or refused). Never raises for a bad export: the pull goes on
    without the roster fields and says why."""
    path = path or configured_path(league)
    if not path:
        return None                                   # off: no output, no change
    if not os.path.isfile(path):
        log(f"  WARNING: {league} roster export is set but not found at {path}; "
            "roster fields (options, Rule 5, 40-man ...) are absent this run.")
        return None
    try:
        rep = merge(primary, load_export(path), mirrors=mirrors, pull_game_date=pull_game_date)
    except RosterExportError as e:
        log(f"  WARNING: {league} roster export not used: {e}. The pull is unchanged.")
        return None
    h = rep["lists"]
    log(f"  roster export: {rep['matched']} of {sum(x['records'] for x in h)} players matched "
        f"({rep['rows_in_export']} rows in {os.path.basename(path)}); "
        f"{len(rep['keys_added'])} keys added")
    log(f"    export dated {rep['as_of'] or 'unknown'} (newest transaction in the file; "
        f"file written {rep['file_date']}); pull game date {rep['pull_game_date'] or 'unknown'}"
        + (f"; export is {rep['gap_days']} game days {'older' if rep['gap_days'] >= 0 else 'NEWER'}"
           if rep["gap_days"] is not None else ""))
    if rep["stale"]:
        log(f"  WARNING: the roster export is {rep['gap_days']} game days older than this pull "
            f"(over {STALE_GAP_DAYS}). Option years, service days and the 40-man may have moved: "
            "re-export the org screen from OOTP.")
    if rep["name_mismatch"]:
        log(f"  note: {rep['name_mismatch']} players share an ID with the export but not a name; skipped.")
    if rep["missing_columns"]:
        log(f"  note: the export has no column {', '.join(rep['missing_columns'])}; those keys are absent.")
    return rep


def main(argv=None):
    """Report what a merge would do against the saved pull. Writes nothing."""
    import json
    argv = list(sys.argv[1:] if argv is None else argv)

    def arg(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default

    league = arg("--league", "SSB")
    path = arg("--csv") or configured_path(league)
    if not path:
        print(f"{league}: no roster_export setting and no --csv")
        return 0
    data = arg("--data-dir") or os.path.join(REPO, "tgs-viz", "public", "data", league)
    lists = []
    for fn in ("hitters.json", "pitchers.json"):
        fp = os.path.join(data, fn)
        if os.path.exists(fp):
            doc = json.load(open(fp, encoding="utf-8"))
            lists.append(doc.get("rows", doc) if isinstance(doc, dict) else doc)
    rep = apply(league, lists, pull_game_date=arg("--pull-date"), path=path)
    if rep:
        print(json.dumps({k: v for k, v in rep.items() if k != "path"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
