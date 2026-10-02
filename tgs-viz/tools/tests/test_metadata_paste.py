"""
test_metadata_paste.py - the SP/RP paste check of ingest/metadata_inputs.py.

A paste of another season stops even with --accept-paste (the Recalibrate BLM
task always passes it). Pitchers above their totals (playoff games), pitchers
in neither tab and a few IDs with no MLB pitching stop only without it.

    python tgs-viz/tools/tests/test_metadata_paste.py

Offline: StatsPlus is never asked and no file is written.
"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
INGEST = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "ingest")
if INGEST not in sys.path:
    sys.path.insert(0, INGEST)
import metadata_inputs as M  # noqa: E402

HDR = ["ID", "IP", "BF", "HA", "HR", "BB", "K", "R"]
IDS_2058 = [str(1000 + i) for i in range(100)]
IDS_2057 = IDS_2058[:70] + [str(2000 + i) for i in range(30)]      # 30 of them did not pitch in 2058


def season(seed, ids):
    """{pid: API totals} of one season; every pitcher's numbers differ per seed."""
    out = {}
    for i, pid in enumerate(ids):
        bf = 100 + 7 * i + seed
        out[pid] = {"bf": float(bf), "outs": float(bf * 3 // 4), "ha": float(bf // 4), "hra": float(i % 9),
                    "bb": float(bf // 12), "k": float(bf // 5), "r": float(bf // 9)}
    return out


P_2058, P_2057 = season(0, IDS_2058), season(3, IDS_2057)


def paste(P, skip=(), extra_k=()):
    """SP Data rows of a paste of P: skip = pitchers left out, extra_k = pitchers
    with one strikeout more than the season (OOTP's role split counts playoff games)."""
    rows = []
    for pid, d in P.items():
        if pid in skip:
            continue
        rows.append([pid, M.thirds(d["outs"]), d["bf"], d["ha"], d["hra"], d["bb"],
                     d["k"] + (1 if pid in extra_k else 0), d["r"]])
    return rows


def check(rows, P=P_2058, others=None):
    """(found, rec, others) of a paste against P as season 2058."""
    rec = M.reconcile_roles({"P": P}, rows, HDR, [], HDR)
    others = {y: M.reconcile_roles({"P": Q}, rows, HDR, [], HDR) for y, Q in (others or {}).items()}
    return M.paste_season(2058, rec, others), rec, others


class PasteSeason(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(M.S, "fetch_pitching", side_effect=AssertionError("StatsPlus asked in a test"))
        p.start()
        self.addCleanup(p.stop)

    def decisions(self, found, rec):
        return M.paste_decision(2058, found, rec, True), M.paste_decision(2058, found, rec, False)

    def test_this_seasons_paste_goes_on(self):
        found, rec, _o = check(paste(P_2058))
        self.assertEqual((found, rec["ok"]), (2058, 100))
        self.assertEqual(self.decisions(found, rec), (None, None))

    def test_playoff_games_and_left_out_pitchers_need_your_ok_only(self):
        found, rec, _o = check(paste(P_2058, skip=IDS_2058[:2], extra_k=IDS_2058[2:5]))
        self.assertEqual(found, 2058)
        self.assertEqual((len(rec["over"]), len(rec["absent"])), (3, 2))
        self.assertEqual(self.decisions(found, rec), (None, "confirm"))

    def test_a_few_ids_with_no_mlb_pitching_are_accepted(self):
        rows = paste(P_2058) + [[str(3000 + i), "10.0", 40.0, 9.0, 1.0, 3.0, 8.0, 4.0] for i in range(3)]
        found, rec, _o = check(rows)
        self.assertEqual((found, len(rec["unknown"])), (2058, 3))
        self.assertEqual(self.decisions(found, rec), (None, "odd"))

    def test_playoff_games_on_every_row_are_not_a_wrong_season(self):
        # no pitcher matches, but every ID pitched in 2058: another stat layout,
        # not another season (the other checks list the rows)
        found, rec, _o = check(paste(P_2058, extra_k=IDS_2058))
        self.assertEqual((found, rec["ok"], len(rec["unknown"])), (2058, 0, 0))
        self.assertEqual(self.decisions(found, rec), (None, "odd"))

    def test_last_seasons_paste_stops_even_with_accept_paste(self):
        found, rec, others = check(paste(P_2057), others={2057: P_2057, 2056: season(5, IDS_2057)})
        self.assertEqual((found, rec["ok"], len(rec["unknown"])), (2057, 0, 30))
        self.assertEqual(self.decisions(found, rec), ("wrong season", "wrong season"))
        text = M.wrong_season_text(2058, found, rec, others)
        self.assertIn("the SP/RP paste is from season 2057, not 2058.", text)
        self.assertIn("100 of 100 pasted pitchers match the 2057 totals; 0 match the 2058 totals.", text)
        self.assertNotIn("—", text)

    def test_another_season_that_no_check_matches_still_stops(self):
        found, rec, others = check(paste(P_2057), others={2056: season(5, IDS_2057)})
        self.assertIsNone(found)
        self.assertEqual(self.decisions(found, rec), ("wrong season", "wrong season"))
        text = M.wrong_season_text(2058, found, rec, others)
        self.assertIn("the SP/RP paste is not from season 2058.", text)
        self.assertIn("30 did not pitch in MLB in 2058. It does not match 2056 either.", text)

    def test_other_seasons(self):
        self.assertEqual(M.other_seasons(2058, "2058-12-30"), [2057, 2056])
        self.assertEqual(M.other_seasons(2058, "2059-02-14"), [2057, 2056])
        self.assertEqual(M.other_seasons(2056, "2058-12-30"), [2055, 2057, 2054, 2058])
        self.assertEqual(M.other_seasons(2056, "2058-06-01"), [2055, 2057, 2054])

    def test_other_seasons_are_read_only_for_a_paste_that_does_not_match(self):
        asked = []

        def fake(base, slug, year, refresh=False):
            asked.append(year)
            return {2057: P_2057}.get(year)

        sp, rp = (paste(P_2058), HDR), ([], HDR)
        with mock.patch.object(M, "season_pitching", side_effect=fake):
            rec = M.reconcile_roles({"P": P_2058}, sp[0], HDR, [], HDR)
            self.assertEqual(M.find_paste_season("base", "blm", 2058, "2058-12-30", rec, sp, rp), (2058, {}))
            self.assertEqual(asked, [])
            sp = (paste(P_2057), HDR)
            rec = M.reconcile_roles({"P": P_2058}, sp[0], HDR, [], HDR)
            found, others = M.find_paste_season("base", "blm", 2058, "2058-12-30", rec, sp, rp)
        self.assertEqual((found, sorted(others), asked), (2057, [2057], [2057, 2056]))

    def test_a_season_statsplus_does_not_send_is_skipped(self):
        cache = os.path.join(INGEST, ".cache", "metadata_zz-test-no-cache_1900")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertIsNone(M.season_pitching("base", "zz-test-no-cache", 1900))
        self.assertIn("1900 is not checked", out.getvalue())
        self.assertFalse(os.path.exists(cache))


if __name__ == "__main__":
    unittest.main(verbosity=2)
