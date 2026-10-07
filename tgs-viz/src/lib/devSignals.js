/**
 * devSignals.js: reads /data/<LG>/dev_signals.json and stamps its fields
 * onto player rows.
 *
 * The file is written by the DEV-league signals build. Each entry is one
 * player aged 16-26 at the league's latest pull: his growth over the last
 * game-year, the direction of his OOTP Pot grade, and the odds a DEV-league
 * player with the same age, Pot bucket and growth became an MLB regular
 * (Make it %, Dev_Odds: kept on the rows, no longer shown in the app).
 * DEV only supplies the grid; the growth and Pot direction are the league's own.
 *
 * Exp peak (peak_p25 / peak_p50 / peak_p75 / peak_n / peak_cell): the
 * eventual peak WAA that DEV players in the same cell actually reached.
 * listed_peak is the app's own peak potential for the player (MAX WAA P for
 * a hitter, the better of WAP and WAP RP for a pitcher), which prices the
 * potential ratings OOTP shows today. peak_vs_listed = peak_p50 - listed_peak.
 * A thin growth cell (n < 15) falls back to the pot-only cell (same age and
 * Pot, growth unknown; peak_cell ends in /any), so the peak fields are null
 * only when that cell is thin too, or the build predates them.
 *
 * Cell gain (peak_gain_p25 / peak_gain_p50 / peak_gain_p75): the lookalikes'
 * (eventual peak WAA minus now-WAA) per DEV player, never below 0. Since
 * 2026-09-24 the lookalikes are the slice of the cell at a similar current
 * (the now-WAA tercile holding his own current, share_basis "now tercile")
 * when that slice has n >= 15, else the whole cell. The path model grows a
 * player to current + peak_gain_p50 (futureValue.js). Null on the same
 * thin-cell rule as the peak fields.
 *
 * MLB / Starter / Star (peak_mlb / peak_useful / peak_good; the app's MLB %,
 * Starter % and Star %): the chance his eventual peak reaches -1 WAA (an
 * MLB-level player: a 5th starter or bench bat), 0 (an average starter) and
 * +1.5 (a star) FROM WHERE HE IS NOW: the share of his lookalikes' gains
 * that covered the distance from his current (share_now) to the bar, so a
 * player already at or above the bar reads 100%. "At the bar" allows
 * BAR_TOLERANCE (0.05 WAA, the table's one-decimal rounding): a row shown as
 * 0.0 can sit at -0.02 and must not read under 100% starter. When his
 * current sits outside every lookalike's
 * (above the top slice's range or below the bottom slice's, share_basis
 * "now tercile, edge"), the chance is the lower of the gain rule and that nearest slice's own share whose
 * peak reached the bar: the gain rule would lend him gains measured on
 * players who were never where he is. The old shares were the whole cell's peak distribution,
 * blind to his current, which tagged players already at 0+ WAA under 100%
 * (user, 2026-09-24: "there are a ton of guys who are already at 0+ WAA
 * that are getting like tagged as less than 100% to reach it"). Those
 * unconditional cell shares still ship as cell_mlb / cell_useful /
 * cell_good for reference. Make it % is playing time (300 PA / 150 BF), not
 * quality; these three say whether he turns out good enough. MLB % is the
 * chance he is ever anything in the majors (user, 2026-09-24: "if they will
 * ever be anything in the mlb first and foremost"); the Org Builder ranks
 * minors playing time on it first (orgBuilder.js chanceOf).
 * Stamped as Dev_PeakMlb / Dev_PeakUseful / Dev_PeakGood, numbers 0-1, with
 * Dev_ShareNow (the current they start from: hitters Max WAA wtd, pitchers
 * the larger of WAA wtd and WAA wtd RP), Dev_ShareBasis (which slice:
 * "now tercile" | "now tercile, edge" | "whole cell" | "pot-only, now
 * tercile" | "pot-only, now tercile, edge" | "pot-only, whole cell"; null
 * when his current is unknown, then the three are the cell shares as is)
 * and Dev_CellMlb / Dev_CellUseful / Dev_CellGood.
 *
 * An absent file means no Dev columns. Rows without an entry get no fields.
 *
 * ML (2026-09-25): when dev_ml.json is on the same pull, devMl.js replaces
 * the peak, gain, chance and Make it fields with the ML model's numbers
 * (Dev_Source 'ML') and keeps the cell method's as Dev_Cell* copies. The
 * text helpers below then say the numbers come from the ML model and show
 * the cell method's value for reference (devIsMl).
 *
 * Pure module apart from fetchDevSignals, so a node check can import it.
 */

/** The Dev signals columns, in the order the table shows them. Make it %
 * (Dev_Odds) is not shown (user, 2026-09-26: "i just want to get rid of the
 * column that you told me to not look at"): it counts playing time, not
 * quality. The field stays on the rows. */
export const DEV_FIELDS = [
  'Dev_Grow', 'Dev_PotDir', 'Dev_PeakMlb', 'Dev_PeakUseful', 'Dev_PeakGood',
  'Dev_PeakP50', 'Dev_PeakRange', 'Dev_PeakVsListed',
  'Dev_VsTypical', 'Dev_Flag',
];

// Growth thresholds (display steps per game-year, summed over core skills).
// keep = at or above these with Pot not falling; move = Pot falling and
// growth at or below the low bar. Same numbers the signals build uses.
export const GROW_KEEP = { H: 4.5, P: 3 };
export const GROW_MOVE = { H: 2, P: 1 };

const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/**
 * Stamp Dev_* fields onto every row whose ID has an entry.
 * Returns the same array when signals is null or has no players, otherwise
 * a new array (rows with an entry are copied, the rest are reused).
 */
export function applyDevSignals(rows, signals) {
  if (!Array.isArray(rows) || !rows.length) return rows;
  const players = signals && signals.players;
  if (!players || typeof players !== 'object') return rows;
  const basis = signals.basis || null;
  let touched = false;
  const out = rows.map(p => {
    const e = players[String(p.ID)];
    if (!e) return p;
    touched = true;
    return {
      ...p,
      Dev_Role: e.role === 'P' ? 'P' : 'H',
      Dev_Grow: num(e.grow),
      Dev_PotDir: e.pot_dir || null,
      Dev_PotDelta: num(e.pot_delta),
      Dev_Odds: num(e.odds),
      Dev_OddsN: num(e.odds_n),
      Dev_OddsCell: e.odds_cell || null,
      Dev_VsTypical: num(e.vs_typical),
      Dev_Flag: e.flag || null,
      Dev_Note: e.note || null,
      Dev_Basis: basis,
      Dev_PeakP25: num(e.peak_p25),
      Dev_PeakP50: num(e.peak_p50),
      Dev_PeakP75: num(e.peak_p75),
      Dev_PeakN: num(e.peak_n),
      Dev_PeakCell: e.peak_cell || null,
      Dev_PeakGainP25: num(e.peak_gain_p25),
      Dev_PeakGainP50: num(e.peak_gain_p50),
      Dev_PeakGainP75: num(e.peak_gain_p75),
      // Chance his peak reaches -1 (MLB level, the chance he is ever
      // anything in the majors) / 0 / +1.5 WAA from where he is now (user,
      // 2026-09-24: a player already at 0+ WAA must not read under 100%).
      Dev_PeakMlb: num(e.peak_mlb),
      Dev_PeakUseful: num(e.peak_useful),
      Dev_PeakGood: num(e.peak_good),
      // The current those chances start from and the slice they were read
      // off (see the header); the whole cell's old shares for reference.
      Dev_ShareNow: num(e.share_now),
      Dev_ShareBasis: e.share_basis || null,
      Dev_CellMlb: num(e.cell_mlb),
      Dev_CellUseful: num(e.cell_useful),
      Dev_CellGood: num(e.cell_good),
      Dev_ListedPeak: num(e.listed_peak),
      Dev_PeakVsListed: num(e.peak_vs_listed),
      // Derived: the 25th to 75th pct band as text, so the table can show it
      // as one column and still sort it (parseFloat reads the low end).
      Dev_PeakRange: fmtPeakRange(e.peak_p25, e.peak_p75),
    };
  });
  return touched ? out : rows;
}

/**
 * Fetch the league's dev_signals.json. Resolves to null when the file is
 * missing (a dev-server SPA fallback counts as missing, same as a 404).
 */
export async function fetchDevSignals(base) {
  try {
    const res = await fetch(`${base}/dev_signals.json`);
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok || !ctype.includes('json')) return null;
    const json = await res.json();
    return json && json.players ? json : null;
  } catch {
    return null;
  }
}

/** Signed one-decimal steps, or '' when null. */
export function fmtGrow(v) {
  const n = num(v);
  if (n === null) return '';
  return (n > 0 ? '+' : '') + n.toFixed(1);
}

/** Odds as a whole percent, or '' when null. */
export function fmtOdds(v) {
  const n = num(v);
  if (n === null) return '';
  return `${Math.round(n * 100)}%`;
}

/** Signed whole internal points, or '' when null. */
export function fmtVsTypical(v) {
  const n = num(v);
  if (n === null) return '';
  const r = Math.round(n);
  return (r > 0 ? '+' : '') + r;
}

/** Signed one-decimal WAA ("+1.2", "-0.3", "0.0"), or '' when null. */
export function fmtWaa(v) {
  const n = num(v);
  if (n === null) return '';
  const s = n.toFixed(1);
  if (s === '0.0' || s === '-0.0') return '0.0';
  return n > 0 ? `+${s}` : s;
}

/** "-0.3 to +1.4" from the 25th and 75th pct, or null when either is missing. */
export function fmtPeakRange(lo, hi) {
  const a = num(lo);
  const b = num(hi);
  if (a === null || b === null) return null;
  return `${fmtWaa(a)} to ${fmtWaa(b)}`;
}

/**
 * The three quality bars (display WAA) behind MLB % / Starter % / Star %,
 * keyed by the short name the hovers use. `already` is the hover for a
 * player whose current sits at or above the bar (his chance reads 100%).
 */
export const PEAK_BARS = {
  mlb: { field: 'Dev_PeakMlb', bar: -1, what: '-1 WAA (an MLB-level player: a 5th starter or bench bat)', already: 'Already at MLB level' },
  useful: { field: 'Dev_PeakUseful', bar: 0, what: '0 WAA (an average starter)', already: 'Already at starter level: an average starter or better' },
  good: { field: 'Dev_PeakGood', bar: 1.5, what: '+1.5 WAA (a star)', already: 'Already a star' },
};

/**
 * A current counts as AT a bar when it is under it by at most this much:
 * the table shows WAA to one decimal, so a row shown as 0.0 can sit at
 * -0.02 and must not read under 100% useful (user, 2026-09-24: "guys
 * already at 0+ WAA tagged as less than 100% is obviously not intended").
 * The same constant lives in the signals build (dev_signals.py).
 */
export const BAR_TOLERANCE = 0.05;

/**
 * True when his chance at that bar is 100% because his current already sits
 * at or above it, within BAR_TOLERANCE (user, 2026-09-24: "guys who are
 * already at 0+ WAA").
 */
export function devAlreadyThere(p, key) {
  const b = PEAK_BARS[key];
  if (!b) return false;
  const s = num(p?.[b.field]);
  const now = num(p?.Dev_ShareNow);
  return s !== null && s >= 0.9995 && now !== null && now >= b.bar - BAR_TOLERANCE;
}

/** True when his current sits outside every lookalike's (Dev_ShareBasis ends in "edge"). */
export function devIsEdge(p) {
  return typeof p?.Dev_ShareBasis === 'string' && p.Dev_ShareBasis.endsWith('edge');
}

/** Plain words for Dev_ShareBasis (which lookalikes the chance was read off). */
export function devShareBasisWords(p) {
  switch (p?.Dev_ShareBasis) {
    case 'now tercile': return 'lookalikes at a similar current';
    case 'now tercile, edge': return 'his current sits outside his lookalikes\' range, so the lower of the gain rule and the nearest group\'s own outcome share is used';
    case 'whole cell': return 'whole group; too few at a similar current';
    case 'pot-only, now tercile': return 'growth group thin, so same age and Pot only, at a similar current';
    case 'pot-only, now tercile, edge': return 'growth group thin, so same age and Pot only; his current sits outside their range, so the lower of the gain rule and the nearest group\'s own outcome share is used';
    case 'pot-only, whole cell': return 'growth group thin, so same age and Pot only, whole group';
    default: return '';
  }
}

/** True when the row's peak, gain and chance fields come from the ML model (devMl.js). */
export function devIsMl(p) {
  return p?.Dev_Source === 'ML';
}

/** The model sentence for an ML row, "the ML model trained on 483 DEV seasons (...)". */
export function devMlWords(p) {
  return p?.Dev_MlWords || 'the ML model trained on the DEV league (every rating, potential, last year\'s growth, level and value)';
}

/** "; ML, outside training range: ..." for a row the models never saw the like of, else ''. */
export function devMlRangeNote(p) {
  return p?.Dev_MlNote ? `; ${p.Dev_MlNote}: DEV has no unsigned international amateurs, so read it with care` : '';
}

/** Cell-method copy of a chance, "cell method: 34%", or '' when unknown. */
function cellWord(v) {
  const n = num(v);
  return n === null ? 'cell method: none' : `cell method: ${fmtOdds(n)}`;
}

/** The cell-method copy field of each chance key. */
const CELL_FIELD = { mlb: 'Dev_CellMlb', useful: 'Dev_CellUseful', good: 'Dev_CellGood' };

/**
 * "Next season: +0.4 (range +0.1 to +0.8)" from the ML path (Dev_MlD[0],
 * Dev_MlD1Lo / Hi), or '' for a row without it.
 */
export function devNextSeasonText(p) {
  const d = Array.isArray(p?.Dev_MlD) ? num(p.Dev_MlD[0]) : null;
  if (d === null) return '';
  const lo = num(p.Dev_MlD1Lo);
  const hi = num(p.Dev_MlD1Hi);
  const range = lo !== null && hi !== null ? ` (range ${fmtWaa(lo)} to ${fmtWaa(hi)})` : '';
  return `Next season: ${fmtWaa(d)}${range}`;
}

/**
 * Hover text for MLB % / Starter % / Star % (columns.js and the Org tab share
 * it so the wording stays the same): the chance his peak reaches the bar
 * from his current, or "Already ..." when he is there. '' when the share is
 * null.
 */
export function devShareTitle(p, key) {
  const b = PEAK_BARS[key];
  if (!b) return '';
  const s = num(p?.[b.field]);
  if (s === null) return '';
  const now = num(p?.Dev_ShareNow);
  const n = num(p?.Dev_PeakN) !== null ? `n ${p.Dev_PeakN}` : 'n unknown';
  const cell = p?.Dev_PeakCell ? `, DEV cell ${p.Dev_PeakCell}` : '';
  // A pitcher's current is the better of his SP and RP lines, which is not
  // always the line the row shows (a rotation row shows the SP line).
  const cur = `${fmtWaa(now)}${p?.Dev_Role === 'P' ? ', his better of SP and RP' : ''}`;
  if (devIsMl(p)) {
    // ML (2026-09-25): the chance comes from the model; the cell method's
    // value is shown for reference.
    const cell = cellWord(p[CELL_FIELD[key]]);
    if (devAlreadyThere(p, key)) return `${b.already} (current ${cur}; ${cell})`;
    return `Chance his peak reaches ${b.what} from his current ${cur}, from ${devMlWords(p)}; ${cell}${devMlRangeNote(p)}`;
  }
  if (devAlreadyThere(p, key)) return `${b.already} (current ${cur})`;
  if (now === null) {
    // No current in the app file: the share is the whole cell's, blind to him.
    return `Share of DEV players with his age, Pot and growth whose eventual peak WAA reached ${b.what} (${n}${cell}); his current is unknown, so this is the group's share, not his own chance`;
  }
  const basis = devShareBasisWords(p);
  if (devIsEdge(p)) {
    // Outside every lookalike's current: the gain rule would lend him gains
    // measured on players who were never where he is, so the nearest
    // group's own outcome share stands in.
    return `Chance his peak reaches ${b.what} from his current ${cur}: ${basis} (the share of the nearest DEV players with his age, Pot and growth whose eventual peak reached the bar; ${n}${cell})`;
  }
  return `Chance his peak reaches ${b.what} from his current ${cur}: the share of DEV players with his age, Pot, growth and a similar current whose gain covered the distance (${n}${cell}${basis ? `, ${basis}` : ''})`;
}

/**
 * The Exp peak sentence for the player card:
 * "players like him ended up at +1.2 WAA (range -0.3 to +2.1), +0.9 above
 * his listed peak; typical gain from here +2.4 WAA; from his -0.4 now: MLB
 * 100% (already there), 62% starter (peak 0 WAA or better), 20% star (+1.5
 * or better); lookalikes at a similar current".
 * The chances are conditional on his current (user, 2026-09-24); without a
 * current in the app file they fall back to the group's own shares.
 * Returns '' when the row has no peak_p50.
 */
export function devPeakText(p) {
  if (!p || num(p.Dev_PeakP50) === null) return '';
  if (devIsMl(p)) return devPeakTextMl(p);
  let s = `players like him ended up at ${fmtWaa(p.Dev_PeakP50)} WAA`;
  if (p.Dev_PeakRange) s += ` (range ${p.Dev_PeakRange})`;
  const d = num(p.Dev_PeakVsListed);
  if (d !== null) {
    if (Math.abs(d) < 0.05) s += ', level with his listed peak';
    else if (d > 0) s += `, ${fmtWaa(d)} above his listed peak`;
    else s += `, ${Math.abs(d).toFixed(1)} below his listed peak`;
  }
  const g = num(p.Dev_PeakGainP50);
  if (g !== null) {
    s += `; typical gain from here ${fmtWaa(g)} WAA`;
    const lo = num(p.Dev_PeakGainP25);
    const hi = num(p.Dev_PeakGainP75);
    if (lo !== null && hi !== null) s += ` (${fmtWaa(lo)} to ${fmtWaa(hi)})`;
  }
  // Chances (user, 2026-09-24): Make it % is playing time, not quality.
  // MLB level first: the chance he is ever anything in the majors. Each is
  // the chance from where he is now, so "already there" when his current
  // sits at the bar.
  const m = num(p.Dev_PeakMlb);
  const u = num(p.Dev_PeakUseful);
  const gd = num(p.Dev_PeakGood);
  const now = num(p.Dev_ShareNow);
  if (u !== null && gd !== null && now !== null) {
    // One parenthetical each: the bar, or "already there" when he is at it.
    const tail = (key, bar) => (devAlreadyThere(p, key) ? ' (already there)' : ` (${bar})`);
    const mlb = m !== null ? `MLB ${fmtOdds(m)}${tail('mlb', 'peak -1 WAA or better')}, ` : '';
    s += `; from his ${fmtWaa(now)} now: ${mlb}${fmtOdds(u)} starter${tail('useful', 'peak 0 WAA or better')}, ${fmtOdds(gd)} star${tail('good', '+1.5 or better')}`;
    const basis = devShareBasisWords(p);
    if (basis) s += `; ${basis}`;
  } else if (u !== null && gd !== null) {
    const mlb = m !== null ? `${fmtOdds(m)} of his lookalikes reached MLB level (-1 WAA or better), ${fmtOdds(u)} became starters` : `${fmtOdds(u)} of his lookalikes became starters`;
    s += `; ${mlb} (peak 0 WAA or better), ${fmtOdds(gd)} became stars (+1.5 or better); his current is unknown, so these are the group's shares`;
  }
  return s;
}

/**
 * Why his growth is unknown, in the words of the signals build's note
 * (dev_signals.py measure_player and its CARD_REPLACED_NOTE / REUSED_ID_NOTE),
 * or '' when the row says nothing. A replaced card comes first: the change
 * from his earlier card was larger than real development (a regenerated or
 * re-scouted card), so that card was not read at all. 'out of an org a year
 * ago' is the old rule's note (before 2026-10-05); a dev_signals.json built
 * before then can still carry it.
 */
function growUnknownReason(p) {
  const note = typeof p?.Dev_Note === 'string' ? p.Dev_Note : '';
  if (note.includes('card replaced between pulls')) return 'card replaced between pulls (regenerated or re-scouted)';
  if (note.includes('out of an org a year ago')) return 'out of an org a year ago';
  if (note.includes('ID held by a different player')) return 'ID held by a different player at the earlier pull';
  for (const why of ['no earlier pull', 'not in the earlier pull', 'core skill missing at the earlier pull']) {
    if (note.includes(why)) return why;
  }
  return '';
}

/**
 * The one-line summary for the player card:
 * "+4.5 steps/yr, Pot up, MLB 100% (already there), 62% starter, 20% star
 * from his -0.4 now, +38 vs typical". MLB (peak -1 WAA or better, the chance
 * he is ever anything in the majors), Starter (0) and Star (+1.5) are the
 * chance from where he is now, so a player at the bar reads 100% (already
 * there). Make it % left the card with its list column (user, 2026-09-26).
 * A row with no growth says why (growUnknownReason).
 * Returns '' for a row without an entry.
 */
export function devSummary(p) {
  if (!p || !p.Dev_Role) return '';
  const parts = [];
  if (p.Dev_Grow === null || p.Dev_Grow === undefined) {
    const why = growUnknownReason(p);
    parts.push(why ? `growth unknown (${why})` : 'growth unknown');
  } else {
    parts.push(`${fmtGrow(p.Dev_Grow)} steps/yr`);
  }
  if (p.Dev_PotDir) parts.push(`Pot ${p.Dev_PotDir}`);
  // Make it % left the card with its list column (user, 2026-09-26).
  const here = key => (devAlreadyThere(p, key) ? ' (already there)' : '');
  const shares = [];
  if (num(p.Dev_PeakMlb) !== null) shares.push(`MLB ${fmtOdds(p.Dev_PeakMlb)}${here('mlb')}`);
  if (num(p.Dev_PeakUseful) !== null) shares.push(`${fmtOdds(p.Dev_PeakUseful)} starter${here('useful')}`);
  if (num(p.Dev_PeakGood) !== null) shares.push(`${fmtOdds(p.Dev_PeakGood)} star${here('good')}`);
  if (shares.length) {
    const now = num(p.Dev_ShareNow);
    parts.push(now !== null ? `${shares.join(', ')} from his ${fmtWaa(now)} now` : shares.join(', '));
  }
  if (p.Dev_VsTypical !== null && p.Dev_VsTypical !== undefined) {
    parts.push(`${fmtVsTypical(p.Dev_VsTypical)} vs typical`);
  }
  return parts.join(', ');
}

/** The small-print basis line under the summary. */
export function devBasisText(p) {
  const b = p && p.Dev_Basis;
  const span = b ? `Growth ${b.from_pull} to ${b.to_pull}, scaled to one game-year.` : '';
  if (devIsMl(p)) {
    // ML (2026-09-25): one sentence for where the numbers come from.
    const note = p.Dev_MlNote ? ` ${p.Dev_MlNote}: DEV has no unsigned international amateurs.` : '';
    return `${span} MLB / Starter / Star %, Exp peak and the gain come from ${devMlWords(p)}; each chance starts from his current ${fmtWaa(p.Dev_ShareNow)}, and a player already at a bar (within ${BAR_TOLERANCE}) reads 100%. The cell method (DEV players with his age, Pot and growth) is shown for reference.${note}`.trim();
  }
  // The Make it % sentence left with Make it % itself (user, 2026-09-26).
  const hasPeak = p && (num(p.Dev_PeakP50) !== null || p.Dev_PeakCell);
  const peak = hasPeak
    ? ' The listed peak prices the potential ratings OOTP shows today; Exp peak is the peak WAA that DEV players with the same age, Pot and growth actually reached. Listed peaks run about 1 WAA above what finished players reach, so a little below listed is normal.'
    : '';
  // MLB / Starter / Star (user, 2026-09-24): Make it % is playing time, not
  // quality, and each chance starts from where he is now, so a player
  // already at 0+ WAA reads 100% starter.
  const hasNow = p && num(p.Dev_ShareNow) !== null;
  const wholeGroup = p && (p.Dev_ShareBasis === 'whole cell' || p.Dev_ShareBasis === 'pot-only, whole cell');
  // Edge (2026-09-24): his current sits outside every lookalike's, so the
  // nearest group's own outcome share stands in for the gain rule.
  const edge = devIsEdge(p);
  const shares = p && num(p.Dev_PeakUseful) !== null
    ? (hasNow
      ? ` MLB / Starter / Star: the chance his peak reaches -1 (an MLB-level player) / 0 / +1.5 WAA from his current ${fmtWaa(p.Dev_ShareNow)}: the share of those DEV players at a similar current whose gain covered the distance; a player already at a bar (within ${BAR_TOLERANCE}, the display rounding) reads 100%.${wholeGroup ? ' Too few at a similar current, so the whole group counts.' : ''}${edge ? ' His current sits outside the range of every lookalike, so the chance is the lower of the gain rule and the nearest group\'s own share whose peak reached each bar.' : ''}`
      : ' MLB / Starter / Star: the share of those same DEV players whose peak reached -1 (an MLB-level player) / 0 / +1.5 WAA; his current is unknown, so these are the group\'s shares, not his own chance.')
    : '';
  const note = p && p.Dev_Note ? ` ${p.Dev_Note}` : '';
  return `${span}${peak}${shares}${note}`.trim();
}

/**
 * The Exp peak sentence for an ML row (2026-09-25): "the ML model expects a
 * peak of +1.2 WAA (range -0.3 to +2.1), ...; gain from here +2.4 WAA (+1.1
 * to +3.5); from his -0.4 now: MLB 100% (already there), 62% starter, 20%
 * star; cell method: peak +0.9, starter 55%".
 */
function devPeakTextMl(p) {
  let s = `the ML model expects a peak of ${fmtWaa(p.Dev_PeakP50)} WAA`;
  if (p.Dev_PeakRange) s += ` (range ${p.Dev_PeakRange})`;
  const d = num(p.Dev_PeakVsListed);
  if (d !== null) {
    if (Math.abs(d) < 0.05) s += ', level with his listed peak';
    else if (d > 0) s += `, ${fmtWaa(d)} above his listed peak`;
    else s += `, ${Math.abs(d).toFixed(1)} below his listed peak`;
  }
  const g = num(p.Dev_PeakGainP50);
  if (g !== null) {
    s += `; gain from here ${fmtWaa(g)} WAA`;
    const lo = num(p.Dev_PeakGainP25);
    const hi = num(p.Dev_PeakGainP75);
    if (lo !== null && hi !== null) s += ` (${fmtWaa(lo)} to ${fmtWaa(hi)})`;
  }
  const m = num(p.Dev_PeakMlb);
  const u = num(p.Dev_PeakUseful);
  const gd = num(p.Dev_PeakGood);
  const now = num(p.Dev_ShareNow);
  if (u !== null && gd !== null && now !== null) {
    const tail = (key, bar) => (devAlreadyThere(p, key) ? ' (already there)' : ` (${bar})`);
    const mlb = m !== null ? `MLB ${fmtOdds(m)}${tail('mlb', 'peak -1 WAA or better')}, ` : '';
    s += `; from his ${fmtWaa(now)} now: ${mlb}${fmtOdds(u)} starter${tail('useful', 'peak 0 WAA or better')}, ${fmtOdds(gd)} star${tail('good', '+1.5 or better')}`;
  }
  const cp = num(p.Dev_CellPeakP50);
  const cu = num(p.Dev_CellUseful);
  const cellBits = [];
  if (cp !== null) cellBits.push(`peak ${fmtWaa(cp)}`);
  if (num(p.Dev_CellGainP50) !== null) cellBits.push(`gain ${fmtWaa(p.Dev_CellGainP50)}`);
  if (cu !== null) cellBits.push(`starter ${fmtOdds(cu)}`);
  s += cellBits.length ? `; cell method: ${cellBits.join(', ')}` : '; cell method: none';
  return s + devMlRangeNote(p);
}
