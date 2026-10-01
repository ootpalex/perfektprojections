/**
 * leagues.js: the league manifest (/data/leagues.json) as the app reads it.
 *
 * Pure module, no imports, so a node check can load it as it is.
 *
 * Manifest entry: { id, name, folder?, datasets?, features? }.
 * Feature flags (each defaults to true when the entry leaves it out):
 *   players   the league has hitters.json / pitchers.json (every player page,
 *             the park toggle). false = a TRENDS-ONLY league: the app reads
 *             only /data/<id>/rating_trends.json and shows the Rating Trends
 *             page alone. Example: the all-AI dev sim
 *             { id: "DEV", name: "Dev test (all-AI sim)",
 *               features: { players: false, trends: true, draft: false, fa: false, contracts: false } }
 *   trends    the Rating Trends page (rating_trends.json exists)
 *   draft     the draft boards
 *   fa        the free-agent boards
 *   contracts contract columns and Market Value
 */

export const DEFAULT_FEATURES = { players: true, trends: true, draft: true, fa: true, contracts: true };

// Used when /data/leagues.json is missing or unreadable: the two leagues the
// app shipped with, so it always boots.
export const FALLBACK_LEAGUES = [
  { id: 'TGS', name: 'TGS', features: { draft: true, fa: true, contracts: true } },
  { id: 'BLM', name: 'BLM', features: { draft: true, fa: false, contracts: true } },
];

/**
 * Accept both manifest schemas:
 *   new:    { "leagues": [{ id, name, features: {...}, ... }] }
 *   legacy: [{ id, name, folder, datasets }]
 * Legacy entries derive draft/fa from their dataset list (contracts unknowable
 * from the old schema, so assumed present; columns are null-safe anyway).
 */
export function normalizeLeagues(raw) {
  const list = Array.isArray(raw) ? raw : (raw && Array.isArray(raw.leagues) ? raw.leagues : []);
  return list
    .filter(lg => lg && lg.id)
    .map(lg => {
      let features = lg.features;
      if (!features && Array.isArray(lg.datasets)) {
        features = {
          draft: lg.datasets.some(d => String(d).endsWith('_draft')),
          fa: lg.datasets.some(d => String(d).endsWith('_fa')),
          contracts: true,
        };
      }
      return {
        ...lg,
        name: lg.name || lg.id,
        features: { ...DEFAULT_FEATURES, ...(features || {}) },
      };
    });
}

/** True for a league with no player files (features.players === false). */
export const isTrendsOnly = lg => !!lg && !!lg.features && lg.features.players === false;
