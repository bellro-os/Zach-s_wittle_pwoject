# Deploying the CMA engine as a shared HTTP service

The warm CMA worker (`worker/cma_worker.py`) keeps the heavy sklearn import + AVM
model resident so every `/profile` and `/generate` call is warm (no ~5–12s cold
start per request). `Dockerfile.engine` packages it as a deployable service.

## Build & run

```bash
# from the repo root (C:\Users\zach\Desktop\MLS Bot or its Linux checkout)
docker build -f Dockerfile.engine -t cma-engine .

docker run --rm \
  -p 8765:8765 \
  -e CMA_WORKER_HOST=0.0.0.0 \
  -e CMA_WORKER_TOKEN=please-change-me \
  -e CMA_WORKER_REQ_TIMEOUT=120 \
  -v "$PWD/data:/app/data" \
  -v "$PWD/outputs:/app/outputs" \
  cma-engine
```

Smoke test (health is always open, no auth):

```bash
curl http://localhost:8765/healthz                       # {"ok":true,"warm":true}
curl -X POST http://localhost:8765/profile \
     -H "Authorization: Bearer please-change-me" \
     -H "Content-Type: application/json" \
     -d '{"address":"7423 Floyd Highway N"}'
```

## Required mounted data volume

The image contains **code only** — the data + model artifacts are gitignored,
large, and refreshed out-of-band, so they must be **mounted** at runtime. Without
them the worker boots but every request fails to find comps / the AVM.

| Mount target (in container)                              | What it is                         | Approx size |
|---------------------------------------------------------|------------------------------------|-------------|
| `/app/data/mls_lookup.parquet`                          | comps the CMA queries              | ~7 MB       |
| `/app/data/parcel_lookup.parquet`                       | parcel attributes                  | ~85 MB      |
| `/app/data/search_index.sqlite`                         | address typeahead (FTS5)           | ~1.1 GB     |
| `/app/outputs/mls_analytics/avm_model/regressor.joblib` | trained AVM regressor              | ~1.9 MB     |
| `/app/outputs/mls_analytics/avm_model/meta.joblib`      | AVM feature metadata               | ~15 KB      |

Simplest approach — mount the whole host `data/` (~8.8 GB) and `outputs/`
(~2.8 GB) directories as shown above. Keep them on a persistent volume so the
refresh scheduler can update them in place.

## Environment variables

All are **additive** — unset = today's behavior (localhost-only, no auth, no
request timeout).

| Var                     | Default     | Effect                                                                 |
|-------------------------|-------------|------------------------------------------------------------------------|
| `CMA_WORKER_HOST`       | `127.0.0.1` | Bind address. Set `0.0.0.0` to serve outside the container.            |
| `CMA_WORKER_PORT`       | `8765`      | Listen port (EXPOSEd in the image).                                    |
| `CMA_WORKER_TOKEN`      | _(unset)_   | When set, POST `/profile` + `/generate` require `Authorization: Bearer <token>` (401 otherwise). `/healthz` stays open. |
| `CMA_WORKER_REQ_TIMEOUT`| `0` (off)   | Per-request wall-clock budget in seconds; on exceed returns a 504-style JSON error. |
| `CHROME_PATH`           | `/usr/bin/chromium` (set in image) | Headless Chrome binary used to render the PDF. |

> Security note: because `CMA_WORKER_HOST=0.0.0.0` exposes the worker beyond
> localhost, always set `CMA_WORKER_TOKEN` (and front it with TLS) in any
> non-loopback deployment.

## Request-timeout caveat

The server is single-threaded on purpose. The `CMA_WORKER_REQ_TIMEOUT` watchdog
returns a timely 504 to the client, but it cannot hard-kill the in-flight CPU
work (Python has no safe thread cancellation); the runaway thread is left as a
daemon and the *next* request queues behind it until it finishes. For true
isolation, run multiple engine instances behind the Next app's existing spawn
fallback pool.

## Data refresh on Linux (replaces Task Scheduler)

On Windows the data refresh runs via Task Scheduler (`python -m tasks mls-hourly`,
etc. — see `tasks.py::mls_hourly`). In a container / on Linux there is no Task
Scheduler, so run the cross-platform scaffold instead:

```bash
python scripts/refresh_scheduler.py
```

It shells out to the same entrypoints on hourly / daily / weekly cadences and
logs each run (stdout + `logs/refresh_scheduler.log`):

- `python -m tasks mls-hourly`  — every hour
- `python -m tasks mls-daily`   — daily (~03:15)
- `python -m tasks mls-weekly`  — Sundays (~04:30)

If `APScheduler` is installed it uses cron triggers (override via
`REFRESH_HOURLY_CRON` / `REFRESH_DAILY_CRON` / `REFRESH_WEEKLY_CRON`); otherwise
it falls back to a stdlib while+sleep loop. Run it as a **second container /
process sharing the same mounted `data/` + `outputs/` volume** as the engine, so
refreshed parquet/sqlite land where the worker reads them. (You'll need RETS
credentials + any deps the pipeline uses present in that environment — the
scaffold is intentionally thin and just invokes the CLI.)
```
