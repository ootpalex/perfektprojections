"""
test_card_replaced.py - the card-replaced failsafe (dev_signals.CARD_LIMITS).

A change from an earlier card that is larger than real development must trip
(a Grueninger-like regenerated card, TGS player 37730); a fast real developer,
a temporary dip and a position change must not. The step check reads a small
SQLite archive built in memory. The numpy twin (ml/common.card_replaced_mask)
is checked against the scalar rule when numpy and pandas are installed (the
ML Python, py -3.14); otherwise those cases are skipped.

    python tgs-viz/tools/tests/test_card_replaced.py
    py -3.14 tgs-viz/tools/tests/test_card_replaced.py

Reads nothing from the real archive and writes nothing.
"""
import datetime
import os
import random
import sqlite3
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(TESTS))
BACKTEST = os.path.join(VIZ, "backtest")
ML = os.path.join(BACKTEST, "ml")
for p in (BACKTEST, ML):
    if p not in sys.path:
        sys.path.insert(0, p)

_BEFORE = set(sys.modules)
import dev_signals as DS  # noqa: E402

try:
    import numpy as np  # noqa: E402
    import common as C  # noqa: E402
except ImportError:          # the plain Python has no numpy / pandas
    np = C = None

# Leave no project module behind in sys.modules: pull_order / ratings_db fix
# the archive path when first imported, and other tests in the same run point
# RATINGS_ARCHIVE_ROOT at a temp archive before they import them.
for _name in set(sys.modules) - _BEFORE:
    _file = getattr(sys.modules[_name], "__file__", None) or ""
    if os.path.abspath(_file).startswith(VIZ + os.sep):
        del sys.modules[_name]

H_SKILLS = ["c_BA", "c_GAP", "c_POW", "c_EYE", "c_K"]
P_SKILLS = ["c_STU", "c_HRR", "c_PBABIP", "c_CON"]


def card(pid="1", age=18, pos="CF", pot=50, bat=None, pit=None):
    """One archive record: bat / pit = the core display values (vR = vL)."""
    bat = bat or [20] * 5
    pit = pit or [20] * 4
    rec = {"player_id": pid, "age": age, "pos": pos, "c_Pot": pot}
    for stem, v in list(zip(H_SKILLS, bat)) + list(zip(P_SKILLS, pit)):
        rec[stem + "_vR"] = v
        rec[stem + "_vL"] = v
    return rec


def trips(prev, rec, scale=1.0):
    role = "P" if rec["pos"] in ("SP", "RP", "CL") else "H"
    return DS.card_change_trips(role, rec["age"], DS.pot_change(prev, rec),
                                DS.core_change(prev, rec, role), scale)


# Grueninger-like: pull 43 SP, Pot 40, batting 20 -> pull 45 CF, Pot 80,
# batting 40 / 45 / 40 / 45 / 35 (the real numbers of TGS player 37730, with
# the name kept, so only the failsafe can catch it)
GRUE_BEFORE = card(age=18, pos="SP", pot=40, pit=[25, 25, 45, 30])
GRUE_AFTER = card(age=19, pos="CF", pot=80, bat=[40, 45, 40, 45, 35])


class PairRule(unittest.TestCase):
    def test_grueninger_trips(self):
        why = trips(GRUE_BEFORE, GRUE_AFTER)
        self.assertTrue(why, "a regenerated card must trip")
        self.assertIn("core +21.0 steps", why[0])

    def test_regenerated_same_position_trips_on_pot_and_core(self):
        before = card(age=18, pos="2B", pot=39)
        after = card(age=18, pos="2B", pot=80, bat=[40, 45, 40, 45, 35])
        why = trips(before, after)
        self.assertEqual(len(why), 2, why)
        self.assertTrue(why[0].startswith("Pot +41"))

    def test_fast_hitter_does_not_trip(self):
        # +13.5 steps and Pot +13 in a game-year at 20 (TGS Teo Velazquez, the
        # DEV p99.99 at 20): fast, real
        before = card(age=19, pos="1B", pot=62, bat=[40, 40, 40, 40, 35])
        after = card(age=20, pos="1B", pot=75, bat=[55, 55, 55, 52.5, 45])
        self.assertAlmostEqual(DS.core_change(before, after, "H"), 13.5)
        self.assertEqual(trips(before, after), [])

    def test_fast_pitcher_does_not_trip(self):
        before = card(age=20, pos="SP", pot=50, pit=[40, 40, 40, 35])
        after = card(age=21, pos="SP", pot=65, pit=[50, 50, 45, 45])
        self.assertAlmostEqual(DS.core_change(before, after, "P"), 7.0)
        self.assertEqual(trips(before, after), [])

    def test_position_change_skips_pot(self):
        # OOTP grades Pot at the listed position: 1B 75 -> SP 42 is no card change
        before = card(age=19, pos="1B", pot=75, bat=[35, 40, 35, 40, 25])
        after = card(age=19, pos="SP", pot=42, bat=[35, 40, 35, 40, 25])
        self.assertIsNone(DS.pot_change(before, after))
        self.assertEqual(trips(before, after), [])

    def test_young_dip_does_not_trip(self):
        # TGS 35107: a 17-year-old lost 1.5 steps for ten weeks, then got them back
        before = card(age=17, pos="2B", pot=33, bat=[30, 25, 22.5, 25, 25])
        after = card(age=17, pos="2B", pot=33, bat=[27.5, 25, 22.5, 20, 25])
        self.assertAlmostEqual(DS.core_change(before, after, "H"), -1.5)
        self.assertEqual(trips(before, after), [])

    def test_span_scales_the_limit(self):
        before = card(age=21, pos="SS", pot=60, bat=[30, 30, 30, 30, 30])
        after = card(age=22, pos="SS", pot=60, bat=[50, 50, 50, 50, 45])    # +19 steps
        self.assertTrue(trips(before, after, 1.0))                            # limit +16.5
        self.assertEqual(trips(before, after, 1.5), [])                       # limit +24.75

    def test_ages_clamp(self):
        self.assertEqual(DS.card_limits("H", 14), DS.CARD_LIMITS["H"][16])
        self.assertEqual(DS.card_limits("P", 45), DS.CARD_LIMITS["P"][40])
        self.assertIsNone(DS.card_limits("H", None))

    def test_limits_table_is_whole(self):
        for role in ("H", "P"):
            self.assertEqual(sorted(DS.CARD_LIMITS[role]), list(range(16, 41)))
            for pot, up, down in DS.CARD_LIMITS[role].values():
                self.assertGreater(pot, 0)
                self.assertGreater(up, 0)
                self.assertLessEqual(down, -up)


def archive(pulls):
    """In-memory archive: pulls = [(pull_id, date, [records])]."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ratings (pull_id INTEGER, " + ", ".join(f'"{c}"' for c in DS.CARD_COLS[0:]) + ")")
    for pid, _d, recs in pulls:
        for r in recs:
            conn.execute("INSERT INTO ratings VALUES (?, " + ", ".join("?" for _ in DS.CARD_COLS) + ")",
                         [pid] + [r[c] for c in DS.CARD_COLS])
    plist = [(pid, d.isoformat(), d.isoformat()) for pid, d, _r in pulls]
    gdates = {pid: d for pid, d, _r in pulls}
    return conn, plist, gdates


def choice(plist, gdates, from_id, to_id):
    span = (gdates[to_id] - gdates[from_id]).days / DS.YEAR_DAYS
    return {"to_id": to_id, "from_id": from_id, "to_date": gdates[to_id], "from_date": gdates[from_id],
            "span": span, "dates": "in-game"}


class StepRule(unittest.TestCase):
    def setUp(self):
        d = datetime.date
        steady = [card("2", 19, "SS", 55 + i, bat=[40 + 2.5 * i] * 5) for i in range(4)]   # +2.5 steps a pull
        spike = [card("3", 20, "C", p, bat=[40] * 5) for p in (50, 50, 80, 55)]          # Pot +30, then back
        grue = [GRUE_BEFORE, GRUE_BEFORE, GRUE_AFTER, GRUE_AFTER]
        grue = [dict(r, player_id="37730") for r in grue]
        dates = [d(2044, 8, 8), d(2045, 1, 9), d(2045, 1, 30), d(2045, 8, 7)]
        self.conn, self.plist, self.gdates = archive(
            [(10 + i, dt, [steady[i], spike[i], grue[i]]) for i, dt in enumerate(dates)])
        self.choice = choice(self.plist, self.gdates, 10, 13)

    def tearDown(self):
        self.conn.close()

    def test_replaced_cards(self):
        rep = DS.replaced_cards(self.conn, self.plist, self.gdates, self.choice)
        self.assertIn("37730", rep)                  # pair +21 steps (and the 21-day step)
        self.assertTrue(rep["37730"].startswith("pair 2044-08-08 to 2045-08-07"))
        self.assertIn("3", rep)                      # Pot +30 in 21 days; the pair total (+5) looks possible
        self.assertTrue(rep["3"].startswith("one step 2045-01-09 to 2045-01-30 (21 game days)"), rep["3"])
        self.assertNotIn("2", rep)                   # +7.5 steps over the year, 2.5 a pull

    def test_long_steps_are_not_read(self):
        # the spike spread over a long step (60+ game days) is the pair rule's business only
        steps = DS.card_steps(self.conn, [10, 12, 13], self.gdates, {"3": ("H", 20)})
        self.assertEqual(steps, {})
        steps = DS.card_steps(self.conn, [11, 12], self.gdates, {"3": ("H", 20)})
        self.assertEqual(len(steps["3"]), 1)

    def test_ids_filter(self):
        rep = DS.replaced_cards(self.conn, self.plist, self.gdates, self.choice, ids=["2", "3"])
        self.assertEqual(sorted(rep), ["3"])

    def test_no_earlier_pull(self):
        ch = dict(self.choice, from_id=None, from_date=None, span=None)
        self.assertEqual(DS.replaced_cards(self.conn, self.plist, self.gdates, ch), {})


@unittest.skipIf(C is None, "numpy / pandas not installed (run with the ML Python, py -3.14)")
class NumpyTwin(unittest.TestCase):
    def test_mask_matches_scalar_rule(self):
        rnd = random.Random(7)
        rows = []
        for _ in range(4000):
            role = rnd.choice("HP")
            age = rnd.choice([None, 14, 16, 18, 19.6, 22, 27, 33, 40, 44])
            d_pot = rnd.choice([None, rnd.uniform(-40, 40)])
            grow = rnd.choice([None, rnd.uniform(-20, 25)])
            span = rnd.choice([0.5, 1.0, 1.3, 2.0])
            same = rnd.random() < 0.8
            rows.append((role, age, d_pot, grow, span, same))
        nan = float("nan")
        mask = C.card_replaced_mask(
            np.array([r[0] for r in rows], dtype=object),
            np.array([nan if r[1] is None else r[1] for r in rows]),
            np.array([nan if r[2] is None else r[2] for r in rows]),
            np.array([nan if r[3] is None else r[3] for r in rows]),
            np.array([r[4] for r in rows]),
            np.array([r[5] for r in rows]))
        for (role, age, d_pot, grow, span, same), m in zip(rows, mask):
            want = bool(DS.card_change_trips(role, age, d_pot if same else None, grow, max(1.0, span)))
            self.assertEqual(bool(m), want, (role, age, d_pot, grow, span, same))

    def test_mask_earlier_card(self):
        f = {"grow_steps": np.array([1.0, 2.0, np.nan], dtype=np.float32),
             "d_pot": np.array([3.0, 4.0, np.nan], dtype=np.float32),
             "grow2_steps": np.array([5.0, 6.0, 7.0], dtype=np.float32)}
        C.mask_earlier_card(f, "H", np.array([False, True, False]), np.array([True, False, False]))
        self.assertEqual(f["has_prev"].tolist(), [1.0, 0.0, 0.0])
        self.assertTrue(np.isnan(f["d_pot"][1]) and f["d_pot"][0] == 3.0)
        self.assertTrue(np.isnan(f["grow2_steps"][0]) and f["grow2_steps"][1] == 6.0)
        # nothing to mask: only has_prev is set
        g = {"grow_steps": np.array([1.0], dtype=np.float32)}
        C.mask_earlier_card(g, "P")
        self.assertEqual(g["has_prev"].tolist(), [1.0])


if __name__ == "__main__":
    unittest.main()
