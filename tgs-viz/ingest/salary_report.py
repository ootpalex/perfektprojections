"""
StatsPlus team salary reports: OOTP's own arbitration projections, opt-outs and retained salary.

WHY THIS FILE EXISTS. /contract carries the signed years of a deal and its option flags. It does not
carry what OOTP projects a player will earn in his arbitration years, the opt-out clauses, or salary a
club keeps paying after a trade or release. Those exist only on the per-team salary report page that
StatsPlus serves as HTML:

    <league root>/reports/news/html/teams/team_<team id>_player_salary_report.html

This module reads those pages, parses them, and attaches the result to the refresh pull's records as
NEW keys. It changes no existing key. Stdlib only. Audit and counts: docs/phase3/salary_report.md.

HOW A PAGE IS READ (his statsplus.py rules, nothing bypassed):
  - one request at a time, a short pause between live requests (PAGE_GAP_S);
  - statsplus._open(url, token=False, stay_on=<api base>): no token is sent (the dashboard's saved
    reports were read without one), the host and every redirect must stay on statsplus.net (or the test
    mock) else OffSiteError and nothing is sent, replies that are not a page raise StatsPlusRefused;
  - statsplus._cached: a page is read at most once per team per in-game day (/date is the key) and is
    at most 6 hours old. The RAW HTML is cached, so a parser fix costs no request.
  - a refusal or an off-site error stops the run at once; two other failures in a row stop it too.

NEW RECORD KEYS (all optional; absent = the player is on no MLB team page, or reports were not read):
  SalaryReport      {year (str): cell}, every year the page shows something other than FA.
                    cell = {"salary": dollars as printed (rounded to $0.1M above $1M) or None,
                            "type": signed | arb | arb_uncertain | milb | milc | team_option |
                                    player_option | vesting_option | opt_out | retained | unparsed,
                            "guaranteed": True when the cell is not italic,
                            "ann": the page's mark without parentheses ("A", "A*", "A#", "*", "T",
                                   "P", "V", "O", "R"), only on marked cells,
                            "raw": the unreadable text (<= 40 chars), only for "unparsed"}
  SalaryReportSpan  [first year, last year] of the page's year columns. A year inside the span with no
                    entry in SalaryReport is shown as FA.
  ArbProjection     {"yr", "salary", "uncertain", "ann", "n"}: the page's first arbitration cell
                    ((A) certain; (A*) and (A#) uncertain); n = arbitration cells on the page.
  OptOutYrs         [year, ...] of "(O)" cells, only when there is one.
  RetainedYrs       [year, ...] of "(R)" cells, only when there is one.
No arbitration formula, no service-time rule and no Super Two rule live here: every number is the
page's own.

    python tgs-viz/ingest/salary_report.py --saved <leagues/SSB/.statsplus_cache.json.gz>
        offline summary of the dashboard's saved parsed reports (no request)
"""
import gzip
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

REPORT_PATH = "reports/news/html/teams/team_{team_id}_player_salary_report.html"
PAGE_GAP_S = 0.5            # courtesy pause before each live request after the first (an assumption)
MAX_CONSECUTIVE_FAILURES = 2
RAW_MAX = 40

NEW_KEYS = ("SalaryReport", "SalaryReportSpan", "ArbProjection", "OptOutYrs", "RetainedYrs")

# ---- parser (the regexes are the dashboard's model/src/salary_report.py, which produced its saved
# results from real pages; the italic test is the one deliberate change, see docs section 6) -------------
_TH_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_LINK_RE = re.compile(r'href="[^"]*/player_(\d+)\.html"[^>]*>([^<]+)</a>', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ITALIC_RE = re.compile(r"<(?:i|em)(?=[\s>])", re.IGNORECASE)
_YEAR_RE = re.compile(r"^\d{4}$")

# (page suffix, cell type); (A*) and (A#) are tested before (A)
ANNOTATIONS = (
    ("(A*)", "arb_uncertain"), ("(A#)", "arb_uncertain"), ("(A)", "arb"), ("(*)", "milb"),
    ("(T)", "team_option"), ("(P)", "player_option"), ("(V)", "vesting_option"),
    ("(O)", "opt_out"), ("(R)", "retained"),
)
ARB_TYPES = ("arb", "arb_uncertain")
# A cell can carry several marks in one pair of brackets, comma-separated (live SSB pages: "(P,O)" a
# player option that is also an opt-out, "(*auto)" a minor-league salary marked auto). Each known
# token maps to a type; an unknown token is kept as written in "marks", never interpreted.
MARK_TYPES = {"A*": "arb_uncertain", "A#": "arb_uncertain", "A": "arb", "*": "milb", "T": "team_option",
              "P": "player_option", "V": "vesting_option", "O": "opt_out", "R": "retained"}
# the cell's one "type" when it carries several marks: the contract term first
TYPE_ORDER = ("team_option", "player_option", "vesting_option", "arb_uncertain", "arb", "milb",
              "opt_out", "retained")
_MULTI_RE = re.compile(r"^(.*?)\(([^()]+)\)$")


def _mark_tokens(inner):
    """'P,O' -> ['P', 'O']; '*auto' -> ['*', 'auto'] (a leading '*' is the minor-league mark)."""
    out = []
    for tok in (t.strip() for t in inner.split(",")):
        if tok.startswith("*") and len(tok) > 1 and tok not in MARK_TYPES:
            out += ["*", tok[1:]]
        elif tok:
            out.append(tok)
    return out


def parse_salary_text(s):
    """Dollars from page text such as '$3.2M', '$804K' or '1,250,000'; None when it is not a number."""
    clean = (s or "").replace("$", "").replace(",", "").replace("\xa0", " ").strip().lower()
    if not clean:
        return None
    try:
        if clean.endswith("m"):
            return int(round(float(clean[:-1]) * 1_000_000))
        if clean.endswith("k"):
            return int(round(float(clean[:-1]) * 1_000))
        return int(round(float(clean)))
    except ValueError:
        return None


def parse_cell(raw_html):
    """One salary cell -> {"salary", "type", "guaranteed"[, "ann"][, "raw"]}. Empty or a dash is 'fa';
    the text 'MiLC' is 'milc'; text with no mark and no readable dollar amount is 'unparsed' (the
    dashboard calls it 'signed'; 23 such cells exist in its saved SSB reports)."""
    italic = bool(_ITALIC_RE.search(raw_html))
    text = _TAG_RE.sub("", raw_html).replace("&nbsp;", " ").strip()
    if not text or text in ("—", "-", "–"):
        return {"salary": None, "type": "fa", "guaranteed": False}
    if text == "MiLC":
        return {"salary": None, "type": "milc", "guaranteed": False}
    for suffix, ctype in ANNOTATIONS:
        if text.endswith(suffix):
            return {"salary": parse_salary_text(text[: -len(suffix)]), "type": ctype,
                    "guaranteed": not italic, "ann": suffix[1:-1]}
    m = _MULTI_RE.match(text)
    if m:
        toks = _mark_tokens(m.group(2))
        marks = [MARK_TYPES.get(t, t) for t in toks]
        known = [t for t in TYPE_ORDER if t in marks]
        amount = parse_salary_text(m.group(1))
        if known and amount is not None:
            return {"salary": amount, "type": known[0], "guaranteed": not italic, "ann": m.group(2),
                    "marks": marks}
    salary = parse_salary_text(text)
    if salary is None:
        return {"salary": None, "type": "unparsed", "guaranteed": not italic, "raw": text[:RAW_MAX]}
    return {"salary": salary, "type": "signed", "guaranteed": not italic}


def parse_report_html(html):
    """A salary report page -> {"span": [first, last] or None, "players": {id: {name, pos, years}}}.
    years = {int year: cell} for every year column (FA cells included). A page without year column
    headers is not a salary report: span None and no players."""
    year_cols = []
    for m in _TH_RE.finditer(html):
        text = _TAG_RE.sub("", m.group(1)).strip()
        if _YEAR_RE.match(text):
            year_cols.append(int(text))
    if not year_cols:
        return {"span": None, "players": {}}
    players = {}
    for row in _TR_RE.finditer(html):
        row_html = row.group(1)
        link = _LINK_RE.search(row_html)
        if not link:
            continue
        tds = [m.group(1) for m in _TD_RE.finditer(row_html)]
        if not tds:
            continue
        years = {}
        for i, cell in enumerate(tds[3:]):          # the first three cells are not salary years
            if i >= len(year_cols):
                break
            years[year_cols[i]] = parse_cell(cell)
        players[link.group(1)] = {"name": link.group(2).strip(), "pos": _TAG_RE.sub("", tds[0]).strip(),
                                  "years": years}
    return {"span": [min(year_cols), max(year_cols)], "players": players}


# ---- which teams ---------------------------------------------------------------------------------------

def mlb_team_ids(rows, team_rows=None):
    """Ids of the league's MLB clubs: the distinct 'Org' of the ratings rows whose 'Lev' is 'MLB'
    (the pull has them already; /teams has no level column). With team_rows (/teams), only ids that
    /teams lists with 'Parent Team ID' 0 are kept. Sorted numerically."""
    ids = {str(r.get("Org")).strip() for r in rows if r.get("Lev") == "MLB" and str(r.get("Org", "")).strip()}
    ids.discard("0")
    if team_rows is not None:
        top = {str(t.get("ID")).strip() for t in team_rows if str(t.get("Parent Team ID", "0")).strip() == "0"}
        ids &= top
    return sorted(ids, key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else 0, s))


# ---- fetching ------------------------------------------------------------------------------------------

def report_base(api_base):
    """The league root a report page hangs off: the API base without its trailing /api."""
    b = (api_base or "").rstrip("/")
    return b[:-4] if b.endswith("/api") else b


def report_url(api_base, team_id, base_override=None):
    return f"{(base_override or report_base(api_base)).rstrip('/')}/{REPORT_PATH.format(team_id=team_id)}"


class PageResult:
    """The outcome of reading the pages: players (id -> entry), span, and the load numbers."""

    def __init__(self):
        self.players = {}
        self.span = None
        self.fetched = 0          # pages requested from StatsPlus this run
        self.reused = 0           # pages served from the date-keyed cache
        self.failed = []          # [(team id, short reason)]
        self.stopped = None       # why the run stopped early, or None
        self.refusal = None       # the StatsPlusRefused / OffSiteError that stopped it, if any

    @property
    def pages(self):
        return self.fetched + self.reused


def _read_page(S, api_base, team_id, url, gap_s, sleep, state, cache, fresh):
    """The raw HTML of one page through the date-keyed cache; validated before it is saved."""
    def fetch():
        if state["live"] and gap_s:
            sleep(gap_s)                               # one request in flight, spaced out
        state["live"] += 1
        state["did_fetch"] = True
        text, _sent = S._open(url, token=False, stay_on=api_base)
        if parse_report_html(text)["span"] is None:    # login page, refusal text, error page, ...
            raise S._refused_reply(text, "a salary report page", url, False)
        return text
    state["did_fetch"] = False
    return S._cached(api_base, url, fetch, cache, fresh)


def fetch_reports(api_base, team_ids, *, cache=True, fresh=False, report_base_url=None,
                  gap_s=PAGE_GAP_S, sleep=time.sleep, S=None):
    """Read and parse the salary report of each team id, one request at a time. Returns a PageResult.
    cache=True reuses a page read earlier the same in-game day (under 6 hours old); fresh=True reads
    now and saves. Never raises for a failed page: it records the failure and stops when StatsPlus
    refuses, when the address leaves statsplus.net, or after two failures in a row."""
    if S is None:
        import statsplus as S
    out = PageResult()
    state = {"live": 0, "did_fetch": False}
    run = 0
    for tid in team_ids:
        url = report_url(api_base, tid, report_base_url)
        try:
            html = _read_page(S, api_base, tid, url, gap_s, sleep, state, cache, fresh)
        except (S.StatsPlusRefused, S.OffSiteError) as e:
            out.failed.append((tid, getattr(e, "kind", type(e).__name__)))
            out.stopped = S.redact(str(e)).splitlines()[0][:160] if str(e) else type(e).__name__
            out.refusal = e
            break
        except Exception as e:                           # 404, timeout, ... : count it, maybe go on
            out.failed.append((tid, type(e).__name__))
            run += 1
            if run >= MAX_CONSECUTIVE_FAILURES:
                out.stopped = (f"{run} failures in a row ({type(e).__name__}: "
                               f"{(S.redact(str(e)).splitlines() or [''])[0][:120]})")
                break
            continue
        run = 0
        out.fetched += state["did_fetch"]
        out.reused += not state["did_fetch"]
        page = parse_report_html(html)
        out.players.update(page["players"])
        if page["span"]:
            out.span = page["span"] if out.span is None else [min(out.span[0], page["span"][0]),
                                                              max(out.span[1], page["span"][1])]
    return out


# ---- attaching -----------------------------------------------------------------------------------------

def entry_keys(entry, span):
    """The record keys for one parsed player entry ({name, pos, years}) and the page span."""
    cells = {y: c for y, c in sorted(entry["years"].items()) if c["type"] != "fa"}
    keys = {"SalaryReport": {str(y): dict(c) for y, c in cells.items()},
            "SalaryReportSpan": list(span)}
    arb = [(y, c) for y, c in cells.items() if c["type"] in ARB_TYPES]
    if arb:
        y, c = arb[0]
        keys["ArbProjection"] = {"yr": y, "salary": c["salary"], "uncertain": c["type"] == "arb_uncertain",
                                 "ann": c.get("ann"), "n": len(arb)}
    outs = [y for y, c in cells.items() if c["type"] == "opt_out" or "opt_out" in (c.get("marks") or ())]
    if outs:
        keys["OptOutYrs"] = outs
    kept = [y for y, c in cells.items() if c["type"] == "retained" or "retained" in (c.get("marks") or ())]
    if kept:
        keys["RetainedYrs"] = kept
    return keys


def attach_salary_reports(recs, players, span):
    """Add the NEW_KEYS to engine records by ID. players = PageResult.players. Records whose ID is on
    no page get nothing (a re-run also clears stale keys). Returns the number of records that gained keys."""
    n = 0
    for r in recs:
        for k in NEW_KEYS:
            r.pop(k, None)
        entry = players.get(str(r.get("ID"))) if span else None
        if entry:
            r.update(entry_keys(entry, span))
            n += 1
    return n


# ---- offline summary of the dashboard's saved parsed reports --------------------------------------------

def summarize_saved(path, out=print):
    """Counts over the dashboard's saved parsed reports (leagues/<slug>/.statsplus_cache.json.gz, key
    'salary_reports'). No request. Prints and returns the summary dict."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    reports = doc.get("salary_reports") or {}
    types, players_with, first_off, n_arb = {}, {}, {}, {}
    uncertain_first = {"arb": 0, "arb_uncertain": 0}
    game_year = int(str(doc.get("game_date", "0000"))[:4]) or None
    for e in reports.values():
        seen = set()
        cells = sorted(((int(y), c) for y, c in e["years"].items()), key=lambda t: t[0])
        arb = [(y, c) for y, c in cells if c["type"] in ARB_TYPES]
        for _y, c in cells:
            types[c["type"]] = types.get(c["type"], 0) + 1
            seen.add(c["type"])
        for t in seen:
            players_with[t] = players_with.get(t, 0) + 1
        if arb:
            y, c = arb[0]
            first_off[y - game_year] = first_off.get(y - game_year, 0) + 1
            uncertain_first[c["type"]] += 1
            n_arb[len(arb)] = n_arb.get(len(arb), 0) + 1
    summary = {"game_date": doc.get("game_date"), "players": len(reports), "cells_by_type": types,
               "players_with_type": players_with, "first_arb_year_minus_game_year": first_off,
               "first_arb_cell_certain_vs_uncertain": uncertain_first, "arb_cells_per_player": n_arb}
    out(json.dumps(summary, indent=1, sort_keys=True))
    return summary


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--saved":
        summarize_saved(sys.argv[2])
    else:
        print(__doc__)
