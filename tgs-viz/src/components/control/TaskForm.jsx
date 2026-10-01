import React, { useMemo, useState } from 'react';
import { Play, Loader2 } from 'lucide-react';
import { useCatalog, useActiveJobs, startJob, startConflict, findTask } from '../../lib/controlApi';
import { visibleInputs, checkInputValue, conflictText, lockReason } from '../../lib/inputConditions';
import { Modal } from './PromptCard';
import { flagNotes } from './TaskCard';

const fieldClass = 'w-full bg-slate-800 text-white text-sm rounded-lg px-3 py-2 border border-slate-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500';

function initialValues(task) {
  const v = {};
  for (const inp of task?.inputs || []) {
    if (inp.type === 'secret') continue;
    if (inp.type === 'confirm') v[inp.name] = inp.default === true;
    else v[inp.name] = inp.default === undefined || inp.default === null ? '' : String(inp.default);
  }
  return v;
}

/** One input field of a run form. */
export function InputField({ inp, value, onChange, error }) {
  const id = `inp-${inp.name}`;
  let control;
  if (inp.type === 'confirm') {
    control = (
      <label htmlFor={id} className="flex items-start gap-2 text-sm text-slate-200 cursor-pointer">
        <input id={id} type="checkbox" checked={value === true} onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5 accent-blue-500" />
        <span>{inp.label}{inp.required ? '' : ' (optional)'}</span>
      </label>
    );
  } else if (inp.type === 'choice') {
    control = (
      <select id={id} value={value ?? ''} onChange={(e) => onChange(e.target.value)} className={fieldClass}>
        {(!inp.required || value === '' || value === undefined) && <option value="">{inp.required ? 'Pick one' : '(none)'}</option>}
        {(inp.choices || []).map(c => <option key={c.value} value={c.value}>{c.label ?? c.value}</option>)}
      </select>
    );
  } else {
    control = (
      <input id={id} type={inp.type === 'secret' ? 'password' : 'text'} value={value ?? ''}
        autoComplete={inp.type === 'secret' ? 'new-password' : 'off'} spellCheck={false}
        inputMode={inp.format === 'int' ? 'numeric' : undefined}
        onChange={(e) => onChange(e.target.value)} className={fieldClass} />
    );
  }
  return (
    <div className="space-y-1" data-input={inp.name}>
      {inp.type !== 'confirm' && (
        <label htmlFor={id} className="block text-xs font-semibold text-slate-300">
          {inp.label || inp.name}{inp.required ? '' : ' (optional)'}
        </label>
      )}
      {control}
      {inp.help && <p className="text-[11px] text-slate-500">{inp.help}</p>}
      {error && <p className="text-[11px] text-red-400" role="alert">{error}</p>}
    </div>
  );
}

/**
 * The run form of one task: the inputs whose ask_when holds, secrets as
 * password fields, confirms as required boxes. Start follows startConflict.
 * Secrets stay in this component's state and are dropped right after the POST.
 */
export default function TaskForm(props) {
  // A refused start can name a task that fixes the problem (fix_task); the
  // form then switches to that task.
  const [task, setTask] = useState(props.task);
  return <TaskFormBody key={task.id} {...props} task={task} onSwitch={setTask} />;
}

function TaskFormBody({ task, onClose, onStarted, presetInputs = null, onSwitch }) {
  const { catalog } = useCatalog();
  const active = useActiveJobs();
  const [values, setValues] = useState(() => ({ ...initialValues(task), ...(presetInputs || {}) }));
  const [secrets, setSecrets] = useState({});
  const [errors, setErrors] = useState({});
  const [serverError, setServerError] = useState(null);
  const [busy, setBusy] = useState(false);

  const ctx = useMemo(() => ({ state: catalog?.state || {}, inputs: { ...values, ...secrets } }), [catalog, values, secrets]);
  const shown = useMemo(() => visibleInputs(task, ctx), [task, ctx]);
  const conflict = startConflict(task, active);
  const blocked = conflict && (conflict.kind === 'conflict' || conflict.kind === 'queue_full');
  const notes = flagNotes(task);

  const setValue = (inp, v) => {
    if (inp.type === 'secret') setSecrets(prev => ({ ...prev, [inp.name]: v }));
    else setValues(prev => ({ ...prev, [inp.name]: v }));
    setErrors(prev => ({ ...prev, [inp.name]: undefined }));
  };

  const submit = async (e) => {
    e?.preventDefault();
    if (blocked || busy) return;
    const errs = {};
    for (const inp of shown) {
      const v = inp.type === 'secret' ? secrets[inp.name] : values[inp.name];
      const msg = checkInputValue(inp, v);
      if (msg) errs[inp.name] = msg;
    }
    setErrors(errs);
    if (Object.keys(errs).length) return;

    const inputs = {};
    const sec = {};
    for (const inp of shown) {
      if (inp.type === 'secret') sec[inp.name] = secrets[inp.name] || '';
      else if (inp.type === 'confirm') inputs[inp.name] = values[inp.name] === true;
      else if (String(values[inp.name] ?? '').trim() !== '') inputs[inp.name] = String(values[inp.name]).trim();
    }
    if (presetInputs) for (const [k, v] of Object.entries(presetInputs)) if (!(k in inputs)) inputs[k] = v;

    setBusy(true);
    setServerError(null);
    try {
      const job = await startJob(task.id, inputs, sec);
      setSecrets({});
      onStarted?.(job);
    } catch (err) {
      setSecrets({});
      const body = err.body || {};
      if (body.errors && typeof body.errors === 'object') setErrors(body.errors);
      let msg = err.message;
      if (err.code === 'conflict' && body.lock) {
        msg = `${body.job?.title || 'Another task'} is running (${lockReason(body.lock)}).`;
      } else if (err.code === 'bad_secret') {
        if (body.field) setErrors(prev => ({ ...prev, [body.field]: 'This value is not accepted.' }));
      }
      setServerError({ message: msg, fix: body.fix_task || null, tail: body.log_tail || body.stderr_tail || null });
    } finally {
      setBusy(false);
    }
  };

  const fixTask = serverError?.fix ? findTask(catalog, serverError.fix) : null;

  return (
    <Modal title={task.title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" autoComplete="off">
        {task.description && <p className="text-xs text-slate-400 leading-relaxed">{task.description}</p>}
        {notes.length > 0 && (
          <ul className="text-[11px] text-slate-500 space-y-0.5 list-disc pl-4">
            {notes.map(n => <li key={n}>{n}</li>)}
          </ul>
        )}

        {shown.length > 0 ? (
          <div className="space-y-3">
            {shown.map(inp => (
              <InputField key={inp.name} inp={inp}
                value={inp.type === 'secret' ? (secrets[inp.name] ?? '') : values[inp.name]}
                onChange={(v) => setValue(inp, v)} error={errors[inp.name]} />
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">This task asks nothing. Press Start to run it.</p>
        )}

        {conflict && conflict.kind !== 'waits' && (
          <p className="text-xs text-amber-300 bg-amber-950/30 border border-amber-600/40 rounded-lg px-3 py-2" role="status">
            {conflictText(conflict)}
          </p>
        )}
        {serverError && (
          <div className="text-xs text-red-300 bg-red-950/30 border border-red-600/40 rounded-lg px-3 py-2 space-y-1" role="alert">
            <p>{serverError.message}</p>
            {serverError.tail && <pre className="whitespace-pre-wrap text-[11px] text-red-300/80">{serverError.tail}</pre>}
            {fixTask && (
              <button type="button" onClick={() => onSwitch(fixTask)}
                className="mt-1 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500">
                <Play size={12} /> {fixTask.title}
              </button>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-800 text-slate-300 hover:bg-slate-700">
            Cancel
          </button>
          <button type="submit" disabled={!!blocked || busy}
            className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed">
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {conflict?.kind === 'waits' ? conflictText(conflict) : 'Start'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
