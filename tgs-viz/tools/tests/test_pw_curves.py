"""
test_pw_curves.py - Phase 2 row 5: the piecewise curve family and the three-way gate.

    python tgs-viz/tools/tests/test_pw_curves.py
    python -m pytest tgs-viz/tools/tests/test_pw_curves.py -q

What it pins:
  1. the evaluator (hand-computed numbers), clamps, the Stuff cap, continuity;
  2. the 14 transcribed specs against values frozen from ootp-dashboard's own
     `piecewise_delta` (model/src/utils.py @ 8c6337a) at anchor 50;
  3. that the generalized gate reproduces the COMMITTED live_gate of calib/BLM/scurves-preview.json
     for all eight pitching blocks (the S-curve and two-line rebuilt from the committed params and
     the sheet), from the on-disk metadata_inputs season;
  4. the gating: promote_scurves.py (default and --three-way) rebuilds the committed scurves.json
     from the committed preview, choose3 equals choose when no piecewise block is present, and the
     engine's S-curve / two-line paths do not see a piecewise block unless a file has one;
  5. the engine's `piecewise` curve type end to end through pitchers.compute.

Read-only: temp dirs only; nothing under calib/ is written.
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(TESTS))
REPO = os.path.dirname(VIZ)
ENGINE = os.path.join(VIZ, "engine")
CALIB = os.path.join(ENGINE, "calib", "BLM")
sys.path.insert(0, ENGINE)

import pw_curves as PW  # noqa: E402
import scurve_fit as SF  # noqa: E402
import pitchers as P  # noqa: E402
import promote_scurves as PS  # noqa: E402


def block(knots, slopes, anchor, offset=0.0, **kw):
    return {"type": "piecewise", "knots": list(knots), "slopes": list(slopes), "anchor": anchor,
            "offset": offset, "clamp_lo": kw.get("clamp_lo", False), "clamp_hi": kw.get("clamp_hi", False),
            "cap": kw.get("cap")}


class EvaluatorTest(unittest.TestCase):
    # slopes 0.01 / 0.02 / 0.04, knots 40 and 60, anchor 50:
    #   cum(v) = 0.01 v + 0.01 max(v-40,0) + 0.02 max(v-60,0); cum(50) = 0.6
    C = block((40.0, 60.0), (0.01, 0.02, 0.04), 50.0)

    def test_hand_values(self):
        self.assertAlmostEqual(P._pw_rate(self.C, 30.0), 0.3 - 0.6, places=12)            # -0.3
        self.assertAlmostEqual(P._pw_rate(self.C, 50.0), 0.0, places=12)
        self.assertAlmostEqual(P._pw_rate(self.C, 70.0), 0.7 + 0.3 + 0.2 - 0.6, places=12)  # 0.6

    def test_offset_is_added(self):
        c = dict(self.C, offset=0.25)
        self.assertAlmostEqual(P._pw_rate(c, 70.0), 0.85, places=12)

    def test_continuous_at_knots(self):
        for k in self.C["knots"]:
            lo, hi = P._pw_rate(self.C, k - 1e-9), P._pw_rate(self.C, k + 1e-9)
            self.assertAlmostEqual(lo, hi, places=8)

    def test_clamp_lo_is_an_exact_floor(self):
        c = block((30.0, 50.0), (0.0, 0.01, 0.02), 55.0, clamp_lo=True)
        self.assertEqual(P._pw_rate(c, 20.0), P._pw_rate(c, 30.0))
        self.assertEqual(P._pw_rate(c, 30.0), P._pw_rate(c, 25.0))
        self.assertGreater(P._pw_rate(c, 40.0), P._pw_rate(c, 30.0))

    def test_stuff_cap(self):
        c = block((), (0.003,), 50.0, cap=88.0)
        self.assertEqual(P._pw_rate(c, 95.0), P._pw_rate(c, 88.0))
        self.assertAlmostEqual(P._pw_rate(c, 88.0), 0.003 * 38.0, places=12)

    def test_spec_relative_knots_follow_the_anchor(self):
        spec = dict(knots=(-10.0, 12.0), slopes=(0.01, 0.02, 0.04), relative=True)
        c = PW.pw_params(spec, 50.0)
        self.assertEqual(c["knots"], [40.0, 62.0])
        c = PW.pw_params(spec, 45.0)
        self.assertEqual(c["knots"], [35.0, 57.0])
        absolute = PW.pw_params(dict(spec, relative=False), 45.0)
        self.assertEqual(absolute["knots"], [-10.0, 12.0])


# values of ootp-dashboard model/src/utils.py piecewise_delta(r, 50.0, <27 coeffs>) at r = 25, 40, 50,
# 65, 80, frozen from `DEFAULT_{PITCHING,HITTING}_REG_COEFFS_27` at ootp-dashboard 8c6337a
OURS_AT_ANCHOR_50 = {
    ("SP", "SO"): (-0.1150052, -0.0339, 0.0, 0.05085, 0.16529095),
    ("SP", "uBB"): (0.0784345, 0.01696042, 0.0, -0.01875, -0.04280841),
    ("SP", "HR"): (0.05324142, 0.01434696, 0.0, -0.01142877, -0.01862877),
    ("SP", "HHR"): (0.0165, 0.0066, 0.0, -0.0099, -0.0198),
    ("RP", "SO"): (-0.10960589, -0.0339, 0.0, 0.05085, 0.16492862),
    ("RP", "uBB"): (0.08142508, 0.01846564, 0.0, -0.01845, -0.04122016),
    ("RP", "HR"): (0.05426312, 0.01522452, 0.0, -0.01132896, -0.01687896),
    ("RP", "HHR"): (0.01425, 0.0057, 0.0, -0.00855, -0.0171),
    ("BAT", "uBB"): (-0.0583696, -0.0199696, 0.0, 0.0264, 0.08116314),
    ("BAT", "HR"): (-0.02654764, -0.0116, 0.0, 0.0174, 0.05946824),
    ("BAT", "SO"): (0.17326176, 0.0483, 0.0, -0.07245, -0.1449),
    ("BAT", "HHR"): (-0.0575337, -0.0192, 0.0, 0.0288, 0.07857761),
    ("BAT", "XBH"): (-0.11647724, -0.02887724, 0.0, 0.03555, 0.12691248),
    ("BAT", "T3B"): (-0.04992, -0.0312, 0.0, 0.04215, 0.0843),
}


class TranscriptionTest(unittest.TestCase):
    RATINGS = (25.0, 40.0, 50.0, 65.0, 80.0)

    def test_every_spec_matches_ours(self):
        for (role, blk), want in OURS_AT_ANCHOR_50.items():
            spec = PW.HIT_PW[blk][0] if role == "BAT" else PW.PIT_PW[role][blk]
            c = PW.pw_params(spec, 50.0)
            for r, w in zip(self.RATINGS, want):
                self.assertAlmostEqual(P._pw_rate(c, r), w, places=9, msg=f"{role} {blk} r={r}")

    def test_all_specs_are_covered(self):
        self.assertEqual(len(OURS_AT_ANCHOR_50), 8 + len(PW.HIT_PW))

    def test_every_pitching_curve_is_monotone_in_its_known_direction(self):
        for role in ("SP", "RP"):
            for blk, (_, _, d) in SF.BLOCKS.items():
                c = PW.pw_params(PW.PIT_PW[role][blk], 50.0)
                ok, _ = PW.monotone_scan(lambda r, c=c: P._pw_rate(c, r), d)
                self.assertTrue(ok, f"{role} {blk}")

    def test_the_family_is_refused_for_the_26_league(self):
        self.assertNotIn("TGS", PW.LEAGUES_27)


class HittingRateTest(unittest.TestCase):
    S = {"PA": 600.0, "AB": 520.0, "H": 140.0, "1B": 90.0, "2B": 30.0, "3B": 5.0, "HR": 15.0,
         "BB": 60.0, "IBB": 5.0, "HP": 4.0, "SF": 4.0, "SH": 0.0, "SO": 100.0}

    def test_denominators_follow_the_engine_chain(self):
        ubb = 55.0
        cases = {"uBB": (ubb, 596.0), "HR": (15.0, 596.0 - ubb), "SO": (100.0, 596.0 - ubb),
                 "HHR": (125.0, 596.0 - ubb - 15.0 - 100.0), "XBH": (35.0, 125.0), "T3B": (5.0, 35.0)}
        for blk, (num, den) in cases.items():
            y, d = PW.hit_rate(self.S, blk)
            self.assertAlmostEqual(d, den, places=9, msg=blk)
            self.assertAlmostEqual(y, num / den, places=12, msg=blk)


@unittest.skipUnless(os.path.exists(os.path.join(CALIB, "metadata_inputs", "SP_Data.csv")), "BLM metadata_inputs absent")
class GateReproductionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import io
        import contextlib
        cls.prev = json.load(open(os.path.join(CALIB, "scurves-preview.json"), encoding="utf-8"))
        with contextlib.redirect_stdout(io.StringIO()):
            cls.meta = SF.read_metadata("BLM")
        cls.dp = P.scan_consts(os.path.join(REPO, "The Sheets BLM", "The Sheet Pitchers.xlsx"))[0]

    def test_n_curve_gate_reproduces_the_committed_live_gate(self):
        worst = 0.0
        for role in ("SP", "RP"):
            for blk, (xc, xl, _) in SF.BLOCKS.items():
                b = self.prev["roles"][role]["blocks"][blk]
                old = b["live_gate"]
                g = PW.live_gate_n(self.meta[role], blk, xc, xl,
                                   {"sigmoid": PW.scurve_fn(b),
                                    "twoline": PW.twoline_pitch_fn(self.dp, role, blk, b["twoline_offset"])})
                self.assertEqual(g["n"], old["n"])
                self.assertAlmostEqual(g["w"], old["w"], places=6)
                for got, want in ((g["rmse"]["sigmoid"], old["rmse_sigmoid"]),
                                  (g["rmse"]["twoline"], old["rmse_twoline"]),
                                  (g["bias"]["sigmoid"], old["bias_sigmoid"]),
                                  (g["bias"]["twoline"], old["bias_twoline"])):
                    worst = max(worst, abs(got - want))
                for rung, ob in old["buckets"].items():
                    nb = g["buckets"][rung]
                    self.assertEqual(nb["n"], ob["n"])
                    self.assertAlmostEqual(nb["emp"], ob["emp"], places=12)
                    self.assertAlmostEqual(nb["sigmoid"], ob["sig"], places=10)
                    self.assertAlmostEqual(nb["twoline"], ob["two"], places=10)
        self.assertLess(worst, 1e-9)

    def test_n_curve_gate_equals_scurve_fit_live_gate_on_the_same_closures(self):
        b = self.prev["roles"]["SP"]["blocks"]["SO"]
        fs, ft = PW.scurve_fn(b), PW.twoline_pitch_fn(self.dp, "SP", "SO", b["twoline_offset"])
        xc, xl, _ = SF.BLOCKS["SO"]
        old = SF.live_gate(self.meta["SP"], "SO", xc, xl, fs, ft)
        new = PW.live_gate_n(self.meta["SP"], "SO", xc, xl, {"sigmoid": fs, "twoline": ft})
        self.assertAlmostEqual(new["rmse"]["sigmoid"], old["rmse_sigmoid"], places=14)
        self.assertAlmostEqual(new["rmse"]["twoline"], old["rmse_twoline"], places=14)

    def test_preview_block_cross_checks_the_two_curve_gate(self):
        role, blk = "RP", "uBB"
        xc, xl, _ = SF.BLOCKS[blk]
        b = self.prev["roles"][role]["blocks"][blk]
        pb = PW.preview_block(self.meta[role], role, blk, xc, xl, PW.scurve_fn(b),
                              PW.twoline_pitch_fn(self.dp, role, blk, b["twoline_offset"]), b["live_gate"])
        self.assertLess(pb["gate2_max_abs_diff"], 1e-9)
        self.assertEqual(pb["type"], "piecewise")
        # exact-mean transport: the BF-weighted projected league rate over the live population is the actual rate
        s = self.meta[role]["share"]
        f = lambda r: P._pw_rate(pb, r)
        e = (s * PW._wmean(f, self.meta[role]["vr"], xc, pb["cap"])
             + (1 - s) * PW._wmean(f, self.meta[role]["vl"], xl, pb["cap"]))
        self.assertAlmostEqual(e, self.meta[role]["rates"][blk], places=12)

    def test_anchor_is_the_sheets_metadata_anchor(self):
        # the sheet's anchors (metadata-latest.json) are the same weighted live averages
        anchors = {a["label"] + a["section"]: a["value"]
                   for a in json.load(open(os.path.join(CALIB, "metadata-latest.json")))["groups"]["anchors"]}
        got = PW.live_anchor(self.meta["SP"], "STU vR", "STU vL")
        self.assertAlmostEqual(got, anchors["STUsp"], places=2)


class ChooseTest(unittest.TestCase):
    @staticmethod
    def blk(two, sig, pw, mono=True, pw_mono=True, with_pw=True):
        b = {"monotone_ok": mono, "live_gate": {"rmse_sigmoid": sig, "rmse_twoline": two}}
        if with_pw:
            b["piecewise"] = {"monotone_ok": pw_mono,
                              "live_gate3": {"rmse": {"sigmoid": sig, "twoline": two, "piecewise": pw}}}
        return b

    def test_without_a_piecewise_key_choose3_is_choose(self):
        for two, sig in ((1.0, 0.9), (1.0, 0.96), (1.0, 1.2), (0.0, 0.5)):
            b = self.blk(two, sig, 0.1, with_pw=False)
            self.assertEqual(PS.choose3(b), PS.choose(b))

    def test_committed_preview_blocks_all_agree(self):
        prev = json.load(open(os.path.join(CALIB, "scurves-preview.json"), encoding="utf-8"))
        for role in ("SP", "RP"):
            for blk, b in prev["roles"][role]["blocks"].items():
                self.assertEqual(PS.choose3(b), PS.choose(b))

    def test_piecewise_wins_only_beyond_the_margin(self):
        self.assertEqual(PS.choose3(self.blk(1.0, 1.1, 0.90))[0], "piecewise")
        self.assertEqual(PS.choose3(self.blk(1.0, 1.1, 0.951))[0], "two-line")

    def test_ties_do_not_switch_the_curve(self):
        # S-curve already beats the two-line by 10%; piecewise is 1% better than the S-curve
        self.assertEqual(PS.choose3(self.blk(1.0, 0.90, 0.891))[0], "S-curve")
        # piecewise must beat the S-curve by more than the margin to replace it
        self.assertEqual(PS.choose3(self.blk(1.0, 0.90, 0.84))[0], "piecewise")

    def test_non_monotone_piecewise_is_refused(self):
        self.assertEqual(PS.choose3(self.blk(1.0, 1.1, 0.5, pw_mono=False))[0], "two-line")


@unittest.skipUnless(os.path.exists(os.path.join(CALIB, "scurves.json")), "BLM calib absent")
class PromoteGatingTest(unittest.TestCase):
    """promote_scurves.py on a COPY of calib/BLM: default and --three-way rebuild the committed scurves.json."""

    def run_promote(self, *flags, preview=None):
        tmp = tempfile.mkdtemp(prefix="pw-promote-")
        self.addCleanup(shutil.rmtree, tmp, True)
        for n in ("scurves-preview.json", "scurves.json"):
            shutil.copy2(os.path.join(CALIB, n), tmp)
        if preview:
            with open(os.path.join(tmp, "scurves-preview.json"), "w", encoding="utf-8") as fh:
                json.dump(preview, fh)
        r = subprocess.run([sys.executable, os.path.join(ENGINE, "promote_scurves.py"), "--league", "BLM",
                            "--calib-dir", tmp, *flags], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.load(open(os.path.join(tmp, "scurves.json"), encoding="utf-8"))

    @staticmethod
    def strip(d):
        d = json.loads(json.dumps(d))
        d.pop("promoted_at", None)
        return d

    def test_default_rebuilds_the_committed_file(self):
        committed = json.load(open(os.path.join(CALIB, "scurves.json"), encoding="utf-8"))
        self.assertEqual(self.strip(self.run_promote()), self.strip(committed))

    def test_three_way_flag_without_a_piecewise_preview_changes_nothing(self):
        committed = json.load(open(os.path.join(CALIB, "scurves.json"), encoding="utf-8"))
        got = self.run_promote("--three-way")
        # only the human-readable gate description differs (it names both families)
        self.assertEqual(self.strip(dict(got, gate=None)), self.strip(dict(committed, gate=None)))

    def test_a_clearly_better_piecewise_block_is_chosen_loadable_and_stays_out_of_s_curve_blocks(self):
        prev = json.load(open(os.path.join(CALIB, "scurves-preview.json"), encoding="utf-8"))
        # attach a piecewise candidate that is 30% better than the two-line on SP uBB (a block that
        # currently runs the two-line): it must be chosen, loadable, and evaluable by the engine
        b = prev["roles"]["SP"]["blocks"]["uBB"]
        g = b["live_gate"]
        c = dict(PW.pw_params(PW.PIT_PW["SP"]["uBB"], 49.0, 0.08), x_vR="CON vR", x_vL="CON vL", direction=-1,
                 monotone_ok=True,
                 live_gate3={"rmse": {"sigmoid": g["rmse_sigmoid"], "twoline": g["rmse_twoline"],
                                      "piecewise": 0.7 * g["rmse_twoline"]}})
        b["piecewise"] = c
        got = self.run_promote("--three-way", preview=prev)
        self.assertEqual(got["roles"]["SP"]["curve"]["uBB"], "piecewise")
        self.assertEqual(got["roles"]["SP"]["blocks"]["uBB"]["type"], "piecewise")
        self.assertNotIn("piecewise", got["roles"]["SP"]["blocks"]["SO"])   # S-curve blocks stay clean
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "scurves.json")
            json.dump(got, open(path, "w", encoding="utf-8"))
            sc = P.load_scurves(path)
        self.assertEqual(sc["SP"]["uBB"]["type"], "piecewise")


@unittest.skipUnless(os.path.exists(os.path.join(REPO, "The Sheets BLM", "The Sheet Pitchers.xlsx")), "BLM sheet absent")
class EngineStatlineTest(unittest.TestCase):
    """The engine's `piecewise` curve type, end to end through pitchers.compute."""

    @classmethod
    def setUpClass(cls):
        cls.dp, cls.filt, cls.park = P.scan_consts(os.path.join(REPO, "The Sheets BLM", "The Sheet Pitchers.xlsx"))
        cls.p = {"_row": 2, "STU P": 60.0, "HRR P": 55.0, "PBABIP P": 50.0, "CON P": 55.0,
                 "STU vR": 62.0, "HRR vR": 55.0, "PBABIP vR": 50.0, "CON vR": 58.0,
                 "STU vL": 58.0, "HRR vL": 50.0, "PBABIP vL": 50.0, "CON vL": 52.0,
                 "STM": 60.0, "HLD": 50.0, "Pitches": 4, "SP Pitch": 4, "SP P Pitch": 4,
                 "B": "R", "T": "R", "POS": "SP", "Name": "Test Starter", "Age": 27.0}

    def run_compute(self, scurves=None):
        return P.compute(dict(self.p), self.dp, self.filt, self.park, scurves=scurves)

    def test_no_scurves_is_the_two_line_baseline(self):
        a, b = self.run_compute(None), self.run_compute({})
        self.assertEqual(a["SO vR"], b["SO vR"])

    def test_piecewise_so_block_prices_so_and_nothing_upstream(self):
        base = self.run_compute(None)
        c = PW.pw_params(PW.PIT_PW["SP"]["SO"], 47.4, 0.20)
        out = self.run_compute({"SP": {"SO": c}})
        cfg = P.SP_CFG
        bf = float(self.dp["H31"])
        stu_adj = self.p["STU vR"] + cfg["stu_delta"]
        want = max(P._pw_rate(c, stu_adj) * (bf - base["uBB vR"] - base["HBP vR"]), 0.0)
        self.assertAlmostEqual(out["SO vR"], want, places=9)
        self.assertEqual(out["uBB vR"], base["uBB vR"])      # upstream block untouched
        self.assertEqual(out["HBP vR"], base["HBP vR"])
        self.assertNotAlmostEqual(out["SO vR"], base["SO vR"], places=3)

    def test_committed_scurves_json_prices_exactly_as_before_the_piecewise_branch(self):
        # frozen from pitchers.py at 43ed272 (before the branch existed), same pitcher, committed
        # calib/BLM/scurves.json: S-curve SO + HR, two-line (level-matched) uBB + HHR for the starter line
        out = self.run_compute(P.load_scurves(os.path.join(CALIB, "scurves.json")))
        frozen = {"SO vR": 218.98539684716033, "uBB vR": 47.95081901253009, "HR vR": 18.442609219386135,
                  "H-HR vR": 146.28164542470086, "wOBA wtd": 0.2841419909884094,
                  "WAA wtd": 1.8166306747772774, "SO vR RP": 88.66867541530891,
                  "WAA wtd RP": 0.8411964793142034, "WAP": 1.9137453076371704}
        for k, v in frozen.items():
            self.assertEqual(out[k], v, k)


if __name__ == "__main__":
    unittest.main()
