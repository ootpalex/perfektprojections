/**
 * Column definitions for the data tables.
 * Based on actual extracted column names from the TGS sheets.
 */
import { formatMoney } from './marketValue';
import { DEV_FIELDS, GROW_KEEP, devShareTitle, devIsMl, devMlWords, devMlRangeNote, fmtGrow, fmtOdds, fmtVsTypical, fmtWaa } from './devSignals';
import { orgAbbr } from './orgAbbr';

// Dev signals (lib/devSignals.js): growth per game-year, Pot direction,
// MLB % / Starter % / Star % (the chance his peak reaches -1 / 0 / +1.5 WAA
// from where he is now: from the ML model, else the share of DEV players
// with his age, Pot, growth and a similar current whose gain covered the
// distance, so a player already at the bar reads 100%; user, 2026-09-24;
// MLB % = the chance he is ever anything in the majors), and Exp peak (his
// expected peak WAA), for players aged 16-26. Make it % (Dev_Odds, the odds
// of becoming an MLB regular) stays on the rows but is not a column.
const DEV_SIGNAL_GROUP = {
  label: 'Dev signals',
  columns: DEV_FIELDS,
};

// Year by year (usePlayersWithFV): display WAA at age+1, +2, +3, +5 on the
// projected path (the ML path where the row has one, else the measured DEV
// path) and the age of the projected peak. Proj Potential stays
// in the Value and Future Value groups.
const YEAR_BY_YEAR_COLS = ['_yr1WAA', '_yr2WAA', '_yr3WAA', '_yr5WAA', '_peakAge'];
const YEAR_BY_YEAR_GROUP = {
  label: 'Year by year',
  columns: YEAR_BY_YEAR_COLS,
};
const YEARS_OUT = { _yr1WAA: 1, _yr2WAA: 2, _yr3WAA: 3, _yr5WAA: 5 };

// WAA columns for hitters (used by roster optimizer)
export const HITTER_WAA_COLUMNS = [
  'C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd',
  'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd',
  'DH WAA wtd', 'Max WAA wtd',
  'C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR',
  'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR',
  'DH WAA vR', 'Max WAA vR',
  'C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL',
  'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL',
  'DH WAA vL', 'Max WAA vL',
  'C WAA P', '1B WAA P', '2B WAA P', '3B WAA P',
  'SS WAA P', 'LF WAA P', 'CF WAA P', 'RF WAA P',
  'DH WAA P', 'MAX WAA P',
];

// WAA columns for pitchers
export const PITCHER_WAA_COLUMNS = [
  'WAA vR', 'WAA vL', 'WAA wtd', 'WAR wtd',
  'WAA vR RP', 'WAA vL RP', 'WAA wtd RP',
  'WAP', 'WAP RP',
];

export const HITTER_COLUMN_GROUPS = {
  info: {
    label: 'Player Info',
    columns: ['Name', 'Best Pos', 'ORG', 'Lev', 'Age', 'B', 'T'],
  },
  value: {
    label: 'Value',
    // 'Pot WAA' (_potentialWAA) is the REALISTIC age-adjusted peak, not the raw 'MAX WAA P'
    // ceiling — so a past-prime hitter doesn't show phantom growth. Raw ceiling lives in the
    // 'Position WAA (Potential)' group for anyone who wants it.
    // 'Fair AAV' sits here, right after the WAA splits, so one dollar figure is
    // visible by DEFAULT near the left edge. Full money detail stays in the
    // '$ Current' / '$ Future' groups.
    // Peak Pot (_rawPotentialWAA) and To Peak (_toPeakWAA) moved out of this
    // default view into the 'Potential' group: the user asked for fewer
    // default columns (2026-09-24).
    columns: ['Max WAA wtd', 'Max WAA vR', 'Max WAA vL', '_offerMid', 'Price', '_ctrStatus', '_ctrLeft', '_owed', '_potentialWAA', 'Ovr', 'Pot'],
  },
  // Max WAA, split the way the rest of baseball reads it. Off = bat + legs,
  // Def = glove + the positional charge, both at the player's BEST position and both
  // in RUNS (not wins), so Off + Def over runs-per-win reproduces Best WAA exactly.
  // There is no 'Def Runs P': OOTP publishes potential for the bat only — no potential
  // range, error, arm or framing exists in the pull — so the glove is never projected.
  runsSplit: {
    label: 'Off / Def Runs',
    columns: ['Off Runs', 'Def Runs', 'Off Runs P'],
  },
  ratingsVR: {
    label: 'Ratings vs R',
    columns: ['BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR'],
  },
  ratingsVL: {
    label: 'Ratings vs L',
    columns: ['BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL'],
  },
  potential: {
    label: 'Potential',
    // Peak Pot (the raw ceiling) and To Peak live here, not in the default
    // Value view (user, 2026-09-24).
    columns: ['HT P', 'GAP P', 'POW P', 'EYE P', 'K P', '_rawPotentialWAA', '_toPeakWAA'],
  },
  devSignals: DEV_SIGNAL_GROUP,
  offense: {
    label: 'Offense',
    columns: ['wOBA vR', 'wOBA vL', 'wOBA wtd', 'OBP vR', 'OBP vL', 'OBP wtd', 'BatR wtd'],
  },
  baserunning: {
    label: 'Baserunning',
    columns: ['SPE', 'STE', 'RUN', 'SB%', 'BSR wtd', 'wSB wtd', 'UBR wtd'],
  },
  defense: {
    label: 'Position Eligibility',
    columns: ['C Eligible', '1B Eligible', '2B Eligible', '3B Eligible', 'SS Eligible', 'LF Eligible', 'CF Eligible', 'RF Eligible'],
  },
  fieldingSkills: {
    label: 'Fielding Skills',
    columns: ['C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM'],
  },
  posWAA: {
    label: 'Position WAA',
    columns: ['C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd', 'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd', 'DH WAA wtd'],
  },
  posWAA_vR: {
    label: 'WAA vs RHP',
    columns: ['C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR', 'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR', 'DH WAA vR'],
  },
  posWAA_vL: {
    label: 'WAA vs LHP',
    columns: ['C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL', 'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL', 'DH WAA vL'],
  },
  posWAA_P: {
    label: 'WAA Potential',
    columns: ['C WAA P', '1B WAA P', '2B WAA P', '3B WAA P', 'SS WAA P', 'LF WAA P', 'CF WAA P', 'RF WAA P', 'DH WAA P'],
  },
  defRuns: {
    label: 'Defensive Runs',
    columns: ['C RunsP', '1B RunsP', '2B RunsP', '3B RunsP', 'SS RunsP', 'LF RunsP', 'CF RunsP', 'RF RunsP'],
  },
  contract: {
    label: 'Contract',
    columns: ['Price', '_ctrStatus', '_ctrLeft', '_owed', 'ContractYr', 'ContractYrs', 'SalarySchedule', 'NoTrade', 'MLBSvcYrs', 'MLBSvcDays', 'MLBSvcDaysTY'],
  },
  health: {
    label: 'Health',
    columns: ['Prone', 'OnDL', 'DLDays'],
  },
  futureValue: {
    label: 'Future Value',
    columns: ['_fvScale', '_futureValue', '_currentWAA', '_potentialWAA', '_peakWAA', '_toPeakWAA', '_yearsTilPeak'],
  },
  yearByYear: YEAR_BY_YEAR_GROUP,
  personality: {
    label: 'Personality',
    columns: ['Int', 'WrkEthic', 'Greed', 'Loy', 'Lead'],
  },
  draftValue: {
    label: 'Draft FV',
    columns: ['_draftRawFV', '_agePercentile', '_draftCeilingWAA', '_durability', '_highINT'],
  },
  g5Value: {
    label: 'G5 Peak FV',
    columns: ['_g5FV', '_g5Raw', '_g5DevPct', '_g5GapFactor', '_g5RiskFactor'],
  },
  hybridValue: {
    label: 'Hybrid FV',
    columns: ['_hybridFV', '_hybridRaw', '_hybridWFV', '_hybridWG5', '_hybridWDraft'],
  },
  signing: {
    label: 'Signing',
    // From the in-game international export only — StatsPlus carries neither.
    columns: ['_iafaDem', '_iafaSign'],
  },
  marketCurrent: {
    label: '$ Current',
    columns: ['Price', '_perWAA', '_annualValue', '_surplus', '_mktPrice', '_mktSurplus', '_mktTier', '_offerFloor', '_offerMid', '_offerCeiling', '_ctrYears', '_ctrSurplus'],
  },
  marketFuture: {
    label: '$ Future',
    columns: ['_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh', '_marketValue'],
  },
};

export const PITCHER_COLUMN_GROUPS = {
  info: {
    label: 'Player Info',
    columns: ['Name', 'POS', 'ORG', 'Lev', 'Age', 'T'],
  },
  value: {
    label: 'Value (SP)',
    // see the hitter note: one headline dollar figure by default, after the splits.
    // _potentialWAA (not raw WAP): the SP-basis WAP is BLANK for ~2/3 of pure
    // RP/CL arms (the starter-stamina gate refuses them an SP projection), which
    // made relief prospects unevaluable at a glance. _potentialWAA is the
    // best-peak-ROLE projection (max of SP/RP potential, role-offset aware) —
    // the same Proj Peak the hitter table shows, never blank for a real arm.
    // Peak Pot (_rawPotentialWAA) and To Peak (_toPeakWAA) moved out of this
    // default view into the 'Potential' group: the user asked for fewer
    // default columns (2026-09-24).
    columns: ['WAA wtd', 'WAA vR', 'WAA vL', '_offerMid', 'Price', '_ctrStatus', '_ctrLeft', '_owed', '_potentialWAA', 'Ovr', 'Pot'],
  },
  valueRP: {
    label: 'Value (RP)',
    columns: ['WAA wtd RP', 'WAA vR RP', 'WAA vL RP', 'WAP RP'],
  },
  ratingsVR: {
    label: 'Ratings vs R',
    columns: ['STU vR', 'HRR vR', 'PBABIP vR', 'CON vR'],
  },
  ratingsVL: {
    label: 'Ratings vs L',
    columns: ['STU vL', 'HRR vL', 'PBABIP vL', 'CON vL'],
  },
  ratingsPot: {
    label: 'Potential',
    // Peak Pot (the raw ceiling) and To Peak live here, not in the default
    // Value view (user, 2026-09-24).
    columns: ['STU P', 'HRR P', 'PBABIP P', 'CON P', '_rawPotentialWAA', '_toPeakWAA'],
  },
  devSignals: DEV_SIGNAL_GROUP,
  performance: {
    label: 'SP Performance',
    columns: ['wOBA vR', 'wOBA vL', 'wOBA wtd', 'RA/9 vR', 'RA/9 vL', 'RA/9 wtd'],
  },
  performanceRP: {
    label: 'RP Performance',
    columns: ['wOBA vR RP', 'wOBA vL RP', 'wOBA wtd RP', 'RA/9 vR RP', 'RA/9 vL RP', 'RA/9 wtd RP'],
  },
  arsenal: {
    label: 'Pitch Arsenal',
    columns: ['Pitches', 'SP Pitch', 'SP P Pitch', 'STM', 'HLD'],
  },
  potential_value: {
    label: 'WAA Potential',
    columns: ['WAP', 'WAP RP'],
  },
  contract: {
    label: 'Contract',
    columns: ['Price', '_ctrStatus', '_ctrLeft', '_owed', 'ContractYr', 'ContractYrs', 'SalarySchedule', 'NoTrade', 'MLBSvcYrs', 'MLBSvcDays', 'MLBSvcDaysTY'],
  },
  health: {
    label: 'Health',
    columns: ['Prone', 'OnDL', 'DLDays'],
  },
  personality: {
    label: 'Personality',
    columns: ['Int', 'WrkEthic', 'Greed', 'Loy', 'Lead'],
  },
  futureValue: {
    label: 'Future Value',
    columns: ['_fvScale', '_futureValue', '_currentWAA', '_potentialWAA', '_peakWAA', '_toPeakWAA', '_yearsTilPeak'],
  },
  yearByYear: YEAR_BY_YEAR_GROUP,
  draftValue: {
    label: 'Draft FV',
    columns: ['_draftRawFV', '_agePercentile', '_draftCeilingWAA', '_durability', '_highINT'],
  },
  g5Value: {
    label: 'G5 Peak FV',
    columns: ['_g5FV', '_g5Raw', '_g5DevPct', '_g5GapFactor', '_g5RiskFactor'],
  },
  hybridValue: {
    label: 'Hybrid FV',
    columns: ['_hybridFV', '_hybridRaw', '_hybridWFV', '_hybridWG5', '_hybridWDraft'],
  },
  signing: {
    label: 'Signing',
    // From the in-game international export only — StatsPlus carries neither.
    columns: ['_iafaDem', '_iafaSign'],
  },
  marketCurrent: {
    label: '$ Current',
    columns: ['Price', '_perWAA', '_marketRole', '_annualValue', '_surplus', '_mktPrice', '_mktSurplus', '_mktTier', '_offerFloor', '_offerMid', '_offerCeiling', '_ctrYears', '_ctrSurplus'],
  },
  marketFuture: {
    label: '$ Future',
    columns: ['_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh', '_marketValue'],
  },
};

// Column formatting helpers
export function formatCellValue(value, columnName) {
  // Dev signals: blank (not '-') for a null value and for rows without an
  // entry, so the columns stay quiet for the thousands of players outside
  // the 16-26 window.
  if (columnName === 'Dev_Grow') return fmtGrow(value);
  if (columnName === 'Dev_Odds') return fmtOdds(value);
  if (columnName === 'Dev_PeakMlb' || columnName === 'Dev_PeakUseful' || columnName === 'Dev_PeakGood') return fmtOdds(value);
  if (columnName === 'Dev_VsTypical') return fmtVsTypical(value);
  if (columnName === 'Dev_PotDir') return value === 'up' || value === 'flat' || value === 'down' ? value : '';
  if (columnName === 'Dev_Flag') return value === 'keep' ? 'KEEP' : value === 'move' ? 'MOVE' : '';
  if (columnName === 'Dev_PeakP50' || columnName === 'Dev_PeakVsListed') return fmtWaa(value);
  if (columnName === 'Dev_PeakRange') return typeof value === 'string' ? value : '';

  if (value === null || value === undefined || value === '') return '-';

  // ORG shows the three-letter code (HOU, not Houston Astros); "0" stays
  // "0" so it still sorts as a group. The user asked for this (2026-09-24).
  if (columnName === 'ORG') return orgAbbr(value);

  // Boolean flags (contract / roster status) — render Yes / - (React won't print raw booleans)
  const boolCols = ['NoTrade', 'OnDL', 'OnDL60', 'DFA', 'OnWaivers', 'IsMajorDeal'];
  if (boolCols.includes(columnName)) return value === true ? 'Yes' : '-';

  // Per-year salary schedule (array) — "$26.0M / $26.0M / ..."
  if (columnName === 'SalarySchedule') {
    return Array.isArray(value) && value.length ? value.map(formatMoney).join(' / ') : '-';
  }

  const num = parseFloat(value);

  // Year by year: signed, one decimal ("+0.3", "-1.2").
  if (YEARS_OUT[columnName] && !isNaN(num)) {
    const v = Math.abs(num) < 0.05 ? 0 : num;
    return (v > 0 ? '+' : '') + v.toFixed(1);
  }

  const intCols = ['Age', 'Rank', 'Rank vR', 'Rank vL', 'Rank P', 'Rank RP', 'Ovr', 'Pot',
    '_fvScale', '_draftFV', '_g5FV', '_hybridFV', '_yearsTilPeak', '_peakAge', '_declineStart',
    '_hybridWFV', '_hybridWG5', '_hybridWDraft',
    'ContractYr', 'ContractYrs', 'MLBSvcYrs', 'MLBSvcDays', 'MLBSvcDaysTY', 'DLDays', '_ctrYears',
    'SPE', 'STE', 'RUN', 'STM', 'HLD',
    'BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL',
    'BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR',
    'HT P', 'GAP P', 'POW P', 'EYE P', 'K P',
    'STU P', 'HRR P', 'PBABIP P', 'CON P',
    'STU vR', 'HRR vR', 'PBABIP vR', 'CON vR',
    'STU vL', 'HRR vL', 'PBABIP vL', 'CON vL',
    'C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM',
  ];

  if (intCols.includes(columnName) && !isNaN(num)) {
    return Math.round(num);
  }

  // Value Gap = our FV minus OOTP's POT. Signed so undervalued (+) pops.
  if (columnName === '_fvGap' && !isNaN(num)) {
    return (num > 0 ? '+' : '') + Math.round(num);
  }

  // WAA/WAR/Runs columns - 1 decimal
  const isWaaCols = columnName.includes('WAA') || columnName.includes('WAR') || columnName.includes('WAP') ||
    columnName.includes('BatR') || columnName.includes('BSR') || columnName.includes('UBR') ||
    columnName.includes('wSB') || columnName.includes('Runs') || columnName.includes('PMAA') ||
    columnName.includes('EAA') || columnName.includes('DPAA') || columnName.includes('ARMAA') ||
    columnName.includes('FRMAA') || columnName.includes('ArmR') ||
    columnName === '_futureValue' || columnName === '_peakWAA' ||
    columnName === '_currentWAA' || columnName === '_potentialWAA' || columnName === '_rawPotentialWAA' ||
    columnName === '_draftRawFV' || columnName === '_draftCeiling' ||
    columnName === '_draftCeilingWAA' || columnName === '_ceilingScore' ||
    columnName === '_g5Raw' || columnName === '_hybridRaw';

  if (isWaaCols && !isNaN(num)) {
    return num.toFixed(1);
  }

  // wOBA / OBP - 3 decimals
  if ((columnName.includes('wOBA') || columnName.includes('OBP')) && !isNaN(num)) {
    return num.toFixed(3);
  }

  // RA/9 - 2 decimals
  if (columnName.includes('RA/9') && !isNaN(num)) {
    return num.toFixed(2);
  }

  if (columnName === 'SB%' && !isNaN(num)) {
    return (num * 100).toFixed(0) + '%';
  }

  if (columnName === '_agePercentile' && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if (columnName === '_g5DevPct' && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if ((columnName === '_g5GapFactor' || columnName === '_g5RiskFactor') && !isNaN(num)) {
    return num.toFixed(3);
  }

  if ((columnName === '_hybridWFV' || columnName === '_hybridWG5' || columnName === '_hybridWDraft') && !isNaN(num)) {
    return `${Math.round(num)}%`;
  }

  if (columnName === '_highINT') {
    return value === true ? 'Y' : '-';
  }

  if (columnName === '_wrecked') {
    return value === true ? 'WRECKED' : '-';
  }

  // High work ethic: +1.5% Draft FV (draftFV.js PERSONALITY_STEP).
  if (columnName === '_weBoost') {
    return value === true ? '+1.5%' : '-';
  }

  // Money columns — format as $12.5M / $750K
  const moneyCols = ['Price', '_owed', '_perWAA', '_marketValue', '_offerFloor', '_offerMid', '_offerCeiling', '_annualValue', '_surplus',
    '_mktPrice', '_mktSurplus',
    '_ctrSurplus', '_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh'];
  if (moneyCols.includes(columnName) && !isNaN(num)) {
    return formatMoney(num);
  }

  // Role column
  if (columnName === '_marketRole') {
    return value || '-';
  }

  // Market tier — 'scarcity' (local price departs the line) vs 'replaceable'
  if (columnName === '_mktTier') {
    return value === 'scarcity' ? 'Scarcity' : value === 'replaceable' ? 'Line' : '-';
  }

  return value;
}

// ─── Night Scorecard colour classes (src/index.css, @layer components) ──────
// Restyle only (Phase 4, docs/phase4/restyle_pattern.md): every threshold
// below is his, unchanged; only the class each band paints was re-pointed.
// Quality ladders (ordered bands grading a rating or a value) translate his
// Tailwind palette by colour name onto the 20-80 grade ramp, top to bottom:
//   purple / sky -> ns-g80 · cyan / emerald -> ns-g70 · green / lime -> ns-g55
//   · neutral middle band (gray / slate-300 / yellow) -> ns-text-2
//   · amber -> ns-g40 · orange -> ns-g30 · red -> ns-g20
// (the ns-gNN classes carry the ramp's own weight, so his font-bold /
// font-semibold tier markers are dropped there). Meaning (flags, good/bad
// splits, money) uses ns-good / ns-bad / ns-warn and keeps his weight;
// greys map slate-400 -> ns-text-2, slate-500 -> ns-muted, slate-600 -> ns-dim.

const PRONE_CLASS = {
  'Wrecked': 'ns-prone-wrecked',
  'Fragile': 'ns-prone-fragile',
  'Normal': 'ns-prone-normal',
  'Durable': 'ns-prone-durable',
  'Iron Man': 'ns-prone-iron-man',
};

const POS_CLASS_KEYS = new Set(['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH', 'SP', 'RP', 'CL']);

/** Position text class ('ns-pos ns-pos-1b'), or '' for anything that is not a position. */
export function posClass(value) {
  const key = typeof value === 'string' ? value.replace(/[^A-Za-z0-9]/g, '').toUpperCase() : '';
  return POS_CLASS_KEYS.has(key) ? `ns-pos ns-pos-${key.toLowerCase()}` : '';
}

// OOTP level -> the data-lvl key of a level chip (.ns-chip[data-lvl]).
// Rookie tiers (R+, R-) read as R, A- as A; FA / AMA and unknowns get no chip.
const LEVEL_KEYS = {
  MLB: 'mlb', AAA: 'aaa', AA: 'aa', 'A+': 'aplus', A: 'a', 'A-': 'a',
  R: 'r', 'R+': 'r', 'R-': 'r', INT: 'int',
};

/** data-lvl key for a level chip, or null when the level has no chip. */
export function levelKey(lev) {
  return LEVEL_KEYS[lev] || null;
}

/**
 * Night Scorecard colour class for one cell. `row` is optional: the Dev_Grow
 * threshold depends on the row's role (Dev_Role), hitter bar when unknown.
 */
export function getCellColorClass(value, columnName, row) {
  // Dev signals
  if (columnName === 'Dev_PotDir') {
    return value === 'up' ? 'ns-good' : value === 'down' ? 'ns-bad' : value === 'flat' ? 'ns-text-2' : '';
  }
  if (columnName === 'Dev_Flag') {
    return value === 'keep' ? 'ns-good font-bold' : value === 'move' ? 'ns-bad font-bold' : '';
  }
  if (columnName === 'Dev_Grow') {
    const g = parseFloat(value);
    if (isNaN(g)) return '';
    const bar = GROW_KEEP[row && row.Dev_Role === 'P' ? 'P' : 'H'];
    if (g >= bar) return 'ns-good font-semibold';
    if (g <= 1) return 'ns-bad';
    return 'ns-text-2';
  }
  if (columnName === 'Dev_Odds') {
    const o = parseFloat(value);
    if (isNaN(o)) return '';
    if (o >= 0.5) return 'ns-good font-semibold';
    if (o >= 0.25) return 'ns-text-2';
    if (o >= 0.1) return 'ns-warn';
    return 'ns-bad';
  }
  // MLB % (user, 2026-09-24, "if they will ever be anything in the mlb"):
  // green at 0.6 or more, red at 0.25 or less, neutral between.
  if (columnName === 'Dev_PeakMlb') {
    const s = parseFloat(value);
    if (isNaN(s)) return '';
    if (s >= 0.6) return 'ns-good font-semibold';
    if (s <= 0.25) return 'ns-bad';
    return 'ns-text-2';
  }
  // Starter % / Star % (user, 2026-09-24): green when the chance is high,
  // red when it is low. Starter bars 0.5 / 0.2, Star bars 0.3 / 0.1.
  if (columnName === 'Dev_PeakUseful' || columnName === 'Dev_PeakGood') {
    const s = parseFloat(value);
    if (isNaN(s)) return '';
    const [hi, lo] = columnName === 'Dev_PeakUseful' ? [0.5, 0.2] : [0.3, 0.1];
    if (s >= hi) return 'ns-good font-semibold';
    if (s <= lo) return 'ns-bad';
    return 'ns-text-2';
  }
  if (columnName === 'Dev_VsTypical') {
    const d = parseFloat(value);
    if (isNaN(d)) return '';
    if (d >= 40) return 'ns-g70';
    if (d >= 15) return 'ns-g55';
    if (d > -15) return 'ns-text-2';
    if (d > -40) return 'ns-g30';
    return 'ns-g20';
  }
  // Exp peak: same ladder as a WAA value.
  if (columnName === 'Dev_PeakP50') {
    const w = parseFloat(value);
    if (isNaN(w)) return '';
    if (w >= 5) return 'ns-g80';
    if (w >= 3) return 'ns-g70';
    if (w >= 1.5) return 'ns-g55';
    if (w >= 0) return 'ns-text-2';
    if (w >= -1) return 'ns-g30';
    return 'ns-g20';
  }
  // vs listed: green when DEV peers beat his listed peak by half a win,
  // red when they fell half a win short.
  if (columnName === 'Dev_PeakVsListed') {
    const d = parseFloat(value);
    if (isNaN(d)) return '';
    if (d >= 0.5) return 'ns-good font-semibold';
    if (d <= -0.5) return 'ns-bad';
    return 'ns-text-2';
  }
  if (columnName === 'Dev_PeakRange') {
    return typeof value === 'string' && value ? 'ns-text-2' : '';
  }

  // String-based color coding (non-numeric)
  // Durability and injury proneness (raw OOTP rating): the theme's proneness encoding
  if (columnName === '_durability' || columnName === 'Prone') {
    return PRONE_CLASS[value] || '';
  }
  if (columnName === '_highINT') {
    return value === true ? 'ns-good font-semibold' : 'ns-dim';
  }
  if (columnName === '_wrecked') {
    return value === true ? 'ns-bad font-bold' : '';
  }
  // Current injury / roster flags — red when flagged
  if (['OnDL', 'OnDL60', 'DFA', 'OnWaivers'].includes(columnName)) {
    return value === true ? 'ns-bad font-semibold' : 'ns-dim';
  }
  if (columnName === 'NoTrade') {
    return value === true ? 'ns-warn' : 'ns-dim';
  }
  // Market tier badge — scarcity tier = local price departs the fitted line
  if (columnName === '_mktTier') {
    return value === 'scarcity' ? 'ns-warn font-semibold' : 'ns-text-2';
  }
  // Position columns: the position hue (Night Scorecard td[data-pos])
  if (columnName === 'POS' || columnName === 'Best Pos' || columnName === 'Best Pos WAR') {
    return posClass(value);
  }

  const num = parseFloat(value);
  if (isNaN(num)) return '';

  // Value Gap: + = our projection (FV) rates him above his OOTP POT → undervalued, a buy
  // target; − = the market's POT is higher than our projection → overvalued.
  if (columnName === '_fvGap') {
    if (num >= 8) return 'ns-g80';
    if (num >= 4) return 'ns-g70';
    if (num >= 1) return 'ns-g55';
    if (num > -1) return 'ns-text-2';
    if (num >= -4) return 'ns-g30';
    return 'ns-g20';
  }

  const ratingLikeCols = [
    'BA vL', 'GAP vL', 'POW vL', 'EYE vL', 'K vL',
    'BA vR', 'GAP vR', 'POW vR', 'EYE vR', 'K vR',
    'HT P', 'GAP P', 'POW P', 'EYE P', 'K P',
    'STU P', 'HRR P', 'PBABIP P', 'CON P',
    'STU vR', 'HRR vR', 'PBABIP vR', 'CON vR',
    'STU vL', 'HRR vL', 'PBABIP vL', 'CON vL',
    '_fvScale', '_draftFV', '_g5FV', '_hybridFV', 'Ovr', 'Pot',
    'C ABI', 'C FRM', 'C ARM', 'IF RNG', 'IF ERR', 'IF ARM', 'TDP', 'OF RNG', 'OF ERR', 'OF ARM',
    'SPE', 'STE', 'STM', 'HLD',
  ];

  if (ratingLikeCols.includes(columnName)) {
    if (num >= 75) return 'ns-g80';
    if (num >= 65) return 'ns-g70';
    if (num >= 55) return 'ns-g55';
    if (num >= 45) return 'ns-text-2';
    if (num >= 35) return 'ns-g30';
    return 'ns-g20';
  }

  const isValueCol = columnName.includes('WAA') || columnName.includes('WAR') ||
    columnName.includes('WAP') || columnName === '_futureValue' || columnName === '_peakWAA' ||
    columnName === '_currentWAA' || columnName === '_potentialWAA' || columnName === '_rawPotentialWAA' ||
    columnName === '_draftCeiling' || columnName === '_draftCeilingWAA' || columnName === '_g5Raw';

  if (isValueCol) {
    if (num >= 5) return 'ns-g80';
    if (num >= 3) return 'ns-g70';
    if (num >= 1.5) return 'ns-g55';
    if (num >= 0) return 'ns-text-2';
    if (num >= -1) return 'ns-g30';
    return 'ns-g20';
  }

  if (columnName.includes('RA/9')) {
    if (num <= 3.0) return 'ns-g80';
    if (num <= 3.5) return 'ns-g70';
    if (num <= 4.0) return 'ns-g55';
    if (num <= 4.5) return 'ns-text-2';
    if (num <= 5.5) return 'ns-g30';
    return 'ns-g20';
  }

  if (columnName.includes('wOBA')) {
    if (num >= 0.400) return 'ns-g80';
    if (num >= 0.360) return 'ns-g70';
    if (num >= 0.320) return 'ns-g55';
    if (num >= 0.300) return 'ns-text-2';
    if (num >= 0.280) return 'ns-g30';
    return 'ns-g20';
  }

  // Surplus: green = underpaid/good deal, red = overpaid
  if (columnName === '_surplus' || columnName === '_ctrSurplus' || columnName === '_mktSurplus') {
    if (num > 10_000_000) return 'ns-good font-bold';
    if (num > 0) return 'ns-good';
    if (num > -5_000_000) return 'ns-warn';
    return 'ns-bad';
  }

  // Money columns — just use green for positive values
  const moneyColorCols = ['_marketValue', '_offerFloor', '_offerMid', '_offerCeiling', '_annualValue', '_mktPrice', '_perWAA',
    '_futureAAV', '_futureOfferLow', '_futureOfferMid', '_futureOfferHigh'];
  if (moneyColorCols.includes(columnName)) {
    if (num > 0) return 'ns-good';
    return 'ns-muted';
  }

  // Role column
  if (columnName === '_marketRole') {
    return value === 'SP' ? 'ns-pos ns-pos-sp' : value === 'RP' ? 'ns-pos ns-pos-rp' : '';
  }

  if (columnName === '_agePercentile' || columnName === '_draftRawFV' || columnName === '_ceilingScore' ||
    columnName === '_g5DevPct' || columnName === '_hybridRaw') {
    if (num >= 90) return 'ns-g80';
    if (num >= 75) return 'ns-g70';
    if (num >= 50) return 'ns-g55';
    if (num >= 25) return 'ns-text-2';
    if (num >= 10) return 'ns-g30';
    return 'ns-g20';
  }

  return '';
}

/**
 * Hover text for one cell, or '' when the column has none.
 * Dev_Odds carries the DEV grid cell and its sample size; Dev_PeakP50 the
 * 25th to 75th pct band and its n; Dev_PeakVsListed the listed peak;
 * Dev_PeakMlb / Dev_PeakUseful / Dev_PeakGood the chance from his current
 * (devSignals.js devShareTitle: the bar, his current, the peak cell, its n
 * and the slice of lookalikes it was read off, or "Already ..." when his
 * current sits at the bar).
 */
export function getCellTitle(row, columnName) {
  // ORG: the full team name on hover when the cell shows the code.
  if (columnName === 'ORG') {
    const raw = row?.ORG;
    return typeof raw === 'string' && orgAbbr(raw) !== raw ? raw : '';
  }
  if (columnName === '_potentialWAA') {
    // Proj Potential = current + the typical GAIN (usePlayersWithFV
    // _potentialSource: 'ML' | 'DEV cell' | 'measured curve' | 'model'). The
    // old hover described the rejected cell-median LEVEL rule (user, 2026-09-24).
    const src = row?._potentialSource;
    if (src === 'ML') {
      // ML (2026-09-25): ages 26 and under = his current (the line with the
      // best WAR, the same line his money uses) + the ML median gain. Exp
      // peak starts from the better of his SP and RP WAA lines instead, so a
      // young arm whose relief line is better today can show a higher Exp
      // peak than Proj Potential. Putting Proj Potential on that line mixed
      // the relief line with the starter's WAR offset and inflated his money
      // (checker, 2026-09-25), so it stays on the money line.
      // 27 and over = the top of the ML path (five ML years, then the DEV
      // curve). The cell method's number is shown for reference.
      const words = devMlWords(row);
      if (devIsMl(row)) {
        const gain = fmtWaa(row.Dev_PeakGainP50) || '?';
        const lo = fmtWaa(row.Dev_PeakGainP25), hi = fmtWaa(row.Dev_PeakGainP75);
        const band = lo && hi ? `, p25 to p75 ${lo} to ${hi}` : '';
        const cg = fmtWaa(row.Dev_CellGainP50);
        const cell = cg ? `; cell method: his current ${cg}` : '; cell method: none';
        const nowWords = row.Dev_Role === 'P'
          ? 'his current WAA on the line his value uses (Exp peak starts from the better of his SP and RP lines, so it can read higher)'
          : 'his WAA today (the same number as Exp peak)';
        return `Where we project him to top out: ${nowWords} + the median gain from ${words} (${gain}${band}). It counts the players who wash out${cell}${devMlRangeNote(row)}`;
      }
      return `The top of his projected path: the next five years from ${words}, then the measured DEV curve`;
    }
    if (src === 'DEV cell') {
      const gain = fmtWaa(row.Dev_PeakGainP50) || '?';
      const lo = fmtWaa(row.Dev_PeakGainP25), hi = fmtWaa(row.Dev_PeakGainP75);
      const band = lo && hi ? `, p25 to p75 ${lo} to ${hi}` : '';
      // Since 2026-09-24 the gain is read off the lookalikes at a similar
      // current when that slice has n >= 15 (Dev_ShareBasis "now tercile"),
      // and a thin growth cell falls back to the pot-only cell (/any).
      const potOnly = /\/any$/.test(row.Dev_PeakCell || '');
      const similar = /now tercile/.test(row.Dev_ShareBasis || '');
      const who = potOnly
        ? (similar ? 'his age, Pot and a similar current (growth group thin)' : 'his age and Pot (growth group thin)')
        : (similar ? 'his age, Pot, growth and a similar current' : 'his age, Pot and growth');
      return `Where we project him to top out: his current WAA + the gain DEV players with ${who} typically made from here (${gain}${band}, group n ${row.Dev_PeakN ?? '?'})`;
    }
    if (src === 'measured curve') {
      return 'Where we project him to top out: his current WAA + the share of his listed gap the measured curve says players his age still close';
    }
    return 'Model ceiling after the development haircut (no measured curve)';
  }
  if (YEARS_OUT[columnName] && Array.isArray(row?.Dev_MlD) && row?._potentialSource === 'ML') {
    // ML path (2026-09-25): years 1..5 are current + the ML median change.
    const a = Math.floor(parseFloat(row.Age));
    const k = YEARS_OUT[columnName];
    const d = row.Dev_MlD[k - 1];
    const at = Number.isFinite(a) ? ` at age ${a + k}` : '';
    const out = `the ML median change ${k} year${k > 1 ? 's' : ''} out (${fmtWaa(d)}) from ${devMlWords(row)}`;
    // Ages 26 and under (devIsMl): the display path is smoothed
    // (futureValue.mlTrack noDip: no dip before 28, a steady climb to Proj
    // Potential) and capped at Proj Potential. The ML change assumes he keeps
    // playing (the path models learn only from players who stayed in the
    // league); Proj Potential counts the washouts.
    if (devIsMl(row)) {
      return `Projected WAA${at}: current + ${out}, smoothed so the path never dips before 28 and climbs steadily to Proj Potential. Capped at his Proj Potential (the change assumes he keeps playing; Proj Potential counts the players who wash out)`;
    }
    return `Projected WAA${at}: current + ${out}`;
  }
  if (YEARS_OUT[columnName]) {
    const a = Math.floor(parseFloat(row?.Age));
    return Number.isFinite(a)
      ? `Projected WAA at age ${a + YEARS_OUT[columnName]} on the measured DEV path`
      : 'Projected WAA on the measured DEV path';
  }
  if (columnName === '_peakAge') {
    // ML rows (2026-09-25): the path is the ML's five years, then the DEV
    // curve, smoothed and capped at Proj Potential for ages 26 and under.
    if (Array.isArray(row?.Dev_MlD) && row?._potentialSource === 'ML') {
      const cap = devIsMl(row) ? ', smoothed (no dip before 28) and capped at his Proj Potential' : '';
      return `Age of the top of his projected path: the next five years from ${devMlWords(row)}, then the measured DEV curve${cap}`;
    }
    return 'Age of the top of his projected path on the measured DEV path';
  }
  if (columnName === '_declineStart') return 'First age his projected path sits 0.1 WAA or more below its peak';
  if (!row) return '';
  if (columnName === 'Dev_Odds') {
    if (row.Dev_Odds === null || row.Dev_Odds === undefined) return '';
    if (devIsMl(row)) {
      // ML (2026-09-25): Make it % from the model, the cell's for reference.
      const c = row.Dev_CellOdds;
      const cell = c === null || c === undefined ? 'cell method: none'
        : `cell method: ${fmtOdds(c)}${row.Dev_OddsN != null ? ` (n ${row.Dev_OddsN}${row.Dev_OddsCell ? `, DEV cell ${row.Dev_OddsCell}` : ''})` : ''}`;
      return `Chance of an MLB season with 300+ PA or 150+ BF, from ${devMlWords(row)}; ${cell}${devMlRangeNote(row)}`;
    }
    const n = row.Dev_OddsN !== null && row.Dev_OddsN !== undefined ? `n ${row.Dev_OddsN}` : 'n unknown';
    return row.Dev_OddsCell ? `${n}, DEV cell ${row.Dev_OddsCell}` : n;
  }
  // MLB % / Starter % / Star % (user, 2026-09-24): the chance his peak
  // reaches the bar from where he is now, "Already ..." when his current
  // sits at it (a player at 0+ WAA must not read under 100% starter). MLB %
  // = the chance he is ever anything in the majors. Wording shared with the
  // Org tab through devSignals.js devShareTitle.
  if (columnName === 'Dev_PeakMlb') return devShareTitle(row, 'mlb');
  if (columnName === 'Dev_PeakUseful') return devShareTitle(row, 'useful');
  if (columnName === 'Dev_PeakGood') return devShareTitle(row, 'good');
  if (columnName === 'Dev_PeakP50') {
    if (row.Dev_PeakP50 === null || row.Dev_PeakP50 === undefined) return '';
    if (devIsMl(row)) {
      // ML (2026-09-25): his current + the ML median gain; cell for reference.
      const range = row.Dev_PeakRange ? `, 25th to 75th pct ${row.Dev_PeakRange}` : '';
      const cp = row.Dev_CellPeakP50;
      const cell = cp === null || cp === undefined ? 'cell method: none' : `cell method: ${fmtWaa(cp)}`;
      return `Expected peak WAA: his current + the median gain from ${devMlWords(row)}${range}; ${cell}${devMlRangeNote(row)}`;
    }
    const band = row.Dev_PeakRange ? `25th to 75th pct ${row.Dev_PeakRange}` : `median ${fmtWaa(row.Dev_PeakP50)}`;
    const n = row.Dev_PeakN !== null && row.Dev_PeakN !== undefined ? `n ${row.Dev_PeakN}` : 'n unknown';
    return `players like him in DEV: ${band}, ${n}`;
  }
  if (columnName === 'Dev_PeakRange') {
    if (!row.Dev_PeakRange) return '';
    if (devIsMl(row)) return `25th to 75th pct of his peak, from ${devMlWords(row)}`;
    const n = row.Dev_PeakN !== null && row.Dev_PeakN !== undefined ? `n ${row.Dev_PeakN}` : 'n unknown';
    return row.Dev_PeakCell ? `${n}, DEV cell ${row.Dev_PeakCell}` : n;
  }
  if (columnName === 'Dev_PeakVsListed') {
    if (row.Dev_ListedPeak === null || row.Dev_ListedPeak === undefined) return '';
    return `his listed peak potential is ${fmtWaa(row.Dev_ListedPeak)}`;
  }
  if (columnName === 'Dev_Grow') {
    return row.Dev_Role ? 'Display steps gained per game-year, summed over the core skills' : '';
  }
  if (columnName === 'Dev_VsTypical') {
    return row.Dev_Role ? 'Internal points above or below the median player in this league with his age and Pot (DEV typical when that group is under 20)' : '';
  }
  if (columnName === 'Dev_PotDir') {
    if (row.Dev_PotDelta === null || row.Dev_PotDelta === undefined) return '';
    const d = row.Dev_PotDelta;
    return `Pot ${d > 0 ? '+' : ''}${d} over the span`;
  }
  if (columnName === 'Dev_Flag') {
    return row.Dev_Note || '';
  }
  return '';
}

export const COLUMN_LABELS = {
  'Dev_Grow': 'Grow/yr',
  'Dev_PotDir': 'Pot dir',
  'Dev_Odds': 'Make it',
  'Dev_PeakMlb': 'MLB %',
  // Starter % / Star % (user, 2026-09-26: "i would define +1.5 WAA as a
  // super star"): the 0 and +1.5 bars were labelled Useful and Good.
  'Dev_PeakUseful': 'Starter %',
  'Dev_PeakGood': 'Star %',
  'Dev_PeakP50': 'Exp peak',
  'Dev_PeakRange': 'Peak range',
  'Dev_PeakVsListed': 'vs listed',
  'Dev_VsTypical': 'vs typical',
  'Dev_Flag': 'Flag',
  '_fvScale': 'FV',
  '_fvGap': 'Value Gap',
  'Ovr': 'OVR',
  'Pot': 'POT',
  '_futureValue': 'Future$',
  '_currentWAA': 'Curr WAA',
  // Short headers so the table fits (user, 2026-09-24).
  '_potentialWAA': 'Proj Pot',
  '_rawPotentialWAA': 'Peak Pot',
  'WAP': 'Peak SP',
  'WAP RP': 'Peak RP',
  '_peakWAA': 'Peak WAA',
  '_toPeakWAA': 'To Peak',
  '_yearsTilPeak': 'Yrs to Peak',
  '_yr1WAA': 'Next yr',
  '_yr2WAA': '+2 yr',
  '_yr3WAA': '+3 yr',
  '_yr5WAA': '+5 yr',
  '_peakAge': 'Peak age',
  '_declineStart': 'Decline from',
  '_maxWAA': 'Max WAA',
  'Best Pos': 'Pos',
  'Off Runs': 'Off Runs',
  'Def Runs': 'Def Runs',
  'Off Runs P': 'Off Runs P',
  'Max WAA wtd': 'Best WAA',
  'Max WAA vR': 'Best vR',
  'Max WAA vL': 'Best vL',
  'MAX WAA P': 'Best P',
  'WAA wtd': 'SP WAA',
  'WAA wtd RP': 'RP WAA',
  'WAR wtd': 'SP WAR',
  '_draftFV': 'Draft FV',
  '_draftRawFV': 'Draft FV',
  '_agePercentile': 'Age Pctl',
  // Since the ceiling basis fix these two ARE the same number (WAA); the offsets that
  // made one of them WAR are gone. Kept as a distinct key only because the draft
  // board's above/below-zero sort tier reads _draftCeiling.
  '_iafaDem': 'Demand',
  '_iafaSign': 'Signability',
  '_draftCeiling': 'Ceiling',
  '_draftCeilingWAA': 'Ceiling',
  '_ceilingScore': 'Ceil Score',
  '_durability': 'Durability',
  '_highINT': 'High INT',
  '_wrecked': 'Wrecked',
  '_weBoost': 'WE+',
  '_g5FV': 'G5 FV',
  '_g5Raw': 'G5 Peak',
  '_g5DevPct': 'Dev Pctl',
  '_g5GapFactor': 'Gap Factor',
  '_g5RiskFactor': 'Risk Factor',
  '_hybridFV': 'Hybrid FV',
  '_hybridRaw': 'Hybrid Raw',
  '_hybridWFV': 'w(FV)',
  '_hybridWG5': 'w(G5)',
  '_hybridWDraft': 'w(Draft)',
  'C Eligible': 'C',
  '1B Eligible': '1B',
  '2B Eligible': '2B',
  '3B Eligible': '3B',
  'SS Eligible': 'SS',
  'LF Eligible': 'LF',
  'CF Eligible': 'CF',
  'RF Eligible': 'RF',
  // Market value labels — two economies (marketValue.js v2):
  // "Line Value" = fitted line (replaceable tier); "Mkt Price" = tier-local
  // price from comparable-WAR signings (scarcity tier).
  '_perWAA': '$/WAR',
  '_marketValue': 'Career $',
  '_offerFloor': 'Offer Low',
  '_offerMid': 'Fair AAV',
  '_offerCeiling': 'Offer High',
  '_annualValue': 'Line Value',
  '_surplus': 'Line Surplus',
  '_mktPrice': 'Mkt Price',
  '_mktSurplus': 'Mkt Surplus',
  '_mktTier': 'Tier',
  '_ctrYears': 'Ctr Yrs',
  '_ctrSurplus': 'Ctr Surplus',
  '_futureAAV': 'Peak AAV',
  '_futureOfferLow': 'Fut Low',
  '_futureOfferMid': 'Fut Mid',
  '_futureOfferHigh': 'Fut High',
  '_marketRole': 'Role $',
  '_bestWAA': 'Best WAA',
  // Contract / service
  '_ctrLeft': 'Ctrl',
  '_owed': 'Owed',
  '_ctrStatus': 'Status',
  'Price': 'Salary',
  'ContractYr': 'Yr #',
  'ContractYrs': 'Yrs',
  'SalarySchedule': 'By year',
  'NoTrade': 'No-Trade',
  'MLBSvcYrs': 'MLB Svc',
  // Day-resolution service time (172 days = 1 service year, MEASURED — see
  // ingest/statsplus.py). Service AT SIGNING = MLBSvcDays - MLBSvcDaysTY, which
  // is what marketValue.js uses to keep extensions out of the FA market fit.
  'MLBSvcDays': 'Svc Days',
  'MLBSvcDaysTY': 'Svc Days (yr)',
  // Health
  'Prone': 'Injury Prone',
  'OnDL': 'On DL',
  'DLDays': 'DL Days',
  // Personality (OOTP makeup ratings)
  'Int': 'Intelligence',
  'WrkEthic': 'Work Ethic',
  'Greed': 'Greed',
  'Loy': 'Loyalty',
  'Lead': 'Leadership',
};
