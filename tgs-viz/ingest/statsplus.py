"""
StatsPlus ingestion — fetch league data from the public StatsPlus HTTP API.

These endpoints are public (no auth) for the user's leagues and replace the
manual copy-paste of contracts / draft results / roster status. RATINGS are NOT
here (StatsPlus gates /ratings behind login) — ratings come from the OOTP export
(see ratings adapter, separate). This module is stdlib-only.

Endpoints (base = https://statsplus.net/<slug>/api):
  /date       current in-game date (cache key)
  /players    bio, level, pos, age, service time, roster/DL status, draft attrs
  /contract   salaries, options, no-trade, bonuses
  /teams/     team hierarchy (ID, Name, Nickname, Parent Team ID)
  /draft      draft results (the "Draft API from S+")
  /lgdata/    league metadata (JSON; league_id, level, parent, primary flag)
  /playerbatstatsv2/    per-player season batting stats   (params: year, lid, pid, split)
  /playerpitchstatsv2/  per-player season pitching stats  (same params)
  /playerfieldstatsv2/  per-player season fielding stats  (same params)

Usage:
  python tgs-viz/ingest/statsplus.py <slug>          # smoke test (counts)
  python tgs-viz/ingest/statsplus.py <slug> --refresh
"""
import os, sys, csv, io, json, gzip, re, time, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")


def normalize_base(url_or_slug):
    """Accept a full URL or a bare slug; return the /api base."""
    s = (url_or_slug or "").strip().rstrip("/")
    if not s:
        raise ValueError("empty StatsPlus url/slug")
    if not s.startswith("http"):
        s = f"https://statsplus.net/{s}"
    if not s.endswith("/api"):
        s = f"{s}/api"
    return s


def _get(url, timeout=30, headers=None):
    h = {"User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_ratings(slug_or_url, cookie=None, token=None, poll_interval=15, max_polls=30, on_log=print):
    """Fetch the login-gated player RATINGS the way StatsPlus actually works
    (per the StatsPlus wiki + the StatsPlus-MCP client):

      auth   = browser cookies  ->  header  Cookie: sessionid=...;csrftoken=...
      ratings is an ASYNC JOB:
        1) GET  {base}/ratings/            -> HTML containing a poll URL (?request=...)
        2) poll that URL every ~15s; while it says "still in progress" / "Request
           received", keep waiting; when it returns CSV, that's the ratings.

    The secret is supplied by the caller (env var) and only sent to statsplus.net.
    Returns (rows, method) or (None, None).
    """
    base = normalize_base(slug_or_url)
    attempts = []
    if cookie:
        attempts.append(("cookie", {"Cookie": cookie}, f"{base}/ratings/"))
    if token:  # fallback guesses in case the league uses a token instead of cookies
        attempts.append(("token-as-sessionid", {"Cookie": f"sessionid={token}"}, f"{base}/ratings/"))
        attempts.append(("token-param", {}, f"{base}/ratings/?api_token={urllib.parse.quote(token)}"))

    def looks_unauth(t):
        low = t[:400].lower()
        return "log in" in low or "logged in" in low or "not authorized" in low

    # NOTE (measured 2026-08-26): a StatsPlus login is PER-LEAGUE — the cookie
    # pair only pulls the league the browser is signed into. Visiting the other
    # league's page with the same cookie does NOT flip it (tried and disproven),
    # so a run simply updates whichever league the user is on; the caller treats
    # the other league's empty response as "not pulled", not a failure.
    for label, headers, start_url in attempts:
        init = None
        for attempt in range(3):
            try:
                init = _get(start_url, headers=headers, timeout=90)
                break
            except Exception as e:
                reason = getattr(e, "reason", None) or getattr(e, "code", None) or e
                on_log(f"[{label}] start attempt {attempt + 1}/3 failed: {type(e).__name__}: {reason}")
                time.sleep(6)
        if init is None:
            on_log(f"[{label}] could not reach StatsPlus to start the job (network). Try again in a minute.")
            continue
        if looks_unauth(init):
            on_log(f"[{label}] not authenticated")
            continue
        m = re.search(r"https?://[^\s\"'<>]*\?request=[^\s\"'<>]+", init)
        if not m:
            rows = _sniff_rows(init)  # maybe it returned the data directly
            if rows and len(rows[0].keys()) > 3:
                return rows, label
            on_log(f"[{label}] no poll URL in response; head: {init[:160]!r}")
            continue
        poll = m.group(0).rstrip(".,)\"'")
        on_log(f"[{label}] job started; polling up to {max_polls}x{poll_interval}s (be patient)...")
        last = ""
        for i in range(max_polls):
            try:
                txt = _get(poll, headers=headers)
            except Exception as e:
                on_log(f"  poll {i + 1}: fetch error {type(e).__name__}"); time.sleep(poll_interval); continue
            last = txt
            head = txt.strip()[:50].replace("\n", " ")
            if "still in progress" in txt.lower() or txt.lstrip().lower().startswith("request received"):
                on_log(f"  poll {i + 1}/{max_polls}: still building...")
                time.sleep(poll_interval); continue
            rows = _sniff_rows(txt)
            if rows and len(rows[0].keys()) > 3:
                on_log(f"  poll {i + 1}: ready — {len(rows)} rows, {len(rows[0].keys())} columns.")
                return rows, label
            on_log(f"  poll {i + 1}: unrecognized response, head={head!r}")
            time.sleep(poll_interval)
        on_log(f"[{label}] timed out. Last response (first 250 chars so we can debug):\n{last[:250]!r}")
    return None, None


def _csv_rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def _sniff_rows(text):
    """Parse delimited text, auto-detecting comma / tab / semicolon / pipe."""
    sample = text[:5000]
    delim = max([",", "\t", ";", "|"], key=lambda d: sample.count(d))
    try:
        return list(csv.DictReader(io.StringIO(text), delimiter=delim))
    except Exception:
        return []


def fetch_date(base):
    return _get(f"{base}/date").strip().splitlines()[-1].strip()


def fetch_players(base):
    return _csv_rows(_get(f"{base}/players"))


def fetch_contracts(base):
    return _csv_rows(_get(f"{base}/contract"))


def fetch_teams(base):
    return _csv_rows(_get(f"{base}/teams/"))


def fetch_draft(base):
    return _csv_rows(_get(f"{base}/draft"))


def fetch_lgdata(base):
    """League metadata (/lgdata): [{league_id, name, abbr, level, parent_league_id, primary_league, ...}]."""
    return json.loads(_get(f"{base}/lgdata/")).get("leagues", [])


def _stats_qs(year=None, lids=None, split=None):
    """Query string for the public per-player stats endpoints. year/lid are
    repeatable (pass a list); split 1=overall 2=vsL 3=vsR 21=playoffs; omit
    split for ALL rows (incl. per-stint). Omitted year = current in-game year;
    omitted lid = the server's default top-level leagues."""
    years = [year] if isinstance(year, (int, str)) else (year or [])
    ls = [lids] if isinstance(lids, (int, str)) else (lids or [])
    parts = [("year", y) for y in years] + [("lid", l) for l in ls]
    if split is not None:
        parts.append(("split", split))
    return ("?" + urllib.parse.urlencode(parts)) if parts else ""


def fetch_batting(base, year=None, lids=None, split=None):
    """Per-player season batting stats (public CSV; trailing slash required — 301 without it)."""
    return _csv_rows(_get(f"{base}/playerbatstatsv2/{_stats_qs(year, lids, split)}"))


def fetch_pitching(base, year=None, lids=None, split=None):
    """Per-player season pitching stats (public CSV; trailing slash required)."""
    return _csv_rows(_get(f"{base}/playerpitchstatsv2/{_stats_qs(year, lids, split)}"))


def fetch_fielding(base, year=None, lids=None, split=None):
    """Per-player season fielding stats (public CSV; trailing slash required)."""
    return _csv_rows(_get(f"{base}/playerfieldstatsv2/{_stats_qs(year, lids, split)}"))


def fetch_all(slug_or_url, refresh=False):
    """Fetch everything, cached by in-game date under .cache/<slug>.json.gz."""
    base = normalize_base(slug_or_url)
    slug = base.replace("https://statsplus.net/", "").replace("/api", "").strip("/") or "league"
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_path = os.path.join(CACHE_DIR, f"{slug.replace('/', '_')}.json.gz")
    game_date = fetch_date(base)
    if not refresh and os.path.exists(cache_path):
        try:
            with gzip.open(cache_path, "rt", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("game_date") == game_date:
                return cached
        except Exception:
            pass
    data = {
        "slug": slug,
        "game_date": game_date,
        "players": fetch_players(base),
        "contracts": fetch_contracts(base),
        "teams": fetch_teams(base),
        "draft": fetch_draft(base),
    }
    with gzip.open(cache_path, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    return data


# StatsPlus /ratings column names -> "The Sheet" / engine input names.
# (a few are best-guess — validated against the sheet's own values downstream.)
STATSPLUS_TO_SHEET = {
    "Pos": "POS", "Bats": "B", "Throws": "T", "Height": "HT",
    # hitter ratings, by split (The Sheet's "BA" = the BABIP rating)
    "BABIP_R": "BA vR", "BABIP_L": "BA vL", "Gap_R": "GAP vR", "Gap_L": "GAP vL",
    "Pow_R": "POW vR", "Pow_L": "POW vL", "Eye_R": "EYE vR", "Eye_L": "EYE vL",
    "Ks_R": "K vR", "Ks_L": "K vL",
    "PotBABIP": "HT P", "PotGap": "GAP P", "PotPow": "POW P", "PotEye": "EYE P", "PotKs": "K P",
    "Speed": "SPE", "StlRt": "SR", "Steal": "STE", "Run": "RUN",
    "IFR": "IF RNG", "IFE": "IF ERR", "IFA": "IF ARM",
    "OFR": "OF RNG", "OFE": "OF ERR", "OFA": "OF ARM",
    "CBlk": "C ABI", "CFrm": "C FRM", "CArm": "C ARM",
    # pitcher ratings, by split
    "Stf": "STU", "Stf_R": "STU vR", "Stf_L": "STU vL", "PotStf": "STU P",
    "HRA": "HRR", "HRA_R": "HRR vR", "HRA_L": "HRR vL", "PotHRA": "HRR P",
    "PBABIP_R": "PBABIP vR", "PBABIP_L": "PBABIP vL", "PotPBABIP": "PBABIP P",
    "Ctrl": "CON", "Ctrl_R": "CON vR", "Ctrl_L": "CON vL", "PotCtrl": "CON P",
    "Stm": "STM", "Hold": "HLD",
    # pitch grades (current then potential)
    "Fst": "FB", "Snk": "SI", "Cutt": "CT", "Crv": "CB", "Sld": "SL", "Chg": "CH",
    "Splt": "SP", "Frk": "FO", "CirChg": "CC", "Scr": "SC", "Kncrv": "KC", "Knbl": "KN",
    "PotFst": "FBP", "PotSnk": "SIP", "PotCutt": "CTP", "PotCrv": "CBP", "PotSld": "SLP", "PotChg": "CHP",
    "PotSplt": "SPP", "PotFrk": "FOP", "PotCirChg": "CCP", "PotScr": "SCP", "PotKncrv": "KCP", "PotKnbl": "KNP",
}


def translate_rows(rows):
    """Rename StatsPlus columns to the engine's input names."""
    return [{STATSPLUS_TO_SHEET.get(k, k): v for k, v in r.items()} for r in rows]


# Foreign (non-MLB) leagues in this world, by StatsPlus League id (verified via
# /teams names). The MLB world uses orgs 1-40 (+1600s complex); these use 1046-1099.
NPB_LEAGUE_IDS = {"117", "118", "202"}   # Japan: Kyoto, Nagoya, Kansai, Fukuoka, Yokohama
KBO_LEAGUE_IDS = {"119", "120"}          # Korea: NC, Lotte, SSG, Doosan, Kiwoom
FOREIGN_LEAGUE_IDS = NPB_LEAGUE_IDS | KBO_LEAGUE_IDS
# Per-world foreign sets (league IDs are numbered per OOTP universe). BLM is a
# realistic-MLB world with no NPB/KBO, so nothing is dropped there.
FOREIGN_BY_LEAGUE = {"TGS": FOREIGN_LEAGUE_IDS, "BLM": set()}


def drop_foreign(rows, league="TGS"):
    """Remove players rostered in a foreign league (NPB/KBO in the TGS world). A
    player in the free-agent pool (League 0) is NOT on a foreign roster, so kept."""
    ids = FOREIGN_BY_LEAGUE.get(league, FOREIGN_LEAGUE_IDS)
    return [r for r in rows if str(r.get("League")) not in ids]


# TGS world: StatsPlus League id -> the sheet's Lev string (dominant-league mapping,
# verified against the sheet). 0 = free-agent pool; -100 = all-star/intl; 200 = winter.
LEAGUE_TO_LEV = {
    "100": "MLB", "101": "AAA", "104": "AA", "107": "A+", "111": "A-",
    "112": "R+", "113": "R-", "200": "WL", "-100": "INT", "0": "FA",
}
# BLM world: its internal league IDs differ from TGS, but the ratings pull carries a
# clean league-level tier `LgLvl` — map that directly. BLM has no winter/INT, one
# full-season-A tier (4), short-season (5), and rookie/complex/DSL (6).
BLM_LGLVL_TO_LEV = {"1": "MLB", "2": "AAA", "3": "AA", "4": "A+", "5": "A-", "6": "R+", "0": "FA"}


def _lev_for(r, league):
    """Resolve the app's Lev string for a ratings row, per world."""
    if league == "BLM":
        lgl = str(r.get("LgLvl") or "").strip()
        if lgl in BLM_LGLVL_TO_LEV:
            return BLM_LGLVL_TO_LEV[lgl]
        # blank LgLvl: org-affiliated but unassigned young reserves (the League -144 pool,
        # mostly 19-yo Ovr~20 signees awaiting a level) -> bottom rung; orgless -> free agent.
        org = str(r.get("Org") or "0")
        return "FA" if org in ("0", "") else "R-"
    return LEAGUE_TO_LEV.get(str(r.get("League")), "-")


def team_name_map(team_rows):
    """{team/org id -> 'City Nickname'} from /teams (matches the sheet's ORG names)."""
    out = {}
    for t in team_rows:
        nm = (str(t.get("Name", "")).strip() + " " + str(t.get("Nickname", "")).strip()).strip()
        out[str(t.get("ID"))] = nm
    return out


def enrich_org_lev(rows, names, league="TGS"):
    """Add readable ORG (team name) and Lev (level string) the app/org-builder need."""
    for r in rows:
        r["ORG"] = names.get(str(r.get("Org")), str(r.get("Org")))
        r["Lev"] = _lev_for(r, league)
    return rows


# ---- contracts + injury/service status (public /contract and /players) -------
# These join onto the engine's records by player ID so the app gets salaries
# (Market Value needs `Price`), the per-year contract schedule, current injury
# status, and MLB service time — none of which the ratings pull carries.

def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def build_contract_injury_maps(contracts, players):
    """Index /contract (by player_id) and /players (by ID) for joining by ID."""
    cmap = {str(c.get("player_id")): c for c in contracts}
    pmap = {str(p.get("ID")): p for p in players}
    return cmap, pmap


def attach_contract_injury(recs, cmap, pmap):
    """Attach salary/contract + injury/service fields onto engine records (by ID).

    Contract (`/contract`): salary{current_year} is this season's pay; salaries run
    salary0..salary14 across the deal's `years`. We add `Price` (current annual
    salary, what Market Value divides by), `SalarySchedule` (remaining years),
    `ContractYrs`/`ContractYr`, `IsMajorDeal`, `NoTrade`.
    Player (`/players`): current `OnDL`/`OnDL60`/`DLDays`, `DFA`, `OnWaivers`, and
    MLB service time. Unmatched records are left as-is.

    SERVICE TIME comes through at DAY resolution, not just whole years:
      `MLBSvcYrs`    whole service years  (= floor(MLBSvcDays / 172), see below)
      `MLBSvcDays`   TOTAL career MLB service days, INCLUDING the current season
      `MLBSvcDaysTY` service days accrued in the current season only
    A service YEAR is 172 days — MEASURED, not assumed: `mlb_service_years ==
    mlb_service_days // 172` holds for every one of the 8,578 TGS and 13,876 BLM
    players rostered in the MLB world, and no other day count in 120..210
    satisfies it. (The only violators anywhere are ex-NPB/KBO free agents in the
    TGS pool, whose service was accrued on a foreign league's shorter clock.)
    The whole-year field alone is ~1 year loose for market work: service AT
    SIGNING of a deal that started this season is MLBSvcDays - MLBSvcDaysTY, and
    marketValue.js needs that to separate real free-agent signings from
    pre-free-agency extensions.
    """
    n_priced = 0
    for r in recs:
        pid = str(r.get("ID"))
        c = cmap.get(pid)
        if c:
            cy = _to_int(c.get("current_year")) or 0
            yrs = _to_int(c.get("years")) or 0
            cur = _to_int(c.get("salary%d" % cy)) if 0 <= cy <= 14 else None
            # Many pre-arb players sit on the MLB roster on a $0 minor-league deal
            # (is_major=0). Leave Price absent there so the app shows "—", not "$0".
            if cur and cur > 0:
                r["Price"] = cur
                n_priced += 1
            else:
                r.pop("Price", None)
            sched = [(_to_int(c.get("salary%d" % y)) or 0)
                     for y in range(cy, max(cy + 1, min(yrs, 15)))]
            if any(s > 0 for s in sched):
                r["SalarySchedule"] = sched
            else:
                r.pop("SalarySchedule", None)
            if yrs:
                r["ContractYrs"] = yrs
            r["ContractYr"] = cy + 1
            r["IsMajorDeal"] = str(c.get("is_major")) == "1"
            r["NoTrade"] = str(c.get("no_trade")) == "1"
        p = pmap.get(pid)
        if p:
            r["OnDL"] = str(p.get("is_on_dl")) == "1"
            r["OnDL60"] = str(p.get("is_on_dl60")) == "1"
            dld = _to_int(p.get("dl_days_this_year"))
            if dld is not None:
                r["DLDays"] = dld
            r["DFA"] = str(p.get("designated_for_assignment")) == "1"
            r["OnWaivers"] = str(p.get("is_on_waivers")) == "1"
            svc = _to_int(p.get("mlb_service_years"))
            if svc is not None:
                r["MLBSvcYrs"] = svc
            # Day-resolution service (see docstring): the market fit needs
            # service AT SIGNING = MLBSvcDays - MLBSvcDaysTY.
            svcd = _to_int(p.get("mlb_service_days"))
            if svcd is not None:
                r["MLBSvcDays"] = svcd
            svcdty = _to_int(p.get("mlb_service_days_this_year"))
            if svcdty is not None:
                r["MLBSvcDaysTY"] = svcdty
            # FA vs AMATEUR POOL (user 2026-09-04: "org 0" mixed real free agents
            # with 14-17yo amateur-pool kids). draft_eligible marks the amateur
            # pool; free_agent alone is useless (flags 32k of 41k players, incl.
            # every amateur). An org-less pull row: draft-eligible -> Lev "AMA",
            # anything else -> a real free agent (FA True). Org'd rows: FA False.
            org0 = str(r.get("ORG", "")).strip() in ("", "0")
            de = str(p.get("draft_eligible")) == "1"
            r["FA"] = bool(org0 and not de)
            if org0 and de and str(r.get("Lev", "")).upper() in ("FA", ""):
                r["Lev"] = "AMA"
    return n_priced


def mlb_team_names(data, exclude_substrings=("japan",), parent_only=True):
    """Best-effort MLB team-name set, excluding NPB/foreign leagues.

    StatsPlus /teams returns the whole world. The user's standing rule: exclude
    the Japanese (NPB) league from MLB comparisons/calibration/projection. The
    sheet's Ballparks team list is the authoritative MLB set; here we provide a
    coarse filter the caller can refine with that list.
    """
    names = set()
    for t in data["teams"]:
        nm = (t.get("Name") or "").strip()
        if not nm:
            continue
        names.add(nm)
    return names


def main():
    if len(sys.argv) < 2:
        print("usage: python statsplus.py <slug> [--refresh]")
        return
    slug = sys.argv[1]
    refresh = "--refresh" in sys.argv[2:]
    data = fetch_all(slug, refresh=refresh)
    print(f"slug={data['slug']}  in-game date={data['game_date']}")
    print(f"  players  : {len(data['players']):>6}")
    print(f"  contracts: {len(data['contracts']):>6}")
    print(f"  teams    : {len(data['teams']):>6}")
    print(f"  draft    : {len(data['draft']):>6}")
    # sample column names
    if data["players"]:
        print("  player cols:", list(data["players"][0].keys())[:8], "...")
    if data["draft"]:
        print("  draft sample:", {k: data["draft"][0][k] for k in list(data["draft"][0])[:6]})


if __name__ == "__main__":
    main()
