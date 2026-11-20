from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    auth,
    dev,
    health,
    internal,
    me,
    tables,
    wallet,
    webhooks,
    withdrawals,
)
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    for module in (health, auth, me, wallet, withdrawals, tables, webhooks, internal, admin):
        app.include_router(module.router)
    if settings.env == "local":
        app.include_router(dev.router)
    return app


app = create_app()
