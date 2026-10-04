"""
test_ssb_metadata_compare.py - the arithmetic of backtest/ssb_metadata_compare.py (the constants table
and the per-group shift statistics), on small made-up inputs. The engine pricing half needs the BLM
workbooks and is not run here.

    python tgs-viz/tools/tests/test_ssb_metadata_compare.py
"""
import math
import os
import sys
import unittest

import numpy as np
import pandas as pd

TESTS = os.path.dirname(os.path.abspath(__file__))
BACKTEST = os.path.join(os.path.dirname(os.path.dirname(TESTS)), "backtest")
if BACKTEST not in sys.path:
    sys.path.insert(0, BACKTEST)
import ssb_metadata_compare as X  # noqa: E402


def doc(**vals):
    return {"groups": {"anchors": [{"section": "hitting", "label": k, "cell": f"F{i + 2}", "value": v}
                                   for i, (k, v) in enumerate(vals.items())]}}


class Table(unittest.TestCase):
    def test_difference_and_percent_of_the_blm_value(self):
        t = X.comparison_table(doc(Eye=50.0, Power=-4.0, Zero=0.0), doc(Eye=51.0, Power=-5.0, Zero=0.3),
                               doc(Eye=49.0, Power=-4.0, Zero=0.0))
        eye, power, zero = (t[t.label == k].iloc[0] for k in ("Eye", "Power", "Zero"))
        self.assertAlmostEqual(eye.d, 1.0)
        self.assertAlmostEqual(eye.pct, 2.0)                    # 1 on a base of 50
        self.assertAlmostEqual(power.d, -1.0)
        self.assertAlmostEqual(power.pct, -25.0)                # a negative base: the percent is of |BLM|, so the sign follows d
        self.assertTrue(math.isnan(zero.pct))                   # BLM is 0: no percent
        self.assertAlmostEqual(eye.vintage_d, -2.0)             # alt - season-end
        self.assertAlmostEqual(eye.pct_alt, -2.0)

    def test_without_an_alt_build_there_are_no_alt_columns(self):
        t = X.comparison_table(doc(Eye=50.0), doc(Eye=51.0))
        self.assertNotIn("SSB_alt", t.columns)


class Shift(unittest.TestCase):
    def test_group_statistics_and_rank_correlation(self):
        j = pd.DataFrame({"kind": ["H", "H", "H", "SP", "SP", "RP"],
                          "WAA_a": [1.0, 2.0, 3.0, 0.0, 1.0, -2.0],
                          "WAA_b": [0.9, 1.9, 2.9, 0.5, 1.5, np.nan]})
        d = (j.WAA_b - j.WAA_a).astype(float)
        s = X.shift_stats(j, d)
        self.assertEqual(s["H"]["n"], 3)
        self.assertAlmostEqual(s["H"]["mean"], -0.1)
        self.assertAlmostEqual(s["H"]["rho"], 1.0)              # order unchanged
        self.assertAlmostEqual(s["SP"]["mean"], 0.5)
        self.assertAlmostEqual(s["SP"]["sd"], 0.0)
        self.assertNotIn("RP", s)                               # its only player has no price after the swap
        self.assertEqual(s["all"]["n"], 5)
        self.assertAlmostEqual(s["all"]["maxabs"], 0.5)

    def test_a_reversed_order_gives_rho_minus_one(self):
        j = pd.DataFrame({"kind": ["H"] * 3, "WAA_a": [1.0, 2.0, 3.0], "WAA_b": [3.0, 2.0, 1.0]})
        self.assertAlmostEqual(X.shift_stats(j, (j.WAA_b - j.WAA_a).astype(float))["H"]["rho"], -1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
