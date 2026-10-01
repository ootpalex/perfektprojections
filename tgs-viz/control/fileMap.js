// Map a data file to the part of the app it feeds (DESIGN.md 9.2). Pure.
// Paths are relative to tgs-viz/public/data/. Returns {league, key, file} or null (ignored).

import path from 'node:path'

const LEAGUE_RE = /^[A-Za-z0-9_-]{1,16}$/

const PLAYER_FILES = new Set([
  'hitters', 'pitchers', 'hitters_park', 'pitchers_park',
  'hitters_draft', 'pitchers_draft', 'hitters_draft_park', 'pitchers_draft_park',
  'hitters_draft_all', 'pitchers_draft_all', 'hitters_draft_all_park', 'pitchers_draft_all_park',
  'draft_picks', 'iafa', 'r5', 'parks', 'park_list', 'metadata', 'market_fit',
  'dev_signals', 'dev_ml',
].map((n) => n + '.json'))

const LEAGUE_FILES = {
  'age_curve.json': 'age_curve',
  'rating_trends.json': 'trends',
  'calibration.json': 'calibration',
  'park_lineup_values.json': 'series',
}

const ROOT_FILES = {
  'leagues.json': 'leagues',
  'dev_rating_odds.json': 'odds',
}

// Relative path under public/data with "/" separators, or null when the file is outside it.
export function relDataPath(file, publicDataDir) {
  if (typeof file !== 'string' || !file) return null
  if (publicDataDir) {
    const rel = path.relative(path.resolve(publicDataDir), path.resolve(file))
    if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) return null
    return rel.split(path.sep).join('/').replace(/\\/g, '/')
  }
  const m = /(?:^|[\\/])public[\\/]data[\\/](.+)$/.exec(file)
  return m ? m[1].replace(/\\/g, '/') : null
}

// rel: a path relative to public/data ("TGS/hitters.json" or "TGS\\hitters.json").
export function mapDataFile(rel) {
  if (typeof rel !== 'string' || !rel) return null
  const parts = rel.replace(/\\/g, '/').split('/').filter((p) => p !== '')
  const file = parts.join('/')
  if (parts.length === 1) {
    const key = ROOT_FILES[parts[0]]
    return key ? { league: null, key, file } : null
  }
  if (parts.length !== 2) return null
  const [lg, name] = parts
  if (!LEAGUE_RE.test(lg)) return null
  if (PLAYER_FILES.has(name)) return { league: lg, key: 'players', file }
  const key = LEAGUE_FILES[name]
  if (!key) return null
  // ageCurve.js makes DEV's curve every league's curve, so its file counts for all.
  if (key === 'age_curve' && lg === 'DEV') return { league: null, key, file }
  return { league: lg, key, file }
}

// Both steps at once: an absolute (or public/data relative) path to {league, key, file} or null.
export function mapPath(file, publicDataDir) {
  const rel = relDataPath(file, publicDataDir)
  return rel ? mapDataFile(rel) : null
}

// pending_leagues and app_leagues write league null as "*".
export function claimKey(league) {
  return league === null || league === undefined ? '*' : String(league)
}
