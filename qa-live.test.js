/**
 * Live integration QA — loads the REAL static/index.html in jsdom and points its
 * fetch() at the running mock server over real HTTP. Exercises the true network
 * path: real status codes, real JSON bodies, real Web Crypto verification.
 *
 * Run (start the mock first):
 *   npm install --no-save --prefix /tmp/jstest jsdom
 *   node qa-mock-preview.mjs &
 *   node qa-live.test.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { JSDOM, VirtualConsole } = require('/tmp/jstest/node_modules/jsdom');

const BASE = 'http://localhost:8080';
const HTML = fs.readFileSync(path.resolve(__dirname, 'static/index.html'), 'utf8');

let pass = 0, fail = 0;
const failures = [];
function ok(n, c, x) {
  if (c) { pass++; console.log('  \x1b[32mPASS\x1b[0m ' + n); }
  else { fail++; failures.push(n); console.log('  \x1b[31mFAIL\x1b[0m ' + n + (x ? '\n        -> ' + x : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

function makeDom(preset) {
  const pageErrors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => { if (!/Not implemented/.test(e.message)) pageErrors.push(e.message); });
  const dom = new JSDOM(HTML, {
    url: BASE + '/static/index.html',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      Object.defineProperty(window, 'crypto', { value: crypto.webcrypto, configurable: true });
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
      window.TextEncoder = TextEncoder;
      window.TextDecoder = TextDecoder;
      window.AbortController = AbortController;
      window.Element.prototype.scrollIntoView = function () {};
      // REAL fetch — only relative URLs are absolutised.
      window.fetch = (u, init) => globalThis.fetch(new URL(u, BASE).href, init);
      if (preset) Object.keys(preset).forEach(k => window.localStorage.setItem(k, preset[k]));
    }
  });
  return { document: dom.window.document, window: dom.window, pageErrors };
}

const tick = (n = 30) => new Promise(r => { let i = 0; (function s() { i++ >= n ? r() : setTimeout(s, 0); })(); });
const $ = (d, id) => d.getElementById(id);
const txt = (d, id) => ($(d, id) ? $(d, id).textContent.trim() : null);
const hidden = (d, id) => $(d, id).classList.contains('hidden');
const click = (d, id) => $(d, id).dispatchEvent(new d.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
const submit = (d, id) => $(d, id).dispatchEvent(new d.defaultView.Event('submit', { bubbles: true, cancelable: true }));
const set = (d, id, v) => { $(d, id).value = v; };
const uniq = () => 'live' + Date.now().toString(36) + Math.floor(Math.random() * 1e6).toString(36);

async function loginAs(d, w, email, pass) {
  click(d, 'tab-login');
  set(d, 'login-email', email); set(d, 'login-pass', pass);
  submit(d, 'login-form');
  await tick(60);
}

(async () => {
  section('A. Live: registration over real HTTP');
  let key = null;
  {
    const { document: d, window: w, pageErrors } = makeDom();
    await tick(30);
    const email = uniq() + '@example.com';
    const device = crypto.randomBytes(8).toString('hex');   // jsdom has no canvas -> fp is constant, so vary it
    set(d, 'reg-email', email); set(d, 'reg-pass', 'password123');
    set(d, 'reg-fp', device);
    submit(d, 'register-form');
    await tick(80);
    ok('registration succeeds against the live endpoint', !hidden(d, 'dashboard'), txt(d, 'auth-msg'));
    key = txt(d, 'api-key');
    ok('live API key rendered in full', /^xbp_[0-9a-f]{20}$/.test(key || ''), key);
    ok('live tier badge = FREE', txt(d, 'tier-badge') === 'FREE', txt(d, 'tier-badge'));
    ok('live usage = 0 / 10', txt(d, 'usage') === '0 / 10 checks today', txt(d, 'usage'));
    ok('no page errors', pageErrors.length === 0, JSON.stringify(pageErrors));

    section('B. Live: duplicate registration surfaces the server 409');
    click(d, 'btn-logout');
    click(d, 'tab-register');
    set(d, 'reg-email', email); set(d, 'reg-pass', 'password123');   // same email, same device
    submit(d, 'register-form');
    await tick(60);
    ok('409 conflict message shown (req 9)', /already exists/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
  }

  section('C. Live: login + full check cycle with a VALID signature');
  {
    const { document: d, window: w, pageErrors } = makeDom();
    await tick(30);
    await loginAs(d, w, 'demo@example.com', 'password123');
    ok('login lands on the dashboard', !hidden(d, 'dashboard'), txt(d, 'auth-msg'));
    ok('premium badge from live login', txt(d, 'tier-badge') === 'PREMIUM', txt(d, 'tier-badge'));

    const usageBefore = parseInt((txt(d, 'usage') || '0').split('/')[0].trim(), 10);
    set(d, 'check-email', 'player@hit.example.com');
    set(d, 'check-pass', 'secretpw');
    set(d, 'check-proxies', 'http://u:p@1.2.3.4:8080\r\nsocks5://5.6.7.8:1080\r\n');
    submit(d, 'check-form');
    await tick(120);
    const res = d.getElementById('result');
    ok('status "hit" rendered', /\bhit\b/.test(res.textContent), res.textContent.slice(0, 200));
    ok('watermark rendered exactly as "Provided by @yorichiiprime"', /Provided by @yorichiiprime/.test(res.textContent));
    ok('watermark match pill is green', res.querySelector('.pill.ok') !== null);
    ok('client-side HMAC verification GREEN against the live server (req 8)',
      /Signature valid/.test(res.textContent), res.textContent.slice(0, 400));
    ok('no red/mismatch pill on a genuine response', res.querySelector('.pill.bad') === null);
    ok('gamertag from payload shown in raw JSON', /DemoPlayer/.test(res.textContent));
    const usageAfter = parseInt((txt(d, 'usage') || '0').split('/')[0].trim(), 10);
    ok('usage counter incremented by exactly 1 after a check',
      usageAfter === usageBefore + 1, usageBefore + ' -> ' + usageAfter + ' (' + txt(d, 'usage') + ')');
    ok('no page errors during a live check', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('D. Live: rate limit (429) is user-friendly');
  {
    const { document: d, window: w, pageErrors } = makeDom();
    await tick(30);
    await loginAs(d, w, 'free@example.com', 'password123');
    ok('free account logs in', !hidden(d, 'dashboard'));
    set(d, 'check-email', 'someone@example.com'); set(d, 'check-pass', 'pw');
    submit(d, 'check-form');
    await tick(100);
    ok('429 renders the server message in the result area',
      /Daily limit reached/i.test(d.getElementById('result').textContent), d.getElementById('result').textContent.slice(0, 200));
    ok('result is not stuck on "Running check…"', !/Running check/.test(d.getElementById('result').textContent));
    ok('check button re-enabled after 429', !d.getElementById('btn-check').disabled);
    ok('no page errors on 429', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('E. Live: regenerate key — old key really dies');
  {
    const { document: d, window: w, pageErrors } = makeDom();
    await tick(30);
    await loginAs(d, w, 'demo@example.com', 'password123');
    const oldKey = txt(d, 'api-key');
    click(d, 'btn-revoke');
    click(d, 'btn-revoke-yes');
    await tick(80);
    const newKey = txt(d, 'api-key');
    ok('a new key was issued', newKey !== oldKey && /^xbp_[0-9a-f]{20}$/.test(newKey), oldKey + ' -> ' + newKey);
    ok('localStorage swapped to the new key', w.localStorage.getItem('xbsp_api_key') === newKey);

    // Verify at the HTTP level that the OLD key is dead.
    const oldRes = await globalThis.fetch(BASE + '/user/me', { headers: { Authorization: 'Bearer ' + oldKey } });
    const newRes = await globalThis.fetch(BASE + '/user/me', { headers: { Authorization: 'Bearer ' + newKey } });
    ok('OLD key now returns 401 from the server (req 4)', oldRes.status === 401, 'status=' + oldRes.status);
    ok('NEW key works (req 4)', newRes.status === 200, 'status=' + newRes.status);
    ok('dashboard still healthy after rotation', txt(d, 'tier-badge') === 'PREMIUM');
    ok('no page errors during rotation', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('F. Live: admin panel');
  {
    const { document: d, window: w, pageErrors } = makeDom();
    await tick(30);
    ok('admin hidden before unlock (req 6)', hidden(d, 'admin-section'));
    click(d, 'admin-trigger');
    set(d, 'admin-key', 'wrong-key');
    submit(d, 'admin-form');
    await tick(60);
    ok('wrong admin key -> friendly 403', /Invalid admin key/.test(txt(d, 'admin-msg')), txt(d, 'admin-msg'));

    set(d, 'admin-key', 'demo-admin-key');
    submit(d, 'admin-form');
    await tick(80);
    const out = d.getElementById('admin-output');
    ok('admin table rendered', out.querySelector('table') !== null);
    ok('seed users listed', /admin@example\.com/.test(out.textContent) && /free@example\.com/.test(out.textContent));
    ok('usage/limit columns present', /daily usage/.test(out.textContent) && /daily limit/.test(out.textContent));
    ok('API keys masked in admin table', !/xbp_admin_9999888877776666/.test(out.textContent));
    ok('device fingerprints masked', !/ffeeddccbbaa9988/.test(out.textContent));
    ok('no page errors in admin flow', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('G. Live: a stale/revoked key in storage recovers gracefully');
  {
    const first = makeDom();
    await tick(30);
    await loginAs(first.document, first.window, 'demo@example.com', 'password123');
    const staleKey = txt(first.document, 'api-key');
    await globalThis.fetch(BASE + '/user/key/revoke', { method: 'POST', headers: { Authorization: 'Bearer ' + staleKey } });

    const { document: d, window: w, pageErrors } = makeDom({ xbsp_api_key: staleKey });
    await tick(80);
    const probe = await globalThis.fetch(BASE + '/user/me', { headers: { Authorization: 'Bearer ' + staleKey } });
    ok('stale key is rejected by the live server (401)', probe.status === 401, 'status=' + probe.status);
    ok('user is bounced back to the login screen, not a blank dashboard',
      !hidden(d, 'auth-section') && hidden(d, 'dashboard'));
    ok('a clear "session no longer valid" message is shown',
      /no longer valid/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
    ok('the dead key is purged from storage', w.localStorage.getItem('xbsp_api_key') === null);
    ok('the page is still fully interactive (no blank screen)',
      d.body.textContent.trim().length > 200 && d.getElementById('login-email') !== null);
    ok('no page errors on the stale-key path', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  console.log('\n' + '='.repeat(60));
  console.log(`  \x1b[1m${pass} passed, ${fail} failed\x1b[0m   (live HTTP against ${BASE})`);
  if (failures.length) { console.log('\n  Failures:'); failures.forEach(f => console.log('   - ' + f)); }
  console.log('='.repeat(60));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS CRASH:', e); process.exit(2); });
