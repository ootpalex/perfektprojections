"""Phase 2 row 6 audit harness: baserunning (SBA%, SB%, UBR) by rating bucket, real vs the fork's
engine vs the OOTP-dashboard pipeline ("ours").  READ-ONLY: writes nothing, no network.

  <repo>/.venv/bin/python docs/phase2/baserunning_audit.py

Reads: this worktree (engine/calib/BLM/metadata_inputs, The Sheets BLM/TGS workbooks, public/data/BLM/hitters.json),
the main checkout's gitignored data (tgs-viz/backtest/actuals, ratings_history.db) and the ootp-dashboard
checkout (leagues/SSB/metadata/2043, model/src).  Override the two external roots with env vars
PP_MAIN and OOTP_DASH.  Everything printed in docs/phase2/baserunning.md comes from this script.
"""
import os, sys, json, sqlite3
sys.dont_write_bytecode = True
import numpy as np, pandas as pd

WT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "/tgs-viz"
MAIN = os.environ.get("PP_MAIN", "/Users/alex/Projects/ootp/perfektprojections") + "/tgs-viz"
OURS = os.environ.get("OOTP_DASH", "/Users/alex/Projects/ootp/dashboard/ootp-dashboard")
sys.path.insert(0, WT + "/engine"); sys.path.insert(0, OURS + "/model")
import hitters as H                                            # his engine (read-only use: scan_consts)
import dataclasses
from src.data_points import DEFAULT_HITTING_REG_COEFFS_27 as R27, HittingRegressionCoeffs
from src.utils import piecewise_delta, baserunning_poly
from src.aggregators.hit_aggregator import (_aggregate_hitting, _compute_matchup_splits_from_ratings,
    _compute_rating_averages_hitting, _compute_ste_pa_distribution)
from src.aggregators._shared import _compute_woba_from_aggregates
R26 = HittingRegressionCoeffs()

# ----------------------------------------------------------------------------- data
def blm2058():
    d = WT + "/engine/calib/BLM/metadata_inputs"
    h = pd.read_csv(f"{d}/Hitting_Data.csv", skiprows=1, encoding="utf-8-sig")
    r = pd.read_csv(f"{d}/Batter_Ratings.csv", skiprows=1, encoding="utf-8-sig")
    vr = r.iloc[:, :19].copy(); vr.columns = [c.split(".")[0] for c in vr.columns]
    vl = r.iloc[:, 22:41].copy(); vl.columns = [c.split(".")[0] for c in vl.columns]
    return h, vr.dropna(subset=["ID"]), vl.dropna(subset=["ID"])
def ssb2043():
    d = OURS + "/leagues/SSB/metadata/2043"
    return (pd.read_csv(f"{d}/hitting_data.csv"), pd.read_csv(f"{d}/batter_ratings_vr.csv"),
            pd.read_csv(f"{d}/batter_ratings_vl.csv"))
def actuals(lg, year, league_id):
    a = pd.read_csv(f"{MAIN}/backtest/actuals/{lg}/{year}/batting.csv")
    m = a[(a.league_id == league_id) & (a.level_id == 1) & (a.split_id == 1)]
    return m.groupby("player_id", as_index=False).sum(numeric_only=True)
def db_ratings(pull):
    c = sqlite3.connect(f"file:{MAIN}/backtest/ratings_history.db?mode=ro", uri=True)
    d = pd.read_sql(f"select player_id,c_SPE SPE,c_STE STE,c_RUN RUN from ratings where pull_id={pull}", c)
    d["player_id"] = d.player_id.astype(int); return d
def norm(h):
    return h.rename(columns={"PA": "pa", "AB": "ab", "H": "h", "2B": "d", "3B": "t", "HR": "hr", "BB": "bb",
                             "IBB": "ibb", "HP": "hp", "SB": "sb", "CS": "cs", "UBR": "ubr", "SF": "sf", "SO": "k"})
def prep(h, vr):
    return norm(h).merge(vr[["ID", "SPE", "STE", "RUN", "B"]], on="ID", how="left")
def add(df):
    df["one"] = df.h - df.d - df.t - df.hr; df["opp"] = df.one + df.bb + df.hp; df["att"] = df.sb + df.cs
    df["bo"] = df.opp * 3 + df.d * 2 + df.t * 2 - df.sb - df.cs * 3        # calibrate.py:174 definition
    return df

# ----------------------------------------------------------------------------- his engine, replicated
def load_dp(league):
    dp, filt, park = H.scan_consts(f"{WT}/../The Sheets {league}/The Sheet Hitters.xlsx"); return dp
class His:
    """hitters.py:259-300 (sbat / SB% / ubr) as pure functions of (rating, workbook constants)."""
    def __init__(self, dp, cap): self.dp, self.cap = dp, cap
    def g(self, k): return float(self.dp[k])
    def g0(self, k): return float(self.dp[k]) if self.dp.get(k) not in (None, "") else 0.0
    def cub(self, x, anchor, row): return sum((x - anchor) ** k * self.g0(c + str(row)) for k, c in zip(range(4), "BCDE"))
    def sba(self, ste, c41=None, h8=None):
        c41 = self.g("C41") if c41 is None else c41; h8 = self.g("H8") if h8 is None else h8
        return np.maximum(self.cub(np.minimum(ste, 80.0), h8, 15) + c41, 0.0)
    def sbpct(self, ste): return np.minimum(np.maximum(self.cub(np.minimum(ste, 80.0), self.g("H8"), 17) + self.g("C39"), 0.0), self.cap)
    def ubr(self, run, sign=+1): return self.cub(np.minimum(run, 80.0), self.g("H9"), 19) + sign * self.g("C40")

# ----------------------------------------------------------------------------- ours
def our_lg(h, vr, vl):
    agg = _aggregate_hitting(h); w = _compute_woba_from_aggregates(agg)
    sp = _compute_matchup_splits_from_ratings(vr, vl); av = _compute_rating_averages_hitting(vr, vl, sp["ovr_vr"])
    dist = _compute_ste_pa_distribution(vr, vl, sp["ovr_vr"])
    e_pw = sum(wt * float(piecewise_delta(float(v), av["ste"], R27.sba)) for v, wt in dist) / sum(wt for _, wt in dist)
    return dict(sba=w["sba_rate"], sbp=w["sb_pct"], ubr=w["ubr_rate"], avg_ste=av["ste"], avg_run=av["run"], adaptive_c0=-e_pw)
def ours_sba(ste, lg, mode="adaptive"):
    co = dataclasses.replace(R27.sba, c0=lg["adaptive_c0"] if mode == "adaptive" else R27.sba.c0)
    return (baserunning_poly(pd.Series(np.asarray(ste, float)), lg["avg_ste"], co) + lg["sba"]).values   # hitters.py:337-338
def ours_sbpct(ste, lg):
    return (baserunning_poly(pd.Series(np.asarray(ste, float)), lg["avg_ste"], R27.sb_pct) + lg["sbp"]).clip(0, 1).values  # :333-334
def ours_ubr(run, lg):
    return (baserunning_poly(pd.Series(np.asarray(run, float)), lg["avg_run"], R27.ubr) - lg["ubr"]).values              # :341-342

def boot(df, fn, B=400, seed=1):
    rng = np.random.default_rng(seed); n = len(df)
    return float(np.nanstd([fn(df.iloc[rng.choice(n, n)]) for _ in range(B)]))

# ----------------------------------------------------------------------------- reports
def bucket_report(df, lg, his, label):
    d = df.dropna(subset=["STE", "RUN"]).reset_index(drop=True); ste = d.STE.values.astype(float); run = d.RUN.values.astype(float)
    d["p_sba_his"] = his.sba(ste); d["p_sba_ours"] = np.maximum(ours_sba(ste, lg), 0); d["p_sba_canon"] = np.maximum(ours_sba(ste, lg, "canon"), 0)
    d["p_sbp_his"] = his.sbpct(ste); d["p_sbp_ours"] = ours_sbpct(ste, lg)
    forms = {"his +C40 (B9)": his.ubr(run, +1), "cubic only": his.ubr(run, 0), "cubic -C40 (pre-B9 / ours form)": his.ubr(run, -1), "ours code": ours_ubr(run, lg)}
    wa = np.average
    print(f"\n=== {label}: n={len(d)}/{len(df)} matched, opp={d.opp.sum():.0f}, attempts={d.att.sum():.0f}")
    print(f"our adaptive c0 {lg['adaptive_c0']:+.5f} (canonical {R27.sba.c0:+.5f}); lg.sba {lg['sba']:.5f} lg.sb% {lg['sbp']:.5f} lg.ubr {lg['ubr']:+.6f}; his C41 {his.g('C41'):.5f} C40 {his.g('C40'):+.6f} C39 {his.g('C39'):.5f}")
    print(f"SBA%  league: real {d.att.sum()/d.opp.sum():.4f} | his {wa(d.p_sba_his,weights=d.opp):.4f} | ours-adaptive {wa(d.p_sba_ours,weights=d.opp):.4f} | ours-canonical {wa(d.p_sba_canon,weights=d.opp):.4f}")
    print(f"SB%   league: real {d.sb.sum()/d.att.sum():.4f} | his {wa(d.p_sbp_his,weights=d.att):.4f} | ours {wa(d.p_sbp_ours,weights=d.att):.4f}")
    d["sb_b"] = pd.cut(d.STE, [0, 35, 45, 55, 65, 75, 100], right=False)
    print("STE bucket |  n |  opp | att | SBA% real (boot SE) | his | ours-adaptive | ours-canonical | SB% real | his | ours")
    for b, s in d.groupby("sb_b", observed=True):
        se = boot(s, lambda x: x.att.sum() / x.opp.sum())
        print(f"{str(b):10s} {len(s):3d} {s.opp.sum():6.0f} {s.att.sum():5.0f} | {s.att.sum()/s.opp.sum():.4f} ({se:.4f}) | {wa(s.p_sba_his,weights=s.opp):.4f} | {wa(s.p_sba_ours,weights=s.opp):.4f} | {wa(s.p_sba_canon,weights=s.opp):.4f} | "
              f"{s.sb.sum()/max(s.att.sum(),1):.3f} | {wa(s.p_sbp_his,weights=s.att):.3f} | {wa(s.p_sbp_ours,weights=s.att):.3f}")
    d["ru_b"] = pd.cut(d.RUN, [0, 40, 50, 60, 70, 100], right=False)
    print("RUN bucket |  n | base_opp | UBR/base_opp x1e3: real (boot SE) | his +C40 | cubic only | cubic -C40 | ours code")
    for b, s in d.groupby("ru_b", observed=True):
        i = s.index; se = boot(s, lambda x: x.ubr.sum() / x.bo.sum()) * 1e3
        f = lambda k: wa(forms[k][i], weights=s.bo) * 1e3
        print(f"{str(b):10s} {len(s):3d} {s.bo.sum():8.0f} | {s.ubr.sum()/s.bo.sum()*1e3:+.3f} ({se:.3f}) | {f('his +C40 (B9)'):+.3f} | {f('cubic only'):+.3f} | {f('cubic -C40 (pre-B9 / ours form)'):+.3f} | {f('ours code'):+.3f}")
    real = d.ubr.sum(); pa = d.pa.sum()
    print(f"UBR league mean, runs per 600 PA: real {real/pa*600:+.3f} | " + " | ".join(f"{k} {(np.sum(v*d.bo.values))/pa*600:+.3f}" for k, v in forms.items()))
    own = (his.ubr(run, 0) + lg["ubr"]) * d.bo.values
    print(f"  his cubic with THIS league's own pooled UBR rate ({lg['ubr']:+.6f}) instead of the workbook C40: {own.sum()/pa*600:+.3f} runs/600PA")
    # mean-preservation of the SBA level and the attempts error by bucket
    tgt = d.att.sum() / d.opp.sum()
    line = his.g("B15") + his.g("C15") * (np.minimum(ste, 80) - his.g("H8")); lo, hi = -0.5, 0.5
    for _ in range(80):
        mid = (lo + hi) / 2; lo, hi = (lo, mid) if np.average(np.maximum(line + mid, 0), weights=d.opp) > tgt else (mid, hi)
    d["p_mp"] = np.maximum(line + lo, 0)
    for nm, col in (("his as built", "p_sba_his"), ("ours adaptive", "p_sba_ours"), ("ours canonical", "p_sba_canon"), (f"his line, mean-preserving const {lo:+.4f}", "p_mp")):
        p = d[col] * d.opp; e = sum(abs((p[s.index]).sum() - s.att.sum()) for _, s in d.groupby("sb_b", observed=True)) / d.att.sum()
        print(f"  attempts error  {nm:42s} league {100*(p.sum()/d.att.sum()-1):+6.1f}% | sum|bucket err|/attempts {100*e:5.1f}%")
    H35, H36 = his.g("H35"), his.g("H36")
    print("  wSB runs/600PA by STE bucket (his H35/H36 weights for both): real | his | ours-adaptive")
    for b, s in d.groupby("sb_b", observed=True):
        i = s.index
        def w(att_hat, sbp): return np.maximum(att_hat * sbp * 0.2 + att_hat * (1 - sbp) * H35, 0).sum() - H36 * s.opp.sum()
        real_w = (0.2 * s.sb + H35 * s.cs).sum() - H36 * s.opp.sum(); k = 600 / s.pa.sum()
        print(f"  {str(b):10s} real {real_w*k:+6.2f} | his {w(d.p_sba_his[i]*s.opp, d.p_sbp_his[i])*k:+6.2f} | ours {w(d.p_sba_ours[i]*s.opp, d.p_sbp_ours[i])*k:+6.2f}")
    return d

def slope_hc1(df, xcol):
    d = df.dropna(subset=[xcol]); d = d[d.bo > 0]; y = (d.ubr / d.bo).values; w = d.bo.values; x = d[xcol].values.astype(float)
    X = np.c_[np.ones(len(d)), x - np.average(x, weights=w)]; sw = np.sqrt(w); b = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
    res = y - X @ b; Xw = X * w[:, None]; inv = np.linalg.inv(X.T @ Xw); meat = (Xw * res[:, None]).T @ (Xw * res[:, None])
    cov = inv @ meat @ inv * len(d) / (len(d) - 2); return b, np.sqrt(np.diag(cov))

def main():
    dpB, dpT = load_dp("BLM"), load_dp("TGS")
    hisB, hisT = His(dpB, 0.888), His(dpT, 0.88)
    print("BLM workbook consts: H8 %.4f H9 %.4f C39 %.5f C40 %+.6f C41 %.5f | B15 %.5f C15 %.5f | B17 %.5f C17 %.5f | B19 %.3e C19 %.3e" % tuple(
        hisB.g(k) for k in ("H8", "H9", "C39", "C40", "C41", "B15", "C15", "B17", "C17", "B19", "C19")))
    # F. replica exactness vs the committed BLM hitters.json (6545 rows)
    js = json.load(open(WT + "/public/data/BLM/hitters.json")); mx = 0.0
    for r in js:
        if r.get("UBR vR") is None or r.get("STE") in (None, ""): continue
        ste, run = float(r["STE"]), float(r["RUN"]); S, u, B, D, T = r["1B vR"], r["uBB vR"], r["HBP vR"], r["2B vR"], r["3B vR"]
        sp = float(hisB.sbpct(ste)); at = max(float(hisB.sba(ste)) * (S + u + B), 0.0); sb = sp * at; cs = at - sb
        wp = max(sb * 0.2 + cs * hisB.g("H35"), 0.0) - hisB.g("H36") * (S + u + B)
        ub = (hisB.ubr(run, +1)) * ((u + S + B) * 3 + D * 2 + T - (cs * 3 - sb if wp > 0 else 0))
        mx = max(mx, abs(sp - r["SB%"]), abs(wp - r["wSB vR"]), abs(ub - r["UBR vR"]))
    print(f"replica vs hitters.json (SB%, wSB vR, UBR vR): max abs diff {mx:.3e} over {len(js)} rows")
    # A-C. BLM 2058 and SSB 2043 (stats and ratings from the same pull)
    out = {}
    for lab, f in (("BLM 2058 Hitting_Data x Batter_Ratings", blm2058), ("SSB 2043 hitting_data x batter_ratings", ssb2043)):
        h, vr, vl = f(); lg = our_lg(h, vr, vl); out[lab] = bucket_report(add(prep(h, vr)), lg, hisB, lab)
        b, se = slope_hc1(out[lab], "RUN"); print(f"  UBR/base_opp on RUN, WLS slope {b[1]:.3e} +-{se[1]:.1e} (HC1); fork C19 {hisB.g('C19'):.3e}, ours 27 {R27.ubr.slopes[0]:.3e}; "
              f"WLS level at the weighted-mean RUN {b[0]:+.3e} vs pooled UBR/base_opp {out[lab].ubr.sum()/out[lab].bo.sum():+.3e}")
    # BLM 2057 actuals x ratings pull 4 (2057-10-13); constants are 2058's, so this is out-of-sample in time
    h, vr, vl = blm2058(); lg = our_lg(h, vr, vl)
    d57 = add(actuals("BLM", 2057, 144).merge(db_ratings(4), on="player_id", how="left")); d57 = d57[d57.pa >= 1]
    bucket_report(d57, lg, hisB, "BLM 2057 actuals x ratings pull 4 (2058 constants)")
    b, se = slope_hc1(d57.dropna(subset=["RUN"]), "RUN"); print(f"  UBR/base_opp on RUN, WLS slope {b[1]:.3e} +-{se[1]:.1e}")
    # E. TGS 2044 (OOTP 26): the 26 linear path of ours and his TGS line
    aT = add(actuals("TGS", 2044, 100).merge(db_ratings(29), on="player_id", how="left")).dropna(subset=["STE", "RUN"]); aT = aT[aT.pa >= 1].reset_index(drop=True)
    ste = aT.STE.values.astype(float); tp = aT.att.sum() / aT.opp.sum(); avg = np.average(aT.STE, weights=aT.pa)
    o26 = np.maximum(R26.sba.c0 + R26.sba.c1 * (ste - avg) + tp, 0); o26_0 = np.maximum(R26.sba.c1 * (ste - avg) + tp, 0)
    aT["his"] = hisT.sba(ste); aT["o26"] = o26; aT["o26_0"] = o26_0; aT["b"] = pd.cut(aT.STE, [0, 35, 45, 55, 65, 75, 100], right=False)
    print(f"\n=== TGS 2044 (OOTP 26) x pull 29: n={len(aT)} opp={aT.opp.sum():.0f} att={aT.att.sum():.0f}; SBA real {tp:.4f} | his {np.average(aT.his,weights=aT.opp):.4f} | ours26 canon {np.average(aT.o26,weights=aT.opp):.4f} | ours26 c0=0 {np.average(aT.o26_0,weights=aT.opp):.4f}; SB% real {aT.sb.sum()/aT.att.sum():.4f} his {np.average(hisT.sbpct(ste),weights=aT.att):.4f}")
    for b, s in aT.groupby("b", observed=True):
        print(f"{str(b):10s} n={len(s):3d} real {s.att.sum()/s.opp.sum():.4f} | his {np.average(s.his,weights=s.opp):.4f} | ours26 {np.average(s.o26,weights=s.opp):.4f} | ours26 c0=0 {np.average(s.o26_0,weights=s.opp):.4f}")
    run = aT.RUN.values.astype(float); lgubr = aT.ubr.sum() / aT.bo.sum(); avg_run = np.average(aT.RUN, weights=aT.pa)
    f26 = R26.ubr.c0 + R26.ubr.c1 * (run - avg_run) - lgubr
    print(f"  UBR/base_opp real {lgubr:+.6f} | his +C40 {np.average(hisT.ubr(run,+1),weights=aT.bo):+.6f} | cubic only {np.average(hisT.ubr(run,0),weights=aT.bo):+.6f} | cubic -C40 {np.average(hisT.ubr(run,-1),weights=aT.bo):+.6f} | ours26 {np.average(f26,weights=aT.bo):+.6f}")
    # D. does the additive C41 transport across run environments?
    dB = out["BLM 2058 Hitting_Data x Batter_Ratings"]; bp = dB.att.sum() / dB.opp.sum()
    def rep(lab, d, his, c41, h8):
        p = his.sba(d.STE.values.astype(float), c41, h8) * d.opp.values; dd = d.assign(p=p, b=pd.cut(d.STE, [0, 35, 45, 55, 65, 75, 100], right=False))
        e = sum(abs(s.p.sum() - s.att.sum()) for _, s in dd.groupby("b", observed=True)) / d.att.sum()
        print(f"  {lab:70s} league {100*(p.sum()/d.att.sum()-1):+6.1f}% | bucket {100*e:5.1f}%")
    print(f"\nC41 transport test: TGS 2044 pooled {tp:.4f} is {100*(tp/bp-1):.1f}% hotter than BLM 2058 {bp:.4f}")
    rep("TGS data, TGS line + TGS workbook C41", aT, hisT, hisT.g("C41"), hisT.g("H8"))
    rep("TGS data, BLM line + TGS pooled rate + TGS H8", aT, hisB, tp, hisT.g("H8"))
    rep("BLM data, BLM line + BLM workbook C41", dB, hisB, hisB.g("C41"), hisB.g("H8"))
    rep("BLM data, TGS line + BLM pooled rate + BLM H8", dB, hisT, bp, hisB.g("H8"))

if __name__ == "__main__":
    main()
