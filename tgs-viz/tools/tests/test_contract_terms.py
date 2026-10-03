"""
test_contract_terms.py - ingest/contract_terms.py (option / buyout / extension keys, the ported
year resolver, the option-aware proposal) and statsplus.fetch_contract_extensions.

    python tgs-viz/tools/tests/test_contract_terms.py
    python -m pytest tgs-viz/tools/tests/test_contract_terms.py -q

Offline. The contract rows in fixtures/contract_terms_ssb.json are copies of rows from the saved SSB
/contract reply (game date 2044-05-02); the extension rows are written here by hand because no
/contractextension reply is saved anywhere (they follow the /contract column layout, which is an
assumption until one live reply is read; see docs/phase3/contracts.md).
"""
import copy
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(VIZ, "ingest"))

import contract_terms as CT  # noqa: E402
import statsplus as S  # noqa: E402

with open(os.path.join(HERE, "fixtures", "contract_terms_ssb.json"), encoding="utf-8") as _f:
    FIX = json.load(_f)


def _recs(ids):
    """Records the way the refresh pull has them after statsplus.attach_contract_injury."""
    cmap, pmap = S.build_contract_injury_maps(FIX["contract"], FIX["players"])
    cols = S.reply_columns(FIX["contract"], FIX["players"])
    recs = [{"ID": i} for i in ids]
    S.attach_contract_injury(recs, cmap, pmap, columns=cols)
    return recs, cmap, cols


def _ext_row(pid, season_year, years, sal, **extra):
    row = {"player_id": pid, "team_id": "1", "season_year": str(season_year), "current_year": "0",
           "years": str(years), "last_year_team_option": "0", "last_year_player_option": "0",
           "last_year_vesting_option": "0", "next_last_year_team_option": "0",
           "next_last_year_player_option": "0", "next_last_year_vesting_option": "0",
           "last_year_option_buyout": "0", "next_last_year_option_buyout": "0"}
    for i in range(15):
        row[f"salary{i}"] = str(sal[i]) if i < len(sal) else "0"
    row.update(extra)
    return row


class Attach(unittest.TestCase):
    def test_existing_keys_are_not_touched(self):
        recs, cmap, cols = _recs([c["player_id"] for c in FIX["contract"]])
        before = copy.deepcopy(recs)
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        for a, b in zip(before, recs):
            for k, v in a.items():
                self.assertEqual(b[k], v, k)

    def test_team_option_in_last_year_with_buyout(self):
        recs, cmap, cols = _recs(["51213"])
        n = CT.attach_contract_terms(recs, cmap, None, columns=cols)
        r = recs[0]
        self.assertEqual(n, 1)
        self.assertEqual(r["SalarySchedule"], [7500000, 7500000, 6500000])
        self.assertEqual(r["SalaryStartYr"], 2044)
        self.assertEqual(r["ContractOptions"],
                         [{"yr": 2046, "i": 2, "type": "team", "slot": "last", "buyout": 1700000}])
        # the next_last slot carries 1.9M with no flag: kept raw, tied to nothing
        self.assertEqual(r["ContractBuyouts"], {"last": 1700000, "next_last": 1900000})

    def test_two_player_options_use_both_slots_and_calendar_years(self):
        recs, cmap, cols = _recs(["39725"])
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        r = recs[0]
        self.assertEqual(r["SalarySchedule"], [15000000, 20000000, 20000000, 20000000])
        self.assertEqual(r["SalaryStartYr"], 2044)            # season_year 2041 + current_year 3
        self.assertEqual([(o["yr"], o["i"], o["type"], o["slot"], o["buyout"]) for o in r["ContractOptions"]],
                         [(2047, 3, "player", "last", 5000000), (2046, 2, "player", "next_last", 3750000)])

    def test_buyout_with_no_flag_is_kept_but_not_an_option(self):
        recs, cmap, cols = _recs(["57774"])
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertNotIn("ContractOptions", recs[0])
        self.assertEqual(recs[0]["ContractBuyouts"], {"last": 3000000, "next_last": 1800000})

    def test_stale_contract_shows_its_old_start_year(self):
        recs, cmap, cols = _recs(["49408", "1449"])
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertEqual(recs[0]["SalaryStartYr"], 2042)       # a 2042 deal still priced in 2044
        self.assertEqual(recs[1]["SalaryStartYr"], 2044)
        for r in recs:
            self.assertNotIn("ContractOptions", r)
            self.assertNotIn("ContractBuyouts", r)

    def test_unpriced_contract_gets_no_start_year(self):
        recs, cmap, cols = _recs(["57570"])                    # season_year 0, all pay 0
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertNotIn("SalaryStartYr", recs[0])

    def test_reply_without_option_columns_leaves_option_keys_unset(self):
        recs, cmap, cols = _recs(["51213"])
        cols = {c for c in cols if "option" not in c}
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertNotIn("ContractOptions", recs[0])
        self.assertEqual(recs[0]["SalaryStartYr"], 2044)

    def test_rerun_leaves_no_stale_keys(self):
        recs, cmap, cols = _recs(["51213"])
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        cmap["51213"] = dict(cmap["51213"], last_year_team_option="0")
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertNotIn("ContractOptions", recs[0])

    def test_extension_attached_with_alignment_flag(self):
        recs, cmap, cols = _recs(["51213", "1449"])
        rows = [_ext_row("51213", 2047, 2, [9000000, 9500000], last_year_player_option="1"),
                _ext_row("1449", 2050, 1, [2000000]),           # does not start where the base ends
                _ext_row("999", 2045, 0, [])]                    # no deal: dropped
        ext_map = CT.build_extension_map(rows)
        self.assertEqual(sorted(ext_map), ["1449", "51213"])
        CT.attach_contract_terms(recs, cmap, ext_map, columns=cols)
        self.assertEqual(recs[0]["ContractExt"], {
            "yr": 2047, "years": 2, "salaries": [9000000, 9500000], "after_base": True,
            "options": [{"yr": 2048, "i": 1, "type": "player", "slot": "last", "buyout": 0}]})
        self.assertFalse(recs[1]["ContractExt"]["after_base"])
        # the base deal's own keys are not changed by an extension
        self.assertEqual(recs[0]["SalarySchedule"], [7500000, 7500000, 6500000])

    def test_not_read_extensions_leave_no_key(self):
        recs, cmap, cols = _recs(["51213"])
        self.assertIsNone(CT.build_extension_map(None))
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        self.assertNotIn("ContractExt", recs[0])


class Resolve(unittest.TestCase):
    def setUp(self):
        base = CT.parse_contract(next(c for c in FIX["contract"] if c["player_id"] == "51213"))
        self.base = base
        self.ext = CT.parse_contract(_ext_row("51213", 2047, 2, [9000000, 9500000], last_year_player_option="1"))

    def test_years_inside_the_base_deal(self):
        self.assertEqual(CT.resolve_year(self.base, self.ext, 2044),
                         {"salary": 7500000, "optionType": None, "buyout": 0, "source": "contract"})
        self.assertEqual(CT.resolve_year(self.base, self.ext, 2046),
                         {"salary": 6500000, "optionType": "team", "buyout": 1700000, "source": "contract"})

    def test_years_inside_the_extension(self):
        self.assertEqual(CT.resolve_year(self.base, self.ext, 2047)["salary"], 9000000)
        r = CT.resolve_year(self.base, self.ext, 2048)
        self.assertEqual((r["salary"], r["optionType"], r["source"]), (9500000, "player", "extension"))

    def test_outside_every_deal(self):
        self.assertIsNone(CT.resolve_year(self.base, self.ext, 2043))
        self.assertIsNone(CT.resolve_year(self.base, self.ext, 2049))
        self.assertIsNone(CT.resolve_year(self.base, None, 2047))
        self.assertIsNone(CT.resolve_year(None, None, 2044))


class ContractYear(unittest.TestCase):
    def test_mode_of_season_year_plus_current_year(self):
        rows = FIX["contract"]                  # eight rows read 2044, one reads 2042, one has season_year 0
        self.assertEqual(CT.detect_contract_year(rows, 2044), 2044)
        self.assertEqual(CT.detect_contract_year(rows, 2043), 2044)   # game_year + 1: the roll has happened
        self.assertEqual(CT.detect_contract_year(rows, 2040), 2040)   # not believed: falls back
        self.assertEqual(CT.detect_contract_year([], 2044), 2044)


class Proposal(unittest.TestCase):
    """option_aware_view: NOT wired anywhere; the numbers here are the worked examples in the doc."""

    def view(self, pid):
        recs, cmap, cols = _recs([pid])
        CT.attach_contract_terms(recs, cmap, None, columns=cols)
        return CT.option_aware_view(recs[0]["SalarySchedule"], recs[0].get("ContractOptions"))

    def test_single_team_option_costs_its_buyout_when_declined(self):
        v = self.view("51213")
        self.assertEqual(v["as_is"], {"years": 3, "owed": 21500000})
        self.assertEqual(v["guaranteed"], {"years": 2, "owed": 15000000 + 1700000})
        self.assertEqual(v["club_holds"], {"years": 3, "owed": 21500000})

    def test_player_options_are_not_guaranteed_and_not_club_controlled(self):
        v = self.view("39725")
        self.assertEqual(v["as_is"], {"years": 4, "owed": 75000000})
        self.assertEqual(v["guaranteed"], {"years": 2, "owed": 35000000})   # no buyout for a player option
        self.assertEqual(v["club_holds"], {"years": 2, "owed": 35000000})

    def test_consecutive_team_options(self):
        v = self.view("60099")
        self.assertEqual(v["as_is"], {"years": 4, "owed": 83400000})
        self.assertEqual(v["guaranteed"], {"years": 2, "owed": 18600000 + 21600000 + 6500000})
        self.assertEqual(v["club_holds"], {"years": 4, "owed": 83400000})

    def test_option_on_the_year_in_force_changes_nothing(self):
        v = self.view("52093")                  # vesting option on the current year of a 2-year deal
        self.assertEqual(v["as_is"], v["guaranteed"])
        self.assertEqual(v["as_is"], v["club_holds"])

    def test_no_options_and_empty_inputs(self):
        v = self.view("1449")
        self.assertEqual(v["guaranteed"], {"years": 1, "owed": 1040000})
        self.assertEqual(CT.option_aware_view([], None)["as_is"], {"years": 0, "owed": 0})
        self.assertEqual(CT.option_aware_view(None, [{"i": 1, "type": "team", "buyout": 5}])["guaranteed"],
                         {"years": 0, "owed": 0})

    def test_mixed_team_then_player(self):
        opts = [{"i": 2, "type": "team", "buyout": 3}, {"i": 3, "type": "player", "buyout": 0}]
        v = CT.option_aware_view([10, 10, 10, 10], opts)
        self.assertEqual(v["guaranteed"], {"years": 2, "owed": 23})
        self.assertEqual(v["club_holds"], {"years": 3, "owed": 30})


class FetchExtensions(unittest.TestCase):
    URL = "https://statsplus.net/ssb/api"

    def run_fetch(self, text):
        with mock.patch.object(S, "_open", return_value=(text, False)) as op:
            rows = S.fetch_contract_extensions(self.URL)
        op.assert_called_once()
        self.assertEqual(op.call_args[0][0], f"{self.URL}/contractextension")
        return rows

    def test_rows_parse_like_contract_rows(self):
        text = ("player_id,team_id,season_year,current_year,years,salary0,salary1,last_year_player_option\n"
                "51213,5,2047,0,2,9000000,9500000,1\n")
        rows = self.run_fetch(text)
        self.assertEqual(rows[0]["player_id"], "51213")
        m = CT.build_extension_map(rows)
        self.assertEqual(m["51213"]["salaries"], [9000000, 9500000])
        self.assertEqual(m["51213"]["options"][0]["type"], "player")

    def test_empty_reply_and_header_only_are_no_extensions(self):
        self.assertEqual(self.run_fetch(""), [])
        self.assertEqual(self.run_fetch("player_id,team_id,season_year,years,salary0\n"), [])

    def test_reply_that_is_not_a_table_is_refused(self):
        with mock.patch.object(S, "_open", return_value=("<html>login</html>", False)):
            with self.assertRaises(S.StatsPlusRefused):
                S.fetch_contract_extensions(self.URL)

    def test_one_request_only_and_columns_registered(self):
        self.assertEqual(S.COLUMNS["contractextension"][0], ("player_id",))


if __name__ == "__main__":
    unittest.main()
