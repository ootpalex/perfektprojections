// The clubs a league's standings / positional-strength / org pages rank against each other.
//
// Source order:
//   1. metadata.json "clubs" (written at pull time by ingest/club_list.py): the league's MLB clubs
//      from the pull, split by the sub-leagues on OOTP's own league page;
//   2. the page's hard-coded AL/NL sets (TeamStandingsPage LEAGUE_TEAMS: TGS, BLM) when the
//      metadata has no club list;
//   3. nothing (known = null): the caller's old fallback, every org with a real roster.
//
// Returns { known, map, names, abbrs }:
//   known  Set of club names, or null (no list)
//   map    { AL: Set, NL: Set } when the league splits into exactly two sub-leagues, else null.
//          The two slots keep the page's AL / NL names; for a metadata list the slots are filled
//          by abbreviation (AL / NL) when the league uses those, else in the league page's order.
//   names  { AL, NL } the sub-league titles to show; abbrs { AL, NL } their short labels.
// Pure: no React, so it is tested in node (tests/client/leagueClubs.test.mjs).

const DEFAULT_NAMES = { AL: 'American League', NL: 'National League' };
const DEFAULT_ABBRS = { AL: 'AL', NL: 'NL' };

function fromMetadata(clubs) {
  const teams = Array.isArray(clubs?.teams)
    ? clubs.teams.filter((t) => t && typeof t.name === 'string' && t.name.trim())
    : [];
  if (teams.length < 2) return null;
  const known = new Set(teams.map((t) => t.name));
  const subs = (Array.isArray(clubs.sub_leagues) ? clubs.sub_leagues : []).filter((s) => s && s.name);
  const split = subs.length === 2 && teams.every((t) => subs.some((s) => s.name === t.sub_league));
  if (!split) return { known, map: null, names: { ...DEFAULT_NAMES }, abbrs: { ...DEFAULT_ABBRS } };
  const byAbbr = (a) => subs.find((s) => String(s.abbr || '').toUpperCase() === a);
  const al = byAbbr('AL') && byAbbr('NL') ? byAbbr('AL') : subs[0];
  const nl = al === subs[0] ? subs[1] : subs[0];
  const members = (s) => new Set(teams.filter((t) => t.sub_league === s.name).map((t) => t.name));
  return {
    known,
    map: { AL: members(al), NL: members(nl) },
    names: { AL: al.name, NL: nl.name },
    abbrs: { AL: al.abbr || al.name, NL: nl.abbr || nl.name },
  };
}

export function resolveLeagueClubs(metadata, builtIn = null) {
  const meta = fromMetadata(metadata?.clubs);
  if (meta) return meta;
  if (builtIn && builtIn.AL && builtIn.NL) {
    return {
      known: new Set([...builtIn.AL, ...builtIn.NL]),
      map: builtIn,
      names: { ...DEFAULT_NAMES },
      abbrs: { ...DEFAULT_ABBRS },
    };
  }
  return { known: null, map: null, names: { ...DEFAULT_NAMES }, abbrs: { ...DEFAULT_ABBRS } };
}
