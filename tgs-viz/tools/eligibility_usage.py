"""
eligibility_usage.py - check the hitter position-eligibility floors against the
innings players really played at each position, and count what a different floor
would change in the shipped hitters.json.

    python tgs-viz/tools/eligibility_usage.py                 usage tables, all leagues
    python tgs-viz/tools/eligibility_usage.py --flips         + eligibility / Best Pos changes
    python tgs-viz/tools/eligibility_usage.py --json out.json write the numbers to a file

Read-only and offline: reads committed or already-banked files, writes nothing
unless --json is given. Changes no engine number. The engine rule it audits is
the `elig` dict in engine/hitters.py (compute()); the rule SETS in RULES are the
engine's current rule ("his"), the ootp-dashboard rule ("ours"), the rule Phase 2
proposes ("rec": corner OF floor 45) and two comparison sets ("lf40", "wide").
Nothing here switches the engine to any of them.

Usage data, per league-season (innings by position per player):
  BLM 2057   backtest/actuals/BLM/2057/fielding.csv (league 144, MLB), joined to
             the ratings of three in-season pulls (ratings_history.db pulls 2, 3, 4:
             2057-09-24, 10-02, 10-13), each a replicate of weight 1/3. For MLB fielders
             the three pulls agree on 98.6-100% of rows per rating (checked), so the
             replicates change the numbers by under 0.1 point; they are kept so a noisy
             pull cannot decide a floor. (Pull 1, 2057-07-27, is the nearest to the
             season start but has no rating for 7 of 1,260 player-positions; those
             count as failing and move RF < 45 from 0.4% to 3.3% of innings, so the
             primary uses pulls 2-4.)
  BLM 2058   engine/calib/BLM/metadata_inputs Fielding_Data + Fielding_Ratings.
  SSB 2043   ootp-dashboard leagues/SSB/metadata/2043 fielding_data_<pos>.csv +
             fielding_ratings.csv (the only OOTP 27 season).
Throws (T) is not in the ratings tables; it is joined from the league's shipped
hitters.json by player id (unknown -> the throws clause is skipped for that
player and the count is reported).

Stdlib + numpy only, like the engine.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VIZ = os.path.dirname(HERE)
REPO = os.path.dirname(VIZ)
DATA = os.path.join(VIZ, "public", "data")

POS_CODE = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
FIELD_POS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
RATING_KEYS = ("IF RNG", "IF ERR", "IF ARM", "TDP", "OF RNG", "OF ERR", "OF ARM", "C FRM")

# ---------------------------------------------------------------- rule sets
# Every floor the engine's `elig` dict uses, as data. None = clause absent.
# "his" is engine/hitters.py as of this commit; "ours" is
# ootp-dashboard model/src/hitters.py:compute_position_eligibility.
RULES = {
    "his": dict(c_frm=45,
                b1_ht=179, b1_rng=20, b1_err=None,
                b2_rng=50, b2_tdp=45,
                b3_rng=40, b3_arm=50,
                ss_rng=60, ss_arm=50, ss_tdp=None,
                lf=50, cf=60, rf=50),
    "ours": dict(c_frm=45,
                 b1_ht=179, b1_rng=20, b1_err=20,
                 b2_rng=50, b2_tdp=45,
                 b3_rng=40, b3_arm=50,
                 ss_rng=60, ss_arm=50, ss_tdp=45,
                 lf=45, cf=60, rf=45),
}
# Strict (>) clauses: 1B height, 1B IF RNG, 1B IF ERR. All others are >=.
# "rec": his rule with ONLY the corner-OF floor lowered 50 -> 45 (the one difference the usage
# data supports; see docs/phase2/eligibility.md). "lf40": same, corner floor 40.
# "wide": every floor moved to the highest 5-point step that excludes <= 3% of pooled real
# innings (implied_floors() below recomputes it). Nothing here is wired into the engine.
RULES["rec"] = dict(RULES["his"], lf=45, rf=45)
RULES["lf40"] = dict(RULES["his"], lf=40, rf=40)
RULES["wide"] = dict(RULES["his"], lf=45, rf=45, b2_rng=45, b3_arm=45, ss_rng=50, ss_arm=45, cf=55)


def clauses(t, pos, rule):
    """{clause name: boolean pass array} for `pos` under `rule` (a dict from RULES), one
    entry per condition in the engine's `elig` dict. Missing ratings (NaN) fail, as in the
    engine's comparisons. Unknown throws ('') passes the throws clause (the caller reports
    how many rows that is)."""
    r = rule
    throws_ok = (t["T"] == "R") | (t["T"] == "")
    c = {}
    if pos == "C":
        c["C FRM>=%s" % r["c_frm"]] = t["C FRM"] >= r["c_frm"]
    elif pos == "1B":
        # unknown height (player not in the league's hitters.json) passes: it is not evidence
        c["HT>%s" % r["b1_ht"]] = (t["HT"] > r["b1_ht"]) | np.isnan(t["HT"])
        c["IF RNG>%s" % r["b1_rng"]] = t["IF RNG"] > r["b1_rng"]
        if r["b1_err"] is not None:
            c["IF ERR>%s" % r["b1_err"]] = t["IF ERR"] > r["b1_err"]
    elif pos == "2B":
        c["IF RNG>=%s" % r["b2_rng"]] = t["IF RNG"] >= r["b2_rng"]
        c["T=R"] = throws_ok
        c["TDP>=%s" % r["b2_tdp"]] = t["TDP"] >= r["b2_tdp"]
    elif pos == "3B":
        c["IF RNG>=%s" % r["b3_rng"]] = t["IF RNG"] >= r["b3_rng"]
        c["IF ARM>=%s" % r["b3_arm"]] = t["IF ARM"] >= r["b3_arm"]
        c["T=R"] = throws_ok
    elif pos == "SS":
        c["IF RNG>=%s" % r["ss_rng"]] = t["IF RNG"] >= r["ss_rng"]
        c["IF ARM>=%s" % r["ss_arm"]] = t["IF ARM"] >= r["ss_arm"]
        c["T=R"] = throws_ok
        if r["ss_tdp"] is not None:
            c["TDP>=%s" % r["ss_tdp"]] = t["TDP"] >= r["ss_tdp"]
    elif pos in ("LF", "CF", "RF"):
        k = {"LF": "lf", "CF": "cf", "RF": "rf"}[pos]
        c["OF RNG>=%s" % r[k]] = t["OF RNG"] >= r[k]
    else:
        raise KeyError(pos)
    return c


def eligible(t, pos, rule):
    """Boolean array: every clause of `pos` passes under `rule`."""
    m = None
    for v in clauses(t, pos, rule).values():
        m = v if m is None else (m & v)
    return m


# The rating each position's floor is mainly a floor ON (for the candidate-floor
# tables): (label, table key). Secondary clauses are listed in CLAUSES.
CLAUSES = {
    "C":  [("C FRM", "C FRM")],
    "1B": [("IF RNG", "IF RNG"), ("IF ERR", "IF ERR"), ("HT cm", "HT")],
    "2B": [("IF RNG", "IF RNG"), ("TDP", "TDP")],
    "3B": [("IF RNG", "IF RNG"), ("IF ARM", "IF ARM")],
    "SS": [("IF RNG", "IF RNG"), ("IF ARM", "IF ARM"), ("TDP", "TDP"), ("IF ERR", "IF ERR")],
    "LF": [("OF RNG", "OF RNG")],
    "CF": [("OF RNG", "OF RNG")],
    "RF": [("OF RNG", "OF RNG")],
}


# ------------------------------------------------------------------- helpers
def ip_thirds(x):
    """OOTP prints innings as W.0 / W.1 / W.2 meaning W, W+1/3, W+2/3 outs.
    Accepts a string or number; returns float innings. '' -> 0."""
    s = str(x).strip()
    if s in ("", "nan", "None"):
        return 0.0
    whole, _, frac = s.partition(".")
    return int(whole or 0) + (int(frac[:1]) / 3.0 if frac else 0.0)


def ht_cm(s):
    """\"6' 2'\" or 6' 2\" -> cm, feet*30.48 + inches*2.54 (the engine's HT Sort)."""
    m = re.match(r"\s*(\d+)\s*'\s*(\d+)", str(s or ""))
    return int(m.group(1)) * 30.48 + int(m.group(2)) * 2.54 if m else float("nan")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return f


def build_table(rows):
    """rows: list of dicts with keys src, pid, pos, ip, w, T, HT and RATING_KEYS.
    Returns a dict of equal-length numpy arrays."""
    t = {"src": np.array([r["src"] for r in rows], dtype=object),
         "pid": np.array([str(r["pid"]) for r in rows], dtype=object),
         "pos": np.array([r["pos"] for r in rows], dtype=object),
         "T": np.array([r.get("T", "") or "" for r in rows], dtype=object)}
    for k in ("ip", "w", "HT") + RATING_KEYS:
        t[k] = np.array([_num(r.get(k)) for r in rows], dtype=float)
    return t


def subset(t, mask):
    return {k: v[mask] for k, v in t.items()}


def concat(tables):
    keys = tables[0].keys()
    return {k: np.concatenate([x[k] for x in tables]) for k in keys}


def wquantile(x, w, q):
    """Weighted quantile (midpoint convention, like gate_proposals.py): the
    smallest value whose cumulative weight share reaches q. Ratings are
    5-point steps, so the 'smallest value reaching q' reading is the right one."""
    ok = ~np.isnan(x) & (w > 0)
    x, w = x[ok], w[ok]
    if not len(x):
        return float("nan")
    o = np.argsort(x, kind="stable")
    x, w = x[o], w[o]
    cw = np.cumsum(w) / w.sum()
    return float(x[min(np.searchsorted(cw, q - 1e-12), len(x) - 1)])


# ---------------------------------------------------------------- loaders
def _hitters_json(lg, root=None):
    p = os.path.join(root or DATA, lg, "hitters.json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _throws_ht_from_json(lg, root=None):
    """{player id -> (throws, HT Sort cm)} from the league's shipped hitters.json."""
    out = {}
    for r in _hitters_json(lg, root):
        out[str(r.get("ID"))] = (r.get("T") or "", _num(r.get("HT Sort")))
    return out


def load_actuals(league, year, league_id, pulls, src, viz=VIZ, ratings_db=None):
    """MLB fielding actuals (backtest/actuals/<league>/<year>) x ratings_history.db pulls.
    Each pull is a replicate with weight 1/len(pulls). Players with no row in a pull are skipped."""
    ratings_db = ratings_db or os.path.join(viz, "backtest", "ratings_history.db")
    th = _throws_ht_from_json(league, os.path.join(viz, "public", "data"))
    ip = {}
    with open(os.path.join(viz, "backtest", "actuals", league, str(year), "fielding.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r["league_id"] != str(league_id) or r["level_id"] != "1":
                continue
            pos = POS_CODE.get(int(r["position"]))
            if pos is None:
                continue
            # ip = whole innings, ipf = leftover outs (0, 1, 2) -> thirds
            ip[(r["player_id"], pos)] = ip.get((r["player_id"], pos), 0.0) + int(r["ip"]) + int(r["ipf"]) / 3.0
    con = sqlite3.connect("file:%s?mode=ro" % ratings_db, uri=True)
    rows = []
    cols = ("c_IF_RNG", "c_IF_ERR", "c_IF_ARM", "c_TDP", "c_OF_RNG", "c_OF_ERR", "c_OF_ARM", "c_C_FRM")
    ids = {pid for pid, _ in ip}
    for pull in pulls:
        ratings = {}
        for r in con.execute("SELECT player_id, %s FROM ratings WHERE pull_id=?" % ",".join(cols), (pull,)):
            if r[0] in ids:
                ratings[r[0]] = r[1:]
        for (pid, pos), inn in ip.items():
            if pid not in ratings:
                continue
            d = dict(zip(RATING_KEYS, ratings[pid]))
            thr, h = th.get(pid, ("", float("nan")))
            rows.append(dict(src=src, pid=pid, pos=pos, ip=inn, w=1.0 / len(pulls), T=thr, HT=h, **d))
    con.close()
    return build_table(rows)


def load_blm_2057(viz=VIZ, ratings_db=None, pulls=(2, 3, 4)):
    """BLM 2057: MLB fielding actuals x three in-season ratings pulls (2057-09-24, 10-02, 10-13)."""
    return load_actuals("BLM", 2057, 144, pulls, "BLM2057", viz, ratings_db)


def load_tgs_2044(viz=VIZ, ratings_db=None, pulls=(11, 21, 28)):
    """TGS 2044: MLB actuals x pulls from the season start (2044-02-22), the middle (07-04) and the
    end (10-03). Not pooled into the BLM / SSB recommendation sample; shown as a check because the
    corner-OF patch also changes TGS flags."""
    return load_actuals("TGS", 2044, 100, pulls, "TGS2044", viz, ratings_db)


def _read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


def _fielding_ratings_by_id(path):
    """metadata_inputs / SSB Fielding_Ratings: header on the 2nd row ('Player List' first)."""
    rows = _read_rows(path)
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "ID")
    hdr = rows[hi]
    out = {}
    for r in rows[hi + 1:]:
        if not r or not r[0]:
            continue
        d = dict(zip(hdr, r))
        out[d["ID"]] = d
    return out


def load_blm_2058(viz=VIZ):
    """BLM 2058: metadata_inputs Fielding_Data (8 side-by-side position blocks) x Fielding_Ratings."""
    base = os.path.join(viz, "engine", "calib", "BLM", "metadata_inputs")
    fr = _fielding_ratings_by_id(os.path.join(base, "Fielding_Ratings.csv"))
    th = _throws_ht_from_json("BLM", os.path.join(viz, "public", "data"))
    rows = _read_rows(os.path.join(base, "Fielding_Data.csv"))
    hdr = rows[1]
    # each block is the same header; blocks are separated by one empty column
    starts = [i for i, h in enumerate(hdr) if h == "ID"]
    width = starts[1] - starts[0] if len(starts) > 1 else len(hdr)
    out = []
    for s in starts:
        names = hdr[s:s + width - 1]
        for r in rows[2:]:
            cell = r[s:s + width - 1]
            if not cell or not cell[0]:
                continue
            d = dict(zip(names, cell))
            pos = POS_CODE.get(int(float(d["POS"])))
            if pos is None or d["ID"] not in fr:
                continue
            f = fr[d["ID"]]
            thr, _h = th.get(d["ID"], ("", float("nan")))
            out.append(dict(src="BLM2058", pid=d["ID"], pos=pos, ip=ip_thirds(d["IP"]), w=1.0, T=thr,
                            HT=ht_cm(f.get("HT")), **{k: f.get(k) for k in RATING_KEYS}))
    return build_table(out)


def load_ssb_2043(ootp_root, viz=VIZ):
    """SSB 2043 (OOTP 27): fielding_data_<pos>.csv x fielding_ratings.csv, read from the
    ootp-dashboard checkout (`ootp_root`)."""
    base = os.path.join(ootp_root, "leagues", "SSB", "metadata", "2043")
    fr = _fielding_ratings_by_id(os.path.join(base, "fielding_ratings.csv"))
    th = _throws_ht_from_json("SSB", os.path.join(viz, "public", "data"))
    out = []
    for pos in FIELD_POS:
        with open(os.path.join(base, "fielding_data_%s.csv" % pos.lower()), newline="") as fh:
            for r in csv.DictReader(fh):
                if r["ID"] not in fr:
                    continue
                f = fr[r["ID"]]
                thr, _h = th.get(r["ID"], ("", float("nan")))
                out.append(dict(src="SSB2043", pid=r["ID"], pos=pos, ip=ip_thirds(r["IP"]), w=1.0, T=thr,
                                HT=ht_cm(f.get("HT")), **{k: f.get(k) for k in RATING_KEYS}))
    return build_table(out)


# ------------------------------------------------------------------ analysis
def population(t, pos, min_ip):
    """Rows of `pos` with at least `min_ip` innings there."""
    return subset(t, (t["pos"] == pos) & (t["ip"] >= min_ip))


def share_excluded(p, mask_pass):
    """(share of innings, share of player-seasons) held by rows that FAIL, weights applied."""
    ipw = p["ip"] * p["w"]
    tot_ip, tot_n = ipw.sum(), p["w"].sum()
    if tot_ip <= 0:
        return float("nan"), float("nan")
    fail = ~mask_pass
    return float(ipw[fail].sum() / tot_ip), float(p["w"][fail].sum() / tot_n)


def replicate_fail_shares(p, mask_pass):
    """Where a (player, position) appears in several ratings replicates (BLM 2057: three
    pulls), return (share of innings failing in ALL replicates, share failing in AT LEAST
    ONE). All-replicates is the floor the player is robustly below; the gap to at-least-one
    is scouting noise (about half of a hitter's rating slots differ between two pulls)."""
    key = np.array([a + "|" + b + "|" + c for a, b, c in zip(p["src"], p["pid"], p["pos"])], dtype=object)
    _, first, inv = np.unique(key, return_index=True, return_inverse=True)
    nrep = np.bincount(inv)
    nfail = np.bincount(inv, weights=(~mask_pass).astype(float))
    ip = p["ip"][first]
    tot = ip.sum()
    if tot <= 0:
        return float("nan"), float("nan")
    return float(ip[nfail == nrep].sum() / tot), float(ip[nfail > 0].sum() / tot)


def rating_quantiles(p, key, qs=(0.01, 0.05, 0.10, 0.25, 0.50)):
    w = p["ip"] * p["w"]
    return {q: wquantile(p[key], w, q) for q in qs}


def floor_table(p, key, floors, strict=False):
    """For each candidate floor f: share of innings / players with rating < f (>= f passes),
    or <= f for strict clauses (> f passes)."""
    out = {}
    for f in floors:
        passm = (p[key] > f) if strict else (p[key] >= f)
        out[f] = share_excluded(p, passm)
    return out


def team_innings_check(t, pos):
    """Innings at `pos` summed over all rows of one source (weight applied): should equal
    teams x games x ~9 innings, a coverage check on the usage file."""
    m = t["pos"] == pos
    return float((t["ip"][m] * t["w"][m]).sum())


# ---- eligibility / Best Pos changes on the shipped hitters.json ----------------
WAA_ORDER = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")      # engine's dict order (ties -> first)


def hitter_table(rows):
    """hitters.json rows -> table with RATING_KEYS, HT, T plus WAA columns."""
    t = {"T": np.array([r.get("T") or "" for r in rows], dtype=object),
         "HT": np.array([_num(r.get("HT Sort")) for r in rows], dtype=float)}
    for k in RATING_KEYS:
        t[k] = np.array([_num(r.get(k)) for r in rows], dtype=float)
    for pos in WAA_ORDER + ("DH",):
        t["WAA " + pos] = np.array([_num(r.get(pos + " WAA wtd")) for r in rows], dtype=float)
        t["WAAP " + pos] = np.array([_num(r.get(pos + " WAA P")) for r in rows], dtype=float)   # potential
    return t


def best_pos_and_max(t, elig, prefix="WAA "):
    """Vectorised Max WAA wtd and Best Pos over the eligible positions plus DH
    (engine/hitters.py: `max(pos for pos in elig if elig[pos], key=WAA wtd)`; ties keep
    the first in dict order). elig: {pos: bool array}. Returns (best index array, max array)."""
    cols = np.stack([np.where(elig[p], t[prefix + p], -np.inf) for p in WAA_ORDER]
                    + [t[prefix + "DH"]], axis=1)                  # DH is always eligible
    idx = np.argmax(cols, axis=1)                                   # argmax keeps the first of ties
    return idx, cols[np.arange(len(idx)), idx]


def flips(rows, rule_a, rule_b, mlb_only=True):
    """Compare rule_a with rule_b on a hitters.json row list. Returns counts."""
    sel = [r for r in rows if (r.get("Lev") == "MLB") or not mlb_only]
    t = hitter_table(sel)
    ea = {p: eligible(t, p, rule_a) for p in FIELD_POS}
    eb = {p: eligible(t, p, rule_b) for p in FIELD_POS}
    out = {"n": len(sel), "gained": {}, "lost": {}}
    changed = np.zeros(len(sel), dtype=bool)
    for p in FIELD_POS:
        out["gained"][p] = int((~ea[p] & eb[p]).sum())
        out["lost"][p] = int((ea[p] & ~eb[p]).sum())
        changed |= ea[p] != eb[p]
    out["any_elig_change"] = int(changed.sum())
    ia, ma = best_pos_and_max(t, ea)
    ib, mb = best_pos_and_max(t, eb)
    names = np.array(list(WAA_ORDER) + ["DH"], dtype=object)
    valid = np.isfinite(ma) & np.isfinite(mb)          # rows without WAA columns (e.g. a free-agent list) have no Best Pos
    out["best_pos_changed"] = int(((names[ia] != names[ib]) & valid).sum())
    d = (mb - ma)[valid]
    out["max_waa_changed"] = int((np.abs(d) > 1e-12).sum())
    out["max_waa_delta_mean_of_changed"] = float(d[np.abs(d) > 1e-12].mean()) if (np.abs(d) > 1e-12).any() else 0.0
    # potential (MAX WAA P): same max over eligible positions on the 'WAA P' columns; rows
    # without potential ratings have no value and are skipped, as in the engine
    iap, map_ = best_pos_and_max(t, ea, "WAAP ")
    ibp, mbp = best_pos_and_max(t, eb, "WAAP ")
    okp = np.isfinite(map_) & np.isfinite(mbp)
    out["max_waa_p_changed"] = int((np.abs(mbp - map_)[okp] > 1e-12).sum())
    out["max_waa_p_rows"] = int(okp.sum())
    out["max_waa_delta_min"] = float(d.min()) if len(d) else 0.0
    out["max_waa_delta_max"] = float(d.max()) if len(d) else 0.0
    moves = {}
    moved = (names[ia] != names[ib]) & valid
    for a, b in zip(names[ia][moved], names[ib][moved]):
        moves["%s->%s" % (a, b)] = moves.get("%s->%s" % (a, b), 0) + 1
    out["best_pos_moves"] = dict(sorted(moves.items(), key=lambda kv: -kv[1]))
    return out


def reproduces_flags(rows, rule=RULES["his"]):
    """Check: do the shipped '<pos> Eligible' flags equal eligible() under `rule`?
    Returns {pos: number of rows that differ}."""
    t = hitter_table(rows)
    out = {}
    for pos in FIELD_POS:
        shipped = np.array([r.get(pos + " Eligible") in (True, 1, "TRUE", "True") for r in rows])
        out[pos] = int((shipped != eligible(t, pos, rule)).sum())
    return out


def reproduces_shipped(rows, rule=RULES["his"]):
    """Check: does best_pos_and_max under `rule` reproduce the shipped Best Pos and
    Max WAA wtd? Returns (n compared, n Best Pos mismatches, max |Max WAA diff|)."""
    t = hitter_table(rows)
    idx, mx = best_pos_and_max(t, {p: eligible(t, p, rule) for p in FIELD_POS})
    names = np.array(list(WAA_ORDER) + ["DH"], dtype=object)
    shipped_best = np.array([r.get("Best Pos") or "" for r in rows], dtype=object)
    shipped_max = np.array([_num(r.get("Max WAA wtd")) for r in rows], dtype=float)
    ok = np.isfinite(shipped_max)
    return int(ok.sum()), int((names[idx][ok] != shipped_best[ok]).sum()), \
        float(np.abs(mx[ok] - shipped_max[ok]).max()) if ok.any() else float("nan")


def reproduces_potential(rows, rule=RULES["his"]):
    """Same check for the potential line: MAX WAA P over eligible positions plus DH.
    Returns (rows compared, max |difference|)."""
    t = hitter_table(rows)
    _, mx = best_pos_and_max(t, {p: eligible(t, p, rule) for p in FIELD_POS}, "WAAP ")
    shipped = np.array([_num(r.get("MAX WAA P")) for r in rows], dtype=float)
    ok = np.isfinite(shipped) & np.isfinite(mx)
    return int(ok.sum()), float(np.abs(mx[ok] - shipped[ok]).max()) if ok.any() else float("nan")


# ------------------------------------------------------------------- report
GRID = list(range(20, 85, 5))

# clause key -> (rule dict key, strict) for the floors that are tables of ratings.
# strict clauses use ">" in the engine, so a rule value v means floor v+5 on the 5-pt grid.
FLOOR_KEYS = {
    ("C", "C FRM"): ("c_frm", False),
    ("1B", "IF RNG"): ("b1_rng", True), ("1B", "IF ERR"): ("b1_err", True),
    ("2B", "IF RNG"): ("b2_rng", False), ("2B", "TDP"): ("b2_tdp", False),
    ("3B", "IF RNG"): ("b3_rng", False), ("3B", "IF ARM"): ("b3_arm", False),
    ("SS", "IF RNG"): ("ss_rng", False), ("SS", "IF ARM"): ("ss_arm", False), ("SS", "TDP"): ("ss_tdp", False),
    ("LF", "OF RNG"): ("lf", False), ("CF", "OF RNG"): ("cf", False), ("RF", "OF RNG"): ("rf", False),
}


def _fmt_pct(x):
    return "  n/a" if x != x else "%5.1f%%" % (100 * x)


def implied_floors(t, max_excl=0.03, min_ip=45, grid=GRID):
    """For each (pos, rating) clause: the highest floor on the 5-point grid below which at most
    `max_excl` of the position's innings (players with >= min_ip there) fall. The 3% is a
    stated assumption (docs/phase2/eligibility.md), not a measured quantity. Returns
    {(pos, rating): floor}; a strict (">") clause's equivalent engine value is floor - 5."""
    out = {}
    for (pos, key) in FLOOR_KEYS:
        p = population(t, pos, min_ip)
        ft = floor_table(p, key, grid)
        ok = [f for f in grid if ft[f][0] <= max_excl]
        out[(pos, key)] = max(ok) if ok else grid[0]
    return out


def usage_report(t, label, min_ip=45, out=print):
    """Per position: population, rating quantiles, share of innings / players each rule excludes."""
    res = {}
    out("\n=== %s: players with >= %g IP at the position; shares are of innings (IP) and of players ===" % (label, min_ip))
    out("%-3s %6s %8s | %s" % ("pos", "n", "IP", " | ".join("%-17s" % ("rule " + k) for k in ("his", "ours", "rec", "wide"))))
    for pos in FIELD_POS:
        p = population(t, pos, min_ip)
        res[pos] = {"n": float(p["w"].sum()), "ip": float((p["ip"] * p["w"]).sum()), "rules": {}, "q": {}}
        cells = []
        for name in ("his", "ours", "rec", "wide"):
            ex = share_excluded(p, eligible(p, pos, RULES[name]))
            res[pos]["rules"][name] = ex
            cells.append("%s IP %s pl" % (_fmt_pct(ex[0]), _fmt_pct(ex[1])))
        out("%-3s %6.1f %8.0f | %s" % (pos, res[pos]["n"], res[pos]["ip"], " | ".join(cells)))
        for lab, key in CLAUSES[pos]:
            res[pos]["q"][lab] = rating_quantiles(p, key)
    return res


def clause_report(t, label, min_ip=45, out=print):
    """Per clause of the his and ours rules: share of innings failing it, and failing ONLY it."""
    out("\n--- %s: share of IP failing each clause (alone / only-this-clause) ---" % label)
    for pos in FIELD_POS:
        p = population(t, pos, min_ip)
        w = p["ip"] * p["w"]
        for name in ("his", "ours"):
            cl = clauses(p, pos, RULES[name])
            cells = []
            for c, m in cl.items():
                others = np.ones(len(m), dtype=bool)
                for c2, m2 in cl.items():
                    if c2 != c:
                        others &= m2
                cells.append("%s %s (only %s)" % (c, _fmt_pct(float(w[~m].sum() / w.sum())),
                                                  _fmt_pct(float(w[~m & others].sum() / w.sum()))))
            out("%-3s %-4s %s" % (pos, name, " | ".join(cells)))


def floor_report(t, label, min_ip=45, out=print):
    """Candidate-floor tables: share of the position's innings held by players BELOW each floor."""
    out("\n--- %s: share of IP at the position below each candidate floor (a floor f passes rating >= f) ---" % label)
    out("%-8s %-7s %s" % ("pos", "rating", " ".join("%5d" % f for f in GRID)))
    for (pos, key) in FLOOR_KEYS:
        p = population(t, pos, min_ip)
        ft = floor_table(p, key, GRID)
        out("%-8s %-7s %s" % (pos, key, " ".join("%5.1f" % (100 * ft[f][0]) for f in GRID)))


def flips_report(out=print):
    res = {}
    for lg in ("BLM", "SSB", "TGS", "RG"):
        rows = _hitters_json(lg)
        res[lg] = {"flags_reproduced_diffs": reproduces_flags(rows), "best_pos_reproduced": reproduces_shipped(rows),
                   "potential_reproduced": reproduces_potential(rows)}
        out("%s: MAX WAA P reproduced on %d rows, max |diff| %.2g" % ((lg,) + res[lg]["potential_reproduced"]))
        out("\n%s: shipped flags vs eligible(his): %s ; Best Pos mismatches / max |Max WAA diff| over %d rows: %s / %.2g"
            % (lg, res[lg]["flags_reproduced_diffs"], res[lg]["best_pos_reproduced"][0],
               res[lg]["best_pos_reproduced"][1], res[lg]["best_pos_reproduced"][2]))
        for scope, mlb in (("MLB", True), ("all", False)):
            for to in ("ours", "rec", "lf40", "wide"):
                f = flips(rows, RULES["his"], RULES[to], mlb)
                res[lg]["%s his->%s" % (scope, to)] = f
                out("  %-3s his->%-4s n=%d  gained %s  lost %s  any-flag-change=%d  Best Pos changed=%d  Max WAA changed=%d (min %.3f)  MAX WAA P changed=%d of %d  moves %s"
                    % (scope, to, f["n"], {k: v for k, v in f["gained"].items() if v},
                       {k: v for k, v in f["lost"].items() if v}, f["any_elig_change"],
                       f["best_pos_changed"], f["max_waa_changed"], f["max_waa_delta_min"], f["max_waa_p_changed"],
                       f["max_waa_p_rows"], f["best_pos_moves"]))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ootp-root", default=os.environ.get("OOTP_DASHBOARD", "/Users/alex/Projects/ootp/dashboard/ootp-dashboard"),
                    help="ootp-dashboard checkout (SSB 2043 files)")
    ap.add_argument("--ratings-db", default=os.path.join(VIZ, "backtest", "ratings_history.db"),
                    help="ratings_history.db (gitignored: pass the main checkout's copy from a worktree)")
    ap.add_argument("--min-ip", type=float, default=45.0)
    ap.add_argument("--flips", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)

    tabs = {"BLM2057": load_blm_2057(ratings_db=a.ratings_db), "BLM2058": load_blm_2058(),
            "SSB2043": load_ssb_2043(a.ootp_root)}
    pooled = concat(list(tabs.values()))
    tgs = load_tgs_2044(ratings_db=a.ratings_db)
    res = {}
    for k, t in list(tabs.items()) + [("POOLED", pooled), ("TGS2044 (check, not pooled)", tgs)]:
        res[k] = usage_report(t, k, a.min_ip)
        clause_report(t, k, a.min_ip)
    floor_report(pooled, "POOLED (BLM 2057 + BLM 2058 + SSB 2043)", a.min_ip)
    imp = implied_floors(pooled, 0.03, a.min_ip)
    print("\nImplied floors (highest 5-pt floor excluding <= 3%% of pooled IP): %s"
          % {"%s %s" % k: v for k, v in imp.items()})
    res["implied_floors_3pct"] = {"%s %s" % k: v for k, v in imp.items()}
    if a.flips:
        res["flips"] = flips_report()
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
