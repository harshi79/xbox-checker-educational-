/**
 * Cross-language signature audit — proves the browser's canonical JSON
 * matches Python's json.dumps(sort_keys=True, separators=(",",":")) exactly.
 *
 * Extracts the SIGNATURE CORE block from static/index.html, signs the same
 * payloads with Python (api/watermark.py) and Node crypto, and asserts the
 * signatures agree. This is the "do the docs actually work?" test.
 *
 * Run (from repo root, needs node + a python with the deps installed):
 *   node qa-signature.test.mjs
 *   PYTHON=.venv/bin/python node qa-signature.test.mjs   # if python3 has no deps
 */
import { readFileSync } from 'node:fs';
import { createHmac } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert';

const SECRET = 'cross-test-secret';
const WATERMARK_TEXT = 'Provided by @yorichiiprime';
const py = process.env.PYTHON || 'python3';

// The signed object is the /check RESPONSE: payload + watermark (added by
// watermark.sign_response on the server, present in the browser response).
const withWatermark = p => ({ ...p, watermark: WATERMARK_TEXT });

const html = readFileSync(new URL('./static/index.html', import.meta.url), 'utf8');
const m = html.match(/\/\* ===== SIGNATURE CORE[^*]*\*\/([\s\S]*?)\/\* ===== END SIGNATURE CORE ===== \*\//);
assert(m, 'SIGNATURE CORE block not found in static/index.html');
const { canonJson, canonCandidates } = new Function(`${m[1]}\n; return { canonJson, canonCandidates };`)();

// Sign with the real Python module (same code the API uses).
// Takes RAW json text so we can control float tokenisation (4.0 stays a float).
function pythonSignRaw(rawJson) {
  const script = `
import json, sys
sys.path.insert(0, '.')
from api import watermark
payload = json.load(sys.stdin)
print(watermark.sign_response(payload)['signature'])
`;
  return execFileSync(py, ['-c', script], {
    input: rawJson,
    env: { ...process.env, WATERMARK_SECRET: SECRET },
    cwd: new URL('.', import.meta.url).pathname,
  }).toString().trim();
}
const pythonSign = payload => pythonSignRaw(JSON.stringify(payload));

function nodeHmac(message) {
  return createHmac('sha256', SECRET).update(message, 'utf8').digest('hex');
}

// Realistic response shapes straight from checker.py (unicode gamertag,
// empty lists, missing keys, integral floats, int duration 0).
const payloads = [
  { status: 'PREMIUM', duration: 4.213572490692139,
    data: { gamertag: 'Γαmertag ✓ € 2026', gamerscore: 12345,
            subscriptions: ['XBOX GAME PASS ULTIMATE', 'EA PLAY'], gamepass: 'XBOX GAME PASS ULTIMATE' } },
  { status: 'FREE', duration: 3.141592653589793, data: { gamertag: 'Pvp_N00b', gamerscore: 0, subscriptions: [] } },
  { status: 'BAD', duration: 1.5 },
  { status: '2FA', duration: 2.718281828459045 },
  { status: 'BANNED', duration: 0.9999999999999999 },
  { status: 'ERROR', duration: 0, error: 'TimeoutError: [Errno -3] Temporary failure in name resolution' },
  // integral float: Python writes "4.0", JSON/JS reads 4 — exercises the .0 retry candidate
  { status: 'FREE', duration: 4.0, data: { gamertag: 'IntegralFloat', gamerscore: 7 } },
];

let pass = 0, fail = 0;
const failures = [];
function ok(name, cond, extra) {
  if (cond) { pass++; console.log('  \x1b[32mPASS\x1b[0m ' + name); }
  else { fail++; failures.push(name); console.log('  \x1b[31mFAIL\x1b[0m ' + name + (extra ? '\n        -> ' + extra : '')); }
}

console.log('\n\x1b[1mA. JS canonical JSON === Python json.dumps (via real watermark module)\x1b[0m');
for (const p of payloads) {
  const expected = pythonSign(withWatermark(p));
  const cands = canonCandidates(withWatermark(p));
  const match = cands.map(nodeHmac).includes(expected);
  ok(`signature matches: ${p.status} (duration ${p.duration}${p.data ? ', data' : ''}${p.error ? ', error' : ''})`,
     match, `expected ${expected}\n        candidates ${cands.map(nodeHmac).join('\n               ')}`);
}

console.log('\n\x1b[1mB. Integral-float edge needs the .0 retry candidate\x1b[0m');
{
  // Raw JSON keeps the "4.0" token so Python parses a *float* 4.0; JS JSON.parse
  // turns it into the number 4 — exactly the mismatch the retry candidate fixes.
  const raw = '{"status":"FREE","duration":4.0,"data":{"gamertag":"IntegralFloat","gamerscore":7},"watermark":"Provided by @yorichiiprime"}';
  const expected = pythonSignRaw(raw);
  const p = JSON.parse(raw);
  ok('python sees a float (signature differs from int version)',
     expected !== pythonSignRaw(raw.replace('4.0', '4')));
  const cands = canonCandidates(p);
  ok('two candidates generated', cands.length === 2, JSON.stringify(cands));
  ok('plain candidate does NOT match (proves the bug exists)', nodeHmac(cands[0]) !== expected);
  ok('.0 retry candidate matches', nodeHmac(cands[1]) === expected);
}

console.log('\n\x1b[1mC. Tamper detection\x1b[0m');
{
  const p = withWatermark({ status: 'PREMIUM', duration: 1.2345, data: { gamertag: 'TamperMe', gamerscore: 1 } });
  const expected = pythonSign(p);
  // mirror of the browser verifySignature(): does ANY candidate hash to this sig?
  const verifyLike = (payload, sig) => canonCandidates(payload).some(c => nodeHmac(c) === sig);
  ok('original signature verifies', verifyLike(p, expected));
  const tampered = { ...p, signature: expected, data: { ...p.data, gamertag: 'Hacker' } };
  ok('tampered value rejected', !verifyLike(tampered, expected));
  const rotated = expected.slice(2) + expected.slice(0, 2);
  ok('rotated signature rejected', !verifyLike(p, rotated));
}

console.log('\n' + '='.repeat(60));
console.log(`  \x1b[1m${pass} passed, ${fail} failed\x1b[0m   (JS<->Python signature audit)`);
if (failures.length) {
  console.log('\n  Failures:');
  for (const f of failures) console.log(`   - ${f}`);
}
console.log('='.repeat(60));
process.exit(fail ? 1 : 0);
