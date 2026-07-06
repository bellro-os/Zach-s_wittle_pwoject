# Deploying Compbird

One Next.js container, added to the **existing Ratifyly stack** on the Hostinger
VPS (engine + app + caddy + autoheal). Compbird reuses that stack's Python CMA
engine over HTTP — the engine is the ONLY shared piece; Compbird has its own
SQLite DB, its own sessions (`cb_session`), and its own Stripe product.

**Production is worker-only.** The dev-machine Python spawn fallback
(`MLS_BOT_ROOT` / `PYTHON_BIN`) does not exist on the VPS and must stay unset —
every engine call goes to `CMA_ENGINE_URL` (the `engine` service). If that URL
is down, CMA routes fail cleanly but nothing works, so the engine container,
the shared `CMA_WORKER_TOKEN`, and the two read-only volume mounts
(`engine-outputs` for PDFs, `engine-data` for the search index) are hard
requirements, not options.

## What persists

| Volume | Mounted at | Holds |
|---|---|---|
| `compbird-data` | `/data` | `compbird.db` (users/accounts/billing/usage) + `compbird-overrides.jsonl` |
| `ratifyly_engine-outputs` (existing, ro) | `/app/engine-outputs` | generated CMA PDFs the engine writes |
| `ratifyly_engine-data` (existing, ro) | `/app/engine-data` | `search_index.sqlite` typeahead index |

## 1. Get the code onto the VPS

```bash
git clone <compbird repo URL> /root/compbird && cd /root/compbird
```

(No GitHub remote yet? `scp`/`rsync` the folder — exclude `node_modules`,
`.next`, `.git`, `prisma/dev.db`.)

## 2. Secrets

```bash
cp .env.production.example .env.production   # fill EVERY uncommented value
chmod 600 .env.production
```

Non-obvious ones:
- `SESSION_SECRET` — `openssl rand -base64 48`. Do NOT reuse Ratifyly's.
- `CMA_WORKER_TOKEN` — copy the value from the ratifyly stack's `.env` (must match the engine's).
- `NEXT_PUBLIC_APP_URL` / `NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL` — **baked in at
  image build** (client bundles + robots/sitemap). Changing them later requires
  a rebuild, not a restart.

## 3. Wire into the stack

Two options — see the comment block in `deploy/docker-compose.compbird.yml`:

- **Option A (recommended): merge** the `compbird` service block into the
  ratifyly `docker-compose.yml` (+ `compbird-data` volume), point
  `build.context` and `env_file` at `/root/compbird`, uncomment `depends_on:
  engine`. One stack, one network, enforced startup order.
- **Option B: standalone file** — `docker compose -f
  deploy/docker-compose.compbird.yml up -d --build` after adjusting the
  external network/volume names (`docker network ls`, `docker volume ls` — the
  `ratifyly_` prefix assumes the stack's project name is `ratifyly`).

Then the vhost: append `deploy/Caddyfile.compbird` to the stack's `Caddyfile`
(replace the `{$COMPBIRD_DOMAIN:...}` placeholders with the literal domain if
you prefer), point the `compbird.com` + `www` A records at the VPS IP, and:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

## 4. Build & launch

Build ON the VPS (proven path; the image compiles better-sqlite3 for linux and
generates the linux Prisma engine during `docker build` — nothing from your
Windows machine ships). From the directory holding the compose file:

```bash
# Merge mode (build args read NEXT_PUBLIC_* from the env file):
docker compose --env-file /root/compbird/.env.production up -d --build compbird
# Standalone mode:
cd /root/compbird && docker compose --env-file .env.production -f deploy/docker-compose.compbird.yml up -d --build
```

First boot: the entrypoint runs `prisma db push` against `/data/compbird.db`
(creates it), then `node server.js` (standalone) on port 3000, non-root.
`docker compose logs -f compbird` should show the push then "Starting compbird".

## 5. Stripe webhook (once)

In the Stripe dashboard (live mode) add an endpoint:

- URL: `https://compbird.com/api/billing/webhook`
- Events: `checkout.session.completed`, `customer.subscription.created`,
  `customer.subscription.updated`, `customer.subscription.deleted`
- Put the signing secret in `.env.production` as `STRIPE_WEBHOOK_SECRET`,
  plus `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID`, then
  `docker compose up -d compbird` to reload env (no rebuild needed — these are
  runtime vars).

## 6. Verify

```bash
docker compose ps                       # compbird: Up (healthy)
curl -fsS https://compbird.com/ -o /dev/null -w '%{http_code}\n'          # 200
curl -fsS https://compbird.com/robots.txt                                # sitemap: https://compbird.com/...
curl -fsS https://compbird.com/api/compbird/markets | head -c 200        # {"ok":true,... or markets:[]
curl -fsS 'https://compbird.com/api/compbird/search?q=walnut' | head -c 200  # results ⇒ search-index mount OK
curl -sI  https://compbird.com/api/compbird/pdf/CMA_compbird_x.pdf | head -1 # 401 (auth wall, not 500)
```

Then the real smoke test: sign up, run a comp report in the studio, download
the PDF (exercises engine → outputs volume → pdf route end-to-end).

## Rollback

```bash
docker compose stop compbird            # take it offline (Caddy will 502 just this vhost)
# or roll back code:
cd /root/compbird && git checkout <last-good-sha>
docker compose --env-file .env.production up -d --build compbird
```

The DB volume is untouched by rollbacks. `prisma db push` on an OLDER schema
can drop newer columns — if a release added columns, back up the volume before
rolling back (below). Nothing else on the box (ratifyly app/engine/caddy) is
affected by stopping or rebuilding compbird.

## Backups (the SQLite holds accounts + billing state — back it up)

```bash
docker run --rm -v compbird-data:/d -v "$PWD/backups":/b alpine \
  tar czf /b/compbird-$(date +%F).tgz -C /d .
```

(Volume name may be project-prefixed, e.g. `ratifyly_compbird-data` in merge
mode — check `docker volume ls`.) Cron it alongside the ratifyly `app-data`
backup.

## Troubleshooting

- **Typeahead/search returns errors** → the `engine-data` volume isn't mounted
  or `SEARCH_INDEX_PATH` is wrong; there is NO Python fallback in production.
- **Report PDF downloads 404** → `engine-outputs` mount / `CMA_OUTPUTS_DIR`
  mismatch, or the engine and compbird aren't sharing the same outputs volume.
- **Engine calls fail** (`cma-worker 401/timeout`) → `CMA_WORKER_TOKEN` doesn't
  match the engine's, or the containers aren't on the same network (Option B:
  check the external network name).
- **Wrong domain in sitemap/OG/footer email** → `NEXT_PUBLIC_*` build args were
  missing at build; rebuild with `--env-file .env.production`.
- **`prisma db push` fails on boot** → `DATABASE_URL` not pointing at the
  writable volume (`file:/data/compbird.db`) or the volume lost its `node`
  ownership (recreate: the image seeds `/data` owned by uid 1000).
