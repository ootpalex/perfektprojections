"""
park_values.py - hitter values in every club park, for the series lineup tool.

A playoff series locks ONE lineup vs RHP and ONE lineup vs LHP for all games,
and the games split between two parks. The lineup tool needs each hitter's
value in each park. This script projects the hitters of every club in
public/data/<LG>/parks.json (Lev MLB and AAA) in every club park at FULL
weight, and once on the neutral basis. It writes the compact file
public/data/<LG>/park_lineup_values.json.

Every number is an engine output: ratings.run_hitters with the club's raw
park factors passed as park_blend. One league per run. The leagues never mix.

The file holds, per hitter and per park (FIELDS order):
  dF_vR  dF_vL    change in '<POS> WAA' vs neutral for 1B 2B 3B SS LF CF RF
  dC_vR  dC_vL    change in 'C WAA' vs neutral
  dDH_vR dDH_vL   change in 'DH WAA' vs neutral
  wOBA_vR wOBA_vL OBP_vR OBP_vL   the park values themselves
Rebuild in the app:
  '<POS> WAA vR' in a park = hitters.json (neutral) value + the delta.
  Any wtd value = s * vR + (1 - s) * vL, with s = vr_share[B]
  (B = the hitter's bats; any other value reads vr_share['R']).

GATE. Park changes batting only, so the WAA change must be the same number at
1B 2B 3B SS LF CF RF (limit 1e-6). The build stops and writes nothing if it is
not. C and DH have their own lines in the engine (the catcher bats on the H32
PA basis and carries the park AB term; the DH has its own wOBA discount), so
each gets its own exact delta. The same gate checks the wtd rule above.

  python tgs-viz/ingest/park_values.py --league BLM            # dry run + gate
  python tgs-viz/ingest/park_values.py --league BLM --write    # write the file
  python tgs-viz/ingest/park_values.py --league BLM --verify   # read the file
        back, rebuild every position WAA, compare with a fresh engine run
"""
import os
import sys
import json
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ratings as R  # noqa: E402

REPO = os.path.dirname(os.path.dirname(HERE))
LEVELS = ("MLB", "AAA")
FIELD_POS = ("1B", "2B", "3B", "SS", "LF", "CF", "RF")
SPLITS = ("vR", "vL")
FIELDS = ["dF_vR", "dF_vL", "dC_vR", "dC_vL", "dDH_vR", "dDH_vL",
          "wOBA_vR", "wOBA_vL", "OBP_vR", "OBP_vL"]
GATE_TOL = 1e-6
WAA_DP = 4      # 0.0001 WAA
RATE_DP = 5     # 0.00001 wOBA / OBP (batting-order ranks read these)
OUT_NAME = "park_lineup_values.json"


class GateError(Exception):
    """The equal-change rule failed. Nothing is written."""


def _data_dir(league):
    return os.path.join(REPO, "tgs-viz", "public", "data", league)


def _rnd(x, dp):
    v = round(float(x), dp)
    return 0 if v == 0 else v        # no -0.0, and a bare 0 is shorter


def _write_json(obj, path):
    """Write through a .tmp file, then replace. The dev server can hold the
    target for a moment, so retry the replace a few times."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    last = None
    for _ in range(6):
        try:
            os.replace(tmp, path)
            return
        except OSError as e:
            last = e
            time.sleep(0.5)
    try:
        os.remove(tmp)
    except OSError:
        pass
    raise last


def _load(league, records=None):
    d = _data_dir(league)
    with open(os.path.join(d, "parks.json"), encoding="utf-8") as fh:
        parks = json.load(fh)
    if records is None:
        with open(os.path.join(d, "hitters.json"), encoding="utf-8") as fh:
            records = json.load(fh)
    clubs = {p["Name"] for p in parks}
    sel = [r for r in records if r.get("ORG") in clubs and r.get("Lev") in LEVELS]
    return parks, sel


def _engine_kw(league):
    # the live pipeline's own layers (refresh.py passes the same three)
    return dict(currency=R.live_currency(league), tails=R.live_hitter_tails(league),
                fielding=R.live_fielding(league))


def _vr_share(league):
    """The engine's platoon share by bats: wtd = s * vR + (1 - s) * vL."""
    dp = R._hitter_dp(league)
    return {"R": float(dp["H24"]), "L": float(dp["H23"]), "S": float(dp["H25"])}


def build(league, records=None, write=False, quiet=False):
    """Project, gate, and (with write=True) save. Returns a report dict.
    Raises GateError when the equal-change rule fails. Never calls sys.exit."""
    t0 = time.time()
    say = (lambda *a: None) if quiet else print
    parks, sel = _load(league, records)
    if not parks or not sel:
        raise ValueError(f"{league}: no parks ({len(parks)}) or no MLB/AAA hitters ({len(sel)})")
    kw = _engine_kw(league)
    share = _vr_share(league)
    neutral = {str(r["ID"]): r for r in R.run_hitters(sel, league, park_mode="neutral", **kw)}
    ids = list(neutral)
    values = {i: [] for i in ids}
    worst_field = worst_wtd = 0.0
    worst_c = worst_dh = 0.0         # informational: how far C / DH sit from the field change
    failures = []

    for pk in parks:
        club = pk["Name"]
        blend = {k: float(pk[k]) for k in R.PARK_FACTOR_KEYS}
        out = {str(r["ID"]): r for r in R.run_hitters(sel, league, park_blend=blend, **kw)}
        if set(out) != set(ids):
            raise ValueError(f"{league} / {club}: the engine returned a different hitter set than neutral")
        for i in ids:
            n, o = neutral[i], out[i]
            s = share.get((o.get("B") or "").strip(), share["R"])
            d = {}
            for suf in SPLITS + ("wtd",):
                ds = [o[f"{p} WAA {suf}"] - n[f"{p} WAA {suf}"] for p in FIELD_POS]
                spread = max(ds) - min(ds)
                worst_field = max(worst_field, spread)
                if spread > GATE_TOL and len(failures) < 20:
                    failures.append(f"{o.get('Name')} ({i}) in {club}, {suf}: " + ", ".join(
                        f"{p} {x:+.6f}" for p, x in zip(FIELD_POS, ds)))
                d["F", suf] = ds[0]
                d["C", suf] = o[f"C WAA {suf}"] - n[f"C WAA {suf}"]
                d["DH", suf] = o[f"DH WAA {suf}"] - n[f"DH WAA {suf}"]
            for suf in SPLITS:
                worst_c = max(worst_c, abs(d["C", suf] - d["F", suf]))
                worst_dh = max(worst_dh, abs(d["DH", suf] - d["F", suf]))
            # the wtd rule the app uses: s * vR + (1 - s) * vL
            devs = [abs(d[k, "wtd"] - (s * d[k, "vR"] + (1 - s) * d[k, "vL"])) for k in ("F", "C", "DH")]
            devs += [abs(o[f"{c} wtd"] - (s * o[f"{c} vR"] + (1 - s) * o[f"{c} vL"]))
                     for c in ("wOBA", "OBP")]
            worst_wtd = max(worst_wtd, max(devs))
            if max(devs) > GATE_TOL and len(failures) < 20:
                failures.append(f"{o.get('Name')} ({i}) in {club}: wtd is not s*vR + (1-s)*vL "
                                f"(off by {max(devs):.3e}, bats {o.get('B')!r})")
            values[i].append([
                _rnd(d["F", "vR"], WAA_DP), _rnd(d["F", "vL"], WAA_DP),
                _rnd(d["C", "vR"], WAA_DP), _rnd(d["C", "vL"], WAA_DP),
                _rnd(d["DH", "vR"], WAA_DP), _rnd(d["DH", "vL"], WAA_DP),
                _rnd(o["wOBA vR"], RATE_DP), _rnd(o["wOBA vL"], RATE_DP),
                _rnd(o["OBP vR"], RATE_DP), _rnd(o["OBP vL"], RATE_DP),
            ])

    report = {
        "league": league, "parks": len(parks), "hitters": len(ids),
        "gate_field_spread": worst_field, "gate_wtd_dev": worst_wtd,
        "c_vs_field": worst_c, "dh_vs_field": worst_dh, "written": None, "bytes": None,
    }
    if worst_field > GATE_TOL or worst_wtd > GATE_TOL:
        raise GateError(
            f"{league}: gate FAILED (field-position spread {worst_field:.3e}, wtd rule "
            f"{worst_wtd:.3e}, limit {GATE_TOL:g}). Nothing written.\n  " + "\n  ".join(failures))

    doc = {
        "league": league,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "basis": ("Engine values. Each park = that club's raw parks.json factors at full weight. "
                  "Deltas are park minus neutral (hitters.json)."),
        "levels": list(LEVELS),
        "field_positions": list(FIELD_POS),
        "fields": FIELDS,
        "vr_share": share,
        "gate": {"tolerance": GATE_TOL, "field_spread_max": worst_field, "wtd_rule_max": worst_wtd},
        "parks": [dict(club=p["Name"], park=p.get("park"), is_home=bool(p.get("is_home")),
                       **{k: float(p[k]) for k in R.PARK_FACTOR_KEYS}) for p in parks],
        # neutral wOBA vR / vL the deltas were measured from: lets the app see a
        # stale file (hitters.json moved on, this file did not)
        "neutral": {i: [_rnd(neutral[i]["wOBA vR"], RATE_DP), _rnd(neutral[i]["wOBA vL"], RATE_DP)]
                    for i in ids},
        "hitters": values,
    }
    path = os.path.join(_data_dir(league), OUT_NAME)
    size = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    report["bytes"] = size
    if write:
        _write_json(doc, path)
        report["written"] = path
    report["seconds"] = time.time() - t0
    say(f"{league}: {len(ids)} hitters (Lev {'/'.join(LEVELS)}) x {len(parks)} parks + neutral, "
        f"{report['seconds']:.1f}s")
    say(f"  gate OK: WAA change equal across {' '.join(FIELD_POS)} to {worst_field:.2e} "
        f"(limit {GATE_TOL:g}); wtd rule to {worst_wtd:.2e}")
    say(f"  own deltas kept for C (up to {worst_c:.3f} WAA from the field change) "
        f"and DH (up to {worst_dh:.3f})")
    say(f"  {'wrote' if write else '(dry run) would write'} {os.path.relpath(path, REPO)}  "
        f"{size / 1e6:.2f} MB" + ("" if write else "  - pass --write"))
    return report


def rebuild(doc, hitter, club, col):
    """One hitter record (hitters.json, neutral) -> his value for `col` in
    `club`'s park, from the file alone. col is '<POS> WAA vR|vL|wtd',
    'wOBA vR|vL|wtd' or 'OBP vR|vL|wtd'. The same rule the app applies."""
    pi = next(k for k, p in enumerate(doc["parks"]) if p["club"] == club)
    row = dict(zip(doc["fields"], doc["hitters"][str(hitter["ID"])][pi]))
    s = doc["vr_share"].get((hitter.get("B") or "").strip(), doc["vr_share"]["R"])
    head, suf = col.rsplit(" ", 1)

    def one(sp):
        if head in ("wOBA", "OBP"):
            return row[f"{head}_{sp}"]
        pos = head.split(" ")[0]
        key = "dC" if pos == "C" else "dDH" if pos == "DH" else "dF"
        return float(hitter[f"{pos} WAA {sp}"]) + row[f"{key}_{sp}"]

    return s * one("vR") + (1 - s) * one("vL") if suf == "wtd" else one(suf)


def verify(league):
    """Read the written file back, rebuild every position WAA / wOBA / OBP in
    every park from hitters.json + the file, compare with a fresh engine run."""
    path = os.path.join(_data_dir(league), OUT_NAME)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    parks, sel = _load(league)
    kw = _engine_kw(league)
    by_id = {str(r["ID"]): r for r in sel if str(r["ID"]) in doc["hitters"]}
    cols = [f"{p} WAA {s}" for p in FIELD_POS + ("C", "DH") for s in ("vR", "vL", "wtd")]
    cols += [f"{c} {s}" for c in ("wOBA", "OBP") for s in ("vR", "vL", "wtd")]
    worst, where = 0.0, None
    for pk in parks:
        out = R.run_hitters(list(by_id.values()), league, park_blend=pk, **kw)
        for o in out:
            h = by_id[str(o["ID"])]
            for col in cols:
                dev = abs(rebuild(doc, h, pk["Name"], col) - o[col])
                if dev > worst:
                    worst, where = dev, f"{o.get('Name')} / {pk['Name']} / {col}"
    print(f"{league}: read-back of {os.path.relpath(path, REPO)}: {len(by_id)} hitters x "
          f"{len(parks)} parks x {len(cols)} columns, worst rebuild error {worst:.2e} ({where})")
    return worst


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    league = sys.argv[sys.argv.index("--league") + 1] if "--league" in sys.argv else None
    if league not in ("TGS", "BLM"):
        print(__doc__)
        return 2
    try:
        if "--verify" in sys.argv:
            return 0 if verify(league) <= 10 ** -WAA_DP else 1
        build(league, write="--write" in sys.argv)
    except GateError as e:
        print(str(e))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
