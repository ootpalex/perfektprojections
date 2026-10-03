"""
pos_adj_multiyear.py - GATED candidate positional adjustments (P2..P10) from a
multi-season window: half ZR position-switcher (defence) + half offence, with
recency weights, a field-8 centring and a DH rule.

NOTHING IN THE ENGINE READS THIS. metadata_calibrate.py still derives P2..P10 from
one season of offence (pos_adj_calc). This module writes a separate calib file
(calib/<LG>/pos_adj_multiyear.json) for a decision to be made on; wiring it in is a
one-line overlay on metadata-latest.json's pos_adj cells, deliberately not done.
Audit and numbers: docs/phase2/pos_adj.md.

Method (ported from the dashboard's calibration research; every choice below that
is not computed from data is a user decision, named in the audit):
  OFFENCE half   his pos_adj_calc accumulation, run per season, pooled over the
                 window with recency weights. Per season, each player's OFF
                 (wRAA + BSR, his hitting_calc) is split across the positions he
                 played pro-rata by innings, with a PAIP/DH remainder; the
                 position value is -(sum apportioned OFF / sum innings) * standard
                 season. Pooling across seasons sums OFF and innings, each season
                 multiplied by its recency weight, so it is exact (an
                 innings-weighted mean of the per-season values), not an average
                 of rounded spectra.
  DEFENCE half   Tango/Zimmerman position-switcher on ZR. Every player who played
                 two of 1B,2B,3B,SS,LF,CF,RF in a season gives one observation:
                 spec[A] - spec[B] = ZRrate[B] - ZRrate[A], weight = harmonic mean
                 of his two innings. A weighted least squares over the window gives
                 7 relative position values. Catcher and DH cannot be rated this
                 way (catchers do not switch), so they come from offence only.
  BLEND          0.5 * defence + 0.5 * offence on the 7 switchable positions, both
                 centred on their own 7-position mean; C and DH from offence
                 (centred with the same 7-position offset); DH = min of all nine;
                 then shift all nine so the 8 field positions average to 0.
  UNITS          runs per STANDARD season of the engine: 1200 IP, catcher 1000 IP
                 (metadata_calibrate.STD_IP). The blend is formed in runs per 1200
                 IP for every position and C is scaled to its 1000 IP season last.

Stdlib + numpy only, like the rest of the engine.

  python pos_adj_multiyear.py --league BLM \\
      --season 2058=calib/BLM/metadata_inputs --season 2057=../backtest/actuals/BLM/2057 \\
      --engine-first-season 2058 --out calib/BLM/pos_adj_multiyear.json
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import metadata_calibrate as mc  # noqa: E402  (his loaders, hitting_calc, dollarde, STD_IP)

POSITIONS = mc.POSITIONS                       # C,1B,2B,3B,SS,LF,CF,RF
SEVEN = ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]       # the positions a player can switch among
NINE = POSITIONS + ["DH"]
PCELL = {"C": "P2", "1B": "P3", "2B": "P4", "3B": "P5", "SS": "P6",
         "LF": "P7", "CF": "P8", "RF": "P9", "DH": "P10"}
STD_ALL = 1200.0                                # common basis the blend is formed on
OOTP_DB_POS = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}

# Decision parameters (all deliberate assumptions, see the audit): defaults are the
# values the dashboard froze, so a first run reproduces the dashboard's design.
H_DEF, CUT_DEF = 5.0, 20       # defence recency half-life and window, in seasons
H_OFF, CUT_OFF = 2.5, 8        # offence recency half-life and window, in seasons
BLEND_W = 0.5                  # weight on the defence half
MIN_OBS = 200                  # fewer switcher observations than this: no defence half

# ------------------------------------------------------------------ season loading


def _stub_ratings():
    """hitting_calc also derives rating anchors and handedness shares from the two
    Batter_Ratings tables. Neither feeds OFF, so one all-ones row per batting hand and table satisfies
    its signature without needing a ratings export for the season."""
    cols = ["EYE vR", "POW vR", "K vR", "BA vR", "GAP vR", "EYE vL", "POW vL", "K vL",
            "BA vL", "GAP vL", "SPE", "STE", "RUN"]
    rows = []
    for n, hand in enumerate(("L", "R", "S")):   # the matchup shares divide by each hand's PA
        row = {"ID": str(n), "B": hand, "PA": "1"}
        row.update({c: "1" for c in cols})
        rows.append(row)
    return [dict(r) for r in rows], [dict(r) for r in rows]


def _season_from_tables(year, label, hit_rows, ip_by_pos, raw_ip, zr_by_pos, ipc=None, of_arm=None):
    """Assemble one season. hit_rows use Hitting_Data column names (R, PA, AB, 1B, ...,
    UBR, GIDP). ip_by_pos[pos][id] = clean innings, zr_by_pos[pos][id] = ZR runs.
    ipc[id] = the player's total fielding innings (Fielding_Ratings IP); when the
    source has no such table it is the sum of his eight position innings, which is the
    same number to the inning for every player the export covers (checked on BLM 2058:
    546 players, 345,667 vs 346,029 IP, 5 players absent from the ratings export)."""
    vr, vl = _stub_ratings()
    hc = mc.hitting_calc(hit_rows, vr, vl)
    if ipc is None:
        ipc = {}
        for pos in POSITIONS:
            for i, v in ip_by_pos[pos].items():
                ipc[i] = ipc.get(i, 0.0) + v
    return {"year": int(year), "label": label,
            "pa": hc["pa_by_id"], "off": hc["off_by_id"], "ipc": ipc,
            "ip": ip_by_pos, "raw_ip": raw_ip, "zr": zr_by_pos, "of_arm": of_arm or {},
            "lg": {"scale": hc["scale"], "lg_woba": hc["lg_woba"], "lg_wsb": hc["lg_wsb"],
                   "pa": hc["totals"]["PA"], "r": hc["totals"]["R"]}}


def load_sheet_layout(path, year):
    """calib/<LG>/metadata_inputs: his single-sheet exports (Fielding_Data is eight
    position tables side by side)."""
    p = lambda n: os.path.join(path, n)
    hit = mc.load_single(p("Hitting_Data.csv"))
    fld = mc.load_fielding(p("Fielding_Data.csv"))
    fr = mc.load_single(p("Fielding_Ratings.csv"))
    ip_by_pos = {pos: mc._by_id(fld[pos], lambda r: mc.dollarde(r["IP"])) for pos in POSITIONS}
    zr_by_pos = {pos: mc._by_id(fld[pos], lambda r: mc.num(r["ZR"])) for pos in POSITIONS}
    raw_ip = {pos: mc._sum(fld[pos], "IP") for pos in POSITIONS}
    ipc = mc._by_id(fr, lambda r: mc.dollarde(r["IP"]))
    of_arm = mc._by_id(fr, lambda r: mc.num(r["OF ARM"]))
    return _season_from_tables(year, os.path.basename(path.rstrip("/\\")), hit, ip_by_pos,
                               raw_ip, zr_by_pos, ipc, of_arm)


def _read_plain(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_split_layout(path, year):
    """The dashboard's per-season exports (leagues/<LG>/metadata/<year>): lower-case
    hitting_data.csv, fielding_ratings.csv and one fielding_data_<pos>.csv per position,
    headers on row 1. Same columns as the sheet exports.""" 
    hit = _read_plain(os.path.join(path, "hitting_data.csv"))
    of_arm = mc._by_id(_read_plain(os.path.join(path, "fielding_ratings.csv")), lambda r: mc.num(r["OF ARM"]))
    ip_by_pos, zr_by_pos, raw_ip = {}, {}, {}
    for pos in POSITIONS:
        rows = _read_plain(os.path.join(path, f"fielding_data_{pos.lower()}.csv"))
        ip_by_pos[pos] = mc._by_id(rows, lambda r: mc.dollarde(r["IP"]))
        zr_by_pos[pos] = mc._by_id(rows, lambda r: mc.num(r["ZR"]))
        raw_ip[pos] = mc._sum(rows, "IP")
    # fielding_ratings.csv is NOT used for the player's total innings here: SSB's 2042 and 2043
    # exports carry minor-league players (987 and 949 rows against ~500 MLB hitters), which
    # inflates innings-per-PA (m2 2.09-2.11 against 1.86 for the MLB-only 2041 export) and with
    # it the DH innings. The MLB-only Fielding_Data position innings are summed instead.
    return _season_from_tables(year, os.path.basename(path.rstrip("/\\")), hit, ip_by_pos,
                               raw_ip, zr_by_pos, None, of_arm)


def load_db_seasons(batting_csv, fielding_csv, league_id=None, level_id=1, years=None):
    """OOTP's own per-player season tables (backtest/actuals/<LG>/<year>/ and the
    dashboard's career pulls). MLB regular season: level_id 1, batting split_id 1,
    fielding split_id 0 or 1 (the export schema labels the same rows either way).
    Returns {year: season}. Innings are ip + ipf/3; the divisor quirk column is
    rebuilt as ip + ipf/10 to mirror OOTP's x.y notation."""
    bat, fld = {}, {}      # year -> {pid: row-accumulator}
    with open(batting_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["level_id"]) != level_id or int(r["split_id"]) != 1:
                continue
            if league_id is not None and int(r["league_id"]) != league_id:
                continue
            y = int(r["year"])
            if years is not None and y not in years:
                continue
            acc = bat.setdefault(y, {}).setdefault(int(r["player_id"]), {})
            for k in ("ab", "h", "d", "t", "hr", "bb", "ibb", "hp", "sf", "sh", "sb", "cs",
                      "k", "pa", "r", "gdp", "ubr"):
                acc[k] = acc.get(k, 0.0) + float(r[k] or 0)
    with open(fielding_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["level_id"]) != level_id or int(r["split_id"]) not in (0, 1):
                continue
            if league_id is not None and int(r["league_id"]) != league_id:
                continue
            y = int(r["year"])
            pos = OOTP_DB_POS.get(int(r["position"]))
            if pos is None or (years is not None and y not in years):
                continue
            acc = fld.setdefault(y, {}).setdefault(pos, {}).setdefault(int(r["player_id"]), [0.0, 0.0, 0.0])
            ip, ipf = float(r["ip"] or 0), float(r["ipf"] or 0)
            acc[0] += ip + ipf / 3.0
            acc[1] += ip + ipf / 10.0
            acc[2] += float(r["zr"] or 0)
    out = {}
    for y in sorted(bat):
        hit_rows = []
        for pid, a in bat[y].items():
            hit_rows.append({"ID": str(pid), "PA": a["pa"], "AB": a["ab"], "R": a["r"],
                             "1B": a["h"] - a["d"] - a["t"] - a["hr"], "2B": a["d"], "3B": a["t"],
                             "HR": a["hr"], "BB": a["bb"], "IBB": a["ibb"], "HP": a["hp"],
                             "SH": a["sh"], "SF": a["sf"], "SB": a["sb"], "CS": a["cs"],
                             "SO": a["k"], "UBR": a["ubr"], "GIDP": a["gdp"]})
        fy = fld.get(y, {})
        ip_by_pos = {p: {i: v[0] for i, v in fy.get(p, {}).items() if v[0] > 0} for p in POSITIONS}
        zr_by_pos = {p: {i: v[2] for i, v in fy.get(p, {}).items() if v[0] > 0} for p in POSITIONS}
        raw_ip = {p: float(sum(v[1] for v in fy.get(p, {}).values() if v[0] > 0)) for p in POSITIONS}
        out[y] = _season_from_tables(y, f"db:{os.path.basename(os.path.dirname(batting_csv))}",
                                     hit_rows, ip_by_pos, raw_ip, zr_by_pos)
    return out


def load_season(path, year, league_id=None):
    """Detect the layout of `path` and load one season."""
    names = set(os.listdir(path))          # exact names: macOS and Windows match case-insensitively
    if "Hitting_Data.csv" in names:
        return load_sheet_layout(path, year)
    if "hitting_data.csv" in names:
        return load_split_layout(path, year)
    if "batting.csv" in names:
        got = load_db_seasons(os.path.join(path, "batting.csv"), os.path.join(path, "fielding.csv"),
                              league_id=league_id, years={int(year)})
        if int(year) not in got:
            raise SystemExit(f"{path}: no MLB rows for {year} (league_id={league_id})")
        return got[int(year)]
    raise SystemExit(f"{path}: not a metadata_inputs folder, a dashboard metadata folder or an actuals folder")

# ------------------------------------------------------------------ offence half


def _arr(d, ids):
    out = np.zeros(len(ids))
    if d:
        keys = np.fromiter(d.keys(), dtype=np.int64, count=len(d))
        out[np.searchsorted(ids, keys)] = np.fromiter(d.values(), dtype=float, count=len(d))
    return out


def offense_accumulate(season, rf_quirk=True, thirds_quirk=True):
    """One season of his pos_adj_calc, stopped before the final division, so seasons can be
    pooled. Returns the apportioned OFF (runs) and the innings divisor per position, the
    DH equivalents, and m2 (innings per PA).

    rf_quirk: his RF branch test window includes RF's own innings and the OFF column, so an
      RF never takes the 'only position he played' branch (see metadata_calibrate docstring).
      True reproduces his numbers; False gives RF the same test as every other position.
    thirds_quirk: his divisors sum OOTP's x.y innings column as decimals (123.2 counts as
      123.2, not 123.667). True reproduces his numbers."""
    ids_set = set(season["pa"]) | set(season["ipc"])
    for pos in POSITIONS:
        ids_set |= set(season["ip"][pos])
    ids = np.array(sorted(ids_set), dtype=np.int64)
    pa, off, c2 = _arr(season["pa"], ids), _arr(season["off"], ids), _arr(season["ipc"], ids)
    ips = np.stack([_arr(season["ip"][p], ids) for p in POSITIONS])       # (8, n)
    m2 = c2.sum() / pa.sum()
    paip = pa * m2                       # PA expressed as equivalent innings
    dh_ip = np.maximum(paip - c2, 0.0)
    denom = np.maximum(c2, paip)
    tot = ips.sum(axis=0)
    pos_off = {}
    for k, p in enumerate(POSITIONS):
        played = ips[k] != 0
        if p == "RF" and rf_quirk:
            window = tot + off + dh_ip
        else:
            window = tot - ips[k] + dh_ip
        only = played & (window == 0)
        prorata = played & ~only
        numer = off * ips[k]
        bad = prorata & (denom == 0) & (numer != 0)
        if bad.any():
            raise ZeroDivisionError(f"POS Adj {p}: nonzero OFF over zero innings for {ids[bad][:5]}")
        frac = np.divide(numer, denom, out=np.zeros_like(numer), where=denom != 0)
        pos_off[p] = float(off[only].sum() + frac[prorata].sum())
    has_dh = dh_ip != 0
    dh_each = np.where(tot == 0, off, np.divide(off * dh_ip, denom, out=np.zeros_like(off), where=denom != 0))
    raw = season["raw_ip"] if thirds_quirk else {p: float(sum(season["ip"][p].values())) for p in POSITIONS}
    return {"pos_off": pos_off, "raw_ip": {p: float(raw[p]) for p in POSITIONS},
            "dh_off": float(dh_each[has_dh].sum()), "dh_ip": float(dh_ip[has_dh].sum()), "m2": float(m2)}


def offense_rates(acc):
    """From (pooled) accumulators to runs per STD_IP season per position. LF and RF are
    returned separately (his pos_adj_calc then averages them into one corner value)."""
    r = {p: -acc["pos_off"][p] / acc["raw_ip"][p] * mc.STD_IP[p] for p in POSITIONS}
    r["DH"] = -acc["dh_off"] / acc["dh_ip"] * 1200.0
    return r


def his_pos_adj(acc):
    """His pos_adj_calc output (P2..P10 as positions) from one season's accumulators:
    LF and RF both get the mean of the two corner rates."""
    r = offense_rates(acc)
    corner = (r["LF"] + r["RF"]) / 2.0
    r["LF"] = r["RF"] = corner
    return r


def pool_accumulators(accs_weights):
    """Recency-weighted sum of per-season accumulators: [(acc, weight), ...]."""
    tot = {"pos_off": {p: 0.0 for p in POSITIONS}, "raw_ip": {p: 0.0 for p in POSITIONS},
           "dh_off": 0.0, "dh_ip": 0.0}
    for acc, w in accs_weights:
        for p in POSITIONS:
            tot["pos_off"][p] += w * acc["pos_off"][p]
            tot["raw_ip"][p] += w * acc["raw_ip"][p]
        tot["dh_off"] += w * acc["dh_off"]
        tot["dh_ip"] += w * acc["dh_ip"]
    return tot

# ------------------------------------------------------------------ defence half (ZR switcher)


def switcher_obs(season, std_ip=STD_ALL):
    """All pairwise switch observations in one season. Arrays a, b (indices into SEVEN),
    target (= ZR rate at b minus at a, runs per std_ip), w (harmonic mean of the two
    innings). One row per player per pair of positions with innings at both.
    The 21 position pairs are looped; each pair is a vector over players."""
    ids_set = set()
    for p in SEVEN:
        ids_set |= set(season["ip"][p])
    ids = np.array(sorted(ids_set), dtype=np.int64)
    inn = np.stack([_arr(season["ip"][p], ids) for p in SEVEN])
    zr = np.stack([_arr(season["zr"][p], ids) for p in SEVEN])
    rate = np.divide(zr, inn, out=np.zeros_like(zr), where=inn > 0) * std_ip
    a_l, b_l, t_l, w_l = [], [], [], []
    for a in range(7):
        for b in range(a + 1, 7):
            m = (inn[a] > 0) & (inn[b] > 0)
            if not m.any():
                continue
            a_l.append(np.full(m.sum(), a))
            b_l.append(np.full(m.sum(), b))
            t_l.append(rate[b][m] - rate[a][m])
            w_l.append(2.0 * inn[a][m] * inn[b][m] / (inn[a][m] + inn[b][m]))
    if not a_l:
        z = np.zeros(0)
        return {"a": z.astype(int), "b": z.astype(int), "t": z, "w": z, "year": season["year"]}
    return {"a": np.concatenate(a_l), "b": np.concatenate(b_l), "t": np.concatenate(t_l),
            "w": np.concatenate(w_l), "year": season["year"]}


def _stack_obs(obs_list, end, half_life, cut):
    """Concatenate the seasons inside the window with recency-scaled weights."""
    a, b, t, w, y = [], [], [], [], []
    for o in obs_list:
        age = end - o["year"]
        if age < 0 or age >= cut:
            continue
        a.append(o["a"]); b.append(o["b"]); t.append(o["t"])
        w.append(o["w"] * (0.5 ** (age / half_life)))
        y.append(np.full(len(o["t"]), o["year"]))
    if not a:
        z = np.zeros(0)
        return z.astype(int), z.astype(int), z, z, z
    return (np.concatenate(a), np.concatenate(b), np.concatenate(t),
            np.concatenate(w), np.concatenate(y))


def _solve(a, b, t, w):
    """Weighted least squares for spec[A]-spec[B] = t. Accumulates the 7x7 normal equations
    (the system is rank-6: only differences are identified), takes the minimum-norm solution
    and centres it on the 7-position mean. Identical to lstsq on the dense sqrt(w)-weighted
    system, without building it."""
    A = np.zeros((7, 7))
    np.add.at(A, (a, a), w)
    np.add.at(A, (b, b), w)
    np.add.at(A, (a, b), -w)
    np.add.at(A, (b, a), -w)
    rhs = np.bincount(a, weights=w * t, minlength=7) - np.bincount(b, weights=w * t, minlength=7)
    sol = np.linalg.lstsq(A, rhs, rcond=None)[0]
    return sol - sol.mean()


def solve_switcher(obs_list, end, half_life=H_DEF, cut=CUT_DEF, min_obs=MIN_OBS):
    """Defence half: {pos: relative runs per 1200 IP} (mean 0 over SEVEN) or None when the
    window has fewer than min_obs switch observations."""
    a, b, t, w, _ = _stack_obs(obs_list, end, half_life, cut)
    if len(t) < min_obs:
        return None, len(t)
    sol = _solve(a, b, t, w)
    return {p: float(sol[i]) for i, p in enumerate(SEVEN)}, len(t)


def bootstrap_se(obs_list, end, half_life=H_DEF, cut=CUT_DEF, n_boot=1000, seed=20260529):
    """Standard error of each position's defence value: resample switch observations with
    replacement (multiplicity weights via bincount), refit, take the SD."""
    a, b, t, w, _ = _stack_obs(obs_list, end, half_life, cut)
    n = len(t)
    rng = np.random.default_rng(seed)
    sols = np.empty((n_boot, 7))
    for i in range(n_boot):
        m = np.bincount(rng.integers(0, n, n), minlength=n)
        sols[i] = _solve(a, b, t, w * m)
    return {p: float(sols[:, k].std(ddof=1)) for k, p in enumerate(SEVEN)}

# ------------------------------------------------------------------ blend


def blend(def7, off9, w=BLEND_W, lf_rf="split", level="field8", dh="min"):
    """def7: {pos: runs/1200 IP} on SEVEN or None. off9: offence {C,1B..RF,DH} in runs per 1200 IP
    (C already converted). Returns (nine, parts): nine = blended spectrum; parts has the
    intermediate stages for the audit.
    level "field8": the 8 field positions average 0 (the dashboard's centring).
    level "offence": the offence half's own level is kept (his metadata_calibrate convention:
      offence runs vs the league average, uncentred) - with w = 0 this returns off9 exactly.
    dh "min": DH tied to the lowest position (the dashboard). dh "offence": DH from offence
      only (his pos_adj_calc)."""
    off7_mean = sum(off9[p] for p in SEVEN) / 7.0
    offc = {p: v - off7_mean for p, v in off9.items()}
    out = {}
    for p in SEVEN:
        out[p] = (w * def7[p] + (1.0 - w) * offc[p]) if def7 is not None else offc[p]
    out["C"], out["DH"] = offc["C"], offc["DH"]
    if lf_rf == "pooled":
        out["LF"] = out["RF"] = (out["LF"] + out["RF"]) / 2.0
    elif lf_rf != "split":
        raise ValueError("lf_rf must be 'split' or 'pooled'")
    raw = dict(out)
    if dh == "min":
        out["DH"] = min(out["DH"], min(out[p] for p in POSITIONS))      # DH tied to the lowest position
    elif dh != "offence":
        raise ValueError("dh must be 'min' or 'offence'")
    if level == "field8":
        f8 = sum(out[p] for p in POSITIONS) / 8.0
    elif level == "offence":
        f8 = -off7_mean                                                 # put the offence level back
    else:
        raise ValueError("level must be 'field8' or 'offence'")
    final = {p: out[p] - f8 for p in NINE}
    return final, {"offence_centred": offc, "blend_before_dh_rule": raw, "field8_mean_removed": f8}


def to_engine_units(spec1200):
    """Runs per 1200 IP -> his standardized season (catcher 1000 IP)."""
    return {p: spec1200[p] * mc.STD_IP.get(p, 1200.0) / 1200.0 for p in NINE}

# ------------------------------------------------------------------ bestPos Option B inputs


def option_b_spectrum(res, anchor="SS"):
    """Defensive-only spectrum for the dashboard's 'Option B' best-position rule, from the
    result of pos_adj_multiyear (needs its defence half). Seven positions are the switcher
    values (mean 0 over the seven, runs per 1200 IP). Catchers do not switch, so C is imputed:
    the anchor position's defence value plus the blended C-minus-anchor gap,
        C = def[anchor] + (blend[C] - blend[anchor]),
    which keeps C on the league's own defensive scale. The dashboard anchors on SS (its
    highest switchable value in both leagues' histories); anchor=None takes the highest
    value in this window instead (CF in the 2057-2058 and 2041-2043 windows). Returned in the engine's units
    (C per 1000 IP, since the engine's catcher RunsP is a 1000 IP quantity)."""
    d = res["defence_runs_per_1200"]
    if d is None:
        raise ValueError("no defence half in this window (fewer than MIN_OBS switch observations)")
    top = anchor or max(SEVEN, key=lambda p: d[p])
    bl = res["spectrum_runs_per_1200"]
    spec = dict(d)
    spec["C"] = d[top] + (bl["C"] - bl[top])
    spec = {p: spec[p] * mc.STD_IP[p] / 1200.0 for p in POSITIONS}
    return spec, top


BESTPOS_ORDER = ["C", "SS", "CF", "2B", "3B", "LF", "RF", "1B"]     # hardest first: ties go to the harder spot


def option_b_best_pos(runs_p, eligible, spectrum, of_arm, arm_threshold, order=BESTPOS_ORDER):
    """The dashboard's 'Option B' best position for one hitter, as a pure function so the same
    rule is counted everywhere: the eligible field position with the highest RunsP + spectrum
    (strict greater-than, so ties go to the earlier, harder position in `order`); DH only when
    the hitter is eligible at no field position; a winning LF or RF is relabelled RF when his
    OF ARM >= the threshold, else LF. runs_p: {pos: RunsP or None}, eligible: positions he
    qualifies at. Nothing in the engine calls this; his Best Pos is unchanged."""
    best, best_score = None, None
    for pos in order:
        v = runs_p.get(pos)
        if pos not in eligible or v is None:
            continue
        score = v + spectrum[pos]
        if best_score is None or score > best_score:
            best, best_score = pos, score
    if best is None:
        return "DH"
    if best in ("LF", "RF"):
        return "RF" if (of_arm is not None and of_arm >= arm_threshold) else "LF"
    return best


def rf_arm_threshold(season, pos="RF"):
    """Mean OF ARM of the players actually deployed at `pos`, weighted by the innings they
    played there that season (MLB only, since the exports are MLB). This is the quantity
    metadata_calibrate already stores as the 'RF Arm' fielding anchor (I43 for RF). None
    when the source has no ratings table (the OOTP database layout)."""
    arms = season.get("of_arm") or {}
    ids = [i for i in season["ip"][pos] if i in arms]
    if not ids:
        return None
    w = np.array([season["ip"][pos][i] for i in ids])
    a = np.array([arms[i] for i in ids])
    return float((w * a).sum() / w.sum())

# ------------------------------------------------------------------ driver


def pos_adj_multiyear(seasons, h_def=H_DEF, cut_def=CUT_DEF, h_off=H_OFF, cut_off=CUT_OFF,
                      w=BLEND_W, lf_rf="split", rf_quirk=True, thirds_quirk=True, min_obs=MIN_OBS,
                      def_from_year=None, level="field8", dh="min"):
    """The whole calculation for a list of seasons (load_* outputs). The window ends at the
    latest season in the list. def_from_year: only seasons from this year on feed the
    defence half (the offence half keeps every season) - for a game-engine boundary."""
    end = max(s["year"] for s in seasons)
    accs = [(s, offense_accumulate(s, rf_quirk, thirds_quirk)) for s in seasons]
    inwin = [(acc, 0.5 ** ((end - s["year"]) / h_off)) for s, acc in accs if 0 <= end - s["year"] < cut_off]
    pooled = pool_accumulators(inwin)
    off_eng = offense_rates(pooled)                                # runs per std season (C 1000)
    off1200 = dict(off_eng)
    off1200["C"] = off_eng["C"] * 1200.0 / mc.STD_IP["C"]          # C to the 1200 IP common basis
    obs = [switcher_obs(s) for s in seasons if def_from_year is None or s["year"] >= def_from_year]
    def7, n_obs = solve_switcher(obs, end, h_def, cut_def, min_obs)
    final, parts = blend(def7, off1200, w, lf_rf, level, dh)
    eng = to_engine_units(final)
    return {"end_year": end, "n_switch_obs": n_obs, "defence_runs_per_1200": def7,
            "offence_runs_engine_units": off_eng, "offence_runs_per_1200": off1200,
            "spectrum_runs_per_1200": final, "P": {PCELL[p]: eng[p] for p in NINE},
            "spectrum_engine_units": eng, "parts": parts,
            "season_weights": {"offence": {s["year"]: 0.5 ** ((end - s["year"]) / h_off)
                                           for s in seasons if 0 <= end - s["year"] < cut_off},
                               "defence": {s["year"]: 0.5 ** ((end - s["year"]) / h_def)
                                           for s in seasons if 0 <= end - s["year"] < cut_def}}}


OVERLAY_PATH = os.path.join(HERE, "calib", "pos_adj_overlay.json")
WCELL = {"C": "W2", "1B": "W3", "2B": "W4", "3B": "W5", "SS": "W6", "LF": "W7", "CF": "W8", "RF": "W9", "DH": "W10"}


def _short(label):
    """A season source without the machine's home directory (repo-relative where possible)."""
    label = str(label).replace("\\", "/")
    for marker in ("ootp-dashboard/", "tgs-viz/"):
        if marker in label:
            return marker + label.split(marker, 1)[1]
    return os.path.basename(label.rstrip("/"))


def write_overlay(seasons, a, path=OVERLAY_PATH):
    """The league's positional adjustments as hitter-sheet cells W2..W10 (= metadata P2..P10),
    into engine/calib/pos_adj_overlay.json under --league. ingest/ratings.live_pos_adj() lays
    them over the basis' cells when that league is priced (decision 2026-10-03, PHASE2_STATUS)."""
    dfy = a.engine_first_season
    r = pos_adj_multiyear(seasons, a.h_def, a.cut_def, a.h_off, a.cut_off, a.blend, a.lf_rf,
                          def_from_year=dfy, level=a.level, dh=a.dh)
    try:
        with open(path, encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        table = {}
    table.setdefault("_about", "Per-app-league positional adjustments laid over the calibration basis' "
                     "hitter cells (W2..W10, runs per standard season; catcher per 1000 IP). Written by "
                     "engine/pos_adj_multiyear.py --overlay; read by ingest/ratings.live_pos_adj(). Kept "
                     "outside calib/<LG>/ so no calibration fingerprint changes.")
    table[a.league] = {
        "cells": {WCELL[p]: r["spectrum_engine_units"][p] for p in NINE},
        "seasons": [s["year"] for s in seasons], "defence_from": dfy,
        "n_switch_obs": r["n_switch_obs"],
        "rule": {"blend_w_def": a.blend, "lf_rf": a.lf_rf, "level": a.level, "dh": a.dh,
                 "h_def": a.h_def, "cut_def": a.cut_def, "h_off": a.h_off, "cut_off": a.cut_off},
        "sources": [_short(s["label"]) for s in seasons],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(table, fh, indent=1)
        fh.write("\n")
    print(f"wrote {a.league} into {path}: " + ", ".join(f"{p} {r['spectrum_engine_units'][p]:+.2f}" for p in NINE))


def _variant(seasons, a, def_from_year=None):
    """One window's candidates, both LF/RF treatments, plus the Option B inputs and (--se)
    the bootstrap standard error of the defence half."""
    res = {m: pos_adj_multiyear(seasons, a.h_def, a.cut_def, a.h_off, a.cut_off, a.blend, m,
                                def_from_year=def_from_year) for m in ("split", "pooled")}
    r = res["split"]
    out = {"seasons": [s["year"] for s in seasons], "n_switch_obs": r["n_switch_obs"],
           "candidates": {"lf_rf_split": r["P"], "lf_rf_pooled": res["pooled"]["P"]},
           "defence_runs_per_1200": r["defence_runs_per_1200"],
           "offence_runs_per_std_season": r["offence_runs_engine_units"]}
    if r["defence_runs_per_1200"] is not None:
        spec, top = option_b_spectrum(r)
        spec_max, top_max = option_b_spectrum(r, anchor=None)
        out["option_b_defensive_spectrum"] = {"engine_units": spec, "catcher_imputed_from": top,
                                              "catcher_if_anchored_on_window_max": {"anchor": top_max, "C": spec_max["C"]}}
        if a.se:
            end = r["end_year"]
            out["defence_se_runs_per_1200"] = bootstrap_se(
                [switcher_obs(s) for s in seasons if def_from_year is None or s["year"] >= def_from_year],
                end, a.h_def, a.cut_def, n_boot=a.se)
    arm = [rf_arm_threshold(s) for s in seasons if s.get("of_arm")]
    out["rf_arm_threshold"] = {"latest_season": arm[-1] if arm else None}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--league", required=True, help="label written to the output (BLM, SSB, ...)")
    ap.add_argument("--season", action="append", required=True, metavar="YEAR=DIR",
                    help="a season's input folder (metadata_inputs, dashboard metadata/<year>, or an "
                         "actuals/<year> folder); repeat for each season of the window")
    ap.add_argument("--league-id", type=int, help="MLB league_id, only for actuals folders (BLM 144)")
    ap.add_argument("--engine-first-season", type=int,
                    help="first season on the current game engine; the output then also carries a "
                         "window of current-engine seasons only, and one with offence over all seasons "
                         "but the defence half from current-engine seasons only")
    ap.add_argument("--h-def", type=float, default=H_DEF); ap.add_argument("--cut-def", type=int, default=CUT_DEF)
    ap.add_argument("--h-off", type=float, default=H_OFF); ap.add_argument("--cut-off", type=int, default=CUT_OFF)
    ap.add_argument("--blend", type=float, default=BLEND_W, help="weight on the defence half")
    ap.add_argument("--se", type=int, default=0, metavar="N", help="bootstrap the defence half N times")
    ap.add_argument("--out", help="write the candidate file here (the engine does not read it)")
    ap.add_argument("--overlay", action="store_true",
                    help="write ONE spectrum into engine/calib/pos_adj_overlay.json for --league (the "
                         "values the engine prices that league with), using --lf-rf / --level / --dh and "
                         "--engine-first-season as the defence window start")
    ap.add_argument("--lf-rf", choices=("split", "pooled"), default="pooled")
    ap.add_argument("--level", choices=("field8", "offence"), default="offence")
    ap.add_argument("--dh", choices=("min", "offence"), default="offence")
    a = ap.parse_args()
    seasons = []
    for spec in a.season:
        y, d = spec.split("=", 1)
        s = load_season(d, int(y), a.league_id)
        if a.engine_first_season:
            s["engine"] = "current" if s["year"] >= a.engine_first_season else "old"
        seasons.append(s)
    seasons.sort(key=lambda s: s["year"])
    if a.overlay:
        write_overlay(seasons, a)
        return
    variants = {"all_seasons": _variant(seasons, a)}
    cur = [s for s in seasons if s.get("engine") == "current"]
    if cur and len(cur) < len(seasons):
        variants["current_engine_only"] = _variant(cur, a)
        variants["defence_current_engine_offence_all_seasons"] = _variant(
            seasons, a, def_from_year=min(s["year"] for s in cur))
        print("  note: the window mixes game-engine versions; 'all_seasons' pools them. The defence half "
              "is not engine-invariant (docs/phase2/pos_adj.md)", file=sys.stderr)
    out = {
        "status": "GATED candidate - no engine file reads this; decide in docs/phase2/pos_adj.md",
        "league": a.league,
        "units": "runs per standardized season (1200 IP; catcher 1000 IP), same as P2..P10",
        "seasons": [{"year": s["year"], "source": s["label"], "engine": s.get("engine")} for s in seasons],
        "params": {"h_def": a.h_def, "cut_def": a.cut_def, "h_off": a.h_off, "cut_off": a.cut_off,
                   "blend_w_def": a.blend, "dh_rule": "min of nine", "centring": "field-8 mean 0"},
        "variants": variants,
    }
    txt = json.dumps(out, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
        print(f"wrote {a.out}")
    else:
        print(txt)


if __name__ == "__main__":
    main()
