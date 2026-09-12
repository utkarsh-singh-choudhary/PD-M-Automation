import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live():
    """Liveness: is the process up at all. No dependency checks - an
    orchestrator uses this to decide whether to restart the container, so
    it should only fail if the process itself is wedged."""
    return {"status": "alive"}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)):
    """Readiness: can this instance actually serve traffic. Checks the
    dependency that matters most - the database - and fails closed. An
    orchestrator uses this to decide whether to route traffic to this
    instance (unlike /health/live, this SHOULD fail during a DB outage so
    the load balancer stops sending requests here)."""
    checks = {}
    healthy = True

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        # Log the real exception server-side only - this endpoint is
        # typically reachable by a load balancer/orchestrator without
        # authentication, so it must never leak connection strings, driver
        # internals, or query text to the caller (Medium: "GET /health/ready
        # exposes database exception details").
        logger.exception("Readiness check failed: database connectivity")
        checks["database"] = "unhealthy"
        healthy = False

    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {"status": "ready" if healthy else "not_ready", "checks": checks}


@router.get("/health")
def health_legacy(db: Session = Depends(get_db)):
    """Deprecated alias kept for existing monitors/dashboards during
    migration to /health/live and /health/ready. New integrations
    (load balancer health checks, k8s probes) should use those instead -
    this endpoint doesn't distinguish liveness from readiness and doesn't
    report scheduler status, since with the scheduler moved to its own
    process (see scheduler_main.py), an API replica legitimately has no
    scheduler running and that used to be misreported as unhealthy."""
    checks = {"api": "healthy"}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        logger.exception("Legacy health check failed: database connectivity")
        checks["database"] = "unhealthy"
    return checks


@router.get("/ready")
def ready_legacy():
    """Deprecated - use /health/ready. Kept only so an unmigrated load
    balancer config doesn't 404 outright during rollout."""
    return {"status": "ready"}
