"""
slot_shares.py - measure how a position's playing time is split across its depth chart
(1st / 2nd / 3rd ... player at the position), from real usage.

    python tgs-viz/tools/slot_shares.py                  tables
    python tgs-viz/tools/slot_shares.py --json out.json  also write the weights file

This is a port of ootp-dashboard model/tools/compute_slot_shares.py (same method), run on
the real-usage files this fork already has, so the weights are measured on BLM and SSB
rather than borrowed:

  per (team, position): rank players by innings at the position (hitters: fielding
  innings; SP / RP: innings pitched; DH: starts as designated hitter), take each rank's
  share of the team-position total, then average the share at each rank over team-seasons.
  The MEAN is used, as in the original: the share is left-skewed (a healthy starter
  carries ~0.7, an injury or platoon season pulls the mean down), so the mean already
  leans toward depth.

Sources (one entry per league-season, each team counted once):
  BLM 2057   backtest/actuals/BLM/2057 fielding / batting / pitching .csv (league 144, MLB)
             SP = pitcher-team rows with GS >= half of G, RP = the rest (a stated rule;
             checked against the StatsPlus SP/RP split on BLM 2058, see --check-role)
  BLM 2058   engine/calib/BLM/metadata_inputs Fielding_Data / SP_Data / RP_Data / Hitting_Data
  SSB 2043   ootp-dashboard leagues/SSB/metadata/2043 (OOTP 27)

DH has no innings; its usage is derived as batting starts minus fielding starts (a player
who started a game and was in no fielding slot started it as DH). Reported as derived.

Writes nothing unless --json is given. Changes no engine or app number. Stdlib + numpy.
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import eligibility_usage as EU  # noqa: E402  (shared parsing helpers)

VIZ = EU.VIZ
FIELD_POS = EU.FIELD_POS
# depth shown per group: the same depths the ootp-dashboard script emits
DEPTH = {"C": 4, "1B": 5, "2B": 5, "3B": 5, "SS": 5, "LF": 5, "CF": 5, "RF": 5, "DH": 4, "SP": 8, "RP": 10}
ORDER = list(FIELD_POS) + ["DH", "SP", "RP"]
EXCLUDE_ORG = {"-", "", "0", "--"}


# --------------------------------------------------------------- the method
def share_vectors(by_team):
    """by_team: {team: [usage per player]} -> list of descending share vectors (one per team
    with positive total usage). Players with no usage are dropped."""
    out = []
    for team, vals in by_team.items():
        v = np.sort(np.asarray([x for x in vals if x > 0], dtype=float))[::-1]
        if v.size and v.sum() > 0:
            out.append(v / v.sum())
    return out


def mean_curve(vecs, depth):
    """Mean share at ranks 1..depth over the vectors (a missing rank counts as 0), the
    mean tail share beyond `depth`, the standard error of each rank's mean, and n."""
    if not vecs:
        return {"shares": [0.0] * depth, "se": [0.0] * depth, "tail": 0.0, "n": 0}
    pad = np.zeros((len(vecs), depth))
    tail = np.zeros(len(vecs))
    for i, v in enumerate(vecs):
        pad[i, :min(depth, v.size)] = v[:depth]
        tail[i] = v[depth:].sum()
    n = len(vecs)
    return {"shares": pad.mean(axis=0).tolist(),
            "se": (pad.std(axis=0, ddof=1) / np.sqrt(n)).tolist() if n > 1 else [0.0] * depth,
            "tail": float(tail.mean()), "n": n}


# ------------------------------------------------------------------ loaders
def _csv_dicts(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _block_rows(path):
    """metadata_inputs sheets: a 'Player List' banner row, then the header, then rows."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "ID")
    hdr = rows[hi]
    return [dict(zip(hdr, r)) for r in rows[hi + 1:] if r and r[0]]


def _add(d, team, val):
    d.setdefault(team, []).append(val)


def load_actuals(league, year, league_id, viz=VIZ):
    """OOTP's own per-player season stats banked under backtest/actuals/<league>/<year>
    (MLB level, regular season). Teams are real team ids, so a traded player's usage stays
    with the team he played it for."""
    base = os.path.join(viz, "backtest", "actuals", league, str(year))
    usage = {p: {} for p in ORDER}
    fgs = {}                                   # (team, player) -> fielding starts, all positions
    for r in _csv_dicts(os.path.join(base, "fielding.csv")):
        if r["league_id"] != str(league_id) or r["level_id"] != "1":
            continue
        pos = EU.POS_CODE.get(int(r["position"]))
        if pos is None:
            continue
        _add(usage[pos], r["team_id"], int(r["ip"]) + int(r["ipf"]) / 3.0)
        fgs[(r["team_id"], r["player_id"])] = fgs.get((r["team_id"], r["player_id"]), 0) + int(r["gs"])
    for r in _csv_dicts(os.path.join(base, "batting.csv")):
        if r["league_id"] != str(league_id) or r["level_id"] != "1" or r["split_id"] != "1":
            continue
        k = (r["team_id"], r["player_id"])
        _add(usage["DH"], r["team_id"], max(int(r["gs"]) - fgs.get(k, 0), 0))
    for r in _csv_dicts(os.path.join(base, "pitching.csv")):
        if r["league_id"] != str(league_id) or r["level_id"] != "1" or r["split_id"] != "1":
            continue
        g, gs = int(r["g"]), int(r["gs"])
        # SP when he started at least half his appearances (the StatsPlus split is not in actuals)
        _add(usage["SP" if g > 0 and 2 * gs >= g else "RP"], r["team_id"], int(r["ip"]) + int(r["ipf"]) / 3.0)
    return usage


def _ip(x):
    return EU.ip_thirds(x)


def load_blm_2058(viz=VIZ):
    """BLM 2058 from the metadata exports (stats sit with each player's CURRENT org). The pitcher
    sheets cover only ~77% of team innings there (released / retired pitchers are dropped),
    so callers use this source for hitters only; see coverage()."""
    base = os.path.join(viz, "engine", "calib", "BLM", "metadata_inputs")
    usage = {p: {} for p in ORDER}
    # Fielding_Data: eight position blocks side by side; split them by the repeated header
    with open(os.path.join(base, "Fielding_Data.csv"), newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    hdr = rows[1]
    starts = [i for i, h in enumerate(hdr) if h == "ID"]
    width = starts[1] - starts[0]
    fgs = {}
    for s in starts:
        names = hdr[s:s + width - 1]
        for r in rows[2:]:
            cell = r[s:s + width - 1]
            if not cell or not cell[0]:
                continue
            d = dict(zip(names, cell))
            pos = EU.POS_CODE.get(int(float(d["POS"])))
            if pos is None or d["ORG"] in EXCLUDE_ORG:
                continue
            _add(usage[pos], d["ORG"], _ip(d["IP"]))
            fgs[(d["ORG"], d["ID"])] = fgs.get((d["ORG"], d["ID"]), 0) + int(float(d["GS"] or 0))
    for d in _block_rows(os.path.join(base, "Hitting_Data.csv")):
        if d["ORG"] in EXCLUDE_ORG:
            continue
        _add(usage["DH"], d["ORG"], max(int(float(d["GS"] or 0)) - fgs.get((d["ORG"], d["ID"]), 0), 0))
    for role, fname in (("SP", "SP_Data.csv"), ("RP", "RP_Data.csv")):
        for d in _block_rows(os.path.join(base, fname)):
            if d["ORG"] not in EXCLUDE_ORG:
                _add(usage[role], d["ORG"], _ip(d["IP"]))
    return usage


def load_ssb_2043(ootp_root):
    base = os.path.join(ootp_root, "leagues", "SSB", "metadata", "2043")
    usage = {p: {} for p in ORDER}
    fgs = {}
    for pos in FIELD_POS:
        for d in _csv_dicts(os.path.join(base, "fielding_data_%s.csv" % pos.lower())):
            if d["ORG"] in EXCLUDE_ORG:
                continue
            _add(usage[pos], d["ORG"], _ip(d["IP"]))
            fgs[(d["ORG"], d["ID"])] = fgs.get((d["ORG"], d["ID"]), 0) + int(float(d["GS"] or 0))
    for d in _csv_dicts(os.path.join(base, "hitting_data.csv")):
        if d["ORG"] in EXCLUDE_ORG:
            continue
        _add(usage["DH"], d["ORG"], max(int(float(d["GS"] or 0)) - fgs.get((d["ORG"], d["ID"]), 0), 0))
    for role, fname in (("SP", "sp_data.csv"), ("RP", "rp_data.csv")):
        for d in _csv_dicts(os.path.join(base, fname)):
            if d["ORG"] not in EXCLUDE_ORG:
                _add(usage[role], d["ORG"], _ip(d["IP"]))
    return usage


def role_rule_agreement(viz=VIZ):
    """BLM 2058: how often does 'SP iff GS >= G/2' agree with the StatsPlus SP_Data / RP_Data split?
    Returns (agree innings share, n rows)."""
    base = os.path.join(viz, "engine", "calib", "BLM", "metadata_inputs")
    ok = tot = 0.0
    n = 0
    for role, fname in (("SP", "SP_Data.csv"), ("RP", "RP_Data.csv")):
        for d in _block_rows(os.path.join(base, fname)):
            g, gs, ip = float(d["G"] or 0), float(d["GS"] or 0), _ip(d["IP"])
            rule = "SP" if g > 0 and 2 * gs >= g else "RP"
            tot += ip
            ok += ip if rule == role else 0
            n += 1
    return ok / tot, n


# -------------------------------------------------------------------- report
EXPECTED = {"hit": 1437.0, "DH": 162.0}      # full-season team innings in the field; DH starts


def coverage(usage):
    """Mean per-team total for a few groups, to show which sources cover a full season:
    hitters ~1440 field innings, DH ~162 starts, SP+RP ~1440 innings."""
    teams = set(usage["C"])
    tot = lambda p: float(np.mean([sum(v) for t, v in usage[p].items() if t in teams] or [0]))
    return {"C": tot("C"), "DH": tot("DH"), "SP+RP": tot("SP") + tot("RP")}


def curves(usage, groups=ORDER):
    """Depth curves per group. Only teams that field a catcher count (drops the 'Retired'
    pseudo-org in the 2058 export)."""
    teams = set(usage["C"])
    return {p: mean_curve(share_vectors({t: v for t, v in usage[p].items() if t in teams}), DEPTH[p])
            for p in groups}


def pooled_curves(parts):
    """parts: [(usage, groups)] pooled one vector per team-season."""
    pooled = {}
    for p in ORDER:
        vecs = []
        for u, groups in parts:
            if p in groups:
                teams = set(u["C"])
                vecs += share_vectors({t: v for t, v in u[p].items() if t in teams})
        pooled[p] = mean_curve(vecs, DEPTH[p])
    return pooled


HITTERS = list(FIELD_POS)
ALL = ORDER


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ootp-root", default=os.environ.get("OOTP_DASHBOARD", "/Users/alex/Projects/ootp/dashboard/ootp-dashboard"))
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    src = {"BLM2057": load_actuals("BLM", 2057, 144), "BLM2058": load_blm_2058(),
           "TGS2044": load_actuals("TGS", 2044, 100), "SSB2043": load_ssb_2043(a.ootp_root)}
    use = {"BLM2057": ALL, "BLM2058": HITTERS, "TGS2044": ALL, "SSB2043": ALL}
    print("coverage (mean per team): %s" % {k: {g: round(v) for g, v in coverage(u).items()} for k, u in src.items()})
    agree, n = role_rule_agreement()
    print("SP/RP rule (GS >= G/2) vs StatsPlus split on BLM 2058: %.1f%% of innings agree over %d pitchers" % (100 * agree, n))
    res = {k: curves(src[k], use[k]) for k in src}
    leagues = {"BLM": pooled_curves([(src["BLM2057"], ALL), (src["BLM2058"], HITTERS)]),
               "SSB": pooled_curves([(src["SSB2043"], ALL)]),
               "TGS": pooled_curves([(src["TGS2044"], ALL)]),
               "ALL": pooled_curves([(src[k], use[k]) for k in src])}
    for k, c in list(res.items()) + list(leagues.items()):
        print("\n== %s ==" % k)
        for p in ORDER:
            if p in c:
                print("  %-3s n=%2d  %s  tail %.3f" % (p, c[p]["n"], " ".join("%.3f" % x for x in c[p]["shares"]), c[p]["tail"]))
    if a.json:
        out = {"gated": "NOT read by the engine or the app; see docs/phase2/slot_shares.md",
               "method": "mean over team-seasons of each depth rank's share of the team-position total; tools/slot_shares.py",
               "depth": DEPTH, "leagues": leagues, "sources": res,
               "role_rule_agreement_blm2058": {"innings_share": agree, "pitchers": n}}
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
