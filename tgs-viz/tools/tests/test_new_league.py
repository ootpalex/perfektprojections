"""
test_new_league.py - the New League backend (new_league.py) on fixtures.

    python tgs-viz/tools/tests/test_new_league.py

Everything happens in a temp folder: a fake OOTP saved_games folder, the local
settings file (TGS_SETTINGS_LOCAL), the control folder (TGS_CONTROL_DIR), the
ratings archive (RATINGS_ARCHIVE_ROOT), the token file (STATSPLUS_TOKEN_FILE),
a copy of leagues.json (--manifest) and the app data folder (patched in this
process). The worktree is only read.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
VIZ = os.path.dirname(TOOLS)
REPO = os.path.dirname(VIZ)

TMP = tempfile.mkdtemp(prefix="tgs-newleague-test-")
SG = os.path.join(TMP, "saved_games27")
DATA = os.path.join(TMP, "data")
ARCH = os.path.join(TMP, "archive")
CONTROL = os.path.join(TMP, "control")
LOCAL = os.path.join(TMP, "settings.local.json")
TOKENS = os.path.join(TMP, "tokens", "StatsPlus Tokens.txt")
MAN = os.path.join(DATA, "leagues.json")
FAKE_TOKEN = "abcdefgh-1234-ijkl-5678-mnopqrstuvwx"      # 36 characters, not a real token

os.environ.update(TGS_SETTINGS_LOCAL=LOCAL, TGS_CONTROL_DIR=CONTROL, RATINGS_ARCHIVE_ROOT=ARCH,
                  STATSPLUS_TOKEN_FILE=TOKENS)
os.environ.pop("RATINGS_DB_ALLOW_NEW", None)
os.environ.pop("TGS_NL_TOKEN", None)


def _mk(*parts, text=None):
    p = os.path.join(*parts)
    if text is None:
        os.makedirs(p, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return p


# fake OOTP 27 saves
for save in ("Fun Save", "Pristine", "0zz01", "AllAI", "BLM", "Regular Game", "DEV TESTS", "6", "3", "0blm07"):
    _mk(SG, save + ".lg")
_mk(SG, "Fun Save.lg", "import_export", "csv", "players.csv", text="player_id\n1\n")
_mk(SG, "0blm07.lg", "import_export", "csv", "players.csv", text="player_id\n1\n")
_mk(SG, "AllAI.lg", "dump")
with open(LOCAL, "w", encoding="utf-8") as f:
    json.dump({"ootp": {"installs": {"27": {"saved_games": SG}}}}, f)
_mk(DATA)
shutil.copyfile(os.path.join(VIZ, "public", "data", "leagues.json"), MAN)
_mk(ARCH, "vintages", "OLD2", "_pulls.csv", text="pull_id,league\n")

for p in (TOOLS, os.path.join(VIZ, "ingest"), os.path.join(VIZ, "backtest"), VIZ):
    if p not in sys.path:
        sys.path.insert(0, p)
import settings as ST          # noqa: E402
import new_league as NL        # noqa: E402
import extract_data as X       # noqa: E402
import ratings_db as RDB       # noqa: E402

NL.DATA = DATA                 # the app data folder of this test
X.OUTPUT_BASE = DATA

# an archive that already holds league OLD (a reused id)
os.environ["RATINGS_DB_ALLOW_NEW"] = "1"
_conn = RDB.connect(os.path.join(ARCH, "ratings_history.db"))
RDB.insert_pull(_conn, "OLD", "2026-01-01", "2026-01-01T00:00:00", "live", [],
                {"1": {"name": "A", "age": 20, "pos": "SS", "org": "1", "lev": "MLB"}})
_conn.close()
os.environ.pop("RATINGS_DB_ALLOW_NEW")


def nl(*argv, env=None):
    """(exit code, printed text) of new_league.main in this process."""
    old = dict(os.environ)
    os.environ.update(env or {})
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = NL.main(list(argv))
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, buf.getvalue()


def _bytes(p):
    with open(p, "rb") as f:
        return f.read()


def spec_file(obj, folder=None):
    folder = folder or tempfile.mkdtemp(dir=TMP)
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, "new_league_spec.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


def check(obj):
    code, out = nl("check", "--spec", spec_file(obj), "--json", "--manifest", MAN)
    res = json.loads(out)
    assert (code == 0) == res["ok"], (code, res)
    return res


def local_leagues():
    return ST.local_raw().get("leagues") or {}


class Options(unittest.TestCase):
    def test_options(self):
        code, out = nl("options", "--type", "local_export", "--version", "27", "--json")
        self.assertEqual(code, 0)
        o = json.loads(out)
        self.assertIn("Fun Save", o["saves"])
        self.assertEqual(o["bases"], ["TGS", "BLM"])
        self.assertIn("0blm07", o["clones"])
        self.assertIn("3", o["clones"])
        self.assertIn("BLM", o["protected"])
        self.assertIn("Regular Game", o["protected"])
        self.assertEqual(o["in_use"].get("DEV TESTS"), "DEV")
        v27 = [v for v in o["versions"] if v["version"] == "27"][0]
        self.assertTrue(v27["exists"])
        self.assertEqual(nl("options", "--type", "x")[0], 2)
        self.assertEqual(nl("options", "--type", "dev", "--version", "2a")[0], 2)

    def test_cli_json(self):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "new_league.py"), "options", "--type", "dev",
                            "--version", "27", "--json"], capture_output=True, text=True, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("AllAI", json.loads(r.stdout)["saves"])
        sp = spec_file({"type": "dev", "fields": {"id": "con", "name": "x", "ootp_version": "27",
                                                  "ootp_save": "AllAI"}})
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "new_league.py"), "check", "--spec", sp, "--json"],
                           capture_output=True, text=True, cwd=REPO)
        self.assertEqual(r.returncode, 2)
        res = json.loads(r.stdout)
        self.assertFalse(res["ok"])
        self.assertIn("id", res["errors"])
        self.assertTrue(res["plan"])


class Check(unittest.TestCase):
    LOCAL_OK = {"type": "local_export", "id": "ZTA", "name": "Fun", "ootp_version": "27", "ootp_save": "Fun Save"}

    def test_local_export(self):
        res = check(self.LOCAL_OK)
        self.assertTrue(res["ok"], res)
        self.assertEqual([s["title"] for s in res["plan"]][:3],
                         ["Check the fields", "Save the league settings", "Read the OOTP export"])
        for typed in ("..\\..\\x", "Nope", "fun save"):
            res = check(dict(self.LOCAL_OK, ootp_save=typed))
            self.assertIn("ootp_save", res["errors"], typed)
        self.assertIn("ootp_save", check(dict(self.LOCAL_OK, ootp_save="Pristine"))["errors"])   # no export
        self.assertIn("ootp_save", check(dict(self.LOCAL_OK, ootp_save="0blm07"))["errors"])     # a clone
        self.assertIn("basis", check(dict(self.LOCAL_OK, basis="XX"))["errors"])

    def test_ids(self):
        for bad in ("CON", "NUL", "COM1", "LPT9", "zta", "TOOLONGID", "A", "TGS", "DEV", "RG", "OLD", "OLD2"):
            res = check(dict(self.LOCAL_OK, id=bad))
            self.assertIn("id", res["errors"], bad)
        self.assertEqual(check(dict(self.LOCAL_OK, id="OLD"))["errors"]["id"], "This id was used before. Pick another id.")
        self.assertEqual(check(dict(self.LOCAL_OK, id="OLD2"))["errors"]["id"], "This id was used before. Pick another id.")
        self.assertIn("name", check(dict(self.LOCAL_OK, name=""))["errors"])
        self.assertIn("name", check(dict(self.LOCAL_OK, name="x" * 41))["errors"])

    def test_statsplus(self):
        good = {"type": "statsplus", "id": "ZTS", "name": "S", "slug": "ztsl", "basis": "BLM"}
        res = check(good)
        self.assertTrue(res["ok"], res)
        self.assertTrue(any("ZTSL=" in w for w in res["warnings"]))
        self.assertIn("slug", check(dict(good, slug="tgs"))["errors"])
        self.assertIn("slug", check(dict(good, slug="Bad Slug"))["errors"])
        self.assertIn("basis", check(dict(good, basis="XX"))["errors"])
        self.assertIn("history_first_date", check(dict(good, history_first_date="2038-13-01"))["errors"])
        self.assertIn("foreign_league_ids", check(dict(good, foreign_league_ids="117,abc"))["errors"])
        self.assertIn("ootp_save", check(dict(good, ootp_version="27", ootp_save="Typed Save"))["errors"])
        self.assertTrue(check(dict(good, ootp_version="27", ootp_save="Fun Save", foreign_league_ids="117, 118",
                                   history_first_date="2040-01-01"))["ok"])

    def test_dev(self):
        good = {"type": "dev", "id": "ZTD", "name": "D", "ootp_version": "27", "ootp_save": "AllAI"}
        self.assertTrue(check(good)["ok"])
        self.assertIn("ootp_save", check(dict(good, ootp_save="BLM"))["errors"])          # a real league
        self.assertIn("ootp_save", check(dict(good, ootp_save="6"))["errors"])            # BLM's master
        self.assertIn("ootp_save", check(dict(good, ootp_save="DEV TESTS"))["errors"])    # DEV sims it
        res = check(dict(good, ootp_save="Pristine"))
        self.assertTrue(res["ok"])
        self.assertTrue(any("dump" in w for w in res["warnings"]))
        self.assertIn("years", check(dict(good, years="many"))["errors"])
        self.assertIn("years", check(dict(good, years=0))["errors"])

    def test_clone(self):
        good = {"type": "clone", "id": "ZTC", "name": "C", "ootp_version": "27", "master": "Pristine", "prefix": "0qq"}
        self.assertTrue(check(good)["ok"])
        self.assertIn("prefix", check(dict(good, prefix="0zz"))["errors"])                # 0zz01 exists
        self.assertIn("prefix", check(dict(good, prefix="0blm"))["errors"])               # BLM's prefix
        self.assertIn("prefix", check(dict(good, prefix="Bad Prefix"))["errors"])
        self.assertIn("master", check(dict(good, master="BLM"))["errors"])
        self.assertIn("master", check(dict(good, master="C:\\x"))["errors"])
        self.assertIn("target_year", check(dict(good, start_year=2030, target_year=2020))["errors"])
        self.assertEqual(NL.normalize({"type": "clone", "id": "ZTC"})[0]["prefix"], "0ztc")

    def test_precheck_only_when_asked(self):
        folder = tempfile.mkdtemp(dir=TMP)
        sp = spec_file(self.LOCAL_OK, folder)
        nl("check", "--spec", sp, "--manifest", MAN)
        self.assertEqual(sorted(os.listdir(folder)), ["new_league_spec.json"])
        pre = os.path.join(folder, "precheck.json")
        nl("check", "--spec", sp, "--precheck-out", pre, "--manifest", MAN)
        with open(pre, encoding="utf-8") as f:
            p = json.load(f)
        for k in ("data_dir_existed", "manifest_had_id", "settings_had_id", "token_line_existed",
                  "vintages_dir_existed", "archive_had_id"):
            self.assertIn(k, p)
        self.assertFalse(any(p[k] for k in p if k != "id"))


class Flow(unittest.TestCase):
    def _job(self, obj):
        folder = os.path.join(CONTROL, "jobs", f"20261001-120000-new_league-{os.urandom(2).hex()}")
        sp = spec_file(obj, folder)
        pre = os.path.join(folder, "precheck.json")
        code, out = nl("check", "--spec", sp, "--precheck-out", pre, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        return sp, pre, folder

    def test_statsplus_profile_register_remove(self):
        obj = {"type": "statsplus", "id": "ZTS", "name": "Online test", "slug": "ztsl", "basis": "BLM",
               "foreign_league_ids": "117", "my_org": "Test Org"}
        sp, pre, _f = self._job(obj)
        code, out = nl("profile", "--spec", sp)
        self.assertEqual(code, 0, out)
        e = local_leagues()["ZTS"]
        self.assertEqual(e["pending"], True)
        self.assertEqual((e["type"], e["slug"], e["basis"], e["foreign_league_ids"]), ("statsplus", "ztsl", "BLM", ["117"]))
        self.assertNotIn("ZTS", ST.leagues())
        self.assertEqual(ST.slug("ZTS"), "ztsl")
        code, out = nl("token", "--spec", sp)
        self.assertEqual(code, 0, out)
        with open(TOKENS, encoding="utf-8") as f:
            self.assertIn("ZTSL=", f.read())
        code, out = nl("register", "--spec", sp, "--manifest", MAN)      # no data files yet
        self.assertEqual(code, 2, out)
        self.assertTrue(local_leagues()["ZTS"]["pending"])
        _mk(DATA, "ZTS", "hitters.json", text="[]")
        _mk(DATA, "ZTS", "pitchers.json", text="[]")
        code, out = nl("register", "--spec", sp, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertNotIn("pending", local_leagues()["ZTS"])
        self.assertIn("ZTS", ST.leagues())
        ent = [x for x in X.load_manifest_entries(MAN) if x["id"] == "ZTS"][0]
        self.assertEqual((ent["name"], ent["basis"], ent["source"], ent["slug"]), ("Online test", "BLM", "StatsPlus", "ztsl"))
        self.assertTrue(ent["features"]["players"])
        # a rollback now changes nothing: the league finished its add step
        code, out = nl("rollback", "--spec", sp, "--precheck", pre, "--manifest", MAN)
        self.assertEqual(code, 0)
        self.assertIn("nothing is undone", out)
        self.assertTrue(os.path.isdir(os.path.join(DATA, "ZTS")))
        # remove
        self.assertEqual(nl("remove", "--league", "TGS", "--manifest", MAN)[0], 2)
        code, out = nl("remove", "--league", "ZTS", "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(DATA, "ZTS")))
        moved = [n for n in os.listdir(os.path.join(CONTROL, "removed")) if n.startswith("ZTS-")]
        self.assertEqual(len(moved), 1)
        self.assertNotIn("ZTS", {x["id"] for x in X.load_manifest_entries(MAN)})
        self.assertNotIn("ZTS", local_leagues())
        with open(TOKENS, encoding="utf-8") as f:
            self.assertIn("ZTSL=", f.read())                               # the token line stays

    def test_local_export_register(self):
        obj = {"type": "local_export", "id": "ZTL", "name": "Local test", "ootp_version": "27", "ootp_save": "Fun Save"}
        sp, _pre, _f = self._job(obj)
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        self.assertEqual(local_leagues()["ZTL"]["basis"], "BLM")
        self.assertEqual(nl("register", "--spec", sp, "--manifest", MAN)[0], 2)   # export did not register it
        _mk(DATA, "ZTL", "hitters.json", text="[]")
        _mk(DATA, "ZTL", "pitchers.json", text="[]")
        X.upsert_manifest(MAN, [dict(X.build_manifest_entry("ZTL", name="Local test"), basis="BLM")])
        code, out = nl("register", "--spec", sp, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertNotIn("pending", local_leagues()["ZTL"])
        self.assertIn("ZTL", ST.leagues())
        self.assertIn("fun save", ST.protected_saves())

    def test_dev_register_manifest(self):
        obj = {"type": "dev", "id": "ZTD", "name": "Dev two", "ootp_version": "27", "ootp_save": "AllAI", "years": "3"}
        sp, _pre, _f = self._job(obj)
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        prof = ST.ootp_profiles()["ZTD"]
        self.assertEqual((prof["folder"], prof["years"], prof["source"], prof["mode"]), ("AllAI", 3, "dump", "continuous"))
        code, out = nl("register", "--spec", sp, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertIn("first banked season", out)
        self.assertNotIn("ZTD", {x["id"] for x in X.load_manifest_entries(MAN)})
        _mk(DATA, "ZTD", "rating_trends.json", text='{"v": 1, "players": {}}')
        code, out = nl("register-manifest", "--league", "ZTD", "--manifest", MAN)
        self.assertEqual(code, 0, out)
        ent = [x for x in X.load_manifest_entries(MAN) if x["id"] == "ZTD"][0]
        self.assertEqual(ent["name"], "Dev two")
        self.assertFalse(ent["features"]["players"])
        self.assertTrue(ent["features"]["trends"])
        self.assertNotIn("ztd", ST.protected_saves())                     # dev saves are never protected
        self.assertIn("allai", ST.league_saves())

    def test_clone_profile(self):
        obj = {"type": "clone", "id": "ZTC", "name": "Clones", "ootp_version": "27", "master": "Pristine",
               "prefix": "0qq", "runs": "4"}
        sp, _pre, _f = self._job(obj)
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        prof = ST.ootp_profiles()["ZTC"]
        self.assertEqual((prof["master"], prof["prefix"], prof["runs"], prof["game"]), ("Pristine", "0qq", 4, "27"))
        self.assertEqual(nl("register", "--spec", sp, "--manifest", MAN)[0], 0)
        self.assertIn("pristine", ST.league_saves())

    def test_rollback_after_fake_first_pull(self):
        obj = {"type": "statsplus", "id": "ZTR", "name": "Rollback test", "slug": "ztr", "basis": "TGS"}
        sp, pre, folder = self._job(obj)
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        self.assertEqual(nl("token", "--spec", sp)[0], 0)
        # the fake first pull: app files, an archive pull, a vintages folder, a manifest entry
        _mk(DATA, "ZTR", "hitters.json", text="[]")
        conn = RDB.connect(os.path.join(ARCH, "ratings_history.db"))
        RDB.insert_pull(conn, "ZTR", "2026-10-01", "2026-10-01T00:00:00", "live", [],
                        {"1": {"name": "A", "age": 20, "pos": "SS", "org": "1", "lev": "MLB"}})
        conn.close()
        _mk(ARCH, "vintages", "ZTR", "_pulls.csv", text="pull_id,league\n")
        X.upsert_manifest(MAN, [X.build_manifest_entry("ZTR", name="Rollback test")])
        self.assertEqual(check(dict(obj, id="ZTR"))["errors"].get("id") is not None, True)
        code, out = nl("rollback", "--spec", sp, "--precheck", pre, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        job_id = os.path.basename(folder)
        dest = os.path.join(CONTROL, "rollback", job_id)
        self.assertTrue(os.path.isdir(os.path.join(dest, "ZTR")))
        self.assertTrue(os.path.isdir(os.path.join(dest, "vintages-ZTR")))
        self.assertFalse(os.path.exists(os.path.join(DATA, "ZTR")))
        self.assertFalse(os.path.exists(os.path.join(ARCH, "vintages", "ZTR")))
        self.assertFalse(NL.archive_has("ZTR"))
        self.assertNotIn("ZTR", {x["id"] for x in X.load_manifest_entries(MAN)})
        self.assertNotIn("ZTR", local_leagues())
        with open(TOKENS, encoding="utf-8") as f:
            self.assertIn("ZTR=", f.read())                                # the token line stays
        self.assertTrue(check(obj)["ok"])                                    # the id is free again
        # a second rollback changes nothing
        snap = (sorted(os.listdir(dest)), _bytes(MAN), _bytes(LOCAL))
        code, out = nl("rollback", "--spec", sp, "--precheck", pre, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing to undo", out)
        self.assertEqual(snap, (sorted(os.listdir(dest)), _bytes(MAN), _bytes(LOCAL)))

    def test_rollback_never_undoes_an_added_league(self):
        obj = {"type": "statsplus", "id": "ZTQ", "name": "Added", "slug": "ztq", "basis": "TGS"}
        sp, pre, folder = self._job(obj)
        old_sp, old_pre, old_folder = self._job(obj)                       # an earlier try of the same id
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        _mk(DATA, "ZTQ", "hitters.json", text="[]")
        _mk(DATA, "ZTQ", "pitchers.json", text="[]")
        conn = RDB.connect(os.path.join(ARCH, "ratings_history.db"))
        RDB.insert_pull(conn, "ZTQ", "2026-10-01", "2026-10-01T00:00:00", "live", [],
                        {"1": {"name": "A", "age": 20, "pos": "SS", "org": "1", "lev": "MLB"}})
        conn.close()
        _mk(ARCH, "vintages", "ZTQ", "_pulls.csv", text="pull_id,league\n")
        self.assertEqual(nl("register", "--spec", sp, "--manifest", MAN)[0], 0)
        state = {"task": "new_league", "status": "lost",
                 "steps": [{"id": "check", "status": "ok"}, {"id": "register", "status": "ok"}]}
        with open(os.path.join(folder, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state, f)
        with open(os.path.join(old_folder, "state.json"), "w", encoding="utf-8") as f:
            json.dump(dict(state, status="failed", steps=[{"id": "register", "status": "pending"}]), f)
        self.assertEqual(nl("remove", "--league", "ZTQ", "--manifest", MAN)[0], 0)
        for s, p in ((sp, pre), (old_sp, old_pre)):
            code, out = nl("rollback", "--spec", s, "--precheck", p, "--manifest", MAN)
            self.assertEqual(code, 0, out)
            self.assertIn("Nothing is undone", out)
            self.assertTrue(NL.archive_has("ZTQ"))                          # remove keeps these on purpose
            self.assertTrue(os.path.isdir(os.path.join(ARCH, "vintages", "ZTQ")))
        self.assertIsNone(NL.changed_after(CONTROL, "20261001-120000-new_league-none", "ZTX"))

    def test_rollback_keeps_what_existed(self):
        obj = {"type": "local_export", "id": "ZTK", "name": "Keep", "ootp_version": "27", "ootp_save": "Fun Save"}
        sp, pre, folder = self._job(obj)
        with open(pre, encoding="utf-8") as f:
            p = json.load(f)
        p.update(data_dir_existed=True)                                     # pretend the folder was there
        with open(pre, "w", encoding="utf-8") as f:
            json.dump(p, f)
        _mk(DATA, "ZTK", "hitters.json", text="[]")
        self.assertEqual(nl("profile", "--spec", sp)[0], 0)
        code, out = nl("rollback", "--spec", sp, "--precheck", pre, "--manifest", MAN)
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isdir(os.path.join(DATA, "ZTK")))
        self.assertNotIn("ZTK", local_leagues())
        missing = os.path.join(folder, "nope.json")
        self.assertEqual(nl("rollback", "--spec", sp, "--precheck", missing, "--manifest", MAN)[0], 0)


class ClonePatterns(unittest.TestCase):
    def test_same_as_cleanup(self):
        sys.path.insert(0, os.path.join(REPO, "ootp"))
        import cleanup_clones as CC
        self.assertEqual(NL.FIXED_CLONE_PATTERNS, CC.ALLOW["TGS"] + CC.ALLOW["BLM"])


class Token(unittest.TestCase):
    def test_token_league(self):
        code, out = nl("token", "--league", "TGS", env={"TGS_NL_TOKEN": FAKE_TOKEN})
        self.assertEqual(code, 0, out)
        self.assertIn("TGS=", out)
        self.assertNotIn(FAKE_TOKEN, out)
        with open(TOKENS, encoding="utf-8") as f:
            self.assertIn(f"TGS={FAKE_TOKEN}", f.read())
        code, out = nl("token", "--league", "BLM", env={"TGS_NL_TOKEN": "short value with words"})
        self.assertEqual(code, 2)
        self.assertNotIn("short value", out)
        code, out = nl("token", "--league", "BLM")
        self.assertEqual(code, 0, out)
        self.assertEqual(nl("token", "--league", "RG")[0], 2)                # not an online league
        self.assertNotIn("TGS_NL_TOKEN", os.environ)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
