"""
metadata_calibrate.py — compute every "Data Points" metadata constant in Python,
replacing the 25 Metadata.xlsx workbook (league calibration for The Sheet).

The workbook takes pasted OOTP/StatsPlus exports (Hitting/Pitching/SP/RP/Fielding
Data + Batter/SP/RP/Fielding Ratings), aggregates them through 25 pivot tables and
a Power Pivot Data Model, and derives: the league run environment (runs per out ->
linear run values -> wOBA scale + weights), league rate stats, PA/BF-weighted
league-average rating anchors (blended vR/vL by the vR share), per-position
innings-weighted fielding rating anchors, positional adjustments, and matchup
shares. This module reproduces that math EXACTLY — including the workbook's
as-built quirks (documented inline) — so it validates cell-for-cell against the
workbook before replacing it.

Data sources (CSV exports of the workbook's own input tabs; only the PASTED
columns are read — every worksheet helper column (wOBA..OFF, IP Clean, HT CM,
C * Fix, Plays A/M) is recomputed here from the pasted data):
  Hitting_Data.csv    : ID..UBR       (600ish hitter rows)
  Pitching_Data.csv   : ID..CS        (all pitchers)
  SP_Data.csv/RP_Data.csv : same schema, split by role
  Fielding_Data.csv   : 8 side-by-side per-position tables (C,1B,..,RF)
  Batter_Ratings.csv  : vR table + vL table side by side (PA = PA vs that side)
  SP_Ratings.csv/RP_Ratings.csv : vR + vL tables (BF = BF vs that side)
  Fielding_Ratings.csv: ID, POS, Name, IP, HT, C ABI.., OF ARM

Modes:
  python metadata_calibrate.py --inputs-dir DIR --json out.json
  python metadata_calibrate.py --inputs-dir DIR --validate expected_metadata.json
  ... add --model-ids FILE to either mode to emulate the workbook's stale
      Data-Model caches (see below).

WORKBOOK STALENESS (proven 2026-07-13 against the TGS 25 Metadata.xlsx):
  The two Helper[ID]-row Data-Model pivots — "Fielding Ratings" (Fielding Calc
  N1:AH589) and "Adj Pivot" (POS Adj Calc A1:L589) — hold a stale snapshot with
  588 IDs. The current input tabs contain 601 IDs; the 13 missing from the model:
    16776 22601 24070 26970 28213 30976 31684 34144 36654 38802 39686 40604 41301
  Every ID present in the cached pivots matches the current tabs exactly (per-ID
  PA, position IP, ratings, OFF all equal), so the stale cache == fresh data minus
  those 13 IDs. Restricting the model-backed layer to the cached ID set reproduces
  every affected Data Points cell to ~1e-15 rel; fresh data does not (rel errors
  up to 1.3e-1 on P10/DH). The affected cells are the fielding anchors (I3..I43,
  J9..J25) and the positional adjustments (P2..P10). All worksheet-table pivots
  (league totals, matchups, per-ID ratings pivots, the 8 per-position fielding
  pivots) match the current tabs exactly — they are fresh.
  --model-ids FILE (one ID per line, or a JSON array) = the ID set the workbook's
  Data Model pivots contained at last refresh (col A of the cached "Adj Pivot"
  grid, POS Adj Calc A2:A589). With it, validation passes 373/373; without it the
  ~35 model-backed cells report the workbook's staleness, and the fresh values
  emitted here are the correct ones.

Latent workbook bug (guarded here, would break the workbook on refresh): player
40604 has 1 fielding inning at RF and no Hitting_Data/Fielding_Ratings row. The
RF OFF branch-test window quirk (see pos_adj_calc) sends him to the pro-rata
branch, whose divisor MAX(total IP, PAIP) is 0 -> #DIV/0! in Excel. The workbook
only survives because its stale Adj Pivot lacks him. Here 0*ip/0 evaluates to 0
(a warning is printed); a nonzero/0 still raises.
"""
import argparse
import csv
import json
import os
import re
import sys
import time

POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
# 'Fielding Calc' row 25 "Standarized IP per POS" (sic): C 1000, everyone else 1200
STD_IP = {p: (1000.0 if p == "C" else 1200.0) for p in POSITIONS}

# Data Points hand-entered statics (no formula behind them)
STATICS = {
    "F31": 600.0,    # PA
    "F32": 500.0,    # PA Catcher
    "F33": 1200.0,   # IP
    "F34": 1000.0,   # IP Catcher
    "F38": 0.75,     # Infield Out
    "F39": 0.9,      # Outfield Out
    "T31": 800.0,    # BF
    "T32": 300.0,    # BF RP
    # T35 RunCS is a stale hand-entry (the hitting side F35 uses the live formula
    # ='Hitting Calc'!H11; nobody ever wired the pitching copy). Ported verbatim.
    "T35": -0.4048885881,
}

# ---------------------------------------------------------------- primitives


def num(v):
    """Pivot 'Sum of x' semantics: text/blank contributes 0."""
    if isinstance(v, float):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def dollarde(ip):
    """=IFERROR(DOLLARDE([IP],3),0) — OOTP x.y thirds notation -> real innings.
    Excel computes int + frac*10/3 in doubles with NO rounding of frac*10
    (123.2 -> 123 + 1.999..*[1/3]); replicated bit-for-bit."""
    try:
        ip = float(ip)
    except (TypeError, ValueError):
        return 0.0
    return int(ip) + (ip - int(ip)) * 10.0 / 3.0


def height_cm(ht):
    """HT CM =IFERROR(VALUE(LEFT(HT,FIND("'",HT)-1))*30.48
              +VALUE(MID(HT,FIND("'",HT)+1,FIND('"',HT)-FIND("'",HT)-1))*2.54,0)
    e.g. 5' 11" -> 5*30.48 + 11*2.54."""
    try:
        feet, rest = ht.split("'", 1)
        inches = rest.split('"')[0]
        return float(feet) * 30.48 + float(inches) * 2.54
    except (AttributeError, ValueError):
        return 0.0


def catcher_fix(v):
    """C ABI/FRM/ARM Fix =IF(x="-",20,x) — StatsPlus renders no-rating as '-'."""
    if isinstance(v, str) and v.strip() == "-":
        return 20.0
    return num(v)

# ---------------------------------------------------------------- loaders


def _norm(h):
    """Header cleanup: the TGS RP_Ratings paste carries 'BF\xa0▴' (NBSP +
    sort arrow); BLM's copy is clean 'BF'. Normalize both to 'BF'."""
    return (h or "").replace("\xa0", " ").replace("▴", "").replace("▾", "").strip()


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


def _header_row(rows):
    """Input tabs have a merged 'Player List' banner on row 1, headers on row 2."""
    for i, r in enumerate(rows[:3]):
        if any(_norm(c) == "ID" for c in r):
            return i
    raise ValueError("no header row with an ID column found")


def _slice_table(rows, hrow, start):
    """One table from a (possibly side-by-side) sheet: columns from `start` until
    the first unnamed/junk header; rows until the sheet ends, skipping blank IDs."""
    hdr = rows[hrow]
    cols = []
    for j in range(start, len(hdr)):
        h = _norm(hdr[j])
        if h in ("", "<--", "-->"):
            break
        cols.append((j, h))
    out = []
    for r in rows[hrow + 1:]:
        if len(r) <= start or r[start].strip() == "":
            continue
        out.append({h: (r[j] if j < len(r) else "") for j, h in cols})
    return out


def load_single(path):
    rows = _read(path)
    h = _header_row(rows)
    return _slice_table(rows, h, 0)


def load_vr_vl(path):
    """Batter/SP/RP Ratings: a vR table and a vL table pasted side by side.
    The vR copy's PA/BF column counts PA/BF vs RHP, the vL copy's vs LHP."""
    rows = _read(path)
    h = _header_row(rows)
    idcols = [j for j, c in enumerate(rows[h]) if _norm(c) == "ID"]
    if len(idcols) < 2:
        raise ValueError(f"{os.path.basename(path)}: expected two side-by-side tables")
    return _slice_table(rows, h, idcols[0]), _slice_table(rows, h, idcols[1])


def load_fielding(path):
    """Fielding Data: 8 side-by-side tables (Fielding_C .. Fielding_RF), keyed
    here by the table's POS code (2=C .. 9=RF) read from its rows."""
    rows = _read(path)
    h = _header_row(rows)
    idcols = [j for j, c in enumerate(rows[h]) if _norm(c) == "ID"]
    if len(idcols) != 8:
        raise ValueError(f"{os.path.basename(path)}: expected 8 position tables, found {len(idcols)}")
    code = {2: "C", 3: "1B", 4: "2B", 5: "3B", 6: "SS", 7: "LF", 8: "CF", 9: "RF"}
    out = {}
    for start in idcols:
        tab = _slice_table(rows, h, start)
        pos = code[int(num(tab[0]["POS"]))]
        out[pos] = tab
    if sorted(out) != sorted(POSITIONS):
        raise ValueError(f"{os.path.basename(path)}: position tables found: {sorted(out)}")
    return out


def _sum(rows, col):
    return sum(num(r[col]) for r in rows)


def _by_id(rows, valfn):
    """Pivot 'group rows by ID, Sum values' (IDs are unique in practice; grouping
    keeps exact pivot semantics if a paste ever carries duplicates)."""
    out = {}
    for r in rows:
        i = int(num(r["ID"]))
        out[i] = out.get(i, 0.0) + valfn(r)
    return out


# ---------------------------------------------------------------- live inputs for the fit tools

def live_inputs(league, names):
    """calib/<LEAGUE>/metadata_inputs when every CSV in `names` is there, else
    None. ingest/metadata_inputs.py writes these from the latest StatsPlus pull;
    it never updates the ratings tabs of 25 Metadata.xlsx, so the fit tools
    (scurve_fit.py, fielding_curves_fit.py) read the CSVs first. A league with
    no metadata_inputs folder keeps reading 25 Metadata.xlsx."""
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib", league, "metadata_inputs")
    if all(os.path.exists(os.path.join(d, n)) for n in names):
        return d
    return None


def inputs_label(d, names):
    """One log line for a metadata_inputs folder: season, in-game date and
    ratings pull from its manifest.json, and when the CSVs were written."""
    try:
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        man = {}
    saved = max(os.path.getmtime(os.path.join(d, n)) for n in names)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    pull = os.path.basename(man.get("pull") or "") or "?"
    return (f"{os.path.relpath(d, repo)} CSVs (season {man.get('season', '?')}, "
            f"in-game date {man.get('in_game_date', '?')}, ratings pull {pull}, "
            f"CSVs saved {time.strftime('%Y-%m-%d %H:%M', time.localtime(saved))})")

# ---------------------------------------------------------------- run environment

# Linear run value constants ('Hitting Calc' A11:H11 / 'Pitching Calc' rows 9/26):
# BB =0.14+R/Out, HBP =BB+0.025, 1B =BB+0.155, 2B =1B+0.3, 3B =2B+0.27,
# HR static 1.4, SB static 0.2, CS =-((2*R/Out)+0.075)


def run_values(rpo):
    rv = {}
    rv["BB"] = 0.14 + rpo
    rv["HBP"] = 0.025 + rv["BB"]
    rv["1B"] = 0.155 + rv["BB"]
    rv["2B"] = 0.3 + rv["1B"]
    rv["3B"] = 0.27 + rv["2B"]
    rv["HR"] = 1.4
    rv["SB"] = 0.2
    rv["CS"] = -((2 * rpo) + 0.075)
    return rv


def woba_engine(T, rv):
    """Rows 14/12/29 ('total run value') + E5/F5/G5. Returns (total_rv, runs_plus,
    runs_minus, scale, weights) where weights are the wOBA weights row 17/15/32
    shape: (rv + runs_minus)*scale for BB..HR, rv*scale for SB/CS."""
    total = ((T["BB"] - T["IBB"]) * rv["BB"] + rv["HBP"] * T["HP"] + rv["1B"] * T["1B"]
             + rv["2B"] * T["2B"] + rv["3B"] * T["3B"] + rv["HR"] * T["HR"]
             + rv["SB"] * T["SB"] + rv["CS"] * T["CS"])
    pro = T["1B"] + T["2B"] + T["3B"] + T["HR"] + T["BB"] + T["HP"] - T["IBB"]   # B5
    unpro = T["AB"] - (T["1B"] + T["2B"] + T["3B"] + T["HR"]) + T["SF"]          # C5
    runs_plus = total / pro
    runs_minus = total / unpro
    scale = 1.0 / (runs_plus + runs_minus)
    w = {k: (rv[k] + runs_minus) * scale for k in ("BB", "HBP", "1B", "2B", "3B", "HR")}
    w["SB"] = rv["SB"] * scale
    w["CS"] = rv["CS"] * scale
    return total, runs_plus, runs_minus, scale, w

# ---------------------------------------------------------------- hitting calc


HIT_COLS = ["R", "PA", "AB", "1B", "2B", "3B", "HR", "BB", "HP", "IBB",
            "SH", "SF", "SB", "CS", "SO", "UBR", "GIDP"]


def hitting_calc(hit, bat_vr, bat_vl):
    T = {c: _sum(hit, c) for c in HIT_COLS}
    # 'Outs' is a pivot CALCULATED FIELD, not a pasted column:
    #   Outs = SUM(AB)-(SUM('1B')+SUM('2B')+SUM('3B')+SUM(HR))+SUM(SF)+SUM(SH)+SUM(GIDP)+SUM(CS)
    T["Outs"] = (T["AB"] - (T["1B"] + T["2B"] + T["3B"] + T["HR"])
                 + T["SF"] + T["SH"] + T["GIDP"] + T["CS"])
    rpo = T["R"] / T["Outs"]                                     # A5 Run per Out
    rv = run_values(rpo)
    _, _, runs_minus, scale, w = woba_engine(T, rv)
    # H5 lg wSB =MAX((SB*G11+CS*H11)/(BB+HP+1B-IBB),0)
    lg_wsb = max((T["SB"] * rv["SB"] + T["CS"] * rv["CS"])
                 / (T["BB"] + T["HP"] + T["1B"] - T["IBB"]), 0.0)
    # I5 lg wOBA (hitting version has NO SB/CS terms)
    lg_woba = ((T["BB"] - T["IBB"]) * w["BB"] + T["HP"] * w["HBP"] + T["1B"] * w["1B"]
               + T["2B"] * w["2B"] + T["3B"] * w["3B"] + T["HR"] * w["HR"]) \
        / (T["AB"] + T["BB"] + T["HP"] - T["IBB"] + T["SF"])
    # N5 UBR rate; denominator verbatim: (1B+BB+HP)*3+2B*2+3B-CS*3-SB
    ubr_rate = T["UBR"] / ((T["1B"] + T["BB"] + T["HP"]) * 3
                           + T["2B"] * 2 + T["3B"] - T["CS"] * 3 - T["SB"])
    rates = {
        "BB%": (T["BB"] - T["IBB"]) / (T["PA"] - T["IBB"] - T["HP"]),        # Q5
        "HR%": T["HR"] / (T["PA"] - T["IBB"] - T["HP"] - T["BB"]),           # R5
        "SO%": T["SO"] / (T["PA"] - T["HP"] - T["IBB"] - T["BB"]),           # P5
        "BABIP": (T["1B"] + T["2B"] + T["3B"]) / (T["AB"] - T["HR"] + T["SF"] - T["SO"]),  # J5
        "XBH%": (T["2B"] + T["3B"]) / (T["1B"] + T["2B"] + T["3B"]),         # K5
        "3B%": T["3B"] / (T["3B"] + T["2B"]),                                # O5
        "SB%": T["SB"] / (T["SB"] + T["CS"]),                                # L5
        "UBR": ubr_rate,                                                     # N5
        "SBA%": (T["SB"] + T["CS"]) / (T["1B"] + T["BB"] + T["HP"]),         # M5
        "R/PA": T["R"] / T["PA"],                                            # S5
        "HBP": T["HP"] / T["PA"],                                            # T5
    }

    # Matchups (Z1:AC5 pivots): Sum of PA by batter handedness, vR and vL exports;
    # Y9..Y12 = share of each handedness group's PA that came vs RHP.
    def pa_by_hand(rows):
        out = {}
        for r in rows:
            out[r["B"]] = out.get(r["B"], 0.0) + num(r["PA"])
        return out
    vr_pa, vl_pa = pa_by_hand(bat_vr), pa_by_hand(bat_vl)
    matchups = {}
    for key, hand in [("LvR", "L"), ("RvR", "R"), ("SvR", "S")]:
        matchups[key] = vr_pa.get(hand, 0.0) / (vr_pa.get(hand, 0.0) + vl_pa.get(hand, 0.0))
    gt_vr, gt_vl = sum(vr_pa.values()), sum(vl_pa.values())
    matchups["OVR vR"] = gt_vr / (gt_vr + gt_vl)                             # Y12

    # League rating anchors K9:S9 / K11:S11: {=SUM(rating*PA)/SUM(PA)} over the
    # per-ID pivots (PA vs that side is the weight), then V8:V15 blends vR/vL by
    # the overall vR share Y12.
    def anchor(rows, col):
        pa = _by_id(rows, lambda r: num(r["PA"]))
        rat = _by_id(rows, lambda r: num(r[col]))
        wsum = sum(pa.values())
        return sum(rat[i] * pa[i] for i in pa) / wsum
    y12 = matchups["OVR vR"]
    anchors = {}
    for label, cvr, cvl in [("Eye", "EYE vR", "EYE vL"), ("Power", "POW vR", "POW vL"),
                            ("AvK", "K vR", "K vL"), ("BABIP", "BA vR", "BA vL"),
                            ("Gap", "GAP vR", "GAP vL"), ("Speed", "SPE", "SPE"),
                            ("Stealing", "STE", "STE"), ("Baserunning", "RUN", "RUN")]:
        anchors[label] = anchor(bat_vr, cvr) * y12 + anchor(bat_vl, cvl) * (1 - y12)

    # Per-player OFF ('Hitting Data' helper cols AA..AF, verbatim), for POS Adj.
    # One-pass dependency: the league weights above use pasted columns only.
    off_by_id, pa_by_id = {}, {}
    for r in hit:
        i = int(num(r["ID"]))
        ab, bb, ibb, hp, sf = (num(r["AB"]), num(r["BB"]), num(r["IBB"]),
                               num(r["HP"]), num(r["SF"]))
        s1, d2, t3, hr = num(r["1B"]), num(r["2B"]), num(r["3B"]), num(r["HR"])
        sb, cs, ubr, pa = num(r["SB"]), num(r["CS"]), num(r["UBR"]), num(r["PA"])
        den = ab + bb - ibb + hp + sf
        woba = 0.0 if den == 0 else \
            ((bb - ibb) * w["BB"] + hp * w["HBP"] + s1 * w["1B"]
             + d2 * w["2B"] + t3 * w["3B"] + hr * w["HR"]) / den    # IFERROR(..,0)
        ubraa = ubr - ubr_rate * ((s1 + bb + hp) * 3 + d2 * 2 + t3 - sb - cs * 3)
        wsb = (sb * rv["SB"] + cs * rv["CS"]) - lg_wsb * (s1 + bb + hp - ibb)
        wraa = (woba - lg_woba) / scale * pa
        off = wraa + (ubraa + wsb)                                  # OFF = wRAA + BSR
        off_by_id[i] = off_by_id.get(i, 0.0) + off
        pa_by_id[i] = pa_by_id.get(i, 0.0) + pa

    return {"totals": T, "rv": rv, "scale": scale, "weights": w, "lg_woba": lg_woba,
            "lg_wsb": lg_wsb, "rates": rates, "matchups": matchups, "anchors": anchors,
            "off_by_id": off_by_id, "pa_by_id": pa_by_id}

# ---------------------------------------------------------------- pitching calc


PIT_COLS = ["R", "BF", "AB", "1B", "2B", "3B", "HR", "BB", "HP", "IBB",
            "SH", "SF", "SB", "CS", "DP", "K"]


def _pitch_block(rows):
    """One SP/RP block ('Pitching Calc' rows 1-15 or 18-32) up to the weights,
    which need the cross-block quirk handled by the caller."""
    T = {c: _sum(rows, c) for c in PIT_COLS}
    T["IPC"] = sum(dollarde(r["IP"]) for r in rows)
    # R2/R19 Outs =AB-(1B+2B+3B+HR)+DP+CS+SH+SF
    T["Outs"] = (T["AB"] - (T["1B"] + T["2B"] + T["3B"] + T["HR"])
                 + T["DP"] + T["CS"] + T["SH"] + T["SF"])
    rpo = T["R"] / T["Outs"]                                        # A5/A22
    rv = run_values(rpo)
    _, _, runs_minus, scale, w = woba_engine(T, rv)
    lg_wsb = max((T["SB"] * rv["SB"] + T["CS"] * rv["CS"])
                 / (T["BB"] + T["HP"] + T["1B"] - T["IBB"]), 0.0)   # H5/H22
    rates = {
        "BB%": (T["BB"] - T["IBB"]) / (T["BF"] - T["IBB"] - T["HP"]),   # P5
        "HR%": T["HR"] / (T["BF"] - T["HP"] - T["BB"]),                 # Q5 (no -IBB, unlike hitting)
        "SO%": T["K"] / (T["BF"] - T["HP"] - T["BB"]),                  # O5 (no -IBB)
        "BABIP": (T["1B"] + T["2B"] + T["3B"]) / (T["AB"] - T["HR"] + T["SF"] - T["K"]),  # J5
        "XBH%": (T["2B"] + T["3B"]) / (T["2B"] + T["3B"] + T["1B"]),    # K5
        "3B%": T["3B"] / (T["3B"] + T["2B"]),                           # N5
        "SB%": T["SB"] / (T["SB"] + T["CS"]),                           # L5
        "HBP%": T["HP"] / T["BF"],                                      # R5
        "IBB": T["IBB"] / T["BF"],                                      # S5
        "SBA%": (T["SB"] + T["CS"]) / (T["1B"] + T["BB"] + T["HP"]),    # M5
    }
    return {"T": T, "rv": rv, "runs_minus": runs_minus, "scale": scale,
            "weights": w, "lg_wsb": lg_wsb, "rates": rates}


def _pitch_woba(T, w):
    """I5/I22 pitcher lg wOBA — unlike the hitting version it has SB/CS terms:
    =((BB-IBB)*wBB+HP*wHBP+1B*w1B+2B*w2B+3B*w3B+HR*wHR+SB*wSB+CS*wCS)
      /(AB+BB-IBB+HP+SF)"""
    return ((T["BB"] - T["IBB"]) * w["BB"] + T["HP"] * w["HBP"] + T["1B"] * w["1B"]
            + T["2B"] * w["2B"] + T["3B"] * w["3B"] + T["HR"] * w["HR"]
            + T["SB"] * w["SB"] + T["CS"] * w["CS"]) \
        / (T["AB"] + T["BB"] - T["IBB"] + T["HP"] + T["SF"])


def pitching_calc(sp, rp, pitch, spr_vr, spr_vl, rpr_vr, rpr_vl):
    SP = _pitch_block(sp)
    RP = _pitch_block(rp)
    # QUIRK (ported verbatim): the RP wOBA weights row 32 scales the RP run values
    # by the SP block's Runs- ($F$5) and wOBA Scale ($G$5): A32=(A26+$F$5)*$G$5 etc.
    RP["weights"] = {k: (RP["rv"][k] + SP["runs_minus"]) * SP["scale"]
                     for k in ("BB", "HBP", "1B", "2B", "3B", "HR")}
    RP["weights"]["SB"] = RP["rv"]["SB"] * SP["scale"]
    RP["weights"]["CS"] = RP["rv"]["CS"] * SP["scale"]
    SP["lg_woba"] = _pitch_woba(SP["T"], SP["weights"])
    RP["lg_woba"] = _pitch_woba(RP["T"], RP["weights"])

    # League constants (direct table SUMs over Pitching_Data, not pivots)
    tot_r = _sum(pitch, "R")
    tot_bf = _sum(pitch, "BF")
    tot_ipc = sum(dollarde(r["IP"]) for r in pitch)
    league = {
        "RA/9 SP": SP["T"]["R"] / SP["T"]["IPC"] * 9,                # J9
        "RA/9 RP": RP["T"]["R"] / RP["T"]["IPC"] * 9,                # K9
        "RA/9": tot_r / tot_ipc * 9,                                 # L9
        "WAA Constant": 9 * (tot_r / tot_ipc) * 1.5 + 3,             # J11
        "R/PA": tot_r / tot_bf,                                      # K11
        "BF/IP": tot_bf / tot_ipc,                                   # L11
        "Team IP": tot_ipc / 30,                                     # J13
    }

    # Matchups (V1:Y8 pivots): Sum of BF by pitcher throw-hand from the vR/vL
    # ratings exports; U9/U10/U11 SP, U13/U14/U15 RP. No switch pitchers exist —
    # Data Points T25 'SvR' and T26 'OVR vR' both read U11 (as built).
    def bf_by_hand(rows):
        out = {}
        for r in rows:
            out[r["T"]] = out.get(r["T"], 0.0) + num(r["BF"])
        return out

    def matchup3(vr_rows, vl_rows):
        vr, vl = bf_by_hand(vr_rows), bf_by_hand(vl_rows)
        gt_vr, gt_vl = sum(vr.values()), sum(vl.values())
        return {"LvR": vr.get("L", 0.0) / (vr.get("L", 0.0) + vl.get("L", 0.0)),
                "RvR": vr.get("R", 0.0) / (vr.get("R", 0.0) + vl.get("R", 0.0)),
                "OVR vR": gt_vr / (gt_vr + gt_vl)}
    SP["matchups"] = matchup3(spr_vr, spr_vl)
    RP["matchups"] = matchup3(rpr_vr, rpr_vl)

    # Anchors L26:P26/L28:P28 (SP) and S26:W26/S28:W28 (RP):
    # {=SUMPRODUCT(rating*BF)/SUM(BF)} over the per-ID pivots, then X/Y blends
    # by the role's OVR vR share (U11 SP / U15 RP).
    def anchor(rows, col):
        bf = _by_id(rows, lambda r: num(r["BF"]))
        rat = _by_id(rows, lambda r: num(r[col]))
        return sum(rat[i] * bf[i] for i in bf) / sum(bf.values())
    for blk, vr_rows, vl_rows in [(SP, spr_vr, spr_vl), (RP, rpr_vr, rpr_vl)]:
        share = blk["matchups"]["OVR vR"]
        blk["anchors"] = {}
        for label, cvr, cvl in [("STU", "STU vR", "STU vL"), ("HRA", "HRR vR", "HRR vL"),
                                ("pBABIP", "PBABIP vR", "PBABIP vL"),
                                ("CON", "CON vR", "CON vL"), ("Hold", "HLD", "HLD")]:
            blk["anchors"][label] = (anchor(vr_rows, cvr) * share
                                     + anchor(vl_rows, cvl) * (1 - share))
    return SP, RP, league

# ---------------------------------------------------------------- fielding calc


def fielding_tables(fld):
    """Per-position sums for the 8 Data-Model position pivots (Fielding Calc
    A1:J16) + per-ID IP Clean maps + raw-IP column sums (POS Adj divisors).
    Plays A =BIZ-R+BIZ-L+BIZ-E+BIZ-U+BIZ-Z+BIZ-I ; Plays M = the five *m cols."""
    biz_a = ["BIZ-R", "BIZ-L", "BIZ-E", "BIZ-U", "BIZ-Z", "BIZ-I"]
    biz_m = ["BIZ-Rm", "BIZ-Lm", "BIZ-Em", "BIZ-Um", "BIZ-Zm"]
    piv, ip_by_id, raw_ip = {}, {}, {}
    for pos in POSITIONS:
        rows = fld[pos]
        piv[pos] = {
            "IPC": sum(dollarde(r["IP"]) for r in rows),
            "PlaysA": sum(sum(num(r[c]) for c in biz_a) for r in rows),
            "PlaysM": sum(sum(num(r[c]) for c in biz_m) for r in rows),
            "E": _sum(rows, "E"), "DP": _sum(rows, "DP"), "ARM": _sum(rows, "ARM"),
            "FRM": _sum(rows, "FRM"), "SBA": _sum(rows, "SBA"), "RTO": _sum(rows, "RTO"),
        }
        ip_by_id[pos] = _by_id(rows, lambda r: dollarde(r["IP"]))
        # QUIRK: the POS Adj divisors SUM(Fielding_X[IP]) use the RAW OOTP x.y
        # thirds-notation column, summed as-is (not IP Clean). Ported verbatim.
        raw_ip[pos] = _sum(rows, "IP")
    return piv, ip_by_id, raw_ip


def fielding_rates(piv):
    """'Fielding Calc' rate rows 19/22/31/34/37 -> Data Points M2..M30."""
    out = {}
    out["C FRM/1000"] = piv["C"]["FRM"] / piv["C"]["IPC"] * STD_IP["C"]      # A37
    out["C SBA/1000"] = piv["C"]["SBA"] / piv["C"]["IPC"] * STD_IP["C"]      # B37
    out["C RTO%"] = piv["C"]["RTO"] / piv["C"]["SBA"]                        # C37
    for pos in ["1B", "2B", "3B", "SS", "LF", "CF", "RF"]:
        p = piv[pos]
        out[f"{pos} PA/1200"] = p["PlaysA"] / p["IPC"] * STD_IP[pos]         # row 19
        out[f"{pos} PM%"] = p["PlaysM"] / p["PlaysA"]                        # row 22
        out[f"{pos} E%"] = p["E"] / p["PlaysM"]                              # row 31 (errors per play MADE)
    for pos in ["2B", "SS"]:
        out[f"{pos} DP/1200"] = piv[pos]["DP"] / piv[pos]["IPC"] * STD_IP[pos]  # row 34
    for pos in ["LF", "CF", "RF"]:
        out[f"{pos} ARM"] = piv[pos]["ARM"] / piv[pos]["IPC"] * STD_IP[pos]  # row 37
    return out


RATING_COLS = {  # Fielding Calc AL..AV headers -> Fielding_Ratings source
    "C ABI": lambda r: catcher_fix(r["C ABI"]),
    "C FRM": lambda r: catcher_fix(r["C FRM"]),
    "C ARM": lambda r: catcher_fix(r["C ARM"]),
    "IF RNG": lambda r: num(r["IF RNG"]), "IF ERR": lambda r: num(r["IF ERR"]),
    "IF ARM": lambda r: num(r["IF ARM"]), "TDP": lambda r: num(r["TDP"]),
    "OF RNG": lambda r: num(r["OF RNG"]), "OF ERR": lambda r: num(r["OF ERR"]),
    "OF ARM": lambda r: num(r["OF ARM"]), "HT": lambda r: height_cm(r["HT"]),
}


def fielding_anchors(fratings, ip_by_id, model_ids=None):
    """Position anchors AL2:AV9: each rating innings-weighted over ALL players by
    that row's position IP ({=SUMPRODUCT(rating*posIP)/SUM(posIP)} over the
    'Fielding Ratings' Data-Model pivot). A player with position innings but no
    Fielding_Ratings row contributes 0 rating and full weight (blank*IP = 0 in
    SUMPRODUCT, IP still in the denominator SUM). model_ids restricts the row set
    to the workbook's stale Data-Model snapshot (validation only)."""
    ratings = {name: _by_id(fratings, fn) for name, fn in RATING_COLS.items()}
    out = {}
    for pos in POSITIONS:
        ids = set(ip_by_id[pos])
        if model_ids is not None:
            ids &= model_ids
        wsum = sum(ip_by_id[pos][i] for i in ids)
        out[pos] = {name: sum(vals.get(i, 0.0) * ip_by_id[pos][i] for i in ids) / wsum
                    for name, vals in ratings.items()}
    return out

# ---------------------------------------------------------------- POS adj calc


def pos_adj_calc(hit_out, fratings, ip_by_id, raw_ip, model_ids=None):
    """'POS Adj Calc': apportion each player's OFF runs across the positions he
    manned (pro-rata by innings, with a PAIP/DH remainder), then per position
    -(sum apportioned OFF / sum raw IP) * standardized season. LF/RF pool into a
    corner-OF average (AC12). Row set = the 'Adj Pivot' Data-Model rows (one per
    ID over Hitting_Data + Fielding_Ratings + Fielding_*); model_ids restricts to
    the workbook's stale snapshot (validation only)."""
    pa = hit_out["pa_by_id"]
    off = hit_out["off_by_id"]
    ipc_by_id = _by_id(fratings, lambda r: dollarde(r["IP"]))
    ids = set(pa) | set(ipc_by_id)
    for pos in POSITIONS:
        ids |= set(ip_by_id[pos])
    if model_ids is not None:
        ids &= model_ids
    # M2 IP/BF =SUM(pivot IP Clean)/SUM(pivot PA). QUIRK: the numerator is the
    # TOTAL fielding IP from the Fielding_Ratings export, not the sum of the 8
    # position IP columns.
    m2 = sum(ipc_by_id.get(i, 0.0) for i in ids) / sum(pa.get(i, 0.0) for i in ids)

    pos_off = {p: 0.0 for p in POSITIONS}
    dh_off = dh_ip_sum = 0.0
    div0_ids = []
    for i in sorted(ids):
        ppa = pa.get(i, 0.0)
        c2 = ipc_by_id.get(i, 0.0)          # total fielding IP (ratings export)
        l2 = off.get(i, 0.0)
        ips = [ip_by_id[p].get(i, 0.0) for p in POSITIONS]
        paip = ppa * m2                     # O: PA converted to equivalent IP
        dh_ip = max(paip - c2, 0.0)         # P: DH IP
        for k, p in enumerate(POSITIONS):
            if ips[k] == 0:
                continue
            # Branch test: "did he play anywhere else?" — sums the OTHER position
            # IPs + DH IP. QUIRK (copy-drag artifact, ported verbatim): the RF
            # window is SUM($K2:L2,$D2:J2,DH) which includes RF's own IP and the
            # OFF column, so RF never takes the all-of-it branch.
            if p == "RF":
                window = sum(ips) + l2 + dh_ip
            else:
                window = sum(ips) - ips[k] + dh_ip
            if window == 0:
                pos_off[p] += l2            # only position he played: all of it
            else:
                numer, denom = l2 * ips[k], max(c2, paip)
                if denom == 0:
                    # Excel would #DIV/0! here (see module docstring: latent bug,
                    # masked by the stale Adj Pivot). 0/0 -> 0; nonzero/0 raises.
                    if numer != 0:
                        raise ZeroDivisionError(f"POS Adj {p} OFF for ID {i}: {numer}/0")
                    div0_ids.append(i)
                else:
                    pos_off[p] += numer / denom
        if dh_ip != 0:                      # Y: DH OFF
            dh_off += l2 if sum(ips) == 0 else l2 * dh_ip / max(c2, paip)
            dh_ip_sum += dh_ip
    if div0_ids:
        print(f"  note: 0*IP/MAX(0,0) treated as 0 for IDs {sorted(set(div0_ids))} "
              "(a refreshed workbook would #DIV/0! here)", file=sys.stderr)

    # AB2:AC10 adjustments; divisors are the raw thirds-notation IP column sums.
    adj = {"C": pos_off["C"] / raw_ip["C"] * STD_IP["C"] * -1}
    for p in ["1B", "2B", "3B", "SS", "CF"]:
        adj[p] = pos_off[p] / raw_ip[p] * STD_IP[p] * -1
    cof = ((pos_off["LF"] / raw_ip["LF"] * 1200) + (pos_off["RF"] / raw_ip["RF"] * 1200)) / -2
    adj["LF"] = adj["RF"] = cof             # AC7 = AC9 = AC12 (corner OF pooled)
    adj["DH"] = dh_off / dh_ip_sum * 1200 * -1
    return m2, adj

# ---------------------------------------------------------------- assembly


def compute_cells(inputs_dir, model_ids=None):
    p = lambda name: os.path.join(inputs_dir, name)
    for name in ["Hitting_Data.csv", "Pitching_Data.csv", "SP_Data.csv", "RP_Data.csv",
                 "Fielding_Data.csv", "Batter_Ratings.csv", "SP_Ratings.csv",
                 "RP_Ratings.csv", "Fielding_Ratings.csv"]:
        if not os.path.exists(p(name)):
            sys.exit(f"missing input: {p(name)}")
    hit = load_single(p("Hitting_Data.csv"))
    pitch = load_single(p("Pitching_Data.csv"))
    sp = load_single(p("SP_Data.csv"))
    rp = load_single(p("RP_Data.csv"))
    fratings = load_single(p("Fielding_Ratings.csv"))
    bat_vr, bat_vl = load_vr_vl(p("Batter_Ratings.csv"))
    spr_vr, spr_vl = load_vr_vl(p("SP_Ratings.csv"))
    rpr_vr, rpr_vl = load_vr_vl(p("RP_Ratings.csv"))
    fld = load_fielding(p("Fielding_Data.csv"))

    H = hitting_calc(hit, bat_vr, bat_vl)
    SP, RP, league = pitching_calc(sp, rp, pitch, spr_vr, spr_vl, rpr_vr, rpr_vl)
    piv, ip_by_id, raw_ip = fielding_tables(fld)
    frates = fielding_rates(piv)
    fanch = fielding_anchors(fratings, ip_by_id, model_ids)
    _, padj = pos_adj_calc(H, fratings, ip_by_id, raw_ip, model_ids)

    c = dict(STATICS)
    # --- Hitting Ratings anchors F2:F9 ='Hitting Calc'!V8..V15
    for cell, lab in zip(["F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9"],
                         ["Eye", "Power", "AvK", "BABIP", "Gap", "Speed", "Stealing", "Baserunning"]):
        c[cell] = H["anchors"][lab]
    # --- Hitting wOBA weights F12:F20
    for cell, k in zip(["F12", "F13", "F14", "F15", "F16", "F17", "F18", "F19"],
                       ["HBP", "BB", "1B", "2B", "3B", "HR", "SB", "CS"]):
        c[cell] = H["weights"][k]
    c["F20"] = H["scale"]
    # --- Hitter matchups F23:F26
    for cell, k in zip(["F23", "F24", "F25", "F26"], ["LvR", "RvR", "SvR", "OVR vR"]):
        c[cell] = H["matchups"][k]
    # --- League measurements F29..F40
    c["F29"] = H["lg_woba"]
    c["F30"] = league["WAA Constant"]
    c["F35"] = H["rv"]["CS"]           # RunCS ='Hitting Calc'!H11
    c["F36"] = H["lg_wsb"]
    c["F37"] = H["rates"]["HBP"]
    c["F40"] = H["rates"]["R/PA"]
    # --- Hitting Stats B33:B41
    for cell, k in zip(["B33", "B34", "B35", "B36", "B37", "B38", "B39", "B40", "B41"],
                       ["BB%", "HR%", "SO%", "BABIP", "XBH%", "3B%", "SB%", "UBR", "SBA%"]):
        c[cell] = H["rates"][k]
    # --- Fielding Ratings anchors (I/J cols; I5 and I7 are duplicate C Arm cells)
    c["I3"] = fanch["C"]["C FRM"]
    c["I5"] = c["I7"] = fanch["C"]["C ARM"]
    c["I9"], c["J9"], c["I11"] = fanch["1B"]["IF RNG"], fanch["1B"]["HT"], fanch["1B"]["IF ERR"]
    c["I13"], c["J13"] = fanch["2B"]["IF RNG"], fanch["2B"]["IF ARM"]
    c["I15"], c["I17"] = fanch["2B"]["IF ERR"], fanch["2B"]["TDP"]
    c["I19"], c["J19"], c["I21"] = fanch["3B"]["IF RNG"], fanch["3B"]["IF ARM"], fanch["3B"]["IF ERR"]
    c["I23"], c["J23"] = fanch["SS"]["IF RNG"], fanch["SS"]["IF ARM"]
    c["I25"], c["J25"] = fanch["SS"]["IF ERR"], fanch["SS"]["TDP"]
    for pos, (r1, r2, r3) in [("LF", ("I27", "I29", "I31")), ("CF", ("I33", "I35", "I37")),
                              ("RF", ("I39", "I41", "I43"))]:
        c[r1], c[r2], c[r3] = fanch[pos]["OF RNG"], fanch[pos]["OF ERR"], fanch[pos]["OF ARM"]
    # --- Fielding Stats M2:M30
    for cell, k in zip(
            [f"M{r}" for r in range(2, 31)],
            ["C FRM/1000", "C SBA/1000", "C RTO%",
             "1B PA/1200", "1B PM%", "1B E%",
             "2B PA/1200", "2B PM%", "2B E%", "2B DP/1200",
             "3B PA/1200", "3B PM%", "3B E%",
             "SS PA/1200", "SS PM%", "SS E%",
             "LF PA/1200", "LF PM%", "LF E%", "LF ARM",
             "CF PA/1200", "CF PM%", "CF E%", "CF ARM",
             "RF PA/1200", "RF PM%", "RF E%", "RF ARM",
             "SS DP/1200"]):
        c[cell] = frates[k]
    # --- Pos ADJ P2:P10
    for cell, k in zip([f"P{r}" for r in range(2, 11)],
                       ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]):
        c[cell] = padj[k]
    # --- Starter/Reliever anchors T2..T10, U2, U7
    c["T2"], c["U2"] = SP["anchors"]["STU"], SP["anchors"]["Hold"]
    c["T3"], c["T4"], c["T5"] = SP["anchors"]["HRA"], SP["anchors"]["pBABIP"], SP["anchors"]["CON"]
    c["T7"], c["U7"] = RP["anchors"]["STU"], RP["anchors"]["Hold"]
    c["T8"], c["T9"], c["T10"] = RP["anchors"]["HRA"], RP["anchors"]["pBABIP"], RP["anchors"]["CON"]
    # --- SP wOBA + weights T11:T20
    c["T11"] = SP["lg_woba"]
    for cell, k in zip(["T12", "T13", "T14", "T15", "T16", "T17", "T18", "T19"],
                       ["HBP", "BB", "1B", "2B", "3B", "HR", "SB", "CS"]):
        c[cell] = SP["weights"][k]
    c["T20"] = SP["scale"]
    # --- Pitcher matchups T23:T26 (T25 SvR ≡ T26 OVR vR — both read U11, as built)
    c["T23"] = SP["matchups"]["LvR"]
    c["T24"] = SP["matchups"]["RvR"]
    c["T25"] = c["T26"] = SP["matchups"]["OVR vR"]
    # --- League Stats T29..T43
    c["T29"] = SP["lg_woba"]
    c["T30"] = league["WAA Constant"]
    c["T33"] = c["T31"] / league["BF/IP"]                     # =T31/T37
    c["T34"] = c["T32"] / league["BF/IP"]                     # =T32/T37
    c["T36"] = SP["lg_wsb"]
    c["T37"] = league["BF/IP"]
    c["T38"] = league["Team IP"]
    c["T39"] = league["Team IP"] - c["T31"] * 5 / league["BF/IP"]   # =T38-T31*5/T37
    c["T40"] = league["R/PA"]
    c["T41"] = league["RA/9 SP"]
    c["T42"] = league["RA/9 RP"]
    c["T43"] = league["RA/9"]
    # --- Pitching Stats W3:W12 (SP) / W15:W24 (RP)
    stat_keys = ["BB%", "HR%", "SO%", "BABIP", "XBH%", "3B%", "SB%", "HBP%", "IBB", "SBA%"]
    for cell, k in zip([f"W{r}" for r in range(3, 13)], stat_keys):
        c[cell] = SP["rates"][k]
    for cell, k in zip([f"W{r}" for r in range(15, 25)], stat_keys):
        c[cell] = RP["rates"][k]
    # --- RP wOBA + weights W28:W37
    c["W28"] = RP["lg_woba"]
    for cell, k in zip(["W29", "W30", "W31", "W32", "W33", "W34", "W35", "W36"],
                       ["HBP", "BB", "1B", "2B", "3B", "HR", "SB", "CS"]):
        c[cell] = RP["weights"][k]
    c["W37"] = RP["scale"]                                    # RP scale is its OWN G22
    return c

# ---------------------------------------------------------------- output map

# Data Points label cells, verbatim (sheet furniture; also validated).
LABELS = {
    "A32": "Hitting Stats", "A33": "BB%", "A34": "HR%", "A35": "SO%", "A36": "BABIP",
    "A37": "XBH%", "A38": "3B%", "A39": "SB%", "A40": "UBR", "A41": "SBA%",
    "E1": "Hitting Ratings", "E2": "Eye", "E3": "Power", "E4": "AvK", "E5": "BABIP",
    "E6": "Gap", "E7": "Speed", "E8": "Stealing", "E9": "Baserunning",
    "E11": "wOBA", "E12": "HBP", "E13": "BB", "E14": "1B", "E15": "2B", "E16": "3B",
    "E17": "HR", "E18": "SB", "E19": "CS", "E20": "Scale",
    "E22": "Matchups", "E23": "LvR", "E24": "RvR", "E25": "SvR", "E26": "OVR vR",
    "E28": "League Measurements", "E29": "wOBA", "E30": "WAA Constant", "E31": "PA",
    "E32": "PA Catcher", "E33": "IP", "E34": "IP Catcher", "E35": "RunCS",
    "E36": "wSB", "E37": "HBP", "E38": "Infield Out", "E39": "Outfield Out", "E40": "R/PA",
    "H2": "C", "H8": "1B", "H12": "2B", "H18": "3B", "H22": "SS", "H26": "LF",
    "H32": "CF", "H38": "RF",
    "I1": "Fielding Ratings", "I2": "Framing", "I4": "Arm", "I6": "Arm",
    "I8": "Range", "I10": "Error", "I12": "Range", "I14": "Error", "I16": "TDP",
    "I18": "Range", "I20": "Error", "I22": "Range", "I24": "Error",
    "I26": "Range", "I28": "Error", "I30": "Arm", "I32": "Range", "I34": "Error",
    "I36": "Arm", "I38": "Range", "I40": "Error", "I42": "Arm",
    "J8": "Height", "J12": "Arm", "J18": "Arm", "J22": "Arm", "J24": "TDP",
    "L1": "Fielding Stats", "L2": "C FRM/1000", "L3": "C SBA/1000", "L4": "C RTO%",
    "L5": "1B PA/1200", "L6": "1B PM%", "L7": "1B E%",
    "L8": "2B PA/1200", "L9": "2B PM%", "L10": "2B E%", "L11": "2B DP/1200",
    "L12": "3B PA/1200", "L13": "3B PM%", "L14": "3B E%",
    "L15": "SS PA/1200", "L16": "SS PM%", "L17": "SS E%",
    "L18": "LF PA/1200", "L19": "LF PM%", "L20": "LF E%", "L21": "LF ARM",
    "L22": "CF PA/1200", "L23": "CF PM%", "L24": "CF E%", "L25": "CF ARM",
    "L26": "RF PA/1200", "L27": "RF PM%", "L28": "RF E%", "L29": "RF ARM",
    "L30": "SS DP/1200",
    "O1": "Pos ADJ", "O2": "C", "O3": "1B", "O4": "2B", "O5": "3B", "O6": "SS",
    "O7": "LF", "O8": "CF", "O9": "RF", "O10": "DH",
    "S1": "Starter Ratings", "S2": "STU", "S3": "HRA", "S4": "pBABIP", "S5": "CON",
    "S6": "Reliever Ratings", "S7": "STU", "S8": "HRA", "S9": "pBABIP", "S10": "CON",
    "S11": "wOBA", "S12": "HBP", "S13": "BB", "S14": "1B", "S15": "2B", "S16": "3B",
    "S17": "HR", "S18": "SB", "S19": "CS", "S20": "Scale",
    "S22": "Matchups", "S23": "LvR", "S24": "RvR", "S25": "SvR", "S26": "OVR vR",
    "S28": "League Stats", "S29": "wOBA", "S30": "WAA Constant", "S31": "BF",
    "S32": "BF RP", "S33": "IP", "S34": "IP RP", "S35": "RunCS", "S36": "wSB",
    "S37": "BF/IP", "S38": "Team IP", "S39": "Pen IP", "S40": "R/PA",
    "S41": "RA/9 SP", "S42": "RA/9 RP", "S43": "RA/9",
    "U1": "Hold", "U6": "Hold",
    "V1": "Pitching Stats", "V2": "SP", "V3": "BB%", "V4": "HR%", "V5": "SO%",
    "V6": "BABIP", "V7": "XBH%", "V8": "3B%", "V9": "SB%", "V10": "HBP%",
    "V11": "IBB", "V12": "SBA%",
    "V14": "RP", "V15": "BB%", "V16": "HR%", "V17": "SO%", "V18": "BABIP",
    "V19": "XBH%", "V20": "3B%", "V21": "SB%", "V22": "HBP%", "V23": "IBB",
    "V24": "SBA%",
    "V28": "wOBA RP", "V29": "HBP", "V30": "BB", "V31": "1B", "V32": "2B",
    "V33": "3B", "V34": "HR", "V35": "SB", "V36": "CS", "V37": "Scale",
}

# (group, section, label, cell) in top-to-bottom sheet order. Duplicate labels
# (e.g. the two C 'Arm' anchor cells, SvR/OVR vR both = U11) are kept in order —
# the sheet-sync step matches duplicate labels top-to-bottom within a section.
OUTPUTS = [
    ("anchors", "hitting", "Eye", "F2"), ("anchors", "hitting", "Power", "F3"),
    ("anchors", "hitting", "AvK", "F4"), ("anchors", "hitting", "BABIP", "F5"),
    ("anchors", "hitting", "Gap", "F6"), ("anchors", "hitting", "Speed", "F7"),
    ("anchors", "hitting", "Stealing", "F8"), ("anchors", "hitting", "Baserunning", "F9"),
    ("anchors", "sp", "STU", "T2"), ("anchors", "sp", "Hold", "U2"),
    ("anchors", "sp", "HRA", "T3"), ("anchors", "sp", "pBABIP", "T4"),
    ("anchors", "sp", "CON", "T5"),
    ("anchors", "rp", "STU", "T7"), ("anchors", "rp", "Hold", "U7"),
    ("anchors", "rp", "HRA", "T8"), ("anchors", "rp", "pBABIP", "T9"),
    ("anchors", "rp", "CON", "T10"),
    ("woba_weights", "hitting", "HBP", "F12"), ("woba_weights", "hitting", "BB", "F13"),
    ("woba_weights", "hitting", "1B", "F14"), ("woba_weights", "hitting", "2B", "F15"),
    ("woba_weights", "hitting", "3B", "F16"), ("woba_weights", "hitting", "HR", "F17"),
    ("woba_weights", "hitting", "SB", "F18"), ("woba_weights", "hitting", "CS", "F19"),
    ("woba_weights", "hitting", "Scale", "F20"),
    ("woba_weights", "sp", "wOBA", "T11"), ("woba_weights", "sp", "HBP", "T12"),
    ("woba_weights", "sp", "BB", "T13"), ("woba_weights", "sp", "1B", "T14"),
    ("woba_weights", "sp", "2B", "T15"), ("woba_weights", "sp", "3B", "T16"),
    ("woba_weights", "sp", "HR", "T17"), ("woba_weights", "sp", "SB", "T18"),
    ("woba_weights", "sp", "CS", "T19"), ("woba_weights", "sp", "Scale", "T20"),
    ("woba_weights", "rp", "wOBA RP", "W28"), ("woba_weights", "rp", "HBP", "W29"),
    ("woba_weights", "rp", "BB", "W30"), ("woba_weights", "rp", "1B", "W31"),
    ("woba_weights", "rp", "2B", "W32"), ("woba_weights", "rp", "3B", "W33"),
    ("woba_weights", "rp", "HR", "W34"), ("woba_weights", "rp", "SB", "W35"),
    ("woba_weights", "rp", "CS", "W36"), ("woba_weights", "rp", "Scale", "W37"),
    ("matchups", "hitting", "LvR", "F23"), ("matchups", "hitting", "RvR", "F24"),
    ("matchups", "hitting", "SvR", "F25"), ("matchups", "hitting", "OVR vR", "F26"),
    ("matchups", "pitching", "LvR", "T23"), ("matchups", "pitching", "RvR", "T24"),
    ("matchups", "pitching", "SvR", "T25"), ("matchups", "pitching", "OVR vR", "T26"),
    ("league_stats", "hitting", "wOBA", "F29"), ("league_stats", "hitting", "WAA Constant", "F30"),
    ("league_stats", "hitting", "PA", "F31"), ("league_stats", "hitting", "PA Catcher", "F32"),
    ("league_stats", "hitting", "IP", "F33"), ("league_stats", "hitting", "IP Catcher", "F34"),
    ("league_stats", "hitting", "RunCS", "F35"), ("league_stats", "hitting", "wSB", "F36"),
    ("league_stats", "hitting", "HBP", "F37"), ("league_stats", "hitting", "Infield Out", "F38"),
    ("league_stats", "hitting", "Outfield Out", "F39"), ("league_stats", "hitting", "R/PA", "F40"),
    ("league_stats", "pitching", "wOBA", "T29"), ("league_stats", "pitching", "WAA Constant", "T30"),
    ("league_stats", "pitching", "BF", "T31"), ("league_stats", "pitching", "BF RP", "T32"),
    ("league_stats", "pitching", "IP", "T33"), ("league_stats", "pitching", "IP RP", "T34"),
    ("league_stats", "pitching", "RunCS", "T35"), ("league_stats", "pitching", "wSB", "T36"),
    ("league_stats", "pitching", "BF/IP", "T37"), ("league_stats", "pitching", "Team IP", "T38"),
    ("league_stats", "pitching", "Pen IP", "T39"), ("league_stats", "pitching", "R/PA", "T40"),
    ("league_stats", "pitching", "RA/9 SP", "T41"), ("league_stats", "pitching", "RA/9 RP", "T42"),
    ("league_stats", "pitching", "RA/9", "T43"),
    ("rates", "hitting", "BB%", "B33"), ("rates", "hitting", "HR%", "B34"),
    ("rates", "hitting", "SO%", "B35"), ("rates", "hitting", "BABIP", "B36"),
    ("rates", "hitting", "XBH%", "B37"), ("rates", "hitting", "3B%", "B38"),
    ("rates", "hitting", "SB%", "B39"), ("rates", "hitting", "UBR", "B40"),
    ("rates", "hitting", "SBA%", "B41"),
    ("rates", "sp", "BB%", "W3"), ("rates", "sp", "HR%", "W4"), ("rates", "sp", "SO%", "W5"),
    ("rates", "sp", "BABIP", "W6"), ("rates", "sp", "XBH%", "W7"), ("rates", "sp", "3B%", "W8"),
    ("rates", "sp", "SB%", "W9"), ("rates", "sp", "HBP%", "W10"), ("rates", "sp", "IBB", "W11"),
    ("rates", "sp", "SBA%", "W12"),
    ("rates", "rp", "BB%", "W15"), ("rates", "rp", "HR%", "W16"), ("rates", "rp", "SO%", "W17"),
    ("rates", "rp", "BABIP", "W18"), ("rates", "rp", "XBH%", "W19"), ("rates", "rp", "3B%", "W20"),
    ("rates", "rp", "SB%", "W21"), ("rates", "rp", "HBP%", "W22"), ("rates", "rp", "IBB", "W23"),
    ("rates", "rp", "SBA%", "W24"),
    ("rates", "fielding", "C FRM/1000", "M2"), ("rates", "fielding", "C SBA/1000", "M3"),
    ("rates", "fielding", "C RTO%", "M4"),
    ("rates", "fielding", "1B PA/1200", "M5"), ("rates", "fielding", "1B PM%", "M6"),
    ("rates", "fielding", "1B E%", "M7"),
    ("rates", "fielding", "2B PA/1200", "M8"), ("rates", "fielding", "2B PM%", "M9"),
    ("rates", "fielding", "2B E%", "M10"), ("rates", "fielding", "2B DP/1200", "M11"),
    ("rates", "fielding", "3B PA/1200", "M12"), ("rates", "fielding", "3B PM%", "M13"),
    ("rates", "fielding", "3B E%", "M14"),
    ("rates", "fielding", "SS PA/1200", "M15"), ("rates", "fielding", "SS PM%", "M16"),
    ("rates", "fielding", "SS E%", "M17"),
    ("rates", "fielding", "LF PA/1200", "M18"), ("rates", "fielding", "LF PM%", "M19"),
    ("rates", "fielding", "LF E%", "M20"), ("rates", "fielding", "LF ARM", "M21"),
    ("rates", "fielding", "CF PA/1200", "M22"), ("rates", "fielding", "CF PM%", "M23"),
    ("rates", "fielding", "CF E%", "M24"), ("rates", "fielding", "CF ARM", "M25"),
    ("rates", "fielding", "RF PA/1200", "M26"), ("rates", "fielding", "RF PM%", "M27"),
    ("rates", "fielding", "RF E%", "M28"), ("rates", "fielding", "RF ARM", "M29"),
    ("rates", "fielding", "SS DP/1200", "M30"),
    ("fielding_anchors", "C", "Framing", "I3"),
    ("fielding_anchors", "C", "Arm", "I5"), ("fielding_anchors", "C", "Arm", "I7"),
    ("fielding_anchors", "1B", "Range", "I9"), ("fielding_anchors", "1B", "Height", "J9"),
    ("fielding_anchors", "1B", "Error", "I11"),
    ("fielding_anchors", "2B", "Range", "I13"), ("fielding_anchors", "2B", "Arm", "J13"),
    ("fielding_anchors", "2B", "Error", "I15"), ("fielding_anchors", "2B", "TDP", "I17"),
    ("fielding_anchors", "3B", "Range", "I19"), ("fielding_anchors", "3B", "Arm", "J19"),
    ("fielding_anchors", "3B", "Error", "I21"),
    ("fielding_anchors", "SS", "Range", "I23"), ("fielding_anchors", "SS", "Arm", "J23"),
    ("fielding_anchors", "SS", "Error", "I25"), ("fielding_anchors", "SS", "TDP", "J25"),
    ("fielding_anchors", "LF", "Range", "I27"), ("fielding_anchors", "LF", "Error", "I29"),
    ("fielding_anchors", "LF", "Arm", "I31"),
    ("fielding_anchors", "CF", "Range", "I33"), ("fielding_anchors", "CF", "Error", "I35"),
    ("fielding_anchors", "CF", "Arm", "I37"),
    ("fielding_anchors", "RF", "Range", "I39"), ("fielding_anchors", "RF", "Error", "I41"),
    ("fielding_anchors", "RF", "Arm", "I43"),
    ("pos_adj", "pos_adj", "C", "P2"), ("pos_adj", "pos_adj", "1B", "P3"),
    ("pos_adj", "pos_adj", "2B", "P4"), ("pos_adj", "pos_adj", "3B", "P5"),
    ("pos_adj", "pos_adj", "SS", "P6"), ("pos_adj", "pos_adj", "LF", "P7"),
    ("pos_adj", "pos_adj", "CF", "P8"), ("pos_adj", "pos_adj", "RF", "P9"),
    ("pos_adj", "pos_adj", "DH", "P10"),
]

# Data Points cells fed by the workbook's Data-Model pivots (the ones its stale
# cache poisons); used only for the validation hint.
MODEL_BACKED = {cell for g, s, l, cell in OUTPUTS if g in ("fielding_anchors", "pos_adj")}


def build_json(cells):
    groups = {}
    for group, section, label, cell in OUTPUTS:
        groups.setdefault(group, []).append(
            {"section": section, "label": label, "cell": cell, "value": cells[cell]})
    allcells = dict(LABELS)
    allcells.update(cells)
    return {"groups": groups, "cells": allcells}

# ---------------------------------------------------------------- validation


def _cellkey(c):
    m = re.match(r"([A-Z]+)(\d+)", c)
    return (m.group(1), int(m.group(2)))


def validate(cells, expected_path, model_ids):
    exp = json.load(open(expected_path, encoding="utf-8"))
    exp = {k: v for k, v in exp.items() if k != "labels"}
    computed = dict(LABELS)
    computed.update(cells)
    npass = nfail = 0
    fails = []
    for cell in sorted(exp, key=_cellkey):
        want = exp[cell]
        got = computed.get(cell)
        if isinstance(want, str) or isinstance(got, str):
            ok = got == want
            rel = 0.0 if ok else float("inf")
        elif got is None:
            ok, rel = False, float("inf")
        else:
            rel = abs(got - want) / max(1e-30, abs(want))
            ok = abs(got - want) <= 1e-9 + 1e-6 * abs(want)
        npass += ok
        nfail += (not ok)
        tag = "PASS" if ok else "FAIL"
        note = "" if ok else f"   want {want!r} got {got!r}"
        print(f"  {tag}  {cell:<5} {str(exp.get(cell))[:20]:<20} rel {rel:.2e}{note}")
        if not ok:
            fails.append(cell)
    print(f"\n  {npass} PASS / {nfail} FAIL")
    if fails and model_ids is None and all(c in MODEL_BACKED for c in fails):
        print("  all failures are Data-Model-backed cells (fielding anchors / pos adj):\n"
              "  the workbook's 'Fielding Ratings'/'Adj Pivot' caches are stale (13 IDs\n"
              "  missing; see module docstring). Re-run with --model-ids FILE (the ID\n"
              "  list from the cached Adj Pivot col A) to confirm cache emulation passes;\n"
              "  the fresh values computed here are the correct ones.")
    return nfail == 0


def load_model_ids(path):
    txt = open(path, encoding="utf-8-sig").read().strip()
    if txt.startswith("["):
        return {int(x) for x in json.loads(txt)}
    return {int(line) for line in txt.split() if line.strip()}

# ---------------------------------------------------------------- driver


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--inputs-dir", required=True,
                    help="dir with the input-tab CSVs (Hitting_Data.csv etc.)")
    ap.add_argument("--validate", help="expected_metadata.json to compare against")
    ap.add_argument("--json", help="write labeled groups + cells map to this path")
    ap.add_argument("--model-ids",
                    help="file of IDs (one per line or JSON array) the workbook's "
                         "Data-Model pivots contained; restricts the model-backed "
                         "layer to emulate the workbook's stale cache (validation)")
    a = ap.parse_args()
    model_ids = load_model_ids(a.model_ids) if a.model_ids else None
    cells = compute_cells(a.inputs_dir, model_ids)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(build_json(cells), f, indent=1)
        print(f"wrote {a.json}")
    if a.validate:
        sys.exit(0 if validate(cells, a.validate, model_ids) else 1)


if __name__ == "__main__":
    main()
