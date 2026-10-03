"""
test_roster_export.py - ingest/roster_export.py (the OOTP org export merged into a pull by player
ID) and the roster_export setting in tools/settings.py.

    python tgs-viz/tools/tests/test_roster_export.py
    python -m pytest tgs-viz/tools/tests/test_roster_export.py -q

Offline. The fixture org_trim.csv is 11 real rows of the SSB org.csv (fictional players, the full
185-column header). Writes only to a temp folder.
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VIZ = os.path.dirname(TOOLS)
INGEST = os.path.join(VIZ, "ingest")
FIXTURE = os.path.join(HERE, "fixtures", "roster_export", "org_trim.csv")

TMP = tempfile.mkdtemp(prefix="tgs-roster-export-test-")
os.environ["TGS_SETTINGS_LOCAL"] = os.path.join(TMP, "settings.local.json")
os.environ["TGS_ROSTER_TEST_DIR"] = TMP       # a defined %VAR% for the path cases
os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(TMP, "tokens", "StatsPlus Tokens.txt")
for p in (TOOLS, INGEST):
    if p not in sys.path:
        sys.path.insert(0, p)

import roster_export as RX  # noqa: E402
import settings as ST       # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def write(name, text, bom=False):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as fh:
        fh.write(text)
    return path


def records():
    """(hitters, pitchers) as a pull would hold them, names as the pull spells them."""
    hit = [{"ID": "64113", "Name": "Chad Able"}, {"ID": "65651", "Name": "Jeff Abramov"},
           {"ID": "73672", "Name": "Leonardo Acenedo"}, {"ID": "70667", "Name": "Eddie Abanto"},
           {"ID": "59213", "Name": "Joel Barnes"},
           {"ID": "1", "Name": "Not In The Export"}]
    pit = [{"ID": "64046", "Name": "Patrick Acevedo"}, {"ID": "63243", "Name": "Phil Phelps"},
           {"ID": "71285", "Name": "Somebody Else"},          # same ID as the export, other name
           {"ID": "61665", "Name": "Edwin Alcantar"}, {"ID": "72354", "Name": "Jose Segui"},
           {"ID": "64759", "Name": "Aaron Brown"}]
    return hit, pit


class ParseDate(unittest.TestCase):
    def test_ootp_transaction_dates(self):
        import datetime
        self.assertEqual(RX.parse_txn_date("Dec. 28th   2043"), datetime.date(2043, 12, 28))
        self.assertEqual(RX.parse_txn_date("Jan. 7th   2041"), datetime.date(2041, 1, 7))
        self.assertEqual(RX.parse_txn_date("Jun. 2nd   2042"), datetime.date(2042, 6, 2))
        self.assertEqual(RX.parse_txn_date("Sep. 3rd   2040"), datetime.date(2040, 9, 3))

    def test_not_a_date(self):
        for bad in ("", "-", None, "Dec. 28th", "Foo. 3rd   2040", "Feb. 30th   2040"):
            self.assertIsNone(RX.parse_txn_date(bad), bad)

    def test_gap_days(self):
        self.assertEqual(RX.gap_days("2044-05-02", "2043-12-28"), 126)
        self.assertEqual(RX.gap_days("2043-12-28", "2043-12-28"), 0)
        self.assertEqual(RX.gap_days("2043-12-20", "2043-12-28"), -8)
        self.assertIsNone(RX.gap_days(None, "2043-12-28"))
        self.assertIsNone(RX.gap_days("2044-05-02", None))
        self.assertIsNone(RX.gap_days("garbage", "2043-12-28"))


class Load(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ex = RX.load_export(FIXTURE)

    def test_rows_and_date(self):
        self.assertEqual(len(self.ex["rows"]), 11)
        self.assertEqual(self.ex["duplicates"], 0)
        self.assertEqual(self.ex["missing_columns"], [])
        self.assertEqual(self.ex["as_of"], "2043-12-28")     # Jose Segui, the newest transaction

    def test_mlb_arbitration_player(self):
        f = self.ex["rows"]["64113"]["fields"]               # Chad Able
        self.assertEqual(f["ContractStatus"], "1 (arbitr.)")
        self.assertIs(f["On40Man"], True)
        self.assertIs(f["ActiveRoster"], True)
        self.assertEqual(f["OptionsUsed"], 0)                # a real 0 is kept, not dropped
        self.assertEqual(f["OptionYearUsed"], 0)
        self.assertIs(f["Rule5Eligible"], False)
        self.assertIs(f["RookieStatus"], False)
        self.assertIs(f["IntlComplex"], False)               # '-' is No
        self.assertEqual(f["SignDifficulty"], "Normal")
        self.assertEqual(f["LastTransaction"], "Rule 5 Draft pick")
        self.assertEqual(f["LastTransactionDate"], "2041-01-07")
        self.assertNotIn("FAType", f)                        # '-' says nothing
        self.assertNotIn("ContractDemand", f)

    def test_options_and_option_year(self):
        self.assertEqual(self.ex["rows"]["59213"]["fields"]["OptionsUsed"], 2)      # Joel Barnes
        self.assertEqual(self.ex["rows"]["59213"]["fields"]["OptionYearUsed"], 2)
        self.assertEqual(self.ex["rows"]["64759"]["fields"]["OptionsUsed"], 1)      # Aaron Brown
        self.assertEqual(self.ex["rows"]["64759"]["fields"]["OptionYearUsed"], 3)

    def test_international_complex_and_rule5(self):
        f = self.ex["rows"]["73672"]["fields"]                                       # Acenedo, INT
        self.assertIs(f["IntlComplex"], True)
        self.assertIs(f["On40Man"], False)
        self.assertIs(f["ActiveRoster"], False)
        self.assertIs(self.ex["rows"]["64046"]["fields"]["Rule5Eligible"], True)     # Acevedo

    def test_demand(self):
        self.assertEqual(self.ex["rows"]["61665"]["fields"]["ContractDemand"], "$5.8m")

    def test_only_listed_keys(self):
        allowed = {k for _, k, _ in RX.FIELDS}
        for row in self.ex["rows"].values():
            self.assertLessEqual(set(row["fields"]), allowed)

    def test_bom_first_duplicate_header_and_short_row(self):
        text = ("ID,Name,OPT,OPT,ON40\n"
                "7,Ann Lee,2,3,Yes\n"
                "8,Bo Day,1\n"                    # short row: the cells it lacks are unknown
                ",Nobody,1,1,Yes\n"               # no ID: skipped
                "7,Ann Lee,9,9,No\n")             # duplicate ID: first wins
        ex = RX.load_export(write("dup.csv", text, bom=True))
        self.assertEqual(sorted(ex["rows"]), ["7", "8"])
        self.assertEqual(ex["duplicates"], 1)
        self.assertEqual(ex["rows"]["7"]["fields"], {"On40Man": True, "OptionsUsed": 2})
        self.assertEqual(ex["rows"]["8"]["fields"], {"OptionsUsed": 1})
        self.assertEqual(ex["missing_columns"], [c for c, _, _ in RX.FIELDS if c not in ("OPT", "ON40")])
        self.assertIsNone(ex["as_of"])

    def test_not_an_org_export(self):
        with self.assertRaises(RX.RosterExportError):
            RX.load_export(write("nocols.csv", "Foo,Bar\n1,2\n"))
        with self.assertRaises(RX.RosterExportError):
            RX.load_export(write("empty.csv", ""))
        with self.assertRaises(RX.RosterExportError):
            RX.load_export(os.path.join(TMP, "does-not-exist.csv"))


class Merge(unittest.TestCase):
    def setUp(self):
        self.ex = RX.load_export(FIXTURE)
        self.hit, self.pit = records()

    def test_keys_land_on_matched_records_only(self):
        rep = RX.merge([self.hit, self.pit], self.ex, pull_game_date="2044-05-02")
        able = self.hit[0]
        self.assertEqual(able["ContractStatus"], "1 (arbitr.)")
        self.assertIs(able["On40Man"], True)
        self.assertEqual(able["OptionsUsed"], 0)
        self.assertEqual(able["RosterExportDate"], "2043-12-28")
        self.assertEqual(able["RosterExportGapDays"], 126)
        self.assertEqual(self.hit[-1], {"ID": "1", "Name": "Not In The Export"})   # unknown stays unknown
        # 5 of 6 hitters and 5 of 6 pitchers match (one name differs among the pitchers)
        self.assertEqual(rep["lists"], [{"records": 6, "matched": 5}, {"records": 6, "matched": 5}])
        self.assertEqual(rep["matched"], 10)
        self.assertEqual(rep["name_mismatch"], 1)
        self.assertEqual(rep["export_only"], 1)            # Josh Abbe's row has no matching record
        self.assertNotIn("On40Man", self.pit[2])           # the mismatched-name record got nothing

    def test_name_match_ignores_case(self):
        RX.merge([self.hit, self.pit], self.ex)
        phelps = self.pit[1]                                # export spells it PHIL PHELPS
        self.assertEqual(phelps["OptionsUsed"], 2)
        self.assertIs(phelps["RookieStatus"], True)

    def test_key_counts(self):
        rep = RX.merge([self.hit, self.pit], self.ex, pull_game_date="2044-05-02")
        k = rep["keys_added"]
        self.assertEqual(k["OptionsUsed"], 10)
        self.assertEqual(k["On40Man"], 10)
        self.assertEqual(k["RosterExportDate"], 10)
        self.assertEqual(k["RosterExportGapDays"], 10)
        self.assertEqual(k["IntlComplex"], 10)
        self.assertEqual(k["ContractDemand"], 1)           # only Edwin Alcantar has a demand
        self.assertNotIn("FAType", k)

    def test_never_overwrites_an_existing_key(self):
        self.hit[0]["On40Man"] = "from-somewhere-else"
        self.hit[0]["RosterExportDate"] = "keep"
        rep = RX.merge([self.hit, self.pit], self.ex, pull_game_date="2044-05-02")
        self.assertEqual(self.hit[0]["On40Man"], "from-somewhere-else")
        self.assertEqual(self.hit[0]["RosterExportDate"], "keep")
        self.assertEqual(self.hit[0]["OptionsUsed"], 0)    # the other keys still arrive
        self.assertEqual(rep["kept_existing"], {"On40Man": 1})

    def test_existing_record_values_unchanged(self):
        before = copy.deepcopy((self.hit, self.pit))
        RX.merge([self.hit, self.pit], self.ex)
        for old, new in zip(before[0] + before[1], self.hit + self.pit):
            for k, v in old.items():
                self.assertEqual(new[k], v)
            self.assertLessEqual(set(new) - set(old), set(RX.KEYS))

    def test_mirrors_get_the_same_keys_without_counting(self):
        mh, mp = copy.deepcopy(self.hit), copy.deepcopy(self.pit)
        rep = RX.merge([self.hit, self.pit], self.ex, mirrors=[mh, mp])
        self.assertEqual(mh[1]["OptionsUsed"], 2)
        self.assertEqual(rep["keys_added"]["OptionsUsed"], 10)     # not 20
        self.assertEqual(rep["mirror_records"], 12)

    def test_gap_and_stale(self):
        rep = RX.merge([self.hit, self.pit], self.ex, pull_game_date="2044-05-02")
        self.assertEqual((rep["gap_days"], rep["stale"]), (126, True))
        rep = RX.merge(list(records()), self.ex, pull_game_date="2044-01-11")
        self.assertEqual((rep["gap_days"], rep["stale"]), (14, False))     # 14 is not over 14
        rep = RX.merge(list(records()), self.ex, pull_game_date="2044-01-12")
        self.assertEqual((rep["gap_days"], rep["stale"]), (15, True))

    def test_no_pull_date_means_no_gap_key(self):
        RX.merge([self.hit, self.pit], self.ex)
        self.assertEqual(self.hit[0]["RosterExportDate"], "2043-12-28")
        self.assertNotIn("RosterExportGapDays", self.hit[0])

    def test_export_without_any_date(self):
        ex = RX.load_export(write("nodate.csv", "ID,Name,OPT\n64113,Chad Able,1\n"))
        rep = RX.merge([self.hit, self.pit], ex, pull_game_date="2044-05-02")
        self.assertEqual(self.hit[0]["OptionsUsed"], 1)
        self.assertNotIn("RosterExportDate", self.hit[0])
        self.assertNotIn("RosterExportGapDays", self.hit[0])
        self.assertIsNone(rep["gap_days"])
        self.assertFalse(rep["stale"])

    def test_another_leagues_file_is_refused_and_nothing_changes(self):
        lines = ["ID,Name,OPT"] + [f"{i},Other Player {i},1" for i in range(1, 251)]
        ex = RX.load_export(write("other.csv", "\n".join(lines) + "\n"))
        recs = [{"ID": str(i), "Name": f"Real Player {i}"} for i in range(1, 251)]
        before = copy.deepcopy(recs)
        with self.assertRaises(RX.RosterExportError):
            RX.merge([recs], ex)
        self.assertEqual(recs, before)

    def test_same_ids_same_names_pass_the_guard(self):
        lines = ["ID,Name,OPT"] + [f"{i},Player {i},2" for i in range(1, 251)]
        ex = RX.load_export(write("same.csv", "\n".join(lines) + "\n"))
        recs = [{"ID": str(i), "Name": f"player {i}"} for i in range(1, 251)]
        rep = RX.merge([recs], ex)
        self.assertEqual(rep["matched"], 250)
        self.assertEqual(recs[0]["OptionsUsed"], 2)

    def test_guard_needs_200_joined_rows(self):
        lines = ["ID,Name,OPT"] + [f"{i},Other {i},1" for i in range(1, 51)]
        ex = RX.load_export(write("small.csv", "\n".join(lines) + "\n"))
        recs = [{"ID": str(i), "Name": f"Real {i}"} for i in range(1, 51)]
        rep = RX.merge([recs], ex)                          # too few to judge: rows skipped by name
        self.assertEqual((rep["matched"], rep["name_mismatch"]), (0, 50))
        self.assertNotIn("OptionsUsed", recs[0])


class Apply(unittest.TestCase):
    def setUp(self):
        self.hit, self.pit = records()
        self.log = []

    def test_off_when_not_configured(self):
        before = copy.deepcopy((self.hit, self.pit))
        orig = RX.configured_path
        RX.configured_path = lambda league: None
        try:
            self.assertIsNone(RX.apply("SSB", [self.hit, self.pit], log=self.log.append))
        finally:
            RX.configured_path = orig
        self.assertEqual((self.hit, self.pit), before)
        self.assertEqual(self.log, [])                      # no output either

    def test_missing_file_warns_and_changes_nothing(self):
        before = copy.deepcopy((self.hit, self.pit))
        rep = RX.apply("SSB", [self.hit, self.pit], path=os.path.join(TMP, "nope.csv"), log=self.log.append)
        self.assertIsNone(rep)
        self.assertEqual((self.hit, self.pit), before)
        self.assertEqual(len(self.log), 1)
        self.assertIn("WARNING", self.log[0])
        self.assertIn("nope.csv", self.log[0])

    def test_unreadable_file_warns_and_changes_nothing(self):
        before = copy.deepcopy((self.hit, self.pit))
        rep = RX.apply("SSB", [self.hit, self.pit], path=write("junk.csv", "Foo,Bar\n1,2\n"), log=self.log.append)
        self.assertIsNone(rep)
        self.assertEqual((self.hit, self.pit), before)
        self.assertIn("not used", self.log[0])

    def test_merge_logs_dates_and_warns_when_stale(self):
        rep = RX.apply("SSB", [self.hit, self.pit], path=FIXTURE, pull_game_date="2044-05-02", log=self.log.append)
        self.assertEqual(rep["matched"], 10)
        text = "\n".join(self.log)
        self.assertIn("10 of 12 players matched", text)
        self.assertIn("2043-12-28", text)
        self.assertIn("126 game days older", text)
        self.assertIn("WARNING: the roster export is 126 game days older", text)
        self.assertIn("1 players share an ID", text)

    def test_fresh_export_does_not_warn(self):
        RX.apply("SSB", [self.hit, self.pit], path=FIXTURE, pull_game_date="2043-12-29", log=self.log.append)
        self.assertNotIn("WARNING", "\n".join(self.log))

    def test_secrets_free(self):
        RX.apply("SSB", [self.hit, self.pit], path=FIXTURE, pull_game_date="2044-05-02", log=self.log.append)
        self.assertNotIn("token", "\n".join(self.log).lower())


class Settings(unittest.TestCase):
    def merged_with(self, value):
        m = copy.deepcopy(ST.load())
        m["leagues"]["RG"]["roster_export"] = value
        return ST.validate(m)

    def test_valid_values(self):
        for v in ("org.csv", "ORG.CSV", "C:\\Users\\a\\org.csv", "C:/Users/a/org.csv",
                  "\\\\server\\share\\org.csv", "~/exports/org.csv", "%TGS_ROSTER_TEST_DIR%/org.csv",
                  "/Users/a/exports/org.csv"):
            self.assertEqual(self.merged_with(v), [], v)

    def test_invalid_values(self):
        for v in ("", "   ", 5, None, ["org.csv"], "org.txt", "org", " org.csv", "sub/org.csv",
                  "sub\\org.csv", "a\x00b.csv"):
            probs = self.merged_with(v)
            self.assertEqual(len(probs), 1, v)
            self.assertTrue(probs[0].startswith("leagues.RG.roster_export:"), probs)

    def test_absent_is_valid_and_the_default_has_none(self):
        self.assertEqual(ST.validate(ST.load()), [])
        self.assertIsNone(ST.roster_export_path("RG"))
        self.assertIsNone(ST.roster_export_path("NOPE"))

    def test_path_resolution(self):
        local = {"leagues": {"RG": {"roster_export": "org.csv"},
                             "BLM": {"roster_export": os.path.join(TMP, "abs", "blm_org.csv")},
                             "TGS": {"roster_export": "~/tgs_org.csv"}}}
        with open(os.environ["TGS_SETTINGS_LOCAL"], "w", encoding="utf-8") as fh:
            json.dump(local, fh)
        try:
            ST._merged(refresh=True)
            self.assertEqual(ST.validate(ST.load()), [])
            save = ST.ootp_save_dir("RG")
            self.assertEqual(ST.roster_export_path("RG"), os.path.normpath(os.path.join(save, "import_export", "org.csv")))
            self.assertEqual(ST.roster_export_path("BLM"), os.path.normpath(os.path.join(TMP, "abs", "blm_org.csv")))
            self.assertEqual(ST.roster_export_path("TGS"), os.path.normpath(os.path.expanduser("~/tgs_org.csv")))
            self.assertEqual(RX.configured_path("RG"), ST.roster_export_path("RG"))
        finally:
            os.remove(os.environ["TGS_SETTINGS_LOCAL"])
            ST._merged(refresh=True)


if __name__ == "__main__":
    unittest.main()
