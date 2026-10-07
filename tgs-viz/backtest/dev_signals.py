"""
dev_signals.py - DEV-league odds applied to the young players of a real league.

Reads two pulls of one league from the ratings archive, about one game-year
apart, measures each 16-26 year old's core-skill growth and Pot grade change
over that span, and looks up his odds of becoming an MLB regular in the DEV
grid (public/data/dev_odds.json, built by dev_odds.py). DEV only supplies the
grid. TGS and BLM never mix.

Output: tgs-viz/public/data/<LG>/dev_signals.json (schema in build_payload).

Pull choice (pulls in IN-GAME order, pull_order.py; asof snapshots from
ingest/statsplus_history.py take part as "from" candidates only):
  to      the latest pull of the league that is not an asof snapshot
  from    the pull whose in-game date is closest to one game-year before "to"
          and at least half a game-year earlier; a shorter archive uses its
          earliest pull and scales growth to one game-year (basis.note says so);
          a pull whose pair with "to" holds a rating scale event (ratings_db
          pair_guard flags it) is skipped and the next nearest clean pull is
          used (choose_clean_pulls; basis.note names each skipped pull)
  dates   in-game dates: pulls.game_date, else pull_game_dates_<LG>.json,
          else real_date of an asof pull; real dates when the latest pull has
          none (basis.note says so; asof pulls are then left out, their
          real_date is an in-game date)

Per player (age 16-26 at "to"):
  role        P when pos is SP, RP or CL, else H
  grow        sum over the core skills of (display at to - display at from) / 5,
              display = mean of vR and vL, scaled to one game-year, rounded to 0.5
  pot_delta   Pot grade at to minus Pot grade at from; pot_dir up / flat / down
  earlier card
              read whatever his status was at the earlier pull. An amateur, an
              unsigned international or a free agent has a real card from the
              day OOTP generates him, so his rating changes count from then on
              (user, 2026-10-05). The out-of-an-org rule of 2026-09-25 (no
              growth when he was out of an org at the earlier pull) is gone:
              it rested on a wrong story (hidden draft-class cards). What
              really happened: TGS regenerated its draft classes once, in Jan
              2045, after an age-rule change (player 37730: SP Jason Lindhout,
              Pot 39-40, skills 20, through pull 43 (2045-01-09); CF Lance
              Grueninger, Pot 80, skills 40-45, from pull 45 (2045-01-30)).
  card replaced (failsafe, 2026-10-05)
              when the change from the earlier card to the latest card is
              larger than real development ever produces, the earlier card
              counts as a different card: grow, pot_delta, pot_dir and the
              keep / move flag are null, the odds and peak cells are the
              pot-only ones, note: "card replaced between pulls (regenerated
              or re-scouted): growth unknown", and card_replaced says what
              tripped. Two checks (replaced_cards):
                pair  the change from the earlier pull to the latest pull is
                      over the limit times max(1, span)
                step  one step between two consecutive pulls inside the pair
                      window, under CARD_STEP_DAYS (60) game days apart, is
                      over the one-year limit, even when the pair total looks
                      possible
              The limits per role and age come from the DEV league (true
              ratings, never regenerated); CARD_LIMITS says how. A rating
              scale event (ratings_db.pair_guard) never reaches this check:
              choose_clean_pulls already skips a pair that crosses one.
  core_sum    sum over the core skills of underlying(display), dev_odds scale
  odds        grid cell role / age / Pot bucket / growth bucket; the grid has a
              cell for every age 16-26; null when the cell has fewer than MIN_N
              players; a player without an earlier pull uses the pot_only cell
  vs_typical  core_sum minus the MEDIAN core_sum of the league's own players of
              the same age and Pot bucket (peer group >= 20); the DEV mean
              core_sum stands in only for a thinner peer group
  flag        keep = grow >= 4.5 (H) or >= 3 (P) and pot_dir is not down
              move = pot_dir down and grow <= 2 (H) or <= 1 (P)
  level       Lev from public/data/<LG>/hitters.json and pitchers.json, else the
              archive's lev ('-' reads as null), else null
  peak_p25 / peak_p50 / peak_p75
              eventual peak WAA of the DEV players in the same cell (dev_odds
              "peak", or "peak_pot_only" without growth): what players like
              him became, not what his listed ratings price today; null when
              the cell has fewer than MIN_N players; peak_n and peak_cell say
              which cell. A thin growth cell falls back to the pot-only cell
              (same age and Pot, growth unknown; the note says so); only when
              that is thin too do the peak fields stay null.
  share_now   the player's current WAA the conditional fields below start
              from: hitters "Max WAA wtd", pitchers the larger of "WAA wtd"
              and "WAA wtd RP" from the app files, the same now the DEV
              cache priced its own players on (agecurve_fit.py) and the org
              builder's currentValue. calculateFutureValue picks a pitcher's
              current role by WAR (with the market offsets), which lands on
              the other role for some arms; that current is never above
              this one.
  share_basis which lookalikes the conditional fields read: "now tercile"
              (the sub-cell of his cell holding his current WAA, n >= MIN_N,
              gain-distance rule), "now tercile, edge" (his current sits
              above the top sub-cell's hi or below the bottom sub-cell's lo,
              outside every lookalike's current, so the chance is the lower
              of the gain rule and the nearest sub-cell's own share), "whole
              cell" (the nearest sub-cell is thin, gain rule on the whole
              cell's grid), each with a "pot-only, " prefix when the pot-only
              cell stood in; null when he has no current WAA in the app
              files (the cell shares are used as is).
  listed_peak the app's listed peak: MAX WAA P (hitters) or the larger of WAP
              and WAP RP (pitchers) from public/data/<LG>/hitters.json and
              pitchers.json; null when he is in neither file
  peak_vs_listed
              peak_p50 minus listed_peak, one decimal; null when either is null
  peak_gain_p25 / peak_gain_p50 / peak_gain_p75
              the gain of his lookalikes: eventual peak WAA minus the DEV
              player's now-WAA at that dump; never below 0; null on the same
              thin-cell rule as peak_p50. From the now-tercile sub-cell
              (dev_odds by_now gain_grid at 25 / 50 / 75) when share_basis is
              a tercile, else the whole cell (dev_odds gain_p25 / gain_p50 /
              gain_p75). The app's growth target is current WAA +
              peak_gain_p50, so Proj Potential is conditional on his current
              too: a player near the top of his cell gets the smaller gain of
              the lookalikes who were already there.
  peak_mlb    the chance his eventual peak reaches -1.0 WAA (an MLB-level
              player, a 5th starter or bench bat) FROM WHERE HE IS NOW: the
              share of his lookalikes' gains at or above (-1.0 - share_now),
              read off the gain grid share_basis names (share_at_least). A
              player at or above the bar reads 1.0, and "at the bar" allows
              BAR_TOLERANCE (0.05 WAA, the app's one-decimal display
              rounding): a row the app shows as 0.0 can sit at -0.02 and
              must not read under 100% useful. User, 2026-09-24: "there are
              a ton of guys who are already at 0+ WAA that are getting like
              tagged as less than 100% to reach it which is kind of funny
              and obviously not intended"; and earlier that day "if they
              will ever be anything in the mlb": the org builder orders
              minors playing time by this chance first. When share_basis is
              an edge (his current sits outside every lookalike's), the
              chance is the lower of the gain rule and the nearest sub-cell's
              own share whose eventual peak reached the bar, still 1.0 at the
              bar. Null on the same
              thin-cell rule as peak_p50.
  peak_useful / peak_good
              the same conditional chance at 0 WAA (an average MLB player)
              and +1.5 (a star), bars from dev_odds peak_bars. User,
              2026-09-24: Make it % is playing time, not quality; these say
              whether the lookalikes turned out good enough, and the org
              builder ranks minors playing time on them.
  cell_mlb / cell_useful / cell_good
              the cell's own mlb_share / useful_share / good_share (the share
              of the whole cell whose peak reached each bar, blind to his
              current), kept for reference; the app reads peak_mlb etc.

Core skills, identical to dev_odds: H BABIP GAP POW EYE K; P STU HRR PBABIP CON.

CLI:
  python tgs-viz/backtest/dev_signals.py --league TGS            print, write nothing
  python tgs-viz/backtest/dev_signals.py --league TGS --write    also write the file
  --db PATH       another ratings_history.db
  --odds PATH     another dev_odds.json
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))           # tgs-viz/backtest
VIZ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import dev_odds as DO                                        # noqa: E402
import pull_order as PO                                      # noqa: E402

DB_PATH = PO.DB_PATH                    # tests: RATINGS_ARCHIVE_ROOT
DATA_DIR = os.path.join(VIZ, "public", "data")
ODDS_PATH = os.path.join(DATA_DIR, "dev_odds.json")
LEAGUES = ("TGS", "BLM")

AGE_MIN, AGE_MAX = 16, 26
GRID_AGE_MIN, GRID_AGE_MAX = 16, 26
MIN_N = 15                      # a grid cell below this n gives no odds
YEAR_DAYS = 365.25
TARGET_YEARS = 1.0
MIN_SPAN_YEARS = 0.5
MIN_USABLE_SPAN = 0.1           # below this, growth is not measured
KEEP_GROW = {"H": 4.5, "P": 3.0}
MOVE_GROW = {"H": 2.0, "P": 1.0}
TOP = 10
NO_ORG_LEVELS = {"AMA", "FA", "INT"}      # app Lev values of players outside every org
FOREIGN_LEV = "-"                         # ratings_db.FOREIGN_LEV: archive lev of an NPB / KBO row
# Leagues whose archived pulls can carry a blank lev that fill_blank_levs
# rebuilds from the raw StatsPlus pull (ratings_db.derive_lev).
RAW_LEV_LEAGUES = ("TGS", "BLM")
# A player counts as AT a bar when his current WAA is within this much under
# it: the app shows WAA to one decimal, so a row shown as 0.0 can sit at
# -0.02 and would otherwise read under 100% useful (user, 2026-09-24: "guys
# already at 0+ WAA tagged as less than 100% is obviously not intended").
BAR_TOLERANCE = 0.05

# core skills as archive column stems (stem_vR, stem_vL); same order as dev_odds.CORE
CORE_COLS = {
    "H": [("BABIP", "c_BA"), ("GAP", "c_GAP"), ("POW", "c_POW"), ("EYE", "c_EYE"), ("K", "c_K")],
    "P": [("STU", "c_STU"), ("HRR", "c_HRR"), ("PBABIP", "c_PBABIP"), ("CON", "c_CON")],
}


# ---------------------------------------------------------------- small helpers
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def display(rec, stem):
    """Display value of one skill: the mean of its vR and vL ratings."""
    r, l = num(rec.get(stem + "_vR")), num(rec.get(stem + "_vL"))
    if r is None or l is None:
        return None
    return (r + l) / 2.0


def half_steps(x):
    v = round(x * 2) / 2.0
    return 0.0 if v == 0 else v


def cell_key(role, age, pb, gb):
    return f"{role}/{age}/{pb}/{gb}"


# Reused player IDs (2026-09-25): TGS hands an old ID to a new player, so the
# same ID can be a different person a year apart (checker: 131 H / 113 P TGS
# rows at 16-26; the name differs and the age step is not 0 or 1; BLM and DEV
# show none). His "earlier card" is someone else's, so any growth read from
# it is fake. Such a player counts as not in the earlier pull.
REUSED_ID_NOTE = "ID held by a different player at the earlier pull: growth not measured"


def _norm_name(s):
    return " ".join(str(s or "").casefold().split())


def same_person(rec_now, rec_prev, span):
    """False when the earlier-pull record under this ID is a different
    player: the names differ, or the age step is below 0 or above the span
    rounded up plus 1. True when there is nothing to compare."""
    if not rec_now or not rec_prev:
        return True
    n1, n0 = _norm_name(rec_now.get("name")), _norm_name(rec_prev.get("name"))
    if n1 and n0 and n1 != n0:
        return False
    a1, a0 = DO.to_int(rec_now.get("age")), DO.to_int(rec_prev.get("age"))
    if a1 is not None and a0 is not None:
        hi = int(-(-float(span) // 1)) + 1 if span else 2
        if a1 - a0 < 0 or a1 - a0 > hi:
            return False
    return True


def lev_out_of_org(lev):
    """True when an archive lev puts the player out of an org: AMA, FA, INT,
    '-' (a foreign-league row) or blank. Readers fill a blank lev first with
    fill_blank_levs. Context only (the ML feature prev_in_org, counts): his
    card is read either way."""
    s = "" if lev is None else str(lev).strip()
    return s == "" or s == FOREIGN_LEV or s in NO_ORG_LEVELS


def out_of_org_then(rec):
    """True when an earlier-pull record shows the player out of an org. See
    lev_out_of_org."""
    return lev_out_of_org(rec.get("lev"))


def fill_blank_levs(conn, pull_id, league, ids, levs):
    """Levels of one archived TGS / BLM pull with every blank lev rebuilt from
    the pull's own raw file (ratings_db.raw_pull_levels, the app's rule
    statsplus._lev_for). ids and levs are parallel lists. A level neither
    source knows stays ''. Returns (list of levels, number filled)."""
    out = ["" if v is None or (isinstance(v, float) and v != v) else str(v).strip() for v in levs]
    blank = [i for i, v in enumerate(out) if v == ""]
    if not blank or league not in RAW_LEV_LEAGUES:
        return out, 0
    import ratings_db as RDB
    raw = RDB.raw_pull_levels(conn, pull_id, league)
    if not raw:
        return out, 0
    n = 0
    for i in blank:
        v = raw.get(str(ids[i]))
        if v:
            out[i] = v
            n += 1
    return out, n


# ---------------------------------------------------------------- card replaced
# Card-replaced failsafe (user, 2026-10-05: "a failsafe in case there are
# massive shifts detected falsely like grueninger"). A change from one card to
# a later one that is larger than real development ever produces means the
# earlier card is in effect another card: a regenerated player (TGS
# regenerated its draft classes once, in Jan 2045) or a re-scouted BLM card.
# The earlier card is then unknown for that pair, as if he had no earlier pull.
#
# Limits per role (H / P) and age at the later card, from the DEV league
# (true ratings, never regenerated; 6,745,218 yearly player pairs, dumps
# 2025-2507, measured 2026-10-05):
#   Pot   |Pot change|, only over a pair with the same listed position at both
#         cards (OOTP grades Pot at the listed position: TGS player 20094 read
#         75 at 1B, 42 at SP and 75 at 1B again within three months)
#   up    core growth in display steps (grow: the sum over the core skills of
#         the vR / vL display change / 5)
#   down  core decline in the same steps
# Rule: limit = CARD_MARGIN (1.5) x the widest DEV p99.9 of ages age-1, age and
# age+1 (DEV ages are Jan-1 ages, league ages are ages on the pull date; the
# neighbours cover that offset), Pot rounded up to a whole grade, growth up to
# 0.5. down = the lower of -up and 1.5 x the DEV p0.1 decline: DEV players
# under 22 hardly ever decline, so a DEV-only down limit would trip on a
# temporary dip (TGS player 35107 lost 1.5 steps for ten weeks and got them
# back). DEV pairs over the limits: 230 of 6,745,218 (0.003%). Ages under 16
# read 16, over 40 read 40.
# Examples, DEV p99.9 / p99.99 / max -> limit: H 18 Pot 16 / 23 / 31 -> 27,
# grow 7.0 / 9.0 / 20.0 -> 13.0; H 21 grow 11.0 / 15.1 / 22.5 -> 16.5; P 20 Pot
# 16 / 21 / 28 -> 24, grow 5.0 / 6.5 / 11.0 -> 8.5.
# Grueninger (37730, TGS): pull 43 (2045-01-09) SP, Pot 40, batting 20 ->
# pull 45 (2045-01-30) CF, Pot 80, batting 35-45: core +21 steps in one step
# of 21 game days (+22 over the pair 2044-08-08 to 2045-08-07) against the
# limit of +15 for a hitter of 19 (the Pot is not compared: SP -> CF).
CARD_MARGIN = 1.5
CARD_STEP_DAYS = 60             # the step check reads steps shorter than this (game days)
CARD_LIMIT_AGES = (16, 40)
CARD_LIMITS = {                 # role: {age: (Pot, core up, core down)}
    "H": {
        16: (27, 5.5, -5.5), 17: (27, 10.5, -10.5), 18: (27, 13.0, -13.0), 19: (24, 15.0, -15.0),
        20: (23, 16.5, -16.5), 21: (21, 16.5, -16.5), 22: (21, 16.5, -16.5), 23: (21, 15.0, -15.0),
        24: (23, 14.5, -14.5), 25: (23, 13.0, -13.0), 26: (23, 10.0, -10.0), 27: (21, 7.0, -7.0),
        28: (20, 6.0, -6.0), 29: (21, 6.0, -6.0), 30: (21, 6.0, -7.0), 31: (23, 5.5, -7.0),
        32: (23, 5.5, -7.5), 33: (23, 4.5, -7.5), 34: (29, 4.5, -8.5), 35: (29, 4.5, -8.5),
        36: (29, 4.5, -9.0), 37: (24, 3.0, -9.0), 38: (24, 3.0, -9.0), 39: (24, 3.0, -9.0),
        40: (24, 2.5, -9.0),
    },
    "P": {
        16: (23, 3.0, -3.0), 17: (23, 5.5, -5.5), 18: (24, 7.0, -7.0), 19: (24, 7.5, -7.5),
        20: (24, 8.5, -8.5), 21: (24, 9.0, -9.0), 22: (23, 9.0, -9.0), 23: (21, 9.0, -9.0),
        24: (23, 9.0, -9.0), 25: (23, 8.5, -8.5), 26: (23, 7.5, -7.5), 27: (23, 7.0, -7.0),
        28: (23, 6.0, -6.0), 29: (23, 5.5, -5.5), 30: (21, 4.5, -4.5), 31: (21, 4.5, -4.5),
        32: (17, 4.5, -5.5), 33: (17, 4.5, -5.5), 34: (17, 4.5, -5.5), 35: (20, 4.5, -5.5),
        36: (20, 4.0, -5.5), 37: (22, 4.0, -6.0), 38: (22, 4.0, -6.5), 39: (22, 4.0, -6.5),
        40: (20, 3.5, -6.5),
    },
}
CARD_REPLACED_NOTE = "card replaced between pulls (regenerated or re-scouted): growth unknown"
CARD_COLS = (["player_id", "age", "pos", "c_Pot"]
             + [stem + s for role in ("H", "P") for _n, stem in CORE_COLS[role] for s in ("_vR", "_vL")])


def card_limits(role, age):
    """(Pot, core up, core down) limits of one role at one age (clamped to
    CARD_LIMIT_AGES); None when the age is unknown."""
    a = DO.to_int(age)
    if a is None:
        return None
    a = min(max(a, CARD_LIMIT_AGES[0]), CARD_LIMIT_AGES[1])
    return CARD_LIMITS["P" if role == "P" else "H"][a]


def core_change(prev, rec, role):
    """Core change in display steps from card prev to card rec: the sum over
    the role's core skills of (display at rec - display at prev) / 5. None
    when a core skill is missing on either card."""
    a = [display(prev, stem) for _n, stem in CORE_COLS[role]]
    b = [display(rec, stem) for _n, stem in CORE_COLS[role]]
    if any(v is None for v in a + b):
        return None
    return sum((y - x) / 5.0 for x, y in zip(a, b))


def pot_change(prev, rec):
    """Pot change from card prev to card rec. None when either Pot is missing
    or the listed position differs (OOTP grades Pot at the listed position)."""
    if str(prev.get("pos") or "").strip() != str(rec.get("pos") or "").strip():
        return None
    a, b = num(prev.get("c_Pot")), num(rec.get("c_Pot"))
    return None if a is None or b is None else b - a


def card_change_trips(role, age, d_pot, grow, scale=1.0):
    """Why a card change is larger than real development, as a list of short
    texts; empty = a possible change. d_pot or grow None = not checked. Each
    limit of card_limits(role, age) is multiplied by scale."""
    lim = card_limits(role, age)
    if lim is None:
        return []
    pot, up, down = (x * scale for x in lim)
    out = []
    if d_pot is not None and abs(d_pot) > pot:
        out.append(f"Pot {d_pot:+.0f} (limit {pot:.1f})")
    if grow is not None and grow > up:
        out.append(f"core {grow:+.1f} steps (limit +{up:.1f})")
    if grow is not None and grow < down:
        out.append(f"core {grow:+.1f} steps (limit {down:.1f})")
    return out


def card_rows(conn, pull_id):
    """The CARD_COLS records of one pull, one dict per player."""
    q = "SELECT " + ", ".join(f'"{c}"' for c in CARD_COLS) + " FROM ratings WHERE pull_id=?"
    for row in conn.execute(q, (pull_id,)):
        yield dict(zip(CARD_COLS, row))


def pair_dates(pulls, gdates, choice):
    """{pull_id: date} on the footing of a choose_pulls choice: the in-game
    dates, or the real dates of the pulls that are not asof snapshots when
    the latest pull has no in-game date."""
    if choice["dates"] == "in-game":
        return dict(gdates)
    out = {}
    for pid, rd, _ts in pulls:
        d = parse_date(rd)
        if d is not None and not is_asof(pulls, pid):
            out[pid] = d
    return out


def pull_window(pulls, dates, from_id, to_id):
    """Pull ids from from_id to to_id (both included) in game order, the
    pulls without a date in dates left out."""
    order = [pid for pid, _rd, _ts in pulls]
    i0, i1 = order.index(from_id), order.index(to_id)
    return [p for p in order[i0:i1 + 1] if p in dates]


def card_steps(conn, window, dates, players):
    """The step check of the card-replaced failsafe over a run of pulls.

    window   pull ids in game order; dates {pull_id: date}
    players  {player_id: (role, age)}, role and age at the latest card
    Returns {player_id: [(start date, end date, text)]}: every step between
    two consecutive pulls of the window that hold him, under CARD_STEP_DAYS
    game days apart, whose change trips card_change_trips at scale 1."""
    last = {}
    out = {}
    for p in window:
        d = dates[p]
        for rec in card_rows(conn, p):
            pid = str(rec["player_id"])
            ra = players.get(pid)
            if ra is None:
                continue
            prev = last.get(pid)
            if prev is not None and (d - prev[0]).days < CARD_STEP_DAYS:
                why = card_change_trips(ra[0], ra[1], pot_change(prev[1], rec), core_change(prev[1], rec, ra[0]))
                if why:
                    out.setdefault(pid, []).append((prev[0], d, "; ".join(why)))
            last[pid] = (d, rec)
    return out


def replaced_cards(conn, pulls, gdates, choice, ids=None):
    """The card-replaced failsafe for the pair a choose_clean_pulls choice
    picked. Returns {player_id: text} for every player in both pulls whose
    change trips a check (text = which check and what tripped):
      pair  the change from the earlier pull to the latest pull, each limit
            times max(1, span)
      step  one step between two consecutive pulls inside the pair window,
            under CARD_STEP_DAYS game days apart, at the one-year limits
    Role and age are the ones at the latest pull. ids limits the check to
    these player ids (default: every player of the latest pull). The
    reused-ID test (same_person) is the caller's: a player whose ID changed
    hands is out of the pair before this check matters."""
    if choice.get("from_id") is None:
        return {}
    to_id, from_id = choice["to_id"], choice["from_id"]
    dates = pair_dates(pulls, gdates, choice)
    if to_id not in dates or from_id not in dates:
        return {}
    want = None if ids is None else {str(x) for x in ids}
    to_rows = {str(r["player_id"]): r for r in card_rows(conn, to_id)
               if want is None or str(r["player_id"]) in want}
    from_rows = {str(r["player_id"]): r for r in card_rows(conn, from_id) if str(r["player_id"]) in to_rows}
    players = {pid: (DO.role_of(to_rows[pid].get("pos") or ""), DO.to_int(to_rows[pid].get("age")))
               for pid in from_rows}
    scale = max(1.0, choice.get("span") or 1.0)
    out = {}
    for pid, (role, age) in players.items():
        prev, rec = from_rows[pid], to_rows[pid]
        why = card_change_trips(role, age, pot_change(prev, rec), core_change(prev, rec, role), scale)
        if why:
            out[pid] = f"pair {dates[from_id]} to {dates[to_id]}: " + "; ".join(why)
    steps = card_steps(conn, pull_window(pulls, dates, from_id, to_id), dates, players)
    for pid, ev in steps.items():
        if pid not in out:
            a, b, why = ev[0]
            out[pid] = f"one step {a} to {b} ({(b - a).days} game days): {why}"
    return out


# ---------------------------------------------------------------- inputs
def load_odds(path):
    try:
        with open(path, encoding="utf-8") as fh:
            odds = json.load(fh)
    except (OSError, ValueError) as e:
        raise SystemExit(f"cannot read the DEV grid {path}: {e}; run dev_odds.py --write first")
    for k in ("grid", "typical", "ages", "pot_buckets", "growth_buckets"):
        if k not in odds:
            raise SystemExit(f"{path} has no '{k}' key; rebuild it with dev_odds.py --write")
    for k in ("peak", "peak_pot_only"):
        if k not in odds:
            print(f"  note: {path} has no '{k}' table; peak fields stay null "
                  "(rebuild it with dev_odds.py --write)")
            odds[k] = {}
    return odds


class PullList(list):
    """[(pull_id, real_date, real_ts)] in in-game order, with two lookups:
    source {pull_id: source} and game {pull_id: 'YYYY-MM-DD'} (known dates)."""
    source = {}
    game = {}


def league_pulls(conn, league):
    """PullList [(pull_id, real_date, real_ts)] oldest first by IN-GAME date
    (pull_order.ordered), asof snapshots included."""
    rows, game = PO.ordered(conn, league)
    out = PullList((int(r[0]), r[1], r[2]) for r in rows)
    out.source = {int(r[0]): r[3] for r in rows}
    out.game = {int(k): v for k, v in game.items()}
    return out


def is_asof(pulls, pid):
    return getattr(pulls, "source", {}).get(pid) == PO.ASOF


def latest_id(pulls):
    """Id of the latest pull that is not an asof snapshot (pulls in game order)."""
    for pid, _rd, _ts in reversed(pulls):
        if not is_asof(pulls, pid):
            return pid
    return pulls[-1][0]


def game_dates(league, pulls):
    """{pull_id: date}. A PullList brings its own dates (pulls.game_date, the
    JSON fit, an asof pull's real_date). A plain list reads
    pull_game_dates_<LG>.json; only entries whose stored real date still
    matches the pull (the ratings_db rule)."""
    if getattr(pulls, "game", None):
        return {pid: parse_date(pulls.game[pid]) for pid, _rd, _ts in pulls
                if pid in pulls.game and parse_date(pulls.game[pid])}
    stored = PO.json_game_dates(league, pulls)
    return {pid: parse_date(d) for pid, d in stored.items() if parse_date(d)}


def choose_pulls(pulls, gdates):
    """Pick "to" and "from". Returns a dict with the ids, dates, span and notes."""
    to_id = latest_id(pulls)
    notes = []
    if to_id in gdates:
        kind = "in-game"
        dated = [(pid, gdates[pid]) for pid, _rd, _ts in pulls if pid in gdates]
        undated = len(pulls) - len(dated)
        if undated:
            notes.append(f"{undated} pull(s) without an in-game date skipped")
    else:
        kind = "real"
        # an asof pull's real_date is an in-game date: never mix it with real dates
        dated = [(pid, parse_date(rd)) for pid, rd, _ts in pulls if not is_asof(pulls, pid)]
        notes.append("no in-game date stored for the latest pull: real dates used, "
                     "so the span is in real years, not game-years")
    by_id = dict(dated)
    to_date = by_id[to_id]
    target = to_date - datetime.timedelta(days=YEAR_DAYS * TARGET_YEARS)
    latest_ok = to_date - datetime.timedelta(days=YEAR_DAYS * MIN_SPAN_YEARS)
    cands = [(pid, d) for pid, d in dated if pid != to_id and d <= latest_ok]
    if cands:
        from_id, from_date = min(cands, key=lambda x: (abs((x[1] - target).days), x[0]))
    else:
        earlier = [(pid, d) for pid, d in dated if pid != to_id and d < to_date]
        if earlier:
            from_id, from_date = min(earlier, key=lambda x: (x[1], x[0]))
            notes.append(f"archive shorter than {MIN_SPAN_YEARS:g} game-years: earliest pull used")
        else:
            from_id, from_date = None, None
            notes.append("no earlier dated pull: growth not measured")
    span = None
    if from_date is not None:
        span = (to_date - from_date).days / YEAR_DAYS
        if span < MIN_USABLE_SPAN:
            notes.append(f"span under {MIN_USABLE_SPAN:g} game-years: growth not measured")
            from_id, from_date, span = None, None, None
    real_of = {pid: rd for pid, rd, _ts in pulls}
    return {"to_id": to_id, "to_date": to_date, "to_real": real_of[to_id],
            "from_id": from_id, "from_date": from_date,
            "from_real": real_of.get(from_id) if from_id is not None else None,
            "span": span, "dates": kind, "notes": notes}


def pair_reading(conn, league, from_id, to_map, floor):
    """ratings_db.pair_guard reading of the pair (from pull, latest pull).

    The shared players are the ones ratings_db.age_curves uses to date a pair:
    in both pulls, with an org at the earlier pull, age step 0 or 1. Returns
    [reason] for every side (pitchers, hitters) the guard flags; empty = clean."""
    import ratings_db as RDB
    old = RDB.load_pull_map(conn, from_id)
    shared = []
    for pid, nrec in to_map.items():
        orec = old.get(pid)
        if not orec or orec.get("org") in (None, "", "0", 0):
            continue
        try:
            a1 = int(float(orec["age"]))
            d = int(float(nrec["age"])) - a1
        except (TypeError, ValueError, KeyError):
            continue
        if d in (0, 1):
            shared.append((pid, orec, nrec, a1, d))
    g = RDB.pair_guard(shared, floor)
    return [f"{RDB.SIDE_LABEL[s]}: {g[s]['reason']}" for s in RDB.SIDES if g[s]["reason"]]


def choose_clean_pulls(conn, league, pulls, gdates):
    """choose_pulls with the scale-event rule: the earlier pull is the one
    nearest one game-year back whose pair with the latest pull is NOT flagged
    by ratings_db.pair_guard (a league-wide re-scout or rating scale event
    between the two pulls moves ratings that are not development).

    Order tried: pulls at least MIN_SPAN_YEARS back, nearest to one game-year
    back first (the choose_pulls order), then shorter spans (down to
    MIN_USABLE_SPAN), earliest first. The first clean pair wins; growth is
    still scaled to one game-year by the span. No clean pair = no growth.
    BLM, 2026-09-24: the event between pull 4 (2057-10-13) and pull 5
    (2057-12-31) made the old pick (pull 4) read the event as growth."""
    import ratings_db as RDB
    base = choose_pulls(pulls, gdates)
    if base["from_id"] is None:
        return base
    if RDB._dump_source(conn, league) is not None:
        return base                       # true-ratings dump league: the guard is informational
    floor = RDB.rated_floor(RDB._scale_of(conn, league))
    to_id, to_date = base["to_id"], base["to_date"]
    if base["dates"] == "in-game":
        dated = [(pid, gdates[pid]) for pid, _rd, _ts in pulls if pid in gdates and pid != to_id]
    else:
        dated = [(pid, parse_date(rd)) for pid, rd, _ts in pulls
                 if pid != to_id and not is_asof(pulls, pid)]
    target = to_date - datetime.timedelta(days=YEAR_DAYS * TARGET_YEARS)
    latest_ok = to_date - datetime.timedelta(days=YEAR_DAYS * MIN_SPAN_YEARS)
    min_ok = to_date - datetime.timedelta(days=YEAR_DAYS * MIN_USABLE_SPAN)
    long_ = sorted([(p, d) for p, d in dated if d <= latest_ok],
                   key=lambda x: (abs((x[1] - target).days), x[0]))
    short = sorted([(p, d) for p, d in dated if latest_ok < d <= min_ok], key=lambda x: (x[1], x[0]))
    to_map = RDB.load_pull_map(conn, to_id)
    notes = list(base["notes"])
    real_of = {pid: rd for pid, rd, _ts in pulls}
    for pid, d in long_ + short:
        reasons = pair_reading(conn, league, pid, to_map, floor)
        if reasons:
            notes.append(f"pull {pid} ({d}) skipped, rating scale event between it and the latest pull: "
                         + "; ".join(reasons))
            continue
        span = (to_date - d).days / YEAR_DAYS
        if pid != base["from_id"]:
            notes.append(f"earlier pull moved from {base['from_id']} to {pid} by the scale-event guard")
        if span < MIN_SPAN_YEARS:
            notes.append(f"no clean pull {MIN_SPAN_YEARS:g}+ game-years back: shorter span used")
        return dict(base, from_id=pid, from_date=d, from_real=real_of.get(pid), span=span, notes=notes)
    notes.append("every earlier pull crosses a rating scale event: growth not measured")
    return dict(base, from_id=None, from_date=None, from_real=None, span=None, notes=notes)


def load_rows(conn, pull_id, league=None):
    """{player_id: record} of one pull with the columns this script needs.
    With a TGS / BLM league, a blank lev is rebuilt from the pull's raw file
    (fill_blank_levs)."""
    cols = ["player_id", "name", "age", "pos", "org", "lev", "c_Pot", "c_Ovr"]
    for role in ("H", "P"):
        for _name, stem in CORE_COLS[role]:
            cols += [stem + "_vR", stem + "_vL"]
    q = "SELECT " + ", ".join(f'"{c}"' for c in cols) + " FROM ratings WHERE pull_id=?"
    out = {}
    for row in conn.execute(q, (pull_id,)):
        rec = dict(zip(cols, row))
        out[str(rec["player_id"])] = rec
    if league is not None and out:
        pids = list(out)
        levs, _n = fill_blank_levs(conn, pull_id, league, pids, [out[p]["lev"] for p in pids])
        for p, v in zip(pids, levs):
            out[p]["lev"] = v or None
    return out


def app_rows(league):
    """Levels, listed peaks and current WAA from the app's hitters.json and
    pitchers.json.

    Returns (levels, peaks, currents): levels = {player_id: Lev}; peaks =
    {"H": {player_id: MAX WAA P}, "P": {player_id: max of WAP and WAP RP}};
    currents = {"H": {player_id: Max WAA wtd}, "P": {player_id: max of WAA
    wtd and WAA wtd RP}}, the same now the DEV cache priced its players on
    (agecurve_fit.py) and the org builder's currentValue. A missing or
    non-numeric value is left out."""
    levels = {}
    peaks = {"H": {}, "P": {}}
    currents = {"H": {}, "P": {}}
    for fname, role, keys, now_keys in (("hitters.json", "H", ("MAX WAA P",), ("Max WAA wtd",)),
                                        ("pitchers.json", "P", ("WAP", "WAP RP"), ("WAA wtd", "WAA wtd RP"))):
        path = os.path.join(DATA_DIR, league, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rows, list):
            continue
        for r in rows:
            if not isinstance(r, dict) or r.get("ID") is None:
                continue
            pid = str(r["ID"])
            if r.get("Lev"):
                levels[pid] = str(r["Lev"])
            vals = [num(r.get(k)) for k in keys]
            vals = [v for v in vals if v is not None]
            if vals:
                peaks[role][pid] = max(vals)
            nows = [num(r.get(k)) for k in now_keys]
            nows = [v for v in nows if v is not None]
            if nows:
                currents[role][pid] = max(nows)
    return levels, peaks, currents


# ---------------------------------------------------------------- measure
def lookup(tree, *keys):
    for k in keys:
        if not isinstance(tree, dict) or k not in tree:
            return None
        tree = tree[k]
    return tree


def thin(pc):
    """True for a peak cell too small to use (n < MIN_N or no p50)."""
    return (pc.get("n") or 0) < MIN_N or pc.get("p50") is None


def pick_sub(by_now, now):
    """(sub, edge): the by_now sub-cell whose now range holds now, else the
    nearest one (the top or bottom sub-cell outside the range). edge is True
    when now sits above every sub-cell's hi or below every sub-cell's lo, so
    no lookalike was ever where he is; a now in the small gap between two
    sub-cells is not an edge. (None, False) without sub-cells."""
    best = None
    lo_all = hi_all = None
    for s in by_now or []:
        if not isinstance(s, dict) or s.get("lo") is None or s.get("hi") is None:
            continue
        lo_all = s["lo"] if lo_all is None or s["lo"] < lo_all else lo_all
        hi_all = s["hi"] if hi_all is None or s["hi"] > hi_all else hi_all
        dist = 0.0 if s["lo"] <= now <= s["hi"] else min(abs(now - s["lo"]), abs(now - s["hi"]))
        if best is None or dist < best[0]:
            best = (dist, s)
    if best is None:
        return None, False
    return best[1], (now < lo_all or now > hi_all)


def at_bar(now, bar):
    """True when now counts as at the bar: at or above it, or under it by at
    most BAR_TOLERANCE (the display rounding; user, 2026-09-24: a player
    already at 0+ WAA must not read under 100%)."""
    return now >= bar - BAR_TOLERANCE


def share_at_least(grid, d, pcts):
    """Share of a gain grid at or above the distance d (the chance to gain d
    or more). grid[i] is the gain at quantile level pcts[i] / 100, so the
    share of gains at or above grid[i] is 1 - that level.

    Rule (2026-09-24, user: a player already at 0+ WAA must not read under
    100% to reach 0):
      d <= 0                    1.0, he is already there
      0 < d <= grid[0]          linear from 1.0 at d = 0 to 1 - pcts[0]/100
                                (0.95) at the 5% quantile
      grid[0] < d <= grid[-1]   linear between the two grid points around d;
                                a run of equal grid values (ties, usually at
                                0) counts at its highest level, so a cell
                                where 20% gained nothing reads 0.8 just
                                above 0
      d > grid[-1]              linear from pcts[-1]/100 (0.05) at the 95%
                                quantile down to 0 at twice the 95% quantile;
                                0 when the 95% quantile is 0
    """
    if d <= 0:
        return 1.0
    lvl = [p / 100.0 for p in pcts]
    q05, q95 = grid[0], grid[-1]
    if d <= q05:
        return 1.0 - lvl[0] * d / q05
    if d > q95:
        if q95 <= 0:
            return 0.0
        return max(0.0, (1.0 - lvl[-1]) * (1.0 - (d - q95) / q95))
    for i in range(len(grid) - 1):
        lo, hi = grid[i], grid[i + 1]
        if lo < d <= hi:
            f = lvl[i] + (lvl[i + 1] - lvl[i]) * (d - lo) / (hi - lo)
            return 1.0 - f
    return 0.0


def measure_player(pid, rec, prev, span, odds, levels, peaks, currents, pcts, bars, replaced=None):
    """One player's entry, or None when he is outside 16-26. replaced = the
    card-replaced failsafe's text when it tripped for his pair
    (replaced_cards): nothing is read from that earlier card."""
    age = DO.to_int(rec.get("age"))
    if age is None or age < AGE_MIN or age > AGE_MAX:
        return None
    pos = rec.get("pos") or ""
    role = DO.role_of(pos)
    pot = DO.to_int(rec.get("c_Pot"))
    notes = []

    cur = [display(rec, stem) for _n, stem in CORE_COLS[role]]
    core_sum = None
    if all(v is not None for v in cur):
        core_sum = sum(DO.underlying(v) for v in cur)
    else:
        notes.append("core skill missing at the latest pull")

    grow = None
    pot_delta = None
    pot_dir = None
    if prev is None:
        notes.append("not in the earlier pull" if span is not None else "no earlier pull")
    elif replaced:
        # card-replaced failsafe: the change from the earlier card is larger
        # than real development, so growth, the Pot change and the growth
        # cell stay unknown (pot-only cells)
        notes.append(CARD_REPLACED_NOTE)
    else:
        pcur = [display(prev, stem) for _n, stem in CORE_COLS[role]]
        if core_sum is not None and all(v is not None for v in pcur):
            raw = sum((c - p) / 5.0 for c, p in zip(cur, pcur))
            grow = half_steps(raw / span)
        else:
            notes.append("core skill missing at the earlier pull")
        ppot = DO.to_int(prev.get("c_Pot"))
        if pot is not None and ppot is not None:
            pot_delta = pot - ppot
            pot_dir = "up" if pot_delta > 0 else "down" if pot_delta < 0 else "flat"
        ppos = prev.get("pos") or ""
        if DO.role_of(ppos) != role:
            notes.append(f"role changed since the earlier pull (was {ppos})")

    age_g = min(max(age, GRID_AGE_MIN), GRID_AGE_MAX)
    if age_g != age:
        notes.append(f"age {age}: age-{age_g} grid cell")

    odds_p = odds_n = cell = vs_typical = None
    if pot is None:
        notes.append("no Pot grade: no odds")
    else:
        pb = DO.pot_bucket(pot)
        if grow is not None:
            gb = DO.growth_bucket(role, grow)
            c = lookup(odds, "grid", role, str(age_g), pb, gb)
            cell = cell_key(role, age_g, pb, gb)
        else:
            c = lookup(odds, "pot_only", role, str(age_g), pb)
            cell = cell_key(role, age_g, pb, "any") if c is not None else None
            if c is not None:
                notes.append("cell numbers by age and Pot only")
        if c is None:
            notes.append("no grid cell")
        elif (c.get("n") or 0) < MIN_N or c.get("p") is None:
            notes.append(f"thin cell (n={c.get('n', 0)}): no odds")
        else:
            odds_p, odds_n = c["p"], c["n"]
        t = lookup(odds, "typical", role, str(age_g), pb)
        if core_sum is not None and t and t.get("core_sum_mean") is not None:
            vs_typical = int(round(core_sum - t["core_sum_mean"]))

    flag = None
    if grow is not None:
        if grow >= KEEP_GROW[role] and pot_dir != "down":
            flag = "keep"
        elif pot_dir == "down" and grow <= MOVE_GROW[role]:
            flag = "move"

    lev = str(rec.get("lev") or "").strip()
    level = levels.get(pid) or (lev if lev and lev != FOREIGN_LEV else None)
    if level is None:
        notes.append("level unknown (not in the app files)")

    # eventual peak of the DEV players in the same cell, against the listed
    # peak, the gain from now-WAA to that peak, and the chance to reach each
    # bar FROM WHERE HE IS NOW (user, 2026-09-24: "there are a ton of guys who
    # are already at 0+ WAA that are getting like tagged as less than 100% to
    # reach it which is kind of funny and obviously not intended")
    peak_p25 = peak_p50 = peak_p75 = peak_n = peak_cell = None
    gain_p25 = gain_p50 = gain_p75 = None
    cell_mlb = cell_useful = cell_good = None    # the cell's own peak shares, blind to his current
    peak_mlb = peak_useful = peak_good = None    # the conditional chances the app reads
    share_basis = None
    # his current WAA: the same now the DEV cache priced its players on;
    # rounded to 2 decimals up front so share_now and the shares agree (a
    # player 0.004 under a bar reads as at it, not as needing a gain)
    now = currents.get(role, {}).get(pid)
    if now is None:
        now = currents.get("P" if role == "H" else "H", {}).get(pid)
    if now is not None:
        now = round(now, 2)
    if pot is not None:
        pb = DO.pot_bucket(pot)
        pot_only = False
        if grow is not None:
            gb = DO.growth_bucket(role, grow)
            pc = lookup(odds, "peak", role, str(age_g), pb, gb)
            peak_cell = cell_key(role, age_g, pb, gb)
            if pc is not None and thin(pc):
                # thin growth cell: the pot-only group (same age and Pot,
                # growth unknown) stands in, not the app's stand-in
                alt = lookup(odds, "peak_pot_only", role, str(age_g), pb)
                if alt is not None and not thin(alt):
                    notes.append(f"thin growth cell (n={pc.get('n', 0)}): shares from the pot-only group")
                    pc, pot_only = alt, True
                    peak_cell = cell_key(role, age_g, pb, "any")
        else:
            pc = lookup(odds, "peak_pot_only", role, str(age_g), pb)
            pot_only = pc is not None
            peak_cell = cell_key(role, age_g, pb, "any") if pc is not None else None
        if pc is None:
            notes.append("no peak cell")
        elif thin(pc):
            notes.append(f"thin peak cell (n={pc.get('n', 0)}): no Exp peak")
        else:
            peak_p25, peak_p50, peak_p75, peak_n = pc["p25"], pc["p50"], pc["p75"], pc["n"]
            gain_p25, gain_p50, gain_p75 = pc.get("gain_p25"), pc.get("gain_p50"), pc.get("gain_p75")
            if gain_p50 is None:
                notes.append("peak cell has no gain (rebuild dev_odds.json)")
            # the cell's own shares whose peak reached -1 / 0 / +1.5 WAA, for reference
            cell_mlb, cell_useful, cell_good = pc.get("mlb_share"), pc.get("useful_share"), pc.get("good_share")
            if cell_mlb is None or cell_useful is None:
                notes.append("peak cell has no mlb/useful/good share (rebuild dev_odds.json)")
            # the gain grid of his lookalikes at a similar current: the now
            # tercile of the cell holding his now, else the whole cell
            grid = pc.get("gain_grid")
            basis = "whole cell"
            edge_shares = None       # the sub-cell's own peak-level shares, edge players only
            sub, edge = pick_sub(pc.get("by_now"), now) if now is not None else (None, False)
            if sub is not None and (sub.get("n") or 0) >= MIN_N and sub.get("gain_grid"):
                grid = sub["gain_grid"]
                basis = "now tercile"
                # the gain conditional on his current, so Proj Potential
                # (current + peak_gain_p50) is conditional on it too
                gain_p25, gain_p50, gain_p75 = (grid[pcts.index(25)], grid[pcts.index(50)],
                                                grid[pcts.index(75)])
                if edge:
                    # his current sits above the top sub-cell's hi or below
                    # the bottom sub-cell's lo: no lookalike was ever where
                    # he is, so the gain rule would lend him gains measured
                    # on players who were not (a P 20 at -1.44 read 98% MLB
                    # in a cell where 7% ever reached the bar). The chance is
                    # the LOWER of the gain rule and the nearest sub-cell's
                    # own outcome share: above the top group the gain rule
                    # over-credits, below the bottom group the sub-cell's
                    # share over-credits (a hitter 0.7 WAA under the worst
                    # lookalike read 96% from it). The lower one is the
                    # honest bound either way.
                    if all(sub.get(name) is not None for name in bars):
                        basis = "now tercile, edge"
                        edge_shares = {name: sub[name] for name in bars}
                    else:
                        notes.append("sub-cell has no peak-level shares (rebuild dev_odds.json): gain rule")
            if pot_only:
                basis = "pot-only, " + basis
            if grid is None:
                notes.append("peak cell has no gain grid (rebuild dev_odds.json): cell shares")
                peak_mlb, peak_useful, peak_good = cell_mlb, cell_useful, cell_good
            elif now is None:
                notes.append("no current WAA in the app files: cell shares")
                peak_mlb, peak_useful, peak_good = cell_mlb, cell_useful, cell_good
            else:
                # the chance his peak reaches the bar from where he is now:
                # 1.0 when he is already at the bar (within BAR_TOLERANCE,
                # the display rounding); an edge player reads his sub-cell's
                # own peak-level share; else the share of the lookalikes'
                # gains at or above (bar - now)
                share_basis = basis
                chance = {}
                for name, bar in bars.items():
                    if at_bar(now, bar):
                        chance[name] = 1.0
                    elif edge_shares is not None:
                        chance[name] = min(edge_shares[name],
                                           round(share_at_least(grid, bar - now, pcts), 3))
                    else:
                        chance[name] = round(share_at_least(grid, bar - now, pcts), 3)
                peak_mlb, peak_useful, peak_good = chance["mlb"], chance["useful"], chance["good"]
    listed = peaks.get(role, {}).get(pid)
    if listed is None:
        listed = peaks.get("P" if role == "H" else "H", {}).get(pid)
    listed_peak = round(listed, 2) if listed is not None else None
    peak_vs_listed = (round(peak_p50 - listed_peak, 1)
                      if peak_p50 is not None and listed_peak is not None else None)

    return {"name": rec.get("name"), "age": age, "pot": pot, "role": role, "pos": pos,
            "grow": grow, "pot_dir": pot_dir, "pot_delta": pot_delta,
            "core_sum": round(core_sum, 1) if core_sum is not None else None,
            "odds": odds_p, "odds_n": odds_n, "odds_cell": cell,
            "vs_typical": vs_typical, "level": level, "flag": flag,
            "peak_p25": peak_p25, "peak_p50": peak_p50, "peak_p75": peak_p75,
            "peak_n": peak_n, "peak_cell": peak_cell,
            "peak_gain_p25": gain_p25, "peak_gain_p50": gain_p50, "peak_gain_p75": gain_p75,
            "peak_mlb": peak_mlb, "peak_useful": peak_useful, "peak_good": peak_good,
            "cell_mlb": cell_mlb, "cell_useful": cell_useful, "cell_good": cell_good,
            "share_basis": share_basis,
            "share_now": round(now, 2) if now is not None else None,
            "listed_peak": listed_peak, "peak_vs_listed": peak_vs_listed,
            "card_replaced": replaced or None,
            "note": "; ".join(notes)}


def measure(conn, league, odds, log=print):
    pulls = league_pulls(conn, league)
    if not pulls:
        raise SystemExit(f"no pulls for league {league} in the archive")
    gdates = game_dates(league, pulls)
    choice = choose_clean_pulls(conn, league, pulls, gdates)
    to_rows = load_rows(conn, choice["to_id"], league)
    from_rows = load_rows(conn, choice["from_id"], league) if choice["from_id"] is not None else {}
    # card-replaced failsafe over the pair and every step inside its window
    replaced = replaced_cards(conn, pulls, gdates, choice)
    levels, peaks, currents = app_rows(league)
    pcts = list(odds.get("gain_grid_pcts") or DO.GAIN_GRID_PCTS)
    bars = odds.get("peak_bars") or DO.PEAK_BARS
    players = {}
    n_out = 0
    for pid in sorted(to_rows, key=lambda s: (len(s), s)):
        prev = from_rows.get(pid)
        reused = prev is not None and not same_person(to_rows[pid], prev, choice["span"])
        if reused:
            prev = None                      # someone else's card: not in the earlier pull
        why = replaced.get(pid) if prev is not None else None
        e = measure_player(pid, to_rows[pid], prev, choice["span"], odds, levels, peaks,
                           currents, pcts, bars, replaced=why)
        if e is not None:
            if reused:
                e["note"] = f"{e['note']}; {REUSED_ID_NOTE}" if e.get("note") else REUSED_ID_NOTE
            n_out += prev is not None and out_of_org_then(prev)
            players[pid] = e
    log(f"dev_signals {league}: to pull {choice['to_id']} ({choice['to_date']}, real {choice['to_real']}), "
        + (f"from pull {choice['from_id']} ({choice['from_date']}, real {choice['from_real']}), "
           f"span {choice['span']:.3f} {'game' if choice['dates'] == 'in-game' else 'real'}-years"
           if choice["from_id"] is not None else "no earlier pull"))
    for n in choice["notes"]:
        log(f"  note: {n}")
    log(f"  earlier card read for {n_out} players {AGE_MIN}-{AGE_MAX} who were out of an org at the earlier "
        f"pull; card replaced (failsafe) for "
        f"{sum(1 for e in players.values() if e['card_replaced'])} players {AGE_MIN}-{AGE_MAX} "
        f"({len(replaced)} of every age, reused IDs included)")
    # vs_typical against SAME-LEAGUE peers of the same age and Pot bucket. The
    # DEV typical carries a league offset (a whole fictional league's rating
    # distribution), which put every TGS player hundreds of points "ahead".
    # The player's own league says where he sits among his peers; the DEV
    # value stays as the fallback for a thin peer group (< 20).
    import statistics
    groups = {}
    for e in players.values():
        if e.get("core_sum") is None or e.get("pot") is None:
            continue
        k = (e["role"], min(max(e["age"], GRID_AGE_MIN), GRID_AGE_MAX), DO.pot_bucket(e["pot"]))
        groups.setdefault(k, []).append(e["core_sum"])
    medians = {k: statistics.median(v) for k, v in groups.items() if len(v) >= 20}
    swapped = 0
    for e in players.values():
        if e.get("core_sum") is None or e.get("pot") is None:
            continue
        k = (e["role"], min(max(e["age"], GRID_AGE_MIN), GRID_AGE_MAX), DO.pot_bucket(e["pot"]))
        if k in medians:
            e["vs_typical"] = int(round(e["core_sum"] - medians[k]))
            e["vs_typical_basis"] = f"{league} peers (n {len(groups[k])})"
            swapped += 1
        elif e.get("vs_typical") is not None:
            e["vs_typical_basis"] = "DEV typical (thin peer group)"
    log(f"  vs_typical: {swapped} players measured against {league} peers of the same age and Pot bucket")
    return choice, players


# ---------------------------------------------------------------- output
def counts_of(players, bars=None):
    bars = bars or DO.PEAK_BARS
    c = {"players": len(players), "H": 0, "P": 0, "with_growth": 0, "with_odds": 0,
         "with_peak": 0, "with_gain": 0, "with_mlb": 0, "with_useful": 0, "with_listed_peak": 0,
         "with_now": 0, "conditional": 0, "pot_only_fallback": 0, "at_useful_bar": 0,
         "at_bar_tolerance": 0, "edge": 0,
         "share_basis": {"now tercile": 0, "now tercile, edge": 0, "whole cell": 0,
                         "pot-only, now tercile": 0, "pot-only, now tercile, edge": 0,
                         "pot-only, whole cell": 0, "none": 0},
         "keep": 0, "move": 0, "none": 0, "keep_H": 0, "keep_P": 0, "move_H": 0, "move_P": 0,
         "card_replaced": 0, "reused_id": 0}
    for e in players.values():
        c[e["role"]] += 1
        c["with_growth"] += e["grow"] is not None
        c["card_replaced"] += bool(e.get("card_replaced"))
        c["reused_id"] += REUSED_ID_NOTE in (e["note"] or "")
        c["with_odds"] += e["odds"] is not None
        c["with_peak"] += e["peak_p50"] is not None
        c["with_gain"] += e["peak_gain_p50"] is not None
        c["with_mlb"] += e["peak_mlb"] is not None
        c["with_useful"] += e["peak_useful"] is not None
        c["with_listed_peak"] += e["listed_peak"] is not None
        c["with_now"] += e["share_now"] is not None
        c["conditional"] += e["share_basis"] is not None
        c["pot_only_fallback"] += "thin growth cell" in (e["note"] or "")
        # players already at the useful bar (0 WAA): their peak_useful must be 1.0
        c["at_useful_bar"] += e["share_now"] is not None and e["share_now"] >= 0 and e["peak_useful"] is not None
        # players the tolerance lifted to 1.0 at some bar: under it, but by
        # no more than BAR_TOLERANCE (shown at the bar by the app)
        c["at_bar_tolerance"] += (e["share_basis"] is not None and e["share_now"] is not None
                                  and any(bar - BAR_TOLERANCE <= e["share_now"] < bar for bar in bars.values()))
        # players whose current sits outside every lookalike's (edge rule)
        c["edge"] += (e["share_basis"] or "").endswith("edge")
        c["share_basis"][e["share_basis"] or "none"] += 1
        f = e["flag"] or "none"
        c[f] += 1
        if f != "none":
            c[f + "_" + e["role"]] += 1
    return c


def build_payload(league, choice, players, odds):
    notes = ["growth scaled to one game-year"] + choice["notes"]
    bars = odds.get("peak_bars") or DO.PEAK_BARS
    return {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "league": league,
        "basis": {
            "to_pull": choice["to_date"].isoformat(),
            "from_pull": choice["from_date"].isoformat() if choice["from_date"] else None,
            "span_years": round(choice["span"], 3) if choice["span"] is not None else None,
            "note": "; ".join(notes),
            "dates": choice["dates"],
            "to_pull_id": choice["to_id"],
            "from_pull_id": choice["from_id"],
            "to_real_date": choice["to_real"],
            "from_real_date": choice["from_real"],
            "odds_generated": odds.get("generated"),
            "min_cell_n": MIN_N,
            "bar_tolerance": BAR_TOLERANCE,
            "card_step_days": CARD_STEP_DAYS,
            "card_margin": CARD_MARGIN,
        },
        "definitions": {
            "players": f"every player aged {AGE_MIN}-{AGE_MAX} at the latest pull; age = the pull's Age "
                       f"field (age on the pull's in-game date; the DEV grid uses Jan-1 ages)",
            "role": "P when pos is SP, RP or CL, else H",
            "grow": "sum over the core skills (H BABIP GAP POW EYE K; P STU HRR PBABIP CON) of "
                    "(display at to - display at from) / 5, display = mean of vR and vL, divided by "
                    "the span in game-years, rounded to 0.5; read whatever his status at the earlier "
                    "pull (an amateur or free agent has a real card from the day OOTP generates him); "
                    "null without an earlier pull, and null when the card-replaced failsafe trips "
                    "(note 'card replaced between pulls (regenerated or re-scouted): growth unknown')",
            "pot_delta": "OOTP Pot grade at to minus at from, over the span, not scaled; "
                         "pot_dir = up / flat / down; null on the same card-replaced rule as grow",
            "card_replaced": f"the card-replaced failsafe: what tripped, else null. The earlier card counts "
                             f"as another card when the change is larger than real development: |Pot "
                             f"change| (same listed position at both cards only), core growth or core "
                             f"decline in display steps over the limit of his role and age "
                             f"(CARD_LIMITS: {CARD_MARGIN:g} x the widest DEV p99.9 of ages age-1 to "
                             f"age+1; decline at least as wide as growth). Two checks: the pair from the "
                             f"earlier pull to the latest (limits times max(1, span)) and every step "
                             f"between two consecutive pulls inside the pair window under "
                             f"{CARD_STEP_DAYS} game days apart (the one-year limits)",
            "core_sum": "sum over the core skills of underlying(display) on the dev_odds internal scale",
            "odds": f"dev_odds grid cell role / age / Pot bucket / growth bucket (odds_cell); "
                    + (f"ages {AGE_MIN}-{GRID_AGE_MIN - 1} use the age-{GRID_AGE_MIN} cell; " if AGE_MIN < GRID_AGE_MIN
                       else f"the grid has a cell for every age {GRID_AGE_MIN}-{GRID_AGE_MAX}; ")
                    + f"null when the cell has n < {MIN_N} (note says so); a player without growth uses the "
                      f"pot_only cell (odds_cell ends in /any)",
            "vs_typical": "core_sum minus the MEDIAN core_sum of this league's own players of the same age and Pot bucket (peer group >= 20), internal points; the DEV mean is the fallback for a thin peer group (vs_typical_basis says which)",
            "flag": f"keep = grow >= {KEEP_GROW['H']:g} (H) or >= {KEEP_GROW['P']:g} (P) and pot_dir not down; "
                    f"move = pot_dir down and grow <= {MOVE_GROW['H']:g} (H) or <= {MOVE_GROW['P']:g} (P); else null",
            "level": "Lev from the app's hitters.json / pitchers.json, else the archive's lev, else null",
            "peak": f"peak_p25 / peak_p50 / peak_p75 = the eventual peak WAA (p25, p50, p75) of the DEV "
                    f"players in the same cell (peak_cell, same key as odds_cell; dev_odds 'peak', or "
                    f"'peak_pot_only' when growth is unknown, cell ends in /any); DEV peak = max "
                    f"engine now_WAA over the player's later dumps, players seen at age >= "
                    f"{odds.get('peak_basis', {}).get('min_age', DO.PEAK_MIN_AGE)} only; a growth cell "
                    f"with n < {MIN_N} falls back to the pot-only cell of the same age and Pot (note: "
                    f"'thin growth cell'), and only when that is thin too are the peak fields null "
                    f"(note says thin); peak_n = the cell's n",
            "share_now": "the player's current WAA the conditional fields start from: hitters 'Max WAA "
                         "wtd', pitchers the larger of 'WAA wtd' and 'WAA wtd RP' from the app's "
                         "hitters.json / pitchers.json, the same now the DEV cache priced its own "
                         "players on (agecurve_fit.py) and the org builder's currentValue; null when "
                         "he is in neither file",
            "share_basis": f"which lookalikes the conditional fields read: 'now tercile' = the dev_odds "
                           f"by_now sub-cell of his cell whose now range holds share_now, used when it "
                           f"has n >= {MIN_N}, gain-distance rule; 'now tercile, edge' = share_now sits "
                           f"above the top sub-cell's hi or below the bottom sub-cell's lo (outside "
                           f"every lookalike's current; a now in the small gap between two sub-cells "
                           f"is not an edge), so the chance is the LOWER of the gain rule and the "
                           f"nearest sub-cell's own peak-level share (its mlb / useful / good): the "
                           f"gain rule alone would lend a player above the group gains measured on "
                           f"players who were never where he is, and the sub-cell share alone would "
                           f"credit a player below the group with better players' outcomes; 'whole cell' = "
                           f"the cell's gain_grid when the nearest sub-cell is thin, gain rule; prefix "
                           f"'pot-only, ' when the pot-only cell stood in; null when share_now is null "
                           f"(then peak_mlb / peak_useful / peak_good are the cell shares as is)",
            "listed_peak": "the app's listed peak: MAX WAA P (hitters) or the larger of WAP and WAP RP "
                           "(pitchers) from public/data/<LG>/hitters.json and pitchers.json; null when "
                           "the player is in neither file",
            "peak_vs_listed": "peak_p50 minus listed_peak, one decimal; null when either is null",
            "peak_gain": f"peak_gain_p25 / peak_gain_p50 / peak_gain_p75 = the gain of his lookalikes "
                         f"(p25, p50, p75): each DEV player's eventual peak WAA minus his now-WAA at "
                         f"that dump; never below 0; from the now-tercile sub-cell's gain_grid when "
                         f"share_basis is a tercile (so the gain is conditional on his current: a "
                         f"player near the top of his cell gets the smaller gain of the lookalikes "
                         f"who were already there), else the whole cell's dev_odds gain_p25 / "
                         f"gain_p50 / gain_p75; null when the cell has n < {MIN_N}, the same rule as "
                         f"peak_p50; the app's growth target (Proj Potential) is the player's "
                         f"current WAA + peak_gain_p50",
            "peak_mlb": f"the chance his eventual peak reaches {bars.get('mlb', -1.0):g} WAA (an "
                        f"MLB-level player, a 5th starter or bench bat) FROM WHERE HE IS NOW: the "
                        f"share of his lookalikes' gains at or above ({bars.get('mlb', -1.0):g} - "
                        f"share_now), read off the gain grid share_basis names, linear between the "
                        f"grid's quantile levels (5, 10, ..., 95): 1.0 when the distance is <= "
                        f"{BAR_TOLERANCE:g} (at the bar, or under it by no more than the app's "
                        f"one-decimal display rounding: a row shown as 0.0 can sit at -0.02 and must "
                        f"not read under 100%), 1.0 down to 0.95 below the 5% quantile, 0.05 down "
                        f"to 0 between the 95% quantile and twice it; a player already at or above "
                        f"the bar reads 1.0 (user, 2026-09-24: 'there are a ton of guys who are "
                        f"already at 0+ WAA that are getting like tagged as less than 100% to reach "
                        f"it', and 'guys already at 0+ WAA tagged as less than 100% is obviously not "
                        f"intended'); when share_basis is an edge the chance is the lower of the "
                        f"gain rule and the nearest sub-cell's own share whose eventual peak reached "
                        f"the bar, still 1.0 at the bar; the org builder orders minors playing time by this chance first "
                        f"(user, 2026-09-24: 'if they will ever be anything in the mlb'); null when "
                        f"the cell has n < {MIN_N}, the same rule as peak_p50",
            "peak_useful": f"peak_useful / peak_good = the same conditional chance at "
                           f"{bars.get('useful', 0.0):g} WAA (an average MLB player) and "
                           f"+{bars.get('good', 1.5):g} (a star), bars from dev_odds "
                           f"peak_bars; user, 2026-09-24: Make it % is playing time, not quality, "
                           f"these say whether the lookalikes turned out good enough",
            "cell_shares": "cell_mlb / cell_useful / cell_good = the cell's own mlb_share / "
                           "useful_share / good_share (the share of the whole cell whose eventual "
                           "peak reached each bar, blind to his current), for reference; the app "
                           "reads peak_mlb / peak_useful / peak_good",
        },
        "counts": counts_of(players, bars),
        "players": players,
    }


def fmt(v, spec):
    return format(v, spec) if v is not None else "-"


def in_org(e):
    """True for a player under contract with an org (not an amateur or a free agent)."""
    return e["level"] is not None and e["level"] not in NO_ORG_LEVELS


def print_summary(league, players, log=print):
    c = counts_of(players)
    log(f"  players {AGE_MIN}-{AGE_MAX}: {c['players']} (H {c['H']}, P {c['P']}); "
        f"with growth {c['with_growth']}; card replaced (growth unknown) "
        f"{c['card_replaced']}; with odds {c['with_odds']}; "
        f"with Exp peak {c['with_peak']}; with gain {c['with_gain']}; with MLB share {c['with_mlb']}; "
        f"with useful/good {c['with_useful']}; with a listed peak {c['with_listed_peak']}")
    sb = c["share_basis"]
    log(f"  shares from where he is now: {c['conditional']} of {c['with_mlb']} (with a current WAA "
        f"{c['with_now']}); basis now tercile {sb['now tercile']}, edge {sb['now tercile, edge']}, "
        f"whole cell {sb['whole cell']}, pot-only tercile {sb['pot-only, now tercile']}, pot-only "
        f"edge {sb['pot-only, now tercile, edge']}, pot-only whole {sb['pot-only, whole cell']}, "
        f"none {sb['none']}; thin growth cell -> pot-only group {c['pot_only_fallback']}; "
        f"already at 0 WAA {c['at_useful_bar']}; at a bar within {BAR_TOLERANCE:g} "
        f"{c['at_bar_tolerance']}; outside every lookalike (edge) {c['edge']}")
    log(f"  flags: keep {c['keep']} (H {c['keep_H']}, P {c['keep_P']}), "
        f"move {c['move']} (H {c['move_H']}, P {c['move_P']}), none {c['none']}")
    org = [e for e in players.values() if in_org(e)]
    log(f"  in an org (level not {'/'.join(sorted(NO_ORG_LEVELS))} or unknown): {len(org)}; "
        f"keep {sum(1 for e in org if e['flag'] == 'keep')}, "
        f"move {sum(1 for e in org if e['flag'] == 'move')}")
    hdr = f"    {'name':24s} {'pos':3s} {'lev':4s} age  Pot dPot  grow   odds  cell"

    def line(e):
        return (f"    {(e['name'] or '')[:24]:24s} {e['pos'][:3]:3s} {(e['level'] or '-')[:4]:4s} "
                f"{e['age']:3d}  {fmt(e['pot'], '3d')} {fmt(e['pot_delta'], '+4d')}  "
                f"{fmt(e['grow'], '+4.1f')}  {fmt(e['odds'], '5.2f')}  {e['odds_cell'] or '-'}")

    keep = [e for e in org if e["flag"] == "keep"]
    keep.sort(key=lambda e: (-(e["odds"] if e["odds"] is not None else -1), -(e["grow"] or 0), -(e["pot"] or 0)))
    log(f"  top {TOP} keep in an org (by odds, then growth):")
    log(hdr)
    for e in keep[:TOP]:
        log(line(e))
    move = [e for e in org if e["flag"] == "move"]
    move.sort(key=lambda e: ((e["pot_delta"] or 0), (e["grow"] or 0), -(e["pot"] or 0)))
    log(f"  top {TOP} move in an org (by Pot drop, then growth):")
    log(hdr)
    for e in move[:TOP]:
        log(line(e))
    peak = [e for e in org if e["peak_p50"] is not None]
    peak.sort(key=lambda e: (-e["peak_p50"], -(e["odds"] if e["odds"] is not None else -1)))
    log(f"  top {TOP} Exp peak in an org (by peak p50; mlb / useful / good = the chance his peak "
        f"reaches -1.0 / 0 / +1.5 WAA from his current (now), basis = which gain grid):")
    log(f"    {'name':24s} {'pos':3s} {'lev':4s} age  Pot  grow   odds  listed     now   p25   p50   p75  "
        f"gain p50     mlb  useful   good  basis                  cell")
    for e in peak[:TOP]:
        log(f"    {(e['name'] or '')[:24]:24s} {e['pos'][:3]:3s} {(e['level'] or '-')[:4]:4s} "
            f"{e['age']:3d}  {fmt(e['pot'], '3d')} {fmt(e['grow'], '+4.1f')}  {fmt(e['odds'], '5.2f')}  "
            f"{fmt(e['listed_peak'], '+6.2f')}  {fmt(e['share_now'], '+6.2f')} {fmt(e['peak_p25'], '+5.1f')} "
            f"{fmt(e['peak_p50'], '+5.1f')} {fmt(e['peak_p75'], '+5.1f')}  {fmt(e['peak_gain_p50'], '+8.2f')}  "
            f"{fmt(e['peak_mlb'], '6.3f')} {fmt(e['peak_useful'], '6.3f')} {fmt(e['peak_good'], '6.3f')}  "
            f"{(e['share_basis'] or '-'):22s} {e['peak_cell'] or '-'}")


def exported_leagues():
    """Leagues put in the app from an OOTP database export (ingest/
    export_league.py; leagues.json entries with a "basis"). They read the
    same rules as TGS and BLM (true ratings from the export)."""
    try:
        with open(os.path.join(DATA_DIR, "leagues.json"), encoding="utf-8") as fh:
            return [e["id"] for e in json.load(fh).get("leagues") or []
                    if e.get("basis") and e.get("id") not in LEAGUES]
    except (OSError, ValueError):
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="DEV-league odds applied to a league's 16-26 year olds")
    ap.add_argument("--league", required=True, help="TGS or BLM")
    ap.add_argument("--write", action="store_true", help="write public/data/<LG>/dev_signals.json")
    ap.add_argument("--db", default=DB_PATH, help="ratings_history.db path")
    ap.add_argument("--odds", default=ODDS_PATH, help="dev_odds.json path")
    args = ap.parse_args(argv)
    try:                                    # a console codepage must not fail the run on a name
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    league = args.league.upper()
    if league not in LEAGUES and league not in exported_leagues():
        raise SystemExit(f"--league must be one of {', '.join(LEAGUES + tuple(exported_leagues()))}; "
                         "DEV only supplies the grid")
    if not os.path.isfile(args.db):
        raise SystemExit(f"no archive at {args.db}")
    odds = load_odds(args.odds)
    conn = sqlite3.connect(args.db)
    try:
        choice, players = measure(conn, league, odds)
    finally:
        conn.close()
    print_summary(league, players)
    payload = build_payload(league, choice, players, odds)
    if args.write:
        out = os.path.join(DATA_DIR, league, "dev_signals.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False)
        print(f"  wrote {out}")
    else:
        print("  (dry run; add --write to write public/data/<LG>/dev_signals.json)")
    return payload


if __name__ == "__main__":
    main()
