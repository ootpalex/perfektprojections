"""
doctor_deep.py - the per-league checks of `doctor.py --deep`.

Ported from ootp-dashboard's model/src/validation.py (validate_league), written
against this project's data layout. For each enabled, non-pending league (clone
profiles are not app leagues and are skipped), up to five rows, ids deep.<LID>.*:

    settings   fields the league's type needs, ootp_version / ootp_save pairing,
               my_org, the engine_first_season boundary
    calib      engine/calib/<basis>/: constants-latest.json is needed to price the
               league; every optional live file that exists must parse
    metadata   calib/<basis>/metadata-latest.json and, when there, metadata_inputs/:
               the header row of each of the nine CSVs against ingest/metadata_inputs.py,
               and the manifest season against the league's engine_first_season
    data       public/data/<LID>/hitters.json and pitchers.json: required keys in
               every record; every dataset the manifest lists is on disk; the
               manifest basis equals the settings basis
    parks      calib/<LID>/park_factors.csv teams against the league's MLB clubs,
               park_blend.json's home team against my_team

Read-only, no network (StatsPlus reachability is left out on purpose: doctor.py
promises no network). Status: fail only where the app shows its error panel
(an app data file with records missing a required key, a listed dataset that is
not there); everything else is warn, and a warn names the task that needs it.
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/tools
VIZ = os.path.dirname(HERE)
for _p in (HERE, os.path.join(VIZ, "ingest")):
    if _p not in sys.path:
        sys.path.append(_p)

# Keys present in EVERY record of all eight committed hitters / pitchers files
# (BLM, SSB, RG, TGS), identity columns plus the headline valuation column.
HITTER_REQUIRED = ("ID", "Name", "POS", "Age", "ORG", "Org", "B", "T", "Best Pos", "BatR wtd", "Max WAA wtd")
PITCHER_REQUIRED = ("ID", "Name", "POS", "Age", "ORG", "Org", "B", "T", "WAA wtd")
# ingest/ratings.py live_*: each returns None (sheet behavior) when its file is missing
OPTIONAL_CALIB = ("scurves.json", "hitter_tails.json", "fielding_curves.json", "role_stuff.json",
                  "currency.json", "age_curve.json", "park_blend.json")
BASES = ("TGS", "BLM")


def _load_json(path):
    """(object, None) or (None, why)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f), None
    except OSError as e:
        return None, f"could not be read ({e.strerror or type(e).__name__})"
    except ValueError:
        return None, "is not valid JSON"


def _names(items, n=4):
    items = sorted(items)
    return ", ".join(items[:n]) + (f" (+{len(items) - n} more)" if len(items) > n else "")


# ---------------------------------------------------------------- settings
def settings_row(lid, lg, profiles):
    """(status, detail, fix) of the league's settings fields."""
    typ = lg.get("type")
    problems, notes = [], []
    ver, save = lg.get("ootp_version"), lg.get("ootp_save")
    if typ == "local_export":
        for k in ("ootp_version", "ootp_save", "basis"):
            if not lg.get(k):
                problems.append(f"{k} is not set (the export update needs it)")
    elif typ == "dev":
        for k in ("ootp_version", "ootp_save"):
            if not lg.get(k):
                problems.append(f"{k} is not set (Sim Dev League needs it)")
        if lid not in profiles:
            problems.append("no OOTP profile (ootp/leagues.json or ootp_profile in settings)")
    elif typ == "statsplus":
        if bool(ver) != bool(save):
            problems.append(f"{'ootp_save' if save else 'ootp_version'} is set without "
                            f"{'ootp_version' if save else 'ootp_save'}, so the draft, Rule 5 and IAFA exports ignore it")
    if typ == "statsplus" and not str(lg.get("my_org") or "").strip():
        problems.append("my_org is empty (the My Org views have no club)")
    efs = lg.get("engine_first_season")
    if efs is not None:
        notes.append(f"engine boundary: season {efs} on OOTP {ver or '?'}")
    detail = f"type {typ}" + ("; " + "; ".join(notes) if notes else "")
    if problems:
        return ("warn", "; ".join(problems),
                "Fix the league on the Setup page, or in the \"leagues\" entry of settings.local.json.")
    return "ok", detail, ""


# ---------------------------------------------------------------- calibration
def calib_row(basis, calib_dir):
    """(status, detail, fix) of engine/calib/<basis>/ (what the engine reads)."""
    folder = os.path.join(calib_dir, basis)
    fix = f"Restore engine/calib/{basis}/ from the project files (git checkout)."
    path = os.path.join(folder, "constants-latest.json")
    if not os.path.isfile(path):
        return ("warn", f"engine/calib/{basis}/constants-latest.json is missing (the league cannot be priced)", fix)
    bad, absent, have = [], [], []
    for fn in ("constants-latest.json",) + OPTIONAL_CALIB:
        p = os.path.join(folder, fn)
        if not os.path.isfile(p):
            absent.append(fn)
            continue
        obj, why = _load_json(p)
        if why or not isinstance(obj, dict):
            bad.append(f"{fn} {why or 'does not hold one JSON object'}")
        else:
            have.append(fn)
    if bad:
        return "warn", f"engine/calib/{basis}/: " + "; ".join(bad) + " (an update task stops on it)", fix
    n_opt = len(OPTIONAL_CALIB) - len([a for a in absent if a in OPTIONAL_CALIB])
    tail = f"; absent, the engine falls back: {', '.join(absent)}" if absent else ""
    return "ok", f"engine/calib/{basis}/: constants-latest.json and {n_opt} of {len(OPTIONAL_CALIB)} optional files{tail}", ""


# ---------------------------------------------------------------- metadata inputs
def _layouts(MI):
    """{file: [(header, [cell offsets])]}: where each CSV's header row sits."""
    def sbs(h):      # two tables side by side with the '<--', '', '-->' spacer
        return [(h, [0, len(h) + 3])]
    fld = MI.FLD_HDR
    return {
        "Hitting_Data.csv": [(MI.HIT_HDR, [0])],
        "Pitching_Data.csv": [(MI.PIT_HDR, [0])],
        "Fielding_Data.csv": [(fld, [i * (len(fld) + 1) for i in range(8)])],
        "Batter_Ratings.csv": sbs(MI.BAT_RAT_HDR),
        "Fielding_Ratings.csv": [(MI.FLD_RAT_HDR, [0])],
        "SP_Ratings.csv": sbs(MI.PIT_RAT_HDR),
        "RP_Ratings.csv": sbs(MI.PIT_RAT_HDR),
        "SP_Data.csv": [(MI.PIT_HDR, [0])],        # the paste tabs may carry extra columns after it
        "RP_Data.csv": [(MI.PIT_HDR, [0])],
    }


def _csv_header_problem(path, layout):
    """Why the CSV's header row (the second row) is not the expected one, or None."""
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            next(r, None)                                   # banner row: "Player List"
            hdr = next(r, None)
            has_rows = next(r, None) is not None
    except OSError as e:
        return f"could not be read ({e.strerror or type(e).__name__})"
    if not hdr:
        return "has no header row"
    for want, offsets in layout:
        for off in offsets:
            got = [c.strip() for c in hdr[off:off + len(want)]]
            if got != want:
                missing = [c for c in want if c not in hdr]
                return ("header does not match ingest/metadata_inputs.py"
                        + (f"; missing {_names(missing)}" if missing else "; columns are out of order or shifted"))
    if not has_rows:
        return "has a header but no data rows"
    return None


def metadata_row(lid, basis, calib_dir, efs):
    """(status, detail, fix) of calib/<basis>/metadata-latest.json and metadata_inputs/.
    efs = the league's engine_first_season, compared only when the league owns the
    calibration (lid == basis): a derived league prices on the basis league's metadata."""
    folder = os.path.join(calib_dir, basis)
    problems, parts = [], []
    p = os.path.join(folder, "metadata-latest.json")
    if os.path.isfile(p):
        obj, why = _load_json(p)
        if why or not isinstance(obj, dict):
            problems.append(f"metadata-latest.json {why or 'does not hold one JSON object'}")
        elif not obj.get("cells"):
            problems.append("metadata-latest.json has no cells")
        else:
            parts.append(f"metadata-latest.json ({len(obj['cells'])} cells)")
    else:
        parts.append("no metadata-latest.json (the sheet constants are used)")
    mdir = os.path.join(folder, "metadata_inputs")
    if os.path.isdir(mdir):
        import metadata_inputs as MI
        lay = _layouts(MI)
        for fn, layout in lay.items():
            fp = os.path.join(mdir, fn)
            if not os.path.isfile(fp):
                problems.append(f"metadata_inputs/{fn} is missing")
                continue
            why = _csv_header_problem(fp, layout)
            if why:
                problems.append(f"metadata_inputs/{fn} {why}")
        man, why = _load_json(os.path.join(mdir, "manifest.json"))
        if why or not isinstance(man, dict):
            problems.append(f"metadata_inputs/manifest.json {why or 'does not hold one JSON object'}")
        else:
            season = man.get("season")
            parts.append(f"metadata_inputs: {len(lay)} CSVs, season {season}")
            if lid == basis and efs is not None and isinstance(season, int) and season < efs:
                problems.append(f"metadata_inputs/manifest.json is season {season}, before this league's "
                                f"engine_first_season {efs}")
            if man.get("league") not in (None, basis):
                problems.append(f"metadata_inputs/manifest.json is for league {man.get('league')}, not {basis}")
    else:
        parts.append("no metadata_inputs folder")
    if problems:
        return ("warn", "; ".join(problems) + " (Recalibrate and Sync Metadata read these)",
                f"Run Recalibrate {basis} on the Control page, or restore engine/calib/{basis}/ from git.")
    return "ok", ("" if lid == basis else f"uses {basis}'s: ") + "; ".join(parts), ""


# ---------------------------------------------------------------- app data and parks
def _records(path):
    """(list of dict records, None) or (None, why)."""
    obj, why = _load_json(path)
    if why:
        return None, why
    if not isinstance(obj, list) or not all(isinstance(r, dict) for r in obj):
        return None, "is not a list of player records"
    return obj, None


def _missing_keys(recs, required):
    """{key: records lacking it} for the keys at least one record lacks."""
    out = {}
    for k in required:
        n = sum(1 for r in recs if k not in r)
        if n:
            out[k] = n
    return out


def data_row(lid, lg, entry, data_dir):
    """((status, detail, fix), hitters records or None) for the committed app data."""
    folder = os.path.join(data_dir, lid)
    bad, parts = [], []
    hitters = None
    for fn, required in (("hitters.json", HITTER_REQUIRED), ("pitchers.json", PITCHER_REQUIRED)):
        p = os.path.join(folder, fn)
        if not os.path.isfile(p):
            continue                       # the plain check already reports a missing file
        recs, why = _records(p)
        if why:
            bad.append(f"{fn} {why}")
            continue
        if fn == "hitters.json":
            hitters = recs
        miss = _missing_keys(recs, required)
        if miss:
            bad.append(f"{fn}: " + ", ".join(f"{k} missing in {n} of {len(recs)} records" for k, n in miss.items()))
        else:
            parts.append(f"{fn} {len(recs)} records have all {len(required)} required keys")
    warns = []
    for ds in (entry or {}).get("datasets") or []:
        if not os.path.isfile(os.path.join(folder, f"{ds}.json")):
            bad.append(f"{ds}.json is listed in leagues.json but is not there")
    mb, sb = (entry or {}).get("basis"), lg.get("basis")
    if entry and sb and sb != lid and mb != sb:
        warns.append(f"leagues.json basis is {mb or 'unset'} but the settings basis is {sb}")
    fix = f"Run Update {lg.get('name') or lid} on the Control page."
    if bad:
        return ("fail", "; ".join(bad + warns) + " (picking it shows the error panel)", fix), hitters
    if warns:
        return ("warn", "; ".join(warns), fix), hitters
    return ("ok", "; ".join(parts) or "no player files to check", ""), hitters


def parks_row(lid, lg, calib_dir, hitters):
    """(status, detail, fix) for calib/<LID>/park_factors.csv, or None when the league has none
    and is not expected to (it prices in a neutral park)."""
    folder = os.path.join(calib_dir, lid)
    pf = os.path.join(folder, "park_factors.csv")
    if not os.path.isfile(pf):
        return "ok", "no park file of its own (priced in a neutral park)", ""
    try:
        with open(pf, encoding="utf-8-sig", newline="") as f:
            park_teams = {(r.get("Team") or "").strip() for r in csv.DictReader(f)} - {""}
    except OSError as e:
        return "warn", f"park_factors.csv could not be read ({e.strerror or type(e).__name__})", ""
    if not park_teams:
        return "warn", "park_factors.csv has no team rows", f"Re-export the StatsPlus Ballparks list into engine/calib/{lid}/park_factors.csv."
    try:
        import parks as PK
        excluded = set((PK.LEAGUES.get(lid) or {}).get("exclude") or ())
    except ImportError:
        excluded = set()
    problems = []
    park_mlb = park_teams - excluded
    if hitters is None:
        problems.append("hitters.json is not there, so the clubs were not compared")
    else:
        # MLB clubs of the league: ORG of the records at level 1; digit-only ORG values are org ids, not clubs
        clubs = {str(r.get("ORG") or "").strip() for r in hitters if str(r.get("LgLvl")) == "1"}
        clubs = {c for c in clubs if c and not c.isdigit()}
        miss, extra = clubs - park_mlb, park_mlb - clubs
        if miss:
            problems.append(f"clubs without a park row: {_names(miss)}")
        if extra:
            problems.append(f"park rows without a club in hitters.json: {_names(extra)}")
    team = str(lg.get("my_team") or "").strip()
    if team and team not in park_teams:
        problems.append(f"my_team {team!r} is not in park_factors.csv")
    blend, why = _load_json(os.path.join(folder, "park_blend.json"))
    if why is None and isinstance(blend, dict) and team and blend.get("home_team") != team:
        problems.append(f"park_blend.json was built for {blend.get('home_team')!r}, my_team is {team!r}")
    if problems:
        return ("warn", "; ".join(problems) + " (My Park values use these)",
                f"Re-copy the StatsPlus Ballparks export to engine/calib/{lid}/park_factors.csv, then run: "
                f"python tgs-viz/ingest/parks.py --write")
    return "ok", f"{len(park_mlb)} park rows match the league's MLB clubs" + (f"; {len(excluded & park_teams)} excluded" if excluded & park_teams else ""), ""


# ---------------------------------------------------------------- driver
def check_deep(d, leagues, manifest, data_dir, calib_dir):
    """Add the deep rows for every league in `leagues` ({id: settings dict}) to Doctor d."""
    import settings as ST
    by_id = {e.get("id"): e for e in manifest}
    profiles = ST.ootp_profiles()
    cache = {}                                       # per basis: the calib and metadata results are shared
    for lid, lg in leagues.items():
        if lg.get("type") == "clone":
            continue
        name = lg.get("name") or lid

        def add(what, title, res, task=None):
            status, detail, fix = res
            d.add(f"deep.{lid}.{what}", f"{name}: {title}", status, detail, fix, task)

        add("settings", "settings fields", settings_row(lid, lg, profiles))
        basis = lg.get("basis") or (lid if lid in BASES else None)
        if basis:
            key = ("calib", basis)
            if key not in cache:
                cache[key] = calib_row(basis, calib_dir)
            add("calib", "calibration files", cache[key])
            add("metadata", "metadata inputs",
                metadata_row(lid, basis, calib_dir, lg.get("engine_first_season")))
        if lg.get("type") == "dev":
            continue                                 # trends only: no player files, no parks
        res, hitters = data_row(lid, lg, by_id.get(lid), data_dir)
        add("data", "app data keys", res, f"update.{lid}")
        pres = parks_row(lid, lg, calib_dir, hitters)
        if pres:
            add("parks", "park files", pres)
        hitters = None                               # free the 35 MB list before the next league
