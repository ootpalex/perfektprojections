// node tgs-viz/control/test/guards.test.mjs
// Guards of DESIGN.md 8.3: loopback, Host with the request's port, Origin, token, content type, job ids.

import assert from 'node:assert/strict'
import path from 'node:path'
import os from 'node:os'
import {
  isLoopback, hostOk, originOk, tokenOk, contentTypeOk, jobDirFor, isJobId,
  checkRequest, checkPostHeaders, MAX_BODY,
} from '../guards.js'

let passed = 0
let failed = 0
function check(name, fn) {
  try { fn(); passed++ } catch (err) { failed++; console.log(`FAIL ${name}: ${err.message}`) }
}

// 1. loopback
for (const a of ['127.0.0.1', '::1', '::ffff:127.0.0.1']) check(`loopback ${a}`, () => assert.equal(isLoopback(a), true))
for (const a of ['192.168.1.5', '10.0.0.1', '::ffff:192.168.1.5', '127.0.0.2', '', undefined, null]) {
  check(`not loopback ${a}`, () => assert.equal(isLoopback(a), false))
}

// 2. Host uses the port the request came in on, never a fixed 3000
check('host localhost', () => assert.equal(hostOk('localhost:3101', 3101), true))
check('host 127', () => assert.equal(hostOk('127.0.0.1:3101', 3101), true))
check('host ::1', () => assert.equal(hostOk('[::1]:3101', 3101), true))
check('host case', () => assert.equal(hostOk('LocalHost:3101', 3101), true))
check('host other port', () => assert.equal(hostOk('localhost:3000', 3101), false))
check('host no port', () => assert.equal(hostOk('localhost', 3101), false))
check('host other name', () => assert.equal(hostOk('evil.com:3101', 3101), false))
check('host rebinding name', () => assert.equal(hostOk('localhost.evil.com:3101', 3101), false))
check('host missing', () => assert.equal(hostOk(undefined, 3101), false))
check('host with port 3000 server', () => assert.equal(hostOk('localhost:3000', 3000), true))

// 3. Origin exact match
check('origin same', () => assert.equal(originOk('http://localhost:3101', undefined, 3101), true))
check('origin 127', () => assert.equal(originOk('http://127.0.0.1:3101', undefined, 3101), true))
check('origin ::1', () => assert.equal(originOk('http://[::1]:3101', undefined, 3101), true))
check('origin 5173 fails', () => assert.equal(originOk('http://localhost:5173', undefined, 3101), false))
check('origin https fails', () => assert.equal(originOk('https://localhost:3101', undefined, 3101), false))
check('origin null fails', () => assert.equal(originOk('null', undefined, 3101), false))
check('origin trailing slash fails', () => assert.equal(originOk('http://localhost:3101/', undefined, 3101), false))
check('origin subdomain fails', () => assert.equal(originOk('http://a.localhost:3101', undefined, 3101), false))
check('no origin, no fetch site', () => assert.equal(originOk(undefined, undefined, 3101), true))
check('no origin, same-origin', () => assert.equal(originOk(undefined, 'same-origin', 3101), true))
check('no origin, cross-site fails', () => assert.equal(originOk(undefined, 'cross-site', 3101), false))
check('no origin, same-site fails', () => assert.equal(originOk(undefined, 'same-site', 3101), false))
check('no origin, none fails', () => assert.equal(originOk(undefined, 'none', 3101), false))

// 4. token
check('token ok', () => assert.equal(tokenOk('abc123', 'abc123'), true))
check('token wrong', () => assert.equal(tokenOk('abc124', 'abc123'), false))
check('token length', () => assert.equal(tokenOk('abc', 'abc123'), false))
check('token missing', () => assert.equal(tokenOk(undefined, 'abc123'), false))
check('token empty server', () => assert.equal(tokenOk('', ''), false))

// 5. content type
check('ct json', () => assert.equal(contentTypeOk('application/json'), true))
check('ct json charset', () => assert.equal(contentTypeOk('application/json; charset=utf-8'), true))
check('ct form', () => assert.equal(contentTypeOk('application/x-www-form-urlencoded'), false))
check('ct text', () => assert.equal(contentTypeOk('text/plain'), false))
check('ct missing', () => assert.equal(contentTypeOk(undefined), false))
check('post headers 415', () => assert.equal(checkPostHeaders({ 'content-type': 'text/plain' }).status, 415))
check('post headers 413', () => assert.equal(checkPostHeaders({ 'content-type': 'application/json', 'content-length': String(MAX_BODY + 1) }).status, 413))
check('post headers ok', () => assert.equal(checkPostHeaders({ 'content-type': 'application/json', 'content-length': '20' }), null))

// 6. job ids
const jobsDir = path.join(os.tmpdir(), 'tgs-guards-test', 'jobs')
const GOOD = '20261001-210000-get_ratings-ab12'
check('id good', () => assert.equal(jobDirFor(jobsDir, GOOD), path.resolve(jobsDir, GOOD)))
check('id dotted task', () => assert.ok(jobDirFor(jobsDir, '20261001-210000-update.TGS-0f0f')))
check('id selftest', () => assert.ok(isJobId('20261001-210000-selftest.long-0000')))
for (const bad of [
  '..', '../..', 'a/b', '..\\..', '20261001-210000-x-ab12/../..', '20261001-x-ab12', '-210000-x-ab12',
  '2026100-210000-x-ab12', '20261001-21000-x-ab12', '20261001-210000--ab12', '20261001-210000-x-AB12',
  '20261001-210000-x-ab1', '20261001-210000-a/b-ab12', '20261001-210000-x-ab12 ', '', null, undefined,
]) {
  check(`id bad ${bad}`, () => assert.equal(jobDirFor(jobsDir, bad), null))
}

// checkRequest end to end
const base = { remoteAddress: '127.0.0.1', localPort: 3101, headers: { host: 'localhost:3101' }, query: {} }
check('request ok with token', () => assert.equal(checkRequest({ ...base, headers: { ...base.headers, 'x-tgs-token': 't0k' } }, { token: 't0k', needToken: true }), null))
check('request 401 without token', () => assert.equal(checkRequest(base, { token: 't0k', needToken: true }).status, 401))
check('request ping without token', () => assert.equal(checkRequest(base, { token: 't0k', needToken: false }), null))
check('request 403 remote', () => assert.equal(checkRequest({ ...base, remoteAddress: '192.168.0.9' }, { token: 't0k', needToken: false }).status, 403))
check('request 403 host', () => assert.equal(checkRequest({ ...base, headers: { host: 'localhost:3000' } }, { token: 't0k', needToken: false }).status, 403))
check('request 403 origin before token', () => assert.equal(checkRequest({ ...base, headers: { ...base.headers, origin: 'http://localhost:5173', 'x-tgs-token': 't0k' } }, { token: 't0k', needToken: true }).status, 403))
check('request 403 cross-site', () => assert.equal(checkRequest({ ...base, headers: { ...base.headers, 'sec-fetch-site': 'cross-site', 'x-tgs-token': 't0k' } }, { token: 't0k', needToken: true }).status, 403))
check('request query token only for SSE', () => assert.equal(checkRequest({ ...base, query: { t: 't0k' } }, { token: 't0k', needToken: true }).status, 401))
check('request query token SSE', () => assert.equal(checkRequest({ ...base, query: { t: 't0k' } }, { token: 't0k', needToken: true, tokenInQuery: true }), null))

console.log(`guards: ${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
