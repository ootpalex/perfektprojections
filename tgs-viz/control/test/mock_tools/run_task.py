"""Test double for tgs-viz/tools/run_task.py (DESIGN.md 6.1, 7). Stdlib only.

Used only by the Control plugin smoke tests through TGS_CONTROL_TOOLS_DIR. It follows the job
folder contract (request.json, state.json, events.jsonl, log.txt, heartbeat, prompt/answer/stop,
active entries, lock files) for a few selftest tasks. It runs no pipeline step.
"""
import ctypes
import datetime as _dt
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TGS_VIZ = REPO / "tgs-viz"
PUBLIC_DATA = TGS_VIZ / "public" / "data"
CONTROL = Path(os.environ["TGS_CONTROL_DIR"]) if os.environ.get("TGS_CONTROL_DIR") else REPO / ".control"
JOBS = CONTROL / "jobs"
ACTIVE = CONTROL / "active"
LOCKS = CONTROL / "locks"
SELFTEST = os.environ.get("TGS_SELFTEST") == "1"
FINAL = {"done", "partial", "failed", "stopped", "killed", "invalid", "refused", "lost"}


def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def local_settings_path():
    v = os.environ.get("TGS_SETTINGS_LOCAL")
    return Path(v) if v else REPO / "settings.local.json"


# ---------------------------------------------------------------- process identity (7.6)

def proc_start_time(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code)) or code.value != 259:
            return None
        c, e, k, u = (ctypes.c_ulonglong() for _ in range(4))
        if not k32.GetProcessTimes(ctypes.c_void_p(h), ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return None
        return c.value
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def alive(rec):
    return bool(rec) and rec.get("pid_started") is not None and proc_start_time(rec.get("pid")) == rec.get("pid_started")


# ---------------------------------------------------------------- files

def write_json(path, obj):
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    for _ in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.2)
    os.replace(tmp, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- registry

def step(sid, title, action, args=None, data=True, app=None):
    return {"id": sid, "title": title, "action": action, "args": args or [],
            "writes_app_data": bool(app), "data": data, "app_leagues": app or []}


def task(tid, title, steps, group="selftest", inputs=None, read_only=False, hidden=False, locks=None,
         stop_modes=None, endless=False, time_label="Seconds", description="Self test."):
    flags = {"writes_app_data": any(s["writes_app_data"] for s in steps), "heavy": False, "long": False,
             "endless": endless, "drives_ootp": False, "needs_ootp_closed": False, "needs_excel_closed": False,
             "network": False, "secret_inputs": any(i["type"] == "secret" for i in (inputs or [])),
             "hidden": hidden, "read_only": read_only, "needs_archive": False}
    all_locks = list(locks or [])
    if not read_only:
        all_locks.insert(0, f"task.{tid}")
    return {"id": tid, "title": title, "description": description, "group": group, "leagues": [], "bat": None,
            "flags": flags, "locks": all_locks, "time": time_label, "inputs": inputs or [],
            "stop_modes": stop_modes or (["after_cycle", "after_step", "kill"] if endless else ["after_step", "kill"]),
            "steps": steps}


def registry():
    ro = dict(data=False)
    tasks = [
        task("doctor", "Setup check", [step("doctor", "Setup check", "print", ["[ OK ] Mock setup check"], **ro)],
             group="setup", read_only=True, description="Checks Python, Node and the league files."),
        task("pull_report", "Data date report", [step("report", "Report", "print", ["Mock report"], **ro)],
             group="everyday", read_only=True),
        task("new_league", "New League", [step("check", "Check", "print", ["mock"])], group="leagues", hidden=True),
    ]
    if SELFTEST:
        tasks += [
            task("selftest.ok", "Self test ok", [step("ok", "Print lines", "ok")]),
            task("selftest.fail_collect", "Self test collect", [
                step("s1", "Step 1", "print", ["one"]), step("s2", "Step 2", "exit1"), step("s3", "Step 3", "print", ["three"])]),
            task("selftest.confirm", "Self test confirm", [
                step("preview", "Preview", "print", ["  3 cell(s) will change"]),
                step("apply", "Apply", "confirm_apply")]),
            task("selftest.long", "Self test long", [step(f"sleep{i}", f"Sleep {i}", "sleep", [20]) for i in range(1, 7)]),
            task("selftest.touch", "Self test touch", [step("touch", "Touch a data file", "touch", app=["TGS"])],
                 inputs=[{"name": "file", "type": "text", "label": "File", "help": "", "required": False,
                          "default": "TGS/r5.json", "ask_when": None, "console": None, "modes": ["console", "job"]}]),
            task("selftest.secret", "Self test secret", [step("secret", "Use the secret", "secret")],
                 inputs=[{"name": "token", "type": "secret", "label": "Token", "help": "", "required": True,
                          "default": None, "ask_when": None, "console": None, "modes": ["console", "job"]}]),
            task("selftest.leagues", "Self test leagues", [
                step("l1", "TGS 1", "sleep", [1], app=["TGS"]), step("l2", "TGS 2", "sleep", [1], app=["TGS"]),
                step("l3", "BLM", "sleep", [1], app=["BLM"]), step("l4", "None", "sleep", [1])]),
        ]
    for t in tasks:
        for s in t["steps"]:
            s["argv"] = ["python", "tgs-viz\\tools\\selftest_steps.py", s["action"]] + [str(a) for a in s["args"]]
    return tasks


def public_tasks(tasks):
    out = []
    for t in tasks:
        c = dict(t)
        c["steps"] = [{k: v for k, v in s.items() if k not in ("action", "args")} for s in t["steps"]]
        out.append(c)
    return out


def list_json():
    settings_error = None
    lp = local_settings_path()
    if lp.exists():
        try:
            json.loads(lp.read_text(encoding="utf-8-sig"))
        except Exception as e:
            settings_error = f"{lp.name} is not valid JSON: {e}"
    tasks = registry()
    if settings_error:
        tasks = [t for t in tasks if t["id"] == "doctor"]
    cat = {
        "schema": 1, "generated": now_iso(),
        "groups": [{"id": "setup", "title": "Setup and checks"}, {"id": "everyday", "title": "Everyday"},
                   {"id": "leagues", "title": "Your leagues"}, {"id": "selftest", "title": "Self tests"}],
        "tasks": public_tasks(tasks),
        "leagues": [] if settings_error else [{"id": "TGS", "name": "TGS", "type": "statsplus", "enabled": True,
                                               "pending": False, "added_by_wizard": False, "in_app": True,
                                               "update_task": "update.TGS", "token_line": "TGS="}],
        "state": {"tokens": {"TGS": True}, "ootp_installs": {}, "ratings_db_exists": True,
                  "settings_local": lp.exists(), "settings_error": settings_error,
                  "watch_files": [str(TGS_VIZ / "tools" / "settings.defaults.json"), str(lp)]},
        "app_config": {"leagues": {"TGS": {"name": "TGS", "my_org": "Chicago Cubs"}}},
    }
    print(json.dumps(cat))
    return 0


# ---------------------------------------------------------------- job mode

class Stop(Exception):
    pass


class Killed(Exception):
    pass


class Job:
    def __init__(self, job_dir):
        self.dir = Path(job_dir)
        self.id = self.dir.name
        self.seq = 0
        self.lock = threading.Lock()
        self.pid = os.getpid()
        self.pid_started = proc_start_time(self.pid)
        self.locks = []
        self.secrets = []
        self.stop_after = False
        self.state = {"schema": 1, "id": self.id, "task": None, "title": None, "mode": "job", "status": "starting",
                      "pid": self.pid, "pid_started": self.pid_started, "started": now_iso(), "ended": None,
                      "inputs": {}, "secrets_given": [], "steps": [], "current": None, "cycle": None, "fails": [],
                      "prompt": None, "stop": None, "locks_held": [], "data_lock": None, "waiting_for": None,
                      "pending_leagues": [], "message": None, "fix_task": None, "summary": [], "exit_code": None}

    def save(self):
        write_json(self.dir / "state.json", self.state)

    def event(self, etype, **data):
        with self.lock:
            self.seq += 1
            line = json.dumps({"seq": self.seq, "at": now_iso(), "type": etype, **data})
            with open(self.dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def mask(self, text):
        for s in self.secrets:
            text = text.replace(s, "****")
        return text

    def log(self, text, end="\n"):
        with open(self.dir / "log.txt", "ab") as f:
            f.write(self.mask(text + end).encode("utf-8"))
            f.flush()

    def check_stop(self):
        stop = read_json(self.dir / "stop.json")
        if not stop:
            return
        mode = stop.get("mode")
        self.state["stop"] = {"mode": mode, "requested_at": stop.get("requested_at")}
        if mode == "kill":
            raise Killed()
        self.stop_after = True

    def sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.check_stop()
            time.sleep(0.2)

    def take_lock(self, name):
        LOCKS.mkdir(parents=True, exist_ok=True)
        target = LOCKS / f"{name}.json"
        rec = {"schema": 1, "name": name, "job_id": self.id, "task": self.state["task"], "title": self.state["title"],
               "mode": "job", "pid": self.pid, "pid_started": self.pid_started, "since": now_iso()}
        for _ in range(2):
            tmp = LOCKS / f"{name}.json.{self.pid}.tmp"
            tmp.write_text(json.dumps(rec), encoding="utf-8")
            try:
                os.rename(tmp, target)
                self.locks.append(name)
                self.state["locks_held"] = list(self.locks)
                self.event("lock", name=name, action="taken")
                return None
            except FileExistsError:
                tmp.unlink(missing_ok=True)
                holder = read_json(target)
                if holder and alive(holder):
                    return holder
                target.unlink(missing_ok=True)
        return read_json(target) or {}

    def release_locks(self):
        for name in list(self.locks):
            target = LOCKS / f"{name}.json"
            holder = read_json(target)
            if holder and holder.get("job_id") == self.id:
                target.unlink(missing_ok=True)
                self.event("lock", name=name, action="released")
        self.locks = []
        self.state["locks_held"] = []

    def prompt(self, kind, text, choices, step_id):
        pid = f"p{self.seq + 1}"
        p = {"prompt_id": pid, "kind": kind, "step_id": step_id, "title": text, "text": text, "details": [],
             "choices": choices, "default": choices[-1]["id"], "created": now_iso()}
        write_json(self.dir / "prompt.json", p)
        self.event("prompt", prompt_id=pid, kind=kind, text=text, details=[], choices=choices)
        self.state["status"] = "waiting"
        self.state["prompt"] = p
        self.save()
        while True:
            ans = read_json(self.dir / "answer.json")
            if ans and ans.get("prompt_id") == pid and ans.get("value") in [c["id"] for c in choices]:
                break
            stop = read_json(self.dir / "stop.json")
            if stop:
                ans = {"value": choices[-1]["id"]}
                self.stop_after = True
                break
            time.sleep(0.3)
        (self.dir / "answer.json").unlink(missing_ok=True)
        (self.dir / "prompt.json").unlink(missing_ok=True)
        self.event("answer", prompt_id=pid, value=ans["value"])
        self.state["status"] = "running"
        self.state["prompt"] = None
        self.save()
        return ans["value"]

    def heartbeat(self):
        hb = self.dir / "heartbeat"
        while True:
            try:
                hb.touch()
            except OSError:
                pass
            time.sleep(5)


def touch_file(rel):
    target = PUBLIC_DATA / rel
    data = target.read_bytes()
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)


def run_action(job, s, inputs, secrets):
    a = s["action"]
    if a == "print":
        for line in s["args"]:
            job.log(str(line))
    elif a == "ok":
        for i in range(1, 6):
            job.log(f"line {i}: café ✓")
        job.log("partial line ...", end="")
        job.sleep(1)
        job.log(" done")
    elif a == "exit1":
        job.log("step exits 1")
        return 1
    elif a == "sleep":
        job.sleep(float(s["args"][0]))
    elif a == "confirm_apply":
        v = job.prompt("confirm", "Apply these changes?", [{"id": "yes", "label": "Apply"}, {"id": "no", "label": "Skip"}], s["id"])
        job.log("applied" if v == "yes" else "Skipped (not applied).")
    elif a == "touch":
        rel = inputs.get("file") or "TGS/r5.json"
        touch_file(rel)
        job.log(f"rewrote {rel}")
    elif a == "secret":
        val = secrets.get("token", "")
        job.log(f"secret received: {'yes' if val else 'no'}, length {len(val)}")
        job.log(val)
    return 0


def run_job(job_dir):
    job = Job(job_dir)
    ACTIVE.mkdir(parents=True, exist_ok=True)
    job.save()
    entry = {"schema": 1, "job_id": job.id, "task": None, "title": None, "mode": "job", "pid": job.pid,
             "pid_started": job.pid_started, "started": now_iso()}
    write_json(ACTIVE / f"{job.id}.json", entry)
    threading.Thread(target=job.heartbeat, daemon=True).start()
    try:
        req = read_json(job.dir / "request.json") or {}
        tasks = {t["id"]: t for t in registry()}
        t = tasks.get(req.get("task"))
        job.state["task"] = req.get("task")
        job.state["inputs"] = req.get("inputs") or {}
        if not t:
            job.state.update(status="invalid", message=f"There is no task named {req.get('task')}.", ended=now_iso(), exit_code=2)
            job.save()
            job.event("job_end", status="invalid", exit_code=2, fails=[], summary=[])
            return 2
        job.state["title"] = t["title"]
        entry.update(task=t["id"], title=t["title"])
        write_json(ACTIVE / f"{job.id}.json", entry)
        declared = {i["name"].lower(): i["name"] for i in t["inputs"] if i["type"] == "secret"}
        secrets = {}
        for k in list(os.environ):
            if k.upper().startswith("TGS_SECRET_"):
                name = declared.get(k[len("TGS_SECRET_"):].lower())
                val = os.environ.pop(k)
                if name:
                    secrets[name] = val
        job.secrets = [v for v in secrets.values() if v]
        job.state["secrets_given"] = sorted(secrets)
        inputs = {i["name"]: i.get("default") for i in t["inputs"] if i["type"] != "secret"}
        inputs.update(req.get("inputs") or {})
        job.state["steps"] = [{"index": i, "id": s["id"], "title": s["title"], "status": "pending", "exit": None,
                               "started": None, "ended": None, "tag": None, "writes_app_data": s["writes_app_data"]}
                              for i, s in enumerate(t["steps"])]
        job.event("job_start", task=t["id"], mode="job", steps_total=len(t["steps"]))
        if not t["flags"]["read_only"]:
            for name in t["locks"]:
                holder = job.take_lock(name)
                if holder is not None:
                    job.release_locks()
                    job.state.update(status="refused", ended=now_iso(), exit_code=3,
                                     message=f"{holder.get('title') or 'Another task'} is running ({name}).")
                    job.save()
                    job.event("job_end", status="refused", exit_code=3, fails=[], summary=[])
                    return 3
        steps = t["steps"]

        def pending_after(i):
            out = []
            for s in steps[i:]:
                for lg in s["app_leagues"]:
                    if lg not in out:
                        out.append(lg)
            return out

        job.state["pending_leagues"] = pending_after(0)
        status = "done"
        fails = []
        for i, s in enumerate(steps):
            if job.stop_after:
                status = "stopped"
                break
            if s["data"] and not t["flags"]["read_only"] and "data" not in job.locks:
                first = True
                while True:
                    holder = job.take_lock("data")
                    if holder is None:
                        job.state["data_lock"] = "held"
                        job.state["waiting_for"] = None
                        break
                    if first:
                        job.state.update(status="queued" if i == 0 else "running", data_lock="waiting",
                                         waiting_for={"job_id": holder.get("job_id"), "title": holder.get("title"), "lock": "data"})
                        job.save()
                        job.event("lock", name="data", action="waiting")
                        first = False
                    time.sleep(0.5)
                    job.check_stop()
                    if job.stop_after:
                        raise Stop()
            job.state["status"] = "running"
            job.state["current"] = i
            st = job.state["steps"][i]
            st.update(status="running", started=now_iso())
            job.save()
            job.event("step_start", index=i, step_id=s["id"], title=s["title"], argv=s["argv"])
            t0 = time.time()
            try:
                code = run_action(job, s, inputs, secrets)
            except Killed:
                st.update(status="killed", ended=now_iso())
                for rest in job.state["steps"][i + 1:]:
                    rest["status"] = "skipped"
                raise
            st.update(status="ok" if code == 0 else "failed", exit=code, ended=now_iso())
            if code != 0:
                fails.append(s["id"])
                status = "partial"
            before = job.state["pending_leagues"]
            after = pending_after(i + 1)
            job.state["pending_leagues"] = after
            job.state["fails"] = fails
            job.save()
            job.event("step_end", index=i, step_id=s["id"], status=st["status"], exit=code,
                      seconds=round(time.time() - t0, 2), tag=None, writes_app_data=s["writes_app_data"])
            for lg in before:
                if lg not in after:
                    job.event("league_done", league=lg)
        if status == "stopped":
            for rest in job.state["steps"]:
                if rest["status"] == "pending":
                    rest["status"] = "skipped"
        code = 0
        job.state.update(status=status, ended=now_iso(), exit_code=code, pending_leagues=[], current=None)
        job.release_locks()
        job.save()
        job.event("job_end", status=status, exit_code=code, fails=fails, summary=[])
        return code
    except Stop:
        job.release_locks()
        job.state.update(status="stopped", ended=now_iso(), exit_code=0, pending_leagues=[], waiting_for=None)
        job.save()
        job.event("job_end", status="stopped", exit_code=0, fails=[], summary=[])
        return 0
    except Killed:
        job.release_locks()
        job.state.update(status="killed", ended=now_iso(), exit_code=4, pending_leagues=[])
        job.save()
        job.event("job_end", status="killed", exit_code=4, fails=[], summary=[])
        return 4
    except Exception as e:
        job.release_locks()
        job.state.update(status="failed", ended=now_iso(), exit_code=1, message=str(e).splitlines()[-1] if str(e) else repr(e))
        job.save()
        job.event("job_end", status="failed", exit_code=1, fails=[], summary=[])
        raise
    finally:
        (ACTIVE / f"{job.id}.json").unlink(missing_ok=True)


# ---------------------------------------------------------------- other commands

def launch(job_dir):
    log = open(Path(job_dir) / "runner.log", "ab")
    flags = 0x00000008 | 0x00000200 | 0x01000000  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    argv = [sys.executable, str(Path(__file__).resolve()), "--job", str(job_dir)]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True, creationflags=flags)
    except OSError:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                         creationflags=flags & ~0x01000000)
    return 0


def release_job_locks(job_id):
    if not LOCKS.exists():
        return
    for f in LOCKS.glob("*.json"):
        rec = read_json(f)
        if rec and rec.get("job_id") == job_id:
            f.unlink(missing_ok=True)


def reap():
    out = []
    if ACTIVE.exists():
        for f in ACTIVE.glob("*.json"):
            entry = read_json(f)
            if not entry or alive(entry):
                continue
            jid = entry.get("job_id") or f.stem
            sp = JOBS / jid / "state.json"
            state = read_json(sp)
            if not state or state.get("status") == "starting":
                status = "failed"
                state = state or {"schema": 1, "id": jid}
                state.update(status=status, message="The runner stopped before it started the task.", ended=now_iso())
            elif state.get("status") not in FINAL:
                status = "lost"
                state.update(status=status, ended=now_iso())
            else:
                status = state.get("status")
            write_json(sp, state)
            release_job_locks(jid)
            f.unlink(missing_ok=True)
            out.append({"job_id": jid, "status": status})
    print(json.dumps({"reaped": out}))
    return 0


def lock_status():
    locks = {}
    if LOCKS.exists():
        for f in LOCKS.glob("*.json"):
            rec = read_json(f) or {}
            locks[f.stem] = {**rec, "alive": alive(rec)}
    active = []
    if ACTIVE.exists():
        for f in ACTIVE.glob("*.json"):
            rec = read_json(f) or {}
            st = read_json(JOBS / f.stem / "state.json") or {}
            active.append({**rec, "alive": alive(rec), "status": st.get("status")})
    print(json.dumps({"locks": locks, "active": active}))
    return 0


def kill(job_id):
    entry = read_json(ACTIVE / f"{job_id}.json")
    if entry and alive(entry):
        subprocess.call(["taskkill", "/PID", str(entry["pid"]), "/T", "/F"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, creationflags=0x08000000)
    sp = JOBS / job_id / "state.json"
    state = read_json(sp) or {"schema": 1, "id": job_id}
    if state.get("status") not in FINAL:
        state.update(status="killed", ended=now_iso())
        write_json(sp, state)
    release_job_locks(job_id)
    (ACTIVE / f"{job_id}.json").unlink(missing_ok=True)
    print(json.dumps({"ok": True, "status": state.get("status")}))
    return 0


def main(argv):
    if "--list-json" in argv:
        return list_json()
    if argv[:1] == ["--launch"]:
        return launch(argv[1])
    if argv[:1] == ["--job"]:
        return run_job(argv[1])
    if argv[:1] == ["--reap"]:
        return reap()
    if argv[:1] == ["--lock-status"]:
        return lock_status()
    if argv[:1] == ["--kill"]:
        return kill(argv[1])
    print("mock run_task: unsupported arguments", argv, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
