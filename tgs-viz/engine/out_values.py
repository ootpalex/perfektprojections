"""
out_values.py - what a play made is worth in runs (Phase 2 row 2), derived from
the league's own data. GATED: nothing in the engine reads this module or its
output. hitters.py still takes H38 / H39 from the workbook's Data Points
(0.75 infield / 0.90 outfield, hand-entered as metadata_calibrate STATICS F38 /
F39). docs/phase2/out_values.md has the audit, the numbers, and the patch that
would wire a result in.

THE DERIVATION. A play converted turns a hit into an out, so its value is the
run value of the hit prevented minus the run value of an out, from the league's
own linear weights (metadata_calibrate.run_values + woba_engine):

  inf_out = 1B_above_out                     infielders prevent singles (a ball past the
                                             infield that goes for extra bases is an
                                             outfield play)
  of_out  = f1*1B_above_out + f2*2B_above_out + f3*3B_above_out
            f = the mix of hits the OUTFIELD zones fail to convert

The mix comes from OOTP's balls-in-zone (BIZ) accounting in Fielding_Data:
  chances (Plays A) = BIZ-R + L + E + U + Z + I (impossible included)
  made    (Plays M) = BIZ-Rm + Lm + Em + Um + Zm
  hits in a zone    = Plays A - Plays M - E
  OF hits = sum over LF, CF, RF;   OF singles = OF hits - (league 2B + 3B)
so  f = (OF singles, 2B, 3B) / OF hits.   ASSUMPTION (tagged deliberate): every
2B and 3B is an outfield event. `xbh_in_of` lowers that share to test it.

Same arithmetic as the dashboard's hit_aggregator._derive_out_values (checked
equal on BLM 2058 to 1e-15), but on the engine's own run_values.

Stdlib only (this lives in engine/). Usage:
    python tgs-viz/engine/out_values.py --league BLM            # report
    python tgs-viz/engine/out_values.py --league BLM --write    # also write
                                                  calib/BLM/out_values_candidate.json (unread)
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import metadata_calibrate as M  # noqa: E402  (stdlib only)

IF_POS = ["1B", "2B", "3B", "SS"]
OF_POS = ["LF", "CF", "RF"]
BIZ_ALL = ["BIZ-R", "BIZ-L", "BIZ-E", "BIZ-U", "BIZ-Z", "BIZ-I"]
BIZ_MADE = ["BIZ-Rm", "BIZ-Lm", "BIZ-Em", "BIZ-Um", "BIZ-Zm"]
FROZEN = {"inf_out": 0.75, "of_out": 0.90}          # metadata_calibrate STATICS F38 / F39
ZR_MIN_CHANCES = 20


def league_totals(hit_rows):
    """Hitting_Data column sums + Outs, exactly as metadata_calibrate.hitting_calc builds T."""
    T = {c: M._sum(hit_rows, c) for c in M.HIT_COLS}
    T["Outs"] = (T["AB"] - (T["1B"] + T["2B"] + T["3B"] + T["HR"])
                 + T["SF"] + T["SH"] + T["GIDP"] + T["CS"])
    return T


def above_out(T):
    """(1B, 2B, 3B) run values ABOVE an out, in runs, plus the pieces: rpo, rv, runs_minus."""
    rpo = T["R"] / T["Outs"]
    rv = M.run_values(rpo)
    _, _, runs_minus, scale, _ = M.woba_engine(T, rv)
    return {"1B": rv["1B"] + runs_minus, "2B": rv["2B"] + runs_minus, "3B": rv["3B"] + runs_minus,
            "runs_per_out": rpo, "runs_minus": runs_minus, "wOBA_scale": scale}


def zone_accounting(fld):
    """Per position: chances, made, errors (sums over the position's table)."""
    out = {}
    for pos, rows in fld.items():
        out[pos] = {"chances": sum(M._sum(rows, c) for c in BIZ_ALL),
                    "made": sum(M._sum(rows, c) for c in BIZ_MADE),
                    "errors": M._sum(rows, "E")}
        out[pos]["unconverted"] = out[pos]["chances"] - out[pos]["made"]
        out[pos]["hits"] = out[pos]["unconverted"] - out[pos]["errors"]
    return out


def derive_out_values(T, zones, xbh_in_of=1.0):
    """inf_out / of_out from league totals T and zone_accounting() output."""
    r = above_out(T)
    hits_if = sum(zones[p]["hits"] for p in IF_POS)
    hits_of = sum(zones[p]["hits"] for p in OF_POS)
    x2, x3 = T["2B"] * xbh_in_of, T["3B"] * xbh_in_of
    of_1b = hits_of - (x2 + x3)
    if hits_of <= 0 or of_1b < 0:
        raise ValueError("BIZ accounting does not reconcile (OF singles < 0)")
    f = (of_1b / hits_of, x2 / hits_of, x3 / hits_of)
    of_out = f[0] * r["1B"] + f[1] * r["2B"] + f[2] * r["3B"]
    return {"inf_out": r["1B"], "of_out": of_out, "of_mix_1b_2b_3b": list(f),
            "hits_if": hits_if, "hits_of": hits_of, "of_singles": of_1b,
            "above_out": {k: r[k] for k in ("1B", "2B", "3B")},
            "runs_per_out": r["runs_per_out"], "runs_minus": r["runs_minus"]}


def identity(T, zones, inf_out, of_out):
    """The zone identity as a level check: runs implied by the league's UNCONVERTED
    chances at a candidate out value, divided by the run value (above an out) of every
    non-HR hit the league actually hit. 1.00 means the candidate prices the failed
    plays at what the hits really cost. The accounting covers the seven field
    positions only (pitcher and catcher zones are not in Fielding_Data), so even exact
    values read slightly under 1: see `single_coverage`."""
    r = above_out(T)
    league = T["1B"] * r["1B"] + T["2B"] * r["2B"] + T["3B"] * r["3B"]
    hits_if = sum(zones[p]["hits"] for p in IF_POS)
    hits_of = sum(zones[p]["hits"] for p in OF_POS)
    of_1b = hits_of - (T["2B"] + T["3B"])
    return {"ratio": (hits_if * inf_out + hits_of * of_out) / league,
            "league_hit_runs": league,
            "single_coverage": (hits_if + of_1b) / T["1B"]}


def zr_slopes(fld):
    """OOTP's own ZR regressed on outs made above the position average, per position,
    players with >= ZR_MIN_CHANCES chances. forward = OLS of ZR on outs (biased low when
    the outs count is the noisier variable); reverse = 1 / OLS of outs on ZR (biased high
    in the same case). The truth lies between them when both carry error."""
    res = {}
    for pos in IF_POS + OF_POS:
        rows = fld[pos]
        ch = [sum(M.num(r[c]) for c in BIZ_ALL) for r in rows]
        mk = [sum(M.num(r[c]) for c in BIZ_MADE) for r in rows]
        p_lg = sum(mk) / sum(ch)
        pts = [(m - p_lg * c, M.num(r["ZR"])) for r, c, m in zip(rows, ch, mk) if c >= ZR_MIN_CHANCES]
        n = len(pts)
        mx = sum(x for x, _ in pts) / n
        my = sum(y for _, y in pts) / n
        sxx = sum((x - mx) ** 2 for x, _ in pts)
        syy = sum((y - my) ** 2 for _, y in pts)
        sxy = sum((x - mx) * (y - my) for x, y in pts)
        res[pos] = {"n": n, "forward": sxy / sxx, "reverse": syy / sxy, "r": sxy / (sxx * syy) ** 0.5}
    return res


def load_inputs(league):
    d = os.path.join(HERE, "calib", league, "metadata_inputs")
    if not os.path.isdir(d):
        sys.exit(f"{league} has no calib/{league}/metadata_inputs CSVs (it reads the 25 Metadata.xlsx tabs); "
                 "this tool reads the CSV form only")
    hit = M.load_single(os.path.join(d, "Hitting_Data.csv"))
    fld = M.load_fielding(os.path.join(d, "Fielding_Data.csv"))
    return d, league_totals(hit), fld


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--league", default="BLM")
    ap.add_argument("--write", action="store_true",
                    help="write calib/<LG>/out_values_candidate.json (nothing reads it)")
    a = ap.parse_args()
    d, T, fld = load_inputs(a.league)
    zones = zone_accounting({p: fld[p] for p in IF_POS + OF_POS})
    v = derive_out_values(T, zones)
    print(M.inputs_label(d, ("Hitting_Data.csv", "Fielding_Data.csv")))
    print(f"run environment: {T['R']:.0f} runs / {T['Outs']:.0f} outs = {v['runs_per_out']:.4f} per out; "
          f"runs_minus {v['runs_minus']:.4f}")
    ab = v["above_out"]
    print(f"above an out (runs):  1B {ab['1B']:.4f}   2B {ab['2B']:.4f}   3B {ab['3B']:.4f}")
    print(f"hits the zones failed to convert (chances - made - errors): infield {v['hits_if']:.0f}, "
          f"outfield {v['hits_of']:.0f}; league 2B+3B {T['2B'] + T['3B']:.0f} -> outfield singles {v['of_singles']:.0f}")
    f = v["of_mix_1b_2b_3b"]
    print(f"outfield-prevented hit mix  1B {f[0]:.3f} / 2B {f[1]:.3f} / 3B {f[2]:.3f}")
    print(f"\nDERIVED  inf_out {v['inf_out']:.4f}   of_out {v['of_out']:.4f}      "
          f"FROZEN (F38/F39) {FROZEN['inf_out']:.2f} / {FROZEN['of_out']:.2f}")
    zr = zr_slopes(fld)
    print("\nOOTP ZR per out made above average (forward OLS .. reverse):")
    for p in IF_POS + OF_POS:
        z = zr[p]
        print(f"  {p:<2} n {z['n']:>3}  {z['forward']:.3f} .. {z['reverse']:.3f}   r {z['r']:.2f}")
    print("\nzone identity (runs implied by unconverted chances / run value of the league's non-HR hits):")
    for lab, (i, o) in (("frozen 0.75/0.90", (FROZEN["inf_out"], FROZEN["of_out"])),
                        ("derived", (v["inf_out"], v["of_out"])),
                        ("ZR-implied 0.50/0.66", (0.50, 0.66))):
        idn = identity(T, zones, i, o)
        print(f"  {lab:<22} {idn['ratio']:.3f}")
    print(f"  (single coverage of the seven field positions: {idn['single_coverage']:.3f} of league 1B)")
    print("\nsensitivity of of_out to the 'every 2B/3B is an outfield event' assumption:")
    for s in (1.0, 0.95, 0.90, 0.80):
        print(f"  {s:.2f} of XBH in the outfield -> of_out {derive_out_values(T, zones, s)['of_out']:.4f}")
    if a.write:
        out = {"league": a.league, "status": "CANDIDATE - nothing in the engine reads this file",
               "derived_at": datetime.datetime.now().isoformat(timespec="seconds"),
               "source": M.inputs_label(d, ("Hitting_Data.csv", "Fielding_Data.csv")),
               "method": "engine/out_values.py derive_out_values (linear weights + BIZ outfield hit mix)",
               "inf_out": v["inf_out"], "of_out": v["of_out"], "frozen": FROZEN,
               "of_mix_1b_2b_3b": v["of_mix_1b_2b_3b"]}
        path = os.path.join(HERE, "calib", a.league, "out_values_candidate.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1)
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
