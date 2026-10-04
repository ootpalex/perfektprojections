// The league's in-game date for the sidebar.
//
// metadata.json game_date is what the pull itself wrote (ingest/roster_clock.py
// write_game_date, from StatsPlus /date), so it is read first. A league whose
// metadata has none (TGS / BLM metadata from the sheets until their next pull, an
// offline league) falls back to the newest rating-trends pull's date.

const DATE = /^\d{4}-\d{2}-\d{2}/;

export function pickGameDate(metadata, trends) {
  const gd = metadata && typeof metadata.game_date === 'string' ? metadata.game_date.trim() : '';
  if (DATE.test(gd)) return gd.slice(0, 10);
  const pulls = trends && Array.isArray(trends.pulls) ? trends.pulls : [];
  const last = pulls.length ? pulls[pulls.length - 1] : null;
  return last && last.g ? last.g : null;
}

// metadata.json of a league, or null (missing, not JSON, offline). no-cache: the
// browser revalidates, so the date follows a pull without a reload.
export async function loadLeagueMetadata(league, fetchImpl = globalThis.fetch) {
  try {
    const res = await fetchImpl(`/data/${league}/metadata.json`, { cache: 'no-cache' });
    const ctype = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
    if (!res.ok || !ctype.includes('json')) return null;
    const v = await res.json();
    return v && typeof v === 'object' && !Array.isArray(v) ? v : null;
  } catch {
    return null;
  }
}
