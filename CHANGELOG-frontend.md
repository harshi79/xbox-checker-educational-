# Frontend QA Changelog — `static/index.html`

Scope: `static/index.html` only. No backend file was opened, modified, or commented on.
All endpoint paths, HTTP methods, request bodies and header names were left exactly as
the existing page already used them (`/auth/register`, `/auth/login`, `/user/me`,
`/user/key/revoke`, `/check`, `/admin/users`).

## Blocker fixes (functionality was broken)

- **Login could never succeed.** The success branch tested `data.access_token` but then
  stored `data.api_key`, so a correct login always fell into the error path. Now keys on
  `api_key` and tolerates `access_token`/`key` as fallbacks.
- **The login form was unreachable.** `showRegister()` existed but there was no counterpart,
  and nothing ever removed `hidden` from `#login-form`. Returning users were locked out of
  the product entirely. Replaced with a proper Register/Login tab pair (`aria-selected` wired).
- **The admin panel was dead UI.** `#admin-section` carried `hidden` and no code ever removed
  it, so `/admin/users` could not be reached from the page at all. Added a discreet footer
  trigger plus a `Ctrl/⌘+Shift+A` shortcut, and a Hide button.
- **Signature verification could never pass.** `JSON.stringify(obj, arrayOfKeys)` was being
  used as if the array ordered keys — it is a *replacer* that filters them. Proven by test:
  the watermark was silently dropped and key order was never sorted, so the canonical string
  never matched. Replaced with a real recursive sorted-key canonicaliser.
- **`crypto.subtle` crashed on non-secure origins**, and `signature.match()` threw when no
  signature was returned. Both now guarded.
- **`getFingerprint()` ran at parse time with no guard** — a null canvas context would throw
  and kill the whole script, leaving a dead page. Every signal is now individually guarded
  with a persisted random fallback, so a fingerprint is always produced.
- **Zero error handling existed** (`try` count: 0, `res.ok` count: 0). Every request can now
  fail without breaking the page.

## Error handling (req 9)

- Central `api()` helper: checks `res.ok`, parses non-JSON error bodies safely, and maps
  400/401/403/404/409/413/422/429/500/502/503/504 to readable messages.
- Network failures and a 60s request timeout (AbortController) produce friendly text.
- 401 on an authenticated call clears the dead key and returns the user to the login screen
  instead of showing an empty dashboard.
- Buttons get a spinner + disabled state, so no double-submit and no stuck "Checking…".
- Global `error` / `unhandledrejection` handlers surface anything unexpected as a toast.
- Result rendering is wrapped, so a malformed response still shows the raw payload.
- `localStorage` access is wrapped — private-browsing modes no longer break boot.
- `<noscript>` fallback and an `init()` guard mean a blank screen is no longer possible.

## Security / correctness

- **XSS closed.** All server-provided values (`detail`, `status`, `watermark`, payload JSON,
  admin rows) are now rendered via `textContent` instead of `innerHTML`. Verified with a
  hostile payload containing `<img onerror>`, `<script>` and `<b>` — no elements injected,
  no handlers fired.
- Client-side HMAC is labelled honestly: the secret ships in the page, so a green check is an
  integrity/plumbing assertion, **not** proof of authenticity.
- Verification now reports three states — valid (green), mismatch (red), and a neutral
  "cannot verify here" when there is no signature or no Web Crypto — instead of a false ❌.
- Accepts hex **and** base64 signatures.
- Admin table masks `api_key`, `device_fingerprint` and any password-like column.
- Added `referrer: no-referrer` (the form carries credentials) and cleared the password field
  after a successful login.

## Proxy input

- Splitting on `\n` left a stray `\r` on every line from a CRLF textarea — proven by test.
  Now splits on `/\r?\n/`, trims, drops blanks and `#` comments, and de-duplicates.
- Live counter shows how many proxies are queued.

## Dashboard (req 3, 4)

- API key shown in full with a working Copy button (Clipboard API + `execCommand` fallback).
- Tier badge with distinct colours for `free` / `premium` / `pro`, plus an `unknown` fallback;
  no longer throws when `tier` is missing.
- Usage rendered as `used / limit checks today` with a progress meter; handles a missing or
  zero limit.
- Key regeneration uses a real inline confirmation panel (works on mobile, unlike `confirm()`);
  the old key is removed from storage before the new one is adopted, and the profile is
  reloaded on the new token. Verified over HTTP: the old key returns 401, the new one 200.
- Added Refresh and Sign out.

## Check results (req 5, 8)

- Structured `Status / Watermark / Signature / Client-side HMAC` readout plus a raw payload
  block, all built as DOM nodes.
- Watermark is compared against the expected string `Provided by @yorichiiprime` and flagged
  green or red.
- Client-side validation before submitting; client-side email/password validation on both
  auth forms.

## Visual & responsive (req 1)

- Dark gradient theme with layered radial gradients, consistent spacing scale, card borders,
  gradient headings, focus rings and a toast layer.
- Mobile breakpoint at 640px: single-column grid, stacked key/value rows, full-width buttons.
- Inputs set to `font-size: 16px` — below 16px iOS Safari auto-zooms the page on focus.
- Grid uses `minmax(min(220px, 100%), 1fr)` so it can never overflow a narrow viewport.
- `overflow-wrap: anywhere` / `word-break: break-all` on keys, code and `<pre>`; horizontal
  scroll container for the admin table; `overflow-x: hidden` guard on `body`.
- `color-scheme` and `theme-color` declared, safe-area padding, `prefers-reduced-motion`
  respected, inline favicon (removes a 404 from the console).

## Accessibility

- Every input has a real `<label for>` (was placeholder-only), `autocomplete` and `inputmode`.
- `aria-live="polite"` on all async message regions, `role="alertdialog"` on the confirmation,
  `:focus-visible` rings, explicit `type` on every button, `Escape` cancels the confirmation.
- Inline `onclick` handlers removed in favour of `addEventListener` (CSP-friendly); real
  `<form>` elements give Enter-to-submit.

## Verification

Two harnesses were added (dev-only; not served by the app, not part of the deploy):

- `qa-frontend.test.js` — loads the real page in jsdom with a stubbed `fetch`. **119 assertions.**
- `qa-live.test.js` — loads the real page in jsdom against `qa-mock-preview.mjs` over real
  HTTP (real status codes, real JSON, real Web Crypto). **41 assertions.**
- `qa-mock-preview.mjs` — in-memory stub server so the UI can be clicked through in a browser.

```bash
npm install --no-save --prefix /tmp/jstest jsdom
node qa-mock-preview.mjs &      # port 8080
node qa-frontend.test.js        # 119 passed
node qa-live.test.js            #  41 passed
```

Both suites were run twice back-to-back against a shared server to confirm they are
state-independent: 160/160 on each pass. HTML structure was also checked — 0 unclosed tags,
0 duplicate ids, and all 44 `getElementById` references resolve to real elements.

Not covered: no headless browser is available in this environment, so real-viewport rendering
was not screenshotted. Layout safety was verified through the CSS rules above and jsdom DOM
assertions rather than pixel comparison.
