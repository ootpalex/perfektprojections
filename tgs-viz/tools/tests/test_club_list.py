"""
test_club_list.py - ingest/club_list.py: the league's MLB clubs and sub-leagues in metadata.json.

    python tgs-viz/tools/tests/test_club_list.py
    python -m pytest tgs-viz/tools/tests/test_club_list.py -q

Offline. fixtures/club_list/league_home_trimmed.html is cut down from the league home page OOTP 27.2
wrote into the SSB save. No StatsPlus copy of that page is saved; a fake statsplus module stands in.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(VIZ, "ingest"))

import club_list as CL  # noqa: E402

with open(os.path.join(HERE, "fixtures", "club_list", "league_home_trimmed.html"), encoding="utf-8") as _f:
    PAGE = _f.read()

TEAMS = [  # /teams rows: four SSB clubs, an affiliate, an all-star team and a foreign club
    {"ID": "35", "Name": "Chicago", "Nickname": "White Sox", "Parent Team ID": "0"},
    {"ID": "36", "Name": "Chicago", "Nickname": "Cubs", "Parent Team ID": "0"},
    {"ID": "50", "Name": "Portland", "Nickname": "Loggers", "Parent Team ID": "0"},
    {"ID": "52", "Name": "Nashville", "Nickname": "Stars", "Parent Team ID": "0"},
    {"ID": "171", "Name": "Iowa", "Nickname": "Cubs", "Parent Team ID": "36"},
    {"ID": "85", "Name": "American League", "Nickname": "All-Stars", "Parent Team ID": "0"},
    {"ID": "439", "Name": "Samsung", "Nickname": "Lions", "Parent Team ID": "0"},
]
ROWS = ([{"Org": o, "Lev": "MLB", "League": "155"} for o in ("35", "36", "50", "52")]
        + [{"Org": "36", "Lev": "AAA", "League": "156"}, {"Org": "439", "Lev": "R+", "League": "119"},
           {"Org": "0", "Lev": "FA", "League": "0"}])
CLUBS = CL.mlb_clubs(ROWS, TEAMS)


class FakeS:
    """The bits of statsplus.py fetch_split uses. pages: list of replies (str or Exception) in order."""

    class Refused(Exception):
        pass

    def __init__(self, *pages):
        self.pages = list(pages)
        self.urls = []

    def _open(self, url, token=None, stay_on=None):
        assert token is False and stay_on
        self.urls.append(url)
        p = self.pages.pop(0)
        if isinstance(p, Exception):
            raise p
        return p, False

    def _cached(self, base, url, fetch, cache, fresh):
        return fetch()

    def _refused_reply(self, text, what, url, sent):
        return FakeS.Refused(what)


class Clubs(unittest.TestCase):
    def test_mlb_clubs_from_the_mlb_rows(self):
        self.assertEqual([(c["id"], c["name"]) for c in CLUBS],
                         [("36", "Chicago Cubs"), ("35", "Chicago White Sox"), ("52", "Nashville Stars"),
                          ("50", "Portland Loggers")])
        self.assertEqual(CL.mlb_league_id(ROWS), "155")

    def test_abbr(self):
        self.assertEqual(CL.abbr_of("American League"), "AL")
        self.assertEqual(CL.abbr_of("National League"), "NL")
        self.assertEqual(CL.abbr_of("Zotti League"), "ZL")
        self.assertEqual(CL.abbr_of("Eastern"), "EAS")


class Parse(unittest.TestCase):
    def test_standings_boxes(self):
        order, of = CL.parse_sub_leagues(PAGE, CLUBS)
        self.assertEqual(order, ["American League", "National League"])
        self.assertEqual(of, {"35": "American League", "50": "American League", "36": "National League",
                              "52": "National League"})
        self.assertTrue(CL.complete_split(CLUBS, order, of))

    def test_abbreviated_links_do_not_count(self):
        # a leader board link to the Cubs inside the AL box (text "CHC") must not make them AL
        page = PAGE.replace('<tr><td class="dl"><a href="../teams/team_35.html">',
                            '<tr><td><a href="../teams/team_36.html">CHC</a></td></tr>'
                            '<tr><td class="dl"><a href="../teams/team_35.html">', 1)
        _order, of = CL.parse_sub_leagues(page, CLUBS)
        self.assertEqual(of["36"], "National League")

    def test_preseason_heading(self):
        page = PAGE.replace("AMERICAN LEAGUE  STANDINGS", "AMERICAN LEAGUE  PREDICTED STANDINGS EAST DIVISION")
        order, _of = CL.parse_sub_leagues(page, CLUBS)
        self.assertEqual(order[0], "American League")

    def test_incomplete_split_is_dropped_whole(self):
        page = PAGE.replace("Nashville Stars</a>", "NSH</a>")
        order, of = CL.parse_sub_leagues(page, CLUBS)
        self.assertFalse(CL.complete_split(CLUBS, order, of))
        doc = CL.build_doc(CLUBS, order, of, league_id="155", game_date="2044-05-09", split_season="2044",
                           split_source="x")
        self.assertEqual(doc["sub_leagues"], [])
        self.assertTrue(all(t["sub_league"] is None for t in doc["teams"]))
        self.assertIsNone(doc["split_source"])
        self.assertEqual(len(doc["teams"]), 4)


class Metadata(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="tgs-clubs-test-")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def meta(self):
        with open(os.path.join(self.dir, "metadata.json"), encoding="utf-8") as f:
            return f.read()

    def test_merge_keeps_other_keys_and_indent(self):
        with open(os.path.join(self.dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump({"league": "SSB", "game_date": "2044-05-09", "matchups": {"OVR vR": 0.7}}, f, indent=1)
        doc = CL.build_doc(CLUBS, *CL.parse_sub_leagues(PAGE, CLUBS), league_id="155")
        self.assertEqual(CL.write_clubs(self.dir, "SSB", doc), "written")
        m = json.loads(self.meta())
        self.assertEqual(m["matchups"], {"OVR vR": 0.7})
        self.assertEqual(m["game_date"], "2044-05-09")
        self.assertEqual(m["clubs"], doc)
        self.assertIn('\n "clubs"', self.meta())
        self.assertEqual(CL.write_clubs(self.dir, "SSB", doc), "unchanged")

    def test_not_a_json_object_is_never_overwritten(self):
        with open(os.path.join(self.dir, "metadata.json"), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        self.assertTrue(CL.write_clubs(self.dir, "SSB", {"teams": []}).startswith("skipped"))
        self.assertEqual(self.meta(), "[1, 2]")

    def test_update_reads_the_page_about_once_a_season(self):
        quiet = []
        s = FakeS(PAGE)
        self.assertEqual(CL.update_clubs(self.dir, "SSB", ROWS, TEAMS, "https://statsplus.net/ssb/api",
                                         "2044-05-09", S=s, out=quiet.append), "written")
        self.assertEqual(s.urls, ["https://statsplus.net/ssb/reports/news/html/leagues/league_155_home.html"])
        doc = json.loads(self.meta())["clubs"]
        self.assertEqual([x["abbr"] for x in doc["sub_leagues"]], ["AL", "NL"])
        self.assertEqual(doc["split_season"], "2044")
        # same clubs, same season: no request
        s2 = FakeS()
        self.assertEqual(CL.update_clubs(self.dir, "SSB", ROWS, TEAMS, "https://statsplus.net/ssb/api",
                                         "2044-06-01", S=s2, out=quiet.append), "written")   # game_date moved
        self.assertEqual(s2.urls, [])
        self.assertEqual(json.loads(self.meta())["clubs"]["sub_leagues"], doc["sub_leagues"])
        # a new season asks again; a failed read keeps last season's split for the same clubs
        s3 = FakeS(OSError("timed out"))
        CL.update_clubs(self.dir, "SSB", ROWS, TEAMS, "https://statsplus.net/ssb/api", "2045-03-01", S=s3,
                        out=quiet.append)
        self.assertEqual(len(s3.urls), 1)
        kept = json.loads(self.meta())["clubs"]
        self.assertEqual(kept["sub_leagues"], doc["sub_leagues"])
        self.assertEqual(kept["split_season"], "2044")

    def test_page_without_a_split_leaves_the_clubs_unsplit(self):
        s = FakeS("<html>login</html>")
        out = []
        CL.update_clubs(self.dir, "SSB", ROWS, TEAMS, "https://statsplus.net/ssb/api", "2044-05-09", S=s,
                        out=out.append)
        doc = json.loads(self.meta())["clubs"]
        self.assertEqual(len(doc["teams"]), 4)
        self.assertEqual(doc["sub_leagues"], [])
        self.assertIn("unknown", out[-1])

    def test_never_raises(self):
        out = []
        res = CL.update_clubs(self.dir, "SSB", None, TEAMS, "https://statsplus.net/ssb/api", "2044-05-09",
                              S=FakeS(), out=out.append)
        self.assertTrue(res.startswith("skipped"))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "metadata.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
