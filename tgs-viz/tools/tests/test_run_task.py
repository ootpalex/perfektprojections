"""Runner tests (DESIGN.md 15.1 step 2).

  set TGS_CONTROL_DIR=<temp dir>
  set TGS_SELFTEST=1
  python -m unittest discover -s tgs-viz\\tools\\tests -p "test_run_task.py"

Every test uses its own control folder under TGS_CONTROL_DIR (or a temp dir)
and runs only the harmless selftest.* tasks.
"""
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(TOOLS))
sys.path.insert(0, TOOLS)

import conditions as C  # noqa: E402
import joblock as JL  # noqa: E402

PY = sys.executable
RUN = os.path.join(TOOLS, "run_task.py")
BASE = os.environ.get("TGS_CONTROL_DIR") or tempfile.mkdtemp(prefix="tgs-control-test-")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    return read_bytes(path).decode("utf-8", "replace").replace("\r\n", "\n")


def child_pids(pid):
    """Pids of the running children of pid (Toolhelp snapshot; ps off Windows)."""
    if os.name != "nt":
        out = subprocess.run(["ps", "-A", "-o", "pid=", "-o", "ppid="], capture_output=True, text=True).stdout
        kids = [int(a) for a, b in (ln.split() for ln in out.splitlines() if len(ln.split()) == 2) if int(b) == pid]
        return [p for p in kids if JL.proc_start_time(p) is not None]
    class PE(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k.CreateToolhelp32Snapshot(0x2, 0)
    out = []
    e = PE()
    e.dwSize = ctypes.sizeof(PE)
    try:
        ok = k.Process32First(snap, ctypes.byref(e))
        while ok:
            if e.th32ParentProcessID == pid:
                out.append(e.th32ProcessID)
            ok = k.Process32Next(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return [p for p in out if JL.proc_start_time(p) is not None]


class Case(unittest.TestCase):
    def setUp(self):
        self.ctl = os.path.join(BASE, self.id().rsplit(".", 1)[-1] + "-" + os.urandom(2).hex())
        os.makedirs(self.ctl, exist_ok=True)
        self.env = dict(os.environ)
        self.env.update(TGS_CONTROL_DIR=self.ctl, TGS_SELFTEST="1", RATINGS_DB_ALLOW_NEW="1",
                        PYTHONIOENCODING="utf-8")
        self.env.pop("TGS_DRY_RUN", None)
        self.env.pop("TGS_RUN_TASK_TEST_CRASH", None)
        self.procs = []
        self._old_ctl = os.environ.get("TGS_CONTROL_DIR")
        os.environ["TGS_CONTROL_DIR"] = self.ctl

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                else:
                    JL.posix_kill_tree(p.pid)
            for stream in (p.stdin, p.stdout):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
        if self._old_ctl is None:
            os.environ.pop("TGS_CONTROL_DIR", None)
        else:
            os.environ["TGS_CONTROL_DIR"] = self._old_ctl
        # every finished job of this test: events start with job_start, end with job_end, seq has no gaps
        jobs = os.path.join(self.ctl, "jobs")
        for jid in (os.listdir(jobs) if os.path.isdir(jobs) else []):
            jd = os.path.join(jobs, jid)
            st = self.state(jd)
            if st.get("status") not in JL.FINAL or st.get("mode") is None:
                continue
            ev = self.events(jd)
            self.assertTrue(ev, jid)
            self.assertEqual([e["seq"] for e in ev], list(range(1, len(ev) + 1)), jid)
            self.assertEqual((ev[0]["type"], ev[-1]["type"]), ("job_start", "job_end"), jid)
            self.assertEqual(ev[-1]["status"], st["status"], jid)

    # -- helpers
    def job(self, task, inputs=None, secrets=None, env=None, wait=False, launch=False):
        jid = JL.new_job_id(task)
        jd = os.path.join(self.ctl, "jobs", jid)
        os.makedirs(jd)
        JL.write_json_atomic(os.path.join(jd, "request.json"),
                             {"schema": 1, "task": task, "inputs": inputs or {},
                              "secret_names": [k.upper() for k in (secrets or {})], "mode": "job",
                              "requested_at": JL.now_iso(), "by": "control-page"})
        e = dict(self.env)
        for k, v in (secrets or {}).items():
            e["TGS_SECRET_" + k] = v
        e.update(env or {})
        argv = [PY, RUN, "--launch" if launch else "--job", jd]
        p = subprocess.Popen(argv, cwd=REPO, env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        self.procs.append(p)
        if wait:
            p.wait(120)
        return p, jd, jid

    def state(self, jd):
        return JL.read_json(os.path.join(jd, "state.json")) or {}

    def events(self, jd):
        out = []
        try:
            with open(os.path.join(jd, "events.jsonl"), encoding="utf-8") as f:
                for ln in f:
                    if ln.strip():
                        out.append(json.loads(ln))
        except OSError:
            pass
        return out

    def wait_for(self, fn, timeout=60, step=0.1, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(step)
        self.fail(f"timed out waiting for {what}")

    def wait_status(self, jd, statuses, timeout=60):
        statuses = (statuses,) if isinstance(statuses, str) else statuses
        return self.wait_for(lambda: self.state(jd) if self.state(jd).get("status") in statuses else None,
                             timeout, what=f"status {statuses} in {os.path.basename(jd)}")

    def wait_step_running(self, jd, index, timeout=60):
        def ok():
            s = self.state(jd)
            st = s.get("steps") or []
            return s if len(st) > index and st[index].get("status") == "running" else None
        return self.wait_for(ok, timeout, what=f"step {index} running")

    def wait_prompt(self, jd, timeout=60):
        return self.wait_for(lambda: JL.read_json(os.path.join(jd, "prompt.json")), timeout, what="prompt")

    def answer(self, jd, pid, value):
        JL.write_json_atomic(os.path.join(jd, "answer.json"), {"prompt_id": pid, "value": value})

    def stop(self, jd, mode):
        JL.write_json_atomic(os.path.join(jd, "stop.json"), {"mode": mode, "requested_at": JL.now_iso()})

    def check_events(self, jd):
        ev = self.events(jd)
        self.assertEqual([e["seq"] for e in ev], list(range(1, len(ev) + 1)), "event seq has gaps")
        self.assertEqual(ev[0]["type"], "job_start")
        self.assertEqual(ev[-1]["type"], "job_end")
        return ev

    def assert_clean(self, jid):
        self.assertFalse(os.path.exists(os.path.join(self.ctl, "active", jid + ".json")), "active entry left")
        for name, rec in JL.list_locks().items():
            self.assertNotEqual(rec.get("job_id"), jid, f"lock {name} left")

    def console(self, task, stdin_text="", env=None, args=(), group=False):
        e = dict(self.env)
        e.update(env or {})
        p = subprocess.Popen([PY, RUN, task, *args], cwd=REPO, env=e, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT,
                             start_new_session=group and os.name != "nt",
                             creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if group and os.name == "nt" else 0)
        self.procs.append(p)
        if stdin_text is not None:
            p.stdin.write(stdin_text.encode())
            p.stdin.flush()
        return p


class TestLocks(Case):
    def test_race_one_winner_each_round(self):
        rounds = 50
        work = os.path.join(self.ctl, "race")
        os.makedirs(work)
        worker = (
            "import os, sys, time, json\n"
            f"sys.path.insert(0, {TOOLS!r})\n"
            "import joblock as JL\n"
            "work, me = sys.argv[1], sys.argv[2]\n"
            "h = dict(JL.me(), job_id=f'20261001-000000-race{me}-abcd', task='race', title='race', mode='job')\n"
            f"for r in range({rounds}):\n"
            "    go = os.path.join(work, f'go{r}')\n"
            "    while not os.path.exists(go): time.sleep(0.001)\n"
            "    ok, cur = JL.take_lock('race', h)\n"
            "    open(os.path.join(work, f'res{r}-{me}'), 'w').write('1' if ok else '0')\n"
            "# stay alive: a holder that has exited is gone, and its lock may be taken\n"
            "while not os.path.exists(os.path.join(work, 'done')): time.sleep(0.01)\n"
        )
        procs = [subprocess.Popen([PY, "-c", worker, work, str(i)], env=self.env) for i in (1, 2)]
        bad_reads = []
        stop_reader = threading.Event()

        def reader():
            p = JL.lock_path("race")
            while not stop_reader.is_set():
                try:
                    with open(p, "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                try:
                    rec = json.loads(data.decode("utf-8"))
                    if not rec.get("job_id") or not rec.get("pid"):
                        bad_reads.append(data)
                except ValueError:
                    bad_reads.append(data)

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        try:
            for r in range(rounds):
                open(os.path.join(work, f"go{r}"), "w").close()
                res = []
                for i in (1, 2):
                    f = os.path.join(work, f"res{r}-{i}")
                    self.wait_for(lambda: os.path.exists(f) and os.path.getsize(f) > 0, 20, 0.002, "race result")
                    res.append(read_text(f))
                self.assertEqual(sorted(res), ["0", "1"], f"round {r}: {res}")
                JL.remove_file(JL.lock_path("race"))
        finally:
            open(os.path.join(work, "done"), "w").close()
            stop_reader.set()
            th.join(2)
            for p in procs:
                p.wait(20)
        self.assertEqual(bad_reads, [], "a reader saw an empty or partial lock file")

    def test_reused_pid_reads_as_gone_and_is_reaped(self):
        real_kill = os.kill

        def no_kill(*a, **k):
            raise AssertionError("os.kill must never be called")

        os.kill = no_kill
        try:
            me = JL.me()
            stale = {"schema": 1, "name": "data", "job_id": "20261001-000000-old-0000", "task": "old", "title": "Old",
                     "mode": "job", "pid": me["pid"], "pid_started": me["pid_started"] + 12345, "since": JL.now_iso()}
            os.makedirs(os.path.join(self.ctl, "locks"), exist_ok=True)
            JL.write_json_atomic(JL.lock_path("data"), stale)
            self.assertFalse(JL.alive(stale))
            self.assertTrue(JL.alive(dict(stale, pid_started=me["pid_started"])))
            ls = JL.lock_status()
            self.assertFalse(ls["locks"]["data"]["alive"])
            holder = dict(me, job_id="20261001-000000-new-1111", task="new", title="New", mode="job")
            ok, cur = JL.take_lock("data", holder)
            self.assertTrue(ok)
            self.assertEqual(JL.read_lock("data")["job_id"], holder["job_id"])
        finally:
            os.kill = real_kill


class TestStale(Case):
    def dead_proc(self):
        p = subprocess.Popen([PY, "-c", "import time; time.sleep(0.5)"])
        started = JL.proc_start_time(p.pid)
        p.wait()
        return p.pid, started

    def test_reap_lost_and_failed(self):
        pid, started = self.dead_proc()
        a = "20261001-120000-selftest.long-aaaa"
        b = "20261001-120001-selftest.ok-bbbb"
        for jid in (a, b):
            os.makedirs(os.path.join(self.ctl, "jobs", jid))
            JL.write_active({"schema": 1, "job_id": jid, "task": jid.split("-")[2][:-5], "title": "T", "mode": "job",
                             "pid": pid, "pid_started": started, "started": JL.now_iso()})
        JL.write_json_atomic(os.path.join(self.ctl, "jobs", a, "state.json"),
                             {"schema": 1, "id": a, "status": "running", "steps": [{"status": "running"}],
                              "current": 0})
        with open(os.path.join(self.ctl, "jobs", b, "runner.log"), "w") as f:
            f.write("Traceback (most recent call last):\nboom line 1\nboom line 2\n")
        holder = {"job_id": a, "task": "selftest.long", "title": "T", "mode": "job", "pid": pid, "pid_started": started}
        JL.write_json_atomic(JL.lock_path("task.selftest.long"), dict(holder, schema=1, name="task.selftest.long"))
        out = json.loads(subprocess.run([PY, RUN, "--lock-status"], env=self.env, capture_output=True, text=True).stdout)
        self.assertIn("task.selftest.long", out["locks"])
        self.assertFalse(out["locks"]["task.selftest.long"]["alive"])
        self.assertEqual(sorted(e["job_id"] for e in out["active"]), [a, b])
        self.assertTrue(all(e["alive"] is False for e in out["active"]))
        out = json.loads(subprocess.run([PY, RUN, "--reap"], env=self.env, capture_output=True, text=True).stdout)
        got = {r["job_id"]: r["status"] for r in out["reaped"]}
        self.assertEqual(got, {a: "lost", b: "failed"})
        sa, sb = self.state(os.path.join(self.ctl, "jobs", a)), self.state(os.path.join(self.ctl, "jobs", b))
        self.assertEqual(sa["status"], "lost")
        self.assertEqual(sb["status"], "failed")
        self.assertEqual(sb["message"], "The runner stopped before it started the task.")
        self.assertIn("boom line 2", sb["summary"])
        self.assertEqual(JL.list_active(), [])
        self.assertEqual(JL.list_locks(), {})

    def test_unreadable_lock_and_active_files(self):
        pid, started = self.dead_proc()
        old = time.time() - 60
        os.makedirs(os.path.join(self.ctl, "locks"), exist_ok=True)
        os.makedirs(os.path.join(self.ctl, "active"), exist_ok=True)
        # a zero-byte data lock: a fresh one is left alone, an old one is dropped at the next take
        lock = JL.lock_path("data")
        open(lock, "wb").close()
        me = dict(JL.me(), job_id="20261001-120002-selftest.ok-cccc", task="selftest.ok", title="T", mode="job")
        self.assertFalse(JL.unreadable(lock))
        os.utime(lock, (old, old))
        self.assertEqual(JL.unreadable_files(), [("locks", "data")])
        ok, _cur = JL.take_lock("data", me)
        self.assertTrue(ok)
        JL.release_lock("data", me["job_id"])
        # a zero-byte active entry of a dead runner: --reap ends the job by its file name
        jid = "20261001-120003-selftest.long-dddd"
        os.makedirs(os.path.join(self.ctl, "jobs", jid))
        JL.write_json_atomic(os.path.join(self.ctl, "jobs", jid, "state.json"),
                             {"schema": 1, "id": jid, "status": "running", "pid": pid, "pid_started": started,
                              "steps": [{"status": "running"}], "current": 0})
        open(JL.active_path(jid), "wb").close()
        open(lock, "wb").close()
        for p in (JL.active_path(jid), lock):
            os.utime(p, (old, old))
        out = json.loads(subprocess.run([PY, RUN, "--reap"], env=self.env, capture_output=True, text=True).stdout)
        got = {(r["job_id"], r["status"]) for r in out["reaped"]}
        self.assertEqual(got, {(jid, "lost"), (None, "unreadable")})
        self.assertFalse(os.path.exists(JL.active_path(jid)))
        self.assertFalse(os.path.exists(lock))
        # --kill falls back to the file name too
        jid2 = "20261001-120004-selftest.long-eeee"
        os.makedirs(os.path.join(self.ctl, "jobs", jid2))
        JL.write_json_atomic(os.path.join(self.ctl, "jobs", jid2, "state.json"),
                             {"schema": 1, "id": jid2, "status": "running", "pid": pid, "pid_started": started})
        open(JL.active_path(jid2), "wb").close()
        out = json.loads(subprocess.run([PY, RUN, "--kill", jid2], env=self.env, capture_output=True, text=True).stdout)
        self.assertEqual(out, {"ok": True, "status": "lost"})
        self.assertFalse(os.path.exists(JL.active_path(jid2)))

    def test_prune_keeps_unfinished_new_league(self):
        local = os.path.join(self.ctl, "settings.local.json")
        with open(local, "w", encoding="utf-8") as f:
            json.dump({"leagues": {"ZQ": {"type": "dev", "name": "Zq", "pending": True}}}, f)
        old = time.time() - 3600
        keep, gone = "20260901-100000-new_league-aaaa", "20260901-100001-new_league-bbbb"
        jobs = [(keep, "new_league", "lost", "ZQ"), (gone, "new_league", "lost", "ZR")]
        jobs += [(f"20260902-1000{i:02d}-selftest.ok-{i:04x}", "selftest.ok", "done", None) for i in range(JL.KEEP_JOBS)]
        for jid, task, status, lid in jobs:
            jd = JL.job_dir(jid)
            os.makedirs(jd)
            JL.write_json_atomic(os.path.join(jd, "state.json"), {"task": task, "status": status, "steps": []})
            if lid:
                JL.write_json_atomic(os.path.join(jd, "new_league_spec.json"), {"type": "dev", "id": lid})
            os.utime(jd, (old, old))
        was = os.environ.get("TGS_SETTINGS_LOCAL")
        os.environ["TGS_SETTINGS_LOCAL"] = local
        try:
            self.assertEqual(JL.prune_jobs(), [gone])
        finally:
            if was is None:
                os.environ.pop("TGS_SETTINGS_LOCAL", None)
            else:
                os.environ["TGS_SETTINGS_LOCAL"] = was
        self.assertTrue(os.path.isdir(JL.job_dir(keep)))

    def test_lock_names_stay_in_the_locks_folder(self):
        for bad in ("dumps.x\\..\\..\\ESCAPED", "../x", "a/b", "dumps..x", ""):
            with self.assertRaises(ValueError, msg=bad):
                JL.lock_path(bad)
        self.assertTrue(JL.lock_path("dumps.DEV").endswith(os.path.join("locks", "dumps.DEV.json")))
        r = subprocess.run([PY, RUN, "new_league", "--input", "type=dev", "--input", "id=x\\..\\..\\..\\ESCAPED",
                            "--input", "name=t"], env=self.env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.ctl), "ESCAPED.json")))
        self.assertFalse(os.listdir(os.path.join(self.ctl, "locks")) if os.path.isdir(os.path.join(self.ctl, "locks")) else [])

    def test_early_death_is_never_stuck_starting(self):
        p, jd, jid = self.job("selftest.ok", env={"TGS_RUN_TASK_TEST_CRASH": "1"}, wait=True)
        st = self.state(jd)
        self.assertEqual(st["status"], "failed")
        self.assertIn("Test crash", st["message"])
        self.assert_clean(jid)


class TestJobs(Case):
    def run_job(self, task, **kw):
        p, jd, jid = self.job(task, wait=True, **kw)
        st = self.state(jd)
        ev = self.check_events(jd)
        self.assert_clean(jid)
        return st, ev, jd

    def test_ok(self):
        st, ev, jd = self.run_job("selftest.ok")
        self.assertEqual(st["status"], "done")
        log = read_text(os.path.join(jd, "log.txt"))
        self.assertIn("café", log)
        self.assertIn("✓", log)
        self.assertIn("partial line ... done", log)
        types = [e["type"] for e in ev]
        self.assertLess(types.index("step_start"), types.index("step_end"))

    def test_fail_collect(self):
        st, ev, _ = self.run_job("selftest.fail_collect")
        self.assertEqual(st["status"], "partial")
        self.assertEqual(st["fails"], ["T2"])
        self.assertEqual([s["status"] for s in st["steps"]], ["ok", "failed", "ok"])

    def test_fail_fast(self):
        st, ev, _ = self.run_job("selftest.fail_fast")
        self.assertEqual(st["status"], "failed")
        self.assertEqual([s["status"] for s in st["steps"]], ["ok", "failed", "skipped"])

    def test_confirm_zero_asks_nothing(self):
        st, ev, _ = self.run_job("selftest.confirm_zero")
        self.assertEqual(st["status"], "done")
        self.assertNotIn("prompt", [e["type"] for e in ev])

    def test_stdin_eof(self):
        st, ev, jd = self.run_job("selftest.stdin")
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["steps"][0]["exit"], 0)
        self.assertIn("skipped (no answer)", read_text(os.path.join(jd, "log.txt")))

    def test_touch_and_corrupt_restore_bytes(self):
        for task, rel in (("selftest.touch", "TGS/r5.json"), ("selftest.corrupt", "RG/iafa.json")):
            path = os.path.join(REPO, "tgs-viz", "public", "data", *rel.split("/"))
            before = read_bytes(path)
            st, ev, _ = self.run_job(task)
            self.assertEqual(st["status"], "done", task)
            self.assertEqual(read_bytes(path), before, task)

    def test_archive_check(self):
        root = os.path.join(self.ctl, "archive")
        os.makedirs(os.path.join(root, "vintages", "X"))
        open(os.path.join(root, "vintages", "X", "_pulls.csv"), "w").close()
        env = {"RATINGS_ARCHIVE_ROOT": root, "RATINGS_DB_ALLOW_NEW": ""}
        st, ev, _ = self.run_job("selftest.archive", env=env)
        self.assertEqual(st["status"], "invalid")
        self.assertEqual(st["fix_task"], "restore_ratings_db")
        self.assertIn("ratings archive is missing", st["message"])
        st, ev, _ = self.run_job("selftest.archive", env={"RATINGS_ARCHIVE_ROOT": root, "RATINGS_DB_ALLOW_NEW": "1"})
        self.assertEqual(st["status"], "done")
        self.assertFalse(os.path.exists(os.path.join(root, "ratings_history.db")))

    def test_launch_detaches(self):
        p, jd, jid = self.job("selftest.ok", launch=True)
        self.assertEqual(p.wait(30), 0)
        st = self.wait_status(jd, ("done",), 60)
        self.assertNotEqual(st["pid"], p.pid)
        self.check_events(jd)
        self.assertTrue(os.path.exists(os.path.join(jd, "runner.log")))

    def test_secrets_are_masked(self):
        secret = "s3cr3t-VALUE-0123456789"
        p, jd, jid = self.job("selftest.secret", secrets={"token": secret, "OTHER": "other-secret-value-xyz"}, wait=True)
        st = self.state(jd)
        self.assertEqual(st["status"], "done")
        for name in os.listdir(jd):
            data = read_bytes(os.path.join(jd, name))
            self.assertNotIn(secret.encode(), data, name)
            self.assertNotIn(b"other-secret-value-xyz", data, name)
        log = read_text(os.path.join(jd, "log.txt"))
        self.assertIn(f"secret received: yes, length {len(secret)}", log)
        self.assertIn("whole: ****", log)
        self.assertIn("split: ****", log)
        warn = [e for e in self.events(jd) if e["type"] == "message" and e.get("level") == "warn"]
        self.assertTrue(any("OTHER" in e["text"] for e in warn))
        self.assertEqual(st["secrets_given"], ["token"])

    def test_bad_secret_is_invalid(self):
        st, ev, _ = self.run_job("selftest.secret", secrets={"token": "short"})
        self.assertEqual(st["status"], "invalid")

    def test_leagues_claims(self):
        p, jd, jid = self.job("selftest.leagues")
        seen = []
        while p.poll() is None:
            s = self.state(jd)
            if s.get("status") == "running" and s.get("current") is not None:
                seen.append((s["current"], tuple(s.get("pending_leagues") or [])))
            time.sleep(0.05)
        want = {0: ("TGS", "BLM"), 1: ("TGS", "BLM"), 2: ("BLM",), 3: ()}
        self.assertTrue(seen)
        for cur, pend in seen:
            # a sample can land between a step end and the next step start
            self.assertIn(pend, (want[cur], want.get(cur + 1, ())), (cur, pend))
        ev = self.check_events(jd)
        order = [(e["type"], e.get("step_id") or e.get("league")) for e in ev if e["type"] in ("step_end", "league_done")]
        self.assertEqual(order, [("step_end", "s1"), ("step_end", "s2"), ("league_done", "TGS"),
                                 ("step_end", "s3"), ("league_done", "BLM"), ("step_end", "s4")])


class TestPrompts(Case):
    def test_confirm_yes_and_no(self):
        for value, applied in (("yes", True), ("no", False)):
            p, jd, jid = self.job("selftest.confirm")
            pr = self.wait_prompt(jd)
            self.assertEqual(pr["kind"], "confirm")
            self.assertTrue(any("3 cell(s) will change" in d for d in pr["details"]))
            # the runner writes prompt.json, then state "waiting": wait out that gap
            self.wait_for(lambda: self.state(jd).get("status") == "waiting", 10, what="state waiting")
            self.answer(jd, pr["prompt_id"], value)
            p.wait(60)
            st = self.state(jd)
            self.assertEqual(st["status"], "done")
            log = read_text(os.path.join(jd, "log.txt"))
            self.assertEqual("applied" in log.splitlines(), applied)
            self.assertFalse(os.path.exists(os.path.join(jd, "prompt.json")))
            self.check_events(jd)

    def test_gate_continue_and_stop(self):
        for value, status in (("continue", "done"), ("stop", "stopped")):
            p, jd, jid = self.job("selftest.gate")
            pr = self.wait_prompt(jd)
            self.assertEqual(pr["kind"], "gate")
            self.answer(jd, pr["prompt_id"], value)
            p.wait(60)
            st = self.state(jd)
            self.assertEqual(st["status"], status)
            if value == "stop":
                self.assertEqual(st["steps"][-1]["status"], "skipped")
            self.assert_clean(jid)

    def test_excel_gate(self):
        jid = JL.new_job_id("selftest.excel")
        xl = os.path.join(self.ctl, "xl-" + jid)
        os.makedirs(xl)
        lockf = os.path.join(xl, "~$a.xlsx")
        open(lockf, "w").close()
        p, jd, jid = self.job("selftest.excel", inputs={"folder": xl})
        pr = self.wait_prompt(jd)
        self.assertIn("Excel has a.xlsx open", pr["text"])
        self.answer(jd, pr["prompt_id"], "continue")
        pr2 = self.wait_for(lambda: (JL.read_json(os.path.join(jd, "prompt.json")) or {}).get("prompt_id") not in
                            (None, pr["prompt_id"]) and JL.read_json(os.path.join(jd, "prompt.json")), 30,
                            what="second excel prompt")
        os.remove(lockf)
        self.answer(jd, pr2["prompt_id"], "continue")
        p.wait(60)
        self.assertEqual(self.state(jd)["status"], "done")


class TestStops(Case):
    def test_after_step(self):
        p, jd, jid = self.job("selftest.long")
        self.wait_step_running(jd, 0)
        self.stop(jd, "after_step")
        p.wait(60)
        st = self.state(jd)
        self.assertEqual(st["status"], "stopped")
        self.assertEqual(st["steps"][0]["status"], "ok")
        self.assertTrue(all(s["status"] == "skipped" for s in st["steps"][1:]))
        self.assert_clean(jid)

    def test_after_cycle(self):
        p, jd, jid = self.job("selftest.loop")
        self.wait_step_running(jd, 0)
        self.stop(jd, "after_cycle")
        p.wait(60)
        st = self.state(jd)
        self.assertEqual(st["status"], "stopped")
        self.assertEqual(st["cycle"], 1)
        self.assertEqual([s["status"] for s in st["steps"]], ["ok", "ok"])

    def test_kill(self):
        p, jd, jid = self.job("selftest.long")
        self.wait_step_running(jd, 0)
        time.sleep(0.5)
        kids = child_pids(p.pid)
        self.assertTrue(kids)
        t0 = time.time()
        self.stop(jd, "kill")
        p.wait(30)
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(self.state(jd)["status"], "killed")
        self.assertEqual(self.state(jd)["steps"][0]["status"], "killed")
        for k in kids:
            self.assertIsNone(JL.proc_start_time(k))
        self.assert_clean(jid)

    def test_kill_cli_on_unresponsive_runner(self):
        p, jd, jid = self.job("selftest.long")
        self.wait_step_running(jd, 0)
        time.sleep(0.5)
        kids = child_pids(p.pid)
        out = json.loads(subprocess.run([PY, RUN, "--kill", jid], env=self.env, capture_output=True, text=True).stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "killed")
        t0 = time.time()
        self.wait_for(lambda: JL.proc_start_time(p.pid) is None and all(JL.proc_start_time(k) is None for k in kids),
                      5, what="runner and child gone")
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(self.state(jd)["status"], "killed")
        self.assert_clean(jid)

    def test_stop_during_countdown(self):
        p, jd, jid = self.job("selftest.hands_off")
        self.wait_for(lambda: any(e.get("level") == "countdown" for e in self.events(jd)), 30, what="countdown")
        self.stop(jd, "after_step")
        p.wait(30)
        st = self.state(jd)
        self.assertEqual(st["status"], "stopped")
        self.assertEqual(st["steps"][0]["status"], "skipped")
        self.assertNotIn("step_start", [e["type"] for e in self.events(jd)])

    def test_hands_off_countdown(self):
        p, jd, jid = self.job("selftest.hands_off", wait=True)
        ev = self.events(jd)
        cd = [e["text"] for e in ev if e.get("level") == "countdown"]
        self.assertEqual(cd, [f"Hands off: OOTP starts in {n}" for n in (5, 4, 3, 2, 1)])
        self.assertLess([e["type"] for e in ev].index("message"), [e["type"] for e in ev].index("step_start"))
        self.assertEqual(self.state(jd)["status"], "done")

    def test_rollback(self):
        p, jd, jid = self.job("selftest.rollback")
        self.wait_step_running(jd, 1)
        self.stop(jd, "kill")
        p.wait(60)
        self.assertEqual(self.state(jd)["status"], "killed")
        self.assertTrue(os.path.exists(os.path.join(jd, "rolled_back")))
        p, jd, jid = self.job("selftest.rollback", wait=True)
        self.assertEqual(self.state(jd)["status"], "done")
        self.assertFalse(os.path.exists(os.path.join(jd, "rolled_back")))


class TestNamedLocks(Case):
    def test_same_task_refused(self):
        p1, jd1, j1 = self.job("selftest.long")
        self.wait_step_running(jd1, 0)
        p2, jd2, j2 = self.job("selftest.long", wait=True)
        self.assertEqual(p2.returncode, 3)
        st = self.state(jd2)
        self.assertEqual(st["status"], "refused")
        self.assertIn("is this same task", st["message"])
        self.stop(jd1, "kill")
        p1.wait(30)

    def test_queued_then_done(self):
        p1, jd1, j1 = self.job("selftest.long")
        self.wait_step_running(jd1, 0)
        p2, jd2, j2 = self.job("selftest.ok")
        st = self.wait_status(jd2, "queued", 30)
        self.assertEqual(st["waiting_for"]["job_id"], j1)
        self.assertEqual(st["data_lock"], "waiting")
        self.stop(jd1, "after_step")
        p2.wait(90)
        self.assertEqual(self.state(jd2)["status"], "done")
        p1.wait(60)

    def test_phase_ootp_lock_and_data_wait(self):
        p1, jd1, j1 = self.job("selftest.phase")
        self.wait_step_running(jd1, 0)
        lk = JL.read_lock("ootp")
        self.assertEqual(lk["job_id"], j1)
        other = dict(JL.me(), job_id="20261001-000000-ootp_tool-9999", task="ootp_tool", title="T", mode="job")
        ok, cur = JL.take_lock("ootp", other)
        self.assertFalse(ok)
        self.assertEqual(cur["job_id"], j1)
        # selftest.ok runs and finishes during phase step 1 (no data lock held)
        p2, jd2, j2 = self.job("selftest.ok", wait=True)
        self.assertEqual(self.state(jd2)["status"], "done")
        self.assertEqual(self.state(jd1)["steps"][0]["status"], "running")
        # wait for the cycle to end (data released), then start long during the next step 1
        self.wait_for(lambda: self.state(jd1).get("cycle") == 2, 60, what="phase cycle 2")
        p3, jd3, j3 = self.job("selftest.long")
        self.wait_step_running(jd3, 0)
        st = self.wait_for(lambda: self.state(jd1) if self.state(jd1).get("data_lock") == "waiting" else None, 30,
                           what="phase waits for data")
        self.assertEqual(st["waiting_for"]["job_id"], j3)
        self.assertEqual(st["status"], "running")
        self.stop(jd3, "after_step")
        p3.wait(60)
        self.wait_for(lambda: self.state(jd1).get("data_lock") == "held", 30, what="phase takes data")
        self.stop(jd1, "kill")
        p1.wait(30)
        self.assert_clean(j1)


class TestConsole(Case):
    def hold_data(self):
        p, jd, jid = self.job("selftest.long")
        self.wait_step_running(jd, 0)
        return p, jd, jid

    def console_job(self, task):
        try:
            ids = [n for n in os.listdir(os.path.join(self.ctl, "jobs")) if task in n]
        except OSError:
            return None
        for n in ids:
            st = self.state(os.path.join(self.ctl, "jobs", n))
            if st.get("mode") == "console":
                return os.path.join(self.ctl, "jobs", n)
        return None

    def test_data_question_cancel(self):
        p1, jd1, j1 = self.hold_data()
        c = self.console("selftest.ok", "C\n")
        out = c.communicate(timeout=60)[0].decode("utf-8", "replace")
        self.assertEqual(c.returncode, 3, out)
        self.assertIn("is updating app data right now", out)
        self.stop(jd1, "kill")
        p1.wait(30)

    def test_data_question_run_anyway(self):
        p1, jd1, j1 = self.hold_data()
        c = self.console("selftest.ok", "R\n")
        out = c.communicate(timeout=60)[0].decode("utf-8", "replace")
        self.assertEqual(c.returncode, 0, out)
        jd = self.console_job("selftest.ok")
        st = self.state(jd)
        self.assertEqual(st["data_lock"], "skipped")
        self.assertIn(("lock", "skipped"), [(e["type"], e.get("action")) for e in self.events(jd)])
        self.stop(jd1, "kill")
        p1.wait(30)

    def test_data_question_eof_waits(self):
        p1, jd1, j1 = self.hold_data()
        c = self.console("selftest.ok", "")
        c.stdin.close()
        c.stdin = None     # POSIX communicate() flushes a set stdin
        time.sleep(4)
        self.assertIsNone(c.poll())
        self.stop(jd1, "after_step")
        out = c.communicate(timeout=90)[0].decode("utf-8", "replace")
        self.assertEqual(c.returncode, 0, out)
        p1.wait(60)

    def ctrl_break(self, answer):
        c = self.console("selftest.long", answer, group=True)
        jd = self.wait_for(lambda: self.console_job("selftest.long"), 30, what="console job")
        self.wait_step_running(jd, 0)
        time.sleep(1)
        if os.name == "nt":
            c.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(c.pid, signal.SIGINT)     # a terminal's Ctrl+C: the whole console group
        out = c.communicate(timeout=60)[0].decode("utf-8", "replace")
        return c.returncode, self.state(jd), out

    def test_ctrl_break_yes(self):
        rc, st, out = self.ctrl_break("Y\n")
        self.assertEqual(rc, 130, out)
        self.assertEqual(st["status"], "stopped")
        self.assertIn("Stop the whole run?", out)

    def test_ctrl_break_no(self):
        rc, st, out = self.ctrl_break("N\n")
        self.assertEqual(st["status"], "failed", out)
        self.assertEqual(st["steps"][0]["status"], "failed")
        self.assertEqual(rc, 1)

    def test_console_asks_later_and_passes_argv(self):
        """Console mode does not demand inputs its prompts ask later, and passes the
        bat's %1 through unchecked. The missing ratings archive stops each run before
        anything runs, so these real tasks only prove that input checking passed."""
        root = os.path.join(self.ctl, "archive")
        os.makedirs(os.path.join(root, "vintages", "X"))
        open(os.path.join(root, "vintages", "X", "_pulls.csv"), "w").close()
        env = {"RATINGS_ARCHIVE_ROOT": root, "RATINGS_DB_ALLOW_NEW": ""}
        for task, args in (("get_history", ()), ("sim_dev", ("abc",)), ("sim_dev", ("3",))):
            c = self.console(task, "", env=env, args=args)
            c.stdin.close()
            c.stdin = None     # POSIX communicate() flushes a set stdin
            out = c.communicate(timeout=60)[0].decode("utf-8", "replace")
            self.assertEqual(c.returncode, 2, out)
            self.assertIn("The ratings archive is missing", out)
            self.assertIn("vintage_backup.py --restore", out)
            self.assertNotIn("required", out)
            self.assertNotIn("====", out, "the banner must not print before the archive check")

    def test_dry_run_takes_no_lock(self):
        p1, jd1, j1 = self.hold_data()
        before = set(os.listdir(os.path.join(self.ctl, "jobs")))
        c = self.console("selftest.long", "", env={"TGS_DRY_RUN": "1"})
        out = c.communicate(timeout=60)[0].decode("utf-8", "replace")
        self.assertEqual(c.returncode, 0, out)
        plan = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(plan["task"], "selftest.long")
        self.assertEqual(set(os.listdir(os.path.join(self.ctl, "jobs"))), before)
        self.assertEqual(sorted(JL.list_locks()), ["data", "task.selftest.long"])
        self.assertEqual(len(JL.list_active()), 1)
        self.stop(jd1, "kill")
        p1.wait(30)


class TestConditions(unittest.TestCase):
    def test_shared_cases(self):
        with open(os.path.join(HERE, "fixtures", "conditions_cases.json"), encoding="utf-8") as f:
            cases = json.load(f)
        self.assertGreater(len(cases), 30)
        for c in cases:
            got = C.evaluate(c["condition"], tokens=c["state"]["tokens"], inputs=c["inputs"], flags=c["flags"],
                             repo=REPO)
            self.assertEqual(got, c["expect"], c["name"])
            self.assertEqual(C.python_only(c["condition"]), c["python_only"], c["name"])


if __name__ == "__main__":
    unittest.main()
