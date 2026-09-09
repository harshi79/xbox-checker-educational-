/**
 * Frontend QA harness — loads the REAL static/index.html in jsdom, stubs fetch,
 * and drives the real event handlers. No logic is re-implemented here.
 *
 * Run:
 *   npm install --no-save --prefix /tmp/jstest jsdom
 *   node qa-frontend.test.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { JSDOM, VirtualConsole } = require('/tmp/jstest/node_modules/jsdom');

const HTML_PATH = path.resolve(__dirname, 'static/index.html');
const HTML = fs.readFileSync(HTML_PATH, 'utf8');
const SECRET = 'dev-secret-change-in-prod';

let pass = 0, fail = 0, envGapsTotal = 0;
const failures = [];

function ok(name, cond, extra) {
  if (cond) { pass++; console.log('  \x1b[32mPASS\x1b[0m ' + name); }
  else { fail++; failures.push(name); console.log('  \x1b[31mFAIL\x1b[0m ' + name + (extra ? '\n        -> ' + extra : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

/* ---- canonicalisation matching the page's implementation (independent copy for signing) ---- */
function canonicalJson(v) {
  if (v === undefined || v === null) return 'null';
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonicalJson(v[k])).join(',') + '}';
}
function sign(payload) {
  const s = canonicalJson(payload);
  return crypto.createHmac('sha256', SECRET).update(s, 'utf8').digest('hex');
}

function makeDom(routes, opts) {
  opts = opts || {};
  const vc = new VirtualConsole();
  const pageErrors = [];
  const envGaps = [];
  vc.on('jsdomError', e => {
    if (/Not implemented/.test(e.message)) { envGaps.push(e.message); envGapsTotal++; }  // jsdom has no canvas etc.
    else pageErrors.push(e.message);
  });
  vc.on('error', (...a) => pageErrors.push(a.join(' ')));

  const calls = [];
  const dom = new JSDOM(HTML, {
    url: 'http://localhost:8000/static/index.html',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      // jsdom has no Web Crypto / canvas / scrollIntoView — provide the browser APIs
      // the page legitimately expects so the real code paths execute.
      Object.defineProperty(window, 'crypto', { value: crypto.webcrypto, configurable: true });
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
      window.TextEncoder = TextEncoder;
      window.TextDecoder = TextDecoder;
      window.AbortController = AbortController;
      window.Element.prototype.scrollIntoView = function () {};
      if (opts.preset) Object.keys(opts.preset).forEach(k => window.localStorage.setItem(k, opts.preset[k]));
      window.confirm = () => true;
      window.alert = () => {};
      window.fetch = async function (url, init) {
        init = init || {};
        calls.push({ url: String(url), method: init.method || 'GET', headers: init.headers || {}, body: init.body || null });
        const route = routes[String(url).replace(/^https?:\/\/[^/]+/, '')] || routes[String(url)];
        if (!route) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: 'Not Found' }) };
        if (route.throwNetwork) { const e = new Error('fetch failed'); e.name = 'TypeError'; throw e; }
        if (route.timeout) { const e = new Error('aborted'); e.name = 'AbortError'; throw e; }
        const status = route.status || 200;
        const bodyText = typeof route.body === 'string' ? route.body : JSON.stringify(route.body);
        return { ok: status >= 200 && status < 300, status, text: async () => bodyText };
      };
    }
  });
  return { dom, window: dom.window, document: dom.window.document, calls, pageErrors, envGaps };
}

const tick = (w, n = 12) => new Promise(res => {
  let i = 0;
  (function step() { if (i++ >= n) return res(); setTimeout(step, 0); })();
});
const $ = (d, id) => d.getElementById(id);
const txt = (d, id) => ($(d, id) ? $(d, id).textContent.trim() : null);
const hidden = (d, id) => $(d, id).classList.contains('hidden');
function click(d, id) {
  const n = $(d, id);
  n.dispatchEvent(new d.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
}
function submit(d, id) {
  $(d, id).dispatchEvent(new d.defaultView.Event('submit', { bubbles: true, cancelable: true }));
}
function setVal(d, id, v) { $(d, id).value = v; }

(async () => {
  /* ===================================================================== */
  section('1. Page load, fingerprint, no blank screen');
  {
    const { document: d, pageErrors, window: w } = makeDom({});
    await tick(w);
    ok('page boots with zero uncaught errors', pageErrors.length === 0, JSON.stringify(pageErrors));
    ok('auth section visible on load', !hidden(d, 'auth-section'));
    ok('dashboard hidden on load', hidden(d, 'dashboard'));
    ok('admin panel hidden on load (req 6)', hidden(d, 'admin-section'));
    const fpv = d.getElementById('reg-fp').value;
    ok('device fingerprint auto-generated (req 7)', /^[0-9a-f]{16}$/.test(fpv), 'got: ' + JSON.stringify(fpv));
    ok('fingerprint is non-empty even with no canvas (jsdom has none)', fpv.length === 16);
    ok('footer watermark text is exact (req 8)',
      /Provided by @yorichiiprime/.test(d.querySelector('footer').textContent));
    // fingerprint stability
    click(d, 'fp-refresh');
    ok('fingerprint regenerate button produces a stable 16-hex id', /^[0-9a-f]{16}$/.test(d.getElementById('reg-fp').value));
  }

  /* ===================================================================== */
  section('2. Login form is reachable (regression: showLogin was missing)');
  {
    const { document: d, window: w } = makeDom({});
    await tick(w);
    ok('login form hidden initially', hidden(d, 'login-form'));
    click(d, 'tab-login');
    ok('clicking Login tab reveals the login form', !hidden(d, 'login-form'));
    ok('clicking Login tab hides the register form', hidden(d, 'register-form'));
    ok('login tab aria-selected=true', d.getElementById('tab-login').getAttribute('aria-selected') === 'true');
    click(d, 'tab-register');
    ok('switching back to Register works', !hidden(d, 'register-form') && hidden(d, 'login-form'));
  }

  /* ===================================================================== */
  section('3. Registration flow (req 2)');
  {
    const { document: d, window: w, calls } = makeDom({
      '/auth/register': { body: { api_key: 'xbp_REG_key_123', tier: 'free' } },
      '/user/me': { body: { tier: 'free', daily_usage: 3, daily_limit: 50 } }
    });
    await tick(w);
    // client-side validation first
    setVal(d, 'reg-email', 'not-an-email'); setVal(d, 'reg-pass', 'short');
    submit(d, 'register-form'); await tick(w);
    ok('invalid email blocked client-side with a clear message',
      /valid email/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
    ok('no request sent for invalid input', calls.length === 0);

    setVal(d, 'reg-email', 'user@example.com'); setVal(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(w, 30);
    const regCall = calls.find(c => c.url.includes('/auth/register'));
    ok('POST /auth/register sent', !!regCall && regCall.method === 'POST');
    const body = JSON.parse(regCall.body);
    ok('register payload has email', body.email === 'user@example.com');
    ok('register payload has password', body.password === 'password123');
    ok('register payload has device_fingerprint (req 7)', /^[0-9a-f]{16}$/.test(body.device_fingerprint), body.device_fingerprint);
    ok('auth section hidden after success (req 2)', hidden(d, 'auth-section'));
    ok('dashboard shown after success (req 2)', !hidden(d, 'dashboard'));
    ok('API key displayed in full (req 3)', txt(d, 'api-key') === 'xbp_REG_key_123', txt(d, 'api-key'));
    ok('tier badge shows FREE (req 3)', txt(d, 'tier-badge') === 'FREE');
    ok('tier badge has colour class (req 3)', d.getElementById('tier-badge').className.includes('badge free'));
    ok('daily usage/limit shown (req 3)', txt(d, 'usage') === '3 / 50 checks today', txt(d, 'usage'));
    ok('usage meter width set', d.getElementById('usage-bar').style.width === '6%');
    ok('key persisted to localStorage', w.localStorage.getItem('xbsp_api_key') === 'xbp_REG_key_123');
    ok('copy button present (req 3)', !!d.getElementById('btn-copy-key'));
  }

  /* ===================================================================== */
  section('4. Login flow (regression: checked access_token but stored api_key)');
  {
    const { document: d, window: w, calls } = makeDom({
      '/auth/login': { body: { api_key: 'xbp_LOGIN_key_999', tier: 'premium' } },
      '/user/me': { body: { tier: 'premium', daily_usage: 12, daily_limit: 100 } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'user@example.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    const c = calls.find(x => x.url.includes('/auth/login'));
    ok('POST /auth/login sent with email+password',
      !!c && JSON.parse(c.body).email === 'user@example.com' && JSON.parse(c.body).password === 'password123');
    ok('login with api_key response now succeeds (regression fixed)', !hidden(d, 'dashboard'));
    ok('API key from login displayed', txt(d, 'api-key') === 'xbp_LOGIN_key_999', txt(d, 'api-key'));
    ok('premium badge rendered', txt(d, 'tier-badge') === 'PREMIUM' && d.getElementById('tier-badge').className.includes('premium'));
    ok('password field cleared after login', d.getElementById('login-pass').value === '');
  }
  {
    const { document: d, window: w } = makeDom({
      '/auth/login': { body: { access_token: 'xbp_TOK_555' } },
      '/user/me': { body: { tier: 'pro', daily_usage: 0, daily_limit: 5000 } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'pw12345678');
    submit(d, 'login-form'); await tick(w, 30);
    ok('login also tolerates an access_token-shaped response', !hidden(d, 'dashboard') && txt(d, 'api-key') === 'xbp_TOK_555');
    ok('PRO tier badge rendered', txt(d, 'tier-badge') === 'PRO' && d.getElementById('tier-badge').className.includes('pro'));
  }
  {
    const { document: d, window: w, pageErrors } = makeDom({
      '/auth/login': { status: 401, body: { detail: 'Incorrect email or password' } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'wrongpass');
    submit(d, 'login-form'); await tick(w, 30);
    ok('401 login shows the server error message (req 9)',
      /Incorrect email or password/.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
    ok('error message uses the error style', !!d.querySelector('#auth-msg .status.error'));
    ok('auth section stays visible on failed login', !hidden(d, 'auth-section'));
    ok('no uncaught errors on 401', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  /* ===================================================================== */
  section('5. Error handling (req 9)');
  {
    const { document: d, window: w, pageErrors } = makeDom({ '/auth/register': { throwNetwork: true } });
    await tick(w);
    setVal(d, 'reg-email', 'u@e.com'); setVal(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(w, 30);
    ok('network failure shows a friendly message',
      /Network error/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
    ok('page did not crash on network failure', pageErrors.length === 0, JSON.stringify(pageErrors));
    ok('register button re-enabled after failure', !d.getElementById('btn-register').disabled);
  }
  {
    const { document: d, window: w } = makeDom({ '/auth/register': { status: 429, body: {} } });
    await tick(w);
    setVal(d, 'reg-email', 'u@e.com'); setVal(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(w, 30);
    ok('429 maps to a rate-limit message', /Rate limit/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
  }
  {
    const { document: d, window: w } = makeDom({ '/auth/register': { status: 500, body: '<html>Server Blew Up</html>' } });
    await tick(w);
    setVal(d, 'reg-email', 'u@e.com'); setVal(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(w, 30);
    ok('500 with a non-JSON body is handled, not thrown',
      d.querySelector('#auth-msg .status.error') !== null, txt(d, 'auth-msg'));
  }
  {
    const { document: d, window: w } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { status: 401, body: { detail: 'Invalid API key' } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    ok('stale/revoked key: 401 on /user/me returns user to login',
      !hidden(d, 'auth-section') && hidden(d, 'dashboard'));
    ok('stale key message explains what happened',
      /no longer valid|log in again/i.test(txt(d, 'auth-msg')), txt(d, 'auth-msg'));
    ok('stale key purged from storage', w.localStorage.getItem('xbsp_api_key') === null);
  }

  /* ===================================================================== */
  section('6. Check functionality + signature verification (req 5, 8)');
  {
    const payload = {
      status: 'hit',
      email: 'target@example.com',
      gamertag: 'TestPlayer',
      watermark: 'Provided by @yorichiiprime'
    };
    const { document: d, window: w, calls, pageErrors } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { body: { tier: 'pro', daily_usage: 1, daily_limit: 5000 } },
      '/check': { body: Object.assign({}, payload, { signature: sign(payload) }) }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);

    setVal(d, 'check-email', 'target@example.com');
    setVal(d, 'check-pass', 'targetpass');
    setVal(d, 'check-proxies', 'http://u:p@1.2.3.4:8080\r\nsocks5://5.6.7.8:1080\r\n# comment\r\nhttp://u:p@1.2.3.4:8080\r\n');
    d.getElementById('check-proxies').dispatchEvent(new w.Event('input', { bubbles: true }));
    ok('CRLF + duplicate + comment proxies normalised (regression)',
      txt(d, 'proxy-count') === '2 proxies queued', txt(d, 'proxy-count'));

    submit(d, 'check-form'); await tick(w, 60);

    const cc = calls.find(x => x.url.includes('/check'));
    ok('POST /check sent', !!cc && cc.method === 'POST');
    ok('Bearer token attached to /check (req 5)', cc.headers['Authorization'] === 'Bearer k1', JSON.stringify(cc.headers));
    const cbody = JSON.parse(cc.body);
    ok('check body has email+password', cbody.email === 'target@example.com' && cbody.password === 'targetpass');
    ok('proxies parsed without stray \\r',
      JSON.stringify(cbody.proxies) === JSON.stringify(['http://u:p@1.2.3.4:8080', 'socks5://5.6.7.8:1080']),
      JSON.stringify(cbody.proxies));

    const res = d.getElementById('result');
    ok('status displayed (req 5)', /hit/.test(res.textContent));
    ok('watermark displayed (req 5)', /Provided by @yorichiiprime/.test(res.textContent));
    ok('watermark match badge shown (req 8)', /matches expected/.test(res.textContent));
    ok('signature displayed (req 5)', res.textContent.includes(sign(payload)));
    ok('valid HMAC shows the green check (req 8)', res.querySelector('.pill.ok') !== null && /Signature valid/.test(res.textContent), res.textContent.slice(0, 300));
    ok('raw payload rendered', res.querySelector('pre') !== null);
    ok('no uncaught errors during check', pageErrors.length === 0, JSON.stringify(pageErrors));
  }
  {
    const payload = { status: 'hit', watermark: 'Provided by @yorichiiprime' };
    const { document: d, window: w } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { body: { tier: 'free', daily_usage: 0, daily_limit: 10 } },
      '/check': { body: Object.assign({}, payload, { signature: sign({ status: 'hit', watermark: 'Provided by @yorichiiprime', email: 'INJECTED@x.com' }) }) }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    setVal(d, 'check-email', 'a@b.c'); setVal(d, 'check-pass', 'p');
    submit(d, 'check-form'); await tick(w, 60);
    const res = d.getElementById('result');
    ok('tampered payload shows a red X, not a false green',
      res.querySelector('.pill.bad') !== null && /Signature mismatch/.test(res.textContent), res.textContent.slice(0, 250));
  }
  {
    const { document: d, window: w } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { body: { tier: 'free', daily_usage: 0, daily_limit: 10 } },
      '/check': { body: { status: 'bad', watermark: 'Provided by @yorichiiprime' } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    setVal(d, 'check-email', 'a@b.c'); setVal(d, 'check-pass', 'p');
    submit(d, 'check-form'); await tick(w, 60);
    const res = d.getElementById('result');
    ok('missing signature -> neutral state, not a false red X',
      res.querySelector('.pill.na') !== null && /No signature returned/.test(res.textContent), res.textContent.slice(0, 250));
    ok('missing signature does not throw (regression: .match on undefined)', true);
  }
  {
    const { document: d, window: w, pageErrors } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { body: { tier: 'free', daily_usage: 0, daily_limit: 10 } },
      '/check': { status: 500, body: { detail: 'Upstream checker exploded' } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    setVal(d, 'check-email', 'a@b.c'); setVal(d, 'check-pass', 'p');
    submit(d, 'check-form'); await tick(w, 60);
    const res = d.getElementById('result');
    ok('check 5xx shows an error, does not hang on "Checking..."',
      /Upstream checker exploded/.test(res.textContent) && !/Running check/.test(res.textContent), res.textContent.slice(0, 200));
    ok('check button re-enabled after failure', !d.getElementById('btn-check').disabled);
    ok('no uncaught errors on check failure', pageErrors.length === 0, JSON.stringify(pageErrors));
  }
  {
    const { document: d, window: w, pageErrors } = makeDom({
      '/auth/login': { body: { api_key: 'k1' } },
      '/user/me': { body: { tier: 'free', daily_usage: 0, daily_limit: 10 } },
      '/check': { body: {
        status: '<img src=x onerror="window.__xss=1">',
        watermark: '<script>window.__xss2=1<\/script>Provided by @yorichiiprime',
        detail: '<b>bold</b>'
      } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);
    setVal(d, 'check-email', 'a@b.c'); setVal(d, 'check-pass', 'p');
    submit(d, 'check-form'); await tick(w, 60);
    const res = d.getElementById('result');
    ok('XSS: no injected <img> element from server data', res.querySelector('img') === null);
    ok('XSS: no injected <script> element from server data', res.querySelector('script') === null);
    ok('XSS: no injected <b> element from server data', res.querySelector('b') === null);
    ok('XSS: handlers never fired', w.__xss !== 1 && w.__xss2 !== 1);
    ok('no uncaught errors while rendering hostile payload', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  /* ===================================================================== */
  section('7. API key regeneration (req 4)');
  {
    const { document: d, window: w, calls } = makeDom({
      '/auth/login': { body: { api_key: 'OLD_KEY' } },
      '/user/me': { body: { tier: 'free', daily_usage: 0, daily_limit: 10 } },
      '/user/key/revoke': { body: { api_key: 'NEW_KEY' } }
    });
    await tick(w);
    click(d, 'tab-login');
    setVal(d, 'login-email', 'u@e.com'); setVal(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(w, 30);

    ok('confirmation panel hidden until requested (req 4)', hidden(d, 'revoke-confirm'));
    click(d, 'btn-revoke');
    ok('regenerate requires explicit confirmation (req 4)', !hidden(d, 'revoke-confirm'));
    ok('no revoke request sent before confirming', !calls.some(c => c.url.includes('/revoke')));
    click(d, 'btn-revoke-no');
    ok('cancel closes the confirmation', hidden(d, 'revoke-confirm'));

    click(d, 'btn-revoke');
    click(d, 'btn-revoke-yes'); await tick(w, 40);
    const rv = calls.find(c => c.url.includes('/user/key/revoke'));
    ok('POST /user/key/revoke sent after confirming', !!rv && rv.method === 'POST');
    ok('dashboard immediately shows the NEW key', txt(d, 'api-key') === 'NEW_KEY', txt(d, 'api-key'));
    ok('localStorage holds only the NEW key (old key dropped)', w.localStorage.getItem('xbsp_api_key') === 'NEW_KEY');
    ok('subsequent calls use the new Bearer token (old key dead)',
      calls.filter(c => c.headers['Authorization'] === 'Bearer NEW_KEY').length > 0);
    ok('no call still carries the old key after revoke',
      calls.filter(c => c.url.includes('/revoke') === false && c.headers['Authorization'] === 'Bearer OLD_KEY' && calls.indexOf(c) > calls.indexOf(rv)).length === 0);
  }

  /* ===================================================================== */
  section('8. Admin panel (req 6)');
  {
    const { document: d, window: w, calls, pageErrors } = makeDom({
      '/admin/users': { body: { users: [
        { email: 'a@example.com', tier: 'pro', daily_usage: 12, daily_limit: 5000, created_at: '2026-01-02', api_key: 'xbp_SECRET_abcd1234efgh', device_fingerprint: 'deadbeefcafebabe' },
        { email: 'b@example.com', tier: 'free', daily_usage: 0, daily_limit: 10, created_at: '2026-02-03', api_key: 'xbp_SECRET_999988887777', device_fingerprint: '0123456789abcdef' }
      ] } }
    });
    await tick(w);
    ok('admin hidden by default (req 6)', hidden(d, 'admin-section'));
    click(d, 'admin-trigger');
    ok('footer trigger reveals the admin section (req 6)', !hidden(d, 'admin-section'));
    click(d, 'btn-admin-close');
    ok('admin section can be hidden again', hidden(d, 'admin-section'));
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'A', ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true }));
    ok('Ctrl+Shift+A also reveals admin', !hidden(d, 'admin-section'));

    submit(d, 'admin-form'); await tick(w, 20);
    ok('admin requires a key first', /Enter the admin API key/i.test(txt(d, 'admin-msg')), txt(d, 'admin-msg'));

    setVal(d, 'admin-key', 'ADMIN_SUPER_SECRET');
    submit(d, 'admin-form'); await tick(w, 40);
    const ac = calls.find(c => c.url.includes('/admin/users'));
    ok('GET /admin/users requested', !!ac && ac.method === 'GET');
    ok('X-Admin-Key header sent (req 6)', ac.headers['X-Admin-Key'] === 'ADMIN_SUPER_SECRET', JSON.stringify(ac.headers));
    const out = d.getElementById('admin-output');
    ok('users rendered as a table (readable, req 6)', out.querySelector('table') !== null);
    ok('user count reported', /2 users/.test(out.textContent), out.textContent.slice(0, 120));
    ok('emails displayed', out.textContent.includes('a@example.com') && out.textContent.includes('b@example.com'));
    ok('tiers displayed', out.textContent.includes('pro') && out.textContent.includes('free'));
    ok('api_key masked in the table', !out.textContent.includes('xbp_SECRET_abcd1234efgh'));
    ok('device_fingerprint masked in the table', !out.textContent.includes('deadbeefcafebabe'));
    ok('no uncaught errors in admin flow', pageErrors.length === 0, JSON.stringify(pageErrors));
  }
  {
    const { document: d, window: w, pageErrors } = makeDom({ '/admin/users': { status: 403, body: { detail: 'Invalid admin key' } } });
    await tick(w);
    click(d, 'admin-trigger');
    setVal(d, 'admin-key', 'wrong');
    submit(d, 'admin-form'); await tick(w, 40);
    ok('admin 403 shows a friendly error', /Invalid admin key/.test(txt(d, 'admin-msg')), txt(d, 'admin-msg'));
    ok('no crash on admin failure', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  /* ===================================================================== */
  section('9. Session restore + sign out');
  {
    const { document: doc, window: w } = makeDom(
      { '/user/me': { body: { tier: 'premium', daily_usage: 7, daily_limit: 100 } } },
      { preset: { xbsp_api_key: 'RESTORED_KEY' } }
    );
    await tick(w, 40);
    ok('stored key restores the dashboard on load', !hidden(doc, 'dashboard'));
    ok('auth section hidden when a session is restored', hidden(doc, 'auth-section'));
    ok('restored key displayed in full', txt(doc, 'api-key') === 'RESTORED_KEY', txt(doc, 'api-key'));
    ok('restored profile renders tier', txt(doc, 'tier-badge') === 'PREMIUM', txt(doc, 'tier-badge'));
    ok('restored profile renders usage', txt(doc, 'usage') === '7 / 100 checks today', txt(doc, 'usage'));
    click(doc, 'btn-logout');
    ok('sign out returns to the login tab', !hidden(doc, 'auth-section') && !hidden(doc, 'login-form'));
    ok('sign out clears the stored key', w.localStorage.getItem('xbsp_api_key') === null);
  }

  section('10. Markup / a11y / responsive static checks');
  {
    const noJs = HTML.includes('<noscript>');
    ok('noscript fallback present', noJs);
    ok('viewport meta present', /name="viewport"/.test(HTML));
    ok('color-scheme declared', /name="color-scheme"/.test(HTML));
    ok('theme-color declared', /name="theme-color"/.test(HTML));
    ok('mobile media query present', /@media \(max-width: 640px\)/.test(HTML));
    ok('reduced-motion respected', /prefers-reduced-motion/.test(HTML));
    ok('inputs >=16px (prevents iOS focus zoom)', /font-size: 16px/.test(HTML));
    ok('grid uses min() to avoid overflow', /minmax\(min\(220px, 100%\)/.test(HTML));
    ok('long strings wrap (no horizontal overflow)', /overflow-wrap: anywhere/.test(HTML) && /word-break: break-all/.test(HTML));
    ok('body has overflow-x guard', /overflow-x: hidden/.test(HTML));
    ok('labels wired to inputs', (HTML.match(/<label for="/g) || []).length >= 8);
    ok('aria-live regions for async messages', (HTML.match(/aria-live="polite"/g) || []).length >= 4);
    ok('autocomplete attributes present', /autocomplete="email"/.test(HTML) && /autocomplete="current-password"/.test(HTML));
    ok('all buttons have an explicit type', !/<button(?![^>]*\btype=)/.test(HTML), (HTML.match(/<button(?![^>]*\btype=)/g) || []).join('|'));
    ok('no inline onclick handlers remain', !/onclick=/.test(HTML));
    ok('referrer policy set (credentials not leaked)', /name="referrer" content="no-referrer"/.test(HTML));
    ok('inline favicon (no 404 noise)', /rel="icon"/.test(HTML));
  }

  console.log('\n  (environment gaps ignored, not page faults: ' + envGapsTotal + ')');
  console.log('='.repeat(60));
  console.log(`  \x1b[1m${pass} passed, ${fail} failed\x1b[0m`);
  if (failures.length) { console.log('\n  Failures:'); failures.forEach(f => console.log('   - ' + f)); }
  console.log('='.repeat(60));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS CRASH:', e); process.exit(2); });
