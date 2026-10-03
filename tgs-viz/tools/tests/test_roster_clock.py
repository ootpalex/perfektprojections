"""
test_roster_clock.py - ingest/roster_clock.py: the waiver-clock and service keys from /players, the
game date written into metadata.json, and the service-year arithmetic ported from the dashboard.

    python tgs-viz/tools/tests/test_roster_clock.py
    python -m pytest tgs-viz/tools/tests/test_roster_clock.py -q

Offline. fixtures/contract_terms_ssb.json holds /players rows copied from the saved SSB reply (game
date 2044-05-02) for ten players, plus generated rows for the service-year measurement.
"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(VIZ, "ingest"))

import roster_clock as RC  # noqa: E402
import statsplus as S  # noqa: E402

with open(os.path.join(HERE, "fixtures", "contract_terms_ssb.json"), encoding="utf-8") as _f:
    FIX = json.load(_f)


def _attach(ids, columns="all"):
    cmap, pmap = S.build_contract_injury_maps(FIX["contract"], FIX["players"])
    cols = S.reply_columns(FIX["contract"], FIX["players"]) if columns == "all" else columns
    recs = [{"ID": i} for i in ids]
    S.attach_contract_injury(recs, cmap, pmap, columns=cols)
    before = [dict(r) for r in recs]
    n = RC.attach_waiver_service(recs, pmap, columns=cols)
    return recs, before, n


class Attach(unittest.TestCase):
    def test_live_waiver_claim_clock_and_service(self):
        recs, _, n = _attach(["62286"])
        r = recs[0]
        self.assertEqual(n, 1)
        self.assertTrue(r["OnWaivers"])                       # his existing key, unchanged
        self.assertEqual((r["WaiverDays"], r["WaiverDaysLeft"]), (7, 1))
        self.assertEqual((r["ProSvcYrs"], r["ProSvcDays"], r["ProSvcDaysTY"]), (9, 1622, 28))
        self.assertEqual((r["SecSvcYrs"], r["SecSvcDays"], r["SecSvcDaysTY"]), (4, 830, 28))
        self.assertIs(r["HasReceivedArb"], False)
        self.assertEqual(r["YearsProtectedFromRule5"], 5)
        self.assertIs(r["IsOnSecondary"], True)
        self.assertIs(r["IsActive"], True)

    def test_roster_flags_follow_the_source_value(self):
        recs, _, _ = _attach(["57570", "52093"])
        self.assertEqual((recs[0]["IsOnSecondary"], recs[0]["IsActive"]), (False, False))
        self.assertEqual((recs[1]["IsOnSecondary"], recs[1]["IsActive"]), (False, True))   # a '0' is False, not unset
        self.assertEqual(recs[0]["YearsProtectedFromRule5"], 4)

    def test_cleared_waiver_has_zero_days_left(self):
        recs, _, _ = _attach(["57570"])
        r = recs[0]
        self.assertTrue(r["OnWaivers"])
        self.assertTrue(r["DFA"])
        self.assertEqual((r["WaiverDays"], r["WaiverDaysLeft"]), (28, 0))

    def test_blank_row_gets_nothing_not_zero(self):
        recs, _, n = _attach(["1"])                           # a retired player: every value is ''
        # except years_protected_from_rule_5, which StatsPlus fills with 0 on every row: kept as given
        self.assertEqual(n, 1)
        self.assertEqual(recs[0]["YearsProtectedFromRule5"], 0)
        for k in RC.NEW_KEYS:
            if k != "YearsProtectedFromRule5":
                self.assertNotIn(k, recs[0])

    def test_unmatched_record_is_left_alone(self):
        recs, _, n = _attach(["no-such-id"])
        self.assertEqual((n, recs), (0, [{"ID": "no-such-id"}]))

    def test_no_existing_key_changes(self):
        recs, before, _ = _attach(["62286", "57570", "1449", "1"])
        for a, b in zip(before, recs):
            for k, v in a.items():
                self.assertEqual(b[k], v, k)

    def test_missing_column_leaves_its_key_unset(self):
        cols = S.reply_columns(FIX["contract"], FIX["players"]) - {"days_on_waivers_left", "has_received_arbitration"}
        recs, _, _ = _attach(["62286"], columns=cols)
        self.assertNotIn("WaiverDaysLeft", recs[0])
        self.assertNotIn("HasReceivedArb", recs[0])
        self.assertEqual(recs[0]["WaiverDays"], 7)

    def test_rerun_drops_stale_keys(self):
        cmap, pmap = S.build_contract_injury_maps(FIX["contract"], FIX["players"])
        r = {"ID": "62286", "WaiverDaysLeft": 99}
        pmap["62286"] = dict(pmap["62286"], days_on_waivers_left="")
        RC.attach_waiver_service([r], pmap)
        self.assertNotIn("WaiverDaysLeft", r)


class GameDate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.path = os.path.join(self.dir, "metadata.json")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_creates_a_small_file_when_there_is_none(self):
        self.assertEqual(RC.write_game_date(self.dir, "SSB", "2044-05-02"), "written")
        self.assertEqual(self.read(), {"league": "SSB", "game_date": "2044-05-02"})
        self.assertEqual(os.listdir(self.dir), ["metadata.json"])        # no temp file left behind

    def test_keeps_every_other_key_and_the_files_indent(self):
        original = {"extracted_at": "2026-09-01T10:00:00", "league": "BLM",
                    "matchups": {"OVR vR": 0.7206}, "datasets": {"hitters": {"count": 3}}}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(original, f, indent=2)
        self.assertEqual(RC.write_game_date(self.dir, "BLM", "2058-04-09 00:00"), "written")   # a longer /date line
        got = self.read()
        self.assertEqual(got.pop("game_date"), "2058-04-09")
        self.assertEqual(got, original)
        with open(self.path, encoding="utf-8") as f:
            self.assertIn('\n  "extracted_at"', f.read())

    def test_same_date_again_is_unchanged_and_a_new_date_replaces(self):
        RC.write_game_date(self.dir, "SSB", "2044-05-02")
        self.assertEqual(RC.write_game_date(self.dir, "SSB", "2044-05-02"), "unchanged")
        self.assertEqual(RC.write_game_date(self.dir, "SSB", "2044-05-09"), "written")
        self.assertEqual(self.read()["game_date"], "2044-05-09")

    def test_bad_date_or_unreadable_file_is_never_overwritten(self):
        self.assertTrue(RC.write_game_date(self.dir, "SSB", "").startswith("skipped"))
        self.assertTrue(RC.write_game_date(self.dir, "SSB", "May 2nd").startswith("skipped"))
        self.assertFalse(os.path.exists(self.path))
        for text in ("{not json", "[1, 2]"):
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(text)
            self.assertTrue(RC.write_game_date(self.dir, "SSB", "2044-05-02").startswith("skipped"))
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)


class ServiceArithmetic(unittest.TestCase):
    def test_service_year_is_measured_from_the_rows(self):
        rows = [r for r in FIX["clock_rows"] if r["Level"] == "1"] + \
               [r for r in FIX["clock_rows"] if r["Level"] == "8"][:55]
        L, detail = RC.service_year_days(rows)
        self.assertEqual(L, 172)                              # exact for 60 rows; 145 is exact for only 55
        self.assertEqual(detail["groups"]["1"], [172])
        self.assertEqual(detail["groups"]["8"], [145])
        self.assertEqual(detail["rows_exact"], {172: 60, 145: 55})

    def test_larger_group_on_another_clock_wins_by_rows(self):
        rows = [r for r in FIX["clock_rows"] if r["Level"] == "1"][:55] + \
               [r for r in FIX["clock_rows"] if r["Level"] == "8"]
        self.assertEqual(RC.service_year_days(rows)[0], 145)

    def test_no_exact_clock_is_none(self):
        rows = [{"Level": "1", "mlb_service_days": str(100 + i), "mlb_service_years": str((i * 7) % 5)}
                for i in range(80)]
        self.assertIsNone(RC.service_year_days(rows)[0])
        self.assertIsNone(RC.service_year_days([])[0])

    def test_rows_on_clock_drops_the_other_leagues_clock(self):
        on = RC.rows_on_clock(FIX["clock_rows"], 172)
        self.assertEqual({r["Level"] for r in on}, {"1"})
        self.assertEqual(len(on), 60)

    def test_season_day_is_the_modal_remainder(self):
        rows = [{"mlb_service_days": str(172 * k + 28)} for k in range(1, 6)] + [{"mlb_service_days": "400"}]
        self.assertEqual(RC.detect_season_day(rows, 172), 28)
        self.assertEqual(RC.detect_season_day([], 172), 0)
        self.assertEqual(RC.detect_season_day([{"mlb_service_days": ""}, {"mlb_service_days": "0"}], 172), 0)

    def test_limbo_needs_season_end_and_years_behind_days(self):
        behind = [{"mlb_service_days": "344", "mlb_service_years": "1"}]    # 344 // 172 = 2, column says 1
        level = [{"mlb_service_days": "344", "mlb_service_years": "2"}]
        self.assertTrue(RC.detect_limbo(behind, 0, 172))
        self.assertFalse(RC.detect_limbo(behind, 28, 172))
        self.assertFalse(RC.detect_limbo(level, 0, 172))


if __name__ == "__main__":
    unittest.main()
