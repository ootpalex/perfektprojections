// Node test for src/lib/inputConditions.js (DESIGN 4.4, 10.2, 15.3 step 1).
// Run: node tgs-viz/tests/client/inputConditions.test.mjs
// It reads A's shared cases (tools/tests/fixtures/conditions_cases.json) and
// skips them with a message when that file is missing.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  evalCondition, visibleInputs, startConflict, checkSecret, checkToken, checkInputValue, conflictText,
} from '../../src/lib/inputConditions.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const CASES = path.resolve(here, '../../tools/tests/fixtures/conditions_cases.json');

let passed = 0;
let failed = 0;
let skipped = 0;
function test(name, fn) {
  try { fn(); passed += 1; console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message.split('\n').join('\n     ')}`); }
}

// ---- shared cases ---------------------------------------------------------
if (fs.existsSync(CASES)) {
  const cases = JSON.parse(fs.readFileSync(CASES, 'utf8'));
  const list = Array.isArray(cases) ? cases : (cases.cases || []);
  for (const c of list) {
    if (c.python_only) { skipped += 1; continue; }
    test(`shared: ${c.name}`, () => {
      const got = evalCondition(c.condition, { state: c.state || {}, inputs: c.inputs || {}, flags: c.flags || {} });
      assert.equal(got, c.expect);
    });
  }
} else {
  console.log(`skip shared cases: ${CASES} is missing (A has not written it yet)`);
}

// ---- Get StatsPlus Ratings cookie inputs (4.3) ------------------------------
const SID_WHEN = { any: [{ no_token: 'TGS' }, { no_token: 'BLM' }] };
const CSRF_WHEN = {
  all: [
    { any: [{ no_token: 'TGS' }, { no_token: 'BLM' }] },
    { any: [{ all: [{ no_token: 'TGS' }, { no_token: 'BLM' }] }, { input_nonblank: 'sessionid' }] },
  ],
};
const STATES = {
  both: { TGS: true, BLM: true },
  tgs_only: { TGS: true, BLM: false },
  blm_only: { TGS: false, BLM: true },
  none: { TGS: false, BLM: false },
};
// expected [sessionid asked, csrftoken asked with sid blank, csrftoken asked with sid given]
const EXPECT = {
  both: [false, false, false],
  tgs_only: [true, false, true],
  blm_only: [true, false, true],
  none: [true, true, true],
};
for (const [state, tokens] of Object.entries(STATES)) {
  test(`get_ratings cookies, tokens ${state}`, () => {
    const [sid, csrfBlank, csrfGiven] = EXPECT[state];
    assert.equal(evalCondition(SID_WHEN, { state: { tokens }, inputs: {} }), sid, 'sessionid');
    assert.equal(evalCondition(CSRF_WHEN, { state: { tokens }, inputs: { sessionid: '' } }), csrfBlank, 'csrftoken, sid blank');
    assert.equal(evalCondition(CSRF_WHEN, { state: { tokens }, inputs: { sessionid: 'abcdefgh123' } }), csrfGiven, 'csrftoken, sid given');
  });
}

test('visibleInputs follows ask_when and leaves out console-only inputs', () => {
  const task = {
    inputs: [
      { name: 'sessionid', type: 'secret', ask_when: SID_WHEN },
      { name: 'csrftoken', type: 'secret', ask_when: CSRF_WHEN },
      { name: 'runs', type: 'text', ask_when: null },
      { name: 'console_only', type: 'confirm', modes: ['console'] },
    ],
  };
  const names = (tokens, inputs) => visibleInputs(task, { state: { tokens }, inputs }).map(i => i.name);
  assert.deepEqual(names(STATES.both, {}), ['runs']);
  assert.deepEqual(names(STATES.tgs_only, {}), ['sessionid', 'runs']);
  assert.deepEqual(names(STATES.tgs_only, { sessionid: 'abcdefgh123' }), ['sessionid', 'csrftoken', 'runs']);
  assert.deepEqual(names(STATES.none, {}), ['sessionid', 'csrftoken', 'runs']);
});

// ---- the condition table (4.4) ---------------------------------------------
test('no_token_input for each league choice', () => {
  const ctx = (league) => ({ state: { tokens: { TGS: true, BLM: false } }, inputs: { league } });
  assert.equal(evalCondition({ no_token_input: 'league' }, ctx('TGS')), false);
  assert.equal(evalCondition({ no_token_input: 'league' }, ctx('BLM')), true);
  assert.equal(evalCondition({ no_token_input: 'league' }, ctx('tgs')), false, 'case does not matter');
  assert.equal(evalCondition({ no_token_input: 'league' }, ctx('')), true, 'no league picked yet');
});

test('input_nonblank, not, all, any, null', () => {
  assert.equal(evalCondition({ input_nonblank: 'x' }, { inputs: { x: '  ' } }), false);
  assert.equal(evalCondition({ input_nonblank: 'x' }, { inputs: { x: ' a ' } }), true);
  assert.equal(evalCondition({ not: { input_nonblank: 'x' } }, { inputs: {} }), true);
  assert.equal(evalCondition({ all: [] }, {}), true);
  assert.equal(evalCondition({ any: [] }, {}), false);
  assert.equal(evalCondition(null, {}), true);
  assert.equal(evalCondition({ flag: 'stopafter' }, { flags: { stopafter: true } }), true);
});

// ---- input checks ----------------------------------------------------------
test('secrets: blank allowed unless required, 8+ characters, one line', () => {
  assert.equal(checkSecret(''), '');
  assert.notEqual(checkSecret('', true), '');
  assert.notEqual(checkSecret('12345'), '', '5 characters are refused');
  assert.equal(checkSecret('12345678'), '');
  assert.notEqual(checkSecret('abcdefgh\nijk'), '');
  assert.notEqual(checkSecret('x'.repeat(4097)), '');
});

test('token shape 20 to 80 of [A-Za-z0-9_-]', () => {
  assert.equal(checkToken(''), '');
  assert.notEqual(checkToken('', true), '');
  assert.notEqual(checkToken('short'), '');
  assert.equal(checkToken('a'.repeat(36)), '');
  assert.notEqual(checkToken('a'.repeat(30) + '!'), '');
});

test('a required secret never says "or leave it blank"; a token secret gets the token check', () => {
  assert.ok(!checkSecret('12345', true).includes('blank'));
  assert.ok(checkSecret('12345').includes('blank'));
  const tok = { type: 'secret', required: true, format: 'statsplus_token' };
  assert.notEqual(checkInputValue(tok, 'abcdefghij'), '', 'a 10-character token is refused');
  assert.notEqual(checkInputValue(tok, ''), '');
  assert.notEqual(checkInputValue(tok, 'a'.repeat(36) + '\n'), '');
  assert.equal(checkInputValue(tok, 'a'.repeat(36)), '');
  assert.equal(checkInputValue({ type: 'secret' }, 'abcdefghij'), '');
});

test('text inputs: int range, equals, required choice, required confirm', () => {
  assert.notEqual(checkInputValue({ type: 'text', format: 'int', min: 1, max: 50 }, '0'), '');
  assert.notEqual(checkInputValue({ type: 'text', format: 'int', min: 1, max: 50 }, '5x'), '');
  assert.equal(checkInputValue({ type: 'text', format: 'int', min: 1, max: 50 }, '10'), '');
  assert.notEqual(checkInputValue({ type: 'text', equals: 'XY', required: true }, 'xy'), '');
  assert.equal(checkInputValue({ type: 'text', equals: 'XY', required: true }, 'XY'), '');
  assert.notEqual(checkInputValue({ type: 'choice', required: true, choices: [{ value: 'TGS' }] }, ''), '');
  assert.equal(checkInputValue({ type: 'choice', required: true, choices: [{ value: 'TGS' }] }, 'TGS'), '');
  assert.notEqual(checkInputValue({ type: 'confirm', required: true }, false), '');
  assert.equal(checkInputValue({ type: 'confirm', required: true }, true), '');
});

// ---- startConflict (10.2) --------------------------------------------------
const grind = { id: 'grind_tgs', title: 'Grind TGS', locks: ['ootp', 'clones.TGS', 'task.grind_tgs'], flags: {}, steps: [{ data: false }, { data: true }] };
const recal = { id: 'recalibrate_tgs', title: 'Recalibrate TGS', locks: ['clones.TGS', 'task.recalibrate_tgs'], flags: {}, steps: [{ data: true }] };
const pull = { id: 'get_ratings', title: 'Get StatsPlus Ratings', locks: ['task.get_ratings'], flags: {}, steps: [{ data: true }] };
const draft = { id: 'draft_board', title: 'Update Draft Board', locks: ['task.draft_board'], flags: {}, steps: [{ data: true }] };
const report = { id: 'pull_report', title: 'Data date report', locks: [], flags: { read_only: true }, steps: [{ data: false }] };
const simOnly = { id: 'sim_tgs', title: 'Sim TGS', locks: ['ootp', 'clones.TGS'], flags: {}, steps: [{ data: false }] };

const running = (task, extra = {}) => ({ id: `j-${task.id}`, task: task.id, title: task.title, status: 'running', locks_held: [...task.locks], data_lock: null, ...extra });

test('startConflict: free when nothing runs', () => {
  assert.equal(startConflict(pull, []), null);
});

test('startConflict: conflict on a shared whole-run lock', () => {
  const c = startConflict(recal, [running(grind)]);
  assert.equal(c.kind, 'conflict');
  assert.equal(c.lock, 'clones.TGS');
  assert.equal(conflictText(c), 'Grind TGS is running (it uses the TGS clone saves).');
  const c2 = startConflict(simOnly, [running(grind)]);
  assert.equal(c2.lock, 'ootp');
  assert.equal(conflictText(c2), 'Grind TGS is running (it uses OOTP and your mouse).');
});

test('startConflict: the same task again is a conflict on task.<id>', () => {
  const c = startConflict(pull, [running(pull, { locks_held: ['task.get_ratings', 'data'], data_lock: 'held' })]);
  assert.equal(c.kind, 'conflict');
  assert.equal(c.lock, 'task.get_ratings');
});

test('startConflict: a summary without locks_held still blocks the same task', () => {
  const c = startConflict(pull, [{ id: 'x', task: 'get_ratings', title: 'Get StatsPlus Ratings', status: 'running' }]);
  assert.equal(c.kind, 'conflict');
});

test('startConflict: waits when another job holds the data lock', () => {
  const c = startConflict(draft, [running(pull, { locks_held: ['task.get_ratings', 'data'], data_lock: 'held' })]);
  assert.equal(c.kind, 'waits');
  assert.equal(conflictText(c), 'Start (waits for Get StatsPlus Ratings)');
});

test('startConflict: queue_full when another job is queued', () => {
  const jobs = [
    running(pull, { locks_held: ['task.get_ratings', 'data'], data_lock: 'held' }),
    { ...running(recal), status: 'queued', data_lock: 'waiting' },
  ];
  const c = startConflict(draft, jobs);
  assert.equal(c.kind, 'queue_full');
  assert.equal(conflictText(c), 'Another task is already waiting. Start this one after it.');
});

test('startConflict: read-only tasks and data-free tasks are never held back by data', () => {
  const jobs = [running(pull, { locks_held: ['task.get_ratings', 'data'], data_lock: 'held' }), { ...running(draft), status: 'queued' }];
  assert.equal(startConflict(report, jobs), null);
  assert.equal(startConflict({ ...simOnly, id: 'sim_x', locks: ['ootp'] }, jobs), null);
});

test('startConflict: finished jobs are ignored', () => {
  assert.equal(startConflict(recal, [{ ...running(grind), status: 'done' }]), null);
});

console.log(`\ninputConditions: ${passed} passed, ${failed} failed, ${skipped} python-only skipped`);
process.exit(failed ? 1 : 0);
