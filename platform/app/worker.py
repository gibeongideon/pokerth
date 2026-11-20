"""Celery worker and beat schedule.

Run locally:
    celery -A app.worker worker --loglevel=info
    celery -A app.worker beat --loglevel=info
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import Celery
from celery.schedules import crontab
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import jobs
from app.core.config import get_settings
from app.services.paystack import get_paystack

celery_app = Celery("platform", broker=get_settings().redis_url)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        "expire-stale-deposits": {
            "task": "app.worker.expire_stale_deposits",
            "schedule": 300.0,
        },
        "reconcile-deposits-daily": {
            "task": "app.worker.reconcile_deposits",
            "schedule": crontab(hour=0, minute=30),
        },
    },
)


def _run[T](job: Callable[[async_sessionmaker[Any]], Awaitable[T]]) -> T:
    """Each task gets its own engine/event loop; Celery workers are sync."""

    async def main() -> T:
        engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        try:
            return await job(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(main())


@celery_app.task(name="app.worker.expire_stale_deposits")
def expire_stale_deposits() -> dict[str, int]:
    return _run(lambda s: jobs.expire_stale_deposits(s, get_paystack()))


@celery_app.task(name="app.worker.reconcile_deposits")
def reconcile_deposits() -> dict[str, Any]:
    yesterday = datetime.now(UTC) - timedelta(days=1)
    return _run(lambda s: jobs.reconcile_deposits(s, get_paystack(), yesterday))
