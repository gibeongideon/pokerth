"""Kubernetes probes.

/healthz  - liveness: the process is up. No dependencies checked.
/readyz   - readiness: Postgres and Redis answer. Returns 503 otherwise.
"""

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception:
        checks["postgres"] = "down"
    try:
        redis = Redis.from_url(get_settings().redis_url)
        async with redis:
            await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"

    if any(v != "ok" for v in checks.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return checks
