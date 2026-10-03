"""
StatsPlus ingestion: fetch league data from the StatsPlus HTTP API.

Base = https://statsplus.net/<slug>/api (slugs tgs and blm). This module is
stdlib-only.

LOGIN. StatsPlus is moving its endpoints behind a per-team API token. A token
belongs to one team in one league, so TGS and BLM each have their own.
statsplus_token.py reads them from StatsPlus Tokens.txt in the project folder
(gitignored). _get sends them as follows:
  - Every request to https statsplus.net (or a subdomain) gets ?token=<the
    token of that URL's league> when one is saved. The league is the path part
    before /api. A request that carries a token must stay on the site through
    every redirect, else OffSiteError and nothing is sent.
  - A saved token never goes to another host, over http, or to this machine.
  - No saved token: the request goes out as before, with no login.
  - A local test base (127.0.0.1) takes its token only from the environment
    (STATSPLUS_TEST_TOKEN_<SLUG> or STATSPLUS_TEST_TOKEN), never from the file.
  - /ratings tries the token first, then the browser cookie pair
    (Cookie: sessionid=...;csrftoken=...) as a fallback.
  - Log lines and error messages never show a token: redact() replaces every
    known token with ***.

REFUSALS. StatsPlus reports most errors as HTTP 200 text ("API token has
expired", "Request too soon, wait N seconds ..."). Every fetch helper raises
StatsPlusRefused(kind, message) when StatsPlus refuses or sends something that
is not the data (an HTML page, a date that is not a date, a CSV without the
columns the callers need). Kinds: token_invalid, token_expired,
login_required, too_soon, not_enabled, blocked (HTTP 401/403/429), not_data.
It subclasses Exception, so existing except blocks still catch it, and
str(e) is a plain-English message. A reply without a column the callers only
read when present prints one WARNING and goes on. fetch_ratings returns
(None, None) on failure; ratings_failure() says why.

REPEAT READS. cache=True on a fetch helper reuses the saved reply while the
league's /date is unchanged and the copy is younger than 6 hours. fresh=True
fetches now and saves the reply for later cache=True reads. The default
(neither) fetches now and saves nothing, as before. When /date is refused or
not reachable, both just fetch the endpoint (no reuse, nothing saved). Files
go to tgs-viz/ingest/.cache/sp/<slug>/ (STATSPLUS_CACHE_DIR overrides the
folder). fetch_date keeps each league's date (or its failure) in memory for
60 s.

TESTS. STATSPLUS_TEST_BASE_URL=http://127.0.0.1:<port> points normalize_base(slug)
at a local mock (only an address on this machine is honored).

Endpoints (base = https://statsplus.net/<slug>/api):
  /date       current in-game date (cache key)
  /players    bio, level, pos, age, service time, roster/DL status, draft attrs
  /contract   salaries, options, no-trade, bonuses
  /teams/     team hierarchy (ID, Name, Nickname, Parent Team ID)
  /draft      draft results (the "Draft API from S+")
  /draftpool/ the IDs of this year's draft class (shape not yet seen live; see fetch_draftpool)
  /lgdata/    league metadata (JSON; league_id, level, parent, primary flag)
  /playerbatstatsv2/    per-player season batting stats   (params: year, lid, pid, split)
  /playerpitchstatsv2/  per-player season pitching stats  (same params)
  /playerfieldstatsv2/  per-player season fielding stats  (same params)
  /ratings/   player ratings, an async job (see fetch_ratings)
  /tokencheck/?token=   the team ID a token belongs to (see tokencheck)

Usage:
  python tgs-viz/ingest/statsplus.py <slug>          # smoke test (counts)
  python tgs-viz/ingest/statsplus.py <slug> --refresh
"""
import os, sys, csv, io, json, gzip, hashlib, ipaddress, re, time
import urllib.error, urllib.request, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")

try:
    import statsplus_token as _TOK
except ImportError:          # loaded by path, without ingest/ on sys.path
    import importlib.util
    _spec = importlib.util.spec_from_file_location("statsplus_token", os.path.join(HERE, "statsplus_token.py"))
    _TOK = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_TOK)
    sys.modules.setdefault("statsplus_token", _TOK)


def _site_base():
    """https://statsplus.net, or the local mock named by STATSPLUS_TEST_BASE_URL
    (tests only; honored only for an address on this machine)."""
    t = os.environ.get("STATSPLUS_TEST_BASE_URL", "").strip().rstrip("/")
    if t and _is_local(t + "/"):
        return t
    return "https://statsplus.net"


def normalize_base(url_or_slug):
    """Accept a full URL or a bare slug; return the /api base."""
    s = (url_or_slug or "").strip().rstrip("/")
    if not s:
        raise ValueError("empty StatsPlus url/slug")
    if not s.startswith("http"):
        s = f"{_site_base()}/{s}"
    if not s.endswith("/api"):
        s = f"{s}/api"
    return s


class OffSiteError(Exception):
    """A request that carries the login would leave the StatsPlus site."""


SITE_ROOT = "statsplus.net"
_HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*")


def _is_ip(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _site_root(host):
    """The site a base host belongs to. statsplus.net and every subdomain of it
    belong to statsplus.net. Any other base host (only a local test mock) is its
    own site, without a "www." prefix."""
    h = (host or "").lower()
    if h == SITE_ROOT or h.endswith("." + SITE_ROOT):
        return SITE_ROOT
    return h.removeprefix("www.")


def _host_on_site(host, root):
    """True when host is the site root or a subdomain of it. An IP address
    matches only itself."""
    if _is_ip(root) or _is_ip(host):
        return host == root
    return host == root or host.endswith("." + root)


def _port(u):
    return u.port or (443 if u.scheme == "https" else 80)


def site_url(url, base):
    """The URL to connect to when `url` may carry the login of `base`, else None.

    Rules (every request that carries the login, its poll address and every
    redirect):
      - the host is statsplus.net or a subdomain of it (for example
        api.statsplus.net) when base is on statsplus.net; for a local test base,
        the base host or a subdomain of it
      - no '@' in the host part and no backslash anywhere (both can make two
        URL parsers read two different hosts)
      - a plain host name or IP address, http or https, never https -> http
      - the same port as base
    Host and port come from urllib.parse.urlsplit, and the returned URL is
    rebuilt from those parts only, so the connection goes to the host that
    was checked."""
    url, base = str(url or ""), str(base or "")
    if "\\" in url or "\\" in base or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    try:
        ub, uu = urllib.parse.urlsplit(base), urllib.parse.urlsplit(url)
        _port(ub), _port(uu)                        # ValueError on a bad port
    except ValueError:
        return None
    if "@" in uu.netloc or "@" in ub.netloc:
        return None
    if uu.scheme not in ("http", "https") or (ub.scheme == "https" and uu.scheme != "https"):
        return None
    hb, hu = (ub.hostname or "").lower(), (uu.hostname or "").lower()
    if not hb or not hu or not (_is_ip(hu) or _HOST_RE.fullmatch(hu)):
        return None
    if not _host_on_site(hu, _site_root(hb)):
        return None
    if not (_port(ub) == _port(uu) or (ub.port is None and uu.port is None)):
        return None
    netloc = f"[{hu}]" if ":" in hu else hu
    if uu.port is not None:
        netloc += f":{uu.port}"
    return urllib.parse.urlunsplit((uu.scheme, netloc, uu.path or "/", uu.query, ""))


def same_site(url, base):
    """True when url may carry the login of base (see site_url)."""
    return site_url(url, base) is not None


def _host_txt(url):
    """The host of a URL for a message ('?' when it does not parse), tokens
    replaced by *** (a server-supplied host can carry one)."""
    try:
        u = urllib.parse.urlsplit(str(url))
        h = u.netloc.rpartition("@")[2] if "@" in u.netloc else (u.hostname or "")
    except ValueError:
        return "?"
    return _head(h or "?", 80)


# ---- tokens: which request gets which token ----------------------------------

def _slug_of(url):
    """The league slug of a StatsPlus API address (the path part before /api), or None."""
    try:
        parts = urllib.parse.urlsplit(str(url)).path.split("/")
    except ValueError:
        return None
    for i in range(1, len(parts)):
        if parts[i] == "api" and parts[i - 1]:
            s = parts[i - 1].lower()
            return s if re.fullmatch(r"[a-z0-9_-]{1,40}", s) else None
    return None


def _endpoint_of(url):
    """The API name of a StatsPlus address ('players', 'ratings', ...), or None."""
    try:
        parts = [p for p in urllib.parse.urlsplit(str(url)).path.split("/") if p]
    except ValueError:
        return None
    if "api" in parts and parts.index("api") + 1 < len(parts):
        return parts[parts.index("api") + 1][:40]
    return None


def _on_statsplus(url):
    """True when url is https on statsplus.net or a subdomain of it, port 443."""
    try:
        if urllib.parse.urlsplit(str(url)).scheme != "https":
            return False
    except ValueError:
        return False
    return site_url(url, f"https://{SITE_ROOT}/") is not None


def _is_local(url):
    """True when url is http(s) on this machine (a local test mock)."""
    try:
        u = urllib.parse.urlsplit(str(url))
        host = (u.hostname or "").lower()
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or "@" in u.netloc or "\\" in str(url):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _test_token(slug):
    v = (os.environ.get(f"STATSPLUS_TEST_TOKEN_{(slug or '').upper()}")
         or os.environ.get("STATSPLUS_TEST_TOKEN") or "")
    return v.strip() or None


def token_for_url(url):
    """The token _get adds to url on its own, or None: the saved token of the
    URL's league for https statsplus.net, a test token from the environment for
    a local test base, nothing for any other address."""
    slug = _slug_of(url)
    if not slug:
        return None
    if _on_statsplus(url):
        return _TOK.token_for(slug)
    if _is_local(url):
        return _test_token(slug)
    return None


def has_token(slug_or_url):
    """True when requests to this league will carry a token (see token_for_url)."""
    return token_for_url(normalize_base(slug_or_url) + "/date") is not None


def _pick_token(url, token):
    """The token to send with url. token: None = the automatic one
    (token_for_url); a string = that token; False or "" = none."""
    if token is None:
        return token_for_url(url)
    if token is False or not str(token).strip():
        return None
    if not (_on_statsplus(url) or _is_local(url)):
        raise OffSiteError(f"refused to send a token to {_host_txt(url)}: a token goes only to "
                           f"https {SITE_ROOT}; nothing was sent")
    return str(token).strip()


def _with_token(url, token):
    """url with token=<token> as its only token parameter."""
    u = urllib.parse.urlsplit(url)
    parts = [p for p in u.query.split("&") if p and not p.lower().startswith("token=")]
    parts.append("token=" + urllib.parse.quote(token, safe=""))
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "&".join(parts), ""))


# ---- redaction: no token in any message ---------------------------------------

_EXTRA_SECRETS = set()
_QS_SECRET = re.compile(r"(?i)\b((?:api_)?token=|sessionid=|csrftoken=)[^&;\s\"'<>#]+")
_QS_SECRET_ENC = re.compile(r"(?i)((?:api_)?token%3D)[^&%\s\"'<>#]+")


def add_secret(value):
    """Hide value in every later redact() (a token or cookie value given by a caller)."""
    v = str(value or "").strip()
    if len(v) >= 6:
        _EXTRA_SECRETS.add(v)


def _test_store_off():
    """True in test mode (a local test base) without STATSPLUS_TOKEN_FILE: the
    default token file is then never read, not even for redaction."""
    return (_site_base() != f"https://{SITE_ROOT}"
            and not os.environ.get("STATSPLUS_TOKEN_FILE", "").strip())


def _secrets():
    out = set(_EXTRA_SECRETS)
    if not _test_store_off():
        try:
            out.update(_TOK.all_tokens())
        except Exception:
            pass
    for k, v in os.environ.items():
        if k.startswith("STATSPLUS_TEST_TOKEN") and len(v.strip()) >= 6:
            out.add(v.strip())
    return out


def redact(text):
    """text with every known token (and every token=, sessionid= or csrftoken=
    value) replaced by ***. Use it on any URL or server text that reaches a log
    line or an exception. Case does not matter (a host name in a URL is
    lowercased)."""
    s = "" if text is None else str(text)
    for t in sorted(_secrets(), key=len, reverse=True):
        for v in {t, urllib.parse.quote(t, safe="")}:
            s = re.sub(re.escape(v), "***", s, flags=re.I)
    s = _QS_SECRET.sub(r"\1***", s)
    return _QS_SECRET_ENC.sub(r"\1***", s)


def _scrub(e):
    """e with tokens removed from its text (in place). When that is not
    possible, a ConnectionError with the redacted text."""
    try:
        e.args = tuple(redact(a) if isinstance(a, str) else a for a in e.args)
    except Exception:
        pass
    for attr in ("reason", "msg", "filename", "filename2", "strerror", "url"):
        try:
            v = getattr(e, attr, None)
            if isinstance(v, str):
                setattr(e, attr, redact(v))
            elif isinstance(v, BaseException) and v is not e:
                _scrub(v)
        except Exception:
            pass
    try:
        txt = f"{e} {e!r}"
    except Exception:
        txt = ""
    if redact(txt) != txt:
        return ConnectionError(redact(str(e)))
    return e


# ---- refusals ------------------------------------------------------------------

REFUSAL_KINDS = ("token_invalid", "token_expired", "login_required", "daily_limit", "too_soon",
                 "not_enabled", "blocked", "not_data")
# StatsPlus words for a refusal, checked on short replies only (case-insensitive).
_REFUSAL_TEXT = (
    ("token_expired", re.compile(r"token (?:has )?expired|expired (?:api )?token")),
    ("token_invalid", re.compile(r"invalid (?:or unknown )?(?:api )?token|unknown (?:api )?token"
                                 r"|token (?:is )?(?:invalid|not valid)")),
    # "Past date requests are limited to 5 a day, the next one is available at ..."
    ("daily_limit", re.compile(r"limited to \d+ (?:requests? )?(?:a|per) day|\d+ (?:requests? )?(?:a|per) day")),
    ("too_soon", re.compile(r"too soon|wait \d+ seconds?")),
    ("not_enabled", re.compile(r"not enabled")),
    ("login_required", re.compile(r"logged in|log ?in\b|login required|sign ?in\b|authenticat"
                                  r"|not authori[sz]ed|unauthori[sz]ed|(?:api )?token (?:is )?required"
                                  r"|token missing|missing (?:api )?token|requires? (?:a |an )?(?:api )?token")),
)


def _classify(text):
    """(kind, wait seconds or None) when text is a known StatsPlus refusal, else None."""
    low = " ".join(str(text or "").lower().split())[:1000]
    for kind, rx in _REFUSAL_TEXT:
        if rx.search(low):
            m = re.search(r"wait (\d+) seconds?", low)
            return kind, (int(m.group(1)) if m else None)
    return None


def _lg(league, slug):
    return str(league or (slug or "").upper() or "StatsPlus")


def _why(kind, lg, status=None, wait=None, token_sent=False, cookie_sent=False, message=""):
    """Plain-English reason and fix for a failure kind."""
    if kind == "token_expired":
        return f"the {lg} token has expired. Get a new one from StatsPlus Prefs and paste it into StatsPlus Tokens.txt."
    if kind == "token_invalid":
        return (f"StatsPlus does not know the {lg} token. Copy the Current Token from StatsPlus Prefs "
                f"and paste it into StatsPlus Tokens.txt.")
    if kind == "login_required":
        if token_sent:
            return f"it asked for a login although the {lg} token was sent. Check the token in StatsPlus Tokens.txt."
        if cookie_sent:
            return (f"the browser login did not work for {lg}. Paste the {lg} token into "
                    f"StatsPlus Tokens.txt instead.")
        return f"it now needs a login. Paste the {lg} token into StatsPlus Tokens.txt, then run this again."
    if kind == "daily_limit":
        return (f"StatsPlus allows only a few past-date requests a day for {lg} and today's are used up. "
                f"Run this again tomorrow (StatsPlus said: {message}).")
    if kind == "too_soon":
        return (f"the request came too soon after the last one. Wait {wait} seconds, then run this again."
                if wait else "the request came too soon after the last one. Wait a few minutes, then run this again.")
    if kind == "not_enabled":
        return f"this is not switched on for the {lg} league (StatsPlus said: {message})."
    if kind == "blocked":
        if status == 429:
            return (f"too many requests (HTTP 429). Wait {wait} seconds, then run this again." if wait
                    else "too many requests (HTTP 429). Wait a minute, then run this again.")
        if token_sent:
            return f"HTTP {status}. Check the {lg} token in StatsPlus Tokens.txt."
        return f"HTTP {status}. It may need a login now: paste the {lg} token into StatsPlus Tokens.txt."
    if kind == "not_data":
        tail = "" if token_sent else f" It may need a login now: paste the {lg} token into StatsPlus Tokens.txt."
        return f"it sent something that is not the data ({message}).{tail}"
    if kind == "network":
        return "StatsPlus could not be reached (network). Try again in a minute."
    if kind == "off_site":
        return "StatsPlus sent an address on another site; nothing was sent there."
    if kind == "timed_out":
        return "StatsPlus did not finish the ratings export in time. Try again in a few minutes."
    if kind == "no_login":
        return (f"no StatsPlus token is saved for {lg} and no browser cookie was given. "
                f"Paste the {lg} token into StatsPlus Tokens.txt.")
    return message or kind


class StatsPlusRefused(Exception):
    """StatsPlus refused a request, or sent something that is not the data.

    kind        token_invalid | token_expired | login_required | too_soon |
                not_enabled | blocked (HTTP 401/403/429) | not_data
    message     the server's words or what was wrong, tokens replaced by ***,
                at most 200 characters
    wait        seconds to wait (too_soon, or a 429 with a wait), else None
    status      the HTTP status (200 for a text refusal)
    slug        the league slug of the request ('tgs', 'blm'), or None
    endpoint    the API name ('players', 'ratings', ...), or None
    token_sent  True when the request carried a token
    str(e) is user_message(): a plain-English reason and fix."""

    KINDS = REFUSAL_KINDS

    def __init__(self, kind, message="", wait=None, status=None, slug=None, endpoint=None,
                 token_sent=False, cookie_sent=False):
        self.kind = kind if kind in REFUSAL_KINDS else "not_data"
        self.message = redact(" ".join(str(message or "").split()))[:200]
        self.wait, self.status, self.slug, self.endpoint = wait, status, slug, endpoint
        self.token_sent, self.cookie_sent = bool(token_sent), bool(cookie_sent)
        super().__init__(self.user_message())

    def user_message(self, league=None):
        lg = _lg(league, self.slug)
        what = f"{lg} /{self.endpoint}" if self.endpoint else lg
        return f"StatsPlus refused the {what} request: " + _why(
            self.kind, lg, self.status, self.wait, self.token_sent, self.cookie_sent, self.message)


class RatingsFailure:
    """Why the last fetch_ratings call returned (None, None).

    kind        a StatsPlusRefused kind, or network | off_site | timed_out |
                no_login (no token saved and no cookie given)
    refused     True for a StatsPlusRefused kind
    message     the server's words or what was wrong, tokens replaced by ***
    wait        seconds to wait (too_soon), else None
    status      the HTTP status, when there was one
    slug        the league slug; method = 'token' or 'cookie' (the first try)
    token_sent  True when the failed try carried a token
    started     True when a job had started (StatsPlus gave a poll address)
    html        True for a not_data job whose replies included an HTML page
                (an error or login page, not an empty snapshot)"""

    def __init__(self, kind, message="", wait=None, status=None, slug=None, method=None,
                 token_sent=False, cookie_sent=False, started=False, html=False):
        self.kind, self.wait, self.status, self.slug, self.method = kind, wait, status, slug, method
        self.message = redact(" ".join(str(message or "").split()))[:200]
        self.token_sent, self.cookie_sent, self.started = bool(token_sent), bool(cookie_sent), started
        self.html = bool(html)

    @property
    def refused(self):
        return self.kind in REFUSAL_KINDS

    def user_message(self, league=None):
        lg = _lg(league, self.slug)
        why = _why(self.kind, lg, self.status, self.wait, self.token_sent, self.cookie_sent, self.message)
        if self.refused:
            return f"StatsPlus refused the {lg} ratings request: {why}"
        return f"{lg} ratings were not pulled: {why}"

    def __str__(self):
        return self.user_message()

    def __repr__(self):
        return f"RatingsFailure(kind={self.kind!r}, slug={self.slug!r}, method={self.method!r})"


_RATINGS_FAILURE = None


def ratings_failure():
    """Why the last fetch_ratings call in this process failed (a RatingsFailure),
    or None after a success."""
    return _RATINGS_FAILURE


def _head(text, n):
    """The first n characters of text, redacted BEFORE the cut (a cut can split
    a token, and a split token no longer matches)."""
    return redact(str(text or "")[:n + 4000])[:n]


def _page_title(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text[:5000], re.I | re.S)
    return _head(" ".join(m.group(1).split()), 80) if m else ""


def _refused_reply(text, what, url, token_sent, status=200, cookie_sent=False):
    """The StatsPlusRefused for a reply that is not `what`: a known refusal
    text, a login page, or not_data."""
    s = (text or "").strip()
    kw = dict(status=status, slug=_slug_of(url), endpoint=_endpoint_of(url), token_sent=token_sent,
              cookie_sent=cookie_sent)
    if not s:
        return StatsPlusRefused("not_data", f"an empty reply where {what} was expected", **kw)
    if s[:1] == "<":
        title = _page_title(s)
        if re.search(r"log ?in|sign ?in|logged in|password", s[:20000].lower()):
            return StatsPlusRefused("login_required", f"a login page ({title or 'HTML'}) where {what} "
                                                      f"was expected", **kw)
        return StatsPlusRefused("not_data", f"an HTML page ({title or 'no title'}) where {what} was expected", **kw)
    if len(s) <= 1000:
        hit = _classify(s)
        if hit:
            return StatsPlusRefused(hit[0], s, wait=hit[1], **kw)
    return StatsPlusRefused("not_data", f"{what} expected; the reply starts {_head(s, 60)!r}", **kw)


def _http_refusal(e, url, token_sent, cookie_sent=False):
    """StatsPlusRefused for an HTTP error StatsPlus uses to refuse (401, 403,
    429, or a 4xx whose text is a known refusal), else the scrubbed HTTPError."""
    try:
        body = e.read(4096).decode("utf-8", "replace") if e.fp else ""
    except Exception:
        body = ""
    hit = _classify(body) if len(body.strip()) <= 1000 else None
    kw = dict(status=e.code, slug=_slug_of(url), endpoint=_endpoint_of(url), token_sent=token_sent,
              cookie_sent=cookie_sent)
    if e.code in (401, 403, 429):
        kind = hit[0] if hit and hit[0] in ("token_invalid", "token_expired") else "blocked"
        wait = hit[1] if hit else None
        ra = str((e.headers or {}).get("Retry-After") or "").strip()
        if wait is None and ra.isdigit():
            wait = int(ra)
        return StatsPlusRefused(kind, body.strip() or f"HTTP {e.code} {e.msg}", wait=wait, **kw)
    if hit and 400 <= e.code < 500:
        return StatsPlusRefused(hit[0], body, wait=hit[1], **kw)
    return _scrub(e)


# ---- HTTP -------------------------------------------------------------------------

class _StayOnSite(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only when it stays on the site of `base`. Python's
    urllib copies the request headers (the Cookie too) onto the redirect, so a
    redirect to another host is refused before it is sent. With a token, a
    redirect inside the same league's /api keeps the token."""

    def __init__(self, base, token=None):
        super().__init__()
        self.base = base
        self.token = token

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        newurl = urllib.parse.urljoin(req.full_url, newurl)
        canon = site_url(newurl, self.base)
        if canon is None:
            raise OffSiteError(redact(f"StatsPlus redirected to another site or a malformed address "
                                      f"({_host_txt(newurl)}); the login was not sent there"))
        if self.token and _slug_of(canon) and _slug_of(canon) == _slug_of(req.full_url):
            canon = _with_token(canon, self.token)
        return super().redirect_request(req, fp, code, msg, headers, canon)


def _open(url, timeout=30, headers=None, stay_on=None, token=None):
    """(reply text, True when a token was sent). See _get."""
    h = {"User-Agent": "Mozilla/5.0"}
    if headers:
        h.update(headers)
    cookie_sent = any(k.lower() == "cookie" for k in h)
    tk = _pick_token(url, token)
    try:
        if tk:
            add_secret(tk)
            url = _with_token(url, tk)
            if stay_on is None:
                u = urllib.parse.urlsplit(url)
                stay_on = f"{u.scheme}://{u.netloc}/"
        if stay_on is not None:
            canon = site_url(url, stay_on)
            if canon is None:
                raise OffSiteError(f"refused a request to another site or a malformed address "
                                   f"({_host_txt(url)}); the login was not sent there")
            url = canon
        req = urllib.request.Request(url, headers=h)
        if stay_on is not None and req.host.lower() != urllib.parse.urlsplit(url).netloc.lower():
            raise OffSiteError(f"refused: the address parses to two different hosts, maybe another site "
                               f"({_host_txt(url)}); the login was not sent there")
        opener = urllib.request.build_opener(_StayOnSite(stay_on, tk)) if stay_on is not None else None
        with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
            return r.read().decode("utf-8", "replace"), bool(tk)
    except urllib.error.HTTPError as e:
        raise _http_refusal(e, url, bool(tk), cookie_sent) from None
    except StatsPlusRefused:
        raise
    except OffSiteError as e:
        raise _scrub(e) from None
    except Exception as e:
        raise _scrub(e) from None


def _get(url, timeout=30, headers=None, stay_on=None, token=None):
    """GET url and return the reply text.

    token: None = add the token of the URL's league on its own (see
    token_for_url); a string = send that token (only to https statsplus.net or
    this machine, else OffSiteError); False or "" = send no token.
    stay_on = a base URL: the request (and every redirect) must stay on that
    site (see site_url), else OffSiteError and nothing is sent (use it whenever
    the headers carry the login). A request with a token always stays on its
    own site.
    HTTP 401, 403 and 429 raise StatsPlusRefused (blocked, or the token kind
    the reply names); another 4xx whose text is a known refusal raises that
    kind; other HTTP errors raise HTTPError as before. No message shows a
    token."""
    return _open(url, timeout, headers, stay_on, token)[0]


def tokencheck(slug_or_url, token):
    """The team ID (a string) a token belongs to, from /tokencheck/?token=.
    Raises StatsPlusRefused (token_invalid, token_expired, ...) when StatsPlus
    refuses the token, and not_data when the reply holds no team ID."""
    base = normalize_base(slug_or_url)
    tk = str(token or "").strip()
    if not tk:
        raise ValueError("tokencheck needs a token")
    add_secret(tk)
    url = f"{base}/tokencheck/"
    text, sent = _open(url, token=tk)
    s = text.strip()
    tid = None
    if re.fullmatch(r"\d{1,7}", s):
        tid = s
    elif s[:1] in "{[":
        try:
            doc = json.loads(s)
        except ValueError:
            doc = None
        if isinstance(doc, int):
            tid = str(doc)
        elif isinstance(doc, dict):
            for k in ("team_id", "teamid", "teamID", "team", "id", "tid"):
                v = str(doc.get(k, "")).strip()
                if re.fullmatch(r"\d{1,7}", v):
                    tid = v
                    break
    elif len(s) <= 200 and not _classify(s):
        m = re.search(r"team\s*(?:id)?\D{0,4}(\d{1,7})", s, re.I)
        tid = m.group(1) if m else None
    if tid is None:
        raise _refused_reply(text, "a team ID", url, sent)
    return tid


# ---- ratings (an async job) --------------------------------------------------------

def _looks_tabular(text):
    """True when the first line is a delimited header (3+ of one delimiter)."""
    first = (text or "").lstrip()[:2000].split("\n", 1)[0]
    return any(first.count(d) >= 3 for d in (",", "\t", ";", "|"))


def _refusal_log(e):
    """A log line for a refusal. Keeps the words statsplus_history.py reads:
    'not authenticated', 'not enabled', 'wait N seconds'."""
    if e.kind in ("token_invalid", "token_expired", "login_required") or (e.kind == "blocked" and e.status in (401, 403)):
        return f"not authenticated ({e.kind}{f', HTTP {e.status}' if e.status and e.status != 200 else ''}): {e.message}"
    wait = f" (wait {e.wait} seconds)" if e.wait and f"wait {e.wait} second" not in e.message.lower() else ""
    return f"StatsPlus refused ({e.kind}{f', HTTP {e.status}' if e.status and e.status != 200 else ''}): {e.message}{wait}"


_AUTH_KINDS = ("token_invalid", "token_expired", "login_required", "blocked", "not_data")


def fetch_ratings(slug_or_url, cookie=None, token=None, poll_interval=15, max_polls=30, on_log=print,
                  date=None, max_unrecognized=None):
    """Fetch the login-gated player RATINGS the way StatsPlus actually works
    (per the StatsPlus wiki + the StatsPlus-MCP client):

      auth   = the league's API token (?token=, on the start AND the poll
               request), else the browser cookies (Cookie: sessionid=...;csrftoken=...)
      ratings is an ASYNC JOB:
        1) GET  {base}/ratings/            -> HTML containing a poll URL (?request=...)
        2) poll that URL every ~15s; while it says "still in progress" / "Request
           received", keep waiting; when it returns CSV, that's the ratings.

    token = None takes the league's saved token (see token_for_url); a string
    overrides it (tests). The token is tried first; the cookie is tried only
    when the token try failed to start a job for a login reason. A poll
    address in another league never gets the token (off_site).

    Once a job has started, a "too soon" or HTTP 429 reply to a poll is
    waited out (the seconds StatsPlus gives, at most 5 minutes) up to 3 times
    in a row; a login page or a token refusal on a poll ends the job.

    date = "YYYY-MM-DD" asks for the PAST snapshot of that in-game day
    (StatsPlus /ratings/?date=..., an undocumented feature the StatsPlus author
    announced; used by statsplus_history.py). None = today's ratings.
    The same poll flow serves both. max_unrecognized = give up on a job after
    this many replies that are neither "in progress" nor CSV with rows (an
    empty snapshot or an error page); None = keep polling (the live pull).

    The login only goes to statsplus.net or a subdomain of it (for example
    api.statsplus.net): every request that carries it (the start request, the
    poll URL from the reply and every redirect) must pass site_url. Anything
    else (another host, an '@' in the host part, a backslash) is refused before
    it is sent, logged with the words "another site", and the call returns
    (None, None).
    Returns (rows, method) with method 'token' or 'cookie', or (None, None).
    After (None, None), ratings_failure() returns a RatingsFailure that says
    why (kind: a StatsPlusRefused kind, network, off_site, timed_out or
    no_login). Log lines never show the token or the cookie.
    """
    global _RATINGS_FAILURE
    _RATINGS_FAILURE = None
    base = normalize_base(slug_or_url)
    q = ""
    if date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
            raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
        q = f"date={date}"
    url = f"{base}/ratings/" + (f"?{q}" if q else "")
    slug = _slug_of(url)

    def log(m):
        on_log(redact(m))

    if cookie:
        for part in str(cookie).split(";"):
            add_secret(part.partition("=")[2])
    try:
        tk = _pick_token(url, token) if token else token_for_url(url)
    except OffSiteError as e:
        log(f"[token] {e}")
        _RATINGS_FAILURE = RatingsFailure("off_site", str(e), slug=slug, method="token")
        return None, None
    attempts = []
    if tk:
        attempts.append(("token", tk, None))
    if cookie:
        attempts.append(("cookie", False, {"Cookie": cookie}))
    if not attempts:
        _RATINGS_FAILURE = RatingsFailure("no_login", slug=slug)
        log(f"[ratings] no StatsPlus token saved for {_lg(None, slug)} and no cookie given")
        return None, None

    # NOTE (measured 2026-08-26): a StatsPlus browser login is PER-LEAGUE: the
    # cookie pair only pulls the league the browser is signed into. Visiting
    # the other league's page with the same cookie does NOT flip it. A token is
    # per team per league too, so each league needs its own.
    first = None
    for label, tok, headers in attempts:
        rows, fail = _ratings_job(base, url, slug, label, tok, headers, poll_interval, max_polls,
                                  log, max_unrecognized)
        if rows:
            return rows, label
        first = first or fail
        if fail.started or fail.kind not in _AUTH_KINDS or (fail.kind == "blocked" and fail.status == 429):
            break
    _RATINGS_FAILURE = first
    return None, None


def _ratings_job(base, url, slug, label, tok, headers, poll_interval, max_polls, log, max_unrecognized):
    """One try of the ratings job: (rows, None) or (None, RatingsFailure)."""
    def failure(kind, message="", wait=None, status=None, started=False, html=False):
        return None, RatingsFailure(kind, message, wait=wait, status=status, slug=slug, method=label,
                                    token_sent=bool(tok), cookie_sent=bool(headers), started=started, html=html)

    def looks_unauth(t):
        low = t[:400].lower()
        return "log in" in low or "logged in" in low or "not authorized" in low

    init = None
    for attempt in range(3):
        try:
            init = _get(url, headers=headers, timeout=90, stay_on=base, token=tok)
            break
        except OffSiteError as e:
            log(f"[{label}] {e}")
            return failure("off_site", str(e))
        except StatsPlusRefused as e:
            log(f"[{label}] {_refusal_log(e)}")
            return failure(e.kind, e.message, e.wait, e.status)
        except Exception as e:
            reason = getattr(e, "reason", None) or getattr(e, "code", None) or e
            log(f"[{label}] start attempt {attempt + 1}/3 failed: {type(e).__name__}: {reason}")
            time.sleep(6)
    if init is None:
        log(f"[{label}] could not reach StatsPlus to start the job (network). Try again in a minute.")
        return failure("network")
    if looks_unauth(init):
        log(f"[{label}] not authenticated")
        return failure("login_required", _head(init, 160))
    m = re.search(r"https?://[^\s\"'<>]*\?request=[^\s\"'<>]+", init)
    if not m:
        rows = _sniff_rows(init)  # maybe it returned the data directly
        if rows and len(rows[0].keys()) > 3:
            return rows, None
        log(f"[{label}] no poll URL in response; head: {_head(init, 160)!r}")
        e = _refused_reply(init, "a ratings job", url, bool(tok), cookie_sent=bool(headers))
        if e.kind in ("token_invalid", "token_expired", "login_required"):
            log(f"[{label}] {_refusal_log(e)}")
        return failure(e.kind, e.message, e.wait)
    poll = m.group(0).rstrip(".,)\"'")
    if poll.startswith("http://") and base.startswith("https://"):
        poll = "https://" + poll[len("http://"):]          # keep the login on https
    canon = site_url(poll, base)
    if canon is None:
        log(f"[{label}] refused: the poll address is on another site or malformed "
            f"({_host_txt(poll)}), not on the StatsPlus site; the login was not sent there")
        return failure("off_site", f"poll address on {_host_txt(poll)}")
    other = _slug_of(canon)
    if tok and other and other != slug:
        # a token belongs to one league: never send it to another league's address
        log(f"[{label}] refused: the poll address is in the {other.upper()} league, not "
            f"{_lg(None, slug)}; the {_lg(None, slug)} token was not sent there")
        return failure("off_site", f"poll address in the {other.upper()} league")
    poll = canon
    log(f"[{label}] job started; polling up to {max_polls}x{poll_interval}s (be patient)...")
    last = ""
    odd = 0
    busy = 0                       # transient replies in a row (too soon, HTTP 429)
    html = None                    # title of the last HTML page among the replies without data
    for i in range(max_polls):
        busy_wait = None
        try:
            txt = _get(poll, headers=headers, stay_on=base, token=tok)
        except OffSiteError as e:
            log(f"[{label}] {e}")
            return failure("off_site", str(e), started=True)
        except StatsPlusRefused as e:
            if not _busy(e) or busy >= POLL_BUSY_TRIES:
                log(f"[{label}] {_refusal_log(e)}")
                return failure(e.kind, e.message, e.wait, e.status, started=True)
            busy_wait, txt = e, None
        except Exception as e:
            log(f"  poll {i + 1}: fetch error {type(e).__name__}"); time.sleep(poll_interval); continue
        if txt is not None:
            last = txt
            head = _head(txt.strip(), 50).replace("\n", " ")
            if "still in progress" in txt.lower() or txt.lstrip().lower().startswith("request received"):
                busy = 0
                log(f"  poll {i + 1}/{max_polls}: still building...")
                time.sleep(poll_interval); continue
            rows = _sniff_rows(txt)
            if rows and len(rows[0].keys()) > 3:
                log(f"  poll {i + 1}: ready — {len(rows)} rows, {len(rows[0].keys())} columns.")
                return rows, None
            if txt.lstrip()[:1] == "<" and _login_page(txt):
                e = StatsPlusRefused("login_required", f"a login page ({_page_title(txt) or 'HTML'}) where the "
                                                       f"ratings were expected", status=200, slug=slug,
                                     endpoint="ratings", token_sent=bool(tok), cookie_sent=bool(headers))
                log(f"[{label}] {_refusal_log(e)}")
                return failure(e.kind, e.message, None, 200, started=True)
            hit = None if _looks_tabular(txt) or len(txt.strip()) > 1000 else _classify(txt)
            if hit:
                e = StatsPlusRefused(hit[0], txt.strip(), wait=hit[1], status=200, slug=slug, endpoint="ratings",
                                     token_sent=bool(tok), cookie_sent=bool(headers))
                if not _busy(e) or busy >= POLL_BUSY_TRIES:
                    log(f"[{label}] {_refusal_log(e)}")
                    return failure(e.kind, e.message, e.wait, 200, started=True)
                busy_wait = e
        if busy_wait is not None:
            # A started job is not lost to a short "too soon" or HTTP 429 on a
            # poll: wait as long as StatsPlus says, then poll again.
            busy += 1
            secs = min(max(busy_wait.wait or poll_interval, poll_interval), POLL_BUSY_MAX_S)
            log(f"  poll {i + 1}: StatsPlus is busy ({busy_wait.kind}"
                f"{f', HTTP {busy_wait.status}' if busy_wait.status and busy_wait.status != 200 else ''}); "
                f"waiting {secs:.0f} s, then polling again")
            time.sleep(secs); continue
        busy = 0
        log(f"  poll {i + 1}: unrecognized response, head={head!r}")
        if txt.lstrip()[:1] == "<":
            html = _page_title(txt) or "no title"
        odd += 1
        if max_unrecognized is not None and odd >= max_unrecognized:
            log(f"[{label}] no ratings rows in the reply ({odd} replies without data).")
            return failure("not_data", f"no ratings rows in {odd} replies"
                           + (f" (an HTML page: {html})" if html else ""), started=True, html=bool(html))
        time.sleep(poll_interval)
    log(f"[{label}] timed out. Last response (first 250 chars so we can debug):\n{_head(last, 250)!r}")
    return failure("timed_out", _head(last, 160), started=True)


POLL_BUSY_TRIES = 3        # a started job survives this many "too soon" / HTTP 429 poll replies in a row
POLL_BUSY_MAX_S = 300      # ... and waits at most this long before each next poll
_LOGIN_PAGE = re.compile(r"type\s*=\s*[\"']?password|<title[^>]*>[^<]*\b(?:log ?in|sign ?in)\b"
                         r"|please (?:log|sign) ?in|you must (?:be )?(?:logged|signed) in|login required")


def _busy(e):
    """True for a refusal that only means "not now": too soon, or HTTP 429."""
    return e.kind == "too_soon" or (e.kind == "blocked" and e.status == 429)


def _login_page(text):
    """True when an HTML reply is a login page: a password field, a login
    title, or a plain request to log in."""
    return bool(_LOGIN_PAGE.search(text[:20000].lower()))


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


# ---- date-keyed cache for repeat reads ---------------------------------------------

CACHE_MAX_AGE_H = 6      # a saved reply is reused only while younger than this
DATE_MEMO_S = 60         # fetch_date keeps a league's date this long in memory
_DATE_MEMO = {}
on_warning = print       # where the missing-column WARNING goes
_WARNED = set()


def _warn_once(msg):
    msg = redact(msg)
    if msg not in _WARNED:
        _WARNED.add(msg)
        on_warning(msg)


def cache_folder(slug_or_url):
    """The folder for one league's saved replies: <cache root>/<slug>. The
    cache root is STATSPLUS_CACHE_DIR, else tgs-viz/ingest/.cache/sp. A base
    that is not statsplus.net (a test mock) gets its own folder."""
    base = normalize_base(slug_or_url)
    root = os.environ.get("STATSPLUS_CACHE_DIR") or os.path.join(CACHE_DIR, "sp")
    name = _slug_of(base + "/x") or "league"
    if not _on_statsplus(base + "/x"):
        name += "@" + re.sub(r"[^a-z0-9]+", "_", urllib.parse.urlsplit(base).netloc.lower()).strip("_")
    return os.path.join(root, name)


def _cache_path(base, url):
    u = urllib.parse.urlsplit(url)
    path = u.path.split("/api/", 1)[-1]
    key = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"
    if u.query:
        key += "_" + hashlib.sha1(u.query.encode("utf-8")).hexdigest()[:12]
    return os.path.join(cache_folder(base), key + ".json.gz")


def _cache_read(path, url, game_date, max_age_h):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        age = time.time() - float(doc["saved"])
        if doc.get("v") == 1 and doc.get("url") == url and doc.get("game_date") == game_date \
                and 0 <= age < max_age_h * 3600:
            return doc["data"]
    except Exception:
        pass
    return None


def _cache_write(path, url, game_date, data):
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"v": 1, "url": url, "game_date": game_date, "saved": time.time(), "data": data}, f)
        os.replace(tmp, path)
    except Exception as e:
        _warn_once(f"  note: the StatsPlus reply was not saved for reuse ({type(e).__name__})")
        try:
            os.remove(tmp)
        except OSError:
            pass


def _cached(base, url, fetch, cache, fresh, max_age_h=CACHE_MAX_AGE_H):
    """fetch() through the date-keyed cache (see the module docstring)."""
    if not (cache or fresh):
        return fetch()
    try:
        game_date = fetch_date(base)
    except Exception:
        # /date refused or not reachable: no reuse and nothing saved, but the
        # endpoint itself is still asked (when it refuses too, its own refusal
        # names it). The date is only the cache label.
        return fetch()
    path = _cache_path(base, url)
    if not fresh:
        hit = _cache_read(path, url, game_date, max_age_h)
        if hit is not None:
            return hit
    data = fetch()
    _cache_write(path, url, game_date, data)
    return data


def clear_date_memo():
    """Forget the in-memory /date of every league (the next fetch_date asks StatsPlus)."""
    _DATE_MEMO.clear()


# ---- public fetch helpers ------------------------------------------------------------

# Columns a reply must have (else StatsPlusRefused not_data) and columns the
# callers read when present (a reply without one prints one WARNING). From
# refresh.py, draft.py, metadata_inputs.py, growth_lenses.py,
# statsplus_history.py, fetch_actuals.py and the saved replies under .cache.
COLUMNS = {
    "players": (("ID",), ("date_of_birth", "draft_eligible", "is_on_dl", "is_on_dl60", "dl_days_this_year",
                          "designated_for_assignment", "is_on_waivers", "mlb_service_years",
                          "mlb_service_days", "mlb_service_days_this_year")),
    "contract": (("player_id",), ("current_year", "years", "salary0", "is_major", "no_trade")),
    "teams": (("ID", "Name"), ("Nickname",)),
    "draft": (("ID", "Player Name", "Overall"), ("Round", "Pick In Round", "Team")),
    # /draftpool/: only ID is needed; the shape is from model/src/draftpool.py (never saved from a live reply)
    "draftpool": (("ID",), ("Player Name",)),
    "playerbatstatsv2": (("player_id", "year"), ("league_id", "split_id", "team_id", "pa")),
    "playerpitchstatsv2": (("player_id", "year"), ("league_id", "split_id", "team_id", "bf")),
    "playerfieldstatsv2": (("player_id", "year"), ("league_id", "split_id", "team_id", "position")),
}


def _parse_csv(text, url, name, sent, allow_empty, min_rows):
    need, want = COLUMNS[name]
    what = f"the /{name} CSV"
    if not text.strip():
        if allow_empty:
            return []
        raise _refused_reply(text, what, url, sent)
    reader = csv.DictReader(io.StringIO(text))
    try:
        head = [str(c).strip() for c in (reader.fieldnames or [])]
    except csv.Error:
        head = []
    missing = [c for c in need if c not in head]
    if missing:
        # a refusal text, a page or JSON (not a table): say what StatsPlus said
        if not _looks_tabular(text) and (len(head) < 2 or text.lstrip()[:1] in "<{["
                                         or (len(text.strip()) <= 1000 and _classify(text))):
            raise _refused_reply(text, what, url, sent)
        raise StatsPlusRefused("not_data", f"the /{name} reply has no {', '.join(missing)} "
                                           f"column{'s' if len(missing) > 1 else ''}",
                               status=200, slug=_slug_of(url), endpoint=name, token_sent=sent)
    rows = list(reader)
    if len(rows) < min_rows:
        raise StatsPlusRefused("not_data", f"the /{name} reply has no rows", status=200,
                               slug=_slug_of(url), endpoint=name, token_sent=sent)
    return rows


def _warn_missing(rows, url, name):
    """One WARNING per process when the rows lack a column the callers read
    when present. Runs on a reused copy too, so a later run still says it."""
    if not rows:
        return
    head = {str(k).strip() for k in rows[0].keys()}
    gone = [c for c in COLUMNS[name][1] if c not in head]
    if gone:
        many = len(gone) > 1
        _warn_once(f"WARNING: the StatsPlus {_lg(None, _slug_of(url))} /{name} reply has no "
                   f"{', '.join(gone)} column{'s' if many else ''}; this run leaves out what is read from "
                   f"{'them' if many else 'it'}.")


def _fetch_csv(base, url, name, cache, fresh, token, allow_empty=False, min_rows=0):
    def fetch():
        text, sent = _open(url, token=token)
        return _parse_csv(text, url, name, sent, allow_empty, min_rows)
    rows = _cached(base, url, fetch, cache, fresh)
    _warn_missing(rows, url, name)
    return rows


def fetch_date(base, fresh=False, token=None):
    """The in-game date from /date (the reply's last line, 'YYYY-MM-DD...').
    Kept in memory for 60 s per league; fresh=True asks StatsPlus again.
    A refusal or a network error is kept for the same 60 s, so the cache
    helpers do not ask a failing /date again and again. Raises
    StatsPlusRefused when the reply is not a date."""
    key = base.rstrip("/")
    hit = _DATE_MEMO.get(key)
    if hit and not fresh and token is None and time.monotonic() - hit[1] < DATE_MEMO_S:
        if isinstance(hit[0], BaseException):
            raise hit[0]
        return hit[0]
    url = f"{base}/date"
    try:
        text, sent = _open(url, token=token)
        lines = text.strip().splitlines()
        last = lines[-1].strip() if lines else ""
        if not re.match(r"\d{4}-\d{2}-\d{2}", last):
            raise _refused_reply(text, "a game date", url, sent)
    except (StatsPlusRefused, OSError) as e:
        if token is None:
            _DATE_MEMO[key] = (e, time.monotonic())
        raise
    _DATE_MEMO[key] = (last, time.monotonic())
    return last


def fetch_players(base, *, cache=False, fresh=False, token=None):
    """/players rows. Needs ID; warns when a column the callers read is missing."""
    return _fetch_csv(base, f"{base}/players", "players", cache, fresh, token, min_rows=1)


def fetch_contracts(base, *, cache=False, fresh=False, token=None):
    """/contract rows. Needs player_id."""
    return _fetch_csv(base, f"{base}/contract", "contract", cache, fresh, token, min_rows=1)


def fetch_teams(base, *, cache=False, fresh=False, token=None):
    """/teams/ rows. Needs ID and Name."""
    return _fetch_csv(base, f"{base}/teams/", "teams", cache, fresh, token, min_rows=1)


def fetch_draft(base, *, cache=False, fresh=False, token=None):
    """/draft rows (the live pick list; empty before the draft). Needs ID,
    Player Name and Overall."""
    return _fetch_csv(base, f"{base}/draft", "draft", cache, fresh, token, allow_empty=True)


def fetch_draftpool(base, *, cache=False, fresh=False, token=None):
    """/draftpool/ rows: the players of the league's current (or just finished) draft class.
    Needs ID; warns when Player Name is missing. An empty reply is no rows (no pool yet).
    Every other column of the reply is kept in the row as sent.

    UNVERIFIED SHAPE: no live reply has been saved. The columns ("ID","Player Name") are what
    ootp-dashboard's model/src/draftpool.py parses; a note in the research workspace says the
    endpoint may now take the league token and carry draft demands. Like every request here it
    carries the saved league token on its own. cache=True fits a caller that only needs the class
    list: it changes with the in-game date, so the date-keyed copy is reused for up to 6 hours."""
    return _fetch_csv(base, f"{base}/draftpool/", "draftpool", cache, fresh, token, allow_empty=True)


def fetch_lgdata(base, *, cache=False, fresh=False, token=None):
    """League metadata (/lgdata): [{league_id, name, abbr, level, parent_league_id, primary_league, ...}].
    Raises StatsPlusRefused when the reply holds no leagues."""
    url = f"{base}/lgdata/"

    def fetch():
        text, sent = _open(url, token=token)
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
        leagues = doc.get("leagues") if isinstance(doc, dict) else None
        if not isinstance(leagues, list) or not leagues:
            raise _refused_reply(text, "league data (JSON with leagues)", url, sent)
        return leagues
    return _cached(base, url, fetch, cache, fresh)


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


def fetch_batting(base, year=None, lids=None, split=None, *, cache=False, fresh=False, token=None):
    """Per-player season batting stats (CSV; trailing slash required, 301 without it).
    An empty reply is no rows. Needs player_id and year."""
    return _fetch_csv(base, f"{base}/playerbatstatsv2/{_stats_qs(year, lids, split)}", "playerbatstatsv2",
                      cache, fresh, token, allow_empty=True)


def fetch_pitching(base, year=None, lids=None, split=None, *, cache=False, fresh=False, token=None):
    """Per-player season pitching stats (CSV; trailing slash required)."""
    return _fetch_csv(base, f"{base}/playerpitchstatsv2/{_stats_qs(year, lids, split)}", "playerpitchstatsv2",
                      cache, fresh, token, allow_empty=True)


def fetch_fielding(base, year=None, lids=None, split=None, *, cache=False, fresh=False, token=None):
    """Per-player season fielding stats (CSV; trailing slash required)."""
    return _fetch_csv(base, f"{base}/playerfieldstatsv2/{_stats_qs(year, lids, split)}", "playerfieldstatsv2",
                      cache, fresh, token, allow_empty=True)


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


def _settings():
    """tgs-viz/tools/settings.py (imported on first use: this module also runs
    under the ML interpreter)."""
    tools = os.path.join(os.path.dirname(HERE), "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import settings
    return settings


def foreign_ids(league):
    """StatsPlus League ids of the foreign leagues to drop. TGS: NPB + KBO; BLM:
    none; any other league: its settings foreign_league_ids (default none)."""
    if league in FOREIGN_BY_LEAGUE:
        return FOREIGN_BY_LEAGUE[league]
    lg = _settings().league(league) or {}
    return {str(x) for x in lg.get("foreign_league_ids") or []}


def drop_foreign(rows, league="TGS"):
    """Remove players rostered in a foreign league (NPB/KBO in the TGS world). A
    player in the free-agent pool (League 0) is NOT on a foreign roster, so kept."""
    ids = foreign_ids(league)
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
    """Resolve the app's Lev string for a ratings row, per world. TGS maps its
    League ids; every other league (BLM and new online leagues) reads the clean
    LgLvl tier."""
    if league != "TGS":
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


def reply_columns(*replies):
    """The column names of StatsPlus CSV replies (lists of row dicts), for
    attach_contract_injury(columns=...)."""
    return {str(k).strip() for rows in replies if rows for k in rows[0].keys()}


def attach_contract_injury(recs, cmap, pmap, columns=None):
    """Attach salary/contract + injury/service fields onto engine records (by ID).

    columns = the column names the /contract and /players replies carry
    (reply_columns). A yes/no field whose column is missing is left unset
    instead of set to False (a reply without draft_eligible must not turn every
    amateur into a free agent). None = every column is there (as before).

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
    def has(col):
        return columns is None or col in columns

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
            if has("is_major"):
                r["IsMajorDeal"] = str(c.get("is_major")) == "1"
            if has("no_trade"):
                r["NoTrade"] = str(c.get("no_trade")) == "1"
        p = pmap.get(pid)
        if p:
            if has("is_on_dl"):
                r["OnDL"] = str(p.get("is_on_dl")) == "1"
            if has("is_on_dl60"):
                r["OnDL60"] = str(p.get("is_on_dl60")) == "1"
            dld = _to_int(p.get("dl_days_this_year"))
            if dld is not None:
                r["DLDays"] = dld
            if has("designated_for_assignment"):
                r["DFA"] = str(p.get("designated_for_assignment")) == "1"
            if has("is_on_waivers"):
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
            # Without the draft_eligible column the split is unknown: FA stays unset.
            if has("draft_eligible"):
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
    try:
        data = fetch_all(slug, refresh=refresh)
    except StatsPlusRefused as e:
        sys.exit(str(e))
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
