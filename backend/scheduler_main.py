"""
Entrypoint for the dedicated scheduler/worker process (the `pm-scheduler`
service in docker-compose.yml), separate from the API process.

Why this exists: previously APScheduler started inside every FastAPI
process (see main.py's old lifespan handler). That's wrong once you run
more than one API replica behind a load balancer - every replica would fire
the same daily-reminder and monthly-report cron jobs at the same time.
Notification/job idempotency (NotificationLog.idempotency_key,
ScheduledJob(job_type, period)) makes that non-catastrophic, but it's still
wasted work and the wrong architecture - a single dedicated process should
own "what runs when," while API replicas stay purely request/response and
horizontally scalable.

Run with:
    python scheduler_main.py
or as its own container - see the `pm-scheduler` service in
docker-compose.yml, which runs this instead of uvicorn.

This process does NOT serve HTTP traffic. If you need a health check for
it in your orchestrator, check that the process is still running (it holds
the scheduler thread alive) rather than expecting a port.
"""
import logging
import signal
import time

from app.jobs.scheduler import start_scheduler, scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pm-scheduler")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("Received signal %s, shutting down scheduler...", signum)
    _shutdown = True


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("Starting PM scheduler process...")
    start_scheduler()
    log.info("Scheduler started. Jobs: %s", [j.id for j in scheduler.get_jobs()])

    while not _shutdown:
        time.sleep(1)

    scheduler.shutdown(wait=True)
    log.info("Scheduler stopped cleanly.")


if __name__ == "__main__":
    main()
