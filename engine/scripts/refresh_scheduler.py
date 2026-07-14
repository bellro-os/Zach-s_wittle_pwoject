"""refresh_scheduler.py — cross-platform (Linux-friendly) data-refresh scaffold.

Replaces the Windows Task Scheduler jobs that drive the data refresh (see the
install snippet in `tasks.py::mls_hourly`). Inside a container / on a Linux VM
there is no Task Scheduler, so this small long-lived process runs the same
`python -m tasks ...` entrypoints on hourly/daily cadences.

It SHELLS OUT to the existing CLI commands (it does not import the pipeline), so
it stays a thin scaffold — the heavy lifting lives in tasks.py:

    hourly:  python -m tasks mls-hourly     (incremental pull + parquet + index + saved searches)
    daily:   python -m tasks mls-daily      (full refresh + analytics + leads + alerts)
    weekly:  python -m tasks mls-weekly     (agent directory refresh + DOM retrain)  [Sundays]

Scheduling backend:
  - If APScheduler is installed, use its BlockingScheduler (cron triggers).
  - Otherwise fall back to a documented while+sleep loop that fires each job when
    its next-due timestamp passes. Either way every run is logged.

This is a SCAFFOLD: cadences are sensible defaults, not battle-tested. Tune the
cron/interval constants below for your deployment, and make sure the data volume
is mounted (the tasks write to data/ + outputs/).

Run:
    python scripts/refresh_scheduler.py           # uses PYTHONPATH=src if needed
Env knobs (all optional):
    REFRESH_HOURLY_CRON / _DAILY_CRON / _WEEKLY_CRON   APScheduler cron exprs
    REFRESH_TASKS_CMD                                  override the base command
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

# ── logging: stdout (captured by docker/journald) + a rolling file ────────────
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [refresh_scheduler] %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(_LOG_DIR, "refresh_scheduler.log")),
    ],
)
log = logging.getLogger(__name__)

# Base command used to invoke the pipeline. `python -m tasks` matches how the
# Windows Task Scheduler jobs are documented. Override via REFRESH_TASKS_CMD
# (space-separated) e.g. "python3 -m tasks" on systems where `python` is py2.
_BASE_CMD = os.environ.get("REFRESH_TASKS_CMD", "python -m tasks").split()

# Job name -> tasks.py subcommand. These are the real command names verified in
# tasks.py (mls-hourly / mls-daily / mls-weekly).
JOBS = {
    "hourly": "mls-hourly",
    "daily": "mls-daily",
    "weekly": "mls-weekly",
}


def _run_job(name: str) -> None:
    """Shell out to `python -m tasks <subcommand>` and log the outcome."""
    sub = JOBS[name]
    cmd = [*_BASE_CMD, sub]
    log.info("START %s -> %s", name, " ".join(cmd))
    started = time.time()
    # Ensure `from mls_bot...` resolves even when launched bare (mirror the
    # PYTHONPATH=src convention used elsewhere in this repo).
    env = {**os.environ, "PYTHONPATH": os.environ.get("PYTHONPATH", "src")}
    try:
        r = subprocess.run(cmd, env=env, check=False)
        dt = time.time() - started
        if r.returncode == 0:
            log.info("DONE  %s in %.1fs", name, dt)
        else:
            log.error("FAIL  %s exit=%s after %.1fs", name, r.returncode, dt)
    except Exception as e:  # never let one bad run kill the scheduler loop
        log.exception("ERROR %s: %s", name, e)


# ── backend 1: APScheduler (preferred when available) ─────────────────────────
def _run_apscheduler() -> int:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    sched = BlockingScheduler()
    # Cron exprs are "min hour day month day_of_week". Defaults: top of every
    # hour; daily at 03:15; weekly Sunday 04:30. Override via env.
    crons = {
        "hourly": os.environ.get("REFRESH_HOURLY_CRON", "0 * * * *"),
        "daily": os.environ.get("REFRESH_DAILY_CRON", "15 3 * * *"),
        "weekly": os.environ.get("REFRESH_WEEKLY_CRON", "30 4 * * 0"),
    }
    for name, expr in crons.items():
        sched.add_job(
            _run_job, CronTrigger.from_crontab(expr), args=[name],
            id=name, max_instances=1, coalesce=True,
        )
        log.info("scheduled %-7s cron=%r", name, expr)
    log.info("APScheduler backend running; Ctrl-C to stop")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    return 0


# ── backend 2: stdlib while+sleep fallback (no third-party deps) ──────────────
def _run_sleep_loop() -> int:
    """Fire each job when its next-due timestamp passes.

    Simple fixed-interval cadences (not true cron): hourly = every 3600s,
    daily = every 24h, weekly = every 7d, measured from process start. Good
    enough for a container with no APScheduler installed. Sleeps in short ticks
    so the process stays responsive to SIGTERM.
    """
    intervals = {
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
    }
    now = datetime.now()
    # First hourly run fires ~immediately; daily/weekly wait a full interval so
    # boot doesn't trigger the heavy jobs all at once.
    next_due = {
        "hourly": now,
        "daily": now + intervals["daily"],
        "weekly": now + intervals["weekly"],
    }
    log.info("sleep-loop backend running (APScheduler not installed); Ctrl-C to stop")
    tick = 30  # seconds between due-time checks
    try:
        while True:
            now = datetime.now()
            for name, when in next_due.items():
                if now >= when:
                    _run_job(name)
                    next_due[name] = now + intervals[name]
            time.sleep(tick)
    except (KeyboardInterrupt, SystemExit):
        log.info("stopping")
    return 0


def main() -> int:
    try:
        import apscheduler  # noqa: F401  (probe only)
        return _run_apscheduler()
    except ImportError:
        return _run_sleep_loop()


if __name__ == "__main__":
    raise SystemExit(main())
