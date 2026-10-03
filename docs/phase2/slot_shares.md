# Phase 2, row 14: slot shares (depth weights)

*2026-10-03, branch `phase2/eligibility`, off `phase2-model`. Audit first: no app or engine file is
changed. The measured weights are a data file and the wiring is a patch that is not applied. Inputs are
tagged 🟢 computed from real data, 🟡 borrowed constant, 🔵 deliberate assumption. Each claim says whether it
was **verified** (run this session) or **inferred**.*

## 0. What this means for you

1. **His Positional Strength board assumes its depth weights; it does not measure them.**
   `src/lib/positionalStrength.js` scores a bat position as its starter alone (the next man up is shown but
   weighted 0), and scores the staff as the sum of the top 5 starters and the top 8 relievers at equal weight.
   Its header says so: depth weights "would have to be measured from the league's own distribution of playing
   time by depth slot", and the shipped rows carry no playing time. (Verified, read.) We now have that
   playing time for BLM, SSB and TGS, so the weights can be measured.
2. **Measured, they are not equal.** Pooled over 120 team-seasons (BLM 60, SSB 28, TGS 32), the starting
   hitter holds **0.63 to 0.71 of a position's innings** (C 0.67, 1B 0.67, 2B 0.64, 3B 0.67, SS 0.69, LF 0.63,
   CF 0.71, RF 0.66), the next man up 0.19 to 0.29, the third man 0.03 to 0.09. The rotation is not flat either: in BLM
   the fifth starter holds 0.113 of rotation innings against 0.244 for the first, and the sixth has 0.027.
   His equal weights treat the fifth starter as worth as much as the ace. (Verified.)
3. **Using them barely moves the board.** Once the next man up is floored at a replacement body (section 5),
   weighting by the measured shares leaves every bat position's club ranking at Spearman rank correlation
   0.98 to 1.00 with the shipped ranking in BLM and SSB, and moves no club by more than 5 places
   (SSB relievers: correlation 0.946, up to 5 places, 9 clubs by 3 or more). Measured weights and our borrowed
   constants rank clubs almost identically (correlation 0.988 or higher at every position in both leagues).
   So this is a correctness upgrade, not a rescoring. (Verified.)
4. **Pitcher curves are league-specific; hitter curves are not.** BLM and TGS starters match our constants
   within noise; SSB's rotation is flatter (first starter 0.183 against 0.244) with a long tail (the sixth to
   eighth starters hold 0.15 of innings against 0.04 in BLM). Hitter curves agree across the three leagues
   within sampling error, except shortstop in SSB (first man 0.621 against 0.726 in BLM, 2.5 standard errors).
   So I ship hitter curves that could be shared and pitcher curves per league. (Verified.)
5. **The floor on the next man up is a design choice I had to make, and it matters.** Without it, a club with a
   deep roster scored *lower* than a thin one. Details in section 5.

## 1. Where depth weights live today

| | His (`tgs-viz`) | Ours (`ootp-dashboard`) |
|---|---|---|
| Bat position score | starter's position WAA only; next man up (`depth`) displayed, weight 0 (`positionalStrength.js:109-130`) | `SLOT_SHARES.hit[pos]` weights the starter, next man, third man ... (`app/src/utils/constants.js:57`, applied in `strength.js`) |
| Staff score | sum of top 5 SP, top 8 RP, equal weight (`armGroups`, `numStartingPitchers` / `numReliefPitchers` = 5 / 8 in `rosterOptimizer.js:1152`) | `SLOT_SHARES.sp` (8 slots) and `.rp` (7 slots) |
| Where the weights come from | none: "a stated roster convention, not a fitted weight" | `model/tools/compute_slot_shares.py`: mean over team-seasons of each rank's share of team-position innings, from `leagues/*/metadata` (BLM-ATL 2058 and one other league's export, n = 58) |
| Bench in the Roster Optimizer | `benchCoverValue`: bench player counted at `1 − PRONE_FACTOR.Normal` = **0.10** of his WAA (`rosterOptimizer.js:577-592`, `PRONE_FACTOR` at 1113) | not applicable |

The 0.10 in his optimizer is a durability factor (🔵 assumed: how often a normal player misses a game),
not a measured depth share. Measured, the non-starters hold 0.29 to 0.37 of a position's innings, of which
the next man holds about 0.21. The two are different quantities (his bench term sits next to separate vR and
vL lineups that already model platooning, so part of the measured 0.33 is already counted), so I did not
treat the 0.10 as an error and have not proposed changing it. The comparison is recorded here because it
is the other place depth is weighted by an assumed number.

## 2. Input audit

| Input | Tag | Provenance and check |
|---|---|---|
| Innings by player, team and position, BLM 2057 | 🟢 | `backtest/actuals/BLM/2057` (`fielding.csv`, league 144, MLB), 30 clubs, 1,437 innings per club per position. (Verified.) |
| Same, TGS 2044 | 🟢 | `backtest/actuals/TGS/2044`, league 100, 32 clubs, 1,454 per club. (Verified.) |
| Same, BLM 2058 (hitters only) | 🟢 | `engine/calib/BLM/metadata_inputs`: stats sit with the player's current org, 1,434 per club. (Verified.) |
| Same, SSB 2043 | 🟢 | `leagues/SSB/metadata/2043/fielding_data_<pos>.csv`, 28 clubs, 1,453 per club. (Verified.) |
| Innings pitched, SP and RP | 🟢 | BLM 2057 and TGS 2044 from `pitching.csv` (1,437 and 1,454 per club, full coverage); SSB 2043 from `sp_data.csv` and `rp_data.csv` (1,453 per club). **BLM 2058 pitchers are dropped**: the metadata export covers 1,137 of 1,434 innings per club (released and retired pitchers are missing). (Verified.) |
| SP versus RP in actuals | 🔵 | SP = pitcher-team rows with GS ≥ half of G. Checked against the StatsPlus SP/RP split on BLM 2058: agrees on 100.0% of innings over 659 pitchers. (Verified.) |
| DH usage | 🟢 derived | No DH innings exist. DH starts = a player's batting starts minus his fielding starts. Per club 162 to 165 DH starts in BLM 2057, TGS 2044 and SSB 2043, the right total for a universal DH. (Verified.) |
| Team of a traded player | 🟢/🔵 | BLM 2057 and TGS 2044 keep a traded player's usage with the team he played it for (`team_id`). BLM 2058 and SSB 2043 attach a player's whole season to his current org, so a deadline acquisition's innings land on his new club. The effect is on rank shares only for the few traded players; not quantified. |
| The "Retired" pseudo-org in BLM 2058 | cleaned | Dropped: only orgs that field a catcher count. Our original script keeps it unless the org is `-`. |
| Averaging rule: the **mean** of each rank's share over team-seasons | 🟡 | Copied from ours (the share is left-skewed, so the mean leans toward depth). Not re-argued. |
| Pairing: the k-th best player *by WAA* gets the k-th largest *innings* share | 🔵 | Ours does the same. Real usage ranks by innings, which is not value order. Where a worse player takes more innings, the pairing overstates the value of depth. |

## 3. Measured weights (verified, `tgs-viz/tools/slot_shares.py`)

Mean share of the team-position total at each depth rank; "tail" is everything beyond the ranks shown.
BLM pools BLM 2057 (all positions) and BLM 2058 (hitters), 60 team-seasons (30 for DH, SP, RP). SSB 28 and
TGS 32 team-seasons. The standard error of the first-rank share is 0.014 to 0.041 for hitters, 0.004 to 0.009
for pitchers except SSB relievers (0.016) (from the spread across clubs).

| Pos | BLM | SSB | TGS | Ours (borrowed) |
|---|---|---|---|---|
| C | .684 / .275 / .037 | .679 / .298 / .020 | .649 / .309 / .039 | .674 / .283 / .038 |
| 1B | .711 / .175 / .066 | .671 / .186 / .085 | .593 / .231 / .089 | .698 / .189 / .066 |
| 2B | .641 / .214 / .093 | .637 / .225 / .078 | .639 / .203 / .099 | .680 / .208 / .070 |
| 3B | .674 / .197 / .075 | .627 / .228 / .096 | .708 / .177 / .065 | .686 / .224 / .063 |
| SS | .726 / .181 / .059 | .621 / .211 / .098 | .667 / .206 / .082 | .738 / .169 / .063 |
| LF | .633 / .213 / .080 | .669 / .190 / .068 | .595 / .194 / .113 | .664 / .204 / .077 |
| CF | .691 / .211 / .064 | .730 / .171 / .057 | .735 / .192 / .049 | .697 / .206 / .064 |
| RF | .673 / .197 / .078 | .638 / .186 / .094 | .635 / .201 / .090 | .705 / .185 / .071 |
| DH | .608 / .203 / .089 | .563 / .210 / .099 | .645 / .190 / .083 | none |
| SP, ranks 1-8 | .244 .227 .205 .182 .113 .027 .001 .000 | .183 .174 .163 .153 .134 .069 .049 .032 | .241 .222 .198 .157 .113 .042 .020 .007 | .244 .229 .195 .163 .103 .036 .016 .008 |
| RP, ranks 1-8 | .182 .151 .130 .118 .108 .094 .083 .061 | .241 .194 .160 .123 .105 .079 .045 .031 | .169 .137 .126 .111 .100 .088 .079 .066 | .224 .172 .149 .121 .096 .079 .054 (7 slots) |

Reading it:

- **Hitters: our borrowed constants are confirmed on independent data.** Ours came from BLM-ATL 2058 and one
  other league. They sit inside the BLM, SSB and TGS spread at every position (differences under 2 standard
  errors, except SS in SSB). I reproduced ours exactly with their script
  (`python model/tools/compute_slot_shares.py`, read-only run) before comparing.
- **SP: BLM and TGS reproduce ours** (first five ranks within 0.02). SSB's rotation is flatter: first starter
  0.183 against 0.244 (BLM), a difference of 5.7 standard errors; the sixth to eighth starters hold 0.15.
  This is the one place a single shared curve would be wrong. SSB clubs in 2043 average 5.4 starters with 100+
  innings against 4.5 in BLM 2057. (Verified; why SSB differs, I did not establish.)
- **RP: all three differ.** First reliever 0.169 (TGS), 0.182 (BLM), 0.241 (SSB), against 0.224 in ours; BLM's
  first three relievers sit 0.019 to 0.042 below ours, several standard errors (BLM standard errors are
  0.003 to 0.004). The reliever role rule in actuals (GS < half of G)
  puts bulk and long relievers in the pen, which lengthens the tail (TGS 0.124 beyond rank 8).
- **DH:** the starter holds 0.56 to 0.65. Ours has no DH entry. (Derived; see section 2.)

The full vectors, standard errors, tails and team counts are in `docs/phase2/slot_shares.json`
(`leagues.BLM`, `.SSB`, `.TGS`, `.ALL`; `sources` has each season on its own).

## 4. Why SP and RP weights are not simply "5 and 8 equal"

His count of 5 and 8 is the roster shape, and the measured curves agree with it as a count: in BLM and TGS
the first five starters hold 0.97 and 0.93 of starter innings. What is not supported is equal weight inside
it. Measured, the fifth starter holds 0.46 and 0.47 of what the first holds in BLM and TGS (0.73 in SSB), and
the eighth reliever holds 0.13 to 0.39 of the first (BLM 0.34, TGS 0.39, SSB 0.13). The shipped score therefore overstates the back of the
rotation and the pen relative to the ace and the closer, and it ignores the sixth starter, who holds 0.03 to
0.07 of innings.

## 5. What it does to the board (verified, `docs/phase2/strength_effects.mjs`)

The script imports the app's own `positionalStrength.js` and `rosterOptimizer.js` unmodified, feeds them the
committed `hitters.json` and `pitchers.json`, and recomputes each score with slot weights. It scores each league
on its MLB clubs only: the app passes a club list for TGS and BLM but not for SSB or RG, and for SSB the
fallback ("any org with 20+ players") keeps **22 foreign clubs with no MLB roster, so the shipped SSB board ranks
28 real clubs among 50 and 22 of them sit at replacement level.** That is a separate bug in the SSB board
(verified: `buildPositionalStrength` returns 50 teams for SSB with no club list; that the app passes none for SSB
is inferred from `LEAGUE_TEAMS` holding only TGS and BLM); I did not fix it.

**The floor.** Bat "next man up" in his module is the second solver pass over the players left after the
starting nine, and it can force a bench bat into a slot he cannot field. The distribution of that value over
the 169 filled backup slots in BLM: min −10.2, p10 −3.3, median −1.0, p90 +0.3 WAA. Weighted unfloored,
Cleveland (23 MLB hitters, backups at −5.6 to −10.2) fell from 13th to 30th at 2B, 16th to 30th at LF, and 17th
to 30th at 1B, while a club with *no* backup at a position was charged only the replacement level (−0.64) and
scored better. A deeper roster scored lower. So the weighted score floors a depth slot at the replacement body
(🔵: a club signs a replacement-level player rather than play a −10 fielder), keeps the starter and the
shipped 5 SP and 8 RP unfloored as today, and charges an absent arm at replacement as today. Unfloored,
correlations with the shipped board fall to 0.857 at BLM DH.

Spearman rank correlation between shipped and slot-weighted club rankings, with the league's own measured
curves, and the largest single move (places):

| Pos | BLM corr / max move | SSB corr / max move |
|---|---|---|
| C | 0.988 / 3 | 0.984 / 4 |
| 1B | 0.990 / 4 | 0.986 / 4 |
| 2B | 0.997 / 2 | 0.997 / 2 |
| 3B | 0.993 / 4 | 0.992 / 3 |
| SS | 0.999 / 2 | 1.000 / 0 |
| LF | 0.988 / 3 | 0.991 / 4 |
| CF | 0.996 / 3 | 0.997 / 3 |
| RF | 0.997 / 3 | 0.995 / 3 |
| DH | 0.986 / 5 | 0.998 / 1 |
| SP | 0.992 / 3 | 0.991 / 4 |
| RP | 0.988 / 4 | 0.946 / 5 |

Selected clubs, rank shipped to weighted:

| Club | Rank changes |
|---|---|
| Atlanta, BLM (of 30) | 1B 22 to 23, RF 10 to 11; every other position unchanged |
| New York (N), BLM | 2B 7 to 9, 3B 10 to 9, LF 25 to 22, CF 9 to 10; the rest within 1 |
| Atlanta, SSB (of 28) | 1B 13 to 17, SP 3 to 4; every other position unchanged |

Largest moves league-wide: BLM Baltimore DH 19 to 14, San Francisco 1B 26 to 22, Tampa Bay 3B 11 to 7;
in SSB the five largest are all relief boards, 5 places each (Arizona 11 to 6, Chicago Cubs 16 to 21, Chicago
White Sox 8 to 13, Kansas City 13 to 18, New York Mets 21 to 16).

## 6. The gated deliverables

- **Data file** `docs/phase2/slot_shares.json`: the weights for BLM, SSB, TGS and pooled, with standard errors.
  The engine and the app do not read it. TGS and BLM curves are for their own boards; SSB uses its own; RG has
  no usage data and would use the pooled `ALL` curve.
- **Wiring patch** `docs/phase2/slot_shares_wiring.patch` (not applied; `git apply --check` passes). It adds an
  optional `options.slotShares` to `buildPositionalStrength`. Unset, the module's output is **byte-identical** to
  today's: I compared the full cell JSON for BLM and SSB with and without the patch (verified). Set, the bat
  scores and the staff scores match an independent recomputation to 0 (verified, 0 difference on both leagues).
  The patch carries the replacement floor from section 5.
- **Display scale.** Staff scores in the patch are Σ share × WAA with the shares summing to about 1, so
  displayed SP scores shrink (BLM first club: 2.2 to 0.5 WAA) while bat scores keep their scale. Z-scores and
  ranks do not depend on the scale. If the displayed WAA must keep its old scale, multiply the SP weights by 5
  and RP by 8 when loading the file; nothing else changes.
- **Tool** `tgs-viz/tools/slot_shares.py` and its test `tools/tests/test_slot_shares.py` (pure tooling: reads
  files, writes only with `--json`).

## 7. Recommendation (a decision for you)

Do not wire it as a correction. The board's order barely changes, so there is no error to fix; it is a
choice about what the board means. If the board should answer "who plays at this position", weight by
measured shares; if it should answer "who is the best everyday player", keep the starter-only score. If you
do wire it:

1. Use the league's own pitcher curves (SSB differs materially) and the shared hitter curves.
2. Keep the replacement floor on depth slots.
3. Fix the SSB club list first (22 foreign clubs on the board), or SSB ranks stay compressed.

## 8. Flags and how each is resolved

| # | Flag | Resolution |
|---|---|---|
| 1 | Next-man-up value can be −10 WAA (forced slot) | Floored at replacement; shown above. |
| 2 | Pairing by value order, not usage order | 🔵 Same as ours; unchecked. A usage-ordered check needs per-player WAA joined to the season's innings, not done. |
| 3 | SP/RP split by a GS rule in actuals | Checked against the StatsPlus split: 100.0% of innings agree on BLM 2058. |
| 4 | BLM 2058 pitcher data cover 1,137 of 1,434 innings | Dropped from the pitcher curves; kept for hitters. |
| 5 | Traded players' innings land on the current org in BLM 2058 and SSB 2043 | Stated; not quantified. |
| 6 | SSB has one OOTP 27 season, 28 clubs | Its SP curve rests on 28 clubs; standard error of rank 1 is 0.005. |
| 7 | Role rule makes RP tails long (TGS 0.124 beyond rank 8) | The patch uses ranks 1 to 8 only. |
| 8 | SSB board ranks 28 clubs among 50 | Not this row's bug; noted for the user. |
| 9 | The 5 SP / 8 RP counts are his roster convention | Left as is; measured shares support 5 as the rotation size in BLM and TGS. |

## 9. Reproduce

```
python tgs-viz/tools/slot_shares.py --json docs/phase2/slot_shares.json
node docs/phase2/strength_effects.mjs BLM SSB
python -m pytest tgs-viz/tools/tests/test_slot_shares.py -q
```

SSB 2043 files are read from the ootp-dashboard checkout (`--ootp-root`, default
`/Users/alex/Projects/ootp/dashboard/ootp-dashboard`).
