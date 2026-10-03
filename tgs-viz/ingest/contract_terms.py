"""
Contract terms from StatsPlus /contract and /contractextension: options, buyouts,
extensions and the calendar year each salary belongs to.

WHY THIS FILE EXISTS. statsplus.attach_contract_injury turns a /contract row into
Price, SalarySchedule, ContractYrs, ContractYr, IsMajorDeal and NoTrade, and drops
the option and buyout columns. SalarySchedule therefore counts a team, player or
vesting option year as if it were guaranteed, and the app's Owed (sum of the
schedule) and control years (length of the schedule) inherit that. This module
keeps what was dropped, as NEW keys on the same records. It changes no existing
key and no existing number. The option-aware pricing it also contains
(option_aware_view) is a PROPOSAL: nothing in the ingest or the app calls it.

Stdlib only. Nothing here asks StatsPlus for anything; the one extra request this
work adds (/contractextension) lives in statsplus.fetch_contract_extensions and
runs inside the refresh pull that already reads /contract.

WHAT THE StatsPlus FIELDS MEAN (checked against the saved SSB replies; see
docs/phase3/contracts.md for the checks and their counts):
  season_year, current_year, years   salary{i} is the pay of contract year i
        (i = 0..years-1); calendar year of year i = season_year + i; the year
        in force is i = current_year.
  last_year_{team,player,vesting}_option       an option on contract year years-1
  next_last_year_{team,player,vesting}_option  an option on contract year years-2
  last_year_option_buyout, next_last_year_option_buyout   a dollar amount that sits
        in the same slot as the flags. A team option's buyout is in its own slot
        in every saved case (62 of 62); the same slot also carries amounts with no
        flag set (49 contracts), which are kept raw and not interpreted.
  /contractextension rows have the same layout as /contract rows; the extension's
        season_year equals the base deal's season_year + years for every one of
        the 140 extensions in the dashboard's saved SSB cache.

NEW RECORD KEYS (all optional; absent means "not known / not applicable"):
  SalaryStartYr     calendar year of SalarySchedule[0] (= season_year + current_year).
                    Present on records that carry SalarySchedule.
  ContractOptions   [{"yr": calendar year, "i": index into SalarySchedule,
                      "type": "team"|"player"|"vesting", "slot": "last"|"next_last",
                      "buyout": dollars in that slot}], only when a flag is set.
  ContractBuyouts   {"last": dollars, "next_last": dollars}, only when either is > 0.
  ContractExt       {"yr": first calendar year, "years": n, "salaries": [...],
                     "options": [...], "buyouts": {...}, "after_base": bool},
                    only for players with a non-empty extension row.
"""
import gzip
import json
import math
import os
import sys

OPTION_TYPES = ("team", "player", "vesting")
# slot name -> how far from the end of the deal the optioned year sits
SLOTS = (("last", "last_year", 1), ("next_last", "next_last_year", 2))
MAX_YEARS = 15                              # salary0..salary14 in the reply
OPTION_COLUMNS = tuple(f"{pre}_{t}_option" for _, pre, _ in SLOTS for t in OPTION_TYPES)
BUYOUT_COLUMNS = tuple(f"{pre}_option_buyout" for _, pre, _ in SLOTS)


def _i(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _has(columns, col):
    return columns is None or col in columns


def _has_option_columns(columns):
    return columns is None or any(c in columns for c in OPTION_COLUMNS)


def parse_options(row, columns=None):
    """The option flags of one /contract (or /contractextension) row.

    Returns (options, buyouts). options = [{"idx", "type", "slot", "buyout"}] with idx the
    contract year index (0-based) of the optioned year; buyouts = {"last", "next_last"}
    raw dollars. When the reply has none of the option columns, options is None
    (unknown), not [] (no options)."""
    years = _i(row.get("years"))
    options = None
    if _has_option_columns(columns):
        options = []
        for slot, pre, back in SLOTS:
            idx = years - back
            if idx < 0 or idx >= MAX_YEARS:
                continue
            for typ in OPTION_TYPES:               # team, then player, then vesting
                if str(row.get(f"{pre}_{typ}_option")) == "1":
                    options.append({"idx": idx, "type": typ, "slot": slot,
                                    "buyout": _i(row.get(f"{pre}_option_buyout"))})
                    break                          # one option per optioned year
    buyouts = {slot: _i(row.get(f"{pre}_option_buyout")) for slot, pre, _ in SLOTS}
    return options, buyouts


def parse_contract(row, columns=None):
    """One /contract or /contractextension row as plain ints and lists. Salaries are
    trimmed to the deal's length (like the dashboard's parser), so the list index is the
    contract year index."""
    years = _i(row.get("years"))
    sal = [_i(row.get(f"salary{i}")) for i in range(MAX_YEARS)]
    options, buyouts = parse_options(row, columns)
    return {"playerId": str(row.get("player_id", "")).strip(),
            "seasonYear": _i(row.get("season_year")), "years": years,
            "currentYear": _i(row.get("current_year")),
            "salaries": sal[:max(years, 1)], "options": options, "buyouts": buyouts}


def build_extension_map(rows):
    """{player_id: parsed extension} for the rows that carry a deal (years > 0 or any pay),
    the same filter the dashboard uses. rows=None (not read) gives None."""
    if rows is None:
        return None
    out = {}
    columns = {str(k).strip() for k in rows[0].keys()} if rows else set()
    for row in rows:
        e = parse_contract(row, columns)
        if e["playerId"] and (e["years"] > 0 or any(s > 0 for s in e["salaries"])):
            out[e["playerId"]] = e
    return out


def _option_entries(parsed, base_year_index, sched_len=None):
    """Options of a parsed deal as record entries. base_year_index is the contract year
    index that maps to SalarySchedule[0] (current_year); entries before it are not in the
    schedule and are left out."""
    out = []
    for o in parsed["options"] or []:
        if o["idx"] < base_year_index:
            continue
        out.append({"yr": parsed["seasonYear"] + o["idx"], "i": o["idx"] - base_year_index,
                    "type": o["type"], "slot": o["slot"], "buyout": o["buyout"]})
    return out


def attach_contract_terms(recs, cmap, ext_map=None, columns=None):
    """Add the option / buyout / start-year / extension keys (module docstring) to engine
    records, by ID. cmap is statsplus.build_contract_injury_maps()[0]; columns is
    statsplus.reply_columns(contracts, ...); ext_map is build_extension_map(...) or None.
    Run it AFTER statsplus.attach_contract_injury: SalaryStartYr follows that function's
    SalarySchedule. Returns the number of records that carry ContractOptions."""
    n_opt = 0
    for r in recs:
        for k in ("SalaryStartYr", "ContractOptions", "ContractBuyouts", "ContractExt"):
            r.pop(k, None)                          # a re-run leaves no stale key
        pid = str(r.get("ID"))
        c = cmap.get(pid)
        if not c:
            continue
        base = parse_contract(c, columns)
        cy = base["currentYear"]
        if "SalarySchedule" in r and base["seasonYear"] > 0:
            r["SalaryStartYr"] = base["seasonYear"] + cy
        opts = _option_entries(base, cy)
        if opts:
            r["ContractOptions"] = opts
            n_opt += 1
        if any(v > 0 for v in base["buyouts"].values()):
            r["ContractBuyouts"] = dict(base["buyouts"])
        e = (ext_map or {}).get(pid)
        if e:
            ext = {"yr": e["seasonYear"], "years": e["years"], "salaries": e["salaries"],
                   "after_base": bool(base["seasonYear"] > 0
                                      and e["seasonYear"] == base["seasonYear"] + base["years"])}
            eo = _option_entries(e, 0)
            if eo:
                ext["options"] = eo
            if any(v > 0 for v in e["buyouts"].values()):
                ext["buyouts"] = dict(e["buyouts"])
            r["ContractExt"] = ext
    return n_opt


# ---- ported from the dashboard's contract_projection.py (arithmetic on StatsPlus fields) ------

def _option_for(parsed, idx):
    """(type, buyout) of the option on contract year idx, or (None, 0)."""
    for o in parsed["options"] or []:
        if o["idx"] == idx:
            return o["type"], o["buyout"]
    return None, 0


def resolve_year(base, ext, calendar_year):
    """What a deal pays in one calendar year: {"salary", "optionType", "buyout", "source"}
    or None when neither the deal nor its extension covers that year.

    base / ext are parse_contract() dicts (ext may be None). The base deal covers
    season_year .. season_year+years-1; the extension covers the years from
    season_year(ext) on, counted from the extension's own first salary. A year inside the
    base wins over an extension that overlaps it. optionType is "team"/"player"/"vesting"
    when that year is an option year, with the buyout of its slot."""
    for deal, source in ((base, "contract"), (ext, "extension")):
        if not deal or deal["years"] <= 0:
            continue
        idx = calendar_year - deal["seasonYear"]
        if 0 <= idx < deal["years"]:
            sal = deal["salaries"][idx] if idx < len(deal["salaries"]) else 0
            typ, buyout = _option_for(deal, idx)
            return {"salary": sal, "optionType": typ, "buyout": buyout, "source": source}
    return None


def detect_contract_year(contract_rows, game_year):
    """The calendar year the league's contracts are currently in force for: the most common
    season_year + current_year among rows with a real season_year (>= 1900). Only game_year
    and game_year + 1 are believed (the index moves to game_year + 1 once the offseason
    deals are settled); anything else, or no rows, returns game_year."""
    counts = {}
    for c in contract_rows or ():
        sy = _i(c.get("season_year"))
        if sy < 1900:
            continue
        y = sy + _i(c.get("current_year"))
        counts[y] = counts.get(y, 0) + 1
    if not counts:
        return game_year
    best = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    return best if best in (game_year, game_year + 1) else game_year


# ---- GATED PROPOSAL: option-aware money and years -----------------------------------------

def option_aware_view(schedule, options):
    """Owed money and years under three readings of the option years. NOT USED by the
    ingest or the app; it is the proposal in docs/phase3/contracts.md, here so the numbers
    in that document can be reproduced and so a decision can be wired in one place.

    schedule  the record's SalarySchedule (remaining years, index 0 = the year in force)
    options   the record's ContractOptions (each has "i" and "type" and "buyout")

    as_is        every year counted (what Owed / control use today)
    guaranteed   only the years before the first option year, plus the buyout when that
                 first option is a team option (the money the club owes if it declines).
                 Years after a declined option are dropped with it.
    club_holds   as guaranteed, but consecutive team options are kept (the club can
                 exercise them), stopping at the first player or vesting option.
    Each reading is {"years": n, "owed": dollars}."""
    sched = [s for s in (schedule or ()) if isinstance(s, (int, float))]
    asis = {"years": len(sched), "owed": sum(sched)}
    # an option on the year in force (i == 0) is already decided: the man is playing it
    future = sorted((o for o in (options or ()) if o.get("i", -1) >= 1 and o["i"] < len(sched)),
                    key=lambda o: o["i"])
    if not future:
        return {"as_is": asis, "guaranteed": dict(asis), "club_holds": dict(asis)}
    first = future[0]
    k = first["i"]
    g_owed = sum(sched[:k]) + (first.get("buyout", 0) if first["type"] == "team" else 0)
    j = k
    by_i = {o["i"]: o for o in future}
    while j in by_i and by_i[j]["type"] == "team":
        j += 1
    return {"as_is": asis,
            "guaranteed": {"years": k, "owed": g_owed},
            "club_holds": {"years": j, "owed": sum(sched[:j])}}


def _read_saved(slug, name, root=None):
    """A saved StatsPlus reply (statsplus._cache_write format) as (data, game_date). The folder
    is statsplus.cache_folder(slug), so STATSPLUS_CACHE_DIR points it at another checkout's
    saved replies."""
    import statsplus as S
    folder = os.path.join(root, slug) if root else S.cache_folder(slug)
    with gzip.open(os.path.join(folder, f"{name}.json.gz"), "rt", encoding="utf-8") as f:
        doc = json.load(f)
    return doc["data"], doc.get("game_date")


def report_saved(slug="ssb", root=None, out=print):
    """Offline numbers for the proposal, from the saved /contract and /players replies.
    No request is made. Prints and returns the summary dict."""
    import statsplus as S
    contracts, gd = _read_saved(slug, "contract", root)
    players, _ = _read_saved(slug, "players", root)
    cmap, pmap = S.build_contract_injury_maps(contracts, players)
    cols = S.reply_columns(contracts, players)
    recs = [{"ID": pid} for pid in cmap]
    S.attach_contract_injury(recs, cmap, pmap, columns=cols)
    attach_contract_terms(recs, cmap, None, columns=cols)
    priced = [r for r in recs if "SalarySchedule" in r]
    tot = {"as_is": [0, 0], "guaranteed": [0, 0], "club_holds": [0, 0]}
    touched = ctrl_g = ctrl_c = 0                 # players whose numbers move under each reading
    kinds = {}
    for r in priced:
        v = option_aware_view(r["SalarySchedule"], r.get("ContractOptions"))
        for k in tot:
            tot[k][0] += v[k]["years"]
            tot[k][1] += v[k]["owed"]
        if r.get("ContractOptions"):
            if v["guaranteed"]["years"] != v["as_is"]["years"] or v["guaranteed"]["owed"] != v["as_is"]["owed"]:
                touched += 1
            for o in r["ContractOptions"]:
                kinds[o["type"]] = kinds.get(o["type"], 0) + 1
        svc = _i(pmap.get(r["ID"], {}).get("mlb_service_days"), None)
        if svc is not None:                         # his controlWindow: max(service years left, deal years)
            to_fa = math.ceil(max(0.0, 6 - svc / 172))
            ctrl_g += max(to_fa, v["guaranteed"]["years"]) != max(to_fa, v["as_is"]["years"])
            ctrl_c += max(to_fa, v["club_holds"]["years"]) != max(to_fa, v["as_is"]["years"])
    summary = {"game_date": gd, "contract_rows": len(contracts), "priced": len(priced),
               "with_option_flag": sum(1 for r in recs if r.get("ContractOptions")),
               "touched_by_future_option": touched, "option_years_by_type": kinds,
               "years_owed_money": {k: {"years": v[0], "owed": v[1]} for k, v in tot.items()},
               "control_changed_guaranteed": ctrl_g, "control_changed_club_holds": ctrl_c,
               "buyout_without_flag": sum(
                   1 for r in recs for slot, amt in (r.get("ContractBuyouts") or {}).items()
                   if amt > 0 and not any(o["slot"] == slot for o in r.get("ContractOptions", ()))),
               }
    out(json.dumps(summary, indent=1))
    return summary


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    report_saved(sys.argv[1] if len(sys.argv) > 1 else "ssb")
