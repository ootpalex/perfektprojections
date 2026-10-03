"""
pos_adj_audit.py - regenerates every number quoted in docs/phase2/pos_adj.md and
docs/phase2/best_pos.md. Read-only: it writes nothing, calls no network.

    <venv python> docs/phase2/pos_adj_audit.py > docs/phase2/pos_adj_audit_output.txt

Inputs (all on disk):
  fork     tgs-viz/engine/calib/BLM/metadata_inputs (BLM 2058), tgs-viz/backtest/actuals/BLM/2057,
           tgs-viz/public/data/{BLM,SSB}/hitters.json
  ours     $OOTP_DASHBOARD/leagues/SSB/metadata/{2041,2042,2043}   (default
           /Users/alex/Projects/ootp/dashboard/ootp-dashboard)
  career   $OOTP_ANALYSIS/data/*_career_*_stats.csv (optional; the dashboard's 42-year BLM and
           22-year SSB histories the frozen literals were fitted on; sections skip if absent)
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FORK = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(FORK, "tgs-viz", "engine")
sys.path.insert(0, ENGINE)
import metadata_calibrate as mc  # noqa: E402
import pos_adj_multiyear as M  # noqa: E402

DASH = os.environ.get("OOTP_DASHBOARD", "/Users/alex/Projects/ootp/dashboard/ootp-dashboard")
ANALYSIS = os.environ.get("OOTP_ANALYSIS", "/Users/alex/Projects/ootp/analysis/positional-adjustments")
RPW = 10.036                      # engine/calib/BLM/currency.json rpw (his WAA divisor H30)
N = M.NINE
BLM_IN = os.path.join(ENGINE, "calib", "BLM", "metadata_inputs")
ACT57 = os.path.join(FORK, "tgs-viz", "backtest", "actuals", "BLM", "2057")
SSB_MD = os.path.join(DASH, "leagues", "SSB", "metadata")

# the dashboard's frozen literals (model/src/data_points.py _FROZEN_POS_ADJ_BY_URL, runs per 162 games = 1458 IP)
OURS = {
    "BLM": {"C": 16.1, "1B": -13.1, "2B": -2.3, "3B": -0.7, "SS": 9.6, "LF": -8.4, "CF": 5.1, "RF": -6.2, "DH": -13.1},
    "SSB": {"C": 21.0, "1B": -12.4, "2B": -0.3, "3B": -1.0, "SS": 10.4, "LF": -12.0, "CF": 2.3, "RF": -8.1, "DH": -13.0},
}
# the dashboard's defensive-only spectra (app/src/utils/constants.js BLM_/SSB_DEF_SPECTRUM, C imputed) and RF arm thresholds
OPTB = {
    "BLM": {"C": 19.2, "1B": -10.1, "2B": -0.3, "3B": -0.5, "SS": 12.7, "LF": -6.8, "CF": 9.9, "RF": -4.9},
    "SSB": {"C": 22.5, "1B": -8.4, "2B": -0.0, "3B": -1.1, "SS": 11.9, "LF": -6.3, "CF": 9.4, "RF": -5.4},
}
ARM_THR = {"BLM": 55.2, "SSB": 54.6}
ORDER = ["C", "SS", "CF", "2B", "3B", "LF", "RF", "1B"]      # BESTPOS_FIELD_ORDER


def fmt(d, keys=N, w=7):
    return " ".join(f"{d[k]:{w}.2f}" for k in keys)


def hdr(t):
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def eng_from_1458(d):
    """Dashboard literal (runs per 1458 IP) -> engine basis (1200 IP, catcher 1000 IP)."""
    return {p: v * mc.STD_IP.get(p, 1200.0) / 1458.0 for p, v in d.items()}


def main():
    b58 = M.load_season(BLM_IN, 2058)
    b57 = M.load_season(ACT57, 2057, 144)
    ssb = {y: M.load_season(os.path.join(SSB_MD, str(y)), y) for y in (2041, 2042, 2043)}
    his_cells = json.load(open(os.path.join(ENGINE, "calib", "BLM", "metadata-latest.json")))["cells"]
    HIS = {p: his_cells[M.PCELL[p]] for p in N}

    hdr("1. VERIFY BOTH SETS AS THEY EXIST NOW")
    print("positions                  " + " ".join(f"{p:>7}" for p in N))
    print("ours BLM  (1458 IP basis)  " + fmt(OURS["BLM"]))
    print("ours SSB  (1458 IP basis)  " + fmt(OURS["SSB"]))
    print("his  BLM  metadata-latest  " + fmt(HIS))
    acc = M.offense_accumulate(b58)
    mine = M.his_pos_adj(acc)
    print("his  BLM  re-derived here  " + fmt(mine))
    print("  max |re-derived - metadata-latest| =", max(abs(mine[p] - HIS[p]) for p in N))
    ref = mc.compute_cells(BLM_IN)
    print("  max |compute_cells(metadata_inputs) - metadata-latest| =",
          max(abs(ref[M.PCELL[p]] - HIS[p]) for p in N), "(his own full recompute)")
    print("ours field-8 mean (C..RF), BLM:", round(sum(OURS["BLM"][p] for p in M.POSITIONS) / 8, 3),
          " SSB:", round(sum(OURS["SSB"][p] for p in M.POSITIONS) / 8, 3))
    print("his  field-8 mean (C..RF), BLM:", round(sum(HIS[p] for p in M.POSITIONS) / 8, 3))

    hdr("2. THE UNIT GAP: ours is runs per 162 games (1458 IP); his is per 1200 IP (catcher 1000 IP)")
    print("ours restated BLM (x1200/1458, C x1000/1458)  " + fmt(eng_from_1458(OURS["BLM"])))
    print("his P                                        " + fmt(HIS))
    gap_raw = {p: (OURS["BLM"][p] - HIS[p]) for p in N}
    gap_unit = {p: (eng_from_1458(OURS["BLM"])[p] - HIS[p]) for p in N}
    print("plan's gap, ours as published - his (runs)   " + fmt(gap_raw))
    print("gap after the unit restatement (runs)        " + fmt(gap_unit))
    print("gap removed by the unit alone (runs)         " + fmt({p: gap_raw[p] - gap_unit[p] for p in N}))

    hdr("3. WHAT ONE MORE PIECE AT A TIME DOES TO HIS BLM 2058 NUMBERS (engine basis, runs per std season)")
    off = M.offense_rates(acc)
    print("a. his P (offence only, 1 season, LF=RF pooled)  " + fmt(mine))
    print("b. LF and RF kept separate                       " + fmt(off))
    off1200 = dict(off)
    off1200["C"] = off["C"] * 1200 / mc.STD_IP["C"]
    fin, parts = M.blend(None, off1200, 0.5, "split")
    print("c. + centred (field-8 mean 0) + DH rule          " + fmt(M.to_engine_units(fin)))
    print("   (centring moves every position by", round(fin["1B"] - off1200["1B"], 3), "runs per 1200 IP; the C row is then rescaled to 1000 IP)")
    r58 = M.pos_adj_multiyear([b58])
    print("d. + 1/2 ZR switcher, 2058 only                  " + fmt(r58["spectrum_engine_units"]))
    r5758 = M.pos_adj_multiyear([b57, b58])
    print("e. + 2057 (H_def 5, H_off 2.5)                   " + fmt(r5758["spectrum_engine_units"]))
    print("   switcher n =", r58["n_switch_obs"], "(2058),", r5758["n_switch_obs"], "(2057+2058)")

    hdr("4. SWITCHER (defence half) EXACTNESS AND STANDARD ERRORS")
    for nm, sl in (("BLM 2058", [b58]), ("BLM 2057+2058", [b57, b58]),
                   ("SSB 2043", [ssb[2043]]), ("SSB 2041-2043", [ssb[y] for y in (2041, 2042, 2043)])):
        o = [M.switcher_obs(s) for s in sl]
        end = max(s["year"] for s in sl)
        d, n = M.solve_switcher(o, end)
        se = M.bootstrap_se(o, end, n_boot=500)
        print(f"{nm:<15} n={n:<5} def " + fmt(d, M.SEVEN) + "   (runs per 1200 IP, mean 0 over the 7)")
        print(f"{'':<15} {'':<7} SE  " + fmt(se, M.SEVEN))

    hdr("5. DOES THE ZR SWITCHER MOVE WHEN THE GAME ENGINE CHANGES (OOTP 26 -> 27)?")

    def sol(sl, end):
        o = [M.switcher_obs(s) for s in sl]
        d, n = M.solve_switcher(o, end, 1e9, 99)
        return d, M.bootstrap_se(o, end, 1e9, 99, n_boot=500), n

    def cmp(name, A, B):
        (da, sa, na), (db, sb, nb) = A, B
        z = []
        print(f"{name}  (n {na} -> {nb}); position: before +/- SE, after +/- SE, change, z")
        for p in M.SEVEN:
            dd = db[p] - da[p]
            s = (sa[p] ** 2 + sb[p] ** 2) ** 0.5
            z.append(dd / s)
            print(f"   {p}: {da[p]:6.2f}+/-{sa[p]:.2f}  {db[p]:6.2f}+/-{sb[p]:.2f}  {dd:6.2f}  z {dd / s:5.2f}")
        print(f"   sum of z^2 = {sum(x * x for x in z):.1f} (chi-square, 6 dof; 12.6 is the 5% line, 22.5 the 0.1% line)")

    cmp("BLM 2057 (OOTP 26) -> 2058 (27)", sol([b57], 2057), sol([b58], 2058))
    cmp("SSB 2041+2042 (26) -> 2043 (27)", sol([ssb[2041], ssb[2042]], 2043), sol([ssb[2043]], 2043))
    cmp("control, SSB 2041 -> 2042 (both 26)", sol([ssb[2041]], 2041), sol([ssb[2042]], 2042))
    print("single-season offence-only spectrum, SD across seasons (engine units):")
    for nm, sl in (("SSB 2041-43", [ssb[2041], ssb[2042], ssb[2043]]), ("BLM 2057-58", [b57, b58])):
        R = [M.offense_rates(M.offense_accumulate(s)) for s in sl]
        print(f"   {nm}: " + " ".join(f"{p}:{np.std([r[p] for r in R], ddof=1):.2f}" for p in N))

    hdr("6. QUIRKS OF HIS pos_adj_calc: do they matter? (max change in any position, runs)")
    for nm, s in (("BLM 2058", b58), ("BLM 2057", b57), ("SSB 2041", ssb[2041]), ("SSB 2043", ssb[2043])):
        a = M.offense_rates(M.offense_accumulate(s))
        b = M.offense_rates(M.offense_accumulate(s, rf_quirk=False))
        c = M.offense_rates(M.offense_accumulate(s, thirds_quirk=False))
        print(f"{nm}: RF branch quirk off -> {max(abs(b[p] - a[p]) for p in N):.4f}; "
              f"thirds-notation divisor fixed -> {max(abs(c[p] - a[p]) for p in N):.4f}")
    pit = {int(float(r["ID"])) for r in mc.load_single(os.path.join(BLM_IN, "Pitching_Data.csv"))}
    pp = [i for i in b58["pa"] if i in pit]
    print(f"BLM 2058: {len(pp)} Hitting_Data players also pitched, {sum(b58['pa'][i] for i in pp):.0f} of "
          f"{sum(b58['pa'].values()):.0f} PA (his pos_adj_calc keeps them; the dashboard's drops pitcher-seasons)")

    cand = {
        "BLM": {"ours as published": OURS["BLM"], "ours restated": eng_from_1458(OURS["BLM"])},
        "SSB": {"ours as published": OURS["SSB"], "ours restated": eng_from_1458(OURS["SSB"])},
    }
    hdr("7. CAREER-HISTORY CHECK: this tool on the dashboard's own 42-year BLM / 22-year SSB data")
    careers = {"BLM": ("players_career", 144, 2016, 2056), "SSB": ("ssb_career", None, 2021, 2042)}
    d_aud = None
    if os.path.exists(os.path.join(ANALYSIS, "data", "audit_spectra.json")):
        d_aud = json.load(open(os.path.join(ANALYSIS, "data", "audit_spectra.json")))
    for lg, (pre, lid, y0, y1) in careers.items():
        bf = os.path.join(ANALYSIS, "data", pre + "_batting_stats.csv")
        ff = os.path.join(ANALYSIS, "data", pre + "_fielding_stats.csv")
        if not (os.path.exists(bf) and os.path.exists(ff)):
            print(f"{lg}: career CSVs not found, skipped")
            continue
        seas = M.load_db_seasons(bf, ff, league_id=lid, years=set(range(y0, y1 + 1)))
        r = M.pos_adj_multiyear([seas[y] for y in sorted(seas)])
        f1458 = {p: r["spectrum_runs_per_1200"][p] * 1458 / 1200 for p in N}
        print(f"{lg} {y0}-{y1}: switcher n = {r['n_switch_obs']}")
        print("   this tool, 1458 basis      " + fmt(f1458))
        print("   dashboard frozen literal   " + fmt(OURS[lg]))
        print("   difference                 " + fmt({p: f1458[p] - OURS[lg][p] for p in N}))
        if d_aud and lg in d_aud:
            ref = d_aud[lg]["H5_C20"]["def_only"]
            dd = {p: r["defence_runs_per_1200"][p] * 1458 / 1200 for p in M.SEVEN}
            print("   defence half vs the dashboard's recorded H5_C20 def_only: max |diff| =",
                  round(max(abs(dd[p] - ref[p]) for p in M.SEVEN), 4), "runs per 1458 IP (rounded to 2 dp in the file)")
        cand[lg]["tool, career history (old engines)"] = {p: r["spectrum_runs_per_1200"][p] * mc.STD_IP.get(p, 1200.0) / 1200 for p in N}

    hdr("8. CANDIDATES AND THEIR IMPACT (wins per player-season = delta P / RPW 10.036)")
    cand["BLM"]["tool, BLM 2058 only"] = r58["spectrum_engine_units"]
    cand["BLM"]["tool, BLM 2057+2058"] = r5758["spectrum_engine_units"]
    cand["BLM"]["tool, BLM 2057+2058, LF=RF pooled"] = M.pos_adj_multiyear([b57, b58], lf_rf="pooled")["spectrum_engine_units"]
    rs3 = M.pos_adj_multiyear([ssb[y] for y in (2041, 2042, 2043)])
    rs43 = M.pos_adj_multiyear([ssb[2043]])
    cand["BLM"]["tool, BLM offence 2057-58, defence 2058 only"] = M.pos_adj_multiyear([b57, b58], def_from_year=2058)["spectrum_engine_units"]
    cand["SSB"]["tool, SSB offence 2041-43, defence 2043 only"] = M.pos_adj_multiyear([ssb[y] for y in (2041, 2042, 2043)], def_from_year=2043)["spectrum_engine_units"]
    cand["SSB"]["tool, SSB 2043 only"] = rs43["spectrum_engine_units"]
    cand["SSB"]["tool, SSB 2041-2043"] = rs3["spectrum_engine_units"]
    for lg in ("BLM", "SSB"):
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        mlb = [r for r in hit if r["Lev"] == "MLB"]
        print(f"\n--- {lg}: the engine currently writes BLM's P2..P10 ({'SSB is priced on BLM calibration' if lg == 'SSB' else 'own'})")
        print(f"{'':<46}" + " ".join(f"{p:>7}" for p in N))
        print(f"{'current P':<46}" + fmt(HIS))
        for nm, C in cand[lg].items():
            print(f"{nm:<46}" + fmt(C))
            print(f"{'   delta wins per player-season':<46}" + " ".join(f"{(C[p] - HIS[p]) / RPW:7.3f}" for p in N))
            for rows, tag in ((mlb, "MLB"), (hit, "all levels")):
                chg, dd = 0, []
                for r in rows:
                    el = [p for p in M.POSITIONS if r[f"{p} Eligible"]] + ["DH"]
                    new = {p: r[f"{p} WAA wtd"] + (C[p] - HIS[p]) / RPW for p in el}
                    old = {p: r[f"{p} WAA wtd"] for p in el}
                    bn, bo = max(el, key=new.get), max(el, key=old.get)
                    chg += bn != bo
                    dd.append(new[bn] - old[bo])
                dd = np.array(dd)
                print(f"{'':<8}{tag:<11} Best Pos changes {chg}/{len(rows)} ({chg / len(rows):.1%}); "
                      f"Max WAA change mean {dd.mean():+.3f}, mean |change| {np.abs(dd).mean():.3f}, "
                      f"range {dd.min():+.2f}..{dd.max():+.2f} wins")

    hdr("9. ROW 4 - bestPos INPUTS")
    thr_data = {"BLM": M.rf_arm_threshold(b58), "SSB": M.rf_arm_threshold(ssb[2043])}
    print("RF arm threshold, the dashboard (mean OF ARM of listed-RF players, ALL levels, its own pool):", ARM_THR)
    for lg in ("BLM", "SSB"):
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        for tag, f in (("all levels", lambda r: True), ("MLB only", lambda r: r["Lev"] == "MLB")):
            arms = [float(r["OF ARM"]) for r in hit if r["POS"] == "RF" and f(r) and r.get("OF ARM") not in (None, "")]
            print(f"   {lg} listed-RF in the fork's hitters.json, {tag:<10}: n={len(arms):<4} mean OF ARM {np.mean(arms):.2f}")
    print("   RF-innings-weighted mean OF ARM of deployed RFs (MLB, the existing anchor):",
          {k: round(v, 2) for k, v in thr_data.items()}, " BLM I43 =", round(his_cells["I43"], 2))
    for y in (2041, 2042, 2043):
        print(f"   SSB {y}: {M.rf_arm_threshold(ssb[y]):.2f}")
    print("defensive-only spectrum (engine units; C imputed on SS as the dashboard does):")
    spec = {}
    for nm, res in (("BLM 2058", r58), ("BLM 2057+2058", r5758), ("SSB 2043", rs43), ("SSB 2041-43", rs3)):
        sp, top = M.option_b_spectrum(res)
        spm, topm = M.option_b_spectrum(res, anchor=None)
        spec[nm] = sp
        print(f"   {nm:<14}" + fmt(sp, M.POSITIONS) + f"   (C anchored on {topm} instead: {spm['C']:.2f})")
    for lg in ("BLM", "SSB"):
        print(f"   dashboard {lg:<4}   " + fmt(OPTB[lg], M.POSITIONS) + "   (1458 basis); restated: " + fmt(eng_from_1458(OPTB[lg]), M.POSITIONS))

    def optb(r, sp, thr):
        a = r.get("OF ARM")
        return M.option_b_best_pos({p: float(r[f"{p} RunsP"]) for p in M.POSITIONS},
                                   {p for p in M.POSITIONS if r[f"{p} Eligible"]}, sp,
                                   float(a) if a not in (None, "") else None, thr, ORDER)

    print("\nHis Best Pos (argmax of '{pos} WAA wtd' over eligible positions + DH) vs Option B, committed hitters.json")
    fam = lambda x: "LF/RF" if x in ("LF", "RF") else x
    cases = {
        "BLM": [("dashboard spectrum as published, dashboard threshold", OPTB["BLM"], ARM_THR["BLM"]),
                ("dashboard spectrum restated to engine basis, dashboard threshold", eng_from_1458(OPTB["BLM"]), ARM_THR["BLM"]),
                ("dashboard spectrum restated, data threshold", eng_from_1458(OPTB["BLM"]), thr_data["BLM"]),
                ("fork-data spectrum BLM 2057+58, data threshold", spec["BLM 2057+2058"], thr_data["BLM"]),
                ("fork-data spectrum BLM 2058, data threshold", spec["BLM 2058"], thr_data["BLM"])],
        "SSB": [("dashboard spectrum as published, dashboard threshold", OPTB["SSB"], ARM_THR["SSB"]),
                ("dashboard spectrum restated to engine basis, dashboard threshold", eng_from_1458(OPTB["SSB"]), ARM_THR["SSB"]),
                ("dashboard spectrum restated, data threshold", eng_from_1458(OPTB["SSB"]), thr_data["SSB"]),
                ("fork-data spectrum SSB 2041-43, data threshold", spec["SSB 2041-43"], thr_data["SSB"]),
                ("fork-data spectrum SSB 2043, data threshold", spec["SSB 2043"], thr_data["SSB"])],
    }
    for lg in ("BLM", "SSB"):
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        bad = 0
        for r in hit:
            el = [p for p in M.POSITIONS if r[f"{p} Eligible"]] + ["DH"]
            bad += max(el, key=lambda p: r[f"{p} WAA wtd"]) != r["Best Pos"]
        print(f"{lg}: his Best Pos re-derived from the JSON's own WAA/eligibility fields: {bad} mismatches in {len(hit)} rows")
        for nm, sp, thr in cases[lg]:
            line = [f"  {lg} {nm} (threshold {thr:.1f})"]
            for rows, tag in (([r for r in hit if r["Lev"] == "MLB"], "MLB"), (hit, "all")):
                pairs = [(r["Best Pos"], optb(r, sp, thr)) for r in rows]
                nd = sum(a != b for a, b in pairs)
                nf = sum(fam(a) != fam(b) for a, b in pairs)
                dh = sum(a == "DH" and b != "DH" for a, b in pairs)
                lr = sum(a != b and fam(a) == fam(b) == "LF/RF" for a, b in pairs)
                line.append(f"{tag}: {nd}/{len(rows)} differ ({nd / len(rows):.1%}); of which his-DH->field {dh}, LF<->RF label only {lr}, "
                            f"LF/RF-collapsed differ {nf}")
            print("\n     ".join(line))

    print("\nAgreement with where MLB hitters (>=300 PA) really played most (innings; DH = PA beyond fielding innings):")

    def deployed(s):
        m2 = sum(s["ipc"].values()) / sum(s["pa"].values())
        out = {}
        for i in s["pa"]:
            ips = {p: s["ip"][p].get(i, 0.0) for p in M.POSITIONS}
            ips["DH"] = max(s["pa"][i] * m2 - s["ipc"].get(i, 0.0), 0.0)
            k = max(ips, key=ips.get)
            out[i] = (k, s["pa"][i])
        return out

    for lg, s in (("BLM", b58), ("SSB", ssb[2043])):
        dep = deployed(s)
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        rows = [r for r in hit if r["Lev"] == "MLB" and int(r["ID"]) in dep and dep[int(r["ID"])][1] >= 300]
        n = len(rows)
        h = sum(r["Best Pos"] == dep[int(r["ID"])][0] for r in rows)
        sp = eng_from_1458(OPTB[lg])
        b = sum(optb(r, sp, thr_data[lg]) == dep[int(r["ID"])][0] for r in rows)
        print(f"   {lg}: {n} hitters; exact agreement his {h} ({h / n:.1%}), Option B restated spectrum + data threshold {b} ({b / n:.1%})")

    print("\nThe LF/RF leaf: RF share of MLB hitters whose Option B label is LF or RF, by threshold "
          "(real deployment is 50/50: LF and RF log equal innings)")
    for lg, s_ in (("BLM", b58), ("SSB", ssb[2043])):
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        rows = [r for r in hit if r["Lev"] == "MLB"]
        sp = eng_from_1458(OPTB[lg])
        lf, rf = M.rf_arm_threshold(s_, "LF"), M.rf_arm_threshold(s_, "RF")
        ilf, irf = sum(s_["ip"]["LF"].values()), sum(s_["ip"]["RF"].values())
        print(f"   {lg}: deployed LF arm {lf:.2f}, deployed RF arm {rf:.2f}, RF share of corner innings {irf / (ilf + irf):.3f}")
        for nm, t in (("dashboard (all-level listed-RF mean)", ARM_THR[lg]), ("midpoint of deployed LF and RF", (lf + rf) / 2),
                      ("deployed-RF mean (MLB, innings-weighted)", rf)):
            lab = [optb(r, sp, t) for r in rows]
            n_lf, n_rf = lab.count("LF"), lab.count("RF")
            nd = sum(optb(r, sp, t) != r["Best Pos"] for r in rows)
            print(f"      {nm:<44} threshold {t:5.1f}: RF {n_rf}, LF {n_lf}, RF share {n_rf / (n_rf + n_lf):.3f}; differs from his Best Pos for {nd}/{len(rows)}")
    print("\nWhere the MLB disagreements fall (restated dashboard spectrum, deployed-RF-mean threshold):")
    for lg, s_ in (("BLM", b58), ("SSB", ssb[2043])):
        hit = json.load(open(os.path.join(FORK, "tgs-viz", "public", "data", lg, "hitters.json")))
        rows = [r for r in hit if r["Lev"] == "MLB"]
        sp, t = eng_from_1458(OPTB[lg]), thr_data[lg]
        cat = {}
        for r in rows:
            a, b = r["Best Pos"], optb(r, sp, t)
            k = ("same" if a == b else "his DH -> field position" if a == "DH" else "Option B DH (eligible nowhere)"
                 if b == "DH" else "LF <-> RF label" if {a, b} == {"LF", "RF"} else "other field move")
            cat[k] = cat.get(k, 0) + 1
        print(f"   {lg} ({len(rows)} MLB hitters): {cat}")


if __name__ == "__main__":
    main()
