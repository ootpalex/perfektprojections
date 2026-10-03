"""Tests for engine/out_values.py (Phase 2 row 2, the derived fielding out values).

  python -m pytest tgs-viz/tools/tests/test_out_values.py -q
  python tgs-viz/tools/tests/test_out_values.py

Stdlib only, like the module. Pins:
  - the run value of a hit above an out, against a hand-rolled copy of the
    sheet's linear-weights construction (BB = .14 + R/Out, 1B = BB + .155, ...);
  - the outfield hit mix and of_out on a synthetic league where every number
    is checkable on paper;
  - the zone identity ratio, which for derived values reduces to the single
    coverage of the field positions;
  - the ZR regression bracket (forward <= truth <= reverse) on exact and noisy data;
  - that the engine does not read the candidate file or the derivation.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(VIZ, "engine"))

import out_values as OV  # noqa: E402

# A synthetic league season, small enough to check by hand.
T = {"AB": 5000.0, "1B": 800.0, "2B": 250.0, "3B": 20.0, "HR": 150.0, "BB": 450.0, "HP": 40.0,
     "IBB": 10.0, "SH": 20.0, "SF": 30.0, "GIDP": 100.0, "CS": 40.0, "SB": 100.0, "SO": 1000.0,
     "R": 700.0, "PA": 5560.0, "UBR": 0.0}
T["Outs"] = 3970.0           # AB - (1B+2B+3B+HR) + SF + SH + GIDP + CS = 5000 - 1220 + 30 + 20 + 100 + 40

# position -> (chances, made, errors); every chance sits in the R bucket for simplicity
ZONES = {"1B": (1000, 900, 20), "2B": (2000, 1500, 50), "3B": (1500, 1100, 40), "SS": (2000, 1500, 60),
         "LF": (1500, 900, 10), "CF": (1800, 1200, 10), "RF": (1500, 950, 10)}


def rows(chances, made, errors, n=1):
    """n identical player rows summing to the given totals (all in BIZ-R / BIZ-Rm)."""
    r = {c: "0" for c in OV.BIZ_ALL + OV.BIZ_MADE}
    r.update({"BIZ-R": str(chances / n), "BIZ-Rm": str(made / n), "E": str(errors / n), "ZR": "0"})
    return [dict(r) for _ in range(n)]


def hand_above_out(t):
    """The sheet's linear weights, written out independently of metadata_calibrate."""
    rpo = t["R"] / t["Outs"]
    bb = 0.14 + rpo
    hbp, b1 = bb + 0.025, bb + 0.155
    b2 = b1 + 0.3
    b3 = b2 + 0.27
    cs = -((2 * rpo) + 0.075)
    total = ((t["BB"] - t["IBB"]) * bb + hbp * t["HP"] + b1 * t["1B"] + b2 * t["2B"] + b3 * t["3B"]
             + 1.4 * t["HR"] + 0.2 * t["SB"] + cs * t["CS"])
    unpro = t["AB"] - (t["1B"] + t["2B"] + t["3B"] + t["HR"]) + t["SF"]
    rm = total / unpro                       # runs value of an out, magnitude
    return b1 + rm, b2 + rm, b3 + rm


class RunValues(unittest.TestCase):
    def test_above_out_matches_hand_construction(self):
        a = OV.above_out(T)
        h1, h2, h3 = hand_above_out(T)
        self.assertAlmostEqual(a["1B"], h1, places=12)
        self.assertAlmostEqual(a["2B"], h2, places=12)
        self.assertAlmostEqual(a["3B"], h3, places=12)
        self.assertAlmostEqual(a["1B"], 0.722357576839419, places=12)        # frozen
        # the construction fixes the steps between events at .30 and .27
        self.assertAlmostEqual(a["2B"] - a["1B"], 0.30, places=12)
        self.assertAlmostEqual(a["3B"] - a["2B"], 0.27, places=12)

    def test_league_totals_builds_outs_like_hitting_calc(self):
        hit = [{"R": "300", "PA": "10", "AB": "2000", "1B": "300", "2B": "100", "3B": "5", "HR": "60", "BB": "0",
                "HP": "0", "IBB": "0", "SH": "10", "SF": "20", "SB": "0", "CS": "15", "SO": "0", "UBR": "0",
                "GIDP": "40"},
               {"R": "400", "PA": "10", "AB": "3000", "1B": "500", "2B": "150", "3B": "15", "HR": "90", "BB": "0",
                "HP": "0", "IBB": "0", "SH": "10", "SF": "10", "SB": "0", "CS": "25", "SO": "0", "UBR": "0",
                "GIDP": "60"}]
        t = OV.league_totals(hit)
        self.assertEqual(t["R"], 700.0)
        # AB 5000 - hits 1220 + SF 30 + SH 20 + GIDP 100 + CS 40
        self.assertEqual(t["Outs"], 5000 - 1220 + 30 + 20 + 100 + 40)


class Derivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fld = {p: rows(*v, n=4) for p, v in ZONES.items()}
        cls.zones = OV.zone_accounting(cls.fld)

    def test_zone_accounting(self):
        z = self.zones
        self.assertEqual(z["2B"]["chances"], 2000)
        self.assertEqual(z["2B"]["unconverted"], 500)
        self.assertEqual(z["2B"]["hits"], 450)                    # 2000 - 1500 - 50
        self.assertEqual(sum(z[p]["hits"] for p in OV.IF_POS), 80 + 450 + 360 + 440)
        self.assertEqual(sum(z[p]["hits"] for p in OV.OF_POS), 590 + 590 + 540)

    def test_zone_accounting_counts_the_impossible_bucket_as_a_chance_never_made(self):
        r = rows(0, 0, 0)[0]
        r.update({"BIZ-R": "10", "BIZ-Rm": "8", "BIZ-I": "5", "BIZ-Z": "2", "BIZ-Zm": "1"})
        z = OV.zone_accounting({"1B": [r]})["1B"]
        self.assertEqual(z["chances"], 17)
        self.assertEqual(z["made"], 9)

    def test_out_values_by_hand(self):
        v = OV.derive_out_values(T, self.zones)
        h1, h2, h3 = hand_above_out(T)
        of_hits = 1720.0
        of_1b = of_hits - (T["2B"] + T["3B"])                      # 1450
        self.assertAlmostEqual(v["inf_out"], h1, places=12)
        self.assertEqual(v["of_singles"], 1450.0)
        f = v["of_mix_1b_2b_3b"]
        self.assertAlmostEqual(f[0], 1450 / 1720, places=12)
        self.assertAlmostEqual(f[1], 250 / 1720, places=12)
        self.assertAlmostEqual(f[2], 20 / 1720, places=12)
        self.assertAlmostEqual(sum(f), 1.0, places=12)
        want = (1450 * h1 + 250 * h2 + 20 * h3) / 1720
        self.assertAlmostEqual(v["of_out"], want, places=12)
        self.assertGreater(v["of_out"], v["inf_out"])             # the outfield prevents some doubles
        self.assertLess(v["of_out"], h3)

    def test_fewer_outfield_extra_base_hits_lowers_of_out(self):
        full = OV.derive_out_values(T, self.zones, 1.0)["of_out"]
        part = OV.derive_out_values(T, self.zones, 0.8)["of_out"]
        self.assertLess(part, full)
        # 80% of 270 XBH = 216 in the OF: mix (1504, 200, 16)/1720
        h1, h2, h3 = hand_above_out(T)
        self.assertAlmostEqual(part, (1504 * h1 + 200 * h2 + 16 * h3) / 1720, places=12)

    def test_unreconcilable_accounting_raises(self):
        thin = {p: rows(*v, n=1) for p, v in ZONES.items()}
        thin["LF"] = rows(100, 99, 0)            # outfield hits collapse below the league's 2B + 3B
        thin["CF"] = rows(100, 99, 0)
        thin["RF"] = rows(100, 99, 0)
        with self.assertRaises(ValueError):
            OV.derive_out_values(T, OV.zone_accounting(thin))


class Identity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.zones = OV.zone_accounting({p: rows(*v, n=2) for p, v in ZONES.items()})
        cls.v = OV.derive_out_values(T, cls.zones)

    def test_derived_values_reproduce_the_league_hit_value_up_to_single_coverage(self):
        # derived: hits_if*1B + of_1b*1B + 2B*rv2 + 3B*rv3 over 1B*rv1 + 2B*rv2 + 3B*rv3;
        # the XBH terms cancel, so the ratio is (hits_if + of_1b) * rv1 / league  -- pin it
        i = OV.identity(T, self.zones, self.v["inf_out"], self.v["of_out"])
        h1, h2, h3 = hand_above_out(T)
        league = T["1B"] * h1 + T["2B"] * h2 + T["3B"] * h3
        want = ((1330 + 1450) * h1 + 250 * h2 + 20 * h3) / league
        self.assertAlmostEqual(i["ratio"], want, places=12)
        self.assertAlmostEqual(i["single_coverage"], (1330 + 1450) / 800, places=12)
        self.assertAlmostEqual(i["league_hit_runs"], league, places=9)

    def test_level_ordering(self):
        lo = OV.identity(T, self.zones, 0.50, 0.66)["ratio"]
        mid = OV.identity(T, self.zones, self.v["inf_out"], self.v["of_out"])["ratio"]
        hi = OV.identity(T, self.zones, 0.75, 0.90)["ratio"]
        self.assertLess(lo, mid)
        self.assertLess(mid, hi)


class ZrBracket(unittest.TestCase):
    def _fld(self, zr_fn, made=None):
        """Seven positions of 30 players, 100 chances each, made = 60..89 (or `made`);
        ZR from zr_fn(x, k) with x = outs made above the position average."""
        out = {}
        for p in OV.IF_POS + OV.OF_POS:
            rs = []
            made = list(made if made is not None else range(60, 90))
            p_lg = sum(made) / (100.0 * len(made))
            for k, m in enumerate(made):
                r = rows(100, m, 0)[0]
                r["ZR"] = str(zr_fn(m - p_lg * 100.0, k))
                rs.append(r)
            out[p] = rs
        return out

    def test_exact_relationship_gives_equal_slopes_and_r_one(self):
        z = OV.zr_slopes(self._fld(lambda x, k: 0.5 * x))
        for p, s in z.items():
            self.assertAlmostEqual(s["forward"], 0.5, places=9)
            self.assertAlmostEqual(s["reverse"], 0.5, places=9)
            self.assertAlmostEqual(s["r"], 1.0, places=9)
            self.assertEqual(s["n"], 30)

    NOISE = [(-1) ** k * (1 + k % 5) for k in range(30)]              # deterministic, mean ~0

    def test_noise_in_zr_inflates_only_the_reverse_slope(self):
        z = OV.zr_slopes(self._fld(lambda x, k: 0.5 * x + self.NOISE[k]))
        for p, s in z.items():
            self.assertAlmostEqual(s["forward"], 0.5, delta=0.03)       # OLS of y on x is unbiased for noise in y
            self.assertGreater(s["reverse"], 0.55)
            self.assertLess(s["r"], 1.0)

    def test_noise_in_the_out_count_attenuates_only_the_forward_slope(self):
        # true outs t_k = k - 14.5 (linear); the count we observe adds a symmetric quadratic
        # pattern n_k, orthogonal to t by symmetry. ZR carries the TRUE outs: ZR = 0.5 * t.
        t = [k - 14.5 for k in range(30)]
        q = [v * v for v in t]
        n = [(v - sum(q) / 30.0) / 20.0 for v in q]
        made = [75.0 + a + b for a, b in zip(t, n)]
        z = OV.zr_slopes(self._fld(lambda x, k: 0.5 * t[k], made=made))
        var_t, var_n = sum(a * a for a in t) / 30.0, sum(b * b for b in n) / 30.0
        for p, s in z.items():
            self.assertAlmostEqual(s["forward"], 0.5 * var_t / (var_t + var_n), places=9)   # attenuated
            self.assertAlmostEqual(s["reverse"], 0.5, places=9)                              # not

    def test_players_under_the_chance_floor_are_excluded(self):
        fld = self._fld(lambda x, k: 0.5 * x)
        fld["SS"].append({**rows(10, 9, 0)[0], "ZR": "50"})            # 10 chances, absurd ZR
        self.assertEqual(OV.zr_slopes(fld)["SS"]["n"], 30)


class Gating(unittest.TestCase):
    def test_nothing_in_the_engine_reads_the_candidate_or_the_derivation(self):
        # Decided 2026-10-03: out values are derived per league at the next Recalibrate. Only
        # metadata_calibrate (its --derived-out-values branch) and tools/tasks.py (which passes
        # that flag) may name out_values; nothing may open out_values_candidate.json.
        allowed = {"engine/metadata_calibrate.py", "tools/tasks.py"}
        offenders = []
        for sub in ("engine", "ingest", "tools"):
            d = os.path.join(VIZ, sub)
            for fn in os.listdir(d):
                if not fn.endswith(".py") or fn == "out_values.py":
                    continue
                txt = open(os.path.join(d, fn), encoding="utf-8", errors="replace").read()
                if "out_values_candidate" in txt or ("out_values" in txt and f"{sub}/{fn}" not in allowed):
                    offenders.append(f"{sub}/{fn}")
        self.assertEqual(offenders, [], "an unapplied-by-default module is being read")

    def test_candidate_file_is_marked_unread_and_carries_the_frozen_values(self):
        path = os.path.join(VIZ, "engine", "calib", "BLM", "out_values_candidate.json")
        if not os.path.exists(path):
            self.skipTest("no candidate file in this checkout")
        c = json.load(open(path, encoding="utf-8"))
        self.assertIn("CANDIDATE", c["status"])
        self.assertEqual(c["frozen"], {"inf_out": 0.75, "of_out": 0.9})
        self.assertLess(c["inf_out"], 0.75)
        self.assertLess(c["of_out"], 0.90)


if __name__ == "__main__":
    unittest.main()
