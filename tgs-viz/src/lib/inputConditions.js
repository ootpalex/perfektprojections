/**
 * inputConditions.js: pure rules the Control page applies before it starts a
 * task. No React, no fetch, so a node test can load it as it is.
 *
 * - evalCondition: the browser mirror of tools/conditions.py (DESIGN 4.4).
 *   It decides which inputs a run form asks for (`ask_when`).
 * - startConflict: what the Start button does while other jobs run (10.2).
 * - checkSecret / checkInputValue: the browser-side input checks (3.3, 8.5).
 */

// ---------------------------------------------------------------------------
// Conditions (4.4)
// ---------------------------------------------------------------------------

const blank = (v) => v === undefined || v === null || String(v).trim() === '';

/**
 * True when `cond` holds. ctx = { state: catalog.state, inputs: {...}, flags: {...}, exists: {...} }.
 * `inputs` holds every value the form has, secrets included (input_nonblank reads them).
 * A null or missing condition is true (an input with no ask_when is always asked).
 * `exists` and `flag` are Python-only; here they read ctx.exists / ctx.flags and
 * default to false.
 */
export function evalCondition(cond, ctx = {}) {
  if (cond === null || cond === undefined) return true;
  if (typeof cond !== 'object' || Array.isArray(cond)) return false;
  const state = ctx.state || {};
  const tokens = state.tokens || {};
  const inputs = ctx.inputs || {};
  const keys = Object.keys(cond);
  if (keys.length !== 1) return false;
  const k = keys[0];
  const v = cond[k];
  switch (k) {
    case 'no_token':
      return !tokens[v];
    case 'no_token_input': {
      const lg = inputs[v];
      if (blank(lg)) return true;
      return !tokens[String(lg).trim().toUpperCase()];
    }
    case 'input_nonblank':
      return typeof inputs[v] === 'string' && inputs[v].trim() !== '';
    case 'exists':
      return !!(ctx.exists && ctx.exists[v]);
    case 'flag':
      return !!(ctx.flags && ctx.flags[v]);
    case 'all':
      return Array.isArray(v) && v.every(c => evalCondition(c, ctx));
    case 'any':
      return Array.isArray(v) && v.some(c => evalCondition(c, ctx));
    case 'not':
      return !evalCondition(v, ctx);
    default:
      return false;
  }
}

/** The inputs a run form shows: job-mode inputs whose ask_when holds. */
export function visibleInputs(task, ctx) {
  return (task?.inputs || []).filter(inp => {
    if (Array.isArray(inp.modes) && !inp.modes.includes('job')) return false;
    return evalCondition(inp.ask_when ?? null, ctx);
  });
}

// ---------------------------------------------------------------------------
// Input checks (3.3, 8.5, 10.3)
// ---------------------------------------------------------------------------

/** Plain-words problem with a secret value, or '' when it is fine. */
export function checkSecret(value, required = false) {
  const v = value === undefined || value === null ? '' : String(value);
  if (/[\r\n\0]/.test(v)) return 'Paste the value on one line, with no line breaks.';
  const t = v.trim();
  if (!t) return required ? 'This value is required.' : '';
  if (t.length < 8) return required ? 'Too short. Use at least 8 characters.' : 'Too short. Use at least 8 characters, or leave it blank.';
  if (new TextEncoder().encode(v).length > 4096) return 'Too long. Use at most 4096 characters.';
  return '';
}

/** StatsPlus token shape the browser checks before a run (10.4). */
export const TOKEN_RE = /^[A-Za-z0-9_-]{20,80}$/;
export function checkToken(value, required = false) {
  const t = String(value ?? '').trim();
  if (!t) return required ? 'Paste the token.' : '';
  if (!TOKEN_RE.test(t)) return `This does not look like a StatsPlus token (${t.length} characters). A token has 20 to 80 letters, digits, - or _.`;
  return '';
}

/** Plain-words problem with one non-secret input value, or ''. */
export function checkInputValue(inp, value) {
  const type = inp.type;
  if (type === 'confirm') {
    return inp.required && value !== true ? 'Tick this box to go on.' : '';
  }
  if (type === 'secret') {
    // a StatsPlus token gets the same shape check in every form (10.4)
    if (inp.format !== 'statsplus_token') return checkSecret(value, !!inp.required);
    if (/[\r\n\0]/.test(String(value ?? ''))) return 'Paste the value on one line, with no line breaks.';
    return checkToken(value, !!inp.required);
  }
  const v = value === undefined || value === null ? '' : String(value);
  if (!v.trim()) return inp.required ? 'This value is required.' : '';
  if (type === 'choice') {
    const ok = (inp.choices || []).some(c => String(c.value) === v);
    return ok ? '' : 'Pick one of the choices.';
  }
  if (inp.format === 'int') {
    if (!/^\s*-?\d+\s*$/.test(v)) return 'Type a whole number.';
    const n = parseInt(v, 10);
    if (inp.min !== undefined && inp.min !== null && n < inp.min) return `Use ${inp.min} or more.`;
    if (inp.max !== undefined && inp.max !== null && n > inp.max) return `Use ${inp.max} or less.`;
  }
  if (inp.equals !== undefined && inp.equals !== null && v.trim() !== String(inp.equals)) {
    return `Type ${inp.equals} exactly.`;
  }
  if (v.length > 4000) return 'Too long.';
  return '';
}

// ---------------------------------------------------------------------------
// Start conflicts (10.2)
// ---------------------------------------------------------------------------

const ACTIVE = new Set(['starting', 'queued', 'running', 'waiting']);

/** Whole-run locks a task takes: its catalog list plus task.<id> (4.10). Read-only: none. */
export function wholeRunLocks(task) {
  if (!task || task.flags?.read_only) return [];
  const out = new Set(task.locks || []);
  out.add(`task.${task.id}`);
  out.delete('data');
  return [...out];
}

/** True when some step of the task takes the data lock (7.5). */
export function needsDataLock(task) {
  if (!task || task.flags?.read_only) return false;
  const steps = task.steps || [];
  if (!steps.length) return true;
  return steps.some(s => s.data !== false);
}

function heldLocks(job) {
  if (Array.isArray(job.locks_held)) return job.locks_held;
  // A tgs:job summary without the state's lock list: the job at least holds its own task lock.
  return job.task ? [`task.${job.task}`] : [];
}

function holdsData(job) {
  if (job.data_lock === 'held') return true;
  return Array.isArray(job.locks_held) && job.locks_held.includes('data');
}

/**
 * What happens if the user starts `task` now.
 * { kind: 'conflict', job, lock } | { kind: 'queue_full', job } | { kind: 'waits', job } | null
 */
export function startConflict(task, activeJobs) {
  if (!task) return null;
  const jobs = (activeJobs || []).filter(j => j && ACTIVE.has(j.status));
  const mine = wholeRunLocks(task);
  for (const job of jobs) {
    const held = heldLocks(job);
    const lock = mine.find(l => held.includes(l));
    if (lock) return { kind: 'conflict', job, lock };
  }
  if (!needsDataLock(task)) return null;
  const queued = jobs.find(j => j.status === 'queued');
  if (queued) return { kind: 'queue_full', job: queued };
  const holder = jobs.find(holdsData);
  if (holder) return { kind: 'waits', job: holder };
  return null;
}

/** The lock's reason in the words of 6.4, as a clause after "it". */
export function lockReason(lock) {
  const l = String(lock || '');
  if (l === 'ootp') return 'it uses OOTP and your mouse';
  if (l.startsWith('clones.')) return `it uses the ${l.slice(7)} clone saves`;
  if (l.startsWith('dumps.')) return `it uses the ${l.slice(6)} dump folder`;
  if (l.startsWith('task.')) return 'it is this same task';
  if (l === 'data') return 'it is updating app data';
  return `it holds the ${l} lock`;
}

/** "Grind TGS is running (it uses OOTP and your mouse)." */
export function conflictText(c) {
  if (!c) return '';
  const title = c.job?.title || c.job?.task || 'Another task';
  if (c.kind === 'conflict') return `${title} is running (${lockReason(c.lock)}).`;
  if (c.kind === 'queue_full') return 'Another task is already waiting. Start this one after it.';
  if (c.kind === 'waits') return `Start (waits for ${title})`;
  return '';
}
