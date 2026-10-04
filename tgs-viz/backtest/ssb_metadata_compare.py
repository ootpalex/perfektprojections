"""
ssb_metadata_compare.py - how far SSB's own metadata constants sit from BLM's, and what the
difference does to prices. Analysis only: reads, writes under .dev_cache/ssb_metadata/ and nothing else.

  python tgs-viz/backtest/ssb_metadata_compare.py table   --se DIR [--alt DIR]
  python tgs-viz/backtest/ssb_metadata_compare.py pricing --se DIR [--alt DIR] [--level 1|all]

DIR is a folder with metadata-latest.json, written by
    metadata_inputs.py --league SSB ... ; metadata_calibrate.py --inputs-dir <out> --json <out>/metadata-latest.json
--se is the season-end build, --alt a second build (the 2044-05 ratings) to show how much the ratings
vintage moves. BLM's side is engine/calib/BLM/metadata-latest.json.

table    one row per metadata constant: BLM, SSB, SSB alt, difference, % difference of BLM -> metadata_comparison.csv
pricing  prices the latest SSB pull twice with the engine, in memory: with BLM's Data Points as they are, and
         with SSB's metadata cells laid over them (BLM's workbooks are only read; nothing is written to
         engine/calib, the sheets or public/data). SSB's own positional adjustments (pos_adj_overlay.json) and
         replacement credits ride along as in the Update task, and the BLM calibration layers (currency, tails,
         fielding curves, S-curves, role stuff) stay BLM's. Reports the WAA shift per player group, then each
         group of constants swapped on its own (the marginal effect), and writes the per-player shifts.
         WAR = WAA + a constant per role, so the WAR shift is the WAA shift.
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, "tgs-viz", "backtest", ".dev_cache", "ssb_metadata")
BLM_JSON = os.path.join(REPO, "tgs-viz", "engine", "calib", "BLM", "metadata-latest.json")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def flatten(doc):
    """{(group, section, label, cell): value} of a metadata-latest.json."""
    return {(g, e["section"], e["label"], e["cell"]): e["value"] for g, lst in doc["groups"].items() for e in lst}


def comparison_table(blm, se, alt=None):
    """One row per constant. d = SSB - BLM, pct = d as a percent of |BLM| (NaN when BLM is 0)."""
    a, b = flatten(blm), flatten(se)
    c = flatten(alt) if alt else {}
    rows = []
    for k, v in a.items():
        row = dict(zip(("group", "section", "label", "cell"), k))
        row.update(BLM=v, SSB=b.get(k), d=b.get(k) - v, pct=100.0 * (b.get(k) - v) / abs(v) if v else np.nan)
        if alt:
            row.update(SSB_alt=c.get(k), d_alt=c.get(k) - v, pct_alt=100.0 * (c.get(k) - v) / abs(v) if v else np.nan,
                       vintage_d=c.get(k) - b.get(k))
        rows.append(row)
    return pd.DataFrame(rows)


def cmd_table(a):
    se = load_json(os.path.join(a.se, "metadata-latest.json"))
    alt = load_json(os.path.join(a.alt, "metadata-latest.json")) if a.alt else None
    df = comparison_table(load_json(BLM_JSON), se, alt)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, "metadata_comparison.csv"), index=False)
    pd.set_option("display.width", 220, "display.max_rows", 400, "display.float_format", lambda x: f"{x:.4g}")
    print(df.to_string())


def shift_stats(j, d):
    """Per player group (all / H / SP / RP): n, mean, sd, mean |shift|, p5, p95, max |shift|, Spearman rho."""
    res = {}
    for kind in ("all", "H", "SP", "RP"):
        m = np.ones(len(j), bool) if kind == "all" else (j.kind == kind).values
        x, y, dd = j.WAA_a[m].astype(float), j.WAA_b[m].astype(float), d[m]
        ok = np.isfinite(x) & np.isfinite(y)
        x, y, dd = x[ok], y[ok], dd[ok]
        if len(dd):
            res[kind] = dict(n=int(len(dd)), mean=float(dd.mean()), sd=float(dd.std()), mad=float(dd.abs().mean()),
                             p5=float(dd.quantile(.05)), p95=float(dd.quantile(.95)), maxabs=float(dd.abs().max()),
                             rho=float(pd.Series(x.values).corr(pd.Series(y.values), method="spearman")))
    return res


def cmd_pricing(a):
    for p in ("tgs-viz/ingest", "tgs-viz/engine", "tgs-viz/tools"):
        sys.path.insert(0, os.path.join(REPO, p))
    import ratings as R            # noqa: E402
    import statsplus as S          # noqa: E402
    import sync_datapoints as SD   # noqa: E402
    P = R.P
    hpath = os.path.join(REPO, "The Sheets BLM", "The Sheet Hitters.xlsx")
    ppath = os.path.join(REPO, "The Sheets BLM", "The Sheet Pitchers.xlsx")
    hdp0, hfilt, hpark = R._scan_consts_cached(hpath)
    pdp0, pfilt, ppark = P.scan_consts(ppath)
    Hv, Pv = SD.load_vals(hpath, "Data Points"), SD.load_vals(ppath, "Data Points")
    REG = SD.load_vals(os.path.join(REPO, "The Sheets BLM", "25 Regressions.xlsx"), "Data Points")
    blm = load_json(BLM_JSON)
    live = {k: v for k, v in blm["cells"].items() if v is not None and v != ""}
    meta = [m for m in SD.build_mapping(Hv, Pv, REG, live) if m["src"] == "MET"]
    cell_group = {e["cell"]: (g, e["section"]) for g, lst in blm["groups"].items() for e in lst}

    def variant(cells, only=None):
        hd, pd_ = dict(hdp0), dict(pdp0)
        for m in meta:
            v = cells.get(m["sc"])
            if (only is None or only(m)) and isinstance(v, (int, float)) and not isinstance(v, bool):
                (hd if m["ts"] == "H" else pd_)[m["tc"]] = float(v)
        return hd, pd_

    pull = load_json(os.path.join(REPO, "tgs-viz", "ingest", ".cache", "statsplus_ssb.json"))
    rows = S.translate_rows(pull if isinstance(pull, list) else pull.get("rows") or pull.get("players"))
    is_pit = lambda r: str(r.get("POS", "")).upper() in ("SP", "RP", "CL")
    keep = (lambda r: True) if a.level == "all" else (lambda r: r.get("LgLvl") == a.level)
    hit_rows, pit_rows = [r for r in rows if not is_pit(r) and keep(r)], [r for r in rows if is_pit(r) and keep(r)]
    calib = "BLM"
    cur = R.with_hitter_cells(R.live_currency(calib), R.live_pos_adj("SSB"))
    tails, fld, sc, rs = R.live_hitter_tails(calib), R.live_fielding(calib), R.live_scurves(calib), R.live_role_stuff(calib)
    repl = R.live_replacement("SSB")

    def price(hd, pd_):
        R._HITTER_DP[calib] = hdp0                       # the park chain reads BLM's constants, unchanged
        orig_h, orig_p = R._scan_consts_cached, P.scan_consts
        R._scan_consts_cached = lambda *x, **k: (dict(hd), dict(hfilt), dict(hpark))
        P.scan_consts = lambda path: (dict(pd_), dict(pfilt), ppark)
        try:
            h = R.run_hitters(hit_rows, calib, currency=cur, tails=tails, fielding=fld, park_mode="neutral", replacement=repl)
            p = R.run_pitchers(pit_rows, calib, scurves=sc, currency=cur, park_mode="neutral", role_stuff=rs,
                               observed=False, replacement=repl)
        finally:
            R._scan_consts_cached, P.scan_consts = orig_h, orig_p
        role = ["RP" if str(r["POS"]).upper() in ("RP", "CL") else "SP" for r in p]
        out = pd.DataFrame({
            "ID": [r["ID"] for r in h] + [r["ID"] for r in p],
            "Name": [r["Name"] for r in h] + [r["Name"] for r in p],
            "POS": [r["POS"] for r in h] + [r["POS"] for r in p],
            "kind": ["H"] * len(h) + role,
            "WAA": [r["Max WAA wtd"] for r in h] + [r["WAA wtd RP"] if k == "RP" else r["WAA wtd"] for r, k in zip(p, role)]})
        out["WAA"] = pd.to_numeric(out["WAA"], errors="coerce")
        return out

    def shift(base, other):
        j = base.merge(other, on=["ID", "kind"], suffixes=("_a", "_b"))
        return j, (j.WAA_b - j.WAA_a).astype(float)

    base = price(hdp0, pdp0)
    chk = price(*variant(live))
    print("sanity: BLM's own metadata laid over BLM's Data Points moves WAA by at most",
          float(np.nanmax((shift(base, chk)[1]).abs())))
    os.makedirs(os.path.join(OUT, "pricing_shift"), exist_ok=True)
    for label, d in (("season-end", a.se), ("alt", a.alt)):
        if not d:
            continue
        cells = {k: v for k, v in load_json(os.path.join(d, "metadata-latest.json"))["cells"].items() if v is not None and v != ""}
        j, dd = shift(base, price(*variant(cells)))
        print(f"\n{label} metadata swapped in ({a.level} level): WAA shift = SSB-metadata price - BLM-metadata price")
        for kind, s in shift_stats(j, dd).items():
            print(f"  {kind:3s}", {k: round(v, 4) for k, v in s.items()})
        j.assign(dWAA=dd).to_csv(os.path.join(OUT, "pricing_shift", f"shift_{label}_L{a.level}.csv"), index=False)
        if label == "season-end":
            print("  largest movers:")
            print(j.assign(dWAA=dd).reindex(dd.abs().sort_values(ascending=False).index).head(8)[
                ["Name_a", "POS_a", "WAA_a", "WAA_b", "dWAA"]].to_string())
            marginal = []
            for ts, g, sec in sorted({(m["ts"],) + cell_group.get(m["sc"], ("?", "?")) for m in meta}):
                pred = lambda m, ts=ts, g=g, sec=sec: m["ts"] == ts and cell_group.get(m["sc"], ("?", "?")) == (g, sec)
                jj, d2 = shift(base, price(*variant(cells, pred)))
                st = shift_stats(jj, d2)["all"]
                marginal.append(dict(sheet={"H": "hitter", "P": "pitcher"}[ts], group=g, section=sec,
                                     n_cells=sum(1 for m in meta if pred(m)), mean=st["mean"], sd=st["sd"], mad=st["mad"],
                                     p95_abs=float(d2.abs().quantile(.95)), rho=st["rho"]))
            mg = pd.DataFrame(marginal).sort_values("sd", ascending=False)
            mg.to_csv(os.path.join(OUT, "pricing_shift", f"group_effects_L{a.level}.csv"), index=False)
            print("\n  each group of constants swapped on its own (WAA shift, all players):")
            print(mg.round(4).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("what", choices=["table", "pricing"])
    ap.add_argument("--se", required=True, help="folder with the season-end build's metadata-latest.json")
    ap.add_argument("--alt", help="folder with a second build's metadata-latest.json")
    ap.add_argument("--level", default="1", help="pricing: LgLvl to price ('1' = MLB, 'all')")
    a = ap.parse_args()
    (cmd_table if a.what == "table" else cmd_pricing)(a)


if __name__ == "__main__":
    main()
