"""
statsplus_history.py - pull PAST rating snapshots from StatsPlus into the
ratings archive.

StatsPlus /ratings/ takes ?date=YYYY-MM-DD and returns the ratings as they
were on that game date (the StatsPlus author announced it; it is not in the
docs). It is on for every league. Older game years are thinned to save space:
their snapshots are mostly on Jan 1 and Jul 1 (the StatsPlus author). This
tool asks for one snapshot every 6 game months, anchored on Jan 1 (so exactly
those dates), and stores each one in backtest/ratings_history.db as an "asof"
pull:

    source     = "asof"
    game_date  = real_date = the game date asked for (the DEV dump rule;
                 TGS game years 2038-2045 and BLM 2051-2058 never collide
                 with the real 2026 dates of the live pulls)
    real_ts    = the real time it was fetched
    raw file   = ingest/.cache/asof/<slug>/<game date>.json, saved only after
                 the date passed every check (its own folder: the
                 ingest/.cache/history folder and ingest/.cache/statsplus_<slug>.json
                 are never touched, so no live-pull reader sees a snapshot)
    vintage    = backtest/vintages/<LG>/<game date>_p<id>.csv.gz (+ _pulls.csv)

Every archive reader sorts by game date (backtest/pull_order.py). The app
values keep coming from the newest LIVE pull; a snapshot never becomes "the
latest pull".

LOGIN. The league's saved StatsPlus token (statsplus_token.py; the token file
StatsPlus Tokens.txt holds one per league). statsplus.py adds it on its own to
every request: /date, /players, /tokencheck and the ratings jobs. Without a saved
token, the ratings jobs use the browser cookie pair from the STATSPLUS_COOKIE
environment variable (Get StatsPlus History.bat asks for it only then); with
both, the token goes first and the cookie is the fallback, and once StatsPlus
refuses the token, the jobs use the cookie only for the rest of the run. A
refused token with no cookie stops the run (exit 3). Neither is ever
printed or saved, and both go only to statsplus.net or a subdomain of it (for
example api.statsplus.net): the slug must be a plain slug, and the poll
address and every redirect must pass statsplus.site_url (statsplus refuses
another host, an '@' in the host part or a backslash before anything is sent).

Order of the jobs:
  1. today's view: what every past date is compared with. It must be TODAY's
     ratings: that is what StatsPlus sends for a date it has no snapshot of.
     - The newest live pull's game date equals today's game date (/date) and
       a token is saved: no ratings job. Today's view = that live pull, and one
       /tokencheck call proves the token (--force-overlap runs the job anyway;
       when the check does not answer, the job runs).
     - The newest live pull's game date equals today's game date, no token:
       the overlap job, the ratings of that game date. It proves the login,
       checks the league (player ID + Name against that live pull), and
       becomes today's view when it passes its own checks: its ages do not
       fit another day, and its ratings differ from that live pull on under 2
       percent of shared players. A reply that fails them, or a started job
       that sends no ratings (StatsPlus has no snapshot of that date), is not
       used: today's view = the newest live pull (also today's), and the run
       goes on.
     - Else (the league played on since the newest live pull, today's game
       date is unknown, or there is no live pull): a job WITHOUT a date. Its
       reply is today's ratings and becomes today's view; it proves the login
       and checks the league the same way, and it is never stored.
  2. without --from: walk back from the league's first known history date
     (TGS 2038-01-01, BLM 2051-01-01) one step at a time; stop after 2 dates
     in a row without new ratings (no snapshot, today's ratings, a repeat or a
     refusal), or at PROBE_YEARS before it. Both leagues are set to 0: no walk
     back. The tool starts asking at the settings date: TGS 2038-01-01 and BLM
     2051-01-01 (about the last 8 seasons; older game versions developed
     players differently). StatsPlus's TGS history begins 2040-08-07: asked
     for an earlier date, StatsPlus says so ("The earliest date with ratings
     history is ..."), and the tool skips every earlier step date and asks for
     that date itself (from_earliest)
  3. every step date from the earliest date with data, oldest first
A date already archived as an asof pull is skipped, and so is a date in the
no-snapshot memory (below) unless --retry-missing. A step date less than 31
days before the overlap date, or on it or after it, is dropped (its ratings are
still close to today's, so the "today's ratings" check below could refuse it
falsely). A step date within 3 days of today's game date (/date), or after it,
is dropped too. With --dates or --to, such dates are refused the same way.

A past date is stored only when all of these hold:
  - the reply has ratings (not empty, not an error page)
  - the RATINGS are not today's. Decided by the ratings (core batting,
    pitching, fielding and potential columns, ratings_db.ALL_COLS), never by
    the ages alone: StatsPlus may rebuild past ratings but fill Age (and the
    team fields) from today's player table. A reply is today's ratings when
    its content hash equals today's view or the newest live pull, or when
    under 2 percent of the players it shares with today's view have any
    rating change, or when its ages fit today AND under 10 percent of shared
    players changed AND the date asked for is more than 150 days before
    today's view.
    Measured on the real archive: live pulls 34 or more game days apart differ
    on 17.7 percent (BLM, 34 days) to 98 percent (TGS, 275 days) of shared
    players; even 11 days apart, 3.6 percent. Such a date is refused as "no
    snapshot for this date (StatsPlus sent today's ratings)" and the run goes
    on. The run STOPS (exit 7) only when 3 step dates in a row come back as
    today's ratings AND no past date was accepted this run: then StatsPlus
    ignores the date. A date already in the no-snapshot memory (asked again
    with --retry-missing) does not count, and any other result resets the
    count, so a real gap of a few snapshots never stops the run. Walk-back
    dates with today's ratings count as dates without new ratings and never
    stop the run.
  - the ages. The birth-date fit (growth_lenses.fit_game_date, /players birth
    dates: the day most players agree on) must land within 3 days of the
    date asked for, with at least 10 percent of the players agreeing (TGS
    reuses player IDs, so on old dates many IDs carry another birth date).
    Ages that fit today or the overlap date (the ratings already passed the
    check above): Age is REBUILT from the /players birth dates at the date
    asked for, the date is accepted, and the report and the raw file
    (AgeSource field on every row) say "ages rebuilt from birth dates". A
    player whose birth date is unknown (none on /players, or his ID now
    belongs to a player with another name) keeps a null age. When the
    rebuilt ages put more than 2 percent of the players under 14 on the date
    asked for, the reply is a roster from a later date (in every real live
    pull the youngest player is 14): refused and remembered. Ages that fit
    another day, or no clear day: the date is refused (not stored), the run
    goes on.
  - its ratings are not a repeat: the content hash differs from every pull of
    the league in the archive (asof and live) and from every date accepted
    this run. A repeat is refused, the run goes on. One exception (see KNOWN
    LIMIT): a step date whose ratings repeat the date accepted before it this
    run, both with rebuilt ages.
  - the league check: on the overlap date, player ID + Name against the newest
    live pull (at least half must match, else exit 6). A past date is checked
    loosely against the nearest StatsPlus pull (asof, live or history) or date
    accepted this run, within 1 game year (at least 25 percent must match, else
    exit 6): old TGS dates share many IDs with other players, so the strict
    check would stop them falsely. Names are compared without accents and
    case. A "bak" pull is never the reference: bak pulls share the player IDs,
    but they come from another source (the sheet backups) with names in
    another case, so they were left out as references.
The overlap snapshot is stored at the end of the run when it passed its checks,
is not a repeat, and the run did not stop.

NO-SNAPSHOT MEMORY. ingest/.cache/asof/<slug>/_no_snapshot.json (in --raw-dir)
keeps, per game date, why StatsPlus had no snapshot for it and the real date
it was asked: no ratings in the reply (an empty snapshot or an error text),
today's ratings, ages that fit another day or no clear day, or a repeat of
another date whose ages do not fit the date asked for. Later runs skip these
dates without a job; --retry-missing asks them again (a date accepted then
leaves the memory). A job that failed for another reason (network, too slow,
too soon, an HTML page instead of the ratings) is not remembered. When the
run stops with exit 7, the today's ratings dates first added that run are not
remembered either. Birth dates come from /players through the date-keyed
cache (statsplus cache=True), so a second run on the same game date does not
download them again.

KNOWN LIMIT. When StatsPlus fills Age from today, the ages can not tell which
date a snapshot belongs to. Steps run oldest first, so when a step date's
ratings repeat the date accepted just before it this run (both with rebuilt
ages), StatsPlus either answered the earlier date with the next LATER
snapshot (then the earlier date holds this date's snapshot) or answered this
date with the nearest EARLIER one (then this date has none). One extra job
for the day before the earlier date decides it: a missing day answered with
the later snapshot repeats the same ratings. Later: the earlier date's pull
is removed and remembered, and this date is stored. Earlier, or no answer:
this date is refused and remembered (the report lists an undecided pair as
CHECK). The extra job runs at most once per run; its answer holds for the
run. (A later snapshot is often refused before that already: its rebuilt
ages put the players who joined later under 14.) Still open: a snapshot of
an odd EARLIER date (not a step date) sent for a missing date is stored
under the date asked for; the end-of-run report says, per stored date,
whether its ages came from the snapshot or were rebuilt from birth dates.

After the run (with --write): the scale-event guard (ratings_db.pair_guard)
against each snapshot's neighbours in game order, and the gap between
neighbours (a gap over 1 game year breaks the age-step rules).

CLI:
  python tgs-viz/ingest/statsplus_history.py --league TGS --write
  --slug tgs|blm        StatsPlus slug: letters, digits and dashes only
  --from YYYY-MM-DD     first game date (default: walk back, see above)
  --to YYYY-MM-DD       last step game date (default: the newest live pull's game
                        date; step dates less than 31 days before it are dropped)
  --step 6m             months between dates (1m .. 12m), anchored on Jan 1
  --dates D1,D2         exact game dates instead of the steps (no walk back); a
                        date less than 31 days before the overlap date, or within
                        3 days of today's game date, is refused
  --write               store the snapshots in the archive
  --dry-run             print the plan only: nothing is fetched or written
  --refetch             fetch again even when the raw file of a date is saved
  --retry-missing       ask again for the dates in the no-snapshot memory
  --force-overlap       run the overlap job even when the newest live pull is today's
  --drop D1,D2          remove these asof snapshots of the league (DB rows,
                        pulls row, vintage file, raw file, game-date entry);
                        no login needed
  --drop-all-asof       remove every asof snapshot of the league
Tests only (never with a real login): --base-url http://127.0.0.1:PORT/tgs
(the mock server; the cookie then comes from STATSPLUS_TEST_COOKIE and the
token from STATSPLUS_TEST_TOKEN_<SLUG>), --raw-dir, --pause and --poll below
the 20 s / 15 s floors.

Exit codes: 0 done, 1 bad arguments, 2 no login (no token saved for the league
and no cookie given), 3 StatsPlus refused the login (the token expired or is
unknown, or the browser is not signed into this league; dates stored before
the stop stay stored and the report lists them), 6 wrong league, 7 StatsPlus
ignores the date (3 step dates in a row came back as today's ratings and no
past date was accepted), 8 StatsPlus pointed the job at another site (the
login was not sent), 9 StatsPlus says past date ratings are not enabled for
this league, 10 the check job for today's view failed for another reason
(today's ratings job sent no ratings, or StatsPlus was not reachable, too
slow, or too soon again and again).
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/ingest
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
BT = os.path.join(VIZ, "backtest")
sys.path.insert(0, HERE)
sys.path.insert(0, BT)
import statsplus as S          # noqa: E402
import pull_order as PO        # noqa: E402
sys.path.insert(0, os.path.join(VIZ, "tools"))
import settings as ST          # noqa: E402

SLUGS = ST.slug_map()
SITE_HOST = "statsplus.net"
_HIST = ST.history_settings()  # settings leagues.<LG>.history
# first game date each league's player pages show rating history for
FIRST_KNOWN = {lg: h["first_date"] for lg, h in _HIST.items()}
# walk back at most this many years before it. TGS: none (user, 2026-09-30:
# "just like the past 8 seasons because older versions of the game likely had
# different ratings"), so the TGS steps start at the settings date 2038-01-01
# (2038-2045 = 8 seasons). StatsPlus's TGS history begins 2040-08-07: it says
# so when asked for an earlier date, and the run skips the earlier steps
# (from_earliest). BLM: none either (same reason; older snapshots would only
# feed displays and could contaminate any measurement), so BLM starts at
# 2051-01-01.
PROBE_YEARS = {lg: h["probe_years"] for lg, h in _HIST.items()}
MIN_PAUSE = 20.0                # seconds between jobs (be gentle with the server)
RATE_GAP = 0.0                  # seconds between job STARTS. No fixed wait (user, 2026-09-30):
                                # the "5 minutes per team" rule was only read secondhand; when
                                # StatsPlus wants a pause it says "Request too soon, wait N
                                # seconds" and the job waits exactly that (TOO_SOON_TRIES)
TOO_SOON_TRIES = 3              # jobs refused as too soon (or HTTP 429): wait the time given, ask again
POLL = 15.0                     # seconds between polls of one job
AGE_WINDOW = 3                  # days: birth-date fit vs the date asked for
PAST_MIN_SHARE = 0.10           # share of players whose ages fit the date asked for (the fit
                                # must also land there: no other day fits better). Low on
                                # purpose: TGS reuses player IDs, so on old dates many IDs
                                # belong to a player with another birth date
TODAY_MIN_SHARE = 0.50          # share that makes a fit on today / the overlap date clear
STRICT_ID_SHARE = 0.50          # overlap date: ID + Name matches vs the newest live pull
LOOSE_ID_SHARE = 0.25           # past date: ID + Name matches vs the nearest snapshot
LOOSE_ID_DAYS = 366             # ... only when that snapshot is at most this far away
NAME_SOURCES = ("asof", "live", "history")   # pulls in the StatsPlus schema. A "bak" pull shares the
                                             # player IDs, but it comes from another source (the sheet
                                             # backups) with names in another case: never a reference
IGNORED_SHARE = 0.02            # today's ratings: under this share of the players shared with
                                # today's view have any rating change (real archive: 34+ game days
                                # apart = 17.7% to 98% changed; 11 days apart = 3.6%)
TODAY_LIKE_SHARE = 0.10         # today's ratings too: ages fit today and under this share changed ...
TODAY_LIKE_DAYS = 150           # ... while the date asked for is more than this many days before today's view
TODAY_STOP_RUN = 3              # step dates in a row with today's ratings, and no date accepted this
                                # run: StatsPlus ignores the date (exit 7)
YOUNG_AGE = 14                  # a reply whose rebuilt ages put more than YOUNG_SHARE of the players
YOUNG_SHARE = 0.02              # under this age on the date asked for is a later roster, not that
                                # date's (real live pulls, TGS and BLM: the youngest player is 14)
MIN_SHARED = 200                # the share tests need at least this many shared players
NEAR_OVERLAP_DAYS = 30          # step dates this close before the overlap date (or later) are dropped
NEAR_TODAY_DAYS = 3             # step dates this close to today's game date (or later) are dropped
AGE_FIELD = "AgeSource"         # raw-file field: where the Age of each row came from
AGE_STATSPLUS = "StatsPlus"
AGE_REBUILT = "rebuilt from birth dates"
DEFAULT_RAW = os.path.join(HERE, ".cache", "asof")
NO_SNAPSHOT_FILE = "_no_snapshot.json"
LOGIN_KINDS = ("token_invalid", "token_expired", "login_required")
NO_TOKEN = " "                  # statsplus.fetch_ratings: a blank token string sends no token (cookie only)
EXIT = {"login": 3, "wrong league": 6, "date ignored": 7, "off site": 8, "not enabled": 9,
        "overlap failed": 10}
# job outcomes that stop the run, and the words for the others
STOP_HOW = {"not signed in": "login", "off site": "off site", "not enabled": "not enabled",
            "daily limit": "daily limit"}
HOW_WORDS = {"no snapshot": "StatsPlus sent no ratings",
             "error page": "StatsPlus sent a web page instead of the ratings",
             "network": "StatsPlus could not be reached (network)",
             "timed out": "the StatsPlus job did not finish in time",
             "too soon": "StatsPlus kept saying the request came too soon"}


def log(msg=""):
    print(msg, flush=True)


def iso(s):
    try:
        return datetime.date.fromisoformat(str(s).strip()[:10])
    except (TypeError, ValueError):
        return None


def add_months(d, n):
    m = d.month - 1 + n
    return datetime.date(d.year + m // 12, m % 12 + 1, 1)


EARLIEST_RE = re.compile(r"earliest date with ratings history is (\d{4}-\d{2}-\d{2})", re.I)


def earliest_said(text):
    """The game date in StatsPlus's 'The earliest date with ratings history is
    YYYY-MM-DD' reply (asked for a date before it), or None."""
    m = EARLIEST_RE.search(str(text or ""))
    return iso(m.group(1)) if m else None


def from_earliest(steps, first, too_close):
    """(steps, n dropped): the step dates on or after StatsPlus's first
    snapshot date `first`, with `first` itself added (it is a real snapshot)."""
    keep = [d for d in steps if d >= first]
    dropped = len(steps) - len(keep)
    if first not in keep and not too_close(first):
        keep = sorted(keep + [first])
    return keep, dropped


def step_dates(start, end, months):
    """Step dates from Jan 1 of start's year, every `months` months, that lie in
    [start, end]."""
    d = datetime.date(start.year, 1, 1)
    out = []
    while d <= end:
        if d >= start:
            out.append(d)
        d = add_months(d, months)
    return out


def repo_rel(path):
    """Repo-relative path when the file is inside the repo, else absolute."""
    ap = os.path.abspath(path)
    try:
        rel = os.path.relpath(ap, REPO)
    except ValueError:
        return ap
    return ap if rel.startswith("..") else rel


def repo_abs(rel):
    p = str(rel).replace("\\", os.sep)
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def inside(path, folder):
    """True when path lies inside folder."""
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:
        return False


def login_refusal(e):
    """True when a StatsPlusRefused (or a statsplus.RatingsFailure) means the
    login itself was refused: the token expired or is unknown, a login is
    needed, or HTTP 401/403."""
    kind = getattr(e, "kind", None)
    return kind in LOGIN_KINDS or (kind == "blocked" and getattr(e, "status", None) in (401, 403))


def failure_how(fail):
    """The Job.fetch outcome for a failed ratings job (statsplus.RatingsFailure)."""
    if fail is None:
        return "no snapshot"
    if fail.kind == "off_site":
        return "off site"
    if fail.kind == "not_enabled":
        return "not enabled"
    if login_refusal(fail) or fail.kind == "no_login":
        return "not signed in"
    if fail.kind == "daily_limit":
        return "daily limit"
    if fail.kind in ("too_soon", "blocked"):          # blocked here = HTTP 429
        return "too soon"
    if fail.kind == "network":
        return "network"
    if fail.kind == "timed_out":
        return "timed out"
    if getattr(fail, "html", False):
        return "error page"                           # not_data from an HTML page: not remembered
    return "no snapshot"                              # not_data: an empty snapshot, an error text


# ---------------------------------------------------------------- archive state
def archive_state(league):
    """What the archive already holds for the league (read only)."""
    import sqlite3
    st = {"live": [], "asof": {}, "latest": None, "game": {}, "hashes": {}, "by_game": {}, "live_raw": []}
    if not os.path.exists(PO.DB_PATH):
        return st
    conn = sqlite3.connect(f"file:{PO.DB_PATH}?mode=ro", uri=True)
    try:
        rows, game = PO.ordered(conn, league, log)
        st["game"] = game
        st["live"] = [r for r in rows if r[3] != PO.ASOF]
        st["asof"] = {game.get(r[0]) or r[1]: r[0] for r in rows if r[3] == PO.ASOF}
        meta = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            "SELECT pull_id, source_files, content_hash, source FROM pulls WHERE league=?", (league,))}
        for r in rows:
            files, h, src = meta.get(r[0], ("[]", None, r[3]))
            if h:
                st["hashes"].setdefault(h, f"pull {r[0]} ({src}, game date {game.get(r[0]) or '?'})")
            g = iso(game.get(r[0]))
            if g and src in NAME_SOURCES:
                st["by_game"].setdefault(g, r[0])
        latest = PO.latest_live(st["live"]) if st["live"] else None
        if latest:
            files, h, _src = meta[latest[0]]
            st["latest"] = {"id": latest[0], "real": latest[1], "game": game.get(latest[0]),
                            "files": json.loads(files or "[]"), "hash": h}
        # raw files of the live pulls (the mover check), oldest first
        for r in st["live"]:
            for rel in json.loads(meta.get(r[0], ("[]",))[0] or "[]"):
                p = repo_abs(rel)
                if p.endswith(".json") and os.path.isfile(p) and "statsplus_" in os.path.basename(p):
                    st["live_raw"].append((r[0], game.get(r[0]), p))
    finally:
        conn.close()
    return st


def load_names(pull_id):
    """{player_id: name} of one archived pull (read only)."""
    import sqlite3
    conn = sqlite3.connect(f"file:{PO.DB_PATH}?mode=ro", uri=True)
    try:
        return {str(a): norm_name(b) for a, b in
                conn.execute("SELECT player_id, name FROM ratings WHERE pull_id=?", (pull_id,))}
    finally:
        conn.close()


def norm_name(s):
    """Name for the ID + Name check: accents dropped, case folded, spaces collapsed."""
    t = unicodedata.normalize("NFKD", str(s or ""))
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return " ".join(t.casefold().split())


def load_raw(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def replace_file(tmp, path, tries=10, pause=0.3):
    """os.replace with retries: on Windows a virus scanner or the indexer can
    hold a fresh file open for a moment (WinError 32). Raises the last
    error after `tries` attempts."""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(pause)


# ---------------------------------------------------------------- no-snapshot memory
class NoSnapshot:
    """Game dates StatsPlus had no snapshot for: {date: {"kind", "reason",
    "asked"}} in <raw dir>/<slug>/_no_snapshot.json. kind = empty | today |
    refused; asked = the real date it was asked. Written after every change
    (a temporary file, then a rename)."""

    def __init__(self, path):
        self.path = path
        self.data = {}
        self.added = {}                  # this run: date -> kind
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                self.data = {k: v for k, v in d.items() if iso(k) and isinstance(v, dict)}
        except (OSError, ValueError):
            pass
        self.loaded = set(self.data)     # the dates remembered before this run

    def _write(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dict(sorted(self.data.items())), fh, indent=1)
            replace_file(tmp, self.path)
        except OSError as e:
            # the run goes on; the memory is saved with the next change
            log(f"  note: the no-snapshot memory was not saved this time ({type(e).__name__}); "
                f"it is saved again with the next change")

    def add(self, day, kind, reason):
        key = day.isoformat()
        self.data[key] = {"kind": kind, "reason": reason, "asked": datetime.date.today().isoformat()}
        self.added[key] = kind
        self._write()

    def remove(self, day):
        if self.data.pop(day.isoformat(), None) is not None:
            self._write()

    def forget_added(self, kind):
        """Remove the entries of this kind first added this run (an entry that
        was in the memory before the run stays). Returns their dates."""
        gone = sorted(k for k, v in self.added.items() if v == kind and k in self.data and k not in self.loaded)
        for k in gone:
            self.data.pop(k, None)
            self.added.pop(k, None)
        if gone:
            self._write()
        return gone


# ---------------------------------------------------------------- birth dates
def dob_map(league, base):
    """{player_id: date} from the /players list (birth dates never change),
    through the date-keyed cache, plus the lens cache copy (read only)."""
    out = {}
    cache = os.path.join(BT, ".lens_cache", f"{league}_dob.json")
    try:
        with open(cache, encoding="utf-8") as fh:
            for k, v in json.load(fh).items():
                d = iso(v)
                if d:
                    out[str(k)] = d
    except (OSError, ValueError):
        pass
    try:
        for r in S.fetch_players(base, cache=True):
            pid, d = str(r.get("ID") or "").strip(), iso(r.get("date_of_birth"))
            if pid and d:
                out[pid] = d
    except S.StatsPlusRefused as e:
        log(f"  note: birth dates not read from /players. {e.user_message(league)} "
            f"{'Using the cached copy.' if out else 'None cached.'}")
    except Exception as e:
        log(f"  note: birth dates not read from /players ({type(e).__name__}); "
            f"{'using the cached copy' if out else 'none cached'}")
    return out


def check_ages(rows, dob, asked, today_ref):
    """Birth-date fit of the snapshot ages. Returns a dict with the verdict:
      'past'        the ages fit the date asked for
      'today'       the ages clearly fit today_ref or later, and the date asked
                    for is well before it: StatsPlus sent today's ages
      'other'       the ages fit another day (not the one asked for)
      'unclear'     no clear day
      'not checked' too few players with a birth date
    today_ref = the earliest of today's game date and the overlap date (None =
    not known)."""
    import growth_lenses as GL
    d, n, share, width = GL.fit_game_date(((r.get("ID"), r.get("Age")) for r in rows), dob)
    out = {"fit": d.isoformat() if d else None, "n": n, "share": round(share, 3), "width": width}
    win = datetime.timedelta(days=AGE_WINDOW)
    if d is None or n < GL.DOB_MIN_PLAYERS:
        out["verdict"] = "not checked"
    elif abs((d - asked).days) <= AGE_WINDOW and share >= PAST_MIN_SHARE:
        out["verdict"] = "past"
    elif (today_ref is not None and d >= today_ref - win and asked < today_ref - win
          and share >= TODAY_MIN_SHARE):
        out["verdict"] = "today"
    elif share >= PAST_MIN_SHARE:
        out["verdict"] = "other"
    else:
        out["verdict"] = "unclear"
    return out


def rating_diff(pmap, ref_map):
    """(shared, changed): players in both maps, and of them the players with any
    rating change (ratings_db.ALL_COLS: core batting, pitching, fielding and
    potential columns; Age, team and name are not compared)."""
    import ratings_db as RDB
    shared = changed = 0
    for pid, rec in pmap.items():
        ref = ref_map.get(pid)
        if ref is None:
            continue
        shared += 1
        changed += int(any(rec.get(c) != ref.get(c) for c in RDB.ALL_COLS))
    return shared, changed


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def rebuild_ages(rows, dob, day, today_names):
    """Rows with Age rebuilt from the birth dates at `day`, and AgeSource set.
    A player whose birth date is unknown keeps a null age: no birth date on
    /players, or his ID now belongs to a player with another name (TGS reuses
    IDs). Returns (rows, with age, null age)."""
    out, n_ok, n_null = [], 0, 0
    for r0 in rows:
        r = dict(r0)
        pid = str(r.get("ID") or "").strip()
        b = dob.get(pid)
        now = (today_names or {}).get(pid)
        if b is not None and (now is None or now == norm_name(r.get("Name"))):
            r["Age"] = str(day.year - b.year - ((day.month, day.day) < (b.month, b.day)))
            n_ok += 1
        else:
            r["Age"] = ""
            n_null += 1
        r[AGE_FIELD] = AGE_REBUILT
        out.append(r)
    return out, n_ok, n_null


AGE_WORDS = {"past": "ages are from that day",
             "today": "ages are TODAY's, not from that day",
             "other": "ages are from ANOTHER day, not the one asked for",
             "unclear": "ages fit no clear day",
             "not checked": "not checked (too few birth dates)"}


# ---------------------------------------------------------------- checks
def identity_check(names, ref_names):
    """(joined, same): players by ID in both, of them with the same Name."""
    if not ref_names:
        return 0, 0
    joined = same = 0
    for pid, nm in names.items():
        pn = ref_names.get(pid)
        if pn is None:
            continue
        joined += 1
        same += int(pn == nm)
    return joined, same


OVERLAP_FIELDS = ("Age", "League", "Team", "Org", "LgLvl")


def overlap_compare(rows, live_rows):
    """Row-by-row comparison of a snapshot with a live pull's raw file."""
    live = {str(r.get("ID")): r for r in live_rows}
    rating_cols = [k for k in (live_rows[0].keys() if live_rows else [])
                   if k not in ("ID", "Name", "Pos", "Bats", "Throws", "Height") + OVERLAP_FIELDS]
    shared = [r for r in rows if str(r.get("ID")) in live]
    out = {"snapshot_rows": len(rows), "live_rows": len(live_rows), "shared": len(shared)}
    same_all = 0
    for r in shared:
        lr = live[str(r.get("ID"))]
        same_all += int(all(str(r.get(c)) == str(lr.get(c)) for c in rating_cols if c in r))
    out["ratings_identical_rows"] = same_all
    for f in OVERLAP_FIELDS:
        out[f] = sum(1 for r in shared if str(r.get(f)) == str(live[str(r.get("ID"))].get(f)))
    return out


def movers_between(old_rows, new_rows):
    """{player_id: (old org, new org)} for players whose Org changed between two
    live pulls (both orgs set)."""
    old = {str(r.get("ID")): str(r.get("Org") or "").strip() for r in old_rows}
    out = {}
    for r in new_rows:
        pid = str(r.get("ID"))
        a, b = old.get(pid), str(r.get("Org") or "").strip()
        if a and b and a not in ("0",) and b not in ("0",) and a != b:
            out[pid] = (a, b)
    return out


# ---------------------------------------------------------------- one job
class Job:
    def __init__(self, args, league, slug, base, cookie):
        self.args, self.league, self.slug, self.base, self.cookie = args, league, slug, base, cookie
        self.last_job_end = None
        self.last_job_start = None
        self.messages = []
        self.failure = None
        self.token_off = False           # True: the saved token was refused, the jobs use the cookie only

    def drop_token(self, why):
        """Use the browser cookie only from now on (the saved token was refused)."""
        if not self.token_off:
            self.token_off = True
            log(f"    StatsPlus refused the saved {self.league} token ({why}); the jobs use the browser "
                f"cookies from now on")

    def _log(self, m):
        self.messages.append(m)
        log("    " + m)

    def raw_path(self, day):
        return os.path.join(self.args.raw_dir, self.slug, f"{day.isoformat()}.json")

    def save(self, day, rows):
        """Save the raw rows of an ACCEPTED date. Returns the path, or None when
        the file could not be written (the date is then not stored this run)."""
        path = self.raw_path(day)
        tmp = path + ".tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(rows, fh)
            replace_file(tmp, path)
        except OSError as e:
            log(f"    the raw file of {day} could not be written ({type(e).__name__}, "
                f"{getattr(e, 'winerror', None) or e.errno})")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None
        return path

    def forget(self, day):
        """Remove a saved raw file that failed the checks (an older build saved
        raw files before checking them)."""
        path = self.raw_path(day)
        if os.path.isfile(path):
            os.remove(path)
            log(f"    removed its saved raw file {repo_rel(path)} (it failed the checks)")

    def fetch(self, day, force=False, undated=False):
        """(rows or None, how): how = 'saved file' | 'fetched' | 'no snapshot' |
        'not signed in' | 'off site' | 'not enabled' | 'too soon' | 'network' |
        'timed out'. After a failed job, self.failure says why (a
        statsplus.RatingsFailure). Nothing is saved here. force = run the job
        even when the raw file is saved (the overlap job). undated = a job
        without a date: today's ratings (day is only the label)."""
        self.failure = None
        path = self.raw_path(day)
        if not undated and os.path.isfile(path) and not (self.args.refetch or force):
            return load_raw(path), "saved file"
        attempt = 0
        while True:
            waits = []
            if self.last_job_end is not None:
                waits.append(self.args.pause - (time.time() - self.last_job_end))
            if self.last_job_start is not None:
                waits.append(self.args.rate_gap - (time.time() - self.last_job_start))
            wait = max(waits, default=0)
            if wait > 0:
                log(f"    waiting {wait:.0f} s before the next job (a short pause between jobs; StatsPlus "
                    f"allows one past-date request every 15 minutes and 5 a day, and the tool waits "
                    f"for that only when StatsPlus says so)")
                time.sleep(wait)
            self.messages = []
            t0 = time.time()
            self.last_job_start = t0
            try:
                rows, method = S.fetch_ratings(self.base, cookie=self.cookie,
                                               token=NO_TOKEN if self.token_off else None,
                                               poll_interval=self.args.poll, max_polls=40, on_log=self._log,
                                               date=None if undated else day.isoformat(),
                                               max_unrecognized=None if undated else 2)
            finally:
                self.last_job_end = time.time()
            log(f"    job took {time.time() - t0:.0f} s")
            if rows:
                if method == "cookie" and not self.token_off and S.has_token(self.base):
                    self.drop_token("the cookie worked instead")
                return rows, "fetched"
            self.failure = f = S.ratings_failure()
            # statsplus reports the token try's refusal even when it went on to
            # the cookie: ask once more with the cookie only, so the reason is the cookie's
            if f is not None and f.method == "token" and self.cookie and not self.token_off and login_refusal(f):
                self.drop_token(f.kind)
                continue
            # StatsPlus allows one past-date request every 15 minutes and 5 a day.
            # A request too soon is refused with the wait to use (HTTP 429 the
            # same): wait that long and ask again. The daily cap is not waited out
            # (failure_how "daily limit": the run stops cleanly).
            if f is None or attempt >= TOO_SOON_TRIES or failure_how(f) != "too soon":
                break
            attempt += 1
            secs = (f.wait if f.wait is not None else 60) + 5
            log(f"    StatsPlus said the request came too soon; waiting {secs} s, then asking again")
            time.sleep(secs)
        return None, failure_how(self.failure)


# ---------------------------------------------------------------- drop
def drop_asof(league, dates, drop_all, raw_dirs):
    """Remove asof snapshots of one league: rating rows, pulls row, vintage file
    (+ its .waa_cache files), raw file, game-date entry; then rewrite the
    league's _pulls.csv. Live pulls are never removed. Returns the number removed."""
    import ratings_db as RDB
    if not os.path.exists(PO.DB_PATH):
        log(f"no archive at {PO.DB_PATH}: nothing to remove")
        return 0
    conn = RDB.connect(PO.DB_PATH)
    removed = []
    try:
        rows = list(conn.execute(
            "SELECT pull_id, real_date, game_date, source, source_files FROM pulls WHERE league=?", (league,)))
        if drop_all:
            targets = [r for r in rows if r[3] == PO.ASOF]
            if not targets:
                log(f"{league}: no asof snapshots in the archive; nothing removed")
        else:
            targets = []
            for d in dates:
                key = d.isoformat()
                hit = [r for r in rows if key in (str(r[2] or "")[:10], str(r[1])[:10])]
                asof = [r for r in hit if r[3] == PO.ASOF]
                if asof:
                    targets += asof
                elif hit:
                    log(f"{league} {key}: pull {hit[0][0]} is a {hit[0][3]} pull, not an asof snapshot; "
                        f"--drop removes only asof snapshots. Nothing removed for {key}.")
                else:
                    log(f"{league} {key}: no asof snapshot on that game date; nothing removed for {key}")
        for pid, real_date, game_date, _src, files in targets:
            n = conn.execute("SELECT COUNT(*) FROM ratings WHERE pull_id=?", (pid,)).fetchone()[0]
            conn.execute("DELETE FROM ratings WHERE pull_id=?", (pid,))
            conn.execute("DELETE FROM pulls WHERE pull_id=?", (pid,))
            conn.commit()
            gone = []
            vdir = os.path.join(PO.VINTAGES_DIR, league)
            vint = os.path.join(vdir, f"{real_date}_p{pid}.csv.gz")
            for f in [vint] + glob.glob(os.path.join(vdir, ".waa_cache", f"{real_date}_p{pid}.csv.gz.*")):
                if os.path.isfile(f):
                    os.remove(f)
                    gone.append(os.path.basename(f))
            for rel in json.loads(files or "[]"):
                p = repo_abs(rel)
                if os.path.isfile(p) and any(inside(p, r) for r in raw_dirs):
                    os.remove(p)
                    gone.append(repo_rel(p))
            n_gd = 0
            gpath = PO.game_dates_path(league)
            try:
                with open(gpath, encoding="utf-8") as fh:
                    gd = json.load(fh)
                if str(pid) in gd:
                    gd.pop(str(pid), None)
                    (gd.get("_real_dates") or {}).pop(str(pid), None)
                    with open(gpath, "w", encoding="utf-8") as fh:
                        json.dump(gd, fh, indent=1)
                    n_gd = 1
            except (OSError, ValueError):
                pass
            removed.append(pid)
            log(f"REMOVED asof pull {pid} ({league}, game date {game_date or real_date}): {n} rating rows, "
                f"the pulls row, {len(gone)} file(s) ({', '.join(gone) or 'none on disk'}), "
                f"{n_gd} game-date entry")
    finally:
        conn.close()
    if removed:
        import vintage_backup as VB
        VB.export(db_path=PO.DB_PATH, out_dir=PO.VINTAGES_DIR, leagues=[league])
        log(f"{league}: {len(removed)} asof snapshot(s) removed; vintages/{league}/_pulls.csv rewritten.")
    return len(removed)


# ---------------------------------------------------------------- main
def parse_args(argv):
    ap = argparse.ArgumentParser(description="Pull past StatsPlus rating snapshots into the ratings archive.")
    ap.add_argument("--league", required=True, choices=sorted(set(SLUGS) & set(FIRST_KNOWN)))
    ap.add_argument("--slug", help="StatsPlus slug: letters, digits and dashes only")
    ap.add_argument("--from", dest="start", help="first game date YYYY-MM-DD (default: walk back)")
    ap.add_argument("--to", dest="end", help="last step game date YYYY-MM-DD (default: newest live pull)")
    ap.add_argument("--step", default="6m", help="months between dates, e.g. 6m")
    ap.add_argument("--dates", help="exact game dates YYYY-MM-DD,YYYY-MM-DD (replaces the steps and the walk back)")
    ap.add_argument("--write", action="store_true", help="store the snapshots in the archive")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only")
    ap.add_argument("--refetch", action="store_true", help="fetch again even when a raw file is saved")
    ap.add_argument("--retry-missing", action="store_true",
                    help="ask again for the dates StatsPlus had no snapshot for on an earlier run")
    ap.add_argument("--force-overlap", action="store_true",
                    help="run the overlap job even when the newest live pull is today's")
    ap.add_argument("--drop", help="remove these asof snapshots: game dates YYYY-MM-DD,YYYY-MM-DD")
    ap.add_argument("--drop-all-asof", action="store_true", help="remove every asof snapshot of the league")
    ap.add_argument("--base-url", help="TESTS ONLY: a local mock server, e.g. http://127.0.0.1:8765/tgs")
    ap.add_argument("--raw-dir", default=DEFAULT_RAW, help="folder for the raw snapshot files")
    ap.add_argument("--pause", type=float, default=MIN_PAUSE, help="seconds between jobs (min 20)")
    ap.add_argument("--poll", type=float, default=POLL, help="seconds between polls (min 15)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    league = a.league
    slug = a.slug if a.slug is not None else SLUGS[league]
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", slug):
        raise SystemExit("--slug must be a plain StatsPlus slug (letters, digits and dashes, "
                         "e.g. tgs), not a web address. Nothing was fetched.")
    m = re.fullmatch(r"(\d{1,2})m", a.step.strip().lower())
    if not m or not 1 <= int(m.group(1)) <= 12:
        raise SystemExit("--step must be 1m .. 12m")
    months = int(m.group(1))

    # --- remove snapshots (no login needed) --------------------------------
    if a.drop or a.drop_all_asof:
        dates = []
        if a.drop:
            dates = sorted({iso(x) for x in a.drop.split(",")} - {None})
            if not dates:
                raise SystemExit("--drop must be YYYY-MM-DD,YYYY-MM-DD")
        drop_asof(league, dates, a.drop_all_asof, [a.raw_dir, DEFAULT_RAW])
        return 0

    # --- where to ask, and with which login --------------------------------
    if a.base_url:
        try:
            u = urllib.parse.urlsplit(a.base_url)
            host = (u.hostname or "").lower()
        except ValueError:
            u, host = None, ""
        if (u is None or "@" in u.netloc or "\\" in a.base_url
                or host not in ("127.0.0.1", "localhost", "::1")):
            raise SystemExit("--base-url is for tests and must point at this machine (127.0.0.1)")
        base = S.normalize_base(a.base_url)
        cookie = os.environ.get("STATSPLUS_TEST_COOKIE")      # never the real login
    else:
        base = f"https://{SITE_HOST}/{slug}/api"
        if urllib.parse.urlsplit(base).hostname != SITE_HOST:
            raise SystemExit("the StatsPlus address must be on statsplus.net; nothing was fetched")
        cookie = os.environ.get("STATSPLUS_COOKIE")
        a.pause = max(a.pause, MIN_PAUSE)
        a.poll = max(a.poll, POLL)
    a.rate_gap = 0.0 if a.base_url else RATE_GAP
    has_token = S.has_token(base)         # the league's saved token (a test token for the mock)
    if not (cookie or has_token) and not a.dry_run:
        log(f"No StatsPlus login for {league}: no token is saved for {league} and no browser cookies were "
            f"given. Run StatsPlus Tokens.txt to save the {league} token (or give the cookies: "
            f"Get StatsPlus History.bat asks for them).")
        return 2

    log(f"=== {league}: past rating snapshots from StatsPlus ({'store' if a.write else 'check only'}) ===")
    log("  login: " + (f"the saved {league} token" + (", the browser cookies as a fallback" if cookie else "")
                       if has_token else "the browser cookies" if cookie else "none (dry run)"))
    st = archive_state(league)
    latest = st["latest"]
    stop = {"why": None, "date": None, "fail": None, "note": None}
    today_game = None
    try:
        today_game = iso(S.fetch_date(base, fresh=True))
    except S.StatsPlusRefused as e:
        if login_refusal(e) and not cookie and not a.dry_run:
            stop.update(why="login", fail=e)
        else:
            log(f"  note: today's game date not read. {e.user_message(league)}")
    except Exception as e:
        log(f"  note: today's game date not read ({type(e).__name__})")
    if stop["why"]:
        return end_login(league, slug, stop, cookie)
    live_game = iso(latest["game"]) if latest and latest.get("game") else today_game
    if live_game is None:
        raise SystemExit("no game date for the newest live pull and /date not reachable; try again later")
    end = iso(a.end) if a.end else live_game
    log(f"  game date today: {today_game}; newest live pull: "
        + (f"pull {latest['id']} (real date {latest['real']}, game date {latest['game']})" if latest else "none"))
    log(f"  already archived as snapshots: {len(st['asof'])} game date(s)")
    nosnap = NoSnapshot(os.path.join(a.raw_dir, slug, NO_SNAPSHOT_FILE))
    if nosnap.data:
        log(f"  no snapshot on an earlier run: {len(nosnap.data)} game date(s) "
            + ("(asked again: --retry-missing)" if a.retry_missing else "(skipped; --retry-missing asks again)"))

    # --- the plan ----------------------------------------------------------
    first_known = iso(FIRST_KNOWN[league])
    probe = []
    if a.dates:
        steps = sorted({iso(x) for x in a.dates.split(",")} - {None})
        if not steps:
            raise SystemExit("--dates must be YYYY-MM-DD,YYYY-MM-DD")
        start = steps[0]
    elif a.start:
        start = iso(a.start)
        if start is None:
            raise SystemExit("--from must be YYYY-MM-DD")
    else:
        start = first_known
        d = add_months(first_known, -months)
        floor = datetime.date(first_known.year - PROBE_YEARS[league], 1, 1)
        while d >= floor:
            probe.append(d)
            d = add_months(d, -months)
    if not a.dates:
        steps = step_dates(start, end, months)
    overlap = live_game if latest else None
    latest_path = next((repo_abs(rel) for rel in (latest or {}).get("files") or []
                        if repo_abs(rel).endswith(".json") and os.path.isfile(repo_abs(rel))), None)
    # today's view without a job: the newest live pull is from today's game date,
    # and a saved token can be checked with /tokencheck (a cookie is proved only by a job)
    skip_overlap = bool(overlap and latest.get("game") and today_game and iso(latest["game"]) == today_game
                        and latest_path and has_token and not a.force_overlap)
    # today's view must be TODAY's ratings: when the league has played on since the
    # newest live pull (or today's game date is unknown, or there is no live pull),
    # the check job asks for the ratings without a date instead of the overlap date
    view_date = today_game or live_game
    undated_view = not skip_overlap and not (overlap and today_game and overlap == today_game)

    def too_close(d):
        """Why a step date is too close to today's ratings to ask for, else None."""
        if today_game and (today_game - d).days <= NEAR_TODAY_DAYS:
            return (f"too close to today (today's game date is {today_game}; a date within "
                    f"{NEAR_TODAY_DAYS} days of it, or after it, is not asked for)")
        if overlap and (overlap - d).days <= NEAR_OVERLAP_DAYS:
            return (f"too close to the overlap date {overlap} (a date less than {NEAR_OVERLAP_DAYS + 1} "
                    f"days before it, or on or after it, is not asked for: its ratings are still close "
                    f"to today's)")
        return None
    dropped = [(d, too_close(d)) for d in steps if too_close(d)]
    steps = [d for d in steps if not too_close(d)]
    for d, why in dropped:
        log(f"  {d}: {'refused' if a.dates else 'dropped from the steps'}: {why}")
    # StatsPlus names its first snapshot date when asked for an earlier one
    # ("The earliest date with ratings history is 2040-08-07"); a run that saw
    # it skips every earlier date and asks for that date itself
    said = sorted({e for e in (earliest_said(v.get("reason")) for v in nosnap.data.values()) if e})
    if said and not a.dates:
        steps, n_early = from_earliest(steps, said[0], too_close)
        probe = [d for d in probe if d >= said[0]]
        log(f"  StatsPlus's {league} ratings history starts at {said[0]} (it said so on an earlier run): "
            f"{n_early} earlier step date(s) not asked; {said[0]} is asked")
    ov_txt = (f"overlap check on game date {overlap}, no job (the newest live pull is today's; the token is "
              f"checked)" if skip_overlap
              else "today's ratings from a job without a date (the league played on since the newest live "
                   "pull, or there is none or no game date)" if undated_view
              else f"overlap check on game date {overlap}")
    log(f"  plan: {ov_txt}; walk back "
        f"{', '.join(x.isoformat() for x in probe) or '-'} (stops after 2 dates in a row without new "
        f"ratings); then {len(steps)} step game date(s) {steps[0] if steps else '-'} .. "
        f"{steps[-1] if steps else '-'} every {months} month(s)")
    if a.dry_run:
        walk = ([start] + probe) if probe else []
        if undated_view:
            log(f"    {view_date}  today job: the ratings without a date become today's view")
        elif overlap:
            log(f"    {overlap}  " + ("overlap: no job, today's view = the newest live pull" if skip_overlap
                                      else "overlap job"))
        for d in walk + [x for x in steps if x not in walk]:
            k = d.isoformat()
            if k in st["asof"]:
                tag = "already archived, skip"
            elif k in nosnap.data and not a.retry_missing:
                tag = f"no snapshot last time ({nosnap.data[k].get('reason')}), skip"
            else:
                tag = "fetch"
                if os.path.isfile(os.path.join(a.raw_dir, slug, f"{k}.json")) and not a.refetch:
                    tag += " (raw file saved, no job needed)"
            log(f"    {d}  {tag}")
        log("  dry run: nothing fetched or written.")
        return 0

    latest_rows = load_raw(latest_path) if latest_path else None
    latest_names = ({str(r.get("ID") or "").strip(): norm_name(r.get("Name")) for r in latest_rows}
                    if latest_rows else None)

    job = Job(a, league, slug, base, cookie)
    # the login proof without a job: one /tokencheck call
    if skip_overlap:
        try:
            tid = S.tokencheck(base, S.token_for_url(base + "/tokencheck/"))
            log(f"  login: StatsPlus accepts the saved {league} token (team {tid})")
        except S.StatsPlusRefused as e:
            if login_refusal(e) and not cookie:
                stop.update(why="login", fail=e)
                return end_login(league, slug, stop, cookie)
            log(f"  note: the token check failed. {e.user_message(league)} The overlap job checks the "
                f"login instead.")
            if login_refusal(e):
                job.drop_token(e.kind)
            skip_overlap = False
        except Exception as e:
            log(f"  note: the token check did not answer ({type(e).__name__}: {S.redact(e)}); the overlap "
                f"job checks the login instead.")
            skip_overlap = False

    dob = dob_map(league, base)
    log(f"  birth dates known: {len(dob)} players")

    # known movers between the oldest and the newest live raw file
    movers, mover_span = {}, None
    if len(st.get("live_raw", [])) >= 2:
        (o_id, o_game, o_path), (n_id, n_game, n_path) = st["live_raw"][0], st["live_raw"][-1]
        movers = movers_between(load_raw(o_path), latest_rows if n_id == (latest or {}).get("id")
                                else load_raw(n_path))
        mover_span = (o_id, o_game, n_id, n_game)
        log(f"  players who changed org between live pulls {o_id} (game date {o_game}) and {n_id} "
            f"(game date {n_game}): {len(movers)}")

    import ratings_db as RDB
    report = {"fetched": [], "skipped": [(d.isoformat(), w) for d, w in dropped], "stored": [],
              "overlap": None, "ages": {}, "movers": {}, "orgs": {}, "diff": {}, "age_src": {},
              "view": None, "memo_skipped": 0, "memo_forgotten": [], "moved": [], "unclear": [],
              "today_job": undated_view}
    seen = dict(st["hashes"])            # content hash -> what holds it (archive + accepted this run)
    run_hash = {}                        # content hash -> game date accepted this run (walk back, steps)
    accepted = []                        # past game dates accepted this run
    fb = {"asked": False, "side": None}  # which snapshot StatsPlus sends for a missing date (fallback_side)
    names_at = {}                        # game date -> {id: name} of the dates accepted this run
    names_cache = {}
    ov = {"hash": None, "store": None,   # today's view (the overlap job or the newest live pull),
          "map": None, "names": None,    # and the overlap rows to store at the end
          "date": None, "src": None}
    latest_map = RDB.rows_to_map(latest_rows, league=league) if latest_rows else None

    def use_live_view(why):
        ov.update(hash=RDB.content_hash(latest_map), map=latest_map, date=live_game,
                  names={pid: norm_name(rec.get("name")) for pid, rec in latest_map.items()},
                  src=f"live pull {latest['id']}")
        report["view"] = f"live pull {latest['id']} (game date {latest['game'] or live_game}): {why}"
        log(f"  today's view = live pull {latest['id']} (game date {latest['game'] or live_game}): {why}")

    def refuse(key, how, why, day):
        report["skipped"].append((key, why))
        log(f"  {key}: {why}; NOT stored")
        if how == "saved file":
            job.forget(day)

    def nearest_names(day):
        """(game date, {id: name}) of the nearest accepted or archived snapshot
        within LOOSE_ID_DAYS, else None."""
        cands = [(abs((g - day).days), g, "run") for g in names_at]
        cands += [(abs((g - day).days), g, pid) for g, pid in st["by_game"].items()]
        cands = [c for c in cands if 0 < c[0] <= LOOSE_ID_DAYS]
        if not cands:
            return None
        _dist, g, src = min(cands, key=lambda c: (c[0], c[1]))
        if src == "run":
            return g, names_at[g]
        if src not in names_cache:
            names_cache[src] = load_names(src)
        return g, names_cache[src]

    def handle(day, phase):
        """Fetch, check and (with --write) store one date. phase = 'overlap'
        (the overlap job), 'today' (a job without a date: today's view; day
        is only its label), 'probe' (walk back) or 'step'. Returns 'data',
        'today' (today's ratings), 'nosnap' (no snapshot, now or on an earlier
        run), 'same', 'refused', 'empty' (no ratings for another reason, or the
        run stops), 'view' (the overlap reply is not today's view) or 'skip'
        (already archived)."""
        key = day.isoformat()
        view_job = phase in ("overlap", "today")
        if not view_job:
            if key in st["asof"]:
                report["skipped"].append((key, f"already archived (pull {st['asof'][key]})"))
                log(f"  {key}: already archived as pull {st['asof'][key]}; skipped")
                return "skip"
            memo = nosnap.data.get(key)
            if memo and not a.retry_missing:
                report["memo_skipped"] += 1
                report["skipped"].append((key, f"no snapshot on an earlier run ({memo.get('reason')}, asked "
                                               f"{memo.get('asked')}); --retry-missing asks again"))
                log(f"  {key}: no snapshot on an earlier run ({memo.get('reason')}); skipped")
                return "nosnap"
        if phase == "today":
            log(f"  {key}: asking StatsPlus for today's ratings (a job without a date) ...")
        else:
            log(f"  {key}: asking StatsPlus for the ratings of game date {key} ...")
        rows, how = job.fetch(day, force=view_job, undated=(phase == "today"))
        if how in STOP_HOW:
            stop.update(why=STOP_HOW[how], date=key, fail=job.failure)
            return "empty"
        if rows is None:
            f = job.failure
            said = f": {f.message}" if f is not None and f.message else ""
            if (phase == "overlap" and latest_map and f is not None and f.started
                    and how in ("no snapshot", "error page")):
                # the job started, so the login works; StatsPlus just has no
                # snapshot of the overlap date. The newest live pull is from
                # today's game date (else the job would have had no date).
                report["skipped"].append((key, f"overlap job: {HOW_WORDS[how]}{said}"))
                use_live_view(f"the overlap job sent no ratings ({HOW_WORDS[how]}{said}); the login works")
                return "view"
            if view_job:
                what = "today's ratings job" if phase == "today" else "overlap job"
                stop.update(why="overlap failed", date=key, fail=f,
                            note=f"{HOW_WORDS.get(how, how)}{said}")
                log(f"!!!! {key}: the {what} failed: {HOW_WORDS.get(how, how)}{said}")
                return "empty"
            if how == "no snapshot":
                why = f"no snapshot for this date ({HOW_WORDS[how]}{said})"
                nosnap.add(day, "empty", f"{HOW_WORDS[how]}{said}")
                report["skipped"].append((key, why))
                log(f"  {key}: {why}; remembered, skipped")
                return "nosnap"
            why = f"{HOW_WORDS.get(how, how)}{said}; not remembered, asked again next run"
            report["skipped"].append((key, why))
            log(f"  {key}: {why}")
            return "empty"
        log(f"  {key}: {len(rows)} players, {len(rows[0])} columns ({how})")
        pmap = RDB.rows_to_map(rows, league=league)
        h = RDB.content_hash(pmap)
        names = {pid: norm_name(rec["name"]) for pid, rec in pmap.items()}

        # 1. the league check
        if view_job:
            joined, same = identity_check(names, latest_names)
            ref_txt = f"the newest {league} live pull"
            bar = STRICT_ID_SHARE
        else:
            ref = nearest_names(day)
            joined, same = identity_check(names, ref[1]) if ref else (0, 0)
            ref_txt = f"the {league} snapshot of game date {ref[0]}" if ref else ""
            bar = LOOSE_ID_SHARE
        if joined >= 200 and same < bar * joined:
            stop["why"], stop["date"] = "wrong league", key
            log(f"!!!! {key}: these ratings do NOT look like {league} ({same} of {joined} players match "
                f"{ref_txt} by ID + Name). Nothing from this date was stored.")
            return "empty"

        if phase == "today":
            # today's ratings ARE today's view: exactly what StatsPlus sends for a
            # date it has no snapshot of, so the hash and 2 percent rules below hold
            ov.update(hash=h, map=pmap, names=names, date=day, src="a job without a date")
            report["view"] = f"today's ratings (a job without a date; game date {key})"
            log(f"  today's view = today's ratings (a job without a date; game date {key}); not stored")
            return "data"

        # 2. today's ratings for a past date? Decided by the RATINGS, never by the ages alone
        if phase == "overlap":
            today_ref = today_game
        else:
            today_ref = min(x for x in (today_game, overlap) if x) if (today_game or overlap) else None
        chk = check_ages(rows, dob, day, today_ref)
        report["ages"][key] = chk
        log(f"  {key}: ages fit game date {chk['fit']} (n={chk['n']}, agree {chk['share']:.2f}) -> "
            + AGE_WORDS[chk["verdict"]])
        if phase == "overlap":
            fails = []
            if latest_map:
                shared, changed = rating_diff(pmap, latest_map)
                report["diff"][key] = (shared, changed)
                log(f"  {key}: ratings differ from live pull {latest['id']} (same game date) on {changed} of "
                    f"{shared} shared players ({pct(changed, shared):.1f}%)")
                if shared and changed >= IGNORED_SHARE * shared:
                    fails.append(f"its ratings differ from live pull {latest['id']} of the same game date on "
                                 f"{pct(changed, shared):.1f}% of shared players (the bar is "
                                 f"{100 * IGNORED_SHARE:.0f}%)")
            if chk["verdict"] in ("other", "unclear"):
                fails.append(AGE_WORDS[chk["verdict"]] + (f" (they fit {chk['fit']})" if chk["fit"] else ""))
            if fails:
                if not latest_map:
                    stop.update(why="overlap failed", date=key, fail=None,
                                note=f"the reply is not the ratings of {key} ({'; '.join(fails)}), and the "
                                     f"newest live pull has no raw file to use instead")
                    log(f"!!!! {key}: {stop['note']}")
                    return "empty"
                report["skipped"].append((key, f"overlap reply not used as today's view: {'; '.join(fails)}"))
                use_live_view(f"the overlap reply is not the ratings of {key} ({'; '.join(fails)}); StatsPlus "
                              f"probably has no snapshot of that date")
                return "view"
            ov.update(hash=h, map=pmap, names=names, date=day, src=f"the overlap job of {key}")
            report["view"] = f"the overlap job (game date {key})"
        else:
            vh = ov["hash"]
            shared, changed = rating_diff(pmap, ov["map"]) if ov["map"] else (0, 0)
            if ov["map"]:
                report["diff"][key] = (shared, changed)
                log(f"  {key}: ratings differ from today's view ({ov['src']}) on {changed} of {shared} "
                    f"shared players ({pct(changed, shared):.1f}%)")
            far = ov["date"] is not None and (ov["date"] - day).days > TODAY_LIKE_DAYS
            why_today = None
            if vh is not None and h == vh:
                why_today = f"the ratings are exactly those of today's view ({ov['src']})"
            elif latest and h == latest.get("hash"):
                why_today = f"the ratings are exactly those of live pull {latest['id']}"
            elif shared >= MIN_SHARED and changed < IGNORED_SHARE * shared:
                why_today = (f"only {changed} of {shared} shared players ({pct(changed, shared):.1f}%) have "
                             f"ratings different from today's view (the bar is {100 * IGNORED_SHARE:.0f}%)")
            elif (chk["verdict"] == "today" and far and shared >= MIN_SHARED
                  and changed < TODAY_LIKE_SHARE * shared):
                why_today = (f"its ages fit today (game date {chk['fit']}) and only {changed} of {shared} "
                             f"shared players ({pct(changed, shared):.1f}%) have ratings different from "
                             f"today's view (under {100 * TODAY_LIKE_SHARE:.0f}%, and {key} is more than "
                             f"{TODAY_LIKE_DAYS} days before it)")
            if why_today:
                log(f"  {key}: {why_today}: StatsPlus has no snapshot of this date and sent today's ratings")
                nosnap.add(day, "today", "StatsPlus sent today's ratings")
                refuse(key, how, "no snapshot for this date (StatsPlus sent today's ratings)", day)
                return "today"

        # 3. the ages. The ratings are that date's; ages that fit today are rebuilt
        age_src = AGE_REBUILT if rows and rows[0].get(AGE_FIELD) == AGE_REBUILT else AGE_STATSPLUS
        if chk["verdict"] == "today":
            rows, n_ok, n_null = rebuild_ages(rows, dob, day, names if phase == "overlap" else ov["names"])
            age_src = AGE_REBUILT
            log(f"  {key}: the ages fit today (game date {chk['fit']}), not {key}: ages rebuilt from birth "
                f"dates at {key} ({n_ok} players; {n_null} with no known birth date keep a null age)")
            if phase != "overlap":
                # a later roster: many players were not even YOUNG_AGE on the date asked for
                ages = [int(r["Age"]) for r in rows if re.fullmatch(r"-?\d+", str(r.get("Age") or ""))]
                young = sum(1 for x in ages if x < YOUNG_AGE)
                if len(ages) >= MIN_SHARED and young > YOUNG_SHARE * len(ages):
                    log(f"  {key}: {young} of {len(ages)} players with a known birth date "
                        f"({pct(young, len(ages)):.0f}%) were under {YOUNG_AGE} on {key}: this is a roster "
                        f"from a later date, so StatsPlus has no snapshot of this date")
                    nosnap.add(day, "refused", "StatsPlus sent a roster from a later date")
                    refuse(key, how, "no snapshot for this date (StatsPlus sent a roster from a later date)", day)
                    return "refused"
        report["age_src"][key] = age_src
        ages_ok = chk["verdict"] == "past" or age_src == AGE_REBUILT

        # 4. a repeat of a stored pull or of a date accepted this run
        if h in seen:
            prev = run_hash.get(h)
            if phase == "overlap":
                log(f"  {key}: the overlap ratings equal {seen[h]}; it is a check only this run (not stored)")
            elif (phase == "step" and prev is not None and prev < day and age_src == AGE_REBUILT
                  and report["age_src"].get(prev.isoformat()) == AGE_REBUILT):
                # KNOWN LIMIT case: the ages can not tell whether `prev` holds the
                # snapshot of `day` (StatsPlus answered the missing prev with the next
                # LATER snapshot) or `day` has none (answered with the EARLIER one)
                side = fallback_side(prev, day, h)
                if stop["why"]:
                    return "empty"
                if side == "later":
                    move_away(prev, day)                 # then this date is accepted below
                else:
                    if side == "earlier":
                        why = (f"the same ratings as {seen[h]} (a repeat): StatsPlus answers a missing date "
                               f"with the nearest EARLIER snapshot, so {key} has none")
                    else:
                        why = (f"the same ratings as {seen[h]} (a repeat); it is not clear whether they are "
                               f"the snapshot of {prev} or of {key} (see KNOWN LIMIT)")
                        report["unclear"].append((prev.isoformat(), key))
                    nosnap.add(day, "refused", why)
                    refuse(key, how, why, day)
                    return "same"
            else:
                why = f"the same ratings as {seen[h]} (a repeat)"
                if chk["verdict"] == "past":
                    why += (f"; its ages fit {key}, so {seen[h]} may hold the snapshot of {key} "
                            f"(see KNOWN LIMIT); not remembered")
                else:
                    nosnap.add(day, "refused", why)
                refuse(key, how, why, day)
                return "same"
        # ages that clearly fit ANOTHER past day: the ratings are a real snapshot
        # (they passed the today's-ratings rules above), just of that day. Store it
        # under the day its ages fit (user, 2026-09-30, on StatsPlus's first TGS
        # snapshot: asked 2040-08-07, every age fit 2040-07-01: "why would we not
        # store that"). Not when that day is already archived or accepted this run.
        fit = iso(chk["fit"]) if chk["verdict"] == "other" and chk.get("fit") else None
        if (not ages_ok and phase != "overlap" and fit is not None and fit.isoformat() not in st["asof"]
                and fit not in run_hash.values() and (today_ref is None or fit < today_ref)):
            nosnap.add(day, "refused", f"its snapshot is from {fit} (the ages fit that day); stored under {fit}")
            log(f"  {key}: the ages fit {fit} exactly (agree {chk['share']:.2f}): StatsPlus's snapshot is "
                f"from {fit}; stored under {fit}")
            report["moved"].append((key, fit.isoformat()))
            day, key, ages_ok = fit, fit.isoformat(), True
            report["age_src"][key] = age_src
        if not ages_ok:
            if phase == "overlap":
                log(f"  {key}: the overlap snapshot is a check only this run (not stored): "
                    f"{AGE_WORDS[chk['verdict']]}")
            else:
                why = AGE_WORDS[chk["verdict"]] + (f" (they fit {chk['fit']})" if chk["fit"] else "")
                if chk["verdict"] in ("other", "unclear"):
                    nosnap.add(day, "refused", why)
                refuse(key, how, why, day)
                return "refused"

        # accepted: every row says where its Age came from (the raw file keeps it)
        rows = [r if r.get(AGE_FIELD) == age_src else dict(r, **{AGE_FIELD: age_src}) for r in rows]
        if phase != "overlap" and how == "fetched" and job.save(day, rows) is None:
            refuse(key, how, "its raw file could not be written; not remembered, asked again next run", day)
            return "empty"
        report["fetched"].append((key, len(rows)))
        if movers:
            byid = {str(r.get("ID")): str(r.get("Org") or "").strip() for r in rows}
            old = new = other = 0
            for pid, (o, nw) in movers.items():
                v = byid.get(pid)
                if v is None:
                    continue
                old += int(v == o)
                new += int(v == nw)
                other += int(v not in (o, nw))
            report["movers"][key] = (old, new, other)
        report["orgs"][key] = {str(r.get("ID")): (str(r.get("Org") or ""), str(r.get("Team") or ""),
                                                  str(r.get("LgLvl") or ""), str(r.get("League") or ""))
                               for r in rows}
        if phase == "overlap":
            if latest_rows:
                report["overlap"] = dict(overlap_compare(rows, latest_rows), date=key, live_pull=latest["id"])
            if h not in seen and ages_ok and key not in st["asof"]:
                ov["store"] = (day, rows, h, how)
            return "data"
        if key in nosnap.data:
            nosnap.remove(day)
            report["memo_forgotten"].append(key)
            log(f"  {key}: removed from the no-snapshot memory (StatsPlus has this snapshot now)")
        seen[h] = f"game date {key} (this run)"
        run_hash[h] = day
        names_at[day] = names
        accepted.append(day)
        if a.write:
            store(day, rows)
        return "data"

    def fallback_side(prev, day, h):
        """Which way StatsPlus answers a date it has no snapshot of: 'later'
        (the next later snapshot: then `prev` holds the snapshot of `day`),
        'earlier' (the nearest earlier one: then `day` has none) or None (not
        decided). One extra job per run, for the day before `prev`: a missing
        day answered with the later snapshot repeats the ratings of `day`."""
        if fb["asked"]:
            return fb["side"]
        fb["asked"] = True
        q = prev - datetime.timedelta(days=1)
        log(f"  {day.isoformat()}: the same ratings as {prev} (both with ages rebuilt): asking {q} to learn "
            f"which snapshot StatsPlus sends for a missing date ...")
        rows, how = job.fetch(q)
        if how in STOP_HOW:
            stop.update(why=STOP_HOW[how], date=q.isoformat(), fail=job.failure)
            return None
        if rows is None:
            log(f"  {q}: {HOW_WORDS.get(how, how)}; not decided")
            return None
        hq = RDB.content_hash(RDB.rows_to_map(rows, league=league))
        if hq == ov["hash"] or (latest and hq == latest.get("hash")):
            log(f"  {q}: today's ratings; not decided")
            return None
        fb["side"] = "later" if hq == h else "earlier"
        log(f"  {q}: " + ("the same ratings again: StatsPlus answers a missing date with the next LATER snapshot"
                          if hq == h else "other ratings: StatsPlus answers a missing date with the nearest "
                                          "EARLIER snapshot"))
        return fb["side"]

    def move_away(prev, day):
        """`prev` holds the snapshot of `day`: take prev out of this run's
        results (and out of the archive with --write) and remember it."""
        pk = prev.isoformat()
        pid = st["asof"].pop(pk, None)
        if pid is not None:
            unstore_pull(pid)
            report["stored"] = [x for x in report["stored"] if x[0] != pk]
        report["fetched"] = [x for x in report["fetched"] if x[0] != pk]
        report["orgs"].pop(pk, None)
        report["movers"].pop(pk, None)
        names_at.pop(prev, None)
        for hh in [k for k, v in run_hash.items() if v == prev]:
            run_hash.pop(hh)
        if prev in accepted:
            accepted.remove(prev)
        path = job.raw_path(prev)
        if os.path.isfile(path):
            os.remove(path)
        nosnap.add(prev, "refused", f"StatsPlus sent the snapshot of {day.isoformat()} for it (it answers a "
                                    f"missing date with the next later snapshot)")
        report["moved"].append((pk, day.isoformat()))
        log(f"  {pk}: its ratings are the snapshot of {day.isoformat()}: "
            + (f"pull {pid} removed, " if pid is not None else "") + f"{day.isoformat()} is stored instead; "
            f"{pk} is remembered as no snapshot")

    def store(day, rows):
        key = day.isoformat()
        pid = RDB.append_pull(league, rows, source=PO.ASOF, real_date=key,
                              real_ts=datetime.datetime.now().isoformat(timespec="seconds"),
                              files=[repo_rel(job.raw_path(day))], db_path=PO.DB_PATH, game_date=key)
        st["asof"][key] = pid
        report["stored"].append((key, pid))
        log(f"  {key}: stored as pull {pid} (source asof, game date {key})")

    # 1. today's view: the newest live pull (no job), the overlap job (the live
    # pull is from today's game date), or today's ratings (a job without a date)
    if stop["why"]:
        pass
    elif skip_overlap:
        use_live_view("it is from today's game date, so no overlap job is needed")
    elif undated_view:
        handle(view_date, "today")
    elif overlap:
        handle(overlap, "overlap")
    # 2. walk back (newest first), then 3. the steps (oldest first)
    earliest = None
    run = 0
    walk = ([start] + probe) if probe else []
    for d in walk:
        if stop["why"]:
            break
        r = handle(d, "probe")
        if r == "data" or (r == "skip" and d.isoformat() in st["asof"]):
            earliest, run = d, 0
        else:
            run += 1
            if run >= 2:
                log(f"  two dates in a row without new ratings (the last one {d}): the walk back stops; "
                    + (f"{league} history starts at {earliest}" if earliest
                       else f"no {league} ratings found this far back"))
                break
    # Exit 7 (StatsPlus ignores the date): TODAY_STOP_RUN step dates in a row came
    # back as today's ratings AND no past date was accepted this run. A date that
    # was already in the no-snapshot memory (--retry-missing) does not count, and
    # any other result resets the count, so a real gap in thinned history never
    # blocks the later runs.
    today_run = 0
    queue = list(steps)
    while queue:
        d = queue.pop(0)
        if stop["why"]:
            break
        if probe and d == start:
            continue                          # done in the walk back
        r = handle(d, "step")
        first = earliest_said((nosnap.data.get(d.isoformat()) or {}).get("reason"))
        if first and not a.dates and first > d:
            queue, n_early = from_earliest(queue, first, too_close)
            log(f"  StatsPlus's {league} ratings history starts at {first}: {n_early} earlier step "
                f"date(s) not asked; {first} is asked next")
        if r != "today":
            today_run = 0
        elif d.isoformat() not in nosnap.loaded:
            today_run += 1
            if today_run >= TODAY_STOP_RUN and not accepted:
                stop["why"], stop["date"] = "date ignored", d.isoformat()
                log(f"!!!! {d}: {TODAY_STOP_RUN} step dates in a row came back as today's ratings, and no past "
                    f"date was accepted this run. StatsPlus ignores the date; the run stops.")
    if stop["why"] == "date ignored":
        gone = nosnap.forget_added("today")
        if gone:
            log(f"  not remembered as 'no snapshot' (StatsPlus ignored the date, so they are asked again next "
                f"run): {', '.join(gone)}")
    # the overlap snapshot: stored last, and only when the run did not stop
    if not stop["why"] and ov["store"]:
        day, rows, h, how = ov["store"]
        if h in seen:
            log(f"  {day}: the overlap ratings equal {seen[h]}; not stored")
        elif how == "fetched" and job.save(day, rows) is None:
            log(f"  {day}: the overlap ratings were not stored (no raw file)")
        elif a.write:
            store(day, rows)

    # --- after the run -----------------------------------------------------
    if stop["why"] == "login":
        end_login(league, slug, stop, cookie, stored=len(report["stored"]))
    if a.write and report["stored"]:
        import vintage_backup as VB
        VB.export(db_path=PO.DB_PATH, out_dir=PO.VINTAGES_DIR, leagues=[league])
        neighbour_checks(league, [p for _d, p in report["stored"]])
    first = min(st["asof"]) if st["asof"] else None
    if not first and report["fetched"]:
        first = min(d for d, _n in report["fetched"])
        first = f"{first} (the first date accepted this run; check only, not stored)"
    print_report(league, report, movers, mover_span, first, stop, a.write, nosnap)
    return EXIT.get(stop["why"], 0)


def unstore_pull(pid):
    """Remove one asof pull from the archive (its rating rows and pulls row).
    Used during a run, before the vintage export, so no vintage file exists yet."""
    import ratings_db as RDB
    conn = RDB.connect(PO.DB_PATH)
    try:
        conn.execute("DELETE FROM ratings WHERE pull_id=?", (pid,))
        conn.execute("DELETE FROM pulls WHERE pull_id=?", (pid,))
        conn.commit()
    finally:
        conn.close()


def end_login(league, slug, stop, cookie, stored=0):
    """The message when StatsPlus refused the login (exit 3)."""
    f = stop.get("fail")
    msg = f.user_message(league) if f is not None else f"StatsPlus refused the {league} login."
    log(f"{league} was not pulled this run. {msg}" if not stored else
        f"{league}: the run stopped at game date {stop.get('date')}. {msg}")
    if cookie and not (f is not None and getattr(f, "token_sent", False)):
        log(f"(A browser login only pulls the league it is signed into. To update {league}: open")
        log(f" statsplus.net/{slug} in your browser, then run this again. StatsPlus Tokens.txt saves")
        log(f" a token instead.)")
    if stored:
        log(f"{stored} date(s) were stored before the stop; they passed every check and stay stored (the "
            f"report below lists them).")
    else:
        log(f"The archive keeps what it had for {league}.")
    return EXIT["login"]


def neighbour_checks(league, new_ids):
    """Scale-event guard and game-date gap of each new snapshot against its
    neighbours in game-date order (the age_curves pair rules)."""
    import sqlite3
    import ratings_db as RDB
    conn = sqlite3.connect(PO.DB_PATH)
    try:
        rows, game = PO.ordered(conn, league, log)
        ids = [r[0] for r in rows]
        log("")
        log("  neighbour check (game-date order; guard = ratings_db.pair_guard; a gap over 1.0 game year "
            "breaks the age-step rules):")
        seen = set()
        for pid in new_ids:
            if pid not in ids:
                continue
            i = ids.index(pid)
            for j in (i - 1, i):
                if j < 0 or j + 1 >= len(ids) or (ids[j], ids[j + 1]) in seen:
                    continue
                seen.add((ids[j], ids[j + 1]))
                a, b = rows[j], rows[j + 1]
                ma, mb = RDB.load_pull_map(conn, a[0]), RDB.load_pull_map(conn, b[0])
                shared = []
                for p, nrec in mb.items():
                    orec = ma.get(p)
                    if not orec or orec.get("org") in (None, "", "0", 0):
                        continue
                    try:
                        a1 = int(float(orec["age"]))
                        dd = int(float(nrec["age"])) - a1
                    except (TypeError, ValueError):
                        continue
                    if dd in (0, 1):
                        shared.append((p, orec, nrec, a1, dd))
                span = (sum(s[4] for s in shared) / len(shared)) if shared else 0.0
                g = RDB.pair_guard(shared, 20)
                flags = [f"{RDB.SIDE_LABEL[s]}: {g[s]['reason']}" for s in RDB.SIDES if g[s]["reason"]]
                ga, gb = iso(game.get(a[0])), iso(game.get(b[0]))
                gap = (gb - ga).days / 365.25 if ga and gb else None
                gap_txt = f"gap {gap:.2f} game years" if gap is not None else "gap unknown"
                log(f"    pull {a[0]} (game date {game.get(a[0])}, {a[3]}) -> pull {b[0]} "
                    f"(game date {game.get(b[0])}, {b[3]}): {len(shared)} shared org players, "
                    f"age-step span {span:.2f}, {gap_txt}")
                log(f"      guard: {'; '.join(flags) if flags else 'clean'}"
                    + ("; GAP OVER 1 GAME YEAR" if gap is not None and gap > 1.0 else ""))
    finally:
        conn.close()


def print_report(league, rep, movers, mover_span, first, stop, wrote, nosnap):
    why = stop["why"]
    log("")
    log(f"=== {league}: report ===")
    if rep.get("view"):
        log(f"  today's view: {rep['view']}")
    stored_txt = (f"; the {len(rep['stored'])} date(s) stored before it passed every check." if rep["stored"]
                  else "; nothing stored.")
    if why == "date ignored":
        log(f"  StatsPlus sent today's ratings for {TODAY_STOP_RUN} step dates in a row (the last one "
            f"{stop['date']}), and no past date was accepted this run: it ignores the date. The run stopped "
            f"there" + stored_txt)
    elif why == "login":
        log(f"  StatsPlus refused the login at game date {stop.get('date') or '-'} (the message above says "
            f"why). The run stopped there" + stored_txt)
    elif why == "wrong league":
        log(f"  The ratings of game date {stop['date']} are not {league}'s. The run stopped there" + stored_txt)
    elif why == "daily limit":
        log(f"  StatsPlus allows 5 past-date requests a day and today's are used up (at game date "
            f"{stop['date']}). The run stopped there" + stored_txt + " Run it again tomorrow: the dates "
            f"already stored are skipped, and it goes on from there.")
    elif why == "not enabled":
        log(f"  StatsPlus says past date ratings are not enabled for {league} (game date {stop['date']}). "
            f"The login worked. Nothing was stored. The league's StatsPlus owner has to switch the "
            f"feature on; then run this again.")
    elif why == "off site":
        log(f"  StatsPlus pointed the job at another site (game date {stop['date']}). The login was not "
            f"sent there. The run stopped" + stored_txt)
    elif why == "overlap failed":
        f = stop.get("fail")
        what = ("The job for today's ratings (a job without a date, for today's view)" if rep.get("today_job")
                else f"The overlap job (game date {stop['date']}, the game date of the newest live pull)")
        log(f"  {what} failed, not because of the login: {stop.get('note')}. Nothing was stored.")
        if f is not None and f.kind in ("network", "timed_out", "too_soon", "blocked"):
            log(f"  {f.user_message(league)}")
        else:
            log(f"  Run Get StatsPlus Ratings.bat first, then run this again: with a saved token and a live "
                f"pull from today, no check job is needed.")
    log(f"  dates with ratings accepted this run: {len(rep['fetched'])}")
    for d, n in rep["fetched"]:
        a = rep["ages"].get(d, {})
        sh, ch = rep["diff"].get(d, (0, 0))
        diff_txt = (f"ratings different from today on {ch} of {sh} shared players ({pct(ch, sh):.1f}%)"
                    if sh else "ratings not compared with today")
        src = rep["age_src"].get(d, AGE_STATSPLUS)
        src_txt = ("ages rebuilt from birth dates (StatsPlus sent today's ages)" if src == AGE_REBUILT
                   else "ages from StatsPlus")
        log(f"    {d}: {n} players; {diff_txt}; {src_txt} (StatsPlus ages fit {a.get('fit')}, n={a.get('n')})")
    n_rebuilt = sum(1 for d, _n in rep["fetched"] if rep["age_src"].get(d) == AGE_REBUILT)
    if n_rebuilt:
        log(f"  NOTE: on {n_rebuilt} date(s) StatsPlus sent past ratings with today's ages; the ages were "
            f"rebuilt from birth dates (raw file field {AGE_FIELD}). Team fields on those dates may be "
            f"today's too (see the team check below).")
    log(f"  stored in the archive: {len(rep['stored'])}"
        + ("" if wrote else " (check only: add --write to store)"))
    n_snap = n_reb = 0
    for d, p in rep["stored"]:
        if rep["age_src"].get(d) == AGE_REBUILT:
            n_reb += 1
            src_txt = "ages rebuilt from birth dates (the snapshot had today's ages)"
        else:
            n_snap += 1
            src_txt = "ages from the snapshot"
        log(f"    game date {d} -> pull {p}; {src_txt}")
    if rep["stored"]:
        log(f"  ages of the stored dates: {n_snap} from the snapshot, {n_reb} rebuilt from birth dates"
            + (" (rebuilt ages: a snapshot of an odd earlier date could be stored under the date asked "
               "for; see KNOWN LIMIT in statsplus_history.py)" if n_reb else ""))
    for d0, d1 in rep.get("moved") or []:
        log(f"  MOVED: game date {d0} held the snapshot of {d1} (StatsPlus answers a missing date with the next "
            f"later snapshot); it is stored under {d1} only.")
    for d0, d1 in rep.get("unclear") or []:
        log(f"  CHECK: game date {d0} and {d1} came back with the same ratings, both with today's ages, and "
            f"the extra check job did not tell which date they belong to. {d0} was kept and {d1} refused. "
            f"If {d0} is wrong: --drop {d0}, then --retry-missing.")
    log(f"  dates skipped or refused: {len(rep['skipped'])}")
    for d, why_ in rep["skipped"]:
        log(f"    {d}: {why_}")
    added = sorted(nosnap.added)
    log(f"  no-snapshot memory ({repo_rel(nosnap.path)}): {len(nosnap.data)} date(s); added this run: "
        f"{', '.join(added) or 'none'}; skipped this run: {rep['memo_skipped']}"
        + (" (--retry-missing asks them again)" if rep["memo_skipped"] else ""))
    if rep["memo_forgotten"]:
        log(f"    removed (StatsPlus has them now): {', '.join(rep['memo_forgotten'])}")
    log(f"  {league} history starts at {first}" if first else f"  no {league} snapshot stored yet")
    ov = rep["overlap"]
    if ov:
        n = ov["shared"] or 1
        log(f"  overlap check, game date {ov['date']}, vs live pull {ov['live_pull']} raw file: "
            f"{ov['snapshot_rows']} snapshot rows, {ov['live_rows']} live rows, {ov['shared']} shared")
        log(f"    ratings identical on {ov['ratings_identical_rows']} of {ov['shared']} shared rows "
            f"({100 * ov['ratings_identical_rows'] / n:.1f}%)")
        for f in OVERLAP_FIELDS:
            log(f"    {f:<6} equal on {ov[f]} of {ov['shared']} ({100 * ov[f] / n:.1f}%)")
    # do past snapshots carry past teams?
    if movers and rep["movers"]:
        o_id, o_game, n_id, n_game = mover_span
        log(f"  team check: {len(movers)} players changed org between live pulls {o_id} (game date {o_game}) "
            f"and {n_id} (game date {n_game}). Their org in each snapshot:")
        for d in sorted(rep["movers"]):
            old, new, other = rep["movers"][d]
            tot = old + new + other
            tag = ""
            if tot and o_game and d <= o_game:
                tag = (" -> PAST teams" if old > 0.6 * tot else " -> TODAY's teams" if new > 0.6 * tot
                       else " -> mixed")
            log(f"    {d}: {tot} found; old org {old}, new org {new}, other {other}{tag}")
    dates = sorted(rep["orgs"])
    if len(dates) >= 2:
        log("  org / team / level / league changes between consecutive snapshots (players in both):")
        for d0, d1 in zip(dates, dates[1:]):
            a, b = rep["orgs"][d0], rep["orgs"][d1]
            both = [p for p in b if p in a]
            ch = [sum(1 for p in both if a[p][i] != b[p][i]) for i in range(4)]
            log(f"    {d0} -> {d1}: {len(both)} players; org changed {ch[0]}, team {ch[1]}, "
                f"level (LgLvl) {ch[2]}, league {ch[3]}")
        if all(sum(1 for p in rep["orgs"][d1] if p in rep["orgs"][d0]
                   and rep["orgs"][d0][p] != rep["orgs"][d1][p]) == 0 for d0, d1 in zip(dates, dates[1:])):
            log("    no team or level changed across any snapshot: the snapshots most likely carry "
                "TODAY's team and level, not the past ones")


if __name__ == "__main__":
    sys.exit(main())
