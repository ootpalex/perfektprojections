"""
test_salary_report.py - ingest/salary_report.py (team salary report pages: parser, MLB team set, record
keys, and the request rules: one at a time, date-keyed cache, no token, typed refusals, stay on site).

    python tgs-viz/tools/tests/test_salary_report.py
    python -m pytest tgs-viz/tools/tests/test_salary_report.py -q

Offline. NO real StatsPlus page is saved anywhere. fixtures/salary_report/team_32_page_UNVERIFIED.html is
a synthetic page built from the dashboard's parser regexes and six players of its saved parsed results
(fixtures/salary_report/saved_parsed_ssb.json, game date 2044-05-09). One live request replaces it
(docs/phase3/salary_report.md section 8). The request rules run against a mock server on 127.0.0.1 (the
client's own test mechanism: STATSPLUS_TEST_BASE_URL, a fake token from the environment, a temporary
cache folder).
"""
import copy
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
sys.path.insert(0, os.path.join(VIZ, "ingest"))
sys.path.insert(0, TOOLS)

import salary_report as SR  # noqa: E402
import statsplus as S  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "salary_report")
PAGE = open(os.path.join(FIX, "team_32_page_UNVERIFIED.html"), encoding="utf-8").read()
with open(os.path.join(FIX, "saved_parsed_ssb.json"), encoding="utf-8") as _f:
    SAVED = json.load(_f)["players"]
TOKEN = "tok-SECRET-123456"


def _page(extra_rows=""):
    """The fixture page with extra table rows (to give different teams different players)."""
    return PAGE.replace("<tr><td colspan", extra_rows + "<tr><td colspan")


class ParseCell(unittest.TestCase):
    def test_salary_text(self):
        self.assertEqual(SR.parse_salary_text("$3.2M"), 3_200_000)
        self.assertEqual(SR.parse_salary_text("$804K"), 804_000)
        self.assertEqual(SR.parse_salary_text("1,250,000"), 1_250_000)
        self.assertIsNone(SR.parse_salary_text("TBD"))
        self.assertIsNone(SR.parse_salary_text(""))

    def test_marks_map_to_types(self):
        for text, ctype, ann in (("$4.6M (A)", "arb", "A"), ("$1.7M (A*)", "arb_uncertain", "A*"),
                                 ("$1.7M (A#)", "arb_uncertain", "A#"), ("$571K (*)", "milb", "*"),
                                 ("$1.0M (T)", "team_option", "T"), ("$1.0M (P)", "player_option", "P"),
                                 ("$1.0M (V)", "vesting_option", "V"), ("$37.0M (O)", "opt_out", "O"),
                                 ("$2.0M (R)", "retained", "R")):
            c = SR.parse_cell(text)
            self.assertEqual((c["type"], c["ann"], c["guaranteed"]), (ctype, ann, True), text)
            self.assertIsNotNone(c["salary"], text)

    def test_italic_is_not_guaranteed(self):
        self.assertFalse(SR.parse_cell("<i>$4.6M (A)</i>")["guaranteed"])
        self.assertFalse(SR.parse_cell("<em>$4.6M (A)</em>")["guaranteed"])
        self.assertFalse(SR.parse_cell('<i class="x">$4.6M (A)</i>')["guaranteed"])
        self.assertTrue(SR.parse_cell("$4.6M")["guaranteed"])

    def test_an_image_tag_is_not_italic(self):
        # the dashboard's <[ie][m>] test also fires on <img
        self.assertTrue(SR.parse_cell('<img src="x.png">$4.6M')["guaranteed"])

    def test_empty_dash_and_milc(self):
        for t in ("", "—", "-", "&nbsp;"):
            self.assertEqual(SR.parse_cell(t)["type"], "fa", t)
        self.assertEqual(SR.parse_cell("<i>MiLC</i>")["type"], "milc")

    def test_unreadable_text_is_unparsed_not_signed(self):
        c = SR.parse_cell("<i>TBD</i>")
        self.assertEqual((c["type"], c["salary"], c["raw"]), ("unparsed", None, "TBD"))
        self.assertEqual(len(SR.parse_cell("x" * 100)["raw"]), SR.RAW_MAX)

    def test_a_mark_with_no_amount_keeps_the_type(self):
        c = SR.parse_cell("(A)")
        self.assertEqual((c["type"], c["salary"]), ("arb", None))


class ParsePage(unittest.TestCase):
    def setUp(self):
        self.page = SR.parse_report_html(PAGE)

    def test_span_and_players(self):
        self.assertEqual(self.page["span"], [2044, 2053])
        self.assertEqual(sorted(self.page["players"]), sorted(SAVED))

    def test_the_total_row_is_not_a_player(self):
        self.assertEqual(len(self.page["players"]), 6)

    def test_matches_the_saved_parsed_results_cell_by_cell(self):
        """The synthetic page was rendered from the saved results, so parsing it must give them back
        (except the two invented 'TBD' cells, which the saved results call 'signed' with no salary)."""
        for pid, saved in SAVED.items():
            got = self.page["players"][pid]
            self.assertEqual((got["name"], got["pos"]), (saved["name"], saved["pos"]))
            for y, c in saved["years"].items():
                g = got["years"][int(y)]
                if g["type"] == "unparsed":
                    self.assertEqual((c["type"], c["salary"]), ("signed", None))
                    continue
                self.assertEqual((g["type"], g["salary"], g["guaranteed"]),
                                 (c["type"], c["salary"], c["guaranteed"]), f"{pid} {y}")

    def test_page_without_year_headers_is_not_a_report(self):
        self.assertIsNone(SR.parse_report_html("<html>API token has expired</html>")["span"])
        self.assertIsNone(SR.parse_report_html("")["span"])

    def test_more_cells_than_year_columns_are_ignored(self):
        html = ('<tr><th>Pos</th><th>Nm</th><th>Age</th><th>2044</th></tr>'
                '<tr><td>C</td><td><a href="x/player_9.html">A B</a></td><td>1</td><td>$1.0M</td><td>$2.0M</td></tr>')
        self.assertEqual(list(SR.parse_report_html(html)["players"]["9"]["years"]), [2044])


class RecordKeys(unittest.TestCase):
    def setUp(self):
        self.players = SR.parse_report_html(PAGE)["players"]
        self.span = [2044, 2053]

    def keys(self, pid):
        return SR.entry_keys(self.players[pid], self.span)

    def test_arb_projection_is_the_first_arbitration_cell(self):
        k = self.keys("59554")["ArbProjection"]                # 2046 (A) 4.6M, 2047 6.0M, 2048 7.0M
        self.assertEqual(k, {"yr": 2046, "salary": 4_600_000, "uncertain": False, "ann": "A", "n": 3})

    def test_an_uncertain_first_cell_is_flagged(self):
        k = self.keys("68528")["ArbProjection"]                # 2047 (A*) 1.3M, then three (A)
        self.assertEqual(k, {"yr": 2047, "salary": 1_300_000, "uncertain": True, "ann": "A*", "n": 4})

    def test_values_equal_the_saved_results(self):
        for pid, saved in SAVED.items():
            arb = [(int(y), c) for y, c in sorted(saved["years"].items()) if c["type"] in ("arb", "arb_uncertain")]
            k = self.keys(pid)
            if not arb:
                self.assertNotIn("ArbProjection", k, pid)
                continue
            self.assertEqual((k["ArbProjection"]["yr"], k["ArbProjection"]["salary"], k["ArbProjection"]["n"]),
                             (arb[0][0], arb[0][1]["salary"], len(arb)), pid)

    def test_no_arbitration_cell_no_key(self):
        k = self.keys("63066")
        self.assertNotIn("ArbProjection", k)

    def test_opt_out_years(self):
        self.assertEqual(self.keys("63066")["OptOutYrs"], [2047])
        self.assertEqual(self.keys("58156")["OptOutYrs"], [2045])
        self.assertNotIn("OptOutYrs", self.keys("59554"))

    def test_retained_years(self):
        entry = {"name": "A", "pos": "SP", "years": {2044: SR.parse_cell("$5.0M"), 2045: SR.parse_cell("$2.0M (R)"),
                                                      2046: SR.parse_cell("")}}
        k = SR.entry_keys(entry, [2044, 2046])
        self.assertEqual(k["RetainedYrs"], [2045])
        self.assertEqual(sorted(k["SalaryReport"]), ["2044", "2045"])      # the FA year is left out

    def test_fa_cells_are_left_out_and_the_span_says_so(self):
        k = self.keys("54669")
        self.assertEqual(sorted(k["SalaryReport"]), ["2044", "2045", "2046"])
        self.assertEqual(k["SalaryReportSpan"], [2044, 2053])

    def test_cell_shape(self):
        c = self.keys("59554")["SalaryReport"]["2046"]
        self.assertEqual(c, {"salary": 4_600_000, "type": "arb", "guaranteed": False, "ann": "A"})
        u = self.keys("59554")["SalaryReport"]["2045"]
        self.assertEqual((u["type"], u["raw"]), ("unparsed", "TBD"))

    def test_keys_are_json_serialisable(self):
        json.dumps(self.keys("68528"))


class Attach(unittest.TestCase):
    def setUp(self):
        self.page = SR.parse_report_html(PAGE)

    def test_only_listed_players_gain_keys_and_no_existing_key_changes(self):
        recs = [{"ID": "59554", "Price": 1, "Max WAA wtd": 2.5}, {"ID": "999", "Price": 3}, {"ID": 63066}]
        before = copy.deepcopy(recs)
        n = SR.attach_salary_reports(recs, self.page["players"], self.page["span"])
        self.assertEqual(n, 2)                                  # the id may be an int in a record
        for a, b in zip(before, recs):
            for k, v in a.items():
                self.assertEqual(b[k], v, k)
        self.assertEqual(recs[1], before[1])
        self.assertIn("SalaryReport", recs[0])
        self.assertIn("OptOutYrs", recs[2])

    def test_rerun_drops_stale_keys(self):
        r = {"ID": "999", "ArbProjection": {"yr": 1}, "SalaryReport": {}}
        SR.attach_salary_reports([r], self.page["players"], self.page["span"])
        self.assertEqual(r, {"ID": "999"})

    def test_no_pages_attaches_nothing(self):
        r = {"ID": "59554"}
        self.assertEqual(SR.attach_salary_reports([r], {}, None), 0)
        self.assertEqual(r, {"ID": "59554"})


class TeamSet(unittest.TestCase):
    TEAMS = [{"ID": "31", "Name": "Arizona", "Nickname": "Diamondbacks", "Parent Team ID": "0"},
             {"ID": "32", "Name": "Atlanta", "Nickname": "Braves", "Parent Team ID": "0"},
             {"ID": "359", "Name": "All-Stars", "Nickname": "All-Stars", "Parent Team ID": "0"},
             {"ID": "3101", "Name": "Reno", "Nickname": "Aces", "Parent Team ID": "31"},
             {"ID": "439", "Name": "Samsung", "Nickname": "Lions", "Parent Team ID": "0"}]

    def test_mlb_level_clubs_only(self):
        rows = [{"Org": "32", "Lev": "MLB"}, {"Org": "31", "Lev": "MLB"}, {"Org": "31", "Lev": "AAA"},
                {"Org": "3101", "Lev": "AAA"}, {"Org": "439", "Lev": "A+"}, {"Org": "0", "Lev": "FA"},
                {"Org": "32", "Lev": "MLB"}]
        self.assertEqual(SR.mlb_team_ids(rows, self.TEAMS), ["31", "32"])

    def test_a_club_missing_from_teams_or_with_a_parent_is_dropped(self):
        rows = [{"Org": "3101", "Lev": "MLB"}, {"Org": "777", "Lev": "MLB"}, {"Org": "32", "Lev": "MLB"}]
        self.assertEqual(SR.mlb_team_ids(rows, self.TEAMS), ["32"])
        self.assertEqual(SR.mlb_team_ids(rows), ["32", "777", "3101"])

    def test_numeric_order(self):
        rows = [{"Org": "100", "Lev": "MLB"}, {"Org": "9", "Lev": "MLB"}]
        self.assertEqual(SR.mlb_team_ids(rows), ["9", "100"])

    def test_report_url(self):
        self.assertEqual(SR.report_url("https://statsplus.net/ssb/api", "32"),
                         "https://statsplus.net/ssb/reports/news/html/teams/team_32_player_salary_report.html")
        self.assertEqual(SR.report_url("https://statsplus.net/ssb/api", "32", "https://atl-01.statsplus.net/ssb/"),
                         "https://atl-01.statsplus.net/ssb/reports/news/html/teams/team_32_player_salary_report.html")


class Mock(BaseHTTPRequestHandler):
    """routes: {path: (status, body, headers)}; log: [(path, query, headers)]; set per test on the server."""

    def do_GET(self):
        path, _, query = self.path.partition("?")
        self.server.log.append((path, query, dict(self.headers)))
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


def _team_path(tid):
    return f"/ssb/reports/news/html/teams/team_{tid}_player_salary_report.html"


class Fetch(unittest.TestCase):
    """A mock StatsPlus on 127.0.0.1 and an isolated client (cache folder, token, date memo)."""

    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), Mock)
        self.srv.log, self.srv.routes = [], {"/ssb/api/date": (200, "2044-05-09", {})}
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = tempfile.mkdtemp()
        env = {"STATSPLUS_TEST_BASE_URL": f"http://127.0.0.1:{self.srv.server_port}",
               "STATSPLUS_CACHE_DIR": os.path.join(self.tmp, "sp"), "STATSPLUS_TEST_TOKEN_SSB": TOKEN}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        S.clear_date_memo()
        S._WARNED.clear()
        self.base = S.normalize_base("ssb")
        self.pauses = []
        for tid in ("32", "33", "34"):
            self.srv.routes[_team_path(tid)] = (200, PAGE, {})

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def hits(self, prefix="/ssb/reports"):
        return [h for h in self.srv.log if h[0].startswith(prefix)]

    def fetch(self, ids=("32", "33", "34"), **kw):
        return SR.fetch_reports(self.base, list(ids), sleep=self.pauses.append, **kw)

    def test_first_pull_fetches_every_page_the_second_reuses_all(self):
        a = self.fetch()
        self.assertEqual((a.fetched, a.reused, a.pages, a.failed, a.stopped), (3, 0, 3, [], None))
        self.assertEqual(len(self.hits()), 3)
        b = self.fetch()
        self.assertEqual((b.fetched, b.reused), (0, 3))
        self.assertEqual(len(self.hits()), 3)                  # no new page request
        self.assertEqual(sorted(b.players), sorted(a.players))
        self.assertEqual(b.span, [2044, 2053])

    def test_pages_are_requested_one_at_a_time_in_order_with_a_pause_between_live_requests(self):
        self.fetch()
        self.assertEqual([h[0] for h in self.hits()], [_team_path(t) for t in ("32", "33", "34")])
        self.assertEqual(self.pauses, [SR.PAGE_GAP_S, SR.PAGE_GAP_S])     # none before the first
        self.pauses.clear()
        self.fetch()
        self.assertEqual(self.pauses, [])                                  # cached pages cost no pause

    def test_the_date_is_read_once_not_per_page(self):
        self.fetch()
        self.assertEqual(len([h for h in self.srv.log if h[0] == "/ssb/api/date"]), 1)

    def test_a_new_game_date_reads_the_pages_again(self):
        self.fetch()
        S.clear_date_memo()
        self.srv.routes["/ssb/api/date"] = (200, "2044-05-10", {})
        b = self.fetch()
        self.assertEqual((b.fetched, b.reused), (3, 0))

    def test_an_old_copy_is_not_reused(self):
        self.fetch()
        with mock.patch.object(S.time, "time", return_value=S.time.time() + 7 * 3600):
            b = self.fetch()
        self.assertEqual((b.fetched, b.reused), (3, 0))

    def test_no_token_is_sent_even_when_one_is_saved(self):
        self.fetch()
        for path, query, headers in self.hits():
            self.assertEqual(query, "")
            self.assertNotIn("Authorization", headers)
            self.assertNotIn("Cookie", headers)
            self.assertNotIn(TOKEN, path)

    def test_the_raw_page_is_what_is_cached(self):
        self.fetch(["32"])
        import gzip
        folder = S.cache_folder("ssb")
        names = [n for n in os.listdir(folder) if "salary_report" in n]
        self.assertEqual(len(names), 1)
        with gzip.open(os.path.join(folder, names[0]), "rt", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["data"], PAGE)

    def test_players_from_every_page_are_merged(self):
        extra = ('<tr><td>SS</td><td><a href="../players/player_111.html">New Guy</a></td><td>25</td>'
                 '<td>$1.0M</td>' + "<td></td>" * 9 + "</tr>")
        self.srv.routes[_team_path("33")] = (200, _page(extra), {})
        r = self.fetch()
        self.assertIn("111", r.players)
        self.assertIn("59554", r.players)

    def test_a_token_refusal_stops_the_run_and_saves_nothing(self):
        self.srv.routes[_team_path("32")] = (200, "API token has expired", {})
        r = self.fetch()
        self.assertEqual(len(self.hits()), 1)                  # stopped at once
        self.assertEqual(r.failed, [("32", "token_expired")])
        self.assertIsNotNone(r.stopped)
        self.assertIsInstance(r.refusal, S.StatsPlusRefused)
        self.assertEqual((r.fetched, r.reused, r.players), (0, 0, {}))
        folder = S.cache_folder("ssb")
        self.assertEqual([n for n in os.listdir(folder) if "salary_report" in n] if os.path.isdir(folder) else [], [])

    def test_a_login_page_is_a_typed_refusal(self):
        self.srv.routes[_team_path("32")] = (200, "<html><title>Log in</title><form>password</form></html>", {})
        r = self.fetch()
        self.assertEqual(r.failed, [("32", "login_required")])
        self.assertEqual(len(self.hits()), 1)

    def test_a_non_report_page_is_not_data(self):
        self.srv.routes[_team_path("32")] = (200, "<html><title>Oops</title>nothing here</html>", {})
        r = self.fetch()
        self.assertEqual(r.failed, [("32", "not_data")])

    def test_http_429_stops_at_once(self):
        self.srv.routes[_team_path("32")] = (429, "Request too soon, wait 30 seconds", {})
        r = self.fetch()
        self.assertEqual(len(self.hits()), 1)
        self.assertEqual(r.failed[0][1], "blocked")

    def test_two_missing_pages_in_a_row_stop_the_run(self):
        ids = ["701", "702", "703", "704", "32"]               # no routes for 701..704: 404
        r = self.fetch(ids)
        self.assertEqual(len(self.hits()), 2)                  # a wrong path costs 2 requests, not all
        self.assertEqual(len(r.failed), 2)
        self.assertIn("2 failures in a row", r.stopped)
        self.assertEqual(r.players, {})

    def test_one_missing_page_does_not_stop_the_run(self):
        r = self.fetch(["32", "701", "33"])
        self.assertEqual((r.fetched, len(r.failed), r.stopped), (2, 1, None))
        self.assertIn("59554", r.players)

    def test_a_redirect_to_another_host_is_refused_before_it_is_followed(self):
        other = HTTPServer(("127.0.0.1", 0), Mock)      # another port = another site for the client
        other.log, other.routes = [], {"/x": (200, PAGE, {})}
        threading.Thread(target=other.serve_forever, daemon=True).start()
        self.addCleanup(other.server_close)
        self.addCleanup(other.shutdown)
        self.srv.routes[_team_path("32")] = (302, "", {"Location": f"http://127.0.0.1:{other.server_port}/x"})
        r = self.fetch()
        self.assertEqual(other.log, [])                        # nothing was sent there
        self.assertEqual(r.failed, [("32", "OffSiteError")])
        self.assertIsInstance(r.refusal, S.OffSiteError)

    def test_a_foreign_report_base_is_refused_before_sending(self):
        r = self.fetch(["32"], report_base_url="https://example.com/ssb")
        self.assertEqual(self.hits(), [])
        self.assertEqual(r.failed, [("32", "OffSiteError")])

    def test_no_message_shows_the_token(self):
        self.srv.routes[_team_path("32")] = (200, f"token {TOKEN} is invalid", {})
        r = self.fetch()
        self.assertNotIn(TOKEN, repr((r.failed, r.stopped)))

    def test_fresh_reads_again_and_saves(self):
        self.fetch()
        b = self.fetch(fresh=True)
        self.assertEqual((b.fetched, b.reused), (3, 0))

    def test_end_to_end_keys_on_records(self):
        r = self.fetch()
        recs = [{"ID": "59554"}, {"ID": "63066"}, {"ID": "1"}]
        self.assertEqual(SR.attach_salary_reports(recs, r.players, r.span), 2)
        self.assertEqual(recs[0]["ArbProjection"]["salary"], 4_600_000)
        self.assertEqual(recs[1]["OptOutYrs"], [2047])
        self.assertNotIn("SalaryReport", recs[2])


class SavedSummary(unittest.TestCase):
    def test_summary_of_a_saved_cache_file(self):
        import gzip
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "c.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"game_date": "2044-05-09", "salary_reports": SAVED}, f)
        s = SR.summarize_saved(path, out=lambda t: None)
        self.assertEqual(s["players"], 6)
        self.assertEqual(s["players_with_type"]["arb"], 3)         # 59554, 68528, 62024
        self.assertEqual(s["players_with_type"]["opt_out"], 2)
        self.assertEqual(s["cells_by_type"]["arb"], 3 + 3 + 3)


if __name__ == "__main__":
    unittest.main()


class LivePage(unittest.TestCase):
    """A real SSB page (team 42, 2026-10-04), trimmed to six player rows: the shapes the synthetic
    fixture could only guess, including cells with several marks ("(P,O)", "(*auto)")."""

    def setUp(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "salary_report",
                         "team_42_live_trimmed.html")
        with open(p, encoding="utf-8") as fh:
            self.page = SR.parse_report_html(fh.read())

    def test_span_and_players(self):
        self.assertEqual(self.page["span"], [2044, 2053])
        self.assertEqual(len(self.page["players"]), 6)

    def test_multi_mark_cells(self):
        y = self.page["players"]["54669"]["years"]
        self.assertEqual((y[2045]["type"], y[2045]["marks"]), ("player_option", ["player_option", "opt_out"]))
        self.assertEqual(SR.entry_keys(self.page["players"]["54669"], self.page["span"])["OptOutYrs"], [2045])
        auto = self.page["players"]["68579"]["years"][2045]
        self.assertEqual((auto["type"], auto["marks"]), ("milb", ["milb", "auto"]))
        self.assertIsNotNone(auto["salary"])

    def test_arbitration_projection(self):
        keys = SR.entry_keys(self.page["players"]["60499"], self.page["span"])
        self.assertEqual(keys["ArbProjection"]["yr"], 2046)
        self.assertTrue(keys["ArbProjection"]["uncertain"])
        self.assertEqual(keys["ArbProjection"]["n"], 4)

    def test_no_unparsed_cells(self):
        cells = [c for p in self.page["players"].values() for c in p["years"].values()]
        self.assertFalse([c for c in cells if c["type"] == "unparsed"])
