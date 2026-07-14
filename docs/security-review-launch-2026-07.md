# Compbird pre-launch security review — 2026-07-14

Scope: the standalone Compbird app (`C:/Users/zach/Desktop/Compbird`, HEAD `6445a66`) —
auth/session libs, every `/api/compbird/*` + `/api/billing/*` route, injection/SSRF/XSS
surfaces, prod headers/config, secrets, DoS. Prior audits covered the sibling host app;
this review is Compbird-specific. Every finding cites file:line (pre-fix line numbers).
**Deploy target: RAILWAY** (app + engine services, Railway edge TLS/proxy, private
networking) — the Railway-specific trust assumptions are called out inline and
collected in the "Railway deployment notes" section at the end.

**Verdict: launch-ready after the fixes below.** No P0. Two P1s (both fixed), six P2s
(four fixed; one open with a clear post-launch remediation, one open-accepted), and P3
notes. The auth core
(scrypt, HMAC sessions, two-dimension throttling, timing-safe decoys, hashed single-use
reset tokens) and the paywall enforcement (server-side redaction, tokenized PDF names,
clamp-at-parse validation) are in genuinely good shape.

---

## P0 — none found

Checked explicitly and refuted:

- **PDF path traversal** — `src/app/api/compbird/pdf/[name]/route.ts:74-88` rejects
  `..` / `/` / `\`, length-caps to 255, allows only `.pdf`, prefixes to the compbird
  namespace, and requires a signed-in `cma.evidence` account. Solid.
- **Client-controlled Stripe price** — `src/app/api/billing/checkout/route.ts:52` uses
  `subscriptionPriceId()` from env only; no client input reaches `line_items`.
- **Webhook forgery** — `src/app/api/billing/webhook/route.ts:71` verifies the raw body
  against `STRIPE_WEBHOOK_SECRET` (`constructEvent`, default 300s replay tolerance);
  tier changes happen nowhere else. `checkout.session.completed` re-reads the LIVE
  subscription status before granting (`:95-98`), so a replayed event can't revive a
  cancelled sub.
- **Override/paywall bypass on generate** — brand allowlist (`src/lib/cma/engine.ts:429`,
  `:465`), server-decided `aiHygiene === true` (`:481`), legacy `subjectSqft` lever
  explicitly stripped (`:482`), overrides clamped to `OVERRIDE_BOUNDS` + audited
  (`src/lib/cma/overrides.ts:125-145`, `src/lib/cma/override-audit.ts`), narrative
  fields length-capped and engine-HTML-escaped (verified invoked in MLS Bot
  `scripts/build_cma.py:2023` execText, `:2138` strategyText, `:269` disclosure,
  `:2245` title).
- **SQL/DuckDB injection** — search uses prepared FTS5 statements with an
  alnum-token-only MATCH builder (`src/lib/cma/search-index.ts:59,106-114`); the
  markets runner interpolates only values read from its own parquet, quote-escaped
  (`src/lib/cma/engine.ts:708-709`); engine spawns pass user strings via env/JSON,
  never a shell.
- **SSRF via streetview** — `src/app/api/compbird/streetview/route.ts` hits a fixed
  Google host with numeric, bounds-checked lat/lng only (`src/lib/compbird/validate.ts:88-105`).
- **IDOR on portfolio** — every GET/DELETE is `accountId`-scoped
  (`src/app/api/compbird/portfolio/route.ts:106-110,148-150`); foreign ids 404.
- **Secrets in client bundles** — grepped `.next/static` for
  `SESSION_SECRET|sk_live|sk_test|whsec_|RESEND|STRIPE_SECRET`: zero hits.
- **Session fixation / privilege staleness** — a fresh token is minted on every login
  (`src/actions/auth.ts:102`); `getActiveContext` re-validates membership, role and
  super-admin flag against the DB on every request (`src/lib/session.ts:45-67`), so
  removing a membership revokes access immediately despite the 14-day token.

---

## P1 — fixed in this review

### 1. No security headers at all — **FIXED**
`next.config.ts` shipped zero headers: no CSP, no HSTS, no `X-Content-Type-Options`,
no frame or referrer policy. Notably, `/reset-password/<token>` pages could leak the
full token URL via the Referer header to any cross-origin resource.

**Fix:** `src/lib/security-headers.ts` (new, pure + unit-tested) wired into
`next.config.ts headers()` for every route, plus `poweredByHeader: false`:

- `Content-Security-Policy` — `default-src 'self'`; `object-src 'none'`;
  `base-uri/form-action/frame-ancestors 'self'`. Documented allowances only:
  - `img-src`: `https://*.tile.openstreetmap.org` (Leaflet tiles,
    `src/components/geo/leaflet-map.tsx:78`) + Meta/Google beacon origins + `data: blob:`
    (Leaflet marker icons).
  - `script-src`: `'unsafe-inline'` (Next inline bootstrap/RSC payload — a nonce
    pipeline is a post-launch follow-up) + `connect.facebook.net` +
    `www.googletagmanager.com` (the pixel loaders in
    `src/components/marketing/pixels.tsx:56,70`).
  - `connect-src`/`frame-src`: the Meta/Google conversion endpoints. Street View is
    proxied same-origin, so `maps.googleapis.com` is deliberately NOT allowed.
  - Dev-only: `'unsafe-eval'` (React Refresh) and `ws:` (HMR); absent in prod.
- `Strict-Transport-Security: max-age=15552000; includeSubDomains` (prod only).
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy: strict-origin-when-cross-origin` (also trims the reset-token path
  from cross-origin requests), `Permissions-Policy` denying camera/mic/geo/payment.

Tests: `src/lib/security-headers.test.ts` (7 tests: baseline presence, HSTS prod-only,
locked directives, no dev relaxations in prod, documented allowances, script-src
exact-set).

### 2. CSV formula injection in the portfolio export — **FIXED**
`src/components/compbird/portfolio/csv.ts:180-184` (`csvCell`) did RFC-4180 quoting
only. The portfolio **label** is arbitrary user input (typed or CSV-uploaded), and
label/address/parcel land in the exported `portfolio-*.csv` — a label like
`=HYPERLINK("http://evil","...")` or `=cmd|' /C ...'!A0` executes when the analyst
opens the download in Excel/Sheets.

**Fix:** string-typed cells starting with `= + - @` (or a tab/CR-smuggled variant) are
prefixed with a single quote — the spreadsheet-standard neutralizer. Numeric figure
columns arrive as numbers and are untouched (negative totals stay `-5`, not `'-5`).

Tests: `src/components/compbird/portfolio/csv.injection.test.ts` (6 tests: each trigger
char, address/parcel cells, numbers untouched, plain text byte-identical, blanks).

---

## P2

### 3. No request-size limit on the JSON POST routes — **FIXED**
Next route handlers have no default body cap and Caddy imposes none by default, so
`await req.json()` on `/generate`, `/preview`, `/profile`, `/portfolio` was an
unauthenticated memory-pressure lever (rate limiter allows 4-15 bodies/min/IP × any
size).

**Fix:** `src/lib/compbird/body-limit.ts` — 1 MB Content-Length gate → 413 before the
body is read; wired into all four JSON POST routes. Best-effort by design (chunked
bodies without the header still hit the per-field caps in `validate.ts`).
Tests: `src/lib/compbird/body-limit.test.ts` (5 tests).

**Railway note:** Railway's edge exposes NO user-configurable request-size cap, so this
app-layer gate is the PRIMARY control in production, not a convenience. (If the legacy
Caddy/VPS stack is ever used instead, add `request_body { max_size 2MB }` there as a
backstop — it also covers chunked uploads and non-JSON routes.)

### 4. Billing return-URLs built from the client Origin header — **FIXED**
`src/app/api/billing/checkout/route.ts:45` and `portal/route.ts:31` preferred the
request `Origin` header over `NEXT_PUBLIC_APP_URL` when building Stripe
`success_url`/`return_url`. Risk is modest (sameSite=lax blocks cross-site cookie
POSTs) but a forged header could steer the post-payment redirect off-site.
**Fix:** env-first, header only as a dev fallback. Ensure
`NEXT_PUBLIC_APP_URL=https://compbird.com` is set on the Railway app service.

### 5. Password change/reset does not invalidate existing sessions — **OPEN**
The `cb_session` token is a stateless 14-day HMAC envelope (`src/lib/auth.ts:11,84`).
`changePassword` (`src/actions/account.ts:77-80`) and `resetPassword`
(`src/actions/auth.ts:255-266`) update the hash but an attacker holding a stolen
session cookie survives the victim's password reset for up to 14 days. (Deleting the
Membership row DOES revoke — `getActiveContext` re-checks it per request — but there is
no user-facing path to that.)

**Remediation (small schema change, post-launch OK):** add
`AuthUser.sessionsValidAfter DateTime` bumped on password change/reset; embed `iat` in
the token (or derive it as `exp - SESSION_TTL_SECONDS`) and reject tokens issued before
it in `getActiveContext`. Also gives `logout everywhere` for free.

### 6. Stripe subscription webhook: no out-of-order event guard — **FIXED**
`customer.subscription.updated/deleted` (`webhook/route.ts:142-179`) applied whatever
state the event carried. Stripe does not guarantee delivery order: a delayed `updated`
(status=active) arriving after `deleted` would re-grant SOLO until the next event.
Signature verification limits this to genuine Stripe events, so it was an integrity nit
rather than an attack — but the fix is canonical Stripe practice and small.

**Fix:** the subscription handler now re-`retrieve`s the LIVE subscription and applies
THAT state (cancelled subs stay retrievable, status=canceled), making event handling
idempotent and order-independent — any replayed/reordered event converges on the live
state. The tier rule was extracted to a pure module, `src/lib/billing-grant.ts`
(`tierDecisionFor`: active/trialing → paid tier, everything else → FREE; deny-by-default
on garbage statuses), re-exported through `src/lib/stripe.ts` for compatibility.
Tests: `src/lib/billing-grant.test.ts` (6 tests covering every status class).

### 7. checkout.session.completed grants SOLO when the live re-read fails — **FIXED**
`webhook/route.ts:92-100`: if `subscriptions.retrieve` threw, the handler fell back
to granting `subscribedTier()` with `status "active"` — a transient Stripe API failure
during a checkout whose subscription was instantly cancelled would leave a paid tier
until the next subscription event. **Fix:** the optimistic fallback is removed; a
retrieve failure now bubbles to the outer catch → 500 → Stripe retries the webhook.
A paid tier is never granted on an unverified subscription state.

### 8. In-memory rate limiters are single-process — **OPEN (accepted constraint)**
`auth-ratelimit.ts` / `compbird-ratelimit.ts` are module-level Maps: counters reset on
restart/deploy and do NOT aggregate across replicas. Correct for the planned
single-container deploy — **on Railway, keep the app service at ONE replica**; a future
horizontal scale-out must move these to a shared store first. The XFF trust model
(`auth-ratelimit.ts:75-95`, rightmost-hop only) is correct **provided the edge appends
(or replaces the header with) the true peer address** — Railway's edge proxy does
exactly that, so the rightmost entry is the trusted hop and left-most client-forged
entries are ignored. First-deploy sanity check for the deploy owners: `curl -H
"X-Forwarded-For: 1.2.3.4" https://compbird.com/...` and confirm throttle keys derive
from your real IP, not 1.2.3.4 (the per-email + global-signup buckets hold regardless).

---

## P3 — notes and accepted risks

9. **PDF tokens are capability URLs, not account-bound.** Any signed-in Pro account
   that learns another account's `CMA_compbird_<48-hex>.pdf` token can fetch it
   (`pdf/[name]/route.ts:84`). Tokens are 24 random bytes → unguessable/unenumerable;
   acceptable. The `CMA_general_` allowlist prefix exists only for the rename-failure
   fallback (`generate/route.ts:210-223`), where the name is address-derived
   (guessable) but still Pro-gated. Post-launch: persist `pdfName → accountId` and
   scope the stream.
10. **Signup reveals account existence** (`?error=exists`, `auth.ts:137-140`).
    Standard UX tradeoff; throttled per-IP + 30/10-min global cap. Login and
    forgot-password do NOT leak (dummy-hash timing decoy at `auth.ts:89`; uniform
    `?sent=1` at `:223`). Accept.
11. **`sa` flag rides in the token** but is re-read from the DB every request
    (`session.ts:53-56`) and the proxy never trusts it for privilege. No action.
12. **Portfolio labels/errors render in the studio** — React escapes by default and no
    `dangerouslySetInnerHTML` exists outside chart internals (grep-verified). No action.
13. **Prod secrets checklist** (deploy owners — Railway service variables on the app
    service): `SESSION_SECRET` ≥16 chars — enforced at boot (`auth.ts:17-20`), current
    dev value is 41 chars; set `STRIPE_SECRET_KEY` / `STRIPE_PRICE_ID` /
    `STRIPE_WEBHOOK_SECRET`, `RESEND_API_KEY` + verified `MAIL_FROM`,
    `NEXT_PUBLIC_APP_URL=https://compbird.com`. Google Maps key stays server-side
    (streetview proxy) — never `NEXT_PUBLIC_`.
14. **Reset-token hygiene verified good:** 32 random bytes, sha256-only at rest,
    15-min TTL, single-use spent atomically with the password write
    (`auth.ts:254-266`), prior unused tokens retired on re-issue
    (`auth-verification.ts:37-51`). The raw token appears in the emailed URL only; the
    new Referrer-Policy keeps it out of cross-origin Referers.
15. **Cookie flags verified:** httpOnly, `secure` when `NODE_ENV=production` (true in
    the Docker runtime behind Railway's TLS termination — the browser only ever sees
    https, so `secure` is correct), sameSite=lax, path=/, 14-day maxAge
    (`src/actions/auth.ts:51-57`).

---

## Railway deployment notes (security-relevant, for the deploy owners)

- **Client IP / rate limiting.** `getClientIp` (`src/lib/auth-ratelimit.ts`) keys on the
  RIGHT-MOST `x-forwarded-for` entry — the hop the trusted edge appends. Railway's edge
  proxy appends the connecting peer's address (Envoy behavior), so this is correct on
  Railway with zero code change. Do the first-deploy forged-XFF sanity check (P2 #8).
- **One replica.** Both rate limiters and the portfolio runner's in-process Set assume a
  single app process. Keep the Railway app service at 1 replica.
- **Engine reachability + auth.** The app reaches the engine through `CMA_ENGINE_URL`
  (precedence: `COMPBIRD_ENGINE_URL` > `CMA_ENGINE_URL` > `CMA_WORKER_URL` >
  `http://127.0.0.1:8765` — `src/lib/cma/worker.ts:23-29`). Set
  `CMA_ENGINE_URL=http://engine.railway.internal:8765` on the app service. **Set
  `CMA_WORKER_TOKEN` on BOTH services** (app sends it as a Bearer header,
  `worker.ts:53-56`; the engine enforces it): the engine binds `0.0.0.0` on Railway's
  private network, which is shared by every service in the environment — the token keeps
  the engine from being an unauthenticated internal RCE-adjacent surface if any other
  service is ever compromised. Never expose the engine service publicly (no Railway
  public domain on it).
- **Body-size cap.** Railway's edge has no configurable request-size limit — the
  app-layer 1 MB gate (P2 #3) is the primary control.
- **HSTS.** Served by the app (`security-headers.ts`) behind Railway TLS; fine. If a
  custom domain fronted by Cloudflare is added later, keep TLS full-strict so HSTS
  never pins an http-reachable host.
- **SQLite volume.** `DATABASE_URL=file:/data/prod.db` on the app volume — the DB file
  (password hashes, reset-token hashes) lives only on that volume; no bank-grade PII is
  stored (email + scrypt hash + Stripe customer ids).

---

## Fix inventory (this review)

| # | Sev | Finding | Status | Where |
|---|-----|---------|--------|-------|
| 1 | P1 | No security headers (CSP/HSTS/nosniff/frame/referrer) | **Fixed** | `next.config.ts`, `src/lib/security-headers.ts` (+test) |
| 2 | P1 | CSV formula injection in portfolio export | **Fixed** | `src/components/compbird/portfolio/csv.ts` (+test) |
| 3 | P2 | No JSON request-size limit | **Fixed** (app layer) | `src/lib/compbird/body-limit.ts` (+test), 4 routes; Railway edge has no cap knob — app gate is primary |
| 4 | P2 | Client Origin header in Stripe return URLs | **Fixed** | `billing/checkout` + `billing/portal` routes |
| 5 | P2 | Sessions survive password change/reset | Open | needs `sessionsValidAfter` column + iat check (schema change — post-launch) |
| 6 | P2 | Webhook out-of-order subscription events | **Fixed** | live re-retrieve per event; pure `src/lib/billing-grant.ts` (+test) |
| 7 | P2 | Optimistic SOLO grant on retrieve failure | **Fixed** | retrieve failure → 500 → Stripe retries (`billing/webhook`) |
| 8 | P2 | Single-process rate limiting; XFF trust needs an appending edge | Open (accepted) | Railway edge appends peer IP — correct as-is; keep app at 1 replica; forged-XFF check at first deploy |
| 9 | P3 | PDF tokens not account-bound | Open (accepted) | persist pdfName→accountId later |

Verification: all 15 `node:test` suites green (96 tests, incl. 24 new this review),
`tsc --noEmit` clean. No studio components or deploy/ files touched.
