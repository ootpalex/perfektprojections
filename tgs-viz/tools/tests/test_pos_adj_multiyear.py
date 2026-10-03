"""
test_pos_adj_multiyear.py - engine/pos_adj_multiyear.py (gated candidate positional
adjustments) against his pos_adj_calc, hand arithmetic and an independent dense
least-squares reference.

    python tgs-viz/tools/tests/test_pos_adj_multiyear.py

Offline and read-only: nothing is written, StatsPlus is never asked.
"""
import json
import os
import sys
import unittest

import numpy as np

TESTS = os.path.dirname(os.path.abspath(__file__))
TGS = os.path.dirname(os.path.dirname(TESTS))
ENGINE = os.path.join(TGS, "engine")
sys.path.insert(0, ENGINE)

import metadata_calibrate as mc  # noqa: E402
import pos_adj_multiyear as M  # noqa: E402

BLM_IN = os.path.join(ENGINE, "calib", "BLM", "metadata_inputs")
POS = mc.POSITIONS


def toy_season(year=2050):
    """Six hitters that exercise every branch of his accumulation: players who played one
    position only, one who split innings across positions, one with a DH remainder, and a
    right fielder (his RF branch test is the quirk)."""
    ip = {p: {} for p in POS}
    plan = {  # id: (PA, OFF runs, {pos: innings})
        1: (600, 12.0, {"1B": 1200.0}),
        2: (620, -4.0, {"SS": 1250.0}),
        3: (580, 3.5, {"2B": 700.0, "3B": 500.0}),
        4: (500, 6.0, {"RF": 1000.0}),
        5: (450, -2.0, {"C": 600.0}),            # 450 PA but only 600 IP: DH remainder
        6: (550, 1.0, {"LF": 600.0, "CF": 500.0, "RF": 90.0}),
    }
    pa, off, ipc = {}, {}, {}
    for i, (p_, o, d) in plan.items():
        pa[i], off[i] = float(p_), float(o)
        ipc[i] = float(sum(d.values()))
        for pos, v in d.items():
            ip[pos][i] = v
    raw = {p: float(sum(ip[p].values())) for p in POS}
    zr = {p: {i: 0.0 for i in ip[p]} for p in POS}
    return {"year": year, "label": "toy", "pa": pa, "off": off, "ipc": ipc, "ip": ip,
            "raw_ip": raw, "zr": zr, "of_arm": {}, "lg": {}}


class OffenceHalf(unittest.TestCase):
    def test_reproduces_his_blm_p_cells(self):
        s = M.load_season(BLM_IN, 2058)
        got = M.his_pos_adj(M.offense_accumulate(s))
        cells = json.load(open(os.path.join(ENGINE, "calib", "BLM", "metadata-latest.json"), encoding="utf-8"))["cells"]
        for p in M.NINE:
            self.assertAlmostEqual(got[p], cells[M.PCELL[p]], places=9, msg=p)

    def test_matches_his_loop_on_toy_season(self):
        s = toy_season()
        acc = M.offense_accumulate(s)
        mine = M.his_pos_adj(acc)
        ipc_rows = [{"ID": str(i), "IP": str(v)} for i, v in s["ipc"].items()]   # whole innings: x.0
        _, theirs = mc.pos_adj_calc({"pa_by_id": s["pa"], "off_by_id": s["off"]}, ipc_rows, s["ip"], s["raw_ip"])
        for p in M.NINE:
            self.assertAlmostEqual(mine[p], theirs[p], places=10, msg=p)

    def test_toy_hand_values(self):
        """Hand arithmetic for the clean cases. m2 = sum(IP)/sum(PA) = 5740/3300 per PA."""
        s = toy_season()
        acc = M.offense_accumulate(s)
        m2 = sum(s["ipc"].values()) / sum(s["pa"].values())
        self.assertAlmostEqual(acc["m2"], m2, places=12)
        # 1B: player 1 played only 1B and has no DH time (PA*m2 = 1043.6 < 1200): all 12.0 runs
        self.assertAlmostEqual(acc["pos_off"]["1B"], 12.0, places=10)
        # SS: player 2 only SS, PA*m2 = 1078 < 1250: all -4.0 runs
        self.assertAlmostEqual(acc["pos_off"]["SS"], -4.0, places=10)
        # 2B: player 3 split 700/500, pro-rata over max(IP 1200, PA*m2=1008.9) = 1200 -> 3.5*700/1200
        self.assertAlmostEqual(acc["pos_off"]["2B"], 3.5 * 700 / 1200, places=10)
        self.assertAlmostEqual(acc["pos_off"]["3B"], 3.5 * 500 / 1200, places=10)
        # C: player 5 has 450 PA = 782.8 equivalent innings but 600 on the field: pro-rata 600/782.8
        paip = 450 * m2
        self.assertAlmostEqual(acc["dh_ip"], paip - 600 + 0.0, places=8)       # only player 5 has DH time
        self.assertAlmostEqual(acc["pos_off"]["C"], -2.0 * 600 / paip, places=10)
        self.assertAlmostEqual(acc["dh_off"], -2.0 * (paip - 600) / paip, places=10)
        # position value = -(apportioned OFF / raw IP) * standard season
        r = M.offense_rates(acc)
        self.assertAlmostEqual(r["1B"], -12.0 / 1200.0 * 1200.0, places=10)
        self.assertAlmostEqual(r["C"], 2.0 * 600 / paip / 600.0 * 1000.0, places=10)

    def test_quirk_flags_default_to_his_behaviour(self):
        s = toy_season()
        a = M.offense_accumulate(s)
        b = M.offense_accumulate(s, rf_quirk=True, thirds_quirk=True)
        self.assertEqual(a["pos_off"], b["pos_off"])
        # RF-only player 4 (1000 IP, 500 PA*m2 = 869 < 1000): his quirk sends him down the pro-rata branch,
        # numer/denom = 6.0*1000/1000 = 6.0, the same number as 'all of it'; the flag changes nothing here
        c = M.offense_accumulate(s, rf_quirk=False)
        self.assertAlmostEqual(a["pos_off"]["RF"], c["pos_off"]["RF"], places=10)

    def test_pooling_is_innings_weighted_mean(self):
        """Two copies of one season with weights 1 and 0.5 pool to the same value, and a
        different second season lands between the two seasons' values."""
        s1, s2 = toy_season(2050), toy_season(2051)
        s2["off"] = {i: v * 2 for i, v in s2["off"].items()}
        a1, a2 = M.offense_accumulate(s1), M.offense_accumulate(s2)
        pooled = M.pool_accumulators([(a1, 1.0), (a2, 0.5)])
        r1, r2, rp = M.offense_rates(a1), M.offense_rates(a2), M.offense_rates(pooled)
        # equal innings in both seasons -> weighted mean of the two values with weights 1 : 0.5
        self.assertAlmostEqual(rp["1B"], (1.0 * r1["1B"] + 0.5 * r2["1B"]) / 1.5, places=10)
        same = M.offense_rates(M.pool_accumulators([(a1, 1.0), (a1, 0.5)]))
        for p in M.NINE:
            self.assertAlmostEqual(same[p], M.offense_rates(a1)[p], places=10)


class DefenceHalf(unittest.TestCase):
    @staticmethod
    def dense_reference(a, b, t, w):
        """What the dashboard's research code does: build the dense +1/-1 design, weight by
        sqrt(w), lstsq (minimum-norm), centre on the mean."""
        X = np.zeros((len(t), 7))
        X[np.arange(len(t)), a] = 1.0
        X[np.arange(len(t)), b] = -1.0
        sw = np.sqrt(w)
        sol = np.linalg.lstsq(X * sw[:, None], t * sw, rcond=None)[0]
        return sol - sol.mean()

    def random_obs(self, seed, n=400):
        rng = np.random.default_rng(seed)
        a = rng.integers(0, 6, n)
        b = a + 1 + rng.integers(0, 6 - a)                 # b > a, within 0..6
        truth = np.array([-8.0, -3.0, -1.0, 6.0, -5.0, 9.0, -2.0])
        t = (truth[a] - truth[b]) + rng.normal(0, 4, n)
        w = rng.uniform(50, 1200, n)
        return a, b, t, w, truth - truth.mean()

    def test_normal_equations_equal_dense_lstsq(self):
        a, b, t, w, _ = self.random_obs(1)
        np.testing.assert_allclose(M._solve(a, b, t, w), self.dense_reference(a, b, t, w), atol=1e-9)

    def test_noise_free_data_recovers_the_spectrum(self):
        a, b, _, w, truth = self.random_obs(2)
        t = truth[a] - truth[b]
        np.testing.assert_allclose(M._solve(a, b, t, w), truth, atol=1e-9)

    def test_recency_weights_halve_per_half_life(self):
        """One pair (positions 0 and 1) observed in two seasons: spec0 - spec1 is the weighted mean
        of the two targets with weights 1 and 0.5**(age/H)."""
        o = [{"a": np.array([0]), "b": np.array([1]), "t": np.array([10.0]), "w": np.array([100.0]), "year": 2050},
             {"a": np.array([0]), "b": np.array([1]), "t": np.array([4.0]), "w": np.array([100.0]), "year": 2048}]
        d, n = M.solve_switcher(o, end=2050, half_life=2.0, cut=20, min_obs=1)     # 2048 weighs 0.5
        want = (10.0 * 100 + 4.0 * 50) / 150.0
        self.assertEqual(n, 2)
        self.assertAlmostEqual(d["1B"] - d["2B"], want, places=10)
        self.assertAlmostEqual(d["1B"] + d["2B"], 0.0, places=10)
        # the cut drops the older season entirely: window of 2 seasons keeps ages 0 and 1 only
        d2, n2 = M.solve_switcher(o, end=2050, half_life=2.0, cut=2, min_obs=1)
        self.assertEqual(n2, 1)
        self.assertAlmostEqual(d2["1B"] - d2["2B"], 10.0, places=10)

    def test_min_obs_returns_no_defence_half(self):
        o = [{"a": np.array([0]), "b": np.array([1]), "t": np.array([1.0]), "w": np.array([1.0]), "year": 1}]
        d, n = M.solve_switcher(o, 1, min_obs=200)
        self.assertIsNone(d)
        self.assertEqual(n, 1)

    def test_switcher_obs_pairs_and_sign(self):
        """A player with innings at 1B (ZR -3 in 600 IP) and SS (ZR +6 in 300 IP) gives one
        observation: target = rate(SS) - rate(1B) per 1200 IP, weight = harmonic mean of innings."""
        s = toy_season()
        s["ip"] = {p: {} for p in POS}
        s["zr"] = {p: {} for p in POS}
        s["ip"]["1B"][9], s["zr"]["1B"][9] = 600.0, -3.0
        s["ip"]["SS"][9], s["zr"]["SS"][9] = 300.0, 6.0
        s["ip"]["2B"][8], s["zr"]["2B"][8] = 900.0, 1.0           # one position only: no observation
        o = M.switcher_obs(s)
        self.assertEqual(len(o["t"]), 1)
        self.assertEqual((int(o["a"][0]), int(o["b"][0])), (M.SEVEN.index("1B"), M.SEVEN.index("SS")))
        self.assertAlmostEqual(o["t"][0], 6.0 / 300 * 1200 - (-3.0 / 600 * 1200), places=10)       # 24 + 6 = 30
        self.assertAlmostEqual(o["w"][0], 2 * 600 * 300 / 900.0, places=10)                          # 400
        # spec[1B] - spec[SS] = rate(SS) - rate(1B): playing SS gives more runs, so SS is the harder spot
        d, _ = M.solve_switcher([o], 2050, min_obs=1)
        self.assertAlmostEqual(d["1B"] - d["SS"], 30.0, places=10)

    def test_catcher_never_enters_the_switcher(self):
        s = toy_season()
        base = len(M.switcher_obs(s)["t"])           # players 3 (2B,3B) and 6 (LF,CF,RF) give 1 + 3 pairs
        self.assertEqual(base, 4)
        s["ip"]["C"][1], s["zr"]["C"][1] = 100.0, 50.0      # player 1 now played C and 1B
        s["ip"]["1B"][1] = 200.0
        s["zr"]["1B"][1] = 1.0
        self.assertEqual(len(M.switcher_obs(s)["t"]), base)


class EngineBoundary(unittest.TestCase):
    def two_seasons(self):
        s1, s2 = toy_season(2050), toy_season(2051)
        for s, zr in ((s1, 1.0), (s2, 3.0)):       # a different 2B/3B ZR gap in each season
            s["zr"]["2B"][3], s["zr"]["3B"][3] = zr, 0.0
        s2["off"] = {i: v * 2 for i, v in s2["off"].items()}
        return s1, s2

    def test_def_from_year_cuts_only_the_defence_half(self):
        s1, s2 = self.two_seasons()
        both = M.pos_adj_multiyear([s1, s2], min_obs=1)
        late = M.pos_adj_multiyear([s1, s2], min_obs=1, def_from_year=2051, )
        alone = M.pos_adj_multiyear([s2], min_obs=1)
        self.assertEqual(both["n_switch_obs"], 2 * late["n_switch_obs"])
        # defence half of the cut run is exactly the 2051-only defence half
        for p in M.SEVEN:
            self.assertAlmostEqual(late["defence_runs_per_1200"][p], alone["defence_runs_per_1200"][p], places=10)
        # the offence half still sees both seasons (recency weights 0.5**(1/2.5) on 2050)
        self.assertNotAlmostEqual(late["offence_runs_engine_units"]["1B"], alone["offence_runs_engine_units"]["1B"], places=3)


class BlendAndCentring(unittest.TestCase):
    OFF = {"C": 10.0, "1B": -6.0, "2B": 2.0, "3B": 4.0, "SS": 8.0, "LF": -4.0, "CF": 0.0, "RF": -2.0, "DH": -12.0}
    DEF = {"1B": -8.0, "2B": -2.0, "3B": 0.0, "SS": 6.0, "LF": -2.0, "CF": 8.0, "RF": -2.0}      # mean 0

    def test_half_and_half_arithmetic(self):
        fin, parts = M.blend(self.DEF, self.OFF, 0.5, "split")
        m7 = sum(self.OFF[p] for p in M.SEVEN) / 7.0                       # 2/7
        raw = {p: 0.5 * self.DEF[p] + 0.5 * (self.OFF[p] - m7) for p in M.SEVEN}
        raw["C"], raw["DH"] = self.OFF["C"] - m7, self.OFF["DH"] - m7      # C and DH from offence only
        f8 = sum(raw[p] for p in M.POSITIONS) / 8.0
        for p in M.NINE:
            self.assertAlmostEqual(fin[p], raw[p] - f8, places=12, msg=p)
        self.assertAlmostEqual(sum(fin[p] for p in M.POSITIONS), 0.0, places=12)    # field-8 mean 0

    def test_dh_is_tied_to_the_lowest_position(self):
        off = dict(self.OFF, DH=-1.0)                                      # DH bats better than a 1B
        fin, _ = M.blend(self.DEF, off, 0.5, "split")
        self.assertAlmostEqual(fin["DH"], min(fin[p] for p in M.POSITIONS), places=12)
        off = dict(self.OFF, DH=-30.0)                                     # already lowest: left alone
        fin, parts = M.blend(self.DEF, off, 0.5, "split")
        self.assertAlmostEqual(fin["DH"] + parts["field8_mean_removed"], -30.0 - sum(off[p] for p in M.SEVEN) / 7.0, places=12)

    def test_pooled_corners_average_and_keep_the_mean(self):
        fin_s, _ = M.blend(self.DEF, self.OFF, 0.5, "split")
        fin_p, _ = M.blend(self.DEF, self.OFF, 0.5, "pooled")
        self.assertAlmostEqual(fin_p["LF"], fin_p["RF"], places=12)
        self.assertAlmostEqual(fin_p["LF"], (fin_s["LF"] + fin_s["RF"]) / 2.0, places=12)
        self.assertAlmostEqual(sum(fin_p[p] for p in M.POSITIONS), 0.0, places=12)

    def test_no_defence_half_is_offence_only(self):
        fin, _ = M.blend(None, self.OFF, 0.5, "split")
        m7 = sum(self.OFF[p] for p in M.SEVEN) / 7.0
        raw = {p: self.OFF[p] - m7 for p in M.NINE}
        f8 = sum(raw[p] for p in M.POSITIONS) / 8.0
        for p in M.POSITIONS:
            self.assertAlmostEqual(fin[p], raw[p] - f8, places=12)

    def test_bad_lf_rf_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            M.blend(self.DEF, self.OFF, 0.5, "merged")

    def test_engine_units_scale_only_the_catcher(self):
        spec = {p: 12.0 for p in M.NINE}
        eng = M.to_engine_units(spec)
        self.assertAlmostEqual(eng["C"], 10.0, places=12)                  # 12 * 1000/1200
        for p in M.NINE:
            if p != "C":
                self.assertAlmostEqual(eng[p], 12.0, places=12)


class BestPosInputs(unittest.TestCase):
    def test_catcher_is_imputed_on_the_anchor(self):
        res = {"defence_runs_per_1200": {"1B": -9.0, "2B": -1.0, "3B": -1.0, "SS": 12.0, "LF": -6.0, "CF": 10.0, "RF": -5.0},
               "spectrum_runs_per_1200": {"C": 16.0, "1B": -13.0, "2B": -2.0, "3B": -1.0, "SS": 9.0,
                                          "LF": -8.0, "CF": 5.0, "RF": -6.0, "DH": -13.0}}
        spec, top = M.option_b_spectrum(res)
        self.assertEqual(top, "SS")
        self.assertAlmostEqual(spec["C"], (12.0 + (16.0 - 9.0)) * 1000 / 1200, places=12)
        spec2, top2 = M.option_b_spectrum(res, anchor=None)               # window maximum is SS here too
        self.assertEqual(top2, "SS")
        res["defence_runs_per_1200"]["CF"] = 13.0
        spec3, top3 = M.option_b_spectrum(res, anchor=None)
        self.assertEqual(top3, "CF")
        self.assertAlmostEqual(spec3["C"], (13.0 + (16.0 - 5.0)) * 1000 / 1200, places=12)
        self.assertAlmostEqual(spec["SS"], 12.0, places=12)               # non-catchers unscaled

    def test_option_b_rule(self):
        spec = {"C": 10.0, "SS": 6.0, "CF": 9.0, "2B": -3.0, "3B": -2.0, "LF": -1.0, "RF": -1.0, "1B": -8.0}
        rp = {"C": -20.0, "SS": -12.0, "CF": -9.0, "2B": -2.0, "3B": -3.0, "LF": -4.0, "RF": -4.0, "1B": 0.0}
        # scores: SS -6, CF 0, 2B -5, 3B -5, LF -5, RF -5, 1B -8 -> CF wins when eligible
        self.assertEqual(M.option_b_best_pos(rp, {"SS", "CF", "2B", "1B"}, spec, 70, 60), "CF")
        # CF ineligible: 2B, 3B, LF, RF tie at -5; the harder position in the order wins (2B)
        self.assertEqual(M.option_b_best_pos(rp, {"SS", "2B", "3B", "LF", "RF", "1B"}, spec, 70, 60), "2B")
        # only the corners: tie goes to LF in the order, then the arm decides the label
        self.assertEqual(M.option_b_best_pos(rp, {"LF", "RF", "1B"}, spec, 70, 60), "RF")
        self.assertEqual(M.option_b_best_pos(rp, {"LF", "RF", "1B"}, spec, 59.9, 60), "LF")
        self.assertEqual(M.option_b_best_pos(rp, {"LF", "RF", "1B"}, spec, None, 60), "LF")
        self.assertEqual(M.option_b_best_pos(rp, {"LF", "RF", "1B"}, spec, 60.0, 60), "RF")     # >= threshold
        # eligible nowhere: DH. A missing RunsP is skipped.
        self.assertEqual(M.option_b_best_pos(rp, set(), spec, 70, 60), "DH")
        self.assertEqual(M.option_b_best_pos(dict(rp, CF=None), {"CF"}, spec, 70, 60), "DH")

    def test_rf_arm_threshold_is_innings_weighted(self):
        s = toy_season()
        s["ip"]["RF"] = {1: 100.0, 2: 300.0, 3: 600.0}
        s["of_arm"] = {1: 40.0, 2: 60.0, 3: 70.0, 4: 99.0}               # player 4 is not at RF here
        self.assertAlmostEqual(M.rf_arm_threshold(s), (100 * 40 + 300 * 60 + 600 * 70) / 1000.0, places=12)
        s["of_arm"] = {}
        self.assertIsNone(M.rf_arm_threshold(s))

    def test_blm_threshold_equals_the_engines_own_rf_arm_anchor(self):
        cells = json.load(open(os.path.join(ENGINE, "calib", "BLM", "metadata-latest.json"), encoding="utf-8"))["cells"]
        self.assertAlmostEqual(M.rf_arm_threshold(M.load_season(BLM_IN, 2058)), cells["I43"], places=9)


class GateAndFiles(unittest.TestCase):
    def test_nothing_in_the_engine_reads_the_candidate_file(self):
        """The candidates are gated: no engine, ingest or tools module may reference them."""
        offenders = []
        for root in ("engine", "ingest", "tools"):
            for dp, _, files in os.walk(os.path.join(TGS, root)):
                for f in files:
                    if not f.endswith(".py") or f in ("pos_adj_multiyear.py", "test_pos_adj_multiyear.py"):
                        continue
                    if "pos_adj_multiyear" in open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read():
                        offenders.append(os.path.join(dp, f))
        self.assertEqual(offenders, [])

    def test_committed_blm_candidate_file_is_current(self):
        path = os.path.join(ENGINE, "calib", "BLM", "pos_adj_multiyear.json")
        act = os.path.join(TGS, "backtest", "actuals", "BLM", "2057")
        if not os.path.exists(path) or not os.path.exists(act):
            self.skipTest("candidate file or 2057 actuals not present")
        saved = json.load(open(path, encoding="utf-8"))
        seasons = [M.load_season(act, 2057, 144), M.load_season(BLM_IN, 2058)]
        res = M.pos_adj_multiyear(seasons)
        got = saved["variants"]["all_seasons"]["candidates"]["lf_rf_split"]
        for cell, v in res["P"].items():
            self.assertAlmostEqual(got[cell], v, places=9, msg=cell)
        self.assertEqual(saved["variants"]["all_seasons"]["n_switch_obs"], res["n_switch_obs"])
        self.assertIn("GATED", saved["status"])


if __name__ == "__main__":
    unittest.main()
