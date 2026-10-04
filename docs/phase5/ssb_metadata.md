# SSB's own metadata (season 2043) and how far it sits from BLM's

Status 2026-10-04. Analysis only: SSB is still priced on BLM's calibration, and nothing under
`engine/calib/`, `public/data/` or the sheets was written. Every output is under
`tgs-viz/backtest/.dev_cache/ssb_metadata/` (gitignored).

Marks: **[computed]** = produced by a run this session; **[inferred]** = my reading of why, not
confirmed against the game; **[from caller]** = reported to me, not re-run.

## What this means

1. SSB's metadata can be built from StatsPlus plus the dashboard's own CSVs, entirely offline, and the
   result agrees with the dashboard's independent code on 102 of 113 constants to 1e-6 relative **[computed]**.
2. Pricing SSB's 944 MLB-level players with SSB's constants instead of BLM's leaves each player's rank
   inside his role almost unchanged (Spearman rank correlation 0.9985 to 0.9997 per role) but moves
   the role baselines: hitters -0.10 WAA, relievers +0.17 WAA, starters -0.003 WAA (mean change in a
   player's WAA per 600 PA for hitters, 800 BF for starters, 300 BF for relievers) **[computed]**. That is a level difference between roles,
   not a different shape.
3. Two inputs of the SSB build are not like BLM's, and both bias the pitcher constants: SSB's SP / RP
   files are not true as-starter / as-reliever splits (section 3), and the calibrator divides league
   innings by a fixed 30 teams while SSB has 28 (section 7; no effect on prices today).
4. The ratings vintage matters for hitters: building with the 2044-05 pull instead of the season-end
   ratings lowers the SSB hitter baseline by 0.117 WAA, and moves fielding anchors by up to 2.1 rating
   points **[computed]**.

## 1. What was pulled

Nine StatsPlus reads (approved, done once before this session) **[from caller]**:
`/date`, `/teams`, batting split 1 (overall), 2 (vs L), 3 (vs R), pitching split 1, 2, 3, fielding
split 1. The saved replies are in `tgs-viz/ingest/.cache/metadata_ssb_2043/` (7 stat feeds) and
`.cache/sp/ssb/teams.json.gz`. The in-game date at the pull was 2044-05-09; the season built is 2043.
The archive holds no SSB pull from 2043, so the ratings the fork could use were the 2044-05-09 ones.

Every run that could reach StatsPlus (`metadata_inputs.py`, the calibrator, the pricing runs, the test
suite) ran under a socket guard that blocks and logs any non-loopback connection: **0 attempts** logged
**[computed]**.

## 2. Sources per tab (`ssb_metadata/2043/`, the primary build)

| Tab | Source | Rows |
| --- | --- | --- |
| Hitting_Data | StatsPlus batting feed, summed over team stints | 491 hitters |
| Pitching_Data | StatsPlus pitching feed | 482 pitchers |
| Fielding_Data | StatsPlus fielding feed, one table per position | C..RF 74 / 189 / 169 / 166 / 163 / 189 / 145 / 192 |
| SP_Data, RP_Data | the dashboard's `sp_data.csv`, `rp_data.csv` (`--paste-dir`) | 238 / 244 |
| Batter_Ratings | the dashboard's `batter_ratings_vr/vl.csv` (`--ratings-dir`) | vR 490 / vL 485 |
| Fielding_Ratings | the dashboard's `fielding_ratings.csv`, pitchers dropped | 486 position players (462 pitchers left out) |
| SP_Ratings, RP_Ratings | the dashboard's `pitcher_ratings_vr/vl.csv`, kept for the SP / RP file's pitchers | SP 238 / 238, RP 242 / 243 |

Second build `2043_ratings2044-05/`: same stat tabs, but the batter and fielding ratings come from the
2044-05-09 StatsPlus pull (moved aside from the primary; nothing deleted). A third copy,
`2043_fieldIP-C-RF-only/`, tests one definition (section 5).

The dashboard's files come from OOTP's own export screens, saved by hand at the start of the playoffs
(`docs/OOTP_EXPORT_GUIDE.md` in his repo) **[from his docs]**.

## 3. Cross-check of the StatsPlus stat tabs against the dashboard's 2043 files **[computed]**

League totals, mine / his:

| Tab | Counts | Totals |
| --- | --- | --- |
| Hitting | 491 / 491 players, same ids | PA 173,223 both; AB 155,689; H 38,373; HR 5,246; BB 13,865; SO 38,453; R 19,203; SB 3,132; CS 976; HBP 1,897; SF 1,197 all equal |
| Pitching | 482 / 482, same ids | IP 40,681.67 (outs-exact); BF 173,223; ER 18,024; R 19,203; HA 38,373; HR 5,246; BB 13,865; K 38,453 all equal |
| Fielding | every position table has the same row count and same ids | IP 40,681.67 at each position; PO, E, BIZ-R and BIZ-Rm equal at each position |

Per player, PA / H / HR / BB / SO agree for all 491 hitters and BF / IP / ER / K for all 482 pitchers.

Where they differ, and why:

- **UBR (extra-base baserunning runs):** league total -96.84 mine vs -99.19 his; 8 of 491 hitters differ,
  by up to 1.88 runs each. His file carries the last team stint's value for a player who changed teams;
  the feed sums the stints. Checked on 4 players: his value equals the last stint's row in the feed
  exactly (for example id 60404: -0.4067 = stint 2, mine -1.4176 = both stints).
- **ARM (fielding arm runs):** 7 player-position rows differ at LF / CF / RF / 3B for the same reason
  (LF total -14.46 mine vs -14.02 his; RF 41.16 vs 39.94).
- **ZR (zone rating):** differs at every position but C; the calibrator never reads it.
- **ORG:** 112 of 491 hitters show another team. Mine is the team in the 2044-05 pull, his is the team
  at the time **[inferred]**. ORG is not used by any constant. 3 players show "ID n" for a name because
  they are not in the pull.
- **Fielding_Ratings IP:** his file's innings include a position player's innings pitched (for example id
  57716: 47.1 at P). The calibrator's innings-per-PA ratio and the DH innings use this column.
  Section 5 measures it.

### The role files are not as-starter / as-reliever splits **[computed]**

The two role files in the dashboard are a partition of pitchers, not a split of each pitcher's games:
238 pitchers in `sp_data.csv`, 244 in `rp_data.csv`, 0 in both, 482 in union (= all pitchers). The SP
file has 7,896 appearances and 4,536 starts; 116 of its 238 pitchers also relieved (3,360 relief games)
and those games sit in the SP file. The RP file has 0 starts. BLM's paste is a true split (267 SP rows
with games = starts in every row, 392 RP rows, 136 pitchers in both).

My estimate that about 18,600 batters faced in the SP file are relief work (15% of the SP file's 124,736
BF, 28% of the league's relief BF) rests on 23.53 BF per start measured from the 122 pure starters
**[inferred]**. StatsPlus has no stats split by role, so the exact split cannot be rebuilt. The
constants that depend on it are the SP / RP wOBA weights, RA/9 SP and RA/9 RP, the SP / RP rate rows
and (through BF weights) the SP / RP rating anchors.

## 4. Roles stage, offline **[computed]**

`metadata_inputs.py --league SSB --year 2043 --stage roles --offline 2044-05-09 --paste-dir <his 2043 dir>`:

| Result | Count |
| --- | --- |
| Pasted pitchers matching the season totals exactly (BF, HA, HR, BB, K, R, IP outs) | 482 of 482 (100%; the stop threshold is 50%) |
| Partial (a role short of the season) | 0 |
| Above the season total (the playoff-game case) | 0 |
| IDs with no MLB pitching in 2043 | 0 |
| MLB pitchers in neither file | 0 |

All flags are empty, so `--accept-paste` was not needed and not used. The other-season check was not
triggered (no request, none needed).

## 5. Ratings vintage **[computed]**

His 2043 rating files are the scouting snapshot `leagues/SSB/ratings/ratings_scout_2043-09-28.csv.gz`:
every rating column matches it on every player (490 hitters x 14 columns, 481 pitchers x 9 columns, 948
fielding rows x 10 columns, all 100%). 2043-09-28 is the newest 2043 snapshot in his archive and falls
before the 2043-10-01 cut-off the fork's `season_end_pull` uses. I did not confirm the last
regular-season day. The same player's ratings in the fork's 2044-05-09 pull are equal on only 79% to
92% of hitters per column (for example POW vR 79%, SPE 92%).

So the primary build uses his files (season-end ratings) and the 2044-05 build is kept for comparison.
The fork's pull holds scouting ratings too, so the two sources are the same kind of rating, a different
date.

Fielding-ratings innings: replacing his total fielding innings (16 position players differ from the
C..RF sum; I checked id 57716, who has 47.1 innings at P) with the C..RF sum moves the positional adjustments by at most 0.09 runs per 1,200
innings (DH -9.47 to -9.56) and nothing else **[computed]**. The primary build keeps his column.

## 6. The calibrator, run on both builds **[computed]**

`engine/metadata_calibrate.py --inputs-dir <dir> --json <dir>/metadata-latest.json`, on `2043/` and on
`2043_ratings2044-05/`. 373 cells each, the same set as BLM's `calib/BLM/metadata-latest.json`.

Audit of the numbers (inputs: 🟢 computed from SSB's real data; 🟡 constants borrowed from the
workbook; 🔵 deliberate assumption):

- 🟢 all stat-derived constants (run environment, wOBA weights, rates, matchups, fielding rates).
- 🟢 rating anchors, from his season-end files.
- 🟡 PA 600, PA catcher 500, IP 1200, IP catcher 1000, BF 800, BF RP 300, RunCS (pitching) -0.4049, and
  the out values 0.75 / 0.90 (F38 / F39) are hand-entered in the workbook and equal in BLM's file and
  SSB's. The dashboard derives 0.7015 / 0.8295 for SSB instead; the calibrator has
  `--derived-out-values` for that and I did not use it.
- 🔵 "Team IP" divides league innings by 30 teams (section 7).

Independent check: I ran the dashboard's own aggregators (read-only, no cache written) on his raw
2043 files and mapped 113 constants to the calibrator's cells. **102 agree to 1e-6 relative.** The 11
that differ:

| Cells | Difference | Reason |
| --- | --- | --- |
| STU SP / RP anchors (T2, T7) | author 47.32 / 51.92, dashboard 46.44 / 52.70 | the dashboard moves Stuff by 5 between SP and RP by listed position [inferred, from his pipeline doc] |
| 1B / 3B / SS / RF fielding anchors (I9, I19, J19, I23, J23, I39) | author lower by 0.3% to 0.6% (0.2 to 0.4 rating points) | the workbook rule that a player with position innings and no ratings row counts as rating 0: 1B 0.55% of innings, 3B 0.44%, SS 0.55% belong to players without a ratings row (Kevin Naclerio, id 64416), and 1 - 0.0055 matches the ratio of the two answers [computed] |
| LF / CF / RF arm (M21, M25, M29) | author -0.426 / -0.410 / 1.214, dashboard -0.414 / -0.410 / 1.178 | the last-stint ARM effect of section 3 |

Positional adjustments (P2..P10) are not compared this way: the dashboard's and the calibrator's
algorithms differ and the dashboard's own answers change by up to 3.4 runs when the pitchers' rows are left in
or out of the fielding ratings (C 14.40 vs 11.04, LF -9.88 vs -6.91). Live pricing does not read the calibrator's
positional adjustments for SSB at all: `pos_adj_overlay.json` overrides W2..W10.

## 7. SSB against BLM

Full table, all 175 constants, BLM / SSB season-end / SSB 2044-05 / differences / percent:
`ssb_metadata/metadata_comparison.csv`. Percent is of |BLM|. "Vintage" = 2044-05 minus season-end.

**Rating anchors** (the PA- or BF-weighted league average rating, 20-80 scale):

| Anchor | BLM | SSB season-end | SSB 2044-05 | SSB - BLM | % | vintage |
| --- | --- | --- | --- | --- | --- | --- |
| hitting Eye | 48.71 | 48.63 | 48.77 | -0.07 | -0.2% | +0.14 |
| hitting Power | 47.70 | 49.04 | 48.40 | +1.35 | +2.8% | -0.64 |
| hitting AvK | 52.93 | 52.85 | 52.81 | -0.08 | -0.1% | -0.04 |
| hitting BABIP | 52.08 | 52.01 | 51.32 | -0.07 | -0.1% | -0.69 |
| hitting Gap | 52.69 | 52.10 | 51.46 | -0.59 | -1.1% | -0.64 |
| hitting Speed | 49.70 | 49.16 | 49.12 | -0.54 | -1.1% | -0.05 |
| hitting Stealing | 48.47 | 48.91 | 48.95 | +0.43 | +0.9% | +0.05 |
| hitting Baserunning | 53.50 | 54.98 | 55.00 | +1.48 | +2.8% | +0.02 |
| SP STU | 47.42 | 47.32 | 46.92 | -0.09 | -0.2% | -0.40 |
| SP Hold | 57.67 | 55.87 | 55.84 | -1.80 | -3.1% | -0.04 |
| SP HRA | 50.66 | 51.81 | 51.43 | +1.15 | +2.3% | -0.38 |
| SP pBABIP | 50.69 | 51.53 | 51.35 | +0.85 | +1.7% | -0.18 |
| SP CON | 48.95 | 50.33 | 50.05 | +1.38 | +2.8% | -0.28 |
| RP STU | 49.27 | 51.92 | 50.84 | +2.64 | +5.4% | -1.07 |
| RP Hold | 55.80 | 55.02 | 55.19 | -0.78 | -1.4% | +0.17 |
| RP HRA | 47.98 | 48.96 | 48.77 | +0.98 | +2.1% | -0.20 |
| RP pBABIP | 49.82 | 49.30 | 49.17 | -0.52 | -1.0% | -0.13 |
| RP CON | 47.36 | 46.67 | 46.46 | -0.69 | -1.5% | -0.20 |

**Other constants that differ by more than 4%** (SSB season-end; the 2044-05 value is identical for
every stat-derived row, because only ratings change with the vintage):

| Constant | BLM | SSB | SSB - BLM | % |
| --- | --- | --- | --- | --- |
| RA/9 relievers (T42) | 4.346 | 4.005 | -0.342 | -7.9% |
| RP wOBA scale (W37) | 1.240 | 1.280 | +0.039 | +3.2% |
| RP CS weight (W36) | -0.494 | -0.456 | +0.039 | +7.8% |
| SP wOBA scale (T20) | 1.253 | 1.233 | -0.020 | -1.6% |
| pitching matchups LvR / RvR / OVR vR (T23, T24, T26) | 0.775 / 0.612 / 0.659 | 0.744 / 0.582 / 0.628 | -0.031 / -0.030 / -0.031 | -4.0% / -5.0% / -4.7% |
| hitting HR% / XBH% (B34, B37) | 0.0320 / 0.2502 | 0.0334 / 0.2395 | +0.0015 / -0.0107 | +4.6% / -4.3% |
| SP HR% (W4) | 0.0309 | 0.0335 | +0.0027 | +8.6% |
| RP XBH% / 3B% (W19, W20) | 0.2537 / 0.0719 | 0.2354 / 0.0683 | -0.0183 / -0.0036 | -7.2% / -5.0% |
| fielding errors per play made: 1B / 3B / LF / CF (M7, M14, M20, M24) | 0.0298 / 0.0443 / 0.0131 / 0.0082 | 0.0249 / 0.0408 / 0.0102 / 0.0073 | -0.0049 / -0.0035 / -0.0029 / -0.0009 | -16.5% / -8.0% / -22.3% / -11.6% |
| double plays per 1200 innings: 2B / SS (M11, M30) | 82.2 / 70.3 | 73.6 / 62.6 | -8.6 / -7.6 | -10.5% / -10.9% |
| arm runs per 1200 innings: LF / CF / RF (M21, M25, M29) | -0.764 / -0.319 / 1.448 | -0.426 / -0.410 / 1.214 | +0.338 / -0.092 / -0.234 | +44% / -29% / -16% |
| fielding anchors: 1B Range / Error | 47.79 / 46.84 | 43.88 / 42.86 | -3.91 / -3.99 | -8.2% / -8.5% |
| fielding anchors: 2B Arm / TDP | 54.18 / 59.85 | 50.80 / 57.36 | -3.38 / -2.49 | -6.2% / -4.2% |
| fielding anchors: SS Arm / Error / TDP | 64.45 / 63.97 / 64.66 | 60.26 / 59.92 / 60.06 | -4.19 / -4.06 / -4.60 | -6.5% / -6.3% / -7.1% |
| positional adjustments (P2..P10): C / 1B / 2B / 3B / SS / LF / CF / RF / DH | 9.65 / -4.87 / -2.14 / -0.20 / 6.93 / -3.77 / 2.15 / -3.77 / -6.80 | 12.56 / -6.93 / 2.75 / 1.11 / 8.20 / -5.52 / -1.52 / -5.52 / -9.47 | +2.9 / -2.1 / +4.9 / +1.3 / +1.3 / -1.7 / -3.7 / -1.7 / -2.7 | not used in live SSB pricing |

Run environment (not >4%): hitting wOBA 0.3073 BLM, 0.3098 SSB (+0.8%); R/PA 0.1129, 0.1109 (-1.8%);
WAA constant 9.464, 9.372 (-1.0%); RA/9 starters 4.284, 4.343 (+1.4%).

Constants that look off for a reason of their own:

- **Team IP (T38) and Pen IP (T39)** divide league innings by a fixed 30 teams (`metadata_calibrate.py`
  line 446). SSB has 28 teams (28 team ids in the feed; each team started 162 games). SSB's Team IP
  is 1,356.1 where 40,681.67 / 28 = 1,452.9, and Pen IP 416.6 where it should be about 513.5 **[computed]**.
  `pitchers.py` never reads the cells these map to (no reference to H38 / H39), so prices are
  unaffected today **[computed, by search]**.
- **RA/9 relievers** at -7.9%, **RP wOBA weights** and **RP XBH%** follow from the role files (section 3):
  SSB's relievers allow 4.005 runs per 9 and starters 4.343, where in BLM relievers allow more (4.346 vs
  4.284). Selecting "pitchers who never started" as the RP file and putting swingmen's relief work in the SP
  file would push the numbers this way **[inferred]**.
- **Hitting league UBR** is 20% off in relative terms on a base near zero (-0.0006 vs -0.0007).

## 8. Does it move prices? **[computed]**

Method: `tgs-viz/backtest/ssb_metadata_compare.py pricing`. It prices the latest SSB pull
(`statsplus_ssb.json`, 14,003 players) with the engine twice, in memory: with BLM's Data Points as they
stand (they equal `calib/BLM/metadata-latest.json` cell for cell: 182 mapped cells, 0 differences), and
with SSB's metadata cells laid over them. As in the Update task, SSB's own positional adjustments and
replacement credits are applied in both, and the BLM calibration layers stay BLM's (currency, hitter
tails, fielding curves, S-curves, role stuff). Sanity: laying BLM's own metadata back on BLM's Data Points
changes WAA by 0.0 for every player. WAR = WAA + one constant per role, so the WAR shift is the WAA
shift.

Shift = price with SSB's metadata minus price with BLM's, in WAA per 600 PA (hitters) or per 800 BF
(starters) or 300 BF (relievers):

| Players (LgLvl 1 = MLB, n) | Mean | SD | Mean abs | 5th to 95th pct | Largest | Rank corr. within group |
| --- | --- | --- | --- | --- | --- | --- |
| All MLB-level (944) | +0.001 | 0.152 | 0.113 | -0.139 to +0.228 | 0.758 | 0.9947 |
| Hitters (468) | -0.102 | 0.033 | 0.102 | -0.152 to -0.045 | 0.169 | 0.9997 |
| Starters (194) | -0.003 | 0.056 | 0.049 | -0.092 to +0.076 | 0.137 | 0.9985 |
| Relievers (282) | +0.175 | 0.159 | 0.175 | +0.047 to +0.580 | 0.758 | 0.9987 |
| All 13,968 priced players, hitters (6,871) | -0.079 | 0.026 | 0.079 | -0.120 to -0.044 | 0.169 | 1.0000 |
| same, starters (3,709) | -0.044 | 0.040 | 0.050 | -0.111 to +0.028 | 0.205 | 0.9999 |
| same, relievers (3,388) | +0.438 | 0.230 | 0.438 | +0.111 to +0.802 | 0.838 | 0.9999 |

Largest movers (MLB level): relievers David Nunez (-5.39 to -4.63 WAA), Orlando Avalos (-5.00 to -4.28),
Mike Thomas (-4.95 to -4.24); all are weak relievers whose price rises 0.7 WAA.

Which groups of constants do it (each swapped alone; SD of the WAA shift over the 944 MLB players):

| Group | SD | Mean |
| --- | --- | --- |
| RP wOBA weights | 0.087 | +0.052 |
| pitching league stats (RA/9, IP, R/PA, BF/IP) | 0.064 | +0.009 |
| hitting rates (BB%, HR%, SO%, BABIP, XBH%, 3B%, SB%, UBR, SBA%) | 0.063 | +0.062 |
| hitting league stats (wOBA, WAA constant, R/PA, ...) | 0.057 | -0.057 |
| SP rating anchors | 0.055 | -0.025 |
| hitting rating anchors | 0.055 | -0.052 |
| SP wOBA weights | 0.046 | +0.022 |
| RP rating anchors | 0.041 | -0.025 |
| RP rates | 0.032 | +0.020 |
| pitching matchups | 0.015 | -0.002 |
| fielding anchors (all 8 positions) | at most 0.012 each | at most 0.003 |
| hitter wOBA weights | 0.008 | -0.008 |
| positional adjustments | 0.000 | 0.000 |

Hitting rates and hitting league stats cancel each other's mean (+0.062 and -0.057); alone each moves
hitters by about 0.06. I did not split the group effects by role.

Vintage: pricing with the 2044-05 build instead of the season-end build raises hitters by 0.117 WAA
(SD 0.017), starters by 0.025, relievers by 0.029 (944 MLB-level players; rank correlation 0.9989 or
higher). Using the newest pull for a season-end calibration would therefore shift hitters about as much as
the BLM-versus-SSB difference itself (-0.102).

Limits: this swaps the Data Points cells only. The calibration layers fitted on BLM (S-curves, tails,
fielding curves) carry BLM's own anchors inside them and were left as they are, so the numbers show the
direct effect of the constants, not a full re-fit on SSB.

## 9. What it suggests for the open question

The question: does SSB need its own model set, or can the BLM models price it?

- The direct effect of SSB's own league constants is a baseline shift by role (hitters -0.10, relievers
  +0.17 WAA at MLB level), with within-role order almost untouched (rank correlation at least 0.9985).
  A per-role offset would correct most of it without a new model **[inferred]**.
- The part of the shift that comes from the role files and from the 30-team constant is an artifact of
  how SSB's inputs were prepared, not a property of SSB's league. Whether relievers really shift +0.17
  cannot be read before the role files are true splits **[inferred]**.
- The actual test needs the author's DEV vintages priced both ways (BLM constants and SSB constants),
  then the models' error on each. This build supplies the SSB side of it: `2043/metadata-latest.json`.
  Without those vintages the table above is all the evidence there is **[from the Phase 5 plan]**.

## 10. Decisions for you

1. Role files: keep the partition files as they are (cheapest; the RP block is the least reliable), or
   re-export true as-starter / as-reliever splits from OOTP for SSB before using its pitching constants.
2. Team count: make `Team IP` use the league's team count (a one-line change in his calibrator, not made
   here because it changes a value in his file and has no price effect).
3. Whether to use `--derived-out-values` for SSB (0.7015 / 0.8295 instead of 0.75 / 0.90).

## How to reproduce

    # StatsPlus stat tabs from the saved feeds, the rest from his CSVs, no request
    .venv/bin/python tgs-viz/ingest/metadata_inputs.py --league SSB --year 2043 --stage all \
        --offline 2044-05-09 --paste-dir <dashboard>/leagues/SSB/metadata/2043 \
        --ratings-dir <dashboard>/leagues/SSB/metadata/2043 --out tgs-viz/backtest/.dev_cache/ssb_metadata/2043
    .venv/bin/python tgs-viz/engine/metadata_calibrate.py \
        --inputs-dir tgs-viz/backtest/.dev_cache/ssb_metadata/2043 \
        --json tgs-viz/backtest/.dev_cache/ssb_metadata/2043/metadata-latest.json
    .venv/bin/python tgs-viz/backtest/ssb_metadata_compare.py table   --se <2043 dir> --alt <2044-05 dir>
    .venv/bin/python tgs-viz/backtest/ssb_metadata_compare.py pricing --se <2043 dir> --alt <2044-05 dir> --level 1

The 2044-05 build: the same command with `--stage auto` (ratings from the pull, no `--ratings-dir`) and then
`--stage roles --paste-dir ...` into a second folder.
