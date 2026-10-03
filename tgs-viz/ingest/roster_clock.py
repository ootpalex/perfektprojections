"""
Waiver clock, service-time detail and the league's in-game date, from StatsPlus /players.

statsplus.attach_contract_injury keeps from /players only the DL fields, the DFA and
OnWaivers flags, and MLB service. This module adds the rest of the waiver and service
block as NEW keys on the same records (no existing key changes), and writes the league's
in-game date into public/data/<LG>/metadata.json.

Stdlib only. Nothing here asks StatsPlus for anything: the rows come from the /players
reply the refresh pull already reads, and the date from the /date value the pull already
holds (statsplus.fetch_date, kept in memory for 60 s).

NEW RECORD KEYS (set only when the /players column exists AND the row's value is not
empty; StatsPlus leaves these blank for players outside a roster, so a blank is "not
known", never 0):
  WaiverDays        days_on_waivers         days the player has been on waivers (int)
  WaiverDaysLeft    days_on_waivers_left    days left to claim him; 0 = cleared (int)
  HasReceivedArb    has_received_arbitration   bool (see docs/phase3/waivers_service.md:
                                              False on every saved SSB row, so do not lean on it)
  YearsProtectedFromRule5   years_protected_from_rule_5   4 or 5 on rostered players, 0 on
                                              amateurs and retired players: StatsPlus's own value,
                                              no rule applied here
  IsOnSecondary     is_on_secondary   bool; StatsPlus's name. Inferred (not stated by StatsPlus) to
                                      be the 40-man flag: matches org.csv ON40 on 99.5% of 7,301
  IsActive          is_active         bool; inferred to be the active roster: matches org.csv ACT
                                      on 99.7% of 7,301
  ProSvcYrs / ProSvcDays / ProSvcDaysTY           pro_service_years / _days / _days_this_year
  SecSvcYrs / SecSvcDays / SecSvcDaysTY           secondary_service_years / _days / _days_this_year
Day counts are days of the league's own calendar; the length of a service year is NOT
assumed here (service_year_days measures it from the same rows).
"""
import json
import os
import re
import tempfile

# /players column -> record key, integers
INT_FIELDS = (
    ("days_on_waivers", "WaiverDays"),
    ("days_on_waivers_left", "WaiverDaysLeft"),
    ("pro_service_years", "ProSvcYrs"),
    ("pro_service_days", "ProSvcDays"),
    ("pro_service_days_this_year", "ProSvcDaysTY"),
    ("secondary_service_years", "SecSvcYrs"),
    ("secondary_service_days", "SecSvcDays"),
    ("secondary_service_days_this_year", "SecSvcDaysTY"),
    ("years_protected_from_rule_5", "YearsProtectedFromRule5"),
)
BOOL_FIELDS = (
    ("has_received_arbitration", "HasReceivedArb"),
    ("is_on_secondary", "IsOnSecondary"),
    ("is_active", "IsActive"),
)
NEW_KEYS = tuple(k for _, k in INT_FIELDS + BOOL_FIELDS)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def attach_waiver_service(recs, pmap, columns=None):
    """Add the NEW_KEYS to engine records by ID. pmap = statsplus.build_contract_injury_maps()[1];
    columns = statsplus.reply_columns(...) (None = every column is there). A column the reply
    lacks leaves its key unset. Returns the number of records that gained at least one key."""
    def has(col):
        return columns is None or col in columns

    n = 0
    for r in recs:
        for k in NEW_KEYS:
            r.pop(k, None)                          # a re-run leaves no stale key
        p = pmap.get(str(r.get("ID")))
        if not p:
            continue
        got = False
        for col, key in INT_FIELDS:
            if has(col):
                v = _to_int(p.get(col))
                if v is not None:
                    r[key] = v
                    got = True
        for col, key in BOOL_FIELDS:
            if has(col) and str(p.get(col, "")).strip() != "":
                r[key] = str(p.get(col)).strip() == "1"
                got = True
        n += got
    return n


# ---- in-game date -> metadata.json --------------------------------------------------------

def _indent_of(text):
    """The indent an existing JSON file was written with (2, 1) or None for compact."""
    m = re.search(r"\n( +)\"", text)
    return len(m.group(1)) if m else None


def write_game_date(out_dir, league, game_date):
    """Merge {"game_date": "YYYY-MM-DD"} into out_dir/metadata.json, creating the file when
    there is none. Every other key is kept as it was (and the file's indent), so the BLM / TGS
    metadata the sheets produce is untouched. Returns "written", "unchanged" or a short reason
    string starting with "skipped" (bad date, or an existing file that is not a JSON object:
    it is never overwritten). Safe to call after every pull."""
    gd = str(game_date or "").strip()[:10]
    if not _DATE.match(gd):
        return f"skipped: not a date ({gd!r})"
    path = os.path.join(out_dir, "metadata.json")
    meta, indent = {}, 2
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            meta = json.loads(text)
        except (OSError, ValueError):
            return "skipped: existing metadata.json is not readable JSON"
        if not isinstance(meta, dict):
            return "skipped: existing metadata.json is not a JSON object"
        indent = _indent_of(text)
        if meta.get("game_date") == gd:
            return "unchanged"
    else:
        meta = {"league": league}
    meta["game_date"] = gd
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".metadata.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=indent, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return f"skipped: could not write ({type(e).__name__})"
    return "written"


# ---- arithmetic on the service fields (ported from the dashboard's contract_projection.py) ----

def service_year_days(rows, group_key="Level", min_group=50):
    """Measure the length of a service year from /players rows instead of assuming it.

    A service year is the number L for which mlb_service_years == mlb_service_days // L.
    Rows are grouped (default by the league level column) because players on another clock
    (other leagues in the world) break the identity for every L. For each group with at
    least min_group rows (days > 0), the L values with ZERO violations are collected; the
    answer is the L that is exact for the most rows. Returns (L or None, detail), detail =
    {"rows_exact": {L: rows}, "groups": {group: [exact L, ...]}}. None when no group is exact."""
    groups = {}
    for r in rows:
        y, d = _to_int(r.get("mlb_service_years")), _to_int(r.get("mlb_service_days"))
        if y is None or d is None or d <= 0:
            continue
        groups.setdefault(str(r.get(group_key, "")), []).append((y, d))
    exact_by_group, rows_exact = {}, {}
    for g, pairs in groups.items():
        if len(pairs) < min_group:
            continue
        ok = [L for L in range(100, 261) if all(d // L == y for y, d in pairs)]
        exact_by_group[g] = ok
        for L in ok:
            rows_exact[L] = rows_exact.get(L, 0) + len(pairs)
    detail = {"rows_exact": rows_exact, "groups": exact_by_group}
    if not rows_exact:
        return None, detail
    best = max(rows_exact.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return best, detail


def rows_on_clock(rows, days_per_year, group_key="Level", min_group=50):
    """The rows whose group (default: league level) obeys mlb_service_years == days // days_per_year
    exactly. Players on another league's clock break that identity and would pollute
    detect_season_day / detect_limbo, so pass those the result of this function."""
    groups = {}
    for r in rows:
        groups.setdefault(str(r.get(group_key, "")), []).append(r)
    out = []
    for g_rows in groups.values():
        pairs = [(_to_int(r.get("mlb_service_years")), _to_int(r.get("mlb_service_days"))) for r in g_rows]
        pairs = [(y, d) for y, d in pairs if y is not None and d is not None and d > 0]
        if len(pairs) >= min_group and all(d // days_per_year == y for y, d in pairs):
            out.extend(g_rows)
    return out


def detect_season_day(rows, days_per_year):
    """League days into the current season: the most common mlb_service_days % days_per_year
    among players with service (pass rows_on_clock(...) so another league's clock does not
    count). 0 at season start and after the season ends. (The calendar date cannot give this:
    a league season is not its calendar span.)"""
    counts = {}
    for r in rows:
        d = _to_int(r.get("mlb_service_days"))
        if d is None or d <= 0:
            continue
        rem = d % days_per_year
        counts[rem] = counts.get(rem, 0) + 1
    if not counts:
        return 0
    return max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def detect_limbo(rows, season_day, days_per_year):
    """True when the season is complete (season_day == 0) but some player's whole service
    years from days (days // days_per_year) are ahead of his mlb_service_years column: the
    days already include the finished season and the years column has not caught up. Pass
    rows_on_clock(...) rows: a player on another league's clock always differs."""
    if season_day != 0:
        return False
    for r in rows:
        d, y = _to_int(r.get("mlb_service_days")), _to_int(r.get("mlb_service_years"))
        if d is not None and y is not None and d > 0 and d // days_per_year != y:
            return True
    return False
