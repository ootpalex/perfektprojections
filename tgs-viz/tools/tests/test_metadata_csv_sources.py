"""
test_metadata_csv_sources.py - the CSV and offline sources of ingest/metadata_inputs.py:
--offline DATE, --paste-dir DIR (sp_data.csv / rp_data.csv) and --ratings-dir DIR
(batter / fielding / pitcher ratings CSVs), the way the dashboard keeps a season's files.

    python tgs-viz/tools/tests/test_metadata_csv_sources.py

Offline: every StatsPlus fetch helper is replaced by one that fails the test when called, and
everything is written under a temp folder (TGS_SETTINGS_LOCAL, STATSPLUS_CACHE_DIR, the module's
cache root HERE are all pointed there).
"""
import contextlib
import csv
import gzip
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
VIZ = os.path.dirname(TOOLS)
INGEST = os.path.join(VIZ, "ingest")
ENGINE = os.path.join(VIZ, "engine")

TMP = tempfile.mkdtemp(prefix="tgs-csvsrc-test-")
os.environ["TGS_SETTINGS_LOCAL"] = os.path.join(TMP, "settings.local.json")
os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(TMP, "tokens.txt")
os.environ["STATSPLUS_CACHE_DIR"] = os.path.join(TMP, "spcache")
for p in (TOOLS, INGEST, ENGINE):
    if p not in sys.path:
        sys.path.insert(0, p)
import settings as ST          # noqa: E402
import statsplus as S          # noqa: E402
import metadata_inputs as M    # noqa: E402
import metadata_calibrate as C  # noqa: E402


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def put(directory, name, header, rows, banner=None):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, name), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if banner:
            w.writerow(banner)
        w.writerow(header)
        w.writerows(rows)


def never(*a, **k):
    raise AssertionError("StatsPlus asked in a test")


class Readers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)

    def test_find_csv_ignores_case_and_reports_a_missing_file(self):
        put(self.d, "SP_Data.csv", ["ID"], [])
        self.assertEqual(os.path.basename(M.find_csv(self.d, "sp_data.csv")), "SP_Data.csv")
        self.assertIsNone(M.find_csv(self.d, "rp_data.csv"))
        self.assertIsNone(M.find_csv(os.path.join(self.d, "nope"), "sp_data.csv"))
        with self.assertRaises(SystemExit) as e:
            M.read_plain_csv(self.d, "rp_data.csv")
        self.assertIn("rp_data.csv is not in", str(e.exception))

    def test_read_plain_csv_keeps_player_rows_only(self):
        put(self.d, "sp_data.csv", ["ID", "Name", "IP"],
            [["12", "A B", "173.1"], ["", "", ""], ["0", "zero", "1"],
             ["Saturday, ... - OOTP Baseball 27.4 Build 76"], ["13", "C D", "127.0"]])
        hdr, rows = M.read_plain_csv(self.d, "sp_data.csv")
        self.assertEqual(hdr, ["ID", "Name", "IP"])
        self.assertEqual(rows, [["12", "A B", "173.1"], ["13", "C D", "127.0"]])     # IP stays text

    def test_a_written_paste_tab_loads_in_the_calibrator_with_ip_untouched(self):
        hdr, rows = ["ID", "Name", "IP", "BF"], [["12", "A B", "127.0", "500"], ["13", "C D", "173.1", "700"]]
        path = os.path.join(self.d, "SP_Data.csv")
        M.write_plain_tab(path, hdr, rows)
        with open(path, encoding="utf-8-sig") as f:
            self.assertEqual(f.readline().split(",")[0], "Player List")
        back = C.load_single(path)
        self.assertEqual([r["IP"] for r in back], ["127.0", "173.1"])
        self.assertAlmostEqual(sum(C.dollarde(r["IP"]) for r in back), 127 + 173 + 1 / 3)


class Height(unittest.TestCase):
    def test_both_quote_styles_read_as_the_same_height_cm(self):
        for ht in ("6' 5'", "6' 5\"", " 6'5' "):
            self.assertAlmostEqual(C.height_cm(M.height_text(ht)), 6 * 30.48 + 5 * 2.54, places=9)
        self.assertEqual(M.height_text("6' 5'"), "6' 5\"")
        # the unfixed text reads as 0 cm in the calibrator: this is what the conversion is for
        self.assertEqual(C.height_cm("6' 5'"), 0.0)

    def test_other_values_are_returned_as_they_are(self):
        for v in ("", "190", "tall"):
            self.assertEqual(M.height_text(v), v)
        self.assertIsNone(M.height_text(None))


BAT_ROWS_VR = [["2", "LF", "B", "300", "R", "55", "50", "40", "45", "50", "60", "55", "45", "50", "55", "70", "60", "65", "70"],
               ["1", "C", "A", "500", "L", "45", "40", "35", "40", "45", "50", "45", "40", "45", "50", "40", "30", "35", "40"],
               ["3", "RF", "Z", "0", "S", "20", "20", "20", "20", "20", "20", "20", "20", "20", "20", "20", "20", "20", "20"]]


class RatingsFromCsv(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)

    def test_batter_ratings_are_ordered_by_pa_and_drop_zero_pa(self):
        # columns in another order than the tab's: the reader picks them by name
        shuffled = ["Name", "ID", "POS"] + [c for c in M.BAT_RAT_HDR if c not in ("ID", "POS", "Name")]
        for name, bump in (("batter_ratings_vr.csv", 0), ("batter_ratings_vl.csv", 7)):
            rows = []
            for r in BAT_ROWS_VR:
                rec = dict(zip(M.BAT_RAT_HDR, r))
                rec["PA"] = str(int(rec["PA"]) + bump)
                rows.append([rec[c] for c in shuffled])
            put(self.d, name, shuffled, rows)
        vr, vl = M.csv_batter_ratings(self.d)
        self.assertEqual([r[0] for r in vr], ["1", "2"])                 # 500 PA, 300 PA; the 0-PA row is gone
        self.assertEqual([r[0] for r in vl], ["1", "2", "3"])            # +7 PA puts id 3 above zero
        self.assertEqual(vr[0], BAT_ROWS_VR[1])                          # columns back in the tab's order

    def test_a_missing_column_stops_and_names_it(self):
        put(self.d, "batter_ratings_vr.csv", ["ID", "POS", "Name", "PA"], [["1", "C", "A", "5"]])
        put(self.d, "batter_ratings_vl.csv", ["ID", "POS", "Name", "PA"], [["1", "C", "A", "5"]])
        with self.assertRaises(SystemExit) as e:
            M.csv_batter_ratings(self.d)
        self.assertIn("no B, BA vL", str(e.exception))

    def test_fielding_ratings_drop_pitchers_and_fix_heights(self):
        def row(i, pos, ip, ht):
            return [i, pos, f"P{i}", ip, ht] + ["20"] * 10
        put(self.d, "fielding_ratings.csv", M.FLD_RAT_HDR,
            [row("1", "7", "1368.1", "6' 5'"), row("2", "1", "173.1", "6' 4'"), row("3", "0", "63.0", "5' 11\""),
             row("4", "1", "10.0", "6' 0'")])
        rows, pitchers = M.csv_fielding_ratings(self.d)
        self.assertEqual(pitchers, 2)
        self.assertEqual([(r[0], r[3], r[4]) for r in rows], [("1", "1368.1", "6' 5\""), ("3", "63.0", "5' 11\"")])

    def test_pitcher_ratings_keep_the_pasted_pitchers_with_bf(self):
        def row(i, bf):
            return [i, "SP", f"P{i}", bf, "R"] + ["50"] * 9
        put(self.d, "pitcher_ratings_vr.csv", M.PIT_RAT_HDR, [row("10", "200"), row("11", "650"), row("12", "0"), row("99", "400")])
        put(self.d, "pitcher_ratings_vl.csv", M.PIT_RAT_HDR, [row("10", "90"), row("11", "300"), row("12", "0"), row("99", "100")])
        vr, vl, missing = M.csv_pitcher_ratings(self.d, ["10", "11", "12", "13"])
        self.assertEqual([r[0] for r in vr], ["11", "10"])
        self.assertEqual([r[3] for r in vl], ["300", "90"])
        self.assertEqual(missing, ["12", "13"])                           # id 12 has no BF, id 13 is not listed


def feed_rows(cols, **vals):
    return [{**{c: "0" for c in cols}, **v} for v in vals["rows"]]


class OfflineFeeds(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(dir=TMP)
        for name, fn in (("fetch_batting", None), ("fetch_pitching", None), ("fetch_fielding", None),
                         ("fetch_teams", None), ("fetch_date", None)):
            p = mock.patch.object(S, name, side_effect=never)
            p.start()
            self.addCleanup(p.stop)

    def test_a_feed_that_is_not_saved_stops_instead_of_asking(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as e:
            M.fetch_season("base", 2043, self.d, False, offline=True)
        self.assertIn("--offline", str(e.exception))
        self.assertIn("bat1", str(e.exception))

    def test_saved_feeds_are_read_with_no_request(self):
        for name, cols in (("bat", M.FEED_COLS["bat"]), ("pit", M.FEED_COLS["pit"]), ("fld", M.FEED_COLS["fld"])):
            for split in ((1, 2, 3) if name != "fld" else (1,)):
                rows = feed_rows(cols, rows=[{"player_id": "1", "position": "2"}])
                json.dump(rows, open(os.path.join(self.d, f"{name}{split}.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()):
            out = M.fetch_season("base", 2043, self.d, False, offline=True)
        self.assertEqual(sorted(out), ["bat1", "bat2", "bat3", "fld1", "pit1", "pit2", "pit3"])

    def test_an_unusable_saved_feed_stops_offline(self):
        json.dump([{"player_id": "1"}], open(os.path.join(self.d, "bat1.json"), "w"))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            M.fetch_season("base", 2043, self.d, False, offline=True)

    def test_season_pitching_offline_reads_only_the_saved_feed(self):
        out = io.StringIO()
        with mock.patch.object(M, "HERE", self.d), contextlib.redirect_stdout(out):
            self.assertIsNone(M.season_pitching("base", "zz", 2042, offline=True))
            self.assertIn("not saved", out.getvalue())
            self.assertFalse(os.path.exists(os.path.join(self.d, ".cache")))
            cache = os.path.join(self.d, ".cache", "metadata_zz_2042")
            os.makedirs(cache)
            rows = feed_rows(M.FEED_COLS["pit"], rows=[{"player_id": "7", "bf": "100", "outs": "60"}])
            json.dump(rows, open(os.path.join(cache, "pit1.json"), "w"))
            self.assertEqual(M.season_pitching("base", "zz", 2042, offline=True)["7"]["bf"], 100.0)

    def test_saved_teams_come_back_whatever_their_age_and_only_for_that_date(self):
        base = "https://statsplus.net/zz/api"
        url = f"{base}/teams/"
        path = S._cache_path(base, url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        old = time.time() - 90 * 86400
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "url": url, "game_date": "2044-05-09", "saved": old, "data": [{"ID": "31"}]}, f)
        self.assertIsNone(S._cache_read(path, url, "2044-05-09", 6))               # the normal 6 h rule says stale
        self.assertEqual(M.saved_teams(base, "2044-05-09"), [{"ID": "31"}])
        self.assertIsNone(M.saved_teams(base, "2044-05-10"))
        self.assertIsNone(M.saved_teams("https://statsplus.net/none/api", "2044-05-09"))


class EndToEnd(unittest.TestCase):
    """metadata_inputs.main() with --offline, --paste-dir and --ratings-dir, on a 8-hitter / 3-pitcher league."""

    def setUp(self):
        self.root = tempfile.mkdtemp(dir=TMP)
        self.src = os.path.join(self.root, "csv")
        self.out = os.path.join(self.root, "out")
        cache = os.path.join(self.root, ".cache", "metadata_tst_2043")
        os.makedirs(cache)
        hit = [{"player_id": str(i), "team_id": "31", "pa": "100", "ab": "90", "h": "25", "d": "5", "t": "1",
                "hr": "4", "bb": "8", "k": "20", "g": "30", "gs": "28", "r": "12", "pitches_seen": "380"}
               for i in range(1, 9)]
        side = lambda pa: [{"player_id": str(i), "pa": pa} for i in range(1, 9)]
        pit = [{"player_id": "21", "team_id": "31", "bf": "40", "outs": "19", "ha": "10", "hra": "2", "bb": "4",
                "k": "9", "r": "5", "er": "5", "g": "2", "gs": "1"},
               {"player_id": "22", "team_id": "31", "bf": "30", "outs": "21", "ha": "6", "hra": "1", "bb": "2",
                "k": "7", "r": "3", "er": "3", "g": "1", "gs": "1"},
               {"player_id": "23", "team_id": "32", "bf": "12", "outs": "9", "ha": "2", "hra": "0", "bb": "1",
                "k": "3", "r": "1", "er": "1", "g": "5", "gs": "0"}]
        psplit = lambda bf: [{"player_id": p["player_id"], "bf": bf} for p in pit]
        fld = [{"player_id": str(i), "position": str(i + 1), "g": "30", "gs": "28", "ip": "250", "ipf": "1", "po": "100"}
               for i in range(1, 9)]
        for name, cols, rows in (("bat1", M.FEED_COLS["bat"], hit), ("bat2", M.FEED_COLS["bat"], side("40")),
                                 ("bat3", M.FEED_COLS["bat"], side("60")), ("pit1", M.FEED_COLS["pit"], pit),
                                 ("pit2", M.FEED_COLS["pit"], psplit("15")), ("pit3", M.FEED_COLS["pit"], psplit("25")),
                                 ("fld1", M.FEED_COLS["fld"], fld)):
            json.dump(feed_rows(cols, rows=rows), open(os.path.join(cache, f"{name}.json"), "w"))
        pull = os.path.join(self.root, "pull.json")
        json.dump({}, open(pull, "w"))
        self.pull = pull
        # the dashboard-style CSVs
        put(self.src, "batter_ratings_vr.csv", M.BAT_RAT_HDR, [[str(i), "C", f"H{i}", str(60 + i), "R"] + ["50"] * 14 for i in range(1, 9)])
        put(self.src, "batter_ratings_vl.csv", M.BAT_RAT_HDR, [[str(i), "C", f"H{i}", str(40 - i), "R"] + ["55"] * 14 for i in range(1, 9)])
        put(self.src, "fielding_ratings.csv", M.FLD_RAT_HDR,
            [[str(i), str(i + 1), f"H{i}", "250.1", "6' 2'"] + ["45"] * 10 for i in range(1, 9)]
            + [["21", "1", "P21", "6.1", "6' 4'"] + ["20"] * 10])
        prow = lambda i, bf: [str(i), "SP", f"P{i}", str(bf), "R"] + ["50"] * 9
        put(self.src, "pitcher_ratings_vr.csv", M.PIT_RAT_HDR, [prow(21, 25), prow(22, 25), prow(23, 25)])
        put(self.src, "pitcher_ratings_vl.csv", M.PIT_RAT_HDR, [prow(21, 15), prow(22, 15), prow(23, 15)])
        hdr = ["ID", "Name", "IP", "BF", "HA", "HR", "BB", "K", "R"]
        put(self.src, "sp_data.csv", hdr, [["21", "P21", "6.1", "40", "10", "2", "4", "9", "5"],
                                           ["22", "P22", "7.0", "30", "6", "1", "2", "7", "3"]])
        put(self.src, "rp_data.csv", hdr, [["23", "P23", "3.0", "12", "2", "0", "1", "3", "1"]])

    def run_main(self, *extra):
        argv = ["metadata_inputs.py", "--league", "BLM", "--slug", "tst", "--year", "2043", "--out", self.out,
                "--pull", self.pull, "--offline", "2044-05-09", "--paste-dir", self.src, "--ratings-dir", self.src, *extra]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(M, "HERE", self.root), \
                mock.patch.object(M, "load_pull", return_value={}), contextlib.redirect_stdout(out):
            for name in ("fetch_batting", "fetch_pitching", "fetch_fielding", "fetch_teams", "fetch_date", "fetch_players"):
                if hasattr(S, name):
                    p = mock.patch.object(S, name, side_effect=never)
                    p.start()
                    self.addCleanup(p.stop)
            M.main()
        return out.getvalue()

    def test_all_stages_run_offline_from_the_csv_files(self):
        text = self.run_main()
        self.assertIn("3 pitchers match exactly", text)
        files = sorted(os.listdir(self.out))
        for f in ("Batter_Ratings.csv", "Fielding_Ratings.csv", "SP_Data.csv", "RP_Data.csv", "SP_Ratings.csv",
                  "RP_Ratings.csv", "Hitting_Data.csv", "Pitching_Data.csv", "Fielding_Data.csv", "manifest.json"):
            self.assertIn(f, files)
        vr, vl = C.load_vr_vl(os.path.join(self.out, "Batter_Ratings.csv"))
        self.assertEqual((len(vr), len(vl)), (8, 8))
        self.assertEqual(vr[0]["PA"], "68")                               # most PA first, PA from the CSV file
        fr = C.load_single(os.path.join(self.out, "Fielding_Ratings.csv"))
        self.assertEqual(len(fr), 8)                                      # the pitcher row is left out
        self.assertEqual({r["HT"] for r in fr}, {"6' 2\""})
        spv, _spl = C.load_vr_vl(os.path.join(self.out, "SP_Ratings.csv"))
        rpv, _rpl = C.load_vr_vl(os.path.join(self.out, "RP_Ratings.csv"))
        self.assertEqual(sorted(r["ID"] for r in spv), ["21", "22"])
        self.assertEqual([r["ID"] for r in rpv], ["23"])
        sp = C.load_single(os.path.join(self.out, "SP_Data.csv"))
        self.assertEqual([r["IP"] for r in sp], ["6.1", "7.0"])
        man = json.load(open(os.path.join(self.out, "manifest.json")))
        self.assertTrue(man["offline"])
        self.assertEqual(man["in_game_date"], "2044-05-09")
        self.assertEqual(man["counts"]["pitchers_left_out"], 1)
        self.assertEqual(man["paste_check"], {"exact": 3, "partial": 0, "absent": 0})

    def test_a_paste_that_does_not_match_the_season_stops(self):
        put(self.src, "rp_data.csv", ["ID", "Name", "IP", "BF", "HA", "HR", "BB", "K", "R"],
            [["23", "P23", "3.0", "12", "2", "0", "1", "4", "1"]])        # one strikeout above the season total
        with self.assertRaises(SystemExit) as e:
            self.run_main()
        self.assertIn("--accept-paste", str(e.exception))
        self.assertTrue(os.path.exists(os.path.join(self.out, "Hitting_Data.csv")))       # the auto stage ran
        self.assertFalse(os.path.exists(os.path.join(self.out, "SP_Data.csv")))


class LeagueChoices(unittest.TestCase):
    """--league takes TGS / BLM and any enabled StatsPlus league in settings (SSB has no workbook)."""

    def tearDown(self):
        with open(os.environ["TGS_SETTINGS_LOCAL"], "w", encoding="utf-8") as f:
            json.dump({"leagues": {}}, f)
        ST.load(refresh=True)

    def run_main(self, league):
        argv = ["metadata_inputs.py", "--league", league, "--year", "2042", "--offline", "2044-05-09",
                "--out", os.path.join(TMP, "o")]
        err = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(S, "fetch_date", side_effect=never), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as e:
                M.main()
        return e.exception.code, err.getvalue()

    def test_a_statsplus_league_in_settings_gets_past_the_argument_check(self):
        with open(os.environ["TGS_SETTINGS_LOCAL"], "w", encoding="utf-8") as f:
            json.dump({"leagues": {"SSB": {"type": "statsplus", "name": "SSB", "basis": "BLM",
                                          "engine_first_season": 2043}}}, f)
        ST.load(refresh=True)
        code, _err = self.run_main("SSB")
        self.assertIn("SSB season 2042 was played before this league's engine boundary", str(code))   # past argparse

    def test_a_league_that_is_not_in_settings_is_refused(self):
        ST.load(refresh=True)
        code, err = self.run_main("SSB")
        self.assertEqual(code, 2)
        self.assertIn("invalid choice", err)


class Arguments(unittest.TestCase):
    def test_bad_offline_arguments_are_refused_before_anything_runs(self):
        for extra in (["--offline", "May 9"], ["--offline", "2044-05-09", "--refresh"]):
            argv = ["metadata_inputs.py", "--league", "BLM", "--out", os.path.join(TMP, "o"), *extra]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(S, "fetch_date", side_effect=never), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                M.main()
            self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
