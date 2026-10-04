# Phase 4 bridge — theme.js in the fork, and ours' accessor API over his records

Branch `phase4/bridge`. Wave 1 of Phase 4. This is the base every ported view builds on.

Two words used throughout:
- **Ours** is ootp-dashboard, `app/` on `main`.
- **His** is this fork's `tgs-viz`.

Legend:
- 🟢 computed from his data.
- 🟡 borrowed constant, with its provenance named.
- 🔵 deliberate assumption.

"Verified" means I ran it in this session. "Inferred" means I reasoned from context.

## 1. What a wave-2 port gets

| File | What it is |
|---|---|
| `tgs-viz/src/theme.js` | Ours' `design/redo:app/src/theme.js`, copied byte for byte under a one-line origin header. It imports nothing, so no imports needed adapting. Wave 2 imports `S`, `TOKENS` and the encoding helpers from here. Do not hand-edit it: re-copy it and regenerate `tokens.css` instead. |
| `tgs-viz/src/lib/accessors.js` | The adapter. It has every export of ours' `app/src/utils/accessors.js` under the same name and signature, plus about 85 new accessors that replace the direct `p.meta.*` / `p.ratings.*` / `p.contract.*` reads in ours' views. |
| `tgs-viz/src/lib/fvV21.js` | The subset of ours' `futureValue.js` the adapter needs: `calcFutureValue`, `calcCreditAge`, `devPercentileRank`, `typicalAtAge` and `DEV_CURVE_DEFAULTS`. The function bodies are verbatim. This is not his `lib/futureValue.js`, which is a different model. |
| `tgs-viz/tests/client/accessors.test.mjs` | 29 tests covering all 134 exports. The last test fails if any export is not exercised. |
| `tgs-viz/tests/client/fixtures/players_trim.json` | 18 whole records copied unmodified from `public/data`: 14 from SSB and 4 from BLM. The BLM records are the absent-key case. |

**tokens.css check (verified).** I ran ours' generator `app/docs/redesign/gen-tokens-css.mjs` against the fork's `theme.js`. Its output equals the fork's `src/tokens.css` exactly, apart from the fork's one-line "Copied from" header. It also equals ours' `app/src/tokens.css`. `design/redo` and `main` carry the same `theme.js`.

**The rule for wave 2.** A ported view calls accessors only. In practice:
- Replace every `p.meta.x`, `p.ratings…`, `p.positions…`, `p.contract…` and `p.Max WAR wtd` with the accessor named in §3.
- Do not port `p.meta?.x ?? p.X` fallbacks. Several column names mean different things in his data. For example, his `CON vR` is pitcher control, while ours' flat `CON vR` was hitter contact.

## 2. Ported exports → his columns

Notation:
- `{pos}` is an upper-case position.
- `{split}` is `vR`, `vL` or `wtd`.
- "null on BLM" means the key is absent until BLM, TGS and RG next pull.

The same holds for every row in this table: a missing key returns null, never a substitute.

| Export | His column(s) | Notes |
|---|---|---|
| `getWaa(p,pos,split)` / `getWaaP` | `{pos} WAA {split}` / `{pos} WAA P` | |
| `getWar(p,pos,split)` / `getWarP` | `{pos} WAR {split}` / `{pos} WAR P` | Null on BLM. There is no WAA + offset fallback. |
| `getRunsP` | `{pos} RunsP` | DH has none, so it returns null. |
| `isEligible` | `{pos} Eligible` (boolean) | DH is true for every hitter. That is ours' pipeline convention (`hitters.py` `"DH Elig": True`), and his rows carry DH WAA/WAR for every hitter (🔵). SP and RP are false, as in ours. |
| `pickFielderPos` | through `getWar` / `getWarP` | FV uses `fvV21.calcFutureValue`. On BLM it returns `{war:null, warP:null, fv:null}`. |
| `categorizeLevel`, `STANDARD_LEVELS`, `LEVEL_CATEGORY_ORDER` | his `Lev` | R+, R- and WL map to Rookie. FA and AMA map to null because they are not levels. His data has no plain "A" tier. |
| `passesLevelFilter` | `getLevel`, `getTeamId` (`Team`) | `"tm:<abbr>"` never matches, because no team abbreviation exists per row. |
| `passesPositionFilter` | as ours | Changed from ours: SP/RP split on the `Starter` flag, not on whether SP WAR is non-null. Otherwise every BLM pitcher would class as RP. On SSB the two tests are identical, because 5,355 of 5,355 starters carry `WAR wtd`. |
| `getPosRating` / `getPosPotential` | `{pos}` / `Pot{pos}` | `'0'` maps to null. On SSB the current and potential values are 0 together on every row. 0 is off the 20-80 scale, so it is treated as no rating (inferred). |
| `isCurrentlyEligible`, `eligibilityStatus`, `POS_RATING_MIN`=50, `POS_RATING_PCT`=0.75 | as ours | 🟡 Ours' display heuristic, not an OOTP rule. |
| `getMaxWaa` / `getMaxWaaP` / `getMaxWar` / `getMaxWarP` | `Max WAA {split}`, `MAX WAA P`, `Max WAR {split}`, `MAX WAR P` | The WAR values are null on BLM. |
| `getBatR` / `getBsr` | `BatR {split}` / `BSR {split}` | |
| `getSp*` (`Waa`, `WaaP`, `War`, `WarP`) | `WAA {split}`, `WAP`, `WAR {split}`, `WARP` | Gated on `Starter`. See below. |
| `getRp*` | `WAA {split} RP`, `WAP RP`, `WAR {split} RP`, `WARP RP` | |
| `getFloorWaa/WaR`, `getSp/RpFloor(War)` | none | Always null. His data has no floor projection. |
| `isInjured` | `OnDL` or `OnDL60` | Ours also counted StatsPlus `injury_is_injured`, which catches players who are hurt but not on the IL. His rows do not carry it. |
| `resolveKey` | per key | `Lev` reports INT through `IntlComplex`. `ORG` normalises `'0'` to `'-'`. `Price` is null without a contract. `STM` reads `STM`. `VELO` returns the `Vel` range string, and `num()` sorts on its lower bound. `OBP`/`wOBA vR/vL` return null on pitchers, because his pitcher rows reuse those names for wOBA against. Other keys fall through to `p[key]`, so his column names work as keys. |
| `genericSort`, `POS_SORT_ORDER`, `SORT_KEY_OVERRIDE` | as ours | `_bestPos` sorts through `getBestPos`. |
| `scaleRpWaaP` / `scaleRpWarP` | none | 🟡 `IP_SP` 185.47, `IP_RP` 69.55 and `RP_SCALE_THRESHOLD` −0.50 are ours' calibration and were not checked against his WAA. No WAR path uses them. |
| `pickPitcherRole`, `getBestPitcherWar/WarP/Fv` | through the `getSp*`/`getRp*` accessors | `devCurves` is ours' pipeline `meta.devCurve`, which his data does not ship, so `devPct` is null. `floorSort` is always null. On BLM every value is null and role defaults to `'rp'` (ours' rule). |
| `blendPlatoon` | none (arithmetic) | 🟡 Without `splits`, the weights fall back to ours' 62/38. |

**The `Starter` flag (verified on SSB).**
- Ours has two flags: `starter` (current pitch grades) and `starterP` (potential pitch grades). Both come from ours' pitch-count plus stamina gate.
- His rows have one flag, `Starter`, and SP columns exist only where it is true. 0 of 1,777 non-starters carry `WAA wtd`.
- His flag agrees with ours' gate on potential grades for 92.6% of SSB pitchers (6,607 of 7,132). It agrees with the current-grade gate for 72.7% (5,186 of 7,132).
- So `isStarter` and `isStarterP` both read `Starter`. A pitcher who is a starter only on potential has no SP projection in his data at all.

## 3. New accessors → his columns (they replace direct reads in ours' views)

Tri-state means the accessor returns true, false, or null when the row lacks the key. Null means unknown and must never be shown as "No".

| Ours read | Accessor | His column(s) |
|---|---|---|
| `_type`, `meta.isPitcher` | `isPitcher`, `getPlayerType` | Presence of `WAA wtd RP`, `WAA wtd` or `Starter`. A stamped `_type` wins. |
| `ID` / `id` | `getId` | `ID` |
| `meta.name` / `pos` | `getName` / `getPos` | `Name` / `POS`. His POS includes `CL`. |
| `meta.org` | `getOrg` (no org returns `'-'`), `getOrgId` | `ORG` / `Org` |
| `meta.team_id` / `meta.tm` | `getTeamId` / `getTeamAbbr` | `Team` / none |
| `meta.lev` | `getLevel` | `Lev`, or `'INT'` when `IntlComplex` is true. The export's IC flag is collinear with INT (Phase 3 `roster_fields.md`). |
| `isTrueFA`, draft-pool tags | `isFreeAgent`, `isAmateur` | `FA`, `Lev === 'AMA'` |
| `_age`, `meta.age`, `meta.dob` | `getAge`, `getDob` | `_age`, else `Age`, which is a whole number. `getDob` is null because there is no DOB. |
| `meta.bats` / `throws` / `ht` / `wt` | `getBats`, `getThrows`, `getHeightCm`, `getWeight` | `B`, `T`, `HT Sort`/`HT`, none |
| `meta.prone` | `getProne` | `Prone` |
| `meta.int/we/lea/loy/ad/fin` | `getIntangible(p,key)` | `Int`, `WrkEthic`, `Lead`, `Loy`, `Greed`. `ad` and `fin` return null. |
| `meta.ovr` / `pot` | `getOvr` / `getPot` | `Ovr` / `Pot` |
| none | `getScoutAccuracy` | `Acc` |
| `ratings.{vR,vL,potential}.x`, bare `ratings.x`, `fieldingRatings.*` | `getRating(p,key,split)` | Hitter contact is `Cntct_R/_L`, `PotCntct`. `ba` is `BA vR/vL`. Potential `ht` is `HT P`. Gap, power, eye and K use `GAP/POW/EYE/K {vR,vL,P}`. Pitchers: `STU`, `Mov_R/_L`/`PotMov`, `CON {vR,vL,P}` (control), `HRR`, `PBABIP`. Unsplit: `STM`, `HLD`, `SPE`, `STE`, `RUN`, `SR`, `SacBunt`, `BuntHit`. Fielding: `C ABI/FRM/ARM`, `IF/OF RNG/ERR/ARM`, `TDP`. There are no potential `spe/run/sr` columns, so those return null. |
| `pitchGrades.current/potential.x` | `getPitchGrade(p,pitch,pot)`, `PITCH_KEYS`, `getPitchCount` | `FB…KN` / `FBP…KNP`. `'0'` returns null. Ours' PitchingTab also reads `cu`, which is not a key in either dataset. |
| `meta.velo` / `vt` | `getVelo`, `getVeloPotential` | `Vel` / `PotVel` (range strings) |
| `_bestPos` | `getBestPos(p, matured)` | Hitters: `Best Pos WAR`, else `Best Pos`. Pitchers: ours' rule ported (see §5). A stamped `_bestPos` wins. |
| `meta.is_on_dl/_dl60` | `isOnIL`, `isOnIL60`, `getInjuryDaysLeft` | `OnDL`, `OnDL60`, `DLDays` |
| `meta.on40` | `isOn40Man` (tri-state) | `IsOnSecondary` (StatsPlus), else `On40Man` (export). See decision 2. |
| `meta.act` | `isActiveRoster` (tri-state) | `ActiveRoster`, else `IsActive` |
| `meta.r5` | `isRule5Eligible` (tri-state), `getYearsProtectedFromRule5` | `Rule5Eligible`, `YearsProtectedFromRule5` |
| `meta.opt` / `oy` | `getOptionsUsed` / `getOptionYearUsed`; `getOptionsRemaining` returns null | `OptionsUsed` / `OptionYearUsed` |
| `meta.rook` / `ic` / `yl` | `isRookie`, `isIntlComplex`, `getYearsLeftStatus` | `RookieStatus`, `IntlComplex`, `ContractStatus` |
| none (staleness) | `getRosterExportDate`, `getRosterExportGapDays` | `RosterExportDate`, `RosterExportGapDays` |
| `meta.is_on_waivers`, `dfa`, `days_on_waivers(_left)` | `isOnWaivers`, `isDFA`, `getWaiverDays`, `getWaiverDaysLeft` | `OnWaivers`, `DFA`, `WaiverDays`, `WaiverDaysLeft` |
| `meta.mld/mly/mlb_service_days_this_year/proy/secy/secd` | `getMlbServiceDays/Years/DaysThisYear`, `getProServiceYears/Days`, `getSecServiceYears/Days` | `MLBSvcDays/Yrs/DaysTY`, `ProSvcYrs/Days`, `SecSvcYrs/Days` |
| `meta.draft` | `getDraftYear` | none, so null |
| `meta.price`, `meta.cv`, `_price` | `getPrice`, `getSalary`, `getContractValue` | `Price` |
| `meta.dem` / `demSort` / `sign` / FA type | `getDemand`, `getDemandValue`, `getSignDifficulty`, `getFaType` | `ContractDemand` (the value is parsed from "$5.0m"), `SignDifficulty`, `FAType` |
| `contract.noTrade` | `hasNoTrade` | `NoTrade` |
| `contract.salaries/years`, `resolveContractYear(contract, yr)` | `getSalarySchedule`, `getContractYearsRemaining`, `getContractYear(p,yr)`, `getExtension` | `SalarySchedule` (remaining seasons) from `SalaryStartYr`, `ContractOptions` (`team` maps to `'club'`), `ContractExt`. Placeholder extensions with `yr` 0 or all-zero salaries return null. |
| `_projection.baseline`, `_salaryReport` | `getSalaryReportCell`, `getSalaryReportSpan`, `getArbProjection`, `getOptOutYears` | `SalaryReport`, `SalaryReportSpan`, `ArbProjection`, `OptOutYrs` |
| `batting.{split}.x`, `prospect.batting` | `getBattingStat(p,stat,split)` (`split` `'P'` for potential) | `{OBP,wOBA,BatR,HR,H-HR,XBH-HR,uBB,HBP,SO} {split}`. Hitters have potential `wOBA P` and `BatR P` only. |
| `baserunning.*`, `prospect.baserunning` | `getBaserunningStat` | `BSR/wSB/UBR {split}`, `SB%`. There is no potential baserunning. |
| `p[role].{split}.x`, `prospect[role]` | `getPitchingStat(p,role,stat,split)` | `{stat} {vR,vL,P}[ RP]`. Only wOBA, RA/9, WAA and WAR have a `wtd` split. |
| `meta.source/manual`, `meta.isTwoWay`, `injury_is_injured` | `getSourceTag`, `isTwoWay`, `isInjuredNotOnIL` | none. All three always return null. |

**Coverage on the saved data (verified).**
- SSB `Price` is set on 2,087 of 14,003 rows, the contracted ones.
- SSB `On40Man` and the other export keys are set on 7,308 of 14,003 rows. The export is dated 2043-12-28, against a pull dated 2044-05-09.
- `IsOnSecondary` is set on all 14,003 SSB rows.
- BLM has none of the Phase 1-3 keys: no WAR, no roster or export flags, no `SalaryStartYr`, no `ProSvc*`.

## 4. What each of ours' views loses on his data

Source: a read-only inventory of every scope file's reads (call sites in a sub-agent report, spot-checked). Everything listed here returns null, or is absent from his rows.

**Everywhere:**
- On BLM, TGS and RG, every WAR accessor returns null until their next pull. Boards that sort on WAR sort those rows last.
- Fields that ours' `processData` and `Dashboard` enrich step stamp on are not in his rows. Examples are `_war`, `_warP`, `_fv`, `_devPct`, `_role`, `_matured`, `_intangibles`, `_uid` and board `_*` keys. Wave 2 needs a port of that enrich step, built on these accessors.
- Data-level inputs are absent: `meta.devCurve`, `progressCurve`, `posAdj`, `platoonSplits`, `metaProjection`, `csvPresence`. As a result, Dev% is blank and FV uses `DEV_CURVE_DEFAULTS`.
- Ages are whole years, because his data has no DOB.

| View | Loses |
|---|---|
| PlayerProfile | Hitter potential OBP, HR and so on: only `wOBA P` and `BatR P` exist. All potential baserunning, including potential `spe/run/sr` ratings. Numeric velocity: a range string only. The Contract tab's `_projection` (ours' contract-projection baseline with per-year status, R5 year, MLFA year and options remaining). Use `SalaryReport` / `ArbProjection` for the years and show the rest as unknown. The "injured, not on IL" flag. `meta.source` tags. |
| Org (Overview, ActiveRoster, FortyMan, Lineup) | Ours' `bestPos` per-league DEF_SPECTRUM and arm split; his engine's `Best Pos WAR` replaces them. Dev%. On40/active status on BLM. The injured-not-on-IL set. |
| RosterPlanner / `rosterPlanning/*` | Draft year, so ours' R5 projection cannot run; show `Rule5Eligible` / `YearsProtectedFromRule5` instead. Options remaining. MLFA year. DOB. `_projection.baseline`. On BLM, every service and roster field. On SSB the roster-export fields are 133 game days old on the 2044-05-09 pull (`RosterExportGapDays` 133; `getRosterExportGapDays`). |
| DevAnalysis | `devCurve` / `progressCurve`, so the scatter overlays and percentile charts lose their reference curves. All WAR on BLM. |
| WaiverWire | `meta.waiv`, the CSV-export WAIV column. His `OnWaivers` is the StatsPlus flag, which ours already treats as authoritative, so the "CSV export only" section has nothing to show. |
| Prospects | Dev%. `meta.source/manual` (IAFA / draft tags); use `isAmateur`. FV uses the default curve settings unless the user saves some. |
| Scout | The `tm:` rookie-team grouping in LevelFilter; `team:` still works. |
| PlayerCompare | AD, FIN, DOB-based fractional age, numeric velocity. |
| DraftBoard | `meta.source` "Draft YYYY" tags; the pool must come from his `hitters_draft.json` / `pitchers_draft.json`, which this stream did not inspect. `demSort` exists on only 34 SSB rows. |
| Rule5Board | `Rule5Eligible` is the export's flag, present on SSB only, and stale (above). |

## 5. Hard-coded rules

**In ours' scope, from the inventory.** None of these are ported into the adapter. A wave-2 port must read the data field or show "unknown":
- `rosterPlanning/service.js:4-5,208,223`: Super Two, defined as the 2.xxx class of 344–516 days, at least 86 days prior-year accrual, and the top 22%.
- `service.js:146-153`: the service accrual rule.
- `eligibility.js:55-81`: arbitration at 3 years, free agency at 6, arbitration years 1–3.
- `eligibility.js:104-115`: Rule 5 at signing age ≤18 gives 5 years, otherwise 4; July-1 fallback; `ceil(5−proy)`.
- `eligibility.js:119-127`: MLFA after 7 pro years.
- `eligibility.js:133`: 3 options.
- `eligibility.js:184`, `crunch.js`, `RosterPlanner.jsx`, `DepthChartPanels.jsx`: the 40-man, 26-man and 14-inactive sizes.
- `projection.js:166-191,312-353,408-418`: the free-agency cap, option burn, last option year, and the 40-man count with IL handling.
- `projection.js:287-293`: 15-day versus 60-day IL semantics.
- `_shared.js:8`: `DAYS_PER_SEASON = 172`. His `serviceTime.js` measured 172 for SSB.
- `utils/waivers.js:26`: a 40-man limit of 40.
- `utils/prospects.js:18`: a prospect is anyone under 45 MLB days. This is ours' definition, not OOTP's.

**Adapter replacements:**
- `getOptionsRemaining` returns null.
- R5 comes only from `Rule5Eligible` and `YearsProtectedFromRule5`.
- Injury comes only from the IL flags.
- `getLevel` reads INT from the IC flag instead of inferring it.

**Non-OOTP constants the adapter keeps, all 🟡 from ours:**
- `POS_RATING_MIN` and `POS_RATING_PCT`.
- `SP_REPLACEMENT_WAP` −0.5 and `RP_ADVANTAGE_THRESHOLD` 1.0, used in pitcher `getBestPos`. These are calibrated on ours' WAR and were not checked against his WAR scale. See decision 1.
- `IP_SP`, `IP_RP` and `RP_SCALE_THRESHOLD`, used only by `scaleRpWaaP`.
- `DEV_CURVE_DEFAULTS`.
- The 62/38 platoon fallback.

## 6. Decisions for the user

1. **Pitcher best position.** His data ships no pitcher best position. The adapter applies ours' rule, which compares SP and RP WAR and uses thresholds of −0.5 and 1.0 on ours' WAR scale, to his engine's WAR. **Recommendation: keep it, but put the thresholds on the wave-2 audit list.** The alternative, his listed `POS`, ignores value.
2. **40-man source — decided 2026-10-04: StatsPlus first.** `isOn40Man` reads `IsOnSecondary`, then the export's `On40Man`; `isActiveRoster` reads `IsActive`, then `ActiveRoster`. The export is made by hand and may not be refreshed consistently; on the 2044-05-09 pull (export 2043-12-28) export-first gave Cleveland 37 active and Colorado 48 on the 40-man, StatsPlus 26 and ≤ 40.
3. **Price for uncontracted players.** Ours showed the league minimum, or the demand for free agents. The adapter returns null. **Recommendation: keep null.** The league minimum is a league setting this data does not carry.

## 7. Verified vs inferred

**Verified by running:**
- The `tokens.css` equality.
- All 134 exports exercised by `accessors.test.mjs`.
- The `Starter` agreement rates and the SP-column gating.
- The coverage counts in §3.
- `npm run build` passes.
- All `tests/client/*.test.mjs` and `control/test/{fileMap,guards,pythonMain}` pass.

**Inferred:**
- That position rating 0 means "no rating".
- That `IsOnSecondary` / `IsActive` mean 40-man / active (Phase 3's inference).
- The per-view call-site counts, which come from a sub-agent's grep and are lower bounds.

**Not exercised:** the adapter is not yet imported by any page, so the build only proves that the other modules still compile. The adapter itself was loaded and run under Node.
