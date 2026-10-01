/**
 * Three-letter codes for the ORG column.
 * The user asked for HOU instead of the full team name (2026-09-24).
 * The table shows the code and keeps the full name on hover; sorting and
 * the ORG filter keep using the raw value, so "0" (free agents, amateurs)
 * still sorts as "0".
 */

// Every team name the TGS and BLM pulls carry today, keyed by the exact
// string in hitters.json / pitchers.json. Atlanta covers both the Hammers
// (TGS) and the Braves (BLM). Both Kansas City clubs get their own code.
export const ORG_ABBR = {
  // TGS
  'Anaheim Angels': 'ANA',
  'Arizona Diamondbacks': 'ARI',
  'Atlanta (PWBL) Hammers': 'ATL',
  'Baltimore Orioles': 'BAL',
  'Boston Red Sox': 'BOS',
  'Chicago Cubs': 'CHC',
  'Chicago White Sox': 'CHW',
  'Cincinnati Reds': 'CIN',
  'Cleveland Guardians': 'CLE',
  'Colorado Rockies': 'COL',
  'Detroit (PWBL) Tigers': 'DET',
  'Florida Marlins': 'FLA',
  'Houston Astros': 'HOU',
  'Kansas City Monarchs': 'KCM',
  'Kansas City Royals': 'KCR',
  'Los Angeles Dodgers': 'LAD',
  'Milwaukee Brewers': 'MIL',
  'Minnesota Twins': 'MIN',
  'Montreal Expos': 'MON',
  'New York Mets': 'NYM',
  'New York Yankees': 'NYY',
  'Oakland Athletics': 'OAK',
  'Philadelphia Phillies': 'PHI',
  'Pittsburgh Pirates': 'PIT',
  'San Diego Padres': 'SDP',
  'San Francisco (PWBL) Giants': 'SFG',
  'Seattle (PWBL) Mariners': 'SEA',
  'St. Louis Cardinals': 'STL',
  'Tampa Bay Devil Rays': 'TBD',
  'Texas Rangers': 'TEX',
  'Toronto Blue Jays': 'TOR',
  'Washington Nationals': 'WSN',
  // BLM (names that differ from the TGS spelling)
  'Atlanta Braves': 'ATL',
  'Chicago (A) White Sox': 'CHW',
  'Chicago (N) Cubs': 'CHC',
  'Detroit Tigers': 'DET',
  'Los Angeles (A) Angels': 'LAA',
  'Los Angeles (N) Dodgers': 'LAD',
  'Miami Marlins': 'MIA',
  'New York (A) Yankees': 'NYY',
  'New York (N) Mets': 'NYM',
  'San Francisco Giants': 'SFG',
  'Seattle Mariners': 'SEA',
  'Tampa Bay Rays': 'TBR',
};

/**
 * Three-letter code for a team name.
 * "0", "9", "", null and non-strings come back unchanged.
 * An unknown name falls back to the first three letters of its last word
 * (any "(...)" tag dropped), upper case.
 */
export function orgAbbr(name) {
  if (typeof name !== 'string') return name;
  const key = name.trim();
  if (!key || /^\d+$/.test(key)) return name;
  const known = ORG_ABBR[key];
  if (known) return known;
  const words = key.replace(/\([^)]*\)/g, ' ').trim().split(/\s+/);
  const last = words[words.length - 1] || '';
  return last.slice(0, 3).toUpperCase() || name;
}
