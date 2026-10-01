"""
Pitcher projection engine -- a faithful, literal port of "The Sheet" Pitchers tab.

It computes every output column (per-BF counting stats -> wOBA-against ->
RA/9 -> WAA/WAR) from a pitcher's rating inputs plus the league's lifted
Data Points / Filters / Ballparks constants. Four role blocks are produced:
  SP   (Starter present-day)     gate: Starter  AND Eligible
  RP   (Reliever present-day)    gate: Eligible
  P    (Starter potential)       gate: Starter P AND Eligible AND Age<24
  P RP (Reliever potential)      gate: Eligible AND Age<24

NOTHING here writes to any workbook. Constants are read read-only.

Run directly to VALIDATE against the sheet's own cached values:
    python tgs-viz/engine/pitchers.py [LEAGUE]      (default TGS)
It computes from rating inputs and reports the max abs diff per output column.
This is the fidelity gate: the port is only trusted when diffs are ~0.
"""
import math, os, sys, re, json
from openpyxl import load_workbook

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------- constants loader (read-only) ----------
def _detect_park_row(path):
    """The Ballparks AA park-factor cell sits at a different row per league
    (TGS row 41, BLM row 39). Read it from the wOBA vR formula's Ballparks ref."""
    wb = load_workbook(path, read_only=True, data_only=False)
    ws = wb["Pitchers"]
    hdr = frow = None
    for i, row in enumerate(ws.iter_rows()):
        v = [c.value for c in row]
        if i == 0:
            hdr = [str(x).strip() if x is not None else "" for x in v]
        elif i == 1:
            frow = v
            break
    wb.close()
    m = re.search(r"Ballparks!\$AA\$(\d+)", str(frow[hdr.index("wOBA vR")]))
    return int(m.group(1)) if m else 41


def scan_consts(path):
    wb = load_workbook(path, read_only=True, data_only=True)
    dp, filt = {}, {}
    for row in wb["Data Points"].iter_rows():
        for c in row:
            if c.value is not None:
                dp[c.coordinate] = c.value
    for row in wb["Filters"].iter_rows():
        for c in row:
            if c.value is not None:
                filt[c.coordinate] = c.value
    bp = {}
    for row in wb["Ballparks"].iter_rows(min_row=30, max_row=50):
        for c in row:
            if c.value is not None:
                bp[c.coordinate] = c.value
    wb.close()
    row = _detect_park_row(path)
    park_aa = float(bp[f"AA{row}"]) if f"AA{row}" in bp and bp[f"AA{row}"] not in ("", None) else 1.0
    return dp, filt, park_aa


def num(v):
    """Coerce a cell value to float, or None if blank/non-numeric."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "" or s == "-":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def load_scurves(path):
    """Load a scurve_fit.py scurves-preview.json or a promote_scurves.py
    scurves.json -> the `scurves` dict compute() accepts:
    {"SP": {block: params}, "RP": {block: params}}. OPT-IN ONLY: the
    sheet-fidelity validator never passes this.

    scurves.json is chosen per block (promote_scurves.py): a block missing
    from a role runs the two-segment line, and a role may have no blocks.
    Its "twoline_offsets" (per role, per block) come back under "_twoline";
    compute() adds them to the two-segment lines so those match the live
    league's level. Files without them (previews, older scurves.json) give
    no "_twoline" key."""
    data = json.load(open(path, encoding="utf-8"))
    roles = data.get("roles") or {}
    out = {role: dict((roles.get(role) or {}).get("blocks") or {}) for role in ("SP", "RP")}
    tl = {role: dict((roles.get(role) or {}).get("twoline_offsets") or {}) for role in ("SP", "RP")}
    if any(tl.values()):
        out["_twoline"] = tl
    return out


PITCH_TYPES = ["FB", "SL", "CB", "CH", "CT", "SI", "SP", "KC", "KN", "SC", "FO", "CC"]
ROLE_STUFF_FEATURES = ("n", "g1", "g2", "mean", "top2_gap", "best_gap", "stu")
# One offset per displayed listed-role stuff level (20, 25, ..., 60 or more;
# 20 is the floor, where a listed reliever never gains) on top of the linear
# terms (the "stu" slope then only acts inside the pooled 60+ level):
# the gain is not linear in the stuff level (review 2026-09-26: a single
# linear term under-predicted 50+ stuff arms and kept rising past 75).
ROLE_STUFF_LEVELS = (20, 25, 30, 35, 40, 45, 50, 55, 60)


def role_stuff_level(stu):
    """Displayed stuff level bin of the role-stuff model: 20 or less -> 20,
    60 or more -> 60, else the nearest 5."""
    b = int(round(float(stu) / 5.0)) * 5
    return min(max(b, ROLE_STUFF_LEVELS[0]), ROLE_STUFF_LEVELS[-1])


def arsenal_features(grades, stu):
    """Arsenal features of the role-stuff model (role_stuff_fit.py): pitch
    count, best and second grade, mean grade, top-two mean minus the mean,
    best minus the mean of the rest, and the displayed stuff of the listed
    role. grades: {pitch: grade}; zero / blank grades are pitches he lacks.
    None when he has no graded pitch or no stuff."""
    g = sorted((float(v) for v in (grades or {}).values() if v not in (None, "") and float(v) > 0),
               reverse=True)
    if not g or stu is None:
        return None
    n = len(g)
    g1, g2 = g[0], (g[1] if n > 1 else g[0])
    mean = sum(g) / n
    rest = g[1:] if n > 1 else g
    return {"n": n, "g1": g1, "g2": g2, "mean": mean, "top2_gap": (g1 + g2) / 2 - mean,
            "best_gap": g1 - sum(rest) / len(rest), "stu": float(stu)}


def role_stuff_gain(model, grades, stu):
    """Expected stuff gain as a reliever (display points) from one fitted
    view of calib/<LEAGUE>/role_stuff.json, or None when the arsenal is
    unknown. Version 2 models carry a level offset per displayed stuff level
    (level_coef); the first form had a linear "stu" feature instead."""
    f = arsenal_features(grades, stu)
    if f is None or not model:
        return None
    v = model.get("intercept", 0.0) + sum(c * f[k] for k, c in zip(model["features"], model["coef"]))
    lc = model.get("level_coef")
    if lc:
        v += float(lc.get(str(role_stuff_level(f["stu"])), 0.0))
    lo, hi = model.get("clip", (0.0, 15.0))
    return min(max(v, lo), hi)


def _pos_grades(grades):
    return {k: float(v) for k, v in (grades or {}).items() if v not in (None, "") and float(v) > 0}


def role_stuff_observed(role_stuff, pid, name, listed_sp, grades, stu, pot=False):
    """What OOTP actually did for THIS pitcher (review 2026-09-26): the gain
    of his own archived SP <-> RP switch when it had the same pitch grades
    and the same stuff in his listed role (for pot=True: the potential
    grades and STU P). None when there is no such switch."""
    obs = (role_stuff or {}).get("observed") or {}
    rows = obs.get(str(pid)) if pid is not None else None
    if not rows or stu is None:
        return None
    mine = _pos_grades(grades)
    for o in rows:
        if o.get("name") != name:
            continue
        if _pos_grades(o.get("pot_grades" if pot else "grades")) != mine:
            continue
        sp_k, rp_k = ("sp_stu_p", "rp_stu_p") if pot else ("sp_stu", "rp_stu")
        if o.get(sp_k) is None or o.get(rp_k) is None:
            continue
        if float(o[sp_k if listed_sp else rp_k]) != float(stu):
            continue
        return float(o[rp_k]) - float(o[sp_k])
    return None


def load_role_stuff(path):
    """Load a role_stuff_fit.py calib/<LEAGUE>/role_stuff.json. OPT-IN, the
    same contract as load_currency: the live pipeline passes it, the
    sheet-fidelity validator never does."""
    return json.load(open(path, encoding="utf-8"))


def load_currency(path):
    """Load a currency_fit.py calib/<LEAGUE>/currency.json (audit D2/D9): the
    archive-FITTED cross-type currency layer. OPT-IN ONLY — same contract as
    load_scurves: the live pipeline passes it, the sheet-fidelity validator
    below never does, so validation keeps matching the workbook bit-for-bit."""
    return json.load(open(path, encoding="utf-8"))


# Data Points cells of the two role stat lines (SP: present-day starter, RP:
# present-day reliever; the P lines reuse them).
SP_CFG = dict(
    role="SP",
    HBP_k="K10",
    uBB_anchor="H5", uBB_sh="C3", uBB_ih="B3", uBB_sl="E3", uBB_il="D3", uBB_k="K3",
    SO_anchor="H2", SO_sh="C7", SO_ih="B7", SO_sl="E7", SO_il="D7", SO_k="K5",
    stu_delta=0, stu_delta_rp=-5, stu_lo_adj=True,
    HR_anchor="H3", HR_sh="C5", HR_ih="B5", HR_sl="E5", HR_il="D5", HR_k="K4",
    HH_anchor="H4", HH_sh="C9", HH_ih="B9", HH_sl="E9", HH_il="D9", HH_k="K6",
    xbh_k="K7", t3b_k="K8",
    hld_anchor="I2", sbat_k="K12", sbpct_k="K9",
    woba_w=["H12", "H13", "H14", "H15", "H16", "H17", "H18", "H19"],
    scale="I31", ra9_base="H41",
)
RP_CFG = dict(
    role="RP",
    HBP_k="K22",
    uBB_anchor="H10", uBB_sh="C14", uBB_ih="B14", uBB_sl="E14", uBB_il="D14", uBB_k="K15",
    SO_anchor="H7", SO_sh="C18", SO_ih="B18", SO_sl="E18", SO_il="D18", SO_k="K17",
    # audit B6 (INTENTIONAL divergence from the sheet): the sheet's RP <50 branch
    # drops the +5 starter-STU bonus (stu_lo_adj was False here) while its SP-block
    # mirror keeps the -5 in both branches, proving intent. A starter at STU 40 lost
    # 5·E18 of K% and his relief floor cliffed at the 50 crossing; the engine now
    # applies the adjusted STU in BOTH branches.
    stu_delta=5, stu_delta_rp=0, stu_lo_adj=True,
    HR_anchor="H8", HR_sh="C16", HR_ih="B16", HR_sl="E16", HR_il="D16", HR_k="K16",
    HH_anchor="H9", HH_sh="C20", HH_ih="B20", HH_sl="E20", HH_il="D20", HH_k="K18",
    xbh_k="K19", t3b_k="K20",
    # INTENTIONAL divergence from the sheet: the sheet's 'SB% vR/vL RP' formulas
    # add Data Points K9 — the SP block's league SB% — while their SBAT sibling
    # in the same formula pair correctly adds the RP block's K24. K21 is the RP
    # league SB% and had no reader anywhere; the RP line now adds its own rate,
    # like every other constant in RP_CFG.
    hld_anchor="I7", sbat_k="K24", sbpct_k="K21",
    woba_w=["K29", "K30", "K31", "K32", "K33", "K34", "K35", "K36"],
    scale="I29", ra9_base="H42",
)
# rate block -> its cell-name prefix in SP_CFG / RP_CFG
TWOLINE_PREFIX = {"uBB": "uBB", "SO": "SO", "HR": "HR", "HHR": "HH"}


def twoline_rate(dp, role, blk, r):
    """One block's two-segment rate line at rating r, as statline() prices it
    with no level offset, no role-stuff shift and no handedness multiplier.
    scurve_fit.py uses it to level the line on the live population."""
    cfg = SP_CFG if role == "SP" else RP_CFG
    pf = TWOLINE_PREFIX[blk]
    g = lambda k: float(dp[cfg[f"{pf}_{k}"]])
    if r >= 50:
        return (r - g("anchor")) * g("sh") + g("ih") + g("k")
    return (r - g("anchor")) * g("sl") + g("il") + g("k")


def compute(p, dp, filt, park_aa, scurves=None, currency=None, role_stuff=None):
    """p: dict of rating inputs + meta (incl. _row). Returns dict of computed outputs.

    role_stuff (OPT-IN, 2026-09-26 — INTENTIONAL divergence from the sheet
    when passed): a role_stuff_fit.py dict (calib/<LEAGUE>/role_stuff.json).
    The sheet moves every pitcher's stuff a flat 5 for the other role (-5 for
    a listed reliever on the starter lines, +5 for a listed starter on the
    reliever lines). With role_stuff the move is his own expected gain from
    his arsenal and listed-role stuff (measured on the league's role switches:
    about half never change a notch). p may carry "_grades" / "_pot_grades"
    ({pitch: grade}) and "_stu" (overall displayed stuff); a pitcher without
    them keeps the flat 5. When role_stuff is None the output is bit-identical
    to the sheet.

    Faithful port: every branch / quirk mirrors the sheet's array formulas.

    scurves (OPT-IN, audit D1): when given ({"SP"/"RP": {"SO"/"uBB"/"HR"/"HHR":
    {A,B,k,m,offset,support}}}), those four rate blocks are evaluated as the
    fitted+transported logistic  A + B/(1+e^(-k(r-m))) + offset  (rating clamped
    to the fitted support) instead of the two-segment anchor lines. Everything
    downstream (XBH/3B split, SBAT, wOBA weights, RA/9, WAA) is unchanged.
    A block missing from scurves[role] keeps the two-segment line; when
    scurves carries "_twoline" ({role: {block: offset}}, from scurves.json),
    that offset is added to the block's two-segment rate so the line matches
    the live league's level (scurve_fit.py measures it the same way as the
    S-curve's own offset). Slopes and the 50 kink are unchanged.
    When scurves is None (default) the output is bit-identical to the sheet.

    currency (OPT-IN, audit D2 + D9 — INTENTIONAL divergence from the sheet
    when passed): a currency_fit.py dict (calib/<LEAGUE>/currency.json). Two
    effects here:
      * ra9_exponent {"SP": e, "RP": e} — the wOBA->RA/9 conversion becomes
        (wOBA/lg)^e instead of the sheet's ^2. FITTED per league per role from
        the clone archives (log-log, BF-weighted; octile calibration table is
        flat under the fit and tilted 0.97->1.04 under ^2). The sheet's ^2
        under-spreads pitcher run impact ~12-15% — the pitcher half of the
        hitter<->pitcher currency skew (audit D2). League-average RA/9 is
        unchanged (the ratio is 1 at the anchor).
      * pitcher_cells {"H30": rpw, ...} — Data Points VALUE overrides. H30 is
        runs-per-win: the sheet's 9*(R/IP)*1.5+3 tangent formula sits below the
        archive's own fitted wins-on-run-diff regression; one FITTED RPW per
        league ships (mid-range spec = GM of the two OLS directions, audit D9).
    When currency is None (default) the output is bit-identical to the sheet.
    """
    if currency:
        cells = currency.get("pitcher_cells") or {}
        if cells:
            dp = {**dp, **cells}
    exps = (currency or {}).get("ra9_exponent") or {}
    ra9_exp = {"SP": float(exps.get("SP", 2.0)), "RP": float(exps.get("RP", 2.0))}
    g = lambda k: float(dp[k])          # Data Points (strict)
    # blank-tolerant Data Points accessor (Excel treats blank SUMPRODUCT cells as 0)
    g0 = lambda k: float(dp[k]) if k in dp and isinstance(dp.get(k), (int, float)) else 0.0
    f = lambda k: float(filt[k]) if k in filt and filt[k] not in ("", None) else None

    T = (p.get("T") or "").strip()      # throws R/L/S
    POS = (p.get("POS") or "").strip()
    is_sp = POS == "SP"

    # Role-stuff shifts (opt-in, see the docstring): None keeps the sheet's
    # flat 5. Current lines use the current arsenal and overall stuff; the P
    # lines the potential arsenal and STU P. Order: his own archived switch
    # when it matches (what OOTP did), else the model, else the view's mean
    # gain (no pitch grades on the row, e.g. the first archived pulls). A
    # listed reliever never goes below the 20 floor on the starter line, and
    # a maxed pitcher's potential gain is at least his current gain (review
    # 2026-09-26: the archive shows STU P gains >= STU gains for maxed arms).
    def _gain(view, grades_key, stu_val, pot):
        if not role_stuff:
            return None
        g = role_stuff_observed(role_stuff, p.get("_id"), p.get("_name"), is_sp,
                                p.get(grades_key), stu_val, pot=pot)
        if g is None:
            model = (role_stuff.get("models") or {}).get(view)
            g = role_stuff_gain(model, p.get(grades_key), stu_val)
            if g is None and model and model.get("mean_gain") is not None:
                g = float(model["mean_gain"])
        if g is not None and not is_sp and stu_val is not None:
            g = min(g, max(0.0, float(stu_val) - 20.0))
        return g

    stu_now = p.get("_stu")
    if stu_now is None and p.get("STU vR") is not None and p.get("STU vL") is not None:
        stu_now = (p["STU vR"] + p["STU vL"]) / 2.0
    gain_now = _gain("sp_view" if is_sp else "rp_view", "_grades", stu_now, False)
    gain_pot = _gain("pot_sp_view" if is_sp else "pot_rp_view", "_pot_grades", p.get("STU P"), True)
    if (gain_now is not None and gain_pot is not None and stu_now is not None and p.get("STU P") is not None
            and float(stu_now) == float(p["STU P"])
            and _pos_grades(p.get("_grades")) == _pos_grades(p.get("_pot_grades"))):
        gain_pot = max(gain_pot, gain_now)
    sign = 1.0 if is_sp else -1.0
    sh = lambda gv: None if gv is None else sign * gv
    if is_sp:
        shift_sp_line, shift_rp_line = None, sh(gain_now)
        shift_sp_line_p, shift_rp_line_p = None, sh(gain_pot)
    else:
        shift_sp_line, shift_rp_line = sh(gain_now), None
        shift_sp_line_p, shift_rp_line_p = sh(gain_pot), None
    row = p.get("_row", 2)
    EPS = row / 10000000.0

    H31, H32 = g("H31"), g("H32")        # BF (SP), BF RP
    out = {}

    # SUMPRODUCT helpers over a 4-wide constant vector (x^0..x^3); blanks -> 0
    def sp4(x, b, c, d, e):
        return g0(b) + g0(c) * x + g0(d) * x ** 2 + g0(e) * x ** 3

    # ---------------- generic role stat-line builder ----------------
    # cfg carries all the row/col anchors + league-adj cells that differ
    # between SP and RP blocks. handed picks HR/H-HR handedness multipliers.
    def statline(CON, STU, HRR, PBABIP, BF, cfg, handed, stu_shift=None):
        # opt-in fitted S-curves for this cfg's regression block (audit D1)
        sc = (scurves or {}).get(cfg.get("role")) or {}
        # level offsets for the blocks that stay on the two-segment line
        tlo = ((scurves or {}).get("_twoline") or {}).get(cfg.get("role")) or {}

        def tl(blk, v):
            return v + tlo[blk] if blk in tlo else v

        def sc_rate(blk, r):
            c = sc[blk]
            lo, hi = c.get("support", (20.0, 80.0))
            rr = min(max(r, lo), hi)
            v = c["A"] + c["B"] / (1.0 + math.exp(-c["k"] * (rr - c["m"]))) + c["offset"]
            kn = c.get("knot")
            if kn:
                # elite-K hinge (D1 tail, SO block): the fitted 75->80 K% jump
                # the logistic saturates below. Slope is live-fitted (hinge_hi=80)
                # or archive-transported (hinge_hi=narrowed support) — see
                # scurve_fit.py; s >= 0 keeps it monotone. Uses the RAW rating
                # (capped at kn["hi"]) so the hinge can keep climbing where the
                # drift-narrowed logistic support has already saturated.
                v += kn["s"] * max(0.0, min(r, kn["hi"]) - kn["r"])
            return v

        # HBP
        HBP = g(cfg["HBP_k"]) * BF
        # uBB (CON): anchor, slope hi/lo, int hi/lo, +Kadj
        if "uBB" in sc:
            uBB = sc_rate("uBB", CON) * (BF - HBP)
        elif CON >= 50:
            uBB = tl("uBB", (CON - g(cfg["uBB_anchor"])) * g(cfg["uBB_sh"]) + g(cfg["uBB_ih"]) + g(cfg["uBB_k"])) * (BF - HBP)
        else:
            uBB = tl("uBB", (CON - g(cfg["uBB_anchor"])) * g(cfg["uBB_sl"]) + g(cfg["uBB_il"]) + g(cfg["uBB_k"])) * (BF - HBP)
        uBB = max(uBB, 0.0)
        # SO (STU): POS adjusts the rating used. The sheet's RP/P-RP <50 branch
        # uses the *bare* STU (cfg stu_lo_adj flags it) — that was audit bug B6;
        # all cfgs now set stu_lo_adj=True so the adjustment holds in both branches.
        delta = cfg["stu_delta"] if is_sp else cfg["stu_delta_rp"]
        if stu_shift is not None and delta != 0:    # role_stuff: his own gain instead of the flat 5
            delta = stu_shift
        stu_adj = STU + delta
        if "SO" in sc:
            SO = sc_rate("SO", stu_adj) * (BF - uBB - HBP)
        elif stu_adj >= 50:
            SO = tl("SO", (stu_adj - g(cfg["SO_anchor"])) * g(cfg["SO_sh"]) + g(cfg["SO_ih"]) + g(cfg["SO_k"])) * (BF - uBB - HBP)
        else:
            stu_lo = stu_adj if cfg["stu_lo_adj"] else STU
            SO = tl("SO", (stu_lo - g(cfg["SO_anchor"])) * g(cfg["SO_sl"]) + g(cfg["SO_il"]) + g(cfg["SO_k"])) * (BF - uBB - HBP)
        SO = max(SO, 0.0)
        # HR (HRR): + handedness multiplier
        hr_mult = handed["hr"]
        if "HR" in sc:
            HR = sc_rate("HR", HRR) * (BF - uBB - HBP) * hr_mult
        elif HRR >= 50:
            HR = tl("HR", (HRR - g(cfg["HR_anchor"])) * g(cfg["HR_sh"]) + g(cfg["HR_ih"]) + g(cfg["HR_k"])) * (BF - uBB - HBP) * hr_mult
        else:
            HR = tl("HR", (HRR - g(cfg["HR_anchor"])) * g(cfg["HR_sl"]) + g(cfg["HR_il"]) + g(cfg["HR_k"])) * (BF - uBB - HBP) * hr_mult
        HR = max(HR, 0.0)
        # H-HR (PBABIP): + babip handedness multiplier
        bab_mult = handed["bab"]
        rem = BF - HBP - uBB - SO - HR
        if "HHR" in sc:
            HHR = sc_rate("HHR", PBABIP) * rem * bab_mult
        elif PBABIP >= 50:
            HHR = tl("HHR", (PBABIP - g(cfg["HH_anchor"])) * g(cfg["HH_sh"]) + g(cfg["HH_ih"]) + g(cfg["HH_k"])) * rem * bab_mult
        else:
            HHR = tl("HHR", (PBABIP - g(cfg["HH_anchor"])) * g(cfg["HH_sl"]) + g(cfg["HH_il"]) + g(cfg["HH_k"])) * rem * bab_mult
        HHR = max(HHR, 0.0)
        # XBH-HR = H-HR * Kxbh * Filters!E9 ; 3B = XBH * K3b * Filters!E10
        XBH = HHR * g(cfg["xbh_k"]) * f("E9")
        T3B = XBH * g(cfg["t3b_k"]) * f("E10")
        D2B = XBH - T3B
        S1B = HHR - XBH
        # SBAT / SB% (HLD): SUMPRODUCT((HLD-anchor)^{0..3}, vec) + Kadj
        HLD = p["HLD"]
        SBAT = max((sp4(HLD - g(cfg["hld_anchor"]), "B25", "C25", "D25", "E25") + g(cfg["sbat_k"]))
                   * (uBB + HBP + S1B), 0.0)
        SBpct = min(sp4(HLD - g(cfg["hld_anchor"]), "B23", "C23", "D23", "E23") + g(cfg["sbpct_k"]), 1.0)
        SB = SBpct * SBAT
        CS = SBAT - SB
        # wOBA: HBP,uBB,1B,2B,3B,HR,SB,CS weighted, / BF / park
        w = cfg["woba_w"]  # list of 8 DP cells
        wOBA = (HBP * g(w[0]) + uBB * g(w[1]) + S1B * g(w[2]) + D2B * g(w[3]) + T3B * g(w[4])
                + HR * g(w[5]) + SB * g(w[6]) + CS * g(w[7])) / BF / park_aa
        # RA/9 = (wOBA/lg-role-wOBA)^exp * RA9base. The sheet hardcodes exp=2;
        # the currency layer (audit D2) replaces it with the archive-fitted
        # per-role exponent. cfg["scale"] is the role's league wOBA (I31/I29).
        RA9 = (wOBA / g(cfg["scale"])) ** ra9_exp[cfg["role"]] * g(cfg["ra9_base"])
        return dict(HBP=HBP, uBB=uBB, SO=SO, HR=HR, HHR=HHR, XBH=XBH, T3B=T3B, D2B=D2B,
                    S1B=S1B, SBAT=SBAT, SBpct=SBpct, SB=SB, CS=CS, wOBA=wOBA, RA9=RA9)

    def statline_mix(CON, STU, HRR, PBABIP, BF, cfg, handed, stu_shift=None):
        """statline with a role-stuff shift priced the way OOTP moves the
        display: 0 or 5 (or 10) points, never 2.5. An expected gain g is the
        blend of the two whole notches around it, weight q = frac(g/5) on the
        upper one (review 2026-09-26: BLM's two-segment SO lines do not meet
        at 50, so pricing a fractional rating in (45, 50) came out above the
        flat 5). g = 5 gives exactly the flat 5."""
        if stu_shift is None:
            return statline(CON, STU, HRR, PBABIP, BF, cfg, handed)
        sgn = 1.0 if stu_shift >= 0 else -1.0
        x = abs(stu_shift) / 5.0
        k = math.floor(x)
        q = x - k
        lo = statline(CON, STU, HRR, PBABIP, BF, cfg, handed, stu_shift=sgn * 5.0 * k)
        if q < 1e-9:
            return lo
        hi = statline(CON, STU, HRR, PBABIP, BF, cfg, handed, stu_shift=sgn * 5.0 * (k + 1))
        return {key: (1.0 - q) * lo[key] + q * hi[key] for key in lo}

    def waa(ra9, ip, ra9_base, waa_const):
        return ((ra9_base - ra9) * (ip / 9.0)) / waa_const + EPS

    # ================= SP block (present-day starter) =================
    # handedness: HR uses Filters C11 (vR) / D11 (vL); H-HR uses C8 (vR) / D8 (vL)
    sp_R = statline_mix(p["CON vR"], p["STU vR"], p["HRR vR"], p["PBABIP vR"], H31, SP_CFG,
                    handed=dict(hr=f("C11"), bab=f("C8")), stu_shift=shift_sp_line)
    sp_L = statline_mix(p["CON vL"], p["STU vL"], p["HRR vL"], p["PBABIP vL"], H31, SP_CFG,
                    handed=dict(hr=f("D11"), bab=f("D8")), stu_shift=shift_sp_line)

    def emit(prefix, sR, sL, woba_share_func, ip, ra9_base, waa_const, scale, exp=2.0):
        for suf, s in (("vR", sR), ("vL", sL)):
            out[f"HBP {suf}{prefix}"] = s["HBP"]; out[f"uBB {suf}{prefix}"] = s["uBB"]
            out[f"SO {suf}{prefix}"] = s["SO"]; out[f"HR {suf}{prefix}"] = s["HR"]
            out[f"H-HR {suf}{prefix}"] = s["HHR"]; out[f"XBH-HR {suf}{prefix}"] = s["XBH"]
            out[f"3B {suf}{prefix}"] = s["T3B"]; out[f"2B {suf}{prefix}"] = s["D2B"]
            out[f"1B {suf}{prefix}"] = s["S1B"]; out[f"SBAT {suf}{prefix}"] = s["SBAT"]
            out[f"SB% {suf}{prefix}"] = s["SBpct"]; out[f"SB {suf}{prefix}"] = s["SB"]
            out[f"CS {suf}{prefix}"] = s["CS"]; out[f"wOBA {suf}{prefix}"] = s["wOBA"]
            out[f"RA/9 {suf}{prefix}"] = s["RA9"]
            out[f"WAA {suf}{prefix}"] = waa(s["RA9"], ip, ra9_base, waa_const)
        # wtd by throws-hand platoon share
        wtd_woba = woba_share_func(sR["wOBA"], sL["wOBA"])
        out[f"wOBA wtd{prefix}"] = wtd_woba
        ra9_wtd = (wtd_woba / scale) ** exp * ra9_base   # exp: currency layer (D2)
        out[f"RA/9 wtd{prefix}"] = ra9_wtd
        out[f"WAA wtd{prefix}"] = waa(ra9_wtd, ip, ra9_base, waa_const)

    # platoon weighting by T (throws): R->H24, L->H23, S->H25 ; wtd = vL*(1-share)+vR*share
    def share_by_T(vr, vl):
        share = {"R": g("H24"), "L": g("H23"), "S": g("H25")}.get(T, g("H24"))
        return vl * (1 - share) + vr * share

    emit("", sp_R, sp_L, share_by_T, g("H33"), g("H41"), g("H30"), g("I31"), ra9_exp["SP"])

    # Starter gate (sheet 'Starter' rule): a pitcher who doesn't qualify to start
    # gets NO starter projection — the sheet leaves those cells blank.
    spp = p.get("SP P Pitch") or 0
    npitch = p.get("Pitches") or 0
    stm = p.get("STM") or 0
    STARTER_MIN_STM = 35   # user-tuned: the sheet's 'Starter' rule uses 40; lowered to 35 so
                           # 35-stamina arms still qualify to start (engine intentionally diverges
                           # from the sheet here — change the sheet 'Starter'/'Starter P' formulas
                           # to >=35 too if you ever extract straight from the workbook).
    starter = ((spp >= 3) or (spp >= 2 and npitch >= 3) or (spp >= 1 and npitch >= 5)) and stm >= STARTER_MIN_STM
    out["Starter"] = starter
    if not starter:
        for suf in ("vR", "vL"):
            for c in ("HBP", "uBB", "SO", "HR", "H-HR", "XBH-HR", "3B", "2B", "1B",
                      "SBAT", "SB%", "SB", "CS", "wOBA", "RA/9", "WAA"):
                out[f"{c} {suf}"] = None
        out["wOBA wtd"] = out["RA/9 wtd"] = out["WAA wtd"] = None

    # ================= RP block (present-day reliever) =================
    rp_R =statline_mix(p["CON vR"], p["STU vR"], p["HRR vR"], p["PBABIP vR"], H32, RP_CFG,
                    handed=dict(hr=f("C11"), bab=f("C8")), stu_shift=shift_rp_line)
    # audit B11 (INTENTIONAL divergence from the sheet): the sheet's RP vL HR/H-HR
    # formulas reference the vR handedness filters (C11/C8); the engine uses the true
    # vL multipliers D11/D8 — same as the SP block's vL line (+3.8% HR-vL in BLM fixed).
    rp_L = statline_mix(p["CON vL"], p["STU vL"], p["HRR vL"], p["PBABIP vL"], H32, RP_CFG,
                    handed=dict(hr=f("D11"), bab=f("D8")), stu_shift=shift_rp_line)
    emit(" RP", rp_R, rp_L, share_by_T, g("H34"), g("H42"), g("H30"), g("I29"), ra9_exp["RP"])

    # ================= P blocks (potential, SPLIT-AWARE) =================
    # OOTP publishes pitcher potential without splits. Measured on fully-developed
    # (28+) TGS pitchers whose current split is >=5 pts (2026-09-04, n=911 lean-vR /
    # 396 lean-vL): the published P sits at the platoon BLEND of the two current
    # splits (P-mid +1.2/+0.1, vs P-vR -1.6/+3.0 and P-vL +4.0/-2.7) — NOT the vR
    # basis hitters.py measured for bats. So the peak keeps the pitcher's own
    # current lean AROUND P: per rating, with s = the same H24/H23/H25 platoon
    # share and lean = current vR - vL,
    #     peak_vR = P + (1-s)*lean      peak_vL = P - s*lean
    # (the s-weighted blend of the two peak lines is exactly P). Both peak lines
    # run through the same per-hand handedness multipliers and platoon weighting
    # as the current blocks — a splitty arm is no longer priced as flat-P against
    # both hands. INTENTIONAL divergence from the sheet, whose P cells are a
    # single blended line: the validator shows P-column diffs on splitty arms
    # (a zero-lean pitcher is unchanged to the digit).
    have_p = all(p.get(k) is not None for k in ("CON P", "STU P", "HRR P", "PBABIP P"))
    if have_p:
        s_share = {"R": g("H24"), "L": g("H23"), "S": g("H25")}.get(T, g("H24"))

        def peak(pcol, rcol, lcol):
            lean = (p[rcol] or 0) - (p[lcol] or 0)
            return p[pcol] + (1 - s_share) * lean, p[pcol] - s_share * lean

        conR, conL = peak("CON P", "CON vR", "CON vL")
        stuR, stuL = peak("STU P", "STU vR", "STU vL")
        hrrR, hrrL = peak("HRR P", "HRR vR", "HRR vL")
        babR, babL = peak("PBABIP P", "PBABIP vR", "PBABIP vL")

        POT_STATS = (("HBP", "HBP"), ("uBB", "uBB"), ("SO", "SO"), ("HR", "HR"),
                     ("H-HR", "HHR"), ("XBH-HR", "XBH"), ("3B", "T3B"), ("2B", "D2B"),
                     ("1B", "S1B"), ("SBAT", "SBAT"), ("SB%", "SBpct"), ("SB", "SB"),
                     ("CS", "CS"))

        def pot_block(cfg, anchor, suffix, role, ip_k, base_k, scale_k, stu_shift=None):
            pR = statline_mix(conR, stuR, hrrR, babR, anchor, cfg, handed=dict(hr=f("C11"), bab=f("C8")),
                          stu_shift=stu_shift)
            pL = statline_mix(conL, stuL, hrrL, babL, anchor, cfg, handed=dict(hr=f("D11"), bab=f("D8")),
                          stu_shift=stu_shift)
            for k, src in POT_STATS:
                out[f"{k}{suffix}"] = share_by_T(pR[src], pL[src])
            woba = share_by_T(pR["wOBA"], pL["wOBA"])
            out[f"wOBA{suffix}"] = woba
            ra9 = (woba / g(scale_k)) ** ra9_exp[role] * g(base_k)
            out[f"RA/9{suffix}"] = ra9
            return waa(ra9, g(ip_k), g(base_k), g("H30"))

        out["WAP"] = pot_block(SP_CFG, H31, " P", "SP", "H33", "H41", "I31", stu_shift=shift_sp_line_p)
        if not starter:   # non-starter -> no starter-potential projection either
            for k, _ in POT_STATS:
                out[f"{k} P"] = None
            out["wOBA P"] = out["RA/9 P"] = out["WAP"] = None

        out["WAP RP"] = pot_block(RP_CFG, H32, " P RP", "RP", "H34", "H42", "I29", stu_shift=shift_rp_line_p)
    return out


# ---------- validation ----------
RATING_COLS = ["STU P", "HRR P", "PBABIP P", "CON P", "STU vR", "HRR vR", "PBABIP vR", "CON vR",
               "STU vL", "HRR vL", "PBABIP vL", "CON vL", "STM", "HLD", "Pitches",
               "SP Pitch", "SP P Pitch", "B", "T", "POS", "Name", "Age"]
META = {"B", "T", "POS", "Name"}
OPTIONAL = {"STU P", "HRR P", "PBABIP P", "CON P", "SP P Pitch"}

# Output columns to validate (every computed numeric column in the sheet)
SP_COLS = ["HBP vR", "uBB vR", "SO vR", "HR vR", "H-HR vR", "XBH-HR vR", "3B vR", "2B vR", "1B vR",
           "SBAT vR", "SB% vR", "SB vR", "CS vR", "wOBA vR", "RA/9 vR", "WAA vR",
           "HBP vL", "uBB vL", "SO vL", "HR vL", "H-HR vL", "XBH-HR vL", "3B vL", "2B vL", "1B vL",
           "SBAT vL", "SB% vL", "SB vL", "CS vL", "wOBA vL", "RA/9 vL", "WAA vL",
           "wOBA wtd", "RA/9 wtd", "WAA wtd"]
RP_COLS = [c + " RP" for c in
           ["HBP vR", "uBB vR", "SO vR", "HR vR", "H-HR vR", "XBH-HR vR", "3B vR", "2B vR", "1B vR",
            "SBAT vR", "SB% vR", "SB vR", "CS vR", "wOBA vR", "RA/9 vR", "WAA vR",
            "HBP vL", "uBB vL", "SO vL", "HR vL", "H-HR vL", "XBH-HR vL", "3B vL", "2B vL", "1B vL",
            "SBAT vL", "SB% vL", "SB vL", "CS vL", "wOBA vL", "RA/9 vL", "WAA vL",
            "wOBA wtd", "RA/9 wtd", "WAA wtd"]]
P_COLS = ["HBP P", "uBB P", "SO P", "HR P", "H-HR P", "XBH-HR P", "3B P", "2B P", "1B P",
          "SBAT P", "SB% P", "SB P", "CS P", "wOBA P", "RA/9 P", "WAP"]
PRP_COLS = ["HBP P RP", "uBB P RP", "SO P RP", "HR P RP", "H-HR P RP", "XBH-HR P RP", "3B P RP",
            "2B P RP", "1B P RP", "SBAT P RP", "SB% P RP", "SB P RP", "CS P RP", "wOBA P RP",
            "RA/9 P RP", "WAP RP"]
CHECK_COLS = SP_COLS + RP_COLS + P_COLS + PRP_COLS


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "TGS"
    path = os.path.join(REPO, f"The Sheets {league}", "The Sheet Pitchers.xlsx")
    dp, filt, park_aa = scan_consts(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Pitchers"]
    header = None
    diffs = {c: 0.0 for c in CHECK_COLS}
    counts = {c: 0 for c in CHECK_COLS}
    worst = {c: None for c in CHECK_COLS}
    n = 0
    for ri, row in enumerate(ws.iter_rows()):
        vals = [c.value for c in row]
        if header is None:
            header = [str(v).strip() if v is not None else "" for v in vals]
            idx = {h: i for i, h in enumerate(header)}
            continue
        rec = {h: vals[i] for h, i in idx.items() if i < len(vals)}
        # row number in the sheet (header is row 1 -> first data row is 2)
        sheet_row = ri + 1
        if not rec.get("Name") or rec.get("Eligible") not in (True, 1, "TRUE"):
            continue
        p = {"_row": sheet_row}
        ok = True
        for col in RATING_COLS:
            v = rec.get(col)
            if col in META:
                p[col] = v
            else:
                nv = num(v)
                p[col] = nv
                if nv is None and col not in OPTIONAL:
                    ok = False
        if not ok:
            continue
        try:
            out = compute(p, dp, filt, park_aa)
        except Exception:
            continue
        n += 1
        for col in CHECK_COLS:
            mine = out.get(col)
            sheet = num(rec.get(col))
            if mine is None or sheet is None:
                continue
            d = abs(mine - sheet)
            diffs[col] = max(diffs[col], d)
            counts[col] += 1
            if worst[col] is None or d > worst[col][0]:
                worst[col] = (d, rec.get("Name"), sheet, mine)
    wb.close()
    print(f"Validated {n} eligible pitchers in {league}  (park AA={park_aa})")
    print(f"{'column':14} {'n':>5} {'maxAbsDiff':>14}   worst-case (name: sheet vs mine)")
    worst_overall = 0.0
    for col in CHECK_COLS:
        w = worst[col]
        wt = f"{w[1]}: {w[2]:.6g} vs {w[3]:.6g}" if w else "-"
        flag = "  <-- MISMATCH" if diffs[col] > 1e-9 else ""
        worst_overall = max(worst_overall, diffs[col])
        print(f"{col:16} {counts[col]:5} {diffs[col]:14.6e}   {wt}{flag}")
    print(f"\nWORST OVERALL maxAbsDiff across all columns: {worst_overall:.6e}")
    print("PASS" if worst_overall < 1e-9 else "FAIL (see mismatches above)")


if __name__ == "__main__":
    main()
