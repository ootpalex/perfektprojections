"""
test_slot_shares.py - tools/slot_shares.py: the share arithmetic, the actuals loader (innings in
thirds, SP/RP rule, DH starts as batting starts minus fielding starts), and the shipped weights file.

    python tgs-viz/tools/tests/test_slot_shares.py
    python -m pytest tgs-viz/tools/tests/test_slot_shares.py -q

Offline; the loader cases build a tiny actuals folder in a temp directory. Writes nothing else.
"""
import csv
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VIZ = os.path.dirname(TOOLS)
REPO = os.path.dirname(VIZ)
sys.path.insert(0, TOOLS)

import slot_shares as S  # noqa: E402


class Arithmetic(unittest.TestCase):
    def test_share_vectors_rank_and_normalise(self):
        v = S.share_vectors({"A": [100.0, 300.0, 0.0, 600.0], "B": [50.0, 50.0]})
        self.assertEqual(len(v), 2)
        self.assertEqual([round(x, 6) for x in v[0]], [0.6, 0.3, 0.1])        # zero usage dropped
        self.assertEqual([round(x, 6) for x in v[1]], [0.5, 0.5])

    def test_mean_curve_pads_missing_ranks_with_zero_and_reports_tail(self):
        v = S.share_vectors({"A": [100.0, 300.0, 600.0], "B": [50.0, 50.0]})
        c = S.mean_curve(v, 2)
        self.assertAlmostEqual(c["shares"][0], (0.6 + 0.5) / 2)
        self.assertAlmostEqual(c["shares"][1], (0.3 + 0.5) / 2)
        self.assertAlmostEqual(c["tail"], (0.1 + 0.0) / 2)                    # beyond depth 2
        self.assertEqual(c["n"], 2)
        c3 = S.mean_curve(v, 3)
        self.assertAlmostEqual(c3["shares"][2], 0.05)                         # B has no third man: counts as 0
        self.assertAlmostEqual(sum(c3["shares"]) + c3["tail"], 1.0)

    def test_mean_curve_standard_error(self):
        v = [np.array([0.7, 0.3]), np.array([0.5, 0.5])]
        c = S.mean_curve(v, 2)
        # sd of [0.7, 0.5] with ddof=1 is 0.141421; se = sd / sqrt(2) = 0.1
        self.assertAlmostEqual(c["se"][0], 0.1, places=6)

    def test_empty_input(self):
        c = S.mean_curve([], 3)
        self.assertEqual(c["shares"], [0.0, 0.0, 0.0])
        self.assertEqual(c["n"], 0)


class Loader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="slot-shares-test-")
        d = os.path.join(self.tmp, "backtest", "actuals", "XXX", "2000")
        os.makedirs(d)
        self.write(d, "fielding.csv", ["league_id", "level_id", "team_id", "player_id", "position", "ip", "ipf", "gs"], [
            # team 1 catchers: 900 2/3 inn and 100 1/3 inn; team 2: one catcher
            [9, 1, 1, 11, 2, 900, 2, 100], [9, 1, 1, 12, 2, 100, 1, 10], [9, 1, 2, 21, 2, 1000, 0, 120],
            [9, 1, 1, 11, 1, 5, 0, 0],            # position 1 (pitcher) is not a fielding slot
            [9, 2, 1, 13, 2, 500, 0, 50],         # level 2 is ignored
            [8, 1, 1, 14, 2, 500, 0, 50],         # another league is ignored
        ])
        self.write(d, "batting.csv", ["league_id", "level_id", "split_id", "team_id", "player_id", "gs"], [
            [9, 1, 1, 1, 11, 110], [9, 1, 1, 1, 12, 10], [9, 1, 1, 1, 15, 52],   # 15 started 52 games, in no field slot: DH
            [9, 1, 2, 1, 15, 99],                                               # split 2 is not the regular season
        ])
        self.write(d, "pitching.csv", ["league_id", "level_id", "split_id", "team_id", "player_id", "g", "gs", "ip", "ipf"], [
            [9, 1, 1, 1, 31, 30, 30, 180, 1],     # starter
            [9, 1, 1, 1, 32, 40, 20, 100, 0],     # exactly half his games started: SP
            [9, 1, 1, 1, 33, 40, 19, 90, 2],      # just under half: RP
            [9, 1, 2, 1, 34, 10, 10, 50, 0],      # split 2 ignored
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def write(d, name, head, rows):
        with open(os.path.join(d, name), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(head)
            w.writerows(rows)

    def test_actuals_loader(self):
        u = S.load_actuals("XXX", 2000, 9, viz=self.tmp)
        self.assertEqual(sorted(u["C"]), ["1", "2"])
        self.assertAlmostEqual(sorted(u["C"]["1"])[1], 900 + 2 / 3)           # ipf is thirds
        self.assertAlmostEqual(sum(u["C"]["1"]), 900 + 2 / 3 + 100 + 1 / 3)
        self.assertEqual(u["DH"]["1"].count(52), 1)                           # 52 = batting starts - 0
        # 11 started 110 games and 100 of them behind the plate -> 10 as DH; 12 started 10, all at C -> 0
        self.assertEqual(sorted(u["DH"]["1"]), [0, 10, 52])
        self.assertAlmostEqual(sorted(u["SP"]["1"])[1], 180 + 1 / 3)
        self.assertEqual(len(u["SP"]["1"]), 2)
        self.assertAlmostEqual(u["RP"]["1"][0], 90 + 2 / 3)

    def test_curves_ignore_orgs_without_a_catcher(self):
        usage = {p: {} for p in S.ORDER}
        usage["C"] = {"T1": [100.0]}
        usage["SP"] = {"T1": [60.0, 40.0], "Retired": [10.0]}
        c = S.curves(usage, ["SP"])
        self.assertEqual(c["SP"]["n"], 1)
        self.assertAlmostEqual(c["SP"]["shares"][0], 0.6)


class ShippedWeights(unittest.TestCase):
    def test_weights_file_is_consistent(self):
        path = os.path.join(REPO, "docs", "phase2", "slot_shares.json")
        if not os.path.exists(path):
            self.skipTest("no docs/phase2/slot_shares.json")
        with open(path) as fh:
            d = json.load(fh)
        self.assertIn("NOT read by the engine", d["gated"])
        for lg in ("BLM", "SSB", "TGS", "ALL"):
            for pos, c in d["leagues"][lg].items():
                total = sum(c["shares"]) + c["tail"]
                self.assertAlmostEqual(total, 1.0, places=6, msg="%s %s" % (lg, pos))
                self.assertEqual(sorted(c["shares"], reverse=True), c["shares"], "%s %s not descending" % (lg, pos))


if __name__ == "__main__":
    unittest.main()
