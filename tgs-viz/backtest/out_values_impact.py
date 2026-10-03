"""
out_values_impact.py - what the candidate out values would change (Phase 2 row 2). Read-only.

Re-runs the production hitter pricing (ingest/ratings.run_hitters, with the same
currency / tails / fielding layers refresh.py passes) twice over the same BLM
records: once with the workbook's H38 / H39 as shipped, once with the candidate
values from calib/<LG>/out_values_candidate.json (engine/out_values.py --write).
Nothing is written. The baseline must reproduce public/data/<LG>/hitters.json
exactly (it is checked and printed); if it does not, the comparison is void.

Because every infield term of hitters.compute() is (pmaa - eaa + dpaa) * H38, an
infield RunsP scales by exactly candidate / shipped; outfield RunsP is
(pmaa - eaa) * H39 + armaa, so the arm term does not move; the catcher does not move.

    python tgs-viz/backtest/out_values_impact.py --league BLM [--names "A,B"] [--top 6]
"""
import argparse
import json
import os
import sys
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(VIZ, "ingest"))
sys.path.insert(0, os.path.join(VIZ, "engine"))

FIELD = ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]


def price(records: Sequence[Mapping], league: str, h38: Optional[float] = None,
          h39: Optional[float] = None) -> List[dict]:
    """The production hitter path, with H38 / H39 optionally overridden for this call only."""
    import ratings as R
    real = R._scan_consts_cached

    def patched(path):
        dp, filt, park = real(path)
        if h38 is not None:
            dp["H38"] = h38
        if h39 is not None:
            dp["H39"] = h39
        return dp, filt, park

    R._scan_consts_cached = patched
    try:
        return R.run_hitters(list(records), league, currency=R.live_currency(league),
                             tails=R.live_hitter_tails(league), fielding=R.live_fielding(league),
                             park_mode="neutral")
    finally:
        R._scan_consts_cached = real


def frame(out: Sequence[Mapping], cols: Sequence[str]) -> pd.DataFrame:
    df = pd.DataFrame(out)
    keep = ["ID", "Name", "POS", "Lev", "Best Pos"] + list(cols)
    df = df[[c for c in keep if c in df.columns]].copy()
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.set_index("ID")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--league", default="BLM")
    ap.add_argument("--names", default="", help="comma list of player names to print")
    ap.add_argument("--top", type=int, default=6, help="how many biggest movers each way")
    a = ap.parse_args(argv)

    cand = json.load(open(os.path.join(VIZ, "engine", "calib", a.league, "out_values_candidate.json"),
                          encoding="utf-8"))
    h38, h39 = float(cand["inf_out"]), float(cand["of_out"])
    recs = json.load(open(os.path.join(VIZ, "public", "data", a.league, "hitters.json"), encoding="utf-8"))
    cols = [f"{p} RunsP" for p in ["C"] + FIELD] + [f"{p} WAA wtd" for p in ["C", "DH"] + FIELD] + ["Max WAA wtd"]

    base = frame(price(recs, a.league), cols)
    shipped = frame(recs, cols)
    common = base.index.intersection(shipped.index)
    worst = float((base.loc[common, cols] - shipped.loc[common, cols]).abs().max().max())
    print(f"{a.league}: {len(base)} hitters priced; baseline vs public/data hitters.json max |diff| {worst:.2e}"
          f"  ({'REPRODUCES production' if worst < 1e-9 else 'DOES NOT REPRODUCE - comparison void'})")
    new = frame(price(recs, a.league, h38, h39), cols)
    print(f"candidate: H38 {h38:.4f} (shipped 0.75, x{h38 / 0.75:.4f})   H39 {h39:.4f} (shipped 0.90, x{h39 / 0.90:.4f})")

    mlb = base["Lev"] == "MLB"
    print(f"\nMLB hitters ({int(mlb.sum())}), runs per season slot, listed position only:")
    print(f"{'pos':<4}{'n':>4} | {'RunsP sd':>9}{'-> cand':>9} | {'mean |d|':>9}{'max |d|':>9}")
    for p in FIELD:
        m = mlb & (base["POS"] == p)
        c = f"{p} RunsP"
        d = (new.loc[m, c] - base.loc[m, c]).abs()
        print(f"{p:<4}{int(m.sum()):>4} | {base.loc[m, c].std():>9.2f}{new.loc[m, c].std():>9.2f} | "
              f"{d.mean():>9.2f}{d.max():>9.2f}")
    # the largest rating-driven spread: the 90th minus 10th percentile of RunsP at each position
    print("\n90th - 10th percentile of RunsP among MLB hitters listed at the position (runs):")
    for p in FIELD:
        m = mlb & (base["POS"] == p)
        c = f"{p} RunsP"
        g0 = base.loc[m, c].quantile(.9) - base.loc[m, c].quantile(.1)
        g1 = new.loc[m, c].quantile(.9) - new.loc[m, c].quantile(.1)
        print(f"  {p:<3} {g0:>6.1f} -> {g1:>6.1f}  ({g1 - g0:+.1f})")

    d = (new["Max WAA wtd"] - base["Max WAA wtd"])
    print(f"\nMax WAA wtd, MLB hitters: mean change {d[mlb].mean():+.4f}, mean |change| {d[mlb].abs().mean():.4f}, "
          f"max |change| {d[mlb].abs().max():.3f} WAA; {int((d[mlb].abs() > 0.1).sum())} of {int(mlb.sum())} move more than 0.1")
    bpos_changed = int((new.loc[mlb, "Best Pos"] != base.loc[mlb, "Best Pos"]).sum()) if "Best Pos" in base else None
    print(f"Best Pos label changes among MLB hitters: {bpos_changed}")

    def show(ix, title):
        print(f"\n{title}")
        print(f"{'Name':<24}{'POS':<4}{'BestPos':<8}{'Max WAA':>9}{'-> cand':>9}{'d':>8}{'  best-pos RunsP':>17}{'-> cand':>9}")
        for i in ix:
            r0, r1 = base.loc[i], new.loc[i]
            bp = str(r0.get("Best Pos", "")).split()[0] if r0.get("Best Pos") else ""
            col = f"{bp} RunsP"
            rp0 = r0[col] if col in base.columns else float("nan")
            rp1 = r1[col] if col in base.columns else float("nan")
            print(f"{str(r0['Name'])[:23]:<24}{r0['POS']:<4}{bp:<8}{r0['Max WAA wtd']:>9.2f}{r1['Max WAA wtd']:>9.2f}"
                  f"{d[i]:>+8.3f}{rp0:>17.1f}{rp1:>9.1f}")

    dm = d[mlb].sort_values()
    show(dm.index[:a.top], f"largest WAA falls (positive-defence players)")
    show(dm.index[::-1][:a.top], f"largest WAA rises (negative-defence players)")
    top = base[mlb]["Max WAA wtd"].sort_values(ascending=False).index[:a.top]
    show(top, "top MLB hitters by Max WAA wtd")
    if a.names:
        want = [n.strip().lower() for n in a.names.split(",") if n.strip()]
        ix = [i for i in base.index if str(base.loc[i, "Name"]).lower() in want]
        show(ix, "named players")
    return 0


if __name__ == "__main__":
    sys.exit(main())
