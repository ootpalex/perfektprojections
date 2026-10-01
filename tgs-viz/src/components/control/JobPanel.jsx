import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CircleStop, Skull, X, Hand, Wrench, ExternalLink, ChevronDown, ChevronRight, SquareTerminal } from 'lucide-react';
import {
  useJobStream, useJobInfo, useCatalog, useServerLost, answer, stop, startJob, findTask, isFinalStatus, isActiveStatus,
} from '../../lib/controlApi';
import JobLog from './JobLog';
import PromptCard, { ConfirmDialog } from './PromptCard';
import TaskForm from './TaskForm';

const WORDS = {
  starting: 'Starting', queued: 'Waiting for its turn', running: 'Running', waiting: 'Needs your answer',
  done: 'Finished', partial: 'Finished with problems', failed: 'Failed', stopped: 'Stopped',
  killed: 'Killed', lost: 'Lost', did_not_start: 'Did not start', invalid: 'Could not start', refused: 'Refused',
};
/** The status in the user's words (10.3). */
export function statusWord(status) {
  return WORDS[status] || (status ? String(status) : 'Unknown');
}

const DOT = {
  running: 'bg-blue-400 animate-pulse', starting: 'bg-blue-400 animate-pulse', waiting: 'bg-amber-400 animate-pulse',
  queued: 'bg-slate-500', done: 'bg-green-400', ok: 'bg-green-400', partial: 'bg-amber-400', ignored_fail: 'bg-amber-400',
  failed: 'bg-red-400', killed: 'bg-red-400', invalid: 'bg-red-400', refused: 'bg-red-400', did_not_start: 'bg-red-400',
  lost: 'bg-red-400', stopped: 'bg-orange-400', skipped: 'bg-slate-700', pending: 'bg-slate-600',
};
export function StatusDot({ status }) {
  return <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${DOT[status] || 'bg-slate-600'}`} title={statusWord(status)} />;
}

const STEP_WORDS = {
  pending: 'waiting', running: 'running', ok: 'done', failed: 'failed', ignored_fail: 'failed (ignored)',
  skipped: 'skipped', killed: 'killed', stopped: 'stopped',
};

/** "21:04" today, else "Sep 30 21:04". */
export function formatWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return hm;
  return `${d.toLocaleString(undefined, { month: 'short', day: 'numeric' })} ${hm}`;
}

function formatElapsed(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${String(s % 60).padStart(2, '0')} s`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}

function useNow(active) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const STOP_TEXT = { after_step: 'after this step', after_cycle: 'after this cycle', kill: 'now (kill)' };
const KILL_TEXT = 'Kill now ends the current step at once. A few steps write their files in place, so a killed step can '
  + 'leave one half-written file (its .bak copy stays). If the step drives OOTP, the app releases the keys and the mouse, '
  + 'but OOTP keeps simming: stop it inside OOTP.';

const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg disabled:opacity-40';

/**
 * One job: status, elapsed time, current step, steps, live log, the open
 * question, the stop buttons and, at the end, the summary (10.3).
 * compact: the panel on the task list (steps folded, a link to the full page).
 */
export default function JobPanel({ jobId, compact = false, onDismiss }) {
  const navigate = useNavigate();
  const info = useJobInfo(jobId);
  const stream = useJobStream(jobId);
  const { catalog } = useCatalog();
  const [confirmKill, setConfirmKill] = useState(false);
  const [stepsOpen, setStepsOpen] = useState(!compact);
  const [actionError, setActionError] = useState(null);
  const [pending, setPending] = useState(null);
  const [formTask, setFormTask] = useState(null);
  const [cleanupMsg, setCleanupMsg] = useState(null);

  const st = useMemo(() => ({ ...(info || {}), ...(stream?.state || {}) }), [info, stream?.state, stream?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const status = stream?.done?.status || st.status || 'starting';
  const active = isActiveStatus(status);
  const final = isFinalStatus(status);
  const lost = useServerLost();
  // While contact is lost, the page knows nothing new: the elapsed time stops too.
  const now = useNow(active && !lost);
  const task = findTask(catalog, st.task);
  const title = st.title || task?.title || st.task || jobId;

  const steps = Array.isArray(st.steps) ? st.steps : [];
  let stepLine = null;
  if (active && steps.length && Number.isInteger(st.current) && steps[st.current]) {
    stepLine = `${st.current + 1} of ${steps.length}: ${steps[st.current].title || steps[st.current].id}`;
  } else if (active && st.step && st.step.title) {
    stepLine = `${(st.step.index ?? 0) + 1} of ${st.step.total ?? '?'}: ${st.step.title}`;
  }
  const cycle = st.cycle ? ` (cycle ${st.cycle})` : '';

  const started = st.started ? Date.parse(st.started) : NaN;
  const ended = st.ended ? Date.parse(st.ended) : NaN;
  // A job that never ran a step was only asked for: no "Started", and no 0 s.
  const neverRan = ['invalid', 'did_not_start', 'refused'].includes(status);
  const askedOnly = neverRan || status === 'queued';
  const elapsed = Number.isFinite(started) && !neverRan ? formatElapsed((Number.isFinite(ended) ? ended : now) - started) : '';
  const when = st.started || st.requested_at;

  const countdown = stream?.countdown && now - stream.countdown.at < 1500 && active ? stream.countdown.text : null;
  const prompt = status === 'waiting' ? (stream?.prompt || (st.prompt && typeof st.prompt === 'object' ? st.prompt : null)) : null;
  const modes = task?.stop_modes || (task?.flags?.endless ? ['after_cycle', 'after_step', 'kill'] : ['after_step', 'kill']);
  const stopAsked = st.stop || null;
  const consoleJob = st.mode === 'console';
  const allSummary = Array.isArray(stream?.done?.summary) ? stream.done.summary : (Array.isArray(st.summary) ? st.summary : []);
  // The message already shows above the summary: never twice.
  const summary = allSummary.filter(l => !st.message || String(l).trim() !== String(st.message).trim());
  // Run_task's own notes while the job runs; the wait notes repeat what the panel already says.
  const messages = active && status !== 'queued'
    ? (stream?.messages || []).filter(m => !/^\s*Waiting for /.test(m.text || ''))
    : [];
  const hasOutput = !!(stream?.lines?.length || stream?.partial?.text);
  const fails = Array.isArray(stream?.done?.fails) ? stream.done.fails : (Array.isArray(st.fails) ? st.fails : []);
  const fixTask = st.fix_task ? findTask(catalog, st.fix_task) : null;
  // After its register step the league exists: Remove takes it out, never the clean-up (12.6).
  const registered = steps.some(s => s && s.id === 'register' && s.status === 'ok');
  const newLeagueLeftover = st.task === 'new_league' && (status === 'lost' || status === 'failed') && !registered;

  const doStop = async (mode) => {
    setActionError(null);
    setPending(mode);
    try { await stop(jobId, mode); } catch (e) { setActionError(e.message); setPending(null); }
  };
  useEffect(() => { if (final) setPending(null); }, [final]);

  const cleanup = async () => {
    setCleanupMsg(null);
    try {
      const job = await startJob('new_league_cleanup', { job_id: jobId }, {});
      setCleanupMsg(job?.id ? `Clean-up started.` : 'Clean-up asked.');
    } catch (e) {
      setCleanupMsg(e.message);
    }
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-3" data-job={jobId} data-status={status}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <StatusDot status={status} />
            <h3 className="text-sm font-bold text-white truncate">{title}</h3>
            <span className="text-xs text-slate-400" data-role="status-word">{statusWord(status)}</span>
          </div>
          <p className="text-[11px] text-slate-500 mt-0.5">
            {when ? `${askedOnly ? 'Asked at' : 'Started'} ${formatWhen(when)}` : ''}{elapsed ? ` · ${elapsed}` : ''}
            {stepLine ? ` · Step ${stepLine}${cycle}` : ''}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {compact && (
            <Link to={`/control/jobs/${encodeURIComponent(jobId)}`} className="text-slate-500 hover:text-slate-200" title="Open this job on its own page">
              <ExternalLink size={14} />
            </Link>
          )}
          {onDismiss && final && (
            <button onClick={onDismiss} className="text-slate-500 hover:text-slate-200" title="Hide this panel" aria-label="Hide this panel">
              <X size={16} />
            </button>
          )}
        </div>
      </div>

      {lost && active && (
        <p className="text-xs text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded-lg px-3 py-2" role="status">
          Lost contact with the app server. The task keeps running. Start Launch TGS again to follow it.
        </p>
      )}

      {countdown && (
        <p className="text-2xl font-black text-amber-300 flex items-center gap-2" role="status">
          <Hand size={24} /> {countdown}
        </p>
      )}

      {status === 'queued' && (
        <div className="flex items-center justify-between gap-3 text-sm text-slate-300 bg-slate-800/50 border border-slate-700 rounded-lg px-3 py-2">
          <span>{st.waiting_for?.title ? `Waiting for ${st.waiting_for.title} to finish.` : 'Waiting for another task to finish.'}</span>
          <button onClick={() => doStop('after_step')} disabled={!!pending} className={`${btn} bg-slate-700 text-slate-100 hover:bg-slate-600`}>
            Cancel
          </button>
        </div>
      )}
      {status === 'running' && st.waiting_for?.title && (
        <p className="text-xs text-slate-400">Waiting for {st.waiting_for.title} to finish before the next step.</p>
      )}

      {consoleJob && active && <p className="text-xs text-slate-400 flex items-center gap-1.5"><SquareTerminal size={14} /> Running in a console window.</p>}

      {prompt && <PromptCard prompt={prompt} onAnswer={(v) => answer(jobId, prompt.prompt_id, v)} />}

      {active && status !== 'queued' && (
        <div className="flex flex-wrap items-center gap-2">
          {modes.includes('after_cycle') && (
            <button onClick={() => doStop('after_cycle')} disabled={!!pending || !!stopAsked}
              className={`${btn} bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700`}>
              <CircleStop size={12} /> Stop after this cycle
            </button>
          )}
          {modes.includes('after_step') && (
            <button onClick={() => doStop('after_step')} disabled={!!pending || !!stopAsked}
              className={`${btn} bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700`}>
              <CircleStop size={12} /> Stop after this step
            </button>
          )}
          {modes.includes('kill') && (
            <button onClick={() => setConfirmKill(true)} disabled={pending === 'kill'}
              className={`${btn} bg-red-900/60 text-red-200 hover:bg-red-800 border border-red-800`}>
              <Skull size={12} /> Kill now
            </button>
          )}
          {(info?.stale || st.stale) && <span className="text-xs text-amber-400">This task is not responding.</span>}
          {(stopAsked || pending) && (
            <span className="text-xs text-slate-400">Stop asked: {STOP_TEXT[(stopAsked && (stopAsked.mode || stopAsked)) || pending] || 'yes'}.</span>
          )}
        </div>
      )}
      {actionError && <p className="text-xs text-red-400">{actionError}</p>}

      {final && (
        <div className="space-y-2">
          {st.message && <p className={`text-sm ${status === 'invalid' || status === 'failed' ? 'text-red-300' : 'text-slate-300'}`}>{st.message}</p>}
          {fixTask && (
            <button onClick={() => setFormTask(fixTask)} className={`${btn} bg-blue-600 text-white hover:bg-blue-500`}>
              <Wrench size={12} /> {fixTask.title}
            </button>
          )}
          {summary.length > 0 && (
            <div className="text-xs text-slate-300 bg-slate-800/40 border border-slate-800 rounded-lg px-3 py-2 space-y-0.5">
              {summary.map((l, i) => <p key={i} className="whitespace-pre-wrap">{l}</p>)}
            </div>
          )}
          {!summary.length && fails.length > 0 && (
            <p className="text-xs text-amber-300">Steps that did not update: {fails.join(', ')}</p>
          )}
          {newLeagueLeftover && (
            <div className="flex items-center gap-2">
              <button onClick={cleanup} className={`${btn} bg-slate-800 text-slate-100 hover:bg-slate-700 border border-slate-700`}>
                <Wrench size={12} /> Clean up unfinished league
              </button>
              {cleanupMsg && <span className="text-xs text-slate-400">{cleanupMsg}</span>}
            </div>
          )}
        </div>
      )}

      {steps.length > 0 && (
        <div>
          <button onClick={() => setStepsOpen(o => !o)} className="flex items-center gap-1 text-[11px] font-semibold text-slate-400 uppercase tracking-wide">
            {stepsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Steps ({steps.length})
          </button>
          {stepsOpen && (
            <ol className="mt-1.5 space-y-1">
              {steps.map((s, i) => (
                <li key={`${s.index ?? i}-${s.id}`} className="flex items-center gap-2 text-xs" data-step={s.id} data-step-status={s.status}>
                  <StatusDot status={s.status} />
                  <span className={s.status === 'running' ? 'text-white font-semibold' : 'text-slate-300'}>{s.title || s.id}</span>
                  <span className="text-slate-500">{STEP_WORDS[s.status] || s.status}</span>
                  {Number.isFinite(s.exit) && s.exit !== 0 && <span className="text-slate-600">exit {s.exit}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}

      {messages.length > 0 && (
        <ul className="text-xs space-y-0.5">
          {messages.slice(-5).map((m, i) => (
            <li key={i} className={m.level === 'warn' ? 'text-amber-300' : 'text-slate-400'}>{m.text}</li>
          ))}
        </ul>
      )}

      {/* A queued job's log holds only the wait line the box above already shows. */}
      {!consoleJob && status !== 'queued' && !(final && !hasOutput) && (
        <JobLog lines={stream?.lines} partial={stream?.partial?.text} dropped={stream?.dropped || 0}
          version={stream?.version} tall={!compact} empty={active ? 'Waiting for output...' : 'No output.'} />
      )}
      {stream?.error && <p className="text-xs text-amber-400">{stream.error}</p>}

      {confirmKill && (
        <ConfirmDialog title="Kill this task now?" text={KILL_TEXT} confirmLabel="Kill now" danger
          onCancel={() => setConfirmKill(false)}
          onConfirm={() => { setConfirmKill(false); doStop('kill'); }} />
      )}
      {formTask && <TaskForm task={formTask} onClose={() => setFormTask(null)} onStarted={(job) => { setFormTask(null); if (job?.id) navigate(`/control/jobs/${encodeURIComponent(job.id)}`); }} />}
    </div>
  );
}
