# Phase 2, row 3: position eligibility floors

*2026-10-03, branch `phase2/eligibility`, off `phase2-model`. Audit first: nothing in the engine is
changed. The proposed change is a patch file that is not applied. Inputs are tagged 🟢 computed from
real data, 🟡 borrowed constant, 🔵 deliberate assumption. Each claim says whether it was **verified**
(run this session) or **inferred**.*

## 0. What this means for you

1. **Adopt a corner-outfield floor of 45 for the BLM basis (BLM, and SSB and RG which run on it); keep his
   50 for TGS. Do not adopt our two other additions.** The data on disk supports one of our three
   differences from his rule, by league. It contradicts a second and says nothing about the third.
   - LF/RF at 50 locks real left and right fielders out in BLM and SSB, not in TGS. Pooled over
     BLM 2057, BLM 2058 and SSB 2043, his floor excludes **12.5% of the innings played at LF and 7.6%
     at RF** by players who had at least 45 innings there. At 45 it excludes **2.7% and 0.9%**.
     In TGS 2044 the same floor excludes **2.3% and 2.0%**, and 45 would save only 1.9 points of LF
     and 0.1 of RF, so TGS keeps 50. (Verified.)
   - Our SS turn-double-play floor (TDP ≥ 45) removes real regulars. In BLM 2058 it strips shortstop
     eligibility from a hitter who played **862 innings at SS** (Natanael Ferreira, range 75, TDP 35) and a
     second who played **643** (Alfonso Rueda, range 60, TDP 40). For Ferreira it moves Best Pos from SS
     to 3B and lowers Max WAA by 1.295. It is the only Best Pos change among 460 BLM MLB hitters
     under any of the rules tested. (Verified.)
   - Our first-base floor (IF ERR > 20) is inert on usage: 0 of 274 player-seasons with 45+ innings at 1B
     fail it. It removes 1B eligibility from 5 BLM and 1 SSB MLB hitters. The five BLM hitters played no
     inning at 1B in 2057 or 2058; the SSB one played 29. It changes no Best Pos. Adding it buys nothing.
     (Verified.)
2. **Adopting the corner-OF floor changes no value, only flags.** On the committed `hitters.json`, under the
   45 rule, **0 of 460 BLM MLB hitters and 0 of 475 SSB MLB hitters change Best Pos, Max WAA wtd or
   MAX WAA P.** 58 BLM and 56 SSB MLB hitters gain LF and RF eligibility (62 for RG, which has no
   usage data to check). (Verified.) What does move is who the roster optimizer and the Positional
   Strength board may play at LF/RF: on the board, BLM changes for no club and SSB changes one club,
   Nashville, which moves a hitter from RF to 3B (section 6).
3. **Other shared floors look strict in the same data, and I left them alone.** SS range ≥ 60 excludes
   10.6% of pooled SS innings, close to the 12.5% that his LF floor excludes. Section 5 lists these with
   the flag counts; it is your call whether to widen them. They are not differences between his engine
   and ours, so they are outside this row.
4. **One verification step is blocked on this machine.** His fielding-curve fit gates engine-versus-
   simulation error only for ratings at or above the eligibility floor (50 for LF/RF). Moving the BLM
   floor to 45 needs that gate re-run over the 45 to 50 band. That needs his clone-sim archives, which
   are not here (section 8).

## 1. The rules as they stand (verified by reading both files and the sheet formulas)

| Position | His engine now (`tgs-viz/engine/hitters.py:383-389`) | Ours (`model/src/hitters.py:compute_position_eligibility`) | Proposed ("rec", BLM basis; TGS stays as his) |
|---|---|---|---|
| C | C FRM ≥ 45 | same | same |
| 1B | HT > 179 cm and IF RNG > 20 | same + **IF ERR > 20** | his |
| 2B | IF RNG ≥ 50, throws R, TDP ≥ 45 | same | same |
| 3B | IF RNG ≥ 40, IF ARM ≥ 50, throws R | same | same |
| SS | IF RNG ≥ 60, IF ARM ≥ 50, throws R | same + **TDP ≥ 45** | his |
| LF | OF RNG ≥ 50 | **OF RNG ≥ 45** | **OF RNG ≥ 45** |
| CF | OF RNG ≥ 60 | same | same |
| RF | OF RNG ≥ 50 | **OF RNG ≥ 45** | **OF RNG ≥ 45** |
| DH | always | always | always |

His rule is the sheet's: `engine/extracted/BLM_hitters_formulas.txt` rows [61]-[68] carry the same
clauses (🟡 borrowed from The Sheet; its authors did not publish a usage check). Ours were retuned on
2026-05-25 against pooled BLM-MIA and SSB 2041/2042 usage (`analysis/fielding-eligibility-usage`).
The plan quoted `engine/hitters.py ~362`; the block is now at 383-389 (drift, verified).

## 2. Input audit

| Input | Tag | Provenance and check |
|---|---|---|
| Innings played by player and position, BLM 2057 | 🟢 | `backtest/actuals/BLM/2057/fielding.csv`, league 144, MLB. Each position sums to exactly 43,122 innings. The 30 clubs × 162 games × 8.87 defensive innings gives 43,132. So coverage is the full league. (Verified.) |
| Innings, BLM 2058 | 🟢 | `engine/calib/BLM/metadata_inputs/Fielding_Data.csv`. About 1,437 innings per club per position, a full season. Stats sit with the player's current org. (Verified.) |
| Innings, SSB 2043 | 🟢 | `leagues/SSB/metadata/2043/fielding_data_<pos>.csv`. 28 clubs, about 1,453 innings per club per position. The only OOTP 27 season. (Verified.) |
| Ratings, BLM 2057 | 🟢 | `ratings_history.db` pulls 2, 3, 4 (2057-09-24, 10-02, 10-13), three replicates of weight 1/3. Across the three pulls an MLB fielder's rating agrees on 98.6% to 100% of rows (IF RNG 99.8%, OF RNG 98.7%, TDP 99.5%, IF ERR 99.0%, C FRM 100%). Scout noise is not a problem for MLB regulars. (Verified.) |
| Innings and ratings, TGS 2044 (check only, not pooled) | 🟢 | `backtest/actuals/TGS/2044/fielding.csv` (league 100, MLB; 32 clubs, about 1,454 innings per club per position) × `ratings_history.db` pulls 11, 21, 28 (2044-02-22, 07-04, 10-03; start, middle, end of season), weight 1/3 each. Shown separately because his main league is TGS and the engine rule is shared. |
| Ratings, BLM 2058, SSB 2043 | 🟢 | `Fielding_Ratings.csv` / `fielding_ratings.csv`, one pull each. |
| Throws (T) | 🟢 | Not in the ratings tables. Joined by player id from the league's shipped `hitters.json`. Unknown (3.2% of BLM 2057 innings, 0.4% BLM 2058, 1.5% SSB) passes the throws clause. The clause is itself supported: left-handed throwers hold 0.00% to 0.1% of innings at 2B, 3B and SS in all three sources. (Verified.) |
| Height (1B clause) | 🟢 | `HT Sort` (cm) from `hitters.json` for BLM 2057; the feet-and-inches field converted at feet × 30.48 + inches × 2.54 (the engine's own conversion, `ingest/ratings.py:28`) for the other two. Unknown height passes. |
| "Played the position" cut | 🔵 | 45 or more innings at the position (about five full games). Sensitivity at 1 and 300 innings is in section 4. |
| "Floor is too strict" criterion | 🔵 | At most 3% of the position's innings fall below it. This is the one assumption behind the recommendation. 3% is roughly where the gates that look well set today sit (C 0.9%, 3B range 1.3%, 2B TDP 2.7%). It is a stated judgement, not a measurement. |
| The 45 for LF/RF | 🟡→🔵 | Ours came from the 2026-05-25 audit. Re-derived here from different data: it is the highest 5-point floor under the 3% criterion on the pooled BLM + SSB sample. 40 also passes (0.9% / 0.2%). |
| "SSB and RG are on the BLM calibration basis" | 🟡 | From `docs/PHASE1_AUDIT.md` and `settings.defaults.json` (`"Regular Game": basis BLM`); the SSB entry is in the local settings file, which is not in the repo. Inferred, not read. It decides whether a per-league key `"BLM"` reaches SSB and RG. |

## 3. Method (verified by running `tgs-viz/tools/eligibility_usage.py`)

For each position, take every player with at least 45 innings there. Weight by innings. For each
rating clause, report the innings-weighted rating percentiles and the share of the position's innings
(and of players) held by players who fail the clause or the whole rule. "Share below floor f" counts
players whose rating is under f. Pooled means the three league-seasons added together by innings.

Reproduction check of the tool itself: its `his` rule reproduces **every** committed `<pos> Eligible` flag,
every `Best Pos`, and `Max WAA wtd` and `MAX WAA P` to 0 difference on BLM (6,545 rows), SSB (6,866),
TGS (7,532) and RG (5,108). (Verified.) The patched engine's flags match the tool's `rec` rule on all
6,578 BLM sheet hitters and its `his` rule on all 4,253 TGS ones (section 8).

## 4. Results

### 4.1 Rating distribution of players who actually played the position

Pooled, 45+ innings at the position, innings-weighted percentiles p1 / p5 / p10 / p25 / p50 (rating
steps are 5 points):

| Pos | Rating | p1 / p5 / p10 / p25 / p50 | Player-seasons |
|---|---|---|---|
| C | C FRM | 45 / 50 / 55 / 60 / 65 | 205 |
| 1B | IF RNG | 20 / 30 / 35 / 40 / 45 | 274 |
| 1B | IF ERR | 25 / 30 / 35 / 40 / 45 | 274 |
| 1B | HT (cm) | 175 / 183 / 184 / 187 / 190.5 | 274 |
| 2B | IF RNG | 40 / 45 / 50 / 55 / 60 | 296 |
| 2B | TDP | 35 / 45 / 50 / 55 / 60 | 296 |
| 3B | IF RNG | 35 / 45 / 45 / 50 / 55 | 280 |
| 3B | IF ARM | 45 / 50 / 55 / 60 / 65 | 280 |
| SS | IF RNG | 40 / 50 / 55 / 65 / 70 | 280 |
| SS | IF ARM | 40 / 50 / 55 / 60 / 65 | 280 |
| SS | TDP | 35 / 45 / 50 / 60 / 65 | 280 |
| LF | OF RNG | 40 / 45 / 45 / 50 / 60 | 305 |
| CF | OF RNG | 50 / 60 / 60 / 65 / 70 | 260 |
| RF | OF RNG | 45 / 45 / 50 / 55 / 60 | 304 |

(Player-seasons: BLM 2057 counted once per player, not once per replicate.)

### 4.2 Share of the position's innings that each rule excludes (pooled; per-source below)

Percent of innings at the position, players with 45+ innings. "his" and "ours" are the rules in section 1.

| Pos | his | ours | rec | BLM 2057 his / ours | BLM 2058 his / ours | SSB 2043 his / ours |
|---|---|---|---|---|---|---|
| C | 0.9 | 0.9 | 0.9 | 0.0 / 0.0 | 0.3 / 0.3 | 2.6 / 2.6 |
| 1B | 2.7 | 2.7 | 2.7 | 2.6 / 2.6 | 1.5 / 1.5 | 4.1 / 4.1 |
| 2B | 7.8 | 7.8 | 7.8 | 9.0 / 9.0 | 4.5 / 4.5 | 10.0 / 10.0 |
| 3B | 4.4 | 4.4 | 4.4 | 0.4 / 0.4 | 4.1 / 4.1 | 9.0 / 9.0 |
| SS | 12.2 | 13.4 | 12.2 | 11.9 / 11.9 | 7.7 / 11.2 | 17.2 / 17.2 |
| LF | **12.5** | 2.7 | 2.7 | 10.3 / 2.5 | 13.8 / 4.3 | 13.4 / 1.2 |
| CF | 4.9 | 4.9 | 4.9 | 4.3 / 4.3 | 3.8 / 3.8 | 6.8 / 6.8 |
| RF | **7.6** | 0.9 | 0.9 | 6.8 / 0.4 | 7.2 / 1.0 | 9.0 / 1.3 |

TGS 2044 (not pooled), his / ours: C 0.7 / 0.7, 1B 3.0 / 3.0, 2B 0.7 / 0.7, 3B 0.7 / 0.7, SS 4.9 / 4.9, LF 2.3 / 0.4,
CF 0.2 / 0.2, RF 2.0 / 1.9. Every position in TGS is under 5%; the SS floor and the corner floors that
look strict in BLM and SSB are not strict there. Among TGS 300+-innings regulars (50 LF, 47 RF) his
floor excludes 1 LF and 1 RF.

At other cuts the ordering holds. Pooled LF excluded by his floor: 12.9% at 1+ innings, 12.5% at 45+,
12.1% at 300+; RF: 8.0%, 7.6%, 6.1%. Among 300+-innings regulars (131 LF, 128 RF pooled), his floor
excludes 17 LF and 10 RF; the 45 floor excludes 4 LF (1 BLM 2057, 3 BLM 2058) and no RF.

### 4.3 Each differing clause, on its own

| Clause (not in his rule, or different) | Innings failing it, pooled | Failing it and nothing else | Real regulars it removes |
|---|---|---|---|
| LF OF RNG ≥ 50 (his) | 12.5% | 12.5% | 17 of 131 LF with 300+ innings |
| RF OF RNG ≥ 50 (his) | 7.6% | 7.6% | 10 of 128 RF |
| LF OF RNG ≥ 45 | 2.7% | 2.7% | 4 of 131 |
| RF OF RNG ≥ 45 | 0.9% | 0.9% | 0 of 128 |
| 1B IF ERR > 20 (ours) | **0.0%** | 0.0% | 0 |
| SS TDP ≥ 45 (ours) | 3.6% | 1.2% (BLM 2057 0.0, BLM 2058 3.5, SSB 0.0) | 2 SS in BLM 2058: 862 and 643 innings |

The prior audit reported that the TDP floor excluded 12 low-inning shortstops (0.28% of SS innings). I
could not reproduce that; its inputs (BLM-MIA, SSB 2041/2042) are not the seasons used here, and BLM-MIA
was retired. On the data on disk the figure is 1.2% of pooled innings and two regulars. The data decides:
the floor is not supported.

### 4.4 Candidate floors, pooled: share of the position's innings below each floor

(A floor f passes ratings of f or more. Strict clauses `> v` are floor v + 5.)

| Pos / rating | 30 | 35 | 40 | 45 | 50 | 55 | 60 | 65 |
|---|---|---|---|---|---|---|---|---|
| C FRM | 0.1 | 0.1 | 0.1 | **0.9** | 3.4 | 8.8 | 21.9 | 47.7 |
| 1B IF RNG | 4.2 | 9.0 | 17.8 | 29.7 | 51.7 | 70.0 | 88.9 | 98.6 |
| 1B IF ERR | 3.2 | 7.1 | 24.0 | 39.1 | 56.1 | 76.5 | 89.5 | 97.1 |
| 2B IF RNG | 0.0 | 0.0 | 0.1 | 1.7 | **5.3** | 15.8 | 34.7 | 57.9 |
| 2B TDP | 0.1 | 0.7 | 1.0 | **2.7** | 7.3 | 24.5 | 40.8 | 64.1 |
| 3B IF RNG | 0.0 | 0.1 | **1.3** | 3.6 | 14.9 | 28.8 | 51.2 | 71.3 |
| 3B IF ARM | 0.0 | 0.0 | 0.1 | 0.2 | **4.0** | 5.4 | 10.9 | 29.6 |
| SS IF RNG | 0.0 | 0.0 | 0.0 | 1.3 | 2.1 | 5.2 | **10.6** | 18.8 |
| SS IF ARM | 0.1 | 0.1 | 0.8 | 1.3 | **4.0** | 8.9 | 18.7 | 36.7 |
| SS TDP | 0.0 | 0.0 | 1.9 | **3.6** | 6.2 | 11.1 | 21.8 | 43.5 |
| LF OF RNG | 0.0 | 0.0 | 0.9 | **2.7** | **12.5** | 26.0 | 43.2 | 66.6 |
| CF OF RNG | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 1.7 | **4.9** | 14.0 |
| RF OF RNG | 0.0 | 0.0 | 0.2 | **0.9** | **7.6** | 18.6 | 40.1 | 60.9 |

Bold is the value some rule uses today (his or ours). On 1B, the shared IF RNG > 20 clause (floor 25)
excludes 1.2% pooled, but 3.9% in SSB alone, where two 1B with 1,528 innings between them sit at range 20
(0.0% in BLM and TGS). I left it: it is in both rules.

## 5. Recommendation

| Rule | Data say | Recommendation |
|---|---|---|
| LF / RF, BLM and SSB | his 50 excludes 12.5% / 7.6% of innings; 45 excludes 2.7% / 0.9%; 40 excludes 0.9% / 0.2%. Same sign in all three league-seasons (LF at 50: 10.3 / 13.8 / 13.4%). | **45.** 40 is defensible, mainly for BLM LF (3.4% below 45 over two seasons; 4 of 90 regulars): it adds 34 BLM and 53 SSB MLB hitters to LF/RF eligibility beyond 45 and moves no Best Pos or Max WAA. |
| LF / RF, TGS | his 50 excludes 2.3% / 2.0%; 45 excludes 0.4% / 1.9% | **Keep 50.** The data show no problem. |
| LF / RF, RG | no usage data on disk | **Your decision.** It runs on the BLM basis, so the patch would give it 45; I have no data of its own. |
| SS TDP | not supported (section 4.3) | **Do not add.** Keep his rule. |
| 1B IF ERR | inert on usage | **Do not add.** |
| C, 1B (RNG, HT), 3B range, 2B TDP, CF | within about 5% | Leave. |
| SS range ≥ 60 | 10.6% of innings below it; ≥ 55 would be 5.2%, ≥ 50 2.1% | **Your decision.** Shared with the sheet, so outside the ours-vs-his question. |
| 2B range ≥ 50 | 5.3%; 45 would be 1.7% | Same. |
| SS and 3B ARM ≥ 50 | 4.0% each | Same. |
| CF ≥ 60 | 4.9%; 55 would be 1.7% | Same. |

`rule wide` in the tool applies the 3%-criterion floors to every clause at once (2B range 45, 3B arm 45, SS
range 50, SS arm 45, CF 55, corners 45). Pooled it excludes 4.2% (2B), 1.5% (3B), 3.4% (SS), 1.7% (CF) of
innings, against 7.8, 4.4, 12.2, 4.9 today. It changes flags for 173 BLM and 168 SSB MLB hitters and, in the committed
data, moves no Best Pos or Max WAA for BLM, SSB or RG. It moves 3 DH to 3B Best Pos among 7,532 TGS rows.
I did not put it in the patch.

One thing the usage cannot tell us: how many players below a floor would be *deployed* if eligible. The
data show the cost of a floor that is too strict (real regulars locked out). They do not show the cost
of one that is too lenient (flags that an optimizer might use for a player OOTP would never play there).
That is why the recommendation stops at the change that is supported on both sides: in BLM and SSB the
45 floor sits at the p5 of real corner-OF usage and moves no value.

## 6. What it changes, counted on the committed `hitters.json` (verified)

MLB hitters (`Lev` = MLB). "Gain" = hitters who become eligible at a position.

| League | n | corner 45 applied (BLM, SSB; RG by basis): flag changes | Best Pos / Max WAA / MAX WAA P changes | ours (his → ours): gain, lose | Best Pos / Max WAA changes under ours |
|---|---|---|---|---|---|
| BLM | 460 | 58 (LF and RF, same 58) | 0 / 0 / 0 | LF 58, RF 58; lose 1B 5, SS 4 (66 hitters in all) | 1 (SS to 3B, Max WAA −1.295; MAX WAA P changes for the same hitter) |
| SSB | 475 | 56 | 0 / 0 / 0 | LF 56, RF 56; lose 1B 1, SS 3 (60 in all) | 0 |
| TGS | 407 | 0 under the patch (48 if 45 were forced on) | 0 / 0 / 0 | lose 1B 4 | 0 |
| RG | 396 | 62 | 0 / 0 / 0 | lose 1B 1, SS 1 | 0 |

Whole files, all levels: BLM `hitters.json` 6,545 rows, 1,176 flag changes under rec; SSB 6,866 rows,
1,174. The park, draft and free-agent files carry the same flags and change in step (flag
changes under the 45 rule: BLM `hitters_draft.json` 6 of 78, `hitters_draft_all.json` 84 of 409; RG
`hitters_draft.json` 96 of 702; TGS `hitters_draft.json` 6 of 21 if 45 were forced on TGS, 0 under the
patch). No Best Pos, Max WAA or MAX WAA P in any of them changes under the 45 rule.

The MLB hitters whom our rule demotes and the usage behind it:

- BLM, lose 1B (IF ERR 20): Stuckey (MIN), Bartfield (TEX), Houghton (CWS), Megginson (ARI), de la Paz (SEA).
  Real innings at 1B in 2057 or 2058: 0 for all five.
- BLM, lose SS (TDP < 45): Gardner (KC) and Pereira (PHI) with 0 innings; Rueda (SF) 41 in 2057 and 643 in
  2058; **Ferreira (HOU) 862 in 2058.**
- SSB, lose 1B: Albrecht (CHC), 29 innings at 1B; lose SS: McCullough (NYM) 0, Landers (SF) 7, Hazley (SF) 18.

**Positional Strength board** (the app's own `positionalStrength.js` run unmodified by
`docs/phase2/strength_effects.mjs`, on each league's MLB clubs; verified): under the 45 flags, **no BLM
club changes at any position.** In SSB one club changes:
Nashville Stars. Austin Bednarik moves from RF to 3B, so their 3B score goes from −0.69 to +2.02 WAA
(rank 22 to 6 of 28) and their RF score from +0.17 to −1.32 (rank 16 to 27), because a hitter who is newly
RF-eligible (David Nanez) takes RF. The solver fills all nine slots together, so the lineup total rises
by 1.2 WAA. The other 27 clubs' scores are untouched; their ranks at those two positions shift by up to
16 places only because Nashville's score moved past them. No other position changes in SSB.

## 7. Downstream readers of the `Eligible` flags (grep, verified)

Direct readers of `<pos> Eligible` (all in the app; nothing in draft or park code reads them):

| File | Use |
|---|---|
| `src/lib/rosterOptimizer.js` (`isEligible`, `getEligiblePositions`, `canPlay*`) | every lineup, bench-role and platoon decision in the Roster Optimizer; also the entry point used below |
| `src/lib/positionalStrength.js` (`getEligiblePositions`) | Positional Strength board: who may fill each of the nine slots |
| `src/lib/waivers.js` | which positions a waiver claim is scored at |
| `src/lib/orgBuilder.js:108-112, 281` | player type (C / IF / OF) and `eligibleAt` in the Org Builder |
| `src/lib/seriesPlanner.js:204` and `src/pages/SeriesPlannerPage.jsx:34` | Series Planner lineups |
| `src/pages/RosterOptimizerPage.jsx:222` | catcher detection |
| `src/lib/columns.js:108, 864-871` | the eight Eligible columns shown in tables |

Indirect readers, through `Max WAA vR/vL/wtd`, `Best Pos`, `MAX WAA P`, `Off Runs P`, which
`engine/hitters.py` builds from the flags (`_eligible_pos`): `ingest/draft.py:353` (draft peak =
`MAX WAA P`); `src/lib/draftFV.js`, `g5FV.js`, `futureValue.js`, `marketValue.js`, `devSignals.js`
and `PlayerDetail.jsx:427` (Best Pos); and the dev and ML code that reads the shipped value as a
target or input (`engine/agecurve_fit.py:180`, `backtest/ml/reprice.py:107`, `backtest/dev_signals.py`,
`backtest/dev_odds.py`). **None of these values moves under the corner-45 rule on the committed data**,
so none of those fits or caches is invalidated by it (inferred for the cache hash; verified for the values).

Writers: `engine/hitters.py` only. `engine/fielding_curves_fit.py:67-69` carries its own copy of the
floors (`elig_min`) for its gate; the patch leaves it (section 8).

Files that carry the flags and would be regenerated if the rule is wired (by the normal refresh / build,
not by hand): `public/data/{BLM,SSB,TGS,RG}/hitters.json`, `hitters_park.json`; `{BLM,TGS,RG}/hitters_draft*.json`;
`TGS/hitters_fa.json`; the root `hitters.json`, `hitters_draft.json`.

## 8. The patch (not applied): `docs/phase2/eligibility_corner_of_45.patch`

One hunk in `engine/hitters.py`. It adds `OF_CORNER_MIN = {"BLM": 45}` beside the existing `SB_CAP`
per-league table (same pattern), reads `OFC = OF_CORNER_MIN.get(league, 50)` where the `elig` dict is built,
and uses `OFC` for LF and RF. The key is the *calibration* league passed to `compute`, so TGS stays at 50 and
BLM, SSB and RG (BLM basis, inferred) get 45. To force 45 everywhere, change the dict to a plain `45`.
`git apply --check` passes against this branch (verified).

Verification with the patch applied in the worktree, then reverted (all verified):

- `python tgs-viz/engine/hitters.py BLM` and `... TGS` print byte-identical output before and after.
  The printout already shows large differences from the sheet before the change (for example `Max WAA wtd`
  max abs diff 1.72 on BLM); that is not caused by the patch and not new.
- The patched `compute()` run over every eligible hitter in both sheets: on BLM (6,578 rows) every flag matches
  the tool's `rec` rule, and on TGS (4,253 rows) every flag matches the tool's `his` rule. For comparison,
  `his` differs from the BLM output on exactly 1,072 LF and 1,072 RF rows.
- The sheet itself still says 50. The patch makes the engine differ from the sheet for BLM, deliberately,
  as the engine already does for other cells (audit B8). Anyone who diffs a fresh BLM sheet export against
  the engine will see LF/RF flags differ for hitters at range 45.

**Blocked, not done.** `engine/fielding_curves_fit.py` gates engine-versus-simulation error to ±3 runs, and
only on ratings inside the eligibility band. `POS_META` hard-codes the LF/RF band start at 50 for every
league. `calib/BLM/fielding_curves.json` already holds the curve at 45 (knots at 35, 45, 50, ...; fitted on
the live population, and the 45 knot rests on n = 2 in the fit's own report), but no simulation check has
been run over 45 to 50. That needs his clone-sim archives. Until it is run, the 45 floor admits ratings whose
curve is fitted but not gated. When the BLM refit is next run, `elig_min` for LF and RF should be 45 for BLM
and 50 for TGS; I did not edit `POS_META` because it is shared and the edit would be a per-league override
in the fit loop.

## 9. Flags and how each is resolved

| # | Flag | Resolution |
|---|---|---|
| 1 | Usage reflects how OOTP's own AI deploys players, which uses its own position ratings, not our floors | 🔵 Stated. A floor is judged by whether real regulars sit below it, not by a claim that OOTP uses it. |
| 2 | Scout noise could blur floors | Checked: MLB fielders agree across three pulls on ≥ 98.6% of rows. Not a driver. |
| 3 | Unknown throws and height | Treated as passing; 3.2% / 0.4% / 1.5% of innings. Reported in the tool. |
| 4 | The 3% criterion is an assumption | 🔵 Stated in section 2. The LF/RF conclusion holds at every innings cut tried (1, 45, 300) and in each of the three BLM and SSB league-seasons; the criterion only picks 45 over 40. |
| 5 | Prior audit disagrees on SS TDP (0.28% versus 1.2%, two regulars) | Different inputs; the data on disk decides; two named players. |
| 6 | Ratings are from 2057/2058; flips are counted on the 2058 `hitters.json` ratings | Different vintages; flips are counts of the rule applied to today's ratings, usage is about the rule. |
| 7 | The 45-50 curve band is un-gated | Blocked on sim data; the fit's `POS_META` needs a per-league override when the BLM refit runs (section 8). |
| 8 | SSB has one OOTP 27 season, 28 clubs | LF/RF result has the same sign in both BLM seasons and in SSB; a second SSB season would tighten it. |
| 9 | `hitters_fa.json` (TGS) has no WAA columns | The tool skips Best Pos for rows without them (tested). |
| 10 | TGS shows no corner-OF problem, BLM and SSB do | The patch is per calibration league, not global. Why the leagues differ (talent mix or deployment) I did not establish. |
| 11 | RG has no usage data and follows the BLM basis | Listed as a decision; 62 RG MLB hitters would gain LF/RF flags. |

## 10. Reproduce

```
python tgs-viz/tools/eligibility_usage.py --flips --json docs/phase2/eligibility_usage.json \
    --ratings-db <main checkout>/tgs-viz/backtest/ratings_history.db
node docs/phase2/strength_effects.mjs BLM SSB
python -m pytest tgs-viz/tools/tests/test_eligibility_usage.py -q
```

`ratings_history.db` is gitignored, so a worktree must be pointed at the main checkout's copy. The SSB
2043 files are read from the ootp-dashboard checkout (`--ootp-root`, default
`/Users/alex/Projects/ootp/dashboard/ootp-dashboard`).
