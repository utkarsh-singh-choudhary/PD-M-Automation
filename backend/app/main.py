from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.jobs.scheduler import start_scheduler, scheduler
from app.routers import machines, pm, import_router, health, auth, audit_router, employees, reports, admin_settings, breakdowns, checklists, data_freshness, cron


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is now managed by Alembic (see backend/alembic/). We only fall
    # back to create_all() in local dev when migrations haven't been run yet,
    # so a fresh `docker compose up` still works out of the box; production
    # should run `alembic upgrade head` as a deploy step instead and this is
    # skipped there.
    if settings.ENV == "development":
        Base.metadata.create_all(bind=engine)

    # RUN_SCHEDULER_IN_API defaults to false: the daily reminder + monthly
    # report jobs run in the dedicated `pm-scheduler` process (see
    # scheduler_main.py / docker-compose.yml), not inside every API
    # replica. Running it here too would mean N API replicas all firing
    # the same cron jobs at 08:00 (Critical #2 in the production review) -
    # the notification/job idempotency guards make that non-catastrophic,
    # but it's still the wrong shape and wastes work. Only flip this on for
    # local single-process dev if you don't want to run scheduler_main.py
    # separately.
    if settings.RUN_SCHEDULER_IN_API:
        start_scheduler()
    yield
    if settings.RUN_SCHEDULER_IN_API:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Preventive Maintenance Automation System", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # from CORS_ALLOWED_ORIGINS, never "*" in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(machines.router)
app.include_router(pm.router)
app.include_router(import_router.router)
app.include_router(audit_router.router)
app.include_router(employees.router)
app.include_router(responsibilities.router)
app.include_router(reports.router)
app.include_router(breakdowns.router)
app.include_router(checklists.router)
# NOTE: admin_settings was imported above but never registered in the
# original upload - the /admin settings panel in the frontend would have
# 404'd on every call. Fixed as part of this update.
app.include_router(admin_settings.router)
app.include_router(data_freshness.router)
app.include_router(cron.router)
