"""
The league's MLB clubs and their sub-leagues (AL / NL, or whatever the league calls them), written into
public/data/<LG>/metadata.json under the key "clubs" at pull time.

WHY THIS FILE EXISTS. The app's standings, positional-strength and org pages rank a league's clubs
against each other. For TGS and BLM the app carries hard-coded AL/NL sets (TeamStandingsPage.jsx
LEAGUE_TEAMS). Any other league fell back to "every org carrying 20+ players", which in SSB ranks 50
clubs: the 28 MLB clubs plus 22 foreign (KBO, South African ...) clubs at replacement level. This
module gives every StatsPlus league its own club list from data.

WHERE EACH PART COMES FROM (no rule of OOTP is re-derived here):
  clubs        the distinct Org of the ratings rows whose Lev is 'MLB' (salary_report.mlb_team_ids,
               the same set the salary reports read), kept only when /teams lists the id as a
               top-level team; names from /teams ('City Nickname', statsplus.team_name_map, the
               same strings as the records' ORG).
  sub-leagues  /teams has no sub-league column (ID, Name, Nickname, Parent Team ID only), and no other
               StatsPlus reply we read carries one. OOTP's own league home page does: its standings
               box lists each sub-league ("AMERICAN LEAGUE  STANDINGS") with its clubs. StatsPlus
               serves that page from the same report tree as the team salary reports:
                   <league root>/reports/news/html/leagues/league_<league id>_home.html
               <league id> = the StatsPlus League of the MLB rows (155 in SSB).
               UNVERIFIED LIVE: no StatsPlus copy of this page is saved. The parser was written against
               the page OOTP 27.2 itself wrote into the SSB save (news/html/leagues/league_155_home.html)
               and its preseason prediction report; StatsPlus hosts OOTP's uploaded reports unchanged
               (the salary report pages are that same tree).

LOAD ON STATSPLUS. The page is read only when the split is unknown, the club set changed, or the
in-game season moved since the split was read: about once a season. One request, no token sent
(statsplus._open(token=False, stay_on=<api base>)), through the date-keyed cache. Never fatal: a page
that cannot be read or parsed leaves the clubs without a split (the app shows one table), or keeps the
last split when the club set is unchanged.

metadata.json "clubs" (additive; every other key of the file is kept):
  {"teams": [{"id": "31", "name": "Arizona Diamondbacks", "sub_league": "National League"}, ...],
   "sub_leagues": [{"name": "American League", "abbr": "AL"}, ...],   # [] when the split is unknown
   "league_id": "155", "game_date": "2044-05-09",
   "split_season": "2044", "split_source": "..."}                   # null when the split is unknown
  sub_league is null on every team when the split is unknown. abbr = the initials of the name.

    python tgs-viz/ingest/club_list.py --league SSB --ratings <statsplus_ssb.json> --teams <teams.json.gz>
        [--home <league_155_home.html>] [--source TEXT] [--write]
        offline: build the clubs from saved replies (and a saved home page), print them; --write merges
        them into public/data/<LG>/metadata.json. No request.
"""
import gzip
import html as _html
import json
import os
import re
import sys
import tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

HOME_PATH = "reports/news/html/leagues/league_{league_id}_home.html"

_HEADING = re.compile(r">\s*([A-Z][A-Z0-9 .&'-]*?)\s+(?:PREDICTED\s+)?STANDINGS\b")
_TEAM_LINK = re.compile(r"""<a\s[^>]*href=["'][^"']*\bteam_(\d+)\.html["'][^>]*>([^<]+)</a>""", re.I)


# ---- the clubs -------------------------------------------------------------------------------------------

def mlb_clubs(rows, team_rows):
    """[{"id", "name"}] of the league's MLB clubs, sorted by name. rows = the ratings rows after
    statsplus.enrich_org_lev (Org, Lev); team_rows = the /teams reply."""
    import salary_report as SR
    import statsplus as S
    names = S.team_name_map(team_rows)
    ids = SR.mlb_team_ids(rows, team_rows)
    out = [{"id": i, "name": names.get(i) or i} for i in ids]
    return sorted(out, key=lambda c: (c["name"], c["id"]))


def mlb_league_id(rows):
    """The StatsPlus League id of the MLB rows (the most common one), or None."""
    c = Counter(str(r.get("League")).strip() for r in rows
                if r.get("Lev") == "MLB" and str(r.get("League") or "").strip() not in ("", "0", "None"))
    return c.most_common(1)[0][0] if c else None


# ---- the sub-leagues -------------------------------------------------------------------------------------

def _title(s):
    return " ".join(w.capitalize() for w in s.split())


def abbr_of(name):
    """'American League' -> 'AL'. The initials of the words (a one-word name keeps its first 3 letters)."""
    words = [w for w in re.split(r"[\s-]+", name or "") if w]
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words).upper()


def parse_sub_leagues(page, clubs):
    """Read the sub-league standings boxes of an OOTP league page.

    Returns (names in page order, {club id: sub-league name}). A club is assigned to the standings
    heading above the first link to it whose text is the club's full name (the standings rows; the
    leader boards link with abbreviations). Clubs the page does not list are left out."""
    full = {c["id"]: c["name"] for c in clubs}
    events = [(m.start(), "h", _title(m.group(1))) for m in _HEADING.finditer(page)]
    events += [(m.start(), "t", (m.group(1), _html.unescape(m.group(2)).strip()))
               for m in _TEAM_LINK.finditer(page)]
    events.sort(key=lambda e: e[0])
    order, of, current = [], {}, None
    for _pos, kind, val in events:
        if kind == "h":
            current = val
            continue
        tid, text = val
        if current is None or tid not in full or tid in of or text != full[tid]:
            continue
        of[tid] = current
        if current not in order:
            order.append(current)
    return order, of


def complete_split(clubs, order, of):
    """True when every club has a sub-league and there are at least two of them."""
    return len(order) >= 2 and all(c["id"] in of for c in clubs)


# ---- the document ----------------------------------------------------------------------------------------

def build_doc(clubs, order=None, of=None, *, league_id=None, game_date=None, split_season=None,
              split_source=None):
    """The metadata.json "clubs" value. A split that is not complete is dropped whole."""
    split = bool(order) and of is not None and complete_split(clubs, order, of)
    return {
        "teams": [{"id": c["id"], "name": c["name"], "sub_league": of[c["id"]] if split else None}
                  for c in clubs],
        "sub_leagues": [{"name": n, "abbr": abbr_of(n)} for n in order] if split else [],
        "league_id": league_id,
        "game_date": (str(game_date)[:10] if game_date else None),
        "split_season": split_season if split else None,
        "split_source": split_source if split else None,
    }


def _prev_split(prev, clubs):
    """(order, of, season, source) of the previous doc when it holds a complete split for exactly
    these club ids, else None."""
    if not isinstance(prev, dict) or not prev.get("sub_leagues"):
        return None
    teams = prev.get("teams") or []
    if {str(t.get("id")) for t in teams} != {c["id"] for c in clubs}:
        return None
    order = [s.get("name") for s in prev["sub_leagues"] if s.get("name")]
    of = {str(t["id"]): t.get("sub_league") for t in teams if t.get("sub_league")}
    if not complete_split(clubs, order, of):
        return None
    return order, of, prev.get("split_season"), prev.get("split_source")


# ---- metadata.json ---------------------------------------------------------------------------------------

def read_meta(out_dir):
    """(metadata dict or None, indent). None when the file is missing; raises ValueError when it is not
    a JSON object."""
    import roster_clock as RC
    path = os.path.join(out_dir, "metadata.json")
    if not os.path.exists(path):
        return None, 2
    with open(path, encoding="utf-8") as f:
        text = f.read()
    meta = json.loads(text)
    if not isinstance(meta, dict):
        raise ValueError("metadata.json is not a JSON object")
    return meta, RC._indent_of(text)


def write_clubs(out_dir, league, doc):
    """Merge {"clubs": doc} into out_dir/metadata.json (created when missing). Every other key and the
    file's indent are kept. Returns "written", "unchanged" or a reason starting with "skipped"."""
    try:
        meta, indent = read_meta(out_dir)
    except (OSError, ValueError):
        return "skipped: existing metadata.json is not a readable JSON object"
    if meta is None:
        meta = {"league": league}
    if meta.get("clubs") == doc:
        return "unchanged"
    meta["clubs"] = doc
    path = os.path.join(out_dir, "metadata.json")
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".metadata.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=indent, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return f"skipped: could not write ({type(e).__name__})"
    return "written"


# ---- pull time -------------------------------------------------------------------------------------------

def home_url(api_base, league_id):
    import salary_report as SR
    return f"{SR.report_base(api_base).rstrip('/')}/{HOME_PATH.format(league_id=league_id)}"


def fetch_split(api_base, league_id, clubs, *, S=None, cache=True):
    """(order, of) read from the league home page on StatsPlus. Raises when the page cannot be read or
    holds no complete split (statsplus.StatsPlusRefused: the page is then not cached)."""
    if S is None:
        import statsplus as S
    url = home_url(api_base, league_id)

    def fetch():
        text, _sent = S._open(url, token=False, stay_on=api_base)
        order, of = parse_sub_leagues(text, clubs)
        if not complete_split(clubs, order, of):
            raise S._refused_reply(text, "a league page with the sub-league standings", url, False)
        return text
    page = S._cached(api_base, url, fetch, cache, False)
    return parse_sub_leagues(page, clubs)


def update_clubs(out_dir, league, rows, team_rows, api_base, game_date, *, S=None, fetch=True, out=print):
    """Build the clubs from this pull and merge them into metadata.json. Never raises."""
    try:
        clubs = mlb_clubs(rows, team_rows)
        if len(clubs) < 2:
            out(f"  clubs: not written ({len(clubs)} MLB clubs found)")
            return "skipped: too few clubs"
        lid = mlb_league_id(rows)
        season = str(game_date or "")[:4] or None
        try:
            prev = (read_meta(out_dir)[0] or {}).get("clubs")
        except (OSError, ValueError):
            prev = None
        kept = _prev_split(prev, clubs)
        order = of = src = split_season = None
        how = ""
        if kept and kept[2] == season:
            order, of, split_season, src = kept
            how = "kept (same clubs, same season)"
        elif fetch and lid:
            try:
                order, of = fetch_split(api_base, lid, clubs, S=S)
                split_season, src = season, f"StatsPlus {HOME_PATH.format(league_id=lid)} ({str(game_date)[:10]})"
                how = "read from the league page"
            except Exception as e:
                if kept:
                    order, of, split_season, src = kept
                    how = f"kept from {kept[2]} (league page not read: {type(e).__name__})"
                else:
                    how = f"unknown (league page not read: {type(e).__name__})"
        elif kept:
            order, of, split_season, src = kept
            how = f"kept from {kept[2]}"
        else:
            how = "unknown"
        doc = build_doc(clubs, order, of, league_id=lid, game_date=game_date, split_season=split_season,
                        split_source=src)
        res = write_clubs(out_dir, league, doc)
        subs = ", ".join(f"{s['abbr']} {sum(t['sub_league'] == s['name'] for t in doc['teams'])}"
                         for s in doc["sub_leagues"]) or "no split"
        out(f"  clubs: {len(clubs)} MLB clubs ({subs}; sub-leagues {how}) -> metadata.json: {res}")
        return res
    except Exception as e:
        out(f"  note: clubs not written to metadata.json ({type(e).__name__})")
        return f"skipped: {type(e).__name__}"


# ---- offline CLI -----------------------------------------------------------------------------------------

def _load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    return doc["data"] if isinstance(doc, dict) and "data" in doc else doc


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", required=True)
    ap.add_argument("--ratings", required=True, help="saved raw ratings rows (statsplus_<slug>.json)")
    ap.add_argument("--teams", required=True, help="saved /teams reply (.json or .json.gz)")
    ap.add_argument("--home", help="a saved OOTP league page with the sub-league standings")
    ap.add_argument("--source", help="what --home is, for split_source")
    ap.add_argument("--game-date", help="default: the /teams reply's game_date")
    ap.add_argument("--out-dir", help="default: tgs-viz/public/data/<league>")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    import statsplus as S
    rows = S.drop_foreign(_load(a.ratings), league=a.league)
    team_rows = _load(a.teams)
    S.enrich_org_lev(rows, S.team_name_map(team_rows), league=a.league)
    gd = a.game_date
    if not gd:
        op = gzip.open if a.teams.endswith(".gz") else open
        with op(a.teams, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        gd = raw.get("game_date") if isinstance(raw, dict) else None
    clubs = mlb_clubs(rows, team_rows)
    order = of = None
    if a.home:
        with open(a.home, encoding="utf-8", errors="replace") as f:
            order, of = parse_sub_leagues(f.read(), clubs)
    doc = build_doc(clubs, order, of, league_id=mlb_league_id(rows), game_date=gd,
                    split_season=(gd or "")[:4] or None, split_source=a.source or (os.path.basename(a.home)
                                                                                    if a.home else None))
    for s in doc["sub_leagues"] or [{"name": None, "abbr": "all"}]:
        members = [t["name"] for t in doc["teams"] if t["sub_league"] == s["name"]]
        print(f"{s['abbr']} ({s['name'] or 'no split'}): {len(members)}")
        for m in members:
            print(f"    {m}")
    missing = [c["name"] for c in clubs if of is not None and c["id"] not in of]
    if missing:
        print(f"not on the page: {', '.join(missing)} -> split dropped")
    if a.write:
        out_dir = a.out_dir or os.path.join(os.path.dirname(HERE), "public", "data", a.league)
        print(f"metadata.json: {write_clubs(out_dir, a.league, doc)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
