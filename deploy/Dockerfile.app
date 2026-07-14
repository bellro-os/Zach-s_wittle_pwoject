# syntax=docker/dockerfile:1
#
# deploy/Dockerfile.app — Compbird Next.js app for RAILWAY.
#
# Railway builds this from the Compbird repo (build context = repo root).
# Point the service at it via deploy/railway.app.json (build.dockerfilePath)
# or the RAILWAY_DOCKERFILE_PATH service variable — see deploy/README.md.
#
# Recipe lineage: the proven Ratifyly/VPS image (node:20-slim, native
# toolchain for better-sqlite3, prisma generate at build, build-heap ceiling),
# shipping Next's STANDALONE output (next.config.ts: output "standalone").
#
# Railway specifics baked in here:
#   * PORT   — Railway injects PORT at runtime; Next's standalone server.js
#              reads it (the ENV below is only a local-run default).
#   * HOSTNAME="::" — dual-stack bind (IPv4 + IPv6). Railway's internal mesh
#              is IPv6; "::" covers both edge and private traffic.
#   * No Docker HEALTHCHECK — Railway IGNORES it. The deploy-gating health
#     probe is railway.app.json → deploy.healthcheckPath = /api/health.
#   * No USER directive (runs as root) — Railway mounts the service volume
#     root-owned; node:20-slim has no gosu/su-exec to drop privileges after
#     fixing ownership, and a non-root user cannot chown the mount. Container
#     isolation is Railway's, per-service. (The old VPS image ran as `node`;
#     this is a deliberate, documented divergence.)
#
# The app is WORKER-ONLY in production: it reaches the Python CMA engine over
# HTTP (CMA_ENGINE_URL=http://engine.railway.internal:8765 — the private-mesh
# hostname of the engine service). The local Python spawn fallback is
# intentionally absent — MLS_BOT_ROOT / PYTHON_BIN stay unset and there is no
# Python engine code in this image.

# ─── base ─────────────────────────────────────────────────────
FROM node:20-slim AS base
WORKDIR /app
# Prisma needs openssl + ca-certificates at build and run time.
RUN apt-get update \
  && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# ─── deps ─────────────────────────────────────────────────────
FROM base AS deps
# better-sqlite3 has no prebuilt binary for this Node/libc combo, so `npm ci`
# compiles it from source via node-gyp — which needs Python + a C/C++ toolchain
# (the sibling Ratifyly deploy hit exactly this; bake the toolchain in).
# Build-time only: the runner copies the already-compiled module, so the
# runtime image stays slim.
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 make g++ \
  && rm -rf /var/lib/apt/lists/*
COPY package.json package-lock.json ./
RUN npm ci

# ─── builder ──────────────────────────────────────────────────
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* values are inlined into the client bundles AND into the
# build-time-prerendered robots.txt/sitemap.xml — runtime env CANNOT change
# them. Railway exposes service variables to Dockerfile builds as build args
# for every name declared with ARG, so set these as SERVICE VARIABLES in the
# Railway dashboard; changing one requires a REDEPLOY (rebuild), not a restart.
ARG NEXT_PUBLIC_APP_URL
ARG NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL
ENV NEXT_PUBLIC_APP_URL=${NEXT_PUBLIC_APP_URL}
ENV NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL=${NEXT_PUBLIC_COMPBIRD_CONTACT_EMAIL}
# Ad pixels (optional — empty ⇒ pixels + consent banner never render).
ARG NEXT_PUBLIC_META_PIXEL_ID
ARG NEXT_PUBLIC_GOOGLE_ADS_ID
ARG NEXT_PUBLIC_GOOGLE_ADS_SIGNUP_LABEL
ARG NEXT_PUBLIC_GOOGLE_ADS_SUBSCRIBE_LABEL
ENV NEXT_PUBLIC_META_PIXEL_ID=${NEXT_PUBLIC_META_PIXEL_ID}
ENV NEXT_PUBLIC_GOOGLE_ADS_ID=${NEXT_PUBLIC_GOOGLE_ADS_ID}
ENV NEXT_PUBLIC_GOOGLE_ADS_SIGNUP_LABEL=${NEXT_PUBLIC_GOOGLE_ADS_SIGNUP_LABEL}
ENV NEXT_PUBLIC_GOOGLE_ADS_SUBSCRIBE_LABEL=${NEXT_PUBLIC_GOOGLE_ADS_SUBSCRIBE_LABEL}

RUN npx prisma generate
# `next build` can exceed Node's default heap (same OOM class the sibling
# app's CI hit: "Ineffective mark-compacts near heap limit"). Ceiling with
# headroom — a max, not a reservation.
RUN NODE_OPTIONS="--max-old-space-size=4096" npm run build

# ─── runner ───────────────────────────────────────────────────
FROM base AS runner
ENV NODE_ENV=production
# Local-run default only — Railway injects PORT at runtime and the standalone
# server.js listens on it. Do NOT pin PORT as a Railway service variable.
ENV PORT=3000
# Dual-stack bind: Railway's edge + private mesh both reach the container;
# Node's listener on "::" accepts IPv4-mapped traffic too.
ENV HOSTNAME=::

# Standalone server + its traced node_modules (includes the linux-compiled
# better-sqlite3 binary and @prisma/client) + static assets. No public/ dir in
# this repo (icons/OG images are generated routes), so nothing else to copy.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Generated Prisma client + its linux query-engine binary. The standalone
# trace usually carries this, but the custom generator output
# (src/generated/prisma) is a known tracing blind spot — an explicit copy makes
# engine resolution deterministic (the client probes <cwd>/src/generated/prisma).
COPY --from=builder /app/src/generated ./src/generated

# Prisma CLI for the boot-time `db push` (schema sync against the volume DB).
# Copied from the builder so versions stay lockfile-pinned; @prisma/* includes
# the linux schema-engine the CLI shells out to.
COPY --from=builder /app/node_modules/prisma ./node_modules/prisma
COPY --from=builder /app/node_modules/@prisma ./node_modules/@prisma
COPY --from=builder /app/prisma ./prisma

# Boot scripts + the data-sync seam. deploy/ is small (text only) and carries:
#   deploy/entrypoint.app.sh              — this image's PID-1 (below)
#   deploy/data-sync/entrypoint.app.sh    — OPTIONAL hook owned by the
#       data-sync kit (search-index pull/refresh); entrypoint.app.sh hands off
#       to it when present. Requires deploy/ NOT being .dockerignore'd.
COPY --from=builder /app/deploy ./deploy
# Strip CRLF (Windows checkouts) + mark executable; prepare the volume mount
# point (Railway mounts the service volume here — see deploy/README.md).
RUN find ./deploy -name '*.sh' -exec sed -i 's/\r$//' {} + \
  && find ./deploy -name '*.sh' -exec chmod +x {} + \
  && mkdir -p /data

EXPOSE 3000

# NOTE: no HEALTHCHECK on purpose — Railway ignores Docker healthchecks.
# Deploy gating: railway.app.json → deploy.healthcheckPath = /api/health
# (200 only when the SQLite DB answers; 503 otherwise).

CMD ["./deploy/entrypoint.app.sh"]
