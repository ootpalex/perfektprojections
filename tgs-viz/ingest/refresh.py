"""
One-command refresh: the no-paste pipeline. It runs the engine and writes the
app's JSON directly. No pasting into Excel, no Excel formulas. Your sheets are
never opened for this (constants were already lifted by the engine).

StatsPlus mode (what the bats and the Control page run):
  python tgs-viz/ingest/refresh.py --statsplus --league TGS --write
      pulls the ratings live, then the team names, contracts and injury status,
      and writes the app's JSON. statsplus.py sends the league's saved StatsPlus
      token (StatsPlus Tokens.txt); the browser cookie in STATSPLUS_COOKIE
      is the fallback for a league with no token.
  add --calib TGS|BLM to price a league with another league's calibration (default:
      the league itself). Such a league has no park factors: its My Park files are
      copies of the neutral ones and park_lineup_values.json is not built.
  add --from-cache to rebuild from the last saved pull (.cache/statsplus_<slug>.json)
      with no new ratings job. The team names, contracts and injury status then
      reuse the StatsPlus replies saved earlier while the league's in-game date
      has not moved (at most 6 hours old). A live pull always reads them fresh.

Export mode (the older manual path): point it at your two OOTP exports (the
batters export and the pitchers export, each = Player List columns ID..R5).

  python tgs-viz/ingest/refresh.py --league TGS --hitters hit.html --pitchers pit.html
      --> writes public/data/TGS/hitters_engine.json + pitchers_engine.json (safe side files)

  add --write to overwrite the real hitters.json / pitchers.json (a timestamped
  .bak is made first). The app then shows engine-generated data.

By default it writes SIDE files so you can diff/verify before switching over.

Exit codes in StatsPlus mode. On every code but 0, nothing is written to the app data:
  0  done
  2  not pulled: no StatsPlus token is saved for this league and no browser cookie was given
  3  not pulled: the browser cookie did not open this league (a login is per-league)
  4  the ratings mapping produced 0 players (the raw pull is saved)
  5  the team names, contracts or injury status could not be read (network or server error)
  6  wrong-league safety net: the pulled ratings do not match this league
  7  StatsPlus refused a request (token expired or unknown, login needed, too soon,
     not switched on, blocked, or not the data). The message says why and what to do.
  8  StatsPlus could not be reached for the ratings (network, timed out, or an
     address on another site)
When a live pull's ratings arrive but a later step stops (4, 5, 7), the raw
pull and its archive copy are still saved: the ratings themselves are good.
"""
import os, sys, json, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ratings as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(REPO, "tgs-viz", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import settings as ST  # noqa: E402
CALIB_LEAGUES = ("TGS", "BLM")    # leagues with their own calibration (sheets + calib/<LG>)


def _arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def _live_datapoints(league, kind):
    """Data Points tab of the LIVE projection workbook (read-only, cached values)."""
    from openpyxl import load_workbook
    fname = "The Sheet Pitchers.xlsx" if kind == "pit" else "The Sheet Hitters.xlsx"
    wb = load_workbook(os.path.join(REPO, f"The Sheets {league}", fname),
                       read_only=True, data_only=True)
    out = {}
    for row in wb["Data Points"].iter_rows():
        for c in row:
            if c.value is not None:
                out[c.coordinate] = c.value
    wb.close()
    return out


def drift_check(league):
    """audit B4 guard — two separate questions, with very different stakes:

    PRIMARY   live workbook vs calib/constants-latest.json. The projections READ
              THE WORKBOOK (ratings.py -> scan_consts), so a mismatch here is a
              real problem: a calibrate ran but was never synced into the sheets
              (or a sheet was restored from a backup). Loud.
    SECONDARY engine/extracted snapshots vs the live workbook. The snapshots are
              developer read-backs used only by the porting/validation tooling;
              staleness there NEVER affects a projection. Quiet note with the
              refresh commands. (The old single-layer check compared snapshot vs
              calib and shouted 'projections may be stale' for what was usually
              just an old snapshot — the 2026-08-14 false alarm.)"""
    eng = os.path.join(REPO, "tgs-viz", "engine")
    cal_path = os.path.join(eng, "calib", league, "constants-latest.json")
    if not os.path.exists(cal_path):
        print(f"  [drift-check {league}] skipped (no constants-latest.json)")
        return
    cal = json.load(open(cal_path, encoding="utf-8"))
    live = {k: _live_datapoints(league, k) for k in ("hit", "pit")}
    snap = {}
    for k, stem in (("hit", "hitters"), ("pit", "pitchers")):
        p = os.path.join(eng, "extracted", f"{league}_{stem}_datapoints.json")
        if os.path.exists(p):
            snap[k] = json.load(open(p, encoding="utf-8"))

    # sentinel cell -> constants-latest key. Covers hitting incl. SB% + SBA (B1/B12)
    # + UBR (B9), fielding E% (B2/B5), SP lo-STU (the original B4 symptom), lBABIP
    # (B7), RP STU.
    SENTINELS = [
        ("hit", "B3",  ("hitting", "hEYE", 0)),  ("hit", "C3",  ("hitting", "hEYE", 1)),
        ("hit", "B15", ("hitting", "hSBA", 0)),  ("hit", "C15", ("hitting", "hSBA", 1)),
        ("hit", "B17", ("hitting", "SB%", 0)),   ("hit", "C17", ("hitting", "SB%", 1)),
        ("hit", "B19", ("hitting", "UBR", 0)),   ("hit", "C19", ("hitting", "UBR", 1)),
        ("hit", "K15", ("fielding", "2B E%", "intercept")), ("hit", "L15", ("fielding", "2B E%", "x")),
        ("hit", "K25", ("fielding", "SS E%", "intercept")), ("hit", "L25", ("fielding", "SS E%", "x")),
        ("pit", "B7",  ("pitching_sp", "hSTU", 0)), ("pit", "C7", ("pitching_sp", "hSTU", 1)),
        ("pit", "D7",  ("pitching_sp", "lSTU", 0)), ("pit", "E7", ("pitching_sp", "lSTU", 1)),
        ("pit", "D9",  ("pitching_sp", "lBABIP", 0)), ("pit", "E9", ("pitching_sp", "lBABIP", 1)),
        ("pit", "B18", ("pitching_rp", "hSTU", 0)), ("pit", "C18", ("pitching_rp", "hSTU", 1)),
    ]
    # relative (6-sig-fig) tolerance - "1 + |want|" would make this an absolute test and
    # blind the guard to drift in the sub-1 constants, which is all of them
    differ = lambda a, b: abs(a - b) > 1e-6 * max(abs(a), abs(b))

    bad = checked = stale_snap = 0
    for which, cell, (sec, key, idx) in SENTINELS:
        want = cal.get(sec, {}).get(key)
        if isinstance(want, dict):
            want = want.get(idx)
        elif isinstance(want, (list, tuple)):
            want = want[idx] if idx < len(want) else None
        try:
            got = float(live[which].get(cell))
        except (TypeError, ValueError):
            continue
        if want is None:
            continue
        checked += 1
        if differ(got, float(want)):
            bad += 1
            print(f"  !! DRIFT {league} {which}!{cell}: live workbook {got:.10g} vs "
                  f"constants-latest {float(want):.10g}  [{sec}/{key}]")
        try:
            if differ(float(snap[which].get(cell)), got):
                stale_snap += 1
        except (KeyError, TypeError, ValueError):
            pass
    if bad:
        print(f"  !!!!!!!! {league}: {bad}/{checked} sentinel constants in the LIVE workbook "
              f"disagree with calib/constants-latest.json - the projections and the last "
              f"calibration are out of step. Run \"Recalibrate {league}.bat\" (or "
              f"sync_datapoints.py --league {league} --calib ... --write) to sync the sheets.")
    else:
        print(f"  [drift-check {league}] OK - live workbook matches constants-latest on {checked} sentinels")
    if stale_snap:
        print(f"  (note: {stale_snap} dev-snapshot cell(s) in engine/extracted/ are behind the "
              f"workbook. Projections are NOT affected - the snapshots are developer read-backs. "
              f"Refresh: python tgs-viz/engine/extract_sheet.py {league} and extract_pitchers.py {league})")
    # audit D1 status note: promote_scurves.py picks the pitching rate curve
    # per block on the real season and writes calib/<LG>/scurves.json (only
    # the S-curve blocks + the level offsets of the two-segment lines). See
    # ratings.live_scurves().
    sc_p = os.path.join(eng, "calib", league, "scurves.json")
    if os.path.exists(sc_p):
        try:
            with open(sc_p, encoding="utf-8") as fh:
                when = json.load(fh).get("promoted_at")
        except (OSError, ValueError):
            when = None
        when = when or time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(sc_p)))
        print(f"  [D1 note] {league} pitching curves per block (scurves.json, {when}): "
              f"{R.scurve_summary(R.live_scurves(league))}. Recalibrate {league} checks each "
              f"block again on the real season.")
    else:
        prev_p = os.path.join(eng, "calib", league, "scurves-preview.json")
        worse = total = 0
        try:
            with open(prev_p, encoding="utf-8") as fh:
                prev = json.load(fh)
            for rd in (prev.get("roles") or {}).values():
                for blk in (rd.get("blocks") or {}).values():
                    total += 1
                    g = blk.get("live_gate")
                    if g:   # the real-season gate (promote_scurves.py rule)
                        sig, two = g.get("rmse_sigmoid"), g.get("rmse_twoline")
                        lost = sig is not None and two is not None and not sig < two * 0.95
                    else:   # older preview: archive-frame RMSE only
                        sig, two = blk.get("bucket_rmse_sigmoid"), blk.get("bucket_rmse_twoline")
                        lost = sig is not None and two is not None and sig > two * 1.05
                    worse += int(blk.get("monotone_ok") is not True or lost)
            tried = time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(prev_p)))
        except (OSError, ValueError):
            tried = None
        if tried and worse:
            print(f"  [D1 note] {league} pitching uses the two-segment curves for every block: no "
                  f"scurves.json yet. The last S-curve refit ({tried}) did not beat them on {worse} of "
                  f"{total} blocks. Recalibrate {league} picks the curve per block.")
        else:
            print(f"  [D1 note] {league} pitching uses the two-segment curves for every block (no "
                  f"scurves.json yet); Recalibrate {league} picks the curve per block.")
    # audit D2/D9 status note: the fitted currency layer (RA/9 exponents + RPW)
    # is league-policy LIVE for BOTH leagues (it is archive-fitted, not
    # anchor-dependent, so BLM's mid-season re-scout does not gate it).
    cpath = os.path.join(eng, "calib", league, "currency.json")
    if not os.path.exists(cpath):
        print(f"  !! [currency note] {league}: calib/{league}/currency.json missing - "
              "projections fall back to sheet constants (exp 2.0, tangent RPW). "
              "Run engine/currency_fit.py to restore the fitted D2/D9 layer.")
    # audit D4 + D3 layers (both leagues live — archive-fitted, not anchor-gated)
    for fn, tool, what in [("hitter_tails.json", "engine/hitter_tails_fit.py",
                            "D4 tail corrections (sheet two-line tails)"),
                           ("fielding_curves.json", "engine/fielding_curves_fit.py",
                            "D3 piecewise PM% (sheet linear fits)")]:
        if not os.path.exists(os.path.join(eng, "calib", league, fn)):
            print(f"  !! [{fn.split('.')[0]} note] {league}: calib/{league}/{fn} missing - "
                  f"hitters fall back to {what}. Run {tool}.")


def _stop(code, *lines):
    """Print why the StatsPlus refresh stops, then exit with code (see the docstring)."""
    for ln in lines:
        print(ln)
    sys.exit(code)


def _not_pulled(S, league, slug):
    """The live ratings pull returned nothing: print why and exit 2, 3, 7 or 8.
    Nothing has been saved at this point."""
    f = S.ratings_failure()
    kind = f.kind if f else "not_data"
    keeps = f"The app keeps the last successful {league} pull - its date is in the report below."
    if kind == "no_login":
        _stop(2, f"{league} was not pulled this run - no StatsPlus token is saved for {league} "
                 "and no browser cookie was given.",
              f"(To update {league}: paste its token into StatsPlus Tokens.txt, then run this bat again.)",
              keeps)
    login_kinds = ("login_required", "token_invalid", "token_expired", "not_data")
    if f and f.method == "cookie" and not f.started and (
            kind in login_kinds or (kind == "blocked" and f.status in (401, 403))):
        # Not an error: a StatsPlus browser login is per-league, so the cookie
        # only pulls the league the browser is signed into. The other league
        # simply keeps its last data.
        _stop(3, f"{league} was not pulled this run - the browser login is not signed in to {league}.",
              f"(A browser login only pulls the league it is signed into. To update {league}: paste its token",
              f" into StatsPlus Tokens.txt, or open statsplus.net/{slug} in your browser, then run",
              " this bat again.)",
              keeps)
    why = f.user_message(league) if f else f"StatsPlus sent no {league} ratings rows."
    _stop(7 if (f is None or f.refused) else 8, f"!!!! {why}",
          "     Nothing was saved or overwritten. " + keeps)


def write_json(records, path, overwrite):
    """Write records as JSON. --write keeps a .bak-<stamp> copy of the old file.
    The data goes to <target>.<pid>.tmp first and then moves onto the target
    (retried while a reader holds it), so a kill mid-write never leaves a
    cut-off file."""
    target = path if overwrite else path.replace(".json", "_engine.json")
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    tmp = f"{target}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)
        ST.replace_retry(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return target


def main():
    league = _arg("--league", "TGS")
    # --calib: the calibration league the engine prices with (default: the league
    # itself). A new online league borrows TGS's or BLM's sheets and calib layers;
    # its output folder, raw cache, archive and level map stay its own.
    calib = _arg("--calib") or league
    if "--calib" in sys.argv and calib not in CALIB_LEAGUES:
        _stop(2, f"--calib must be {' or '.join(CALIB_LEAGUES)} (got {calib!r}).")
    own = calib == league           # False: no park factors and no per-pitcher role table for this league
    overwrite = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    drift_check(calib)    # audit B4: warn loudly if constants snapshots disagree

    # --- fully-automatic mode: pull ratings from StatsPlus with your token ---
    if "--statsplus" in sys.argv:
        import statsplus as S
        slug = _arg("--slug") or ST.slug(league)
        raw_path = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
        if "--from-cache" in sys.argv:    # reprocess the saved raw pull: no new ratings job
            rows = json.load(open(raw_path, encoding="utf-8"))
            method = "cache"
        else:
            # statsplus.py sends the league's saved token on its own. The browser
            # cookie (sessionid=...;csrftoken=...) is the fallback. A cookie with
            # blank values (Enter at both bat prompts) counts as no cookie.
            cookie = os.environ.get("STATSPLUS_COOKIE", "").strip() or None
            if cookie and not any(p.partition("=")[2].strip() for p in cookie.split(";")):
                cookie = None
            # With no token and no cookie, fetch_ratings sends nothing and returns
            # (None, None). Every failure exits nonzero, so the calling bat lists
            # the league as not refreshed; _not_pulled says why.
            rows, method = S.fetch_ratings(slug, cookie=cookie)
            if not rows:
                _not_pulled(S, league, slug)
            if method == "cookie" and S.has_token(slug):
                print(f"  WARNING: the saved {league} StatsPlus token did not work (the browser cookie did). "
                      "Check the token in StatsPlus Tokens.txt.")
            # --- league-identity guard (runs BEFORE anything is saved) ---
            # A StatsPlus session serves whichever league it is pointed at. If the
            # flip ever fails, the site could hand back the OTHER league's ratings,
            # and writing those would poison this league's cache, vintage history,
            # trends DB and app data in one stroke. Player IDs are per-league and
            # can collide numerically, so compare ID->Name pairs against the last
            # successful pull: a same-league pull matches nearly 100%.
            if os.path.exists(raw_path):
                try:
                    prev = json.load(open(raw_path, encoding="utf-8"))
                    prev_names = {str(r.get("ID")): str(r.get("Name") or "").strip()
                                  for r in prev if r.get("ID") is not None}
                    joined = same = 0
                    for r in rows:
                        pn = prev_names.get(str(r.get("ID")))
                        if pn is None:
                            continue
                        joined += 1
                        if pn == str(r.get("Name") or "").strip():
                            same += 1
                    if joined >= 200 and same < 0.5 * joined:
                        print(f"!!!! PULL FAILED for {league}: the returned ratings do NOT look like this league")
                        print(f"     (only {same}/{joined} players match the last {league} pull by ID+Name).")
                        print("     This is the wrong-league safety net: nothing was saved or overwritten.")
                        print(f"     Open statsplus.net/{slug} in your browser (logged in), then run the bat again.")
                        sys.exit(6)
                except SystemExit:
                    raise
                except Exception as e:
                    print(f"  WARNING: league-identity guard skipped ({type(e).__name__}: {e})")
            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
            with open(raw_path, "w", encoding="utf-8") as f:   # save raw for validation / --from-cache reprocess
                json.dump(rows, f)
            # audit M2 (ratings-input governance): ALSO archive every successful
            # live pull immutably under .cache/history/ — snapshot-to-snapshot
            # scout churn moves projections ~3x model error, and smoothing
            # (ratings.smoothed_pull) needs the vintages. --from-cache
            # reprocessing deliberately does NOT re-archive (same vintage).
            hist_dir = os.path.join(HERE, ".cache", "history")
            os.makedirs(hist_dir, exist_ok=True)
            hist_path = os.path.join(
                hist_dir, f"statsplus_{slug}_" + time.strftime("%Y%m%d-%H%M") + ".json")
            shutil.copy2(raw_path, hist_path)
            print(f"  archived pull -> {os.path.relpath(hist_path, REPO)}")
            # ratings-history DB: append this live pull to backtest/ratings_history.db
            # so per-player rating trends accumulate automatically. Prices always use
            # the current ratings as they are; the archive feeds last year's growth into
            # the dev numbers (dev signals, ML scoring rows). Additive; never fatal.
            try:
                import importlib.util
                _rdb = os.path.join(REPO, "tgs-viz", "backtest", "ratings_db.py")
                spec = importlib.util.spec_from_file_location("ratings_db", _rdb)
                rdb = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rdb)
                # in-game date of this pull: /date right now. The archive sorts
                # its pulls by it (backtest/pull_order.py). If /date fails, the
                # next trends export measures it from birth dates.
                game_date = None
                try:
                    import datetime as _dt
                    gd = S.fetch_date(S.normalize_base(slug), fresh=True).strip()[:10]
                    game_date = _dt.date.fromisoformat(gd).isoformat()
                except S.StatsPlusRefused as e:
                    print(f"  note: in-game date not read. {e}")
                    print("  (the trends export dates this pull from birth dates)")
                except Exception as e:
                    print(f"  note: in-game date not read from StatsPlus /date ({type(e).__name__}); "
                          "the trends export dates this pull from birth dates")
                rdb.append_pull(league, rows, source="live",
                                files=[os.path.relpath(hist_path, REPO)], game_date=game_date)
                print("  ratings-history DB: appended pull -> tgs-viz/backtest/ratings_history.db")
                # The .db is gitignored (92 MB binary) and StatsPlus serves no
                # rating history, so a lost pull is unrecoverable. Mirror each
                # vintage to a small committed CSV as it arrives.
                _vb = os.path.join(REPO, "tgs-viz", "backtest", "vintage_backup.py")
                spec = importlib.util.spec_from_file_location("vintage_backup", _vb)
                vb = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(vb)
                vb.export()
            except Exception as e:
                print(f"  WARNING: ratings-history DB append failed "
                      f"({type(e).__name__}: {e}) — refresh continues unaffected")
        cols = list(rows[0].keys())
        print(f"StatsPlus: {len(rows)} ratings rows via {method} ({len(cols)} columns).")

        before = len(rows)
        rows = S.drop_foreign(rows, league=league)   # TGS: NPB/KBO; BLM: none
        print(f"  filtered out {before - len(rows)} foreign players; {len(rows)} remain")

        # --- team names, contracts, injury/service status (read here, attached below) ---
        # A live pull reads them fresh and saves the replies; --from-cache reuses
        # the saved replies while the league's in-game date has not moved. When
        # StatsPlus refuses or cannot be reached, stop now: app data without team
        # names or salaries is worse than the last good copy.
        base = S.normalize_base(slug)
        reuse = {"cache": True} if "--from-cache" in sys.argv else {"fresh": True}
        what = "team names"
        try:
            teams = S.fetch_teams(base, **reuse)
            what = "contracts and injury status"
            contracts, players = S.fetch_contracts(base, **reuse), S.fetch_players(base, **reuse)
        except S.StatsPlusRefused as e:
            _stop(7, f"!!!! {league} not updated. {e.user_message(league)}",
                  f"     Nothing was written to the app data; it keeps the last successful {league} data.")
        except Exception as e:
            detail = (S.redact(str(e)).splitlines() or [""])[0][:200]
            _stop(5, f"!!!! {league} not updated: could not read the {what} from StatsPlus "
                     f"({type(e).__name__}{': ' + detail if detail else ''}).",
                  f"     Nothing was written to the app data; it keeps the last successful {league} data. "
                  "Try again in a minute.")
        names = S.team_name_map(teams)
        S.enrich_org_lev(rows, names, league=league)   # readable ORG + Lev for the app/org-builder

        trows = S.translate_rows(rows)

        def is_pit(r):
            return str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
        if not own:
            print(f"  engine calibration: {calib} (the sheets and calib layers of {calib})")
        currency = R.live_currency(calib)   # audit D2/D9: fitted currency layer (both leagues)
        pos_adj = R.live_pos_adj(league)    # Phase 2 row 1: the league's own positional adjustments
        if pos_adj:
            currency = R.with_hitter_cells(currency, pos_adj)
            print(f"  positional adjustments: {league}'s own (engine/calib/pos_adj_overlay.json)")
        print(f"  currency layer: {'FITTED (D2 exponents + D9 RPW, calib/' + calib + '/currency.json)' if currency else 'sheet constants (no currency.json)'}")
        tails = R.live_hitter_tails(calib)      # audit D4: measured tail corrections (both leagues)
        fielding = R.live_fielding(calib)       # audit D3: monotone piecewise PM% (both leagues)
        print(f"  hitter tails: {'FITTED (D4, calib/' + calib + '/hitter_tails.json)' if tails else 'sheet two-line (no hitter_tails.json)'}")
        print(f"  fielding PM%: {'PIECEWISE (D3, calib/' + calib + '/fielding_curves.json)' if fielding else 'sheet linear (no fielding_curves.json)'}")
        # Park spec 2026-08-14: the shipped default is NEUTRAL (all parks equal —
        # contracts and cross-team comparisons are park-normalized); a second
        # *_park dataset carries the 50% home / 50% other-MLB-parks blend for
        # the app's "My Park" toggle.
        hit_rows = [r for r in trows if not is_pit(r)]
        pit_rows = [r for r in trows if is_pit(r)]
        repl = R.live_replacement(league)       # Phase 1: WAR columns beside WAA
        print(f"  replacement: " + (f"{repl['hitter']} / {repl['sp']} / {repl['rp']} wins (hitter / SP / RP, "
                                     f"{repl['league']}{', proxy' if repl['league'] != league else ''})"
                                     if repl else "none (no WAR columns)"))
        hrecs = R.run_hitters(hit_rows, calib, currency=currency,
                              tails=tails, fielding=fielding, park_mode="neutral", replacement=repl)
        if own:
            hrecs_park = R.run_hitters(hit_rows, calib, currency=currency,
                                       tails=tails, fielding=fielding, park_mode="blend", replacement=repl)
        scurves = R.live_scurves(calib)   # audit D1: per-block curves from calib/<LG>/scurves.json, or None
        print(f"  pitching curves: {R.scurve_summary(scurves)}")
        role_stuff = R.live_role_stuff(calib)   # 2026-09-26: measured SP <-> RP stuff change
        print(f"  role stuff: {'MEASURED (calib/' + calib + '/role_stuff.json)' if role_stuff else 'sheet flat 5 (no role_stuff.json)'}")
        precs = R.run_pitchers(pit_rows, calib, scurves=scurves, currency=currency, park_mode="neutral",
                               role_stuff=role_stuff, observed=own, replacement=repl)
        if own:
            precs_park = R.run_pitchers(pit_rows, calib, scurves=scurves, currency=currency, park_mode="blend",
                                        role_stuff=role_stuff, replacement=repl)
            print(f"  park layer: neutral default + blend variant "
                  f"({len(hrecs_park)} hitters / {len(precs_park)} pitchers on the My-Park basis)")
        else:
            # No park factors exist for this league: the My Park files are copies
            # of the neutral results (as export_league.py does).
            hrecs_park, precs_park = [dict(r) for r in hrecs], [dict(r) for r in precs]
            print(f"  park layer: neutral only ({league} has no park factors; My Park = neutral)")
        if not hrecs and not precs:
            print(f"!!!! PULL FAILED for {league}: mapping produced 0 players. Raw columns:")
            print(" ", cols)
            print("Paste that list to me (already saved the raw file) and I'll fix the mapping.")
            sys.exit(4)

        # --- attach contracts (salary) + injury/service status ---
        # /contract and /players were read above with the team names. Market
        # Value needs Price; this also adds the per-year salary schedule,
        # current DL status, and MLB service time.
        try:
            cmap, pmap = S.build_contract_injury_maps(contracts, players)
            # a yes/no field whose column the reply lacks stays unset (not False)
            cols = S.reply_columns(contracts, players)
            n = (S.attach_contract_injury(hrecs, cmap, pmap, columns=cols)
                 + S.attach_contract_injury(precs, cmap, pmap, columns=cols))
            S.attach_contract_injury(hrecs_park, cmap, pmap, columns=cols)
            S.attach_contract_injury(precs_park, cmap, pmap, columns=cols)
            print(f"  attached contracts + injury status: {n} players now carry a salary (Price)")
        except Exception as e:
            _stop(5, f"!!!! {league} not updated: contracts/injury did NOT attach ({type(e).__name__}: "
                     f"{S.redact(e)}).",
                  f"     Nothing was written to the app data; it keeps the last successful {league} data.")

        # --- optional: roster-management fields from the OOTP org export ---
        # Option years, Rule 5, 40-man, rookie status ... are not in StatsPlus. A league
        # that sets roster_export gets them merged by player ID as NEW keys (ingest/
        # roster_export.py). No setting = nothing happens. It can never stop a pull.
        try:
            import roster_export as RX
            if RX.configured_path(league):
                try:
                    pull_date = S.fetch_date(base)[:10]    # the pull's own /date, kept for 60 s
                except Exception:
                    pull_date = None
                RX.apply(league, [hrecs, precs], mirrors=[hrecs_park, precs_park], pull_game_date=pull_date)
        except Exception as e:
            print(f"  WARNING: roster export skipped ({type(e).__name__}: {S.redact(e)}). The pull is unchanged.")

        # Validate the mapping: compare to the sheet's existing hitters.json (same players).
        try:
            cur = {str(x.get("ID")): x for x in json.load(open(os.path.join(out_dir, "hitters.json"), encoding="utf-8"))}
            n = ok = 0; worst = 0.0
            for r in hrecs:
                j = cur.get(str(r.get("ID")))
                if not j:
                    continue
                try:
                    d = abs(float(r.get("Max WAA wtd")) - float(j.get("Max WAA wtd")))
                except (TypeError, ValueError):
                    continue
                n += 1; worst = max(worst, d); ok += (d < 0.5)
            if n:
                if ok > 0.9 * n:
                    verdict = "LOOKS RIGHT — safe to use."
                elif not os.path.exists(os.path.join(out_dir, "hitters_park.json")):
                    # first refresh after the park-basis change: the on-disk file
                    # still carries the old preset-park basis, so a uniform shift
                    # is EXPECTED, not a mapping failure. Self-heals next run.
                    verdict = ("shift is the park-basis change (old file = preset park, "
                               "new default = neutral) — expected on this one run.")
                else:
                    verdict = "MISMATCH — I'll use the saved raw file to fix the mapping/scale."
                print(f"  mapping check: {ok}/{n} hitters within 0.5 WAA of your sheet (worst {worst:.2f}) -> {verdict}")
        except Exception:
            pass

        if hrecs:
            t = write_json(hrecs, os.path.join(out_dir, "hitters.json"), overwrite)
            print(f"hitters: {len(hrecs)} -> {os.path.relpath(t, REPO)}")
        if hrecs_park:
            t = write_json(hrecs_park, os.path.join(out_dir, "hitters_park.json"), overwrite)
            print(f"hitters (My Park): {len(hrecs_park)} -> {os.path.relpath(t, REPO)}")
        if precs:
            t = write_json(precs, os.path.join(out_dir, "pitchers.json"), overwrite)
            print(f"pitchers: {len(precs)} -> {os.path.relpath(t, REPO)}")
        if precs_park:
            t = write_json(precs_park, os.path.join(out_dir, "pitchers_park.json"), overwrite)
            print(f"pitchers (My Park): {len(precs_park)} -> {os.path.relpath(t, REPO)}")
        # Series lineup tool: hitter values in every club park
        # (park_lineup_values.json), rebuilt from the hitters just written.
        # Additive. It can never fail or block a pull.
        if overwrite and hrecs and not own:
            print(f"park lineup values: skipped ({league} has no park factors).")
        elif overwrite and hrecs:
            try:
                import park_values as PV
                rep = PV.build(league, records=hrecs, write=True, quiet=True)
                print(f"park lineup values: {rep['hitters']} hitters x {rep['parks']} parks -> "
                      f"{os.path.relpath(rep['written'], REPO)} ({rep['bytes'] / 1e6:.1f} MB)")
            except (Exception, SystemExit) as e:
                print(f"  park lineup values not rebuilt this run ({type(e).__name__}: "
                      f"{str(e).splitlines()[0] if str(e) else 'no detail'}). The pull is fine; "
                      f"the series lineup tool keeps its last file.")
        print("done." + ("" if overwrite else "  (side files — add --write to go live)"))
        return

    hit_f, pit_f = _arg("--hitters"), _arg("--pitchers")
    if not hit_f and not pit_f:
        print(__doc__)
        return

    if hit_f:
        recs = R.run_hitters(R.read_export(hit_f), calib, currency=R.live_currency(calib),
                             tails=R.live_hitter_tails(calib), fielding=R.live_fielding(calib))
        t = write_json(recs, os.path.join(out_dir, "hitters.json"), overwrite)
        print(f"hitters: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    if pit_f:
        recs = R.run_pitchers(R.read_export(pit_f), calib, scurves=R.live_scurves(calib),
                              currency=R.live_currency(calib), role_stuff=R.live_role_stuff(calib),
                              observed=own)
        t = write_json(recs, os.path.join(out_dir, "pitchers.json"), overwrite)
        print(f"pitchers: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    print("done." + ("" if overwrite else "  (side files — add --write to make them live)"))


if __name__ == "__main__":
    main()
