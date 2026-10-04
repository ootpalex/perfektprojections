"""
Build the Draft Board JSON from the draft pool + the cached StatsPlus pull.

WHO IS IN THE CLASS comes from StatsPlus first: the league's /draftpool/ list (statsplus.fetch_draftpool).
/players carries a draft_eligible flag, but it marks the whole amateur pool, future classes
included (its draft_year = year drafted, /draft = past results), so the flag is only a last resort
(API_POOL_FALLBACK). When /draftpool/ is refused, unreachable or empty, OOTP's own draft-pool export
is the fallback (settings: ootp_version and ootp_save). A league with neither (SSB on a Mac without
OOTP) keeps its board as it is. The RATINGS for every prospect ARE in the StatsPlus ratings pull. So:
the pool supplies the IDs, the cached pull supplies the ratings, the engine projects them. No manual
ratings paste.

  python tgs-viz/ingest/draft.py --league TGS [--csv "<path>"] [--pool-source auto|statsplus|export] [--write]

--pool-source auto (default): StatsPlus /draftpool/ first; an OOTP export, when one is found,
only adds the columns StatsPlus does not send (DEM, Sign, SctAcc, NAT, Inf) for players that are
in the StatsPlus pool, and its hitter/pitcher tag. statsplus: never read an export. export: the
old behaviour, the export only (--csv implies it). /draftpool/ is read through the date-keyed
cache (one request per in-game day at most). The shape of its reply has not been seen live yet.

DISPERSAL mode (--orgs): a commish-run draft that doesn't exist in the game at all —
teams are folding and their entire orgs go into the pool. Eligibility is just org
membership, which the pull DOES know, so no CSV is involved:

  python tgs-viz/ingest/draft.py --league TGS --orgs "Org A,Org B" [--exclude <txt>] [--write]

Pool = every player whose ORG matches (all levels, real Lev kept, contracts + injury
status attached). StatsPlus can't know this draft's picks either, so removal is manual:
--exclude (default: <repo>/dispersal_drafted.txt) lists one player ID or exact name per
line ('#' comments ok) — append as picks happen and re-run. A fresh ratings pull after
the commish processes moves also shrinks the pool naturally (players change org).

Reads `.cache/statsplus_<slug>.json` (left by refresh.py), so run a StatsPlus pull first.
Without --write it writes *_engine.json side files; with --write it overwrites the live
hitters_draft.json / pitchers_draft.json (timestamped .bak first).

StatsPlus requests carry the league's saved token on their own (statsplus.py). The pick
list (/draft), the BLM /players fallback and the dispersal reads (/teams, /contract,
/players) are read fresh on every run. An EMPTY pick list while the saved one holds picks
of this pool's players (a draft under way) keeps the saved list, with a WARNING: picks
never disappear during a draft. An empty list with no saved picks from this pool (no
draft yet, or last year's) is used as before.

--calib TGS|BLM prices the players with another league's calibration (default: the
league itself). Such a league has no park factors, so its *_park files are copies of
the neutral ones. The default pool exports sit in the league's OOTP save
(settings: ootp_version and ootp_save, tgs-viz/tools/settings.py).

Exit codes:
  0  board written, or skipped with a note (no pool export, no cached pull)
  3  StatsPlus refused a request or sent something that is not the data. Nothing was
     written; the saved pick list and the board stay as they were.
  4  dispersal mode: StatsPlus could not be reached for the team names. Nothing was written.
"""
import os, sys, json, csv, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, HERE); sys.path.insert(0, ENGINE)
import statsplus as S
import ratings as R
REPO = os.path.dirname(os.path.dirname(HERE))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402
CALIB_LEAGUES = ("TGS", "BLM")    # leagues with their own calibration (sheets + calib/<LG>)
EXIT_REFUSED = 3      # StatsPlus refused, or its reply was not the data; nothing written
EXIT_NETWORK = 4      # dispersal: StatsPlus not reachable for the team names; nothing written


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _stop(e, league, kept):
    """Print why StatsPlus refused and what was kept, then exit EXIT_REFUSED."""
    print(f"  {e.user_message(league)}")
    print(f"  {kept}")
    raise SystemExit(EXIT_REFUSED)


def _saved_picks(path):
    """The saved pick list, or [] when there is none (or it does not read)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_json(path, obj):
    """Write obj as JSON through a temp file, so a failed write keeps the old copy.
    The move is retried while a reader holds the file (10 tries, 200 ms apart)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    ST.replace_retry(tmp, path)


def _calib(league):
    """(calibration league, own): --calib, else the league itself. own is False
    when the league borrows another league's calibration."""
    calib = _arg("--calib") or league
    if "--calib" in sys.argv and calib not in CALIB_LEAGUES:
        print(f"--calib must be {' or '.join(CALIB_LEAGUES)} (got {calib!r}).")
        raise SystemExit(2)
    return calib, calib == league


# OOTP draft-pool export(s), per league. Override with --csv (repeatable).
# TGS exports ONE combined file; BLM's screen exports hitters and pitchers
# SEPARATELY — both are read and merged, and the file a row came from decides
# whether it is projected as a hitter or a pitcher (more reliable than POS).
import glob as _glob
POOL_DEFAULT = "major_league_baseball_draft_pool_-_draft_pool_default.csv"
POOL_HITTERS = "major_league_baseball_draft_pool_-_draft_pool_hitter_export.csv"
POOL_PITCHERS = "major_league_baseball_draft_pool_-_draft_pool_pitcher_export.csv"


def _pool_groups(lg):
    """The league's default export groups, in its OOTP save's import_export folder
    (settings ootp_version + ootp_save). TGS exports one combined file; every other
    league may also export hitters and pitchers separately."""
    save = ST.ootp_save_dir(lg)
    if not save:
        return None
    ie = os.path.join(save, "import_export")
    groups = [[os.path.join(ie, POOL_DEFAULT)]]
    if lg != "TGS":
        groups.append([os.path.join(ie, POOL_HITTERS), os.path.join(ie, POOL_PITCHERS)])
    return groups


DEFAULT_CSV = {
    # Each league is a LIST OF GROUPS. The first group with a file present wins, so a
    # fresh combined export is never merged with a stale split pair (or vice versa).
    lg: g for lg, g in ((lg, _pool_groups(lg)) for lg, e in ST.leagues(include_disabled=True).items()
                        if e.get("type") == "statsplus") if g
}

# Leagues allowed to build the board from the StatsPlus draft_eligible flag when no CSV
# exists. The flag sweeps the whole amateur pool (ages 14+, future classes included), so
# it's a last resort, never a substitute for the export — both leagues can and should
# export (BLM's OOTP-27 save has an import_export dir too). BLM keeps the fallback so its
# board still updates on a pull without one; TGS without a CSV leaves the board as-is.
API_POOL_FALLBACK = {"BLM"}


def _pick_group(groups):
    """First group containing at least one existing file (groups may be a flat list)."""
    if groups and isinstance(groups[0], str):
        groups = [groups]
    for g in groups or []:
        if any(p and os.path.exists(p) for p in g):
            return [p for p in g if p and os.path.exists(p)]
    return []


POOL_SOURCES = ("auto", "statsplus", "export")


def _load_pool(paths, warn_stale=True):
    """Read one or more draft-pool CSVs. Returns {id: row}; rows from a file whose
    name says 'pitcher' are tagged _isPit=True, 'hitter' -> False, else None
    (fall back to POS). Later files never clobber earlier ids."""
    by_id, seen = {}, []
    for path in paths:
        if not path or not os.path.exists(path):
            continue
        seen.append(path)
        low = os.path.basename(path).lower()
        tag = True if "pitcher" in low else (False if "hitter" in low else None)
        text = open(path, encoding="utf-8-sig", errors="replace").read()
        n = 0
        for r in csv.DictReader(text.splitlines()):
            pid = str(r.get("ID", "")).strip()
            if not pid or pid in by_id:
                continue
            r["_isPit"] = tag
            by_id[pid] = r
            n += 1
        age_d = (time.time() - os.path.getmtime(path)) / 86400.0
        print(f"  {os.path.basename(path)}: {n} players  (exported {age_d:.0f} days ago)")
        if age_d > 14 and warn_stale:
            print(f"    ^ WARNING: that export is {age_d:.0f} days old - re-export the pool "
                  f"from OOTP's Amateur Draft screen if this is a NEW draft.")
    return by_id, seen
# CSV columns the pull lacks but the Draft Board uses (signing demand etc.). Kept verbatim.
CSV_EXTRA = ["DEM", "Sign", "SctAcc", "NAT", "Inf"]
PITCHER_POS = {"SP", "RP", "CL", "P"}


def _api_pool(slug):
    """{id: row} from StatsPlus /draftpool/ (date-keyed cache). Rows look like the export
    rows the board reads: ID, Name, _isPit=None (the ratings pull's POS decides), plus any
    column the reply sent under a CSV_EXTRA name. Raises StatsPlusRefused or the network error."""
    rows = S.fetch_draftpool(S.normalize_base(slug), cache=True)
    by_id, other = {}, set()
    for r in rows:
        pid = str(r.get("ID", "")).strip()
        if not pid or pid in by_id:
            continue
        row = {"ID": pid, "Name": str(r.get("Player Name") or "").strip(), "_isPit": None}
        for k, v in r.items():
            k = str(k).strip()
            if k in CSV_EXTRA and str(v or "").strip():
                row[k] = str(v).strip()
            elif k not in ("ID", "Player Name"):
                other.add(k)
        by_id[pid] = row
    if other:
        # the shape of /draftpool/ is unverified: say what else it sends (not mapped to anything)
        print(f"  note: /draftpool/ also sends {', '.join(sorted(other))} (not used)")
    return by_id


def _resolve_pool(league, slug, csv_paths, source):
    """(pool {id: row}, labels) by the precedence in the module docstring. May raise SystemExit
    through _stop when StatsPlus refuses /draftpool/ and nothing else can supply the class."""
    def named(pool_files):
        return [os.path.basename(f) for f in pool_files]
    if source == "export":
        by_id, files = _load_pool(csv_paths)
        return by_id, named(files)
    api, refused, failed = {}, None, None
    try:
        api = _api_pool(slug)
    except S.StatsPlusRefused as e:
        refused = e
    except Exception as e:      # network error or OffSiteError; S.redact keeps tokens out of the line
        failed = f"{type(e).__name__}: {S.redact(e)}"
    export, files = ({}, []) if source == "statsplus" else _load_pool(csv_paths, warn_stale=not api)
    if api:
        got = [f"StatsPlus /draftpool/ ({len(api)})"]
        if export:
            both = set(api) & set(export)
            for pid in both:               # the export only adds what StatsPlus does not send
                for f in CSV_EXTRA:
                    if export[pid].get(f) not in (None, "") and api[pid].get(f) in (None, ""):
                        api[pid][f] = export[pid][f]
                if export[pid].get("_isPit") is not None:
                    api[pid]["_isPit"] = export[pid]["_isPit"]
            print(f"  StatsPlus pool {len(api)}, OOTP export {len(export)}, in both {len(both)}"
                  + ("" if len(both) == len(api) == len(export) else
                     "  (they differ: the StatsPlus list is used; export-only players are left out)"))
            got.append(f"export extras ({len(both)})")
        return api, got
    if refused is not None:
        print(f"  WARNING: {refused.user_message(league)}")
        if not export and league not in API_POOL_FALLBACK:
            _stop(refused, league, "No pool export was found either, so there is no draft pool. "
                                   "The existing board was left as-is.")
    elif failed:
        print(f"  WARNING: StatsPlus /draftpool/ could not be read ({failed})")
    else:
        print("  StatsPlus /draftpool/ sent an empty list (no pool yet)")
    if export:
        print("  using the OOTP draft-pool export instead")
    return export, named(files)


def main():
    league = _arg("--league", "TGS")
    slug = _arg("--slug") or ST.slug(league)
    calib, own = _calib(league)
    # --csv may be repeated; otherwise use the league's default export path(s).
    cli_csv = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--csv" and i + 1 < len(sys.argv)]
    csv_paths = cli_csv or _pick_group(DEFAULT_CSV.get(league) or _pool_groups(league)) or []
    write = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)

    source = "export" if cli_csv else _arg("--pool-source", "auto")   # --csv names the export to use
    if source not in POOL_SOURCES:
        print(f"--pool-source must be {', '.join(POOL_SOURCES)} (got {source!r}).")
        raise SystemExit(2)
    by_id, found = _resolve_pool(league, slug, csv_paths, source)
    if not by_id and league in API_POOL_FALLBACK:
        # No local export. StatsPlus /players has a draft_eligible flag, but it marks the
        # WHOLE amateur pool, not this year's class (measured 2026-09-04: TGS 4,801 flagged
        # incl. 3,002 aged 14-17; BLM 1,940 incl. 1,020 aged 14-17). OOTP's export is the
        # only authoritative class list — see API_POOL_FALLBACK above for who may fall
        # back to the flag. TGS: export, or no board.
        # Read fresh, like every other draft-board read: the pool must be StatsPlus's
        # current one, not a copy saved earlier the same in-game day.
        try:
            api_players = S.fetch_players(S.normalize_base(slug), fresh=True)
            if api_players and "draft_eligible" not in api_players[0]:
                raise S.StatsPlusRefused("not_data", "the /players reply has no draft_eligible column",
                                         status=200, slug=slug.lower(), endpoint="players")
            by_id = {str(r["ID"]): {"ID": str(r["ID"]),
                                    "Name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
                                    "POS": (r.get("Pos") or "").strip(), "_isPit": None}
                     for r in api_players if str(r.get("draft_eligible")) == "1"}
            if by_id:
                print(f"{len(by_id)} draft-eligible players from the StatsPlus /players API "
                      f"(no local pool export found)")
                print("  WARNING: the API flag can include FUTURE amateur classes, not just "
                      "this year's — an OOTP pool export is more accurate if you can get one.")
        except S.StatsPlusRefused as e:
            _stop(e, league, "No pool export was found, so there is no draft pool. The existing "
                             "board was left as-is.")
        except Exception as e:
            print(f"  WARNING: StatsPlus /players draft_eligible fetch failed ({type(e).__name__}: {e})")
    if not by_id:
        print(f"No draft pool for {league}. Looked for:")
        for g in (DEFAULT_CSV.get(league) or _pool_groups(league) or []):
          for p in (g if isinstance(g, list) else [g]):
            print("   " + str(p))
        print("StatsPlus /draftpool/ gave no pool either (see above). Export the pool from OOTP's")
        print("Amateur Draft screen (Draft Pool report -> CSV), or pass --csv <path> (repeat --csv")
        print("for separate hitter/pitcher exports).")
        if league not in API_POOL_FALLBACK:
            print("(The StatsPlus draft_eligible flag is NOT used for this league - it marks "
                  "the whole amateur pool, not the class. The existing board was left as-is.)")
        return
    print(f"{len(by_id)} draft-pool players from " + (", ".join(found) or "the draft_eligible flag"))

    # StatsPlus /draft is the LIVE pick list (matches the pool by ID). The FULL class is
    # projected and kept (with each drafted player stamped with his real pick) for the Mock
    # Draft page's from-the-beginning view; the live board files then drop the drafted so
    # every other screen shrinks as the draft happens. As-current-as your last upload.
    dids, dnames, pick_by_id, pick_by_name = set(), set(), {}, {}
    picks_cache = os.path.join(HERE, ".cache", f"draftpicks_{slug}.json")
    picks, picks_src = [], "live"
    try:
        picks = S.fetch_draft(S.normalize_base(slug), fresh=True)
        saved = _saved_picks(picks_cache) if not picks else []
        mine = [p for p in saved if str(p.get("ID")) in by_id]
        if mine:
            # An empty reply while this pool's players are already drafted is not "no picks":
            # keep the saved list, so drafted players do not come back onto the board.
            picks = saved
            age_h = (time.time() - os.path.getmtime(picks_cache)) / 3600.0
            picks_src = f"saved, {age_h:.1f}h old"
            print(f"  WARNING: StatsPlus /draft sent an empty pick list, but the saved list has {len(mine)} "
                  f"picks of this pool - using the saved pick list ({picks_src}); rerun later for newer picks")
        else:
            _save_json(picks_cache, picks)
    except S.StatsPlusRefused as e:
        # A refusal is not a busy server: stop, so the board is never rebuilt from an
        # old pick list without a word. The saved pick list is kept for the next run.
        _stop(e, league, "The saved pick list and the board were left as they were.")
    except Exception as e:
        # Draft day hammers StatsPlus (503s) — fall back to the last successful pick
        # list so the board doesn't resurrect players drafted an hour ago.
        if os.path.exists(picks_cache):
            picks = json.load(open(picks_cache, encoding="utf-8"))
            age_h = (time.time() - os.path.getmtime(picks_cache)) / 3600.0
            picks_src = f"cached, {age_h:.1f}h old"
            print(f"  WARNING: /draft fetch failed ({type(e).__name__}: {e}) - using the "
                  f"cached pick list ({picks_src}); rerun later for newer picks")
        else:
            print(f"  WARNING: couldn't fetch draft results ({type(e).__name__}: {e}); board may still show drafted players")
    for p in picks:
        pid = str(p.get("ID"))
        pname = (p.get("Player Name") or "").strip().lower()
        dids.add(pid); dnames.add(pname)
        info = {"overall": p.get("Overall"), "round": p.get("Round"),
                "pick": p.get("Pick In Round"), "team": p.get("Team")}
        pick_by_id[pid] = info; pick_by_name[pname] = info
    if picks:
        print(f"  {len(picks)} picks ({picks_src}) - full class kept, drafted stamped + dropped from the live board")

    cache = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
    if not os.path.exists(cache):
        print(f"No cached StatsPlus pull at {cache} — run a StatsPlus refresh first.")
        return
    pull = json.load(open(cache, encoding="utf-8"))
    # StatsPlus /draftpool/ lists only the players still available, so a player drafted before
    # this run is not in the pool. Put each picked player back into the class from the ratings
    # pull, so the full class (the Mock Draft's from-the-beginning view) keeps him, stamped with
    # his real pick; the live board still drops him below.
    in_pull = {str(r.get("ID")) for r in pull}
    back = sorted(pid for pid in dids if pid not in by_id and pid in in_pull)
    for pid in back:
        by_id[pid] = {}
    if back:
        print(f"  {len(back)} drafted players no longer in the pool: added back from the ratings pull "
              f"(full class only)")
    lost = sorted(pid for pid in dids if pid not in by_id)
    if lost:
        print(f"  WARNING: {len(lost)} drafted players are in neither the pool nor the ratings pull: {', '.join(lost)}")
    draft = [r for r in pull if str(r.get("ID")) in by_id]
    print(f"matched {len(draft)} of them in the StatsPlus ratings pull")

    trows = S.translate_rows(draft)
    def is_pit(r):
        """hitter/pitcher: the split-file tag if we have one, else the CSV's POS, else
        the ratings pull's own POS (the combined export carries only ID/Name/OVR/POT)."""
        cr = by_id.get(str(r.get("ID")), {})
        tag = cr.get("_isPit")
        if tag is not None:
            return tag
        pos = str(cr.get("POS") or r.get("POS") or "").upper()
        return pos in PITCHER_POS
    def _picked(rec):
        return (pick_by_id.get(str(rec.get("ID")))
                or pick_by_name.get((rec.get("Name") or "").strip().lower()))

    def out(records, name):
        target = os.path.join(out_dir, name if write else name.replace(".json", "_engine.json"))
        if write and os.path.exists(os.path.join(out_dir, name)):
            shutil.copy2(os.path.join(out_dir, name), os.path.join(out_dir, name) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        json.dump(records, open(target, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {name if write else os.path.basename(target)}: {len(records)}")

    # The real draft structure, in pick order (round, pick-in-round, overall, club),
    # supplemental picks included — the Mock Draft slots our board into THESE picks
    # instead of a fixed rounds x picks-per-round grid (user 2026-09-12). One file,
    # no park basis. `Name` is the drafted player so the app's row filter keeps it.
    pick_rows = sorted(
        [{"Overall": int(p.get("Overall") or 0), "Round": int(p.get("Round") or 0),
          "Pick": int(p.get("Pick In Round") or 0), "Team": p.get("Team"),
          "ID": str(p.get("ID")), "Name": p.get("Player Name") or "-"}
         for p in picks if str(p.get("Overall") or "").strip().lstrip("-").isdigit()],
        key=lambda r: r["Overall"])
    if pick_rows:
        out(pick_rows, "draft_picks.json")

    # BOTH park bases, same as refresh.py builds the league population ("we have to
    # draft for our park"): neutral files + *_park (50% home / 50% other-MLB blend).
    # The app's Park Basis toggle swaps draft datasets exactly like hitters/pitchers.
    currency = R.live_currency(calib)   # audit D2/D9: same fitted currency layer as refresh.py
    tails, fielding = R.live_hitter_tails(calib), R.live_fielding(calib)
    scurves = R.live_scurves(calib)
    hit_rows = [r for r in trows if not is_pit(r)]
    pit_rows = [r for r in trows if is_pit(r)]
    hit_ids = {str(r.get("ID")) for r in hit_rows}
    for park_mode, suffix in (("neutral", ""), ("blend", "_park")):
        # a league priced with another league's calibration has no park factors:
        # its *_park files use the neutral basis (as refresh.py --calib does)
        mode = park_mode if own else "neutral"
        # BOTH engines over EVERY row (every pull row carries both skill sets; a pure
        # pitcher's bat is just 20-floors) so two-way players stop being invisible.
        hrecs_full = R.run_hitters(trows, calib, currency=currency,     # audit D4/D3
                                   tails=tails, fielding=fielding, park_mode=mode)
        # audit D1: same live curve model as refresh.py (S-curves TGS / two-line BLM)
        precs_full = R.run_pitchers(trows, calib, scurves=scurves,
                                    currency=currency, park_mode=mode,
                                    role_stuff=R.live_role_stuff(calib), observed=own)
        hrecs = [r for r in hrecs_full if str(r.get("ID")) in hit_ids]
        precs = [r for r in precs_full if str(r.get("ID")) not in hit_ids]
        # Two-way flag — GENUINE threats only (user 2026-09-04): BOTH sides must clear
        # league average at peak (>= 0 WAA). A one-sided case (bad arm, decent bat) is a
        # conversion candidate, not a two-way player, and gets no flag. The 2026 TGS
        # class flags exactly two: Bridges (+0.9 bat / +2.3 arm), Seibel (+0.4 / +0.3).
        # A flag, not a score change: Draft FV stays single-side; the user judges the
        # package by eye.
        bat_peak = {str(r.get("ID")): r.get("MAX WAA P") for r in hrecs_full}
        arm_peak = {}
        for r in precs_full:
            vals = [v for v in (r.get("WAP"), r.get("WAP RP")) if isinstance(v, (int, float))]
            arm_peak[str(r.get("ID"))] = max(vals) if vals else None
        def _ok(v):
            return isinstance(v, (int, float)) and v >= 0
        for rec in hrecs:
            pid = str(rec.get("ID"))
            if _ok(bat_peak.get(pid)) and _ok(arm_peak.get(pid)):
                rec["Arm Peak"] = round(arm_peak[pid], 2)
        for rec in precs:
            pid = str(rec.get("ID"))
            if _ok(bat_peak.get(pid)) and _ok(arm_peak.get(pid)):
                rec["Bat Peak"] = round(bat_peak[pid], 2)
        for rec in hrecs + precs:
            cr = by_id.get(str(rec.get("ID")))
            if cr:
                for f in CSV_EXTRA:
                    if cr.get(f) not in (None, ""):
                        rec[f] = cr[f]
            rec["Lev"] = "DRAFT"
            rec.setdefault("ORG", cr.get("NAT", "") if cr else "")
            pk = _picked(rec)
            if pk:
                rec["DraftedOverall"] = pk["overall"]
                rec["DraftedRound"] = pk["round"]
                rec["DraftedPick"] = pk["pick"]
                rec["DraftedTeam"] = pk["team"]
        print(f"projected ({park_mode if own else park_mode + ' = neutral'}): {len(hrecs)} hitters, {len(precs)} pitchers (full class)")
        # Full class (drafted stamped, nobody removed) — the Mock Draft page's dataset.
        out(hrecs, f"hitters_draft_all{suffix}.json")
        out(precs, f"pitchers_draft_all{suffix}.json")
        # Live board — drafted players removed, same as always.
        out([r for r in hrecs if not _picked(r)], f"hitters_draft{suffix}.json")
        out([r for r in precs if not _picked(r)], f"pitchers_draft{suffix}.json")
    print("done." + ("" if write else "  (side files - add --write to go live)"))


def dispersal_main():
    """--orgs mode: pool = entire orgs (folding teams), from the cached pull only."""
    league = _arg("--league", "TGS")
    slug = _arg("--slug") or ST.slug(league)
    calib, own = _calib(league)
    orgs = [o.strip() for o in (_arg("--orgs") or "").split(",") if o.strip()]
    excl_path = _arg("--exclude") or os.path.join(REPO, "dispersal_drafted.txt")
    write = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    if not orgs:
        print("--orgs needs a comma-separated list of org names (as shown in the app).")
        return

    cache = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
    if not os.path.exists(cache):
        print(f"No cached StatsPlus pull at {cache} — run a StatsPlus refresh first.")
        return
    rows = json.load(open(cache, encoding="utf-8"))
    rows = S.drop_foreign(rows, league=league)

    # Team names are required here (org matching is by name) — fail loudly, not numerically.
    base = S.normalize_base(slug)
    try:
        names = S.team_name_map(S.fetch_teams(base, fresh=True))
    except S.StatsPlusRefused as e:
        _stop(e, league, "Nothing was written; the board was left as it was.")
    except Exception as e:
        print(f"  StatsPlus team names could not be read ({type(e).__name__}: {e}). The orgs are "
              f"matched by name, so nothing was written. Try again in a minute.")
        raise SystemExit(EXIT_NETWORK)
    S.enrich_org_lev(rows, names, league=league)

    orgset = {o.lower() for o in orgs}
    pool = [r for r in rows if str(r.get("ORG", "")).strip().lower() in orgset]
    from collections import Counter
    per = Counter(str(r.get("ORG")) for r in pool)
    for o in orgs:
        n = per.get(o, sum(v for k, v in per.items() if k.lower() == o.lower()))
        print(f"  {o}: {n} players" + ("  <-- 0 matched — check the spelling!" if not n else ""))
    print(f"dispersal pool: {len(pool)} players from {len(orgs)} orgs")

    # Manual drafted-list removal (this draft doesn't exist in StatsPlus either).
    if os.path.exists(excl_path):
        toks = {ln.strip().lower() for ln in open(excl_path, encoding="utf-8-sig")
                if ln.strip() and not ln.strip().startswith("#")}
        if toks:
            before = len(pool)
            pool = [r for r in pool
                    if str(r.get("ID", "")).strip().lower() not in toks
                    and str(r.get("Name", "")).strip().lower() not in toks]
            print(f"  removed {before - len(pool)} drafted (of {len(toks)} lines in {os.path.basename(excl_path)}); {len(pool)} on the board")

    trows = S.translate_rows(pool)
    is_pit = lambda r: str(r.get("POS", "")).upper() in ("SP", "RP", "CL")

    def out(records, name):
        target = os.path.join(out_dir, name if write else name.replace(".json", "_engine.json"))
        if write and os.path.exists(os.path.join(out_dir, name)):
            shutil.copy2(os.path.join(out_dir, name), os.path.join(out_dir, name) + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
        json.dump(records, open(target, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {name if write else os.path.basename(target)}: {len(records)}")

    # Contract/DL maps once; attached to every basis (inheriting real contracts).
    cmap = pmap = cols = None
    try:
        contracts, players = S.fetch_contracts(base, fresh=True), S.fetch_players(base, fresh=True)
        cmap, pmap = S.build_contract_injury_maps(contracts, players)
        cols = S.reply_columns(contracts, players)
    except S.StatsPlusRefused as e:
        _stop(e, league, "Nothing was written; the board was left as it was.")
    except Exception as e:
        print(f"  WARNING: couldn't fetch contracts/injury ({type(e).__name__}: {e})")

    # Both park bases, same as the amateur board (the Park Basis toggle swaps
    # draft datasets like every other player dataset).
    currency = R.live_currency(calib)   # audit D2/D9: same fitted currency layer as refresh.py
    tails, fielding = R.live_hitter_tails(calib), R.live_fielding(calib)
    scurves = R.live_scurves(calib)
    hit_rows = [r for r in trows if not is_pit(r)]
    pit_rows = [r for r in trows if is_pit(r)]
    for park_mode, suffix in (("neutral", ""), ("blend", "_park")):
        mode = park_mode if own else "neutral"      # no park factors for a borrowed calibration
        hrecs = R.run_hitters(hit_rows, calib, currency=currency,       # audit D4/D3
                              tails=tails, fielding=fielding, park_mode=mode)
        # audit D1: same live curve model as refresh.py (S-curves TGS / two-line BLM)
        precs = R.run_pitchers(pit_rows, calib, scurves=scurves,
                               currency=currency, park_mode=mode,
                               role_stuff=R.live_role_stuff(calib), observed=own)
        print(f"projected ({park_mode if own else park_mode + ' = neutral'}): {len(hrecs)} hitters, {len(precs)} pitchers")
        if cmap is not None:
            n = (S.attach_contract_injury(hrecs, cmap, pmap, columns=cols)
                 + S.attach_contract_injury(precs, cmap, pmap, columns=cols))
            print(f"  attached contracts + injury status ({n} with a salary)")
        out(hrecs, f"hitters_draft{suffix}.json")
        out(precs, f"pitchers_draft{suffix}.json")
    print("done." + ("" if write else "  (side files - add --write to go live)"))


if __name__ == "__main__":
    dispersal_main() if "--orgs" in sys.argv else main()
