"""
One-command refresh — the no-paste pipeline.

Point it at your two OOTP exports (the batters export and the pitchers export,
each = Player List columns ID..R5) and it runs the engine and writes the app's
JSON directly. No pasting into Excel, no Excel formulas. Your sheets are never
opened for this (constants were already lifted by the engine).

  python tgs-viz/ingest/refresh.py --league TGS --hitters hit.html --pitchers pit.html
      --> writes public/data/TGS/hitters_engine.json + pitchers_engine.json (safe side files)

  add --write to overwrite the real hitters.json / pitchers.json (a timestamped
  .bak is made first). The app then shows engine-generated data.

By default it writes SIDE files so you can diff/verify before switching over.
"""
import os, sys, json, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ratings as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    # audit D1 status note (league policy): TGS runs the fitted S-curves
    # (calib/TGS/scurves.json); BLM stays on the two-segment lines until its
    # season-end rebuild (ratings re-scouted mid-season after the metadata
    # anchors). See ratings.live_scurves() for the flip procedure.
    if league == "BLM":
        print("  [D1 note] BLM pitching still uses the TWO-SEGMENT curves - the "
              "S-curve flip is TGS-only until BLM's season-end recalibration.")
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


def write_json(records, path, overwrite):
    target = path if overwrite else path.replace(".json", "_engine.json")
    if overwrite and os.path.exists(path):
        shutil.copy2(path, path + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    return target


def main():
    league = _arg("--league", "TGS")
    overwrite = "--write" in sys.argv
    out_dir = os.path.join(REPO, "tgs-viz", "public", "data", league)
    drift_check(league)   # audit B4: warn loudly if constants snapshots disagree

    # --- fully-automatic mode: pull ratings from StatsPlus with your token ---
    if "--statsplus" in sys.argv:
        import statsplus as S
        slug = _arg("--slug") or {"TGS": "tgs"}.get(league, league.lower())
        raw_path = os.path.join(HERE, ".cache", f"statsplus_{slug}.json")
        if "--from-cache" in sys.argv:    # reprocess the saved raw pull — no auth, no re-fetch
            rows = json.load(open(raw_path, encoding="utf-8"))
            method = "cache"
        else:
            token = os.environ.get("STATSPLUS_TOKEN")
            cookie = os.environ.get("STATSPLUS_COOKIE")
            if not (token or cookie):
                print("Set your StatsPlus browser cookies first (PowerShell):")
                print('  $env:STATSPLUS_COOKIE="sessionid=<...>;csrftoken=<...>"; python tgs-viz\\ingest\\refresh.py --statsplus --league TGS')
                # a missing cookie is a FAILED pull, not a quiet no-op — exit nonzero
                # so the calling bat can report the league as not refreshed
                sys.exit(2)
            rows, method = S.fetch_ratings(slug, cookie=cookie, token=token)
            if not rows:
                # Not an error: a StatsPlus login is per-league, so a run only
                # pulls the league the browser is signed into. The other league
                # simply keeps its last data until the user runs from its page.
                print(f"{league} was not pulled this run - your StatsPlus login is on the other league's site.")
                print(f"(A login only pulls the league it is signed into. To update {league}: open")
                print(f" statsplus.net/{slug} in your browser, then run this bat again.)")
                print(f"The app keeps the last successful {league} pull - its date is in the report below.")
                sys.exit(3)
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
            # ratings-history DB (informational only — projections never read it):
            # append this live pull to backtest/ratings_history.db so per-player
            # rating trends accumulate automatically. Additive; never fatal.
            try:
                import importlib.util
                _rdb = os.path.join(REPO, "tgs-viz", "backtest", "ratings_db.py")
                spec = importlib.util.spec_from_file_location("ratings_db", _rdb)
                rdb = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(rdb)
                rdb.append_pull(league, rows, source="live",
                                files=[os.path.relpath(hist_path, REPO)])
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

        try:
            names = S.team_name_map(S.fetch_teams(S.normalize_base(slug)))
            S.enrich_org_lev(rows, names, league=league)   # readable ORG + Lev for the app/org-builder
        except Exception as e:
            print(f"  WARNING: couldn't fetch team names ({type(e).__name__}); ORG stays numeric")

        trows = S.translate_rows(rows)

        def is_pit(r):
            return str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
        currency = R.live_currency(league)   # audit D2/D9: fitted currency layer (both leagues)
        print(f"  currency layer: {'FITTED (D2 exponents + D9 RPW, calib/' + league + '/currency.json)' if currency else 'sheet constants (no currency.json)'}")
        tails = R.live_hitter_tails(league)      # audit D4: measured tail corrections (both leagues)
        fielding = R.live_fielding(league)       # audit D3: monotone piecewise PM% (both leagues)
        print(f"  hitter tails: {'FITTED (D4, calib/' + league + '/hitter_tails.json)' if tails else 'sheet two-line (no hitter_tails.json)'}")
        print(f"  fielding PM%: {'PIECEWISE (D3, calib/' + league + '/fielding_curves.json)' if fielding else 'sheet linear (no fielding_curves.json)'}")
        # Park spec 2026-08-14: the shipped default is NEUTRAL (all parks equal —
        # contracts and cross-team comparisons are park-normalized); a second
        # *_park dataset carries the 50% home / 50% other-MLB-parks blend for
        # the app's "My Park" toggle.
        hit_rows = [r for r in trows if not is_pit(r)]
        pit_rows = [r for r in trows if is_pit(r)]
        hrecs = R.run_hitters(hit_rows, league, currency=currency,
                              tails=tails, fielding=fielding, park_mode="neutral")
        hrecs_park = R.run_hitters(hit_rows, league, currency=currency,
                                   tails=tails, fielding=fielding, park_mode="blend")
        scurves = R.live_scurves(league)   # audit D1: fitted S-curves (TGS) / None (BLM)
        print(f"  pitching curves: {'fitted S-curves (D1, calib/' + league + '/scurves.json)' if scurves else 'two-segment lines'}")
        precs = R.run_pitchers(pit_rows, league, scurves=scurves, currency=currency, park_mode="neutral")
        precs_park = R.run_pitchers(pit_rows, league, scurves=scurves, currency=currency, park_mode="blend")
        print(f"  park layer: neutral default + blend variant "
              f"({len(hrecs_park)} hitters / {len(precs_park)} pitchers on the My-Park basis)")
        if not hrecs and not precs:
            print(f"!!!! PULL FAILED for {league}: mapping produced 0 players. Raw columns:")
            print(" ", cols)
            print("Paste that list to me (already saved the raw file) and I'll fix the mapping.")
            sys.exit(4)

        # --- attach contracts (salary) + injury/service status ---
        # Public endpoints (no auth). Market Value needs Price; this also adds the
        # per-year salary schedule, current DL status, and MLB service time.
        attach_failed = None
        try:
            base = S.normalize_base(slug)
            cmap, pmap = S.build_contract_injury_maps(S.fetch_contracts(base), S.fetch_players(base))
            n = S.attach_contract_injury(hrecs, cmap, pmap) + S.attach_contract_injury(precs, cmap, pmap)
            S.attach_contract_injury(hrecs_park, cmap, pmap)
            S.attach_contract_injury(precs_park, cmap, pmap)
            print(f"  attached contracts + injury status: {n} players now carry a salary (Price)")
        except Exception as e:
            attach_failed = f"{type(e).__name__}: {e}"
            print(f"  WARNING: couldn't attach contracts/injury ({attach_failed}); Market Value will be blank")

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
        if attach_failed:
            # ratings were written, but salaries/DL/service are missing for this
            # vintage — flag the leg so the bat's FAILS list tells the user to
            # simply run the pull again (a transient endpoint failure heals).
            print(f"!!!! {league}: ratings updated, but contracts/injury did NOT attach ({attach_failed}).")
            print("     Market Value, Owed, Status and DL info are blank until the next successful pull.")
            sys.exit(5)
        print("done." + ("" if overwrite else "  (side files — add --write to go live)"))
        return

    hit_f, pit_f = _arg("--hitters"), _arg("--pitchers")
    if not hit_f and not pit_f:
        print(__doc__)
        return

    if hit_f:
        recs = R.run_hitters(R.read_export(hit_f), league, currency=R.live_currency(league),
                             tails=R.live_hitter_tails(league), fielding=R.live_fielding(league))
        t = write_json(recs, os.path.join(out_dir, "hitters.json"), overwrite)
        print(f"hitters: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    if pit_f:
        recs = R.run_pitchers(R.read_export(pit_f), league, scurves=R.live_scurves(league),
                              currency=R.live_currency(league))
        t = write_json(recs, os.path.join(out_dir, "pitchers.json"), overwrite)
        print(f"pitchers: {len(recs)} players -> {os.path.relpath(t, REPO)}")
    print("done." + ("" if overwrite else "  (side files — add --write to make them live)"))


if __name__ == "__main__":
    main()
