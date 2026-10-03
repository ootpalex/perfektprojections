"""
settings.py - the project settings: committed defaults plus an optional local file.

Files:
  tgs-viz/tools/settings.defaults.json   committed. Its values equal what the code
                                         did before settings existed.
  <repo>/settings.local.json             optional, never committed. Holds only what
                                         differs on this computer. TGS_SETTINGS_LOCAL
                                         points at another file (tests only).

Merge: dicts merge deeply and the local file wins. Lists are replaced, not merged.
"leagues" merges per league id. A league id that only the local file has is a new
league (the New League wizard writes those). A local entry {"enabled": false}
hides a default league's tasks; its data stays on disk.

A file that is not valid JSON, or a value that fails the checks, raises
SettingsError with a plain message that names the file and the key. Pipeline
scripts stop on it; they never fall back silently.

Interpreters are argv lists and are never expanded. Paths expand %VAR% and a
leading ~, nothing else.

Stdlib only. Runs on Python 3.11 or newer (both the main and the ML interpreter).

CLI:
  python tgs-viz/tools/settings.py --json                     merged settings
  python tgs-viz/tools/settings.py --app-json                 the browser-safe subset
  python tgs-viz/tools/settings.py get <dotted.key>           one value as JSON
  python tgs-viz/tools/settings.py set --patch-file <path>    merge a patch into the local file
  python tgs-viz/tools/settings.py validate                   exit 0 when both files are fine, else 2
"""
import copy
import datetime
import json
import os
import re
import sys
import time

# abspath, like every pipeline script (no junction resolution), so paths compare equal
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULTS_PATH = os.path.join(REPO, "tgs-viz", "tools", "settings.defaults.json")
LOCAL_NAME = "settings.local.json"
PROFILES_PATH = os.path.join(REPO, "ootp", "leagues.json")

TYPES = ("statsplus", "local_export", "dev", "clone")
BASES = ("TGS", "BLM")
ID_RE = re.compile(r"^[A-Z0-9]{2,8}$")
DEVICE_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$")
SLUG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
VERSION_RE = re.compile(r"^\d{2}$")
SAVE_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def local_path():
    """The local settings file (TGS_SETTINGS_LOCAL wins, tests only)."""
    p = os.environ.get("TGS_SETTINGS_LOCAL", "").strip()
    return os.path.abspath(p) if p else os.path.join(REPO, LOCAL_NAME)


LOCAL_PATH = local_path()


class SettingsError(Exception):
    """A settings file is missing, not valid JSON, or holds a bad value."""

    def __init__(self, message, problems=None, path=None):
        super().__init__(message)
        self.problems = list(problems or [message])
        self.path = path


# ---------------------------------------------------------------- reading
def _label(path):
    """A short name for a settings file in messages."""
    try:
        rel = os.path.relpath(path, REPO)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel


def _stat_key(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_json(path, required):
    """The JSON object in path, or None when the file is missing and not required."""
    label = _label(path)
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        if required:
            raise SettingsError(f"{label} is missing. Restore it from the project files.", path=path)
        return None
    except OSError as e:
        raise SettingsError(f"{label} could not be read ({e.strerror or type(e).__name__}).", path=path)
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise SettingsError(f"{label} is not UTF-8 text. Save it as UTF-8.", path=path)
    except json.JSONDecodeError as e:
        raise SettingsError(f"{label} is not valid JSON: line {e.lineno}, column {e.colno}: {e.msg}.", path=path)
    if not isinstance(obj, dict):
        raise SettingsError(f"{label} must hold one JSON object ({{...}}).", path=path)
    return obj


def _merge(base, over):
    """Deep merge: dicts merge, over wins, lists and other values are replaced."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _patch(base, patch):
    """Like _merge, but a None value in patch deletes that key."""
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _patch(out[k], v)
        elif isinstance(v, dict):
            out[k] = _patch({}, v)
        else:
            out[k] = copy.deepcopy(v)
    return out


_CACHE = {"key": None, "merged": None}


_WIN_PYTHON = {"main": ["python"], "ml": ["py", "-3.14"]}
_WIN_FOLDER = re.compile(r"^([A-Za-z]:[\\/]|%USERPROFILE%)")
OOTP_MAC_ROOT = "~/Library/Application Support/Out of the Park Developments"


def _platform_defaults(defaults):
    """Off Windows, swap each committed Windows value for this platform's: the python and
    py launchers become python3, a C:/ or %USERPROFILE% saved_games folder becomes the
    macOS one (OOTP ships for Windows and macOS only; other systems get the macOS layout).
    Only values still equal to the Windows text are swapped; the local file is never touched.
    paths.js applies the same swap to python.main."""
    if os.name == "nt" or not isinstance(defaults, dict):
        return defaults
    py = defaults.get("python")
    if isinstance(py, dict):
        for k, win in _WIN_PYTHON.items():
            if py.get(k) == win:
                py[k] = ["python3"]
    inst = (defaults.get("ootp") or {}).get("installs") if isinstance(defaults.get("ootp"), dict) else None
    for ver, v in (inst or {}).items():
        if isinstance(v, dict) and isinstance(v.get("saved_games"), str) and _WIN_FOLDER.match(v["saved_games"]):
            v["saved_games"] = f"{OOTP_MAC_ROOT}/OOTP Baseball {ver}/saved_games"
    return defaults


def _load_files():
    """(defaults, local or None, merged). Raises SettingsError."""
    dpath, lpath = DEFAULTS_PATH, local_path()
    defaults = _platform_defaults(_read_json(dpath, required=True))
    problems = validate(defaults) + _pending_in(defaults)
    if problems:
        raise SettingsError(f"{_label(dpath)}: " + "; ".join(problems), problems, dpath)
    local = _read_json(lpath, required=False)
    merged = _merge(defaults, local) if local is not None else copy.deepcopy(defaults)
    if local is not None:
        problems = validate(merged)
        if problems:
            raise SettingsError(f"{_label(lpath)}: " + "; ".join(problems), problems, lpath)
    return defaults, local, merged


def _merged(refresh=False):
    """The cached merged settings (do not change the returned dict)."""
    dpath, lpath = DEFAULTS_PATH, local_path()
    key = (dpath, _stat_key(dpath), lpath, _stat_key(lpath))
    if refresh or _CACHE["key"] != key:
        _CACHE.update(key=None, merged=None)
        merged = _load_files()[2]
        _CACHE.update(key=key, merged=merged)
    return _CACHE["merged"]


def load(refresh=False):
    """The merged settings. Cached by both files' (mtime_ns, size)."""
    return copy.deepcopy(_merged(refresh))


def defaults_raw():
    """The defaults file alone (validated)."""
    return copy.deepcopy(_load_files()[0])


def local_raw():
    """The local file alone, or {} when there is none."""
    return copy.deepcopy(_read_json(local_path(), required=False) or {})


# ---------------------------------------------------------------- checks
def _pending_in(defaults):
    lgs = defaults.get("leagues") if isinstance(defaults.get("leagues"), dict) else {}
    return [f"leagues.{lid}.pending: only settings.local.json may hold pending"
            for lid, lg in lgs.items() if isinstance(lg, dict) and "pending" in lg]


def _argv_ok(v):
    return isinstance(v, list) and len(v) > 0 and all(isinstance(x, str) and x.strip() for x in v)


def _date_ok(s):
    if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return False
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def save_name_problem(name):
    """Why name cannot be an OOTP save name, or None."""
    if not isinstance(name, str) or not name.strip():
        return "must be a save name"
    if SAVE_BAD.search(name) or name.strip() in (".", "..") or name != name.strip():
        return "must be a plain save name (no path, no \\ / : * ? \" < > |)"
    return None


def validate(merged):
    """Problems in a settings dict, in plain words. [] when it is fine."""
    out = []
    if not isinstance(merged, dict):
        return ["the settings must be one JSON object"]
    if merged.get("schema") != 1:
        out.append("schema: must be 1")
    py = merged.get("python")
    if not isinstance(py, dict):
        out.append("python: must be an object with main and ml")
    else:
        for k in ("main", "ml"):
            if not _argv_ok(py.get(k)):
                out.append(f'python.{k}: must be a list of words, for example ["python"]')
    if not _argv_ok(merged.get("node")):
        out.append('node: must be a list of words, for example ["node"]')
    sp = merged.get("statsplus")
    if not isinstance(sp, dict) or not isinstance(sp.get("token_file"), str) or not sp["token_file"].strip():
        out.append("statsplus.token_file: must be a file name")
    oo = merged.get("ootp")
    if not isinstance(oo, dict):
        out.append("ootp: must be an object with installs")
    else:
        inst = oo.get("installs")
        if not isinstance(inst, dict):
            out.append("ootp.installs: must be an object")
        else:
            for ver, v in inst.items():
                if not VERSION_RE.match(str(ver)):
                    out.append(f"ootp.installs.{ver}: the version must be two digits, like 27")
                if not isinstance(v, dict) or not isinstance(v.get("saved_games"), str) or not v["saved_games"].strip():
                    out.append(f"ootp.installs.{ver}.saved_games: must be a folder path")
        pe = oo.get("protected_extra", [])
        if not isinstance(pe, list) or not all(isinstance(x, str) for x in pe):
            out.append("ootp.protected_extra: must be a list of save names")
    app = merged.get("app")
    if app is not None:
        port = app.get("port") if isinstance(app, dict) else None
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            out.append("app.port: must be a port number")
    lgs = merged.get("leagues")
    if not isinstance(lgs, dict):
        out.append("leagues: must be an object")
        return out
    slugs = {}
    for lid, lg in lgs.items():
        p = f"leagues.{lid}"
        if not ID_RE.match(str(lid)):
            out.append(f"{p}: a league id is 2 to 8 capital letters or digits")
        elif DEVICE_RE.match(lid):
            out.append(f"{p}: {lid} is a reserved Windows name; pick another id")
        if not isinstance(lg, dict):
            out.append(f"{p}: must be an object")
            continue
        typ = lg.get("type")
        if typ not in TYPES:
            out.append(f"{p}.type: must be one of {', '.join(TYPES)}")
        name = lg.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            out.append(f"{p}.name: must be 1 to 40 characters")
        for k in ("enabled", "pending"):
            if k in lg and not isinstance(lg[k], bool):
                out.append(f"{p}.{k}: must be true or false")
        if "slug" in lg and not (isinstance(lg["slug"], str) and SLUG_RE.match(lg["slug"])):
            out.append(f"{p}.slug: use 1 to 40 lowercase letters, digits, - or _")
        if typ in ("statsplus", "local_export") or "basis" in lg:
            if lg.get("basis") not in BASES:
                out.append(f"{p}.basis: must be TGS or BLM")
            elif lid in BASES and lg.get("basis") != lid:
                out.append(f"{p}.basis: must be {lid}")
        if "ootp_version" in lg and not (isinstance(lg["ootp_version"], str) and VERSION_RE.match(lg["ootp_version"])):
            out.append(f'{p}.ootp_version: must be two digits in quotes, like "27"')
        if "ootp_save" in lg:
            why = save_name_problem(lg["ootp_save"])
            if why:
                out.append(f"{p}.ootp_save: {why}")
        for k in ("my_team", "my_org"):
            if k in lg and not isinstance(lg[k], str):
                out.append(f"{p}.{k}: must be text")
        if "history" in lg:
            h = lg["history"]
            if not isinstance(h, dict):
                out.append(f"{p}.history: must be an object")
            else:
                if "first_date" in h and not _date_ok(h["first_date"]):
                    out.append(f"{p}.history.first_date: must be a date like 2038-01-01")
                py_ = h.get("probe_years", 0)
                if not isinstance(py_, int) or isinstance(py_, bool) or py_ < 0:
                    out.append(f"{p}.history.probe_years: must be a whole number, 0 or more")
        for k in ("dispersal_orgs", "foreign_league_ids"):
            if k in lg and not (isinstance(lg[k], list) and all(isinstance(x, str) for x in lg[k])):
                out.append(f"{p}.{k}: must be a list of text values")
        if "ootp_profile" in lg and not isinstance(lg["ootp_profile"], dict):
            out.append(f"{p}.ootp_profile: must be an object")
        if typ == "statsplus":
            s = lg.get("slug") if isinstance(lg.get("slug"), str) else str(lid).lower()
            if s in slugs:
                out.append(f"{p}.slug: {s} is already the slug of {slugs[s]}")
            slugs.setdefault(s, lid)
    return out


# ---------------------------------------------------------------- answers
def interp(key):
    """argv list of an interpreter: "main", "ml" or "node". Never expanded."""
    m = _merged()
    v = m["node"] if key == "node" else m["python"][key]
    return list(v)


def _active(lg):
    return lg.get("enabled", True) is not False and lg.get("pending") is not True


def leagues(include_disabled=False):
    """{id: league dict with "id"}, defaults order first. Enabled and non-pending
    leagues only, unless include_disabled (then every configured league)."""
    out = {}
    for lid, lg in _merged()["leagues"].items():
        if include_disabled or _active(lg):
            d = copy.deepcopy(lg)
            d["id"] = lid
            out[lid] = d
    return out


def league(league_id):
    """Any configured league (enabled, disabled or pending), or None."""
    lg = _merged()["leagues"].get(str(league_id))
    if not isinstance(lg, dict):
        return None
    d = copy.deepcopy(lg)
    d["id"] = str(league_id)
    return d


def slug(league_id):
    """The league's StatsPlus slug: the settings slug, else the id in lower case."""
    lg = _merged()["leagues"].get(str(league_id)) or {}
    return lg.get("slug") or str(league_id).lower()


def slug_map():
    """{id: slug} of the enabled, non-pending StatsPlus leagues, defaults order first."""
    return {lid: slug(lid) for lid, lg in _merged()["leagues"].items()
            if lg.get("type") == "statsplus" and _active(lg)}


def online_leagues():
    """Ids of the enabled, non-pending StatsPlus leagues."""
    return list(slug_map())


def expand_path(p):
    """Expand %VAR% (defined variables only) and a leading ~. Nothing else."""
    if not isinstance(p, str):
        return p
    s = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), p)
    if s.startswith("~"):
        s = os.path.expanduser(s)
    return s


def saved_games_raw(version):
    """The saved_games folder of an OOTP version, expanded, not normalized."""
    inst = (_merged().get("ootp") or {}).get("installs") or {}
    v = (inst.get(str(version)) or {}).get("saved_games")
    return expand_path(v) if v else None


def saved_games(version):
    raw = saved_games_raw(version)
    return os.path.normpath(raw) if raw else None


def ootp_save_dir(league_id):
    """<saved_games of the league's version>/<ootp_save>.lg, or None. Answers for
    pending leagues too, so a new league's first pull finds its save."""
    lg = _merged()["leagues"].get(str(league_id)) or {}
    ver, save = lg.get("ootp_version"), lg.get("ootp_save")
    sg = saved_games(ver) if ver and save else None
    return os.path.join(sg, f"{save}.lg") if sg else None


def protected_saves():
    """Lower-case save names winsim never clones or sims and cleanup never
    deletes: ootp.protected_extra plus the save of every statsplus and
    local_export league, disabled and pending ones included. Never dev or clone
    leagues (winsim guards the folder it sims in place)."""
    m = _merged()
    out = {str(x).strip().lower() for x in (m.get("ootp") or {}).get("protected_extra") or []}
    for lg in m["leagues"].values():
        if lg.get("type") in ("statsplus", "local_export") and lg.get("ootp_save"):
            out.add(lg["ootp_save"].strip().lower())
    return out


def league_saves():
    """Lower-case save name of every configured league, any type, enabled or not."""
    return {lg["ootp_save"].strip().lower() for lg in _merged()["leagues"].values()
            if isinstance(lg.get("ootp_save"), str) and lg["ootp_save"].strip()}


def ootp_profiles():
    """ootp/leagues.json merged with the ootp_profile of every configured league.
    The file wins on a clash (New League refuses one)."""
    try:
        with open(PROFILES_PATH, encoding="utf-8") as f:
            out = json.load(f)
    except FileNotFoundError:
        out = {}
    for lid, lg in _merged()["leagues"].items():
        prof = lg.get("ootp_profile")
        if isinstance(prof, dict) and lid not in out:
            out[lid] = copy.deepcopy(prof)
    return out


def history_settings():
    """{id: {"first_date", "probe_years"}} of the enabled, non-pending StatsPlus
    leagues that have a history start date."""
    out = {}
    for lid, lg in _merged()["leagues"].items():
        h = lg.get("history") if isinstance(lg.get("history"), dict) else {}
        if lg.get("type") == "statsplus" and _active(lg) and h.get("first_date"):
            out[lid] = {"first_date": h["first_date"], "probe_years": int(h.get("probe_years", 0))}
    return out


def token_file(use_env=True):
    """Absolute path of the StatsPlus token file. STATSPLUS_TOKEN_FILE still
    wins (tests); use_env=False gives the settings file alone."""
    env = os.environ.get("STATSPLUS_TOKEN_FILE", "").strip() if use_env else ""
    if env:
        return os.path.abspath(env)
    p = expand_path(_merged()["statsplus"]["token_file"])
    return os.path.abspath(p if os.path.isabs(p) else os.path.join(REPO, p))


def app_config():
    """The browser-safe subset: {"leagues": {id: {"name", "my_org"}}}."""
    out = {}
    for lid, lg in leagues().items():
        e = {"name": lg.get("name") or lid}
        if lg.get("my_org"):
            e["my_org"] = lg["my_org"]
        out[lid] = e
    return {"leagues": out}


def extra_leagues():
    """{id: basis} of the enabled StatsPlus and local_export leagues that price
    with another league's calibration (today: RG -> BLM)."""
    return {lid: lg["basis"] for lid, lg in leagues().items()
            if lg.get("type") in ("statsplus", "local_export") and lg.get("basis") and lg["basis"] != lid}


# ---------------------------------------------------------------- writing
def atomic_write_text(path, text, newline=None):
    """Write text to <path>.<pid>.tmp, then os.replace it onto path. A
    PermissionError from os.replace (a reader holds the file) is retried 10
    times, 200 ms apart."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)
    replace_retry(tmp, path)


def replace_retry(src, dst, tries=10, wait=0.2):
    """os.replace with retries on PermissionError. Removes src when it fails."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                try:
                    os.remove(src)
                except OSError:
                    pass
                raise
            time.sleep(wait)


def write_local(patch):
    """Deep-merge patch into the local file, check the result, write it
    atomically. A None value in patch deletes that key. Returns the merged
    settings. Raises SettingsError and writes nothing when a check fails."""
    if not isinstance(patch, dict):
        raise SettingsError("the patch must be one JSON object")
    lpath = local_path()
    defaults = _load_files_defaults_only()
    local = _read_json(lpath, required=False) or {}
    new_local = _patch(local, patch)
    merged = _merge(defaults, new_local)
    problems = validate(merged)
    if problems:
        raise SettingsError(f"{_label(lpath)}: " + "; ".join(problems), problems, lpath)
    atomic_write_text(lpath, json.dumps(new_local, indent=2, ensure_ascii=False) + "\n")
    _CACHE.update(key=None, merged=None)
    return copy.deepcopy(_merged(refresh=True))


def _load_files_defaults_only():
    defaults = _platform_defaults(_read_json(DEFAULTS_PATH, required=True))
    problems = validate(defaults) + _pending_in(defaults)
    if problems:
        raise SettingsError(f"{_label(DEFAULTS_PATH)}: " + "; ".join(problems), problems, DEFAULTS_PATH)
    return defaults


# ---------------------------------------------------------------- command line
def _get(merged, dotted):
    cur = merged
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise KeyError(dotted)
    return cur


def _out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=True))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    usage = ("usage: settings.py --json | --app-json | get <dotted.key> | "
             "set --patch-file <path> | validate")
    if not args:
        print(usage, file=sys.stderr)
        return 2
    cmd = args[0]
    try:
        if cmd == "--json":
            _out(load())
            return 0
        if cmd == "--app-json":
            _out(app_config())
            return 0
        if cmd == "get" and len(args) == 2:
            try:
                _out(_get(load(), args[1]))
            except KeyError:
                print(f"no setting named {args[1]}", file=sys.stderr)
                return 2
            return 0
        if cmd == "validate":
            load(refresh=True)
            print("Settings OK.")
            return 0
    except SettingsError as e:
        if cmd == "validate":
            print("Settings problems:")
            for p in e.problems:
                print(f"  {_label(e.path) + ': ' if e.path and not p.startswith(_label(e.path)) else ''}{p}")
        else:
            print(str(e), file=sys.stderr)
        return 2
    if cmd == "set" and len(args) == 3 and args[1] == "--patch-file":
        try:
            with open(args[2], encoding="utf-8-sig") as f:
                patch = json.load(f)
        except (OSError, ValueError) as e:
            _out({"ok": False, "errors": [f"the patch file could not be read ({type(e).__name__})"]})
            return 2
        try:
            merged = write_local(patch)
        except SettingsError as e:
            _out({"ok": False, "errors": e.problems})
            return 2
        except OSError as e:
            _out({"ok": False, "errors": [f"{_label(local_path())} could not be written ({e.strerror or e})"]})
            return 2
        _out({"ok": True, "merged": merged})
        return 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
