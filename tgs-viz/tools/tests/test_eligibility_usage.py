"""
test_eligibility_usage.py - tools/eligibility_usage.py: the rule sets, the usage arithmetic, and
that the tool's current-engine rule ("his") reproduces every shipped '<pos> Eligible' flag.

    python tgs-viz/tools/tests/test_eligibility_usage.py
    python -m pytest tgs-viz/tools/tests/test_eligibility_usage.py -q

Offline. The shipped-flag cases read the committed public/data/<LG>/hitters.json and skip a league
whose file is missing. Writes nothing.
"""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VIZ = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import eligibility_usage as E  # noqa: E402

NAN = float("nan")


def table(rows):
    """rows: dicts with ip, w (default 1), pos, T (default 'R'), HT (default 190), pid, src and ratings."""
    full = []
    for i, r in enumerate(rows):
        d = dict(src="X", pid=str(r.get("pid", i)), pos=r.get("pos", "1B"), ip=r.get("ip", 100.0), w=r.get("w", 1.0),
                 T=r.get("T", "R"), HT=r.get("HT", 190.0))
        for k in E.RATING_KEYS:
            d[k] = r.get(k, 50)
        full.append(d)
    return E.build_table(full)


class Helpers(unittest.TestCase):
    def test_ip_thirds(self):
        self.assertAlmostEqual(E.ip_thirds("178.1"), 178 + 1 / 3)
        self.assertAlmostEqual(E.ip_thirds("1116.2"), 1116 + 2 / 3)
        self.assertEqual(E.ip_thirds("1370"), 1370.0)
        self.assertEqual(E.ip_thirds(""), 0.0)

    def test_ht_cm_matches_the_engine_sheet_conversion(self):
        # ingest/ratings.py: HT Sort = inches * 2.54
        self.assertAlmostEqual(E.ht_cm("6' 4\""), 76 * 2.54)
        self.assertAlmostEqual(E.ht_cm("6' 2'"), 74 * 2.54)
        self.assertTrue(np.isnan(E.ht_cm("")))

    def test_weighted_quantile_takes_the_value_that_reaches_the_share(self):
        x = np.array([40.0, 50.0, 60.0])
        w = np.array([1.0, 1.0, 2.0])          # cumulative share .25, .5, 1.0
        self.assertEqual(E.wquantile(x, w, 0.25), 40.0)
        self.assertEqual(E.wquantile(x, w, 0.26), 50.0)
        self.assertEqual(E.wquantile(x, w, 0.5), 50.0)
        self.assertEqual(E.wquantile(x, w, 0.51), 60.0)


class Rules(unittest.TestCase):
    def passes(self, rule, pos, **kw):
        return bool(E.eligible(table([dict(pos=pos, **kw)]), pos, E.RULES[rule])[0])

    def test_corner_of_floor(self):
        # his 50, ours / rec 45, lf40 40; CF stays 60 in all
        for rule, lo in (("his", 50), ("ours", 45), ("rec", 45), ("lf40", 40)):
            self.assertTrue(self.passes(rule, "LF", **{"OF RNG": lo}), rule)
            self.assertFalse(self.passes(rule, "LF", **{"OF RNG": lo - 5}), rule)
            self.assertTrue(self.passes(rule, "RF", **{"OF RNG": lo}), rule)
            self.assertFalse(self.passes(rule, "RF", **{"OF RNG": lo - 5}), rule)
        self.assertFalse(self.passes("rec", "CF", **{"OF RNG": 55}))
        self.assertTrue(self.passes("rec", "CF", **{"OF RNG": 60}))
        self.assertTrue(self.passes("wide", "CF", **{"OF RNG": 55}))

    def test_first_base_clauses(self):
        base = {"IF RNG": 30, "IF ERR": 20}
        self.assertTrue(self.passes("his", "1B", **base))                     # no ERR floor
        self.assertFalse(self.passes("ours", "1B", **base))                   # ERR > 20 is strict
        self.assertTrue(self.passes("ours", "1B", **{"IF RNG": 30, "IF ERR": 25}))
        self.assertFalse(self.passes("his", "1B", **{"IF RNG": 20, "IF ERR": 60}))   # RNG > 20 is strict
        self.assertFalse(self.passes("his", "1B", HT=179.0))                  # HT > 179 is strict
        self.assertTrue(self.passes("his", "1B", HT=180.34))                  # 5'11"
        self.assertTrue(self.passes("his", "1B", HT=NAN))                     # unknown height is not evidence

    def test_shortstop_turn_double_play_floor_is_ours_only(self):
        ok = {"IF RNG": 60, "IF ARM": 50, "TDP": 35}
        self.assertTrue(self.passes("his", "SS", **ok))
        self.assertFalse(self.passes("ours", "SS", **ok))
        self.assertTrue(self.passes("ours", "SS", **dict(ok, TDP=45)))

    def test_throws_clause_and_unknown_throws(self):
        ok = {"IF RNG": 60, "IF ARM": 60, "TDP": 60}
        for pos in ("2B", "3B", "SS"):
            self.assertTrue(self.passes("his", pos, T="R", **ok), pos)
            self.assertFalse(self.passes("his", pos, T="L", **ok), pos)
            self.assertTrue(self.passes("his", pos, T="", **ok), pos)         # unknown passes
        self.assertTrue(self.passes("his", "LF", T="L", **{"OF RNG": 60}))     # lefties play the outfield

    def test_missing_rating_fails(self):
        self.assertFalse(self.passes("his", "C", **{"C FRM": NAN}))
        self.assertTrue(self.passes("his", "C", **{"C FRM": 45}))
        self.assertFalse(self.passes("his", "C", **{"C FRM": 40}))

    def test_wide_rule_is_what_implied_floors_returns_on_a_known_table(self):
        # 100 innings at each rating 40..70 step 5; 3% cut: floor 40 excludes 0%, 45 excludes 1/7=14%
        rows = [dict(pos="LF", ip=100.0, **{"OF RNG": r}) for r in range(40, 75, 5)]
        t = table(rows)
        got = E.implied_floors(t, 0.03, 45)
        self.assertEqual(got[("LF", "OF RNG")], 40)


class Usage(unittest.TestCase):
    def test_share_excluded_is_innings_and_player_weighted(self):
        t = table([dict(ip=300.0, w=1.0), dict(ip=100.0, w=1.0), dict(ip=100.0, w=0.5)])
        passm = np.array([True, False, False])
        ip_share, pl_share = E.share_excluded(t, passm)
        self.assertAlmostEqual(ip_share, (100 + 50) / (300 + 100 + 50))        # w scales innings
        self.assertAlmostEqual(pl_share, 1.5 / 2.5)

    def test_population_cut(self):
        t = table([dict(pos="LF", ip=44.9), dict(pos="LF", ip=45.0), dict(pos="RF", ip=500.0)])
        self.assertEqual(len(E.population(t, "LF", 45)["ip"]), 1)

    def test_replicate_fail_shares_all_vs_any(self):
        # player a fails in 1 of 2 pulls, player b fails in both, player c in neither; 100 IP each
        rows = [dict(pid="a", ip=100.0, w=.5), dict(pid="a", ip=100.0, w=.5),
                dict(pid="b", ip=100.0, w=.5), dict(pid="b", ip=100.0, w=.5),
                dict(pid="c", ip=100.0, w=.5), dict(pid="c", ip=100.0, w=.5)]
        passm = np.array([True, False, False, False, True, True])
        all_f, any_f = E.replicate_fail_shares(table(rows), passm)
        self.assertAlmostEqual(all_f, 1 / 3)
        self.assertAlmostEqual(any_f, 2 / 3)

    def test_floor_table_pass_means_at_or_above(self):
        t = table([dict(pos="LF", ip=100.0, **{"OF RNG": r}) for r in (40, 45, 50, 55)])
        ft = E.floor_table(t, "OF RNG", [45, 50])
        self.assertAlmostEqual(ft[45][0], 0.25)       # only the 40
        self.assertAlmostEqual(ft[50][0], 0.50)       # 40 and 45
        ft_strict = E.floor_table(t, "OF RNG", [45], strict=True)
        self.assertAlmostEqual(ft_strict[45][0], 0.50)  # > 45 passes only 50, 55


class BestPosAndFlips(unittest.TestCase):
    def rows(self):
        def r(**kw):
            d = {"Lev": "MLB", "T": "R", "HT Sort": "190", "IF RNG": "40", "IF ERR": "40", "IF ARM": "40", "TDP": "40",
                 "OF RNG": "45", "OF ERR": "40", "OF ARM": "40", "C FRM": "20"}
            for p in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"):
                d[p + " WAA wtd"] = "0"
            d.update(kw)
            return d
        return [
            r(**{"LF WAA wtd": "1.5", "DH WAA wtd": "1.0"}),                    # LF would win, only at floor 45
            r(**{"OF RNG": "50", "LF WAA wtd": "1.5", "DH WAA wtd": "1.0"}),    # eligible already
            r(Lev="AA", **{"LF WAA wtd": "9", "DH WAA wtd": "1.0"}),            # minors: out of MLB-only scope
        ]

    def test_flips_count_flag_and_best_pos_changes(self):
        f = E.flips(self.rows(), E.RULES["his"], E.RULES["rec"], True)
        self.assertEqual(f["n"], 2)
        self.assertEqual(f["gained"]["LF"], 1)
        self.assertEqual(f["gained"]["RF"], 1)
        self.assertEqual(f["any_elig_change"], 1)
        self.assertEqual(f["best_pos_changed"], 1)
        self.assertEqual(f["best_pos_moves"], {"DH->LF": 1})
        self.assertEqual(f["max_waa_changed"], 1)
        self.assertAlmostEqual(f["max_waa_delta_max"], 0.5)
        f_all = E.flips(self.rows(), E.RULES["his"], E.RULES["rec"], False)
        self.assertEqual(f_all["n"], 3)
        self.assertEqual(f_all["best_pos_changed"], 2)

    def test_rows_without_waa_columns_are_not_counted_as_best_pos_changes(self):
        rows = [{"Lev": "MLB", "T": "R", "HT Sort": "190", "IF RNG": "40", "IF ERR": "40", "IF ARM": "40", "TDP": "40",
                 "OF RNG": "45", "OF ERR": "40", "OF ARM": "40", "C FRM": "20"}]      # a list with no '<pos> WAA wtd'
        f = E.flips(rows, E.RULES["his"], E.RULES["rec"], True)
        self.assertEqual(f["any_elig_change"], 1)
        self.assertEqual(f["best_pos_changed"], 0)
        self.assertEqual(f["max_waa_changed"], 0)

    def test_best_pos_tie_keeps_the_first_in_engine_order(self):
        rows = [{"Lev": "MLB", "T": "R", "HT Sort": "190", "IF RNG": "60", "IF ERR": "50", "IF ARM": "60", "TDP": "60",
                 "OF RNG": "20", "OF ERR": "20", "OF ARM": "20", "C FRM": "20",
                 **{p + " WAA wtd": "2" for p in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH")}}]
        t = E.hitter_table(rows)
        idx, mx = E.best_pos_and_max(t, {p: E.eligible(t, p, E.RULES["his"]) for p in E.FIELD_POS})
        names = list(E.WAA_ORDER) + ["DH"]
        self.assertEqual(names[idx[0]], "1B")          # C ineligible; 1B is first eligible in dict order
        self.assertEqual(mx[0], 2.0)


class ShippedFlags(unittest.TestCase):
    """The tool's "his" rule is the engine's rule: it reproduces every committed flag, Best Pos and Max WAA."""

    def check(self, lg):
        path = os.path.join(VIZ, "public", "data", lg, "hitters.json")
        if not os.path.exists(path):
            self.skipTest("no committed %s hitters.json" % lg)
        rows = E._hitters_json(lg)
        self.assertEqual(sum(E.reproduces_flags(rows).values()), 0, lg)
        n, bad_best, max_diff = E.reproduces_shipped(rows)
        self.assertGreater(n, 1000)
        self.assertEqual(bad_best, 0, lg)
        self.assertLess(max_diff, 1e-9, lg)

    def test_blm(self):
        self.check("BLM")

    def test_ssb(self):
        self.check("SSB")

    def test_tgs(self):
        self.check("TGS")

    def test_rg(self):
        self.check("RG")


if __name__ == "__main__":
    unittest.main()
