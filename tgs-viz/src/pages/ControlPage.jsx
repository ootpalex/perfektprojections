import React, { useEffect, useMemo, useState } from 'react';
import { Routes, Route, NavLink, Navigate, Link, useParams, useLocation } from 'react-router-dom';
import { Play, Plus, Settings, Loader2, ChevronDown, ChevronRight, ArrowLeft, History, RefreshCw } from 'lucide-react';
import {
  useControlStatus, useCatalog, useActiveJobs, useRecentJobIds, listJobs, dismissRecent, reloadCatalog,
} from '../lib/controlApi';
import TaskCard from '../components/control/TaskCard';
import TaskForm from '../components/control/TaskForm';
import JobPanel, { StatusDot, statusWord, formatWhen } from '../components/control/JobPanel';
import NewLeagueWizard from '../components/control/NewLeagueWizard';
import SetupPanel from '../components/control/SetupPanel';
import { Notice } from '../components/control/PromptCard';

const GROUPS_KEY = 'tgs-control.groups';

function readGroups() {
  try { return JSON.parse(localStorage.getItem(GROUPS_KEY) || '{}') || {}; } catch { return {}; }
}
function saveGroups(v) {
  try { localStorage.setItem(GROUPS_KEY, JSON.stringify(v)); } catch { /* storage blocked: the choice lasts for the session */ }
}

const tabClass = ({ isActive }) => (isActive
  ? 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white flex items-center gap-1.5'
  : 'px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 text-slate-400 hover:text-slate-200 flex items-center gap-1.5');

function Connection({ status }) {
  if (status.mode === 'connecting') {
    return (
      <div className="flex items-center gap-2 text-slate-400 text-sm p-4">
        <Loader2 size={16} className="animate-spin" /> Connecting to the app server...
      </div>
    );
  }
  if (status.mode === 'no_plugin') {
    return (
      <Notice tone="warn" title="The Control page is not available">
        <p>The Control page works only when the app runs from Launch TGS.bat.</p>
      </Notice>
    );
  }
  if (status.mode === 'off') {
    return (
      <Notice tone="warn" title="The Control panel is off">
        <p>The Control panel is off: {status.reason || 'no reason given'}. The app itself works.</p>
        <p>Run Check Setup.bat in the TGS Projections folder.</p>
      </Notice>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Tasks view: active jobs, then the task cards by group, then recent runs.
// ---------------------------------------------------------------------------

function RecentRuns({ refreshKey }) {
  const [jobs, setJobs] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return undefined;
    let on = true;
    listJobs(20).then(j => { if (on) { setJobs(j); setErr(null); } }).catch(e => { if (on) setErr(e.message); });
    return () => { on = false; };
  }, [open, refreshKey]);
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-2 px-4 py-3 text-left">
        {open ? <ChevronDown size={16} className="text-slate-500" /> : <ChevronRight size={16} className="text-slate-500" />}
        <History size={16} className="text-slate-400" />
        <span className="text-sm font-bold text-slate-200">Recent runs</span>
      </button>
      {open && (
        <div className="px-4 pb-3">
          {err && <p className="text-xs text-red-400">{err}</p>}
          {!jobs && !err && <p className="text-xs text-slate-500">Loading...</p>}
          {jobs && !jobs.length && <p className="text-xs text-slate-500">No runs yet.</p>}
          {jobs && jobs.length > 0 && (
            <table className="w-full text-xs">
              <tbody>
                {jobs.map(j => (
                  <tr key={j.id} className="border-t border-slate-800/70">
                    <td className="py-1.5 pr-2"><StatusDot status={j.status} /></td>
                    <td className="py-1.5 pr-2 text-slate-200">
                      <Link to={`/control/jobs/${encodeURIComponent(j.id)}`} className="hover:text-blue-400">{j.title || j.task}</Link>
                    </td>
                    <td className="py-1.5 pr-2 text-slate-400">{statusWord(j.status)}</td>
                    <td className="py-1.5 text-slate-500 text-right whitespace-nowrap">{formatWhen(j.started || j.requested_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function TasksView() {
  const { catalog, error } = useCatalog();
  const active = useActiveJobs();
  const recent = useRecentJobIds();
  const [groupsOpen, setGroupsOpen] = useState(readGroups);
  const [formTask, setFormTask] = useState(null);

  const groups = useMemo(() => {
    if (!catalog) return [];
    const tasks = (catalog.tasks || []).filter(t => !t.flags?.hidden);
    const known = (catalog.groups || []).map(g => g.id);
    const out = (catalog.groups || []).map(g => ({ ...g, tasks: tasks.filter(t => t.group === g.id) }));
    const other = tasks.filter(t => !known.includes(t.group));
    if (other.length) out.push({ id: '_other', title: 'Other', tasks: other });
    return out.filter(g => g.tasks.length);
  }, [catalog]);

  const toggle = (id) => setGroupsOpen(prev => {
    const next = { ...prev, [id]: prev[id] === false };
    saveGroups(next);
    return next;
  });

  const settingsError = catalog?.state?.settings_error;

  return (
    <div className="space-y-4">
      {settingsError && (
        <Notice tone="error" title="The settings file has a problem">
          <p>{settingsError}</p>
          <p>Only the setup check can run until it is fixed. <Link to="/control/setup" className="text-blue-300 underline">Open Setup check</Link>.</p>
        </Notice>
      )}

      {(active.length > 0 || recent.length > 0) && (
        <div className="space-y-3">
          {active.map(j => <JobPanel key={j.id} jobId={j.id} compact />)}
          {recent.map(id => <JobPanel key={id} jobId={id} compact onDismiss={() => dismissRecent(id)} />)}
        </div>
      )}

      {error && !catalog && (
        <Notice tone="error" title="The task list did not load">
          <p>{error.message}</p>
          {error.body?.stderr_tail && <pre className="text-[11px] whitespace-pre-wrap text-red-300/80">{error.body.stderr_tail}</pre>}
          <button onClick={() => reloadCatalog(true)} className="mt-2 px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 text-slate-200 hover:bg-slate-700 inline-flex items-center gap-1.5">
            <RefreshCw size={12} /> Try again
          </button>
        </Notice>
      )}
      {!catalog && !error && (
        <div className="flex items-center gap-2 text-slate-400 text-sm"><Loader2 size={16} className="animate-spin" /> Loading the task list...</div>
      )}

      {groups.map(g => {
        const open = groupsOpen[g.id] !== false;
        return (
          <section key={g.id}>
            <button onClick={() => toggle(g.id)} className="flex items-center gap-1.5 mb-2 text-left">
              {open ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-widest">{g.title}</span>
              <span className="text-[11px] text-slate-600">({g.tasks.length})</span>
            </button>
            {open && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                {g.tasks.map(t => <TaskCard key={t.id} task={t} onRun={() => setFormTask(t)} />)}
              </div>
            )}
          </section>
        );
      })}

      <RecentRuns refreshKey={`${active.length}-${recent.join(',')}`} />

      {formTask && (
        <TaskForm task={formTask} onClose={() => setFormTask(null)} onStarted={() => {
          setFormTask(null);
          // The new job's panel sits at the top of this page.
          document.querySelector('[data-control-scroll]')?.scrollTo({ top: 0, behavior: 'smooth' });
        }} />
      )}
    </div>
  );
}

function JobView() {
  const { id } = useParams();
  return (
    <div className="space-y-3">
      <Link to="/control" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200">
        <ArrowLeft size={14} /> All tasks
      </Link>
      <JobPanel jobId={id} />
    </div>
  );
}

export default function ControlPage() {
  const status = useControlStatus();
  const location = useLocation();
  const onSetup = location.pathname.startsWith('/control/setup');

  return (
    <div className="h-full overflow-auto" data-control-scroll>
      <div className="p-4 pb-2">
        <h1 className="text-2xl font-bold text-white">Control</h1>
        <p className="text-sm text-slate-400 mt-1 max-w-3xl">
          Run the updates and tools from here. Each task does the same as its .bat file. The app updates
          itself when a task finishes a league; no reload needed.
        </p>
        <div className="flex gap-1 mt-3">
          <NavLink to="/control" end className={tabClass}><Play size={12} /> Tasks</NavLink>
          <NavLink to="/control/new-league" className={tabClass}><Plus size={12} /> New league</NavLink>
          <NavLink to="/control/setup" className={tabClass}><Settings size={12} /> Setup check</NavLink>
        </div>
      </div>

      <div className="p-4 pt-2 max-w-6xl">
        {status.mode !== 'ok' ? (
          <div className="space-y-3">
            <Connection status={status} />
            {onSetup && status.mode === 'off' && status.python && status.python.ok === false && (
              <Notice tone="warn" title="Python">
                <p>Install Python 3.13 from python.org and tick Add python.exe to PATH.</p>
              </Notice>
            )}
          </div>
        ) : (
          <Routes>
            <Route path="/control" element={<TasksView />} />
            <Route path="/control/jobs/:id" element={<JobView />} />
            <Route path="/control/new-league" element={<NewLeagueWizard />} />
            <Route path="/control/setup" element={<SetupPanel />} />
            <Route path="*" element={<Navigate to="/control" replace />} />
          </Routes>
        )}
      </div>
    </div>
  );
}

