/**
 * QA preview harness — FRONTEND ONLY.
 *
 * Serves static/index.html plus in-memory stubs of the endpoints the page calls,
 * so the UI can be clicked through end-to-end in a browser without a live backend.
 * This is a test fixture for visual/interaction QA. It is NOT part of the product
 * and replaces nothing in the deployed application.
 *
 * Run: node qa-mock-preview.mjs   (listens on 0.0.0.0:8080)
 */
import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 8080);
const SECRET = 'dev-secret-change-in-prod';      // mirrors the constant in index.html
const WATERMARK = 'Provided by @yorichiiprime';

/* --- users held in memory only --- */
const users = new Map();   // email -> {email, pass, api_key, tier, daily_usage, daily_limit, fp, created_at}
const byKey = new Map();   // api_key -> email
const ADMIN_KEY = 'demo-admin-key';

const rnd = (n = 24) => crypto.randomBytes(n).toString('hex').slice(0, n);

function canonicalJson(v) {
  if (v === undefined || v === null) return 'null';
  if (typeof v === 'number' || typeof v === 'boolean' || typeof v === 'string') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(canonicalJson).join(',') + ']';
  return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonicalJson(v[k])).join(',') + '}';
}
function sign(payload) {
  return crypto.createHmac('sha256', SECRET).update(canonicalJson(payload), 'utf8').digest('hex');
}

/* Seed a demo account so login can be tried immediately. */
(function seed() {
  const u = {
    email: 'demo@example.com', pass: 'password123', api_key: 'xbp_demo_1111222233334444',
    tier: 'premium', daily_usage: 7, daily_limit: 100, fp: 'a1b2c3d4e5f60718', created_at: '2026-01-04T10:00:00Z'
  };
  users.set(u.email, u); byKey.set(u.api_key, u.email);
  const p = {
    email: 'admin@example.com', pass: 'password123', api_key: 'xbp_admin_9999888877776666',
    tier: 'pro', daily_usage: 1240, daily_limit: 5000, fp: 'ffeeddccbbaa9988', created_at: '2025-11-19T08:30:00Z'
  };
  users.set(p.email, p); byKey.set(p.api_key, p.email);
  const f = {
    email: 'free@example.com', pass: 'password123', api_key: 'xbp_free_0000111122223333',
    tier: 'free', daily_usage: 10, daily_limit: 10, fp: '0123456789abcdef', created_at: '2026-03-11T16:45:00Z'
  };
  users.set(f.email, f); byKey.set(f.api_key, f.email);
})();

function json(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}
function readBody(req) {
  return new Promise((resolve) => {
    let buf = '';
    req.on('data', (c) => { buf += c; if (buf.length > 1e6) req.destroy(); });
    req.on('end', () => { try { resolve(buf ? JSON.parse(buf) : {}); } catch { resolve({}); } });
  });
}
function authUser(req) {
  const h = req.headers['authorization'] || '';
  const key = h.startsWith('Bearer ') ? h.slice(7).trim() : null;
  if (!key || !byKey.has(key)) return null;
  return users.get(byKey.get(key));
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const p = url.pathname;

  /* ---------- static ---------- */
  if (p === '/' || p === '/index.html' || p === '/static/index.html') {
    const html = fs.readFileSync(path.join(__dirname, 'static', 'index.html'));
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(html);
  }

  /* ---------- auth ---------- */
  if (p === '/auth/register' && req.method === 'POST') {
    const b = await readBody(req);
    if (!b.email || !b.password) return json(res, 422, { detail: 'email and password are required' });
    if (String(b.password).length < 8) return json(res, 422, { detail: 'Password must be at least 8 characters' });
    if (users.has(String(b.email).toLowerCase())) return json(res, 409, { detail: 'An account with that email already exists' });
    const fp = String(b.device_fingerprint || '');
    for (const u of users.values()) if (fp && u.fp === fp) return json(res, 409, { detail: 'This device already has an account' });
    const u = {
      email: String(b.email).toLowerCase(), pass: b.password, api_key: 'xbp_' + rnd(20),
      tier: 'free', daily_usage: 0, daily_limit: 10, fp: fp || rnd(16), created_at: new Date().toISOString()
    };
    users.set(u.email, u); byKey.set(u.api_key, u.email);
    return json(res, 200, { api_key: u.api_key, tier: u.tier });
  }

  if (p === '/auth/login' && req.method === 'POST') {
    const b = await readBody(req);
    const u = users.get(String(b.email || '').toLowerCase());
    if (!u || u.pass !== b.password) return json(res, 401, { detail: 'Incorrect email or password' });
    return json(res, 200, { api_key: u.api_key, tier: u.tier });
  }

  /* ---------- user ---------- */
  if (p === '/user/me' && req.method === 'GET') {
    const u = authUser(req);
    if (!u) return json(res, 401, { detail: 'Invalid or revoked API key' });
    return json(res, 200, { email: u.email, tier: u.tier, daily_usage: u.daily_usage, daily_limit: u.daily_limit });
  }

  if (p === '/user/key/revoke' && req.method === 'POST') {
    const u = authUser(req);
    if (!u) return json(res, 401, { detail: 'Invalid or revoked API key' });
    byKey.delete(u.api_key);                 // old key dies immediately
    u.api_key = 'xbp_' + rnd(20);
    byKey.set(u.api_key, u.email);
    return json(res, 200, { api_key: u.api_key });
  }

  /* ---------- check ---------- */
  if (p === '/check' && req.method === 'POST') {
    const u = authUser(req);
    if (!u) return json(res, 401, { detail: 'Invalid or revoked API key' });
    if (u.daily_usage >= u.daily_limit) return json(res, 429, { detail: 'Daily limit reached — upgrade your tier' });
    const b = await readBody(req);
    u.daily_usage += 1;
    const proxies = Array.isArray(b.proxies) ? b.proxies : [];
    const hit = String(b.email || '').toLowerCase().endsWith('@hit.example.com');
    const payload = {
      status: hit ? 'hit' : 'bad',
      email: String(b.email || ''),
      gamertag: hit ? 'DemoPlayer' : null,
      proxy_used: proxies.length ? proxies[0] : 'direct',
      checked_at: new Date().toISOString(),
      watermark: WATERMARK
    };
    return json(res, 200, Object.assign({}, payload, { signature: sign(payload) }));
  }

  /* ---------- admin ---------- */
  if (p === '/admin/users' && req.method === 'GET') {
    if (req.headers['x-admin-key'] !== ADMIN_KEY) return json(res, 403, { detail: 'Invalid admin key' });
    return json(res, 200, {
      users: [...users.values()].map((u) => ({
        email: u.email, tier: u.tier, daily_usage: u.daily_usage, daily_limit: u.daily_limit,
        created_at: u.created_at, api_key: u.api_key, device_fingerprint: u.fp
      }))
    });
  }

  return json(res, 404, { detail: 'Not Found' });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`Frontend QA preview on http://0.0.0.0:${PORT}`);
  console.log('');
  console.log('  Demo logins   : demo@example.com / password123   (premium)');
  console.log('                  admin@example.com / password123  (pro)');
  console.log('                  free@example.com  / password123  (free, limit reached)');
  console.log('  Admin key     : demo-admin-key');
  console.log('  Green-check   : use an email ending in @hit.example.com');
});
