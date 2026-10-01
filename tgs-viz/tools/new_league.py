"""
new_league.py - the New League wizard's backend: checks, settings entry, token
line, manifest entry, rollback and removal of a league added by the wizard.

Four league types:
  statsplus     an online league on StatsPlus, priced with TGS's or BLM's calibration
  local_export  an OOTP save's database CSV export (like Regular Game)
  dev           an all-AI OOTP league simmed in place (like DEV); Rating Trends only
  clone         calibration clone profile (no app league)

Subcommands (exit 0 ok, 2 invalid or failed; --json prints one JSON object):
  options --type T [--version V] [--json]     OOTP versions and the save names of one version
  check --spec F [--precheck-out P] [--json]  check the fields; P records what exists before the run
  token --spec F | --league ID                save the token from TGS_NL_TOKEN, or add an empty line
  profile --spec F                            write the league into settings.local.json as pending
  register --spec F                           add the manifest entry, then clear pending
  register-manifest --league ID               manifest entry of a trends-only league (DEV type)
  rollback --spec F --precheck P              undo what a failed New League run created
  remove --league ID                          take a wizard-added league out of the app
--manifest <path> (tests only) points register, register-manifest, remove,
rollback and check at a copy of public/data/leagues.json.

The spec file holds the wizard's non-secret fields: {"type", "id", "name", ...}
(or {"type", "fields": {...}}). It never holds a token. Nothing here prints a token.
Folders are moved into the control folder (rollback/, removed/), never deleted.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/tools
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
INGEST = os.path.join(VIZ, "ingest")
BACKTEST = os.path.join(VIZ, "backtest")
DATA = os.path.join(VIZ, "public", "data")
MANIFEST = os.path.join(DATA, "leagues.json")
for _p in (HERE, INGEST, BACKTEST, VIZ):
    if _p not in sys.path:
        sys.path.append(_p)
import settings as ST  # noqa: E402

TYPES = ("statsplus", "local_export", "dev", "clone")
BASES = ("TGS", "BLM")
RESERVED = {"TGS", "BLM", "DEV"}
TOKEN_ENV = "TGS_NL_TOKEN"
# Deletable clone names of TGS and BLM: the same lists as ootp/cleanup_clones.py
# ALLOW (test_new_league.py checks they agree). Any other profile: <prefix> + digits.
FIXED_CLONE_PATTERNS = [r"0tgs\d+", r"tgs-run\d+", r"0blm\d+", r"blm-run\d+", r"[1-5]", r"baseline02"]
PREFIX_RE = re.compile(r"^[0-9a-z_-]{2,12}$")
SLUG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")


# ---------------------------------------------------------------- small helpers
def _out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=True))


def control_dir():
    p = os.environ.get("TGS_CONTROL_DIR", "").strip()
    return os.path.abspath(p) if p else os.path.join(REPO, ".control")


def archive_paths():
    """(ratings_history.db, vintages folder); RATINGS_ARCHIVE_ROOT wins (tests)."""
    import pull_order as PO
    return PO.DB_PATH, PO.VINTAGES_DIR


def archive_has(league_id):
    """True / False: the ratings archive holds pulls of league_id. None when the
    database exists but cannot be read. Opens it read-only; never creates it."""
    db, _v = archive_paths()
    if not os.path.isfile(db):
        return False
    try:
        conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return conn.execute("SELECT 1 FROM pulls WHERE league=? LIMIT 1", (league_id,)).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def manifest_ids(path):
    import extract_data as X
    return {e["id"] for e in X.load_manifest_entries(path)}


def manifest_name(path, league_id):
    import extract_data as X
    for e in X.load_manifest_entries(path):
        if e.get("id") == league_id:
            return e.get("name")
    return None


def saves_of(version):
    """Sorted .lg folder names (without .lg) in the version's saved_games folder."""
    sg = ST.saved_games(version)
    if not sg or not os.path.isdir(sg):
        return []
    out = []
    for name in os.listdir(sg):
        if name.lower().endswith(".lg") and not name.startswith(".") and os.path.isdir(os.path.join(sg, name)):
            out.append(name[:-3])
    return sorted(out, key=str.lower)


def profile_masters():
    return {str(p.get("master")).strip().lower() for p in ST.ootp_profiles().values()
            if isinstance(p, dict) and p.get("master")}


def clone_patterns():
    pats = list(FIXED_CLONE_PATTERNS)
    for p in ST.ootp_profiles().values():
        if isinstance(p, dict) and p.get("prefix"):
            pats.append(re.escape(str(p["prefix"])) + r"\d+")
    return [re.compile(rf"^(?:{p})$", re.I) for p in pats]


def is_clone_name(name, patterns=None):
    return any(rx.match(name) for rx in (patterns or clone_patterns()))


def _int(v, default):
    if v is None or (isinstance(v, str) and not v.strip()):
        return default
    if isinstance(v, bool):
        raise ValueError
    return int(str(v).strip())


def _text(v):
    return v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())


def read_spec(path):
    """The wizard fields as one flat dict (accepts {"type", "fields": {...}} too)."""
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("the spec file must hold one JSON object")
    spec = dict(raw.get("fields") or {}) if isinstance(raw.get("fields"), dict) else {}
    for k, v in raw.items():
        if k != "fields":
            spec[k] = v
    spec.pop("token", None)                       # never kept, never printed
    return spec


def normalize(spec):
    """(fields, errors): the spec with defaults filled in and numbers parsed."""
    f, errors = {}, {}
    f["type"] = _text(spec.get("type"))
    f["id"] = _text(spec.get("id"))
    f["name"] = _text(spec.get("name"))
    f["my_org"] = _text(spec.get("my_org"))
    f["ootp_version"] = _text(spec.get("ootp_version"))
    f["ootp_save"] = spec.get("ootp_save") if isinstance(spec.get("ootp_save"), str) else _text(spec.get("ootp_save"))
    typ, lid = f["type"], f["id"]
    if typ == "statsplus":
        f["slug"] = _text(spec.get("slug")) or lid.lower()
        f["basis"] = _text(spec.get("basis"))
        f["history_first_date"] = _text(spec.get("history_first_date"))
        fids = spec.get("foreign_league_ids")
        if isinstance(fids, str):
            fids = [x for x in re.split(r"[,\s]+", fids) if x]
        f["foreign_league_ids"] = [str(x).strip() for x in (fids or []) if str(x).strip()]
    elif typ == "local_export":
        f["basis"] = _text(spec.get("basis")) or {"27": "BLM", "26": "TGS"}.get(f["ootp_version"], "")
    elif typ == "dev":
        f["dump_dir"] = _text(spec.get("dump_dir"))
        for k, d in (("years", 5), ("resume_after", 600), ("nostart_abort", 1800)):
            try:
                f[k] = _int(spec.get(k), d)
            except ValueError:
                errors[k] = "Type a whole number."
    elif typ == "clone":
        f["master"] = spec.get("master") if isinstance(spec.get("master"), str) else _text(spec.get("master"))
        f["prefix"] = _text(spec.get("prefix")) or ("0" + lid.lower())
        for k, d in (("start_year", 2016), ("target_year", 2026), ("runs", 10)):
            try:
                f[k] = _int(spec.get(k), d)
            except ValueError:
                errors[k] = "Type a whole number."
    return f, errors


# ---------------------------------------------------------------- check
def check(spec, manifest=MANIFEST):
    """{ok, errors: {field: msg}, warnings: [], plan: [{title, writes}]}."""
    f, errors = normalize(spec)
    warnings = []
    needs_credentials = False
    typ, lid = f["type"], f["id"]
    if typ not in TYPES:
        errors["type"] = f"Pick one of: {', '.join(TYPES)}."
        return {"ok": False, "errors": errors, "warnings": warnings, "plan": []}

    # id
    if not lid:
        errors["id"] = "Type a league id."
    elif not ST.ID_RE.match(lid):
        errors["id"] = "Use 2 to 8 capital letters or digits, for example XY or LG2."
    elif ST.DEVICE_RE.match(lid):
        errors["id"] = f"{lid} is a reserved Windows name. Pick another id."
    elif lid in RESERVED:
        errors["id"] = f"{lid} is one of your existing leagues. Pick another id."
    elif ST.league(lid) is not None:
        errors["id"] = f"{lid} is already in the settings. Pick another id."
    elif lid in manifest_ids(manifest):
        errors["id"] = f"{lid} is already in the app's league list. Pick another id."
    elif os.path.exists(os.path.join(DATA, lid)):
        errors["id"] = f"The app already has a data folder named {lid}. Pick another id."
    elif lid in ST.ootp_profiles():
        errors["id"] = f"ootp/leagues.json already has a profile named {lid}. Pick another id."
    else:
        _db, vint = archive_paths()
        used = archive_has(lid)
        if used is None:
            errors["id"] = "The ratings archive could not be read to check this id. Try again in a minute."
        elif used or os.path.exists(os.path.join(vint, lid)):
            errors["id"] = "This id was used before. Pick another id."

    # name and my_org
    if not 1 <= len(f["name"]) <= 40:
        errors["name"] = "Type a name of 1 to 40 characters."
    if len(f["my_org"]) > 80:
        errors["my_org"] = "Use at most 80 characters."

    ver, save = f["ootp_version"], f["ootp_save"]
    if ver and not ST.VERSION_RE.match(ver):
        errors["ootp_version"] = "Pick an OOTP version from the list."
        ver = ""
    saves = saves_of(ver) if ver else []

    def save_in_list(field, value, required):
        if not value:
            if required:
                errors[field] = "Pick a save from the list."
            return False
        if not ver:
            errors.setdefault("ootp_version", "Pick an OOTP version first.")
            return False
        if value not in saves:
            errors[field] = f"Pick a save from the list. There is no save named {value!r} in OOTP {ver}."
            return False
        return True

    if typ == "statsplus":
        slug = f["slug"]
        if not SLUG_RE.match(slug):
            errors["slug"] = "Use 1 to 40 lowercase letters, digits, - or _ (the part after statsplus.net/)."
        else:
            for other, lg in ST.leagues(include_disabled=True).items():
                if lg.get("type") == "statsplus" and ST.slug(other) == slug:
                    errors["slug"] = f"{other} already uses the StatsPlus name {slug}."
        if f["basis"] not in BASES:
            errors["basis"] = "Pick TGS or BLM."
        elif not os.path.isfile(os.path.join(VIZ, "engine", "calib", f["basis"], "constants-latest.json")):
            errors["basis"] = f"The {f['basis']} calibration is missing (engine/calib/{f['basis']}/constants-latest.json)."
        if save:
            save_in_list("ootp_save", save, False)
        elif ver:
            pass                                    # a version without a save: harmless
        if f["history_first_date"] and not ST._date_ok(f["history_first_date"]):
            errors["history_first_date"] = "Use a date like 2038-01-01."
        bad = [x for x in f["foreign_league_ids"] if not x.lstrip("-").isdigit()]
        if bad:
            errors["foreign_league_ids"] = "Use StatsPlus league numbers, separated by commas."
        if "slug" not in errors:
            try:
                import statsplus_token as T
                if not T.token_for(slug):
                    # the first pull then needs the token or the cookie pair (12.1); the browser requires one
                    needs_credentials = True
                    warnings.append(f"No token is saved on the line {slug.upper()}= yet. Give the token here, "
                                    "or both browser cookies for the first pull.")
            except Exception:
                pass
        if not save:
            warnings.append("No OOTP save given: the draft board, Rule 5 and IAFA boards need the save's exports.")
    elif typ == "local_export":
        if not ver:
            errors["ootp_version"] = "Pick an OOTP version."
        if save_in_list("ootp_save", save, True):
            if is_clone_name(save):
                errors["ootp_save"] = "That is a calibration clone save. Pick a save you play."
            elif not os.path.isfile(os.path.join(ST.saved_games(ver), f"{save}.lg", "import_export", "csv",
                                                 "players.csv")):
                errors["ootp_save"] = ("This save has no database export. In OOTP: File, Export, Database to CSV, "
                                       "then check again.")
        if f["basis"] not in BASES:
            errors["basis"] = "Pick TGS or BLM."
    elif typ == "dev":
        if not ver:
            errors["ootp_version"] = "Pick an OOTP version."
        if save_in_list("ootp_save", save, True):
            low = save.strip().lower()
            if low in ST.protected_saves():
                errors["ootp_save"] = "That is one of your real leagues. Pick an all-AI league to sim in place."
            elif low in profile_masters():
                errors["ootp_save"] = "That save is a clone master. Pick another save."
            elif any(lg.get("type") == "dev" and str(lg.get("ootp_save") or "").strip().lower() == low
                     for lg in ST.leagues(include_disabled=True).values()):
                errors["ootp_save"] = "Another dev league already sims this save. Pick another save."
            elif not os.path.isdir(os.path.join(ST.saved_games(ver), f"{save}.lg", "dump")):
                warnings.append("This save has no dump folder yet. Turn on Export CSV files after each simulated "
                                "season in this league.")
        if f.get("dump_dir") and not os.path.isdir(f["dump_dir"]):
            errors["dump_dir"] = "That folder does not exist."
        for k, lo, hi in (("years", 1, 50), ("resume_after", 60, 86400), ("nostart_abort", 60, 86400)):
            if k not in errors and not lo <= f[k] <= hi:
                errors[k] = f"Use a number from {lo} to {hi}."
    elif typ == "clone":
        if not ver:
            errors["ootp_version"] = "Pick an OOTP version."
        master = f["master"]
        if save_in_list("master", master, True):
            if master.strip().lower() in ST.protected_saves():
                errors["master"] = "That is one of your real leagues. Pick a pristine master save."
        prefix = f["prefix"]
        if not PREFIX_RE.match(prefix):
            errors["prefix"] = "Use 2 to 12 lowercase letters, digits, - or _."
        else:
            rx = re.compile(rf"^{re.escape(prefix)}\d+$", re.I)
            taken = sorted({n for n in saves if rx.match(n)}
                           | {n for n in ST.league_saves() if rx.match(n)}
                           | {n for n in profile_masters() if rx.match(n)})
            if taken:
                errors["prefix"] = (f"Saves already match {prefix}NN ({', '.join(taken[:5])}). Clean up would "
                                    "delete them. Pick another prefix.")
            elif any(isinstance(p, dict) and str(p.get("prefix") or "").lower() == prefix
                     for p in ST.ootp_profiles().values()):
                errors["prefix"] = "Another clone league uses this prefix. Pick another prefix."
        for k in ("start_year", "target_year", "runs"):
            if k not in errors and not (1 <= f[k] <= (50 if k == "runs" else 9999)):
                errors[k] = "Use a positive number."
        if "start_year" not in errors and "target_year" not in errors and f["target_year"] <= f["start_year"]:
            errors["target_year"] = "The target year must come after the start year."
    return {"ok": not errors, "errors": errors, "warnings": warnings, "plan": plan(f),
            "needs_credentials": needs_credentials}


def plan(f):
    """The steps the New League task runs for this type, with what each writes."""
    lid, typ = f.get("id") or "<ID>", f.get("type")
    d = f"tgs-viz/public/data/{lid}"
    first = [{"title": "Check the fields", "writes": "Nothing."},
             {"title": "Save the league settings", "writes": "settings.local.json (the league stays hidden until "
                                                             "it is added)."}]
    if typ == "statsplus":
        slug = (f.get("slug") or lid.lower()).upper()
        return first + [
            {"title": "Save the StatsPlus token", "writes": f"StatsPlus Tokens.txt, line {slug}=."},
            {"title": "Pull the ratings", "writes": f"{d}/hitters.json, pitchers.json and their My Park copies; "
                                                     "the ratings archive."},
            {"title": "Build the draft board", "writes": f"{d}/ draft files (needs the OOTP draft-pool export)."},
            {"title": "Add the league to the app", "writes": "tgs-viz/public/data/leagues.json; settings.local.json."},
            {"title": "Rating trends", "writes": f"{d}/rating_trends.json."},
            {"title": "Dev signals", "writes": f"{d}/dev_signals.json."},
            {"title": "ML rows", "writes": "The ML cache (tgs-viz/backtest/.dev_cache)."},
            {"title": "ML scores", "writes": f"{d}/dev_ml.json."}]
    if typ == "local_export":
        return first + [
            {"title": "Read the OOTP export", "writes": f"{d}/ player, draft and IAFA files; leagues.json; the ratings "
                                                         "archive."},
            {"title": "Add the league to the app", "writes": "settings.local.json."},
            {"title": "Dev signals", "writes": f"{d}/dev_signals.json."},
            {"title": "ML rows", "writes": "The ML cache (tgs-viz/backtest/.dev_cache)."},
            {"title": "ML scores", "writes": f"{d}/dev_ml.json."}]
    if typ == "dev":
        return first + [
            {"title": "Read the yearly dumps", "writes": f"The ratings archive; tgs-viz/backtest/vintages/{lid}."},
            {"title": "Rating trends", "writes": f"{d}/rating_trends.json (once a season is banked)."},
            {"title": "Add the league to the app", "writes": "tgs-viz/public/data/leagues.json (once trends exist); "
                                                             "settings.local.json."}]
    if typ == "clone":
        return first + [
            {"title": "Preview the clone plan", "writes": "Nothing."},
            {"title": "Finish", "writes": "settings.local.json."}]
    return first


def precheck(spec, manifest=MANIFEST):
    """What exists before the run, so rollback undoes only what the run made."""
    f, _e = normalize(spec)
    lid = f["id"]
    _db, vint = archive_paths()
    token_line = False
    if f["type"] == "statsplus" and SLUG_RE.match(f.get("slug") or ""):
        try:
            import statsplus_token as T
            token_line = f["slug"] in T._read()
        except Exception:
            token_line = False
    return {"id": lid,
            "data_dir_existed": bool(lid) and os.path.exists(os.path.join(DATA, lid)),
            "manifest_had_id": lid in manifest_ids(manifest),
            "settings_had_id": ST.league(lid) is not None,
            "token_line_existed": token_line,
            "vintages_dir_existed": bool(lid) and os.path.exists(os.path.join(vint, lid)),
            "archive_had_id": archive_has(lid) is not False}


# ---------------------------------------------------------------- settings entry
def settings_entry(f):
    """The leagues.<id> entry the profile step writes (pending until register)."""
    typ = f["type"]
    e = {"type": typ, "name": f["name"], "pending": True}
    if f.get("my_org"):
        e["my_org"] = f["my_org"]
    if typ == "statsplus":
        e.update(slug=f["slug"], basis=f["basis"])
        if f["ootp_version"] and f["ootp_save"]:
            e.update(ootp_version=f["ootp_version"], ootp_save=f["ootp_save"])
        if f["history_first_date"]:
            e["history"] = {"first_date": f["history_first_date"], "probe_years": 0}
        if f["foreign_league_ids"]:
            e["foreign_league_ids"] = f["foreign_league_ids"]
    elif typ == "local_export":
        e.update(ootp_version=f["ootp_version"], ootp_save=f["ootp_save"], basis=f["basis"])
    elif typ == "dev":
        prof = {"game": f["ootp_version"], "mode": "continuous", "folder": f["ootp_save"],
                "league": f["ootp_save"], "source": "dump", "years": f["years"],
                "resume_after": f["resume_after"], "nostart_abort": f["nostart_abort"],
                "note": "Added by New League: an all-AI league simmed in place; its yearly CSV dump is the data source."}
        if f.get("dump_dir"):
            prof["dump_dir"] = f["dump_dir"]
        e.update(ootp_version=f["ootp_version"], ootp_save=f["ootp_save"], ootp_profile=prof)
    elif typ == "clone":
        prof = {"game": f["ootp_version"], "master": f["master"], "prefix": f["prefix"],
                "start_year": f["start_year"], "target_year": f["target_year"], "runs": f["runs"],
                "note": "Added by New League: clone leagues of a pristine master save."}
        e.update(ootp_version=f["ootp_version"], ootp_save=f["master"], ootp_profile=prof)
    return e


# ---------------------------------------------------------------- moves
def _move(src, dst_dir, name):
    """Move src into dst_dir/name (a free name). Returns the destination."""
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, name)
    n = 2
    while os.path.exists(dst):
        dst = os.path.join(dst_dir, f"{name}-{n}")
        n += 1
    shutil.move(src, dst)
    return dst


def _rel(p):
    try:
        r = os.path.relpath(p, REPO)
        return p if r.startswith("..") else r
    except ValueError:
        return p


def _job_of(spec_path):
    """(control folder, job id) from <control>/jobs/<job_id>/new_league_spec.json;
    else the control folder of this run and a manual id."""
    folder = os.path.dirname(os.path.abspath(spec_path))
    parent = os.path.dirname(folder)
    if os.path.basename(parent).lower() == "jobs":
        return os.path.dirname(parent), os.path.basename(folder)
    return control_dir(), "manual-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _register_ok(state):
    """True when the job's state shows its register step ended ok."""
    steps = (state or {}).get("steps")
    return isinstance(steps, list) and any(
        isinstance(s, dict) and s.get("id") == "register" and s.get("status") == "ok" for s in steps)


JOB_STAMP_RE = re.compile(r"^\d{8}-\d{6}")


def changed_after(control, job_id, lid):
    """Why rollback of job_id must not touch lid, or None. A rollback undoes only
    what its own job made: never a league its job registered, and never once a
    later job added the same id again or removed it."""
    if _register_ok(_read_json(os.path.join(control, "jobs", job_id, "state.json"))):
        return "its add step finished"
    m = JOB_STAMP_RE.match(job_id)
    if not m:
        return None
    since = m.group(0)
    try:
        later = [n for n in os.listdir(os.path.join(control, "jobs")) if n[:15] >= since and n != job_id]
    except OSError:
        later = []
    for n in later:
        st = _read_json(os.path.join(control, "jobs", n, "state.json")) or {}
        task = st.get("task")
        if task == f"remove_league.{lid}" and st.get("status") in ("done", "partial"):
            return "it was removed later"
        if task == "new_league" and _register_ok(st):
            try:
                other = _text(read_spec(os.path.join(control, "jobs", n, "new_league_spec.json")).get("id"))
            except (OSError, ValueError):
                other = ""
            if other == lid:
                return "a later New League job added it again"
    try:
        removed = os.listdir(os.path.join(control, "removed"))
    except OSError:
        removed = []
    for n in removed:
        if n.startswith(lid + "-") and n[len(lid) + 1:len(lid) + 16] >= since:
            return "it was removed later"
    return None


# ---------------------------------------------------------------- commands
def cmd_options(a):
    if a.type not in TYPES:
        print(f"--type must be one of {', '.join(TYPES)}")
        return 2
    if a.version and not ST.VERSION_RE.match(a.version):
        print("--version must be two digits, like 27")
        return 2
    installs = (ST.load().get("ootp") or {}).get("installs") or {}
    versions = []
    for v in sorted(installs, key=int):
        sg = ST.saved_games(v)
        versions.append({"version": v, "saved_games": sg, "exists": bool(sg and os.path.isdir(sg))})
    ver = a.version
    if not ver:
        have = [x["version"] for x in versions if x["exists"]]
        ver = have[-1] if have else (versions[-1]["version"] if versions else "")
    saves = saves_of(ver) if ver else []
    pats = clone_patterns()
    protected = ST.protected_saves()
    in_use = {}
    for lid, lg in ST.leagues(include_disabled=True).items():
        if lg.get("ootp_save") and str(lg.get("ootp_version") or "") == ver:
            in_use[lg["ootp_save"]] = lid
    out = {"type": a.type, "version": ver, "versions": versions, "saves": saves,
           "clones": [s for s in saves if is_clone_name(s, pats)],
           "protected": [s for s in saves if s.strip().lower() in protected],
           "in_use": in_use, "bases": list(BASES)}
    if a.json:
        _out(out)
    else:
        print(f"OOTP {ver}: {len(saves)} saves")
        for s in saves:
            tags = [t for t, on in (("clone", s in out["clones"]), ("protected", s in out["protected"]),
                                    (f"league {in_use.get(s)}", s in in_use)) if on]
            print(f"  {s}" + (f"  ({', '.join(tags)})" if tags else ""))
    return 0


def _load_spec_or_fail(path, as_json=False):
    try:
        return read_spec(path)
    except (OSError, ValueError) as e:
        msg = f"The spec file could not be read ({type(e).__name__})."
        if as_json:
            _out({"ok": False, "errors": {"spec": msg}, "warnings": [], "plan": []})
        else:
            print(msg)
        return None


def cmd_check(a):
    spec = _load_spec_or_fail(a.spec, a.json)
    if spec is None:
        return 2
    try:
        res = check(spec, a.manifest)
    except ST.SettingsError as e:
        res = {"ok": False, "errors": {"settings": str(e)}, "warnings": [], "plan": []}
    if a.precheck_out:
        try:
            pre = precheck(spec, a.manifest)
            ST.atomic_write_text(a.precheck_out, json.dumps(pre, indent=2) + "\n")
        except (OSError, ST.SettingsError) as e:
            res["ok"] = False
            res["errors"]["precheck"] = f"The precheck file could not be written ({type(e).__name__})."
    if a.json:
        _out(res)
    else:
        if res["ok"]:
            print("  The fields are fine.")
        for k, v in res["errors"].items():
            print(f"  {k}: {v}")
        for w in res["warnings"]:
            print(f"  note: {w}")
    return 0 if res["ok"] else 2


def cmd_token(a):
    import statsplus_token as T
    if a.league:
        lg = ST.league(a.league)
        if not lg or lg.get("type") != "statsplus":
            print(f"  {a.league} is not an online league in the settings.")
            return 2
        slug = ST.slug(a.league)
    else:
        spec = _load_spec_or_fail(a.spec)
        if spec is None:
            return 2
        f, _e = normalize(spec)
        slug = f.get("slug") or f["id"].lower()
    if not SLUG_RE.match(slug or ""):
        print("  The league has no valid StatsPlus slug.")
        return 2
    line = slug.upper() + "="
    fname = os.path.basename(T.token_file())
    raw = os.environ.pop(TOKEN_ENV, "")
    if raw.strip():
        tok, problem = T.read_value(raw)
        raw = None
        if problem or not tok:
            print(f"  The token was not saved: {problem or 'the value is empty.'}")
            return 2
        T.save(slug, tok)
        tok = None
        print(f"  Saved the StatsPlus token on the line {line} in {fname}.")
        return 0
    if T.ensure_line(slug):
        print(f"  Added an empty {line} line to {fname}. Paste the token there before the next update.")
    elif T.token_for(slug):
        print(f"  A token is already saved on the line {line} in {fname}.")
    else:
        print(f"  The line {line} is already in {fname}. Paste the token there before the next update.")
    return 0


def cmd_profile(a):
    spec = _load_spec_or_fail(a.spec)
    if spec is None:
        return 2
    f, errors = normalize(spec)
    if errors or f["type"] not in TYPES or not ST.ID_RE.match(f["id"] or ""):
        print("  The spec is not valid. Run the check step first.")
        return 2
    existing = ST.league(f["id"])
    if existing is not None and not existing.get("pending"):
        print(f"  {f['id']} is already a league in the settings. Nothing written.")
        return 2
    entry = settings_entry(f)
    try:
        if existing is not None:
            ST.write_local({"leagues": {f["id"]: None}})      # a rerun replaces its own pending entry
        ST.write_local({"leagues": {f["id"]: entry}})
    except ST.SettingsError as e:
        print(f"  The settings were not written: {e}")
        return 2
    print(f"  Wrote {f['id']} ({f['type']}) into {_rel(ST.local_path())} as pending: "
          "no task card appears until it is added.")
    return 0


def register_manifest(league_id, manifest=MANIFEST):
    """Manifest entry of a trends-only league. True when written."""
    import extract_data as X
    if not os.path.isfile(os.path.join(DATA, league_id, "rating_trends.json")):
        return False
    name = manifest_name(manifest, league_id) or (ST.league(league_id) or {}).get("name") or league_id
    X.upsert_manifest(manifest, [X.build_manifest_entry(league_id, name=name)])
    return True


def cmd_register_manifest(a):
    lid = a.league.strip()
    try:
        done = register_manifest(lid, a.manifest)
    except ST.SettingsError as e:
        print(f"  {e}")
        return 2
    if done:
        print(f"  Registered {lid} in {_rel(a.manifest)}.")
    else:
        print(f"  {lid} has no rating_trends.json yet; nothing registered.")
    return 0


def cmd_register(a):
    import extract_data as X
    spec = _load_spec_or_fail(a.spec)
    if spec is None:
        return 2
    f, _e = normalize(spec)
    lid, typ = f["id"], f["type"]
    lg = ST.league(lid)
    if lg is None:
        print(f"  {lid} is not in the settings. Run the profile step first.")
        return 2
    folder = os.path.join(DATA, lid)
    # 1. the manifest entry, only when the league's data files exist
    if typ == "statsplus":
        if not all(os.path.isfile(os.path.join(folder, fn)) for fn in ("hitters.json", "pitchers.json")):
            print(f"  {lid} has no hitters.json and pitchers.json yet. The pull did not write them.")
            return 2
        entry = X.build_manifest_entry(lid, name=f["name"] or lid)
        entry.update({"basis": f["basis"], "source": "StatsPlus", "slug": f["slug"]})
        X.upsert_manifest(a.manifest, [entry])
        print(f"  Added {lid} ('{entry['name']}') to the app's league list.")
    elif typ == "local_export":
        if lid not in manifest_ids(a.manifest):
            print(f"  {lid} is not in the app's league list. The export step did not register it.")
            return 2
        print(f"  {lid} is in the app's league list (the export step added it).")
    elif typ == "dev":
        if register_manifest(lid, a.manifest):
            print(f"  Added {lid} to the app's league list (Rating Trends).")
        else:
            print(f"  {lid} has no banked season yet. It appears in the app after its first banked season.")
    else:
        print(f"  {lid} is a clone profile: it has no app league.")
    # 2. clear pending last: from here on the league is added and is never rolled back
    if lg.get("pending"):
        ST.write_local({"leagues": {lid: {"pending": None}}})
    print(f"  {lid} is added. Its tasks appear on the Control page.")
    return 0


def cmd_rollback(a):
    spec = _load_spec_or_fail(a.spec)
    if spec is None:
        return 2
    f, _e = normalize(spec)
    lid = f["id"]
    try:
        with open(a.precheck, encoding="utf-8") as fh:
            pre = json.load(fh)
    except (OSError, ValueError):
        print("  Nothing to undo: the check step did not record what existed before.")
        return 0
    if not ST.ID_RE.match(lid or "") or pre.get("id", lid) != lid:
        print("  The spec and the precheck file do not match. Nothing was changed.")
        return 2
    lg = ST.league(lid)
    if lg is not None and not pre.get("settings_had_id") and not lg.get("pending"):
        print(f"  {lid} finished its add step, so nothing is undone. To take it out, use "
              f"Remove {lg.get('name') or lid} from the app.")
        return 0
    control, job_id = _job_of(a.spec)
    why = changed_after(control, job_id, lid)
    if why:
        print(f"  Nothing is undone for {lid}: {why}. Its data stays as it is.")
        return 0
    dest = os.path.join(control, "rollback", job_id)
    did = []
    folder = os.path.join(DATA, lid)
    if not pre.get("data_dir_existed") and os.path.exists(folder):
        did.append(f"moved {_rel(folder)} to {_rel(_move(folder, dest, lid))}")
    _db, vint = archive_paths()
    vfolder = os.path.join(vint, lid)
    if not pre.get("vintages_dir_existed") and os.path.exists(vfolder):
        did.append(f"moved {_rel(vfolder)} to {_rel(_move(vfolder, dest, 'vintages-' + lid))}")
    db = archive_paths()[0]
    if not pre.get("archive_had_id") and os.path.isfile(db):
        import ratings_db as RDB
        conn = RDB.connect(db)
        try:
            n = RDB.forget_league(conn, lid)
        finally:
            conn.close()
        if n:
            did.append(f"removed {n} {lid} pull(s) from the ratings archive")
    if not pre.get("manifest_had_id"):
        import extract_data as X
        if X.remove_manifest_entry(a.manifest, lid):
            did.append(f"removed {lid} from {_rel(a.manifest)}")
    if not pre.get("settings_had_id") and lid in (ST.local_raw().get("leagues") or {}):
        ST.write_local({"leagues": {lid: None}})
        did.append(f"removed {lid} from {_rel(ST.local_path())}")
    if did:
        print(f"  Undid the unfinished league {lid}:")
        for d in did:
            print(f"    {d}")
        if f["type"] == "statsplus":
            print(f"  The {f['slug'].upper()}= line in the token file stays (your own input).")
    else:
        print(f"  Nothing to undo for {lid}.")
    return 0


def cmd_remove(a):
    import extract_data as X
    lid = a.league.strip()
    local = ST.local_raw().get("leagues") or {}
    defaults = ST.defaults_raw().get("leagues") or {}
    if lid in defaults or lid not in local:
        print(f"  {lid} was not added with New League, so it cannot be removed here.")
        return 2
    name = (ST.league(lid) or {}).get("name") or lid
    did = []
    folder = os.path.join(DATA, lid)
    if os.path.exists(folder):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = _move(folder, os.path.join(control_dir(), "removed"), f"{lid}-{stamp}")
        did.append(f"moved {_rel(folder)} to {_rel(dst)}")
    if X.remove_manifest_entry(a.manifest, lid):
        did.append(f"removed {lid} from {_rel(a.manifest)}")
    ST.write_local({"leagues": {lid: None}})
    did.append(f"removed {lid} from {_rel(ST.local_path())}")
    print(f"  Removed {name} ({lid}) from the app:")
    for d in did:
        print(f"    {d}")
    print("  The ratings archive, its vintages folder and the token line stay, so the id stays used.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="New League backend (the Control page's wizard).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--manifest", default=MANIFEST, help=argparse.SUPPRESS)
        return p

    p = add("options")
    p.add_argument("--type", required=True)
    p.add_argument("--version")
    p.add_argument("--json", action="store_true")
    p = add("check")
    p.add_argument("--spec", required=True)
    p.add_argument("--precheck-out")
    p.add_argument("--json", action="store_true")
    p = add("token")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec")
    g.add_argument("--league")
    p = add("profile")
    p.add_argument("--spec", required=True)
    p = add("register")
    p.add_argument("--spec", required=True)
    p = add("register-manifest")
    p.add_argument("--league", required=True)
    p = add("rollback")
    p.add_argument("--spec", required=True)
    p.add_argument("--precheck", required=True)
    p = add("remove")
    p.add_argument("--league", required=True)
    a = ap.parse_args(argv)
    a.manifest = os.path.abspath(a.manifest)
    cmds = {"options": cmd_options, "check": cmd_check, "token": cmd_token, "profile": cmd_profile,
            "register": cmd_register, "register-manifest": cmd_register_manifest,
            "rollback": cmd_rollback, "remove": cmd_remove}
    try:
        return cmds[a.cmd](a)
    except ST.SettingsError as e:
        if getattr(a, "json", False):
            _out({"ok": False, "errors": {"settings": str(e)}, "warnings": [], "plan": []})
        else:
            print(f"  Settings problem: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
