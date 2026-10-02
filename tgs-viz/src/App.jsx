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
import ParksPage from './pages/ParksPage';
import MakeItOddsPage from './pages/MakeItOddsPage';
import ControlPage from './pages/ControlPage';
import { useActiveJobs, useControlStatus } from './lib/controlApi';
import { Users, Zap, Target, Trophy, Loader2, AlertCircle, BarChart3, TrendingUp, ChevronDown, DollarSign, TableProperties, Building2, Activity, ClipboardList, Swords, Percent, SquareTerminal } from 'lucide-react';

// The dot next to Control: the most urgent active job. Amber = a job waits for
// an answer, blue = one runs, slate = one only waits for its turn.
function controlDot(jobs) {
  if (!jobs || !jobs.length) return null;
  if (jobs.some(j => j.status === 'waiting' || j.prompt === true)) return { cls: 'bg-amber-400 animate-pulse', title: 'A task needs your answer' };
  if (jobs.some(j => j.status === 'running' || j.status === 'starting')) return { cls: 'bg-blue-400 animate-pulse', title: 'A task is running' };
  if (jobs.some(j => j.status === 'queued')) return { cls: 'bg-slate-500', title: 'A task is waiting for its turn' };
  return null;
}

// The footer line about live refresh (DESIGN 9.5).
function RefreshLine({ refresh, liveRefresh }) {
  if (!liveRefresh) {
    return <p className="text-amber-400/80 mb-1">Live refresh is off. Press F5 after an update.</p>;
  }
  if (!refresh) return null;
  if (refresh.refreshing) return <p className="text-blue-400 mb-1">Updating...</p>;
  if (refresh.refreshFailed) return <p className="text-amber-400 mb-1">Update failed; showing the previous data</p>;
  if (refresh.refreshedAt) {
    const t = new Date(refresh.refreshedAt);
    const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
    return <p className="text-slate-500 mb-1">Updated {hhmm}</p>;
  }
  return null;
}

function Sidebar({ leagues, currentLeague, onLeagueChange, parkMode, onParkModeChange, features, iafaCount = 0, r5Count = 0, faCount = 0, refresh = null }) {
  const activeJobs = useActiveJobs();
  const { liveRefresh } = useControlStatus();
  const dot = controlDot(activeJobs);
  const linkClass = ({ isActive }) =>
    `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
      isActive
        ? 'bg-blue-600/20 text-blue-400 border-l-2 border-blue-400'
        : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
    }`;

  // A trends-only league (features.players false) has no player files: the
  // park toggle and every page built on players stay out of the nav, and only
  // Rating Trends is offered.
  const players = features.players !== false;

  // The link list is taller than a short window. Without overflow-y-auto on it
  // the nav grows past the viewport, the whole document scrolls, and every page
  // looks cut off with a blank band under it. Only the list scrolls; the league
  // select and park toggle stay pinned above it.
  return (
    <nav className="w-56 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col h-full">
      <div className="p-4 border-b border-slate-800">
        <h1 className="text-lg font-black text-white tracking-tight">TGS</h1>
        <p className="text-[10px] text-slate-500 uppercase tracking-widest">Projections Viz</p>
      </div>

      {/* League Switcher */}
      {leagues.length > 1 && (
        <div className="px-3 pt-3 pb-1">
          <p className="text-[10px] text-slate-600 uppercase tracking-widest px-1 pb-1.5">League</p>
          <div className="relative">
            <select
              value={currentLeague}
              onChange={(e) => onLeagueChange(e.target.value)}
              className="w-full appearance-none bg-slate-800 text-white text-sm font-semibold rounded-lg px-3 py-2 pr-8 border border-slate-700 hover:border-blue-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 transition-colors cursor-pointer"
            >
              {leagues.map(lg => (
                <option key={lg.id} value={lg.id}>{lg.name}</option>
              ))}
            </select>
            <ChevronDown size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          </div>
        </div>
      )}

      {/* Park basis toggle — Neutral is the shipped default (contracts normalized) */}
      {players && (
      <div className="px-3 pt-2 pb-1">
        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-1 pb-1.5">Park Basis</p>
        <div className="flex rounded-lg overflow-hidden border border-slate-700">
          {[['neutral', 'Neutral'], ['park', 'My Park']].map(([mode, label]) => (
            <button
              key={mode}
              onClick={() => onParkModeChange(mode)}
              className={`flex-1 px-2 py-1.5 text-xs font-semibold transition-colors ${
                parkMode === mode
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-0.5">
        {players && (
        <>
        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-3 pb-1">Team Sheets</p>
        <NavLink to="/hitters" className={linkClass}>
          <Users size={16} /> Hitters
        </NavLink>
        <NavLink to="/pitchers" className={linkClass}>
          <Zap size={16} /> Pitchers
        </NavLink>

        {features.draft && (
          <>
            <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Draft</p>
            <NavLink to="/hitters-draft" className={linkClass}>
              <Users size={16} /> Hitters (Draft)
            </NavLink>
            <NavLink to="/pitchers-draft" className={linkClass}>
              <Zap size={16} /> Pitchers (Draft)
            </NavLink>
            <NavLink to="/draft-board" className={linkClass}>
              <BarChart3 size={16} /> Draft Board
            </NavLink>
            <NavLink to="/mock-draft" className={linkClass}>
              <BarChart3 size={16} /> Mock Draft
            </NavLink>
          </>
        )}

        {iafaCount > 0 && (
          <>
            <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">International</p>
            <NavLink to="/hitters-iafa" className={linkClass}>
              <Users size={16} /> IAFA Hitters
            </NavLink>
            <NavLink to="/pitchers-iafa" className={linkClass}>
              <Zap size={16} /> IAFA Pitchers
            </NavLink>
          </>
        )}

        {r5Count > 0 && (
          <>
            <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Rule 5</p>
            <NavLink to="/hitters-r5" className={linkClass}>
              <Users size={16} /> R5 Hitters
            </NavLink>
            <NavLink to="/pitchers-r5" className={linkClass}>
              <Zap size={16} /> R5 Pitchers
            </NavLink>
          </>
        )}

        {/* The FA boards derive live from the players (App's fa lists), so they
            show for every league whose lists hold free agents. features.fa only
            tracks the retired hitters_fa.json file; it keeps TGS's link as it was. */}
        {(features.fa || faCount > 0) && (
          <>
            <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Free Agency</p>
            <NavLink to="/hitters-fa" className={linkClass}>
              <Users size={16} /> Hitters (FA)
            </NavLink>
            <NavLink to="/pitchers-fa" className={linkClass}>
              <Zap size={16} /> Pitchers (FA)
            </NavLink>
          </>
        )}

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Organization</p>
        <NavLink to="/organization" className={linkClass}>
          <Building2 size={16} /> Org Builder
        </NavLink>
        <NavLink to="/waivers" className={linkClass}>
          <ClipboardList size={16} /> Waivers &amp; DFA
        </NavLink>
        <NavLink to="/parks" className={linkClass}>
          <Building2 size={16} /> Parks
        </NavLink>

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Standings</p>
        <NavLink to="/standings" className={linkClass}>
          <TableProperties size={16} /> Team Projections
        </NavLink>
        </>
        )}

        <p className="text-[10px] text-slate-600 uppercase tracking-widest px-3 pt-4 pb-1">Tools</p>
        {players && features.contracts && (
          <NavLink to="/market-value" className={linkClass}>
            <DollarSign size={16} /> Market Value
          </NavLink>
        )}
        {players && (
        <>
        <NavLink to="/optimizer" className={linkClass}>
          <Trophy size={16} /> Roster Optimizer
        </NavLink>
        <NavLink to="/series" className={linkClass}>
          <Swords size={16} /> Series Planner
        </NavLink>
        <NavLink to="/dev-analysis" className={linkClass}>
          <TrendingUp size={16} /> Dev Analysis
        </NavLink>
        </>
        )}
        {features.trends !== false && (
        <NavLink to="/trends" className={linkClass}>
          <Activity size={16} /> Rating Trends
        </NavLink>
        )}
        {/* Make-it odds tables (user asked, 2026-09-24): DEV-league data, one
            file for every league, so the link shows whatever league is picked. */}
        <NavLink to="/odds" className={linkClass}>
          <Percent size={16} /> Make-it odds
        </NavLink>
        {players && (
        <NavLink to="/calibration" className={linkClass}>
          <Target size={16} /> Model vs Actual
        </NavLink>
        )}
      </div>
      {/* Control: always here, for every league and every data state. */}
      <div className="px-2 pt-2 border-t border-slate-800">
        <NavLink to="/control" className={linkClass}>
          <SquareTerminal size={16} /> Control
          {dot && <span className={`ml-auto w-2 h-2 rounded-full ${dot.cls}`} title={dot.title} />}
        </NavLink>
      </div>
      <div className="p-3 border-t border-slate-800 text-[10px] text-slate-600 mt-2">
        <RefreshLine refresh={refresh} liveRefresh={liveRefresh} />
        OOTP Analytics
      </div>
    </nav>
  );
}

function LoadingScreen({ progress, league, full = true }) {
  return (
    <div className={`flex items-center justify-center ${full ? 'h-screen' : 'h-full'} bg-slate-950`}>
      <div className="text-center space-y-4">
        <Loader2 size={48} className="animate-spin text-blue-500 mx-auto" />
        <div>
          <h2 className="text-xl font-bold text-white">Loading Player Data</h2>
          <p className="text-sm text-slate-400 mt-1">
            {league ? `Loading ${league} league...` : 'Processing thousands of players...'}
          </p>
        </div>
        <div className="space-y-1.5 text-left">
          {Object.entries(progress).map(([key, status]) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <span className={`w-2 h-2 rounded-full ${
                status === 'loaded' ? 'bg-green-400' :
                status === 'loading' ? 'bg-blue-400 animate-pulse' :
                status === 'error' ? 'bg-red-400' :
                'bg-slate-600'
              }`} />
              <span className="text-slate-400 capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="text-xs text-slate-600">{status}</span>
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
    <div className="flex items-center justify-center h-full bg-slate-950 p-6">
      <div className="text-center space-y-4 max-w-md">
        <AlertCircle size={48} className="text-red-400 mx-auto" />
        <div>
          <h2 className="text-xl font-bold text-white">This league's data could not be loaded</h2>
          <p className="text-sm text-red-400 mt-2">{error}</p>
        </div>
        <div className="text-sm text-slate-400 bg-slate-900 border border-slate-800 rounded-lg p-4 text-left">
          <p>
            Pick another league in the menu on the left, or open Control, then Setup check, to see what is missing.
          </p>
          <Link to="/control/setup" className="inline-block mt-3 text-blue-400 hover:text-blue-300 font-semibold">
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
    <div className="flex h-screen bg-slate-950">
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
        <div className="gradient-bar" />
        <div className="h-[calc(100%-3px)]">
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
            <Route path="/parks" element={<ParksPage parks={data.parks} parkList={data.park_list} league={currentLeague} />} />
            <Route path="/organization" element={
              <OrganizationPage hitters={data.hitters} pitchers={data.pitchers} metadata={data.metadata} league={currentLeague} parkMode={parkMode} />
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
