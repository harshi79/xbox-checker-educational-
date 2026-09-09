/**
 * Live frontend integration QA against qa-mock-preview.mjs.
 *
 * Run: node qa-mock-preview.mjs &
 *      node qa-live.test.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { JSDOM, VirtualConsole } = require('jsdom');

const BASE = 'http://localhost:8080';
const HTML = fs.readFileSync(path.resolve(__dirname, 'static/index.html'), 'utf8');
let pass = 0, fail = 0;
const failures = [];

function ok(name, condition, detail = '') {
  if (condition) { pass++; console.log('  \x1b[32mPASS\x1b[0m ' + name); }
  else { fail++; failures.push(name); console.log('  \x1b[31mFAIL\x1b[0m ' + name + (detail ? '\n        -> ' + detail : '')); }
}
function section(title) { console.log('\n\x1b[1m' + title + '\x1b[0m'); }

function makeDom(preset) {
  const pageErrors = [];
  const requests = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', error => { if (!/Not implemented/.test(error.message)) pageErrors.push(error.message); });
  const dom = new JSDOM(HTML, {
    url: BASE + '/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      Object.defineProperty(window, 'crypto', { value: crypto.webcrypto, configurable: true });
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
      window.TextEncoder = TextEncoder;
      window.AbortController = AbortController;
      window.Element.prototype.scrollIntoView = function () {};
      let cookie = '';
      window.fetch = async (input, init = {}) => {
        const target = new URL(input, BASE).href;
        init = Object.assign({}, init);
        init.headers = Object.assign({}, init.headers || {});
        if (cookie) init.headers.Cookie = cookie;
        requests.push({ url: target, method: init.method || 'GET', headers: init.headers, body: init.body || null });
        const response = await globalThis.fetch(target, init);
        const setCookie = response.headers.get('set-cookie');
        if (setCookie && /^xb_session=/.test(setCookie)) {
          cookie = /Max-Age=0/i.test(setCookie) ? '' : setCookie.split(';', 1)[0];
        }
        return response;
      };
      if (preset) Object.entries(preset).forEach(([k, v]) => window.localStorage.setItem(k, v));
    }
  });
  return { document: dom.window.document, window: dom.window, requests, pageErrors };
}

const tick = (n = 45) => new Promise(resolve => { let i = 0; (function next() { if (i++ >= n) return resolve(); setTimeout(next, 0); })(); });
const $ = (d, id) => d.getElementById(id);
const text = (d, id) => ($(d, id) ? $(d, id).textContent.trim() : '');
const hidden = (d, id) => $(d, id).classList.contains('hidden');
const click = (d, id) => $(d, id).dispatchEvent(new d.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
const submit = (d, id) => $(d, id).dispatchEvent(new d.defaultView.Event('submit', { bubbles: true, cancelable: true }));
const set = (d, id, value) => { $(d, id).value = value; };
const unique = () => 'live-' + Date.now().toString(36) + '-' + crypto.randomBytes(3).toString('hex');

async function login(document, email, password = 'password123') {
  click(document, 'tab-login');
  set(document, 'login-email', email);
  set(document, 'login-pass', password);
  submit(document, 'login-form');
  await tick(70);
}

(async () => {
  section('A. Registration over real HTTP + cookie session');
  {
    const { document: d, window: w, requests, pageErrors } = makeDom({ xbsp_api_key: 'OLD_LEAKED_KEY' });
    await tick();
    const email = unique() + '@example.com';
    set(d, 'reg-email', email);
    set(d, 'reg-pass', 'password123');
    set(d, 'reg-fp', crypto.randomBytes(8).toString('hex'));
    submit(d, 'register-form');
    await tick(90);
    ok('registration opens dashboard', !hidden(d, 'dashboard'), text(d, 'auth-msg'));
    ok('profile email comes from backend DB', text(d, 'profile-email') === email, text(d, 'profile-email'));
    ok('new user starts disconnected', /Not connected/.test(text(d, 'xbox-status')), text(d, 'xbox-status'));
    ok('API key shown but not stored in localStorage', /^xbp_[0-9a-f]{20}$/.test(text(d, 'api-key')) && w.localStorage.getItem('xbsp_api_key') === null, text(d, 'api-key'));
    ok('protected calls carry a cookie, not Authorization', requests.some(r => r.url.endsWith('/user/me') && r.headers.Cookie && !r.headers.Authorization));
    ok('no page errors', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('B. Login shows consented Xbox snapshot');
  {
    const { document: d, requests, pageErrors } = makeDom();
    await tick();
    await login(d, 'demo@example.com');
    ok('login opens dashboard', !hidden(d, 'dashboard'), text(d, 'auth-msg'));
    ok('premium workspace tier renders', text(d, 'tier-badge') === 'PREMIUM', text(d, 'tier-badge'));
    ok('connected profile badge renders', /Xbox profile connected/.test(text(d, 'xbox-status')), text(d, 'xbox-status'));
    ok('gamertag and gamerscore render from API', /ConsentPlayer/.test(text(d, 'xbox-result')) && /9876/.test(text(d, 'xbox-result')), text(d, 'xbox-result'));
    ok('signature is present without browser shared secret', /Server signature present/.test(text(d, 'xbox-result')));
    ok('OAuth refresh points to backend route', $(d, 'btn-ms-connect').getAttribute('href') === '/microsoft/connect');
    ok('no target password/proxy request is sent', !requests.some(r => r.url.endsWith('/check')));
    ok('no page errors', pageErrors.length === 0, JSON.stringify(pageErrors));

    click(d, 'btn-ms-disconnect');
    await tick(60);
    ok('disconnect updates backend and UI', /Not connected/.test(text(d, 'xbox-status')) && hidden(d, 'btn-ms-disconnect'), text(d, 'xbox-status'));
  }

  section('C. Session restore and logout');
  {
    const { document: d, requests, pageErrors } = makeDom();
    await tick();
    await login(d, 'admin@example.com');
    ok('login succeeded before logout', !hidden(d, 'dashboard'));
    click(d, 'btn-logout');
    await tick(55);
    ok('logout endpoint called', requests.some(r => r.url.endsWith('/auth/logout') && r.method === 'POST'));
    ok('logout returns to login form', !hidden(d, 'auth-section') && !hidden(d, 'login-form') && hidden(d, 'dashboard'));
    ok('no blank screen/page error', d.body.textContent.length > 300 && pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('D. API-key rotation remains available for programmatic clients');
  {
    const { document: d, window: w } = makeDom();
    await tick();
    await login(d, 'admin@example.com');
    const oldKey = 'xbp_admin_9999888877776666';
    ok('login restores only a safe key preview', /…/.test(text(d, 'api-key')) && !text(d, 'api-key').includes(oldKey));
    click(d, 'btn-revoke'); click(d, 'btn-revoke-yes');
    await tick(60);
    const newKey = text(d, 'api-key');
    ok('rotation issues a different full key once', newKey !== oldKey && /^xbp_[0-9a-f]{20}$/.test(newKey), oldKey + ' -> ' + newKey);
    ok('rotated key is not persisted in browser storage', w.localStorage.getItem('xbsp_api_key') === null);
    const oldResponse = await globalThis.fetch(BASE + '/user/me', { headers: { Authorization: 'Bearer ' + oldKey } });
    const newResponse = await globalThis.fetch(BASE + '/user/me', { headers: { Authorization: 'Bearer ' + newKey } });
    ok('old key is rejected at HTTP layer', oldResponse.status === 401, String(oldResponse.status));
    ok('new key authenticates at HTTP layer', newResponse.status === 200, String(newResponse.status));
  }

  section('E. Admin table');
  {
    const { document: d, pageErrors } = makeDom();
    await tick(); click(d, 'admin-trigger');
    set(d, 'admin-key', 'wrong'); submit(d, 'admin-form'); await tick(35);
    ok('wrong admin key shows 403 detail', /Invalid admin key/.test(text(d, 'admin-msg')), text(d, 'admin-msg'));
    set(d, 'admin-key', 'demo-admin-key'); submit(d, 'admin-form'); await tick(55);
    const output = $(d, 'admin-output');
    ok('admin users render in a table', !!output.querySelector('table'));
    ok('seed users are listed', /demo@example\.com/.test(output.textContent) && /free@example\.com/.test(output.textContent));
    ok('only key previews are shown', !/xbp_admin_9999888877776666/.test(output.textContent));
    ok('no device fingerprints are shown', !/ffeeddccbbaa9988/.test(output.textContent));
    ok('no admin page errors', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('F. Legacy credential endpoint is retired');
  {
    // The QA fixture returns the retirement response directly. Production's
    // authenticated compatibility behavior is covered by backend integration.
    const response = await globalThis.fetch(BASE + '/check', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'x@example.com', password: 'never-send-this' })
    });
    ok('fixture returns 410 for legacy endpoint', response.status === 410, String(response.status));
    ok('production HTML has no checker password field', !/id="check-pass"|id="check-proxies"/.test(HTML));
    ok('production HTML contains no QA demo credentials', !/demo@example\.com/.test(HTML));
  }

  console.log('\n' + '='.repeat(60));
  console.log(`  \x1b[1m${pass} passed, ${fail} failed\x1b[0m   (live HTTP against ${BASE})`);
  if (failures.length) { console.log('\n  Failures:'); failures.forEach(item => console.log('   - ' + item)); }
  console.log('='.repeat(60));
  process.exit(fail ? 1 : 0);
})().catch(error => { console.error('HARNESS CRASH:', error); process.exit(2); });
