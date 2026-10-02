"""
test_settings_defaults.py - the settings defaults equal the values the code had
at ef23800 (the literals are written out below), and the settings rules hold.

    python tgs-viz/tools/tests/test_settings_defaults.py
    py -3.14 tgs-viz/tools/tests/test_settings_defaults.py

Runs with no local settings file (TGS_SETTINGS_LOCAL points at a missing temp
file) and a temp token file. Cases that need another settings file run in a
child process of the same interpreter. Writes only to a temp folder.
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
INGEST = os.path.join(VIZ, "ingest")
BACKTEST = os.path.join(VIZ, "backtest")
OOTP = os.path.join(REPO, "ootp")
CASES = os.path.join(VIZ, "control", "test", "fixtures", "python_main_cases.json")

TMP = tempfile.mkdtemp(prefix="tgs-settings-test-")
os.environ["TGS_SETTINGS_LOCAL"] = os.path.join(TMP, "no-local-settings.json")
os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(TMP, "tokens", "StatsPlus Tokens.txt")
os.environ.pop("RATINGS_DB_ALLOW_NEW", None)
os.environ.pop("RATINGS_ARCHIVE_ROOT", None)
_ENV = dict(os.environ)          # this module's environment, as set above
for p in (TOOLS, INGEST, BACKTEST, OOTP, VIZ):
    if p not in sys.path:
        sys.path.insert(0, p)

import settings as ST  # noqa: E402

# ---- the literals at ef23800 ----------------------------------------------------
OLD_TEMPLATE = (
    "# StatsPlus API tokens, one per league.\r\n"
    "# Paste each league's token after its = sign, then save this file.\r\n"
    "# Where: log in on statsplus.net, open the league, click Prefs (top right),\r\n"
    "# copy the Current Token from the API Token box (36 characters).\r\n"
    "# Tokens expire 90 days after StatsPlus makes them: paste the new one here then.\r\n"
    "# This file stays on this computer (it is not uploaded to GitHub).\r\n"
    "TGS=\r\n"
    "BLM=\r\n"
)
OLD_SLUGS = {"TGS": "tgs", "BLM": "blm"}
OLD_OOTP26 = r"C:\OOTP 26\data\saved_games"
OLD_OOTP27 = os.path.join(os.path.expanduser("~"), "Documents", "Out of the Park Developments",
                          "OOTP Baseball 27", "saved_games")
OLD_DRAFT_CSV = {
    "TGS": [[r"C:\OOTP 26\data\saved_games\TheGrandestSalami.lg\import_export\major_league_baseball_draft_pool_-_draft_pool_default.csv"]],
    "BLM": [[os.path.join(OLD_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_default.csv")],
            [os.path.join(OLD_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_hitter_export.csv"),
             os.path.join(OLD_OOTP27, "BLM.lg", "import_export",
                          "major_league_baseball_draft_pool_-_draft_pool_pitcher_export.csv")]],
}
OLD_R5_CSV = {
    "TGS": os.path.join(OLD_OOTP26, "TheGrandestSalami.lg", "import_export",
                        "major_league_baseball_draft_pool_-_draft_pool_fa_screen.csv"),
    "BLM": os.path.join(OLD_OOTP27, "BLM.lg", "import_export",
                        "major_league_baseball_draft_pool_-_draft_pool_fa_screen.csv"),
}
OLD_IAFA_CSV = {
    "TGS": os.path.join(OLD_OOTP26, "TheGrandestSalami.lg", "import_export",
                        "mlb_transactions_free_agents_-_international_amateur_fa_fa_screen.csv"),
    "BLM": os.path.join(OLD_OOTP27, "BLM.lg", "import_export",
                        "mlb_transactions_free_agents_-_international_amateur_fa_fa_screen.csv"),
}
OLD_PROTECTED = {"blm", "thegrandestsalami", "new game", "regular game"}
OLD_ALLOW = {
    "TGS": [r"0tgs\d+", r"tgs-run\d+"],
    "BLM": [r"0blm\d+", r"blm-run\d+", r"[1-5]", r"baseline02"],
}
FAKE_TOKEN = "abcdefgh-1234-ijkl-5678-mnopqrstuvwx"      # 36 characters, not a real token


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def run_py(code, local=None, env=None):
    """Run code in a child of this interpreter with its own local settings
    file; the code prints one JSON value, which is returned."""
    e = dict(os.environ)
    d = tempfile.mkdtemp(dir=TMP)
    if local is not None:
        lp = os.path.join(d, "settings.local.json")
        with open(lp, "w", encoding="utf-8") as f:
            f.write(local if isinstance(local, str) else json.dumps(local))
        e["TGS_SETTINGS_LOCAL"] = lp
    e["STATSPLUS_TOKEN_FILE"] = os.path.join(d, "StatsPlus Tokens.txt")
    e.update(env or {})
    pre = ("import sys, json, os\n"
           + "".join(f"sys.path.insert(0, {p!r})\n" for p in (TOOLS, INGEST, BACKTEST, OOTP, VIZ)))
    p = subprocess.run([sys.executable, "-c", pre + code], capture_output=True, text=True, env=e,
                       cwd=REPO, timeout=120)
    if p.returncode != 0:
        raise AssertionError(f"child failed ({p.returncode}):\n{p.stdout}\n{p.stderr}")
    return json.loads(p.stdout.strip().splitlines()[-1])


class Defaults(unittest.TestCase):
    """Every refactored value equals its ef23800 literal with no local file."""

    def test_statsplus_token(self):
        import statsplus_token as T
        self.assertEqual(T.LEAGUES, (("TGS", "tgs"), ("BLM", "blm")))
        self.assertEqual(T.TEMPLATE.encode("utf-8"), OLD_TEMPLATE.encode("utf-8"))
        self.assertEqual(T.FILE_NAME, "StatsPlus Tokens.txt")
        self.assertEqual(norm(T.default_token_file()), norm(os.path.join(REPO, "StatsPlus Tokens.txt")))

    def test_pull_report(self):
        import pull_report as PR
        self.assertEqual(PR.LEAGUES, ["TGS", "BLM"])
        self.assertEqual(PR.SLUGS, OLD_SLUGS)

    def test_ratings_db(self):
        import ratings_db as RDB
        self.assertEqual(RDB.LEAGUES, OLD_SLUGS)

    def test_statsplus_history(self):
        import statsplus_history as SH
        self.assertEqual(SH.SLUGS, OLD_SLUGS)
        self.assertEqual(SH.FIRST_KNOWN, {"TGS": "2038-01-01", "BLM": "2051-01-01"})
        self.assertEqual(SH.PROBE_YEARS, {"TGS": 0, "BLM": 0})
        self.assertEqual(SH.parse_args(["--league", "TGS"]).league, "TGS")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            SH.parse_args(["--league", "RG"])

    def test_metadata_inputs(self):
        import metadata_inputs as MI
        self.assertEqual(MI.SLUGS, OLD_SLUGS)

    def test_growth_lenses(self):
        import growth_lenses as GL
        self.assertEqual(GL.LEAGUE_SLUG, OLD_SLUGS)

    def test_parks(self):
        import parks
        self.assertEqual({k: v["home"] for k, v in parks.LEAGUES.items()},
                         {"TGS": "Chicago Cubs", "BLM": "Tampa Bay Rays"})

    def test_winsim_protected(self):
        import winsim
        self.assertEqual(winsim.PROTECTED, OLD_PROTECTED)
        with open(os.path.join(OOTP, "leagues.json"), encoding="utf-8") as f:
            self.assertEqual(winsim.load_profiles(), json.load(f))

    def test_cleanup_allow(self):
        import cleanup_clones as CC
        self.assertEqual(CC.ALLOW["TGS"], OLD_ALLOW["TGS"])
        self.assertEqual(CC.ALLOW["BLM"], OLD_ALLOW["BLM"])
        self.assertEqual(set(CC.ALLOW), {"TGS", "BLM"})

    def test_draft_r5_iafa_csv(self):
        import draft, r5, iafa
        self.assertEqual(set(draft.DEFAULT_CSV), set(OLD_DRAFT_CSV))
        for lg, groups in OLD_DRAFT_CSV.items():
            self.assertEqual([[norm(p) for p in g] for g in draft.DEFAULT_CSV[lg]],
                             [[norm(p) for p in g] for g in groups], lg)
        for mod, old in ((r5, OLD_R5_CSV), (iafa, OLD_IAFA_CSV)):
            self.assertEqual({k: norm(v) for k, v in mod.DEFAULT_CSV.items()},
                             {k: norm(v) for k, v in old.items()}, mod.__name__)

    def test_saved_games_raw(self):
        self.assertEqual(ST.saved_games_raw("26"), "C:/OOTP 26/data/saved_games")
        self.assertEqual(ST.saved_games_raw("27"), os.environ["USERPROFILE"]
                         + "/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games")

    def test_ootp_profiles(self):
        with open(os.path.join(OOTP, "leagues.json"), encoding="utf-8") as f:
            self.assertEqual(ST.ootp_profiles(), json.load(f))

    def test_settings_answers(self):
        self.assertEqual(ST.validate(ST.load()), [])
        self.assertEqual(ST.interp("main"), ["python"])
        self.assertEqual(ST.interp("ml"), ["py", "-3.14"])
        self.assertEqual(ST.interp("node"), ["node"])
        self.assertEqual(ST.slug_map(), OLD_SLUGS)
        self.assertEqual(ST.online_leagues(), ["TGS", "BLM"])
        self.assertEqual(ST.extra_leagues(), {"RG": "BLM"})
        self.assertEqual(ST.protected_saves(), OLD_PROTECTED)
        self.assertEqual(ST.league_saves(), {"thegrandestsalami", "blm", "regular game", "dev tests"})
        self.assertEqual(list(ST.leagues()), ["TGS", "BLM", "RG", "DEV"])
        self.assertEqual(ST.slug("RG"), "rg")
        self.assertEqual(ST.app_config()["leagues"]["BLM"], {"name": "BLM", "my_org": "Chicago (N) Cubs"})
        self.assertEqual(ST.app_config()["leagues"]["TGS"]["my_org"], "Chicago Cubs")
        self.assertEqual(ST.league("TGS")["dispersal_orgs"],
                         ["Atlanta Hammers", "Detroit Tigers", "San Francisco Giants", "Seattle Mariners"])
        self.assertEqual(norm(ST.ootp_save_dir("TGS")), norm(os.path.join(OLD_OOTP26, "TheGrandestSalami.lg")))
        self.assertEqual(norm(ST.ootp_save_dir("DEV")), norm(os.path.join(OLD_OOTP27, "DEV TESTS.lg")))
        self.assertEqual(ST.load()["app"]["port"], 3000)


class CalibArg(unittest.TestCase):
    """--calib absent: calib = league (refresh.py and draft.py)."""

    def _refresh_calib(self, argv):
        import refresh
        seen = []

        class Stop(Exception):
            pass

        def fake(lg):
            seen.append(lg)
            raise Stop()
        old_argv, old_dc = sys.argv, refresh.drift_check
        sys.argv, refresh.drift_check = ["refresh.py"] + argv, fake
        try:
            refresh.main()
        except Stop:
            pass
        finally:
            sys.argv, refresh.drift_check = old_argv, old_dc
        return seen[0]

    def test_refresh(self):
        self.assertEqual(self._refresh_calib(["--league", "TGS"]), "TGS")
        self.assertEqual(self._refresh_calib(["--league", "BLM", "--slug", "blm"]), "BLM")
        self.assertEqual(self._refresh_calib(["--league", "XY", "--calib", "BLM"]), "BLM")
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            self._refresh_calib(["--league", "XY", "--calib", "XY"])

    def test_draft(self):
        import draft
        old = sys.argv
        try:
            sys.argv = ["draft.py", "--league", "TGS"]
            self.assertEqual(draft._calib("TGS"), ("TGS", True))
            sys.argv = ["draft.py", "--league", "BLM", "--slug", "blm"]
            self.assertEqual(draft._calib("BLM"), ("BLM", True))
            sys.argv = ["draft.py", "--league", "XY", "--calib", "TGS"]
            self.assertEqual(draft._calib("XY"), ("TGS", False))
        finally:
            sys.argv = old


class StatsplusRules(unittest.TestCase):
    """_lev_for and drop_foreign answer as at ef23800 for TGS and BLM rows."""

    def test_lev_and_foreign(self):
        import statsplus as S
        tgs_rows = [{"ID": str(i), "League": lg} for i, lg in enumerate(
            ["100", "101", "104", "107", "111", "112", "113", "200", "-100", "0", "117", "118", "202", "119", "120", "999"])]
        self.assertEqual([S._lev_for(r, "TGS") for r in tgs_rows],
                         ["MLB", "AAA", "AA", "A+", "A-", "R+", "R-", "WL", "INT", "FA", "-", "-", "-", "-", "-", "-"])
        blm_rows = [{"LgLvl": x, "Org": o} for x, o in
                    [("1", "5"), ("2", "5"), ("3", "5"), ("4", "5"), ("5", "5"), ("6", "5"), ("0", "0"),
                     ("", "0"), ("", "7"), (None, "")]]
        self.assertEqual([S._lev_for(r, "BLM") for r in blm_rows],
                         ["MLB", "AAA", "AA", "A+", "A-", "R+", "FA", "FA", "R-", "FA"])
        kept = [r["League"] for r in S.drop_foreign(tgs_rows, league="TGS")]
        self.assertEqual(kept, ["100", "101", "104", "107", "111", "112", "113", "200", "-100", "0", "999"])
        self.assertEqual(len(S.drop_foreign(tgs_rows, league="BLM")), len(tgs_rows))
        self.assertEqual(len(S.drop_foreign(tgs_rows)), 11)         # default league stays TGS


class LocalFile(unittest.TestCase):
    """Settings rules with a local file (child processes)."""

    XY = {"leagues": {"XY": {"type": "statsplus", "name": "XY test", "slug": "xyleague", "basis": "BLM",
                             "foreign_league_ids": ["300"]}}}

    def test_new_online_league(self):
        out = run_py("import settings as ST, statsplus_token as T, statsplus as S\n"
                     "rows=[{'League':'300'},{'League':'117'}]\n"
                     "print(json.dumps({'tpl': T.TEMPLATE, 'leagues': T.LEAGUES, "
                     "'line': ST.slug('XY').upper() + '=', 'map': ST.slug_map(), "
                     "'drop': [r['League'] for r in S.drop_foreign(rows, league='XY')], "
                     "'lev': S._lev_for({'LgLvl': '2'}, 'XY')}))", local=self.XY)
        self.assertTrue(out["tpl"].endswith("TGS=\r\nBLM=\r\nXYLEAGUE=\r\n"))
        self.assertEqual(out["leagues"], [["TGS", "tgs"], ["BLM", "blm"], ["XY", "xyleague"]])
        self.assertEqual(out["line"], "XYLEAGUE=")
        self.assertEqual(out["map"], {"TGS": "tgs", "BLM": "blm", "XY": "xyleague"})
        self.assertEqual(out["drop"], ["117"])
        self.assertEqual(out["lev"], "AAA")

    def test_have_reads_slug_line(self):
        d = tempfile.mkdtemp(dir=TMP)
        lp = os.path.join(d, "settings.local.json")
        with open(lp, "w", encoding="utf-8") as f:
            json.dump(self.XY, f)
        tok = os.path.join(d, "tokens.txt")
        env = dict(os.environ, TGS_SETTINGS_LOCAL=lp, STATSPLUS_TOKEN_FILE=tok)
        script = os.path.join(INGEST, "statsplus_token.py")
        with open(tok, "w", encoding="utf-8", newline="") as f:
            f.write("TGS=\r\nBLM=\r\n")
        r1 = subprocess.run([sys.executable, script, "--have", "XY"], env=env, capture_output=True, text=True)
        with open(tok, "w", encoding="utf-8", newline="") as f:
            f.write(f"TGS=\r\nBLM=\r\nXYLEAGUE={FAKE_TOKEN}\r\n")
        r2 = subprocess.run([sys.executable, script, "--have", "XY"], env=env, capture_output=True, text=True)
        r3 = subprocess.run([sys.executable, script, "--have", "ZZ"], env=env, capture_output=True, text=True)
        self.assertEqual(r1.returncode, 1, r1.stdout + r1.stderr)
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertNotEqual(r3.returncode, 0)
        self.assertNotIn(FAKE_TOKEN, r2.stdout + r2.stderr)

    def test_disabled_tgs_stays_protected(self):
        out = run_py("import settings as ST, winsim, cleanup_clones as CC\n"
                     "print(json.dumps({'prot': sorted(winsim.PROTECTED), 'keep': sorted(CC.never_delete()), "
                     "'map': ST.slug_map(), 'saves': sorted(ST.league_saves()), "
                     "'masters': sorted(str(p['master']).lower() for p in winsim.load_profiles().values() "
                     "if p.get('master'))}))",
                     local={"leagues": {"TGS": {"enabled": False}}})
        self.assertIn("thegrandestsalami", out["prot"])
        self.assertEqual(out["map"], {"BLM": "blm"})
        for name in out["saves"] + out["masters"]:
            self.assertIn(name, out["keep"])
        self.assertEqual(set(out["keep"]), set(out["prot"]) | set(out["saves"]) | set(out["masters"]))

    def test_pending_league(self):
        local = {"leagues": {"XY": {"type": "statsplus", "name": "XY", "slug": "xy", "basis": "TGS",
                                    "ootp_version": "27", "ootp_save": "XY Save", "pending": True}}}
        out = run_py("import settings as ST\n"
                     "print(json.dumps({'in_list': 'XY' in ST.leagues(), 'any': ST.league('XY') is not None, "
                     "'slug': ST.slug('XY'), 'dir': ST.ootp_save_dir('XY'), 'map': 'XY' in ST.slug_map(), "
                     "'prot': 'xy save' in ST.protected_saves(), 'saves': 'xy save' in ST.league_saves(), "
                     "'all': 'XY' in ST.leagues(include_disabled=True), 'app': 'XY' in ST.app_config()['leagues']}))",
                     local=local)
        self.assertEqual(out["in_list"], False)
        self.assertEqual(out["any"], True)
        self.assertEqual(out["slug"], "xy")
        self.assertTrue(out["dir"].endswith("XY Save.lg"))
        self.assertEqual((out["map"], out["prot"], out["saves"], out["all"], out["app"]),
                         (False, True, True, True, False))

    def test_bad_values(self):
        bad = [{"leagues": {"CON": {"type": "dev", "name": "x"}}},
               {"leagues": {"xy": {"type": "dev", "name": "x"}}},
               {"leagues": {"XY": {"type": "statsplus", "name": "x", "slug": "tgs", "basis": "TGS"}}},
               {"leagues": {"XY": {"type": "local_export", "name": "x", "basis": "XX"}}},
               {"leagues": {"XY": {"type": "dev", "name": "x", "ootp_save": "..\\..\\x"}}},
               {"python": {"main": "python"}},
               {"ootp": {"installs": {"27": {"saved_games": ""}}}}]
        for local in bad:
            out = run_py("import settings as ST\n"
                         "try:\n    ST.load(); print(json.dumps('loaded'))\n"
                         "except ST.SettingsError as e:\n    print(json.dumps(str(e)))", local=local)
            self.assertNotEqual(out, "loaded", local)
            self.assertIn("settings.local.json", out)

    def test_write_local_round_trip(self):
        d = tempfile.mkdtemp(dir=TMP)
        lp = os.path.join(d, "settings.local.json")
        patch = os.path.join(d, "patch.json")
        env = dict(os.environ, TGS_SETTINGS_LOCAL=lp)
        cli = [sys.executable, os.path.join(TOOLS, "settings.py")]
        with open(patch, "w", encoding="utf-8") as f:
            json.dump({"leagues": {"BLM": {"my_org": "Tampa Bay Rays"}}}, f)
        r = subprocess.run(cli + ["set", "--patch-file", patch], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["merged"]["leagues"]["BLM"]["my_org"], "Tampa Bay Rays")
        with open(lp, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"leagues": {"BLM": {"my_org": "Tampa Bay Rays"}}})
        with open(patch, "w", encoding="utf-8") as f:
            json.dump({"leagues": {"BLM": {"slug": "Bad Slug"}}}, f)
        r = subprocess.run(cli + ["set", "--patch-file", patch], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["ok"])
        with open(lp, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"leagues": {"BLM": {"my_org": "Tampa Bay Rays"}}})
        r = subprocess.run(cli + ["get", "leagues.BLM.my_org"], env=env, capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout), "Tampa Bay Rays")
        r = subprocess.run(cli + ["validate"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual([f for f in os.listdir(d) if f.endswith(".tmp")], [])


class Manifest(unittest.TestCase):
    """leagues.json keeps its bytes (CRLF included)."""

    def setUp(self):
        self.copy = os.path.join(tempfile.mkdtemp(dir=TMP), "leagues.json")
        shutil.copyfile(os.path.join(VIZ, "public", "data", "leagues.json"), self.copy)
        with open(self.copy, "rb") as f:
            self.before = f.read()

    def test_register_manifest_dev(self):
        r = subprocess.run([sys.executable, os.path.join(TOOLS, "new_league.py"), "register-manifest",
                            "--league", "DEV", "--manifest", self.copy], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.copy, "rb") as f:
            self.assertEqual(f.read(), self.before)

    def test_upsert_unchanged(self):
        import extract_data as X
        X.upsert_manifest(self.copy, X.load_manifest_entries(self.copy))
        with open(self.copy, "rb") as f:
            self.assertEqual(f.read(), self.before)
        self.assertEqual([n for n in os.listdir(os.path.dirname(self.copy)) if n.endswith(".tmp")], [])
        self.assertTrue(X.remove_manifest_entry(self.copy, "RG"))
        self.assertNotIn("RG", {e["id"] for e in X.load_manifest_entries(self.copy)})
        self.assertFalse(X.remove_manifest_entry(self.copy, "RG"))


OLD_WRITE_JSON = '''
def write_json(records, path, overwrite):
    target = path if overwrite else path.replace(".json", "_engine.json")
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    return target
'''


class RefreshWrite(unittest.TestCase):
    """refresh.write_json: same bytes as the ef23800 code, a .bak- copy, no .tmp left."""

    def test_same_bytes(self):
        import refresh
        import time as _time
        old_ns = {"os": os, "shutil": shutil, "time": _time, "json": json}
        exec(OLD_WRITE_JSON, old_ns)
        recs = [{"ID": "1", "Name": "Zoë Ångström", "WAA": 1.25, "Price": None, "Pos": ["SS", "2B"]},
                {"ID": "2", "Name": "Plain", "WAA": -0.5}]
        for overwrite in (True, False):
            a, b = tempfile.mkdtemp(dir=TMP), tempfile.mkdtemp(dir=TMP)
            for d in (a, b):
                with open(os.path.join(d, "hitters.json"), "w", encoding="utf-8") as f:
                    f.write('[{"old": 1}]')
            ta = old_ns["write_json"](recs, os.path.join(a, "hitters.json"), overwrite)
            tb = refresh.write_json(recs, os.path.join(b, "hitters.json"), overwrite)
            self.assertEqual(os.path.basename(ta), os.path.basename(tb))
            with open(ta, "rb") as fa, open(tb, "rb") as fb:
                self.assertEqual(fa.read(), fb.read())
            names = sorted(os.listdir(b))
            self.assertFalse([n for n in names if n.endswith(".tmp")], names)
            baks = [n for n in names if n.startswith("hitters.json.bak-")]
            self.assertEqual(len(baks), 1 if overwrite else 0, names)
            if overwrite:
                with open(os.path.join(b, baks[0]), encoding="utf-8") as f:
                    self.assertEqual(f.read(), '[{"old": 1}]')


class ArchiveGuard(unittest.TestCase):
    def test_connect_guard(self):
        import ratings_db as RDB
        root = tempfile.mkdtemp(dir=TMP)
        os.makedirs(os.path.join(root, "vintages", "X"))
        with open(os.path.join(root, "vintages", "X", "_pulls.csv"), "w", encoding="utf-8") as f:
            f.write("pull_id,league\n")
        db = os.path.join(root, "ratings_history.db")
        os.environ.pop("RATINGS_DB_ALLOW_NEW", None)
        with self.assertRaises(SystemExit) as cm:
            RDB.connect(db)
        self.assertIn("ratings archive is missing", str(cm.exception))
        self.assertFalse(os.path.exists(db))
        os.environ["RATINGS_DB_ALLOW_NEW"] = "1"
        try:
            RDB.connect(db).close()
        finally:
            os.environ.pop("RATINGS_DB_ALLOW_NEW", None)
        self.assertTrue(os.path.exists(db))
        conn = RDB.connect(db)                      # it exists now: no guard
        conn.close()

    def test_forget_league(self):
        import ratings_db as RDB
        db = os.path.join(tempfile.mkdtemp(dir=TMP), "ratings_history.db")
        conn = RDB.connect(db)
        try:
            for lg, date in (("ZZ", "2026-01-01"), ("ZZ", "2026-02-01"), ("YY", "2026-01-01")):
                RDB.insert_pull(conn, lg, date, date + "T00:00:00", "live", [],
                                {"1": {"name": "A", "age": 20, "pos": "SS", "org": "1", "lev": "MLB"}})
            self.assertEqual(RDB.forget_league(conn, "ZZ"), 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pulls WHERE league='ZZ'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM pulls WHERE league='YY'").fetchone()[0], 1)
            self.assertEqual(RDB.forget_league(conn, "ZZ"), 0)
        finally:
            conn.close()


class TokenAge(unittest.TestCase):
    def test_token_age_writes_nothing(self):
        import statsplus_token as T
        d = tempfile.mkdtemp(dir=TMP)
        old = os.environ["STATSPLUS_TOKEN_FILE"]
        os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(d, "tokens.txt")
        try:
            with open(T.token_file(), "w", encoding="utf-8", newline="") as f:
                f.write(f"TGS={FAKE_TOKEN}\r\nBLM=\r\n")
            T._MEMO.clear()
            seen = T.seen_file()
            self.assertEqual(T.token_age("tgs"), {"days": None, "new": True})
            self.assertFalse(os.path.exists(seen))
            self.assertIsNone(T.token_age("blm"))
            T.saved_info("tgs")                        # the pull's own call: writes the first-seen entry
            st = os.stat(seen)
            with open(seen, "rb") as f:
                data = f.read()
            self.assertEqual(T.token_age("tgs"), {"days": 0})
            st2 = os.stat(seen)
            with open(seen, "rb") as f:
                self.assertEqual(f.read(), data)
            self.assertEqual((st.st_mtime_ns, st.st_size), (st2.st_mtime_ns, st2.st_size))
            self.assertNotIn(FAKE_TOKEN, data.decode("utf-8"))
        finally:
            os.environ["STATSPLUS_TOKEN_FILE"] = old
            T._MEMO.clear()


class PythonMainCases(unittest.TestCase):
    """The Python side of B's shared python.main cases."""

    def test_cases(self):
        if not os.path.isfile(CASES):
            raise unittest.SkipTest(f"{CASES} is missing (B's file)")
        with open(CASES, encoding="utf-8") as f:
            cases = json.load(f)
        for c in cases:
            d = tempfile.mkdtemp(dir=TMP)
            env = {}
            if c.get("defaults") is not None:
                dp = os.path.join(d, "settings.defaults.json")
                with open(dp, "w", encoding="utf-8") as f:
                    json.dump(c["defaults"], f)
                env["TEST_DEFAULTS"] = dp
            local = c.get("local")
            code = ("import settings as ST\n"
                    "if os.environ.get('TEST_DEFAULTS'): ST.DEFAULTS_PATH = os.environ['TEST_DEFAULTS']\n"
                    "try:\n    print(json.dumps(ST.interp('main')))\n"
                    "except ST.SettingsError:\n    print(json.dumps('SettingsError'))")
            if local is None:
                out = run_py(code, env=dict(env, TGS_SETTINGS_LOCAL=os.path.join(d, "missing.json")))
            else:
                out = run_py(code, local=local, env=env)
            want = c.get("expect_python", c["expect"])
            self.assertEqual(out, want, c["name"])


_BEFORE = {}


def setUpModule():
    # unittest discover imports every test module before it runs any; a later
    # module's import-time environment would leak into this one. Put this
    # module's back for its tests, and the previous one back after them.
    _BEFORE.clear()
    _BEFORE.update(os.environ)
    os.environ.clear()
    os.environ.update(_ENV)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)
    os.environ.clear()
    os.environ.update(_BEFORE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
