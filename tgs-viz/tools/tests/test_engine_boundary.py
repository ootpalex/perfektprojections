"""
test_engine_boundary.py - the engine-version boundary: settings key
leagues.<id>.engine_first_season and the refusal in ingest/metadata_inputs.py.

    python tgs-viz/tools/tests/test_engine_boundary.py

Offline: StatsPlus is never asked. Every network entry point of statsplus.py is
replaced by a function that fails the test when called, and each refusal case
asserts which of them ran (none with --year; only /date without it). Settings
come from a temp file (TGS_SETTINGS_LOCAL); nothing is written outside the temp
folder.
"""
import contextlib
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
VIZ = os.path.dirname(TOOLS)
INGEST = os.path.join(VIZ, "ingest")

TMP = tempfile.mkdtemp(prefix="tgs-boundary-test-")
LOCAL = os.path.join(TMP, "settings.local.json")
os.environ["TGS_SETTINGS_LOCAL"] = LOCAL
os.environ["STATSPLUS_TOKEN_FILE"] = os.path.join(TMP, "tokens.txt")
for p in (TOOLS, INGEST):
    if p not in sys.path:
        sys.path.insert(0, p)
import settings as ST          # noqa: E402
import statsplus as S          # noqa: E402
import metadata_inputs as M    # noqa: E402


def write_local(leagues):
    with open(LOCAL, "w", encoding="utf-8") as f:
        json.dump({"leagues": leagues}, f)
    ST.load(refresh=True)


class NetworkTouched(AssertionError):
    pass


def _boom(name):
    def f(*a, **k):
        raise NetworkTouched(f"{name} was called")
    return f


def run_main(argv, date=None):
    """metadata_inputs.main() with argv. Returns (SystemExit message or None, names of the fetches that ran)."""
    calls = []

    def fake_date(base, *a, **k):
        calls.append("fetch_date")
        if date is None:
            raise NetworkTouched("fetch_date was called")
        return date

    patches = [mock.patch.object(S, "fetch_date", fake_date)]
    for fn in ("fetch_teams", "fetch_pitching", "fetch_batting", "fetch_fielding", "_open"):
        if hasattr(S, fn):
            patches.append(mock.patch.object(S, fn, _boom(fn)))
    msg = None
    with contextlib.ExitStack() as st:
        for p in patches:
            st.enter_context(p)
        st.enter_context(mock.patch.object(sys, "argv", ["metadata_inputs.py"] + argv))
        st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        try:
            M.main()
        except SystemExit as e:
            msg = str(e.code)
    return msg, calls


class SettingsKey(unittest.TestCase):
    def setUp(self):
        write_local({})

    def test_valid_and_reader(self):
        write_local({"BLM": {"engine_first_season": 2055}, "SSB": {"type": "statsplus", "name": "SSB",
                     "basis": "BLM", "engine_first_season": 2043}})
        self.assertEqual(ST.engine_first_season("BLM"), 2055)
        self.assertEqual(ST.engine_first_season("SSB"), 2043)
        self.assertIsNone(ST.engine_first_season("TGS"))
        self.assertIsNone(ST.engine_first_season("NOPE"))

    def test_bad_values_named(self):
        base = ST.defaults_raw()
        for bad in ("2043", True, 43, 99999, 2043.5, None, [2043]):
            m = copy.deepcopy(base)
            m["leagues"]["BLM"]["engine_first_season"] = bad
            problems = ST.validate(m)
            self.assertEqual(len(problems), 1, (bad, problems))
            self.assertIn("leagues.BLM.engine_first_season: must be a season year like 2043", problems[0])
        m = copy.deepcopy(base)
        m["leagues"]["BLM"]["engine_first_season"] = 2043
        self.assertEqual(ST.validate(m), [])

    def test_bad_local_value_fails_load_with_the_key(self):
        with open(LOCAL, "w", encoding="utf-8") as f:
            json.dump({"leagues": {"BLM": {"engine_first_season": "2043"}}}, f)
        with self.assertRaises(ST.SettingsError) as cm:
            ST.load(refresh=True)
        self.assertIn("leagues.BLM.engine_first_season", str(cm.exception))

    def test_defaults_unchanged(self):
        """No default league carries a boundary: nothing changes unless the user sets one."""
        for lid, lg in ST.defaults_raw()["leagues"].items():
            self.assertNotIn("engine_first_season", lg, lid)


class Refusal(unittest.TestCase):
    def setUp(self):
        write_local({"BLM": {"engine_first_season": 2055}})
        self.out = os.path.join(TMP, "out")
        shutil.rmtree(self.out, ignore_errors=True)

    def test_problem_text(self):
        self.assertIsNone(M.engine_boundary_problem("BLM", 2055, 2055))        # the boundary season itself is fine
        self.assertIsNone(M.engine_boundary_problem("BLM", 2060, 2055))
        self.assertIsNone(M.engine_boundary_problem("BLM", 1999, None))        # no boundary: never refuses
        msg = M.engine_boundary_problem("BLM", 2054, 2055, "27")
        for want in ("STOP:", "BLM season 2054", "engine_first_season = 2055", "OOTP 27", "season 2055 or later"):
            self.assertIn(want, msg)

    def test_year_before_boundary_refuses_before_any_request(self):
        msg, calls = run_main(["--league", "BLM", "--out", self.out, "--year", "2050"])
        self.assertIn("engine_first_season = 2055", msg)
        self.assertEqual(calls, [])                      # not even /date
        self.assertFalse(os.path.exists(self.out))       # nothing written

    def test_date_season_before_boundary_refuses_after_date_only(self):
        msg, calls = run_main(["--league", "BLM", "--out", self.out], date="2052-11-02")     # season 2052
        self.assertIn("BLM season 2052", msg)
        self.assertEqual(calls, ["fetch_date"])          # one request; /teams and the feeds never asked
        self.assertFalse(os.path.exists(self.out))

    def test_boundary_season_and_unconfigured_league_go_on_to_fetch(self):
        """At the boundary, and for a league without one, the run continues to the
        first real request (here /teams, which the test turns into a failure)."""
        for league_cfg, year in (({"BLM": {"engine_first_season": 2055}}, "2055"), ({}, "2001")):
            write_local(league_cfg)
            with self.assertRaises(NetworkTouched) as cm:
                run_main(["--league", "BLM", "--out", self.out, "--year", year], date="2056-11-02")
            self.assertIn("fetch_teams", str(cm.exception))

    def test_other_league_not_affected(self):
        write_local({"BLM": {"engine_first_season": 2055}})
        with self.assertRaises(NetworkTouched):
            run_main(["--league", "TGS", "--out", self.out, "--year", "2040"], date="2056-11-02")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
