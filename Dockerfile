# syntax=docker/dockerfile:1
#
# Compbird — production image. Mirrors the proven Ratifyly app recipe
# (node:20-slim, native toolchain for better-sqlite3, prisma generate at build,
# build-heap ceiling) but ships Next's STANDALONE output and runs as non-root.
#
# The app is WORKER-ONLY in production: it reaches the Python CMA engine over
# HTTP (CMA_ENGINE_URL, e.g. http://engine:8765 on the compose network). The
# local Python spawn fallback is intentionally absent — MLS_BOT_ROOT/PYTHON_BIN
# stay unset and there is no Python engine code in this image.

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
# compiles it from source via node-gyp — which needs Python + a C/C++ toolchain.
# Build-time only: the runner copies the already-compiled module, so the runtime
# image stays slim.
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
# them. They must be supplied here as build args (compose passes them from
# .env.production via build.args).
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
# `next build` can exceed Node's default heap (same OOM class the sibling app's
# CI hit: "Ineffective mark-compacts near heap limit"). Ceiling with headroom —
# a max, not a reservation; safe on a modest VPS.
RUN NODE_OPTIONS="--max-old-space-size=4096" npm run build

# ─── runner ───────────────────────────────────────────────────
FROM base AS runner
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Standalone server + its traced node_modules (includes the linux-compiled
# better-sqlite3 binary and @prisma/client) + static assets. No public/ dir in
# this repo (icons/OG images are generated routes), so nothing else to copy.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

# Generated Prisma client + its linux query-engine binary. The standalone trace
# usually carries this, but the custom generator output (src/generated/prisma)
# is a known tracing blind spot — an explicit copy makes engine resolution
# deterministic (the client probes <cwd>/src/generated/prisma).
COPY --from=builder --chown=node:node /app/src/generated ./src/generated

# Prisma CLI for the boot-time `db push` (schema sync against the volume DB).
# Copied from the builder so versions stay lockfile-pinned; @prisma/* includes
# the linux schema-engine the CLI shells out to.
COPY --from=builder --chown=node:node /app/node_modules/prisma ./node_modules/prisma
COPY --from=builder --chown=node:node /app/node_modules/@prisma ./node_modules/@prisma
COPY --from=builder --chown=node:node /app/prisma ./prisma

COPY --chown=node:node docker-entrypoint.sh ./docker-entrypoint.sh
# Strip CRLF in case the file was checked out with Windows line endings, then
# prepare the SQLite volume mount point owned by the runtime user.
RUN sed -i 's/\r$//' docker-entrypoint.sh \
  && chmod +x docker-entrypoint.sh \
  && mkdir -p /data \
  && chown node:node /data

USER node
EXPOSE 3000

# node:20-slim has no wget/curl — use Node's global fetch. "/" is the landing
# page: always present, no auth, no engine dependency, no rate limit.
HEALTHCHECK --interval=30s --timeout=5s --retries=5 --start-period=40s \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["./docker-entrypoint.sh"]
