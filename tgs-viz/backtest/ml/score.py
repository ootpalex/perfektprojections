"""
score.py - score one league's current players with the DEV machine-learning
models and write public/data/<LG>/dev_ml.json for the app.

User, 2026-09-24: "is there any way you can make a machine learning model to
help with figuring out this dev stuff".

Rules:
  basis     one model set per league: a TGS player is scored with the TGS
            models (DEV priced with the TGS calibration), a BLM player with the
            BLM models. TGS and BLM are never mixed.
  rows      the league's scoring rows score_<LG>_H / score_<LG>_P (dataset.py
            --basis <LG> --score-only builds them from the latest pull). Every
            number goes through predict.predict(), the one shared scoring
            function (order rule, bar rule, range flags).
  pull      "pull" = the latest pull id the scoring rows were built from. It is
            the same id dev_signals.json records as basis.to_pull_id. The app
            uses the ML numbers only when the two match (stale guard in
            src/lib/devMl.js); a mismatch here is printed as a warning.
  ages      peak fields (gain, mlb, useful, good, regular) for ages 16-26, the
            peak models' training ages; path fields (d, dm, d1_lo, d1_hi) for
            ages 16-38, the path models' ages; present1 for ages 27-38. A
            player outside 16-38 is not written (the app keeps the cell method).
  note      "ML, outside training range" for a peak row the models never saw
            the like of: an unsigned international amateur (app Lev INT; DEV
            has none). Written only when it applies.
  lean      3-decimal rounding, short keys, no nulls (a missing number is left
            out); the keys are spelled out in the file's "definitions".

Commands (Python 3.14):
  score.py --league TGS            dry run: score and print a summary
  score.py --league TGS --write    also write public/data/TGS/dev_ml.json
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402
import predict as PR  # noqa: E402

PEAK_AGES = (16, 26)
PATH_AGES = (16, 38)
PRESENT_AGES = (27, 38)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def r3(v):
    """Round to 3 decimals; None for a missing or non-finite number."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    f = round(f, 3)
    return 0.0 if f == 0 else f


def lean(d):
    """Drop None values (the file carries no nulls)."""
    return {k: v for k, v in d.items() if v is not None}


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def signals_pull(league):
    """basis.to_pull_id of public/data/<LG>/dev_signals.json, or None."""
    p = os.path.join(C.APP_DATA, league, "dev_signals.json")
    if not os.path.isfile(p):
        return None
    return (read_json(p).get("basis") or {}).get("to_pull_id")


def scoring_note(league):
    """The scoring note dataset.py wrote into schema_<LG>.json (to_pull and
    more); for an exported league, score_note_<LG>.json plus its basis'
    schema (for the model facts)."""
    if league not in C.BASES:
        p = os.path.join(C.DATA_DIR, f"score_note_{league}.json")
        if not os.path.isfile(p):
            raise SystemExit(f"no {p}; run: py -3.14 tgs-viz/backtest/ml/dataset.py --basis {league} --score-only --write")
        n = read_json(p)
        s, _ = scoring_note(C.league_basis(league))
        return s, (n.get("scoring") or {}).get(league) or {}
    p = os.path.join(C.DATA_DIR, f"schema_{league}.json")
    if not os.path.isfile(p):
        raise SystemExit(f"no {p}; run: py -3.14 tgs-viz/backtest/ml/dataset.py --basis {league} --score-only --write")
    s = read_json(p)
    return s, (s.get("scoring") or {}).get(league) or {}


def player_entry(row, pr, role):
    """One player's lean dict from his scoring row and his predict() row."""
    age = float(row["age"])
    e = {"r": role, "age": int(age) if age == int(age) else r3(age), "now": r3(row["now_waa"]),
         "in_org": int(row["in_org"] == 1)}
    peak = PEAK_AGES[0] <= age <= PEAK_AGES[1]
    path = PATH_AGES[0] <= age <= PATH_AGES[1]
    if peak:
        e["gain"] = [r3(pr[c]) for c in PR.QCOLS]
        e["mlb"] = r3(pr["p_mlb"])
        e["useful"] = r3(pr["p_useful"])
        e["good"] = r3(pr["p_good"])
        e["regular"] = r3(pr["p_regular"])
        if pr["ml_source"] != "ML":
            e["note"] = str(pr["ml_source"])
    if path:
        e["d"] = [r3(pr[f"d{k}"]) for k in PR.KS]
        e["dm"] = [r3(pr[f"d{k}_mean"]) for k in PR.KS]
        e["d1_lo"] = r3(pr["d1_q25"])
        e["d1_hi"] = r3(pr["d1_q75"])
        if PRESENT_AGES[0] <= age <= PRESENT_AGES[1]:
            e["present1"] = r3(pr["p_present1"])
    if not (peak or path):
        return None
    return lean(e)


DEFINITIONS = {
    "players": "keyed by player ID; every player of the league's latest pull aged 16-38 with a scoring row",
    "r": "role the models scored him in: H (hitter) or P (pitcher: pos SP, RP or CL)",
    "age": "the pull's Age field",
    "now": "his current WAA the models start from (neutral park): hitters Max WAA wtd, pitchers the larger of "
           "WAA wtd and WAA wtd RP; the same number dev_signals.json calls share_now",
    "in_org": "1 = under contract with an org (not AMA, FA or INT)",
    "gain": "ages 16-26: eventual peak WAA minus now, quantiles 10/25/50/75/90, never below 0 and never crossing; "
            "Exp peak = now + gain[2], its range now + gain[1] to now + gain[3]",
    "mlb": "ages 16-26: chance his eventual peak reaches -1 WAA (an MLB-level player); 1 when now is at the bar "
           "(within 0.05)",
    "useful": "the same at 0 WAA (an average MLB player); never above mlb",
    "good": "the same at +1.5 WAA (a clear regular); never above useful",
    "regular": "ages 16-26: chance of some later MLB season with 300+ PA or 150+ BF (the app's Make it %)",
    "d": "ages 16-38: median change of his WAA 1..5 game-years from now (for a player still in the league)",
    "dm": "ages 16-38: expected (mean) change of his WAA 1..5 game-years from now, for money (FA pricing)",
    "d1_lo": "25th percentile of next season's change",
    "d1_hi": "75th percentile of next season's change",
    "present1": "ages 27-38: chance he is still in the league next season",
    "note": "'ML, outside training range' when the models never saw players like him (app Lev INT: DEV has no "
            "unsigned international amateurs); left out otherwise",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", required=True, choices=C.scoring_leagues(),
                    help="league to score; its own model set is used (one model set per league)")
    ap.add_argument("--write", action="store_true", help="write public/data/<LG>/dev_ml.json")
    args = ap.parse_args(argv)
    lg = args.league
    t0 = time.time()

    schema, note = scoring_note(lg)
    pull = note.get("to_pull")
    sig_pull = signals_pull(lg)
    if sig_pull is None:
        log(f"WARNING: no dev_signals.json pull for {lg}; the app will not use this file until one exists")
    elif sig_pull != pull:
        log(f"WARNING: scoring rows are from pull {pull} but dev_signals.json is on pull {sig_pull}; the app will "
            f"keep the cell method until both are rebuilt from the same pull (dataset.py --score-only, dev_signals.py)")

    basis = C.league_basis(lg)          # an exported league borrows its basis' models
    bundle = PR.load_bundle(basis)
    log(f"loaded {basis} models for {lg} ({time.time() - t0:.1f}s)")
    pm = bundle["peak"]
    seasons = (schema.get("source") or {}).get("dumps")
    players, counts = {}, {}
    for role in C.ROLES:
        sp = C.table_path(f"score_{lg}_{role}")
        if not os.path.exists(sp):
            raise SystemExit(f"no {sp}; run: py -3.14 tgs-viz/backtest/ml/dataset.py --basis {lg} --score-only --write")
        sc = C.load_table(sp)
        keep = (sc["age"] >= PATH_AGES[0]) & (sc["age"] <= PATH_AGES[1])
        sub = sc[keep]
        P = PR.predict(bundle, sub, role)
        n_peak = n_path = n_note = 0
        for i in range(len(sub)):
            row = sub.iloc[i]
            e = player_entry(row, P.iloc[i], role)
            if e is None:
                continue
            pid = str(int(row["pid"]))
            if pid in players:
                log(f"WARNING: player {pid} in both role tables; the {role} row is dropped")
                continue
            players[pid] = e
            n_peak += "gain" in e
            n_path += "d" in e
            n_note += "note" in e
        counts[role] = {"rows": int(len(sc)), "peak": n_peak, "path": n_path, "note": n_note,
                        "under_16": int((sc["age"] < PATH_AGES[0]).sum()),
                        "over_38": int((sc["age"] > PATH_AGES[1]).sum())}
        young = sub[(sub["age"] >= PEAK_AGES[0]) & (sub["age"] <= PEAK_AGES[1])]
        yp = P.loc[young.index]
        counts[role]["mean_p_useful_16_26"] = r3(yp["p_useful"].mean()) if len(yp) else None
        log(f"[{role}] {counts[role]}")

    out = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "league": lg,
        "basis": basis,
        "model": {
            "trained_on": f"DEV league, {seasons} seasons",
            "seasons": seasons,
            "fit_date": pm.get("date"),
            "rows": {role: {"peak": pm["roles"][role].get("train_rows"),
                            "path": bundle["path"][role]["models"]["d1"].get("n_train")} for role in C.ROLES},
            "features": "every rating, potential, last year's growth, level and value",
            "calibration": pm.get("basis_rule"),
        },
        "pull": pull,
        "pull_date": note.get("to_date"),
        "bars": {"mlb": C.PEAK_BARS["mlb"], "useful": C.PEAK_BARS["useful"], "good": C.PEAK_BARS["good"],
                 "tolerance": PR.BAR_TOL},
        "counts": counts,
        "definitions": DEFINITIONS,
        "players": players,
    }
    text = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    log(f"{lg}: {len(players):,} players, pull {pull} (dev_signals pull {sig_pull}), {len(text) / 1e6:.2f} MB")
    if not args.write:
        log("dry run; add --write to write the app file")
        return
    dst = os.path.join(C.APP_DATA, lg, "dev_ml.json")
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    for attempt in range(10):          # the app may be reading dev_ml.json: retry the move
        try:
            os.replace(tmp, dst)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.2)
    log(f"wrote {dst} [{time.time() - t0:.0f}s]")


if __name__ == "__main__":
    main()
