import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  useControlStatus, useCatalog, getDoctor, getSettings, patchSettings, resetLocalSettings, startJob,
  findTask, reloadPing, reloadCatalog, reprobePython,
} from '../../lib/controlApi';
import { checkToken } from '../../lib/inputConditions';
import { Notice, ConfirmDialog } from './PromptCard';
import TaskForm from './TaskForm';
import JobPanel, { StatusDot } from './JobPanel';

const fieldClass = 'ns-input w-full';
const card = 'ns-card space-y-3';
const btn = 'ns-btn ns-btn-sm';
const btnPrimary = 'ns-btn ns-btn-sm ns-btn-primary';

const RESET_TEXT = 'This renames settings.local.json to settings.local.bad-<time>.json and goes back to the default settings. '
  + 'No league data is touched. Leagues you added with New League keep their data and stay in the league menu, but their '
  + 'tasks disappear until you fix the file and rename it back.';
const PY_FIX = 'Install Python 3.13 from python.org and tick Add python.exe to PATH. Then close the Launch TGS window, '
  + 'start it again, and press Check again.';

/** argv shown as one line; a part with a space is quoted. */
function argvToText(argv) {
  return (Array.isArray(argv) ? argv : []).map(a => (/\s/.test(a) ? `"${a}"` : a)).join(' ');
}
/** One line back to argv: split on spaces, quotes keep a path with spaces together. */
function textToArgv(text) {
  const out = [];
  const re = /"([^"]*)"|(\S+)/g;
  let m;
  while ((m = re.exec(String(text || ''))) !== null) out.push(m[1] !== undefined ? m[1] : m[2]);
  return out;
}

const ORDER = { fail: 0, warn: 1, ok: 2, skip: 3 };

// doctor.py also prints to a console, where "on the Setup page" is right; here the user is on it.
const onThisPage = (text) => String(text).replace(/ on the Setup page/g, ' below');
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function PythonLine({ python }) {
  if (!python) return <p className="text-sm ns-text-2">Python: checking...</p>;
  if (python.ok) {
    const v = String(python.version || '').split(/\s/)[0];
    return <p className="text-sm ns-text">Python: {v || 'found'} <span className="ns-muted">({argvToText(python.argv)})</span></p>;
  }
  const known = python.code === 'ENOENT' || String(python.code) === '9009';
  return (
    <div className="text-sm space-y-0.5">
      <p className="ns-bad">Python does not start{python.argv ? ` (${argvToText(python.argv)})` : ''}.</p>
      {!known && python.message && <p className="text-xs ns-text-2">{python.message}</p>}
      <p className="ns-warn">{PY_FIX}</p>
    </div>
  );
}

function DoctorRows({ result, catalog, onRunTask }) {
  const rows = [...(result?.checks || [])].sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9));
  if (!rows.length) return <p className="text-xs ns-muted">No checks came back.</p>;
  return (
    <ul className="divide-y divide-[var(--line)]">
      {rows.map(r => {
        const task = r.task ? findTask(catalog, r.task) : null;
        const dot = r.status === 'fail' ? 'failed' : r.status === 'warn' ? 'partial' : r.status === 'ok' ? 'done' : 'skipped';
        return (
          <li key={r.id} className="py-2 flex items-start gap-3" data-check={r.id} data-check-status={r.status}>
            <span className="mt-1.5"><StatusDot status={dot} /></span>
            <div className="flex-1 min-w-0">
              <p className="text-sm ns-text">
                <span className="font-semibold">{r.title}</span>
                {r.detail && <span className="ns-text-2">: {r.detail}</span>}
              </p>
              {r.fix && r.status !== 'ok' && <p className="text-xs ns-warn mt-0.5">{onThisPage(r.fix)}</p>}
            </div>
            {task && r.status !== 'ok' && (
              <button onClick={() => onRunTask(task)} className={`${btnPrimary} shrink-0`}>
                {task.title}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// Form values from the merged settings.
function formFrom(merged) {
  const f = {
    'python.main': argvToText(merged?.python?.main),
    'python.ml': argvToText(merged?.python?.ml),
    node: argvToText(merged?.node),
  };
  for (const [ver, ins] of Object.entries(merged?.ootp?.installs || {})) f[`ootp.${ver}`] = ins?.saved_games || '';
  for (const [id, lg] of Object.entries(merged?.leagues || {})) {
    f[`lg.${id}.enabled`] = lg?.enabled !== false;
    for (const k of ['name', 'my_team', 'my_org', 'ootp_save', 'ootp_version']) f[`lg.${id}.${k}`] = lg?.[k] ?? '';
  }
  return f;
}

// The whitelisted patch (8.5) of the fields that changed.
function patchFrom(before, after) {
  const patch = {};
  const put = (path, v) => {
    let o = patch;
    for (let i = 0; i < path.length - 1; i++) { o[path[i]] = o[path[i]] || {}; o = o[path[i]]; }
    o[path[path.length - 1]] = v;
  };
  for (const [k, v] of Object.entries(after)) {
    if (before[k] === v) continue;
    if (k === 'python.main' || k === 'python.ml') put(['python', k.split('.')[1]], textToArgv(v));
    else if (k === 'node') put(['node'], textToArgv(v));
    else if (k.startsWith('ootp.')) put(['ootp', 'installs', k.slice(5), 'saved_games'], String(v).trim());
    else if (k.startsWith('lg.')) {
      const [, id, field] = k.split('.');
      put(['leagues', id, field], field === 'enabled' ? !!v : String(v).trim());
    }
  }
  return patch;
}

function SettingsForm({ onSaved, catalog, onRunTask }) {
  const [data, setData] = useState(null);
  const [loadErr, setLoadErr] = useState(null);
  const [form, setForm] = useState({});
  const [base, setBase] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [parkHint, setParkHint] = useState(false);

  const load = useCallback(() => {
    setLoadErr(null);
    getSettings().then(d => {
      setData(d);
      const f = formFrom(d?.merged);
      setForm(f);
      setBase(f);
    }).catch(e => setLoadErr(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loadErr) return <p className="text-xs ns-bad">The settings did not load: {loadErr}</p>;
  if (!data) return <p className="text-xs ns-muted flex items-center gap-1.5">Loading the settings...</p>;

  const set = (k, v) => { setForm(prev => ({ ...prev, [k]: v })); setFieldErr(prev => ({ ...prev, [k]: undefined })); setMsg(null); };
  const leagues = Object.keys(data.merged?.leagues || {});
  const versions = Object.keys(data.merged?.ootp?.installs || {});
  const patch = patchFrom(base, form);
  const changed = Object.keys(patch).length > 0;

  const save = async () => {
    setBusy(true);
    setMsg(null);
    setFieldErr({});
    try {
      await patchSettings(patch);
      const teamChanged = leagues.some(id => base[`lg.${id}.my_team`] !== form[`lg.${id}.my_team`]);
      setParkHint(teamChanged);
      setMsg({ tone: 'ok', text: 'Saved.' });
      reloadPing();
      load();
      onSaved?.();
    } catch (e) {
      const body = e.body || {};
      if (e.code === 'bad_interpreter') {
        const argv = argvToText(body.argv);
        const key = ['python.main', 'python.ml', 'node'].find(k => argvToText(textToArgv(form[k])) === argv) || 'python.main';
        setFieldErr({ [key]: `This command did not work. Nothing was saved.${body.output ? `\n${body.output}` : ''}` });
        setMsg({ tone: 'error', text: 'Nothing was saved.' });
      } else if (e.code === 'busy') {
        setMsg({ tone: 'error', text: 'A task is running. Save the settings after it finishes.' });
      } else if (Array.isArray(body.errors)) {
        setMsg({ tone: 'error', text: body.errors.join(' ') });
      } else {
        setMsg({ tone: 'error', text: e.message });
      }
    } finally {
      setBusy(false);
    }
  };

  const input = (k, label, hint) => (
    <div className="space-y-1" data-setting={k}>
      <label htmlFor={`set-${k}`} className="block ns-label">{label}</label>
      <input id={`set-${k}`} value={form[k] ?? ''} onChange={(e) => set(k, e.target.value)} className={fieldClass} spellCheck={false} autoComplete="off" />
      {hint && <p className="text-[11px] ns-muted">{hint}</p>}
      {fieldErr[k] && <pre className="text-[11px] ns-bad whitespace-pre-wrap">{fieldErr[k]}</pre>}
    </div>
  );

  return (
    <div className="space-y-4">
      {data.python_failed && (
        <p className="text-xs ns-warn">Python does not start, so only the commands show here. Fix Python (main), then save.</p>
      )}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {input('python.main', 'Python (main)', 'For example: python, or py -3')}
        {input('python.ml', 'Python (ML)', 'For example: py -3.14')}
        {input('node', 'Node.js', 'For example: node')}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {versions.map(v => <React.Fragment key={v}>{input(`ootp.${v}`, `OOTP ${v} saved games folder`, '%USERPROFILE% and ~ work here.')}</React.Fragment>)}
      </div>
      <div className={`space-y-2 ${leagues.length ? '' : 'hidden'}`}>
        <p className="ns-subhead">Leagues</p>
        {leagues.map(id => (
          <div key={id} className="ns-box ns-box-body space-y-2" data-league={id}>
            <label className="flex items-center gap-2 text-sm ns-text">
              <input type="checkbox" checked={form[`lg.${id}.enabled`] !== false} onChange={(e) => set(`lg.${id}.enabled`, e.target.checked)} className="accent-[var(--accent)]" />
              <span className="font-semibold">{id}</span>
              <span className="text-xs ns-muted">{form[`lg.${id}.enabled`] === false ? 'off: its tasks are hidden, its data stays' : 'on'}</span>
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {input(`lg.${id}.name`, 'Name')}
              {input(`lg.${id}.my_team`, 'My team (park home)')}
              {input(`lg.${id}.my_org`, 'My org (where Org Builder opens)')}
              {input(`lg.${id}.ootp_save`, 'OOTP save')}
              {input(`lg.${id}.ootp_version`, 'OOTP version')}
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button onClick={save} disabled={!changed || busy} className={btnPrimary}>
          Save settings
        </button>
        {!changed && !msg && <span className="text-xs ns-muted">No changes.</span>}
        {msg && <span className={`text-xs ${msg.tone === 'ok' ? 'ns-good' : 'ns-bad'}`}>{msg.text}</span>}
      </div>
      {parkHint && (
        <div className="flex items-center gap-3">
          <p className="text-xs ns-warn">Run Update park factors to apply this.</p>
          {findTask(catalog, 'parks_update') && (
            <button onClick={() => onRunTask(findTask(catalog, 'parks_update'))} className={btnPrimary}>
              {findTask(catalog, 'parks_update').title}
            </button>
          )}
        </div>
      )}
      {data.paths?.local && <p className="text-[11px] ns-muted">Your changes go to {data.paths.local}.</p>}
    </div>
  );
}

function TokenForm({ catalog, pythonBad }) {
  const task = findTask(catalog, 'token_set');
  const leagueInput = (task?.inputs || []).find(i => i.name === 'league');
  const choices = leagueInput?.choices?.length
    ? leagueInput.choices
    : (catalog?.leagues || []).filter(l => l.type === 'statsplus' && l.enabled !== false && !l.pending).map(l => ({ value: l.id, label: l.name || l.id }));
  const [league, setLeague] = useState('');
  const [token, setToken] = useState('');
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState(null);
  useEffect(() => { if (!league && choices.length) setLeague(String(choices[0].value)); }, [choices.length]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!task) {
    return <p className="text-xs ns-muted">{pythonBad ? 'Needs Python. Fix Python above first.' : 'This task is not in the task list.'}</p>;
  }
  const line = (catalog?.leagues || []).find(l => l.id === league)?.token_line;

  const submit = async (e) => {
    e.preventDefault();
    const problem = checkToken(token, true);
    if (problem) { setErr(problem); return; }
    setBusy(true);
    setErr(null);
    try {
      const job = await startJob('token_set', { league }, { token: token.trim() });
      setToken('');
      if (job?.id) setJobId(job.id);
    } catch (ex) {
      setToken('');
      setErr(ex.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3" autoComplete="off">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label htmlFor="token-league" className="block ns-label">League</label>
          <select id="token-league" value={league} onChange={(e) => setLeague(e.target.value)} className={fieldClass}>
            {choices.map(c => <option key={c.value} value={c.value}>{c.label ?? c.value}</option>)}
          </select>
          {line && <p className="text-[11px] ns-muted">It writes the line {line} in StatsPlus Tokens.txt.</p>}
        </div>
        <div className="space-y-1">
          <label htmlFor="token-value" className="block ns-label">New token</label>
          <input id="token-value" type="password" value={token} onChange={(e) => { setToken(e.target.value); setErr(null); }}
            className={fieldClass} autoComplete="new-password" spellCheck={false} />
          <p className="text-[11px] ns-muted">From statsplus.net, your league, Prefs. Tokens expire every 90 days.</p>
        </div>
      </div>
      {err && <p className="text-xs ns-bad" role="alert">{err}</p>}
      <button type="submit" disabled={busy || !league} className={btnPrimary}>
        Save the token
      </button>
      {jobId && <JobPanel jobId={jobId} compact onDismiss={() => setJobId(null)} />}
    </form>
  );
}

/**
 * Setup (DESIGN 10.5): the Python line, the setup check rows, the settings
 * form, Reset local settings and Replace a StatsPlus token.
 */
export default function SetupPanel() {
  const navigate = useNavigate();
  const status = useControlStatus();
  const { catalog } = useCatalog();
  const [doctor, setDoctor] = useState(null);
  const [doctorErr, setDoctorErr] = useState(null);
  const [checking, setChecking] = useState(false);
  const [formTask, setFormTask] = useState(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetMsg, setResetMsg] = useState(null);
  const [settingsKey, setSettingsKey] = useState(0);

  const runCheck = useCallback(async (again = false) => {
    setChecking(true);
    setDoctorErr(null);
    if (again === true) {
      // Probe Python again: a fixed Python then shows at once, with the task list and the settings form.
      const ping = await reprobePython();
      if (ping?.python?.ok) reloadCatalog(true);
      setSettingsKey(k => k + 1);
    } else {
      reloadPing();
    }
    try {
      setDoctor(await getDoctor());
    } catch (e) {
      setDoctor(null);   // rows from an earlier check would read as this one's
      setDoctorErr(e.code === 'timeout' ? { text: 'The check took longer than a minute and stopped.' } : { text: e.message, code: e.code });
    } finally {
      setChecking(false);
    }
  }, []);
  useEffect(() => { runCheck(); }, [runCheck]);

  const settingsError = catalog?.state?.settings_error || null;
  const pythonBad = status.python?.ok === false;
  const showReset = !!(catalog?.state?.settings_local || settingsError);
  const counts = useMemo(() => {
    const c = { fail: 0, warn: 0 };
    for (const r of doctor?.checks || []) if (r.status in c) c[r.status] += 1;
    return c;
  }, [doctor]);

  const doReset = async () => {
    setConfirmReset(false);
    setResetMsg(null);
    try {
      const r = await resetLocalSettings();
      setResetMsg({ tone: 'ok', text: `Done. The old file is now ${r?.renamed_to || 'renamed'}.` });
      reloadCatalog(true);
      setSettingsKey(k => k + 1);
      runCheck();
    } catch (e) {
      setResetMsg({ tone: 'error', text: e.code === 'busy' ? 'A task is running. Reset after it finishes.' : e.code === 'no_local_file' ? 'There is no settings.local.json to reset.' : e.message });
    }
  };

  return (
    <div className="space-y-4">
      {settingsError && (
        <Notice tone="error" title="The settings file has a problem">
          <p>{settingsError}</p>
          <p>Fix the file, or press Reset local settings below.</p>
        </Notice>
      )}

      <div className={card}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="ns-strip">Setup check</h2>
          <button onClick={() => runCheck(true)} disabled={checking} className={btn}>
            {checking ? 'Checking...' : 'Check again'}
          </button>
        </div>
        <PythonLine python={status.python} />
        {doctorErr && (
          <p className="text-xs ns-bad">
            {/* the Python line above already gives the install advice: say it once */}
            {pythonBad && doctorErr.code === 'python_failed' ? 'The setup check needs Python. Fix Python first.' : doctorErr.text}
          </p>
        )}
        {checking && !doctor && <p className="text-xs ns-muted">Checking. This takes up to 20 seconds.</p>}
        {doctor && (
          <>
            <p className="text-xs ns-text-2">
              {counts.fail === 0 && counts.warn === 0 ? 'Everything checks out.'
                : `${plural(counts.fail, 'problem', 'problems')}, ${plural(counts.warn, 'warning', 'warnings')}.`}
            </p>
            <DoctorRows result={doctor} catalog={catalog} onRunTask={setFormTask} />
          </>
        )}
      </div>

      {!settingsError && (
        <div className={card}>
          <h2 className="ns-strip">Settings</h2>
          <SettingsForm key={settingsKey} onSaved={runCheck} catalog={catalog} onRunTask={setFormTask} />
        </div>
      )}

      {showReset && (
        <div className={card}>
          <h2 className="ns-strip">Reset local settings</h2>
          <p className="text-xs ns-text-2">Goes back to the default settings. Your league data stays.</p>
          <button onClick={() => setConfirmReset(true)} className={btn}>
            Reset local settings
          </button>
        </div>
      )}
      {resetMsg && (
        <Notice tone={resetMsg.tone === 'ok' ? 'ok' : 'error'} title="Reset local settings">
          <p>{resetMsg.text}</p>
        </Notice>
      )}

      {!settingsError && (
        <div className={card}>
          <h2 className="ns-strip">Replace a StatsPlus token</h2>
          <TokenForm catalog={catalog} pythonBad={pythonBad} />
        </div>
      )}

      {confirmReset && (
        <ConfirmDialog title="Reset local settings?" text={RESET_TEXT} confirmLabel="Reset" danger
          onCancel={() => setConfirmReset(false)} onConfirm={doReset} />
      )}
      {formTask && <TaskForm task={formTask} onClose={() => setFormTask(null)} onStarted={(job) => { setFormTask(null); if (job?.id) navigate(`/control/jobs/${encodeURIComponent(job.id)}`); }} />}
    </div>
  );
}
