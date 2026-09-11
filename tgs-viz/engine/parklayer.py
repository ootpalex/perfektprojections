"""
parklayer.py — the park state, computed in Python from per-outcome factors.

THE SHEET'S OWN PARK INTERFACE (mapped 2026-08-14, validated cell-exact below):
the engines consume park through exactly two surfaces —
  * the Ballparks summary block: AG/AH/AI additive count-deltas (events per
    600-PA season, >=50 rating branches), AA (multiplicative wOBA divisor),
    AB (runs per 600 PA, catcher lines only);
  * the Filters cells C8/D8/E8 (park BA factor), C9/D9/E9 (2B), C10/D10/E10
    (3B), C11/D11/E11 (HR) — each an INDEX into the Ballparks table for the
    selected team, blended halfway to 1 by the sheet ((x+1)/2). These are how
    below-anchor hitters, ALL hitter HR, and the whole pitcher side get their
    park treatment. They are not generic "handedness multipliers".
When Filters!C3 is blank the sheet's IFERROR fallbacks set every one of these
knobs to 1 (deltas 0) — that IS the sheet's neutral, all-parks-equal state.

THIS MODULE recomputes all of those knobs from per-outcome factors, replacing
the workbook's park source (its pasted factor table is stale; the fresh export
lives in calib/<LG>/park_factors.csv -> park_blend.json). Two states:

  NEUTRAL  (blend=None)  every factor 1, every delta 0 — all parks equal.
           The sheet's own C3="" semantics. THE SHIPPED DEFAULT: contracts
           and cross-team comparisons are park-normalized.
  BLEND    the user's park state: 50% home park + 50% the average of the
           OTHER MLB parks (NPB excluded), per outcome and per batter hand.
           Pushed through the sheet's own Ballparks chain. NO extra halving —
           the sheet's G3=0.5 implemented "half park / half neutral", and the
           50/50 now lives inside the factors themselves.

Fidelity proof (run this file): rebuilding the workbook's OWN knobs from the
workbook's OWN factors with the OLD construction (x0.5 deltas, (x+1)/2 AA)
reproduces every live cell to ~1e-12 — including the closed-form AB
    AB = -PA * (BL - H29) * (1/H20 - H40/H29) * G3
(the sheet's BO formula's third term is a self-cancelling template) and the
sheet's BL re-anchoring: BL = H29 + platoon-weighted chain-wOBA delta.
Known TGS quirk reproduced as-is: its Delta LH cells for AG/AH/AI reuse the RH
pick (BLM's do not); the validator reports it informationally.

    python tgs-viz/engine/parklayer.py            # fidelity self-test, both leagues
"""
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# every Filters cell the two engines read as a park factor
FILT_CELLS = ("C8", "D8", "E8", "C9", "D9", "E9", "C10", "D10", "E10", "C11", "D11", "E11")


def load_blend(league):
    """calib/<LG>/park_blend.json 'blend' block (written by ingest/parks.py)."""
    path = os.path.join(HERE, "calib", league, "park_blend.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["blend"]


def _chain(g, fhr=1.0, fba=1.0, f2=1.0, f3=1.0):
    """The Ballparks per-team chain: the league-average hitter pushed through a
    park. Exactly the sheet's AC..AK / AS..BA column math (validated below)."""
    PA = g("H31")
    HBP = g("H37") * PA
    BB = g("C33") * (PA - HBP)
    HR = g("C34") * (PA - HBP - BB) * fhr
    SO = g("C35") * (PA - HBP - BB)
    HHR = g("C36") * (PA - HBP - BB - HR - SO) * fba
    XBH = g("C37") * HHR * f2
    T3B = XBH * g("C38") * f3
    D2B, S1B = XBH - T3B, HHR - XBH
    woba = (HBP * g("H12") + BB * g("H13") + S1B * g("H14") + D2B * g("H15")
            + T3B * g("H16") + HR * g("H17")) / PA
    return dict(HHR=HHR, XBH=XBH, T3B=T3B, woba=woba)


def knobs(dp, blend=None):
    """dp: HITTER workbook Data Points dict (the chain constants live there).
    blend: park_blend.json 'blend' dict, or None for NEUTRAL.
    Returns (park, filt_over, park_aa):
      park      hitter-engine park dict (AA/AB + AG/AH/AI _home/_away)
      filt_over Filters overrides for BOTH engines (C8..E11)
      park_aa   the pitcher engine's wOBA divisor (= park['AA'])."""
    if blend is None:
        park = dict(AA=1.0, AB=0.0, AG_home=0.0, AG_away=0.0,
                    AH_home=0.0, AH_away=0.0, AI_home=0.0, AI_away=0.0)
        return park, {c: 1.0 for c in FILT_CELLS}, 1.0

    g = lambda k: float(dp[k])
    n = _chain(g)
    cR = _chain(g, blend["hr_rhb"], blend["avg_rhb"], blend["doubles"], blend["triples"])
    cL = _chain(g, blend["hr_lhb"], blend["avg_lhb"], blend["doubles"], blend["triples"])
    # BL re-anchored on the league's actual wOBA (sheet: Park wOBA = chain delta + H29)
    BL = g("H29") + g("H26") * (cR["woba"] - n["woba"]) + (1 - g("H26")) * (cL["woba"] - n["woba"])
    AA = BL / g("H29")
    AB = -g("H31") * (BL - g("H29")) * (1 / g("H20") - g("H40") / g("H29"))
    park = dict(
        AA=AA, AB=AB,
        AG_home=cR["XBH"] - n["XBH"], AG_away=cL["XBH"] - n["XBH"],
        AH_home=cR["HHR"] - n["HHR"], AH_away=cL["HHR"] - n["HHR"],
        AI_home=cR["T3B"] - n["T3B"], AI_away=cL["T3B"] - n["T3B"],
    )
    filt_over = {
        "C8": blend["avg_rhb"], "D8": blend["avg_lhb"], "E8": blend["avg"],
        "C9": blend["doubles"], "D9": blend["doubles"], "E9": blend["doubles"],
        "C10": blend["triples"], "D10": blend["triples"], "E10": blend["triples"],
        "C11": blend["hr_rhb"], "D11": blend["hr_lhb"], "E11": blend["hr"],
    }
    return park, filt_over, AA


# ---------- fidelity self-test ----------
def _validate(league):
    """Rebuild the live workbook's own park knobs from its own Filters factors
    with the OLD construction; every cell must reproduce to ~1e-9."""
    import hitters as H
    dp, filt, park = H.scan_consts(
        os.path.join(REPO, f"The Sheets {league}", "The Sheet Hitters.xlsx"))
    g = lambda k: float(dp[k])
    fv = lambda k: 2 * float(filt[k]) - 1   # un-halve the sheet's (x+1)/2 cells
    n = _chain(g)
    cR = _chain(g, fv("C11"), fv("C8"), fv("C9"), fv("C10"))
    cL = _chain(g, fv("D11"), fv("D8"), fv("D9"), fv("D10"))
    BL = g("H29") + g("H26") * (cR["woba"] - n["woba"]) + (1 - g("H26")) * (cL["woba"] - n["woba"])
    want = {
        "AA": (BL / g("H29") + 1) / 2,
        "AB": -g("H31") * (BL - g("H29")) * (1 / g("H20") - g("H40") / g("H29")) / 2,
        "AG_home": 0.5 * (cR["XBH"] - n["XBH"]), "AH_home": 0.5 * (cR["HHR"] - n["HHR"]),
        "AI_home": 0.5 * (cR["T3B"] - n["T3B"]),
        "AG_away": 0.5 * (cL["XBH"] - n["XBH"]), "AH_away": 0.5 * (cL["HHR"] - n["HHR"]),
        "AI_away": 0.5 * (cL["T3B"] - n["T3B"]),
    }
    bad = quirk = 0
    for k, w in want.items():
        got = park[k]
        if abs(got - w) < 1e-9:
            continue
        # TGS's Delta LH AG/AH/AI cells reuse the RH pick (sheet quirk) — the
        # workbook value equals the _home value instead of the true LH build.
        if k.endswith("_away") and abs(got - park[k.replace("_away", "_home")]) < 1e-12:
            quirk += 1
            continue
        bad += 1
        print(f"  {league} {k}: workbook {got:.12g} vs rebuilt {w:.12g}  MISMATCH")
    tag = f" ({quirk} Delta-LH cells reuse the RH pick - known sheet quirk)" if quirk else ""
    print(f"{league}: {8 - bad - quirk}/8 park knobs reproduced from the sheet's own factors{tag}"
          + ("" if not bad else f"  <-- {bad} MISMATCH"))
    return bad == 0


if __name__ == "__main__":
    ok = all([_validate("TGS"), _validate("BLM")])
    raise SystemExit(0 if ok else 1)
