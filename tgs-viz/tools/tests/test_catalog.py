"""Catalog shape test (DESIGN.md 3.4, 15.1 step 3).

  python tgs-viz\\tools\\tests\\test_catalog.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(TOOLS))
RUN = os.path.join(TOOLS, "run_task.py")
PY = sys.executable

TASK_FIELDS = ("id", "title", "description", "group", "leagues", "bat", "flags", "locks", "time", "inputs",
               "stop_modes", "steps")
FLAG_NAMES = ("writes_app_data", "heavy", "long", "endless", "drives_ootp", "needs_ootp_closed", "needs_excel_closed",
              "network", "secret_inputs", "hidden", "read_only", "needs_archive")
STEP_FIELDS = ("id", "title", "writes_app_data", "data", "app_leagues", "argv")
INPUT_TYPES = ("choice", "text", "secret", "confirm")
BAT_TASKS = ["get_ratings", "get_history", "bank_season", "bank_dev", "grind_tgs", "grind_blm", "recalibrate_tgs",
             "recalibrate_blm", "sim_dev", "sync_metadata", "dispersal_board", "draft_board", "update.RG",
             "ootp_check_26", "ootp_grab_menu_26", "sim_tgs_preview", "sim_tgs", "ootp_test_year_26"]
NO_BAT_TASKS = ["retrain_ml", "retrain_ml.TGS", "retrain_ml.BLM", "dev_rescore", "bank_market_fit", "iafa_board",
                "parks_update", "pull_report", "cleanup_clones.TGS", "cleanup_clones.BLM", "sim_blm_preview",
                "token_check", "token_set", "restore_ratings_db", "doctor", "winsim_games", "dev_test_load",
                "dev_test_year", "new_league", "new_league_cleanup"]


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tgs-catalog-test-")
        cls.token_file = os.path.join(cls.tmp, "tokens", "StatsPlus Tokens.txt")
        cls.env = dict(os.environ, STATSPLUS_TOKEN_FILE=cls.token_file,
                       TGS_SETTINGS_LOCAL=os.path.join(cls.tmp, "settings.local.json"),
                       TGS_CONTROL_DIR=os.path.join(cls.tmp, "control"))
        cls.env.pop("TGS_SELFTEST", None)

    def list_json(self, *extra, env=None):
        t0 = time.time()
        cp = subprocess.run([PY, RUN, "--list-json", *extra], cwd=REPO, env=env or self.env, capture_output=True,
                            text=True, encoding="utf-8")
        secs = time.time() - t0
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout), secs

    def test_shape(self):
        cat, secs = self.list_json()
        self.assertLess(secs, 2.0, f"--list-json took {secs:.2f} s")
        self.assertEqual(cat["schema"], 1)
        for key in ("generated", "groups", "tasks", "leagues", "state", "app_config"):
            self.assertIn(key, cat)
        ids = [t["id"] for t in cat["tasks"]]
        self.assertEqual(len(ids), len(set(ids)), "task ids are not unique")
        groups = {g["id"] for g in cat["groups"]}
        self.assertNotIn("selftest", groups)
        for t in cat["tasks"]:
            for f in TASK_FIELDS:
                self.assertIn(f, t, f"{t['id']} has no {f}")
            self.assertRegex(t["id"], r"^[A-Za-z0-9_.-]+$")
            self.assertIn(t["group"], groups, t["id"])
            self.assertEqual(sorted(t["flags"]), sorted(FLAG_NAMES), t["id"])
            self.assertTrue(t["description"].strip(), t["id"])
            self.assertTrue(t["time"].strip(), t["id"])
            self.assertNotIn("—", t["description"] + t["title"] + t["time"], t["id"])
            for i in t["inputs"]:
                self.assertIn(i["type"], INPUT_TYPES, t["id"])
            for s in t["steps"]:
                for f in STEP_FIELDS:
                    self.assertIn(f, s, f"{t['id']}.{s.get('id')} has no {f}")
                if s["argv"] is not None:
                    self.assertTrue(all(isinstance(a, str) for a in s["argv"]))
            self.assertIn("kill", t["stop_modes"])
            if t["flags"]["endless"]:
                self.assertIn("after_cycle", t["stop_modes"])
        self.assertFalse(any(i.startswith("selftest.") for i in ids))
        # 18 bat tasks, update.TGS/BLM/DEV and the 4.6 tasks: 41 (16 step 2)
        want = BAT_TASKS + ["update.TGS", "update.BLM", "update.DEV"] + NO_BAT_TASKS
        self.assertEqual(sorted(ids), sorted(want))
        self.assertEqual(len(ids), 41)
        by = {t["id"]: t for t in cat["tasks"]}
        for tid in ("new_league", "new_league_cleanup"):
            self.assertTrue(by[tid]["flags"]["hidden"], tid)
        self.assertEqual(by["restore_ratings_db"]["flags"]["hidden"], cat["state"]["ratings_db_exists"])
        for tid in BAT_TASKS:
            self.assertTrue(by[tid]["bat"], tid)
        # steps never show a secret marker or a secret value
        text = json.dumps(cat)
        self.assertNotIn("@secret", text)
        self.assertNotIn("@cookie", text)

    def test_locks_table(self):
        """DESIGN.md 4.10: whole-run locks, when the data lock is taken, read_only, needs_archive."""
        first, cycle, after_winsim, never = "first", "cycle", "after_winsim", "never"
        table = {
            ("get_ratings", "get_history", "update.TGS", "update.BLM", "update.RG"): ([], first, False, True),
            ("bank_season", "sync_metadata", "dispersal_board", "draft_board", "iafa_board", "bank_market_fit"):
                ([], first, False, False),
            ("parks_update", "dev_rescore", "retrain_ml.TGS"): ([], first, False, True),
            # retrain_ml and retrain_ml.BLM rerun dev_odds, which reads the DEV dump folder
            ("bank_dev", "update.DEV", "retrain_ml", "retrain_ml.BLM"): (["dumps.DEV"], first, False, True),
            ("grind_tgs",): (["clones.TGS", "ootp"], cycle, False, True),
            ("grind_blm",): (["clones.BLM", "ootp"], cycle, False, True),
            ("recalibrate_tgs",): (["clones.TGS"], first, False, True),
            ("recalibrate_blm",): (["clones.BLM"], first, False, True),
            ("cleanup_clones.TGS",): (["clones.TGS"], never, False, False),
            ("cleanup_clones.BLM",): (["clones.BLM"], never, False, False),
            ("sim_tgs",): (["clones.TGS", "ootp"], never, False, False),
            ("sim_dev",): (["dumps.DEV", "ootp"], after_winsim, False, True),
            ("ootp_check_26", "ootp_grab_menu_26", "ootp_test_year_26", "dev_test_load", "dev_test_year"):
                (["ootp"], never, False, False),
            ("token_set",): ([], never, False, False),
            ("restore_ratings_db",): ([], first, False, False),
            ("new_league", "new_league_cleanup"): ([], None, False, True),
            ("pull_report", "doctor", "token_check", "winsim_games", "sim_tgs_preview", "sim_blm_preview"):
                (None, never, True, False),
        }
        cat, _ = self.list_json()
        by = {t["id"]: t for t in cat["tasks"]}
        covered = set()
        for ids, (locks, data, ro, archive) in table.items():
            for tid in ids:
                covered.add(tid)
                t = by[tid]
                self.assertEqual(t["flags"]["read_only"], ro, tid)
                self.assertEqual(t["flags"]["needs_archive"], archive, tid)
                if ro:
                    self.assertEqual(t["locks"], [], tid)
                else:
                    self.assertEqual(t["locks"], [f"task.{tid}"] + locks, tid)
                runs = [s for s in t["steps"] if s["kind"] in ("run", "probe", "exists_check", "excel_check", "gate")]
                if data == never:
                    self.assertFalse(any(s["data"] for s in t["steps"]), tid)
                elif data == first:
                    self.assertTrue(runs[0]["data"], tid)
                elif data == cycle:
                    self.assertEqual([s["id"] for s in runs if not s["data"]], ["winsim", "cleanup"], tid)
                elif data == after_winsim:
                    self.assertFalse(runs[0]["data"], tid)
                    self.assertTrue(all(s["data"] for s in runs[1:]), tid)
        self.assertEqual(covered, set(by), "every task is in the 4.10 table")

    def test_retrain_cards_price_dev_first(self):
        """A retrain card first prices DEV on its basis with Bank Dev Seasons' own
        commands. A BLM re-price reruns the odds and the dev signals of every
        league before the training rows; an extra league gets rows, then a score."""
        cat, _ = self.list_json()
        by = {t["id"]: t for t in cat["tasks"]}

        def argv(tid):
            return {s["id"]: s["argv"] for s in by[tid]["steps"] if s["argv"]}

        def order(tid):
            return [s["id"] for s in by[tid]["steps"] if s["argv"]]

        bank = argv("bank_dev")
        shown = sorted(lg["id"] for lg in cat["leagues"] if lg["id"] != "DEV")      # TGS, BLM, RG
        tgs, blm, both = order("retrain_ml.TGS"), order("retrain_ml.BLM"), order("retrain_ml")
        self.assertEqual(tgs[:2], ["reprice", "ml_dataset"])
        self.assertEqual(blm[:3], ["dev_value", "dev_odds", "dev_rating_odds"])
        self.assertEqual(both[:4], ["dev_value", "reprice", "dev_odds", "dev_rating_odds"])
        for tid in ("retrain_ml.TGS", "retrain_ml.BLM", "retrain_ml"):
            for sid, a in argv(tid).items():
                if sid in ("dev_value", "reprice", "dev_odds", "dev_rating_odds"):
                    self.assertEqual(a, bank[sid], f"{tid}.{sid}")
        for tid, ids, first_ml in (("retrain_ml.BLM", blm, "ml_dataset"), ("retrain_ml", both, "tgs_ml_dataset")):
            sig = [s for s in ids if s.endswith("_devsignals")]
            self.assertEqual(sorted(s.split("_")[0].upper() for s in sig), shown, tid)
            self.assertLess(max(ids.index(s) for s in sig), ids.index(first_ml), tid)
            self.assertLess(ids.index("rg_ml_rows"), ids.index("rg_ml_score"), tid)
        self.assertNotIn("dev_odds", tgs)
        self.assertFalse(any(s.startswith("rg_") for s in tgs))

    def test_state_and_leagues(self):
        cat, _ = self.list_json()
        st = cat["state"]
        for key in ("tokens", "ootp_installs", "ratings_db_exists", "settings_local", "settings_error", "watch_files"):
            self.assertIn(key, st)
        self.assertIsNone(st["settings_error"])
        self.assertEqual(sorted(st["tokens"]), ["BLM", "TGS"])
        self.assertEqual(st["tokens"], {"TGS": False, "BLM": False})
        self.assertEqual(len(st["watch_files"]), 5)
        lg = {x["id"]: x for x in cat["leagues"]}
        self.assertEqual(sorted(lg), ["BLM", "DEV", "RG", "TGS"])
        self.assertEqual(lg["TGS"]["token_line"], "TGS=")
        self.assertEqual(lg["RG"]["update_task"], "update.RG")
        self.assertFalse(any(x["added_by_wizard"] for x in lg.values()))
        self.assertTrue(all(x["in_app"] for x in lg.values()))
        self.assertEqual(cat["app_config"]["leagues"]["TGS"]["my_org"], "Chicago Cubs")

    def test_no_token_file_created(self):
        self.assertFalse(os.path.exists(self.token_file))
        self.list_json()
        self.assertFalse(os.path.exists(self.token_file))
        self.assertFalse(os.path.exists(os.path.dirname(self.token_file)))

    def test_selftest_flag(self):
        cat, _ = self.list_json("--selftest")
        ids = [t["id"] for t in cat["tasks"]]
        self.assertIn("selftest.ok", ids)
        self.assertIn("selftest", {g["id"] for g in cat["groups"]})
        env = dict(self.env, TGS_SELFTEST="1")
        cat2, _ = self.list_json(env=env)
        self.assertIn("selftest.long", [t["id"] for t in cat2["tasks"]])

    def test_bad_settings(self):
        bad = os.path.join(self.tmp, "bad.local.json")
        with open(bad, "w") as f:
            f.write("{bad")
        cat, _ = self.list_json(env=dict(self.env, TGS_SETTINGS_LOCAL=bad))
        self.assertEqual([t["id"] for t in cat["tasks"]], ["doctor"])
        self.assertEqual(cat["leagues"], [])
        self.assertTrue(cat["state"]["settings_error"])
        self.assertIn("bad.local.json", cat["state"]["settings_error"])

    def test_disabled_league_hides_its_tasks(self):
        loc = os.path.join(self.tmp, "off.local.json")
        with open(loc, "w") as f:
            json.dump({"leagues": {"RG": {"enabled": False}}}, f)
        cat, _ = self.list_json(env=dict(self.env, TGS_SETTINGS_LOCAL=loc))
        ids = [t["id"] for t in cat["tasks"]]
        self.assertNotIn("update.RG", ids)
        rg = next(x for x in cat["leagues"] if x["id"] == "RG")
        self.assertFalse(rg["enabled"])
        self.assertIsNone(rg["update_task"])

    def test_no_heavy_imports(self):
        code = (f"import sys; sys.path.insert(0, {TOOLS!r}); import run_task; run_task.catalog(False); "
                "bad = [m for m in ('winsim', 'numpy', 'openpyxl', 'statsplus') if m in sys.modules]; "
                "print(','.join(bad))")
        cp = subprocess.run([PY, "-c", code], cwd=REPO, env=self.env, capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
