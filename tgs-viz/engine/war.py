"""
war.py - WAR columns beside the engine's WAA (migration Phase 1, docs/PHASE1_AUDIT.md).

WAR = WAA + the league's replacement credit for the role, all at the engine's fixed playing
time (WAA is a rate there, not scaled by projected playing time):
  hitter   {pos} WAA {vR,vL,wtd,P} + hitter credit           (per 600 PA, H31)
  catcher  C WAA ...               + hitter credit x H32/H31  (C WAA is on 500 PA)
  SP       WAA {vR,vL,wtd}, WAP    + SP credit                (per H33 IP)
  RP       WAA {..} RP, WAP RP     + RP credit                (per H34 IP)
New columns: {pos} WAR {vR,vL,wtd,P}, Max WAR {vR,vL,wtd}, MAX WAR P, Best Pos WAR (argmax of
{pos} WAR wtd over the same eligible positions Best Pos uses); pitchers WAR {vR,vL,wtd},
WAR {..} RP, WARP, WARP RP. No pitcher role is chosen here (that decision is open).

The credits come from engine/calib/replacement.json via load_replacement(league). Nothing
calls this unless a caller passes a replacement dict (ingest/ratings.py run_hitters /
run_pitchers, replacement=...): the sheet validators and the ML repricing never do, so their
numbers are unchanged. Stdlib only.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPLACEMENT_PATH = os.path.join(HERE, "calib", "replacement.json")
POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH")
SUFFIXES = ("vR", "vL", "wtd", "P")
PITCH_COLS = ("WAA vR", "WAA vL", "WAA wtd")


def load_replacement(league, path=REPLACEMENT_PATH):
    """{"hitter", "sp", "rp", "league", "source"} for an app league, following one "use" proxy
    hop, or None when the league has no entry (then no WAR columns are written)."""
    try:
        with open(path, encoding="utf-8") as fh:
            table = json.load(fh)
    except (OSError, ValueError):
        return None
    ent = table.get(str(league))
    if not isinstance(ent, dict):
        return None
    used = str(league)
    if ent.get("use"):
        used = str(ent["use"])
        ent = table.get(used)
        if not isinstance(ent, dict) or ent.get("use"):
            return None
    try:
        out = {k: float(ent[k]) for k in ("hitter", "sp", "rp")}
    except (KeyError, TypeError, ValueError):
        return None
    out["league"] = used
    out["source"] = ent.get("source", "")
    return out


def catcher_share(basis):
    """H32/H31 of the basis' hitter sheet (catcher PA over hitter PA, 500/600 today)."""
    p = os.path.join(HERE, "extracted", f"{basis}_hitters_datapoints.json")
    try:
        with open(p, encoding="utf-8") as fh:
            dp = json.load(fh)
        return float(dp["H32"]) / float(dp["H31"])
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return 500.0 / 600.0


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _eligible(rec):
    """The positions Max WAA / Best Pos range over: the engine's eight flags, plus DH."""
    return [pos for pos in POSITIONS if pos == "DH" or rec.get(f"{pos} Eligible") is True]


def hitter_war(rec, repl, c_share):
    """The WAR columns of one hitter record (a dict of new keys)."""
    out = {}
    for pos in POSITIONS:
        credit = repl["hitter"] * (c_share if pos == "C" else 1.0)
        for suf in SUFFIXES:
            v = _num(rec.get(f"{pos} WAA {suf}"))
            out[f"{pos} WAR {suf}"] = None if v is None else v + credit
    elig = _eligible(rec)
    for suf, name in (("vR", "Max WAR vR"), ("vL", "Max WAR vL"), ("wtd", "Max WAR wtd"), ("P", "MAX WAR P")):
        vals = [out[f"{pos} WAR {suf}"] for pos in elig if out[f"{pos} WAR {suf}"] is not None]
        out[name] = max(vals) if vals else None
    cand = [pos for pos in elig if out[f"{pos} WAR wtd"] is not None]
    out["Best Pos WAR"] = max(cand, key=lambda pos: out[f"{pos} WAR wtd"]) if cand else None
    return out


def pitcher_war(rec, repl):
    """The WAR columns of one pitcher record (a dict of new keys)."""
    out = {}
    for col in PITCH_COLS:
        sp, rp = _num(rec.get(col)), _num(rec.get(col + " RP"))
        war = col.replace("WAA", "WAR")
        out[war] = None if sp is None else sp + repl["sp"]
        out[war + " RP"] = None if rp is None else rp + repl["rp"]
    wap, wap_rp = _num(rec.get("WAP")), _num(rec.get("WAP RP"))
    out["WARP"] = None if wap is None else wap + repl["sp"]
    out["WARP RP"] = None if wap_rp is None else wap_rp + repl["rp"]
    return out


def add_war(records, kind, repl, basis=None):
    """Add the WAR columns to each record in place (kind "hitters" or "pitchers"); returns
    records. repl None = do nothing."""
    if not repl:
        return records
    c_share = catcher_share(basis) if basis else 500.0 / 600.0
    for rec in records:
        rec.update(hitter_war(rec, repl, c_share) if kind == "hitters" else pitcher_war(rec, repl))
    return records
