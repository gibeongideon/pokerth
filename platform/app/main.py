from fastapi import FastAPI

from app.api import health
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Poker Platform API",
        version="0.1.0",
        debug=settings.debug,
        # Interactive docs only outside production.
        docs_url=None if settings.env == "prod" else "/docs",
        redoc_url=None,
    )
    app.include_router(health.router)
    return app


app = create_app()
