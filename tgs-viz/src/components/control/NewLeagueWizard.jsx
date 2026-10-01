import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Globe, HardDrive, FlaskConical, Copy, ArrowLeft, Loader2, Play, ListChecks } from 'lucide-react';
import { newLeagueOptions, validateNewLeague, startJob, useJobInfo, useActiveJobs, useCatalog, findTask, startConflict } from '../../lib/controlApi';
import { checkToken, checkSecret, conflictText } from '../../lib/inputConditions';
import JobPanel from './JobPanel';
import TaskForm from './TaskForm';
import { Notice } from './PromptCard';

const TYPES = [
  {
    id: 'statsplus', icon: Globe, title: 'Online league on StatsPlus',
    text: "Pulls ratings from statsplus.net with your league's token. Prices players with TGS's or BLM's calibration.",
  },
  { id: 'local_export', icon: HardDrive, title: 'Local OOTP save', text: "Reads a save's database CSV export, like Regular Game." },
  {
    id: 'dev', icon: FlaskConical, title: 'DEV research league',
    text: 'An all-AI OOTP league you sim in place. Adds a Rating Trends page from its yearly dumps.',
  },
  {
    id: 'clone', icon: Copy, title: 'Calibration clone league',
    text: 'Makes and sims clone leagues from a pristine master save. No app league. Turning the clones into a calibration '
      + 'is an advanced manual job (see STATUS.md and engine/calibrate.py).',
  },
];

// Known limits the wizard states (DESIGN 12.3).
const LIMITS = {
  statsplus: [
    'My Park equals Neutral: there are no park factors for this league.',
    'The Series Planner says its file is missing.',
    "Draft boards need the OOTP draft-pool export in the save's import_export folder.",
    'Dev signals treat the league like an exported league (the out-of-org rule covers TGS and BLM only).',
    'Get StatsPlus History works only when a history start date is given.',
  ],
  local_export: [
    'The save needs its database CSV export (import_export/csv/players.csv).',
  ],
  dev: [
    'The measured age curve and the ML models still come from DEV.',
    'A second dev league adds its own Rating Trends page.',
  ],
  clone: [
    'No app league is added.',
    'Calibration from the clones is a manual job.',
  ],
};

// Field labels for the review's error list (the server names fields by key).
const LABELS = {
  type: 'League type', id: 'League id', name: 'Name', my_org: 'Your org', slug: 'StatsPlus name', basis: 'Calibration',
  token: 'StatsPlus token', sessionid: 'Browser cookie: sessionid', csrftoken: 'Browser cookie: csrftoken',
  ootp_version: 'OOTP version', ootp_save: 'OOTP save', history_first_date: 'History start date',
  foreign_league_ids: 'StatsPlus league ids to leave out', dump_dir: 'Dump folder', years: 'Years per sim',
  resume_after: 'Resume after', nostart_abort: 'Give up after', master: 'Master save', prefix: 'Clone name prefix',
  start_year: 'Start year', target_year: 'Target year', runs: 'Runs', settings: 'Settings',
};
const NEEDS_CREDENTIALS = 'No token is saved for this league yet. Give the token, or both browser cookies.';

const fieldClass = 'w-full bg-slate-800 text-white text-sm rounded-lg px-3 py-2 border border-slate-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500';

function defaultsFor(type) {
  const base = { id: '', name: '', my_org: '' };
  if (type === 'statsplus') return { ...base, slug: '', basis: 'TGS', ootp_version: '', ootp_save: '', history_first_date: '', foreign_league_ids: '' };
  if (type === 'local_export') return { ...base, ootp_version: '', ootp_save: '', basis: '' };
  if (type === 'dev') return { ...base, ootp_version: '', ootp_save: '', dump_dir: '', years: '5', resume_after: '600', nostart_abort: '1800' };
  if (type === 'clone') return { ...base, ootp_version: '', master: '', prefix: '', start_year: '2016', target_year: '2026', runs: '10' };
  return base;
}

const INT_FIELDS = ['years', 'resume_after', 'nostart_abort', 'start_year', 'target_year', 'runs'];

// A save entry from `options`: a name (marked from the clones, protected and
// in_use lists of the answer), or an object with flags.
function saveEntry(s, o = {}) {
  if (typeof s === 'string') {
    const notes = [];
    if ((o.clones || []).includes(s)) notes.push('clone');
    if (o.in_use && o.in_use[s]) notes.push(`used by ${o.in_use[s]}`);
    else if ((o.protected || []).includes(s)) notes.push('protected');
    return { name: s, note: notes.join(', ') };
  }
  const name = s?.name ?? s?.save ?? s?.value ?? '';
  const notes = [];
  if (s?.clone) notes.push('clone');
  if (s?.protected) notes.push('used by a league');
  if (s?.note) notes.push(String(s.note));
  return { name: String(name), note: notes.join(', ') };
}

function Field({ label, hint, error, children, name }) {
  return (
    <div className="space-y-1" data-field={name}>
      <label htmlFor={`nl-${name}`} className="block text-xs font-semibold text-slate-300">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
      {error && <p className="text-[11px] text-red-400" role="alert">{error}</p>}
    </div>
  );
}

/**
 * The browser-side checks before Review (10.4): blanks, shapes and the token.
 * The id rules (pattern, device names, ids used before) are the server's
 * check, so its message shows next to the field.
 */
function localErrors(type, f, sec) {
  const e = {};
  if (!f.id.trim()) e.id = 'Type an id.';
  const name = f.name.trim();
  if (!name || name.length > 40) e.name = 'Type a name of 1 to 40 characters.';
  if (type === 'statsplus') {
    if (f.slug.trim() && !/^[a-z0-9_-]{1,40}$/.test(f.slug.trim())) e.slug = 'Use small letters, digits, - or _ (up to 40).';
    const t = checkToken(sec.token);
    if (t) e.token = t;
    if (!sec.token?.trim()) {
      const a = checkSecret(sec.sessionid);
      const b = checkSecret(sec.csrftoken);
      if (a) e.sessionid = a;
      if (b) e.csrftoken = b;
      // the first pull sends the cookie pair together, so one alone is no use
      if (!a && !b && !!sec.sessionid?.trim() !== !!sec.csrftoken?.trim()) {
        e[sec.sessionid?.trim() ? 'csrftoken' : 'sessionid'] = 'Give both cookies, or neither.';
      }
    }
    if (f.history_first_date.trim() && !/^\d{4}-\d{2}-\d{2}$/.test(f.history_first_date.trim())) e.history_first_date = 'Use the form YYYY-MM-DD.';
    if (f.ootp_save && !f.ootp_version) e.ootp_version = 'Pick the OOTP version of that save.';
  }
  if (type === 'local_export' || type === 'dev') {
    if (!f.ootp_version) e.ootp_version = 'Pick an OOTP version.';
    if (!f.ootp_save) e.ootp_save = 'Pick a save.';
  }
  if (type === 'clone') {
    if (!f.ootp_version) e.ootp_version = 'Pick an OOTP version.';
    if (!f.master) e.master = 'Pick the master save.';
    if (f.prefix.trim() && !/^[0-9a-z_-]{2,12}$/.test(f.prefix.trim())) e.prefix = 'Use 2 to 12 small letters, digits, - or _.';
  }
  for (const k of INT_FIELDS) {
    if (k in f && String(f[k]).trim() && !/^\d+$/.test(String(f[k]).trim())) e[k] = 'Type a whole number.';
  }
  return e;
}

/** The fields as the backend gets them: blanks left out, whole numbers as numbers. */
function payload(type, f) {
  const out = {};
  for (const [k, v] of Object.entries(f)) {
    const s = String(v ?? '').trim();
    if (!s) continue;
    out[k] = INT_FIELDS.includes(k) && /^\d+$/.test(s) ? parseInt(s, 10) : s;
  }
  if (type === 'statsplus' && !out.slug && out.id) out.slug = out.id.toLowerCase();
  if (type === 'clone' && !out.prefix && out.id) out.prefix = `0${out.id.toLowerCase()}`;
  if (type === 'local_export' && !out.basis) out.basis = out.ootp_version === '26' ? 'TGS' : 'BLM';
  return out;
}

function Running({ jobId }) {
  const info = useJobInfo(jobId);
  const status = info?.status;
  return (
    <div className="space-y-3">
      {(status === 'done' || status === 'partial') && (
        <Notice tone="ok" title="League added">
          <p>League added. Pick it in the league menu.</p>
          {status === 'partial' && <p>Some later steps did not finish. The job below says which.</p>}
        </Notice>
      )}
      {(status === 'failed' || status === 'stopped' || status === 'killed') && (
        <Notice tone="warn" title="The league was not added">
          <p>The job below says what the rollback undid. Nothing that existed before was changed.</p>
        </Notice>
      )}
      <JobPanel jobId={jobId} />
    </div>
  );
}

/**
 * New League (DESIGN 10.4): pick a type, fill its fields (save names and
 * versions come from the server; a save name cannot be typed), review the
 * server's checks and the step plan, then start the new_league task.
 */
export default function NewLeagueWizard() {
  const { catalog } = useCatalog();
  const active = useActiveJobs();
  const [type, setType] = useState(null);
  const [f, setF] = useState({});
  const [sec, setSec] = useState({ token: '', sessionid: '', csrftoken: '' });
  const [opts, setOpts] = useState(null);       // { versions, bases }
  const [saves, setSaves] = useState(null);     // [{name, note}]
  const [optsError, setOptsError] = useState(null);
  const [errors, setErrors] = useState({});
  const [review, setReview] = useState(null);   // { ok, errors, warnings, plan }
  const [busy, setBusy] = useState(false);
  const [startError, setStartError] = useState(null);
  const [startFix, setStartFix] = useState(null);   // fix_task of a refused start (the archive check)
  const [fixForm, setFixForm] = useState(null);
  const [fixJob, setFixJob] = useState(null);
  const [jobId, setJobId] = useState(null);

  const set = (k, v) => { setF(prev => ({ ...prev, [k]: v })); setErrors(prev => ({ ...prev, [k]: undefined })); setReview(null); };
  const setS = (k, v) => { setSec(prev => ({ ...prev, [k]: v })); setErrors(prev => ({ ...prev, [k]: undefined })); setReview(null); };

  const pickType = (t) => {
    setType(t);
    setF(defaultsFor(t));
    setSec({ token: '', sessionid: '', csrftoken: '' });
    setErrors({});
    setReview(null);
    setOpts(null);
    setSaves(null);
    setOptsError(null);
    setStartError(null);
    setStartFix(null);
  };

  // Versions and bases for the type.
  useEffect(() => {
    if (!type) return undefined;
    let on = true;
    newLeagueOptions(type).then(o => {
      if (!on) return;
      setOpts(o || {});
      const versions = (o?.versions || []).filter(v => v.exists !== false);
      if (type !== 'statsplus' && versions.length) {
        setF(prev => (prev.ootp_version ? prev : { ...prev, ootp_version: String((versions.find(v => String(v.version) === '27') || versions[0]).version) }));
      }
    }).catch(e => { if (on) setOptsError(e.message); });
    return () => { on = false; };
  }, [type]);

  // Saves for the picked version.
  const version = f.ootp_version;
  useEffect(() => {
    if (!type || !version) { setSaves(null); return undefined; }
    let on = true;
    setSaves(null);
    newLeagueOptions(type, version).then(o => {
      if (on) setSaves((o?.saves || []).map(s => saveEntry(s, o || {})).filter(s => s.name));
    }).catch(e => { if (on) { setSaves([]); setOptsError(e.message); } });
    return () => { on = false; };
  }, [type, version]);

  const task = findTask(catalog, 'new_league');
  const conflict = task ? startConflict(task, active) : null;
  const blocked = conflict && (conflict.kind === 'conflict' || conflict.kind === 'queue_full');
  const slug = (f.slug || f.id || '').trim().toLowerCase();
  const versions = useMemo(() => (opts?.versions || []), [opts]);
  const noSavedGames = !!opts && !versions.some(v => v.exists !== false);
  const bases = opts?.bases?.length ? opts.bases : ['TGS', 'BLM'];

  const doReview = async () => {
    const e = localErrors(type, f, sec);
    setErrors(e);
    setReview(null);
    if (Object.keys(e).length) return;
    setBusy(true);
    try {
      const r = await validateNewLeague(type, payload(type, f));
      let res = r || { ok: false };
      const errs = r?.errors && typeof r.errors === 'object' ? { ...r.errors } : {};
      if (errs.slug && type === 'statsplus' && !f.slug.trim()) {
        errs.slug = `The id gives the StatsPlus name ${slug}. ${errs.slug} Type another StatsPlus name.`;
      }
      // No token saved for the slug: the first pull needs the token or the cookie pair (12.1).
      if (type === 'statsplus' && r?.needs_credentials && !sec.token.trim()
        && !(sec.sessionid.trim() && sec.csrftoken.trim())) {
        errs.token = NEEDS_CREDENTIALS;
      }
      if (Object.keys(errs).length) res = { ...res, ok: false, errors: errs };
      setReview(res);
      setErrors(errs);
    } catch (err) {
      setReview({ ok: false, failed: err.message });
    } finally {
      setBusy(false);
    }
  };

  const doStart = async () => {
    if (!review?.ok || blocked) return;
    setBusy(true);
    setStartError(null);
    setStartFix(null);
    const secrets = {};
    if (type === 'statsplus') {
      if (sec.token.trim()) secrets.token = sec.token.trim();
      else { secrets.sessionid = sec.sessionid; secrets.csrftoken = sec.csrftoken; }
    }
    try {
      const job = await startJob('new_league', { type, ...payload(type, f) }, secrets);
      setSec({ token: '', sessionid: '', csrftoken: '' });
      if (job?.id) setJobId(job.id);
    } catch (err) {
      setSec({ token: '', sessionid: '', csrftoken: '' });
      if (err.body?.errors) setErrors(err.body.errors);
      setStartError(err.message);
      setStartFix(err.body?.fix_task || null);
    } finally {
      setBusy(false);
    }
  };

  if (jobId) {
    return (
      <div className="space-y-3">
        <button onClick={() => { setJobId(null); pickType(null); }} className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200">
          <ArrowLeft size={14} /> Add another league
        </button>
        <Running jobId={jobId} />
      </div>
    );
  }

  if (!type) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-slate-400">What kind of league do you want to add?</p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {TYPES.map(t => {
            const Icon = t.icon;
            return (
              <button key={t.id} onClick={() => pickType(t.id)} data-type={t.id}
                className="text-left bg-slate-900/60 border border-slate-800 hover:border-blue-500 rounded-xl p-4 transition-colors">
                <div className="flex items-center gap-2 mb-1">
                  <Icon size={16} className="text-blue-400" />
                  <span className="text-sm font-bold text-white">{t.title}</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{t.text}</p>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  const meta = TYPES.find(t => t.id === type);
  const saveSelect = (key, label, required) => (
    <Field name={key} label={`${label}${required ? '' : ' (optional)'}`} error={errors[key]}
      hint={!version ? 'Pick the OOTP version first.' : saves && !saves.length ? 'No saves found for this version.' : 'Only saves in the OOTP saved_games folder are listed.'}>
      <select id={`nl-${key}`} value={f[key] || ''} onChange={(e) => set(key, e.target.value)} disabled={!version || !saves} className={fieldClass}>
        <option value="">{!saves && version ? 'Loading...' : 'Pick a save'}</option>
        {(saves || []).map(s => <option key={s.name} value={s.name}>{s.name}{s.note ? ` (${s.note})` : ''}</option>)}
      </select>
    </Field>
  );
  const versionSelect = (required) => (
    <Field name="ootp_version" label={`OOTP version${required ? '' : ' (optional)'}`} error={errors.ootp_version}>
      <select id="nl-ootp_version" value={f.ootp_version || ''} onChange={(e) => { set('ootp_version', e.target.value); set('ootp_save', ''); set('master', ''); }} className={fieldClass}>
        <option value="">{opts ? 'Pick a version' : 'Loading...'}</option>
        {versions.map(v => (
          <option key={v.version} value={String(v.version)} disabled={v.exists === false}>
            OOTP {v.version}{v.exists === false ? ' (saved games folder not found)' : ''}
          </option>
        ))}
      </select>
    </Field>
  );
  const text = (key, label, hint, extra = {}) => (
    <Field name={key} label={label} hint={hint} error={errors[key]}>
      <input id={`nl-${key}`} value={f[key] ?? ''} onChange={(e) => set(key, e.target.value)} className={fieldClass} spellCheck={false} autoComplete="off" {...extra} />
    </Field>
  );
  const secret = (key, label, hint) => (
    <Field name={key} label={label} hint={hint} error={errors[key]}>
      <input id={`nl-${key}`} type="password" value={sec[key]} onChange={(e) => setS(key, e.target.value)} className={fieldClass} autoComplete="new-password" spellCheck={false} />
    </Field>
  );

  return (
    <div className="space-y-4">
      <button onClick={() => pickType(null)} className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200">
        <ArrowLeft size={14} /> Pick another type
      </button>
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-4">
        <div>
          <h2 className="text-sm font-bold text-white">{meta.title}</h2>
          <p className="text-xs text-slate-400 mt-0.5">{meta.text}</p>
        </div>
        {optsError && <p className="text-xs text-red-400">{optsError}</p>}
        {noSavedGames && (
          <Notice tone="warn" title="No OOTP saved games folder was found">
            <p>
              Set it on <Link to="/control/setup" className="text-blue-300 underline">Setup check</Link>, then come back.
            </p>
          </Notice>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {text('id', 'League id', '2 to 8 capital letters or digits. The app and the data folder use it.')}
          {text('name', 'Name', 'The name in the league menu.')}
          {type !== 'clone' && text('my_org', 'Your org (optional)', 'The org the Org Builder and Waivers pages open on.')}

          {type === 'statsplus' && (
            <>
              {text('slug', 'StatsPlus name (optional)', `The league's name in its statsplus.net address. Blank = ${(f.id || 'the id').toLowerCase()}.`)}
              <Field name="basis" label="Calibration" hint="The league whose calibration prices the players." error={errors.basis}>
                <select id="nl-basis" value={f.basis} onChange={(e) => set('basis', e.target.value)} className={fieldClass}>
                  {bases.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </Field>
              {secret('token', 'StatsPlus token (optional)', `This goes on the line ${slug ? slug.toUpperCase() : '<SLUG>'}= in StatsPlus Tokens.txt.`)}
              {!sec.token.trim() && secret('sessionid', 'Browser cookie: sessionid (optional)', 'Only needed when you give no token and none is saved.')}
              {!sec.token.trim() && secret('csrftoken', 'Browser cookie: csrftoken (optional)', 'Only needed when you give no token and none is saved.')}
              {versionSelect(false)}
              {saveSelect('ootp_save', 'OOTP save (for draft, Rule 5 and IAFA exports)', false)}
              {text('history_first_date', 'History start date (optional)', 'YYYY-MM-DD. Needed for Get StatsPlus History.')}
              {text('foreign_league_ids', 'StatsPlus league ids to leave out (optional)', 'Comma separated, for example 3,4.')}
            </>
          )}

          {type === 'local_export' && (
            <>
              {versionSelect(true)}
              {saveSelect('ootp_save', 'OOTP save', true)}
              <Field name="basis" label="Calibration" hint="Blank = BLM for OOTP 27, TGS for OOTP 26." error={errors.basis}>
                <select id="nl-basis" value={f.basis} onChange={(e) => set('basis', e.target.value)} className={fieldClass}>
                  <option value="">Default</option>
                  {bases.map(b => <option key={b} value={b}>{b}</option>)}
                </select>
              </Field>
            </>
          )}

          {type === 'dev' && (
            <>
              {versionSelect(true)}
              {saveSelect('ootp_save', 'OOTP save', true)}
              {text('dump_dir', 'Dump folder (optional)', "Blank = the save's dump folder.")}
              {text('years', 'Years per sim', 'Default 5.', { inputMode: 'numeric' })}
              {text('resume_after', 'Advanced: resume after (seconds)', 'Default 600.', { inputMode: 'numeric' })}
              {text('nostart_abort', 'Advanced: give up if the sim does not start (seconds)', 'Default 1800.', { inputMode: 'numeric' })}
            </>
          )}

          {type === 'clone' && (
            <>
              {versionSelect(true)}
              {saveSelect('master', 'Master save', true)}
              {text('prefix', 'Clone name prefix (optional)', `Blank = 0${(f.id || 'id').toLowerCase()}. Clean-up deletes every save named prefix plus a number.`)}
              {text('start_year', 'Start year', 'Default 2016.', { inputMode: 'numeric' })}
              {text('target_year', 'Target year', 'Default 2026.', { inputMode: 'numeric' })}
              {text('runs', 'Runs', 'Default 10.', { inputMode: 'numeric' })}
            </>
          )}
        </div>

        <div className="flex justify-end">
          <button onClick={doReview} disabled={busy}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-lg bg-slate-700 text-white hover:bg-slate-600 disabled:opacity-40">
            {busy && !review ? <Loader2 size={12} className="animate-spin" /> : <ListChecks size={12} />} Review
          </button>
        </div>
      </div>

      {review && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 space-y-3" data-role="review">
          <h3 className="text-sm font-bold text-white">Review</h3>
          {review.failed && <p className="text-sm text-red-300">{review.failed}</p>}
          {!review.failed && !review.ok && (
            <p className="text-sm text-red-300">Fix the fields marked in red, then press Review again.</p>
          )}
          {review.errors && Object.keys(review.errors).length > 0 && (
            <ul className="text-xs text-red-300 list-disc pl-4 space-y-0.5">
              {Object.entries(review.errors).map(([k, v]) => <li key={k}><span className="text-red-400">{LABELS[k] || k}:</span> {String(v)}</li>)}
            </ul>
          )}
          {Array.isArray(review.warnings) && review.warnings.length > 0 && (
            <ul className="text-xs text-amber-300 list-disc pl-4 space-y-0.5">
              {review.warnings.map((w, i) => <li key={i}>{String(w)}</li>)}
            </ul>
          )}
          <div>
            <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1">Known limits</p>
            <ul className="text-xs text-slate-400 list-disc pl-4 space-y-0.5">
              {LIMITS[type].map(l => <li key={l}>{l}</li>)}
            </ul>
          </div>
          {Array.isArray(review.plan) && review.plan.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide mb-1">What it will do</p>
              <ol className="text-xs text-slate-300 list-decimal pl-5 space-y-0.5">
                {review.plan.map((p, i) => {
                  const writes = Array.isArray(p.writes) ? p.writes.join(', ') : String(p.writes || '');
                  return (
                    <li key={i}>
                      {p.title}
                      {writes && writes !== 'Nothing.' && <span className="block text-slate-500">Writes: {writes}</span>}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}
          {conflict && conflict.kind !== 'waits' && <p className="text-xs text-amber-300">{conflictText(conflict)}</p>}
          {startError && <p className="text-xs text-red-400" role="alert">{startError}</p>}
          {startFix && findTask(catalog, startFix) && (
            <button type="button" onClick={() => setFixForm(findTask(catalog, startFix))}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500">
              <Play size={12} /> {findTask(catalog, startFix).title}
            </button>
          )}
          {fixJob && <JobPanel jobId={fixJob} compact />}
          {fixForm && <TaskForm task={fixForm} onClose={() => setFixForm(null)}
            onStarted={(job) => { setFixForm(null); setStartFix(null); setStartError(null); if (job?.id) setFixJob(job.id); }} />}
          <div className="flex justify-end">
            <button onClick={doStart} disabled={!review.ok || busy || !!blocked}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed">
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Add the league
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
