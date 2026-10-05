"""
test_war.py - engine/war.py: WAR = WAA + the league's replacement credit (Phase 1).

    python -m pytest tgs-viz/tools/tests/test_war.py -q
"""
import json
import os
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(TESTS))
sys.path.insert(0, os.path.join(VIZ, "engine"))

import war as W  # noqa: E402

REPL = {"hitter": 1.8, "sp": 2.4, "rp": 0.3, "league": "X", "source": "test"}


def hitter(**kw):
    rec = {f"{p} Eligible": False for p in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")}
    rec.update(kw)
    return rec


class Load(unittest.TestCase):
    def table(self, obj):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "replacement.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return p

    def test_own_proxy_missing(self):
        p = self.table({"A": {"hitter": 1, "sp": 2, "rp": 0.5, "source": "s"}, "B": {"use": "A"},
                        "C": {"use": "B"}, "D": {"hitter": 1}})
        self.assertEqual(W.load_replacement("A", p)["sp"], 2.0)
        b = W.load_replacement("B", p)
        self.assertEqual((b["hitter"], b["league"]), (1.0, "A"))
        self.assertIsNone(W.load_replacement("C", p))      # one proxy hop only
        self.assertIsNone(W.load_replacement("D", p))      # incomplete entry
        self.assertIsNone(W.load_replacement("Z", p))      # no entry: no WAR columns
        self.assertIsNone(W.load_replacement("A", p + ".missing"))

    def test_committed_table(self):
        ssb, rg = W.load_replacement("SSB"), W.load_replacement("RG")
        self.assertEqual(ssb["league"], "SSB")              # SSB's own 2043 measurement (2026-10-05)
        self.assertEqual({k: ssb[k] for k in ("hitter", "sp", "rp")}, {"hitter": 1.872, "sp": 2.63, "rp": 0.35})
        self.assertEqual(rg["league"], "BLM")               # RG still on BLM's credits (proxy)

    def test_catcher_share(self):
        self.assertAlmostEqual(W.catcher_share("BLM"), 500 / 600)
        self.assertAlmostEqual(W.catcher_share("NOPE"), 500 / 600)


class Hitters(unittest.TestCase):
    def test_columns_catcher_and_max(self):
        rec = hitter(**{"C Eligible": True, "SS Eligible": False,
                        "C WAA wtd": 1.0, "SS WAA wtd": 1.5, "DH WAA wtd": 0.5, "C WAA P": 2.0})
        out = W.hitter_war(rec, REPL, 500 / 600)
        self.assertAlmostEqual(out["C WAR wtd"], 1.0 + 1.8 * 500 / 600)
        self.assertAlmostEqual(out["SS WAR wtd"], 1.5 + 1.8)        # written, like SS WAA wtd
        self.assertAlmostEqual(out["Max WAR wtd"], 1.0 + 1.5)      # SS not eligible; C beats DH
        self.assertEqual(out["Best Pos WAR"], "C")
        self.assertAlmostEqual(out["MAX WAR P"], 2.0 + 1.5)
        self.assertIsNone(out["1B WAR wtd"])                     # no WAA, no WAR

    def test_catcher_credit_can_move_best_pos(self):
        # C 1.0 vs DH 0.8 in WAA; with the 5/6 catcher credit DH wins in WAR
        rec = hitter(**{"C Eligible": True, "C WAA wtd": 1.0, "DH WAA wtd": 0.8})
        self.assertEqual(W.hitter_war(rec, REPL, 500 / 600)["Best Pos WAR"], "DH")

    def test_no_eligible_values(self):
        out = W.hitter_war(hitter(), REPL, 500 / 600)
        self.assertIsNone(out["Max WAR wtd"])
        self.assertIsNone(out["Best Pos WAR"])


class Pitchers(unittest.TestCase):
    def test_columns(self):
        out = W.pitcher_war({"WAA wtd": 1.0, "WAA wtd RP": 0.2, "WAA vR": None, "WAP": 3.0}, REPL)
        self.assertAlmostEqual(out["WAR wtd"], 3.4)
        self.assertAlmostEqual(out["WAR wtd RP"], 0.5)
        self.assertIsNone(out["WAR vR"])
        self.assertAlmostEqual(out["WARP"], 5.4)
        self.assertIsNone(out["WARP RP"])

    def test_add_war_none_is_a_no_op(self):
        recs = [{"WAA wtd": 1.0}]
        self.assertEqual(W.add_war(recs, "pitchers", None), [{"WAA wtd": 1.0}])
        W.add_war(recs, "pitchers", REPL)
        self.assertIn("WAR wtd", recs[0])


if __name__ == "__main__":
    unittest.main()
