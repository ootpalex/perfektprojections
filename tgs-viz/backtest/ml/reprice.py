"""
reprice.py - price every DEV vintage with one league's engine calibration.

Why: the DEV machine-learning rows read now / ceiling WAA from the engine. The
existing DEV prices (vintages/DEV/.waa_cache/*.197c3f18ed-BLM.json) use the BLM
calibration. TGS and BLM are 100 percent separate leagues, so the TGS model
must learn from DEV priced with the TGS calibration, and the BLM model from DEV
priced with the BLM one. User, 2026-09-24: "is there any way you can make a
machine learning model to help with figuring out this dev stuff".

How: the same steps as engine/agecurve_fit.py vintage_waa, line for line:
  - agecurve_fit.load_vintage + agecurve_fit.to_records (same record shape)
  - static traits (bats / throws / height) from the DEV raw dumps
    (vintages/DEV/raw_<year>.json.gz, read oldest first, the latest row wins),
    the agecurve_fit rule for a league with no shipped pull
  - ingest/ratings.py run_hitters / run_pitchers on the NEUTRAL park, with the
    calibration's live currency, hitter tails, fielding curves and S-curves
  - one record per player: [now, ceil, kind, age, org, stu_p, ht_p, pow_p]

Where it writes (never into vintages/DEV/.waa_cache):
  --calib TGS   .dev_cache/ml/waa_TGS/<vintage>.<TGS fingerprint>-TGS.json
  --out DIR     any other folder (the port check writes BLM prices to scratch)
The folder's _manifest.json keys each file by the vintage's size and mtime and
the calibration fingerprint: a run prices only what is new or changed.
dev_odds.py, dataset.py and others read "the newest file per vintage" in
vintages/DEV/.waa_cache, so a TGS file there would silently change the app.

Interpreter: the default python (3.13). The engine needs openpyxl and numpy
only; it reads the league workbook constants (The Sheets <LG>/*.xlsx).

CLI:
  python reprice.py --calib TGS                          price all 148 vintages
  python reprice.py --calib BLM --out DIR --only 2026-01-01_p74,2100-01-01_p148
  python reprice.py --calib BLM --out DIR --only ... --check
        --check compares each written file with the vintages/DEV/.waa_cache
        file of the same calibration fingerprint (max abs difference)
  --workers N   worker processes (default: logical CPUs minus 8, at most 20)
  --force       ignore the manifest and price again
"""
import argparse
import glob
import gzip
import json
import math
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))              # tgs-viz/backtest/ml
BT = os.path.dirname(HERE)                                      # tgs-viz/backtest
VIZ = os.path.dirname(BT)                                       # tgs-viz
ENGINE = os.path.join(VIZ, "engine")
DEV_VINT = os.path.join(BT, "vintages", "DEV")
DEV_WAA_DIR = os.path.join(DEV_VINT, ".waa_cache")
ML_ROOT = os.path.join(BT, ".dev_cache", "ml")
LEAGUE = "DEV"
MANIFEST = "_manifest.json"

sys.path.insert(0, ENGINE)
import agecurve_fit as AF                                       # noqa: E402  (imports ingest/ratings as R)

R = AF.R


def default_out(calib):
    """.dev_cache/ml/waa_<calib>/ (the TGS basis lives there)."""
    return os.path.join(ML_ROOT, f"waa_{calib}")


def cache_tag(calib):
    """File tag the way agecurve_fit.main builds it for a borrowed calibration:
    '<fingerprint>-<calib>' (DEV has no calibration of its own)."""
    return AF.calib_fingerprint(calib) + ("" if calib == LEAGUE else f"-{calib}")


def load_static():
    """{pid: {B, T, HT}} from the DEV raw dumps, oldest first, the latest row
    wins. Same code as agecurve_fit.main's no-shipped-pull branch."""
    static = {}
    for rp in sorted(glob.glob(os.path.join(DEV_VINT, "raw_*.json.gz"))):
        with gzip.open(rp, "rt", encoding="utf-8") as fh:
            for r in json.load(fh):
                ht = r.get("Height") or r.get("HT")
                try:
                    ht = float(ht) if ht not in (None, "") else None
                except ValueError:
                    ht = None
                static[str(r.get("ID"))] = {"B": r.get("Bats") or r.get("B"),
                                            "T": r.get("Throws") or r.get("T"), "HT": ht}
    return static


def price_vintage(path, static, calib):
    """{pid: [now, ceil, kind, age, org, stu_p, ht_p, pow_p]} for one vintage.
    The body of agecurve_fit.vintage_waa without its cache read / write."""
    vint = AF.load_vintage(path)
    hit, pit = AF.to_records(vint, static)
    league = calib
    cur = R.live_currency(league)
    out = {}
    hrecs = R.run_hitters(hit, league, currency=cur, tails=R.live_hitter_tails(league),
                          fielding=R.live_fielding(league), park_mode="neutral")
    for r in hrecs:
        out[str(r["ID"])] = [AF._num(r.get("Max WAA wtd")), AF._num(r.get("MAX WAA P")), "H"]
    precs = R.run_pitchers(pit, league, scurves=R.live_scurves(league), currency=cur,
                           park_mode="neutral", role_stuff=R.live_role_stuff(league),
                           observed=False)       # DEV players: never the league's own switch table
    for r in precs:
        now = max([x for x in (AF._num(r.get("WAA wtd")), AF._num(r.get("WAA wtd RP")))
                   if x is not None], default=None)
        ceil = max([x for x in (AF._num(r.get("WAP")), AF._num(r.get("WAP RP")))
                    if x is not None], default=None)
        out[str(r["ID"])] = [now, ceil, "P"]
    for pid, entry in out.items():
        v = vint.get(pid, {})
        entry.extend([v.get("age"), v.get("org"),
                      AF._num(v.get("c_STU_P")), AF._num(v.get("c_HT_P")), AF._num(v.get("c_POW_P"))])
    return out


# ---------------------------------------------------------------- workers
_STATIC = None


def _init(static_path):
    global _STATIC
    with open(static_path, encoding="utf-8") as fh:
        _STATIC = json.load(fh)


def _work(job):
    path, calib, dest = job
    t0 = time.time()
    out = price_vintage(path, _STATIC, calib)
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    os.replace(tmp, dest)
    return os.path.basename(path), len(out), time.time() - t0


# ---------------------------------------------------------------- check
def compare(mine_path, ref_path):
    """(n players both, only mine, only ref, max abs diff over the numeric
    fields, count of differing non-numeric fields)."""
    with open(mine_path, encoding="utf-8") as fh:
        a = json.load(fh)
    with open(ref_path, encoding="utf-8") as fh:
        b = json.load(fh)
    both = set(a) & set(b)
    mx, other = 0.0, 0
    for pid in both:
        x, y = a[pid], b[pid]
        if len(x) != len(y):
            other += 1
            continue
        for u, v in zip(x, y):
            if isinstance(u, (int, float)) and isinstance(v, (int, float)) \
                    and not isinstance(u, bool) and not isinstance(v, bool):
                if math.isfinite(u) and math.isfinite(v):
                    mx = max(mx, abs(u - v))
                elif not (u == v or (math.isnan(u) and math.isnan(v))):
                    other += 1
            elif u != v:
                other += 1
    return len(both), len(set(a) - set(b)), len(set(b) - set(a)), mx, other


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Price the DEV vintages with one league's engine calibration.")
    ap.add_argument("--calib", required=True, choices=("TGS", "BLM"))
    ap.add_argument("--out", help="output folder (default .dev_cache/ml/waa_<calib>)")
    ap.add_argument("--only", help="comma list of vintage names (with or without .csv.gz)")
    ap.add_argument("--workers", type=int, default=max(1, min(20, (os.cpu_count() or 8) - 8)))
    ap.add_argument("--force", action="store_true", help="ignore the manifest")
    ap.add_argument("--check", action="store_true",
                    help="compare each file with the vintages/DEV/.waa_cache file of the same fingerprint")
    args = ap.parse_args(argv)
    calib = args.calib
    out_dir = os.path.abspath(args.out or default_out(calib))
    if os.path.normcase(out_dir) == os.path.normcase(os.path.abspath(DEV_WAA_DIR)):
        raise SystemExit("refusing to write into vintages/DEV/.waa_cache: the app reads the newest file there")
    os.makedirs(out_dir, exist_ok=True)
    tag = cache_tag(calib)

    files = sorted(glob.glob(os.path.join(DEV_VINT, "*.csv.gz")))
    if args.only:
        want = {w.strip().replace(".csv.gz", "") for w in args.only.split(",") if w.strip()}
        files = [f for f in files if os.path.basename(f).replace(".csv.gz", "") in want]
    man_path = os.path.join(out_dir, MANIFEST)
    try:
        with open(man_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}

    jobs, skipped = [], 0
    for f in files:
        base = os.path.basename(f)
        dest = os.path.join(out_dir, f"{base}.{tag}.json")
        stamp = {"size": os.path.getsize(f), "mtime": int(os.path.getmtime(f)), "tag": tag}
        m = manifest.get(base)
        if not args.force and os.path.isfile(dest) and m and all(m.get(k) == v for k, v in stamp.items()):
            skipped += 1
            continue
        jobs.append((f, calib, dest, stamp))
    print(f"reprice: {len(files)} DEV vintages, calibration {calib}, tag {tag}, out {out_dir}", flush=True)
    print(f"  {skipped} already priced (manifest match), {len(jobs)} to price, {args.workers} workers", flush=True)

    t0 = time.time()
    if jobs:
        ts = time.time()
        static = load_static()
        static_path = os.path.join(out_dir, "_static.json.tmp")
        with open(static_path, "w", encoding="utf-8") as fh:
            json.dump(static, fh)
        print(f"  static traits: {len(static)} players from the raw dumps [{time.time() - ts:.0f}s]", flush=True)
        n_workers = max(1, min(args.workers, len(jobs)))
        stamps = {os.path.basename(f): s for f, _c, _d, s in jobs}
        done = 0
        try:
            with mp.Pool(n_workers, initializer=_init, initargs=(static_path,)) as pool:
                for base, n, secs in pool.imap_unordered(_work, [(f, c, d) for f, c, d, _s in jobs]):
                    done += 1
                    manifest[base] = dict(stamps[base], rows=n, seconds=round(secs, 1))
                    if done % 10 == 0 or done == len(jobs):
                        tmp = man_path + ".tmp"
                        with open(tmp, "w", encoding="utf-8") as fh:
                            json.dump(manifest, fh, indent=1, sort_keys=True)
                        os.replace(tmp, man_path)
                        print(f"  {done}/{len(jobs)} priced [{time.time() - t0:.0f}s]", flush=True)
        finally:
            try:
                os.remove(static_path)
            except OSError:
                pass
    print(f"  done in {time.time() - t0:.0f}s", flush=True)

    if args.check:
        print("\nPORT CHECK against vintages/DEV/.waa_cache (same fingerprint tag)")
        worst = 0.0
        for f in files:
            base = os.path.basename(f)
            mine = os.path.join(out_dir, f"{base}.{tag}.json")
            ref = os.path.join(DEV_WAA_DIR, f"{base}.{tag}.json")
            if not os.path.isfile(ref):
                print(f"  {base}: no reference file {os.path.basename(ref)}")
                continue
            n, only_a, only_b, mx, other = compare(mine, ref)
            worst = max(worst, mx)
            print(f"  {base}: players both {n}, only mine {only_a}, only reference {only_b}, "
                  f"max abs diff {mx:.3g}, other differing fields {other}")
        print(f"  worst max abs diff {worst:.3g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
