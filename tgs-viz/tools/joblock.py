"""Jobs, named locks and process identity for the Control panel (DESIGN.md 7).

Only run_task.py writes state.json, events.jsonl, lock files and active
entries. doctor.py imports this module to read them.

Never call os.kill(pid, 0) here: on Windows signal 0 is CTRL_C_EVENT. Process
checks go through proc_start_time().
"""
import datetime
import json
import os
import re
import shutil
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JOB_ID_RE = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$")
FINAL = ("done", "partial", "failed", "stopped", "killed", "invalid", "refused", "lost")
KEEP_JOBS = 50


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---- paths

def control_dir():
    """<repo>/.control, or TGS_CONTROL_DIR when set."""
    p = os.environ.get("TGS_CONTROL_DIR", "").strip()
    return os.path.abspath(p) if p else os.path.join(REPO, ".control")


def jobs_dir():
    return os.path.join(control_dir(), "jobs")


def job_dir(job_id):
    return os.path.join(jobs_dir(), job_id)


def active_dir():
    return os.path.join(control_dir(), "active")


def locks_dir():
    return os.path.join(control_dir(), "locks")


LOCK_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def lock_path(name):
    """<control>/locks/<name>.json. A name that could leave the locks folder raises ValueError."""
    name = str(name)
    if not LOCK_NAME_RE.match(name) or ".." in name:
        raise ValueError(f"The lock name {name!r} is not valid.")
    return os.path.join(locks_dir(), name + ".json")


def active_path(job_id):
    return os.path.join(active_dir(), job_id + ".json")


def new_job_id(task_id):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{task_id}-{os.urandom(2).hex()}"


# ---- files

def replace_retry(src, dst, tries=10, wait=0.2):
    """os.replace with retries: a reader on Windows can block the swap for a moment."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait)


def write_json_atomic(path, obj):
    """Write <path>.<pid>.tmp, then replace the target."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    data = json.dumps(obj, ensure_ascii=False, indent=1)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
        f.write("\n")
    try:
        replace_retry(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


UNREADABLE_AGE = 5.0


def unreadable(path, min_age=UNREADABLE_AGE):
    """True when a lock or active file can be opened but holds no JSON object and is
    older than min_age seconds. Locks and entries are written whole (tmp, then rename),
    so such a file was cut short by a crash or a power cut: its record is gone."""
    try:
        if time.time() - os.path.getmtime(path) < min_age:
            return False
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return False
    try:
        return not isinstance(json.loads(data.decode("utf-8")), dict)
    except (UnicodeDecodeError, ValueError):
        return True


def unreadable_files():
    """[(kind, name)] of the unreadable lock and active files (kind "locks" or "active")."""
    out = []
    for kind, folder in (("locks", locks_dir()), ("active", active_dir())):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if n.endswith(".json") and unreadable(os.path.join(folder, n)):
                out.append((kind, n[:-5]))
    return out


def remove_file(path, tries=10):
    """Delete a file. A reader can hold it open for a moment on Windows, so a
    PermissionError is retried."""
    for i in range(tries):
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False
        except PermissionError:
            if i == tries - 1:
                return False
            time.sleep(0.05)
        except OSError:
            return False
    return False


# ---- process identity (ctypes, no packages)

def proc_start_time(pid):
    """Creation time of a running process as a 64-bit FILETIME integer, or
    None when no such process runs (or it cannot be opened)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if sys.platform != "win32":
        return _posix_start_time(pid)
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return None
        if code.value != STILL_ACTIVE:
            return None
        c, e, k, u = (wintypes.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return (c.dwHighDateTime << 32) | c.dwLowDateTime
    finally:
        k32.CloseHandle(h)


def _posix_start_time(pid):
    if sys.platform == "darwin":
        return _darwin_start_time(pid)
    try:
        with open(f"/proc/{pid}/stat", "r") as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


_LIBPROC = []


def _darwin_start_time(pid):
    """Start time in microseconds from libproc proc_pidinfo(PROC_PIDTBSDINFO), or None
    when no such process runs or it is a zombie (macOS has no /proc)."""
    import ctypes

    class BsdInfo(ctypes.Structure):           # struct proc_bsdinfo, <sys/proc_info.h>
        _fields_ = [("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
                    ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("ids", ctypes.c_uint32 * 6),
                    ("rfu_1", ctypes.c_uint32), ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
                    ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("pjobc", ctypes.c_uint32),
                    ("tdev", ctypes.c_uint32), ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
                    ("start_tvsec", ctypes.c_uint64), ("start_tvusec", ctypes.c_uint64)]

    PROC_PIDTBSDINFO, SZOMB = 3, 5
    try:
        if not _LIBPROC:
            lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
            lib.proc_pidinfo.restype = ctypes.c_int
            lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            _LIBPROC.append(lib)
        info = BsdInfo()
        n = _LIBPROC[0].proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    except (OSError, AttributeError):
        return None
    if n != ctypes.sizeof(info) or info.pid != pid or info.status == SZOMB:
        return None
    return info.start_tvsec * 1_000_000 + info.start_tvusec


def posix_kill_tree(pid, grace=3.0):
    """POSIX twin of taskkill /PID pid /T /F: SIGTERM the process, its descendants (from
    ps) and the process groups they lead, then SIGKILL whatever is left after grace
    seconds. Never signals the caller's own process group."""
    import signal
    import subprocess
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    kids = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    pids, todo = [], [pid]
    while todo:
        p = todo.pop()
        if p not in pids:
            pids.append(p)
            todo.extend(kids.get(p, []))
    own = os.getpgrp()
    groups = set()
    for p in pids:
        try:
            if os.getpgid(p) == p and p != own:
                groups.add(p)
        except OSError:
            pass

    def send(sig):
        for g in groups:
            try:
                os.killpg(g, sig)
            except OSError:
                pass
        for p in pids:
            try:
                os.kill(p, sig)
            except OSError:
                pass

    def running(p):
        try:
            os.kill(p, 0)
        except OSError:
            return False
        try:                                   # a child of ours that exited is a zombie: reap it
            done, _ = os.waitpid(p, os.WNOHANG)
            return done == 0
        except ChildProcessError:
            return proc_start_time(p) is not None

    send(signal.SIGTERM)
    end = time.time() + grace
    while time.time() < end and any(running(p) for p in pids):
        time.sleep(0.05)
    if any(running(p) for p in pids):
        send(signal.SIGKILL)


def alive(rec):
    """True when the process the record names still runs (pid and start time match)."""
    if not isinstance(rec, dict):
        return False
    pid, started = rec.get("pid"), rec.get("pid_started")
    if pid is None or started is None:
        return False
    st = proc_start_time(pid)
    return st is not None and st == started


def me():
    pid = os.getpid()
    return {"pid": pid, "pid_started": proc_start_time(pid)}


# ---- active entries

def write_active(entry):
    write_json_atomic(active_path(entry["job_id"]), entry)


def remove_active(job_id):
    remove_file(active_path(job_id))


def list_active():
    """Active entries, oldest first."""
    out = []
    try:
        names = sorted(os.listdir(active_dir()))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        rec = read_json(os.path.join(active_dir(), n))
        if isinstance(rec, dict) and rec.get("job_id"):
            out.append(rec)
    return out


# ---- locks

LOCK_REASONS = {
    "ootp": "uses OOTP and your mouse",
    "data": "is updating app data",
}


def lock_reason(name):
    if name in LOCK_REASONS:
        return LOCK_REASONS[name]
    kind, _, arg = name.partition(".")
    if kind == "clones":
        return f"uses the {arg} clone saves"
    if kind == "dumps":
        return f"uses the {arg} dump folder"
    if kind == "task":
        return "is this same task"
    return "holds the lock " + name


def read_lock(name):
    return read_json(lock_path(name))


def take_lock(name, holder):
    """Try to take a lock. holder: {job_id, task, title, mode, pid, pid_started}.
    Returns (True, None) or (False, holder of the busy lock)."""
    os.makedirs(locks_dir(), exist_ok=True)
    rec = {"schema": 1, "name": name, "job_id": holder["job_id"], "task": holder.get("task"),
           "title": holder.get("title"), "mode": holder.get("mode"), "pid": holder["pid"],
           "pid_started": holder["pid_started"], "since": now_iso()}
    path = lock_path(name)
    reaped = False
    cur = None
    for _ in range(6):
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            try:
                if sys.platform == "win32":
                    os.rename(tmp, path)
                else:
                    os.link(tmp, path)      # POSIX rename overwrites; link fails when path exists
                return True, None
            except FileExistsError:
                pass
        finally:
            remove_file(tmp)
        cur = read_json(path)
        if cur is None:
            if unreadable(path):
                # a lock file cut short by a crash names no holder: drop it
                remove_file(path)
                continue
            # gone since the rename failed, or being deleted: try again
            time.sleep(0.02)
            continue
        if cur.get("job_id") == holder["job_id"]:
            return True, None
        if alive(cur):
            return False, cur
        if not reaped:
            reaped = True
            reap_job(cur.get("job_id"), lock_rec=cur)
            continue
        return False, cur
    return False, cur or {"name": name}


def release_lock(name, job_id):
    """Delete the lock file only when this job holds it."""
    cur = read_json(lock_path(name))
    if isinstance(cur, dict) and cur.get("job_id") == job_id:
        return remove_file(lock_path(name))
    return False


def list_locks():
    out = {}
    try:
        names = os.listdir(locks_dir())
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        rec = read_json(os.path.join(locks_dir(), n))
        if isinstance(rec, dict):
            out[n[:-5]] = rec
    return out


def release_all(job_id):
    released = []
    for name, rec in list_locks().items():
        if rec.get("job_id") == job_id:
            if remove_file(os.path.join(locks_dir(), name + ".json")):
                released.append(name)
    return released


# ---- stale jobs

def tail_lines(path, n=20):
    try:
        with open(path, "rb") as f:
            data = f.read()[-65536:]
    except OSError:
        return []
    text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    return [l for l in text.split("\n") if l.strip()][-n:]


def reap_job(job_id, lock_rec=None):
    """Apply the stale rule to one job whose runner is gone. Returns the status
    written, or None when the job is alive or unknown."""
    if not job_id or not JOB_ID_RE.match(str(job_id)):
        if lock_rec is not None:
            # a lock with no valid job: drop it when its holder is gone
            if not alive(lock_rec) and lock_rec.get("name"):
                try:
                    remove_file(lock_path(lock_rec["name"]))
                except ValueError:
                    pass
        return None
    entry = read_json(active_path(job_id))
    if isinstance(entry, dict) and alive(entry):
        return None
    if entry is None and lock_rec is not None and alive(lock_rec):
        return None
    jd = job_dir(job_id)
    state_path = os.path.join(jd, "state.json")
    state = read_json(state_path)
    status = None
    if os.path.isdir(jd):
        if not isinstance(state, dict) or state.get("status") == "starting":
            st = state if isinstance(state, dict) else {"schema": 1, "id": job_id}
            st.update({"status": "failed", "ended": now_iso(),
                       "message": "The runner stopped before it started the task.",
                       "summary": tail_lines(os.path.join(jd, "runner.log"), 20)})
            if entry:
                for k in ("task", "title", "mode", "pid", "pid_started", "started"):
                    st.setdefault(k, entry.get(k))
            write_json_atomic(state_path, st)
            status = "failed"
            end_events(jd, st)
        elif state.get("status") not in FINAL:
            state.update({"status": "lost", "ended": now_iso(), "prompt": None,
                          "waiting_for": None, "pending_leagues": [], "locks_held": [],
                          "message": state.get("message") or "The task's runner stopped without finishing."})
            for s in state.get("steps") or []:
                if s.get("status") in ("running", "pending"):
                    s["status"] = "skipped" if s.get("status") == "pending" else "killed"
            write_json_atomic(state_path, state)
            status = "lost"
            end_events(jd, state)
        else:
            status = state.get("status")
    release_all(job_id)
    remove_active(job_id)
    return status


def end_events(jd, state):
    """Append job_end to a job the runner could not finish (and job_start first
    when the runner never wrote one), so the event log is always complete."""
    p = os.path.join(jd, "events.jsonl")
    seq, started = 0, False
    try:
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    seq += 1
                    if '"job_start"' in ln:
                        started = True
    except OSError:
        pass
    try:
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            if not started:
                seq += 1
                f.write(json.dumps({"seq": seq, "at": now_iso(), "type": "job_start", "task": state.get("task"),
                                    "mode": state.get("mode"), "steps_total": len(state.get("steps") or [])}) + "\n")
            seq += 1
            f.write(json.dumps({"seq": seq, "at": now_iso(), "type": "job_end", "status": state.get("status"),
                                "exit_code": state.get("exit_code"), "fails": state.get("fails") or [],
                                "summary": state.get("summary") or []}) + "\n")
    except OSError:
        pass


def reap_all():
    """Reap every stale active entry. Returns [{"job_id", "status"}]."""
    out = []
    for entry in list_active():
        if alive(entry):
            continue
        st = reap_job(entry["job_id"])
        out.append({"job_id": entry["job_id"], "status": st})
    # locks whose holder is gone and whose job has no active entry
    for name, rec in list_locks().items():
        if not alive(rec) and not os.path.exists(active_path(str(rec.get("job_id")))):
            jid = rec.get("job_id")
            st = reap_job(jid, lock_rec=rec)
            if jid and not any(r["job_id"] == jid for r in out):
                out.append({"job_id": jid, "status": st})
    # files cut short by a crash: an active entry is reaped by its file name (unless
    # its state shows a live runner); a lock file names no job, so it is removed
    for kind, name in unreadable_files():
        if kind == "active":
            if not JOB_ID_RE.match(name) or alive(read_json(os.path.join(job_dir(name), "state.json"))):
                continue
            st = reap_job(name)
            if not any(r["job_id"] == name for r in out):
                out.append({"job_id": name, "status": st})
        elif remove_file(os.path.join(locks_dir(), name + ".json")):
            out.append({"job_id": None, "status": "unreadable", "lock": name})
    return out


def lock_status():
    locks = {}
    for name, rec in list_locks().items():
        r = dict(rec)
        r["alive"] = alive(rec)
        locks[name] = r
    active = []
    for entry in list_active():
        e = dict(entry)
        e["alive"] = alive(entry)
        st = read_json(os.path.join(job_dir(entry["job_id"]), "state.json"))
        e["status"] = st.get("status") if isinstance(st, dict) else None
        active.append(e)
    return {"locks": locks, "active": active}


# ---- job folder housekeeping

def pending_league_ids():
    """Ids the New League wizard left pending in settings.local.json, or None when
    the settings cannot be read."""
    try:
        import settings as ST
        leagues = ST.local_raw().get("leagues") or {}
    except Exception:
        return None
    return {lid for lid, lg in leagues.items() if isinstance(lg, dict) and lg.get("pending")}


def new_league_leftover(job_id, state=None, pending=None):
    """The league id of a lost or failed New League job whose league is still
    pending (pending=None: any), else None. Its clean-up needs the job folder."""
    st = state if isinstance(state, dict) else read_json(os.path.join(job_dir(job_id), "state.json"))
    if not isinstance(st, dict) or st.get("task") != "new_league" or st.get("status") not in ("lost", "failed"):
        return None
    if any(isinstance(s, dict) and s.get("id") == "register" and s.get("status") == "ok"
           for s in st.get("steps") or []):
        return None
    spec = read_json(os.path.join(job_dir(job_id), "new_league_spec.json"))
    lid = str((spec or {}).get("id") or "").strip() if isinstance(spec, dict) else ""
    if not lid:
        return None
    return lid if pending is None or lid in pending else None


def prune_jobs(keep=KEEP_JOBS, min_age=600):
    """Keep the newest finished job folders; delete older finished ones.
    Never touches a job with an active entry, or a folder younger than min_age s,
    or a lost or failed New League job whose league is still pending (12.6)."""
    try:
        names = sorted(n for n in os.listdir(jobs_dir()) if JOB_ID_RE.match(n))
    except OSError:
        return []
    active = {e["job_id"] for e in list_active()}
    finished = []
    pending = False
    for n in names:
        if n in active:
            continue
        st = read_json(os.path.join(jobs_dir(), n, "state.json"))
        if isinstance(st, dict) and st.get("status") not in FINAL:
            continue
        if isinstance(st, dict) and st.get("task") == "new_league":
            if pending is False:
                pending = pending_league_ids()
            if new_league_leftover(n, st, pending):
                continue
        finished.append(n)
    removed = []
    now = time.time()
    for n in finished[:-keep] if keep else finished:
        p = os.path.join(jobs_dir(), n)
        try:
            if now - os.path.getmtime(p) < min_age:
                continue
            shutil.rmtree(p)
            removed.append(n)
        except OSError:
            pass
    return removed
