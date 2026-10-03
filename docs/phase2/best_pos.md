# Phase 2 row 4: bestPos Option B inputs (audit; no engine change)

His `Best Pos` is unchanged. The `Best Pos WAR` column waits on Phase 1. This file audits the two
inputs Option B needs, computes both from data for BLM and SSB, and counts how many MLB hitters
would change position label.

Terms. **Option B** = the dashboard's best-position rule (`app/src/utils/dataProcessing.js:44-75`):
the eligible field position with the highest RunsP plus a defensive-only spectrum, DH only if the
hitter is eligible nowhere, and an LF/RF label chosen by OF ARM. **RunsP** = the engine's projected
fielding runs for a hitter at a position. **Spectrum** = the per-position credit for how hard the
position is, here from the ZR switcher half of `pos_adj.md` only (no offence). **OF ARM** = the
outfield throwing rating. **IP** = innings played. **Deployed RF** = a player who logged innings at RF
in the MLB season export. Numbers come from `pos_adj_audit_output.txt` section 9.

## 1. What this means for you

1. **The two rules disagree for 22 to 32% of MLB hitters, and most of it is rule design, not
   input values.** On the committed `hitters.json`, Option B with the dashboard's own inputs gives a
   different label than his rule for 134 of 460 BLM MLB hitters (29.1%) and 153 of 475 SSB MLB
   hitters (32.2%). With inputs rebuilt from data it is 100 of 460 (21.7%, BLM) and 113 of 475 (23.8%, SSB).
2. **The dashboard's RF arm threshold is not what its description says.** It is documented as the mean
   OF ARM of the players deployed at RF. It is computed over every listed-RF player at every level
   (prospects and free agents included). The MLB-deployed mean is 62.35 (BLM 2058) and 61.72 (SSB 2043),
   against the dashboard's 55.2 and 54.6, a gap of about 7 rating points.
3. **At the dashboard's SSB threshold, 72% of SSB MLB corner outfielders are labelled RF.** Real
   deployment is 50/50 (LF and RF log equal innings in both leagues). BLM's 55.2 happens to give 48%.
4. **The dashboard's spectrum is on the wrong basis for his RunsP and is OOTP-26-era.** It is runs per
   1458 IP added to RunsP per 1200 IP (the same mismatch as `pos_adj.md` F1), and its SS premium
   (12.7 BLM as published, 10.45 restated) is about twice what the OOTP 27 seasons show (5.5 to 6.0).
5. **Neither rule can be shown better against real usage.** Exact agreement with where hitters actually
   played most is 47.6% for his rule and 50.0% (BLM, 252 hitters) / 50.2% (SSB, 227 hitters) for Option B.
   The gap is 6 hitters in each league, inside noise (the standard error of each agreement rate is about
   3 percentage points).

## 2. How his rule works (verified)

`engine/hitters.py:403-405`: `Best Pos` is the argmax of `{pos} WAA wtd` over positions where the hitter
is eligible, with DH always eligible. WAA is (RunsP + base running + batting + posAdj) / 10.036 for
1B..RF, with a catcher batting term at 500 PA and a DH term (`BSR * 0.98 + DH BatR + P10`). I recomputed
`Best Pos` from the JSON's own WAA and eligibility fields: 0 mismatches in 6,545 BLM rows and 0 in
6,866 SSB rows. So his rule is exactly "highest positionally-adjusted WAA", where the posAdj is the
blended offence-and-defence value from row 1.

Option B differs in three ways: it drops the offence-derived half of the position credit (the
dashboard's argument is that a hitter's bat is the same at every position, so it cancels; the
offence-by-position half of posAdj does not cancel, which is why the rules differ), it forbids DH as the
winner unless the hitter is eligible nowhere, and it picks LF or RF by arm instead of by RunsP.

## 3. Input trace

| Input | Tag | Provenance and check |
|---|---|---|
| RunsP per position, eligibility flags | 🟢 | His engine's own output in `hitters.json`. Eligibility floors are Row 3's decision and are taken as committed. |
| Defensive-only spectrum, 7 positions | 🟢 | The ZR switcher half of `pos_adj_multiyear.py`; windows and engine-boundary choices are `pos_adj.md` decisions 2 and 3. |
| Catcher entry, imputed | 🔵 | C = defence[anchor] + (blended C minus blended anchor). The dashboard anchors on SS. Anchoring on the window's highest value (CF in every 27-era window) raises BLM 2057+58 C from 9.55 to 12.29 and SSB 2041-43 C from 12.68 to 19.36. |
| Spectrum basis | 🟡 | Dashboard literals are per 1458 IP; restated by x1200/1458 (C x1000/1458) for his RunsP. |
| RF arm threshold | 🔵 | Definition and population are the decision (section 5). |
| Tie order: C, SS, CF, 2B, 3B, LF, RF, 1B | 🔵 | Dashboard order, hardest first. |
| DH only when eligible nowhere | 🔵 | Dashboard rule. |
| Defence-only rather than total WAA as the argmax target | 🔵 | Dashboard rule; the main source of disagreement (section 4). |

## 4. The spectrum

Engine units (C per 1000 IP, others per 1200 IP), C imputed on SS as the dashboard does. The same
function (`option_b_spectrum`) is in the candidate files under `option_b_defensive_spectrum`.

| source | C | 1B | 2B | 3B | SS | LF | CF | RF |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| dashboard BLM, as published (1458 IP) | 19.2 | -10.1 | -0.3 | -0.5 | 12.7 | -6.8 | 9.9 | -4.9 |
| dashboard BLM, restated | 13.17 | -8.31 | -0.25 | -0.41 | 10.45 | -5.60 | 8.15 | -4.03 |
| BLM 2058 (OOTP 27) | 9.38 | -7.48 | -5.95 | -3.01 | 5.49 | 0.74 | 10.43 | -0.22 |
| BLM 2057+2058 | 9.55 | -8.03 | -4.62 | -2.09 | 6.04 | -1.01 | 9.63 | 0.09 |
| dashboard SSB, as published | 22.5 | -8.4 | 0.0 | -1.1 | 11.9 | -6.3 | 9.4 | -5.4 |
| dashboard SSB, restated | 15.43 | -6.91 | 0.00 | -0.91 | 9.79 | -5.19 | 7.74 | -4.44 |
| SSB 2043 (OOTP 27) | 10.85 | -8.59 | -3.02 | -0.65 | 3.00 | -0.76 | 10.06 | -0.05 |
| SSB 2041-2043 | 12.68 | -6.49 | -2.21 | -1.38 | 5.99 | -3.81 | 9.79 | -1.88 |

The switcher values carry the SEs in `pos_adj.md` section 4 (one season: 1.0 to 2.1 runs per
position). The gap between 2B and the next position in the 27-era data is wider than the
dashboard's history shows (2B -5.95 against 3B -3.01 in BLM 2058), and the SS premium is smaller;
both are inside or near the one-season SEs for BLM and outside them for SSB's SS (-5.85, z -3.09).

## 5. The RF arm threshold

Three definitions, each computed from data on disk. LF and RF each log equal innings in a league, so
the share of corner outfielders who are really RF is 50%.

| definition | BLM | SSB | RF share of Option B corner labels, BLM / SSB |
|---|--:|--:|--:|
| dashboard: mean OF ARM of every listed-RF player, all levels | 55.2 (fork's `hitters.json`: 54.03, n 663) | 54.6 (fork's `hitters.json`: 54.60, n 709) | 48% / 72% |
| midpoint of the deployed LF and deployed RF mean arms (innings-weighted) | 57.78 (LF 53.21, RF 62.35) | 58.17 (LF 54.62, RF 61.72) | 48% / 45% |
| mean OF ARM of deployed RFs, MLB, innings-weighted (the existing anchor `I43`) | 62.35 | 61.72 (2041: 63.43, 2042: 62.54) | 28% / 32% |

Mean OF ARM of listed-RF players in MLB only is 60.92 (BLM, n 49) and 61.45 (SSB, n 62), in line with the
third row. The SSB all-level figure in the fork's data reproduces the dashboard's 54.6 exactly, so the
dashboard's threshold is what its pool gives, not a typo. BLM's 55.2 comes from a different pool and date
(the fork's all-level pool gives 54.03).

The third definition is the dashboard's own wording ("RF is the high bar; the split skews toward LF, not 50/50")
applied to the population its wording names. It is also computed already: it is the `I43` fielding anchor in
`metadata-latest.json` (62.3522 for BLM, equal to my recomputation to 1e-9), so no new input is needed and it
self-derives per league and per refresh.

## 6. How many MLB hitters change label

Population: `Lev == "MLB"` in the committed `hitters.json` (460 BLM, 475 SSB). A "difference" is any label
different from his `Best Pos`. All-level counts are in the output file (34 to 39% of 6,545 and 6,866).

| Option B inputs | BLM differ | SSB differ |
|---|--:|--:|
| dashboard spectrum as published, dashboard threshold | 134 (29.1%) | 153 (32.2%) |
| dashboard spectrum restated, dashboard threshold | 126 (27.4%) | 141 (29.7%) |
| dashboard spectrum restated, deployed-RF-mean threshold | 119 (25.9%) | 123 (25.9%) |
| spectrum from fork data (BLM 2057+58 / SSB 2041-43), deployed-RF-mean threshold | 100 (21.7%) | 113 (23.8%) |
| spectrum from current-engine data only (BLM 2058 / SSB 2043), deployed-RF-mean threshold | 102 (22.2%) | 135 (28.4%) |

Where the 119 BLM and 123 SSB differences fall (restated dashboard spectrum, deployed-RF-mean threshold):

| kind | BLM | SSB |
|---|--:|--:|
| his DH, Option B a field position | 40 | 61 |
| LF and RF swap labels only | 43 | 40 |
| other field-position moves (mostly 1B to 2B 12 and 12, 1B to 3B 6 and 3) | 36 | 22 |
| Option B gives DH (eligible nowhere) while his rule does not | 0 | 0 (the 12 SSB hitters Option B sends to DH are already DH under his rule) |

So the choice of spectrum source moves the "other field moves" bucket and a handful of labels; the DH rule
and the arm leaf account for 70% (BLM) and 82% (SSB) of the disagreement before any input is chosen.

## 7. Flags and their resolution

| Flag | Resolution |
|---|---|
| B1 Dashboard threshold pool is all levels | Measured (section 5). Resolved by decision 3 below. |
| B2 Dashboard spectrum on 1458 IP basis | Restated in sections 4 and 6; the restatement alone lowers the count of differing labels by 8 (BLM) and 12 (SSB). |
| B3 Catcher imputation anchor | Reported both ways in the candidate files (`catcher_if_anchored_on_window_max`); not data-resolvable. |
| B4 `hitters.json` is a pull from a different date than the 2058 / 2043 fielding export | The deployed-arm figures use the fielding export; the label counts use the JSON. A refresh would move counts slightly; the structure of the result does not depend on it. |
| B5 Eligibility floors will change with Row 3 | Counts here use the floors as committed; rerun `pos_adj_audit.py` after Row 3. |
| B6 Agreement with real deployment is not a referee | Teams deploy for reasons other than WAR; the figure only shows the two rules cannot be separated that way. |

## 8. Decisions for you

1. **Argmax target.** (a) total positionally-adjusted WAA, his rule; (b) RunsP plus defence-only
   spectrum, Option B. Evidence: section 2 and 6. The agreement test in section 1 (point 5) cannot separate them.
   Recommendation: keep (a) as `Best Pos`; when `Best Pos WAR` is built in Phase 1, show Option B's
   label as a second column if you want both views. This is a design choice, not a data question.
2. **DH.** Whether DH may win. His rule lets DH win for 40 BLM and 73 SSB MLB hitters (8.7% and 15.4%);
   Option B allows it for 0 and 12. Evidence: section 6. Recommendation: your call; it is a design
   choice with no data referee.
3. **RF threshold.** (a) dashboard 55.2 / 54.6; (b) deployed-RF mean 62.35 / 61.72, equal to the existing `I43`
   anchor; (c) midpoint of deployed LF and RF arms 57.78 / 58.17. Evidence: section 5. Recommendation: (b)
   if the locked wording ("high bar, skews LF") is the intent, because it matches that wording on MLB data and needs
   no new input; (c) if the intent is a 50/50 split, which is what real deployment shows.
4. **Spectrum source.** (a) dashboard literals restated; (b) pooled fork data; (c) current-engine only.
   Follows `pos_adj.md` decision 3; with the same 26-to-27 evidence. Recommendation: the same window as the posAdj
   decision, so the two never come from different eras.
5. **Catcher anchor.** SS (dashboard) or the window's highest value. Affects only how catchers compare with
   field positions. Recommendation: SS, to match the dashboard, until a catcher-specific decision is made.
6. **Gate.** Option B is not wired. When approved, the inputs are `option_b_defensive_spectrum.engine_units` and
   `rf_arm_threshold` (or `I43`) from the candidate files, and the rule is `option_b_best_pos` in
   `engine/pos_adj_multiyear.py` (pure function, unit-tested, called by nothing in the engine).

## 9. What was built, and what is not verified

`option_b_spectrum`, `rf_arm_threshold` and `option_b_best_pos` in `tgs-viz/engine/pos_adj_multiyear.py`;
the two candidate files carry the inputs per window; `test_pos_adj_multiyear.py` covers the rule (ties,
strict greater-than, DH, arm cutoff, missing RunsP), the catcher imputation and the innings-weighted arm.
`pos_adj_audit.py` regenerates every number here.

Verified by running: his `Best Pos` rule reproduced from the JSON (0 mismatches); all counts and
thresholds above. Inferred: why the dashboard's BLM 55.2 differs from the fork's all-level 54.03 (a different
pool or date; I could not recover the original pool). Not done by design: `hitters.py` and `Best Pos` are untouched.
