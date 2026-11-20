from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_reports_down_dependencies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Point at closed ports so both checks fail fast without real services.
    from app.core import config, db

    monkeypatch.setenv("PLATFORM_DATABASE_URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("PLATFORM_REDIS_URL", "redis://127.0.0.1:1/0")
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/readyz")
        assert resp.status_code == 503
        assert resp.json() == {"postgres": "down", "redis": "down"}
    finally:
        config.get_settings.cache_clear()
        db.get_engine.cache_clear()
