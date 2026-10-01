/**
 * controlApi.js: the browser side of the Control panel (DESIGN 10.2).
 *
 * One module-level store, so job state survives route changes and league
 * switches (those unmount every page). It holds the per-start token, the
 * ping and catalog answers, the app config, the active jobs and one buffered
 * event stream per open job.
 *
 * The token comes over Vite's own websocket (tgs:hello -> tgs:token) and lives
 * in page memory only. Secrets pass through startJob and are never stored.
 */
import { useEffect, useReducer, useSyncExternalStore } from 'react';
import { startConflict } from './inputConditions';

export { startConflict };

const hot = import.meta.hot;
const TOKEN_WAIT_MS = 5000;
const FINAL = new Set(['done', 'partial', 'failed', 'stopped', 'killed', 'invalid', 'refused', 'lost', 'did_not_start']);
const ACTIVE = new Set(['starting', 'queued', 'running', 'waiting']);

export const isFinalStatus = (s) => FINAL.has(s);
export const isActiveStatus = (s) => ACTIVE.has(s);

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

let store = {
  hot: !!hot,
  tokenStatus: hot ? 'pending' : 'none',   // pending | ok | none
  ping: null,
  pingError: null,
  catalog: null,
  catalogError: null,
  config: null,
  jobs: {},          // id -> latest known state, merged with tgs:job summaries
  activeIds: [],     // active job ids, oldest first
  recentIds: [],     // ids that ended while this page was open, newest first
  activeList: [],    // derived: jobs[activeIds]
  serverLost: false, // the Vite websocket is closed (Launch TGS window closed or Vite stopped)
};
const listeners = new Set();

function setStore(patch) {
  store = { ...store, ...patch };
  if (patch.jobs || patch.activeIds) {
    store.activeList = store.activeIds.map(id => store.jobs[id]).filter(Boolean);
  }
  for (const fn of [...listeners]) {
    try { fn(); } catch (e) { console.warn('[tgs-control] listener failed:', e); }
  }
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function useSlice(pick) {
  return useSyncExternalStore(subscribe, () => pick(store), () => pick(store));
}

// ---------------------------------------------------------------------------
// Token handshake (8.4)
// ---------------------------------------------------------------------------

let token = null;
let tokenWaiters = [];

function sayHello() {
  if (!hot) return;
  try { hot.send('tgs:hello', {}); } catch (e) { console.warn('[tgs-control] hello failed:', e); }
}

function waitToken(ms = TOKEN_WAIT_MS) {
  if (token) return Promise.resolve(token);
  if (!hot) return Promise.resolve(null);
  return new Promise(resolve => {
    const t = setTimeout(() => {
      tokenWaiters = tokenWaiters.filter(w => w !== done);
      resolve(null);
    }, ms);
    function done(tok) { clearTimeout(t); resolve(tok); }
    tokenWaiters.push(done);
  });
}

let helloInFlight = null;
async function rehello() {
  if (helloInFlight) return helloInFlight;
  token = null;
  helloInFlight = (async () => {
    sayHello();
    const tok = await waitToken();
    if (!tok) setStore({ tokenStatus: 'none' });
    return tok;
  })();
  try { return await helloInFlight; } finally { helloInFlight = null; }
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

export class ControlError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body || {};
    this.code = this.body.code || null;
  }
}

async function readJson(res) {
  const ctype = res.headers.get('content-type') || '';
  if (!ctype.includes('json')) return null;
  try { return await res.json(); } catch { return null; }
}

/** fetch on /__tgs with the token. Throws ControlError on a non-2xx answer. */
async function api(path, { method = 'GET', body, raw = false, retry = true } = {}) {
  let tok = token || await waitToken();
  if (!tok) throw new ControlError('The Control page is not connected to the app server.', 0, { code: 'no_token' });
  const headers = { 'X-TGS-Token': tok };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(`/__tgs${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new ControlError('The app server did not answer. Is the Launch TGS window still open?', 0, { code: 'network' });
  }
  if (res.status === 401 && retry) {
    await rehello();
    return api(path, { method, body, raw, retry: false });
  }
  if (raw && res.ok) return res;
  const json = await readJson(res);
  if (!res.ok) {
    const err = (json && json.error) || {};
    throw new ControlError(err.message || `The app server answered ${res.status}.`, res.status, err);
  }
  return json;
}

// ---------------------------------------------------------------------------
// Loads
// ---------------------------------------------------------------------------

/** Ask the server again for ping (Python probe, Control on or off). */
export function reloadPing() {
  return loadPing();
}

/** Ask the server to run the Python probe again (Setup page's Check again), then store the answer. */
export async function reprobePython() {
  try {
    const json = await api('/ping?probe=1');
    if (json) setStore({ ping: json, pingError: null });
    return json;
  } catch {
    return loadPing();
  }
}

async function loadPing() {
  try {
    const res = await fetch('/__tgs/ping');
    const json = await readJson(res);
    if (!json) throw new Error(`ping answered ${res.status}`);
    setStore({ ping: json, pingError: null });
    return json;
  } catch (e) {
    setStore({ pingError: String(e.message || e) });
    return null;
  }
}

let catalogLoad = null;
export function reloadCatalog(refresh = false) {
  if (catalogLoad) return catalogLoad;
  catalogLoad = (async () => {
    try {
      const cat = await api(`/catalog${refresh ? '?refresh=1' : ''}`);
      setStore({ catalog: cat, catalogError: null, config: cat?.app_config || store.config });
    } catch (e) {
      setStore({ catalogError: e });
    } finally {
      catalogLoad = null;
    }
  })();
  return catalogLoad;
}

async function loadConfig() {
  try {
    const cfg = await api('/config');
    if (cfg && typeof cfg === 'object') setStore({ config: cfg });
  } catch { /* the catalog carries app_config too */ }
}

function mergeJob(prev, next) {
  if (!prev) return { ...next };
  return { ...prev, ...next };
}

// A tgs:job summary or a state.json: same id, different fields. Both go into jobs[id].
function noteJob(job) {
  if (!job || !job.id) return;
  const jobs = { ...store.jobs, [job.id]: mergeJob(store.jobs[job.id], job) };
  let activeIds = store.activeIds;
  let recentIds = store.recentIds;
  const st = jobs[job.id].status;
  if (ACTIVE.has(st)) {
    if (!activeIds.includes(job.id)) activeIds = [...activeIds, job.id];
  } else if (FINAL.has(st)) {
    if (activeIds.includes(job.id)) {
      activeIds = activeIds.filter(id => id !== job.id);
      recentIds = [job.id, ...recentIds.filter(id => id !== job.id)].slice(0, 10);
    }
  }
  setStore({ jobs, activeIds, recentIds });
}

export async function reloadActiveJobs() {
  try {
    const res = await api('/jobs/active');
    const list = Array.isArray(res?.jobs) ? res.jobs : [];
    const jobs = { ...store.jobs };
    const ids = [];
    for (const j of list) {
      if (!j || !j.id) continue;
      jobs[j.id] = mergeJob(jobs[j.id], j);
      ids.push(j.id);
    }
    // Jobs we followed that are no longer active ended between two looks.
    const gone = store.activeIds.filter(id => !ids.includes(id));
    const recentIds = [...gone, ...store.recentIds.filter(id => !gone.includes(id))].slice(0, 10);
    setStore({ jobs, activeIds: ids, recentIds });
    for (const id of gone) refreshJob(id);
  } catch { /* the page shows the connection problem elsewhere */ }
}

async function refreshJob(id) {
  try {
    const res = await api(`/jobs/${encodeURIComponent(id)}`);
    if (res?.job) noteJob({ id, ...res.job });
  } catch { /* keep what we have */ }
}

function dismissRecent(id) {
  setStore({ recentIds: store.recentIds.filter(x => x !== id) });
}
export { dismissRecent };

// ---------------------------------------------------------------------------
// Start-up
// ---------------------------------------------------------------------------

let started = false;
function start() {
  if (started || typeof window === 'undefined') return;
  started = true;
  loadPing();
  if (!hot) return;
  hot.on('tgs:token', (d) => {
    if (!d || !d.token) return;
    token = String(d.token);
    const waiters = tokenWaiters;
    tokenWaiters = [];
    for (const w of waiters) w(token);
    if (store.tokenStatus !== 'ok') setStore({ tokenStatus: 'ok' });
  });
  hot.on('tgs:job', (d) => {
    try {
      if (!d || !d.id) return;
      const known = !!store.jobs[d.id];
      noteJob(d);
      if (!known) refreshJob(d.id);
    } catch (e) { console.warn('[tgs-control] tgs:job:', e); }
  });
  hot.on('tgs:catalog', () => { reloadCatalog(); loadConfig(); });
  hot.on('tgs:control', (d) => {
    if (!d) return;
    const ping = { ...(store.ping || {}), control: { on: !!d.on, reason: d.reason || null } };
    if (d.python !== undefined) ping.python = d.python;
    if (d.live_refresh !== undefined) ping.live_refresh = d.live_refresh;
    ping.ok = !!d.on;
    setStore({ ping });
    if (d.on && !token) rehello().then(tok => { if (tok) { reloadCatalog(); loadConfig(); reloadActiveJobs(); } });
  });
  // Lost contact: Vite's client keeps polling and reloads the page when the server is back.
  // A short gap (a config restart) shows nothing.
  let lostTimer = null;
  hot.on('vite:ws:disconnect', () => {
    clearTimeout(lostTimer);
    lostTimer = setTimeout(() => setStore({ serverLost: true }), 3000);
  });
  hot.on('vite:ws:connect', () => {
    clearTimeout(lostTimer);
    if (store.serverLost) setStore({ serverLost: false });
  });
  sayHello();
  waitToken().then(tok => {
    if (!tok) { setStore({ tokenStatus: 'none' }); return; }
    setStore({ tokenStatus: 'ok' });
    loadConfig();
    reloadCatalog();
    reloadActiveJobs();
  });
  // A slow look at the active list covers a missed websocket message.
  const poll = setInterval(() => {
    if (token && document.visibilityState === 'visible') reloadActiveJobs();
  }, 20000);
  hot.dispose(() => {
    clearInterval(poll);
    for (const s of streams.values()) { if (s.close) s.close(); clearTimeout(s.idleTimer); }
  });
}
start();

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** { catalog, error } */
export function useCatalog() {
  const catalog = useSlice(s => s.catalog);
  const error = useSlice(s => s.catalogError);
  return { catalog, error };
}

/** The app config (catalog.app_config), or null until it arrives. */
export function useAppConfig() {
  return useSlice(s => s.config);
}

/** Active jobs, oldest first. */
export function useActiveJobs() {
  return useSlice(s => s.activeList);
}

/** True while the page has lost contact with the app server. */
export function useServerLost() {
  return useSlice(s => s.serverLost);
}

/** Ids of jobs that ended while this page was open, newest first. */
export function useRecentJobIds() {
  return useSlice(s => s.recentIds);
}

/** One job's latest known state (from the active list, tgs:job or a stream). */
export function useJobInfo(id) {
  return useSlice(s => (id ? s.jobs[id] || null : null));
}

/**
 * Connection state for the page.
 * mode: 'connecting' | 'ok' | 'no_plugin' | 'off'
 */
export function useControlStatus() {
  const hotOn = useSlice(s => s.hot);
  const tokenStatus = useSlice(s => s.tokenStatus);
  const ping = useSlice(s => s.ping);
  let mode = 'connecting';
  if (!hotOn) mode = 'no_plugin';
  else if (ping && ping.control && ping.control.on === false) mode = 'off';
  else if (tokenStatus === 'ok') mode = 'ok';
  else if (tokenStatus === 'none') mode = 'no_plugin';
  return {
    mode,
    reason: ping?.control?.reason || null,
    python: ping?.python || null,
    // Control off means no data watcher either, so live refresh is off too.
    liveRefresh: ping ? (ping.live_refresh !== false && ping.control?.on !== false) : true,
    ping,
  };
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

/**
 * Start a task. inputs: non-secret values. secrets: {name: value}; blank ones are dropped.
 * Resolves to the job ({id, status, ...}); throws ControlError (body has errors, fix_task, job, lock).
 */
export async function startJob(task, inputs = {}, secrets = {}) {
  const sec = {};
  for (const [k, v] of Object.entries(secrets || {})) {
    if (v !== undefined && v !== null && String(v).trim() !== '') sec[k] = String(v);
  }
  const res = await api('/jobs', { method: 'POST', body: { task, inputs, secrets: sec } });
  const job = res?.job || null;
  if (job && job.id) {
    noteJob(job);
    // A quick task can end before the server answers. It was never active here,
    // so show it as a recent run: the user just asked for it.
    const st = store.jobs[job.id]?.status;
    if (FINAL.has(st) && !store.activeIds.includes(job.id) && !store.recentIds.includes(job.id)) {
      setStore({ recentIds: [job.id, ...store.recentIds].slice(0, 10) });
    }
  }
  return job;
}

export function answer(jobId, promptId, value) {
  return api(`/jobs/${encodeURIComponent(jobId)}/answer`, { method: 'POST', body: { prompt_id: promptId, value } });
}

export function stop(jobId, mode) {
  return api(`/jobs/${encodeURIComponent(jobId)}/stop`, { method: 'POST', body: { mode } });
}

export async function getJob(jobId) {
  const res = await api(`/jobs/${encodeURIComponent(jobId)}`);
  if (res?.job) noteJob({ id: jobId, ...res.job });
  return res?.job || null;
}

export async function listJobs(limit = 20) {
  const res = await api(`/jobs?limit=${limit}`);
  return Array.isArray(res?.jobs) ? res.jobs : [];
}

/** Plain text of a job log from a byte offset: { text, next }. */
export async function getLog(jobId, from = 0, max = 262144) {
  const res = await api(`/jobs/${encodeURIComponent(jobId)}/log?from=${from}&max=${max}`, { raw: true });
  const text = await res.text();
  const next = parseInt(res.headers.get('X-TGS-Next-Offset') || '', 10);
  return { text, next: Number.isFinite(next) ? next : from };
}

export const getDoctor = () => api('/doctor');
export const getSettings = () => api('/settings');
export const patchSettings = (patch) => api('/settings', { method: 'POST', body: { patch } });
export const resetLocalSettings = () => api('/settings/reset-local', { method: 'POST', body: {} });
export function newLeagueOptions(type, version) {
  const q = new URLSearchParams({ type });
  if (version) q.set('version', version);
  return api(`/new-league/options?${q}`);
}
export const validateNewLeague = (type, fields) => api('/new-league/validate', { method: 'POST', body: { type, fields } });

// ---------------------------------------------------------------------------
// Event streams (8.6)
// ---------------------------------------------------------------------------

/**
 * Open the SSE stream of one job. handlers: { hello, log, step, message, prompt,
 * state, done, error } each called with the parsed data and the event id.
 * opts: { from (event id cursor), tail (bytes) }. Returns close().
 */
export function openEvents(jobId, handlers = {}, opts = {}) {
  if (!token) {
    handlers.error?.({ code: 'no_token' });
    return () => {};
  }
  const q = new URLSearchParams({ t: token });
  if (opts.from) q.set('from', opts.from);
  if (opts.tail !== undefined) q.set('tail', String(opts.tail));
  const es = new EventSource(`/__tgs/jobs/${encodeURIComponent(jobId)}/events?${q}`);
  for (const name of ['hello', 'log', 'step', 'message', 'prompt', 'state', 'done']) {
    es.addEventListener(name, (e) => {
      let data = null;
      try { data = JSON.parse(e.data); } catch { return; }
      try { handlers[name]?.(data, e.lastEventId || null); } catch (err) { console.warn('[tgs-control] stream handler:', err); }
      if (name === 'done') es.close();
    });
  }
  es.onerror = () => {
    if (es.readyState === EventSource.CLOSED) handlers.error?.({ code: 'closed' });
  };
  return () => es.close();
}

const MAX_LINES = 5000;
const streams = new Map();

function newStream(id) {
  return {
    id, lines: [], partial: null, dropped: 0,
    state: null, prompt: null, done: null, countdown: null, messages: [],
    cursor: null, close: null, subs: new Set(), idleTimer: null,
    reopenTries: 0, error: null, version: 0, notifyQueued: false,
  };
}

function notifyStream(s) {
  s.version += 1;
  if (s.notifyQueued) return;
  s.notifyQueued = true;
  const run = () => {
    s.notifyQueued = false;
    for (const fn of [...s.subs]) {
      try { fn(); } catch { /* one bad listener must not stop the rest */ }
    }
  };
  if (typeof requestAnimationFrame === 'function' && document.visibilityState === 'visible') requestAnimationFrame(run);
  else setTimeout(run, 50);
}

function pushLines(s, text) {
  const parts = text.split('\n');
  if (parts.length && parts[parts.length - 1] === '') parts.pop();
  for (const p of parts) s.lines.push(p);
  if (s.lines.length > MAX_LINES) {
    const cut = s.lines.length - MAX_LINES;
    s.lines.splice(0, cut);
    s.dropped += cut;
  }
}

function onLog(s, d) {
  let text = String(d?.text ?? '');
  if (s.partial) {
    const resend = (d.offset !== undefined && d.offset !== null && d.offset === s.partial.offset)
      || text.startsWith(s.partial.text);
    if (!resend) text = s.partial.text + text;
    s.partial = null;
  }
  if (d?.partial) {
    const nl = text.lastIndexOf('\n');
    if (nl >= 0) {
      pushLines(s, text.slice(0, nl + 1));
      text = text.slice(nl + 1);
    }
    s.partial = { text, offset: d.offset };
  } else {
    pushLines(s, text);
  }
}

function openStream(s) {
  if (s.close || s.done) return;
  const opts = s.cursor ? { from: s.cursor } : { tail: 262144 };
  s.close = openEvents(s.id, {
    hello: () => { s.error = null; s.reopenTries = 0; },
    log: (d, eid) => { if (eid) s.cursor = eid; onLog(s, d); notifyStream(s); },
    step: (d, eid) => { if (eid) s.cursor = eid; },
    message: (d, eid) => {
      if (eid) s.cursor = eid;
      if (d?.level === 'countdown') s.countdown = { text: d.text, at: Date.now() };
      else if (d?.text) { s.messages.push({ level: d.level || 'info', text: d.text }); s.messages = s.messages.slice(-20); }
      notifyStream(s);
    },
    prompt: (d, eid) => { if (eid) s.cursor = eid; s.prompt = d; notifyStream(s); },
    state: (d, eid) => {
      if (eid) s.cursor = eid;
      s.state = d;
      if (d && d.status !== 'waiting') s.prompt = null;
      else if (d && d.prompt) s.prompt = d.prompt;
      if (d && (d.id || s.id)) noteJob({ id: s.id, ...d });
      notifyStream(s);
    },
    done: (d, eid) => {
      if (eid) s.cursor = eid;
      s.done = d || {};
      if (s.partial) { pushLines(s, s.partial.text); s.partial = null; }
      s.close = null;
      s.prompt = null;
      s.countdown = null;
      if (d?.status) noteJob({ id: s.id, status: d.status, ...(s.state ? { summary: d.summary ?? s.state.summary } : {}) });
      refreshJob(s.id);
      notifyStream(s);
    },
    error: async () => {
      s.close = null;
      if (s.done || s.reopenTries >= 3) {
        if (!s.done) { s.error = 'The live log stopped. Reload the page to try again.'; notifyStream(s); }
        return;
      }
      s.reopenTries += 1;
      // A closed stream is a new token (401), a gone job (404) or a restart.
      try {
        await getJob(s.id);
      } catch (e) {
        if (e.status === 404) { s.error = 'This job is not on record any more.'; notifyStream(s); return; }
        await rehello();
      }
      setTimeout(() => { if (s.subs.size) openStream(s); }, 1000 * s.reopenTries);
    },
  }, opts);
}

/** The buffered stream of one job; opens the SSE while a component watches it. */
export function useJobStream(jobId) {
  const [, force] = useReducer(x => x + 1, 0);
  useEffect(() => {
    if (!jobId) return undefined;
    let s = streams.get(jobId);
    if (!s) { s = newStream(jobId); streams.set(jobId, s); }
    if (s.idleTimer) { clearTimeout(s.idleTimer); s.idleTimer = null; }
    s.subs.add(force);
    const tryOpen = () => { if (token) openStream(s); else waitToken().then(t => { if (t && s.subs.size) openStream(s); }); };
    tryOpen();
    force();
    return () => {
      s.subs.delete(force);
      if (!s.subs.size) {
        // Keep the buffer; close the connection after a quiet minute.
        s.idleTimer = setTimeout(() => { if (!s.subs.size && s.close) { s.close(); s.close = null; } }, 60000);
      }
    };
  }, [jobId]);
  return jobId ? streams.get(jobId) || null : null;
}

/** Task lookup by id in the current catalog (hidden tasks included). */
export function findTask(catalog, id) {
  return (catalog?.tasks || []).find(t => t.id === id) || null;
}
