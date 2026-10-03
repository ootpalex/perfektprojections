"""
test_doctor_deep.py - `doctor.py --deep`: the per-league checks of doctor_deep.py.

    python tgs-viz/tools/tests/test_doctor_deep.py

Two layers:
  * in process, on a fixture tree built in a temp folder (calibration folder, app
    data folder, manifest): each check passes on clean data and names the problem,
    with its counts, on broken data. Sockets are blocked and the fixture tree is
    compared before and after, so the checks are shown to be offline and read-only.
  * as a child process like test_doctor.py: the default output has no deep rows,
    --deep only adds rows, and on the committed data of this checkout --deep adds
    no failing row.
"""
import copy
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
VIZ = os.path.dirname(TOOLS)
DOCTOR = os.path.join(TOOLS, "doctor.py")
TMP = tempfile.mkdtemp(prefix="tgs-doctor-deep-test-")
os.environ["TGS_SETTINGS_LOCAL"] = os.path.join(TMP, "no-local-settings.json")
os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(TMP, "tokens.txt")
for p in (TOOLS, os.path.join(VIZ, "ingest")):
    if p not in sys.path:
        sys.path.insert(0, p)
import doctor              # noqa: E402
import doctor_deep as DD   # noqa: E402
import metadata_inputs as MI   # noqa: E402
import parks as PK         # noqa: E402

CLUBS = ["Alpha Ants", "Beta Bees", "Gamma Geese"]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def put_json(path, obj):
    write(path, json.dumps(obj))


def csv_text(rows):
    return "".join(",".join(r) + "\r\n" for r in rows)


def good_hitter(i, org=None, lvl="1"):
    r = {k: "x" for k in DD.HITTER_REQUIRED}
    r.update(ID=str(i), ORG=org or CLUBS[i % 3], LgLvl=lvl)
    return r


def good_pitcher(i):
    r = {k: "x" for k in DD.PITCHER_REQUIRED}
    r.update(ID=str(i))
    return r


def metadata_csvs(folder):
    """The nine metadata_inputs CSVs with the right header row (banner, header, one data row)."""
    for fn, layout in DD._layouts(MI).items():
        hdr, offsets = layout[0]
        width = max(offsets) + len(hdr)
        row = [""] * width
        for off in offsets:
            row[off:off + len(hdr)] = hdr
        write(os.path.join(folder, fn), csv_text([["Player List"] + [""] * (width - 1), row, ["1"] + [""] * (width - 1)]))


def build_tree(root, league="BLM", season=2058):
    """calib/<league>/ + data/<league>/ + manifest entry for one clean league."""
    calib, data = os.path.join(root, "calib"), os.path.join(root, "data")
    cf = os.path.join(calib, league)
    for fn in ("constants-latest.json",) + DD.OPTIONAL_CALIB:
        put_json(os.path.join(cf, fn), {"home_team": CLUBS[0]} if fn == "park_blend.json" else {"a": 1})
    put_json(os.path.join(cf, "metadata-latest.json"), {"groups": {}, "cells": {"A1": 1, "A2": 2}})
    metadata_csvs(os.path.join(cf, "metadata_inputs"))
    put_json(os.path.join(cf, "metadata_inputs", "manifest.json"), {"league": league, "season": season})
    write(os.path.join(cf, "park_factors.csv"), csv_text([["Team", "Avg RHB"]] + [[c, "1.0"] for c in CLUBS]))
    put_json(os.path.join(data, league, "hitters.json"), [good_hitter(i) for i in range(6)])
    put_json(os.path.join(data, league, "pitchers.json"), [good_pitcher(i) for i in range(4)])
    entry = {"id": league, "datasets": ["hitters", "pitchers"]}
    return calib, data, entry


def tree_state(root):
    out = {}
    for dp, _dn, files in os.walk(root):
        for fn in files:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = f.read()
    return out


LG = {"id": "BLM", "type": "statsplus", "name": "BLM", "basis": "BLM", "my_org": "Alpha Ants",
      "my_team": "Alpha Ants", "ootp_version": "27", "ootp_save": "BLM"}


class Deep(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.calib, self.data, self.entry = build_tree(self.root)

    def run_deep(self, lg=None, entry="entry", leagues=None):
        d = doctor.Doctor(True)
        lg = lg or LG
        leagues = leagues or {lg["id"]: lg}
        man = [self.entry if entry == "entry" else entry] if entry else []
        before = tree_state(self.root)
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network used")):
            DD.check_deep(d, leagues, man, self.data, self.calib)
        self.assertEqual(tree_state(self.root), before)           # read-only
        return {r["id"]: r for r in d.rows}

    def test_clean_tree_is_all_ok(self):
        rows = self.run_deep()
        self.assertEqual(sorted(rows), [f"deep.BLM.{w}" for w in ("calib", "data", "metadata", "parks", "settings")])
        for r in rows.values():
            self.assertEqual(r["status"], "ok", r)
        self.assertIn("6 records have all 11 required keys", rows["deep.BLM.data"]["detail"])
        self.assertIn("4 records have all 9 required keys", rows["deep.BLM.data"]["detail"])
        self.assertIn("3 park rows match", rows["deep.BLM.parks"]["detail"])
        self.assertIn("2 cells", rows["deep.BLM.metadata"]["detail"])
        self.assertEqual(rows["deep.BLM.data"]["task"], "update.BLM")

    # ---- app data
    def test_records_missing_a_required_key_fail_with_counts(self):
        hs = [good_hitter(i) for i in range(6)]
        del hs[0]["Max WAA wtd"]
        del hs[1]["Max WAA wtd"]
        del hs[2]["ID"]
        put_json(os.path.join(self.data, "BLM", "hitters.json"), hs)
        r = self.run_deep()["deep.BLM.data"]
        self.assertEqual(r["status"], "fail")
        self.assertIn("Max WAA wtd missing in 2 of 6 records", r["detail"])
        self.assertIn("ID missing in 1 of 6 records", r["detail"])
        self.assertIn("Update BLM", r["fix"])

    def test_not_a_record_list_and_listed_dataset_missing(self):
        put_json(os.path.join(self.data, "BLM", "pitchers.json"), {"a": 1})
        self.entry["datasets"] = ["hitters", "pitchers", "hitters_draft"]
        r = self.run_deep()["deep.BLM.data"]
        self.assertEqual(r["status"], "fail")
        self.assertIn("pitchers.json is not a list of player records", r["detail"])
        self.assertIn("hitters_draft.json is listed in leagues.json but is not there", r["detail"])

    def test_manifest_basis_must_match_settings(self):
        lg = dict(LG, id="SSB", name="SSB")
        shutil.copytree(os.path.join(self.data, "BLM"), os.path.join(self.data, "SSB"))
        entry = {"id": "SSB", "datasets": ["hitters", "pitchers"], "basis": "TGS"}
        r = self.run_deep(lg, entry)["deep.SSB.data"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("leagues.json basis is TGS but the settings basis is BLM", r["detail"])
        entry["basis"] = "BLM"
        self.assertEqual(self.run_deep(lg, entry)["deep.SSB.data"]["status"], "ok")

    # ---- calibration
    def test_calibration(self):
        folder = os.path.join(self.calib, "BLM")
        os.remove(os.path.join(folder, "scurves.json"))
        r = self.run_deep()["deep.BLM.calib"]
        self.assertEqual(r["status"], "ok")                       # optional: the engine falls back
        self.assertIn("6 of 7 optional files", r["detail"])
        self.assertIn("scurves.json", r["detail"])
        write(os.path.join(folder, "currency.json"), "{broken")
        r = self.run_deep()["deep.BLM.calib"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("currency.json is not valid JSON", r["detail"])
        os.remove(os.path.join(folder, "constants-latest.json"))
        r = self.run_deep()["deep.BLM.calib"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("constants-latest.json is missing", r["detail"])

    def test_derived_league_reads_its_basis_calibration(self):
        lg = dict(LG, id="SSB", name="SSB")
        shutil.copytree(os.path.join(self.data, "BLM"), os.path.join(self.data, "SSB"))
        rows = self.run_deep(lg, {"id": "SSB", "datasets": ["hitters"], "basis": "BLM"})
        self.assertIn("engine/calib/BLM/", rows["deep.SSB.calib"]["detail"])
        self.assertEqual(rows["deep.SSB.parks"]["detail"], "no park file of its own (priced in a neutral park)")

    # ---- metadata inputs
    def test_metadata_header_and_files(self):
        mdir = os.path.join(self.calib, "BLM", "metadata_inputs")
        rows = list(csv.reader(open(os.path.join(mdir, "Hitting_Data.csv"), encoding="utf-8-sig")))
        rows[1][5], rows[1][6] = rows[1][6], rows[1][5]            # PA <-> AB
        write(os.path.join(mdir, "Hitting_Data.csv"), csv_text(rows))
        os.remove(os.path.join(mdir, "SP_Ratings.csv"))
        write(os.path.join(mdir, "Batter_Ratings.csv"), csv_text([["Player List"], ["ID", "POS"], ["1", "C"]]))
        r = self.run_deep()["deep.BLM.metadata"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("Hitting_Data.csv header does not match", r["detail"])
        self.assertIn("SP_Ratings.csv is missing", r["detail"])
        self.assertIn("Batter_Ratings.csv header does not match", r["detail"])
        self.assertIn("missing", r["detail"])

    def test_metadata_header_without_rows(self):
        mdir = os.path.join(self.calib, "BLM", "metadata_inputs")
        rows = list(csv.reader(open(os.path.join(mdir, "Pitching_Data.csv"), encoding="utf-8-sig")))[:2]
        write(os.path.join(mdir, "Pitching_Data.csv"), csv_text(rows))
        self.assertIn("Pitching_Data.csv has a header but no data rows", self.run_deep()["deep.BLM.metadata"]["detail"])

    def test_metadata_season_against_the_engine_boundary(self):
        for first, status in ((2058, "ok"), (2043, "ok"), (2059, "warn")):
            r = self.run_deep(dict(LG, engine_first_season=first))["deep.BLM.metadata"]
            self.assertEqual(r["status"], status, (first, r))
            if status == "warn":
                self.assertIn("season 2058, before this league's engine_first_season 2059", r["detail"])
        # a derived league prices on the basis league's metadata: its own boundary is not compared with it
        lg = dict(LG, id="SSB", name="SSB", engine_first_season=2059)
        shutil.copytree(os.path.join(self.data, "BLM"), os.path.join(self.data, "SSB"))
        self.assertEqual(self.run_deep(lg, {"id": "SSB", "datasets": ["hitters"], "basis": "BLM"})
                         ["deep.SSB.metadata"]["status"], "ok")

    def test_metadata_manifest_for_another_league(self):
        put_json(os.path.join(self.calib, "BLM", "metadata_inputs", "manifest.json"), {"league": "TGS", "season": 2058})
        self.assertIn("is for league TGS, not BLM", self.run_deep()["deep.BLM.metadata"]["detail"])

    # ---- parks
    def test_parks_against_the_clubs(self):
        hs = [good_hitter(i) for i in range(6)] + [good_hitter(7, org="Delta Ducks"), good_hitter(8, org="Zeta", lvl="4"),
                                                   good_hitter(9, org="0", lvl="1")]
        put_json(os.path.join(self.data, "BLM", "hitters.json"), hs)
        write(os.path.join(self.calib, "BLM", "park_factors.csv"),
              csv_text([["Team", "Avg RHB"], ["Alpha Ants", "1"], ["Beta Bees", "1"], ["Gamma Geese", "1"],
                        ["Omega Owls", "1"]]))
        r = self.run_deep()["deep.BLM.parks"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("clubs without a park row: Delta Ducks", r["detail"])      # Zeta is minor level, '0' is not a club
        self.assertIn("park rows without a club in hitters.json: Omega Owls", r["detail"])
        self.assertNotIn("Zeta", r["detail"])

    def test_parks_excluded_clubs_and_home_team(self):
        npb = sorted(PK.NPB)[0]
        shutil.copytree(os.path.join(self.data, "BLM"), os.path.join(self.data, "TGS"))
        lg = dict(LG, id="TGS", name="TGS", basis="TGS", my_team="Alpha Ants")
        shutil.copytree(os.path.join(self.calib, "BLM"), os.path.join(self.calib, "TGS"), dirs_exist_ok=True)
        write(os.path.join(self.calib, "TGS", "park_factors.csv"),
              csv_text([["Team", "Avg RHB"]] + [[c, "1"] for c in CLUBS + [npb]]))
        put_json(os.path.join(self.calib, "TGS", "park_blend.json"), {"home_team": "Beta Bees"})
        r = self.run_deep(lg, {"id": "TGS", "datasets": ["hitters"]})["deep.TGS.parks"]
        self.assertEqual(r["status"], "warn")
        self.assertNotIn(npb, r["detail"])                                          # NPB clubs have no hitters: excluded
        self.assertIn("park_blend.json was built for 'Beta Bees', my_team is 'Alpha Ants'", r["detail"])
        lg["my_team"] = "Nowhere"
        self.assertIn("my_team 'Nowhere' is not in park_factors.csv", self.run_deep(lg, {"id": "TGS", "datasets": ["hitters"]})["deep.TGS.parks"]["detail"])

    # ---- settings fields
    def test_settings_rows(self):
        profiles = {}
        s = lambda lid, **kw: DD.settings_row(lid, dict(kw), profiles)
        self.assertEqual(s("RG", type="local_export", ootp_version="27", ootp_save="RG", basis="BLM")[0], "ok")
        st, detail, _ = s("RG", type="local_export", ootp_version="27")
        self.assertEqual(st, "warn")
        self.assertIn("ootp_save is not set", detail)
        self.assertIn("basis is not set", detail)
        st, detail, _ = s("DEV", type="dev", ootp_version="27", ootp_save="D")
        self.assertIn("no OOTP profile", detail)
        self.assertEqual(DD.settings_row("DEV", {"type": "dev", "ootp_version": "27", "ootp_save": "D"}, {"DEV": {}})[0], "ok")
        st, detail, _ = s("XX", type="statsplus", my_org="A", ootp_save="Save")
        self.assertIn("ootp_save is set without ootp_version", detail)
        self.assertIn("my_org is empty", s("XX", type="statsplus")[1])
        st, detail, _ = s("BLM", type="statsplus", my_org="A", ootp_version="27", ootp_save="B",
                           engine_first_season=2043)
        self.assertEqual((st, detail), ("ok", "type statsplus; engine boundary: season 2043 on OOTP 27"))

    # ---- scope
    def test_clone_leagues_and_trends_only_leagues(self):
        dev = {"id": "DEV", "type": "dev", "name": "Dev", "ootp_version": "27", "ootp_save": "D"}
        clone = {"id": "CL", "type": "clone", "name": "Clone"}
        with mock.patch.object(DD, "settings_row", return_value=("ok", "", "")) as sr:
            rows = self.run_deep(leagues={"DEV": dev, "CL": clone}, entry=None)
        self.assertEqual(sorted(rows), ["deep.DEV.settings"])
        self.assertEqual(sr.call_count, 1)


class Cli(unittest.TestCase):
    """doctor.py as a child process, the way test_doctor.py runs it."""

    def run_doctor(self, *args, local=None):
        d = tempfile.mkdtemp(dir=TMP)
        e = dict(os.environ)
        e.update(TGS_SETTINGS_LOCAL=os.path.join(d, "settings.local.json"),
                 STATSPLUS_TOKEN_FILE=os.path.join(d, "StatsPlus Tokens.txt"),
                 TGS_CONTROL_DIR=os.path.join(d, "control"))
        e.pop("TGS_JOB_ID", None)
        if local is not None:
            write(e["TGS_SETTINGS_LOCAL"], json.dumps(local))
        p = subprocess.run([sys.executable, DOCTOR] + list(args), capture_output=True, text=True, env=e, timeout=120)
        return p

    def test_default_has_no_deep_rows_and_deep_only_adds_rows(self):
        plain = self.run_doctor("--json")
        deep = self.run_doctor("--deep", "--json")
        pr, dr = json.loads(plain.stdout)["checks"], json.loads(deep.stdout)["checks"]
        self.assertFalse([r for r in pr if r["id"].startswith("deep.")])
        extra = [r for r in dr if r["id"].startswith("deep.")]
        self.assertEqual([r for r in dr if not r["id"].startswith("deep.")], pr)       # nothing else differs
        ids = {r["id"] for r in extra}
        for lid in ("TGS", "BLM", "RG"):
            for what in ("settings", "calib", "metadata", "data", "parks"):
                self.assertIn(f"deep.{lid}.{what}", ids)
        self.assertEqual(ids & {"deep.DEV.data", "deep.DEV.parks"}, set())
        # on this checkout's committed data the deep rows add no failure
        self.assertEqual([r["id"] for r in extra if r["status"] == "fail"], [])
        self.assertEqual(plain.returncode, deep.returncode)
        for r in extra:
            self.assertEqual(set(r), {"id", "title", "status", "detail", "fix", "task"})

    def test_text_output_and_disabled_leagues(self):
        p = self.run_doctor("--deep", local={"leagues": {"BLM": {"enabled": False}}})
        self.assertIn("TGS: calibration files:", p.stdout)
        self.assertNotIn("BLM: calibration files", p.stdout)
        self.assertRegex(p.stdout.strip().splitlines()[-1], r"^Setup check: \d+ problems, \d+ warnings\.$")

    def test_boundary_shows_in_deep_rows(self):
        p = self.run_doctor("--deep", "--json", local={"leagues": {"BLM": {"engine_first_season": 2059}}})
        rows = {r["id"]: r for r in json.loads(p.stdout)["checks"]}
        self.assertIn("engine boundary: season 2059", rows["deep.BLM.settings"]["detail"])
        self.assertEqual(rows["deep.BLM.metadata"]["status"], "warn")
        self.assertIn("before this league's engine_first_season 2059", rows["deep.BLM.metadata"]["detail"])

    def test_bad_boundary_value_is_a_settings_failure(self):
        p = self.run_doctor("--deep", "--json", local={"leagues": {"BLM": {"engine_first_season": "2043"}}})
        rows = {r["id"]: r for r in json.loads(p.stdout)["checks"]}
        self.assertEqual(rows["settings"]["status"], "fail")
        self.assertIn("leagues.BLM.engine_first_season", rows["settings"]["detail"])
        self.assertFalse([k for k in rows if k.startswith("deep.")])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
