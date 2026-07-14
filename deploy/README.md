# Compbird — production deploy on RAILWAY

Two Railway services in one project: **engine** (Python CMA worker — warm,
six production flags, Chromium PDF) + **app** (Next.js standalone, SQLite,
Stripe). Railway provides TLS, the public domain, per-service Docker builds,
private networking between services, and ONE persistent volume per service.
No compose, no Caddy, no SSH-push — data sync goes through S3-compatible
object storage (Cloudflare R2 assumed; parameterized by `deploy/data-sync/`).

```
internet ──https──▶ Railway edge ──▶ app (Next standalone, PORT injected)
                                       │ volume /data: compbird.db +
                                       │   search_index.sqlite + overrides.jsonl
                                       │ HTTP + bearer token, private mesh (IPv6)
                                       ▼
                     engine.railway.internal:8765 (warm CMA worker)
                                       │ volume /data: data/ (parquets) +
                                       │   outputs/ (models, PDFs) + cache/ (AI)
Windows pipeline box ──hourly──▶ R2 bucket ──▶ puller inside each container
  ("MLS Bot Hourly" task)                       (deploy/data-sync/)
```

Files in this directory:

| File | Purpose |
|---|---|
| `Dockerfile.app` | app image (context = Compbird repo root) |
| `Dockerfile.engine` | engine image — **canonical copy**; ships in the ENGINE repo (below) |
| `entrypoint.app.sh` | app boot: `prisma db push` → data-sync hook seam → `node server.js` |
| `entrypoint.engine.sh` | engine boot — **canonical copy**: volume symlink layout → data-sync supervisor seam → worker |
| `railway.app.json` | app service config-as-code (dockerfilePath, healthcheck, restarts) |
| `railway.engine.json` | engine service config-as-code — **canonical copy**; ships in the engine repo as `railway.json` |
| `ops/`, `data-sync/` | operations + the hourly data pipeline — see their own READMEs (separately owned) |

> **Superseded:** the old single-VPS stack (docker-compose + Caddyfile) was
> deleted from this directory when the launch pivoted to Railway. It survives
> in git history if ever needed.

---

## 0. The two-repo reality

The app (this repo) and the engine (`MLS Bot`) are SEPARATE git repos.
Railway builds each service from a GitHub repo, so the simplest layout — and
the **recommended** one — is:

- **app service** ← the Compbird GitHub repo (this one)
- **engine service** ← the MLS Bot GitHub repo

The engine's deploy files are AUTHORED here (single source of truth for the
whole pipeline) and SHIPPED there. Sync whenever the canonical copies change:

```powershell
# from C:\Users\zach\Desktop\Compbird
Copy-Item deploy\Dockerfile.engine      "..\MLS Bot\deploy\Dockerfile.engine"
Copy-Item deploy\entrypoint.engine.sh   "..\MLS Bot\deploy\entrypoint.engine.sh"
Copy-Item deploy\railway.engine.json    "..\MLS Bot\railway.json"
Copy-Item deploy\data-sync\* -Recurse   "..\MLS Bot\deploy\data-sync\" -Force   # puller seam
```

(Alternative for the git-purist: maintain `MLS Bot/deploy/` as a `git subtree`
of `Compbird/deploy/`. More ceremony, same bytes — start with the copy.)

Neither repo has a GitHub remote yet (both are local-only). Create two
**private** GitHub repos and push. The engine's `.gitignore`/`.dockerignore`
already exclude the multi-GB `data/` + `outputs/` — the repo/image is code
only; verify the first push is code-sized, not gigabytes.

## 1. Create the Railway project + engine service

1. Railway → New Project → Deploy from GitHub repo → **MLS Bot** repo.
2. Railway reads `railway.json` at the repo root automatically →
   `deploy/Dockerfile.engine`, healthcheck `/healthz`, 600 s timeout.
3. **Volume:** service → Settings → Volumes → attach one, **mount path
   `/data`**. Size: the steady state is ~150 MB of parquets/models/caches +
   generated PDFs that accumulate — **1 GB is comfortable** (grow later; the
   entrypoint lays out `/data/{data,outputs,cache}` and symlinks them to
   `/app/*` on boot).
4. **Region:** pick one and use the SAME region for the app service (private
   networking is per-project; same-region keeps app→engine latency down).
5. **Networking:** do NOT add a public domain to the engine. Private mesh
   only: the app reaches it at `http://engine.railway.internal:8765`. Name the
   service `engine` so that hostname is literally correct.
6. **Variables** (service → Variables) — full table in §7. Minimum to boot:
   `ANTHROPIC_API_KEY`, `CMA_WORKER_TOKEN`, and the six CMA flags (baked into
   the image as defaults, but set them explicitly so the dashboard shows the
   certified posture).

**IPv6 note (load-bearing):** Railway's private mesh is IPv6-only. The image
sets `CMA_WORKER_HOST=::` (dual-stack) and the worker carries a small additive
patch (`worker/cma_worker.py`: `address_family = AF_INET6` when the host is an
IPv6 literal). Do not "simplify" the host back to `0.0.0.0` — the bind will
succeed and the service will be silently unreachable from the app.

First deploy: expect the healthcheck to sit "waiting" for a while — the worker
only listens after warm-up (sklearn import + AVM joblib load), and on an empty
volume the AVM warm logs a non-fatal failure. `/healthz` goes 200 regardless;
requests fail until data is seeded (§3).

## 2. Create the app service

1. Same project → New Service → GitHub repo → **Compbird** repo.
2. Settings → Config-as-code file path: **`deploy/railway.app.json`**
   (it is not at the repo root, so this one is a manual click) →
   `deploy/Dockerfile.app`, healthcheck `/api/health`.
3. **Volume:** attach one, **mount path `/data`**. Size: the SQLite DB is
   tiny, but the volume also carries `search_index.sqlite` (~1.1 GB — the
   typeahead index the app opens with better-sqlite3; production has NO Python
   fallback) — **attach ≥ 2 GB**.
4. **Variables** — full table in §7. `PORT` is injected by Railway; the
   standalone server listens on it. Note `NEXT_PUBLIC_*` are consumed at
   BUILD time (Railway passes service variables to the Docker build for every
   name the Dockerfile declares as `ARG`): changing one needs a redeploy, not
   a restart.
5. First deploy boots, `prisma db push` creates `/data/compbird.db` on the
   fresh volume, `/api/health` returns 200 — the site is up on the
   `*.up.railway.app` domain even before engine data lands (CMA calls will
   error cleanly until §3).

## 3. First data seed (volumes start EMPTY)

The images contain code only. Both services read data files that are
gitignored and live on their volumes, so the FIRST deploy needs a seed before
first traffic. The mechanism is the same one that keeps data fresh forever
after: **the Windows box pushes to R2 hourly; a puller inside each container
fetches + atomically swaps** (owned by `deploy/data-sync/` — see its README
for bucket layout, credentials, and the puller's env).

Boot-time seams this pipeline guarantees (already wired in the entrypoints):

- **engine:** `entrypoint.engine.sh` execs `deploy/data-sync/entrypoint.sh`
  when present. That script is the container's supervisor: initial pull from
  R2 → start the worker → hourly pull loop. No kit present ⇒ the worker starts
  directly and the entrypoint prints loud `!! WARNING` lines for missing data.
- **app:** `entrypoint.app.sh` sequence is `litestream restore` (if a replica
  is configured; BEFORE the push so a fresh volume can be recovered) →
  `prisma db push` → **calls** `deploy/data-sync/entrypoint.app.sh` when present
  (blocking search-index seed; it RETURNS, it does NOT start the server) →
  starts the server UNDER Litestream (`litestream replicate -exec "node
  server.js"`) when `LITESTREAM_REPLICA_URL` is set, else plain `node server.js`.

What must land where:

| File (from the Windows `MLS Bot` checkout) | Service:path | Size |
|---|---|---|
| `data/mls_lookup.parquet` | engine `/data/data/` | ~7 MB — THE hourly comp pool |
| `data/parcel_lookup.parquet` | engine `/data/data/` | ~85 MB |
| `data/market_index.parquet` | engine `/data/data/` | ~11 KB (`CMA_AVM_INDEX_DEBIAS`) |
| `data/cma_regions.json` | engine `/data/data/` | ~2 KB |
| `data/supplemental_listings.parquet` | engine `/data/data/` | ~13 MB (opt-in pool) |
| `outputs/mls_analytics/{avm,dom,price_cut}_model/*.joblib` | engine `/data/outputs/mls_analytics/…` | ~9 MB |
| `data/cma_blind_cache.json`, `data/cma_hygiene_cache.json` | engine `/data/cache/` | KBs — optional but preserves blind-anchor continuity |
| `data/search_index.sqlite` | **app** `/data/` | ~1.1 GB — typeahead FTS |

Manual fallback / spot repair (no SSH keys on Railway, but the CLI can shell
into a live deployment): `railway ssh` into the service, then download from a
presigned R2 URL, e.g.
`curl -fsSL "<presigned-url>" -o /data/data/mls_lookup.parquet.tmp && mv /data/data/mls_lookup.parquet.tmp /data/data/mls_lookup.parquet`
(always the tmp+`mv` dance — the engine reads parquets per-request).

**Freshness claim:** the studio stamps "MLS data — refreshed hourly". That is
only TRUE if the Windows Task Scheduler job pushes to R2 every hour AND the
engine puller applies it. Watch it end-to-end via `deploy/ops/` monitoring and
the puller's own status output. Search-index caveat: the app holds
`search_index.sqlite` open; after the (roughly daily) index swap the app must
restart/redeploy to serve the new inode — the data-sync kit documents its
hook for this.

## 4. Custom domain + DNS

App service → Settings → Networking → Custom Domain → `compbird.com` (and
`www.compbird.com` if wanted; Railway serves both, TLS auto-provisioned).
At the DNS host: apex via CNAME-flattening/ALIAS → the `*.up.railway.app`
target Railway shows; `www` as a plain CNAME. Then set/confirm
`NEXT_PUBLIC_APP_URL=https://compbird.com` **and redeploy the app** (build-time
value: metadataBase, robots.txt, sitemap, OG URLs).

## 5. Stripe webhook (once)

Stripe dashboard (live mode) → add endpoint
`https://compbird.com/api/billing/webhook` with events
`checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted`.
Put the signing secret in the app service variables as
`STRIPE_WEBHOOK_SECRET` (with `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID`).
Runtime vars → a restart (Railway applies on save) suffices, no rebuild.

## 6. Verify

```bash
curl -fsS https://compbird.com/ -o /dev/null -w '%{http_code}\n'              # 200
curl -fsS https://compbird.com/api/health                                     # {"ok":true,...,"db":"up"}
curl -fsS https://compbird.com/robots.txt | head -2                           # sitemap: https://compbird.com/...
curl -fsS 'https://compbird.com/api/compbird/search?q=walnut' | head -c 200   # results ⇒ search index seeded
railway logs --service engine | grep "cma_worker"                             # "[cma_worker] ready on :::8765 (auth=token-required, ...)"
```

Then the real smoke test: sign up, run a comp report in the studio, and
confirm the report shows the Match scores and the tuning disclosure (proves
the six flags are live). **See the known gap below before treating PDF
download as passing.**

## 7. Environment variables

`.env.production.example` at the repo root mirrors these tables with comments;
on Railway they are entered as SERVICE VARIABLES (there is no env file).

**app service** (Compbird repo):

| Var | Value / note |
|---|---|
| `DATABASE_URL` | `file:/data/compbird.db` — SQLite on the service volume |
| `SESSION_SECRET` | `openssl rand -base64 48`; min 16 chars; never reuse another app's |
| `CMA_ENGINE_URL` | `http://engine.railway.internal:8765` — read by `src/lib/cma/worker.ts:25` (precedence: `COMPBIRD_ENGINE_URL` > `CMA_ENGINE_URL` > `CMA_WORKER_URL` > localhost default) |
| `CMA_WORKER_TOKEN` | `openssl rand -hex 32`; set the SAME value on both services |
| `SEARCH_INDEX_PATH` | `/data/search_index.sqlite` — typeahead index on the app volume |
| `COMPBIRD_OVERRIDES_PATH` | `/data/compbird-overrides.jsonl` — override audit trail, persistent |
| `CMA_OUTPUTS_DIR` | see **Known gap #1** — no shared filesystem exists on Railway |
| `NEXT_PUBLIC_APP_URL` | `https://compbird.com` — **build-time** (redeploy on change) |
| `NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL` | `support@compbird.com` — build-time |
| `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_ANNUAL` | optional at boot; billing degrades to "not configured" until set |
| `RESEND_API_KEY`, `MAIL_FROM` | optional; email sends are suppressed-and-logged until set |
| `GOOGLE_MAPS_API_KEY` | optional — Street View photos |
| `NEXT_PUBLIC_META_PIXEL_ID`, `META_CAPI_ACCESS_TOKEN`, `NEXT_PUBLIC_GOOGLE_ADS_ID`, `NEXT_PUBLIC_GOOGLE_ADS_SIGNUP_LABEL`, `NEXT_PUBLIC_GOOGLE_ADS_SUBSCRIBE_LABEL` | optional ad pixels; `NEXT_PUBLIC_*` are build-time |
| `COMPBIRD_LISTINGS_PARQUET` | optional opt-in supplemental pool — path AS SEEN BY THE ENGINE: `/app/data/supplemental_listings.parquet` |
| `PORT` | DO NOT SET — Railway injects it |
| `MLS_BOT_ROOT`, `PYTHON_BIN` | MUST stay unset — the Python spawn fallback does not exist in this image |

**engine service** (MLS Bot repo):

| Var | Value / note |
|---|---|
| `CMA_WORKER_HOST` | `::` — dual-stack; REQUIRED (IPv6-only private mesh). Image default; set explicitly for visibility |
| `CMA_WORKER_PORT` | `8765` (image default) |
| `PORT` | `8765` — aligns Railway's healthcheck/port detection with the worker |
| `CMA_WORKER_TOKEN` | same value as the app's |
| `CMA_WORKER_REQ_TIMEOUT` | `180` — per-request watchdog (s) on a wedged Chromium render |
| `ANTHROPIC_API_KEY` | **required** — comp hygiene + blind ensemble; absent ⇒ silent degradation off the certified posture (entrypoint warns) |
| **`CMA_COMP_SCORE_SURFACE`** | **`1`** — six production flags, verbatim. Baked as image defaults; set them as service variables anyway so the dashboard shows the certified posture. NOT tunables — removing any one changes valuations/serialization vs. what was certified |
| **`CMA_COMP_TUNING_DISCLOSURE`** | **`1`** |
| **`CMA_AVM_INDEX_DEBIAS`** | **`1`** |
| **`CMA_PRIOR_SALE_GUARDS`** | **`1`** |
| **`CMA_BLIND_ENSEMBLE`** | **`1`** |
| **`CMA_OVERRIDE_DAMPING`** | **`1`** |
| `CMA_HYGIENE_MODEL`, `CMA_BLIND_MODEL` | optional model overrides (engine defaults: Haiku) |
| `CMA_BLIND_CACHE`, `CMA_HYGIENE_CACHE` | defaulted by the entrypoint to `/data/cache/…` — override only with volume paths |
| R2 credentials / bucket for the puller | owned by `deploy/data-sync/` — see its README for exact names |

## 8. Upgrade + rollback

- **Upgrade:** push to the linked branch → Railway rebuilds + redeploys that
  service. Healthcheck gates cutover (old deployment serves until the new one
  is healthy). Engine changes: remember the canonical-copy sync (§0) if a
  deploy/ file changed.
- **Rollback:** service → Deployments → previous deployment → Redeploy/
  Rollback. Volumes are untouched. **Caveat:** the app entrypoint runs
  `prisma db push` on every boot — rolling back past a schema change can drop
  columns the newer release added. If the bad release changed the schema,
  back up the DB first (`railway ssh` → copy `/data/compbird.db` out via R2,
  or use `deploy/ops/`).
- **Env-only change:** edit the variable → Railway restarts the service
  (redeploy needed only for `NEXT_PUBLIC_*`).

## Known gaps — read before launch

1. **PDF download is cross-service broken on Railway (launch blocker until
   addressed).** The engine writes rendered PDFs to ITS filesystem
   (`/app/outputs` → engine volume); the app's
   `/api/compbird/pdf/[name]` streams from `CMA_OUTPUTS_DIR` on ITS OWN
   filesystem, and the generate route renames the fresh PDF there
   (`src/app/api/compbird/generate/route.ts` ~line 219). On the VPS both
   containers mounted the same `engine-outputs` volume; Railway volumes are
   NOT shareable between services, and there is no code path that fetches the
   PDF over HTTP. Net effect as-is: report generation succeeds and returns
   values, but the download 404s (and the anti-enumeration rename silently
   no-ops). Options, smallest-change first:
   - worker grows a token-gated `GET /outputs/<basename>` (+ tokenized rename
     at render time) and the app's pdf route falls back to proxying the
     engine when the local file is absent — small, contained code change in
     both repos (NOT done here; deploy-config cannot fix it);
   - or the engine uploads finished PDFs to R2 and the app streams from R2;
   - or (architecture change) co-locate worker + app in one service sharing
     one volume — solves outputs AND the search index, at the cost of the
     locked two-service shape.
   Until one lands, leave `CMA_OUTPUTS_DIR` unset (reads fail as clean 404s,
   never 500s) and treat PDF download as a known-red smoke test.
2. **Worker IPv6 bind.** Already patched additively in
   `worker/cma_worker.py` + verified (IPv4 defaults byte-identical). If that
   patch is ever reverted, private networking silently breaks — see §1.
3. **Search-index reopen.** The app holds the FTS index open; a daily index
   swap needs an app restart (Railway: Deployments → Restart) — the data-sync
   kit owns automating this.
4. **`/api/health` is DB-only.** It does not probe the engine, so the app can
   be "healthy" with a cold/empty engine. Watch the engine's own `/healthz`
   (Railway healthcheck + `deploy/ops/` monitoring).

## Image-size + resource expectations (honest)

| Image | Base | Expect |
|---|---|---|
| app | node:20-slim | **~0.8–1.2 GB** (standalone server + traced node_modules incl. compiled better-sqlite3 + full Prisma CLI for boot-time `db push` — the CLI alone is ~200 MB) |
| engine | python:3.12-slim | **~2.0–2.5 GB** (Chromium + fonts ~450 MB; numpy/scipy/sklearn/pandas/duckdb wheels ~1.2 GB; source ~50 MB) |

Runtime memory: engine ~1.5–2.5 GB warm (sklearn + DuckDB + a Chromium
render) — set restart alerts accordingly; app comfortably under 1 GB
(`NODE_OPTIONS=--max-old-space-size=1024` in the entrypoint). Volumes: app
≥ 2 GB (search index dominates), engine ≥ 1 GB. Egress: PDFs/reports are
small; the hourly R2 → engine pull (~7 MB/h steady state) is the main mover.
