/**
 * ratingTrends.js — loader/helpers for /data/<LG>/rating_trends.json, the
 * ratings-history export built by backtest/ratings_db.py --export.
 *
 * INFORMATIONAL ONLY: this data shows how scouting ratings moved across pulls.
 * Nothing here feeds any projection — projections are ratings-only from the
 * CURRENT pull, exactly as before.
 */

const cache = {};

/**
 * Rating display scales the export can stamp in age_curves.scale, and the
 * size of one display step on each: 1 point on 20-80, and 100/60 = 1.67
 * points on 1-100 (one 20-80 point spans that much of 1-100). An export
 * without a stamp is a 20-80 league (TGS, BLM).
 */
export const DISPLAY_UNIT = { '20-80': 1, '1-100': 100 / 60 };

/** The league's rating display scale: "20-80" (default) or "1-100". */
export function ratingScale(ageCurves) {
  const s = ageCurves?.scale;
  return DISPLAY_UNIT[s] ? s : '20-80';
}

/**
 * Forget the cached trends of one league, so the next load fetches the file
 * again (live refresh, lib/dataVersion.js). No league: forget every league.
 */
export function invalidateRatingTrends(league) {
  if (league === undefined || league === null) {
    for (const k of Object.keys(cache)) delete cache[k];
    for (const k of Object.keys(probes)) delete probes[k];
    return;
  }
  delete cache[league];
  delete probes[league];
}

const probes = {};

/**
 * Whether the league's trends file exists, without downloading it: a HEAD
 * request (DEV's file is ~10 MB, and the league list needs only its presence).
 * Reuses a full load already made; falls back to one if the server refuses HEAD.
 */
export function probeRatingTrends(league) {
  const lg = league || 'TGS';
  if (cache[lg]) return cache[lg].then((t) => t != null);
  if (!probes[lg]) {
    probes[lg] = fetch(`/data/${lg}/rating_trends.json`, { method: 'HEAD' })
      .then((res) => {
        if (res.status === 405 || res.status === 501) return loadRatingTrends(lg).then((t) => t != null);
        // Non-JSON = dev-server SPA fallback for a missing file, as in loadRatingTrends.
        const ctype = res.headers.get('content-type') || '';
        return res.ok && ctype.includes('json');
      })
      .catch(() => false);
  }
  return probes[lg];
}

/** Fetch (once per league) the trends file. Resolves to null when missing. */
export function loadRatingTrends(league) {
  const lg = league || 'TGS';
  if (!cache[lg]) {
    cache[lg] = fetch(`/data/${lg}/rating_trends.json`)
      .then(res => {
        const ctype = res.headers.get('content-type') || '';
        if (!res.ok || !ctype.includes('json')) throw new Error(`rating_trends.json ${res.status}`);
        return res.json();
      })
      .catch(() => null);
  }
  return cache[lg];
}

/**
 * Per-rating history for one player.
 * Returns null when the trends file is missing, or
 * { dates, rows: [{col, values (aligned to dates, null = not in that pull),
 *   first, last, delta}], vintages } — rows sorted by |delta| desc.
 * A player absent from the file had NO rating changes in the window.
 */
export function playerHistory(trends, playerId) {
  if (!trends || !trends.players) return null;
  const entry = trends.players[String(playerId)];
  const windowIdx = trends.window || [];
  const dates = windowIdx.map(i => (trends.pulls[i] ? trends.pulls[i].d : ''));
  if (!entry) return { dates, rows: [], vintages: trends.pulls.length };
  const rows = Object.entries(entry.s).map(([ci, values]) => {
    const present = values.filter(v => v !== null && v !== undefined);
    const first = present.length ? present[0] : null;
    const last = present.length ? present[present.length - 1] : null;
    return {
      col: trends.cols[Number(ci)] || `#${ci}`,
      values,
      first,
      last,
      delta: (first !== null && last !== null) ? last - first : 0,
    };
  });
  rows.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  return { dates, rows, vintages: trends.pulls.length };
}
