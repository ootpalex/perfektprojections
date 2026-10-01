// Implementer C's test double for the Control API (DESIGN 8.3 to 8.9).
//
// It answers the /__tgs/ routes and the ws events the React side uses, with
// jobs simulated in memory. Selftest tasks follow DESIGN 4.9; any other task
// runs two harmless sleep steps. It never runs Python, never writes league
// data and never touches the network. Used only with vite.mock.config.js on
// the C test port.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { buildCatalog } from './catalog.js';

const FINAL = new Set(['done', 'partial', 'failed', 'stopped', 'killed', 'invalid', 'refused', 'lost']);
const JOB_ID_RE = /^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$/;

function stamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}
const iso = () => new Date().toISOString();

function sendJson(res, code, body) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(body));
}
const fail = (res, code, errCode, message, extra = {}) => sendJson(res, code, { error: { code: errCode, message, ...extra } });

function readBody(req) {
  return new Promise((resolve, reject) => {
    let buf = '';
    req.on('data', (c) => { buf += c; if (buf.length > 65536) reject(new Error('too big')); });
    req.on('end', () => { try { resolve(buf ? JSON.parse(buf) : {}); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}

export default function mockControl() {
  return {
    name: 'tgs-control-mock-c',
    apply: 'serve',
    configureServer(server) {
      const token = crypto.randomBytes(24).toString('hex');
      const selftest = process.env.TGS_SELFTEST === '1';
      const localPath = process.env.TGS_SETTINGS_LOCAL || null;
      const jobs = new Map();          // id -> job
      const locks = new Map();         // name -> job id
      const corrupt = new Set();       // public/data paths served as broken JSON
      const repoRoot = path.resolve(server.config.root, '..');
      const defaultsPath = path.join(server.config.root, 'tools', 'settings.defaults.json');

      // ---- settings --------------------------------------------------------
      function readLocal() {
        if (!localPath || !fs.existsSync(localPath)) return { exists: false, data: null, error: null };
        const text = fs.readFileSync(localPath, 'utf8');
        try { return { exists: true, data: JSON.parse(text), error: null, text }; } catch (e) {
          return { exists: true, data: null, error: `${path.basename(localPath)} is not valid JSON (${e.message}).`, text };
        }
      }
      function defaults() {
        try { return JSON.parse(fs.readFileSync(defaultsPath, 'utf8')); } catch {
          return {
            python: { main: ['python'], ml: ['py', '-3.14'] }, node: ['node'],
            ootp: { installs: { 26: { saved_games: 'C:/OOTP 26/data/saved_games' }, 27: { saved_games: '%USERPROFILE%/Documents/OOTP Baseball 27/saved_games' } } },
            leagues: { TGS: { name: 'TGS', my_team: 'Chicago Cubs', my_org: 'Chicago Cubs', ootp_save: 'TheGrandestSalami', ootp_version: '26' } },
          };
        }
      }
      const isObj = (o) => o && typeof o === 'object' && !Array.isArray(o);
      function merge(a, b) {
        const out = { ...a };
        for (const [k, v] of Object.entries(b || {})) out[k] = isObj(v) && isObj(a?.[k]) ? merge(a[k], v) : v;
        return out;
      }
      function merged() {
        const l = readLocal();
        return merge(defaults(), l.data || {});
      }
      function catalog() {
        const l = readLocal();
        const m = merged();
        const myOrg = {};
        for (const [id, lg] of Object.entries(m.leagues || {})) if (lg?.my_org) myOrg[id] = lg.my_org;
        return buildCatalog({ selftest, settingsError: l.error, settingsLocal: l.exists, myOrg });
      }
      const findTask = (id) => catalog().tasks.find(t => t.id === id) || null;

      // ---- broadcast -------------------------------------------------------
      const ws = (event, data) => { try { server.ws.send(event, data); } catch { /* no clients */ } };
      server.ws.on('tgs:hello', (_d, client) => {
        client.send('tgs:token', { token, port: server.httpServer?.address()?.port ?? null, api: 1 });
      });

      function summary(job) {
        const s = job.state;
        const cur = s.steps[s.current];
        return {
          id: s.id, task: s.task, title: s.title, mode: 'job', status: s.status,
          step: cur ? { index: s.current, total: s.steps.length, title: cur.title } : null,
          prompt: !!s.prompt, stop: s.stop ? s.stop.mode : null, stale: false, waiting_for: s.waiting_for, at: Date.now(),
        };
      }
      function emit(job, type, data) {
        job.seq += 1;
        const id = `e${job.seq}-l${job.log.length}`;
        for (const c of job.clients) c.write(`id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
        if (type === 'done') for (const c of job.clients) c.end();
        if (type === 'done') job.clients.clear();
      }
      function pushState(job) {
        emit(job, 'state', job.state);
        ws('tgs:job', summary(job));
      }
      function log(job, text) {
        if (job.partial) {
          // the held partial line comes again whole, from the same offset
          const off = job.partialAt;
          job.log = job.log.slice(0, off) + job.partial + text;
          job.partial = null;
          job.seq += 1;
          for (const c of job.clients) c.write(`id: e${job.seq}-l${job.log.length}\nevent: log\ndata: ${JSON.stringify({ text: job.log.slice(off), offset: off, partial: false })}\n\n`);
          return;
        }
        const off = job.log.length;
        job.log += text;
        job.seq += 1;
        for (const c of job.clients) c.write(`id: e${job.seq}-l${job.log.length}\nevent: log\ndata: ${JSON.stringify({ text, offset: off, partial: false })}\n\n`);
      }
      function logPartial(job, text) {
        job.partialAt = job.log.length;
        job.partial = text;
        job.seq += 1;
        for (const c of job.clients) c.write(`id: e${job.seq}-l${job.log.length}\nevent: log\ndata: ${JSON.stringify({ text, offset: job.partialAt, partial: true })}\n\n`);
      }
      const dataEvent = (league, files, reason) => ws('tgs:data', { league, keys: ['players'], files, at: Date.now(), reason });

      // ---- job engine ------------------------------------------------------
      class Killed extends Error {}
      function sleep(job, ms) {
        return new Promise((resolve, reject) => {
          const t = setTimeout(() => { job.sleeper = null; resolve(); }, ms);
          job.sleeper = () => { clearTimeout(t); job.sleeper = null; reject(new Killed()); };
        });
      }
      function ask(job, kind, text, details, choices, def) {
        const pid = `p${++job.promptN}`;
        job.state.prompt = { prompt_id: pid, kind, step_id: job.state.steps[job.state.current]?.id, title: job.state.title, text, details, choices, default: def, created: iso() };
        job.state.status = 'waiting';
        emit(job, 'prompt', job.state.prompt);
        pushState(job);
        return new Promise((resolve) => { job.answer = (v) => { job.answer = null; job.state.prompt = null; job.state.status = 'running'; pushState(job); resolve(v); }; });
      }

      // Each script step: async (job, ctx) => exit code
      function script(task, inputs, secrets) {
        const id = task.id;
        const L = (job, t) => log(job, t);
        const s = (ms) => async (job) => { await sleep(job, ms); L(job, `  slept ${ms / 1000} s\n`); return 0; };
        switch (id) {
          case 'selftest.ok':
            return [async (job) => {
              for (const l of ['  line 1', '  line 2 é', '  line 3 ✓', '  line 4', '  line 5']) L(job, `${l}\n`);
              logPartial(job, '  partial line ...');
              await sleep(job, 1000);
              L(job, ' done\n');
              return 0;
            }];
          case 'selftest.fail_collect':
            return [s(500), async (job) => { L(job, '  step 2 fails\n'); return 1; }, s(500)];
          case 'selftest.fail_fast':
            return [s(500), async (job) => { L(job, '  step 2 fails\n'); return 1; }, s(500)];
          case 'selftest.confirm':
          case 'selftest.confirm_zero':
            return [async (job) => {
              const n = id === 'selftest.confirm' ? 3 : 0;
              L(job, `  ${n} cell(s) will change\n`);
              if (!n) { L(job, '  Nothing to apply.\n'); return 0; }
              const v = await ask(job, 'confirm', 'Apply these changes to the test sheet?', [`  ${n} cell(s) will change`, '  A1: 1 -> 2', '  B2: x -> y', '  C3: 0 -> 5'], [{ id: 'yes', label: 'Apply' }, { id: 'no', label: 'Skip' }], 'no');
              L(job, v === 'yes' ? '  applied\n' : '  Skipped (not applied).\n');
              return 0;
            }];
          case 'selftest.gate':
            return [s(500), async (job) => {
              const v = await ask(job, 'gate', 'Paste the test data, save, and close Excel.', [], [{ id: 'continue', label: 'Continue' }, { id: 'stop', label: 'Stop' }], 'stop');
              if (v === 'stop') { job.stopNow = true; return 0; }
              L(job, '  continued\n');
              return 0;
            }, s(500)];
          case 'selftest.long':
            return Array.from({ length: 6 }, () => s(20000));
          case 'selftest.loop':
            return [s(5000), s(5000)];
          case 'selftest.secret':
            return [async (job) => {
              const v = secrets.token || '';
              L(job, `  secret received: ${v ? 'yes' : 'no'}, length ${v.length}\n`);
              L(job, '  ****\n');
              logPartial(job, '  **');
              await sleep(job, 200);
              L(job, '**\n');
              return 0;
            }];
          case 'selftest.touch':
            return [async (job) => {
              const file = String(inputs.file || 'TGS/r5.json');
              L(job, `  touched ${file} (mock: same bytes, nothing written)\n`);
              job.touched = file;
              return 0;
            }];
          case 'selftest.corrupt':
            return [async (job) => {
              const rel = 'RG/iafa.json';
              corrupt.add(rel);
              L(job, `  ${rel} now reads as [{bad\n`);
              dataEvent('RG', [rel], 'watch');
              await sleep(job, 8000);
              corrupt.delete(rel);
              L(job, `  ${rel} restored\n`);
              dataEvent('RG', [rel], 'watch');
              return 0;
            }];
          case 'selftest.stdin':
            return [async (job) => { L(job, '  skipped (no answer)\n'); return 0; }];
          case 'selftest.hands_off':
            return [async (job) => {
              for (let n = 5; n >= 1; n -= 1) {
                emit(job, 'message', { level: 'countdown', text: `Hands off: OOTP starts in ${n}` });
                await sleep(job, 1000);
              }
              L(job, '  clicked nothing\n');
              await sleep(job, 1000);
              return 0;
            }];
          case 'selftest.leagues':
            return [s(1000), s(1000), s(1000), s(1000)];
          default:
            return [async (job) => { L(job, `  mock: ${task.title} is simulated here; nothing ran.\n`); await sleep(job, 1500); return 0; }, s(1500)];
        }
      }

      function needsData(task) { return !task.flags?.read_only && (task.steps || []).some(s => s.data !== false); }
      function wholeLocks(task) {
        if (task.flags?.read_only) return [];
        return [...new Set([...(task.locks || []), `task.${task.id}`])].filter(l => l !== 'data');
      }

      async function run(job, task, inputs, secrets) {
        const s = job.state;
        const steps = script(task, inputs, secrets);
        s.steps = (task.steps.length === steps.length ? task.steps : steps.map((_, i) => ({ id: `s${i + 1}`, title: `Step ${i + 1}` })))
          .map((st, i) => ({ index: i, id: st.id, title: st.title, status: 'pending', exit: null, started: null, ended: null, tag: null, writes_app_data: !!st.writes_app_data }));
        const policy = task.id === 'selftest.fail_collect' ? 'collect' : 'fail';
        const endless = !!task.flags?.endless;
        let cycle = 0;
        try {
          // data lock: wait as queued when another job holds it
          if (needsData(task)) {
            while (locks.has('data') && locks.get('data') !== s.id) {
              const holder = jobs.get(locks.get('data'));
              if (s.status !== 'queued') {
                s.status = 'queued';
                s.data_lock = 'waiting';
                s.waiting_for = { job_id: holder.state.id, title: holder.state.title, lock: 'data' };
                pushState(job);
              }
              if (job.stopMode) { s.status = 'stopped'; throw new Error('stopped while queued'); }
              await new Promise(r => setTimeout(r, 300));
            }
            locks.set('data', s.id);
            s.locks_held.push('data');
            s.data_lock = 'held';
            s.waiting_for = null;
          }
          s.status = 'running';
          pushState(job);
          do {
            cycle += 1;
            if (endless) { s.cycle = cycle; emit(job, 'step', { type: 'cycle_start', cycle }); if (cycle > 1) s.steps.forEach(st => { st.status = 'pending'; st.exit = null; }); }
            for (let i = 0; i < steps.length; i += 1) {
              if (job.stopMode === 'after_step' || job.stopNow) { s.status = 'stopped'; break; }
              const st = s.steps[i];
              s.current = i;
              st.status = 'running';
              st.started = iso();
              pushState(job);
              let code;
              try {
                code = await steps[i](job);
              } catch (e) {
                if (e instanceof Killed) { st.status = 'killed'; st.ended = iso(); s.status = 'killed'; log(job, '  Killed.\n'); break; }
                throw e;
              }
              st.exit = code;
              st.ended = iso();
              st.status = code === 0 ? 'ok' : 'failed';
              emit(job, 'step', { type: 'step_end', index: i, step_id: st.id, status: st.status, exit: code });
              if (code !== 0) {
                if (policy === 'collect') { s.fails.push(`T${i + 1}`); st.tag = `T${i + 1}`; } else { s.status = 'failed'; break; }
              }
              pushState(job);
            }
            if (FINAL.has(s.status)) break;
            if (job.stopMode === 'after_cycle' || job.stopMode === 'after_step' || job.stopNow) { s.status = 'stopped'; break; }
          } while (endless);
          if (!FINAL.has(s.status)) s.status = s.fails.length ? 'partial' : 'done';
        } catch (e) {
          if (!FINAL.has(s.status)) { s.status = 'failed'; s.message = e.message; }
        } finally {
          for (const st of s.steps) if (st.status === 'pending' || st.status === 'running') st.status = 'skipped';
          s.ended = iso();
          s.current = null;
          s.prompt = null;
          s.exit_code = s.status === 'failed' ? 1 : s.status === 'killed' ? 4 : 0;
          if (s.fails.length) s.summary = [`Steps that did not update: ${s.fails.join(', ')}`];
          else if (s.status === 'done') s.summary = ['All steps finished.'];
          else if (s.status === 'stopped') s.summary = ['Stopped. The steps after the stop did not run.'];
          for (const [name, holder] of [...locks]) if (holder === s.id) locks.delete(name);
          s.locks_held = [];
          s.data_lock = null;
          s.pending_leagues = [];
          pushState(job);
          emit(job, 'done', { status: s.status, exit_code: s.exit_code, fails: s.fails, summary: s.summary });
          if (job.touched) {
            const lg = job.touched.split('/')[0];
            dataEvent(lg, [job.touched], 'league_done');
          }
          setTimeout(() => ws('tgs:catalog', { at: Date.now() }), 50);
        }
      }

      function startJob(taskId, inputs, secrets) {
        const task = findTask(taskId);
        const id = `${stamp()}-${taskId}-${crypto.randomBytes(2).toString('hex')}`;
        const state = {
          schema: 1, id, task: taskId, title: task.title, mode: 'job', status: 'starting', pid: process.pid, pid_started: 0,
          started: iso(), ended: null, inputs, secrets_given: Object.keys(secrets), steps: [], current: null, cycle: null,
          fails: [], prompt: null, stop: null, locks_held: [], data_lock: null, waiting_for: null, pending_leagues: [],
          message: null, fix_task: null, summary: [], exit_code: null,
        };
        const job = { state, log: '', seq: 0, clients: new Set(), promptN: 0, answer: null, sleeper: null, stopMode: null, partial: null };
        jobs.set(id, job);
        for (const l of wholeLocks(task)) { locks.set(l, id); state.locks_held.push(l); }
        run(job, task, inputs, secrets);
        return job;
      }

      // ---- routes ----------------------------------------------------------
      // Broken data files for the corrupt test (before Vite's static files).
      server.middlewares.use('/data', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\//, '');
        if (corrupt.has(rel)) {
          res.setHeader('Content-Type', 'application/json');
          res.end('[{bad');
          return;
        }
        next();
      });

      server.middlewares.use('/__tgs', async (req, res) => {
        try {
          const url = new URL(req.url, 'http://x');
          const p = url.pathname;
          const method = req.method;
          if (p === '/ping') {
            return sendJson(res, 200, { ok: true, api: 1, control: { on: true }, python: { ok: true, argv: ['python'], version: '3.13.14 (mock)' }, live_refresh: true });
          }
          const tok = req.headers['x-tgs-token'] || url.searchParams.get('t');
          if (tok !== token) return fail(res, 401, 'bad_token', 'The page token is out of date.');

          if (p === '/catalog' && method === 'GET') return sendJson(res, 200, catalog());
          if (p === '/config' && method === 'GET') return sendJson(res, 200, catalog().app_config);
          if (p === '/jobs/active' && method === 'GET') {
            return sendJson(res, 200, { jobs: [...jobs.values()].filter(j => !FINAL.has(j.state.status)).map(j => j.state) });
          }
          if (p === '/jobs' && method === 'GET') {
            const limit = Math.min(100, Math.max(1, parseInt(url.searchParams.get('limit') || '20', 10) || 20));
            return sendJson(res, 200, { jobs: [...jobs.values()].map(j => j.state).reverse().slice(0, limit) });
          }
          if (p === '/jobs' && method === 'POST') {
            const body = await readBody(req);
            const task = findTask(body.task);
            if (!task) return fail(res, 404, 'unknown_task', `No task named ${body.task}.`);
            const inputs = body.inputs || {};
            const secrets = body.secrets || {};
            for (const k of Object.keys(inputs)) {
              if ((task.inputs || []).some(i => i.name === k && i.type === 'secret')) return fail(res, 400, 'secret_in_inputs', 'A secret came in the inputs.');
            }
            for (const [k, v] of Object.entries(secrets)) {
              const known = (task.inputs || []).some(i => i.type === 'secret' && i.name.toLowerCase() === k.toLowerCase());
              const t = String(v).trim();
              if (!known || /[\r\n\0]/.test(v) || (t && t.length < 8)) return fail(res, 400, 'bad_secret', `The value for ${k} is not accepted.`, { field: k });
            }
            if (task.id === 'selftest.archive') {
              return fail(res, 400, 'invalid_input', 'The ratings archive is missing. Rebuild it first: Control, Setup check, Rebuild ratings archive.', { errors: {}, fix_task: 'restore_ratings_db' });
            }
            for (const l of wholeLocks(task)) {
              if (locks.has(l)) {
                const holder = jobs.get(locks.get(l));
                return fail(res, 409, 'conflict', `${holder.state.title} is running.`, { job: { id: holder.state.id, title: holder.state.title }, lock: l });
              }
            }
            if (needsData(task) && [...jobs.values()].some(j => j.state.status === 'queued')) {
              return fail(res, 409, 'queue_full', 'Another task is already waiting.');
            }
            const job = startJob(task.id, inputs, secrets);
            await new Promise(r => setTimeout(r, 150));
            return sendJson(res, 201, { job: job.state });
          }
          const m = p.match(/^\/jobs\/([^/]+)(\/[a-z]+)?$/);
          if (m) {
            const id = decodeURIComponent(m[1]);
            const job = JOB_ID_RE.test(id) ? jobs.get(id) : null;
            if (!job) return fail(res, 404, 'no_job', 'No such job.');
            const sub = m[2] || '';
            if (!sub && method === 'GET') return sendJson(res, 200, { job: job.state });
            if (sub === '/log' && method === 'GET') {
              const from = parseInt(url.searchParams.get('from') || '0', 10) || 0;
              res.setHeader('Content-Type', 'text/plain; charset=utf-8');
              res.setHeader('X-TGS-Next-Offset', String(job.log.length));
              return res.end(job.log.slice(from));
            }
            if (sub === '/events' && method === 'GET') {
              res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
              res.write('retry: 2000\n\n');
              const last = req.headers['last-event-id'] || url.searchParams.get('from') || '';
              const lm = String(last).match(/-l(\d+)$/);
              let from = lm ? parseInt(lm[1], 10) : Math.max(0, job.log.length - (parseInt(url.searchParams.get('tail') || '262144', 10) || 262144));
              if (!lm && from > 0) { const nl = job.log.indexOf('\n', from); from = nl >= 0 ? nl + 1 : job.log.length; }
              res.write(`event: hello\ndata: ${JSON.stringify({ job_id: id, cursor: `e${job.seq}-l${from}` })}\n\n`);
              if (job.log.length > from) res.write(`id: e${job.seq}-l${job.log.length}\nevent: log\ndata: ${JSON.stringify({ text: job.log.slice(from), offset: from, partial: false })}\n\n`);
              if (job.partial) res.write(`id: e${job.seq}-l${job.log.length}\nevent: log\ndata: ${JSON.stringify({ text: job.partial, offset: job.partialAt, partial: true })}\n\n`);
              res.write(`id: e${job.seq}-l${job.log.length}\nevent: state\ndata: ${JSON.stringify(job.state)}\n\n`);
              if (FINAL.has(job.state.status)) {
                res.write(`id: e${job.seq}-l${job.log.length}\nevent: done\ndata: ${JSON.stringify({ status: job.state.status, exit_code: job.state.exit_code, fails: job.state.fails, summary: job.state.summary })}\n\n`);
                return res.end();
              }
              if (job.state.prompt) res.write(`event: prompt\ndata: ${JSON.stringify(job.state.prompt)}\n\n`);
              job.clients.add(res);
              const ping = setInterval(() => res.write(': ping\n\n'), 15000);
              req.on('close', () => { clearInterval(ping); job.clients.delete(res); });
              return undefined;
            }
            if (sub === '/answer' && method === 'POST') {
              const body = await readBody(req);
              if (!job.state.prompt || !job.answer) return fail(res, 409, 'no_prompt', 'The task is not waiting for an answer.');
              if (body.prompt_id !== job.state.prompt.prompt_id) return fail(res, 409, 'prompt_mismatch', 'That question was already answered.');
              if (!job.state.prompt.choices.some(c => c.id === body.value)) return fail(res, 400, 'bad_value', 'Not one of the choices.');
              emit(job, 'step', { type: 'answer', prompt_id: body.prompt_id, value: body.value });
              job.answer(body.value);
              return sendJson(res, 200, { ok: true });
            }
            if (sub === '/stop' && method === 'POST') {
              const body = await readBody(req);
              if (FINAL.has(job.state.status)) return fail(res, 409, 'not_running', 'The task has ended.');
              const task = findTask(job.state.task);
              if (!['after_step', 'after_cycle', 'kill'].includes(body.mode) || (body.mode === 'after_cycle' && !task?.flags?.endless)) {
                return fail(res, 400, 'bad_mode', 'That stop is not possible for this task.');
              }
              job.stopMode = body.mode;
              job.state.stop = { mode: body.mode, requested_at: iso() };
              emit(job, 'step', { type: 'stop_requested', mode: body.mode });
              if (job.answer) job.answer(job.state.prompt?.choices?.find(c => /no|stop|skip/i.test(c.id))?.id || 'no');
              if (body.mode === 'kill' && job.sleeper) job.sleeper();
              if (body.mode === 'kill' && !job.sleeper) job.stopNow = true;
              pushState(job);
              return sendJson(res, 202, { ok: true });
            }
          }
          if (p === '/doctor' && method === 'GET') {
            await new Promise(r => setTimeout(r, 600));
            const l = readLocal();
            return sendJson(res, 200, {
              schema: 1, ok: !l.error,
              checks: [
                { id: 'python.main', title: 'Python (main)', status: 'ok', detail: '3.13.14 (python)', fix: '', task: null },
                { id: 'node', title: 'Node.js', status: 'ok', detail: process.version, fix: '', task: null },
                { id: 'settings', title: 'Settings', status: l.error ? 'fail' : 'ok', detail: l.error || 'both files read fine', fix: l.error ? 'Or press Reset local settings on the Setup page.' : '', task: null },
                { id: 'ratings_db', title: 'Ratings archive', status: 'warn', detail: 'missing while vintages exist (mock)', fix: 'Rebuild it from the saved vintages.', task: 'restore_ratings_db' },
                { id: 'ml_models', title: 'ML dev models', status: 'warn', detail: 'no model files (mock)', fix: 'The app uses the older cell method until Bank Dev Seasons trains the models.', task: null },
                { id: 'tokens', title: 'StatsPlus tokens', status: 'ok', detail: 'TGS present, BLM present', fix: '', task: null },
              ],
            });
          }
          if (p === '/settings' && method === 'GET') {
            const l = readLocal();
            if (l.error) return fail(res, 503, 'python_failed', l.error);
            return sendJson(res, 200, { merged: merged(), local: l.data, paths: { defaults: defaultsPath, local: localPath || path.join(repoRoot, 'settings.local.json') } });
          }
          if (p === '/settings' && method === 'POST') {
            const body = await readBody(req);
            const patch = body.patch || {};
            if ([...jobs.values()].some(j => !FINAL.has(j.state.status))) return fail(res, 409, 'busy', 'A task is running.');
            const main = patch.python?.main;
            if (Array.isArray(main) && /nope/i.test(main.join(' '))) {
              return fail(res, 400, 'bad_interpreter', 'That command did not start.', { argv: main, output: `[WinError 2] The system cannot find the file specified: '${main[0]}'` });
            }
            if (!localPath) return fail(res, 400, 'invalid', 'The mock writes settings only with TGS_SETTINGS_LOCAL set.', { errors: ['No local settings path in this test server.'] });
            const l = readLocal();
            const next = merge(l.data || {}, patch);
            fs.writeFileSync(localPath, JSON.stringify(next, null, 2));
            ws('tgs:catalog', { at: Date.now() });
            return sendJson(res, 200, { ok: true, merged: merged() });
          }
          if (p === '/settings/reset-local' && method === 'POST') {
            if (!localPath || !fs.existsSync(localPath)) return fail(res, 404, 'no_local_file', 'There is no local settings file.');
            if ([...jobs.values()].some(j => !FINAL.has(j.state.status))) return fail(res, 409, 'busy', 'A task is running.');
            const to = path.join(path.dirname(localPath), `settings.local.bad-${stamp()}.json`);
            fs.renameSync(localPath, to);
            ws('tgs:catalog', { at: Date.now() });
            return sendJson(res, 200, { ok: true, renamed_to: to });
          }
          if (p === '/new-league/options' && method === 'GET') {
            const type = url.searchParams.get('type');
            const version = url.searchParams.get('version');
            if (!['statsplus', 'local_export', 'dev', 'clone'].includes(type) || (version && !/^\d{2}$/.test(version))) {
              return fail(res, 400, 'bad_query', 'Bad type or version.');
            }
            const saves = version === '26'
              ? ['TheGrandestSalami', { name: '0tgs1', clone: true }, 'Baseline']
              : ['Regular Game', 'BLM', 'DEV TESTS', 'new game', { name: 'No Export Save' }];
            return sendJson(res, 200, {
              versions: [{ version: '26', saved_games: 'C:/OOTP 26/data/saved_games', exists: true }, { version: '27', saved_games: 'C:/Users/x/Documents/OOTP Baseball 27/saved_games', exists: true }],
              saves: version ? saves : [],
              bases: ['TGS', 'BLM'],
            });
          }
          if (p === '/new-league/validate' && method === 'POST') {
            const body = await readBody(req);
            const f = body.fields || {};
            const errors = {};
            const id = String(f.id || '');
            if (!/^[A-Z0-9]{2,8}$/.test(id)) errors.id = 'Use 2 to 8 capital letters or digits.';
            else if (/^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])$/.test(id)) errors.id = 'Windows reserves this name. Pick another id.';
            else if (['TGS', 'BLM', 'DEV', 'RG'].includes(id)) errors.id = 'This id was used before. Pick another id.';
            if (body.type === 'local_export' && f.ootp_save === 'No Export Save') {
              errors.ootp_save = 'This save has no database export (import_export/csv/players.csv). Export it in OOTP first.';
            }
            const warnings = body.type === 'dev' ? ['Turn on Export CSV files after each simulated season in this league'] : [];
            return sendJson(res, 200, {
              ok: !Object.keys(errors).length, errors, warnings,
              plan: [{ title: 'Check the fields', writes: [] }, { title: 'Add the league to settings.local.json', writes: ['settings.local.json'] }, { title: 'First update', writes: [`public/data/${id}/`] }],
            });
          }
          return fail(res, 404, 'not_found', 'No such route.');
        } catch (e) {
          return fail(res, 500, 'internal', String(e.message || e));
        }
      });
    },
  };
}
