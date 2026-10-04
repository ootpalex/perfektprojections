import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Routes, Route, NavLink, Navigate, Link, useLocation } from 'react-router-dom';
import { usePlayerData, useLeagues, useMarketRate, DEFAULT_FEATURES } from './hooks/usePlayerData';
import HittersPage from './pages/HittersPage';
import PitchersPage from './pages/PitchersPage';
import DraftBoardPage from './pages/DraftBoardPage';
import MockDraftPage from './pages/MockDraftPage';
import RosterOptimizerPage from './pages/RosterOptimizerPage';
import SeriesPlannerPage from './pages/SeriesPlannerPage';
import DevAnalysisPage from './pages/DevAnalysisPage';
import CalibrationPage from './pages/CalibrationPage';
import MarketValuePage from './pages/MarketValuePage';
import TeamStandingsPage from './pages/TeamStandingsPage';
import OrganizationPage from './pages/OrganizationPage';
import TrendsPage from './pages/TrendsPage';
import WaiverClaimPage from './pages/WaiverClaimPage';
import RosterPlannerPage from './pages/RosterPlannerPage';
import ParksPage from './pages/ParksPage';
import MakeItOddsPage from './pages/MakeItOddsPage';
import ControlPage from './pages/ControlPage';
import ProspectsPage from './pages/ProspectsPage';
import ScoutPage from './pages/ScoutPage';
import PlayerComparePage from './pages/PlayerComparePage';
import { useActiveJobs, useControlStatus, useAppConfig } from './lib/controlApi';
import { loadRatingTrends } from './lib/ratingTrends';
import { loadLeagueMetadata, pickGameDate } from './lib/gameDate';

// The dot next to Control: the most urgent active job. Warn = a job waits for
// an answer, focus = one runs, muted = one only waits for its turn.
function controlDot(jobs) {
  if (!jobs || !jobs.length) return null;
  if (jobs.some(j => j.status === 'waiting' || j.prompt === true)) return { color: 'var(--warn)', pulse: true, title: 'A task needs your answer' };
  if (jobs.some(j => j.status === 'running' || j.status === 'starting')) return { color: 'var(--focus)', pulse: true, title: 'A task is running' };
  if (jobs.some(j => j.status === 'queued')) return { color: 'var(--text-3)', pulse: false, title: 'A task is waiting for its turn' };
  return null;
}

// The footer line about live refresh (DESIGN 9.5).
function RefreshLine({ refresh, liveRefresh }) {
  if (!liveRefresh) {
    return <p style={{ color: 'var(--warn)' }}>Live refresh is off. Press F5 after an update.</p>;
  }
  if (!refresh) return null;
  if (refresh.refreshing) return <p style={{ color: 'var(--focus)' }}>Updating...</p>;
  if (refresh.refreshFailed) return <p style={{ color: 'var(--warn)' }}>Update failed; showing the previous data</p>;
  if (refresh.refreshedAt) {
    const t = new Date(refresh.refreshedAt);
    const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
    return <p>Updated {hhmm}</p>;
  }
  return null;
}

// The league's in-game date: metadata.json game_date (written by the pull itself), else
// the newest ratings pull in rating_trends.json (through the shared cached loader, only
// when the league has trends), else null.
function useGameDate(league, enabled, refreshedAt) {
  const [date, setDate] = useState(null);
  useEffect(() => {
    setDate(null);
    if (!league) return undefined;
    let live = true;
    // metadata.json game_date first (what the pull wrote), else the newest trends pull.
    loadLeagueMetadata(league).then(async (meta) => {
      const first = pickGameDate(meta, null);
      const d = first || pickGameDate(null, enabled ? await loadRatingTrends(league) : null);
      if (live) setDate(d);
    });
    return () => { live = false; };
  }, [league, enabled, refreshedAt]);
  return date;
}

// Night Scorecard sidebar (ootp-dashboard app/docs/redesign/mockup/night-scorecard.html):
// paper panel, nav-controls box, page list with the red-pencil tick on the active page,
// Control pinned at the bottom. Styles: .nav in index.css.
function Sidebar({ leagues, currentLeague, onLeagueChange, parkMode, onParkModeChange, features, iafaCount = 0, r5Count = 0, faCount = 0, refresh = null }) {
  const activeJobs = useActiveJobs();
  const { liveRefresh } = useControlStatus();
  const myOrg = useAppConfig()?.leagues?.[currentLeague]?.my_org;
  const gameDate = useGameDate(currentLeague, features.trends !== false, refresh?.refreshedAt);
  const dot = controlDot(activeJobs);
  const link = ({ isActive }) => (isActive ? 'active' : undefined);
  const current = leagues.find(lg => lg.id === currentLeague);

  // A trends-only league (features.players false) has no player files: the
  // park toggle and every page built on players stay out of the nav, and only
  // Rating Trends is offered.
  const players = features.players !== false;

  // The page list is taller than a short window: only the list scrolls; the brand
  // and the nav-controls box stay pinned above it, Control below it.
  return (
    <nav className="nav" aria-label="Main navigation">
      <div className="brand">SSB</div>

      <div className="nav-controls">
        <label htmlFor="nav-league">League</label>
        {leagues.length > 1 ? (
          <select id="nav-league" className="select" value={currentLeague} onChange={(e) => onLeagueChange(e.target.value)}>
            {leagues.map(lg => <option key={lg.id} value={lg.id}>{lg.name}</option>)}
          </select>
        ) : (
          <div className="input">{current?.name || currentLeague || '—'}</div>
        )}
        <label>My Team</label>
        <div className="input" title="Set on the Setup page (Control)">{myOrg || '—'}</div>
        <label>Game Date</label>
        <div className="input">{gameDate || '—'}</div>
        {/* Park basis — Neutral is the shipped default (contracts normalized) */}
        {players && (
          <>
            <label htmlFor="nav-park">Park basis</label>
            <select id="nav-park" className="select" value={parkMode} onChange={(e) => onParkModeChange(e.target.value)}>
              <option value="neutral">Neutral</option>
              <option value="park">My Park</option>
            </select>
          </>
        )}
      </div>

      <ul className="pages">
        {players && (
          <>
            <li className="group">Team sheets</li>
            <li><NavLink to="/hitters" className={link}>Hitters</NavLink></li>
            <li><NavLink to="/pitchers" className={link}>Pitchers</NavLink></li>

            {features.draft && (
              <>
                <li className="group">Draft</li>
                <li><NavLink to="/hitters-draft" className={link}>Hitters (Draft)</NavLink></li>
                <li><NavLink to="/pitchers-draft" className={link}>Pitchers (Draft)</NavLink></li>
                <li><NavLink to="/draft-board" className={link}>Draft Board</NavLink></li>
                <li><NavLink to="/mock-draft" className={link}>Mock Draft</NavLink></li>
              </>
            )}

            {iafaCount > 0 && (
              <>
                <li className="group">International</li>
                <li><NavLink to="/hitters-iafa" className={link}>IAFA Hitters</NavLink></li>
                <li><NavLink to="/pitchers-iafa" className={link}>IAFA Pitchers</NavLink></li>
              </>
            )}

            {r5Count > 0 && (
              <>
                <li className="group">Rule 5</li>
                <li><NavLink to="/hitters-r5" className={link}>R5 Hitters</NavLink></li>
                <li><NavLink to="/pitchers-r5" className={link}>R5 Pitchers</NavLink></li>
              </>
            )}

            {/* The FA boards derive live from the players (App's fa lists), so they
                show for every league whose lists hold free agents. features.fa only
                tracks the retired hitters_fa.json file; it keeps TGS's link as it was. */}
            {(features.fa || faCount > 0) && (
              <>
                <li className="group">Free agency</li>
                <li><NavLink to="/hitters-fa" className={link}>Hitters (FA)</NavLink></li>
                <li><NavLink to="/pitchers-fa" className={link}>Pitchers (FA)</NavLink></li>
              </>
            )}

            <li className="group">Scouting</li>
            <li><NavLink to="/prospects" className={link}>Prospects</NavLink></li>
            <li><NavLink to="/scout" className={link}>Scout</NavLink></li>
            <li><NavLink to="/compare" className={link}>Player Compare</NavLink></li>

            <li className="group">Organization</li>
            <li><NavLink to="/organization" className={link}>Org Builder</NavLink></li>
            <li><NavLink to="/roster-planner" className={link}>Roster Planner</NavLink></li>
            <li><NavLink to="/waivers" className={link}>Waivers &amp; DFA</NavLink></li>
            <li><NavLink to="/parks" className={link}>Parks</NavLink></li>

            <li className="group">Standings</li>
            <li><NavLink to="/standings" className={link}>Team Projections</NavLink></li>
          </>
        )}

        <li className="group">Tools</li>
        {players && features.contracts && (
          <li><NavLink to="/market-value" className={link}>Market Value</NavLink></li>
        )}
        {players && (
          <>
            <li><NavLink to="/optimizer" className={link}>Roster Optimizer</NavLink></li>
            <li><NavLink to="/series" className={link}>Series Planner</NavLink></li>
            <li><NavLink to="/dev-analysis" className={link}>Dev Analysis</NavLink></li>
          </>
        )}
        {features.trends !== false && (
          <li><NavLink to="/trends" className={link}>Rating Trends</NavLink></li>
        )}
        {/* Make-it odds tables (user asked, 2026-09-24): DEV-league data, one
            file for every league, so the link shows whatever league is picked. */}
        <li><NavLink to="/odds" className={link}>Make-it odds</NavLink></li>
        {players && (
          <li><NavLink to="/calibration" className={link}>Model vs Actual</NavLink></li>
        )}
      </ul>

      {/* Control: always here, for every league and every data state. */}
      <div className="nav-foot">
        <NavLink to="/control" className={link}>
          Control
          {dot && <span className={`dot${dot.pulse ? ' animate-pulse' : ''}`} style={{ background: dot.color }} title={dot.title} />}
        </NavLink>
        <div className="refresh">
          <RefreshLine refresh={refresh} liveRefresh={liveRefresh} />
        </div>
      </div>
    </nav>
  );
}

function LoadingScreen({ progress, league, full = true }) {
  return (
    <div className={`flex items-center justify-center ${full ? 'h-screen' : 'h-full'}`}>
      <div className="text-center space-y-4">
        <div>
          <h2 className="text-xl font-bold ns-text">Loading Player Data</h2>
          <p className="text-sm ns-text-2 mt-1">
            {league ? `Loading ${league} league...` : 'Processing thousands of players...'}
          </p>
        </div>
        <div className="space-y-1.5 text-left">
          {Object.entries(progress).map(([key, status]) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 ${
                status === 'loaded' ? 'bg-[var(--good)]' :
                status === 'loading' ? 'bg-[var(--text)] animate-pulse' :
                status === 'error' ? 'bg-[var(--bad)]' :
                'bg-[var(--text-disabled)]'
              }`} />
              <span className="ns-text-2 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-xs ns-muted">{status}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Shown inside the app shell, so the league menu and Control stay usable.
function ErrorPanel({ error }) {
  return (
    <div className="flex items-center justify-center h-full p-6">
      <div className="text-center space-y-4 max-w-md">
        <div>
          <h2 className="text-xl font-bold ns-text">This league's data could not be loaded</h2>
          <p className="text-sm ns-bad mt-2">{error}</p>
        </div>
        <div className="ns-box ns-box-body text-sm ns-text-2 text-left">
          <p>
            Pick another league in the menu on the left, or open Control, then Setup check, to see what is missing.
          </p>
          <Link to="/control/setup" className="ns-link inline-block mt-3">
            Open Setup check
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const onControl = location.pathname === '/control' || location.pathname.startsWith('/control/');

  // Load the leagues manifest (falls back to built-in TGS/BLM if missing)
  const { leagues, loading: leaguesLoading } = useLeagues();

  // League selection — persisted in localStorage
  const [currentLeague, setCurrentLeague] = useState(() => {
    return localStorage.getItem('tgs-league') || '';
  });

  // When leagues load, ensure we have a valid selection. On the first load an
  // unknown saved league is replaced, as always. A later list (live refresh)
  // that no longer holds the open league only switches the view: the saved
  // choice stays, so it comes back if the league returns.
  const firstLeagues = useRef(true);
  useEffect(() => {
    if (leagues.length > 0) {
      if (firstLeagues.current) {
        firstLeagues.current = false;
        const saved = localStorage.getItem('tgs-league');
        const isValid = leagues.some(lg => lg.id === saved);
        if (!isValid) {
          // Default to first league
          setCurrentLeague(leagues[0].id);
          localStorage.setItem('tgs-league', leagues[0].id);
        }
      } else if (!leagues.some(lg => lg.id === currentLeague)) {
        setCurrentLeague(leagues[0].id);
      }
    }
  }, [leagues]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleLeagueChange = (leagueId) => {
    setCurrentLeague(leagueId);
    localStorage.setItem('tgs-league', leagueId);
  };

  // Park basis — Neutral (default, all parks equal) vs My Park (50% home /
  // 50% other MLB parks). Persisted like the league choice.
  const [parkMode, setParkMode] = useState(() => localStorage.getItem('tgs-park') || 'neutral');
  const handleParkModeChange = (mode) => {
    setParkMode(mode);
    localStorage.setItem('tgs-park', mode);
  };

  // Per-league feature flags from the manifest (unknown league -> everything on,
  // pages already degrade gracefully on missing fields/datasets).
  const activeLeague = leagues.find(lg => lg.id === currentLeague);
  const features = { ...DEFAULT_FEATURES, ...(activeLeague?.features || {}) };
  // players false = a trends-only league: no player files exist, so nothing is
  // fetched and the Rating Trends page is the only page. While the manifest is
  // still loading the flag is unknown, and the fetch starts as it always did.
  const showPlayers = features.players !== false;
  const wantPlayers = leaguesLoading || showPlayers;

  // Load player data for the selected league
  const { data, loading, error, loadProgress, refreshing, refreshedAt, refreshFailed } = usePlayerData(currentLeague, parkMode, wantPlayers);
  const refresh = { refreshing, refreshedAt, refreshFailed };

  // Compute league-wide $/WAA rate (must be before early returns — React hooks rule)
  const marketRate = useMarketRate(data.hitters, data.pitchers, data.marketBank);

  // International amateur class. The ratings pull cannot identify these players (no
  // nationality field exists), so membership comes from the in-game export via
  // ingest/iafa.py. Their projections are the SAME rows as everywhere else, joined on
  // ID — only signing demand and signability are merged in, because StatsPlus has
  // neither. A league with no international phase simply has an empty list.
  const iafa = useMemo(() => {
    const terms = new Map((data.iafa || []).map(r => [String(r.ID), r]));
    if (!terms.size) return { hitters: [], pitchers: [], count: 0 };
    const take = (rows) => (rows || [])
      .filter(p => terms.has(String(p.ID)))
      .map(p => ({ ...p, _iafaDem: terms.get(String(p.ID)).DEM, _iafaSign: terms.get(String(p.ID)).Sign }));
    const h = take(data.hitters), pit = take(data.pitchers);
    return { hitters: h, pitchers: pit, count: h.length + pit.length };
  }, [data.iafa, data.hitters, data.pitchers]);

  // Rule 5 pool — membership from the in-game export (ingest/r5.py), projections
  // joined on ID. The edge: the league shops this pool by OVR/POT card; this
  // screen sorts it by the engine instead.
  const r5 = useMemo(() => {
    const ids = new Set((data.r5 || []).map(r => String(r.ID)));
    if (!ids.size) return { hitters: [], pitchers: [], count: 0 };
    const take = (rows) => (rows || []).filter(p => ids.has(String(p.ID)));
    const h = take(data.hitters), pit = take(data.pitchers);
    return { hitters: h, pitchers: pit, count: h.length + pit.length };
  }, [data.r5, data.hitters, data.pitchers]);

  // Free agents, derived LIVE from the current pull (no org = FA — same rule as
  // the contract Status column). The old hitters_fa/pitchers_fa.json files were
  // a retired Excel extract that silently shadowed fresh data with a stale
  // snapshot on a different calibration basis; they are no longer read, and the
  // FA pages now follow every pull (and the park toggle) automatically.
  const fa = useMemo(() => {
    // Prefer the pull's stamped FA flag (true free agent; amateurs get FA:false +
    // Lev "AMA" — a 15yo draft-pool kid is NOT a free agent, user 2026-09-04).
    // Data from before the stamp has no FA field anywhere — fall back to the old
    // no-org rule so the pages never go empty on a stale pull.
    const stamped = (data.hitters || []).some(p => p.FA !== undefined)
      || (data.pitchers || []).some(p => p.FA !== undefined);
    const isFA = stamped
      ? (p) => p.FA === true
      : (p) => { const org = String(p.ORG ?? '').trim(); return !org || org === '0'; };
    return {
      hitters: (data.hitters || []).filter(isFA),
      pitchers: (data.pitchers || []).filter(isFA),
    };
  }, [data.hitters, data.pitchers]);

  // Today's layout: the sidebar and the page. Every state below the first
  // manifest load keeps the sidebar, so the league menu and Control stay usable.
  const shell = (content) => (
    <div className="flex h-screen" style={{ background: 'var(--bg)' }}>
      <Sidebar
        leagues={leagues}
        currentLeague={currentLeague}
        onLeagueChange={handleLeagueChange}
        parkMode={parkMode}
        onParkModeChange={handleParkModeChange}
        features={features}
        iafaCount={iafa.count}
        r5Count={r5.count}
        faCount={fa.hitters.length + fa.pitchers.length}
        refresh={refresh}
      />
      <main className="flex-1 overflow-hidden">
        <div className="h-full">
          {content}
        </div>
      </main>
    </div>
  );

  // Show loading while leagues manifest loads (first load only)
  if (leaguesLoading) return <LoadingScreen progress={{}} league="" />;

  // The Control page works whatever state the league data is in; the player
  // data keeps loading underneath.
  if (onControl) return shell(<ControlPage league={currentLeague} />);

  if (leagues.length === 0) return shell(<ErrorPanel error="No leagues found." />);

  // Show loading while player data loads
  if (loading) return shell(<LoadingScreen progress={loadProgress} league={currentLeague} full={false} />);
  if (error) return shell(<ErrorPanel error={error} />);

  const hasData = data.hitters.length > 0 || data.pitchers.length > 0;

  if (!hasData && showPlayers) {
    return shell(<ErrorPanel error={`No player data found for league "${currentLeague}".`} />);
  }

  return shell(
          !showPlayers ? (
          // Trends-only league: one page. Any other path (a player page left
          // open from the previous league) lands on it.
          <Routes>
            <Route path="/trends" element={<TrendsPage league={currentLeague} />} />
            <Route path="/odds" element={<MakeItOddsPage />} />
            <Route path="*" element={<Navigate to="/trends" replace />} />
          </Routes>
          ) : (
          <Routes>
            <Route path="/" element={<Navigate to="/hitters" replace />} />
            <Route path="/hitters" element={<HittersPage players={data.hitters} allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers" element={<PitchersPage players={data.pitchers} allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-draft" element={<HittersPage players={data.hitters_draft} isDraft allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-draft" element={<PitchersPage players={data.pitchers_draft} isDraft allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-fa" element={<HittersPage players={fa.hitters} isFA allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-fa" element={<PitchersPage players={fa.pitchers} isFA allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-iafa" element={<HittersPage players={iafa.hitters} isIAFA isFA allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-iafa" element={<PitchersPage players={iafa.pitchers} isIAFA isFA allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/hitters-r5" element={<HittersPage players={r5.hitters} isR5 allPlayers={data.hitters} marketRate={marketRate} />} />
            <Route path="/pitchers-r5" element={<PitchersPage players={r5.pitchers} isR5 allPlayers={data.pitchers} marketRate={marketRate} />} />
            <Route path="/draft-board" element={
              <DraftBoardPage
                hitters={data.hitters_draft.length ? data.hitters_draft : data.hitters}
                pitchers={data.pitchers_draft.length ? data.pitchers_draft : data.pitchers}
                allHitters={data.hitters}
                allPitchers={data.pitchers}
                picks={data.draft_picks}
                league={currentLeague}
              />
            } />
            <Route path="/mock-draft" element={
              <MockDraftPage
                hitters={data.hitters_draft}
                pitchers={data.pitchers_draft}
                fullHitters={data.hitters_draft_all}
                fullPitchers={data.pitchers_draft_all}
                picks={data.draft_picks}
                allHitters={data.hitters}
                allPitchers={data.pitchers}
              />
            } />
            <Route path="/standings" element={
              <TeamStandingsPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} />
            } />
            <Route path="/prospects" element={<ProspectsPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} />} />
            <Route path="/scout" element={<ScoutPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} />} />
            <Route path="/compare" element={<PlayerComparePage hitters={data.hitters} pitchers={data.pitchers} />} />
            <Route path="/parks" element={<ParksPage parks={data.parks} parkList={data.park_list} league={currentLeague} />} />
            <Route path="/organization" element={
              <OrganizationPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} parkMode={parkMode} />
            } />
            <Route path="/roster-planner" element={
              <RosterPlannerPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} />
            } />
            <Route path="/waivers" element={
              <WaiverClaimPage hitters={data.hitters} pitchers={data.pitchers} league={currentLeague} />
            } />
            <Route path="/market-value" element={
              <MarketValuePage hitters={data.hitters} pitchers={data.pitchers} marketBank={data.marketBank} />
            } />
            <Route path="/optimizer" element={
              <RosterOptimizerPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} />
            } />
            <Route path="/series" element={
              <SeriesPlannerPage hitters={data.hitters} pitchers={data.pitchers} parks={data.parks} metadata={data.metadata} league={currentLeague} parkMode={parkMode} />
            } />
            <Route path="/dev-analysis" element={<DevAnalysisPage />} />
            <Route path="/calibration" element={<CalibrationPage league={currentLeague} />} />
            <Route path="/trends" element={<TrendsPage league={currentLeague} />} />
            <Route path="/odds" element={<MakeItOddsPage />} />
          </Routes>
          )
  );
}
