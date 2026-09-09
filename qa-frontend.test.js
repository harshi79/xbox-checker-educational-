/**
 * Frontend DOM/integration QA for the real static/index.html.
 *
 * Run: npm install --no-save --prefix /tmp/jstest jsdom
 *      node qa-frontend.test.js
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { JSDOM, VirtualConsole } = require('jsdom');

const HTML = fs.readFileSync(path.resolve(__dirname, 'static/index.html'), 'utf8');
const GOOD_SIG = 'a'.repeat(64);
let pass = 0, fail = 0;
const failures = [];

function ok(name, condition, detail = '') {
  if (condition) { pass++; console.log('  \x1b[32mPASS\x1b[0m ' + name); }
  else {
    fail++; failures.push(name);
    console.log('  \x1b[31mFAIL\x1b[0m ' + name + (detail ? '\n        -> ' + detail : ''));
  }
}
function section(title) { console.log('\n\x1b[1m' + title + '\x1b[0m'); }

function response(status, body) {
  const bodyText = status === 204 ? '' : (typeof body === 'string' ? body : JSON.stringify(body));
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => bodyText
  };
}

function makeDom(routes = {}, opts = {}) {
  const calls = [];
  const pageErrors = [];
  let sessionActive = !!opts.initialSession;
  const vc = new VirtualConsole();
  vc.on('jsdomError', error => {
    if (!/Not implemented/.test(error.message)) pageErrors.push(error.message);
  });
  vc.on('error', (...parts) => pageErrors.push(parts.join(' ')));

  const dom = new JSDOM(HTML, {
    url: opts.url || 'http://localhost:8000/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    virtualConsole: vc,
    beforeParse(window) {
      Object.defineProperty(window, 'crypto', { value: crypto.webcrypto, configurable: true });
      Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
      window.TextEncoder = TextEncoder;
      window.AbortController = AbortController;
      window.Element.prototype.scrollIntoView = function () {};
      window.confirm = () => true;
      if (opts.preset) {
        Object.entries(opts.preset).forEach(([key, value]) => window.localStorage.setItem(key, value));
      }

      window.fetch = async function (input, init = {}) {
        const url = String(input);
        const pathname = new URL(url, window.location.href).pathname;
        const call = {
          url,
          pathname,
          method: init.method || 'GET',
          headers: init.headers || {},
          body: init.body || null,
          credentials: init.credentials
        };
        calls.push(call);

        const protectedPath = pathname.startsWith('/user/') || pathname.startsWith('/microsoft/status') || pathname.startsWith('/microsoft/disconnect');
        if (protectedPath && !sessionActive) return response(401, { detail: 'Authentication required or session expired' });

        let route = routes[pathname];
        if (typeof route === 'function') route = route(call);
        if (!route) return response(404, { detail: 'Not Found' });
        if (route.throwNetwork) throw new TypeError('fetch failed');
        if (route.timeout) { const error = new Error('aborted'); error.name = 'AbortError'; throw error; }

        const status = route.status === undefined ? 200 : route.status;
        if ((pathname === '/auth/register' || pathname === '/auth/login') && status >= 200 && status < 300) {
          sessionActive = true;
        }
        if (pathname === '/auth/logout' && status >= 200 && status < 300) sessionActive = false;
        return response(status, route.body);
      };
    }
  });
  return { dom, window: dom.window, document: dom.window.document, calls, pageErrors };
}

const tick = (n = 25) => new Promise(resolve => {
  let count = 0;
  (function next() { if (count++ >= n) return resolve(); setTimeout(next, 0); })();
});
const $ = (document, id) => document.getElementById(id);
const text = (document, id) => ($(document, id) ? $(document, id).textContent.trim() : '');
const hidden = (document, id) => $(document, id).classList.contains('hidden');
const click = (document, id) => $(document, id).dispatchEvent(new document.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
const submit = (document, id) => $(document, id).dispatchEvent(new document.defaultView.Event('submit', { bubbles: true, cancelable: true }));
const set = (document, id, value) => { $(document, id).value = value; };

function profile(tier = 'free') {
  return {
    email: 'student@example.com', tier,
    daily_usage: 0, daily_limit: 100,
    api_key_preview: 'xbsp_demo…1234', auth_method: 'session'
  };
}
function disconnected(configured = true) {
  return {
    connected: false,
    profile: null,
    capabilities: {
      oauth_configured: configured,
      game_pass_entitlement_access: false,
      game_pass_requirement: 'Partner authorization required'
    },
    watermark: 'Provided by @yorichiiprime',
    signature: GOOD_SIG
  };
}

(async () => {
  section('1. Boot, professional copy and auth tabs');
  {
    const { document: d, window: w, pageErrors, calls } = makeDom({}, { preset: { xbsp_api_key: 'LEGACY_SECRET' } });
    await tick();
    ok('page boots without uncaught errors', pageErrors.length === 0, JSON.stringify(pageErrors));
    ok('auth visible and dashboard hidden', !hidden(d, 'auth-section') && hidden(d, 'dashboard'));
    ok('legacy localStorage API key is removed', w.localStorage.getItem('xbsp_api_key') === null);
    ok('backend session probe is attempted', calls.some(c => c.pathname === '/user/me'));
    ok('Microsoft-password safety copy is visible', /never receives your Microsoft password/i.test(d.body.textContent));
    ok('device identifier is generated', /^[0-9a-f]{32}$/.test($ (d, 'reg-fp').value), $(d, 'reg-fp').value);
    click(d, 'tab-login');
    ok('login tab reveals login form', !hidden(d, 'login-form') && hidden(d, 'register-form'));
    click(d, 'tab-register');
    ok('register tab restores registration form', !hidden(d, 'register-form') && hidden(d, 'login-form'));
  }

  section('2. Registration uses backend cookie session, not localStorage');
  {
    const routes = {
      '/auth/register': { status: 201, body: { api_key: 'xbsp_FULL_REGISTRATION_KEY', tier: 'free', session: 'active' } },
      '/user/me': { body: profile('free') },
      '/microsoft/status': { body: disconnected(true) }
    };
    const { document: d, window: w, calls, pageErrors } = makeDom(routes);
    await tick();
    set(d, 'reg-email', 'bad'); set(d, 'reg-pass', 'short');
    submit(d, 'register-form'); await tick(5);
    ok('invalid registration is blocked client-side', /valid email/i.test(text(d, 'auth-msg')));
    ok('invalid registration sends no register request', !calls.some(c => c.pathname === '/auth/register'));

    set(d, 'reg-email', 'student@example.com'); set(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(45);
    const registration = calls.find(c => c.pathname === '/auth/register');
    const body = registration ? JSON.parse(registration.body) : {};
    ok('POST /auth/register is sent', registration && registration.method === 'POST');
    ok('registration carries app credentials and installation id', body.email === 'student@example.com' && body.password === 'password123' && /^[0-9a-f]{32}$/.test(body.device_fingerprint || ''));
    ok('dashboard opens after backend session creation', !hidden(d, 'dashboard') && hidden(d, 'auth-section'));
    ok('full API key is displayed only in current memory', text(d, 'api-key') === 'xbsp_FULL_REGISTRATION_KEY');
    ok('API key never enters localStorage', w.localStorage.getItem('xbsp_api_key') === null);
    ok('profile email and tier render', text(d, 'profile-email') === 'student@example.com' && text(d, 'tier-badge') === 'FREE');
    ok('disconnected Microsoft state renders', /Not connected/.test(text(d, 'xbox-status')));
    ok('Microsoft link is available when configured', $(d, 'btn-ms-connect').getAttribute('href') === '/microsoft/connect');
    ok('browser API calls use same-origin cookies', calls.filter(c => c.pathname.startsWith('/user/') || c.pathname.startsWith('/microsoft/')).every(c => c.credentials === 'same-origin' && !c.headers.Authorization));
    ok('no page errors during registration', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('3. Login, errors and logout');
  {
    const routes = {
      '/auth/login': { body: { api_key_preview: 'xbsp_logi…_KEY', tier: 'premium', session: 'active' } },
      '/auth/logout': { status: 204, body: '' },
      '/user/me': { body: profile('premium') },
      '/microsoft/status': { body: disconnected(true) }
    };
    const { document: d, window: w, calls } = makeDom(routes);
    await tick();
    click(d, 'tab-login');
    set(d, 'login-email', 'student@example.com'); set(d, 'login-pass', 'password123');
    submit(d, 'login-form'); await tick(45);
    ok('successful login opens dashboard', !hidden(d, 'dashboard'));
    ok('password field is cleared', $(d, 'login-pass').value === '');
    ok('premium tier renders', text(d, 'tier-badge') === 'PREMIUM');
    ok('login restores only a key preview', /…/.test(text(d, 'api-key')) && $(d, 'btn-copy-key').disabled);
    ok('login key is not persisted', w.localStorage.getItem('xbsp_api_key') === null);
    click(d, 'btn-logout'); await tick(30);
    ok('logout calls backend', calls.some(c => c.pathname === '/auth/logout' && c.method === 'POST'));
    ok('logout returns to login form', !hidden(d, 'auth-section') && !hidden(d, 'login-form') && hidden(d, 'dashboard'));
  }
  {
    const { document: d } = makeDom({ '/auth/login': { status: 401, body: { detail: 'Incorrect email or password' } } });
    await tick(); click(d, 'tab-login');
    set(d, 'login-email', 'student@example.com'); set(d, 'login-pass', 'wrong-password');
    submit(d, 'login-form'); await tick(20);
    ok('401 login shows backend error', /Incorrect email or password/.test(text(d, 'auth-msg')));
    ok('failed login keeps auth screen visible', !hidden(d, 'auth-section'));
  }
  {
    const { document: d, pageErrors } = makeDom({ '/auth/register': { throwNetwork: true } });
    await tick(); set(d, 'reg-email', 'student@example.com'); set(d, 'reg-pass', 'password123');
    submit(d, 'register-form'); await tick(20);
    ok('network failure is user-friendly', /Network error/.test(text(d, 'auth-msg')));
    ok('submit button recovers after network error', !$(d, 'btn-register').disabled);
    ok('network failure causes no uncaught page errors', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('4. Server-side session restore');
  {
    const routes = {
      '/user/me': { body: profile('pro') },
      '/microsoft/status': { body: disconnected(true) }
    };
    const { document: d } = makeDom(routes, { initialSession: true });
    await tick(45);
    ok('valid HttpOnly session restores dashboard', !hidden(d, 'dashboard') && hidden(d, 'auth-section'));
    ok('restored account shows API-key preview only', text(d, 'api-key') === 'xbsp_demo…1234');
    ok('copy disabled without full in-memory key', $(d, 'btn-copy-key').disabled);
    ok('restored PRO tier renders', text(d, 'tier-badge') === 'PRO');
  }

  section('5. Real Xbox profile presentation and disconnect');
  {
    let connected = true;
    const routes = {
      '/user/me': { body: profile('free') },
      '/microsoft/status': () => ({ body: connected ? {
        connected: true,
        profile: {
          gamertag: 'ConsentPlayer', gamerscore: 9876, account_tier: 'Gold',
          last_checked_at: '2026-09-09T20:00:00+00:00'
        },
        capabilities: { oauth_configured: true, game_pass_entitlement_access: false },
        watermark: 'Provided by @yorichiiprime', signature: GOOD_SIG
      } : disconnected(true) }),
      '/microsoft/disconnect': () => { connected = false; return { body: { message: 'disconnected' } }; }
    };
    const { document: d, calls, pageErrors } = makeDom(routes, { initialSession: true });
    await tick(45);
    ok('connected badge renders', /Xbox profile connected/.test(text(d, 'xbox-status')));
    ok('real profile fields render', /ConsentPlayer/.test(text(d, 'xbox-result')) && /9876/.test(text(d, 'xbox-result')));
    ok('well-formed server signature is described honestly', /Server signature present/.test(text(d, 'xbox-result')));
    ok('refresh link remains official backend OAuth route', $(d, 'btn-ms-connect').getAttribute('href') === '/microsoft/connect' && /Refresh/.test($(d, 'btn-ms-connect').textContent));
    ok('disconnect action is visible', !hidden(d, 'btn-ms-disconnect'));
    click(d, 'btn-ms-disconnect'); await tick(35);
    ok('disconnect POST is sent', calls.some(c => c.pathname === '/microsoft/disconnect' && c.method === 'POST'));
    ok('UI becomes disconnected after response', /Not connected/.test(text(d, 'xbox-status')) && hidden(d, 'btn-ms-disconnect'));
    ok('no page errors in connection lifecycle', pageErrors.length === 0, JSON.stringify(pageErrors));
  }
  {
    const routes = {
      '/user/me': { body: profile() },
      '/microsoft/status': { body: disconnected(false) }
    };
    const { document: d } = makeDom(routes, { initialSession: true });
    await tick(40);
    ok('unconfigured OAuth has a clear operator message', /MICROSOFT_CLIENT_ID/.test(text(d, 'xbox-result')));
    ok('unconfigured OAuth link is disabled', !$(d, 'btn-ms-connect').hasAttribute('href') && $(d, 'btn-ms-connect').getAttribute('aria-disabled') === 'true');
  }
  {
    const hostile = {
      connected: true,
      profile: { gamertag: '<img src=x onerror="window.__xss=1">', gamerscore: '<script>bad()<\/script>' },
      capabilities: { oauth_configured: true }, watermark: 'bad', signature: 'not-valid'
    };
    const { document: d, window: w } = makeDom({ '/user/me': { body: profile() }, '/microsoft/status': { body: hostile } }, { initialSession: true });
    await tick(40);
    const result = $(d, 'xbox-result');
    ok('profile data is rendered with textContent (no XSS nodes)', !result.querySelector('img') && !result.querySelector('script') && w.__xss !== 1);
    ok('malformed signature gets a warning', /Malformed signature/.test(result.textContent));
  }

  section('6. API key regeneration');
  {
    const routes = {
      '/user/me': { body: profile() },
      '/microsoft/status': { body: disconnected(true) },
      '/user/key/revoke': { body: { api_key: 'xbsp_NEW_FULL_KEY' } }
    };
    const { document: d, window: w, calls } = makeDom(routes, { initialSession: true });
    await tick(40);
    click(d, 'btn-revoke');
    ok('rotation requires explicit confirmation', !hidden(d, 'revoke-confirm'));
    click(d, 'btn-revoke-yes'); await tick(35);
    ok('rotation endpoint called', calls.some(c => c.pathname === '/user/key/revoke' && c.method === 'POST'));
    ok('new key is shown and copy enabled', text(d, 'api-key') === 'xbsp_NEW_FULL_KEY' && !$(d, 'btn-copy-key').disabled);
    ok('rotated key is not persisted', w.localStorage.getItem('xbsp_api_key') === null);
  }

  section('7. Admin table and secret masking');
  {
    const routes = {
      '/admin/users': { body: { users: [
        { id: 1, email: 'a@example.com', tier: 'pro', is_active: 1, daily_usage: 0, daily_limit: 100, audit_events: 1, api_key_preview: 'xbsp_abcd…1234' },
        { id: 2, email: 'b@example.com', tier: 'free', is_active: 1, daily_usage: 0, daily_limit: 2, audit_events: 0, api_key_preview: 'xbsp_efgh…5678' }
      ] } }
    };
    const { document: d, calls, pageErrors } = makeDom(routes);
    await tick(); click(d, 'admin-trigger');
    ok('admin is hidden until explicitly opened', !hidden(d, 'admin-section'));
    submit(d, 'admin-form'); await tick(5);
    ok('admin key required client-side', /Enter the admin API key/.test(text(d, 'admin-msg')));
    set(d, 'admin-key', 'qa-admin'); submit(d, 'admin-form'); await tick(25);
    const request = calls.find(c => c.pathname === '/admin/users');
    ok('admin key is sent only in X-Admin-Key header', request && request.headers['X-Admin-Key'] === 'qa-admin');
    ok('admin users render in table', !!$(d, 'admin-output').querySelector('table') && /a@example.com/.test(text(d, 'admin-output')));
    ok('full secret material is absent', !/FULL|password_hash|device_fingerprint/.test(text(d, 'admin-output')));
    ok('admin rendering has no page errors', pageErrors.length === 0, JSON.stringify(pageErrors));
  }

  section('8. Static security, accessibility and production checks');
  ok('no target-account password field exists', !/id="check-pass"|Account Password|Run Check/.test(HTML));
  ok('no proxy input or proxy rotation copy exists', !/id="check-proxies"|proxies queued/i.test(HTML));
  ok('no browser HMAC secret exists', !/HMAC_SECRET|dev-secret-change-in-prod/.test(HTML));
  ok('browser auth never loads an API key from storage', !/storeGet\(['"]xbsp_api_key/.test(HTML));
  ok('official OAuth route is linked', /href="\/microsoft\/connect"/.test(HTML));
  ok('Game Pass partner limitation is disclosed', /Partner Center publishers/.test(HTML));
  ok('noscript fallback exists', HTML.includes('<noscript>'));
  ok('responsive viewport exists', /name="viewport"/.test(HTML));
  ok('reduced motion is respected', /prefers-reduced-motion/.test(HTML));
  ok('all buttons have explicit type', !/<button(?![^>]*\btype=)/.test(HTML));
  ok('async regions use aria-live', (HTML.match(/aria-live="polite"/g) || []).length >= 4);
  ok('external account link protects opener', /target="_blank" rel="noopener noreferrer"/.test(HTML));
  ok('production page has no seeded demo login', !/demo@example\.com|password123\s*\(premium\)/.test(HTML));

  console.log('\n' + '='.repeat(60));
  console.log(`  \x1b[1m${pass} passed, ${fail} failed\x1b[0m   (frontend DOM)`);
  if (failures.length) { console.log('\n  Failures:'); failures.forEach(item => console.log('   - ' + item)); }
  console.log('='.repeat(60));
  process.exit(fail ? 1 : 0);
})().catch(error => { console.error('HARNESS CRASH:', error); process.exit(2); });
