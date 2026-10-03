"""
test_draft_pool.py - the StatsPlus draft pool: statsplus.fetch_draftpool and the pool source order in
ingest/draft.py (StatsPlus /draftpool/ first, the OOTP export second, BLM's draft_eligible flag last).

    python tgs-viz/tools/tests/test_draft_pool.py
    python -m pytest tgs-viz/tools/tests/test_draft_pool.py -q

Offline. fetch_draftpool is exercised against a mock server on 127.0.0.1 (the client's own test
mechanism: STATSPLUS_TEST_BASE_URL, a fake token from the environment, a temporary cache folder).
The /draftpool/ reply shape has never been seen live: the fixture draftpool_reply_UNVERIFIED_SHAPE.csv
is the shape model/src/draftpool.py parses ("ID","Player Name"), and the cases below pin what the
client does with that shape and with every refusal. The ratings fixture is 8 amateurs trimmed from the
2026-10-02 SSB pull (fictional players). Nothing is written outside temporary folders.
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
VIZ = os.path.dirname(TOOLS)
INGEST = os.path.join(VIZ, "ingest")
FIX = os.path.join(HERE, "fixtures", "draft_pool")
sys.path.insert(0, INGEST)
sys.path.insert(0, TOOLS)

import statsplus as S  # noqa: E402

TOKEN = "tok-SECRET-123456"
POOL_REPLY = open(os.path.join(FIX, "draftpool_reply_UNVERIFIED_SHAPE.csv"), encoding="utf-8").read()
POOL_IDS = ["73232", "73121", "73091", "73317", "74258", "73266"]      # first three hitters, then three pitchers
NOT_IN_POOL = ["74485", "74426"]                                        # in the pull, not in the pool


class Mock(BaseHTTPRequestHandler):
    """routes: {path: (status, body, headers)}; log: [(path, query)]; set per test on the server."""

    def do_GET(self):
        path, _, query = self.path.partition("?")
        self.server.log.append((path, query))
        status, body, headers = self.server.routes.get(path, (404, "not found", {}))
        raw = body.encode("utf-8")
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


class MockServerCase(unittest.TestCase):
    """A mock StatsPlus on 127.0.0.1 and an isolated client (cache folder, token, date memo)."""

    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), Mock)
        self.srv.log, self.srv.routes = [], {"/ssb/api/date": (200, "2044-05-02", {})}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.mkdtemp()
        env = {"STATSPLUS_TEST_BASE_URL": f"http://127.0.0.1:{self.srv.server_port}",
               "STATSPLUS_CACHE_DIR": os.path.join(self.tmp, "sp"), "STATSPLUS_TEST_TOKEN_SSB": TOKEN}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        S.clear_date_memo()
        S._WARNED.clear()
        self.warnings = []
        old = S.on_warning
        S.on_warning = self.warnings.append
        self.addCleanup(setattr, S, "on_warning", old)
        self.base = S.normalize_base("ssb")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def route(self, path, body, status=200, headers=None):
        self.srv.routes[path] = (status, body, headers or {})

    def hits(self, path):
        return [q for p, q in self.srv.log if p == path]


class FetchDraftpool(MockServerCase):
    POOL = "/ssb/api/draftpool/"

    def test_parses_the_assumed_shape(self):
        self.route(self.POOL, POOL_REPLY)
        rows = S.fetch_draftpool(self.base)
        self.assertEqual([r["ID"] for r in rows], POOL_IDS)
        self.assertEqual(rows[0]["Player Name"], "Josh Adams")
        self.assertEqual(self.warnings, [])

    def test_sends_the_league_token_to_the_pool_only_on_the_test_site(self):
        self.route(self.POOL, POOL_REPLY)
        S.fetch_draftpool(self.base)
        self.assertEqual(self.hits(self.POOL), [f"token={TOKEN}"])

    def test_request_goes_to_the_trailing_slash_endpoint(self):
        self.route(self.POOL, POOL_REPLY)
        S.fetch_draftpool(self.base)
        self.assertIn(self.POOL, [p for p, _ in self.srv.log])

    def test_extra_columns_are_kept_as_sent(self):
        self.route(self.POOL, '"ID","Player Name","DEM"\n"1","A B","Impossible"\n')
        rows = S.fetch_draftpool(self.base)
        self.assertEqual(rows, [{"ID": "1", "Player Name": "A B", "DEM": "Impossible"}])

    def test_missing_player_name_warns_once_and_goes_on(self):
        self.route(self.POOL, '"ID"\n"1"\n"2"\n')
        self.assertEqual(len(S.fetch_draftpool(self.base)), 2)
        S.fetch_draftpool(self.base)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("Player Name", self.warnings[0])

    def test_empty_reply_is_no_rows(self):
        self.route(self.POOL, "")
        self.assertEqual(S.fetch_draftpool(self.base), [])

    def test_header_only_reply_is_no_rows(self):
        self.route(self.POOL, '"ID","Player Name"\n')
        self.assertEqual(S.fetch_draftpool(self.base), [])

    def test_reply_without_id_is_not_data(self):
        self.route(self.POOL, '"Player Name","Age"\n"A B","17"\n')
        with self.assertRaises(S.StatsPlusRefused) as cm:
            S.fetch_draftpool(self.base)
        self.assertEqual((cm.exception.kind, cm.exception.endpoint), ("not_data", "draftpool"))

    def test_html_page_is_not_data(self):
        self.route(self.POOL, "<html><head><title>Maintenance</title></head><body>back soon</body></html>")
        with self.assertRaises(S.StatsPlusRefused) as cm:
            S.fetch_draftpool(self.base)
        self.assertEqual(cm.exception.kind, "not_data")

    def test_json_reply_is_not_data(self):
        self.route(self.POOL, '{"ids": [1, 2]}')
        with self.assertRaises(S.StatsPlusRefused) as cm:
            S.fetch_draftpool(self.base)
        self.assertEqual(cm.exception.kind, "not_data")

    def test_text_refusals_are_typed(self):
        for body, kind in (("API token has expired", "token_expired"),
                           ("Invalid API token", "token_invalid"),
                           ("Request too soon, wait 30 seconds before the next one", "too_soon"),
                           ("This is not enabled for this league", "not_enabled"),
                           ("You must be logged in", "login_required")):
            with self.subTest(kind=kind):
                self.route(self.POOL, body)
                with self.assertRaises(S.StatsPlusRefused) as cm:
                    S.fetch_draftpool(self.base)
                self.assertEqual(cm.exception.kind, kind)
                self.assertEqual(cm.exception.endpoint, "draftpool")
                self.assertTrue(cm.exception.token_sent)
        self.route(self.POOL, "Request too soon, wait 30 seconds before the next one")
        with self.assertRaises(S.StatsPlusRefused) as cm:
            S.fetch_draftpool(self.base)
        self.assertEqual(cm.exception.wait, 30)

    def test_http_429_and_403_are_blocked(self):
        for status in (403, 429):
            with self.subTest(status=status):
                self.route(self.POOL, "", status=status)
                with self.assertRaises(S.StatsPlusRefused) as cm:
                    S.fetch_draftpool(self.base)
                self.assertEqual((cm.exception.kind, cm.exception.status), ("blocked", status))

    def test_no_message_shows_the_token(self):
        self.route(self.POOL, f"Invalid API token {TOKEN}")
        with self.assertRaises(S.StatsPlusRefused) as cm:
            S.fetch_draftpool(self.base)
        e = cm.exception
        self.assertNotIn(TOKEN, f"{e} {e!r} {e.message} {e.user_message('SSB')}")

    def test_redirect_to_another_site_is_refused_before_it_is_sent(self):
        self.route(self.POOL, "", status=302, headers={"Location": "http://example.com/steal"})
        with self.assertRaises(S.OffSiteError) as cm:
            S.fetch_draftpool(self.base)
        self.assertNotIn(TOKEN, str(cm.exception))
        self.assertEqual(len(self.hits(self.POOL)), 1)

    def test_cache_reuses_the_reply_while_the_game_date_is_unchanged(self):
        self.route(self.POOL, POOL_REPLY)
        first = S.fetch_draftpool(self.base, cache=True)
        second = S.fetch_draftpool(self.base, cache=True)
        self.assertEqual(first, second)
        self.assertEqual(len(self.hits(self.POOL)), 1)          # one pool request
        self.assertEqual(len(self.hits("/ssb/api/date")), 1)    # and /date asked once (60 s memo)

    def test_cache_asks_again_when_the_game_date_moves(self):
        self.route(self.POOL, POOL_REPLY)
        S.fetch_draftpool(self.base, cache=True)
        self.route("/ssb/api/date", "2044-05-03")
        S.clear_date_memo()
        S.fetch_draftpool(self.base, cache=True)
        self.assertEqual(len(self.hits(self.POOL)), 2)

    def test_default_call_neither_reads_nor_saves_the_cache(self):
        self.route(self.POOL, POOL_REPLY)
        S.fetch_draftpool(self.base)
        S.fetch_draftpool(self.base)
        self.assertEqual(len(self.hits(self.POOL)), 2)
        self.assertEqual(self.hits("/ssb/api/date"), [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "sp")))

    def test_refused_date_still_asks_the_endpoint_and_saves_nothing(self):
        self.route("/ssb/api/date", "API token has expired")
        self.route(self.POOL, POOL_REPLY)
        self.assertEqual(len(S.fetch_draftpool(self.base, cache=True)), 6)
        self.assertEqual(len(S.fetch_draftpool(self.base, cache=True)), 6)
        self.assertEqual(len(self.hits(self.POOL)), 2)


# ---- draft.py: the pool source order ----------------------------------------------------------

import draft as D  # noqa: E402


def api_rows(ids=POOL_IDS, **extra):
    return [dict({"ID": i, "Player Name": f"P{i}"}, **extra) for i in ids]


def export_csv(path, rows, header=("ID", "Name", "DEM", "Sign", "SctAcc", "NAT", "Inf")):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(str(r.get(h, "")) for h in header) + "\n")


class PoolSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def resolve(self, league="SSB", paths=(), source="auto", api=None):
        """_resolve_pool with fetch_draftpool replaced: api is a list of rows, or an exception."""
        def fake(base, **kw):
            if isinstance(api, BaseException):
                raise api
            return api
        out = io.StringIO()
        with mock.patch.object(S, "fetch_draftpool", side_effect=fake) as m, contextlib.redirect_stdout(out):
            try:
                res = D._resolve_pool(league, "ssb", list(paths), source)
            except SystemExit as e:
                res = e.code
        return res, out.getvalue(), m

    def test_statsplus_alone_supplies_the_pool(self):
        (pool, labels), out, m = self.resolve(api=api_rows())
        self.assertEqual(list(pool), POOL_IDS)
        self.assertEqual(pool["73232"], {"ID": "73232", "Name": "P73232", "_isPit": None})
        self.assertEqual(labels, ["StatsPlus /draftpool/ (6)"])
        self.assertEqual(m.call_args.kwargs, {"cache": True})       # date-keyed cache, not a fresh read

    def test_duplicate_and_blank_ids_are_dropped(self):
        (pool, _), _, _ = self.resolve(api=api_rows(["5", "5", " ", "6"]))
        self.assertEqual(list(pool), ["5", "6"])

    def test_export_adds_only_what_statsplus_does_not_send(self):
        p = os.path.join(self.tmp, "major_league_baseball_draft_pool_-_draft_pool_pitcher_export.csv")
        export_csv(p, [{"ID": "73232", "Name": "X", "DEM": "Hard", "Sign": "Easy", "SctAcc": "High"},
                       {"ID": "99999", "Name": "Export Only", "DEM": "Easy"}])
        api = api_rows(["73232", "73121"])
        api[1]["DEM"] = "Normal"                                      # StatsPlus value must not be overwritten
        (pool, labels), out, _ = self.resolve(paths=[p], api=api)
        self.assertEqual(set(pool), {"73232", "73121"})              # the export-only player is not added
        self.assertEqual((pool["73232"]["DEM"], pool["73232"]["Sign"], pool["73232"]["SctAcc"]), ("Hard", "Easy", "High"))
        self.assertIs(pool["73232"]["_isPit"], True)                  # the split-file tag carries over
        self.assertEqual(pool["73121"]["DEM"], "Normal")
        self.assertEqual(pool["73232"]["Name"], "P73232")             # the name stays StatsPlus's
        self.assertIn("in both 1", out)
        self.assertIn("they differ", out)
        self.assertEqual(labels[0], "StatsPlus /draftpool/ (2)")

    def test_a_stale_export_is_not_warned_about_when_statsplus_answers(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "73232"}])
        os.utime(p, (1_000_000_000, 1_000_000_000))
        _, out, _ = self.resolve(paths=[p], api=api_rows(["73232"]))
        self.assertNotIn("WARNING", out)

    def test_refused_with_an_export_uses_the_export_and_says_why(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "7", "Name": "Seven"}])
        err = S.StatsPlusRefused("not_enabled", "not enabled", endpoint="draftpool", slug="ssb")
        (pool, labels), out, _ = self.resolve(paths=[p], api=err)
        self.assertEqual(list(pool), ["7"])
        self.assertEqual(labels, ["pool.csv"])
        self.assertIn("WARNING: StatsPlus refused the SSB /draftpool request", out)
        self.assertIn("using the OOTP draft-pool export", out)

    def test_refused_without_an_export_stops_with_exit_3(self):
        err = S.StatsPlusRefused("token_expired", "API token has expired", endpoint="draftpool", slug="ssb")
        code, out, _ = self.resolve(api=err)
        self.assertEqual(code, D.EXIT_REFUSED)
        self.assertIn("token has expired", out)
        self.assertIn("left as-is", out)

    def test_refused_without_an_export_lets_blm_try_its_flag(self):
        err = S.StatsPlusRefused("not_enabled", "not enabled", endpoint="draftpool", slug="blm")
        (pool, labels), out, _ = self.resolve(league="BLM", api=err)
        self.assertEqual((pool, labels), ({}, []))
        self.assertIn("WARNING", out)

    def test_network_failure_falls_back_to_the_export(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "7"}])
        (pool, labels), out, _ = self.resolve(paths=[p], api=OSError(f"connection reset {TOKEN}"))
        self.assertEqual(list(pool), ["7"])
        self.assertIn("could not be read (OSError", out)

    def test_network_failure_without_an_export_is_no_pool(self):
        (pool, labels), out, _ = self.resolve(api=ConnectionError("down"))
        self.assertEqual((pool, labels), ({}, []))

    def test_off_site_redirect_is_reported_without_the_token(self):
        with mock.patch.dict(os.environ, {"STATSPLUS_TEST_TOKEN_SSB": TOKEN}):
            (pool, _), out, _ = self.resolve(api=S.OffSiteError(f"went to example.com ?token={TOKEN}"))
        self.assertEqual(pool, {})
        self.assertNotIn(TOKEN, out)

    def test_empty_statsplus_list_falls_back_to_the_export(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "7"}])
        (pool, _), out, _ = self.resolve(paths=[p], api=[])
        self.assertEqual(list(pool), ["7"])
        self.assertIn("sent an empty list", out)

    def test_source_export_never_asks_statsplus(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "7"}])
        (pool, _), _, m = self.resolve(paths=[p], source="export", api=api_rows())
        self.assertEqual(list(pool), ["7"])
        m.assert_not_called()

    def test_source_statsplus_never_reads_the_export(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "7"}])
        (pool, _), out, _ = self.resolve(paths=[p], source="statsplus", api=api_rows(["8"]))
        self.assertEqual(list(pool), ["8"])
        self.assertNotIn("pool.csv", out)

    def test_columns_sent_under_board_names_are_copied_and_others_are_reported(self):
        (pool, _), out, _ = self.resolve(api=api_rows(["8"], DEM="Impossible", Mystery="x"))
        self.assertEqual(pool["8"]["DEM"], "Impossible")
        self.assertNotIn("Mystery", pool["8"])
        self.assertIn("also sends Mystery", out)


# ---- the whole board for an SSB-like league, from a saved pull ---------------------------------------

class SsbBoard(unittest.TestCase):
    """draft.main() for league SSB (no ootp_save, priced on the BLM basis) with the pool from StatsPlus
    and the ratings from the trimmed pull. Writes only into a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        os.makedirs(os.path.join(self.tmp, "ingest", ".cache"))
        shutil.copy(os.path.join(FIX, "pull_ssb_amateurs.json"),
                    os.path.join(self.tmp, "ingest", ".cache", "statsplus_ssb.json"))
        self.data = os.path.join(self.tmp, "repo", "tgs-viz", "public", "data", "SSB")
        os.makedirs(self.data)

    def run_main(self, pool_rows, picks=(), extra_args=()):
        argv = ["draft.py", "--league", "SSB", "--slug", "ssb", "--calib", "BLM", "--write", *extra_args]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(D, "HERE", os.path.join(self.tmp, "ingest")), \
                mock.patch.object(D, "REPO", os.path.join(self.tmp, "repo")), \
                mock.patch.object(S, "fetch_draftpool", return_value=pool_rows), \
                mock.patch.object(S, "fetch_draft", return_value=list(picks)), \
                contextlib.redirect_stdout(out):
            D.main()
        return out.getvalue()

    def load(self, name):
        with open(os.path.join(self.data, name), encoding="utf-8") as f:
            return json.load(f)

    def test_board_is_built_for_the_statsplus_pool_only(self):
        log = self.run_main(api_rows())
        self.assertIn("6 draft-pool players from StatsPlus /draftpool/ (6)", log)
        self.assertIn("matched 6 of them in the StatsPlus ratings pull", log)
        hit, pit = self.load("hitters_draft.json"), self.load("pitchers_draft.json")
        self.assertEqual(sorted(r["ID"] for r in hit), sorted(POOL_IDS[:3]))
        self.assertEqual(sorted(r["ID"] for r in pit), sorted(POOL_IDS[3:]))
        self.assertTrue(all(r["Lev"] == "DRAFT" for r in hit + pit))
        for pid in NOT_IN_POOL:
            self.assertNotIn(pid, [r["ID"] for r in hit + pit])
        for name in ("hitters_draft_all.json", "hitters_draft_park.json", "hitters_draft_all_park.json",
                     "pitchers_draft_all.json", "pitchers_draft_park.json", "pitchers_draft_all_park.json"):
            self.assertTrue(os.path.exists(os.path.join(self.data, name)), name)

    def test_players_with_the_same_name_are_told_apart_by_id(self):
        # 73232 (a catcher) and 74426 (a pitcher) are both "Josh Adams"; only 73232 is in the pool
        self.run_main(api_rows(["73232"]))
        self.assertEqual([r["ID"] for r in self.load("hitters_draft.json")], ["73232"])
        self.assertEqual(self.load("pitchers_draft.json"), [])

    def test_a_pick_is_stamped_and_leaves_the_live_board(self):
        pick = {"ID": "73121", "Player Name": "Rob Albin", "Overall": "1", "Round": "1",
                "Pick In Round": "1", "Team": "Somewhere"}
        self.run_main(api_rows(), picks=[pick])
        live = [r["ID"] for r in self.load("hitters_draft.json")]
        full = {r["ID"]: r for r in self.load("hitters_draft_all.json")}
        self.assertNotIn("73121", live)
        self.assertEqual(full["73121"]["DraftedOverall"], "1")
        self.assertEqual(len(full), 3)

    def test_the_export_only_adds_columns_for_players_in_the_statsplus_pool(self):
        p = os.path.join(self.tmp, "pool.csv")
        export_csv(p, [{"ID": "73232", "DEM": "Hard", "Sign": "Easy"}, {"ID": "74485", "DEM": "Easy"}])
        with mock.patch.object(D, "DEFAULT_CSV", {"SSB": [[p]]}):
            self.run_main(api_rows())
        hit = {r["ID"]: r for r in self.load("hitters_draft.json")}
        self.assertEqual(hit["73232"]["DEM"], "Hard")
        self.assertNotIn("DEM", hit["73121"])
        self.assertNotIn("74485", hit)

    def test_empty_pool_and_no_export_writes_nothing(self):
        log = self.run_main([])
        self.assertIn("No draft pool for SSB", log)
        self.assertEqual(os.listdir(self.data), [])

    def test_bad_pool_source_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_main(api_rows(), extra_args=["--pool-source", "magic"])
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
