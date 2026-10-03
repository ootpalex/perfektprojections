"""
doctor.py - the setup check: what this computer needs before the app and its
tasks can run, and what to do about each gap.

    python tgs-viz/tools/doctor.py            one line per check, then the fix
    python tgs-viz/tools/doctor.py --json     {"schema": 1, "ok": bool, "checks": [...]}
    python tgs-viz/tools/doctor.py --deep     also parse each league's player files

No network and no writes: tokens are read in memory (never printed, only
"present", "empty" or "looks wrong: N characters"), the ratings archive opens
read-only, the job check only reads the control folder. Checks of disabled
leagues are skipped.

Status: fail only when the app or the Control page cannot work (Node, the app
packages, the settings files) or a league the app lists cannot load. The rest
is warn or ok, and every warn says which task needs it.

Exit code: 0 when no check failed, 1 when one did (the doctor task shows that
as "Finished with problems").
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/tools
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
DATA = os.path.join(VIZ, "public", "data")
for _p in (HERE, os.path.join(VIZ, "ingest"), os.path.join(VIZ, "backtest")):
    if _p not in sys.path:
        sys.path.append(_p)
import settings as ST  # noqa: E402

NO_WINDOW = 0x08000000 if os.name == "nt" else 0            # CREATE_NO_WINDOW
WARN_DAYS = 80
PY_FIX = ("Install Python 3.13 from python.org and tick Add python.exe to PATH, or set the command on the Setup page."
          if os.name == "nt" else
          "Install Python 3.13 (python.org or Homebrew) or make the repo's .venv, or set the command on the Setup page.")
# pywin32 (win32gui) exists only on Windows; the OOTP automation is Windows-only
GUI_MODULES = ["pyautogui", "win32gui", "cv2", "PIL"] if os.name == "nt" else ["pyautogui", "cv2", "PIL"]


class Doctor:
    def __init__(self, deep=False):
        self.deep = deep
        self.rows = []
        self.settings_ok = True

    def add(self, cid, title, status, detail="", fix="", task=None):
        self.rows.append({"id": cid, "title": title, "status": status, "detail": detail,
                          "fix": fix, "task": task})


# ---------------------------------------------------------------- helpers
def run(argv, timeout=15):
    """(exit code, stdout+stderr) of argv with no shell and no window; code
    'ENOENT' when the program does not exist, 'timeout' when it hangs."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return "ENOENT", ""
    except subprocess.TimeoutExpired:
        return "timeout", ""
    except OSError as e:
        return "ENOENT", str(e)


def probe_python(argv):
    """{ok, version (tuple), executable, code, message}."""
    code, out = run(list(argv) + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1], "
                                         "sys.version_info[2]); print(sys.executable)"])
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if code == 0 and lines and re.fullmatch(r"\d+ \d+ \d+", lines[0]):
        ver = tuple(int(x) for x in lines[0].split())
        return {"ok": True, "version": ver, "executable": lines[1] if len(lines) > 1 else ""}
    if code == "ENOENT":
        msg = "the command does not exist"
    elif code == 9009:
        msg = "only the Microsoft Store shortcut answered (Python is not installed)"
    elif code == "timeout":
        msg = "it did not answer within 15 seconds"
    else:
        msg = f"it stopped with code {code}"
    return {"ok": False, "code": code, "message": msg}


def missing_modules(argv, names):
    """Names whose module the interpreter cannot find (find_spec: nothing is imported)."""
    code, out = run(list(argv) + ["-c", "import importlib.util as u, json, sys; "
                                         "print(json.dumps([n for n in sys.argv[1:] if u.find_spec(n) is None]))"]
                    + list(names))
    try:
        return json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _vtext(v):
    return ".".join(str(x) for x in v)


def _shown(argv):
    return " ".join(f'"{a}"' if " " in a else a for a in argv)


def control_dir():
    p = os.environ.get("TGS_CONTROL_DIR", "").strip()
    return os.path.abspath(p) if p else os.path.join(REPO, ".control")


def read_manifest():
    """public/data/leagues.json entries (either schema); [] when missing or broken."""
    try:
        with open(os.path.join(DATA, "leagues.json"), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("leagues", [])
    return [e for e in raw if isinstance(e, dict) and e.get("id")] if isinstance(raw, list) else []


def json_edges_ok(path):
    """True when the file is not empty and starts with [ and ends with ] (reads
    only the two ends, so a 90 MB file costs nothing)."""
    try:
        size = os.path.getsize(path)
        if size < 2:
            return False
        with open(path, "rb") as f:
            head = f.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
            f.seek(max(0, size - 64))
            tail = f.read().rstrip(b" \t\r\n")
        return head[:1] == b"[" and tail[-1:] == b"]"
    except OSError:
        return False


# ---------------------------------------------------------------- checks
def check_settings(d):
    try:
        ST.load(refresh=True)
        d.add("settings", "Settings", "ok", "settings.defaults.json" +
              (f" and {os.path.basename(ST.local_path())}" if os.path.isfile(ST.local_path()) else
               " (no local settings file)"))
    except ST.SettingsError as e:
        d.settings_ok = False
        # a validation problem names a key; a file that does not read or parse names none
        named = "file and key" if list(e.problems) != [str(e)] else "file"
        d.add("settings", "Settings", "fail", str(e),
              f"Fix the {named} named above. Or press Reset local settings on the Setup page.")


def check_python(d):
    try:
        main_argv, ml_argv = ST.interp("main"), ST.interp("ml")
    except (ST.SettingsError, KeyError):
        main_argv, ml_argv = (["python"], ["py", "-3.14"]) if os.name == "nt" else (["python3"], ["python3"])
    pm = probe_python(main_argv)
    if pm["ok"] and pm["version"] >= (3, 11):
        d.add("python.main", "Python (main)", "ok", f"{_vtext(pm['version'])} ({_shown(main_argv)}): {pm['executable']}")
        miss = missing_modules(main_argv, ["openpyxl", "numpy"] + GUI_MODULES)
        if miss is None:
            d.add("python.main.packages", "Packages (main)", "warn", "the package check did not answer",
                  f"Run: {_shown(main_argv)} -m pip install -r requirements.txt")
        else:
            core = [m for m in miss if m in ("openpyxl", "numpy")]
            gui = [{"win32gui": "pywin32", "cv2": "opencv-python", "PIL": "Pillow"}.get(m, m)
                   for m in miss if m not in ("openpyxl", "numpy")]
            if not miss:
                d.add("python.main.packages", "Packages (main)", "ok", "openpyxl, numpy and the OOTP automation packages")
            else:
                parts = []
                if core:
                    parts.append(f"missing {', '.join(core)} (needed by every update task)")
                if gui:
                    parts.append(f"missing {', '.join(gui)} (needed only for Grind, Sim Dev League and the OOTP tools)")
                d.add("python.main.packages", "Packages (main)", "warn", "; ".join(parts),
                      f"Run: {_shown(main_argv)} -m pip install -r requirements.txt")
    else:
        if pm["ok"]:
            detail = f"{_vtext(pm['version'])} is too old ({_shown(main_argv)}); the tasks need 3.11 or newer"
        else:
            detail = f"{_shown(main_argv)} does not start: {pm['message']}"
        fix = PY_FIX
        alt = probe_python(["py", "-3"]) if os.name == "nt" and main_argv != ["py", "-3"] else {"ok": False}
        if alt["ok"] and alt["version"] >= (3, 11):
            fix = "Set Python (main) to py -3 on the Setup page."
        d.add("python.main", "Python (main)", "warn", detail + ". The app still opens; every task needs Python.", fix)
        d.add("python.main.packages", "Packages (main)", "skip", "Python (main) does not start")
    pl = probe_python(ml_argv)
    why = "needed for ML dev scores; without it the app uses the older cell method"
    if pl["ok"] and pl["version"] >= (3, 11):
        d.add("python.ml", "Python (ML)", "ok", f"{_vtext(pl['version'])} ({_shown(ml_argv)}): {pl['executable']}")
        # xgboost: peak.py trains the gain quantiles with it, and the saved models
        # need it to load, so ML scoring stops without it
        miss = missing_modules(ml_argv, ["numpy", "pandas", "sklearn", "xgboost"])
        if miss is None or miss:
            names = ", ".join({"sklearn": "scikit-learn"}.get(m, m) for m in (miss or []))
            extra = "; the ML gain models do not load without xgboost" if "xgboost" in (miss or []) else ""
            d.add("python.ml.packages", "Packages (ML)", "warn",
                  (f"missing {names}" if names else "the package check did not answer") + f" ({why}{extra})",
                  f"Run: {_shown(ml_argv)} -m pip install -r requirements-ml.txt")
        else:
            d.add("python.ml.packages", "Packages (ML)", "ok", "numpy, pandas, scikit-learn, xgboost")
    else:
        detail = (f"{_vtext(pl['version'])} is too old" if pl["ok"] else
                  f"{_shown(ml_argv)} does not start: {pl['message']}")
        d.add("python.ml", "Python (ML)", "warn", f"{detail} ({why})",
              "Install Python 3.14, or set the ML command on the Setup page.")
        d.add("python.ml.packages", "Packages (ML)", "skip", "Python (ML) does not start")


def node_ok(text):
    """Vite 7 engines: ^20.19.0 || >=22.12.0."""
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    if not m:
        return False, None
    v = tuple(int(x) for x in m.groups())
    ok = (v[0] == 20 and v[1] >= 19) or (v[0] == 22 and v[1] >= 12) or v[0] >= 23
    return ok, v


def check_node(d):
    try:
        argv = ST.interp("node")
    except (ST.SettingsError, KeyError):
        argv = ["node"]
    code, out = run(list(argv) + ["--version"])
    ok, v = node_ok(out) if code == 0 else (False, None)
    if ok:
        d.add("node", "Node.js", "ok", f"{_vtext(v)} ({_shown(argv)})")
    elif v:
        d.add("node", "Node.js", "fail", f"{_vtext(v)} is too old for the app (it needs 20.19 or 22.12 or newer)",
              "Install Node.js 22 LTS.")
    else:
        d.add("node", "Node.js", "fail", f"{_shown(argv)} does not start", "Install Node.js 22 LTS.")
    vite_cmd = os.path.join(VIZ, "node_modules", ".bin", "vite.cmd" if os.name == "nt" else "vite")
    vite_pkg = os.path.join(VIZ, "node_modules", "vite", "package.json")
    ver = None
    try:
        with open(vite_pkg, encoding="utf-8") as f:
            ver = str(json.load(f).get("version") or "")
    except (OSError, ValueError):
        pass
    if os.path.isfile(vite_cmd) and ver and ver.startswith("7"):
        d.add("node_modules", "App packages", "ok", f"Vite {ver}")
    else:
        d.add("node_modules", "App packages", "fail",
              "not installed" if not ver else f"Vite {ver} found; the app needs Vite 7",
              "Open a terminal in tgs-viz and run: npm install")


def check_tokens(d):
    import statsplus_token as T
    path = T.token_file()
    have_file = os.path.isfile(path)
    for lid, slug in ST.slug_map().items():
        line = slug.upper() + "="
        title = f"StatsPlus token: {lid}"
        fix = (f"Paste the token from statsplus.net/{slug} Prefs on the line {line} in {os.path.basename(path)}, "
               "or use Replace a StatsPlus token on the Setup page.")
        if not have_file:
            d.add(f"tokens.{lid}", title, "warn", f"{os.path.basename(path)} is missing (needed by Update {lid} "
                  "and Get StatsPlus Ratings; the browser cookie still works)", fix, "token_set")
            continue
        entry = T._read().get(slug)
        tok = T.token_for(slug)
        if tok:
            age = T.token_age(slug) or {}
            days = age.get("days")
            if days is None:
                d.add(f"tokens.{lid}", title, "ok", "present (first seen today on this computer)")
            elif days > WARN_DAYS:
                d.add(f"tokens.{lid}", title, "warn", f"present, {days} days old; tokens expire after 90 days",
                      fix, "token_set")
            else:
                d.add(f"tokens.{lid}", title, "ok", f"present, {days} days old")
        elif entry and str(entry[2] or "").strip():
            n = len(T.clean_token(entry[2]))
            d.add(f"tokens.{lid}", title, "warn", f"looks wrong: {n} characters (needed by Update {lid})",
                  fix, "token_set")
        else:
            d.add(f"tokens.{lid}", title, "warn", f"empty (needed by Update {lid}; the browser cookie still works)",
                  fix, "token_set")


def check_ootp(d, leagues):
    installs = (ST.load().get("ootp") or {}).get("installs") or {}
    for ver in sorted(installs, key=int):
        sg = ST.saved_games(ver)
        users = [lg.get("name") or lid for lid, lg in leagues.items() if str(lg.get("ootp_version") or "") == ver]
        if sg and os.path.isdir(sg):
            n = sum(1 for x in os.listdir(sg) if x.lower().endswith(".lg") and os.path.isdir(os.path.join(sg, x)))
            d.add(f"ootp.{ver}", f"OOTP {ver} saved games", "ok", f"{sg}: {n} saves")
        else:
            need = f"needed by the tasks of {', '.join(users)}" if users else "no league uses it"
            d.add(f"ootp.{ver}", f"OOTP {ver} saved games", "warn" if users else "ok",
                  f"{sg or '(not set)'} is missing ({need})", "Set the saved_games folder on the Setup page.")


def check_leagues(d, leagues, manifest):
    by_id = {e.get("id"): e for e in manifest}
    for lid, lg in leagues.items():
        name = lg.get("name") or lid
        save = ST.ootp_save_dir(lid)
        if save:
            if not os.path.isdir(save):
                d.add(f"league.{lid}.save", f"{name}: OOTP save", "warn",
                      f"{save} is missing (needed by the tasks that read this save)",
                      "Set the save and the OOTP version of this league on the Setup page.")
            elif lg.get("type") == "dev" and not os.path.isdir(os.path.join(save, "dump")):
                d.add(f"league.{lid}.save", f"{name}: OOTP save", "warn", f"{save} has no dump folder (needed by "
                      f"Update {name} and Sim Dev League)",
                      "In OOTP, turn on Export CSV files after each simulated season in this league.")
            else:
                d.add(f"league.{lid}.save", f"{name}: OOTP save", "ok", save)
    ids = [lid for lid, lg in leagues.items() if lg.get("type") != "clone"]
    disabled = {lid for lid, lg in ST.leagues(include_disabled=True).items() if lid not in leagues}
    ids += [i for i in by_id if i not in leagues and i not in disabled]
    for lid in ids:
        lg = leagues.get(lid) or {}
        name = lg.get("name") or (by_id.get(lid) or {}).get("name") or lid
        title = f"{name}: app data"
        fix = f"Run Update {name} on the Control page, or turn this league off on the Setup page."
        task = f"update.{lid}" if lid in leagues else None
        e = by_id.get(lid)
        if not e:
            d.add(f"league.{lid}.data", title, "warn", "not in the app yet (no entry in leagues.json)", fix, task)
            continue
        folder = os.path.join(DATA, lid)
        players = (e.get("features") or {}).get("players")
        if players is None:
            players = lg.get("type") != "dev"
        if players:
            bad = []
            for fn in ("hitters.json", "pitchers.json"):
                p = os.path.join(folder, fn)
                if not os.path.isfile(p):
                    bad.append(f"{fn} is missing")
                elif not json_edges_ok(p):
                    bad.append(f"{fn} is empty or cut off")
                elif d.deep:
                    try:
                        with open(p, encoding="utf-8") as f:
                            json.load(f)
                    except (OSError, ValueError):
                        bad.append(f"{fn} is not valid JSON")
            if bad:
                d.add(f"league.{lid}.data", title, "fail", "; ".join(bad) + " (picking it shows the error panel)",
                      fix, task)
            else:
                d.add(f"league.{lid}.data", title, "ok", "hitters.json and pitchers.json are there")
        else:
            p = os.path.join(folder, "rating_trends.json")
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                d.add(f"league.{lid}.data", title, "ok", "rating_trends.json is there")
            else:
                d.add(f"league.{lid}.data", title, "fail", "rating_trends.json is missing (picking it shows the "
                      "error panel)", fix, task)


def _vintage_counts(vint):
    out = {}
    if not os.path.isdir(vint):
        return out
    for lg in sorted(os.listdir(vint)):
        p = os.path.join(vint, lg, "_pulls.csv")
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8", newline="") as f:
                    out[lg] = sum(1 for _ in csv.DictReader(f))
            except (OSError, csv.Error):
                pass
    return out


def check_archive(d):
    import pull_order as PO
    db, vint = PO.DB_PATH, PO.VINTAGES_DIR
    vc = _vintage_counts(vint)
    if not os.path.isfile(db):
        if vc:
            d.add("ratings_db", "Ratings archive", "warn",
                  "missing while saved vintages exist (every update task refuses until it is rebuilt)",
                  "Rebuild it from the saved vintages.", "restore_ratings_db")
        else:
            d.add("ratings_db", "Ratings archive", "ok", "none yet (the first pull starts it)")
        return
    try:
        conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            pulls = dict(conn.execute("SELECT league, COUNT(*) FROM pulls GROUP BY league").fetchall())
        finally:
            conn.close()
    except sqlite3.Error as e:
        d.add("ratings_db", "Ratings archive", "warn", f"could not be read ({e})",
              "Close other programs that use it, then run the check again.")
        return
    short = [f"{lg}: {pulls.get(lg, 0)} pulls, {n} vintages" for lg, n in vc.items() if pulls.get(lg, 0) < n]
    if short:
        d.add("ratings_db", "Ratings archive", "warn", "; ".join(short),
              "The archive has fewer pulls than the saved vintages. Rename tgs-viz\\backtest\\ratings_history.db, "
              "then run Rebuild ratings archive.", "restore_ratings_db")
    else:
        d.add("ratings_db", "Ratings archive", "ok",
              ", ".join(f"{lg} {n}" for lg, n in sorted(pulls.items())) + " pulls")


def check_models(d):
    root = os.path.join(VIZ, "backtest", ".dev_cache", "ml", "models")
    has = False
    for _dp, _dn, files in os.walk(root):
        if files:
            has = True
            break
    if has:
        d.add("ml_models", "ML dev models", "ok", "trained models are there")
    else:
        d.add("ml_models", "ML dev models", "warn", "no trained models",
              "The app uses the older cell method until Bank Dev Seasons trains the models.")


def check_git(d):
    code, _out = run(["git", "--version"])
    if code != 0:
        d.add("git_ignore", "Secrets stay off GitHub", "skip", "git is not installed")
        return
    bad = []
    for name in ("StatsPlus Tokens.txt", "settings.local.json"):
        c, _o = run(["git", "-C", REPO, "check-ignore", "-q", name])
        if c == 128:
            d.add("git_ignore", "Secrets stay off GitHub", "skip", "this folder is not a git checkout")
            return
        if c != 0:
            bad.append(name)
    if bad:
        d.add("git_ignore", "Secrets stay off GitHub", "warn", f"git would upload {', '.join(bad)}",
              "Add these names to .gitignore.")
    else:
        d.add("git_ignore", "Secrets stay off GitHub", "ok", "StatsPlus Tokens.txt and settings.local.json are ignored")


def check_jobs(d):
    try:
        import joblock as JL
    except ImportError:
        d.add("jobs", "Control jobs", "skip", "the job module (joblock.py) is not there")
        return
    own = os.environ.get("TGS_JOB_ID", "").strip()
    stale = {}
    for rec in JL.list_active():
        if rec.get("job_id") != own and not JL.alive(rec):
            stale[rec["job_id"]] = rec.get("title") or rec.get("task") or rec["job_id"]
    for name, rec in JL.list_locks().items():
        if rec.get("job_id") and rec.get("job_id") != own and not JL.alive(rec):
            stale.setdefault(rec["job_id"], rec.get("title") or rec.get("task") or rec["job_id"])
    broken = [f"{kind}\\{name}.json" for kind, name in getattr(JL, "unreadable_files", lambda: [])()
              if name != own]
    if broken:
        d.add("jobs", "Control jobs", "warn",
              f"{', '.join(broken)} in the control folder cannot be read (cut short by a crash)",
              "Run this in the TGS Projections folder to remove them: python tgs-viz\\tools\\run_task.py --reap")
        return
    if not stale:
        d.add("jobs", "Control jobs", "ok", "no job left behind")
        return
    d.add("jobs", "Control jobs", "warn",
          "; ".join(f"{title} ({jid}) is not running but still holds its place" for jid, title in stale.items()),
          f"A task ended without cleaning up ({', '.join(stale.values())}). The next task cleans it up.")


def check_pending_leagues(d):
    """Leagues the New League wizard left half added, with no job still adding them."""
    try:
        import joblock as JL
    except ImportError:
        return
    pending = JL.pending_league_ids() or set()
    if not pending:
        return
    busy = set()
    for rec in JL.list_active():
        if rec.get("task") == "new_league" and JL.alive(rec):
            spec = JL.read_json(os.path.join(JL.job_dir(rec["job_id"]), "new_league_spec.json"))
            busy.add(str((spec or {}).get("id") or "").strip() if isinstance(spec, dict) else "")
    left = sorted(pending - busy)
    if not left:
        return
    try:
        names = sorted(os.listdir(JL.jobs_dir()), reverse=True)
    except OSError:
        names = []
    jobs = {}
    for n in names:
        if JL.JOB_ID_RE.match(n):
            lid = JL.new_league_leftover(n, None, set(left))
            if lid and lid not in jobs:
                jobs[lid] = n
    fixes = []
    for lid in left:
        if lid in jobs:
            fixes.append(f"{lid}: open http://localhost:3000/control/jobs/{jobs[lid]} "
                         "and press Clean up unfinished league.")
        else:
            fixes.append(f"{lid}: its New League job is gone. Delete the \"{lid}\" entry under \"leagues\" "
                         f"in {os.path.basename(ST.local_path())}.")
    d.add("leagues.pending", "Unfinished new leagues",
          "warn", f"{', '.join(left)} {'was' if len(left) == 1 else 'were'} not finished: a New League job "
                  "stopped before it added the league, so the id stays blocked", " ".join(fixes))


def collect(deep=False):
    d = Doctor(deep)
    check_settings(d)
    check_node(d)
    check_python(d)
    if d.settings_ok:
        leagues = ST.leagues()
        check_tokens(d)
        check_ootp(d, leagues)
        check_leagues(d, leagues, read_manifest())
        check_pending_leagues(d)
    check_archive(d)
    check_models(d)
    check_git(d)
    check_jobs(d)
    return d.rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Setup check for TGS Projections (no network, no writes).")
    ap.add_argument("--json", action="store_true", help="print one JSON object")
    ap.add_argument("--deep", action="store_true", help="also parse each league's player files")
    a = ap.parse_args(argv)
    rows = collect(a.deep)
    fails = sum(1 for r in rows if r["status"] == "fail")
    warns = sum(1 for r in rows if r["status"] == "warn")
    if a.json:
        print(json.dumps({"schema": 1, "ok": fails == 0, "checks": rows}, indent=2, ensure_ascii=True))
    else:
        tag = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]", "skip": "[SKIP]"}
        for r in rows:
            print(f"{tag[r['status']]} {r['title']}: {r['detail']}")
            if r["fix"] and r["status"] in ("warn", "fail"):
                print(f"    {r['fix']}")
        print(f"Setup check: {fails} problems, {warns} warnings.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
