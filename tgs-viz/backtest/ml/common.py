"""
common.py - shared helpers for the DEV machine-learning backtest (backtest/ml).

What lives here:
  paths          the ml data / preds / models / report folders under .dev_cache/ml
  constants      peak bars, the regular-season bars, org levels, fold count
  scale          underlying(): 20-80 display to OOTP's 1-600 internal points
                 (ratings_db.UNDERLYING_BAND middles, 20 read at 115.5)
  cards          parse raw StatsPlus-schema rows (DEV raw dumps, TGS/BLM raw
                 pulls) into float arrays keyed by the raw key name
  features       build_features(): one feature table from a current card, the
                 card one game-year earlier and two game-years earlier; the
                 SAME code builds the DEV training rows and the TGS/BLM
                 scoring rows
  spec           feature_spec(): name, dtype, family, DEV source and TGS/BLM
                 source of every feature, for schema.json
  tables         save_table() / load_table(): pandas pickle (.pkl); pyarrow is
                 not installed under Python 3.14, so no parquet
  folds          fold_of(): stable 0..4 fold from an md5 of the player id
  bases          one model set per league (2026-09-24): BASES, waa_tag(),
                 basis_waa_files() pick the DEV engine prices of one
                 calibration by its file tag (BLM: vintages/DEV/.waa_cache,
                 TGS: .dev_cache/ml/waa_TGS from ml/reprice.py); basis_name()
                 and load_schema(basis) name the per-basis tables;
                 score_level() reads a winter-league (WL) player as R;
                 use_basis(basis) points PREDS_DIR / MODELS_DIR / REPORT_DIR
                 at the per-basis folders preds/<basis>, models/<basis>,
                 report/<basis>; dev_table(role) names the basis table
  model extras   amateur_flag(): the one model-only feature (1 = amateur),
                 read from the DEV raw Lev or the app Lev
  earlier card   the earlier dump / pull is read whatever his status there
                 (amateur, free agent or in an org; user, 2026-10-05: rating
                 changes count "from generation onward"). mask_earlier_card()
                 applies the card-replaced failsafe: every feature built from
                 the earlier card is unknown where the change from it is
                 larger than real development (card_replaced_mask,
                 dev_signals.CARD_LIMITS); prev_in_org stays a context input
  history        history_inputs(): the player's own earlier seasons
                 (2026-09-25, behind the --history switch of dataset.py):
                 (A) recent detail 1, 2 and 3 seasons back, (B) the whole
                 record from E (his earliest usable dump / pull) to now.
                 sim_depth() and apply_archive_depth(): the archive-depth
                 mask the training scripts apply to DEV rows, so a DEV row
                 can look like a league player whose archive is short.
                 use_history() points dev_table / load_schema / score_table
                 at the *_hist tables (default off)

Every script in backtest/ml imports this module. Nothing here writes outside
.dev_cache/ml. The DEV league is the only source of training rows; TGS and BLM
only get scored (leagues are separate).
"""
import glob
import gzip
import hashlib
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- paths
ML_HERE = os.path.dirname(os.path.abspath(__file__))          # tgs-viz/backtest/ml
BT = os.path.dirname(ML_HERE)                                   # tgs-viz/backtest
VIZ = os.path.dirname(BT)                                       # tgs-viz
DEV_VINT = os.path.join(BT, "vintages", "DEV")
DEV_WAA_DIR = os.path.join(DEV_VINT, ".waa_cache")
ENGINE_CALIB = os.path.join(VIZ, "engine", "calib")
PT_CACHE = os.path.join(BT, ".dev_cache", "dev_mlb_pt.json.gz")
# The TGS / BLM ratings archive (the DB and its vintages). RATINGS_ARCHIVE_ROOT
# (tests only) points both at a copy; the DEV files above never move.
ARCHIVE_ROOT = os.environ.get("RATINGS_ARCHIVE_ROOT") or BT
DB_PATH = os.path.join(ARCHIVE_ROOT, "ratings_history.db")
LEAGUE_VINT = os.path.join(ARCHIVE_ROOT, "vintages")          # vintages/<LG>/<real_date>_p<id>.csv.gz
APP_DATA = os.path.join(VIZ, "public", "data")
INGEST_CACHE = os.path.join(VIZ, "ingest", ".cache")

ML_ROOT = os.path.join(BT, ".dev_cache", "ml")
DATA_DIR = os.path.join(ML_ROOT, "data")
PREDS_DIR = os.path.join(ML_ROOT, "preds")
MODELS_DIR = os.path.join(ML_ROOT, "models")
REPORT_DIR = os.path.join(ML_ROOT, "report")

# ONE MODEL SET PER LEAGUE (2026-09-24). TGS and BLM are separate leagues, and
# the DEV rows get their now / ceiling WAA from the engine, so each league's
# model trains on DEV priced with that league's own calibration and scores that
# league's own app values. BLM basis = vintages/DEV/.waa_cache files tagged
# '<BLM fingerprint>-BLM' (agecurve_fit --league DEV --calib BLM); TGS basis =
# .dev_cache/ml/waa_TGS files tagged '<TGS fingerprint>-TGS' (ml/reprice.py).
# The files are picked by that tag, never as "the newest file per vintage".
BASES = ("TGS", "BLM")
WAA_BASIS_DIR = {"BLM": DEV_WAA_DIR, "TGS": os.path.join(ML_ROOT, "waa_TGS")}


def extra_leagues():
    """{league: basis} of the exported leagues (ingest/export_league.py, user
    2026-09-27: a fun OOTP 27 save "Regular Game" with BLM's settings): the
    public/data/leagues.json entries that carry a "basis". Such a league is
    scored with that basis' models (no model set of its own)."""
    p = os.path.join(VIZ, "public", "data", "leagues.json")
    try:
        with open(p, encoding="utf-8") as fh:
            entries = json.load(fh).get("leagues") or []
    except (OSError, ValueError):
        return {}
    return {e["id"]: e["basis"] for e in entries
            if e.get("basis") in BASES and e.get("id") not in BASES}


def league_basis(league):
    """Model basis a league is scored with: TGS and BLM their own, an exported
    league the basis its manifest entry names. Stops on an unknown league."""
    if league in BASES:
        return league
    b = extra_leagues().get(league)
    if not b:
        raise SystemExit(f"{league} is neither a basis ({', '.join(BASES)}) nor an exported league with a basis "
                         "in public/data/leagues.json")
    return b


def scoring_leagues():
    return list(BASES) + sorted(extra_leagues())

# Per-basis output folders. use_basis() moves PREDS_DIR, MODELS_DIR and
# REPORT_DIR into a <basis> subfolder, so the TGS and BLM models, predictions
# and reports never overwrite each other. The tuned settings of the first run
# (models/peak_settings.json, models/path_settings.json) stay in MODELS_ROOT and
# both bases read them as they are: no re-tuning per basis.
PREDS_ROOT, MODELS_ROOT, REPORT_ROOT = PREDS_DIR, MODELS_DIR, REPORT_DIR
BASIS = None

if BT not in sys.path:
    sys.path.insert(0, BT)
import dev_signals as DSIG                                      # noqa: E402  (stdlib only)

# ---------------------------------------------------------------- constants
ROLES = ("H", "P")
PITCHER_POS = {"SP", "RP", "CL"}
ORG_LEV = {"R", "A", "A-", "A+", "AA", "AAA", "MLB"}          # dev_odds.ORG_LEV
NO_ORG_LEVELS = {"AMA", "FA", "INT"}                            # dev_signals.NO_ORG_LEVELS
PEAK_BARS = {"mlb": -1.0, "useful": 0.0, "good": 1.5}           # dev_odds.PEAK_BARS
PEAK_MIN_AGE = 27                                               # dev_odds.PEAK_MIN_AGE
REGULAR_PA = 300                                                # dev_odds.REGULAR_PA
REGULAR_BF = 150                                                # dev_odds.REGULAR_BF
N_FOLDS = 5
HORIZONS = (1, 2, 3, 4, 5)
AGE_MIN, AGE_MAX = 16, 40                                       # row ages kept in the DEV tables

# collapsed org level. DEV has one A tier and one R tier; TGS / BLM split them.
LEVELS = ["none", "R", "A", "AA", "AAA", "MLB"]
LEVEL_RANK = {"none": 0, "R": 1, "A": 2, "AA": 3, "AAA": 4, "MLB": 5}
_LEVEL_MAP = {"MLB": "MLB", "AAA": "AAA", "AA": "AA", "A": "A", "A+": "A", "A-": "A",
              "R": "R", "R+": "R", "R-": "R", "FA": "none", "AMA": "none", "INT": "none"}
POS_CATS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SP", "RP", "CL"]
BATS_CATS = ["R", "L", "S"]
THROWS_CATS = ["R", "L"]

# OOTP velocity code (DEV dump) -> StatsPlus velocity band. Inferred, not read
# from OOTP: the order of the StatsPlus bands, with the DEV and BLM pitcher
# modes lining up at code 9 = "89-91".
VEL_BANDS = ["75-80", "80-83", "83-85", "84-86", "85-87", "86-88", "87-89", "88-90", "89-91",
             "90-92", "91-93", "92-94", "93-95", "94-96", "95-97", "96-98", "97-99", "98-100",
             "99-101", "100+"]
VEL_CODE = {b: i + 1 for i, b in enumerate(VEL_BANDS)}

# ---------------------------------------------------------------- skills
# (feature stem, raw key stem, potential raw key); raw stem has _R and _L
SPLIT_SKILLS = {
    "H": [("babip", "BABIP", "PotBABIP"), ("gap", "Gap", "PotGap"), ("pow", "Pow", "PotPow"),
          ("eye", "Eye", "PotEye"), ("avk", "Ks", "PotKs"), ("cnt", "Cntct", "PotCntct")],
    "P": [("stu", "Stf", "PotStf"), ("hrr", "HRA", "PotHRA"), ("pbabip", "PBABIP", "PotPBABIP"),
          ("con", "Ctrl", "PotCtrl")],
}
# core skills: dev_odds.CORE (H BABIP GAP POW EYE K; P STU HRR PBABIP CON)
CORE = {"H": ["babip", "gap", "pow", "eye", "avk"], "P": ["stu", "hrr", "pbabip", "con"]}
RUN_KEYS = [("speed", "Speed"), ("stlrt", "StlRt"), ("steal", "Steal"), ("run", "Run")]
FLD_KEYS = [("ifr", "IFR"), ("ife", "IFE"), ("ifa", "IFA"), ("tdp", "TDP"), ("ofr", "OFR"),
            ("ofe", "OFE"), ("ofa", "OFA"), ("cblk", "CBlk"), ("cfrm", "CFrm"), ("carm", "CArm")]
POS_KEYS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"]
PITCH_KEYS = ["Fst", "Snk", "Cutt", "Crv", "Sld", "Chg", "Splt", "Frk", "CirChg", "Scr", "Kncrv", "Knbl"]
P_SINGLE = [("stm", "Stm"), ("hold", "Hold"), ("gb", "GB")]

# raw keys read as numbers from a card (DEV raw rows and TGS/BLM raw pulls share them)
RAW_NUM = (["Age", "Ovr", "Pot", "Height", "Mov", "PotMov", "VelCode"]
           + [f"{stem}_{s}" for role in ROLES for _f, stem, _p in SPLIT_SKILLS[role] for s in ("R", "L")]
           + [pot for role in ROLES for _f, _s, pot in SPLIT_SKILLS[role]]
           + [k for _f, k in RUN_KEYS + FLD_KEYS + P_SINGLE]
           + POS_KEYS + ["Pot" + p for p in POS_KEYS]
           + PITCH_KEYS + ["Pot" + p for p in PITCH_KEYS])
RAW_STR = ["ID", "Pos", "Lev", "Bats", "Throws", "DOB"]

# archive vintage columns (ratings_db, vintages/<LG>/*.csv.gz) -> raw key.
# Only what the earlier-pull side needs: the core splits, Pot and Ovr.
ARCHIVE_TO_RAW = {
    "c_BA_vR": "BABIP_R", "c_BA_vL": "BABIP_L", "c_GAP_vR": "Gap_R", "c_GAP_vL": "Gap_L",
    "c_POW_vR": "Pow_R", "c_POW_vL": "Pow_L", "c_EYE_vR": "Eye_R", "c_EYE_vL": "Eye_L",
    "c_K_vR": "Ks_R", "c_K_vL": "Ks_L",
    "c_STU_vR": "Stf_R", "c_STU_vL": "Stf_L", "c_HRR_vR": "HRA_R", "c_HRR_vL": "HRA_L",
    "c_PBABIP_vR": "PBABIP_R", "c_PBABIP_vL": "PBABIP_L", "c_CON_vR": "Ctrl_R", "c_CON_vL": "Ctrl_L",
    "c_Pot": "Pot", "c_Ovr": "Ovr",
}

# ---------------------------------------------------------------- scale
# ratings_db.UNDERLYING_BAND middles; 20 = the measured floor 115.5 (ratings_db.UNDERLYING_MID)
UNDERLYING_MID = {20: 115.5, 25: 153.5, 30: 198.0, 35: 249.5, 40: 299.0, 45: 348.5, 50: 393.5,
                  55: 424.5, 60: 443.0, 65: 457.0, 70: 471.5, 75: 485.5, 80: 505.0, 85: 559.0}
_UND_LUT = np.full(18, np.nan)
for _k, _v in UNDERLYING_MID.items():
    _UND_LUT[_k // 5] = _v


def underlying(display):
    """Internal 1-600 points of 20-80 display values (array or scalar).

    Same rule as ratings_db.underlying: round to the nearest 5-point band
    (round half to even, like Python's round), 20 and below read 115.5, 85 and
    above read 559. NaN stays NaN."""
    v = np.asarray(display, dtype=np.float64)
    k = np.round(v / 5.0)
    k = np.clip(k, 4, 17)
    out = np.where(np.isnan(v), np.nan, _UND_LUT[np.nan_to_num(k, nan=4).astype(int)])
    return out


def split_internal(r, l):
    """Mean of the internal points of the vR and the vL rating. Each side is a
    whole 5-point step, so no rounding of a half-step mean is needed."""
    return (underlying(r) + underlying(l)) / 2.0


def role_of(pos):
    return "P" if pos in PITCHER_POS else "H"


def collapse_level(lev):
    """App or dump Lev string -> one of LEVELS, or None when unknown (WL, blank)."""
    if lev is None:
        return None
    return _LEVEL_MAP.get(str(lev).strip())


# Scoring rule (2026-09-24): a TGS winter-league player (app Lev "WL") has no
# level of his own; he reads R, the rookie rung. The WL is an overlay of the
# best young prospects, so R is the lowest org rung that fits every one of them.
SCORE_LEVEL_EXTRA = {"WL": "R"}


def score_level(lev):
    """collapse_level for a TGS / BLM scoring row: WL reads R."""
    if lev is None:
        return None
    s = str(lev).strip()
    return SCORE_LEVEL_EXTRA.get(s) or _LEVEL_MAP.get(s)


def fold_of(pid):
    """Stable fold 0..N_FOLDS-1 from the md5 of the player id string."""
    h = hashlib.md5(str(pid).encode("utf-8")).hexdigest()
    return int(h[:8], 16) % N_FOLDS


def to_num(v):
    """Raw rating value -> float, NaN when blank. '-' reads 20 (ratings_db.num)."""
    if v is None:
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s == "":
        return np.nan
    if s == "-":
        return 20.0
    try:
        return float(s)
    except ValueError:
        return np.nan


# ---------------------------------------------------------------- cards
def parse_cards(rows):
    """Raw StatsPlus-schema rows -> (ids, num, strs).

    ids  = list of player id strings
    num  = {raw key: float32 array} for every RAW_NUM key (NaN when absent);
           VelCode is filled from the StatsPlus 'Vel' band when the row has no
           VelCode (TGS / BLM pulls)
    strs = {raw key: object array} for RAW_STR keys"""
    df = pd.DataFrame.from_records(rows)
    n = len(df)
    num = {}
    for k in RAW_NUM:
        if k in df.columns:
            col = df[k]
            if col.dtype == object:
                col = col.replace({"-": "20", "": None})
            num[k] = pd.to_numeric(col, errors="coerce").to_numpy(dtype=np.float32)
        else:
            num[k] = np.full(n, np.nan, dtype=np.float32)
    if np.isnan(num["VelCode"]).all() and "Vel" in df.columns:
        num["VelCode"] = df["Vel"].map(lambda s: VEL_CODE.get(str(s).strip(), np.nan)).to_numpy(dtype=np.float32)
    strs = {}
    for k in RAW_STR:
        strs[k] = df[k].astype(object).to_numpy() if k in df.columns else np.full(n, None, dtype=object)
    ids = [str(x) for x in strs["ID"]]
    return ids, num, strs


def take(num, idx):
    """Rows idx (int array, -1 = missing) of a card dict; missing rows are NaN."""
    idx = np.asarray(idx)
    ok = idx >= 0
    out = {}
    for k, v in num.items():
        a = np.full(len(idx), np.nan, dtype=np.float32)
        a[ok] = v[idx[ok]]
        out[k] = a
    return out


# ---------------------------------------------------------------- features
def _f32(a):
    return np.asarray(a, dtype=np.float32)


# OOTP OVR / POT scale (user, 2026-09-26): the DEV league rated OVR and POT
# relative to ALL players through dump 2414 and relative to POSITION from dump
# 2415 on ("which will be like TGS more"); measured on the dumps: from 2415
# catchers' mean OVR / POT rise 25.6 / 36.3 -> 27.2 / 37.7 while 1B, 2B, SS,
# CF and RF fall 1-1.5; pitchers do not move. Both leagues rate relative to
# ALL players (BLM: user; TGS: user, 2026-09-26, "in the tgs constitution it
# actually says that players are relative to all for ovr and pot", so the DEV
# switch did not match TGS after all). pot_scale (1 = position, 0 = all
# players) is a model input, so the DEV seasons on the position scale still
# train everything else while every league row is scored on the all-players
# scale; a Pot / OVR change across the switch is unknown (d_pot / d_ovr NaN).
OVR_POT_SCALE_SWITCH_DEV = 2415
LEAGUE_OVR_POT_SCALE = {"TGS": 0.0, "BLM": 0.0}


def dev_pot_scale(year):
    """pot_scale of DEV dump years: 1.0 from OVR_POT_SCALE_SWITCH_DEV, else 0.0."""
    return (np.asarray(year, dtype=np.float64) >= OVR_POT_SCALE_SWITCH_DEV).astype(np.float32)


def build_features(role, cur, prev=None, prev2=None, span1=1.0, span2=2.0, ctx=None):
    """One feature table (dict name -> array) for players of one role.

    cur, prev, prev2  card dicts (raw key -> float array, NaN = missing) for the
                      current dump / pull, the one about one game-year earlier
                      and the one about two game-years earlier (prev2 may be
                      None: two-year growth is then NaN)
    span1, span2      game-years between cur and prev / prev2 (scalar or
                      array); one-year growth is divided by span1 so it is per
                      game-year (dev_signals scales the same way); two-year
                      growth is the raw total, not scaled
    ctx               dict of arrays: age, age_frac, level (object: LEVELS
                      value or None), in_org, pos, bats, throws, now, ceil,
                      prev_now, prev_ceil, prev_in_org (1 in an org at the
                      card one game-year earlier, 0 out of an org, NaN no such
                      card; context only), card_replaced / card_replaced2
                      (True where the card-replaced failsafe tripped for the
                      one-year / two-year pair; see mask_earlier_card)
    Categorical features come back as object arrays; the caller makes them
    pandas categories with the fixed category lists in this module."""
    ctx = ctx or {}
    n = len(cur["Age"])
    nanv = np.full(n, np.nan, dtype=np.float32)
    f = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        # context
        f["age"] = _f32(ctx.get("age", cur["Age"]))
        f["age_frac"] = _f32(ctx.get("age_frac", nanv))
        lev = np.asarray(ctx.get("level", np.full(n, None, dtype=object)), dtype=object)
        f["level"] = lev
        f["level_rank"] = _f32([LEVEL_RANK.get(x, np.nan) if x is not None else np.nan for x in lev])
        f["in_org"] = _f32(ctx.get("in_org", nanv))
        f["prev_in_org"] = _f32(ctx.get("prev_in_org", nanv))
        f["pos"] = np.asarray(ctx.get("pos", np.full(n, None, dtype=object)), dtype=object)
        f["bats"] = np.asarray(ctx.get("bats", np.full(n, None, dtype=object)), dtype=object)
        f["throws"] = np.asarray(ctx.get("throws", np.full(n, None, dtype=object)), dtype=object)
        f["height"] = _f32(cur["Height"])
        # value
        now = _f32(ctx.get("now", nanv))
        ceil = _f32(ctx.get("ceil", nanv))
        f["now_waa"] = now
        f["ceiling_waa"] = ceil
        f["ceiling_gap"] = ceil - now
        f["ovr"] = _f32(cur["Ovr"])
        f["pot"] = _f32(cur["Pot"])
        f["pot_minus_ovr"] = f["pot"] - f["ovr"]
        f["pot_scale"] = _f32(ctx.get("pot_scale", nanv))

        # split skills: display mean, lean, potential, room
        core_int = np.zeros(n)
        room_core = np.zeros(n)
        for name, stem, potk in SPLIT_SKILLS[role]:
            r, l = cur[stem + "_R"], cur[stem + "_L"]
            f[f"{name}_mean"] = _f32((r + l) / 2.0)
            f[f"{name}_lean"] = _f32(r - l)
            f[f"pot_{name}"] = _f32(cur[potk])
            ci = split_internal(r, l)
            f[f"room_{name}"] = _f32(underlying(cur[potk]) - ci)
            if name in CORE[role]:
                core_int = core_int + ci
                room_core = room_core + (underlying(cur[potk]) - ci)
        f["core_int"] = _f32(core_int)
        f["room_core"] = _f32(room_core)

        if role == "H":
            for name, key in RUN_KEYS + FLD_KEYS:
                f[name] = _f32(cur[key])
            pos = np.stack([cur[p] for p in POS_KEYS], axis=1)
            ppos = np.stack([cur["Pot" + p] for p in POS_KEYS], axis=1)
            # StatsPlus shows a position potential of 0 wherever the current
            # position rating is 0; the DEV dump fills one in. Zero it the
            # StatsPlus way so both sides mean the same thing.
            ppos = np.where(pos == 0, 0.0, ppos)
            for j, p in enumerate(POS_KEYS):
                f[f"pos_{p.lower()}"] = _f32(pos[:, j])
                f[f"potpos_{p.lower()}"] = _f32(ppos[:, j])
            allnan = np.isnan(pos).all(axis=1)
            f["best_pos"] = _f32(np.where(allnan, np.nan, np.nanmax(np.where(np.isnan(pos), -1, pos), axis=1)))
            pallnan = np.isnan(ppos).all(axis=1)
            f["best_pos_pot"] = _f32(np.where(pallnan, np.nan, np.nanmax(np.where(np.isnan(ppos), -1, ppos), axis=1)))
            f["n_pos50"] = _f32(np.where(allnan, np.nan, (np.nan_to_num(pos, nan=0) >= 50).sum(axis=1)))
        else:
            f["mov"] = _f32(cur["Mov"])
            f["pot_mov"] = _f32(cur["PotMov"])
            f["room_mov"] = _f32(underlying(cur["PotMov"]) - underlying(cur["Mov"]))
            f["vel"] = _f32(cur["VelCode"])
            for name, key in P_SINGLE:
                f[name] = _f32(cur[key])
            pc = np.stack([cur[p] for p in PITCH_KEYS], axis=1)
            pp = np.stack([cur["Pot" + p] for p in PITCH_KEYS], axis=1)
            allnan = np.isnan(pc).all(axis=1)
            f["n_pitches45"] = _f32(np.where(allnan, np.nan, (np.nan_to_num(pc, nan=0) >= 45).sum(axis=1)))
            f["best_pitch"] = _f32(np.where(allnan, np.nan, np.nanmax(np.where(np.isnan(pc), -1, pc), axis=1)))
            pallnan = np.isnan(pp).all(axis=1)
            f["best_pitch_pot"] = _f32(np.where(pallnan, np.nan, np.nanmax(np.where(np.isnan(pp), -1, pp), axis=1)))

        # growth over the core skills (per game-year for one year, raw total for two)
        span1 = np.asarray(span1, dtype=np.float64)
        g_steps_tot = np.zeros(n)
        g_int_tot = np.zeros(n)
        g2_steps_tot = np.zeros(n)
        g2_int_tot = np.zeros(n)
        stems = {name: stem for name, stem, _p in SPLIT_SKILLS[role]}
        for name in CORE[role]:
            stem = stems[name]
            r, l = cur[stem + "_R"], cur[stem + "_L"]
            d_now = (r + l) / 2.0
            i_now = split_internal(r, l)
            if prev is not None:
                pr, pl = prev[stem + "_R"], prev[stem + "_L"]
                gs = ((d_now - (pr + pl) / 2.0) / 5.0) / span1
                gi = (i_now - split_internal(pr, pl)) / span1
            else:
                gs = gi = np.full(n, np.nan)
            f[f"g_{name}_steps"] = _f32(gs)
            f[f"g_{name}_int"] = _f32(gi)
            g_steps_tot = g_steps_tot + gs
            g_int_tot = g_int_tot + gi
            if prev2 is not None:
                qr, ql = prev2[stem + "_R"], prev2[stem + "_L"]
                g2_steps_tot = g2_steps_tot + (d_now - (qr + ql) / 2.0) / 5.0
                g2_int_tot = g2_int_tot + (i_now - split_internal(qr, ql))
            else:
                g2_steps_tot = g2_steps_tot + np.nan
                g2_int_tot = g2_int_tot + np.nan
        f["grow_steps"] = _f32(g_steps_tot)
        # dev_odds / dev_signals round the step total to 0.5 (half_steps)
        f["grow_steps_r"] = _f32(np.round(g_steps_tot * 2.0) / 2.0 + 0.0)
        f["grow_int"] = _f32(g_int_tot)
        f["grow2_steps"] = _f32(g2_steps_tot)
        f["grow2_int"] = _f32(g2_int_tot)
        if prev is not None:
            f["d_pot"] = _f32(cur["Pot"] - prev["Pot"])
            f["d_ovr"] = _f32(cur["Ovr"] - prev["Ovr"])
            # a change of OVR / POT scale between the two cards is not growth
            pps = _f32(ctx.get("prev_pot_scale", f["pot_scale"]))
            switched = ~np.isnan(pps) & ~np.isnan(f["pot_scale"]) & (pps != f["pot_scale"])
            f["d_pot"] = np.where(switched, np.nan, f["d_pot"]).astype(np.float32)
            f["d_ovr"] = np.where(switched, np.nan, f["d_ovr"]).astype(np.float32)
        else:
            f["d_pot"] = f["d_ovr"] = nanv.copy()
        f["d_ceiling"] = _f32(ceil - _f32(ctx.get("prev_ceil", nanv)))
        f["d_now"] = _f32(now - _f32(ctx.get("prev_now", nanv)))
    return mask_earlier_card(f, role, ctx.get("card_replaced"), ctx.get("card_replaced2"))


# Earlier card (user, 2026-10-05): the card one / two game-years back is read
# whatever the player's status there. An amateur, an unsigned international
# or a free agent has a real card from the day OOTP generates him, so his
# rating changes count from then on. This replaces the out-of-an-org rule of
# 2026-09-25, which blanked every feature built from the earlier card when he
# was out of an org there; it rested on a wrong story (hidden draft-class
# cards). What really happened: TGS regenerated its draft classes once, in
# Jan 2045, after an age-rule change (player 37730: SP Jason Lindhout, Pot
# 40, batting 20 at pull 43, 2045-01-09; CF Lance Grueninger, Pot 80,
# batting 35-45 at pull 45, 2045-01-30), and the growth features read that
# swap as growth.
# Card-replaced failsafe: where the change from the earlier card is larger
# than real development ever produces (dev_signals.CARD_LIMITS, measured on
# DEV), every feature built from that card is unknown, as if there were no
# earlier card. DEV rows: the yearly pair (dump_year-1 -> dump_year); TGS /
# BLM rows: dev_signals.replaced_cards (the pair and every short step inside
# its window). prev_in_org (1 in an org, 0 out of an org, NaN no earlier
# card) stays a context input.
PREV_CARD_FEATURES = {
    role: [f"g_{n}_{u}" for n in CORE[role] for u in ("steps", "int")]
    + ["grow_steps", "grow_steps_r", "grow_int", "d_pot", "d_ovr", "d_ceiling", "d_now"]
    for role in ROLES}
PREV2_CARD_FEATURES = ["grow2_steps", "grow2_int"]


def _bool_mask(m):
    """Boolean array of a mask (None stays None; NaN reads False)."""
    if m is None:
        return None
    a = np.asarray(m)
    if a.dtype == bool:
        return a
    a = a.astype(np.float64)
    return ~np.isnan(a) & (a != 0)


def mask_earlier_card(f, role, replaced=None, replaced2=None):
    """Apply the card-replaced failsafe to a feature dict in place: the
    features of PREV_CARD_FEATURES become NaN where replaced is True, the
    two-year growth where replaced2 is True; has_prev is then 1 only where
    one-year growth is known. None = nothing masked. Safe to call twice.
    Returns f."""
    rep = _bool_mask(replaced)
    if rep is not None and rep.any():
        for k in PREV_CARD_FEATURES[role]:
            if k in f:
                f[k] = _f32(np.where(rep, np.nan, f[k]))
    rep2 = _bool_mask(replaced2)
    if rep2 is not None and rep2.any():
        for k in PREV2_CARD_FEATURES:
            if k in f:
                f[k] = _f32(np.where(rep2, np.nan, f[k]))
    f["has_prev"] = _f32(~np.isnan(f["grow_steps"]))
    return f


def card_limit_arrays(role, age):
    """(pot, up, down) float arrays of dev_signals.CARD_LIMITS for each row.
    role is one role for every row ('H' / 'P') or an array of roles; age is
    clamped to dev_signals.CARD_LIMIT_AGES; an unknown age gets NaN limits
    (never trips)."""
    a = np.asarray(age, dtype=np.float64)
    n = a.shape[0]
    lo, hi = DSIG.CARD_LIMIT_AGES
    ai = np.clip(np.nan_to_num(np.floor(a), nan=lo), lo, hi).astype(int)
    roles = np.broadcast_to(np.asarray(role, dtype=object), (n,))
    out = [np.full(n, np.nan) for _ in range(3)]
    for r in ROLES:
        m = (roles == r) & ~np.isnan(a)
        if not m.any():
            continue
        tab = np.array([DSIG.CARD_LIMITS[r][x] for x in range(lo, hi + 1)], dtype=np.float64)
        for j in range(3):
            out[j][m] = tab[ai[m] - lo, j]
    return tuple(out)


def card_replaced_mask(role, age, d_pot, grow_steps_total, span=1.0, same_pos=None):
    """True where a change from the earlier card trips the card-replaced
    failsafe (dev_signals.card_change_trips, the pair rule): |d_pot| over the
    Pot limit, or the core change in display steps (the RAW total over the
    span, not per game-year) over the growth limit or under the decline
    limit, each limit times max(1, span). d_pot is not compared where
    same_pos is False (Pot is graded at the listed position). NaN inputs
    never trip."""
    pot, up, down = card_limit_arrays(role, age)
    scale = np.maximum(1.0, np.nan_to_num(np.asarray(span, dtype=np.float64), nan=1.0))
    dp = np.asarray(d_pot, dtype=np.float64)
    g = np.asarray(grow_steps_total, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        trip_pot = np.abs(dp) > pot * scale
        if same_pos is not None:
            trip_pot = trip_pot & np.asarray(same_pos, dtype=bool)
        trip = trip_pot | (g > up * scale) | (g < down * scale)
    return np.asarray(trip, dtype=bool)


CATEGORICAL = {"level": LEVELS, "pos": POS_CATS, "bats": BATS_CATS, "throws": THROWS_CATS}


def to_frame(feats):
    """Feature dict -> DataFrame; the CATEGORICAL columns become pandas
    categories with fixed category lists (an unseen value becomes NaN)."""
    cols = {}
    for k, v in feats.items():
        if k in CATEGORICAL:
            cols[k] = pd.Categorical(pd.Series(v, dtype=object).where(pd.notna(v), None),
                                     categories=CATEGORICAL[k])
        else:
            cols[k] = np.asarray(v, dtype=np.float32)
    return pd.DataFrame(cols)


# ---------------------------------------------------------------- spec
def _lg_split(stem_sheet):
    return f"raw StatsPlus pull {stem_sheet}_R / {stem_sheet}_L (app: the same keys)"


def feature_spec(role, basis=None, history=False):
    """[{name, dtype, family, dev_source, lg_source, desc}] in build_features order.
    basis (TGS / BLM) names the engine calibration that priced the DEV value
    columns; None keeps the old text (BLM). history=True appends the history
    inputs (history_spec)."""
    S = []
    waa_src = (".dev_cache/ml/waa_TGS (TGS engine calibration, neutral park, ml/reprice.py)"
               if basis == "TGS" else "vintages/DEV/.waa_cache files tagged <BLM fingerprint>-BLM "
                                      "(BLM engine calibration, neutral park)")

    def add(name, family, dev, lg, desc, dtype="float32"):
        S.append({"name": name, "dtype": dtype, "family": family, "dev_source": dev,
                  "lg_source": lg, "desc": desc})

    raw_lg = "raw StatsPlus pull of the latest vintage (ingest/.cache/history), key "
    add("age", "context", "raw dump Age (Jan-1 age, integer)", "app hitters/pitchers.json Age (age at the pull date)",
        "integer age")
    add("age_frac", "context", "(Jan 1 of dump_year+1 - DOB) / 365.25 from the raw dump DOB",
        "none: TGS / BLM data carry no birth date", "fractional age at the dump")
    add("level", "context", "raw dump Lev collapsed (MLB AAA AA A R none); MLB with no MLB PA and no MLB BF in the "
        "season just played and age <= 22 reads R (parked international kids)",
        "app Lev collapsed (A+/A- -> A, R+/R- -> R, AMA/FA/INT -> none, WL -> R: the rookie rung, "
        "scoring rule 2026-09-24, common.score_level)",
        "org level", "category")
    add("level_rank", "context", "level as 0..5 (none R A AA AAA MLB)", "same", "org level rank")
    add("in_org", "context", "raw Lev in dev_odds.ORG_LEV", "app Lev not in AMA/FA/INT and not blank (dev_signals.in_org)",
        "1 = under contract with an org")
    add("prev_in_org", "context",
        "raw Lev at dump_year-1 in dev_odds.ORG_LEV: 1, else 0; NaN when he is not in that dump (first seen)",
        "earlier pull's lev (the archive vintage dev_signals.choose_clean_pulls picks; a blank lev is rebuilt "
        "from the raw pull first, dev_signals.fill_blank_levs): 0 for AMA, FA, INT, '-' (foreign league) or "
        "blank, else 1; NaN when he is missing from that pull or there is no earlier pull",
        "1 = in an org at the earlier card, 0 = out of an org there (an amateur or free agent; his card is read "
        "all the same), NaN = no earlier card")
    add("pos", "context", "raw dump Pos", "app POS", "listed position", "category")
    add("bats", "context", "raw dump Bats", "raw pull Bats", "R / L / S", "category")
    add("throws", "context", "raw dump Throws", "raw pull Throws", "R / L", "category")
    add("height", "context", "raw dump Height (cm)", raw_lg + "Height (cm)", "height in cm")
    now_lg = ("app hitters.json 'Max WAA wtd' / pitchers.json max('WAA wtd', 'WAA wtd RP') (dev_signals.app_rows)")
    ceil_lg = "app hitters.json 'MAX WAA P' / pitchers.json max('WAP', 'WAP RP')"
    add("now_waa", "value", waa_src + " element 0", now_lg, "WAA today")
    add("ceiling_waa", "value", waa_src + " element 1", ceil_lg, "engine WAA at the listed potential ratings")
    add("ceiling_gap", "value", "ceiling_waa - now_waa", "same", "listed room in WAA")
    add("ovr", "value", "raw dump Ovr (1-point steps; NaN in the 2025 dump)", raw_lg + "Ovr (TGS 1-point, BLM 5-point steps)",
        "OOTP overall grade")
    add("pot", "value", "raw dump Pot (NaN in 2025)", raw_lg + "Pot (TGS 1-point, BLM 5-point steps)", "OOTP potential grade")
    add("pot_minus_ovr", "value", "pot - ovr", "same", "grade room")
    add("pot_scale", "value", f"1.0 from DEV dump {OVR_POT_SCALE_SWITCH_DEV} (OVR / POT relative to position), "
        "0.0 before (relative to all players)", "TGS and BLM 0.0 (relative to all players)",
        "OOTP OVR / POT scale")
    fam_cur = "bat" if role == "H" else "pitch"
    fam_pot = "bat_pot" if role == "H" else "pitch_pot"
    for name, stem, potk in SPLIT_SKILLS[role]:
        add(f"{name}_mean", fam_cur, f"raw dump ({stem}_R + {stem}_L) / 2", _lg_split(stem),
            f"{name} display value, vR/vL mean")
        add(f"{name}_lean", fam_cur, f"raw dump {stem}_R - {stem}_L", _lg_split(stem), f"{name} vR minus vL")
        add(f"pot_{name}", fam_pot, f"raw dump {potk}", raw_lg + potk, f"{name} potential (display)")
        add(f"room_{name}", fam_pot, f"underlying({potk}) - mean(underlying({stem}_R), underlying({stem}_L))",
            "same from the raw pull", f"{name} room in internal points")
    add("core_int", fam_cur, "sum over the core skills of the internal vR/vL mean", "same", "core skills in internal points")
    add("room_core", fam_pot, "sum of the core rooms", "same", "core room in internal points")
    if role == "H":
        for name, key in RUN_KEYS:
            add(name, "bat", f"raw dump {key}", raw_lg + key, f"running: {key}")
        for name, key in FLD_KEYS:
            add(name, "glove", f"raw dump {key}", raw_lg + key, f"fielding: {key}")
        for p in POS_KEYS:
            add(f"pos_{p.lower()}", "glove", f"raw dump {p}", raw_lg + p, f"position rating {p} (0 = cannot play)")
            add(f"potpos_{p.lower()}", "glove", f"raw dump Pot{p}, set to 0 where {p} is 0 (the StatsPlus rule)",
                raw_lg + "Pot" + p, f"position potential {p}")
        add("best_pos", "glove", "max of the 8 position ratings C..RF", "same", "best position rating")
        add("best_pos_pot", "glove", "max of PotC..PotRF", "same", "best position potential")
        add("n_pos50", "glove", "count of C..RF ratings >= 50", "same", "positions playable at 50+")
    else:
        add("mov", "pitch", "raw dump Mov", raw_lg + "Mov", "movement (overall)")
        add("pot_mov", "pitch_pot", "raw dump PotMov", raw_lg + "PotMov", "movement potential")
        add("room_mov", "pitch_pot", "underlying(PotMov) - underlying(Mov)", "same", "movement room, internal points")
        add("vel", "pitch", "raw dump VelCode (OOTP velocity code)",
            raw_lg + "Vel band mapped to the code by common.VEL_BANDS (inferred order)", "velocity code")
        for name, key in P_SINGLE:
            add(name, "pitch", f"raw dump {key}", raw_lg + key, key)
        add("n_pitches45", "pitch", "count of the 12 pitch grades >= 45", "same", "pitches at 45+")
        add("best_pitch", "pitch", "max pitch grade", "same", "best pitch grade")
        add("best_pitch_pot", "pitch_pot", "max pitch potential", "same", "best pitch potential")
    lg_prev = ("earlier pull = the archive vintage (vintages/<LG>/*.csv.gz) dev_signals.choose_clean_pulls "
               "picks: the pull nearest one game-year before the latest whose pair with the latest pull "
               "ratings_db.pair_guard does not flag; per game-year = divided by the span")
    for name in CORE[role]:
        add(f"g_{name}_steps", "growth", f"(display now - display at dump_year-1) / 5", lg_prev,
            f"{name} growth in display steps per game-year")
        add(f"g_{name}_int", "growth", "internal now - internal at dump_year-1", lg_prev,
            f"{name} growth in internal points per game-year")
    add("grow_steps", "growth", "sum of g_*_steps over the core skills", lg_prev, "core growth, display steps")
    add("grow_steps_r", "growth", "grow_steps rounded to 0.5 (dev_odds growth)", lg_prev, "dev_odds growth value")
    add("grow_int", "growth", "sum of g_*_int", lg_prev, "core growth, internal points")
    add("grow2_steps", "growth", "core display steps gained since dump_year-2 (total, not per year)",
        "none: the TGS / BLM archives span under two game-years", "two-year core growth, steps")
    add("grow2_int", "growth", "core internal points gained since dump_year-2", "none (same reason)",
        "two-year core growth, internal")
    add("d_pot", "growth", "Pot - Pot at dump_year-1", "latest Pot - earlier pull c_Pot (not scaled, dev_signals pot_delta)",
        "Pot grade change")
    add("d_ovr", "growth", "Ovr - Ovr at dump_year-1", "latest Ovr - earlier pull c_Ovr", "Ovr grade change")
    add("d_ceiling", "growth", "ceiling_waa - ceiling_waa at dump_year-1 (DEV prices on the same basis)",
        "league .waa_cache (the league's own current calibration fingerprint, neutral park) at the latest pull "
        "minus at the earlier pull",
        "listed-peak change")
    add("d_now", "growth", "now_waa - now_waa at dump_year-1", "league .waa_cache pair, as d_ceiling", "now-WAA change")
    add("has_prev", "growth", "1 when growth is known (0 when there is no earlier card or the card-replaced "
        "failsafe tripped, common.mask_earlier_card)", "same", "growth known flag")
    if history:
        S.extend(history_spec(role))
    return S


# ---------------------------------------------------------------- history inputs
# User, 2026-09-25: "oh yeah it should absolutely use all of the seasons it
# already has on file i always assumed it did", and "why 2-3 seasons why not
# their entire career so it can get everyone's trajectory". Two kinds of
# inputs, all read from the player's own earlier dumps (DEV) or pulls (TGS /
# BLM):
#   (A) RECENT DETAIL, k = 1, 2, 3 seasons back (h<k>_*, h_grow_int_prev,
#       h_accel): core growth, Pot / Ovr change, now / ceiling WAA change,
#       level change over k seasons; growth the season before last and the
#       change from it (acceleration).
#   (B) WHOLE RECORD from E to now (seasons_recorded, archive_depth, rec_*,
#       h_grow_int_max3). E = his earliest usable dump / pull: no
#       card-replaced trip between it and now (the failsafe of
#       mask_earlier_card), the same person under the ID (TGS reused IDs), no
#       rating-scale event between it and now (BLM), and at least
#       HIST_MIN_SPAN game-years back. No such dump: E = now, seasons_recorded
#       0, every total 0 and every per-season value unknown.
# A card read (skills, Pot, Ovr, WAA) from an earlier dump needs no
# card-replaced trip between it and now: DEV, no yearly pair in between trips;
# a league, the pair from that pull to the latest pull does not trip and no
# short step in between does (dev_signals.card_steps). His status there
# (amateur, free agent or in an org) does not matter (user, 2026-10-05).
# His level and org status there are not card data and are read as they are
# (seasons in an org, seasons at the current level).
#
# The same function builds both sides. A DEV "slot" is the dump j seasons
# back (span j); a league slot is an archived pull (span = game-years back).
# League deltas are put on a whole-season footing like DEV: an A total over
# span s stands for k seasons and is scaled by k / s; a B total over span sE
# is scaled by round(sE) / sE; a per-season value is total / sE. Pot and Ovr
# changes are not scaled (OOTP re-rates them once a spring; dev_signals reads
# pot_delta unscaled too). Level changes are not scaled.
#
# ARCHIVE-DEPTH MASK. The TGS / BLM archives are short (TGS reaches back 1.68
# game-years, BLM 0.81 after its rating-scale event), so most league players
# show a short record because the ARCHIVE is short, not because they are new.
# In DEV a short record only happens to young or newly seen players. So each
# DEV row gets a simulated archive depth (sim_depth, from an md5 of pid and
# dump_year): half the rows keep the full record, the rest see 0, 1, 2 or 3
# seasons (one eighth each). apply_archive_depth() swaps in the record
# inputs recomputed over that shorter archive (the __w<d> columns), blanks
# the recent inputs deeper than d, and at d = 0 blanks the one-year growth
# too. archive_depth tells the model how far back the archive itself goes
# (DEV: min(dump_year - 2025, d, 4); a league: its oldest clean pull, e.g.
# TGS 1.68, BLM 0.81); seasons_recorded tells it how far back his own record
# goes inside that archive.
HIST_K = (1, 2, 3)
HIST_WINDOWS = (0, 1, 2, 3)
HIST_MIN_SPAN = 0.5            # game-years: a pull closer than this is no season of record
ARCHIVE_DEPTH_CAP = 4.0        # archive_depth 4 = "4 or more seasons of archive"
SIM_FULL = -1                  # sim_depth of a row that keeps its full record


def hist_recent_names(role):
    """(A) recent-detail input names of one role, in table order."""
    out = []
    for k in HIST_K:
        out += ([f"h{k}_grow_int"] + [f"h{k}_g_{s}_int" for s in CORE[role]]
                + [f"h{k}_d_pot", f"h{k}_d_ovr", f"h{k}_d_now", f"h{k}_d_ceiling", f"h{k}_d_level"])
    return out + ["h_grow_int_prev", "h_accel"]


def hist_record_names(role):
    """(B) whole-record input names of one role (plus the windowed
    h_grow_int_max3); these are recomputed per archive window (__w<d>)."""
    return (["seasons_recorded", "archive_depth", "rec_age_start", "rec_level_start",
             "rec_grow_int", "rec_grow_int_ps"]
            + [f"rec_g_{s}_int{x}" for s in CORE[role] for x in ("", "_ps")]
            + ["rec_d_pot", "rec_d_pot_ps", "rec_pot_max", "rec_pot_below_max", "rec_d_now_ps",
               "rec_now_best", "rec_now_below_best", "rec_seasons_since_best", "rec_d_level_ps",
               "rec_seasons_in_org", "rec_seasons_at_level", "h_grow_int_max3"])


def hist_feature_names(role):
    return hist_recent_names(role) + hist_record_names(role)


def hist_window_columns(role):
    """Names of the stored window variants <name>__w<d> (d = 0..3)."""
    return [f"{n}__w{d}" for d in HIST_WINDOWS for n in hist_record_names(role)]


def sim_depth(pid, dump_year):
    """Simulated archive depth of one DEV row: SIM_FULL (-1) for about half
    the rows, else 0, 1, 2 or 3 seasons (one eighth each). Deterministic: md5
    of 'pid/dump_year'."""
    h = hashlib.md5(f"{int(pid)}/{int(dump_year)}".encode("utf-8")).hexdigest()
    u = int(h[:8], 16) / 4294967296.0
    return SIM_FULL if u < 0.5 else min(3, int((u - 0.5) * 8.0))


def sim_depths(pids, years):
    return np.array([sim_depth(p, y) for p, y in zip(pids, years)], dtype=np.int8)


def _nan(n):
    return np.full(n, np.nan, dtype=np.float64)


def _span_arr(s, n):
    return np.broadcast_to(np.asarray(s["span"], dtype=np.float64), (n,))


def whole_seasons(span):
    """round(span) with 0.5-1.5 -> 1, 1.5-2.5 -> 2, ... (never below 1)."""
    return np.maximum(1.0, np.floor(np.asarray(span, dtype=np.float64) + 0.5))


def history_inputs(role, cur, path, kslots, window=None, archive_depth=np.nan, recent=True):
    """History inputs of one role as {name: float32 array}.

    cur     the current card: arrays 'age', 'rank' (level rank, NaN unknown),
            'in_org' (1 / 0), 'core' (core internal points), 'i_<skill>' per
            core skill, 'pot', 'ovr', 'now', 'ceil'
    path    earlier slots, NEAREST FIRST (ascending span for every row): each
            a dict (or a callable returning one) with the cur keys plus 'span'
            (game-years back; scalar or array), 'present' (bool: his record,
            same person, clean pair) and 'usable' (present and no
            card-replaced trip between that card and now: card readable)
    kslots  {k: slot} the slot standing for k seasons back (A inputs)
    window  None = the whole archive; d = an archive that starts d seasons
            back (slots further back are ignored)
    recent  False = only the (B) record inputs (for the __w<d> variants)
    Rules: see the history block comment above."""
    n = len(cur["core"])
    W = np.inf if window is None else float(window)
    skills = [f"i_{s}" for s in CORE[role]]
    ekeys = ["age", "rank", "core", "pot", "now"] + skills
    f64 = {k: np.asarray(cur[k], dtype=np.float64) for k in ekeys + ["ovr", "ceil", "in_org"]}
    out = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        # ---- E: the oldest usable slot at least HIST_MIN_SPAN back, inside the window
        e = {k: f64[k].copy() for k in ekeys}
        e_span = np.zeros(n)
        slots = []
        for s in path:
            s = s() if callable(s) else s
            span = _span_arr(s, n)
            if np.nanmin(span, initial=np.inf) > W:
                break
            slots.append((s, span))
            cand = s["usable"] & (span >= HIST_MIN_SPAN) & (span <= W)
            if cand.any():
                for k in ekeys:
                    e[k] = np.where(cand, np.asarray(s[k], dtype=np.float64), e[k])
                e_span = np.where(cand, span, e_span)
        has = e_span >= HIST_MIN_SPAN
        sE = np.where(has, e_span, np.nan)

        # ---- walk the record from now back to E
        pot_max = f64["pot"].copy()
        best = f64["now"].copy()
        best_span = np.zeros(n)
        org = np.zeros(n)
        prev_span = np.zeros(n)
        prev_org = f64["in_org"].copy()
        run = np.zeros(n)
        running = ~np.isnan(f64["rank"])
        for s, span in slots:
            within = span <= e_span                      # NaN span -> False
            inwin = within & s["present"]
            u = inwin & s["usable"]
            v = np.asarray(s["pot"], dtype=np.float64)
            up = u & ~np.isnan(v) & (np.isnan(pot_max) | (v > pot_max))
            pot_max = np.where(up, v, pot_max)
            v = np.asarray(s["now"], dtype=np.float64)
            up = u & ~np.isnan(v) & (np.isnan(best) | (v > best))
            best = np.where(up, v, best)
            best_span = np.where(up, span, best_span)
            org = org + np.where(inwin & (prev_org == 1), span - prev_span, 0.0)
            prev_span = np.where(inwin, span, prev_span)
            prev_org = np.where(inwin, np.asarray(s["in_org"], dtype=np.float64), prev_org)
            same = running & inwin & (np.asarray(s["rank"], dtype=np.float64) == f64["rank"])
            run = np.where(same, span, run)
            running = np.where(within, same, running)

        tot = np.where(has, whole_seasons(np.where(has, e_span, 1.0)) / np.where(has, e_span, 1.0), 1.0)
        out["seasons_recorded"] = np.where(has, e_span, 0.0)
        ad = np.asarray(archive_depth, dtype=np.float64)
        out["archive_depth"] = np.broadcast_to(np.minimum(np.minimum(ad, W), ARCHIVE_DEPTH_CAP), (n,))
        out["rec_age_start"] = e["age"]
        out["rec_level_start"] = e["rank"]
        g = f64["core"] - e["core"]
        out["rec_grow_int"] = g * tot
        out["rec_grow_int_ps"] = g / sE
        for sk, name in zip(skills, CORE[role]):
            g = f64[sk] - e[sk]
            out[f"rec_g_{name}_int"] = g * tot
            out[f"rec_g_{name}_int_ps"] = g / sE
        g = f64["pot"] - e["pot"]
        out["rec_d_pot"] = g
        out["rec_d_pot_ps"] = g / sE
        out["rec_pot_max"] = pot_max
        out["rec_pot_below_max"] = f64["pot"] - pot_max
        out["rec_d_now_ps"] = (f64["now"] - e["now"]) / sE
        out["rec_now_best"] = best
        out["rec_now_below_best"] = f64["now"] - best
        out["rec_seasons_since_best"] = np.where(np.isnan(best), np.nan, best_span)
        out["rec_d_level_ps"] = (f64["rank"] - e["rank"]) / sE
        out["rec_seasons_in_org"] = org
        out["rec_seasons_at_level"] = np.where(np.isnan(f64["rank"]), np.nan, run)

        # ---- single-season growth among now, 1, 2 and 3 seasons back
        seq = ["cur"] + [kslots.get(k) for k in HIST_K]
        seq = [s() if callable(s) else s for s in seq]
        pair_g = []
        for a, b in zip(seq[:-1], seq[1:]):
            if a is None or b is None:
                pair_g.append(_nan(n))
                continue
            now_end = isinstance(a, str)
            sa = np.zeros(n) if now_end else _span_arr(a, n)
            ua = np.ones(n, dtype=bool) if now_end else a["usable"]
            ca = f64["core"] if now_end else np.asarray(a["core"], dtype=np.float64)
            sb = _span_arr(b, n)
            ok = ua & b["usable"] & (sb - sa >= HIST_MIN_SPAN) & (sb <= W)
            pair_g.append(np.where(ok, (ca - np.asarray(b["core"], dtype=np.float64)) / (sb - sa), np.nan))
        stack = np.stack(pair_g, axis=1)
        allnan = np.isnan(stack).all(axis=1)
        out["h_grow_int_max3"] = np.where(allnan, np.nan, np.nanmax(np.where(np.isnan(stack), -np.inf, stack), axis=1))

        if recent:
            for k in HIST_K:
                s = seq[k]
                if s is None:
                    for nm in ([f"h{k}_grow_int"] + [f"h{k}_g_{x}_int" for x in CORE[role]]
                               + [f"h{k}_d_pot", f"h{k}_d_ovr", f"h{k}_d_now", f"h{k}_d_ceiling", f"h{k}_d_level"]):
                        out[nm] = _nan(n)
                    continue
                u = s["usable"]
                fac = k / _span_arr(s, n)
                out[f"h{k}_grow_int"] = np.where(u, (f64["core"] - np.asarray(s["core"], np.float64)) * fac, np.nan)
                for sk, name in zip(skills, CORE[role]):
                    out[f"h{k}_g_{name}_int"] = np.where(u, (f64[sk] - np.asarray(s[sk], np.float64)) * fac, np.nan)
                out[f"h{k}_d_pot"] = np.where(u, f64["pot"] - np.asarray(s["pot"], np.float64), np.nan)
                out[f"h{k}_d_ovr"] = np.where(u, f64["ovr"] - np.asarray(s["ovr"], np.float64), np.nan)
                out[f"h{k}_d_now"] = np.where(u, (f64["now"] - np.asarray(s["now"], np.float64)) * fac, np.nan)
                out[f"h{k}_d_ceiling"] = np.where(u, (f64["ceil"] - np.asarray(s["ceil"], np.float64)) * fac, np.nan)
                out[f"h{k}_d_level"] = np.where(u, f64["rank"] - np.asarray(s["rank"], np.float64), np.nan)
            # pair_g[0] = now vs 1 back, pair_g[1] = 1 back vs 2 back (both per season)
            prev = pair_g[1] if seq[2] is not None else _nan(n)
            out["h_grow_int_prev"] = prev
            out["h_accel"] = pair_g[0] - prev
    names = hist_feature_names(role) if recent else hist_record_names(role)
    return {k: np.asarray(out[k], dtype=np.float32) for k in names}


def apply_archive_depth(df, role, depth_col="sim_depth", drop_windows=True):
    """The archive-depth mask for DEV training rows. Returns a new frame (the
    input is not changed): for each row with sim_depth d in 0..3,
      - every (B) record input takes its __w<d> value (recomputed over an
        archive that starts d seasons back),
      - every (A) input deeper than d is unknown (h<k>_* for k > d;
        h_grow_int_prev and h_accel need d >= 2),
      - d = 0: the one-year growth features of build_features are unknown,
        prev_in_org is unknown and has_prev is 0 (no earlier pull at all);
        d < 2: grow2_* unknown.
    Rows with sim_depth -1 keep the full record. drop_windows removes the
    __w<d> columns from the result."""
    d = df[depth_col].to_numpy().astype(np.int16)
    out = df.copy(deep=False)
    for name in hist_record_names(role):
        col = out[name].to_numpy(dtype=np.float32, copy=True)
        for w in HIST_WINDOWS:
            m = d == w
            if m.any():
                col[m] = out[f"{name}__w{w}"].to_numpy(dtype=np.float32)[m]
        out[name] = col
    for k in HIST_K:
        m = (d >= 0) & (d < k)
        if m.any():
            for name in [c for c in hist_recent_names(role) if c.startswith(f"h{k}_")]:
                col = out[name].to_numpy(dtype=np.float32, copy=True)
                col[m] = np.nan
                out[name] = col
    m2 = (d >= 0) & (d < 2)
    for name in ["h_grow_int_prev", "h_accel"] + [c for c in PREV2_CARD_FEATURES if c in out.columns]:
        col = out[name].to_numpy(dtype=np.float32, copy=True)
        col[m2] = np.nan
        out[name] = col
    m0 = d == 0
    if m0.any():
        for name in PREV_CARD_FEATURES[role] + ["prev_in_org"]:
            if name in out.columns:
                col = out[name].to_numpy(dtype=np.float32, copy=True)
                col[m0] = np.nan
                out[name] = col
        if "has_prev" in out.columns:
            col = out["has_prev"].to_numpy(dtype=np.float32, copy=True)
            col[m0] = 0.0
            out["has_prev"] = col
    if drop_windows:
        out = out.drop(columns=[c for c in hist_window_columns(role) if c in out.columns])
    return out


def history_spec(role):
    """feature_spec entries of the history inputs (family 'history')."""
    S = []

    def add(name, dev, lg, desc):
        S.append({"name": name, "dtype": "float32", "family": "history", "dev_source": dev,
                  "lg_source": lg, "desc": desc})

    lg_k = ("the archived pull nearest k game-years back (k = 1: the dev_signals.choose_clean_pulls pick; "
            "k = 2, 3: span within k +- 0.5 and at least 0.5 past the k-1 pick), clean against the latest "
            "pull (ratings_db.pair_guard); unknown when the card-replaced failsafe tripped between it and the "
            "latest pull (the pair or a short step in between), he is missing, or the ID was someone else's "
            "(dev_signals.same_person)")
    dev_k = ("dump dump_year-k; unknown when a yearly pair between it and now tripped the card-replaced "
             "failsafe, or he is not in it")
    for k in HIST_K:
        add(f"h{k}_grow_int", dev_k, lg_k + "; scaled by k / span",
            f"core growth over {k} season(s), internal points (total, not per season)")
        for s in CORE[role]:
            add(f"h{k}_g_{s}_int", dev_k, lg_k + "; scaled by k / span", f"{s} growth over {k} season(s), internal")
        add(f"h{k}_d_pot", dev_k, lg_k + "; not scaled", f"Pot change over {k} season(s)")
        add(f"h{k}_d_ovr", dev_k, lg_k + "; not scaled", f"Ovr change over {k} season(s)")
        add(f"h{k}_d_now", dev_k + "; DEV prices on the basis", lg_k + "; league .waa_cache (own fingerprint), "
            "scaled by k / span", f"now_WAA change over {k} season(s)")
        add(f"h{k}_d_ceiling", dev_k, lg_k + "; league .waa_cache, scaled by k / span",
            f"ceiling_WAA change over {k} season(s)")
        add(f"h{k}_d_level", dev_k + "; collapsed level rank", lg_k + "; archive lev (blank lev: rebuilt from the "
            "raw pull by dev_signals.fill_blank_levs, the app's rule statsplus._lev_for), WL reads R; not scaled",
            f"level rank change over {k} season(s)")
    add("h_grow_int_prev", "core growth from dump_year-2 to dump_year-1 (both cards usable)",
        "same from the k = 2 and k = 1 pulls, per season (needs 0.5+ game-years between them)",
        "core growth the season before last, internal points per season")
    add("h_accel", "(core growth over the last season) - h_grow_int_prev", "same, per season",
        "growth acceleration")
    rec_dev = ("E = his earliest dump with no card-replaced trip between it and now (whole record; under the "
               "archive-depth mask: the earliest such dump at most sim_depth seasons back)")
    rec_lg = ("E = his earliest archived pull that is clean against the latest pull, 0.5+ game-years back, "
              "with no card-replaced trip between it and the latest pull and the same person under the ID")
    add("seasons_recorded", rec_dev + "; seasons from E to now", rec_lg + "; game-years from E to now",
        "seasons of his own record (0 = none)")
    add("archive_depth", "min(dump_year - 2025, sim_depth, 4)", "game-years back to the oldest clean pull "
        "(TGS 1.68, BLM 0.81 on 2026-09-25), capped at 4", "how far back the archive itself goes")
    add("rec_age_start", rec_dev, rec_lg, "age at E")
    add("rec_level_start", rec_dev, rec_lg, "level rank at E")
    add("rec_grow_int", rec_dev, rec_lg + "; scaled by round(span) / span", "core growth since E, internal")
    add("rec_grow_int_ps", rec_dev, rec_lg, "core growth since E per season")
    for s in CORE[role]:
        add(f"rec_g_{s}_int", rec_dev, rec_lg + "; scaled by round(span) / span", f"{s} growth since E, internal")
        add(f"rec_g_{s}_int_ps", rec_dev, rec_lg, f"{s} growth since E per season")
    add("rec_d_pot", rec_dev, rec_lg + "; not scaled", "Pot now minus Pot at E")
    add("rec_d_pot_ps", rec_dev, rec_lg, "Pot change since E per season")
    add("rec_pot_max", rec_dev, rec_lg + "; over E, the k-season pulls after E and now", "highest Pot since E")
    add("rec_pot_below_max", rec_dev, rec_lg, "Pot now minus the highest Pot since E")
    add("rec_d_now_ps", rec_dev, rec_lg + "; league .waa_cache", "now_WAA change since E per season")
    add("rec_now_best", rec_dev, rec_lg + "; league .waa_cache", "best now_WAA since E")
    add("rec_now_below_best", rec_dev, rec_lg, "now_WAA minus the best since E")
    add("rec_seasons_since_best", rec_dev, rec_lg, "seasons since that best (0 = now is the best)")
    add("rec_d_level_ps", rec_dev, rec_lg, "levels climbed since E per season")
    add("rec_seasons_in_org", rec_dev + "; dumps after E with him in an org", rec_lg + "; game-years between "
        "record points with him in an org at the later one", "seasons in an org since E")
    add("rec_seasons_at_level", rec_dev, rec_lg, "seasons in a row at the current level (0 = new at it)")
    add("h_grow_int_max3", "largest single-season core growth among the last 3 seasons (both ends in an org)",
        "same over the now / k = 1, 2, 3 pulls, per season", "best recent single-season growth, internal")
    return S


# ---------------------------------------------------------------- engine WAA caches
def newest_waa_files(cache_dir):
    """{dump year: path} of the DEV .waa_cache, newest file (mtime) per vintage
    date; a file dated Jan 1 of year+1 belongs to dump_<year> (dev_odds.load_waa)."""
    newest = {}
    for p in glob.glob(os.path.join(cache_dir, "*.json")):
        m = re.match(r"(\d{4})-\d{2}-\d{2}_", os.path.basename(p))
        if not m:
            continue
        year = int(m.group(1)) - 1
        mt = os.path.getmtime(p)
        if year not in newest or mt > newest[year][0]:
            newest[year] = (mt, p)
    return {y: p for y, (_mt, p) in sorted(newest.items())}


def calib_fingerprint(league):
    """engine/agecurve_fit.calib_fingerprint, copied so this module needs no
    engine import: md5 of the calib files the engine reads, first 10 hex."""
    h = hashlib.md5()
    for fn in ("constants-latest.json", "scurves.json", "fielding_curves.json", "hitter_tails.json",
               "role_stuff.json", "currency.json"):
        p = os.path.join(ENGINE_CALIB, league, fn)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:10]


def check_basis(basis):
    if basis not in BASES:
        raise SystemExit(f"basis must be one of {', '.join(BASES)}, not {basis!r}")
    return basis


def waa_tag(basis):
    """File tag of the DEV prices on one basis: '<fingerprint>-<basis>', the
    tag agecurve_fit gives a DEV cache priced with a borrowed calibration."""
    return f"{calib_fingerprint(check_basis(basis))}-{basis}"


def basis_waa_files(basis):
    """{dump year: path} of the DEV engine prices on one basis, chosen by the
    calibration tag (never "newest file"). A file dated Jan 1 of year+1 belongs
    to dump_<year> (dev_odds.load_waa). Stops with a clear message when no file
    carries the current tag (the calibration changed: re-price first)."""
    d = WAA_BASIS_DIR[check_basis(basis)]
    tag = waa_tag(basis)
    out = {}
    for p in glob.glob(os.path.join(d, f"*.csv.gz.{tag}.json")):
        m = re.match(r"(\d{4})-\d{2}-\d{2}_", os.path.basename(p))
        if m:
            out[int(m.group(1)) - 1] = p
    if not out:
        how = ("python tgs-viz/engine/agecurve_fit.py --league DEV --calib BLM" if basis == "BLM"
               else "python tgs-viz/backtest/ml/reprice.py --calib TGS")
        raise SystemExit(f"no DEV engine prices tagged {tag} in {d}; run: {how}")
    return dict(sorted(out.items()))


def read_waa_file(path):
    """{pid: (now, ceil, kind)} with finite now and ceil (dev_odds.load_waa rule)."""
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    out = {}
    for pid, v in d.items():
        try:
            now, ceil = float(v[0]), float(v[1])
            kind = v[2] if len(v) > 2 else None
        except (TypeError, ValueError, IndexError):
            continue
        if math.isfinite(now) and math.isfinite(ceil):
            out[str(pid)] = (now, ceil, kind)
    return out


# ---------------------------------------------------------------- tables
def save_table(df, path):
    """Write a DataFrame as a pandas pickle (.pkl)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    df.to_pickle(tmp)
    os.replace(tmp, path)


# GitHub keeps the ML models and training tables in Git LFS (2026-10-06). A
# clone skips them by default (.lfsconfig), so each file is a small pointer
# text until `git lfs pull` downloads it.
LFS_PULL = 'git lfs pull --include="tgs-viz/backtest/.dev_cache/**" --exclude=""'


def is_lfs_pointer(path):
    """True when path is a Git LFS pointer file, not the real data."""
    try:
        with open(path, "rb") as fh:
            return fh.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


def check_downloaded(path):
    """Stop with the download command when path is a Git LFS pointer."""
    if is_lfs_pointer(path):
        raise SystemExit(f"{os.path.basename(path)} is not downloaded (Git LFS pointer). "
                         f"From the repo folder, run: {LFS_PULL}")


def load_table(path):
    check_downloaded(path)
    return pd.read_pickle(path)


def table_path(name):
    """.dev_cache/ml/data/<name>.pkl, e.g. table_path('dev_H')."""
    return os.path.join(DATA_DIR, f"{name}.pkl")


def use_basis(basis):
    """Select one basis for this run: BASIS, and PREDS_DIR / MODELS_DIR /
    REPORT_DIR move to preds/<basis>, models/<basis>, report/<basis>. The
    scripts read these names at call time, so call this before any work."""
    global BASIS, PREDS_DIR, MODELS_DIR, REPORT_DIR
    BASIS = check_basis(basis)
    PREDS_DIR = os.path.join(PREDS_ROOT, basis)
    MODELS_DIR = os.path.join(MODELS_ROOT, basis)
    REPORT_DIR = os.path.join(REPORT_ROOT, basis)
    return basis


def dev_table(role, basis=None):
    """Path of the DEV row table of one role on the basis (default: BASIS),
    e.g. dev_H_TGS.pkl. With no basis at all: the old dev_H.pkl. After
    use_history(True): the history table, e.g. dev_H_TGS_hist.pkl."""
    return table_path(hist_name(basis_name(f"dev_{role}", basis if basis is not None else BASIS)))


def score_table(league, role):
    """Path of the scoring rows of one league and role: score_TGS_H.pkl, or
    score_TGS_H_hist.pkl after use_history(True)."""
    return table_path(hist_name(f"score_{league}_{role}"))


# History tables (2026-09-25). dataset.py --history writes the tables with the
# history inputs under new names (suffix _hist), so the live tables stay as
# they are until the switch is turned on. use_history(True) makes dev_table,
# score_table and load_schema read the _hist names.
HISTORY = False
HIST_SUFFIX = "_hist"


def use_history(on=True):
    """Select the history tables (True) or the live tables (False) for this run."""
    global HISTORY
    HISTORY = bool(on)
    return HISTORY


def hist_name(name, history=None):
    """name + '_hist' when the history tables are selected (or history=True)."""
    on = HISTORY if history is None else history
    return f"{name}{HIST_SUFFIX}" if on else name


def basis_name(name, basis):
    """Table / file name on one basis: dev_H + BLM -> dev_H_BLM. basis None
    keeps the old single-basis name (the BLM-priced build of 2026-09-24)."""
    return name if basis is None else f"{name}_{check_basis(basis)}"


def load_schema(basis=None):
    """schema_<basis>.json; basis None reads the basis use_basis() selected,
    and the old schema.json when none is selected."""
    basis = basis if basis is not None else BASIS
    fn = "schema.json" if basis is None else f"{hist_name('schema_' + check_basis(basis))}.json"
    with open(os.path.join(DATA_DIR, fn), encoding="utf-8") as fh:
        return json.load(fh)


def usable_features(role, schema=None, basis=None):
    """Feature names of one role that the schema marks usable_for_scoring."""
    schema = schema or load_schema(basis)
    return [c["name"] for c in schema["roles"][role]["columns"]
            if c.get("kind") == "feature" and c.get("usable_for_scoring")]


# ---------------------------------------------------------------- model extras
# Rule (fix 6, 2026-09-24): the peak models also train on DEV rows outside an
# org at ages 16-26. Amateurs and free agents both read level 'none', but
# their odds are far apart (DEV peak rows at 16-26, TGS basis: useful rate AMA
# 0.030, FA 0.0014), so the models get one extra 0/1 feature, 'amateur'. It is
# not in schema_<basis>.json: the model manifests list it, and amateur_flag()
# makes it from a DEV table (raw Lev AMA) or a TGS / BLM scoring table (app Lev
# AMA or INT; INT = an unsigned international amateur, which DEV does not have).
AMATEUR_LEVELS = {"AMA", "INT"}
MODEL_EXTRA_FEATURES = ["amateur"]


def amateur_flag(df):
    """float32 array: 1 for an amateur, 0 for everyone else (in an org or a
    free agent). Reads lev_raw (DEV tables) or lev_app (scoring tables)."""
    col = "lev_raw" if "lev_raw" in df.columns else "lev_app" if "lev_app" in df.columns else None
    if col is None:
        raise KeyError("amateur_flag needs a lev_raw (DEV) or lev_app (TGS / BLM) column")
    s = df[col].astype(object)
    s = s.where(s.notna(), "").astype(str).str.strip()
    return s.isin(AMATEUR_LEVELS).to_numpy().astype(np.float32)


def chance_order(p_mlb, p_useful, p_good):
    """Rule (fix 2, 2026-09-24): the three bars are nested (-1 < 0 < +1.5 WAA),
    so the chances must be too: p_useful = min(p_useful, p_mlb) and
    p_good = min(p_good, p_useful). Separate classifiers can cross by a hair;
    this puts them back in order. Returns the three arrays (float32)."""
    pm = np.asarray(p_mlb, dtype=np.float32)
    pu = np.minimum(np.asarray(p_useful, dtype=np.float32), pm)
    pg = np.minimum(np.asarray(p_good, dtype=np.float32), pu)
    return pm, pu, pg


GAIN_QUANTS = np.array([0.10, 0.25, 0.50, 0.75, 0.90])


def blend_chance(p, need, q):
    """Rule (2026-09-26): the chance shown for a bar is the average of the
    reach classifier (p) and the chance the five gain quantiles (q, sorted,
    one row per player) give for a gain of at least `need` (bar minus now).

    Why: the two model parts are separate, so for a few players they
    disagreed (a peak range wholly above 0 next to a 51% Useful). On
    held-out DEV rows (time split) the average scored a lower log loss
    than the classifier alone on 11 of 12 basis x role x bar targets (TGS
    and BLM bases) and a better AUC on all 12, and where the parts differed
    by more than 25 points the truth sat between them (e.g. TGS hitters,
    0 WAA: actual 0.40, classifier 0.34, quantiles 0.52, average 0.43).

    The quantile chance is 1 - F(need), F linear between the quantile
    points (a repeated value counts once, at its lowest level). Beyond the
    ends the quantiles say only "under 10%" or "over 90%", so there the
    classifier's own value is clipped into that tail. A missing need keeps
    p. Returns float64."""
    p = np.asarray(p, dtype=np.float64)
    need = np.asarray(need, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    imp = p.copy()
    ok = np.isfinite(need)
    hi = ok & (need >= q[:, -1])
    lo = ok & (need <= q[:, 0])
    imp[hi] = np.clip(p[hi], 0.0, 0.1)
    imp[lo] = np.clip(p[lo], 0.9, 1.0)            # the low end wins when q10 == q90
    for i in np.flatnonzero(ok & ~hi & ~lo):
        qq, ii = np.unique(q[i], return_index=True)
        imp[i] = 1.0 - np.interp(need[i], qq, GAIN_QUANTS[ii])
    return (p + imp) / 2.0


def add_model_extras(df, names):
    """Add the model-only features in names (see MODEL_EXTRA_FEATURES) to df in
    place when missing. Returns df."""
    for n in names:
        if n == "amateur" and n not in df.columns:
            df[n] = amateur_flag(df)
    return df


def gz_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)
