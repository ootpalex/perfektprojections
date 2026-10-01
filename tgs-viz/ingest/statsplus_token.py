"""
StatsPlus API tokens, one per league, read from a text file you edit.

StatsPlus gives each team one API token per league (statsplus.net/<slug>,
Prefs at the top right, API Token box, Current Token). A token is 36
characters and expires 90 days after StatsPlus made it. statsplus.py adds the
league's token to every request it sends to https://statsplus.net/<slug>/api.

File: "StatsPlus Tokens.txt" in the project folder (next to the .bat files).
      Open it in Notepad, paste each token after its "=" and save:
          TGS=<the TGS token>
          BLM=<the BLM token>
      Lines that start with # are notes. Spaces, quotes and fancy dashes
      around a token are ignored. The file is in .gitignore, so it never goes
      to GitHub. STATSPLUS_TOKEN_FILE overrides the path (tests only).
A small side file remembers the first day each token was seen, so the pulls
can warn before the 90 days run out: tgs-viz/ingest/.cache/statsplus_token_seen.json
(<token file>.seen.json when STATSPLUS_TOKEN_FILE is set). It holds a short
hash of the token, never the token. Nothing here prints, logs or echoes a token.

Usage:
  python tgs-viz/ingest/statsplus_token.py --check [TGS|BLM]  check the tokens in the file with StatsPlus
  python tgs-viz/ingest/statsplus_token.py --have TGS,BLM     exit 0 when every named league has a token, else 1
Both create the file (with empty TGS= and BLM= lines) when it is missing.
The leagues and their slugs come from the settings (tgs-viz/tools/settings.py):
every enabled online league has a line, keyed by its slug in capitals.
This module is stdlib-only. The CLI imports statsplus.py; the functions do not.
"""
import argparse, datetime, hashlib, json, os, re, sys, urllib.error, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402  (league ids, slugs and the token file)

FILE_NAME = os.path.basename(ST.token_file(use_env=False))     # "StatsPlus Tokens.txt"
# (league id, slug) of every enabled online league. The file is keyed by slug.
LEAGUES = tuple(ST.slug_map().items())
EXPIRE_DAYS = 90
WARN_DAYS = 80
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,80}")
DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹣－"), "-")
TEMPLATE = (
    "# StatsPlus API tokens, one per league.\r\n"
    "# Paste each league's token after its = sign, then save this file.\r\n"
    "# Where: log in on statsplus.net, open the league, click Prefs (top right),\r\n"
    "# copy the Current Token from the API Token box (36 characters).\r\n"
    "# Tokens expire 90 days after StatsPlus makes them: paste the new one here then.\r\n"
    "# This file stays on this computer (it is not uploaded to GitHub).\r\n"
) + "".join(f"{_slug_.upper()}=\r\n" for _lg_, _slug_ in LEAGUES)
_MEMO = {}


def default_token_file():
    """The token file when STATSPLUS_TOKEN_FILE is not set (settings statsplus.token_file)."""
    return ST.token_file(use_env=False)


def token_file():
    """Path of the token file (see the module docstring)."""
    p = os.environ.get("STATSPLUS_TOKEN_FILE", "").strip()
    return p or default_token_file()


def seen_file():
    """Path of the first-seen side file (hashes and dates, no tokens)."""
    p = os.environ.get("STATSPLUS_TOKEN_FILE", "").strip()
    if p:
        return p + ".seen.json"
    return os.path.join(HERE, ".cache", "statsplus_token_seen.json")


def _slug(league_or_slug):
    s = str(league_or_slug or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", s):
        raise ValueError(f"not a league name: {league_or_slug!r}")
    return s


def looks_like_token(value):
    """True when value has the shape of a StatsPlus token (20-80 of A-Z a-z 0-9 _ -)."""
    return bool(TOKEN_RE.fullmatch(str(value or "")))


def clean_token(raw):
    """A pasted token without spaces, line breaks or surrounding quotes."""
    s = "".join(str(raw or "").split())
    return s.strip("\"'`")


def read_value(raw):
    """(token, problem) from the text after "=". Fancy dashes become '-'. When
    the text holds more than the token (a label, a second word), the one
    token-shaped word in it is used. problem describes a bad value by counts
    only (never its content); token is '' for an empty value."""
    s = str(raw or "").translate(DASHES)
    tok = clean_token(s)
    if not tok or looks_like_token(tok):
        return tok, None
    words = [w.strip("\"'`.,;:()[]<>") for w in s.split()]
    runs = [w for w in words if looks_like_token(w)]
    if len(runs) == 1:
        return runs[0], None
    good = sum(1 for ch in tok if ch.isascii() and (ch.isalnum() or ch in "-_"))
    return None, (f"the value has {len(tok)} characters ({good} letters, digits or dashes, "
                  f"{len(tok) - good} other). The Current Token is 36 letters, digits and dashes: "
                  f"copy only the token from the API Token box.")


def _decode(data):
    """Text of the file as Notepad may save it (UTF-8 with or without BOM, UTF-16, ANSI)."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _read():
    """{slug: (token or None, problem or None, raw value)} from the token file; {} when missing."""
    path = token_file()
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_mtime_ns, st.st_size)
    if _MEMO.get("key") == key:
        return _MEMO["data"]
    try:
        with open(path, "rb") as f:
            text = _decode(f.read())
    except OSError:
        text = ""
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line and ":" not in line:
            continue
        name, _sep, value = line.partition("=") if "=" in line else line.partition(":")
        try:
            slug = _slug(name.strip().strip("\"'"))
        except ValueError:
            continue
        tok, problem = read_value(value)
        data[slug] = (tok or None, problem, value.strip())
    _MEMO.update(key=key, data=data)
    return data


def ensure_file():
    """Create the token file with one empty line per online league (TGS=, BLM=) when it is missing.
    Returns True when it was created."""
    path = token_file()
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(TEMPLATE)
    _MEMO.clear()
    return True


def ensure_line(slug):
    """Add an empty <SLUG>= line when the file has no line for the slug.
    Other lines and notes are kept. Returns True when it added the line."""
    s = _slug(slug)
    ensure_file()
    if s in _read():
        return False
    _set_line(s, "")
    return True


def token_for(slug):
    """The league's token from the file ('tgs', 'blm'), or None."""
    tok = (_read().get(_slug(slug)) or (None,))[0]
    return tok if looks_like_token(tok) else None


def problem_for(slug):
    """Why the league's line in the file holds no usable token (counts only), or None."""
    return (_read().get(_slug(slug)) or (None, None))[1]


def all_tokens():
    """Every value in the file, good or not (statsplus.redact hides them)."""
    out = set()
    for tok, _problem, raw in _read().values():
        for v in (tok, clean_token(raw)):
            if isinstance(v, str) and len(v) >= 6:
                out.add(v)
    return out


def _fp(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _read_seen():
    try:
        with open(seen_file(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_seen(d):
    path = seen_file()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass                                    # the age warning is a convenience: never fatal


def _seen(slug, today=None, team_id=None, team=None):
    """The league's first-seen entry for its current token (a new token starts
    today). team_id / team update it. None when the league has no token."""
    s = _slug(slug)
    tok = token_for(s)
    if not tok:
        return None
    d = _read_seen()
    e = d.get(s) if isinstance(d.get(s), dict) else {}
    fp = _fp(tok)
    changed = False
    if e.get("fp") != fp:
        e = {"fp": fp, "seen": (today or datetime.date.today()).isoformat(), "team_id": "", "team": ""}
        changed = True
    if team_id is not None and (str(team_id), str(team or "")) != (e.get("team_id"), e.get("team")):
        e.update(team_id=str(team_id), team=str(team or ""))
        changed = True
    if changed:
        d[s] = e
        _write_seen(d)
    return e


def _days_since(saved, today=None):
    try:
        d = datetime.date.fromisoformat(str(saved)[:10])
    except ValueError:
        return None
    return ((today or datetime.date.today()) - d).days


def saved_info(slug, today=None):
    """{'league', 'saved', 'days', 'team_id', 'team'} for the league's token
    ('saved' = the first day it was seen in the file; never the token itself),
    or None when the league has none."""
    e = _seen(slug)
    if not e:
        return None
    return {"league": _slug(slug).upper(), "saved": e.get("seen") or "", "days": _days_since(e.get("seen"), today),
            "team_id": str(e.get("team_id") or ""), "team": str(e.get("team") or "")}


def token_age(slug, today=None):
    """How old the league's token is, without writing anything (doctor.py).
    {"days": n} when the first-seen file knows the current token,
    {"days": None, "new": True} when the token is new to it, None when the
    league has no token."""
    s = _slug(slug)
    tok = token_for(s)
    if not tok:
        return None
    e = _read_seen().get(s)
    if isinstance(e, dict) and e.get("fp") == _fp(tok):
        return {"days": _days_since(e.get("seen"), today)}
    return {"days": None, "new": True}


def age_warning(slug, today=None):
    """A warning when the league's token was first seen more than 80 days ago, else None."""
    info = saved_info(slug, today)
    if not info or info["days"] is None or info["days"] <= WARN_DAYS:
        return None
    return (f"your {info['league']} StatsPlus token is {info['days']} days old; tokens expire after "
            f"{EXPIRE_DAYS} days. Get a new one from StatsPlus Prefs and paste it into {FILE_NAME}.")


def save(slug, token, team_id=None, team=None, today=None):
    """Write a league's token into the file (its KEY= line; notes and other lines
    kept). today sets its first-seen date (tests)."""
    t, problem = read_value(token)
    if not t or problem:
        raise ValueError("that does not look like a StatsPlus token")
    _set_line(_slug(slug), t)
    d = _read_seen()
    d[_slug(slug)] = {"fp": _fp(t), "seen": (today or datetime.date.today()).isoformat(),
                      "team_id": str(team_id or ""), "team": str(team or "")}
    _write_seen(d)


def clear(slug):
    """Empty a league's line. True when it held a value."""
    s = _slug(slug)
    if s not in _read() or not _read()[s][2]:
        return False
    _set_line(s, "")
    return True


def _set_line(slug, value):
    path = token_file()
    ensure_file()
    with open(path, "rb") as f:
        lines = _decode(f.read()).splitlines()
    out, done = [], False
    for line in lines:
        name = line.strip().partition("=")[0].strip().lower()
        if not line.strip().startswith("#") and "=" in line and name == slug:
            out.append(f"{slug.upper()}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{slug.upper()}={value}")
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(out) + "\r\n")
    os.replace(tmp, path)
    _MEMO.clear()


def have(leagues):
    """True when every named league ('TGS', 'blm', ...) has a token in the file."""
    return all(token_for(x) for x in leagues)


# ---- command line --------------------------------------------------------------

def _and(words, last="and"):
    """'A', 'A and B', 'A, B and C'."""
    words = list(words)
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} {last} {words[-1]}"


def _leagues(arg):
    """[(LG, slug)] from 'TGS', 'BLM', 'TGS,BLM' or 'all' (any enabled online league)."""
    known = dict(LEAGUES)
    names = [x.strip().upper() for x in re.split(r"[,\s]+", arg or "") if x.strip()]
    if not names or names == ["ALL"]:
        return list(LEAGUES)
    bad = [n for n in names if n not in known]
    if bad:
        use = _and(known, "or") if known else "no online league is set up"
        raise SystemExit(f"unknown league {', '.join(bad)}: use {use}")
    return [(n, known[n]) for n in names]


def _base(slug):
    """The league's API base. STATSPLUS_TEST_BASE_URL (tests only) points it at
    a mock on this machine and needs STATSPLUS_TOKEN_FILE."""
    test = os.environ.get("STATSPLUS_TEST_BASE_URL", "").strip()
    if not test:
        return f"https://statsplus.net/{slug}/api"
    u = urllib.parse.urlsplit(test)
    own = os.environ.get("STATSPLUS_TOKEN_FILE", "").strip()
    same = bool(own) and os.path.normcase(os.path.abspath(own)) == os.path.normcase(
        os.path.abspath(default_token_file()))
    if (u.hostname or "").lower() not in ("127.0.0.1", "localhost", "::1") or "@" in u.netloc or not own or same:
        raise SystemExit("STATSPLUS_TEST_BASE_URL is for tests: it must point at this machine "
                         "and needs STATSPLUS_TOKEN_FILE set to a test file (not the real token file)")
    return f"{test.rstrip('/')}/{slug}/api"


def _statsplus():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import statsplus
    return statsplus


class NotThisLeague(Exception):
    """StatsPlus accepted the token, but its team is not in this league's team list."""


class Unconfirmed(Exception):
    """StatsPlus accepted the token, but the league's team list could not be read."""


def _refused_text(S, e, lg):
    if isinstance(e, NotThisLeague):
        return (f"StatsPlus accepted the token, but its team (team {e}) is not in the {lg} team list. "
                f"Is it the token of another league? Copy the Current Token from statsplus.net/"
                f"{lg.lower()} Prefs (each league has its own).")
    if isinstance(e, Unconfirmed):
        return (f"StatsPlus accepted the token, but the {lg} team list could not be read to confirm "
                f"the league. {_refused_text(S, e.args[0], lg)}")
    if isinstance(e, S.StatsPlusRefused):
        if e.kind == "token_expired":
            return (f"StatsPlus says this token has expired. Copy the Current Token from StatsPlus Prefs "
                    f"again and paste it into {FILE_NAME}.")
        if e.kind == "token_invalid":
            return (f"StatsPlus does not know this token. Copy the Current Token from the {lg} Prefs page "
                    f"(each league has its own) and paste it into {FILE_NAME}.")
        return e.user_message(lg)
    if isinstance(e, urllib.error.HTTPError):
        if e.code == 404:
            return ("StatsPlus answered, but it has no token check at this address (HTTP 404), so the "
                    "token could not be checked. The pulls still send it.")
        return f"StatsPlus answered with an error (HTTP {e.code}). Try again later."
    return f"StatsPlus could not be reached ({type(e).__name__}: {S.redact(e)}). Try again in a minute."


def _check(S, lg, slug, token):
    """(team_id, team name or None) when StatsPlus accepts the token AND its team
    is in this league's team list (/teams/, sent with the token); raises
    otherwise (NotThisLeague, Unconfirmed, or the refusal)."""
    base = _base(slug)
    S.add_secret(token)
    tid = S.tokencheck(base, token)
    try:
        names = S.team_name_map(S.fetch_teams(base, token=token))
    except Exception as e:
        raise Unconfirmed(e) from None
    if str(tid) not in names:
        raise NotThisLeague(str(tid))
    return tid, names.get(str(tid)) or None


def _no_token_line(lg, slug):
    p = problem_for(slug)
    if p:
        return f"{lg}: the {slug.upper()}= line in {FILE_NAME} does not hold a usable token: {p}"
    return f"{lg}: no token in {FILE_NAME} (paste it after {slug.upper()}=)."


def cmd_check(leagues):
    S = _statsplus()
    if ensure_file():
        print(f"Made {token_file()}: paste the tokens after "
              f"{_and(s.upper() + '=' for _lg, s in LEAGUES)}, then save it.")
    ok = n = 0
    for lg, slug in leagues:
        tok = token_for(slug)
        if not tok:
            print(_no_token_line(lg, slug))
            continue
        n += 1
        try:
            tid, team = _check(S, lg, slug, tok)
        except Exception as e:
            print(f"{lg}: {_refused_text(S, e, lg)}")
            continue
        ok += 1
        info = _seen(slug, team_id=tid, team=team) or {}
        days = _days_since(info.get("seen"))
        when = f", first seen {days} days ago" if days is not None else ""
        print(f"{lg}: OK, {team} (team {tid}){when}." if team else f"{lg}: OK (team {tid}){when}.")
        w = age_warning(slug)
        if w:
            print(f"  WARNING: {w}")
    return 0 if n and ok == n else 1


def cmd_have(leagues):
    ensure_file()
    for lg, slug in leagues:
        if not token_for(slug) and problem_for(slug):
            print(f"  WARNING: {_no_token_line(lg, slug)}")
        w = age_warning(slug)
        if w:
            print(f"  WARNING: {w}")
    return 0 if have([slug for _lg, slug in leagues]) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=f"Check the StatsPlus API tokens in {FILE_NAME} (one per league).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", nargs="?", const="all", metavar="LEAGUES",
                   help="check the tokens in the file with StatsPlus")
    g.add_argument("--have", metavar="LEAGUES", help="exit 0 when every named league has a token, else 1")
    a = ap.parse_args(argv)
    if a.check is not None:
        return cmd_check(_leagues(a.check))
    return cmd_have(_leagues(a.have))


if __name__ == "__main__":
    sys.exit(main())
