/**
 * devMl.js: reads /data/<LG>/dev_ml.json (backtest/ml/score.py) and puts the
 * machine-learning numbers on player rows in place of the cell method.
 *
 * User, 2026-09-24: "is there any way you can make a machine learning model
 * to help with figuring out this dev stuff". The models learned from the DEV
 * league (every rating, potential, last year's growth, level and value) and
 * beat the cell method on every target in held-out tests, so the app reads
 * them first. One model set per league: TGS rows get the TGS models, BLM rows
 * the BLM models.
 *
 * STALE GUARD: the file is used only when its pull equals the pull of
 * dev_signals.json (basis.to_pull_id) and its league matches. Otherwise the
 * rows stay on the cell method and one console.info line says why.
 *
 * For a row with ML peak numbers (ages 16-26):
 *   - the cell method's values are kept for reference as Dev_CellGainP25 /
 *     P50 / P75, Dev_CellMlb / Useful / Good, Dev_CellOdds, Dev_CellPeakP50
 *     (the cell's unconditional shares, which dev_signals ships as cell_mlb /
 *     cell_useful / cell_good, move to Dev_CellShareMlb / Useful / Good);
 *   - Dev_PeakGainP25 / P50 / P75 = the ML gain quantiles; Dev_PeakP25 / P50
 *     / P75 = now + gain (Exp peak and its range); Dev_PeakMlb / Useful /
 *     Good and Dev_Odds (Make it %) = the ML chances; Dev_Source = 'ML'.
 * For a row with ML path numbers (ages 16-38): Dev_MlD (median change 1..5
 * years out), Dev_MlDm (expected change, for money), Dev_MlD1Lo / Hi (next
 * season's 25th / 75th percentile), Dev_MlPresent1 (ages 27-38).
 * Everything downstream reads these fields: Proj Potential (futureValue.js
 * devGain and the ML path), the Org Builder (chanceOf / noChance), the
 * columns, the card and the draft boards.
 *
 * Pure module apart from fetchDevMl, so a node check can import it.
 */

const num = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const arr5 = a => (Array.isArray(a) && a.length === 5 && a.every(x => num(x) !== null) ? a.slice() : null);

/** "-0.3 to +1.4" in the same style as devSignals.fmtPeakRange (kept local to avoid a cycle). */
function rangeText(lo, hi) {
  const f = v => {
    const s = v.toFixed(1);
    if (s === '0.0' || s === '-0.0') return '0.0';
    return v > 0 ? `+${s}` : s;
  };
  return lo === null || hi === null ? null : `${f(lo)} to ${f(hi)}`;
}

/**
 * Why the file cannot be used with these signals, or '' when it can.
 * The ML file and dev_signals.json must come from the same pull of the same
 * league (the stale guard).
 */
export function devMlStaleReason(ml, signals) {
  if (!ml || !ml.players) return 'no ML file';
  const sb = signals && signals.basis;
  if (!sb) return 'no dev_signals file to check the pull against';
  if (signals.league && ml.league && signals.league !== ml.league) {
    return `league ${ml.league} does not match dev_signals league ${signals.league}`;
  }
  if (ml.pull === null || ml.pull === undefined || ml.pull !== sb.to_pull_id) {
    return `ML pull ${ml.pull} does not match dev_signals pull ${sb.to_pull_id}`;
  }
  return '';
}

/** One line for the hovers: "the ML model trained on 483 DEV seasons (...)". */
export function devMlModelWords(ml) {
  const n = ml && ml.model && num(ml.model.seasons);
  return `the ML model trained on ${n !== null ? n : '?'} DEV seasons (every rating, potential, last year's growth, level and value)`;
}

/**
 * Put the ML numbers on every row whose ID has an entry. Returns the same
 * array when the file is missing, stale or has no entry for any row (the
 * cell method stays), else a new array (rows with an entry are copied).
 */
export function applyDevMl(rows, ml, signals) {
  if (!Array.isArray(rows) || !rows.length || !ml || !ml.players) return rows;
  if (devMlStaleReason(ml, signals)) return rows;
  const words = devMlModelWords(ml);
  let touched = false;
  const out = rows.map(p => {
    const e = ml.players[String(p.ID)];
    if (!e) return p;
    const q = arr5(e.gain);
    const d = arr5(e.d);
    const dm = arr5(e.dm);
    if (!q && !d) return p;
    touched = true;
    const o = { ...p };
    o.Dev_MlWords = words;
    if (d) {
      o.Dev_MlD = d;
      o.Dev_MlDm = dm;
      o.Dev_MlD1Lo = num(e.d1_lo);
      o.Dev_MlD1Hi = num(e.d1_hi);
      o.Dev_MlPresent1 = num(e.present1);
    }
    if (q) {
      const now = num(e.now);
      // The cell method's values, kept for reference in the hovers.
      o.Dev_CellGainP25 = num(p.Dev_PeakGainP25) ?? null;
      o.Dev_CellGainP50 = num(p.Dev_PeakGainP50) ?? null;
      o.Dev_CellGainP75 = num(p.Dev_PeakGainP75) ?? null;
      o.Dev_CellShareMlb = num(p.Dev_CellMlb) ?? null;
      o.Dev_CellShareUseful = num(p.Dev_CellUseful) ?? null;
      o.Dev_CellShareGood = num(p.Dev_CellGood) ?? null;
      o.Dev_CellMlb = num(p.Dev_PeakMlb) ?? null;
      o.Dev_CellUseful = num(p.Dev_PeakUseful) ?? null;
      o.Dev_CellGood = num(p.Dev_PeakGood) ?? null;
      o.Dev_CellOdds = num(p.Dev_Odds) ?? null;
      o.Dev_CellPeakP50 = num(p.Dev_PeakP50) ?? null;
      // The ML numbers.
      o.Dev_PeakGainP25 = q[1];
      o.Dev_PeakGainP50 = q[2];
      o.Dev_PeakGainP75 = q[3];
      o.Dev_MlGain = q;
      o.Dev_PeakP25 = now !== null ? now + q[1] : null;
      o.Dev_PeakP50 = now !== null ? now + q[2] : null;
      o.Dev_PeakP75 = now !== null ? now + q[3] : null;
      o.Dev_PeakRange = now !== null ? rangeText(now + q[1], now + q[3]) : null;
      const listed = num(p.Dev_ListedPeak);
      o.Dev_PeakVsListed = listed !== null && o.Dev_PeakP50 !== null
        ? Math.round((o.Dev_PeakP50 - listed) * 10) / 10 : null;
      o.Dev_PeakMlb = num(e.mlb);
      o.Dev_PeakUseful = num(e.useful);
      o.Dev_PeakGood = num(e.good);
      o.Dev_Odds = num(e.regular);
      if (now !== null) o.Dev_ShareNow = now;
      if (!o.Dev_Role) o.Dev_Role = e.r === 'P' ? 'P' : 'H';
      o.Dev_Source = 'ML';
      o.Dev_MlNote = e.note || null;
    }
    return o;
  });
  return touched ? out : rows;
}

/**
 * Fetch the league's dev_ml.json. Resolves to null when the file is missing
 * (a dev-server SPA fallback counts as missing, same as a 404).
 */
export async function fetchDevMl(base) {
  try {
    const res = await fetch(`${base}/dev_ml.json`);
    const ctype = res.headers.get('content-type') || '';
    if (!res.ok || !ctype.includes('json')) return null;
    const json = await res.json();
    return json && json.players ? json : null;
  } catch {
    return null;
  }
}
