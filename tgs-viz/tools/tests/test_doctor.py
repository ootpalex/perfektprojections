"""
test_doctor.py - doctor.py output shape, no token leaks, no writes, bad
settings, and the jobs row.

    python tgs-viz/tools/tests/test_doctor.py

Each run points STATSPLUS_TOKEN_FILE, TGS_SETTINGS_LOCAL and TGS_CONTROL_DIR at
a temp folder. Nothing in the worktree is written.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
DOCTOR = os.path.join(TOOLS, "doctor.py")
TMP = tempfile.mkdtemp(prefix="tgs-doctor-test-")
FAKE_TOKEN = "abcdefgh-1234-ijkl-5678-mnopqrstuvwx"      # 36 characters, not a real token
STATUSES = {"ok", "warn", "fail", "skip"}


def run(*args, env=None, files=None):
    d = tempfile.mkdtemp(dir=TMP)
    e = dict(os.environ)
    e.update(TGS_SETTINGS_LOCAL=os.path.join(d, "settings.local.json"),
             STATSPLUS_TOKEN_FILE=os.path.join(d, "StatsPlus Tokens.txt"),
             TGS_CONTROL_DIR=os.path.join(d, "control"))
    e.pop("TGS_JOB_ID", None)
    e.update(env or {})
    for name, text in (files or {}).items():
        p = e[name] if name in e else os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    t0 = time.time()
    p = subprocess.run([sys.executable, DOCTOR] + list(args), capture_output=True, text=True, env=e, timeout=60)
    return p, time.time() - t0, d, e


class Doctor(unittest.TestCase):
    def test_json_shape_and_speed(self):
        p, secs, _d, _e = run("--json")
        self.assertIn(p.returncode, (0, 1), p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["schema"], 1)
        self.assertIsInstance(out["ok"], bool)
        ids = [c["id"] for c in out["checks"]]
        for c in out["checks"]:
            self.assertEqual(set(c), {"id", "title", "status", "detail", "fix", "task"})
            self.assertIn(c["status"], STATUSES)
        for want in ("settings", "node", "node_modules", "python.main", "python.ml", "ratings_db", "ml_models",
                     "git_ignore", "jobs", "ootp.26", "ootp.27", "league.TGS.data", "league.DEV.data"):
            self.assertIn(want, ids)
        self.assertEqual(out["ok"], not any(c["status"] == "fail" for c in out["checks"]))
        self.assertEqual(p.returncode, 0 if out["ok"] else 1)
        self.assertLess(secs, 20)

    def test_text_output(self):
        p, _s, _d, _e = run()
        lines = p.stdout.strip().splitlines()
        self.assertRegex(lines[-1], r"^Setup check: \d+ problems, \d+ warnings\.$")
        self.assertTrue(all(ln.startswith(("[ OK ]", "[WARN]", "[FAIL]", "[SKIP]", "    ")) for ln in lines[:-1]))

    def test_token_never_shown_and_nothing_written(self):
        files = {"STATSPLUS_TOKEN_FILE": f"TGS={FAKE_TOKEN}\r\nBLM=not a token value here!!\r\n"}
        for args in ([], ["--json"]):
            p, _s, d, e = run(*args, files=files)
            self.assertNotIn(FAKE_TOKEN, p.stdout + p.stderr)
            self.assertNotIn("not a token value", p.stdout + p.stderr)
            self.assertEqual(sorted(os.listdir(d)), ["StatsPlus Tokens.txt"])     # no seen file, no control dir
            if args:
                rows = {c["id"]: c for c in json.loads(p.stdout)["checks"]}
                self.assertEqual(rows["tokens.TGS"]["status"], "ok")
                self.assertIn("present", rows["tokens.TGS"]["detail"])
                self.assertEqual(rows["tokens.BLM"]["status"], "warn")
                self.assertIn("looks wrong: ", rows["tokens.BLM"]["detail"])
                self.assertEqual(rows["tokens.BLM"]["task"], "token_set")

    def test_bad_settings(self):
        p, _s, _d, _e = run("--json", files={"TGS_SETTINGS_LOCAL": "{bad"})
        self.assertEqual(p.returncode, 1, p.stderr)
        rows = {c["id"]: c for c in json.loads(p.stdout)["checks"]}
        self.assertEqual(rows["settings"]["status"], "fail")
        self.assertIn("settings.local.json", rows["settings"]["detail"])
        self.assertIn("Reset local settings", rows["settings"]["fix"])

    def test_jobs_row(self):
        try:
            sys.path.insert(0, TOOLS)
            import joblock  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("joblock.py (A's module) is not there yet")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        own, other = "20261001-120000-selftest.long-aaaa", "20261001-120001-selftest.ok-bbbb"
        d = tempfile.mkdtemp(dir=TMP)
        control = os.path.join(d, "control")
        os.makedirs(os.path.join(control, "active"))
        for jid, title in ((own, "Self test long"), (other, "Self test ok")):
            with open(os.path.join(control, "active", jid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "job_id": jid, "task": "selftest", "title": title, "mode": "job",
                           "pid": dead.pid, "pid_started": 1, "started": "2026-10-01T12:00:00"}, f)
        p, _s, _d, _e = run("--json", env={"TGS_CONTROL_DIR": control, "TGS_JOB_ID": own})
        jobs = [c for c in json.loads(p.stdout)["checks"] if c["id"] == "jobs"]
        self.assertEqual(len(jobs), 1, jobs)
        self.assertEqual(jobs[0]["status"], "warn")
        self.assertIn("Self test ok", jobs[0]["detail"])
        self.assertNotIn(own, jobs[0]["detail"])
        self.assertEqual(sorted(os.listdir(os.path.join(control, "active"))), [own + ".json", other + ".json"])
        p, _s, _d, _e = run("--json", env={"TGS_CONTROL_DIR": control, "TGS_JOB_ID": other})
        jobs = [c for c in json.loads(p.stdout)["checks"] if c["id"] == "jobs"]
        self.assertEqual([j["detail"].split(" (")[0] for j in jobs], ["Self test long"])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
