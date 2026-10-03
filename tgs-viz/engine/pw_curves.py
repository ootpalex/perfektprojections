"""
pw_curves.py - Phase 2 row 5: a THIRD rating->rate curve family (OOTP-27
continuous multi-knot piecewise) and the three-way real-season gate.

GATED. Nothing here is read by the live pipeline. It is used only when
`scurve_fit.py --pw` or `promote_scurves.py --three-way` is passed, and by
curve_bakeoff.py (a report). With those flags off every engine output, every
calib file and every promote_scurves choice is unchanged (tools/tests/
test_pw_curves.py proves it against the committed JSONs).

What the family is (ootp-dashboard model/src/data_points.py Section 1b,
model/src/utils.py piecewise_delta, transcribed here as literals):
    rate(r) = offset + cum(r) - cum(anchor)
    cum(v)  = s0*v + sum_i (s_{i+1} - s_i) * max(v - knot_i, 0)
slopes are per displayed rating point; knots are OFFSETS from the league's
average rating (relative=True: SP/RP STU/CON/HRR/PBABIP, hitter EYE/POW/K/BA/
GAP) or absolute displayed values (relative=False: SPE). The curve is
continuous by construction. Clamped ends (slope 0) are exact floors/ceilings.

Provenance of the numbers (all tagged in docs/phase2/curves.md):
  * knots/slopes: designed test-league sims ("H-pool"), OOTP 27 engine; the
    sp_hrr / rp_hrr rows keep the older "C-pool" lock (the real-SSB referee
    rejected the H-pool candidates). Transcribed from ootp-dashboard
    8c6337a model/src/data_points.py DEFAULT_{HITTING,PITCHING}_REG_COEFFS_27.
  * They are OOTP-27 constants. TGS is OOTP 26: the family must not be offered
    to a 26 league (guarded in `LEAGUES_27`).

Transport to the live frame is the same one the two-line gets: ONE level
offset = league actual rate - the curve's weighted mean over the live
population. (The S-curve additionally gets its live-fitted drift (a, c) and
elite hinge; `with_drift` below gives the piecewise the same two parameters as
a labelled diagnostic.)

stdlib only; no pandas.
"""
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scurve_fit as SF  # noqa: E402  (live_gate machinery, loaders, SUPPORT)
import metadata_calibrate as M  # noqa: E402
import pitchers as P  # noqa: E402  (_pw_rate: the ONE evaluator the engine uses)

# Leagues whose engine is OOTP 27 (ootp/leagues.json "game"; BLM "27", TGS "26").
LEAGUES_27 = ("BLM",)
STUFF_CAP_27 = 88.0   # decision D24 (displayed Stuff caps at 88); STU block only
PITCH_BLOCKS = ("SO", "uBB", "HR", "HHR")
HIT_BLOCKS = ("uBB", "HR", "SO", "HHR", "XBH", "T3B")


def _rel(abs_knots, calib_avg):
    """Absolute display knots -> offsets from the calibration average."""
    return tuple(k - calib_avg for k in abs_knots)


# ---------------------------------------------------------------- family specs
# block -> dict(knots (offsets if relative else absolute), slopes, relative,
#               clamp_lo, clamp_hi, x = rating column(s), cap)
PIT_PW = {
    "SP": {
        "SO":  dict(knots=_rel((32.0, 42.0, 78.0), 56.605),
                    slopes=(0.01315, 0.00603, 0.00339, 0.01078), relative=True, cap=STUFF_CAP_27),
        "uBB": dict(knots=_rel((22.0, 42.0, 50.0, 78.0), 57.313),
                    slopes=(-0.00573, -0.00475, -0.00291, -0.00125, -0.00182), relative=True),
        "HR":  dict(knots=_rel((30.0, 39.0, 52.0, 65.0), 54.157),
                    slopes=(-0.00481, -0.00296, -0.00159, -0.00087, -0.00048), relative=True),
        "HHR": dict(knots=(), slopes=(-0.00066,), relative=True),
    },
    "RP": {
        "SO":  dict(knots=_rel((41.0, 78.0), 57.217),
                    slopes=(0.00622, 0.00339, 0.01025), relative=True, cap=STUFF_CAP_27),
        "uBB": dict(knots=_rel((23.0, 42.0, 50.0, 78.0), 56.308),
                    slopes=(-0.00549, -0.00472, -0.00290, -0.00123, -0.00175), relative=True),
        "HR":  dict(knots=_rel((31.0, 40.0, 53.0, 67.0), 53.866),
                    slopes=(-0.00449, -0.00259, -0.00159, -0.00081, -0.00037), relative=True),
        "HHR": dict(knots=(), slopes=(-0.00057,), relative=True),
    },
}

# hitter block -> (spec, rating column vR, rating column vL)
HIT_PW = {
    "uBB": (dict(knots=_rel((26.0, 49.0, 79.0), 56.038),
                 slopes=(0.00056, 0.00256, 0.00176, 0.00579), relative=True), "EYE vR", "EYE vL"),
    "HR":  (dict(knots=_rel((36.0, 79.0), 57.686),
                 slopes=(0.00042, 0.00116, 0.00400), relative=True), "POW vR", "POW vL"),
    "SO":  (dict(knots=_rel((15.0, 44.0), 56.316),
                 slopes=(0.0, -0.00897, -0.00483), relative=True, clamp_lo=True), "K vR", "K vL"),
    "HHR": (dict(knots=_rel((22.0, 43.0, 78.0), 57.407),
                 slopes=(0.00422, 0.00282, 0.00192, 0.00415), relative=True), "BA vR", "BA vL"),
    "XBH": (dict(knots=_rel((30.0, 49.0, 79.0), 57.508),
                 slopes=(0.00389, 0.00584, 0.00237, 0.00893), relative=True), "GAP vR", "GAP vL"),
    "T3B": (dict(knots=(34.0, 50.0),
                 slopes=(0.0, 0.00312, 0.00281), relative=False, clamp_lo=True), "SPE", "SPE"),
}


def pw_params(spec, anchor, offset=0.0):
    """Engine-side parameter dict for one block (what scurves.json would carry).
    Knots are made ABSOLUTE here (anchor + offset for relative blocks) so the
    engine evaluator needs no league average."""
    knots = [anchor + k for k in spec["knots"]] if spec["relative"] else list(spec["knots"])
    return {"type": "piecewise", "knots": knots, "slopes": list(spec["slopes"]),
            "clamp_lo": bool(spec.get("clamp_lo")), "clamp_hi": bool(spec.get("clamp_hi")),
            "cap": spec.get("cap"), "anchor": float(anchor), "offset": float(offset)}


def pw_value(c, r):
    """Evaluate a piecewise param dict (the engine's own evaluator)."""
    return P._pw_rate(c, r)


# ---------------------------------------------------------------- his curves, rebuilt from disk
def scurve_fn(c):
    """The S-curve of a scurves(-preview).json block, exactly as
    pitchers.statline.sc_rate evaluates it (level offset included)."""
    def f(r):
        lo, hi = c.get("support", (20.0, 80.0))
        rr = min(max(r, lo), hi)
        v = c["A"] + c["B"] / (1.0 + math.exp(-c["k"] * (rr - c["m"]))) + c["offset"]
        kn = c.get("knot")
        if kn:
            v += kn["s"] * max(0.0, min(r, kn["hi"]) - kn["r"])
        return v
    return f


def twoline_pitch_fn(dp, role, blk, tl_offset=0.0):
    """pitchers.twoline_rate (+ the block's level offset)."""
    return lambda r: P.twoline_rate(dp, role, blk, r) + tl_offset


_HIT_TWOLINE_CELLS = {   # block -> (anchor, slope_hi, int_hi, slope_lo, int_lo) Data Points cells
    "uBB": ("H2", "C3", "B3", "E3", "D3"),
    "HR":  ("H3", "C5", "B5", "E5", "D5"),
    "SO":  ("H4", "C7", "B7", "E7", "D7"),
    "HHR": ("H5", "C9", "B9", "E9", "D9"),
    "XBH": ("H6", "C11", "B11", "E11", "D11"),
    "T3B": ("H7", "C13", "B13", "E13", "D13"),
}


def twoline_hit_fn(dp, blk, tails=None):
    """hitters.compute's two-segment line for one block (no league constant,
    no park, no handedness - the gate is level-matched), plus the archive tail
    delta `tadj` when `tails` (hitter_tails.json) is given: the live pipeline
    runs it that way for BLM."""
    a, sh, ih, sl, il = (float(dp[k]) for k in _HIT_TWOLINE_CELLS[blk])
    import hitters as H
    tb = ((tails or {}).get("blocks") or {}).get(blk)

    def f(r):
        v = (r - a) * sh + ih if r >= 50 else (r - a) * sl + il
        if tb and tb.get("knots"):
            v += H._interp_knots(tb["knots"], r)
        return v
    return f


# ---------------------------------------------------------------- hitting live population
HIT_STAT_COLS = ("PA", "AB", "H", "1B", "2B", "3B", "HR", "BB", "IBB", "HP", "SF", "SH", "SO")


def hit_rate(s, blk):
    """(season rate, denominator) of one hitting block from a Hitting_Data row,
    with the denominators hitters.compute multiplies back by:
      uBB  (BB-IBB) / (PA-HP)
      HR   HR / (PA-HP-uBB)          SO  SO / (PA-HP-uBB)
      HHR  (H-HR) / (PA-HP-uBB-HR-SO)
      XBH  (2B+3B) / (H-HR)          T3B 3B / (2B+3B)"""
    ubb = s["BB"] - s["IBB"]
    if blk == "uBB":
        den, num = s["PA"] - s["HP"], ubb
    elif blk == "HR":
        den, num = s["PA"] - s["HP"] - ubb, s["HR"]
    elif blk == "SO":
        den, num = s["PA"] - s["HP"] - ubb, s["SO"]
    elif blk == "HHR":
        den, num = s["PA"] - s["HP"] - ubb - s["HR"] - s["SO"], s["H"] - s["HR"]
    elif blk == "XBH":
        den, num = s["H"] - s["HR"], s["2B"] + s["3B"]
    else:  # T3B
        den, num = s["2B"] + s["3B"], s["3B"]
    return (num / den if den > 0 else None), den


def pit_rate(s, blk):
    return SF._live_rate(s, blk)


def _mrole(stat_rows, vr_rows, vl_rows, cols, wcol, rate_fn, blocks, id_filter=None):
    """Build the live_gate-shaped dict {per_id, vr, vl, share, rates} from loader rows."""
    per_id, T = {}, defaultdict(float)
    for r in stat_rows:
        pid = SF._num(r.get("ID"))
        if pid is None:
            continue
        rec = {c: (SF._num(r.get(c)) or 0.0) for c in cols}
        per_id[pid] = rec
        for c in cols:
            T[c] += rec[c]

    def tab(rows):
        out = []
        for r in rows:
            vid, w = SF._num(r.get("ID")), SF._num(r.get(wcol))
            if vid is None or w is None or (id_filter is not None and vid not in id_filter):
                continue
            rec = {h: SF._num(v) for h, v in r.items()}
            rec["ID"], rec[wcol] = vid, w
            out.append(rec)
        return out
    vr, vl = tab(vr_rows), tab(vl_rows)
    # live_gate/live_mean weight pitchers by "BF"; hitters carry "PA" - alias it
    for rec in vr + vl:
        rec["BF"] = rec[wcol]
    bf_vr, bf_vl = sum(x["BF"] for x in vr), sum(x["BF"] for x in vl)
    rates = {b: rate_fn(dict(T), b)[0] for b in blocks}
    return {"per_id": per_id, "vr": vr, "vl": vl, "share": bf_vr / (bf_vr + bf_vl),
            "rates": rates, "T": dict(T)}


def read_hitting_blm(d):
    """calib/<LG>/metadata_inputs Hitting_Data.csv + Batter_Ratings.csv (two side-by-side tables)."""
    vr, vl = M.load_vr_vl(os.path.join(d, "Batter_Ratings.csv"))
    return _mrole(M.load_single(os.path.join(d, "Hitting_Data.csv")), vr, vl,
                  HIT_STAT_COLS, "PA", hit_rate, HIT_BLOCKS)


def read_hitting_flat(d):
    """ootp-dashboard leagues/<L>/metadata/<year>/ layout: hitting_data.csv + batter_ratings_vr/vl.csv."""
    return _mrole(M.load_single(os.path.join(d, "hitting_data.csv")),
                  M.load_single(os.path.join(d, "batter_ratings_vr.csv")),
                  M.load_single(os.path.join(d, "batter_ratings_vl.csv")),
                  HIT_STAT_COLS, "PA", hit_rate, HIT_BLOCKS)


def read_pitching_flat(d):
    """ootp-dashboard flat layout -> {"SP": mrole, "RP": mrole}. The ratings files hold every
    pitcher (BF vs RHB / LHB), so each role's tables are cut to that role's Data-tab pitchers."""
    vr_rows = M.load_single(os.path.join(d, "pitcher_ratings_vr.csv"))
    vl_rows = M.load_single(os.path.join(d, "pitcher_ratings_vl.csv"))
    out = {}
    for role, fn in (("SP", "sp_data.csv"), ("RP", "rp_data.csv")):
        stats = M.load_single(os.path.join(d, fn))
        ids = {SF._num(r.get("ID")) for r in stats}
        m = _mrole(stats, vr_rows, vl_rows, SF.STAT_COLS, "BF", pit_rate, PITCH_BLOCKS, id_filter=ids)
        m["rates"] = SF._league_rates(m["T"])
        out[role] = m
    return out


# ---------------------------------------------------------------- piecewise on a live population
def _wmean(fn, recs, col, cap=None):
    """BF/PA-weighted mean of fn(rating) over a ratings table (no support clamp)."""
    sw = swy = 0.0
    for x in recs:
        r = x.get(col)
        if not isinstance(r, (int, float)):
            continue
        r = float(r)
        if cap is not None:
            r = min(r, cap)
        w = float(x["BF"])
        sw += w
        swy += w * fn(r)
    return swy / sw


def live_anchor(mrole, xcol, xcol_vl, cap=None):
    """League average rating of the live population: weighted mean of each side, blended by the
    matchup share - ours `_compute_rating_averages_*` (weights BF or PA)."""
    s = mrole["share"]
    ident = lambda r: r
    return (s * _wmean(ident, mrole["vr"], xcol, cap) + (1 - s) * _wmean(ident, mrole["vl"], xcol_vl, cap))


def build_pw(mrole, spec, xcol, xcol_vl, league_rate, anchor=None):
    """Transported piecewise params for one block on one live population: anchor = the
    population's average rating, offset = league_rate - E_live[delta] (same exact-mean step the
    two-line and S-curve get)."""
    cap = spec.get("cap")
    a = live_anchor(mrole, xcol, xcol_vl, cap) if anchor is None else anchor
    c0 = pw_params(spec, a, 0.0)
    s = mrole["share"]
    e = (s * _wmean(lambda r: pw_value(c0, r), mrole["vr"], xcol, cap)
         + (1 - s) * _wmean(lambda r: pw_value(c0, r), mrole["vl"], xcol_vl, cap))
    return pw_params(spec, a, league_rate - e)


def monotone_scan(fn, direction, lo=20.0, hi=80.0):
    """(ok, max |step| per 0.1 pt) - the same scan scurve_fit.py runs for the S-curve."""
    bad, worst, prev, r = 0, 0.0, fn(lo), lo + 0.1
    while r <= hi + 1e-9:
        cur = fn(r)
        if (cur - prev) * direction < -1e-12:
            bad += 1
        worst = max(worst, abs(cur - prev))
        prev, r = cur, r + 0.1
    return bad == 0, worst


def with_drift(f, pts):
    """DIAGNOSTIC: give a curve the S-curve's two live-fitted parameters (rating-scale drift a, c
    from scurve_fit.calibrate_scale, fitted on the same live points the gate scores).
    Returns (curve, a, c)."""
    a, c, _, _ = SF.calibrate_scale(f, pts)
    lo, hi = SF.SUPPORT

    def g(r):
        return f(min(max(a * (min(max(r, lo), hi) - 50.0) + 50.0 + c, lo), hi))
    return g, a, c


# ---------------------------------------------------------------- the N-curve gate
def gate_points(mrole, blk, xcol, xcol_vl, rate_fn, curves):
    """Per-player points of live_gate for any set of curves:
    [(vR rating, season rate, weight, {name: share-blended prediction})]."""
    share = mrole["share"]
    rat_vr = {x["ID"]: x.get(xcol) for x in mrole["vr"]}
    rat_vl = {x["ID"]: x.get(xcol_vl) for x in mrole["vl"]}
    pts = []
    for pid, s in mrole["per_id"].items():
        rv, rl = rat_vr.get(pid), rat_vl.get(pid)
        if rv is None and rl is None:
            continue
        rv = float(rv if rv is not None else rl)
        rl = float(rl if rl is not None else rv)
        y, den = rate_fn(s, blk)
        if den <= 0:
            continue
        pts.append((rv, y, den, {n: share * f(rv) + (1 - share) * f(rl) for n, f in curves.items()}))
    return pts


def gate_from_points(pts, names):
    """live_gate's arithmetic on gate_points output, for any number of curves."""
    W = sum(w for _, _, w, _ in pts)
    if W <= 0:
        return None
    bias = {n: sum(w * (p[n] - y) for _, y, w, p in pts) / W for n in names}
    b = {}
    for r, y, w, p in pts:
        rung = round(r / 5) * 5
        if not (SF.SUPPORT[0] <= rung <= SF.SUPPORT[1]):
            continue
        a = b.setdefault(rung, {"n": 0, "w": 0.0, "wy": 0.0, **{n: 0.0 for n in names}})
        a["n"] += 1
        a["w"] += w
        a["wy"] += w * y
        for n in names:
            a[n] += w * (p[n] - bias[n])
    wb = sum(a["w"] for a in b.values())
    rmse = {n: math.sqrt(sum(a["w"] * (a["wy"] / a["w"] - a[n] / a["w"]) ** 2 for a in b.values()) / wb)
            for n in names}
    return {"n": len(pts), "w": W, "bias": bias, "rmse": rmse,
            "buckets": {str(int(r)): {"n": a["n"], "w": a["w"], "emp": a["wy"] / a["w"],
                                      **{n: a[n] / a["w"] for n in names}}
                        for r, a in sorted(b.items())}}


def live_gate_n(mrole, blk, xcol, xcol_vl, curves, rate_fn=pit_rate):
    """N-curve live_gate. With curves {"sigmoid": f, "twoline": g} it returns the numbers
    scurve_fit.live_gate returns (checked by test_pw_curves)."""
    return gate_from_points(gate_points(mrole, blk, xcol, xcol_vl, rate_fn, curves), list(curves))


def noise_floor(gate):
    """Binomial floor on the gate metric: bucket means are sampled, so even the true curve scores
    sqrt(sum_b p_b(1-p_b) / W_b-total) where W is the summed denominator (a LOWER bound - pitchers'
    true talent beyond ratings adds overdispersion)."""
    bk = gate["buckets"].values()
    wb = sum(a["w"] for a in bk)
    return math.sqrt(sum(a["emp"] * (1 - a["emp"]) for a in bk) / wb)


# ---------------------------------------------------------------- scurve_fit.py hook (gated)
def preview_block(mrole, role, blk, xcol, xcol_vl, f_sig, f_two, gate2=None):
    """The `--pw` addition to one scurve_fit.py preview block: the transported piecewise params,
    its monotone scan, and the three-way live gate. f_sig / f_two are the S-curve and two-line
    exactly as scurve_fit.main priced them for the gate (level offsets included). Returns None for a
    block the family has no row for. `gate2` (the two-curve gate main() already computed) is
    cross-checked, not trusted: the returned dict records the max difference."""
    spec = PIT_PW[role][blk]
    c = build_pw(mrole, spec, xcol, xcol_vl, mrole["rates"][blk])
    f_pw = lambda r: pw_value(c, r)
    direction = SF.BLOCKS[blk][2]
    mono, step = monotone_scan(f_pw, direction)
    g3 = live_gate_n(mrole, blk, xcol, xcol_vl,
                     {"sigmoid": f_sig, "twoline": f_two, "piecewise": f_pw})
    chk = None
    if gate2 and g3:
        chk = max(abs(g3["rmse"]["sigmoid"] - gate2["rmse_sigmoid"]),
                  abs(g3["rmse"]["twoline"] - gate2["rmse_twoline"]))
    out = dict(c)
    out.update({"x_vR": xcol, "x_vL": xcol_vl, "direction": direction, "league_rate": mrole["rates"][blk],
                "monotone_ok": mono, "max_step_0p1": step,
                "live_gate3": g3, "gate2_max_abs_diff": chk})
    return out
