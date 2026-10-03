"""Tests for backtest/referee_fielding.py (Phase 2 row 10, the fielding referee).

  python -m pytest tgs-viz/tools/tests/test_referee_fielding.py -q
  python tgs-viz/tools/tests/test_referee_fielding.py

Needs pandas (the backtest interpreter has it; the plain requirements.txt
interpreter does not, so the module skips there). The last class also needs the
BLM workbook and public/data/BLM/hitters.json from the repo and skips without
them.

What is pinned:
  - the pieces of arithmetic (height, innings, interpolation, WLS, HC1, binomial
    floor, cluster bootstrap) against independent loop / numpy references;
  - a frozen 14-player SS fixture built so the true slope is EXACTLY 1.2: made
    counts are 10000 * (0.72 + 1.2 * engine_rate), so the referee must return
    slope 1.2 and intercept -1.2 * mean(model);
  - the engine channel against hitters.compute() itself, with the error / DP /
    arm terms zeroed so RunsP = pmaa * out value (both the curve and the linear
    branch);
  - the two-sample governance verdicts.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VIZ = os.path.dirname(TOOLS)
REPO = os.path.dirname(VIZ)
FIX = os.path.join(HERE, "fixtures", "referee_fielding")
sys.path.insert(0, os.path.join(VIZ, "backtest"))
sys.path.insert(0, os.path.join(VIZ, "engine"))

try:
    import numpy as np
    import pandas as pd
    import referee_fielding as RF
except ImportError:           # plain interpreter without pandas
    np = pd = RF = None


# The toy calibration the fixture was generated from (see the module docstring).
TOY_CURVES = {"positions": {"SS": {"knots": [[40, -0.05], [60, 0.0], [80, 0.06]],
                                   "offset": 0.001, "m2": 0.001}}}
TOY_DP = {"T15": 500.0, "H38": 0.75, "H39": 0.9}


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class Arithmetic(unittest.TestCase):
    def test_height_cm(self):
        self.assertAlmostEqual(RF.height_cm("6' 2\""), 6 * 30.48 + 2 * 2.54, places=9)
        self.assertAlmostEqual(RF.height_cm("5' 11\""), 5 * 30.48 + 11 * 2.54, places=9)
        self.assertAlmostEqual(RF.height_cm("6' 5'"), 6 * 30.48 + 5 * 2.54, places=9)  # dashboard export spelling
        self.assertTrue(np.isnan(RF.height_cm("n/a")))

    def test_ip_thirds(self):
        got = RF.ip_thirds(pd.Series([123.0, 123.1, 123.2, 0.2, "x"])).tolist()
        self.assertAlmostEqual(got[1], 123 + 1 / 3, places=9)
        self.assertAlmostEqual(got[2], 123 + 2 / 3, places=9)
        self.assertAlmostEqual(got[3], 2 / 3, places=9)
        self.assertTrue(np.isnan(got[4]))

    def test_interp_matches_the_engine_helper(self):
        import hitters as H
        knots = [[35.0, -0.03], [40.0, -0.004], [50.0, 0.004], [65.0, 0.0101], [70.0, 0.0101]]
        r = np.array([20.0, 35.0, 37.5, 40.0, 47.0, 65.0, 67.0, 70.0, 80.0])
        mine = RF.interp_knots(knots, r)
        for v, m in zip(r, mine):
            self.assertAlmostEqual(H._interp_knots(knots, float(v)), m, places=12)

    def test_wls_matches_polyfit(self):
        x = np.array([1.0, 2.0, 3.5, 4.0, 7.0])
        y = np.array([2.1, 3.9, 7.4, 7.7, 14.6])
        w = np.array([1.0, 2.0, 1.0, 3.0, 1.5])
        a, b = RF.wls(x, y, w)
        slope, icpt = np.polyfit(x, y, 1, w=np.sqrt(w))     # polyfit squares the weights
        self.assertAlmostEqual(b, slope, places=10)
        self.assertAlmostEqual(a, icpt, places=10)

    def test_hc1_against_explicit_sandwich(self):
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([0.3, 0.9, 2.4, 2.7, 4.6, 4.8])
        w = np.array([1.0, 1.0, 2.0, 2.0, 1.0, 3.0])
        a, b = RF.wls(x, y, w)
        e = y - a - b * x
        # hand-rolled with plain loops: bread = inv(sum w x x'), meat = sum (w e)^2 x x'
        S = np.zeros((2, 2))
        M = np.zeros((2, 2))
        for xi, wi, ei in zip(x, w, e):
            v = np.array([1.0, xi])
            S += wi * np.outer(v, v)
            M += (wi * ei) ** 2 * np.outer(v, v)
        V = np.linalg.inv(S) @ M @ np.linalg.inv(S) * len(x) / (len(x) - 2)
        np.testing.assert_allclose(RF.hc1_se(x, y, w, (a, b)), np.sqrt(np.diag(V)), rtol=1e-10)

    def test_binomial_floor_is_zero_without_noise_and_positive_with(self):
        x = np.linspace(0, 5, 6)
        w = np.full(6, 100.0)
        self.assertTrue(np.allclose(RF.binomial_floor_se(x, w, np.zeros(6)), 0.0))
        self.assertTrue(np.all(RF.binomial_floor_se(x, w, np.full(6, 4.0)) > 0))

    def test_cluster_bootstrap_matches_a_loop_with_the_same_draws(self):
        x = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        y = np.array([0.2, 1.1, 1.8, 3.3, 3.9, 5.2, 5.8, 7.4])
        w = np.array([1.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 2.0])
        ids = np.array(list("abcdefgh"))
        got = RF.cluster_boot_se(x, y, w, ids, n_boot=500, seed=11)
        rs = np.random.default_rng(11)
        pick = rs.integers(0, 8, size=(500, 8))
        A, B = [], []
        for row in pick:
            mult = np.bincount(row, minlength=8)
            a, b = RF.wls(x, y, w * mult)       # zero-weight rows drop out exactly
            A.append(a)
            B.append(b)
        np.testing.assert_allclose(got, [np.std(A, ddof=1), np.std(B, ddof=1)], rtol=1e-9)

    def test_cluster_bootstrap_resamples_whole_clusters(self):
        # two rows per cluster with identical values: resampling by cluster keeps the
        # pairs together, so the SE is that of 4 distinct points, not 8
        x = np.array([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0])
        y = np.array([0.1, 0.1, 1.2, 1.2, 1.9, 1.9, 3.2, 3.2])
        w = np.ones(8)
        by_cluster = RF.cluster_boot_se(x, y, w, np.array([0, 0, 1, 1, 2, 2, 3, 3]), n_boot=800, seed=3)
        by_row = RF.cluster_boot_se(x, y, w, np.arange(8), n_boot=800, seed=3)
        self.assertGreater(by_cluster[1], by_row[1])


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class Loaders(unittest.TestCase):
    def test_observed_from_buckets_uses_all_six_for_chances_and_five_for_made(self):
        df = pd.DataFrame({"ID": ["1", "2"], "IP": ["10.1", "0.0"],
                           "BIZ-R": [10, 5], "BIZ-L": [4, 0], "BIZ-E": [3, 0], "BIZ-U": [2, 0],
                           "BIZ-Z": [1, 0], "BIZ-I": [5, 0],
                           "BIZ-Rm": [9, 0], "BIZ-Lm": [3, 0], "BIZ-Em": [2, 0], "BIZ-Um": [1, 0], "BIZ-Zm": [0, 0]})
        o = RF.observed_from_buckets(df)
        self.assertEqual(len(o), 1)                  # the 0-inning row is dropped
        self.assertEqual(o.loc[0, "tot"], 25)        # impossible bucket counts as a chance
        self.assertEqual(o.loc[0, "made"], 15)
        self.assertAlmostEqual(o.loc[0, "ipc"], 10 + 1 / 3, places=9)

    def test_actuals_sums_a_traded_player_and_reads_ipf_as_thirds(self):
        base = dict(year=2057, level_id=1, league_id=144, split_id=0, position=6)
        rows = [dict(base, player_id=7, ip=100, ipf=2, **{f"opps_{i}": 10 for i in range(6)},
                     **{f"opps_made_{i}": 5 for i in range(6)}),
                dict(base, player_id=7, ip=50, ipf=1, **{f"opps_{i}": 4 for i in range(6)},
                     **{f"opps_made_{i}": 2 for i in range(6)}),
                dict(base, player_id=8, ip=10, ipf=0, **{f"opps_{i}": 1 for i in range(6)},
                     **{f"opps_made_{i}": 1 for i in range(6)}),
                dict(base, level_id=2, player_id=9, ip=500, ipf=0, **{f"opps_{i}": 9 for i in range(6)},
                     **{f"opps_made_{i}": 9 for i in range(6)})]
        path = os.path.join(FIX, "_actuals_tmp.csv")
        pd.DataFrame(rows).to_csv(path, index=False)
        try:
            ss = RF.load_actuals_observed(path, 2057)["SS"].set_index("id")
        finally:
            os.remove(path)
        self.assertEqual(sorted(ss.index), ["7", "8"])             # the minor-league row is excluded
        self.assertEqual(ss.loc["7", "tot"], 60 + 24)
        self.assertEqual(ss.loc["7", "made"], 30 + 12)
        self.assertAlmostEqual(ss.loc["7", "ipc"], 100 + 2 / 3 + 50 + 1 / 3, places=9)


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class FrozenFixture(unittest.TestCase):
    """14 SS whose made counts are 10000 * (0.72 + 1.2 * engine rate), engine rate from TOY_CURVES."""

    @classmethod
    def setUpClass(cls):
        cls.obs = RF.observed_from_buckets(pd.read_csv(os.path.join(FIX, "fielding_data_ss.csv")))
        fr = pd.read_csv(os.path.join(FIX, "fielding_ratings.csv"))
        cls.ratings = RF._ratings_frame(fr, "ID", "IF RNG", "IF ARM", "OF RNG", "HT")

    def test_fixture_shape(self):
        self.assertEqual(len(self.obs), 14)
        self.assertTrue((self.obs["tot"] == 10000).all())
        self.assertEqual(int(self.obs["made"].sum()), 110382)   # 14 x 10000 x (0.72 + 1.2 rate), rounded

    def test_channel_by_hand(self):
        d = self.obs.merge(self.ratings, left_on="id", right_index=True)
        x = RF.model_range_runs("SS", d, TOY_CURVES, TOY_DP)
        # player 0: IFR 40, IFA 40 -> (-0.05 - 0.001 + 40 * 0.001) * 500 * 0.75 = -4.125
        self.assertAlmostEqual(x[0], (-0.05 - 0.001 + 0.04) * 500 * 0.75, places=9)
        # player 4: IFR 60, IFA 45 -> (0 - 0.001 + 0.045) * 500 * 0.75 = 16.5
        self.assertAlmostEqual(x[4], 0.044 * 500 * 0.75, places=9)
        # player 12: IFR 80, IFA 75 -> (0.06 - 0.001 + 0.075) * 500 * 0.75 = 50.25
        self.assertAlmostEqual(x[12], 0.134 * 500 * 0.75, places=9)

    def test_referee_recovers_the_built_in_slope(self):
        r = RF.referee_position("SS", self.obs, self.ratings, TOY_CURVES, TOY_DP, min_chances=20, n_boot=400)
        self.assertEqual(r["n"], 14)
        self.assertEqual(r["n_unmatched"], 0)
        self.assertAlmostEqual(r["pa_obs"], 500.0, places=9)              # 10000 chances / 24000 IP * 1200
        self.assertAlmostEqual(r["slope"], 1.2, places=9)
        # equal weights: y = 1.2 * (x - mean(x))  =>  intercept = -1.2 * mean(model)
        d = self.obs.merge(self.ratings, left_on="id", right_index=True)
        x = RF.model_range_runs("SS", d, TOY_CURVES, TOY_DP)
        self.assertAlmostEqual(r["intercept"], -1.2 * x.mean(), places=9)
        self.assertAlmostEqual(r["mean_model"], x.mean(), places=9)
        self.assertAlmostEqual(r["r2w"], 1.0, places=9)
        self.assertGreater(r["se_slope"], 0.0)
        self.assertTrue(np.isfinite(r["se_slope"]))
        # unfitted skill = 1 - sum w((y-ybar)-(x-xbar))^2 / sum w (y-ybar)^2
        #               = 1 - (0.2^2 var x) / (1.2^2 var x) = 1 - 0.04 / 1.44
        self.assertAlmostEqual(r["skill_unfitted"], 1 - 0.04 / 1.44, places=9)

    def test_out_value_cancels_in_the_slope(self):
        a = RF.referee_position("SS", self.obs, self.ratings, TOY_CURVES, TOY_DP, n_boot=200)
        b = RF.referee_position("SS", self.obs, self.ratings, TOY_CURVES, {**TOY_DP, "H38": 0.5}, n_boot=200)
        self.assertAlmostEqual(a["slope"], b["slope"], places=9)
        self.assertAlmostEqual(b["intercept"], a["intercept"] * 0.5 / 0.75, places=9)

    def test_unmatched_players_are_counted_not_silently_dropped(self):
        short = self.ratings.drop(self.ratings.index[:3])
        r = RF.referee_position("SS", self.obs, short, TOY_CURVES, TOY_DP, n_boot=100)
        self.assertEqual(r["n"], 11)
        self.assertEqual(r["n_unmatched"], 3)

    def test_bootstrap_is_reproducible(self):
        a = RF.referee_position("SS", self.obs, self.ratings, TOY_CURVES, TOY_DP, n_boot=300, seed=5)
        b = RF.referee_position("SS", self.obs, self.ratings, TOY_CURVES, TOY_DP, n_boot=300, seed=5)
        self.assertEqual(a["se_slope"], b["se_slope"])

    def test_linear_branch_reads_the_sheet_cells(self):
        dp = {**TOY_DP, "P23": 60.0, "L23": 0.002, "Q23": 50.0, "M23": 0.001, "K23": 0.01}
        d = self.obs.merge(self.ratings, left_on="id", right_index=True)
        x = RF.model_range_runs("SS", d, None, dp)                        # no curves -> linear cells
        want = ((d["IFR"] - 60.0) * 0.002 + (d["IFA"] - 50.0) * 0.001 + 0.01) * 500 * 0.75
        np.testing.assert_allclose(x, want.to_numpy(), rtol=1e-12)
        y = RF.model_range_runs("SS", d, TOY_CURVES, dp, linear=True)
        np.testing.assert_allclose(y, x, rtol=1e-12)


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class Governance(unittest.TestCase):
    @staticmethod
    def _s(slope, se):
        return {"pos": "LF", "slope": slope, "se_slope": se}

    def test_replicated_needs_both_samples_beyond_two_se_in_the_same_direction(self):
        v = RF.two_sample_verdict(self._s(0.5, 0.2), self._s(0.6, 0.15))         # z -2.5, -2.67
        self.assertEqual(v["verdict"], "replicated")

    def test_one_sample_is_only_a_watch(self):
        v = RF.two_sample_verdict(self._s(0.5, 0.2), self._s(1.0, 0.15))
        self.assertEqual(v["verdict"], "watch")

    def test_opposite_signs_are_a_watch_not_a_replication(self):
        v = RF.two_sample_verdict(self._s(0.5, 0.2), self._s(1.6, 0.2))
        self.assertEqual(v["verdict"], "watch")

    def test_neither_beyond_is_consistent_with_one(self):
        v = RF.two_sample_verdict(self._s(0.9, 0.2), self._s(1.1, 0.2))
        self.assertEqual(v["verdict"], "consistent-with-1")

    def test_pooled_slope_is_inverse_variance_weighted(self):
        v = RF.two_sample_verdict(self._s(0.5, 0.1), self._s(1.0, 0.2))
        # weights 100 and 25 -> (0.5*100 + 1.0*25)/125 = 0.6; se = 1/sqrt(125)
        self.assertAlmostEqual(v["pooled_slope"], 0.6, places=12)
        self.assertAlmostEqual(v["se_pooled"], 1 / np.sqrt(125.0), places=12)


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class FlowCheck(unittest.TestCase):
    def test_flags_only_positions_beyond_ten_percent(self):
        rows = [{"pos": "2B", "pa_obs": 568.5, "pa_model": 483.9},     # x1.175
                {"pos": "SS", "pa_obs": 526.9, "pa_model": 523.6},     # x1.006
                {"pos": "3B", "pa_obs": 356.8, "pa_model": 434.3},     # x0.822
                {"pos": "RF", "pa_obs": 425.4 * 1.09, "pa_model": 425.4}]         # +9%: inside the band
        got = RF.flow_check(rows)
        self.assertEqual([p for p, _ in got], ["2B", "3B"])
        self.assertAlmostEqual(got[0][1], 568.5 / 483.9, places=12)


@unittest.skipIf(RF is None, "pandas not installed in this interpreter")
class EngineParity(unittest.TestCase):
    """The referee's channel must equal what hitters.compute() produces for the same player
    when the error / DP / arm terms are zeroed: RunsP = pmaa * H38 (or H39)."""

    @classmethod
    def setUpClass(cls):
        wb = os.path.join(REPO, "The Sheets BLM", "The Sheet Hitters.xlsx")
        js = os.path.join(VIZ, "public", "data", "BLM", "hitters.json")
        if not (os.path.exists(wb) and os.path.exists(js)):
            raise unittest.SkipTest("BLM workbook / hitters.json not in this checkout")
        try:
            import hitters as H
        except ImportError:
            raise unittest.SkipTest("openpyxl not installed")
        cls.H = H
        cls.curves, cls.dp = RF.load_calibration("BLM")
        _, cls.filt, cls.park = H.scan_consts(wb)
        recs = json.load(open(js, encoding="utf-8"))
        ing = os.path.join(VIZ, "ingest")
        sys.path.insert(0, ing)
        import ratings as R
        cls.p_list = []
        for rec in (R.prep(r) for r in recs[:400]):
            p, ok = {}, True
            for col in H.RATING_COLS:
                v = rec.get(col)
                if col in ("B", "T", "Name", "POS"):
                    p[col] = v
                else:
                    nv = 20.0 if isinstance(v, str) and v.strip() == "-" else H.num(v)
                    p[col] = nv
                    if nv is None and col not in H.OPTIONAL:
                        ok = False
            if ok:
                cls.p_list.append(p)
        if len(cls.p_list) < 50:
            raise unittest.SkipTest("too few usable BLM hitter records")

    # engine cell triples that zero the non-range terms, per position:
    #   (IFE/OFE key, its P, L, K cells), plus the TDP / OFA key and cells where the position has one
    ZERO = {
        "1B": [("IF ERR", "P11", "L11", "K11")],
        "2B": [("IF ERR", "P15", "L15", "K15"), ("TDP", "P17", "L17", "K17")],
        "3B": [("IF ERR", "P21", "L21", "K21")],
        "SS": [("IF ERR", "P25", "L25", "K25"), ("TDP", "Q25", "L45", "K45")],
        "LF": [("OF ERR", "P29", "L29", "K29"), ("OF ARM", "P31", "L31", "K31")],
        "CF": [("OF ERR", "P35", "L35", "K35"), ("OF ARM", "P37", "L37", "K37")],
        "RF": [("OF ERR", "P41", "L41", "K41"), ("OF ARM", "P43", "L43", "K43")],
    }

    def _engine_channel(self, pos, curves):
        out = []
        for p in self.p_list:
            q = dict(p)
            for key, pc, lc, kc in self.ZERO[pos]:
                q[key] = self.dp[pc] - self.dp[kc] / self.dp[lc]       # (x - P) * L + K == 0
            res = self.H.compute(q, self.dp, self.filt, self.park, "BLM", fielding=curves)
            out.append(res[f"{pos} RunsP"])
        return np.array(out)

    def _referee_channel(self, pos, linear):
        r = pd.DataFrame({"IFR": [p["IF RNG"] for p in self.p_list], "IFA": [p["IF ARM"] for p in self.p_list],
                          "OFR": [p["OF RNG"] for p in self.p_list], "ht_cm": [p["HT Sort"] for p in self.p_list]})
        return RF.model_range_runs(pos, r, self.curves, self.dp, linear=linear)

    def test_curve_channel_equals_engine_runs(self):
        for pos in RF.POSITIONS:
            with self.subTest(pos=pos):
                np.testing.assert_allclose(self._referee_channel(pos, False),
                                           self._engine_channel(pos, self.curves), rtol=1e-9, atol=1e-9)

    def test_linear_channel_equals_engine_runs(self):
        for pos in RF.POSITIONS:
            with self.subTest(pos=pos):
                np.testing.assert_allclose(self._referee_channel(pos, True),
                                           self._engine_channel(pos, None), rtol=1e-9, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
